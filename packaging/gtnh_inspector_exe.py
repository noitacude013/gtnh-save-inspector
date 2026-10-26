"""Entry point for the single-file GTNH Save Inspector GUI executable.

This is intentionally GUI-only: a windowed PyInstaller build has no console, so the
full CLI stays available through the normal `gtnh-inspect` command / Python install.
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import traceback
from pathlib import Path


def _ensure_stdio():
    # A --windowed build has sys.stdout/sys.stderr set to None; keep a log in
    # %TEMP% so native-window/WebView2 failures are diagnosable.
    log_path = os.path.join(tempfile.gettempdir(), "gtnh-save-inspector-exe.log")
    try:
        log = open(log_path, "a", encoding="utf-8")
        print("\n=== GTNH Save Inspector exe ===\n", file=log)
    except OSError:
        log = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = sys.stdout


def _configure_bundled_java():
    """Use the packaged JDK runtime when this is the full-dependency build."""
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    java = base / "java-runtime" / "bin" / ("java.exe" if os.name == "nt" else "java")
    if java.is_file():
        os.environ.setdefault("GTNH_PROBE_JAVA", str(java))
        print("bundled java: %s" % java)


def _message(text: str, title: str = "GTNH Save Inspector"):
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x00000010)
    except Exception:
        pass


def main() -> int:
    _ensure_stdio()
    _configure_bundled_java()
    print("frozen:", getattr(sys, "frozen", False), "meipass:", getattr(sys, "_MEIPASS", None))
    try:
        import webview

        print("pywebview imported:", getattr(webview, "__version__", "?"))
    except Exception:
        traceback.print_exc()
    try:
        from gtnh_save_inspector.gui.server import GuiServer, run_browser, run_native
        print("server module imported")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _message("无法加载 GTNH Save Inspector：\n%s" % exc)
        return 2

    try:
        server = GuiServer()
    except Exception as exc:  # noqa: BLE001
        _message("无法启动本地 GUI 服务：\n%s" % exc)
        return 2

    if "--browser" in sys.argv:
        try:
            run_browser(server, open_browser=True)
            return 0
        except Exception as exc:  # noqa: BLE001
            _message("无法启动浏览器界面：\n%s" % exc)
            return 2

    print("calling run_native")
    if run_native(server):
        print("native window returned OK")
        return 0
    print("native window unavailable; falling back to browser")

    # pywebview / WebView2 unavailable: fall back to the default browser.
    try:
        if getattr(server, "_closed", False):
            server = GuiServer()
        run_browser(server, open_browser=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _message("原生窗口不可用，浏览器回退也失败：\n%s" % exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
