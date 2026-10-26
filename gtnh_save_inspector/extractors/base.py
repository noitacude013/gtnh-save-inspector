"""Extractor base class: turns raw tile entity NBT into named, reportable fields."""

from __future__ import annotations

from ..data.mte_ids import mte_name


class Extractor:
    """A machine-specific NBT field extractor."""

    name = "unknown"
    priority = 100
    description = ""

    def matches(self, te: dict) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def extract(self, te: dict) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


def reason_key(value):
    """GT shutdown/check-recipe results serialise as {'key': '...', 'params': [...]}."""
    if isinstance(value, dict):
        return value.get("key")
    if isinstance(value, str):
        return value
    return None


def stored_fields(te: dict) -> dict:
    """Collect GT multiblock ``stored.*`` entries (e.g. stored.fluid.hydrogen)."""
    return {
        str(key)[len("stored.") :]: value
        for key, value in te.items()
        if str(key).startswith("stored.")
    }


def common_fields(te: dict) -> dict:
    """Fields shared by every GT meta tile entity (state flags, registration name)."""
    mte_id = te.get("mID")
    return {
        "mID": mte_id,
        "machineName": mte_name(mte_id),
        "active": te.get("mActive"),
        "works": te.get("mWorks"),
        "wasShutdown": te.get("mWasShutdown"),
        "batchMode": te.get("batchMode"),
        "inputSeparation": te.get("inputSeparation"),
        "voidingMode": te.get("voidingMode"),
        "mLockUpgrade": te.get("mLockUpgrade"),
        "mStoredEnergy": te.get("mStoredEnergy"),
        "mStoredSteam": te.get("mStoredSteam"),
        "mPollution": te.get("mPollution"),
        "mRuntime": te.get("mRuntime"),
        "shutdownID": te.get("shutDownReasonID"),
        "checkRecipeID": te.get("checkRecipeResultID"),
        "inventory": inventory_summary(te),
        "fluid": _first_fluid(te),
    }


def inventory_summary(te: dict):
    """Summarise a GT ``Inventory`` NBT list (offline) or live inventory dict."""
    live = te.get("inventory")
    if isinstance(live, dict):
        return {
            "slots": live.get("slots"),
            "slotsUsed": live.get("slotsUsed"),
            "itemCount": live.get("itemCount"),
        }
    inventory = te.get("Inventory")
    if not isinstance(inventory, list):
        return None
    used = 0
    items = 0
    for entry in inventory:
        if not isinstance(entry, dict):
            continue
        count = entry.get("Count")
        if isinstance(count, int) and count > 0:
            used += 1
            items += count
    return {"slots": len(inventory), "slotsUsed": used, "itemCount": items}


def _first_fluid(te: dict):
    for key in ("mFluid", "fluidTank", "mFluidStack", "mTank"):
        value = te.get(key)
        if isinstance(value, dict) and value.get("fluid") is not None:
            return {"name": value.get("fluid"), "amount": value.get("amount")}
    return None
