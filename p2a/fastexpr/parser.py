"""Pratt parser for Fast Expression programs."""
from __future__ import annotations

from .ast import Assign, BinOp, Call, Ident, KwArg, Num, Program, Str, Ternary, UnaryOp
from .lexer import FastExprSyntaxError, Token, tokenize

# (left binding power, right binding power); right < left means right-associative.
BINARY_BP = {
    "||": (2, 3),
    "&&": (4, 5),
    "==": (6, 7), "!=": (6, 7),
    "<": (8, 9), ">": (8, 9), "<=": (8, 9), ">=": (8, 9),
    "+": (10, 11), "-": (10, 11),
    "*": (12, 13), "/": (12, 13),
    "^": (15, 14),
}
TERNARY_BP = 1
PREFIX_BP = 14
PREFIX_OPS = ("-", "+", "!")


class Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = tokenize(source)
        self.i = 0

    # -- token helpers -------------------------------------------------
    @property
    def tok(self) -> Token:
        return self.tokens[self.i]

    def peek(self, k: int = 1) -> Token:
        return self.tokens[min(self.i + k, len(self.tokens) - 1)]

    def advance(self) -> Token:
        t = self.tokens[self.i]
        if t.kind != "EOF":
            self.i += 1
        return t

    def is_op(self, text: str, tok: Token | None = None) -> bool:
        t = tok or self.tok
        return t.kind == "OP" and t.text == text

    def expect_op(self, text: str, context: str = "") -> Token:
        if not self.is_op(text):
            got = self.tok.text or "end of input"
            raise self.error(f"expected '{text}'{context}, got '{got}'")
        return self.advance()

    def error(self, msg: str, tok: Token | None = None) -> FastExprSyntaxError:
        t = tok or self.tok
        return FastExprSyntaxError(msg, t.line, t.col, self.source)

    # -- grammar -------------------------------------------------------
    def parse_program(self) -> Program:
        statements = []
        while self.tok.kind != "EOF":
            if self.is_op(";"):
                self.advance()
                continue
            statements.append(self.parse_statement())
            if self.tok.kind != "EOF":
                if not self.is_op(";"):
                    raise self.error(f"expected ';' or end of expression, got '{self.tok.text}'")
        if not statements:
            raise FastExprSyntaxError("empty expression", 1, 1, self.source)
        return Program(statements=statements, source=self.source)

    def parse_statement(self):
        t = self.tok
        if t.kind == "ID" and self.is_op("=", self.peek()):
            self.advance()
            self.advance()
            if self.tok.kind == "EOF" or self.is_op(";"):
                raise self.error(f"missing value in assignment to '{t.text}'")
            return Assign(line=t.line, col=t.col, name=t.text, value=self.parse_expr(0))
        return self.parse_expr(0)

    def parse_expr(self, min_bp: int):
        left = self.parse_prefix()
        while True:
            t = self.tok
            if t.kind != "OP":
                break
            if t.text == "?":
                if TERNARY_BP <= min_bp:
                    break
                self.advance()
                then = self.parse_expr(0)
                self.expect_op(":", " in conditional expression")
                other = self.parse_expr(0)
                left = Ternary(line=t.line, col=t.col, cond=left, then=then, other=other)
                continue
            bp = BINARY_BP.get(t.text)
            if bp is None or bp[0] <= min_bp:
                break
            self.advance()
            if self.tok.kind == "EOF" or (self.tok.kind == "OP" and self.tok.text in (")", ",", ";")):
                raise self.error(f"missing right operand for '{t.text}'")
            right = self.parse_expr(bp[1])
            left = BinOp(line=t.line, col=t.col, op=t.text, left=left, right=right)
        return left

    def parse_prefix(self):
        t = self.tok
        if t.kind == "NUM":
            self.advance()
            return Num(line=t.line, col=t.col, value=float(t.text), text=t.text)
        if t.kind == "STR":
            self.advance()
            return Str(line=t.line, col=t.col, value=t.text)
        if t.kind == "ID":
            self.advance()
            if self.is_op("("):
                return self.parse_call(t)
            return Ident(line=t.line, col=t.col, name=t.text)
        if t.kind == "OP" and t.text == "(":
            self.advance()
            if self.is_op(")"):
                raise self.error("empty parentheses")
            inner = self.parse_expr(0)
            if not self.is_op(")"):
                raise self.error(f"expected ')' to close '(' opened at line {t.line}, col {t.col}, got '{self.tok.text or 'end of input'}'")
            self.advance()
            return inner
        if t.kind == "OP" and t.text in PREFIX_OPS:
            self.advance()
            if self.tok.kind == "EOF":
                raise self.error(f"missing operand after '{t.text}'")
            return UnaryOp(line=t.line, col=t.col, op=t.text, operand=self.parse_expr(PREFIX_BP))
        if t.kind == "EOF":
            raise self.error("unexpected end of expression")
        raise self.error(f"unexpected '{t.text}'")

    def parse_call(self, name_tok: Token) -> Call:
        open_tok = self.advance()  # '('
        args, kwargs = [], []
        if self.is_op(")"):
            self.advance()
            return Call(line=name_tok.line, col=name_tok.col, name=name_tok.text, args=args, kwargs=kwargs)
        while True:
            t = self.tok
            if t.kind == "ID" and self.is_op("=", self.peek()):
                self.advance()
                self.advance()
                kwargs.append(KwArg(name=t.text, value=self.parse_expr(0), line=t.line, col=t.col))
            else:
                if kwargs:
                    raise self.error(f"positional argument after keyword argument in {name_tok.text}()")
                if self.is_op(",") or self.is_op(")"):
                    raise self.error(f"missing argument in {name_tok.text}()")
                args.append(self.parse_expr(0))
            if self.is_op(","):
                self.advance()
                if self.is_op(")"):
                    raise self.error(f"trailing comma in {name_tok.text}()")
                continue
            if self.is_op(")"):
                self.advance()
                break
            raise self.error(
                f"expected ',' or ')' in {name_tok.text}() opened at line {open_tok.line}, col {open_tok.col}, "
                f"got '{self.tok.text or 'end of input'}'")
        return Call(line=name_tok.line, col=name_tok.col, name=name_tok.text, args=args, kwargs=kwargs)


def parse(source: str) -> Program:
    return Parser(source).parse_program()
