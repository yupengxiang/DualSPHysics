#!/usr/bin/env python3
"""Parent-lease bridge for the F2 portable v7 replay.

The v7 engine owns relocation and the fresh loader subprocess.  It deliberately
does not mutate the shared resource ledger.  This bridge supplies the missing
parent boundary for the external ``/var/tmp`` namespace: it binds the actual
Stage2 v4 dispatch/strict/runtime sources, takes the existing ledger lock,
calls the v4 reservation guard, runs v7, measures the exact new target and
output trees, verifies required artifacts, and charges the measured bytes and
CPU under the same attempt id.

The bridge is additive and development-only.  It never resets the ledger,
creates a second data root, grants QI/QN/QE, or treats a metadata preflight as
a replay.  A call without ``--io-slot-approved`` performs only stat/hash and
filesystem checks.  The parent must still supply the approved slot and an OS
``strace`` receipt for native C HDF5/BI4 opens.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-portable-ledger-bridge-request.v8"
REPORT_SCHEMA = "ds02.stage2.f2-portable-ledger-bridge-report.v8"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
V7_SCHEMA = "ds02.stage2.f2-portable-orchestration-request.v7"
V4_GUARD_ROLES = (
    "shared_dispatch_v4",
    "shared_strict_dispatch_v4",
    "shared_runtime_v4",
    "shared_runtime_v2",
)


class BridgeV8Error(RuntimeError):
    """Raised when parent reservation or external storage accounting is unsafe."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise BridgeV8Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise BridgeV8Error(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise BridgeV8Error(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise BridgeV8Error(f"{role} must be a lowercase SHA-256")
    return value


def _require_file(value: Any, role: str) -> Path:
    target = Path(str(value)).expanduser().resolve()
    if not target.is_file():
        raise BridgeV8Error(f"{role} is missing: {target}")
    return target


