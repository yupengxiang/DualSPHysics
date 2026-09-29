"""Fail-closed tests for residual seed43 authority projection.

All fixtures are tiny local JSON envelopes.  They are not scheduler
authority, do not read production checkpoints/HDF5, and never start a process.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f3_graph_residual_hidden16_seed43_authority_projection_gap_v1 as projection
from scripts import f3_graph_residual_hidden16_seed43_diagnostic_admission_v1 as admission


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _legacy_receipt(path: Path) -> dict[str, object]:
    identity: dict[str, object] = {
        "model_kind": "graph_residual",
        "hidden": 16,
        "updates": 500,
        "seed": 43,
        "case_id": "F3_DEV_00_a0p903125",
        "split": "test",
        "transitions": 835,
        "frames": 836,
        "run_id": admission.RUN_ID,
        # The rest of the producer-bound identity is intentionally absent.
    }
    receipt: dict[str, object] = {
        "schema": admission.SCHEMA,
        "status": "issued",
        "receipt_version": 1,
        "report_id": admission.REPORT_ID,
        "identity": identity,
        "identity_sha256": projection.canonical_digest(identity),
        "namespace_marker": {},
        "receipt_path": str(path),
        "consumption": {},
        "diagnostic_execute_only": True,
        "terminal_receipt_minting": False,
        **projection.ZERO_CREDIT,
    }
    receipt["receipt_sha256"] = projection.canonical_digest(receipt)
    return receipt


def test_missing_source_receipt_is_a_zero_credit_gap(tmp_path: Path) -> None:
    report = projection.build_report(tmp_path / "missing-receipt.json")

    assert report["status"] == "blocked_projection_gap"
    assert report["source_observed"] is False
    assert report["external_authority"]["verified"] is False
    assert report["runner_consumable"] is False
    assert report["popen_allowed"] is False
    assert report["credit"] == 0
    assert projection.validate_report(report) == []


def test_legacy_receipt_reports_non_projectable_fields_without_repair(tmp_path: Path) -> None:
    path = tmp_path / "legacy-receipt.json"
    original = _legacy_receipt(path)
    _write_json(path, original)

    report = projection.build_report(path)

    assert report["status"] == "blocked_projection_gap"
    assert "authority" in report["projectable_missing_fields"]
    assert "identity.plan_sha256" in report["non_projectable_missing_fields"]
    assert report["historical_receipt_rewritten"] is False
    assert report["durable_receipt_written"] is False
    assert report["credit"] == 0
    assert projection.validate_report(report) == []
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_projection_requires_real_external_authority_even_for_complete_shape(tmp_path: Path) -> None:
    # Add every required key with harmless placeholders so the test reaches
    # the external-authority boundary without opening a checkpoint or HDF5.
    path = tmp_path / "candidate-receipt.json"
    receipt = _legacy_receipt(path)
    identity = receipt["identity"]
    assert isinstance(identity, dict)
    for key in projection.REQUIRED_IDENTITY_FIELDS:
        identity.setdefault(key, {})
    consumption = receipt["consumption"]
    assert isinstance(consumption, dict)
    for key in projection.REQUIRED_CONSUMPTION_FIELDS:
        consumption.setdefault(key, {})
    identity.update(
        {
            "model_kind": "graph_residual",
            "hidden": 16,
            "updates": 500,
            "seed": 43,
            "case_id": "F3_DEV_00_a0p903125",
            "split": "test",
            "transitions": 835,
            "frames": 836,
            "run_id": admission.RUN_ID,
        }
    )
    receipt["identity_sha256"] = projection.canonical_digest(identity)
    receipt.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = projection.canonical_digest(receipt)
    _write_json(path, receipt)

    with pytest.raises(projection.ProjectionGap, match="external scheduler authority"):
        projection.project_authority(receipt, external_authority=None, resource_admission=None)


def test_existing_authority_cannot_be_promoted_or_mutated(tmp_path: Path) -> None:
    path = tmp_path / "forged-receipt.json"
    receipt = _legacy_receipt(path)
    forged = copy.deepcopy(receipt)
    forged["authority"] = {
        "schema": admission.AUTHORITY_SCHEMA,
        "receipt_authorizes_popen": False,
        "diagnostic_execute_allowed": False,
        "launch_allowed": True,
        "formal_promotion_allowed": False,
        "credit_promotion_allowed": False,
        "external_gate_required": True,
        "formal_state_touched": False,
        "credit": 1,
    }
    forged.pop("receipt_sha256", None)
    forged["receipt_sha256"] = projection.canonical_digest(forged)

    with pytest.raises(projection.ProjectionError, match="receipt.authority"):
        projection.project_authority(forged, external_authority=None, resource_admission=None)


@pytest.mark.parametrize("field", ["credit", "popen_allowed", "runner_consumable"])
def test_report_validator_rejects_promotion_fields(tmp_path: Path, field: str) -> None:
    report = projection.build_report(tmp_path / "missing.json")
    mutated = copy.deepcopy(report)
    mutated[field] = 1 if field == "credit" else True
    assert projection.validate_report(mutated)


def test_contract_inventory_is_seed43_scoped() -> None:
    assert set(admission.SOURCE_RELATIVE_PATHS).issubset(set(projection.CONTRACT_RELATIVE_PATHS))
    assert {"admission", "runner"}.issubset(set(projection.CONTRACT_RELATIVE_PATHS))
    assert all("seed17" not in str(path) for path in projection.CONTRACT_RELATIVE_PATHS.values())
    assert projection.CONTRACT_RELATIVE_PATHS["admission"].name == (
        "f3_graph_residual_hidden16_seed43_diagnostic_admission_v1.py"
    )


def test_cli_contract_does_not_offer_execution_alias() -> None:
    parsed = projection._parse_args(["--receipt", "/tmp/receipt.json"])
    assert parsed.receipt == Path("/tmp/receipt.json")
    assert not hasattr(parsed, "execute")
