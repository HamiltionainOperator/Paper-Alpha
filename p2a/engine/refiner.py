"""Improve near-miss alphas: cheap deterministic variants first, then one batched LLM call."""
from __future__ import annotations

import re

from ..brain.settings import allowed_values
from ..fastexpr import analyze, to_source
from ..fastexpr.ast import BinOp, Call, Ident, Num, UnaryOp
from ..knowledge import shortlist_fields
from ..llm import LLMError
from ..util import console, esc
from .context import Context
from .generator import CANDIDATE_SCHEMA, Candidate, Generator, _has_candidates
from .lifecycle import Lifecycle, family_key, row_family, shape_library
from .playbook import playbook_text
from .routes import reasons_key, route_of, route_text
from .grounding import (constraints_text, field_lines, grouping_text, operator_reference, render, scope_text,
                        settings_text)


def split_description(desc: str, sections: list[str]) -> dict:
    out = {"idea": "", "rationale_data": "", "rationale_operators": ""}
    keys = ["idea", "rationale_data", "rationale_operators"]
    pattern = "|".join(re.escape(s) for s in sections)
    parts = re.split(rf"(?m)^({pattern}):\s*", desc or "")
    label = None
    for chunk in parts:
        if chunk in sections:
            label = keys[sections.index(chunk)]
        elif label:
            out[label] = chunk.strip()
    return out


def negate_last_statement(program) -> bool:
    """Invert the alpha's sign, at zero operator cost when the structure allows it."""
    stmts = program.statements
    last = stmts[-1]
    if isinstance(last, UnaryOp) and last.op == "-":
        stmts[-1] = last.operand
        return True
    if isinstance(last, BinOp) and last.op == "*" and (isinstance(last.left, Num) or isinstance(last.right, Num)):
        num = last.left if isinstance(last.left, Num) else last.right
        num.value = -num.value
        return True
    if isinstance(last, BinOp) and last.op == "-":
        last.left, last.right = last.right, last.left
        return True
    stmts[-1] = UnaryOp(line=last.line, col=last.col, op="-", operand=last)
    return True


def residual_code(code: str, factor: str, name: str = "sig") -> str:
    """`code` minus its cross-sectional regression on `factor`: the part of the signal the factor does not explain.
    regression_proj(y, x) fits a + b*x with an intercept; vector_neut has none, so against a rank (all values of
    one sign) it mostly removes a constant and leaves the factor in (measured: 0.75 -> 0.80 with it)."""
    stmts = [x.strip() for x in code.split(";") if x.strip()]
    *pre, last = stmts
    taken = {s.split("=", 1)[0].strip() for s in pre if "=" in s}
    while name in taken:
        name += "_"
    return "; ".join(pre + [f"{name} = {last}", f"{name} - regression_proj({name}, {factor})"])


