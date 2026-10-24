"""Idea lifecycle: decide from simulation evidence whether an idea deserves more simulations.

An idea *family* is the set of data fields an alpha reads. Settings changes and cosmetic wrappers (rank, zscore,
winsorize, group transforms) of the same fields produce highly correlated PnL: they cannot rescue a weak signal, and
they cannot produce a second submittable alpha either (Power Pool alphas must be < 0.5 correlated with each other).
So a family is budgeted as one idea, and every decision below is about the family, not about one expression.

States: open (probed, undecided) | promising (worth a targeted refinement) | winner (has a submittable alpha:
stop spending on it) | used (already submitted, or correlated with a submitted alpha) | dropped (the evidence says
no). Every threshold comes from the `lifecycle` section of config.yaml.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..fastexpr import parse
from ..fastexpr.ast import Assign, Call, Ident, walk
from ..util import console


def family_key(fields, cls: str | None = None) -> str:
    """One idea = a set of data fields used in one shape class (level, change, event, spread, residual, ...)."""
    key = "+".join(sorted(set(fields or [])))
    return f"{key}|{cls}" if cls else key


def key_fields(key: str) -> set[str]:
    return set(key.split("|", 1)[0].split("+")) if key else set()


def code_operators(code: str) -> set[str]:
    try:
        prog = parse(code or "")
    except Exception:
        return set()
    return {n.name.lower() for n in walk(prog) if isinstance(n, Call)}


_LIB = None


def shape_library(ctx):
    global _LIB
    if _LIB is None:
        from .shapes import ShapeLibrary
        _LIB = ShapeLibrary.load(ctx.cfg)
    return _LIB


def row_family(ctx, row: dict) -> str:
    cls = row.get("shape_class") or shape_library(ctx).class_of(row.get("operators") or [])
    return family_key(row.get("fields"), cls)


def code_identifiers(code: str) -> set[str]:
    """Every free identifier in an expression (field-like names), without needing a catalog."""
    try:
        prog = parse(code or "")
    except Exception:
        return set()
    assigned = {s.name for s in prog.statements if isinstance(s, Assign)}
    return {n.name for n in walk(prog) if isinstance(n, Ident) and n.name not in assigned}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check_of(row: dict, name: str) -> dict | None:
    for c in row.get("checks") or []:
        if c.get("name") == name:
            return c
    return None


@dataclass
class Family:
    key: str                                              # "field+field|shape class"
    rows: list[dict] = field(default_factory=list)       # simulated rows, any settings
    queued: int = 0                                       # rows waiting for simulation
    state: str = "open"
    reason: str = ""
    remedies: list[str] = field(default_factory=list)    # what a refinement may change (see Lifecycle.remedies)

    @property
    def sims(self) -> int:
        return len(self.rows)

    @property
    def best(self) -> dict | None:
        good = [r for r in self.rows if r.get("pp_status") != "suspect"] or self.rows
        return max(good, key=lambda r: (_f((r.get("stats") or {}).get("sharpe")) or -9), default=None)

    @property
    def best_sharpe(self) -> float:
        b = self.best
        return (_f((b.get("stats") or {}).get("sharpe")) or 0.0) if b else 0.0

    @property
    def worst_sharpe(self) -> float:
        return min(((_f((r.get("stats") or {}).get("sharpe")) or 0.0) for r in self.rows), default=0.0)

    @property
    def open_for_work(self) -> bool:
        return self.state in ("open", "promising")


class Lifecycle:
    def __init__(self, ctx, submitted: list[dict] | None = None, simulator=None, route: str | None = None):
        from .routes import route_of, status_key
        self.ctx = ctx
        self.simulator = simulator
        self.cfg = ctx.cfg.section("lifecycle")
        self.pp = ctx.pp
        self.rc = ctx.cfg.section("regular")
        self.route = route or route_of(ctx)
        self.sk = status_key(self.route)  # the row column holding this route's verdict
        self.submitted = submitted if submitted is not None else submitted_alphas(ctx)
        sc = ctx.scope  # an alpha submitted in another region or delay does not use up this scope's idea
        lib = shape_library(ctx)
        self.used_keys = {family_key(a["fields"], lib.class_of(code_operators(a.get("code")))) for a in self.submitted
                          if a.get("fields") and a.get("region") in (None, sc["region"])
                          and int(a.get("delay") or sc["delay"]) == int(sc["delay"])}
        # plus alphas submitted earlier and since decommissioned (no longer ACTIVE; `p2a restore` records them)
        self.submitted_ids = {a.get("id") for a in self.submitted if a.get("id")} | set(ctx.store.kv_get("submitted_ever") or [])

    # -- thresholds -------------------------------------------------------------------------
    @property
    def floor(self) -> float:
        """The Sharpe a family must reach to be submittable on this route."""
        if self.route == "regular":
            return float(self.rc.get("min_sharpe", 1.58))
        return float(self.pp.get("min_sharpe", 1.0))

    @property
    def pnl_limit(self) -> float:
        """Daily-PnL correlation at which two candidates of this route are copies of each other."""
        if self.route == "regular":
            return float(self.rc.get("self_correlation_limit", 0.7))
        return float(self.cfg.get("submitted_correlation_limit") or self.pp.get("correlation_limit", 0.5))

    def t(self, name: str, default: float) -> float:
        v = self.cfg.get(name, default)
        return float(default if v is None else v)

    # -- families -----------------------------------------------------------------------------
    def families(self) -> dict[str, Family]:
        sc = self.ctx.scope
        rows = self.ctx.store.q("SELECT * FROM alphas WHERE region=? AND delay=? AND status IN "
                                "('simulated','valid','simulating') ORDER BY id", (sc["region"], sc["delay"]))
        fams: dict[str, Family] = {}
        for r in rows:
            key = row_family(self.ctx, r)
            fam = fams.setdefault(key, Family(key))
            if r["status"] == "simulated" and r.get("stats"):
                fam.rows.append(r)
            elif r["status"] in ("valid", "simulating"):
                fam.queued += 1
        self._all_keys = set(fams)
        for fam in fams.values():
            self.assess(fam)
        if self.simulator is not None:
            self._correlation_with_submitted(fams)
        return fams

    def _correlation_with_submitted(self, fams: dict[str, "Family"]) -> None:
        """A family whose best alpha trades like something already submitted is used up, whatever its fields.
        Daily PnL is compared with the submitted alphas of this region and delay: against Power Pool alphas the
        Power Pool limit applies (they must be weakly correlated with each other), against the rest the
        self-correlation limit."""
        sc = self.ctx.scope
        pp_limit = self.pnl_limit  # regular alphas only need self-correlation < 0.7, even against Power Pool alphas
        other_limit = self.t("used_self_correlation", 0.7)
        pp_cls = self.pp.get("eligible_classification")
        days = int(self.cfg.get("correlation_days", 1000))
        subs = [a for a in self.submitted if a.get("region") == sc["region"] and int(a.get("delay") or -1) == int(sc["delay"])]
        sub_pnl = {a["id"]: (daily_pnl(self.ctx, self.simulator, a["id"]),
                             pp_limit if pp_cls in (a.get("classifications") or []) else other_limit) for a in subs}
        for fam in fams.values():
            if fam.state not in ("winner", "promising", "open") or not fam.rows:
                continue
            best = fam.best
            if not best or not best.get("brain_id") or fam.best_sharpe < self.t("drop_below_fraction", 0.5) * self.floor:
                continue
            mine = daily_pnl(self.ctx, self.simulator, best["brain_id"])
            for aid, (p, limit) in sub_pnl.items():
                c = pnl_correlation(mine, p, days) if aid != best["brain_id"] else None
                if c is not None and c >= limit:
                    fam.state, fam.remedies = "used", []
                    fam.reason = f"trades like submitted {aid} (daily PnL correlation {c:.2f} >= {limit})"
                    break
        # a family still being worked on that trades like an existing winner can only become its copy
        winners = [f for f in fams.values() if f.state == "winner" and f.best and f.best.get("brain_id")]
        for fam in fams.values():
            if fam.state not in ("promising", "open") or not fam.best or not fam.best.get("brain_id"):
                continue
            mine = daily_pnl(self.ctx, self.simulator, fam.best["brain_id"])
            for w in winners:
                c = pnl_correlation(mine, daily_pnl(self.ctx, self.simulator, w.best["brain_id"]), days)
                if c is None or c < pp_limit:
                    continue
                if fam.best_sharpe > w.best_sharpe + self.t("min_gain", 0.05):
                    # a better version of a winner's idea: keep it for the check; the queue keeps the better one
                    fam.reason += f"; may supersede #{w.best['id']} (correlation {c:.2f}, Sharpe {w.best_sharpe:.2f})"
                    continue
                fam.state, fam.remedies = "dropped", []
                fam.reason = f"trades like winner #{w.best['id']} (daily PnL correlation {c:.2f} >= {pp_limit})"
                break

    def family_of(self, fields, cls: str | None = None) -> Family:
        key = family_key(fields, cls or shape_library(self.ctx).default_class)
        fam = self.families().get(key) or Family(key)
        if not fam.rows:
            self.assess(fam)
        return fam

    # -- the decision ---------------------------------------------------------------------------
    def assess(self, fam: Family) -> Family:
        floor = self.floor
        fam.remedies = []
        mine = next((r["brain_id"] for r in fam.rows if r.get("brain_id") in getattr(self, "submitted_ids", ())), None)
        if mine:  # one of this family's own alphas has been submitted
            fam.state, fam.reason = "used", f"submitted ({mine})"
            return fam
        if fam.key in self.used_keys:
            fam.state, fam.reason = "used", "these exact fields are already in a submitted alpha"
            return fam
        for r in fam.rows:
            sc = check_of(r, "SELF_CORRELATION")
            ppc = check_of(r, "POWER_POOL_CORRELATION")
            if sc and (_f(sc.get("value")) or 0) >= self.t("used_self_correlation", 0.7):
                fam.state, fam.reason = "used", f"correlation {_f(sc.get('value')):.2f} with a submitted alpha"
                return fam
            if ppc and ppc.get("result") == "FAIL":
                fam.state, fam.reason = "used", "fails POWER_POOL_CORRELATION against your Power Pool alphas"
                return fam
        if not fam.rows:
            fam.state, fam.reason = "open", "not simulated yet"
            return fam
        if any(r.get(self.sk) == "eligible" for r in fam.rows):
            fam.state, fam.reason = "winner", "has a submittable alpha; more variants would only be correlated copies"
            return fam
        clean = [r for r in fam.rows if r.get("pp_status") != "suspect"]
        if not clean:
            fam.state, fam.reason = "dropped", "every result looked like an artifact (one-sided, narrow or concentrated)"
            return fam
        best = fam.best
        st = best.get("stats") or {}
        s = _f(st.get("sharpe")) or 0.0
        worst = fam.worst_sharpe
        flip_at = self.t("flip_below_fraction", -0.6) * floor
        flipped = any("invert" in (r.get("rationale") or "").lower() or r.get("origin") == "refine:flip"
                      for r in fam.rows)
        if s < self.t("drop_below_fraction", 0.5) * floor:
            if worst <= flip_at and not flipped:
                fam.state, fam.reason, fam.remedies = "promising", f"strongly negative (Sharpe {worst:.2f}): invert once", ["flip"]
            else:
                fam.state, fam.reason = "dropped", (f"weak signal: best Sharpe {s:.2f} after {fam.sims} simulation(s) "
                                                    f"(< {self.t('drop_below_fraction', 0.5):.0%} of {floor}); "
                                                    "settings cannot add signal")
            return fam
        sub = check_of(best, "LOW_SUB_UNIVERSE_SHARPE")
        if sub and sub.get("result") == "FAIL":
            v, lim = _f(sub.get("value")), _f(sub.get("limit"))
            if v is not None and lim and v < self.t("sub_universe_drop_ratio", 0.5) * lim:
                fam.state, fam.reason = "dropped", (f"illiquid effect: sub-universe Sharpe {v:.2f} vs limit {lim:.2f}; "
                                                    "the signal lives in small stocks")
                return fam
        prod = check_of(best, "PROD_CORRELATION")
        pv = _f((prod or {}).get("value"))
        if pv is None:  # measured with the fast correlation endpoint before BRAIN's full check
            pv = _f(st.get("prod_corr"))
        crowd = self.t("crowded_prod_correlation", 0.9)
        if pv is not None and pv >= crowd and self.cfg.get("drop_crowded", True):
            fam.state, fam.reason = "dropped", (f"crowded: correlation {pv:.2f} with production alphas; "
                                                "it adds nothing new")
            return fam
        ref = _f(st.get("ref_corr"))
        if self.route == "regular" and ref is not None and abs(ref) >= self._ref_limit():
            # the idea trades like a crowded reference factor (references.py): its residual on that factor shows
            # whether it carries anything else. One residual variant; if that has no signal, the idea is the factor
            kids = self._orthogonalized(fam)
            if not kids and s >= self.t("promising_fraction", 0.75) * floor:
                fam.state, fam.remedies = "promising", ["orthogonalize"]
                fam.reason = (f"trades like the {st.get('ref_factor')} factor ({ref:.2f}): one residual variant tests "
                              "for information beyond it")
                return fam
            best_kid = max((abs(_f((k.get("stats") or {}).get("sharpe")) or 0) for k in kids), default=0.0)
            fam.state = "dropped"
            fam.reason = (f"trades like the {st.get('ref_factor')} factor ({ref:.2f}); " +
                          (f"its residual (Sharpe {best_kid:.2f}) is a new idea of its own" if kids and
                           best_kid >= self.t("promising_fraction", 0.75) * floor else
                           f"its residual has no signal (Sharpe {best_kid:.2f})" if kids else
                           "too weak to test its residual"))
            return fam
        if self.route == "regular" and pv is not None and pv >= float(self.rc.get("prod_correlation_limit", 0.7)):
            # production alphas trade this already: one decorrelating attempt, then the idea is closed for this route
            if s >= self.t("promising_fraction", 0.75) * floor and not self._decorrelated(fam):
                fam.state, fam.remedies = "promising", ["decorrelate"]
                fam.reason = f"production correlation {pv:.2f}: one decorrelating variant (risk-neutralized)"
            else:
                fam.state, fam.reason = "dropped", f"crowded for production (prod correlation {pv:.2f})"
            return fam
        if fam.sims >= int(self.t("max_sims_per_family", 5)):
            fam.state, fam.reason = "dropped", f"budget used: {fam.sims} simulations, best Sharpe {s:.2f}"
            return fam
        if self._plateau(fam):
            fam.state, fam.reason = "dropped", (f"plateau: the last refinements did not beat Sharpe {s:.2f} by "
                                                f"{self.t('min_gain', 0.05)}")
            return fam
        promising = self.t("promising_fraction", 0.75) * floor
        fam.remedies = self.remedies(fam, best)
        if best.get(self.sk) == "pending" and s >= floor and not fam.remedies:
            fam.state, fam.reason = "open", f"Sharpe {s:.2f}; waiting for BRAIN's submission check"
            return fam
        if s >= promising and fam.remedies:
            fam.state, fam.reason = "promising", f"Sharpe {s:.2f}; fix: {', '.join(fam.remedies)}"
        elif fam.remedies and fam.sims < int(self.t("second_chance_sims", 2)):
            fam.state, fam.reason = "promising", f"some signal (Sharpe {s:.2f}); one expression-level attempt"
            fam.remedies = [m for m in fam.remedies if m == "expression"] or fam.remedies[:1]
        else:
            fam.state, fam.reason = "dropped", f"below the promising level: best Sharpe {s:.2f} after {fam.sims} simulation(s)"
        return fam

    def size_fields(self) -> set[str]:
        """Company-size fields of this scope, recognised by their catalog description."""
        if getattr(self, "_size", None) is None:
            pats = [re.compile(p, re.I) for p in self.cfg.get("liquidity_field_patterns") or []]
            self._size = {f["id"] for f in self.ctx.store.fields(self.ctx.scope)
                          if pats and any(p.search(f.get("description") or "") for p in pats)}
        return self._size

    def _size_weighted(self, fam: Family) -> bool:
        """True when the family already is, or already has, a size-weighted version."""
        fields = key_fields(fam.key)
        cls = fam.key.split("|", 1)[1] if "|" in fam.key else None
        if fields & self.size_fields() or any(r.get("origin") == "refine:liquidity" for r in fam.rows):
            return True
        keys = getattr(self, "_all_keys", set())
        return any(family_key(fields | {sz}, cls) in keys for sz in self.size_fields())

    def _ref_limit(self) -> float:
        from .references import limit
        return limit(self.ctx.cfg)

    def _orthogonalized(self, fam: Family) -> list[dict]:
        """Residual variants of the family on a reference factor (children carry an extra field, so they live in a
        family of their own; they are found by parent)."""
        ids = [r["id"] for r in fam.rows if r.get("id") is not None]
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        return self.ctx.store.q(f"SELECT * FROM alphas WHERE origin='refine:orthogonalize' AND parent_id IN ({marks}) "
                                "AND status IN ('simulated','valid','simulating')", tuple(ids))

    def _decorrelated(self, fam: Family) -> bool:
        """True when the family already has a risk-neutralized (decorrelating) variant."""
        risk = {str(v).upper() for v in (self.rc.get("risk_neutralizations") or {}).values()}
        return any(r.get("origin") == "refine:decorrelate" or
                   str((r.get("settings") or {}).get("neutralization") or "").upper() in risk for r in fam.rows)

    def _plateau(self, fam: Family) -> bool:
        """Children that did not improve on their parent close the branch."""
        by_id = {r["id"]: r for r in fam.rows}
        gain = self.t("min_gain", 0.05)
        stalls = 0
        for r in fam.rows:
            p = by_id.get(r.get("parent_id"))
            if not p:
                continue
            sr, sp = _f((r.get("stats") or {}).get("sharpe")) or 0, _f((p.get("stats") or {}).get("sharpe")) or 0
            if sr < sp + gain:
                stalls += 1
        return stalls >= int(self.t("max_stalled_children", 2))

    def remedies(self, fam: Family, best: dict) -> list[str]:
        """What a refinement may change. Settings only ever change to fix one specific failed check, and only once
        per expression (`max_settings_variants`); everything else must change the expression."""
        out = []
        st = best.get("stats") or {}
        s = _f(st.get("sharpe")) or 0.0
        turnover = _f(st.get("turnover")) or 0.0
        lo, hi = self.pp.get("turnover_range", [0.01, 0.7])
        reasons = " ".join(best.get("pp_reasons") or [])
        settings_children = sum(1 for r in fam.rows if r["canonical"] == best["canonical"] and r["id"] != best["id"])
        settings_ok = settings_children < int(self.t("max_settings_variants", 1))
        if turnover > hi and settings_ok:
            out.append("decay_up")
        if "CONCENTRATED" in reasons and settings_ok:
            out.append("truncation_down")
        sub = check_of(best, "LOW_SUB_UNIVERSE_SHARPE")
        if sub and sub.get("result") == "FAIL" and settings_ok and (_f(sub.get("value")) or 0) >= self.floor:
            out.append("liquid_universe")  # only when the liquid names alone already clear the Sharpe floor
        if sub and sub.get("result") == "FAIL" and self.cfg.get("liquidity_weighting", True) and not self._size_weighted(fam):
            out.append("liquidity_weight")  # scale positions by company size: the sub-universe test is about liquid names
        if self.route == "regular":
            fit = _f(st.get("fitness"))
            if fit is not None and fit < float(self.rc.get("min_fitness", 1.0)) and s >= self.floor and settings_ok \
                    and turnover > float(self.rc.get("fitness_decay_turnover", 0.2)) and "decay_up" not in out:
                out.append("decay_up")  # fitness = Sharpe * sqrt(returns / turnover): slower trading lifts it
            two = check_of(best, "LOW_2Y_SHARPE")
            if two and two.get("result") in ("FAIL", "WARNING"):
                out.append("expression")  # the recent years are weaker: only a better idea fixes that
        if s < self.floor or (turnover and turnover < lo) or "NARROW" in reasons or "INVESTABILITY" in reasons \
                or (sub and sub.get("result") == "FAIL"):
            out.append("expression")
        return list(dict.fromkeys(out))


# -- what the account has already submitted -------------------------------------------------------
def submitted_alphas(ctx, max_age_s: float | None = None) -> list[dict]:
    """Submitted (ACTIVE) alphas of this account with the identifiers their code reads; cached in kv."""
    max_age = max_age_s if max_age_s is not None else float(ctx.cfg.get("lifecycle.submitted_refresh_s", 1800))
    cached = ctx.store.kv_get("submitted_alphas", max_age_s=max_age)
    if cached is not None:
        return cached
    client = getattr(ctx.sync, "client", None)
    if client is None:
        return ctx.store.kv_get("submitted_alphas") or []
    out = []
    try:
        for a in client.paginate("/users/self/alphas", {"status": "ACTIVE", "order": "-dateSubmitted"}, page_size=100,
                                 max_items=int(ctx.cfg.get("lifecycle.submitted_lookback", 500))):
            code = (a.get("regular") or {}).get("code") or ""
            s = a.get("settings") or {}
            ids = code_identifiers(code)
            known = {f for f in ids if ctx.catalog.field(f)}
            grouping = ctx.constraints.grouping_fields if ctx.constraints else set()
            is_ = a.get("is") or {}
            out.append({"id": a["id"], "code": code, "region": s.get("region"), "delay": s.get("delay"),
                        "universe": s.get("universe"), "submitted": a.get("dateSubmitted"), "type": a.get("type"),
                        "classifications": [c.get("id") for c in a.get("classifications") or []],
                        "fields": sorted((known or ids) - set(grouping)),
                        "osmosis_points": a.get("osmosisPoints"),
                        "stats": {"sharpe": is_.get("sharpe"), "fitness": is_.get("fitness"),
                                  "turnover": is_.get("turnover"), "returns": is_.get("returns"),
                                  "book": is_.get("bookSize"),
                                  "ic_sharpe": (is_.get("investabilityConstrained") or {}).get("sharpe")}})
    except Exception as e:  # never block generation on this
        console.print(f"  [yellow]could not list submitted alphas: {e}[/yellow]")
        return ctx.store.kv_get("submitted_alphas") or []
    ctx.store.kv_set("submitted_alphas", out)
    return out


def family_table(fams: dict[str, Family]) -> list[list]:
    order = {"promising": 0, "open": 1, "winner": 2, "used": 3, "dropped": 4}
    rows = []
    for f in sorted(fams.values(), key=lambda f: (order.get(f.state, 9), -f.best_sharpe)):
        rows.append([f.key[:60], f.state, f.sims, f.queued, f"{f.best_sharpe:.2f}" if f.rows else "-", f.reason[:90]])
    return rows


# -- realised correlation between candidates --------------------------------------------------------
def daily_pnl(ctx, simulator, brain_id: str) -> dict[str, float]:
    """Daily PnL of a simulated alpha (from BRAIN's cumulative PnL record set), cached in kv."""
    key = f"pnl:{brain_id}"
    rec = ctx.store.kv_get(key)
    if rec is None:
        data = simulator.recordset(brain_id, "pnl") if simulator else None
        if not data or not data.get("records"):
            return {}
        names = [p.get("name") for p in (data.get("schema") or {}).get("properties") or []]
        col = names.index("pnl") if "pnl" in names else 1
        rec = [[r[0], r[col]] for r in data["records"] if r and r[col] is not None]
        ctx.store.kv_set(key, rec)
    out, prev = {}, None
    for d, cum in rec:
        if prev is not None:
            out[d] = float(cum) - prev
        prev = float(cum)
    return out


def pnl_correlation(a: dict[str, float], b: dict[str, float], days: int) -> float | None:
    common = sorted(set(a) & set(b))
    common = [d for d in common if a[d] != 0.0 or b[d] != 0.0][-days:]
    if len(common) < 60:
        return None
    xa = [a[d] for d in common]
    xb = [b[d] for d in common]
    ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
    va = sum((x - ma) ** 2 for x in xa)
    vb = sum((x - mb) ** 2 for x in xb)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
    return cov / (va * vb) ** 0.5


def value_score(row: dict) -> float:
    """Ordering heuristic for submissions: Sharpe x BRAIN's quality-factor multipliers (pyramid x theme) x
    uniqueness (1 - production correlation; 0.7 assumed when BRAIN has not measured it). BRAIN does not publish
    its payment formula; this only ranks candidates by the levers it documents."""
    from .routes import multiplier_product
    st = row.get("stats") or {}
    prod = _f(st.get("prod_corr"))
    if prod is None:
        c = check_of(row, "PROD_CORRELATION")
        prod = _f((c or {}).get("value"))
    mult = _f(st.get("mult")) or multiplier_product(row.get("checks"))
    return round((_f(st.get("sharpe")) or 0.0) * (mult or 1.0) * (1.0 - (0.7 if prod is None else prod)), 4)


def submission_queue(ctx, simulator, lifecycle: Lifecycle | None = None, route: str | None = None) -> list[dict]:
    """Eligible alphas of one route in the order to submit them: the best alpha of each winning family, fewest
    quality warnings first, then the highest uniqueness-weighted value, skipping any that trades (daily PnL) like a
    better one already in the queue - Power Pool alphas must be < 0.5 correlated with each other, regular alphas
    < 0.7 (self-correlation), so a near-copy is not a second submission."""
    lc = lifecycle or Lifecycle(ctx, simulator=simulator, route=route)
    fams = lc.families()
    limit = lc.pnl_limit
    days = int(ctx.cfg.get("lifecycle.correlation_days", 1000))
    cands = []
    for f in fams.values():
        if f.state != "winner":
            continue
        elig = [r for r in f.rows if r.get(lc.sk) == "eligible"]
        if elig:
            best = max(elig, key=lambda r: (value_score(r), r.get("score") or 0))
            flags = quality_flags(ctx, best, simulator)
            if lc.route != "regular" and best.get("reg_status") == "eligible":
                flags = ["Power Pool + Regular: does not use the pure Power Pool quota"] + flags
            cands.append({**best, "flags": flags, "value": value_score(best)})

    def warnings(r):
        return sum(1 for fl in r["flags"] if not fl.startswith(("also passes", "Power Pool + Regular")))

    cands.sort(key=lambda r: (warnings(r), -r["value"], -((r.get("stats") or {}).get("sharpe") or 0)))
    selected, out, pnls = [], [], {}
    for r in cands:
        pnls[r["brain_id"]] = daily_pnl(ctx, simulator, r["brain_id"])
        worst = None
        for q in selected:
            c = pnl_correlation(pnls[r["brain_id"]], pnls[q["brain_id"]], days)
            if c is not None and (worst is None or c > worst[0]):
                worst = (c, q["id"])
        entry = {**r, "max_corr": worst[0] if worst else None, "corr_with": worst[1] if worst else None,
                 "queued": not (worst and worst[0] >= limit), "warnings": warnings(r), "route": lc.route}
        if entry["queued"]:
            selected.append(entry)
        else:
            entry["why_not"] = f"PnL correlation {worst[0]:.2f} with #{worst[1]} (limit {limit})"
        out.append(entry)
    return out


def yearly_sharpes(ctx, simulator, brain_id: str) -> dict[str, float]:
    key = f"yearly:{brain_id}"
    rec = ctx.store.kv_get(key)
    if rec is None:
        data = simulator.recordset(brain_id, "yearly-stats") if simulator else None
        if not data or not data.get("records"):
            return {}
        names = [p.get("name") for p in (data.get("schema") or {}).get("properties") or []]
        rec = [dict(zip(names, r)) for r in data["records"]]
        ctx.store.kv_set(key, rec)
    return {str(r.get("year")): float(r.get("sharpe") or 0.0) for r in rec if r.get("turnover")}


def quality_flags(ctx, row: dict, simulator=None) -> list[str]:
    """Warnings a researcher would want before submitting, from BRAIN's own check values (exempt checks included)."""
    floor = float(ctx.pp.get("min_sharpe", 1.0))
    out = []
    two = check_of(row, "LOW_2Y_SHARPE")
    if two and _f(two.get("value")) is not None and _f(two.get("value")) < floor:
        out.append(f"recent 2y Sharpe {_f(two.get('value')):.2f}")
    sub = check_of(row, "LOW_SUB_UNIVERSE_SHARPE")
    if sub and _f(sub.get("value")) is not None and _f(sub.get("limit")) and _f(sub.get("value")) < 1.1 * _f(sub.get("limit")):
        out.append(f"thin sub-universe margin ({_f(sub.get('value')):.2f} vs {_f(sub.get('limit')):.2f})")
    prod = check_of(row, "PROD_CORRELATION")
    if prod and (_f(prod.get("value")) or 0) >= 0.7:
        out.append(f"crowded (prod corr {_f(prod.get('value')):.2f})")
    selfc = check_of(row, "SELF_CORRELATION")
    if selfc and (_f(selfc.get("value")) or 0) >= 0.7:
        out.append(f"like your own alphas (self corr {_f(selfc.get('value')):.2f})")
    if simulator is not None and row.get("brain_id"):
        years = yearly_sharpes(ctx, simulator, row["brain_id"])
        bad = [y for y, s in years.items() if s < 0]
        if bad:
            out.append(f"losing year(s) {', '.join(sorted(bad))}")
    sh, fit = check_of(row, "LOW_SHARPE"), check_of(row, "LOW_FITNESS")
    if sh and fit and sh.get("result") == "PASS" and fit.get("result") == "PASS":
        out.append("also passes the regular Sharpe and fitness bars")
    return out
