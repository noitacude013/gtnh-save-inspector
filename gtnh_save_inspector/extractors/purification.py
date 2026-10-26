"""Waterline purification unit extractor.

Each purification unit persists its controller link as a ``controller`` compound with
``x``/``y``/``z``, which lets us map units to the plant offline. The plant's linked-unit
list itself is transient (synced, not saved), so ghost/duplicate links are not visible
from a save file.
"""

from __future__ import annotations

from .base import Extractor, common_fields, inventory_summary, reason_key, stored_fields


class PurificationUnitExtractor(Extractor):
    name = "PurificationUnit"
    priority = 20
    description = "Waterline purification unit: progress and controller link"

    def matches(self, te: dict) -> bool:
        controller = te.get("controller")
        return (
            isinstance(controller, dict)
            and "mMaxProgresstime" in te
            and "x" in controller
            and "y" in controller
            and "z" in controller
        )

    def extract(self, te: dict) -> dict:
        result = self._extract(te)
        result.update(common_fields(te))
        return result

    def _extract(self, te: dict) -> dict:
        def field(key, default=None):
            return te.get(key, default)

        controller = te.get("controller") or {}
        total = field("mTotalRunTime")
        last = field("mLastWorkingTick")
        return {
            "progress": field("mProgresstime"),
            "max": field("mMaxProgresstime"),
            "totalRun": total,
            "lastWorkingTick": last,
            "idleSinceStop": None if total is None or last is None else total - last,
            "controller": [controller.get("x"), controller.get("y"), controller.get("z")],
            "mEfficiency": field("mEfficiency"),
            "mEUT": field("mEUT"),
            "mID": field("mID"),
            "shutdown": reason_key(field("shutDownReason")),
            "checkRecipe": reason_key(field("checkRecipeResult")),
            "stored": stored_fields(te),
        }
