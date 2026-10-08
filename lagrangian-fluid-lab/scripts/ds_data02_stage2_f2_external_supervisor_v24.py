#!/usr/bin/env python3
"""Forward v23 with an entry-wide deadline and helper cancellation cleanup.

The consumed v23 wrapper validates the complete request before entering the
v21 timer and its v22 helper runner only handles ``TimeoutExpired``.  This
version records and installs the deadline before any request/source
validation, makes the same-parent supervisor reservation before the expensive
content pass, and replaces the helper runner with a ``BaseException`` cleanup
path.  A SIGTERM or deadline raised while a real helper is in
``communicate()`` therefore terminates and reaps that helper group before the
v21 terminal charge path continues.

The v21 accounting implementation remains the owner of the ledger.  This
forwarder owns no ledger, does not relax source checks, and grants no
scientific qualification.  The v24 entry is additive; v23 requests and
receipts remain immutable.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V22_PATH = SCRIPT.with_name("ds_data02_stage2_f2_external_supervisor_v22.py")
V22_SPEC = importlib.util.spec_from_file_location("ds02_external_supervisor_v22_for_v24", V22_PATH)
if V22_SPEC is None or V22_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import immutable v22 supervisor: {V22_PATH}")
V22 = importlib.util.module_from_spec(V22_SPEC)
V22_SPEC.loader.exec_module(V22)
V21 = V22.V21

SCHEMA = V21.SCHEMA
REPORT_SCHEMA = V21.REPORT_SCHEMA
UNKNOWN = V21.UNKNOWN
V24Error = V21.SupervisorError
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
        raise V24Error(f"JSON object required: {path}")
    return value


def _binding(path: Path, role: str) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise V24Error(f"v24 source binding is missing: {target}")
    stat = target.stat()
    return {"role": role, "path": str(target), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(target),
            "source_kind": "static", "content_scope": "content_sha256"}


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    target = path.expanduser().resolve()
    if target.exists():
        raise V24Error(f"refusing existing v24 request: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def build_request(v14_path: Path | str, output_path: Path | str, *,
                  output_root: Path | str, max_wall_seconds: float = 6000.0) -> dict[str, Any]:
    """Build a fresh request from the immutable v21/v22 graph."""
    V22.build_request(v14_path, output_path, output_root=output_root,
                      max_wall_seconds=max_wall_seconds)
    output = Path(output_path).expanduser().resolve()
    request = load_json(output)
    bindings = list(request.get("static_bindings", []))
    bindings.append(_binding(SCRIPT, "external_supervisor_v24"))
    request["static_bindings"] = bindings
    request["forward_runtime"] = {
        "schema": "ds02.stage2.f2-external-supervisor-runtime.v24",
        "path": str(SCRIPT), "sha256": sha256_file(SCRIPT), "immutable": True,
        "forward_of": {"path": str(V22_PATH), "sha256": sha256_file(V22_PATH)},
        "io_slot_flag_forwarded": True,
        "entry_timer_before_validation": True,
        "reservation_before_content_validation": True,
        "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS,
        "helper_cleanup_on_base_exception": True,
    }
    execution = dict(request.get("execution", {}))
    execution.update({
        "outer_entrypoint": str(SCRIPT),
        "outer_entrypoint_sha256": sha256_file(SCRIPT),
        "io_slot_approved_flag": "--io-slot-approved",
        "start_clock": "v24 run entry before JSON/source validation",
        "hard_wall_scope": "entry through validation, reservation, v14, v20 helpers, and v21 charge preparation",
        "helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS,
    })
    request["execution"] = execution
    request["limitations"] = list(request.get("limitations", [])) + [
        "v24 starts the outer timer before request/source validation and makes the idempotent parent reservation before the full content pass.",
        "The v21 report retains its own internal phase timing; the v24 returned result carries outer preflight timing separately.",
        "Helper cleanup is bounded by the v24 cleanup grace and is limited to the helper process group created by this supervisor.",
        "Final filesystem/ledger writes remain reported as local finalization scope; no QI/QN/QE is granted.",
    ]
    request["sha256"] = canonical_sha(request)
    output.unlink()
    _write_new(output, request)
    return request


def validate_request(request_path: Path | str, *, verify_content: bool = False) -> dict[str, Any]:
    request = load_json(request_path)
    if request.get("schema") != SCHEMA:
        raise V24Error("v24 accepts only the immutable v21 supervisor schema")
    forward = request.get("forward_runtime")
    if not isinstance(forward, Mapping) or forward.get("path") != str(SCRIPT):
        raise V24Error("v24 forward runtime binding is missing")
    if forward.get("sha256") != sha256_file(SCRIPT):
        raise V24Error("v24 forward runtime SHA differs")
    if forward.get("entry_timer_before_validation") is not True:
        raise V24Error("v24 entry timer binding is missing")
    if forward.get("reservation_before_content_validation") is not True:
        raise V24Error("v24 reservation ordering binding is missing")
    if float(forward.get("helper_cleanup_grace_seconds", 0.0) or 0.0) < HELPER_CLEANUP_GRACE_SECONDS:
        raise V24Error("v24 helper cleanup grace is less than 25 seconds")
    bindings = request.get("static_bindings")
    if not isinstance(bindings, list) or not any(
            isinstance(item, Mapping) and item.get("role") == "external_supervisor_v24"
            for item in bindings):
        raise V24Error("v24 static source binding is missing")
    return V21._validate_request(request, verify_content=verify_content)


def _raw_max_wall(request: Mapping[str, Any]) -> float:
    execution = request.get("execution")
    if not isinstance(execution, Mapping):
        raise V24Error("request execution binding is missing before timer install")
    value = float(execution.get("max_wall_seconds", 0.0) or 0.0)
    if not math.isfinite(value) or value <= 0.0:
        raise V24Error("request max_wall_seconds must be finite and positive")
    return value


def _pre_reserve(request: Mapping[str, Any], checked: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the same-parent idempotent reservation before content hashing."""
    bound = checked["bound"]
    limits = bound["ledger_limits"]
    home_path = Path(str(limits.get("home_path", bound["ledger"].parent.parent))).expanduser().resolve()
    accounting = request.get("accounting")
    storage = request.get("storage_scope")
    runtime = request.get("runtime_binding")
    if not isinstance(accounting, Mapping) or not isinstance(storage, Mapping) or not isinstance(runtime, Mapping):
        raise V24Error("v24 reservation bindings are incomplete")
    return V21._reserve_wrapper(
        Path(str(runtime["path"])), str(runtime["sha256"]), bound["ledger"],
        str(accounting["reservation_id"]), bound["attempt_id"],
        external=bound["external"], bytes_count=int(storage["estimated_output_bytes"]),
        home_path=home_path, home_floor=int(limits.get("home_min_free_bytes", 0) or 0),
        external_floor=int(storage.get("external_min_free_bytes", 1) or 0),
        cpu_reserve_seconds=float(accounting["cpu_reservation_seconds"]),
        max_wall_seconds=float(request["execution"]["max_wall_seconds"]),
        deadline_utc=str(bound.get("deadline_utc", "")),
        max_storage=int(limits["new_storage_bytes"]) if limits.get("new_storage_bytes") is not None else None,
        max_cpu=float(limits["cpu_core_seconds"]) if limits.get("cpu_core_seconds") is not None else None,
    )


