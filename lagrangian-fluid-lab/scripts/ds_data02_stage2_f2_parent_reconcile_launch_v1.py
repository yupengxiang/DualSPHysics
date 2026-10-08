#!/usr/bin/env python3
"""Reconcile the interrupted F2 parent attempt and build a bounded retry.

This is an additive, read-only-by-default companion to the consumed v3
parent guard.  ``reconcile`` is the only mutating subcommand: it requires an
explicit observed PID/PGID termination set, verifies that the old output
namespace contains only the measured trace/log files, and applies one
conservative failed charge to the *same* Stage2 ledger.  It never releases a
reservation without that charge.  ``build-retry`` is allowed only after the
charge is visible and the old reservation is gone.

``systemd-command`` emits a command for a root-owned transient user service;
it does not start the service.  ``launch`` is the small service entrypoint
which keeps a direct parent process alive while it starts the v3 guard with a
literal virtualenv path.  Systemd owns the outer deadline and journal; the v3
guard remains the sole Stage2 ledger writer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V3_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_parent_v3.py"
DEFAULT_REQUEST = SCRIPT_DIR.parent / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v34-full-chain/"
    "f2-s1-portable-executor-parent-request-v3-047.json")
DEFAULT_RECONCILIATION = SCRIPT_DIR.parent / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v34-full-chain/"
    "f2-s1-portable-executor-parent-reconciliation-v1-047.json")
DEFAULT_RETRY = SCRIPT_DIR.parent / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v34-full-chain/"
    "f2-s1-portable-executor-parent-request-v3-050.json")
DEFAULT_RETRY_OUTPUT_ROOT = Path(
    "/var/tmp/ds02-stage2/ds-data-02/families/F2/"
    "STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5/f2-s1-v34-parent-050")
DEFAULT_RETRY_RECEIPT = SCRIPT_DIR.parent / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v34-full-chain/"
    "f2-s1-portable-executor-parent-report-v3-050.json")
SCHEMA = "ds02.stage2.f2-parent-reconcile-launch.v1"
RECONCILIATION_STATUS = "RECONCILED_INTERRUPTED_PARENT_FAILED"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
EXPECTED_OLD_REQUEST_SHA = "3df45c105c613a0af402341dddec86bc6acaafa77a0288bae5e65f88ebec0cf2"
EXPECTED_ATTEMPT = "f2-s1-portable-executor-v34-047"
EXPECTED_RESERVATION = EXPECTED_ATTEMPT + "::f2-v34-parent-v3-reservation"
EXPECTED_CHARGE = EXPECTED_ATTEMPT + "::f2-v34-parent-v3-charge"
EXPECTED_CPU_RESERVATION = 6000.0
EXPECTED_TRACE_BYTES = 2_264_442
RETRY_ATTEMPT = "f2-s1-portable-executor-v34-050"
PR_SET_PDEATHSIG = 1


class ReconcileError(RuntimeError):
    pass


def _load_v3():
    spec = importlib.util.spec_from_file_location("ds02_reconcile_bound_parent_v3", V3_PATH)
    if spec is None or spec.loader is None:
        raise ReconcileError(f"cannot load parent v3: {V3_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load_v3()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReconcileError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise ReconcileError(f"JSON object required: {target}")
    return value


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ReconcileError(f"{role} must be a lowercase SHA-256")
    return value


def _write_new_json(path: Path, value: Mapping[str, Any], encoded: bytes | None = None) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        raise ReconcileError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = encoded or ((json.dumps(value, indent=2, sort_keys=True,
                                      ensure_ascii=False, allow_nan=False,
                                      default=str) + "\n").encode("utf-8"))
    with target.open("xb") as stream:
        stream.write(payload)


def _fixed_report_bytes(value: dict[str, Any]) -> tuple[bytes, int]:
    predicted = 0
    for _ in range(32):
        value["filesystem"]["home_receipt_bytes"] = int(predicted)
        value["sha256"] = canonical_sha(value)
        encoded = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                               allow_nan=False, default=str) + "\n").encode("utf-8")
        if len(encoded) == predicted:
            return encoded, predicted
        predicted = len(encoded)
    raise ReconcileError("reconciliation receipt size fixed point did not converge")


def _tree_bytes(root: Path) -> int:
    total = 0
    root = root.expanduser().resolve()
    if not root.is_dir():
        return 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ReconcileError(f"symlink output file is forbidden: {path}")
            total += int(path.stat().st_size)
    return total


def _prefix_files(prefix: Path) -> list[Path]:
    prefix = prefix.expanduser().resolve()
    paths = []
    if prefix.is_file():
        paths.append(prefix)
    paths.extend(sorted(path for path in prefix.parent.glob(prefix.name + ".*")
                        if path.is_file() and not path.is_symlink()))
    return sorted(set(paths))


def _pid_absent(pid: int) -> bool:
    return not Path(f"/proc/{int(pid)}").exists()


def _proc_pgid(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
        fields = stat.rsplit(")", 1)[1].strip().split()
        # After the comm field: state, ppid, pgrp, session.
        return int(fields[2])
    except (OSError, IndexError, ValueError):
        return None


def _pgid_absent(pgid: int) -> bool:
    proc_root = Path("/proc")
    try:
        entries = list(proc_root.iterdir())
    except OSError as error:
        raise ReconcileError(f"cannot inspect /proc for PGID closure: {error}") from error
    for entry in entries:
        if not entry.name.isdigit():
            continue
        if _proc_pgid(int(entry.name)) == int(pgid):
            return False
    return True


def _load_old_request(path: Path) -> tuple[dict[str, Any], Path, Path, Path]:
    request = load_json(path)
    if request.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3":
        raise ReconcileError("old request schema is not v3")
    actual_sha = canonical_sha(request)
    if request.get("sha256") != actual_sha or actual_sha != EXPECTED_OLD_REQUEST_SHA:
        raise ReconcileError("old request canonical SHA is not the frozen 047 SHA")
    parent = request.get("parent_resource_binding")
    storage = request.get("storage_scope")
    if not isinstance(parent, Mapping) or not isinstance(storage, Mapping):
        raise ReconcileError("old request parent/storage binding is incomplete")
    if str(parent.get("attempt_id")) != EXPECTED_ATTEMPT:
        raise ReconcileError("old request attempt differs")
    if str(parent.get("reservation_id")) != EXPECTED_RESERVATION:
        raise ReconcileError("old request reservation differs")
    if str(parent.get("charge_id")) != EXPECTED_CHARGE:
        raise ReconcileError("old request charge differs")
    if float(request.get("execution", {}).get("max_wall_seconds", 0.0)) != EXPECTED_CPU_RESERVATION:
        raise ReconcileError("old request CPU reservation is not 6000 seconds")
    ledger = Path(str(parent.get("ledger_path"))).expanduser().resolve()
    external = Path(str(storage.get("external_filesystem"))).expanduser().resolve()
    output_root = Path(str(storage.get("supervisor_output_root"))).expanduser().resolve()
    receipt = Path(str(storage.get("home_receipt_path"))).expanduser().resolve()
    if not ledger.is_file() or not external.is_dir() or not output_root.is_dir():
        raise ReconcileError("old request ledger/external/output binding is unavailable")
    if receipt.exists():
        raise ReconcileError("old v3 receipt already exists; refusing to overwrite it")
    return request, ledger, external, output_root


def _ledger_rows(ledger: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    value = load_json(ledger)
    reservations = [row for row in value.get("reservations", []) if isinstance(row, dict)]
    charges = [row for row in value.get("charges", []) if isinstance(row, dict)]
    return value, reservations, charges


def _bound_for_charge(request: Mapping[str, Any], ledger: Path, external: Path,
                      limits: Mapping[str, Any]) -> dict[str, Any]:
    parent = request["parent_resource_binding"]
    runtime = request["runtime_binding"]
    runtime_path = Path(str(runtime["path"])).expanduser().resolve()
    if not runtime_path.is_file() or sha256_file(runtime_path) != str(runtime["sha256"]):
        raise ReconcileError("shared runtime changed before reconciliation")
    return {
        "request": request, "ledger": ledger, "external": external,
        "runtime_path": runtime_path, "runtime_sha": str(runtime["sha256"]),
        "limits": dict(limits), "parent_attempt_id": str(parent["attempt_id"]),
        "reservation_id": str(parent["reservation_id"]),
        "charge_id": str(parent["charge_id"]),
        "allow_missing_parent": bool(parent.get("allow_missing_parent", False)),
    }


def reconcile(*, request_path: Path, receipt_path: Path, observed_pids: Sequence[int],
              observed_pgids: Sequence[int], expected_trace_bytes: int = EXPECTED_TRACE_BYTES,
              cpu_seconds: float = EXPECTED_CPU_RESERVATION,
              trace_pid: int = 1946669) -> dict[str, Any]:
    """Apply one conservative failed charge after independently observed death."""
    request, ledger, external, output_root = _load_old_request(request_path)
    if tuple(sorted(set(int(pid) for pid in observed_pids))) == ():
        raise ReconcileError("an explicit observed PID set is required")
    if tuple(sorted(set(int(pid) for pid in observed_pgids))) == ():
        raise ReconcileError("an explicit observed PGID set is required")
    missing_pids = [pid for pid in observed_pids if not _pid_absent(int(pid))]
    missing_pgids = [pgid for pgid in observed_pgids if not _pgid_absent(int(pgid))]
    if missing_pids or missing_pgids:
        raise ReconcileError(
            f"observed process/group is still alive: pids={sorted(set(missing_pids))}, "
            f"pgids={sorted(set(missing_pgids))}")
    if float(cpu_seconds) != EXPECTED_CPU_RESERVATION:
        raise ReconcileError("reconciliation CPU must remain the full reserved 6000 seconds")
    value, reservations, charges = _ledger_rows(ledger)
    reservation_rows = [row for row in reservations if row.get("id") == EXPECTED_RESERVATION]
    charge_rows = [row for row in charges if row.get("id") == EXPECTED_CHARGE]
    if len(reservation_rows) > 1:
        raise ReconcileError("duplicate 047 reservation rows")
    if len(charge_rows) > 1:
        raise ReconcileError("duplicate 047 charge rows")
    if charge_rows:
        if reservation_rows:
            raise ReconcileError("charge exists while old reservation remains active")
        existing = charge_rows[-1]
        if float(existing.get("cpu_core_seconds", -1.0)) != EXPECTED_CPU_RESERVATION:
            raise ReconcileError("existing 047 charge CPU differs")
        return {"schema": SCHEMA, "status": "ALREADY_RECONCILED", "charge": existing,
                "reservation_present": False, "receipt": str(receipt_path)}
    if len(reservation_rows) != 1 or reservation_rows[0].get("status") != "reserved":
        raise ReconcileError("old 047 reservation is not the single reserved row")
    reservation = reservation_rows[0]
    if float(reservation.get("cpu_core_seconds", -1.0)) != EXPECTED_CPU_RESERVATION:
        raise ReconcileError("reservation CPU differs from the observed 6000-second ceiling")
    if int(reservation.get("home_storage_bytes", -1)) != int(request["storage_scope"]["home_receipt_bytes"]):
        raise ReconcileError("reservation Home bytes differ from request")
    if str(reservation.get("storage_filesystems", [None, None])[0]) != str(external):
        raise ReconcileError("reservation external filesystem differs from request")
    if int(reservation.get("external_storage_bytes", -1)) != int(request["storage_scope"]["external_reservation_bytes"]):
        raise ReconcileError("reservation external bytes differ from request")
    files = _prefix_files(output_root / "os-trace-v34")
    expected_trace = output_root / f"os-trace-v34.{int(trace_pid)}"
    if expected_trace not in files:
        raise ReconcileError(f"expected terminated worker trace is missing: {expected_trace}")
    trace_bytes = sum(int(path.stat().st_size) for path in files)
    if trace_bytes != int(expected_trace_bytes):
        raise ReconcileError(f"trace bytes differ: observed {trace_bytes}, expected {expected_trace_bytes}")
    allowed = {expected_trace.name, "parent-executor.stdout.log", "parent-executor.stderr.log"}
    unexpected = sorted(path.name for path in files if path.name not in allowed)
    for directory, dirs, names in os.walk(output_root, followlinks=False):
        if Path(directory).resolve() != output_root and (dirs or names):
            raise ReconcileError(f"unexpected nested output below interrupted namespace: {directory}")
    if unexpected:
        raise ReconcileError(f"unexpected interrupted output files: {unexpected}")
    log_bytes = sum((output_root / name).stat().st_size for name in
                    ("parent-executor.stdout.log", "parent-executor.stderr.log")
                    if (output_root / name).is_file())
    if log_bytes != 0:
        raise ReconcileError(f"interrupted parent logs are nonempty: {log_bytes}")
    external_bytes = _tree_bytes(output_root)
    if external_bytes != trace_bytes:
        raise ReconcileError("interrupted external bytes are not exactly the trace bytes")
    limits = value.get("limits", {})
    bound = _bound_for_charge(request, ledger, external, limits)
    now = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": RECONCILIATION_STATUS,
        "created_at_utc": now,
        "old_request": {"path": str(request_path.resolve()), "sha256": EXPECTED_OLD_REQUEST_SHA},
        "observed_termination": {
            "pids": sorted(set(int(pid) for pid in observed_pids)),
            "pgids": sorted(set(int(pid) for pid in observed_pgids)),
            "all_absent_at_check": True,
            "trace_worker_pid": int(trace_pid),
        },
        "filesystem": {
            "external_filesystem": str(external), "output_root": str(output_root),
            "trace_files": [str(path) for path in files],
            "trace_bytes": trace_bytes, "new_external_bytes": external_bytes,
            "copied_files": 0, "stdout_stderr_bytes": log_bytes,
            "home_receipt_path": str(receipt_path.resolve()), "home_receipt_bytes": 0,
        },
        "accounting": {
            "ledger_path": str(ledger), "same_parent_ledger": True, "ledger_reset": False,
            "reservation_id": EXPECTED_RESERVATION, "charge_id": EXPECTED_CHARGE,
            "cpu_core_seconds": float(cpu_seconds),
            "cpu_accounting_status": "UNKNOWN_CONSERVATIVE_RESERVED_CEILING",
            "external_storage_bytes": external_bytes, "home_storage_bytes": None,
            "trace_bytes": trace_bytes, "copy_hash_bytes": 0,
            "release_requires_successful_charge": True,
        },
        "hdf5_or_bi4_content_read": "UNKNOWN_AFTER_INTERRUPTED_SOURCE_PHASE",
        "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "limitations": [
            "The interrupted worker CPU usage is unavailable; the full 6000-second reservation ceiling is charged conservatively.",
            "The trace proves only the observed file/process syscall bytes; it does not reconstruct source-read completion.",
            "This receipt does not convert the interrupted attempt into a successful replay or scientific evidence.",
        ],
    }
    encoded, home_bytes = _fixed_report_bytes(report)
    report["accounting"]["home_storage_bytes"] = home_bytes
    encoded, home_bytes = _fixed_report_bytes(report)
    # Charge first and never release on an accounting error.  The immutable
    # receipt is written immediately after the ledger charge with the exact
    # byte count supplied to it.
    charge = V3._charge(bound, status="failed", cpu_seconds=float(cpu_seconds),
                        external_bytes=external_bytes, home_bytes=home_bytes,
                        trace_bytes=trace_bytes, copy_hash_bytes=0,
                        allow_missing_parent=bound["allow_missing_parent"])
    _write_new_json(receipt_path.resolve(), report, encoded)
    post_value, post_reservations, post_charges = _ledger_rows(ledger)
    if any(row.get("id") == EXPECTED_RESERVATION for row in post_reservations):
        raise ReconcileError("reservation remained after successful charge")
    if not any(row.get("id") == EXPECTED_CHARGE for row in post_charges):
        raise ReconcileError("charge disappeared after successful charge")
    return {"schema": SCHEMA, "status": RECONCILIATION_STATUS,
            "receipt_path": str(receipt_path.resolve()), "receipt_sha256": sha256_file(receipt_path),
            "charge": charge, "trace_bytes": trace_bytes, "cpu_core_seconds": float(cpu_seconds),
            "reservation_present": False, "qualification": dict(UNKNOWN)}


def _assert_reconciled(request_path: Path, reconciliation_path: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    request = load_json(request_path)
    if request.get("sha256") != EXPECTED_OLD_REQUEST_SHA:
        raise ReconcileError("retry source is not the frozen 047 request")
    receipt = load_json(reconciliation_path)
    if receipt.get("schema") != SCHEMA or receipt.get("status") != RECONCILIATION_STATUS:
        raise ReconcileError("reconciliation receipt is not a completed conservative 047 closure")
    if receipt.get("old_request", {}).get("sha256") != EXPECTED_OLD_REQUEST_SHA:
        raise ReconcileError("reconciliation receipt is bound to another request")
    ledger = Path(str(request["parent_resource_binding"]["ledger_path"])).expanduser().resolve()
    value, reservations, charges = _ledger_rows(ledger)
    charge = next((row for row in charges if row.get("id") == EXPECTED_CHARGE), None)
    if charge is None or str(charge.get("status")) != "failed":
        raise ReconcileError("same-parent failed charge is not visible")
    if any(row.get("id") == EXPECTED_RESERVATION for row in reservations):
        raise ReconcileError("old reservation is still active")
    if float(charge.get("cpu_core_seconds", -1.0)) != EXPECTED_CPU_RESERVATION:
        raise ReconcileError("old failed charge is not the conservative 6000-second ceiling")
    return request, ledger, charge


def build_retry(*, request_path: Path, reconciliation_path: Path, executor_request: Path,
                output: Path,
                output_root: Path, receipt: Path, parent_attempt_id: str = RETRY_ATTEMPT,
                max_wall_seconds: float = EXPECTED_CPU_RESERVATION) -> dict[str, Any]:
    request, ledger, charge = _assert_reconciled(request_path, reconciliation_path)
    if output.resolve() == request_path.resolve():
        raise ReconcileError("retry request cannot overwrite 047")
    external = Path(str(request["parent_resource_binding"]["external_filesystem"])).expanduser().resolve()
    if output_root.exists() or receipt.exists():
        raise ReconcileError("retry output namespace or receipt already exists")
    executor_request = executor_request.expanduser().resolve()
    if not executor_request.is_file():
        raise ReconcileError(f"fresh v34 executor request is missing: {executor_request}")
    if executor_request == Path(str(request["executor_request"]["path"])).expanduser().resolve():
        raise ReconcileError("retry must bind a newly built v34 request with fresh roots")
    built = V3.build_request(
        executor_request=executor_request, output=output,
        external_filesystem=external, ledger_path=ledger,
        parent_attempt_id=parent_attempt_id, max_wall_seconds=max_wall_seconds,
        external_bytes=int(request["storage_scope"]["external_reservation_bytes"]),
        home_receipt_bytes=int(request["storage_scope"]["home_receipt_bytes"]),
        home_receipt_path=receipt, supervisor_output_root=output_root,
        home_path=request["parent_resource_binding"]["home_path"],
        external_min_free_bytes=int(request["storage_scope"]["external_min_free_bytes"]),
        home_min_free_bytes=int(request["parent_resource_binding"]["home_min_free_bytes"]),
        runtime_v6=request["runtime_binding"]["path"],
        executor_script=request["executor_script"]["path"],
        allow_missing_parent=bool(request["parent_resource_binding"].get("allow_missing_parent", True)),
    )
    return {"schema": SCHEMA, "status": "RETRY_REQUEST_READY_FOR_ROOT_GUARD",
            "request_path": str(output.resolve()), "request_sha256": built["sha256"],
            "supersedes": str(request_path.resolve()), "reconciliation": str(reconciliation_path.resolve()),
            "old_charge_id": str(charge["id"]), "qualification": dict(UNKNOWN)}


def _literal_python(request: Mapping[str, Any]) -> Path:
    command = request.get("execution", {}).get("closed_executor_command", [])
    if not isinstance(command, list) or not command or not isinstance(command[0], str):
        raise ReconcileError("retry request has no literal venv command")
    python = Path(command[0]).expanduser()
    if not python.is_file():
        raise ReconcileError(f"literal venv interpreter is missing: {python}")
    return python


def systemd_command(*, request_path: Path, unit: str, launcher: Path = SCRIPT) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3":
        raise ReconcileError("systemd command requires a v3 retry request")
    if str(request.get("parent_resource_binding", {}).get("attempt_id")) == EXPECTED_ATTEMPT:
        raise ReconcileError("systemd command refuses the interrupted 047 request")
    python = _literal_python(request)
    launcher = launcher.expanduser().resolve()
    if not launcher.is_file():
        raise ReconcileError(f"launcher is missing: {launcher}")
    # Do not resolve argv[0]: the virtualenv path is part of the ABI binding.
    command = [str(python), "-B", "-I", str(launcher), "launch",
               "--request", str(request_path.expanduser().resolve()),
               "--parent-v3", str(V3_PATH), "--python", str(python)]
    systemd = ["/usr/bin/systemd-run", "--user", "--unit", unit, "--collect",
               "--property=Type=exec", "--property=RemainAfterExit=yes",
               "--property=RuntimeMaxSec=6300", "--property=TimeoutStopSec=45",
               "--property=KillMode=mixed", "--property=CPUAccounting=yes",
               "--property=MemoryAccounting=yes", "--property=StandardOutput=journal",
               "--property=StandardError=journal", "--"] + command
    return {"schema": SCHEMA, "status": "SYSTEMD_COMMAND_READY_NOT_STARTED",
            "unit": unit, "request": str(request_path.resolve()), "request_sha256": sha256_file(request_path),
            "literal_python": str(python), "systemd_argv": systemd,
            "journal_output": True, "service_started": False,
            "runtime_max_seconds": 6300, "timeout_stop_seconds": 45,
            "qualification": dict(UNKNOWN)}


def _pdeath(parent_pid: int) -> None:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError("cannot install parent-death signal")
    if os.getppid() != int(parent_pid):
        os.kill(os.getpid(), signal.SIGTERM)


def launch(*, request_path: Path, parent_v3: Path, python: Path) -> int:
    """Service entry: keep a direct parent for v3 and forward its journal."""
    request_path = request_path.expanduser().resolve()
    parent_v3 = parent_v3.expanduser().resolve()
    python = python.expanduser()
    if not request_path.is_file() or not parent_v3.is_file() or not python.is_file():
        raise ReconcileError("systemd launcher binding is missing")
    request = load_json(request_path)
    if request.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3":
        raise ReconcileError("launcher request schema differs")
    if _literal_python(request) != python:
        raise ReconcileError("launcher interpreter differs from request literal path")
    wrapper_pid = os.getpid()
    command = [str(python), "-B", "-I", str(parent_v3), "run", "--request", str(request_path),
               "--io-slot-approved", "--parent-pid", str(wrapper_pid)]
    env = os.environ.copy()
    env.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"})
    child = subprocess.Popen(command, stdout=None, stderr=None, env=env,
                             start_new_session=False,
                             preexec_fn=lambda pid=wrapper_pid: _pdeath(pid))
    return int(child.wait())


def status(*, unit: str) -> dict[str, Any]:
    command = ["/usr/bin/systemctl", "--user", "show", unit,
               "--property=ActiveState,SubState,ExecMainPID,CPUUsageNSec,Result", "--no-pager"]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    return {"schema": SCHEMA, "status": "SYSTEMD_STATUS_READONLY", "unit": unit,
            "systemctl_returncode": result.returncode, "fields": fields,
            "stderr": result.stderr[-1000:], "service_started_by_this_command": False}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    reconcile_parser = sub.add_parser("reconcile")
    reconcile_parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    reconcile_parser.add_argument("--receipt", type=Path, default=DEFAULT_RECONCILIATION)
    reconcile_parser.add_argument("--observed-pids", type=int, nargs="+", required=True)
    reconcile_parser.add_argument("--observed-pgids", type=int, nargs="+", required=True)
    reconcile_parser.add_argument("--trace-pid", type=int, default=1946669)
    reconcile_parser.add_argument("--expected-trace-bytes", type=int, default=EXPECTED_TRACE_BYTES)
    retry_parser = sub.add_parser("build-retry")
    retry_parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    retry_parser.add_argument("--reconciliation", type=Path, default=DEFAULT_RECONCILIATION)
    retry_parser.add_argument("--executor-request", type=Path, required=True,
                              help="new v34 request with fresh target/output roots")
    retry_parser.add_argument("--output", type=Path, default=DEFAULT_RETRY)
    retry_parser.add_argument("--output-root", type=Path, default=DEFAULT_RETRY_OUTPUT_ROOT)
    retry_parser.add_argument("--receipt", type=Path, default=DEFAULT_RETRY_RECEIPT)
    retry_parser.add_argument("--parent-attempt-id", default=RETRY_ATTEMPT)
    retry_parser.add_argument("--max-wall-seconds", type=float, default=EXPECTED_CPU_RESERVATION)
    systemd_parser = sub.add_parser("systemd-command")
    systemd_parser.add_argument("--request", type=Path, required=True)
    systemd_parser.add_argument("--unit", required=True)
    systemd_parser.add_argument("--launcher", type=Path, default=SCRIPT)
    launch_parser = sub.add_parser("launch")
    launch_parser.add_argument("--request", type=Path, required=True)
    launch_parser.add_argument("--parent-v3", type=Path, required=True)
    launch_parser.add_argument("--python", type=Path, required=True)
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--unit", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "reconcile":
            value = reconcile(request_path=args.request, receipt_path=args.receipt,
                              observed_pids=args.observed_pids, observed_pgids=args.observed_pgids,
                              expected_trace_bytes=args.expected_trace_bytes, trace_pid=args.trace_pid)
        elif args.command == "build-retry":
            value = build_retry(request_path=args.request, reconciliation_path=args.reconciliation,
                                executor_request=args.executor_request,
                                output=args.output, output_root=args.output_root, receipt=args.receipt,
                                parent_attempt_id=args.parent_attempt_id,
                                max_wall_seconds=args.max_wall_seconds)
        elif args.command == "systemd-command":
            value = systemd_command(request_path=args.request, unit=args.unit, launcher=args.launcher)
        elif args.command == "launch":
            return launch(request_path=args.request, parent_v3=args.parent_v3, python=args.python)
        else:
            value = status(unit=args.unit)
    except (ReconcileError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"parent reconcile/launch v1: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
