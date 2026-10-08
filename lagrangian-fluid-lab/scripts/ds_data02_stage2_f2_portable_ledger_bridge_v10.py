#!/usr/bin/env python3
"""Parent-lease bridge for the F2 portable v7 replay (forward v10).

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
filesystem checks.  Approved execution installs an entry-to-finalization
wall timer, catches parent cancellation, and gives the nested loader its own
process group; the parent must still supply the approved slot and an OS
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
import signal
import shutil
import subprocess
import sys
import time
import types
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-portable-ledger-bridge-request.v10"
REPORT_SCHEMA = "ds02.stage2.f2-portable-ledger-bridge-report.v10"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
V7_SCHEMA = "ds02.stage2.f2-portable-orchestration-request.v7"
V6_GUARD_ROLES = (
    "shared_dispatch_v6",
    "shared_strict_dispatch_v6",
    "shared_runtime_v6",
    "shared_runtime_v2",
)


class BridgeV10Error(RuntimeError):
    """Raised when parent reservation or external storage accounting is unsafe."""


class BridgeDeadlineExceeded(BridgeV10Error):
    """Raised when an approved bridge phase reaches its parent wall deadline."""


class BridgeCancelled(BridgeV10Error):
    """Raised when the supervising parent asks this bridge to stop."""


_ACTIVE_DEADLINE: "_Deadline | None" = None


class _Deadline:
    def __init__(self, seconds: float):
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            raise BridgeV10Error("max_wall_seconds must be positive")
        self.started = time.monotonic()
        self.seconds = float(seconds)
        self.deadline = self.started + self.seconds

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def check(self, phase: str) -> None:
        if self.remaining() <= 0:
            raise BridgeDeadlineExceeded(f"bridge wall deadline exceeded during {phase}")


def _terminate_child_group(pid: int) -> None:
    """Terminate only a child process group created by this bridge."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        # Never spend a fixed five-second grace period after the bridge's
        # deadline has fired.  A timeout must remain a hard wall: give a
        # cooperative loader at most a short grace interval, capped by the
        # active bridge deadline, then kill only this bridge-created group.
        grace_deadline = time.monotonic() + 0.25
        if _ACTIVE_DEADLINE is not None:
            grace_deadline = min(grace_deadline, _ACTIVE_DEADLINE.deadline)
        while time.monotonic() < grace_deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return


def _bounded_subprocess_run(command, *, cwd=None, env=None, check=False,
                            capture_output=False, text=False, **kwargs):
    """Replacement for v7's subprocess.run with a deadline and child group."""
    deadline = _ACTIVE_DEADLINE
    if deadline is None:
        raise BridgeV10Error("bounded subprocess called without an active deadline")
    stdout = subprocess.PIPE if capture_output else kwargs.pop("stdout", None)
    stderr = subprocess.PIPE if capture_output else kwargs.pop("stderr", None)
    child = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                             text=text, start_new_session=True, **kwargs)
    try:
        out, err = child.communicate(timeout=deadline.remaining())
    except subprocess.TimeoutExpired as error:
        _terminate_child_group(child.pid)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_child_group(child.pid)
            child.wait()
        raise BridgeDeadlineExceeded("bridge wall deadline exceeded during nested loader") from error
    except BaseException:
        _terminate_child_group(child.pid)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_child_group(child.pid)
            child.wait()
        raise
    completed = subprocess.CompletedProcess(command, child.returncode, out, err)
    if check and child.returncode:
        raise subprocess.CalledProcessError(child.returncode, command, output=out, stderr=err)
    return completed


def _install_phase_guards(seconds: float):
    """Install an entry-to-finalization timer and parent cancellation handlers."""
    previous = {
        signal.SIGALRM: signal.getsignal(signal.SIGALRM),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }

    def alarm_handler(signum, frame):
        raise BridgeDeadlineExceeded("bridge wall deadline exceeded")

    def cancel_handler(signum, frame):
        raise BridgeCancelled(f"bridge cancelled by signal {signum}")

    signal.signal(signal.SIGALRM, alarm_handler)
    signal.signal(signal.SIGTERM, cancel_handler)
    signal.signal(signal.SIGINT, cancel_handler)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    return previous


