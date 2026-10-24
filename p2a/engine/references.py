"""Crowded reference factors: a local stand-in for BRAIN's production-correlation test.

BRAIN's correlation endpoints answer only a few requests an hour, and production is full of the same few price-based
factors (short-term reversal, momentum, size, low volatility, volume-price, value, estimate revisions). An idea on
rarely used data can still be one of them in disguise: on this account ETF flow growth (0.925 with production) and an
equity-minus-bond-implied return (0.895) were mostly the stock's own past return. Each reference in
`uniqueness.references` (config.yaml) is simulated once; a new alpha whose daily PnL correlates with one of them above
`uniqueness.reference_limit` carries that factor, however unusual its fields, and is flagged before any correlation
request is spent on it.

References are simulated straight through the simulator and kept in kv (`reference:<scope>:<id>`), not as alpha rows,
so they never enter families, combinations or the submission queue.
"""
from __future__ import annotations

from ..brain import SimJob
from ..util import console
from .lifecycle import daily_pnl, pnl_correlation


def _key(ctx, rid: str) -> str:
    s = ctx.scope
    return f"reference:{s['region']}:{s['delay']}:{s['universe']}:{rid}"


def specs(cfg) -> list[dict]:
    return list(cfg.get("uniqueness.references") or [])


def _settled(rec: dict, r: dict) -> bool:
    """Simulated, or already failed in this scope with the same expression (a field the region does not have):
    either way there is nothing to simulate again."""
    return rec.get("expression") == r["expression"] and bool(rec.get("brain_id") or rec.get("error"))


def ensure(ctx, simulator, build_settings) -> int:
    """Simulate the references this scope has not got yet; returns how many were simulated."""
    missing = [r for r in specs(ctx.cfg) if not _settled(ctx.store.kv_get(_key(ctx, r["id"])) or {}, r)]
    if not missing or simulator is None:
        return 0
    jobs = []
    for i, r in enumerate(missing):
        settings, _ = build_settings({"neutralization": r.get("neutralization"), "decay": r.get("decay"),
                                      "truncation": r.get("truncation")})
        jobs.append(SimJob(key=i, payload={"type": "REGULAR", "settings": settings, "regular": r["expression"]}))
    console.print(f"  simulating {len(jobs)} reference factor(s)")
    simulator.run(jobs)
    n = 0
    for job, r in zip(jobs, missing):
        if job.status == "done" and job.alpha_id:
            st = ((job.alpha or {}).get("is") or {})
            ctx.store.kv_set(_key(ctx, r["id"]), {"brain_id": job.alpha_id, "expression": r["expression"],
                                                  "sharpe": st.get("sharpe"), "turnover": st.get("turnover")})
            console.print(f"   {r['id']}: Sharpe {st.get('sharpe')} turnover {st.get('turnover')}")
            n += 1
        else:
            transient = any(t in (job.message or "") for t in ("timed out", "could not fetch"))
            if job.status == "error" and not transient:  # BRAIN rejected it (e.g. an unknown field here)
                ctx.store.kv_set(_key(ctx, r["id"]), {"expression": r["expression"], "error": (job.message or "")[:300]})
            console.print(f"   {r['id']}: [red]{(job.message or 'failed')[:120]}[/red]")
    return n


def pnls(ctx, simulator) -> dict[str, dict]:
    out = {}
    for r in specs(ctx.cfg):
        rec = ctx.store.kv_get(_key(ctx, r["id"])) or {}
        if rec.get("brain_id"):
            p = daily_pnl(ctx, simulator, rec["brain_id"])
            if p:
                out[r["id"]] = p
    return out


def exposures(ctx, simulator, pnl: dict, refs: dict[str, dict] | None = None) -> dict[str, float]:
    """Daily-PnL correlation of an alpha with every reference factor."""
    refs = pnls(ctx, simulator) if refs is None else refs
    days = int(ctx.cfg.get("lifecycle.correlation_days", 1000))
    out = {}
    for rid, rp in refs.items():
        v = pnl_correlation(pnl, rp, days)
        if v is not None:
            out[rid] = round(v, 3)
    return out


def exposure(ctx, simulator, pnl: dict, refs: dict[str, dict] | None = None) -> tuple[float | None, str | None]:
    """The largest absolute daily-PnL correlation of an alpha with any reference factor, and which one."""
    ex = exposures(ctx, simulator, pnl, refs)
    if not ex:
        return None, None
    name = max(ex, key=lambda k: abs(ex[k]))
    return ex[name], name


def row_exposure(ctx, simulator, row: dict, refs: dict[str, dict] | None = None) -> tuple[float | None, str | None]:
    if not row.get("brain_id"):
        return None, None
    p = daily_pnl(ctx, simulator, row["brain_id"])
    return exposure(ctx, simulator, p, refs) if p else (None, None)


def row_exposures(ctx, simulator, row: dict, refs: dict[str, dict] | None = None) -> dict[str, float]:
    if not row.get("brain_id"):
        return {}
    p = daily_pnl(ctx, simulator, row["brain_id"])
    return exposures(ctx, simulator, p, refs) if p else {}


def tilts(stats: dict, cfg) -> list[str]:
    """The reference factors an alpha leans on enough to matter for production correlation (|corr| >=
    uniqueness.tilt_min), largest first, at most uniqueness.max_tilts."""
    ex = stats.get("ref_exposures") or {}
    lim = float(cfg.get("uniqueness.tilt_min", 0.2))
    keep = sorted((k for k, v in ex.items() if abs(v) >= lim), key=lambda k: -abs(ex[k]))
    return keep[: int(cfg.get("uniqueness.max_tilts", 2))]


def limit(cfg) -> float:
    return float(cfg.get("uniqueness.reference_limit", 0.5))
