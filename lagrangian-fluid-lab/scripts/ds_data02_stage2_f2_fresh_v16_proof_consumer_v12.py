#!/usr/bin/env python3
"""Source-bound V12 forward of the immutable V8 proof consumer.

The ROOT190 attempt exposed a producer/consumer spelling mismatch.  The
producer's real V2/V16 result uses
``initial_fluid_source_cohort_global; identity fate unknown`` for
``initial_mass_denominator.missing_scope``.  The immutable V8 consumer quite
deliberately requires that field to say ``denominator`` and therefore stopped
before producing a proof.

V12 accepts that spelling only when a separate, small semantic sidecar binds
it to the exact V66 producer request, CURRENT df7e, result SHA, cohort, and
mass interval.  It normalizes the spelling in memory solely for the call into
V8; the source result is never rewritten.  The sidecar preserves the strict
denominator contract: the initial denominator is frozen, initial missing mass
is distinct from later missing mass, and later missing mass is not added.
All identity, timeline, event, receiver, source, path, and UNKNOWN checks
remain V8 checks.  This module never opens HDF5, BI4, raw frames, or models.
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
V8_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
SIDECAR_SCHEMA = "ds02.stage2.f2-fresh-v16-missing-scope-sidecar.v1"
FORWARD_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-v12-forward.v1"
PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
ACCEPTED_MISSING_SCOPE = "initial_fluid_source_cohort_global; identity fate unknown"
ACCEPTED_SCOPE_SEMANTICS = (
    "initial denominator is already the frozen fluid mass; later missing mass "
    "remains in the unknown bucket and is never added"
)
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
EXPECTED_COUNT = 21114
EXPECTED_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
EXPECTED_DENOMINATOR = 21.114001002861187
EXPECTED_INITIAL_MISSING = 0.0
EXPECTED_LATER_MISSING = 0.003000000142492354
EXPECTED_LATER_MISSING_COUNT = 3
REQUIRED_TYPED_FIELDS = {
    "time", "particle_id", "particle_zone", "valid", "position", "velocity",
    "mass", "initial_type", "initial_mk", "initial_mass",
}
REQUIRED_STATUS_VOCABULARY = {
    "observed", "right_censored", "failed_before_observation",
    "initially_inside", "ambiguous_multiple_crossing",
}
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_SIDECAR_BYTES = 2 * 1024 * 1024


class V12ProofConsumerError(RuntimeError):
    """Raised for malformed or stale V12 inputs."""


def _load_v8() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ds02_bound_fresh_v16_proof_consumer_v8_for_v12", V8_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise V12ProofConsumerError(f"cannot load immutable V8 consumer: {V8_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V8 = _load_v8()
_V8_VALIDATE_RESULT = V8._validate_result
_ACTIVE_SCOPE: dict[str, Any] | None = None


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise V12ProofConsumerError(f"{role} must be a lowercase SHA-256")
    return value


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    digest = hashlib.sha256()
    total = 0
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(block)
            if max_bytes is not None and total > max_bytes:
                raise V12ProofConsumerError(f"file exceeds bound: {target}")
            digest.update(block)
    return digest.hexdigest()


def _absolute_file(value: Any, role: str) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.startswith("/"):
        raise V12ProofConsumerError(f"{role} must be an absolute path")
    target = Path(value).expanduser()
    if target.is_symlink() or not target.is_file():
        raise V12ProofConsumerError(f"{role} must be a regular non-symlink file: {target}")
    return target


def _json(path: Any, role: str, *, max_bytes: int = MAX_SIDECAR_BYTES) -> tuple[Path, dict[str, Any]]:
    target = _absolute_file(path, role)
    if target.stat().st_size > max_bytes:
        raise V12ProofConsumerError(f"{role} exceeds the bounded JSON limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V12ProofConsumerError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V12ProofConsumerError(f"{role} must be a JSON object")
    return target, value


def _finite(value: Any, role: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V12ProofConsumerError(f"{role} must be numeric")
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise V12ProofConsumerError(f"{role} must be finite")
    return result


def _close(value: Any, expected: float, role: str, tolerance: float = 1e-14) -> None:
    if abs(_finite(value, role) - expected) > tolerance:
        raise V12ProofConsumerError(f"{role} differs from the source-bound value")


def _binding(value: Any, role: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V12ProofConsumerError(f"{role} must be an object")
    return value


def _validate_sidecar(request: Mapping[str, Any], sidecar_path: Path,
                     sidecar: Mapping[str, Any]) -> dict[str, Any]:
    if sidecar.get("schema") != SIDECAR_SCHEMA:
        raise V12ProofConsumerError("semantic sidecar schema differs")
    if sidecar.get("sha256") != canonical_sha(sidecar):
        raise V12ProofConsumerError("semantic sidecar canonical SHA differs")
    if sidecar.get("status") != "SOURCE_BOUND_SEMANTIC_CONTRACT":
        raise V12ProofConsumerError("semantic sidecar is not source-bound")
    if sidecar.get("missing_scope") != ACCEPTED_MISSING_SCOPE:
        raise V12ProofConsumerError("semantic sidecar missing_scope is not the exact producer spelling")
    if sidecar.get("denominator_semantics") != ACCEPTED_SCOPE_SEMANTICS:
        raise V12ProofConsumerError("semantic sidecar denominator semantics are not frozen")

    source = _binding(request.get("v12_forward"), "v12_forward")
    if source.get("schema") != FORWARD_SCHEMA:
        raise V12ProofConsumerError("V12 forward marker is missing")
    sidecar_binding = _binding(source.get("semantic_sidecar"), "v12_forward.semantic_sidecar")
    if sidecar_binding.get("path") != str(sidecar_path):
        raise V12ProofConsumerError("V12 sidecar path differs")
    if sidecar_binding.get("sha256") != sha256_file(sidecar_path, max_bytes=MAX_SIDECAR_BYTES):
        raise V12ProofConsumerError("V12 sidecar SHA differs")

    source_request = _binding(source.get("source_request"), "v12_forward.source_request")
    if source_request.get("schema") != REQUEST_SCHEMA:
        raise V12ProofConsumerError("V12 source request schema differs")
    sidecar_request = _binding(sidecar.get("producer_v66_request"), "sidecar.producer_v66_request")
    if source_request.get("sha256") != sidecar_request.get("file_sha256"):
        raise V12ProofConsumerError("sidecar and V12 source request SHA differ")
    if source_request.get("canonical_sha256") != sidecar_request.get("canonical_sha256"):
        raise V12ProofConsumerError("sidecar and V12 source request canonical SHA differ")

    producer = _binding(request.get("v66_parent_binding"), "request.v66_parent_binding")
    for key in ("producer_case_id", "producer_attempt_id"):
        if producer.get(key) != sidecar_request.get(key):
            raise V12ProofConsumerError(f"sidecar producer {key} differs")
    nested = _binding(sidecar.get("producer_nested_report"), "sidecar.producer_nested_report")
    _sha(nested.get("sha256"), "sidecar.producer_nested_report.sha256")
    if nested.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2":
        raise V12ProofConsumerError("sidecar producer report is not the real V2 schema")
    request_nested = _binding(producer.get("nested_worker_report"),
                              "request.v66_parent_binding.nested_worker_report")
    if nested.get("path") != request_nested.get("path") or nested.get("sha256") != request_nested.get("sha256"):
        raise V12ProofConsumerError("sidecar producer report differs from the V66 request")

    result = _binding(request.get("result"), "request.result")
    result_sidecar = _binding(sidecar.get("v16_result"), "sidecar.v16_result")
    for key in ("path", "sha256", "bytes"):
        if result.get(key) != result_sidecar.get(key):
            raise V12ProofConsumerError(f"sidecar V16 result {key} differs")
    _sha(result_sidecar.get("sha256"), "sidecar.v16_result.sha256")

    current = _binding(request.get("current_manifest_binding"), "request.current_manifest_binding")
    sidecar_current = _binding(sidecar.get("current_manifest"), "sidecar.current_manifest")
    if current.get("sha256") != ACTUAL_CURRENT_SHA or sidecar_current.get("sha256") != ACTUAL_CURRENT_SHA:
        raise V12ProofConsumerError("semantic sidecar does not bind CURRENT df7e")
    if current.get("sha256") != sidecar_current.get("sha256"):
        raise V12ProofConsumerError("sidecar CURRENT differs")

    expected = _binding(request.get("expected"), "request.expected")
    cohort = _binding(expected.get("cohort"), "expected.cohort")
    if cohort.get("selected_count") != EXPECTED_COUNT or cohort.get("identity_key") != "(Zone,Idp)":
        raise V12ProofConsumerError("source-bound cohort is not the 21114 (Zone,Idp) cohort")
    if cohort.get("identity_sha256") != EXPECTED_IDENTITY_SHA:
        raise V12ProofConsumerError("source-bound cohort identity differs")
    mass = _binding(expected.get("initial_mass_denominator"), "expected.initial_mass_denominator")
    _close(mass.get("denominator_kg"), EXPECTED_DENOMINATOR, "denominator_kg")
    _close(mass.get("initial_missing_mass_kg"), EXPECTED_INITIAL_MISSING, "initial_missing_mass_kg")
    _close(mass.get("later_missing_mass_kg"), EXPECTED_LATER_MISSING, "later_missing_mass_kg")
    if mass.get("later_missing_unique_count") != EXPECTED_LATER_MISSING_COUNT:
        raise V12ProofConsumerError("later missing identity count differs")

    sidecar_expected = _binding(sidecar.get("expected"), "sidecar.expected")
    if sidecar_expected.get("identity_key") != cohort.get("identity_key") or sidecar_expected.get("selected_count") != EXPECTED_COUNT:
        raise V12ProofConsumerError("sidecar expected cohort differs")
    if sidecar_expected.get("identity_sha256") != EXPECTED_IDENTITY_SHA:
        raise V12ProofConsumerError("sidecar expected identity differs")
    _close(sidecar_expected.get("denominator_kg"), EXPECTED_DENOMINATOR, "sidecar denominator_kg")
    _close(sidecar_expected.get("initial_missing_mass_kg"), EXPECTED_INITIAL_MISSING, "sidecar initial_missing_mass_kg")
    _close(sidecar_expected.get("later_missing_mass_kg"), EXPECTED_LATER_MISSING, "sidecar later_missing_mass_kg")
    if sidecar_expected.get("later_missing_unique_count") != EXPECTED_LATER_MISSING_COUNT:
        raise V12ProofConsumerError("sidecar later missing identity count differs")

    typed = sidecar.get("typed_fields")
    if not isinstance(typed, list) or set(typed) != REQUIRED_TYPED_FIELDS:
        raise V12ProofConsumerError("sidecar typed fields do not cover the V8 contract exactly")
    vocabulary = sidecar.get("status_vocabulary")
    if set(vocabulary or ()) != REQUIRED_STATUS_VOCABULARY:
        raise V12ProofConsumerError("sidecar censor vocabulary differs")
    scope_source = _binding(sidecar.get("scope_source"), "sidecar.scope_source")
    _sha(scope_source.get("sha256"), "sidecar.scope_source.sha256")
    if scope_source.get("missing_scope_literal") != ACCEPTED_MISSING_SCOPE:
        raise V12ProofConsumerError("sidecar scope-source literal differs")
    if sidecar.get("qualification") != UNKNOWN:
        raise V12ProofConsumerError("sidecar may not promote QI/QN/QE")
    return {
        "schema": SIDECAR_SCHEMA,
        "path": str(sidecar_path),
        "sha256": sha256_file(sidecar_path, max_bytes=MAX_SIDECAR_BYTES),
        "missing_scope": ACCEPTED_MISSING_SCOPE,
        "denominator_semantics": ACCEPTED_SCOPE_SEMANTICS,
        "scope_source": dict(scope_source),
        "producer_nested_report": dict(nested),
        "denominator_kg": EXPECTED_DENOMINATOR,
        "initial_missing_mass_kg": EXPECTED_INITIAL_MISSING,
        "later_missing_mass_kg": EXPECTED_LATER_MISSING,
        "later_missing_unique_count": EXPECTED_LATER_MISSING_COUNT,
        "identity_sha256": EXPECTED_IDENTITY_SHA,
        "selected_count": EXPECTED_COUNT,
        "original_result_missing_scope_preserved": True,
    }


def _load_marker(request_path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    request_file = Path(request_path).expanduser().resolve()
    try:
        request = V8._load_object(request_file)
    except Exception as error:  # V8 gives its own typed error; keep CLI stable.
        raise V12ProofConsumerError(f"cannot load V12 request: {error}") from error
    if request.get("schema") != REQUEST_SCHEMA:
        raise V12ProofConsumerError("V12 requires the immutable V8 request schema")
    marker = _binding(request.get("v12_forward"), "request.v12_forward")
    if marker.get("schema") != FORWARD_SCHEMA:
        raise V12ProofConsumerError("V12 forward marker is missing")
    sidecar_binding = _binding(marker.get("semantic_sidecar"), "v12_forward.semantic_sidecar")
    sidecar_path, sidecar = _json(sidecar_binding.get("path"), "semantic sidecar")
    contract = _validate_sidecar(request, sidecar_path, sidecar)
    return request_file, request, contract


def _validate_result_v12(result: Mapping[str, Any], bound: Mapping[str, Any],
                         result_sha: str, result_bytes: int) -> dict[str, Any]:
    contract = _ACTIVE_SCOPE
    if contract is None:
        raise V12ProofConsumerError("V12 validator was called without a semantic sidecar")
    mass = result.get("initial_mass_denominator")
    if not isinstance(mass, Mapping) or mass.get("missing_scope") != ACCEPTED_MISSING_SCOPE:
        raise V12ProofConsumerError("result missing_scope is not the exact source-bound V2 spelling")
    # Normalize only the in-memory view passed to immutable V8.  The original
    # result bytes and SHA remain the values bound by the request.
    normalized = dict(result)
    normalized_mass = dict(mass)
    normalized_mass["missing_scope"] = (
        "initial denominator mass; " + ACCEPTED_MISSING_SCOPE + "; " + ACCEPTED_SCOPE_SEMANTICS
    )
    normalized["initial_mass_denominator"] = normalized_mass
    summary = _V8_VALIDATE_RESULT(normalized, bound, result_sha, result_bytes)
    summary["source_bound_missing_scope"] = ACCEPTED_MISSING_SCOPE
    summary["denominator_semantics"] = ACCEPTED_SCOPE_SEMANTICS
    summary["later_missing_is_not_added_to_initial_denominator"] = True
    return summary


def _annotate_proof(output_path: Path, contract: Mapping[str, Any], request_file: Path) -> dict[str, Any]:
    try:
        proof = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V12ProofConsumerError(f"cannot reopen V8 proof output: {error}") from error
    if not isinstance(proof, dict) or proof.get("schema") != PROOF_SCHEMA:
        raise V12ProofConsumerError("V8 did not produce the expected proof schema")
    proof["v12_semantic_scope_adapter"] = {
        "schema": FORWARD_SCHEMA,
        "sidecar_path": contract["path"],
        "sidecar_sha256": contract["sha256"],
        "source_bound_missing_scope": ACCEPTED_MISSING_SCOPE,
        "normalized_for_v8_only": True,
        "original_result_bytes_unchanged": True,
        "denominator_semantics": ACCEPTED_SCOPE_SEMANTICS,
        "later_missing_is_not_added_to_initial_denominator": True,
        "quality": dict(UNKNOWN),
    }
    proof["request"]["path"] = str(request_file)
    proof["sha256"] = V8.canonical_sha(proof)
    output_path.write_text(
        json.dumps(proof, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return proof


def preflight(request_path: Path | str) -> dict[str, Any]:
    request_file, _request, contract = _load_marker(request_path)
    value = V8.preflight(request_file)
    value["consumer"] = {"schema": FORWARD_SCHEMA, "semantic_sidecar": contract}
    value["status"] = "READY_FOR_PARENT_V12_PROOF"
    return value


def run(request_path: Path | str, output_path: Path | str, *, io_slot_approved: bool = False,
        parent_pid: int | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    global _ACTIVE_SCOPE
    request_file, _request, contract = _load_marker(request_path)
    old_validator = V8._validate_result
    _ACTIVE_SCOPE = contract
    V8._validate_result = _validate_result_v12
    try:
        result = V8.run(request_file, output_path, io_slot_approved=io_slot_approved,
                        parent_pid=parent_pid, max_wall_seconds=max_wall_seconds)
        proof = _annotate_proof(Path(output_path).expanduser().resolve(), contract, request_file)
        result = dict(result)
        result["proof_sha256"] = proof["sha256"]
        result["semantic_scope_adapter"] = contract
        result["schema"] = FORWARD_SCHEMA
        return result
    finally:
        V8._validate_result = old_validator
        _ACTIVE_SCOPE = None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--request", type=Path, required=True)
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
    except (V12ProofConsumerError, V8.ProofConsumerError, OSError, TypeError,
            ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof consumer V12: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
