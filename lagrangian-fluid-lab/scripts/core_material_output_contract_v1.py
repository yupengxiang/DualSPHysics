"""Validate a source-only JSON material-output contract.

This module is intentionally independent from :mod:`core_material` and
:mod:`core_material_acceptance`.  It consumes one already materialized,
JSON-like dictionary.  It never opens a path, imports HDF5 support, reads a
solver artifact, or changes a registry/ledger.

The input contract is ``core.material.output_contract.v1``.  The canonical
shape is:

``mass``
    ``initial_mass_kg`` plus ``source``, ``destination`` and ``unknown``
    buckets.  Every bucket has ``mass_kg`` and ``fraction``.  Fractions are
    charged against the full initial-mass denominator.
``transfer_matrix``
    A 3x3 mass matrix whose rows are origin buckets and columns are terminal
    buckets.  Both axes must contain exactly ``source``, ``destination`` and
    ``unknown``; the unknown bucket cannot be hidden in an aggregate.
``events``
    ``first_passage``, ``return`` and ``residence``.  Each event has a CDF
    with ``time_s``, ``lower`` and ``upper`` arrays, and an explicit censor
    object.  Right-censored mass remains in the denominator and never counts
    as acceptance.
``unknown_bound`` and ``path_error``
    Explicit worst-case unknown accounting and path-error/common-reliable
    coverage accounting, both over the full initial-mass denominator.
``family_specific``
    Frozen minimum metadata for F3 or F4.  Extra family-specific keys are
    retained but are not interpreted as qualification evidence.

Structural corruption raises ``ValueError``.  A well-formed result whose
scientific gates fail is returned as a diagnostic receipt with
``passed=False``.  :func:`validate_material_output` is the strict wrapper for
callers that require every gate to pass; :func:`evaluate_material_output`
preserves negative evidence without granting any qualification credit.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any


SCHEMA = "core.material.output_contract.v1"
OUTPUT_SCHEMA = SCHEMA
UNKNOWN_FRACTION_LIMIT = 0.01
MASS_CLOSURE_TOLERANCE_KG = 1.0e-9
DENOMINATOR_POLICY = "all_initial_mass"
PATH_COVERAGE_POLICY = "common_reliable_mass_over_all_initial_mass"
BUCKETS = ("source", "destination", "unknown")
EVENTS = ("first_passage", "return", "residence")


def _finite_number(value: Any, name: str) -> float:
    """Return a native finite number and reject booleans/strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _bounded(value: Any, name: str, *, low: float = 0.0, high: float = 1.0) -> float:
    result = _finite_number(value, name)
    if not low <= result <= high:
        raise ValueError(f"{name} must be in [{low},{high}]")
    return result


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_bool(value: Any, name: str, expected: bool | None = None) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    if expected is not None and value is not expected:
        raise ValueError(f"{name} must be {str(expected).lower()}")
    return value


def _require_policy(value: Any, name: str, expected: str) -> str:
    if value != expected:
        raise ValueError(f"{name} must be {expected!r}")
    return expected


def _assert_json_like(value: Any, path: str = "payload", active: set[int] | None = None) -> None:
    """Reject cycles, non-string object keys, and non-finite JSON numbers."""
    if active is None:
        active = set()
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, dict):
        identity = id(value)
        if identity in active:
            raise ValueError(f"{path} contains a cyclic object")
        active.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} has a non-string object key")
                _assert_json_like(item, f"{path}.{key}", active)
        finally:
            active.remove(identity)
        return
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise ValueError(f"{path} contains a cyclic list")
        active.add(identity)
        try:
            for index, item in enumerate(value):
                _assert_json_like(item, f"{path}[{index}]", active)
        finally:
            active.remove(identity)
        return
    raise ValueError(f"{path} is not JSON-like")


def _close(actual: float, expected: float, tolerance: float) -> bool:
    return abs(actual - expected) <= max(tolerance, 1.0e-12)


