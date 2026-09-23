from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f4_tallwall120_t2_admission_acceptance_gap_audit_v4 import (
    DEFAULT_OUTPUT_NAME,
    DEFAULT_REPORT_NAME,
    SCHEMA,
    build_audit,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_audit_reconciles_validator_presence_with_negative_science_gates() -> None:
    value = build_audit(ROOT)
    route = value["sidecar_preflight_v2"]
    implementation = value["acceptance_implementation"]

    assert value["schema"] == SCHEMA
    assert value["T2_macro"] is False and value["T2_path"] is False
    assert value["qualification_credit"] == "none"
    assert implementation["diagnostic_validator_present"] is True
    assert implementation["sidecar_preflight_calls_validator"] is True
    assert implementation["authoritative_f4_cdf_tolerance_registered"] is False
    assert implementation["authoritative_f4_residence_tolerance_registered"] is False
    assert route["registered_case_count"] == 6
    assert route["validator_invocation_count"] == 6
    assert route["blocked_case_count"] == 6
    assert route["passed_case_count"] == 0
    assert route["formal_acceptance_receipt_count"] == 0
    assert value["acceptance_gates"]["sidecar_preflight_bridges_acceptance"] is True
    assert value["acceptance_gates"]["per_case_sidecar_acceptance"] is False
    assert value["admission_surface_pass"] is False


def test_current_audit_artifacts_bind_the_v2_route_without_rewriting_history() -> None:
    evidence = ROOT / DEFAULT_OUTPUT_NAME
    report = ROOT / DEFAULT_REPORT_NAME
    assert evidence.is_file() and report.is_file()
    value = json.loads(evidence.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert "acceptance validator 和逐例 sidecar wiring 已实现" in report.read_text(encoding="utf-8")
    assert "T2_macro=false" in report.read_text(encoding="utf-8")
    assert value["execution_constraints"]["old_evidence_overwritten"] is False
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name
