#!/usr/bin/env python3
"""Forward CPU runtime with reservation-before-content-hash semantics.

The consumed v6 runner still validates and hashes every input before it can
register an attempt.  That loses the cost of a large F3/F7 source preflight
from the parent's active reservation and leaves no bounded cancellation point
while hashing.  v8 is an additive CPU-only runner: it performs cheap request
and ``stat`` checks, registers the attempt under the existing Stage2 ledger,
then performs the digest-bound content validation inside an entry-to-terminal
wall/cancellation guard.  HDF5/BI4 content is never opened by this module
without a parent scheduler approving the request.

The v6 runtime remains the receipt/fixed-point implementation dependency, but
the v8 runner owns the ordering and deadline boundary.  QI/QN/QE are not
granted by this executable.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import time
from typing import Any

import ds_data02_runtime_v6 as v6


base = v6.base
DATA_ROOT = base.DATA_ROOT
RUNTIME_PATH = str(Path(__file__).resolve())
V6_RUNTIME_PATH = str(Path(v6.__file__).resolve())
ledger_locked = v6.ledger_locked
tree_bytes = v6.tree_bytes
check_reservation = v6.check_reservation

_base_validate = v6.validate_request
_base_atomic_json = v6._base_atomic_json
_active_v6_root: Path | None = None


class RuntimeV8Deadline(RuntimeError):
    """Entry-to-terminal v8 wall deadline was reached."""


class RuntimeV8Cancelled(RuntimeError):
    """A supervising parent cancelled the v8 attempt."""


def _finite(value: Any, name: str, *, minimum: float = 0.0, integer: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(name + " must be finite numeric data")
    if float(value) < minimum or (integer and not isinstance(value, int)):
        raise ValueError(name + " has an invalid range or type")


def _light_validate(request: dict[str, Any], *, data_root: Path) -> None:
    required = ("family_id", "case_id", "attempt_id", "kind", "command", "cwd",
                "max_wall_seconds", "cpu_threads", "estimated_storage_bytes",
                "input_files", "worktree_root")
    for key in required:
        if key not in request:
            raise ValueError("missing request field: " + key)
    if request["family_id"] not in {"infra", *[f"F{i}" for i in range(1, 8)]}:
        raise ValueError("unknown family_id")
    for key in ("case_id", "attempt_id"):
        value = request[key]
        if not isinstance(value, str) or not value or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in value):
            raise ValueError("unsafe identity: " + key)
    if request["kind"] != "cpu":
        raise ValueError("runtime v8 only accepts dataset CPU requests")
    if request.get("cpu_task_kind") not in base.CPU_KINDS:
        raise ValueError("CPU task is outside the dataset-only allowlist")
    command = request["command"]
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise ValueError("command must be an argv list")
    _finite(request["max_wall_seconds"], "max_wall_seconds", minimum=1e-9)
    _finite(request["cpu_threads"], "cpu_threads", minimum=1, integer=True)
    _finite(request["estimated_storage_bytes"], "estimated_storage_bytes", integer=True)
    cwd = Path(str(request["cwd"])).expanduser().resolve()
    worktree = Path(str(request["worktree_root"])).expanduser().resolve()
    if not cwd.is_dir() or not worktree.is_dir():
        raise ValueError("request cwd/worktree_root must be existing directories")
    input_files = request["input_files"]
    if not isinstance(input_files, list) or not input_files:
        raise ValueError("input_files must be a non-empty list")
    for value in input_files:
        path = Path(str(value)).expanduser().resolve()
        if not path.is_file():
            raise ValueError("input file missing: " + str(path))
        # stat is intentional and bounded; content hashing begins only after
        # the reservation is registered below.
        path.stat()
    output = data_root / "families" / request["family_id"] / request["case_id"] / request["attempt_id"]
    if output.exists():
        raise FileExistsError("attempt output already exists: " + str(output))


def validate_request(request: dict[str, Any], *, approval_context: dict[str, Any] | None = None) -> dict[str, str]:
    """Full digest-bound validation, called only after reservation."""
    actual = _base_validate(request, approval_context=approval_context)
    if V6_RUNTIME_PATH not in actual:
        raise ValueError("v8 request must bind consumed v6 runtime")
    if RUNTIME_PATH not in actual:
        raise ValueError("v8 request must bind its runtime source")
    return actual


def _install_signals(max_wall: float):
    previous = {
        signal.SIGALRM: signal.getsignal(signal.SIGALRM),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }

    def alarm(_signum, _frame):
        raise RuntimeV8Deadline("runtime v8 entry-to-terminal wall deadline exceeded")

    def cancel(signum, _frame):
        raise RuntimeV8Cancelled("runtime v8 cancelled by signal " + str(signum))

    signal.signal(signal.SIGALRM, alarm)
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, float(max_wall)))
    return previous


def _restore_signals(previous) -> None:
    signal.setitimer(signal.ITIMER_REAL, 0.0)
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _stop_child_bounded(proc) -> bool:
    if proc is None or proc.poll() is not None:
        return True
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return True
    until = time.monotonic() + 0.25
    while proc.poll() is None and time.monotonic() < until:
        time.sleep(0.01)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=0.5)
        return True
    except base.subprocess.TimeoutExpired:
        return False


def _attempt_id(request: dict[str, Any]) -> str:
    return f"{request['family_id']}/{request['case_id']}/{request['attempt_id']}"


def _receipt_path(output: Path) -> Path:
    return output / "execution-receipt.json"


def _write_terminal_receipt(path: Path, value: dict[str, Any]) -> None:
    """Use v6's fixed-point writer while preserving the v8 runner identity."""
    value["runner_source"] = RUNTIME_PATH
    value["runner_sha256"] = base.sha256(__file__)
    v6._write_terminal_receipt(path, value)


