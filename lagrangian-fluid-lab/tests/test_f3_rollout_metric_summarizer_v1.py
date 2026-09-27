import json

import pytest

from scripts.f3_rollout_metric_summarizer_v1 import (
    SUMMARY_SCHEMA,
    canonical_json,
    main,
    summarize_evaluation,
)


def _evaluation(*, maximum_steps=None, include_tail_nulls=True, future_state_inputs=False):
    position_rmse = [0.1, 0.2]
    position_ade = [0.11, 0.21]
    velocity_rmse = [0.3, 0.4]
    velocity_ade = [0.31, 0.41]
    if include_tail_nulls:
        position_rmse += [None, None]
        position_ade += [None, None]
        velocity_rmse += [None, None]
        velocity_ade += [None, None]
    rollout = {
        "schema": "core.rollout.v1",
        "case_id": "F3_SYNTHETIC_00",
        "expected_frames": 4,
        "frames_executed": 2,
        "position_rmse": position_rmse,
        "position_ade": position_ade,
        "velocity_rmse": velocity_rmse,
        "velocity_ade": velocity_ade,
        "failure_category": "maximum_steps_limit" if maximum_steps else None,
        "first_failure_frame": 3 if maximum_steps else None,
        "requested_window_execution_complete": True,
        "requested_window_finite_rollout_complete": True,
        "complete_over_registered_denominator": False,
        "future_state_inputs": future_state_inputs,
        "physics": {
            "summary": {
                "expected_frames": 4,
                "completed_frames": 2,
                "mass_error_abs_max_kg": 1.5e-9,
                "wall_chord_statuses": ["not_applicable"],
            }
        },
    }
    return {
        "schema": "core.evaluation.v1",
        "family": "F3",
        "model_kind": "graph_raw",
        "maximum_steps": maximum_steps,
        "future_state_inputs": future_state_inputs,
        "cases": {"F3_SYNTHETIC_00": {"rollout": rollout}},
    }


def test_incomplete_maximum_steps_keeps_registered_denominator_and_null_tail():
    summary = summarize_evaluation(_evaluation(maximum_steps=2))

    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["case_count"] == 1
    case = summary["cases"][0]
    assert [row["step"] for row in case["per_step"]] == [1, 2, 3, 4]
    assert case["per_step"][0]["position_rmse_m"] == 0.1
    assert case["per_step"][1]["velocity_ade_mps"] == 0.41
    assert case["per_step"][2]["position_rmse_m"] is None
    assert case["coverage"] == {
        "complete_over_registered_denominator": False,
        "expected_frames": 4,
        "finite_prefix_frames": 2,
        "frames_executed": 2,
        "raw_error_coverage": 0.5,
        "requested_maximum_steps": 2,
        "requested_window_execution_complete": True,
        "requested_window_finite_rollout_complete": True,
        "requested_window_frames": 2,
    }
    assert case["failure_category"] == "maximum_steps_limit"
    assert case["first_failure_frame"] == 3
    assert case["physics_summary"]["completed_frames"] == 2


def test_complete_rollout_has_no_implicit_renormalization():
    payload = _evaluation(maximum_steps=None, include_tail_nulls=False)
    row = payload["cases"]["F3_SYNTHETIC_00"]["rollout"]
    row.update(
        expected_frames=2,
        frames_executed=2,
        failure_category=None,
        first_failure_frame=None,
        requested_window_execution_complete=True,
        requested_window_finite_rollout_complete=True,
        complete_over_registered_denominator=True,
        physics={"summary": {"expected_frames": 2, "completed_frames": 2}},
    )
    summary = summarize_evaluation(payload)
    case = summary["cases"][0]
    assert case["coverage"]["raw_error_coverage"] == 1.0
    assert case["coverage"]["complete_over_registered_denominator"] is True
    assert case["failure_category"] is None
    assert len(case["per_step"]) == 2


def test_multiple_cases_are_sorted_for_stable_canonical_output():
    payload = _evaluation(maximum_steps=2)
    first = payload["cases"].pop("F3_SYNTHETIC_00")
    first["rollout"]["case_id"] = "F3_SYNTHETIC_01"
    payload["cases"]["F3_SYNTHETIC_01"] = first
    second = json.loads(json.dumps(first))
    second["rollout"]["case_id"] = "F3_SYNTHETIC_00"
    payload["cases"]["F3_SYNTHETIC_00"] = second

    summary = summarize_evaluation(payload)
    assert [case["case_id"] for case in summary["cases"]] == [
        "F3_SYNTHETIC_00", "F3_SYNTHETIC_01"
    ]
    reversed_payload = dict(payload)
    reversed_payload["cases"] = dict(reversed(list(payload["cases"].items())))
    assert canonical_json(summary) == canonical_json(summarize_evaluation(reversed_payload))


def test_future_state_input_declaration_is_rejected():
    with pytest.raises(ValueError, match="future_state_inputs"):
        summarize_evaluation(_evaluation(maximum_steps=2, future_state_inputs=True))


def test_nonfinite_and_non_monotonic_metric_tail_fail_closed():
    payload = _evaluation(maximum_steps=2)
    payload["cases"]["F3_SYNTHETIC_00"]["rollout"]["position_rmse"] = [
        0.1, None, 0.2, None
    ]
    with pytest.raises(ValueError, match="after a missing frame"):
        summarize_evaluation(payload)

    payload = _evaluation(maximum_steps=2)
    payload["cases"]["F3_SYNTHETIC_00"]["rollout"]["velocity_ade"][0] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        summarize_evaluation(payload)


def test_cli_emits_only_canonical_json_and_does_not_need_model_inputs(tmp_path, capsys):
    source = tmp_path / "evaluation.json"
    output = tmp_path / "summary.json"
    source.write_text(json.dumps(_evaluation(maximum_steps=2)), encoding="utf-8")

    assert main([str(source), "--output", str(output)]) == 0
    assert capsys.readouterr().out == ""
    written = output.read_text(encoding="utf-8")
    assert written.endswith("\n")
    assert json.loads(written)["schema"] == SUMMARY_SCHEMA
    assert written[:-1] == canonical_json(json.loads(written))

    assert main([str(source)]) == 0
    stdout = capsys.readouterr().out
    assert stdout.endswith("\n")
    assert stdout[:-1] == written[:-1]
