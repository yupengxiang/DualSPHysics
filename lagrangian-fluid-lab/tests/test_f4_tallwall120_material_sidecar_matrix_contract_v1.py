from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.f4_tallwall120_material_sidecar_matrix_contract_v1 import (
    COLLECTION_MANIFEST,
    DEFAULT_OUTPUT_NAMESPACE,
    EXPECTED_CASE_COUNT,
    EXPECTED_CASE_IDS,
    EXPECTED_CASE_SPLITS,
    EXPECTED_EVENT_WINDOW_S,
    EXPECTED_RELIABLE_COVERAGE_MIN,
    EXPECTED_RIGHT_CENSOR_STATUS,
    EXPECTED_UNKNOWN_FRACTION_MAX,
    MATERIAL_SIDECAR_SCHEMA,
    PROPOSAL_REPORT,
    build_report,
    evaluate_matrix,
    load_inputs,
    validate_report,
    verify_report,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/F4-TALLWALL120-MATERIAL-SIDECAR-MATRIX-CONTRACT-V1-2026-09-28.json"


@pytest.fixture()
def inputs() -> dict[str, dict]:
    return load_inputs(ROOT)


def _manifest_sha() -> str:
    return hashlib.sha256((ROOT / COLLECTION_MANIFEST).read_bytes()).hexdigest()


def _evaluate(inputs: dict[str, dict], sidecars=None) -> dict:
    return evaluate_matrix(
        inputs["collection"],
        inputs["proposal"],
        inputs["reader"],
        inputs["consistency_audit"],
        inputs["terminal_intake"],
        inputs["acceptance_bridge"],
        sidecars=sidecars,
        collection_manifest_sha256=_manifest_sha(),
    )


def _sidecar(inputs: dict[str, dict], case_id: str, **overrides) -> dict:
    row = next(row for row in inputs["collection"]["cases"] if row["case_id"] == case_id)
    source_path = row["trajectory"]["path"].replace("archives-v1", "archives-v2")
    source_sha = row["trajectory"]["sha256"]
    if case_id == EXPECTED_CASE_IDS[7]:
        source_sha = inputs["proposal"]["target"]["source_sha256"]
    result = {
        "schema": MATERIAL_SIDECAR_SCHEMA,
        "family": "F4",
        "scope_id": "F4_resting_pool_laminar_tallwall120_x_v1",
        "case_id": case_id,
        "split": EXPECTED_CASE_SPLITS[case_id],
        "source": {"hdf5": source_path, "sha256": source_sha},
        "output": {
            "namespace": f"{DEFAULT_OUTPUT_NAMESPACE.as_posix()}/{case_id}",
            "fresh": True,
            "overwrite_allowed": False,
        },
        "terminal": {
            "status": "complete",
            "execution_complete": True,
            "event_window_complete": True,
            "event_window_s": EXPECTED_EVENT_WINDOW_S,
            "right_censor_status": EXPECTED_RIGHT_CENSOR_STATUS,
        },
        "material_markers": {
            "mass_closure": {"error": 0.0},
            "unknown_fraction": {"max": 0.0},
            "reliable_coverage": {"fraction": EXPECTED_RELIABLE_COVERAGE_MIN},
            "right_censor_status": EXPECTED_RIGHT_CENSOR_STATUS,
        },
        "claims": {
            "formal": False,
            "formal_eligible": False,
            "qualification": False,
            "T1": False,
            "T2": False,
            "credit": 0,
            "qualification_credit": 0,
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result


def test_fixed_32_case_denominator_and_split_matrix_are_bound(inputs):
    report = _evaluate(inputs)
    assert report["fixed_matrix"]["case_count"] == EXPECTED_CASE_COUNT
    assert report["matrix_summary"]["observed_collection_case_count"] == EXPECTED_CASE_COUNT
    assert report["matrix_summary"]["split_counts_observed"] == {
        "train": 16,
        "validation": 4,
        "id_test": 6,
        "ood_test": 6,
    }
    assert report["matrix_summary"]["denominator_complete"] is True
    assert report["material_sidecars"]["missing_case_ids"] == list(EXPECTED_CASE_IDS)
    assert "missing_or_incomplete_material_sidecars" in report["blocking_reasons"]


def test_missing_and_duplicate_manifest_cases_fail_closed(inputs):
    mutated = copy.deepcopy(inputs)
    mutated["collection"]["cases"] = mutated["collection"]["cases"][:-1]
    mutated["collection"]["cases"].append(copy.deepcopy(mutated["collection"]["cases"][0]))
    report = _evaluate(mutated)
    assert report["matrix_summary"]["denominator_complete"] is False
    assert "missing_or_duplicate_cases" in report["blocking_reasons"]
    fixed_check = next(item for item in report["checks"] if item["check"] == "fixed_32_case_denominator")
    assert fixed_check["passed"] is False


def test_split_drift_is_a_matrix_blocker(inputs):
    mutated = copy.deepcopy(inputs)
    mutated["collection"]["cases"][0]["split"] = "train"
    report = _evaluate(mutated)
    assert "split_drift" in report["blocking_reasons"]
    assert report["matrix_summary"]["split_counts_observed"]["train"] == 17
    assert report["matrix_summary"]["split_counts_observed"]["ood_test"] == 5


def test_archives_reader_and_consistency_drift_remain_visible(inputs):
    report = _evaluate(inputs)
    assert "archives_v1_v2_source_drift" in report["blocking_reasons"]
    assert "reader_manifest_sha_drift" in report["blocking_reasons"]
    assert "archives_v1_v2_receipt_drift" in report["blocking_reasons"]
    assert report["source_binding"]["dev07"]["archives_v1_v2_drift"] is True
    assert report["source_binding"]["reader"]["sha256_exact"] is False


def test_partial_and_right_censored_sidecar_fail_closed(inputs):
    sidecar = _sidecar(
        inputs,
        EXPECTED_CASE_IDS[7],
        terminal={
            "status": "partial",
            "execution_complete": False,
            "event_window_complete": False,
            "event_window_s": 4.340002980805959,
            "right_censor_status": "right_censored_or_unresolved",
        },
        material_markers={
            "unknown_fraction": {"max": EXPECTED_UNKNOWN_FRACTION_MAX + 0.5},
            "reliable_coverage": {"fraction": 0.0},
            "right_censor_status": "right_censored_or_unresolved",
        },
    )
    report = _evaluate(inputs, [sidecar])
    case = report["material_sidecars"]["cases"][7]
    assert case["status"] == "blocked"
    assert "partial_or_missing_terminal_event_window" in case["blocking_reasons"]
    assert "right_censored_or_unresolved" in case["blocking_reasons"]
    assert "missing_required_material_markers" in report["blocking_reasons"]
    assert case["material_markers"]["reliable_coverage_pass"] is False


def test_wrong_sidecar_source_is_rejected_even_with_complete_markers(inputs):
    sidecar = _sidecar(inputs, EXPECTED_CASE_IDS[7])
    sidecar["source"]["hdf5"] = sidecar["source"]["hdf5"].replace("archives-v2", "archives-v1")
    report = _evaluate(inputs, [sidecar])
    case = report["material_sidecars"]["cases"][7]
    assert case["status"] == "blocked"
    assert "sidecar_source_path" in [item["check"] for item in case["checks"] if not item["passed"]]


def test_formal_or_credit_claims_never_mint_credit(inputs):
    sidecar = _sidecar(
        inputs,
        EXPECTED_CASE_IDS[7],
        claims={"formal": True, "credit": 1, "qualification_credit": 1},
    )
    report = _evaluate(inputs, [sidecar])
    case = report["material_sidecars"]["cases"][7]
    assert case["credit"] == 0
    assert "formal_or_credit_claim_present" in case["blocking_reasons"]
    assert report["qualification"]["T1"] is False
    assert report["qualification"]["T2"] is False
    assert report["qualification"]["credit"] == 0


def test_report_binding_and_execution_boundary_are_zero_authority():
    report = build_report(ROOT)
    assert validate_report(report) == []
    assert json.loads(REPORT.read_text(encoding="utf-8")) == report
    assert verify_report(REPORT, ROOT) == report
    assert report["status"] == "blocked_fail_closed"
    assert report["decision"] == "diagnostic_proposal_contract_only"
    assert report["qualification"]["credit"] == 0
    assert report["qualification"]["formal"] is False
    assert report["execution_controls"]["production_hdf5_opened"] is False
    assert report["execution_controls"]["solver_started"] is False
    assert report["execution_controls"]["worker_started"] is False
    assert report["execution_controls"]["gpu_started"] is False
    assert report["execution_controls"]["queue_started"] is False
