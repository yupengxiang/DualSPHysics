"""Metadata-only V64 -> fresh V16 proof/evaluator binding tests.

The fixtures contain tiny JSON/placeholder files only.  They intentionally do
not open native BI4, HDF5, or a large V16 result.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_v65_fresh_v16_proof_request.py"


def _load():
    spec = importlib.util.spec_from_file_location("f2_v65_fresh_proof_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(module, value):
    return module.canonical_sha(value)


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    else:
        path.write_bytes(value)
    return path


def _source_contract(module, path: Path, current_sha: str, runtime_sha: str) -> Path:
    expected = {
        "case_identity": {"family_id": "F2", "current_case_index": 78},
        "cohort": {"identity_key": "(Zone,Idp)", "selected_count": 1,
                    "identity_sha256": "1" * 64},
        "initial_mass_denominator": {"denominator_kg": 1.0,
                                      "initial_missing_mass_kg": 0.0,
                                      "later_missing_mass_kg": 0.0,
                                      "later_missing_unique_count": 0},
        "time": {"first_s": 0.0, "last_s": 1.0, "frame_count": 2,
                 "tolerance_s": 0.0, "observer_profile_sha256": "2" * 64},
        "observer_fields": [],
        "events": {"require_receiver_labels": True,
                    "require_residence_semantics": True,
                    "require_total_net_interval": True,
                    "require_unknown_recross": True,
                    "status_vocabulary": ["observed"]},
        "source_binding": {
            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND",
            "actual_current_catalog_sha256": current_sha,
            "current_catalog_sha256": runtime_sha,
            "runtime_view_sha256": runtime_sha,
            "source_files": {"current_catalog": current_sha},
        },
    }
    value = {
        "schema": "ds02.stage2.f2-fresh-v16-source-contract.v65",
        "expected": expected,
        "quality": dict(module.UNKNOWN),
        "current_catalog_provenance": {
            "actual_current_catalog": {"sha256": current_sha},
            "relocated_runtime_view": {"sha256": runtime_sha},
        },
    }
    value["sha256"] = _canonical(module, value)
    return _write(path, value)


def _make_fixture(tmp_path: Path):
    module = _load()
    case = "STAGE2_F2_ROOT179B_V64_FRESH_PROOF_TEST"
    attempt = "f2-root179b-v64-fresh-proof-test-001"
    target = tmp_path / "target"
    products = tmp_path / "products"
    original = tmp_path / "original-source"
    target.mkdir()
    products.mkdir()
    original.mkdir()
    (target / "runtime").mkdir()

    typed = _write(products / "typed-reconstructed.h5", b"tiny typed placeholder")
    v15_result = _write(products / "v15-result.json", b"tiny v15 placeholder")
    v16_result = _write(products / "v16-result.json", b"tiny v16 placeholder")
    nested_request = _write(target / "runtime" / "f2-worker-request.json", b"{\"schema\":\"tiny-worker-request\"}\n")
    current = _write(tmp_path / "CURRENT336.json", b"tiny current manifest fixture")
    current_sha = module.sha256_file(current)
    runtime_sha = "4" * 64
    # The production constant remains the exact df7e identity.  This test
    # substitutes the tiny fixture hash only to avoid reading the 2.5 MB
    # production CURRENT file; stale identity rejection is still exercised.
    module.ACTUAL_CURRENT_SHA = current_sha

    request = {
        "schema": module.V64_REQUEST_SCHEMA, "status": "READY_FOR_PARENT_GUARD",
        "case_id": case, "attempt_id": attempt, "request_id": attempt,
        "v62_provenance": {"case_id": "STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V38_ROOT_060"},
        "fresh_cold_credit": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(module.UNKNOWN),
        "runtime": {"worker_target": str(target / "runtime/worker.py")},
        "storage_scope": {"external_output_root": str(products)},
        "embedded_worker_request": {"current_binding": {
            "path": str(current), "sha256": current_sha,
        }},
    }
    request["sha256"] = _canonical(module, request)
    request_path = _write(tmp_path / "v64-parent-request.json", request)
    nested = {
        "schema": module.V2_REPORT_SCHEMA, "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(nested_request), "sha256": module.sha256_file(nested_request)},
        "qualification": dict(module.UNKNOWN),
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True,
                                "converter_invoked": True, "label_operator_invoked": True,
                                "model_invoked": False, "cfd_invoked": False},
        "typed_output": {"path": str(typed), "sha256": "a" * 64,
                          "bytes": typed.stat().st_size},
        "typed_to_label": {
            "status": "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN",
            "result": str(v15_result), "result_sha256": "9" * 64,
            "v16_forward": {"status": "COMPLETE_DEVELOPMENT_UNKNOWN",
                             "result": str(v16_result), "result_sha256": "8" * 64},
        },
    }
    nested["report_sha256"] = module.report_canonical_sha(nested)
    nested_path = _write(products / "raw-to-typed-to-label-report-v2.json", nested)
    summary = {
        "schema": module.V64_SUMMARY_SCHEMA,
        "status": "COMPLETED_RAW_TYPED_LABEL_UNKNOWN",
        "report_path": str(nested_path),
        "report_file_sha256": module.sha256_file(nested_path),
        "typed_output_report_contract": {"path": str(typed), "sha256": "a" * 64,
                                          "bytes": typed.stat().st_size},
        "execution_boundary": nested["execution_boundary"],
        "model_invoked": False, "cfd_invoked": False,
    }
    report = {
        "schema": module.V64_REPORT_SCHEMA,
        "status": "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN",
        # The V64 runtime stores the request *file* SHA here.  The request's
        # own sha256 field is its canonical-body SHA and is carried separately
        # to exercise the real report/request interface.
        "request": {"path": str(request_path), "sha256": module.sha256_file(request_path),
                     "canonical_sha256": request["sha256"]},
        "parent": {"attempt_id": attempt},
        "executor": {"result": summary},
        "raw_source": {"full_prepost_equal": True},
        "source_closure": {"prepost_equal": True},
        "copy_contract": {"raw_copy_attempts": 0},
        "typed_output_contract": {"path": str(typed), "sha256": "a" * 64,
                                   "bytes": typed.stat().st_size},
        "fresh_cold_credit": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(module.UNKNOWN),
    }
    report_path = _write(tmp_path / "v64-parent-report.json", report)
    contract_path = _source_contract(module, tmp_path / "fresh-source-contract.json",
                                     current_sha, runtime_sha)
    return module, {"case": case, "attempt": attempt, "target": target,
                    "products": products, "original": original,
                    "current": current, "request": request_path,
                    "report": report_path, "contract": contract_path,
                    "current_sha": current_sha, "runtime_sha": runtime_sha,
                    "v16": v16_result}


def test_v64_nested_report_builds_fresh_v8_and_evaluator_metadata(tmp_path):
    module, f = _make_fixture(tmp_path)
    proof = tmp_path / "fresh-proof-v8.json"
    evaluator = tmp_path / "fresh-evaluator-v1.json"
    output = module._build(
        v64_report=f["report"], v64_request=f["request"],
        source_contract=f["contract"], current_manifest=f["current"],
        target_root=f["target"], output_root=f["products"],
        original_roots=[f["original"]], output_proof=proof,
        output_evaluator=evaluator, case_id=f["case"], attempt_id=f["attempt"],
        parent_guard_record=None, trace_audit_request=None,
        max_wall_seconds=900.0, max_result_bytes=100_000_000,
        python_executable=None)
    assert output["payload_read"] is False
    assert output["hdf5_bi4_result_content_read"] is False
    proof_value = json.loads(proof.read_text(encoding="utf-8"))
    eval_value = json.loads(evaluator.read_text(encoding="utf-8"))
    assert proof_value["case_id"] == f["case"]
    assert proof_value["attempt_id"] == f["attempt"]
    assert proof_value["v64_parent_binding"]["current_identity_sha256"] == f["current_sha"]
    assert proof_value["result"]["path"] == str(f["v16"])
    assert proof_value["result"]["content_sha_verified"] is False
    assert proof_value["expected"]["source_binding"]["current_catalog_sha256"] == f["current_sha"]
    assert proof_value["expected"]["source_binding"]["binding_status"] == "EXACT_CURRENT_SOURCE_BOUND"
    assert "runtime_view_sha256" not in proof_value["expected"]["source_binding"]
    assert proof_value["v64_parent_binding"]["relocated_current_view_sha256"] == f["runtime_sha"]
    assert proof_value["v8_consumer"]["sha256"] == module.sha256_file(
        module.V8_SCRIPT)
    assert eval_value["proof_request"]["canonical_sha256"] == proof_value["sha256"]
    assert eval_value["old_proof_reuse"] is False
    assert eval_value["status"] == "DEFERRED_UNTIL_FRESH_PROOF_SUCCESS"


def test_emitted_request_passes_actual_v8_validator_and_staging_preflight(tmp_path):
    module, f = _make_fixture(tmp_path)
    proof = tmp_path / "fresh-proof-v8.json"
    evaluator = tmp_path / "fresh-evaluator-v1.json"
    module._build(
        v64_report=f["report"], v64_request=f["request"],
        source_contract=f["contract"], current_manifest=f["current"],
        target_root=f["target"], output_root=f["products"],
        original_roots=[f["original"]], output_proof=proof,
        output_evaluator=evaluator, case_id=f["case"], attempt_id=f["attempt"],
        parent_guard_record=None, trace_audit_request=None,
        max_wall_seconds=900.0, max_result_bytes=100_000_000,
        python_executable=None)

    # This calls the production V8 validator, not a copied test schema.  V8
    # only stats the tiny placeholder result; it does not read its content.
    v8_preflight = module.validate_emitted_v8_request(proof, verify_result_stat=True)
    assert v8_preflight["status"] == "V8_METADATA_VALIDATED_READY_FOR_PARENT_PROOF"
    assert v8_preflight["case_id"] == f["case"]
    assert v8_preflight["attempt_id"] == f["attempt"]
    assert v8_preflight["current_identity_sha256"] == f["current_sha"]
    assert v8_preflight["relocated_current_view_sha256"] == f["runtime_sha"]
    assert v8_preflight["payload_read"] is False
    staging = module.validate_evaluator_staging(proof, evaluator)
    assert staging["status"] == "DEFERRED_UNTIL_FRESH_V8_PROOF_SUCCESS"
    assert staging["next_guard"]["old_proof_reuse"] is False


@pytest.mark.parametrize("mutation", ["case", "current", "relocated"])
def test_v65_provenance_wrapper_rejects_cross_bound_v8_mutations(tmp_path, mutation):
    module, f = _make_fixture(tmp_path)
    proof = tmp_path / "fresh-proof-v8.json"
    evaluator = tmp_path / "fresh-evaluator-v1.json"
    module._build(
        v64_report=f["report"], v64_request=f["request"],
        source_contract=f["contract"], current_manifest=f["current"],
        target_root=f["target"], output_root=f["products"],
        original_roots=[f["original"]], output_proof=proof,
        output_evaluator=evaluator, case_id=f["case"], attempt_id=f["attempt"],
        parent_guard_record=None, trace_audit_request=None,
        max_wall_seconds=900.0, max_result_bytes=100_000_000,
        python_executable=None)
    value = json.loads(proof.read_text(encoding="utf-8"))
    if mutation == "case":
        value["v64_parent_binding"]["case_id"] = "STAGE2_F2_OTHER_CASE"
    elif mutation == "current":
        value["v64_parent_binding"]["current_identity_sha256"] = module.HISTORICAL_CURRENT_SHA
    else:
        value["v64_parent_binding"]["relocated_current_view_sha256"] = f["current_sha"]
    value["sha256"] = module.canonical_sha(value)
    proof.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(module.V65FreshProofError):
        module.validate_emitted_v8_request(proof, verify_result_stat=True)


def test_v65_rejects_canonical_digest_in_v64_file_sha_slot(tmp_path):
    module, f = _make_fixture(tmp_path)
    report = json.loads(f["report"].read_text(encoding="utf-8"))
    # Deliberately put the request canonical SHA in the file-SHA slot.  The
    # strict V65 interface must reject this even though the fixture's request
    # is otherwise canonical.
    request = json.loads(f["request"].read_text(encoding="utf-8"))
    report["request"]["sha256"] = request["sha256"]
    bad = _write(tmp_path / "bad-report.json", report)
    with pytest.raises(module.V65FreshProofError, match="file SHA"):
        module._build(
            v64_report=bad, v64_request=f["request"],
            source_contract=f["contract"], current_manifest=f["current"],
            target_root=f["target"], output_root=f["products"],
            original_roots=[f["original"]], output_proof=tmp_path / "bad-p.json",
            output_evaluator=tmp_path / "bad-e.json", case_id=f["case"],
            attempt_id=f["attempt"], parent_guard_record=None,
            trace_audit_request=None, max_wall_seconds=900.0,
            max_result_bytes=100_000_000, python_executable=None)


def test_v65_rejects_stale_current_and_historical_result(tmp_path):
    module, f = _make_fixture(tmp_path)
    stale = json.loads(f["contract"].read_text(encoding="utf-8"))
    stale["expected"]["source_binding"]["source_files"]["current_catalog"] = module.HISTORICAL_CURRENT_SHA
    stale["sha256"] = _canonical(module, stale)
    stale_path = _write(tmp_path / "stale-contract.json", stale)
    with pytest.raises(module.V65FreshProofError, match="source_files.current_catalog"):
        module._build(v64_report=f["report"], v64_request=f["request"],
                      source_contract=stale_path, current_manifest=f["current"],
                      target_root=f["target"], output_root=f["products"],
                      original_roots=[f["original"]], output_proof=tmp_path / "p1.json",
                      output_evaluator=tmp_path / "e1.json", case_id=f["case"],
                      attempt_id=f["attempt"], parent_guard_record=None,
                      trace_audit_request=None, max_wall_seconds=900.0,
                      max_result_bytes=100_000_000, python_executable=None)

    bad_nested = json.loads((f["products"] / "raw-to-typed-to-label-report-v2.json").read_text())
    bad_nested["typed_to_label"]["v16_forward"]["result_sha256"] = next(iter(module.OLD_V16_RESULT_SHAS))
    bad_nested["report_sha256"] = module.report_canonical_sha(bad_nested)
    _write(f["products"] / "raw-to-typed-to-label-report-v2.json", bad_nested)
    # Update only the report-file digest in a fresh parent report.  This is a
    # distinct output namespace, so the positive fixture remains untouched.
    fresh = tmp_path / "bad-result"
    fresh.mkdir()
    # The builder reaches the result-SHA rejection after the same report path
    # checks; no payload content is opened.
    summary = json.loads(f["report"].read_text())
    summary["executor"]["result"]["report_file_sha256"] = module.sha256_file(f["products"] / "raw-to-typed-to-label-report-v2.json")
    report_path = _write(fresh / "report.json", summary)
    with pytest.raises(module.V65FreshProofError, match="historical proof/result SHA"):
        module._build(v64_report=report_path, v64_request=f["request"],
                      source_contract=f["contract"], current_manifest=f["current"],
                      target_root=f["target"], output_root=f["products"],
                      original_roots=[f["original"]], output_proof=fresh / "p2.json",
                      output_evaluator=fresh / "e2.json", case_id=f["case"],
                      attempt_id=f["attempt"], parent_guard_record=None,
                      trace_audit_request=None, max_wall_seconds=900.0,
                      max_result_bytes=100_000_000, python_executable=None)


def test_v65_rejects_case_reuse_before_writing_outputs(tmp_path):
    module, f = _make_fixture(tmp_path)
    request = json.loads(f["request"].read_text())
    request["case_id"] = request["v62_provenance"]["case_id"]
    request["sha256"] = _canonical(module, request)
    reused_request = _write(tmp_path / "reused-request.json", request)
    with pytest.raises(module.V65FreshProofError, match="historical marker|equals historical|case/attempt differs"):
        module._build(v64_report=f["report"], v64_request=reused_request,
                      source_contract=f["contract"], current_manifest=f["current"],
                      target_root=f["target"], output_root=f["products"],
                      original_roots=[f["original"]], output_proof=tmp_path / "p3.json",
                      output_evaluator=tmp_path / "e3.json", case_id=f["case"],
                      attempt_id=f["attempt"], parent_guard_record=None,
                      trace_audit_request=None, max_wall_seconds=900.0,
                      max_result_bytes=100_000_000, python_executable=None)
