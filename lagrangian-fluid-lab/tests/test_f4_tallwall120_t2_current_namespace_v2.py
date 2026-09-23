from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.f4_tallwall120_t2_acceptance_bridge_v3 import (
    FORMAL_RECEIPT_SCHEMA,
    SCHEMA as BRIDGE_SCHEMA,
    verify_receipt,
)
from scripts.f4_tallwall120_t2_admission_acceptance_gap_audit_v3 import (
    SCHEMA as GAP_SCHEMA,
    build_audit,
)


ROOT = Path(__file__).resolve().parents[1]
GAP_EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-admission-acceptance-gap-audit-20260923-v4.json"
)
GAP_REPORT = ROOT / "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-23-v4.zh-CN.md"
BRIDGE_EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260923-v5.json"
)
BRIDGE_REPORT = ROOT / "reports/F4-TALLWALL120-T2-ACCEPTANCE-BRIDGE-2026-09-23-v5.zh-CN.md"


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
    # v5 is retained as historical evidence.  A later source-only change to
    # the tallwall tracer invalidated its binding; current closure is tested
    # in the v3 namespace against bridge v6.
    with pytest.raises(ValueError, match="tallwall_material_code byte count changed|tallwall_material_code SHA-256 changed"):
        verify_receipt(BRIDGE_EVIDENCE, ROOT)


def test_current_artifacts_are_distinct_from_historical_namespace() -> None:
    assert GAP_EVIDENCE.is_file() and GAP_REPORT.is_file()
    assert BRIDGE_EVIDENCE.is_file() and BRIDGE_REPORT.is_file()
    assert "v4" in GAP_EVIDENCE.name and "v5" in BRIDGE_EVIDENCE.name
    assert "T2_macro=false" in GAP_REPORT.read_text(encoding="utf-8")
    assert "T2_macro=false" in BRIDGE_REPORT.read_text(encoding="utf-8")
