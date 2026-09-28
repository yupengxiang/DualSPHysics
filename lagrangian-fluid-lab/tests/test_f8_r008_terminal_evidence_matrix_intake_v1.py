from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f8_r008_terminal_evidence_matrix_intake_v1 as intake


def _scope_document() -> dict:
    return json.loads((intake.LAB_ROOT / intake.DEFAULT_SCOPE).read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _claim(fields: frozenset[str]) -> dict:
    return {"bound": False, "trusted": False, "claims": {key: None for key in sorted(fields)}}


def _bcd(stage: str) -> dict:
    receipt, manifest = {
        "B": (intake.ATTEMPT_AND_METRIC_SCHEMAS["B_receipt"], intake.ATTEMPT_AND_METRIC_SCHEMAS["B_manifest"]),
        "C": (intake.ATTEMPT_AND_METRIC_SCHEMAS["C_receipt"], intake.ATTEMPT_AND_METRIC_SCHEMAS["C_manifest"]),
        "D": (intake.ATTEMPT_AND_METRIC_SCHEMAS["D_receipt"], intake.ATTEMPT_AND_METRIC_SCHEMAS["D_manifest"]),
    }[stage]
    return {
        "manifest_schema": manifest,
        "manifest_sha256": None,
        "provenance_bound": False,
        "receipt_schema": receipt,
        "receipt_sha256": None,
        "status": "partial",
        "trusted": False,
    }


def _claim_row(case_id: str, q: float, *, terminal_status: str = "partial") -> dict:
    return {
        "abi": _claim(intake.ABI_CLAIM_FIELDS),
        "B": _bcd("B"),
        "C": _bcd("C"),
        "D": _bcd("D"),
        "case_id": case_id,
        "metric": {
            "metric_result_sha256": None,
            "status": "partial",
            "t1_numerical": False,
            "trusted": False,
        },
        "provenance": {
            "chain_closed": False,
            "source_identity_verified": False,
            "status": "partial",
            "trusted": False,
        },
        "q": q,
        "runtime": _claim(intake.RUNTIME_CLAIM_FIELDS),
        "source": _claim(intake.SOURCE_CLAIM_FIELDS),
        "target": _claim(intake.TARGET_CLAIM_FIELDS),
        "terminal_status": terminal_status,
    }


def _evidence(case_id: str, q: float, *, origin: str = "trusted_production_terminal_evidence",
              terminal_status: str = "partial", rows: list[dict] | None = None) -> dict:
    return {
        "case_count": intake.CASE_COUNT,
        "input_origin": origin,
        "record_id": intake.TERMINAL_EVIDENCE_RECORD_ID,
        "rows": rows if rows is not None else [_claim_row(case_id, q, terminal_status=terminal_status)],
        "schema": intake.TERMINAL_EVIDENCE_SCHEMA,
        "scope_id": intake.SCOPE_ID,
        "status": "partial" if terminal_status != "complete" else "complete_claim",
    }


def _first_case() -> tuple[str, float]:
    row = _scope_document()["matrix"]["rows"][0]
    return row["case_id"], row["q"]


def test_default_report_binds_exact_frozen_15_rows_and_q_values() -> None:
    report = intake.build_report()
    rows = report["rows"]
    assert report["matrix_contract"]["case_count"] == 15
    assert report["matrix_contract"]["exact_15_rows"] is True
    assert len(rows) == 15
    assert [row["case_id"] for row in rows] == report["matrix_contract"]["case_ids"]
    assert [row["q"] for row in rows] == [
        report["matrix_contract"]["q_values_by_case"][row["case_id"]] for row in rows
    ]
    assert all(row["input_refs"]["definition"]["path"].endswith(".xml") for row in rows)
    assert all(row["input_refs"]["control"]["path"].endswith(".csv") for row in rows)


def test_default_without_production_terminal_evidence_is_rowwise_missing_and_zero_credit() -> None:
    report = intake.build_report()
    assert report["summary"]["missing_rows"] == 15
    assert report["summary"]["unresolved_rows"] == 0
    assert all(row["terminal_status"] == "missing" for row in report["rows"])
    assert all(row["solver_completion_verified"] is False for row in report["rows"])
    assert report["authorization"]["readiness_pass"] is False
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["formal"] is False
    assert report["authorization"]["qualification_credit"] == 0


def test_partial_terminal_evidence_remains_unresolved_and_does_not_complete_other_rows(tmp_path: Path) -> None:
    case_id, q = _first_case()
    evidence_path = _write_json(tmp_path / "partial.json", _evidence(case_id, q))
    report = intake.build_report(terminal_evidence_path=evidence_path)
    by_id = {row["case_id"]: row for row in report["rows"]}
    assert by_id[case_id]["terminal_status"] == "unresolved"
    assert by_id[case_id]["claim_input_origin"] == "trusted_production_terminal_evidence"
    assert sum(row["terminal_status"] == "unresolved" for row in report["rows"]) == 1
    assert sum(row["terminal_status"] == "missing" for row in report["rows"]) == 14
    assert by_id[case_id]["solver_completion_verified"] is False
    assert report["authorization"]["qualification_credit"] == 0


def test_scope_row_drift_is_rejected_against_definition_control_pack(tmp_path: Path) -> None:
    scope = _scope_document()
    scope["matrix"]["rows"][0]["q"] = 0.125
    scope_path = _write_json(tmp_path / "drifted-scope.json", scope)
    with pytest.raises(intake.TerminalEvidenceMatrixIntakeError, match="row drift"):
        intake.build_report(scope_path=scope_path)


def test_terminal_evidence_row_drift_is_rejected(tmp_path: Path) -> None:
    case_id, q = _first_case()
    evidence = _evidence(case_id, q + 0.125)
    evidence_path = _write_json(tmp_path / "row-drift.json", evidence)
    with pytest.raises(intake.TerminalEvidenceMatrixIntakeError, match="q drift"):
        intake.build_report(terminal_evidence_path=evidence_path)


def test_untrusted_static_receipt_is_unresolved_not_solver_completion(tmp_path: Path) -> None:
    case_id, q = _first_case()
    evidence_path = _write_json(
        tmp_path / "static.json",
        _evidence(case_id, q, origin="synthetic_static_receipt", terminal_status="complete"),
    )
    report = intake.build_report(terminal_evidence_path=evidence_path)
    row = next(item for item in report["rows"] if item["case_id"] == case_id)
    assert row["terminal_status"] == "unresolved"
    assert row["claim_input_origin"] == "synthetic_static_receipt"
    assert row["source_pins"]["trusted"] is False
    assert row["runtime_pins"]["trusted"] is False
    assert row["B"]["trusted"] is False
    assert row["metric"]["t1_numerical"] is False
    assert report["authorization"]["T1_numerical"] is False


def test_duplicate_terminal_evidence_rows_are_rejected(tmp_path: Path) -> None:
    case_id, q = _first_case()
    row = _claim_row(case_id, q)
    evidence_path = _write_json(tmp_path / "duplicate.json", _evidence(case_id, q, rows=[row, copy.deepcopy(row)]))
    with pytest.raises(intake.TerminalEvidenceMatrixIntakeError, match="duplicate terminal evidence row"):
        intake.build_report(terminal_evidence_path=evidence_path)


def test_report_binding_and_zero_credit_validator_reject_promotion() -> None:
    report = intake.build_report()
    assert report == intake.build_report()
    assert intake.validate_report(report) == report
    tampered = copy.deepcopy(report)
    tampered["authorization"]["qualification_credit"] = 1
    with pytest.raises(intake.TerminalEvidenceMatrixIntakeError, match="authorization boundary"):
        intake.validate_report(tampered)
