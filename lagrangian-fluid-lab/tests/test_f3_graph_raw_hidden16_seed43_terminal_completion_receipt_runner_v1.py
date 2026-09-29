"""Focused tests for the seed43-specific F3 terminal completion runner."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_graph_raw_hidden16_seed43_terminal_completion_receipt_runner_v1 as runner


def _live_summary() -> tuple[dict, dict]:
    return runner._read_summary(runner.DEFAULT_SUMMARY)


def _write_summary(path: Path, payload: dict) -> None:
    path.write_text(runner.canonical_json(payload) + "\n", encoding="utf-8")


def test_seed43_existing_full835_terminal_binds() -> None:
    report = runner.build_report()

    assert report["status"] == "bound_existing_terminal_summary"
    assert report["terminal_markers"]["transitions"] == 835
    assert report["terminal_markers"]["frames"] == 836
    assert report["terminal_markers"]["validator"]["passed"] is True
    assert report["launch"]["attempted"] is False
    assert report["scope"]["progress_content_opened"] is False
    assert report["scope"]["trajectory_content_opened"] is False
    assert report["scope"]["hdf5_content_opened"] is False
    assert report["scope"]["manifest_content_opened"] is False
    assert report["scope"]["checkpoint_content_opened"] is False
    assert report["scope"]["registry_mutation"] == 0
    assert report["scope"]["ledger_mutation"] == 0
    assert report["scope"]["denominator_mutation"] == 0
    assert report["scope"]["gate_mutation"] == 0
    assert report["security_boundary"]["status"] == "blocked_fail_closed"
    assert report["security_boundary"]["launch_allowed"] is False
    assert report["security_boundary"]["controls"]["sealed_real_popen_wait"] is False
    assert report["security_boundary"]["controls"]["formal_credit_isolation"] is True
    assert runner.validate_report(report) == []


def test_seed43_known_legacy_summary_duplicate_is_reconciled() -> None:
    summary, identity = _live_summary()

    assert identity["content_opened"] is True
    assert summary["qualification"]["formal_eligible"] is False
    assert summary["qualification"]["qualification_credit"] == 0


def test_seed43_terminal_summary_validation_rejects_marker_drift() -> None:
    summary, _ = _live_summary()
    drifted = copy.deepcopy(summary)
    drifted["evaluation"]["frames_executed"] = 834

    with pytest.raises(runner.ClosureError, match="evaluation.frames_executed drift"):
        runner._validate_summary(drifted)


def test_seed43_terminal_summary_validation_rejects_formal_marker() -> None:
    summary, _ = _live_summary()
    drifted = copy.deepcopy(summary)
    drifted["formal_eligible"] = True

    with pytest.raises(runner.ClosureError, match="summary formal_eligible"):
        runner._validate_summary(drifted)


def test_seed43_terminal_summary_validation_rejects_duplicate_unknown_key(tmp_path: Path) -> None:
    raw = '{"schema":"x","qualification":false,"qualification":true}\n'
    path = tmp_path / "duplicate-summary.json"
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(runner.ClosureError, match="duplicate JSON key"):
        runner._read_summary(path)


def test_seed43_runner_blocks_missing_summary_without_launch(tmp_path: Path) -> None:
    report = runner.build_report(tmp_path / "missing-seed43-summary.json")

    assert report["status"] == "blocked_fail_closed"
    assert report["launch"]["attempted"] is False
    assert report["scope"]["new_evaluation_started"] is False
    assert report["blocked_reasons"]


def test_seed43_report_outputs_are_bounded_and_seed_specific(tmp_path: Path) -> None:
    report = runner.build_report()
    output = tmp_path / runner.REPORT_FILENAME
    zh_output = tmp_path / runner.ZH_REPORT_FILENAME
    runner.write_outputs(report, output, zh_output)

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["report_id"] == runner.REPORT_ID
    assert "SEED43" in output.name
    assert "SEED43" in zh_output.name
    assert output.stat().st_size < 64 * 1024
    assert zh_output.stat().st_size < 64 * 1024
    assert "diagnostic" in zh_output.read_text(encoding="utf-8")


def test_seed43_explicit_summary_copy_keeps_actual_receipt_hash_binding(tmp_path: Path) -> None:
    summary, _ = _live_summary()
    copy_path = tmp_path / runner.SUMMARY_FILENAME
    _write_summary(copy_path, summary)

    report = runner.build_report(copy_path)

    training = report["identity_bindings"]["training_receipt"]
    evaluation = report["identity_bindings"]["evaluation_receipt"]
    assert training["hash_verification"] == "verified"
    assert evaluation["hash_verification"] == "verified"
    assert report["terminal_markers"] == {
        "case_id": "F3_DEV_00_a0p903125",
        "model_kind": "graph_raw",
        "seed": 43,
        "hidden": 16,
        "updates": 500,
        "transitions": 835,
        "frames": 836,
        "parameter_count": 6086,
        "validator": {
            "passed": True,
            "complete": True,
            "trajectory_frames": 836,
            "trajectory_transitions": 835,
            "tail_frame_count": 0,
        },
    }


def test_seed43_bounded_json_rejects_symlink_and_hardlink_aliases(tmp_path: Path) -> None:
    source = tmp_path / "receipt.json"
    source.write_text('{"schema":"core.training.v1"}\n', encoding="utf-8")

    symlink = tmp_path / "receipt-symlink.json"
    symlink.symlink_to(source)
    with pytest.raises(runner.ReceiptError, match="link|artifact"):
        runner._read_bounded_json(symlink, "seed43 test receipt", 1024)

    hardlink = tmp_path / "receipt-hardlink.json"
    hardlink.hardlink_to(source)
    with pytest.raises(runner.ReceiptError, match="hard link|artifact"):
        runner._read_bounded_json(hardlink, "seed43 test receipt", 1024)


def test_seed43_report_rejects_security_boundary_promotion() -> None:
    report = runner.build_report()
    report["security_boundary"]["launch_allowed"] = True

    assert any("security_boundary.launch_allowed" in error for error in runner.validate_report(report))
