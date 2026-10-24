"""Learning memory: what the engine has learned from its own validations and simulations.

There is no fine-tuning of the free models. The engine "trains" by feeding its own
experience back into every prompt:
  * hallucinations it has caught before (unknown operators/fields, bad keywords, ...)
  * its best simulated alphas as few-shot exemplars (closest dataset/category first)
  * per-dataset outcome statistics (typical Sharpe/turnover, most frequent failing checks)
and by choosing hypotheses, datasets and models with Thompson sampling on past results.
"""
from __future__ import annotations

import random
import statistics
from collections import Counter

from ..fastexpr import Catalog, analyze
from ..store import Store

TRACKED = ("E_UNKNOWN_OP", "E_UNKNOWN_FIELD", "E_KWARG", "E_VECTOR", "E_VEC_INPUT", "E_GROUP_ARG", "E_GROUP_MISUSE",
           "E_LOOKBACK", "E_ARITY", "E_POLICY", "E_SCOPE", "E_INFIX_ONLY", "C_MAX_OPERATORS", "C_MAX_FIELDS",
           "C_CATEGORY", "C_SINGLE_CATEGORY", "E_SYNTAX", "E_KW_VALUE", "E_FIELD_TYPE", "E_DEGENERATE", "SIM_ERROR")


def _phrase(code: str, subject: str, n: int) -> str | None:
    s = subject
    if code == "E_UNKNOWN_OP" and s:
        return f"`{s}` is NOT an available operator (invented {n}x before)"
    if code == "E_UNKNOWN_FIELD" and s:
        return f"`{s}` is NOT a data field in this scope (invented {n}x before)"
    if code == "E_KWARG" and s and "." in s:
        op, kw = s.split(".", 1)
        return f"{op}() has no keyword `{kw}` ({n}x)"
    if code == "E_VECTOR" and s:
        return f"`{s}` is a VECTOR field: always wrap it in a vec_* operator first ({n}x)"
    if code == "E_VEC_INPUT" and s:
        return f"{s}() only accepts VECTOR fields, never MATRIX fields or expressions ({n}x)"
    if code == "E_GROUP_ARG":
        return f"group arguments must be GROUP fields (industry/subindustry/sector/market...) or bucket(...) ({n}x)"
    if code == "E_GROUP_MISUSE" and s:
        return f"`{s}` is a GROUP field: use it only as the group argument ({n}x)"
    if code == "E_LOOKBACK":
        return f"time-series windows must be positive integer literals ({n}x)"
    if code == "C_MAX_OPERATORS":
        return f"too many operators happened {n}x: count every call and every infix + - * / < > == (ts_backfill free)"
    if code == "C_MAX_FIELDS":
        return f"too many distinct data fields happened {n}x: at most the limit, grouping fields excluded"
    if code in ("C_CATEGORY", "C_SINGLE_CATEGORY"):
        return f"mixing data categories / leaving the theme categories happened {n}x"
    if code == "E_POLICY":
        return f"'^' and 'a ? b : c' are not allowed: use power()/signed_power() and if_else() ({n}x)"
    if code == "E_INFIX_ONLY" and s:
        return f"comparison operators are infix only: write x < y, not less(x, y) ({n}x)"
    if code == "E_SYNTAX":
        return f"syntax errors happened {n}x: balance parentheses, separate statements with ';'"
    if code == "E_FIELD_TYPE" and s:
        return f"`{s}` is not a numeric field (e.g. a date/SYMBOL); never use it ({n}x)"
    if code == "E_DEGENERATE":
        return (f"group-level signals were flattened {n}x: never group_neutralize/group_rank a value that is constant "
                "within the same or a finer group (e.g. group_mean over industry, then neutralize by industry)")
    if code == "SIM_ERROR" and s:
        return f"the BRAIN simulator rejected an alpha with: \"{s}\" ({n}x)"
    return None


