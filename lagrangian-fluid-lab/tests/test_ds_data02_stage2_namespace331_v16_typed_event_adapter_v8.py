from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_v16_typed_event_adapter_v8.py"
SPEC = importlib.util.spec_from_file_location("namespace331_event_v8_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

V7_TEST = ROOT / "tests/test_ds_data02_stage2_namespace331_v16_typed_event_adapter_v7.py"
V7_SPEC = importlib.util.spec_from_file_location("namespace331_event_v7_fixture_for_v8", V7_TEST)
assert V7_SPEC is not None and V7_SPEC.loader is not None
V7 = importlib.util.module_from_spec(V7_SPEC)
V7_SPEC.loader.exec_module(V7)


def test_root307_retry_requires_full_selected_proof_closure() -> None:
    result = MODULE.validate_request_v8(V7._request(V7.F5_CASE, "F5"), allow_fixture=True)
    join = result["current_identity_scope"]["join"]
    assert join["producer_id"] == "ROOT327"
    assert join["failed_history_count"] == 1
    assert join["proof_closure"]["selected_case_status"] == "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY"
    assert result["production_eligible"] is False


def test_missing_required_proof_field_is_rejected(tmp_path: Path) -> None:
    request = V7._request(V7.F5_CASE, "F5")
    registry = json.loads(V7.REGISTRY.read_text(encoding="utf-8"))
    producer = next(item for item in registry["producers"] if item.get("producer_id") == "ROOT327")
    proof_path = Path(producer["proof"]["path"])
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof.pop("guarded_receipt_status")
    replacement = tmp_path / "proof-missing-receipt-status.json"
    replacement.write_text(json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8")
    producer["proof"] = {"path": str(replacement),
                          "sha256": __import__("hashlib").sha256(replacement.read_bytes()).hexdigest()}
    bad_registry = tmp_path / "registry.json"
    bad_registry.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    plan = json.loads(V7.PLAN.read_text(encoding="utf-8"))
    plan["evidence_registry"] = {"path": str(bad_registry),
                                 "sha256": __import__("hashlib").sha256(bad_registry.read_bytes()).hexdigest()}
    bad_plan = tmp_path / "plan.json"
    bad_plan.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
    request["lifecycle_scope"]["current_plan"] = {"path": str(bad_plan),
                                                   "file_sha256": __import__("hashlib").sha256(bad_plan.read_bytes()).hexdigest()}
    request["lifecycle_scope"]["producer_registry"] = {"path": str(bad_registry),
                                                        "file_sha256": __import__("hashlib").sha256(bad_registry.read_bytes()).hexdigest()}
    request["request_sha256"] = MODULE._V7.canonical_sha(request)
    with pytest.raises(MODULE.TypedEventAdapterV8Error, match="required fields|receipt"):
        MODULE.validate_request_v8(request, allow_fixture=True)


def test_selected_proof_case_crossbind_is_required(tmp_path: Path) -> None:
    request = V7._request(V7.F5_CASE, "F5")
    registry = json.loads(V7.REGISTRY.read_text(encoding="utf-8"))
    producer = next(item for item in registry["producers"] if item.get("producer_id") == "ROOT327")
    proof_path = Path(producer["proof"]["path"])
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["case_verifications"][0]["physical_case_id"] = "F5_WRONG_CASE"
    replacement = tmp_path / "proof-crossed-case.json"
    replacement.write_text(json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8")
    producer["proof"] = {"path": str(replacement),
                          "sha256": __import__("hashlib").sha256(replacement.read_bytes()).hexdigest()}
    bad_registry = tmp_path / "registry.json"
    bad_registry.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    plan = json.loads(V7.PLAN.read_text(encoding="utf-8"))
    plan["evidence_registry"] = {"path": str(bad_registry),
                                 "sha256": __import__("hashlib").sha256(bad_registry.read_bytes()).hexdigest()}
    bad_plan = tmp_path / "plan.json"
    bad_plan.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
    request["lifecycle_scope"]["current_plan"] = {"path": str(bad_plan),
                                                   "file_sha256": __import__("hashlib").sha256(bad_plan.read_bytes()).hexdigest()}
    request["lifecycle_scope"]["producer_registry"] = {"path": str(bad_registry),
                                                        "file_sha256": __import__("hashlib").sha256(bad_registry.read_bytes()).hexdigest()}
    request["request_sha256"] = MODULE._V7.canonical_sha(request)
    with pytest.raises(MODULE.TypedEventAdapterV8Error, match="case|selected proof"):
        MODULE.validate_request_v8(request, allow_fixture=True)
