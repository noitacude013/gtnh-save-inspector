"""Generate the anonymous test world fixture and its golden snapshot.

Run from the repository root:

    python tests/fixtures/build_fixture.py

The fixture is a tiny 1.7.10 Anvil save (one chunk) with three machines: an Eye of
Harmony, a waterline purification unit and a generic multiblock. It contains no player
data, no UUIDs and no coordinates from a real world.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from tests._build import gzipped, nbt_root  # noqa: E402

WORLD = os.path.join(HERE, "world")
EXPECTED = os.path.join(HERE, "expected_entries.json")
TAG_COMPOUND = 10

TILE_ENTITIES = [
    {
        "id": "gregtech:gt.blockmachines",
        "x": 1,
        "y": 49,
        "z": 1,
        "mID": 15410,
        "mProgresstime": 29178,
        "mMaxProgresstime": 39850,
        "mTotalRunTime": 9256780,
        "mLastWorkingTick": 9222292,
        "eyeOfHarmonyOutputrecipeRunning": 1,
        "eyeOfHarmonyOutputrecipeSuccessChance": 0.2229,
        "eyeOfHarmonyOutputpityChance": 0.2102,
        "eyeOfHarmonyOutputrocketTier": 5,
        "eyeOfHarmonyOutputparallelAmount": 1,
        "eyeOfHarmonyOutputastralArrayAmount": 0,
        "stored.fluid.hydrogen": 0,
        "shutDownReason": {"key": "structure_incomplete"},
        "checkRecipeResult": {"key": "success"},
    },
    {
        "id": "gregtech:gt.blockmachines",
        "x": 4,
        "y": 64,
        "z": 4,
        "mID": 40,
        "Inventory": (TAG_COMPOUND, [{"Count": 5}, {"Count": 3}]),
    },
    {
        "id": "gregtech:gt.blockmachines",
        "x": 2,
        "y": 64,
        "z": 2,
        "mID": 9403,
        "mProgresstime": 100,
        "mMaxProgresstime": 200,
        "mTotalRunTime": 5000,
        "mLastWorkingTick": 4900,
        "controller": {"x": 10, "y": 64, "z": 10},
        "mEfficiency": 10000,
    },
    {
        "id": "gregtech:gt.blockmachines",
        "x": 3,
        "y": 64,
        "z": 3,
        "mID": 1,
        "mProgresstime": 36,
        "mMaxProgresstime": 47,
        "mTotalRunTime": 62089140,
        "mLastWorkingTick": 62089104,
        "mEfficiency": 10000,
    },
]


def build_region(chunk) -> bytes:
    header = bytearray(8192)
    body = bytearray()
    next_sector = 2
    payload = zlib.compress(nbt_root(chunk))
    chunk_bytes = struct.pack(">i", len(payload) + 1) + b"\x02" + payload
    sector_count = (len(chunk_bytes) + 4095) // 4096
    header[0:3] = next_sector.to_bytes(3, "big")
    header[3] = sector_count
    body += chunk_bytes.ljust(sector_count * 4096, b"\x00")
    return bytes(header) + bytes(body)


def write_world() -> None:
    os.makedirs(os.path.join(WORLD, "region"), exist_ok=True)
    with open(os.path.join(WORLD, "level.dat"), "wb") as handle:
        handle.write(
            gzipped(
                {
                    "Data": {
                        "LevelName": "FixtureWorld",
                        "version": {"Id": 19133, "Name": "1.7.10"},
                    }
                }
            )
        )
    chunk = {
        "Level": {
            "xPos": 0,
            "zPos": 0,
            "TileEntities": (TAG_COMPOUND, TILE_ENTITIES),
        }
    }
    with open(os.path.join(WORLD, "region", "r.0.0.mca"), "wb") as handle:
        handle.write(build_region(chunk))


def write_expected() -> None:
    from gtnh_save_inspector.core.snapshot import collect
    from gtnh_save_inspector.core.world import open_world
    from gtnh_save_inspector.extractors import find_extractor

    world = open_world(WORLD)
    snapshot = collect(world, ["overworld"], find_extractor)
    entries = json.loads(json.dumps(snapshot.entries, ensure_ascii=False))
    with open(EXPECTED, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print("machines in fixture:", len(entries))


if __name__ == "__main__":
    write_world()
    write_expected()
    print("fixture written to", WORLD)
