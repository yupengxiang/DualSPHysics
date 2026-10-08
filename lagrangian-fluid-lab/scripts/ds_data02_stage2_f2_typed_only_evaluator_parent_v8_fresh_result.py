#!/usr/bin/env python3
"""V8 typed-only parent binding for a fresh producer result.

V7 and all older requests remain immutable.  This forward builder changes the
typed-result binding as a complete unit: the fresh request, producer report,
proof request, proof, source contract, and result stat are all bound to a new
namespace before a parent request is written.  It never hashes the result
payload; the result SHA is verified by the parent after reservation.  It also
refuses the historical root051/root060 typed request and proof paths, so a
metadata-only rebuild cannot accidentally receive old-product credit.

The runtime runner remains the reviewed V7 parent/evaluator chain.  A V8
request therefore carries an explicit ``runtime_semantics`` marker saying
that the fresh result's CURRENT-view join and full V10 semantics are deferred
to the post-reservation child.  QI/QN/QE remain UNKNOWN.
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
V7_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_parent_v7_current_bound.py"
EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v4_current_bound.py"
SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-request.v2"
FORWARD_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-parent-v8-fresh-result-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
TE_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-request.v2"


class TypedParentV8FreshResultError(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedParentV8FreshResultError(f"cannot load bound source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V7 = _load(V7_SCRIPT, "ds02_bound_typed_only_evaluator_parent_v7_for_v8")
V6 = V7.V6
V4 = V6.V4
EVALUATOR = _load(EVALUATOR_SCRIPT, "ds02_bound_typed_only_evaluator_v4_for_parent_v8")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V6.canonical_sha(value)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return V6._write_new(path, value)


def _sha_file(path: Path | str) -> str:
    return V4._sha_file(path)


def _static(path: Path | str, role: str) -> dict[str, Any]:
    return V4.P1._static(Path(path).expanduser().resolve(), role)


def _load_fresh_typed_request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    """Validate only the request/dependency metadata, never result content."""
    typed_path = V4.P1._file(path, "fresh typed-only evaluator request")
    typed = V4.P1._load_typed_request(typed_path)
    if typed.get("schema") != TE_SCHEMA:
        raise TypedParentV8FreshResultError("fresh typed request schema differs")
    return typed_path, typed


def _old_product_paths(base: Mapping[str, Any]) -> set[Path]:
    """Return immutable product paths which a fresh request must not reuse."""
    result: set[Path] = set()
    for key in ("typed_request", "proof", "proof_request", "producer_report", "source_contract"):
        item = base.get(key)
        if isinstance(item, Mapping) and item.get("path"):
            result.add(Path(str(item["path"])).expanduser().resolve())
    return result


def _old_product_hashes(base: Mapping[str, Any]) -> set[str]:
    """Collect direct old-product hashes without opening payload files."""
    result: set[str] = set()
    for key in ("typed_request", "proof", "proof_request", "producer_report", "source_contract"):
        item = base.get(key)
        if isinstance(item, Mapping) and isinstance(item.get("sha256"), str):
            result.add(str(item["sha256"]))
    bindings = base.get("static_bindings")
    if isinstance(bindings, list):
        for item in bindings:
            if (isinstance(item, Mapping) and item.get("role") == "typed_evaluator_request"
                    and isinstance(item.get("sha256"), str)):
                result.add(str(item["sha256"]))
    typed_item = base.get("typed_request")
    if isinstance(typed_item, Mapping) and typed_item.get("path"):
        try:
            typed = V4.P1._json(Path(str(typed_item["path"])).expanduser().resolve(),
                                "old typed-only evaluator request")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            typed = {}
        for key in ("producer_report", "proof_request", "proof", "source_contract", "frozen_request"):
            item = typed.get(key)
            if isinstance(item, Mapping) and isinstance(item.get("sha256"), str):
                result.add(str(item["sha256"]))
    return result


def _fresh_binding(value: Mapping[str, Any], typed: Mapping[str, Any]) -> dict[str, Any]:
    result = typed.get("result")
    current = typed.get("current_catalog_binding")
    if not isinstance(result, Mapping) or not isinstance(current, Mapping):
        raise TypedParentV8FreshResultError("fresh typed request lacks result/current binding")
    result_path = Path(str(result.get("path"))).expanduser().resolve()
    if not result_path.is_file():
        raise TypedParentV8FreshResultError("fresh typed result is missing")
    result_stat = result_path.stat()
    declared_bytes = result.get("bytes")
    if isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int):
        raise TypedParentV8FreshResultError("fresh typed result bytes must be an integer")
    if int(declared_bytes) != int(result_stat.st_size) or int(declared_bytes) <= 0:
        raise TypedParentV8FreshResultError("fresh typed result stat differs")
    declared_sha = result.get("sha256")
    if not isinstance(declared_sha, str) or len(declared_sha) != 64:
        raise TypedParentV8FreshResultError("fresh typed result SHA is malformed")
    current_sha = current.get("current_catalog_sha256")
    if not isinstance(current_sha, str) or len(current_sha) != 64:
        raise TypedParentV8FreshResultError("fresh typed CURRENT binding SHA is malformed")
    return {
        "result": {"path": str(result_path), "sha256": declared_sha,
                    "bytes": int(declared_bytes),
                    "mtime_ns": int(result_stat.st_mtime_ns),
                    "mode_bits": int(result_stat.st_mode & 0o777),
                    "content_hash_phase": "AFTER_PARENT_RESERVATION"},
        "current_catalog_sha256": current_sha,
        "producer_report": dict(typed["producer_report"]),
        "proof_request": dict(typed["proof_request"]),
        "proof": dict(typed["proof"]),
        "source_contract": dict(typed["source_contract"]),
        "frozen_request": dict(typed["frozen_request"]),
    }


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
                          fresh_typed_request: Path | str,
                          output: Path | str, parent_attempt_id: str,
                          supervisor_output_root: Path | str, home_receipt: Path | str,
                          max_wall_seconds: float | None = None,
                          trace_path: Path | str | None = None,
                          allow_missing_parent: bool | None = None) -> dict[str, Any]:
    """Build V8 from V7 while rebinding every fresh typed-product input.

    ``fresh_typed_request`` is read as JSON and its result is stat-checked,
    but result content is never hashed here.  The old request's product paths
    are compared before writing the new request; this catches accidental
    reuse of root051/root060 even when a caller changes only the parent ID.
    """
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise TypedParentV8FreshResultError(f"refusing existing V8 request: {target}")
    fresh_path, fresh_typed = _load_fresh_typed_request(fresh_typed_request)
    old_request_path = Path(base_request).expanduser().resolve()
    old_request = V4.P1._json(old_request_path, "base V7 typed-only parent request")
    old_typed_item = old_request.get("typed_request")
    old_typed_path = (Path(str(old_typed_item.get("path"))).expanduser().resolve()
                      if isinstance(old_typed_item, Mapping) and old_typed_item.get("path")
                      else None)
    old_product = _old_product_paths(old_request)
    old_hashes = _old_product_hashes(old_request)
    fresh_request_sha = _sha_file(fresh_path)
    if fresh_path in old_product or fresh_request_sha in old_hashes:
        raise TypedParentV8FreshResultError("fresh typed request reuses an immutable old product path")
    fresh = _fresh_binding(old_request, fresh_typed)
    for key in ("producer_report", "proof_request", "proof", "source_contract"):
        path = Path(str(fresh[key]["path"])).expanduser().resolve()
        if path in old_product or str(fresh[key].get("sha256")) in old_hashes:
            raise TypedParentV8FreshResultError(f"fresh {key} reuses an immutable old product path")

    old = _patch_child_sources()
    # V7's builder was never consumed through its build path and calls a
    # helper that V6 exposes only indirectly through V4.  Supply that helper
    # for this additive invocation, then restore the module exactly.
    had_v6_sha = hasattr(V6, "_sha_file")
    old_v6_sha = getattr(V6, "_sha_file", None)
    V6._sha_file = V4._sha_file
    try:
        with tempfile.TemporaryDirectory(prefix="ds02-v8-builder-") as tmp:
            intermediate = Path(tmp) / "v7-request.json"
            V7.build_forward_request(
                base_request=base_request, current_binding=current_binding,
                output=intermediate, parent_attempt_id=parent_attempt_id,
                supervisor_output_root=supervisor_output_root,
                home_receipt=home_receipt, max_wall_seconds=max_wall_seconds,
                trace_path=trace_path, allow_missing_parent=allow_missing_parent)
            value = json.loads(intermediate.read_text(encoding="utf-8"))
    finally:
        if had_v6_sha:
            V6._sha_file = old_v6_sha
        else:
            delattr(V6, "_sha_file")
        _restore_child_sources(old)
    if value.get("schema") != SCHEMA or value.get("sha256") != canonical_sha(value):
        raise TypedParentV8FreshResultError("V7 intermediate request is not canonical")
    bindings = value.get("static_bindings")
    if not isinstance(bindings, list):
        raise TypedParentV8FreshResultError("V7 static bindings are missing")

    # Replace, rather than append over, the old typed request role.  This is
    # what makes an eventual relocated run use the new result/proof graph.
    filtered: list[dict[str, Any]] = []
    replaced = False
    for item in bindings:
        if not isinstance(item, Mapping):
            continue
        if item.get("role") == "typed_evaluator_request":
            if replaced:
                raise TypedParentV8FreshResultError("duplicate typed_evaluator_request role")
            filtered.append(_static(fresh_path, "typed_evaluator_request"))
            replaced = True
        else:
            filtered.append(dict(item))
    if not replaced:
        filtered.append(_static(fresh_path, "typed_evaluator_request"))
    # V8 and V7 wrappers are both actionable runtime sources.  Their hashes
    # are small code reads, separate from the deferred result payload hash.
    for role, path in (("typed_only_parent_v7_current_bound", V7_SCRIPT),
                       ("typed_only_parent_v8_fresh_result", SCRIPT)):
        if any(item.get("role") == role for item in filtered):
            raise TypedParentV8FreshResultError(f"duplicate V8 static role: {role}")
        filtered.append(_static(path, role))
    # Keep the CURRENT sidecar's historical proof role as provenance for the
    # parent CURRENT join, but bind the fresh producer/proof graph separately
    # so the child cannot silently fall back to root060 files.
    for role, item in (("fresh_typed_producer_report", fresh["producer_report"]),
                       ("fresh_typed_proof_request", fresh["proof_request"]),
                       ("fresh_typed_proof", fresh["proof"]),
                       ("fresh_typed_source_contract", fresh["source_contract"]),
                       ("fresh_typed_frozen_request", fresh["frozen_request"])):
        path = Path(str(item["path"])).expanduser().resolve()
        if any(entry.get("role") == role for entry in filtered):
            raise TypedParentV8FreshResultError(f"duplicate V8 static role: {role}")
        filtered.append(_static(path, role))
    value["static_bindings"] = filtered

    old_typed_string = str(old_typed_path) if old_typed_path is not None else ""
    execution = dict(value.get("execution", {}))
    closed = list(execution.get("closed_command", []))
    execution["closed_command"] = [str(fresh_path) if str(item) == old_typed_string else item
                                    for item in closed]
    # A defensive check catches a future parent wrapper that stores the typed
    # path in a different command field instead of silently falling back.
    if old_typed_string and any(str(item) == old_typed_string for item in execution["closed_command"]):
        raise TypedParentV8FreshResultError("old typed request remains in closed command")
    execution["fresh_result_binding_phase"] = "AFTER_PARENT_RESERVATION"
    execution["result_payload_hash_during_build"] = False
    execution["typed_request_content_read_during_build"] = True
    value["execution"] = execution
    value["typed_request"] = {
        "path": str(fresh_path), "sha256": _sha_file(fresh_path),
        "schema": TE_SCHEMA, "immutable": True,
        "result_sha256": fresh["result"]["sha256"],
        "result_bytes": fresh["result"]["bytes"],
        "result_stat": {"mtime_ns": fresh["result"]["mtime_ns"],
                         "mode_bits": fresh["result"]["mode_bits"]},
        "result_content_verification": "AFTER_PARENT_RESERVATION",
    }
    value["v8_fresh_result_forward"] = {
        "schema": FORWARD_SCHEMA,
        "base_v7_request": {"path": str(old_request_path),
                             "sha256": old_request.get("sha256")},
        "parent_wrapper": {"path": str(SCRIPT), "sha256": _sha_file(SCRIPT)},
        "previous_parent_wrapper": {"path": str(V7_SCRIPT), "sha256": _sha_file(V7_SCRIPT)},
        "fresh_typed_request": {
            "path": str(fresh_path), "sha256": _sha_file(fresh_path),
            "schema": TE_SCHEMA, "result": fresh["result"]},
        "fresh_producer_report": fresh["producer_report"],
        "fresh_proof_request": fresh["proof_request"],
        "fresh_proof": fresh["proof"],
        "fresh_source_contract": fresh["source_contract"],
        "fresh_frozen_request": fresh["frozen_request"],
        "result_current_catalog_sha256": fresh["current_catalog_sha256"],
        "current_join": "DEFERRED_TO_PARENT_AFTER_RESERVATION",
        "old_typed_request_reuse": "FORBIDDEN",
        "old_proof_reuse": "FORBIDDEN",
        "result_content_hash_during_build": False,
        "result_content_hash_phase": "AFTER_PARENT_RESERVATION",
        "same_parent_ledger": True,
        "new_ledger_owner": False,
        "hdf5_or_bi4_content_read_during_build": False,
        "raw_to_typed_credit": "NOT_CLAIMED",
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "qualification": dict(UNKNOWN),
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "V8 accepts only a fresh typed request/proof graph; old root051/root060 product paths are rejected.",
        "The result SHA is declared and stat-bound at build time, but content is verified only after parent reservation.",
        "A metadata build does not establish a fresh CURRENT-view semantic join or scientific qualification.",
    ]
    value["sha256"] = canonical_sha(value)
    result = _write_new(target, value)
    return {"status": "READY_V8_FRESH_TYPED_RESULT_PARENT_GUARD", "schema": value["schema"],
            "request": str(result), "sha256": value["sha256"],
            "static_role_count": len(filtered), "fresh_result_bytes": fresh["result"]["bytes"],
            "result_content_hash_during_build": False,
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
    build.add_argument("--fresh-typed-request", type=Path, required=True)
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
                fresh_typed_request=args.fresh_typed_request,
                output=args.output, parent_attempt_id=args.parent_attempt_id,
                supervisor_output_root=args.supervisor_output_root,
                home_receipt=args.home_receipt, max_wall_seconds=args.max_wall_seconds,
                trace_path=args.trace_path, allow_missing_parent=args.allow_missing_parent)
        elif args.command == "preflight":
            _validate_request(args.request)
            value = {"schema": "ds02.stage2.f2-typed-only-evaluator-parent-report.v8-fresh-result",
                     "status": "READY_FOR_PARENT_IO_SLOT", "metadata_only": True,
                     "ledger_mutated": False, "qualification": dict(UNKNOWN)}
        else:
            value = run(args.request, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid)
    except (TypedParentV8FreshResultError, V6.TypedParentV6CurrentError,
            V6.V4.TypedParentV3CurrentError, OSError, ValueError,
            TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator parent V8 fresh-result: {error}")
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 1 if str(value.get("status", "")).startswith("FAILED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
