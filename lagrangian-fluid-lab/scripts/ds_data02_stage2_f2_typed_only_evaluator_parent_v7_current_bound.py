#!/usr/bin/env python3
"""V7 additive parent binding for the complete dual-CURRENT evaluator.

V6 and its root078 request remain immutable.  This forward parent keeps V6's
same-parent reservation/callback and swaps only the child evaluator source for
the V4 shadow scorer, which rebinds ``observer_profile`` together with the
request CURRENT fields.  New requests explicitly bind the V7 parent and child
bytes; no existing request is rewritten.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V6_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v6_current_bound.py"
EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v4_current_bound.py"
SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-request.v2"
FORWARD_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-v7-current-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class TypedParentV7CurrentError(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentV7CurrentError(f"cannot load bound source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V6 = _load(V6_SCRIPT, "ds02_bound_typed_only_evaluator_parent_v6_for_v7")
V4 = V6.V4
EVALUATOR = _load(EVALUATOR_SCRIPT, "ds02_bound_typed_only_evaluator_v4_for_parent_v7")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V6.canonical_sha(value)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return V6._write_new(path, value)


def _patch_child_sources() -> dict[str, Any]:
    """Install V7 child globals and return the exact values to restore."""
    old = {
        "evaluator_script": V4.EVALUATOR_SCRIPT,
        "evaluator": V4.EVALUATOR,
        "te_script": V4.P1.TE_SCRIPT,
        "te_schema": V4.P1.TE_SCHEMA,
        "te": V4.P1.TE,
        "child_pass_status": V4.CHILD_PASS_STATUS,
    }
    V4.EVALUATOR_SCRIPT = EVALUATOR_SCRIPT
    V4.EVALUATOR = EVALUATOR
    V4.P1.TE_SCRIPT = EVALUATOR_SCRIPT
    V4.P1.TE_SCHEMA = EVALUATOR.REQUEST_SCHEMA
    V4.P1.TE = EVALUATOR
    # The V4 evaluator emits this existing PASS token; V7 changes the source
    # and shadow semantics without inventing a new scientific status token.
    V4.CHILD_PASS_STATUS = "PASS_DEVELOPMENT_TYPED_ONLY_OPERATOR_TRIAL_V3_DUAL_CURRENT"
    return old


def _restore_child_sources(old: Mapping[str, Any]) -> None:
    V4.EVALUATOR_SCRIPT = old["evaluator_script"]
    V4.EVALUATOR = old["evaluator"]
    V4.P1.TE_SCRIPT = old["te_script"]
    V4.P1.TE_SCHEMA = old["te_schema"]
    V4.P1.TE = old["te"]
    V4.CHILD_PASS_STATUS = old["child_pass_status"]


def _replace_evaluator_binding(bindings: list[Any]) -> list[Any]:
    out: list[Any] = []
    replaced = False
    for item in bindings:
        if isinstance(item, Mapping) and item.get("role") == "typed_only_evaluator_v3_current_bound":
            if not replaced:
                out.append(V4.P1._static(EVALUATOR_SCRIPT, "typed_only_evaluator_v4_current_bound"))
                replaced = True
            continue
        out.append(item)
    if not replaced:
        out.append(V4.P1._static(EVALUATOR_SCRIPT, "typed_only_evaluator_v4_current_bound"))
    return out


def build_forward_request(*, base_request: Path | str, current_binding: Path | str,
                          output: Path | str, parent_attempt_id: str,
                          supervisor_output_root: Path | str, home_receipt: Path | str,
                          max_wall_seconds: float | None = None,
                          trace_path: Path | str | None = None,
                          allow_missing_parent: bool | None = None) -> dict[str, Any]:
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise TypedParentV7CurrentError(f"refusing existing V7 request: {target}")
    old = _patch_child_sources()
    try:
        with tempfile.TemporaryDirectory(prefix="ds02-v7-builder-") as tmp:
            intermediate = Path(tmp) / "v6-request.json"
            V6.build_forward_request(
                base_request=base_request, current_binding=current_binding,
                output=intermediate, parent_attempt_id=parent_attempt_id,
                supervisor_output_root=supervisor_output_root,
                home_receipt=home_receipt, max_wall_seconds=max_wall_seconds,
                trace_path=trace_path, allow_missing_parent=allow_missing_parent)
            value = json.loads(intermediate.read_text(encoding="utf-8"))
    finally:
        _restore_child_sources(old)
    if value.get("schema") != SCHEMA or value.get("sha256") != canonical_sha(value):
        raise TypedParentV7CurrentError("V6 intermediate request is not canonical")
    bindings = value.get("static_bindings")
    if not isinstance(bindings, list):
        raise TypedParentV7CurrentError("V6 static bindings are missing")
    value["static_bindings"] = _replace_evaluator_binding(bindings)
    execution = dict(value.get("execution", {}))
    closed = list(execution.get("closed_command", []))
    execution["closed_command"] = [str(EVALUATOR_SCRIPT) if item == str(V6.V4.P1.TE_SCRIPT) else item
                                    for item in closed]
    execution["child_evaluator"] = {
        "path": str(EVALUATOR_SCRIPT),
        "schema": EVALUATOR.REQUEST_SCHEMA,
        "dual_current_shadow": "CURRENT fields and observer_profile are rebound together",
        "profile_self_hash_recomputed": True,
    }
    value["execution"] = execution
    forward = dict(value.get("v6_current_forward", {}))
    forward["child_evaluator"] = {
        "path": str(EVALUATOR_SCRIPT),
        "sha256": V6._sha_file(EVALUATOR_SCRIPT),
        "replaces": "typed_only_evaluator_v3_current_bound",
    }
    value["v6_current_forward"] = forward
    value["v7_current_forward"] = {
        "schema": FORWARD_SCHEMA,
        "base_v6_request_sha256": value.get("sha256"),
        "parent_wrapper": {"path": str(SCRIPT), "sha256": V4._sha_file(SCRIPT)},
        "child_evaluator": {"path": str(EVALUATOR_SCRIPT),
                             "sha256": V4._sha_file(EVALUATOR_SCRIPT)},
        "same_parent_ledger": True,
        "new_ledger_owner": False,
        "observer_profile_current_fields_rebound": True,
        "historical_result_view_only": True,
        "hdf5_or_bi4_content_read_during_build": False,
        "qualification": dict(UNKNOWN),
    }
    # The base SHA in v7_current_forward is the pre-v7 value by design; the
    # published request's own SHA is recomputed below.
    value["sha256"] = canonical_sha(value)
    result = _write_new(target, value)
    return {"status": value.get("status"), "schema": value["schema"],
            "request": str(result), "sha256": value["sha256"],
            "hdf5_or_bi4_read": False, "payload_read": False,
            "qualification": dict(UNKNOWN)}


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    old = _patch_child_sources()
    try:
        return V6._validate_request(path, verify_static_content=verify_static_content)
    finally:
        _restore_child_sources(old)


def run(path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    old = _patch_child_sources()
    try:
        return V6._run_fixed(path, io_slot_approved=io_slot_approved, parent_pid=parent_pid)
    finally:
        _restore_child_sources(old)


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
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--request", type=Path, required=True)
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
            _validate_request(args.request)
            value = {"schema": "ds02.stage2.f2-typed-only-evaluator-parent-report.v7-current-bound",
                     "status": "READY_FOR_PARENT_IO_SLOT", "metadata_only": True,
                     "ledger_mutated": False, "qualification": dict(UNKNOWN)}
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid)
    except (TypedParentV7CurrentError, V6.TypedParentV6CurrentError,
            V6.V4.TypedParentV3CurrentError, OSError, ValueError,
            TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator parent V7 current-bound: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 1 if str(value.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
