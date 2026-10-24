import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from p2a.config import Config
from p2a.engine import references as refs
from p2a.store import Store

SCOPE = {"instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000", "delay": 1}


def cum(pnl):
    out, c = [], 0.0
    for d in sorted(pnl):
        c += pnl[d]
        out.append([d, c])
    return out


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite")
        cfg = Config.load(None)
        cfg.data["uniqueness"] = {"reference_limit": 0.5, "references": [
            {"id": "reversal_5d", "expression": "-rank(ts_sum(returns, 5))"},
            {"id": "size", "expression": "-rank(log(cap))"}]}
        self.ctx = SimpleNamespace(cfg=cfg, store=self.store, scope=SCOPE)
        rnd = random.Random(1)
        self.days = [f"2016-{i:05d}" for i in range(1200)]
        self.rev = {d: rnd.gauss(0, 1) for d in self.days}
        self.size = {d: rnd.gauss(0, 1) for d in self.days}
        for rid, p in (("reversal_5d", self.rev), ("size", self.size)):
            self.store.kv_set(f"pnl:R_{rid}", cum(p))
            self.store.kv_set(f"reference:USA:1:TOP3000:{rid}", {"brain_id": f"R_{rid}", "expression": "x"})

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_a_disguised_reversal_is_caught_and_a_new_idea_is_not(self):
        rnd = random.Random(2)
        disguised = {d: 0.8 * self.rev[d] + 0.6 * rnd.gauss(0, 1) for d in self.days}  # mostly the reversal factor
        new_idea = {d: rnd.gauss(0, 1) for d in self.days}
        v, name = refs.exposure(self.ctx, None, disguised)
        self.assertEqual(name, "reversal_5d")
        self.assertGreater(abs(v), refs.limit(self.ctx.cfg))
        v2, _ = refs.exposure(self.ctx, None, new_idea)
        self.assertLess(abs(v2), 0.15)

    def test_a_negative_exposure_counts_by_its_size(self):
        anti = {d: -self.size[d] for d in self.days}
        v, name = refs.exposure(self.ctx, None, anti)
        self.assertEqual(name, "size")
        self.assertAlmostEqual(v, -1.0, places=3)

    def test_the_tilts_worth_removing_are_the_large_ones_largest_first(self):
        st = {"ref_exposures": {"value": 0.31, "momentum_12_1": -0.24, "size": -0.02, "eps_revision": 0.01}}
        self.assertEqual(refs.tilts(st, self.ctx.cfg), ["value", "momentum_12_1"])
        self.assertEqual(refs.tilts({"ref_exposures": {"size": 0.1}}, self.ctx.cfg), [])
        from p2a.engine.refiner import residual_code
        code = residual_code(residual_code("add(rank(a) - 0.5, rank(b) - 0.5, filter=true)", "rank(v)"), "rank(m)")
        self.assertEqual(code, "sig = add(rank(a) - 0.5, rank(b) - 0.5, filter=true); "
                               "sig_ = sig - regression_proj(sig, rank(v)); sig_ - regression_proj(sig_, rank(m))")

    def test_references_already_simulated_are_not_simulated_again(self):
        called = []
        sim = SimpleNamespace(run=lambda jobs, on_done=None: called.append(jobs))
        self.store.kv_set("reference:USA:1:TOP3000:reversal_5d",
                          {"brain_id": "R_reversal_5d", "expression": "-rank(ts_sum(returns, 5))"})
        self.store.kv_set("reference:USA:1:TOP3000:size", {"brain_id": "R_size", "expression": "-rank(log(cap))"})
        self.assertEqual(refs.ensure(self.ctx, sim, lambda raw: ({}, [])), 0)
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
