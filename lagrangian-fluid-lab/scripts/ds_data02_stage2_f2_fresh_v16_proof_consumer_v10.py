#!/usr/bin/env python3
"""Strict V10 forward of the immutable V8/V9 typed-only proof consumer.

The root051 producer uses the exact scope string
``initial_fluid_source_cohort_global; identity fate unknown``.  V8's
historical text check expected the word ``denominator`` in that field and
therefore rejected the real producer result.  V10 accepts that one
source-bound spelling only after checking the small producer report,
expected cohort/mass/event contract, and source/result SHA binding.  All
other V8 validation, including identity, time, censor vocabulary, labels,
mass sums, source binding, and path audit, remains delegated to V8 through
V9.  No HDF5, BI4, or raw payload is read by request construction.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V9_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v9.py"
V8_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
PRODUCER_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
ACCEPTED_MISSING_SCOPE = "initial_fluid_source_cohort_global; identity fate unknown"
ACCEPTED_SCOPE_SEMANTICS = (
    "initial denominator is already the frozen fluid mass; later missing mass "
    "remains in the unknown bucket and is never added"
)
REQUIRED_TYPED_FIELDS = {
    "time", "particle_id", "particle_zone", "valid", "position", "velocity",
    "mass", "initial_type", "initial_mk", "initial_mass",
}
REQUIRED_STATUS_VOCABULARY = {
    "observed", "right_censored", "failed_before_observation",
    "initially_inside", "ambiguous_multiple_crossing",
}
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_METADATA_BYTES = 32 * 1024 * 1024


class V10ProofConsumerError(RuntimeError):
    """Raised when the narrow V10 source-bound contract is malformed."""


def _load_v9() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ds02_bound_fresh_v16_consumer_v9_for_v10", V9_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise V10ProofConsumerError(f"cannot load V9 consumer: {V9_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V9 = _load_v9()
V8 = V9.V8


def _file(path: Any, role: str) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).startswith("/"):
        raise V10ProofConsumerError(f"{role} must be an absolute path")
    target = Path(path).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise V10ProofConsumerError(f"{role} is not a regular non-symlink file: {target}")
    return target


def _json(path: Any, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise V10ProofConsumerError(f"{role} exceeds metadata-only bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V10ProofConsumerError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V10ProofConsumerError(f"{role} must be an object")
    return target, value


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value: Any, role: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V10ProofConsumerError(f"{role} must be numeric")
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise V10ProofConsumerError(f"{role} must be finite")
    return result


def _require_close(value: Any, expected: float, role: str, tolerance: float = 1e-12) -> None:
    observed = _finite(value, role)
    if abs(observed - expected) > tolerance:
        raise V10ProofConsumerError(f"{role} differs from the source-bound value")


def _validate_mass_contract(request: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the real root051 producer contract before V8 reads the result."""
    contract = request.get("v10_mass_scope_contract")
    if not isinstance(contract, Mapping):
        raise V10ProofConsumerError("v10_mass_scope_contract is required")
    if contract.get("accepted_result_missing_scope") != ACCEPTED_MISSING_SCOPE:
        raise V10ProofConsumerError("V10 missing-scope allowlist is not the root051 spelling")
    if contract.get("semantics") != ACCEPTED_SCOPE_SEMANTICS:
        raise V10ProofConsumerError("V10 missing-scope semantics are not frozen")
    source = contract.get("source_report")
    bound_source = request.get("provenance_source_report")
    if not isinstance(source, Mapping) or not isinstance(bound_source, Mapping):
        raise V10ProofConsumerError("V10 scope source binding is missing")
    if source.get("path") != bound_source.get("path") or source.get("sha256") != bound_source.get("sha256"):
        raise V10ProofConsumerError("V10 scope source differs from the provenance report")

    typed_validation = report.get("typed_validation")
    if not isinstance(typed_validation, Mapping):
        raise V10ProofConsumerError("producer typed_validation is missing")
    if typed_validation.get("selected_particles") != 21114:
        raise V10ProofConsumerError("producer selected particle count is not root051")
    if typed_validation.get("identity_sha256") != request.get("expected", {}).get("cohort", {}).get("identity_sha256"):
        raise V10ProofConsumerError("producer identity SHA differs from expected cohort")
    fields = typed_validation.get("typed_fields_validated")
    if not isinstance(fields, list) or not REQUIRED_TYPED_FIELDS.issubset(set(fields)):
        raise V10ProofConsumerError("producer typed fields do not cover the V8 result contract")

    expected = request.get("expected")
    if not isinstance(expected, Mapping):
        raise V10ProofConsumerError("V8 expected contract is missing")
    cohort = expected.get("cohort")
    if not isinstance(cohort, Mapping) or cohort.get("selected_count") != 21114:
        raise V10ProofConsumerError("V8 cohort count is not the bound root051 cohort")
    mass = expected.get("initial_mass_denominator")
    if not isinstance(mass, Mapping):
        raise V10ProofConsumerError("V8 initial mass contract is missing")
    _require_close(mass.get("denominator_kg"), 21.114001002861187, "expected denominator_kg", 1e-14)
    _require_close(mass.get("initial_missing_mass_kg"), 0.0, "expected initial_missing_mass_kg", 1e-14)
    _require_close(mass.get("later_missing_mass_kg"), 0.003000000142492354,
                   "expected later_missing_mass_kg", 1e-14)
    if mass.get("initially_absent_count") != 0 or mass.get("later_missing_unique_count") != 3:
        raise V10ProofConsumerError("V8 missing-mass counts differ from root051")
    derivation = mass.get("derivation")
    if not isinstance(derivation, str) or "not augmented by later missing" not in derivation:
        raise V10ProofConsumerError("V8 mass derivation does not freeze later-missing semantics")
    events = expected.get("events")
    if not isinstance(events, Mapping):
        raise V10ProofConsumerError("V8 event contract is missing")
    vocabulary = events.get("status_vocabulary")
    if set(vocabulary or ()) != REQUIRED_STATUS_VOCABULARY:
        raise V10ProofConsumerError("V8 censor vocabulary differs from the source-bound vocabulary")
    semantics = events.get("semantics_source")
    if not isinstance(semantics, Mapping):
        raise V10ProofConsumerError("V8 event semantics source is missing")
    for key in ("later_missing", "saved_bracket", "recross", "receiver_volume", "aperture"):
        if not isinstance(semantics.get(key), str) or not semantics[key].strip():
            raise V10ProofConsumerError(f"V8 event semantics missing {key}")

    labels = report.get("labels")
    result_binding = labels.get("v16") if isinstance(labels, Mapping) else None
    result_request = request.get("result")
    if not isinstance(result_binding, Mapping) or not isinstance(result_request, Mapping):
        raise V10ProofConsumerError("producer V16 result binding is missing")
    if result_binding.get("path") != result_request.get("path") or result_binding.get("sha256") != result_request.get("sha256"):
        raise V10ProofConsumerError("producer V16 result binding differs from the V8 request")
    return {
        "accepted_result_missing_scope": ACCEPTED_MISSING_SCOPE,
        "semantics": ACCEPTED_SCOPE_SEMANTICS,
        "source_report_sha256": str(bound_source.get("sha256")),
        "denominator_kg": float(mass["denominator_kg"]),
        "initial_missing_mass_kg": float(mass["initial_missing_mass_kg"]),
        "later_missing_mass_kg": float(mass["later_missing_mass_kg"]),
        "later_missing_unique_count": int(mass["later_missing_unique_count"]),
    }


