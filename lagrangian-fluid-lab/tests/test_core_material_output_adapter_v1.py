from __future__ import annotations

from copy import deepcopy
import json

import pytest

from scripts.core_material_output_adapter_v1 import (
    EVENTS_SCHEMA,
    FAMILY_FIELDS_SCHEMA,
    PATH_ERROR_SCHEMA,
    SOURCE_SUMMARY_SCHEMA,
    TRANSFER_MATRIX_SCHEMA,
    adapt_material_output,
    normalize_material_output,
)
from scripts.core_material_output_contract_v1 import (
    MASS_CLOSURE_TOLERANCE_KG,
    OUTPUT_SCHEMA,
    evaluate_material_output,
)


FAMILY = "F3"
CASE_ID = "synthetic-material-adapter-f3"
REQUIRED_SOURCE_IDS = ["source-a", "source-b"]


def _source_summary(family: str = FAMILY, case_id: str = CASE_ID) -> dict:
    return {
        "schema": SOURCE_SUMMARY_SCHEMA,
        "family": family,
        "case_id": case_id,
        "denominator_policy": "all_initial_mass",
        "initial_mass_kg": 100.0,
        "closure_tolerance_kg": MASS_CLOSURE_TOLERANCE_KG,
        "terminal_buckets": {
            "source": {"mass_kg": 40.0, "fraction": 0.40},
            "destination": {"mass_kg": 59.5, "fraction": 0.595},
            "unknown": {"mass_kg": 0.5, "fraction": 0.005},
        },
        "source_rows": [
            {
                "source_id": "source-a",
                "denominator_policy": "all_initial_mass",
                "initial_mass_kg": 50.0,
                "unknown_fraction_max": 0.005,
            },
            {
                "source_id": "source-b",
                "denominator_policy": "all_initial_mass",
                "initial_mass_kg": 50.0,
                "unknown_fraction_max": 0.005,
            },
        ],
        "unknown_bound": {
            "denominator_policy": "all_initial_mass",
            "observed_fraction": 0.005,
            "worst_case_fraction": 0.01,
            "limit": 0.01,
            "includes_right_censored_mass": True,
        },
    }


def _transfer(family: str = FAMILY, case_id: str = CASE_ID) -> dict:
    return {
        "schema": TRANSFER_MATRIX_SCHEMA,
        "family": family,
        "case_id": case_id,
        "denominator_policy": "all_initial_mass",
        "orientation": "rows_origin_columns_terminal",
        "origin_labels": ["source", "destination", "unknown"],
        "terminal_labels": ["source", "destination", "unknown"],
        "mass_kg": [
            [35.0, 14.5, 0.5],
            [5.0, 45.0, 0.0],
            [0.0, 0.0, 0.0],
        ],
    }


def _events(family: str = FAMILY, case_id: str = CASE_ID) -> dict:
    def event(name: str) -> dict:
        return {
            "definition": f"synthetic {name} event",
            "denominator_policy": "all_initial_mass",
            "cdf_denominator_policy": "all_initial_mass",
            "time_s": [0.0, 1.0, 2.0],
            "lower": [0.0, 0.20, 0.50],
            "upper": [0.0, 0.25, 0.60],
            "censor": {
                "type": "right",
                "fraction": 0.10,
                "policy": "right_censored_mass_remains_in_denominator",
                "counts_as_acceptance": False,
            },
        }

    return {
        "schema": EVENTS_SCHEMA,
        "family": family,
        "case_id": case_id,
        "first_passage": event("first passage"),
        "return": event("return"),
        "residence": event("residence"),
    }


def _path_error(family: str = FAMILY, case_id: str = CASE_ID) -> dict:
    return {
        "schema": PATH_ERROR_SCHEMA,
        "family": family,
        "case_id": case_id,
        "denominator_policy": "all_initial_mass",
        "coverage_policy": "common_reliable_mass_over_all_initial_mass",
        "maximum_abs_error_m": 0.004,
        "tolerance_m": 0.01,
        "common_reliable_mass_coverage": 0.98,
        "minimum_common_reliable_mass_coverage": 0.95,
    }


