from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from scripts import f8_r008_untrusted_pin_blocker_inventory_v1 as contract


LAB = Path(__file__).parents[1]
REPORT_PATH = LAB / "reports/f8_r008_untrusted_pin_blocker_inventory_v1_report.json"


def _checked_in_report() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_inventory_has_exact_open_target_and_runtime_blocker_sets() -> None:
    report = contract.build_report()

    assert report["status"] == contract.STATUS
    assert report["inventory_mode"] == contract.INVENTORY_MODE
    assert report["source_and_runtime_claims"] == {
        "all_claims_untrusted": True,
        "synthetic_fixture_only": True,
        "external_evidence_consumed": False,
        "runtime_evidence_consumed": False,
        "promotion_surface": "none",
    }
    assert report["target_kernel_source_build"]["open_count"] == 6
    assert report["target_kernel_source_build"]["closed_count"] == 0
    assert report["trusted_runtime"]["open_count"] == 6
    assert report["trusted_runtime"]["closed_count"] == 0
    assert len(report["blockers"]) == 12
    assert report["blockers"][0]["code"] == "target_kernel_identity_pin_incomplete"
    assert report["blockers"][-1]["code"] == "target_kernel_runtime_conformance_missing"


def test_all_rows_remain_untrusted_and_unverified() -> None:
    report = contract.build_report()
    rows = (report["target_kernel_source_build"]["rows"]
            + report["trusted_runtime"]["rows"])

    assert len(rows) == 12
    assert all(row["claim_origin"] == "synthetic_fixture" for row in rows)
    assert all(row["trust"] == "untrusted" for row in rows)
    assert all(row["declared_value"] is None for row in rows)
    assert all(row["external_evidence_present"] is False for row in rows)
    assert all(row["runtime_verified"] is False for row in rows)
    assert all(row["closed"] is False for row in rows)


def test_checked_in_report_matches_deterministic_contract() -> None:
    expected = contract.build_report()
    checked_in = _checked_in_report()

    assert checked_in == expected
    assert contract.verify_report() == expected
    assert contract.validate_report(checked_in) == checked_in


@pytest.mark.parametrize("path", [
    ("target_kernel_source_build", "rows", 0, "trust"),
    ("target_kernel_source_build", "rows", 1, "closed"),
    ("trusted_runtime", "rows", 2, "runtime_verified"),
])
def test_promotion_attempts_fail_closed(path: tuple[str, str, int, str]) -> None:
    promoted = copy.deepcopy(contract.build_report())
    section, rows_key, index, field = path
    promoted[section][rows_key][index][field] = {
        "trust": "trusted",
        "closed": True,
        "runtime_verified": True,
    }[field]

    with pytest.raises(contract.UntrustedPinBlockerInventoryError, match="promoted"):
        contract.validate_report(promoted)


def test_missing_or_unknown_blocker_row_fails_closed() -> None:
    missing = copy.deepcopy(contract.build_report())
    missing["trusted_runtime"]["rows"].pop()
    with pytest.raises(contract.UntrustedPinBlockerInventoryError, match="row count"):
        contract.validate_report(missing)

    unknown = copy.deepcopy(contract.build_report())
    unknown["target_kernel_source_build"]["rows"][0]["unexpected"] = True
    with pytest.raises(contract.UntrustedPinBlockerInventoryError, match="fields differ"):
        contract.validate_report(unknown)


def test_report_and_inputs_are_not_mutated() -> None:
    report = contract.build_report()
    before = copy.deepcopy(report)
    result = contract.validate_report(report)

    assert report == before
    assert result == before
    assert result is not report


def test_module_has_no_execution_or_production_read_surface() -> None:
    source = inspect.getsource(contract)
    for forbidden in (
        "subprocess",
        "os.system",
        "Popen",
        "nvidia-smi",
        "CUDA_VISIBLE_DEVICES",
        "import torch",
        "h5py",
        "fanotify_init",
        "ctypes",
        "open(",
        "Path.read_text",
    ):
        assert forbidden not in source
