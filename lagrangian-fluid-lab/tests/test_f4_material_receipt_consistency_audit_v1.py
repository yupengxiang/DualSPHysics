import json
from pathlib import Path

from scripts import f4_material_receipt_consistency_audit_v1 as audit


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json"


def _checked_in_report():
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _check(report, name):
    return next(item for item in report["checks"] if item["check"] == name)


def test_report_matches_checked_in_report():
    assert audit.build_report(ROOT) == _checked_in_report()


def test_audit_is_fail_closed_and_never_credits_t2():
    report = _checked_in_report()

    assert report["status"] == "blocked_fail_closed"
    assert report["audit_only"] is True
    assert report["diagnostic_only"] is True
    assert report["formal_eligible"] is False
    assert report["qualification"]["T1"] is False
    assert report["qualification"]["T2"] is False
    assert report["qualification"]["credit"] == 0
    assert report["qualification"]["qualification_credit"] == 0
    assert all(value == 0 for key, value in report["qualification"].items() if key.endswith("_mutations"))
    assert all(value is False for key, value in report["execution_controls"].items() if key.endswith("_mutation"))


def test_reader_smoke_manifest_sha_drift_is_detected():
    report = _checked_in_report()
    check = _check(report, "reader_smoke_manifest_sha_matches_current")

    assert check["passed"] is False
    assert check["observed"] == "86100523e66202f567ee29da6e178702f0e3ab19c63bd0cf861ff8a5fa0f86b4"
    assert check["expected"] == "808fe201c4df28f2be9b48a514f338689c38bcb96db0b0c0590946b79fb9ad09"
    assert report["reader_smoke_binding"]["manifest_sha_matches_current"] is False


def test_archives_v1_v2_mismatch_is_explicit():
    report = _checked_in_report()
    check = _check(report, "archives_v1_v2_path_exact")

    assert check["passed"] is False
    assert report["archives_path_binding"]["mismatch_class"] == "archives-v1_vs_archives-v2"
    assert "/f4-tallwall120-production-archives-v1/" in check["observed"]
    assert "/f4-tallwall120-production-archives-v2/" in check["expected"]
    assert report["archives_path_binding"]["source_sha256_match"] is True


def test_dev07_diagnostic_is_bound_but_remains_negative():
    report = _checked_in_report()

    assert _check(report, "dev07_diagnostic_source_path_matches_target")["passed"] is True
    assert _check(report, "dev07_diagnostic_source_sha_matches_target")["passed"] is True
    assert _check(report, "dev07_diagnostic_negative_boundary_is_preserved")["passed"] is True
    binding = report["dev07_diagnostic_binding"]
    assert binding["source_path_matches_target"] is True
    assert binding["source_sha256_matches_target"] is True
    assert binding["event_window_complete"] is False
    assert binding["event_window_status"] == "right_censored_or_unresolved"
    assert binding["unknown_fraction_max"] == 1.0
    assert binding["common_reliable_path_coverage"] == 0.0
    assert binding["T2"] is False
    assert binding["credit"] == 0
    assert binding["promote"] is False


def test_current_planner_and_historical_receipt_drift_is_explicit():
    report = _checked_in_report()

    assert report["planner_binding"]["semantic_projection_match"] is True
    assert report["planner_binding"]["raw_top_level_shape_match"] is False
    assert report["planner_binding"]["derived_blocker_projection_match"] is False
    assert _check(report, "planner_raw_report_shape_matches_committed_receipt")["passed"] is False
    assert _check(report, "planner_blocker_projection_exact")["passed"] is False
    finding_names = {item["finding"] for item in report["findings"]}
    assert "committed_proposal_receipt_projection_drift" in finding_names
    assert "committed_proposal_receipt_omits_current_derived_blocker" in finding_names


def test_build_report_never_opens_hdf5_content(monkeypatch):
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise AssertionError(f"audit attempted to open HDF5 content: {path}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    report = audit.build_report(ROOT)

    assert report["input_boundary"]["hdf5_opened"] is False
    assert report["input_boundary"]["hdf5_content_read"] is False
    assert report["input_boundary"]["hdf5_hash_recomputed"] is False
    assert report["inputs"]["hdf5_metadata"]["content_read"] is False
    assert report["inputs"]["hdf5_metadata"]["content_hash_recomputed"] is False
