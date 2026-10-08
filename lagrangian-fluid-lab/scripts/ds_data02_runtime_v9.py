#!/usr/bin/env python3
"""Forward CPU runtime with reservation-before-content-hash semantics.

The consumed v6 runner still validates and hashes every input before it can
register an attempt.  That loses the cost of a large F3/F7 source preflight
from the parent's active reservation and leaves no bounded cancellation point
while hashing.  v9 is an additive CPU-only runner: it performs cheap request
and ``stat`` checks, registers the attempt under the existing Stage2 ledger,
then performs the digest-bound content validation inside an entry-to-terminal
wall/cancellation guard.  HDF5/BI4 content is never opened by this module
without a parent scheduler approving the request.  Its storage contract keeps
Home and an explicitly bound external filesystem separate; unsplit legacy
rows remain conservatively Home-owned.

The v6 runtime remains the receipt/fixed-point implementation dependency, but
the v9 runner owns the ordering and deadline boundary.  QI/QN/QE are not
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
from typing import Any, Mapping

import ds_data02_runtime_v6 as v6


base = v6.base
DATA_ROOT = base.DATA_ROOT
RUNTIME_PATH = str(Path(__file__).resolve())
V6_RUNTIME_PATH = str(Path(v6.__file__).resolve())
ledger_locked = v6.ledger_locked
tree_bytes = v6.tree_bytes

_base_validate = v6.validate_request
_base_atomic_json = v6._base_atomic_json
_active_v6_root: Path | None = None
_active_storage_scope: dict[str, Any] | None = None


class RuntimeV9Deadline(RuntimeError):
    """Entry-to-terminal v9 wall deadline was reached."""


class RuntimeV9Cancelled(RuntimeError):
    """A supervising parent cancelled the v9 attempt."""


def _finite(value: Any, name: str, *, minimum: float = 0.0, integer: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(name + " must be finite numeric data")
    if float(value) < minimum or (integer and not isinstance(value, int)):
        raise ValueError(name + " has an invalid range or type")


def _nonnegative_int(value: Any, name: str) -> int:
    _finite(value, name, minimum=0, integer=True)
    return int(value)


def _storage_scope(request: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize split Home/external storage before the atomic reservation."""
    total = _nonnegative_int(request.get("estimated_storage_bytes"), "estimated_storage_bytes")
    raw = request.get("storage_scope")
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError("storage_scope must be an object")
    external_value = raw.get("external_storage_bytes", raw.get("external_reservation_bytes", 0))
    external = _nonnegative_int(external_value, "storage_scope.external_storage_bytes")
    home = _nonnegative_int(raw.get("home_storage_bytes", raw.get("home_reservation_bytes", total - external)),
                            "storage_scope.home_storage_bytes")
    if home + external != total:
        raise ValueError("storage_scope Home/external bytes must sum to estimated_storage_bytes")
    external_path = raw.get("external_filesystem")
    if external and (not isinstance(external_path, str) or not external_path):
        raise ValueError("external_storage_bytes requires storage_scope.external_filesystem")
    home_path = raw.get("home_path")
    return {
        "schema": "ds02.storage-scope.v1",
        "home_storage_bytes": home,
        "external_storage_bytes": external,
        "home_path": str(Path(home_path).expanduser().resolve()) if home_path else None,
        "external_filesystem": str(Path(external_path).expanduser().resolve()) if external_path else None,
        "external_min_free_bytes": _nonnegative_int(raw.get("external_min_free_bytes", 0),
                                                       "storage_scope.external_min_free_bytes"),
        "home_headroom_bytes": _nonnegative_int(raw.get("home_headroom_bytes", 2 * 1024 ** 3),
                                                  "storage_scope.home_headroom_bytes"),
        "external_headroom_bytes": _nonnegative_int(raw.get("external_headroom_bytes", 2 * 1024 ** 3),
                                                      "storage_scope.external_headroom_bytes"),
        "legacy_scope_defaulted": not bool(raw),
    }


