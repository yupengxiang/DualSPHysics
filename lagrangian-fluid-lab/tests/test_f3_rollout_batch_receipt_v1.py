"""Synthetic JSON-only tests for the F3 diagnostic batch receipt reducer."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_rollout_batch_receipt_v1 as reducer


EXPECTED = 835
MANIFEST_PATH = "campaigns/core-v1/f3-dataset-v2.json"
MANIFEST_SHA = "a" * 64
CHECKPOINT_PATH = "checkpoints/graph-raw-seed17.pt"
CHECKPOINT_SHA = "b" * 64


def _metric_values(executed: int) -> list[float | None]:
    return [0.001 * (index + 1) if index < executed else None
            for index in range(EXPECTED)]


def _binding(case_id: str) -> dict:
    return {
        "manifest": {"path": MANIFEST_PATH, "sha256": MANIFEST_SHA},
        "case": {
            "case_id": case_id,
            "path": f"cases/{case_id}/source.h5",
            "sha256": (
                "c" + "0" * 63 if case_id.endswith("00") else
                "d" + "0" * 63 if case_id.endswith("01") else
                "e" + "0" * 63
            ),
        },
        "checkpoint": {"path": CHECKPOINT_PATH, "sha256": CHECKPOINT_SHA},
    }


def _case_bindings(*case_ids: str) -> dict[str, dict[str, str]]:
    return {
        case_id: {
            "path": f"cases/{case_id}/source.h5",
            "sha256": ("c" + "0" * 63) if case_id.endswith("00") else (
                "d" + "0" * 63 if case_id.endswith("01") else "e" + "0" * 63
            ),
        }
        for case_id in case_ids
    }


def _write_item(
    tmp_path: Path,
    case_id: str,
    *,
    status: str = "completed",
    executed: int = EXPECTED,
    failure_category: str | None = None,
    include_progress: bool = False,
) -> Path:
    complete = status == "completed"
    row = {
        "case_id": case_id,
        "frames_predicted": executed,
        "frames_expected": EXPECTED,
        "frames_executed": executed,
        "expected_frames": EXPECTED,
        "executed": True,
        "position_rmse": _metric_values(executed),
        "velocity_rmse": _metric_values(executed),
        "position_ade": _metric_values(executed),
        "velocity_ade": _metric_values(executed),
        "failure_category": failure_category,
        "first_failure_frame": None if failure_category is None else executed + 1,
        "execution_complete": complete,
        "finite_rollout_complete": complete,
        "future_state_inputs": False,
        "trajectory_output": f"diagnostic/{case_id}-trajectory.h5",
        "progress_output": f"diagnostic/{case_id}-progress.json",
        "score": {
            "expected_frames": EXPECTED,
            "finite_prefix_frames": executed,
            "executed": True,
            "complete": complete,
            "failure_category": failure_category,
            "raw_error_coverage": executed / EXPECTED,
        },
    }
    row["rollout"] = copy.deepcopy({key: value for key, value in row.items()
                                    if key != "score"})
    evaluation = {
        "schema": "core.evaluation.v1",
        "evaluation_mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "autonomous": True,
        "future_state_inputs": False,
        "checkpoint": CHECKPOINT_PATH,
        "registered_case_ids": [case_id],
        "selected_case_ids": [case_id],
        "expected_frames": {case_id: EXPECTED},
        "cases": {case_id: row},
    }
    item = {
        "schema": reducer.ITEM_SCHEMA,
        "status": status,
        "binding": _binding(case_id),
        "evaluation": evaluation,
    }
    if include_progress:
        item["progress"] = {
            "schema": "core.rollout.progress.v1",
            "case_id": case_id,
            "status": status,
            "completed_frames": executed,
            "expected_frames": EXPECTED,
            "frames_expected": EXPECTED,
            "frames_executed": executed,
            "autonomous": True,
            "future_state_inputs": False,
            "trajectory_output": row["trajectory_output"],
        }
    path = tmp_path / f"{case_id}-{status}.json"
    path.write_text(json.dumps(item, sort_keys=True), encoding="utf-8")
    return path


def _aggregate(paths: list[Path]) -> dict:
    return reducer.aggregate_rollout_files(
        paths,
        manifest_path=MANIFEST_PATH,
        manifest_sha256=MANIFEST_SHA,
        checkpoint_path=CHECKPOINT_PATH,
        checkpoint_sha256=CHECKPOINT_SHA,
        case_bindings=_case_bindings(*(path.name.split("-", 1)[0] for path in paths)),
    )


def test_completed_failed_running_batch_preserves_835_denominator_and_zero_credit(tmp_path):
    completed = _write_item(tmp_path, "F3_SYNTHETIC_00", include_progress=True)
    failed = _write_item(
        tmp_path, "F3_SYNTHETIC_01", status="failed", executed=17,
        failure_category="model_execution_error",
    )
    running = _write_item(tmp_path, "F3_SYNTHETIC_02", status="running", executed=23)

    result = _aggregate([running, completed, failed])

    assert result["status"] == "aggregated_diagnostic"
    assert result["source_bound"] is True
    assert result["diagnostic_only"] is True
    assert result["formal_eligible"] is False
    assert result["T1_numerical"] is False
    assert result["T2_macro"] is False
    assert result["qualification"] is False
    assert result["qualification_credit"] == 0
    assert result["credit"] == 0
    assert result["denominator"] == {
        "expected_transitions_per_case": EXPECTED,
        "case_count": 3,
        "total_expected_transitions": 3 * EXPECTED,
        "total_executed_transitions": EXPECTED + 17 + 23,
        "full_denominator_case_count": 1,
        "raw_error_coverage": (EXPECTED + 17 + 23) / (3 * EXPECTED),
        "all_cases_complete": False,
    }
    assert result["status_counts"] == {"completed": 1, "failed": 1, "running": 1}
    assert [item["case_id"] for item in result["cases"]] == [
        "F3_SYNTHETIC_00", "F3_SYNTHETIC_01", "F3_SYNTHETIC_02"
    ]


def test_output_is_deterministic_and_cli_writes_canonical_json(tmp_path):
    first = _write_item(tmp_path, "F3_SYNTHETIC_00")
    second = _write_item(tmp_path, "F3_SYNTHETIC_01")
    output = tmp_path / "batch.json"

    assert reducer.main([
        "--input", str(second), "--input", str(first),
        "--manifest-path", MANIFEST_PATH, "--manifest-sha256", MANIFEST_SHA,
        "--checkpoint-path", CHECKPOINT_PATH, "--checkpoint-sha256", CHECKPOINT_SHA,
        "--case-binding", "F3_SYNTHETIC_00", "cases/F3_SYNTHETIC_00/source.h5", "c" + "0" * 63,
        "--case-binding", "F3_SYNTHETIC_01", "cases/F3_SYNTHETIC_01/source.h5", "d" + "0" * 63,
        "--output", str(output),
    ]) == 0
    written = output.read_text(encoding="utf-8")
    parsed = json.loads(written)
    assert written.endswith("\n")
    assert written[:-1] == reducer.canonical_json(parsed)
    assert reducer.canonical_json(_aggregate([first, second])) == written[:-1]


@pytest.mark.parametrize("mutation", [
    "manifest_sha", "checkpoint_path", "checkpoint_sha", "case_sha",
])
def test_fixed_source_binding_drift_fails_closed(tmp_path, mutation):
    path = _write_item(tmp_path, "F3_SYNTHETIC_00")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "manifest_sha":
        payload["binding"]["manifest"]["sha256"] = "e" * 64
    elif mutation == "checkpoint_path":
        payload["binding"]["checkpoint"]["path"] = "checkpoints/other.pt"
    elif mutation == "checkpoint_sha":
        payload["binding"]["checkpoint"]["sha256"] = "f" * 64
    elif mutation == "case_sha":
        payload["binding"]["case"]["sha256"] = "1" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(reducer.BatchReceiptError, match="fail-closed"):
        _aggregate([path])


def test_duplicate_case_and_path_collision_fail_closed(tmp_path):
    first = _write_item(tmp_path, "F3_SYNTHETIC_00")
    duplicate = _write_item(tmp_path, "F3_SYNTHETIC_00", status="failed",
                            executed=2, failure_category="model_execution_error")
    with pytest.raises(reducer.BatchReceiptError, match="duplicate case_id"):
        _aggregate([first, duplicate])

    other = _write_item(tmp_path, "F3_SYNTHETIC_01")
    first_payload = json.loads(first.read_text(encoding="utf-8"))
    other_payload = json.loads(other.read_text(encoding="utf-8"))
    other_payload["evaluation"]["cases"]["F3_SYNTHETIC_01"]["trajectory_output"] = (
        first_payload["evaluation"]["cases"]["F3_SYNTHETIC_00"]["trajectory_output"]
    )
    other_payload["evaluation"]["cases"]["F3_SYNTHETIC_01"]["rollout"]["trajectory_output"] = (
        other_payload["evaluation"]["cases"]["F3_SYNTHETIC_01"]["trajectory_output"]
    )
    other.write_text(json.dumps(other_payload), encoding="utf-8")
    with pytest.raises(reducer.BatchReceiptError, match="path collision"):
        _aggregate([first, other])


@pytest.mark.parametrize("mutation", ["future", "nonfinite", "missing_report", "denominator", "formal"])
def test_malformed_or_missing_reports_are_fail_closed(tmp_path, mutation):
    path = _write_item(tmp_path, "F3_SYNTHETIC_00")
    paths = [path]
    if mutation == "future":
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["evaluation"]["future_state_inputs"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "nonfinite":
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["evaluation"]["cases"]["F3_SYNTHETIC_00"]["position_rmse"][0] = float("nan")
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "missing_report":
        paths = [tmp_path / "does-not-exist.json"]
    elif mutation == "denominator":
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["evaluation"]["expected_frames"]["F3_SYNTHETIC_00"] = EXPECTED - 1
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "formal":
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["evaluation"]["formal_eligible"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")

    result = reducer.run_batch(
        paths,
        manifest_path=MANIFEST_PATH,
        manifest_sha256=MANIFEST_SHA,
        checkpoint_path=CHECKPOINT_PATH,
        checkpoint_sha256=CHECKPOINT_SHA,
        case_bindings=_case_bindings("F3_SYNTHETIC_00"),
    )
    assert result["status"] == "fail_closed"
    assert result["fail_closed"] is True
    assert result["diagnostic_only"] is True
    assert result["formal_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["credit"] == 0


def test_explicit_running_status_cannot_claim_completed_denominator(tmp_path):
    path = _write_item(tmp_path, "F3_SYNTHETIC_00", status="running", executed=EXPECTED)
    result = reducer.run_batch(
        [path],
        manifest_path=MANIFEST_PATH,
        manifest_sha256=MANIFEST_SHA,
        checkpoint_path=CHECKPOINT_PATH,
        checkpoint_sha256=CHECKPOINT_SHA,
        case_bindings=_case_bindings("F3_SYNTHETIC_00"),
    )
    assert result["fail_closed"] is True
    assert "running status" in result["error"]
