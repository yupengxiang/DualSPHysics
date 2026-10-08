#!/usr/bin/env python3
"""V6 current-bound typed-only parent with the corrected V2 CURRENT adapter.

V5/V4 remain immutable.  V4's post-reservation callback accidentally asks
the V3 wrapper for ``_current_item`` even though that adapter is defined by
the V2-current-bound wrapper.  V6 supplies the real V2 adapter at the one
callback boundary and delegates the rest of the reviewed V4 runner.  This
keeps the same parent ledger, reservation ordering, child shim, strace and
UNKNOWN qualification policy while making the actual runner executable.

The builder is metadata-only.  It reads JSON/stat/source code bindings but
does not read H5, BI4, CSV or typed-result payloads.  Actual reservation,
CURRENT validation, child execution, report writing and charging remain in
the parent guard and are only entered with ``--io-slot-approved``.
"""
from __future__ import annotations

# Keep these before the ordinary stdlib imports: the V4 parent already does
# the same for its CPU/cgroup baseline, and V6 must carry that baseline across
# the V5/V4 closure import instead of silently dropping wrapper bootstrap CPU.
_SCRIPT_ENTRY_WALL = __import__("time").monotonic()


def _raw_bootstrap_proc_ticks() -> int | None:
    try:
        with open("/proc/self/stat", "r", encoding="ascii") as stream:
            text = stream.read()
        tail = text[text.rfind(")") + 2:].split()
        return int(tail[11]) + int(tail[12])
    except (OSError, ValueError, IndexError):
        return None


def _raw_bootstrap_cgroup_seconds() -> float | None:
    try:
        with open("/proc/self/cgroup", "r", encoding="ascii") as stream:
            relative = next((line[3:].strip() for line in stream
                             if line.startswith("0::")), None)
        if relative is None:
            return None
        with open("/sys/fs/cgroup" + relative + "/cpu.stat", "r", encoding="ascii") as stream:
            for line in stream:
                key, _, value = line.partition(" ")
                if key == "usage_usec":
                    return float(value.strip()) / 1_000_000.0
    except (OSError, ValueError, StopIteration):
        return None
    return None


_SCRIPT_ENTRY_PROC_TICKS = _raw_bootstrap_proc_ticks()
_SCRIPT_ENTRY_CGROUP_SECONDS = _raw_bootstrap_cgroup_seconds()

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V5_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v5_current_bound.py"
SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-request.v2"
FORWARD_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-v6-current-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
_BOOTSTRAP_WALL = time.monotonic()