def _row_storage_split(row: Mapping[str, Any]) -> tuple[int, int, str]:
    """Return (Home, external, evidence-mode) for one ledger reservation."""
    total = _nonnegative_int(row.get("new_storage_bytes", 0), "ledger.new_storage_bytes")
    if "home_storage_bytes" not in row and "external_storage_bytes" not in row:
        # Unknown legacy schema is conservatively charged to Home.
        return total, 0, "LEGACY_UNSPLIT_CONSERVATIVE_HOME"
    home = _nonnegative_int(row.get("home_storage_bytes", 0), "ledger.home_storage_bytes")
    external = _nonnegative_int(row.get("external_storage_bytes", 0), "ledger.external_storage_bytes")
    if home + external != total:
        raise ValueError("ledger split storage does not equal new_storage_bytes")
    return home, external, "EXPLICIT_V1_SPLIT"


def _filesystem_device(path: str | Path) -> int:
    return int(Path(path).expanduser().resolve().stat().st_dev)


def _external_free(path: str | Path) -> int:
    stat = os.statvfs(Path(path).expanduser().resolve())
    return int(stat.f_bavail * stat.f_frsize)


def _check_split_reservation(ledger: Mapping[str, Any], reservation: dict[str, Any],
                             existing_bytes: int, *, current_time=None,
                             available_bytes: int | None = None) -> None:
    """Check CPU/attempt budgets and separate Home/external storage floors."""
    for key in ("gpu_seconds", "cpu_core_seconds", "new_storage_bytes"):
        _finite(ledger["limits"][key], "limit." + key)
        _finite(reservation[key], "reservation." + key)
        for row in list(ledger.get("charges", [])) + list(ledger.get("reservations", [])):
            _finite(row.get(key, 0), "ledger." + key)
    for key in ("qualification_attempts", "production_attempts"):
        _finite(ledger["limits"][key], "limit." + key, integer=True)
    _finite(reservation.get("cpu_threads"), "cpu_threads", minimum=1, integer=True)
    stamp = current_time or datetime.now(timezone.utc)
    deadline = datetime.fromisoformat(str(ledger["deadline_utc"]))
    if stamp >= deadline:
        raise RuntimeError("campaign deadline reached")
    if any(row.get("id") == reservation["id"] for row in ledger.get("attempts", [])):
        raise RuntimeError("attempt_id already registered; never overwrite or restart it")
    totals = {key: 0.0 for key in ("gpu_seconds", "cpu_core_seconds")}
    for row in list(ledger.get("charges", [])) + list(ledger.get("reservations", [])):
        for key in totals:
            totals[key] += float(row.get(key, 0) or 0)
    for key in totals:
        if totals[key] + float(reservation[key]) > float(ledger["limits"][key]):
            raise RuntimeError("parent budget exhausted: " + key)
    threads = sum(int(row.get("cpu_threads", 1)) for row in ledger.get("reservations", []))
    if threads + int(reservation["cpu_threads"]) > min(64, os.cpu_count() or 1):
        raise RuntimeError("shared CPU thread reservation exceeded")
    kind = reservation["kind"]
    if kind in {"qualification", "production"}:
        cap_key = f"{kind}_attempts"
        if sum(row.get("kind") == kind for row in ledger.get("attempts", [])) >= int(ledger["limits"][cap_key]):
            raise RuntimeError("parent attempt cap reached: " + kind)
        if sum(row.get("kind") in {"qualification", "production"} for row in ledger.get("reservations", [])) >= 4:
            raise RuntimeError("initial shared solver concurrency reached")
    if kind == "cpu" and reservation.get("cpu_task_kind") == "conversion":
        if sum(row.get("cpu_task_kind") == "conversion" for row in ledger.get("reservations", [])) >= 2:
            raise RuntimeError("initial shared conversion concurrency reached")
    if float(reservation["cpu_core_seconds"]) / int(reservation["cpu_threads"]) > (deadline - stamp).total_seconds():
        raise RuntimeError("reserved duration would exceed campaign deadline")

    if ledger["limits"].get("storage_policy") != "home_free_floor":
        if int(existing_bytes) + sum(int(row.get("new_storage_bytes", 0)) for row in ledger.get("reservations", [])) + int(reservation["new_storage_bytes"]) > int(ledger["limits"]["new_storage_bytes"]):
            raise RuntimeError("parent storage budget exhausted")
        return
    if available_bytes is None:
        raise RuntimeError("live Home availability is required")
    floor = _nonnegative_int(ledger["limits"].get("home_min_free_bytes"), "limit.home_min_free_bytes")
    home_reserved = external_reserved = legacy_rows = 0
    for row in ledger.get("reservations", []):
        home, external, mode = _row_storage_split(row)
        home_reserved += home
        external_reserved += external
        legacy_rows += mode == "LEGACY_UNSPLIT_CONSERVATIVE_HOME"
    home_need, external_need, _ = _row_storage_split(reservation)
    if int(available_bytes) - home_reserved - home_need < floor:
        raise RuntimeError("Home free-space floor would be crossed")
    scope = _active_storage_scope or {}
    external_path = scope.get("external_filesystem")
    if external_need:
        if not external_path:
            raise RuntimeError("external reservation lacks a bound filesystem")
        home_path = scope.get("home_path") or ledger["limits"].get("home_path")
        if home_path and _filesystem_device(home_path) == _filesystem_device(external_path):
            raise RuntimeError("external filesystem must be a distinct device")
        external_floor = int(scope.get("external_min_free_bytes", 0))
        if _external_free(external_path) - external_reserved - external_need < external_floor:
            raise RuntimeError("external filesystem floor would be crossed")
    reservation["storage_accounting"] = {
        "policy": "home_free_floor",
        "home_reserved_bytes": home_need,
        "external_reserved_bytes": external_need,
        "existing_reservations_home_bytes": home_reserved,
        "existing_reservations_external_bytes": external_reserved,
        "legacy_unsplit_rows_conservatively_home": legacy_rows,
        "home_floor_checked_against": "home_statvfs_only",
        "external_floor_checked_against": str(external_path) if external_need else None,
        "atomic_same_parent_ledger": True,
    }


