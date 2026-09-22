import hashlib
import json
from pathlib import Path

from scripts.f3_t2_admission_acceptance_gap_audit_v2 import (
    DEFAULT_OUTPUT,
    DEFAULT_REPORT,
    SCHEMA,
    build_audit,
    render_report,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v2_binds_bridge_without_promoting_science():
    value = build_audit(ROOT)
    assert value["schema"] == SCHEMA
    assert value["T2_macro"] is False
    assert value["qualification_credit"] == "none"
    assert value["acceptance_gates"]["native_mls_acceptance_bridge_present"] is True
    assert value["matrix"]["registered_row_count"] == 33
    assert value["matrix"]["formal_acceptance_receipt_count"] == 0
    assert value["observed_gate_comparison"]["source_window"]["unknown_mass"]["all_rows_pass"] is False
    assert value["observed_gate_comparison"]["source_window"]["cdf"]["all_rows_pass"] is False


def test_v2_bridge_binding_is_current_and_old_evidence_is_preserved():
    value = build_audit(ROOT)
    binding = value["input_bindings"]["native_mls_acceptance_adapter"]
    adapter = ROOT / binding["path"]
    assert adapter.is_file()
    assert binding["bytes"] == adapter.stat().st_size
    assert binding["sha256"] == hashlib.sha256(adapter.read_bytes()).hexdigest()
    assert value["version_transition"]["previous_evidence_preserved"] is True
    assert value["version_transition"]["scientific_denominator_changed"] is False
    report = render_report(value, ROOT / DEFAULT_OUTPUT)
    assert "acceptance bridge" in report
    assert "qualification_credit=none" in report


def test_v2_artifacts_are_present_and_hash_closed():
    evidence = ROOT / DEFAULT_OUTPUT
    report = ROOT / DEFAULT_REPORT
    assert evidence.is_file()
    assert report.is_file()
    value = json.loads(evidence.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    binding = value["input_bindings"]["native_mls_acceptance_adapter"]
    adapter = ROOT / binding["path"]
    assert binding["sha256"] == hashlib.sha256(adapter.read_bytes()).hexdigest()
    assert "T2_macro=false" in report.read_text(encoding="utf-8")
