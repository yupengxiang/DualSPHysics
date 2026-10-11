"""Focused tests for the M4 solver/native-audit queue gates."""

from __future__ import annotations

import copy
import hashlib
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


def test_completed_stage_rejects_missing_or_wrong_request_hash(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_text('{"case_id":"UF_F1_MDBC_DP010_H052"}\n', encoding="utf-8")
    receipt = {"request_sha256": QUEUE._sha256(request)}
    QUEUE._assert_receipt_request_binding(
        receipt, request, "UF_F1_MDBC_DP010_H052", "solver-001"
    )

    missing = dict(receipt)
    missing.pop("request_sha256")
    with pytest.raises(QUEUE.QueueError, match="request_sha256"):
        QUEUE._assert_receipt_request_binding(
            missing, request, "UF_F1_MDBC_DP010_H052", "solver-001"
        )

    wrong = dict(receipt)
    wrong["request_sha256"] = "0" * 64
    with pytest.raises(QUEUE.QueueError, match="request_sha256"):
        QUEUE._assert_receipt_request_binding(
            wrong, request, "UF_F1_MDBC_DP010_H052", "solver-001"
        )


def test_exact_source_binding_rejects_a_case_path_swap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected_path = tmp_path / "UF_F1_MDBC_DP010_H052" / "Run.out"
    expected_path.parent.mkdir()
    expected_path.write_text("case-specific metadata\n", encoding="utf-8")
    swapped_path = tmp_path / "UF_F1_MDBC_DP010_H058" / "Run.out"
    swapped_path.parent.mkdir()
    swapped_path.write_text("different case\n", encoding="utf-8")
    monkeypatch.setattr(
        QUEUE,
        "_expected_native_source_paths",
        lambda case, mode: {"run_out": expected_path},
    )
    good = {"source_bindings": {"run_out": QUEUE._binding(expected_path, "fixture")}}
    QUEUE._assert_exact_native_source_bindings(good, "UF_F1_MDBC_DP010_H052", "exclusions")
    bad = {"source_bindings": {"run_out": QUEUE._binding(swapped_path, "fixture")}}
    with pytest.raises(QUEUE.QueueError, match="exact child file"):
        QUEUE._assert_exact_native_source_bindings(bad, "UF_F1_MDBC_DP010_H052", "exclusions")


def test_auditor_stdout_is_bound_to_report_and_execution_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt_root = tmp_path / "native-integrity-001"
    attempt_root.mkdir()
    report = attempt_root / "integrity.json"
    report.write_text(json.dumps({"status": "verified"}, sort_keys=True) + "\n", encoding="utf-8")
    stdout = attempt_root / "stdout.log"
    stdout.write_text(
        json.dumps({"path": str(report.resolve()), "status": "verified"}) + "\n",
        encoding="utf-8",
    )
    receipt_path = attempt_root / "execution-receipt.json"
    receipt_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        QUEUE,
        "_paths",
        lambda case: {
            "integrity_root": attempt_root,
            "frame_root": tmp_path / "frame",
            "integrity_receipt": receipt_path,
            "frame_receipt": tmp_path / "frame-receipt.json",
        },
    )
    receipt = {
        "stdout_sha256": QUEUE._sha256(stdout),
        "output_root": str(attempt_root.resolve()),
    }
    binding = QUEUE._assert_runner_report_binding(
        "UF_F1_MDBC_DP010_H052", "native-integrity-001", report, receipt
    )
    assert binding["report_sha256"] == QUEUE._sha256(report)

    stdout.write_text(stdout.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
    with pytest.raises(QUEUE.QueueError, match="stdout_sha256"):
        QUEUE._assert_runner_report_binding(
            "UF_F1_MDBC_DP010_H052", "native-integrity-001", report, receipt
        )


def test_prepared_frame_sequence_uses_metadata_without_opening_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "solver-001" / "data"
    monkeypatch.setattr(QUEUE, "_paths", lambda case: {"solver_data": data_root})
    frame_bindings = []
    expected = hashlib.sha256()
    deferred = []
    for index in range(QUEUE.EXPECTED_FRAMES):
        name = f"Part_{index:04d}.bi4"
        path = data_root / name
        size = index + 1
        digest = f"{index + 1:064x}"
        frame_bindings.append({"path": str(path), "bytes": size, "sha256": digest})
        deferred.append(str(path.resolve()))
        expected.update(name.encode("ascii"))
        expected.update(b"\0")
        expected.update(str(size).encode("ascii"))
        expected.update(b"\0")
        expected.update(digest.encode("ascii"))
        expected.update(b"\n")
    candidate = {
        "actual_solver_binding": {
            "regular_native_solver_files": frame_bindings,
            "frame_files_deferred_from_input_files": deferred,
        }
    }
    assert QUEUE._prepared_frame_hash_sequence(candidate, "UF_F1_MDBC_DP010_H052") == expected.hexdigest()

    frame_bindings[-1] = dict(frame_bindings[-1], bytes=999)
    # The metadata remains structurally valid; recomputing here proves the
    # sequence changes when a prepared source binding changes.
    assert QUEUE._prepared_frame_hash_sequence(candidate, "UF_F1_MDBC_DP010_H052") != expected.hexdigest()
