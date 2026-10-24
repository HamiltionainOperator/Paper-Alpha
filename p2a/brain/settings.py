"""Validate simulation settings against the live OPTIONS /simulations schema."""
from __future__ import annotations


def resolve_choices(spec: dict, settings: dict) -> list | None:
    """Follow nested choice maps such as {"instrumentType": {"EQUITY": {"region": {"USA": [...]}}}}."""
    choices = spec.get("choices")
    while isinstance(choices, dict):
        if len(choices) != 1:
            return None
        key, sub = next(iter(choices.items()))
        val = settings.get(key)
        if val is None or not isinstance(sub, dict):
            return None
        nxt = sub.get(str(val))
        if nxt is None:
            nxt = next((v for k, v in sub.items() if str(k).upper() == str(val).upper()), None)
        if nxt is None:
            return []
        choices = nxt
    if isinstance(choices, list):
        return [c.get("value") if isinstance(c, dict) else c for c in choices]
    return None


def allowed_values(options: dict, key: str, settings: dict) -> list | None:
    spec = options.get(key)
    return resolve_choices(spec, settings) if spec else None


def validate_settings(settings: dict, options: dict) -> list[str]:
    errors = []
    for key, val in settings.items():
        spec = options.get(key)
        if spec is None:
            errors.append(f"unknown setting '{key}'")
            continue
        if spec.get("readOnly"):
            continue
        kind = spec.get("type")
        if kind == "choice":
            allowed = resolve_choices(spec, settings)
            if allowed is not None and val not in allowed and str(val) not in {str(a) for a in allowed}:
                errors.append(f"{key}={val!r} not allowed; choose from {allowed}")
        elif kind in ("integer", "float"):
            try:
                num = float(val)
            except (TypeError, ValueError):
                errors.append(f"{key} must be numeric")
                continue
            if kind == "integer" and num != int(num):
                errors.append(f"{key} must be an integer")
            lo, hi = spec.get("minValue"), spec.get("maxValue")
            if lo is not None and num < float(lo):
                errors.append(f"{key}={val} below minimum {lo}")
            if hi is not None and num > float(hi):
                errors.append(f"{key}={val} above maximum {hi}")
        elif kind == "boolean" and not isinstance(val, bool):
            errors.append(f"{key} must be true/false")
    return errors
