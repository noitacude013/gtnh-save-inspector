# Live probe

The live probe attaches to a **running GTNH client/server JVM** and samples machine state from
memory. It complements the offline inspector: offline answers "what is on disk", live answers "what
is in memory right now".

Available in **v1.0**.

## Requirements

- A **JDK 11+** `java` executable (the attach API lives in `jdk.attach`). The game itself may run on
  any supported Java version.
- The game must be running (ideally in a world; on the title screen there is no server and the probe
  reports `no-server`).

## Usage

```bash
# one sample, then detach
gtnh-inspect probe dump --pid 12345 --machine MTEEyeOfHarmony

# stream samples every second until Ctrl+C
gtnh-inspect probe watch --pid 12345 --interval 1000 --machine MTEEyeOfHarmony

# only print machines whose fields changed (with numeric deltas)
gtnh-inspect probe watch --pid 12345 --changes

# save a live snapshot and compare it with a backup
gtnh-inspect probe dump --pid 12345 --world saves/Horizon --save live.json
gtnh-inspect diff --a backup.json --b live.json

# what is loaded right now (per dimension, with machine-type counts)
gtnh-inspect probe worlds --pid 12345

# scope a sample to one dimension and raise/lower the machine cap
gtnh-inspect probe watch --pid 12345 --dim 180 --max 200 --changes

# include hatches/buses (fallback GTMachine entries)
gtnh-inspect probe dump --pid 12345 --dim 180 --all

# inspect a chunk or a single tile entity by coordinates
gtnh-inspect probe chunk --pid 12345 --dim 180 --x 104 --z 104
gtnh-inspect probe te --pid 12345 --dim 180 --pos 104,49,104

# stop watching when a filter matches (optionally save the matching machines as evidence)
gtnh-inspect probe watch --pid 12345 --dim 180 --machine MTEEyeOfHarmony --until "progress>30000" --save trigger.json
# (the saved snapshot keeps every field; --fields only trims console output)

# stop a probe that is still attached
gtnh-inspect probe stop --pid 12345
```

All probe commands accept `--java /path/to/jdk/bin/java` if the right JDK is not on `PATH`
(`JAVA_HOME` and `GTNH_PROBE_JAVA` are also consulted).

`probe worlds` prints loaded dimensions with tile-entity / GT machine counts and the most common
machine types — useful to find which dimension and machine class to watch. `probe dump` prints a
table (or `--json`); `probe watch` prints one table per sample and `--detail` gives the full field
block. `--dim <id>` (repeatable) limits sampling to those dimensions and `--max N` caps machines per
sample (default 500). `--machine` matches Java class names exactly, by prefix or by suffix, so
`--machine MTEPurificationUnit` matches every waterline unit class. Both accept `--interval` (ms) and `--timeout` (seconds).
`--world <save>` maps the JVM's numeric dimension ids to save folder names (otherwise entries use
`DIM_<id>`), and `--save <file>` writes the sample as a regular snapshot for `diff`.
`probe dump/watch` hide fallback `GTMachine` entries by default so live and offline `scan`
select the same machines; add `--all` to include hatches/buses.
`--where "progress>0"` filters entries by field (repeatable, AND) for `probe dump` and
`probe watch`.

## What it samples

For every GregTech `BaseMetaTileEntity` in the loaded worlds:

- machine class (simple name), dimension id, block position, chunk coordinates
- `chunkModified` — `Chunk.isModified` of the machine's chunk
- primitive/enum/String fields of the meta tile entity (up to 120 per machine), including
  `mProgresstime`, `mMaxProgresstime`, `mTotalRunTime`, `mLastWorkingTick`, `mEfficiency`, `mEUT`, ...
- `shutDownReason` / `checkRecipeResult` as `{"key": ...}`
- `BigInteger` fields as decimal strings (the Python side converts them back to ints)
- stored fluids from `validFluidMap` as `stored.<fluid>`
- `mInventory` summary (`slots`, `slotsUsed`, `itemCount`, first items) and FluidStack fields
  (`{"fluid": ..., "amount": ...}`)

The Python side maps Java field names onto the same pseudo-NBT keys the offline extractors use
(`gtnh_save_inspector/live/convert.py`), so `show`/`scan`/`diff`-style formatting is shared.

## How it works

1. `gtnh-inspect probe …` locates the packaged agent (`live/agent/live-probe.jar`) and attach helper
   (`live/agent/attach/AttachMain.class`).
2. It runs `java --add-modules jdk.attach -cp <attach dir> AttachMain <pid> <agent.jar> <args>`.
3. The agent starts a daemon thread: finds `MinecraftServer` through
   `Instrumentation#getAllLoadedClasses()` (never `Class.forName`, which breaks under modded class
   loaders), walks the loaded worlds and tile entities by reflection, and appends one JSON line per
   sample to the output file.
4. The CLI tails that file and prints samples. Stopping is file-based: the CLI creates
   `<tmp>/gtnh-save-inspector/probe-<pid>.stop`, which the agent checks each iteration.

If you **rebuild the agent while the game is running**, the JVM keeps the previously loaded
`LiveProbeAgent` class; restarting the game is required to load a new build (or use a new agent
class name for testing). Every attach resets the agent options, so a later `probe dump` does not
inherit a previous `--machine`/`--samples` filter.

Agent arguments are a semicolon-separated list:

```text
out=<jsonl path>;stop=<stop flag path>;interval=<ms>;filter=<class>[,<class>...];samples=<n>;log=<path>
```

## Safety

- The probe **never writes to the world save** and never retransforms classes.
- It is read-only reflection; the only side effect is a JSONL file under the temp directory.
- If a future experiment needs to modify state (e.g. forcing `Chunk.isModified`), it must live in a
  separate, clearly marked build with an explicit opt-in flag.

## Limitations

- Dimension labels: without `--world`, live entries use `DIM_<id>`. `diff` normalises
  `PERSONAL_DIM_180`, `DIM180` and `DIM_180` to the same numeric id, so cross offline/live
  diffs work; pass `--world <save>` to print save-folder names directly.
- Only GregTech meta tile entities are sampled; other mods' tile entities are ignored.
- `--machine` filters by Java simple class name (`MTEEyeOfHarmony`); `--machine GTMultiblock` means
  "no filter".
- Sampling walks loaded tile entity lists, so on very large bases the cost is proportional to the
  number of loaded tile entities (one walk per interval).

## Agent class versioning

The agent class and jar are versioned (`LiveProbeAgent3` / `live-probe-3.jar`). A running
game keeps the first class it loaded, so bumping the version is what lets a fixed agent load
without restarting Minecraft. Bump both names in `agents/java/`, `agents/build.ps1`,
`agents/build.sh` and `gtnh_save_inspector/live/attach.py` when changing the agent.
