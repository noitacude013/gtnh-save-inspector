import unittest

from gtnh_save_inspector.dimensions import (
    dimension_id_of,
    dimension_key,
    label_for_id,
    resolve_dim,
)
from gtnh_save_inspector.core.snapshot import diff


class DimensionTest(unittest.TestCase):
    def test_id_of_labels(self):
        self.assertEqual(dimension_id_of("PERSONAL_DIM_180"), 180)
        self.assertEqual(dimension_id_of("DIM-1"), -1)
        self.assertEqual(dimension_id_of("DIM_180"), 180)
        self.assertEqual(dimension_id_of("DIM1"), 1)
        self.assertEqual(dimension_id_of("overworld"), 0)
        self.assertIsNone(dimension_id_of("something"))

    def test_label_for_id(self):
        folders = ["PERSONAL_DIM_180", "DIM-1", "DIM1", "DIM_42"]
        self.assertEqual(label_for_id(180, folders), "PERSONAL_DIM_180")
        self.assertEqual(label_for_id(-1, folders), "DIM-1")
        self.assertEqual(label_for_id(42, folders), "DIM_42")
        self.assertEqual(label_for_id(0, folders), "overworld")
        self.assertEqual(label_for_id(7, folders), "DIM_7")

    def test_resolve_dim_accepts_numbers(self):
        folders = ["PERSONAL_DIM_180", "DIM-1"]
        self.assertEqual(resolve_dim("180", folders), "PERSONAL_DIM_180")
        self.assertEqual(resolve_dim("-1", folders), "DIM-1")
        self.assertEqual(resolve_dim("PERSONAL_DIM_180", folders), "PERSONAL_DIM_180")
        self.assertEqual(resolve_dim("nope", folders), "nope")

    def test_canonical_key(self):
        self.assertEqual(dimension_key("PERSONAL_DIM_180"), dimension_key("DIM_180"))
        self.assertEqual(dimension_key("overworld"), dimension_key("DIM_0"))
        self.assertNotEqual(dimension_key("PERSONAL_DIM_180"), dimension_key("PERSONAL_DIM_181"))

    def test_diff_matches_offline_and_live_labels(self):
        offline = {
            "snapshot": {"source": "save", "captured": "a"},
            "entries": [
                {
                    "dim": "PERSONAL_DIM_180",
                    "pos": [104, 49, 104],
                    "machine": "MTEEyeOfHarmony",
                    "fields": {"progress": 29178, "totalRun": 9256780},
                }
            ],
        }
        live = {
            "snapshot": {"source": "live:1", "captured": "b"},
            "entries": [
                {
                    "dim": "DIM_180",
                    "pos": [104, 49, 104],
                    "machine": "MTEEyeOfHarmony",
                    "fields": {"progress": 29300, "totalRun": 9257000},
                }
            ],
        }
        result = diff(offline, live)
        self.assertEqual(len(result["changes"]), 1)
        change = result["changes"][0]
        self.assertEqual(change["status"], "changed")
        self.assertEqual(change["dim"], "DIM_180")
        self.assertEqual(change["fields"]["progress"]["delta"], 122)
        self.assertEqual(change["pos"], [104, 49, 104])


if __name__ == "__main__":
    unittest.main()
