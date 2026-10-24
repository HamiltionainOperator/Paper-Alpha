"""Retrieval over papers, BRAIN docs, datasets and data fields."""
from __future__ import annotations

import math
import re

from ..store import Store
from .bm25 import BM25


def paper_excerpts(store: Store, paper_id: str, query: str, max_chars: int) -> str:
    chunks = store.chunks(doc_id=paper_id)
    if not chunks:
        return ""
    head = chunks[0]["text"]  # title + abstract live at the top
    picked, total = {0}, len(head)
    if len(chunks) > 1:
        bm = BM25([c["text"] for c in chunks])
        for i, score in bm.top(query, len(chunks)):
            if score <= 0 or total >= max_chars:
                break
            if i in picked:
                continue
            picked.add(i)
            total += len(chunks[i]["text"])
    text = "\n[...]\n".join(chunks[i]["text"] for i in sorted(picked))
    return text[:max_chars]


def doc_snippets(store: Store, query: str, kind: str = "brain_doc", k: int = 3, max_chars: int = 2400) -> list[tuple[str, str]]:
    chunks = store.chunks(kind=kind)
    if not chunks:
        return []
    bm = BM25([f"{c['title']} {c['text']}" for c in chunks])
    out, total = [], 0
    for i, score in bm.top(query, k * 3):
        if score <= 0:
            break
        c = chunks[i]
        if total + len(c["text"]) > max_chars:
            continue
        out.append((c["title"], c["text"]))
        total += len(c["text"])
        if len(out) >= k:
            break
    return out


def rank_datasets(rows: list[dict], query: str) -> list[tuple[dict, float]]:
    """BM25 relevance to the hypothesis, nudged toward under-used, well-covered datasets."""
    if not rows:
        return []
    bm = BM25([f"{r.get('name', '')} {r.get('description', '')} {r.get('subcategory', '')} {r['id']}" for r in rows])
    rel = bm.scores(query)
    top = max(rel) or 1.0
    scored = []
    for r, s in zip(rows, rel):
        crowd = math.log10(1 + (r.get("alpha_count") or 0))           # crowded datasets correlate with prod
        novelty = 1.0 / (1.0 + crowd / 3.0)
        coverage = r.get("coverage") or 0.5
        scored.append((r, 0.75 * s / top + 0.15 * novelty + 0.10 * coverage))
    return sorted(scored, key=lambda x: x[1], reverse=True)


def shortlist_fields(rows: list[dict], query: str, k: int, min_coverage: float,
                     technical_patterns: list[str]) -> list[dict]:
    tech = [re.compile(p, re.I) for p in technical_patterns]
    usable = [r for r in rows
              if (r.get("coverage") is None or r["coverage"] >= min_coverage)
              and not any(p.search(r.get("description") or "") or p.search(r["id"]) for p in tech)]
    if not usable:
        return []
    bm = BM25([f"{r['id']} {r.get('description') or ''}" for r in usable])
    sc = bm.scores(query)
    order = sorted(range(len(usable)), key=lambda i: (sc[i], usable[i].get("coverage") or 0), reverse=True)
    picked = [usable[i] for i in order[:k]]
    # keep a few vector fields in view if the dataset is mostly event data
    vec = [usable[i] for i in order if (usable[i].get("type") or "").upper() == "VECTOR" and usable[i] not in picked]
    if vec and not any((p.get("type") or "").upper() == "VECTOR" for p in picked):
        picked = picked[:-3] + vec[:3]
    return picked