def _family_fields(family: str = FAMILY, case_id: str = CASE_ID) -> dict:
    if family == "F3":
        specific = {
            "source_definition": {"axis": 0, "boundary": 0.0},
            "trace_schema": "core.material.f3.synthetic.trace.v1",
            "native_interval_s": 0.002,
            "full_window_s": 8.35,
        }
    else:
        specific = {
            "scope_id": "F4_synthetic_scope",
            "revision_id": "F4_synthetic_revision",
            "recipe_id": "F4_synthetic_recipe",
            "residence_definition": {
                "definition": "time inside destination after contact",
                "right_censored": True,
            },
            "event_window_s": 4.34,
            "maximum_extension_s": 8.68,
        }
    return {
        "schema": FAMILY_FIELDS_SCHEMA,
        "family": family,
        "case_id": case_id,
        "family_specific": specific,
    }


def _components(family: str = FAMILY, case_id: str = CASE_ID) -> tuple[dict, ...]:
    return (
        _source_summary(family, case_id),
        _transfer(family, case_id),
        _events(family, case_id),
        _path_error(family, case_id),
        _family_fields(family, case_id),
    )


def test_f3_pass_normalizes_to_contract_and_keeps_full_source_denominator() -> None:
    result = adapt_material_output(*_components(), required_source_ids=REQUIRED_SOURCE_IDS)

    assert result["schema"] == OUTPUT_SCHEMA
    assert result["passed"] is True
    assert result["diagnostic_only"] is True
    assert result["qualification_claim"] == "none"
    assert result["qualification_credit"] == 0
    assert result["mass"]["denominator_policy"] == "all_initial_mass"
    assert result["events"]["return"]["censor"]["counts_as_acceptance"] is False
    assert result["source_coverage"]["source_count"] == 2
    assert result["source_coverage"]["source_unknown_gate_pass"] is True
    assert result["source_coverage"]["aggregate_unknown_gate_pass"] is True
    assert result["execution_constraints"]["hdf5_opened"] is False
    assert result["execution_constraints"]["registry_mutation"] == 0
    json.dumps(result, allow_nan=False)
    assert evaluate_material_output(result)["passed"] is True


def test_f4_pass_uses_its_own_family_fields_without_importing_f3_fields() -> None:
    result = adapt_material_output(
        *_components("F4", "synthetic-material-adapter-f4"),
        required_source_ids=REQUIRED_SOURCE_IDS,
    )

    assert result["family"] == "F4"
    assert result["passed"] is True
    assert result["family_specific"]["scope_id"] == "F4_synthetic_scope"
    assert "trace_schema" not in result["family_specific"]
    assert result["qualification_credit"] == 0


@pytest.mark.parametrize(
    ("component_index", "field_path"),
    [
        (0, ("unknown_bound",)),
        (1, ("mass_kg",)),
        (2, ("return", "censor")),
        (3, ("minimum_common_reliable_mass_coverage",)),
        (4, ("family_specific",)),
    ],
)
def test_missing_new_fields_fail_closed(component_index, field_path) -> None:
    components = list(_components())
    target = components[component_index]
    for key in field_path[:-1]:
        target = target[key]
    del target[field_path[-1]]

    with pytest.raises(ValueError, match="missing required field"):
        adapt_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)


def test_old_bridge_summary_shape_is_not_guessed_or_adapted() -> None:
    components = list(_components())
    components[0] = {
        "by_source": [
            {"source": "source-a", "initial_mass_kg": 100.0, "unknown_fraction_max": 0.0}
        ],
        "mass_closed": True,
        "event_window_complete": True,
    }

    with pytest.raises(ValueError, match="source_summary.*schema"):
        adapt_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)


def test_component_identity_mismatch_is_rejected() -> None:
    components = list(_components())
    components[2]["case_id"] = "different-case"

    with pytest.raises(ValueError, match="identity"):
        adapt_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)


