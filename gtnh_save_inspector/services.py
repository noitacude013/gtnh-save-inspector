"""Read-only operations shared by the CLI and the GUI API.

Keeping this layer separate from argparse/HTTP makes the GUI and the CLI use exactly the
same scan/diff/live logic (and lets tests exercise it without a browser).
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from typing import Callable, Iterable, List, Optional

from .core.snapshot import (
    Snapshot,
    collect,
    diff as diff_snapshots,
    filter_diff_changes,
    load as load_snapshot_file,
)
from .core.world import (
    ScanCancelled,
    ScanStats,
    WorldError,
    WorldSource,
    discover_worlds,
    open_world,
    read_tile_entity,
)
from .dimensions import resolve_dim
from .export import write_csv
from .extractors import find_extractor
from .filters import parse_filters, resolve_field


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def normalize_path(path) -> str:
    return os.path.normcase(os.path.realpath(os.path.expanduser(str(path))))


def _split_ignore(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ValueError("ignore must be a string or a list of strings")
    result = []
    for item in items:
        if not isinstance(item, str):
            raise ValueError("ignore entries must be strings")
        result.extend(part.strip() for part in item.split(",") if part.strip())
    return result


def validate_snapshot(payload, label="snapshot") -> dict:
    if not isinstance(payload, dict):
        raise ValueError("%s is not a JSON object" % label)
    snapshot = payload.get("snapshot") or {}
    if not isinstance(snapshot, dict):
        raise ValueError("%s header is not an object" % label)
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("%s has no entries list" % label)
    fmt = payload.get("format")
    if fmt is not None and not isinstance(fmt, int):
        raise ValueError("%s format is invalid" % label)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError("%s entry %d is not an object" % (label, index))
        fields = entry.get("fields", {})
        if not isinstance(fields, dict):
            raise ValueError("%s entry %d fields is not an object" % (label, index))
        if "dim" in entry and not isinstance(entry["dim"], str):
            raise ValueError("%s entry %d dim is not a string" % (label, index))
        if "machine" in entry and not isinstance(entry["machine"], str):
            raise ValueError("%s entry %d machine is not a string" % (label, index))
        if "pos" in entry:
            pos = entry["pos"]
            if not (isinstance(pos, list) and len(pos) == 3):
                raise ValueError("%s entry %d pos is invalid" % (label, index))
    return payload


def dims_of(world: WorldSource, requested: Optional[Iterable[str]]) -> List[str]:
    folders = list(world.dims().keys())
    requested = _as_list(requested)
    if requested:
        return [resolve_dim(name, folders) for name in requested]
    ordered = []
    if "overworld" in folders:
        ordered.append("overworld")
    ordered.extend(name for name in folders if name != "overworld")
    return ordered


def world_summary(world: WorldSource) -> dict:
    try:
        dims = sorted(world.dims())
    except Exception:
        dims = []
    try:
        info = world.level_info()
    except Exception:
        info = {}
    version = info.get("version") or info.get("Version")
    if isinstance(version, dict):
        version = version.get("Name") or version.get("name")
    if not isinstance(version, str):
        version = None
    return {
        "name": world.name,
        "path": os.path.abspath(world.path),
        "kind": world.kind,
        "dims": dims,
        "level_name": info.get("LevelName") if isinstance(info.get("LevelName"), str) else None,
        "version": version,
    }


def list_worlds(directory: str) -> List[dict]:
    directory = os.path.abspath(os.path.expanduser(directory))
    if not os.path.exists(directory):
        raise WorldError("path does not exist: %s" % directory)
    if os.path.isfile(directory) and not directory.lower().endswith(".zip"):
        raise WorldError("not a save directory or backup zip: %s" % directory)
    try:
        worlds = discover_worlds(directory)
    except (WorldError, OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return []
    result = [world_summary(world) for world in worlds]
    # Backups are plain .zip files next to the save folders; list them too.
    if os.path.isdir(directory):
        known = {item["path"] for item in result}
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if not (os.path.isfile(path) and name.lower().endswith(".zip")):
                continue
            if os.path.abspath(path) in known:
                continue
            try:
                result.append(world_summary(open_world(path)))
            except (WorldError, OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
                continue
    return result


def scan(
    world_path: str,
    dims: Optional[Iterable[str]] = None,
    mte: Optional[str] = None,
    where: Optional[Iterable[str]] = None,
    sort: Optional[str] = None,
    top: Optional[int] = None,
    limit: Optional[int] = None,
    include_fallback: bool = False,
    fast: bool = False,
    jobs: int = 1,
    with_stats: bool = False,
    progress: Optional[Callable[[float, str, int], None]] = None,
    cancel=None,
) -> dict:
    world = open_world(world_path)
    selected = dims_of(world, dims)
    rules = parse_filters(_as_list(where))
    include_fallback = include_fallback or (mte or "").lower() == "gtmachine"
    if include_fallback or (mte or "").lower() == "gtmachine":
        needle = b"mID" if fast else None
    elif (mte or "").lower() == "mteeyeofharmony":
        needle = b"eyeOfHarmonyOutput" if fast else None
    else:
        needle = b"mMaxProgresstime" if fast else None
    stats = ScanStats() if with_stats else None
    entries: List[dict] = []
    total_dims = max(1, len(selected))
    cap = None
    if not sort:
        cap = top or limit
    for index, dim in enumerate(selected):
        if cancel is not None and cancel.is_set():
            raise ScanCancelled()
        remaining = None
        if cap:
            remaining = max(1, cap - len(entries))
        def dim_progress(done, total, _index=index, _dim=dim):
            if progress is not None:
                progress(
                    (_index + (done / max(1, total))) / total_dims,
                    _dim,
                    len(entries),
                )

        snapshot = collect(
            world,
            [dim],
            find_extractor,
            machine_filter=mte,
            limit=remaining,
            needle=needle,
            jobs=jobs,
            filter_rules=rules,
            include_fallback=include_fallback,
            stats=stats,
            cancel=cancel,
            progress=dim_progress,
        )
        entries.extend(snapshot.entries)
        if progress is not None:
            progress((index + 1) / total_dims, dim, len(entries))
        if cap and len(entries) >= cap:
            entries = entries[:cap]
            break
    if sort:
        if not any(resolve_field(entry, sort) is not None for entry in entries):
            raise ValueError("no machine has field %r, cannot sort" % sort)

        def sort_key(entry):
            value = resolve_field(entry, sort)
            if isinstance(value, (int, float)):
                return (0, -value)
            return (1, str(value))

        entries.sort(key=sort_key)
    if top:
        entries = entries[:top]
    elif limit:
        entries = entries[:limit]
    return {
        "world": world_summary(world),
        "dims": selected,
        "entries": entries,
        "stats": stats.to_dict() if stats is not None else None,
    }


def entry_detail(world_path: str, dim: str, pos) -> Optional[dict]:
    world = open_world(world_path)
    dim = resolve_dim(dim, list(world.dims().keys()))
    te = read_tile_entity(world, dim, tuple(int(value) for value in pos))
    if te is None:
        return None
    extractor = find_extractor(te)
    fields = extractor.extract(te) if extractor is not None else {"raw": _squash(te)}
    return {
        "dim": dim,
        "chunk": [int(pos[0]) >> 4, int(pos[2]) >> 4],
        "pos": [te.get("x"), te.get("y"), te.get("z")],
        "machine": extractor.name if extractor is not None else "unknown",
        "fields": fields,
        "raw": _squash(te),
    }


def _squash(te):
    from .core import nbt

    return nbt.squash(te)


def capture_snapshot(
    world_path: str,
    dims: Optional[Iterable[str]] = None,
    mte: Optional[str] = None,
    where: Optional[Iterable[str]] = None,
    include_fallback: bool = False,
    fast: bool = False,
    jobs: int = 1,
    meta: Optional[dict] = None,
    progress=None,
    cancel=None,
) -> Snapshot:
    result = scan(
        world_path,
        dims=dims,
        mte=mte,
        where=where,
        include_fallback=include_fallback,
        fast=fast,
        jobs=jobs,
        progress=progress,
        cancel=cancel,
    )
    snapshot = Snapshot(
        source=result["world"]["path"],
        world_name=result["world"]["name"],
        entries=result["entries"],
        meta=dict(meta or {}),
    )
    return snapshot


def save_snapshot(snapshot: Snapshot, path: str, compact: bool = False) -> str:
    path = os.path.realpath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    snapshot.save(path, compact=compact)
    return path


def load_snapshot(path: str) -> dict:
    path = os.path.expanduser(str(path))
    return validate_snapshot(load_snapshot_file(path), str(path))


def diff_files(
    path_a: str,
    path_b: str,
    ignore: Optional[Iterable[str]] = None,
    machine: Optional[str] = None,
) -> dict:
    if not isinstance(path_a, str) or not isinstance(path_b, str):
        raise ValueError("a and b snapshot paths are required")
    if machine is not None and not isinstance(machine, str):
        raise ValueError("machine must be a string")
    ignored = _split_ignore(ignore)
    first = load_snapshot(path_a)
    second = load_snapshot(path_b)
    result = diff_snapshots(first, second)
    changes = result["changes"]
    if machine:
        wanted = machine.lower()
        changes = [
            change
            for change in changes
            if (change.get("machine") or "").lower() == wanted
            or (change.get("machine_before") or "").lower() == wanted
        ]
    if ignored:
        changes = filter_diff_changes(changes, ignored)
    return dict(result, changes=changes)


def export_csv(entries: List[dict], path: str) -> int:
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return write_csv(path, entries)


def snapshot_summary(path: str) -> dict:
    payload = load_snapshot(path)
    snapshot = payload.get("snapshot") or {}
    entries = payload.get("entries") or []
    return {
        "path": os.path.realpath(path),
        "captured": snapshot.get("captured"),
        "source": snapshot.get("source"),
        "world": snapshot.get("world"),
        "meta": snapshot.get("meta") or {},
        "entries": len(entries),
    }


def new_workspace() -> str:
    return tempfile.mkdtemp(prefix="gtnh-save-inspector-gui-")
