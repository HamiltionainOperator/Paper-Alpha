"""Submission routes: pure Power Pool alphas and regular (production) alphas, and what BRAIN pays more for.

BRAIN accepts two kinds of alpha (BRAIN Learn: "Power Pool Alphas", "Consultant Submission Tests"):

- pure Power Pool alphas: simple (few operators and fields), Sharpe >= 1.0, matching the active theme, weakly
  correlated with your other Power Pool alphas; a small daily and monthly quota;
- regular alphas: every consultant test must PASS - the Sharpe and fitness bars, turnover, weight, sub-universe,
  the 2-year Sharpe (and the IS ladder, which single-dataset ATOM alphas may skip), self-correlation < 0.7 and
  production correlation < 0.7 (the largest daily-PnL correlation with any alpha in BRAIN's consultant pool, unless
  the Sharpe is 10% higher). An alpha that is Power Pool eligible and passes every regular test is both
  ([Power Pool + Regular]) and does not count against the pure Power Pool quota.

Base payments carry quality-factor multipliers that BRAIN reports with every simulation (MATCHES_PYRAMID,
MATCHES_THEMES): the pyramid multiplier (region x delay x data category; higher for under-used pyramids) and theme
multipliers (for example a universe theme). They are read from the checks and from
/users/self/activities/pyramid-multipliers, never hard-coded. How BRAIN combines them into a payment is not
published; the engine only uses their product to order candidates.
"""
from __future__ import annotations

import re
import time

ROUTES = ("power_pool", "regular")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def route_of(ctx) -> str:
    return getattr(ctx, "route", None) or "power_pool"


def status_key(route: str) -> str:
    return "reg_status" if route == "regular" else "pp_status"


def reasons_key(route: str) -> str:
    return "reg_reasons" if route == "regular" else "pp_reasons"


def regular_bar(checks: list[dict] | None, rc: dict) -> float:
    """BRAIN's own Sharpe bar for this alpha (the LOW_SHARPE limit), else the configured one."""
    for c in checks or []:
        if c.get("name") == "LOW_SHARPE" and _f(c.get("limit")):
            return float(c["limit"])
    return float(rc.get("min_sharpe", 1.58))


def is_atom(classifications, datasets, rc: dict) -> bool:
    """Single-dataset alphas are ATOM alphas: BRAIN lets them skip the IS ladder (not the 2-year Sharpe)."""
    want = rc.get("atom_classification", "DATA_USAGE:SINGLE_DATA_SET")
    ids = {c.get("id") if isinstance(c, dict) else c for c in classifications or []}
    return want in ids or len(set(datasets or [])) == 1


MEASURED = ("prod_corr", "prod_crowd", "self_corr", "self_with", "self_with_sharpe", "ref_corr", "ref_factor", "ref_exposures")


def correlation_stats(prod: dict | None, self_: dict | None) -> dict:
    """Uniqueness numbers from /alphas/{id}/correlations/prod and /self: the largest correlation with any production
    alpha, how many production alphas sit at 0.5 or above (how crowded the neighbourhood is), and the closest of
    your own alphas with its Sharpe (BRAIN lets a correlated alpha through when its Sharpe is 10% higher)."""
    out: dict = {}
    if prod and prod.get("max") is not None:
        out["prod_corr"] = round(float(prod["max"]), 4)
        out["prod_crowd"] = sum(int(r[2] or 0) for r in prod.get("records") or []
                                if isinstance(r, list) and len(r) >= 3 and _f(r[0]) is not None and _f(r[0]) >= 0.5)
    if self_ and self_.get("max") is not None:
        out["self_corr"] = round(float(self_["max"]), 4)
        names = [p.get("name") for p in ((self_.get("schema") or {}).get("properties") or [])]
        rows = [dict(zip(names, r)) for r in self_.get("records") or [] if isinstance(r, list)]
        top = max(rows, key=lambda r: _f(r.get("correlation")) or -1.0, default=None)
        if top:
            out["self_with"], out["self_with_sharpe"] = top.get("id"), _f(top.get("sharpe"))
    return out


