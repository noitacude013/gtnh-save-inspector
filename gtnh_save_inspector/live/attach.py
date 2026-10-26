"""Locating Java and attaching the live probe agent to a running JVM."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

AGENT_JAR_NAME = "live-probe-13.jar"


class AttachError(RuntimeError):
    """Raised when the live probe cannot be attached."""


def _agents_root() -> Path:
    """Repository-level ``agents/`` directory (source checkout only)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "agents" / "java" / "LiveProbeAgent13.java"
        if candidate.is_file():
            return parent / "agents"
    return here.parent / "agent"


def _package_agent_dir() -> Path:
    return Path(__file__).resolve().parent / "agent"


def default_artifact_paths() -> Tuple[Path, Path]:
    """Return (agent jar, attach class directory), preferring packaged artifacts."""
    jar_override = os.environ.get("GTNH_PROBE_AGENT_JAR")
    attach_override = os.environ.get("GTNH_PROBE_ATTACH_DIR")
    if jar_override and os.path.isfile(jar_override):
        attach_dir = Path(attach_override) if attach_override else _package_agent_dir() / "attach"
        if (attach_dir / "AttachMain.class").is_file():
            return Path(jar_override), attach_dir
    package = _package_agent_dir()
    jar = package / AGENT_JAR_NAME
    if jar.is_file():
        attach_dir = package / "attach"
        if (attach_dir / "AttachMain.class").is_file():
            return jar, attach_dir
    root = _agents_root()
    return root / AGENT_JAR_NAME, root / "attach"


def find_java(explicit: Optional[str] = None) -> str:
    """Locate a JDK 11+ ``java`` executable (attach needs ``jdk.attach``)."""
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    env_java = os.environ.get("GTNH_PROBE_JAVA")
    if env_java:
        candidates.append(env_java)
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(os.path.join(java_home, "bin", "java"))
    on_path = shutil.which("java")
    if on_path:
        candidates.append(on_path)
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise AttachError(
        "no Java executable found; pass --java <path-to-jdk-bin/java> or set JAVA_HOME"
    )


def java_version(java: str) -> Tuple[int, str]:
    try:
        result = subprocess.run(
            [java, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        raise AttachError("cannot run %s: %s" % (java, exc)) from exc
    output = (result.stderr or "") + (result.stdout or "")
    match = re.search(r'version "(\d+)', output)
    if not match:
        return 0, output.strip()
    major = int(match.group(1))
    if major == 1:
        match2 = re.search(r'version "1\.(\d+)', output)
        major = int(match2.group(1)) if match2 else 0
    return major, output.strip()


def _build(path: Path) -> None:
    """Best-effort compile fallback for source checkouts (requires javac + jar)."""
    javac = shutil.which("javac")
    jar_tool = shutil.which("jar")
    root = _agents_root()
    if not javac or not jar_tool:
        raise AttachError(
            "live-probe.jar is missing and javac/jar are not available; "
            "build it with agents/build.ps1 or agents/build.sh"
        )
    cache = Path(tempfile.gettempdir()) / "gtnh-save-inspector-build"
    cache.mkdir(parents=True, exist_ok=True)
    sources = [str(root / "java" / "LiveProbeAgent13.java"), str(root / "java" / "AttachMain.java")]
    subprocess.run([javac, "--release", "8", "-d", str(cache / "agent")] + [sources[0]], check=True)
    subprocess.run([javac, "--release", "11", "-d", str(cache / "attach")] + [sources[1]], check=True)
    manifest = cache / "manifest.txt"
    manifest.write_text(
        "Agent-Class: LiveProbeAgent13\nCan-Redefine-Classes: false\nCan-Retransform-Classes: false\n",
        encoding="ascii",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [jar_tool, "cfm", str(path), str(manifest), "-C", str(cache / "agent"), "."], check=True
    )
    attach_dir = path.parent / "attach"
    attach_dir.mkdir(parents=True, exist_ok=True)
    built_class = cache / "attach" / "AttachMain.class"
    if built_class.is_file():
        shutil.copy2(built_class, attach_dir / "AttachMain.class")


def ensure_artifacts() -> Tuple[Path, Path]:
    """Return usable (agent jar, attach dir), building them if needed."""
    jar, attach_dir = default_artifact_paths()
    if not jar.is_file() or not (attach_dir / "AttachMain.class").is_file():
        try:
            _build(jar)
        except AttachError:
            raise
        except Exception as exc:  # pragma: no cover - environment specific
            raise AttachError("failed to build the live probe agent: %s" % exc) from exc
    if not jar.is_file() or not (attach_dir / "AttachMain.class").is_file():
        raise AttachError("live probe artifacts are missing; run agents/build.ps1")
    return jar, attach_dir


def stop_flag_path(pid: int) -> Path:
    return Path(tempfile.gettempdir()) / "gtnh-save-inspector" / ("probe-%d.stop" % pid)


def attach_agent(
    pid: int,
    agent_args: str,
    java: Optional[str] = None,
) -> str:
    """Attach the live probe agent; returns the attacher process output."""
    if pid <= 0:
        raise AttachError("invalid pid: %r" % pid)
    java_path = find_java(java)
    major, _version = java_version(java_path)
    if major < 11:
        raise AttachError(
            "Java %d is too old for the attach API; a JDK 11+ java is required (use --java)" % major
        )
    jar, attach_dir = ensure_artifacts()
    command = [
        java_path,
        "--add-modules",
        "jdk.attach",
        "-cp",
        str(attach_dir),
        "AttachMain",
        str(pid),
        str(jar),
        agent_args,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
    except subprocess.TimeoutExpired as exc:
        raise AttachError("attach timed out") from exc
    except OSError as exc:
        raise AttachError("cannot run %s: %s" % (java_path, exc)) from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise AttachError("attach failed (exit %d): %s" % (result.returncode, message))
    return (result.stdout or "").strip()


def clear_stop_flag(pid: int) -> None:
    path = stop_flag_path(pid)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def request_stop(pid: int) -> Path:
    path = stop_flag_path(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stop\n", encoding="ascii")
    return path

