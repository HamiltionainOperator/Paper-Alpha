"""Tokenizer for WorldQuant BRAIN Fast Expression (FASTEXPR).

Syntax facts (from the BRAIN "Introduction to BRAIN Expression Language" page and
observed platform behaviour): statements are separated by ';', the last statement is
the alpha, '/* ... */' block comments and '#' line comments are ignored, keyword
arguments use 'name=value', strings use double or single quotes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class FastExprSyntaxError(Exception):
    def __init__(self, message: str, line: int, col: int, source: str | None = None):
        self.message = message
        self.line = line
        self.col = col
        self.source = source
        super().__init__(self.render())

    def render(self) -> str:
        loc = f"line {self.line}, col {self.col}"
        if not self.source:
            return f"{self.message} ({loc})"
        lines = self.source.splitlines() or [""]
        src_line = lines[self.line - 1] if 0 < self.line <= len(lines) else ""
        return f"{self.message} ({loc})\n    {src_line}\n    {' ' * max(self.col - 1, 0)}^"


@dataclass(frozen=True)
class Token:
    kind: str  # NUM | STR | ID | OP | EOF
    text: str
    line: int
    col: int


# Longest symbols first so '<=' wins over '<'.
SYMBOLS = ("&&", "||", "<=", ">=", "==", "!=", "<", ">", "+", "-", "*", "/", "^", "!", "?", ":", "=", "(", ")", ",", ";")

_NUM = re.compile(r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Characters that LLMs (and the BRAIN docs themselves) emit but the simulator rejects.
_SANITIZE = {
    "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
    "–": "-", "—": "-", "−": "-", " ": " ", " ": " ",
    " ": " ", "​": "", "﻿": "",
}


def sanitize(text: str) -> tuple[str, list[str]]:
    """Normalise typography and strip markdown wrappers. Returns (clean, fixes)."""
    fixes: list[str] = []
    out = text
    for bad, good in _SANITIZE.items():
        if bad in out:
            fixes.append(f"replaced U+{ord(bad):04X} with {good!r}")
            out = out.replace(bad, good)
    stripped = out.strip()
    if stripped.startswith("```"):
        body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
        out = body
        fixes.append("removed markdown code fence")
    elif len(stripped) > 1 and stripped.startswith("`") and stripped.endswith("`"):
        out = stripped.strip("`")
        fixes.append("removed backticks")
    return out.strip(), fixes


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i, line, col, n = 0, 1, 1, len(src)

    def err(msg: str, ln: int = None, cl: int = None) -> FastExprSyntaxError:
        return FastExprSyntaxError(msg, ln or line, cl or col, src)

    while i < n:
        c = src[i]
        if c == "\n":
            i, line, col = i + 1, line + 1, 1
            continue
        if c.isspace():
            i, col = i + 1, col + 1
            continue
        if c == "#":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            if end == -1:
                raise err("unterminated block comment '/*'")
            chunk = src[i:end + 2]
            nl = chunk.count("\n")
            if nl:
                line += nl
                col = len(chunk) - chunk.rfind("\n")
            else:
                col += len(chunk)
            i = end + 2
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            m = _NUM.match(src, i)
            tokens.append(Token("NUM", m.group(0), line, col))
            col += len(m.group(0))
            i = m.end()
            if i < n and (src[i].isalpha() or src[i] == "_"):
                raise err(f"invalid number literal '{m.group(0)}{src[i]}'")
            continue
        if c.isalpha() or c == "_":
            m = _ID.match(src, i)
            tokens.append(Token("ID", m.group(0), line, col))
            col += len(m.group(0))
            i = m.end()
            continue
        if c in "\"'":
            j = src.find(c, i + 1)
            if j == -1 or "\n" in src[i:j]:
                raise err("unterminated string literal")
            tokens.append(Token("STR", src[i + 1:j], line, col))
            col += j - i + 1
            i = j + 1
            continue
        for sym in SYMBOLS:
            if src.startswith(sym, i):
                tokens.append(Token("OP", sym, line, col))
                i += len(sym)
                col += len(sym)
                break
        else:
            raise err(f"unexpected character {c!r}")
    tokens.append(Token("EOF", "", line, col))
    return tokens