class Refiner:
    def __init__(self, ctx: Context, generator: Generator, simulator=None):
        self.ctx = ctx
        self.gen = generator
        self.simulator = simulator
        self.rcfg = ctx.cfg.section("refine")

    def near_misses(self, limit: int) -> list[dict]:
        """The best alpha of each family the lifecycle still considers worth work ('promising'), strongest first.
        Families that are weak, illiquid, crowded, already submitted, out of budget or already winners are left
        alone: changing the settings of their alphas would only produce correlated copies."""
        self.lifecycle = Lifecycle(self.ctx, simulator=self.simulator)
        fams = self.lifecycle.families()
        work = [f for f in fams.values() if f.state == "promising" and f.best is not None and not f.queued]
        work.sort(key=lambda f: -(abs(f.worst_sharpe) if "flip" in f.remedies else f.best_sharpe))  # flips by |Sharpe|
        rows = []
        for f in work[:limit]:
            row = dict(f.best)
            row["_family"] = f
            rows.append(row)
        return rows

    # -- deterministic -------------------------------------------------------------------
    def deterministic(self, row: dict) -> list[Candidate]:
        """Cheap, targeted fixes only: each one answers a specific failed check (lifecycle remedies). There is no
        settings sweep - neutralization and decay are not search dimensions."""
        ctx = self.ctx
        fam = row.get("_family")
        remedies = list(fam.remedies) if fam is not None else []
        sections = (ctx.pp.get("description") or {}).get("sections") or ["Idea", "Rationale for data used",
                                                                          "Rationale for operators used"]
        base_text = split_description(row.get("description") or "", sections)
        settings = dict(row.get("settings") or {})
        stats = row.get("stats") or {}
        turnover = stats.get("turnover") or 0.0
        lo, hi = ctx.pp.get("turnover_range", [0.01, 0.7])
        decay_spec = (ctx.options or {}).get("decay") or {}
        max_decay = int(decay_spec.get("maxValue", 512))
        variants: list[tuple[str, dict, str, str]] = []

        def add(expr: str, new_settings: dict, why: str, origin: str = "refine:auto"):
            variants.append((expr, {**settings, **new_settings}, why, origin))

        an = analyze(row["canonical"], ctx.catalog, ctx.constraints)
        if an.program is None:
            return []
        if "flip" in remedies:
            negate_last_statement(an.program)
            add(to_source(an.program, ctx.catalog), {}, "inverted the signal (strongly negative Sharpe)", "refine:flip")
            an = analyze(row["canonical"], ctx.catalog, ctx.constraints)
        if "liquid_universe" in remedies:
            alt = (self.rcfg.get("sub_universe_alternatives") or {}).get(str(settings.get("universe")))
            allowed = allowed_values(ctx.options, "universe", settings) if ctx.options else None
            if alt and (allowed is None or alt in allowed):
                add(row["canonical"], {"universe": alt}, f"universe {alt}, the liquid sub-universe where it fell short")
        if "liquidity_weight" in remedies:
            size = self.size_field(row)
            if size:
                prog = analyze(row["canonical"], ctx.catalog, ctx.constraints).program
                last = prog.statements[-1]
                ranked = last if isinstance(last, Call) and last.name.lower() == "rank" else Call(line=0, col=0, name="rank", args=[last])
                prog.statements[-1] = BinOp(line=0, col=0, op="*",
                                            left=BinOp(line=0, col=0, op="-", left=ranked, right=Num(line=0, col=0, value=0.5, text="0.5")),
                                            right=Call(line=0, col=0, name="rank", args=[Ident(line=0, col=0, name=size)]))
                add(to_source(prog, ctx.catalog), {}, f"centred the signal and scaled positions by the rank of {size} "
                    "so liquid companies carry the bet", "refine:liquidity")
        if "decorrelate" in remedies:
            # production alphas share common style exposure: neutralize it with the factor set that suits the
            # signal's speed (BRAIN Learn "Risk Neutralized Alphas"; slow factors for slow signals, fast for fast)
            rc = ctx.regular
            sets = rc.get("risk_neutralizations") or {}
            speed = ("slow" if turnover < float(rc.get("risk_slow_turnover_below", 0.15)) else
                     "fast" if turnover > float(rc.get("risk_fast_turnover_above", 0.4)) else "medium")
            neut = sets.get(speed)
            allowed = allowed_values(ctx.options, "neutralization", settings) if ctx.options else None
            if neut and (allowed is None or neut in allowed) and neut != settings.get("neutralization"):
                add(row["canonical"], {"neutralization": neut},
                    f"{neut} risk-factor neutralization removes the style exposure production alphas share",
                    "refine:decorrelate")
        if "orthogonalize" in remedies:
            # the residual of a daily cross-sectional regression on the crowded factor it resembles: regression_proj
            # fits a + b*factor (with intercept; vector_neut has none, so on a rank it mostly removes a constant)
            ref_id = (row.get("stats") or {}).get("ref_factor")
            ref = next((r for r in (ctx.cfg.get("uniqueness.references") or []) if r.get("id") == ref_id), None)
            if ref:
                add(residual_code(row["canonical"], ref["expression"]), {},
                    f"removed the {ref_id} factor it traded like (residual of a cross-sectional regression "
                    "on it), to keep only the information beyond that factor", "refine:orthogonalize")
        if "decay_up" in remedies:
            cur = int(settings.get("decay") or 0)
            add(row["canonical"], {"decay": min(max_decay, max(cur * 2, cur + 6))}, "raised decay to cut turnover")
        if "truncation_down" in remedies:
            cur = float(settings.get("truncation") or 0.08)
            add(row["canonical"], {"truncation": round(max(0.01, cur / 2), 4)}, "lower truncation against concentration")
        if "expression" in remedies and an.lookback_nodes and (turnover > hi or (turnover and turnover < lo)):
            scale = 2.0 if turnover > hi else 0.5  # move turnover into range by changing the windows, not the settings
            for n in an.lookback_nodes:
                n.value = float(max(1, min(ctx.rules.max_lookback, round(n.value * scale))))
            add(to_source(an.program, ctx.catalog), {}, f"scaled look-back windows x{scale} to bring turnover into range")

        out = []
        for expr, new_settings, why, origin in variants[: int(self.rcfg.get("variants_per_alpha", 3))]:
            raw = {"expression": expr, "neutralization": new_settings.get("neutralization"), "universe": new_settings.get("universe"),
                   "decay": new_settings.get("decay"), "truncation": new_settings.get("truncation"),
                   "idea": f"{base_text['idea']} (Variant: {why}.)".strip(),
                   "rationale_data": base_text["rationale_data"], "rationale_operators": base_text["rationale_operators"]}
            cand = self.gen.check(raw, origin=origin, parent_id=row["id"])
            if cand.ok:
                out.append(cand)
        return out

    def size_field(self, row: dict) -> str | None:
        """A company-size field from the alpha's own data category (single-category themes stay matched), found by
        its catalog description (lifecycle.liquidity_field_patterns): highest coverage, then least used."""
        ctx = self.ctx
        pats = [re.compile(p, re.I) for p in ctx.cfg.get("lifecycle.liquidity_field_patterns") or []]
        cats = set(row.get("categories") or [])
        if not pats or len(cats) != 1:
            return None
        best = None
        for f in ctx.store.fields(ctx.scope):
            if f.get("category") not in cats or (f.get("type") or "MATRIX").upper() != "MATRIX":
                continue
            if not any(p.search(f.get("description") or "") for p in pats) or (f.get("coverage") or 0) < 0.95:
                continue
            key = (f.get("coverage") or 0, -(f.get("alpha_count") or 0))
            if best is None or key > best[0]:
                best = (key, f["id"])
        return best[1] if best else None

    # -- LLM ------------------------------------------------------------------------------
    def with_llm(self, rows: list[dict]) -> list[Candidate]:
        ctx = self.ctx
        if not rows:
            return []
        k = int(self.rcfg.get("variants_per_alpha", 3))
        blocks, field_rows, query = [], [], []
        for r in rows:
            hyp = ctx.store.hypothesis(r["hypothesis_id"]) if r.get("hypothesis_id") else None
            title = hyp["title"] if hyp else "n/a"
            mech = ((hyp or {}).get("body") or {}).get("mechanism", "")
            st = r.get("stats") or {}
            s = r.get("settings") or {}
            margin = st.get("margin")
            blocks.append(
                f"### Alpha id {r['id']}\nhypothesis: {title}: {mech}\nexpression: {r['canonical']}\n"
                f"settings: neutralization={s.get('neutralization')}, decay={s.get('decay')}, truncation={s.get('truncation')}\n"
                f"results: Sharpe {st.get('sharpe')}, fitness {st.get('fitness')}, turnover {st.get('turnover')}, "
                f"returns {st.get('returns')}, drawdown {st.get('drawdown')}, "
                f"margin {round(margin * 1e4, 2) if isinstance(margin, (int, float)) else margin} bps\n"
                f"failing: {'; '.join(r.get(reasons_key(route_of(ctx))) or [])}\n"
                f"verdict: {(r.get('_family').reason if r.get('_family') else 'n/a')}; allowed changes: "
                f"{', '.join(r.get('_family').remedies) if r.get('_family') else 'expression'}")
            query.append(f"{title} {mech}")
            for ds in r.get("datasets") or []:
                ctx.sync.ensure_fields(ds, ctx.scope)
                field_rows += ctx.store.fields(ctx.scope, dataset=ds)
        gen_cfg = ctx.cfg.section("generation")
        shortlist = shortlist_fields(field_rows, " ".join(query), int(gen_cfg.get("fields_shortlist", 45)),
                                     float(gen_cfg.get("min_field_coverage", 0.3)),
                                     list(gen_cfg.get("technical_field_patterns") or []))
        used = {f for r in rows for f in (r.get("fields") or [])}
        have = {f["id"] for f in shortlist}
        shortlist += [f for f in field_rows if f["id"] in used and f["id"] not in have]
        pp = ctx.pp
        if route_of(ctx) == "regular":
            rc = ctx.regular
            criteria = (f"regular consultant alpha: Sharpe >= {rc.get('min_sharpe')}, fitness >= {rc.get('min_fitness')}, "
                        "turnover 1%-70%, sub-universe and 2-year Sharpe tests, self- and production correlation < "
                        f"{rc.get('prod_correlation_limit')}; at most {rc.get('max_operators')} operators and "
                        f"{rc.get('max_fields')} data fields")
        else:
            criteria = (f"Sharpe >= {pp.get('min_sharpe')}, turnover {pp.get('turnover_range')}, "
                        f"at most {pp.get('max_operators')} operators and {pp.get('max_unique_fields')} data fields, "
                        f"must pass: {', '.join(pp.get('must_pass_checks') or [])}")
        user = render(ctx.cfg.prompt("refine"), k=k, criteria=criteria, scope=scope_text(ctx.scope), route=route_text(ctx),
                      constraints=constraints_text(ctx.constraints, ctx.theme),
                      settings_choices=settings_text(ctx.options, ctx.scope, ctx.defaults),
                      alphas="\n\n".join(blocks), operators=operator_reference(ctx.catalog),
                      fields=field_lines(shortlist), grouping_fields=grouping_text(ctx.catalog, ctx.constraints),
                      lessons=self.gen.lessons({d for r in rows for d in (r.get("datasets") or [])}),
                      shapes=self.gen.shapes(shortlist), playbook=playbook_text(ctx.cfg, shortlist))
        msgs = [{"role": "system", "content": ctx.cfg.prompt("system")}, {"role": "user", "content": user}]
        try:
            res = ctx.llm.chat_json(msgs, purpose="refine", schema=CANDIDATE_SCHEMA, auto_reward=False,
                                    check=_has_candidates)
        except LLMError as e:
            console.print(f"  [yellow]LLM refinement skipped: {esc(str(e))}[/yellow]")
            return []
        valid_parents = {r["id"] for r in rows}
        cands = []
        for raw in res.obj["candidates"]:
            pid = raw.get("parent_id")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = None
            c = self.gen.check(raw, origin="refine:llm", parent_id=pid if pid in valid_parents else rows[0]["id"])
            c.model = res.model
            cands.append(c)
        first = sum(c.ok for c in cands) / max(1, len(cands))
        cands = self.gen.repair(res.messages, cands, origin_prefix="refine:")
        self.ctx.llm.reward(res.model, 0.7 * first + 0.3 * sum(c.ok for c in cands) / max(1, len(cands)))
        return cands

    def run(self, limit: int | None = None, use_llm: bool = True, ids: list[int] | None = None) -> list[Candidate]:
        limit = limit or int(self.rcfg.get("llm_batch", 4))
        if ids:  # explicitly requested rows still get the lifecycle verdict of their family
            self.lifecycle = Lifecycle(self.ctx, simulator=self.simulator)
            fams = self.lifecycle.families()
            rows = []
            for r in (self.ctx.store.alpha(i) for i in ids):
                if r and r.get("canonical"):
                    r = dict(r)
                    r["_family"] = fams.get(row_family(self.ctx, r))
                    rows.append(r)
        else:
            rows = self.near_misses(limit)
        if not rows:
            console.print("  nothing worth refining: every family is either a winner, used, or dropped by the lifecycle")
            return []
        console.print(f"  refining {len(rows)} promising famil{'y' if len(rows) == 1 else 'ies'}")
        for r in rows:
            f = r.get("_family")
            if f is not None:
                console.print(f"    [dim]{esc(f.key[:60])}: {esc(f.reason)}[/dim]")
        cands = []
        for r in rows:
            cands += self.deterministic(r)
        llm_rows = [r for r in rows if r.get("_family") is None or
                    {"expression", "decorrelate"} & set(r["_family"].remedies)]
        if use_llm and llm_rows:
            cands += self.with_llm(llm_rows)
        return self._within_budget(cands, rows)

    def _within_budget(self, cands: list[Candidate], rows: list[dict]) -> list[Candidate]:
        """Never queue more children than a family has budget left (lifecycle.max_sims_per_family)."""
        cap = int(self.ctx.cfg.get("lifecycle.max_sims_per_family", 5))
        per_round = int(self.ctx.cfg.get("lifecycle.max_children_per_round", 2))
        left: dict[str, int] = {}
        for r in rows:
            f = r.get("_family")
            if f is not None:
                left[f.key] = max(0, min(per_round, cap - f.sims - f.queued))
        out = []
        for c in cands:
            key = family_key(c.analysis.counted_fields(), shape_library(self.ctx).class_of(c.analysis.operators))
            if key in left:
                if left[key] <= 0:
                    c.skip = "skipped: the family's simulation budget is used"
                    continue
                left[key] -= 1
            out.append(c)
        return out
