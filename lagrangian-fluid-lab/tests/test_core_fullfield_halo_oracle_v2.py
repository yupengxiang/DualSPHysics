"""Read-only verification tests for the refreshed full-field/halo bundle."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from scripts.core_fullfield_halo_oracle_v2 import (
    CLOSURE_VERSION,
    build_v2_bundle,
    verify_v2_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "campaigns/core-v1/learning/core-fullfield-halo-oracle-diagnostic-20260922-v2.json"
CLOSURE = ROOT / "campaigns/core-v1/learning/core-fullfield-halo-oracle-source-closure-20260922-v2.json"
RECEIPT_SHA256 = RECEIPT.with_name(RECEIPT.name + ".sha256")
CLOSURE_SHA256 = CLOSURE.with_name(CLOSURE.name + ".sha256")
REGISTRY = ROOT / "campaigns/core-v1/registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_committed_v2_receipt_and_source_closure_verify() -> None:
    result = verify_v2_receipt(RECEIPT, data_root=ROOT, closure_path=CLOSURE)
    assert result["ok"] is True
    assert result["mismatch_paths"] == []
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert payload["diagnostic_only"] is True
    assert payload["formal_training"] is False
    assert payload["execution_constraints"]["registry_written"] is False
    assert payload["execution_constraints"]["ledger_written"] is False
    assert payload["source_closure"]["closure_version"] == CLOSURE_VERSION
    assert RECEIPT_SHA256.read_text(encoding="utf-8").split()[0] == _sha256(RECEIPT)
    assert CLOSURE_SHA256.read_text(encoding="utf-8").split()[0] == _sha256(CLOSURE)


def test_v2_bundle_refresh_is_cpu_only_and_does_not_touch_registry(tmp_path: Path) -> None:
    registry_before = _sha256(REGISTRY)
    receipt = tmp_path / "receipt.json"
    closure = tmp_path / "source-closure.json"
    build_v2_bundle(data_root=ROOT, receipt_path=receipt, closure_path=closure)
    result = verify_v2_receipt(receipt, data_root=ROOT, closure_path=closure)
    assert result["ok"] is True
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["protocol"]["device"] == "cpu"
    assert payload["protocol"]["optimizer_started"] is False
    assert payload["protocol"]["gpu_started"] is False
    assert _sha256(REGISTRY) == registry_before


def test_v2_verifier_rejects_source_or_closure_tampering(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    closure = tmp_path / "source-closure.json"
    build_v2_bundle(data_root=ROOT, receipt_path=receipt, closure_path=closure)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(payload)
    tampered["source_closure"]["source_bindings"][0]["sha256"] = "0" * 64
    receipt.write_text(json.dumps(tampered), encoding="utf-8")
    result = verify_v2_receipt(receipt, data_root=ROOT, closure_path=closure)
    assert result["ok"] is False
    assert "source_closure.receipt_bindings" in result["mismatch_paths"]

    receipt.write_text(json.dumps(payload), encoding="utf-8")
    closure_payload = json.loads(closure.read_text(encoding="utf-8"))
    closure_payload["source_bindings"][1]["sha256"] = "0" * 64
    closure.write_text(json.dumps(closure_payload), encoding="utf-8")
    result = verify_v2_receipt(receipt, data_root=ROOT, closure_path=closure)
    assert result["ok"] is False
    assert "scripts/core_models.py" in result["mismatch_paths"]
