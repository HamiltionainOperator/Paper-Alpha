import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from p2a.brain.settings import allowed_values, validate_settings
from p2a.engine.evaluator import evaluate
from p2a.engine.refiner import negate_last_statement, split_description
from p2a.engine.themes import ThemeSpec, constraints_for, parse_rule
from p2a.fastexpr import parse, to_source
from p2a.knowledge import BM25
from p2a.knowledge.papers import clean_text, load_source
from p2a.llm import extract_json
from p2a.llm.jsonx import salvage_list
from p2a.util import chunk_text, html_to_text
from tests.helpers import FIXTURES, load_catalog_fixture

CATS = load_catalog_fixture()["categories"]
OPTIONS = json.loads((FIXTURES / "settings_options.json").read_text())
PP = {"max_operators": 8, "excluded_operators": ["ts_backfill", "group_backfill"], "max_unique_fields": 3,
      "grouping_fields": ["industry", "sector"], "min_sharpe": 1.0, "turnover_range": [0.01, 0.7],
      "must_pass_checks": ["LOW_SUB_UNIVERSE_SHARPE", "POWER_POOL_CORRELATION", "HIGH_TURNOVER"],
      "eligible_classification": "POWER_POOL:POWER_POOL_ELIGIBLE", "theme_name_pattern": "(?i)power\\s*pool"}
WEIGHTS = {"sharpe": 1.0, "fitness": 0.35, "margin_bps": 0.05, "margin_cap_bps": 20, "turnover_soft_cap": 0.35,
           "turnover_penalty": 2.0}
REFINE = {"near_miss_min_sharpe": 0.6, "sign_flip_below": -0.8}


def minimal_pdf(text_lines):
    """Build a one-page PDF with Helvetica text (no external libraries)."""
    stream = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({l}) Tj T*" for l in text_lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


class ThemeTests(unittest.TestCase):
    def test_parse_rule_with_typo(self):
        spec = parse_rule(ThemeSpec(name="t"), "delay=1 & datacategory in ['pv', 'fundamnetal'] & single datacategory", CATS)
        self.assertEqual(spec.delay, 1)
        self.assertEqual(spec.categories, {"pv", "fundamental"})
        self.assertTrue(spec.single_category)
        self.assertTrue(any("fundamnetal" in w for w in spec.warnings))

    def test_extra_conditions_and_scope(self):
        spec = parse_rule(ThemeSpec(name="IND"), "region=IND & delay=1 & Robust Universe Sharpe > 1", CATS)
        self.assertEqual(spec.regions, {"IND"})
        self.assertEqual(spec.extra, ["Robust Universe Sharpe > 1"])
        self.assertTrue(spec.scope_problems({"region": "USA", "delay": 1, "universe": "TOP3000"}))
        c = constraints_for(spec, PP)
        self.assertEqual(c.max_ops, 8)
        self.assertIn("ts_backfill", c.excluded_ops)

    def test_activity_window(self):
        spec = ThemeSpec(name="x", start=date(2026, 10, 14), end=date(2026, 10, 27))
        self.assertTrue(spec.active(date(2026, 10, 15)))
        self.assertFalse(spec.active(date(2026, 10, 28)))


class SettingsTests(unittest.TestCase):
    def test_nested_choices(self):
        s = {"instrumentType": "EQUITY", "region": "GLB", "universe": "TOPDIV3000", "delay": 1}
        self.assertIn("COUNTRY", allowed_values(OPTIONS, "neutralization", s))
        self.assertNotIn("COUNTRY", allowed_values(OPTIONS, "neutralization", {**s, "region": "USA"}))

    def test_validate(self):
        ok = {"instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000", "delay": 1, "decay": 4,
              "neutralization": "SUBINDUSTRY", "truncation": 0.08, "language": "FASTEXPR", "visualization": False}
        self.assertEqual(validate_settings(ok, OPTIONS), [])
        errs = validate_settings({**ok, "universe": "TOP9999", "decay": 999, "truncation": 3, "foo": 1}, OPTIONS)
        self.assertEqual(len(errs), 4)


class EvaluatorTests(unittest.TestCase):
    def alpha(self, sharpe, turnover, checks, cls=()):
        return {"is": {"sharpe": sharpe, "turnover": turnover, "fitness": 0.8, "margin": 0.0005, "checks": checks},
                "classifications": [{"id": c} for c in cls]}

    def test_eligible_after_check(self):
        checks = [{"name": "LOW_SUB_UNIVERSE_SHARPE", "result": "PASS"}, {"name": "POWER_POOL_CORRELATION", "result": "PASS"},
                  {"name": "MATCHES_THEMES", "result": "PASS", "themes": [{"name": "D1 Power Pool Oct`26 2"}]}]
        ev = evaluate(self.alpha(1.3, 0.2, checks, ["POWER_POOL:POWER_POOL_ELIGIBLE"]), PP, WEIGHTS, REFINE)
        self.assertEqual(ev.status, "eligible")
        self.assertEqual(ev.theme_matches, ["D1 Power Pool Oct`26 2"])

    def test_pending_and_failures(self):
        pend = [{"name": "POWER_POOL_CORRELATION", "result": "PENDING"},
                {"name": "MATCHES_THEMES", "result": "PENDING", "themes": [{"name": "D1 Power Pool"}]}]
        self.assertEqual(evaluate(self.alpha(1.3, 0.2, pend), PP, WEIGHTS, REFINE).status, "pending")
        bad = [{"name": "HIGH_TURNOVER", "result": "FAIL", "value": 0.9, "limit": 0.7}]
        ev = evaluate(self.alpha(0.9, 0.9, bad), PP, WEIGHTS, REFINE)
        self.assertEqual(ev.status, "near_miss")
        self.assertTrue(any("HIGH_TURNOVER" in r for r in ev.reasons))
        self.assertEqual(evaluate(self.alpha(-1.2, 0.2, pend), PP, WEIGHTS, REFINE).status, "near_miss")
        self.assertEqual(evaluate(self.alpha(0.1, 0.2, pend), PP, WEIGHTS, REFINE).status, "fail")
        wrong_theme = [{"name": "MATCHES_THEMES", "result": "WARNING", "themes": [{"name": "D1 Power Pool"}]}]
        self.assertIn("MATCHES_THEMES", " ".join(evaluate(self.alpha(1.5, 0.2, wrong_theme), PP, WEIGHTS, REFINE).reasons))


