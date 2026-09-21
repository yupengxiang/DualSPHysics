import json
from pathlib import Path

import pytest

from scripts.core_cfd import digest


LAB = Path(__file__).resolve().parents[1]
REPORT = LAB / "campaigns/core-v1/evidence/f2-closed-catchment-v2-h200/five-second-feasibility-v1.json"
CARD = LAB / "campaigns/core-v1/cfd/f2-resting-fill-static-hold-candidate-card-v1.json"


def test_five_second_projection_is_tail_only_and_keeps_native_mass():
    report = json.loads(REPORT.read_text())
    source = report["source"]
    hashes = source["hashes"]
    assert report["qualification_claim"].startswith("none;")
    assert report["solver_relaunched"] is False
    assert report["gpu_launched"] is False
    assert source["active_native_particle_count"] == 56115
    assert source["mass_retained"] is True
    assert report["physical_contract"]["fluid_facing_floor_z_m"] == -0.2
    assert report["tail_selection"]["particle_count"] == 145
    assert report["tail_selection"]["mass_fraction_of_native"] == pytest.approx(0.002583979328165375)
    assert report["runtime_domain"]["current_tail_outside_endpoint_count"] == 0
    assert report["runtime_domain"]["projected_tail_outside_endpoint_count"] == 145
    assert report["future_finite_wall_recontact"]["closed_face_event_count"] == 0
    assert report["future_finite_wall_recontact"]["open_top_entry_count"] == 12
    assert report["cell_memory_estimate"]["projected_union_with_0p5m_margin"]["cells"] == 4853024748
    assert report["cell_memory_estimate"]["projected_union_with_0p5m_margin"]["estimated_gpu_cell_memory_gib"] == pytest.approx(72.4526251484)
    assert report["settled_assessment"]["global_settled_claim"] == "unavailable"
    assert report["extension_recommendation"]["status"] == "do_not_extend_current_scope_from_this_projection"
    assert digest(Path(hashes["analysis_script"])) == hashes["analysis_script_sha256"]

    for key, path_name in (
        ("prepared_sha256", "prepared"),
        ("trajectory_sha256", "trajectory"),
        ("observations_sha256", "observations"),
        ("audit_sha256", "audit"),
    ):
        path = Path(source[path_name]) if path_name == "prepared" else REPORT.parent / {"trajectory": "trajectory.h5", "observations": "observations.json", "audit": "audit.json"}[path_name]
        assert digest(path) == hashes[key]


def test_resting_fill_card_is_independent_and_unsubmitted():
    card = json.loads(CARD.read_text())
    assert card["scope_id"] == "F2_resting_fill_static_hold_x_v1"
    assert card["status"] == "proposal_only_unprepared"
    assert card["supersedes_nothing"] is True
    assert card["central_ledger_mutation"] == 0
    assert card["gpu_launch_by_subagent"] is False
    assert card["physical_contract"]["continuum_wall_geometry_changed"] is False
    assert card["physical_contract"]["fluid_initial_condition_changed"] is True
    assert card["physical_contract"]["native_particle_count"] == 56115
    assert card["physical_contract"]["native_mass_kg"] == pytest.approx(23.673516239068704)
    assert card["source_failure_context"]["measured_initial_bottom_gap_m"] == pytest.approx(0.055)
    assert card["source_failure_context"]["pre_motion_evidence"]["outside_observation_mass_fraction_max"] == pytest.approx(0.04006058986010871)
    reference = card["initial_condition_recipe"]["native_boundary_reference"]
    assert reference["proposed_first_fluid_center_z_m"] == pytest.approx(0.665)
    assert reference["proposed_physical_floor_clearance_m"] == pytest.approx(0.015)
    assert card["static_hold_canary"]["gates_reused_without_relaxation"]["all_native_ids_retained"] is True
    assert card["followup_dynamic_scope"]["inherits_current_f2_qualification"] is False
    assert card["launch_policy"]["prepared"] is False
    assert card["launch_policy"]["gpu_submit"] is False
