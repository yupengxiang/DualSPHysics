"""CPU-only tests for the fixed-gate minimal repair audit."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.f3_f4_t2_minimal_repair_audit_v1 import (
    CDF_LIMIT,
    EVENT_WINDOW_S,
    UNKNOWN_LIMIT,
    build_report,
    maximum_allowed_count,
)


def test_integer_budget_preserves_closed_fixed_denominator() -> None:
    assert maximum_allowed_count(2048, UNKNOWN_LIMIT) == 20
    assert maximum_allowed_count(512, UNKNOWN_LIMIT) == 5
    assert maximum_allowed_count(2048, CDF_LIMIT) == 40


def test_audit_reports_minimal_deficits_without_promoting_t2(tmp_path: Path) -> None:
    output = tmp_path / "minimal-repair.json"
    report = build_report(Path(__file__).resolve().parents[1], output)

    assert output.is_file()
    assert report["qualification_claim"] == "none"
    assert report["T2_macro"] is False
    assert report["T2_path"] is False
    assert report["independent_qualification_path_available"] is False
    assert report["registered_gates"]["unknown_fraction_per_source_max"] == UNKNOWN_LIMIT
    assert report["registered_gates"]["f4_full_registered_event_window_s"] == EVENT_WINDOW_S
    assert report["minimum_repair_deficits"]["f3"][
        "minimum_unknown_recovery_count_across_retained_rows"
    ] == 26
    assert report["minimum_repair_deficits"]["f3"][
        "minimum_cdf_bound_reduction_units_by_source"
    ] == {"0": 85, "1": 83}
    assert report["minimum_repair_deficits"]["f4"][
        "minimum_unknown_recovery_count_across_retained_cases"
    ] == 2796

    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["execution_constraints"]["terminal_h5_opened"] is False
    assert loaded["execution_constraints"]["registry_mutation"] == 0


def test_valid_checkpoint_does_not_close_missing_event_window() -> None:
    report = build_report(Path(__file__).resolve().parents[1])
    f4 = report["minimum_repair_deficits"]["f4"]
    assert f4["all_checkpoints_valid"] is True
    assert f4["all_event_windows_complete"] is False
    assert all(
        case["checkpoint_recovery_status"] == "valid_checkpoint_but_source_horizon_incomplete"
        for case in f4["cases"]
    )
    assert all(
        case["event_window"]["minimum_missing_horizon_s"] > 3.9
        for case in f4["cases"]
    )
    probe = f4["repair_candidate_probe"]
    for variant in ("f4_ess32_v2", "f4_affine_bound_v2"):
        assert probe[variant]["first_unknown_probe"]["frame"] == 81
        assert probe[variant]["first_unknown_probe"]["reconstruction_fail_count"] == 64
        assert probe[variant]["first_unknown_probe"]["support_distance_fail_count"] == 0


def test_f3_scope_and_f4_coverage_remain_open() -> None:
    report = build_report(Path(__file__).resolve().parents[1])
    coverage = report["coverage_audit"]
    assert coverage["f3"]["registered_rows"] == 33
    assert coverage["f3"]["formal_row_complete"] is False
    assert coverage["f4"]["registered_overlay_rows"] == 33
    assert coverage["f4"]["cadence_exact_pairs_complete"] is False
    assert coverage["f4"]["seed_density_4096_overlays_complete"] is False


def test_versioned_evidence_binds_inputs_and_implementation() -> None:
    lab_root = Path(__file__).resolve().parents[1]
    evidence = lab_root / "campaigns/core-v1/material/evidence/" \
        "f3-f4-t2-minimal-repair-audit-20260920.json"
    value = json.loads(evidence.read_text(encoding="utf-8"))
    assert value["schema"] == "core.material.t2.minimal_repair_audit.v1"
    assert value["qualification_claim"] == "none"
    for item in value["input_evidence"]:
        path = lab_root / item["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == item["sha256"]
    implementation = value["implementation_binding"]["script"]
    script = lab_root / implementation["path"]
    assert hashlib.sha256(script.read_bytes()).hexdigest() == implementation["sha256"]


def test_chinese_report_binds_receipt_and_preserves_core_gate() -> None:
    lab_root = Path(__file__).resolve().parents[1]
    report = lab_root / "reports/F3-F4-T2-MINIMAL-REPAIR-AUDIT-2026-09-20.zh-CN.md"
    receipt = lab_root / (
        "campaigns/core-v1/material/evidence/"
        "f3-f4-t2-minimal-repair-audit-20260920.json"
    )
    text = report.read_text(encoding="utf-8")
    assert report.is_file()
    assert "9a9799abd9e8f8f46b34496b61e60bf5cbab873336fb6d5c469748b72dcf4c20" in text
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() in text
    assert "T2_macro=false" in text
    assert "T2_path=false" in text
    assert "registry_mutation=0" in text
    assert "central_ledger_mutation=0" in text
