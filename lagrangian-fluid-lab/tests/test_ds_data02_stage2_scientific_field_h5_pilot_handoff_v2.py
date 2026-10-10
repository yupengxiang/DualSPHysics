"""Bounded tests for the actual seven-pilot handoff aggregator."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_scientific_field_h5_pilot_handoff_v2.py"


def _load():
    spec = importlib.util.spec_from_file_location("pilot_handoff_v2_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path):
    module = _load()
    handoffs = tmp_path / "handoffs"
    proofs = tmp_path / "proofs"
    source_path = tmp_path / "pilot-index.json"
    source = {
        "schema": module.SOURCE_INDEX_SCHEMA,
        "pilot_count": 7,
        "families": [family for _, family, _ in module.PILOTS],
        "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
        "read_policy": {
            "metadata_only": True,
            "launch_performed": False,
            "solver_started": False,
            "trajectory_h5_opened": False,
            "trajectory_h5_hashed": False,
            "bi4_opened": False,
        },
    }
    _write(source_path, source)
    source_sha = _sha(source_path)
    proof_refs = []
    for root_id, family, case_id in module.PILOTS:
        proof_path = proofs / f"SCIENTIFIC_FIELD_H5_ACTUAL_ROOT_VERIFICATION_{root_id}.json"
        proof = {
            "schema": module.ROOT_PROOF_SCHEMA,
            "status": "VERIFIED_ACTUAL_PRODUCTION_H5_FIELD_SCAN_METADATA_CLOSURE_NO_PHYSICAL_Q",
            "request": f"/tmp/request-{root_id}.json",
            "request_sha256": f"{root_id:064x}"[-64:],
            "receipt": f"/tmp/receipt-{root_id}.json",
            "receipt_sha256": f"{root_id + 1:064x}"[-64:],
            "report_sha256": f"{root_id + 2:064x}"[-64:],
            "manifest_sha256": f"{root_id + 3:064x}"[-64:],
            "independent_verification_sha256": f"{root_id + 4:064x}"[-64:],
            "systemd_evidence_sha256": f"{root_id + 5:064x}"[-64:],
            "terminal_cpu_reconciliation_sha256": f"{root_id + 6:064x}"[-64:],
            "parent_actual_prepost_content_hashes_equal": True,
            "parent_reservation_released": True,
            "H5_BI4_read_by_root": False,
            "root_h5_payload_content_read": False,
            "repeat_fee_idempotent": True,
            "scientific_Q_credit": 0,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "units_material_physical_authority": "UNKNOWN",
            "guarded_receipt_status": "completed",
            "outer_unit_result": "success",
            "actual_cpu_core_seconds": float(root_id),
            "full_systemd_cpu_seconds": float(root_id) + 0.1,
            "actual_cpu_delta_seconds": 0.1,
            "actual_tree_bytes": 1000 + root_id,
            "source_index": {"path": str(source_path), "sha256": source_sha},
            "case_verifications": [{
                "active_finite_status": "ALL_ACTIVE_REQUIRED_FIELDS_FINITE",
                "family_id": family,
                "initial_mass_status": "PRESENT_FINITE_POSITIVE",
                "missing_fields": [],
                "physical_case_id": case_id,
                "physical_ranges_diagnostic": True,
                "status": "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT",
                "unit_comparison": "DECLARED_MATCHES_PRODUCER_PROTOCOL",
            }],
        }
        _write(proof_path, proof)
        proof_refs.append({"path": str(proof_path), "sha256": _sha(proof_path)})

        handoff = {
            "schema": module.HANDOFF_SCHEMA,
            "actual_pilot_count": len(proof_refs),
            "actual_proofs": list(proof_refs),
            "full_cpu_seconds": float(root_id),
            "goal_complete": False,
            "goal_status": "ACTIVE_FULL_SEVEN_ITEMS",
            "production_scientific_Q_credit": 0,
            "selected_case_id": case_id,
            "source_index": {"path": str(source_path), "sha256": source_sha},
        }
        _write(handoffs / f"ROOT{root_id}_ACTUAL_SCIENTIFIC_FIELD_H5_PILOT_HANDOFF_V1.json", handoff)
    return module, handoffs, source_path, source_sha


def test_aggregates_complete_cumulative_handoffs(tmp_path: Path) -> None:
    module, handoffs, source_path, source_sha = _fixture(tmp_path)
    output = tmp_path / "pilot-report.json"
    result = module.aggregate(
        handoffs,
        output,
        expected_source_index=source_path,
        expected_source_sha256=source_sha,
    )
    assert result["status"] == module.REPORT_STATUS
    assert result["pilot_count"] == 7
    assert set(result["family_card_evidence"]) == set("F1 F2 F3 F4 F5 F6 F7".split())
    assert result["claim_boundary"]["production_scientific_Q_credit"] == 0
    assert result["claim_boundary"]["portable_replay_verified"] is False
    assert json.loads(output.read_text(encoding="utf-8"))["aggregate_terminal"]["all_outer_units_success"] is True


def test_rejects_changed_root_proof_bytes(tmp_path: Path) -> None:
    module, handoffs, source_path, source_sha = _fixture(tmp_path)
    proof_path = tmp_path / "proofs/SCIENTIFIC_FIELD_H5_ACTUAL_ROOT_VERIFICATION_349.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["root_h5_payload_content_read"] = True
    _write(proof_path, proof)
    with pytest.raises(module.PilotHandoffV2Error, match="proof SHA differs"):
        module.aggregate(handoffs, tmp_path / "report.json", expected_source_index=source_path, expected_source_sha256=source_sha)


def test_rejects_historical_alias_case_or_source_drift(tmp_path: Path) -> None:
    module, handoffs, source_path, source_sha = _fixture(tmp_path)
    handoff_path = handoffs / "ROOT352_ACTUAL_SCIENTIFIC_FIELD_H5_PILOT_HANDOFF_V1.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["selected_case_id"] = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
    _write(handoff_path, handoff)
    with pytest.raises(module.PilotHandoffV2Error, match="selected case differs"):
        module.aggregate(handoffs, tmp_path / "report.json", expected_source_index=source_path, expected_source_sha256=source_sha)
