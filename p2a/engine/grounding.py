"""Builds the grounding blocks injected into prompts. Everything comes from synced data."""
from __future__ import annotations

from collections import defaultdict

from ..brain.settings import allowed_values
from ..fastexpr import Catalog, Constraints
from ..util import truncate


def render(template: str, **values) -> str:
    out = template
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", str(val))
    return out


def operator_reference(catalog: Catalog) -> str:
    groups = defaultdict(list)
    for sig in sorted(catalog.ops.values(), key=lambda s: s.name):
        groups[sig.category or "Other"].append(f"- {sig.usage()} : {sig.short_description(150)}")
    return "\n".join(f"[{cat}]\n" + "\n".join(lines) for cat, lines in sorted(groups.items()))


def field_lines(rows: list[dict]) -> str:
    out = []
    for r in rows:
        cov = r.get("coverage")
        cov_s = f"{cov:.0%}" if isinstance(cov, (int, float)) else "?"
        out.append(f"{r['id']} | {(r.get('type') or 'MATRIX').upper()} | {r.get('dataset')} | {cov_s} | "
                   f"{truncate((r.get('description') or '').replace(chr(10), ' '), 120)}")
    return "\n".join(out)


def grouping_text(catalog: Catalog, constraints: Constraints | None) -> str:
    names = sorted(constraints.grouping_fields) if constraints and constraints.grouping_fields else []
    present = [n for n in names if (f := catalog.field(n)) is not None and (f.type or "").upper() == "GROUP"]
    return ", ".join(present) or "(none synced)"


def scope_text(scope: dict) -> str:
    return (f"instrumentType={scope.get('instrumentType', 'EQUITY')}, region={scope['region']}, "
            f"universe={scope['universe']}, delay={scope['delay']}")


def constraints_text(constraints: Constraints | None, theme) -> str:
    lines = []
    if constraints and constraints.max_ops is not None:
        free = ", ".join(sorted(constraints.excluded_ops)) or "none"
        lines.append(f"- At most {constraints.max_ops} operators per alpha ({free} not counted).")
    if constraints and constraints.max_fields is not None:
        lines.append(f"- At most {constraints.max_fields} distinct data fields per alpha (grouping fields not counted).")
    if theme is not None:
        lines.append(theme.describe())
    if constraints and constraints.count_grouping_categories and constraints.grouping_fields:
        lines.append("- Do NOT use grouping fields (" + ", ".join(sorted(constraints.grouping_fields)) + ") anywhere in "
                     "the expression: BRAIN counts their own (price-volume) category against this theme. Group "
                     "operators are only allowed with bucket(...) groups built from theme fields. To neutralize by "
                     "industry or sector, choose the neutralization setting instead.")
    if not lines:
        lines.append("- none beyond valid syntax")
    return "\n".join(lines)


def settings_text(options: dict, scope: dict, defaults: dict) -> str:
    probe = {**defaults, **scope}
    lines = []
    neut = allowed_values(options, "neutralization", probe) if options else None
    if neut:
        lines.append(f"- neutralization: one of {neut} (default {defaults.get('neutralization')})")
    for key in ("decay", "truncation"):
        spec = (options or {}).get(key) or {}
        rng = f" (allowed {spec.get('minValue')}..{spec.get('maxValue')})" if spec else ""
        lines.append(f"- {key}: number{rng}, default {defaults.get(key)}")
    return "\n".join(lines)


def hypothesis_text(h: dict) -> str:
    body = h.get("body") or {}
    parts = [f"Title: {h.get('title') or body.get('title')}"]
    for key, label in (("mechanism", "Mechanism"), ("signal_construction", "Construction"),
                       ("data_concepts", "Data needed"), ("horizon", "Horizon"),
                       ("expected_turnover", "Expected turnover"), ("evidence", "Evidence")):
        val = body.get(key)
        if val:
            parts.append(f"{label}: {', '.join(val) if isinstance(val, list) else val}")
    return "\n".join(parts)


def hypothesis_query(h: dict) -> str:
    body = h.get("body") or {}
    bits = [h.get("title") or "", body.get("mechanism") or "", body.get("signal_construction") or ""]
    bits += list(body.get("data_concepts") or []) + list(body.get("keywords") or [])
    return " ".join(str(b) for b in bits)


def exemplar_text(rows: list[dict], official: list[str]) -> str:
    lines = []
    for r in rows:
        st = r.get("stats") or {}
        s = r.get("settings") or {}
        lines.append(f"- {r['canonical']}  [neutralization={s.get('neutralization')}, decay={s.get('decay')}] "
                     f"Sharpe {st.get('sharpe')}, turnover {st.get('turnover')}, fitness {st.get('fitness')}")
    for code in official:
        lines.append(f"- {code}  [official BRAIN example]")
    return "\n".join(lines) or "(none yet)"
