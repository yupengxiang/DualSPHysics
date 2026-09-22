from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f3_t2_admission_acceptance_gap_audit_v1 import (
    INPUTS,
    SCHEMA,
    build_audit,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f3-t2-admission-acceptance-gap-audit-v2-20260922.json"
)
REPORT = ROOT / "reports/F3-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-22.zh-CN.md"


def test_audit_preserves_negative_scientific_gates_and_denominators() -> None:
    value = build_audit(ROOT)
    source = value["observed_gate_comparison"]["source_window"]
    assert value["schema"] == SCHEMA
    assert value["status"] == "blocked_for_macro_t2"
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == "none"
    assert source["row_count"] == 2
    assert source["source_window_integrity_pass"] is True
    assert source["unknown_mass"]["maximum_observed"] == 0.015625
    assert source["unknown_mass"]["failing_source_count"] == 3
    assert source["unknown_mass"]["all_rows_pass"] is False
    assert source["cdf"]["maximum_observed"] == 0.06103515625
    assert source["cdf"]["all_rows_pass"] is False
    assert value["current_qualification_state"]["overall_T2_credit"] == 0
    assert value["current_qualification_state"]["T1_numerical"] is True
    assert value["current_qualification_state"]["T2_macro"] is False
    assert value["current_qualification_state"]["T2_path"] is False


def test_native_cadence_and_event_window_are_separated_from_acceptance() -> None:
    value = build_audit(ROOT)
    cadence = value["observed_gate_comparison"]["native_cadence"]
    canary = cadence["bounded_canary"]
    assert cadence["source_preflight_pass"] is True
    assert cadence["source"]["interpolation"] is False
    assert cadence["direct_every_fifth_view"]["pass"] is True
    assert canary["full_event_window"] is False
    assert canary["right_censored"] is True
    assert canary["matrix_credit"] == 0
    assert cadence["material_acceptance_pass"] is False
    assert value["acceptance_gates"]["native_cadence_source_preflight"] is True
    assert value["acceptance_gates"]["native_cadence_material_acceptance"] is False
    assert value["acceptance_gates"]["event_window_acceptance_for_bounded_canary"] is False


def test_matrix_and_material_sidecar_gaps_fail_closed() -> None:
    value = build_audit(ROOT)
    matrix = value["matrix"]
    contracts = value["code_contracts"]
    acceptance = contracts["core_material_acceptance"]
    comparison = value["observed_gate_comparison"]["comparison"]
    assert matrix["registered_row_count"] == 33
    assert matrix["status_counts"] == {
        "blocked_missing_registered_source": 12,
        "native_dense_material_postprocess_running": 1,
        "related_v3_s2_diagnostic_running_not_canonical_s4_row": 1,
        "source_available_not_submitted": 2,
        "terminal_diagnostic_observed": 16,
        "terminal_matched_decimation_diagnostic_only": 1,
    }
    assert len(matrix["diagnostic_terminal_rows"]) == 16
    assert matrix["formal_acceptance_receipt_count"] == 0
    assert matrix["material_matrix_ready"] is False
    assert comparison["residence_cdf_present"] is True
    assert acceptance["per_source_unknown_gate"] is True
    assert acceptance["generic_cdf_difference_gate"] is True
    assert acceptance["native_mls_trace_schema"] is False
    assert acceptance["native_mls_checkpoint_schema"] is False
    assert acceptance["residence_cdf_gate"] is False
    assert acceptance["f3_event_definition_gate"] is False
    assert acceptance["native_cadence_gate"] is False
    assert acceptance["per_matrix_acceptance_gate"] is False
    assert value["admission_surface_pass"] is False


def test_audit_artifact_binds_inputs_and_keeps_mutations_zero() -> None:
    assert EVIDENCE.is_file()
    assert REPORT.is_file()
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    constraints = value["execution_constraints"]
    assert constraints["read_only"] is True
    assert constraints["solver_started"] is False
    assert constraints["gpu_started"] is False
    assert constraints["new_job_submitted"] is False
    assert constraints["queue_mutation"] == 0
    assert constraints["registry_mutation"] == 0
    assert constraints["central_ledger_mutation"] == 0
    assert constraints["matrix_mutation"] == 0
    assert constraints["T1_denominator_changed"] is False
    assert constraints["T2_denominator_changed"] is False
    assert constraints["thresholds_changed"] is False
    assert constraints["old_evidence_overwritten"] is False
    assert "T2_macro=false" in REPORT.read_text(encoding="utf-8")
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name
    assert set(INPUTS) == set(value["input_bindings"])


def test_minimal_repair_preserves_fixed_gates_and_does_not_execute_work() -> None:
    value = build_audit(ROOT)
    repair = value["minimal_next_executable_repair"]
    assert repair["status"] == "required_before_any_future_material_acceptance"
    assert repair["priority"] == "Core W0/W1"
    assert "core.material.f3.native_volume_mls.trace.v1/v2 binding and checkpoint schema" in repair[
        "must_accept"
    ]
    assert "residence_cdf_bounds" in " ".join(repair["must_accept"])
    assert "unknown <= 0.01 and CDF sup <= 0.02" in repair["must_preserve"]
    assert "33-row matrix definition and exact source lineage" in repair["must_preserve"]
    assert repair["follow_on_evidence"]["qualification_effect"].startswith("none")
    assert repair["audit_did_not_execute"] is True
