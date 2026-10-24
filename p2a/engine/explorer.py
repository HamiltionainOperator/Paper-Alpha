"""Exploration: one cheap probe per untried signal family, chosen from BRAIN's own dataset metadata.

The best alphas of this engine came from datasets the platform itself marks as valuable and that few alphas use
yet (high `valueScore`, low `alphaCount`), not from re-working crowded textbook fields. The explorer ranks the
theme's datasets by that metadata, picks the fields whose catalog descriptions read like forecasts or scores,
skips fields whose family the lifecycle has already decided, and queues one plain probe per field
(`rank(field)`, vector fields aggregated first). The lifecycle then inverts strong negatives, drops weak ones and
sends strong ones to BRAIN's check. Every choice comes from the live catalog and `config.yaml` (`explore`).
"""
from __future__ import annotations

import math
import re

from ..llm import LLMError
from ..util import console, esc
from .context import Context
from .generator import Candidate, Generator
from .lifecycle import Lifecycle, family_key
from .routes import pyramid_of, route_of
from .shapes import ShapeLibrary

DESCRIBE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "field": {"type": "string"}, "idea": {"type": "string"}, "rationale_data": {"type": "string"},
        "rationale_operators": {"type": "string"}}, "required": ["field", "idea"]}}},
    "required": ["items"],
}


