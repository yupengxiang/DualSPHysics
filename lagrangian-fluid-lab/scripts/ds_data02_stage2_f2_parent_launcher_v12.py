#!/usr/bin/env python3
"""Parent-supervised v12 forward of the consumed F2 v11 launcher.

The v11 launcher used a short TERM-to-KILL interval.  That interval could
kill the v10 bridge while it was closing a registered reservation, receipt,
and ledger charge.  v12 keeps the same parent-owned strace and two-filesystem
preflight, but gives the bridge a bounded cooperative cleanup interval.  It
then verifies the terminal receipt, parent charge, and any attempt lease.  A
non-terminal result is reported as ``UNCONFIRMED`` and never receives replay
credit.

The bridge owns the Stage2 ledger mutation.  This launcher only reads the
ledger after the child exits and writes a finalization sidecar for the parent
supervisor.  A sidecar is deliberately accounted as a supplemental byte
charge: v10's immutable receipt cannot be rewritten after it was charged.
The launcher never opens HDF5/BI4, creates a ledger/data root, or grants
QI/QN/QE.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v12"
REPORT_SCHEMA = "ds02.stage2.f2-parent-supervised-launch-report.v12"
V11_SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v11"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
PR_SET_PDEATHSIG = 1


class ParentLaunchError(RuntimeError):
    """The parent launch contract cannot be safely executed."""


class ParentLaunchCancelled(ParentLaunchError):
    """The supervising parent cancelled this launcher."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ParentLaunchError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ParentLaunchError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ParentLaunchError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ParentLaunchError(f"{name} must be a lowercase SHA-256")
    return value


