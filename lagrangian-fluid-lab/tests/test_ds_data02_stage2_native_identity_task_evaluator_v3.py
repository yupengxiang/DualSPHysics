from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_native_identity_task_evaluator_v3.py"
SPEC = importlib.util.spec_from_file_location("native_identity_task_evaluator_v3", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _row(case_key: str, idp: int, *, motive: str = "position", code: int = 1, cause: str = "NATIVE_PARTVTKOUT_POSITION_EXCLUSION") -> dict:
    return {"case_key": case_key, "family_id": "F2", "idp": idp, "native_motive": motive, "native_motive_code": code, "numerical_cause": cause}


def test_exact_ordered_join_passes_for_source_rows():
    source = [_row("F2/A", 7), _row("F2/B", 7)]
    assert MODULE.join_source_records(source, source, expected_count=2)["ordered_case_qualified_join"] is True


def test_count_preserving_same_family_case_key_swap_is_rejected():
    source = [_row("F2/A", 7), _row("F2/B", 7)]
    swapped = [_row("F2/B", 7), _row("F2/A", 7)]
    with pytest.raises(MODULE.EvaluationError, match="order"):
        MODULE.join_source_records(swapped, source, expected_count=2)


def test_key_set_change_is_rejected_even_when_count_is_preserved():
    source = [_row("F2/A", 7), _row("F2/B", 8)]
    wrong = [_row("F2/A", 7), _row("F2/C", 8)]
    with pytest.raises(MODULE.EvaluationError, match="key sets"):
        MODULE.join_source_records(wrong, source, expected_count=2)


def test_same_family_cause_mutation_is_rejected():
    source = [_row("F2/A", 7), _row("F2/B", 8)]
    wrong = [_row("F2/A", 7), _row("F2/B", 8, motive="density", code=2, cause="NATIVE_PARTVTKOUT_DENSITY_EXCLUSION")]
    with pytest.raises(MODULE.EvaluationError, match="native_motive"):
        MODULE.join_source_records(wrong, source, expected_count=2)
