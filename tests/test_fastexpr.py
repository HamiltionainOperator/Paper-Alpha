import unittest

from p2a.fastexpr import Constraints, FastExprSyntaxError, analyze, parse, parse_operator, to_source
from p2a.fastexpr.signatures import Symbol
from tests.helpers import load_operators, make_catalog

OPS = {o["name"]: o for o in load_operators()}
PP = Constraints(max_ops=8, excluded_ops={"ts_backfill", "group_backfill"}, max_fields=3,
                 grouping_fields={"country", "industry", "subindustry", "currency", "market", "sector", "exchange"},
                 allowed_categories={"analyst", "model", "news"}, single_category=True, label="test theme")


def codes(an):
    return [i.code for i in an.errors]


class SignatureTests(unittest.TestCase):
    def test_variadic_with_infix(self):
        s = parse_operator(OPS["add"])
        self.assertEqual(s.positional, ["x", "y"])
        self.assertEqual(s.keywords, {"filter": False})
        self.assertTrue(s.variadic)
        self.assertEqual(s.infix, ["+"])

    def test_keyword_with_symbolic_default(self):
        s = parse_operator(OPS["ts_backfill"])
        self.assertEqual(s.positional, ["x"])
        self.assertEqual(list(s.keywords), ["lookback", "k"])
        self.assertIsInstance(s.keywords["lookback"], Symbol)
        self.assertEqual(s.max_args, 3)

    def test_infix_only(self):
        s = parse_operator(OPS["not_equal"])
        self.assertFalse(s.call_form)
        self.assertEqual(s.infix, ["!="])

    def test_alternative_forms_and_smart_quotes(self):
        s = parse_operator(OPS["bucket"])
        self.assertEqual(s.positional, ["x"])
        self.assertEqual(s.keywords["range"], "0, 1, 0.1")
        self.assertIn("buckets", s.keywords)
        self.assertIs(s.keywords["skipBoth"], False)

    def test_odd_definitions(self):
        self.assertEqual(parse_operator(OPS["if_else"]).positional, ["input1", "input2", "input3"])
        self.assertEqual(parse_operator(OPS["ts_step"]).positional, ["x"])
        mn = parse_operator(OPS["min"])
        self.assertTrue(mn.variadic)
        self.assertEqual(mn.positional, ["x", "y"])
        self.assertEqual(parse_operator(OPS["kth_element"]).keywords["ignore"], "NaN")


class ParserTests(unittest.TestCase):
    def test_precedence_and_print_roundtrip(self):
        src = "a = rank(x) ; -a * 2 + b / c - d"
        prog = parse(src)
        self.assertEqual(to_source(prog), "a = rank(x); -a * 2 + b / c - d")
        self.assertEqual(to_source(parse("a - (b - c)")), "a - (b - c)")
        self.assertEqual(to_source(parse("(a - b) - c")), "a - b - c")
        self.assertEqual(to_source(parse("-(a + b)")), "-(a + b)")

    def test_comments_and_keywords(self):
        prog = parse("# header\n/* block\n comment */ ts_regression(y, x, 252, lag=0, rettype=2)")
        call = prog.statements[0]
        self.assertEqual([k.name for k in call.kwargs], ["lag", "rettype"])

    def test_syntax_error_position(self):
        with self.assertRaises(FastExprSyntaxError) as cm:
            parse("rank(ts_mean(x, 5)")
        self.assertIn("expected ',' or ')'", str(cm.exception))
        with self.assertRaises(FastExprSyntaxError):
            parse("rank(x,)")
        with self.assertRaises(FastExprSyntaxError):
            parse("a = ")


