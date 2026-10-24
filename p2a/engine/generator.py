"""Hypothesis -> grounded prompt -> candidates -> static validation -> targeted repair."""
from __future__ import annotations

import copy
import json
import math
import random
import re
from dataclasses import dataclass, field

from ..brain.catalog import row_to_field
from ..brain.settings import allowed_values, validate_settings
from ..fastexpr import Analysis, Issue, analyze, to_source
from ..fastexpr.ast import Call, walk
from ..knowledge import BM25, doc_snippets, paper_excerpts, rank_datasets, shortlist_fields
from ..llm import LLMError
from ..util import console, esc, stable_hash
from .context import Context
from .lifecycle import Lifecycle, family_key, shape_library
from .playbook import playbook_text
from .routes import pyramid_of, route_of, route_text
from .grounding import (constraints_text, exemplar_text, field_lines, grouping_text, hypothesis_query,
                        hypothesis_text, operator_reference, render, scope_text, settings_text)

_FIELD_LIKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")  # field ids contain underscores

CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "parent_id": {"type": "integer"},
                    "expression": {"type": "string"},
                    "neutralization": {"type": "string"},
                    "decay": {"type": "integer"},
                    "truncation": {"type": "number"},
                    "idea": {"type": "string"},
                    "rationale_data": {"type": "string"},
                    "rationale_operators": {"type": "string"},
                    "shape": {"type": "string"},
                },
                "required": ["expression", "idea", "rationale_data", "rationale_operators"],
            },
        }
    },
    "required": ["candidates"],
}


def _has_candidates(obj) -> str | None:
    if isinstance(obj, dict) and isinstance(obj.get("candidates"), list) and obj["candidates"]:
        if all(isinstance(c, dict) and isinstance(c.get("expression"), str) for c in obj["candidates"]):
            return None
    return "JSON lacks a non-empty 'candidates' list with 'expression' strings"


@dataclass
class Candidate:
    raw: dict
    expression: str
    analysis: Analysis
    settings: dict
    description: str = ""
    notes: list[str] = field(default_factory=list)
    origin: str = "llm"
    parent_id: int | None = None
    model: str | None = None
    skip: str | None = None
    equivalent: str = ""          # canonical code with no-op transforms removed (duplicate detection)

    @property
    def ok(self) -> bool:
        return self.analysis.ok

    @property
    def payload_hash(self) -> str:
        return stable_hash({"regular": self.equivalent or self.analysis.canonical, "settings": self.settings})


def equivalent_source(an: Analysis, monotonic) -> str:
    """The canonical code with transforms that cannot change a cross-sectional rank removed from inside rank():
    rank(zscore(x)) and rank(rank(x)) trade exactly like rank(x), so they must not be simulated again."""
    if an.program is None:
        return an.canonical
    mono = {m.lower() for m in monotonic or []}
    if not mono:
        return an.canonical
    prog = copy.deepcopy(an.program)
    changed = True
    while changed:
        changed = False
        for node in walk(prog):
            if isinstance(node, Call) and node.name.lower() == "rank" and len(node.args) == 1 and not node.kwargs:
                inner = node.args[0]
                if isinstance(inner, Call) and inner.name.lower() in mono and len(inner.args) == 1 and not inner.kwargs:
                    node.args[0] = inner.args[0]
                    changed = True
    out = to_source(prog)
    return an.canonical if out.replace(" ", "") == (an.canonical or "").replace(" ", "") else out


