"""Find running GTNH game JVMs (used by ``probe find`` and ``--pid auto``)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time

_GTNH = re.compile(r"GT New Horizons|GTNH|gtnh")
_CACHE = {"at": 0.0, "games": []}
_CACHE_TTL = 5.0
_JAVA = re.compile(r"[\\/]([^\\/]+)[\\/]bin[\\/]java(?:w)?\.exe", re.IGNORECASE)
_VERSION = re.compile(r'--version\s+(?:"([^"]+)"|(.+?))(?=\s+--|$)')
_GAMEDIR = re.compile(r'--gameDir\s+(?:"([^"]+)"|(\S+))')
_JAR = re.compile(r'-Dminecraft\.client\.jar=(?:"([^"]+)"|(\S+))')


def _first(match):
    if not match:
        return None
    for group in match.groups():
        if group:
            return group
    return None


def _candidate(pid, memory_bytes, command):
    command = command or ""
    jar = _first(_JAR.search(command)) or ""
    game_dir = _first(_GAMEDIR.search(command))
    instance = _first(_VERSION.search(command))
    if not instance and jar:
        instance = os.path.basename(os.path.dirname(jar)) or os.path.basename(jar)
    java = _first(_JAVA.search(command))
    return {
        "pid": int(pid),
        "memoryMB": int(memory_bytes) // (1024 * 1024),
        "java": java,
        "instance": instance,
        "game_dir": game_dir,
        "command": command[:400],
    }


def find_games(force: bool = False):
    """Return running GTNH game processes, largest memory first (5 s cache)."""
    now = time.time()
    if not force and now - _CACHE["at"] < _CACHE_TTL:
        return list(_CACHE["games"])
    games = _find_windows() if os.name == "nt" else _find_posix()
    _CACHE["at"] = now
    _CACHE["games"] = games
    return list(games)


def _find_windows():
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-CimInstance Win32_Process -Filter \"Name = 'java.exe' OR Name = 'javaw.exe'\" | "
        "Select-Object ProcessId,WorkingSetSize,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if not (result.stdout or "").strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    items = data if isinstance(data, list) else [data]
    games = []
    for item in items:
        command = str(item.get("CommandLine") or "")
        if not _GTNH.search(command):
            continue
        games.append(
            _candidate(item.get("ProcessId"), item.get("WorkingSetSize") or 0, command)
        )
    games.sort(key=lambda game: game["memoryMB"], reverse=True)
    return games


def _find_posix():
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,rss=,args="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    games = []
    for line in (result.stdout or "").splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, rss, command = parts
        if not _GTNH.search(command):
            continue
        try:
            games.append(_candidate(pid, int(rss) * 1024, command))
        except ValueError:
            continue
    games.sort(key=lambda game: game["memoryMB"], reverse=True)
    return games


def find_game_pid(force: bool = False):
    games = find_games(force=force)
    return games[0] if games else None


def clear_cache():
    _CACHE["at"] = 0.0
    _CACHE["games"] = []


def process_alive(pid: int) -> bool:
    """Return True if *pid* is a live process (used by the GUI live watcher)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
