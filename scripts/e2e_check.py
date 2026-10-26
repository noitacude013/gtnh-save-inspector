"""End-to-end smoke test for gtnh-save-inspector.

Offline checks always run; live checks run when --pid is given (game must be running).

    python scripts/e2e_check.py --world "...\\saves\\Horizon" --pid 12345 \
        --backup "...\\backups\\2026-10-13-13-07-30.zip"

Exit code 0 when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TMP = tempfile.mkdtemp(prefix="gtnh-e2e-")
os.environ.setdefault("GTNH_INSPECTOR_CONFIG", os.path.join(TMP, "config.json"))

RESULTS = []


def run(args, timeout=180):
    return subprocess.run(
        [PY, "-m", "gtnh_save_inspector"] + args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def check(name, args, expect_code=0, contains=None, not_contains=None, timeout=180):
    try:
        result = run(args, timeout)
        output = (result.stdout or "") + (result.stderr or "")
        ok = result.returncode == expect_code
        if contains:
            ok = ok and all(text in output for text in contains)
        if not_contains:
            ok = ok and all(text not in output for text in not_contains)
        RESULTS.append((name, ok, result.returncode, output.strip()[:160]))
        return result
    except Exception as exc:  # pragma: no cover - diagnostics only
        RESULTS.append((name, False, None, repr(exc)))
        return None


def check_units():
    result = subprocess.run(
        [PY, "-m", "unittest", "discover"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    ok = result.returncode == 0 and "OK" in (result.stderr or "") + (result.stdout or "")
    RESULTS.append(("unit tests (unittest discover)", ok, result.returncode, (result.stderr or "").strip()[:160]))


def expect_file(name, path, contains=None):
    try:
        ok = os.path.isfile(path)
        text = ""
        if ok and contains:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        if contains:
            ok = ok and all(token in text for token in contains)
        RESULTS.append((name, ok, 0 if ok else 1, path))
        return text
    except Exception as exc:  # pragma: no cover
        RESULTS.append((name, False, None, repr(exc)))
        return ""


def offline_checks(world, backup):
    fixture = os.path.join(ROOT, "tests", "fixtures", "world")
    check("--version", ["--version"], contains=["gtnh-save-inspector"])
    for sub in ("worlds", "show", "scan", "diff", "dump", "extractors", "probe"):
        check("help: %s" % sub, [sub, "--help"], contains=["usage:"])
    check("extractors list", ["extractors"], contains=[
        "MTEEyeOfHarmony", "PurificationUnit", "QuantumComputer", "DataBank",
        "ResearchStation", "GTMultiblock", "GTMachine"
    ])
    check("worlds --dir", ["worlds", "--dir", os.path.dirname(world)], contains=["Horizon"])
    check("worlds --json", ["worlds", "--dir", os.path.dirname(world), "--json"], contains=['"Horizon"'])

    check("show EoH A", ["show", "--world", world, "--dim", "180", "--pos", "104,49,104"],
          contains=["MTEEyeOfHarmony", "progress"])
    result = check("show --json", ["show", "--world", world, "--dim", "180", "--pos", "104,49,104", "--json"],
                   contains=['"machine"'])
    if result is not None:
        try:
            payload = json.loads(result.stdout)
            RESULTS.append(("show --json parses", payload["fields"]["progress"] is not None, 0, ""))
        except Exception as exc:
            RESULTS.append(("show --json parses", False, None, repr(exc)))
    check("show missing position -> code 2", ["show", "--world", world, "--pos", "0,0,0"], expect_code=2)
    check("show bad position -> code 2", ["show", "--world", world, "--pos", "1,2"], expect_code=2)

    for dim in ("180", "DIM_180", "PERSONAL_DIM_180"):
        check("scan --dim %s" % dim, ["scan", "--world", world, "--dim", dim, "--mte", "MTEEyeOfHarmony"],
              contains=["MTEEyeOfHarmony"])
    check("scan --fast", ["scan", "--world", world, "--dim", "180", "--fast", "--mte", "MTEEyeOfHarmony"],
          contains=["MTEEyeOfHarmony"])
    check("scan --detail", ["scan", "--world", world, "--dim", "180", "--mte", "MTEEyeOfHarmony", "--detail"],
          contains=["progress", "stored"])
    check("scan --limit", ["scan", "--world", world, "--dim", "180", "--limit", "1"],
          contains=["1 machine"])
    check("scan --json", ["scan", "--world", world, "--dim", "180", "--mte", "MTEEyeOfHarmony", "--json"],
          contains=['"entries"'])
    check("scan --mte filter excludes", ["scan", "--world", world, "--dim", "180", "--mte", "MTEEyeOfHarmony"],
          not_contains=["PurificationUnit"])

    snap_a = os.path.join(TMP, "a.json")
    snap_b = os.path.join(TMP, "b.json")
    check("scan --out", ["scan", "--world", world, "--dim", "180", "--fast", "--out", snap_a])
    expect_file("scan --out file", snap_a, contains=['"entries"'])
    check("scan --out (repeat)", ["scan", "--world", world, "--dim", "180", "--fast", "--out", snap_b])
    expect_file("second snapshot file", snap_b, contains=['"entries"'])
    stable_a = os.path.join(TMP, "stable_a.json")
    stable_b = os.path.join(TMP, "stable_b.json")
    check("fixture snapshot A", ["scan", "--world", fixture, "--out", stable_a, "--quiet"])
    check("fixture snapshot B", ["scan", "--world", fixture, "--out", stable_b, "--quiet"])
    check("scan --where", ["scan", "--world", world, "--dim", "180", "--fast",
                           "--mte", "MTEEyeOfHarmony", "--where", "progress>0"],
          contains=["MTEEyeOfHarmony"])
    check("scan --jobs 4", ["scan", "--world", world, "--dim", "180", "--fast", "--jobs", "4",
                            "--mte", "MTEEyeOfHarmony"], contains=["MTEEyeOfHarmony"])
    check("scan QuantumComputer", ["scan", "--world", world, "--dim", "93", "--fast",
                                   "--mte", "QuantumComputer"], contains=["QuantumComputer"])
    check("scan ResearchStation", ["scan", "--world", world, "--dim", "180", "--fast",
                                   "--mte", "ResearchStation"], contains=["ResearchStation"])
    check("scan DataBank", ["scan", "--world", world, "--dim", "180", "--fast",
                            "--mte", "DataBank"], contains=["DataBank"])

    jobs_world = os.path.join(TMP, "jobs-world")
    os.makedirs(os.path.join(jobs_world, "region"), exist_ok=True)
    fixture_region = os.path.join(fixture, "region", "r.0.0.mca")
    shutil.copyfile(fixture_region, os.path.join(jobs_world, "region", "r.0.0.mca"))
    shutil.copyfile(fixture_region, os.path.join(jobs_world, "region", "r.1.0.mca"))
    jobs_a = os.path.join(TMP, "jobs1.json")
    jobs_b = os.path.join(TMP, "jobs4.json")
    check("scan --jobs 1 --out", ["scan", "--world", jobs_world,
                                  "--jobs", "1", "--out", jobs_a, "--quiet"])
    check("scan --jobs 4 --out", ["scan", "--world", jobs_world,
                                  "--jobs", "4", "--out", jobs_b, "--quiet"])
    try:
        with open(jobs_a, encoding="utf-8") as handle:
            left = json.load(handle)["entries"]
        with open(jobs_b, encoding="utf-8") as handle:
            right = json.load(handle)["entries"]
        RESULTS.append(("jobs=1 vs jobs=4 identical", left == right, 0, "%d entries" % len(left)))
    except Exception as exc:  # pragma: no cover
        RESULTS.append(("jobs=1 vs jobs=4 identical", False, None, repr(exc)))

    check("fixture scan --all", ["scan", "--world", fixture, "--all"], contains=["GTMachine(ENERGY_HATCH_ULV)"])
    fast_a = os.path.join(TMP, "fa.json")
    fast_b = os.path.join(TMP, "fb.json")
    check("fixture --all --out", ["scan", "--world", fixture, "--all", "--out", fast_a, "--quiet"])
    check("fixture --all --fast --out", ["scan", "--world", fixture, "--all", "--fast", "--out", fast_b, "--quiet"])
    try:
        with open(fast_a, encoding="utf-8") as handle:
            left = json.load(handle)["entries"]
        with open(fast_b, encoding="utf-8") as handle:
            right = json.load(handle)["entries"]
        RESULTS.append(("fast --all keeps every machine", left == right, 0, "%d entries" % len(left)))
    except Exception as exc:  # pragma: no cover
        RESULTS.append(("fast --all keeps every machine", False, None, repr(exc)))
    check("scan --top without --sort", ["scan", "--world", fixture, "--all", "--top", "2"],
          contains=["2 machine(s)"])
    check("scan --sort invalid -> code 2", ["scan", "--world", fixture,
                                            "--sort", "no_such_field"], expect_code=2,
          contains=["cannot sort"])
    check("show --raw removed -> code 2", ["show", "--world", fixture, "--pos", "1,49,1", "--raw"],
          expect_code=2)
    check("snapshot subcommand removed -> code 2", ["snapshot", "--world", fixture, "--out", "x.json"],
          expect_code=2)

    csv_path = os.path.join(TMP, "machines.csv")
    check("scan --csv", ["scan", "--world", world, "--dim", "180", "--fast",
                         "--mte", "MTEEyeOfHarmony", "--csv", csv_path, "--quiet"])
    expect_file("csv export file", csv_path, contains=["machine", "MTEEyeOfHarmony"])

    meta_path = os.path.join(TMP, "meta.json")
    check("scan --meta --compact", ["scan", "--world", world, "--dim", "180", "--fast",
                                    "--mte", "MTEEyeOfHarmony", "--meta", "pack=2.8.4",
                                    "--meta", "gt=5.09.51.482", "--compact", "--out", meta_path,
                                    "--quiet"])
    try:
        with open(meta_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        meta_ok = payload["snapshot"]["meta"] == {"pack": "2.8.4", "gt": "5.09.51.482"}
        compact_ok = all(
            value is not None for entry in payload["entries"] for value in entry["fields"].values()
        )
        RESULTS.append(("meta stored", meta_ok, 0, ""))
        RESULTS.append(("compact drops null fields", compact_ok, 0, ""))
    except Exception as exc:  # pragma: no cover
        RESULTS.append(("meta stored", False, None, repr(exc)))
        RESULTS.append(("compact drops null fields", False, None, repr(exc)))

    check("scan --stats", ["scan", "--world", world, "--dim", "180", "--fast",
                           "--mte", "MTEEyeOfHarmony", "--stats"], contains=["scan stats:"])

    check("config path", ["config", "path"], contains=["config.json"])
    check("config set world", ["config", "set", "world", world], contains=["saved"])
    check("config show", ["config", "show"], contains=["world"])
    check("show without --world uses config", ["show", "--pos", "104,49,104"],
          contains=["MTEEyeOfHarmony"])
    check("scan without --world uses config", ["scan", "--dim", "180", "--fast",
                                               "--mte", "MTEEyeOfHarmony"],
          contains=["MTEEyeOfHarmony"])

    proc = run(["scan", "--world", fixture, "--mte", "MTEEyeOfHarmony", "--json",
                "--csv", os.path.join(TMP, "json_clean.csv")])
    try:
        json.loads(proc.stdout or "")
        json_ok = proc.returncode == 0
    except Exception:
        json_ok = False
    RESULTS.append(("scan --json --csv stdout is valid JSON", json_ok, proc.returncode,
                    (proc.stdout or "")[:80]))

    check("scan --quiet --stats", ["scan", "--world", fixture, "--mte", "MTEEyeOfHarmony",
                                   "--stats", "--quiet"], contains=["scan stats"])

    check("capabilities --json", ["capabilities", "--json"],
          contains=['"commands"', '"exit_codes"', '"probe"'])
    check("extractors --json", ["extractors", "--json"], contains=['"priority"', "MTEEyeOfHarmony"])

    proc = run(["scan", "--world", fixture, "--json", "--compact-json"])
    try:
        json.loads(proc.stdout or "")
        compact_ok = proc.returncode == 0 and len((proc.stdout or "").strip().splitlines()) == 1
    except Exception:
        compact_ok = False
    RESULTS.append(("scan --compact-json", compact_ok, proc.returncode,
                    (proc.stdout or "")[:80]))

    result = run(["show", "--world", fixture, "--pos", "bad", "--json"])
    error_ok = result.returncode == 2 and '"error"' in (result.stderr or "")
    RESULTS.append(("structured JSON error", error_ok, result.returncode,
                    (result.stderr or "")[:80]))

    meta_a = os.path.join(TMP, "meta_a.json")
    meta_b = os.path.join(TMP, "meta_b.json")
    with open(meta_a, "w", encoding="utf-8") as handle:
        json.dump({"snapshot": {"source": "a", "captured": "a", "meta": {"pack": "2.8.4"}},
                   "entries": []}, handle)
    with open(meta_b, "w", encoding="utf-8") as handle:
        json.dump({"snapshot": {"source": "b", "captured": "b", "meta": {"pack": "2.9.0"}},
                   "entries": []}, handle)
    check("diff reports metadata mismatch", ["diff", "--a", meta_a, "--b", meta_b],
          contains=["metadata differs", "2.8.4", "2.9.0"])

    ign_a = os.path.join(TMP, "ign_a.json")
    ign_b = os.path.join(TMP, "ign_b.json")
    for path, progress, noise in ((ign_a, 1, 1), (ign_b, 2, 2)):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"snapshot": {"source": path, "captured": path},
                       "entries": [{"dim": "overworld", "pos": [1, 2, 3],
                                    "machine": "GTMultiblock",
                                    "fields": {"progress": progress, "noise": noise}}]},
                      handle)
    check("diff --ignore", ["diff", "--a", ign_a, "--b", ign_b, "--ignore", "noise"],
          contains=["progress"], not_contains=["noise"])
    check("diff --ignore all", ["diff", "--a", ign_a, "--b", ign_b,
                                "--ignore", "progress,noise"], contains=["no differences"])

    check("probe te invalid pos -> code 2", ["probe", "te", "--pid", "1", "--dim", "180",
                                             "--pos", "bad"], expect_code=2)
    check("scan --sort --top", ["scan", "--world", world, "--dim", "180", "--fast",
                                "--sort", "progress", "--top", "3"], contains=["progress="])
    check("scan --fields", ["scan", "--world", fixture, "--mte", "MTEEyeOfHarmony",
                            "--fields", "progress,mID"], contains=["progress"])

    gz_a = os.path.join(TMP, "gz_a")
    gz_b = os.path.join(TMP, "gz_b")
    check("scan --gzip 1", ["scan", "--world", fixture, "--gzip", "--out", gz_a, "--quiet"])
    check("scan --gzip 2", ["scan", "--world", fixture, "--gzip", "--out", gz_b, "--quiet"])
    expect_file("gzip snapshot file", gz_a + ".gz")
    check("diff gzip snapshots", ["diff", "--a", gz_a + ".gz", "--b", gz_b + ".gz"],
          contains=["no differences"])

    check("diff identical", ["diff", "--a", stable_a, "--b", stable_b], contains=["no differences"])
    check("diff --machine filter", ["diff", "--a", stable_a, "--b", stable_b,
                                    "--machine", "MTEEyeOfHarmony"], contains=["no differences"])
    check("diff --json", ["diff", "--a", stable_a, "--b", stable_b, "--json"], contains=["changes"])

    check("dump raw NBT", ["dump", "--world", world, "--dim", "180", "--pos", "104,49,104"],
          contains=["eyeOfHarmonyOutputrecipeRunning"])
    check("dump --json", ["dump", "--world", world, "--dim", "180", "--pos", "104,49,104", "--json"],
          contains=['"nbt"'])

    plugin = os.path.join(ROOT, "examples", "plugin_example.py")
    check("plugin loads", ["--plugin", plugin, "scan", "--world", world, "--dim", "180", "--limit", "1"])
    check("missing plugin -> code 2", ["--plugin", os.path.join(TMP, "nope.py"), "scan", "--world", world],
          expect_code=2, contains=["plugin error"])

    fixture = os.path.join(ROOT, "tests", "fixtures", "world")
    check("fixture scan", ["scan", "--world", fixture],
          contains=["MTEEyeOfHarmony", "PurificationUnit", "GTMultiblock"])
    check("fixture worlds", ["worlds", "--dir", os.path.join(ROOT, "tests", "fixtures")],
          contains=["FixtureWorld"])

    if backup and os.path.isfile(backup):
        backup_snap = os.path.join(TMP, "backup.json")
        check("backup zip scan", ["scan", "--world", backup, "--dim", "180", "--fast",
                                  "--mte", "MTEEyeOfHarmony", "--out", backup_snap],
              contains=["MTEEyeOfHarmony"])
        expect_file("backup snapshot file", backup_snap, contains=['"entries"'])
        check("backup vs current diff", ["diff", "--a", backup_snap, "--b", snap_b],
              contains=["change(s)"])
    else:
        RESULTS.append(("backup zip checks", True, 0, "skipped (no --backup)"))


def process_alive(pid):
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def live_checks(pid, world):
    if not process_alive(pid):
        RESULTS.append(("live checks", False, None, "pid %d is not running (game closed/crashed)" % pid))
        return
    base = ["--pid", str(pid)]
    check("probe worlds", ["probe", "worlds"] + base, contains=["GT TEs"], timeout=60)
    result = check("probe worlds --json", ["probe", "worlds", "--json"] + base, contains=['"worlds"'], timeout=60)
    if result is not None:
        try:
            payload = json.loads(result.stdout)
            with_machines = [item for item in payload["worlds"] if item["gtTes"] > 0]
            RESULTS.append(("probe worlds has loaded machines", bool(with_machines), 0, ""))
        except Exception as exc:
            RESULTS.append(("probe worlds has loaded machines", False, None, repr(exc)))

    check("probe dump (dim 180)", ["probe", "dump", "--dim", "180", "--max", "100"] + base,
          contains=["machine(s)"], not_contains=["GTMachine("], timeout=90)
    check("probe dump --all", ["probe", "dump", "--dim", "180", "--max", "200", "--all"] + base,
          contains=["GTMachine("], timeout=90)
    check("probe dump fallback filtered", ["probe", "dump", "--machine", "MTEHatchMuffler",
                                           "--max", "20"] + base,
          expect_code=1, contains=["all were filtered out"], timeout=90)
    check("probe dump fallback with --all", ["probe", "dump", "--machine", "MTEHatchMuffler",
                                             "--max", "20", "--all"] + base,
          contains=["GTMachine(MTEHatchMuffler)"], timeout=90)
    check("probe dump EoH", ["probe", "dump", "--world", world, "--dim", "180",
                             "--machine", "MTEEyeOfHarmony"] + base,
          contains=["PERSONAL_DIM_180", "MTEEyeOfHarmony", "chunkModified"], timeout=90)
    live_snap = os.path.join(TMP, "live.json")
    check("probe dump --save", ["probe", "dump", "--world", world, "--dim", "180",
                                "--machine", "MTEEyeOfHarmony", "--save", live_snap] + base,
          contains=["live snapshot written"], timeout=90)
    expect_file("probe dump snapshot file", live_snap, contains=['"entries"'])
    check("probe dump waterline", ["probe", "dump", "--world", world, "--dim", "180",
                                   "--machine", "MTEPurificationUnit"] + base,
          contains=["PurificationUnit"], timeout=90)
    check("probe dump --json", ["probe", "dump", "--world", world, "--dim", "180",
                                "--machine", "MTEEyeOfHarmony", "--json"] + base,
          contains=['"fields"'], timeout=90)
    check("probe dump --where", ["probe", "dump", "--world", world, "--dim", "180",
                                 "--machine", "MTEEyeOfHarmony", "--where", "progress>0"] + base,
          contains=["MTEEyeOfHarmony"], timeout=90)
    check("probe dump QuantumComputer", ["probe", "dump", "--dim", "93",
                                         "--machine", "MTEQuantumComputer"] + base,
          contains=["QuantumComputer"], timeout=90)
    check("probe dump ResearchStation", ["probe", "dump", "--dim", "180",
                                         "--machine", "MTEResearchStation"] + base,
          contains=["ResearchStation"], timeout=90)
    live_off = os.path.join(TMP, "off_eoh.json")
    check("offline EoH snapshot", ["scan", "--world", world, "--dim", "180", "--fast",
                                   "--mte", "MTEEyeOfHarmony", "--out", live_off, "--quiet"])
    check("live vs offline default sets agree", ["diff", "--a", live_off, "--b", live_snap],
          contains=["0 added", "0 removed"])
    check("probe watch --where", ["probe", "watch", "--world", world, "--dim", "180",
                                  "--machine", "MTEEyeOfHarmony", "--where", "progress>0",
                                  "--samples", "1", "--interval", "1000"] + base,
          contains=["MTEEyeOfHarmony"], timeout=120)
    check("probe dump --fields", ["probe", "dump", "--world", world, "--dim", "180",
                                  "--machine", "MTEEyeOfHarmony", "--fields", "progress"] + base,
          contains=["progress"], timeout=90)
    check("probe watch --min-delta filters noise", ["probe", "watch", "--dim", "180",
                                                    "--machine", "MTEIndustrialCentrifuge",
                                                    "--changes", "--min-delta", "1000",
                                                    "--samples", "2", "--interval", "1000"] + base,
          contains=["[added]"], not_contains=["(+20"], timeout=120)

    check("probe watch --changes", ["probe", "watch", "--world", world, "--dim", "180",
                                    "--machine", "MTEIndustrialCentrifuge", "--changes",
                                    "--samples", "2", "--interval", "1000"] + base,
          contains=["changes=", "totalRun"], timeout=120)
    check("probe watch default", ["probe", "watch", "--dim", "180", "--machine", "MTEEyeOfHarmony",
                                  "--samples", "1", "--interval", "1000"] + base,
          contains=["tick=", "MTEEyeOfHarmony"], timeout=120)
    check("probe watch --json", ["probe", "watch", "--dim", "180", "--machine", "MTEEyeOfHarmony",
                                 "--samples", "1", "--interval", "1000", "--json"] + base,
          contains=['"machines"'], timeout=120)
    check("probe watch --detail", ["probe", "watch", "--world", world, "--dim", "180",
                                   "--machine", "MTEEyeOfHarmony", "--detail",
                                   "--samples", "1", "--interval", "1000"] + base,
          contains=["progress"], timeout=120)
    check("probe stop", ["probe", "stop"] + base, contains=["stop requested"])

    check("probe chunk", ["probe", "chunk", "--dim", "180", "--x", "104", "--z", "104"] + base,
          contains=["isModified=", "tileEntities="], timeout=60)
    check("probe chunk unloaded", ["probe", "chunk", "--dim", "180",
                                   "--x", "460000", "--z", "460000"] + base,
          expect_code=1, contains=["chunk is not loaded"], timeout=60)
    check("probe te", ["probe", "te", "--dim", "180", "--pos", "104,49,104"] + base,
          contains=["MTEEyeOfHarmony", "inventory:"], timeout=60)
    check("probe te --json", ["probe", "te", "--dim", "180", "--pos", "104,49,104",
                              "--json"] + base,
          contains=['"fields"'], timeout=60)
    check("probe te unloaded", ["probe", "te", "--dim", "180",
                                "--pos", "460000,64,460000"] + base,
          expect_code=1, contains=["refusing to load"], timeout=60)
    check("probe te empty position", ["probe", "te", "--dim", "180", "--pos", "0,0,0"] + base,
          expect_code=1, contains=["no tile entity"], timeout=60)
    check("probe watch --until", ["probe", "watch", "--dim", "180",
                                  "--machine", "MTEEyeOfHarmony", "--until", "totalRun>0",
                                  "--interval", "1000", "--timeout", "20"] + base,
          contains=["until condition met"], timeout=120)
    until_save = os.path.join(TMP, "until_save.json")
    check("probe watch --until --save", ["probe", "watch", "--dim", "180",
                                         "--machine", "MTEEyeOfHarmony", "--until", "totalRun>0",
                                         "--save", until_save, "--interval", "1000",
                                         "--timeout", "20"] + base,
          contains=["until condition met"], timeout=120)
    expect_file("until save snapshot", until_save, contains=['"entries"'])
    check("probe dump inventory", ["probe", "dump", "--dim", "180",
                                   "--machine", "MTEEyeOfHarmony", "--json"] + base,
          contains=['"inventory"'], timeout=90)

    proc = run(["probe", "find", "--json"])
    try:
        found = json.loads(proc.stdout or "")
        find_ok = any(game.get("pid") == pid for game in found.get("games", []))
    except Exception:
        find_ok = False
    RESULTS.append(("probe find --json", find_ok, proc.returncode,
                    (proc.stdout or "")[:80]))

    check("probe dump --pid auto", ["probe", "dump", "--pid", "auto",
                                    "--machine", "MTEEyeOfHarmony", "--json"],
          contains=["MTEEyeOfHarmony"], timeout=90)

    proc = run(["probe", "watch", "--dim", "180", "--machine", "MTEEyeOfHarmony",
                "--samples", "2", "--interval", "1000", "--jsonl"] + base, timeout=120)
    try:
        lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
        parsed = [json.loads(line) for line in lines]
        jsonl_ok = proc.returncode == 0 and len(parsed) == 2 and all("machines" in row for row in parsed)
    except Exception:
        jsonl_ok = False
    RESULTS.append(("probe watch --jsonl", jsonl_ok, proc.returncode,
                    "%d lines" % len((proc.stdout or "").splitlines())))

    check("probe stop", ["probe", "stop"] + base, contains=["stop requested"])

    jdk = os.environ.get("E2E_JAVA")
    if jdk and os.path.isfile(jdk):
        check("probe --java", ["probe", "dump", "--java", jdk, "--dim", "180",
                               "--machine", "MTEEyeOfHarmony"] + base,
              contains=["MTEEyeOfHarmony"], timeout=90)
    else:
        RESULTS.append(("probe --java", True, 0, "skipped (set E2E_JAVA)"))

    check("probe invalid pid -> code 2", ["probe", "dump", "--pid", "0"], expect_code=2,
          contains=["invalid pid"])
    check("probe missing pid -> code 2", ["probe", "dump", "--pid", "999999"], expect_code=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", required=True, help="GTNH save directory")
    parser.add_argument("--backup", help="optional backup .zip to test")
    parser.add_argument("--pid", type=int, help="game JVM pid for live checks")
    parser.add_argument("--no-units", action="store_true", help="skip unit tests")
    args = parser.parse_args()

    if not args.no_units:
        check_units()
    offline_checks(args.world, args.backup)
    if args.pid:
        live_checks(args.pid, args.world)
    else:
        RESULTS.append(("live checks", True, 0, "skipped (no --pid)"))

    failures = [item for item in RESULTS if not item[1]]
    width = max(len(item[0]) for item in RESULTS) + 2
    for name, ok, code, detail in RESULTS:
        print("%s %-*s %s" % ("PASS" if ok else "FAIL", width, name, "" if ok else detail))
    print()
    print("%d/%d checks passed" % (len(RESULTS) - len(failures), len(RESULTS)))
    if failures:
        print("failed: " + ", ".join(item[0] for item in failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
