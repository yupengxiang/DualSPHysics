"""Tests for the static/synthetic Core physical-material metric contract."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import core_metrics_contract as metrics
from scripts.core_metrics_contract import (
    DEFAULT_CONTRACT,
    DEFAULT_RECEIPT,
    FIXTURE_SCHEMA,
    HISTORICAL_CONTRACT,
    HISTORICAL_RECEIPT,
    METRIC_DEFINITIONS,
    _synthetic_fixture,
    evaluate_fixture,
    validate_fixture,
    verify_contract,
    verify_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def test_schema_covers_requested_physical_and_material_metrics() -> None:
    assert set(METRIC_DEFINITIONS) == {
        "kinetic_energy", "geometry_aware_field", "material_transfer",
        "first_passage", "residence", "return", "unknown_bound",
    }
    assert all(spec["fixed_denominator"] for spec in METRIC_DEFINITIONS.values())


def test_committed_planning_receipt_fails_closed_when_source_binding_is_stale() -> None:
    report = verify_receipt(DEFAULT_RECEIPT, root=ROOT, contract_path=DEFAULT_CONTRACT)
    assert report["ok"] is False
    assert report["credit"] == 0
    assert any(item.startswith("contract.source_closure.source_bindings[")
               for item in report["mismatches"])
    receipt = json.loads(DEFAULT_RECEIPT.read_text(encoding="utf-8"))
    assert receipt["qualification_claim"] == "none"
    assert receipt["credit"] == 0
    assert receipt["synthetic_report"]["status"] == "evaluated"
    assert receipt["synthetic_report"]["negative_result"] is True


def test_historical_planning_bundle_is_preserved_but_stale_against_current_source() -> None:
    assert HISTORICAL_CONTRACT.is_file()
    assert HISTORICAL_RECEIPT.is_file()
    report = verify_receipt(HISTORICAL_RECEIPT, root=ROOT, contract_path=HISTORICAL_CONTRACT)
    assert report["ok"] is False
    assert any(item.startswith("contract.source_closure.source_bindings[") for item in report["mismatches"])


def test_receipt_verification_does_not_reparse_after_contract_hash(monkeypatch) -> None:
    original = DEFAULT_CONTRACT.read_bytes()
    original_sha256_file = metrics.sha256_file

    def hash_then_replace(path: str | Path) -> str:
        observed = original_sha256_file(path)
        if Path(path).resolve() == DEFAULT_CONTRACT.resolve():
            forged = json.loads(original.decode("utf-8"))
            forged["status"] = "tampered"
            DEFAULT_CONTRACT.write_text(json.dumps(forged), encoding="utf-8")
        return observed

    monkeypatch.setattr(metrics, "sha256_file", hash_then_replace)
    def verify_contract_probe(contract, *, root):
        if isinstance(contract, (str, Path)):
            contract = metrics._load_json(contract)
        return {"ok": True, "mismatches": [], "status": "planning_only", "credit": 0}

    monkeypatch.setattr(metrics, "verify_contract", verify_contract_probe)
    report = None
    try:
        report = metrics.verify_receipt(
            DEFAULT_RECEIPT, root=ROOT, contract_path=DEFAULT_CONTRACT
        )
    finally:
        DEFAULT_CONTRACT.write_bytes(original)

    assert report is not None
    assert report["ok"] is True


def test_synthetic_fixture_uses_fixed_denominators_and_no_renormalization() -> None:
    fixture = _synthetic_fixture()
    validate_fixture(fixture)
    report = evaluate_fixture(fixture)
    assert report["fixed_denominators"]["source_mass_kg"] == 4.0
    assert report["metric_values"]["material_unknown_fraction"] == pytest.approx(0.005)
    assert report["metric_values"]["unknown_bound_pass"] is True
    assert report["metric_values"]["first_passage_observed_count"] == 3


@pytest.mark.parametrize("mutation", [
    lambda f: f["execution"].update(material_sidecar_present=False),
    lambda f: f["execution"].update(early_failure=True),
    lambda f: f["metrics"]["kinetic_energy"]["values_j"].__setitem__(1, float("nan")),
    lambda f: f["metrics"]["material_transfer"].update(unclassified_mass_kg=1.0),
    lambda f: f["metrics"]["first_passage"].update(right_censored_count=0),
])
def test_bad_or_missing_evidence_fails_closed(mutation) -> None:
    fixture = deepcopy(_synthetic_fixture())
    mutation(fixture)
    report = evaluate_fixture(fixture)
    assert report["status"] == "rejected"
    assert report["credit"] == 0
    assert report["qualification_claim"] == "none"


def test_fixture_schema_mismatch_is_rejected() -> None:
    fixture = _synthetic_fixture()
    fixture["schema"] = "wrong"
    report = evaluate_fixture(fixture)
    assert report["status"] == "rejected"
    assert "fixture schema mismatch" in report["failure_reasons"]


def test_contract_verifier_rejects_metric_or_permission_mutation() -> None:
    contract = json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    contract["metric_definitions"]["kinetic_energy"]["fixed_denominator"] = False
    assert verify_contract(contract, root=ROOT)["ok"] is False
    receipt = json.loads(DEFAULT_RECEIPT.read_text(encoding="utf-8"))
    receipt["execution_constraints"]["gpu_started"] = True
    assert verify_receipt(receipt, root=ROOT, contract_path=DEFAULT_CONTRACT)["ok"] is False


def test_validation_rejects_missing_denominator_without_partial_metric() -> None:
    fixture = _synthetic_fixture()
    del fixture["denominators"]["source_particles"]
    with pytest.raises(ValueError, match="source_particles"):
        validate_fixture(fixture)