def _validate_envelope(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if payload.get("schema") != SCHEMA:
        raise ValueError("unsupported material output contract schema")
    if payload.get("diagnostic_only") is not True:
        raise ValueError("material output must be diagnostic_only")
    if payload.get("qualification_claim") != "none":
        raise ValueError("material output carries a qualification claim")
    credit = payload.get("qualification_credit")
    if isinstance(credit, bool) or not isinstance(credit, (int, float)) or float(credit) != 0.0:
        raise ValueError("material output qualification_credit must be numeric zero")
    for name in ("T2_macro", "T2_path", "qualified_T2_macro", "qualified_T2_path"):
        if name in payload and payload[name] is not False:
            raise ValueError(f"material output cannot claim {name}")
    family = payload.get("family")
    if family not in ("F3", "F4"):
        raise ValueError("material output family must be F3 or F4")
    case_id = _require_string(payload.get("case_id"), "case_id")
    family_specific = _require_object(payload.get("family_specific"), "family_specific")
    return family, case_id, family_specific


def _validate_mass(payload: dict[str, Any]) -> tuple[dict[str, Any], float, float, bool]:
    mass = _require_object(payload.get("mass"), "mass")
    initial = _finite_number(mass.get("initial_mass_kg"), "mass.initial_mass_kg")
    if initial <= 0:
        raise ValueError("mass.initial_mass_kg must be positive")
    tolerance = _finite_number(mass.get("closure_tolerance_kg"), "mass.closure_tolerance_kg")
    if tolerance < 0:
        raise ValueError("mass.closure_tolerance_kg cannot be negative")
    _require_policy(mass.get("denominator_policy"), "mass.denominator_policy", DENOMINATOR_POLICY)

    buckets: dict[str, dict[str, float]] = {}
    for name in BUCKETS:
        bucket = _require_object(mass.get(name), f"mass.{name}")
        mass_kg = _finite_number(bucket.get("mass_kg"), f"mass.{name}.mass_kg")
        if mass_kg < 0:
            raise ValueError(f"mass.{name}.mass_kg cannot be negative")
        fraction = _bounded(bucket.get("fraction"), f"mass.{name}.fraction")
        expected_fraction = mass_kg / initial
        if not _close(fraction, expected_fraction, tolerance / initial):
            raise ValueError(f"mass.{name}.fraction is not bound to mass_kg")
        buckets[name] = {"mass_kg": mass_kg, "fraction": fraction}

    total = sum(row["mass_kg"] for row in buckets.values())
    mass_closed = _close(total, initial, tolerance)
    normalized = {
        "initial_mass_kg": initial,
        "closure_tolerance_kg": tolerance,
        "denominator_policy": DENOMINATOR_POLICY,
        **buckets,
        "terminal_mass_sum_kg": total,
        "closure_pass": mass_closed,
    }
    return normalized, initial, tolerance, mass_closed


def _validate_transfer_matrix(
    payload: dict[str, Any], mass: dict[str, Any], initial: float, tolerance: float
) -> tuple[dict[str, Any], bool]:
    matrix = _require_object(payload.get("transfer_matrix"), "transfer_matrix")
    row_labels = _require_list(matrix.get("row_labels"), "transfer_matrix.row_labels")
    column_labels = _require_list(matrix.get("column_labels"), "transfer_matrix.column_labels")
    if len(row_labels) != len(BUCKETS) or set(row_labels) != set(BUCKETS):
        raise ValueError("transfer_matrix.row_labels must contain source, destination and unknown exactly once")
    if len(column_labels) != len(BUCKETS) or set(column_labels) != set(BUCKETS):
        raise ValueError("transfer_matrix.column_labels must contain source, destination and unknown exactly once")
    values = _require_list(matrix.get("mass_kg"), "transfer_matrix.mass_kg")
    if len(values) != len(row_labels):
        raise ValueError("transfer_matrix.mass_kg row count does not match row_labels")

    normalized_values: list[list[float]] = []
    for row_index, row in enumerate(values):
        row_values = _require_list(row, f"transfer_matrix.mass_kg[{row_index}]")
        if len(row_values) != len(column_labels):
            raise ValueError("transfer_matrix.mass_kg column count does not match column_labels")
        normalized_row = []
        for column_index, value in enumerate(row_values):
            number = _finite_number(
                value,
                f"transfer_matrix.mass_kg[{row_index}][{column_index}]",
            )
            if number < 0:
                raise ValueError("transfer_matrix mass cannot be negative")
            normalized_row.append(number)
        normalized_values.append(normalized_row)

    column_mass = {
        label: sum(normalized_values[row_index][column_labels.index(label)] for row_index in range(len(row_labels)))
        for label in BUCKETS
    }
    matrix_total = sum(sum(row) for row in normalized_values)
    total_pass = _close(matrix_total, initial, tolerance)
    column_pass = {
        label: _close(column_mass[label], mass[label]["mass_kg"], tolerance)
        for label in BUCKETS
    }
    matrix_pass = bool(total_pass and all(column_pass.values()))
    return {
        "orientation": "rows_origin_columns_terminal",
        "row_labels": list(row_labels),
        "column_labels": list(column_labels),
        "mass_kg": normalized_values,
        "total_mass_kg": matrix_total,
        "column_mass_kg": column_mass,
        "total_closure_pass": bool(total_pass),
        "column_closure_pass": column_pass,
        "closure_pass": matrix_pass,
    }, matrix_pass


def _validate_event(name: str, event: Any) -> dict[str, Any]:
    event = _require_object(event, f"events.{name}")
    definition = _require_string(event.get("definition"), f"events.{name}.definition")
    _require_policy(
        event.get("denominator_policy"),
        f"events.{name}.denominator_policy",
        DENOMINATOR_POLICY,
    )
    cdf = _require_object(event.get("cdf"), f"events.{name}.cdf")
    time_s = _require_list(cdf.get("time_s"), f"events.{name}.cdf.time_s")
    lower = _require_list(cdf.get("lower"), f"events.{name}.cdf.lower")
    upper = _require_list(cdf.get("upper"), f"events.{name}.cdf.upper")
    if not time_s or len(time_s) != len(lower) or len(lower) != len(upper):
        raise ValueError(f"events.{name}.cdf arrays must be non-empty and have equal lengths")
    time_values = [_finite_number(value, f"events.{name}.cdf.time_s[{index}]") for index, value in enumerate(time_s)]
    lower_values = [_bounded(value, f"events.{name}.cdf.lower[{index}]") for index, value in enumerate(lower)]
    upper_values = [_bounded(value, f"events.{name}.cdf.upper[{index}]") for index, value in enumerate(upper)]
    if any(value < 0 for value in time_values) or any(
        later <= earlier for earlier, later in zip(time_values, time_values[1:])
    ):
        raise ValueError(f"events.{name}.cdf.time_s must be strictly increasing and non-negative")
    if any(lo > hi for lo, hi in zip(lower_values, upper_values)):
        raise ValueError(f"events.{name}.cdf lower bound exceeds upper bound for {name}")
    if any(later < earlier for earlier, later in zip(lower_values, lower_values[1:])):
        raise ValueError(f"events.{name}.cdf.lower must be non-decreasing")
    if any(later < earlier for earlier, later in zip(upper_values, upper_values[1:])):
        raise ValueError(f"events.{name}.cdf.upper must be non-decreasing")
    _require_policy(cdf.get("denominator_policy"), f"events.{name}.cdf.denominator_policy", DENOMINATOR_POLICY)

    censor = _require_object(event.get("censor"), f"events.{name}.censor")
    censor_type = censor.get("type")
    if censor_type not in ("none", "right"):
        raise ValueError(f"events.{name}.censor.type must be 'none' or 'right'")
    censor_fraction = _bounded(censor.get("fraction"), f"events.{name}.censor.fraction")
    _require_bool(censor.get("counts_as_acceptance"), f"events.{name}.censor.counts_as_acceptance", False)
    expected_policy = (
        "no_censoring"
        if censor_type == "none"
        else "right_censored_mass_remains_in_denominator"
    )
    _require_policy(censor.get("policy"), f"events.{name}.censor.policy", expected_policy)
    if censor_type == "none" and censor_fraction != 0.0:
        raise ValueError(f"events.{name}.censor.fraction must be zero when censor.type is 'none'")
    if censor_type == "right" and censor_fraction <= 0.0:
        raise ValueError(f"events.{name}.censor.fraction must be positive for right censoring")

    return {
        "definition": definition,
        "denominator_policy": DENOMINATOR_POLICY,
        "cdf": {
            "time_s": time_values,
            "lower": lower_values,
            "upper": upper_values,
            "denominator_policy": DENOMINATOR_POLICY,
        },
        "censor": {
            "type": censor_type,
            "fraction": censor_fraction,
            "policy": expected_policy,
            "counts_as_acceptance": False,
        },
    }


def _validate_events(payload: dict[str, Any]) -> dict[str, Any]:
    events = _require_object(payload.get("events"), "events")
    return {name: _validate_event(name, events.get(name)) for name in EVENTS}


def _validate_unknown_bound(
    payload: dict[str, Any], mass: dict[str, Any], initial: float, tolerance: float
) -> tuple[dict[str, Any], bool]:
    bound = _require_object(payload.get("unknown_bound"), "unknown_bound")
    _require_policy(bound.get("denominator_policy"), "unknown_bound.denominator_policy", DENOMINATOR_POLICY)
    observed = _bounded(bound.get("observed_fraction"), "unknown_bound.observed_fraction")
    worst = _bounded(bound.get("worst_case_fraction"), "unknown_bound.worst_case_fraction")
    limit = _finite_number(bound.get("limit"), "unknown_bound.limit")
    if limit < 0 or limit > UNKNOWN_FRACTION_LIMIT or not _close(limit, UNKNOWN_FRACTION_LIMIT, 1.0e-12):
        raise ValueError("unknown_bound.limit must remain the fixed 1% limit")
    expected_observed = mass["unknown"]["mass_kg"] / initial
    if not _close(observed, expected_observed, tolerance / initial):
        raise ValueError("unknown_bound.observed_fraction is not bound to mass.unknown")
    if worst < observed:
        raise ValueError("unknown_bound.worst_case_fraction cannot be below observed_fraction")
    includes_censored = _require_bool(
        bound.get("includes_right_censored_mass"),
        "unknown_bound.includes_right_censored_mass",
        True,
    )
    return {
        "denominator_policy": DENOMINATOR_POLICY,
        "observed_fraction": observed,
        "worst_case_fraction": worst,
        "limit": UNKNOWN_FRACTION_LIMIT,
        "includes_right_censored_mass": includes_censored,
        "gate_pass": bool(worst <= UNKNOWN_FRACTION_LIMIT),
    }, bool(worst <= UNKNOWN_FRACTION_LIMIT)


def _validate_path_error(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    path = _require_object(payload.get("path_error"), "path_error")
    _require_policy(path.get("denominator_policy"), "path_error.denominator_policy", DENOMINATOR_POLICY)
    _require_policy(path.get("coverage_policy"), "path_error.coverage_policy", PATH_COVERAGE_POLICY)
    maximum = _finite_number(path.get("maximum_abs_error_m"), "path_error.maximum_abs_error_m")
    tolerance = _finite_number(path.get("tolerance_m"), "path_error.tolerance_m")
    if maximum < 0 or tolerance < 0:
        raise ValueError("path_error values cannot be negative")
    coverage = _bounded(path.get("common_reliable_mass_coverage"), "path_error.common_reliable_mass_coverage")
    minimum = _bounded(
        path.get("minimum_common_reliable_mass_coverage"),
        "path_error.minimum_common_reliable_mass_coverage",
    )
    error_pass = maximum <= tolerance
    coverage_pass = coverage >= minimum
    return {
        "denominator_policy": DENOMINATOR_POLICY,
        "coverage_policy": PATH_COVERAGE_POLICY,
        "maximum_abs_error_m": maximum,
        "tolerance_m": tolerance,
        "common_reliable_mass_coverage": coverage,
        "minimum_common_reliable_mass_coverage": minimum,
        "error_pass": bool(error_pass),
        "coverage_pass": bool(coverage_pass),
        "gate_pass": bool(error_pass and coverage_pass),
    }, bool(error_pass and coverage_pass)


def _validate_family_specific(family: str, fields: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(fields)
    if family == "F3":
        source_definition = fields.get("source_definition")
        if not isinstance(source_definition, (dict, str)) or (isinstance(source_definition, str) and not source_definition.strip()):
            raise ValueError("F3 family_specific.source_definition must be non-empty")
        _require_string(fields.get("trace_schema"), "F3 family_specific.trace_schema")
        native_interval = _finite_number(fields.get("native_interval_s"), "F3 family_specific.native_interval_s")
        full_window = _finite_number(fields.get("full_window_s"), "F3 family_specific.full_window_s")
        if native_interval <= 0 or full_window <= 0 or full_window < native_interval:
            raise ValueError("F3 family-specific time window is invalid")
        normalized.update(
            {
                "native_interval_s": native_interval,
                "full_window_s": full_window,
            }
        )
    else:
        for name in ("scope_id", "revision_id", "recipe_id", "residence_definition"):
            value = fields.get(name)
            if not isinstance(value, (dict, str)) or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"F4 family_specific.{name} must be non-empty")
        event_window = _finite_number(fields.get("event_window_s"), "F4 family_specific.event_window_s")
        maximum_extension = _finite_number(
            fields.get("maximum_extension_s"),
            "F4 family_specific.maximum_extension_s",
        )
        if event_window <= 0 or maximum_extension < event_window:
            raise ValueError("F4 family-specific event window is invalid")
        normalized.update(
            {
                "event_window_s": event_window,
                "maximum_extension_s": maximum_extension,
            }
        )
    return normalized


def evaluate_material_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a diagnostic receipt for one JSON-only material output.

    Malformed structure raises ``ValueError``.  Scientific gate failures are
    represented by ``passed=False`` so a caller can preserve negative
    evidence without mistaking it for a missing artifact or a T2 claim.
    """
    if not isinstance(payload, dict):
        raise ValueError("material output must be an object")
    _assert_json_like(payload)
    family, case_id, family_specific = _validate_envelope(payload)
    normalized_mass, initial, tolerance, mass_pass = _validate_mass(payload)
    normalized_matrix, matrix_pass = _validate_transfer_matrix(
        payload, normalized_mass, initial, tolerance
    )
    normalized_events = _validate_events(payload)
    normalized_unknown, unknown_pass = _validate_unknown_bound(
        payload, normalized_mass, initial, tolerance
    )
    normalized_path, path_pass = _validate_path_error(payload)
    normalized_family = _validate_family_specific(family, family_specific)

    gates = {
        "mass_closure": bool(mass_pass),
        "transfer_matrix_closure": bool(matrix_pass),
        "event_cdf_and_censor_contract": True,
        "unknown_worst_case_bound": bool(unknown_pass),
        "path_error": bool(normalized_path["error_pass"]),
        "common_reliable_mass_coverage": bool(normalized_path["coverage_pass"]),
        "family_specific_contract": True,
    }
    failures = [name for name, passed in gates.items() if not passed]
    return {
        "schema": SCHEMA,
        "status": "diagnostic_only",
        "diagnostic_only": True,
        "passed": not failures,
        "failure_reasons": failures,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "family": family,
        "case_id": case_id,
        "mass": normalized_mass,
        "transfer_matrix": normalized_matrix,
        "events": normalized_events,
        "unknown_bound": normalized_unknown,
        "path_error": normalized_path,
        "family_specific": normalized_family,
        "gates": gates,
        "execution_constraints": {
            "json_source_only": True,
            "hdf5_opened": False,
            "solver_started": False,
            "gpu_started": False,
            "training_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "t2_credit_registered": 0,
        },
    }


def validate_material_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a material output and require all scientific gates to pass."""
    result = evaluate_material_output(payload)
    if not result["passed"]:
        raise ValueError("material output contract failed: " + ", ".join(result["failure_reasons"]))
    return result


def validate_material_output_diagnostic(payload: dict[str, Any]) -> dict[str, Any]:
    """Compatibility alias for callers that want negative evidence, not raises."""
    return evaluate_material_output(payload)


__all__ = [
    "BUCKETS",
    "DENOMINATOR_POLICY",
    "EVENTS",
    "MASS_CLOSURE_TOLERANCE_KG",
    "OUTPUT_SCHEMA",
    "PATH_COVERAGE_POLICY",
    "SCHEMA",
    "UNKNOWN_FRACTION_LIMIT",
    "evaluate_material_output",
    "validate_material_output",
    "validate_material_output_diagnostic",
]
