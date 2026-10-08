"""Counterexamples for the conservative all-118 mechanism-bound ledger."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_omission_mechanism_bounds_v1.py"
SPEC = importlib.util.spec_from_file_location("mechanism_bounds_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import mechanism bounds module")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base_case(tmp_path: Path, *, family: str = "F2") -> tuple[dict, dict, dict, dict]:
    xml = tmp_path / "case.xml"
    xml.write_text(
        '<case><massbody value="128"/><massbody value="128"/>'
        '<massfluid value="0.015625"/></case>', encoding="utf-8"
    )
    forensic = {
        "schema": "ds02.stage2.omission-forensics.v2",
        "status": "CAUSES_RECONCILED",
        "source_provenance": {"generated_xml": {"path": str(xml), "sha256": digest(xml)}} if family == "F6" else {},
        "typed_identity": {"missing_fluid_count": 1, "missing_fluid_initial_mass_kg": 0.001},
        "excluded_particles": [{
            "zone": 0, "idp": 7, "initial_mass_kg": 0.001,
            "first_missing_frame": 2, "first_missing_bracket_s": [0.1, 0.2],
            "first_gap_previous_state": {
                "frame": 1, "time_s": 0.1, "position_m": [1.0, 2.0, 3.0],
                "velocity_m_s": [0.1, 0.2, 0.3], "density_kg_m3": 1000.0,
            },
            "last_known_frame": 1, "last_known_time_s": 0.1,
            "last_known_position_m": [1.0, 2.0, 3.0],
            "last_known_velocity_m_s": [0.1, 0.2, 0.3],
            "last_known_density_kg_m3": 1000.0,
            "native_exit_cause": "NUMERICAL_POSITION_EXCLUSION",
            "native_motive": "position", "native_motive_code": 1,
            "partvtkout_position_m": [1.2, 2.2, 3.2],
            "partvtkout_density_kg_m3": 999.0,
            "legal_outflow_proven": True,
        }],
    }
    if family == "F6":
        forensic["excluded_particles"][0]["initial_mass_kg"] = 0.015625
        forensic["typed_identity"]["missing_fluid_initial_mass_kg"] = 0.015625
    scan = {
        "physical_case_id": "TEST_CASE",
        "time_s": [0.0, 0.1, 0.2],
    }
    impact_mass = 0.015625 if family == "F6" else 0.001
    impact = {
        "family_id": family, "physical_case_id": "TEST_CASE",
        "typed_initial_fluid_mass_kg": 1.0,
        "missing_fluid_count": 1, "missing_mass_lower_bound_kg": impact_mass,
        "missing_mass_fraction_lower_bound": impact_mass,
        "mass_screen": "mass_screen_subset_below_gate",
        "native_motive_counts": {"position": 1},
        "native_exit_cause_counts": {"NUMERICAL_POSITION_EXCLUSION": 1},
        "particles": [{
            "zone": 0, "idp": 7, "type_code": 3,
            "initial_mass_kg": impact_mass, "native_motive": "position",
            "native_motive_code": 1, "native_exit_cause": "NUMERICAL_POSITION_EXCLUSION",
            "first_missing_frame": 2, "first_missing_bracket_s": [0.1, 0.2],
        }],
    }
    if family == "F6":
        impact["f6_mass_semantics"] = {"sample_floating_typed_initial_mass_kg": 256.0}
    entry = {
        "case_key": f"{family}/test-001", "family_id": family,
        "physical_case_id": "TEST_CASE", "forensic_kind": "omission-forensics.v2",
        "forensic_path": str(tmp_path / "forensic.json"),
        "scan_path": str(tmp_path / "scan.json"),
        "scan_receipt_path": str(tmp_path / "receipt.json"),
    }
    Path(entry["forensic_path"]).write_text(json.dumps(forensic), encoding="utf-8")
    Path(entry["scan_path"]).write_text(json.dumps(scan), encoding="utf-8")
    Path(entry["scan_receipt_path"]).write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    return entry, impact, forensic, scan


def test_position_endpoint_cannot_claim_spill_and_mk_weight_is_interval(tmp_path: Path):
    entry, impact, forensic, scan = base_case(tmp_path)
    result = MODULE.summarize_case(entry, impact, forensic, scan)
    assert result["native_cause"]["motive_counts"] == {"position": 1}
    assert result["region_transport"]["physical_destination"] == "UNKNOWN"
    assert result["region_transport"]["legal_outflow_or_spill"] == "UNKNOWN_NOT_PROVEN"
    assert result["region_transport"]["conditional_physical_outflow_mass_interval_kg"] == [0.0, 0.001]
    assert result["source_mk_weight"]["admissible_mass_interval_kg_for_each_unidentified_mk"] == [0.0, 0.001]
    assert result["event_censoring"]["first_missing_window_s"] == [0.1, 0.2]
    assert result["physical_fate"] == "UNKNOWN"
    assert result["dynamical_impact"] == "UNKNOWN"


def test_f6_xml_body_mass_is_separate_from_sample_mass(tmp_path: Path):
    entry, impact, forensic, scan = base_case(tmp_path, family="F6")
    result = MODULE.summarize_case(entry, impact, forensic, scan)
    semantics = result["f6_mass_semantics"]
    assert semantics["sample_floating_typed_initial_mass_kg"] == 256.0
    assert semantics["physical_rigid_body_mass_kg"] == 128.0
    assert semantics["xml_massfluid_per_particle_kg"] == 0.015625
    assert semantics["physical_rigid_body_mass_is_not_in_missing_fluid_mass"] is True


@pytest.mark.parametrize("mutation", ["identity", "missing_bracket", "wrong_mass", "wrong_motive"])
def test_incomplete_join_cannot_receive_mechanism_credit(tmp_path: Path, mutation: str):
    entry, impact, forensic, scan = base_case(tmp_path)
    if mutation == "identity":
        impact["particles"][0]["idp"] = 99
    elif mutation == "missing_bracket":
        forensic["excluded_particles"][0].pop("first_missing_bracket_s")
    elif mutation == "wrong_mass":
        impact["missing_mass_lower_bound_kg"] = 0.002
    elif mutation == "wrong_motive":
        impact["particles"][0]["native_exit_cause"] = "NUMERICAL_DENSITY_EXCLUSION"
    with pytest.raises(MODULE.MechanismBoundsError):
        MODULE.summarize_case(entry, impact, forensic, scan)


def test_repair_controls_are_plans_and_keep_physical_fate_unknown():
    controls = MODULE.repair_controls()
    assert set(controls) == {"F2", "F4", "F6"}
    assert all(value["status"] == "PLANNED_NOT_EXECUTED" for value in controls.values())
    assert "mass matching" in controls["F2"]["frozen"]
    assert "wetted wall/bottom and body geometry" in controls["F6"]["preserve"]
    assert controls["F4"]["changed_factor"].startswith("none")


def test_prepared_manifest_rejects_wrong_hash_and_h5_input(tmp_path: Path):
    source = tmp_path / "impact-v2.json"
    source.write_text("{}", encoding="utf-8")
    input_file = tmp_path / "small.json"
    input_file.write_text("small", encoding="utf-8")
    manifest = {
        "schema": MODULE.MANIFEST_SCHEMA,
        "status": "PREPARED_118_SOURCE_CLOSED_NO_H5",
        "case_count": 118,
        "family_case_counts": {"F2": 48, "F4": 22, "F6": 48},
        "input_sha256": {str(input_file): digest(input_file)},
        "source_impact_manifest": {"path": str(source), "sha256": digest(source)},
    }
    valid = tmp_path / "manifest.json"
    valid.write_text(json.dumps(manifest), encoding="utf-8")
    assert MODULE.validate_prepared_manifest(valid)[2] == source.resolve()

    wrong = copy.deepcopy(manifest)
    wrong["input_sha256"][str(input_file)] = "0" * 64
    wrong_path = tmp_path / "wrong.json"
    wrong_path.write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(MODULE.MechanismBoundsError):
        MODULE.validate_prepared_manifest(wrong_path)

    h5 = tmp_path / "trajectory.h5"
    h5.write_text("forbidden", encoding="utf-8")
    with_h5 = copy.deepcopy(manifest)
    with_h5["input_sha256"][str(h5)] = digest(h5)
    h5_path = tmp_path / "h5.json"
    h5_path.write_text(json.dumps(with_h5), encoding="utf-8")
    with pytest.raises(MODULE.MechanismBoundsError):
        MODULE.validate_prepared_manifest(h5_path)


if __name__ == "__main__":
    raise SystemExit("use pytest")
