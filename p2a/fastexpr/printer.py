"""Canonical, precedence-aware printing of Fast Expression ASTs."""
from __future__ import annotations

from .ast import Assign, BinOp, Call, Ident, Num, Program, Str, Ternary, UnaryOp

PREC = {"||": 2, "&&": 4, "==": 6, "!=": 6, "<": 8, ">": 8, "<=": 8, ">=": 8,
        "+": 10, "-": 10, "*": 12, "/": 12, "^": 15}
UNARY_PREC = 14


def fmt_number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return ("%.12f" % value).rstrip("0").rstrip(".")


def _fmt(node, catalog, parent: int = 0, right: bool = False) -> str:
    if isinstance(node, Num):
        return fmt_number(node.value)
    if isinstance(node, Str):
        return '"' + node.value.replace('"', "'") + '"'
    if isinstance(node, Ident):
        return node.name
    if isinstance(node, Call):
        sig = catalog.op(node.name) if catalog is not None else None
        name = sig.name if sig else node.name
        kwnames = {k.lower(): k for k in (sig.keywords if sig else {})}
        parts = [_fmt(a, catalog) for a in node.args]
        parts += [f"{kwnames.get(k.name.lower(), k.name)}={_fmt(k.value, catalog)}" for k in node.kwargs]
        return f"{name}({', '.join(parts)})"
    if isinstance(node, BinOp):
        p = PREC.get(node.op, 10)
        text = f"{_fmt(node.left, catalog, p)} {node.op} {_fmt(node.right, catalog, p, right=True)}"
        return f"({text})" if p < parent or (right and p == parent) else text
    if isinstance(node, UnaryOp):
        inner = node.operand
        body = _fmt(inner, catalog, UNARY_PREC)
        if isinstance(inner, UnaryOp) or (isinstance(inner, (BinOp, Ternary)) and not body.startswith("(")):
            body = f"({body})"
        return f"{node.op}{body}"
    if isinstance(node, Ternary):
        text = f"{_fmt(node.cond, catalog, 1)} ? {_fmt(node.then, catalog)} : {_fmt(node.other, catalog)}"
        return f"({text})" if parent > 0 else text
    if isinstance(node, Assign):
        return f"{node.name} = {_fmt(node.value, catalog)}"
    raise TypeError(f"cannot print {type(node).__name__}")


def to_source(program: Program, catalog=None, sep: str = "; ") -> str:
    return sep.join(_fmt(s, catalog) for s in program.statements)
