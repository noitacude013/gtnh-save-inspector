#!/usr/bin/env python3
"""Offline smoke test for CI: exercises the CLI against the anonymous fixture.

No game, no real save and no network required; safe to run on every push.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "world")
PY = sys.executable
TMP = tempfile.mkdtemp(prefix="gtnh-ci-")
os.environ.setdefault("GTNH_INSPECTOR_CONFIG", os.path.join(TMP, "config.json"))
RESULTS = []


def run(args, timeout=120):
    return subprocess.run(
        [PY, "-m", "gtnh_save_inspector"] + args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def check(name, args, expect_code=0, contains=None, not_contains=None):
    result = run(args)
    output = (result.stdout or "") + (result.stderr or "")
    ok = result.returncode == expect_code
    if contains:
        ok = ok and all(text in output for text in contains)
    if not_contains:
        ok = ok and all(text not in output for text in not_contains)
    RESULTS.append((name, ok, result.returncode, output.strip()[:160]))
    return result


def expect_file(name, path, contains=None):
    ok = os.path.isfile(path)
    text = ""
    if ok and contains:
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            ok = False
    if ok and contains:
        ok = all(value in text for value in contains)
    RESULTS.append((name, ok, 0, path))


def write_snapshot(path, fields):
    payload = {
        "format": 1,
        "tool": "gtnh-save-inspector",
        "tool_version": "ci",
        "snapshot": {"captured": "ci", "source": path, "world": "ci"},
        "entries": [
            {
                "dim": "overworld",
                "chunk": [0, 0],
                "pos": [1, 2, 3],
                "machine": "GTMultiblock",
                "fields": fields,
            }
        ],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def main() -> int:
    if not os.path.isdir(FIXTURE):
        print("fixture world not found: %s" % FIXTURE, file=sys.stderr)
        return 2

    check("--version", ["--version"], contains=["gtnh-save-inspector"])
    check("scan fixture", ["scan", "--world", FIXTURE], contains=["3 machine(s)"])
    check("scan fixture --all", ["scan", "--world", FIXTURE, "--all"],
          contains=["GTMachine(ENERGY_HATCH_ULV)"])
    check("scan --top", ["scan", "--world", FIXTURE, "--all", "--top", "2"],
          contains=["2 machine(s)"])
    check("scan invalid --sort", ["scan", "--world", FIXTURE, "--sort", "nope"],
          expect_code=2, contains=["cannot sort"])
    check("scan --quiet --stats", ["scan", "--world", FIXTURE, "--stats", "--quiet"],
          contains=["scan stats"])

    check("capabilities --json", ["capabilities", "--json"],
          contains=['"commands"', '"exit_codes"'])
    check("extractors --json", ["extractors", "--json"],
          contains=['"priority"', "MTEEyeOfHarmony"])

    proc = run(["scan", "--world", FIXTURE, "--json", "--compact-json"])
    try:
        json.loads(proc.stdout or "")
        compact_ok = proc.returncode == 0 and len((proc.stdout or "").strip().splitlines()) == 1
    except Exception:
        compact_ok = False
    RESULTS.append(("scan --compact-json", compact_ok, proc.returncode,
                    (proc.stdout or "")[:80]))

    result = run(["show", "--world", FIXTURE, "--pos", "bad", "--json"])
    error_ok = result.returncode == 2 and '"error"' in (result.stderr or "")
    RESULTS.append(("structured JSON error", error_ok, result.returncode,
                    (result.stderr or "")[:80]))

    a = os.path.join(TMP, "a.json")
    b = os.path.join(TMP, "b.json")
    check("scan --out", ["scan", "--world", FIXTURE, "--all", "--out", a, "--quiet"])
    check("scan --out --fast", ["scan", "--world", FIXTURE, "--all", "--fast", "--out", b, "--quiet"])
    try:
        with open(a, encoding="utf-8") as handle:
            left = json.load(handle)["entries"]
        with open(b, encoding="utf-8") as handle:
            right = json.load(handle)["entries"]
        RESULTS.append(("fast --all equals normal --all", left == right, 0, "%d entries" % len(left)))
    except Exception as exc:
        RESULTS.append(("fast --all equals normal --all", False, None, repr(exc)))

    check("diff identical", ["diff", "--a", a, "--b", b], contains=["no differences"])

    # --ignore on a hand-written pair of snapshots
    left = os.path.join(TMP, "ignore_a.json")
    right = os.path.join(TMP, "ignore_b.json")
    write_snapshot(left, {"progress": 1, "noise": 1})
    write_snapshot(right, {"progress": 2, "noise": 2})
    check("diff --ignore keeps other fields", ["diff", "--a", left, "--b", right,
                                               "--ignore", "noise"],
          contains=["progress"], not_contains=["noise"])
    check("diff --ignore all fields", ["diff", "--a", left, "--b", right,
                                       "--ignore", "progress,noise"],
          contains=["no differences"])

    # gzip round-trip on the fixture
    gz = os.path.join(TMP, "gz")
    check("scan --gzip", ["scan", "--world", FIXTURE, "--gzip", "--out", gz, "--quiet"])
    try:
        with open(gz + ".gz", "rb") as handle:
            gzip_ok = handle.read(2) == b"\x1f\x8b"
    except OSError:
        gzip_ok = False
    RESULTS.append(("gzip magic", gzip_ok, 0, gz + ".gz"))

    # CSV / metadata / compact / config / JSON purity
    csv_path = os.path.join(TMP, "machines.csv")
    check("scan --csv", ["scan", "--world", FIXTURE, "--csv", csv_path, "--quiet"])
    expect_file("csv file", csv_path, contains=["machine", "MTEEyeOfHarmony"])

    meta_path = os.path.join(TMP, "meta.json")
    check("scan --meta --compact", ["scan", "--world", FIXTURE, "--meta", "pack=ci",
                                   "--compact", "--out", meta_path, "--quiet"])
    try:
        with open(meta_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        meta_ok = payload["snapshot"]["meta"] == {"pack": "ci"}
        compact_ok = all(
            value is not None
            for entry in payload["entries"]
            for value in entry["fields"].values()
        )
        RESULTS.append(("meta stored", meta_ok, 0, ""))
        RESULTS.append(("compact omits null fields", compact_ok, 0, ""))
    except Exception as exc:
        RESULTS.append(("meta stored", False, None, repr(exc)))
        RESULTS.append(("compact omits null fields", False, None, repr(exc)))

    check("config set world", ["config", "set", "world", FIXTURE], contains=["saved"])
    check("show without --world", ["show", "--pos", "1,49,1"], contains=["MTEEyeOfHarmony"])
    check("scan without --world", ["scan", "--all"], contains=["machine(s)"])

    proc = run(["scan", "--world", FIXTURE, "--json", "--csv", os.path.join(TMP, "purity.csv")])
    try:
        json.loads(proc.stdout or "")
        purity_ok = proc.returncode == 0
    except Exception:
        purity_ok = False
    RESULTS.append(("json stdout is valid with --csv", purity_ok, proc.returncode,
                    (proc.stdout or "")[:80]))

    failed = [row for row in RESULTS if not row[1]]
    for name, ok, code, detail in RESULTS:
        print("%s %-36s %s" % ("PASS" if ok else "FAIL", name, detail))
    print("\n%d/%d offline checks passed" % (len(RESULTS) - len(failed), len(RESULTS)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
