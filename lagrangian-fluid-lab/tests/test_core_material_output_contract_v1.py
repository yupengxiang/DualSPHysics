from __future__ import annotations

from copy import deepcopy
import math

import pytest

from scripts.core_material_output_contract_v1 import (
    PATH_COVERAGE_POLICY,
    SCHEMA,
    UNKNOWN_FRACTION_LIMIT,
    evaluate_material_output,
    validate_material_output,
)


def _event(name: str) -> dict:
    return {
        "definition": f"synthetic {name} event",
        "denominator_policy": "all_initial_mass",
        "cdf": {
            "time_s": [0.0, 1.0, 2.0],
            "lower": [0.0, 0.20, 0.50],
            "upper": [0.0, 0.25, 0.60],
            "denominator_policy": "all_initial_mass",
        },
        "censor": {
            "type": "right",
            "fraction": 0.10,
            "policy": "right_censored_mass_remains_in_denominator",
            "counts_as_acceptance": False,
        },
    }


def _f3_output() -> dict:
    return {
        "schema": SCHEMA,
        "family": "F3",
        "case_id": "synthetic-f3-case",
        "diagnostic_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "mass": {
            "initial_mass_kg": 100.0,
            "closure_tolerance_kg": 1.0e-9,
            "denominator_policy": "all_initial_mass",
            "source": {"mass_kg": 40.0, "fraction": 0.40},
            "destination": {"mass_kg": 59.5, "fraction": 0.595},
            "unknown": {"mass_kg": 0.5, "fraction": 0.005},
        },
        "transfer_matrix": {
            "row_labels": ["source", "destination", "unknown"],
            "column_labels": ["source", "destination", "unknown"],
            "mass_kg": [
                [35.0, 4.5, 0.5],
                [5.0, 54.5, 0.0],
                [0.0, 0.5, 0.0],
            ],
        },
        "events": {
            "first_passage": _event("first-passage"),
            "return": _event("return"),
            "residence": _event("residence"),
        },
        "unknown_bound": {
            "denominator_policy": "all_initial_mass",
            "observed_fraction": 0.005,
            "worst_case_fraction": UNKNOWN_FRACTION_LIMIT,
            "limit": UNKNOWN_FRACTION_LIMIT,
            "includes_right_censored_mass": True,
        },
        "path_error": {
            "denominator_policy": "all_initial_mass",
            "coverage_policy": PATH_COVERAGE_POLICY,
            "maximum_abs_error_m": 0.004,
            "tolerance_m": 0.01,
            "common_reliable_mass_coverage": 0.98,
            "minimum_common_reliable_mass_coverage": 0.95,
        },
        "family_specific": {
            "source_definition": {"axis": 0, "boundary": 0.0},
            "trace_schema": "core.material.f3.synthetic.trace.v1",
            "native_interval_s": 0.01,
            "full_window_s": 2.0,
        },
    }


def _f4_output() -> dict:
    value = _f3_output()
    value["family"] = "F4"
    value["case_id"] = "synthetic-f4-case"
    value["family_specific"] = {
        "scope_id": "F4_synthetic_scope",
        "revision_id": "F4_synthetic_revision",
        "recipe_id": "F4_synthetic_recipe",
        "event_window_s": 2.0,
        "maximum_extension_s": 4.0,
        "residence_definition": {
            "definition": "time inside the destination region after contact",
            "right_censored": True,
        },
    }
    return value


def test_pass_receipt_is_json_only_and_never_qualification() -> None:
    result = validate_material_output(_f3_output())

    assert result["schema"] == SCHEMA
    assert result["status"] == "diagnostic_only"
    assert result["diagnostic_only"] is True
    assert result["passed"] is True
    assert result["qualification_claim"] == "none"
    assert result["qualification_credit"] == 0
    assert isinstance(result["qualification_credit"], int)
    assert result["T2_macro"] is False and result["T2_path"] is False
    assert result["execution_constraints"]["hdf5_opened"] is False
    assert result["execution_constraints"]["solver_started"] is False
    assert result["execution_constraints"]["registry_mutation"] == 0
    assert result["execution_constraints"]["ledger_mutation"] == 0
    assert result["mass"]["closure_pass"] is True
    assert result["transfer_matrix"]["closure_pass"] is True
    assert result["gates"]["event_cdf_and_censor_contract"] is True


def test_mass_closure_failure_is_negative_evidence_and_strict_validation_rejects() -> None:
    value = _f3_output()
    value["mass"]["destination"]["mass_kg"] = 59.0
    value["mass"]["destination"]["fraction"] = 0.59

    diagnostic = evaluate_material_output(value)
    assert diagnostic["passed"] is False
    assert diagnostic["gates"]["mass_closure"] is False
    assert diagnostic["gates"]["transfer_matrix_closure"] is False
    with pytest.raises(ValueError, match="mass_closure"):
        validate_material_output(value)


