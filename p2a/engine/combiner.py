"""Combinations of weakly correlated, economically linked signals.

Why this is the main source of regular (production) alphas:
- The Sharpe of an equal-risk sum of signals with Sharpes S_i and pairwise correlations rho_ij is about
  sum(S_i) / sqrt(n + 2 * sum(rho_ij)) (Grinold and Kahn's fundamental law; Kakushadze and Yu 2016, "How to combine
  a billion alphas"): two signals of Sharpe 1.2 that are 0.3 correlated make about 1.5, three make about 1.75.
- A combination's correlation with any production alpha p is diluted by the parts that do not trade like p:
  corr(a + b, p) = (rho_ap * s_a + rho_bp * s_b) / s_(a+b). A crowded signal (0.85 with production) joined at equal
  risk with an unrelated one (0.3 with it) is about 0.85 / sqrt(2.6) = 0.53 with production - real
  diversification, not noise (BRAIN's Dos and Don'ts forbid adding noise to beat the correlation test).
- Only parts whose data kinds share a mechanism are joined (`combine_groups` in research/shapes.yaml), so every
  combination keeps an economic story, as BRAIN requires.

Everything is estimated from the daily PnL BRAIN already reported for each part (no simulation): each part's PnL
is scaled to unit volatility and the parts are summed. Only combinations whose estimate clears the route's Sharpe
bar by a margin, and that do not trade like an alpha you already submitted, are queued for simulation.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from itertools import combinations

from ..fastexpr import parse
from ..fastexpr.ast import Assign
from ..util import console
from .context import Context
from .generator import Candidate, Generator
from .lifecycle import Lifecycle, check_of, daily_pnl, family_key, key_fields, pnl_correlation, row_family, shape_library
from .routes import pyramid_of, route_of


_COMBINED = re.compile(r"rank\([^;]*\)\s*[-+*]\s*\(?\s*rank\(")


def _sentence(text) -> str:
    t = " ".join(str(text or "").split()).rstrip(".")
    return t[:1].upper() + t[1:]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class Part:
    row: dict
    kind: str | None
    pnl: dict
    prod: float | None            # BRAIN's measured production correlation, if checked
    prior: float                  # crowding prior for the production correlation (dataset alpha count)
    sign: int = 1                 # -1: the evidence says the opposite of the template's direction (its PnL is negated)
    sub: float | None = None      # its own sub-universe (liquid subset) Sharpe, in its direction
    sub_required: float | None = None  # the ratio BRAIN requires: sub-universe Sharpe >= this x Sharpe
    weight: float = 1.0           # parts whose effect lives in illiquid stocks enter at a lower weight

    @property
    def sharpe(self) -> float:
        return self.sign * (_f((self.row.get("stats") or {}).get("sharpe")) or 0.0)

    @property
    def code(self) -> str:
        c = self.row["canonical"]
        return c if self.sign > 0 else f"-({c})"

    @property
    def fields(self) -> set:
        return set(self.row.get("fields") or [])


@dataclass
class Combo:
    parts: list[Part]
    group: str
    sharpe: float                 # estimated Sharpe after the turnover haircut
    max_corr: float
    prod_est: float
    value: float
    fitness: float | None = None  # estimated fitness (returns, turnover and Sharpe estimates)
    turnover: float | None = None
    sub_ratio: float | None = None     # estimated sub-universe Sharpe / Sharpe of the combination
    sub_required: float | None = None  # what BRAIN requires of that ratio
    notes: list[str] = field(default_factory=list)


def _std(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1)), m


def common_dates(pnls: list[dict], days: int) -> list:
    """The last `days` dates all series share, from the day every part has started trading. Flat days after that
    are real (the combination is flat too), so they stay in: dropping them inflated the estimate for parts that
    trade only on data-update days."""
    common = sorted(set.intersection(*[set(p) for p in pnls]))
    starts = [next((d for d in common if p[d] != 0.0), None) for p in pnls]
    if any(s is None for s in starts):
        return []
    return [d for d in common if d >= max(starts)][-days:]


def active_ratio(pnl: dict) -> float:
    """Share of days with a nonzero PnL after the alpha's first trade (an alpha on a sparse field that is not carried
    forward holds positions only on data-update days)."""
    ds = sorted(pnl)
    start = next((i for i, d in enumerate(ds) if pnl[d] != 0.0), None)
    if start is None:
        return 0.0
    rest = ds[start:]
    return sum(1 for d in rest if pnl[d] != 0.0) / len(rest)


def combo_stats(pnls: list[dict], days: int, weights: list[float] | None = None,
                scaling: str = "position") -> tuple[float, list[float]] | None:
    """Annualised Sharpe of the weighted sum of daily PnL series, and the sum itself (for correlations), over
    `common_dates`. scaling="position" adds the parts' PnL as simulated: a rank sum gives every part the same position
    size, so a part's share of the risk is its own PnL volatility (calibrated 19 Oct on 11 composites: mean error 0.05
    Sharpe; "risk", each part scaled to unit volatility, erred by 0.12 and over-credited slow, low-volatility parts)."""
    common = common_dates(pnls, days)
    if len(common) < 250:
        return None
    weights = weights or [1.0] * len(pnls)
    total = [0.0] * len(common)
    for p, w in zip(pnls, weights):
        xs = [p[d] for d in common]
        sd, _ = _std(xs)
        if sd <= 0:
            return None
        k = w if scaling == "position" else w / sd
        for i, x in enumerate(xs):
            total[i] += k * x
    sd, m = _std(total)
    if sd <= 0:
        return None
    return m / sd * math.sqrt(252), total


class Combiner:
    def __init__(self, ctx: Context, generator: Generator, simulator=None):
        self.ctx = ctx
        self.gen = generator
        self.simulator = simulator
        self.cfg = ctx.cfg.section("combine")
        self.lib = shape_library(ctx)
        self.route = route_of(ctx)
        self.days = int(ctx.cfg.get("lifecycle.correlation_days", 1000))      # correlations: recent years
        self.est_days = int(self.cfg.get("estimate_days", 0) or 10 ** 6)       # Sharpe estimate: the whole history
        self.groups = self.lib.data.get("combine_groups") or {}
        self._mech_groups: set | None = None
        self._ref_pnls: dict | None = None

    # -- parts ------------------------------------------------------------------------------------
    def prior(self, row: dict) -> float:
        """Rough prior for a part's production correlation from how many alphas use its datasets (fitted on this
        engine's own measured values) and how much it trades like a crowded reference factor; replaced by BRAIN's
        number once a part is checked."""
        a, b = float(self.cfg.get("prod_prior_intercept", 0.45)), float(self.cfg.get("prod_prior_slope", 0.13))
        worst = 0.0
        for ds in row.get("datasets") or []:
            d = self.ctx.store.one("SELECT alpha_count FROM datasets WHERE id=? AND region=? AND delay=?",
                                   (ds, self.ctx.scope["region"], self.ctx.scope["delay"]))
            n = (d or {}).get("alpha_count") or 0
            worst = max(worst, min(0.99, a + b * math.log10(1 + n)))
        ref = _f((row.get("stats") or {}).get("ref_corr"))  # trades like a crowded reference factor (references.py)
        if ref is not None:
            ra = float(self.ctx.cfg.get("uniqueness.ref_prior_intercept", 0.35))
            rb = float(self.ctx.cfg.get("uniqueness.ref_prior_slope", 0.6))
            worst = max(worst, min(0.99, ra + rb * abs(ref)))
        return worst or a

    def kind(self, row: dict) -> str | None:
        shape = str(row.get("shape") or "")
        if shape.startswith("mech:"):  # a research mechanism: its group is its kind (residual reversal, ...)
            from .mechanisms import mechanism_library
            m = mechanism_library(self.ctx).get(shape[5:])
            if m is not None:
                return m.group or m.id
        kinds = [self.lib.kind_of(f) for f in (self.ctx.store.field(fid, self.ctx.scope) for fid in row.get("fields") or [])
                 if f]
        kinds = [k for k in kinds if k]
        return max(set(kinds), key=kinds.count) if kinds else None

    def parts(self, fams: dict, origin_prefix: str | None = None, subs: list[dict] | None = None) -> list[Part]:
        """The best simulated alpha of every family that carries signal on its own: positive Sharpe above
        `combine.part_min_sharpe`, a passing (or near) liquid sub-universe, no artifact flags, one statement, few
        fields. Combinations are not parts of new combinations (they would stack into complexity)."""
        cfg = self.cfg
        min_s = float(cfg.get("part_min_sharpe", 0.8))
        max_fields = int(cfg.get("part_max_fields", 2))
        sub_ratio = float(cfg.get("part_min_sub_universe_ratio", 0.8))
        universe = self.ctx.scope["universe"]
        out = []
        used_ok = bool(cfg.get("parts_from_used", True))
        for key, f in fams.items():
            if not f.rows:
                continue
            if f.state == "used" and not (used_ok and f.reason.startswith("trades like")):
                continue  # a family that trades like a submission may still be one part of many (the sum is checked)
            good = [r for r in f.rows if r.get("pp_status") != "suspect" and r.get("brain_id")
                    and (r.get("settings") or {}).get("universe") == universe]
            if not good:
                continue
            if origin_prefix:
                good = [r for r in good if str(r.get("origin") or "").startswith(origin_prefix)]
                if not good:
                    continue
            best = max(good, key=lambda r: abs(_f((r.get("stats") or {}).get("sharpe")) or 0))
            st = best.get("stats") or {}
            raw_s = _f(st.get("sharpe")) or 0
            sign = 1 if raw_s >= 0 else -1
            if sign < 0 and not cfg.get("allow_flipped_parts", True):
                continue
            if abs(raw_s) < min_s or len(best.get("fields") or []) > max_fields:
                continue
            if (best.get("shape_class") or "") in ("combo", "interaction") or str(best.get("origin") or "").startswith("combine"):
                continue
            if _COMBINED.search(best.get("canonical") or ""):
                continue  # already a sum or product of ranked signals: a part must be one idea
            if int(best.get("op_count") or 0) > int(cfg.get("part_max_operators", 4)):
                continue
            sub = check_of(best, "LOW_SUB_UNIVERSE_SHARPE")
            sub_v, sub_l = (_f(sub.get("value")), _f(sub.get("limit"))) if sub else (None, None)
            weight = 1.0
            if sub_v is not None and sub_l and sign * sub_v < sub_ratio * abs(sub_l):
                # the effect lives in illiquid stocks (judged in the part's own direction): such a part may still
                # join liquid ones at a lower weight - the combination's own sub-universe test is estimated below
                if sign * sub_v <= 0 or not cfg.get("illiquid_parts", True):
                    continue
                weight = float(cfg.get("illiquid_part_weight", 0.5))
            try:
                prog = parse(best.get("canonical") or "")
            except Exception:
                continue
            if len(prog.statements) != 1 or any(isinstance(s, Assign) for s in prog.statements):
                continue
            pnl = daily_pnl(self.ctx, self.simulator, best["brain_id"])
            if not pnl:
                continue
            if active_ratio(pnl) < float(cfg.get("part_min_active_ratio", 0.5)):
                continue  # trades only on data-update days: its Sharpe is an event effect, not a signal to hold
            if self.route == "regular" and self.crowded_factor(best, pnl):
                continue  # a crowded factor in disguise makes the whole combination crowded (references.py)
            if subs and self.dominates_submitted(pnl, subs):
                continue  # this signal already drives a submitted alpha: combinations with it would copy that alpha
            if sign < 0:
                pnl = {d: -v for d, v in pnl.items()}
            prod = _f(st.get("prod_corr"))
            if prod is None:
                prod = _f((check_of(best, "PROD_CORRELATION") or {}).get("value"))
            out.append(Part(row=best, kind=self.kind(best), pnl=pnl, prod=prod, prior=self.prior(best), sign=sign,
                            sub=sign * sub_v if sub_v is not None else None,
                            sub_required=abs(sub_l) / abs(raw_s) if sub_l and raw_s else None, weight=weight))
        out.sort(key=lambda p: -p.sharpe)
        return out[: int(cfg.get("max_parts_considered", 60))]

    def dominates_submitted(self, pnl: dict, subs: list[dict]) -> bool:
        """True when the part trades like a submitted alpha (part_max_submitted_corr). Measured 18 Oct: the smirk was
        0.75 like the submitted #499, which held it among six parts - any new combination with it would be a copy."""
        lim = float(self.cfg.get("part_max_submitted_corr", 0.6))
        return any((pnl_correlation(pnl, s["pnl"], self.days) or 0.0) >= lim for s in subs)

    def crowded_factor(self, row: dict, pnl: dict) -> bool:
        """True when the part trades like a crowded reference factor. Measured 17 Oct: combinations that held one such
        part (residual reversal, 0.80 like five-day reversal) were 0.83 correlated with production at Sharpe 3.0; the
        same channels without it were 0.63. One crowded part is not diluted away - production holds thousands of
        alphas that mix it with other signals."""
        from . import references as refs
        v = _f((row.get("stats") or {}).get("ref_corr"))
        if v is None:
            if self._ref_pnls is None:
                self._ref_pnls = refs.pnls(self.ctx, self.simulator)
            if not self._ref_pnls:
                return False
            v, _ = refs.exposure(self.ctx, self.simulator, pnl, self._ref_pnls)
        lim = float(self.cfg.get("part_max_ref_corr") or refs.limit(self.ctx.cfg))
        return v is not None and abs(v) >= lim

    # -- pairing ------------------------------------------------------------------------------------
    def group_of(self, parts: list[Part], any_size: bool = False) -> str | None:
        """The mechanism group all parts share. Groups marked `integrated` (a multi-signal model across mechanisms)
        only hold composites of at least `combine.integrated_min_parts` parts: small combinations must share one
        mechanism, large ones are an integrated model of established predictors."""
        kinds = [p.kind for p in parts]
        if any(k is None for k in kinds):
            return None
        min_int = int(self.cfg.get("integrated_min_parts", 4))
        for name, g in self.groups.items():
            if g.get("integrated") and (not self.cfg.get("allow_integrated", True) or (len(parts) < min_int and not any_size)):
                continue
            members = set(g.get("kinds") or [])
            if g.get("include_mechanism_groups"):  # every research mechanism (research/mechanisms.yaml) is a predictor
                members |= self._mechanism_groups()
            if all(k in members for k in kinds):
                return name
        return None

    def _mechanism_groups(self) -> set:
        if self._mech_groups is None:
            from .mechanisms import mechanism_library
            lib = mechanism_library(self.ctx)
            self._mech_groups = {m.group or m.id for m in lib.mechanisms}
        return self._mech_groups

    def allowed(self, parts: list[Part]) -> str | None:
        """Route rules for a combination; returns the reason it is not allowed, or None."""
        fields = set().union(*[p.fields for p in parts])
        owner: dict = {}
        for p in parts:  # one field in two parts double-counts an idea - unless the parts are different mechanisms
            for f in p.fields:  # (the smirk and implied-volatility innovations both read ATM call volatility)
                if f in owner and (owner[f] is None or owner[f] == p.kind):
                    return "parts share fields"
                owner.setdefault(f, p.kind)
        c = self.ctx.constraints
        if c and c.max_fields is not None and len(fields) > c.max_fields:
            return "too many fields"
        cats = set().union(*[set(p.row.get("categories") or []) for p in parts])
        if c and c.allowed_categories and not cats <= set(c.allowed_categories):
            return "outside the theme's categories"
        if c and c.single_category and len(cats) > 1:
            return "the theme needs a single data category"
        if c and c.single_dataset and len(set().union(*[set(p.row.get("datasets") or []) for p in parts])) > 1:
            return "the theme needs a single dataset"
        return None

    def estimate(self, parts: list[Part], corr: dict) -> Combo | None:
        """What BRAIN will report for the rank-sum of the parts, from their own results (no simulation):
        - Sharpe of the equal-risk sum of their daily PnL, cut for turnover: fast parts lose more when combined
          (`turnover_haircut` per unit of mean turnover above `haircut_from_turnover`);
        - returns: the parts' mean returns x sqrt(n / (1 + (n-1) * mean correlation)) - BRAIN rescales the summed
          positions to the same book, so diversified parts are levered up;
        - turnover: the parts' mean; fitness from the three, as BRAIN defines it;
        - production correlation: the most crowded part's (measured, else the crowding prior) times
          sd^-`prod_dilution`; the production pool already holds combinations of popular signals, so the
          dilution is weak (fitted on this engine's measured combinations)."""
        cfg = self.cfg
        ws = [p.weight for p in parts]
        res = combo_stats([p.pnl for p in parts], self.est_days, ws, cfg.get("estimate_scaling", "position"))
        if res is None:
            return None
        cs = [corr.get((a.row["id"], b.row["id"])) for a, b in combinations(parts, 2)]
        if any(c is None for c in cs):
            return None
        n = len(parts)
        sd = math.sqrt(n + 2 * sum(cs))
        sub_ratio, sub_required = self.sub_universe(parts, corr)
        st = [p.row.get("stats") or {} for p in parts]
        tos = [_f(x.get("turnover")) for x in st]
        rets = [_f(x.get("returns")) for x in st]
        turnover = sum(tos) / n if all(t is not None for t in tos) else None
        sharpe = res[0]
        if turnover is not None:
            sharpe *= max(0.0, 1.0 - float(cfg.get("turnover_haircut", 0.8))
                          * max(0.0, turnover - float(cfg.get("haircut_from_turnover", 0.2))))
        fitness = None
        if turnover is not None and all(r is not None for r in rets):
            rbar = sum(cs) / len(cs)
            returns = abs(sum(rets) / n) * math.sqrt(n / max(1e-6, 1 + (n - 1) * rbar))
            fitness = sharpe * math.sqrt(returns / max(turnover, 0.125))
        prod_est = max((p.prod if p.prod is not None else p.prior) for p in parts) * sd ** -float(cfg.get("prod_dilution", 0.15))
        mult = max(pyramid_of(self.ctx, cat) for p in parts for cat in (p.row.get("categories") or [None]))
        value = sharpe * (1.0 - min(prod_est, 0.99)) * mult
        return Combo(parts=parts, group="", sharpe=round(sharpe, 3), max_corr=round(max(cs), 3),
                     prod_est=round(prod_est, 3), value=round(value, 4),
                     fitness=round(fitness, 3) if fitness is not None else None,
                     turnover=round(turnover, 3) if turnover is not None else None,
                     sub_ratio=sub_ratio, sub_required=sub_required)

    @staticmethod
    def sub_universe(parts: list[Part], corr: dict) -> tuple[float | None, float | None]:
        """Estimated sub-universe ratio of the weighted combination: sum(w * sub) / sum(w * S), both over the same
        risk sqrt(sum w^2 + 2 sum w_i w_j rho_ij), so the ratio needs only the parts' own Sharpes, their own
        sub-universe Sharpes, their weights and their PnL volatility. Checked on this account: #486 0.40 estimated vs
        0.39 measured (fails 0.433), #493 0.436 vs 0.433 (passes at the limit), #516 0.46 vs 0.44."""
        if any(p.sub is None for p in parts):
            return None, None
        # each part counts with its weight times its PnL volatility (its share of a rank sum's risk); calibrated 19 Oct
        # on 9 composites: mean error 0.017 in the ratio
        vol = [(_std(list(p.pnl.values()))[0] if len(p.pnl) > 1 else 1.0) or 1.0 for p in parts]
        full = sum(p.weight * v * p.sharpe for p, v in zip(parts, vol))
        if full <= 0:
            return None, None
        ratio = sum(p.weight * v * p.sub for p, v in zip(parts, vol)) / full
        req = max((p.sub_required for p in parts if p.sub_required), default=None)
        return round(ratio, 3), (round(req, 3) if req else None)

    def like_submitted(self, c: Combo, subs: list[dict]) -> bool:
        """True when the combination trades like an alpha already submitted (at that alpha's limit); notes the
        closest ones."""
        res = combo_stats([p.pnl for p in c.parts], self.days)
        if res is None:
            return True
        common = common_dates([p.pnl for p in c.parts], self.days)
        series = dict(zip(common, res[1]))
        if self.route == "regular":
            # the combination as a whole must not trade like a crowded factor: parts that each lean on one only mildly
            # add up (19 Oct: composites at 0.50-0.53 with a reference factor were 0.77-0.83 with production; at 0.15-0.31,
            # 0.63-0.69)
            from . import references as refs
            if self._ref_pnls is None:
                self._ref_pnls = refs.pnls(self.ctx, self.simulator)
            if self._ref_pnls:
                v, name = refs.exposure(self.ctx, self.simulator, series, self._ref_pnls)
                if v is not None and abs(v) >= float(self.cfg.get("max_ref_corr", 0.45)):
                    c.notes.append(f"trades like the {name} factor ({v:.2f})")
                    return True
        target = float(self.cfg.get("max_submitted_corr", 1.0))  # stricter than BRAIN's limit: unique, not just allowed
        for sub in subs:
            v = pnl_correlation(series, sub["pnl"], self.days)
            if v is not None and v >= min(sub["limit"], target):
                return True
            if v is not None and v >= 0.5 * sub["limit"]:
                c.notes.append(f"{v:.2f} with submitted {sub['id']}")
        return False

    def submitted_pnls(self, lc: Lifecycle) -> list[dict]:
        """Daily PnL of the submitted alphas of this region and delay, each with the correlation it may not reach:
        regular alphas need self-correlation < 0.7 with everything; Power Pool alphas < 0.5 with Power Pool ones."""
        sc = self.ctx.scope
        pp_cls = self.ctx.pp.get("eligible_classification")
        reg_lim = float(self.ctx.cfg.get("regular.self_correlation_limit", 0.7))
        pp_lim = float(self.ctx.pp.get("correlation_limit", 0.5))
        out = []
        for a in lc.submitted:
            if a.get("region") != sc["region"] or int(a.get("delay") or -1) != int(sc["delay"]):
                continue
            pnl = daily_pnl(self.ctx, self.simulator, a["id"])
            if pnl:
                pp = self.route != "regular" and pp_cls in (a.get("classifications") or [])
                out.append({"id": a["id"], "pnl": pnl, "limit": pp_lim if pp else reg_lim})
        return out

    def combos(self, n: int | None = None, origin_prefix: str | None = None) -> list[Combo]:
        cfg = self.cfg
        n = int(n or cfg.get("per_step", 6))
        lc = Lifecycle(self.ctx, simulator=self.simulator)
        fams = lc.families()
        subs = self.submitted_pnls(lc)
        parts = self.parts(fams, origin_prefix, subs)
        if len(parts) < 2:
            return []
        bar = lc.floor * float(cfg.get("sharpe_margin", 1.1))
        max_corr = float(cfg.get("max_part_correlation", 0.5))
        known = set(fams)
        # composites already simulated under any shape label (hand-made ones included): same fields = same combination
        known_sets = {frozenset(key_fields(k)) for k, f in fams.items()
                      if any(_COMBINED.search(r.get("canonical") or "") or str(r.get("canonical") or "").startswith("add(")
                             for r in f.rows)}
        corr = {}
        for a, b in combinations(parts, 2):
            v = pnl_correlation(a.pnl, b.pnl, self.days)
            corr[(a.row["id"], b.row["id"])] = corr[(b.row["id"], a.row["id"])] = v

        def candidate(group: tuple, final: bool = True) -> Combo | None:
            """`final=False` evaluates a partial combination that may still grow into an integrated model."""
            if self.allowed(list(group)):
                return None
            gname = self.group_of(list(group), any_size=not final)
            if gname is None:
                return None
            fields = set().union(*[p.fields for p in group])
            if family_key(fields, "combo") in known or frozenset(fields) in known_sets:
                return None
            cs = [corr.get((a.row["id"], b.row["id"])) for a, b in combinations(group, 2)]
            if any(v is None or v > max_corr for v in cs):
                return None
            c = self.estimate(list(group), corr)
            if c is None:
                return None
            c.group = gname
            return c

        regular = self.route == "regular"
        min_fit = float(self.ctx.cfg.get("regular.min_fitness", 1.0)) * float(cfg.get("fitness_margin", 1.0))
        max_to = float(cfg.get("max_turnover", 0.45))

        sub_margin = float(cfg.get("sub_universe_margin", 1.02))

        def good(c: Combo) -> bool:
            if c.sharpe < bar or (c.turnover is not None and c.turnover > max_to):
                return False
            if c.sub_ratio is not None and c.sub_required is not None and c.sub_ratio < c.sub_required * sub_margin:
                return False  # the combination would fail the sub-universe test (its liquid part is too weak)
            return not regular or c.fitness is None or c.fitness >= min_fit

        def final_ok(c: Combo) -> bool:
            g = self.group_of(c.parts)
            if g is None:
                return False
            c.group = g
            return good(c)

        def score(c: Combo) -> float:
            """Estimated Sharpe, discounted when the combination would fail the sub-universe test: the search grows
            towards combinations that can pass every test, not only towards the highest Sharpe."""
            if c.sub_ratio is None or not c.sub_required:
                return c.sharpe
            return c.sharpe * min(1.0, c.sub_ratio / (c.sub_required * sub_margin))

        pairs = [c for c in (candidate(g, final=False) for g in combinations(parts, 2)) if c is not None]
        found = [c for c in pairs if final_ok(c)]
        # forward selection: grow the best combinations one part at a time while each new part lifts the estimate
        # by `third_part_gain` (a part must add, not ride along), up to `max_size` parts
        gain = float(cfg.get("third_part_gain", 0.15))
        frontier = sorted(pairs, key=lambda c: -score(c))[: int(cfg.get("triples_from_pairs", 25))]
        for size in range(3, int(cfg.get("max_size", 3)) + 1):
            grown = []
            for pc in frontier:
                for p in parts:
                    if p in pc.parts:
                        continue
                    c = candidate(tuple(pc.parts) + (p,), final=False)
                    if c is not None and score(c) >= score(pc) + gain and (c.turnover is None or c.turnover <= max_to):
                        grown.append(c)
            grown.sort(key=lambda c: -score(c))
            seen_sets = set()
            frontier = []
            for c in grown:  # keep the best few distinct combinations of this size to grow further
                ids = frozenset(p.row["id"] for p in c.parts)
                if ids not in seen_sets:
                    seen_sets.add(ids)
                    frontier.append(c)
                if len(frontier) >= int(cfg.get("frontier", 25)):
                    break
            found += [c for c in frontier if final_ok(c)]
            if not frontier:
                break
        found.sort(key=lambda c: -c.value)
        reuse = int(cfg.get("part_reuse", 2))  # breadth: each part in at most this many proposals per step
        used: dict[int, int] = {}
        seen_sets = set()
        out = []
        for c in found:
            ids = frozenset(p.row["id"] for p in c.parts)
            if ids in seen_sets or any(used.get(p.row["id"], 0) >= reuse for p in c.parts):
                continue
            seen_sets.add(ids)
            if self.like_submitted(c, subs):
                continue
            for p in c.parts:
                used[p.row["id"]] = used.get(p.row["id"], 0) + 1
            out.append(c)
            if len(out) >= n:
                break
        return out

    # -- candidates --------------------------------------------------------------------------------
    @staticmethod
    def _ranked(code: str) -> str:
        """The part as a uniform cross-sectional score: kept as is when the whole code already is one rank(...)."""
        code = code.strip()
        if code.startswith("rank(") and code.endswith(")"):
            depth = 0
            for i, ch in enumerate(code[4:], start=4):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0 and i < len(code) - 1:
                        break  # the first rank(...) closes early, e.g. rank(a) - rank(b)
            else:
                return code
        return f"rank({code})"

    def raw(self, c: Combo) -> dict:
        g = self.groups.get(c.group) or {}
        exprs = [self._ranked(p.code) for p in c.parts]
        if self.cfg.get("nan_safe", True):
            # a stock missing one part keeps the other parts' views: centred ranks, NaN counted as neutral (0)
            # (16 Oct: plain rank sums dropped 15-20% of the universe and cost ~0.5 Sharpe); a part whose effect lives
            # in illiquid stocks enters at its lower weight
            terms = [f"{e} - 0.5" if p.weight == 1.0 else f"{p.weight:g} * ({e} - 0.5)" for e, p in zip(exprs, c.parts)]
            nan_safe = f"add({', '.join(terms)}, filter=true)"
        else:
            nan_safe = None
        neut = self.neutralization(c.parts)
        decay = max(int((p.row.get("settings") or {}).get("decay") or 0) for p in c.parts)
        names = [f"{', '.join(sorted(p.fields))} (Sharpe {p.sharpe:.2f}, {p.kind})" for p in c.parts]
        return {
            "expression": nan_safe or " + ".join(exprs), "shape": "combo", "neutralization": neut or None, "decay": decay,
            "idea": (f"{_sentence(g.get('rationale'))} ({'; '.join(g.get('sources') or [])}). "
                     f"This alpha averages {len(c.parts)} such signals whose daily PnL is at most {c.max_corr:.2f} "
                     "correlated, so the combination is stronger and less like any single crowded signal."),
            "rationale_data": "; ".join(f"{p.code}: {self._desc(p)}" for p in c.parts),
            "rationale_operators": "rank() puts each signal on the same uniform cross-sectional scale so each part "
                                   "carries a similar share of the risk; subtracting 0.5 centres it; add(..., filter=true) "
                                   "averages the parts and counts a missing part as neutral instead of dropping the stock.",
            "_estimate": {"sharpe": c.sharpe, "fitness": c.fitness, "turnover": c.turnover,
                          "sub_ratio": c.sub_ratio, "sub_required": c.sub_required,
                          "max_corr": c.max_corr, "prod_est": c.prod_est, "value": c.value,
                          "parts": [p.row["id"] for p in c.parts], "group": c.group, "names": names, "notes": c.notes},
        }

    def neutralization(self, parts: list[Part]) -> str | None:
        """The parts' shared group neutralization: the majority if there is one, else the strongest part's. A
        risk-factor set (SLOW, CROWDING, ...) is kept only when every part used it - it changes what each part
        earns, so the PnL estimate would not hold (16 Oct: a tie that fell to SLOW cut Sharpe from 2.2 to 1.18)."""
        risk = {str(v).upper() for v in (self.ctx.cfg.get("regular.risk_neutralizations") or {}).values()}
        neuts = [str((p.row.get("settings") or {}).get("neutralization") or "").upper() for p in parts]
        if neuts and len(set(neuts)) == 1:
            return neuts[0] or None
        plain = [(p.sharpe, n) for p, n in zip(parts, neuts) if n and n not in risk]
        if not plain:
            return self.ctx.defaults.get("neutralization")
        counts = {n: sum(1 for _, m in plain if m == n) for _, n in plain}
        top = max(counts.values())
        winners = [n for n, k in counts.items() if k == top]
        if len(winners) == 1 and top > 1:
            return winners[0]
        return max(plain)[1]  # no majority: the strongest part's

    def _desc(self, p: Part) -> str:
        bits = []
        for fid in sorted(p.fields):
            f = self.ctx.store.field(fid, self.ctx.scope) or {}
            bits.append(f"{fid} ({f.get('dataset')}): {(f.get('description') or '')[:140]}")
        return "; ".join(bits)

    def run(self, n: int | None = None, origin_prefix: str | None = None) -> list[Candidate]:
        combos = self.combos(n, origin_prefix)
        if not combos:
            console.print("  no combination clears the estimate (parts, correlation, Sharpe margin, mechanism)")
            return []
        console.print(f"  {len(combos)} combination(s) estimated to clear Sharpe {self.ctx.cfg.get('combine.sharpe_margin', 1.1)}x the bar:")
        out = []
        for c in combos:
            raw = self.raw(c)
            est = raw["_estimate"]
            fit = f", fitness ~{c.fitness:.2f}" if c.fitness is not None else ""
            sub = (f", sub-universe ~{c.sub_ratio:.2f} (needs {c.sub_required:.2f})"
                   if c.sub_ratio is not None and c.sub_required is not None else "")
            labels = [str(p.row["id"]) if p.weight == 1.0 else f"{p.weight:g}x{p.row['id']}" for p in c.parts]
            console.print(f"    est. Sharpe {est['sharpe']:.2f}{fit}{sub}, parts corr <= {est['max_corr']:.2f}, "
                          f"prod corr ~{est['prod_est']:.2f} [{c.group}]: {' + '.join(labels)}")
            cand = self.gen.check(raw, origin=f"combine:{c.group}")
            out.append(cand)
        return out
