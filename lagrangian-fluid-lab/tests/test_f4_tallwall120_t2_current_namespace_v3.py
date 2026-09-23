from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f4_tallwall120_t2_acceptance_bridge_v4 import (
    FORMAL_RECEIPT_SCHEMA,
    SCHEMA as BRIDGE_SCHEMA,
    verify_receipt,
)
from scripts.f4_tallwall120_t2_admission_acceptance_gap_audit_v4 import (
    SCHEMA as GAP_SCHEMA,
)


ROOT = Path(__file__).resolve().parents[1]
GAP_EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-admission-acceptance-gap-audit-20260923-v5.json"
)
GAP_REPORT = ROOT / "reports/F4-TALLWALL120-T2-ADMISSION-ACCEPTANCE-GAP-AUDIT-2026-09-23-v5.zh-CN.md"
BRIDGE_EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-t2-acceptance-bridge-v1-20260923-v6.json"
)
BRIDGE_REPORT = ROOT / "reports/F4-TALLWALL120-T2-ACCEPTANCE-BRIDGE-2026-09-23-v6.zh-CN.md"


def test_current_artifacts_bind_updated_tallwall_and_acceptance_sources() -> None:
    gap = json.loads(GAP_EVIDENCE.read_text(encoding="utf-8"))
    bridge = json.loads(BRIDGE_EVIDENCE.read_text(encoding="utf-8"))
    assert gap["schema"] == GAP_SCHEMA
    assert bridge["schema"] == BRIDGE_SCHEMA
    assert bridge["formal_acceptance_receipt"]["schema"] == FORMAL_RECEIPT_SCHEMA
    assert bridge["formal_acceptance_receipt"]["credit"] == 0
    assert bridge["formal_acceptance_receipt"]["T2_macro"] is False
    assert bridge["formal_acceptance_receipt"]["T2_path"] is False
    assert gap["sidecar_preflight_v2"]["blocked_case_count"] == 6
    for name, binding in bridge["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name
    assert "T2_macro=false" in GAP_REPORT.read_text(encoding="utf-8")
    assert "T2_macro=false" in BRIDGE_REPORT.read_text(encoding="utf-8")


def test_current_bridge_verifies_only_zero_credit_diagnostic_evidence() -> None:
    verified = verify_receipt(BRIDGE_EVIDENCE, ROOT)
    assert verified["schema"] == BRIDGE_SCHEMA
    assert verified["status"] == "blocked"
    value = verified["value"]
    assert value["credit"] == 0
    assert value["T2_macro"] is False and value["T2_path"] is False
    assert value["execution_constraints"]["source_h5_opened"] is False
    assert value["execution_constraints"]["solver_started"] is False
    assert value["execution_constraints"]["gpu_started"] is False
