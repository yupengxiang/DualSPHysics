"""Unit tests for matched RV4 spatial-reference conversion templates and macro preregistration."""

from __future__ import annotations

import json
from pathlib import Path
import pytest


MODULE_DIR = (
    Path(__file__).resolve().parents[1]
    / "handoff_20261003/rv4_matched_three_dp_init_v1"
)
TEMPLATE_DIR = MODULE_DIR / "conversion_templates_spatial_reference_v1"
MANIFEST_PATH = MODULE_DIR / "artifacts/rv4_matched_spatial_macro_preregistration_manifest_v1.json"


def test_four_spatial_solver_runs_in_manifest():
    assert MANIFEST_PATH.is_file(), "Manifest file must exist"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    summary = data["solver_runs_summary"]
    assert summary["total_runs"] == 4
    assert summary["all_runs_completed_code0"] is True
    assert summary["all_runs_401_frames"] is True
    assert summary["all_runs_4s_window"] is True

    runs = {r["case_id"]: r for r in summary["runs"]}
    assert len(runs) == 4

    center_coarse = runs["F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010"]
    assert center_coarse["excluded_particles"] == 122
    assert abs(center_coarse["elapsed_seconds"] - 98.709) < 0.01

    center_medium = runs["F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010"]
    assert center_medium["excluded_particles"] == 216
    assert abs(center_medium["elapsed_seconds"] - 266.534) < 0.01

    offset_coarse = runs["F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010"]
    assert offset_coarse["excluded_particles"] == 118
    assert abs(offset_coarse["elapsed_seconds"] - 118.527) < 0.01

    offset_medium = runs["F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010"]
    assert offset_medium["excluded_particles"] == 210
    assert abs(offset_medium["elapsed_seconds"] - 719.516) < 0.01


def test_conversion_templates_are_source_bound_and_not_launched():
    template_files = sorted(TEMPLATE_DIR.glob("*_conversion_template_v1.json"))
    assert len(template_files) == 4

    for path in template_files:
        t = json.loads(path.read_text(encoding="utf-8"))
        assert t["schema"] == "ds-data-02.runner.request.v1"
        assert t["family_id"] == "F2"
        assert t["kind"] == "cpu"
        assert t["cpu_task_kind"] == "native_bi4_streaming_fullstate_conversion"
        assert t["conversion_launch"]["allowed"] is False
        assert "explicitly forbidden" in t["conversion_launch"]["reason"]
        assert t["launch_allowed"] is False
        assert t["solver_launch_forbidden"] is True
        assert t["gpu_launch"]["family_owner_launch"] is False

        # Verify claim boundaries
        assert "not_granted" in t["claim_boundary"]["q_i"]
        assert "not_assessed" in t["claim_boundary"]["q_n"]
        assert t["claim_boundary"]["production"] == "not_evaluated"

        # Verify exact matching continuum mass
        assert t["spatial_reference_preregistration"]["continuum_mass_kg"] == 24.576
        assert t["spatial_reference_preregistration"]["save_interval_s"] == 0.01
        assert t["spatial_reference_preregistration"]["save_half_bracket_s"] == 0.005
        assert t["spatial_reference_preregistration"]["save_temporal_allocation_budget_s"] == 0.0001467278159987655
        assert t["spatial_reference_preregistration"]["event_qn_grant_permitted"] is False


def test_macro_preregistration_vs_fine_dp005_within_budget():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    comparisons = data["macro_preregistration_vs_fine_dp005"]

    assert len(comparisons) == 4
    for name, comp in comparisons.items():
        assert comp["within_macro_budget_0p05"] is True
        assert comp["relative_retained_mass_difference"] < 0.05
        assert comp["continuum_fluid_mass_kg"] == 24.576
        assert comp["case_excluded_mass_fraction"] < 0.011
        assert comp["fine_excluded_mass_fraction"] < 0.011


def test_save_boundary_and_f3_provenance():
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    boundary = data["temporal_save_qualification_boundary"]
    assert boundary["save_interval_s"] == 0.01
    assert boundary["half_bracket_width_s"] == 0.005
    assert boundary["frozen_event_allocation_s"] == 0.0001467278159987655
    assert "insufficient" in boundary["verdict"]
    assert boundary["q_i_granted"] is False
    assert boundary["q_n_granted"] is False
    assert boundary["production_eligible"] is False

    f3 = data["preserved_f3_provenance"]
    assert f3["weak_quarter_allocation_x"] == 0.010238388262513484
    assert f3["weak_quarter_allocation_y"] == 0.017270993599294474
    assert f3["actual_conditional_gap_x"] == 0.02248
    assert f3["actual_conditional_gap_y"] == 0.06929
    assert f3["gate_verdict"] == "fail"
    assert f3["f3_gpu_forbidden"] is True
