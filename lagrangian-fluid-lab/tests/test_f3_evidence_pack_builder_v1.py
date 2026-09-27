"""Synthetic-only tests for the read-only F3 canonical evidence packer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import f3_evidence_pack_builder_v1 as builder


EXPECTED = 835
CASE_ID = "F3_SYNTHETIC_EVIDENCE"


def _metrics() -> list[float]:
    return [0.001 * (index + 1) for index in range(EXPECTED)]


def _write_fixture(
    tmp_path: Path,
    *,
    include_checkpoint: bool = True,
) -> dict[str, Path]:
    trajectory = tmp_path / "trajectory.h5"
    frames = EXPECTED + 1
    particles = 3
    position = np.arange(frames, dtype=np.float32)[:, None, None] * 0.001
    position = np.broadcast_to(position, (frames, particles, 3)).copy()
    velocity = np.full((frames, particles, 3), 0.25, dtype=np.float32)
    valid = np.ones((frames, particles), dtype=np.bool_)
    with h5py.File(trajectory, "w") as handle:
        handle.attrs["schema_version"] = 1
        handle.attrs["future_state_inputs"] = False
        handle.attrs["autonomous_prediction"] = True
        handle.attrs["case_id"] = CASE_ID
        handle["time"] = np.arange(frames, dtype=np.float64) * 0.01
        handle["position"] = position
        handle["velocity"] = velocity
        handle["particle_id"] = np.array([101, 102, 201], dtype=np.int64)
        handle["particle_zone"] = np.array([0, 0, 1], dtype=np.int32)
        handle["mass"] = np.ones(particles, dtype=np.float64)
        handle["valid"] = valid

    trajectory_digest = hashlib.sha256(trajectory.read_bytes()).hexdigest()
    trajectory_bytes = trajectory.stat().st_size
    progress = tmp_path / "progress.json"
    rollout = tmp_path / "rollout.json"
    progress_payload = {
        "schema": "core.rollout.progress.v1",
        "case_id": CASE_ID,
        "status": "completed",
        "completed_frames": EXPECTED,
        "expected_frames": EXPECTED,
        "frames_expected": EXPECTED,
        "frames_executed": EXPECTED,
        "particles": particles,
        "elapsed_seconds": 1.5,
        "time_s": EXPECTED * 0.01,
        "trajectory_output": str(trajectory),
        "progress_every": 25,
        "autonomous": True,
        "future_state_inputs": False,
        "execution_complete": True,
        "finite_rollout_complete": True,
        "scientific_status": "not_assessed",
        "scientific_failure_category": None,
        "scientific_first_failure_frame": None,
        "trajectory_sha256": trajectory_digest,
        "trajectory_bytes": trajectory_bytes,
    }
    progress.write_text(json.dumps(progress_payload), encoding="utf-8")

    values = _metrics()
    nested = {
        "schema": "core.rollout.v1",
        "case_id": CASE_ID,
        "frames_predicted": EXPECTED,
        "frames_expected": EXPECTED,
        "frames_executed": EXPECTED,
        "expected_frames": EXPECTED,
        "executed": True,
        "position_rmse": values,
        "velocity_rmse": values,
        "position_ade": values,
        "velocity_ade": values,
        "failure_category": None,
        "first_failure_frame": None,
        "execution_complete": True,
        "finite_rollout_complete": True,
        "requested_window_execution_complete": True,
        "requested_window_finite_rollout_complete": True,
        "complete_over_registered_denominator": True,
        "scientific_status": "not_assessed",
        "scientific_failure_category": None,
        "scientific_first_failure_frame": None,
        "future_state_inputs": False,
        "trajectory_output": str(trajectory),
        "progress_output": str(progress),
        "physics": {
            "summary": {
                "expected_frames": EXPECTED,
                "completed_frames": EXPECTED,
                "mass_error_abs_max_kg": 0.0,
            }
        },
    }
    row = {
        **nested,
        "rollout": nested,
        "score": {
            "expected_frames": EXPECTED,
            "finite_prefix_frames": EXPECTED,
            "executed": True,
            "complete": True,
            "failure_category": None,
            "raw_error_coverage": 1.0,
            "selection_score": 0.0,
        },
        "trajectory_sha256": trajectory_digest,
        "trajectory_bytes": trajectory_bytes,
    }
    evaluation_payload = {
        "schema": "core.evaluation.v1",
        "evaluation_mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "model_kind": "graph_raw",
        "checkpoint": None,
        "maximum_steps": None,
        "registered_case_ids": [CASE_ID],
        "selected_case_ids": [CASE_ID],
        "expected_frames": {CASE_ID: EXPECTED},
        "cases": {CASE_ID: row},
        "autonomous": True,
        "future_state_inputs": False,
    }

    checkpoint = tmp_path / "checkpoint.bin"
    receipt = tmp_path / "training.json"
    if include_checkpoint:
        checkpoint.write_bytes(b"synthetic-checkpoint-v1\n")
        reference = {
            "path": str(checkpoint),
            "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "bytes": checkpoint.stat().st_size,
            "update": 500,
        }
        evaluation_payload["checkpoint"] = str(checkpoint)
        progress_payload["checkpoint"] = str(checkpoint)
        progress.write_text(json.dumps(progress_payload), encoding="utf-8")
        receipt.write_text(json.dumps({
            "schema": "core.training.v1",
            "completed_updates": 500,
            "checkpoint_verified": True,
            "evidence_status": "complete",
            "evidence": {"status": "complete"},
            "checkpoint": reference,
            "checkpoints": [reference],
        }), encoding="utf-8")

    rollout.write_text(json.dumps(evaluation_payload), encoding="utf-8")
    return {
        "rollout": rollout,
        "progress": progress,
        "trajectory": trajectory,
        "checkpoint": checkpoint,
        "receipt": receipt,
    }


def _build(paths: dict[str, Path], **kwargs):
    return builder.build_evidence_pack(
        paths["rollout"], paths["progress"], paths["trajectory"], **kwargs)


def test_complete_pack_binds_inputs_and_is_deterministic(tmp_path):
    paths = _write_fixture(tmp_path)
    before = {name: path.read_bytes() for name, path in paths.items()
              if path.exists()}

    result = _build(paths, training_receipt=paths["receipt"])

    assert result["passed"] is True
    assert result["fail_closed"] is False
    assert result["formal_eligible"] is False
    assert result["t1_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["credit"] == 0
    assert result["source"]["expected_transitions"] == EXPECTED
    assert result["checks"] == {
        "failure_absent": True,
        "full_denominator": True,
        "future_state_inputs": True,
        "hdf5_finite_state": True,
        "hdf5_shape": True,
        "hdf5_valid_prefix": True,
        "maximum_steps_semantics": True,
        "path_references": True,
        "progress_complete": True,
        "sha256_and_bytes": True,
    }
    assert result["artifacts"]["checkpoint"]["bytes"] == paths["checkpoint"].stat().st_size
    assert len(result["artifacts"]["training_receipt_checkpoints"]) == 2

    first = builder.canonical_json(result)
    second = builder.canonical_json(_build(paths, training_receipt=paths["receipt"]))
    assert first == second
    assert first == builder.canonical_json(json.loads(first))
    assert {name: path.read_bytes() for name, path in paths.items()
            if path.exists()} == before


def test_optional_checkpoint_and_training_receipt_are_allowed(tmp_path):
    paths = _write_fixture(tmp_path, include_checkpoint=False)

    result = _build(paths)

    assert result["passed"] is True
    assert result["artifacts"]["checkpoint"] is None
    assert result["artifacts"]["training_receipt"] is None


@pytest.mark.parametrize("mutation", ["bounded", "running", "future"])
def test_incomplete_or_future_state_inputs_fail_closed(tmp_path, mutation):
    paths = _write_fixture(tmp_path, include_checkpoint=False)
    payload = json.loads(paths["rollout"].read_text(encoding="utf-8"))
    progress = json.loads(paths["progress"].read_text(encoding="utf-8"))
    if mutation == "bounded":
        payload["maximum_steps"] = 10
    elif mutation == "running":
        progress["status"] = "running"
    elif mutation == "future":
        payload["future_state_inputs"] = True
    else:  # pragma: no cover
        raise AssertionError(mutation)
    paths["rollout"].write_text(json.dumps(payload), encoding="utf-8")
    paths["progress"].write_text(json.dumps(progress), encoding="utf-8")

    result = builder.run_evidence_pack(
        paths["rollout"], paths["progress"], paths["trajectory"])

    assert result["passed"] is False
    assert result["fail_closed"] is True
    assert result["formal_eligible"] is False
    assert result["t1_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["credit"] == 0


@pytest.mark.parametrize("mutation", ["digest", "path", "nonfinite", "invalid"])
def test_digest_path_and_hdf5_contracts_fail_closed(tmp_path, mutation):
    paths = _write_fixture(tmp_path, include_checkpoint=False)
    payload = json.loads(paths["rollout"].read_text(encoding="utf-8"))
    if mutation == "digest":
        payload["cases"][CASE_ID]["trajectory_sha256"] = "0" * 64
        paths["rollout"].write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "path":
        payload["cases"][CASE_ID]["trajectory_output"] = str(tmp_path / "other.h5")
        paths["rollout"].write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "nonfinite":
        with h5py.File(paths["trajectory"], "r+") as handle:
            handle["position"][1, 0, 0] = np.nan
    elif mutation == "invalid":
        with h5py.File(paths["trajectory"], "r+") as handle:
            handle["valid"][1, 0] = False
    else:  # pragma: no cover
        raise AssertionError(mutation)

    result = builder.run_evidence_pack(
        paths["rollout"], paths["progress"], paths["trajectory"])

    assert result["passed"] is False
    assert result["fail_closed"] is True
    assert result["qualification_credit"] == 0


def test_cli_writes_canonical_fail_closed_output(tmp_path):
    paths = _write_fixture(tmp_path, include_checkpoint=False)
    payload = json.loads(paths["progress"].read_text(encoding="utf-8"))
    payload["status"] = "failed"
    paths["progress"].write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "evidence-pack.json"

    exit_code = builder.main([
        str(paths["rollout"]), str(paths["progress"]), str(paths["trajectory"]),
        "--output", str(output),
    ])

    assert exit_code == 1
    written = output.read_text(encoding="utf-8")
    assert written.endswith("\n")
    parsed = json.loads(written)
    assert parsed["fail_closed"] is True
    assert written[:-1] == builder.canonical_json(parsed)
