"""Local HTTP API and static-file server for the GUI.

Only binds to loopback by default and requires a per-run token, so other local
applications cannot call the API by accident.  The browser window (or pywebview) just
talks to this server; all game/save access stays in Python.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__, config as config_module, services
from ..core.snapshot import Snapshot
from ..core.nbt import NbtError
from ..core.region import RegionError
from ..core.world import WorldError, open_world
from ..dimensions import dimension_id_of
from ..filters import filter_entries, matches, parse_filters
from ..live import (
    AttachError,
    attach_agent,
    clear_stop_flag,
    machine_to_entry,
    read_samples,
    request_stop,
    stop_flag_path,
)
from ..live.changes import diff_entries, filter_changes
from ..live.findgame import find_game_pid, find_games, process_alive

STATIC_DIR = Path(__file__).with_name("static")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _job_id() -> str:
    return secrets.token_hex(6)


def _default_saves_dir() -> str:
    configured = config_module.get_value("saves")
    if configured:
        return configured
    return os.path.join(os.getcwd(), "saves")


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _probe_filter(machine):
    if not machine:
        return None
    lowered = machine.lower()
    if lowered in ("all", "*", "gtmultiblock"):
        return None
    return machine


class GuiServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, workspace: str = None):
        self.host = host
        self.token = secrets.token_urlsafe(18)
        if workspace is None:
            workspace = os.path.join(str(config_module.config_path().parent), "gui-workspace")
        self.workspace = os.path.abspath(workspace)
        os.makedirs(self.workspace, exist_ok=True)
        self._prune_workspace()
        self._jobs = {}
        self._job_lock = threading.Lock()
        self._snapshots = []
        self._snapshot_cache = {}
        self._snapshot_stat = {}
        self._snapshot_lock = threading.Lock()
        self._live = None
        self._live_config = None
        self._live_lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._closing = False
        self._httpd = ThreadingHTTPServer((host, int(port)), _make_handler(self))
        self._thread = None
        self._closed = False
        self._started = False

    # -- lifecycle ---------------------------------------------------------
    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        host = self.host
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"
        if ":" in host and not host.startswith("["):
            host = "[%s]" % host
        return "http://%s:%d/?token=%s" % (host, self.port, self.token)

    def start(self) -> "GuiServer":
        if self._started:
            return self
        if self._closed:
            raise RuntimeError("this GuiServer was stopped; create a new instance")
        self._closed = False
        self._closing = False
        self._started = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._closing = True
        with self._job_lock:
            for job in self._jobs.values():
                if job["status"] == "running":
                    job["cancel"].set()
        with self._probe_lock:
            with self._live_lock:
                live, self._live = self._live, None
            if live is not None:
                live.stop()
        if self._started:
            self._httpd.shutdown()
            self._started = False
        self._httpd.server_close()
        self._closed = True

    # -- helpers -----------------------------------------------------------
    WORKSPACE_KEEP = 100
    WORKSPACE_PREFIXES = ("probe-", "inspect-", "live-", "export-", "snapshot-")

    def _prune_workspace(self, keep=None) -> dict:
        keep = self.WORKSPACE_KEEP if keep is None else max(0, int(keep))
        generated = []
        try:
            names = os.listdir(self.workspace)
        except OSError:
            return {"removed": 0, "kept": 0}
        for name in names:
            if not name.startswith(self.WORKSPACE_PREFIXES):
                continue
            path = os.path.join(self.workspace, name)
            if os.path.isfile(path):
                try:
                    generated.append((os.path.getmtime(path), path))
                except OSError:
                    continue
        generated.sort(reverse=True)
        removed = 0
        for _mtime, path in generated[keep:]:
            try:
                os.unlink(path)
                removed += 1
            except OSError:
                continue
        if removed:
            with self._snapshot_lock:
                for path in list(self._snapshots):
                    if not os.path.exists(path):
                        self._snapshots.remove(path)
                        self._snapshot_cache.pop(path, None)
                        self._snapshot_stat.pop(path, None)
        return {"removed": removed, "kept": min(len(generated), keep)}

    def _export_dir(self, fmt: str) -> str:
        key = "snapshot_dir" if fmt == "snapshot" else "csv_dir"
        with self._config_lock:
            config = config_module.load()
        configured = config.get(key)
        directory = configured or self.workspace
        directory = os.path.abspath(os.path.expanduser(str(directory)))
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise ApiError("cannot create export directory: %s" % exc)
        if not os.path.isdir(directory):
            raise ApiError("export path is not a directory: %s" % directory)
        return directory

    def _export_roots(self) -> list:
        roots = {services.normalize_path(self.workspace)}
        with self._config_lock:
            config = config_module.load()
        for key in ("snapshot_dir", "csv_dir"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                roots.add(services.normalize_path(value))
        return roots

    def _is_export_path(self, target: str) -> bool:
        target = services.normalize_path(target)
        for root in self._export_roots():
            if target == root or target.startswith(root + os.sep):
                return True
        return False

    def _job_update(self, job: dict, progress: float, message: str) -> None:
        with self._job_lock:
            job["progress"] = max(0.0, min(1.0, progress))
            job["message"] = message

    def _add_snapshot(self, path: str) -> dict:
        path = services.normalize_path(path)
        summary = services.snapshot_summary(path)
        try:
            stat = os.stat(path)
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        with self._snapshot_lock:
            self._snapshot_cache[path] = summary
            self._snapshot_stat[path] = signature
            if path not in self._snapshots:
                self._snapshots.append(path)
        return summary

    def _list_snapshots(self) -> list:
        # Pick up snapshots left in the persistent workspace by earlier runs.
        try:
            names = os.listdir(self.workspace)
        except OSError:
            names = []
        with self._snapshot_lock:
            known = set(self._snapshots)
        for name in names:
            if not name.lower().endswith((".json", ".json.gz")):
                continue
            path = services.normalize_path(os.path.join(self.workspace, name))
            if path in known:
                continue
            try:
                summary = services.snapshot_summary(path)
            except Exception:  # noqa: BLE001 - skip corrupt files
                continue
            with self._snapshot_lock:
                self._snapshot_cache[path] = summary
                if path not in self._snapshots:
                    self._snapshots.append(path)
        with self._snapshot_lock:
            paths = list(self._snapshots)
            cache = dict(self._snapshot_cache)
            signatures = dict(self._snapshot_stat)
        result = []
        for path in paths:
            try:
                stat = os.stat(path)
                signature = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                with self._snapshot_lock:
                    if path in self._snapshots:
                        self._snapshots.remove(path)
                    self._snapshot_cache.pop(path, None)
                    self._snapshot_stat.pop(path, None)
                continue
            if path in cache and signatures.get(path) == signature:
                result.append(cache[path])
                continue
            try:
                summary = services.snapshot_summary(path)
            except Exception:  # noqa: BLE001
                continue
            with self._snapshot_lock:
                self._snapshot_cache[path] = summary
                self._snapshot_stat[path] = signature
            result.append(summary)
        result.sort(key=lambda item: str(item.get("captured") or ""))
        return result

    # -- jobs --------------------------------------------------------------
    def start_scan_job(self, body: dict) -> dict:
        if not isinstance(body, dict):
            raise ApiError("scan body must be a JSON object")
        world = body.get("world")
        if not world:
            raise ApiError("world is required")
        for key in ("top", "limit", "jobs"):
            if body.get(key) not in (None, ""):
                try:
                    int(body[key])
                except (TypeError, ValueError):
                    raise ApiError("%s must be an integer" % key)
        # Remember the scanned world automatically; the normal flow must not
        # require a separate settings save.
        world_path = body.get("world")
        if isinstance(world_path, str) and world_path:
            try:
                normalized = os.path.abspath(os.path.expanduser(world_path))
                with self._config_lock:
                    config = config_module.load()
                    if config.get("world") != normalized:
                        config["world"] = normalized
                        config_module.save(config)
            except (OSError, ValueError, TypeError):
                pass
        job = {
            "id": _job_id(),
            "status": "running",
            "progress": 0.0,
            "message": "starting",
            "created": time.time(),
            "result": None,
            "error": None,
            "cancel": threading.Event(),
        }
        with self._job_lock:
            self._jobs[job["id"]] = job
            finished = [
                value for value in self._jobs.values() if value["status"] != "running"
            ]
            if len(finished) > 20:
                for old in finished[:-20]:
                    self._jobs.pop(old["id"], None)
        thread = threading.Thread(
            target=self._run_scan_job, args=(job, dict(body)), daemon=True
        )
        job["thread"] = thread
        thread.start()
        return {"id": job["id"]}

    def _run_scan_job(self, job: dict, body: dict) -> None:
        try:
            world_path = body["world"]
            snapshot_name = body.get("snapshot_name") or ""

            def progress(fraction, dim, count):
                self._job_update(job, fraction * 0.95, "scanned %s (%d entries)" % (dim, count))

            result = services.scan(
                world_path,
                dims=_as_list(body.get("dims")) or None,
                mte=body.get("mte") or None,
                where=_as_list(body.get("where")) or None,
                sort=body.get("sort") or None,
                top=int(body["top"]) if body.get("top") else None,
                limit=int(body["limit"]) if body.get("limit") else None,
                include_fallback=bool(body.get("all")),
                fast=bool(body.get("fast")),
                jobs=max(1, int(body.get("jobs") or 1)),
                with_stats=True,
                progress=progress,
                cancel=job["cancel"],
            )
            if body.get("snapshot") and job["cancel"].is_set():
                with self._job_lock:
                    job["status"] = "cancelled"
                    job["message"] = "cancelled"
                return
            if body.get("snapshot"):
                name = _clean_name(
                    snapshot_name or "snapshot-%s.json" % time.strftime("%Y%m%d-%H%M%S-%f")
                )
                name = _unique_name(self.workspace, name)
                path = os.path.join(self.workspace, name)
                snapshot = Snapshot(
                    source=result["world"]["path"],
                    world_name=result["world"]["name"],
                    entries=result["entries"],
                    meta=_snapshot_meta(body, result),
                )
                snapshot.save(path)
                result["snapshot"] = self._add_snapshot(path)
            with self._job_lock:
                if job["cancel"].is_set():
                    job["status"] = "cancelled"
                    job["message"] = "cancelled"
                else:
                    job["result"] = result
                    job["status"] = "done"
                    job["progress"] = 1.0
                    job["message"] = "%d entries" % len(result["entries"])
        except services.ScanCancelled:
            with self._job_lock:
                job["status"] = "cancelled"
                job["message"] = "cancelled"
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            with self._job_lock:
                job["status"] = "error"
                job["error"] = str(exc)
                job["message"] = str(exc)

    def get_job(self, job_id: str) -> dict:
        with self._job_lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ApiError("unknown job", 404)
            return {
                "id": job["id"],
                "status": job["status"],
                "progress": job["progress"],
                "message": job["message"],
                "error": job["error"],
                "result": job["result"],
            }

    def cancel_job(self, job_id: str) -> dict:
        with self._job_lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ApiError("unknown job", 404)
            job["cancel"].set()
            if job["status"] == "running":
                job["message"] = "cancelling"
                return {"id": job_id, "status": "cancelling"}
            return {"id": job_id, "status": job["status"]}

    # -- live probe --------------------------------------------------------
    def live_state(self) -> dict:
        with self._live_lock:
            live = self._live
        if live is None:
            return {"status": "disconnected"}
        return live.state()

    def connect_live(self, body: dict) -> dict:
        with self._probe_lock:
            if self._closing:
                raise ApiError("GUI server is closing", 409)
            where = _filter_list(body.get("where"))
            until = _filter_list(body.get("until"))
            try:
                parse_filters(where)
                parse_filters(until)
            except ValueError as exc:
                raise ApiError("invalid filter: %s" % exc)
            pid = self._resolve_pid(body.get("pid"))
            with self._live_lock:
                previous, self._live = self._live, None
            if previous is not None:
                previous.stop()
            live = LiveSession(
                self,
                pid,
                world=body.get("world") or None,
                machine=body.get("machine") or None,
                dims=_filter_list(body.get("dims")),
                max_machines=_int_value(body.get("max"), 500, "max"),
                interval=_int_value(body.get("interval"), 1000, "interval"),
                include_fallback=bool(body.get("all")),
                where=where,
                until=until,
                changes=bool(body.get("changes")),
                min_delta=_int_value(body.get("min_delta"), 0, "min_delta"),
            )
            if self._closing:
                live.stop()
                raise ApiError("GUI server is closing", 409)
            with self._live_lock:
                self._live = live
                self._live_config = {
                    "pid": pid,
                    "world": body.get("world") or None,
                    "machine": body.get("machine") or None,
                    "dims": _filter_list(body.get("dims")),
                    "max_machines": _int_value(body.get("max"), 500, "max"),
                    "interval": _int_value(body.get("interval"), 1000, "interval"),
                    "include_fallback": bool(body.get("all")),
                    "where": where,
                    "until": until,
                    "changes": bool(body.get("changes")),
                    "min_delta": _int_value(body.get("min_delta"), 0, "min_delta"),
                }
            return live.state()

    def stop_live(self) -> dict:
        with self._probe_lock:
            with self._live_lock:
                live, self._live = self._live, None
            if live is None:
                self._live_config = None
                return {"status": "disconnected"}
            live.stop()
            self._live_config = None
            return live.state()

    def save_live_snapshot(self) -> dict:
        with self._live_lock:
            live = self._live
        if live is None:
            raise ApiError("no live session")
        with live.lock:
            entries = list(live.entries)
            world_name = live.world_name
            pid = live.pid
        if not entries:
            raise ApiError("no live entries to save")
        name = _unique_name(
            self.workspace, "live-%s.json" % time.strftime("%Y%m%d-%H%M%S-%f")
        )
        path = os.path.join(self.workspace, name)
        snapshot = Snapshot(
            source="live:%d" % pid,
            world_name=world_name or "live",
            entries=entries,
            meta={"gui": True, "live": True},
        )
        snapshot.save(path)
        return self._add_snapshot(path)

    def _resolve_pid(self, value) -> int:
        if value is None or value == "" or value == "auto":
            found = find_game_pid()
            if not found:
                raise ApiError("no running GTNH game found (try probe find)")
            return int(found["pid"])
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ApiError("invalid pid: %r" % (value,))

    def live_inspect(self, mode: str, body: dict) -> dict:
        with self._probe_lock:
            if self._closing:
                raise ApiError("GUI server is closing", 409)
            pid = self._resolve_pid(body.get("pid"))
            dim = _int_value(body.get("dim"), None, "dim", required=True)
            watch_stopped = False
            resume_config = None
            with self._live_lock:
                live, self._live = self._live, None
                if live is not None:
                    resume_config = self._live_config
            if live is not None:
                live.stop()
                watch_stopped = True
            if mode == "chunk":
                x = _int_value(body.get("x"), None, "x", required=True)
                z = _int_value(body.get("z"), None, "z", required=True)
                extra = "x=%d;z=%d" % (x, z)
            else:
                raw_pos = body.get("pos")
                if isinstance(raw_pos, str):
                    parts = [part.strip() for part in raw_pos.split(",")]
                elif isinstance(raw_pos, list):
                    parts = raw_pos
                else:
                    raise ApiError("pos must be x,y,z")
                if len(parts) != 3:
                    raise ApiError("pos must be x,y,z")
                try:
                    positions = [int(value) for value in parts]
                except (TypeError, ValueError):
                    raise ApiError("pos must be three integers")
                extra = "pos=%s" % ",".join(str(value) for value in positions)
            out = os.path.join(
                self.workspace, "inspect-%d-%d.jsonl" % (pid, time.time_ns())
            )
            stop = stop_flag_path(pid)
            clear_stop_flag(pid)
            agent_args = "out=%s;stop=%s;mode=%s;dim=%d;%s" % (
                out, stop, mode, dim, extra
            )
            try:
                try:
                    attach_agent(pid, agent_args, java=config_module.get_value("java"))
                except AttachError as exc:
                    raise ApiError(str(exc), 502)
                deadline = time.time() + 20
                result = None
                while time.time() < deadline:
                    try:
                        samples = read_samples(out)
                    except (OSError, FileNotFoundError):
                        samples = []
                    for sample in samples:
                        if sample.get("mode") == mode or sample.get("status") in (
                            "error",
                            "no-server",
                        ):
                            result = sample
                            break
                    if result:
                        break
                    time.sleep(0.15)
            finally:
                request_stop(pid)
                cleanup_paths = [out, out + ".log", stop]
                for path in cleanup_paths:
                    _unlink(path)
                _cleanup_later(cleanup_paths)
            watch_resumed = False
            if resume_config is not None and not self._closing:
                try:
                    resumed = LiveSession(self, **resume_config)
                    with self._live_lock:
                        self._live = resumed
                    watch_resumed = True
                except Exception:  # noqa: BLE001 - inspection still succeeded
                    watch_resumed = False
            if result is None:
                raise ApiError("no response from the game (timeout)", 504)
            if result.get("status") == "error":
                raise ApiError(result.get("message") or "inspection failed")
            if result.get("status") == "no-server":
                raise ApiError("game is on the title screen; load a world first")
            result = dict(result)
            result["watch_stopped"] = watch_stopped
            result["watch_resumed"] = watch_resumed
            return result

    def handle_api(self, method: str, path: str, query: dict, body):
        value = lambda key, default=None: (query.get(key) or [default])[0]
        if method == "GET" and path == "/api/version":
            return 200, {"tool": "gtnh-save-inspector", "version": __version__}
        if path == "/api/config":
            if method == "GET":
                return 200, {"config": config_module.load(), "path": str(config_module.config_path())}
            if method == "POST":
                if not isinstance(body, dict):
                    raise ApiError("config body must be an object")
                with self._config_lock:
                    config = config_module.load()
                    for key in ("world", "saves", "pid", "java", "language", "theme", "snapshot_dir", "csv_dir"):
                        if key not in body:
                            continue
                        value = body[key]
                        if key == "pid":
                            if value is not None and not isinstance(value, (int, str)):
                                raise ApiError("pid must be an integer or string")
                        elif value is not None and not isinstance(value, str):
                            raise ApiError("%s must be a string" % key)
                        config[key] = value
                    config_module.save(config)
                    return 200, {"config": config_module.load()}
            raise ApiError("method not allowed", 405)
        if path == "/api/worlds" and method == "GET":
            directory = value("dir") or _default_saves_dir()
            try:
                worlds = services.list_worlds(directory)
            except (WorldError, OSError) as exc:
                raise ApiError(str(exc))
            # Remember the saves directory as soon as it scans successfully; the
            # Worlds/Saves page should never require a separate settings save.
            if directory:
                try:
                    normalized = os.path.abspath(os.path.expanduser(str(directory)))
                    with self._config_lock:
                        config = config_module.load()
                        if config.get("saves") != normalized:
                            config["saves"] = normalized
                            config_module.save(config)
                except (OSError, ValueError, TypeError):
                    pass
            return 200, {"dir": directory, "worlds": worlds}
        if path == "/api/jobs/scan" and method == "POST":
            return 202, self.start_scan_job(body or {})
        if path.startswith("/api/jobs/") and method == "GET":
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                return 200, self.get_job(parts[2])
        if path.startswith("/api/jobs/") and method == "POST":
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "cancel":
                return 200, self.cancel_job(parts[2])
        if path == "/api/entry" and method == "GET":
            world = value("world")
            raw_pos = value("pos")
            if not world or not raw_pos:
                raise ApiError("world and pos are required")
            try:
                pos = [int(part.strip()) for part in str(raw_pos).split(",")]
            except ValueError:
                raise ApiError("pos must be x,y,z")
            if len(pos) != 3:
                raise ApiError("pos must be x,y,z")
            try:
                detail = services.entry_detail(world, value("dim") or "overworld", pos)
            except (WorldError, RegionError, NbtError, OSError, ValueError) as exc:
                raise ApiError(str(exc))
            if detail is None:
                raise ApiError("no tile entity at %s" % raw_pos, 404)
            return 200, detail
        if path == "/api/snapshots" and method == "GET":
            return 200, {"snapshots": self._list_snapshots()}
        if path == "/api/snapshots/import" and method == "POST":
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise ApiError("import body must be a JSON object")
            snapshot_path = body.get("path")
            if not snapshot_path:
                raise ApiError("path is required")
            snapshot_path = os.path.expanduser(str(snapshot_path))
            try:
                return 200, self._add_snapshot(snapshot_path)
            except (OSError, ValueError) as exc:
                raise ApiError(str(exc))
        if path == "/api/diff" and method == "POST":
            body = body or {}
            if not isinstance(body, dict):
                raise ApiError("diff body must be a JSON object")
            if not body.get("a") or not body.get("b"):
                raise ApiError("a and b snapshot paths are required")
            try:
                result = services.diff_files(
                    body.get("a"),
                    body.get("b"),
                    ignore=_as_list(body.get("ignore")),
                    machine=body.get("machine") or None,
                )
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise ApiError(str(exc))
            try:
                limit = int(body.get("limit") or 0)
            except (TypeError, ValueError):
                raise ApiError("limit must be an integer")
            if limit > 0:
                total = len(result.get("changes") or [])
                result["total_changes"] = total
                result["truncated"] = total > limit
                result["changes"] = (result.get("changes") or [])[:limit]
            return 200, result
        if path == "/api/export" and method == "POST":
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise ApiError("export body must be a JSON object")
            job_id = body.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise ApiError("job_id must be a non-empty string")
            job = self.get_job(job_id)
            if job.get("status") != "done" or not job.get("result"):
                raise ApiError("scan job is not finished yet")
            entries = job["result"].get("entries") or []
            fmt = str(body.get("format") or "csv").lower()
            raw_name = _clean_name(body.get("name") or "export")
            if fmt == "csv":
                directory = self._export_dir("csv")
                name = raw_name if raw_name.lower().endswith(".csv") else raw_name + ".csv"
                name = _unique_name(directory, name)
                target = os.path.join(directory, name)
                rows = services.export_csv(entries, target)
                return 200, {"file": name, "path": target, "format": "csv", "rows": rows}
            if fmt == "snapshot":
                if raw_name.lower().endswith(".json.gz"):
                    name = raw_name
                elif raw_name.lower().endswith(".json"):
                    name = raw_name
                else:
                    name = raw_name + ".json"
                directory = self._export_dir("snapshot")
                name = _unique_name(directory, name)
                target = os.path.join(directory, name)
                snapshot = Snapshot(
                    source=job["result"]["world"]["path"],
                    world_name=job["result"]["world"]["name"],
                    entries=entries,
                    meta={
                        "gui": True,
                        "world": job["result"]["world"]["name"],
                        "dims": job["result"].get("dims") or [],
                    },
                )
                snapshot.save(target)
                return 200, {
                    "file": name,
                    "path": target,
                    "format": "snapshot",
                    "summary": self._add_snapshot(target),
                }
            raise ApiError("unknown export format: %s" % fmt)
        if path == "/api/workspace/clean" and method == "POST":
            body = body or {}
            if not isinstance(body, dict):
                raise ApiError("clean body must be a JSON object")
            keep = body.get("keep", self.WORKSPACE_KEEP)
            try:
                keep = int(keep)
            except (TypeError, ValueError):
                raise ApiError("keep must be an integer")
            return 200, self._prune_workspace(keep)
        if path == "/api/download" and method == "GET":
            snapshot_path = value("path")
            if snapshot_path:
                target = services.normalize_path(snapshot_path)
                with self._snapshot_lock:
                    allowed = target in self._snapshots
                if not allowed and not self._is_export_path(target):
                    raise ApiError("file is not registered or inside an export directory", 403)
                if not os.path.isfile(target):
                    raise ApiError("file not found", 404)
                return 200, ("file", target)
            name = value("name")
            if not name or os.path.basename(name) != name:
                raise ApiError("invalid file name")
            target = os.path.join(self.workspace, name)
            if not os.path.isfile(target):
                raise ApiError("file not found", 404)
            return 200, ("file", target)
        if path == "/api/probe/find" and method == "GET":
            refresh = str(value("refresh") or "").lower() in ("1", "true", "yes")
            return 200, {"games": find_games(force=refresh)}
        if path == "/api/probe/connect" and method == "POST":
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise ApiError("connect body must be a JSON object")
            return 200, self.connect_live(body)
        if path == "/api/probe/state" and method == "GET":
            return 200, self.live_state()
        if path == "/api/probe/stop" and method == "POST":
            return 200, self.stop_live()
        if path == "/api/probe/save" and method == "POST":
            return 200, self.save_live_snapshot()
        if path == "/api/probe/chunk" and method == "POST":
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise ApiError("chunk body must be a JSON object")
            return 200, self.live_inspect("chunk", body)
        if path == "/api/probe/te" and method == "POST":
            if body is None:
                body = {}
            if not isinstance(body, dict):
                raise ApiError("te body must be a JSON object")
            return 200, self.live_inspect("te", body)
        raise ApiError("not found: %s" % path, 404)


def _clean_name(name: str) -> str:
    cleaned = os.path.basename(str(name or "")).strip()
    if not cleaned or cleaned in (".", ".."):
        cleaned = "export-%s" % time.strftime("%Y%m%d-%H%M%S-%f")
    if any(char in cleaned for char in '<>:"/\\|?*') or any(
        ord(char) < 32 for char in cleaned
    ):
        raise ApiError("file name contains invalid characters")
    return cleaned


def _unique_name(workspace: str, name: str) -> str:
    if not os.path.exists(os.path.join(workspace, name)):
        return name
    if name.lower().endswith(".json.gz"):
        stem, ext = name[:-8], ".json.gz"
    else:
        stem, ext = os.path.splitext(name)
    counter = 1
    while True:
        candidate = "%s-%d%s" % (stem, counter, ext)
        if not os.path.exists(os.path.join(workspace, candidate)):
            return candidate
        counter += 1


def _snapshot_meta(body: dict, result: dict) -> dict:
    return {
        "gui": True,
        "world": result["world"]["name"],
        "dims": result.get("dims") or [],
        "mte": body.get("mte") or None,
        "where": _as_list(body.get("where")),
    }


def _filter_list(value):
    result = []
    for item in _as_list(value):
        result.extend(part.strip() for part in str(item).split(",") if part.strip())
    return result


def _int_value(value, default, name, required=False):
    if value is None or value == "":
        if required:
            raise ApiError("%s is required" % name)
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("%s must be an integer" % name)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _cleanup_later(paths, delay=2.0):
    """Windows keeps agent files open briefly; retry the delete once after stop."""
    def cleanup():
        for path in paths:
            _unlink(path)

    timer = threading.Timer(delay, cleanup)
    timer.daemon = True
    timer.start()


class LiveSession:
    MAX_INTERVAL = 5000

    def __init__(self, server, pid, world=None, machine=None, dims=None,
                 max_machines=500, interval=1000, include_fallback=False,
                 where=None, until=None, changes=False, min_delta=0):
        self.server = server
        self.pid = pid
        self.world_name = ""
        self.dim_labels = {}
        if world:
            try:
                world_source = open_world(world)
                self.world_name = world_source.name
                folders = list(world_source.dims().keys())
                self.dim_labels = {
                    dimension_id_of(folder): folder
                    for folder in folders
                    if dimension_id_of(folder) is not None
                }
                if "overworld" in folders:
                    self.dim_labels[0] = "overworld"
            except (WorldError, OSError):
                pass
        self.include_fallback = include_fallback
        self.where = _filter_list(where)
        self.until = _filter_list(until)
        self.changes = changes
        self.min_delta = min_delta
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.status = "connecting"
        self.previous_status = None
        self.error = None
        self.tick = None
        self.entries = []
        self.changes_list = []
        self.alert = None
        self.samples = 0
        interval = max(100, min(self.MAX_INTERVAL, int(interval or 1000)))
        self.interval = interval
        self.out = os.path.join(
            server.workspace, "probe-%d-%d.jsonl" % (pid, time.time_ns())
        )
        self.stop_path = stop_flag_path(pid)
        clear_stop_flag(pid)
        args = "out=%s;stop=%s;interval=%d" % (self.out, self.stop_path, interval)
        machine_filter = _probe_filter(machine)
        if machine_filter:
            args += ";filter=" + machine_filter
        dim_ids = []
        for dim in _filter_list(dims):
            dim_id = dimension_id_of(dim)
            if dim_id is not None:
                dim_ids.append(dim_id)
        if dim_ids:
            args += ";dim=" + ",".join(str(value) for value in dim_ids)
        args += ";max=%d" % max(1, int(max_machines or 500))
        self._attach_error = None
        self.thread = None
        try:
            attach_agent(pid, args, java=config_module.get_value("java"))
        except AttachError as exc:
            self._attach_error = str(exc)
            self.status = "error"
            self.error = str(exc)
            _unlink(self.stop_path)
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _process(self, sample, rules, until_rules, previous):
        status = sample.get("status")
        if status == "error":
            with self.lock:
                self.previous_status = self.status
                self.status = "error"
                self.error = sample.get("message") or "live probe failed"
            return False
        if status == "no-server":
            with self.lock:
                self.previous_status = self.status
                self.status = "no-server"
            return True
        if status in ("done", "stopped"):
            with self.lock:
                self.previous_status = self.status
                self.status = "stopped"
            return False
        machines = sample.get("machines")
        if machines is None:
            return True
        entries = [
            machine_to_entry(machine, dim_labels=self.dim_labels) for machine in machines
        ]
        if not self.include_fallback:
            entries = [entry for entry in entries if entry.get("machine") != "GTMachine"]
        entries = filter_entries(entries, rules)
        changes = []
        if self.changes:
            changes = diff_entries(previous[0], entries)
            changes = filter_changes(changes, min_delta=self.min_delta)
            previous[0] = entries
        matched = (
            [entry for entry in entries if matches(entry, until_rules)]
            if until_rules
            else []
        )
        with self.lock:
            self.previous_status = self.status
            self.status = "running"
            self.tick = sample.get("tick")
            self.entries = entries
            self.changes_list = changes
            self.samples += 1
            self.alert = (
                {
                    "tick": self.tick,
                    "count": len(matched),
                    "machines": [
                        {
                            "dim": entry.get("dim"),
                            "pos": entry.get("pos"),
                            "machine": entry.get("machine"),
                        }
                        for entry in matched[:20]
                    ],
                }
                if matched
                else None
            )
        return True

    def _run(self):
        previous = [[]]
        try:
            rules = parse_filters(self.where)
            until_rules = parse_filters(self.until)
            offset = 0
            while not self.stop_event.is_set():
                if not process_alive(self.pid):
                    with self.lock:
                        self.previous_status = self.status
                        self.status = "lost"
                        self.error = "game process exited"
                    break
                try:
                    with open(self.out, "r", encoding="utf-8", errors="replace") as handle:
                        handle.seek(offset)
                        chunk = handle.read()
                        end = handle.tell()
                except OSError:
                    chunk = ""
                    end = offset
                consumed = 0
                for line in chunk.splitlines(keepends=True):
                    if not line.endswith(("\n", "\r")):
                        break
                    consumed += len(line)
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        sample = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if not self._process(sample, rules, until_rules, previous):
                        return
                offset = end - (len(chunk) - consumed)
                if self.stop_event.wait(0.2):
                    break
        except Exception as exc:  # noqa: BLE001 - shown to the UI
            with self.lock:
                self.previous_status = self.status
                self.error = str(exc)
                self.status = "error"
        finally:
            with self.lock:
                if self.status in ("connecting", "running"):
                    self.previous_status = self.status
                    self.status = "stopped"

    def stop(self):
        self.stop_event.set()
        request_stop(self.pid)
        if self.thread is not None:
            self.thread.join(timeout=3)
        with self.lock:
            self.previous_status = self.status
            self.status = "stopped"
        cleanup_paths = [self.out, self.out + ".log", self.stop_path]
        for path in cleanup_paths:
            _unlink(path)
        _cleanup_later(cleanup_paths)

    def state(self):
        with self.lock:
            return {
                "status": self.status,
                "previous_status": self.previous_status,
                "pid": self.pid,
                "world": self.world_name,
                "tick": self.tick,
                "entries": list(self.entries),
                "changes": list(self.changes_list),
                "alert": self.alert,
                "samples": self.samples,
                "error": self.error,
                "attach_error": getattr(self, "_attach_error", None),
                "changes_enabled": bool(self.changes),
                "min_delta": self.min_delta,
                "until": list(self.until),
                "where": list(self.where),
            }


class _GuiHandler(BaseHTTPRequestHandler):
    server_version = "gtnh-save-inspector-gui"
    gui = None

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_OPTIONS(self):
        self._send_json({"ok": True})

    def log_message(self, fmt, *args):  # keep the console quiet
        return

    def _authorized(self, query):
        supplied = (query.get("token") or [""])[0] or self.headers.get("X-GTNH-Token", "")
        return secrets.compare_digest(str(supplied), str(self.gui.token))

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError("invalid JSON body")

    def _host_allowed(self):
        if self.gui.host not in ("127.0.0.1", "localhost", "::1"):
            return True  # user explicitly opted into another bind address
        host = (self.headers.get("Host") or "").lower()
        port = self.gui.port
        return host in {
            "127.0.0.1:%d" % port,
            "localhost:%d" % port,
            "[::1]:%d" % port,
        }

    def _send_text(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, method):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if not self._host_allowed():
                self._send_json({"error": "invalid Host header"}, 403)
                return
            if parsed.path.startswith("/api/"):
                if not self._authorized(query):
                    self._send_json({"error": "forbidden"}, 403)
                    return
                body = self._read_json() if method == "POST" else None
                status, payload = self.gui.handle_api(method, parsed.path, query, body)
                if status == 200 and isinstance(payload, tuple) and payload[0] == "file":
                    self._send_file(payload[1])
                    return
                self._send_json(payload, status)
                return
            self._send_static(parsed.path, query)
        except ApiError as exc:
            self._send_json({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001 - API surface
            self._send_json({"error": str(exc)}, 500)

    def _send_json(self, payload, status=200):
        if status == 204:
            self.send_response(204)
            self.end_headers()
            return
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        try:
            handle = open(path, "rb")
        except OSError:
            self._send_json({"error": "file not found"}, 404)
            return
        try:
            size = os.fstat(handle.fileno()).st_size
        except OSError:
            handle.close()
            self._send_json({"error": "file not found"}, 404)
            return
        filename = os.path.basename(path)
        ascii_name = "".join(
            char if char.isascii() and char.isprintable() and char not in '"\\;' else "_"
            for char in filename
        ) or "download"
        encoded = urllib.parse.quote(filename)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (ascii_name, encoded),
        )
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with handle:
            shutil.copyfileobj(handle, self.wfile)

    ALLOWED_STATIC = {"index.html", "app.js", "style.css", "i18n.js"}

    def _send_static(self, path, query):
        if path in ("/", "/index.html"):
            supplied = (query.get("token") or [""])[0]
            if not secrets.compare_digest(str(supplied), str(self.gui.token)):
                self._send_text(
                    "gtnh-save-inspector: open the URL printed by 'gtnh-inspect gui' "
                    "(missing or invalid token)",
                    403,
                )
                return
            path = "/index.html"
        name = urllib.parse.unquote(path.lstrip("/"))
        if name.startswith("static/"):
            name = name[len("static/"):]
        # Strict whitelist: path separators/backslashes/drive letters can never escape.
        if name == "index.html" and path != "/index.html":
            supplied = (query.get("token") or [""])[0]
            if not secrets.compare_digest(str(supplied), str(self.gui.token)):
                self._send_text("gtnh-save-inspector: invalid token", 403)
                return
        if name not in self.ALLOWED_STATIC:
            if path == "/favicon.ico":
                self._send_json({}, 204)
                return
            self._send_json({"error": "not found"}, 404)
            return
        target = STATIC_DIR / name
        if not target.is_file():
            if path == "/favicon.ico":
                self._send_json({}, 204)
                return
            self._send_json({"error": "not found"}, 404)
            return
        data = target.read_bytes()
        content_type = CONTENT_TYPES.get(
            target.suffix.lower(), mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _make_handler(gui):
    return type("GuiHandler", (_GuiHandler,), {"gui": gui})


def run_browser(server: GuiServer, open_browser: bool = True):
    """Start the server and block until Ctrl+C (browser fallback)."""
    import webbrowser

    server.start()
    try:
        print("gtnh-save-inspector GUI: %s" % server.url, flush=True)
        if open_browser:
            webbrowser.open(server.url)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopping GUI server")
    finally:
        server.stop()


def run_native(server: GuiServer) -> bool:
    """Start the server and open a pywebview window; returns False if the window fails."""
    try:
        import webview
    except Exception:  # noqa: BLE001 - optional dependency
        return False
    try:
        server.start()
        print("gtnh-save-inspector GUI: %s" % server.url, flush=True)
        webview.create_window(
            "gtnh-save-inspector",
            server.url,
            width=1400,
            height=900,
            min_size=(1000, 650),
        )
        webview.start()
    except Exception as exc:  # noqa: BLE001 - WebView2/runtime failures
        import sys

        print("native window failed: %r" % exc, file=sys.stderr, flush=True)
        return False
    finally:
        try:
            server.stop()
        except Exception:  # noqa: BLE001 - already stopped
            pass
    return True
