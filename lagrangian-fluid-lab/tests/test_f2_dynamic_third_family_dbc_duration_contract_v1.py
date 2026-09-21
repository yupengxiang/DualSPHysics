from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
CARD = LAB / "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-candidate-card-v1.json"
MATRIX = LAB / "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-matrix-v1.json"
DENOMINATOR = LAB / "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-failure-denominator-v1.json"
REVIEW = LAB / "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-root-review-draft-v1.json"
LINEAGE = LAB / "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-lineage-clarification-v1.json"
PREPARED = LAB / "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-q0p75-preflight-v1/prepared.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_candidate_card_binds_real_preflight_and_keeps_dynamic_scope() -> None:
    card = _load(CARD)
    assert card["status"] == "candidate_handoff_root_review_only"
    assert card["qualification_claim"].startswith("none;")
    assert card["third_family_role"]["candidate_family"] == "F2"
    assert card["third_family_role"]["dynamic_mechanism_required"] is True
    assert card["third_family_role"]["static_hold_excluded"] is True
    assert card["lineage_clarification"]["static_v3_role"].startswith("source lattice")
    assert card["lineage_clarification"]["dynamic_baseline_role"].startswith("same cup")
    assert LINEAGE.is_file()
    assert _sha256(LINEAGE) == card["lineage_clarification"]["sha256"]
    assert card["physical_scope"]["motion"]["anchor_q"] == 0.75
    assert card["physical_scope"]["motion"]["anchor_target_time_s"] == 1.525
    assert card["physical_scope"]["geometry_lineage"]["relative_to_static_v3_source"]["physical_geometry_changed"] is True
    assert card["physical_scope"]["geometry_lineage"]["relative_to_dynamic_dbc_baseline"]["physical_geometry_changed"] is False
    assert card["single_change"]["same_input_retry"] is False
    assert card["single_change"]["threshold_change"] is False
    assert card["single_change"]["static_source_is_not_single_change_baseline"] is True

    adapter = LAB / card["preflight"]["adapter"]["path"]
    manifest = LAB / card["preflight"]["prepared_manifest"]["path"]
    assert adapter.is_file()
    assert manifest.is_file()
    assert _sha256(adapter) == card["preflight"]["adapter"]["sha256"]
    assert _sha256(manifest) == card["preflight"]["prepared_manifest"]["sha256"]
    assert card["preflight"]["execution_controls"] == {
        "solver_invoked": False,
        "gpu_invoked": False,
        "central_queue_mutation": 0,
        "central_ledger_mutation": 0,
        "central_registry_mutation": 0,
    }


def test_matrix_is_fixed_15_rows_with_new_case_identity_and_duration_mapping() -> None:
    matrix = _load(MATRIX)
    cells = matrix["cells"]
    assert matrix["denominator"] == 15
    assert matrix["numerator"] == 0
    assert matrix["execution_controls"]["materialized_cells"] == 0
    assert matrix["lineage_clarification"]["sha256"] == _sha256(LINEAGE)
    assert matrix["fixed_recipe"]["geometry_changed_relative_to_static_source"] is True
    assert matrix["fixed_recipe"]["geometry_changed_relative_to_dynamic_baseline"] is False
    assert len(cells) == 15
    assert [cell["index"] for cell in cells] == list(range(15))
    assert len({cell["case_id"] for cell in cells}) == 15
    assert all(cell["case_id"].startswith("CORE_F2_DYNAMIC_THIRD_DBC_DURATION_") for cell in cells)

    for cell in cells:
        expected_duration = 0.50 + 0.70 * cell["q"]
        assert abs(cell["rotation_duration_s"] - expected_duration) < 1e-12
        assert cell["status"] == "not_started"

    kinds = [cell["row_kind"] for cell in cells]
    assert kinds.count("spatial_anchor") == 9
    assert kinds.count("spatial_held_out") == 4
    assert kinds.count("temporal_internal_time") == 1
    assert kinds.count("temporal_native_output") == 1
    assert matrix["anchor_preflight"]["matrix_cell_credit"] == 0
    assert matrix["anchor_preflight"]["prepared_manifest_sha256"] == _sha256(PREPARED)
    assert matrix["anchor_preflight"]["geometry_changed_relative_to_static_source"] is True
    assert matrix["anchor_preflight"]["geometry_changed_relative_to_dynamic_baseline"] is False
    assert matrix["anchor_preflight"]["case_id"] not in {cell["case_id"] for cell in cells}


