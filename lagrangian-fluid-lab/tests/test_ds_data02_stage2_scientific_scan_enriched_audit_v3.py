from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_scientific_scan_enriched_audit_v3.py"
spec = importlib.util.spec_from_file_location("scientific_scan_enriched_audit_v3", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _case_fixture(tmp_path: Path) -> tuple[dict, dict, Path, dict, Path, dict, Path]:
    key = "F1/CASE"
    current_path = tmp_path / "CURRENT336.json"
    current = {"current_index": 0, "family_id": "F1", "physical_case_id": "CASE", "_current_path": str(current_path)}
    current_path.write_text(json.dumps({"schema": MODULE.CURRENT_SCHEMA, "cases": [current]}), encoding="utf-8")
    frames = 2
    ledgers = {role: {"active_count": [2, 2], "active_mass_kg": [1.0, 1.0]} for role in MODULE.LEDGER_ROLES}
    scan = {"schema": MODULE.SCAN_SCHEMA, "trajectory": "/source/trajectory.h5", "source_bytes": 123, "source_mtime_ns": 456, "full_saved_timeline_scanned": True, "frames": frames, "particles": 8, "time_s": [0.0, 0.1], "metadata": {"identity_key": "(Zone,Idp)", "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)", "units": {"density": "kg/m^3", "mass": "kg", "position": "m", "pressure": "Pa", "time": "s", "velocity": "m/s"}}, "type_ledgers": ledgers, "missing_id_records": [{"frame": 1}], "macros": [{"active_fluid_com_m": [0.0, 0.0, 0.0], "active_fluid_kinetic_energy_J": 0.0, "active_fluid_mass_kg": 1.0, "active_fluid_mean_velocity_m_s": [0.0, 0.0, 0.0], "time_s": 0.0}, {"active_fluid_com_m": [0.0, 0.0, 0.0], "active_fluid_kinetic_energy_J": 1.0, "active_fluid_mass_kg": 1.0, "active_fluid_mean_velocity_m_s": [1.0, 0.0, 0.0], "time_s": 0.1}], "failures": [], "scan_status": "SCANNED", "raw_native_alignment": "NOT_ASSESSED", "QI_dynamics": "NOT_ASSESSED", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED", "input_hash_verification": "See execution receipt", "wall_seconds": 0.1, "peak_rss_kib": 1, "family_id": "F1", "physical_case_id": "CASE"}
    scan_path = _write(tmp_path / "scan.json", scan)
    request = {"attempt_id": "ATT", "command": ["python", "scan.py", "--case-id", "CASE"]}
    receipt_path = _write(tmp_path / "execution-receipt.json", {"schema": MODULE.RECEIPT_SCHEMA, "status": "completed", "returncode": 0, "request": request, "input_hashes_after_run": {str(current_path): MODULE.CURRENT_SHA256}, "finished_at_utc": "2026-10-09T00:00:00+00:00", "output_root": str(tmp_path)})
    scientific_projection = {k: v for k, v in scan.items() if k not in {"family_id", "physical_case_id", "trajectory", "source_bytes", "source_mtime_ns", "time_s", "raw_native_alignment", "QI_dynamics", "QN", "QE", "input_hash_verification", "wall_seconds", "peak_rss_kib"}}
    card = {"schema": MODULE.DETAIL_CARD_SCHEMA, "case_key": key, "current_index": 0, "scan_provenance": {"path": str(scan_path), "observed_sha256": _sha(scan_path)}, "receipt_provenance": {"path": str(receipt_path), "observed_sha256": _sha(receipt_path)}, "claim_boundary": {"units_identity_time_lifecycle": "observed JSON fields"}, "scientific_scan": scientific_projection}
    card_path = _write(tmp_path / "detail.json", card)
    v29 = {"current": {"source_role": "native_initial_mk"}, "scientific_audit": {"scan_provenance": {"path": str(scan_path), "declared_sha256": _sha(scan_path)}, "receipt_provenance": {"path": str(receipt_path), "declared_sha256": _sha(receipt_path)}}}
    return current, v29, card_path, scan, scan_path, card, receipt_path


def test_case_audit_exposes_typed_saved_metadata_without_per_id_lifecycle_credit(tmp_path: Path) -> None:
    current, v29, card_path, scan, scan_path, card, receipt_path = _case_fixture(tmp_path)
    result = MODULE._case_audit("F1/CASE", current, v29, card_path, MODULE._ref(card_path, "detail"), scan_path, MODULE._ref(scan_path, "scan"), receipt_path, MODULE._ref(receipt_path, "receipt"), str(current["_current_path"]), MODULE.CURRENT_SHA256)
    observed = result["observed_fields"]
    assert observed["typed_ledgers"]["fluid"]["active_mass_kg_last"] == 1.0
    assert observed["macro_time_strictly_increasing"] is True
    assert observed["missing_id_record_count"] == 1
    assert observed["per_id_lifecycle"] == "NOT_EXPOSED_AS_PER_ID_LIFECYCLE"
    assert result["scientific_qualification"]["QI"] == "UNKNOWN"
    assert result["source_closure"]["status"] == "EXACT_CURRENT_AND_SCAN_RECEIPT_JOIN"


def test_empty_failure_list_is_observed_only_and_nonempty_is_preserved(tmp_path: Path) -> None:
    current, v29, card_path, scan, scan_path, card, receipt_path = _case_fixture(tmp_path)
    scan["failures"] = [{"field": "rho", "status": "nonfinite"}]
    scan_path.write_text(json.dumps(scan, sort_keys=True), encoding="utf-8")
    card["scan_provenance"]["observed_sha256"] = _sha(scan_path)
    card["scientific_scan"]["failures"] = scan["failures"]
    card_path.write_text(json.dumps(card, sort_keys=True), encoding="utf-8")
    v29["scientific_audit"]["scan_provenance"]["declared_sha256"] = _sha(scan_path)
    result = MODULE._case_audit("F1/CASE", current, v29, card_path, MODULE._ref(card_path, "detail"), scan_path, MODULE._ref(scan_path, "scan"), receipt_path, MODULE._ref(receipt_path, "receipt"), str(current["_current_path"]), MODULE.CURRENT_SHA256)
    assert result["observed_fields"]["finite_field_failure_list"] == {"status": "OBSERVED_NONEMPTY", "count": 1, "qualification_credit": "NONE"}


def test_nonexact_current_alias_is_retained_without_exact_source_credit(tmp_path: Path) -> None:
    current, v29, card_path, scan, scan_path, card, receipt_path = _case_fixture(tmp_path)
    alias_path = tmp_path / "catalog-002" / "CURRENT336.json"
    alias_path.parent.mkdir()
    alias_path.write_text(json.dumps({"schema": MODULE.CURRENT_SCHEMA, "cases": []}), encoding="utf-8")
    receipt = json.loads(receipt_path.read_text())
    receipt["input_hashes_after_run"] = {str(alias_path): "1" * 64}
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    card = json.loads(card_path.read_text())
    card["receipt_provenance"]["observed_sha256"] = _sha(receipt_path)
    card_path.write_text(json.dumps(card, sort_keys=True), encoding="utf-8")
    v29["scientific_audit"]["receipt_provenance"]["declared_sha256"] = _sha(receipt_path)
    result = MODULE._case_audit("F1/CASE", current, v29, card_path, MODULE._ref(card_path, "detail"), scan_path, MODULE._ref(scan_path, "scan"), receipt_path, MODULE._ref(receipt_path, "receipt"), str(current["_current_path"]), MODULE.CURRENT_SHA256)
    assert result["source_closure"]["status"] == "CURRENT_RECEIPT_BINDING_MISMATCH"
    assert result["receipt"]["current_binding"]["exact"] is False
    assert result["source_closure"]["scientific_credit"] == "NONE"


def test_ledger_frame_mismatch_is_rejected() -> None:
    with pytest.raises(MODULE.AuditError, match="lengths do not equal frames"):
        MODULE._summary_ledger("fluid", {"active_count": [1], "active_mass_kg": [1.0]}, 2, "F1/CASE")


def test_producer_identity_is_required_and_cannot_be_replaced_by_catalog_case_key(tmp_path: Path) -> None:
    current, v29, card_path, scan, scan_path, card, receipt_path = _case_fixture(tmp_path)
    scan.pop("family_id")
    scan_path.write_text(json.dumps(scan, sort_keys=True), encoding="utf-8")
    card["scan_provenance"]["observed_sha256"] = _sha(scan_path)
    card_path.write_text(json.dumps(card, sort_keys=True), encoding="utf-8")
    with pytest.raises(MODULE.AuditError, match="producer family_id/physical_case_id"):
        MODULE._case_audit("F1/CASE", current, v29, card_path, MODULE._ref(card_path, "detail"), scan_path, MODULE._ref(scan_path, "scan"), receipt_path, MODULE._ref(receipt_path, "receipt"), str(current["_current_path"]), MODULE.CURRENT_SHA256)
