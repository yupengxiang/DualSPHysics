from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f8_r008_target_kernel_source_build_runtime_pin_readiness_inventory_v1 as inventory


LAB = Path(__file__).parents[1]
REPORT = LAB / inventory.DEFAULT_REPORT


def test_live_inventory_is_blocked_without_external_pin_inputs() -> None:
    report = inventory.build_report()

    assert report["status"] == inventory.STATUS
    assert report["audit_mode"] == "live_repository_contract_only_no_v7_v8_revalidation"
    assert report["historical_revalidation"] == {
        "v7_revalidated": False,
        "v8_revalidated": False,
        "reason": "only current live source, manifest boundary, and target contract were inspected",
    }
    assert report["pin_inventory"]["open_count"] == 51
    assert report["pin_inventory"]["closed_count"] == 0
    assert all(row["closed"] is False for row in report["pin_inventory"]["rows"])
    assert report["minimal_unit"]["can_advance"] is False
    assert report["authorization"]["readiness_pass"] is False
    assert report["authorization"]["T1_numerical"] is False
    assert report["authorization"]["qualification_credit"] == 0


def test_current_external_paths_and_contract_sources_are_exactly_bound() -> None:
    report = inventory.build_report()
    external = report["external_inputs"]

    assert external["target_kernel_manifest"] == {
        **external["target_kernel_manifest"],
        "path": inventory.MANIFEST_PATH,
        "exists": False,
        "regular": False,
        "bytes": None,
        "sha256": None,
        "error": "missing",
    }
    assert external["trusted_pin_attestation"]["path"] == inventory.ATTESTATION_PATH
    assert external["trusted_pin_attestation"]["exists"] is False
    assert external["independent_trust_anchor"]["path"] == inventory.TRUST_ANCHOR_PATH
    assert external["independent_trust_anchor"]["exists"] is False
    assert all(item["exists"] and item["sha256"] for item in report["live_contracts"])
    assert report["target_contract"]["scope"]["scope_id"] == inventory.SCOPE_ID


def test_checked_in_report_is_deterministic_and_verifies() -> None:
    expected = inventory.build_report()
    checked_in = json.loads(REPORT.read_text(encoding="utf-8"))

    assert checked_in == expected
    assert inventory.verify_report(REPORT) == expected


def test_promoting_one_pin_row_is_rejected() -> None:
    value = inventory.build_report()
    mutated = copy.deepcopy(value)
    mutated["pin_inventory"]["rows"][0]["closed"] = True

    with pytest.raises(inventory.InventoryError, match="differs from current live-contract state"):
        inventory.validate_report(mutated)


def test_execution_and_mutation_boundaries_remain_closed() -> None:
    report = inventory.build_report()

    assert report["side_effects"]["external_pin_inputs_read"] is False
    assert report["side_effects"]["target_source_read"] is False
    assert report["side_effects"]["target_build_read"] is False
    assert report["side_effects"]["native_started"] is False
    assert report["side_effects"]["solver_started"] is False
    assert report["side_effects"]["worker_started"] is False
    assert report["side_effects"]["gpu_started"] is False
    assert report["side_effects"]["queue_started"] is False
    assert all(value == 0 for key, value in report["side_effects"].items() if key.endswith("_mutation"))
    assert report["non_changes"][-3:] == ["F3 files", "F4 files", "A8 files"]
