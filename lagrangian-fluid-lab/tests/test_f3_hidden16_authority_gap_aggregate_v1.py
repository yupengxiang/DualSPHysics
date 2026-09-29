"""Focused fail-closed tests for the nine-report F3 hidden16 aggregate."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil

import pytest

from scripts import f3_hidden16_authority_gap_aggregate_v1 as aggregate


def _copy_inputs(tmp_path: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for source in aggregate.DEFAULT_INPUTS:
        target = tmp_path / source.name
        shutil.copyfile(source, target)
        paths.append(target)
    return tuple(paths)


def test_current_matrix_has_complete_unique_fail_closed_zero_credit_coverage() -> None:
    report = aggregate.build_aggregate(observed_at_utc="2026-09-29T00:00:00Z")

    assert report["status"] == "blocked_fail_closed"
    assert report["coverage"] == {
        "expected_count": 9,
        "observed_count": 9,
        "complete_unique": True,
        "missing": [],
        "unexpected": [],
        "duplicate_model_seed": [],
    }
    assert [(row["model_kind"], row["seed"]) for row in report["projections"]] == list(
        aggregate.EXPECTED_KEYS
    )
    assert all(row["zero_credit_verified"] for row in report["projections"])
    assert all(row["launch_denied_verified"] for row in report["projections"])
    assert aggregate.validate_report(report) == []


def test_explicit_input_set_rejects_missing_duplicate_and_unapproved_basename(tmp_path: Path) -> None:
    paths = list(_copy_inputs(tmp_path))

    with pytest.raises(aggregate.AggregateError, match="exactly 9"):
        aggregate.build_aggregate(paths[:-1])

    with pytest.raises(aggregate.AggregateError, match="duplicate"):
        aggregate.build_aggregate(paths[:-1] + [paths[0]])

    renamed = paths.copy()
    renamed[0] = tmp_path / "not-an-explicit-gap-report.json"
    shutil.copyfile(aggregate.DEFAULT_INPUTS[0], renamed[0])
    with pytest.raises(aggregate.AggregateError, match="explicit reports"):
        aggregate.build_aggregate(renamed)


def test_bounded_reader_rejects_symlink_input(tmp_path: Path) -> None:
    paths = list(_copy_inputs(tmp_path))
    symlink = tmp_path / paths[0].name
    symlink.unlink()
    symlink.symlink_to(aggregate.DEFAULT_INPUTS[0])
    paths[0] = symlink

    with pytest.raises(aggregate.AggregateError, match="symlink"):
        aggregate.build_aggregate(paths)


def test_identity_drift_in_schema_or_scope_fails_closed(tmp_path: Path) -> None:
    paths = list(_copy_inputs(tmp_path))
    target = paths[1]
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["scope"]["seed"] = 17
    target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(aggregate.AggregateError, match="scope.seed"):
        aggregate.build_aggregate(paths)


def test_input_credit_or_launch_promotion_is_rejected(tmp_path: Path) -> None:
    paths = list(_copy_inputs(tmp_path))
    target = paths[2]
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["credit"] = 1
    target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(aggregate.AggregateError, match="credit"):
        aggregate.build_aggregate(paths)

    payload["credit"] = 0
    payload["readiness"]["launch_allowed"] = True
    target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(aggregate.AggregateError, match="launch_allowed"):
        aggregate.build_aggregate(paths)


def test_aggregate_validator_rejects_coverage_credit_and_launch_mutations() -> None:
    report = aggregate.build_aggregate(observed_at_utc="2026-09-29T00:00:00Z")

    forged_coverage = copy.deepcopy(report)
    forged_coverage["coverage"]["complete_unique"] = False
    assert aggregate.validate_report(forged_coverage)

    forged_credit = copy.deepcopy(report)
    forged_credit["zero_credit"]["credit"] = 1
    assert aggregate.validate_report(forged_credit)

    forged_launch = copy.deepcopy(report)
    forged_launch["launch_boundary"]["launch_allowed"] = True
    assert aggregate.validate_report(forged_launch)


def test_writer_emits_self_validating_json_and_markdown(tmp_path: Path) -> None:
    report = aggregate.build_aggregate(observed_at_utc="2026-09-29T00:00:00Z")
    json_path = tmp_path / "aggregate.json"
    markdown_path = tmp_path / "aggregate.zh-CN.md"
    aggregate.write_reports(report, report_path=json_path, markdown_path=markdown_path)

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert aggregate.validate_report(parsed) == []
    assert "graph_residual" in markdown_path.read_text(encoding="utf-8")
    assert "blocked_fail_closed" in markdown_path.read_text(encoding="utf-8")