class Explorer:
    def __init__(self, ctx: Context, generator: Generator, simulator=None):
        self.ctx = ctx
        self.gen = generator
        self.ecfg = ctx.cfg.section("explore")
        self.simulator = simulator
        self.lib = ShapeLibrary.load(ctx.cfg, ctx.catalog)
        self.level_class = self.lib.default_class

    # -- choosing ---------------------------------------------------------------------------
    def datasets(self, tried: dict[str, int], category: str | None = None) -> list[dict]:
        c = self.ctx.constraints
        cats = set(c.allowed_categories or []) if c else set()
        if category:
            cats = (cats & {category}) if cats else {category}
        rows = self.ctx.store.datasets(self.ctx.scope, cats or None)
        if c and c.allowed_datasets:
            rows = [d for d in rows if d["id"] in c.allowed_datasets]
        w = self.ecfg
        regular = route_of(self.ctx) == "regular"
        out = []
        for d in rows:
            cov = d.get("coverage") or 0.0
            if cov < float(w.get("min_dataset_coverage", 0.5)):
                continue
            value = d.get("value_score") or 0.0
            crowd = math.log10(10 + (d.get("alpha_count") or 0))
            score = (value ** float(w.get("value_weight", 1.0))) * cov / crowd / (1 + tried.get(d["id"], 0))
            if regular:  # production correlation follows crowding; BRAIN pays more in under-used pyramids
                score *= pyramid_of(self.ctx, d.get("category")) ** float(w.get("pyramid_weight", 1.0))
            out.append((score, d))
        out.sort(key=lambda x: -x[0])
        return [d for _, d in out]

    def fields(self, dataset: str, closed: set[str], k: int) -> list[dict]:
        ctx = self.ctx
        ctx.sync.ensure_fields(dataset, ctx.scope)
        gen_cfg = ctx.cfg.section("generation")
        tech = [re.compile(p, re.I) for p in gen_cfg.get("technical_field_patterns") or []]
        signal = [re.compile(p, re.I) for p in self.ecfg.get("signal_patterns") or []]
        avoid = [re.compile(p, re.I) for p in self.ecfg.get("avoid_patterns") or []]
        min_cov = float(self.ecfg.get("min_field_coverage", 0.8))
        ds = ctx.store.one("SELECT coverage FROM datasets WHERE id=? AND region=? AND delay=? AND universe=?",
                           (dataset, ctx.scope["region"], ctx.scope["delay"], ctx.scope["universe"])) or {}
        rel = float(self.ecfg.get("min_field_coverage_vs_dataset", 0.9))
        if ds.get("coverage"):  # regions with thinner data (e.g. EUR): judge a field against its own dataset
            min_cov = min(min_cov, rel * float(ds["coverage"]))
        rows = []
        for f in ctx.store.fields(ctx.scope, dataset=dataset):
            text = f"{f['id']} {f.get('description') or ''}"
            if (f.get("type") or "MATRIX").upper() not in ("MATRIX", "VECTOR"):
                continue
            if (f.get("coverage") or 0) < min_cov or any(p.search(text) for p in tech + avoid):
                continue
            sh = self.first_shape(f)
            if family_key([f["id"]], sh.cls if sh else self.level_class) in closed:
                continue
            hits = sum(1 for p in signal if p.search(text))
            if not hits:
                continue
            crowd = math.log10(10 + (f.get("alpha_count") or 0))
            rows.append((hits / crowd, f))
        rows.sort(key=lambda x: -x[0])
        return [f for _, f in rows[:k]]

    def first_shape(self, f: dict):
        """The research shape a never-tried field of this kind is probed with (research/shapes.yaml first_shape)."""
        lib = self.lib
        sid = (lib.data.get("first_shape") or {}).get(lib.kind_of(f) or "", lib.default_class)
        sh = lib.get(sid)
        vector = (f.get("type") or "MATRIX").upper() == "VECTOR"
        if sh is None or not sh.available or (sh.vector_only and not vector) or sh.fields != 1:
            sh = lib.get("level")
        return sh

    def expression(self, f: dict) -> str | None:
        """The probe in the live operator vocabulary: the field's first research shape, or a plain rank."""
        sh = self.first_shape(f)
        if sh is not None and sh.id != "level":
            return self.lib.instantiate(sh, f, None, "medium")
        cat = self.ctx.catalog
        wrap = self.ecfg.get("wrapper", "rank")
        if not cat.op(wrap):
            return None
        inner = f["id"]
        if (f.get("type") or "").upper() == "VECTOR":
            agg = self.ecfg.get("vector_aggregator", "vec_avg")
            if not cat.op(agg):
                return None
            inner = f"{agg}({inner})"
        return f"{wrap}({inner})"

    # -- describing -----------------------------------------------------------------------
    def describe(self, probes: list[tuple[dict, dict]]) -> dict[str, dict]:
        """One LLM request writes the Power Pool description of every probe (template text if it fails)."""
        ctx = self.ctx
        lines = [f"- field `{f['id']}` ({(f.get('type') or 'MATRIX').upper()}) in dataset {d['id']} '{d.get('name')}': "
                 f"{f.get('description') or ''}" for f, d in probes]
        user = ("For each data field below, write the Power Pool description of a one-field alpha that ranks stocks "
                "on the field (higher value = long). Cite the academic finding that best explains why the field "
                "should predict returns, in one or two sentences; do not invent results or numbers.\n\n"
                + "\n".join(lines) +
                '\n\nJSON only: {"items": [{"field": "...", "idea": "...", "rationale_data": "...", '
                '"rationale_operators": "..."}]}')
        msgs = [{"role": "system", "content": "You are a quantitative equity researcher. Answer with JSON only."},
                {"role": "user", "content": user}]
        try:
            res = ctx.llm.chat_json(msgs, purpose="explore", schema=DESCRIBE_SCHEMA,
                                    check=lambda o: None if isinstance(o, dict) and isinstance(o.get("items"), list)
                                    else "JSON lacks an 'items' list")
            return {str(i.get("field")): i for i in res.obj["items"] if isinstance(i, dict)}
        except LLMError as e:
            console.print(f"  [yellow]descriptions from templates ({esc(str(e))[:80]})[/yellow]")
            return {}

    # -- run ------------------------------------------------------------------------------
    def run(self, n: int | None = None, category: str | None = None) -> list[Candidate]:
        ctx = self.ctx
        n = int(n or self.ecfg.get("probes", 10))
        per_ds = int(self.ecfg.get("fields_per_dataset", 2))
        fams = Lifecycle(ctx, simulator=self.simulator).families()
        closed = {k for k, f in fams.items() if f.rows or f.queued}  # anything already tried or queued
        tried: dict[str, int] = {}
        for r in ctx.store.q("SELECT datasets FROM alphas WHERE status IN ('simulated','valid','simulating') "
                             "AND region=? AND delay=?", (ctx.scope["region"], ctx.scope["delay"])):
            for d in r.get("datasets") or []:
                tried[d] = tried.get(d, 0) + 1
        probes: list[tuple[dict, dict]] = []
        for d in self.datasets(tried, category):
            if len(probes) >= n:
                break
            for f in self.fields(d["id"], closed, per_ds):
                if len(probes) < n:
                    probes.append((f, d))
        if not probes:
            console.print("  nothing left to explore in the theme's datasets with the current filters")
            return []
        console.print(f"  exploring {len(probes)} untried field(s) across "
                      f"{len({d['id'] for _, d in probes})} dataset(s)")
        texts = self.describe(probes)
        neut = self.ecfg.get("neutralization") or None
        cands = []
        for f, d in probes:
            expr = self.expression(f)
            if not expr:
                continue
            t = texts.get(f["id"]) or {}
            sh = self.first_shape(f)
            if sh is not None and sh.id != "level":  # describe the research shape, not a plain ranking
                t = {"idea": f"{sh.idea[0].upper() + sh.idea[1:]} ({'; '.join(sh.sources)}), applied to {f['id']}.",
                     "rationale_data": f"{f['id']} ({d['id']}, {d.get('category')} category): {f.get('description')}",
                     "rationale_operators": f"the {sh.id} shape: {sh.template}; rank() keeps a uniform cross-sectional score."}
            raw = {"expression": expr, "neutralization": neut, "shape": sh.id if sh else "level",
                   "idea": t.get("idea") or f"{d.get('name')}: {f.get('description')}. Stocks ranked higher on this "
                                             "vendor signal are expected to outperform; one-field probe.",
                   "rationale_data": t.get("rationale_data") or f"{f['id']} ({d['id']}, {d.get('category')} category): "
                                                                f"{f.get('description')}",
                   "rationale_operators": t.get("rationale_operators") or "rank() turns the field into a uniform "
                                                                         "cross-sectional score; neutralization removes group effects."}
            c = self.gen.check(raw, origin="explore")
            cands.append(c)
        return cands
