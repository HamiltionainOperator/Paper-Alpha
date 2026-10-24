"""The construction playbook (research/operator_playbook.yaml): which operators a field's structure calls for, how to
lower production correlation and how to raise fitness, from BRAIN's documentation, the literature and this engine's
own measurements. The generator and the refiner put the rules that fit the fields in front of the LLM, so it builds
alphas for the data it is given (sparse fields carried forward or traded as events, vectors reduced, noisy daily
data smoothed, peer-relative signals grouped) instead of rank(field).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_CACHE: dict = {}

# words in a field's description that mark data that changes rarely or on events
_SPARSE = re.compile(r"\b(quarter\w*|annual\w*|yearly|monthly|filing\w*|10-?k|10-?q|8-?k|event\w*|announce\w*|"
                     r"transaction\w*|deal\w*|report\w*|patent\w*|board|director\w*|insider\w*|holding\w*|"
                     r"rating\w*|call|transcript\w*|dividend\w*)\b", re.I)


def load(cfg) -> dict:
    path = Path(cfg.get("playbook.path", "research/operator_playbook.yaml"))
    if not path.is_absolute():
        path = cfg.root / path
    key = str(path)
    mtime = path.stat().st_mtime if path.exists() else None
    if key not in _CACHE or _CACHE[key][0] != mtime:
        _CACHE[key] = (mtime, (yaml.safe_load(path.read_text()) or {}) if path.exists() else {})
    return _CACHE[key][1]


def field_tags(f: dict) -> set:
    """What a field is, in the playbook's terms: its type, category and whether it changes rarely."""
    tags = {"any"}
    ftype = (f.get("type") or "MATRIX").lower()
    tags.add(ftype)
    if f.get("category"):
        tags.add(str(f["category"]).lower())
    desc = f"{f.get('id', '')} {f.get('description') or ''}"
    dc = f.get("date_coverage")
    if _SPARSE.search(desc.replace("_", " ")) or (dc is not None and dc < 0.6):
        tags.add("sparse")
    if f.get("category") in ("news", "sentiment", "socialmedia"):
        tags.add("event")
    return tags


def rules_for(cfg, fields: list[dict], n: int | None = None) -> list[dict]:
    data = load(cfg)
    tags = set().union(*(field_tags(f) for f in fields)) if fields else {"any"}
    n = int(n or cfg.get("playbook.rules_in_prompt", 10))
    scored = []
    for i, r in enumerate(data.get("rules") or []):
        want = {str(t).lower() for t in r.get("tags") or ["any"]}
        hit = len(want & tags - {"any"})
        if hit or "any" in want:
            scored.append((-hit, i, r))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in scored[:n]]


def playbook_text(cfg, fields: list[dict], n: int | None = None) -> str:
    data = load(cfg)
    if not data:
        return "(no playbook)"
    lines = []
    for r in rules_for(cfg, fields, n):
        tpl = f" e.g. `{r['template']}`" if r.get("template") else ""
        lines.append(f"- [{', '.join(r.get('tags') or ['any'])}] {r['rule']}{tpl}")
    k = int(cfg.get("playbook.techniques_in_prompt", 4))
    for title, key in (("Lower production correlation", "uniqueness"), ("Raise fitness", "fitness")):
        items = (data.get(key) or [])[:k]
        if items:
            lines.append(f"{title}:")
            lines += [f"  - {t['technique']}: {t['how']}" + (f" e.g. `{t['template']}`" if t.get("template") else "")
                      for t in items]
    return "\n".join(lines) or "(no playbook rules fit these fields)"