class QualityGateTests(unittest.TestCase):
    Q = {"min_side_fraction": 0.03, "min_ic_sharpe_ratio": 0.3, "max_concentrated_weight": 0.25}
    PASSING = [{"name": "LOW_SUB_UNIVERSE_SHARPE", "result": "PASS"}, {"name": "POWER_POOL_CORRELATION", "result": "PASS"},
               {"name": "MATCHES_THEMES", "result": "PASS", "themes": [{"name": "D1 Power Pool Oct`26 2"}]}]

    def alpha(self, longs, shorts, ic, conc=None):
        checks = self.PASSING + ([{"name": "CONCENTRATED_WEIGHT", "result": "WARNING", "value": conc}] if conc else [])
        return {"settings": {"universe": "TOP3000"}, "classifications": [{"id": "POWER_POOL:POWER_POOL_ELIGIBLE"}],
                "is": {"sharpe": 2.6, "turnover": 0.24, "fitness": 3.6, "longCount": longs, "shortCount": shorts,
                       "investabilityConstrained": {"sharpe": ic}, "checks": checks}}

    def test_artifact_is_suspect(self):
        ev = evaluate(self.alpha(74, 49, -1.38, conc=0.5), PP, WEIGHTS, REFINE, quality=self.Q)
        self.assertEqual(ev.status, "suspect")
        text = " ".join(ev.reasons)
        for tag in ("NARROW", "INVESTABILITY", "CONCENTRATED"):
            self.assertIn(tag, text)

    def test_one_sided_and_healthy(self):
        self.assertIn("ONE_SIDED", " ".join(evaluate(self.alpha(3056, 0, 0.2), PP, WEIGHTS, REFINE, quality=self.Q).reasons))
        self.assertEqual(evaluate(self.alpha(1400, 1450, 1.9), PP, WEIGHTS, REFINE, quality=self.Q).status, "eligible")


class RefinerTests(unittest.TestCase):
    def test_negation_costs(self):
        for src, want in [("-rank(x)", "rank(x)"), ("0.5 * rank(x)", "-0.5 * rank(x)"), ("a - b", "b - a"),
                          ("rank(x)", "-rank(x)"), ("a = rank(x); a + 1", "a = rank(x); -(a + 1)")]:
            prog = parse(src)
            negate_last_statement(prog)
            self.assertEqual(to_source(prog), want)

    def test_split_description(self):
        d = "Idea: up\n\nRationale for data used: f1\n\nRationale for operators used: rank(): norm"
        parts = split_description(d, ["Idea", "Rationale for data used", "Rationale for operators used"])
        self.assertEqual(parts, {"idea": "up", "rationale_data": "f1", "rationale_operators": "rank(): norm"})


class KnowledgeTests(unittest.TestCase):
    def test_json_extraction(self):
        self.assertEqual(extract_json('<think>hmm</think>```json\n{"a": [1, 2,],}\n```'), {"a": [1, 2]})
        self.assertEqual(extract_json('Sure! {"candidates": [{"expression": "rank(x)"}]} hope it helps'),
                         {"candidates": [{"expression": "rank(x)"}]})
        self.assertIsNone(extract_json("no json here"))
        truncated = '{"candidates": [{"expression": "rank(a)", "idea": "x {y}"}, {"expression": "rank(b)"}, {"expression": "ra'
        self.assertNotIn("candidates", extract_json(truncated) or {})
        self.assertEqual([c["expression"] for c in salvage_list(truncated)["candidates"]], ["rank(a)", "rank(b)"])

    def test_bm25_and_chunks(self):
        bm = BM25(["analyst estimate revisions", "news sentiment scores", "option implied volatility"])
        self.assertEqual(bm.top("revision of analysts' estimates", 1)[0][0], 0)
        chunks = chunk_text("\n\n".join(f"para {i} " + "x" * 300 for i in range(20)), size=1000, overlap=100)
        self.assertTrue(all(len(c) <= 1100 for c in chunks))
        self.assertGreater(len(chunks), 4)

    def test_html_and_clean(self):
        self.assertEqual(html_to_text("<p>a<br>b</p><style>x{}</style><li>c</li>"), "a\nb\nc")
        t = clean_text("Momen-\ntum works\nwell.\n\nMain text.\n" + "body\n" * 10 + "References\n[1] Foo")
        self.assertIn("Momentum works well.", t)
        self.assertNotIn("[1] Foo", t)

    def test_pdf_ingestion(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "paper.pdf"
            p.write_bytes(minimal_pdf(["Earnings Revisions and Stock Returns",
                                       "Stocks with upward analyst revisions outperform."]))
            title, text, meta = load_source(str(p))
            self.assertIn("upward analyst revisions", text)
            self.assertEqual(title, "Earnings Revisions and Stock Returns")


if __name__ == "__main__":
    unittest.main()
