#!/usr/bin/env python3
"""Forward trace ancestry and owned-scratch audit for the F2 private replay.

This is the first cold-read audit version that can close the PID-role part of
the binding when the parent guard supplies a process record.  It parses
``clone``, ``clone3``, ``fork``, ``vfork`` and ``execve`` edges from filtered
``strace -ff`` files, checks every traced PID against the guard record, and
then applies source/private path policy.  A parent-owned scratch directory is
allowed only when the guard registers its exact path (or an explicit
``/tmp/ds02-direct-bi4-*`` prefix) and the trace contains the matching
``mkdir`` by its registered creator.  A prefix is expanded only to the exact
path created by that creator; it does not whitelist ``/tmp``.

Relative paths and directory-FD paths are deliberately retained as UNKNOWN;
this version does not guess a cwd or reconstruct an fd table.  The bound
venv/site-packages environment is reported as a registered shared environment
scope.  It is not claimed to be a standalone portable environment.

The helper reads JSON, source-sidecar files and trace text only.  It never
opens H5/BI4/raw scientific content and never starts a worker.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V2_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_cold_readonly_audit_v2.py"
SCHEMA = "ds02.stage2.f2-cold-readonly-audit.v4"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PROCESS_SYSCALLS = {"clone", "clone3", "fork", "vfork"}
EXEC_SYSCALLS = {"execve", "execveat"}
SCRATCH_CREATE_SYSCALLS = {"mkdir", "mkdirat"}
SOURCE_ROLE_PREFIXES = ("source", "copy", "provenance_copy")
PRIVATE_ROLE_PREFIXES = (
    "private", "worker", "evaluator", "helper", "strace", "executor",
    "converter", "replay", "portable",
)


class AuditV4Error(RuntimeError):
    pass


def _is_source_role(role: Any) -> bool:
    value = str(role or "").lower()
    return value in {"copy", "source_copy", "copy_worker", "source_phase"} or value.startswith(SOURCE_ROLE_PREFIXES)


def _is_private_role(role: Any) -> bool:
    value = str(role or "").lower()
    return value in {"private_worker", "private_evaluator", "executor_v36", "v36_executor"} or value.startswith(PRIVATE_ROLE_PREFIXES)


def _load_v2():
    if not V2_SCRIPT.is_file():
        raise AuditV4Error(f"v2 audit dependency is missing: {V2_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ds02_cold_audit_v2_bound", V2_SCRIPT)
    if spec is None or spec.loader is None:
        raise AuditV4Error("cannot load v2 audit dependency")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load_v2()
QUOTED = V2.QUOTED


def _load_json(path: Path | str) -> dict[str, Any]:
    try:
        return V2.load_json(path)
    except Exception as error:  # keep v3's public error type stable
        if isinstance(error, AuditV4Error):
            raise
        raise AuditV4Error(str(error)) from error


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return V2.canonical_sha(value)


def _sha256_file(path: Path | str) -> str:
    return V2.sha256_file(path)


# Keep the small helper surface used by the v2 tests and by parent-side
# metadata probes.  These aliases are JSON/trace utilities only.
sha256_file = _sha256_file
canonical_sha = _canonical_sha
_binding_files = V2._binding_files
_product_paths = V2._product_paths


def _decode_quoted(raw: str) -> str:
    return V2._decode_quoted(raw)


def _syscall_name(line: str) -> str:
    return V2._syscall_name(line)


def _path_tokens(line: str) -> list[str]:
    return list(V2._path_tokens(line))


def _relative_file_access(line: str) -> bool:
    return bool(V2._relative_file_access(line))


def _trace_files(prefix: Path) -> list[Path]:
    return V2._trace_files(prefix)


def _trace_pid(path: Path, prefix: Path) -> int | None:
    return V2._trace_pid(path, prefix)


def _within(path: str | Path, root: str | Path) -> bool:
    return V2._within(path, root)


def _result_pid(line: str) -> int | None:
    """Return a positive child PID from a process-creation syscall line."""
    match = re.search(r"\)\s*=\s*(-?\d+)(?:\s|$)", line)
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def _first_absolute_path(line: str) -> str | None:
    tokens = _path_tokens(line)
    return tokens[0] if tokens else None


def _int_value(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _process_records(value: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """Read explicit guard process records without trusting arbitrary lists."""
    records: dict[int, dict[str, Any]] = {}
    containers = []
    for key in ("processes", "process_tree", "pid_records", "process_bindings",
                "ancestry", "pid_graph"):
        candidate = value.get(key)
        if isinstance(candidate, (list, Mapping)):
            containers.append(candidate)
    nested = value.get("parent_guard")
    if isinstance(nested, Mapping):
        for key in ("processes", "process_tree", "pid_records", "process_bindings", "ancestry"):
            candidate = nested.get(key)
            if isinstance(candidate, (list, Mapping)):
                containers.append(candidate)
    for container in containers:
        if isinstance(container, Mapping):
            iterable = []
            for key, item in container.items():
                if isinstance(item, Mapping):
                    value_item = dict(item)
                    value_item.setdefault("pid", key)
                    iterable.append(value_item)
        else:
            iterable = [item for item in container if isinstance(item, Mapping)]
        for item in iterable:
            pid = _int_value(item.get("pid", item.get("process_id")))
            if pid is None:
                continue
            record = dict(item)
            parent = _int_value(item.get("parent_pid", item.get("ppid")))
            if parent is not None:
                record["parent_pid"] = parent
            record["pid"] = pid
            records[pid] = record
    return records


def _root_pids(value: Mapping[str, Any], records: Mapping[int, Mapping[str, Any]]) -> set[int]:
    roots: set[int] = set()
    for key in ("root_pids", "guard_pids", "root_pid", "guard_pid", "wrapper_pid",
                "supervisor_pid", "launcher_pid"):
        candidate = value.get(key)
        if isinstance(candidate, list):
            roots.update(pid for pid in (_int_value(x) for x in candidate) if pid is not None)
        else:
            pid = _int_value(candidate)
            if pid is not None:
                roots.add(pid)
    nested = value.get("parent_guard")
    if isinstance(nested, Mapping):
        roots.update(_root_pids(nested, records))
    for pid, record in records.items():
        role = str(record.get("role", "")).lower()
        if role in {"parent_guard", "guard", "supervisor", "wrapper"}:
            roots.add(pid)
    return roots


def _scratch_records(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    candidates = []
    for key in ("scratch_roots", "owned_scratch_roots", "temporary_roots",
                "scratch", "owned_scratch"):
        candidate = value.get(key)
        if isinstance(candidate, list):
            candidates.extend(candidate)
        elif isinstance(candidate, Mapping):
            if isinstance(candidate.get("path"), str) or isinstance(candidate.get("path_prefix"), str) or isinstance(candidate.get("prefix"), str):
                candidates.append(candidate)
            else:
                candidates.extend(dict(item, path=key) if isinstance(item, Mapping) else {"path": key}
                                  for key, item in candidate.items())
    nested = value.get("parent_guard")
    if isinstance(nested, Mapping):
        nested_value = _scratch_records(nested)
        candidates.extend(nested_value)
    for item in candidates:
        if isinstance(item, str):
            result.append({"path": os.path.normpath(item), "allowed_pids": [],
                           "creator_pid": None, "registered": True})
            continue
        if not isinstance(item, Mapping):
            continue
        exact_path = item.get("path")
        path_prefix = item.get("path_prefix", item.get("prefix"))
        if not isinstance(exact_path, str) and not isinstance(path_prefix, str):
            continue
        if isinstance(exact_path, str) and not exact_path.startswith("/"):
            continue
        if isinstance(path_prefix, str) and not path_prefix.startswith("/"):
            continue
        allowed = item.get("allowed_pids", item.get("owner_pids", []))
        if not isinstance(allowed, list):
            allowed = [allowed]
        allowed_pids = sorted(pid for pid in (_int_value(x) for x in allowed) if pid is not None)
        creator = _int_value(item.get("creator_pid", item.get("owner_pid")))
        if creator is not None and creator not in allowed_pids:
            allowed_pids.append(creator)
        result.append({
            "path": os.path.normpath(exact_path) if isinstance(exact_path, str) else None,
            "path_prefix": os.path.normpath(path_prefix) if isinstance(path_prefix, str) else None,
            "allowed_pids": sorted(set(allowed_pids)), "creator_pid": creator,
            "registered": bool(item.get("registered", True)),
            "preexisting": bool(item.get("preexisting", False)),
        })
    unique: dict[tuple[str | None, str | None], dict[str, Any]] = {
        (item["path"], item["path_prefix"]): item for item in result
    }
    return sorted(unique.values(), key=lambda item: (item["path"] or item["path_prefix"] or ""))


def _guard_contract(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"records": {}, "root_pids": set(), "scratch_roots": [],
                "path": None, "available": False}
    value = _load_json(path)
    records = _process_records(value)
    roots = _root_pids(value, records)
    if not roots:
        raise AuditV4Error("parent guard record has no explicit root PID")
    return {"records": records, "root_pids": roots, "scratch_roots": _scratch_records(value),
            "path": str(path.expanduser().resolve()), "available": True,
            "sha256": _sha256_file(path)}


def _trace_events(prefix: Path) -> dict[str, Any]:
    files = _trace_files(prefix)
    if not files:
        raise AuditV4Error(f"no trace files found for {prefix}")
    groups: dict[int | None, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    execs: dict[int, list[str]] = defaultdict(list)
    scratch_creations: list[dict[str, Any]] = []
    for path in files:
        pid = _trace_pid(path, prefix)
        group = groups.setdefault(pid, {"pid": pid, "files": [], "lines": [], "bytes": 0})
        group["files"].append(str(path))
        group["bytes"] += int(path.stat().st_size)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            group["lines"].append(line)
            syscall = _syscall_name(line)
            child = _result_pid(line) if syscall in PROCESS_SYSCALLS else None
            if pid is not None and child is not None:
                edges.append({"parent_pid": pid, "child_pid": child,
                              "syscall": syscall, "line": line[:500]})
            if pid is not None and syscall in EXEC_SYSCALLS:
                executable = _first_absolute_path(line)
                if executable:
                    execs[pid].append(executable)
            if pid is not None and syscall in SCRATCH_CREATE_SYSCALLS:
                created = _first_absolute_path(line)
                if created:
                    scratch_creations.append({"pid": pid, "path": created,
                                              "syscall": syscall, "line": line[:500]})
    return {"files": files, "groups": groups, "edges": edges,
            "execs": {pid: sorted(set(paths)) for pid, paths in execs.items()},
            "scratch_creations": scratch_creations,
            "trace_pids": sorted(pid for pid in groups if pid is not None),
            "trace_bytes": sum(int(path.stat().st_size) for path in files)}


def _verify_ancestry(events: Mapping[str, Any], guard: Mapping[str, Any],
                     source_pids: set[int], private_pids: set[int]) -> dict[str, Any]:
    records: Mapping[int, Mapping[str, Any]] = guard["records"]
    roots: set[int] = set(guard["root_pids"])
    trace_pids = set(int(pid) for pid in events["trace_pids"])
    trace_parent: dict[int, int] = {}
    edge_conflicts: list[dict[str, Any]] = []
    unrecorded_edges: list[dict[str, Any]] = []
    for edge in events["edges"]:
        parent, child = int(edge["parent_pid"]), int(edge["child_pid"])
        existing = trace_parent.get(child)
        if existing is not None and existing != parent:
            edge_conflicts.append(edge)
        trace_parent[child] = parent
        if child not in records:
            unrecorded_edges.append(edge)
    parent_map: dict[int, int] = {}
    parent_conflicts: list[dict[str, Any]] = []
    for pid, record in records.items():
        parent = _int_value(record.get("parent_pid", record.get("ppid")))
        if parent is not None:
            parent_map[pid] = parent
            observed = trace_parent.get(pid)
            if observed is not None and observed != parent:
                parent_conflicts.append({"pid": pid, "guard_parent_pid": parent,
                                         "trace_parent_pid": observed})
    for child, parent in trace_parent.items():
        parent_map.setdefault(child, parent)

    missing_records = sorted(pid for pid in trace_pids if pid not in records)
    missing_exec = sorted(pid for pid in trace_pids if pid not in roots and not events["execs"].get(pid))
    ancestry_paths: dict[str, list[int]] = {}
    ancestry_missing: dict[str, str] = {}
    cycles: list[int] = []
    for pid in sorted(trace_pids):
        path: list[int] = []
        current = pid
        seen: set[int] = set()
        while current not in roots:
            if current in seen:
                cycles.append(pid)
                ancestry_missing[str(pid)] = "cycle"
                break
            seen.add(current)
            path.append(current)
            parent = parent_map.get(current)
            if parent is None:
                ancestry_missing[str(pid)] = "parent_missing_before_guard_root"
                break
            current = parent
        else:
            path.append(current)
            ancestry_paths[str(pid)] = path

    role_mismatches: list[dict[str, Any]] = []
    for pid in sorted(source_pids | private_pids):
        record = records.get(pid)
        role = str(record.get("role", "")).lower() if record else ""
        expected = "source_copy" if pid in source_pids else "private_worker_or_evaluator"
        source_role = _is_source_role(role)
        private_role = _is_private_role(role)
        if (expected == "source_copy" and not source_role) or (expected != "source_copy" and not private_role):
            role_mismatches.append({"pid": pid, "expected": expected, "guard_role": role})

    verified = bool(guard["available"]) and not (
        missing_records or missing_exec or edge_conflicts or unrecorded_edges or
        parent_conflicts or ancestry_missing or role_mismatches or not roots
    )
    return {
        "verified": verified, "guard_record_available": bool(guard["available"]),
        "guard_root_pids": sorted(roots), "trace_pids": sorted(trace_pids),
        "guard_record_pids": sorted(records), "missing_guard_records": missing_records,
        "missing_exec_evidence": missing_exec, "edge_conflicts": edge_conflicts,
        "unrecorded_child_edges": unrecorded_edges, "parent_conflicts": parent_conflicts,
        "ancestry_missing": ancestry_missing, "cycles": sorted(set(cycles)),
        "role_mismatches": role_mismatches, "ancestry_paths": ancestry_paths,
        "exec_paths": {str(pid): paths for pid, paths in events["execs"].items()},
        "edge_count": len(events["edges"]),
    }


def _expand_scratch_roots(items: Sequence[Mapping[str, Any]], events: Mapping[str, Any],
                          ancestry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Resolve registered dynamic scratch prefixes to trace-created paths.

    The converter uses ``tempfile.mkdtemp(prefix="ds02-direct-bi4-")`` and
    therefore cannot know the random suffix before the run.  A parent guard
    may register the exact prefix and creator PID.  We only admit paths that
    appear in a matching ``mkdir`` event from that creator and whose PID has
    a verified ancestry path.  An exact path still follows the older
    registration rule; a prefix without a matching creation remains
    unverified.
    """
    expanded: list[dict[str, Any]] = []
    creations = list(events.get("scratch_creations", []))
    verified_paths = ancestry.get("ancestry_paths", {})
    for item in items:
        exact = item.get("path")
        prefix = item.get("path_prefix")
        creator = item.get("creator_pid")
        matching = [event for event in creations
                    if creator is not None and int(event["pid"]) == int(creator)
                    and ((isinstance(exact, str) and event["path"] == exact) or
                         (isinstance(prefix, str) and event["path"].startswith(prefix)))]
        candidates = sorted({event["path"] for event in matching}) if prefix and not exact else [exact] if exact else []
        # A preexisting path is admissible only when it is exact.  A prefix
        # cannot prove the identity of a preexisting directory without a
        # creation event, so it remains conservatively unverified.
        if not candidates and exact and item.get("preexisting"):
            candidates = [exact]
        for path in candidates:
            made = [event for event in matching if event["path"] == path]
            creator_verified = creator is not None and bool(made) and str(creator) in verified_paths
            usable = bool(creator_verified or (exact and item.get("preexisting")))
            expanded.append({**item, "path": path, "resolved_from_prefix": bool(prefix and not exact),
                             "mkdir_events": made, "creator_verified": creator_verified,
                             "usable": usable})
        if not candidates:
            expanded.append({**item, "mkdir_events": [], "creator_verified": False,
                             "usable": False})
    unique: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    for item in expanded:
        unique[(item.get("path"), item.get("creator_pid"))] = item
    return sorted(unique.values(), key=lambda item: (item.get("path") or item.get("path_prefix") or ""))


