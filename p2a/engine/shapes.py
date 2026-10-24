"""Alpha shapes: research-backed expression templates matched to the kind and speed of each field.

A shape is the structure of an alpha independent of its field (level, change, event-gated, spread, orthogonal,
combination, ...). The library is knowledge, not code: it lives in research/shapes.yaml with its sources, and
every template is checked against the live operator catalog, so a shape that needs an operator this account does
not have is simply disabled. The engine learns which shape works on which kind of data from its own results.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..fastexpr import parse
from ..fastexpr.ast import Call, walk

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass
class Shape:
    id: str
    cls: str
    template: str
    fields: int = 1
    kinds: list[str] = field(default_factory=list)
    speeds: list[str] | None = None
    vector_only: bool = False
    pair: str | None = None
    sources: list[str] = field(default_factory=list)
    idea: str = ""
    remedy: str | None = None
    missing_ops: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.missing_ops


def template_operators(template: str) -> set[str]:
    """Operator names a template calls (placeholders replaced by dummies so it parses)."""
    code = _PLACEHOLDER.sub(lambda m: "5" if m.group(1) in ("d", "ds", "ds2", "dl", "k") else f"ph_{m.group(1)}",
                            template)
    try:
        prog = parse(code)
    except Exception:
        return set()
    return {n.name.lower() for n in walk(prog) if isinstance(n, Call)}


class ShapeLibrary:
    def __init__(self, data: dict, catalog=None):
        self.data = data or {}
        self.speeds: dict = self.data.get("speeds") or {}
        self.speed_cut: dict = self.data.get("speed_from_turnover") or {"fast": 0.25, "medium": 0.05}
        self.kind_patterns = [(k, [re.compile(p, re.I) for p in pats]) for k, pats in (self.data.get("kinds") or {}).items()]
        self.classes = [(c, {o.lower() for o in ops}) for c, ops in (self.data.get("classes") or {}).items()]
        self.default_class = self.data.get("default_class", "level")
        self.shapes = [self._shape(s) for s in self.data.get("shapes") or []]
        self.wrappers = [self._shape({**w, "class": "wrapper"}) for w in self.data.get("wrappers") or []]
        if catalog is not None:
            for s in self.shapes + self.wrappers:
                s.missing_ops = sorted(o for o in template_operators(s.template) if not catalog.op(o))

    @staticmethod
    def _shape(d: dict) -> Shape:
        return Shape(id=d["id"], cls=d.get("class", "level"), template=d["template"], fields=int(d.get("fields", 1)),
                     kinds=list(d.get("kinds") or []), speeds=d.get("speeds"), vector_only=bool(d.get("vector_only")),
                     pair=d.get("pair"), sources=list(d.get("sources") or []), idea=d.get("idea", ""),
                     remedy=d.get("remedy"))

    @classmethod
    def load(cls, cfg, catalog=None) -> "ShapeLibrary":
        path = Path(cfg.get("shapes.library", "research/shapes.yaml"))
        if not path.is_absolute():
            path = cfg.root / path
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        return cls(data, catalog)

    # -- lookups ---------------------------------------------------------------------------
    def get(self, shape_id: str) -> Shape | None:
        return next((s for s in self.shapes + self.wrappers if s.id == shape_id), None)

    def kind_of(self, f: dict) -> str | None:
        text = re.sub(r"[_\d]+", " ", f"{f.get('id', '')} {f.get('description') or ''}")  # eps in anl4_eps_mean
        for kind, pats in self.kind_patterns:
            if any(p.search(text) for p in pats):
                return kind
        return None

    def speed_of(self, turnover: float | None) -> str:
        if turnover is None:
            return "medium"
        if turnover >= float(self.speed_cut.get("fast", 0.25)):
            return "fast"
        if turnover >= float(self.speed_cut.get("medium", 0.05)):
            return "medium"
        return "slow"

    def class_of(self, operators) -> str:
        """Shape class of any expression, from the operators it uses."""
        ops = {o.lower() for o in operators or []}
        for cls, members in self.classes:
            if ops & members:
                return cls
        return self.default_class

    def for_field(self, f: dict, n_fields: int | None = None, speed: str | None = None) -> list[Shape]:
        """Available shapes that suit this field's kind (and speed), in library order."""
        kind = self.kind_of(f)
        vector = (f.get("type") or "MATRIX").upper() == "VECTOR"
        out = []
        for s in self.shapes:
            if not s.available or (n_fields is not None and s.fields != n_fields):
                continue
            if s.vector_only and not vector:
                continue
            if kind is None and s.id not in (self.data.get("unknown_kind_shapes") or [s.id]):
                continue
            if kind is not None and s.kinds and kind not in s.kinds:
                continue
            if speed and s.speeds and speed not in s.speeds:
                continue
            out.append(s)
        return out

    # -- building -------------------------------------------------------------------------
    @staticmethod
    def field_expr(f: dict, aggregator: str = "vec_avg") -> str:
        return f"{aggregator}({f['id']})" if (f.get("type") or "MATRIX").upper() == "VECTOR" else f["id"]

    def instantiate(self, shape: Shape, x: dict, y: dict | None = None, speed: str = "medium",
                    size: str | None = None, base: str | None = None) -> str | None:
        if shape.fields == 2 and y is None:
            return None
        values = {k: str(v) for k, v in (self.speeds.get(speed) or self.speeds.get("medium") or {}).items()}
        values.update({"x": self.field_expr(x), "v": x["id"], "y": self.field_expr(y) if y else "",
                       "size": size or "", "s": base or ""})
        needed = set(_PLACEHOLDER.findall(shape.template))
        if any(not values.get(k) for k in needed):
            return None
        return _PLACEHOLDER.sub(lambda m: values[m.group(1)], shape.template)

    def describe(self, shapes: list[Shape], stats: dict | None = None) -> str:
        """Prompt text: one line per shape with its template, idea, sources and what the engine has seen."""
        lines = []
        for s in shapes:
            st = (stats or {}).get(s.cls)
            seen = f" | seen: {st['n']} tried, best Sharpe {st['best']:.2f}, {st['wins']} cleared the bar" if st else ""
            lines.append(f"- {s.id} ({s.cls}): {s.template} -- {s.idea}. [{'; '.join(s.sources)}]{seen}")
        return "\n".join(lines)


