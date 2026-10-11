"""Focused tests for the M4 solver/native-audit queue gates."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("run_solver_native_audit_queue.py")
SPEC = importlib.util.spec_from_file_location("m4_native_queue", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
QUEUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUEUE)


def test_case_aliases_and_solver_contract_are_root_bound() -> None:
    case = QUEUE._case_id("H052")
    assert case == "UF_F1_MDBC_DP010_H052"
    request = QUEUE._solver_request(case)
    grant = QUEUE._validate_solver_grant(case, request)
    assert request["estimated_storage_bytes"] == 9 * 1024**3
    assert request["time_max_s"] == 6.0
    assert request["time_out_s"] == 0.025
    assert request["dp_m"] == 0.01
    assert request["expected_frames"] == 241
    assert grant["attempt_id"] == f"F1/{case}/solver-001"


@pytest.mark.parametrize("status", ["running", "failed"])
def test_running_or_failed_receipts_fail_closed(tmp_path: Path, status: str) -> None:
    receipt = tmp_path / "execution-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": QUEUE.RECEIPT_SCHEMA,
                "status": status,
                "request": {"case_id": "UF_F1_MDBC_DP010_H052", "attempt_id": "solver-001"},
            }
        ),
        encoding="utf-8",
    )
    state, _ = QUEUE._receipt_state(receipt, "UF_F1_MDBC_DP010_H052", "solver-001")
    assert state == status


def test_completed_receipt_requires_case_bound_terminal_returncode(tmp_path: Path) -> None:
    receipt = tmp_path / "execution-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": QUEUE.RECEIPT_SCHEMA,
                "status": "completed",
                "request": {"case_id": "UF_F1_MDBC_DP010_H052", "attempt_id": "solver-001"},
            }
        ),
        encoding="utf-8",
    )
    state, _ = QUEUE._receipt_state(receipt, "UF_F1_MDBC_DP010_H052", "solver-001")
    assert state == "invalid"


def test_promotion_cannot_change_scientific_fields() -> None:
    candidate = {"case_id": "UF_F1_MDBC_DP010_H052", "time_out_s": 0.025, "status": "candidate"}
    promoted = copy.deepcopy(candidate)
    promoted["status"] = "root_authorized"
    QUEUE._assert_only_promotion_fields_changed(candidate, promoted)

    promoted["time_out_s"] = 0.01
    with pytest.raises(QUEUE.QueueError, match="non-authorization"):
        QUEUE._assert_only_promotion_fields_changed(candidate, promoted)


def test_frame_input_name_is_deferred_contract() -> None:
    assert QUEUE.FRAME_RE.fullmatch("Part_0000.bi4")
    assert QUEUE.FRAME_RE.fullmatch("Part_0240.bi4")
    assert not QUEUE.FRAME_RE.fullmatch("PartInfo.ibi4")
