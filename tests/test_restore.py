"""p2a restore: a fresh store rebuilt from the account's own alphas on BRAIN (mock API)."""
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import yaml

from p2a.config import Config
from p2a.engine import Engine
from tests import mock_brain

ROOT = Path(__file__).resolve().parent.parent
REVISION = "rank(ts_mean(mdl26_avrevsn_fq1_earnings_30, 20))"


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.server, self.state, url = mock_brain.start()
        self.tmp = Path(tempfile.mkdtemp())
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        cfg["paths"] = {"data_dir": str(self.tmp / "data"), "prompts_dir": str(ROOT / "prompts")}
        cfg["brain"]["api_base"] = url
        cfg["brain"]["min_request_interval_s"] = 0
        cfg["brain"]["auth"] = {"auto_open_browser": False}
        (self.tmp / "config.yaml").write_text(yaml.safe_dump(cfg))
        self.env = {k: os.environ.get(k) for k in ("BRAIN_EMAIL", "BRAIN_PASSWORD")}
        os.environ["BRAIN_EMAIL"], os.environ["BRAIN_PASSWORD"] = "user@test", "pw"
        self.eng = Engine(Config.load(self.tmp / "config.yaml"), interactive=False)
        self.settings = {**self.eng.cfg.section("default_settings"), **self.eng.scope(), "neutralization": "INDUSTRY"}

    def tearDown(self):
        self.server.shutdown()
        self.eng.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def account_alpha(self, aid: str, code: str, created: str, settings: dict | None = None, **extra) -> dict:
        a = mock_brain.make_alpha(aid, code, {**self.settings, **(settings or {})})
        a.update({"dateCreated": created, **extra})
        self.state.alphas[aid] = a
        return a

    def test_restores_regular_alphas_once_without_polluting_memory(self):
        self.account_alpha("R1", REVISION, "2026-10-20T10:00:00-04:00", status="ACTIVE",
                           dateSubmitted="2026-10-20T12:00:00-04:00")
        self.account_alpha("D1", "rank(ts_mean(mdl26_avrevsn_fy1_earnings_30, 20))", "2026-10-16T10:00:00-04:00",
                           status="DECOMMISSIONED", dateSubmitted="2026-10-16T12:00:00-04:00")
        self.account_alpha("R2", "-rank(ts_delta(close, 5))", "2026-10-19T10:00:00-04:00", status="UNSUBMITTED")
        self.account_alpha("R3", "rank(retired_field_x)", "2026-10-18T10:00:00-04:00")  # a field BRAIN no longer has
        self.state.alphas["S1"] = {"id": "S1", "type": "SUPER", "settings": dict(self.settings),
                                   "selection": "x", "combo": "y", "dateCreated": "2026-10-21T10:00:00-04:00"}
        self.state.alphas["G1"] = {"id": "G1", "type": "REGION_AGNOSTIC", "regular": {"code": "rank(close)"},
                                   "settings": {**self.settings, "region": "ALL", "universe": "LARGE"},
                                   "dateCreated": "2026-10-21T11:00:00-04:00"}
        # the engine's own reversal reference factor (config uniqueness.references), simulated in an earlier session
        self.account_alpha("F1", "-rank(ts_sum(returns, 5))", "2026-10-17T10:00:00-04:00",
                           settings={"neutralization": "SUBINDUSTRY", "decay": 4})

        res = self.eng.restore()
        self.assertEqual((res["restored"], res["skipped"], res["known"], res["references"]), (4, 2, 0, 1))
        # a reference factor never becomes an alpha row (families, combinations, queue); the uniqueness screen
        # finds it where references.py keeps it, so it is not simulated again
        ref = self.eng.store.kv_get("reference:USA:1:TOP3000:reversal_5d")
        self.assertEqual(ref["brain_id"], "F1")
        rows = {r["brain_id"]: r for r in self.eng.store.alphas(status="simulated")}
        self.assertEqual(set(rows), {"R1", "R2", "R3", "D1"})
        # a decommissioned alpha is no longer ACTIVE but was submitted: its idea is used, never queued again
        from p2a.engine.lifecycle import Lifecycle, row_family
        ctx = self.eng.context(self.eng.scope(), None, "power_pool")
        fams = Lifecycle(ctx, submitted=[]).families()
        self.assertEqual((fams[row_family(ctx, rows["D1"])].state, fams[row_family(ctx, rows["D1"])].reason),
                         ("used", "submitted (D1)"))
        r1 = rows["R1"]
        self.assertEqual(r1["fields"], ["mdl26_avrevsn_fq1_earnings_30"])  # analysed against the live catalog
        self.assertEqual(r1["datasets"], ["model26"])
        self.assertEqual(r1["settings"]["neutralization"], "INDUSTRY")     # BRAIN's settings, as simulated
        self.assertEqual(r1["stats"]["sharpe"], 1.45)                     # BRAIN's results and checks, re-judged
        self.assertTrue(r1["pp_status"] and r1["reg_status"])
        self.assertEqual(r1["origin"], "restore")
        self.assertAlmostEqual(r1["simulated_at"], datetime.fromisoformat("2026-10-20T14:00:00+00:00").timestamp())
        self.assertIn("USA/TOP3000/D1", res["scopes"])
        # an alpha on a vanished field is still history; its analysis issue stays on its row, not in the
        # hallucination memory that future prompts read
        self.assertTrue(any("retired_field_x" in i for i in rows["R3"]["issues"]))
        self.assertFalse(any(i["subject"] == "retired_field_x" for i in self.eng.store.top_issues(50)))
        # themes in old checks are not themes BRAIN shows today
        self.assertIsNone(self.eng.store.kv_get("observed_themes"))

        again = self.eng.restore()
        self.assertEqual((again["restored"], again["known"]), (0, 4))
        self.assertEqual(len(self.eng.store.alphas()), 4)

        # the engine never simulates a restored alpha again: the same code and settings are a duplicate
        ids = self.eng.try_candidates(self.eng.scope(), None, [{"expression": REVISION, "neutralization": "INDUSTRY"}],
                                      route="regular")
        self.assertEqual(ids, [])


if __name__ == "__main__":
    unittest.main()