class OperatorCountTests(unittest.TestCase):
    """Structural cases mirroring the platform's operatorCount on real alphas."""
    CASES = [
        ("group_neutralize(rank(close / cap), industry)", 3),
        ("-ts_delta(close, 3410)", 2),
        ("ts_delta(close, 3400)", 1),
        ("rank(-1*returns)", 2),
        ("rank(returns)", 1),
        ("-group_rank(ts_std_dev(ts_backfill(vec_avg(nws18_ssc), 90), 252), sector)", 5),
        ("group_rank(ts_zscore(ts_backfill(vec_avg(nws18_ssc), 120), 252) - "
         "ts_zscore(ts_backfill(vec_avg(nws18_bee), 120), 252), industry)", 8),
        ("-group_rank(ts_zscore(ts_backfill(vec_range(nws18_ssc) / (vec_count(nws18_ssc) + 0.0001), 90), 252), industry)", 8),
        ("trade_when(days_from_last_change(vec_avg(nws18_ssc)) == 0, group_rank(vec_avg(nws18_ssc), industry), -1)", 6),
        ("a = rank(ts_arg_max(close, 30)); b = (close - volume) / close; b / min(ts_decay_linear(a, 1), 0.15)", 7),
        ("p = ts_sum(close, 5); q = ts_sum(volume, 5); m = ts_delta(p - q, 5) / max(p + q, 1); "
         "z = ts_zscore(returns, 5); rank(m * sign(z))", 11),
        ("rank(-0.60 * (5500 * (0.50 * (ts_delta(close, 2500) / 2500) + 0.30 * (ts_delta(close, 1250) / 1250) "
         "+ 0.20 * (ts_delta(close, 625) / 625))) -0.40 * ts_delta(close, 2500))", 17),
        ("0.6 * (-ts_delay(close, 20) + ts_delay(close, 5520)) + 0.4 * (-ts_delay(close, 20) + ts_delay(close, 2520))", 11),
        ("# comment\nrank(0.6*ts_delta(close, 5500) + 0.4*ts_delta(close, 2500)) * 10 +\n"
         "# more\nrank(ts_delta(close, 1260)) * 2 + rank(ts_delta(close, 500)) * 1", 15),
        ("-(rank(hump(ts_zscore(returns, 126) - ts_zscore(ts_delay(group_mean(returns, 1, market), 1), 126), hump=0.02)))", 8),
    ]

    def test_counts(self):
        cat = make_catalog(lenient=True)
        for src, expected in self.CASES:
            with self.subTest(src=src):
                self.assertEqual(analyze(src, cat).op_count, expected)

    def test_power_pool_count_excludes_backfill(self):
        an = analyze("-group_rank(ts_std_dev(ts_backfill(vec_avg(nws18_ssc), 90), 252), sector)", make_catalog(), PP)
        self.assertEqual(an.op_count, 5)
        self.assertEqual(an.pp_op_count(), 4)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.cat = make_catalog()

    def test_valid_power_pool_alpha(self):
        an = analyze("group_rank(ts_mean(vec_avg(nws18_ssc), 20), subindustry)", self.cat, PP)
        self.assertTrue(an.ok, an.report())
        self.assertEqual(an.counted_fields(), ["nws18_ssc"])
        self.assertEqual(an.categories(), ["news"])

    def test_hallucinated_operator(self):
        an = analyze("rank(ts_max(close, 20))", self.cat)
        self.assertIn("E_UNKNOWN_OP", codes(an))
        self.assertIn("ts_", an.errors[0].hint)

    def test_unknown_field_suggestion(self):
        an = analyze("rank(Close)", self.cat)
        self.assertIn("E_UNKNOWN_FIELD", codes(an))
        self.assertIn("close", an.errors[0].hint)

    def test_vector_rules(self):
        self.assertIn("E_VECTOR", codes(analyze("rank(nws18_ssc)", self.cat)))
        self.assertIn("E_VEC_INPUT", codes(analyze("rank(vec_avg(close))", self.cat)))
        self.assertTrue(analyze("rank(vec_sum(nws18_bee))", self.cat).ok)

    def test_group_rules(self):
        self.assertIn("E_GROUP_ARG", codes(analyze("group_rank(close, volume)", self.cat)))
        self.assertIn("E_GROUP_MISUSE", codes(analyze("rank(industry)", self.cat)))
        an = analyze('g = bucket(rank(cap), range="0.1,1,0.1"); group_zscore(close, densify(g))', self.cat)
        self.assertTrue(an.ok, an.report())

    def test_lookback_and_keywords(self):
        self.assertIn("E_LOOKBACK", codes(analyze("ts_mean(close, volume)", self.cat)))
        self.assertIn("E_LOOKBACK", codes(analyze("ts_mean(close, 2.5)", self.cat)))
        self.assertIn("E_KWARG", codes(analyze("ts_mean(close, d=5)", self.cat)))
        self.assertIn("E_KWARG", codes(analyze("winsorize(close, sigma=3)", self.cat)))
        self.assertTrue(analyze("ts_backfill(close, 60)", self.cat).ok)
        self.assertTrue(analyze("quantile(close, driver=cauchy, sigma=0.5)", self.cat).ok)
        self.assertIn("E_KW_VALUE", codes(analyze("quantile(close, driver=banana)", self.cat)))

    def test_arity_scope_and_policy(self):
        self.assertIn("E_ARITY", codes(analyze("ts_corr(close, volume)", self.cat)))
        self.assertIn("E_SCOPE", codes(analyze("combo_a(close)", self.cat)))
        self.assertIn("E_POLICY", codes(analyze("close ^ 2", self.cat)))
        self.assertIn("E_POLICY", codes(analyze("close > 1 ? close : volume", self.cat)))
        self.assertIn("E_INFIX_ONLY", codes(analyze("less(close, volume)", self.cat)))

    def test_program_structure(self):
        self.assertIn("E_NO_ALPHA", codes(analyze("a = rank(close)", self.cat)))
        self.assertIn("E_NO_DATA", codes(analyze("rank(ts_step(1))", self.cat)))
        self.assertIn("E_VAR_NAME", codes(analyze("close = rank(volume); close", self.cat)))
        an = analyze("a = rank(close); b = rank(volume); a", self.cat)
        self.assertIn("W_UNUSED", [w.code for w in an.warnings])

    def test_theme_constraints(self):
        an = analyze("rank(vec_avg(nws18_ssc)) * rank(mdl26_avrevsn_fq1_earnings_30)", self.cat, PP)
        self.assertIn("C_SINGLE_CATEGORY", codes(an))
        an = analyze("group_rank(ts_delta(close, 5), industry)", self.cat, PP)
        self.assertIn("C_CATEGORY", codes(an))
        an = analyze("rank(vec_avg(nws18_ssc) + vec_avg(nws18_bee) + vec_avg(nws18_nip) + vec_avg(nws18_relevance))",
                     self.cat, PP)
        self.assertIn("C_MAX_FIELDS", codes(an))
        long = "rank(ts_mean(ts_delta(ts_zscore(ts_rank(ts_decay_linear(vec_avg(nws18_ssc), 5), 20), 20), 5), 10)) * 2 + 1"
        self.assertIn("C_MAX_OPERATORS", codes(analyze(long, self.cat, PP)))

    def test_theme_counts_grouping_field_categories(self):
        from dataclasses import replace
        strict = replace(PP, count_grouping_categories=True)
        an = analyze("group_rank(ts_mean(vec_avg(nws18_ssc), 20), subindustry)", self.cat, strict)
        self.assertIn("C_CATEGORY", codes(an))
        self.assertIn("neutralization setting", an.errors[0].hint)
        self.assertTrue(analyze("rank(ts_mean(vec_avg(nws18_ssc), 20))", self.cat, strict).ok)
        self.assertEqual(an.counted_fields(), ["nws18_ssc"])  # still free for the 3-field limit

    def test_sanitize_and_canonical(self):
        an = analyze("```\nRank(ts_mean(close, 5)) – rank(volume)\n```", self.cat)
        self.assertTrue(an.ok, an.report())
        self.assertEqual(an.canonical, "rank(ts_mean(close, 5)) - rank(volume)")
        self.assertTrue(an.fixes)

    def test_non_numeric_and_case_mismatched_fields(self):
        from p2a.fastexpr import Catalog, FieldInfo, Rules
        from tests.helpers import load_operators
        lookup = {"Close_Price": FieldInfo(id="close_price"), "period_end": FieldInfo(id="period_end", type="SYMBOL")}
        cat = Catalog(load_operators(), Rules(), [], field_lookup=lambda n: lookup.get(n))
        an = analyze("rank(Close_Price)", cat)
        self.assertIn("E_UNKNOWN_FIELD", codes(an))
        self.assertIn("close_price", an.errors[0].hint)
        self.assertIn("E_FIELD_TYPE", codes(analyze("rank(period_end)", cat)))

    def test_group_level_tracking(self):
        ind = "s = group_mean(mdl26_avrevsn_fq1_earnings_30, 1, industry); sign(ts_mean(s, 63))"
        self.assertEqual(analyze(ind, self.cat).group_level, "industry")
        self.assertEqual(analyze("rank(group_mean(close, 1, sector))", self.cat).group_level, "sector")
        self.assertIsNone(analyze("group_mean(close, 1, industry) - close", self.cat).group_level)
        self.assertIsNone(analyze("group_neutralize(rank(close), industry)", self.cat).group_level)
        an = analyze("group_neutralize(group_mean(close, 1, industry), sector)", self.cat)
        self.assertTrue(an.ok, an.report())
        self.assertEqual(an.group_level, "industry")
        flat = analyze("s = group_mean(close, 1, sector); group_neutralize(sign(ts_mean(s, 63)), sector)", self.cat)
        self.assertIn("E_DEGENERATE", codes(flat))
        self.assertIn("E_DEGENERATE", codes(analyze("group_rank(group_mean(close, 1, industry), subindustry)", self.cat)))

    def test_coverage_warning_suppressed_by_backfill(self):
        w = [i.code for i in analyze("rank(days_since_positive_bold_estimate_fy2)", self.cat).warnings]
        self.assertIn("W_COVERAGE", w)
        w = [i.code for i in analyze("rank(ts_backfill(days_since_positive_bold_estimate_fy2, 63))", self.cat).warnings]
        self.assertNotIn("W_COVERAGE", w)


if __name__ == "__main__":
    unittest.main()
