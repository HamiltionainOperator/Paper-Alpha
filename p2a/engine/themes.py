"""Power Pool themes: parse rule text, cross-check with API theme tags, derive constraints."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date

from ..fastexpr import Constraints
from ..store import Store

KEY_ALIASES = {
    "datacategory": "category", "data_category": "category", "category": "category", "categories": "category",
    "dataset": "dataset", "datasets": "dataset", "region": "region", "regions": "region",
    "universe": "universe", "universes": "universe", "delay": "delay",
}


@dataclass
class ThemeSpec:
    name: str
    rule: str = ""
    start: date | None = None
    end: date | None = None
    delay: int | None = None
    regions: set | None = None
    universes: set | None = None
    categories: set | None = None
    datasets: set | None = None
    single_category: bool = False
    single_dataset: bool = False
    extra: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    api_ids: set = field(default_factory=set)
    api_datasets: set = field(default_factory=set)
    api_categories: set = field(default_factory=set)
    source: str = "config"

    def active(self, today: date) -> bool:
        if self.start and today < self.start:
            return False
        if self.end and today > self.end:
            return False
        if self.source == "api":
            return bool(self.api_datasets)
        return True

    def scope_problems(self, scope: dict) -> list[str]:
        out = []
        if self.delay is not None and int(scope["delay"]) != self.delay:
            out.append(f"theme requires delay={self.delay}, scope has delay={scope['delay']}")
        if self.regions and scope["region"] not in self.regions:
            out.append(f"theme regions {sorted(self.regions)} exclude {scope['region']}")
        if self.universes and scope["universe"] not in self.universes:
            out.append(f"theme universes {sorted(self.universes)} exclude {scope['universe']}")
        return out

    def describe(self) -> str:
        parts = [f"Theme: {self.name}"]
        if self.rule:
            parts.append(f"Official rule: {self.rule}")
        if self.delay is not None:
            parts.append(f"- delay must be {self.delay}")
        if self.regions:
            parts.append(f"- region in {sorted(self.regions)}")
        if self.universes:
            parts.append(f"- universe in {sorted(self.universes)}")
        if self.categories:
            parts.append(f"- every non-grouping data field must come from data categories {sorted(self.categories)}")
        if self.datasets:
            parts.append(f"- allowed datasets: {sorted(self.datasets)}")
        if self.single_category:
            parts.append("- all non-grouping fields must come from ONE single data category")
        if self.single_dataset:
            parts.append("- all non-grouping fields must come from ONE single dataset")
        for e in self.extra:
            parts.append(f"- additional condition: {e}")
        return "\n".join(parts)


def _match_category(value: str, categories: list[dict]) -> tuple[str | None, str | None]:
    v = value.strip().lower()
    ids = {c["id"].lower(): c["id"] for c in categories}
    names = {c.get("name", "").lower(): c["id"] for c in categories}
    if v in ids:
        return ids[v], None
    if v in names:
        return names[v], None
    pool = list(ids) + list(names)
    close = difflib.get_close_matches(v, pool, n=1, cutoff=0.72)
    if close:
        cid = ids.get(close[0]) or names.get(close[0])
        return cid, f"interpreted category '{value}' as '{cid}'"
    return None, f"unknown data category '{value}' (not in the live category list)"


def parse_rule(spec: ThemeSpec, rule: str, categories: list[dict]) -> ThemeSpec:
    spec.rule = rule
    for raw in re.split(r"\s*&\s*|\s+and\s+", rule.strip()):
        part = raw.strip()
        if not part:
            continue
        m = re.fullmatch(r"single\s+(data\s*category|datacategory|category|dataset)", part, re.I)
        if m:
            if "set" in m.group(1).lower():
                spec.single_dataset = True
            else:
                spec.single_category = True
            continue
        m = re.fullmatch(r"([A-Za-z_ ]+?)\s+in\s+\[(.*)\]", part, re.I)
        if m:
            key = KEY_ALIASES.get(m.group(1).strip().lower().replace(" ", ""))
            values = [v.strip().strip("'\"` ") for v in m.group(2).split(",") if v.strip()]
            if key == "category":
                cats = set()
                for v in values:
                    cid, note = _match_category(v, categories) if categories else (v.lower(), None)
                    if note:
                        spec.warnings.append(note)
                    if cid:
                        cats.add(cid)
                spec.categories = cats
            elif key == "dataset":
                spec.datasets = set(values)
            elif key == "region":
                spec.regions = {v.upper() for v in values}
            elif key == "universe":
                spec.universes = {v.upper() for v in values}
            else:
                spec.extra.append(part)
            continue
        m = re.fullmatch(r"([A-Za-z_ ]+?)\s*==?\s*([\w.\-]+)", part)
        if m:
            key = KEY_ALIASES.get(m.group(1).strip().lower().replace(" ", ""))
            val = m.group(2)
            if key == "delay" and val.isdigit():
                spec.delay = int(val)
            elif key == "region":
                spec.regions = {val.upper()}
            elif key == "universe":
                spec.universes = {val.upper()}
            elif key == "category":
                cid, note = _match_category(val, categories) if categories else (val.lower(), None)
                if note:
                    spec.warnings.append(note)
                spec.categories = {cid} if cid else None
            elif key == "dataset":
                spec.datasets = {val}
            else:
                spec.extra.append(part)
            continue
        spec.extra.append(part)
    return spec


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _as_date(v) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def load_themes(cfg, store: Store, scope: dict) -> list[ThemeSpec]:
    pattern = re.compile(cfg.get("power_pool.theme_name_pattern", r"(?i)power\s*pool"))
    categories = store.kv_get("data_categories") or []
    specs: list[ThemeSpec] = []
    for t in cfg.get("themes") or []:
        spec = ThemeSpec(name=t["name"], start=_as_date(t.get("start")), end=_as_date(t.get("end")))
        parse_rule(spec, t.get("rule", ""), categories)
        specs.append(spec)
    tagged: dict[str, dict] = {}
    for ds in store.datasets(scope):
        for th in ds.get("themes") or []:
            if pattern.search(th.get("name", "")):
                info = tagged.setdefault(th["name"], {"ids": set(), "datasets": set(), "categories": set()})
                info["ids"].add(th.get("id"))
                info["datasets"].add(ds["id"])
                if ds.get("category"):
                    info["categories"].add(ds["category"])
    by_norm = {_norm(s.name): s for s in specs}
    for name, info in tagged.items():
        spec = by_norm.get(_norm(name))
        if spec is None:
            close = difflib.get_close_matches(_norm(name), list(by_norm), n=1, cutoff=0.9)
            spec = by_norm[close[0]] if close else None
        if spec is None:
            spec = ThemeSpec(name=name, source="api", categories=set(info["categories"]),
                             datasets=set(info["datasets"]))
            d = re.search(r"\bD(\d)\b", name)
            if d:
                spec.delay = int(d.group(1))
            spec.warnings.append("no rule text in config.yaml; scope inferred from API dataset tags "
                                 "(paste the official rule into config.yaml themes to be exact)")
            specs.append(spec)
        spec.api_ids |= info["ids"]
        spec.api_datasets |= info["datasets"]
        spec.api_categories |= info["categories"]
        if spec.categories and spec.source == "config":
            extra = spec.api_categories - spec.categories
            if extra:
                spec.warnings.append(f"API tags this theme on categories {sorted(extra)} not in the rule text")
    return specs


def active_themes(specs: list[ThemeSpec], today: date | None = None) -> list[ThemeSpec]:
    today = today or date.today()
    return [s for s in specs if s.active(today)]


def constraints_for(theme: ThemeSpec | None, pp: dict) -> Constraints:
    c = Constraints(
        max_ops=pp.get("max_operators"),
        excluded_ops=set(pp.get("excluded_operators") or []),
        max_fields=pp.get("max_unique_fields"),
        grouping_fields=set(pp.get("grouping_fields") or []),
        label=theme.name if theme else "Power Pool",
    )
    if theme:
        c.allowed_categories = set(theme.categories) if theme.categories else None
        c.allowed_datasets = set(theme.datasets) if theme.datasets else None
        c.single_category = theme.single_category
        c.single_dataset = theme.single_dataset
        if theme.categories or theme.single_category or theme.single_dataset:
            c.count_grouping_categories = bool(pp.get("theme_counts_grouping_fields", True))
    return c