def test_transfer_matrix_requires_unknown_bucket_and_closes_terminal_mass() -> None:
    value = _f3_output()
    value["transfer_matrix"]["column_labels"] = ["source", "destination", "other"]
    with pytest.raises(ValueError, match="unknown"):
        evaluate_material_output(value)

    value = _f3_output()
    value["transfer_matrix"]["mass_kg"][0][2] = 0.0
    diagnostic = evaluate_material_output(value)
    assert diagnostic["passed"] is False
    assert diagnostic["transfer_matrix"]["column_closure_pass"]["unknown"] is False


def test_unknown_worst_case_is_checked_against_fixed_one_percent_limit() -> None:
    value = _f3_output()
    value["unknown_bound"]["worst_case_fraction"] = 0.011

    diagnostic = evaluate_material_output(value)
    assert diagnostic["passed"] is False
    assert diagnostic["gates"]["unknown_worst_case_bound"] is False
    with pytest.raises(ValueError, match="unknown_worst_case_bound"):
        validate_material_output(value)

    value = _f3_output()
    value["unknown_bound"]["limit"] = 0.02
    with pytest.raises(ValueError, match="fixed 1%"):
        evaluate_material_output(value)


def test_all_three_events_require_cdf_bounds_and_explicit_censor_semantics() -> None:
    value = _f3_output()
    del value["events"]["return"]["cdf"]["upper"]
    with pytest.raises(ValueError, match="upper"):
        evaluate_material_output(value)

    value = _f3_output()
    value["events"]["residence"]["censor"]["counts_as_acceptance"] = True
    with pytest.raises(ValueError, match="counts_as_acceptance"):
        evaluate_material_output(value)

    value = _f3_output()
    value["events"]["first_passage"]["cdf"]["lower"] = [0.0, 0.2, 0.2]
    value["events"]["first_passage"]["cdf"]["upper"] = [0.0, 0.25, 0.2]
    with pytest.raises(ValueError, match="upper.*non-decreasing"):
        evaluate_material_output(value)


def test_path_error_and_common_reliable_mass_coverage_are_separate_gates() -> None:
    value = _f3_output()
    value["path_error"]["common_reliable_mass_coverage"] = 0.90
    diagnostic = evaluate_material_output(value)
    assert diagnostic["passed"] is False
    assert diagnostic["gates"]["path_error"] is True
    assert diagnostic["gates"]["common_reliable_mass_coverage"] is False

    value = _f3_output()
    value["path_error"]["maximum_abs_error_m"] = 0.02
    diagnostic = evaluate_material_output(value)
    assert diagnostic["gates"]["path_error"] is False
    assert diagnostic["gates"]["common_reliable_mass_coverage"] is True


def test_f3_and_f4_family_specific_contracts_are_supported_without_credit() -> None:
    f3 = validate_material_output(_f3_output())
    f4 = validate_material_output(_f4_output())
    assert f3["family"] == "F3"
    assert f4["family"] == "F4"
    assert f3["qualification_credit"] == 0
    assert f4["qualification_credit"] == 0

    missing = _f4_output()
    del missing["family_specific"]["residence_definition"]
    with pytest.raises(ValueError, match="residence_definition"):
        evaluate_material_output(missing)


@pytest.mark.parametrize(
    ("location", "bad_value"),
    [
        (("mass", "source", "mass_kg"), math.nan),
        (("mass", "destination", "fraction"), math.inf),
        (("transfer_matrix", "mass_kg", 0, 0), True),
        (("events", "first_passage", "cdf", "lower", 1), math.nan),
        (("unknown_bound", "worst_case_fraction"), math.inf),
        (("path_error", "common_reliable_mass_coverage"), math.nan),
    ],
)
def test_non_finite_or_boolean_numeric_values_are_rejected(location, bad_value) -> None:
    value = _f3_output()
    target = value
    for part in location[:-1]:
        target = target[part]
    target[location[-1]] = bad_value
    with pytest.raises(ValueError):
        evaluate_material_output(value)


def test_qualification_fields_are_fail_closed_and_numeric_zero_is_required() -> None:
    value = _f3_output()
    value["qualification_credit"] = "none"
    with pytest.raises(ValueError, match="numeric zero"):
        evaluate_material_output(value)

    value = _f3_output()
    value["T2_path"] = True
    with pytest.raises(ValueError, match="T2_path"):
        evaluate_material_output(value)
