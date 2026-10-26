"""Shared human-readable formatting for offline and live machine entries."""

from __future__ import annotations


def seconds(ticks):
    if not isinstance(ticks, (int, float)):
        return "?"
    return "%.1f s" % (ticks / 20.0)


def format_table_line(entry: dict) -> str:
    """One line per machine, for scanning many machines at once."""
    fields = entry.get("fields") or {}
    bits = []
    if fields.get("progress") is not None or fields.get("max") is not None:
        if fields.get("max") is not None:
            bits.append("progress=%s/%s" % (fields.get("progress"), fields.get("max")))
        else:
            bits.append("progress=%s" % fields.get("progress"))
    if fields.get("totalRun") is not None:
        bits.append("totalRun=%s" % fields["totalRun"])
    for key in ("recipeRunning", "mEfficiency", "shutdown", "checkRecipe"):
        if fields.get(key) is not None:
            bits.append("%s=%s" % (key, fields[key]))
    if entry.get("chunk_modified") is not None:
        bits.append("chunkModified=%s" % entry["chunk_modified"])
    machine = entry.get("machine")
    machine_name = fields.get("machineName")
    if machine == "GTMachine":
        if machine_name:
            machine = "GTMachine(%s)" % machine_name
        elif fields.get("class"):
            machine = "GTMachine(%s)" % fields["class"]
        if fields.get("mID") is not None:
            bits.append("mID=%s" % fields["mID"])
        inventory = fields.get("inventory")
        if isinstance(inventory, dict):
            bits.append("inv=%s/%s" % (inventory.get("slotsUsed"), inventory.get("slots")))
    return "%-18s %-18s %-26s %s" % (
        entry.get("dim"),
        "(%s,%s,%s)" % tuple(entry.get("pos") or ()),
        machine,
        "  ".join(bits),
    )


_KNOWN_KEYS = (
    "totalRun",
    "lastWorkingTick",
    "idleSinceStop",
    "recipeRunning",
    "recipeSuccessChance",
    "pityChance",
    "rocketTier",
    "astralArrayAmount",
    "parallelAmount",
    "successfulParallelAmount",
    "yield",
    "usedEU",
    "outputEU",
    "mEfficiency",
    "mEfficiencyIncrease",
    "mEUT",
    "mID",
    "mUpdate",
    "mWorks",
    "working",
    "shutdown",
    "checkRecipe",
)


def format_entry(entry: dict, world_name: str = "") -> str:
    fields = entry.get("fields") or {}
    lines = [
        "%s%s  chunk=%s  pos=%s  %s"
        % (
            (world_name + "  ") if world_name else "",
            entry.get("dim"),
            tuple(entry.get("chunk") or ()),
            tuple(entry.get("pos") or ()),
            entry.get("machine"),
        )
    ]
    progress = fields.get("progress")
    maximum = fields.get("max")
    if progress is not None or maximum is not None:
        lines.append(
            "  progress       : %s / %s   (%s / %s)"
            % (progress, maximum, seconds(progress), seconds(maximum))
        )
    for key in _KNOWN_KEYS:
        value = fields.get(key)
        if value is not None:
            lines.append("  %-14s : %s" % (key, value))
    stored = fields.get("stored") or {}
    if stored:
        lines.append("  %-14s : %s" % ("stored", stored))
    if entry.get("chunk_modified") is not None:
        lines.append("  %-14s : %s" % ("chunkModified", entry["chunk_modified"]))
    extra = {
        key: value
        for key, value in fields.items()
        if key not in _KNOWN_KEYS
        and key not in ("progress", "max", "stored")
        and value is not None
    }
    for key in sorted(extra):
        lines.append("  %-14s : %s" % (key, extra[key]))
    return "\n".join(lines)
