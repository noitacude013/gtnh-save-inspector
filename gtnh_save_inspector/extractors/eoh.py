"""Eye of Harmony (MTEEyeOfHarmony) extractor.

The machine persists its custom fields with an ``eyeOfHarmonyOutput`` prefix, which
makes it reliably identifiable without knowing the numeric meta tile entity id.
"""

from __future__ import annotations

from .base import Extractor, common_fields, inventory_summary, reason_key, stored_fields

PREFIX = "eyeOfHarmonyOutput"


def _bigint(value):
    """GT stores BigInteger fields as big-endian two's-complement byte arrays in NBT."""
    if isinstance(value, (bytes, bytearray)):
        return int.from_bytes(bytes(value), "big", signed=True)
    return value


class EyeOfHarmonyExtractor(Extractor):
    name = "MTEEyeOfHarmony"
    priority = 10
    description = "Eye of Harmony (TecTech): recipe progress, stored fluids, recipe running state"

    def matches(self, te: dict) -> bool:
        return any(str(key).startswith(PREFIX) for key in te)

    def extract(self, te: dict) -> dict:
        result = self._extract(te)
        result.update(common_fields(te))
        return result

    def _extract(self, te: dict) -> dict:
        def field(key, default=None):
            return te.get(key, default)

        return {
            "progress": field("mProgresstime"),
            "max": field("mMaxProgresstime"),
            "totalRun": field("mTotalRunTime"),
            "lastWorkingTick": field("mLastWorkingTick"),
            "idleSinceStop": (field("mTotalRunTime") or 0) - (field("mLastWorkingTick") or 0),
            "recipeRunning": field(PREFIX + "recipeRunning"),
            "recipeSuccessChance": field(PREFIX + "recipeSuccessChance"),
            "pityChance": field(PREFIX + "pityChance"),
            "rocketTier": field(PREFIX + "rocketTier"),
            "astralArrayAmount": field(PREFIX + "astralArrayAmount"),
            "parallelAmount": field(PREFIX + "parallelAmount"),
            "successfulParallelAmount": field(PREFIX + "successfulParallelAmount"),
            "yield": field(PREFIX + "yield"),
            "outputEU": _bigint(field(PREFIX + "outputEU_BigInt")),
            "usedEU": _bigint(field(PREFIX + "usedEU")),
            "previousChance": field(PREFIX + "previousChance"),
            "currentCircuitMultiplier": field(PREFIX + "currentCircuitMultiplier"),
            "animationsEnabled": field(PREFIX + "animationsEnabled"),
            "outputItems": (field(PREFIX + "itemOutput") or {}).get("numberOfItems"),
            "outputFluids": (field(PREFIX + "fluidOutput") or {}).get("numberOfFluids"),
            "mEfficiency": field("mEfficiency"),
            "mEUT": field("mEUT"),
            "shutdown": reason_key(field("shutDownReason")),
            "checkRecipe": reason_key(field("checkRecipeResult")),
            "stored": stored_fields(te),
        }
