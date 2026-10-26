"""Read-only Anvil (.mca) region file support (Minecraft 1.7.10)."""

from __future__ import annotations

import struct

from . import nbt

SECTOR_SIZE = 4096
HEADER_SECTORS = 2  # 1024 * (offset + timestamp)
MAX_CHUNK_BYTES = 128 * 1024 * 1024


class RegionError(ValueError):
    """Raised when a region file is malformed."""


class RegionFile:
    """A single region file held in memory.

    Region files are small (a few MB), so keeping them in memory keeps the API
    simple and also lets us read them straight out of a backup zip.
    """

    def __init__(self, data: bytes, label: str = "<memory>"):
        if len(data) < SECTOR_SIZE * HEADER_SECTORS:
            raise RegionError("region file %r is too small (%d bytes)" % (label, len(data)))
        self.data = data
        self.label = label
        self._header = data[:SECTOR_SIZE]
        self._timestamps = data[SECTOR_SIZE : SECTOR_SIZE * HEADER_SECTORS]

    @classmethod
    def open(cls, path: str) -> "RegionFile":
        with open(path, "rb") as handle:
            return cls(handle.read(), label=path)

    # -- slot helpers -----------------------------------------------------
    @staticmethod
    def slot_of(chunk_x: int, chunk_z: int) -> int:
        """Slot of an absolute chunk coordinate inside its region file."""
        return (chunk_x & 31) + (chunk_z & 31) * 32

    @staticmethod
    def region_of(chunk_x: int, chunk_z: int):
        """Region coordinates (rx, rz) that contain the given chunk."""
        return chunk_x >> 5, chunk_z >> 5

    def slot_info(self, slot: int):
        """Return (sector_offset, sector_count, timestamp) or None if the slot is empty."""
        if not 0 <= slot < 1024:
            raise RegionError("slot out of range: %d" % slot)
        base = slot * 4
        offset = int.from_bytes(self._header[base : base + 3], "big")
        count = self._header[base + 3]
        if offset == 0 or count == 0:
            return None
        timestamp = struct.unpack_from(">i", self._timestamps, base)[0]
        return offset, count, timestamp

    def iter_slots(self):
        """Yield slot indexes that contain chunk data."""
        for slot in range(1024):
            if self.slot_info(slot) is not None:
                yield slot

    # -- reading ----------------------------------------------------------
    def read_slot_bytes(self, slot: int):
        """Return the decompressed chunk bytes for a slot, or None if empty."""
        info = self.slot_info(slot)
        if info is None:
            return None
        offset, count, _timestamp = info
        start = offset * SECTOR_SIZE
        if start + 5 > len(self.data):
            raise RegionError(
                "%s: slot %d points past end of file (offset %d)" % (self.label, slot, offset)
            )
        length = struct.unpack_from(">i", self.data, start)[0]
        if length <= 1 or length > MAX_CHUNK_BYTES:
            return None
        compression = self.data[start + 4]
        payload = self.data[start + 5 : start + 4 + length]
        if len(payload) != length - 1:
            raise RegionError("%s: truncated chunk at slot %d" % (self.label, slot))
        return nbt.decompress(payload, compression)

    def read_slot_nbt(self, slot: int):
        data = self.read_slot_bytes(slot)
        if data is None:
            return None
        return nbt.parse_nbt(data)

    def read_chunk_nbt(self, chunk_x: int, chunk_z: int):
        """Return the chunk NBT for absolute chunk coordinates, or None."""
        return self.read_slot_nbt(self.slot_of(chunk_x, chunk_z))

def level_of(chunk_nbt):
    """1.7.10 chunks wrap their payload in a ``Level`` compound."""
    if not isinstance(chunk_nbt, dict):
        return {}
    level = chunk_nbt.get("Level", chunk_nbt)
    return level if isinstance(level, dict) else {}


def tile_entities_of(chunk_nbt):
    """Yield tile entity compounds of a chunk (empty list when there are none)."""
    for te in level_of(chunk_nbt).get("TileEntities") or []:
        if isinstance(te, dict):
            yield te
