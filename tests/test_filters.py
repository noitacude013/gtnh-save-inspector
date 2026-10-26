import unittest

from gtnh_save_inspector.filters import (
    filter_entries,
    matches,
    parse_filters,
    parse_where,
    resolve_field,
)


class ParseWhereTest(unittest.TestCase):
    def test_numeric_expression(self):
        self.assertEqual(parse_where("progress>0"), ("progress", ">", 0))
        self.assertEqual(parse_where("totalRun<=-5"), ("totalRun", "<=", -5))
        self.assertEqual(parse_where("mEfficiency = 10000"), ("mEfficiency", "=", 10000))

    def test_string_and_bool_values(self):
        self.assertEqual(parse_where("machine=GTMultiblock"), ("machine", "=", "GTMultiblock"))
        self.assertEqual(parse_where("chunk_modified=true"), ("chunk_modified", "=", True))
        self.assertEqual(parse_where('shutdown!="none"'), ("shutdown", "!=", "none"))

    def test_invalid_expression(self):
        with self.assertRaises(ValueError):
            parse_where("progress")
        with self.assertRaises(ValueError):
            parse_where(">0")

    def test_parse_multiple(self):
        rules = parse_filters(["progress>0", "machine=GTMultiblock"])
        self.assertEqual(len(rules), 2)


class ResolveFieldTest(unittest.TestCase):
    ENTRY = {
        "machine": "MTEEyeOfHarmony",
        "dim": "PERSONAL_DIM_180",
        "chunk_modified": True,
        "fields": {"progress": 100, "stored": {"fluid": {"hydrogen": 5}}},
    }

    def test_entry_level_field(self):
        self.assertEqual(resolve_field(self.ENTRY, "machine"), "MTEEyeOfHarmony")

    def test_fields_level_field(self):
        self.assertEqual(resolve_field(self.ENTRY, "progress"), 100)

    def test_dotted_path(self):
        self.assertEqual(resolve_field(self.ENTRY, "stored.fluid.hydrogen"), 5)

    def test_missing_field_is_none(self):
        self.assertIsNone(resolve_field(self.ENTRY, "nope.deep.path"))


class MatchTest(unittest.TestCase):
    ENTRIES = [
        {"machine": "GTMultiblock", "fields": {"progress": 10, "totalRun": 100}},
        {"machine": "GTMultiblock", "fields": {"progress": 0, "totalRun": 0}},
        {"machine": "MTEEyeOfHarmony", "fields": {"progress": 500, "totalRun": 900}},
    ]

    def test_single_rule(self):
        rules = parse_filters(["progress>0"])
        self.assertEqual(len(filter_entries(self.ENTRIES, rules)), 2)

    def test_and_semantics(self):
        rules = parse_filters(["progress>0", "machine=GTMultiblock"])
        result = filter_entries(self.ENTRIES, rules)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["fields"]["totalRun"], 100)

    def test_missing_field_never_matches(self):
        rules = parse_filters(["shutdown=power_loss"])
        self.assertEqual(filter_entries(self.ENTRIES, rules), [])

    def test_no_rules_keeps_everything(self):
        self.assertEqual(len(filter_entries(self.ENTRIES, [])), 3)


if __name__ == "__main__":
    unittest.main()
