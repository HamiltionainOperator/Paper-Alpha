"""The idea lifecycle: when to keep refining a signal family and when to drop it."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from p2a.config import Config
from p2a.engine.lifecycle import Lifecycle, code_identifiers, family_key, pnl_correlation
from p2a.store import Store

SCOPE = {"instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000", "delay": 1}


def check(name, result, value=None, limit=None):
    return {"name": name, "result": result, "value": value, "limit": limit}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite")
        self.cfg = Config.load(None)
        self.ctx = SimpleNamespace(cfg=self.cfg, store=self.store, scope=SCOPE, pp=self.cfg.section("power_pool"),
                                   sync=SimpleNamespace(client=None), catalog=None, constraints=None)
        self.n = 0

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def add(self, fields, sharpe, turnover=0.2, status="near_miss", checks=None, canonical=None, parent=None,
            settings=None, origin="llm", rationale="", operators=("rank",)):
        self.n += 1
        aid = self.store.add_alpha({
            "payload_hash": f"h{self.n}", "canonical": canonical or f"rank({'+'.join(fields)})", "expression": "x",
            "settings": settings or {"decay": 4, "neutralization": "INDUSTRY", "universe": "TOP3000"},
            "parent_id": parent, "origin": origin, "region": "USA", "delay": 1, "universe": "TOP3000",
            "fields": fields, "operators": list(operators), "status": "valid", "rationale": rationale})
        self.store.update_alpha(aid, status="simulated", pp_status=status, brain_id=f"B{self.n}",
                                stats={"sharpe": sharpe, "turnover": turnover}, checks=checks or [], pp_reasons=[])
        return aid

    def lc(self, submitted=None):
        return Lifecycle(self.ctx, submitted=submitted or [])

    def test_weak_signal_is_dropped_after_one_probe(self):
        self.add(["a_f"], 0.3, status="fail")
        fam = self.lc().families()[family_key(["a_f"], "level")]
        self.assertEqual(fam.state, "dropped")
        self.assertIn("weak signal", fam.reason)

    def test_strong_negative_gets_one_flip_then_drops(self):
        aid = self.add(["b_f"], -0.9, status="near_miss")
        fam = self.lc().families()[family_key(["b_f"], "level")]
        self.assertEqual((fam.state, fam.remedies), ("promising", ["flip"]))
        self.add(["b_f"], 0.2, status="fail", parent=aid, origin="refine:flip", canonical="-rank(b_f)")
        fam = self.lc().families()[family_key(["b_f"], "level")]
        self.assertEqual(fam.state, "dropped")

    def test_winner_stops_spending(self):
        self.add(["c_f"], 1.3, status="eligible")
        self.add(["c_f"], 1.1, status="near_miss", canonical="zscore(c_f)")
        fam = self.lc().families()[family_key(["c_f"], "level")]
        self.assertEqual(fam.state, "winner")

    def test_illiquid_effect_is_dropped(self):
        self.add(["d_f"], 1.6, checks=[check("LOW_SUB_UNIVERSE_SHARPE", "FAIL", 0.2, 0.7)])
        fam = self.lc().families()[family_key(["d_f"], "level")]
        self.assertEqual(fam.state, "dropped")
        self.assertIn("illiquid", fam.reason)

    def test_near_miss_sub_universe_is_promising_but_not_a_universe_sweep(self):
        self.add(["e_f"], 1.6, checks=[check("LOW_SUB_UNIVERSE_SHARPE", "FAIL", 0.69, 0.72)])
        fam = self.lc().families()[family_key(["e_f"], "level")]
        self.assertEqual(fam.state, "promising")
        # the liquid names alone are below the Sharpe floor, so simulating in TOP1000 would not help
        self.assertNotIn("liquid_universe", fam.remedies)
        self.assertIn("expression", fam.remedies)

    def test_settings_variant_budget(self):
        self.add(["f_f"], 0.9, turnover=0.8, canonical="rank(f_f)")
        fam = self.lc().families()[family_key(["f_f"], "level")]
        self.assertIn("decay_up", fam.remedies)
        self.add(["f_f"], 0.95, turnover=0.75, canonical="rank(f_f)", settings={"decay": 12})
        fam = self.lc().families()[family_key(["f_f"], "level")]
        self.assertNotIn("decay_up", fam.remedies)  # one settings-only child per expression

    def test_plateau_closes_the_family(self):
        root = self.add(["g_f"], 0.9)
        self.add(["g_f"], 0.88, parent=root, canonical="rank(ts_mean(g_f, 5))")
        self.add(["g_f"], 0.7, parent=root, canonical="rank(ts_zscore(g_f, 10))")
        fam = self.lc().families()[family_key(["g_f"], "level")]
        self.assertEqual(fam.state, "dropped")
        self.assertIn("plateau", fam.reason)

    def test_crowded_signal_is_dropped(self):
        self.add(["h_f"], 1.2, checks=[check("PROD_CORRELATION", "WARNING", 0.97, 0.7)], status="near_miss")
        fam = self.lc().families()[family_key(["h_f"], "level")]
        self.assertEqual(fam.state, "dropped")
        self.assertIn("crowded", fam.reason)

    def test_submitted_fields_are_used(self):
        self.add(["i_f"], 1.4, status="eligible")
        subs = [{"id": "S1", "fields": ["i_f"], "region": "USA", "delay": 1, "classifications": []}]
        fam = self.lc(subs).families()[family_key(["i_f"], "level")]
        self.assertEqual(fam.state, "used")
        other_region = [{"id": "S2", "fields": ["i_f"], "region": "EUR", "delay": 1, "classifications": []}]
        self.assertEqual(self.lc(other_region).families()[family_key(["i_f"], "level")].state, "winner")

    def test_family_budget(self):
        for k in range(5):
            self.add(["j_f"], 0.8 + k * 0.001, canonical=f"rank(ts_mean(j_f, {k + 2}))")
        fam = self.lc().families()[family_key(["j_f"], "level")]
        self.assertEqual(fam.state, "dropped")
        self.assertIn("budget", fam.reason)

    def test_shapes_on_the_same_field_are_separate_ideas(self):
        self.add(["k_f"], 0.3, status="fail")
        self.add(["k_f"], 1.2, status="eligible", canonical="rank(ts_delta(k_f, 21))", operators=("rank", "ts_delta"))
        fams = self.lc().families()
        self.assertEqual(fams[family_key(["k_f"], "level")].state, "dropped")    # weak as a level...
        self.assertEqual(fams[family_key(["k_f"], "change")].state, "winner")    # ...but its revisions work
        subs = [{"id": "S", "fields": ["k_f"], "code": "rank(ts_delta(k_f, 21))", "region": "USA", "delay": 1,
                 "classifications": []}]
        fams = self.lc(subs).families()
        self.assertEqual(fams[family_key(["k_f"], "change")].state, "used")
        self.assertNotEqual(fams[family_key(["k_f"], "level")].state, "used")

    def test_identifiers_and_correlation(self):
        self.assertEqual(code_identifiers("a = rank(x_y); group_rank(a, industry) - z_w"), {"x_y", "industry", "z_w"})
        a = {f"d{i}": float(i % 7) for i in range(200)}
        b = {k: 2 * v + 1 for k, v in a.items()}
        c = {k: -v for k, v in a.items()}
        self.assertAlmostEqual(pnl_correlation(a, b, 1000), 1.0, places=6)
        self.assertAlmostEqual(pnl_correlation(a, c, 1000), -1.0, places=6)
        self.assertIsNone(pnl_correlation(a, {}, 1000))


if __name__ == "__main__":
    unittest.main()
