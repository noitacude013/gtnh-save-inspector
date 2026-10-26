"""Map live-probe Java fields onto the pseudo-NBT keys used by the extractors."""

from __future__ import annotations

from ..dimensions import dimension_id_of, label_for_id
from ..extractors import find_extractor

# MTEEyeOfHarmony persists its extra state under an "eyeOfHarmonyOutput" prefix, while the live
# agent dumps plain Java fields. This table bridges the two.
EOH_FIELD_MAP = {
    "recipeRunning": "eyeOfHarmonyOutputrecipeRunning",
    "successChance": "eyeOfHarmonyOutputrecipeSuccessChance",
    "currentRecipeRocketTier": "eyeOfHarmonyOutputrocketTier",
    "currentCircuitMultiplier": "eyeOfHarmonyOutputcurrentCircuitMultiplier",
    "animationsEnabled": "eyeOfHarmonyOutputanimationsEnabled",
    "parallelAmount": "eyeOfHarmonyOutputparallelAmount",
    "successfulParallelAmount": "eyeOfHarmonyOutputsuccessfulParallelAmount",
    "yield": "eyeOfHarmonyOutputyield",
    "astralArrayAmount": "eyeOfHarmonyOutputastralArrayAmount",
    "usedEU": "eyeOfHarmonyOutputusedEU",
    "outputEU_BigInt": "eyeOfHarmonyOutputoutputEU_BigInt",
    "pityChance": "eyeOfHarmonyOutputpityChance",
    "previousRecipeChance": "eyeOfHarmonyOutputpreviousChance",
}

RESEARCH_FIELD_MAP = {
    "computationRemaining": "eComputationRemaining",
    "computationRequired": "eComputationRequired",
    "machineType": "eMachineType",
}

BIGINT_KEYS = (
    "eyeOfHarmonyOutputusedEU",
    "eyeOfHarmonyOutputoutputEU_BigInt",
)


def to_pseudo_nbt(fields: dict, machine_class=None) -> dict:
    """Return a dict shaped like persisted TileEntity NBT for the offline extractors."""
    pseudo = dict(fields)
    for java_name, nbt_key in RESEARCH_FIELD_MAP.items():
        if java_name in fields and nbt_key not in pseudo:
            pseudo[nbt_key] = fields[java_name]
    if machine_class == "MTEQuantumComputer" and "eAvailableData" in fields:
        pseudo.setdefault("computation", fields["eAvailableData"])
    for java_name, nbt_key in EOH_FIELD_MAP.items():
        if java_name in fields:
            pseudo[nbt_key] = fields[java_name]
    for key in BIGINT_KEYS:
        value = pseudo.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text.lstrip("-").isdigit():
                pseudo[key] = int(text)
    # Purification units persist the plant link as {"controller": {"x","y","z"}} in NBT but
    # expose plain controllerX/controllerY/controllerZ fields at runtime.
    if "controller" not in pseudo and all(
        key in fields for key in ("controllerX", "controllerY", "controllerZ")
    ):
        if fields.get("controllerSet", True):
            pseudo["controller"] = {
                "x": fields["controllerX"],
                "y": fields["controllerY"],
                "z": fields["controllerZ"],
            }
    return pseudo


def dimension_label(dimension, labels=None) -> str:
    if not isinstance(dimension, int) or dimension == -2147483648:
        return "DIM_unknown"
    if labels and dimension in labels:
        return labels[dimension]
    return label_for_id(dimension)


def machine_to_entry(machine: dict, dim_labels=None) -> dict:
    """Convert one machine dict from the live agent into a snapshot-style entry."""
    fields = to_pseudo_nbt(machine.get("fields") or {}, machine.get("class"))
    extractor = find_extractor(fields)
    live_inventory = machine.get("inventory") if isinstance(machine.get("inventory"), dict) else None
    inventory_summary = None
    if live_inventory:
        inventory_summary = {
            key: live_inventory.get(key) for key in ("slots", "slotsUsed", "itemCount")
        }
    if extractor is None:
        # No dedicated extractor: use the fallback name so live and offline defaults agree
        # (offline scan excludes GTMachine unless --all). Keep the Java class for context.
        fallback_fields = dict(fields)
        fallback_fields["class"] = machine.get("class")
        if inventory_summary:
            fallback_fields["inventory"] = inventory_summary
        entry = {
            "dim": dimension_label(machine.get("dim"), dim_labels),
            "chunk": machine.get("chunk") or [None, None],
            "pos": [machine.get("x"), machine.get("y"), machine.get("z")],
            "machine": "GTMachine",
            "fields": fallback_fields,
        }
    else:
        extracted = extractor.extract(fields)
        if inventory_summary:
            extracted["inventory"] = inventory_summary
        entry = {
            "dim": dimension_label(machine.get("dim"), dim_labels),
            "chunk": machine.get("chunk") or [None, None],
            "pos": [machine.get("x"), machine.get("y"), machine.get("z")],
            "machine": extractor.name,
            "fields": extracted,
        }
    if machine.get("chunkModified") is not None:
        entry["chunk_modified"] = machine["chunkModified"]
    return entry
