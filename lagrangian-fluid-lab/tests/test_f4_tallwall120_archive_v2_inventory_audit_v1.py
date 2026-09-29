from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import f4_tallwall120_archive_v2_inventory_audit_v1 as audit


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / audit.DEFAULT_REPORT


def _report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_checked_in_report_recomputes_from_bounded_metadata() -> None:
    assert audit.build_report(ROOT) == _report()


def test_variant_drift_and_production_inventory_are_explicit() -> None:
    report = _report()
    checks = report["checks"]
    assert checks["production_v1_32_case_inventory_complete"] is True
    assert checks["production_v1_archive_bundles_complete"] is True
    assert checks["production_v2_32_case_inventory_complete"] is False
    assert checks["production_v2_archive_bundles_complete_for_observed_entries"] is True
    assert checks["production_v1_archive_root_lock_present"] is True
    assert checks["production_v2_archive_root_lock_present"] is False
    assert checks["collection_uses_required_archives_v2_variant"] is False
    assert report["collection_source_audit"]["path_variant_drift_case_ids"] == list(audit.EXPECTED_CASE_IDS)


def test_v2_entries_do_not_mint_independent_archive_coverage() -> None:
    report = _report()
    comparison = report["production_archives"]["v1_v2_identity_comparison"]
    assert comparison["compared_case_count"] == 4
    assert comparison["same_artifact_identity_case_count"] == 4
    assert comparison["new_independent_case_count"] == 0
    assert all(
        row["archive_manifest_semantic_diff_keys"] == ["verified_at_unix_s"]
        for row in comparison["rows"]
    )


def test_sidecar_matrix_is_empty_and_qualification_archive_is_partial() -> None:
    report = _report()
    sidecars = report["material_sidecars"]
    assert sidecars["namespace_exists"] is False
    assert sidecars["json_file_count"] == 0
    assert sidecars["complete_case_count"] == 0
    assert sidecars["missing_case_ids"] == list(audit.EXPECTED_CASE_IDS)
    qualification = report["qualification_v2"]["inventory"]
    assert qualification["observed_directory_count"] == 13
    assert qualification["missing_directories"] == [
        "f4-tallwall120-qualification-cell-03",
        "f4-tallwall120-qualification-cell-12",
    ]


def test_every_hdf5_output_is_stat_only_and_every_observed_bundle_is_complete() -> None:
    report = _report()
    assert report["checks"]["hdf5_content_never_read_or_rehashed"] is True
    for inventory_name in ("v1", "v2"):
        inventory = report["production_archives"][inventory_name]
        for row in inventory["rows"].values():
            assert row["archive_bundle_complete"] is True
            assert row["receipt_hash_match"] is True
            for output in row["output_checks"]:
                if output["hdf5"]:
                    assert output["content_read"] is False
                    assert output["hash_recomputed"] is False


def test_report_is_fail_closed_and_non_mutating() -> None:
    report = _report()
    assert audit.validate_report(report) == []
    assert report["qualification"] == {
        "T1": False,
        "T2": False,
        "credit": 0,
        "formal": False,
        "status": "blocked_fail_closed",
    }
    controls = report["execution_controls"]
    assert controls["archive_copied"] is False
    assert controls["archive_converted"] is False
    assert controls["archive_overwritten"] is False
    assert controls["hdf5_read"] is False
    assert controls["formal_gate_mutations"] == 0
    assert controls["registry_mutations"] == 0
    assert controls["ledger_mutations"] == 0
    assert controls["plan_mutations"] == 0


def test_validator_rejects_an_attempt_to_promote_a_bounded_audit() -> None:
    report = copy.deepcopy(_report())
    report["qualification"]["T2"] = True
    assert "qualification" in audit.validate_report(report)


def test_empty_root_is_safe_and_does_not_infer_archive_completeness(tmp_path: Path) -> None:
    report = audit.build_report(tmp_path)
    assert report["status"] == "blocked_fail_closed"
    assert report["production_archives"]["v1"]["observed_directory_count"] == 0
    assert report["production_archives"]["v2"]["observed_directory_count"] == 0
    assert report["material_sidecars"]["complete_case_count"] == 0
    assert report["execution_controls"]["archive_copied"] is False
