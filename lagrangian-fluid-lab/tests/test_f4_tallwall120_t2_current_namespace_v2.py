from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f4_tallwall120_t2_acceptance_bridge_v2 import (
    FORMAL_RECEIPT_SCHEMA,
    SCHEMA as BRIDGE_SCHEMA,
    verify_receipt,
)
from scripts.f4_tallwall120_t2_admission_acceptance_gap_audit_v2 import (
    SCHEMA as GAP_SCHEMA,
    build_audit,
)


ROOT = Path(__file__).resolve().parents[1]
GAP_EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-admission-acceptance-gap-audit-20260922-v3.json"
)
GAP_REPORT = ROOT / "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-22-v3.zh-CN.md"
BRIDGE_EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260922-v4.json"
)
BRIDGE_REPORT = ROOT / "reports/F4-TALLWALL120-T2-ACCEPTANCE-BRIDGE-2026-09-22-v4.zh-CN.md"


def test_current_gap_audit_is_a_new_namespace_and_binds_current_material_code() -> None:
    value = json.loads(GAP_EVIDENCE.read_text(encoding="utf-8"))
    assert value["schema"] == GAP_SCHEMA
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification_credit"] == "none"
    assert value["execution_constraints"]["old_evidence_overwritten"] is False
    for name in ("core_material", "core_material_acceptance"):
        binding = value["input_bindings"][name]
        path = ROOT / binding["path"]
        assert path.stat().st_size == binding["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]


def test_current_gap_builder_keeps_negative_scientific_state() -> None:
    value = build_audit(ROOT)
    assert value["schema"] == GAP_SCHEMA
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification_credit"] == "none"
    assert value["admission_surface_pass"] is False


def test_current_bridge_closes_current_hashes_and_keeps_zero_credit() -> None:
    value = json.loads(BRIDGE_EVIDENCE.read_text(encoding="utf-8"))
    assert value["schema"] == BRIDGE_SCHEMA
    assert value["engineering_receipt"]["status"] == "recorded"
    assert value["scientific_qualification"]["status"] == "blocked"
    assert value["formal_acceptance_receipt"]["schema"] == FORMAL_RECEIPT_SCHEMA
    assert value["formal_acceptance_receipt"]["credit"] == 0
    assert value["formal_acceptance_receipt"]["T2_macro"] is False
    assert value["formal_acceptance_receipt"]["T2_path"] is False
    for name in ("core_material", "core_material_acceptance"):
        binding = value["input_bindings"][name]
        path = ROOT / binding["path"]
        assert path.stat().st_size == binding["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]


def test_current_bridge_verifier_passes_without_opening_h5_or_mutating_qualification() -> None:
    verified = verify_receipt(BRIDGE_EVIDENCE, ROOT)
    assert verified["schema"] == BRIDGE_SCHEMA
    assert verified["status"] == "blocked"
    value = verified["value"]
    assert value["credit"] == 0
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["execution_constraints"]["source_h5_opened"] is False
    assert value["execution_constraints"]["solver_started"] is False
    assert value["execution_constraints"]["gpu_started"] is False


def test_current_artifacts_are_distinct_from_historical_namespace() -> None:
    assert GAP_EVIDENCE.is_file() and GAP_REPORT.is_file()
    assert BRIDGE_EVIDENCE.is_file() and BRIDGE_REPORT.is_file()
    assert "v3" in GAP_EVIDENCE.name and "v4" in BRIDGE_EVIDENCE.name
    assert "T2_macro=false" in GAP_REPORT.read_text(encoding="utf-8")
    assert "T2_macro=false" in BRIDGE_REPORT.read_text(encoding="utf-8")
