#!/usr/bin/env python3
"""V11 forward of the V10 fresh proof consumer for V40 relocated CURRENT.

V10 already performs the complete F2-S1 mass, identity, time, censoring,
receiver, flux and residence checks.  Its immutable V8 source-binding helper
predates the V40 relocation scope and only allowed ``EXACT_CURRENT_SOURCE_BOUND``.
This additive wrapper accepts the one explicit relocated status
``RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND`` when it is present on both
the expected contract and the result.  The original exact CURRENT df7e digest
must remain in the request's provenance; the actionable digest is the newly
generated V40 runtime view.  All other V10/V9/V8 checks remain unchanged.

The wrapper reads only JSON and the new V16 result during an approved run.
It never opens HDF5, BI4 or raw frames, invokes no model/CFD, and keeps
QI/QN/QE UNKNOWN.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V10_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v10.py"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
FORWARD_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-v11-forward.v1"
RELOCATED_STATUS = "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND"


class V11ProofConsumerError(RuntimeError):
    """Raised when a relocated V10 proof request is not source-bound."""


def _load_v10() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_fresh_v16_consumer_v10_for_v11", V10_SCRIPT)
    if spec is None or spec.loader is None:
        raise V11ProofConsumerError(f"cannot load V10 consumer: {V10_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V10 = _load_v10()
V9 = V10.V9
V8 = V10.V8
_V8_SOURCE_BINDING = V8._validate_source_binding


def _relocated_source_binding(result: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    actual_status = result.get("binding_status")
    expected_status = expected.get("binding_status")
    if actual_status != RELOCATED_STATUS or expected_status != RELOCATED_STATUS:
        return _V8_SOURCE_BINDING(result, expected)
    # Reuse the immutable V8 comparison and role-set checks while normalizing
    # only the status token that the old helper's allow-list predates.  The
    # returned summary restores the explicit relocated scope; no source digest
    # or path is changed.
    actual_copy = dict(result)
    expected_copy = dict(expected)
    actual_copy["binding_status"] = "EXACT_CURRENT_SOURCE_BOUND"
    expected_copy["binding_status"] = "EXACT_CURRENT_SOURCE_BOUND"
    summary = _V8_SOURCE_BINDING(actual_copy, expected_copy)
    summary["binding_status"] = RELOCATED_STATUS
    summary["relocation_scope"] = "RELOCATED_RUNTIME_CURRENT_VIEW_ONLY"
    return summary


def _validate_request_marker(request_path: Path | str) -> None:
    request = V8._load_object(Path(request_path).expanduser().resolve())
    if request.get("schema") != REQUEST_SCHEMA:
        raise V11ProofConsumerError("V11 requires the immutable V8 request schema")
    marker = request.get("v11_forward")
    if not isinstance(marker, Mapping) or marker.get("schema") != FORWARD_SCHEMA:
        raise V11ProofConsumerError("V11 relocated-source forward marker is missing")
    expected = request.get("expected")
    source = expected.get("source_binding") if isinstance(expected, Mapping) else None
    if not isinstance(source, Mapping) or source.get("binding_status") != RELOCATED_STATUS:
        raise V11ProofConsumerError("V11 expected source scope is not relocated-runtime-only")
    provenance = marker.get("current_catalog_provenance")
    if not isinstance(provenance, Mapping):
        raise V11ProofConsumerError("V11 CURRENT provenance is missing")
    if provenance.get("original_current_catalog_sha256") != marker.get("actual_current_catalog_sha256"):
        raise V11ProofConsumerError("V11 CURRENT provenance identity is inconsistent")
    if provenance.get("relocated_view_sha256") != source.get("current_catalog_sha256"):
        raise V11ProofConsumerError("V11 relocated view digest is inconsistent")


def run(request_path: Path | str, output_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    _validate_request_marker(request_path)
    old_binding = V8._validate_source_binding
    V8._validate_source_binding = _relocated_source_binding
    try:
        return V10.run(request_path, output_path, io_slot_approved=io_slot_approved,
                       parent_pid=parent_pid, max_wall_seconds=max_wall_seconds)
    finally:
        V8._validate_source_binding = old_binding


def preflight(request_path: Path | str) -> dict[str, Any]:
    _validate_request_marker(request_path)
    old_binding = V8._validate_source_binding
    V8._validate_source_binding = _relocated_source_binding
    try:
        return V10.preflight(request_path)
    finally:
        V8._validate_source_binding = old_binding


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("preflight")
    prep.add_argument("--request", type=Path, required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--io-slot-approved", action="store_true")
    run_parser.add_argument("--parent-pid", type=int)
    run_parser.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            value = preflight(args.request)
        else:
            value = run(args.request, args.output, io_slot_approved=args.io_slot_approved,
                        parent_pid=args.parent_pid, max_wall_seconds=args.max_wall_seconds)
    except (V11ProofConsumerError, V10.V10ProofConsumerError, V9.V9ProofConsumerError,
            V8.ProofConsumerError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof consumer V11: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
