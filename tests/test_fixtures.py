import contextlib
import io
import json
import unittest
from pathlib import Path

from gtnh_save_inspector.cli.main import main
from gtnh_save_inspector.core.snapshot import collect
from gtnh_save_inspector.core.world import open_world
from gtnh_save_inspector.extractors import find_extractor

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WORLD = FIXTURES / "world"
EXPECTED = FIXTURES / "expected_entries.json"


class FixtureWorldTest(unittest.TestCase):
    def test_golden_snapshot(self):
        self.assertTrue(WORLD.is_dir(), "fixture world missing; run tests/fixtures/build_fixture.py")
        world = open_world(str(WORLD))
        snapshot = collect(world, ["overworld"], find_extractor)
        entries = json.loads(json.dumps(snapshot.entries, ensure_ascii=False))
        expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
        self.assertEqual(entries, expected)

    def test_fallback_machines_excluded_by_default(self):
        world = open_world(str(WORLD))
        snapshot = collect(world, ["overworld"], find_extractor)
        self.assertEqual(len(snapshot.entries), 3)
        self.assertNotIn("GTMachine", {entry["machine"] for entry in snapshot.entries})

    def test_include_fallback_adds_hatches(self):
        world = open_world(str(WORLD))
        snapshot = collect(world, ["overworld"], find_extractor, include_fallback=True)
        self.assertEqual(len(snapshot.entries), 4)
        fallback = [entry for entry in snapshot.entries if entry["machine"] == "GTMachine"]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["fields"]["machineName"], "ENERGY_HATCH_ULV")
        self.assertEqual(fallback[0]["fields"]["inventory"], {"slots": 2, "slotsUsed": 2, "itemCount": 8})

    def test_machines_are_sorted(self):
        world = open_world(str(WORLD))
        snapshot = collect(world, ["overworld"], find_extractor)
        positions = [tuple(entry["pos"]) for entry in snapshot.entries]
        self.assertEqual(positions, sorted(positions))

    def test_fast_scan_filters_by_needle(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(
                [
                    "scan",
                    "--world",
                    str(WORLD),
                    "--fast",
                    "--mte",
                    "MTEEyeOfHarmony",
                ]
            )
        self.assertEqual(code, 0)
        output = stream.getvalue()
        self.assertIn("MTEEyeOfHarmony", output)
        self.assertNotIn("PurificationUnit", output)

    def test_worlds_lists_fixture(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["worlds", "--dir", str(FIXTURES)])
        self.assertEqual(code, 0)
        self.assertIn("FixtureWorld", stream.getvalue())


class PurificationExtractorTest(unittest.TestCase):
    def test_matches_unit_with_controller(self):
        te = {
            "x": 2,
            "y": 64,
            "z": 2,
            "mProgresstime": 100,
            "mMaxProgresstime": 200,
            "controller": {"x": 10, "y": 64, "z": 10},
        }
        extractor = find_extractor(te)
        self.assertEqual(extractor.name, "PurificationUnit")
        fields = extractor.extract(te)
        self.assertEqual(fields["controller"], [10, 64, 10])
        self.assertEqual(fields["progress"], 100)

    def test_does_not_match_plain_multiblock(self):
        te = {"x": 1, "y": 1, "z": 1, "mProgresstime": 1, "mMaxProgresstime": 2}
        self.assertEqual(find_extractor(te).name, "GTMultiblock")


if __name__ == "__main__":
    unittest.main()