def _stat_binding(item: Mapping[str, Any], *, verify_content: bool) -> dict[str, Any]:
    path = _require_file(item.get("path"), str(item.get("role", "source")))
    stat = path.stat()
    expected_bytes = item.get("bytes")
    if expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise BridgeV8Error(f"source byte stat differs: {path}")
    expected_mtime = item.get("mtime_ns")
    if expected_mtime is not None and int(expected_mtime) != stat.st_mtime_ns:
        raise BridgeV8Error(f"source mtime stat differs: {path}")
    digest = _require_sha(item.get("sha256"), f"{item.get('role')}.sha256")
    if verify_content and sha256_file(path) != digest:
        raise BridgeV8Error(f"source content SHA differs: {path}")
    return {"role": str(item.get("role")), "path": str(path),
            "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "sha256": digest}


def _load_v7(path: Path | str) -> dict[str, Any]:
    request = load_json(path)
    if request.get("schema") != V7_SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise BridgeV8Error("v7 request is not a ready development request")
    if request.get("qualification") != UNKNOWN or request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise BridgeV8Error("v7 request is not model-free UNKNOWN")
    if request.get("sha256") != canonical_sha(request):
        raise BridgeV8Error("v7 request canonical SHA differs")
    return request


def _guard_paths(root: Path) -> dict[str, Path]:
    scripts = root / "lagrangian-fluid-lab" / "scripts"
    return {
        "shared_dispatch_v4": scripts / "ds_data02_stage2_dispatch_v4.py",
        "shared_strict_dispatch_v4": scripts / "ds_data02_strict_dispatch_v4.py",
        "shared_runtime_v4": scripts / "ds_data02_runtime_v4.py",
        "shared_runtime_v2": scripts / "ds_data02_runtime_v2.py",
    }


def _tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            try:
                if not path.is_symlink():
                    total += int(path.stat().st_size)
            except FileNotFoundError:
                continue
    return total


def _disk_probe(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise BridgeV8Error(f"filesystem probe root is unavailable: {target}")
    usage = shutil.disk_usage(target)
    return {"path": str(target), "total_bytes": int(usage.total),
            "used_bytes": int(usage.used), "free_bytes": int(usage.free),
            "probe_status": "READ_ONLY_STAT"}


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _load_shared_v4(dispatch_path: Path) -> tuple[Any, Any]:
    """Load the exact dispatch v4 and its runtime dependency closure."""
    scripts = dispatch_path.parent
    previous = list(sys.path)
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location("_ds02_shared_dispatch_v4_bridge", dispatch_path)
        if spec is None or spec.loader is None:
            raise BridgeV8Error(f"cannot import shared dispatch v4: {dispatch_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous
    if not hasattr(module, "check_reservation") or not hasattr(module, "runtime"):
        raise BridgeV8Error("shared dispatch v4 lacks reservation/runtime interface")
    module.install_guard()
    return module, module.runtime


def _parent_ledger_binding(request: Mapping[str, Any]) -> dict[str, Any]:
    binding = request.get("parent_resource_binding")
    if not isinstance(binding, Mapping):
        raise BridgeV8Error("parent_resource_binding is required")
    if binding.get("no_reset") is not True or binding.get("no_new_data_root_ledger") is not True:
        raise BridgeV8Error("parent ledger reset/new-root policy is unsafe")
    ledger = _require_file(binding.get("path"), "parent ledger")
    checkpoint = _require_file(binding.get("checkpoint_path"), "parent checkpoint")
    return {"ledger": ledger, "checkpoint": checkpoint, "binding": dict(binding)}


def build_request(v7_request_path: Path | str, output_path: Path | str,
                  *, shared_root: Path | str,
                  data_root: Path | str = "/home/jade/Projects/DualSPHysics-data/ds-data-02") -> dict[str, Any]:
    v7_path = _require_file(v7_request_path, "v7 request")
    v7 = _load_v7(v7_path)
    root = Path(shared_root).expanduser().resolve()
    guards = _guard_paths(root)
    guard_bindings = []
    for role, path in guards.items():
        stat = _stat_binding({"role": role, "path": str(path),
                              "bytes": path.stat().st_size,
                              "mtime_ns": path.stat().st_mtime_ns,
                              "sha256": sha256_file(path)}, verify_content=False)
        guard_bindings.append(stat)
    parent = _parent_ledger_binding(v7)
    plan = load_json(v7["storage_plan"]["path"])
    mapping = plan["storage_mapping"]
    target_root = Path(v7["copy_contract"]["target_root"]).expanduser().resolve()
    selected_root = Path(v7["execution"]["output_dir"]).expanduser().resolve()
    required_bytes = int(v7["resource_request"]["new_storage_reservation_bytes"])
    attempt_id = "f2-s1-portable-ledger-bridge-v8-001"
    # The listed artifacts are checked after the child returns.  They cover
    # orchestration, v5 loader, Python audit, sealed copy, and native output;
    # the worker may add more files underneath the two explicitly scoped roots.
    expected_artifacts = [
        {"role": "v7_orchestration_report", "path": str(selected_root.parent / "orchestration-v7-report.json")},
        {"role": "private_loader_receipt", "path": str(selected_root / "private-loader-subprocess-v1.json")},
        {"role": "v5_loader_report", "path": str(selected_root / "portable-raw-to-label-run-report-v5.json")},
        {"role": "python_access_audit", "path": str(selected_root / "portable-python-access-audit-v5.json")},
        {"role": "sealed_overlay", "path": str(target_root / "sealed-overlay-v7.json")},
        {"role": "native_output_root", "path": str(selected_root / "native-v5")},
    ]
    source_bindings = [_stat_binding({"role": "v7_request", "path": str(v7_path),
                                      "bytes": v7_path.stat().st_size,
                                      "mtime_ns": v7_path.stat().st_mtime_ns,
                                      "sha256": sha256_file(v7_path)}, verify_content=False)]
    bridge_path = Path(__file__).resolve()
    source_bindings.append(_stat_binding({"role": "portable_ledger_bridge_v8", "path": str(bridge_path),
                                          "bytes": bridge_path.stat().st_size,
                                          "mtime_ns": bridge_path.stat().st_mtime_ns,
                                          "sha256": sha256_file(bridge_path)}, verify_content=False))
    source_bindings.extend(guard_bindings)
    # The v7 request remains the authority for the complete copy closure.  A
    # bridge source list records every path/expected SHA without reading large
    # content at build time.
    seen = {item["path"] for item in source_bindings}
    for item in v7["source_bindings"]:
        path = str(Path(item["path"]).expanduser().resolve())
        if path in seen:
            continue
        source_bindings.append({"role": f"v7:{item['role']}", "path": path,
                                "bytes": int(item["bytes"]), "mtime_ns": int(item["mtime_ns"]),
                                "sha256": _require_sha(item["sha256"], f"v7:{item['role']}.sha256"),
                                "source_kind": item.get("source_kind", "copy_source"),
                                "content_scope": "v7_target_seal_for_copy_source" if item.get("source_kind") == "copy_source" else "content_sha256"})
        seen.add(path)
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "request_id": attempt_id,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "case_id": "F2_S1_PORTABLE_RAW_TO_LABEL_V7",
        "attempt_id": attempt_id,
        "data_root": str(Path(data_root).expanduser().resolve()),
        "shared_v4_root": str(root),
        "v7_request": {"path": str(v7_path), "sha256": sha256_file(v7_path), "schema": V7_SCHEMA},
        "parent_resource_binding": dict(parent["binding"]),
        "guard_bindings": guard_bindings,
        "source_bindings": source_bindings,
        "input_files": [item["path"] for item in source_bindings],
        "input_hashes": {item["path"]: item["sha256"] for item in source_bindings},
        "reservation": {
            "kind": "cpu",
            "cpu_task_kind": "conversion",
            "cpu_threads": int(v7["resource_request"]["cpu_threads"]),
            "max_wall_seconds": int(v7["resource_request"]["max_wall_seconds"]),
            "cpu_core_seconds": int(v7["resource_request"]["cpu_threads"]) * int(v7["resource_request"]["max_wall_seconds"]),
            "gpu_seconds": 0,
            "new_storage_bytes": required_bytes,
            "storage_filesystem": str(selected_root.parent),
            "same_parent_lease": True,
            "atomic_ledger_lock": "shared v4 runtime ledger_locked",
        },
        "external_storage_scope": {
            "filesystem": str(selected_root.parent),
            "roots": [str(target_root), str(selected_root)],
            "requested_reservation_bytes": required_bytes,
            "tree_bytes_measurement": "recursive regular-file bytes under exactly the two new roots plus listed sidecar artifacts",
            "existing_products_deleted": False,
            "existing_products_moved": False,
            "namespace_must_be_absent_before_reservation": True,
            "accessible_index_path": str(mapping["accessible_index_path"]),
            "expected_artifacts": expected_artifacts,
        },
        "execution": {
            "entrypoint": str(Path(__file__).resolve()),
            "command": [sys.executable, "-B", str(Path(__file__).resolve()), "run", "--request", "<request>", "--io-slot-approved"],
            "v7_engine": str(Path(v7["execution"]["command"][2]).expanduser().resolve()) if len(v7["execution"].get("command", [])) > 2 else None,
            "prevalidation_cost": {"wall_seconds": "measured", "process_and_children_cpu_seconds": "measured", "included_in_same_parent_charge": True},
            "expected_artifacts_gate": True,
            "raw_bi4_hdf5_read": "parent slot only",
            "os_open_audit_required": True,
            "model_invoked": False,
            "cfd_invoked": False,
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "limitations": [
            "The bridge calls the bound v4 check_reservation/ledger_locked interface; it does not create or reset a ledger.",
            "External NVMe tree bytes are charged from measured target/output roots, including listed sidecars; no stat-only claim is promoted.",
            "Native HDF5/BI4 C-open absence still requires parent OS strace/openat evidence.",
            "Raw labels and all QI/QN/QE remain DEVELOPMENT/UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output_path, request)
    return request


def _validate(request: Mapping[str, Any], *, verify_content: bool) -> list[dict[str, Any]]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise BridgeV8Error("unsupported or non-ready v8 bridge request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise BridgeV8Error("v8 bridge must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise BridgeV8Error("v8 bridge cannot invoke model/CFD")
    if request.get("sha256") != canonical_sha(request):
        raise BridgeV8Error("v8 bridge canonical SHA differs")
    guards = request.get("guard_bindings")
    if not isinstance(guards, list) or {item.get("role") for item in guards} != set(V4_GUARD_ROLES):
        raise BridgeV8Error("complete shared v4 guard closure is required")
    sources = request.get("source_bindings")
    if not isinstance(sources, list) or not sources:
        raise BridgeV8Error("source_bindings are required")
    checked = []
    for item in sources:
        if not isinstance(item, Mapping):
            raise BridgeV8Error("source binding is malformed")
        mutable_parent = item.get("source_kind") == "parent"
        stat_item = dict(item)
        if mutable_parent:
            # The shared parent ledger is mutable inside the existing lease;
            # its semantic fields are rechecked by v4 under the same lock.
            stat_item["bytes"] = None
            stat_item["mtime_ns"] = None
        checked.append(_stat_binding(stat_item, verify_content=verify_content and not mutable_parent and item.get("content_scope") != "v7_target_seal_for_copy_source"))
    external = request.get("external_storage_scope")
    if not isinstance(external, Mapping) or not isinstance(external.get("roots"), list) or len(external["roots"]) != 2:
        raise BridgeV8Error("external storage scope is incomplete")
    for root in external["roots"]:
        path = Path(str(root)).expanduser().resolve()
        if not str(path).startswith("/var/tmp/"):
            raise BridgeV8Error(f"external output root is outside /var/tmp: {path}")
        if path.exists():
            raise BridgeV8Error(f"external output namespace already exists: {path}")
    return checked


def _expected_artifacts(scope: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = scope.get("expected_artifacts")
    if not isinstance(values, list) or not values:
        raise BridgeV8Error("expected_artifacts are required")
    return [dict(item) for item in values]


def _artifact_check(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = []
    missing = []
    for item in items:
        path = Path(str(item["path"])).expanduser().resolve()
        exists = path.is_file() if path.suffix else path.is_dir()
        record = {"role": item.get("role"), "path": str(path), "exists": exists}
        if exists and path.is_file():
            record["bytes"] = int(path.stat().st_size)
            record["sha256"] = sha256_file(path)
        result.append(record)
        if not exists:
            missing.append(str(path))
    return {"status": "PASS" if not missing else "MISSING_REQUIRED_ARTIFACTS",
            "items": result, "missing": missing}


def _charge_parent(dispatch: Any, runtime: Any, request: Mapping[str, Any], *,
                   reservation: Mapping[str, Any], actual_bytes: int,
                   cpu_seconds: float, status: str, finished_at: str) -> None:
    data_root = Path(str(request["data_root"])).expanduser().resolve()
    attempt_id = str(request["attempt_id"])
    with runtime.ledger_locked(data_root) as ledger:
        ledger["reservations"] = [row for row in ledger["reservations"] if row.get("id") != attempt_id]
        ledger["charges"].append({
            "id": attempt_id,
            "gpu_seconds": 0.0,
            "cpu_core_seconds": float(cpu_seconds),
            "new_storage_bytes": int(actual_bytes),
            "status": status,
            "finished_at_utc": finished_at,
            "storage_filesystem": str(request["external_storage_scope"]["filesystem"]),
            "accounting_scope": "external_storage_scope_target_and_selected_roots_plus_expected_sidecars",
        })
        for row in ledger.get("attempts", []):
            if row.get("id") == attempt_id:
                row.update(status=status, finished_at_utc=finished_at)


def run(request_path: Path | str, *, io_slot_approved: bool = False) -> dict[str, Any]:
    request_file = _require_file(request_path, "v8 bridge request")
    request = load_json(request_file)
    checked = _validate(request, verify_content=False)
    if not io_slot_approved:
        return {
            "schema": REPORT_SCHEMA,
            "status": "READY_FOR_PARENT_IO_SLOT",
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "source_count": len(checked),
            "execution_boundary": {"ledger_mutated": False, "raw_opened": False, "hdf5_opened": False, "model_invoked": False, "cfd_invoked": False},
            "qualification": copy.deepcopy(UNKNOWN),
        }
    # Recheck every small executable/metadata binding content before the
    # reservation.  Large BI4/HDF5/CSV copy sources are intentionally covered
    # by the v7 post-copy target seal and are excluded from this prehash pass.
    _validate(request, verify_content=True)
    # Import only the exact bound v4 source path declared by the request.
    dispatch_path = next(Path(item["path"]).resolve() for item in request["guard_bindings"] if item["role"] == "shared_dispatch_v4")
    dispatch, runtime = _load_shared_v4(dispatch_path)
    root = Path(request["external_storage_scope"]["filesystem"]).expanduser().resolve()
    if not root.is_dir():
        raise BridgeV8Error(f"external storage filesystem is unavailable: {root}")
    before_fs = _disk_probe(root)
    required = int(request["reservation"]["new_storage_bytes"])
    if before_fs["free_bytes"] < required:
        raise BridgeV8Error("external output filesystem lacks requested reservation headroom")
    preflight_wall_start = time.monotonic()
    preflight_cpu_start = _cpu_seconds()
    # v7 performs its own exact source/stat and v5 semantic checks.  Run its
    # validator here before taking the ledger lock so malformed requests never
    # reserve a parent slot.
    v7_path = Path(request["v7_request"]["path"]).expanduser().resolve()
    v7 = _load_v7(v7_path)
    v7_module_path = Path(str(v7["execution"]["command"][2])).expanduser().resolve()
    v7_binding = next((item for item in request["source_bindings"]
                       if item.get("role") == "v7:portable_orchestrator_v7"), None)
    if not isinstance(v7_binding, Mapping) or Path(str(v7_binding["path"])).resolve() != v7_module_path:
        raise BridgeV8Error("v7 engine path is not the bound relocated orchestrator source")
    v7_spec = importlib.util.spec_from_file_location("_ds02_v7_engine_for_bridge", v7_module_path)
    if v7_spec is None or v7_spec.loader is None:
        raise BridgeV8Error(f"cannot import v7 engine: {v7_module_path}")
    v7_module = importlib.util.module_from_spec(v7_spec)
    v7_spec.loader.exec_module(v7_module)
    v7_module._validate_request(v7, verify_metadata_content=False)
    preflight_wall = time.monotonic() - preflight_wall_start
    preflight_cpu = _cpu_seconds() - preflight_cpu_start
    data_root = Path(request["data_root"]).expanduser().resolve()
    attempt_id = str(request["attempt_id"])
    reservation = dict(request["reservation"])
    reservation.update({"id": attempt_id, "reserved_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "launcher_pid": os.getpid(), "host": os.uname().nodename})
    registered = False
    started = time.monotonic()
    cpu_start = _cpu_seconds()
    result: dict[str, Any]
    status = "failed"
    error: str | None = None
    try:
        # This is the same v4 lock and reservation function used by the shared
        # launcher.  No ledger path or limits are replaced by the bridge.
        with runtime.ledger_locked(data_root) as ledger:
            dispatch.check_reservation(
                ledger, reservation, runtime.tree_bytes(data_root),
                available_bytes=os.statvfs(data_root).f_bavail * os.statvfs(data_root).f_frsize,
            )
            ledger["reservations"].append(reservation)
            ledger["attempts"].append({"id": attempt_id, "kind": reservation["kind"],
                                       "status": "reserved", "started_at_utc": reservation["reserved_at_utc"]})
            registered = True
        result = v7_module.run(v7_path, io_slot_approved=True, verify_metadata_content=True)
        status = "completed" if str(result.get("status", "")).startswith("COMPLETE") else "failed"
    except BaseException as exc:
        result = {"status": "BRIDGE_EXECUTION_FAILED", "error": f"{type(exc).__name__}: {exc}"}
        error = result["error"]
    finally:
        cpu_seconds = max(0.0, _cpu_seconds() - cpu_start + preflight_cpu)
        scope = request["external_storage_scope"]
        roots = [Path(str(value)).expanduser().resolve() for value in scope["roots"]]
        artifact_check = _artifact_check(_expected_artifacts(scope))
        actual_bytes = sum(_tree_bytes(path) for path in roots)
        sidecars = [Path(str(item["path"])).expanduser().resolve() for item in scope["expected_artifacts"]
                    if Path(str(item["path"])).expanduser().resolve().is_file() and
                    not any(Path(str(item["path"])).expanduser().resolve() == root or root in Path(str(item["path"])).expanduser().resolve().parents for root in roots)]
        actual_bytes += sum(int(path.stat().st_size) for path in sidecars)
        after_fs = _disk_probe(root)
        if artifact_check["status"] != "PASS":
            status = "failed"
            if error is None:
                error = "required output artifact is missing"
        if actual_bytes > required:
            status = "failed"
            if error is None:
                error = "measured external output exceeds reservation"
        finished = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if registered:
            _charge_parent(dispatch, runtime, request, reservation=reservation,
                           actual_bytes=actual_bytes, cpu_seconds=cpu_seconds,
                           status=status, finished_at=finished)
        receipt = {
            "schema": REPORT_SCHEMA,
            "status": "COMPLETE_DEVELOPMENT_UNKNOWN" if status == "completed" else "FAILED_PARENT_BRIDGED_REPLAY",
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "attempt_id": attempt_id,
            "parent_ledger": {"path": str(request["parent_resource_binding"]["path"]),
                               "same_parent_lock": True, "reservation_registered": registered,
                               "ledger_reset": False},
            "prevalidation": {"wall_seconds": preflight_wall, "process_and_children_cpu_seconds": preflight_cpu,
                               "included_in_same_parent_charge": True},
            "execution": {"wall_seconds": time.monotonic() - started,
                           "process_and_children_cpu_seconds": cpu_seconds,
                           "result": result, "error": error},
            "filesystem": {"before": before_fs, "after": after_fs,
                           "scope": [str(path) for path in roots],
                           "measured_tree_bytes": actual_bytes,
                           "reserved_bytes": required,
                           "artifact_check": artifact_check},
            "model_invoked": False,
            "cfd_invoked": False,
            "os_open_audit_required": True,
            "original_path_fallback": "FORBIDDEN",
            "qualification": copy.deepcopy(UNKNOWN),
        }
        receipt["sha256"] = canonical_sha(receipt)
        receipt_path = data_root / "families" / "F2" / "F2_S1_PORTABLE_RAW_TO_LABEL_V8" / attempt_id / "execution-receipt.json"
        write_new(receipt_path, receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v7-request", type=Path, required=True)
    build.add_argument("--shared-root", type=Path, required=True)
    build.add_argument("--data-root", type=Path, default=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02"))
    build.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v7_request, args.output, shared_root=args.shared_root,
                                  data_root=args.data_root)
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved)
    except (BridgeV8Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": value.get("schema", SCHEMA), "status": value.get("status"),
                      "qualification": value.get("qualification", UNKNOWN)}, sort_keys=True,
                     default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
