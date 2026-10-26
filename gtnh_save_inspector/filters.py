"""Field filters for entries: ``--where "progress>0"``.

Expressions are ``FIELD OP VALUE`` where OP is one of ``< <= = == != > >=``. Fields are looked
up on the entry itself (``machine``, ``dim``, ``pos``...) or inside ``fields``; dotted paths
descend into nested dictionaries (``stored.fluid.hydrogen``). Multiple ``--where`` flags are
combined with AND.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

OPERATORS = ("<=", ">=", "!=", "==", "=", "<", ">")


def _coerce(text: str):
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text.strip("\"'")


def parse_where(expression: str) -> Tuple[str, str, object]:
    """Parse ``FIELD OP VALUE`` into (field, operator, expected)."""
    for operator in OPERATORS:
        index = expression.find(operator)
        if index <= 0:
            continue
        field = expression[:index].strip()
        raw = expression[index + len(operator) :].strip()
        if not field:
            continue
        return field, operator, _coerce(raw)
    raise ValueError(
        "invalid --where expression %r (expected FIELD OP VALUE, e.g. progress>0)" % expression
    )


def parse_filters(expressions: Optional[Iterable[str]]) -> List[Tuple[str, str, object]]:
    return [parse_where(expression) for expression in expressions or []]


def resolve_field(entry: dict, field: str):
    if field in entry:
        return entry[field]
    value = entry.get("fields") or {}
    if field in value:
        return value[field]
    for part in field.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def _compare(actual, operator: str, expected) -> bool:
    if actual is None:
        return False
    if operator in ("=", "=="):
        return actual == expected
    if operator == "!=":
        return actual != expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if operator == "<":
            return actual < expected
        if operator == "<=":
            return actual <= expected
        if operator == ">":
            return actual > expected
        if operator == ">=":
            return actual >= expected
    return False


def matches(entry: dict, rules) -> bool:
    for field, operator, expected in rules:
        if not _compare(resolve_field(entry, field), operator, expected):
            return False
    return True


def filter_entries(entries: List[dict], rules) -> List[dict]:
    if not rules:
        return list(entries)
    return [entry for entry in entries if matches(entry, rules)]
