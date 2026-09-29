from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f8_r008_target_kernel_pin_authority_reconciliation_v1 as reconciliation


LAB = Path(__file__).parents[1]
REPORT = LAB / reconciliation.DEFAULT_REPORT


def _fixture_values() -> dict[str, str]:
    return {
        "kernel_release": "6.8.0-target-synthetic",
        "source_commit": "a" * 40,
        "source_tree_sha256": "b" * 64,
        "uapi_sha256": "c" * 64,
        "config_sha256": "d" * 64,
        "build_id": "e" * 64,
    }


def _fixture_records() -> tuple[dict, dict, dict]:
    values = _fixture_values()
    local = {
        "origin": "local_observation",
        "synthetic": True,
        "verified": False,
        "values": values,
    }
    target = {
        "origin": "synthetic_fixture",
        "synthetic": True,
        "verified": False,
        "values": dict(values),
    }
    trusted = {
        "origin": "synthetic_fixture",
        "synthetic": True,
        "verified": False,
        "values": dict(values),
    }
    return local, target, trusted


def test_default_reconciliation_keeps_local_observations_non_authoritative() -> None:
    report = reconciliation.build_report()

    assert report["status"] == reconciliation.STATUS
    assert report["contract_role"] == "value_level_cross_contract_reconciliation_non_authorizing"
    assert report["authority_separation"] == {
        "local_observation_is_authority": False,
        "caller_claim_is_authority": False,
        "synthetic_fixture_is_authority": False,
        "manifest_status_alone_is_authority": False,
        "trusted_intake_status_alone_is_runtime_authority": False,
        "full_value_projection_required_for_comparison": True,
        "independent_runtime_measurement_required": True,
        "independent_consume_path_required": True,
    }
    rows = {row["pin"]: row for row in report["pin_reconciliation"]}
    assert rows["kernel_release"]["state"] == "local_observation_not_external_pin"
    assert rows["config_sha256"]["state"] == "local_observation_not_external_pin"
    assert rows["uapi_sha256"]["state"] == "local_sample_only_not_external_pin"
    assert rows["source_commit"]["state"] == "external_authority_missing"
    assert rows["build_id"]["state"] == "external_authority_missing"
    assert all(row["accepted_as_authority"] is False for row in rows.values())
    assert report["summary"]["cross_contract_match_count"] == 0
    assert report["authorization"] == reconciliation.AUTHORIZATION


def test_matching_synthetic_values_are_diagnostic_only() -> None:
    local, target, trusted = _fixture_records()

    result = reconciliation.reconcile_synthetic_fixture(
        local_observation=local,
        target_manifest=target,
        trusted_authority=trusted,
    )

    assert result["synthetic_only"] is True
    assert result["authority_minted"] is False
    assert result["decision"] == "diagnostic_non_authorizing"
    assert {row["state"] for row in result["rows"]} == {"values_match_but_untrusted"}
    assert all(row["accepted_as_authority"] is False for row in result["rows"])
    assert result["authorization"] == reconciliation.AUTHORIZATION


def test_synthetic_target_authority_drift_is_rejected() -> None:
    local, target, trusted = _fixture_records()
    trusted["values"]["build_id"] = "f" * 64

    result = reconciliation.reconcile_synthetic_fixture(
        local_observation=local,
        target_manifest=target,
        trusted_authority=trusted,
    )

    build_row = next(row for row in result["rows"] if row["pin"] == "build_id")
    assert result["decision"] == "reject_drift"
    assert build_row["state"] == "cross_contract_drift_fail_closed"
    assert build_row["accepted_as_authority"] is False


def test_caller_or_local_spoof_claim_is_rejected() -> None:
    local, target, trusted = _fixture_records()
    spoofed = copy.deepcopy(trusted)
    spoofed["origin"] = "caller_claim"
    spoofed["verified"] = True

    with pytest.raises(reconciliation.ReconciliationError, match="caller-supplied verified claim"):
        reconciliation.reconcile_synthetic_fixture(
            local_observation=local,
            target_manifest=target,
            trusted_authority=spoofed,
        )


def test_report_rejects_authority_promotion_and_report_drift() -> None:
    value = copy.deepcopy(reconciliation.build_report())
    value["authorization"]["qualification_credit"] = 1
    with pytest.raises(reconciliation.ReconciliationError, match="current bounded inputs|authorization"):
        reconciliation.validate_report(value)

    value = copy.deepcopy(reconciliation.build_report())
    value["pin_reconciliation"][0]["accepted_as_authority"] = True
    with pytest.raises(reconciliation.ReconciliationError, match="current bounded inputs|authorization"):
        reconciliation.validate_report(value)


def test_checked_in_report_is_deterministic_and_verifies() -> None:
    expected = reconciliation.build_report()
    assert json.loads(REPORT.read_text(encoding="utf-8")) == expected
    assert reconciliation.verify_report(REPORT) == expected
    assert expected["side_effects"] == reconciliation.SIDE_EFFECTS
    assert expected["read_policy"] == reconciliation.READ_POLICY
