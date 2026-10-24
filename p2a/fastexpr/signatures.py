"""Derive operator signatures from the live BRAIN operator catalog.

Every operator returned by GET /operators carries a free-text `definition`, e.g.
    "add(x, y, filter = false), x + y"
    "ts_backfill(x,lookback = d, k=1)"
    "bucket(rank(x), range=“0, 1, 0.1”, ...)\nor\nbucket(rank(x), buckets = ...)"
    "input1 < input2"
Nothing about individual operators is hard-coded here: arity, keyword parameters,
defaults, variadic-ness and infix symbols are all parsed from that text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_QUOTES = {"“": '"', "”": '"', "‘": "'", "’": "'"}
_INFIX = re.compile(r"([A-Za-z_]\w*)\s*(<=|>=|==|!=|&&|\|\||<|>|\+|-|\*|/|\^)\s*([A-Za-z_]\w*)")
_VARIADIC_TEXT = re.compile(r"two or more|at least 2|at least two|2 or more|multiple inputs", re.I)


class Symbol(str):
    """A bare identifier used as a default value in a definition (e.g. `driver = gaussian`)."""


@dataclass
class OperatorSig:
    name: str
    category: str
    scope: list[str]
    definition: str
    description: str
    level: str | None = None
    documentation: str | None = None
    positional: list[str] = field(default_factory=list)
    keywords: dict[str, object] = field(default_factory=dict)
    variadic: bool = False
    infix: list[str] = field(default_factory=list)
    call_form: bool = True

    @property
    def min_args(self) -> int:
        return len(self.positional)

    @property
    def max_args(self) -> int | None:
        return None if self.variadic else len(self.positional) + len(self.keywords)

    @property
    def param_order(self) -> list[str]:
        return self.positional + list(self.keywords)

    def usage(self) -> str:
        parts = list(self.positional)
        if self.variadic:
            parts.append("...")
        for k, v in self.keywords.items():
            parts.append(f"{k}={_fmt_default(v)}")
        text = f"{self.name}({', '.join(parts)})" if self.call_form else ""
        if self.infix:
            text = (text + " or " if text else "") + f"x {self.infix[0]} y"
        return text

    def short_description(self, limit: int = 160) -> str:
        d = re.sub(r"\s+", " ", self.description or "").strip()
        if "Input:" in d:
            d = d.split("Input:")[0].strip()
        if len(d) <= limit:
            return d
        cut = d[:limit]
        stop = max(cut.rfind(". "), cut.rfind("; "))
        return (cut[:stop + 1] if stop > 60 else cut.rstrip() + "...").strip()


def _fmt_default(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Symbol):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, float) and v.is_integer():
        return str(int(v)) if abs(v) < 1e15 else str(v)
    return str(v)


def _normalise(text: str) -> str:
    for a, b in _QUOTES.items():
        text = text.replace(a, b)
    return text


def _find_call_forms(defn: str, name: str) -> list[tuple[int, int, str]]:
    """Return (start, end, inner_args) for every `name(...)` in the definition."""
    out = []
    for m in re.finditer(rf"\b{re.escape(name)}\s*\(", defn, re.I):
        depth, j, quote = 0, m.end() - 1, None
        while j < len(defn):
            ch = defn[j]
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    out.append((m.start(), j + 1, defn[m.end():j]))
                    break
            j += 1
    return out


def _split_args(inner: str) -> list[str]:
    parts, depth, quote, cur = [], 0, None, []
    for ch in inner:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _parse_default(text: str):
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(t) if any(c in t for c in ".eE") else int(t)
    except ValueError:
        return Symbol(t)


def parse_operator(op: dict) -> OperatorSig:
    name = op["name"]
    defn = _normalise(op.get("definition") or "")
    sig = OperatorSig(
        name=name,
        category=op.get("category") or "",
        scope=list(op.get("scope") or []),
        definition=defn,
        description=op.get("description") or "",
        level=op.get("level"),
        documentation=op.get("documentation"),
    )
    forms = _find_call_forms(defn, name)
    sig.call_form = bool(forms)
    seen_kw: dict[str, object] = {}
    positional: list[str] | None = None
    for _, _, inner in forms:
        pos: list[str] = []
        for raw in _split_args(inner):
            token = raw.strip()
            if token in ("...", "..", "…"):
                sig.variadic = True
                continue
            if token.endswith(".."):
                sig.variadic = True
                token = token.rstrip(". ").strip()
                if not token:
                    continue
            if "=" in token and "==" not in token:
                k, v = token.split("=", 1)
                k = re.sub(r"\s+", "", k)
                seen_kw.setdefault(k, _parse_default(v))
                continue
            ids = re.findall(r"[A-Za-z_]\w*", token)
            if "(" in token and ids:
                pname = ids[-1]          # e.g. bucket(rank(x), ...) -> x
            elif ids:
                pname = "".join(token.split())  # "input 3" -> "input3"
            else:
                pname = "x"              # literal placeholder, e.g. ts_step(1)
            pos.append(pname)
        if positional is None or len(pos) < len(positional):
            positional = pos
    sig.positional = positional or []
    sig.keywords = seen_kw

    rest = defn
    for start, end, _ in sorted(forms, reverse=True):
        rest = rest[:start] + " " + rest[end:]
    for m in _INFIX.finditer(rest):
        if m.group(2) not in sig.infix:
            sig.infix.append(m.group(2))
    if not sig.call_form and sig.infix:
        sig.positional = ["input1", "input2"]
    if _VARIADIC_TEXT.search(sig.description or ""):
        sig.variadic = True
    return sig


def enum_words(sig: OperatorSig) -> set[str]:
    """Words an operator accepts as symbolic option values (e.g. gaussian, cauchy)."""
    text = f"{sig.definition} {sig.description}"
    return {w.lower() for w in re.findall(r"[A-Za-z_]\w*", text)}
