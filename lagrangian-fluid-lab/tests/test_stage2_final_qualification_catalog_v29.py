from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_final_qualification_catalog_v29.py"
SPEC = importlib.util.spec_from_file_location("stage2_final_qualification_catalog_v29", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _current_fixture() -> tuple[list[dict], dict[tuple[str, str], tuple[int, dict]]]:
    rows = []
    for family_index in range(1, 8):
        family = f"F{family_index}"
        for offset in range(48):
            physical = f"{family}_CASE_{offset:02d}"
            rows.append({
                "family_id": family,
                "physical_case_id": physical,
                "runtime_case_alias": physical,
                "frames": 10,
                "particles": 20,
                "actual_time_window_s": [0.0, 1.0],
                "known_numeric_physical_parameters": {},
                "source_bindings": {},
            })
    return rows, {(row["family_id"], row["physical_case_id"]): (i, row) for i, row in enumerate(rows)}


def _audit_rows(current: list[dict]) -> list[dict]:
    return [
        {
            "family_id": row["family_id"],
            "physical_case_id": row["physical_case_id"],
            "trajectory": f"/provenance/{row['physical_case_id']}.h5",
            "trajectory_verified_sha256": "a" * 64,
            "scan": f"/evidence/{row['physical_case_id']}/scientific-scan.json",
            "scan_sha256": "b" * 64,
            "receipt": f"/evidence/{row['physical_case_id']}/execution-receipt.json",
            "receipt_sha256": "c" * 64,
            "scan_status": "SCANNED",
            "frames": row["frames"],
            "fluid_initial_mass_kg": 1.0,
            "fluid_initially_absent_count": 0,
            "fluid_cumulative_unique_missing": 0,
            "fluid_missing_final_count": 0,
            "field_failures": [],
            "QI_dynamics": "NOT_ASSESSED",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
            "exact_CURRENT_path_and_declared_sha_match": True,
        }
        for row in current
    ]


def test_scientific_audit_requires_exact_current_key_set():
    current, by_key = _current_fixture()
    rows = _audit_rows(current)
    audit = {
        "schema": MODULE.AUDIT_SCHEMA,
        "distinct_completed_cases": 336,
        "by_family": {f"F{i}": 48 for i in range(1, 8)},
        "verified_cases": rows,
        "current_catalog": {"sha256": "d" * 64},
    }
    validated = MODULE._validate_scientific_audit(Path("/tmp/audit.json"), audit, by_key, "d" * 64)
    assert len(validated) == 336
    rows[-1]["physical_case_id"] = "F7_WRONG_CASE"
    with pytest.raises(MODULE.CatalogError, match="identity is not exact CURRENT336"):
        MODULE._validate_scientific_audit(Path("/tmp/audit-wrong.json"), audit, by_key, "d" * 64)


def test_native_summary_keeps_mass_as_lower_bound_and_time_as_bracket_only():
    impact = {
        "case_key": "F2/F2_CASE_00",
        "family_id": "F2",
        "physical_case_id": "F2_CASE_00",
        "native_numerical_cause": {"motive": "position", "native_count": 2, "exit_cause_counts": {"NUMERICAL_POSITION_EXCLUSION": 2}},
        "mass_impact": {
            "initial_fluid_mass_denominator_kg": 10.0,
            "source_visible_missing_mass_lower_bound_kg": 0.2,
            "source_visible_missing_fraction_lower_bound": 0.02,
            "screen": "mass_screen_subset_above_gate",
            "screen_gate_fraction": 0.003,
            "source_mk_partition": {"per_mk_fraction": "UNKNOWN"},
        },
        "censoring": {"first_missing_window_s": [0.1, 0.2]},
        "source_closure": {"status": "FULL_NATIVE_SOURCE_CLOSED"},
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
    }
    mechanism = {
        "case_key": impact["case_key"],
        "native_gate": {"motive": "position", "native_count": 2, "runparts_totals": {"NpOut": 2}},
        "particle_observations": [{"idp": 1}, {"idp": 2}],
        "saved_record_impacts": [{"part": 1}],
        "source_closure": {"status": "EXACT_NATIVE_SOURCE_CLOSED"},
    }
    summary = MODULE._native_summary(impact, mechanism)
    assert summary["source_visible_mass"]["missing_source_visible_fraction_lower_bound"] == 0.02
    assert summary["saved_censoring"]["first_missing_window_s"] == [0.1, 0.2]
    assert summary["saved_censoring"]["event_time_semantics"].endswith("UNKNOWN")
    assert summary["physical_fate"] == "UNKNOWN"


def test_native_summary_rejects_motive_count_mismatch():
    impact = {
        "case_key": "F4/F4_CASE_00", "native_numerical_cause": {"motive": "density", "native_count": 1},
        "mass_impact": {}, "source_closure": {"status": "FULL_NATIVE_SOURCE_CLOSED"},
    }
    mechanism = {"native_gate": {"motive": "position", "native_count": 1}}
    with pytest.raises(MODULE.CatalogError, match="native cause/mechanism mismatch"):
        MODULE._native_summary(impact, mechanism)


def test_case_record_keeps_non_native_qualification_explicitly_unknown():
    current = {"family_id": "F1", "physical_case_id": "F1_CASE_00", "runtime_case_alias": "F1_CASE_00", "frames": 10, "particles": 20, "actual_time_window_s": [0.0, 1.0], "known_numeric_physical_parameters": {}, "source_bindings": {}}
    audit = {"family_id": "F1", "physical_case_id": "F1_CASE_00", "scan_status": "SCANNED", "frames": 10, "fluid_initial_mass_kg": 1.0, "fluid_initially_absent_count": 0, "fluid_cumulative_unique_missing": 0, "fluid_missing_final_count": 0, "field_failures": []}
    record = MODULE._case_record(0, current, audit, None, None, None, None)
    assert record["native_omission"] is None
    assert record["qualification_dimensions"]["error_qualification"]["QN"] == "UNKNOWN"
    assert record["qualification_dimensions"]["censoring"]["status"] == "NO_NATIVE_118_CENSOR_RECORD_FOR_THIS_CASE"
