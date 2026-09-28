"""Focused tests for the bounded F8/R008 consistency bridge."""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import sys

import pytest

from scripts import f8_r008_terminal_matrix_readiness_consistency_v1 as contract


LAB = Path(__file__).resolve().parents[1]


def test_default_report_is_blocked_with_complete_denominator_and_zero_credit() -> None:
    report = contract.build_report()

    assert report["schema"] == contract.REPORT_SCHEMA
    assert report["status"] == contract.STATUS_BLOCKED
    assert report["scope_id"] == contract.SCOPE_ID
    assert report["matrix_binding"]["case_count"] == 15
    assert report["matrix_binding"]["rows_bound"] == 15
    assert report["attempt_terminal_binding"]["present"] is False
    assert report["attempt_terminal_binding"]["attempt_count"] == 0
    assert report["cross_binding"]["consistent"] is False
    assert report["cross_binding"]["blockers"] == [
        "attempt_evidence_missing",
        "attempt_nonce_markers_missing",
        "terminal_markers_missing",
    ]
    assert report["authorization"] == contract.AUTHORIZATION
    assert report["mutations"] == {
        "completion_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "ledger_mutation": 0,
        "plan_mutation": 0,
        "registry_mutation": 0,
    }


def test_checked_in_machine_report_equals_build_report() -> None:
    expected = contract.build_report()
    checked_in = json.loads(
        (LAB / "reports/F8-R008-TERMINAL-MATRIX-READINESS-CONSISTENCY-V1-2026-09-28.json").read_text(
            encoding="utf-8"
        )
    )
    assert checked_in == expected
    assert contract.validate_report(checked_in) == checked_in


def test_checked_in_chinese_report_preserves_blocked_boundary() -> None:
    text = (
        LAB / "reports/F8-R008-TERMINAL-MATRIX-READINESS-CONSISTENCY-V1-2026-09-28.zh-CN.md"
    ).read_text(encoding="utf-8")
    assert "diagnostic_only_terminal_matrix_readiness_consistency_blocked" in text
    assert "attempt_evidence_missing" in text
    assert "credit 为 `0`" in text


def test_report_authorization_promotion_fails_closed() -> None:
    report = copy.deepcopy(contract.build_report())
    report["authorization"]["T1_numerical"] = True

    with pytest.raises(contract.TerminalMatrixReadinessConsistencyError) as caught:
        contract.validate_report(report)

    assert caught.value.code == "authorization_drift"


def test_cross_binding_digest_drift_fails_closed() -> None:
    report = copy.deepcopy(contract.build_report())
    report["cross_binding"]["trusted_handoff_report_sha256"] = "f" * 64

    with pytest.raises(contract.TerminalMatrixReadinessConsistencyError) as caught:
        contract.validate_report(report)

    assert caught.value.code == "digest_drift"


def test_matrix_row_scope_drift_fails_closed(tmp_path: Path) -> None:
    source = LAB / contract.DEFAULT_TERMINAL_MATRIX
    matrix = json.loads(source.read_text(encoding="utf-8"))
    matrix["rows"][0]["q"] = 0.5
    mutated = tmp_path / "matrix.json"
    mutated.write_text(json.dumps(matrix, sort_keys=True), encoding="utf-8")

    with pytest.raises(contract.TerminalMatrixReadinessConsistencyError) as caught:
        contract.build_report(terminal_matrix_path=mutated)

    assert caught.value.code == "matrix_row_drift"


def test_duplicate_json_key_in_optional_attempt_projection_fails_closed(tmp_path: Path) -> None:
    duplicate = tmp_path / "attempt.json"
    duplicate.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")

    with pytest.raises(contract.TerminalMatrixReadinessConsistencyError) as caught:
        contract.build_report(attempt_evidence_path=duplicate)

    assert caught.value.code == "duplicate_json_key"


def test_missing_required_projection_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "readiness.json"

    with pytest.raises(contract.TerminalMatrixReadinessConsistencyError) as caught:
        contract.build_report(target_readiness_path=missing)

    assert caught.value.code == "missing_input"


def test_module_has_no_execution_or_production_artifact_reader() -> None:
    source = inspect.getsource(contract)
    for forbidden in (
        "import subprocess", "subprocess.", "nvidia-smi", "CUDA_VISIBLE_DEVICES",
        "import torch", "import h5py", "fanotify_init", "os.system",
    ):
        assert forbidden not in source
    assert "production_bi4_hdf5_or_solver_frame_read" in source
    assert str(sys.executable)
