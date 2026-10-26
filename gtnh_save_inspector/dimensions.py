"""Dimension label mapping between save folders and numeric dimension ids.

Offline snapshots label dimensions with save folder names (``PERSONAL_DIM_180``,
``DIM-1``, ``overworld``). The live probe only knows numeric ids from the JVM, so it
labels them ``DIM_<id>``. This module converts between the two so ``diff`` works across
offline and live snapshots.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple

PERSONAL_RE = re.compile(r"PERSONAL_DIM_(-?\d+)$")
DIM_RE = re.compile(r"DIM_?(-?\d+)$")
INT_RE = re.compile(r"-?\d+$")

OVERWORLD_ID = 0


def dimension_id_of(label) -> Optional[int]:
    """Extract the numeric dimension id from a save-folder or live label."""
    if not isinstance(label, str):
        return None
    text = label.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in ("overworld", "world", "dim0", "dim_0"):
        return OVERWORLD_ID
    if INT_RE.fullmatch(text):
        return int(text)
    match = PERSONAL_RE.fullmatch(text)
    if match:
        return int(match.group(1))
    match = DIM_RE.fullmatch(text)
    if match:
        return int(match.group(1))
    return None


def label_for_id(dimension_id: int, folders: Iterable[str] = ()) -> str:
    """Pick the best save-folder name for a numeric dimension id."""
    if dimension_id == OVERWORLD_ID:
        return "overworld"
    folders = list(folders)
    preferred = "DIM%d" % dimension_id
    if preferred in folders:
        return preferred
    personal = "PERSONAL_DIM_%d" % dimension_id
    if personal in folders:
        return personal
    dim_underscore = "DIM_%d" % dimension_id
    if dim_underscore in folders:
        return dim_underscore
    for folder in folders:
        if dimension_id_of(folder) == dimension_id:
            return folder
    return "DIM_%d" % dimension_id


def resolve_dim(name: str, folders: Iterable[str]) -> str:
    """Resolve a user supplied --dim value (folder name or numeric id) to a folder."""
    folders = list(folders)
    if name in folders:
        return name
    dimension_id = dimension_id_of(name)
    if dimension_id is not None:
        candidate = label_for_id(dimension_id, folders)
        if candidate in folders:
            return candidate
        for folder in folders:
            if dimension_id_of(folder) == dimension_id:
                return folder
    return name


def dimension_key(label) -> Tuple[str, object]:
    """Canonical key for diffing: numeric ids compare across label styles."""
    dimension_id = dimension_id_of(label)
    if dimension_id is not None:
        return ("id", dimension_id)
    return ("label", str(label).lower())