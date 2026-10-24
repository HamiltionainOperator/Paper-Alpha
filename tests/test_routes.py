"""Submission routes: the regular (production) verdict, BRAIN's payment multipliers, and combinations."""
import math
import random
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from p2a.config import Config
from p2a.engine.combiner import Combiner, combo_stats
from p2a.engine.evaluator import evaluate
from p2a.engine.lifecycle import Lifecycle, family_key, value_score
from p2a.engine.routes import multipliers, record_themes, regular_verdict, theme_universe
from p2a.store import Store

SCOPE = {"instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000", "delay": 1}


def check(name, result, value=None, limit=None, **kw):
    return {"name": name, "result": result, "value": value, "limit": limit, **kw}


def passing(**override):
    """The checks of a fresh simulation that passes every computed regular test."""
    base = [check("LOW_SHARPE", "PASS", 1.9, 1.58), check("LOW_FITNESS", "PASS", 1.1, 1.0),
            check("LOW_TURNOVER", "PASS", 0.2, 0.01), check("HIGH_TURNOVER", "PASS", 0.2, 0.7),
            check("CONCENTRATED_WEIGHT", "PASS"), check("LOW_SUB_UNIVERSE_SHARPE", "PASS", 1.0, 0.8),
            check("LOW_2Y_SHARPE", "PASS", 1.9, 1.58), check("SELF_CORRELATION", "PENDING"),
            check("PROD_CORRELATION", "PENDING"), check("REGULAR_SUBMISSION", "PENDING"),
            check("CLUSTER_TEST", "WARNING", 1.2, 1.58), check("OSMOSIS_ALLOCATION", "WARNING"),
            {"name": "MATCHES_PYRAMID", "result": "PASS", "multiplier": 1.3, "pyramids": [{"name": "USA/D1/MODEL", "multiplier": 1.3}]},
            {"name": "MATCHES_THEMES", "result": "WARNING", "themes": [{"id": "T1", "name": "USA/D1 TOP1000 Theme", "multiplier": 2.0}]}]
    out = []
    for c in base:
        if c["name"] in override:
            c = {**c, **override[c["name"]]}
        out.append(c)
    return out


class RegularVerdictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rc = Config.load(None).section("regular")

    def verdict(self, checks, sharpe=1.9, atom=False):
        return regular_verdict(checks, {"sharpe": sharpe}, self.rc, atom=atom)

    def test_correlations_pending_means_check_it(self):
        status, why = self.verdict(passing())
        self.assertEqual(status, "pending")
        self.assertIn("PROD_CORRELATION", why[0])

    def test_all_passed_is_eligible_and_informational_checks_do_not_block(self):
        status, _ = self.verdict(passing(SELF_CORRELATION={"result": "PASS", "value": 0.3},
                                         PROD_CORRELATION={"result": "PASS", "value": 0.55},
                                         REGULAR_SUBMISSION={"result": "PASS"}))
        self.assertEqual(status, "eligible")  # cluster tag, Osmosis and a missed theme are not tests

    def test_power_pool_exempt_warning_is_a_regular_failure(self):
        # BRAIN shows the regular tests a Power Pool alpha is exempt from as WARNING
        status, why = self.verdict(passing(PROD_CORRELATION={"result": "WARNING", "value": 0.75, "limit": 0.7}))
        self.assertEqual(status, "near_miss")
        self.assertTrue(any("PROD_CORRELATION WARNING" in w for w in why))
        status, _ = self.verdict(passing(LOW_SHARPE={"result": "WARNING", "value": 1.1}), sharpe=1.1)
        self.assertEqual(status, "fail")  # far below the bar: not even a near miss

    def test_a_test_brain_could_not_compute_is_not_a_pass(self):
        checks = passing(SELF_CORRELATION={"result": "PASS", "value": 0.3}, PROD_CORRELATION={"result": "ERROR"},
                         REGULAR_SUBMISSION={"result": "PASS"})
        status, why = self.verdict(checks)
        self.assertEqual(status, "pending")
        self.assertIn("ERROR", why[0])
        status, _ = regular_verdict(checks, {"sharpe": 1.9, "prod_corr": 0.62}, self.rc)
        self.assertEqual(status, "eligible")  # measured with the correlation endpoint instead

    def test_hard_failures_and_quota(self):
        status, _ = self.verdict(passing(CONCENTRATED_WEIGHT={"result": "FAIL"}))
        self.assertEqual(status, "fail")
        status, why = self.verdict(passing(SELF_CORRELATION={"result": "PASS"}, PROD_CORRELATION={"result": "PASS"},
                                           REGULAR_SUBMISSION={"result": "FAIL", "value": 4, "limit": 4}))
        self.assertEqual(status, "eligible")
        self.assertTrue(why[0].startswith("WAIT"))

    def test_atom_alphas_skip_the_is_ladder_only(self):
        checks = passing(SELF_CORRELATION={"result": "PASS"}, PROD_CORRELATION={"result": "PASS"},
                         REGULAR_SUBMISSION={"result": "PASS"}) + [check("IS_LADDER_SHARPE", "FAIL", 1.4, 1.58)]
        self.assertEqual(self.verdict(checks, atom=True)[0], "eligible")
        self.assertNotEqual(self.verdict(checks, atom=False)[0], "eligible")

    def test_evaluate_reports_both_routes_and_uniqueness_stats(self):
        cfg = Config.load(None)
        checks = passing(SELF_CORRELATION={"result": "PASS", "value": 0.3}, PROD_CORRELATION={"result": "WARNING", "value": 0.75})
        alpha = {"is": {"sharpe": 1.9, "fitness": 1.1, "turnover": 0.2, "longCount": 1400, "shortCount": 1400,
                        "checks": checks, "riskNeutralized": {"sharpe": 1.2, "returns": 0.03, "fitness": 0.5}},
                 "settings": {"universe": "TOP3000"}, "classifications": []}
        ev = evaluate(alpha, cfg.section("power_pool"), cfg.section("scoring"), cfg.section("refine"),
                      quality=cfg.section("quality"), regular=cfg.section("regular"), datasets=["d1"])
        self.assertEqual(ev.reg_status, "near_miss")
        self.assertEqual(ev.stats["prod_corr"], 0.75)
        self.assertEqual(ev.stats["rn_sharpe"], 1.2)
        self.assertEqual(ev.stats["mult"], 1.3)  # pyramid x1.3; the TOP1000 theme was not matched


class MultiplierTests(unittest.TestCase):
    def test_pyramid_and_theme_multipliers(self):
        checks = [{"name": "MATCHES_PYRAMID", "result": "PASS", "multiplier": 1.3, "pyramids": [{"name": "USA/D1/MODEL"}]},
                  {"name": "MATCHES_THEMES", "result": "PASS", "themes": [
                      {"id": "a", "name": "D1 Power Pool Oct`26 2", "multiplier": 1.0},
                      {"id": "b", "name": "USA/D1/MODEL Pyramid Theme", "multiplier": 1.3}]},
                  {"name": "MATCHES_THEMES", "result": "WARNING", "themes": [{"id": "c", "name": "USA/D1 TOP1000 Theme", "multiplier": 2.0}]}]
        m = multipliers(checks)
        self.assertEqual(m["pyramid"], 1.3)
        self.assertEqual(m["theme"], 1.0)  # the pyramid theme is the pyramid multiplier, not counted twice
        self.assertEqual([t["name"] for t in m["missed"]], ["USA/D1 TOP1000 Theme"])

    def test_theme_universe_from_observed_themes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "t.sqlite")
            checks = [{"name": "MATCHES_THEMES", "result": "WARNING",
                       "themes": [{"id": "c", "name": "USA/D1 TOP1000 Theme", "multiplier": 2.0}]}]
            record_themes(store, checks, {"region": "USA", "delay": 1})
            allowed = ["TOP3000", "TOP1000", "TOP500"]
            self.assertEqual(theme_universe(store, SCOPE, allowed)[0], "TOP1000")
            self.assertIsNone(theme_universe(store, {**SCOPE, "region": "EUR"}, allowed)[0])
            self.assertIsNone(theme_universe(store, {**SCOPE, "delay": 0}, allowed)[0])
            seen = store.kv_get("observed_themes")
            seen["c"]["seen_at"] = time.time() - 10 * 86400  # an old sighting does not count as active
            store.kv_set("observed_themes", seen)
            self.assertIsNone(theme_universe(store, SCOPE, allowed)[0])
            store.close()