class Memory:
    def __init__(self, store: Store, cfg):
        self.store = store
        self.cfg = cfg

    # -- validation feedback ------------------------------------------------------
    def record_analysis(self, analysis) -> None:
        for issue in analysis.errors:
            if issue.code in TRACKED:
                subject = issue.subject if issue.code not in ("E_LOOKBACK", "E_GROUP_ARG", "E_SYNTAX", "E_POLICY", "E_DEGENERATE",
                                                              "C_MAX_OPERATORS", "C_MAX_FIELDS", "C_SINGLE_CATEGORY") else ""
                self.store.record_issue(issue.code, subject)

    def hallucination_notes(self, n: int = 12) -> list[str]:
        out = []
        for row in self.store.top_issues(n * 2, codes=TRACKED):
            text = _phrase(row["code"], row["subject"], row["count"])
            if text and text not in out:
                out.append(text)
            if len(out) >= n:
                break
        return out

    # -- exemplars ----------------------------------------------------------------
    def exemplars(self, categories: set | None, datasets: set | None, k: int) -> list[dict]:
        rows = self.store.q("SELECT * FROM alphas WHERE status='simulated' AND score IS NOT NULL "
                            "AND pp_status IN ('eligible','pending','near_miss') ORDER BY score DESC LIMIT 300")

        def rank(r):
            ds = set(r.get("datasets") or [])
            cats = set(r.get("categories") or [])
            return (2 if datasets and ds & datasets else 1 if categories and cats & categories else 0, r["score"])

        picked, seen_ops = [], set()
        for r in sorted(rows, key=rank, reverse=True):
            sig = tuple(r.get("operators") or [])
            if sig in seen_ops:
                continue
            seen_ops.add(sig)
            picked.append(r)
            if len(picked) >= k:
                break
        return picked

    def official_examples(self, catalog: Catalog, k: int, seed: int | None = None, constraints=None) -> list[str]:
        """Platform-provided example alphas that still validate against this account's catalog (and theme)."""
        good = []
        for ex in self.store.examples():
            an = analyze(ex["expression"], catalog, constraints)
            if an.ok and 2 <= an.op_count <= 10:
                good.append(an.canonical)
        rnd = random.Random(seed)
        rnd.shuffle(good)
        return good[:k]

    # -- outcome statistics -------------------------------------------------------------
    def dataset_lessons(self, datasets: set) -> list[str]:
        if not datasets:
            return []
        rows = [r for r in self.store.q("SELECT datasets, stats, pp_reasons, pp_status FROM alphas WHERE status='simulated'")
                if set(r.get("datasets") or []) & datasets]
        if len(rows) < 3:
            return []
        sharpes = [r["stats"].get("sharpe") for r in rows if r.get("stats") and r["stats"].get("sharpe") is not None]
        turns = [r["stats"].get("turnover") for r in rows if r.get("stats") and r["stats"].get("turnover") is not None]
        fails = Counter(reason.split(" ")[0] for r in rows for reason in (r.get("pp_reasons") or []))
        good = sum(1 for r in rows if r.get("pp_status") in ("eligible", "pending"))
        out = [f"{len(rows)} past simulations on {', '.join(sorted(datasets))}: {good} met Power Pool criteria"]
        if sharpes:
            out.append(f"median Sharpe {statistics.median(sharpes):.2f}, median turnover {statistics.median(turns):.1%}"
                       if turns else f"median Sharpe {statistics.median(sharpes):.2f}")
        if fails:
            out.append("most frequent failures: " + ", ".join(f"{k} ({v})" for k, v in fails.most_common(4)))
        return out

    # -- exploration ----------------------------------------------------------------------
    def pick_hypotheses(self, k: int, paper_id: str | None = None, ids: list[int] | None = None) -> list[dict]:
        rows = [self.store.hypothesis(i) for i in ids] if ids else self.store.hypotheses(paper_id)
        rows = [r for r in rows if r]
        if ids:
            return rows  # explicitly requested: use all of them, in the given order
        scored = [(random.betavariate(1 + (r["wins"] or 0), 1 + max(0, (r["tries"] or 0) - (r["wins"] or 0)) * 0.5)
                   + (0.5 if not r["tries"] else 0.0), r) for r in rows]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:k]]
