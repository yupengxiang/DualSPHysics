from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_scientific_scan_detail_v2.py"
SPEC = importlib.util.spec_from_file_location("scientific_scan_detail_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def manifest() -> dict:
    cases = []
    for index in range(336):
        family = f"F{index // 48 + 1}"
        physical = f"CASE_{index:03d}"
        cases.append({
            "case_key": f"{family}/{physical}",
            "family_id": family,
            "physical_case_id": physical,
            "current_index": index,
            "trajectory": {"path": f"/declared/{index}.h5", "sha256": "a" * 64},
            "scan": {"path": f"/declared/{index}-scan.json", "sha256": "b" * 64},
            "receipt": {"path": f"/declared/{index}-receipt.json", "sha256": "c" * 64},
        })
    return {
        "schema": MODULE.MANIFEST_SCHEMA,
        "case_count": 336,
        "trajectory_read_policy": "json_only_no_h5_bi4_raw_solver",
        "cases": cases,
    }


def test_v2_accepts_manifest_and_preserves_current_index_contract():
    entries = MODULE.validate_manifest_dict(manifest())
    assert entries[17]["current_index"] == 17


def test_v2_rejects_manifest_index_drift_without_reading_sources():
    value = manifest()
    value["cases"][10]["current_index"] = 11
    with pytest.raises(MODULE.DetailContractError):
        MODULE.validate_manifest_dict(value)


def test_authoritative_current_order_supplies_index_when_case_has_no_index():
    current = {"cases": [{"family_id": "F1", "physical_case_id": f"CASE_{i:03d}"} for i in range(336)]}
    by_key, positions = MODULE._authoritative_current_order(current)
    assert positions["F1/CASE_000"] == 0
    assert positions["F1/CASE_335"] == 335
    assert by_key["F1/CASE_004"]["physical_case_id"] == "CASE_004"


def test_authoritative_current_order_rejects_duplicate_identity():
    current = {"cases": [{"family_id": "F1", "physical_case_id": f"CASE_{i:03d}"} for i in range(336)]}
    current["cases"][1]["physical_case_id"] = "CASE_000"
    with pytest.raises(MODULE.DetailContractError):
        MODULE._authoritative_current_order(current)


def test_detail_card_retains_effective_list_position_and_unknown_boundary():
    entry = manifest()["cases"][0]
    current = {"family_id": "F1", "physical_case_id": "CASE_000", "frames": 1, "particles": 1, "actual_time_window_s": [0.0, 0.0]}
    scan = {"failures": [], "missing_id_records": [], "type_ledgers": {}}
    receipt = {"status": "completed"}
    card = MODULE._detail_card(entry=entry, current=current, current_list_index=0, scan=scan, receipt=receipt, scan_sha="b" * 64, receipt_sha="c" * 64)
    assert card["current_identity"]["current_index"] is None
    assert card["current_identity"]["current_list_index"] == 0
    assert card["claim_boundary"]["physical_fate"] == "UNKNOWN"