def similar_partner(lib: ShapeLibrary, x: dict, candidates: list[dict], min_score: float = 0.34) -> dict | None:
    """The counterpart of x for spread-like shapes: same dataset, most similar id/description, preferring pairs
    that differ by a polarity word (call/put, up/down, buy/sell, ...)."""
    polar = lib.data.get("polarity_pairs") or [["call", "put"], ["up", "down"], ["upward", "downward"], ["buy", "sell"],
                                                 ["positive", "negative"], ["pos", "neg"], ["increase", "decrease"],
                                                 ["increasing", "decreasing"], ["long", "short"], ["finup", "findown"]]

    def tokens(f):
        return set(t for t in re.split(r"[^a-z]+", f"{f['id']} {f.get('description') or ''}".lower()) if len(t) > 2)

    tx = tokens(x)
    ids_x = set(re.split(r"[_\d]+", x["id"].lower()))
    exclude = [w.lower() for w in lib.data.get("pair_exclude_words") or []]
    kind_x = lib.kind_of(x)
    best = None
    for c in candidates:
        if c["id"] == x["id"] or c.get("dataset") != x.get("dataset") or lib.kind_of(c) != kind_x:
            continue
        text_c = f"{c['id']} {c.get('description') or ''}".lower()
        text_x = f"{x['id']} {x.get('description') or ''}".lower()
        if any(w in text_c and w not in text_x for w in exclude):
            continue
        tc = tokens(c)
        if not tx or not tc:
            continue
        score = len(tx & tc) / len(tx | tc)
        ids_c = set(re.split(r"[_\d]+", c["id"].lower()))
        if any((a in ids_x and b in ids_c) or (b in ids_x and a in ids_c) for a, b in polar):
            score += 0.5
        if best is None or score > best[0]:
            best = (score, c)
    return best[1] if best and best[0] >= min_score else None


def shape_stats(store, lib: ShapeLibrary, floor: float, scope: dict | None = None) -> dict[tuple, dict]:
    """What each (shape class, data kind) has produced so far: tries, best Sharpe, how many cleared the floor."""
    sql = "SELECT fields, operators, shape_class, stats, pp_status FROM alphas WHERE status='simulated'"
    args: tuple = ()
    if scope:
        sql += " AND region=? AND delay=?"
        args = (scope["region"], scope["delay"])
    fields_cache: dict = {}
    out: dict[tuple, dict] = {}
    for r in store.q(sql, args):
        fl = r.get("fields") or []
        if not fl:
            continue
        cls = r.get("shape_class") or lib.class_of(r.get("operators") or [])
        f0 = fl[0]
        if f0 not in fields_cache:
            row = store.one("SELECT id, description FROM fields WHERE id=? LIMIT 1", (f0,)) or {"id": f0}
            fields_cache[f0] = lib.kind_of(row)
        kind = fields_cache[f0]
        sh = (r.get("stats") or {}).get("sharpe")
        if sh is None:
            continue
        st = out.setdefault((cls, kind), {"n": 0, "best": -9.0, "wins": 0, "sum": 0.0})
        st["n"] += 1
        st["sum"] += float(sh)
        st["best"] = max(st["best"], float(sh))
        # cleared = submittable, or above the floor with no failed check yet (pending its BRAIN check)
        st["wins"] += 1 if r.get("pp_status") == "eligible" or (float(sh) >= floor and r.get("pp_status") == "pending") else 0
    return out


def thompson_order(shapes: list[Shape], stats: dict[tuple, dict], kind: str | None, seed: int | None = None) -> list[Shape]:
    """Order shapes by a draw from Beta(1 + wins, 1 + losses) of their class on this kind of data."""
    rnd = random.Random(seed)

    def draw(s):
        st = stats.get((s.cls, kind)) or {"n": 0, "wins": 0}
        return rnd.betavariate(1 + st["wins"], 1 + max(0, st["n"] - st["wins"]))

    return sorted(shapes, key=draw, reverse=True)