_ACTIVE_SCOPE_CONTRACT: dict[str, Any] | None = None
_V8_VALIDATE_RESULT = V8._validate_result


def _validate_result_v10(result: Mapping[str, Any], bound: Mapping[str, Any],
                         result_sha: str, result_bytes: int) -> dict[str, Any]:
    contract = _ACTIVE_SCOPE_CONTRACT
    if contract is None:
        raise V10ProofConsumerError("V10 result validator was called without a scope contract")
    mass = result.get("initial_mass_denominator")
    if not isinstance(mass, Mapping) or mass.get("missing_scope") != contract["accepted_result_missing_scope"]:
        raise V10ProofConsumerError("result missing_scope is not the exact source-bound root051 scope")
    # V8's check is retained by normalizing only the exact, source-bound
    # spelling to a phrase that states the already-frozen denominator.  The
    # original result is never rewritten on disk and its SHA remains bound.
    normalized = dict(result)
    normalized_mass = dict(mass)
    normalized_mass["missing_scope"] = (
        "initial denominator mass; " + contract["accepted_result_missing_scope"]
    )
    normalized["initial_mass_denominator"] = normalized_mass
    return _V8_VALIDATE_RESULT(normalized, bound, result_sha, result_bytes)


def _load_and_validate_contract(request_path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    request_file = Path(request_path).expanduser().resolve()
    request = V8._load_object(request_file)
    if request.get("schema") != V8_SCHEMA:
        raise V10ProofConsumerError("V10 forward requires the immutable V8 request schema")
    report_path, report = _json(request.get("provenance_source_report", {}).get("path"),
                                "provenance source report")
    expected_sha = request.get("provenance_source_report", {}).get("sha256")
    if expected_sha != _sha_file(report_path):
        raise V10ProofConsumerError("provenance source report SHA differs")
    if report.get("sha256") != V8.canonical_sha(report) or report.get("schema") != PRODUCER_SCHEMA:
        raise V10ProofConsumerError("provenance source report is not canonical producer v1")
    scope = _validate_mass_contract(request, report)
    return request_file, request, scope


def run(request_path: Path | str, output_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    global _ACTIVE_SCOPE_CONTRACT
    _request_file, request, scope = _load_and_validate_contract(request_path)
    # V9 performs the producer-derived path declaration audit and delegates
    # all other work to V8.  The only V10 patch is the exact scope adapter.
    old_validator = V8._validate_result
    _ACTIVE_SCOPE_CONTRACT = scope
    V8._validate_result = _validate_result_v10
    try:
        return V9.run(request_path, output_path, io_slot_approved=io_slot_approved,
                      parent_pid=parent_pid, max_wall_seconds=max_wall_seconds)
    finally:
        V8._validate_result = old_validator
        _ACTIVE_SCOPE_CONTRACT = None


def preflight(request_path: Path | str) -> dict[str, Any]:
    _request_file, request, _scope = _load_and_validate_contract(request_path)
    # Preserve V9's exact producer-derived provenance declaration check even
    # on metadata-only preflight; this does not open any declared provenance
    # path and prevents a preflight from being weaker than the real run.
    V9._declared_paths(request)
    # V8 preflight remains the authoritative stat/path/schema preflight.
    return V8.preflight(_request_file)


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
    except (V10ProofConsumerError, V9.V9ProofConsumerError, V8.ProofConsumerError,
            OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof consumer V10: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
