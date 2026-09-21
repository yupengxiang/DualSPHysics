import json
from pathlib import Path

import h5py
import numpy as np

from scripts.f2_receiver_overflow_runtime_v1 import (
    AUDIT_SCHEMA,
    JOB_SCHEMA,
    PROPOSAL_SCHEMA,
    audit_hdf5_trajectory,
    make_anchor_job_proposal,
    prepare_proposal,
)


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-receiver-overflow-weir-scope-v1"


def test_prepare_proposal_is_hash_bound_and_solver_disabled(tmp_path):
    output = tmp_path / "prepared.json"
    proposal = prepare_proposal(BASE, output)
    assert output.is_file()
    assert proposal["schema"] == PROPOSAL_SCHEMA
    assert proposal["status"] == "prepared_proposal_not_runtime_authorized"
    assert proposal["qualification_claim"] == "none"
    assert proposal["matrix_credit"] == 0
    assert proposal["preflight_pass"] is True
    assert proposal["native_initial"]["normal_decode_probe"] == "passed"
    assert proposal["native_initial"].get("normal_directory") is None
    assert proposal["execution_controls"] == {
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "runtime_preparation_authorized": False,
        "submit_allowed": False,
    }
    assert proposal["input_hashes"]["adapter"]
    assert proposal["input_hashes"]["runtime_preparation_script"]
    assert "argv" not in proposal


def test_anchor_job_proposal_cannot_be_submitted(tmp_path):
    prepared_path = tmp_path / "prepared.json"
    job_path = tmp_path / "job.json"
    prepare_proposal(BASE, prepared_path)
    job = make_anchor_job_proposal(prepared_path, job_path)
    assert job_path.is_file()
    assert job["schema"] == JOB_SCHEMA
    assert job["status"] == "proposal_only_not_submitted"
    assert job["execution_policy"]["submit_allowed"] is False
    assert job["execution_policy"]["solver_launch"] is False
    assert job["execution_policy"]["gpu_launch"] is False
    assert job["execution_policy"]["queue_mutation"] == 0
    assert job["execution_policy"]["matrix_submission"] is False
    assert job["argv"] == []


def test_hdf5_hard_audit_accepts_complete_safe_anchor_trajectory(tmp_path):
    prepared_path = tmp_path / "prepared.json"
    prepare_proposal(BASE, prepared_path)
    trajectory_path = tmp_path / "trajectory.h5"
    # Two synthetic particles cross the finite weir plane above the crest and
    # remain in the receiver for 1.4 s.  They stay above the weir volume, so
    # this exercises both the event observer and the finite-wall hard audit.
    positions = np.array([
        [[0.70, 0.10, 0.30], [0.70, 0.20, 0.30]],
        [[0.80, 0.10, 0.27], [0.80, 0.20, 0.27]],
        [[0.80, 0.10, 0.27], [0.80, 0.20, 0.27]],
        [[0.80, 0.10, 0.27], [0.80, 0.20, 0.27]],
    ], dtype=np.float64)
    times = np.array([0.0, 0.10, 0.80, 1.50], dtype=np.float64)
    valid = np.ones((len(times), 2), dtype=bool)
    ids = np.array([101, 102], dtype=np.int64)
    mass = np.array([0.5, 0.5], dtype=np.float64)
    with h5py.File(trajectory_path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("position", data=positions)
        handle.create_dataset("valid", data=valid)
        handle.create_dataset("particle_id", data=ids)
        handle.create_dataset("mass", data=mass)

    receipt = audit_hdf5_trajectory(prepared_path, trajectory_path)
    assert receipt["schema"] == AUDIT_SCHEMA
    assert receipt["hard_integrity_pass"] is True
    assert receipt["requested_horizon_reached"] is True
    assert receipt["finite_failure_count"] == 0
    assert receipt["endpoint_violation_particle_frames"] == 0
    assert receipt["obstacle_penetration_particle_frames"] == 0
    assert receipt["saved_chord_crossing_count"] == 0
    assert receipt["mass_change_relative_max"] == 0.0
    assert receipt["event_window_complete"] is True
    assert receipt["event_observation"]["crest_crossing"]["frame_index"] == 1
    assert receipt["event_observation"]["receiver_contact"]["frame_index"] == 1
    assert receipt["qualification_claim"] == "none"
    assert receipt["matrix_credit"] == 0
    assert receipt["execution_controls"]["queue_mutation"] == 0
