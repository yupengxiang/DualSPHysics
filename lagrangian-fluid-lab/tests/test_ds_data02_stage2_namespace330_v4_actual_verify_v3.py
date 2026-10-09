from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_namespace330_v4_actual_verify_v3.py"
SPEC = importlib.util.spec_from_file_location("namespace330_verify_v3_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REAL_PRODUCT = (
    ROOT / "campaigns" / "ds-data-02" / "stage2" / "lineage"
    / "v30-namespace330-v4-root300-actual279-001"
)


def _proof(tmp_path: Path, name: str, row: dict) -> dict[str, str]:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({
        "schema": "ds02.stage2.mass-proof.v1",
        "scope_id": name,
        "status": "COMPLETED",
        "newly_bound_cases": [row],
    }, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "role": f"mass_proof_{name}",
        "path": str(path),
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _completed_row(case_id: str, *, total: float = 1.5) -> dict:
    return {
        "physical_case_id": case_id,
        "status": "COMPLETED",
        "selected_typed_initial_mass": {
            "selected_typed_initial_mass_sum_kg": 1.25,
            "selected_typed_initial_mass_count": 2,
            "selected_typed_initial_mass_status": "COMPLETED",
            "selected_exclusion_mass_kg": 0.25,
        },
        "case_total_initial_mass_kg": total,
        "expected_case_total_initial_mass_kg": total,
        "mass_match": True,
    }


def test_multi_file_mass_join_keeps_selected_and_whole_case_fields_separate(tmp_path: Path) -> None:
    refs = [
        _proof(tmp_path, "mass-a", _completed_row("CASE_A")),
        _proof(tmp_path, "mass-b", _completed_row("CASE_B", total=2.5)),
    ]
    result = MODULE.validate_mass_proof_inputs(refs, {"CASE_A", "CASE_B", "CASE_C"})

    assert result["summary"] == {
        "proof_count": 2,
        "proofs_with_case_rows": 2,
        "matching_case_rows": 2,
        "unmatched_case_rows": 0,
        "unscoped_top_level_proofs": 0,
    }
    case_a = result["observations"]["CASE_A"]
    assert case_a["selected_initial_mass_sum_kg"] == 1.25
    assert case_a["selected_initial_mass_count"] == 2
    assert case_a["case_total_initial_mass_kg"] == 1.5
    assert case_a["initial_mass_kg"] == 1.5
    assert result["observations"]["CASE_C"]["status"] == "UNKNOWN_NO_EXACT_CASE_ROW"


def test_failed_mass_row_preserves_null_whole_case_mass(tmp_path: Path) -> None:
    refs = [_proof(tmp_path, "mass-failed", {
        "physical_case_id": "CASE_A",
        "status": "FAILED_REQUIRES_NEW_ATTEMPT",
        "selected_typed_initial_mass": {
            "selected_typed_initial_mass_status": "UNKNOWN",
        },
    })]
    result = MODULE.validate_mass_proof_inputs(refs, {"CASE_A"})
    observation = result["observations"]["CASE_A"]

    assert observation["status"] == "FAILED_OR_UNKNOWN"
    assert observation["initial_mass_kg"] is None
    assert observation["case_total_initial_mass_kg"] is None
    assert observation["mass_match"] is None


def test_conflicting_mass_rows_fail_closed(tmp_path: Path) -> None:
    refs = [
        _proof(tmp_path, "mass-a", _completed_row("CASE_A", total=1.5)),
        _proof(tmp_path, "mass-b", _completed_row("CASE_A", total=1.6)),
    ]
    with pytest.raises(MODULE.Namespace330V4DynamicVerificationError, match="conflicting mass proofs"):
        MODULE.validate_mass_proof_inputs(refs, {"CASE_A"})


def test_duplicate_mass_role_path_sha_is_rejected(tmp_path: Path) -> None:
    ref = _proof(tmp_path, "mass-a", _completed_row("CASE_A"))
    duplicate = dict(ref)
    with pytest.raises(MODULE.Namespace330V4DynamicVerificationError, match="duplicated"):
        MODULE.validate_mass_proof_inputs([ref, duplicate], {"CASE_A"})


def test_failed_attempt_can_precede_one_successful_retry_without_pending_credit() -> None:
    plan_rows = [
        {
            "physical_case_id": "CASE_A",
            "status": "COMPLETED",
            "actual_saved_mask_coverage": True,
            "attempt_lineage": [
                {"producer_id": "failed-a", "attempt_id": "attempt-a-1"},
                {"producer_id": "success-a", "attempt_id": "attempt-a-2"},
            ],
            "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN",
            "historical_alias": "NONE",
            "scientific_credit": "NONE",
        },
        {
            "physical_case_id": "CASE_B",
            "status": "FAILED_REQUIRES_NEW_ATTEMPT",
            "actual_saved_mask_coverage": False,
            "attempt_lineage": [],
            "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN",
            "historical_alias": "NONE",
            "scientific_credit": "NONE",
        },
        {
            "physical_case_id": "CASE_C",
            "status": "READY_FOR_PARENT_GUARD",
            "actual_saved_mask_coverage": False,
            "attempt_lineage": [],
            "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN",
            "historical_alias": "NONE",
            "scientific_credit": "NONE",
        },
    ]
    producers = [
        {"producer_id": "failed-a", "attempt_id": "attempt-a-1",
         "status": "FAILED_PARENT_EXECUTOR", "case_ids": ["CASE_A"]},
        {"producer_id": "success-a", "attempt_id": "attempt-a-2",
         "status": "COMPLETED", "case_ids": ["CASE_A"]},
        {"producer_id": "retry-b", "attempt_id": "attempt-b-2",
         "status": "RUNNING_NO_CREDIT", "case_ids": ["CASE_B"]},
    ]

    result = MODULE.validate_lifecycle_retry_metadata(plan_rows, producers)

    assert result["actual_ids"] == {"CASE_A"}
    assert result["failed_ids"] == {"CASE_B"}
    assert result["inflight_ids"] == {"CASE_C"}
    assert result["derived_coverage"]["pending_no_credit_cases"] == 1
    assert result["derived_coverage"]["failed_requires_new_attempt_cases"] == 1
    assert result["successful_case_to_producer"] == {"CASE_A": "success-a"}


def test_two_successful_retry_producers_for_one_case_are_rejected() -> None:
    plan_rows = [{
        "physical_case_id": "CASE_A",
        "status": "COMPLETED",
        "actual_saved_mask_coverage": True,
        "attempt_lineage": [{"producer_id": "success-a"}],
    }]
    producers = [
        {"producer_id": "success-a", "status": "COMPLETED", "case_ids": ["CASE_A"]},
        {"producer_id": "success-b", "status": "COMPLETED", "case_ids": ["CASE_A"]},
    ]
    with pytest.raises(MODULE.Namespace330V4DynamicVerificationError, match="two successful"):
        MODULE.validate_lifecycle_retry_metadata(plan_rows, producers)


@pytest.mark.skipif(not REAL_PRODUCT.is_dir(), reason="ROOT300 metadata product is not present")
def test_v3_runs_against_current_root300_metadata_product() -> None:
    report = MODULE.verify_namespace330_v4_dynamic(REAL_PRODUCT)
    assert report["schema"].endswith("verification.v3")
    assert report["coverage"]["actual_saved_mask_cases"] == 279
    assert report["coverage"]["current_cases"] == 336
    assert report["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert report["read_scope"]["payload_opened"] is False
