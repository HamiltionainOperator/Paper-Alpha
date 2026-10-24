"""The shape library: research templates validated against the live operator catalog."""
import unittest
from types import SimpleNamespace

from p2a.config import Config
from p2a.engine.shapes import ShapeLibrary, similar_partner, template_operators, thompson_order
from p2a.fastexpr import analyze
from tests.helpers import make_catalog


class ShapeLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.load(None)
        cls.lib = ShapeLibrary.load(cls.cfg)

    def test_library_loads_with_sources(self):
        ids = {s.id for s in self.lib.shapes}
        for needed in ("level", "change", "history_relative", "fresh_update", "spread", "orthogonal", "combo"):
            self.assertIn(needed, ids)
        self.assertTrue(all(s.sources for s in self.lib.shapes), "every shape cites where it comes from")

    def test_shapes_missing_operators_are_disabled(self):
        catalog = SimpleNamespace(op=lambda name: name in {"rank", "ts_delta"})
        lib = ShapeLibrary(self.lib.data, catalog)
        self.assertTrue(lib.get("level").available)
        self.assertTrue(lib.get("change").available)
        self.assertFalse(lib.get("orthogonal").available)          # no vector_neut on this account
        self.assertIn("vector_neut", lib.get("orthogonal").missing_ops)
        self.assertEqual(template_operators("trade_when(days_from_last_change({x}) <= {k}, rank({x}), -1)"),
                         {"trade_when", "days_from_last_change", "rank"})

    def test_kinds_speeds_and_classes(self):
        k = self.lib.kind_of
        self.assertEqual(k({"id": "short_term_return_pred_r20_q1", "description": "Short-term return prediction"}), "forecast")
        self.assertEqual(k({"id": "anl4_qfv4_eps_mean", "description": "mean"}), "analyst_estimate")   # eps in the id
        self.assertEqual(k({"id": "atm_put_option_implied_volatility", "description": "Implied volatility for the ATM put"}),
                         "implied")
        self.assertEqual(self.lib.speed_of(0.5), "fast")
        self.assertEqual(self.lib.speed_of(0.1), "medium")
        self.assertEqual(self.lib.speed_of(0.01), "slow")
        self.assertEqual(self.lib.class_of(["rank"]), "level")
        self.assertEqual(self.lib.class_of(["rank", "ts_zscore"]), "change")
        self.assertEqual(self.lib.class_of(["trade_when", "rank", "ts_delta"]), "event")
        self.assertEqual(self.lib.class_of(["vector_neut", "rank"]), "residual")

    def test_instantiation_is_valid_fast_expression(self):
        catalog = make_catalog()
        x = {"id": "close", "type": "MATRIX"}
        y = {"id": "open", "type": "MATRIX"}
        for sid in ("change", "history_relative", "trend", "fresh_update", "spread", "zspread", "ts_residual", "combo"):
            sh = self.lib.get(sid)
            expr = self.lib.instantiate(sh, x, y if sh.fields == 2 else None, "medium")
            self.assertIsNotNone(expr, sid)
            an = analyze(expr, catalog)
            self.assertIsNotNone(an.program, f"{sid}: {expr}")
        self.assertIsNone(self.lib.instantiate(self.lib.get("spread"), x, None, "medium"))  # needs a partner
        self.assertEqual(self.lib.instantiate(self.lib.get("change"), x, None, "slow"), "rank(ts_delta(close, 63))")

    def test_vector_shapes_need_vector_fields(self):
        vec = {"id": "nws18_ssc", "type": "VECTOR", "description": "story sentiment score"}
        mat = {"id": "mean_composite_sentiment_score", "type": "MATRIX", "description": "average sentiment score"}
        self.assertIn("news_day", [s.id for s in self.lib.for_field(vec)])
        self.assertNotIn("news_day", [s.id for s in self.lib.for_field(mat)])
        self.assertEqual(self.lib.instantiate(self.lib.get("news_day"), vec),
                         "trade_when(vec_count(nws18_ssc) > 0, rank(vec_avg(nws18_ssc)), -1)")

    def test_counterparts_and_learning_order(self):
        x = {"id": "atm_call_option_implied_volatility", "dataset": "o", "description": "Implied volatility of the ATM call option"}
        cands = [x, {"id": "atm_put_option_implied_volatility", "dataset": "o", "description": "Implied volatility of the ATM put option"},
                 {"id": "atm_call_option_implied_volatility_confidence", "dataset": "o",
                  "description": "Confidence of the implied volatility of the ATM call option"},
                 {"id": "other_put", "dataset": "elsewhere", "description": "Implied volatility of the ATM put option"}]
        self.assertEqual(similar_partner(self.lib, x, cands)["id"], "atm_put_option_implied_volatility")
        shapes = [self.lib.get("change"), self.lib.get("trend")]   # classes "change" and "trend"
        firsts = [thompson_order(shapes, {("change", "analyst_estimate"): {"n": 30, "wins": 0}}, "analyst_estimate",
                                 seed=s)[0].id for s in range(20)]
        self.assertGreater(firsts.count("trend"), 15)  # a class that keeps failing on this kind of data goes last


if __name__ == "__main__":
    unittest.main()
