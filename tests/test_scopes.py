"""Alphas in other regions: each region's own universe, and reference factors of the alpha's own region."""
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from p2a.config import Config
from p2a.engine import references as refs
from p2a.engine.pipeline import Engine

ROOT = Path(__file__).resolve().parents[1]

UNIVERSES = {"type": "choice", "choices": {"instrumentType": {"EQUITY": {"region": {
    "USA": [{"value": "TOP3000"}, {"value": "TOP1000"}], "CHN": [{"value": "TOP2000U"}],
    "DEU": [{"value": "TOP500"}]}}}}}


def cum(pnl):
    out, c = [], 0.0
    for d in sorted(pnl):
        c += pnl[d]
        out.append([d, c])
    return out


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        cfg["paths"] = {"data_dir": str(self.tmp / "data"), "prompts_dir": str(ROOT / "prompts")}
        cfg["uniqueness"]["references"] = [{"id": "reversal_5d", "expression": "-rank(ts_sum(returns, 5))"}]
        (self.tmp / "config.yaml").write_text(yaml.safe_dump(cfg))
        self.cfg = Config.load(self.tmp / "config.yaml")
        self.eng = Engine(self.cfg, offline=True)
        self.eng.store.kv_set("settings_options", {"universe": UNIVERSES})
        # the context only needs config, store and scope here (no catalog)
        self.eng.context = lambda scope, theme, route="power_pool": SimpleNamespace(
            cfg=self.cfg, store=self.eng.store, scope=scope)

    def tearDown(self):
        self.eng.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_another_region_without_a_universe_gets_one_that_exists_there(self):
        self.assertEqual(self.eng.scope("CHN")["universe"], "TOP2000U")
        self.assertEqual(self.eng.scope("DEU")["universe"], "TOP500")
        self.assertEqual(self.eng.scope("USA")["universe"], "TOP3000")
        self.assertEqual(self.eng.scope("USA", "TOP1000")["universe"], "TOP1000")
        self.assertEqual(self.eng.scope()["universe"], "TOP3000")

    def _alpha(self, region, universe, brain_id, pnl):
        self.eng.store.kv_set(f"pnl:{brain_id}", cum(pnl))
        return self.eng.store.add_alpha({
            "payload_hash": brain_id, "canonical": "rank(x)", "expression": "rank(x)", "status": "simulated",
            "brain_id": brain_id, "region": region, "universe": universe, "delay": 1,
            "settings": {"region": region, "universe": universe, "delay": 1}, "stats": {"sharpe": 2.0}})

    def test_each_alpha_is_screened_against_the_references_of_its_own_region(self):
        rnd = random.Random(3)
        days = [f"2018-{i:05d}" for i in range(800)]
        usa_rev = {d: rnd.gauss(0, 1) for d in days}
        chn_rev = {d: rnd.gauss(0, 1) for d in days}
        for region, universe, p in (("USA", "TOP3000", usa_rev), ("CHN", "TOP2000U", chn_rev)):
            self.eng.store.kv_set(f"pnl:R_{region}", cum(p))
            self.eng.store.kv_set(f"reference:{region}:1:{universe}:reversal_5d",
                                  {"brain_id": f"R_{region}", "expression": "-rank(ts_sum(returns, 5))"})
        chn = self._alpha("CHN", "TOP2000U", "C1", {d: 0.9 * chn_rev[d] + 0.3 * rnd.gauss(0, 1) for d in days})
        usa = self._alpha("USA", "TOP3000", "U1", {d: rnd.gauss(0, 1) for d in days})
        out = {r["id"]: r for r in self.eng.references(ids=[chn, usa])}
        self.assertGreater(out[chn]["ref_corr"], 0.9)  # a Chinese reversal in disguise is caught by China's reference
        self.assertLess(abs(out[usa]["ref_corr"]), 0.15)
        # a run in one region measures only that region's alphas
        self.eng.store.update_alpha(chn, stats={"sharpe": 2.0})
        self.eng.store.update_alpha(usa, stats={"sharpe": 2.0})
        self.assertEqual(self.eng.exposures(self.eng.scope("DEU")), 0)
        self.assertEqual(self.eng.exposures(self.eng.scope("CHN")), 1)

    def test_a_reference_the_region_cannot_simulate_is_not_simulated_again(self):
        ctx = SimpleNamespace(cfg=self.cfg, store=self.eng.store, scope=self.eng.scope("CHN"))
        calls = []

        def run(jobs, on_done=None):
            calls.append(len(jobs))
            for j in jobs:
                j.status, j.message = "error", "unknown variable 'equity'"
        sim = SimpleNamespace(run=run)
        build = lambda overrides: ({}, [])
        refs.ensure(ctx, sim, build)
        refs.ensure(ctx, sim, build)
        self.assertEqual(calls, [1])
        # the same reference with a new expression is tried again
        self.cfg.data["uniqueness"]["references"] = [{"id": "reversal_5d", "expression": "-rank(ts_sum(returns, 3))"}]
        refs.ensure(ctx, sim, build)
        self.assertEqual(calls, [1, 1])


if __name__ == "__main__":
    unittest.main()