def series(seed, sharpe, n=2500, common=None, w=0.0):
    """Daily PnL with a given annualised Sharpe; `common` mixes in a shared component (correlation)."""
    rnd = random.Random(seed)
    mu = sharpe / math.sqrt(252)
    out = {}
    for i in range(n):
        d = f"2015-{i:05d}"
        x = rnd.gauss(0, 1)
        if common is not None:
            x = math.sqrt(1 - w * w) * x + w * common[d]
        out[d] = mu + x
    return out


class CombinerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite")
        self.cfg = Config.load(None)
        self.ctx = SimpleNamespace(cfg=self.cfg, store=self.store, scope=SCOPE, pp=self.cfg.section("power_pool"),
                                   sync=SimpleNamespace(client=None), catalog=None, constraints=None, route="regular")
        self.n = 0
        self.store.upsert_datasets([{"id": "opt", "category": {"id": "option"}, "alphaCount": 30},
                                    {"id": "anl", "category": {"id": "analyst"}, "alphaCount": 40},
                                    {"id": "nws", "category": {"id": "news"}, "alphaCount": 20}], SCOPE)
        self.store.upsert_fields([
            {"id": "iv_spread", "dataset": {"id": "opt"}, "category": {"id": "option"}, "type": "MATRIX",
             "description": "Implied volatility spread between call and put options", "coverage": 0.9},
            {"id": "eps_rev", "dataset": {"id": "anl"}, "category": {"id": "analyst"}, "type": "MATRIX",
             "description": "Analyst EPS estimate revision", "coverage": 0.9},
            {"id": "tone", "dataset": {"id": "nws"}, "category": {"id": "news"}, "type": "MATRIX",
             "description": "News sentiment tone", "coverage": 0.9}], SCOPE)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, field, dataset, category, sharpe, pnl, checks=None, turnover=0.2, returns=None):
        self.n += 1
        aid = self.store.add_alpha({"payload_hash": f"h{self.n}", "canonical": f"rank({field})", "expression": "x",
                                    "settings": {"decay": 4, "neutralization": "INDUSTRY", "universe": "TOP3000"},
                                    "region": "USA", "delay": 1, "universe": "TOP3000", "fields": [field],
                                    "operators": ["rank"], "status": "valid", "datasets": [dataset],
                                    "categories": [category], "origin": "explore", "shape_class": "level"})
        self.store.update_alpha(aid, status="simulated", pp_status="near_miss", reg_status="fail", brain_id=f"B{self.n}",
                                stats={"sharpe": sharpe, "turnover": turnover, "returns": returns}, checks=checks or [],
                                pp_reasons=[])
        cum, rec = 0.0, []
        for d in sorted(pnl):
            cum += pnl[d]
            rec.append([d, cum])
        self.store.kv_set(f"pnl:B{self.n}", rec)
        return aid

    def test_position_scaling_follows_the_volatile_part_like_a_rank_sum(self):
        strong = {d: 5.0 * v for d, v in series(1, 2.0).items()}   # Sharpe 2, five times the PnL volatility
        weak = series(2, 0.0)                                        # no signal, low volatility
        pos, _ = combo_stats([strong, weak], 10 ** 6)                # rank sums: equal positions, PnL as simulated
        risk, _ = combo_stats([strong, weak], 10 ** 6, scaling="risk")
        self.assertGreater(pos, 1.7)                                 # the noise part barely dilutes
        self.assertLess(risk, 1.6)                                   # equal risk would let it halve the Sharpe

    def test_equal_risk_sum_of_independent_signals(self):
        a, b = series(1, 1.2), series(2, 1.2)
        s, _ = combo_stats([a, b], 10 ** 6)
        self.assertAlmostEqual(s, 1.2 * math.sqrt(2), delta=0.5)

    def test_combines_linked_uncrowded_signals_and_skips_unlinked_ones(self):
        common = series(9, 0.0)
        self.add("iv_spread", "opt", "option", 1.6, series(1, 1.6, common=common, w=0.2))
        self.add("eps_rev", "anl", "analyst", 1.6, series(2, 1.6, common=common, w=0.2))
        self.add("tone", "nws", "news", 1.6, series(3, 1.6))
        self.store.kv_set("submitted_alphas", [])
        self.store.kv_set("pyramid_multipliers", {"USA/1/option": 1.3, "USA/1/analyst": 1.2, "USA/1/news": 1.2})
        comb = Combiner(self.ctx, generator=None, simulator=None)
        combos = comb.combos(5)
        self.assertTrue(combos, "two linked signals of Sharpe 1.6, weakly correlated, clear 1.1 x 1.58 together")
        names = [{p.row["fields"][0] for p in c.parts} for c in combos]
        self.assertIn({"iv_spread", "eps_rev"}, names)   # informed trading: options + analyst revisions
        self.assertNotIn({"iv_spread", "tone"}, names)    # option demand and news tone share no mechanism group
        c = next(c for c in combos if {p.row["fields"][0] for p in c.parts} == {"iv_spread", "eps_rev"})
        self.assertLess(c.prod_est, max(p.prior for p in c.parts))  # diluted below either part's own prior
        raw = comb.raw(c)
        # NaN-safe: a stock missing one part keeps the other's view
        self.assertEqual(raw["expression"], "add(rank(iv_spread) - 0.5, rank(eps_rev) - 0.5, filter=true)")
        self.assertIn("Cremers and Weinbaum", raw["idea"])

    def test_estimates_cut_fast_parts_and_predict_fitness(self):
        self.store.kv_set("pyramid_multipliers", {})
        self.cfg.data.setdefault("combine", {})["turnover_haircut"] = 0.8  # the haircut mechanism (default now 0)
        comb = Combiner(self.ctx, generator=None, simulator=None)
        a = self.add("iv_spread", "opt", "option", 1.6, series(1, 1.6), turnover=0.2, returns=0.05)
        b = self.add("eps_rev", "anl", "analyst", 1.6, series(2, 1.6), turnover=0.2, returns=0.05)
        lc = Lifecycle(self.ctx, submitted=[])
        parts = comb.parts(lc.families())
        corr = {(x.row["id"], y.row["id"]): 0.0 for x in parts for y in parts}
        slow = comb.estimate(parts, corr)
        # fitness = Sharpe * sqrt(returns / turnover), returns levered by sqrt(2) for two uncorrelated parts
        self.assertAlmostEqual(slow.fitness, slow.sharpe * math.sqrt(0.05 * math.sqrt(2) / 0.2), places=2)
        for p in parts:
            p.row["stats"]["turnover"] = 0.6
        fast = comb.estimate(parts, corr)
        self.assertAlmostEqual(fast.sharpe / slow.sharpe, 1 - 0.8 * (0.6 - 0.2), places=2)

    def test_combination_neutralization_ignores_a_lone_risk_set(self):
        from p2a.engine.combiner import Part
        self.ctx.defaults = {"neutralization": "SUBINDUSTRY"}
        comb = Combiner(self.ctx, generator=None, simulator=None)

        def part(sharpe, neut):
            return Part(row={"settings": {"neutralization": neut}, "stats": {"sharpe": sharpe}, "fields": []},
                        kind=None, pnl={}, prod=None, prior=0.6)
        self.assertEqual(comb.neutralization([part(1.4, "INDUSTRY"), part(1.5, "SLOW"), part(1.3, "SUBINDUSTRY")]), "INDUSTRY")
        self.assertEqual(comb.neutralization([part(1.2, "INDUSTRY"), part(1.3, "SUBINDUSTRY"), part(1.1, "SUBINDUSTRY")]),
                         "SUBINDUSTRY")
        self.assertEqual(comb.neutralization([part(1.2, "SLOW"), part(1.3, "SLOW")]), "SLOW")

    def test_a_strongly_negative_idea_enters_with_its_sign_inverted(self):
        self.store.kv_set("submitted_alphas", [])
        self.store.kv_set("pyramid_multipliers", {})
        neg = series(1, 1.6)
        self.add("iv_spread", "opt", "option", -1.6, {d: -v for d, v in neg.items()})
        self.add("eps_rev", "anl", "analyst", 1.6, series(2, 1.6))
        comb = Combiner(self.ctx, generator=None, simulator=None)
        parts = comb.parts(Lifecycle(self.ctx, submitted=[]).families())
        flipped = next(p for p in parts if p.row["fields"] == ["iv_spread"])
        self.assertEqual((flipped.sign, flipped.sharpe, flipped.code), (-1, 1.6, "-(rank(iv_spread))"))
        c = next(c for c in comb.combos(5) if len(c.parts) == 2)
        self.assertIn("rank(-(rank(iv_spread))) - 0.5", comb.raw(c)["expression"])

    def test_a_combination_that_trades_like_a_submission_is_skipped(self):
        a, b = series(1, 1.6), series(2, 1.6)
        self.add("iv_spread", "opt", "option", 1.6, a)
        self.add("eps_rev", "anl", "analyst", 1.6, b)
        sub = {d: a[d] + b[d] for d in a}
        cum, rec = 0.0, []
        for d in sorted(sub):
            cum += sub[d]
            rec.append([d, cum])
        self.store.kv_set("pnl:SUB1", rec)
        self.store.kv_set("submitted_alphas", [{"id": "SUB1", "fields": ["x_y"], "region": "USA", "delay": 1,
                                                 "classifications": [], "code": "rank(x_y)"}])
        self.store.kv_set("pyramid_multipliers", {})
        self.assertEqual(Combiner(self.ctx, generator=None, simulator=None).combos(5), [])

    def test_mild_factor_tilts_that_add_up_make_the_combination_crowded(self):
        rnd = random.Random(7)
        days = sorted(series(1, 0.0))
        factor = {d: rnd.gauss(0, 1) for d in days}
        cum, rec = 0.0, []
        for d in days:
            cum += factor[d]
            rec.append([d, cum])
        self.store.kv_set("pnl:REF1", rec)
        self.store.kv_set("reference:USA:1:TOP3000:reversal_5d", {"brain_id": "REF1", "expression": "-rank(returns)"})
        self.cfg.data.setdefault("uniqueness", {})["references"] = [{"id": "reversal_5d", "expression": "-rank(returns)"}]
        a, b = series(2, 1.6), series(3, 1.6)
        tilt_a = {d: a[d] + 0.55 * factor[d] for d in days}   # each part alone: about 0.48 with the factor
        tilt_b = {d: b[d] + 0.55 * factor[d] for d in days}
        self.add("iv_spread", "opt", "option", 1.6, tilt_a)
        self.add("eps_rev", "anl", "analyst", 1.6, tilt_b)
        self.store.kv_set("submitted_alphas", [])
        self.store.kv_set("pyramid_multipliers", {})
        comb = Combiner(self.ctx, generator=None, simulator=None)
        parts = comb.parts(Lifecycle(self.ctx, submitted=[]).families())
        self.assertEqual(len(parts), 2)                          # neither part is crowded on its own (< 0.6)
        c = comb.estimate(parts, {(parts[0].row["id"], parts[1].row["id"]): 0.25, (parts[1].row["id"], parts[0].row["id"]): 0.25})
        self.assertTrue(comb.like_submitted(c, []))              # together they trade like the factor
        self.assertTrue(any("reversal_5d" in n for n in c.notes))

    def test_a_part_that_drives_a_submitted_alpha_stays_out(self):
        a, b = series(1, 1.6), series(2, 1.6)
        ia = self.add("iv_spread", "opt", "option", 1.6, a)
        self.add("eps_rev", "anl", "analyst", 1.6, b)
        cum, rec = 0.0, []
        for d in sorted(b):  # the submitted alpha is the eps_rev signal itself
            cum += b[d]
            rec.append([d, cum])
        self.store.kv_set("pnl:SUB2", rec)
        subs = [{"id": "SUB2", "pnl": {d: b[d] for d in b}, "limit": 0.7}]
        parts = Combiner(self.ctx, generator=None, simulator=None).parts(Lifecycle(self.ctx, submitted=[]).families(),
                                                                        subs=subs)
        self.assertEqual([p.row["id"] for p in parts], [ia])

    def test_a_part_that_trades_like_a_crowded_factor_stays_out_of_regular_combinations(self):
        a = self.add("iv_spread", "opt", "option", 1.6, series(1, 1.6))
        b = self.add("eps_rev", "anl", "analyst", 1.6, series(2, 1.6))
        self.store.update_alpha(b, stats={"sharpe": 1.6, "turnover": 0.2, "ref_corr": 0.8, "ref_factor": "reversal_5d"})
        parts = Combiner(self.ctx, generator=None, simulator=None).parts(Lifecycle(self.ctx, submitted=[]).families())
        self.assertEqual([p.row["id"] for p in parts], [a])

    def test_the_combination_sub_universe_ratio_is_estimated_from_its_parts(self):
        from p2a.engine.combiner import Part

        def part(sharpe, sub, weight=1.0):
            return Part(row={"stats": {"sharpe": sharpe}, "fields": []}, kind="k", pnl={}, prod=None, prior=0.6,
                        sub=sub, sub_required=0.433, weight=weight)
        # the parts of #486: smirk, profitability tone, leverage tone, lending tightness (measured 1.01 / 2.58 = 0.39)
        p486 = [part(1.80, 0.87), part(1.04, 0.48), part(1.10, 0.39), part(1.43, 0.35)]
        ratio, req = Combiner.sub_universe(p486, {})
        self.assertAlmostEqual(ratio, 0.39, delta=0.02)
        self.assertEqual(req, 0.433)
        # #494: implied-volatility innovations added, the two illiquid parts at half weight (measured 0.49)
        p494 = [part(1.80, 0.87), part(1.04, 0.48), part(1.10, 0.39, 0.5), part(1.43, 0.35, 0.5), part(0.95, 0.66)]
        self.assertAlmostEqual(Combiner.sub_universe(p494, {})[0], 0.47, delta=0.03)
        self.assertEqual(Combiner.sub_universe([part(1.2, None)], {}), (None, None))

    def test_an_illiquid_part_joins_at_half_weight_and_says_so_in_the_code(self):
        from p2a.engine.combiner import Combo, Part
        comb = Combiner(self.ctx, generator=None, simulator=None)
        liquid = Part(row={"id": 1, "canonical": "rank(a_x)", "stats": {"sharpe": 1.5}, "fields": ["a_x"], "settings": {}},
                      kind="k1", pnl={}, prod=None, prior=0.6)
        illiquid = Part(row={"id": 2, "canonical": "rank(b_y)", "stats": {"sharpe": 1.4}, "fields": ["b_y"], "settings": {}},
                        kind="k2", pnl={}, prod=None, prior=0.6, weight=0.5)
        c = Combo(parts=[liquid, illiquid], group="g", sharpe=2.0, max_corr=0.1, prod_est=0.6, value=1.0)
        self.assertEqual(comb.raw(c)["expression"], "add(rank(a_x) - 0.5, 0.5 * (rank(b_y) - 0.5), filter=true)")

    def test_different_mechanisms_may_share_a_field_but_one_idea_may_not_count_twice(self):
        from p2a.engine.combiner import Part
        comb = Combiner(self.ctx, generator=None, simulator=None)

        def part(fields, kind):
            return Part(row={"fields": fields, "stats": {"sharpe": 1.2}, "categories": ["option"], "datasets": ["opt"]},
                        kind=kind, pnl={}, prod=None, prior=0.6)
        smirk, innovation = part(["put_iv", "call_iv"], "option_smirk"), part(["call_iv", "put_atm_iv"], "option_iv_innovation")
        self.assertIsNone(comb.allowed([smirk, innovation]))
        self.assertEqual(comb.allowed([smirk, part(["call_iv"], "option_smirk")]), "parts share fields")

    def test_flat_days_count_in_the_estimate_and_sparse_parts_are_skipped(self):
        from p2a.engine.combiner import active_ratio
        dense = series(1, 1.2)
        days = sorted(dense)
        sparse = {d: (v if i % 10 == 0 else 0.0) for i, (d, v) in enumerate(sorted(series(2, 1.2).items()))}
        self.assertAlmostEqual(active_ratio(sparse), 0.1, delta=0.01)
        self.assertEqual(active_ratio(dense), 1.0)
        # an alpha that trades one day in ten: the days it is flat dilute its Sharpe, as in BRAIN's own number
        self.assertIsNone(combo_stats([sparse, {d: 0.0 for d in days}], 10 ** 6))  # a part that never trades
        s_sparse, _ = combo_stats([sparse, sparse], 10 ** 6)
        self.assertLess(s_sparse, 1.2 * 1.5)  # not inflated to the active-day Sharpe (about 1.2 x sqrt(10))
        self.add("iv_spread", "opt", "option", 1.2, sparse)
        self.add("eps_rev", "anl", "analyst", 1.6, dense)
        parts = Combiner(self.ctx, generator=None, simulator=None).parts(Lifecycle(self.ctx, submitted=[]).families())
        self.assertEqual([p.row["fields"] for p in parts], [["eps_rev"]])


class RegularLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite")
        self.cfg = Config.load(None)
        self.ctx = SimpleNamespace(cfg=self.cfg, store=self.store, scope=SCOPE, pp=self.cfg.section("power_pool"),
                                   sync=SimpleNamespace(client=None), catalog=None, constraints=None, route="regular")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, sharpe, prod, neut="INDUSTRY", origin="llm", reg="near_miss", pp="eligible"):
        aid = self.store.add_alpha({"payload_hash": f"h{neut}{origin}", "canonical": "rank(f_x)", "expression": "x",
                                    "settings": {"decay": 4, "neutralization": neut, "universe": "TOP3000"},
                                    "region": "USA", "delay": 1, "universe": "TOP3000", "fields": ["f_x"],
                                    "operators": ["rank"], "status": "valid", "origin": origin})
        checks = [check("PROD_CORRELATION", "WARNING", prod, 0.7), check("LOW_SHARPE", "PASS", sharpe, 1.58)]
        self.store.update_alpha(aid, status="simulated", pp_status=pp, reg_status=reg, brain_id=f"B{aid}",
                                stats={"sharpe": sharpe, "turnover": 0.1, "prod_corr": prod}, checks=checks, pp_reasons=[])
        return aid

    def test_crowded_family_gets_one_decorrelating_attempt_on_the_regular_route(self):
        self.add(1.7, 0.78)
        lc = Lifecycle(self.ctx, submitted=[])
        self.assertEqual(lc.floor, 1.58)
        fam = lc.families()[family_key(["f_x"], "level")]
        self.assertEqual((fam.state, fam.remedies), ("promising", ["decorrelate"]))
        # a Power Pool winner is not a regular winner
        pp = Lifecycle(self.ctx, submitted=[], route="power_pool").families()[family_key(["f_x"], "level")]
        self.assertEqual(pp.state, "winner")
        self.add(1.6, 0.74, neut="SLOW", origin="refine:decorrelate")
        fam = Lifecycle(self.ctx, submitted=[]).families()[family_key(["f_x"], "level")]
        self.assertEqual(fam.state, "dropped")
        self.assertIn("crowded for production", fam.reason)

    def test_measured_production_correlation_also_triggers_decorrelation(self):
        aid = self.store.add_alpha({"payload_hash": "hm", "canonical": "rank(g_y)", "expression": "x",
                                    "settings": {"decay": 4, "neutralization": "INDUSTRY", "universe": "TOP3000"},
                                    "region": "USA", "delay": 1, "universe": "TOP3000", "fields": ["g_y"],
                                    "operators": ["rank"], "status": "valid", "origin": "combine:x"})
        self.store.update_alpha(aid, status="simulated", pp_status="near_miss", reg_status="near_miss", brain_id="BM",
                                stats={"sharpe": 2.6, "turnover": 0.36, "prod_corr": 0.737},
                                checks=[check("PROD_CORRELATION", "PENDING")], pp_reasons=[])
        fam = Lifecycle(self.ctx, submitted=[]).families()[family_key(["g_y"], "level")]
        self.assertEqual((fam.state, fam.remedies), ("promising", ["decorrelate"]))

    def test_a_submitted_alpha_uses_up_its_family(self):
        aid = self.add(1.9, 0.6, reg="eligible")
        sub = [{"id": f"B{aid}", "fields": ["f_x"], "region": "USA", "delay": 1, "classifications": [],
                "code": "rank(f_x) + rank(f_x)"}]  # its code would classify differently than the row's shape
        fam = Lifecycle(self.ctx, submitted=sub).families()[family_key(["f_x"], "level")]
        self.assertEqual(fam.state, "used")

    def test_an_idea_that_trades_like_a_reference_factor_gets_one_residual_test(self):
        aid = self.store.add_alpha({"payload_hash": "hr", "canonical": "-rank(vec_avg(gap_x))", "expression": "x",
                                    "settings": {"decay": 4, "neutralization": "SUBINDUSTRY", "universe": "TOP3000"},
                                    "region": "USA", "delay": 1, "universe": "TOP3000", "fields": ["gap_x"],
                                    "operators": ["rank", "vec_avg"], "status": "valid", "origin": "mechanism:x"})
        self.store.update_alpha(aid, status="simulated", pp_status="near_miss", reg_status="near_miss", brain_id="BR",
                                stats={"sharpe": 1.3, "turnover": 0.3, "ref_corr": -0.75, "ref_factor": "reversal_1d"},
                                checks=[], pp_reasons=[])
        fam = next(f for k, f in Lifecycle(self.ctx, submitted=[]).families().items() if "gap_x" in k)
        self.assertEqual((fam.state, fam.remedies), ("promising", ["orthogonalize"]))
        # its residual had no signal: the idea was the factor
        kid = self.store.add_alpha({"payload_hash": "hk", "canonical": "sig = x; sig - regression_proj(sig, -rank(returns))",
                                    "expression": "x", "settings": {"universe": "TOP3000"}, "region": "USA", "delay": 1,
                                    "universe": "TOP3000", "fields": ["gap_x", "returns"], "operators": ["rank"],
                                    "status": "valid", "origin": "refine:orthogonalize", "parent_id": aid})
        self.store.update_alpha(kid, status="simulated", brain_id="BK", stats={"sharpe": -0.2, "turnover": 0.7},
                                checks=[], pp_status="fail", reg_status="fail", pp_reasons=[])
        fam = next(f for k, f in Lifecycle(self.ctx, submitted=[]).families().items() if k.startswith("gap_x|"))
        self.assertEqual(fam.state, "dropped")
        self.assertIn("residual has no signal", fam.reason)

    def test_the_residual_variant_regresses_out_the_matched_factor(self):
        from p2a.engine.refiner import residual_code
        self.assertEqual(residual_code("-rank(vec_avg(gap_x))", "-rank(returns)"),
                         "sig = -rank(vec_avg(gap_x)); sig - regression_proj(sig, -rank(returns))")
        # earlier statements are kept, and the residual's name never shadows one of them
        self.assertEqual(residual_code("sig = rank(a); b = ts_mean(sig, 5); rank(b)", "rank(returns)"),
                         "sig = rank(a); b = ts_mean(sig, 5); sig_ = rank(b); sig_ - regression_proj(sig_, rank(returns))")

    def test_value_prefers_unique_alphas(self):
        crowded = {"stats": {"sharpe": 2.0, "prod_corr": 0.69, "mult": 1.3}}
        unique = {"stats": {"sharpe": 1.7, "prod_corr": 0.35, "mult": 1.3}}
        self.assertGreater(value_score(unique), value_score(crowded))


if __name__ == "__main__":
    unittest.main()
