"""Static analysis of Fast Expression programs against the live BRAIN catalog.

This is the anti-hallucination gate: every operator, keyword, data field and type is
checked against what the platform actually exposes (GET /operators, /data-fields)
before a single simulation is spent.

Operator counting follows the platform's `operatorCount` (calibrated against real
alphas): each function call counts 1, each binary infix operator counts 1, unary
minus counts 1 unless it negates a numeric literal, comments and assignments count 0,
and variables are not inlined (operators are counted where they are written).
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .ast import Assign, BinOp, Call, Ident, Num, Program, Str, Ternary, UnaryOp
from .lexer import FastExprSyntaxError, sanitize
from .parser import parse
from .signatures import OperatorSig, Symbol, enum_words, parse_operator

ERROR, WARNING = "error", "warning"
MATRIX, VECTOR, GROUP, CONST, STR, UNKNOWN = "MATRIX", "VECTOR", "GROUP", "CONST", "STR", "UNKNOWN"


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    line: int = 0
    col: int = 0
    hint: str = ""
    subject: str = ""

    def render(self) -> str:
        loc = f" (line {self.line}, col {self.col})" if self.line else ""
        text = f"{self.code}: {self.message}{loc}"
        if self.hint:
            text += f" -> {self.hint}"
        return text


@dataclass
class FieldInfo:
    id: str
    type: str = MATRIX
    dataset: str | None = None
    category: str | None = None
    coverage: float | None = None
    description: str = ""


@dataclass
class Rules:
    """Language rules. Loaded from the `fastexpr` section of config.yaml."""
    scope: str = "REGULAR"
    group_param_names: set = field(default_factory=lambda: {"group", "g1", "g2"})
    lookback_param_names: set = field(default_factory=lambda: {"d", "lookback", "nlength"})
    integer_param_names: set = field(default_factory=lambda: {"k", "nth", "rettype", "lag"})
    vector_categories: set = field(default_factory=lambda: {"Vector"})
    type_overrides: dict = field(default_factory=dict)
    infix_aliases: dict = field(default_factory=lambda: {"&&": "and", "||": "or", "!": "not", "unary-": "reverse"})
    allow_ternary: bool = False
    allow_power_symbol: bool = False
    backfill_operators: set = field(default_factory=lambda: {"ts_backfill", "group_backfill"})
    max_lookback: int = 2520
    min_coverage_warn: float = 0.5
    literal_words: dict = field(default_factory=lambda: {"nan": CONST, "true": CONST, "false": CONST, "inf": CONST})
    group_hierarchy: list = field(default_factory=lambda: ["subindustry", "industry", "sector", "market"])
    group_aggregators: set = field(default_factory=lambda: {"group_mean"})
    group_transforms: set = field(default_factory=lambda: {"group_rank", "group_zscore", "group_scale",
                                                           "group_neutralize", "group_normalize"})

    @classmethod
    def from_config(cls, cfg: dict | None) -> "Rules":
        r = cls()
        for key, val in (cfg or {}).items():
            if not hasattr(r, key):
                continue
            cur = getattr(r, key)
            setattr(r, key, set(val) if isinstance(cur, set) else val)
        return r


@dataclass
class Constraints:
    max_ops: int | None = None
    excluded_ops: set = field(default_factory=set)
    max_fields: int | None = None
    grouping_fields: set = field(default_factory=set)
    allowed_categories: set | None = None
    allowed_datasets: set | None = None
    single_category: bool = False
    single_dataset: bool = False
    count_grouping_categories: bool = False   # theme matching counts grouping fields' own category
    label: str = ""


class Catalog:
    """In-memory view of operators + data fields for one simulation scope."""

    def __init__(self, operators: Iterable[dict], rules: Rules | None = None,
                 fields: Iterable[FieldInfo] = (), field_lookup: Callable[[str], FieldInfo | None] | None = None):
        self.rules = rules or Rules()
        self.all_ops: dict[str, OperatorSig] = {}
        for o in operators:
            sig = parse_operator(o)
            self.all_ops[sig.name.lower()] = sig
        self.ops = {k: v for k, v in self.all_ops.items() if self.rules.scope in v.scope}
        self.infix: dict[str, str] = {}
        for sig in self.ops.values():
            for sym in sig.infix:
                self.infix.setdefault(sym, sig.name)
        for sym, opname in self.rules.infix_aliases.items():
            if opname.lower() in self.ops:
                self.infix.setdefault(sym, self.ops[opname.lower()].name)
        self.fields: dict[str, FieldInfo] = {}
        self._lower: dict[str, str] = {}
        self.add_fields(fields)
        self._lookup = field_lookup
        self._missing: set[str] = set()

    def add_fields(self, fields: Iterable[FieldInfo]) -> None:
        for f in fields:
            self.fields[f.id] = f
            self._lower.setdefault(f.id.lower(), f.id)

    def op(self, name: str) -> OperatorSig | None:
        return self.ops.get(name.lower())

    def op_any(self, name: str) -> OperatorSig | None:
        return self.all_ops.get(name.lower())

    def field(self, name: str) -> FieldInfo | None:
        f = self.fields.get(name)
        if f is None and self._lookup and name not in self._missing:
            f = self._lookup(name)
            if f is not None:
                self.add_fields([f])  # known under its canonical id; also feeds suggest_fields
                if f.id != name:      # e.g. wrong letter case: reject, the hint will name the exact id
                    f = None
            if f is None:
                self._missing.add(name)
        return f

    def suggest_ops(self, name: str, n: int = 4) -> list[str]:
        names = [s.name for s in self.ops.values()]
        out = difflib.get_close_matches(name.lower(), names, n=n, cutoff=0.55)
        stem = name.lower().split("_")[0]
        out += [m for m in names if m.startswith(stem + "_") and m not in out][: max(0, n - len(out))]
        return out[:n]

    def suggest_fields(self, name: str, n: int = 4) -> list[str]:
        exact = self._lower.get(name.lower())
        if exact:
            return [exact]
        return difflib.get_close_matches(name, list(self.fields), n=n, cutoff=0.6)

    def ops_in_categories(self, cats: set) -> list[str]:
        return sorted(s.name for s in self.ops.values() if s.category in cats)


@dataclass
class Analysis:
    source: str
    clean: str = ""
    issues: list[Issue] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    program: Program | None = None
    operators: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    field_info: dict[str, FieldInfo] = field(default_factory=dict)
    lookbacks: list[int] = field(default_factory=list)
    lookback_nodes: list = field(default_factory=list)
    group_level: str | None = None   # e.g. "industry": the alpha is constant within each industry
    canonical: str = ""
    constraints: Constraints | None = None

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def ok(self) -> bool:
        return self.program is not None and not self.errors

    @property
    def op_count(self) -> int:
        return len(self.operators)

    def pp_op_count(self, excluded: set | None = None) -> int:
        ex = {e.lower() for e in (excluded if excluded is not None else (self.constraints.excluded_ops if self.constraints else set()))}
        return sum(1 for o in self.operators if o.lower() not in ex)

    def counted_fields(self, grouping: set | None = None) -> list[str]:
        g = grouping if grouping is not None else (self.constraints.grouping_fields if self.constraints else set())
        return [f for f in self.fields if f not in g]

    def categories(self, grouping: set | None = None) -> list[str]:
        return sorted({self.field_info[f].category for f in self.counted_fields(grouping)
                       if f in self.field_info and self.field_info[f].category})

    def datasets(self, grouping: set | None = None) -> list[str]:
        return sorted({self.field_info[f].dataset for f in self.counted_fields(grouping)
                       if f in self.field_info and self.field_info[f].dataset})

    def report(self) -> str:
        lines = [i.render() for i in self.issues]
        return "\n".join(lines) if lines else "OK"


class _Walker:
    def __init__(self, catalog: Catalog, an: Analysis):
        self.cat = catalog
        self.rules = catalog.rules
        self.an = an
        self.vars: dict[str, str] = {}
        self.var_used: set[str] = set()
        self.backfill_depth = 0
        self.backfilled: set[str] = set()

    # -- helpers --------------------------------------------------------
    def issue(self, code, severity, message, node=None, hint="", subject=""):
        line, col = (node.line, node.col) if node is not None and hasattr(node, "line") else (0, 0)
        self.an.issues.append(Issue(code, severity, message, line, col, hint, subject))

    def count(self, opname: str):
        self.an.operators.append(opname)

    def _vector_ops_hint(self) -> str:
        ops = self.cat.ops_in_categories(self.rules.vector_categories)
        return ", ".join(ops[:8])

    def _value_check(self, typ: str, node, context: str):
        if typ == VECTOR:
            name = node.name if isinstance(node, Ident) else "this input"
            self.issue("E_VECTOR", ERROR, f"vector field '{name}' used directly in {context}", node,
                       f"aggregate it first with a vector operator, e.g. vec_avg({name}); available: {self._vector_ops_hint()}",
                       subject=name)
        elif typ == GROUP:
            name = node.name if isinstance(node, Ident) else "a group expression"
            self.issue("E_GROUP_MISUSE", ERROR, f"group field '{name}' used as a numeric input in {context}", node,
                       "group fields may only be passed as the group argument of group_* operators (or bucket/densify)",
                       subject=name)
        elif typ == STR:
            self.issue("E_TYPE", ERROR, f"string literal used as a numeric input in {context}", node,
                       "strings are only valid as keyword option values, e.g. range=\"0.1,1,0.1\"")

    # -- expressions ----------------------------------------------------
    def expr(self, node) -> str:
        if isinstance(node, Num):
            return CONST
        if isinstance(node, Str):
            return STR
        if isinstance(node, Ident):
            return self.ident(node)
        if isinstance(node, UnaryOp):
            return self.unary(node)
        if isinstance(node, BinOp):
            return self.binop(node)
        if isinstance(node, Ternary):
            return self.ternary(node)
        if isinstance(node, Call):
            return self.call(node)
        self.issue("E_SYNTAX", ERROR, f"unsupported construct {type(node).__name__}", node)
        return UNKNOWN

    def ident(self, node: Ident) -> str:
        name = node.name
        if name in self.vars:
            self.var_used.add(name)
            return self.vars[name]
        if name.lower() in self.rules.literal_words:
            return self.rules.literal_words[name.lower()]
        f = self.cat.field(name)
        if f is not None:
            if name not in self.an.field_info:
                self.an.fields.append(name)
                self.an.field_info[name] = f
            if self.backfill_depth:
                self.backfilled.add(name)
            t = (f.type or MATRIX).upper()
            if t not in (MATRIX, VECTOR, GROUP):
                self.issue("E_FIELD_TYPE", ERROR, f"field '{name}' has type {t}, which is not numeric", node,
                           "use a MATRIX (or vec_-aggregated VECTOR) field instead", subject=name)
                return UNKNOWN
            return t
        if self.cat.op(name):
            self.issue("E_UNKNOWN_ID", ERROR, f"'{name}' is an operator used without parentheses", node,
                       f"call it as {self.cat.op(name).usage()}", subject=name)
            return UNKNOWN
        sugg = self.cat.suggest_fields(name)
        hint = f"did you mean: {', '.join(sugg)}" if sugg else "use only data fields from the provided field list"
        self.issue("E_UNKNOWN_FIELD", ERROR, f"'{name}' is not a data field available in this region/delay/universe "
                   "(and not a variable defined earlier)", node, hint, subject=name)
        return UNKNOWN

    def unary(self, node: UnaryOp) -> str:
        if node.op == "-" and isinstance(node.operand, Num):
            return CONST  # negative literal, not an operator
        if node.op == "+":
            return self.expr(node.operand)
        key = "unary-" if node.op == "-" else node.op
        opname = self.rules.infix_aliases.get(key)
        sig = self.cat.op(opname) if opname else None
        if sig is None:
            self.issue("E_OPERATOR", ERROR, f"prefix '{node.op}' has no available operator", node)
        self.count(sig.name if sig else (opname or node.op))
        t = self.expr(node.operand)
        self._value_check(t, node.operand, f"prefix '{node.op}'")
        return CONST if t == CONST else MATRIX

    def binop(self, node: BinOp) -> str:
        opname = self.cat.infix.get(node.op)
        if opname is None:
            if node.op == "^":
                self.issue("E_POLICY", ERROR, "'^' is not a supported infix operator", node,
                           "use power(x, y) or signed_power(x, y)")
            else:
                self.issue("E_OPERATOR", ERROR, f"infix '{node.op}' has no available operator", node)
        self.count(opname or node.op)
        lt = self.expr(node.left)
        rt = self.expr(node.right)
        self._value_check(lt, node.left, f"'{node.op}'")
        self._value_check(rt, node.right, f"'{node.op}'")
        return CONST if lt == CONST and rt == CONST else MATRIX

    def ternary(self, node: Ternary) -> str:
        if not self.rules.allow_ternary:
            self.issue("E_POLICY", ERROR, "conditional 'a ? b : c' is not allowed", node,
                       "use if_else(condition, value_if_true, value_if_false)")
        sig = self.cat.op("if_else")
        self.count(sig.name if sig else "if_else")
        for part in (node.cond, node.then, node.other):
            t = self.expr(part)
            self._value_check(t, part, "conditional")
        return MATRIX

    def _param_role(self, sig: OperatorSig, pname: str, index: int) -> str:
        ov = (self.rules.type_overrides.get(sig.name) or {}).get("params", {})
        if pname in ov:
            return "group" if ov[pname] == GROUP else ov[pname].lower()
        if pname in self.rules.group_param_names:
            return "group"
        if sig.category in self.rules.vector_categories and index == 0:
            return "vector"
        if pname in self.rules.lookback_param_names:
            return "lookback"
        if pname in self.rules.integer_param_names:
            return "int"
        if pname in sig.keywords:
            return "option"
        return "value"

    def _literal_number(self, node) -> float | None:
        if isinstance(node, Num):
            return node.value
        if isinstance(node, UnaryOp) and node.op == "-" and isinstance(node.operand, Num):
            return -node.operand.value
        return None

    def _check_arg(self, sig: OperatorSig, pname: str, role: str, arg, index: int):
        ctx = f"argument '{pname}' of {sig.name}()"
        if role == "lookback":
            v = self._literal_number(arg)
            if v is None:
                self.expr(arg)
                self.issue("E_LOOKBACK", ERROR, f"{ctx} must be a constant number of days", arg,
                           "use an integer literal such as 5, 21, 63 or 252")
            elif v <= 0 or v != int(v):
                self.issue("E_LOOKBACK", ERROR, f"{ctx} must be a positive integer, got {v:g}", arg)
            else:
                self.an.lookbacks.append(int(v))
                if isinstance(arg, Num):
                    self.an.lookback_nodes.append(arg)
                if v > self.rules.max_lookback:
                    self.issue("W_LOOKBACK", WARNING, f"{ctx} = {int(v)} days is unusually long", arg,
                               f"history may not cover it; prefer <= {self.rules.max_lookback}")
            return
        if role == "int":
            v = self._literal_number(arg)
            if v is None or v != int(v):
                self.expr(arg)
                self.issue("E_INT_ARG", ERROR, f"{ctx} must be an integer literal", arg)
            return
        if role == "option":
            default = sig.keywords.get(pname)
            if isinstance(arg, Ident) and arg.name not in self.vars and self.cat.field(arg.name) is None:
                word = arg.name.lower()
                if isinstance(default, bool) and word in ("true", "false"):
                    return
                if word in enum_words(sig) or word in ("true", "false"):
                    return
                self.issue("E_KW_VALUE", ERROR, f"unknown option value '{arg.name}' for {ctx}", arg,
                           f"default is {default!r}; see {sig.usage()}", subject=arg.name)
                return
            if isinstance(arg, Str):
                if isinstance(default, (int, float)) and not isinstance(default, bool):
                    self.issue("E_KW_VALUE", ERROR, f"{ctx} expects a number, got a string", arg)
                return
            if self._literal_number(arg) is not None:
                return
            t = self.expr(arg)
            self._value_check(t, arg, ctx)
            if isinstance(default, (int, float, str)) and not isinstance(default, Symbol):
                self.issue("W_OPTION_EXPR", WARNING, f"{ctx} is normally a constant", arg)
            return
        t = self.expr(arg)
        if role == "group":
            if t not in (GROUP, UNKNOWN):
                self.issue("E_GROUP_ARG", ERROR, f"{ctx} must be a group (e.g. industry, subindustry, sector, market) "
                           "or bucket(...)", arg, "pass a GROUP-type field, not a numeric expression")
            return
        if role == "vector":
            if t not in (VECTOR, UNKNOWN):
                name = arg.name if isinstance(arg, Ident) else "this input"
                self.issue("E_VEC_INPUT", ERROR, f"{sig.name}() expects a VECTOR field but '{name}' is {t}", arg,
                           f"vector operators only aggregate VECTOR fields; use '{name}' directly", subject=sig.name)
            return
        if role == "group_in":
            return
        self._value_check(t, arg, ctx)

    def call(self, node: Call) -> str:
        sig = self.cat.op(node.name)
        if sig is None:
            other = self.cat.op_any(node.name)
            if other is not None:
                self.issue("E_SCOPE", ERROR, f"operator '{node.name}' is only usable in {'/'.join(other.scope)} "
                           f"expressions, not {self.rules.scope} alphas", node, subject=node.name)
            else:
                sugg = self.cat.suggest_ops(node.name)
                hint = f"closest available: {', '.join(sugg)}" if sugg else "use only operators from the provided list"
                self.issue("E_UNKNOWN_OP", ERROR, f"operator '{node.name}' does not exist on this account", node,
                           hint, subject=node.name)
            self.count(node.name)
            for a in node.args:
                self.expr(a)
            for kw in node.kwargs:
                self.expr(kw.value)
            return UNKNOWN
        self.count(sig.name)
        if node.name != sig.name:
            self.an.fixes.append(f"normalised operator name {node.name} -> {sig.name}")
        if not sig.call_form:
            self.issue("E_INFIX_ONLY", ERROR, f"'{sig.name}' is written as an infix operator", node,
                       f"write it as x {sig.infix[0]} y" if sig.infix else "")
        npos = len(node.args)
        if npos < sig.min_args:
            self.issue("E_ARITY", ERROR, f"{sig.name}() needs at least {sig.min_args} positional argument(s), got {npos}",
                       node, f"usage: {sig.usage()}", subject=sig.name)
        elif sig.max_args is not None and npos > sig.max_args:
            self.issue("E_ARITY", ERROR, f"{sig.name}() takes at most {sig.max_args} argument(s), got {npos}",
                       node, f"usage: {sig.usage()}", subject=sig.name)
        order = sig.param_order
        filled = set()
        is_backfill = sig.name.lower() in self.rules.backfill_operators
        for i, arg in enumerate(node.args):
            if sig.variadic and sig.positional and i >= len(sig.positional):
                pname = sig.positional[-1]  # add(a, b, c, filter=true): extra inputs, not the keyword slots
            elif i < len(order):
                pname = order[i]
            else:
                pname = sig.positional[-1] if sig.positional else f"arg{i}"
            filled.add(pname)
            role = self._param_role(sig, pname, i)
            if is_backfill and i == 0:
                self.backfill_depth += 1
                self._check_arg(sig, pname, role, arg, i)
                self.backfill_depth -= 1
            else:
                self._check_arg(sig, pname, role, arg, i)
        kwmap = {k.lower(): k for k in sig.keywords}
        for kw in node.kwargs:
            real = kwmap.get(kw.name.lower())
            if real is None:
                if kw.name in sig.positional:
                    self.issue("E_KWARG", ERROR, f"'{kw.name}' is a positional parameter of {sig.name}()", kw,
                               f"pass it positionally: {sig.usage()}")
                else:
                    valid = ", ".join(sig.keywords) or "none"
                    self.issue("E_KWARG", ERROR, f"{sig.name}() has no keyword '{kw.name}'", kw,
                               f"valid keywords: {valid}; usage: {sig.usage()}", subject=f"{sig.name}.{kw.name}")
                self.expr(kw.value)
                continue
            if real in filled:
                self.issue("E_KWARG", ERROR, f"keyword '{real}' of {sig.name}() given twice", kw)
            filled.add(real)
            self._check_arg(sig, real, self._param_role(sig, real, -1), kw.value, -1)
        ret = (self.rules.type_overrides.get(sig.name) or {}).get("returns")
        return ret or MATRIX

    # -- program --------------------------------------------------------
    def program(self, prog: Program) -> str:
        last_type = UNKNOWN
        stmts = prog.statements
        for idx, st in enumerate(stmts):
            is_last = idx == len(stmts) - 1
            if isinstance(st, Assign):
                if self.cat.op(st.name) or self.cat.field(st.name):
                    self.issue("E_VAR_NAME", ERROR, f"variable name '{st.name}' shadows an operator or data field", st,
                               "rename the variable, e.g. sig_" + st.name)
                t = self.expr(st.value)
                if st.name in self.vars:
                    self.issue("W_REDEFINED", WARNING, f"variable '{st.name}' redefined", st)
                self.vars[st.name] = t
                if is_last:
                    self.issue("E_NO_ALPHA", ERROR, "the last statement is an assignment; it must be the alpha expression",
                               st, f"end with an expression that uses '{st.name}'")
            else:
                t = self.expr(st)
                if not is_last:
                    self.issue("W_DEAD_CODE", WARNING, "statement result is discarded (only the last statement is the alpha)", st)
                last_type = t
        if last_type == VECTOR:
            self.issue("E_VECTOR", ERROR, "the alpha is a vector field; aggregate it with a vec_ operator", None,
                       f"available: {self._vector_ops_hint()}")
        elif last_type == GROUP:
            self.issue("E_FINAL_GROUP", ERROR, "the alpha evaluates to a group, not numeric weights")
        elif last_type == CONST:
            self.issue("E_CONSTANT", ERROR, "the alpha is a constant and cannot rank instruments")
        for v in self.vars:
            if v not in self.var_used:
                self.issue("W_UNUSED", WARNING, f"variable '{v}' is never used")
        return last_type


def analyze(source: str, catalog: Catalog, constraints: Constraints | None = None) -> Analysis:
    clean, fixes = sanitize(source or "")
    an = Analysis(source=source, clean=clean, fixes=list(fixes), constraints=constraints)
    try:
        an.program = parse(clean)
    except FastExprSyntaxError as e:
        an.issues.append(Issue("E_SYNTAX", ERROR, e.render(), e.line, e.col))
        return an
    walker = _Walker(catalog, an)
    walker.program(an.program)
    _group_levels(an, catalog)
    if not an.fields and not any(i.code == "E_UNKNOWN_FIELD" for i in an.issues):
        an.issues.append(Issue("E_NO_DATA", ERROR, "the alpha uses no data field"))
    rules = catalog.rules
    for f in an.fields:
        info = an.field_info[f]
        if (info.coverage is not None and info.coverage < rules.min_coverage_warn and f not in walker.backfilled
                and (info.type or MATRIX).upper() == MATRIX):
            an.issues.append(Issue("W_COVERAGE", WARNING, f"field '{f}' covers only {info.coverage:.0%} of the universe",
                                   hint=f"consider ts_backfill({f}, 63) or a group_backfill", subject=f))
    from .printer import to_source  # local import to avoid a cycle
    an.canonical = to_source(an.program, catalog)
    if constraints:
        _apply_constraints(an, constraints)
    return an


def _apply_constraints(an: Analysis, c: Constraints) -> None:
    label = f" ({c.label})" if c.label else ""
    if c.max_ops is not None:
        n = an.pp_op_count(c.excluded_ops)
        if n > c.max_ops:
            counted = [o for o in an.operators if o.lower() not in {e.lower() for e in c.excluded_ops}]
            an.issues.append(Issue("C_MAX_OPERATORS", ERROR,
                                   f"uses {n} operators, limit is {c.max_ops}{label}. Counted: {', '.join(counted)}",
                                   hint="every function call and every + - * / < > == && || counts once; "
                                        "unary minus counts unless on a number; "
                                        f"{', '.join(sorted(c.excluded_ops)) or 'nothing'} not counted"))
    fields = an.counted_fields(c.grouping_fields)
    if c.max_fields is not None and len(fields) > c.max_fields:
        an.issues.append(Issue("C_MAX_FIELDS", ERROR,
                               f"uses {len(fields)} distinct data fields ({', '.join(fields)}), limit is {c.max_fields}{label}",
                               hint=f"grouping fields ({', '.join(sorted(c.grouping_fields))}) do not count"))
    theme_fields = list(an.fields) if c.count_grouping_categories else fields
    if c.allowed_categories is not None:
        for f in theme_fields:
            cat = an.field_info[f].category
            if cat and cat not in c.allowed_categories:
                grouping = f in c.grouping_fields
                an.issues.append(Issue("C_CATEGORY", ERROR,
                                       f"{'grouping ' if grouping else ''}field '{f}' is in data category '{cat}', which is "
                                       f"outside the theme{label}" + (" (the platform counts grouping fields for theme "
                                                                     "matching)" if grouping else ""),
                                       hint=("drop the group operator and use the neutralization setting (e.g. INDUSTRY) "
                                             "instead" if grouping else
                                             f"allowed categories: {', '.join(sorted(c.allowed_categories))}"), subject=f))
    if c.allowed_datasets is not None:
        for f in fields:
            ds = an.field_info[f].dataset
            if ds and ds not in c.allowed_datasets:
                an.issues.append(Issue("C_DATASET", ERROR, f"field '{f}' comes from dataset '{ds}', outside the theme{label}",
                                       subject=f))
    cats = an.categories(set() if c.count_grouping_categories else c.grouping_fields)
    if c.single_category and len(cats) > 1:
        an.issues.append(Issue("C_SINGLE_CATEGORY", ERROR,
                               f"mixes data categories {', '.join(cats)}; the theme requires a single category{label}",
                               hint="take every non-grouping field from one category"))
    dss = an.datasets(c.grouping_fields)
    if c.single_dataset and len(dss) > 1:
        an.issues.append(Issue("C_SINGLE_DATASET", ERROR,
                               f"mixes datasets {', '.join(dss)}; a single dataset is required{label}"))


def _group_levels(an: Analysis, catalog: Catalog) -> None:
    """Track at which group level each value is constant (None = varies stock by stock).

    group_mean(x, w, industry) is constant within each industry; neutralizing or ranking such a value within the
    same or a finer group (industry, subindustry) gives every stock in a group the same number, i.e. no signal.
    """
    rules = catalog.rules
    hier = [h.lower() for h in rules.group_hierarchy]
    STOCK, FLAT = None, "const"

    def finer(levels):
        varying = [lv for lv in levels if lv != FLAT]
        if not varying:
            return FLAT
        if any(lv is STOCK for lv in varying):
            return STOCK
        return min(varying, key=hier.index)

    def group_name(node):
        return node.name.lower() if isinstance(node, Ident) and node.name.lower() in hier else None

    def level(node, env):
        if isinstance(node, (Num, Str)):
            return FLAT
        if isinstance(node, Ident):
            if node.name in env:
                return env[node.name]
            return FLAT if node.name.lower() in rules.literal_words else STOCK
        if isinstance(node, UnaryOp):
            return level(node.operand, env)
        if isinstance(node, BinOp):
            return finer([level(node.left, env), level(node.right, env)])
        if isinstance(node, Ternary):
            return finer([level(node.cond, env), level(node.then, env), level(node.other, env)])
        if not isinstance(node, Call):
            return STOCK
        sig = catalog.op(node.name)
        name = (sig.name if sig else node.name).lower()
        if sig is not None and sig.category in rules.vector_categories:
            return STOCK
        order = sig.param_order if sig else []
        named = {(order[i] if i < len(order) else f"arg{i}"): a for i, a in enumerate(node.args)}
        named.update({k.name: k.value for k in node.kwargs})
        groups = [v for k, v in named.items() if k in rules.group_param_names]
        values = [v for k, v in named.items() if k not in rules.group_param_names]
        g = group_name(groups[0]) if groups else None
        if name in rules.group_aggregators:
            if g is None:
                return STOCK
            inner = finer([level(v, env) for v in values[:1]])
            if inner in (STOCK, FLAT) or hier.index(inner) < hier.index(g):
                return g
            return inner
        if name in rules.group_transforms:
            inner = level(values[0], env) if values else STOCK
            if g is not None and inner is not STOCK and (inner == FLAT or hier.index(g) <= hier.index(inner)):
                what = "already constant" if inner == FLAT else f"already constant within each {inner}"
                an.issues.append(Issue("E_DEGENERATE", ERROR,
                                       f"{name}(..., {g}) is applied to a value that is {what}: every stock in a "
                                       f"{g} gets the same number, so the signal disappears", node.line, node.col,
                                       f"use a coarser group than {inner} (e.g. sector or market), or keep stock-level "
                                       f"variation in the input", subject=name))
                return FLAT
            return inner
        return finer([level(v, env) for v in values])

    env: dict = {}
    for st in an.program.statements:
        if isinstance(st, Assign):
            env[st.name] = level(st.value, env)
    last = an.program.statements[-1]
    if not isinstance(last, Assign):
        lv = level(last, env)
        an.group_level = lv if lv in hier else None
