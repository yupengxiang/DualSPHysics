"""Tests for the F3 hidden16 terminal-evidence generation/binding bridge."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import f3_graph_raw_hidden16_terminal_evidence_bridge_v1 as bridge


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> tuple[int, str]:
    raw = bridge.canonical_json(payload).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def _write_candidate(tmp_path: Path, *, seed: int = 17) -> tuple[Path, dict[str, Path]]:
    evaluation_path = tmp_path / f"seed{seed}-evaluation.json"
    evaluation_path.write_bytes(b'{"opaque":"evaluation body"}\n')
    trajectory_path = tmp_path / f"seed{seed}-trajectory.h5"
    trajectory_path.write_bytes(b"this is intentionally not an HDF5 file")
    checkpoint_path = tmp_path / f"seed{seed}-checkpoint.pt"
    checkpoint_path.write_bytes(b"checkpoint bytes are never opened by the bridge")

    validator_payload = {
        "schema": "core.f3.full_rollout_receipt_hdf5_validation.v1",
        "passed": True,
        "fail_closed": False,
        "diagnostic_only": True,
        "synthetic_only": False,
        "production_artifacts_touched": False,
        "qualification_credit": 0,
        "case_id": "F3_DEV_00_a0p903125",
        "evaluation_json": str(evaluation_path),
        "trajectory_hdf5": str(trajectory_path),
        "expected_transitions": 835,
        "frames_executed": 835,
        "complete": True,
        "incomplete": False,
        "checks": {
            "case_binding": True,
            "shape": True,
            "time": True,
            "valid": True,
            "future_state_inputs": True,
            "completion_semantics": True,
            "trajectory_frames": 836,
            "trajectory_transitions": 835,
            "executed_frame_count": 836,
            "tail_frame_count": 0,
        },
        "row_fields_checked": ["case_id"],
    }
    validator_path = tmp_path / f"seed{seed}-validator.json"
    validator_bytes, validator_sha = _write_json(validator_path, validator_payload)

    training_payload = {
        "schema": "core.training.v1",
        "evidence_status": "complete",
        "completed_updates": 500,
        "model_kind": "graph_raw",
        "seed": seed,
        "checkpoint_verified": True,
        "config": {
            "model_kind": "graph_raw",
            "hidden": 16,
            "seed": seed,
            "updates": 500,
        },
        "checkpoint": {
            "path": str(checkpoint_path),
            "sha256": "c" * 64,
            "update": 500,
        },
    }
    training_path = tmp_path / f"seed{seed}-training.json"
    training_bytes, training_sha = _write_json(training_path, training_payload)

    evaluation_bytes = evaluation_path.stat().st_size
    evaluation_sha = _sha256(evaluation_path)
    trajectory_bytes = trajectory_path.stat().st_size
    trajectory_sha = "d" * 64
    checkpoint_bytes = checkpoint_path.stat().st_size

    summary = {
        "schema": f"core.f3.graph_raw.hidden16.seed{seed}.full835.rollout_diagnostic.summary.v1",
        "report_id": f"synthetic-seed{seed}-diagnostic-summary",
        "status": "completed_diagnostic",
        "diagnostic_only": True,
        "formal_eligible": False,
        "future_state_inputs": False,
        "qualification_credit": 0,
        "qualification": {
            "formal_training": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification_credit": 0,
        },
        "source": {
            "baseline_git_commit": "a" * 40,
            "source_script_sha256": {"scripts/core_learning.py": "e" * 64},
            "case": {
                "case_id": "F3_DEV_00_a0p903125",
                "family": "F3",
                "evaluation_role": "development_extrapolation",
            },
        },
        "protocol": {
            "model_kind": "graph_raw",
            "seed": seed,
            "hidden": 16,
            "updates": 500,
            "maximum_steps": 835,
            "diagnostic": True,
            "autonomous": True,
            "future_state_inputs": False,
            "split": "test",
        },
        "training": {
            "schema": "core.training.v1",
            "status": "completed",
            "evidence_status": "complete",
            "completed_updates": 500,
            "model_kind": "graph_raw",
            "seed": seed,
            "hidden": 16,
            "checkpoint_verified": True,
        },
        "evaluation": {
            "schema": "core.evaluation.v1",
            "status": "completed",
            "mode": "diagnostic",
            "diagnostic": True,
            "formal_eligible": False,
            "requested_steps": 835,
            "frames_executed": 835,
            "trajectory_frames_including_initial": 836,
            "requested_window_complete": True,
            "finite_rollout_complete_for_requested_window": True,
            "expected_full_case_transitions": 835,
            "expected_full_case_frames": 836,
            "full_registered_denominator_complete": True,
            "failure_category": None,
            "first_failure_frame": None,
            "future_state_inputs": False,
            "receipt": {
                "path": str(evaluation_path),
                "bytes": evaluation_bytes,
                "sha256": evaluation_sha,
            },
            "hdf5_validation": {
                "path": str(validator_path),
                "bytes": validator_bytes,
                "sha256": validator_sha,
                "schema": "core.f3.full_rollout_receipt_hdf5_validation.v1",
                "passed": True,
                "complete": True,
                "production_artifacts_touched": False,
                "qualification_credit": 0,
                "synthetic_only": False,
                "trajectory_frames": 836,
                "trajectory_transitions": 835,
                "executed_frame_count": 836,
                "tail_frame_count": 0,
            },
        },
        "trajectory": {
            "path": str(trajectory_path),
            "bytes": trajectory_bytes,
            "sha256": trajectory_sha,
        },
        "bindings": {
            "training_receipt": {
                "path": str(training_path),
                "bytes": training_bytes,
                "sha256": training_sha,
            },
            "checkpoint": {
                "path": str(checkpoint_path),
                "bytes": checkpoint_bytes,
                "sha256": "c" * 64,
                "schema": "core.checkpoint.v1",
                "update": 500,
                "model_kind": "graph_raw",
                "hidden": 16,
                "seed": seed,
            },
        },
        "side_effects": {
            "rollout_inputs_read_only": True,
            "source_modified_by_rollout": False,
            "production_hdf5_modified": False,
            "manifest_modified": False,
            "registry_mutation": False,
            "completion_mutation": False,
            "ledger_mutation": False,
            "denominator_mutation": False,
            "gate_mutation": False,
            "formal_training_counted": False,
            "diagnostic_counted_as_T1_or_T2": False,
            "future_state_inputs": False,
        },
    }
    summary_path = tmp_path / f"seed{seed}-summary.json"
    _write_json(summary_path, summary)
    return summary_path, {
        "evaluation": evaluation_path,
        "validator": validator_path,
        "training": training_path,
        "trajectory": trajectory_path,
        "checkpoint": checkpoint_path,
    }


def test_real_like_terminal_candidate_binds_without_opening_hdf5(tmp_path: Path):
    summary_path, _ = _write_candidate(tmp_path)
    report = bridge.build_report(
        tmp_path,
        candidates={17: {"summary": summary_path}},
        observed_at_utc="2026-09-28T12:00:00Z",
    )

    assert report["status"] == "bound_terminal_diagnostic"
    assert report["source_bound"] is True
    assert report["bound_seeds"] == [17]
    assert report["missing_seeds"] == [29, 43]
    row = next(row for row in report["seed_matrix"] if row["seed"] == 17)
    receipt = row["terminal_receipt"]
    assert receipt["transitions"] == 835
    assert receipt["frames"] == 836
    assert receipt["terminal_markers"]["terminal"] is True
    assert receipt["qualification_credit"] == 0
    assert receipt["trajectory_binding"]["content_opened"] is False
    assert receipt["trajectory_binding"]["stat"]["stat_only"] is True
    assert receipt["side_effects"]["trajectory_hdf5_opened"] is False
    assert receipt["side_effects"]["progress_opened"] is False
    assert report["side_effects"]["gate_mutation"] == 0


def test_evaluation_sha_drift_blocks_candidate(tmp_path: Path):
    summary_path, paths = _write_candidate(tmp_path)
    paths["evaluation"].write_bytes(b'{"opaque":"evaluation bodx"}\n')
    report = bridge.build_report(tmp_path, candidates={17: {"summary": summary_path}})

    assert report["source_bound"] is False
    row = next(row for row in report["seed_matrix"] if row["seed"] == 17)
    assert row["status"] == "blocked_fail_closed"
    assert "evaluation source SHA drift" in row["blocked_reasons"][0]
    assert row["terminal_receipt"] is None


def test_validator_or_training_sha_drift_blocks_candidate(tmp_path: Path):
    summary_path, paths = _write_candidate(tmp_path)
    paths["validator"].write_bytes(paths["validator"].read_bytes() + b" ")
    report = bridge.build_report(tmp_path, candidates={17: {"summary": summary_path}})

    assert report["source_bound"] is False
    row = next(row for row in report["seed_matrix"] if row["seed"] == 17)
    assert row["status"] == "blocked_fail_closed"
    assert "validator source SHA/bytes drift" in row["blocked_reasons"][0]


def test_hidden16_or_horizon_drift_blocks_candidate(tmp_path: Path):
    summary_path, _ = _write_candidate(tmp_path)
    payload = json.loads(summary_path.read_text())
    payload["protocol"]["hidden"] = 8
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    report = bridge.build_report(tmp_path, candidates={17: {"summary": summary_path}})

    assert report["source_bound"] is False
    row = next(row for row in report["seed_matrix"] if row["seed"] == 17)
    assert row["status"] == "blocked_fail_closed"
    assert "protocol.hidden drift" in row["blocked_reasons"][0]


def test_missing_candidate_matrix_is_fail_closed(tmp_path: Path):
    report = bridge.build_report(tmp_path, candidates={})

    assert report["status"] == "blocked_fail_closed"
    assert report["source_bound"] is False
    assert report["bound_seeds"] == []
    assert report["missing_seeds"] == [17, 29, 43]
    assert all(row["terminal_receipt"] is None for row in report["seed_matrix"])


def test_report_and_chinese_render_are_bounded_and_canonical(tmp_path: Path):
    summary_path, _ = _write_candidate(tmp_path)
    report = bridge.build_report(tmp_path, candidates={17: {"summary": summary_path}})
    output = tmp_path / "report.json"
    zh_output = tmp_path / "report.zh-CN.md"
    bridge.write_outputs(report, output, zh_output)

    assert json.loads(output.read_text()) == report
    assert output.stat().st_size < 100_000
    assert zh_output.stat().st_size < 20_000
    assert "diagnostic-only" in zh_output.read_text()


def test_forbidden_progress_json_is_not_accepted_as_summary(tmp_path: Path):
    summary_path, _ = _write_candidate(tmp_path)
    forbidden = tmp_path / "seed17-evaluation-progress.json"
    forbidden.write_bytes(summary_path.read_bytes())
    report = bridge.build_report(tmp_path, candidates={17: {"summary": forbidden}})

    assert report["source_bound"] is False
    row = next(row for row in report["seed_matrix"] if row["seed"] == 17)
    assert row["status"] == "blocked_fail_closed"
    assert "forbidden progress" in row["blocked_reasons"][0]
