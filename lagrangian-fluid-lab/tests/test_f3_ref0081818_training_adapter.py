"""Fail-closed checks for the ref0081818 training contract boundary."""

import json

import pytest

from scripts import f3_ref0081818_development as revision_development
from scripts import f3_ref0081818_training_data as revision_training
from scripts import f3_training_data as legacy_training
from scripts import f3_training_runner as runner


def test_ref008_training_gate_requires_explicit_training_opt_in(monkeypatch):
    gate = {
        "development_launch_allowed": True,
        "training_launch_allowed": False,
    }
    monkeypatch.setattr(revision_development, "verify_revision_gate", lambda: gate)
    with pytest.raises(ValueError, match="training launch"):
        revision_training._require_training_gate()


def test_unknown_contract_recipe_does_not_fall_back_to_legacy(tmp_path):
    path = tmp_path / "contract.json"
    path.write_text(json.dumps({"schema": "f3.training.development_data.v1",
                                "recipe_id": "unregistered"}))
    with pytest.raises(ValueError, match="recipe is not registered"):
        legacy_training.loader_for_contract(path)


def test_runner_routes_ref008_to_revision_gate_and_validator(monkeypatch, tmp_path):
    domain = {
        "schema": "f3.revision075.ref0081818.gate.v1",
        "recipe_id": revision_training.RECIPE,
        "status": "passed",
        "development_launch_allowed": True,
        "training_launch_allowed": True,
        "production_resolution_m": 0.0075,
        "time_window_s": [0.0, 8.35],
        "scoring_interval_s": 0.01,
    }
    monkeypatch.setattr(revision_development, "verify_revision_gate", lambda: domain)
    validated = {
        "schema": revision_training.SCHEMA,
        "status": "passed",
        "qualified_sources": True,
        "recipe_id": revision_training.RECIPE,
        "production_resolution_m": 0.0075,
        "scope": "pilot",
        "source_domain_gate": None,
    }
    monkeypatch.setattr(revision_training, "validate_development_contract",
                        lambda path: validated)
    monkeypatch.setattr(runner, "LAB", tmp_path)
    domain_path = tmp_path / "gate.json"
    development_path = tmp_path / "development.json"
    domain_path.write_text(json.dumps(domain))
    development_path.write_text(json.dumps(validated))
    qualification = {
        "path": str(domain_path),
        "sha256": runner._sha256(domain_path),
        "content": domain,
    }
    development = {
        "path": str(development_path),
        "sha256": runner._sha256(development_path),
        "content": {**validated, "source_domain_gate": {
            "path": "gate.json", "sha256": qualification["sha256"]}},
    }
    validated = development["content"]
    result = runner._require_production_contracts(qualification, development)
    assert result["domain"] == domain
    assert result["development"]["recipe_id"] == revision_training.RECIPE
