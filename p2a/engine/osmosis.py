"""Osmosis allocation plan: how many Osmosis points each submitted alpha should get, per scope (region x delay).

BRAIN computes the daily PnL of each consultant's Osmosis combo - points allocated across submitted alphas - and uses it
three ways (Learn: "Osmosis Allocation Guide for Consultants"): the multiplier on the daily base payment (1-2x, the
average of the consultant's per-scope ranks), Combined Osmosis Performance in Genius (after-cost Sharpe of the weekly
combos over the quarter) and the leaderboard's Daily Osmosis Rank. An allocation is valid only with at least
`min_scopes` scopes, each with exactly `points_per_scope` points over at least `min_alphas` alphas (config `osmosis`).

The plan is read-only: the consultant enters the points on the platform. For each scope it
- counts the submitted alphas against the minimum and reports how many are missing;
- applies the guide's exclusions: the investability-constrained Sharpe keeping less than `ic_keep_min` of the Sharpe
  (unless no other alpha of the scope uses its datasets), turnover above `turnover_soft_max` unless the constrained
  Sharpe keeps `ic_keep_high_turnover`, and the weaker of any pair whose daily PnL correlates above `max_pair_corr`;
  excluded alphas come back, best first, only when the scope would otherwise fall below the minimum;
- weights the rest to maximize the Sharpe of the combined in-sample daily PnL after an assumed trading cost
  (out-of-sample PnL is hidden), with the covariance shrunk toward its diagonal and each alpha's Sharpe shrunk toward
  the scope's mean so that estimation noise does not crown a few lucky alphas; weights stay in [min_weight, max_weight];
- turns the weights into integer points that add up to exactly `points_per_scope`.
"""
from __future__ import annotations

import math

from .lifecycle import daily_pnl, pnl_correlation, submitted_alphas

PP_ELIGIBLE = "POWER_POOL:POWER_POOL_ELIGIBLE"


def _ann_sharpe(xs: list[float]) -> float | None:
    if len(xs) < 60:
        return None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return round(m / sd * math.sqrt(252), 2) if sd > 0 else None


def _project(v: list[float], lo: float, hi: float) -> list[float]:
    """Euclidean projection onto {lo <= w_i <= hi, sum w = 1} (bisection on the shift)."""
    a, b = min(v) - hi - 1.0, max(v) - lo + 1.0
    for _ in range(100):
        t = (a + b) / 2
        if sum(min(hi, max(lo, x - t)) for x in v) > 1:
            a = t
        else:
            b = t
    t = (a + b) / 2
    return [min(hi, max(lo, x - t)) for x in v]


def max_sharpe_weights(series: list[list[float]], lo: float, hi: float, shrink_cov: float = 0.5,
                       shrink_sharpe: float = 0.5, iters: int = 400) -> list[float]:
    """Long-only weights in [lo, hi] summing to 1 that maximize the Sharpe of sum_i w_i x_i (x_i: aligned daily PnL)."""
    n = len(series)
    if n == 0:
        return []
    lo, hi = min(lo, 0.5 / n), max(hi, 1.0 / n)  # a floor above 1/n would force equal weights
    T = len(series[0])
    mu = [sum(x) / T for x in series]
    dev = [[v - m for v in x] for x, m in zip(series, mu)]
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            c = sum(a * b for a, b in zip(dev[i], dev[j])) / max(T - 1, 1)
            cov[i][j] = cov[j][i] = c if i == j else (1 - shrink_cov) * c
    sd = [math.sqrt(cov[i][i]) if cov[i][i] > 0 else 1e-12 for i in range(n)]
    sr = [m / s for m, s in zip(mu, sd)]
    bar = sum(sr) / n
    mu = [s * ((1 - shrink_sharpe) * r + shrink_sharpe * bar) for s, r in zip(sd, sr)]

    def sharpe(w):
        var = sum(w[i] * cov[i][j] * w[j] for i in range(n) for j in range(n))
        return sum(a * b for a, b in zip(w, mu)) / math.sqrt(var) if var > 0 else 0.0

    iv = [1 / s for s in sd]  # start from inverse volatility: every alpha carries about the same risk
    w = _project([x / sum(iv) for x in iv], lo, hi)
    best, best_s, step = w, sharpe(w), 0.5
    for _ in range(iters):
        cw = [sum(cov[i][j] * w[j] for j in range(n)) for i in range(n)]
        var = sum(a * b for a, b in zip(w, cw))
        if var <= 0:
            break
        vol, ret = math.sqrt(var), sum(a * b for a, b in zip(w, mu))
        g = [mu[i] / vol - ret * cw[i] / vol ** 3 for i in range(n)]
        gn = math.sqrt(sum(x * x for x in g)) or 1.0
        cand = _project([w[i] + step * g[i] / gn for i in range(n)], lo, hi)
        s = sharpe(cand)
        if s > best_s + 1e-12:
            best, best_s, w = cand, s, cand
        else:
            step *= 0.6
            if step < 1e-5:
                break
    return best


