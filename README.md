# gtnh-save-inspector

[中文说明](README_zh.md)

A read-only inspector for **GregTech: New Horizons** (Minecraft 1.7.10) saves and running clients.

> **Compatibility:** developed and tested against **GTNH 2.8.4**. GTNH 2.9.x may change machine
> classes or NBT layouts; offline scan and live extraction there are best-effort, so verify results.

It is useful when you need to know whether a machine actually saved its state, what changed between
two backups, or what a machine looks like in memory right now.

**Current version: v1.0**

Offline parsing never writes to the save. The live probe only reads loaded chunks and tile entities.

## Features

- Read `level.dat`, dimension folders and Anvil region files directly, including GTNH backup zips.
- Scan a dimension by machine type, block position, field filters and sort order.
- Extract readable state from common GTNH machines:
  - Eye of Harmony: progress, total runtime, rocket tier, stored fluids, shutdown/check-recipe state
  - Waterline purification unit: progress and controller position
  - Quantum computer / data bank: computation and wireless mode
  - Research station: computation usage and machine type
  - Generic GT multiblocks and single machines; every multiblock controller with
  progress fields is covered automatically, and any extra scalar NBT fields are exposed
  under `extra`
- Save snapshots as JSON or gzip, then diff them with numeric deltas and ignored-field support.
- Export scan results to CSV.
- Attach to a running game with a JDK 11+ runtime and inspect loaded machines, chunks and tile
  entities without opening the save.
- Use the local GUI (browser or native pywebview window) for world browsing, machine detail,
  snapshots/diff, live probes and chunk/TE inspection.
- Switch the GUI between Chinese/English and light/dark monochrome themes.
- Run scans in the background with progress and cancellation.

## Install

```bash
git clone https://github.com/noitacude013/gtnh-save-inspector.git
cd gtnh-save-inspector
python -m pip install -e .
```

Python 3.9+ is required. The CLI and offline inspection use only the standard library.

For the native GUI window on Windows:

```bash
python -m pip install -e ".[gui]"
```

That installs pywebview (and pythonnet on Windows). Browser mode works without it.

## Start the GUI

```bash
gtnh-inspect gui                 # native window when pywebview is available, otherwise browser
gtnh-inspect gui --browser       # always use the browser
gtnh-inspect gui --port 8765     # fixed port (default is a random free port)
```

In the machine results table, click the `PROGRESS` or `TOTALRUN` header to cycle through
ascending, descending and unsorted. Snapshot and CSV export folders can be set in Settings;
leave them empty to use the default workspace.

The GUI binds to `127.0.0.1` by default, uses a random per-run token and remembers the last saves
folder and selected world. It does not upload anything.

On Windows you can also double-click `gtnh-inspector-launcher.pyw`, or run `launch-gui.cmd` when
you want a visible console. The launcher shows the GUI log and can stop the local server cleanly.

## Single-file exe (Windows)

The repository does not ship a prebuilt exe. Build one with the project venv:

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-exe.ps1
```

There are two builds:

- **Standard** — `dist\GTNH-Save-Inspector.exe` (about 13 MB). Live probing needs an installed
  Java 11+ JDK with `jdk.attach`.
- **Full dependency** — `dist\GTNH-Save-Inspector-Full.exe` (about 29 MB). Embeds a jlink
  OpenJDK 17 runtime, so live probing works without a separate Java install.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-exe-full.ps1
```

Both builds still use the Windows WebView2 runtime for the native window (Windows 11 includes it;
the exe falls back to the browser if it is unavailable). See [packaging/README.md](packaging/README.md).

## CLI quick start

