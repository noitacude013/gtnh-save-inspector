"""Command line interface for gtnh-save-inspector."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from .. import __version__
from ..core import nbt
from ..core.nbt import NbtError
from ..core.region import RegionError
from ..core.snapshot import (
    SNAPSHOT_FORMAT,
    Snapshot,
    collect,
    diff as diff_snapshots,
    filter_diff_changes,
    load as load_snapshot,
)
from ..core.world import (
    ScanStats,
    WorldError,
    discover_worlds,
    open_world,
    read_tile_entity,
)
from .. import config as config_module
from ..dimensions import dimension_id_of, resolve_dim
from ..export import write_csv
from ..extractors import EXTRACTORS, find_extractor
from ..filters import filter_entries, matches, parse_filters, resolve_field
from ..formatting import format_entry, format_table_line

DEFAULT_SAVES = os.path.join(os.getcwd(), "saves")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def parse_pos(text: str):
    parts = text.replace(" ", "").split(",")
    if len(parts) != 3:
        raise ValueError("position must be 'x,y,z' (got %r)" % text)
    return tuple(int(part) for part in parts)


def _parse_field_selection(value):
    if not value:
        return None
    names = {part.strip() for part in value.split(",") if part.strip()}
    return names or None


def _select_fields(entry, names):
    if not names:
        return entry
    fields = {
        key: value for key, value in (entry.get("fields") or {}).items() if key in names
    }
    selected = dict(entry)
    selected["fields"] = fields
    return selected


def dims_of(world, requested):
    folders = list(world.dims().keys())
    if requested:
        return [resolve_dim(name, folders) for name in requested]
    dims = world.dims()
    ordered = []
    if "overworld" in dims:
        ordered.append("overworld")
    ordered.extend(name for name in dims if name != "overworld")
    return ordered


def cmd_worlds(args) -> int:
    directory = args.dir or config_module.get_value("saves") or DEFAULT_SAVES
    worlds = discover_worlds(directory)
    if not worlds:
        print("no worlds found below %s" % directory, file=sys.stderr)
        return 2
    payload = []
    for world in worlds:
        info = world.level_info()
        dims = world.dims()
        payload.append(
            {
                "path": world.path,
                "name": world.name,
                "kind": world.kind,
                "level_name": info.get("LevelName"),
                "version": info.get("version", {}).get("Name")
                if isinstance(info.get("version"), dict)
                else None,
                "last_played": info.get("LastPlayed"),
                "dims": sorted(dims),
            }
        )
    if args.json:
        print(_json_text(args, payload))
        return 0
    for item in payload:
        print("%s  [%s]" % (item["name"], item["kind"]))
        print("  path        : %s" % item["path"])
        print("  level name  : %s" % item["level_name"])
        print("  version     : %s" % item["version"])
        print("  dimensions  : %s" % ", ".join(item["dims"]))
    return 0


def cmd_show(args) -> int:
    pos = parse_pos(args.pos)
    world = open_world(args.world)
    dims = dims_of(world, args.dim)
    for dim in dims:
        te = read_tile_entity(world, dim, pos)
        if te is None:
            continue
        extractor = find_extractor(te)
        fields = extractor.extract(te) if extractor else {"raw": nbt.squash(te)}
        entry = {
            "dim": dim,
            "chunk": [pos[0] >> 4, pos[2] >> 4],
            "pos": list(pos),
            "machine": extractor.name if extractor else "unknown",
            "fields": fields,
        }
        entry = _select_fields(entry, _parse_field_selection(getattr(args, "fields", None)))
        if args.json:
            print(_json_text(args, entry))
        else:
            print(format_entry(entry, world_name=world.name))
        return 0
    print("no tile entity at %s in %s" % (list(pos), ", ".join(dims)), file=sys.stderr)
    return 2


def cmd_scan(args) -> int:
    world = open_world(args.world)
    dims = dims_of(world, args.dim)
    rules = parse_filters(getattr(args, "where", None))
    include_fallback = bool(getattr(args, "all", False)) or (
        (args.mte or "").lower() == "gtmachine"
    )
    stats = ScanStats() if getattr(args, "stats", False) else None
    needle = None
    if getattr(args, "fast", False):
        if include_fallback:
            # hatches/buses have no mMaxProgresstime, but every GT machine has mID
            needle = b"mID"
        elif (args.mte or "").lower() == "mteeyeofharmony":
            needle = b"eyeOfHarmonyOutput"
        else:
            needle = b"mMaxProgresstime"
    sort_field = getattr(args, "sort", None)
    snapshot = collect(
        world,
        dims,
        find_extractor,
        machine_filter=args.mte,
        limit=None if sort_field else args.limit,
        needle=needle,
        jobs=getattr(args, "jobs", 1),
        filter_rules=rules,
        include_fallback=include_fallback,
        stats=stats,
    )
    if sort_field:
        if not any(
            resolve_field(entry, sort_field) is not None for entry in snapshot.entries
        ):
            print(
                "error: no machine has field %r, cannot sort" % sort_field,
                file=sys.stderr,
            )
            return 2

        def sort_key(entry):
            value = resolve_field(entry, sort_field)
            if isinstance(value, (int, float)):
                return (0, -value)
            return (1, str(value))

        snapshot.entries.sort(key=sort_key)
    cap = getattr(args, "top", None)
    if cap is None and sort_field:
        cap = args.limit
    if cap:
        snapshot.entries = snapshot.entries[:cap]
    snapshot.meta = _parse_meta(getattr(args, "meta", None))
    if getattr(args, "csv", None):
        rows = write_csv(args.csv, snapshot.entries)
        print(
            "csv written to %s (%d rows)" % (args.csv, rows),
            file=sys.stderr if args.json else sys.stdout,
        )
    if args.out:
        out_path = args.out
        compress = bool(getattr(args, "gzip", False))
        if compress and not out_path.lower().endswith(".gz"):
            out_path += ".gz"
        snapshot.save(out_path, compress=compress, compact=bool(getattr(args, "compact", False)))
        args.out = out_path
    if args.json:
        payload = snapshot.to_dict(compact=bool(getattr(args, "compact", False)))
        if stats is not None:
            payload["stats"] = stats.to_dict()
        field_names = _parse_field_selection(getattr(args, "fields", None))
        if field_names:
            payload["entries"] = [
                _select_fields(entry, field_names) for entry in payload["entries"]
            ]
        print(_json_text(args, payload))
        return 0
    field_names = _parse_field_selection(getattr(args, "fields", None))
    if not args.quiet:
        if args.detail:
            for entry in snapshot.entries:
                print(format_entry(_select_fields(entry, field_names), world_name=world.name))
                print()
        else:
            for entry in snapshot.entries:
                print(format_table_line(_select_fields(entry, field_names)))
        print(
            "scanned %s: %d machine(s) in dims: %s"
            % (world.name, len(snapshot.entries), ", ".join(dims))
        )
    if stats is not None:
        print(
            "scan stats: regions=%d chunks=%d skipped=%d parsed=%d parse_errors=%d tile_entities=%d"
            % (
                stats.regions,
                stats.chunks,
                stats.chunks_skipped,
                stats.chunks_parsed,
                stats.parse_errors,
                stats.tile_entities,
            )
        )
    if args.out:
        print("snapshot written to %s" % args.out)
    return 0


def cmd_diff(args) -> int:
    first = load_snapshot(args.a)
    second = load_snapshot(args.b)
    result = diff_snapshots(first, second)
    changes = result["changes"]
    if args.machine:
        wanted = args.machine.lower()
        changes = [c for c in changes if (c.get("machine") or "").lower() == wanted]
    ignored = set()
    for item in getattr(args, "ignore", None) or []:
        ignored.update(part.strip() for part in item.split(",") if part.strip())
    if ignored:
        changes = filter_diff_changes(changes, ignored)
    if args.json:
        print(_json_text(args, dict(result, changes=changes)))
        return 0
    print("A: %s (%s)" % (result["a"]["source"], result["a"]["captured"]))
    print("B: %s (%s)" % (result["b"]["source"], result["b"]["captured"]))
    meta_diff = result.get("meta_diff") or {}
    if meta_diff:
        print("metadata differs:")
        for key in sorted(meta_diff):
            print("  %s: %r -> %r" % (key, meta_diff[key]["a"], meta_diff[key]["b"]))
    if not changes:
        if ignored:
            print("\nno differences (after --ignore)")
        else:
            print("\nno differences")
        return 0
    added = sum(1 for c in changes if c["status"] == "added")
    removed = sum(1 for c in changes if c["status"] == "removed")
    changed = sum(1 for c in changes if c["status"] == "changed")
    print("\n%d change(s): %d added, %d removed, %d changed" % (len(changes), added, removed, changed))
    shown = 0
    for change in changes:
        if args.limit is not None and shown >= args.limit:
            print("\n... (%d more changes, raise --limit to see them)" % (len(changes) - shown))
            break
        dim = change.get("dim")
        pos = tuple(change.get("pos") or ())
        if change["status"] in ("added", "removed"):
            print("\n[%s] %s pos=%s %s" % (change["status"], dim, pos, change.get("machine", "")))
            shown += 1
            continue
        print("\n[changed] %s pos=%s %s" % (dim, pos, change.get("machine") or ""))
        for name, values in change["fields"].items():
            delta = values.get("delta")
            suffix = "  (%+d)" % delta if isinstance(delta, int) else ""
            print("  %-14s : %s -> %s%s" % (name, values["before"], values["after"], suffix))
        shown += 1
    return 0


def cmd_dump(args) -> int:
    pos = parse_pos(args.pos)
    world = open_world(args.world)
    dims = dims_of(world, args.dim)
    for dim in dims:
        te = read_tile_entity(world, dim, pos)
        if te is None:
            continue
        payload = {"dim": dim, "pos": list(pos), "nbt": nbt.squash(te, max_items=args.max_items)}
        if args.json:
            print(_json_text(args, payload))
        else:
            print("dim=%s pos=%s" % (dim, list(pos)))
            print(_json_text(args, payload["nbt"]))
        return 0
    print("no tile entity at %s in %s" % (list(pos), ", ".join(dims)), file=sys.stderr)
    return 2


def cmd_extractors(args) -> int:
    if getattr(args, "json", False):
        print(
            _json_text(
                args,
                [
                    {
                        "name": extractor.name,
                        "priority": extractor.priority,
                        "description": extractor.description,
                    }
                    for extractor in EXTRACTORS
                ],
            )
        )
        return 0
    for extractor in EXTRACTORS:
        print("%-20s priority=%-3d %s" % (extractor.name, extractor.priority, extractor.description))
    return 0


# --------------------------------------------------------------------------- #
# argument parsing
# --------------------------------------------------------------------------- #
class _JsonArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that emits JSON usage errors when the caller asked for JSON."""

    def error(self, message):
        argv = getattr(self, "_argv", sys.argv[1:])
        if any(flag in argv for flag in ("--json", "--jsonl")):
            print(json.dumps({"error": message, "code": 2}, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        super().error(message)


def _json_text(args, payload):
    indent = None if getattr(args, "compact_json", False) else 1
    return json.dumps(payload, indent=indent, ensure_ascii=False, default=str)


def _error(args, message, code=2):
    if getattr(args, "json", False) or getattr(args, "jsonl", False):
        print(json.dumps({"error": str(message), "code": code}, ensure_ascii=False), file=sys.stderr)
    else:
        print("error: %s" % message, file=sys.stderr)
    return code


def _parse_meta(pairs):
    meta = {}
    for item in pairs or []:
        if "=" in item:
            key, value = item.split("=", 1)
            meta[key.strip()] = value.strip()
    return meta


def _wait_for_mode(out, mode, timeout):
    from ..live import read_samples

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            samples = read_samples(out)
        except (FileNotFoundError, OSError):
            samples = []
        for sample in samples:
            if sample.get("mode") == mode or sample.get("status") in ("error", "no-server"):
                return sample
        time.sleep(0.2)
    return None


def _probe_java_filter(machine):
    """Translate a --machine value into a Java simple class name filter."""
    if not machine:
        return None
    if machine.lower() in ("all", "*", "gtmultiblock"):
        return None
    return machine


def _probe_output_path(pid: int, out):
    if out:
        path = Path(out)
    else:
        # Unique per invocation: a stale agent from an earlier attach must never collide
        # with this run's output file (Windows keeps the old handle open for a while).
        path = Path(tempfile.gettempdir()) / "gtnh-save-inspector" / (
            "probe-%d-%d.jsonl" % (pid, time.time_ns())
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _dim_label_map(world_path):
    if not world_path:
        return {}, ""
    world = open_world(world_path)
    folders = list(world.dims().keys())
    labels = {}
    for folder in folders:
        dimension_id = dimension_id_of(folder)
        if dimension_id is not None:
            labels[dimension_id] = folder
    if "overworld" in folders:
        labels[0] = "overworld"
    return labels, world.name


def _save_live_snapshot(path, entries, pid, world_name):
    if not path:
        return
    snapshot = Snapshot(source="live:%d" % pid, world_name=world_name or "live", entries=list(entries))
    snapshot.save(path)
    print("live snapshot written to %s" % path, file=sys.stderr)


def _sample_entries(sample, dim_labels=None, rules=None, include_fallback=False):
    from ..live import machine_to_entry

    entries = [
        machine_to_entry(machine, dim_labels=dim_labels) for machine in sample.get("machines") or []
    ]
    if not include_fallback:
        entries = [entry for entry in entries if entry.get("machine") != "GTMachine"]
    return filter_entries(entries, rules)


def _print_live_sample(sample: dict, args, entries) -> None:
    if getattr(args, "jsonl", False):
        print(
            json.dumps(
                {"tick": sample.get("tick"), "machines": entries},
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )
        return
    if getattr(args, "json", False):
        print(_json_text(args, {"tick": sample.get("tick"), "machines": entries}))
        return
    print("tick=%s  machines=%d" % (sample.get("tick"), len(entries)))
    for entry in entries:
        if getattr(args, "detail", False):
            print(format_entry(entry))
            print()
        else:
            print(format_table_line(entry))


def cmd_probe_dump(args) -> int:
    from ..live import (
        AttachError,
        attach_agent,
        clear_stop_flag,
        read_samples,
        request_stop,
        stop_flag_path,
    )

    pid = args.pid
    dim_labels, world_name = _dim_label_map(args.world)
    out = _probe_output_path(pid, args.out)
    clear_stop_flag(pid)
    agent_args = "out=%s;stop=%s;interval=500" % (out, stop_flag_path(pid))
    machine_filter = _probe_java_filter(args.machine)
    if machine_filter:
        agent_args += ";filter=" + machine_filter
    if args.dim:
        agent_args += ";dim=" + ",".join(str(d) for d in args.dim)
    if args.max:
        agent_args += ";max=%d" % args.max
    try:
        output = attach_agent(pid, agent_args, java=args.java)
    except AttachError as exc:
        return _error(args, str(exc))
    if output:
        print(output, file=sys.stderr)
    deadline = time.time() + args.timeout
    machines = []
    while time.time() < deadline:
        try:
            samples = read_samples(out)
        except (FileNotFoundError, OSError):
            samples = []
        machines = []
        for sample in samples:
            if "machines" in sample:
                machines = sample["machines"]
                last_tick = sample.get("tick")
        if machines:
            break
        time.sleep(0.2)
    request_stop(pid)
    if not machines:
        print(
            "no machines returned within %.0fs (probe file: %s)" % (args.timeout, out),
            file=sys.stderr,
        )
        return 1
    entries = _sample_entries(
        {"machines": machines},
        dim_labels,
        parse_filters(args.where),
        include_fallback=bool(getattr(args, "all", False)),
    )
    field_names = _parse_field_selection(getattr(args, "fields", None))
    if field_names:
        entries = [_select_fields(entry, field_names) for entry in entries]
    if not entries:
        print(
            "machines returned but all were filtered out "
            "(use --all to include fallback machines; check --where/--fields)",
            file=sys.stderr,
        )
        return 1
    _save_live_snapshot(args.save, entries, pid, world_name)
    if args.json:
        print(_json_text(args, entries))
        return 0
    print("live sample from pid %d (%d machine(s))" % (pid, len(entries)))
    for entry in entries:
        if args.detail:
            print(format_entry(entry))
            print()
        else:
            print(format_table_line(entry))
    return 0


def cmd_probe_watch(args) -> int:
    from ..live import (
        AttachError,
        attach_agent,
        clear_stop_flag,
        follow_samples,
        machine_to_entry,
        request_stop,
        stop_flag_path,
    )

    pid = args.pid
    dim_labels, world_name = _dim_label_map(args.world)
    out = _probe_output_path(pid, args.out)
    clear_stop_flag(pid)
    agent_args = "out=%s;stop=%s;interval=%d" % (out, stop_flag_path(pid), max(100, args.interval))
    machine_filter = _probe_java_filter(args.machine)
    if machine_filter:
        agent_args += ";filter=" + machine_filter
    if args.dim:
        agent_args += ";dim=" + ",".join(str(d) for d in args.dim)
    if args.max:
        agent_args += ";max=%d" % args.max
    if args.samples:
        agent_args += ";samples=%d" % args.samples
    try:
        attach_agent(pid, agent_args, java=args.java)
    except AttachError as exc:
        return _error(args, str(exc))
    print("watching pid %d (output: %s) - Ctrl+C to stop" % (pid, out), file=sys.stderr)
    rules = parse_filters(args.where)
    field_names = _parse_field_selection(getattr(args, "fields", None))
    min_delta = int(getattr(args, "min_delta", 0) or 0)
    until_rules = parse_filters(getattr(args, "until", None))
    previous_entries = []
    try:
        for sample in follow_samples(
            out, max_machine_samples=args.samples, timeout_s=args.timeout
        ):
            if sample.get("status"):
                print("[probe] %s" % sample["status"], file=sys.stderr)
                continue
            entries = _sample_entries(
                sample, dim_labels, rules, include_fallback=bool(getattr(args, "all", False))
            )
            if until_rules:
                matched = [entry for entry in entries if matches(entry, until_rules)]
                if matched:
                    if args.save:
                        _save_live_snapshot(args.save, matched, pid, world_name)
                    print(
                        "[probe] --until condition met (%d machine(s))" % len(matched),
                        file=sys.stderr,
                    )
                    break
            if field_names:
                entries = [_select_fields(entry, field_names) for entry in entries]
            _save_live_snapshot(args.save, entries, pid, world_name)
            if args.changes:
                from ..live.changes import diff_entries, filter_changes, format_changes

                changes = diff_entries(previous_entries, entries)
                previous_entries = entries
                changes = filter_changes(changes, min_delta=min_delta, fields=field_names)
                if not changes:
                    continue
                if getattr(args, "jsonl", False):
                    print(
                        json.dumps(
                            {"tick": sample.get("tick"), "changes": changes},
                            ensure_ascii=False,
                            default=str,
                        ),
                        flush=True,
                    )
                    continue
                if args.json:
                    print(_json_text(args, {"tick": sample.get("tick"), "changes": changes}))
                    continue
                print("tick=%s  changes=%d" % (sample.get("tick"), len(changes)))
                for line in format_changes(changes):
                    print(line)
                print()
                continue
            _print_live_sample(sample, args, entries)
            previous_entries = entries
            print()
    except KeyboardInterrupt:
        print("\nstopping...", file=sys.stderr)
    finally:
        request_stop(pid)
    return 0


def cmd_probe_worlds(args) -> int:
    from ..live import (
        AttachError,
        attach_agent,
        clear_stop_flag,
        read_samples,
        request_stop,
        stop_flag_path,
    )

    pid = args.pid
    out = _probe_output_path(pid, args.out)
    clear_stop_flag(pid)
    agent_args = "out=%s;stop=%s;mode=worlds" % (out, stop_flag_path(pid))
    try:
        attach_agent(pid, agent_args, java=args.java)
    except AttachError as exc:
        return _error(args, str(exc))
    deadline = time.time() + args.timeout
    summary = None
    while time.time() < deadline:
        try:
            samples = read_samples(out)
        except (FileNotFoundError, OSError):
            samples = []
        for sample in samples:
            if sample.get("mode") == "worlds":
                summary = sample
                break
        if summary:
            break
        time.sleep(0.2)
    request_stop(pid)
    if not summary:
        print("no world summary returned within %.0fs (probe file: %s)" % (args.timeout, out), file=sys.stderr)
        return 1
    if args.json:
        print(_json_text(args, summary))
        return 0
    worlds = sorted(summary.get("worlds") or [], key=lambda item: item.get("dim", 0))
    print("%-8s %-8s %-8s %s" % ("dim", "TEs", "GT TEs", "top machine types"))
    for world in worlds:
        classes = world.get("classes") or {}
        top = sorted(classes.items(), key=lambda item: -item[1])[:6]
        top_text = ", ".join("%s x%d" % (name, count) for name, count in top)
        print("%-8s %-8d %-8d %s" % (world.get("dim"), world.get("tes"), world.get("gtTes"), top_text))
    return 0


def cmd_probe_chunk(args) -> int:
    from ..live import (
        AttachError,
        attach_agent,
        clear_stop_flag,
        read_samples,
        request_stop,
        stop_flag_path,
    )

    pid = args.pid
    out = _probe_output_path(pid, None)
    clear_stop_flag(pid)
    agent_args = "out=%s;stop=%s;mode=chunk;dim=%d;x=%d;z=%d" % (
        out,
        stop_flag_path(pid),
        args.dim,
        args.x,
        args.z,
    )
    try:
        attach_agent(pid, agent_args, java=args.java)
    except AttachError as exc:
        return _error(args, str(exc))
    summary = _wait_for_mode(out, "chunk", args.timeout)
    request_stop(pid)
    if summary is None:
        print("no chunk information returned within %.0fs" % args.timeout, file=sys.stderr)
        return 1
    if summary.get("status") == "error":
        print("error: %s" % summary.get("message"), file=sys.stderr)
        return 1
    if summary.get("status") == "no-server":
        print("game is on the title screen (no server); load a world first", file=sys.stderr)
        return 1
    if summary.get("status") == "no-server":
        print("game is on the title screen (no server); load a world first", file=sys.stderr)
        return 1
    if args.json:
        print(_json_text(args, summary))
        return 0
    print(
        "dim=%s block=(%s,%s) chunk=(%s,%s) isModified=%s hasEntities=%s tileEntities=%s"
        % (
            summary.get("dim"),
            summary.get("blockX"),
            summary.get("blockZ"),
            summary.get("chunkX"),
            summary.get("chunkZ"),
            summary.get("isModified"),
            summary.get("hasEntities"),
            summary.get("tileEntities"),
        )
    )
    return 0


def cmd_probe_te(args) -> int:
    from ..live import (
        AttachError,
        attach_agent,
        clear_stop_flag,
        read_samples,
        request_stop,
        stop_flag_path,
    )

    pid = args.pid
    pos = args.pos
    parts = str(pos).split(",")
    try:
        positions = [int(part.strip()) for part in parts]
    except ValueError:
        positions = []
    if len(positions) != 3:
        print("error: --pos must be x,y,z", file=sys.stderr)
        return 2
    pos = ",".join(str(value) for value in positions)
    out = _probe_output_path(pid, None)
    clear_stop_flag(pid)
    agent_args = "out=%s;stop=%s;mode=te;dim=%d;pos=%s" % (
        out,
        stop_flag_path(pid),
        args.dim,
        pos,
    )
    try:
        attach_agent(pid, agent_args, java=args.java)
    except AttachError as exc:
        return _error(args, str(exc))
    summary = _wait_for_mode(out, "te", args.timeout)
    request_stop(pid)
    if summary is None:
        print("no tile entity information returned within %.0fs" % args.timeout, file=sys.stderr)
        return 1
    if summary.get("status") == "error":
        print("error: %s" % summary.get("message"), file=sys.stderr)
        return 1
    if args.json:
        print(_json_text(args, summary))
        return 0
    print(
        "dim=%s pos=(%s,%s,%s) te=%s mte=%s chunkModified=%s"
        % (
            summary.get("dim"),
            summary.get("x"),
            summary.get("y"),
            summary.get("z"),
            summary.get("teClass"),
            summary.get("mteClass"),
            summary.get("chunkModified"),
        )
    )
    inventory = summary.get("inventory")
    if isinstance(inventory, dict):
        print(
            "inventory: slots=%s used=%s items=%s"
            % (inventory.get("slots"), inventory.get("slotsUsed"), inventory.get("itemCount"))
        )
        for item in (inventory.get("items") or [])[:8]:
            print("  %-32s x%s" % (item.get("name"), item.get("count")))
    for key in sorted((summary.get("fields") or {})):
        print("  %-28s %s" % (key, (summary.get("fields") or {})[key]))
    return 0


def cmd_probe_find(args) -> int:
    from ..live.findgame import find_games

    games = find_games()
    if getattr(args, "json", False):
        print(_json_text(args, {"found": bool(games), "games": games}))
        return 0 if games else 1
    if not games:
        print("no running GTNH game process found", file=sys.stderr)
        return 1
    for game in games:
        print(
            "pid=%d mem=%dMB java=%s instance=%s"
            % (game["pid"], game["memoryMB"], game["java"], game["instance"])
        )
    return 0


def cmd_gui(args) -> int:
    from ..gui.server import GuiServer, run_browser, run_native

    if args.host in ("0.0.0.0", "::"):
        print(
            "warning: GUI is bound to %s and is reachable from other machines; "
            "the token is required for API access" % args.host,
            file=sys.stderr,
        )
    elif args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "warning: GUI is bound to %s; only use this on a trusted network" % args.host,
            file=sys.stderr,
        )
    try:
        server = GuiServer(host=args.host, port=args.port)
    except (OSError, OverflowError, ValueError) as exc:
        print("error: cannot start GUI server: %s" % exc, file=sys.stderr)
        return 2
    if args.browser:
        run_browser(server, open_browser=not args.no_open)
        return 0
    if run_native(server):
        return 0
    print(
        "pywebview is unavailable; falling back to the browser "
        "(install with: pip install '.[gui]')",
        file=sys.stderr,
    )
    if getattr(server, "_closed", False):
        try:
            server = GuiServer(host=args.host, port=args.port)
        except (OSError, OverflowError, ValueError) as exc:
            print("error: cannot start GUI server: %s" % exc, file=sys.stderr)
            return 2
    run_browser(server, open_browser=not args.no_open)
    return 0


def cmd_capabilities(args) -> int:
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    payload = {
        "tool": "gtnh-save-inspector",
        "version": __version__,
        "snapshot_format": SNAPSHOT_FORMAT,
        "exit_codes": {
            "0": "success",
            "1": "no result, no running game, or a watch condition/limit was not met",
            "2": "usage error or environment error (missing world/pid, attach failure, ...)",
        },
        "commands": {
            name: _describe_command(command) for name, command in sub.choices.items()
        },
    }
    if getattr(args, "json", False):
        print(_json_text(args, payload))
        return 0
    print("gtnh-save-inspector %s" % __version__)
    for name in sorted(payload["commands"]):
        print("  %-12s %s" % (name, payload["commands"][name].get("description", "")))


def _describe_command(parser) -> dict:
    options = []
    subcommands = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, command in action.choices.items():
                subcommands[name] = _describe_command(command)
            continue
        if not action.option_strings or action.help == argparse.SUPPRESS:
            continue
        default = action.default
        if not (default is None or isinstance(default, (str, int, float, bool))):
            default = str(default)
        options.append(
            {
                "flags": list(action.option_strings),
                "help": action.help or "",
                "required": bool(action.required),
                "default": default,
                "choices": list(action.choices) if action.choices else None,
            }
        )
    result = {"description": parser.description or "", "options": options}
    if subcommands:
        result["subcommands"] = subcommands
    return result


def cmd_probe_stop(args) -> int:
    from ..live import request_stop

    path = request_stop(args.pid)
    print("stop requested for pid %d (%s)" % (args.pid, path))
    return 0


def cmd_config(args) -> int:
    action = args.action
    if action == "path":
        print(config_module.config_path())
    elif action in ("show", "list"):
        print(_json_text(args, config_module.load()))
    elif action == "set":
        if not args.key or args.value is None:
            print("error: config set needs KEY VALUE", file=sys.stderr)
            return 2
        path = config_module.set_value(args.key, args.value)
        print("saved %s to %s" % (args.key, path))
    return 0


def _add_compact_json(parser) -> None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                if not any(
                    "--compact-json" in option.option_strings for option in child._actions
                ):
                    child.add_argument(
                        "--compact-json",
                        action="store_true",
                        default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS,
                    )
                _add_compact_json(child)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="gtnh-inspect",
        description="Read-only inspector for GTNH (1.7.10) world saves and machines.",
    )
    parser.add_argument("--version", action="version", version="gtnh-save-inspector " + __version__)
    parser.add_argument("--compact-json", action="store_true",
                        help="emit JSON on one line (default: indent=1)")
    parser.add_argument(
        "--plugin",
        action="append",
        default=[],
        help="load an extractor plugin (.py); repeatable; must precede the subcommand",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    worlds = subparsers.add_parser("worlds", help="list world saves below a path")
    worlds.add_argument("--dir", help="saves folder, world folder or instance (default: config/./saves)")
    worlds.add_argument("--json", action="store_true")
    worlds.set_defaults(func=cmd_worlds)

    show = subparsers.add_parser("show", help="show one machine at a block position")
    show.add_argument("--world", help="world save directory or backup .zip")
    show.add_argument("--dim", action="append", help="dimension name (repeatable, default: all)")
    show.add_argument("--pos", required=True, help="block position x,y,z")
    show.add_argument("--json", action="store_true")
    show.add_argument("--fields", help="comma separated field names to display")
    show.set_defaults(func=cmd_show)

    scan = subparsers.add_parser("scan", help="scan a world (or backup) for known machines")
    scan.add_argument("--world")
    scan.add_argument("--dim", action="append", help="dimension name (repeatable, default: all)")
    scan.add_argument("--mte", help="only machines from this extractor, e.g. MTEEyeOfHarmony")
    scan.add_argument("--limit", type=int, help="stop after N matches")
    scan.add_argument("--out", help="write a JSON snapshot to this path")
    scan.add_argument("--detail", action="store_true", help="print a full block per machine")
    scan.add_argument(
        "--fast",
        action="store_true",
        help="skip chunks without multiblock fields before parsing NBT (much faster on big saves)",
    )
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--jobs", type=int, default=1, help="parse N region files in parallel (default: 1)")
    scan.add_argument("--where", action="append", help="field filter, e.g. progress>0 (repeatable, AND)")
    scan.add_argument("--quiet", action="store_true")
    scan.add_argument("--all", action="store_true",
                      help="include every GT machine (hatches/buses) via the GTMachine fallback")
    scan.add_argument("--sort", help="sort machines by this field, descending")
    scan.add_argument("--top", type=int, help="keep only the first N machines after sorting")
    scan.add_argument("--gzip", action="store_true", help="gzip the --out snapshot")
    scan.add_argument("--fields", help="comma separated field names to display")
    scan.add_argument("--csv", help="write a CSV export to this path")
    scan.add_argument("--meta", action="append", help="snapshot metadata KEY=VALUE (repeatable)")
    scan.add_argument("--compact", action="store_true", help="omit null fields from snapshots/JSON")
    scan.add_argument("--stats", action="store_true", help="print chunk/parse scan statistics")
    scan.set_defaults(func=cmd_scan)

    diff = subparsers.add_parser("diff", help="compare two snapshots")
    diff.add_argument("--a", required=True, help="older snapshot JSON")
    diff.add_argument("--b", required=True, help="newer snapshot JSON")
    diff.add_argument("--machine", help="only compare this extractor/machine type")
    diff.add_argument("--ignore", action="append",
                      help="ignore changed fields (comma separated, repeatable)")
    diff.add_argument("--limit", type=int, default=30, help="max changes to print (default: 30)")
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(func=cmd_diff)

    dump = subparsers.add_parser("dump", help="dump the raw NBT of one tile entity")
    dump.add_argument("--world")
    dump.add_argument("--dim", action="append")
    dump.add_argument("--pos", required=True)
    dump.add_argument("--json", action="store_true")
    dump.add_argument("--max-items", type=int, default=64, help="truncate long arrays to this many entries")
    dump.set_defaults(func=cmd_dump)

    config_parser = subparsers.add_parser("config", help="show or change default settings")
    config_sub = config_parser.add_subparsers(dest="action", required=True)
    config_sub.add_parser("path", help="print the config file path")
    config_sub.add_parser("show", help="print the current config")
    config_sub.add_parser("list", help="print the current config")
    config_set = config_sub.add_parser("set", help="set a config value (world, saves, pid, java)")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_parser.set_defaults(func=cmd_config)

    gui = subparsers.add_parser("gui", help="open the local web GUI (browser or pywebview)")
    gui.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    gui.add_argument("--port", type=int, default=0, help="port (default: random free port)")
    gui.add_argument("--browser", action="store_true", help="force the browser window")
    gui.add_argument("--no-open", action="store_true", help="do not open a browser automatically")
    gui.set_defaults(func=cmd_gui)

    capabilities = subparsers.add_parser(
        "capabilities", help="machine-readable command/option/exit-code description"
    )
    capabilities.add_argument("--json", action="store_true")
    capabilities.set_defaults(func=cmd_capabilities)

    extractors = subparsers.add_parser("extractors", help="list available machine extractors")
    extractors.add_argument("--json", action="store_true")
    extractors.set_defaults(func=cmd_extractors)

    probe = subparsers.add_parser("probe", help="live inspection of a running game JVM")
    probe_sub = probe.add_subparsers(dest="probe_command", required=True)

    def add_probe_common(subparser):
        subparser.add_argument("--pid", type=str,
                               help="JVM process id or 'auto' (default: config pid)")
        subparser.add_argument("--java", help="path to a JDK 11+ java executable")

    probe_dump = probe_sub.add_parser("dump", help="attach and print one live sample")
    add_probe_common(probe_dump)
    probe_dump.add_argument("--machine", help="filter by Java machine class, e.g. MTEEyeOfHarmony")
    probe_dump.add_argument("--world", help="offline save for dimension name mapping")
    probe_dump.add_argument("--save", help="write the sample as a snapshot JSON")
    probe_dump.add_argument("--out", help=argparse.SUPPRESS)
    probe_dump.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for a sample")
    probe_dump.add_argument("--dim", action="append", type=int, help="only sample these dimension ids (repeatable)")
    probe_dump.add_argument("--max", type=int, default=500, help="max machines per sample (default: 500)")
    probe_dump.add_argument("--json", action="store_true")
    probe_dump.add_argument("--detail", action="store_true")
    probe_dump.add_argument("--where", action="append", help="field filter, e.g. progress>0 (repeatable, AND)")
    probe_dump.add_argument("--fields", help="comma separated field names to display")
    probe_dump.add_argument("--all", action="store_true",
                            help="include fallback GTMachine entries (hatches/buses)")
    probe_dump.set_defaults(func=cmd_probe_dump)

    probe_watch = probe_sub.add_parser("watch", help="attach and stream live samples")
    add_probe_common(probe_watch)
    probe_watch.add_argument("--machine", help="filter by Java machine class, e.g. MTEEyeOfHarmony")
    probe_watch.add_argument("--world", help="offline save for dimension name mapping")
    probe_watch.add_argument("--save", help="write every sample as a snapshot JSON")
    probe_watch.add_argument("--changes", action="store_true", help="only print machines that changed")
    probe_watch.add_argument("--interval", type=int, default=1000, help="sample interval in ms")
    probe_watch.add_argument("--out", help=argparse.SUPPRESS)
    probe_watch.add_argument("--samples", type=int, default=0, help="stop after N samples (0 = Ctrl+C)")
    probe_watch.add_argument("--timeout", type=float, default=60.0,
                             help="stop after N seconds (default: 60, 0 = unlimited)")
    probe_watch.add_argument("--dim", action="append", type=int, help="only sample these dimension ids (repeatable)")
    probe_watch.add_argument("--max", type=int, default=500, help="max machines per sample (default: 500)")
    probe_watch.add_argument("--json", action="store_true")
    probe_watch.add_argument("--jsonl", action="store_true",
                             help="emit one compact JSON object per sample")
    probe_watch.add_argument("--detail", action="store_true")
    probe_watch.add_argument("--where", action="append", help="field filter, e.g. progress>0 (repeatable, AND)")
    probe_watch.add_argument("--fields", help="comma separated field names to display")
    probe_watch.add_argument("--all", action="store_true",
                             help="include fallback GTMachine entries (hatches/buses)")
    probe_watch.add_argument("--min-delta", type=int, default=0,
                             help="with --changes: only show numeric deltas >= this")
    probe_watch.add_argument("--until", action="append",
                             help="stop when a machine matches this filter (e.g. progress>30000)")
    probe_watch.set_defaults(func=cmd_probe_watch)

    probe_chunk = probe_sub.add_parser("chunk", help="inspect a loaded chunk (isModified, TE count)")
    add_probe_common(probe_chunk)
    probe_chunk.add_argument("--dim", type=int, required=True, help="dimension id")
    probe_chunk.add_argument("--x", type=int, required=True, help="block x")
    probe_chunk.add_argument("--z", type=int, required=True, help="block z")
    probe_chunk.add_argument("--timeout", type=float, default=15.0)
    probe_chunk.add_argument("--json", action="store_true")
    probe_chunk.set_defaults(func=cmd_probe_chunk)

    probe_te = probe_sub.add_parser("te", help="inspect one tile entity (classes, fields, inventory)")
    add_probe_common(probe_te)
    probe_te.add_argument("--dim", type=int, required=True, help="dimension id")
    probe_te.add_argument("--pos", required=True, help="block position x,y,z")
    probe_te.add_argument("--timeout", type=float, default=15.0)
    probe_te.add_argument("--json", action="store_true")
    probe_te.set_defaults(func=cmd_probe_te)

    probe_worlds = probe_sub.add_parser("worlds", help="list loaded worlds and machine counts")
    add_probe_common(probe_worlds)
    probe_worlds.add_argument("--out", help=argparse.SUPPRESS)
    probe_worlds.add_argument("--timeout", type=float, default=20.0, help="seconds to wait for the summary")
    probe_worlds.add_argument("--json", action="store_true")
    probe_worlds.set_defaults(func=cmd_probe_worlds)

    probe_find = probe_sub.add_parser("find", help="find the running GTNH game JVM")
    probe_find.add_argument("--json", action="store_true")
    probe_find.set_defaults(func=cmd_probe_find)

    probe_stop = probe_sub.add_parser("stop", help="ask a running probe to stop")
    add_probe_common(probe_stop)
    probe_stop.set_defaults(func=cmd_probe_stop)

    _add_compact_json(parser)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    parser._argv = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(argv)
    try:
        from ..extractors.plugins import PluginError, load_config_plugins

        load_config_plugins(getattr(args, "plugin", None))
        config_module.apply_defaults(args)
        if args.command in ("show", "scan", "dump") and not getattr(args, "world", None):
            return _error(
                args, "no world; pass --world or run 'gtnh-inspect config set world PATH'"
            )
        if args.command == "probe" and args.probe_command != "find":
            pid = getattr(args, "pid", None)
            if pid is not None:
                if isinstance(pid, str) and pid.lower() == "auto":
                    from ..live.findgame import find_game_pid

                    found = find_game_pid()
                    if not found:
                        return _error(
                            args,
                            "no running GTNH game found; run 'gtnh-inspect probe find'",
                        )
                    args.pid = int(found["pid"])
                    print(
                        "using pid %d (%s)" % (args.pid, found.get("instance") or "GTNH"),
                        file=sys.stderr,
                    )
                else:
                    try:
                        args.pid = int(pid)
                    except (TypeError, ValueError):
                        return _error(args, "invalid --pid: %r" % (pid,))
            if getattr(args, "pid", None) is None:
                return _error(
                    args,
                    "no pid; pass --pid, --pid auto, or 'gtnh-inspect config set pid N'",
                )
        return args.func(args)
    except PluginError as exc:
        return _error(args, "plugin error: %s" % exc)
    except (WorldError, RegionError, NbtError, FileNotFoundError, ValueError) as exc:
        return _error(args, str(exc))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
