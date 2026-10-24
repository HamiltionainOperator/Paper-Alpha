"""Exploration picks untried fields from valuable, uncrowded datasets, using only catalog metadata."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from p2a.config import Config
from p2a.engine.explorer import Explorer
from p2a.llm import LLMError
from p2a.store import Store

SCOPE = {"instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000", "delay": 1}


class _NoLLM:
    def chat_json(self, *a, **k):
        raise LLMError("offline")


class _Gen:
    def check(self, raw, origin="llm", parent_id=None):
        return SimpleNamespace(raw=raw, origin=origin, expression=raw["expression"])


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.sqlite")
        cfg = Config.load(None)
        ds = [
            {"id": "crowded_ds", "name": "Crowded", "category": {"id": "model"}, "coverage": 0.9, "valueScore": 1,
             "alphaCount": 90000},
            {"id": "gem_ds", "name": "Gem", "category": {"id": "model"}, "coverage": 0.95, "valueScore": 5,
             "alphaCount": 40},
            {"id": "news_ds", "name": "Other category", "category": {"id": "news"}, "coverage": 0.95, "valueScore": 6,
             "alphaCount": 10},
        ]
        self.store.upsert_datasets(ds, SCOPE)

        def fld(fid, dsid, desc, typ="MATRIX", cov=0.95, n=0, cat="model"):
            return {"id": fid, "dataset": {"id": dsid}, "category": {"id": cat}, "type": typ, "coverage": cov,
                    "description": desc, "alphaCount": n}
        fields = [
            fld("gem_pred_5d", "gem_ds", "Predicted 5-day forward return"),
            fld("gem_score_vec", "gem_ds", "Model score per analyst", typ="VECTOR"),
            fld("gem_mcap", "gem_ds", "Market capitalization in USD"),           # avoided: size, not a signal
            fld("gem_date", "gem_ds", "Forecast date of the score"),             # avoided: a date
            fld("gem_sparse_pred", "gem_ds", "Predicted return", cov=0.3),     # too sparse
            fld("crowded_pred", "crowded_ds", "Predicted return", n=5000),
            fld("news_pred", "news_ds", "Predicted return", cat="news"),
        ]
        self.store.upsert_fields(fields, SCOPE)
        for d in ("gem_ds", "crowded_ds", "news_ds"):
            self.store.mark_dataset_synced(d, SCOPE, 1)
        ops = {"rank", "vec_avg"}
        catalog = SimpleNamespace(op=lambda name: name in ops)
        constraints = SimpleNamespace(allowed_categories={"model"}, allowed_datasets=None)
        sync = SimpleNamespace(ensure_fields=lambda *a, **k: 0, client=None)
        self.ctx = SimpleNamespace(cfg=cfg, store=self.store, scope=SCOPE, pp=cfg.section("power_pool"), sync=sync,
                                   catalog=catalog, constraints=constraints, llm=_NoLLM())

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_picks_valuable_datasets_and_signal_fields(self):
        ex = Explorer(self.ctx, _Gen())
        order = [d["id"] for d in ex.datasets({})]
        self.assertEqual(order[0], "gem_ds")             # high value score, few alphas
        self.assertNotIn("news_ds", order)               # outside the theme's categories
        picked = [f["id"] for f in ex.fields("gem_ds", set(), 5)]
        self.assertEqual(set(picked), {"gem_pred_5d", "gem_score_vec"})

    def test_probes_use_live_operators_and_skip_tried_families(self):
        ex = Explorer(self.ctx, _Gen())
        exprs = {ex.expression(f) for f in self.store.fields(SCOPE, dataset="gem_ds") if f["id"] in ("gem_pred_5d", "gem_score_vec")}
        self.assertEqual(exprs, {"rank(gem_pred_5d)", "rank(vec_avg(gem_score_vec))"})
        self.assertEqual([f["id"] for f in ex.fields("gem_ds", {"gem_pred_5d|level"}, 5)], ["gem_score_vec"])

    def test_run_falls_back_to_template_descriptions(self):
        ex = Explorer(self.ctx, _Gen())
        cands = ex.run(3)
        self.assertTrue(cands)
        self.assertTrue(all(c.origin == "explore" and c.raw["idea"] for c in cands))
        self.assertEqual(cands[0].expression, "rank(gem_pred_5d)")


if __name__ == "__main__":
    unittest.main()
