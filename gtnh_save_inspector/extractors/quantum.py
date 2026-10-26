"""Data-oriented TecTech machines: quantum computer, data bank and research station.

These persist machine-specific state that the generic extractor cannot show:
- QuantumComputer: ``computation`` (available computation, NBT double), ``wirelessModeEnabled``
- DataBank: ``wirelessModeEnabled`` (it is a quantum computer without the computation field)
- ResearchStation: ``eComputationRemaining`` / ``eComputationRequired`` / ``eMachineType``
"""

from __future__ import annotations

from .base import Extractor, common_fields, inventory_summary, reason_key, stored_fields


class QuantumComputerExtractor(Extractor):
    name = "QuantumComputer"
    priority = 30
    description = "TecTech quantum computer: available computation and wireless mode"

    def matches(self, te: dict) -> bool:
        return "computation" in te and "wirelessModeEnabled" in te

    def extract(self, te: dict) -> dict:
        result = self._extract(te)
        result.update(common_fields(te))
        return result

    def _extract(self, te: dict) -> dict:
        total = te.get("mTotalRunTime")
        last = te.get("mLastWorkingTick")
        return {
            "computation": te.get("computation"),
            "wirelessModeEnabled": te.get("wirelessModeEnabled"),
            "progress": te.get("mProgresstime"),
            "max": te.get("mMaxProgresstime"),
            "totalRun": total,
            "idleSinceStop": None if total is None or last is None else total - last,
            "mEUT": te.get("mEUT"),
            "mID": te.get("mID"),
            "shutdown": reason_key(te.get("shutDownReason")),
            "checkRecipe": reason_key(te.get("checkRecipeResult")),
            "stored": stored_fields(te),
        }


class DataBankExtractor(Extractor):
    name = "DataBank"
    priority = 31
    description = "TecTech data bank: wireless data mode"

    def matches(self, te: dict) -> bool:
        return "wirelessModeEnabled" in te and "computation" not in te

    def extract(self, te: dict) -> dict:
        total = te.get("mTotalRunTime")
        return {
            "wirelessModeEnabled": te.get("wirelessModeEnabled"),
            "progress": te.get("mProgresstime"),
            "max": te.get("mMaxProgresstime"),
            "totalRun": total,
            "mEUT": te.get("mEUT"),
            "mID": te.get("mID"),
            "shutdown": reason_key(te.get("shutDownReason")),
            "checkRecipe": reason_key(te.get("checkRecipeResult")),
        }


class ResearchStationExtractor(Extractor):
    name = "ResearchStation"
    priority = 32
    description = "TecTech research station: remaining/required computation"

    def matches(self, te: dict) -> bool:
        return "eComputationRequired" in te

    def extract(self, te: dict) -> dict:
        total = te.get("mTotalRunTime")
        return {
            "computationRemaining": te.get("eComputationRemaining"),
            "computationRequired": te.get("eComputationRequired"),
            "machineType": te.get("eMachineType"),
            "progress": te.get("mProgresstime"),
            "max": te.get("mMaxProgresstime"),
            "totalRun": total,
            "mEUT": te.get("mEUT"),
            "mID": te.get("mID"),
            "shutdown": reason_key(te.get("shutDownReason")),
            "checkRecipe": reason_key(te.get("checkRecipeResult")),
        }
