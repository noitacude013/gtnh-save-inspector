import json
import os
import tempfile
import unittest
from pathlib import Path

from gtnh_save_inspector.cli.main import main
from gtnh_save_inspector.live import attach, convert, sampler
from gtnh_save_inspector.live.changes import diff_entries, filter_changes, format_changes

EOH_MACHINE = {
    "class": "MTEEyeOfHarmony",
    "dim": 180,
    "x": 104,
    "y": 49,
    "z": 104,
    "chunk": [6, 6],
    "chunkModified": True,
    "fields": {
        "mProgresstime": 29178,
        "mMaxProgresstime": 39850,
        "mTotalRunTime": 9256780,
        "mLastWorkingTick": 9222292,
        "recipeRunning": True,
        "currentRecipeRocketTier": 5,
        "astralArrayAmount": 0,
        "usedEU": "51075998174623996",
        "successChance": 0.2229,
        "pityChance": 0.2102,
        "shutDownReason": {"key": "structure_incomplete"},
        "checkRecipeResult": {"key": "success"},
        "stored.fluid.hydrogen": 0,
    },
}

GENERIC_MACHINE = {
    "class": "MTEAssemblyLine",
    "dim": 180,
    "x": 36,
    "y": 20,
    "z": 122,
    "chunk": [2, 7],
    "chunkModified": False,
    "fields": {
        "mProgresstime": 36,
        "mMaxProgresstime": 47,
        "mTotalRunTime": 62089140,
        "mLastWorkingTick": 62089104,
        "mEfficiency": 10000,
    },
}


class ConvertTest(unittest.TestCase):
    def test_eoh_pseudo_nbt_mapping(self):
        pseudo = convert.to_pseudo_nbt(EOH_MACHINE["fields"])
        self.assertEqual(pseudo["eyeOfHarmonyOutputrecipeRunning"], True)
        self.assertEqual(pseudo["eyeOfHarmonyOutputrocketTier"], 5)
        self.assertEqual(pseudo["eyeOfHarmonyOutputusedEU"], 51075998174623996)
        # BigInt strings become ints, other fields are kept as-is.
        self.assertEqual(pseudo["mProgresstime"], 29178)

    def test_eoh_entry(self):
        entry = convert.machine_to_entry(EOH_MACHINE)
        self.assertEqual(entry["machine"], "MTEEyeOfHarmony")
        self.assertEqual(entry["dim"], "DIM_180")
        self.assertEqual(entry["fields"]["progress"], 29178)
        self.assertEqual(entry["fields"]["max"], 39850)
        self.assertEqual(entry["fields"]["recipeRunning"], True)
        self.assertEqual(entry["fields"]["rocketTier"], 5)
        self.assertEqual(entry["fields"]["shutdown"], "structure_incomplete")
        self.assertTrue(entry["chunk_modified"])

    def test_generic_entry(self):
        entry = convert.machine_to_entry(GENERIC_MACHINE)
        self.assertEqual(entry["machine"], "GTMultiblock")
        self.assertEqual(entry["fields"]["progress"], 36)
        self.assertFalse(entry["chunk_modified"])

    def test_live_inventory_is_summarised_for_diff(self):
        entry = convert.machine_to_entry(
            {
                "class": "MTEHatchMuffler",
                "dim": 180,
                "x": 1,
                "y": 2,
                "z": 3,
                "fields": {"mTier": 1},
                "inventory": {
                    "slots": 2,
                    "slotsUsed": 1,
                    "itemCount": 5,
                    "items": [{"name": "x", "count": 5, "damage": 0}],
                },
            }
        )
        self.assertEqual(
            entry["fields"]["inventory"],
            {"slots": 2, "slotsUsed": 1, "itemCount": 5},
        )

    def test_unknown_machine_uses_fallback_name(self):
        entry = convert.machine_to_entry(
            {"class": "MTEUnknown", "dim": -1, "x": 0, "y": 0, "z": 0, "fields": {"a": 1}}
        )
        self.assertEqual(entry["machine"], "GTMachine")
        self.assertEqual(entry["fields"]["class"], "MTEUnknown")
        self.assertEqual(entry["dim"], "DIM_-1")


class ChangeFilterTest(unittest.TestCase):
    CHANGES = [
        {
            "status": "changed",
            "dim": "DIM_180",
            "pos": [1, 2, 3],
            "machine": "GTMultiblock",
            "fields": {
                "progress": {"before": 0, "after": 20, "delta": 20},
                "mUpdate": {"before": -1, "after": -21, "delta": -20},
                "shutdown": {"before": "none", "after": None, "delta": None},
            },
        }
    ]

    def test_min_delta_drops_small_deltas(self):
        result = filter_changes(self.CHANGES, min_delta=100)
        # only the non-numeric change survives
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0]["fields"]), {"shutdown"})

    def test_fields_selection(self):
        result = filter_changes(self.CHANGES, fields=["progress"])
        self.assertEqual(set(result[0]["fields"]), {"progress"})

    def test_drop_machine_when_all_fields_filtered(self):
        self.assertEqual(filter_changes(self.CHANGES, fields=["nope"]), [])


