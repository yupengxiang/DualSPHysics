import json
from pathlib import Path

import pytest

from scripts.core_cfd import digest


LAB = Path(__file__).resolve().parents[1]
PREPARED_DIR = LAB / "campaigns/core-v1/cfd/prepared/F2_resting_fill_static_hold_canary_v2"
PREPARED = PREPARED_DIR / "prepared.json"
PREFLIGHT = PREPARED_DIR / "static-preflight.json"
JOB = LAB / "campaigns/core-v1/cfd/f2-resting-fill-static-hold-canary-v2-job.json"
CARD = LAB / "campaigns/core-v1/cfd/f2-resting-fill-static-hold-candidate-card-v2.json"
ARCHIVED_FAILED = LAB / "campaigns/core-v1/cfd/prepared/F2_resting_fill_static_hold_canary_preflight_failed_001"


def test_resting_fill_v2_is_a_native_cpu_preflight_only_candidate():
    prepared = json.loads(PREPARED.read_text())
    config = prepared["config"]
    preflight = prepared["static_preflight"]

    assert prepared["preflight_pass"] is True
    assert prepared["qualification_only"] is True
    assert prepared["qualification_claim"].startswith("none;")
    assert config["stage"] == "repair_canary"
    assert config["split"] == "qualification_only"
    assert config["qualification_only"] is True
    assert config["scope_id"] == "F2_resting_fill_static_hold_x_v1"
    assert config["revision_id"] == "F2_resting_fill_static_hold_v2"
    assert config["qualified"] is False
    assert config["initial_condition"]["fluid_initial_condition_changed"] is True
    assert config["initial_condition"]["continuum_wall_geometry_changed"] is False
    assert config["initial_condition"]["mass_rescaling"] is False
    assert config["static_hold"]["drive_start_s"] == pytest.approx(0.5)
    assert config["static_hold"]["requested_horizon_s"] == pytest.approx(0.6)
    assert config["static_hold"]["event_window_complete_requires_settled"] is True

    checks = preflight["checks"]
    assert all(checks.values())
    assert preflight["native_source"]["fluid_particles"] == 56115
    assert preflight["native_source"]["native_fluid_mass_kg"] == pytest.approx(23.673515625)
    candidate = preflight["candidate_initial_fluid"]
    assert candidate["actual_native_position_bounds_m"]["low"][2] == pytest.approx(0.660)
    assert candidate["actual_native_position_bounds_m"]["high"][2] == pytest.approx(0.990)
    assert candidate["minimum_physical_face_clearance_m"] == pytest.approx(0.010)
    assert candidate["minimum_native_cup_boundary_center_distance_m"] == pytest.approx(0.0075)
    assert candidate["maximum_initial_speed_m_s"] == pytest.approx(0.0)
    assert candidate["particle_count"] == 56115

    mass = prepared["mass_preflight"]
    assert mass["mass_rescaling"] is False
    assert mass["mass_gate_pass"] is True
    assert mass["total_relative_error"] == pytest.approx(0.00332763827082)
    assert digest(PREFLIGHT) == prepared["inputs"][str(PREFLIGHT.resolve())]


def test_resting_fill_job_is_ready_for_coordinator_review_only():
    prepared = json.loads(PREPARED.read_text())
    job = json.loads(JOB.read_text())
    assert job["job_id"] == "f2-resting-fill-static-hold-canary-v2-001"
    assert job["qualification_only"] is True
    assert job["qualification_claim"] == "none"
    assert job["physical_geometry_changed"] is False
    assert job["initial_condition_changed"] is True
    assert job["mass_rescaling"] is False
    assert job["registered_window_s"] == pytest.approx(0.6)
    assert job["pre_motion_window_s"] == pytest.approx(0.5)
    assert job["resources"] == {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.25}
    assert job["required_outputs"] == [
        "product/result.json",
        "product/trajectory.h5",
        "product/audit.json",
        "product/observations.json",
    ]
    prepared_input = next(item for item in job["input_files"] if item["path"] == str(PREPARED.resolve()))
    assert prepared_input["sha256"] == digest(PREPARED)
    assert job["prepared_case_id"] == prepared["config"]["case_id"]
    assert "run" in job["argv"]
    assert "--lab-root" in job["argv"]


def test_resting_fill_candidate_card_binds_hashes_and_preserves_scope_boundaries():
    card = json.loads(CARD.read_text())
    assert card["status"] == "cpu_prepared_unsubmitted"
    assert card["qualification_only"] is True
    assert card["qualified"] is False
    assert card["supersedes_nothing"] is True
    assert card["physical_contract"]["continuum_wall_geometry_changed"] is False
    assert card["physical_contract"]["fluid_initial_condition_changed"] is True
    assert card["physical_contract"]["native_first_fluid_center_z_m"] == pytest.approx(0.66)
    assert card["physical_contract"]["minimum_physical_floor_clearance_m"] == pytest.approx(0.01)
    assert card["static_hold_canary"]["original_drive_start_s"] == pytest.approx(0.5)
    assert card["static_hold_canary"]["no_static_result_yet"] is True
    assert card["launch_policy"]["central_ledger_mutation"] == 0
    for entry in card["artifacts"].values():
        assert digest(LAB / entry["path"]) == entry["sha256"]


def test_failed_z0p665_preflight_is_retained_and_no_scope_claim_is_made():
    assert ARCHIVED_FAILED.is_dir()
    old_preflight = json.loads((ARCHIVED_FAILED / "static-preflight.json").read_text())
    assert old_preflight["preflight_pass"] is False
    assert old_preflight["checks"]["target_first_fluid_center_z"] is False
    assert old_preflight["checks"]["native_fluid_count"] is False
    assert old_preflight["candidate_initial_fluid"]["actual_native_position_bounds_m"]["low"][2] == pytest.approx(0.6375)
