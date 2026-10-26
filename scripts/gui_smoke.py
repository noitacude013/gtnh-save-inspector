#!/usr/bin/env python3
"""Start the GUI API against the fixture, exercise it, and shut it down (CI-safe)."""

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gtnh_save_inspector.gui.server import GuiServer  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "world")
FAILS = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("  " + detail if detail else ""))
    if not condition:
        FAILS.append(name)


def main() -> int:
    if not os.path.isdir(FIXTURE):
        print("fixture world missing: %s" % FIXTURE)
        return 2
    workspace = tempfile.mkdtemp(prefix="gtnh-gui-smoke-")
    old_config = os.environ.get("GTNH_INSPECTOR_CONFIG")
    os.environ["GTNH_INSPECTOR_CONFIG"] = os.path.join(workspace, "config.json")
    server = GuiServer(port=0, workspace=workspace)
    server.start()
    base = "http://127.0.0.1:%d" % server.port

    def call(method, path, body=None, auth=True):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(base + path, data=data, method=method)
        if auth:
            request.add_header("X-GTNH-Token", server.token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    try:
        import urllib.request as _request

        with _request.urlopen(base + "/?token=" + server.token, timeout=10) as response:
            html = response.read().decode("utf-8", "replace")
        check("index page", "<html" in html and "gtnh-save-inspector" in html)
        with _request.urlopen(base + "/static/app.js", timeout=10) as response:
            app_js = response.read().decode("utf-8", "replace")
        check("static app.js", "gtnh-save-inspector" in app_js or "api(" in app_js)

        status, payload = call("GET", "/api/version")
        check("version", status == 200 and payload.get("version"), str(payload))

        status, payload = call("GET", "/api/worlds?dir=" + urllib.parse.quote(os.path.dirname(FIXTURE)))
        check("worlds", status == 200 and any(w["name"] == "world" for w in payload["worlds"]))

        status, job = call("POST", "/api/jobs/scan", {"world": FIXTURE})
        check("scan start", status == 202 and job.get("id"))
        result = None
        deadline = time.time() + 30
        while time.time() < deadline:
            status, result = call("GET", "/api/jobs/" + job["id"])
            if result["status"] != "running":
                break
            time.sleep(0.1)
        entries = (result or {}).get("result", {}).get("entries", [])
        check("scan result", result["status"] == "done" and len(entries) == 3, str(len(entries)))

        status, detail = call(
            "GET",
            "/api/entry?world=%s&dim=overworld&pos=1,49,1" % urllib.parse.quote(FIXTURE),
        )
        check("entry detail", status == 200 and detail.get("machine") == "MTEEyeOfHarmony")

        status, exported = call("POST", "/api/export", {"job_id": job["id"], "format": "csv"})
        check("csv export", status == 200 and os.path.isfile(os.path.join(workspace, exported["file"])))

        status, snap = call("POST", "/api/export", {"job_id": job["id"], "format": "snapshot"})
        check("snapshot export", status == 200 and snap["summary"]["entries"] == 3)

        status, snaps = call("GET", "/api/snapshots")
        check("snapshot list", status == 200 and len(snaps["snapshots"]) == 1)
        path = snaps["snapshots"][0]["path"]
        status, diff = call("POST", "/api/diff", {"a": path, "b": path})
        check("diff", status == 200 and diff["changes"] == [])

        status, payload = call("GET", "/api/version", auth=False)
        check("token required", status == 403)

        status, payload = call("GET", "/api/download?name=../secret")
        check("download traversal blocked", status == 400)

        status, payload = call("POST", "/api/config", {"language": "en"})
        check("config", status == 200 and payload["config"]["language"] == "en")
    finally:
        server.stop()
        if old_config is None:
            os.environ.pop("GTNH_INSPECTOR_CONFIG", None)
        else:
            os.environ["GTNH_INSPECTOR_CONFIG"] = old_config
    print("%d GUI smoke check(s) failed" % len(FAILS) if FAILS else "all GUI smoke checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
