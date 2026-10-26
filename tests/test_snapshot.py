import os
import tempfile
import unittest

from gtnh_save_inspector.core.snapshot import Snapshot, diff, load


class GzipSnapshotTest(unittest.TestCase):
    def test_gzip_roundtrip_and_diff(self):
        entries = [
            {
                "dim": "PERSONAL_DIM_180",
                "chunk": [6, 6],
                "pos": [1, 2, 3],
                "machine": "MTEEyeOfHarmony",
                "fields": {"progress": 10},
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            plain = os.path.join(tmp, "snap.json")
            compressed = os.path.join(tmp, "snap.json.gz")
            snapshot = Snapshot(source="test", world_name="w", entries=entries)
            snapshot.save(plain)
            snapshot.save(compressed, compress=True)
            self.assertTrue(os.path.getsize(compressed) < os.path.getsize(plain))
            self.assertEqual(load(plain)["entries"], entries)
            self.assertEqual(load(compressed)["entries"], entries)
            self.assertEqual(diff(load(plain), load(compressed))["changes"], [])

    def test_meta_roundtrip_and_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Snapshot(source="a", entries=[], meta={"pack": "2.8.4", "gt": "5.09.51.482"})
            second = Snapshot(source="b", entries=[], meta={"pack": "2.9.0", "gt": "5.10.0"})
            path_a = os.path.join(tmp, "a.json")
            path_b = os.path.join(tmp, "b.json")
            first.save(path_a)
            second.save(path_b)
            loaded = load(path_a)
            self.assertEqual(loaded["snapshot"]["meta"]["pack"], "2.8.4")
            result = diff(loaded, load(path_b))
            self.assertEqual(result["meta_diff"]["pack"], {"a": "2.8.4", "b": "2.9.0"})

    def test_compact_drops_none_fields(self):
        entries = [{"dim": "overworld", "pos": [1, 2, 3], "machine": "GTMultiblock",
                    "fields": {"progress": 1, "shutdown": None, "stored": {}}}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "compact.json")
            Snapshot(source="x", entries=entries).save(path, compact=True)
            fields = load(path)["entries"][0]["fields"]
            self.assertIn("progress", fields)
            self.assertNotIn("shutdown", fields)

    def test_gz_extension_implies_compression(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "snap.json.gz")
            Snapshot(source="test", entries=[]).save(path)
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(2), b"\x1f\x8b")


if __name__ == "__main__":
    unittest.main()
