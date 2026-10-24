"""Research mechanisms: roles filled from the live catalog, templates in live operators."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from p2a.config import Config
from p2a.engine.mechanisms import MechanismBuilder, MechanismLibrary, RoleResolver
from p2a.fastexpr import analyze
from p2a.store import Store
from tests.helpers import make_catalog

SCOPE = {"instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000", "delay": 1}


class MechanismTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite")
        self.cfg = Config.load(None)
        self.store.upsert_fields([
            {"id": "barra_x_top3000_specific_return", "dataset": {"id": "pv20"}, "category": {"id": "pv"}, "type": "MATRIX",
             "description": "Specific return component for securities in the top 3000 universe", "coverage": 0.96, "alphaCount": 27},
            {"id": "specific_return_top500", "dataset": {"id": "pv20"}, "category": {"id": "pv"}, "type": "MATRIX",
             "description": "Specific return for the top 500", "coverage": 0.95, "alphaCount": 0},
            {"id": "news_tone_fast_d1", "dataset": {"id": "news7"}, "category": {"id": "news"}, "type": "MATRIX",
             "description": "Sentiment or tone score of news headlines over time", "coverage": 0.92, "alphaCount": 0},
            {"id": "news_tone", "dataset": {"id": "news7"}, "category": {"id": "news"}, "type": "MATRIX",
             "description": "Sentiment or tone score of news headlines over time", "coverage": 0.92, "alphaCount": 40},
            {"id": "story_vec", "dataset": {"id": "news46"}, "category": {"id": "news"}, "type": "VECTOR",
             "description": "Story count", "coverage": 1.0, "alphaCount": 3},
            {"id": "sta1_top3000c50", "dataset": {"id": "pv29"}, "category": {"id": "pv"}, "type": "GROUP",
             "description": "Statistical industry classification", "coverage": 0.99, "alphaCount": 1791},
            {"id": "sta1_top1000c50", "dataset": {"id": "pv29"}, "category": {"id": "pv"}, "type": "GROUP",
             "description": "Statistical industry classification", "coverage": 0.35, "alphaCount": 900},
        ], SCOPE)
        self.ctx = SimpleNamespace(cfg=self.cfg, store=self.store, scope=SCOPE, sync=SimpleNamespace(client=None),
                                   catalog=None, constraints=None, route="regular", pp=self.cfg.section("power_pool"))
        self.lib = MechanismLibrary.load(self.cfg)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_roles_follow_descriptions_coverage_and_universe(self):
        r = RoleResolver(self.ctx, self.lib.roles)
        self.assertEqual(r.candidates("residual_return")[0]["id"], "barra_x_top3000_specific_return")  # top500 excluded
        self.assertEqual([f["id"] for f in r.candidates("tone_fast")], ["news_tone_fast_d1"])        # only the fast field
        self.assertEqual([f["id"] for f in r.candidates("stat_group")], ["sta1_top3000c50"])         # this universe's clusters
        self.assertEqual(r.expr("news_count", r.candidates("news_count")[0]), "vec_count(story_vec)")

    def test_templates_fill_with_counterparts_and_parse(self):
        mb = MechanismBuilder.__new__(MechanismBuilder)
        mb.ctx, mb.lib, mb.resolver = self.ctx, self.lib, RoleResolver(self.ctx, self.lib.roles)
        change = mb.fill(self.lib.get("overnight_tone_change"), 1)
        self.assertEqual(change[0]["expr"], "rank(news_tone_fast_d1 - news_tone)")
        cat = make_catalog()
        import re
        for m in self.lib.mechanisms + self.lib.enhancers:
            code = m.template.replace("{stat_group}", "sector")
            code = re.sub(r"\{[a-z0-9_]+\}", "close", code)  # every role slot -> a live matrix field
            self.assertNotIn("{", code, m.id)
            self.assertIsNotNone(analyze(code, cat).program, f"{m.id}: {code}")
        self.assertTrue(all(m.sources for m in self.lib.mechanisms + self.lib.enhancers), "every mechanism cites research")


if __name__ == "__main__":
    unittest.main()
