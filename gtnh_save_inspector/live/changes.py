"""In-memory snapshot diffs for consecutive live samples."""

from __future__ import annotations

from ..core.snapshot import diff as snapshot_diff


def diff_entries(previous: list, current: list) -> list:
    """Return change records between two lists of snapshot-style entries."""
    result = snapshot_diff({"entries": previous}, {"entries": current})
    return result["changes"]


def format_changes(changes: list, limit: int = 0) -> list:
    """Render change records as printable lines (numeric fields get a delta)."""
    lines = []
    for index, change in enumerate(changes):
        if limit and index >= limit:
            lines.append("... (%d more changes)" % (len(changes) - limit))
            break
        dim = change.get("dim")
        pos = tuple(change.get("pos") or ())
        status = change.get("status")
        if status in ("added", "removed"):
            lines.append("[%s] %s pos=%s %s" % (status, dim, pos, change.get("machine") or ""))
            continue
        lines.append("[changed] %s pos=%s %s" % (dim, pos, change.get("machine") or ""))
        for name, values in (change.get("fields") or {}).items():
            delta = values.get("delta")
            suffix = "  (%+d)" % delta if isinstance(delta, int) else ""
            lines.append(
                "  %-16s : %s -> %s%s" % (name, values.get("before"), values.get("after"), suffix)
            )
    return lines


def filter_changes(changes: list, min_delta: int = 0, fields=None) -> list:
    """Drop unchanged/too-small field deltas and unselected fields from change records."""
    wanted = set(fields) if fields else None
    filtered = []
    for change in changes:
        if change.get("status") != "changed":
            filtered.append(change)
            continue
        kept = {}
        for name, values in (change.get("fields") or {}).items():
            if wanted is not None and name not in wanted:
                continue
            delta = values.get("delta")
            if min_delta and isinstance(delta, (int, float)) and abs(delta) < min_delta:
                continue
            kept[name] = values
        if not kept:
            continue
        copy = dict(change)
        copy["fields"] = kept
        filtered.append(copy)
    return filtered
