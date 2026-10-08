from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_native_identity_task_evaluator_v2.py"
SPEC = importlib.util.spec_from_file_location("native_identity_task_evaluator_v2", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _records() -> list[dict]:
    records = []
    specs = [("F2", "position", 1078), ("F4", "density", 51), ("F6", "position", 199)]
    idp = 0
    for family, motive, count in specs:
        code, cause = MODULE.CAUSE_BY_MOTIVE[motive]
        for index in range(count):
            records.append({
                "case_key": f"{family}/case-{index // 3}", "family_id": family, "idp": idp,
                "native_motive": motive, "native_motive_code": code, "numerical_cause": cause,
            })
            idp += 1
    return records


def test_actual_family_motive_counts_and_case_qualified_identity():
    result = MODULE.validate_native_motive_records(_records())
    assert result["row_count"] == 1328
    assert result["family_motive_counts"] == MODULE.EXPECTED_FAMILY_MOTIVE
    assert result["case_qualified_unique"] is True


def test_wrong_motive_code_is_rejected():
    rows = _records()
    rows[0]["native_motive_code"] = 2
    with pytest.raises(MODULE.EvaluationError, match="motive/code/cause"):
        MODULE.validate_native_motive_records(rows)


def test_duplicate_case_qualified_identity_is_rejected():
    rows = _records()
    rows[1]["case_key"] = rows[0]["case_key"]
    rows[1]["idp"] = rows[0]["idp"]
    with pytest.raises(MODULE.EvaluationError, match="duplicate case-qualified"):
        MODULE.validate_native_motive_records(rows)


def test_unknown_boundary_cannot_be_widened():
    qualification = {"physical_fate": "PASS", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN_BEYOND_SAVED_BRACKET", "dynamical_impact": "UNKNOWN", "scientific_split_safe": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    with pytest.raises(MODULE.EvaluationError, match="UNKNOWN boundary"):
        MODULE._unknown_boundary(qualification)
