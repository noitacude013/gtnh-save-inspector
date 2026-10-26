import contextlib
import io
import os
import tempfile
import unittest

from gtnh_save_inspector.cli.main import main
from gtnh_save_inspector.extractors import find_extractor
from gtnh_save_inspector.extractors.plugins import PluginError, load_plugins, unregister

from tests.test_cli import write_world

PLUGIN_SOURCE = '''
from gtnh_save_inspector.extractors.base import Extractor


class PluginEohExtractor(Extractor):
    name = "PluginEoH"
    priority = 5
    description = "test plugin extractor"

    def matches(self, te):
        return "eyeOfHarmonyOutputrecipeRunning" in te

    def extract(self, te):
        return {
            "progress": te.get("mProgresstime"),
            "max": te.get("mMaxProgresstime"),
            "plugin": True,
        }
'''

EOH_TE = {
    "x": 1,
    "y": 49,
    "z": 2,
    "mProgresstime": 29178,
    "mMaxProgresstime": 39850,
    "mTotalRunTime": 9256780,
    "eyeOfHarmonyOutputrecipeRunning": 1,
}


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plugin = os.path.join(self.tmp.name, "my_plugin.py")
        with open(self.plugin, "w", encoding="utf-8") as handle:
            handle.write(PLUGIN_SOURCE)
        self.world = write_world(self.tmp.name, EOH_TE)

    def tearDown(self):
        unregister("PluginEoH")

    def test_load_plugin_registers_extractor(self):
        names = load_plugins([self.plugin])
        self.assertIn("PluginEoH", names)
        extractor = find_extractor(EOH_TE)
        self.assertEqual(extractor.name, "PluginEoH")
        self.assertEqual(extractor.extract(EOH_TE)["progress"], 29178)

    def test_missing_plugin_raises(self):
        with self.assertRaises(PluginError):
            load_plugins([os.path.join(self.tmp.name, "nope.py")])

    def test_plugin_without_extractor_raises(self):
        empty = os.path.join(self.tmp.name, "empty.py")
        with open(empty, "w", encoding="utf-8") as handle:
            handle.write("VALUE = 1\n")
        with self.assertRaises(PluginError):
            load_plugins([empty])

    def test_cli_plugin_flag_is_used(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["--plugin", self.plugin, "scan", "--world", self.world])
        self.assertEqual(code, 0)
        self.assertIn("PluginEoH", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
