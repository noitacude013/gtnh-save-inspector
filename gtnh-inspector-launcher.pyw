#!/usr/bin/env pythonw
"""GTNH Save Inspector desktop launcher.

Double-click this file (or the desktop shortcut) to open a small launcher window.
It starts the GUI in a background process, shows its log, and can stop it cleanly.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "gui-launcher.log"
URL_RE = re.compile(r"http://(?:127\.0\.0\.1|localhost):(\d+)/\?token=([^\s]+)")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _venv_python() -> Path:
    scripts = ROOT / ".venv" / "Scripts"
    for name in ("pythonw.exe", "python.exe"):
        candidate = scripts / name
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


PYTHON = _venv_python()


def _run(command, timeout=10):
    return subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=NO_WINDOW,
    )


def pywebview_available() -> bool:
    try:
        result = _run([str(PYTHON), "-c", "import webview"], timeout=15)
        return result.returncode == 0
    except Exception:
        return False


def self_test() -> int:
    print("launcher root:", ROOT)
    print("launcher python:", sys.executable)
    print("child python:", PYTHON)
    print("venv exists:", (ROOT / ".venv").is_dir())
    print("pywebview:", pywebview_available())
    print("guiscript:", (ROOT / "gtnh_save_inspector" / "__main__.py").is_file())
    return 0


def _read_tail(path: Path, limit: int = 16000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


class Launcher:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title("GTNH 存档检查器 · GUI 启动器")
        icon = ROOT / "assets" / "gtnh-inspector.ico"
        if icon.is_file():
            try:
                self.root.iconbitmap(default=str(icon))
            except Exception:
                pass
        self.root.geometry("660x440")
        self.root.minsize(560, 380)
        self.proc = None
        self.log_handle = None
        self.started_at = 0.0
        self.last_url = ""
        self.last_port = ""
        self.last_token = ""
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=self._check_native, daemon=True).start()
        self.root.after(400, self.poll)

    def _build(self):
        tk, ttk = self.tk, self.ttk
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, text="GTNH 存档检查器", font=("Segoe UI", 16, "bold")
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="离线存档检查 / 在线机器探针 / 快照对比",
            foreground="#666666",
        ).pack(anchor="w", pady=(0, 8))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=4)
        self.native_btn = ttk.Button(
            buttons, text="打开 GUI（原生窗口）", command=lambda: self.start("native")
        )
        self.native_btn.pack(side="left", padx=(0, 6))
        self.browser_btn = ttk.Button(
            buttons, text="浏览器模式", command=lambda: self.start("browser")
        )
        self.browser_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = ttk.Button(
            buttons, text="停止 GUI", command=self.stop_gui, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="打开日志", command=self.open_log).pack(side="left")

        info = ttk.Frame(frame)
        info.pack(fill="x", pady=(8, 4))
        self.status_var = tk.StringVar(value="就绪")
        self.native_var = tk.StringVar(value="原生窗口：检测中…")
        ttk.Label(info, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(
            anchor="w"
        )
        ttk.Label(info, textvariable=self.native_var, foreground="#666666").pack(anchor="w")

        ttk.Label(frame, text="启动日志（最后 16 KB）", foreground="#666666").pack(
            anchor="w", pady=(8, 2)
        )
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            log_frame, height=10, wrap="none", font=("Consolas", 9), state="disabled"
        )
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        ttk.Label(
            frame,
            text="关闭原生 GUI 窗口即可正常退出；浏览器模式请点「停止 GUI」。",
            foreground="#888888",
        ).pack(anchor="w", pady=(8, 0))

    def _check_native(self):
        available = pywebview_available()
        self.root.after(
            0,
            lambda: self.native_var.set(
                "原生窗口：可用" if available else "原生窗口：不可用（将自动回退浏览器）"
            ),
        )

    def _set_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _refresh_log(self):
        self._set_log(_read_tail(LOG))

    def start(self, mode):
        if self.proc is not None and self.proc.poll() is None:
            self.status_var.set("GUI 已在运行，请先停止或关闭窗口")
            return
        self._refresh_log()
        header = "\n" + "=" * 60 + "\n[launcher] %s %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"),
            mode,
        )
        try:
            self.log_handle = LOG.open("a", encoding="utf-8", errors="replace")
            self.log_handle.write(header)
            self.log_handle.flush()
        except OSError:
            self.log_handle = subprocess.DEVNULL
        command = [str(PYTHON), "-m", "gtnh_save_inspector", "gui"]
        if mode == "browser":
            command.append("--browser")
        try:
            self.proc = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
                creationflags=NO_WINDOW,
            )
        except OSError as exc:
            self.status_var.set("启动失败: %s" % exc)
            self.proc = None
            return
        self.started_at = time.time()
        self.status_var.set("启动中…")
        self.native_btn.configure(state="disabled")
        self.browser_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.last_url = self.last_port = self.last_token = ""
        self.root.after(300, self.poll)

    def poll(self):
        if self.proc is None:
            self.root.after(500, self.poll)
            return
        self._refresh_log()
        text = _read_tail(LOG, 100000)
        matches = URL_RE.findall(text)
        if matches:
            port, token = matches[-1]
            self.last_port, self.last_token = port, token
            self.last_url = "http://127.0.0.1:%s/" % port
        code = self.proc.poll()
        if code is None:
            suffix = (" · " + self.last_url) if self.last_url else ""
            self.status_var.set("运行中" + suffix)
            self.root.after(500, self.poll)
            return
        self.status_var.set("已退出（code %s）" % code)
        self.native_btn.configure(state="normal")
        self.browser_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if self.log_handle not in (None, subprocess.DEVNULL):
            try:
                self.log_handle.close()
            except OSError:
                pass
        self.log_handle = None
        self.proc = None
        if code != 0 and time.time() - self.started_at < 15:
            self.status_var.set(
                "启动失败（code %s），请查看日志。常见原因：依赖未安装或端口被占用。" % code
            )
        self._refresh_log()

    def stop_gui(self):
        if self.proc is None or self.proc.poll() is not None:
            return
        self.status_var.set("正在停止…")
        if self.last_port and self.last_token:
            try:
                import urllib.request

                request = urllib.request.Request(
                    "http://127.0.0.1:%s/api/shutdown?token=%s"
                    % (self.last_port, self.last_token),
                    data=b"{}",
                    method="POST",
                )
                request.add_header("Content-Type", "application/json")
                urllib.request.urlopen(request, timeout=5).read()
            except Exception:
                pass
        for _ in range(30):
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.status_var.set("已停止")
        self.native_btn.configure(state="normal")
        self.browser_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def open_log(self):
        self._refresh_log()
        try:
            os.startfile(LOG)  # type: ignore[attr-defined]
        except OSError:
            self.status_var.set("日志文件尚未生成: %s" % LOG)

    def on_close(self):
        import tkinter.messagebox as messagebox

        if self.proc is not None and self.proc.poll() is None:
            if not messagebox.askyesno("退出", "GUI 仍在运行，停止并退出吗？"):
                return
            self.stop_gui()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if "--smoke-start" in sys.argv:
        app = Launcher()
        app.start("native")
        app.root.after(5000, app.stop_gui)
        app.root.after(7000, app.root.destroy)
        app.run()
        raise SystemExit(0)
    try:
        Launcher().run()
    except Exception as exc:  # noqa: BLE001
        # pythonw has no console; show a dialog when Tk is available.
        try:
            import tkinter.messagebox as messagebox
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("GTNH 启动器", "启动器初始化失败:\n%s" % exc)
            root.destroy()
        except Exception:
            pass
        raise
