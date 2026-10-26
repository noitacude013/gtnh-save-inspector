"""Snapshot model: capture machine states from a save and compare snapshots."""

from __future__ import annotations

import datetime
import gzip
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .. import __version__
from ..dimensions import dimension_key
from ..filters import matches as entry_matches
from .world import WorldSource

SNAPSHOT_FORMAT = 1


def filter_diff_changes(changes, ignore_fields=None):
    """Drop ignored fields from ``changed`` entries; drop entries left with no fields."""
    ignored = set(ignore_fields or ())
    if not ignored:
        return changes
    result = []
    for change in changes:
        if change.get("status") != "changed":
            result.append(change)
            continue
        fields = {
            key: value
            for key, value in (change.get("fields") or {}).items()
            if key not in ignored
        }
        machine_changed = change.get("machine_before") != change.get("machine_after")
        if not fields and not machine_changed:
            continue
        filtered = dict(change)
        filtered["fields"] = fields
        result.append(filtered)
    return result


def _compact_entry(entry: dict) -> dict:
    fields = entry.get("fields")
    if not isinstance(fields, dict):
        return entry
    compact = {key: value for key, value in fields.items() if value is not None}
    result = dict(entry)
    result["fields"] = compact
    return result


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def make_entry(dim: str, chunk, pos, machine: str, fields: dict) -> dict:
    return {
        "dim": dim,
        "chunk": list(chunk) if chunk is not None else None,
        "pos": list(pos) if pos is not None else None,
        "machine": machine,
        "fields": fields,
    }


@dataclass
class Snapshot:
    source: str
    world_name: str = ""
    entries: List[dict] = field(default_factory=list)
    captured: str = field(default_factory=now_iso)
    tool_version: str = __version__
    meta: dict = field(default_factory=dict)

    def to_dict(self, compact: bool = False) -> dict:
        entries = self.entries
        if compact:
            entries = [_compact_entry(entry) for entry in entries]
        return {
            "format": SNAPSHOT_FORMAT,
            "tool": "gtnh-save-inspector",
            "tool_version": self.tool_version,
            "snapshot": {
                "captured": self.captured,
                "source": self.source,
                "world": self.world_name,
                "meta": self.meta,
            },
            "entries": entries,
        }

    def save(self, path: str, compress=None, compact: bool = False) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        if compress is None:
            compress = str(path).lower().endswith(".gz")
        payload = json.dumps(self.to_dict(compact=compact), indent=1, ensure_ascii=False) + "\n"
        if compress:
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(payload)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(payload)


def load(path: str) -> dict:
    with open(path, "rb") as probe:
        gzipped = probe.read(2) == b"\x1f\x8b"
    opener = gzip.open if gzipped else open
    with opener(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if "entries" not in payload:
        raise ValueError("%s does not look like a gtnh-save-inspector snapshot" % path)
    return payload


def _entry_key(entry: dict) -> Tuple:
    return (dimension_key(entry.get("dim")), tuple(entry.get("pos") or ()))


def diff(a: dict, b: dict) -> dict:
    """Compare two snapshots and return a list of changes per machine field."""
    amap = {_entry_key(entry): entry for entry in a.get("entries", [])}
    bmap = {_entry_key(entry): entry for entry in b.get("entries", [])}
    changes = []
    for key in sorted(set(amap) | set(bmap)):
        before = amap.get(key)
        after = bmap.get(key)
        display = after or before or {}
        record = {
            "dim": display.get("dim"),
            "pos": list(display.get("pos") or ()),
            "chunk": display.get("chunk"),
        }
        if before is None:
            record["status"] = "added"
            record["machine"] = display.get("machine")
            changes.append(record)
            continue
        if after is None:
            record["status"] = "removed"
            record["machine"] = display.get("machine")
            changes.append(record)
            continue
        field_changes = {}
        before_fields = before.get("fields") or {}
        after_fields = after.get("fields") or {}
        for name in sorted(set(before_fields) | set(after_fields)):
            old = before_fields.get(name)
            new = after_fields.get(name)
            if old == new:
                continue
            delta = None
            if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                delta = new - old
            field_changes[name] = {"before": old, "after": new, "delta": delta}
        old_dirty = before.get("chunk_modified")
        new_dirty = after.get("chunk_modified")
        if old_dirty is not None and new_dirty is not None and old_dirty != new_dirty:
            field_changes["chunk_modified"] = {"before": old_dirty, "after": new_dirty, "delta": None}
        machine_changed = before.get("machine") != after.get("machine")
        if field_changes or machine_changed:
            record["status"] = "changed"
            record["machine"] = after.get("machine")
            record["fields"] = field_changes
            if machine_changed:
                record["machine_before"] = before.get("machine")
                record["machine_after"] = after.get("machine")
            changes.append(record)
    a_meta = (a.get("snapshot") or {}).get("meta") or {}
    b_meta = (b.get("snapshot") or {}).get("meta") or {}
    meta_diff = {
        key: {"a": a_meta.get(key), "b": b_meta.get(key)}
        for key in sorted(set(a_meta) | set(b_meta))
        if a_meta.get(key) != b_meta.get(key)
    }
    return {
        "a": {
            "source": a.get("snapshot", {}).get("source"),
            "captured": a.get("snapshot", {}).get("captured"),
            "meta": a_meta,
        },
        "b": {
            "source": b.get("snapshot", {}).get("source"),
            "captured": b.get("snapshot", {}).get("captured"),
            "meta": b_meta,
        },
        "meta_diff": meta_diff,
        "changes": changes,
    }


def collect(
    world: WorldSource,
    dims: List[str],
    extractor_for,
    machine_filter: Optional[str] = None,
    limit: Optional[int] = None,
    needle: bytes = None,
    jobs: int = 1,
    filter_rules=None,
    include_fallback: bool = False,
    stats=None,
    cancel=None,
    progress=None,
) -> Snapshot:
    """Walk a world and collect every tile entity matched by an extractor."""
    snapshot = Snapshot(source=str(world.path), world_name=world.name)
    count = 0
    from .world import iter_tile_entities

    for dim, chunk_x, chunk_z, te in iter_tile_entities(
        world, dims, needle=needle, jobs=jobs, stats=stats, cancel=cancel,
        progress=progress,
    ):
        extractor = extractor_for(te)
        if extractor is None:
            continue
        if not include_fallback and extractor.name == "GTMachine":
            continue
        if machine_filter and extractor.name.lower() != machine_filter.lower():
            continue
        fields = extractor.extract(te)
        entry = make_entry(
            dim,
            (chunk_x, chunk_z),
            (te.get("x"), te.get("y"), te.get("z")),
            extractor.name,
            fields,
        )
        if filter_rules and not entry_matches(entry, filter_rules):
            continue
        snapshot.entries.append(entry)
        count += 1
        if limit is not None and count >= limit:
            break
    snapshot.entries.sort(key=lambda entry: (dimension_key(entry.get("dim")), tuple(entry.get("pos") or ())))
    return snapshot
