# Writing an extractor

An extractor turns one TileEntity's raw NBT dictionary into the named fields that `show`, `scan`
and `diff` report. Adding one is a small, self-contained change.

## 1. Create the extractor

Create `gtnh_save_inspector/extractors/my_machine.py`:

```python
from .base import Extractor, reason_key, stored_fields


class MyMachineExtractor(Extractor):
    name = "MTEMyMachine"          # shown by `scan`, used by `--mte`
    priority = 50                  # lower runs first; EoH is 10, generic is 90
    description = "My machine: progress and stored fluids"

    def matches(self, te: dict) -> bool:
        # Prefer a field prefix unique to this machine class (see MTEEyeOfHarmony,
        # which persists fields as "eyeOfHarmonyOutput*"). Avoid numeric meta ids
        # when possible: they change between GT versions.
        return "mMyMachineField" in te

    def extract(self, te: dict) -> dict:
        return {
            "progress": te.get("mProgresstime"),
            "max": te.get("mMaxProgresstime"),
            "totalRun": te.get("mTotalRunTime"),
            "shutdown": reason_key(te.get("shutDownReason")),
            "stored": stored_fields(te),
        }
```

Notes:

- `matches()` must be cheap and reliable: it runs against **every** TileEntity.
- Extractors are tried in ascending `priority`; the first match wins. Give specific machines a
  low priority and keep `GenericGTMultiblockExtractor` at the end.
- Values must be JSON-serialisable. Use `nbt.sanitize()` for byte arrays, or `nbt.squash()` for
  large arrays. `TAG_Byte_Array` values (e.g. BigIntegers) can be decoded with
  `int.from_bytes(value, "little")`.
- Missing fields are fine; return `None` for them instead of raising.

## 2. Register it

Edit `gtnh_save_inspector/extractors/__init__.py`:

```python
from .my_machine import MyMachineExtractor

EXTRACTORS = [
    EyeOfHarmonyExtractor(),
    MyMachineExtractor(),
    GenericGTMultiblockExtractor(),
]
```

The list is sorted by priority at import time.

## 3. Test it

Add a case to `tests/test_extractors.py`:

```python
TE = {"x": 1, "y": 64, "z": 1, "mProgresstime": 10, "mMyMachineField": 1}

def test_my_machine(self):
    extractor = find_extractor(TE)
    self.assertEqual(extractor.name, "MTEMyMachine")
    self.assertEqual(extractor.extract(TE)["progress"], 10)
```

Run the suite:

```bash
python -m unittest discover -v
```

## Generic multiblock coverage

`GenericGTMultiblockExtractor` matches every GT multiblock controller that persists
`mProgresstime` / `mMaxProgresstime`. It extracts the common progress, runtime,
efficiency, EU/t, shutdown/check-recipe and inventory/fluid fields plus common
controller fields (parallel limits, input/output disabled, owner, facing, redstone,
muffler, upgrades). Other scalar NBT fields are exposed in an `extra` dictionary, so
new or uncommon multiblocks still get their fields without a dedicated extractor.

Hatches, buses and single-block machines are intentionally not matched by this
extractor; they fall back to `GTMachine` and are included only with `scan --all`.

## Finding fields in a real save

`dump` shows the raw NBT of any TileEntity, which is the fastest way to discover persisted field
names:

```bash
gtnh-inspect dump --world "/path/to/saves/Horizon" --dim PERSONAL_DIM_180 --pos 104,49,104
```

Waterline purification units persist their plant link as a `controller` compound with `x`/`y`/`z`;
`PurificationUnitExtractor` exposes it as `controller: [x, y, z]` (the plant's live linked-unit
list is not saved, so ghost links cannot be read offline).

GT multiblocks store progress in `mProgresstime` / `mMaxProgresstime`, total run time in
`mTotalRunTime`, and machine-specific data either in a field prefix (as the Eye of Harmony does)
or under `stored.*`.

## Plugins

If you only need a private extractor, you do not have to modify the tool: see
[docs/plugins.md](plugins.md) for the plugin format (same ``Extractor`` API).

## Live probe compatibility

The live agent dumps plain Java field names, while extractors match persisted NBT keys. The
`generic` fields already share names; machines that rename fields on save (like the Eye of Harmony,
which prefixes them with `eyeOfHarmonyOutput`) need an entry in
`gtnh_save_inspector/live/convert.py::EOH_FIELD_MAP` (add your machine's map there). BigIntegers
arrive as decimal strings and are converted back to ints by `to_pseudo_nbt()`.
