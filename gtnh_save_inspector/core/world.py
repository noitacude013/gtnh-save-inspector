"""World save sources: a directory, or a backup .zip, with dimension/region discovery."""

from __future__ import annotations

import os
import re
import threading
import zipfile
from typing import Dict, Iterable, List, Optional, Tuple

from . import nbt
from .region import RegionFile, level_of, tile_entities_of

REGION_RE = re.compile(r"(?P<dir>.+?)/region/r\.(?P<rx>-?\d+)\.(?P<rz>-?\d+)\.mca$")


class ScanCancelled(Exception):
    """Raised when a caller cancels a long scan."""


class ScanStats:
    """Counters for one scan (thread-safe: parallel region parsing updates it)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.regions = 0
        self.chunks = 0
        self.chunks_skipped = 0
        self.chunks_parsed = 0
        self.parse_errors = 0
        self.tile_entities = 0

    def add(self, **values):
        with self._lock:
            for key, value in values.items():
                setattr(self, key, getattr(self, key) + value)

    def to_dict(self):
        return {
            "regions": self.regions,
            "chunks": self.chunks,
            "chunks_skipped": self.chunks_skipped,
            "chunks_parsed": self.chunks_parsed,
            "parse_errors": self.parse_errors,
            "tile_entities": self.tile_entities,
        }


class WorldError(ValueError):
    """Raised when a world/backup source cannot be opened."""


class WorldSource:
    """Abstract access to a world save (directory or zip), read-only."""

    kind = "unknown"

    def __init__(self, path: str):
        self.path = path

    def read(self, relpath: str) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError

    def exists(self, relpath: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def entries(self) -> List[str]:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def name(self) -> str:
        base = os.path.basename(self.path.rstrip("\\/"))
        if base.lower().endswith(".zip"):
            base = base[:-4]
        return base

    # -- dimensions -------------------------------------------------------
    def dims(self) -> Dict[str, str]:
        """Map dimension name -> dimension root prefix ("" for the overworld)."""
        raise NotImplementedError

    def region_entries(self, dim: str) -> List[Tuple[str, int, int]]:
        """List (relpath, region_x, region_z) for a dimension."""
        raise NotImplementedError

    def open_region(self, relpath: str) -> RegionFile:
        return RegionFile(self.read(relpath), label=relpath)

    def level_info(self) -> dict:
        raw = nbt.load_bytes(self.read("level.dat")) if self.exists("level.dat") else {}
        data = raw.get("Data", raw) if isinstance(raw, dict) else {}
        return data if isinstance(data, dict) else {}


class DirectoryWorld(WorldSource):
    kind = "directory"

    def __init__(self, root: str):
        super().__init__(root)
        if not os.path.isdir(root):
            raise WorldError("not a directory: %s" % root)

    def _abs(self, relpath: str) -> str:
        return os.path.join(self.path, relpath.replace("/", os.sep))

    def read(self, relpath: str) -> bytes:
        with open(self._abs(relpath), "rb") as handle:
            return handle.read()

    def exists(self, relpath: str) -> bool:
        return os.path.isfile(self._abs(relpath))

    def entries(self) -> List[str]:
        found = []
        for root, _dirs, files in os.walk(self.path):
            for filename in files:
                full = os.path.join(root, filename)
                found.append(os.path.relpath(full, self.path).replace(os.sep, "/"))
        return found

    def dims(self) -> Dict[str, str]:
        result = {}
        if os.path.isdir(os.path.join(self.path, "region")):
            result["overworld"] = ""
        for name in sorted(os.listdir(self.path)):
            sub = os.path.join(self.path, name)
            if os.path.isdir(sub) and os.path.isdir(os.path.join(sub, "region")):
                result[name] = name
        return result

    def region_entries(self, dim: str) -> List[Tuple[str, int, int]]:
        prefix = "" if dim == "overworld" else dim + "/"
        region_dir = os.path.join(self.path, prefix, "region")
        if not os.path.isdir(region_dir):
            return []
        found = []
        for filename in sorted(os.listdir(region_dir)):
            match = re.fullmatch(r"r\.(-?\d+)\.(-?\d+)\.mca", filename)
            if match:
                found.append(
                    (prefix + "region/" + filename, int(match.group(1)), int(match.group(2)))
                )
        return found


class ZipWorld(WorldSource):
    kind = "zip-backup"

    def __init__(self, path: str, world_root: Optional[str] = None):
        super().__init__(path)
        if not os.path.isfile(path):
            raise WorldError("not a file: %s" % path)
        self._zip = zipfile.ZipFile(path)
        names = self._zip.namelist()
        self._names = names
        self._name_set = set(names)
        self._world_root = world_root or self._detect_world_root(names)

    @staticmethod
    def _detect_world_root(names: Iterable[str]) -> str:
        candidates = sorted(
            name[: -len("level.dat")] for name in names if name.endswith("/level.dat")
        )
        if not candidates:
            raise WorldError("backup does not contain a level.dat")
        # Prefer the world that also has region files.
        for root in candidates:
            if any(name.startswith(root + "region/") for name in names):
                return root
        return candidates[0]

    def read(self, relpath: str) -> bytes:
        with self._zip.open(self._world_root + relpath) as handle:
            return handle.read()

    def exists(self, relpath: str) -> bool:
        return (self._world_root + relpath) in self._name_set

    def entries(self) -> List[str]:
        prefix = self._world_root
        return [name[len(prefix) :] for name in self._names if name.startswith(prefix)]

    def dims(self) -> Dict[str, str]:
        result = {}
        prefix = self._world_root
        for name in self._names:
            if not name.startswith(prefix + "region/r."):
                continue
            result["overworld"] = ""
            break
        for name in self._names:
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix) :]
            match = REGION_RE.fullmatch(rest)
            if match:
                result[match.group("dir")] = match.group("dir")
        return result

    def region_entries(self, dim: str) -> List[Tuple[str, int, int]]:
        prefix = "" if dim == "overworld" else dim + "/"
        found = []
        for rest in self.entries():
            if not rest.startswith(prefix):
                continue
            match = REGION_RE.fullmatch(rest)
            if match:
                found.append((rest, int(match.group("rx")), int(match.group("rz"))))
        found.sort()
        return found


def open_world(path: str) -> WorldSource:
    """Open a save directory or a GTNH backup zip."""
    if os.path.isdir(path):
        return DirectoryWorld(path)
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        return ZipWorld(path)
    raise WorldError("unsupported world source: %s" % path)


def discover_worlds(path: str) -> List[WorldSource]:
    """Discover save directories below *path* (a save, a saves folder, or an instance)."""
    if os.path.isdir(path):
        if os.path.isfile(os.path.join(path, "level.dat")):
            return [DirectoryWorld(path)]
        result = []
        for name in sorted(os.listdir(path)):
            candidate = os.path.join(path, name)
            if os.path.isfile(os.path.join(candidate, "level.dat")):
                result.append(DirectoryWorld(candidate))
        if result:
            return result
        nested = []
        for name in sorted(os.listdir(path)):
            candidate = os.path.join(path, name)
            if os.path.isdir(candidate):
                for child in sorted(os.listdir(candidate)):
                    world = os.path.join(candidate, child)
                    if os.path.isfile(os.path.join(world, "level.dat")):
                        nested.append(DirectoryWorld(world))
        return nested
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        return [ZipWorld(path)]
    raise WorldError("unsupported path: %s" % path)


def read_tile_entity(world: WorldSource, dim: str, pos: Tuple[int, int, int]):
    """Find the tile entity at an absolute block position inside a dimension."""
    x, y, z = pos
    chunk_x, chunk_z = x >> 4, z >> 4
    region_x, region_z = chunk_x >> 5, chunk_z >> 5
    relpath = "%sregion/r.%d.%d.mca" % ("" if dim == "overworld" else dim + "/", region_x, region_z)
    if not world.exists(relpath):
        return None
    region = world.open_region(relpath)
    chunk = region.read_chunk_nbt(chunk_x, chunk_z)
    if chunk is None:
        return None
    for te in tile_entities_of(chunk):
        if (te.get("x"), te.get("y"), te.get("z")) == pos:
            return te
    return None


def _iter_region(
    world: WorldSource, dim: str, relpath: str, needle: bytes = None, stats=None, cancel=None
):
    if stats is not None:
        stats.add(regions=1)
    region = world.open_region(relpath)
    for slot in region.iter_slots():
        if cancel is not None and cancel.is_set():
            raise ScanCancelled()
        if stats is not None:
            stats.add(chunks=1)
        try:
            raw = region.read_slot_bytes(slot)
        except Exception:
            if stats is not None:
                stats.add(parse_errors=1)
            continue
        if raw is None:
            continue
        if needle is not None and needle not in raw:
            if stats is not None:
                stats.add(chunks_skipped=1)
            continue
        try:
            chunk = nbt.parse_nbt(raw)
        except Exception:
            if stats is not None:
                stats.add(parse_errors=1)
            continue
        if stats is not None:
            stats.add(chunks_parsed=1)
        level = level_of(chunk)
        chunk_x = level.get("xPos")
        chunk_z = level.get("zPos")
        for te in tile_entities_of(chunk):
            if stats is not None:
                stats.add(tile_entities=1)
            yield dim, chunk_x, chunk_z, te


def iter_tile_entities(
    world: WorldSource, dims: List[str], needle: bytes = None, jobs: int = 1,
    stats=None, cancel=None, progress=None,
):
    """Yield (dim, chunk_x, chunk_z, tile_entity) for every tile entity in the dimensions.

    When ``needle`` is given, chunks whose decompressed bytes do not contain it are skipped
    before NBT parsing (a large speed-up on big dimensions). ``jobs > 1`` parses region
    files in parallel threads (directory worlds only; zip backups stay sequential).
    """
    tasks = []
    for dim in dims:
        for relpath, _rx, _rz in world.region_entries(dim):
            tasks.append((dim, relpath))
    total = len(tasks)
    if jobs <= 1 or world.kind != "directory" or len(tasks) <= 1:
        for index, (dim, relpath) in enumerate(tasks):
            for item in _iter_region(world, dim, relpath, needle, stats, cancel):
                yield item
            if progress is not None:
                progress(index + 1, total)
        return
    from concurrent.futures import ThreadPoolExecutor

    def parse(indexed):
        index, task = indexed
        items = list(_iter_region(world, task[0], task[1], needle, stats, cancel))
        if progress is not None:
            progress(index + 1, total)
        return items

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for region_items in pool.map(parse, enumerate(tasks)):
            for item in region_items:
                yield item
