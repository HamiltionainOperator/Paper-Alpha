"""Signal inventory: which simulated parts of a scope can still feed a production alpha."""
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from p2a.config import Config
from p2a.engine import inventory
from p2a.engine.pipeline import Engine

ROOT = Path(__file__).resolve().parents[1]
EUR = {"instrumentType": "EQUITY", "region": "EUR", "universe": "TOP2500", "delay": 1}


def cum(pnl):
    out, c = [], 0.0
    for d in sorted(pnl):
        c += pnl[d]
        out.append([d, c])
    return out


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        cfg["paths"] = {"data_dir": str(self.tmp / "data"), "prompts_dir": str(ROOT / "prompts")}
        cfg["uniqueness"]["references"] = [{"id": "reversal_5d", "expression": "-rank(ts_sum(returns, 5))"}]
        (self.tmp / "config.yaml").write_text(yaml.safe_dump(cfg))
        self.cfg = Config.load(self.tmp / "config.yaml")
        self.eng = Engine(self.cfg, offline=True)
        self.eng.context = lambda scope, theme, route="power_pool": SimpleNamespace(
            cfg=self.cfg, store=self.eng.store, scope=scope)
        self.rnd = random.Random(7)
        self.days = [f"2019-{i:05d}" for i in range(900)]
        self.rev = self._series()
        self.sub = self._series()
        self.eng.store.kv_set("pnl:R_rev", cum(self.rev))
        self.eng.store.kv_set("reference:EUR:1:TOP2500:reversal_5d",
                              {"brain_id": "R_rev", "expression": "-rank(ts_sum(returns, 5))"})
        self.eng.store.kv_set("pnl:SUB1", cum(self.sub))
        self._orig = inventory.submitted_alphas
        inventory.submitted_alphas = lambda ctx: [{"id": "SUB1", "region": "EUR", "delay": 1, "universe": "TOP2500",
                                                   "fields": ["oth553_recvalue", "returns"]}]

    def tearDown(self):
        inventory.submitted_alphas = self._orig
        self.eng.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _series(self):
        return {d: self.rnd.gauss(0, 1) for d in self.days}

    def _alpha(self, bid, fields, sharpe, pnl, sub=None, region="EUR"):
        self.eng.store.kv_set(f"pnl:{bid}", cum(pnl))
        checks = [{"name": "LOW_SUB_UNIVERSE_SHARPE", "value": sub}] if sub is not None else []
        return self.eng.store.add_alpha({
            "payload_hash": bid, "canonical": f"rank({fields[0]})", "expression": f"rank({fields[0]})",
            "status": "simulated", "brain_id": bid, "region": region, "universe": "TOP2500", "delay": 1,
            "settings": {"region": region, "universe": "TOP2500", "delay": 1}, "fields": fields,
            "stats": {"sharpe": sharpe}, "checks": checks})

    def test_each_part_gets_the_verdict_that_decides_whether_it_can_feed_a_new_alpha(self):
        mix = lambda base, w: {d: w * base[d] + (1 - w) * self.rnd.gauss(0, 1) for d in self.days}
        ids = {
            "used_fields": self._alpha("A1", ["oth553_recvalue", "oth553_prerecvalue"], 1.8, self._series(), 1.2),
            "used_corr": self._alpha("A2", ["fieldx"], 1.5, mix(self.sub, 0.85), 1.0),
            "crowded": self._alpha("A3", ["fieldy"], 1.4, mix(self.rev, 0.9), 1.0),
            "illiquid": self._alpha("A4", ["fieldz"], 1.5, self._series(), 0.1),
            "weak": self._alpha("A5", ["fieldw"], 0.6, self._series(), 0.5),
            "available": self._alpha("A6", ["fieldv", "returns"], -1.4, self._series(), -1.0),
        }
        composite = self._alpha("A7", ["f1", "f2", "f3", "f4", "f5"], 2.2, self._series(), 1.5)
        elsewhere = self._alpha("A8", ["fieldu"], 1.6, self._series(), 1.0, region="USA")
        rows = {r["id"]: r for r in inventory.build(self.eng, EUR)}
        for label, aid in ids.items():
            self.assertEqual(rows[aid]["verdict"], label.split("_")[0], label)
        self.assertNotIn(composite, rows)  # five non-generic fields: a composite, not a part
        self.assertNotIn(elsewhere, rows)
        self.assertEqual(rows[ids["used_fields"]]["shared_fields"], ["oth553_recvalue"])
        self.assertEqual(rows[ids["available"]]["sub_ratio"], 0.71)  # a negative part keeps its ratio
        self.assertEqual(rows[ids["available"]]["fields"], ["fieldv"])  # generic fields are not counted
        self.assertEqual(next(iter(rows)), ids["available"])  # strongest available part first
        # measurements that never change are cached; the use test is redone when submissions change
        self.assertIsNotNone(self.eng.store.kv_get(f"inventory:EUR:1:TOP2500:{ids['used_corr']}"))
        inventory.submitted_alphas = lambda ctx: []
        rows = {r["id"]: r for r in inventory.build(self.eng, EUR)}
        self.assertEqual(rows[ids["used_corr"]]["verdict"], "available")


if __name__ == "__main__":
    unittest.main()