class Generator:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.gen = ctx.cfg.section("generation")

    # -- validation of one LLM candidate -------------------------------------------------
    def build_settings(self, raw: dict) -> tuple[dict, list[str]]:
        ctx = self.ctx
        settings = {**ctx.defaults, **{k: ctx.scope[k] for k in ("instrumentType", "region", "universe", "delay")}}
        notes = []
        for key, cast in (("neutralization", lambda v: str(v).strip().upper()), ("decay", lambda v: int(float(v))),
                          ("truncation", float)):
            val = raw.get(key)
            if val in (None, ""):
                continue
            try:
                settings[key] = cast(val)
            except (TypeError, ValueError):
                notes.append(f"ignored invalid {key}={val!r}")
        if raw.get("universe") and raw["universe"] != settings["universe"]:  # refinement may try another universe
            allowed = allowed_values(ctx.options, "universe", settings) if ctx.options else None
            if allowed is None or raw["universe"] in allowed:
                settings["universe"] = raw["universe"]
        replace_none = ctx.cfg.get("settings_policy.replace_none_neutralization_with")
        if replace_none and str(settings.get("neutralization", "")).upper() == "NONE":
            settings["neutralization"] = replace_none
            notes.append(f"neutralization NONE -> {replace_none}: without it most alphas are one-sided market bets")
        if ctx.options:
            for err in validate_settings(settings, ctx.options):
                key = err.split("=")[0].split(" ")[0].strip("'")
                if key in ctx.defaults:
                    notes.append(f"{err}; using default {ctx.defaults[key]!r}")
                    settings[key] = ctx.defaults[key]
        return settings, notes

    def fit_neutralization(self, an: Analysis, settings: dict) -> list[str]:
        """A signal that is constant within each industry vanishes under INDUSTRY or SUBINDUSTRY neutralization:
        move the setting to the next coarser level the platform allows for this region."""
        level = an.group_level
        hier = [h.lower() for h in self.ctx.rules.group_hierarchy]
        neut = str(settings.get("neutralization") or "").lower()
        if not level or neut not in hier or hier.index(neut) > hier.index(level):
            return []
        allowed = allowed_values(self.ctx.options, "neutralization", settings) if self.ctx.options else None
        for h in hier[hier.index(level) + 1:]:
            if allowed is None or h.upper() in allowed:
                settings["neutralization"] = h.upper()
                return [f"neutralization {neut.upper()} -> {h.upper()}: the signal is constant within each {level}"]
        an.issues.append(Issue("E_DEGENERATE", "error",
                               f"the signal is constant within each {level}; {neut.upper()} neutralization removes it",
                               hint="add stock-level variation or use a finer grouping for the signal", subject="neutralization"))
        return []

    def build_description(self, raw: dict, an: Analysis) -> tuple[str, list[str]]:
        pp = self.ctx.pp
        sections = (pp.get("description") or {}).get("sections") or ["Idea", "Rationale for data used",
                                                                      "Rationale for operators used"]
        min_chars = int((pp.get("description") or {}).get("min_chars", 100))
        notes = []
        idea = str(raw.get("idea") or "").strip()
        r_data = str(raw.get("rationale_data") or "").strip()
        r_ops = str(raw.get("rationale_operators") or "").strip()
        cat = self.ctx.catalog
        if an.program is not None:
            called = []
            for node in walk(an.program):
                if isinstance(node, Call):
                    sig = cat.op(node.name)
                    if sig and sig.name not in called:
                        called.append(sig.name)
            missing = [op for op in called if op.lower() not in r_ops.lower()]
            if missing:
                extra = "; ".join(f"{op}(): {cat.op(op).short_description(90)}" for op in missing)
                r_ops = f"{r_ops}; {extra}" if r_ops else extra
                notes.append(f"description: added catalog notes for {', '.join(missing)}")
            unnamed = [f for f in an.counted_fields() if f in an.field_info and f not in r_data]
            if unnamed:
                extra = "; ".join(f"{f}: {an.field_info[f].description}" for f in unnamed)
                r_data = f"{r_data} ({extra})" if r_data else extra
                notes.append("description: named the data fields used")
        needle = (an.canonical or "").replace(" ", "")

        def strip_expression(text: str) -> str:
            if needle and needle in text.replace(" ", ""):
                notes.append("description: removed pasted expression")
                return text.replace(an.canonical, "").replace(an.clean, "").strip()
            return text

        idea, r_data, r_ops = strip_expression(idea), strip_expression(r_data), strip_expression(r_ops)
        desc =f"{sections[0]}: {idea}\n\n{sections[1]}: {r_data}\n\n{sections[2]}: {r_ops}"
        if not idea:
            notes.append("description: idea is empty")
        if len(desc) < min_chars:
            notes.append(f"description shorter than {min_chars} characters")
        return desc, notes

    def check(self, raw: dict, origin: str = "llm", parent_id: int | None = None) -> Candidate:
        expr = str(raw.get("expression") or "")
        an = analyze(expr, self.ctx.catalog, self.ctx.constraints)
        settings, s_notes = self.build_settings(raw)
        s_notes += self.fit_neutralization(an, settings)
        self.ctx.memory.record_analysis(an)
        desc, d_notes = self.build_description(raw, an)
        pid = parent_id if parent_id is not None else raw.get("parent_id")
        return Candidate(raw=raw, expression=expr, analysis=an, settings=settings, description=desc,
                         notes=an.fixes + s_notes + d_notes, origin=origin,
                         equivalent=equivalent_source(an, self.ctx.cfg.get("fastexpr.monotonic_in_rank") or []),
                         parent_id=int(pid) if isinstance(pid, (int, float)) or (isinstance(pid, str) and pid.isdigit()) else None)

    # -- grounding ----------------------------------------------------------------------
    def cited_fields(self, hyp: dict, max_lookups: int = 8) -> list[dict]:
        """Exact field ids the source paper mentions next to this hypothesis, verified against the catalog and
        filtered to the theme. Research notes name concrete fields; paraphrased hypotheses lose them."""
        ctx = self.ctx
        c = ctx.constraints
        chunks = ctx.store.chunks(doc_id=hyp["paper_id"])
        texts = [json.dumps(hyp.get("body") or {})]
        if chunks:
            bm = BM25([ch["text"] for ch in chunks])
            texts += [chunks[i]["text"] for i, score in bm.top(hypothesis_query(hyp), 2) if score > 0]
        tokens = list(dict.fromkeys(t for t in _FIELD_LIKE.findall(" ".join(texts))))
        out, lookups = [], 0
        for tok in tokens:
            row = ctx.store.field(tok, ctx.scope) or ctx.store.field(tok.lower(), ctx.scope)
            if row is None and ctx.sync and ctx.sync.client and lookups < max_lookups:
                lookups += 1
                info = ctx.sync.lookup_field(tok.lower(), ctx.scope)
                row = ctx.store.field(info.id, ctx.scope) if info else None
            if row is None or (row.get("type") or "").upper() not in ("MATRIX", "VECTOR"):
                continue
            if c and c.allowed_categories and row.get("category") not in c.allowed_categories:
                continue
            if c and c.grouping_fields and row["id"] in c.grouping_fields:
                continue
            if row["id"] not in {r["id"] for r in out}:
                out.append(row)
        if not out:
            return out
        # passages can span neighbouring ideas: keep the fields whose own description matches this hypothesis
        rel = BM25([f"{r['id']} {r.get('description') or ''}" for r in out]).scores(hypothesis_query(hyp))
        top = max(rel)
        keep = [(r, sc) for r, sc in zip(out, rel) if top > 0 and sc >= 0.3 * top]
        for r, sc in keep:
            r["_relevance"] = sc
        return [r for r, _ in sorted(keep, key=lambda x: x[1], reverse=True)]

    def choose_datasets(self, hyp: dict, cited: list[dict] | None = None) -> list[dict]:
        ctx = self.ctx
        c = ctx.constraints
        allowed = c.allowed_categories if c else None
        hyp_cats = set((hyp.get("body") or {}).get("candidate_categories") or [])
        cats = (hyp_cats & allowed) if (allowed and hyp_cats & allowed) else (allowed or (hyp_cats or None))
        rows = ctx.store.datasets(ctx.scope, categories=cats) or ctx.store.datasets(ctx.scope, categories=allowed)
        if c and c.allowed_datasets:
            rows = [r for r in rows if r["id"] in c.allowed_datasets]
        if not rows:
            return []
        ranked = rank_datasets(rows, hypothesis_query(hyp))
        if route_of(ctx) == "regular":
            # production correlation is driven by how many alphas already use the data: weight relevance by the
            # dataset's crowding and its pyramid multiplier (BRAIN's own under-use measures)
            ranked = sorted(((r, sc * pyramid_of(ctx, r.get("category")) / math.log10(10 + (r.get("alpha_count") or 0)))
                             for r, sc in ranked), key=lambda t: -t[1])
        by_id = {r["id"]: r for r in rows}
        counts: dict = {}
        for f in cited or []:
            if f.get("dataset") in by_id:
                counts[f["dataset"]] = counts.get(f["dataset"], 0) + f.get("_relevance", 1.0)
        pinned = [by_id[d] for d in sorted(counts, key=counts.get, reverse=True)]
        if pinned:  # the research names concrete fields: start from their datasets
            head = pinned[0]
            ranked = [(r, 9.0) for r in pinned] + [(r, sc) for r, sc in ranked if r["id"] not in counts]
            ranked = [(r, sc) for r, sc in ranked if not (c and c.single_category) or r.get("category") == head.get("category")]
        picked = [ranked[0][0]]
        single = bool(c and (c.single_category or c.single_dataset))
        pool = [(r, s) for r, s in ranked[1:8] if not single or r.get("category") == picked[0].get("category")]
        if c and c.single_dataset:
            pool = []
        want = int(self.gen.get("datasets_per_hypothesis", 2))
        for r, _ in pool[:]:
            if len(picked) < want and r["id"] in counts:  # other datasets the research cites come next
                picked.append(r)
                pool = [(x, sc) for x, sc in pool if x["id"] != r["id"]]
        while len(picked) < want and pool:
            weights = [max(s, 1e-3) for _, s in pool]
            idx = random.choices(range(len(pool)), weights=weights)[0]
            picked.append(pool.pop(idx)[0])
        return picked

    def field_rows(self, datasets: list[dict], query: str, cited: list[dict] | None = None) -> list[dict]:
        ctx = self.ctx
        rows = []
        for ds in datasets:
            n = ctx.sync.ensure_fields(ds["id"], ctx.scope)
            if n:
                console.print(f"  synced {n} fields of dataset {ds['id']}")
            ds_rows = ctx.store.fields(ctx.scope, dataset=ds["id"])
            ctx.catalog.add_fields(row_to_field(r) for r in ds_rows)
            rows += ds_rows
        short = shortlist_fields(rows, query, int(self.gen.get("fields_shortlist", 45)),
                                 float(self.gen.get("min_field_coverage", 0.3)),
                                 list(self.gen.get("technical_field_patterns") or []))
        chosen = {d["id"] for d in datasets}
        first = [f for f in cited or [] if f.get("dataset") in chosen]
        return first + [f for f in short if f["id"] not in {x["id"] for x in first}]

    def lessons(self, datasets: set) -> str:
        notes = self.ctx.memory.hallucination_notes() + self.ctx.memory.dataset_lessons(datasets)
        return "\n".join(f"- {n}" for n in notes) or "(none yet)"

    def guidance(self, query: str) -> str:
        snippets = doc_snippets(self.ctx.store, query, kind="brain_doc", k=2, max_chars=2200)
        return "\n\n".join(f"### {t}\n{x}" for t, x in snippets) or "(no BRAIN docs synced)"

    def messages(self, hyp: dict, datasets: list[dict], fields: list[dict], n: int,
                 cited: list[str] | None = None) -> list[dict]:
        ctx = self.ctx
        query = hypothesis_query(hyp)
        ds_ids = {d["id"] for d in datasets}
        cats = {d.get("category") for d in datasets}
        k = int(self.gen.get("exemplars", 4))
        ex_rows = ctx.memory.exemplars(cats, ds_ids, k)
        official = ctx.memory.official_examples(ctx.catalog, max(0, k - len(ex_rows)), constraints=ctx.constraints)
        paper = ctx.store.document(hyp["paper_id"]) or {}
        user = render(
            ctx.cfg.prompt("generate"),
            n=n,
            paper_title=paper.get("title", "unknown"),
            hypothesis=hypothesis_text(hyp),
            paper_excerpts=paper_excerpts(ctx.store, hyp["paper_id"], query, int(self.gen.get("paper_context_chars", 7000)))
            or "(no excerpts)",
            scope=scope_text(ctx.scope),
            constraints=constraints_text(ctx.constraints, ctx.theme),
            settings_choices=settings_text(ctx.options, ctx.scope, ctx.defaults),
            operators=operator_reference(ctx.catalog),
            datasets=", ".join(f"{d['id']} ({d.get('category')}: {d.get('name')})" for d in datasets),
            fields=field_lines(fields),
            cited_fields=", ".join(cited or []) or "(none - choose from the table)",
            grouping_fields=grouping_text(ctx.catalog, ctx.constraints),
            exemplars=exemplar_text(ex_rows, official),
            lessons=self.lessons(ds_ids),
            guidance=self.guidance(query + " " + " ".join(d.get("name", "") for d in datasets)),
            shapes=self.shapes(fields),
            route=route_text(ctx),
            playbook=playbook_text(ctx.cfg, fields),
        )
        return [{"role": "system", "content": ctx.cfg.prompt("system")}, {"role": "user", "content": user}]

    def shapes(self, fields: list[dict]) -> str:
        if not self.ctx.cfg.get("shapes.enabled", True):
            return "(not used)"
        from .shaper import shapes_text
        try:
            return shapes_text(self.ctx, fields, int(self.ctx.cfg.get("shapes.in_prompt", 8)))
        except Exception as e:  # the prompt must not fail because the library is missing or malformed
            return f"(shape library unavailable: {e})"

    # -- LLM loop -------------------------------------------------------------------------
    def repair(self, messages: list[dict], cands: list[Candidate], origin_prefix: str = "") -> list[Candidate]:
        rounds = int(self.gen.get("max_repair_rounds", 2))
        convo = messages
        for _ in range(rounds):
            bad = [i for i, c in enumerate(cands) if not c.ok]
            if not bad:
                break
            blocks = []
            for n, i in enumerate(bad, 1):
                c = cands[i]
                problems = "\n".join(f"- {iss.render()}" for iss in c.analysis.errors[:8])
                blocks.append(f"### Candidate {n}\nexpression: {c.expression}\nproblems:\n{problems}")
            convo = convo + [{"role": "user", "content": render(self.ctx.cfg.prompt("repair"), problems="\n\n".join(blocks))}]
            try:
                res = self.ctx.llm.chat_json(convo, purpose="repair", schema=CANDIDATE_SCHEMA, auto_reward=False,
                                             check=_has_candidates, max_attempts=2)
            except LLMError as e:
                console.print(f"  [yellow]repair skipped: {esc(str(e))}[/yellow]")
                break
            fixed = res.obj["candidates"]
            n_fixed = 0
            for i, raw in zip(bad, fixed):
                new = self.check(raw, origin=f"{origin_prefix}repair", parent_id=cands[i].parent_id)
                new.model = res.model
                if new.ok:
                    n_fixed += 1
                cands[i] = new
            self.ctx.llm.reward(res.model, n_fixed / max(1, len(bad)))
            convo = res.messages
        return cands

    def generate(self, hyp: dict, n: int | None = None) -> list[Candidate]:
        n = n or int(self.gen.get("candidates_per_call", 6))
        cited = self.cited_fields(hyp)
        datasets = self.choose_datasets(hyp, cited)
        if not datasets:
            console.print("[red]  no datasets available for this scope/theme - run `p2a sync`[/red]")
            return []
        fields = self.field_rows(datasets, hypothesis_query(hyp), cited)
        if not fields:
            console.print("[red]  no usable fields in the chosen datasets[/red]")
            return []
        console.print(f"  datasets: {', '.join(d['id'] for d in datasets)} | {len(fields)} fields in prompt")
        chosen = {d["id"] for d in datasets}
        cited_here = [f["id"] for f in cited if f.get("dataset") in chosen]
        if cited_here:
            console.print(f"  fields cited by the research: {', '.join(cited_here)}")
        msgs = self.messages(hyp, datasets, fields, n, cited_here)
        res = self.ctx.llm.chat_json(msgs, purpose="generate", schema=CANDIDATE_SCHEMA, auto_reward=False,
                                     check=_has_candidates)
        cands = [self.check(raw) for raw in res.obj["candidates"]]
        for c in cands:
            c.model = res.model
        first_pass = sum(c.ok for c in cands) / max(1, len(cands))
        cands = self.repair(res.messages, cands)
        final = sum(c.ok for c in cands) / max(1, len(cands))
        self.ctx.llm.reward(res.model, 0.7 * first_pass + 0.3 * final)
        self.limit_same_fields(cands)
        console.print(f"  {res.model}: {sum(c.ok for c in cands)}/{len(cands)} valid "
                      f"(first pass {first_pass:.0%})")
        return cands

    def limit_same_fields(self, cands: list[Candidate]) -> None:
        """Power Pool alphas must be < 0.5 correlated with each other, so do not spend simulations on many
        variants built from the identical set of fields; keep the first few, skip the rest."""
        cap = int(self.gen.get("max_same_field_set", 2))
        seen: dict[str, int] = {}
        for c in cands:
            if not c.ok:
                continue
            key = family_key(c.analysis.counted_fields(), self.shape_class(c))  # same fields in another shape = new idea
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > cap:
                c.skip = f"skipped: {cap} candidates already use these fields in this shape"

    # -- persistence ----------------------------------------------------------------------
    def shape_class(self, c: Candidate) -> str:
        """The class of the library shape the candidate says it follows, else the class read from its operators."""
        lib = shape_library(self.ctx)
        shape = str(c.raw.get("shape") or "")
        if shape.startswith("mech:"):  # a research mechanism is its own idea, whatever operators it uses
            from .mechanisms import mechanism_library
            m = mechanism_library(self.ctx).get(shape[5:])
            if m is not None:
                return m.group or m.id
        sh = lib.get(shape)
        if sh is not None and sh.cls != "wrapper":
            return sh.cls
        return lib.class_of(c.analysis.operators)

    def _closed_families(self, cands: list[Candidate]) -> dict:
        """Families the lifecycle has closed (used / dropped / winner): new candidates on them would only repeat
        a decided experiment or produce a correlated copy of a winner."""
        if not any(c.ok and c.origin != "manual" for c in cands) or not self.ctx.cfg.get("lifecycle.skip_closed_families", True):
            return {}
        try:
            fams = Lifecycle(self.ctx).families()
        except Exception:
            return {}
        return {k: f for k, f in fams.items() if f.state in ("used", "dropped", "winner")}

    def save(self, cands: list[Candidate], hypothesis_id: int | None) -> dict:
        ctx = self.ctx
        stats = {"valid": 0, "invalid": 0, "duplicate": 0, "skipped": 0, "ids": []}
        grouping = ctx.constraints.grouping_fields if ctx.constraints else set()
        excluded = ctx.constraints.excluded_ops if ctx.constraints else set()
        closed = self._closed_families(cands)
        for c in cands:
            an = c.analysis
            if c.ok and not c.skip and c.origin != "manual":
                fam = closed.get(family_key(an.counted_fields(grouping), self.shape_class(c)))
                if fam is not None:  # the lifecycle already decided about these exact fields
                    c.skip = f"skipped: family {fam.state} ({fam.reason})"
            row = {
                "payload_hash": c.payload_hash if c.ok else stable_hash({"invalid": c.expression, "n": random.random()}),
                "canonical": an.canonical or None, "expression": c.expression, "settings": c.settings,
                "hypothesis_id": hypothesis_id, "parent_id": c.parent_id, "origin": c.origin, "model": c.model,
                "theme": ctx.theme.name if ctx.theme else None, "region": ctx.scope["region"],
                "delay": ctx.scope["delay"], "universe": c.settings.get("universe", ctx.scope["universe"]),
                "fields": an.counted_fields(grouping), "operators": an.operators,
                "categories": an.categories(grouping), "datasets": an.datasets(grouping),
                "op_count": an.op_count, "pp_op_count": an.pp_op_count(excluded),
                "description": c.description, "rationale": c.raw.get("idea"),
                "status": ("skipped" if c.skip else "valid") if c.ok else "invalid",
                "shape": c.raw.get("shape"), "shape_class": self.shape_class(c) if c.ok else None,
                "route": getattr(ctx, "route", None) or "power_pool",
                "issues": [i.render() for i in an.issues] + c.notes + ([c.skip] if c.skip else []),
            }
            aid = ctx.store.add_alpha(row)
            if aid is None:
                stats["duplicate"] += 1
                continue
            if c.ok and c.skip:
                stats["skipped"] += 1
                continue
            stats["valid" if c.ok else "invalid"] += 1
            if c.ok:
                stats["ids"].append(aid)
        return stats
