from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f3_native_mls_acceptance_bridge_v2 import (
    CDF_LIMIT,
    FULL_WINDOW_S,
    INPUTS,
    NATIVE_INTERVAL_S,
    RECEIPT_SCHEMA,
    SCHEMA,
    UNKNOWN_LIMIT,
    build_reconciliation,
    verify_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f3-native-mls-acceptance-bridge-v2/reconciliation-v1-20260922.json"
)
REPORT = ROOT / "reports/F3-NATIVE-MLS-ACCEPTANCE-BRIDGE-V2-2026-09-22.zh-CN.md"


def test_reconciliation_is_zero_credit_and_repairs_current_hash_closure() -> None:
    value = build_reconciliation(ROOT)
    assert value["schema"] == SCHEMA
    assert value["candidate"]["qualification_claim"] == "none"
    assert value["candidate"]["credit"] == 0
    assert value["qualification_claim"] == "none"
    assert value["credit"] == 0
    assert value["qualification_credit"] == 0
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    binding = value["input_bindings"]["core_material"]
    source = ROOT / binding["path"]
    assert binding["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert binding["sha256"] != "75564f6fba20f8f3298dd6882e211ad4ad8278676c67083fb24e4ab140bb614c"


def test_schema_cadence_metrics_and_right_censoring_are_bound_fail_closed() -> None:
    value = build_reconciliation(ROOT)
    fixed = value["fixed_gates"]
    assert fixed["unknown_fraction_per_source_max"] == UNKNOWN_LIMIT
    assert fixed["cdf_sup_abs_difference_max"] == CDF_LIMIT
    assert fixed["native_source_interval_s"] == NATIVE_INTERVAL_S
    assert fixed["full_source_window_s"] == FULL_WINDOW_S
    schemas = value["trace_and_checkpoint_schema"]
    assert schemas["schema_gate_pass"] is True
    assert schemas["observed_row24"]["trace_schema"] == "core.material.f3.native_volume_mls.trace.v2"
    assert schemas["observed_row24"]["checkpoint_schema"] == "core.material.f3.native_volume_mls.checkpoint.v2"
    assert schemas["observed_row28"]["trace_schema"] == "core.material.f3.native_volume_mls.trace.v2"
    assert schemas["observed_row28"]["checkpoint_schema"] == "core.material.f3.native_volume_mls.checkpoint.v2"
    dense = value["source_cadence_and_window"]["dense_cadence_failure"]
    assert dense["declared_nominal_interval_s"] == 0.01
    assert dense["required_native_interval_s"] == NATIVE_INTERVAL_S
    assert dense["cadence_gate_pass"] is False
    assert value["right_censoring"]["right_censored_is_not_acceptance"] is True
    assert value["acceptance_gates"]["full_event_window"] is False


def test_rows_28_32_row24_and_missing_sources_are_explicit() -> None:
    value = build_reconciliation(ROOT)
    rows = value["matrix"]["rows"]
    assert len(rows) == 33
    assert [row["row"] for row in rows] == list(range(33))
    assert all(row["formal_acceptance_receipt"] is False for row in rows)
    assert all(row["credit"] == 0 for row in rows)
    by_row = {row["row"]: row for row in rows}
    assert by_row[24]["reconciliation_status"] == "terminal_negative_receipt_zero_credit"
    assert by_row[28]["reconciliation_status"] == "profile_source_audit_only_zero_credit"
    assert by_row[32]["reconciliation_status"] == "source_available_but_no_source_audit"
    reconciled = value["source_closure_reconciliation"]["rows_28_32"]
    assert reconciled["reconciled_row28"]["source_audit_present"] is True
    assert reconciled["reconciled_row28"]["observed_committed_frames"] == 21
    assert reconciled["reconciled_row28"]["full_event_window"] is False
    assert reconciled["reconciled_row32"]["source_audit_present"] is False
    assert value["matrix"]["formal_acceptance_receipt_count"] == 0
    assert value["matrix"]["material_matrix_ready"] is False


def test_row24_preserves_all_three_cdf_events_and_zero_credit() -> None:
    value = build_reconciliation(ROOT)
    row24 = value["cdf_metrics"]["row24"]
    assert set(row24["by_source"]) == {"0", "1"}
    assert row24["first_passage_receipt"] is True
    assert row24["return_receipt"] is True
    assert row24["residence_receipt"] is True
    assert row24["gate_results"]["first_passage_cdf_gate_pass"] is False
    assert row24["gate_results"]["return_cdf_gate_pass"] is False
    assert row24["gate_results"]["residence_cdf_gate_pass"] is True
    assert row24["scientific_acceptance"] is False
    assert row24["credit"] == 0


def test_artifact_is_versioned_read_only_and_hash_verifiable() -> None:
    assert EVIDENCE.is_file()
    assert REPORT.is_file()
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert value["formal_acceptance_receipt"]["schema"] == RECEIPT_SCHEMA
    assert value["formal_acceptance_receipt"]["credit"] == 0
    constraints = value["execution_constraints"]
    assert constraints["read_only"] is True
    assert constraints["hdf5_opened"] is False
    assert constraints["solver_started"] is False
    assert constraints["gpu_started"] is False
    assert constraints["queue_started"] is False
    assert constraints["new_cfd_generated"] is False
    assert constraints["queue_mutation"] == 0
    assert constraints["registry_mutation"] == 0
    assert constraints["central_ledger_mutation"] == 0
    assert constraints["matrix_mutation"] == 0
    assert constraints["T1_denominator_changed"] is False
    assert constraints["T2_denominator_changed"] is False
    assert constraints["historical_receipts_overwritten"] is False
    assert "历史 gap audit 的旧 hash" in REPORT.read_text(encoding="utf-8")
    assert set(INPUTS) == set(value["input_bindings"])
    verified = verify_receipt(EVIDENCE, ROOT)
    assert verified["schema"] == SCHEMA
