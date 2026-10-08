from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_scientific_scan_detail_v1.py"
SPEC = importlib.util.spec_from_file_location("scientific_scan_detail_v1", SCRIPT)
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


def current_case() -> dict:
    return {
        "family_id": "F1",
        "physical_case_id": "CASE_000",
        "current_index": 0,
        "runtime_case_alias": "alias",
        "frames": 2,
        "particles": 3,
        "actual_time_window_s": [0.0, 1.0],
        "known_numeric_physical_parameters": {},
    }


def entry() -> dict:
    return manifest()["cases"][0]


def scan() -> dict:
    return {
        "schema": MODULE.SCAN_SCHEMA,
        "trajectory": "/declared/0.h5",
        "family_id": "F1",
        "physical_case_id": "CASE_000",
        "source_bytes": 123,
        "source_mtime_ns": 4,
        "full_saved_timeline_scanned": True,
        "frames": 2,
        "particles": 3,
        "time_s": [0.0, 1.0],
        "metadata": {"units": {"mass": "kg"}, "identity_key": "(Zone,Idp)"},
        "type_ledgers": {"fluid": {"typed_initial_count": 2, "active_count": [2, 1]}, "fixed": {"typed_initial_count": 1, "active_count": [1, 1]}},
        "missing_id_records": [{"frame": 1, "count": 1}],
        "macros": [{"frame": 0}, {"frame": 1}],
        "failures": [],
        "scan_status": "SCANNED",
        "raw_native_alignment": "NOT_ASSESSED",
        "QI_dynamics": "NOT_ASSESSED",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "input_hash_verification": "receipt-bound",
        "wall_seconds": 1.0,
        "peak_rss_kib": 1,
    }


def receipt() -> dict:
    return {
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "output_root": "/declared",
        "command": ["python", "--case-id", "CASE_000"],
        "input_hashes_at_launch": {"/declared/0.h5": "a" * 64},
        "input_hashes_after_run": {"/declared/0.h5": "a" * 64},
    }


def test_manifest_structure_requires_all_336_unique_cases_without_opening_files():
    entries = MODULE.validate_manifest_dict(manifest())
    assert len(entries) == 336
    assert entries[0]["case_key"] == "F1/CASE_000"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["cases"].pop(),
        lambda value: value["cases"][1].update({"case_key": "F1/CASE_000"}),
        lambda value: value.update({"trajectory_read_policy": "open_h5"}),
        lambda value: value["cases"][0]["scan"].update({"sha256": "bad"}),
    ],
)
def test_manifest_rejects_count_identity_policy_or_digest_drift(mutator):
    value = manifest()
    mutator(value)
    with pytest.raises(MODULE.DetailContractError):
        MODULE.validate_manifest_dict(value)


def test_scan_receipt_contract_binds_json_identity_and_h5_digest_without_opening_h5():
    MODULE._validate_scan_and_receipt(entry=entry(), current=current_case(), scan=scan(), receipt=receipt())
    bad = copy.deepcopy(receipt())
    bad["input_hashes_after_run"]["/declared/0.h5"] = "d" * 64
    with pytest.raises(MODULE.DetailContractError):
        MODULE._validate_scan_and_receipt(entry=entry(), current=current_case(), scan=scan(), receipt=bad)


def test_detail_card_preserves_lifecycle_fields_and_boundary():
    card = MODULE._detail_card(entry=entry(), current=current_case(), scan=scan(), receipt=receipt(), scan_sha="b" * 64, receipt_sha="c" * 64)
    assert card["scientific_scan"]["type_ledgers"]["fluid"]["active_count"] == [2, 1]
    assert card["scientific_scan"]["missing_id_records"] == [{"frame": 1, "count": 1}]
    assert card["scientific_scan"]["failures"] == []
    assert card["claim_boundary"]["physical_fate"] == "UNKNOWN"
    assert card["claim_boundary"]["trajectory_h5_opened_by_collector"] is False
