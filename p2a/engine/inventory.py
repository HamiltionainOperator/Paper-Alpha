"""Signal inventory: every simulated idea of a scope, with what decides whether it can still feed a production alpha.

A production alpha on this account is a composite of several independent sources of non-price information (EUR #742
and #771, USA #499 / #516 / #605 / #692). Once a source is inside a submitted alpha, reusing it fails BRAIN's
self-correlation test, so the scarce resource is unused sources, not combining skill. For each simulated part of a
scope (few fields; composites are left out) the inventory records what the combiner needs:

- strength: Sharpe, fitness, returns, turnover, and the Sharpe of the last one and two years (the IS ladder);
- liquidity: sub-universe Sharpe / Sharpe (the sub-universe test needs about 0.43 in USA TOP3000, 0.52 in EUR TOP2500);
- crowding: the largest |PnL correlation| with the reference factors (references.py);
- use: the largest |PnL correlation| with the account's submitted alphas of the region, and data fields shared with them.

Each part gets one verdict, checked in this order: used, crowded, illiquid, weak, available. The measurements that never
change (PnL statistics, reference exposure) are cached in kv; the use test is redone on every call because the account's
submitted alphas change.
"""
from __future__ import annotations

import math

from . import references as refs
from .lifecycle import daily_pnl, pnl_correlation, submitted_alphas


def _key(scope: dict, aid: int) -> str:
    return f"inventory:{scope['region']}:{scope['delay']}:{scope['universe']}:{aid}"


def _sharpe(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    if len(xs) < 60:
        return None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return round(m / sd * math.sqrt(252), 2) if sd > 0 else None


def _check(row: dict, name: str):
    for c in row.get("checks") or []:
        if c.get("name") == name:
            return c.get("value")
    return None


def _same_scope(row: dict, scope: dict) -> bool:
    s = row.get("settings") or {}
    return ((s.get("region") or row.get("region")) == scope["region"]
            and (s.get("universe") or row.get("universe")) == scope["universe"]
            and int(s.get("delay", row.get("delay")) or 0) == int(scope["delay"]))


def part_fields(row: dict, generic: set) -> list[str]:
    return sorted(f for f in (row.get("fields") or []) if f not in generic)


def measure(ctx, simulator, row: dict, ref_pnls: dict) -> dict:
    """The facts about a part that do not depend on the account's submissions (cached)."""
    st = row.get("stats") or {}
    s = st.get("sharpe") or 0.0
    p = daily_pnl(ctx, simulator, row["brain_id"]) if row.get("brain_id") else {}
    xs = [p[d] for d in sorted(p)]
    ex = st.get("ref_exposures") or (refs.exposures(ctx, simulator, p, ref_pnls) if p and ref_pnls else {})
    top = max(ex.items(), key=lambda kv: abs(kv[1])) if ex else (None, None)
    sub = _check(row, "LOW_SUB_UNIVERSE_SHARPE")
    return {"id": row["id"], "sharpe": s, "fitness": st.get("fitness"), "turnover": st.get("turnover"),
            "returns": st.get("returns"), "last1y": _sharpe(xs[-252:]), "last2y": _sharpe(xs[-504:]),
            "sub_ratio": round(sub / s, 2) if sub is not None and s else None,
            "ref_corr": top[1], "ref_factor": top[0], "code": row.get("canonical") or row.get("expression"),
            "datasets": row.get("datasets") or []}


def verdict(rec: dict, cfg) -> str:
    c = cfg.section("inventory")
    if rec.get("shared_fields") or abs(rec.get("max_sub_corr") or 0) >= float(c.get("used_corr", 0.4)):
        return "used"
    if rec.get("ref_corr") is not None and abs(rec["ref_corr"]) >= refs.limit(cfg):
        return "crowded"
    # sub-universe Sharpe / Sharpe is the same for a signal and its negation, so negative parts are judged alike
    if rec.get("sub_ratio") is not None and rec["sub_ratio"] < float(c.get("illiquid_ratio", 0.3)):
        return "illiquid"
    if abs(rec.get("sharpe") or 0) < float(c.get("strong_sharpe", 0.8)):
        return "weak"
    return "available"


def build(eng, scope: dict, refresh: bool = False) -> list[dict]:
    """The inventory of `scope`, strongest available parts first."""
    c = eng.cfg.section("inventory")
    generic = set(c.get("generic_fields") or [])
    min_s = float(c.get("min_sharpe", 0.5))
    max_f = int(c.get("max_part_fields", 4))
    ctx = eng.context(scope, None, "regular")
    sim = eng.simulator if eng.client else None
    subs = [s for s in submitted_alphas(ctx) if s.get("region") == scope["region"]
            and int(s.get("delay") or 0) == int(scope["delay"])]
    sub_pnls = {s["id"]: daily_pnl(ctx, sim, s["id"]) for s in subs}
    sub_fields = {s["id"]: set(s.get("fields") or []) - generic for s in subs}
    ref_pnls = refs.pnls(ctx, sim)
    rows = [r for r in eng.store.q("SELECT * FROM alphas WHERE status='simulated' AND brain_id IS NOT NULL")
            if _same_scope(r, scope) and abs((r.get("stats") or {}).get("sharpe") or 0) >= min_s
            and 0 < len(part_fields(r, generic)) <= max_f]
    out = []
    for r in rows:
        rec = None if refresh else eng.store.kv_get(_key(scope, r["id"]))
        if rec is None:
            rec = measure(ctx, sim, r, ref_pnls)
            eng.store.kv_set(_key(scope, r["id"]), rec)
        p = daily_pnl(ctx, sim, r["brain_id"])
        corrs = {sid: pnl_correlation(p, sp, int(eng.cfg.get("lifecycle.correlation_days", 1000)))
                 for sid, sp in sub_pnls.items() if sp}
        corrs = {k: v for k, v in corrs.items() if v is not None}
        best = max(corrs.items(), key=lambda kv: abs(kv[1])) if corrs else (None, None)
        fields = set(part_fields(r, generic))
        shared = sorted({f for sid, fs in sub_fields.items() for f in fields & fs})
        rec = {**rec, "fields": sorted(fields), "max_sub_corr": round(best[1], 3) if best[1] is not None else None,
               "sub_with": best[0], "shared_fields": shared}
        rec["verdict"] = verdict(rec, eng.cfg)
        out.append(rec)
    order = {"available": 0, "weak": 1, "illiquid": 2, "crowded": 3, "used": 4}
    out.sort(key=lambda x: (order[x["verdict"]], -abs(x["sharpe"] or 0)))
    return out