def _restore_phase_guards(previous) -> None:
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    for signum, handler in previous.items():
        signal.signal(signum, handler)


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
        raise BridgeV10Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise BridgeV10Error(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise BridgeV10Error(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise BridgeV10Error(f"{role} must be a lowercase SHA-256")
    return value


def _require_file(value: Any, role: str) -> Path:
    target = Path(str(value)).expanduser().resolve()
    if not target.is_file():
        raise BridgeV10Error(f"{role} is missing: {target}")
    return target


def _stat_binding(item: Mapping[str, Any], *, verify_content: bool) -> dict[str, Any]:
    path = _require_file(item.get("path"), str(item.get("role", "source")))
    stat = path.stat()
    expected_bytes = item.get("bytes")
    if expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise BridgeV10Error(f"source byte stat differs: {path}")
    expected_mtime = item.get("mtime_ns")
    if expected_mtime is not None and int(expected_mtime) != stat.st_mtime_ns:
        raise BridgeV10Error(f"source mtime stat differs: {path}")
    digest = _require_sha(item.get("sha256"), f"{item.get('role')}.sha256")
    if verify_content and sha256_file(path) != digest:
        raise BridgeV10Error(f"source content SHA differs: {path}")
    return {"role": str(item.get("role")), "path": str(path),
            "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "sha256": digest}


def _load_v7(path: Path | str) -> dict[str, Any]:
    request = load_json(path)
    if request.get("schema") != V7_SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise BridgeV10Error("v7 request is not a ready development request")
    if request.get("qualification") != UNKNOWN or request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise BridgeV10Error("v7 request is not model-free UNKNOWN")
    if request.get("sha256") != canonical_sha(request):
        raise BridgeV10Error("v7 request canonical SHA differs")
    return request


def _guard_paths(root: Path) -> dict[str, Path]:
    scripts = root / "lagrangian-fluid-lab" / "scripts"
    return {
        "shared_dispatch_v6": scripts / "ds_data02_stage2_dispatch_v6.py",
        "shared_strict_dispatch_v6": scripts / "ds_data02_strict_dispatch_v6.py",
        "shared_runtime_v6": scripts / "ds_data02_runtime_v6.py",
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
        raise BridgeV10Error(f"filesystem probe root is unavailable: {target}")
    usage = shutil.disk_usage(target)
    return {"path": str(target), "total_bytes": int(usage.total),
            "used_bytes": int(usage.used), "free_bytes": int(usage.free),
            "probe_status": "READ_ONLY_STAT"}


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform != "darwin" else value


def _posthash_copy_sources(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Hash each large source after reservation and child copy/seal."""
    records: list[dict[str, Any]] = []
    for item in request.get("source_bindings", []):
        if not isinstance(item, Mapping) or item.get("content_scope") != "v7_target_seal_for_copy_source":
            continue
        path = _require_file(item.get("path"), str(item.get("role", "copy_source")))
        expected = _require_sha(item.get("sha256"), f"{item.get('role')}.sha256")
        actual = sha256_file(path)
        record = {"role": item.get("role"), "path": str(path),
                  "expected_sha256": expected, "actual_sha256": actual,
                  "match": actual == expected}
        records.append(record)
        if actual != expected:
            raise BridgeV10Error(f"large copy source SHA differs after run: {path}")
    return records


def _load_shared_v6(dispatch_path: Path) -> tuple[Any, Any]:
    """Load the exact dispatch v6 and its runtime dependency closure."""
    scripts = dispatch_path.parent
    previous = list(sys.path)
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location("_ds02_shared_dispatch_v6_bridge", dispatch_path)
        if spec is None or spec.loader is None:
            raise BridgeV10Error(f"cannot import shared dispatch v6: {dispatch_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous
    if not hasattr(module, "check_reservation") or not hasattr(module, "runtime"):
        raise BridgeV10Error("shared dispatch v6 lacks reservation/runtime interface")
    module.install_guard()
    return module, module.runtime


def _parent_ledger_binding(request: Mapping[str, Any]) -> dict[str, Any]:
    binding = request.get("parent_resource_binding")
    if not isinstance(binding, Mapping):
        raise BridgeV10Error("parent_resource_binding is required")
    if binding.get("no_reset") is not True or binding.get("no_new_data_root_ledger") is not True:
        raise BridgeV10Error("parent ledger reset/new-root policy is unsafe")
    ledger = _require_file(binding.get("path"), "parent ledger")
    checkpoint = _require_file(binding.get("checkpoint_path"), "parent checkpoint")
    return {"ledger": ledger, "checkpoint": checkpoint, "binding": dict(binding)}


def build_request(v7_request_path: Path | str, output_path: Path | str,
                  *, shared_root: Path | str,
                  data_root: Path | str = "/home/jade/Projects/DualSPHysics-data/ds-data-02",
                  attempt_id: str = "f2-s1-portable-ledger-bridge-v10-001") -> dict[str, Any]:
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
    # v7's plan reservation covers a wider multi-case research product.  A
    # single F2-S1 replay reserves only the source copy plus its bounded
    # per-case typed/label output estimate; importing the full 252 GB plan
    # would incorrectly consume the Home floor for this one task.
    source_copy_bytes = int(v7["copy_contract"]["source_bytes_from_overlay"])
    typed_output_reserve_bytes = int(v7.get("resource_request", {}).get("source_copy_bytes", 0))
    typed_output_reserve_bytes = max(typed_output_reserve_bytes // 2, 512 * 1024 * 1024)
    external_required_bytes = source_copy_bytes + typed_output_reserve_bytes
    home_receipt_reserve_bytes = 512 * 1024
    total_required_bytes = external_required_bytes + home_receipt_reserve_bytes
    if not attempt_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in attempt_id):
        raise BridgeV10Error("attempt_id must be a non-empty portable identifier")
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
        {"role": "parent_os_open_trace", "path": str(selected_root.parent / "os-open-trace-v10.log"),
         "parent_owned": True, "required_for_completion": True},
    ]
    source_bindings = [_stat_binding({"role": "v7_request", "path": str(v7_path),
                                      "bytes": v7_path.stat().st_size,
                                      "mtime_ns": v7_path.stat().st_mtime_ns,
                                      "sha256": sha256_file(v7_path)}, verify_content=False)]
    bridge_path = Path(__file__).resolve()
    source_bindings.append(_stat_binding({"role": "portable_ledger_bridge_v10", "path": str(bridge_path),
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
        "forward_of": {"prior_attempt_id": "f2-s1-portable-ledger-bridge-v9-002",
                       "prior_request_is_immutable": True,
                       "revision": "v10-hardwall"},
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "case_id": "F2_S1_PORTABLE_RAW_TO_LABEL_V10",
        "attempt_id": attempt_id,
        "data_root": str(Path(data_root).expanduser().resolve()),
        "shared_v6_root": str(root),
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
            "new_storage_bytes": total_required_bytes,
            "storage_filesystem": str(selected_root.parent),
            "same_parent_lease": True,
            "atomic_ledger_lock": "shared v6 runtime ledger_locked",
            "home_receipt_reserved_bytes": home_receipt_reserve_bytes,
            "external_product_reserved_bytes": external_required_bytes,
        },
        "external_storage_scope": {
            "filesystem": str(selected_root.parent),
            "roots": [str(target_root), str(selected_root)],
            "requested_reservation_bytes": external_required_bytes,
            "tree_bytes_measurement": "recursive regular-file bytes under exactly the two new roots plus listed sidecar artifacts",
            "existing_products_deleted": False,
            "existing_products_moved": False,
            "namespace_must_be_absent_before_reservation": True,
            "accessible_index_path": str(mapping["accessible_index_path"]),
            "expected_artifacts": expected_artifacts,
            "home_receipt": {
                "path": str(Path(data_root).expanduser().resolve() / "families" / "F2" /
                              "F2_S1_PORTABLE_RAW_TO_LABEL_V10" / attempt_id / "execution-receipt.json"),
                "reserved_bytes": home_receipt_reserve_bytes,
                "included_in_parent_charge": True,
            },
        },
        "execution": {
            "entrypoint": str(Path(__file__).resolve()),
            "command": [sys.executable, "-B", str(Path(__file__).resolve()), "run", "--request", "<request>", "--io-slot-approved"],
            "v7_engine": str(Path(v7["execution"]["command"][2]).expanduser().resolve()) if len(v7["execution"].get("command", [])) > 2 else None,
            "prevalidation_cost": {"wall_seconds": "measured", "process_and_children_cpu_seconds": "measured", "included_in_same_parent_charge": True},
            "expected_artifacts_gate": True,
            "raw_bi4_hdf5_read": "parent slot only",
            "source_hash_policy": {
                "declared_sha256_for_all_static_sources": True,
                "large_copy_source_hash_before_reservation": "not_done; source hash verification is charged after reservation",
                "large_copy_source_hash_after_copy": "required before completion; compare every v7 copy_source SHA",
                "target_seal_is_not_the_only_source_check": True,
            },
            "prevalidation_clock": "entry before request/stat/content validation through v7 semantic validation",
            "rss_measurement": "observational getrusage maxrss; no RLIMIT enforcement",
            "hard_wall": {
                "max_wall_seconds": int(v7["resource_request"]["max_wall_seconds"]),
                "enforced_by": "bridge entry-to-finalization SIGALRM plus parent process-group supervisor",
                "covered_phases": ["source_validation", "guard_import", "copy", "seal", "raw_to_typed", "labels", "source_posthash", "artifact_accounting"],
                "nested_loader_process_group": "bridge-created child group; only that group is terminated on timeout",
                "terminal_cleanup": "timer disabled only after expensive checks so receipt and ledger charge can close the registered attempt",
            },
            "failed_status_exit_code": 2,
            "os_open_audit_required": True,
            "model_invoked": False,
            "cfd_invoked": False,
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "limitations": [
            "The bridge calls the bound v6 check_reservation/ledger_locked interface; it does not create or reset a ledger.",
            "Approved execution enforces max_wall_seconds across validation, copy/seal, nested loader, source posthash, and artifact accounting; direct unsupervised invocation is still not an acceptable parent run.",
            "External NVMe tree bytes and the small Home receipt are charged together under the same parent reservation; no stat-only claim is promoted.",
            "Native HDF5/BI4 C-open absence still requires parent OS strace/openat evidence.",
            "Raw labels and all QI/QN/QE remain DEVELOPMENT/UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output_path, request)
    return request


def _validate(request: Mapping[str, Any], *, verify_content: bool) -> list[dict[str, Any]]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise BridgeV10Error("unsupported or non-ready v10 bridge request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise BridgeV10Error("v10 bridge must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise BridgeV10Error("v10 bridge cannot invoke model/CFD")
    if request.get("sha256") != canonical_sha(request):
        raise BridgeV10Error("v10 bridge canonical SHA differs")
    _parent_ledger_binding(request)
    guards = request.get("guard_bindings")
    if not isinstance(guards, list) or {item.get("role") for item in guards} != set(V6_GUARD_ROLES):
        raise BridgeV10Error("complete shared v6 guard closure is required")
    sources = request.get("source_bindings")
    if not isinstance(sources, list) or not sources:
        raise BridgeV10Error("source_bindings are required")
    checked = []
    for item in sources:
        if not isinstance(item, Mapping):
            raise BridgeV10Error("source binding is malformed")
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
        raise BridgeV10Error("external storage scope is incomplete")
    for root in external["roots"]:
        path = Path(str(root)).expanduser().resolve()
        if not str(path).startswith("/var/tmp/"):
            raise BridgeV10Error(f"external output root is outside /var/tmp: {path}")
        if path.exists():
            raise BridgeV10Error(f"external output namespace already exists: {path}")
    return checked


def _expected_artifacts(scope: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = scope.get("expected_artifacts")
    if not isinstance(values, list) or not values:
        raise BridgeV10Error("expected_artifacts are required")
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


def _json_size(value: Mapping[str, Any]) -> int:
    body = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, default=str) + "\n"
    return len(body.encode("utf-8"))


def _prepare_receipt_fixed_point(receipt: dict[str, Any], receipt_path: Path,
                                 external_bytes: int) -> int:
    """Include the Home receipt itself in the charged byte total."""
    predicted = external_bytes + _json_size(receipt)
    for _ in range(128):
        receipt["filesystem"]["home_receipt_bytes"] = predicted - external_bytes
        receipt["filesystem"]["measured_total_bytes"] = predicted
        receipt["sha256"] = canonical_sha(receipt)
        next_total = external_bytes + _json_size(receipt)
        if next_total == predicted:
            return predicted
        predicted = next_total
    raise BridgeV10Error(f"receipt byte fixed point did not converge: {receipt_path}")


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
            "storage_filesystems": [
                str(request["external_storage_scope"]["filesystem"]),
                str(Path(request["data_root"]).expanduser().resolve()),
            ],
            "accounting_scope": "external_target_selected_roots_sidecars_plus_home_bridge_receipt",
        })
        for row in ledger.get("attempts", []):
            if row.get("id") == attempt_id:
                row.update(status=status, finished_at_utc=finished_at)


def run(request_path: Path | str, *, io_slot_approved: bool = False) -> dict[str, Any]:
    global _ACTIVE_DEADLINE
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    entry_rss = _max_rss_bytes()
    request_file = _require_file(request_path, "v10 bridge request")
    request = load_json(request_file)
    if not io_slot_approved:
        checked = _validate(request, verify_content=False)
        return {
            "schema": REPORT_SCHEMA,
            "status": "READY_FOR_PARENT_IO_SLOT",
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "source_count": len(checked),
            "prevalidation": {
                "wall_seconds": time.monotonic() - entry_wall,
                "process_and_children_cpu_seconds": _cpu_seconds() - entry_cpu,
            },
            "execution_boundary": {
                "ledger_mutated": False,
                "raw_opened": False,
                "hdf5_opened": False,
                "model_invoked": False,
                "cfd_invoked": False,
            },
            "qualification": copy.deepcopy(UNKNOWN),
        }

    reservation_cfg = request.get("reservation")
    if not isinstance(reservation_cfg, Mapping):
        raise BridgeV10Error("reservation is required for approved execution")
    max_wall = float(reservation_cfg.get("max_wall_seconds", 0))
    deadline = _Deadline(max_wall)
    # The bridge timer must include request parsing/stat validation as well as
    # the expensive approved phases.  The metadata-only preflight remains
    # outside this path and never mutates the ledger.
    deadline.started = entry_wall
    deadline.deadline = entry_wall + max_wall
    previous_guards = _install_phase_guards(max(0.001, deadline.remaining()))
    _ACTIVE_DEADLINE = deadline
    root: Path | None = None
    data_root: Path | None = None
    dispatch = None
    runtime = None
    before_fs: dict[str, Any] = {"status": "NOT_REACHED"}
    after_fs: dict[str, Any] = {"status": "NOT_REACHED"}
    reservation = dict(request["reservation"])
    required_total = int(reservation["new_storage_bytes"])
    required_external = int(reservation["external_product_reserved_bytes"])
    result: dict[str, Any] = {}
    status = "failed"
    error: str | None = None
    source_posthash: list[dict[str, Any]] = []
    registered = False
    timed_out = False
    cancelled = False
    started = time.monotonic()
    try:
        # This validation is deliberately inside the entry-to-deadline scope:
        # static source hashing, imports, and semantic checks cannot run past
        # the reservation's hard wall unnoticed.
        _validate(request, verify_content=False)
        deadline.check("request prevalidation")
        _validate(request, verify_content=True)
        deadline.check("source validation")
        dispatch_path = next(
            Path(item["path"]).resolve()
            for item in request["guard_bindings"]
            if item["role"] == "shared_dispatch_v6"
        )
        dispatch, runtime = _load_shared_v6(dispatch_path)
        deadline.check("shared v6 guard import")
        root = Path(request["external_storage_scope"]["filesystem"]).expanduser().resolve()
        if not root.is_dir():
            raise BridgeV10Error(f"external storage filesystem is unavailable: {root}")
        before_fs = _disk_probe(root)
        if before_fs["free_bytes"] < required_external:
            raise BridgeV10Error("external output filesystem lacks requested reservation headroom")
        v7_path = Path(request["v7_request"]["path"]).expanduser().resolve()
        v7 = _load_v7(v7_path)
        v7_module_path = Path(str(v7["execution"]["command"][2])).expanduser().resolve()
        v7_binding = next(
            (item for item in request["source_bindings"]
             if item.get("role") == "v7:portable_orchestrator_v7"),
            None,
        )
        if not isinstance(v7_binding, Mapping) or Path(str(v7_binding["path"])).resolve() != v7_module_path:
            raise BridgeV10Error("v7 engine path is not the bound relocated orchestrator source")
        v7_spec = importlib.util.spec_from_file_location("_ds02_v7_engine_for_bridge_v10", v7_module_path)
        if v7_spec is None or v7_spec.loader is None:
            raise BridgeV10Error(f"cannot import v7 engine: {v7_module_path}")
        v7_module = importlib.util.module_from_spec(v7_spec)
        v7_spec.loader.exec_module(v7_module)
        # v7 only calls subprocess.run for the private loader.  Replace that
        # reference with a proxy so the nested child receives its own process
        # group and cannot outlive the bridge deadline.
        v7_module.subprocess = types.SimpleNamespace(run=_bounded_subprocess_run)
        v7_module._validate_request(v7, verify_metadata_content=False)
        deadline.check("v7 semantic validation")
        prevalidation_wall = time.monotonic() - entry_wall
        prevalidation_cpu = _cpu_seconds() - entry_cpu
        data_root = Path(request["data_root"]).expanduser().resolve()
        attempt_id = str(request["attempt_id"])
        reservation.update({
            "id": attempt_id,
            "reserved_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "launcher_pid": os.getpid(),
            "host": os.uname().nodename,
        })
        with runtime.ledger_locked(data_root) as ledger:
            policy = ledger.get("limits", {}).get("storage_policy")
            existing = 0 if policy == "home_free_floor" else runtime.tree_bytes(data_root)
            available_home = os.statvfs(data_root).f_bavail * os.statvfs(data_root).f_frsize
            dispatch.check_reservation(
                ledger, reservation, existing, available_bytes=available_home
            )
            ledger["reservations"].append(reservation)
            ledger["attempts"].append({
                "id": attempt_id,
                "kind": reservation["kind"],
                "status": "reserved",
                "started_at_utc": reservation["reserved_at_utc"],
            })
            registered = True
        deadline.check("reservation")
        deadline.check("before portable copy")
        result = v7_module.run(v7_path, io_slot_approved=True, verify_metadata_content=True)
        deadline.check("raw-to-typed loader and labels")
        status = "completed" if str(result.get("status", "")).startswith("COMPLETE") else "failed"
        source_posthash = _posthash_copy_sources(request)
        deadline.check("source posthash")
    except BridgeDeadlineExceeded as exc:
        timed_out = True
        status = "failed"
        error = str(exc)
        result = {"status": "BRIDGE_WALL_DEADLINE_EXCEEDED", "error": error}
    except BridgeCancelled as exc:
        cancelled = True
        status = "failed"
        error = str(exc)
        result = {"status": "BRIDGE_CANCELLED", "error": error}
    except BaseException as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        result = {"status": "BRIDGE_EXECUTION_FAILED", "error": error}
    finally:
        # Artifact/source checks are part of the deadline scope.  A deadline
        # signal may interrupt one of these expensive operations; in that
        # case, preserve a terminal failure and skip further expensive hashes.
        scope = request["external_storage_scope"]
        roots = [Path(str(value)).expanduser().resolve() for value in scope["roots"]]
        expected_artifacts: list[dict[str, Any]] = []
        artifact_check: dict[str, Any] = {"status": "NOT_REACHED", "items": [], "missing": []}
        external_bytes = 0
        finalization_error: str | None = None
        try:
            expected_artifacts = _expected_artifacts(scope)
            if not timed_out and not cancelled:
                deadline.check("artifact and output accounting")
                artifact_check = _artifact_check(expected_artifacts)
                external_bytes = sum(_tree_bytes(path) for path in roots)
                sidecars = [
                    Path(str(item["path"])).expanduser().resolve()
                    for item in expected_artifacts
                    if Path(str(item["path"])).expanduser().resolve().is_file()
                    and not any(
                        Path(str(item["path"])).expanduser().resolve() == root_path
                        or root_path in Path(str(item["path"])).expanduser().resolve().parents
                        for root_path in roots
                    )
                ]
                external_bytes += sum(int(path.stat().st_size) for path in sidecars)
                if root is not None:
                    after_fs = _disk_probe(root)
                if artifact_check["status"] != "PASS":
                    status = "failed"
                    if error is None:
                        error = "required output artifact is missing"
                if external_bytes > required_external:
                    status = "failed"
                    if error is None:
                        error = "measured external output exceeds reservation"
                if registered and not source_posthash:
                    deadline.check("source posthash")
                    source_posthash = _posthash_copy_sources(request)
            else:
                artifact_check = {
                    "status": "SKIPPED_AFTER_DEADLINE_OR_CANCEL",
                    "items": [],
                    "missing": [],
                }
                # A terminal charge still needs a conservative byte count.
                # This cleanup is performed after the deadline signal has
                # fired and is intentionally recorded as post-deadline cleanup.
                external_bytes = sum(_tree_bytes(path) for path in roots)
                if root is not None:
                    after_fs = _disk_probe(root)
        except (BridgeDeadlineExceeded, BridgeCancelled) as exc:
            timed_out = timed_out or isinstance(exc, BridgeDeadlineExceeded)
            cancelled = cancelled or isinstance(exc, BridgeCancelled)
            status = "failed"
            finalization_error = str(exc)
            if error is None:
                error = finalization_error
            artifact_check = {
                "status": "SKIPPED_AFTER_DEADLINE_OR_CANCEL",
                "items": [],
                "missing": [],
            }
            external_bytes = sum(_tree_bytes(path) for path in roots)
            if root is not None:
                after_fs = _disk_probe(root)
        except BaseException as exc:
            status = "failed"
            finalization_error = f"{type(exc).__name__}: {exc}"
            if error is None:
                error = finalization_error

        if finalization_error and not error:
            error = finalization_error
        # The hard wall covers source/posthash and output accounting.  Disable
        # the alarm before terminal JSON/fixed-point and ledger charge so every
        # registered reservation receives a terminal charge rather than a
        # dangling reservation.  The receipt records any cleanup after the
        # deadline explicitly.
        if _ACTIVE_DEADLINE is not None:
            _restore_phase_guards(previous_guards)
            _ACTIVE_DEADLINE = None
        total_cpu = max(0.0, _cpu_seconds() - entry_cpu)
        total_rss = max(entry_rss, _max_rss_bytes())
        finished = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        attempt_id = str(request["attempt_id"])
        if data_root is None:
            data_root = Path(request["data_root"]).expanduser().resolve()
        receipt_path = (
            data_root / "families" / "F2" / "F2_S1_PORTABLE_RAW_TO_LABEL_V10"
            / attempt_id / "execution-receipt.json"
        )
        deadline_status = (
            "EXCEEDED" if timed_out else "CANCELLED" if cancelled else "WITHIN_LIMIT"
        )
        receipt = {
            "schema": REPORT_SCHEMA,
            "status": "COMPLETE_DEVELOPMENT_UNKNOWN" if status == "completed"
            else "FAILED_PARENT_BRIDGED_REPLAY",
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "attempt_id": attempt_id,
            "parent_ledger": {
                "path": str(request["parent_resource_binding"]["path"]),
                "same_parent_lock": True,
                "reservation_registered": registered,
                "ledger_reset": False,
                "charge_includes_home_receipt": True,
            },
            "deadline": {
                "max_wall_seconds": max_wall,
                "status": deadline_status,
                "phase_coverage": [
                    "source_validation",
                    "v6_guard_import",
                    "copy",
                    "seal",
                    "nested_raw_to_typed_loader",
                    "labels",
                    "source_posthash",
                    "artifact_and_output_accounting",
                ],
                "child_process_group_termination": "only nested loader child group",
                "cleanup_after_deadline_allowed": True,
            },
            "prevalidation": {
                "wall_seconds": time.monotonic() - entry_wall,
                "process_and_children_cpu_seconds": max(0.0, prevalidation_cpu if "prevalidation_cpu" in locals() else _cpu_seconds() - entry_cpu),
                "started_at_function_entry": True,
                "included_in_same_parent_charge": True,
            },
            "execution": {
                "wall_seconds": time.monotonic() - started,
                "wall_seconds_from_function_entry": time.monotonic() - entry_wall,
                "process_and_children_cpu_seconds": total_cpu,
                "max_rss_observed_bytes": total_rss,
                "result": result,
                "error": error,
            },
            "filesystem": {
                "before": before_fs,
                "after": after_fs,
                "scope": [str(path) for path in roots],
                "external_product_bytes": external_bytes,
                "home_receipt_bytes": 0,
                "measured_total_bytes": 0,
                "reserved_external_product_bytes": required_external,
                "reserved_total_parent_bytes": required_total,
                "artifact_check": artifact_check,
            },
            "source_posthash": {
                "status": (
                    "PASS" if source_posthash and all(item["match"] for item in source_posthash)
                    else "SKIPPED_AFTER_DEADLINE_OR_CANCEL"
                    if timed_out or cancelled else "UNKNOWN_OR_FAILED"
                ),
                "copy_sources": source_posthash,
            },
            "model_invoked": False,
            "cfd_invoked": False,
            "os_open_audit_required": True,
            "original_path_fallback": "FORBIDDEN",
            "qualification": copy.deepcopy(UNKNOWN),
        }
        total_bytes = _prepare_receipt_fixed_point(receipt, receipt_path, external_bytes)
        # CPU/RSS are measured after all expensive source/output checks, then
        # fixed-point generation is rerun so the terminal receipt carries the
        # same values that are charged to the parent.
        total_cpu = max(0.0, _cpu_seconds() - entry_cpu)
        total_rss = max(total_rss, _max_rss_bytes())
        receipt["execution"]["process_and_children_cpu_seconds"] = total_cpu
        receipt["execution"]["max_rss_observed_bytes"] = total_rss
        total_bytes = _prepare_receipt_fixed_point(receipt, receipt_path, external_bytes)
        if total_bytes > required_total or receipt["filesystem"]["home_receipt_bytes"] > int(reservation["home_receipt_reserved_bytes"]):
            status = "failed"
            if error is None:
                error = "Home receipt or total storage reservation exceeded"
            receipt["status"] = "FAILED_PARENT_BRIDGED_REPLAY"
            receipt["execution"]["error"] = error
            receipt["deadline"]["status"] = "FAILED_STORAGE_RESERVATION"
            total_cpu = max(0.0, _cpu_seconds() - entry_cpu)
            receipt["execution"]["process_and_children_cpu_seconds"] = total_cpu
            total_bytes = _prepare_receipt_fixed_point(receipt, receipt_path, external_bytes)
        write_new(receipt_path, receipt)
        actual_total = external_bytes + int(receipt_path.stat().st_size)
        receipt["filesystem"]["measured_total_bytes"] = actual_total
        if registered and dispatch is not None and runtime is not None:
            _charge_parent(
                dispatch, runtime, request, reservation=reservation,
                actual_bytes=actual_total, cpu_seconds=total_cpu,
                status=status, finished_at=finished,
            )
        return receipt

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v7-request", type=Path, required=True)
    build.add_argument("--shared-root", type=Path, required=True)
    build.add_argument("--data-root", type=Path, default=Path("/home/jade/Projects/DualSPHysics-data/ds-data-02"))
    build.add_argument("--attempt-id", default="f2-s1-portable-ledger-bridge-v10-001")
    build.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v7_request, args.output, shared_root=args.shared_root,
                                  data_root=args.data_root, attempt_id=args.attempt_id)
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved)
    except (BridgeV10Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": value.get("schema", SCHEMA), "status": value.get("status"),
                      "qualification": value.get("qualification", UNKNOWN)}, sort_keys=True,
                     default=str))
    status = str(value.get("status", ""))
    return 0 if status in {"READY_FOR_PARENT_GUARD", "READY_FOR_PARENT_IO_SLOT", "COMPLETE_DEVELOPMENT_UNKNOWN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
