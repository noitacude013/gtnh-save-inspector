"""GUI HTTP API integration tests (no browser required)."""

import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import socket
import shutil

from gtnh_save_inspector.gui.server import GuiServer

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tests", "fixtures", "world")
FIXTURE_ROOT = os.path.dirname(FIXTURE)


class GuiApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.mkdtemp(prefix="gtnh-gui-test-")
        cls._old_config = os.environ.get("GTNH_INSPECTOR_CONFIG")
        os.environ["GTNH_INSPECTOR_CONFIG"] = os.path.join(cls.workspace, "config.json")
        cls.server = GuiServer(port=0, workspace=cls.workspace)
        cls.server.start()
        cls.base = "http://127.0.0.1:%d" % cls.server.port
        cls.token = cls.server.token

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        if cls._old_config is None:
            os.environ.pop("GTNH_INSPECTOR_CONFIG", None)
        else:
            os.environ["GTNH_INSPECTOR_CONFIG"] = cls._old_config

    def request(self, method, path, body=None, auth=True):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if auth:
            request.add_header("X-GTNH-Token", self.token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def scan(self, body):
        status, job = self.request("POST", "/api/jobs/scan", body)
        self.assertEqual(status, 202)
        deadline = time.time() + 30
        while time.time() < deadline:
            status, result = self.request("GET", "/api/jobs/" + job["id"])
            self.assertEqual(status, 200)
            if result["status"] != "running":
                return result
            time.sleep(0.1)
        self.fail("scan job did not finish")

    def test_version_and_worlds(self):
        status, payload = self.request("GET", "/api/version")
        self.assertEqual(status, 200)
        self.assertIn("version", payload)
        status, payload = self.request(
            "GET", "/api/worlds?dir=" + urllib.parse.quote(FIXTURE_ROOT)
        )
        self.assertEqual(status, 200)
        paths = [world["path"] for world in payload["worlds"]]
        self.assertIn(os.path.abspath(FIXTURE), paths)

    def test_scan_entry_and_export(self):
        job = self.scan({"world": FIXTURE, "where": "progress>0"})
        self.assertEqual(job["status"], "done")
        entries = job["result"]["entries"]
        self.assertEqual(len(entries), 3)
        first = entries[0]
        status, detail = self.request(
            "GET",
            "/api/entry?world=%s&dim=%s&pos=%s"
            % (
                urllib.parse.quote(FIXTURE),
                urllib.parse.quote(first["dim"]),
                urllib.parse.quote(",".join(str(value) for value in first["pos"])),
            ),
        )
        self.assertEqual(status, 200)
        self.assertIn("raw", detail)

        status, exported = self.request(
            "POST", "/api/export", {"job_id": job["id"], "format": "csv", "name": "machines"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(os.path.isfile(os.path.join(self.workspace, exported["file"])))

        status, snapshot = self.request(
            "POST", "/api/export", {"job_id": job["id"], "format": "snapshot", "name": "snap"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(snapshot["summary"]["entries"], 3)

        status, payload = self.request("GET", "/api/snapshots")
        self.assertEqual(status, 200)
        self.assertTrue(payload["snapshots"])
        path = payload["snapshots"][0]["path"]
        status, diff = self.request("POST", "/api/diff", {"a": path, "b": path})
        self.assertEqual(status, 200)
        self.assertEqual(diff["changes"], [])

        status, payload = self.request(
            "GET", "/api/download?name=" + urllib.parse.quote(os.path.basename(snapshot["file"]))
        )
        self.assertEqual(status, 200)

    def test_config_roundtrip(self):
        status, payload = self.request("GET", "/api/config")
        self.assertEqual(status, 200)
        status, saved = self.request(
            "POST", "/api/config", {"language": "en", "theme": "dark"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["config"]["language"], "en")
        self.assertEqual(saved["config"]["theme"], "dark")

    def raw_get(self, path, host=None, token=None):
        port = self.server.port
        request = "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % (
            path,
            host or "127.0.0.1:%d" % port,
        )
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(request.encode("latin-1"))
            chunks = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        data = b"".join(chunks)
        head, _, body = data.partition(b"\r\n\r\n")
        status = int(head.split()[1])
        return status, body

    def test_static_traversal_and_token(self):
        # index without a token must not redirect to a URL containing the token
        status, body = self.raw_get("/")
        self.assertEqual(status, 403)
        self.assertNotIn(self.token.encode(), body)
        status, body = self.raw_get("/?token=wrong")
        self.assertEqual(status, 403)
        # allow-listed assets work
        status, body = self.raw_get("/?token=" + self.token)
        self.assertEqual(status, 200)
        self.assertIn(b"gtnh-save-inspector", body)
        status, _ = self.raw_get("/static/app.js")
        self.assertEqual(status, 200)
        # Windows-style separators / drive letters / percent-encoded traversal
        for path in (
            "/..\\..\\README.md",
            "/C:\\Windows\\win.ini",
            "/C:/Windows/win.ini",
            "/../README.md",
            "/static/%2e%2e/server.py",
        ):
            status, body = self.raw_get(path)
            self.assertIn(status, (403, 404), path)
            self.assertNotIn(b"gtnh-save-inspector", body[:200], path)

    def test_host_header_validation(self):
        status, _ = self.raw_get("/api/version", host="evil.example:80")
        self.assertEqual(status, 403)

    def test_broken_zip_is_skipped(self):
        directory = tempfile.mkdtemp(prefix="gtnh-badzip-")
        try:
            with open(os.path.join(directory, "broken.zip"), "wb") as handle:
                handle.write(b"not a zip file")
            status, payload = self.request(
                "GET", "/api/worlds?dir=" + urllib.parse.quote(directory)
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["worlds"], [])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_stop_before_start_does_not_hang(self):
        server = GuiServer(port=0, workspace=tempfile.mkdtemp(prefix="gtnh-stop-"))
        server.stop()
        self.assertTrue(server._closed)

    def test_snapshot_download_and_validation(self):
        job = self.scan({"world": FIXTURE})
        status, snap = self.request(
            "POST", "/api/export", {"job_id": job["id"], "format": "snapshot", "name": "s1"}
        )
        self.assertEqual(status, 200)
        path = snap["summary"]["path"]
        request = urllib.request.Request(
            self.base + "/api/download?path=" + urllib.parse.quote(path)
        )
        request.add_header("X-GTNH-Token", self.token)
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("filename*=UTF-8''", response.headers.get("Content-Disposition", ""))

        # unregistered paths are refused
        request = urllib.request.Request(
            self.base + "/api/download?path=" + urllib.parse.quote(FIXTURE + "/level.dat")
        )
        request.add_header("X-GTNH-Token", self.token)
        try:
            urllib.request.urlopen(request, timeout=10)
            self.fail("unregistered path was served")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 403)

        bad = os.path.join(self.workspace, "bad-snapshot.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write('{"entries": "not-a-list"}')
        status, _ = self.request("POST", "/api/snapshots/import", {"path": bad})
        self.assertEqual(status, 400)
        # a bad registered file must not break the whole list
        self.server._snapshots.append(bad)
        try:
            status, payload = self.request("GET", "/api/snapshots")
            self.assertEqual(status, 200)
            self.assertNotIn(bad, [item["path"] for item in payload["snapshots"]])
        finally:
            self.server._snapshots.remove(bad)

    def test_export_extension_not_duplicated(self):
        job = self.scan({"world": FIXTURE})
        status, result = self.request(
            "POST", "/api/export", {"job_id": job["id"], "format": "csv", "name": "named.csv"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["file"], "named.csv")

    def test_diff_validation(self):
        status, payload = self.request("POST", "/api/diff", {})
        self.assertEqual(status, 400)

    def test_snapshot_persistence_across_servers(self):
        job = self.scan({"world": FIXTURE})
        status, snap = self.request(
            "POST", "/api/export", {"job_id": job["id"], "format": "snapshot", "name": "persist"}
        )
        self.assertEqual(status, 200)
        second = GuiServer(port=0, workspace=self.workspace)
        second.start()
        try:
            request = urllib.request.Request(second.url.replace("/?token=", "/api/snapshots?token="))
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(any(item["path"].endswith("persist.json") for item in payload["snapshots"]))
        finally:
            second.stop()

    def test_diff_machine_change_and_ignore_string(self):
        left = os.path.join(self.workspace, "machine-a.json")
        right = os.path.join(self.workspace, "machine-b.json")
        with open(left, "w", encoding="utf-8") as handle:
            json.dump({"snapshot": {"source": "a", "captured": "a"}, "entries": [
                {"dim": "overworld", "pos": [1, 2, 3], "machine": "OldMachine",
                 "fields": {"progress": 1, "mUpdate": 1}}]}, handle)
        with open(right, "w", encoding="utf-8") as handle:
            json.dump({"snapshot": {"source": "b", "captured": "b"}, "entries": [
                {"dim": "overworld", "pos": [1, 2, 3], "machine": "NewMachine",
                 "fields": {"progress": 1, "mUpdate": 2}}]}, handle)
        status, result = self.request(
            "POST", "/api/diff", {"a": left, "b": right, "ignore": "mUpdate,progress"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["machine_before"], "OldMachine")
        status, result = self.request(
            "POST", "/api/diff", {"a": left, "b": right, "machine": "OldMachine"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(result["changes"]), 1)
        status, result = self.request("POST", "/api/diff", {"a": left, "b": right, "limit": 1})
        self.assertEqual(result["total_changes"], 1)
        self.assertFalse(result["truncated"])

    def test_export_names_and_chinese_download(self):
        job = self.scan({"world": FIXTURE})
        status, result = self.request(
            "POST", "/api/export", {"job_id": job["id"], "format": "csv", "name": "report.csv"}
        )
        self.assertEqual((status, result["file"]), (200, "report.csv"))
        status, result = self.request(
            "POST", "/api/export", {"job_id": job["id"], "format": "snapshot", "name": "机器"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(result["file"].endswith(".json"))
        status, _ = self.request(
            "POST", "/api/export", {"job_id": job["id"], "format": "csv", "name": 'a"b'}
        )
        self.assertEqual(status, 400)

    def test_snapshot_schema_rejects_bad_entries(self):
        bad = os.path.join(self.workspace, "bad-entry.json")
        with open(bad, "w", encoding="utf-8") as handle:
            json.dump({"snapshot": {"source": "x"}, "entries": [{"dim": 1, "pos": [1, 2]}]}, handle)
        status, _ = self.request("POST", "/api/snapshots/import", {"path": bad})
        self.assertEqual(status, 400)

    def test_worlds_scan_persists_saves_path(self):
        status, _ = self.request(
            "GET", "/api/worlds?dir=" + urllib.parse.quote(FIXTURE_ROOT)
        )
        self.assertEqual(status, 200)
        status, payload = self.request("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(
            os.path.normcase(payload["config"]["saves"]),
            os.path.normcase(os.path.abspath(FIXTURE_ROOT)),
        )

    def test_scan_persists_world(self):
        self.scan({"world": FIXTURE})
        status, payload = self.request("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(
            os.path.normcase(payload["config"]["world"]),
            os.path.normcase(os.path.abspath(FIXTURE)),
        )

    def test_world_version_and_direct_bad_zip(self):
        status, payload = self.request(
            "GET", "/api/worlds?dir=" + urllib.parse.quote(FIXTURE_ROOT)
        )
        world = next(item for item in payload["worlds"] if item["name"] == "world")
        self.assertEqual(world["version"], "1.7.10")

        directory = tempfile.mkdtemp(prefix="gtnh-badzip2-")
        try:
            broken = os.path.join(directory, "broken.zip")
            with open(broken, "wb") as handle:
                handle.write(b"not a zip")
            status, payload = self.request(
                "GET", "/api/worlds?dir=" + urllib.parse.quote(broken)
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["worlds"], [])
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_cancel_running_scan(self):
        import time
        from unittest import mock
        import gtnh_save_inspector.services as services_module

        jobs_world = tempfile.mkdtemp(prefix="gtnh-cancel-world-")
        try:
            os.makedirs(os.path.join(jobs_world, "region"), exist_ok=True)
            source = os.path.join(FIXTURE, "region", "r.0.0.mca")
            shutil.copyfile(source, os.path.join(jobs_world, "region", "r.0.0.mca"))
            shutil.copyfile(source, os.path.join(jobs_world, "region", "r.1.0.mca"))
            original = services_module.find_extractor

            def slow(te):
                time.sleep(0.2)
                return original(te)

            with mock.patch.object(services_module, "find_extractor", slow):
                status, job = self.request("POST", "/api/jobs/scan", {"world": jobs_world})
                self.assertEqual(status, 202)
                time.sleep(0.3)
                status, payload = self.request(
                    "POST", "/api/jobs/" + job["id"] + "/cancel", {}
                )
                self.assertEqual(status, 200)
                deadline = time.time() + 10
                state = {}
                while time.time() < deadline:
                    status, state = self.request("GET", "/api/jobs/" + job["id"])
                    if state["status"] != "running":
                        break
                    time.sleep(0.1)
                self.assertEqual(state["status"], "cancelled")
        finally:
            shutil.rmtree(jobs_world, ignore_errors=True)

    def test_scan_progress_updates_between_regions(self):
        import time
        from unittest import mock
        import gtnh_save_inspector.services as services_module

        jobs_world = tempfile.mkdtemp(prefix="gtnh-progress-world-")
        try:
            os.makedirs(os.path.join(jobs_world, "region"), exist_ok=True)
            source = os.path.join(FIXTURE, "region", "r.0.0.mca")
            shutil.copyfile(source, os.path.join(jobs_world, "region", "r.0.0.mca"))
            shutil.copyfile(source, os.path.join(jobs_world, "region", "r.1.0.mca"))
            original = services_module.find_extractor

            def slow(te):
                time.sleep(0.2)
                return original(te)

            with mock.patch.object(services_module, "find_extractor", slow):
                status, job = self.request("POST", "/api/jobs/scan", {"world": jobs_world})
                self.assertEqual(status, 202)
                progress = []
                deadline = time.time() + 10
                while time.time() < deadline:
                    status, state = self.request("GET", "/api/jobs/" + job["id"])
                    progress.append(state["progress"])
                    if state["status"] != "running":
                        break
                    time.sleep(0.05)
                self.assertTrue(any(0 < value < 0.95 for value in progress), progress)
        finally:
            shutil.rmtree(jobs_world, ignore_errors=True)

    def test_worlds_rejects_plain_file(self):
        status, payload = self.request(
            "GET", "/api/worlds?dir=" + urllib.parse.quote(FIXTURE + "/level.dat")
        )
        self.assertEqual(status, 400)

    def test_static_index_requires_token(self):
        status, body = self.raw_get("/static/index.html")
        self.assertEqual(status, 403)
        status, body = self.raw_get("/static/index.html?token=" + self.token)
        self.assertEqual(status, 200)

    def test_export_custom_directories(self):
        snapshot_dir = tempfile.mkdtemp(prefix="gtnh-snap-export-")
        csv_dir = tempfile.mkdtemp(prefix="gtnh-csv-export-")
        try:
            status, _ = self.request(
                "POST",
                "/api/config",
                {"snapshot_dir": snapshot_dir, "csv_dir": csv_dir},
            )
            self.assertEqual(status, 200)
            job = self.scan({"world": FIXTURE})
            status, csv_result = self.request(
                "POST", "/api/export", {"job_id": job["id"], "format": "csv", "name": "custom.csv"}
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                os.path.normcase(os.path.dirname(csv_result["path"])),
                os.path.normcase(csv_dir),
            )
            status, body = self.raw_get(
                "/api/download?path=" + urllib.parse.quote(csv_result["path"])
                + "&token=" + self.token
            )
            self.assertEqual(status, 200)
            self.assertIn(b"dim,chunk_x", body)
            status, snap_result = self.request(
                "POST", "/api/export", {"job_id": job["id"], "format": "snapshot", "name": "custom"}
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                os.path.normcase(os.path.dirname(snap_result["path"])),
                os.path.normcase(snapshot_dir),
            )
            status, body = self.raw_get(
                "/api/download?path=" + urllib.parse.quote(snap_result["path"])
                + "&token=" + self.token
            )
            self.assertEqual(status, 200)
            self.assertIn(b"entries", body)
        finally:
            self.request("POST", "/api/config", {"snapshot_dir": "", "csv_dir": ""})
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            shutil.rmtree(csv_dir, ignore_errors=True)

    def test_workspace_clean(self):
        for index in range(5):
            with open(os.path.join(self.workspace, "probe-%d.jsonl" % index), "w") as handle:
                handle.write("x")
        status, payload = self.request("POST", "/api/workspace/clean", {"keep": 2})
        self.assertEqual(status, 200)
        self.assertEqual(payload["kept"], 2)
        remaining = [
            name for name in os.listdir(self.workspace)
            if name.startswith("probe-") and name.endswith(".jsonl")
        ]
        self.assertEqual(len(remaining), 2)

    def test_invalid_gui_port(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "gtnh_save_inspector", "gui", "--port", "-1",
             "--browser", "--no-open"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot start GUI server", result.stderr)

    def test_api_validation_edges(self):
        status, _ = self.request(
            "GET", "/api/entry?world=Z:%5Cnope&pos=0,0,0"
        )
        self.assertEqual(status, 400)
        status, _ = self.request(
            "POST", "/api/diff", {"a": FIXTURE + "/level.dat", "b": FIXTURE + "/level.dat",
                                  "limit": "abc"}
        )
        self.assertEqual(status, 400)
        job = self.scan({"world": FIXTURE})
        status, _ = self.request(
            "POST", "/api/export", {"job_id": [1], "format": "csv"}
        )
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/api/config", {"pid": [1]})
        self.assertEqual(status, 400)

    def test_bad_body_types(self):
        status, payload = self.request("POST", "/api/export", [1, 2])
        self.assertEqual(status, 400)
        status, payload = self.request("POST", "/api/snapshots/import", [1])
        self.assertEqual(status, 400)

    def test_authentication_and_validation(self):
        status, payload = self.request("GET", "/api/version", auth=False)
        self.assertEqual(status, 403)
        status, payload = self.request("GET", "/api/jobs/nope")
        self.assertEqual(status, 404)
        status, payload = self.request("POST", "/api/jobs/scan", {})
        self.assertEqual(status, 400)
        status, payload = self.request("GET", "/api/download?name=../secret")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