def _run_process_group_v24(command: Sequence[str], *, cwd: Path, timeout: float) -> dict[str, Any]:
    """Run a helper and clean its own group for every exceptional exit."""
    proc = subprocess.Popen(list(command), cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    cleanup: dict[str, Any] = {}
    try:
        stdout, stderr = proc.communicate(timeout=max(0.001, float(timeout)))
        return {"returncode": proc.returncode, "stdout": stdout, "stderr": stderr,
                "cleanup": cleanup}
    except BaseException as error:
        # This includes SupervisorCancelled raised by the parent SIGTERM
        # handler, SupervisorDeadline from the entry timer, and
        # TimeoutExpired.  The child group is ours, so it is safe to stop and
        # reap it before propagating the supervisor error to v21.run.
        cleanup = V21._stop_group(proc, grace=HELPER_CLEANUP_GRACE_SECONDS)
        if isinstance(error, subprocess.TimeoutExpired):
            raise V21.SupervisorDeadline(f"bound helper deadline exceeded: {command[0]}") from error
        raise
    finally:
        # A helper can exit between communicate() and the exception path.  A
        # live group is never left behind by this entrypoint.
        if proc.poll() is None:
            V21._stop_group(proc, grace=HELPER_CLEANUP_GRACE_SECONDS)


def run(request_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    entry_wall = time.monotonic()
    entry_cpu = V21._cpu_seconds()
    request = load_json(request_file)
    max_wall = _raw_max_wall(request)
    if not io_slot_approved:
        checked = V21._validate_request(request, verify_content=False)
        return {"schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
                "request_sha256": sha256_file(request_file), "ledger_mutated": False,
                "v24_entry_wall_seconds": time.monotonic() - entry_wall,
                "raw_opened": False, "hdf5_opened": False, "model_invoked": False,
                "cfd_invoked": False, "qualification": dict(UNKNOWN)}

    # Install the outer timer before even the cheap metadata/source checks.
    previous_signals = V21._install_signals(max_wall)
    originals = (V21._install_signals, V21._restore_signals, V21._run_process_group)
    pre_reservation: dict[str, Any] | None = None
    try:
        checked = V21._validate_request(request, verify_content=False)
        if parent_pid is not None and os.getppid() != int(parent_pid):
            raise V21.SupervisorCancelled("supervising parent already exited")
        pre_reservation = _pre_reserve(request, checked)

        # Keep the outer handler/timer while V21 performs its immutable
        # content validation, child launch, helper calls, and charge.  Its
        # internal install/restore hooks are disabled only to prevent it from
        # resetting the entry-wide timer.
        V21._install_signals = lambda _ignored: {"v24_outer_timer": True}
        V21._restore_signals = lambda _ignored: None
        V21._run_process_group = _run_process_group_v24
        result = V21.run(request_file, io_slot_approved=True, parent_pid=parent_pid)
        if isinstance(result, dict):
            result = dict(result)
            result.update({
                "v24_entry_wall_seconds": time.monotonic() - entry_wall,
                "v24_entry_cpu_core_seconds": max(0.0, V21._cpu_seconds() - entry_cpu),
                "v24_prevalidation_reservation": pre_reservation.get("status") if pre_reservation else None,
                "v24_timer_scope": "entry through validation/reservation/v14/v20 and v21 charge preparation",
                "v24_helper_cleanup_grace_seconds": HELPER_CLEANUP_GRACE_SECONDS,
                "v24_model_invoked": False, "v24_cfd_invoked": False,
            })
        return result
    finally:
        V21._install_signals, V21._restore_signals, V21._run_process_group = originals
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
            value = validate_request(args.request, verify_content=args.verify_content)
            result = {"status": "VALIDATED_V24", "v14": str(value["v14_path"]),
                      "helper_cleanup_grace_seconds": value["child_cleanup_grace_seconds"]}
        else:
            if not args.io_slot_approved:
                parser.error("approved supervisor run requires --io-slot-approved")
            result = run(args.request, io_slot_approved=True, parent_pid=args.parent_pid)
    except (V24Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0 if str(result.get("status", "")).startswith(("READY_", "VALIDATED_", "COMPLETED_")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
