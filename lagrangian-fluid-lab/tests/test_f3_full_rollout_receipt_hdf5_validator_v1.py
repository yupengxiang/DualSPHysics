"""Synthetic-only tests for the read-only F3 rollout/HDF5 sidecar validator."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as validator


EXPECTED = 835
CASE_ID = "F3_SYNTHETIC_RECEIPT"
CURRENT_MANIFEST_TRAJECTORY_BYTES = 723_147_992


def _metric_values(executed: int) -> list[float | None]:
    return [0.001 * (index + 1) if index < executed else None
            for index in range(EXPECTED)]


def _write_fixture(
    tmp_path: Path,
    *,
    maximum_steps: int | None = None,
    unsafe_link: str | None = None,
) -> tuple[Path, Path]:
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
        if unsafe_link == "soft":
            handle["unsafe_soft"] = h5py.SoftLink("/time")
        elif unsafe_link == "external":
            handle["unsafe_external"] = h5py.ExternalLink("outside.h5", "/time")
        elif unsafe_link == "vds":
            source = tmp_path / "vds-source.h5"
            with h5py.File(source, "w") as source_handle:
                source_handle["source"] = np.array([1.0], dtype=np.float64)
            layout = h5py.VirtualLayout(shape=(1,), dtype=np.float64)
            source_spec = h5py.VirtualSource(str(source), "source", shape=(1,))
            layout[:] = source_spec
            handle.create_virtual_dataset("unsafe_vds", layout)
        elif unsafe_link is not None:  # pragma: no cover - protects the fixture table.
            raise AssertionError(unsafe_link)

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
    assert result["checks"]["trajectory_file_bytes"] == len(before)
    assert result["checks"]["trajectory_file_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["checks"]["trajectory_filesystem_identity_stable"] is True
    assert trajectory.read_bytes() == before


def test_current_manifest_sized_trajectory_above_512_mib_passes(tmp_path):
    """The observed full current-manifest byte size remains a valid input."""
    evaluation, trajectory = _write_fixture(tmp_path)
    os.truncate(trajectory, CURRENT_MANIFEST_TRAJECTORY_BYTES)

    assert trajectory.stat().st_size > 512 * 1024 * 1024
    assert trajectory.stat().st_size < validator.MAX_HDF5_BYTES

    result = validator.validate_receipt(evaluation)

    assert result["passed"] is True
    assert result["checks"]["trajectory_file_bytes"] == CURRENT_MANIFEST_TRAJECTORY_BYTES
    assert result["checks"]["trajectory_frames"] == EXPECTED + 1
    assert result["checks"]["trajectory_transitions"] == EXPECTED


def test_trajectory_over_new_bounded_size_is_rejected_before_read(tmp_path):
    evaluation, trajectory = _write_fixture(tmp_path)
    os.truncate(trajectory, validator.MAX_HDF5_BYTES + 1)

    with pytest.raises(validator.ValidationError, match="bounded size"):
        validator.validate_receipt(evaluation)


def test_small_fixture_remains_below_new_bound_and_passes(tmp_path):
    evaluation, trajectory = _write_fixture(tmp_path)
    assert trajectory.stat().st_size < 512 * 1024 * 1024
    assert trajectory.stat().st_size < validator.MAX_HDF5_BYTES

    result = validator.validate_receipt(evaluation)

    assert result["passed"] is True
    assert result["checks"]["trajectory_file_bytes"] == trajectory.stat().st_size


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


@pytest.mark.parametrize("link_kind,pattern", [
    ("soft", "non-hard.*external/soft"),
    ("external", "non-hard.*external/soft"),
    ("vds", "virtual dataset"),
])
def test_hdf5_external_soft_and_vds_links_fail_closed_before_dereference(
    tmp_path, link_kind, pattern
):
    evaluation, _ = _write_fixture(tmp_path, unsafe_link=link_kind)

    with pytest.raises(validator.ValidationError, match=pattern):
        validator.validate_receipt(evaluation)


def test_symlinked_trajectory_is_rejected_without_following_the_leaf(tmp_path):
    evaluation, trajectory = _write_fixture(tmp_path)
    symlink = tmp_path / "trajectory-symlink.h5"
    symlink.symlink_to(trajectory)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["cases"][CASE_ID]["trajectory_output"] = symlink.name
    evaluation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(validator.ValidationError, match="regular file|symlinks"):
        validator.validate_receipt(evaluation)


def test_symlinked_parent_directory_is_rejected_before_leaf_open(tmp_path):
    evaluation, trajectory = _write_fixture(tmp_path)
    real_dir = tmp_path / "real-parent"
    real_dir.mkdir()
    moved_trajectory = real_dir / trajectory.name
    trajectory.rename(moved_trajectory)
    symlink_dir = tmp_path / "parent-symlink"
    symlink_dir.symlink_to(real_dir, target_is_directory=True)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["cases"][CASE_ID]["trajectory_output"] = str(
        symlink_dir / moved_trajectory.name
    )
    evaluation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(validator.ValidationError, match="parent component|unsafe"):
        validator.validate_receipt(evaluation)


def test_hardlinked_trajectory_is_rejected_before_hdf5_open(tmp_path):
    evaluation, trajectory = _write_fixture(tmp_path)
    hardlink = tmp_path / "trajectory-hardlink.h5"
    os.link(trajectory, hardlink)
    payload = json.loads(evaluation.read_text(encoding="utf-8"))
    payload["cases"][CASE_ID]["trajectory_output"] = hardlink.name
    evaluation.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(validator.ValidationError, match="hard link"):
        validator.validate_receipt(evaluation)


def test_path_identity_drift_after_descriptor_read_fails_closed(tmp_path, monkeypatch):
    evaluation, trajectory = _write_fixture(tmp_path)
    real_lstat = validator.os.lstat
    calls = 0

    def drifting_lstat(path):
        nonlocal calls
        info = real_lstat(path)
        if Path(path) == trajectory:
            calls += 1
            if calls == 2:
                return SimpleNamespace(
                    st_dev=info.st_dev,
                    st_ino=info.st_ino + 1,
                    st_mode=info.st_mode,
                    st_nlink=info.st_nlink,
                    st_size=info.st_size,
                    st_mtime_ns=info.st_mtime_ns,
                    st_ctime_ns=info.st_ctime_ns,
                )
        return info

    monkeypatch.setattr(validator.os, "lstat", drifting_lstat)
    with pytest.raises(validator.ValidationError, match="path identity changed"):
        validator.validate_receipt(evaluation)


def test_fd_identity_drift_during_read_fails_closed(tmp_path, monkeypatch):
    evaluation, _ = _write_fixture(tmp_path)
    real_fstat = validator.os.fstat
    calls = 0

    def drifting_fstat(descriptor):
        nonlocal calls
        info = real_fstat(descriptor)
        calls += 1
        if calls == 2:
            return SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_mode=info.st_mode,
                st_nlink=info.st_nlink,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns + 1,
                st_ctime_ns=info.st_ctime_ns,
            )
        return info

    monkeypatch.setattr(validator.os, "fstat", drifting_fstat)
    with pytest.raises(validator.ValidationError, match="fd identity changed"):
        validator.validate_receipt(evaluation)


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
