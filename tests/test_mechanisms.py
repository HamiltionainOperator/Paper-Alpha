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

    def _scope_ctx(self, region: str, universe: str, fields: list[tuple[str, str, str]]):
        scope = {**SCOPE, "region": region, "universe": universe}
        self.store.upsert_fields([{"id": fid, "dataset": {"id": ds}, "category": {"id": "fundamental"}, "type": "MATRIX",
                                   "description": desc, "coverage": 0.9, "alphaCount": 5} for fid, ds, desc in fields], scope)
        return SimpleNamespace(**{**vars(self.ctx), "scope": scope})

    def test_round15_roles_take_verified_ids_first_then_descriptions(self):
        chn = self._scope_ctx("CHN", "TOP2000U", [("net_income_total_5", "fundamental23", "Net income - total"),
                                                  ("ni_parent", "fundamental23", "Net income attributable to parent")])
        r = RoleResolver(chn, self.lib.roles)
        self.assertEqual([f["id"] for f in r.candidates("net_income")], ["net_income_total_5", "ni_parent"])
        ind = self._scope_ctx("IND", "TOP500", [
            ("fnd_ni_ttm", "fnd", "Net income attributable to shareholders, trailing twelve months"),
            ("fnd_ni_est", "fnd", "Net income - consensus estimate for the next fiscal year"),
            ("fnd_ni_growth", "fnd", "Net income growth, year over year"),
            ("fnd_npm", "fnd", "Net profit margin"),
            ("fnd_eps", "fnd", "Net income per share (basic)"),
            ("fnd_teq", "fnd", "Total shareholders' equity"),
            ("fnd_tle", "fnd", "Total liabilities and shareholders' equity"),
            ("fnd_roe", "fnd", "Return on equity"),
            ("fnd_eqiss", "fnd", "Equity issuance over the last year"),
            ("fnd_bvps", "fnd", "Book value per share")])
        r = RoleResolver(ind, self.lib.roles)
        self.assertEqual([f["id"] for f in r.candidates("net_income")], ["fnd_ni_ttm"])  # no estimates, growth, margins
        self.assertEqual([f["id"] for f in r.candidates("book_equity")], ["fnd_teq"])    # not assets, ROE, issuance

    def test_round15_mechanisms_run_only_where_the_research_found_them_and_once(self):
        from p2a.engine.lifecycle import family_key
        from p2a.fastexpr import Catalog, FieldInfo, Rules
        from tests.helpers import TYPE_OVERRIDES, load_operators
        pv = [("cap", "pv1", "Daily market capitalization (in millions)"), ("volume", "pv1", "Daily volume")]
        fund = [("net_income_total_5", "fundamental23", "Net income - total"),
                ("total_equity_5", "fundamental23", "Total equity")]
        chn = self._scope_ctx("CHN", "TOP2000U", pv + fund)
        usa = self._scope_ctx("USA", "TOP3000", pv + fund)
        self.store.kv_set("submitted_alphas", [])

        def builder(ctx):
            mb = MechanismBuilder.__new__(MechanismBuilder)
            mb.ctx, mb.lib, mb.resolver, mb.simulator = ctx, self.lib, RoleResolver(ctx, self.lib.roles), None
            mb.mcfg = {"per_step": 20, "per_mechanism": 1}
            return mb

        shapes = {p["shape"] for p in builder(chn).proposals()}
        self.assertTrue({"mech:ep_value", "mech:ep_value_ex_shells", "mech:abnormal_turnover",
                         "mech:profitability"} <= shapes)
        self.assertNotIn("mech:country_value_quality", shapes)   # ASI / IND / JPN only
        self.assertFalse(any(s in {"mech:ep_value", "mech:abnormal_turnover"} for s in
                             {p["shape"] for p in builder(usa).proposals()}))
        self.assertEqual([p["shape"] for p in builder(usa).proposals(only=["ep_value"])], ["mech:ep_value"])

        # a proposal's family is the family of the alpha it becomes: once queued, it is not proposed again
        ep = next(p for p in builder(chn).proposals() if p["shape"] == "mech:ep_value")
        cat = Catalog(load_operators(), Rules(type_overrides=TYPE_OVERRIDES),
                      [FieldInfo(id=f, type="MATRIX", dataset=d, description=t) for f, d, t in pv + fund])
        fields = analyze(ep["expression"], cat).counted_fields(set())
        self.store.add_alpha({"payload_hash": "ep1", "canonical": ep["expression"], "fields": fields,
                              "shape_class": "value_ep", "region": "CHN", "delay": 1, "universe": "TOP2000U",
                              "status": "valid", "settings": {}})
        self.assertNotIn("mech:ep_value", {p["shape"] for p in builder(chn).proposals()})
        self.assertEqual(family_key(fields, "value_ep"), family_key({"net_income_total_5", "cap"}, "value_ep"))


if __name__ == "__main__":
    unittest.main()
