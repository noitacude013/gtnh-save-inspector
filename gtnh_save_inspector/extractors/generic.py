"""Generic GregTech/TecTech multiblock extractor (any machine with recipe progress)."""

from __future__ import annotations

from .base import Extractor, common_fields, inventory_summary, reason_key, stored_fields


class GenericGTMultiblockExtractor(Extractor):
    name = "GTMultiblock"
    priority = 90
    description = "Generic GregTech multiblock: progress, total run time and status"

    def matches(self, te: dict) -> bool:
        return "mMaxProgresstime" in te and "mProgresstime" in te

    def extract(self, te: dict) -> dict:
        def field(key, default=None):
            return te.get(key, default)

        total = field("mTotalRunTime")
        last = field("mLastWorkingTick")
        result = {
            "progress": field("mProgresstime"),
            "max": field("mMaxProgresstime"),
            "totalRun": total,
            "lastWorkingTick": last,
            "idleSinceStop": None if total is None or last is None else total - last,
            "mEfficiency": field("mEfficiency"),
            "mEfficiencyIncrease": field("mEfficiencyIncrease"),
            "mEUT": field("mEUT"),
            "mID": field("mID"),
            "mUpdate": field("mUpdate"),
            "mWorks": field("mWorks"),
            "working": field("mWorking"),
            "shutdown": reason_key(field("shutDownReason")),
            "checkRecipe": reason_key(field("checkRecipeResult")),
            "stored": stored_fields(te),
            "inventory": inventory_summary(te),
            "powerPanelMaxParallel": field("powerPanelMaxParallel"),
            "alwaysMaxParallel": field("alwaysMaxParallel"),
            "inputDisabled": field("mInputDisabled"),
            "outputDisabled": field("mOutputDisabled"),
            "softMallet": field("mSoftMallet"),
            "facing": field("mFacing"),
            "redstone": field("mRedstone"),
            "redstoneSided": field("mRedstoneSided"),
            "muffler": field("mMuffler"),
            "lastStop": field("lastStop"),
            "owner": field("mOwnerName"),
            "ownerUuid": field("mOwnerUuid"),
            "upgrades": field("mOtherUpgrades"),
            "extra": multiblock_extra(te),
        }
        result.update(common_fields(te))
        return result


_ALREADY_EXTRACTED = {
    "mProgresstime", "mMaxProgresstime", "mTotalRunTime", "mLastWorkingTick",
    "mEfficiency", "mEfficiencyIncrease", "mEUT", "mID", "mUpdate", "mWorks",
    "mWorking", "shutDownReason", "checkRecipeResult", "Inventory", "mActive",
    "mWasShutdown", "batchMode", "inputSeparation", "voidingMode", "mLockUpgrade",
    "mStoredEnergy", "mStoredSteam", "mPollution", "mRuntime", "shutDownReasonID",
    "checkRecipeResultID", "mFluid", "fluidTank", "mFluidStack", "mTank",
    "powerPanelMaxParallel", "alwaysMaxParallel", "mInputDisabled", "mOutputDisabled",
    "mSoftMallet", "mFacing", "mRedstone", "mRedstoneSided", "mMuffler", "lastStop",
    "mOwnerName", "mOwnerUuid", "mWrench", "mHardHammer", "mScrewdriver", "mCrowbar",
    "mSolderingTool", "mOtherUpgrades", "mColor", "eFlip", "eRotation", "mLightValue",
    "x", "y", "z", "id", "nbtVersion",
}


def multiblock_extra(te: dict) -> dict:
    """Expose other scalar NBT fields of any GT multiblock without per-machine code."""
    extra = {}
    for key, value in te.items():
        name = str(key)
        if name.startswith("stored.") or name in _ALREADY_EXTRACTED:
            continue
        if isinstance(value, bool):
            extra[name] = value
        elif isinstance(value, (int, float)):
            extra[name] = value
        elif isinstance(value, str):
            extra[name] = value
    return extra


class GTMachineExtractor(Extractor):
    """Fallback for every GT meta tile entity (hatches, buses, simple machines, ...)."""

    name = "GTMachine"
    priority = 1000
    description = "Any GT meta tile entity: registration name, state flags and inventory summary"

    def matches(self, te: dict) -> bool:
        return "mID" in te

    def extract(self, te: dict) -> dict:
        total = te.get("mTotalRunTime")
        last = te.get("mLastWorkingTick")
        result = {
            "progress": te.get("mProgresstime"),
            "max": te.get("mMaxProgresstime"),
            "totalRun": total,
            "lastWorkingTick": last,
            "idleSinceStop": None if total is None or last is None else total - last,
            "mEUT": te.get("mEUT"),
            "mEfficiency": te.get("mEfficiency"),
            "mEfficiencyIncrease": te.get("mEfficiencyIncrease"),
            "inventory": inventory_summary(te),
            "stored": stored_fields(te),
        }
        result.update(common_fields(te))
        return result
