#!/usr/bin/env python3
"""Forward external-filesystem solver runner with bounded parent accounting.

v1 remains immutable.  v2 keeps its source/storage contract but owns the
execution boundary and terminal accounting: the entry deadline covers
preflight, reservation, post-reservation source hashing, child execution and
posthash; receipt and ledger reuse one CPU cutoff; failure/cancel after a
registered reservation still produces one terminal charge and releases the
UUID lease.  Home receipt bytes and external product bytes remain separate
ledger dimensions.  The runner never creates a second ledger/data root and
never follows a symlink to bypass either filesystem floor.
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
import subprocess
import sys
import time
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
V1_PATH = SCRIPT_DIR / "ds_data02_stage2_external_solver_v1.py"
_SPEC = importlib.util.spec_from_file_location("ds02_external_solver_v1_for_v2", V1_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load external solver v1 dependency")
V1 = importlib.util.module_from_spec(_SPEC)
sys.path.insert(0, str(SCRIPT_DIR))
_SPEC.loader.exec_module(V1)


SCHEMA = "ds02.stage2.external-solver-request.v2"
REPORT_SCHEMA = "ds02.stage2.external-solver-report.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PR_SET_PDEATHSIG = 1


class ExternalSolverV2Error(RuntimeError):
    pass


class ExternalSolverV2Deadline(ExternalSolverV2Error):
    pass


class ExternalSolverV2Cancelled(ExternalSolverV2Error):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ExternalSolverV2Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ExternalSolverV2Error(f"JSON object required: {path}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise ExternalSolverV2Error(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str)
        stream.write("\n")
    return target


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime)


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform != "darwin" else value


def _load_runtime(request: Mapping[str, Any]):
    binding = request.get("runtime_binding")
    if not isinstance(binding, Mapping):
        raise ExternalSolverV2Error("runtime_binding is required")
    path = Path(str(binding.get("path", ""))).expanduser().resolve()
    if not path.is_file() or sha256_file(path) != str(binding.get("sha256")):
        raise ExternalSolverV2Error("shared runtime path or SHA differs")
    spec = importlib.util.spec_from_file_location("ds02_external_solver_runtime_v2", path)
    if spec is None or spec.loader is None:
        raise ExternalSolverV2Error("cannot import shared runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "ledger_locked", None)):
        raise ExternalSolverV2Error("runtime lacks ledger_locked")
    return module


def _v1_request_view(request: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(request))
    value["schema"] = V1.SCHEMA
    value["sha256"] = V1.canonical_sha(value)
    return value


def _validate_request(request: Mapping[str, Any], *, verify_content: bool = False) -> dict[str, Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ExternalSolverV2Error("unsupported or non-ready v2 request")
    if request.get("role") != "DEVELOPMENT" or request.get("qualification") != UNKNOWN:
        raise ExternalSolverV2Error("v2 request must remain development/UNKNOWN")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ExternalSolverV2Error("model/CFD invocation is forbidden")
    if request.get("sha256") != canonical_sha(request):
        raise ExternalSolverV2Error("v2 request canonical SHA differs")
    binding = request.get("v1_runner_binding")
    if not isinstance(binding, Mapping) or Path(str(binding.get("path", ""))).expanduser().resolve() != V1_PATH.resolve():
        raise ExternalSolverV2Error("v1 forward runner binding differs")
    if str(binding.get("sha256")) != sha256_file(V1_PATH):
        raise ExternalSolverV2Error("v1 forward runner SHA differs")
    view = _v1_request_view(request)
    try:
        checked = V1._validate_request(view, verify_content=verify_content)
    except Exception as error:
        raise ExternalSolverV2Error(str(error)) from error
    if not request.get("timing_contract", {}).get("entry_to_terminal_deadline"):
        raise ExternalSolverV2Error("entry-to-terminal timing contract is required")
    return checked


def _stop_child(proc: subprocess.Popen[str], grace: float = 1.0) -> dict[str, Any]:
    result = {"sigterm_sent": False, "forced_sigkill": False, "exited": proc.poll() is not None,
              "grace_seconds": float(grace)}
    if proc.poll() is not None:
        return result
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        result["sigterm_sent"] = True
    except (ProcessLookupError, PermissionError):
        pass
    until = time.monotonic() + max(0.01, grace)
    while proc.poll() is None and time.monotonic() < until:
        time.sleep(0.02)
    if proc.poll() is None:
        result["forced_sigkill"] = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=max(0.5, grace))
    except subprocess.TimeoutExpired:
        result["reap_bounded"] = False
    result["exited"] = proc.poll() is not None
    return result


def _parent_death(parent_pid: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot install parent-death signal")
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGTERM)


def _tree_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return int(V1._tree_bytes(root))


def _write_receipt(path: Path, receipt: dict[str, Any], external_bytes: int) -> int:
    # v1's fixed-point writer is reused only for deterministic Home receipt
    # sizing; v2 sets status and CPU cutoff before invoking it.
    return V1._write_receipt_fixed_point(path, receipt, external_bytes)


def _charge(runtime: Any, data_root: Path, attempt: str, reservation: Mapping[str, Any], *,
            external_bytes: int, home_bytes: int, cpu_seconds: float, gpu_seconds: float,
            status: str) -> dict[str, Any]:
    total = int(external_bytes + home_bytes)
    with runtime.ledger_locked(data_root) as ledger:
        existing = [row for row in ledger.get("charges", []) if row.get("id") == attempt]
        if existing:
            row = existing[-1]
            expected = (int(row.get("new_storage_bytes", -1)) == total
                        and row.get("status") == status
                        and int(row.get("external_storage_bytes", -1)) == int(external_bytes)
                        and int(row.get("home_storage_bytes", -1)) == int(home_bytes))
            if not expected:
                raise ExternalSolverV2Error("attempt charge already exists with different accounting")
            return {"status": "IDEMPOTENT_ALREADY_CHARGED", "charge": dict(row)}
        ledger["reservations"] = [row for row in ledger.get("reservations", []) if row.get("id") != attempt]
        finished = datetime.now(timezone.utc).isoformat()
        row = {
            "id": attempt, "gpu_seconds": float(gpu_seconds), "cpu_core_seconds": float(cpu_seconds),
            "new_storage_bytes": total, "external_storage_bytes": int(external_bytes),
            "home_storage_bytes": int(home_bytes), "storage_filesystems": [str(data_root), str(reservation["external_filesystem"])],
            "status": status, "finished_at_utc": finished,
            "accounting_scope": "same_parent_ledger_external_product_plus_home_receipt",
        }
        ledger.setdefault("charges", []).append(row)
        for item in ledger.get("attempts", []):
            if item.get("id") == attempt:
                item.update(status=status, finished_at_utc=finished)
    return {"status": "CHARGE_APPLIED", "charge": row}


def _install_signals(max_wall: float):
    previous = {signal.SIGALRM: signal.getsignal(signal.SIGALRM), signal.SIGTERM: signal.getsignal(signal.SIGTERM), signal.SIGINT: signal.getsignal(signal.SIGINT)}
    def deadline(_signal, _frame):
        raise ExternalSolverV2Deadline("entry-to-terminal wall deadline exceeded")
    def cancel(signum, _frame):
        raise ExternalSolverV2Cancelled("parent or supervisor cancellation signal " + str(signum))
    signal.signal(signal.SIGALRM, deadline)
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, max_wall))
    return previous


def _restore_signals(previous: Mapping[int, Any]) -> None:
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def run(request_path: Path | str, *, io_slot_approved: bool = False, parent_pid: int | None = None) -> dict[str, Any]:
    entry_wall = time.monotonic()
    entry_cpu = _cpu_seconds()
    request_file = Path(request_path).expanduser().resolve()
    request = load_json(request_file)
    max_wall = float(request.get("max_wall_seconds", 0))
    if not math.isfinite(max_wall) or max_wall <= 0:
        raise ExternalSolverV2Error("max_wall_seconds must be positive")
    if not io_slot_approved:
        checked = _validate_request(request, verify_content=False)
        return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT", "request_sha256": sha256_file(request_file),
                "input_count": len(checked["files"]), "ledger_mutated": False, "raw_opened": False,
                "hdf5_opened": False, "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}
    previous = _install_signals(max_wall)
    registered = False
    runtime = None
    data_root: Path | None = None
    attempt = f"{request['family_id']}/{request['case_id']}/{request['attempt_id']}"
    output: Path | None = None
    receipt_path: Path | None = None
    lease_path: Path | None = None
    process: subprocess.Popen[str] | None = None
    termination: str | None = None
    status = "failed"
    returncode: int | None = None
    cleanup: dict[str, Any] = {}
    source_verified = False
    try:
        checked = _validate_request(request, verify_content=False)
        data_root = checked["data_root"]
        storage = checked["storage"]
        scope = request["storage_scope"]
        output = Path(str(scope["output_root"])).expanduser().resolve()
        receipt_path = data_root / "families" / request["family_id"] / request["case_id"] / request["attempt_id"] / "execution-receipt.json"
        if output.exists() or receipt_path.exists():
            raise ExternalSolverV2Error("attempt output or receipt already exists")
        runtime = _load_runtime(request)
        if parent_pid is not None and os.getppid() != int(parent_pid):
            raise ExternalSolverV2Cancelled("supervising parent already exited")
        gpu_info = V1._gpu_snapshot_and_select(runtime, request, data_root)
        device = gpu_info["device"]
        reservation = {
            "id": attempt, "kind": request["kind"], "cpu_threads": int(request["cpu_threads"]),
            "cpu_core_seconds": int(request["cpu_threads"]) * max_wall, "gpu_seconds": max_wall,
            "new_storage_bytes": int(scope["new_storage_bytes"]),
            "home_storage_bytes": int(scope["home_receipt_reserved_bytes"]),
            "external_storage_bytes": int(scope["external_product_reserved_bytes"]),
            "external_filesystem": str(scope["external_filesystem"]), "reserved_at_utc": datetime.now(timezone.utc).isoformat(),
            "launcher_pid": os.getpid(), "host": os.uname().nodename, "gpu_uuid": str(device["uuid"]),
        }
        with runtime.ledger_locked(data_root) as ledger:
            live_home = V1._disk_probe(Path(str(ledger["limits"]["home_path"])))
            live_external = V1._disk_probe(Path(str(scope["external_filesystem"])))
            V1._check_two_fs_reservation(ledger, reservation,
                                          home_free=live_home["free_bytes"], external_free=live_external["free_bytes"],
                                          home_floor=int(scope["home_min_free_bytes"]), external_floor=int(scope["external_min_free_bytes"]))
            lease_path = data_root / "leases" / (str(device["uuid"]) + ".json")
            if lease_path.exists():
                raise ExternalSolverV2Error("GPU UUID lease appeared during reservation")
            lease_path.parent.mkdir(parents=True, exist_ok=True)
            with lease_path.open("x", encoding="utf-8") as stream:
                json.dump({"schema": "ds02.gpu-lease.v1", "uuid": device["uuid"], "attempt_id": attempt, "launcher_pid": os.getpid(), "parent_pid": parent_pid}, stream)
                stream.write("\n")
            ledger.setdefault("reservations", []).append(reservation)
            ledger.setdefault("attempts", []).append({"id": attempt, "kind": request["kind"], "status": "reserved", "started_at_utc": datetime.now(timezone.utc).isoformat()})
            registered = True
        # Expensive input content validation begins only after parent reserve.
        _validate_request(request, verify_content=True)
        source_verified = True
        if output is None:
            raise ExternalSolverV2Error("output was not bound")
        output.mkdir(parents=True, exist_ok=False)
        command = [arg.replace("{output_root}", str(output)).replace("{attempt_root}", str(output)) for arg in request["command"]]
        env = os.environ.copy()
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            env[name] = str(request["cpu_threads"])
        env["CUDA_VISIBLE_DEVICES"] = str(device["uuid"])
        if parent_pid is not None:
            env["DS02_PARENT_PID"] = str(parent_pid)
        launcher_pid = os.getpid()
        log_path = output / "stdout.log"
        with log_path.open("x", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=str(Path(request["cwd"]).expanduser().resolve()), env=env,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                       preexec_fn=(lambda: _parent_death(launcher_pid)) if parent_pid is not None else None)
            while process.poll() is None:
                if parent_pid is not None and os.getppid() != int(parent_pid):
                    raise ExternalSolverV2Cancelled("supervising parent exited")
                time.sleep(0.05)
            returncode = process.returncode
        status = "completed" if returncode == 0 else "failed"
        if status != "completed":
            termination = f"solver_returncode_{returncode}"
    except (ExternalSolverV2Deadline, ExternalSolverV2Cancelled) as error:
        status = "failed"
        termination = str(error)
        if process is not None:
            cleanup = _stop_child(process)
    except BaseException as error:
        status = "failed"
        termination = f"{type(error).__name__}: {error}"
        if process is not None:
            cleanup = _stop_child(process)
    finally:
        # No expensive source posthash is attempted after a deadline/cancel.
        _restore_signals(previous)
        external_bytes = _tree_bytes(output) if output is not None and output.exists() else 0
        cutoff_cpu = max(0.0, _cpu_seconds() - entry_cpu)
        receipt: dict[str, Any] = {
            "schema": REPORT_SCHEMA,
            "status": "COMPLETED_DEVELOPMENT_UNKNOWN" if status == "completed" else "FAILED_EXTERNAL_SOLVER",
            "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "attempt_id": attempt, "parent_ledger": {"path": str(data_root / "runtime/resource-ledger.json") if data_root else None, "same_parent_lock": True, "reservation_registered": registered, "ledger_reset": False},
            "gpu": {"uuid": request.get("gpu", {}).get("gpu_uuid"), "lease_path": str(lease_path) if lease_path else None},
            "filesystem": {"output_root": str(output) if output else None, "external_product_bytes": external_bytes, "home_receipt_bytes": 0, "measured_total_bytes": 0},
            "execution": {"returncode": returncode, "termination": termination, "cleanup": cleanup, "wall_seconds_from_entry": time.monotonic() - entry_wall, "cpu_core_seconds": cutoff_cpu, "max_rss_observed_bytes": _max_rss_bytes(), "source_verified_after_reservation": source_verified, "entry_to_terminal_deadline": True},
            "source_validation": {"content_verified": source_verified, "content_started_after_reservation": registered},
            "timing_scope": {"cpu_cutoff": "after_source_posthash_and_external_output_measurement_before_terminal_receipt_write", "receipt_and_ledger_reuse_same_cpu_cutoff": True},
            "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN), "original_path_fallback": "FORBIDDEN",
        }
        if receipt_path is not None and registered:
            try:
                home_bytes = _write_receipt(receipt_path, receipt, external_bytes)
                receipt["filesystem"]["home_receipt_bytes"] = home_bytes
                receipt["filesystem"]["measured_total_bytes"] = external_bytes + home_bytes
            except BaseException as error:
                status = "failed"
                receipt["status"] = "FAILED_EXTERNAL_SOLVER"
                receipt["execution"]["termination"] = f"receipt_finalization: {type(error).__name__}: {error}"
                home_bytes = 0
            if runtime is not None and data_root is not None:
                charge_status = receipt["status"]
                # Lease removal is in the finally block even when the parent
                # ledger refuses a terminal charge.  Leaving a UUID lease
                # behind would make a failed attempt indistinguishable from a
                # live solver and would block the next parent-scheduled job.
                try:
                    _charge(runtime, data_root, attempt,
                            {"external_filesystem": request["storage_scope"]["external_filesystem"]},
                            external_bytes=external_bytes, home_bytes=home_bytes, cpu_seconds=cutoff_cpu,
                            gpu_seconds=max(0.0, min(max_wall, time.monotonic() - entry_wall)), status=charge_status)
                finally:
                    if lease_path is not None:
                        lease_path.unlink(missing_ok=True)
            elif lease_path is not None:
                lease_path.unlink(missing_ok=True)
        else:
            home_bytes = 0
        if lease_path is not None and not registered:
            lease_path.unlink(missing_ok=True)
    return {"schema": REPORT_SCHEMA, "status": receipt["status"], "attempt_id": attempt,
            "output_root": str(output) if output else None, "receipt_path": str(receipt_path) if receipt_path else None,
            "terminal_charge_written": registered, "external_product_bytes": external_bytes, "home_receipt_bytes": home_bytes,
            "cpu_core_seconds": receipt["execution"]["cpu_core_seconds"], "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "run"):
        command = sub.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--io-slot-approved", action="store_true")
        command.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        value = run(args.request, io_slot_approved=False, parent_pid=args.parent_pid)
    else:
        if not args.io_slot_approved:
            parser.error("approved v2 solver run requires --io-slot-approved")
        value = run(args.request, io_slot_approved=True, parent_pid=args.parent_pid)
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0 if str(value.get("status", "")).startswith(("COMPLETED_", "READY_", "IDEMPOTENT")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
