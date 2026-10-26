"""Extractor registry: add new machines here (see docs/extractors.md)."""

from __future__ import annotations

from typing import List, Optional

from .base import Extractor
from .eoh import EyeOfHarmonyExtractor
from .generic import GenericGTMultiblockExtractor, GTMachineExtractor
from .purification import PurificationUnitExtractor
from .quantum import DataBankExtractor, QuantumComputerExtractor, ResearchStationExtractor

EXTRACTORS: List[Extractor] = [
    EyeOfHarmonyExtractor(),
    PurificationUnitExtractor(),
    QuantumComputerExtractor(),
    DataBankExtractor(),
    ResearchStationExtractor(),
    GenericGTMultiblockExtractor(),
    GTMachineExtractor(),
]

# Sorted by priority (lower first) once at import time.
EXTRACTORS.sort(key=lambda extractor: extractor.priority)


def find_extractor(te: dict) -> Optional[Extractor]:
    """Return the first extractor matching a tile entity, or None."""
    for extractor in EXTRACTORS:
        if extractor.matches(te):
            return extractor
    return None


def extractor_names() -> List[str]:
    return [extractor.name for extractor in EXTRACTORS]
