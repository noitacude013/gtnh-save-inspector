import os
import tempfile
import unittest

from gtnh_save_inspector.core.world import ScanStats, open_world
from gtnh_save_inspector.core.snapshot import collect
from gtnh_save_inspector.extractors import find_extractor

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "world")


class StatsTest(unittest.TestCase):
    def test_collect_tracks_regions_and_chunks(self):
        world = open_world(FIXTURE)
        stats = ScanStats()
        snapshot = collect(world, ["overworld"], find_extractor, stats=stats)
        self.assertEqual(len(snapshot.entries), 3)
        self.assertEqual(stats.regions, 1)
        self.assertGreaterEqual(stats.chunks, 1)
        self.assertEqual(stats.parse_errors, 0)
        self.assertEqual(stats.tile_entities, 4)

    def test_needle_skips_chunks(self):
        world = open_world(FIXTURE)
        stats = ScanStats()
        collect(world, ["overworld"], find_extractor, needle=b"not-present", stats=stats)
        self.assertEqual(stats.chunks_parsed, 0)
        self.assertEqual(stats.chunks_skipped, 1)


if __name__ == "__main__":
    unittest.main()
