"""Fail-closed tests for the real F3 material coarse scheduler-result intake."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f3_material_coarse_terminal_result_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / intake.DEFAULT_REPORT
ZH_REPORT = ROOT / intake.DEFAULT_ZH_REPORT


def _check(report: dict, name: str) -> dict:
    return next(item for item in report["validation"]["checks"] if item["check"] == name)


def test_real_scheduler_attempt_is_successful_but_negative_diagnostic() -> None:
    report = intake.build_report(ROOT)

    assert intake.validate_report(report) == []
    assert report["status"] == "negative_diagnostic"
    assert report["runtime_reference"]["scheduler_owned"] is True
    assert report["runtime_reference"]["portable_artifact"] is False
    assert report["runtime_reference"]["static_formal_receipt"] is False
    assert report["runtime_reference"]["classification"] == (
        "scheduler_owned_runtime_receipt_reference_not_static_formal_receipt"
    )
    assert _check(report, "execution_receipt_success")["passed"] is True
    assert _check(report, "mass_closure")["passed"] is True
    assert _check(report, "unknown_monotonicity")["passed"] is True
    assert _check(report, "unknown_gate")["passed"] is True
    assert _check(report, "coverage")["passed"] is True
    assert report["material_terminal"]["native_frame_count"] == 836
    assert report["material_terminal"]["committed_frame"] == 835
    assert report["material_terminal"]["transition_count"] == 835
    assert report["material_terminal"]["committed_transition"] == 835
    assert report["validation"]["unknown_gate_negative_diagnostic"] == {
        "recorded": True,
        "observed_unknown_fraction_max": 0.0625,
        "limit": 0.01,
        "above_one_percent": True,
        "message": "unknown_fraction_max exceeds 1%; retain as negative diagnostic and do not promote.",
    }
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["T2_macro"] is False
    assert report["authorization"]["credit"] == 0


def test_all_scheduler_artifact_hashes_are_recomputed_and_match() -> None:
    report = intake.build_report(ROOT)
    artifacts = report["artifact_hashes"]["scheduler_artifact_index"]

    assert len(artifacts) == 8
    assert {item["path"] for item in artifacts} >= set(intake.REQUIRED_ARTIFACTS)
    assert all(item["hash_match"] is True for item in artifacts)
    assert all(item["stable_read"] is True for item in artifacts)
    assert report["artifact_hashes"]["source_hdf5_hash_recomputed"] is False


def test_source_snapshot_and_native_input_claims_are_distinct_and_bound() -> None:
    report = intake.build_report(ROOT)
    source = report["input_bindings"]["source"]

    assert source["source_snapshot"]["sha256"] == intake.EXPECTED_SOURCE_SNAPSHOT_SHA256
    assert source["source_snapshot"]["sha256"] == source["source_snapshot"]["result_sha256"]
    assert source["source_input"]["sha256"] == intake.EXPECTED_SOURCE_INPUT_SHA256
    assert source["source_input"]["sha256"] == source["material_binding_source_sha256"]
    assert source["source_input"]["opened"] is False
    assert source["source_input"]["read"] is False
    assert source["source_input"]["hash_recomputed"] is False


def test_full_frame_transition_binding_rejects_truncation() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["material_terminal"]["native_frame_count"] = 835

    assert "material_terminal.native_frame_count" in intake.validate_report(forged)


def test_unknown_negative_diagnostic_cannot_be_promoted() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["validation"]["unknown_gate_negative_diagnostic"]["above_one_percent"] = False

    assert "validation.unknown_gate_negative_diagnostic" in intake.validate_report(forged)


def test_tampered_artifact_hash_fails_closed() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["artifact_hashes"]["scheduler_artifact_index"][0]["actual_sha256"] = "0" * 64

    errors = intake.validate_report(forged)
    assert "artifact_hashes[0].declared_actual" in errors


def test_tampered_authorization_cannot_mint_credit() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["authorization"]["credit"] = 1
    forged["authorization"]["T2_macro"] = True

    errors = intake.validate_report(forged)
    assert "authorization.credit" in errors
    assert "authorization.T2_macro" in errors


def test_missing_attempt_is_blocked_without_authorization(tmp_path: Path) -> None:
    report = intake.build_report(tmp_path, intake.ATTEMPT_RELATIVE)

    assert report["status"] == "blocked_fail_closed"
    assert intake.validate_report(report)
    assert report["authorization"]["credit"] == 0
    assert report["execution_controls"]["attempt_mutations"] == 0


def test_checked_in_json_and_chinese_report_match_live_attempt() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert report == intake.build_report(ROOT)
    assert intake.validate_report(report) == []
    assert ZH_REPORT.read_text(encoding="utf-8").startswith(
        "# F3 material coarse terminal-result intake RERUN1"
    )
    assert "scheduler-owned runtime receipt" in ZH_REPORT.read_text(encoding="utf-8")


def test_report_writers_are_create_only(tmp_path: Path) -> None:
    report = intake.build_report(ROOT)
    output = tmp_path / "report.json"
    zh_output = tmp_path / "report.zh-CN.md"

    assert intake.write_report(report, output) == output
    assert intake.write_zh_cn(report, zh_output) == zh_output
    with pytest.raises(FileExistsError):
        intake.write_report(report, output)
    with pytest.raises(FileExistsError):
        intake.write_zh_cn(report, zh_output)


def test_malformed_report_is_rejected() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["runtime_reference"]["static_formal_receipt"] = True

    assert "report.runtime_reference.static_formal_receipt" in intake.validate_report(forged)
