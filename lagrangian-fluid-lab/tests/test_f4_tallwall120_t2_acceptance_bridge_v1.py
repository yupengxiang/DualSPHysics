from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.f4_tallwall120_t2_acceptance_bridge_v1 import (
    ENGINEERING_RECEIPT_SCHEMA,
    FORMAL_RECEIPT_SCHEMA,
    INPUTS,
    SCHEMA,
    build_bridge,
    verify_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260922-v3.json"
)
REPORT = ROOT / "reports/F4-TALLWALL120-T2-ACCEPTANCE-BRIDGE-2026-09-22-v3.zh-CN.md"


def test_engineering_receipt_is_distinct_from_blocked_scientific_qualification() -> None:
    value = build_bridge(ROOT, created_at_utc="2026-09-22T00:00:00+00:00")

    assert value["schema"] == SCHEMA
    assert value["status"] == "blocked"
    assert value["decision"] == "blocked"
    assert value["engineering_receipt"]["schema"] == ENGINEERING_RECEIPT_SCHEMA
    # The v3 bridge is historical: its upstream v2 gap audit has stale
    # implementation bindings, so its engineering receipt must remain stale.
    assert value["engineering_receipt"]["status"] == "blocked"
    assert value["engineering_receipt"]["input_hash_closure_pass"] is False
    assert value["engineering_receipt"]["qualification_effect"] == "none"
    assert value["scientific_qualification"]["status"] == "blocked"
    assert value["scientific_qualification"]["credit"] == 0
    assert value["formal_acceptance_receipt"]["schema"] == FORMAL_RECEIPT_SCHEMA
    assert value["formal_acceptance_receipt"]["status"] == "blocked"
    assert value["formal_acceptance_receipt"]["credit"] == 0
    assert value["formal_acceptance_receipt"]["T2_macro"] is False
    assert value["formal_acceptance_receipt"]["T2_path"] is False


def test_unknown_window_and_cdf_gates_fail_closed_without_importing_f3_threshold() -> None:
    value = build_bridge(ROOT, created_at_utc="2026-09-22T00:00:00+00:00")
    science = value["scientific_qualification"]
    gates = science["acceptance_gates"]

    assert science["unknown"]["maximum_observed"] == 1.0
    assert gates["per_source_unknown_fraction"] is False
    assert gates["full_event_window"] is False
    assert science["event_window"]["complete_case_count"] == 0
    assert gates["f4_cdf_tolerance_registered"] is False
    assert gates["f4_cdf_qualification"] is False
    assert science["cdf"]["tolerance"] is None
    assert science["cdf"]["f3_reference_limit_not_applied"] == 0.02
    assert gates["residence_fields_and_acceptance"] is False
    assert gates["event_tolerance_acceptance"] is False


def test_case_gaps_are_explicit_and_checkpoint_is_not_science_acceptance() -> None:
    value = build_bridge(ROOT, created_at_utc="2026-09-22T00:00:00+00:00")
    cases = value["case_gaps"]
    assert len(cases) == 6
    assert value["case_summary"]["formal_acceptance_receipt_count"] == 0
    assert value["case_summary"]["cdf_fields_complete_count"] == 5
    assert value["case_summary"]["residence_fields_complete_count"] == 5
    assert value["case_summary"]["mass_closed_count"] == 6
    assert all(row["scientific_status"] == "blocked" for row in cases)
    assert all(row["credit"] == 0 for row in cases)
    assert all(row["formal_acceptance_receipt_present"] is False for row in cases)
    assert all(row["recovery"]["checkpoint_integrity_pass"] is True for row in cases)
    short = cases[-1]
    assert short["canary_id"] == "f4_tallwall120_short_canary"
    assert short["cdf"]["fields_present"] is False
    assert short["event_window"]["gate_pass"] is False
    assert any("checkpoint" in reason for reason in short["blocking_gaps"]) is False


