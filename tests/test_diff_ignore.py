import unittest

from gtnh_save_inspector.core.snapshot import filter_diff_changes


def change(status="changed", fields=None):
    return {"status": status, "dim": "overworld", "pos": [1, 2, 3], "fields": fields or {}}


class DiffIgnoreTest(unittest.TestCase):
    def test_ignored_fields_are_removed(self):
        result = filter_diff_changes(
            [change(fields={"progress": {"before": 1, "after": 2, "delta": 1},
                            "noise": {"before": 1, "after": 2, "delta": 1}})],
            {"noise"},
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(list(result[0]["fields"]), ["progress"])

    def test_entry_dropped_when_all_fields_ignored(self):
        result = filter_diff_changes([change(fields={"noise": {"before": 1, "after": 2}})],
                                     {"noise"})
        self.assertEqual(result, [])

    def test_added_and_removed_are_kept(self):
        result = filter_diff_changes([change("added"), change("removed")], {"progress"})
        self.assertEqual([row["status"] for row in result], ["added", "removed"])

    def test_no_ignore_returns_same_list(self):
        original = [change(fields={"a": {}})]
        self.assertIs(filter_diff_changes(original), original)


if __name__ == "__main__":
    unittest.main()