def test_failure_denominator_preserves_prior_dynamic_failures_without_credit() -> None:
    record = _load(DENOMINATOR)
    assert record["lineage_clarification"]["sha256"] == _sha256(LINEAGE)
    matrix = record["matrix"]
    assert matrix["fixed_denominator"] == 15
    assert matrix["executed"] == 0
    assert matrix["passed"] == 0
    assert matrix["failed"] == 0
    assert matrix["unattempted"] == 15
    assert matrix["preflight_anchor_credit"] == 0
    assert matrix["canary_reuse_credit"] == 0

    evidence = {item["id"]: item for item in record["historical_evidence"]}
    assert evidence["dbc_q0p5_5s_right_censored"]["hard_integrity_pass"] is True
    assert evidence["dbc_q0p5_5s_right_censored"]["event_window_complete"] is False
    assert evidence["dbc_q1p0_5s_right_censored"]["terminal_speed_p95_m_s"] > 0.1
    assert evidence["moving_mdbc_contact_failure"]["hard_integrity_pass"] is False
    assert evidence["open_tray_position_loss"]["native_missing_fluid_count"] == 16038
    assert evidence["q0p75_cpu_anchor_preflight"]["solver_product_present"] is False
    assert evidence["q0p75_cpu_anchor_preflight"]["geometry_changed_relative_to_static_source"] is True
    assert evidence["q0p75_cpu_anchor_preflight"]["geometry_changed_relative_to_dynamic_baseline"] is False
    assert "static hold" in record["rules"]["static_exclusion"]
    assert "no horizon extension" in record["rules"]["event_censor"]
    assert "same prepared input" in record["rules"]["same_input_retry"]

    for item in record["historical_evidence"]:
        path = LAB / item["path"]
        assert path.is_file(), item["path"]
        assert _sha256(path) == item["sha256"], item["path"]


def test_root_review_is_pending_and_cannot_authorize_solver_or_central_mutation() -> None:
    review = _load(REVIEW)
    assert review["status"] == "draft_pending_root_review"
    assert review["approval"]["root_approval_present"] is False
    assert review["approval"]["solver_launch_allowed_by_this_draft"] is False
    assert review["approval"]["gpu_launch_allowed_by_this_draft"] is False
    assert review["approval"]["queue_mutation_by_this_draft"] == 0
    assert review["approval"]["ledger_mutation_by_this_draft"] == 0
    assert review["approval"]["registry_mutation_by_this_draft"] == 0
    step3 = review["requested_decision_sequence"][2]
    assert step3["action"].startswith("issue a separate root approval")
    assert step3["allowed_by_this_draft"] is False
    assert review["failure_handling"]["all_rows_required"] is True
    assert any(item["path"].endswith("lineage-clarification-v1.json") for item in review["review_inputs"])
    assert any("physical_geometry_changed=false" in item for item in review["why_executable"])
    assert "do not update the Core registry" in review["explicit_non_actions"]
    assert "do not call the static hold a third dynamic mechanism" in review["explicit_non_actions"]


def test_cpu_preflight_manifest_has_closed_hashes_and_no_solver_product() -> None:
    card = _load(CARD)
    prepared = _load(PREPARED)
    assert prepared["preflight_pass"] is True
    assert prepared["qualification_only"] is True
    assert prepared["config"]["scope_id"] == "F2_dynamic_third_family_dbc_duration_x_v1"
    assert prepared["config"]["parameter"]["q"] == 0.75
    assert prepared["config"]["parameter"]["value"] == 1.025
    assert prepared["config"]["boundary_method"] == 1
    assert prepared["config"]["physical_geometry_changed"] is False
    assert prepared["config"]["catchment"]["physical_geometry_changed"] is True
    assert prepared["third_family_preflight"]["geometry_changed_relative_to_static_source"] is True
    assert prepared["third_family_preflight"]["geometry_changed_relative_to_dynamic_baseline"] is False
    assert prepared["lineage_clarification"]["sha256"] == _sha256(LINEAGE)
    assert prepared["config"]["time_max_s"] == 5.0
    assert prepared["third_family_preflight"]["motion_complete_s"] == 1.525
    assert prepared["third_family_preflight"]["solver_invoked"] is False
    assert prepared["third_family_preflight"]["gpu_invoked"] is False
    assert prepared["third_family_preflight"]["solver_product_present"] is False
    assert prepared["execution_controls"]["registry_allowed"] is False
    assert prepared["execution_controls"]["queue_allowed"] is False
    assert prepared["execution_controls"]["ledger_allowed"] is False

    assert _sha256(PREPARED) == card["preflight"]["prepared_manifest"]["sha256"]
    forbidden = {"result.json", "trajectory.h5", "audit.json", "observations.json", "worker-status.json"}
    assert not [path for path in PREPARED.parent.rglob("*") if path.name in forbidden]
    for path_text, expected in prepared["inputs"].items():
        path = Path(path_text)
        assert path.is_file(), path_text
        assert _sha256(path) == expected, path_text


def test_lineage_clarification_binds_static_source_and_dynamic_baselines() -> None:
    clarification = _load(LINEAGE)
    assert clarification["comparison_rule"].startswith("physical_geometry_changed")
    static = clarification["static_source"]
    assert static["physical_geometry_changed_relative_to_source"] is True
    assert static["qualification_inheritance"] == "none"
    assert _sha256(LAB / static["path"]) == static["sha256"]

    dynamic = clarification["dynamic_baseline"]
    assert dynamic["physical_geometry_changed_relative_to_dynamic_baseline"] is False
    assert [item["q"] for item in dynamic["baselines"]] == [0.5, 1.0]
    for item in dynamic["baselines"]:
        prepared = LAB / item["prepared"]["path"]
        assert prepared.is_file()
        assert _sha256(prepared) == item["prepared"]["sha256"]
        assert "walls" in dynamic["geometry_signature"]["catchment_side_walls"]

    candidate = clarification["candidate_comparison"]
    assert candidate["candidate_prepared_geometry_changed_relative_to_static_source"] is True
    assert candidate["candidate_prepared_geometry_changed_relative_to_dynamic_baseline"] is False
    assert candidate["single_variable_change_relative_to_dynamic_baseline"] == "rotation_duration_s only"
