#!/usr/bin/env python3
"""Evaluate an already verified typed-only V16 result.

This worker is deliberately separate from the raw-to-typed-to-label
evaluator.  It consumes a V8 fresh-proof request/result and the small
typed-only producer report, then validates the V16 identity, denominator,
saved-time and event contracts.  It does not manufacture a raw report or
claim that the copied BI4 tree was reconstructed.  A result-derived
operator self-test is included for the existing macro/event score contract;
all scientific qualification remains UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V3_EVALUATOR = SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v3.py"
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-report.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-request.v1"
PRODUCER_REPORT_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
RESULT_SCHEMA = "ds02.stage2.f2-s1-replay-result.v16"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024


class TypedEvaluatorError(RuntimeError):
    """Typed-only binding or score-contract failure."""


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedEvaluatorError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V8 = _load(V8_SCRIPT, "ds02_bound_fresh_v16_consumer_v8_typed_eval")
V3 = _load(V3_EVALUATOR, "ds02_bound_no_model_evaluator_v3_typed_eval")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V8.canonical_sha(value)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(x not in HEX64 for x in value):
        raise TypedEvaluatorError(f"{name} must be a lowercase SHA-256")
    return value


def _file(path: Any, role: str) -> Path:
    if not isinstance(path, (str, Path)):
        raise TypedEvaluatorError(f"{role} path is missing")
    target = Path(path).expanduser().resolve()
    if not target.is_file() or target.is_symlink():
        raise TypedEvaluatorError(f"{role} is not a regular non-symlink file: {target}")
    return target


def _json(path: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    if target.stat().st_size > max_bytes:
        raise TypedEvaluatorError(f"{role} exceeds metadata-only limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TypedEvaluatorError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise TypedEvaluatorError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise TypedEvaluatorError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                                 allow_nan=False, default=str) + "\n", encoding="utf-8")
    return target


def _load_request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    request_path, request = _json(path, "typed-only evaluator request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise TypedEvaluatorError("typed-only evaluator request schema/SHA differs")
    if request.get("status") not in {"READY_FOR_PARENT_GUARD", "PENDING_PARENT_IO_SLOT"}:
        raise TypedEvaluatorError("typed-only evaluator request is not parent-ready")
    if request.get("role") != "DEVELOPMENT" or request.get("model_invoked") is not False:
        raise TypedEvaluatorError("typed-only evaluator must remain model-free DEVELOPMENT")
    if request.get("qualification") != UNKNOWN:
        raise TypedEvaluatorError("typed-only evaluator qualification must remain UNKNOWN")
    if request.get("product_mode") != "TYPED_ONLY_LABELS":
        raise TypedEvaluatorError("raw/cold product mode cannot enter typed-only evaluator")
    return request_path, request


def _validate_producer_report(path: Path, result_path: Path, result_sha: str) -> dict[str, Any]:
    report_path, report = _json(path, "typed-only producer report")
    if report.get("schema") != PRODUCER_REPORT_SCHEMA or report.get("sha256") != canonical_sha(report):
        raise TypedEvaluatorError("typed-only producer report schema/SHA differs")
    if not str(report.get("status", "")).startswith("COMPLETE_TYPED_ONLY_LABELS_"):
        raise TypedEvaluatorError("typed-only producer report is not complete")
    if report.get("model_invoked") is not False or report.get("cfd_invoked") is not False:
        raise TypedEvaluatorError("typed-only producer report model/CFD flags are not closed")
    if report.get("qualification") != UNKNOWN:
        raise TypedEvaluatorError("typed-only producer report qualification is not UNKNOWN")
    binding = report.get("labels", {}).get("v16") if isinstance(report.get("labels"), Mapping) else None
    if not isinstance(binding, Mapping):
        raise TypedEvaluatorError("producer report labels.v16 binding is missing")
    if Path(str(binding.get("path"))).expanduser().resolve() != result_path:
        raise TypedEvaluatorError("producer report result path differs from evaluator request")
    if binding.get("sha256") != result_sha:
        raise TypedEvaluatorError("producer report result SHA differs from observed result")
    return {"path": str(report_path), "sha256": sha256_file(report_path),
            "schema": report.get("schema"), "status": report.get("status")}


def _validate_proof(proof_path: Path, result_sha: str) -> dict[str, Any]:
    path, proof = _json(proof_path, "fresh V8 proof")
    if proof.get("schema") != PROOF_SCHEMA:
        raise TypedEvaluatorError("fresh proof is not V8 typed-result proof")
    if proof.get("sha256") != canonical_sha(proof):
        raise TypedEvaluatorError("fresh proof canonical SHA differs")
    if proof.get("status") != "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN":
        raise TypedEvaluatorError("fresh V8 proof is not a completed development proof")
    if proof.get("qualification") != UNKNOWN or proof.get("quality") != UNKNOWN:
        raise TypedEvaluatorError("fresh V8 proof qualification is not UNKNOWN")
    source = proof.get("source_result")
    if not isinstance(source, Mapping) or source.get("sha256") != result_sha or source.get("content_sha_verified") is not True:
        raise TypedEvaluatorError("fresh V8 proof does not verify the observed V16 result")
    if proof.get("execution", {}).get("hdf5_or_bi4_content_read") is not False:
        raise TypedEvaluatorError("fresh proof has an unexpected HDF5/BI4 read")
    return {"path": str(path), "sha256": sha256_file(path), "schema": proof.get("schema"),
            "result_sha256": result_sha, "status": proof.get("status")}


def _validate_source_contract(path: Path) -> dict[str, Any]:
    contract_path, contract = _json(path, "fresh V16 source contract")
    if contract.get("schema") != "ds02.stage2.f2-fresh-v16-source-contract.v1":
        raise TypedEvaluatorError("fresh V16 source contract schema differs")
    if contract.get("sha256") != canonical_sha(contract) or contract.get("role") != "DEVELOPMENT":
        raise TypedEvaluatorError("fresh V16 source contract canonical/status differs")
    if contract.get("quality") != UNKNOWN:
        raise TypedEvaluatorError("fresh V16 source contract quality is not UNKNOWN")
    return {"path": str(contract_path), "sha256": sha256_file(contract_path),
            "schema": contract.get("schema")}


def build_request(*, producer_report: Path | str, proof_request: Path | str,
                  proof: Path | str, source_contract: Path | str,
                  frozen_request: Path | str, output: Path | str,
                  max_wall_seconds: float = 300.0,
                  max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    """Bind a typed-only evaluator request without reading the V16 payload.

    The producer report supplies the expected V16 SHA and stat.  The parent
    worker hashes and validates that 62 MB JSON only after its reservation;
    this builder therefore performs metadata/stat checks and never turns a
    typed-only product into a raw-to-label claim.
    """
    if isinstance(max_result_bytes, bool) or not isinstance(max_result_bytes, int) or max_result_bytes <= 0:
        raise TypedEvaluatorError("max_result_bytes must be a positive integer")
    if not isinstance(max_wall_seconds, (int, float)) or isinstance(max_wall_seconds, bool) or float(max_wall_seconds) <= 0:
        raise TypedEvaluatorError("max_wall_seconds must be positive")
    producer_path, producer = _json(producer_report, "typed-only producer report")
    if producer.get("schema") != PRODUCER_REPORT_SCHEMA or producer.get("sha256") != canonical_sha(producer):
        raise TypedEvaluatorError("typed-only producer report schema/SHA differs")
    if not str(producer.get("status", "")).startswith("COMPLETE_TYPED_ONLY_LABELS_"):
        raise TypedEvaluatorError("typed-only producer report is not complete")
    if producer.get("model_invoked") is not False or producer.get("cfd_invoked") is not False:
        raise TypedEvaluatorError("typed-only producer report model/CFD flags are not closed")
    if producer.get("qualification") != UNKNOWN:
        raise TypedEvaluatorError("typed-only producer qualification must remain UNKNOWN")
    labels = producer.get("labels")
    if not isinstance(labels, Mapping) or not isinstance(labels.get("v16"), Mapping):
        raise TypedEvaluatorError("typed-only producer labels.v16 binding is missing")
    producer_result = labels["v16"]
    result_path = _file(producer_result.get("path"), "typed V16 result")
    result_sha = _sha(producer_result.get("sha256"), "producer V16 result SHA")
    result_stat = result_path.stat()
    declared_bytes = int(producer_result.get("bytes", result_stat.st_size))
    if result_stat.st_size != declared_bytes or declared_bytes <= 0 or declared_bytes > max_result_bytes:
        raise TypedEvaluatorError("typed V16 result stat exceeds builder contract")

    proof_request_path, proof_request_value = _json(proof_request, "fresh V8 proof request")
    if proof_request_value.get("schema") != V8.REQUEST_SCHEMA:
        raise TypedEvaluatorError("proof request is not V8")
    if proof_request_value.get("sha256") != V8.canonical_sha(proof_request_value):
        raise TypedEvaluatorError("proof request canonical SHA differs")
    bound = V8._validate_request(proof_request_value, verify_result_stat=True)
    if bound["result_path"] != result_path or bound["result_sha256"] != result_sha:
        raise TypedEvaluatorError("producer result and fresh V8 request are not the same product")
    if int(bound["max_result_bytes"]) < declared_bytes:
        raise TypedEvaluatorError("fresh V8 result bound is smaller than producer result")

    proof_path = _file(proof, "fresh V8 proof")
    proof_info = _validate_proof(proof_path, result_sha)
    contract_path = _file(source_contract, "fresh V16 source contract")
    contract_info = _validate_source_contract(contract_path)
    frozen_path = _file(frozen_request, "frozen V15 request")
    frozen_sha = sha256_file(frozen_path)
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if not isinstance(frozen, Mapping):
        raise TypedEvaluatorError("frozen V15 request must be a JSON object")
    try:
        V3.v2.validate_frozen_request(frozen)
    except Exception as error:
        raise TypedEvaluatorError(f"frozen V15 request does not validate: {error}") from error
    try:
        wall = float(max_wall_seconds)
    except (TypeError, ValueError) as error:
        raise TypedEvaluatorError("max_wall_seconds is malformed") from error
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "product_mode": "TYPED_ONLY_LABELS",
        "case_id": bound["expected"].get("case_identity", {}).get("manifest_case_id"),
        "producer_report": {"path": str(producer_path), "sha256": sha256_file(producer_path),
                             "schema": PRODUCER_REPORT_SCHEMA, "content_read": True},
        "proof_request": {"path": str(proof_request_path), "sha256": sha256_file(proof_request_path),
                           "schema": V8.REQUEST_SCHEMA, "content_read": True},
        "proof": {"path": str(proof_path), "sha256": proof_info["sha256"],
                   "schema": PROOF_SCHEMA, "content_read": True},
        "source_contract": {"path": contract_info["path"], "sha256": contract_info["sha256"],
                             "schema": contract_info["schema"], "content_read": True},
        "frozen_request": {"path": str(frozen_path), "sha256": frozen_sha,
                            "schema": frozen.get("schema"), "content_read": True},
        "result": {"path": str(result_path), "sha256": result_sha,
                    "bytes": declared_bytes,
                    "stat": {"bytes": int(result_stat.st_size),
                             "mtime_ns": int(result_stat.st_mtime_ns),
                             "mode_bits": int(result_stat.st_mode & 0o777)},
                    "content_sha_verified": False,
                    "content_verification_phase": "PARENT_AFTER_RESERVATION"},
        "execution": {"max_wall_seconds": wall, "max_result_bytes": int(max_result_bytes),
                       "read_hdf5_or_bi4": False, "raw_opened": False,
                       "original_path_fallback": "FORBIDDEN",
                       "result_content_verification": "after_parent_reservation"},
        "model_invoked": False, "cfd_invoked": False, "ledger_mutated": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "credit_boundary": {"typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
                             "portable_cold_replay_credit": "NOT_CLAIMED",
                             "scientific_qualification": "UNKNOWN"},
        "limitations": [
            "The parent hashes the V16 JSON only after its same-parent reservation.",
            "This worker validates an existing typed-only result and independent V8 proof.",
            "No HDF5/BI4/raw source is opened and no raw-to-typed or portable-cold credit is granted.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    return {"status": request["status"], "request": str(target),
            "sha256": request["sha256"], "result_sha256": result_sha,
            "result_bytes": declared_bytes, "proof_sha256": proof_info["sha256"],
            "payload_read": False, "hdf5_or_bi4_read": False,
            "qualification": dict(UNKNOWN)}


def _score_typed_result(result: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any]:
    """Run the existing macro/event operator self-test in memory only."""
    adapted, adapter = V3.adapt_v16_result(result)
    frozen_validation = V3.v2.validate_frozen_request(frozen)
    result_validation = V3.v2._validate_result_shape(adapted, frozen)
    profile = frozen["observer_profile"]
    cases: dict[str, Any] = {}
    for mutation in ("pass", "wrong_velocity", "wrong_time", "wrong_budget", "wrong_shape", "wrong_source"):
        try:
            prediction = V3.v2.macro_prediction_from_result(adapted, profile, mutation=mutation)
            cases[mutation] = V3.v2.score_macro_prediction(adapted, prediction, profile)
        except V3.v2.EvaluatorV2BindingError as error:
            cases[mutation] = {"status": "BINDING_ERROR", "error": str(error),
                               "binding_error": True, "model_invoked": False,
                               "qualification": dict(UNKNOWN)}
    expected = {"pass": "PASS", "wrong_velocity": "FAIL", "wrong_time": "FAIL",
                "wrong_budget": "FAIL", "wrong_shape": "BINDING_ERROR",
                "wrong_source": "BINDING_ERROR"}
    if any(cases[key].get("status") != value for key, value in expected.items()):
        raise TypedEvaluatorError("typed-only operator counterexample expectations were not met")
    return {"source_profile_binding": frozen_validation, "result_binding": result_validation,
            "v16_schema_adapter": adapter, "cases": cases, "case_expectations": expected}


def run_trial(request_path: Path | str, *, output: Path | str,
              parent_pid: int | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    request_file, request = _load_request(request_path)
    if parent_pid is not None and os.getppid() != int(parent_pid):
        raise TypedEvaluatorError("typed-only evaluator parent is not the direct parent")
    result_binding = request.get("result")
    result_path = _file(result_binding.get("path") if isinstance(result_binding, Mapping) else None,
                        "typed V16 result")
    expected_sha = _sha(result_binding.get("sha256") if isinstance(result_binding, Mapping) else None,
                        "result.sha256")
    observed_sha = sha256_file(result_path)
    if observed_sha != expected_sha:
        raise TypedEvaluatorError("typed V16 result SHA differs from request")
    if int(result_binding.get("bytes", -1)) != result_path.stat().st_size:
        raise TypedEvaluatorError("typed V16 result byte stat differs from request")
    proof_request_path = _file(request.get("proof_request", {}).get("path"), "fresh V8 proof request")
    proof_request = V8.load_json(proof_request_path)
    if V8.canonical_sha(proof_request) != request["proof_request"]["sha256"]:
        raise TypedEvaluatorError("fresh V8 proof request SHA differs")
    bound = V8._validate_request(proof_request, verify_result_stat=True)
    if bound["result_path"] != result_path or bound["result_sha256"] != observed_sha:
        raise TypedEvaluatorError("typed result and fresh V8 request are not the same product")
    result = V8._read_result(result_path, int(bound["max_result_bytes"]))[0]
    V8._validate_result(result, bound, observed_sha, result_path.stat().st_size)
    report_info = _validate_producer_report(_file(request["producer_report"]["path"], "producer report"), result_path, observed_sha)
    proof_info = _validate_proof(_file(request["proof"]["path"], "fresh V8 proof"), observed_sha)
    contract_info = _validate_source_contract(_file(request["source_contract"]["path"], "source contract"))
    frozen_path, frozen = _json(request["frozen_request"]["path"], "frozen V15 request")
    if sha256_file(frozen_path) != request["frozen_request"]["sha256"]:
        raise TypedEvaluatorError("frozen V15 request SHA differs")
    score = _score_typed_result(result, frozen)
    value: dict[str, Any] = {
        "schema": REPORT_SCHEMA, "status": "PASS_DEVELOPMENT_TYPED_ONLY_OPERATOR_TRIAL_V1",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "typed_only_product": {"result_path": str(result_path), "result_sha256": observed_sha,
                                "result_bytes": result_path.stat().st_size,
                                "raw_opened": False, "hdf5_or_bi4_content_read": False},
        "producer_report": report_info, "fresh_v8_proof": proof_info,
        "fresh_v8_proof_request": {"path": str(proof_request_path),
                                    "sha256": request["proof_request"]["sha256"]},
        "source_contract": contract_info,
        "frozen_v15_request": {"path": str(frozen_path), "sha256": request["frozen_request"]["sha256"]},
        "operator_score": score, "model_invoked": False, "cfd_invoked": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "credit_boundary": {
            "typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
            "portable_cold_replay_credit": "NOT_CLAIMED",
            "scientific_qualification": "UNKNOWN",
            "statement": "This is a JSON typed-result operator self-test after an independent V8 proof; it does not re-run or certify raw BI4 reconstruction.",
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
    except (TypedEvaluatorError, V8.ProofConsumerError, V3.EvaluatorV3BindingError,
            V3.v2.EvaluatorV2BindingError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value.get("status"), "sha256": value.get("sha256"),
                      "qualification": value.get("qualification", UNKNOWN)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