class ChangeDiffTest(unittest.TestCase):
    def test_entry_diff_and_formatting(self):
        previous = [convert.machine_to_entry(EOH_MACHINE)]
        machine = json.loads(json.dumps(EOH_MACHINE))
        machine["fields"]["mProgresstime"] += 20
        current = [convert.machine_to_entry(machine)]
        changes = diff_entries(previous, current)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["fields"]["progress"]["delta"], 20)
        lines = format_changes(changes)
        self.assertTrue(any("+20" in line for line in lines))

    def test_dimension_label_override(self):
        entry = convert.machine_to_entry(EOH_MACHINE, dim_labels={180: "PERSONAL_DIM_180"})
        self.assertEqual(entry["dim"], "PERSONAL_DIM_180")
        default = convert.machine_to_entry(EOH_MACHINE)
        self.assertEqual(default["dim"], "DIM_180")


class TecTechConvertTest(unittest.TestCase):
    def test_research_station_fields(self):
        machine = {
            "class": "MTEResearchStation",
            "dim": 180,
            "x": 1,
            "y": 2,
            "z": 3,
            "fields": {
                "machineType": "Assembly line",
                "computationRemaining": 0,
                "computationRequired": 0,
                "mProgresstime": 0,
                "mMaxProgresstime": 0,
            },
        }
        entry = convert.machine_to_entry(machine)
        self.assertEqual(entry["machine"], "ResearchStation")
        self.assertEqual(entry["fields"]["machineType"], "Assembly line")

    def test_quantum_computer_eavailable_maps_to_computation(self):
        machine = {
            "class": "MTEQuantumComputer",
            "dim": 93,
            "x": 140,
            "y": 82,
            "z": 31,
            "fields": {
                "wirelessModeEnabled": True,
                "eAvailableData": 107448,
                "mProgresstime": 7,
                "mMaxProgresstime": 20,
            },
        }
        entry = convert.machine_to_entry(machine)
        self.assertEqual(entry["machine"], "QuantumComputer")
        self.assertEqual(entry["fields"]["computation"], 107448)

    def test_data_bank(self):
        machine = {
            "class": "MTEDataBank",
            "dim": 180,
            "x": 9,
            "y": 44,
            "z": 36,
            "fields": {"wirelessModeEnabled": True, "mProgresstime": 0, "mMaxProgresstime": 0},
        }
        entry = convert.machine_to_entry(machine)
        self.assertEqual(entry["machine"], "DataBank")


class PurificationConvertTest(unittest.TestCase):
    def test_controller_fields_become_pseudo_nbt(self):
        machine = {
            "class": "MTEPurificationUnitClarifier",
            "dim": 180,
            "x": 1,
            "y": 2,
            "z": 3,
            "fields": {
                "mProgresstime": 10,
                "mMaxProgresstime": 20,
                "controllerSet": True,
                "controllerX": 10,
                "controllerY": 64,
                "controllerZ": 10,
            },
        }
        entry = convert.machine_to_entry(machine)
        self.assertEqual(entry["machine"], "PurificationUnit")
        self.assertEqual(entry["fields"]["controller"], [10, 64, 10])


class SamplerTest(unittest.TestCase):
    def test_read_samples_skips_bad_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.jsonl"
            path.write_text(
                '{"status": "no-server"}\n'
                "not json\n"
                + json.dumps({"tick": 5, "machines": [EOH_MACHINE]})
                + "\n",
                encoding="utf-8",
            )
            samples = sampler.read_samples(path)
            self.assertEqual(len(samples), 2)
            machines = sampler.machine_samples(samples)
            self.assertEqual(len(machines), 1)
            self.assertEqual(machines[0]["tick"], 5)

    def test_follow_samples_reads_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.jsonl"
            path.write_text(json.dumps({"tick": 1, "machines": []}) + "\n", encoding="utf-8")
            samples = list(sampler.follow_samples(path, max_machine_samples=1, timeout_s=5))
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0]["tick"], 1)


class ArtifactsTest(unittest.TestCase):
    def test_packaged_agent_present(self):
        jar, attach_dir = attach.default_artifact_paths()
        self.assertTrue(jar.is_file(), "missing agent jar: %s" % jar)
        self.assertTrue((attach_dir / "AttachMain.class").is_file())


class AttachGuardTest(unittest.TestCase):
    def test_invalid_pid_rejected(self):
        with self.assertRaises(attach.AttachError):
            attach.attach_agent(0, "out=x")

    def test_stop_flag_roundtrip(self):
        pid = 987654
        path = attach.request_stop(pid)
        try:
            self.assertTrue(path.is_file())
        finally:
            attach.clear_stop_flag(pid)
        self.assertFalse(path.is_file())


class CliProbeTest(unittest.TestCase):
    def test_probe_help(self):
        import contextlib
        import io

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            with self.assertRaises(SystemExit) as raised:
                main(["probe", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("dump", stream.getvalue())

    def test_probe_stop_creates_flag(self):
        import contextlib
        import io

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["probe", "stop", "--pid", "987653"])
        try:
            self.assertEqual(code, 0)
            self.assertTrue(attach.stop_flag_path(987653).is_file())
        finally:
            attach.clear_stop_flag(987653)


if __name__ == "__main__":
    unittest.main()
