# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the full-dependency, single-file GTNH Save Inspector GUI.

This build also embeds a jlink Java runtime (jdk.attach) so live probing works on
machines without a separately installed JDK. WebView2 is still a Windows component.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
RUNTIME = os.path.join(ROOT, "packaging", "java-runtime")
if not os.path.isdir(RUNTIME):
    raise SystemExit("missing %s; run packaging/build-exe-full.ps1 first" % RUNTIME)

datas = []
datas += collect_data_files("gtnh_save_inspector")
datas += collect_data_files("webview", include_py_files=False)
for package in ("pythonnet", "clr_loader", "cffi", "bottle", "proxy_tools"):
    try:
        datas += collect_data_files(package, include_py_files=False)
    except Exception:
        pass
icon = os.path.join(ROOT, "assets", "gtnh-inspector.ico")
if os.path.isfile(icon):
    datas.append((icon, "assets"))
datas.append((RUNTIME, "java-runtime"))

binaries = []
for package in ("pythonnet", "clr_loader", "webview", "cffi"):
    try:
        binaries += collect_dynamic_libs(package)
    except Exception:
        pass

hiddenimports = []
for package in ("webview", "clr_loader", "pythonnet", "bottle", "proxy_tools", "cffi"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass
hiddenimports += ["clr", "pythonnet", "webview.platforms.edgechromium"]

a = Analysis(
    [os.path.join(ROOT, "packaging", "gtnh_inspector_exe.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GTNH-Save-Inspector-Full",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icon if os.path.isfile(icon) else None,
)
