"""Source-bounded tests for the actual family-card evidence overlay."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_cards_v26_actual_overlay.py"


def _load():
    spec = importlib.util.spec_from_file_location("family_overlay_v26_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    module = _load()
    proof_dir = tmp_path / "pilot-proofs"
    proof_refs = {}
    for root_id, family, case_id in module.PILOTS if hasattr(module, "PILOTS") else (
        (346, "F1", "F1_CASE"), (347, "F2", "F2_CASE"), (348, "F3", "F3_CASE"),
        (349, "F4", "F4_CASE"), (350, "F5", "F5_CASE"), (351, "F6", "F6_CASE"), (352, "F7", "F7_CASE"),
    ):
        path = proof_dir / f"proof-{root_id}.json"
        _write(path, {"family": family, "case": case_id})
        proof_refs[family] = {
            "physical_case_id": case_id,
            "root_proof": {
                "path": str(path),
                "sha256": _sha(path),
                "case_verification": {"family_id": family},
            },
        }
    pilot_report = tmp_path / "pilot-report.json"
    _write(pilot_report, {
        "schema": module.REPORT_SCHEMA,
        "status": "ACTUAL_FIELD_PILOTS_METADATA_VERIFIED_NO_SCIENTIFIC_Q",
        "pilot_count": 7,
        "source_index": {"path": str(tmp_path / "source-index.json"), "sha256": "a" * 64},
        "claim_boundary": {"production_scientific_Q_credit": 0, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "family_card_evidence": proof_refs,
    })
    source = tmp_path / "source-index.json"
    _write(source, {})
    cause = tmp_path / "cause.json"
    _write(cause, {
        "schema": "ds02.stage2.original118-native-cause-actual-overlay.v1",
        "status": "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS",
        "physical_case_count": 118,
        "native_cause_bound_per_fluid_id_cases": 111,
        "cause_not_located_after_completed_scan_cases": 7,
        "actual_typed_native_saved_frame_join_physical_cases": 64,
        "root_H5_native_JSONL_content_read": False,
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    })
    mass = tmp_path / "mass.json"
    _write(mass, {
        "schema": "ds02.stage2.root-actual-verification.v1",
        "status": "VERIFIED_ACTUAL_ROOT313_NATIVE_TYPED_MASS_IMPACT_REPORTED_CASE_TERMINALS_NO_PHYSICAL_Q",
        "case_verifications": [{"physical_case_id": f"F6_CASE_{i}"} for i in range(17)],
        "verified_counts": {"cases": 17, "completed": 17, "failed": 0},
        "new_native_cause_credit": 0, "new_native_join_credit": 0, "scientific_Q_credit": 0,
        "H5_BI4_read_by_root": False, "root_deferred_payload_content_read": False,
        "parent_reservation_released": True, "outer_unit_result": "success", "guarded_receipt_status": "completed",
        "scientific_mass_scope": "selected typed fluid rows", "physical_fate_flux_dynamics": "UNKNOWN",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    })
    geometry = tmp_path / "geometry.json"
    _write(geometry, {
        "schema": "ds02.stage2.root-actual-verification.v1",
        "status": "VERIFIED_ACTUAL_ROOT316_FOUR_SENTINEL_VTK_GEOMETRY_SUPPORT_DIAGNOSTIC_NO_OWNER_Q",
        "case_verifications": [{"sentinel_id": x} for x in ("F2-S2", "F4-S2", "F5-S2", "F7-S1")],
        "continuous_owner_credit": 0, "physical_penetration_credit": 0, "scientific_Q_credit": 0,
        "H5_BI4_read_by_root": False, "root_deferred_payload_content_read": False,
        "parent_reservation_released": True, "outer_unit_result": "success", "guarded_receipt_status": "completed",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    })
    failure = tmp_path / "failure.json"
    _write(failure, {
        "schema": "ds02.stage2.root353-failed-native-scalar-metadata-closure.v1",
        "status": "VERIFIED_FAILED_PARENT_FULL_CPU_NATIVE_PRODUCER_PRESERVED_NO_CHAIN_CREDIT",
        "scientific_Q_credit": 0, "reservation_released": True, "repeat_cpu_fee_idempotent": True,
        "unit_cgroup_empty": True, "root_payload_content_read": False, "failure": "child_failed",
        "chain_credit": 0, "preserved_successful_producer_scope": "diagnostic only",
    })
    return module, pilot_report, cause, mass, geometry, failure


def test_builds_seven_cards_without_promoting_shared_scope(tmp_path: Path) -> None:
    module, pilot, cause, mass, geometry, failure = _fixture(tmp_path)
    result = module.build(
        pilot_report=pilot, native_causes=cause, mass_proof=mass,
        geometry_proof=geometry, failure_proof=failure, output_dir=tmp_path / "overlay",
    )
    assert result["card_count"] == 7
    assert set(result["family_cards"]) == set(module.FAMILIES)
    cards = json.loads((tmp_path / "overlay/F6-card.json").read_text())
    assert cards["scoped_native_mass_rows"] == sorted(f"F6_CASE_{i}" for i in range(17))
    assert cards["shared_native_cause_scope"]["attached_to_this_card"] is False
    assert cards["claim_boundary"]["production_scientific_Q_credit"] == 0


def test_rejects_promoted_mass_or_changed_native_scope(tmp_path: Path) -> None:
    module, pilot, cause, mass, geometry, failure = _fixture(tmp_path)
    value = json.loads(mass.read_text())
    value["scientific_Q_credit"] = 1
    _write(mass, value)
    with pytest.raises(module.FamilyOverlayError, match="carries scientific credit"):
        module.build(
            pilot_report=pilot, native_causes=cause, mass_proof=mass,
            geometry_proof=geometry, failure_proof=failure, output_dir=tmp_path / "overlay",
        )


def test_rejects_wrong_geometry_sentinel_set(tmp_path: Path) -> None:
    module, pilot, cause, mass, geometry, failure = _fixture(tmp_path)
    value = json.loads(geometry.read_text())
    value["case_verifications"][0]["sentinel_id"] = "F1-S1"
    _write(geometry, value)
    with pytest.raises(module.FamilyOverlayError, match="sentinel set differs"):
        module.build(
            pilot_report=pilot, native_causes=cause, mass_proof=mass,
            geometry_proof=geometry, failure_proof=failure, output_dir=tmp_path / "overlay",
        )
