"""CPU-only contract tests for the R4 core-mother-case audit."""

from __future__ import annotations

from pathlib import Path

from scripts.r4_core_mother_case_audit import (
    build_audit,
    planned_runs,
    render_markdown,
)


LAB = Path(__file__).resolve().parents[1]


def test_audit_selects_f1_and_keeps_execution_blocked():
    payload = build_audit(LAB)

    assert payload["current_conclusion"]["first_core_mother_case"] == "F1_obstacle_ladder"
    assert payload["current_conclusion"]["formal_execution_authorization"] == "NO_GO"
    assert payload["current_conclusion"]["development_numerical_route"] == "GO_T1_ONLY"
    assert payload["decision"]["formal_t1_t2_route"] == "NO_GO"


def test_a0_and_a1_coverage_are_explicit():
    payload = build_audit(LAB)
    a0 = payload["A0_official_anchor_audit"]
    a1 = payload["A1_three_background_by_three_resolution_audit"]

    assert all(item["exists"] for item in payload["audit_inputs"])
    assert "cases/manifest.json" in {
        item["path"] for item in payload["audit_inputs"]
    }
    assert a0["F1"]["official_test"] == "SPHERIC Test 02"
    assert a0["F3"]["official_test"] == "SPHERIC Test 10"
    assert all(item["status"] == "anchor_present_partial_not_full_gold" for item in a0.values())
    assert all(item["three_resolution_runs_completed"] for item in a0.values())

    for family in ("F1", "F3"):
        summary = a1["families"][family]
        assert summary["cell_count"] == 9
        assert summary["evidence_coverage"] == "5/9"
        assert summary["target_compatible_coverage"] == "3/9"
        assert summary["missing_execution_cells"] == 4
        assert summary["prepared_only_cells"] == 0
        assert len(summary["cells"]) == 9


def test_planned_experiment_is_bounded_and_never_executes():
    runs = planned_runs()

    assert len(runs) == 9
    assert len({run["case_id"] for run in runs}) == 9
    assert all(not run["execute"] for run in runs)
    assert {run["background_id"] for run in runs} == {
        "plain_dam_break",
        "center_obstacle",
        "twin_obstacle_split_remerge",
    }
    assert {run["level"] for run in runs} == {"coarse", "medium", "fine"}
    assert all(run["saved_output_cadence_s"] == 0.001 for run in runs)
    assert all(run["time_window_s"] == [0.0, 1.5] for run in runs)
    assert all(run["event_window_s"] == [0.35, 0.55] for run in runs)
    assert all(run["integrator"] == "Verlet" for run in runs)
    assert all(run["boundary_formulation"] == "DBC" for run in runs)


def test_single_gate_contains_t1_t2_evidence_requirements():
    payload = build_audit(LAB)
    gate = payload["acceptance_gate"]

    assert gate["gate_id"] == "R4_CORE_MOTHER_CASE_GATE_v1"
    assert gate["status"] == "not_passed"
    assert gate["screening_thresholds"]["top_two_resolution_primary_distribution_tv_max"] == 0.05
    assert gate["screening_thresholds"]["event_sampling_cadence_s_max"] == 0.001
    assert gate["screening_thresholds"]["event_window_s"] == [0.35, 0.55]
    condition_ids = {condition["id"] for condition in gate["conditions"]}
    assert {
        "A0_official_anchor",
        "A1_nine_executed_cells",
        "A2_common_control_protocol",
        "A2_event_sampling_and_window",
        "closed_trajectory_quality_and_resolution",
        "T2_destination_closure",
    } <= condition_ids
    assert "T2_destination_closure" in gate["current_blocking_conditions"]


def test_checked_in_report_is_reproducible_from_cpu_audit():
    payload = build_audit(LAB)
    report = (LAB / "campaigns/v0.1-candidate/R4-CORE-MOTHER-CASE-AUDIT.md").read_text()

    assert render_markdown(payload) == report
    assert payload["read_only_policy"]["solver_invocations"] == 0
    assert payload["read_only_policy"]["gencase_invocations"] == 0
    assert payload["read_only_policy"]["gpu_queries"] == 0
