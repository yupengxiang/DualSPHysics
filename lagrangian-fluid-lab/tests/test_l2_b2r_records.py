import json

import pytest

from scripts.l2_b2r_contract import build_study_spec
from scripts.l2_b2r_records import (
    B2RContractError,
    build_failure_denominator,
    create_attempt_record,
    validate_failure_denominator,
    write_attempt_record,
)


def _spec():
    return build_study_spec()[0]


def _record(spec, index=0, **updates):
    logical = spec.logical_runs[index]
    values = dict(
        logical_run_id=logical["logical_run_id"],
        route=logical["route"],
        seed=logical["seed"],
        physical_case_ids=spec.evaluation_case_ids,
        execution_attempt_id=f"attempt{index}",
    )
    values.update(updates)
    return create_attempt_record(**values)


def test_empty_attempt_list_keeps_all_six_runs_and_96_case_runs_in_denominator():
    report = build_failure_denominator(_spec(), [])
    logical = report["logical_run_denominator"]
    evaluation = report["evaluation_case_denominator"]
    assert report["status"] == "incomplete"
    assert logical["planned"] == 6
    assert logical["failure_count"] == 6
    assert logical["outcome_counts"]["not_started"] == 6
    assert evaluation["physical_case_count"] == 16
    assert evaluation["planned_case_run_count"] == 96
    assert evaluation["status_counts"]["missing"] == 96
    assert validate_failure_denominator(report)["valid"] is True


def test_worker_failure_and_physical_failure_are_distinct_denominator_outcomes():
    spec = _spec()
    worker_failure = _record(
        spec,
        0,
        status="failed",
        worker_exit_status="nonzero",
        failure_reason="worker exception",
    )
    physical_failure = _record(
        spec,
        1,
        status="completed",
        worker_exit_status="zero",
        training_completed=True,
        evaluation_completed=True,
        model_physical_pass="fail",
    )
    report = build_failure_denominator(spec, [worker_failure, physical_failure])
    counts = report["logical_run_denominator"]["outcome_counts"]
    assert counts["training_failure"] == 1
    assert counts["physical_failure"] == 1
    assert counts["not_started"] == 4
    assert report["logical_run_denominator"]["failure_count"] == 6


def test_retry_is_visible_but_does_not_inflate_logical_denominator():
    spec = _spec()
    first = _record(spec, 0, status="failed", worker_exit_status="timeout")
    retry = _record(
        spec,
        0,
        execution_attempt_id="attempt0retry",
        retry_of="attempt0",
        status="completed",
        worker_exit_status="zero",
        training_completed=True,
        evaluation_completed=True,
        model_physical_pass="pass",
        finished_at_utc="2026-09-20T00:00:00+00:00",
    )
    report = build_failure_denominator(spec, [first, retry])
    row = report["logical_run_denominator"]["rows"][0]
    assert row["attempt_count"] == 2
    assert row["retry_count"] == 1
    assert row["outcome"] == "physical_pass"
    assert report["logical_run_denominator"]["planned"] == 6
    assert report["logical_run_denominator"]["outcome_counts"]["physical_pass"] == 1


def test_physical_pass_cannot_be_recorded_before_all_prior_layers():
    with pytest.raises(B2RContractError, match="lacks completed"):
        _record(
            _spec(),
            0,
            status="failed",
            worker_exit_status="nonzero",
            model_physical_pass="pass",
        )


def test_attempt_record_write_is_atomic_and_non_overwriting(tmp_path):
    spec = _spec()
    record = _record(spec)
    target = tmp_path / "attempt.json"
    result = write_attempt_record(target, record)
    assert target.is_file()
    assert result["bytes"] == target.stat().st_size
    assert json.loads(target.read_text())["schema"] == "l2r.b2r.training_attempt.v1"
    with pytest.raises(FileExistsError):
        write_attempt_record(target, record)