def to_points(weights: list[float], total: int) -> list[int]:
    """Integer points proportional to `weights`, each >= 1, adding up to exactly `total` (largest remainders)."""
    raw = [w * total for w in weights]
    pts = [max(1, int(math.floor(r))) for r in raw]
    left = total - sum(pts)
    order = sorted(range(len(raw)), key=lambda i: -(raw[i] - math.floor(raw[i])))
    k = 0
    while left != 0 and order and k < 10 * len(order) * (abs(left) + 1):
        i = order[k % len(order)]
        if left > 0:
            pts[i] += 1
            left -= 1
        elif pts[i] > 1:
            pts[i] -= 1
            left += 1
        k += 1
    return pts


def _datasets(store, row: dict) -> tuple[list, list]:
    scope = {"region": row.get("region"), "delay": row.get("delay"), "universe": row.get("universe")}
    ds, cats = set(), set()
    if scope["region"] and scope["delay"] is not None and scope["universe"]:
        for f in row.get("fields") or []:
            rec = store.field(f, scope)
            if rec:
                ds.add(rec.get("dataset"))
                cats.add(rec.get("category"))
    return sorted(d for d in ds if d), sorted(c for c in cats if c)


def _combo_sharpe(recs: list[dict], weights: list[float]) -> float | None:
    common = sorted(set.intersection(*(set(r["pnl"]) for r in recs))) if recs else []
    return _ann_sharpe([sum(w * r["pnl"][d] for w, r in zip(weights, recs)) for d in common])


def exclude(recs: list[dict], ic_min: float, to_max: float, ic_hi_to: float, max_corr: float, days: int) -> None:
    """Mark each alpha with the guide's reason to leave it out (None = keep); stronger alphas are judged first."""
    for r in recs:
        r["excluded"], r["note"], r["max_corr"] = None, "", None
        if not r["pnl"]:
            r["excluded"] = "no PnL"
            continue
        others = {d for o in recs if o is not r for d in o["datasets"]}
        if r["ic_keep"] is not None and r["ic_keep"] < ic_min:
            if r["datasets"] and not set(r["datasets"]) & others:
                r["note"] = "low investability kept: only alpha on its datasets"
            else:
                r["excluded"] = f"investability keeps {r['ic_keep']:.0%}"
        elif r["turnover"] > to_max and (r["ic_keep"] is None or r["ic_keep"] < ic_hi_to):
            if r["ic_keep"] is None:
                r["note"] = f"turnover {r['turnover']:.0%}: verify with MaxTrade on"
            else:
                r["excluded"] = f"turnover {r['turnover']:.0%}, investability keeps {r['ic_keep']:.0%}"
    kept = []
    for r in sorted(recs, key=lambda r: -(r["net_sharpe"] or -9)):
        if r["excluded"]:
            continue
        corrs = [(abs(pnl_correlation(r["pnl"], k["pnl"], days) or 0.0), k) for k in kept]
        top = max(corrs, key=lambda t: t[0]) if corrs else (0.0, None)
        r["max_corr"] = round(top[0], 2) if top[1] else None
        if top[1] is not None and top[0] > max_corr:
            r["excluded"] = f"corr {top[0]:.2f} with {top[1]['id']}"
            continue
        kept.append(r)


