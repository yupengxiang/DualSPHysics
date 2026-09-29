"""Fail-closed tests for the actual F3 material coarse s4 terminal receipt."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import f3_material_coarse_s4_terminal_result_intake_v1 as intake


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / intake.DEFAULT_REPORT
ZH_REPORT = ROOT / intake.DEFAULT_ZH_REPORT


def _check(report: dict, name: str) -> dict:
    return next(item for item in report["validation"]["checks"] if item["check"] == name)


def test_actual_s4_terminal_is_successful_but_negative_diagnostic() -> None:
    report = intake.build_report(ROOT)

    assert intake.validate_report(report) == []
    assert report["status"] == "negative_diagnostic"
    assert report["scope"]["variant"] == "coarse-s4"
    assert "s2" not in report["scope"]["candidate"]
    assert report["runtime_reference"]["scheduler_owned"] is True
    assert report["runtime_reference"]["portable_artifact"] is False
    assert report["runtime_reference"]["static_formal_receipt"] is False
    assert report["runtime_reference"]["classification"] == (
        "scheduler_owned_runtime_receipt_reference_not_static_formal_receipt"
    )
    assert _check(report, "execution_receipt_success")["passed"] is True
    assert _check(report, "mass_closure")["passed"] is True
    assert _check(report, "unknown_monotonicity")["passed"] is True
    assert _check(report, "coverage")["passed"] is True
    assert report["material_terminal"]["native_frame_count"] == 836
    assert report["material_terminal"]["transition_count"] == 835
    assert report["material_terminal"]["committed_frame"] == 835
    assert report["material_terminal"]["common_reliable_path_coverage"] == 0.947265625
    assert [row["unknown_fraction_max"] for row in report["material_terminal"]["sources"]] == [0.0625, 0.04296875]
    assert report["validation"]["unknown_gate_negative_diagnostic"] == {
        "recorded": True,
        "observed_unknown_fraction_max": 0.0625,
        "limit": 0.01,
        "above_one_percent": True,
        "message": "unknown_fraction_max exceeds 1%; retain as negative diagnostic and do not promote.",
    }
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["T2_macro"] is False
    assert report["authorization"]["T2_path"] is False
    assert report["authorization"]["credit"] == 0


def test_result_spec_material_bytes_and_sha_are_pinned() -> None:
    report = intake.build_report(ROOT)
    for name in intake.REQUIRED_JSON_FILES:
        reference = report["input_bindings"][name.removesuffix(".json") + "_json"]
        expected = intake.EXPECTED_FILE_BINDINGS[name]
        assert (reference["bytes"], reference["sha256"]) == expected
        assert reference["stable_read"] is True
        assert reference["content_read"] is True
        assert reference["expected_binding_match"] is True


def test_worker_host_source_and_runtime_identity_are_bound() -> None:
    report = intake.build_report(ROOT)
    identity = report["scheduler_identity"]
    assert identity["job_id"] == intake.JOB_ID
    assert identity["attempt_id"] == intake.ATTEMPT_ID
    assert identity["host"] == "ada"
    assert identity["spec_allocation_host"] == "ada"
    assert identity["result_allocation_host"] == "ada"
    assert identity["gpu_uuid"] is None
    assert identity["reserved_gpu_mib"] == 0
    assert identity["worker"] == identity["heartbeat_worker"]
    assert identity["worker"]["boot_id"]
    assert isinstance(identity["worker"]["pid"], int)
    assert isinstance(identity["worker"]["start_ticks"], int)
    source = report["input_bindings"]["source"]
    assert source["source_snapshot"]["sha256"] == intake.EXPECTED_SOURCE_SNAPSHOT_SHA256
    assert source["source_snapshot"]["sha256"] == source["source_snapshot"]["result_sha256"]
    assert source["source_input"]["sha256"] == intake.EXPECTED_SOURCE_INPUT_SHA256
    assert source["source_input"]["opened"] is False
    assert source["source_input"]["read"] is False
    assert source["source_input"]["hash_recomputed"] is False
    assert source["runtime_sha256"] == intake.EXPECTED_INPUTS


def test_all_scheduler_artifact_hashes_are_recomputed_and_match() -> None:
    report = intake.build_report(ROOT)
    artifacts = report["artifact_hashes"]["scheduler_artifact_index"]

    assert len(artifacts) == 8
    assert {item["path"] for item in artifacts} >= set(intake.REQUIRED_ARTIFACTS)
    assert all(item["hash_match"] is True for item in artifacts)
    assert all(item["stable_read"] is True for item in artifacts)
    assert report["artifact_hashes"]["source_hdf5_hash_recomputed"] is False


def test_truncated_frames_fail_closed() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["material_terminal"]["native_frame_count"] = 835
    assert "material_terminal.native_frame_count" in intake.validate_report(forged)


def test_unknown_gate_cannot_be_promoted() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["validation"]["unknown_gate_negative_diagnostic"]["above_one_percent"] = False
    assert "validation.unknown_gate_negative_diagnostic" in intake.validate_report(forged)


def test_tampered_input_hash_fails_closed() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["input_bindings"]["material_json"]["sha256"] = "0" * 64
    assert "input_bindings.material_json.binding" in intake.validate_report(forged)


def test_tampered_identity_and_authorization_fail_closed() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["scheduler_identity"]["host"] = "other-host"
    forged["authorization"]["credit"] = 1
    forged["authorization"]["T2_macro"] = True
    errors = intake.validate_report(forged)
    assert "scheduler_identity.job_attempt_host" in errors
    assert "authorization.no_promotion" in errors


def test_missing_attempt_is_blocked_without_authorization(tmp_path: Path) -> None:
    report = intake.build_report(tmp_path)

    assert report["status"] == "blocked_fail_closed"
    assert intake.validate_report(report)
    assert report["authorization"]["credit"] == 0
    assert report["execution_controls"]["attempt_mutations"] == 0


def test_checked_in_reports_match_the_live_attempt() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert report == intake.build_report(ROOT)
    assert intake.validate_report(report) == []
    zh = ZH_REPORT.read_text(encoding="utf-8")
    assert zh.startswith("# F3 material coarse s4 terminal-result intake RERUN1")
    assert "scheduler-owned runtime attempt" in zh
    assert "超过 1%" in zh


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


def test_static_formal_receipt_claim_is_rejected() -> None:
    report = intake.build_report(ROOT)
    forged = deepcopy(report)
    forged["runtime_reference"]["static_formal_receipt"] = True
    assert "report.runtime_reference.static_formal_receipt" in intake.validate_report(forged)