def regular_verdict(checks: list[dict], stats: dict, rc: dict, atom: bool = False) -> tuple[str, list[str]]:
    """eligible | pending | near_miss | fail for the regular route, from BRAIN's own check results.

    Every check except the informational ones (themes, pyramids, Osmosis, cluster tag, Power Pool correlation) must
    PASS: BRAIN shows a regular test that a Power Pool alpha is exempt from as WARNING, and for a regular
    submission that is a failure. Correlation checks stay PENDING until BRAIN computes them; values measured with
    the correlation endpoints (`correlation_stats`) stand in for them."""
    measured = {"PROD_CORRELATION": (_f((stats or {}).get("prod_corr")), float(rc.get("prod_correlation_limit", 0.7))),
                "SELF_CORRELATION": (_f((stats or {}).get("self_corr")), float(rc.get("self_correlation_limit", 0.7)))}
    info = set(rc.get("info_checks") or [])
    quota = set(rc.get("quota_checks") or [])
    skip = set(rc.get("atom_skips") or []) if atom else set()
    soft = set(rc.get("near_miss_checks") or [])
    blocking, hard, pending, waits = [], False, [], []
    for c in checks or []:
        name, res = c.get("name"), c.get("result")
        if not name or name in info:
            continue
        if name in quota:
            if res == "FAIL":
                waits.append(f"WAIT: {name} quota used ({c.get('value')}/{c.get('limit')})")
            continue
        if name in skip:
            continue
        if res in ("FAIL", "WARNING"):
            v, lim = c.get("value"), c.get("limit")
            blocking.append(f"{name} {res}" + (f" (value {v}, limit {lim})" if v is not None or lim is not None else ""))
            hard = hard or name not in soft
        elif res != "PASS":  # PENDING, or ERROR when BRAIN could not compute the test: not passed yet
            v, lim = measured.get(name, (None, None))
            if v is None:
                pending.append(name if res == "PENDING" else f"{name} (BRAIN returned {res}; ask again)")
                continue
            better = _f((stats or {}).get("self_with_sharpe"))
            if name == "SELF_CORRELATION" and better and (_f((stats or {}).get("sharpe")) or 0) >= 1.1 * better:
                continue  # BRAIN accepts a correlated alpha whose Sharpe is 10% higher
            if v >= lim:
                blocking.append(f"{name} {v:.2f} >= {lim} (measured)")
                hard = hard or name not in soft
    sharpe = _f((stats or {}).get("sharpe")) or 0.0
    bar = regular_bar(checks, rc)
    if not checks:  # offline: judge from the statistics alone
        if sharpe < bar:
            blocking.append(f"LOW_SHARPE {sharpe:.2f} < {bar}")
        fit = _f((stats or {}).get("fitness"))
        if fit is not None and fit < float(rc.get("min_fitness", 1.0)):
            blocking.append(f"LOW_FITNESS {fit:.2f} < {rc.get('min_fitness', 1.0)}")
        pending.append("checks")
    if blocking:
        near = float(rc.get("near_miss_fraction", 0.8))
        status = "near_miss" if (not hard and sharpe >= near * bar) else "fail"
        return status, blocking + waits
    if pending:
        return "pending", [f"waiting for {', '.join(pending)}"] + waits
    return "eligible", waits


# -- quality-factor multipliers ------------------------------------------------------------------------
def multipliers(checks: list[dict] | None) -> dict:
    """Pyramid and theme multipliers BRAIN reports for an alpha. `theme` is the best matched theme multiplier
    (pyramid themes are the pyramid multiplier again and are not counted twice); `missed` lists themes the alpha
    did not match (a hint, e.g. a universe theme)."""
    out = {"pyramid": None, "pyramids": [], "theme": 1.0, "matched": [], "missed": []}
    for c in checks or []:
        if c.get("name") == "MATCHES_PYRAMID":
            out["pyramid"] = _f(c.get("multiplier"))
            out["pyramids"] = [p.get("name") for p in c.get("pyramids") or []]
        elif c.get("name") == "MATCHES_THEMES":
            for t in c.get("themes") or []:
                item = {"id": t.get("id"), "name": t.get("name"), "multiplier": _f(t.get("multiplier")) or 1.0}
                if "pyramid" in (t.get("name") or "").lower():
                    continue
                (out["matched"] if c.get("result") == "PASS" else out["missed"]).append(item)
    if out["matched"]:
        out["theme"] = max(t["multiplier"] for t in out["matched"])
    return out


def multiplier_product(checks: list[dict] | None) -> float:
    m = multipliers(checks)
    return round((m["pyramid"] or 1.0) * (m["theme"] or 1.0), 3)


def record_themes(store, checks: list[dict] | None, scope: dict) -> None:
    """Remember the themes BRAIN lists in checks (name, multiplier, the scope they were seen in)."""
    seen = store.kv_get("observed_themes") or {}
    changed = False
    for c in checks or []:
        if c.get("name") != "MATCHES_THEMES":
            continue
        for t in c.get("themes") or []:
            if not t.get("id") or "pyramid" in (t.get("name") or "").lower():
                continue
            seen[t["id"]] = {"name": t.get("name"), "multiplier": _f(t.get("multiplier")) or 1.0,
                             "region": scope.get("region"), "delay": scope.get("delay"), "seen_at": time.time()}
            changed = True
    if changed:
        store.kv_set("observed_themes", seen)