def _file_ref(item: Mapping[str, Any], *, verify_content: bool) -> dict[str, Any]:
    path = Path(str(item.get("path"))).expanduser().resolve()
    if not path.is_file():
        raise ParentLaunchError(f"bound source is missing: {path}")
    stat = path.stat()
    mutable_parent = item.get("source_kind") == "parent"
    expected_bytes = item.get("bytes")
    if not mutable_parent and expected_bytes is not None and int(expected_bytes) != stat.st_size:
        raise ParentLaunchError(f"bound source byte stat differs: {path}")
    expected_mtime = item.get("mtime_ns")
    if not mutable_parent and expected_mtime is not None and int(expected_mtime) != stat.st_mtime_ns:
        raise ParentLaunchError(f"bound source mtime differs: {path}")
    expected = _sha(item.get("sha256"), str(item.get("role", "source")))
    if verify_content and not mutable_parent and sha256_file(path) != expected:
        raise ParentLaunchError(f"bound source SHA differs: {path}")
    return {"role": str(item.get("role", "source")), "path": str(path),
            "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "sha256": expected, "source_kind": "parent" if mutable_parent else "static"}


def _load_v11_module(path: Path):
    spec = importlib.util.spec_from_file_location("ds02_parent_launcher_v11_for_v12", path)
    if spec is None or spec.loader is None:
        raise ParentLaunchError(f"cannot import v11 launcher: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_v11(request_path: Path | str, *, verify_sources: bool = False) -> tuple[dict[str, Any], Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    if request.get("schema") != V11_SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentLaunchError("bound request is not a ready v11 launch request")
    if request.get("sha256") != canonical_sha(request):
        raise ParentLaunchError("v11 launch request canonical SHA differs")
    launcher_binding = next((item for item in request.get("source_bindings", [])
                             if item.get("role") == "parent_launcher_v11"), None)
    if not isinstance(launcher_binding, Mapping):
        raise ParentLaunchError("v11 launcher source binding is missing")
    launcher_path = Path(str(launcher_binding.get("path"))).expanduser().resolve()
    module = _load_v11_module(launcher_path)
    module._validate_launch(request, verify_content=verify_sources)
    return request, module


def _trace_binding(v11: Mapping[str, Any]) -> dict[str, Any]:
    value = v11.get("trace")
    if not isinstance(value, Mapping):
        raise ParentLaunchError("v11 trace binding is missing")
    path = Path(str(value.get("path"))).expanduser().resolve()
    bridge = load_json(Path(str(v11["bridge_request"]["path"])))
    filesystem = Path(str(bridge["external_storage_scope"]["filesystem"])).expanduser().resolve()
    if path.parent != filesystem:
        raise ParentLaunchError("parent OS trace must be in the v10 external filesystem root")
    if path.exists():
        raise ParentLaunchError(f"parent OS trace already exists: {path}")
    return {"role": "parent_os_open_trace", "path": str(path),
            "required_for_completion": bool(value.get("required_for_completion", False))}


def _sidecar_path(trace_path: Path) -> Path:
    return trace_path.with_name(trace_path.stem + "-finalization-v12.json")


def _python_path() -> Path:
    path = Path(sys.executable).expanduser().resolve()
    if not path.is_file():
        raise ParentLaunchError(f"Python executable is missing: {path}")
    return path


def build_request(v11_request_path: Path | str, output_path: Path | str,
                  *, cleanup_grace_seconds: float = 5.0) -> dict[str, Any]:
    v11_file = Path(v11_request_path).expanduser().resolve()
    v11, module = _load_v11(v11_file, verify_sources=False)
    if not isinstance(cleanup_grace_seconds, (int, float)) or cleanup_grace_seconds <= 0:
        raise ParentLaunchError("cleanup_grace_seconds must be positive")
    trace = _trace_binding(v11)
    trace_path = Path(trace["path"])
    sidecar = _sidecar_path(trace_path)
    if sidecar.exists():
        raise ParentLaunchError(f"v12 finalization sidecar already exists: {sidecar}")
    launcher_path = Path(__file__).resolve()
    python_path = _python_path()
    v11_launcher = next(Path(str(item["path"])).expanduser().resolve()
                        for item in v11["source_bindings"]
                        if item.get("role") == "parent_launcher_v11")
    bridge_request_path = Path(str(v11["bridge_request"]["path"])).expanduser().resolve()
    bridge_request = load_json(bridge_request_path)
    ledger_path = Path(str(v11["parent_resource_binding"]["path"])).expanduser().resolve()
    home_receipt = Path(str(bridge_request["external_storage_scope"]["home_receipt"]["path"])).expanduser().resolve()
    attempt_id = str(bridge_request["attempt_id"])
    bindings: list[dict[str, Any]] = []

    def add(role: str, path: Path, *, sha: str | None = None,
            source_kind: str = "static") -> None:
        stat = path.stat()
        bindings.append(_file_ref({"role": role, "path": str(path), "bytes": stat.st_size,
                                   "mtime_ns": stat.st_mtime_ns,
                                   "sha256": sha or sha256_file(path),
                                   "source_kind": source_kind}, verify_content=False))

    add("parent_launcher_v12", launcher_path)
    add("v11_launch_request", v11_file, sha=v11_file and sha256_file(v11_file))
    for item in v11["source_bindings"]:
        add("v11:" + str(item["role"]), Path(str(item["path"])).expanduser().resolve(),
            sha=str(item["sha256"]))
    # The parent ledger is intentionally mutable while its semantic campaign,
    # limits, and deadline remain bound.  Preserve the original path/role but
    # do not freeze its mtime or content hash as a static code input.
    add("parent_resource_ledger", ledger_path, sha=sha256_file(ledger_path),
        source_kind="parent")
    python = python_path
    strace = Path(str(next(item for item in bridge_request["source_bindings"]
                           if item.get("role") == "v7:os_strace")["path"])).expanduser().resolve()
    add("python_executable_v12", python)
    add("os_strace_v12", strace)
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "forward_of": {"schema": V11_SCHEMA, "path": str(v11_file),
                       "sha256": v11["sha256"], "immutable": True,
                       "revision": "terminal-cleanup-and-trace-reconciliation-v12"},
        "v11_launch": {"path": str(v11_file), "sha256": v11["sha256"],
                       "file_sha256": sha256_file(v11_file),
                       "schema": V11_SCHEMA, "attempt_id": attempt_id},
        "parent_resource_binding": copy.deepcopy(v11["parent_resource_binding"]),
        "accounting": {
            "ledger_path": str(ledger_path),
            "attempt_id": attempt_id,
            "home_receipt_path": str(home_receipt),
            "terminal_charge_required": True,
            "reservation_must_be_absent_after_child_exit": True,
            "lease_scope": "any lease row carrying this attempt_id must be absent; v10 CPU request normally has no GPU lease",
            "launcher_does_not_mutate_ledger": True,
        },
        "storage_scope": {
            "home_path": v11["storage_scope"]["home_path"],
            "home_min_free_bytes": int(v11["storage_scope"]["home_min_free_bytes"]),
            "external_filesystem": v11["storage_scope"]["external_filesystem"],
            "trace_path": trace["path"],
            "finalization_sidecar": str(sidecar),
            "supplemental_delta_is_parent_charge": True,
        },
        "trace": trace,
        "execution": {
            "python": str(python),
            "strace": str(strace),
            "v11_launcher": str(v11_launcher),
            "bridge": v11["execution"]["bridge"],
            "parent_supervised": [str(python), "-B", str(launcher_path), "run",
                                   "--request", "<request>", "--parent-pid", "<supervisor_pid>"],
            "cleanup_grace_seconds": float(cleanup_grace_seconds),
            "cleanup_sequence": ["SIGTERM_own_process_group", "bounded_grace", "SIGKILL_own_process_group_if_alive", "verify_terminal_accounting"],
            "trace_finalization_sidecar": str(sidecar),
        },
        "parent_boundary": {
            "max_wall_seconds": int(v11["parent_boundary"]["max_wall_seconds"]),
            "clock_starts": "v12 function entry",
            "parent_pid_required": True,
            "parent_death_signal": "SIGTERM",
            "child_process_group": "launcher-created strace/bridge group only",
            "cancellation": "SIGTERM then bounded cleanup grace; SIGKILL only own group if still alive",
            "hard_wall_claim": "outer child wait is bounded; terminal bridge cleanup may extend the observed wall by cleanup_grace_seconds and is reported explicitly",
            "ledger_owner": "v10 bridge only; v12 verifies, never mutates",
        },
        "source_bindings": bindings,
        "input_files": [item["path"] for item in bindings],
        "input_sha256": {item["path"]: item["sha256"] for item in bindings},
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "limitations": [
            "Metadata preflight reads only declared small JSON/code/stat inputs; it does not open HDF5/BI4.",
            "A cooperative v10 bridge must finish terminal receipt/charge during cleanup grace; an uncooperative or D-state child is reported UNCONFIRMED.",
            "The v12 trace sidecar is a new product byte. The parent must charge its bytes and any post-charge trace delta under the same parent accounting scope.",
            "No QI/QN/QE or raw-to-label credit is granted by this launcher.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output_path, request)
    return request


def _validate_launch(request: Mapping[str, Any], *, verify_content: bool) -> tuple[dict[str, Any], Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ParentLaunchError("unsupported or non-ready v12 launch request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise ParentLaunchError("v12 launch must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ParentLaunchError("v12 launch cannot invoke model/CFD")
    if request.get("sha256") != canonical_sha(request):
        raise ParentLaunchError("v12 launch canonical SHA differs")
    bindings = request.get("source_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ParentLaunchError("v12 source closure is incomplete")
    roles = {str(item.get("role")) for item in bindings if isinstance(item, Mapping)}
    if "parent_launcher_v12" not in roles or "v11_launch_request" not in roles:
        raise ParentLaunchError("v12 source closure lacks launcher or v11 request")
    checked = {str(item["role"]): _file_ref(item, verify_content=verify_content)
               for item in bindings if isinstance(item, Mapping)}
    v11_path = Path(str(request["v11_launch"]["path"])).expanduser().resolve()
    if checked.get("v11_launch_request", {}).get("path") != str(v11_path):
        raise ParentLaunchError("v11 request path differs from source binding")
    v11, module = _load_v11(v11_path, verify_sources=verify_content)
    if v11.get("sha256") != request["v11_launch"].get("sha256"):
        raise ParentLaunchError("v11 request SHA differs")
    if request["v11_launch"].get("file_sha256") != sha256_file(v11_path):
        raise ParentLaunchError("v11 request file SHA differs")
    trace = _trace_binding(v11)
    if trace != request.get("trace"):
        raise ParentLaunchError("parent trace binding differs from v11")
    expected_sidecar = str(_sidecar_path(Path(trace["path"])))
    if request.get("storage_scope", {}).get("finalization_sidecar") != expected_sidecar:
        raise ParentLaunchError("finalization sidecar path is not derived from trace")
    sidecar = Path(expected_sidecar)
    if sidecar.exists():
        raise ParentLaunchError(f"finalization sidecar already exists: {sidecar}")
    grace = request.get("execution", {}).get("cleanup_grace_seconds")
    if isinstance(grace, bool) or not isinstance(grace, (int, float)) or grace <= 0:
        raise ParentLaunchError("cleanup grace must be positive")
    accounting = request.get("accounting")
    if not isinstance(accounting, Mapping) or not accounting.get("terminal_charge_required"):
        raise ParentLaunchError("terminal accounting binding is required")
    return v11, module


def _existing_dir(path: Path) -> Path:
    current = path.expanduser().resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    if not current.is_dir():
        raise ParentLaunchError(f"no existing filesystem anchor for {path}")
    return current


def _storage_preflight(v11: Mapping[str, Any]) -> dict[str, Any]:
    # Reuse v11's exact statvfs semantics; it does not mutate the ledger.
    launcher = _load_v11_module(Path(str(next(item for item in v11["source_bindings"]
                                          if item.get("role") == "parent_launcher_v11")["path"])))
    bridge, _module = launcher._load_v10(Path(str(v11["bridge_request"]["path"])), verify_sources=False)
    result = launcher._storage_preflight(bridge)
    result["v12_cleanup_grace_seconds"] = None
    return result


def _set_parent_death_signal(parent_pid: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot install parent-death signal")
    if os.getppid() != parent_pid:
        raise ParentLaunchCancelled("supervising parent already exited")


def _terminate_child_group_bounded(child: subprocess.Popen[str], grace: float) -> dict[str, Any]:
    """Give the bridge a bounded chance to close its registered attempt."""
    result: dict[str, Any] = {"sigterm_sent": False, "grace_seconds": float(grace),
                              "forced_sigkill": False, "exited_after_cleanup": False}
    try:
        pgid = os.getpgid(child.pid)
        os.killpg(pgid, signal.SIGTERM)
        result["sigterm_sent"] = True
    except (ProcessLookupError, PermissionError):
        result["exited_after_cleanup"] = child.poll() is not None
        return result
    deadline = time.monotonic() + max(0.001, float(grace))
    while child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    if child.poll() is None:
        result["forced_sigkill"] = True
        try:
            os.killpg(os.getpgid(child.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        child.wait(timeout=max(0.5, min(2.0, float(grace))))
    except subprocess.TimeoutExpired:
        # A D-state process cannot be synchronously reaped.  Report it rather
        # than pretending that terminal ledger cleanup was observed.
        pass
    result["exited_after_cleanup"] = child.poll() is not None
    return result


def _parse_child_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _terminal_accounting_status(request: Mapping[str, Any]) -> dict[str, Any]:
    accounting = request.get("accounting", {})
    ledger_path = Path(str(accounting.get("ledger_path", ""))).expanduser().resolve()
    attempt_id = str(accounting.get("attempt_id", ""))
    receipt_path = Path(str(accounting.get("home_receipt_path", ""))).expanduser().resolve()
    result: dict[str, Any] = {
        "status": "UNCONFIRMED",
        "ledger_path": str(ledger_path),
        "attempt_id": attempt_id,
        "receipt_path": str(receipt_path),
        "receipt_exists": receipt_path.is_file(),
        "reservation_rows": None,
        "charge_rows": None,
        "attempt_rows": None,
        "lease_paths": [],
        "reason": None,
    }
    if not ledger_path.is_file():
        result["reason"] = "parent ledger unavailable"
        return result
    try:
        ledger = load_json(ledger_path)
    except ParentLaunchError as error:
        result["reason"] = str(error)
        return result
    reservations = [row for row in ledger.get("reservations", [])
                    if isinstance(row, Mapping) and row.get("id") == attempt_id]
    charges = [row for row in ledger.get("charges", [])
               if isinstance(row, Mapping) and row.get("id") == attempt_id]
    attempts = [row for row in ledger.get("attempts", [])
                if isinstance(row, Mapping) and row.get("id") == attempt_id]
    lease_paths: list[str] = []
    leases_root = ledger_path.parent.parent / "leases"
    if leases_root.is_dir():
        for path in sorted(leases_root.glob("*.json")):
            try:
                value = load_json(path)
            except ParentLaunchError:
                continue
            if value.get("attempt_id") == attempt_id:
                lease_paths.append(str(path))
    result.update({"reservation_rows": len(reservations), "charge_rows": len(charges),
                   "attempt_rows": len(attempts), "lease_paths": lease_paths})
    if not receipt_path.is_file():
        result["reason"] = "terminal Home receipt is missing"
        return result
    try:
        receipt = load_json(receipt_path)
    except ParentLaunchError as error:
        result["reason"] = f"terminal receipt unreadable: {error}"
        return result
    receipt_status = str(receipt.get("status", ""))
    result["receipt_status"] = receipt_status
    terminal_receipt = receipt_status.startswith(("COMPLETE_", "FAILED_"))
    terminal_attempt = bool(attempts) and str(attempts[-1].get("status", "")) not in {"reserved", "running"}
    if reservations or not charges or lease_paths or not terminal_receipt or not terminal_attempt:
        result["reason"] = "reservation/charge/lease/receipt/attempt is not terminal"
        return result
    result["status"] = "PASS_TERMINAL_CHARGE_AND_LEASE_CLEANUP"
    result["reason"] = None
    return result


def _trace_record(request: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(request["trace"]["path"])).expanduser().resolve()
    return {"path": str(path), "exists": path.is_file(),
            "bytes": int(path.stat().st_size) if path.is_file() else 0,
            "sha256": sha256_file(path) if path.is_file() else None,
            "single_file_follow_fork": True}


def _bridge_trace_bytes(request: Mapping[str, Any]) -> int | None:
    receipt_path = Path(str(request["accounting"]["home_receipt_path"])).expanduser().resolve()
    if not receipt_path.is_file():
        return None
    try:
        receipt = load_json(receipt_path)
    except ParentLaunchError:
        return None
    artifact = receipt.get("filesystem", {}).get("artifact_check", {}).get("items", [])
    if isinstance(artifact, list):
        for item in artifact:
            if isinstance(item, Mapping) and item.get("role") == "parent_os_open_trace":
                value = item.get("bytes")
                if isinstance(value, int) and value >= 0:
                    return value
    return None


def _write_trace_sidecar(request: Mapping[str, Any], accounting: Mapping[str, Any],
                         cleanup: Mapping[str, Any], trace: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(request["storage_scope"]["finalization_sidecar"])).expanduser().resolve()
    bridge_bytes = _bridge_trace_bytes(request)
    final_bytes = int(trace.get("bytes", 0))
    trace_delta = max(0, final_bytes - bridge_bytes) if bridge_bytes is not None else final_bytes
    value: dict[str, Any] = {
        "schema": "ds02.stage2.f2-parent-trace-finalization.v12",
        "role": "DEVELOPMENT_ACCOUNTING_SIDECAR",
        "request_sha256": request.get("sha256"),
        "attempt_id": accounting.get("attempt_id"),
        "trace": dict(trace),
        "bridge_receipt_trace_bytes": bridge_bytes,
        "trace_growth_after_bridge_charge_bytes": trace_delta,
        "cleanup": dict(cleanup),
        "parent_charge_required": True,
        "supplemental_charge_scope": "trace_growth_after_bridge_charge_plus_this_sidecar",
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "source_path_fallback": "FORBIDDEN",
    }
    value["sha256"] = canonical_sha(value)
    path_written = write_new(path, value)
    value["sidecar_path"] = str(path_written)
    value["sidecar_bytes"] = int(path_written.stat().st_size)
    value["supplemental_charge_bytes_lower_bound"] = int(trace_delta + value["sidecar_bytes"])
    # The sidecar is immutable; the path/size accounting fields returned to
    # the parent are deliberately outside the file so adding them cannot alter
    # the already-written canonical bytes.
    return value


def run(request_path: Path | str, *, parent_pid: int) -> dict[str, Any]:
    entry = time.monotonic()
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    max_wall = int(request.get("parent_boundary", {}).get("max_wall_seconds", 0))
    cleanup_grace = float(request.get("execution", {}).get("cleanup_grace_seconds", 0))
    if max_wall <= 0 or cleanup_grace <= 0:
        raise ParentLaunchError("v12 max_wall and cleanup grace must be positive")
    previous = {signal.SIGTERM: signal.getsignal(signal.SIGTERM),
                signal.SIGINT: signal.getsignal(signal.SIGINT)}

    def cancelled(signum, _frame):
        raise ParentLaunchCancelled(f"launcher cancelled by signal {signum}")

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    child: subprocess.Popen[str] | None = None
    status = "FAILED_PARENT_SUPERVISED_LAUNCH"
    error: str | None = None
    stdout = ""
    stderr = ""
    child_timed_out = False
    cleanup: dict[str, Any] = {"attempted": False}
    storage: dict[str, Any] | None = None
    child_result: dict[str, Any] | None = None
    try:
        v11, _module = _validate_launch(request, verify_content=True)
        storage = _storage_preflight(v11)
        trace_path = Path(str(request["trace"]["path"])).expanduser().resolve()
        sidecar_path = Path(str(request["storage_scope"]["finalization_sidecar"])).expanduser().resolve()
        if trace_path.exists() or sidecar_path.exists():
            raise ParentLaunchError("trace or finalization sidecar already exists")
        _set_parent_death_signal(parent_pid)
        python = Path(str(request["execution"]["python"])).expanduser().resolve()
        strace = Path(str(request["execution"]["strace"])).expanduser().resolve()
        bridge = Path(str(request["execution"]["bridge"])).expanduser().resolve()
        command = [str(strace), "-f", "-e",
                   "trace=openat,openat2,creat,truncate,rename,unlink,statx",
                   "-o", str(trace_path), str(python), "-B", str(bridge),
                   "run", "--request", str(v11["bridge_request"]["path"]),
                   "--io-slot-approved"]
        launcher_pid = os.getpid()
        child = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parents[2]),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, start_new_session=True,
                                 preexec_fn=lambda: _set_parent_death_signal(launcher_pid))
        remaining = max(0.001, float(max_wall) - (time.monotonic() - entry))
        try:
            stdout, stderr = child.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            child_timed_out = True
            cleanup = _terminate_child_group_bounded(child, cleanup_grace)
            try:
                stdout, stderr = child.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", "child did not become reapable after bounded cleanup"
            error = "parent launcher wall deadline exceeded"
        child_result = _parse_child_json(stdout)
        if not child_timed_out and child.returncode == 0:
            status = "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN"
        elif not child_timed_out and error is None:
            error = f"bridge child returned {child.returncode}: {stderr[-1000:]}"
            status = "FAILED_PARENT_SUPERVISED_CHILD"
        elif child_timed_out:
            status = "FAILED_PARENT_SUPERVISED_DEADLINE"
    except ParentLaunchCancelled as exc:
        error = str(exc)
        status = "FAILED_PARENT_SUPERVISED_CANCELLED"
        if child is not None:
            cleanup = _terminate_child_group_bounded(child, cleanup_grace)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "FAILED_PARENT_SUPERVISED_LAUNCH"
        if child is not None:
            cleanup = _terminate_child_group_bounded(child, cleanup_grace)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    trace = _trace_record(request)
    accounting = _terminal_accounting_status(request)
    if accounting["status"] != "PASS_TERMINAL_CHARGE_AND_LEASE_CLEANUP":
        status = "FAILED_PARENT_ACCOUNTING_UNCONFIRMED"
        if error is None:
            error = accounting.get("reason") or "terminal accounting was not observed"
    sidecar: dict[str, Any] | None = None
    try:
        sidecar = _write_trace_sidecar(request, accounting, cleanup, trace)
    except BaseException as exc:
        if error is None:
            error = f"trace finalization sidecar failed: {type(exc).__name__}: {exc}"
        status = "FAILED_PARENT_FINALIZATION"
    return {
        "schema": REPORT_SCHEMA,
        "status": status,
        "request": {"path": str(request_file), "sha256": request.get("sha256"),
                     "v11_launch_sha256": request.get("v11_launch", {}).get("sha256")},
        "parent": {"pid": int(parent_pid), "launcher_pid": os.getpid(),
                    "same_parent_ledger": True, "ledger_mutated_by_launcher": False},
        "storage_preflight": storage,
        "deadline": {"max_wall_seconds": max_wall, "started_at_entry": True,
                      "elapsed_seconds": time.monotonic() - entry,
                      "timed_out": child_timed_out,
                      "cleanup_grace_seconds": cleanup_grace,
                      "cleanup_may_extend_observed_wall": True},
        "cleanup": cleanup,
        "child": {"returncode": child.returncode if child is not None else None,
                  "bridge_result": child_result, "stdout_tail": stdout[-2000:],
                  "stderr_tail": stderr[-2000:]},
        "trace": trace,
        "terminal_accounting": accounting,
        "trace_finalization_sidecar": sidecar,
        "error": error,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "development_only": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v11-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--cleanup-grace-seconds", type=float, default=5.0)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v11_request, args.output,
                                  cleanup_grace_seconds=args.cleanup_grace_seconds)
            result = {"status": value["status"], "sha256": value["sha256"]}
            code = 0
        elif args.command == "preflight":
            request = load_json(args.request)
            _validate_launch(request, verify_content=True)
            result = {"status": "READY_FOR_PARENT_IO_SLOT", "request_sha256": request["sha256"],
                      "ledger_mutated": False, "raw_opened": False, "hdf5_opened": False}
            code = 0
        else:
            value = run(args.request, parent_pid=args.parent_pid)
            result = value
            code = 0 if value["status"] == "COMPLETED_PARENT_SUPERVISED_DEVELOPMENT_UNKNOWN" else 2
    except (ParentLaunchError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
