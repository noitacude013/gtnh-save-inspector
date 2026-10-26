"""Example gtnh-save-inspector plugin.

Load with:
    gtnh-inspect --plugin examples/plugin_example.py scan --world <save> --dim 180
"""

from gtnh_save_inspector.extractors.base import Extractor, reason_key, stored_fields


class ExampleMachineExtractor(Extractor):
    """Matches a (hypothetical) machine that persists a "mExampleState" field."""

    name = "MTEExampleMachine"
    priority = 50
    description = "Example plugin extractor"

    def matches(self, te):
        return "mExampleState" in te

    def extract(self, te):
        return {
            "progress": te.get("mProgresstime"),
            "max": te.get("mMaxProgresstime"),
            "totalRun": te.get("mTotalRunTime"),
            "exampleState": te.get("mExampleState"),
            "shutdown": reason_key(te.get("shutDownReason")),
            "stored": stored_fields(te),
        }
