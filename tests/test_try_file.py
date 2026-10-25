"""p2a try --file: entries naming their own scope, and {role} slots filled from the live catalog."""
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from p2a.cli import try_groups
from p2a.config import Config
from p2a.engine import Engine
from tests.helpers import load_operators

ROOT = Path(__file__).resolve().parent.parent
EUR = {"instrumentType": "EQUITY", "region": "EUR", "universe": "TOP2500", "delay": 1}


class TryFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        cfg["paths"] = {"data_dir": str(self.tmp / "data"), "prompts_dir": str(ROOT / "prompts")}
        cfg["mechanisms"]["library"] = str(ROOT / "research" / "mechanisms.yaml")
        (self.tmp / "config.yaml").write_text(yaml.safe_dump(cfg))
        self.eng = Engine(Config.load(self.tmp / "config.yaml"), offline=True)
        self.eng.store.upsert_operators(load_operators())
        self.eng.store.upsert_fields([
            {"id": f, "dataset": {"id": ds}, "category": {"id": cat}, "type": typ, "description": desc,
             "coverage": 0.95, "alphaCount": 3}
            for f, ds, cat, typ, desc in [
                ("cap", "pv1", "pv", "MATRIX", "Daily market capitalization (in millions)"),
                ("close", "pv1", "pv", "MATRIX", "Daily close price"),
                ("industry", "pv1", "pv", "GROUP", "Industry grouping"),
                ("fnd_ni", "fnd2", "fundamental", "MATRIX", "Net income attributable to shareholders"),
                ("fnd_ni_est", "anl9", "analyst", "MATRIX", "Net income - consensus estimate"),
                ("anl9_tp_mean", "anl9", "analyst", "MATRIX", "Mean analyst target price"),
                ("anl9_tp_std", "anl9", "analyst", "MATRIX", "Standard deviation of analyst target price")]], EUR)

    def tearDown(self):
        self.eng.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_role_slots_take_this_scopes_fields(self):
        raws = [
            {"id": "ep", "expression": "rank(ts_backfill({net_income}, 252) / {cap})", "rationale_data": "earnings yield"},
            {"id": "tp", "expression": "group_rank({target_price} / close, industry)",
             "roles": {"target_price": {"type": "MATRIX", "patterns": ["target price"], "exclude": ["standard deviation"]}}},
            {"id": "none", "expression": "rank({carbon})", "roles": {"carbon": {"patterns": ["co2 emission"]}}},
            {"id": "undefined", "expression": "rank({no_such_role})"}]
        ids = self.eng.try_candidates(EUR, None, raws, route="regular")
        rows = [self.eng.store.alpha(i) for i in ids]
        self.assertEqual([r["canonical"] for r in rows],
                         ["rank(ts_backfill(fnd_ni, 252) / cap)",          # the library role, not the estimate
                          "group_rank(anl9_tp_mean / close, industry)"])   # the entry's own role spec
        self.assertIn("earnings yield; fnd_ni (fnd2): Net income attributable", rows[0]["description"])
        self.assertEqual(len(self.eng.store.alphas()), 2)                 # unresolved entries are not stored

    def test_entries_are_grouped_by_the_scope_they_name(self):
        raws = [{"expression": "a", "region": "EUR", "universe": "TOP2500"}, {"expression": "b", "region": "GLB"},
                {"expression": "c"}, {"expression": "d", "region": "eur", "delay": 0}]
        args = SimpleNamespace(region=None, universe="TOP3000", delay=None)
        self.assertEqual({k: [r["expression"] for r in v] for k, v in try_groups(raws, args).items()},
                         {("EUR", "TOP2500", None): ["a"], ("GLB", None, None): ["b"],
                          (None, "TOP3000", None): ["c"], ("EUR", None, 0): ["d"]})
        # --region keeps that region's entries (and those without one), with the command line's universe
        args = SimpleNamespace(region="eur", universe="TOP1200", delay=1)
        self.assertEqual({k: [r["expression"] for r in v] for k, v in try_groups(raws, args).items()},
                         {("EUR", "TOP2500", 1): ["a"], ("EUR", "TOP1200", 1): ["c"], ("EUR", "TOP1200", 0): ["d"]})


if __name__ == "__main__":
    unittest.main()