```bash
# list worlds below a saves folder
gtnh-inspect worlds --dir "/path/to/instance/saves"

# scan one dimension, only Eye of Harmony machines, with a snapshot output
gtnh-inspect scan --world "/path/to/saves/Horizon" --dim 180 \
    --mte MTEEyeOfHarmony --out current.json

# inspect one machine by block position
gtnh-inspect show --world "/path/to/saves/Horizon" \
    --dim PERSONAL_DIM_180 --pos 104,49,104

# compare a backup snapshot with the current scan
gtnh-inspect diff --a backup.json --b current.json --ignore mUpdate,mTotalRunTime

# live probe against a running game (JDK 11+)
gtnh-inspect probe dump --pid 12345 --machine MTEEyeOfHarmony
gtnh-inspect probe watch --pid 12345 --machine MTEEyeOfHarmony --changes

# save the current live state and compare it with the save file
gtnh-inspect probe dump --pid 12345 --world "/path/to/saves/Horizon" --save live.json
gtnh-inspect diff --a current.json --b live.json
```

`gtnh-inspect <command> --help` lists all options. `--json` and `--jsonl` are available for scripting.

## Commands

| Command | Purpose |
| --- | --- |
| `worlds` | List save folders and backup zips below a path |
| `show` | Show the machine at a block position |
| `scan` | Scan dimensions for machines; filters, sorting, CSV and snapshot output |
| `diff` | Compare two snapshots |
| `dump` | Print raw (sanitised) NBT of one tile entity |
| `extractors` | List registered machine extractors |
| `probe dump` | Print one live sample from a running game |
| `probe watch` | Stream live samples with optional change/until filtering |
| `probe chunk` / `probe te` | Inspect a loaded chunk or one tile entity |
| `probe worlds` / `probe find` | List live dimensions or find running GTNH JVMs |
| `probe stop` | Ask a probe session to stop |
| `gui` | Open the local web GUI |
| `config` | Show or set default world/pid/java/saves |
| `capabilities` | Machine-readable command and exit-code listing |

## Snapshots

A snapshot contains a header and one entry per machine:

```json
{
  "format": 1,
  "tool": "gtnh-save-inspector",
  "tool_version": "1.0",
  "snapshot": { "captured": "...", "source": "...", "world": "Horizon" },
  "entries": [
    {
      "dim": "PERSONAL_DIM_180",
      "chunk": [6, 6],
      "pos": [104, 49, 104],
      "machine": "MTEEyeOfHarmony",
      "fields": { "progress": 29178, "max": 39850, "totalRun": 9256780 }
    }
  ]
}
```

## Testing

```bash
# unit tests; no game or save required
python -m unittest discover -v

# offline checks against the anonymous fixture
python scripts/ci_offline.py

# GUI API / static / frontend checks
python scripts/gui_smoke.py
python scripts/check_gui_static.py
npm ci
node tests/frontend_smoke.mjs

# full end-to-end run against a real save and optionally a running game
python scripts/e2e_check.py --world "/path/to/saves/Horizon" \
    --backup "/path/to/backups/latest.zip" --pid <game-pid>
```

CI runs the unit, offline, GUI and frontend checks on Python 3.9 and 3.12.

## Limitations

- Developed against GTNH 2.8.4; GTNH 2.9.x compatibility is not guaranteed.
- 1.7.10 Anvil saves only.
- Extractor fields depend on the GTNH version; missing fields are reported as `null` instead of
  failing the scan.
- Large dimensions take time to scan; use `--dim`, `--mte`, `--limit`, `--top` and `--fast`.
- Live probing needs a JDK 11+ `java` and a running game. On the title screen it reports `no-server`.
- Live dimensions use numeric labels such as `DIM_180` when the save folder is not provided.

## Privacy

The tool does not send data to any external service. Snapshots can contain coordinates, inventories and player UUIDs;
review them before sharing. See [docs/privacy.md](docs/privacy.md).

## Contributing

Machine extractors are small and self-contained; see [docs/extractors.md](docs/extractors.md).
Plugins can be added without forking: [docs/plugins.md](docs/plugins.md).

## License

MIT — see [LICENSE](LICENSE).
