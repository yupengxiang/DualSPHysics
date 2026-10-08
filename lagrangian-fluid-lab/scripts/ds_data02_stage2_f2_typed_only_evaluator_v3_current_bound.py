#!/usr/bin/env python3
"""V3 typed-only evaluator with an explicit dual CURRENT reconciliation.

``ds_data02_stage2_f2_typed_only_evaluator_v2.py`` is kept byte-for-byte
stable as the earlier V2 development interface.  This forward module adds a
small CURRENT binding sidecar for a V10 proof whose inherited ``aabfb...``
catalog value is a historical relocated view.  The actual CURRENT file
(``df7e...``) is checked separately by the parent; the historical hash is
admitted only through an in-memory, explicitly named adapter.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V2_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v2.py"
CURRENT_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_current_catalog_binding_v1.py"
REQUEST_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-request.v2"
REPORT_SCHEMA = "ds02.stage2.f2-typed-only-evaluator-report.v3-current-reconciled"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class TypedEvaluatorV2CurrentError(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TypedEvaluatorV2CurrentError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load(V2_SCRIPT, "ds02_bound_typed_only_evaluator_v2_for_current_bound")
CURRENT = _load(CURRENT_SCRIPT, "ds02_bound_current_catalog_binding_v1_for_evaluator_v2")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V2.canonical_sha(value)


def sha256_file(path: Path | str) -> str:
    return V2.sha256_file(path)


def _file(value: Any, role: str) -> Path:
    return V2._file(value, role)


def _json(path: Any, role: str, *, max_bytes: int = V2.MAX_METADATA_BYTES) -> tuple[Path, dict[str, Any]]:
    return V2._json(path, role, max_bytes=max_bytes)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    return V2._write_new(path, value)


def _binding_item(value: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    item = value.get("current_catalog_binding")
    if not isinstance(item, Mapping):
        raise TypedEvaluatorV2CurrentError("current_catalog_binding is required")
    path = _file(item.get("path"), "CURRENT catalog binding sidecar")
    if item.get("sha256") != sha256_file(path):
        raise TypedEvaluatorV2CurrentError("CURRENT catalog binding sidecar SHA differs")
    sidecar = CURRENT._json(path, "CURRENT catalog binding sidecar")[1]
    current_path = _file(sidecar.get("current_catalog", {}).get("path"), "CURRENT336 source")
    frozen_path = _file(sidecar.get("frozen_v15_request", {}).get("path"), "frozen V15 source")
    proof_path = _file(sidecar.get("historical_v10_proof", {}).get("path"), "historical V10 proof source")
    info = CURRENT.validate_binding(path, current_catalog=current_path,
                                    frozen_request=frozen_path, proof=proof_path)
    if info["status"] != "PASS_FROZEN_V15_CURRENT_JOIN_RESULT_BINDING_STALE":
        raise TypedEvaluatorV2CurrentError("CURRENT catalog binding is not conservative")
    return path, info


def _validate_current_request(value: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    path, info = _binding_item(value)
    if value.get("current_catalog_binding", {}).get("schema") != CURRENT.SCHEMA:
        raise TypedEvaluatorV2CurrentError("CURRENT catalog binding schema differs")
    forward = value.get("v2_current_forward")
    if not isinstance(forward, Mapping) or forward.get("schema") != "ds02.stage2.f2-typed-only-evaluator-v2-current-forward.v1":
        raise TypedEvaluatorV2CurrentError("current-bound V2 forward metadata is missing")
    return path, info


def _dual_source_score(result: Mapping[str, Any], frozen: Mapping[str, Any],
                       binding_info: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Score a result against an explicitly historical relocated source view.

    The parent has already validated the actual CURRENT file and its case row.
    The inherited V16 result still carries the historical overlay hash.  A
    shadow request is used only in memory for the existing operator; neither
    the frozen request nor the result is rewritten.
    """
    source = result.get("source_binding")
    if not isinstance(source, Mapping):
        raise TypedEvaluatorV2CurrentError("result source_binding is missing")
    actual = str(binding_info.get("current_catalog_sha256", ""))
    historical = str(binding_info.get("historical_result_current_catalog_sha256", ""))
    if len(actual) != 64 or len(historical) != 64 or actual == historical:
        raise TypedEvaluatorV2CurrentError("dual CURRENT binding is not a distinct actual/historical pair")
    if source.get("current_catalog_sha256") != historical:
        raise TypedEvaluatorV2CurrentError(
            "result CURRENT hash differs from the explicitly bound historical relocated view")
    files = source.get("source_files")
    if not isinstance(files, Mapping) or files.get("current_catalog") != historical:
        raise TypedEvaluatorV2CurrentError(
            "result current source-file hash differs from the explicitly bound historical view")
    shadow = copy.deepcopy(frozen)
    current = shadow.get("current_binding")
    if not isinstance(current, dict):
        raise TypedEvaluatorV2CurrentError("frozen current_binding is missing")
    current["sha256"] = historical
    source_files = shadow.get("source_files")
    if not isinstance(source_files, list):
        raise TypedEvaluatorV2CurrentError("frozen source_files are missing")
    current_entries = [item for item in source_files
                       if isinstance(item, dict) and item.get("role") == "current_catalog"]
    if len(current_entries) != 1:
        raise TypedEvaluatorV2CurrentError("frozen current_catalog source entry is not unique")
    current_entries[0]["sha256"] = historical
    score = V2.V1._score_typed_result(result, shadow)
    reconciliation = {
        "status": "PASS_DUAL_CURRENT_RESULT_HISTORICAL_VIEW",
        "actual_current_catalog_sha256": actual,
        "historical_result_current_catalog_sha256": historical,
        "result_current_catalog_sha256": historical,
        "shadow_request_used_only_in_memory": True,
        "real_current_validated_separately_by_parent": True,
        "exact_current_source_claim": "NOT_GRANTED_TO_HISTORICAL_RESULT_VIEW",
    }
    score["current_source_reconciliation"] = reconciliation
    return score, reconciliation


