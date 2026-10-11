"""Focused metadata-only M4 resource-audit checks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("run_m4_resource_audit.py")
SPEC = importlib.util.spec_from_file_location("m4_resource_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


CASE = "UF_F1_MDBC_DP010_H052"
ATTEMPT = "gencase-001"
CHARGE_ID = f"F1/{CASE}/{ATTEMPT}"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _execution_fixture(tmp_path: Path) -> tuple[dict, Path]:
    nas = tmp_path / "nas"
    requests = tmp_path / "requests"
    request_path = requests / f"{CASE}-{ATTEMPT}.json"
    _write_json(request_path, {"case_id": CASE, "attempt_id": ATTEMPT})
    attempt_root = nas / "runs" / "F1" / CASE / ATTEMPT
    request_hash = AUDIT._sha256(request_path)
    receipt = {
        "schema": AUDIT.RECEIPT_SCHEMA,
        "request": {"case_id": CASE, "attempt_id": ATTEMPT},
        "request_sha256": request_hash,
        "output_root": str(attempt_root.resolve()),
        "status": "completed",
        "returncode": 0,
        "cpu_core_seconds": 2.5,
        "gpu_seconds": 0.0,
        "bytes": 1234,
    }
    receipt_path = attempt_root / "execution-receipt.json"
    _write_json(receipt_path, receipt)
    return (
        {
            "id": CHARGE_ID,
            "status": "completed",
            "cpu_core_seconds": 2.5,
            "gpu_seconds": 0.0,
            "new_storage_bytes": 1234,
            "output_storage": "upstream_nas",
        },
        requests,
    )


def test_charge_tamper_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row, requests = _execution_fixture(tmp_path)
    monkeypatch.setattr(AUDIT, "NAS_ROOT", tmp_path / "nas")
    monkeypatch.setattr(AUDIT, "REQUESTS", requests)
    AUDIT._verify_execution_charge(row)

    tampered = dict(row, new_storage_bytes=1235)
    with pytest.raises(AUDIT.AuditError, match="new_storage_bytes"):
        AUDIT._verify_execution_charge(tampered)


def test_missing_execution_receipt_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row, requests = _execution_fixture(tmp_path)
    receipt = tmp_path / "nas" / "runs" / "F1" / CASE / ATTEMPT / "execution-receipt.json"
    receipt.unlink()
    monkeypatch.setattr(AUDIT, "NAS_ROOT", tmp_path / "nas")
    monkeypatch.setattr(AUDIT, "REQUESTS", requests)
    with pytest.raises(AUDIT.AuditError, match="execution receipt"):
        AUDIT._verify_execution_charge(row)


def test_product_audit_is_pending_when_all_four_receipts_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = {
        "schema": "ds-data-02.m4.release-input.v1",
        "conditions": [
            {
                "case_id": case,
                "actual_validation": {"receipt": str(tmp_path / case / "actual-validation-receipt.json")},
            }
            for case in (
                "UF_F1_MDBC_DP010_H050",
                "UF_F1_MDBC_DP010_H052",
                "UF_F1_MDBC_DP010_H058",
                "UF_F1_MDBC_DP010_H060",
            )
        ],
    }
    release_path = tmp_path / "release-input.json"
    _write_json(release_path, release)
    monkeypatch.setattr(AUDIT, "RELEASE_INPUT", release_path)
    result = AUDIT._product_receipts()
    assert result["status"] == "pending_actual_product_receipts"
    assert result["all_four_product_receipts_missing"] is True
    assert len(result["missing_case_ids"]) == 4
