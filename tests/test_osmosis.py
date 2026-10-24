"""Osmosis plan: exclusions from the guide, the platform's minimum, and points that maximize the combo's Sharpe."""
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from p2a.config import Config
from p2a.engine import osmosis
from p2a.engine.pipeline import Engine

ROOT = Path(__file__).resolve().parents[1]


def cum(pnl):
    out, c = [], 0.0
    for d in sorted(pnl):
        c += pnl[d]
        out.append([d, c])
    return out


class WeightTests(unittest.TestCase):
    def test_weights_respect_bounds_and_prefer_the_diversifying_alpha(self):
        rnd = random.Random(3)
        a = [0.1 + rnd.gauss(0, 1) for _ in range(1500)]
        b = [x + rnd.gauss(0, 0.3) for x in a]          # a near copy of a
        c = [0.1 + rnd.gauss(0, 1) for _ in range(1500)]  # as good, independent
        w = osmosis.max_sharpe_weights([a, b, c], lo=0.05, hi=0.8)
        self.assertAlmostEqual(sum(w), 1.0, places=6)
        self.assertTrue(all(0.05 - 1e-9 <= x <= 0.8 + 1e-9 for x in w))
        self.assertGreater(w[2], w[1])
        self.assertGreater(w[2], 0.4)

    def test_points_add_up_exactly(self):
        pts = osmosis.to_points([0.123456, 0.2, 0.3, 0.376544], 100000)
        self.assertEqual(sum(pts), 100000)
        self.assertEqual(pts[1], 20000)
        pts = osmosis.to_points([1 / 3] * 3, 100000)
        self.assertEqual(sum(pts), 100000)
        self.assertTrue(all(p >= 33333 for p in pts))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        cfg["paths"] = {"data_dir": str(self.tmp / "data"), "prompts_dir": str(ROOT / "prompts")}
        cfg["osmosis"].update({"min_alphas": 4, "max_weight": 0.5, "min_weight": 0.05, "cost_bps": 0.0})
        (self.tmp / "config.yaml").write_text(yaml.safe_dump(cfg))
        self.cfg = Config.load(self.tmp / "config.yaml")
        self.eng = Engine(self.cfg, offline=True)
        self.eng.context = lambda scope, theme, route="power_pool": SimpleNamespace(
            cfg=self.cfg, store=self.eng.store, scope=scope)
        self.rnd = random.Random(11)
        self.days = [f"2019-{i:05d}" for i in range(800)]
        self.subs = []
        self._orig = osmosis.submitted_alphas
        osmosis.submitted_alphas = lambda ctx, max_age_s=None: self.subs

    def tearDown(self):
        osmosis.submitted_alphas = self._orig
        self.eng.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _series(self, drift=0.08, base=None, mix=0.0):
        return {d: drift + (mix * base[d] if base else 0.0) + (1 - mix) * self.rnd.gauss(0, 1) for d in self.days}

    def _sub(self, aid, region="EUR", sharpe=1.8, ic=None, turnover=0.1, pnl=None, points=None, fields=None):
        self.eng.store.kv_set(f"pnl:{aid}", cum(pnl if pnl is not None else self._series()))
        self.subs.append({"id": aid, "region": region, "delay": 1, "universe": "TOP2500", "fields": fields or [],
                          "classifications": [], "osmosis_points": points,
                          "stats": {"sharpe": sharpe, "ic_sharpe": ic, "turnover": turnover, "book": 2e7}})

    def test_guide_exclusions_and_the_platform_minimum(self):
        base = self._series()
        self._sub("GOOD1", pnl=base, sharpe=2.2, ic=2.0)
        self._sub("COPY", pnl={d: 0.95 * base[d] + 0.05 * self.rnd.gauss(0, 1) for d in self.days}, sharpe=2.0, ic=1.8)
        self._sub("GOOD2", sharpe=1.9, ic=1.7)
        self._sub("ILLIQ", sharpe=2.0, ic=0.5)                   # keeps 25% under investability constraints
        self._sub("FAST", sharpe=1.9, ic=1.0, turnover=0.35)     # 35% turnover and keeps 53%
        self._sub("FASTX", sharpe=1.7, ic=None, turnover=0.30)   # constrained Sharpe unknown: flagged, not excluded
        self._sub("GOOD3", sharpe=1.6, ic=1.5)
        self._sub("USA1", region="USA")
        res = osmosis.plan(self.eng)
        eur = next(s for s in res["scopes"] if s["scope"] == "EUR/D1")
        rows = {r["id"]: r for r in eur["rows"]}
        # the weaker of the near-identical pair goes (in-sample after-cost Sharpe decides which)
        dropped = [k for k in ("GOOD1", "COPY") if (rows[k]["excluded"] or "").startswith("corr")]
        self.assertEqual(len(dropped), 1)
        self.assertEqual(rows["ILLIQ"]["excluded"], "investability keeps 25%")
        self.assertIn("turnover 35%", rows["FAST"]["excluded"])
        self.assertIsNone(rows["FASTX"]["excluded"])
        self.assertIn("MaxTrade", rows["FASTX"]["note"])
        allocated = [r for r in eur["rows"] if r.get("points")]
        self.assertEqual(sum(r["points"] for r in allocated), 100000)
        self.assertGreaterEqual(len(allocated), 4)
        self.assertIsNotNone(eur["combo"]["proposed"])
        usa = next(s for s in res["scopes"] if s["scope"] == "USA/D1")
        self.assertEqual(usa["needed"], 3)          # 1 of the 4 alphas the test minimum asks for
        self.assertIsNone(usa["combo"])
        self.assertEqual(res["plannable"], 1)

    def test_excluded_alphas_fill_in_when_a_scope_would_fall_below_the_minimum(self):
        self._sub("A", sharpe=2.0, ic=1.8)
        self._sub("B", sharpe=1.9, ic=1.7)
        self._sub("C", sharpe=1.8, ic=1.6)
        self._sub("ILLIQ", sharpe=2.0, ic=0.4)
        eur = osmosis.plan(self.eng)["scopes"][0]
        rows = {r["id"]: r for r in eur["rows"]}
        self.assertTrue(rows["ILLIQ"]["note"].startswith("fill-in"))
        self.assertEqual(sum(1 for r in eur["rows"] if r.get("points")), 4)
        self.assertEqual(eur["needed"], 0)

    def test_current_allocation_is_read_and_judged(self):
        for k in range(4):
            self._sub(f"P{k}", points=25000)
        eur = osmosis.plan(self.eng)["scopes"][0]
        self.assertTrue(eur["valid_now"])
        self.assertIsNotNone(eur["combo"]["current"])


if __name__ == "__main__":
    unittest.main()
