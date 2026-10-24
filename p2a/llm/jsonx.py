"""Robust JSON extraction from LLM output."""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def _loads(s: str):
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        pass
    repaired = re.sub(r",\s*([}\]])", r"\1", s)
    repaired = repaired.replace("\u201c", '\\"').replace("\u201d", '\\"')
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, TypeError):
        return None


def _balanced(s: str, open_c: str, close_c: str):
    """Yield balanced {...} / [...] substrings, longest first, respecting strings."""
    found = []
    for start in [i for i, ch in enumerate(s) if ch == open_c]:
        depth, in_str, esc = 0, False, False
        for j in range(start, len(s)):
            ch = s[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_c:
                depth += 1
            elif ch == close_c:
                depth -= 1
                if depth == 0:
                    found.append(s[start:j + 1])
                    break
    return sorted(found, key=len, reverse=True)


def _match_brace(s: str, start: int) -> int:
    depth, in_str, esc = 0, False, False
    for j in range(start, len(s)):
        ch = s[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def salvage_list(text: str | None, keys=("candidates", "hypotheses")):
    """Recover the complete objects of a truncated `{"key": [{...}, {...}, {..` response."""
    if not text:
        return None
    t = _THINK.sub("", text)
    for key in keys:
        i = t.find(f'"{key}"')
        if i < 0:
            continue
        k = t.find("[", i)
        if k < 0:
            continue
        items, k = [], k + 1
        while True:
            while k < len(t) and t[k] in " \n\r\t,":
                k += 1
            if k >= len(t) or t[k] != "{":
                break
            end = _match_brace(t, k)
            if end < 0:
                break
            obj = _loads(t[k:end + 1])
            if obj is None:
                break
            items.append(obj)
            k = end + 1
        if items:
            return {key: items}
    return None


def extract_json(text: str | None):
    if not text:
        return None
    t = _THINK.sub("", text).strip()
    candidates = [m.group(1) for m in _FENCE.finditer(t)] + [t]
    for c in candidates:
        obj = _loads(c.strip())
        if obj is not None:
            return obj
    for c in candidates:
        for open_c, close_c in (("{", "}"), ("[", "]")):
            for blob in _balanced(c, open_c, close_c)[:5]:
                obj = _loads(blob)
                if obj is not None:
                    return obj
    return None
