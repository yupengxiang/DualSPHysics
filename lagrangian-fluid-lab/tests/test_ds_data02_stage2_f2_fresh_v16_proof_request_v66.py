"""Source-only tests for the ROOT179C V66 -> ROOT190 V8 bridge.

These fixtures exercise the real top-level V64 report shape and the separate
worker summary/nested report shape.  All files are tiny JSON/placeholders; no
native BI4, HDF5, or large result content is opened by the test.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_request_v66.py"


def _load():
    spec = importlib.util.spec_from_file_location("f2_v66_fresh_proof_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    else:
        path.write_bytes(value)
    return path


def _source_contract(module, path: Path, current_sha: str) -> Path:
    expected = {
        "case_identity": {"family_id": "F2", "current_case_index": 78},
        "cohort": {"identity_key": "(Zone,Idp)", "selected_count": 1,
                    "identity_sha256": "1" * 64},
        "initial_mass_denominator": {"denominator_kg": 1.0,
                                      "initial_missing_mass_kg": 0.0,
                                      "later_missing_mass_kg": 0.0,
                                      "later_missing_unique_count": 0},
        "time": {"first_s": 0.0, "last_s": 1.0, "frame_count": 2,
                 "tolerance_s": 0.01},
        "observer_fields": [],
        "events": {"require_receiver_labels": True,
                    "require_residence_semantics": True,
                    "require_total_net_interval": True,
                    "require_unknown_recross": True,
                    "status_vocabulary": ["observed"]},
        "source_binding": {
            "binding_status": "EXACT_CURRENT_SOURCE_BOUND",
            "current_catalog_sha256": current_sha,
            "source_files": {"current_catalog": current_sha},
        },
    }
    value = {
        "schema": "ds02.stage2.f2-fresh-v16-source-contract.v65",
        "role": "DEVELOPMENT", "quality": dict(module.UNKNOWN),
        "expected": expected,
        "original_roots": [str(path.parent / "original")],
    }
    value["sha256"] = module.canonical_sha(value)
    return _write(path, value)


def _fixture(tmp_path: Path, *, forbidden_result: bool = False):
    module = _load()
    current = _write(tmp_path / "CURRENT336.json", b"tiny current manifest")
    current_sha = hashlib.sha256(current.read_bytes()).hexdigest()
    module.ACTUAL_CURRENT_SHA = current_sha

    producer_target = tmp_path / "producer" / "bundle-target"
    producer_output = tmp_path / "producer" / "products"
    producer_target.mkdir(parents=True)
    producer_output.mkdir(parents=True)
    original = tmp_path / "original"
    original.mkdir()

    nested_request = _write(producer_target / "runtime" / "worker-request.json",
                             b'{"schema":"tiny-worker-request"}\n')
    typed = _write(producer_output / "typed-reconstructed.h5", b"tiny typed")
    v15 = _write(producer_output / "v15-result.json", b"tiny v15")
    v16 = _write(producer_output / "v16-result.json", b"tiny v16")
    result_sha = "2b71dcb5370b9cdbd745ece877e892a6f30871207e9351c102cfb9720422fb47" if forbidden_result else "9" * 64

    request = {
        "schema": module.PARENT_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "case_id": "STAGE2_F2_V66_PRODUCER_FIXTURE",
        "attempt_id": "f2-v66-producer-fixture-001",
        "fresh_cold_credit": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(module.UNKNOWN),
        "embedded_worker_request": {"current_binding": {
            "path": str(current), "sha256": current_sha,
        }},
    }
    request["sha256"] = module.canonical_sha(request)
    request_path = _write(tmp_path / "producer-request.json", request)
    receipt = {
        "request": {"path": str(request_path), "sha256": module.sha256_file(request_path)},
        "accounting": {"charge_id": "f2-v66-producer-fixture-001::charge",
                        "reservation_id": "f2-v66-producer-fixture-001::reservation"},
    }
    receipt_path = _write(tmp_path / "execution-receipt.json", receipt)
    report = {
        "schema": module.PARENT_REPORT_SCHEMA,
        "status": "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN",
        "request_sha256": module.sha256_file(request_path),
        "report_path": str(receipt_path), "raw_opened": True, "hdf5_opened": True,
        "raw_copy_attempts": 0, "qualification": dict(module.UNKNOWN),
        "charge": {"charge": {"id": "f2-v66-producer-fixture-001::charge",
                               "status": "completed"}},
    }
    report_path = _write(tmp_path / "actual-returned-parent-report.json", report)
    summary = {
        "schema": module.SUMMARY_SCHEMA, "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "report_path": "PLACEHOLDER", "raw_copy_attempts": 0,
        "raw_tree_before_sha256": "a" * 64, "raw_tree_after_sha256": "a" * 64,
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True,
                                "converter_invoked": True, "label_operator_invoked": True,
                                "model_invoked": False, "cfd_invoked": False},
        "typed_output_report_contract": {"path": str(typed), "sha256": "b" * 64,
                                          "bytes": typed.stat().st_size},
    }
    nested = {
        "schema": module.NESTED_SCHEMA, "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "qualification": dict(module.UNKNOWN),
        "request": {"path": str(nested_request), "sha256": module.sha256_file(nested_request)},
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True,
                                "converter_invoked": True, "label_operator_invoked": True,
                                "model_invoked": False, "cfd_invoked": False},
        "typed_output": {"path": str(typed), "sha256": "b" * 64,
                          "bytes": typed.stat().st_size},
        "typed_to_label": {"status": "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN",
                            "result": str(v15), "result_sha256": "c" * 64,
                            "v16_forward": {"status": "COMPLETE_DEVELOPMENT_UNKNOWN",
                                             "result": str(v16), "result_sha256": result_sha}},
    }
    nested["report_sha256"] = module.report_canonical_sha(nested)
    nested_path = _write(producer_output / "nested-report.json", nested)
    summary["report_path"] = str(nested_path)
    summary["report_file_sha256"] = module.sha256_file(nested_path)
    summary_path = _write(producer_output / "worker-summary.json", summary)
    contract_path = _source_contract(module, tmp_path / "source-contract.json", current_sha)
    return module, {
        "current": current, "request": request_path, "report": report_path,
        "receipt": receipt_path, "summary": summary_path, "nested": nested_path,
        "target": producer_target, "products": producer_output, "original": original,
        "contract": contract_path, "v16": v16, "current_sha": current_sha,
    }


def _build(module, f, tmp_path):
    return module.build_requests(
        parent_request=f["request"], parent_report=f["report"], parent_receipt=f["receipt"],
        worker_summary=f["summary"], nested_report=f["nested"], current_manifest=f["current"],
        source_contract=f["contract"], producer_target_root=f["target"],
        producer_output_root=f["products"], original_roots=[f["original"]],
        output_source_contract=tmp_path / "root190-source-contract.json",
        output_proof=tmp_path / "root190-proof-request.json",
        output_evaluator=tmp_path / "root190-evaluator-request.json",
        case_id="STAGE2_F2_ROOT190_V66_PROOF_FIXTURE",
        attempt_id="f2-root190-v66-proof-fixture-001",
        fresh_output_root=tmp_path / "root190-proof-output",
    )


def test_real_v64_shape_builds_and_passes_v8_metadata_validation(tmp_path):
    module, fixture = _fixture(tmp_path)
    result = _build(module, fixture, tmp_path)
    assert result["status"] == "READY_FOR_PARENT_V8_PROOF"
    assert result["payload_read"] is False
    proof_path = Path(result["proof_request"])
    validated = module.validate_emitted_v8_request(proof_path)
    assert validated["status"] == "V8_METADATA_VALIDATED_READY_FOR_PARENT_PROOF"
    assert validated["producer_case_id"] != validated["case_id"]
    assert validated["result"]["content_sha_verified"] is False
    proof_value = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof_value["fresh_proof_namespace"]["is_new"] is True
    assert proof_value["relocation"]["output_root"] == str(tmp_path / "root190-proof-output")
    expected_source = json.loads(proof_path.read_text(encoding="utf-8"))["expected"]["source_binding"]
    assert "relocated_current_view_sha256" not in expected_source
    # Exercise the actual V8 source/result comparison entry point with the
    # result-facing source contract.  Relocation provenance is carried by the
    # bridge sidecar, not injected into the producer result schema.
    module.V8._validate_source_binding({"source_binding": expected_source}, expected_source)


def test_supplied_current_must_be_the_producer_bound_current(tmp_path):
    module, fixture = _fixture(tmp_path)
    wrong = _write(tmp_path / "wrong-current.json", b"different")
    with pytest.raises(module.V66FreshProofError, match="CURRENT manifest differs"):
        module.build_requests(
            parent_request=fixture["request"], parent_report=fixture["report"],
            parent_receipt=fixture["receipt"], worker_summary=fixture["summary"],
            nested_report=fixture["nested"], current_manifest=wrong,
            source_contract=fixture["contract"], producer_target_root=fixture["target"],
            producer_output_root=fixture["products"], original_roots=[fixture["original"]],
            output_source_contract=tmp_path / "bad-source.json",
            output_proof=tmp_path / "bad-proof.json", output_evaluator=tmp_path / "bad-eval.json",
            case_id="STAGE2_F2_ROOT190_V66_PROOF_FIXTURE",
            attempt_id="f2-root190-v66-proof-fixture-001",
        )


def test_forbidden_historical_result_sha_is_rejected(tmp_path):
    module, fixture = _fixture(tmp_path, forbidden_result=True)
    with pytest.raises(module.V66FreshProofError, match="forbidden historical proof SHA"):
        _build(module, fixture, tmp_path)
