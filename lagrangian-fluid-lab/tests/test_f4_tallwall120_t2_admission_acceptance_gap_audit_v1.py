from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f4_tallwall120_t2_admission_acceptance_gap_audit_v1 import (
    INPUTS,
    SCHEMA,
    build_audit,
    summarize_case_sidecars,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-admission-acceptance-gap-audit-20260922-v2.json"
)
REPORT = ROOT / "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-22-v2.zh-CN.md"


def test_audit_keeps_fixed_scientific_gates_and_denominators_negative() -> None:
    value = build_audit(ROOT)
    assert value["schema"] == SCHEMA
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification_credit"] == "none"
    assert value["observed_gate_comparison"]["unknown_mass"]["maximum_observed"] == 1.0
    assert value["observed_gate_comparison"]["unknown_mass"]["all_cases_pass"] is False
    assert value["observed_gate_comparison"]["event_window"]["all_cases_complete"] is False
    assert value["observed_gate_comparison"]["mass_closure"]["all_retained_cases_closed"] is True
    assert value["case_sidecars"]["case_count"] == 6
    assert value["execution_constraints"]["T1_denominator_changed"] is False
    assert value["execution_constraints"]["T2_denominator_changed"] is False


def test_acceptance_gap_is_explicit_for_tallwall_residence_and_event_contract() -> None:
    value = build_audit(ROOT)
    acceptance = value["code_contracts"]["core_material_acceptance"]
    macro = value["code_contracts"]["macro_sidecar_preflight"]
    assert acceptance["per_source_unknown_gate"] is True
    assert acceptance["generic_cdf_difference_gate"] is True
    assert acceptance["tallwall_schema"] is False
    assert acceptance["tallwall_checkpoint_v2"] is True
    assert acceptance["residence_cdf_gate"] is False
    assert acceptance["f4_event_tolerance_gate"] is False
    assert acceptance["content_addressed_generation_gate"] is False
    assert macro["acceptance_adapter_called"] is False
    assert macro["f4_residence_gate"] is False
    assert macro["f4_event_tolerance_gate"] is False
    assert value["acceptance_gates"]["f4_cdf_tolerance_registered"] is False
    assert value["acceptance_gates"]["residence_tolerance_acceptance"] is False
    assert value["acceptance_gates"]["event_tolerance_acceptance"] is False
    assert value["admission_surface_pass"] is False


def test_per_case_receipts_separate_cdf_fields_from_checkpoint_integrity() -> None:
    value = build_audit(ROOT)
    sidecars = value["case_sidecars"]
    assert sidecars["result_sidecars_present"] == 6
    assert sidecars["cdf_complete_case_count"] == 5
    assert sidecars["residence_complete_case_count"] == 5
    assert sidecars["formal_acceptance_receipt_count"] == 0
    assert sidecars["checkpoint_integrity_pass_count"] == 6
    assert sidecars["content_addressed_checkpoint_count"] == 1
    assert value["recovery_contract"]["append_only_required"] is True
    assert value["recovery_contract"]["tallwall_generation_support"] is True
    assert value["recovery_contract"]["acceptance_generation_support"] is False
    assert value["recovery_contract"]["root_authorized_one_cpu_only"] is False


def test_audit_artifact_and_report_bind_current_inputs_without_overwriting_old_evidence() -> None:
    assert EVIDENCE.is_file()
    assert REPORT.is_file()
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    assert value["execution_constraints"]["old_evidence_overwritten"] is False
    assert "T2_macro=false" in REPORT.read_text(encoding="utf-8")
    stale = []
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        if (
            path.stat().st_size != binding["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != binding["sha256"]
        ):
            stale.append(name)
    # v2 is retained as immutable historical evidence.  Its core_material
    # binding predates the current source and is intentionally not repaired in
    # place; the acceptance implementation happened not to drift in this
    # historical snapshot.
    assert stale == ["core_material"]


def test_case_sidecar_helper_fails_closed_when_a_result_lacks_event_fields(tmp_path: Path) -> None:
    source_window = {
        "f4": {
            "cases": [
                {
                    "canary_id": "fixture",
                    "case_id": "fixture",
                    "result_path": str(tmp_path / "result.json"),
                    "seed_denominator": 512,
                    "unknown_fraction_max": 0.0,
                    "mass_closed": True,
                    "event_window_complete": True,
                    "qualification_credit": "none",
                    "trace_audit": {
                        "unknown_gate": {"pass": True},
                        "event_window": {"status": "complete"},
                        "checkpoint": {
                            "manifest_path": str(tmp_path / "missing.checkpoint.json"),
                            "pass": False,
                            "state_hash_pass": False,
                        },
                    },
                }
            ]
        }
    }
    (tmp_path / "result.json").write_text(
        json.dumps({"by_source": [{"contact_cdf": {}, "upward_cdf": {}, "return_cdf": {}}]}),
        encoding="utf-8",
    )
    result = summarize_case_sidecars(ROOT, source_window)
    assert result["case_count"] == 1
    assert result["cdf_complete_case_count"] == 0
    assert result["residence_complete_case_count"] == 0
    assert result["formal_acceptance_receipt_count"] == 0
    assert result["checkpoint_integrity_pass_count"] == 0