def _load_request(path: Path | str) -> tuple[Path, dict[str, Any]]:
    request_path, request = V2._load_request(path)
    _validate_current_request(request)
    return request_path, request


def build_request(*, producer_report: Path | str, proof_request: Path | str,
                  proof: Path | str, source_contract: Path | str,
                  frozen_request: Path | str, current_binding: Path | str,
                  output: Path | str, max_wall_seconds: float = 300.0,
                  max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    binding_path = _file(current_binding, "CURRENT catalog binding sidecar")
    binding_sidecar = CURRENT._json(binding_path, "CURRENT catalog binding sidecar")[1]
    binding_info = CURRENT.validate_binding(
        binding_path,
        current_catalog=_file(binding_sidecar.get("current_catalog", {}).get("path"), "CURRENT336 source"),
        frozen_request=_file(binding_sidecar.get("frozen_v15_request", {}).get("path"), "frozen V15 source"),
        proof=_file(binding_sidecar.get("historical_v10_proof", {}).get("path"), "historical V10 proof source"),
    )
    # V2's build is metadata-only and already checks the producer/proof/V15
    # contracts.  Use a fresh temporary output, then add the required binding
    # before canonicalising the published request.
    temporary = Path(tempfile.gettempdir()) / f"ds02-typed-evaluator-v2-current-{os.getpid()}.json"
    if temporary.exists():
        raise TypedEvaluatorV2CurrentError(f"temporary request already exists: {temporary}")
    # Root and consumer worktrees carry byte-identical V10 consumers but the
    # historical root request names the root path.  Accept that relocation
    # only after hashing the named consumer against the bound V2 source, then
    # let the unchanged V2 validator use that exact named path for this
    # forward request.
    _proof_req_path, _proof_req = _json(proof_request, "fresh V10 proof request")
    _consumer = _proof_req.get("v10_forward", {}).get("consumer", {})
    _consumer_path = _file(_consumer.get("path"), "V10 consumer in proof request")
    if _consumer.get("sha256") != sha256_file(_consumer_path):
        raise TypedEvaluatorV2CurrentError("V10 consumer in proof request SHA differs")
    if sha256_file(_consumer_path) != sha256_file(V2.V10_SCRIPT):
        raise TypedEvaluatorV2CurrentError("V10 consumer bytes differ from current-bound source")
    old_v10_script = V2.V10_SCRIPT
    V2.V10_SCRIPT = _consumer_path
    try:
        V2.build_request(producer_report=producer_report, proof_request=proof_request,
                         proof=proof, source_contract=source_contract,
                         frozen_request=frozen_request, output=temporary,
                         max_wall_seconds=max_wall_seconds,
                         max_result_bytes=max_result_bytes)
        request = json.loads(temporary.read_text(encoding="utf-8"))
    except Exception as error:
        raise TypedEvaluatorV2CurrentError(f"V2 metadata binding failed: {error}") from error
    finally:
        V2.V10_SCRIPT = old_v10_script
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    request["current_catalog_binding"] = {
        "path": str(binding_path), "sha256": sha256_file(binding_path),
        "schema": CURRENT.SCHEMA, "content_read_during_build": True,
        "current_catalog_sha256": binding_info["current_catalog_sha256"],
        "historical_result_current_catalog_sha256": binding_info["historical_result_current_catalog_sha256"],
        "case_join_status": binding_info["case_join"]["status"],
    }
    request["v2_current_forward"] = {
        "schema": "ds02.stage2.f2-typed-only-evaluator-v2-current-forward.v1",
        "base_v2_schema": REQUEST_SCHEMA,
        "current_binding_schema": CURRENT.SCHEMA,
        "current_binding_module": {"path": str(CURRENT_SCRIPT),
                                    "sha256": sha256_file(CURRENT_SCRIPT)},
        "import_closure": [
            {"role": "typed_evaluator_v2_base", "path": str(V2_SCRIPT),
             "sha256": sha256_file(V2_SCRIPT)},
            {"role": "typed_evaluator_v1_base", "path": str(V2.V1_SCRIPT),
             "sha256": sha256_file(V2.V1_SCRIPT)},
            {"role": "fresh_v16_consumer_v10", "path": str(V2.V10_SCRIPT),
             "sha256": sha256_file(V2.V10_SCRIPT)},
            {"role": "fresh_v16_consumer_v9", "path": str(V2.V10.V9_SCRIPT),
             "sha256": sha256_file(V2.V10.V9_SCRIPT)},
            {"role": "fresh_v16_consumer_v8", "path": str(V2.V10.V9.V8_SCRIPT),
             "sha256": sha256_file(V2.V10.V9.V8_SCRIPT)},
        ],
        "current_binding_sha256": sha256_file(binding_path),
        "actual_current_catalog_sha256": binding_info["current_catalog_sha256"],
        "historical_result_current_catalog_sha256": binding_info["historical_result_current_catalog_sha256"],
        "requires_exact_v15_case_join": True,
        "historical_exact_current_claim": "REJECTED_STALE_CATALOG_BINDING",
        "hdf5_or_bi4_content_read_during_build": False,
        "original_path_fallback": "FORBIDDEN",
    }
    request["limitations"] = list(request.get("limitations", [])) + [
        "V10 result/proof inherited aabfb current binding; this request accepts it only with the explicit metadata reconciliation sidecar.",
        "The sidecar establishes a CURRENT/V15 case/source join; QI/QN/QE and portable/raw credit remain UNKNOWN.",
    ]
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    return {"status": request["status"], "request": str(target),
            "sha256": request["sha256"],
            "current_binding_sha256": sha256_file(binding_path),
            "actual_current_catalog_sha256": binding_info["current_catalog_sha256"],
            "historical_result_current_catalog_sha256": binding_info["historical_result_current_catalog_sha256"],
            "result_sha256": request["result"]["sha256"],
            "result_bytes": request["result"]["bytes"],
            "payload_read": False, "hdf5_or_bi4_read": False,
            "qualification": dict(UNKNOWN)}


def run_trial(request_path: Path | str, *, output: Path | str,
              parent_pid: int | None = None, max_wall_seconds: float | None = None) -> dict[str, Any]:
    request_file, request = _load_request(request_path)
    binding_path, binding_info = _validate_current_request(request)
    if parent_pid is not None and os.getppid() != int(parent_pid):
        raise TypedEvaluatorV2CurrentError("typed-only evaluator parent is not the direct parent")
    result_binding = request.get("result")
    result_path = _file(result_binding.get("path") if isinstance(result_binding, Mapping) else None,
                        "typed V16 result")
    expected_sha = V2._sha(result_binding.get("sha256") if isinstance(result_binding, Mapping) else None,
                           "result.sha256")
    observed_sha = sha256_file(result_path)
    if observed_sha != expected_sha:
        raise TypedEvaluatorV2CurrentError("typed V16 result SHA differs from V3 request")
    if int(result_binding.get("bytes", -1)) != result_path.stat().st_size:
        raise TypedEvaluatorV2CurrentError("typed V16 result byte stat differs from V3 request")
    proof_request_path, proof_request, scope = V2._validate_v10_proof_request(
        _file(request.get("proof_request", {}).get("path"), "fresh V10 proof request"))
    bound = V2.V8._validate_request(proof_request, verify_result_stat=True)
    if bound["result_path"] != result_path or bound["result_sha256"] != observed_sha:
        raise TypedEvaluatorV2CurrentError("typed result and fresh V10 request are not the same product")
    result = V2.V8._read_result(result_path, int(bound["max_result_bytes"]))[0]
    previous = V2.V10._ACTIVE_SCOPE_CONTRACT
    V2.V10._ACTIVE_SCOPE_CONTRACT = scope
    try:
        V2.V10._validate_result_v10(result, bound, observed_sha, result_path.stat().st_size)
    finally:
        V2.V10._ACTIVE_SCOPE_CONTRACT = previous
    report_info = V2.V1._validate_producer_report(
        _file(request["producer_report"]["path"], "producer report"), result_path, observed_sha)
    proof_info = V2._validate_v10_proof(
        _file(request["proof"]["path"], "fresh V8 proof"), observed_sha, proof_request)
    contract_info = V2.V1._validate_source_contract(
        _file(request["source_contract"]["path"], "source contract"))
    frozen_path, frozen = V2._json(request["frozen_request"]["path"], "frozen V15 request")
    if sha256_file(frozen_path) != request["frozen_request"]["sha256"]:
        raise TypedEvaluatorV2CurrentError("frozen V15 request SHA differs")
    operator_score, reconciliation = _dual_source_score(result, frozen, binding_info)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_DEVELOPMENT_TYPED_ONLY_OPERATOR_TRIAL_V3_DUAL_CURRENT",
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
        "operator_score": operator_score,
        "current_catalog_binding": {"path": str(binding_path), "sha256": sha256_file(binding_path),
                                     "schema": CURRENT.SCHEMA,
                                     "actual_current_catalog_sha256": binding_info["current_catalog_sha256"],
                                     "historical_result_current_catalog_sha256": binding_info["historical_result_current_catalog_sha256"],
                                     "case_join_status": binding_info["case_join"]["status"]},
        "current_source_reconciliation": reconciliation,
        "model_invoked": False, "cfd_invoked": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "credit_boundary": {
            "typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
            "portable_cold_replay_credit": "NOT_CLAIMED",
            "scientific_qualification": "UNKNOWN",
            "historical_result_view": "DEVELOPMENT_METADATA_ONLY",
            "statement": "The actual CURRENT catalog is validated separately; the inherited result's historical relocated hash is admitted only through the explicit dual binding.",
        },
    }
    report["sha256"] = canonical_sha(report)
    _write_new(output, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("producer-report", "proof-request", "proof", "source-contract", "frozen-request", "current-binding", "output"):
        build.add_argument(f"--{name}", type=Path, required=True)
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
                                  frozen_request=args.frozen_request,
                                  current_binding=args.current_binding, output=args.output,
                                  max_wall_seconds=args.max_wall_seconds,
                                  max_result_bytes=args.max_result_bytes)
        else:
            value = run_trial(args.request, output=args.output,
                              parent_pid=args.parent_pid,
                              max_wall_seconds=args.max_wall_seconds)
    except (TypedEvaluatorV2CurrentError, V2.TypedEvaluatorV2Error,
            V2.V1.TypedEvaluatorError, V2.V8.ProofConsumerError,
            OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only evaluator V2 current-bound: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
