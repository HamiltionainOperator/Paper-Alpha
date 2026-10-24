"""Paper -> testable alpha hypotheses (one LLM call per paper)."""
from __future__ import annotations

import json

from ..knowledge.bm25 import BM25
from ..llm import OpenRouter
from ..store import Store
from ..util import console, esc
from .grounding import render
from .themes import _match_category

HYP_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_summary": {"type": "string"},
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "mechanism": {"type": "string"},
                    "signal_construction": {"type": "string"},
                    "data_concepts": {"type": "array", "items": {"type": "string"}},
                    "candidate_categories": {"type": "array", "items": {"type": "string"}},
                    "horizon": {"type": "string"},
                    "expected_turnover": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                },
                "required": ["title", "mechanism", "signal_construction"],
            },
        },
    },
    "required": ["hypotheses"],
}

SIGNAL_QUERY = ("portfolio returns predict predictability long short decile quintile anomaly signal alpha "
                "cross-section sort abnormal return strategy factor")


def categories_text(cats: list[dict]) -> str:
    lines = []
    for c in cats:
        subs = ", ".join(ch.get("name", "") for ch in c.get("children") or [])
        lines.append(f"- {c['id']}: {c.get('name', '')}" + (f" - {subs}" if subs else ""))
    return "\n".join(lines) or "(categories not synced)"


def paper_body(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.65)]
    rest = text[len(head):]
    parts = [rest[i:i + 1500] for i in range(0, len(rest), 1500)]
    budget = max_chars - len(head)
    picked, total = [], 0
    for i, score in BM25(parts).top(SIGNAL_QUERY, len(parts)):
        if score <= 0 or total + len(parts[i]) > budget:
            continue
        picked.append(i)
        total += len(parts[i])
    return head + "\n[...]\n" + "\n[...]\n".join(parts[i] for i in sorted(picked))


def extract_hypotheses(store: Store, llm: OpenRouter, cfg, paper_id: str) -> list[int]:
    doc = store.document(paper_id)
    if not doc:
        raise KeyError(paper_id)
    cats = store.kv_get("data_categories") or []
    body = paper_body(doc["text"], int(cfg.get("generation.paper_max_chars", 120000)))
    max_h = int(cfg.get("generation.max_hypotheses_per_paper", 6))
    user = render(cfg.prompt("extract_hypotheses"), categories=categories_text(cats), title=doc["title"],
                  text=body, max=max_h)
    min_ctx = int(len(user) / 3.2) + 12000
    res = llm.chat_json([{"role": "user", "content": user}], purpose="hypotheses", schema=HYP_SCHEMA,
                        min_context=min_ctx,
                        check=lambda o: None if isinstance(o, dict) and o.get("hypotheses") else "no hypotheses found")
    ids = []
    for h in res.obj["hypotheses"][:max_h]:
        if not isinstance(h, dict) or not h.get("title"):
            continue
        if cats:
            fixed = []
            for c in h.get("candidate_categories") or []:
                cid, _ = _match_category(str(c), cats)
                if cid and cid not in fixed:
                    fixed.append(cid)
            h["candidate_categories"] = fixed
        ids.append(store.add_hypothesis(paper_id, h))
        console.print(f"  hypothesis #{ids[-1]}: {esc(h['title'])}  ({esc(', '.join(h.get('candidate_categories') or []))})")
    summary = res.obj.get("paper_summary")
    if summary:
        meta = (store.document(paper_id) or {}).get("meta") or {}
        store.db.execute("UPDATE documents SET meta=? WHERE id=?", (json.dumps({**meta, "summary": summary}), paper_id))
        store.db.commit()
    return ids
