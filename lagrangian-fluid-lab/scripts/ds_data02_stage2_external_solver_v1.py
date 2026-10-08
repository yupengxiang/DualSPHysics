#!/usr/bin/env python3
"""Guarded external-filesystem solver runner for DS-DATA-02 Stage2.

This is an additive resource/accounting entrypoint.  It makes the intended
NVMe product scope executable without changing the existing v6/v7 runners:

* one existing DS-DATA-02 parent ledger and lock are used;
* Home receipt bytes and external product bytes are separate fields, while
  their exact sum is charged to the parent ``new_storage_bytes`` budget;
* qualification/production work has an explicit GPU UUID lease under the
  parent data root; an arbitrary CUDA device or a second ledger is rejected;
* Home and external ``statvfs`` floors are checked independently;
* the output namespace must be new and symlink-free; no alternate data root or
  symlink bypass is accepted.

``preflight`` is metadata/stat-only and does not mutate the ledger or open
HDF5/BI4/CSV payloads.  ``run --io-slot-approved`` is a parent-scheduled
operation.  It is suitable for a manufactured child in tests, but this
module does not itself select a scientific case or grant QI/QN/QE.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import signal
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, Iterator, Mapping, Sequence


SCHEMA = "ds02.stage2.external-solver-request.v1"
REPORT_SCHEMA = "ds02.stage2.external-solver-report.v1"
RUNTIME_ROLE = "shared_runtime_v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/:")
IDENTITY_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
CPU_KINDS = {"qualification", "production"}
PR_SET_PDEATHSIG = 1


class ExternalSolverError(RuntimeError):
    """The external solver resource/source contract is unsafe."""


class ExternalSolverDeadline(ExternalSolverError):
    pass


class ExternalSolverCancelled(ExternalSolverError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        raise ExternalSolverError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ExternalSolverError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ExternalSolverError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ExternalSolverError(f"{name} must be a lowercase SHA-256")
    return value


def _positive_int(value: Any, name: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExternalSolverError(f"{name} must be an integer")
    if value < (0 if allow_zero else 1):
        raise ExternalSolverError(f"{name} must be positive")
    return value


def _finite_positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ExternalSolverError(f"{name} must be finite and positive")
    return float(value)


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _no_symlink_components(path: Path, *, allow_missing_leaf: bool = True) -> None:
    target = path.expanduser()
    current = target if target.exists() else target.parent
    missing: list[str] = []
    while not current.exists() and current != current.parent:
        missing.append(current.name)
        current = current.parent
    if current.is_symlink():
        raise ExternalSolverError(f"symlink filesystem component is forbidden: {current}")
    for component in reversed(missing):
        current = current / component
        if current.is_symlink():
            raise ExternalSolverError(f"symlink output component is forbidden: {current}")
    if target.exists() and target.is_symlink():
        raise ExternalSolverError(f"symlink output path is forbidden: {target}")
    if not allow_missing_leaf and not target.exists():
        raise ExternalSolverError(f"required path is missing: {target}")


def _disk_probe(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_dir():
        raise ExternalSolverError(f"filesystem anchor is not a directory: {target}")
    stat = os.statvfs(target)
    return {"path": str(target), "free_bytes": int(stat.f_bavail * stat.f_frsize),
            "total_bytes": int(stat.f_blocks * stat.f_frsize),
            "device_id": int(target.stat().st_dev), "probe": "READ_ONLY_STATVFS"}


def _tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ExternalSolverError(f"symlink output file is forbidden: {path}")
            try:
                total += int(path.stat().st_size)
            except FileNotFoundError:
                raise ExternalSolverError(f"output disappeared during accounting: {path}")
    return total


def _load_runtime(request: Mapping[str, Any]):
    binding = request.get("runtime_binding")
    if not isinstance(binding, Mapping):
        raise ExternalSolverError("shared runtime binding is required")
    path = Path(str(binding.get("path"))).expanduser().resolve()
    if not path.is_file():
        raise ExternalSolverError(f"shared runtime is missing: {path}")
    spec = importlib.util.spec_from_file_location("ds02_external_solver_shared_runtime", path)
    if spec is None or spec.loader is None:
        raise ExternalSolverError(f"cannot import shared runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_parent(request: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    binding = request.get("parent_resource_binding")
    if not isinstance(binding, Mapping):
        raise ExternalSolverError("parent_resource_binding is required")
    ledger_path = Path(str(binding.get("ledger_path", ""))).expanduser().resolve()
    if not ledger_path.is_file():
        raise ExternalSolverError(f"parent ledger is missing: {ledger_path}")
    ledger = load_json(ledger_path)
    if ledger.get("schema") != "ds02.resource-ledger.v1" or ledger.get("campaign_id") != "DS-DATA-02":
        raise ExternalSolverError("unexpected parent ledger schema/campaign")
    limits = ledger.get("limits")
    if not isinstance(limits, Mapping):
        raise ExternalSolverError("parent ledger limits are missing")
    for key in ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes", "qualification_attempts",
                "production_attempts", "home_min_free_bytes", "home_path"):
        if key not in limits:
            raise ExternalSolverError(f"parent ledger limit is missing: {key}")
    data_root = Path(str(binding.get("data_root", ""))).expanduser().resolve()
    if data_root != ledger_path.parent.parent:
        raise ExternalSolverError("request data_root is not the existing parent ledger root")
    if binding.get("no_new_data_root") is not True or binding.get("ledger_reset") is not False:
        raise ExternalSolverError("new data root or ledger reset is forbidden")
    expected_deadline = binding.get("deadline_utc")
    if expected_deadline is not None and expected_deadline != ledger.get("deadline_utc"):
        raise ExternalSolverError("parent deadline changed")
    expected_campaign = binding.get("campaign_id")
    if expected_campaign is not None and expected_campaign != ledger.get("campaign_id"):
        raise ExternalSolverError("parent campaign changed")
    return data_root, ledger


def _validate_files(request: Mapping[str, Any], *, verify_content: bool) -> list[dict[str, Any]]:
    values = request.get("input_files")
    hashes = request.get("input_sha256")
    if not isinstance(values, list) or not values:
        raise ExternalSolverError("input_files must be a non-empty list")
    if not isinstance(hashes, Mapping):
        raise ExternalSolverError("input_sha256 is required")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        path = Path(str(value)).expanduser().resolve()
        if str(path) in seen:
            raise ExternalSolverError(f"duplicate input file binding: {path}")
        seen.add(str(path))
        if not path.is_file():
            raise ExternalSolverError(f"input file is missing: {path}")
        expected = _require_sha(hashes.get(str(path)), str(path))
        stat = path.stat()
        item = {"path": str(path), "bytes": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns), "sha256": expected}
        scope = request.get("input_content_scope", {}).get(str(path), "post_reservation_hash")
        item["content_scope"] = scope
        if verify_content and scope != "stat_only" and sha256_file(path) != expected:
            raise ExternalSolverError(f"input content SHA differs: {path}")
        result.append(item)
    return result


def _validate_parent_binding(request: Mapping[str, Any], data_root: Path, ledger: Mapping[str, Any]) -> None:
    binding = request["parent_resource_binding"]
    checkpoint = binding.get("checkpoint_path")
    if checkpoint:
        checkpoint_path = Path(str(checkpoint)).expanduser().resolve()
        if not checkpoint_path.is_file():
            raise ExternalSolverError(f"parent checkpoint is missing: {checkpoint_path}")
        expected = binding.get("checkpoint_sha256")
        if expected is not None and sha256_file(checkpoint_path) != _require_sha(expected, "checkpoint_sha256"):
            raise ExternalSolverError("parent checkpoint SHA differs")


def _validate_storage_scope(request: Mapping[str, Any], data_root: Path, ledger: Mapping[str, Any]) -> dict[str, Any]:
    scope = request.get("storage_scope")
    if not isinstance(scope, Mapping):
        raise ExternalSolverError("storage_scope is required")
    external_raw = Path(str(scope.get("external_filesystem", ""))).expanduser()
    output_raw = Path(str(scope.get("output_root", ""))).expanduser()
    _no_symlink_components(external_raw, allow_missing_leaf=False)
    _no_symlink_components(output_raw)
    external_fs = external_raw.resolve()
    output_root = output_raw.resolve()
    home = Path(str(ledger["limits"]["home_path"])).expanduser().resolve()
    if not external_fs.is_dir():
        raise ExternalSolverError(f"external filesystem is unavailable: {external_fs}")
    if not _under(output_root, external_fs) or output_root == external_fs:
        raise ExternalSolverError("output_root must be a new child of external_filesystem")
    if _under(output_root, data_root) or _under(external_fs, data_root):
        raise ExternalSolverError("external output must not be inside the parent data root")
    if output_root.exists():
        raise ExternalSolverError(f"output namespace already exists: {output_root}")
    if int(external_fs.stat().st_dev) == int(home.stat().st_dev):
        raise ExternalSolverError("external solver output must be on a distinct filesystem device")
    external_reserve = _positive_int(scope.get("external_product_reserved_bytes"),
                                      "external_product_reserved_bytes")
    home_reserve = _positive_int(scope.get("home_receipt_reserved_bytes"),
                                 "home_receipt_reserved_bytes")
    total = _positive_int(scope.get("new_storage_bytes"), "new_storage_bytes")
    if total != external_reserve + home_reserve:
        raise ExternalSolverError("new_storage_bytes must equal external plus Home receipt reserves")
    home_floor = _positive_int(scope.get("home_min_free_bytes"), "home_min_free_bytes")
    external_floor = _positive_int(scope.get("external_min_free_bytes", 1), "external_min_free_bytes")
    home_probe = _disk_probe(home)
    external_probe = _disk_probe(external_fs)
    return {"home": home_probe, "external": external_probe,
            "home_floor_bytes": home_floor, "external_floor_bytes": external_floor,
            "external_reserved_bytes": external_reserve, "home_reserved_bytes": home_reserve,
            "new_storage_bytes": total}


def _validate_request(request: Mapping[str, Any], *, verify_content: bool = False) -> dict[str, Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ExternalSolverError("unsupported or non-ready external solver request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise ExternalSolverError("request must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ExternalSolverError("model/CFD invocation is forbidden")
    if request.get("sha256") != canonical_sha(request):
        raise ExternalSolverError("request canonical SHA differs")
    runtime_binding = request.get("runtime_binding")
    if not isinstance(runtime_binding, Mapping):
        raise ExternalSolverError("runtime_binding is required")
    runtime_path = Path(str(runtime_binding.get("path", ""))).expanduser().resolve()
    if not runtime_path.is_file():
        raise ExternalSolverError(f"shared runtime is missing: {runtime_path}")
    runtime_sha = _require_sha(runtime_binding.get("sha256"), "runtime_binding.sha256")
    if verify_content and sha256_file(runtime_path) != runtime_sha:
        raise ExternalSolverError("shared runtime content SHA differs")
    for key in ("family_id", "case_id", "attempt_id"):
        value = request.get(key)
        if not isinstance(value, str) or not value or any(char not in IDENTITY_SAFE for char in value):
            raise ExternalSolverError(f"unsafe {key}")
    kind = request.get("kind")
    if kind not in CPU_KINDS:
        raise ExternalSolverError("external solver kind must be qualification or production")
    if kind == "production":
        approval = request.get("scientific_approval")
        if not isinstance(approval, Mapping) or approval.get("status") != "PARENT_APPROVED_EXPLICIT_CASE":
            raise ExternalSolverError("production requires an explicit parent scientific approval binding")
    _positive_int(request.get("cpu_threads"), "cpu_threads")
    _positive_int(request.get("estimated_peak_gpu_mib"), "estimated_peak_gpu_mib")
    max_wall = _finite_positive(request.get("max_wall_seconds"), "max_wall_seconds")
    command = request.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
        raise ExternalSolverError("command must be an argv list")
    cwd = Path(str(request.get("cwd", ""))).expanduser().resolve()
    if not cwd.is_dir():
        raise ExternalSolverError("command cwd is missing")
    gpu = request.get("gpu")
    if not isinstance(gpu, Mapping) or gpu.get("required") is not True:
        raise ExternalSolverError("qualification/production requires an explicit GPU lease")
    if gpu.get("lease_root") != str((_load_parent(request)[0] / "leases").resolve()):
        raise ExternalSolverError("GPU lease_root must be the existing parent data-root leases directory")
    if request.get("execution", {}).get("manufactured_only") is not True:
        binary = Path(command[0]).expanduser().resolve()
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ExternalSolverError("approved solver executable is missing or not executable")
    data_root, ledger = _load_parent(request)
    _validate_parent_binding(request, data_root, ledger)
    files = _validate_files(request, verify_content=verify_content)
    storage = _validate_storage_scope(request, data_root, ledger)
    return {"data_root": data_root, "ledger": ledger, "files": files, "storage": storage,
            "max_wall_seconds": max_wall}


def _reservation_totals(ledger: Mapping[str, Any]) -> dict[str, float]:
    totals = {"gpu_seconds": 0.0, "cpu_core_seconds": 0.0, "new_storage_bytes": 0.0}
    for row in list(ledger.get("charges", [])) + list(ledger.get("reservations", [])):
        if not isinstance(row, Mapping):
            continue
        for key in totals:
            totals[key] += float(row.get(key, 0) or 0)
    return totals


def _reserved_fs_bytes(ledger: Mapping[str, Any]) -> tuple[int, int]:
    home = external = 0
    for row in ledger.get("reservations", []):
        if not isinstance(row, Mapping):
            continue
        home += int(row.get("home_storage_bytes", row.get("new_storage_bytes", 0)) or 0)
        external += int(row.get("external_storage_bytes", 0) or 0)
    return home, external


def _check_two_fs_reservation(ledger: Mapping[str, Any], reservation: Mapping[str, Any],
                              *, home_free: int, external_free: int,
                              home_floor: int, external_floor: int) -> None:
    if datetime.now(timezone.utc) >= datetime.fromisoformat(str(ledger["deadline_utc"])):
        raise ExternalSolverError("parent campaign deadline reached")
    attempt = str(reservation["id"])
    if any(row.get("id") == attempt for row in ledger.get("attempts", [])):
        raise ExternalSolverError("attempt_id already exists; no restart/overwrite")
    totals = _reservation_totals(ledger)
    for key in ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes"):
        if totals[key] + float(reservation[key]) > float(ledger["limits"][key]):
            raise ExternalSolverError(f"parent budget exhausted: {key}")
    existing_home, existing_external = _reserved_fs_bytes(ledger)
    if home_free - existing_home - int(reservation["home_storage_bytes"]) < home_floor:
        raise ExternalSolverError("Home free-space floor would be crossed")
    if external_free - existing_external - int(reservation["external_storage_bytes"]) < external_floor:
        raise ExternalSolverError("external filesystem floor would be crossed")
    kind = str(reservation["kind"])
    cap_key = f"{kind}_attempts"
    if sum(1 for row in ledger.get("attempts", []) if row.get("kind") == kind) >= int(ledger["limits"][cap_key]):
        raise ExternalSolverError(f"parent attempt cap reached: {kind}")
    if sum(1 for row in ledger.get("reservations", []) if row.get("kind") in CPU_KINDS) >= 4:
        raise ExternalSolverError("shared solver concurrency reached")


def _gpu_snapshot_and_select(runtime: Any, request: Mapping[str, Any], data_root: Path) -> dict[str, Any]:
    snapshot = runtime.inventory()
    gpu = request["gpu"]
    requested = gpu.get("gpu_uuid")
    leases_root = data_root / "leases"
    leases_root.mkdir(parents=True, exist_ok=True)
    leased: set[str] = set()
    for path in leases_root.glob("*.json"):
        try:
            value = load_json(path)
        except ExternalSolverError:
            continue
        value_uuid = value.get("uuid")
        if isinstance(value_uuid, str):
            leased.add(value_uuid)
    if requested:
        device = next((row for row in snapshot.get("devices", []) if row.get("uuid") == requested), None)
        if device is None:
            raise ExternalSolverError("requested GPU UUID is not in the parent inventory")
        if requested in leased or any(row.get("uuid") == requested for row in snapshot.get("processes", [])):
            raise ExternalSolverError("requested GPU UUID is busy or already leased")
        return {"device": device, "snapshot": snapshot, "leased_uuids": sorted(leased)}
    device = runtime.choose_gpu(snapshot, leased, int(request["estimated_peak_gpu_mib"]))
    return {"device": device, "snapshot": snapshot, "leased_uuids": sorted(leased)}


@contextmanager
def _gpu_lease(data_root: Path, attempt: str, device: Mapping[str, Any], parent_pid: int) -> Iterator[Path]:
    leases_root = data_root / "leases"
    leases_root.mkdir(parents=True, exist_ok=True)
    uuid = str(device.get("uuid", ""))
    if not uuid or any(char not in SAFE for char in uuid):
        raise ExternalSolverError("GPU UUID is unsafe")
    path = leases_root / (uuid + ".json")
    if path.exists():
        raise ExternalSolverError(f"GPU UUID lease already exists: {path}")
    lease = {"schema": "ds02.gpu-lease.v1", "uuid": uuid,
             "device_index": device.get("index"), "attempt_id": attempt,
             "launcher_pid": os.getpid(), "parent_pid": parent_pid,
             "host": socket.gethostname(), "heartbeat_utc": now()}
    with path.open("x", encoding="utf-8") as stream:
        json.dump(lease, stream, sort_keys=True)
        stream.write("\n")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform != "darwin" else value


def _stop_child(proc: subprocess.Popen[str]) -> bool:
    if proc.poll() is not None:
        return True
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return True
    deadline = time.monotonic() + 0.5
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        return False
    return True


def _child_parent_death(parent_pid: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot install solver parent-death signal")
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGTERM)


def _write_receipt_fixed_point(path: Path, receipt: dict[str, Any], external_bytes: int) -> int:
    predicted = external_bytes + 1024
    for _ in range(128):
        receipt["filesystem"]["home_receipt_bytes"] = max(0, predicted - external_bytes)
        receipt["filesystem"]["measured_total_bytes"] = predicted
        receipt["sha256"] = canonical_sha(receipt)
        encoded = (json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False, default=str) + "\n").encode()
        next_total = external_bytes + len(encoded)
        if next_total == predicted:
            if path.exists():
                raise ExternalSolverError(f"receipt path already exists: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encoded)
            return len(encoded)
        predicted = next_total
    raise ExternalSolverError("receipt byte fixed point did not converge")


def _charge(runtime: Any, data_root: Path, attempt: str, reservation: Mapping[str, Any], *,
            external_bytes: int, home_bytes: int, cpu_seconds: float,
            gpu_seconds: float, status: str) -> None:
    # Use the same parent lock, but retain the two filesystem dimensions in
    # addition to the exact total understood by the legacy ledger.
    with runtime.ledger_locked(data_root) as ledger:
        ledger["reservations"] = [row for row in ledger.get("reservations", [])
                                   if row.get("id") != attempt]
        total = int(external_bytes + home_bytes)
        ledger.setdefault("charges", []).append({
            "id": attempt, "gpu_seconds": float(gpu_seconds),
            "cpu_core_seconds": float(cpu_seconds), "new_storage_bytes": total,
            "external_storage_bytes": int(external_bytes),
            "home_storage_bytes": int(home_bytes),
            "storage_filesystems": [str(data_root), str(reservation["external_filesystem"])],
            "status": status, "finished_at_utc": now(),
            "accounting_scope": "parent_ledger_home_receipt_plus_external_solver_product",
        })
        for row in ledger.get("attempts", []):
            if row.get("id") == attempt:
                row.update(status=status, finished_at_utc=now())


def _bind_command(request: Mapping[str, Any], output: Path, lease_device: Mapping[str, Any] | None) -> tuple[list[str], dict[str, str]]:
    command = [arg.replace("{output_root}", str(output)).replace("{attempt_root}", str(output))
               for arg in request["command"]]
    env = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = str(request["cpu_threads"])
    if lease_device is not None:
        if request.get("execution", {}).get("manufactured_only") is not True:
            command = [arg for arg in command if not arg.startswith("-gpu")]
            command.insert(1, "-gpu:0")
        env["CUDA_VISIBLE_DEVICES"] = str(lease_device["uuid"])
    return command, env


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    if not io_slot_approved:
        checked = _validate_request(request, verify_content=False)
        return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                "request_sha256": sha256_file(request_file), "input_count": len(checked["files"]),
                "ledger_mutated": False, "raw_opened": False, "hdf5_opened": False,
                "model_invoked": False, "cfd_invoked": False, "qualification": copy.deepcopy(UNKNOWN)}
    checked = _validate_request(request, verify_content=False)
    data_root = checked["data_root"]
    storage = checked["storage"]
    scope = request["storage_scope"]
    output = Path(str(scope["output_root"])).expanduser().resolve()
    receipt_path = data_root / "families" / request["family_id"] / request["case_id"] / request["attempt_id"] / "execution-receipt.json"
    attempt = f"{request['family_id']}/{request['case_id']}/{request['attempt_id']}"
    if receipt_path.exists() or output.exists():
        raise ExternalSolverError("attempt output or receipt already exists")
    runtime = _load_runtime(request)
    max_wall = float(request["max_wall_seconds"])
    if parent_pid is not None and os.getppid() != int(parent_pid):
        raise ExternalSolverCancelled("supervising parent already exited")
    gpu_info = _gpu_snapshot_and_select(runtime, request, data_root)
    device = gpu_info["device"]
    reservation = {
        "id": attempt, "kind": request["kind"], "cpu_threads": int(request["cpu_threads"]),
        "cpu_core_seconds": int(request["cpu_threads"]) * max_wall,
        "gpu_seconds": max_wall, "new_storage_bytes": int(scope["new_storage_bytes"]),
        "home_storage_bytes": int(scope["home_receipt_reserved_bytes"]),
        "external_storage_bytes": int(scope["external_product_reserved_bytes"]),
        "external_filesystem": str(scope["external_filesystem"]),
        "reserved_at_utc": now(), "launcher_pid": os.getpid(),
        "host": socket.gethostname(), "gpu_uuid": str(device["uuid"]),
    }
    home_probe = _disk_probe(Path(str(storage["home"]["path"])))
    external_probe = _disk_probe(Path(str(storage["external"]["path"])))
    registered = False
    process: subprocess.Popen[str] | None = None
    status = "failed"
    termination: str | None = None
    returncode: int | None = None
    lease_path: Path | None = None
    stdout = ""
    stderr = ""
    try:
        # The shared v2 lock is the parent lock.  We intentionally do not call
        # v2.check_reservation because its Home policy subtracts external
        # product bytes from the Home floor; the two-FS check above preserves
        # both dimensions while retaining the same ledger schema/lock.
        # The bound runtime's ledger_locked is the existing parent lock/API;
        # it is not a new ledger implementation or a second data root.
        with runtime.ledger_locked(data_root) as ledger:
            live_home = _disk_probe(Path(str(ledger["limits"]["home_path"])))
            live_external = _disk_probe(Path(str(scope["external_filesystem"])))
            _check_two_fs_reservation(ledger, reservation,
                                       home_free=live_home["free_bytes"],
                                       external_free=live_external["free_bytes"],
                                       home_floor=int(scope["home_min_free_bytes"]),
                                       external_floor=int(scope["external_min_free_bytes"]))
            lease_path = data_root / "leases" / (str(device["uuid"]) + ".json")
            if lease_path.exists():
                raise ExternalSolverError("GPU UUID lease appeared during reservation")
            lease_path.parent.mkdir(parents=True, exist_ok=True)
            with lease_path.open("x", encoding="utf-8") as stream:
                json.dump({"schema": "ds02.gpu-lease.v1", "uuid": device["uuid"],
                           "device_index": device.get("index"), "attempt_id": attempt,
                           "launcher_pid": os.getpid(), "parent_pid": parent_pid,
                           "heartbeat_utc": now()}, stream, sort_keys=True)
                stream.write("\n")
            ledger.setdefault("reservations", []).append(reservation)
            ledger.setdefault("attempts", []).append({"id": attempt, "kind": request["kind"],
                                                       "status": "reserved", "started_at_utc": now()})
            registered = True
        # Content verification starts after parent reservation.  This is the
        # only place this runner may hash the source/runtime list; HDF5/BI4
        # are opened only by the explicitly bound solver command.
        _validate_request(request, verify_content=True)
        output.mkdir(parents=True, exist_ok=False)
        command, env = _bind_command(request, output, device)
        if parent_pid is not None:
            env["DS02_PARENT_PID"] = str(parent_pid)
        launcher_pid = os.getpid()
        log_path = output / "stdout.log"
        with log_path.open("x", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=str(Path(request["cwd"]).expanduser().resolve()),
                                       env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True,
                                       preexec_fn=(lambda: _child_parent_death(launcher_pid))
                                       if parent_pid is not None else None)
            deadline = time.monotonic() + max_wall
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    termination = "wall_deadline"
                    _stop_child(process)
                    break
                if parent_pid is not None and os.getppid() != int(parent_pid):
                    termination = "parent_exit"
                    _stop_child(process)
                    break
                time.sleep(0.05)
            returncode = process.wait(timeout=2) if process.poll() is None else process.returncode
        status = "completed" if termination is None and returncode == 0 else "failed"
        if status != "completed" and termination is None:
            termination = f"solver_returncode_{returncode}"
    except (ExternalSolverDeadline, ExternalSolverCancelled) as error:
        status = "failed"
        termination = str(error)
        if process is not None:
            _stop_child(process)
    except BaseException as error:
        status = "failed"
        termination = f"{type(error).__name__}: {error}"
        if process is not None:
            _stop_child(process)
    finally:
        external_bytes = _tree_bytes(output) if output.exists() else 0
        receipt = {
            "schema": REPORT_SCHEMA, "status": "COMPLETED_DEVELOPMENT_UNKNOWN" if status == "completed" else "FAILED_EXTERNAL_SOLVER",
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "attempt_id": attempt,
            "parent_ledger": {"path": str(data_root / "runtime/resource-ledger.json"),
                               "same_parent_lock": True, "reservation_registered": registered,
                               "ledger_reset": False},
            "gpu": {"uuid": device.get("uuid"), "index": device.get("index"),
                    "lease_path": str(lease_path) if lease_path else None,
                    "lease_released_after_charge": True},
            "filesystem": {"home_path": str(storage["home"]["path"]),
                            "external_path": str(storage["external"]["path"]),
                            "output_root": str(output), "external_product_bytes": external_bytes,
                            "home_receipt_bytes": 0, "measured_total_bytes": 0,
                            "reserved_external_product_bytes": int(scope["external_product_reserved_bytes"]),
                            "reserved_home_receipt_bytes": int(scope["home_receipt_reserved_bytes"]),
                            "two_filesystem_preflight": storage},
            "execution": {"returncode": returncode, "termination": termination,
                           "wall_seconds": time.monotonic() - entry_wall,
                           "cpu_core_seconds": max(0.0, _cpu_seconds() - entry_cpu),
                           "max_rss_observed_bytes": _max_rss_bytes(),
                           "command": request.get("command"), "model_invoked": False,
                           "cfd_invoked": False},
            "source_validation": {"after_reservation": True, "content_verified": False},
            "qualification": copy.deepcopy(UNKNOWN),
            "original_path_fallback": "FORBIDDEN",
        }
        home_bytes = 0
        try:
            if registered:
                home_bytes = _write_receipt_fixed_point(receipt_path, receipt, external_bytes)
                receipt["filesystem"]["home_receipt_bytes"] = home_bytes
                receipt["filesystem"]["measured_total_bytes"] = external_bytes + home_bytes
                receipt["source_validation"]["content_verified"] = True
        except BaseException as error:
            status = "failed"
            receipt["execution"]["termination"] = f"receipt_finalization: {type(error).__name__}: {error}"
        if registered:
            try:
                _charge(runtime, data_root, attempt, {"external_filesystem": scope["external_filesystem"]},
                        external_bytes=external_bytes, home_bytes=home_bytes,
                        cpu_seconds=max(0.0, _cpu_seconds() - entry_cpu),
                        gpu_seconds=max(0.0, min(max_wall, time.monotonic() - entry_wall)),
                        status=status)
            finally:
                if lease_path is not None:
                    lease_path.unlink(missing_ok=True)
    return {"schema": REPORT_SCHEMA, "status": receipt["status"],
            "attempt_id": attempt, "output_root": str(output),
            "receipt_path": str(receipt_path), "terminal_charge_written": registered,
            "external_product_bytes": external_bytes, "home_receipt_bytes": home_bytes,
            "model_invoked": False, "cfd_invoked": False, "qualification": copy.deepcopy(UNKNOWN),
            "termination": termination}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "run"):
        p = sub.add_parser(name)
        p.add_argument("--request", type=Path, required=True)
        p.add_argument("--io-slot-approved", action="store_true")
        p.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            value = run(args.request, io_slot_approved=False, parent_pid=args.parent_pid)
            code = 0
        else:
            if not args.io_slot_approved:
                raise ExternalSolverError("approved solver run requires --io-slot-approved")
            value = run(args.request, io_slot_approved=True, parent_pid=args.parent_pid)
            code = 0 if str(value["status"]).startswith("COMPLETED_") else 2
    except (ExternalSolverError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