def run_request(request_path, *, data_root=DATA_ROOT, parent_pid: int | None = None):
    global _active_v6_root
    entry_wall = time.monotonic()
    entry_cpu = base.cpu_usage()
    entry_utc = base.now()
    data_root = Path(data_root).expanduser().resolve()
    request_path = Path(request_path).expanduser().resolve()
    request = json.loads(request_path.read_text())
    if not isinstance(request, dict):
        raise ValueError("request JSON must be an object")
    max_wall = float(request.get("max_wall_seconds", 0))
    _finite(max_wall, "max_wall_seconds", minimum=1e-9)
    previous_signals = _install_signals(max_wall)
    previous_v6_root = v6._ACTIVE_DATA_ROOT
    v6._ACTIVE_DATA_ROOT = data_root
    _active_v6_root = data_root
    attempt = None
    output = None
    reservation = None
    registered = False
    proc = None
    hashes: dict[str, str] = {}
    input_hashes_after: dict[str, str | None] = {}
    source_hash_status = "NOT_STARTED"
    status = "failed"
    error: str | None = None
    deadline_status = "WITHIN_LIMIT"
    child_started = None
    child_elapsed = 0.0
    reservation_utc: str | None = None
    launch_utc: str | None = None
    runner_git_at_launch: dict[str, Any] | None = None
    git_at_launch: dict[str, Any] | None = None
    accounting_cpu_cutoff: float | None = None
    accounting_finished_utc: str | None = None
    result: dict[str, Any] = {}
    try:
        _light_validate(request, data_root=data_root)
        attempt = _attempt_id(request)
        output = data_root / "families" / attempt
        reservation_utc = base.now()
        reservation = {
            "id": attempt,
            "kind": "cpu",
            "cpu_task_kind": request.get("cpu_task_kind"),
            "cpu_threads": request["cpu_threads"],
            "cpu_core_seconds": request["cpu_threads"] * request["max_wall_seconds"],
            "gpu_seconds": 0,
            "new_storage_bytes": request["estimated_storage_bytes"],
            "reserved_at_utc": reservation_utc,
            "launcher_pid": os.getpid(),
            "host": base.socket.gethostname(),
        }
        with ledger_locked(data_root) as ledger:
            stat = os.statvfs(data_root)
            free_disk = stat.f_bavail * stat.f_frsize
            check_reservation(ledger, reservation, tree_bytes(data_root), available_bytes=free_disk)
            if free_disk < request["estimated_storage_bytes"] + 2 * 1024 ** 3:
                raise RuntimeError("insufficient filesystem headroom")
            ledger["reservations"].append(dict(reservation))
            ledger["attempts"].append({"id": attempt, "kind": "cpu", "status": "reserved",
                                       "started_at_utc": reservation_utc})
            registered = True
        output.mkdir(parents=True, exist_ok=False)
        source_hash_status = "STARTED_AFTER_RESERVATION"
        # This is the first operation allowed to read input content.  The
        # shared strict wrapper is installed by dispatch_v8 when used by a
        # parent; direct invocation still uses the same full validator.
        hashes = validate_request(request, approval_context={})
        source_hash_status = "PASS_AFTER_RESERVATION"
        if parent_pid is not None and os.getppid() != int(parent_pid):
            raise RuntimeV8Cancelled("supervising parent already exited")
        # Capture launch provenance at the actual child boundary.  Do not
        # recompute git state in terminal finalization: a changed worktree or
        # later HEAD is not launch provenance.
        runner_git_at_launch = base.git_launch_state(Path(__file__).resolve().parents[2])
        git_at_launch = base.git_launch_state(request["worktree_root"])
        command = list(request["command"])
        command = [arg.replace("{attempt_root}", str(output)) for arg in command]
        environment = os.environ.copy()
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            environment[name] = str(request["cpu_threads"])
        environment["LD_LIBRARY_PATH"] = str(base.BIN_ROOT) + ":" + environment.get("LD_LIBRARY_PATH", "")
        launch_utc = base.now()
        child_started = time.monotonic()
        with (output / "stdout.log").open("w") as log:
            proc = base.subprocess.Popen(command, cwd=request["cwd"], env=environment,
                                         stdout=log, stderr=base.subprocess.STDOUT,
                                         start_new_session=True)
            while proc.poll() is None:
                elapsed = time.monotonic() - child_started
                if elapsed > request["max_wall_seconds"]:
                    raise RuntimeV8Deadline("child wall allocation exceeded")
                if parent_pid is not None and os.getppid() != int(parent_pid):
                    raise RuntimeV8Cancelled("supervising parent exited")
                time.sleep(0.1)
            proc.wait()
        child_elapsed = time.monotonic() - child_started
        result["returncode"] = proc.returncode
        status = "completed" if proc.returncode == 0 else "failed"
        if status != "completed":
            error = "child returned nonzero"
    except (RuntimeV8Deadline, RuntimeV8Cancelled) as exc:
        error = str(exc)
        deadline_status = "EXCEEDED" if isinstance(exc, RuntimeV8Deadline) else "CANCELLED"
        status = "failed"
        if proc is not None:
            _stop_child_bounded(proc)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        status = "failed"
        if proc is not None:
            _stop_child_bounded(proc)
    finally:
        if child_started is not None and child_elapsed == 0.0:
            child_elapsed = max(0.0, time.monotonic() - child_started)
        # Keep the alarm active while normal posthashing is underway.  A
        # timeout switches to a cheap failure receipt instead of extending the
        # promised wall with another large source scan.
        try:
            if registered and hashes and deadline_status == "WITHIN_LIMIT":
                for path in hashes:
                    if time.monotonic() - entry_wall >= max_wall:
                        raise RuntimeV8Deadline("post-run source hash reached runtime v8 deadline")
                    input_hashes_after[path] = base.sha256(path) if Path(path).is_file() else None
                if input_hashes_after != hashes:
                    status = "failed"
                    error = "input_mutated_during_run"
            elif registered:
                source_hash_status = "SKIPPED_AFTER_DEADLINE_OR_CANCEL"
        except (RuntimeV8Deadline, RuntimeV8Cancelled) as exc:
            status = "failed"
            deadline_status = "EXCEEDED" if isinstance(exc, RuntimeV8Deadline) else "CANCELLED"
            error = str(exc)
            source_hash_status = "SKIPPED_AFTER_DEADLINE_OR_CANCEL"
        finally:
            _restore_signals(previous_signals)
        if registered and output is not None and attempt is not None:
            output_bytes = tree_bytes(output)
            stdout_hash = base.sha256(output / "stdout.log") if (output / "stdout.log").is_file() else None
            receipt = {
                "schema": "ds02.execution-receipt.v1",
                "request": request,
                "request_sha256": base.sha256(request_path),
                "input_hashes_at_launch": hashes,
                "input_hashes_after_run": input_hashes_after,
                "runner_source": RUNTIME_PATH,
                "runner_sha256": base.sha256(__file__),
                "runner_git_at_launch": runner_git_at_launch,
                "git_at_launch": git_at_launch,
                "entry_started_at_utc": entry_utc,
                "reservation_started_at_utc": reservation_utc,
                "started_at_utc": launch_utc or reservation_utc or entry_utc,
                "output_root": str(output),
                "status": status,
                "returncode": result.get("returncode"),
                "termination_reason": error,
                "elapsed_seconds": child_elapsed,
                "wall_seconds_from_entry": time.monotonic() - entry_wall,
                "cpu_core_seconds": accounting_cpu_cutoff if accounting_cpu_cutoff is not None else max(0.0, base.cpu_usage() - entry_cpu),
                "gpu_seconds": 0.0,
                "bytes": output_bytes,
                "stdout_sha256": stdout_hash,
                "source_preflight": {
                    "status": source_hash_status,
                    "reservation_registered_before_content_hash": True,
                    "content_read_started_after_reservation": source_hash_status != "NOT_STARTED",
                },
                "timing_scope": {
                    "clock_start": "function_entry_before_request_parse_and_light_validation",
                    "reservation_before_input_content_hash": True,
                    "wall_covers_source_hash_child_and_posthash": True,
                    "cpu_includes_source_hash_and_posthash": True,
                    "terminal_cleanup": "timer disabled before receipt/ledger close",
                },
                "deadline": {"max_wall_seconds": max_wall, "status": deadline_status,
                             "failure_charge_required": True},
                "model_invoked": False,
                "cfd_invoked": False,
                "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            }
            # The accounting cutoff is after source posthash, output byte
            # measurement, and stdout hashing.  Receipt writing/fixed-point
            # serialization is intentionally after this cutoff; the exact
            # value is reused for the parent ledger charge below.
            accounting_cpu_cutoff = max(0.0, base.cpu_usage() - entry_cpu)
            accounting_finished_utc = base.now()
            receipt["cpu_core_seconds"] = accounting_cpu_cutoff
            receipt["finished_at_utc"] = accounting_finished_utc
            receipt["timing_scope"]["cpu_cutoff"] = "after_source_posthash_output_bytes_stdout_hash_before_terminal_receipt_write"
            receipt["timing_scope"]["cpu_cutoff_value_reused_for_ledger_charge"] = True
            # v6's guarded writer retains the consumed terminal fixed-point
            # implementation.  It is called only after v8's outer content
            # phase has stopped; ledger close is bounded to this small receipt.
            _write_terminal_receipt(_receipt_path(output), receipt)
            measured_cpu = max(0.0, base.cpu_usage() - entry_cpu)
            actual_bytes = tree_bytes(output)
            with ledger_locked(data_root) as ledger:
                ledger["reservations"] = [row for row in ledger["reservations"] if row.get("id") != attempt]
                ledger["charges"].append({"id": attempt, "gpu_seconds": 0.0,
                                          "cpu_core_seconds": accounting_cpu_cutoff,
                                          "new_storage_bytes": int(actual_bytes),
                                          "status": receipt.get("status", status), "finished_at_utc": accounting_finished_utc})
                for row in ledger.get("attempts", []):
                    if row.get("id") == attempt:
                        row.update(status=receipt.get("status", status), finished_at_utc=accounting_finished_utc)
        _active_v6_root = None
        v6._ACTIVE_DATA_ROOT = previous_v6_root
    if not registered and error:
        raise RuntimeError(error)
    return {
        "status": "completed" if status == "completed" else "failed",
        "attempt": attempt,
        "output_root": str(output) if output is not None else None,
        "source_preflight_status": source_hash_status,
        "deadline_status": deadline_status,
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run"])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    result = run_request(args.request, data_root=args.data_root, parent_pid=args.parent_pid)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return int(result["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
