"""Synthetic-only tests for the F3 JSON batch-closure binding adapter."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_rollout_batch_closure_binding_v1 as closure


EXPECTED = 835


def _fixture() -> tuple[dict, dict, dict, dict, dict]:
    launch = closure._synthetic_launch()
    training = closure._synthetic_training(launch)
    case_ids = [job["case_id"] for job in launch["jobs"]]
    statuses = {
        case_ids[0]: (EXPECTED, "completed", None),
        case_ids[1]: (23, "running", None),
        case_ids[2]: (17, "failed", "model_execution_error"),
    }
    evaluations = {
        case_id: closure._synthetic_evaluation(
            launch,
            case_id,
            executed=statuses[case_id][0],
            status=statuses[case_id][1],
            failure_category=statuses[case_id][2],
        )
        for case_id in case_ids
    }
    progresses = {
        case_id: closure._synthetic_progress(
            launch,
            case_id,
            executed=statuses[case_id][0],
            status=statuses[case_id][1],
        )
        for case_id in case_ids
    }
    bindings = {
        case_id: {
            "path": f"cases/{case_id}/source.h5",
            "sha256": ("d" + "0" * 63) if index == 1 else (
                "e" + "0" * 63 if index == 2 else "c" + "0" * 63
            ),
        }
        for index, case_id in enumerate(case_ids)
    }
    normalized_launch = closure.validate_launch_receipt(launch)
    for case_id in case_ids:
        evaluations[case_id]["binding"] = closure._expected_binding(
            normalized_launch, case_id, bindings[case_id]
        )
    return launch, training, evaluations, progresses, bindings


def _verify(
    launch: dict,
    training: dict,
    evaluations: dict,
    progresses: dict,
    bindings: dict,
) -> dict:
    return closure.verify_payloads(
        launch, training, evaluations, progresses, bindings, synthetic_only=True
    )


def test_json_only_binding_reuses_aggregator_and_preserves_zero_credit():
    result = _verify(*_fixture())

    assert result["schema"] == closure.SCHEMA
    assert result["status"] == "json_bound_diagnostic_batch"
    assert result["source_bound"] is True
    assert result["synthetic_only"] is True
    assert result["diagnostic_only"] is True
    assert result["formal"] is False
    assert result["formal_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["credit"] == 0
    assert result["training"]["hidden"] == 8
    assert result["training"]["completed_updates"] == 500
    assert result["aggregate"]["schema"] == "core.f3.rollout_batch_receipt.v1"
    assert result["aggregate"]["denominator"] == {
        "expected_transitions_per_case": EXPECTED,
        "case_count": 3,
        "total_expected_transitions": 3 * EXPECTED,
        "total_executed_transitions": EXPECTED + 23 + 17,
        "full_denominator_case_count": 1,
        "raw_error_coverage": (EXPECTED + 23 + 17) / (3 * EXPECTED),
        "all_cases_complete": False,
    }
    assert result["aggregate"]["status_counts"] == {
        "completed": 1,
        "failed": 1,
        "running": 1,
    }
    assert result["checks"]["existing_batch_aggregator_reused"] is True
    assert result["side_effects"] == {
        "manifest_opened": False,
        "checkpoint_opened": False,
        "trajectory_hdf5_opened": False,
        "progress_path_opened": False,
        "live_jobs_required": False,
        "runtime_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
    }


def test_payloads_are_not_mutated_and_output_namespaces_are_derived_only():
    fixture = _fixture()
    before = copy.deepcopy(fixture)
    result = _verify(*fixture)

    assert fixture == before
    for case in result["aggregate"]["cases"]:
        paths = case["paths"]
        assert paths["trajectory_output"].endswith("-trajectory.h5")
        assert paths["progress_output"].endswith("-evaluation-progress.json")
        assert case["evaluation_json"]["path"].startswith("synthetic://")
        assert case["progress_json"]["path"].startswith("synthetic://")


@pytest.mark.parametrize(
    "mutation",
    [
        "launch_model",
        "launch_checkpoint_sha",
        "training_hidden",
        "training_updates",
        "training_checkpoint_path",
        "evaluation_output_prefix",
        "progress_denominator",
        "progress_status",
        "case_set",
        "case_sha",
        "formal_claim",
    ],
)
def test_binding_mutations_fail_closed(mutation: str):
    launch, training, evaluations, progresses, bindings = _fixture()
    case_id = sorted(job["case_id"] for job in launch["jobs"])[0]
    if mutation == "launch_model":
        launch["model"] = "mlp"
    elif mutation == "launch_checkpoint_sha":
        launch["checkpoint_sha256"] = "f" * 64
    elif mutation == "training_hidden":
        training["config"]["hidden"] = 16
    elif mutation == "training_updates":
        training["config"]["updates"] = 499
    elif mutation == "training_checkpoint_path":
        training["checkpoint"]["path"] = "/synthetic/checkpoints/other.pt"
    elif mutation == "evaluation_output_prefix":
        evaluations[case_id]["cases"][case_id]["trajectory_output"] = "/synthetic/other.h5"
    elif mutation == "progress_denominator":
        progresses[case_id]["expected_frames"] = EXPECTED - 1
    elif mutation == "progress_status":
        progresses[case_id]["status"] = "failed"
    elif mutation == "case_set":
        evaluations.pop(case_id)
    elif mutation == "case_sha":
        bindings[case_id]["sha256"] = "f" * 64
    elif mutation == "formal_claim":
        evaluations[case_id]["formal_eligible"] = True

    result = closure.run_closure(
        launch, training, evaluations, progresses, bindings, synthetic_only=True
    )
    assert result["status"] == "fail_closed"
    assert result["fail_closed"] is True
    assert result["diagnostic_only"] is True
    assert result["formal_eligible"] is False
    assert result["qualification_credit"] == 0
    assert result["credit"] == 0


def test_file_adapter_reads_independent_json_without_hdf5(tmp_path: Path):
    launch, training, evaluations, progresses, bindings = _fixture()
    for job in launch["jobs"]:
        job["output_prefix"] = str(tmp_path / f"{job['case_id']}-fresh")
        prefix = job["output_prefix"]
        job["output_paths"] = closure._output_paths(prefix)
    case_ids = [job["case_id"] for job in launch["jobs"]]
    for case_id in case_ids:
        evaluations[case_id] = closure._synthetic_evaluation(
            launch,
            case_id,
            executed=evaluations[case_id]["cases"][case_id]["frames_executed"],
            status=progresses[case_id]["status"],
            failure_category=evaluations[case_id]["cases"][case_id]["failure_category"],
        )
        progresses[case_id] = closure._synthetic_progress(
            launch,
            case_id,
            executed=progresses[case_id]["frames_executed"],
            status=progresses[case_id]["status"],
        )

    launch_path = tmp_path / "launch.json"
    training_path = tmp_path / "training.json"
    launch_path.write_text(closure.canonical_json(launch) + "\n", encoding="utf-8")
    training_path.write_text(closure.canonical_json(training) + "\n", encoding="utf-8")
    evaluation_paths = {}
    progress_paths = {}
    for job in launch["jobs"]:
        case_id = job["case_id"]
        evaluation_path = Path(job["output_paths"]["evaluation"])
        progress_path = Path(job["output_paths"]["progress"])
        evaluation_path.write_text(
            closure.canonical_json(evaluations[case_id]) + "\n", encoding="utf-8"
        )
        progress_path.write_text(
            closure.canonical_json(progresses[case_id]) + "\n", encoding="utf-8"
        )
        evaluation_paths[case_id] = evaluation_path
        progress_paths[case_id] = progress_path

    result = closure.verify_files(
        launch_path, training_path, evaluation_paths, progress_paths, bindings,
        synthetic_only=True,
    )
    assert result["fail_closed"] is False
    assert result["aggregate"]["denominator"]["case_count"] == 3
    assert all(
        case["evaluation_json"]["path"].endswith("-evaluation.json")
        for case in result["aggregate"]["cases"]
    )


def test_run_closure_rejects_missing_live_terminal_files_without_side_effects():
    launch, training, evaluations, progresses, bindings = _fixture()
    evaluations.pop(sorted(evaluations)[-1])
    result = closure.run_closure(
        launch, training, evaluations, progresses, bindings, synthetic_only=True
    )
    assert result["status"] == "fail_closed"
    assert "case sets" in result["error"]
    assert result["registry_mutation"] == 0
    assert result["gate_mutation"] == 0


def test_committed_machine_report_matches_build_report():
    report_path = Path(__file__).parents[1] / (
        "reports/F3-ROLLOUT-BATCH-CLOSURE-BINDING-V1.json"
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == closure.build_report()
