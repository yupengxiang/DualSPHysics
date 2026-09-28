from __future__ import annotations

import json
from pathlib import Path

from scripts import f4_tallwall120_material_source_drift_reconciliation_v1 as reconciliation


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT = LAB_ROOT / "reports/F4-TALLWALL120-MATERIAL-SOURCE-DRIFT-RECONCILIATION-V1-2026-09-28.json"


def _checked_in_report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_report_recomputes_exactly_from_bounded_inputs() -> None:
    assert reconciliation.build_report(LAB_ROOT) == _checked_in_report()


def test_source_drift_is_explicit_and_source_sha_remains_consistent() -> None:
    report = _checked_in_report()
    checks = report["checks"]

    assert checks["proposal_target_exact"] is True
    assert checks["collection_row_path_exact"] is False
    assert checks["collection_row_source_sha_exact"] is True
    assert checks["reader_manifest_path_exact"] is True
    assert checks["reader_manifest_sha_exact"] is False
    assert checks["source_sha_consistent_without_hdf5_rehash"] is True
    assert report["source_reconciliation"]["ready"] is False
    findings = {item["finding"] for item in report["findings"]}
    assert "collection_manifest_archives_v1_vs_target_archives_v2_mismatch" in findings
    assert "reader_smoke_manifest_sha_stale" in findings


def test_existing_dev07_diagnostic_is_not_reused() -> None:
    report = _checked_in_report()
    checks = report["checks"]
    diagnostic = report["existing_diagnostic"]

    assert checks["diagnostic_source_path_exact"] is True
    assert checks["diagnostic_source_unchanged_claim"] is True
    assert checks["diagnostic_parameter_binding"] is False
    assert diagnostic["parameters"]["q"] == 0.5
    assert checks["diagnostic_full_event_window"] is False
    assert checks["diagnostic_unknown_gate"] is False
    assert checks["diagnostic_reliable_coverage"] is False
    assert diagnostic["decision"]["T2"] is False
    assert diagnostic["decision"]["credit"] == 0


def test_missing_authority_receipts_keep_actual_sidecar_closed() -> None:
    report = _checked_in_report()
    authority = report["authority"]
    root_scheduler = report["root_scheduler"]

    assert root_scheduler["validation_checks"]["future_root_receipt_present"] is False
    assert root_scheduler["validation_checks"]["future_scheduler_receipt_present"] is False
    assert authority["credible_fresh_root_receipt"] is False
    assert authority["credible_scheduler_owned_io_receipt"] is False
    assert authority["pair_cross_bound"] is False
    assert authority["actual_sidecar_execution_allowed"] is False
    assert authority["sidecar_executed"] is False
    assert len(report["minimum_external_inputs"]) == 4
    assert all(item["present"] is False for item in report["minimum_external_inputs"])


def test_reconciliation_is_strictly_fail_closed() -> None:
    report = _checked_in_report()
    errors = reconciliation.validate_report(report)
    assert errors == []
    controls = report["execution_controls"]
    assert controls["trajectory_hdf5_lstat_only"] is True
    assert controls["source_hdf5_opened"] is False
    assert controls["source_hdf5_read"] is False
    assert controls["source_hdf5_hash_recomputed"] is False
    assert controls["authority_receipt_written"] is False
    assert controls["material_sidecar_written"] is False
    assert all(controls[key] == 0 for key in ("registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations", "completion_mutations", "plan_mutations"))


def test_build_report_never_opens_trajectory_hdf5(monkeypatch) -> None:
    original_open = Path.open
    original_read_bytes = Path.read_bytes

    def guarded_open(path: Path, *args, **kwargs):
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise AssertionError(f"reconciliation attempted to open HDF5: {path}")
        return original_open(path, *args, **kwargs)

    def guarded_read_bytes(path: Path, *args, **kwargs):
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise AssertionError(f"reconciliation attempted to read HDF5: {path}")
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    report = reconciliation.build_report(LAB_ROOT)
    assert report["source_identity"]["hdf5_metadata"]["mode"] == "lstat_metadata_only"
    assert report["execution_controls"]["source_hdf5_opened"] is False
    assert report["execution_controls"]["source_hdf5_read"] is False


def test_report_does_not_claim_gpu_or_scheduler_authority() -> None:
    report = _checked_in_report()
    assert report["authority"]["credible_scheduler_owned_io_receipt"] is False
    assert report["execution_controls"]["gpu_started"] is False
    assert report["execution_controls"]["queue_or_scheduler_started"] is False
