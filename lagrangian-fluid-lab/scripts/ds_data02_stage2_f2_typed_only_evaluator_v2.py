#!/usr/bin/env python3
"""Strict typed-only evaluator bound to the fresh V10/V8 proof.

This additive evaluator forwards the existing V1 operator and score logic,
but binds the actual V10 proof request and its exact root051 mass-scope
contract.  It reads the 62 MB typed JSON only in ``run`` after its parent
guard has reserved resources.  It never opens H5/BI4/raw input and grants no
raw reconstruction or scientific qualification credit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V1_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v1.py"
V10_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v10.py"
REQUEST_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-request.v2"
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-report.v2"
PRODUCER_REPORT_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_METADATA_BYTES = 32 * 1024 * 1024


class TypedEvaluatorV2Error(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedEvaluatorV2Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load(V1_SCRIPT, "ds02_bound_typed_only_evaluator_v1_for_v2")
V10 = _load(V10_SCRIPT, "ds02_bound_fresh_v16_consumer_v10_for_typed_v2")
V8 = V10.V8
# V10 re-exports the V9/V8 implementation, whose immutable module exposes
# ``_read_result`` but not the convenience ``load_json`` used by this V2
# validator.  Keep the binding strict while supplying that metadata-only
# helper locally; this reads only the small V8 proof JSON at build/run time.
if not hasattr(V8, "load_json"):
    def _load_json_compat(path: Path) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise TypedEvaluatorV2Error(f"cannot read V8 proof JSON: {error}") from error
        if not isinstance(value, dict):
            raise TypedEvaluatorV2Error("V8 proof JSON must be an object")
        return value
    V8.load_json = _load_json_compat


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V1.canonical_sha(value)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file(path: Any, role: str) -> Path:
    return V1._file(path, role)


def _json(path: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> tuple[Path, dict[str, Any]]:
    return V1._json(path, role, max_bytes=max_bytes)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return V1._write_new(path, value)


def _sha(value: Any, name: str) -> str:
    return V1._sha(value, name)


def _validate_v10_proof_request(path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    request_path, request = _json(path, "fresh V10 proof request")
    if request.get("schema") != V8.REQUEST_SCHEMA:
        raise TypedEvaluatorV2Error("fresh proof request is not V8-shaped")
    if request.get("sha256") != V8.canonical_sha(request):
        raise TypedEvaluatorV2Error("fresh V10 proof request canonical SHA differs")
    if request.get("v10_forward", {}).get("consumer", {}).get("schema") != "fresh_v16_proof_consumer_v10":
        raise TypedEvaluatorV2Error("fresh proof request is not V10-forwarded")
    consumer = request["v10_forward"]["consumer"]
    consumer_path = _file(consumer.get("path"), "V10 proof consumer")
    if consumer.get("sha256") != sha256_file(consumer_path) or consumer_path != V10_SCRIPT:
        raise TypedEvaluatorV2Error("fresh proof request V10 consumer binding differs")
    # This validates the small producer report, expected mass/cohort/event
    # contract, and exact source-bound missing-scope allow-list.
    _path, loaded, scope = V10._load_and_validate_contract(request_path)
    V10.V9._declared_paths(loaded)
    return request_path, loaded, scope


def _validate_v10_proof(path: Path, result_sha: str, proof_request: Mapping[str, Any]) -> dict[str, Any]:
    info = V1._validate_proof(path, result_sha)
    source = proof_request.get("result")
    proof = V8.load_json(path)
    if not isinstance(source, Mapping) or source.get("sha256") != result_sha:
        raise TypedEvaluatorV2Error("fresh V10 request/result binding differs")
    if proof.get("source_result", {}).get("sha256") != result_sha:
        raise TypedEvaluatorV2Error("fresh proof source result differs")
    return info


def _load_request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    request_path, request = _json(path, "typed-only evaluator V2 request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise TypedEvaluatorV2Error("typed-only evaluator V2 request schema/SHA differs")
    if request.get("status") not in {"READY_FOR_PARENT_GUARD", "PENDING_PARENT_IO_SLOT"}:
        raise TypedEvaluatorV2Error("typed-only evaluator V2 request is not parent-ready")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise TypedEvaluatorV2Error("typed-only evaluator V2 must remain model-free DEVELOPMENT")
    if request.get("qualification") != UNKNOWN or request.get("product_mode") != "TYPED_ONLY_LABELS":
        raise TypedEvaluatorV2Error("typed-only evaluator V2 quality/product mode differs")
    return request_path, request


def build_request(*, producer_report: Path | str, proof_request: Path | str,
                  proof: Path | str, source_contract: Path | str,
                  frozen_request: Path | str, output: Path | str,
                  max_wall_seconds: float = 300.0,
                  max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    """Build V2 metadata bindings without reading typed-result content."""
    proof_request_path, fresh_request, scope = _validate_v10_proof_request(proof_request)
    proof_path = _file(proof, "fresh V10/V8 proof")
    # Reuse V1's producer/source/frozen/result stat checks by asking it to
    # create a short-lived V1-shaped intermediate request.  No result bytes
    # are read by that builder; only its small JSON bindings are inspected.
    intermediate = Path(tempfile.gettempdir()) / f"ds02-typed-evaluator-v2-intermediate-{os.getpid()}.json"
    if intermediate.exists():
        raise TypedEvaluatorV2Error(f"intermediate path already exists: {intermediate}")
    try:
        value = V1.build_request(producer_report=producer_report,
                                 proof_request=proof_request, proof=proof,
                                 source_contract=source_contract,
                                 frozen_request=frozen_request, output=intermediate,
                                 max_wall_seconds=max_wall_seconds,
                                 max_result_bytes=max_result_bytes)
        intermediate_request = json.loads(intermediate.read_text(encoding="utf-8"))
    except Exception as error:
        raise TypedEvaluatorV2Error(f"V1 metadata binding failed under V10 contract: {error}") from error
    producer_path, producer = _json(producer_report, "typed-only producer report")
    producer_binding = producer.get("labels", {}).get("v16") if isinstance(producer.get("labels"), Mapping) else None
    if not isinstance(producer_binding, Mapping):
        raise TypedEvaluatorV2Error("producer V16 binding is missing")
    # V1 already verifies the source contract, stat, frozen request and proof
    # schema; V2 additionally requires the proof request's V10 scope source to
    # be the same producer report and the expected result SHA to be identical.
    scope_source = fresh_request.get("v10_mass_scope_contract", {}).get("source_report")
    if not isinstance(scope_source, Mapping) or scope_source.get("path") != str(producer_path) or scope_source.get("sha256") != sha256_file(producer_path):
        raise TypedEvaluatorV2Error("V10 scope source does not equal the producer report")
    result = intermediate_request.get("result")
    if not isinstance(result, Mapping) or result.get("sha256") != producer_binding.get("sha256"):
        raise TypedEvaluatorV2Error("V1 intermediate result binding differs")
    result_path = _file(result.get("path"), "typed V16 result")
    proof_info = _validate_v10_proof(proof_path, str(result["sha256"]), fresh_request)
    request: dict[str, Any] = dict(intermediate_request)
    request["schema"] = REQUEST_SCHEMA
    request["proof_request"] = dict(request["proof_request"])
    request["proof_request"]["schema"] = V8.REQUEST_SCHEMA
    request["v2_forward"] = {
        "schema": "ds02.stage2.f2-typed-only-evaluator-v2-forward.v1",
        "source_evaluator_request_schema": V1.REQUEST_SCHEMA,
        "fresh_proof_consumer": {"path": str(V10_SCRIPT), "sha256": sha256_file(V10_SCRIPT),
                                  "schema": "fresh_v16_proof_consumer_v10"},
        "fresh_proof_request_sha256": sha256_file(proof_request_path),
        "mass_scope_contract": scope,
        "source_bound_only": True,
        "hdf5_or_bi4_content_read_during_build": False,
        "original_path_fallback": "FORBIDDEN",
    }
    request["limitations"] = list(request.get("limitations", [])) + [
        "V2 accepts only the exact root051 missing_scope spelling through the V10 source-bound contract; other spellings remain rejected.",
        "Fresh proof remains V8 schema and all QI/QN/QE remain UNKNOWN.",
    ]
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    return {"status": request["status"], "request": str(target), "sha256": request["sha256"],
            "result_sha256": result["sha256"], "result_bytes": result["bytes"],
            "proof_sha256": proof_info["sha256"], "mass_scope": scope["accepted_result_missing_scope"],
            "payload_read": False, "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def run_trial(request_path: Path | str, *, output: Path | str,
              parent_pid: int | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    request_file, request = _load_request(request_path)
    if parent_pid is not None and os.getppid() != int(parent_pid):
        raise TypedEvaluatorV2Error("typed-only evaluator parent is not the direct parent")
    result_binding = request.get("result")
    result_path = _file(result_binding.get("path") if isinstance(result_binding, Mapping) else None,
                        "typed V16 result")
    expected_sha = _sha(result_binding.get("sha256") if isinstance(result_binding, Mapping) else None,
                        "result.sha256")
    observed_sha = sha256_file(result_path)
    if observed_sha != expected_sha:
        raise TypedEvaluatorV2Error("typed V16 result SHA differs from V2 request")
    if int(result_binding.get("bytes", -1)) != result_path.stat().st_size:
        raise TypedEvaluatorV2Error("typed V16 result byte stat differs from V2 request")
    proof_request_path = _file(request.get("proof_request", {}).get("path"), "fresh V10 proof request")
    proof_request_path, proof_request, scope = _validate_v10_proof_request(proof_request_path)
    bound = V8._validate_request(proof_request, verify_result_stat=True)
    if bound["result_path"] != result_path or bound["result_sha256"] != observed_sha:
        raise TypedEvaluatorV2Error("typed result and fresh V10 request are not the same product")
    result = V8._read_result(result_path, int(bound["max_result_bytes"]))[0]
    previous = V10._ACTIVE_SCOPE_CONTRACT
    V10._ACTIVE_SCOPE_CONTRACT = scope
    try:
        V10._validate_result_v10(result, bound, observed_sha, result_path.stat().st_size)
    finally:
        V10._ACTIVE_SCOPE_CONTRACT = previous
    report_info = V1._validate_producer_report(_file(request["producer_report"]["path"], "producer report"), result_path, observed_sha)
    proof_info = _validate_v10_proof(_file(request["proof"]["path"], "fresh V8 proof"), observed_sha, proof_request)
    contract_info = V1._validate_source_contract(_file(request["source_contract"]["path"], "source contract"))
    frozen_path, frozen = _json(request["frozen_request"]["path"], "frozen V15 request")
    if sha256_file(frozen_path) != request["frozen_request"]["sha256"]:
        raise TypedEvaluatorV2Error("frozen V15 request SHA differs")
    score = V1._score_typed_result(result, frozen)
    value: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "status": "PASS_DEVELOPMENT_TYPED_ONLY_OPERATOR_TRIAL_V2",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "typed_only_product": {"result_path": str(result_path), "result_sha256": observed_sha,
                                "result_bytes": result_path.stat().st_size,
                                "raw_opened": False, "hdf5_or_bi4_content_read": False},
        "producer_report": report_info, "fresh_v8_proof": proof_info,
        "fresh_v8_proof_request": {"path": str(proof_request_path),
                                    "sha256": request["proof_request"]["sha256"],
                                    "consumer": {"path": str(V10_SCRIPT), "sha256": sha256_file(V10_SCRIPT)}},
        "mass_scope_contract": scope, "source_contract": contract_info,
        "frozen_v15_request": {"path": str(frozen_path), "sha256": request["frozen_request"]["sha256"]},
        "operator_score": score, "model_invoked": False, "cfd_invoked": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "credit_boundary": {
            "typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
            "portable_cold_replay_credit": "NOT_CLAIMED",
            "scientific_qualification": "UNKNOWN",
            "statement": "V2 scores a typed JSON result after a fresh V10/V8 proof; it does not rerun or certify raw BI4 reconstruction.",
        },
    }
    value["sha256"] = canonical_sha(value)
    _write_new(output, value)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--producer-report", type=Path, required=True)
    build.add_argument("--proof-request", type=Path, required=True)
    build.add_argument("--proof", type=Path, required=True)
    build.add_argument("--source-contract", type=Path, required=True)
    build.add_argument("--frozen-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float, default=300.0)
    build.add_argument("--max-result-bytes", type=int, default=100_000_000)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--parent-pid", type=int)
    run.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = build_request(producer_report=args.producer_report,
                                  proof_request=args.proof_request, proof=args.proof,
                                  source_contract=args.source_contract,
                                  frozen_request=args.frozen_request, output=args.output,
                                  max_wall_seconds=args.max_wall_seconds,
                                  max_result_bytes=args.max_result_bytes)
        else:
            value = run_trial(args.request, output=args.output, parent_pid=args.parent_pid,
                              max_wall_seconds=args.max_wall_seconds)
    except (TypedEvaluatorV2Error, V1.TypedEvaluatorError, V8.ProofConsumerError,
            V1.V3.EvaluatorV3BindingError, V1.V3.v2.EvaluatorV2BindingError,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator V2: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value.get("status"), "sha256": value.get("sha256"),
                      "qualification": value.get("qualification", UNKNOWN)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