def classify_trace(prefix: Path, *, source_pids: set[int], private_pids: set[int],
                   original_roots: Sequence[str], target_root: str, output_root: str,
                   registered_environment_roots: Sequence[str] = (),
                   guard: Mapping[str, Any] | None = None) -> dict[str, Any]:
    guard = guard or _guard_contract(None)
    events = _trace_events(prefix)
    ancestry = _verify_ancestry(events, guard, source_pids, private_pids)
    records: Mapping[int, Mapping[str, Any]] = guard["records"]
    scratch = _expand_scratch_roots(guard["scratch_roots"], events, ancestry)
    groups: dict[str, dict[str, Any]] = {}
    for pid, data in events["groups"].items():
        pid_key = str(pid) if pid is not None else "unclassified"
        record = records.get(pid, {}) if pid is not None else {}
        guard_role = str(record.get("role", ""))
        role_lower = guard_role.lower()
        if pid in source_pids or _is_source_role(role_lower):
            access_role = "source_copy"
        elif pid in private_pids or _is_private_role(role_lower):
            access_role = "private_worker_or_evaluator"
        elif role_lower in {"parent_guard", "guard", "supervisor", "wrapper"}:
            access_role = "parent_guard"
        else:
            access_role = "unclassified"
        group = {"pid": pid, "files": data["files"], "bytes": data["bytes"],
                 "access_role": access_role, "guard_role": guard_role,
                 "original_hits": [], "target_hits": [], "environment_hits": [],
                 "owned_scratch_hits": [], "other_absolute_hits": [],
                 "unresolved_relative_paths": []}
        for line in data["lines"]:
            if _relative_file_access(line):
                group["unresolved_relative_paths"].append(line[:500])
            if _syscall_name(line) in SCRATCH_CREATE_SYSCALLS:
                # Creation is represented in ``scratch.registered`` and
                # ``mkdir_events``; it is not a data-file access hit.
                continue
            for token in _path_tokens(line):
                if any(_within(token, item["path"]) and item["usable"] and
                       (not item["allowed_pids"] or pid in item["allowed_pids"])
                       for item in scratch):
                    group["owned_scratch_hits"].append(token)
                elif any(_within(token, root) for root in registered_environment_roots):
                    group["environment_hits"].append(token)
                elif any(_within(token, root) for root in original_roots):
                    group["original_hits"].append(token)
                elif _within(token, target_root) or _within(token, output_root):
                    group["target_hits"].append(token)
                elif token.startswith(("/home/", "/var/tmp/", "/tmp/")):
                    group["other_absolute_hits"].append(token)
        for key in ("original_hits", "target_hits", "environment_hits", "owned_scratch_hits", "other_absolute_hits"):
            group[key] = sorted(set(group[key]))
        group["unresolved_relative_paths"] = sorted(set(group["unresolved_relative_paths"]))
        groups[pid_key] = group
    unknown_groups = sorted(pid for pid, group in groups.items() if group["access_role"] == "unclassified")
    private_groups = [group for group in groups.values() if group["access_role"] == "private_worker_or_evaluator"]
    private_original = {str(group["pid"]): group["original_hits"] for group in private_groups if group["original_hits"]}
    private_unbound = {str(group["pid"]): group["other_absolute_hits"] for group in private_groups if group["other_absolute_hits"]}
    private_relative = {str(group["pid"]): group["unresolved_relative_paths"] for group in private_groups if group["unresolved_relative_paths"]}
    missing_source = sorted(pid for pid in source_pids if str(pid) not in groups)
    missing_private = sorted(pid for pid in private_pids if str(pid) not in groups)
    return {
        "prefix": str(prefix.expanduser().resolve()), "files": [str(path) for path in events["files"]],
        "groups": groups, "source_pids": sorted(source_pids), "private_pids": sorted(private_pids),
        "unknown_groups": unknown_groups, "missing_source_pids": missing_source,
        "missing_private_pids": missing_private, "private_original_path_violations": private_original,
        "private_unbound_absolute_path_hits": private_unbound,
        "private_unresolved_relative_path_access": private_relative,
        "registered_environment_roots": sorted(os.path.normpath(str(x)) for x in registered_environment_roots),
        "source_copy_original_access_allowed": True, "private_target_only_required": True,
        "trace_bytes": events["trace_bytes"], "ancestry": ancestry,
        "scratch": {"registered": scratch,
                     "unverified_roots": [item for item in scratch if not item["usable"]]},
        "environment_scope": "REGISTERED_SHARED_ENVIRONMENT_ONLY; standalone environment not claimed",
        "cwd_fd_resolution": "UNKNOWN_FOR_UNRESOLVED_RELATIVE_OR_DIRFD_PATHS",
    }


