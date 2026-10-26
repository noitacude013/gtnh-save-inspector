import unittest

from gtnh_save_inspector.core.snapshot import diff
from gtnh_save_inspector.extractors import find_extractor, extractor_names

EOH_TE = {
    "x": 104,
    "y": 49,
    "z": 104,
    "mProgresstime": 29178,
    "mMaxProgresstime": 39850,
    "mTotalRunTime": 9256780,
    "mLastWorkingTick": 9222292,
    "eyeOfHarmonyOutputrecipeRunning": 1,
    "eyeOfHarmonyOutputrocketTier": 5,
    "eyeOfHarmonyOutputastralArrayAmount": 0,
    "stored.fluid.hydrogen": 0,
    "shutDownReason": {"key": "structure_incomplete"},
    "checkRecipeResult": {"key": "success"},
}

GENERIC_TE = {
    "x": 1,
    "y": 64,
    "z": 1,
    "mProgresstime": 100,
    "mMaxProgresstime": 200,
    "mTotalRunTime": 5000,
    "mLastWorkingTick": 4900,
    "mEfficiency": 10000,
    "mEUT": -2048,
    "mID": 13532,
    "powerPanelMaxParallel": 4,
    "mInputDisabled": 1,
    "mOwnerName": "tester",
    "customScalar": 42,
    "makePowerfailEvents": True,
}


class ExtractorTest(unittest.TestCase):
    def test_registry(self):
        self.assertIn("MTEEyeOfHarmony", extractor_names())
        self.assertIn("GTMultiblock", extractor_names())

    def test_eoh_extraction(self):
        extractor = find_extractor(EOH_TE)
        self.assertIsNotNone(extractor)
        self.assertEqual(extractor.name, "MTEEyeOfHarmony")
        fields = extractor.extract(EOH_TE)
        self.assertEqual(fields["progress"], 29178)
        self.assertEqual(fields["max"], 39850)
        self.assertEqual(fields["idleSinceStop"], 9256780 - 9222292)
        self.assertEqual(fields["recipeRunning"], 1)
        self.assertEqual(fields["shutdown"], "structure_incomplete")
        self.assertEqual(fields["checkRecipe"], "success")
        self.assertEqual(fields["stored"], {"fluid.hydrogen": 0})

    def test_generic_extraction(self):
        extractor = find_extractor(GENERIC_TE)
        self.assertIsNotNone(extractor)
        self.assertEqual(extractor.name, "GTMultiblock")
        fields = extractor.extract(GENERIC_TE)
        self.assertEqual(fields["progress"], 100)
        self.assertEqual(fields["mEfficiency"], 10000)
        self.assertEqual(fields["machineName"], "AdvancedAssline")
        self.assertEqual(fields["powerPanelMaxParallel"], 4)
        self.assertEqual(fields["inputDisabled"], 1)
        self.assertEqual(fields["owner"], "tester")
        self.assertEqual(fields["extra"]["customScalar"], 42)
        self.assertTrue(fields["extra"]["makePowerfailEvents"])

    def test_non_machine_is_ignored(self):
        self.assertIsNone(find_extractor({"x": 1, "y": 2, "z": 3, "id": "Chest"}))


QUANTUM_TE = {
    "x": 1,
    "y": 2,
    "z": 3,
    "computation": 107448.0,
    "wirelessModeEnabled": 1,
    "mProgresstime": 7,
    "mMaxProgresstime": 20,
    "mTotalRunTime": 500,
}

DATA_BANK_TE = {
    "x": 1,
    "y": 2,
    "z": 3,
    "wirelessModeEnabled": 1,
    "mProgresstime": 0,
    "mMaxProgresstime": 0,
}

RESEARCH_TE = {
    "x": 1,
    "y": 2,
    "z": 3,
    "eComputationRemaining": 50,
    "eComputationRequired": 100,
    "eMachineType": "Assembly line",
    "mProgresstime": 0,
    "mMaxProgresstime": 0,
}


