"""End-to-end run against the mock BRAIN API with a scripted (deliberately hallucinating) LLM."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from p2a.config import Config
from p2a.engine import Engine
from p2a.llm import LLMResult
from tests import mock_brain

ROOT = Path(__file__).resolve().parent.parent

GENERATE = {"candidates": [
    {"expression": "group_rank(ts_mean(mdl26_avrevsn_fq1_earnings_30, 20), subindustry)", "neutralization": "industry",
     "decay": 4, "truncation": 0.08, "idea": "Upward revisions keep drifting.", "rationale_data": "average revision of FQ1 EPS",
     "rationale_operators": "ts_mean(): smooths; group_rank(): peer comparison"},
    {"expression": "rank(ts_max(mdl26_avrevsn_fy1_earnings_30, 60))", "idea": "Peak revision", "rationale_data": "FY1",
     "rationale_operators": "ts_max(): peak"},
    {"expression": "rank(nws18_ssc)", "idea": "news tone", "rationale_data": "story sentiment", "rationale_operators": "rank()"},
    {"expression": "rank(ts_mean(ts_delta(ts_zscore(ts_rank(ts_decay_linear(abs(mdl26_avrevsn_fy1_earnings_30), 5), 20), 20), 5), 10)) * 2 + 1",
     "idea": "deep stack", "rationale_data": "FY1 revisions", "rationale_operators": "many"},
    {"expression": "rank(ts_delta(mdl26_eps_revision_score, 5))", "idea": "made-up field", "rationale_data": "?",
     "rationale_operators": "ts_delta()"},
    {"expression": "hump(rank(mdl26_60dy_srprs_lst_q_rnngs), hump=0.01)", "decay": 2, "idea": "Surprise drift, damped.",
     "rationale_data": "60-day surprise", "rationale_operators": "hump(): limits changes; rank(): normalise"},
]}
REPAIR = {"candidates": [
    {"expression": "rank(ts_rank(mdl26_avrevsn_fy1_earnings_30, 60))", "idea": "Peak revision", "rationale_data": "FY1",
     "rationale_operators": "ts_rank(): position in window; rank()"},
    {"expression": "rank(ts_mean(vec_avg(nws18_ssc), 10))", "idea": "news tone", "rationale_data": "story sentiment",
     "rationale_operators": "vec_avg(), ts_mean(), rank()"},
    {"expression": "rank(ts_zscore(mdl26_avrevsn_fy1_earnings_30, 60))", "idea": "standardised revision",
     "rationale_data": "FY1 revisions", "rationale_operators": "ts_zscore(), rank()"},
    {"expression": "rank(ts_delta(mdl26_60dy_srprs_lst_q_rnngs, 5))", "idea": "surprise change",
     "rationale_data": "60-day surprise", "rationale_operators": "ts_delta(), rank()"},
]}
HYPOTHESES = {"paper_summary": "Analyst revisions predict returns.", "hypotheses": [
    {"title": "Analyst revision momentum", "mechanism": "Investors under-react to estimate revisions.",
     "signal_construction": "Rank stocks by recent average EPS revisions; long upward, short downward.",
     "data_concepts": ["EPS estimate revisions"], "candidate_categories": ["Model", "analyst"],
     "horizon": "medium", "expected_turnover": "low", "keywords": ["revision", "estimate", "earnings"]}]}


class ScriptedLLM:
    """Stands in for OpenRouter; records prompts so the test can inspect the grounding."""

    daily_budget = 99

    def __init__(self):
        self.calls = []

    def budget_left(self):
        return 99 - len(self.calls)

    def reward(self, model, value):
        self.calls.append(("reward", model, value))

    def chat_json(self, messages, purpose, schema=None, min_context=0, max_attempts=3, temperature=None,
                  auto_reward=True, check=None):
        self.calls.append((purpose, messages))
        obj = {"hypotheses": HYPOTHESES, "generate": GENERATE, "repair": REPAIR}.get(purpose)
        if purpose == "refine":
            parent = int(messages[-1]["content"].split("### Alpha id ")[1].split("\n")[0])
            obj = {"candidates": [{"parent_id": parent, "expression": "rank(ts_mean(mdl26_avrevsn_fq1_earnings_30, 40))",
                                   "idea": "longer smoothing", "rationale_data": "FQ1 revisions",
                                   "rationale_operators": "ts_mean(), rank()"}]}
        if check:
            assert check(obj) is None, check(obj)
        return LLMResult(obj=obj, model="scripted/model", raw="{}", messages=messages + [{"role": "assistant", "content": "{}"}])


class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.state, url = mock_brain.start()
        cls.tmp = Path(tempfile.mkdtemp())
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        cfg["paths"] = {"data_dir": str(cls.tmp / "data"), "prompts_dir": str(ROOT / "prompts")}
        cfg["brain"]["api_base"] = url
        cfg["brain"]["min_request_interval_s"] = 0
        cfg["brain"]["auth"] = {"auto_open_browser": False}  # never open a real browser in tests
        cfg["power_pool"]["theme_counts_grouping_fields"] = False  # scenario below predates that rule
        cfg["themes"] = [{"name": "D1 Power Pool Oct`26 2",
                          "rule": "delay=1 & datacategory in ['analyst', 'model', 'news'] & single datacategory"}]
        (cls.tmp / "config.yaml").write_text(yaml.safe_dump(cfg))
        os.environ["BRAIN_EMAIL"], os.environ["BRAIN_PASSWORD"] = "persona@test", "pw"
        cls.cfg = Config.load(cls.tmp / "config.yaml")
        cls.eng = Engine(cls.cfg, interactive=False)
        cls.llm = ScriptedLLM()
        cls.eng.llm = cls.llm

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.eng.store.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_full_pipeline(self):
        eng, llm = self.eng, self.llm
        scope = eng.scope()
        # 1. biometric login is surfaced, not bypassed
        from p2a.brain import AuthRequired
        with self.assertRaises(AuthRequired) as cm:
            eng.client.login()
        self.assertIn("/authentication/persona", str(cm.exception))
        # 2. sync the catalog
        summary = eng.sync_catalog(scope)
        self.assertEqual(summary["operators"], len(self.state.operators))
        self.assertGreater(summary["datasets"], 3)
        self.assertTrue(eng.store.examples())
        self.assertTrue(eng.store.documents("brain_doc"))
        # 3. themes: config rule + API tags
        theme = eng.resolve_theme(scope)
        self.assertEqual(theme.categories, {"analyst", "model", "news"})
        self.assertTrue(theme.single_category)
        self.assertIn("news18", theme.api_datasets)
        # 4. ingest a paper and extract hypotheses
        paper = self.tmp / "paper.txt"
        paper.write_text("Analyst Revisions and Returns\n\nAbstract\nStocks with upward earnings estimate revisions "
                         "outperform. We sort stocks into deciles on 30-day EPS revisions.\n\n" + "Body text. " * 200)
        pids = eng.ingest([str(paper)])
        hyps = eng.store.hypotheses(pids[0])
        self.assertEqual(hyps[0]["body"]["candidate_categories"], ["model", "analyst"])
        # 5. generate: hallucinations are caught and repaired
        ids = eng.generate(scope, theme, hypothesis_ids=[hyps[0]["id"]])
        gen_prompt = next(m for p, m in [c for c in llm.calls if c[0] != "reward"] if p == "generate")[1]["content"]
        self.assertIn("ts_rank(x, d, constant=0)", gen_prompt)
        self.assertTrue(any(f["id"] in gen_prompt for f in self.state.fields if f["dataset"]["id"] != "pv1"))
        self.assertIn("ONE single data category", gen_prompt)
        self.assertNotIn("combo_a", gen_prompt)  # COMBO-only operators never reach the prompt
        repair_prompt = next(m for p, m in [c for c in llm.calls if c[0] != "reward"] if p == "repair")[-1]["content"]
        self.assertIn("E_UNKNOWN_OP", repair_prompt)
        self.assertIn("E_VECTOR", repair_prompt)
        self.assertIn("C_MAX_OPERATORS", repair_prompt)
        self.assertIn("E_UNKNOWN_FIELD", repair_prompt)
        self.assertEqual(len(ids), 6)
        rows = [eng.store.alpha(i) for i in ids]
        self.assertTrue(all(r["pp_op_count"] <= 8 and len(r["fields"]) <= 3 for r in rows))
        self.assertEqual(rows[0]["settings"]["neutralization"], "INDUSTRY")
        self.assertIn("Rationale for operators used:", rows[0]["description"])
        hallucinations = {(r["code"], r["subject"]) for r in eng.store.top_issues(50)}
        self.assertIn(("E_UNKNOWN_OP", "ts_max"), hallucinations)
        # 6. simulate through the mock (429 back-off, multi-simulation, polling, one simulator error)
        tally = eng.simulate()
        self.assertEqual(tally["done"] + tally["error"], 6)
        self.assertEqual(tally["error"], 1)
        statuses = {eng.store.alpha(i)["pp_status"] for i in ids if eng.store.alpha(i)["status"] == "simulated"}
        self.assertTrue(statuses <= {"pending", "near_miss", "fail"})
        self.assertIn("the BRAIN simulator rejected", " ".join(eng.memory.hallucination_notes(20)))
        # 7. refine near-misses (deterministic + LLM), then simulate the variants
        new = eng.refine(scope, theme)
        if new:
            eng.simulate(ids=new)
        # 8. submission check promotes pending alphas once correlation + theme pass
        checked = eng.check(top=10)
        self.assertTrue(any(c["pp_status"] == "eligible" for c in checked))
        # 9. report
        report = eng.report().read_text()
        self.assertIn("Power Pool description", report)
        self.assertIn("eligible", report)


class BiometricPollingTest(unittest.TestCase):
    """Biometric sign-in opens the link (fake opener here) and polls until BRAIN confirms it."""

    def test_auto_open_and_poll(self):
        server, state, url = mock_brain.start()
        tmp = Path(tempfile.mkdtemp())
        try:
            cfg = Config({"brain": {"api_base": url, "min_request_interval_s": 0,
                                    "auth": {"auto_open_browser": True, "persona_poll_interval_s": 0.05,
                                             "persona_timeout_s": 5}},
                          "paths": {"data_dir": str(tmp)}}, tmp)
            from p2a.brain import BrainClient
            client = BrainClient(cfg, ("persona@test", "pw"), interactive=False)
            opened = []
            client.open_in_browser = lambda link: opened.append(link) or True
            state.persona_needed_polls = 3
            client.login()
            self.assertEqual(len(opened), 1)
            self.assertIn("/authentication/persona?inquiry=", opened[0])
            self.assertEqual(state.persona_posts, 3)
            self.assertTrue(client.authenticated())
        finally:
            server.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
