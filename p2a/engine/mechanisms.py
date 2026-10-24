"""Return mechanisms with high documented Sharpe, filled from the live catalog (research/mechanisms.yaml).

A mechanism is a research result written as a BRAIN expression whose inputs are ROLES (a residual return, a news
count, an overnight tone, a statistical industry group, ...), not field names. Each role is filled from the live
catalog by matching field ids and descriptions, preferring high coverage and few existing alphas, so the same
mechanism adapts to whatever data the account and region offer. Enhancers are research-backed transformations
(volatility scaling, double neutralization, turnover targeting) applied to signals that already work.

The lifecycle, the uniqueness screen and BRAIN's checks then judge every candidate like any other alpha.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..util import console
from .context import Context
from .generator import Candidate, Generator
from .lifecycle import Lifecycle, family_key
from .shapes import template_operators

_SLOT = re.compile(r"\{([a-z0-9_]+)\}")


def _rx(items) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in items or []]


@dataclass
class Mechanism:
    id: str
    template: str
    roles: list[str]
    group: str = ""
    neutralization: str | None = None
    decay: int | None = None
    sources: list[str] = field(default_factory=list)
    idea: str = ""
    counterpart: str | None = None
    enhancer: bool = False
    regions: list[str] = field(default_factory=list)  # where the research says it works; empty = every region
    missing_ops: set = field(default_factory=set)

    @property
    def available(self) -> bool:
        return not self.missing_ops

    def fits(self, region: str) -> bool:
        return not self.regions or str(region).upper() in self.regions


_MLIB = None


def mechanism_library(ctx) -> "MechanismLibrary":
    global _MLIB
    if _MLIB is None:
        _MLIB = MechanismLibrary.load(ctx.cfg)
    return _MLIB


class MechanismLibrary:
    def __init__(self, data: dict, catalog=None):
        self.data = data or {}
        self.roles: dict = self.data.get("roles") or {}
        self.mechanisms = [self._make(m) for m in self.data.get("mechanisms") or []]
        self.enhancers = [self._make({**m, "enhancer": True}) for m in self.data.get("enhancers") or []]
        if catalog is not None:
            for m in self.mechanisms + self.enhancers:
                m.missing_ops = {op for op in template_operators(m.template) if not catalog.op(op)}

    @staticmethod
    def _make(d: dict) -> Mechanism:
        return Mechanism(id=d["id"], template=" ".join(str(d["template"]).split()), roles=list(d.get("roles") or []),
                         group=d.get("group", ""), neutralization=d.get("neutralization"), decay=d.get("decay"),
                         sources=list(d.get("sources") or []), idea=" ".join(str(d.get("idea") or "").split()),
                         counterpart=d.get("counterpart"), enhancer=bool(d.get("enhancer")),
                         regions=[str(r).upper() for r in d.get("regions") or []])

    @classmethod
    def load(cls, cfg, catalog=None) -> "MechanismLibrary":
        path = Path(cfg.get("mechanisms.library", "research/mechanisms.yaml"))
        if not path.is_absolute():
            path = cfg.root / path
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        return cls(data, catalog)

    def get(self, mid: str) -> Mechanism | None:
        return next((m for m in self.mechanisms + self.enhancers if m.id == mid), None)


class RoleResolver:
    """Fills a role with live catalog fields: exact ids, or description / id patterns, filtered by type, coverage and
    exclusions, ranked by preference hits, coverage and crowding (alphas already built on the field)."""

    def __init__(self, ctx: Context, roles: dict):
        self.ctx = ctx
        self.roles = roles
        self._searched: set = set()

    def _search(self, spec: dict) -> None:
        sync = getattr(self.ctx, "sync", None)
        if not sync or not getattr(sync, "client", None):
            return
        for term in spec.get("search") or []:
            if term in self._searched:
                continue
            self._searched.add(term)
            key = f"role_search:{self.ctx.scope['region']}:{self.ctx.scope['delay']}:{self.ctx.scope['universe']}:{term}"
            if self.ctx.store.kv_get(key, max_age_s=7 * 86400) is None:
                rows = sync.search_fields(term, self.ctx.scope, limit=int(self.ctx.cfg.get("mechanisms.search_limit", 100)))
                self.ctx.store.kv_set(key, len(rows))

    def candidates(self, role: str) -> list[dict]:
        """Exact ids first (those the scope has), then, when the role also has patterns, the fields its patterns find:
        a field verified in one region leads there, and the patterns fill the role in regions that name it otherwise."""
        spec = self.roles.get(role) or {}
        store, scope = self.ctx.store, self.ctx.scope
        exact = [r for r in (store.field(i, scope) or self._lookup(i) for i in spec.get("ids") or []) if r]
        if spec.get("ids") and not (spec.get("patterns") or spec.get("id_patterns")):
            return exact
        found = {r["id"] for r in exact}
        return exact + [f for f in self._matches(spec) if f["id"] not in found]

    def _matches(self, spec: dict) -> list[dict]:
        store, scope = self.ctx.store, self.ctx.scope
        self._search(spec)
        pats, idp, exc, pref = _rx(spec.get("patterns")), _rx(spec.get("id_patterns")), _rx(spec.get("exclude")), \
            _rx(spec.get("prefer"))
        want_type = (spec.get("type") or "").upper()
        min_cov = float(spec.get("min_coverage", 0) or 0)
        uni = str(scope.get("universe") or "").lower()
        out = []
        for f in store.fields(scope):
            fid, desc = f["id"], f.get("description") or ""
            text = f"{fid} {desc}"
            ftype = (f.get("type") or "MATRIX").upper()
            if want_type and ftype != want_type:
                continue
            if ftype not in ("MATRIX", "VECTOR", "GROUP"):
                continue
            if (f.get("coverage") or 0) < min_cov:
                continue
            if pats and not any(p.search(desc) or p.search(fid) or p.search(fid.replace("_", " ")) for p in pats):
                continue
            if idp and not any(p.search(fid) for p in idp):
                continue
            if any(p.search(text) for p in exc):
                continue
            if spec.get("universe_in_id") and uni and uni not in fid.lower():
                continue
            hits = sum(1 for p in pref if p.search(text))
            crowd = math.log10(10 + (f.get("alpha_count") or 0))
            out.append(((hits, round(f.get("coverage") or 0, 2), -crowd), f))
        out.sort(key=lambda t: t[0], reverse=True)
        return [f for _, f in out]

    def _lookup(self, fid: str) -> dict | None:
        sync = getattr(self.ctx, "sync", None)
        if sync and getattr(sync, "client", None):
            sync.lookup_field(fid, self.ctx.scope)
        return self.ctx.store.field(fid, self.ctx.scope)

    def expr(self, role: str, f: dict) -> str:
        """The field as a matrix expression: vector fields are aggregated (counts for count roles)."""
        if (f.get("type") or "").upper() != "VECTOR":
            return f["id"]
        agg = "vec_count" if "count" in role else "vec_avg"
        return f"{agg}({f['id']})"


class MechanismBuilder:
    def __init__(self, ctx: Context, generator: Generator, simulator=None):
        self.ctx = ctx
        self.gen = generator
        self.simulator = simulator
        self.mcfg = ctx.cfg.section("mechanisms")
        self.lib = MechanismLibrary.load(ctx.cfg, ctx.catalog)
        self.resolver = RoleResolver(ctx, self.lib.roles)

    # -- mechanisms ------------------------------------------------------------------------------
    def fill(self, m: Mechanism, k: int) -> list[dict]:
        """Up to k fillings of a mechanism's roles. Single-role mechanisms try the k best fields; multi-role ones
        combine the best field of each role."""
        per_role = {r: self.resolver.candidates(r) for r in m.roles}
        if any(not v for v in per_role.values()):
            return []
        if len(m.roles) == 1:
            role = m.roles[0]
            fills = [{role: f} for f in per_role[role][:max(k * 3, k)]]
        else:
            fills = [{r: v[0] for r, v in per_role.items()}]
        out = []
        for fl in fills:
            slots = {r: self.resolver.expr(r, f) for r, f in fl.items()}
            if m.counterpart == "d1":
                role = m.roles[0]
                base = fl[role]["id"].replace("_fast_d1", "")
                if base == fl[role]["id"]:
                    continue
                twin = self.ctx.store.field(base, self.ctx.scope) or self.resolver._lookup(base)
                if not twin:
                    continue
                slots[f"{role}_d1"] = self.resolver.expr(role, twin)
                fl = {**fl, f"{role}_d1": twin}
            expr = _SLOT.sub(lambda mm: slots.get(mm.group(1), mm.group(0)), m.template)
            if _SLOT.search(expr):
                continue
            out.append({"expr": expr, "fields": fl})
            if len(out) >= k:
                break
        return out

    def proposals(self, n: int | None = None, only: list[str] | None = None) -> list[dict]:
        n = int(n or self.mcfg.get("per_step", 8))
        k = int(self.mcfg.get("per_mechanism", 2))
        fams = Lifecycle(self.ctx, simulator=self.simulator).families()
        tried = {key for key, f in fams.items() if f.rows or f.queued}
        out = []
        for m in self.lib.mechanisms:
            if only and m.id not in only:
                continue
            if not only and not m.fits(self.ctx.scope["region"]):  # naming a mechanism with --only overrides its regions
                continue
            if not m.available:
                console.print(f"  [dim]{m.id}: operators missing on this account ({', '.join(sorted(m.missing_ops))})[/dim]")
                continue
            for fill in self.fill(m, k + 2):
                fields = {f["id"] for f in fill["fields"].values() if (f.get("type") or "").upper() != "GROUP"}
                key = family_key(fields, m.group or m.id)
                if key in tried:  # this mechanism family was already simulated on these inputs
                    continue
                tried.add(key)
                out.append(self._raw(m, fill))
                if sum(1 for o in out if o["shape"] == f"mech:{m.id}") >= k:
                    break
            if len(out) >= n:
                break
        return out[:n]

    def _raw(self, m: Mechanism, fill: dict, base: dict | None = None) -> dict:
        data = "; ".join(f"{f['id']} ({f.get('dataset')}, {f.get('category')} category): {(f.get('description') or '')[:160]}"
                         for f in fill["fields"].values())
        idea = f"{m.idea[0].upper() + m.idea[1:]} ({'; '.join(m.sources)})." if m.idea else ""
        if base:
            idea = (f"{idea} Applied to an alpha that already works: {base.get('canonical')} "
                    f"(Sharpe {((base.get('stats') or {}).get('sharpe'))}).")
        return {"expression": fill["expr"], "shape": f"mech:{m.id}", "neutralization": m.neutralization,
                "decay": m.decay, "idea": idea, "rationale_data": data,
                "rationale_operators": f"the {m.id} mechanism: {m.template}; rank() keeps a uniform cross-sectional score."}

    def run(self, n: int | None = None, only: list[str] | None = None) -> list[Candidate]:
        raws = self.proposals(n, only)
        if not raws:
            console.print("  no mechanism could be filled with untried live fields")
            return []
        console.print(f"  {len(raws)} mechanism candidate(s)")
        return [self.gen.check(r, origin=f"mechanism:{r['shape'][5:]}") for r in raws]

    # -- enhancers -------------------------------------------------------------------------------
    def enhance(self, rows: list[dict], only: list[str] | None = None) -> list[Candidate]:
        """Research-backed enhancers applied to alphas that already work (each enhancer once per alpha)."""
        out = []
        done = {(r.get("parent_id"), r.get("origin")) for r in self.ctx.store.q(
            "SELECT parent_id, origin FROM alphas WHERE origin LIKE 'enhance:%' AND status != 'invalid'")}
        for row in rows:
            for m in self.lib.enhancers:
                if only and m.id not in only:
                    continue
                if not m.available or (row["id"], f"enhance:{m.id}") in done:
                    continue
                slots = {"s": f"({row['canonical']})"}
                ok = True
                fl = {}
                for role in m.roles:
                    cands = self.resolver.candidates(role)
                    if not cands:
                        ok = False
                        break
                    slots[role] = self.resolver.expr(role, cands[0])
                    fl[role] = cands[0]
                if not ok:
                    continue
                expr = _SLOT.sub(lambda mm: slots.get(mm.group(1), mm.group(0)), m.template)
                raw = self._raw(m, {"expr": expr, "fields": fl}, base=row)
                s = row.get("settings") or {}
                raw.update(neutralization=m.neutralization or s.get("neutralization"), decay=s.get("decay"),
                           truncation=s.get("truncation"), shape=f"enh:{m.id}")
                c = self.gen.check(raw, origin=f"enhance:{m.id}", parent_id=row["id"])
                out.append(c)
        return out
