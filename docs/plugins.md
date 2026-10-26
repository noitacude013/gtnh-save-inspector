# Extractor plugins

You can extend the inspector with your own machine extractors **without forking the tool**. A
plugin is a plain Python file that defines one or more subclasses of
`gtnh_save_inspector.extractors.base.Extractor`.

## Quick example

Create `my_plugin.py`:

```python
from gtnh_save_inspector.extractors.base import Extractor, reason_key, stored_fields


class MyMachineExtractor(Extractor):
    name = "MTEMyMachine"          # shown by scan / used by --mte
    priority = 50                  # lower runs first (EoH=10, generic=90)
    description = "My machine"

    def matches(self, te):
        return "mMyMachineField" in te

    def extract(self, te):
        return {
            "progress": te.get("mProgresstime"),
            "max": te.get("mMaxProgresstime"),
            "shutdown": reason_key(te.get("shutDownReason")),
            "stored": stored_fields(te),
        }
```

Load it:

```bash
# once per command
gtnh-inspect --plugin ./my_plugin.py scan --world saves/Horizon --dim 180

# or via environment variable (separator: ";" on Windows, ":" elsewhere)
GTNH_INSPECTOR_PLUGINS=./my_plugin.py gtnh-inspect scan --world saves/Horizon
```

Plugins are loaded before the subcommand runs and the registry is re-sorted by `priority`, so a
plugin can take precedence over built-ins (lower priority value wins).

## Rules

- `matches(te)` is called for every TileEntity, so keep it cheap and reliable.
- Return JSON-serialisable values; missing fields should be `None`, not exceptions.
- Byte arrays from NBT can be converted with `nbt.sanitize()` or decoded manually
  (`int.from_bytes(value, "little")` for BigIntegers).
- The plugin file must define at least one `Extractor` subclass, otherwise loading fails with an
  error.
- For the **live probe**, the agent dumps Java field names. Fields whose names equal the persisted
  NBT keys work out of the box; machines that rename fields on save need an entry in
  `gtnh_save_inspector/live/convert.py::EOH_FIELD_MAP` (this is a code change, not a plugin).

## How loading works

```text
gtnh-inspect [--plugin FILE ...] <command> ...
```

`PluginError` is reported on stderr and the command exits with code 2 if a plugin cannot be
imported or defines no extractors. Tests can register/unregister extractors programmatically via
`gtnh_save_inspector.extractors.plugins.register()` / `unregister()`.
