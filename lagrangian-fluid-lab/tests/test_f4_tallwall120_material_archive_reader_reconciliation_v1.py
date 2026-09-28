from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import f4_tallwall120_material_archive_reader_reconciliation_v1 as reconciliation


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / reconciliation.DEFAULT_REPORT


def _checked_in_report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_report_recomputes_from_bounded_archive_and_reader_inputs() -> None:
    assert reconciliation.build_report(ROOT) == _checked_in_report()


def test_archives_v1_v2_are_distinct_manifests_with_same_artifact_identity() -> None:
    report = _checked_in_report()
    assert report["archives"]["v1"]["path"].endswith("production-archives-v1/f4-tallwall120-production-dev-07/archive.json")
    assert report["archives"]["v2"]["path"].endswith("production-archives-v2/f4-tallwall120-production-dev-07/archive.json")
    assert report["archives"]["v1"]["manifest_sha256"] != report["archives"]["v2"]["manifest_sha256"]
    assert report["checks"]["archive_v1_v2_manifest_bytes_distinct"] is True
    assert report["checks"]["archive_v1_v2_artifact_identity_exact"] is True
    assert report["source_reconciliation"]["archives_v1_v2_artifact_identity_exact"] is True


def test_collection_path_and_reader_sha_drift_remain_blocking() -> None:
    report = _checked_in_report()
    checks = report["checks"]
    assert checks["collection_case_source_path_exact"] is False
    assert checks["collection_case_source_sha_exact"] is True
    assert checks["reader_manifest_path_exact"] is True
    assert checks["reader_manifest_sha_exact"] is False
    findings = {item["finding"] for item in report["findings"]}
    assert "collection_manifest_archives_v1_vs_archives_v2_path_drift" in findings
    assert "reader_manifest_sha_stale" in findings
    assert report["source_reconciliation"]["ready"] is False


def test_missing_root_and_scheduler_receipts_keep_authority_closed() -> None:
    report = _checked_in_report()
    prerequisites = report["root_scheduler_prerequisites"]
    authority = report["authority"]
    assert prerequisites["fresh_root_receipt_present"] is False
    assert prerequisites["scheduler_host_io_reservation_present"] is False
    assert prerequisites["accepted_as_authority"] is False
    assert authority["launch_allowed"] is False
    assert authority["worker_launch_authorized"] is False
    assert authority["credit"] == 0


def test_report_is_fail_closed_and_non_mutating() -> None:
    report = _checked_in_report()
    assert reconciliation.validate_report(report) == []
    controls = report["execution_controls"]
    assert controls["bounded_json_only"] is True
    assert controls["archive_hdf5_opened"] is False
    assert controls["source_hdf5_opened"] is False
    assert controls["source_hdf5_read"] is False
    assert controls["source_hdf5_hash_recomputed"] is False
    assert controls["solver_started"] is False
    assert controls["worker_started"] is False
    assert controls["gpu_started"] is False
    assert controls["queue_or_scheduler_started"] is False
    assert all(controls[key] == 0 for key in (
        "registry_mutations", "ledger_mutations", "denominator_mutations",
        "gate_mutations", "completion_mutations", "plan_mutations",
    ))


def test_validator_rejects_promoted_authority() -> None:
    report = copy.deepcopy(_checked_in_report())
    report["authority"]["launch_allowed"] = True
    errors = reconciliation.validate_report(report)
    assert "authority.launch_allowed" in errors


def test_empty_root_stays_blocked_without_creating_receipts(tmp_path: Path) -> None:
    report = reconciliation.build_report(tmp_path)
    assert report["status"] == "blocked_fail_closed"
    assert report["authority"]["launch_allowed"] is False
    assert report["execution_controls"]["fresh_root_receipt_written"] is False
    assert report["execution_controls"]["scheduler_receipt_written"] is False
