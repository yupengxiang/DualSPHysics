import json
from pathlib import Path

from scripts.f4_macro_t2_sidecar_preflight_v2 import (
    DEFAULT_OUTPUT,
    DEFAULT_REPORT,
    SCHEMA,
    build_preflight,
    render_report,
    validate_sidecar_payloads,
)


ROOT = Path(__file__).resolve().parents[1]


def test_validator_is_invoked_for_all_registered_f4_sidecars_and_fails_closed():
    value = build_preflight(ROOT)
    acceptance = value["json_acceptance"]
    assert value["schema"] == SCHEMA
    assert value["T2_macro"] is False
    assert value["qualification_claim"] == "none"
    assert acceptance["registered_case_count"] == 6
    assert acceptance["validator_invocation_count"] == 6
    assert acceptance["blocked_case_count"] == 6
    assert acceptance["passed_case_count"] == 0
    assert acceptance["formal_acceptance_receipt_count"] == 0
    assert value["gate_evaluation"]["json_case_validator_invoked"] is True
    assert value["gate_evaluation"]["json_case_acceptance_pass"] is False
    assert value["execution_constraints"]["json_validator_mutation"] == 0


def test_validator_contract_preserves_zero_credit_for_structural_and_scientific_failures():
    result = validate_sidecar_payloads([{"schema": "legacy.f4.summary.v1", "case_id": "legacy"}])
    row = result["rows"][0]
    assert result["blocked_case_count"] == 1
    assert row["passed"] is False
    assert row["qualification_claim"] == "none"
    assert row["qualification_credit"] == 0
    assert row["T2_macro"] is False
    assert row["execution_constraints"]["hdf5_opened"] is False


def test_v2_artifact_and_report_are_hash_bound():
    evidence = ROOT / DEFAULT_OUTPUT
    report = ROOT / DEFAULT_REPORT
    assert evidence.is_file()
    assert report.is_file()
    value = json.loads(evidence.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert value["json_acceptance"]["validator_invocation_count"] == 6
    rendered = render_report(value, evidence)
    assert "validator" in rendered
    assert "T2_macro=false" in rendered
