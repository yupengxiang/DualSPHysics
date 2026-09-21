import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.f2_resting_fill_side_wet_dynamic import observe_dynamic_side_wet


LAB = Path(__file__).resolve().parents[1]
PREPARED_DIR = LAB / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_dynamic_canary_v1"
PREPARED = PREPARED_DIR / "prepared.json"
PREFLIGHT = PREPARED_DIR / "dynamic-preflight.json"
JOB = LAB / "campaigns/core-v1/cfd/f2-resting-fill-side-wet-dynamic-canary-v1-job.json"
CARD = LAB / "campaigns/core-v1/cfd/f2-resting-fill-side-wet-dynamic-candidate-card-v1.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _fixture(path: Path) -> Path:
    times = np.asarray([0.0, 0.01, 0.50, 1.35, 2.50], dtype=float)
    n = 4
    position = np.asarray([
        [[0.0025, -0.145, 0.66], [0.4225, -0.145, 0.66], [0.0025, 0.1475, 0.8325], [0.4225, 0.1475, 0.8325]],
    ] * len(times), dtype=float)
    velocity = np.zeros((len(times), n, 3), dtype=float)
    density = np.full((len(times), n), 1000.0, dtype=float)
    pressure = np.zeros((len(times), n), dtype=float)
    mass = np.full((len(times), n), 0.001, dtype=float)
    valid = np.ones((len(times), n), dtype=bool)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("density", data=density)
        handle.create_dataset("pressure", data=pressure)
        handle.create_dataset("mass", data=mass)
        handle.create_dataset("valid", data=valid)
    return path


def test_dynamic_preflight_reuses_passed_native_sampling_and_freezes_event_window():
    prepared = json.loads(PREPARED.read_text())
    preflight = json.loads(PREFLIGHT.read_text())
    config = prepared["config"]
    assert prepared["preflight_pass"] is True
    assert prepared["qualification_only"] is True
    assert config["scope_id"] == "F2_resting_fill_side_wet_dynamic_x_v1"
    assert config["revision_id"] == "F2_resting_fill_side_wet_dynamic_canary_v1"
    assert config["stage"] == "canary"
    assert config["split"] == "qualification_only"
    assert config["parameter"]["value"] == pytest.approx(0.85)
    assert config["time_max_s"] == pytest.approx(2.5)
    assert config["maximum_extended_time_s"] == pytest.approx(5.0)
    assert config["event_window"]["motion_start_s"] == pytest.approx(0.5)
    assert config["event_window"]["settle_hold_s"] == pytest.approx(0.2)
    assert config["event_window"]["post_settle_observation_s"] == pytest.approx(0.35)
    assert preflight["native_sampling_matches_passed_static"] is True
    assert preflight["native"]["fluid_particles"] == 54720
    assert preflight["native_initial_zero_velocity"] is True
    assert preflight["mass_gate_pass"] is True
    assert preflight["runtime_domain_declaration_matches_generated"] is True
    assert config["static_predecessor"]["static_result"]["hard_integrity_pass"] is True
    assert config["static_predecessor"]["static_result"]["event_window_complete"] is True
    assert config["qualification_claim"].startswith("none;")


def test_side_wet_observer_keeps_valid_physical_edge_centres_inside_at_initial_frame(tmp_path):
    observations = observe_dynamic_side_wet(PREPARED, _fixture(tmp_path / "trajectory.h5"))
    assert observations["cup_mass_fraction"][0] == pytest.approx(1.0)
    assert observations["outside_observation_mass_fraction"][0] == pytest.approx(0.0)
    assert observations["cup_observation_bounds"] == "physical cup source planes; no one-dp shrink for side-wetted initial state"
    assert observations["event_times_s"]["motion_complete"] == pytest.approx(1.35)
    assert observations["event_window_complete"] is False


def test_dynamic_job_and_card_bind_all_runner_inputs_without_qualification_claim():
    prepared = json.loads(PREPARED.read_text())
    job = json.loads(JOB.read_text())
    card = json.loads(CARD.read_text())
    assert job["qualification_only"] is True
    assert job["qualification_claim"] == "none"
    assert job["scope_id"] == prepared["config"]["scope_id"]
    assert job["revision_id"] == prepared["config"]["revision_id"]
    assert job["physical_geometry_changed"] is False
    assert job["initial_condition_changed"] is True
    assert job["motion_control_changed"] is True
    assert job["mass_rescaling"] is False
    assert job["argv"][1].endswith("scripts/f2_resting_fill_side_wet_dynamic.py")
    assert job["registered_window_s"] == pytest.approx(2.5)
    assert job["maximum_extended_window_s"] == pytest.approx(5.0)
    assert job["resources"] == {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.5}
    for item in job["input_files"]:
        path = Path(item["path"])
        assert path.is_file()
        assert digest(path) == item["sha256"]
    assert card["status"] == "cpu_prepared_unsubmitted"
    assert card["qualification_claim"].startswith("none;")
    assert card["qualified"] is False
    assert card["qualification_only"] is True
    assert card["gpu_launch_by_subagent"] is False
    assert card["central_ledger_mutation"] == 0
    assert card["artifacts"]["prepared"]["sha256"] == digest(PREPARED)
    assert card["artifacts"]["dynamic_preflight"]["sha256"] == digest(PREFLIGHT)
    assert card["artifacts"]["job"]["sha256"] == digest(JOB)
