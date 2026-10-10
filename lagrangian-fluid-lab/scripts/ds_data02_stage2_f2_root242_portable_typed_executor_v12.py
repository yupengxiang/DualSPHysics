#!/usr/bin/env python3
"""ROOT242 V12 output-slot successor for the portable typed executor.

The consumed V11 executor correctly rejects an old absolute output directory,
but its V2 overlay did not know the producer-specific
``/v12_forward/output_root_rebind_v14/path`` marker.  V12 adds one narrow
mapping: that marker is an attempt-owned ``products`` slot under the fresh
parent root.  The old value remains a provenance value in the sealed request
and is never opened.

V11, V2, V5, the copied worker, and the parent ledger protocol remain
immutable.  This wrapper only patches the V2 directory mapping while V11
constructs its overlay, then restores it in ``finally``.  It is intended to
be launched by the outer parent after reservation; this process does not
reserve, charge, or mutate a ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V11_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v11.py"
REQUEST_SCHEMA = "ds02.request.v1"
OUTPUT_SLOT_SCHEMA = "ds02.stage2.f2-root242-v12-output-slot.v1"
SOURCE_BINDING_SCHEMA = "ds02.stage2.f2-root242-v12-output-slot-source-binding.v1"
REPORT_SCHEMA = "ds02.stage2.f2-root242-portable-typed-executor-report.v12"
MAX_METADATA_BYTES = 32 * 1024 * 1024


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V11 = _load(V11_SCRIPT, "ds02_root242_v11_executor_for_v12")
V2 = V11.V2
_ORIGINAL_DIRECTORY_REBIND = V2._directory_rebind


class Root242V12ExecutorError(RuntimeError):
    pass


def _canonical(value: Mapping[str, Any]) -> str:
    return V11._canonical(value)


def _json(path: Path, role: str) -> dict[str, Any]:
    return V11._json(path, role)


def _absolute(value: Any, role: str) -> Path:
    return V11._absolute(value, role)


def _hash(path: Path, *, maximum: int = 4 * 1024 * 1024 * 1024,
          allow_symlink: bool = False) -> tuple[str, int]:
    return V11._hash(path, maximum=maximum, allow_symlink=allow_symlink)


def _directory_rebind_v12(parts: tuple[str, ...], root: Path) -> Path | None:
    """Map only the producer's output-slot marker, then use immutable V2."""
    lowered = {str(item).lower() for item in parts}
    if "output_root_rebind_v14" in lowered:
        return root / "products"
    return _ORIGINAL_DIRECTORY_REBIND(parts, root)


def _find_output_marker(value: Any, parts: tuple[str, ...] = ()) -> tuple[str, str] | None:
    if isinstance(value, Mapping):
        marker = value.get("output_root_rebind_v14")
        if isinstance(marker, Mapping) and isinstance(marker.get("path"), str):
            pointer = "".join("/" + part.replace("~", "~0").replace("/", "~1")
                               for part in parts + ("output_root_rebind_v14", "path"))
            return pointer, marker["path"]
        for key, child in value.items():
            found = _find_output_marker(child, parts + (str(key),))
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_output_marker(child, parts + (str(index),))
            if found is not None:
                return found
    return None


def _source_inner(contract: Mapping[str, Any]) -> tuple[str, Path]:
    binding = contract.get("root242_source_binding")
    roles = binding.get("roles") if isinstance(binding, Mapping) else None
    if not isinstance(roles, list):
        raise Root242V12ExecutorError("V11 role table is missing")
    for role in roles:
        if isinstance(role, Mapping) and role.get("logical_role") == "root200_inner_request":
            source = role.get("source_path_provenance")
            if isinstance(source, str) and source.startswith("/"):
                return source, Path(source)
    raise Root242V12ExecutorError("root200 inner request role is missing")


def _validate_v12_binding(request: Mapping[str, Any], contract: Mapping[str, Any],
                          request_path: Path, root: Path) -> dict[str, Any]:
    slot = request.get("root242_v12_output_slot")
    if not isinstance(slot, Mapping) or slot.get("schema") != OUTPUT_SLOT_SCHEMA:
        raise Root242V12ExecutorError("V12 output-slot binding is missing")
    if slot.get("target_relative_path") != "products":
        raise Root242V12ExecutorError("V12 output slot is not the products directory")
    if slot.get("replacement_pointer") != "/v12_forward/output_root_rebind_v14/path":
        raise Root242V12ExecutorError("V12 output marker pointer differs")
    if slot.get("original_path_fallback") != "REJECT" or slot.get("attempt_owned") is not True:
        raise Root242V12ExecutorError("V12 output slot permits fallback or is not attempt-owned")
    if slot.get("proof_output_only") is not True:
        raise Root242V12ExecutorError("V12 output slot is not proof-output-only")
    old_source = slot.get("old_source_path")
    if not isinstance(old_source, str) or not old_source.startswith("/"):
        raise Root242V12ExecutorError("V12 old output provenance is missing")
    source_binding = request.get("root242_v12_source_binding")
    if (not isinstance(source_binding, Mapping)
            or source_binding.get("schema") != SOURCE_BINDING_SCHEMA):
        raise Root242V12ExecutorError("V12 source binding is missing")
    source_path = source_binding.get("path")
    if source_path != str(SCRIPT):
        raise Root242V12ExecutorError("V12 source binding does not identify this launcher")
    source_sha = source_binding.get("sha256")
    actual_sha, _ = _hash(SCRIPT, maximum=MAX_METADATA_BYTES)
    if source_sha != actual_sha:
        raise Root242V12ExecutorError("V12 launcher source SHA differs")
    expected_root = _absolute(
        request.get("storage_scope", {}).get("external_filesystem"),
        "V12 external filesystem",
    )
    if root != expected_root:
        raise Root242V12ExecutorError("V12 output root differs from parent-bound filesystem")
    if root == Path(old_source).absolute() or str(root).startswith(str(Path(old_source).absolute()) + os.sep):
        raise Root242V12ExecutorError("V12 fresh output root reuses old output provenance")
    inner_source_name, inner_source = _source_inner(contract)
    inner = _json(inner_source, "V12 source inner request")
    marker = _find_output_marker(inner)
    if marker is None:
        raise Root242V12ExecutorError("V12 source inner request lacks output-slot marker")
    pointer, actual_old = marker
    if pointer != str(slot.get("replacement_pointer")) or actual_old != old_source:
        raise Root242V12ExecutorError("V12 output-slot provenance does not match source inner request")
    return {
        "slot_schema": OUTPUT_SLOT_SCHEMA,
        "replacement_pointer": pointer,
        "old_source_path": old_source,
        "old_path_role": "HISTORICAL_PROVENANCE_ONLY",
        "target_relative_path": "products",
        "launcher_source_path": str(SCRIPT),
        "launcher_source_sha256": actual_sha,
        "inner_source_path": inner_source_name,
        "output_root": str(root),
    }


