"""Synthetic-only tests for the read-only F3 rollout/HDF5 sidecar validator."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as validator


EXPECTED = 835
CASE_ID = "F3_SYNTHETIC_RECEIPT"


def _metric_values(executed: int) -> list[float | None]:
    return [0.001 * (index + 1) if index < executed else None
            for index in range(EXPECTED)]


def _write_fixture(tmp_path: Path, *, maximum_steps: int | None = None) -> tuple[Path, Path]:
    executed = EXPECTED if maximum_steps is None else maximum_steps
    frame_count = executed + 1
    particles = 3
    trajectory = tmp_path / ("complete.h5" if maximum_steps is None else "bounded.h5")
    position = np.full((frame_count, particles, 3), np.nan, dtype=np.float32)
    velocity = np.full((frame_count, particles, 3), np.nan, dtype=np.float32)
    position[:] = np.arange(frame_count, dtype=np.float32)[:, None, None] * 0.001
    velocity[:] = 0.25
    valid = np.ones((frame_count, particles), dtype=np.bool_)
    with h5py.File(trajectory, "w") as handle:
        handle.attrs["schema_version"] = 1
        handle.attrs["future_state_inputs"] = False
        handle.attrs["autonomous_prediction"] = True
        handle.attrs["case_id"] = CASE_ID
        handle["time"] = np.arange(frame_count, dtype=np.float64) * 0.01
        handle["position"] = position
        handle["velocity"] = velocity
        handle["particle_id"] = np.array([101, 102, 201], dtype=np.int64)
        handle["particle_zone"] = np.array([0, 0, 1], dtype=np.int32)
        handle["mass"] = np.ones(particles, dtype=np.float64)
        handle["valid"] = valid

    failure = None if maximum_steps is None else "maximum_steps_limit"
    first_failure = None if failure is None else executed + 1
    complete = failure is None
    score = {
        "expected_frames": EXPECTED,
        "finite_prefix_frames": executed,
        "executed": True,
        "complete": complete,
        "failure_category": failure,
        "raw_error_coverage": executed / EXPECTED,
        "selection_score": 0.0,
    }
    row = {
        "case_id": CASE_ID,
        "frames_predicted": executed,
        "frames_expected": EXPECTED,
        "frames_executed": executed,
        "expected_frames": EXPECTED,
        "executed": True,
        "position_rmse": _metric_values(executed),
        "velocity_rmse": _metric_values(executed),
        "position_ade": _metric_values(executed),
        "velocity_ade": _metric_values(executed),
        "failure_category": failure,
        "first_failure_frame": first_failure,
        "execution_complete": complete,
        "finite_rollout_complete": complete,
        "scientific_status": "not_assessed",
        "scientific_failure_category": None,
        "scientific_first_failure_frame": None,
        "future_state_inputs": False,
        "trajectory_output": trajectory.name,
        "score": score,
    }
    evaluation = {
        "schema": "core.evaluation.v1",
        "evaluation_mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "registered_case_ids": [CASE_ID],
        "selected_case_ids": [CASE_ID],
        "expected_frames": {CASE_ID: EXPECTED},
        "cases": {CASE_ID: row},
        "maximum_steps": maximum_steps,
        "autonomous": True,
        "future_state_inputs": False,
    }
    evaluation_path = tmp_path / ("complete.json" if maximum_steps is None else "bounded.json")
    evaluation_path.write_text(json.dumps(evaluation), encoding="utf-8")
    return evaluation_path, trajectory


def test_complete_835_transition_fixture_passes_read_only_validation(tmp_path):
    evaluation, trajectory = _write_fixture(tmp_path)
    before = trajectory.read_bytes()

    result = validator.validate_receipt(evaluation)

    assert result["passed"] is True
    assert result["complete"] is True
    assert result["incomplete"] is False
    assert result["failure_category"] is None
    assert result["checks"]["trajectory_frames"] == EXPECTED + 1
    assert result["checks"]["trajectory_transitions"] == EXPECTED
    assert trajectory.read_bytes() == before


def test_maximum_steps_fixture_preserves_835_denominator_and_is_incomplete(tmp_path):
    evaluation, trajectory = _write_fixture(tmp_path, maximum_steps=10)

    result = validator.validate_receipt(evaluation)

    assert result["passed"] is True
    assert result["complete"] is False
    assert result["incomplete"] is True
    assert result["frames_executed"] == 10
    assert result["failure_category"] == "maximum_steps_limit"
    assert result["checks"]["trajectory_frames"] == 11
    assert result["checks"]["tail_frame_count"] == 0
    assert trajectory.is_file()


def test_complete_receipt_rejects_a_maximum_steps_trajectory_override(tmp_path):
    full_root, bounded_root = tmp_path / "full", tmp_path / "bounded"
    full_root.mkdir()
    bounded_root.mkdir()
    complete_evaluation, _ = _write_fixture(full_root)
    _, bounded_trajectory = _write_fixture(bounded_root, maximum_steps=10)

    with pytest.raises(validator.ValidationError, match="frame count"):
        validator.validate_receipt(complete_evaluation, bounded_trajectory)


@pytest.mark.parametrize("mutation,pattern", [
    ("json_future_state", "future_state_inputs"),
    ("hdf5_future_state", "HDF5 future_state_inputs"),
    ("time", "strictly increasing"),
    ("valid_tail", "valid lifecycle"),
    ("false_complete", "frame count"),
])
def test_complete_and_bounded_contracts_fail_closed(tmp_path, mutation, pattern):
    evaluation, trajectory = _write_fixture(tmp_path, maximum_steps=10)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))

    if mutation == "json_future_state":
        payload["future_state_inputs"] = True
        evaluation.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "hdf5_future_state":
        with h5py.File(trajectory, "r+") as handle:
            handle.attrs["future_state_inputs"] = True
    elif mutation == "time":
        with h5py.File(trajectory, "r+") as handle:
            handle["time"][3] = handle["time"][2]
    elif mutation == "valid_tail":
        with h5py.File(trajectory, "r+") as handle:
            handle["valid"][0, 0] = False
    elif mutation == "false_complete":
        payload["maximum_steps"] = None
        row = payload["cases"][CASE_ID]
        row["frames_executed"] = EXPECTED
        row["frames_predicted"] = EXPECTED
        row["failure_category"] = None
        row["first_failure_frame"] = None
        row["execution_complete"] = True
        row["finite_rollout_complete"] = True
        row["score"]["failure_category"] = None
        row["score"]["complete"] = True
        row["score"]["finite_prefix_frames"] = EXPECTED
        row["score"]["raw_error_coverage"] = 1.0
        row["position_rmse"] = [0.001] * EXPECTED
        row["velocity_rmse"] = [0.001] * EXPECTED
        row["position_ade"] = [0.001] * EXPECTED
        row["velocity_ade"] = [0.001] * EXPECTED
        evaluation.write_text(json.dumps(payload), encoding="utf-8")
    else:  # pragma: no cover - protects the test table itself.
        raise AssertionError(mutation)

    with pytest.raises(validator.ValidationError, match=pattern):
        validator.validate_receipt(evaluation)


def test_run_validation_returns_nonzero_credit_fail_closed_without_writing(tmp_path):
    evaluation, trajectory = _write_fixture(tmp_path)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["cases"][CASE_ID]["case_id"] = "other-case"
    evaluation.write_text(json.dumps(payload), encoding="utf-8")
    before = trajectory.stat().st_mtime_ns

    result = validator.run_validation(evaluation)

    assert result["passed"] is False
    assert result["fail_closed"] is True
    assert result["qualification_credit"] == 0
    assert result["production_artifacts_touched"] is False
    assert trajectory.stat().st_mtime_ns == before


def test_cli_emits_canonical_pass_and_fail_closed_json(tmp_path, capsys):
    evaluation, _ = _write_fixture(tmp_path)
    assert validator.main([str(evaluation)]) == 0
    passed = json.loads(capsys.readouterr().out)
    assert passed["passed"] is True
    assert capsys.readouterr().out == ""

    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["future_state_inputs"] = True
    evaluation.write_text(json.dumps(payload), encoding="utf-8")
    assert validator.main([str(evaluation)]) == 1
    failed_text = capsys.readouterr().out.strip()
    failed = json.loads(failed_text)
    assert failed["passed"] is False
    assert failed["fail_closed"] is True
