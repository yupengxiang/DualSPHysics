from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_graph_raw_seed17_formal_training_readiness_v1 as readiness


LAB_ROOT = Path(__file__).resolve().parents[1]


def test_current_graph_raw_seed17_unit_is_blocked_without_formal_authority() -> None:
    report = readiness.build_report(root=LAB_ROOT, observed_at_utc="2026-09-29T00:00:00Z")

    assert report["status"] == "blocked_fail_closed"
    assert report["scope"]["run_id"] == "graph_raw-seed17"
    assert report["decision"] == {
        "inputs_closed": False,
        "formal_training_ready": False,
        "spec_created": False,
        "launch_allowed": False,
        "reason": "external formal trust anchor and upstream Core admission gates are not closed",
    }
    codes = {row["code"] for row in report["blockers"]}
    assert "FORMAL_ROOT_TRUST_ANCHOR_MISSING" in codes
    assert "FORMAL_SCHEDULER_SPEC_MISSING" in codes
    assert "FORMAL_TERMINAL_CONTRACT_MISSING" in codes
    assert "CURRENT_DATASET_NOT_FORMAL_RELEASE" in codes
    assert report["scheduler"]["matching_spec_count"] >= 1
    assert report["scheduler"]["formal_spec_present"] is False
    assert report["current_source_closure"]["current_hashes_match"] is True
    assert report["current_source_closure"]["root_admission_granted"] is False
    assert report["zero_credit"]["credit"] == 0
    assert readiness.validate_report(report) == []


def test_diagnostic_scheduler_and_terminal_records_cannot_be_promoted() -> None:
    report = readiness.build_report(root=LAB_ROOT, observed_at_utc="2026-09-29T00:00:00Z")

    assert report["formal_protocol"]["training_contract_matches_formal_target"] is True
    assert report["terminal"]["formal_terminal_evidence_present"] is False
    assert all(row["formal_training"] is False for row in report["terminal"]["contracts"])
    assert all(row["credit"] == 0 for row in report["terminal"]["contracts"])
    assert all(row["outputs_are_not_formal_evidence"] is True for row in report["scheduler"]["matching_specs"] if "outputs_are_not_formal_evidence" in row)


def test_report_validator_rejects_authority_or_side_effect_tampering() -> None:
    report = readiness.build_report(root=LAB_ROOT, observed_at_utc="2026-09-29T00:00:00Z")

    tampered = copy.deepcopy(report)
    tampered["decision"]["launch_allowed"] = True
    tampered["zero_credit"]["credit"] = 1
    tampered["side_effects"]["queue_submitted"] = True
    errors = readiness.validate_report(tampered)

    assert "decision.launch_allowed must remain false" in errors
    assert "zero-credit authority drift" in errors
    assert "side_effects.queue_submitted must remain false" in errors


def test_missing_root_is_bounded_and_fail_closed(tmp_path: Path) -> None:
    report = readiness.build_report(root=tmp_path, observed_at_utc="2026-09-29T00:00:00Z")

    assert report["status"] == "blocked_fail_closed"
    assert report["decision"]["launch_allowed"] is False
    assert any(row["code"] == "BOUNDED_INPUT_ERROR" for row in report["blockers"])
    assert readiness.validate_report(report) == []


def test_write_report_is_create_only(tmp_path: Path) -> None:
    report = readiness.build_report(root=LAB_ROOT, observed_at_utc="2026-09-29T00:00:00Z")
    output = tmp_path / "readiness.json"

    assert readiness.write_report(report, output) == output
    before = output.read_bytes()
    with pytest.raises(readiness.ReadinessError, match="refuses overwrite"):
        readiness.write_report(report, output)
    assert output.read_bytes() == before
    assert json.loads(before)["status"] == "blocked_fail_closed"
