import struct
import unittest
import zlib

from gtnh_save_inspector.core import nbt
from gtnh_save_inspector.core.region import RegionFile, level_of, tile_entities_of

from tests._build import Raw, nbt_root

TAG_COMPOUND = 10


def chunk_nbt(chunk_x: int, chunk_z: int, tile_entities) -> dict:
    return {
        "Level": {
            "xPos": chunk_x,
            "zPos": chunk_z,
            "TileEntities": (TAG_COMPOUND, tile_entities),
        }
    }


def build_region(chunks) -> bytes:
    """chunks: {slot: (chunk_x, chunk_z, [tile entities])}"""
    header = bytearray(8192)
    body = bytearray()
    next_sector = 2
    for slot, tile_entities in chunks.items():
        payload = zlib.compress(nbt_root(chunk_nbt(0, 0, tile_entities)))
        chunk = struct.pack(">i", len(payload) + 1) + b"\x02" + payload
        sector_count = (len(chunk) + 4095) // 4096
        header[slot * 4 : slot * 4 + 3] = next_sector.to_bytes(3, "big")
        header[slot * 4 + 3] = sector_count
        body += chunk.ljust(sector_count * 4096, b"\x00")
        next_sector += sector_count
    return bytes(header) + bytes(body)


class NbtReaderTest(unittest.TestCase):
    def test_roundtrip_compound(self):
        payload = nbt_root(
            {
                "name": "Horizon",
                "count": 42,
                "long": Raw(4, 9223372036854775807),
                "ratio": 1.5,
                "nested": {"a": 1},
            }
        )
        parsed = nbt.parse_nbt(payload)
        self.assertEqual(parsed["name"], "Horizon")
        self.assertEqual(parsed["count"], 42)
        self.assertEqual(parsed["long"], 9223372036854775807)
        self.assertAlmostEqual(parsed["ratio"], 1.5)
        self.assertEqual(parsed["nested"], {"a": 1})

    def test_parse_gzip_bytes(self):
        from tests._build import gzipped

        parsed = nbt.load_bytes(gzipped({"Data": {"LevelName": "Test"}}))
        self.assertEqual(parsed["Data"]["LevelName"], "Test")

    def test_rejects_truncated_payload(self):
        payload = nbt_root({"a": 1})
        with self.assertRaises(nbt.NbtError):
            nbt.parse_nbt(payload[:-1])

    def test_sanitize_bytes(self):
        self.assertEqual(nbt.sanitize({"k": b"\x01\x02"}), {"k": {"hex": "0102"}})


class RegionReaderTest(unittest.TestCase):
    def test_reads_chunk_and_tile_entities(self):
        te = {"x": 1, "y": 64, "z": 2, "mProgresstime": 5, "mMaxProgresstime": 10}
        region = RegionFile(build_region({0: [te]}))
        chunk = region.read_chunk_nbt(0, 0)
        self.assertIsNotNone(chunk)
        self.assertEqual(level_of(chunk)["xPos"], 0)
        self.assertEqual(list(tile_entities_of(chunk))[0]["mProgresstime"], 5)

    def test_empty_slot_returns_none(self):
        region = RegionFile(build_region({}))
        self.assertIsNone(region.read_chunk_nbt(0, 0))

    def test_slot_of_matches_region_layout(self):
        self.assertEqual(RegionFile.slot_of(6, 6), 198)
        self.assertEqual(RegionFile.slot_of(6, 8), 262)
        self.assertEqual(RegionFile.region_of(104 >> 4, 136 >> 4), (0, 0))


if __name__ == "__main__":
    unittest.main()