def test_scientific_failure_is_diagnostic_zero_credit_not_silently_repaired() -> None:
    components = list(_components())
    components[0]["unknown_bound"]["worst_case_fraction"] = 0.011

    result = normalize_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)

    assert result["passed"] is False
    assert "unknown_worst_case_bound" in result["failure_reasons"]
    assert result["diagnostic_only"] is True
    assert result["qualification_claim"] == "none"
    assert result["qualification_credit"] == 0


def test_censor_acceptance_claim_is_rejected_instead_of_defaulted() -> None:
    components = list(_components())
    components[2]["first_passage"]["censor"]["counts_as_acceptance"] = True

    with pytest.raises(ValueError, match="counts_as_acceptance"):
        adapt_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)


def test_component_schemas_are_required() -> None:
    components = list(_components())
    del components[1]["schema"]

    with pytest.raises(ValueError, match="transfer_matrix.*schema"):
        adapt_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)


def test_required_source_ids_are_mandatory_and_external() -> None:
    with pytest.raises(TypeError, match="required_source_ids"):
        adapt_material_output(*_components())


@pytest.mark.parametrize("shape", ["merged", "missing", "extra"])
def test_source_rows_must_match_registered_source_set_exactly(shape: str) -> None:
    components = list(_components())
    rows = components[0]["source_rows"]
    if shape == "merged":
        components[0]["source_rows"] = [
            {
                "source_id": "source-a+source-b",
                "denominator_policy": "all_initial_mass",
                "initial_mass_kg": 100.0,
                "unknown_fraction_max": 0.005,
            }
        ]
    elif shape == "missing":
        components[0]["source_rows"] = rows[:1]
    else:
        components[0]["source_rows"] = [
            *rows,
            {
                "source_id": "source-c",
                "denominator_policy": "all_initial_mass",
                "initial_mass_kg": 1.0,
                "unknown_fraction_max": 0.0,
            },
        ]

    with pytest.raises(ValueError, match="required_source_ids"):
        adapt_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)


def test_registered_mass_tolerance_cannot_hide_missing_mass() -> None:
    components = list(_components())
    components[0]["closure_tolerance_kg"] = 1.0
    components[0]["terminal_buckets"]["unknown"] = {"mass_kg": 0.0, "fraction": 0.0}
    components[0]["unknown_bound"]["observed_fraction"] = 0.0

    with pytest.raises(ValueError, match="closure_tolerance_kg.*registered"):
        adapt_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)


def test_per_source_and_weighted_aggregate_unknown_gates_are_separate() -> None:
    components = list(_components())
    components[0]["source_rows"][0]["initial_mass_kg"] = 10.0
    components[0]["source_rows"][0]["unknown_fraction_max"] = 0.02
    components[0]["source_rows"][1]["initial_mass_kg"] = 90.0
    components[0]["source_rows"][1]["unknown_fraction_max"] = 0.0

    result = normalize_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)

    coverage = result["source_coverage"]
    assert coverage["maximum_source_unknown_fraction"] == pytest.approx(0.02)
    assert coverage["aggregate_worst_case_unknown_fraction"] == pytest.approx(0.002)
    assert coverage["source_unknown_gate_pass"] is False
    assert coverage["aggregate_unknown_gate_pass"] is True
    assert result["passed"] is False
    assert "source_unknown_gate" in result["failure_reasons"]
    assert result["diagnostic_only"] is True
    assert result["qualification_claim"] == "none"
    assert result["qualification_credit"] == 0
    assert result["T2_macro"] is False
    assert result["T2_path"] is False


def test_weighted_aggregate_unknown_failure_is_diagnostic() -> None:
    components = list(_components())
    for row in components[0]["source_rows"]:
        row["unknown_fraction_max"] = 0.011

    result = normalize_material_output(*components, required_source_ids=REQUIRED_SOURCE_IDS)

    coverage = result["source_coverage"]
    assert coverage["aggregate_worst_case_unknown_fraction"] == pytest.approx(0.011)
    assert coverage["aggregate_bound_covers_source_rows"] is False
    assert coverage["aggregate_unknown_gate_pass"] is False
    assert result["passed"] is False
    assert "source_unknown_gate" in result["failure_reasons"]
    assert "aggregate_unknown_gate" in result["failure_reasons"]
    assert result["qualification_credit"] == 0
