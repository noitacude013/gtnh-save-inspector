"""CSV export of machine entries (flat columns; nested fields as JSON)."""

from __future__ import annotations

import csv
import json
from typing import Iterable, List

BASE_COLUMNS = ("dim", "chunk_x", "chunk_z", "x", "y", "z", "machine")


def _safe_cell(value):
    if isinstance(value, str) and value and value[0] in "=+-@":
        return "'" + value
    return value


def _flatten_row(entry: dict) -> dict:
    pos = list(entry.get("pos") or [None, None, None])
    chunk = list(entry.get("chunk") or [None, None])
    row = {
        "dim": entry.get("dim"),
        "chunk_x": chunk[0] if len(chunk) > 0 else None,
        "chunk_z": chunk[1] if len(chunk) > 1 else None,
        "x": pos[0] if len(pos) > 0 else None,
        "y": pos[1] if len(pos) > 1 else None,
        "z": pos[2] if len(pos) > 2 else None,
        "machine": entry.get("machine"),
    }
    if entry.get("chunk_modified") is not None:
        row["chunk_modified"] = entry["chunk_modified"]
    for key, value in (entry.get("fields") or {}).items():
        if isinstance(value, (dict, list)):
            row[str(key)] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            row[str(key)] = _safe_cell(value)
    return row


def write_csv(path: str, entries: Iterable[dict]) -> int:
    rows = [_flatten_row(entry) for entry in entries]
    columns: List[str] = list(BASE_COLUMNS)
    seen = set(columns)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)