class QuantumExtractorTest(unittest.TestCase):
    def test_quantum_computer(self):
        extractor = find_extractor(QUANTUM_TE)
        self.assertEqual(extractor.name, "QuantumComputer")
        fields = extractor.extract(QUANTUM_TE)
        self.assertEqual(fields["computation"], 107448.0)
        self.assertEqual(fields["wirelessModeEnabled"], 1)

    def test_data_bank(self):
        extractor = find_extractor(DATA_BANK_TE)
        self.assertEqual(extractor.name, "DataBank")

    def test_research_station(self):
        extractor = find_extractor(RESEARCH_TE)
        self.assertEqual(extractor.name, "ResearchStation")
        fields = extractor.extract(RESEARCH_TE)
        self.assertEqual(fields["computationRemaining"], 50)
        self.assertEqual(fields["computationRequired"], 100)
        self.assertEqual(fields["machineType"], "Assembly line")


class EohExtraFieldsTest(unittest.TestCase):
    def test_enriched_fields(self):
        te = dict(EOH_TE)
        te["eyeOfHarmonyOutputyield"] = 0.7
        te["eyeOfHarmonyOutputsuccessfulParallelAmount"] = 1
        te["eyeOfHarmonyOutputpreviousChance"] = 0.21
        te["eyeOfHarmonyOutputitemOutput"] = {"numberOfItems": 3}
        te["eyeOfHarmonyOutputfluidOutput"] = {"numberOfFluids": 2}
        fields = find_extractor(te).extract(te)
        self.assertEqual(fields["yield"], 0.7)
        self.assertEqual(fields["successfulParallelAmount"], 1)
        self.assertEqual(fields["previousChance"], 0.21)
        self.assertEqual(fields["outputItems"], 3)
        self.assertEqual(fields["outputFluids"], 2)


class FallbackExtractorTest(unittest.TestCase):
    HATCH = {
        "x": 4,
        "y": 64,
        "z": 4,
        "mID": 40,
        "Inventory": [{"Count": 5}, {"Count": 3}],
    }

    def test_fallback_matches_any_gt_machine(self):
        extractor = find_extractor(self.HATCH)
        self.assertEqual(extractor.name, "GTMachine")
        fields = extractor.extract(self.HATCH)
        self.assertEqual(fields["machineName"], "ENERGY_HATCH_ULV")
        self.assertEqual(fields["inventory"], {"slots": 2, "slotsUsed": 2, "itemCount": 8})

    def test_specific_extractor_adds_common_fields(self):
        te = dict(GENERIC_TE)
        te["mID"] = 1
        fields = find_extractor(te).extract(te)
        self.assertEqual(fields["machineName"], "HULL_BRONZE")
        self.assertIn("batchMode", fields)


class BigIntegerTest(unittest.TestCase):
    def test_eoh_bigint_is_big_endian_signed(self):
        te = dict(EOH_TE)
        # byte array captured from a real save: GT stores BigInteger.toByteArray() (big-endian)
        te["eyeOfHarmonyOutputusedEU"] = bytes.fromhex("fc38bf875975b500")
        extractor = find_extractor(te)
        self.assertEqual(extractor.extract(te)["usedEU"], -272257189413538560)


class DiffTest(unittest.TestCase):
    def snapshot(self, progress):
        return {
            "snapshot": {"source": "test", "captured": "2026-10-25T00:00:00+08:00"},
            "entries": [
                {
                    "dim": "PERSONAL_DIM_180",
                    "chunk": [6, 6],
                    "pos": [104, 49, 104],
                    "machine": "MTEEyeOfHarmony",
                    "fields": {"progress": progress, "totalRun": progress * 10},
                }
            ],
        }

    def test_reports_numeric_delta(self):
        result = diff(self.snapshot(29178), self.snapshot(32696))
        self.assertEqual(len(result["changes"]), 1)
        change = result["changes"][0]
        self.assertEqual(change["status"], "changed")
        self.assertEqual(change["fields"]["progress"]["delta"], 3518)

    def test_identical_snapshots_have_no_changes(self):
        self.assertEqual(diff(self.snapshot(100), self.snapshot(100))["changes"], [])


if __name__ == "__main__":
    unittest.main()
