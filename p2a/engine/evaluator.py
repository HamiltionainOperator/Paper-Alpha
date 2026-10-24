"""Judge simulated alphas against the Power Pool rules from config.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .routes import MEASURED, is_atom, multipliers, regular_verdict


@dataclass
class Evaluation:
    status: str                      # eligible | pending | near_miss | fail
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0
    stats: dict = field(default_factory=dict)
    theme_matches: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    reg_status: str | None = None        # the regular (production) route: eligible | pending | near_miss | fail
    reg_reasons: list[str] = field(default_factory=list)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def score(stats: dict, w: dict) -> float:
    sharpe = _f(stats.get("sharpe")) or 0.0
    fitness = _f(stats.get("fitness")) or 0.0
    turnover = _f(stats.get("turnover")) or 0.0
    margin_bps = (_f(stats.get("margin")) or 0.0) * 1e4
    s = w.get("sharpe", 1.0) * sharpe + w.get("fitness", 0.35) * fitness
    s += w.get("margin_bps", 0.05) * max(-w.get("margin_cap_bps", 20), min(margin_bps, w.get("margin_cap_bps", 20)))
    s -= w.get("turnover_penalty", 2.0) * max(0.0, turnover - w.get("turnover_soft_cap", 0.35))
    return round(s, 4)


def quality_issues(alpha: dict, stats: dict, checks: list[dict], q: dict) -> list[str]:
    """The engine's own gates for after-cost robustness, beyond the platform's Power Pool checks."""
    out = []
    longs, shorts = _f(stats.get("longCount")), _f(stats.get("shortCount"))
    if longs is not None and shorts is not None:
        if longs == 0 or shorts == 0:
            out.append(f"ONE_SIDED portfolio (long {int(longs)}, short {int(shorts)}): the alpha is mostly market exposure")
        else:
            m = re.search(r"(\d+)", str((alpha.get("settings") or {}).get("universe") or ""))
            frac = float(q.get("min_side_fraction", 0) or 0)
            if m and frac:
                need = int(m.group(1)) * frac
                if min(longs, shorts) < need:
                    out.append(f"NARROW portfolio (long {int(longs)}, short {int(shorts)}; want >= {int(need)} names per side)")
    sharpe, ic = _f(stats.get("sharpe")), _f(stats.get("ic_sharpe"))
    ratio = float(q.get("min_ic_sharpe_ratio", 0) or 0)
    if sharpe and sharpe > 0 and ic is not None and ratio and ic < ratio * sharpe:
        out.append(f"INVESTABILITY: constrained Sharpe {ic:.2f} keeps < {ratio:.0%} of Sharpe {sharpe:.2f} (after-cost risk)")
    cap = float(q.get("max_concentrated_weight", 0) or 0)
    for c in checks:
        if cap and c.get("name") == "CONCENTRATED_WEIGHT" and _f(c.get("value")) is not None and _f(c.get("value")) > cap:
            out.append(f"CONCENTRATED: a single stock reached {_f(c.get('value')):.0%} of the book")
    return out


def evaluate(alpha: dict, pp: dict, weights: dict, refine_cfg: dict, structural: dict | None = None,
             quality: dict | None = None, regular: dict | None = None, datasets: list | None = None,
             measured: dict | None = None) -> Evaluation:
    is_ = alpha.get("is") or {}
    stats = {k: is_.get(k) for k in ("sharpe", "fitness", "turnover", "returns", "drawdown", "margin",
                                     "longCount", "shortCount")}
    ic = is_.get("investabilityConstrained") or {}
    if isinstance(ic, dict):
        stats["ic_sharpe"] = ic.get("sharpe")
    rn = is_.get("riskNeutralized") or {}
    if isinstance(rn, dict) and rn.get("sharpe") is not None:  # what is left after BRAIN's risk-factor model
        stats.update(rn_sharpe=rn.get("sharpe"), rn_returns=rn.get("returns"), rn_fitness=rn.get("fitness"))
    checks = is_.get("checks") or []
    for name, key in (("PROD_CORRELATION", "prod_corr"), ("SELF_CORRELATION", "self_corr")):
        for c in checks:
            if c.get("name") == name and c.get("value") is not None:
                stats[key] = c.get("value")
    for k in MEASURED:  # correlations measured with the fast endpoints, kept until BRAIN's check reports its own
        if stats.get(k) is None and (measured or {}).get(k) is not None:
            stats[k] = measured[k]
    m = multipliers(checks)
    if m["pyramid"] is not None or m["matched"]:
        stats["mult"] = round((m["pyramid"] or 1.0) * (m["theme"] or 1.0), 3)
    pattern = re.compile(pp.get("theme_name_pattern", r"(?i)power\s*pool"))
    reasons: list[str] = []

    sharpe = _f(stats.get("sharpe")) or 0.0
    min_sharpe = float(pp.get("min_sharpe", 1.0))
    if sharpe < min_sharpe:
        reasons.append(f"LOW_SHARPE {sharpe:.2f} < {min_sharpe}")
    lo, hi = pp.get("turnover_range", [0.01, 0.7])
    to = _f(stats.get("turnover"))
    if to is not None and not (lo <= to <= hi):
        reasons.append(f"TURNOVER {to:.1%} outside {lo:.0%}-{hi:.0%}")
    must = set(pp.get("must_pass_checks") or [])
    quota = set(pp.get("quota_checks") or [])
    exempt = set(pp.get("exempt_checks") or [])
    pending, waits = False, []
    for c in checks:
        name, result = c.get("name"), c.get("result")
        if name in quota:
            if result == "FAIL":  # submittable, but the daily/monthly allowance is used up for now
                waits.append(f"WAIT: {name} quota used ({c.get('value')}/{c.get('limit')})")
            continue
        if name in must and result in ("FAIL", "WARNING"):
            # must-pass checks: a WARNING here (e.g. Power Pool correlation above its limit) also disqualifies
            reasons.append(f"{name} {result} (value {c.get('value')}, limit {c.get('limit')})")
        elif result == "FAIL" and name not in exempt and name != "MATCHES_THEMES":
            # any other FAIL blocks submission (BRAIN shows the checks a Power Pool alpha is exempt from as WARNING)
            reasons.append(f"{name} FAIL (value {c.get('value')}, limit {c.get('limit')})")
        elif result == "PENDING" and name in must:
            pending = True
    if structural:
        if pp.get("max_operators") is not None and structural.get("pp_op_count", 0) > pp["max_operators"]:
            reasons.append(f"OPERATORS {structural['pp_op_count']} > {pp['max_operators']}")
        if pp.get("max_unique_fields") is not None and structural.get("n_fields", 0) > pp["max_unique_fields"]:
            reasons.append(f"FIELDS {structural['n_fields']} > {pp['max_unique_fields']}")

    matched, theme_state = [], None
    for c in checks:
        if c.get("name") != "MATCHES_THEMES":
            continue
        pp_themes = [t.get("name") for t in c.get("themes") or [] if pattern.search(t.get("name", ""))]
        if not pp_themes:
            continue
        if c.get("result") == "PASS":
            matched += pp_themes
            theme_state = "PASS"
        elif theme_state != "PASS":
            theme_state = c.get("result")
    if theme_state == "PENDING":
        pending = True
    elif theme_state not in (None, "PASS") and not reasons:
        # only meaningful when everything else qualifies: a sub-1.0 Sharpe alpha cannot match a Power Pool theme
        reasons.append("MATCHES_THEMES: no Power Pool theme matched")

    eligible_cls = pp.get("eligible_classification")
    classified = any(cl.get("id") == eligible_cls for cl in alpha.get("classifications") or [])

    q_issues = quality_issues(alpha, stats, checks, quality or {})
    if reasons:
        near = float(refine_cfg.get("near_miss_min_sharpe", 0.6))
        flip = float(refine_cfg.get("sign_flip_below", -0.8))
        status = "near_miss" if (abs(sharpe) >= near or sharpe <= flip) else "fail"
    elif q_issues:
        status = "suspect"  # passes the platform's checks but looks like an artifact / poor after-cost bet
    elif pending or theme_state is None:
        status = "pending"
    else:
        status = "eligible"
    if status == "eligible" and eligible_cls and not classified and not matched:
        status = "pending"  # the Power Pool tag is only assigned on submission; a theme PASS is the pre-submit proof
    sc = score(stats, weights) - (2.0 * len(q_issues) if q_issues else 0.0)
    reg_status, reg_reasons = None, []
    if regular is not None and regular.get("enabled", True):
        atom = is_atom(alpha.get("classifications"), datasets, regular)
        reg_status, reg_reasons = regular_verdict(checks, stats, regular, atom=atom)
        if q_issues and reg_status in ("eligible", "pending"):
            reg_status, reg_reasons = "suspect", reg_reasons + q_issues
    return Evaluation(status=status, reasons=reasons + q_issues + waits, score=round(sc, 4), stats=stats,
                      theme_matches=matched, checks=checks, reg_status=reg_status, reg_reasons=reg_reasons)
