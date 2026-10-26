"""GUI live-probe tests with a fake attach agent (no game required)."""

import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

from gtnh_save_inspector.gui import server as server_module
from gtnh_save_inspector.gui.server import GuiServer


def fake_attach(pid, args, java=None):
    params = {}
    for part in str(args).split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            params[key] = value
    out = params.get("out")
    mode = params.get("mode")
    if not out:
        return
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if mode == "chunk":
        payload = {
            "mode": "chunk", "dim": 180, "blockX": 1, "blockZ": 1,
            "chunkX": 0, "chunkZ": 0, "isModified": True,
            "hasEntities": False, "tileEntities": 3,
        }
    elif mode == "te":
        payload = {
            "mode": "te", "dim": 180, "x": 1, "y": 2, "z": 3,
            "teClass": "BaseMetaTileEntity", "mteClass": "MTEUnknown",
            "chunkModified": True, "inventory": None, "fields": {"mProgress": 5},
        }
    else:
        payload = {
            "tick": 42,
            "machines": [
                {
                    "class": "MTEUnknown", "dim": 180, "x": 1, "y": 2, "z": 3,
                    "fields": {"mProgress": 5, "mUpdate": 1},
                }
            ],
        }
    with open(out, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


class GuiLiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.mkdtemp(prefix="gtnh-gui-live-")
        cls._old_config = os.environ.get("GTNH_INSPECTOR_CONFIG")
        os.environ["GTNH_INSPECTOR_CONFIG"] = os.path.join(cls.workspace, "config.json")
        cls._old_attach = server_module.attach_agent
        server_module.attach_agent = fake_attach
        cls.server = GuiServer(port=0, workspace=cls.workspace)
        cls.server.start()
        cls.base = "http://127.0.0.1:%d" % cls.server.port
        cls.token = cls.server.token

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        server_module.attach_agent = cls._old_attach
        if cls._old_config is None:
            os.environ.pop("GTNH_INSPECTOR_CONFIG", None)
        else:
            os.environ["GTNH_INSPECTOR_CONFIG"] = cls._old_config

    def request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("X-GTNH-Token", self.token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def wait_state(self, predicate, seconds=10):
        deadline = time.time() + seconds
        state = {}
        while time.time() < deadline:
            status, state = self.request("GET", "/api/probe/state")
            self.assertEqual(status, 200)
            if predicate(state):
                return state
            time.sleep(0.1)
        self.fail("live state did not reach expectation: %r" % state)

    def test_connect_state_stop(self):
        status, state = self.request(
            "POST",
            "/api/probe/connect",
            {"pid": os.getpid(), "all": True, "dims": [180], "interval": 100},
        )
        self.assertEqual(status, 200)
        state = self.wait_state(lambda item: item.get("samples", 0) >= 1)
        self.assertEqual(state["status"], "running")
        self.assertEqual(len(state["entries"]), 1)
        status, stopped = self.request("POST", "/api/probe/stop", {})
        self.assertEqual(status, 200)
        self.assertEqual(stopped["status"], "stopped")
        status, state = self.request("GET", "/api/probe/state")
        self.assertEqual(state["status"], "disconnected")

    def test_invalid_filter_is_400(self):
        status, payload = self.request(
            "POST", "/api/probe/connect", {"pid": os.getpid(), "until": "bogus"}
        )
        self.assertEqual(status, 400)
        self.assertIn("invalid filter", payload["error"])

    def test_inspect_requires_integers(self):
        status, _ = self.request(
            "POST", "/api/probe/chunk", {"pid": os.getpid(), "dim": 180, "x": "a", "z": 1}
        )
        self.assertEqual(status, 400)
        status, _ = self.request(
            "POST", "/api/probe/te", {"pid": os.getpid(), "dim": 180, "pos": "a,b,c"}
        )
        self.assertEqual(status, 400)

    def test_inspect_stops_active_watch(self):
        status, _ = self.request(
            "POST",
            "/api/probe/connect",
            {"pid": os.getpid(), "all": True, "dims": [180], "interval": 100},
        )
        self.assertEqual(status, 200)
        self.wait_state(lambda item: item.get("samples", 0) >= 1)
        status, chunk = self.request(
            "POST", "/api/probe/chunk", {"pid": os.getpid(), "dim": 180, "x": 1, "z": 1}
        )
        self.assertEqual(status, 200)
        self.assertTrue(chunk.get("watch_stopped"))
        self.assertTrue(chunk.get("watch_resumed"))
        state = self.wait_state(lambda item: item.get("samples", 0) >= 1)
        self.assertEqual(state["status"], "running")
        self.request("POST", "/api/probe/stop", {})


if __name__ == "__main__":
    unittest.main()
