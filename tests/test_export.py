import csv
import os
import tempfile
import unittest

from gtnh_save_inspector.export import write_csv


class CsvExportTest(unittest.TestCase):
    ENTRIES = [
        {
            "dim": "PERSONAL_DIM_180",
            "chunk": [6, 6],
            "pos": [104, 49, 104],
            "machine": "MTEEyeOfHarmony",
            "chunk_modified": True,
            "fields": {"progress": 100, "max": 200, "stored": {"fluid.hydrogen": 5}},
        },
        {
            "dim": "PERSONAL_DIM_180",
            "chunk": [6, 8],
            "pos": [104, 49, 136],
            "machine": "GTMultiblock",
            "fields": {"progress": 10, "shutdown": "power_loss"},
        },
    ]

    def test_csv_columns_and_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "machines.csv")
            rows = write_csv(path, self.ENTRIES)
            self.assertEqual(rows, 2)
            with open(path, encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                data = list(reader)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["machine"], "MTEEyeOfHarmony")
            self.assertEqual(data[0]["progress"], "100")
            self.assertEqual(data[0]["chunk_modified"], "True")
            # nested dict is JSON encoded
            self.assertIn("fluid.hydrogen", data[0]["stored"])
            self.assertEqual(data[1]["shutdown"], "power_loss")


if __name__ == "__main__":
    unittest.main()
