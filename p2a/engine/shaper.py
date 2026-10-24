"""Shape exploration: give fields that have shown signal their next research shapes.

A field whose level probe carried signal (or that trades like an alpha you already submitted) gets the shapes
the library says suit its kind of data and its update speed: changes, history-relative values, event gating,
spreads against its counterpart, orthogonalisation against the submitted signal it resembles, combinations with
an unrelated signal of the same dataset. Each shape on a field is its own idea family; the lifecycle and the
daily-PnL screen then decide, exactly as for every other alpha. Shape classes that keep working on a kind of data
are tried first (Thompson sampling on past results).
"""
from __future__ import annotations

from ..util import console, esc
from .context import Context
from .generator import Candidate, Generator
from .lifecycle import Lifecycle, daily_pnl, family_key, key_fields, pnl_correlation, shape_library
from .shapes import ShapeLibrary, shape_stats, similar_partner, thompson_order


class ShapeExplorer:
    def __init__(self, ctx: Context, generator: Generator, simulator=None):
        self.ctx = ctx
        self.gen = generator
        self.simulator = simulator
        self.scfg = ctx.cfg.section("shapes")
        self.lib = ShapeLibrary.load(ctx.cfg, ctx.catalog)
        self.floor = float(ctx.pp.get("min_sharpe", 1.0))

    def _field(self, fid: str) -> dict | None:
        return self.ctx.store.field(fid, self.ctx.scope)

    def bases(self, fams: dict) -> list[tuple[dict, object]]:
        """Single-field level families with signal (any state except artifacts / illiquid), strongest first."""
        min_s = float(self.scfg.get("base_min_sharpe", 0.5)) * self.floor
        skip = tuple(self.scfg.get("skip_reasons") or ("artifact", "illiquid"))
        out = []
        level = self.lib.default_class
        for key, f in fams.items():
            if not key.endswith(f"|{level}") or len(key_fields(key)) != 1 or not f.rows:
                continue
            if f.state == "dropped" and any(w in f.reason for w in skip):
                continue
            if max(abs(f.best_sharpe), abs(f.worst_sharpe)) < min_s:
                continue
            row = self._field(next(iter(key_fields(key))))
            if row:
                out.append((row, f))
        out.sort(key=lambda t: -max(abs(t[1].best_sharpe), abs(t[1].worst_sharpe)))
        return out

    # -- partners for two-field shapes ----------------------------------------------------------
    def partner(self, shape, x: dict, fam, fams: dict, submitted: list[dict]) -> dict | None:
        ctx = self.ctx
        if shape.pair == "similar":
            return similar_partner(self.lib, x, ctx.store.fields(ctx.scope, dataset=x.get("dataset")))
        if self.simulator is None or not fam.best or not fam.best.get("brain_id"):
            return None
        days = int(ctx.cfg.get("lifecycle.correlation_days", 1000))
        mine = daily_pnl(ctx, self.simulator, fam.best["brain_id"])
        if shape.pair == "submitted":
            # the submitted single-field alpha of the same category this signal trades most like
            best = None
            for a in submitted:
                fl = a.get("fields") or []
                if len(fl) != 1 or fl[0] == x["id"]:
                    continue
                y = self._field(fl[0])
                if not y or y.get("category") != x.get("category"):
                    continue
                c = pnl_correlation(mine, daily_pnl(ctx, self.simulator, a["id"]), days)
                if c is not None and c > float(self.scfg.get("orthogonal_min_corr", 0.3)) and (best is None or c > best[0]):
                    best = (c, y)
            return best[1] if best else None
        if shape.pair == "diverse":
            # the strongest other level signal of the same dataset that trades differently
            best = None
            level = self.lib.default_class
            for key, f in fams.items():
                if not key.endswith(f"|{level}") or len(key_fields(key)) != 1 or f is fam or not f.best:
                    continue
                if f.best_sharpe < float(self.scfg.get("base_min_sharpe", 0.5)) * self.floor:
                    continue
                y = self._field(next(iter(key_fields(key))))
                if not y or y.get("dataset") != x.get("dataset") or y["id"] == x["id"] or not f.best.get("brain_id"):
                    continue
                if f.state == "used":  # combining with a submitted signal keeps its exposure
                    continue
                c = pnl_correlation(mine, daily_pnl(ctx, self.simulator, f.best["brain_id"]), days)
                if c is not None and c < float(ctx.pp.get("correlation_limit", 0.5)) and (best is None or f.best_sharpe > best[0]):
                    best = (f.best_sharpe, y)
            return best[1] if best else None
        return None

    # -- proposals ------------------------------------------------------------------------------
    def proposals(self, n: int | None = None) -> list[dict]:
        ctx = self.ctx
        n = int(n or self.scfg.get("per_step", 10))
        per_base = int(self.scfg.get("per_field", 2))
        lc = Lifecycle(ctx, simulator=self.simulator)
        fams = lc.families()
        closed = set(fams)
        stats = shape_stats(ctx.store, self.lib, self.floor, ctx.scope)
        out = []
        for x, fam in self.bases(fams):
            if len(out) >= n:
                break
            kind = self.lib.kind_of(x)
            speed = self.lib.speed_of((fam.best.get("stats") or {}).get("turnover") if fam.best else None)
            shapes = [s for s in self.lib.for_field(x, speed=speed) if s.cls != self.lib.default_class]
            if fam.state == "used":
                if fam.reason.startswith("trades like"):
                    # its own information overlaps a submission: orthogonalise against it first
                    shapes = [s for s in shapes if s.fields == 1 or s.pair == "submitted"]
                else:
                    # the field itself is submitted: only new single-field transforms can be a different idea
                    shapes = [s for s in shapes if s.fields == 1]
            ordered = thompson_order(shapes, stats, kind)
            if fam.state == "used":
                ordered.sort(key=lambda s: s.pair != "submitted")
            done = 0
            for s in ordered:
                if done >= per_base or len(out) >= n:
                    break
                y = self.partner(s, x, fam, fams, lc.submitted) if s.fields == 2 else None
                if s.fields == 2 and y is None:
                    continue
                expr = self.lib.instantiate(s, x, y, speed)
                if not expr:
                    continue
                key = family_key([x["id"]] + ([y["id"]] if y else []), s.cls)
                if key in closed:
                    continue
                closed.add(key)
                done += 1
                settings = (fam.best or {}).get("settings") or {}
                sign = "" if fam.best_sharpe >= abs(fam.worst_sharpe) else "-"  # keep the probe's working sign
                out.append(self._raw(s, x, y, speed, f"{sign}({expr})" if sign else expr, settings, fam))
        return out

    def _raw(self, s, x: dict, y: dict | None, speed: str, expr: str, settings: dict, fam) -> dict:
        pair = f", paired with {y['id']} ({(y.get('description') or '')[:120]})" if y else ""
        return {
            "expression": expr, "shape": s.id,
            "neutralization": settings.get("neutralization"), "decay": settings.get("decay"),
            "hypothesis_id": (fam.best or {}).get("hypothesis_id"),
            "idea": f"{s.idea[0].upper() + s.idea[1:]} ({'; '.join(s.sources)}). Applied to {x['id']}, whose plain "
                    f"ranking already showed signal (Sharpe {fam.best_sharpe:.2f}){pair}.",
            "rationale_data": f"{x['id']} ({x.get('dataset')}, {x.get('category')} category): {x.get('description')}"
                              + (f"; {y['id']}: {y.get('description')}" if y else ""),
            "rationale_operators": f"the {s.id} shape ({s.cls}): {s.template}, with windows for a {speed}-changing field; "
                                   "rank() keeps the result a uniform cross-sectional score.",
        }

    def run(self, n: int | None = None) -> list[Candidate]:
        raws = self.proposals(n)
        if not raws:
            console.print("  no field with signal has an untried shape left")
            return []
        console.print(f"  {len(raws)} new shape(s) for fields that showed signal")
        return [self.gen.check(r, origin=f"shape:{r['shape']}") for r in raws]


def shapes_text(ctx: Context, fields: list[dict], k: int = 8) -> str:
    """Prompt section: the shapes that suit the kinds of data in this field list, best-performing first."""
    lib = ShapeLibrary.load(ctx.cfg, ctx.catalog)
    floor = float(ctx.pp.get("min_sharpe", 1.0))
    stats = shape_stats(ctx.store, lib, floor, ctx.scope)
    kinds = [lib.kind_of(f) for f in fields]
    has_vector = any((f.get("type") or "").upper() == "VECTOR" for f in fields)
    pool, seen = [], set()
    for kind in [k_ for k_ in dict.fromkeys(kinds) if k_]:
        for s in thompson_order([s for s in lib.shapes if s.available and kind in s.kinds], stats, kind):
            if s.id not in seen and (has_vector or not s.vector_only):
                seen.add(s.id)
                pool.append(s)
    by_class: dict = {}
    for (cls, kind), st in stats.items():
        if kind in kinds:
            agg = by_class.setdefault(cls, {"n": 0, "best": -9.0, "wins": 0})
            agg["n"] += st["n"]
            agg["wins"] += st["wins"]
            agg["best"] = max(agg["best"], st["best"])
    return lib.describe(pool[:k], by_class) if pool else "(no shape library loaded)"
