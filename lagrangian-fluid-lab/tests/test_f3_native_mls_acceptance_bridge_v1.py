from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f3_native_mls_acceptance_bridge_v1 import (
    CDF_LIMIT,
    FULL_WINDOW_S,
    INPUTS,
    NATIVE_INTERVAL_S,
    RECEIPT_SCHEMA,
    SCHEMA,
    UNKNOWN_LIMIT,
    build_bridge,
    verify_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f3-native-mls-acceptance-bridge-v2-20260922.json"
)
REPORT = ROOT / "reports/F3-NATIVE-MLS-ACCEPTANCE-BRIDGE-2026-09-22.zh-CN.md"


def test_bridge_is_blocked_and_preserves_fixed_negative_gates() -> None:
    value = build_bridge(ROOT)

    assert value["schema"] == SCHEMA
    assert value["status"] == "blocked_for_acceptance"
    assert value["decision"] == "blocked"
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == "none"
    assert value["fixed_gates"]["unknown_fraction_per_source_max"] == UNKNOWN_LIMIT
    assert value["fixed_gates"]["cdf_sup_abs_difference_max"] == CDF_LIMIT
    assert value["fixed_gates"]["native_source_interval_s"] == NATIVE_INTERVAL_S
    assert value["fixed_gates"]["full_source_window_s"] == FULL_WINDOW_S
    assert value["per_source_unknown"]["maximum_observed"] == 0.015625
    assert value["cdf_bounds"]["maximum_observed"] == 0.06103515625
    assert value["formal_acceptance_receipt"]["schema"] == RECEIPT_SCHEMA
    assert value["formal_acceptance_receipt"]["status"] == "blocked"
    assert value["formal_acceptance_receipt"]["credit"] == 0


def test_bridge_binds_trace_checkpoint_cadence_and_event_provenance() -> None:
    value = build_bridge(ROOT)
    rows = value["trace_and_checkpoint_schema"]["rows"]
    assert len(rows) == 2
    assert {row["trace_schema"] for row in rows} == {
        "core.material.f3.native_volume_mls.trace.v2"
    }
    assert {row["checkpoint_schema"] for row in rows} == {
        "core.material.f3.native_volume_mls.checkpoint.v2"
    }
    source = value["source_window_provenance"]
    assert source["audit_binding"]["path"].endswith(
        "f3-f4-t2-cpu-source-window-audit-v1-20260920.json"
    )
    assert all(row["full_window_complete"] for row in source["rows"])

    cadence = value["cadence_provenance"]
    assert cadence["native_interval_s"] == NATIVE_INTERVAL_S
    assert cadence["source_preflight_pass"] is True
    assert cadence["direct_every_fifth_view"]["pass"] is True
    assert cadence["direct_every_fifth_view"]["derived_view_is_independent_solve"] is False
    assert cadence["bounded_canary"]["full_event_window"] is False
    assert cadence["bounded_canary"]["right_censored"] is True
    assert cadence["bounded_canary"]["acceptance_credit"] == 0

    event = value["event_contract"]
    assert "continuous crossing" in event["first_passage"]
    assert "first later crossing" in event["return"]
    assert "accepted segment time" in event["residence"]
    assert event["right_censoring"]["right_censored_counts_as_acceptance"] is False
    assert event["right_censoring"]["full_window_required_for_acceptance"] is True


def test_unknown_and_all_three_cdf_metrics_are_per_source() -> None:
    value = build_bridge(ROOT)
    unknown_rows = value["per_source_unknown"]["rows"]
    assert len(unknown_rows) == 2
    assert all(len(row["sources"]) == 2 for row in unknown_rows)
    for row in unknown_rows:
        for source in row["sources"]:
            assert source["seed_denominator"] == 2048
            assert source["terminal_unknown_count"] == round(
                source["terminal_unknown_fraction"] * source["seed_denominator"]
            )
            assert source["denominator_policy"]

    cdf = value["cdf_bounds"]
    assert cdf["event_names"] == ["first_passage", "return", "residence"]
    assert cdf["source_count"] == 2
    assert cdf["source_rows_reused_across_diagnostic_rows"] is True
    assert len(cdf["by_source"]) == 2
    for source in cdf["by_source"]:
        assert source["first_passage_cdf_sup_abs_difference"] > CDF_LIMIT
        assert source["return_cdf_sup_abs_difference"] > CDF_LIMIT
        assert source["residence_cdf_sup_abs_difference"] > CDF_LIMIT
        assert source["residence_cdf_bounds_present"] is True


def test_diagnostic_matrix_cannot_promote_t2_and_constraints_are_zero() -> None:
    value = build_bridge(ROOT)
    matrix = value["matrix"]
    assert matrix["registered_row_count"] == 33
    assert len(matrix["diagnostic_terminal_rows"]) == 16
    assert matrix["upstream_formal_acceptance_receipt_count"] == 0
    assert matrix["formal_acceptance_receipt_count"] == 0
    assert matrix["diagnostic_rows_do_not_upgrade_t2"] is True
    assert matrix["material_matrix_ready"] is False
    assert value["acceptance_gates"]["per_matrix_formal_acceptance_receipts"] is False
    assert value["admission_surface_pass"] is False

    constraints = value["execution_constraints"]
    assert constraints["read_only"] is True
    assert constraints["source_h5_opened"] is False
    assert constraints["terminal_h5_opened"] is False
    assert constraints["solver_started"] is False
    assert constraints["gpu_started"] is False
    assert constraints["queue_mutation"] == 0
    assert constraints["registry_mutation"] == 0
    assert constraints["central_ledger_mutation"] == 0
    assert constraints["matrix_mutation"] == 0
    assert constraints["T1_denominator_changed"] is False
    assert constraints["T2_denominator_changed"] is False
    assert constraints["thresholds_changed"] is False
    assert constraints["old_evidence_overwritten"] is False


def test_artifact_and_hash_closure_are_versioned() -> None:
    assert EVIDENCE.is_file()
    assert REPORT.is_file()
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert value["formal_acceptance_receipt"]["schema"] == RECEIPT_SCHEMA
    assert "T2_macro=false" in REPORT.read_text(encoding="utf-8")
    assert "zero credit" in REPORT.read_text(encoding="utf-8")

    verified = verify_receipt(EVIDENCE, ROOT)
    assert verified["schema"] == SCHEMA
    assert set(INPUTS) == set(value["input_bindings"])
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name
