"""Tests for the static/synthetic Core physical-material metric contract."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.core_metrics_contract import (
    DEFAULT_CONTRACT,
    DEFAULT_RECEIPT,
    FIXTURE_SCHEMA,
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


def test_committed_planning_receipt_is_hash_bound_and_zero_credit() -> None:
    report = verify_receipt(DEFAULT_RECEIPT, root=ROOT, contract_path=DEFAULT_CONTRACT)
    assert report["ok"] is True
    receipt = json.loads(DEFAULT_RECEIPT.read_text(encoding="utf-8"))
    assert receipt["qualification_claim"] == "none"
    assert receipt["credit"] == 0
    assert receipt["synthetic_report"]["status"] == "evaluated"
    assert receipt["synthetic_report"]["negative_result"] is True


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