class TypedParentV6CurrentError(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentV6CurrentError(f"cannot load V5 parent: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V5 = _load(V5_SCRIPT, "ds02_bound_typed_only_evaluator_parent_v5_current_bound_for_v6")
V4 = V5.V4

# Keep the name used by the V6 callback wrapper, but source it from the first
# executable timestamp above.  Do not recapture after V5/V4 import.
_BOOTSTRAP_WALL = _SCRIPT_ENTRY_WALL


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V5.canonical_sha(value)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return V5._write_new(path, value)


def _current_after_reservation(bound: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Use the actual V2-current-bound adapter behind V3/V4.

    V4.BASE is the V3 wrapper and V4.BASE.BASE is the V2-current-bound
    wrapper.  Keeping this lookup explicit prevents a future wrapper from
    silently satisfying the callback with a different CURRENT source.
    """
    v2_current = getattr(V4.BASE, "BASE", None)
    callback = getattr(v2_current, "_current_item", None)
    if not callable(callback):
        raise TypedParentV6CurrentError(
            "V2 current-bound _current_item adapter is missing behind V4.BASE.BASE")
    sidecar, info = callback(bound["request"])
    expected = bound["request"].get("current_catalog_binding", {})
    if info.get("current_catalog_sha256") != expected.get("current_catalog_sha256"):
        raise TypedParentV6CurrentError("post-reservation CURRENT SHA differs from request binding")
    return sidecar, info


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    return V4._validate_request(path, verify_static_content=verify_static_content)


def _run_fixed(path: Path | str, *, io_slot_approved: bool = False,
               parent_pid: int | None = None) -> dict[str, Any]:
    """Run the real V4 parent with only its broken callback replaced."""
    old_callback = V4._current_after_reservation
    # V4 captures its wall clock at the beginning of _run_fixed, after the
    # V4 closure has already been imported.  Feed its first clock read from
    # this wrapper's earliest timestamp, then restore the real clock.  The
    # parent guard still owns the external RuntimeMax/kill boundary; this
    # only prevents module-import time from disappearing from V4's remaining
    # wall budget and receipt.
    real_monotonic = V4.time.monotonic
    old_bootstrap_ticks = getattr(V4, "_BOOTSTRAP_PROC_TICKS", None)
    old_bootstrap_cgroup = getattr(V4, "_BOOTSTRAP_CGROUP_SECONDS", None)
    first_clock_read = True

    def _entry_anchored_monotonic() -> float:
        nonlocal first_clock_read
        if first_clock_read:
            first_clock_read = False
            return _BOOTSTRAP_WALL
        return real_monotonic()

    V4._current_after_reservation = _current_after_reservation
    V4.time.monotonic = _entry_anchored_monotonic
    # V4's own raw baseline is captured when V4 is imported, which is later
    # than this wrapper's first executable line because V6 imports V5 first.
    # Carry the early raw values into V4 for this invocation only; the module
    # globals are restored below so no later run inherits stale process data.
    V4._BOOTSTRAP_PROC_TICKS = _SCRIPT_ENTRY_PROC_TICKS
    V4._BOOTSTRAP_CGROUP_SECONDS = _SCRIPT_ENTRY_CGROUP_SECONDS
    try:
        return V4._run_fixed(path, io_slot_approved=io_slot_approved,
                              parent_pid=parent_pid)
    finally:
        V4._current_after_reservation = old_callback
        V4.time.monotonic = real_monotonic
        V4._BOOTSTRAP_PROC_TICKS = old_bootstrap_ticks
        V4._BOOTSTRAP_CGROUP_SECONDS = old_bootstrap_cgroup


def build_forward_request(*, base_request: Path | str, current_binding: Path | str,
                          output: Path | str, parent_attempt_id: str,
                          supervisor_output_root: Path | str, home_receipt: Path | str,
                          max_wall_seconds: float | None = None,
                          trace_path: Path | str | None = None,
                          allow_missing_parent: bool | None = None) -> dict[str, Any]:
    """Build a fresh V6 request through the immutable V5/V4 builder."""
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise TypedParentV6CurrentError(f"refusing existing V6 request: {target}")
    with tempfile.TemporaryDirectory(prefix="ds02-v6-builder-") as tmp:
        intermediate = Path(tmp) / "v5-request.json"
        V5.build_forward_request(
            base_request=base_request, current_binding=current_binding,
            output=intermediate, parent_attempt_id=parent_attempt_id,
            supervisor_output_root=supervisor_output_root, home_receipt=home_receipt,
            max_wall_seconds=max_wall_seconds, trace_path=trace_path,
            allow_missing_parent=allow_missing_parent)
        value = json.loads(intermediate.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value.get("sha256") != canonical_sha(value):
        raise TypedParentV6CurrentError("V5 intermediate request is not canonical")
    bindings = value.get("static_bindings")
    if not isinstance(bindings, list):
        raise TypedParentV6CurrentError("V5 static bindings are missing")
    if any(isinstance(item, Mapping) and item.get("role") == "typed_only_parent_v6_current_bound"
           for item in bindings):
        raise TypedParentV6CurrentError("V6 parent role is already bound")
    bindings.append(V4.P1._static(SCRIPT, "typed_only_parent_v6_current_bound"))
    value["static_bindings"] = bindings
    value["execution"] = dict(value.get("execution", {}))
    value["execution"]["current_adapter"] = {
        "module": "ds_data02_stage2_f2_typed_only_evaluator_parent_v2_current_bound.py",
        "lookup": "V4.BASE.BASE._current_item",
        "phase": "AFTER_PARENT_RESERVATION",
        "source_callback_is_not_mocked": True,
    }
    value["execution"]["wall_clock_capture"] = {
        "phase": "FIRST_SCRIPT_EXECUTION_BEFORE_V5_V4_CLOSURE_IMPORT",
        "remaining_wall_includes_closure_import": True,
        "outer_runtime_max_must_cover_full_invocation": True,
        "cleanup_grace_is_separate_bounded_phase": True,
    }
    value["execution"]["cpu_baseline_capture"] = {
        "phase": "FIRST_SCRIPT_EXECUTION_BEFORE_V5_V4_CLOSURE_IMPORT",
        "carried_into_v4_bootstrap_snapshot": True,
        "systemd_terminal_cpu_must_still_be_compared_after_run": True,
    }
    value["v6_current_forward"] = {
        "schema": FORWARD_SCHEMA,
        "previous_v5_request": {
            "path": str(Path(base_request).expanduser().resolve()),
            "sha256": value.get("v5_current_forward", {}).get("base_v4_request", {}).get("sha256"),
        },
        "v5_wrapper": {"path": str(V5_SCRIPT), "sha256": V4._sha_file(V5_SCRIPT)},
        "v4_wrapper": {"path": str(V4.SCRIPT), "sha256": V4._sha_file(V4.SCRIPT)},
        "corrected_callback": "V4.BASE.BASE._current_item",
        "same_parent_ledger": True,
        "new_ledger_owner": False,
        "post_reservation_current_validation": True,
        "hdf5_or_bi4_content_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    # Keep the V1/V4 validator's exact executable status.  The V6 marker is
    # additive; changing ``READY_FOR_PARENT_GUARD`` would make the reviewed
    # parent reject its own request before reservation.
    if value.get("status") != "READY_FOR_PARENT_GUARD":
        raise TypedParentV6CurrentError("V5 request is not executable by the parent guard")
    value["v6_status"] = "READY_FOR_PARENT_V6_CURRENT_ADAPTER_GUARD"
    value["raw_opened"] = False
    value["hdf5_opened"] = False
    value["model_invoked"] = False
    value["cfd_invoked"] = False
    value["qualification"] = dict(UNKNOWN)
    value["sha256"] = canonical_sha(value)
    _write_new(target, value)
    return {"status": value["v6_status"], "schema": SCHEMA, "request": str(target),
            "sha256": value["sha256"], "static_role_count": len(bindings),
            "current_adapter": "V4.BASE.BASE._current_item",
            "hdf5_or_bi4_read": False, "payload_read": False,
            "qualification": dict(UNKNOWN)}


def preflight(path: Path | str) -> dict[str, Any]:
    _validate_request(path, verify_static_content=False)
    return {"schema": "ds02.stage2.f2-typed-only-evaluator-parent-report.v6-current-bound",
            "status": "READY_FOR_PARENT_IO_SLOT", "metadata_only": True,
            "ledger_mutated": False, "source_content_validation_phase": "AFTER_PARENT_RESERVATION",
            "current_adapter": "V4.BASE.BASE._current_item",
            "hdf5_or_bi4_read": False, "raw_opened": False,
            "qualification": dict(UNKNOWN)}


def run(path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    return _run_fixed(path, io_slot_approved=io_slot_approved, parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-forward-request")
    build.add_argument("--base-request", type=Path, required=True)
    build.add_argument("--current-binding", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--parent-attempt-id", required=True)
    build.add_argument("--supervisor-output-root", type=Path, required=True)
    build.add_argument("--home-receipt", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float)
    build.add_argument("--trace-path", type=Path)
    group = build.add_mutually_exclusive_group()
    group.add_argument("--allow-missing-parent", dest="allow_missing_parent", action="store_true")
    group.add_argument("--disallow-missing-parent", dest="allow_missing_parent", action="store_false")
    build.set_defaults(allow_missing_parent=None)
    pre = sub.add_parser("preflight")
    pre.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-forward-request":
            value = build_forward_request(
                base_request=args.base_request, current_binding=args.current_binding,
                output=args.output, parent_attempt_id=args.parent_attempt_id,
                supervisor_output_root=args.supervisor_output_root,
                home_receipt=args.home_receipt, max_wall_seconds=args.max_wall_seconds,
                trace_path=args.trace_path, allow_missing_parent=args.allow_missing_parent)
        elif args.command == "preflight":
            value = preflight(args.request)
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid)
    except (TypedParentV6CurrentError, V5.TypedParentV5CurrentError,
            V4.TypedParentV3CurrentError, V4.P1.TypedParentError,
            V4.P1.ParentDeadline, V4.P1.ParentCancelled,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator parent V6 current-bound: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 1 if str(value.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
