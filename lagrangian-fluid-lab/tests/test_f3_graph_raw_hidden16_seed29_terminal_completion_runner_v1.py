"""Tests for the seed29-specific F3 hidden16 terminal completion runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import (
    f3_graph_raw_hidden16_seed29_terminal_completion_runner_v1 as runner,
)


def _write_json(path: Path, payload: dict) -> tuple[int, str]:
    raw = runner.canonical_json(payload).encode("utf-8") + b"\n"
    path.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def _training(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    checkpoint = tmp_path / "seed29-checkpoint.pt"
    checkpoint.write_bytes(b"checkpoint content is never opened")
    training = {
        "schema": "core.training.v1",
        "evidence_status": "complete",
        "completed_updates": 500,
        "model_kind": "graph_raw",
        "seed": 29,
        "checkpoint_verified": True,
        "config": {
            "model_kind": "graph_raw",
            "hidden": 16,
            "seed": 29,
            "paired_seed": 29,
            "updates": 500,
            "max_neighbors": 192,
            "target_normalization": "raw_dual_increment_train_shared",
        },
        "checkpoint": {
            "path": str(checkpoint),
            "bytes": checkpoint.stat().st_size,
            "sha256": "c" * 64,
            "update": 500,
        },
    }
    training_path = tmp_path / "seed29-training.json"
    _write_json(training_path, training)
    return training_path, {"checkpoint": checkpoint}


def _evaluation(
    tmp_path: Path,
    training_paths: dict[str, Path],
    *,
    complete: bool = True,
    model_kind: str = "graph_raw",
) -> tuple[Path, dict[str, Path]]:
    evaluation = tmp_path / "seed29-terminal-evaluation.json"
    trajectory = tmp_path / "seed29-terminal-trajectory.h5"
    progress = tmp_path / "seed29-terminal-evaluation-progress.json"
    trajectory.write_bytes(b"trajectory content is never opened")
    progress.write_bytes(b'{"status":"completed"}\n')
    frames = 835 if complete else 834
    row = {
        "case_id": runner.CASE_ID,
        "executed": complete,
        "execution_complete": complete,
        "expected_frames": runner.TRANSITIONS,
        "frames_expected": runner.TRANSITIONS,
        "frames_predicted": frames,
        "frames_executed": frames,
        "finite_rollout_complete": complete,
        "failure_category": None if complete else "runtime_error",
        "first_failure_frame": None if complete else frames + 1,
        "future_state_inputs": False,
        "rollout": {
            "schema": "core.rollout.v1",
            "case_id": runner.CASE_ID,
            "executed": complete,
            "execution_complete": complete,
            "expected_frames": runner.TRANSITIONS,
            "frames_expected": runner.TRANSITIONS,
            "frames_predicted": frames,
            "frames_executed": frames,
            "finite_rollout_complete": complete,
            "failure_category": None if complete else "runtime_error",
            "first_failure_frame": None if complete else frames + 1,
            "future_state_inputs": False,
            "trajectory_output": str(trajectory),
            "progress_output": str(progress),
        },
    }
    payload = {
        "schema": "core.evaluation.v1",
        "model_kind": model_kind,
        "evaluation_mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "future_state_inputs": False,
        "maximum_steps": runner.TRANSITIONS,
        "checkpoint": str(training_paths["checkpoint"]),
        "expected_frames": {runner.CASE_ID: runner.TRANSITIONS},
        "selected_case_ids": [runner.CASE_ID],
        "cases": {runner.CASE_ID: row},
    }
    _write_json(evaluation, payload)
    return evaluation, {"trajectory": trajectory, "progress": progress}


def test_missing_terminal_is_fail_closed_without_opening_forbidden_files(tmp_path: Path):
    training_path, _ = _training(tmp_path)
    report = runner.build_report(
        tmp_path,
        training_path=training_path,
        evaluation_path=tmp_path / "missing-evaluation.json",
        scan_existing=False,
    )

    assert report["status"] == "blocked_missing_terminal"
    assert report["source_bound"] is False
    assert report["seed29_terminal_receipt"] is None
    assert report["input_boundary"]["checkpoint_opened"] is False
    assert report["input_boundary"]["trajectory_hdf5_opened"] is False
    assert report["input_boundary"]["progress_opened"] is False
    assert runner.validate_report(report) == []


def test_completed_hidden16_seed29_binds_training_evaluation_and_stat_only_trajectory(
    tmp_path: Path,
):
    training_path, paths = _training(tmp_path)
    evaluation_path, output_paths = _evaluation(tmp_path, paths)
    report = runner.build_report(
        tmp_path,
        training_path=training_path,
        evaluation_path=evaluation_path,
        observed_at_utc="2026-09-28T12:00:00Z",
        scan_existing=False,
    )

    assert report["status"] == "bound_terminal_diagnostic"
    assert report["source_bound"] is True
    receipt = report["seed29_terminal_receipt"]
    assert receipt["seed"] == 29
    assert receipt["hidden"] == 16
    assert receipt["transitions"] == 835
    assert receipt["frames"] == 836
    assert receipt["terminal_markers"]["terminal"] is True
    assert receipt["terminal_markers"]["execution_complete"] is True
    assert receipt["evaluation_binding"]["content_opened"] is True
    assert receipt["trajectory_binding"]["content_opened"] is False
    assert receipt["trajectory_binding"]["stat_only"] is True
    assert receipt["trajectory_binding"]["path"] == str(output_paths["trajectory"].resolve())
    assert receipt["progress_binding"]["completion_not_inferred"] is True
    assert report["side_effects"]["trajectory_hdf5_opened"] is False
    assert report["side_effects"]["progress_opened"] is False
    assert report["qualification_credit"] == 0
    assert runner.validate_report(report) == []


def test_incomplete_or_hidden_drift_rejects_terminal_candidate(tmp_path: Path):
    training_path, paths = _training(tmp_path)
    incomplete_path, _ = _evaluation(tmp_path, paths, complete=False)
    report = runner.build_report(
        tmp_path,
        training_path=training_path,
        evaluation_path=incomplete_path,
        scan_existing=False,
    )
    assert report["source_bound"] is False
    assert any("frames_predicted" in reason for reason in report["blocked_reasons"])

    complete_path, _ = _evaluation(tmp_path, paths, complete=True, model_kind="mlp")
    report = runner.build_report(
        tmp_path,
        training_path=training_path,
        evaluation_path=complete_path,
        scan_existing=False,
    )
    assert report["source_bound"] is False
    assert any("model_kind drift" in reason for reason in report["blocked_reasons"])


def test_existing_namespace_collision_never_launches(tmp_path: Path, monkeypatch):
    training_path, _ = _training(tmp_path)
    namespace = tmp_path / "f3-graph-raw500-hidden16-seed29-full835-20260928-terminal-closure-v1"
    namespace.with_name(namespace.name + "-evaluation.json").write_text("existing", encoding="utf-8")
    monkeypatch.setattr(runner, "_gpu_snapshot", lambda _index: (_ for _ in ()).throw(AssertionError("GPU probe must not run")))

    launch = runner.launch_diagnostic(
        tmp_path,
        gpu_index=7,
        namespace=namespace,
        training_path=training_path,
    )
    assert launch["status"] == "blocked_namespace_collision"
    assert launch["attempted"] is False


def test_outputs_are_bounded_and_canonical(tmp_path: Path):
    training_path, _ = _training(tmp_path)
    report = runner.build_report(
        tmp_path,
        training_path=training_path,
        evaluation_path=tmp_path / "missing-evaluation.json",
        scan_existing=False,
    )
    output = tmp_path / "report.json"
    zh_output = tmp_path / "report.zh-CN.md"
    runner.write_outputs(report, output, zh_output)
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert output.stat().st_size < 1 * 1024 * 1024
    assert "seed29" in zh_output.read_text(encoding="utf-8")
