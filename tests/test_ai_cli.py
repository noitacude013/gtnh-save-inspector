import argparse
import contextlib
import io
import json
import unittest

from gtnh_save_inspector.cli.main import _describe_command, _error, build_parser


class AiCliTest(unittest.TestCase):
    def test_capabilities_include_scan_and_probe_find(self):
        parser = build_parser()
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        scan = _describe_command(sub.choices["scan"])
        flags = [flag for option in scan["options"] for flag in option["flags"]]
        self.assertIn("--json", flags)
        probe = _describe_command(sub.choices["probe"])
        self.assertIn("find", probe["subcommands"])
        self.assertIn("dump", probe["subcommands"])

    def test_error_is_json_when_json_requested(self):
        args = argparse.Namespace(json=True, jsonl=False)
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            code = _error(args, "boom")
        self.assertEqual(code, 2)
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload, {"error": "boom", "code": 2})


if __name__ == "__main__":
    unittest.main()
