from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f3_t2_source_closure_audit_v1 import (
    INPUTS,
    SCHEMA,
    build_audit,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "campaigns/core-v1/material/evidence/"
    "f3-t2-source-closure-audit-v1-20260922.json"
)
REPORT = ROOT / "reports/F3-T2-SOURCE-CLOSURE-AUDIT-2026-09-22.zh-CN.md"


def test_rows_28_32_have_metadata_lineage_but_no_acceptance_receipts() -> None:
    value = build_audit(ROOT)
    rows = value["rows_28_32"]
    assert value["schema"] == SCHEMA
    assert value["status"] == "source_closure_blocked"
    assert value["T2_macro"] is False
    assert value["T2_path"] is False
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert rows["summary"] == {
        "exact_lineage_present": True,
        "full_source_window_declared": True,
        "native_cadence_declared": True,
        "independent_source_window_receipt": False,
        "per_source_unknown_receipt": False,
        "per_source_cdf_receipt": False,
        "per_source_residence_cdf_receipt": False,
        "source_side_closure_pass": False,
        "qualification_credit": 0,
    }
    for row in ("28", "32"):
        assert rows["rows"][row]["exact_lineage"] is True
        assert rows["rows"][row]["declared_source_window"]["full_window"] is True
        assert rows["rows"][row]["declared_native_cadence"]["pass"] is True
        assert rows["rows"][row]["source_side_closure_pass"] is False
        assert rows["rows"][row]["qualification_credit"] == 0


def test_row24_terminalization_is_legal_engineering_receipt_only() -> None:
    value = build_audit(ROOT)
    row = value["row24_terminalization"]
    assert row["execution_status"] == "succeeded"
    assert row["terminalization_receipt"] is True
    assert row["legal_terminalization"] is True
    assert row["diagnostic_only"] is True
    assert row["qualification_claim"].startswith("none")
    assert row["qualification_credit"] == 0
    assert row["source_window"]["frames"] == 4176
    assert row["source_window"]["full_window"] is True
    assert row["native_cadence"]["pass"] is True
    assert row["checkpoint"]["committed_frame"] == 4175
    assert row["cdf_receipt"] is False
    assert row["residence_cdf_receipt"] is False
    assert row["material_acceptance_pass"] is False


def test_missing_source_list_is_exact_and_root_owned() -> None:
    value = build_audit(ROOT)
    items = value["missing_root_owned_cfd_sources"]["items"]
    assert [item["matrix_row"] for item in items] == [
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        26,
        27,
        29,
        31,
    ]
    assert all(item["root_owned_cfd_source_required"] for item in items)
    assert all(item["source_template_is_not_output"] for item in items)
    assert all(item["qualification_credit"] == 0 for item in items)
    assert items[-2]["source_asset_id"] == "f3_production_amp0p95_native010"
    assert items[-1]["source_asset_id"] == "f3_production_amp1p05_native010"
    assert value["missing_root_owned_cfd_sources"]["source_template_substitution_forbidden"] is True


def test_audit_is_read_only_and_artifact_binds_inputs() -> None:
    assert EVIDENCE.is_file()
    assert REPORT.is_file()
    value = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert value["schema"] == SCHEMA
    cpu = value["cpu_only_source_audit"]
    assert cpu["performed"] is False
    assert cpu["invocation_count"] == 0
    assert cpu["hdf5_opened"] is False
    assert cpu["solver_started"] is False
    assert cpu["gpu_started"] is False
    boundary = value["bridge_boundary"]
    assert boundary["registry_mutation"] == 0
    assert boundary["ledger_mutation"] == 0
    assert boundary["matrix_mutation"] == 0
    assert boundary["denominator_mutation"] == 0
    assert boundary["threshold_mutation"] == 0
    assert boundary["prior_evidence_overwritten"] is False
    assert "T2 macro/path 均为 `false`" in REPORT.read_text(encoding="utf-8")
    assert set(INPUTS) == set(value["input_bindings"])
    for name, binding in value["input_bindings"].items():
        path = ROOT / binding["path"]
        assert path.is_file(), name
        assert path.stat().st_size == binding["bytes"], name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"], name
