from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_native_identity_task_loader_v1.py"
SPEC = importlib.util.spec_from_file_location("native_identity_task_loader_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _row(case_key: str, idp: int, *, motive: str = "position", code: int = 1, cause: str = "NATIVE_PARTVTKOUT_POSITION_EXCLUSION") -> dict:
    return {
        "case_key": case_key,
        "family_id": "F2",
        "physical_case_id": "F2_CASE",
        "idp": idp,
        "mk": 1,
        "type": 3,
        "native_motive": motive,
        "native_motive_code": code,
        "numerical_cause": cause,
        "first_missing_bracket_s": [1.0, 1.1],
    }


def test_case_qualified_identity_allows_global_idp_collision_and_reports_it():
    result = MODULE.validate_records([_row("F2/A", 7), _row("F2/B", 7)], expected_count=2)
    assert result["case_qualified_unique"] is True
    assert result["global_idp_unique"] is False
    assert result["global_idp_collision_count"] == 1


def test_duplicate_case_qualified_identity_is_rejected():
    with pytest.raises(MODULE.LoaderError, match="duplicate case-qualified"):
        MODULE.validate_records([_row("F2/A", 7), _row("F2/A", 7)], expected_count=2)


def test_motive_code_and_cause_mismatch_is_rejected():
    with pytest.raises(MODULE.LoaderError, match="motive/code/cause"):
        MODULE.validate_records([_row("F2/A", 7, motive="density", code=2, cause="NATIVE_PARTVTKOUT_POSITION_EXCLUSION")], expected_count=1)


def test_unknown_physical_task_is_rejected_before_source_read(tmp_path: Path):
    with pytest.raises(MODULE.LoaderError, match="remains UNKNOWN"):
        MODULE.load_task(tmp_path / "does-not-exist.json", "physical_fate")


def test_finite_task_fields_are_explicit():
    records = [_row("F2/A", 7), _row("F2/B", 8)]
    assert MODULE.task_records(records, "native_motive")[0]["numerical_cause"] == "NATIVE_PARTVTKOUT_POSITION_EXCLUSION"
    with pytest.raises(MODULE.LoaderError, match="not an eligible finite"):
        MODULE.task_records(records, "continuous_event")
