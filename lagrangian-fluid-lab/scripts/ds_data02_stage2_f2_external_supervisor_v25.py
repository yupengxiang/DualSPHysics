#!/usr/bin/env python3
"""Forward v24 with a true outer CPU/deadline baseline.

The consumed v24 entry starts its clock early, but its V21 child resets the
CPU baseline after the v24 pre-reservation.  This forward wrapper keeps the
V24 helper cleanup implementation and binds the V21 terminal accounting to the
actual outer entry CPU baseline.  It also routes an exception between
pre-reservation and V21 through the real V21 prelaunch failure charge, which
releases the same reservation ID when terminal accounting fails.

V25 owns no ledger.  V21 remains the single accounting owner; V25 only keeps
the outer timer and installs a first-call CPU baseline around that immutable
owner.  The request remains DEVELOPMENT/UNKNOWN and native/HDF5 access stays
parent-slot gated.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V24_PATH = SCRIPT.with_name("ds_data02_stage2_f2_external_supervisor_v24.py")
V24_SPEC = importlib.util.spec_from_file_location("ds02_external_supervisor_v24_for_v25", V24_PATH)
if V24_SPEC is None or V24_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import immutable v24 supervisor: {V24_PATH}")
V24 = importlib.util.module_from_spec(V24_SPEC)
V24_SPEC.loader.exec_module(V24)
V21 = V24.V21
SCHEMA = V21.SCHEMA
REPORT_SCHEMA = V21.REPORT_SCHEMA
UNKNOWN = V21.UNKNOWN
V25Error = V21.SupervisorError
HELPER_CLEANUP_GRACE_SECONDS = 25.0


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V21.canonical_sha(value)


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V25Error(f"JSON object required: {path}")
    return value


def _binding(path: Path, role: str) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise V25Error(f"v25 source binding is missing: {target}")
    stat = target.stat()
    return {"role": role, "path": str(target), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(target),
            "source_kind": "static", "content_scope": "content_sha256"}


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        raise V25Error(f"refusing existing v25 request: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def build_request(v14_path: Path | str, output_path: Path | str, *,
                  output_root: Path | str, max_wall_seconds: float = 6000.0) -> dict[str, Any]:
    """Create a fresh V25 request from a V14/V15-compatible immutable input."""
    V24.build_request(v14_path, output_path, output_root=output_root,
                      max_wall_seconds=max_wall_seconds)
    output = Path(output_path).expanduser().resolve()
    request = load_json(output)
    bindings = list(request.get("static_bindings", []))
    bindings.append(_binding(SCRIPT, "external_supervisor_v25"))
    request["static_bindings"] = bindings
    request["forward_runtime"] = {
        "schema": "ds02.stage2.f2-external-supervisor-runtime.v25",
        "path": str(SCRIPT), "sha256": sha256_file(SCRIPT), "immutable": True,
        "forward_of": {"path": str(V24_PATH), "sha256": sha256_file(V24_PATH), "immutable": True},
        "entry_clock_at_function_entry": True,
        "outer_cpu_baseline_includes_pre_reservation": True,
        "reservation_before_expensive_content_validation": True,
        "pre_reservation_failure_uses_v21_terminal_failure_path": True,
        "reservation_cleanup_on_failure": "same reservation id through V21 _record_prelaunch_failure",
        "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS,
    }
    execution = dict(request.get("execution", {}))
    execution.update({
        "outer_entrypoint": str(SCRIPT),
        "outer_entrypoint_sha256": sha256_file(SCRIPT),
        "start_clock": "v25 function entry before request load/validation/reservation",
        "hard_wall_scope": "outer entry through validation, reservation, v14, v20 helpers, and V21 charge preparation",
        "cpu_scope": "V25 outer baseline is passed to the V21 accounting owner; pre-reservation CPU is included",
        "pre_reservation_cancel_scope": "V21 terminal failure charge/release; no second ledger owner",
        "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS,
    })
    request["execution"] = execution
    request["limitations"] = list(request.get("limitations", [])) + [
        "V25 forwards V24 helper cleanup and V21 terminal accounting without changing consumed bytes.",
        "The V25 returned outer timing includes request load, validation, reservation, and V21 finalization preparation.",
        "Local filesystem/ledger finalization remains separately reported and may be delayed by the OS.",
    ]
    request["sha256"] = canonical_sha(request)
    output.unlink()
    _write_new(output, request)
    return request


def validate_request(request_path: Path | str, *, verify_content: bool = False) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != SCHEMA:
        raise V25Error("v25 accepts only the immutable V21 supervisor schema")
    forward = request.get("forward_runtime")
    if not isinstance(forward, Mapping) or forward.get("path") != str(SCRIPT):
        raise V25Error("v25 forward runtime binding is missing")
    if forward.get("sha256") != sha256_file(SCRIPT):
        raise V25Error("v25 forward runtime SHA differs")
    if forward.get("entry_clock_at_function_entry") is not True:
        raise V25Error("v25 entry clock binding is missing")
    if forward.get("outer_cpu_baseline_includes_pre_reservation") is not True:
        raise V25Error("v25 CPU baseline binding is missing")
    if forward.get("reservation_before_expensive_content_validation") is not True:
        raise V25Error("v25 reservation ordering binding is missing")
    if forward.get("pre_reservation_failure_uses_v21_terminal_failure_path") is not True:
        raise V25Error("v25 pre-reservation failure accounting binding is missing")
    if float(forward.get("helper_cleanup_grace_seconds", 0.0) or 0.0) < HELPER_CLEANUP_GRACE_SECONDS:
        raise V25Error("v25 helper cleanup grace is less than 25 seconds")
    bindings = request.get("static_bindings")
    if not isinstance(bindings, list) or not any(
            isinstance(item, Mapping) and item.get("role") == "external_supervisor_v25"
            for item in bindings):
        raise V25Error("v25 static source binding is missing")
    return V21._validate_request(request, verify_content=verify_content)


def _outer_baseline_cpu(original, entry_cpu: float):
    first = True

    def wrapped() -> float:
        nonlocal first
        if first:
            first = False
            return float(entry_cpu)
        return float(original())

    return wrapped


def _outer_baseline_self_cpu(original, entry_cpu: float):
    first = True

    def wrapped() -> float:
        nonlocal first
        if first:
            first = False
            return float(entry_cpu)
        return float(original())

    return wrapped


def _ready_result(request_file: Path, entry_wall: float) -> dict[str, Any]:
    return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
            "request_sha256": sha256_file(request_file), "ledger_mutated": False,
            "v25_entry_wall_seconds": time.monotonic() - entry_wall,
            "raw_opened": False, "hdf5_opened": False, "model_invoked": False,
            "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    """Run the real V21 owner with the V25 outer baseline and cleanup path."""
    request_file = Path(request_path).expanduser().resolve()
    entry_wall = time.monotonic()
    entry_cpu = V21._cpu_seconds()
    entry_self_cpu = V21._self_cpu_seconds()
    request = load_json(request_file)
    if not io_slot_approved:
        validate_request(request_file, verify_content=False)
        return _ready_result(request_file, entry_wall)
    max_wall = V24._raw_max_wall(request)
    previous_signals = V21._install_signals(max_wall)
    originals = (V21._install_signals, V21._restore_signals,
                 V21._run_process_group, V21._cpu_seconds, V21._self_cpu_seconds)
    pre_reserved: dict[str, Any] | None = None
    pre_reservation_attempted = False
    try:
        # This cheap metadata validation remains under the outer timer.  The
        # reservation is applied before V21's verify_content pass.
        checked = validate_request(request_file, verify_content=False)
        if parent_pid is not None and V21.os.getppid() != int(parent_pid):
            raise V21.SupervisorCancelled("supervising parent already exited")
        # Mark the call before entering the ledger API.  A parent signal can
        # arrive after that API has appended the reservation but before its
        # return value reaches Python; the real V21 failure path must then
        # still clean the request's reservation id.  The report calls this
        # "attempted" rather than claiming the return object was observed.
        pre_reservation_attempted = True
        pre_reserved = V24._pre_reserve(request, checked)
        V21._install_signals = lambda _ignored: {"v25_outer_timer": True}
        V21._restore_signals = lambda _ignored: None
        V21._run_process_group = V24._run_process_group_v24
        V21._cpu_seconds = _outer_baseline_cpu(originals[3], entry_cpu)
        V21._self_cpu_seconds = _outer_baseline_self_cpu(originals[4], entry_self_cpu)
        result = V21.run(request_file, io_slot_approved=True, parent_pid=parent_pid)
        if isinstance(result, dict):
            result = dict(result)
            result.update({
                "v25_entry_wall_seconds": time.monotonic() - entry_wall,
                "v25_entry_cpu_core_seconds": max(0.0, originals[3]() - entry_cpu),
                "v25_outer_timer_scope": "function entry through V21 charge preparation",
                "v25_pre_reservation_status": pre_reserved.get("status") if pre_reserved else None,
                "v25_cpu_baseline_includes_pre_reservation": True,
                "v25_helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS,
                "v25_model_invoked": False, "v25_cfd_invoked": False,
            })
        return result
    except BaseException as error:
        # If the outer deadline/cancel fires after reservation but before V21
        # enters its own failure path, call the real V21 prelaunch accounting
        # function.  It writes a fresh failure report, charges the same parent
        # row, and releases the reservation on charge failure.
        try:
            V21._install_signals, V21._restore_signals, V21._run_process_group, \
                V21._cpu_seconds, V21._self_cpu_seconds = originals
            failure = V21._record_prelaunch_failure(
                request_file, request, error, entry_wall=entry_wall, entry_cpu=entry_cpu)
            failure["v25_outer_failure"] = True
            failure["v25_pre_reservation_attempted"] = pre_reservation_attempted
            failure["v25_pre_reservation_returned"] = pre_reserved is not None
            return failure
        except BaseException as accounting_error:
            return {"schema": REPORT_SCHEMA, "status": "FAILED_EXTERNAL_SUPERVISOR_PREFLIGHT",
                    "error": f"{type(error).__name__}: {error}; accounting: {type(accounting_error).__name__}: {accounting_error}",
                    "ledger_mutated": False, "model_invoked": False, "cfd_invoked": False,
                    "qualification": dict(UNKNOWN)}
    finally:
        V21._install_signals, V21._restore_signals, V21._run_process_group, \
            V21._cpu_seconds, V21._self_cpu_seconds = originals
        V21._restore_signals(previous_signals)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v14-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float, default=6000.0)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--verify-content", action="store_true")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(args.v14_request, args.output,
                                  output_root=args.output_root,
                                  max_wall_seconds=args.max_wall_seconds)
            result = {"status": value["status"], "sha256": value["sha256"],
                      "path": str(args.output.expanduser().resolve()),
                      "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS}
        elif args.command == "validate":
            checked = validate_request(args.request, verify_content=args.verify_content)
            result = {"status": "VALIDATED_V25", "v14": str(checked["v14_path"]),
                      "helper_cleanup_grace_seconds": checked["child_cleanup_grace_seconds"]}
        else:
            if not args.io_slot_approved:
                parser.error("approved supervisor run requires --io-slot-approved")
            result = run(args.request, io_slot_approved=True, parent_pid=args.parent_pid)
    except (V25Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0 if str(result.get("status", "")).startswith(("READY_", "VALIDATED_", "COMPLETED_")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
