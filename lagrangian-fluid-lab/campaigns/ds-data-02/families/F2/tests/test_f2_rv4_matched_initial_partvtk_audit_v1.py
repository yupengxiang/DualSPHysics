"""Tests for the actual initial-state evidence sidecar.

These checks intentionally read the compact reports produced by the bounded
official PartVTK requests.  They keep the evidence boundary explicit: passing
initial geometry checks is not a solver Q-I or Q-N result.
"""

from __future__ import annotations

import json
from pathlib import Path


FAMILY_ROOT = Path(__file__).resolve().parents[1]
HANDOFF = FAMILY_ROOT / "handoff_20261003/rv4_matched_three_dp_init_v1"
SUMMARY = HANDOFF / "artifacts/rv4-matched-initial-evidence-summary-v1.json"


def load_summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_summary_has_four_actual_cases_and_keeps_qn_pending():
    summary = load_summary()
    assert summary["status"] == "actual_initial_gencase_partvtk_evidence_complete"
    assert summary["checks"] == {
        "all_initial_reports_pass": True,
        "all_native_mass_matches_continuum": True,
        "all_cases_remain_qn_pending": True,
        "case_count_is_four": True,
        "center_and_offset_have_two_resolutions": True,
        "same_background_physical_hash_stable": True,
    }
    assert summary["qualification_claim"] == "none"
    assert summary["q_i_status"].startswith("initial geometry/population")
    assert summary["q_n_status"] == "not_assessed"
    assert {case["background"] for case in summary["cases"]} == {"CENTER", "OFFSET"}


def test_each_actual_report_binds_3d_population_mass_and_finite_faces():
    summary = load_summary()
    expected_counts = {0.01: 24576, 0.008: 48000}
    for case in summary["cases"]:
        assert case["q_n_status"] == "not_assessed"
        assert case["qualification_claim"] == "none"
        assert case["gencase"]["returncode"] == 0
        assert case["gencase"]["solver_dimension_from_gencase"] == 3
        assert case["partvtk"]["returncode"] == 0
        assert case["fluid_count"] == expected_counts[case["dp_m"]]
        assert case["unique_fluid_ids"] == case["fluid_count"]
        assert case["source_band_positions_pass"] is True
        assert case["native_xml_mass_kg"] == 24.576
        assert case["continuum_mass_kg"] == 24.576
        assert case["native_mass_relative_error"] == 0.0
        assert case["finite_faces"]["all_finite_faces_covered"] is True
        assert all(case["finite_faces"]["face_pass"].values())
        assert case["initial_overlap"]["cup"]["pass"] is True
        assert case["initial_overlap"]["receiver"]["pass"] is True
        assert case["initial_overlap"]["tray"]["pass"] is True


def test_requests_are_official_frame_zero_cpu_only_and_background_hashes_are_distinct():
    summary = load_summary()
    request_dir = HANDOFF / "artifacts/requests"
    physical_by_background = {}
    for case in summary["cases"]:
        request_path = request_dir / f"{case['case_id']}_initial_partvtk_audit_request_v3.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert request["cpu_task_kind"] == "audit"
        assert request["cpu_threads"] == 4
        assert request["solver_launch_forbidden"] is True
        assert request["q_n_status"] == "not_assessed"
        assert request["qualification_claim"].startswith("none;")
        assert "PartVTK_linux64" in request["request_note"]
        assert request["gencase_terminal_binding"]["receipt_path"] == case["gencase"]["receipt"]
        physical_by_background.setdefault(case["background"], set()).add(case["physical_condition_hash"])
    assert all(len(values) == 1 for values in physical_by_background.values())
    assert next(iter(physical_by_background["CENTER"])) != next(iter(physical_by_background["OFFSET"]))