def theme_universe(store, scope: dict, allowed: list | None, max_age_days: float = 3.0) -> tuple[str | None, dict | None]:
    """The universe a currently observed multiplier theme of this region and delay names (e.g. 'USA/D1 TOP1000
    Theme' -> TOP1000), if it is a universe BRAIN allows for the region. Returns (universe, theme)."""
    best = None
    now = time.time()
    for tid, t in (store.kv_get("observed_themes") or {}).items():
        if (t.get("multiplier") or 1.0) <= 1.0 or now - (t.get("seen_at") or 0) > max_age_days * 86400:
            continue
        if t.get("region") != scope.get("region") or int(t.get("delay") if t.get("delay") is not None else -1) != int(scope["delay"]):
            continue
        name = t.get("name") or ""
        if re.search(r"power\s*pool|pyramid", name, re.I):
            continue
        for u in allowed or []:
            if re.search(rf"\b{re.escape(str(u))}\b", name, re.I) and (best is None or t["multiplier"] > best[1]["multiplier"]):
                best = (str(u), {"id": tid, **t})
    return (best[0], best[1]) if best else (None, None)


def pyramid_multipliers(ctx, max_age_s: float = 86400) -> dict[str, float]:
    """{'USA/1/model': 1.3, ...} from /users/self/activities/pyramid-multipliers (cached a day)."""
    cached = ctx.store.kv_get("pyramid_multipliers", max_age_s=max_age_s)
    if cached is not None:
        return cached
    client = getattr(getattr(ctx, "sync", None), "client", None)
    if client is None:
        return ctx.store.kv_get("pyramid_multipliers") or {}
    try:
        data = client.get_json(ctx.cfg.get("regular.pyramid_endpoint", "/users/self/activities/pyramid-multipliers"))
    except Exception:
        return ctx.store.kv_get("pyramid_multipliers") or {}
    out = {}
    for p in (data or {}).get("pyramids") or []:
        cat = (p.get("category") or {}).get("id")
        if cat and p.get("region") is not None:
            out[f"{p['region']}/{p.get('delay')}/{cat}"] = _f(p.get("multiplier")) or 1.0
    ctx.store.kv_set("pyramid_multipliers", out)
    return out


def pyramid_of(ctx, category: str | None) -> float:
    if not category:
        return 1.0
    return pyramid_multipliers(ctx).get(f"{ctx.scope['region']}/{ctx.scope['delay']}/{category}", 1.0)


# -- prompt block ------------------------------------------------------------------------------------
def route_text(ctx) -> str:
    """What the candidates are for: the rules of the submission route, in the prompt."""
    route = route_of(ctx)
    if route != "regular":
        lim = ctx.pp.get("correlation_limit", 0.5)
        return (f"Power Pool alphas (simple, Sharpe >= {ctx.pp.get('min_sharpe', 1.0)}, matching the theme). Your Power "
                f"Pool alphas must be less than {lim} correlated with each other, and BRAIN pays more for alphas that "
                "are weakly correlated with the alphas already in production, so prefer data and constructions few "
                "consultants use.")
    rc = ctx.cfg.section("regular")
    return "\n".join([
        f"REGULAR (production) consultant alphas. BRAIN's submission check must PASS every test: Sharpe >= "
        f"{rc.get('min_sharpe', 1.58)}; fitness >= {rc.get('min_fitness', 1.0)} (fitness = Sharpe * "
        "sqrt(|annual return| / max(turnover, 0.125)), so a low-turnover signal with solid returns passes more "
        "easily); turnover between 1% and 70%; no stock above 10% of the book; the liquid sub-universe and the "
        "most recent two years must hold up; self-correlation and production correlation below "
        f"{rc.get('prod_correlation_limit', 0.7)}.",
        "- Production correlation is the largest daily-PnL correlation with ANY alpha in BRAIN's consultant pool. "
        "Thousands of consultants already rank the popular vendor forecasts, so a plain rank of a popular field is "
        "a copy. BRAIN's guidance: low correlation matters more than a small Sharpe gain.",
        "- What makes an alpha unique: data few alphas use (low alpha count, high pyramid multiplier); changes, "
        "surprises and revisions rather than static levels; short-lived information (the production pool is "
        "dominated by slow signals); two economically linked signals from different data sources combined "
        "(each is a noisy view of the same mechanism, so together they are stronger and less like either one); "
        "risk-factor neutralization settings (SLOW, FAST, SLOW_AND_FAST, CROWDING, STATISTICAL, "
        "REVERSION_AND_MOMENTUM) that remove the common style exposure production alphas share.",
        "- Never add noise or an unrelated signal just to lower correlation (BRAIN's Dos and Don'ts); every part "
        "needs an economic reason.",
    ])