def _original_and_environment_roots(v34: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    original: set[str] = set()
    environment = {"/usr", "/lib", "/lib64", "/etc", "/dev", "/proc"}
    for item in v34.get("source_entries", []):
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            path = os.path.normpath(item["path"])
            original.update({os.path.dirname(path), path})
    for item in v34.get("runtime_sources", []):
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            path = os.path.normpath(item["path"])
            if item.get("role") == "python_executable":
                current = path
                for _ in range(3):
                    environment.add(current)
                    parent = os.path.dirname(current)
                    if parent == current:
                        break
                    current = parent
            else:
                original.update({os.path.dirname(path), path})
    return original, environment


def audit(*, executor_report_path: Path, v34_request_path: Path, provenance_path: Path,
          trace_prefix: Path, source_pids: Sequence[int], private_pids: Sequence[int],
          target_root: Path, output_root: Path, parent_guard_path: Path | None = None,
          v16_proof: Path | None = None, v16_result: Path | None = None,
          evaluator_report_path: Path | None = None) -> dict[str, Any]:
    executor = _load_json(executor_report_path)
    v34 = _load_json(v34_request_path)
    if executor.get("original_path_fallback") != "FORBIDDEN":
        raise AuditV4Error("executor report permits original-path fallback")
    if v34.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise AuditV4Error("v34 request schema differs")
    if v34.get("sha256") != _canonical_sha(v34):
        raise AuditV4Error("v34 request canonical SHA differs")
    guard = _guard_contract(parent_guard_path)
    original, environment = _original_and_environment_roots(v34)
    original.update({str(v34_request_path.expanduser().resolve()), str(provenance_path.expanduser().resolve())})
    trace = classify_trace(trace_prefix, source_pids=set(int(x) for x in source_pids),
                           private_pids=set(int(x) for x in private_pids),
                           original_roots=sorted(original), target_root=str(target_root.expanduser().resolve()),
                           output_root=str(output_root.expanduser().resolve()),
                           registered_environment_roots=sorted(environment), guard=guard)
    provenance = V2._binding_files(_load_json(provenance_path))
    product = V2._product_paths(executor, str(target_root), str(output_root))
    blockers: list[str] = []
    if not trace["ancestry"]["verified"]:
        blockers.append("trace PID ancestry/process roles are not verified by the parent guard record")
    if trace["unknown_groups"] or trace["missing_source_pids"] or trace["missing_private_pids"]:
        blockers.append("trace PID groups are incomplete or unclassified")
    if trace["private_original_path_violations"]:
        blockers.append("private worker/evaluator opened an original source/runtime path")
    if trace["private_unbound_absolute_path_hits"]:
        blockers.append("private worker/evaluator opened an unregistered absolute path")
    if trace["private_unresolved_relative_path_access"]:
        blockers.append("private worker/evaluator used an unresolved relative/dirfd path")
    if trace["scratch"]["unverified_roots"]:
        blockers.append("temporary scratch root lacks parent registration/creator trace")
    if product["module_original_path_violations"]:
        blockers.append("private runtime module audit is missing or points outside relocated roots")
    license_pending = provenance["license_scope_status"] != "DECLARED"
    source_binding_status = "PASS_SOURCE_PROCESS_BINDING" if not blockers else "PENDING_SOURCE_PROCESS_BINDING"
    status = source_binding_status + ("_LICENSE_SCOPE_PENDING" if license_pending else "")
    return {
        "schema": SCHEMA, "status": status,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "executor_report": {"path": str(executor_report_path.expanduser().resolve()),
                             "sha256": _sha256_file(executor_report_path)},
        "trace": trace, "parent_guard": {"path": guard["path"], "sha256": guard.get("sha256"),
                                            "available": guard["available"]},
        "private_runtime": product, "provenance": provenance,
        "source_copy_original_access": "ALLOWED_FOR_SOURCE_PHASE",
        "private_worker_original_access": "FORBIDDEN",
        "environment_scope": "REGISTERED_SHARED_ENVIRONMENT_ONLY",
        "standalone_environment_claim": "NOT_CLAIMED",
        "hdf5_or_bi4_content_read": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN), "source_binding_status": source_binding_status,
        "license_scope_status": provenance["license_scope_status"], "blockers": blockers,
        "credit_boundary": "Source/process binding evidence only; no portable, QI, QN or QE credit.",
    }


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        raise AuditV4Error(f"refusing existing audit output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = dict(value)
    body["sha256"] = _canonical_sha(body)
    target.write_text(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-report", type=Path, required=True)
    parser.add_argument("--v34-request", type=Path, required=True)
    parser.add_argument("--provenance-sidecar", type=Path, required=True)
    parser.add_argument("--trace-prefix", type=Path, required=True)
    parser.add_argument("--parent-guard-record", type=Path)
    parser.add_argument("--source-pids", type=int, nargs="+", required=True)
    parser.add_argument("--private-pids", type=int, nargs="+", required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--v16-proof", type=Path)
    parser.add_argument("--v16-result", type=Path)
    parser.add_argument("--evaluator-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        value = audit(executor_report_path=args.executor_report, v34_request_path=args.v34_request,
                      provenance_path=args.provenance_sidecar, trace_prefix=args.trace_prefix,
                      source_pids=args.source_pids, private_pids=args.private_pids,
                      target_root=args.target_root, output_root=args.output_root,
                      parent_guard_path=args.parent_guard_record, v16_proof=args.v16_proof,
                      v16_result=args.v16_result, evaluator_report_path=args.evaluator_report)
        if args.output:
            _write_new(args.output, value)
            value = dict(value, output_path=str(args.output.resolve()), output_sha256=_sha256_file(args.output))
    except (AuditV4Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"cold readonly audit v3: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