check_reservation = _check_split_reservation


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
        raise ValueError("runtime v9 only accepts dataset CPU requests")
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
        raise ValueError("v9 request must bind consumed v6 runtime")
    if RUNTIME_PATH not in actual:
        raise ValueError("v9 request must bind its runtime source")
    return actual


def _install_signals(max_wall: float):
    previous = {
        signal.SIGALRM: signal.getsignal(signal.SIGALRM),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }

    def alarm(_signum, _frame):
        raise RuntimeV9Deadline("runtime v9 entry-to-terminal wall deadline exceeded")

    def cancel(signum, _frame):
        raise RuntimeV9Cancelled("runtime v9 cancelled by signal " + str(signum))

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
    """Use v6's fixed-point writer while preserving the v9 runner identity."""
    value["runner_source"] = RUNTIME_PATH
    value["runner_sha256"] = base.sha256(__file__)
    v6._write_terminal_receipt(path, value)


def run_request(request_path, *, data_root=DATA_ROOT, parent_pid: int | None = None):
    global _active_v6_root, _active_storage_scope
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
    storage_scope = _storage_scope(request)
    previous_signals = _install_signals(max_wall)
    previous_v6_root = v6._ACTIVE_DATA_ROOT
    previous_storage_scope = _active_storage_scope
    v6._ACTIVE_DATA_ROOT = data_root
    _active_v6_root = data_root
    _active_storage_scope = storage_scope
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
            "home_storage_bytes": storage_scope["home_storage_bytes"],
            "external_storage_bytes": storage_scope["external_storage_bytes"],
            "external_filesystem": storage_scope["external_filesystem"],
            "reserved_at_utc": reservation_utc,
            "launcher_pid": os.getpid(),
            "host": base.socket.gethostname(),
        }
        with ledger_locked(data_root) as ledger:
            stat = os.statvfs(data_root)
            free_disk = stat.f_bavail * stat.f_frsize
            check_reservation(ledger, reservation, tree_bytes(data_root), available_bytes=free_disk)
            if free_disk < storage_scope["home_storage_bytes"] + storage_scope["home_headroom_bytes"]:
                raise RuntimeError("insufficient filesystem headroom")
            if storage_scope["external_storage_bytes"]:
                ext_free = _external_free(storage_scope["external_filesystem"])
                if ext_free < storage_scope["external_storage_bytes"] + storage_scope["external_headroom_bytes"]:
                    raise RuntimeError("insufficient external filesystem headroom")
            ledger["reservations"].append(dict(reservation))
            ledger["attempts"].append({"id": attempt, "kind": "cpu", "status": "reserved",
                                       "started_at_utc": reservation_utc})
            registered = True
        output.mkdir(parents=True, exist_ok=False)
        source_hash_status = "STARTED_AFTER_RESERVATION"
        # This is the first operation allowed to read input content.  The
        # shared strict wrapper is installed by dispatch_v9 when used by a
        # parent; direct invocation still uses the same full validator.
        hashes = validate_request(request, approval_context={})
        source_hash_status = "PASS_AFTER_RESERVATION"
        if parent_pid is not None and os.getppid() != int(parent_pid):
            raise RuntimeV9Cancelled("supervising parent already exited")
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
                    raise RuntimeV9Deadline("child wall allocation exceeded")
                if parent_pid is not None and os.getppid() != int(parent_pid):
                    raise RuntimeV9Cancelled("supervising parent exited")
                time.sleep(0.1)
            proc.wait()
        child_elapsed = time.monotonic() - child_started
        result["returncode"] = proc.returncode
        status = "completed" if proc.returncode == 0 else "failed"
        if status != "completed":
            error = "child returned nonzero"
    except (RuntimeV9Deadline, RuntimeV9Cancelled) as exc:
        error = str(exc)
        deadline_status = "EXCEEDED" if isinstance(exc, RuntimeV9Deadline) else "CANCELLED"
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
                        raise RuntimeV9Deadline("post-run source hash reached runtime v9 deadline")
                    input_hashes_after[path] = base.sha256(path) if Path(path).is_file() else None
                if input_hashes_after != hashes:
                    status = "failed"
                    error = "input_mutated_during_run"
            elif registered:
                source_hash_status = "SKIPPED_AFTER_DEADLINE_OR_CANCEL"
        except (RuntimeV9Deadline, RuntimeV9Cancelled) as exc:
            status = "failed"
            deadline_status = "EXCEEDED" if isinstance(exc, RuntimeV9Deadline) else "CANCELLED"
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
                "storage_accounting": {
                    **(reservation.get("storage_accounting") or {}),
                    "terminal_output_home_bytes": int(output_bytes),
                    "terminal_output_external_bytes": 0,
                    "declared_total_bytes": int(request["estimated_storage_bytes"]),
                    "legacy_scope_defaulted": storage_scope["legacy_scope_defaulted"],
                },
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
                                          "home_storage_bytes": int(actual_bytes),
                                          "external_storage_bytes": 0,
                                          "status": receipt.get("status", status), "finished_at_utc": accounting_finished_utc})
                for row in ledger.get("attempts", []):
                    if row.get("id") == attempt:
                        row.update(status=receipt.get("status", status), finished_at_utc=accounting_finished_utc)
        _active_v6_root = None
        v6._ACTIVE_DATA_ROOT = previous_v6_root
        _active_storage_scope = previous_storage_scope
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
