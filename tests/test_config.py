import argparse
import json
import os
import tempfile
import unittest

from gtnh_save_inspector import config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "config.json")
        self._old = os.environ.get("GTNH_INSPECTOR_CONFIG")
        os.environ["GTNH_INSPECTOR_CONFIG"] = self.path

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GTNH_INSPECTOR_CONFIG", None)
        else:
            os.environ["GTNH_INSPECTOR_CONFIG"] = self._old

    def test_path_uses_env_override(self):
        self.assertEqual(str(config.config_path()), self.path)

    def test_load_missing_is_empty(self):
        self.assertEqual(config.load(), {})

    def test_set_and_get(self):
        config.set_value("world", "/saves/Horizon")
        config.set_value("pid", "12345")
        self.assertTrue(os.path.isfile(self.path))
        self.assertEqual(config.get_value("world"), "/saves/Horizon")
        self.assertEqual(config.get_value("pid"), 12345)

    def test_apply_defaults(self):
        config.set_value("world", "/saves/Horizon")
        config.set_value("pid", "777")
        args = argparse.Namespace(world=None, pid=None, java=None, dir=None)
        config.apply_defaults(args)
        self.assertEqual(args.world, "/saves/Horizon")
        self.assertEqual(args.pid, 777)

    def test_concurrent_set_value_does_not_lose_updates(self):
        import threading

        threads = []
        for index in range(8):
            thread = threading.Thread(
                target=config.set_value, args=("key%d" % index, "value%d" % index)
            )
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        loaded = config.load()
        for index in range(8):
            self.assertEqual(loaded.get("key%d" % index), "value%d" % index)

    def test_cli_values_win(self):
        config.set_value("world", "/from/config")
        args = argparse.Namespace(world="/from/cli", pid=None, java=None, dir=None)
        config.apply_defaults(args)
        self.assertEqual(args.world, "/from/cli")


if __name__ == "__main__":
    unittest.main()