def _write_slot_report(root: Path, *, base_report: Mapping[str, Any],
                       request_path: Path, slot: Mapping[str, Any]) -> Path:
    report_path = root / "reports" / "root242-v12-output-slot-report.json"
    if report_path.exists() or report_path.is_symlink():
        raise Root242V12ExecutorError("refusing existing V12 output-slot report")
    report = {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETE_ROOT242_V12_OUTPUT_SLOT_REBOUND",
        "request": {"path": str(request_path), "file_sha256": _hash(request_path)[0]},
        "base_v11_report": {
            "target_relative_path": "reports/root242-v11-executor-report.json",
            "sha256": _hash(root / "reports/root242-v11-executor-report.json")[0],
            "status": base_report.get("status"),
        },
        "output_slot": dict(slot),
        "execution": {
            "output_marker_rebound": True,
            "original_path_fallback": "REJECT",
            "attempt_owned_output": True,
            "payload_read": False,
            "ledger_mutated": False,
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }
    report["sha256"] = _canonical(report)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True,
                                      ensure_ascii=True, allow_nan=False) + "\n",
                           encoding="utf-8")
    return report_path


def run(*, request: Path | str, output_root: Path | str, parent_pid: int,
        max_wall_seconds: float) -> dict[str, Any]:
    request_path = Path(request).expanduser().absolute()
    root = Path(output_root).expanduser().absolute()
    # _outer validates the immutable V11 closure before any output namespace
    # is created.  The output-slot check then verifies the producer-specific
    # nested path against the same source bytes.
    outer, contract, _contract_path = V11._outer(request_path)
    slot = _validate_v12_binding(outer, contract, request_path, root)
    if root.is_symlink() or (root.exists() and any(root.iterdir())):
        raise Root242V12ExecutorError("refusing non-empty or symlink V12 fresh root")
    old = V2._directory_rebind
    V2._directory_rebind = _directory_rebind_v12
    try:
        base = V11.run(request=request_path, output_root=root, parent_pid=parent_pid,
                       max_wall_seconds=max_wall_seconds)
    finally:
        V2._directory_rebind = old
    slot_report = _write_slot_report(root, base_report=base,
                                     request_path=request_path, slot=slot)
    return {
        "schema": REPORT_SCHEMA,
        "status": "COMPLETE_ROOT242_V12_OUTPUT_SLOT_REBOUND",
        "base_v11": base,
        "output_slot_report": {
            "path": str(slot_report), "file_sha256": _hash(slot_report)[0],
            "slot": slot,
        },
        "source_fallback": "REJECT",
        "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }


def validate_request(request: Path | str, contract: Path | str) -> dict[str, Any]:
    # Keep V11's complete role/path validation as the base admission check.
    value = V11.validate_request(request, contract)
    request_path = Path(request).expanduser().absolute()
    contract_path = Path(contract).expanduser().absolute()
    outer = _json(request_path, "V12 request")
    inner = _json(contract_path, "V12 contract")
    root = _absolute(outer.get("storage_scope", {}).get("external_filesystem"),
                     "V12 external filesystem")
    slot = _validate_v12_binding(outer, inner, request_path, root)
    return {
        "schema": SOURCE_BINDING_SCHEMA,
        "status": "ROOT242_V12_METADATA_VALIDATED_READY_FOR_PARENT",
        "base": value,
        "output_slot": slot,
        "payload_read": False,
        "ledger_mutated": False,
        "launch_performed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--contract", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output-root", type=Path, required=True)
    run_parser.add_argument("--parent-pid", type=int, required=True)
    run_parser.add_argument("--max-wall-seconds", type=float, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            value = validate_request(args.request, args.contract)
        else:
            value = run(request=args.request, output_root=args.output_root,
                        parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root242V12ExecutorError, V11.Root242V11ExecutorError,
            V11.V9.V1.PortableRebindError, V2.PortableRebindV2Error,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT242 V12 executor: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
