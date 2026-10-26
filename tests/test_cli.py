import contextlib
import io
import json
import os
import tempfile
import unittest

from gtnh_save_inspector.cli.main import main
from gtnh_save_inspector.core.world import open_world

from tests._build import gzipped, nbt_root
from tests.test_region import TAG_COMPOUND, chunk_nbt

import struct
import zlib


def write_world(root: str, te) -> str:
    world = os.path.join(root, "Horizon")
    os.makedirs(os.path.join(world, "region"), exist_ok=True)
    with open(os.path.join(world, "level.dat"), "wb") as handle:
        handle.write(gzipped({"Data": {"LevelName": "TestWorld"}}))
    payload = zlib.compress(nbt_root(chunk_nbt(0, 0, [te])))
    chunk = struct.pack(">i", len(payload) + 1) + b"\x02" + payload
    sector_count = (len(chunk) + 4095) // 4096
    header = bytearray(8192)
    header[0:3] = (2).to_bytes(3, "big")
    header[3] = sector_count
    with open(os.path.join(world, "region", "r.0.0.mca"), "wb") as handle:
        handle.write(bytes(header) + chunk.ljust(sector_count * 4096, b"\x00"))
    return world


EOH_TE = {
    "x": 1,
    "y": 49,
    "z": 2,
    "mProgresstime": 29178,
    "mMaxProgresstime": 39850,
    "mTotalRunTime": 9256780,
    "eyeOfHarmonyOutputrecipeRunning": 1,
}


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = write_world(self.tmp.name, EOH_TE)

    def run_cli(self, argv):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(argv)
        return code, stream.getvalue()

    def test_worlds_lists_world(self):
        code, output = self.run_cli(["worlds", "--dir", self.tmp.name])
        self.assertEqual(code, 0)
        self.assertIn("TestWorld", output)

    def test_show_machine(self):
        code, output = self.run_cli(["show", "--world", self.world, "--pos", "1,49,2"])
        self.assertEqual(code, 0)
        self.assertIn("MTEEyeOfHarmony", output)
        self.assertIn("29178", output)

    def test_show_json(self):
        code, output = self.run_cli(["show", "--world", self.world, "--pos", "1,49,2", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["fields"]["progress"], 29178)
        self.assertEqual(payload["machine"], "MTEEyeOfHarmony")

    def test_scan_writes_snapshot(self):
        out = os.path.join(self.tmp.name, "snapshot.json")
        code, output = self.run_cli(["scan", "--world", self.world, "--out", out])
        self.assertEqual(code, 0)
        self.assertIn("MTEEyeOfHarmony", output)
        with open(out, encoding="utf-8") as handle:
            snapshot = json.load(handle)
        self.assertEqual(len(snapshot["entries"]), 1)
        self.assertEqual(snapshot["entries"][0]["fields"]["progress"], 29178)

    def test_missing_position_returns_error(self):
        code, _output = self.run_cli(["show", "--world", self.world, "--pos", "50,10,50"])
        self.assertEqual(code, 2)

    def test_open_world_sees_dimensions(self):
        world = open_world(self.world)
        self.assertIn("overworld", world.dims())


if __name__ == "__main__":
    unittest.main()
