"""Manufactured gate/fate and dimensional-impact counterexamples."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_omission_mechanism_probe_v2.py"
SPEC = importlib.util.spec_from_file_location("mechanism_probe_v2", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import mechanism probe")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def runparts(part: int, time_s: float, *, motive: str) -> dict:
    counts = {"NpOut": 1, "NpOutPos": int(motive == "position"),
              "NpOutRho": int(motive == "density"), "NpOutMov": 0}
    row = {"part": part, "time_s": time_s, "previous_time_s": time_s - 0.1,
           "saved_record_bracket_s": [time_s - 0.1, time_s], **counts}
    return {"rows": [row], "by_part": {part: row}, "totals": counts}


def base_case(tmp_path: Path, *, family: str = "F2", motive: str = "position") -> tuple[dict, dict, dict, dict, dict, dict]:
    physical = "F2_FIXTURE" if family == "F2" else "F4_FIXTURE"
    idp = 7 if family == "F2" else 8
    endpoint = [1.0001, 0.5, 0.5] if family == "F2" else [0.5, 0.5, 0.5]
    endpoint_density = 1000.0 if family == "F2" else 699.0
    motive_code = 1 if motive == "position" else 2
    case = {
        "case_key": f"{family}/fixture", "family_id": family, "physical_case_id": physical,
        "native_cause": {"motive_counts": {motive: 1}, "exit_cause_counts": {f"NUMERICAL_{motive.upper()}_EXCLUSION": 1}},
        "mass_visibility": {
            "initial_fluid_mass_denominator_kg": 1.0,
            "missing_source_visible_mass_lower_bound_kg": 0.001,
            "missing_source_visible_fraction_lower_bound": 0.001,
            "screen": "mass_screen_subset_below_gate", "screen_gate_fraction": MODULE.MASS_GATE,
        },
        "particles": [{"idp": idp, "initial_mass_kg": 0.001}],
    }
    row = {
        "zone": 0, "idp": idp, "type_code": 3, "initial_mass_kg": 0.001,
        "first_missing_frame": 1, "first_missing_bracket_s": [0.1, 0.2],
        "first_gap_previous_state": {"frame": 0, "time_s": 0.1, "position_m": [0.5, 0.5, 0.5],
                                      "velocity_m_s": [0.0, 0.0, 0.0], "density_kg_m3": 1000.0},
        "native_exit_cause": f"NUMERICAL_{motive.upper()}_EXCLUSION", "native_motive": motive,
        "native_motive_code": motive_code, "partvtkout_position_m": endpoint,
        "partvtkout_density_kg_m3": endpoint_density,
    }
    forensic = {"family_id": family, "physical_case_id": physical, "excluded_particles": [row]}
    scan = {"physical_case_id": physical, "time_s": [0.0, 0.1, 0.2]}
    native = {"rows": [{"idp": idp, "part": 1, "motive_code": motive_code,
                         "position_m": endpoint, "velocity_m_s": [2.0, 0.0, 0.0],
                         "density_kg_m3": endpoint_density}],
              "by_id": {idp: {"idp": idp, "part": 1, "motive_code": motive_code,
                               "position_m": endpoint, "velocity_m_s": [2.0, 0.0, 0.0],
                               "density_kg_m3": endpoint_density}}}
    bounds = {"source": {"path": "fixture-Run.out", "sha256": "fixture", "bytes": 1},
              "maprealpos_final_m": {"low": [0.0, 0.0, 0.0], "high": [1.0, 1.0, 1.0], "predicate": "printed"},
              "rhop_out_kg_m3": {"enabled": True, "min": 700.0, "max": 1300.0, "predicate": "strict"}}
    return case, forensic, scan, runparts(1, 0.2, motive=motive), native, bounds


def test_position_gate_is_separate_from_legal_flux_and_units_are_dimensional(tmp_path: Path):
    case, forensic, scan, parts, native, bounds = base_case(tmp_path)
    result = MODULE.summarize_case(case, forensic, scan, parts, native, bounds)
    assert result["native_gate"]["motive"] == "position"
    assert result["printed_final_bounds_observation"]["previous_state_position_classes"] == {"inside": 1}
    assert result["printed_final_bounds_observation"]["native_endpoint_position_classes"] == {"x_high": 1}
    assert result["legal_outflow_or_spill"] == "UNKNOWN_NOT_PROVEN"
    impact = result["saved_record_impacts"][0]
    assert impact["momentum_kg_m_s"] == [0.002, 0.0, 0.0]
    assert impact["kinetic_energy_j"] == pytest.approx(0.002)
    assert impact["saved_record_bracket_s"] == [0.1, 0.2]
    assert result["physical_fate"] == "UNKNOWN"


def test_density_gate_can_be_identified_without_assigning_fate(tmp_path: Path):
    case, forensic, scan, parts, native, bounds = base_case(tmp_path, family="F4", motive="density")
    result = MODULE.summarize_case(case, forensic, scan, parts, native, bounds)
    assert result["native_gate"]["motive"] == "density"
    assert result["printed_final_bounds_observation"]["native_endpoint_position_classes"] == {"inside": 1}
    assert result["density_gate_observation"]["counts"] == {"below_min": 1}
    assert result["physical_fate"] == "UNKNOWN"
    assert result["dynamical_impact"] == "UNKNOWN"


@pytest.mark.parametrize("mutation", ["identity", "motive", "part"])
def test_wrong_native_join_cannot_receive_gate_credit(tmp_path: Path, mutation: str):
    case, forensic, scan, parts, native, bounds = base_case(tmp_path)
    if mutation == "identity":
        native["by_id"].clear()
    elif mutation == "motive":
        native["by_id"][7]["motive_code"] = 2
    else:
        native["by_id"][7]["part"] = 2
    with pytest.raises(MODULE.MechanismProbeError):
        MODULE.summarize_case(case, forensic, scan, parts, native, bounds)


def test_control_plan_preserves_physical_unknown(tmp_path: Path):
    f2 = base_case(tmp_path)[0:6]
    f4 = base_case(tmp_path, family="F4", motive="density")[0:6]
    f2_summary = MODULE.summarize_case(*f2)
    f4_summary = MODULE.summarize_case(*f4)
    plan = MODULE.control_plan([f2_summary, f4_summary])
    assert plan["status"] == "PLANNED_NOT_EXECUTED"
    assert any("wetted geometry" in item for item in plan["F2"]["preserve"])
    assert "do not widen thresholds" in plan["F4"]["forbidden"]
    assert plan["physical_fate_evidence_missing"]


def test_partial_native_reconciliation_preserves_unknown_source_scope(tmp_path: Path):
    physical = "F2_S1_FIXTURE"
    case = {
        "case_key": "F2/scan-F2-S1-001", "family_id": "F2", "physical_case_id": physical,
        "native_cause": {"motive_counts": {"position": 1}, "exit_cause_counts": {"NUMERICAL_POSITION_EXCLUSION": 1}},
        "mass_visibility": {"initial_fluid_mass_denominator_kg": 1.0, "missing_source_visible_mass_lower_bound_kg": 0.001,
                            "missing_source_visible_fraction_lower_bound": 0.001, "screen": "mass_screen_subset_below_gate",
                            "screen_gate_fraction": MODULE.MASS_GATE},
        "particles": [{"idp": 17, "initial_mass_kg": 0.001}],
    }
    forensic = {
        "schema": "ds02.stage2.native-exclusion-reconciliation.v1", "status": "CAUSES_RECONCILED",
        "family_id": "F2", "physical_case_id": physical, "joined_count": 1,
        "native_motive_counts": {"position": 1, "density": 0, "movement": 0},
        "runparts_totals": {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0},
        "missing_fluid_ids": [{"idp": 17, "zone": 0, "type_code": 3, "initial_mass_kg": 0.001,
            "first_missing_bracket_s": [1.0, 1.1],
            "first_gap_previous_state": {"position_m": [0.0, 0.0, 0.0]},
            "native_record": {"idp": 17, "motive_code": 1, "motive": "position", "position_m": [-1.0, 0.0, 0.0], "density_kg_m3": 1000.0}}],
    }
    scan = {"physical_case_id": physical}
    forensic_path = tmp_path / "fixture-reconciliation.json"
    scan_path = tmp_path / "fixture-scan.json"
    receipt_path = tmp_path / "fixture-receipt.json"
    forensic_path.write_text("{}")
    scan_path.write_text("{}")
    receipt_path.write_text("{}")
    result, _ = MODULE.summarize_partial_reconciliation(case, forensic_path, forensic,
                                                          scan_path, scan, receipt_path)
    assert result["source_closure"]["status"] == "PARTIAL_NATIVE_RECONCILIATION_ONLY"
    assert result["printed_final_bounds_observation"]["status"] == "UNKNOWN_SOURCE_MISSING"
    assert result["particle_observations"][0]["saved_record_time_s"] == "UNKNOWN_SOURCE_MISSING"
    assert result["particle_observations"][0]["momentum_kg_m_s"] == "UNKNOWN_ENDPOINT_VELOCITY"
    assert result["physical_fate"] == "UNKNOWN"


def test_all118_source_selection_requires_exact_family_membership():
    report = {"schema": MODULE.SOURCE_REPORT_SCHEMA, "status": "MECHANISM_BOUNDS_AUDITED_TYPED_NATIVE_SOURCE_CLOSED", "cases": []}
    with pytest.raises(MODULE.MechanismProbeError):
        MODULE.source_cases(report)


if __name__ == "__main__":
    raise SystemExit("use pytest")
