"""Reading probe output files (JSON lines produced by the agent)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator


def read_samples(path) -> list:
    """Read all samples from a probe output file (invalid lines are skipped)."""
    samples = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return samples


def machine_samples(samples) -> list:
    return [sample for sample in samples if "machines" in sample]


def follow_samples(
    path,
    max_machine_samples: int = 0,
    timeout_s: float = 0.0,
) -> Iterator[dict]:
    """Tail a probe output file and yield parsed JSON samples as they appear."""
    deadline = time.time() + timeout_s if timeout_s else None
    offset = 0
    seen_machines = 0
    while True:
        if deadline is not None and time.time() > deadline:
            return
        target = Path(path)
        if target.is_file():
            with target.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield sample
                if "machines" in sample:
                    seen_machines += 1
                    if max_machine_samples and seen_machines >= max_machine_samples:
                        return
                if sample.get("status") == "stopped":
                    return
        time.sleep(0.2)
