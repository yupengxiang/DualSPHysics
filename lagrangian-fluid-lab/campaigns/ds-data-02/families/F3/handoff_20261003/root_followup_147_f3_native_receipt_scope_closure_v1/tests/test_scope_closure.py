#!/usr/bin/env python3
"""Metadata-only smoke/regression tests for fresh147."""

from pathlib import Path
import importlib.util


HERE = Path(__file__).resolve().parents[1]
VALIDATOR = HERE / "metadata" / "validate_scope_closure.py"


def _load():
    spec = importlib.util.spec_from_file_location("fresh147_validator", VALIDATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metadata_closure_and_known_role_regressions():
    validator = _load()
    report = validator.load_and_validate()
    validator.synthetic_contract_tests(report)
