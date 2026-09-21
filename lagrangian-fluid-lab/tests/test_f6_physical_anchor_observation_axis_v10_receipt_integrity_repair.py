"""Tests for the one-shot F6 receipt metadata repair."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.f6_physical_anchor_observation_axis_v10_receipt_integrity_repair import repair


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _receipt() -> dict:
    return {
        "schema": "core.f6.observation_axis.protected_solver_canary_receipt.v1",
        "receipt_id": "cell_receipt",
        "status": "solver_completed_hard_failure",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "execution_controls": {
            "solver_invoked": True,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
        "hard_gates": {"native_arrays_finite": False},
        "native_frame_audit": {
            "path": "tmp/native-frame-audit.json",
            "sha256": None,
            "bytes": 0,
            "role": "per-frame native audit",
        },
    }


def test_repair_binds_existing_audit_without_solver_or_science_change(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt-001"
    attempt.mkdir()
    (attempt / "native-frame-audit.json").write_text('{"frames": []}\n', encoding="utf-8")
    receipt = _receipt()
    receipt["native_frame_audit"]["path"] = str((attempt / "native-frame-audit.json").resolve())
    # The production path is relative to LAB.  Use a synthetic absolute path
    # only for the contract rejection test below.
    with pytest.raises(ValueError, match="under LAB"):
        _write(attempt / "execution-receipt.json", receipt)
        repair(attempt)


def test_repair_is_one_shot_and_preserves_science_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import f6_physical_anchor_observation_axis_v10_receipt_integrity_repair as module

    monkeypatch.setattr(module, "LAB", tmp_path)
    attempt = tmp_path / "attempt-001"
    attempt.mkdir()
    audit = attempt / "native-frame-audit.json"
    audit.write_text('{"frames": []}\n', encoding="utf-8")
    receipt = _receipt()
    relative = (attempt.resolve().relative_to(module.LAB.resolve()) / "native-frame-audit.json").as_posix()
    receipt["native_frame_audit"]["path"] = relative
    _write(attempt / "execution-receipt.json", receipt)
    result = repair(attempt)
    assert result["solver_reinvoked"] is False
    repaired = json.loads((attempt / "execution-receipt.json").read_text())
    assert repaired["status"] == receipt["status"]
    assert repaired["hard_gates"] == receipt["hard_gates"]
    assert repaired["qualification_credit"] == 0
    assert repaired["native_frame_audit"]["sha256"] == _sha(audit)
    assert repaired["native_frame_audit"]["bytes"] == audit.stat().st_size
    assert json.loads((attempt / "execution-receipt-pre-repair.json").read_text()) == receipt
    with pytest.raises(RuntimeError, match="already consumed"):
        repair(attempt)
