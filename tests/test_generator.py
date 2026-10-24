"""Generator checks that need a context: settings fitting and description completion."""
import json
import tempfile
import unittest
from pathlib import Path

from p2a.config import Config
from p2a.engine.context import Context
from p2a.engine.generator import Generator
from p2a.engine.memory import Memory
from p2a.engine.themes import constraints_for
from p2a.store import Store
from tests.helpers import FIXTURES, TYPE_OVERRIDES, make_catalog

PP = {"max_operators": 8, "excluded_operators": ["ts_backfill"], "max_unique_fields": 3,
      "grouping_fields": ["industry", "subindustry", "sector", "market"]}


class GeneratorChecks(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        root = Path(__file__).resolve().parent.parent
        cfg = Config({"paths": {"prompts_dir": str(root / "prompts")}, "power_pool": PP,
                      "default_settings": {"decay": 4, "neutralization": "SUBINDUSTRY", "truncation": 0.08}}, tmp)
        store = Store(tmp / "db.sqlite")
        cat = make_catalog()
        options = json.loads((FIXTURES / "settings_options.json").read_text())
        self.gen = Generator(Context(cfg=cfg, store=store, llm=None, sync=None, memory=Memory(store, cfg),
                                     rules=cat.rules, scope={"instrumentType": "EQUITY", "region": "USA",
                                                             "universe": "TOP3000", "delay": 1},
                                     theme=None, constraints=constraints_for(None, PP), catalog=cat, options=options))

    def test_industry_level_signal_gets_coarser_neutralization(self):
        c = self.gen.check({"expression": "s = group_mean(mdl26_avrevsn_fq1_earnings_30, 1, industry); rank(ts_mean(s, 63))",
                            "neutralization": "SUBINDUSTRY", "idea": "industry revisions drift",
                            "rationale_data": "x", "rationale_operators": "y"})
        self.assertTrue(c.ok, c.analysis.report())
        self.assertEqual(c.settings["neutralization"], "SECTOR")
        self.assertTrue(any("constant within each industry" in n for n in c.notes))

    def test_stock_level_signal_keeps_settings(self):
        c = self.gen.check({"expression": "rank(ts_mean(mdl26_avrevsn_fq1_earnings_30, 21))", "neutralization": "industry",
                            "idea": "i", "rationale_data": "", "rationale_operators": ""})
        self.assertEqual(c.settings["neutralization"], "INDUSTRY")
        self.assertIn("mdl26_avrevsn_fq1_earnings_30", c.description)  # data rationale names the field
        self.assertIn("ts_mean():", c.description)                      # operator rationale completed from catalog


if __name__ == "__main__":
    unittest.main()
