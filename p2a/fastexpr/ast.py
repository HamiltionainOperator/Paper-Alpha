"""AST node types for Fast Expression programs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Node:
    line: int
    col: int


@dataclass
class Num(Node):
    value: float = 0.0
    text: str = "0"


@dataclass
class Str(Node):
    value: str = ""


@dataclass
class Ident(Node):
    name: str = ""


@dataclass
class KwArg:
    name: str
    value: Node
    line: int
    col: int


@dataclass
class Call(Node):
    name: str = ""
    args: list[Node] = field(default_factory=list)
    kwargs: list[KwArg] = field(default_factory=list)


@dataclass
class BinOp(Node):
    op: str = "+"
    left: Node | None = None
    right: Node | None = None


@dataclass
class UnaryOp(Node):
    op: str = "-"
    operand: Node | None = None


@dataclass
class Ternary(Node):
    cond: Node | None = None
    then: Node | None = None
    other: Node | None = None


@dataclass
class Assign(Node):
    name: str = ""
    value: Node | None = None


@dataclass
class Program:
    statements: list[Node]
    source: str


def walk(node):
    """Yield every node in the subtree (pre-order)."""
    yield node
    if isinstance(node, Program):
        for s in node.statements:
            yield from walk(s)
    elif isinstance(node, Call):
        for a in node.args:
            yield from walk(a)
        for kw in node.kwargs:
            yield from walk(kw.value)
    elif isinstance(node, BinOp):
        yield from walk(node.left)
        yield from walk(node.right)
    elif isinstance(node, UnaryOp):
        yield from walk(node.operand)
    elif isinstance(node, Ternary):
        yield from walk(node.cond)
        yield from walk(node.then)
        yield from walk(node.other)
    elif isinstance(node, Assign):
        yield from walk(node.value)
