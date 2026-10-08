#!/usr/bin/env python3
"""Parent V2 wrapper that enforces the exact CURRENT336 reconciliation.

The underlying V2 parent remains the same-parent resource owner.  This
forward wrapper adds the sidecar as an immutable static input and validates
the real CURRENT file before delegating to the already-reviewed parent
runner.  It does not create a second ledger owner or read H5/BI4/raw data.
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
PARENT_V2_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v2.py"
EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v2_current_bound.py"
CURRENT_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_current_catalog_binding_v1.py"
SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-request.v2"
TE_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-request.v2"


class TypedParentV2CurrentError(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentV2CurrentError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P2 = _load(PARENT_V2_SCRIPT, "ds02_bound_typed_only_evaluator_parent_v2_for_current_bound")
CURRENT = _load(CURRENT_SCRIPT, "ds02_bound_current_catalog_binding_v1_for_parent_v2")
EVAL = _load(EVALUATOR_SCRIPT, "ds02_bound_typed_only_evaluator_v2_current_bound_for_parent")

# Rebind the V1 parent internals held by the V2 wrapper.  The resource,
# timeout, cancellation, strace, and accounting implementation remains the
# existing V1/V2 code; only the typed child module is the current-bound one.
P2.SCRIPT = SCRIPT
P2.SCRIPT_DIR = SCRIPT_DIR
P2.V2_EVALUATOR_SCRIPT = EVALUATOR_SCRIPT
P2.P1.SCRIPT = SCRIPT
P2.P1.SCRIPT_DIR = SCRIPT_DIR
P2.P1.TE_SCRIPT = EVALUATOR_SCRIPT
P2.P1.TE_SCHEMA = TE_SCHEMA
P2.P1.TE = EVAL


def canonical_sha(value: Mapping[str, Any]) -> str:
    return P2.canonical_sha(value)


def _file(value: Any, role: str) -> Path:
    return P2.P1._file(value, role)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return P2._write_new(path, value)


def _current_item(request: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    item = request.get("current_catalog_binding")
    if not isinstance(item, Mapping):
        raise TypedParentV2CurrentError("parent current_catalog_binding is missing")
    sidecar = _file(item.get("path"), "CURRENT catalog binding sidecar")
    if item.get("sha256") != P2.P1.sha256_file(sidecar):
        raise TypedParentV2CurrentError("parent CURRENT sidecar SHA differs")
    sidecar_value = CURRENT._json(sidecar, "CURRENT catalog binding sidecar")[1]
    current_path = _file(sidecar_value.get("current_catalog", {}).get("path"), "CURRENT336 source")
    frozen_path = _file(sidecar_value.get("frozen_v15_request", {}).get("path"), "frozen V15 source")
    proof_path = _file(sidecar_value.get("historical_v10_proof", {}).get("path"), "historical V10 proof source")
    info = CURRENT.validate_binding(sidecar, current_catalog=current_path,
                                    frozen_request=frozen_path, proof=proof_path)
    return sidecar, info


def build_request(*, typed_request: Path | str, parent_v3_request: Path | str,
                  current_binding: Path | str, output: Path | str,
                  external_filesystem: Path | str, ledger: Path | str,
                  parent_attempt_id: str, supervisor_output_root: Path | str,
                  home_receipt: Path | str, python_executable: Path | str,
                  max_wall_seconds: float = 300.0,
                  external_bytes: int = 256 * 1024 * 1024,
                  home_receipt_bytes: int = 256 * 1024,
                  allow_missing_parent: bool = False) -> dict[str, Any]:
    sidecar = _file(current_binding, "CURRENT catalog binding sidecar")
    sidecar_value = CURRENT._json(sidecar, "CURRENT catalog binding sidecar")[1]
    current_path = _file(sidecar_value.get("current_catalog", {}).get("path"), "CURRENT336 source")
    frozen_path = _file(sidecar_value.get("frozen_v15_request", {}).get("path"), "frozen V15 source")
    proof_path = _file(sidecar_value.get("historical_v10_proof", {}).get("path"), "historical V10 proof source")
    current_info = CURRENT.validate_binding(sidecar, current_catalog=current_path,
                                            frozen_request=frozen_path, proof=proof_path)
    temporary = Path("/tmp") / f"ds02-typed-parent-v2-current-{__import__('os').getpid()}.json"
    if temporary.exists():
        raise TypedParentV2CurrentError(f"temporary parent request already exists: {temporary}")
    try:
        result = P2.build_request(
            typed_request=typed_request, parent_v3_request=parent_v3_request,
            output=temporary, external_filesystem=external_filesystem, ledger=ledger,
            parent_attempt_id=parent_attempt_id, supervisor_output_root=supervisor_output_root,
            home_receipt=home_receipt, python_executable=python_executable,
            max_wall_seconds=max_wall_seconds, external_bytes=external_bytes,
            home_receipt_bytes=home_receipt_bytes, allow_missing_parent=allow_missing_parent)
        request = json.loads(temporary.read_text(encoding="utf-8"))
    except Exception as error:
        raise TypedParentV2CurrentError(f"V2 parent metadata binding failed: {error}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    request["current_catalog_binding"] = {
        "path": str(sidecar), "sha256": P2.P1.sha256_file(sidecar),
        "schema": CURRENT.SCHEMA, "content_read_during_build": True,
        "current_catalog_sha256": current_info["current_catalog_sha256"],
        "historical_result_current_catalog_sha256": current_info["historical_result_current_catalog_sha256"],
        "case_join_status": current_info["case_join"]["status"],
    }
    bindings = request.get("static_bindings")
    if not isinstance(bindings, list):
        raise TypedParentV2CurrentError("parent static bindings are missing")
    bindings.append(P2.P1._static(sidecar, "current_catalog_binding"))
    bindings.append(P2.P1._static(CURRENT_SCRIPT, "current_catalog_binding_module"))
    # The base V2/V1 evaluator and V10->V9->V8 imports are not all listed by
    # the immutable parent-v1 binding table.  Register their exact files so a
    # private -I child cannot silently import an original worktree copy.
    closure = (
        (SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v2.py", "typed_evaluator_v2_base"),
        (SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v1.py", "typed_evaluator_v1_base"),
        (SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v10.py", "fresh_v16_consumer_v10"),
        (SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v9.py", "fresh_v16_consumer_v9"),
        (SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py", "fresh_v16_consumer_v8"),
        (PARENT_V2_SCRIPT, "typed_only_parent_v2_base"),
        (SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v1.py", "typed_only_parent_v1_base"),
    )
    for path, role in closure:
        bindings.append(P2.P1._static(path, role))
    request["v2_current_forward"] = {
        "schema": "ds02.stage2.f2-typed-only-evaluator-parent-v2-current-forward.v1",
        "base_parent_schema": SCHEMA,
        "typed_evaluator_schema": TE_SCHEMA,
        "current_binding_schema": CURRENT.SCHEMA,
        "current_binding_module": {"path": str(CURRENT_SCRIPT),
                                    "sha256": P2.P1.sha256_file(CURRENT_SCRIPT)},
        "current_binding_sha256": P2.P1.sha256_file(sidecar),
        "actual_current_catalog_sha256": current_info["current_catalog_sha256"],
        "historical_result_current_catalog_sha256": current_info["historical_result_current_catalog_sha256"],
        "same_parent_ledger": True, "new_ledger_owner": False,
        "hdf5_or_bi4_content_read_during_build": False,
        "original_path_fallback": "FORBIDDEN",
    }
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    result = dict(result)
    result.update({"request": str(target), "sha256": request["sha256"],
                   "schema": SCHEMA, "current_binding_sha256": P2.P1.sha256_file(sidecar),
                   "actual_current_catalog_sha256": current_info["current_catalog_sha256"],
                   "historical_result_current_catalog_sha256": current_info["historical_result_current_catalog_sha256"],
                   "hdf5_or_bi4_read": False, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}})
    return result


def _validate_request(path: Path | str, *, verify_static_content: bool = False) -> dict[str, Any]:
    bound = P2._validate_request(path, verify_static_content=verify_static_content)
    sidecar, info = _current_item(bound["request"])
    bound["current_binding_path"] = sidecar
    bound["current_binding_info"] = info
    return bound


def run(path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None) -> dict[str, Any]:
    # Preflight the current source before entering the immutable parent runner;
    # the parent still owns reservation and child content hashing.
    _validate_request(path, verify_static_content=False)
    return P2.run(path, io_slot_approved=io_slot_approved, parent_pid=parent_pid)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("typed-request", "parent-v3-request", "current-binding", "output", "external-filesystem", "ledger", "supervisor-output-root", "home-receipt", "python-executable"):
        build.add_argument(f"--{name}", type=Path, required=True)
    build.add_argument("--parent-attempt-id", required=True)
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
                                  current_binding=args.current_binding, output=args.output,
                                  external_filesystem=args.external_filesystem, ledger=args.ledger,
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
    except (TypedParentV2CurrentError, P2.TypedParentV2Error,
            P2.P1.TypedParentError, P2.P1.ParentDeadline, P2.P1.ParentCancelled,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator parent V2 current-bound: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
