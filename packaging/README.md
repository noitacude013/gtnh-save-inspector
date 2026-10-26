# Single-file Windows GUI builds

This directory contains the PyInstaller builds for the standalone GUI executable.

## Standard build

```powershell
cd C:\path\to\gtnh-save-inspector
.venv\Scripts\python.exe -m pip install pyinstaller
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-exe.ps1
```

Output:

```text
dist\GTNH-Save-Inspector.exe   (about 13 MB)
```

Live probing needs an installed Java 11+ JDK with `jdk.attach`. Offline scanning,
snapshots and CSV work without Java.

## Full-dependency build

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build-exe-full.ps1
```

Output:

```text
dist\GTNH-Save-Inspector-Full.exe   (about 29 MB)
```

This build embeds a `jlink` OpenJDK 17 runtime containing `jdk.attach`, so live probing
works on machines without a separate Java installation. The runtime is generated under
`packaging/java-runtime/` during the build and is not committed.

Both builds are GUI-only (windowed, no console). The normal `gtnh-inspect` CLI remains
available from the Python install / repository.

## What is bundled

- `gtnh_save_inspector` Python package
- `gui/static/*` frontend files
- `live/agent/live-probe-13.jar` and `live/agent/attach/*.class`
- pywebview + pythonnet + clr_loader dependencies
- app icon
- (full build only) jlink OpenJDK 17 runtime

## Runtime requirements

- **Windows 10/11**, WebView2 Runtime (Windows 11 has it; Edge/WebView2 is a common
  install on Windows 10). If WebView2 is unavailable the exe falls back to the browser.
- Live probe also needs the game to be running; the GUI discovers its PID or accepts a
  manual PID.
- The full build still relies on the Windows WebView2 component; it does not embed a
  fixed WebView2 runtime.

## Notes

- One-file builds extract to a temporary directory on first launch (about 1–3 seconds).
- Diagnostics are written to `%TEMP%\gtnh-save-inspector-exe.log`.
- Some antivirus products may flag unsigned one-file PyInstaller executables; sign the
  exe for distribution if needed.
- To use a different icon or version metadata, edit the spec files in this directory.
