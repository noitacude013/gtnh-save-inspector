import unittest

from gtnh_save_inspector.live.findgame import _VERSION, _candidate


class FindGameTest(unittest.TestCase):
    def test_unquoted_version_stops_at_next_flag(self):
        match = _VERSION.search(
            "--version GT New Horizons 2.8.4 --gameDir E:\\MC\\x --userProperties {}"
        )
        self.assertEqual(match.group(1) or match.group(2), "GT New Horizons 2.8.4")

    def test_quoted_version(self):
        match = _VERSION.search('--version "GT New Horizons 2.8.4" --gameDir "E:\\MC\\x y"')
        self.assertEqual(match.group(1) or match.group(2), "GT New Horizons 2.8.4")

    def test_candidate_extracts_fields(self):
        command = (
            "C:\\java\\windows-x86_64\\epsilon\\bin\\java.exe -Xmx8G "
            "--version GT New Horizons 2.8.4 --gameDir E:\\MC\\gtnh"
        )
        game = _candidate(1234, 512 * 1024 * 1024, command)
        self.assertEqual(game["pid"], 1234)
        self.assertEqual(game["memoryMB"], 512)
        self.assertEqual(game["instance"], "GT New Horizons 2.8.4")
        self.assertEqual(game["java"], "epsilon")
        self.assertEqual(game["game_dir"], "E:\\MC\\gtnh")


if __name__ == "__main__":
    unittest.main()
