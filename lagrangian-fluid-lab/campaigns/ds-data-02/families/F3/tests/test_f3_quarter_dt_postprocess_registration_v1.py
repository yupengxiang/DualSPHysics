from __future__ import annotations

import json
from pathlib import Path


FAMILY = Path(__file__).resolve().parents[1]
HANDOFF = FAMILY / "handoff_20261003/quarter_dt_postprocess_v1"


def load(name: str) -> dict:
    return json.loads((HANDOFF / name).read_text(encoding="utf-8"))


def test_completed_quarter_receipt_and_runparts_are_bound_without_exclusions():
    manifest = load("quarter_dt_postprocess_manifest_v1.json")
    evidence = manifest["actual_solver_evidence"]
    timeline = evidence["timeline"]
    assert timeline["rows"] == 4001
    assert timeline["full_window_completed"] is True
    assert timeline["last_time_s"] >= 10.0
    assert timeline["NpOut_sum"] == 0
    assert timeline["NpOutPos_sum"] == 0
    assert timeline["NpOutRho_sum"] == 0
    assert timeline["NpOutMov_sum"] == 0
    assert timeline["post_initial_fixed_step_exact"] is True
    assert timeline["post_initial_DtMin_min_s"] == 5.53067421676747e-06
    assert timeline["post_initial_DtMax_max_s"] == 5.53067421676747e-06
    assert evidence["receipt"]["sha256"]
    assert evidence["runparts"]["sha256"]


def test_conversion_request_is_root_ready_but_has_no_local_launch_authority():
    request = load("quarter_dt_conversion_request_v1.json")
    assert request["status"] == "root_review_ready"
    assert request["runnable"] is True
    assert request["ready_for_root_dispatch"] is True
    assert request["launch_allowed_by_this_agent"] is False
    assert request["root_only"] is True
    assert request["cpu_threads"] == 4
    assert request["max_wall_seconds"] == 7200
    assert request["estimated_storage_bytes"] == 64 * 1024**3
    assert request["qualification_claim"].startswith("none")
    assert request["q_n_status"] == "not_assessed"
    assert request["expected_native"]["saved_frames"] == 4001
    assert request["expected_native"]["native_exclusions"]["NpOut_sum"] == 0


def test_quarter_labels_and_comparison_wait_for_real_terminal_h5():
    labels = load("quarter_dt_labels_request_v1_deferred.json")
    comparison = load("quarter_vs_half_comparison_request_v1_deferred.json")
    assert labels["runnable"] is False
    assert labels["launch_allowed"] is False
    assert labels["status"] == "deferred_until_terminal_conversion"
    assert all(item["sha256"] is None for item in labels["deferred_input_bindings"].values())
    assert comparison["runnable"] is False
    assert comparison["launch_allowed"] is False
    assert comparison["status"] == "deferred_until_quarter_labels_terminal"
    assert comparison["quarter_label_binding"]["sha256"] is None
    assert comparison["baseline_label_binding"]["sha256"]
    assert comparison["budget_contract"]["macro_relative"] == 0.05
    assert comparison["budget_contract"]["event_time_relative"] == 0.02
    assert comparison["budget_contract"]["save_or_integration_share"] == 0.20
    assert comparison["budget_contract"]["residence_time_budget_registered"] is False
    assert comparison["q_n_status"] == "not_assessed"


def test_physical_binding_and_same_save_temporal_role_are_explicit():
    owner = load("F3_DUAL_AXIS_WEAK_006G_004G_QUARTER_DT.owner.v1-deferred.json")
    assert owner["physical_binding_sha256"] == "fdb645e24952ed2f41225ca537d067d0233c9a94746fd4af0c390205736c9b10"
    physical = owner["physical_geometry_control_contract"]
    assert physical["same_physical_case_as"] == "F3_DUAL_AXIS_WEAK_006G_004G_HALF_DT"
    assert physical["changed_solver_keys_only"] == ["DtIni", "DtMin", "DtFixed"]
    assert physical["generated_xml_physical_projection_sha256"] == physical["half_dt_generated_xml_physical_projection_sha256"]
    assert physical["bi4_same_sha256"] is True
    assert physical["control_same_sha256"] is True
    assert owner["numerical_recipe"]["DtFixed_s"] == 5.53067421676747e-06
    assert owner["numerical_recipe"]["TimeOut_s"] == 0.0025
    assert owner["terminal_conversion_binding"]["status"] == "deferred_until_root_conversion_terminal"
    assert owner["qualification_claim"] == "none"
    assert owner["q_n_status"] == "not_assessed"
