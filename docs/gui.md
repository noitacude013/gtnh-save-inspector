# GUI

On Windows, `gtnh-inspector-launcher.pyw` (or the desktop shortcut) provides a small
launcher with native/browser modes, a log view and a clean stop button; `launch-gui.cmd`
is the same thing with a visible console. Both use `.venv` when present.

`gtnh-inspect gui` starts a local HTTP server (127.0.0.1 by default, random port, per-run token)
and opens the interface. If `pywebview` is installed it opens a native window (WebView2 on
Windows, other platform backends elsewhere); otherwise it falls back to the default browser.

```bash
gtnh-inspect gui                 # native window if pywebview is installed, else browser
gtnh-inspect gui --browser       # force the browser
gtnh-inspect gui --port 8765     # fixed port
gtnh-inspect gui --browser --no-open   # only print the URL (browser mode)
```

In the machine results table, click the `PROGRESS` or `TOTALRUN` header to cycle
ascending / descending / unsorted. The table sort is client-side and does not re-scan.

## Optional native window

The browser mode has **no extra dependencies**. A native window needs the optional extra:

```bash
pip install -e ".[gui]"          # pywebview (+ pythonnet on Windows), uses WebView2
```

Windows 11 ships the WebView2 runtime; on older systems install the Evergreen runtime from
Microsoft. If pywebview/WebView2 fails, the tool automatically falls back to the browser.

## Tabs

| Tab | What it does |
|---|---|
| Worlds | scan a saves/instance directory, list worlds and backup `.zip` files |
| Machines | scan with dims/machine/filter/sort/top/all/fast/jobs, progress, detail + raw NBT, CSV/snapshot export |
| Snapshots & Diff | capture/import snapshots, diff A/B with `ignore` fields, metadata warning |
| Live probe | find/auto PID, watch live machines, changes-only, min-delta, `until` alerts, save snapshot, chunk/TE inspection |
| Settings | default world/saves/pid/java, language (zh/en), theme, config path |

Everything stays read-only; the GUI never writes to the save folder.

## API

The frontend is a thin layer over a JSON API; the same API can be used by scripts/AI:

```
GET  /api/version                 GET  /api/worlds?dir=
POST /api/jobs/scan               GET  /api/jobs/{id}
POST /api/jobs/{id}/cancel        GET  /api/entry?world&dim&pos
POST /api/export                  GET  /api/snapshots
POST /api/snapshots/import        POST /api/diff
GET  /api/download?name=          GET  /api/download?path=
GET  /api/probe/find              POST /api/probe/connect
GET  /api/probe/state             POST /api/probe/stop
POST /api/probe/save              POST /api/probe/chunk
POST /api/probe/te
```

All `/api/*` calls require the `X-GTNH-Token` header (or `?token=`) printed in the launch URL.
`/api/download?name=` serves files generated in the server workspace; `/api/download?path=`
serves snapshots explicitly registered/imported in the GUI (never arbitrary paths).

Snapshot and CSV export folders can be configured in Settings. A blank value uses the
persistent GUI workspace. Exports are downloaded through the token-protected download
endpoint, and only files inside the configured export folders/workspace are served.

The GUI is monochrome by default (light: white/black, dark: black/white). The online probe
machine-class field is an editable datalist: built-in common classes plus classes seen in scans
and live samples; free text is accepted, and an unmatched value is allowed (the watch simply
shows zero rows). Changing a live parameter takes effect only after clicking Connect again;
the running watch is not auto-restarted.

Scanning a saves directory and selecting a world are remembered automatically; the last
saves directory is auto-scanned on startup, so the Settings page is only needed for advanced
overrides. The GUI binds to `127.0.0.1` by default; `--host` exposes it (the token is still required).
Snapshots/exports live in a persistent workspace under the config directory
(`…/gtnh-save-inspector/gui-workspace`), so they survive GUI restarts. The server keeps the
100 most recent generated files and prunes older ones at startup; Settings → Clean workspace
can remove them explicitly, and the API endpoint is `POST /api/workspace/clean`.

## Tests

```bash
python -m unittest discover -v      # includes tests/test_gui_api.py
python scripts/gui_smoke.py        # headless API smoke, CI-safe
```

The native window path is verified manually with `pywebview` (page load, worlds, scan, detail,
snapshot/download, diff, settings/theme). `tests/frontend_smoke.mjs` runs a headless jsdom
smoke test (world → scan → detail → language switch → theme) in CI.
