"""User configuration (defaults for world/pid/java) stored as JSON.

Location: ``$GTNH_INSPECTOR_CONFIG`` if set, else
``%APPDATA%/gtnh-save-inspector/config.json`` on Windows,
``$XDG_CONFIG_HOME/gtnh-save-inspector/config.json`` elsewhere (falling back to ~/.config).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

def config_path() -> Path:
    override = os.environ.get("GTNH_INSPECTOR_CONFIG")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "gtnh-save-inspector" / "config.json"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "gtnh-save-inspector" / "config.json"


def load() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


_save_lock = threading.Lock()
_value_lock = threading.Lock()


def save(config: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _save_lock:
        fd, temp_path = tempfile.mkstemp(prefix="config-", suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config, handle, indent=1, ensure_ascii=False)
                handle.write("\n")
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    return path


def set_value(key: str, value: str) -> Path:
    with _value_lock:
        config = load()
        if key == "pid":
            try:
                config[key] = int(value)
            except ValueError:
                config[key] = value
        else:
            config[key] = value
        return save(config)


def get_value(key: str, default=None):
    return load().get(key, default)


def apply_defaults(args) -> None:
    """Fill unset CLI arguments from the config file (mutates argparse Namespace)."""
    config = load()
    if hasattr(args, "world") and not getattr(args, "world", None):
        world = config.get("world")
        if world:
            args.world = world
    if hasattr(args, "pid") and getattr(args, "pid", None) is None:
        pid = config.get("pid")
        if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit()):
            args.pid = int(pid)
    if hasattr(args, "java") and not getattr(args, "java", None):
        java = config.get("java")
        if java:
            args.java = java
