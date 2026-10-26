import os
import tempfile
import unittest

from gtnh_save_inspector.core.snapshot import collect
from gtnh_save_inspector.core.world import DirectoryWorld
from gtnh_save_inspector.extractors import find_extractor
from gtnh_save_inspector.filters import parse_filters

from tests.test_region import build_region


def machine(x, z):
    return {
        "x": x,
        "y": 64,
        "z": z,
        "mProgresstime": 10,
        "mMaxProgresstime": 20,
        "mTotalRunTime": 1000,
    }


class ParallelScanTest(unittest.TestCase):
    def test_jobs_matches_sequential(self):
        with tempfile.TemporaryDirectory() as tmp:
            world_dir = os.path.join(tmp, "world")
            os.makedirs(os.path.join(world_dir, "region"))
            for name, x in (("r.0.0.mca", 1), ("r.1.0.mca", 17), ("r.2.0.mca", 33)):
                with open(os.path.join(world_dir, "region", name), "wb") as handle:
                    handle.write(build_region({0: [machine(x, 1)]}))
            world = DirectoryWorld(world_dir)
            sequential = collect(world, ["overworld"], find_extractor, jobs=1).entries
            parallel = collect(world, ["overworld"], find_extractor, jobs=4).entries
            self.assertEqual(len(sequential), 3)
            self.assertEqual(sequential, parallel)

    def test_limit_applies_after_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            world_dir = os.path.join(tmp, "world")
            os.makedirs(os.path.join(world_dir, "region"))
            idle = machine(1, 1)
            idle["mProgresstime"] = 0
            running = machine(2, 2)
            running["mProgresstime"] = 10
            with open(os.path.join(world_dir, "region", "r.0.0.mca"), "wb") as handle:
                handle.write(build_region({0: [idle, running]}))
            world = DirectoryWorld(world_dir)
            entries = collect(
                world,
                ["overworld"],
                find_extractor,
                limit=1,
                filter_rules=parse_filters(["progress>0"]),
            ).entries
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["fields"]["progress"], 10)

    def test_parallel_with_needle(self):
        with tempfile.TemporaryDirectory() as tmp:
            world_dir = os.path.join(tmp, "world")
            os.makedirs(os.path.join(world_dir, "region"))
            with open(os.path.join(world_dir, "region", "r.0.0.mca"), "wb") as handle:
                handle.write(build_region({0: [machine(1, 1)]}))
            world = DirectoryWorld(world_dir)
            entries = collect(
                world, ["overworld"], find_extractor, jobs=2, needle=b"mMaxProgresstime"
            ).entries
            self.assertEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()
