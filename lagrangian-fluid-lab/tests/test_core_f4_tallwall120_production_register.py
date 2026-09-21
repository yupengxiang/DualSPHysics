from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.core_f4_tallwall120_production_register import RegistrationError, register_f4


def _write(path: Path, data: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": path.as_posix(), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def _make_fixture(root: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    range_path = root / "range.json"
    range_path.write_text(json.dumps({
        "schema": "core.qualification.v1", "scope_id": "F4_resting_pool_laminar_tallwall120_x_v1",
        "family": "F4", "T1_numerical": True, "matrix_complete": True,
        "independent_checks_passed": True, "extent": "parameter_range",
    }))
    cases = []
    manifest = []
    split_for = lambda i: "train" if i < 16 else "validation" if i < 20 else "id_test" if i < 26 else "ood_test"
    for i in range(32):
        case_id = f"F4_CASE_{i:02d}"
        base = root / "products" / case_id
        refs = {name: _write(base / f"{name}.json", f"{case_id}-{name}".encode())
                for name in ("audit", "execution", "result", "observations", "prepared")}
        trajectory = _write(base / "trajectory.h5", f"trajectory-{case_id}".encode())
        cases.append({
            "index": i, "case_id": case_id, "physical_case_id": case_id,
            "lineage_group_id": case_id, "family": "F4", "split": split_for(i),
            "status": "completed", "scientific_status": "passed",
            "authoritative_audit_verified": True, "execution_complete": True,
            "execution_receipt_bound": True, "qualification_only": False,
            "reader_eligible": True, "failure_category": None, "reasons": [],
            **refs,
        })
        manifest.append({
            "case_id": case_id, "hdf5": trajectory["path"], "bytes": trajectory["bytes"],
            "sha256": trajectory["sha256"], "production_status": "completed",
            "scientific_status": "passed", "qualification_case": False,
            "known_inputs_sha256": "known-inputs",
        })
    collection = root / "collection.json"
    collection.write_text(json.dumps({
        "schema": "core.f4.tallwall120.production_collection.v1",
        "scope_id": "F4_resting_pool_laminar_tallwall120_x_v1", "family": "F4",
        "formal_release_requested": True, "formal_eligible": True,
        "qualification_evidence_verified": True, "gpu_started": False,
        "ledger_written": False, "central_registry_written": False,
        "registered_case_count": 32, "prepared_case_count": 32,
        "execution_complete_count": 32, "execution_receipt_bound_case_count": 32,
        "authoritative_audit_verified_case_count": 32,
        "scientifically_passed_case_count": 32, "failed_case_count": 0,
        "pending_case_count": 0, "invalid_case_count": 0, "hold_reasons": [],
        "cases": cases, "reader_manifest": {"cases": manifest},
    }))
    registry = root / "registry.json"
    registry.write_text(json.dumps({"schema": "core.registry.v1", "scope_studies": [],
                                    "scopes": [], "training_runs": [], "evaluations": []}))
    qualification = root / "registered-qualification.json"
    case_dir = root / "registered-cases"
    registration = root / "registration.json"
    return collection, range_path, registry, qualification, case_dir, registration


def test_formal_f4_registration_is_hash_bound_and_idempotent(tmp_path: Path) -> None:
    collection, range_path, registry, qualification, case_dir, registration = _make_fixture(tmp_path)
    first = register_f4(lab_root=tmp_path, registry_path=registry,
                        formal_collection=collection, range_qualification=range_path,
                        qualification_output=qualification, case_dir=case_dir,
                        registration_output=registration)
    second = register_f4(lab_root=tmp_path, registry_path=registry,
                         formal_collection=collection, range_qualification=range_path,
                         qualification_output=qualification, case_dir=case_dir,
                         registration_output=registration)
    assert first["case_count"] == second["case_count"] == 32
    state = json.loads(registry.read_text())
    assert len(state["scopes"]) == 1
    assert len(state["scopes"][0]["cases"]) == 32
    assert len(list(case_dir.glob("*.json"))) == 32
    assert json.loads(registration.read_text())["central_registry_written"] is True


def test_formal_f4_registration_rejects_ineligible_collection_without_writing(tmp_path: Path) -> None:
    collection, range_path, registry, qualification, case_dir, registration = _make_fixture(tmp_path)
    payload = json.loads(collection.read_text())
    payload["formal_eligible"] = False
    collection.write_text(json.dumps(payload))
    before = registry.read_bytes()
    with pytest.raises(RegistrationError, match="not formally eligible"):
        register_f4(lab_root=tmp_path, registry_path=registry,
                    formal_collection=collection, range_qualification=range_path,
                    qualification_output=qualification, case_dir=case_dir,
                    registration_output=registration)
    assert registry.read_bytes() == before
    assert not qualification.exists()
    assert not case_dir.exists()
