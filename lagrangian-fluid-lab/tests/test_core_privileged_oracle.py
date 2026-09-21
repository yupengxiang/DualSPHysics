from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.core_privileged_oracle import (
    PROPOSAL_SCHEMA,
    SCHEMA,
    make_proposal,
    run_privileged_oracle,
)
import scripts.core_privileged_oracle as oracle_module


def _tiny_prepared(path: Path) -> Path:
    payload = {
        "schema": "core.cfd.v1",
        "config": {
            "schema": "core.cfd.v1", "family": "F4",
            "case_id": "F4_oracle_fixture", "scope_id": "fixture",
            "recipe_id": "fixture", "stage": "qualification",
            "qualification_only": True, "qualification_claim": "none",
            "split": "qualification_only", "dp_m": 0.1,
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "wall_bounds": {"xmin": -1.0, "xmax": 1.0,
                            "ymin": -1.0, "ymax": 1.0,
                            "zmin": -1.0, "zmax": 1.0},
            "closed_faces": ["bottom", "left", "right", "front", "back"],
            "open_faces": ["top"],
        },
    }
    path.write_text(json.dumps(payload))
    return path


def _tiny_trajectory(path: Path) -> Path:
    times = np.asarray([0.0, 0.1, 0.2])
    position = np.asarray([
        [[0.0, 0.0, 0.0], [0.2, 0.0, 0.0]],
        [[0.1, 0.0, 0.0], [0.4, 0.0, 0.0]],
        [[0.3, 0.0, 0.0], [np.nan, np.nan, np.nan]],
    ], dtype=np.float32)
    velocity = np.asarray([
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        [[2.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        [[3.0, 0.0, 0.0], [np.nan, np.nan, np.nan]],
    ], dtype=np.float32)
    valid = np.asarray([[True, True], [True, True], [True, False]])
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("particle_id", data=np.asarray([10, 11], dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.asarray([0, 0], dtype=np.int64))
        handle.create_dataset("mass", data=np.asarray([1.0, 2.0], dtype=np.float32))
        handle.create_dataset("valid", data=valid)
    return path


def _lifecycle_trajectory(path: Path, *, changed_active_mass: bool = False) -> Path:
    """Native full-axis fixture with an inactive NaN payload."""
    times = np.asarray([0.0, 0.1, 0.2])
    position = np.asarray([
        [[0.0, 0.0, 0.0], [0.2, 0.0, 0.0]],
        [[0.1, 0.0, 0.0], [np.nan, np.nan, np.nan]],
        [[0.2, 0.0, 0.0], [np.nan, np.nan, np.nan]],
    ], dtype=np.float32)
    velocity = np.asarray([
        [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        [[1.0, 0.0, 0.0], [np.nan, np.nan, np.nan]],
        [[1.0, 0.0, 0.0], [np.nan, np.nan, np.nan]],
    ], dtype=np.float32)
    valid = np.asarray([[True, True], [True, False], [True, False]])
    mass = np.asarray([[1.0, 2.0], [1.0, np.nan], [1.0, np.nan]], dtype=np.float64)
    if changed_active_mass:
        mass[1, 0] = 1.5
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=times)
        handle.create_dataset("position", data=position)
        handle.create_dataset("velocity", data=velocity)
        handle.create_dataset("particle_id", data=np.asarray([10, 11], dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.asarray([0, 0], dtype=np.int64))
        handle.create_dataset("mass", data=mass)
        handle.create_dataset("valid", data=valid)
    return path


def test_privileged_oracle_uses_native_dv_and_fixed_denominator(tmp_path):
    prepared = _tiny_prepared(tmp_path / "prepared.json")
    trajectory = _tiny_trajectory(tmp_path / "trajectory.h5")
    report = run_privileged_oracle(
        prepared, trajectory,
        output=tmp_path / "oracle.json", progress_output=tmp_path / "progress.json",
    )
    assert report["schema"] == SCHEMA
    assert report["privileged_reference_oracle"] is True
    assert report["training_excluded"] is True
    assert report["qualification_excluded"] is True
    assert report["predictor_future_state_inputs"] is False
    assert report["future_reference_state_used_by_oracle"] is True
    assert report["summary"]["execution_complete"] is True
    assert report["summary"]["expected_frames"] == 2
    assert report["summary"]["completed_frames"] == 2
    assert report["summary"]["native_lifecycle_transition_count"] == 1
    assert report["evaluator"]["fixed_denominator_expected_frames"] == 2
    assert report["evaluator"]["score"]["complete"] is True
    assert report["evaluator"]["score"]["selection_score"] == 0.0
    # Frame 0->1 has dx/dt = 1 m/s but native dv = 2 m/s.  The oracle must
    # expose that distinction instead of silently reconstructing velocity.
    first = report["frames"][0]["increment"]
    assert first["dv_max_abs_mps"] == 2.0
    assert first["native_dv_minus_dx_over_dt_max_abs_mps"] == pytest.approx(1.0, abs=1e-6)
    assert report["physics"]["frames_completed"] == 2
    progress = json.loads((tmp_path / "progress.json").read_text())
    assert progress["status"] == "completed"
    assert progress["predictor_future_state_inputs"] is False
    assert progress["future_reference_state_used_by_oracle"] is True


def test_privileged_oracle_proposal_is_cpu_only_and_nonqualifying(tmp_path):
    prepared = _tiny_prepared(tmp_path / "prepared.json")
    trajectory = _tiny_trajectory(tmp_path / "trajectory.h5")
    proposal = make_proposal(
        prepared, trajectory, output_path=tmp_path / "proposal.json",
        report_path=tmp_path / "report.json", progress_path=tmp_path / "progress.json",
    )
    assert proposal["schema"] == PROPOSAL_SCHEMA
    assert proposal["proposal_only"] is True
    assert proposal["training_excluded"] is True
    assert proposal["qualification_only"] is True
    assert proposal["formal_eligible"] is False
    assert proposal["resources"]["device"] == "cpu"
    assert proposal["resources"]["gpu"] is False
    assert "--progress-output" in proposal["command"]
    assert "" not in proposal["command"]


def test_bad_public_updater_is_visible_to_commit_error_and_score(tmp_path, monkeypatch):
    prepared = _tiny_prepared(tmp_path / "prepared.json")
    trajectory = _tiny_trajectory(tmp_path / "trajectory.h5")
    real_apply = oracle_module.apply_prediction

    def bad_apply(state, prediction, dt):
        updated = real_apply(state, prediction, dt)
        position = np.array(updated.position, copy=True)
        position[np.flatnonzero(state.valid)[0], 0] += 1e-3
        return oracle_module.State(
            updated.time_s, position, updated.velocity,
            updated.particle_id, updated.particle_zone, updated.mass, updated.valid,
        )

    monkeypatch.setattr(oracle_module, "apply_prediction", bad_apply)
    report = run_privileged_oracle(
        prepared, trajectory, output=tmp_path / "broken.json", include_physics=False,
    )
    assert report["summary"]["execution_complete"] is True
    assert report["summary"]["finite_rollout_complete"] is True
    assert report["summary"]["oracle_accuracy_pass"] is False
    assert report["frames"][0]["increment"]["committed_position_max_abs_error_m"] >= 1e-3
    assert report["evaluator"]["score"]["selection_score"] > 0.0


def test_inactive_nan_mass_is_bound_to_initial_identity_axis(tmp_path):
    prepared = _tiny_prepared(tmp_path / "prepared.json")
    trajectory = _lifecycle_trajectory(tmp_path / "lifecycle.h5")
    report = run_privileged_oracle(prepared, trajectory,
                                   output=tmp_path / "lifecycle.json",
                                   include_physics=False)
    assert report["summary"]["execution_complete"] is True
    assert report["summary"]["completed_frames"] == 2
    assert report["summary"]["native_lifecycle_transition_count"] == 1
    assert report["summary"]["failure_category"] is None


def test_active_mass_change_still_fails_closed(tmp_path):
    prepared = _tiny_prepared(tmp_path / "prepared.json")
    trajectory = _lifecycle_trajectory(tmp_path / "changed.h5", changed_active_mass=True)
    report = run_privileged_oracle(prepared, trajectory,
                                   output=tmp_path / "changed.json",
                                   include_physics=False)
    assert report["summary"]["execution_complete"] is False
    assert report["summary"]["failure_category"] == "native_identity_or_mass_mismatch"
    assert report["summary"]["first_failure_frame"] == 1