def scope_plan(name: str, recs: list[dict], c: dict) -> dict:
    """Exclusions, weights and points for the alphas of one scope (recs carry pnl, sharpe, ic_keep, turnover, ...)."""
    min_alphas, total = int(c.get("min_alphas", 10)), int(c.get("points_per_scope", 100000))
    exclude(recs, float(c.get("ic_keep_min", 0.4)), float(c.get("turnover_soft_max", 0.2)),
            float(c.get("ic_keep_high_turnover", 0.7)), float(c.get("max_pair_corr", 0.7)),
            int(c.get("correlation_days", 1000)))
    chosen = [r for r in recs if not r["excluded"]]
    if len(chosen) < min_alphas:  # the platform's minimum wins over the guide's exclusions
        back = sorted((r for r in recs if r["excluded"] and r["pnl"]), key=lambda r: -(r["net_sharpe"] or -9))
        for r in back[:min_alphas - len(chosen)]:
            r["note"], r["excluded"] = f"fill-in ({r['excluded']})", None
            chosen.append(r)
    sc = {"scope": name, "submitted": len(recs), "needed": max(0, min_alphas - len(recs)), "rows": recs,
          "allocated_now": sum(r["points_now"] for r in recs), "alphas_now": sum(1 for r in recs if r["points_now"]),
          "combo": None}
    sc["valid_now"] = sc["allocated_now"] == total and sc["alphas_now"] >= min_alphas
    held = [r for r in recs if r["points_now"] and r["pnl"]]
    current = _combo_sharpe(held, [r["points_now"] / sc["allocated_now"] for r in held]) if held else None
    if len(chosen) < min_alphas:
        return sc
    common = sorted(set.intersection(*(set(r["pnl"]) for r in chosen)))
    if len(common) < 250:
        return sc
    X = [[r["pnl"][d] for d in common] for r in chosen]
    w = max_sharpe_weights(X, float(c.get("min_weight", 0.02)), float(c.get("max_weight", 0.2)),
                           float(c.get("shrink_cov", 0.5)), float(c.get("shrink_sharpe", 0.5)))
    for r, p in zip(chosen, to_points(w, total)):
        r["points"] = p
    sc["combo"] = {"proposed": _combo_sharpe(chosen, w), "equal": _combo_sharpe(chosen, [1 / len(chosen)] * len(chosen)),
                   "current": current, "days": len(common), "alphas": len(chosen)}
    return sc


def plan(eng, refresh: bool = False) -> dict:
    """The Osmosis plan for every scope the account has submitted alphas in."""
    c = eng.cfg.section("osmosis")
    cost = float(c.get("cost_bps", 0.0)) / 1e4
    ctx = eng.context(eng.scope("USA"), None, "regular")
    sim = eng.simulator if eng.client else None
    local = {r["brain_id"]: r["id"] for r in eng.store.q("SELECT id, brain_id FROM alphas WHERE brain_id IS NOT NULL")}
    groups: dict[str, list[dict]] = {}
    for s in submitted_alphas(ctx, max_age_s=0 if refresh else None):
        st = s.get("stats") or {}
        p = daily_pnl(ctx, sim, s["id"])
        sh, ic, to = st.get("sharpe"), st.get("ic_sharpe"), st.get("turnover") or 0.0
        drag = to * (st.get("book") or 0.0) * cost  # assumed daily trading cost, in PnL units
        net = {d: v - drag for d, v in p.items()}
        ds, cats = _datasets(eng.store, s)
        groups.setdefault(f"{s.get('region')}/D{s.get('delay')}", []).append({
            "id": s["id"], "local": local.get(s["id"]), "sharpe": sh, "ic_sharpe": ic, "turnover": to,
            "ic_keep": round(ic / sh, 2) if ic is not None and sh else None,
            "pp": PP_ELIGIBLE in (s.get("classifications") or []), "datasets": ds, "categories": cats,
            "points_now": s.get("osmosis_points") or 0, "pnl": net,
            "net_sharpe": _ann_sharpe([net[d] for d in sorted(net)]) if net else None})
    scopes = [scope_plan(name, recs, c) for name, recs in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
    return {"scopes": scopes, "plannable": sum(1 for s in scopes if s["combo"]),
            "valid_now": sum(1 for s in scopes if s["valid_now"]), "min_scopes": int(c.get("min_scopes", 3)),
            "min_alphas": int(c.get("min_alphas", 10)), "points_per_scope": int(c.get("points_per_scope", 100000)),
            "cost_bps": c.get("cost_bps", 0.0)}