def test_all_33_matrix_rows_remain_individually_blocked() -> None:
    value = build_bridge(ROOT, created_at_utc="2026-09-22T00:00:00+00:00")
    rows = value["matrix_gaps"]
    assert len(rows) == 33
    assert [row["matrix_row"] for row in rows] == list(range(33))
    assert [row["axis"] for row in rows[:24]] == ["resolution_substep"] * 24
    assert [row["axis"] for row in rows[24:28]] == ["cadence"] * 4
    assert [row["axis"] for row in rows[28:]] == ["seed_density"] * 5
    assert all(row["formal_acceptance_receipt_present"] is False for row in rows)
    assert all(row["credit"] == 0 for row in rows)
    assert rows[0]["status"] == "blocked_pending_material_overlay"
    assert rows[24]["status"] == "blocked_missing_exact_cfd_source"
    assert rows[28]["status"] == "blocked_pending_seed_density_overlay"
    assert value["matrix_summary"]["material_matrix_ready"] is False
    assert value["matrix_summary"]["formal_acceptance_receipt_count"] == 0


def test_recovery_semantics_are_bound_but_not_authorized_or_credited() -> None:
    value = build_bridge(ROOT, created_at_utc="2026-09-22T00:00:00+00:00")
    recovery = value["recovery_semantics"]

    assert recovery["contract_bound"] is True
    assert recovery["frame_start"] == 0
    assert recovery["frame_end"] == 1085
    assert recovery["recovery_boundary_frame"] == 40
    assert recovery["checkpoint_every_native_frame"] is True
    assert "append-only" in recovery["generation_policy"]
    assert recovery["rerun_from_zero_after_interruption"] is False
    assert recovery["execution_authorized_now"] is False
    assert recovery["recovery_acceptance_receipt_present"] is False
    assert recovery["historical_trace"]["source_h5_reopened_by_bridge"] is False
    assert value["acceptance_gates"]["recovery_contract_bound"] is True


def test_bridge_is_repeatable_with_fixed_timestamp() -> None:
    first = build_bridge(ROOT, created_at_utc="2026-09-22T00:00:00+00:00")
    second = build_bridge(ROOT, created_at_utc="2026-09-22T00:00:00+00:00")
    assert first == second


def test_artifacts_and_hash_closure_are_versioned_without_overwriting_old_namespace() -> None:
    assert EVIDENCE.is_file()
    assert REPORT.is_file()
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert value["engineering_receipt"]["schema"] == ENGINEERING_RECEIPT_SCHEMA
    assert value["formal_acceptance_receipt"]["schema"] == FORMAL_RECEIPT_SCHEMA
    assert value["formal_acceptance_receipt"]["credit"] == 0
    assert "engineering receipt" in REPORT.read_text(encoding="utf-8")
    assert "T2_macro=false" in REPORT.read_text(encoding="utf-8")
    assert "未借用 F3 的 `0.02`" in REPORT.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="byte count changed|SHA-256 changed"):
        verify_receipt(EVIDENCE, ROOT)
    assert set(INPUTS) == set(value["input_bindings"])
    for group_name in ("input_bindings", "case_input_bindings", "checkpoint_input_bindings"):
        for name, binding in value[group_name].items():
            path = ROOT / binding["path"]
            assert path.is_file(), (group_name, name)
            if group_name == "input_bindings" and name in {"core_material", "tallwall_material_code"}:
                assert (
                    path.stat().st_size != binding["bytes"]
                    or hashlib.sha256(path.read_bytes()).hexdigest() != binding["sha256"]
                )
                continue
            assert path.stat().st_size == binding["bytes"], (group_name, name)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], (group_name, name)


def test_verify_receipt_rejects_scientific_credit_mutation(tmp_path: Path) -> None:
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    value["formal_acceptance_receipt"]["credit"] = 1
    mutated = tmp_path / "mutated.json"
    mutated.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="formal receipt credit"):
        verify_receipt(mutated, ROOT)
