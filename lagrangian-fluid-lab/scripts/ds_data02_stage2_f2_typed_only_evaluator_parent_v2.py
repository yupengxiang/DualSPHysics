#!/usr/bin/env python3
"""Parent-guarded V2 typed-only evaluator.

The V1 parent implementation is immutable and already carries the tested
same-parent reservation, literal virtual-environment invocation, strace,
two-filesystem accounting, cancellation, and cleanup machinery.  V2 binds
that implementation to the V2 evaluator and fresh V10 proof request through
an additive module namespace; it does not alter V1 bytes or create a second
ledger owner.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V1_PARENT_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v1.py"
V2_EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v2.py"
SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-request.v2"
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-report.v2"
TE_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-request.v2"


class TypedParentV2Error(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentV2Error(f"cannot load parent implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P1 = _load(V1_PARENT_SCRIPT, "ds02_bound_typed_only_evaluator_parent_v1_for_v2")

# Rebind only the V1 module's dependency constants.  Its implementation and
# all resource/cleanup code remain the immutable, already-reviewed V1 code.
P1.SCRIPT = SCRIPT
P1.SCRIPT_DIR = SCRIPT_DIR
P1.TE_SCRIPT = V2_EVALUATOR_SCRIPT
P1.TE_SCHEMA = TE_SCHEMA
P1.SCHEMA = SCHEMA
P1.REPORT_SCHEMA = REPORT_SCHEMA
P1.TE = _load(V2_EVALUATOR_SCRIPT, "ds02_bound_typed_only_evaluator_v2_for_parent_v2")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return P1.canonical_sha(value)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return P1._write_new(path, value)


def build_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Build a V2 parent request through V1's resource-bound builder."""
    output = Path(kwargs.get("output") if "output" in kwargs else args[2]).expanduser().resolve()
    intermediate = Path("/tmp") / f"ds02-typed-parent-v2-intermediate-{__import__('os').getpid()}.json"
    if intermediate.exists():
        raise TypedParentV2Error(f"intermediate parent request already exists: {intermediate}")
    if "output" in kwargs:
        child_kwargs = dict(kwargs)
        child_kwargs["output"] = intermediate
    else:
        child_args = list(args)
        child_args[2] = intermediate
        child_kwargs = None
    try:
        result = P1.build_request(*child_args, **child_kwargs) if child_kwargs is None else P1.build_request(**child_kwargs)
        request = json.loads(intermediate.read_text(encoding="utf-8"))
    except Exception as error:
        raise TypedParentV2Error(f"V1 parent resource binding failed: {error}") from error
    if request.get("schema") != SCHEMA:
        raise TypedParentV2Error("V2 rebinding did not produce V2 parent schema")
    request["v2_forward"] = {
        "schema": "ds02.stage2.f2-typed-only-evaluator-parent-v2-forward.v1",
        "source_parent_implementation": {"path": str(V1_PARENT_SCRIPT),
                                          "sha256": P1.sha256_file(V1_PARENT_SCRIPT)},
        "typed_evaluator": {"path": str(V2_EVALUATOR_SCRIPT),
                             "sha256": P1.sha256_file(V2_EVALUATOR_SCRIPT),
                             "schema": TE_SCHEMA},
        "same_parent_ledger": True,
        "new_ledger_owner": False,
        "original_path_fallback": "FORBIDDEN",
    }
    parent_binding = request.get("parent_resource_binding")
    accounting = request.get("accounting")
    if isinstance(parent_binding, dict):
        parent_binding["reservation_id"] = str(parent_binding.get("reservation_id", "")).replace(
            "typed-only-evaluator-v1", "typed-only-evaluator-v2")
        parent_binding["charge_id"] = str(parent_binding.get("charge_id", "")).replace(
            "typed-only-evaluator-v1", "typed-only-evaluator-v2")
    if isinstance(accounting, dict):
        accounting["reservation_id"] = str(accounting.get("reservation_id", "")).replace(
            "typed-only-evaluator-v1", "typed-only-evaluator-v2")
        accounting["charge_id"] = str(accounting.get("charge_id", "")).replace(
            "typed-only-evaluator-v1", "typed-only-evaluator-v2")
    bindings = request.get("static_bindings")
    if isinstance(bindings, list):
        for item in bindings:
            if isinstance(item, dict) and item.get("role") == "typed_only_evaluator_v1":
                item["role"] = "typed_only_evaluator_v2"
            if isinstance(item, dict) and item.get("role") == "typed_only_parent_v1":
                item["role"] = "typed_only_parent_v2"
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    result = dict(result)
    result.update({"request": str(target), "sha256": request["sha256"],
                   "schema": SCHEMA, "typed_evaluator_schema": TE_SCHEMA})
    return result


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    return P1._validate_request(path, verify_static_content=verify_static_content)


def run(path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    return P1.run(path, io_slot_approved=io_slot_approved, parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--typed-request", type=Path, required=True)
    build.add_argument("--parent-v3-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--external-filesystem", type=Path, required=True)
    build.add_argument("--ledger", type=Path, required=True)
    build.add_argument("--parent-attempt-id", required=True)
    build.add_argument("--supervisor-output-root", type=Path, required=True)
    build.add_argument("--home-receipt", type=Path, required=True)
    build.add_argument("--python-executable", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float, default=300.0)
    build.add_argument("--external-bytes", type=int, default=256 * 1024 * 1024)
    build.add_argument("--home-receipt-bytes", type=int, default=256 * 1024)
    build.add_argument("--allow-missing-parent", action="store_true")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(typed_request=args.typed_request,
                                  parent_v3_request=args.parent_v3_request,
                                  output=args.output,
                                  external_filesystem=args.external_filesystem,
                                  ledger=args.ledger,
                                  parent_attempt_id=args.parent_attempt_id,
                                  supervisor_output_root=args.supervisor_output_root,
                                  home_receipt=args.home_receipt,
                                  python_executable=args.python_executable,
                                  max_wall_seconds=args.max_wall_seconds,
                                  external_bytes=args.external_bytes,
                                  home_receipt_bytes=args.home_receipt_bytes,
                                  allow_missing_parent=args.allow_missing_parent)
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid)
    except (TypedParentV2Error, P1.TypedParentError, P1.ParentDeadline, P1.ParentCancelled,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator parent V2: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
