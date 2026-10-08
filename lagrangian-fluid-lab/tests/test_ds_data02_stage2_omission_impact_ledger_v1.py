"""Independent impact-ledger validation and claim-boundary tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_stage2_omission_impact_ledger_v1.py"
SPEC = importlib.util.spec_from_file_location("impact_ledger_v1", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import impact ledger")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict) -> dict:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def partial_fixture(tmp_path: Path):
    physical = "F2_S1_FIXTURE"
    forensic = {
        "schema": "ds02.stage2.native-exclusion-reconciliation.v1", "status": "CAUSES_RECONCILED",
        "family_id": "F2", "physical_case_id": physical, "joined_count": 1,
        "native_motive_counts": {"position": 1, "density": 0, "movement": 0},
        "missing_fluid_ids": [{"idp": 17, "zone": 0, "type_code": 3, "initial_mass_kg": 0.001,
            "first_missing_bracket_s": [1.0, 1.1],
            "first_gap_previous_state": {"position_m": [0.0, 0.0, 0.0]},
            "native_record": {"idp": 17, "motive_code": 1, "motive": "position", "position_m": [-1.0, 0.0, 0.0], "density_kg_m3": 1000.0}}],
    }
    forensic_path = tmp_path / "forensic.json"
    scan_path = tmp_path / "scan.json"
    receipt_path = tmp_path / "scan-receipt.json"
    forensic_binding = write_json(forensic_path, forensic)
    scan_binding = write_json(scan_path, {"physical_case_id": physical})
    receipt_binding = write_json(receipt_path, {"status": "completed"})
    source = {
        "case_key": "F2/scan-F2-S1-001", "family_id": "F2", "physical_case_id": physical,
        "native_cause": {"motive_counts": {"position": 1}, "exit_cause_counts": {"NUMERICAL_POSITION_EXCLUSION": 1}},
        "mass_visibility": {"initial_fluid_mass_denominator_kg": 1.0, "missing_source_visible_mass_lower_bound_kg": 0.001,
                            "missing_source_visible_fraction_lower_bound": 0.001, "screen": "mass_screen_subset_below_gate",
                            "screen_gate_fraction": MODULE.MASS_GATE},
        "particles": [{"idp": 17, "initial_mass_kg": 0.001}],
        "event_censoring": {"first_missing_window_s": [1.0, 1.1], "per_particle_first_missing_windows": [{"idp": 17, "window_s": [1.0, 1.1]}],
                             "physical_event_time_s": "UNKNOWN", "post_gap_state": "UNOBSERVED"},
        "source_mk_weight": {"status": "UNKNOWN"},
        "source_bindings": {"forensic": forensic_binding, "scan": scan_binding, "scan_receipt": receipt_binding},
    }
    probe = {
        "case_key": source["case_key"], "family_id": "F2", "physical_case_id": physical,
        "source_closure": {"status": "PARTIAL_NATIVE_RECONCILIATION_ONLY", "missing_inputs": ["Run.out", "RunPARTs", "PartVTKOut receipt"]},
        "native_gate": {"motive": "position", "native_count": 1, "cause": source["native_cause"]},
        "mass_visibility": source["mass_visibility"],
        "particle_observations": [{"idp": 17}],
        "source_files": {"forensic": forensic_binding, "scan": scan_binding, "scan_receipt": receipt_binding},
    }
    return source, probe, forensic_path


def test_partial_case_is_unknown_and_requires_repair(tmp_path: Path):
    source, probe, _ = partial_fixture(tmp_path)
    record = MODULE.validate_case(source, probe, "source-sha")
    assert record["source_closure"]["status"] == "PARTIAL_NATIVE_RECONCILIATION_ONLY"
    assert record["conversion_omission"]["status"] == "UNKNOWN_SOURCE_MISSING"
    assert record["next_validation_control"]["status"] == "REQUIRED_BEFORE_FULL_SOURCE_CREDIT"
    assert record["mass_impact"]["source_visible_missing_mass_lower_bound_kg"] == pytest.approx(0.001)
    assert record["physical_fate"] == "UNKNOWN"
    assert record["legal_outflow_or_spill"] == "UNKNOWN_NOT_PROVEN"
    assert record["dynamical_impact"] == "UNKNOWN"


def test_full_conversion_metadata_match_does_not_grant_converter_or_fate_credit(tmp_path: Path):
    source, probe, forensic_path = partial_fixture(tmp_path)
    physical = source["physical_case_id"]
    conversion_path = tmp_path / "conversion.json"
    conversion = {"conversion_status": "completed", "output_hdf5": str(tmp_path / "trajectory.h5"),
                  "output_sha256": "trajectory-sha", "partvtk_validation": {"all_passed": True},
                  "lifecycle": {"missing_semantics": "native solver output omission"}}
    conversion_binding = write_json(conversion_path, conversion)
    forensic = {"schema": "ds-data-02.omission-forensics.v1", "family_id": "F2", "physical_case_id": physical,
                "trajectory": {"path": conversion["output_hdf5"], "sha256": conversion["output_sha256"], "conversion_report": conversion_binding}}
    forensic_binding = write_json(forensic_path, forensic)
    source["source_bindings"]["forensic"] = forensic_binding
    probe["source_closure"] = {"status": "FULL_PROBE_SOURCE_CLOSED"}
    probe["source_files"] = {"forensic": forensic_binding, "scan": probe["source_files"]["scan"],
                             "scan_receipt": probe["source_files"]["scan_receipt"], "conversion_report": conversion_binding}
    record = MODULE.validate_case(source, probe, "source-sha")
    assert record["conversion_omission"]["status"] == "COMPLETED_OUTPUT_PATH_SHA_METADATA_MATCHED"
    assert record["conversion_omission"]["converter_source_closure"] == "UNKNOWN_NOT_BOUND_BY_CONVERSION_RECEIPT"
    assert record["physical_fate"] == "UNKNOWN"


def test_conversion_path_mismatch_is_rejected(tmp_path: Path):
    source, probe, forensic_path = partial_fixture(tmp_path)
    conversion_path = tmp_path / "conversion.json"
    conversion = {"conversion_status": "completed", "output_hdf5": str(tmp_path / "wrong.h5"), "output_sha256": "wrong"}
    conversion_binding = write_json(conversion_path, conversion)
    forensic = {"schema": "ds-data-02.omission-forensics.v1", "family_id": "F2", "physical_case_id": source["physical_case_id"],
                "trajectory": {"path": str(tmp_path / "expected.h5"), "sha256": "expected", "conversion_report": conversion_binding}}
    forensic_binding = write_json(forensic_path, forensic)
    source["source_bindings"]["forensic"] = forensic_binding
    probe["source_closure"] = {"status": "FULL_PROBE_SOURCE_CLOSED"}
    probe["source_files"] = {"forensic": forensic_binding, "scan": probe["source_files"]["scan"],
                             "scan_receipt": probe["source_files"]["scan_receipt"], "conversion_report": conversion_binding}
    with pytest.raises(MODULE.LedgerError):
        MODULE.validate_case(source, probe, "source-sha")


def test_f6_control_keeps_body_and_sample_mass_separate():
    control = MODULE.FAMILY_CONTROLS["F6"]
    assert "sample/body mass separation" in control["preserve"]
    assert control["factor"] == "simulation-domain numerical bounds only, wall/body condition fixed"

