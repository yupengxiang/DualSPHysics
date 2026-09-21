"""Normalize complete JSON material summaries into the Core output contract.

This adapter is deliberately narrower than the historical F3/F4 bridges.  It
does not read a bridge receipt, inspect a path, open HDF5, or infer a value
from an older summary.  Callers provide five complete, versioned JSON objects:

``source_summary``
    Full-mass terminal buckets, per-source denominators, and the explicit
    unknown-mass bound.
``transfer_matrix``
    An origin-by-terminal mass matrix with explicit axis labels.
``events``
    The three event definitions, CDF bounds, and censor semantics.
``path_error``
    Maximum path error and common-reliable coverage over the full denominator.
``family_fields``
    Family/case identity and the frozen F3 or F4 fields.

Every component has its own input schema, family, case id, and denominator
policy.  Missing fields, mixed identities, or attempts to use an old/unknown
shape fail closed with :class:`ValueError`.  Numerical gate failures are
preserved by the target contract as ``passed=False`` diagnostic output.

The returned object is validated by
:mod:`scripts.core_material_output_contract_v1`.  It always carries
``diagnostic_only=true``, ``qualification_claim=none``, and numeric
``qualification_credit=0``.  This module has no filesystem, HDF5, solver,
training, registry, ledger, completion, or evidence I/O.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

try:
    from scripts.core_material_output_contract_v1 import (
        DENOMINATOR_POLICY,
        EVENTS,
        OUTPUT_SCHEMA,
        PATH_COVERAGE_POLICY,
        UNKNOWN_FRACTION_LIMIT,
        evaluate_material_output,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script import
    from core_material_output_contract_v1 import (  # type: ignore
        DENOMINATOR_POLICY,
        EVENTS,
        OUTPUT_SCHEMA,
        PATH_COVERAGE_POLICY,
        UNKNOWN_FRACTION_LIMIT,
        evaluate_material_output,
    )


ADAPTER_SCHEMA = "core.material.output_adapter.v1"
SOURCE_SUMMARY_SCHEMA = "core.material.source_summary.v1"
TRANSFER_MATRIX_SCHEMA = "core.material.transfer_matrix.v1"
EVENTS_SCHEMA = "core.material.event_cdf_censor.v1"
PATH_ERROR_SCHEMA = "core.material.path_error.v1"
FAMILY_FIELDS_SCHEMA = "core.material.family_fields.v1"

BUCKETS = ("source", "destination", "unknown")
CLAIM_FIELDS = {
    "diagnostic_only",
    "qualification_claim",
    "qualification_credit",
    "T2_macro",
    "T2_path",
    "qualified_T2_macro",
    "qualified_T2_path",
}


def _assert_json_like(value: Any, path: str = "value", active: set[int] | None = None) -> None:
    """Reject non-JSON values, cycles, and non-finite JSON numbers."""
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


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _required(obj: dict[str, Any], key: str, name: str) -> Any:
    if key not in obj:
        raise ValueError(f"{name} is missing required field: {key}")
    return obj[key]


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _fraction(value: Any, name: str) -> float:
    result = _number(value, name)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be in [0,1]")
    return result


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _policy(value: Any, name: str) -> str:
    if value != DENOMINATOR_POLICY:
        raise ValueError(f"{name} must be {DENOMINATOR_POLICY!r}")
    return DENOMINATOR_POLICY


def _close(actual: float, expected: float, tolerance: float) -> bool:
    return abs(actual - expected) <= max(tolerance, 1.0e-12)


def _identity(component: dict[str, Any], component_name: str) -> tuple[str, str]:
    family = _string(_required(component, "family", component_name), f"{component_name}.family")
    case_id = _string(_required(component, "case_id", component_name), f"{component_name}.case_id")
    if family not in ("F3", "F4"):
        raise ValueError(f"{component_name}.family must be F3 or F4")
    return family, case_id


def _schema(component: dict[str, Any], expected: str, component_name: str) -> None:
    value = _required(component, "schema", component_name)
    if value != expected:
        raise ValueError(f"{component_name}.schema must be {expected!r}")


def _validate_component_identity(
    component: dict[str, Any], component_name: str, expected_family: str, expected_case_id: str
) -> None:
    family, case_id = _identity(component, component_name)
    if family != expected_family or case_id != expected_case_id:
        raise ValueError(f"{component_name} family/case identity does not match family_fields")


def _source_summary(
    value: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]:
    summary = _object(value, "source_summary")
    _schema(summary, SOURCE_SUMMARY_SCHEMA, "source_summary")
    family, case_id = _identity(summary, "source_summary")
    _policy(
        _required(summary, "denominator_policy", "source_summary"),
        "source_summary.denominator_policy",
    )
    initial = _number(
        _required(summary, "initial_mass_kg", "source_summary"),
        "source_summary.initial_mass_kg",
    )
    if initial <= 0:
        raise ValueError("source_summary.initial_mass_kg must be positive")
    tolerance = _number(
        _required(summary, "closure_tolerance_kg", "source_summary"),
        "source_summary.closure_tolerance_kg",
    )
    if tolerance < 0:
        raise ValueError("source_summary.closure_tolerance_kg cannot be negative")

    terminal = _object(
        _required(summary, "terminal_buckets", "source_summary"),
        "source_summary.terminal_buckets",
    )
    if set(terminal) != set(BUCKETS):
        raise ValueError("source_summary.terminal_buckets must contain source, destination and unknown")
    buckets: dict[str, dict[str, float]] = {}
    for bucket_name in BUCKETS:
        bucket = _object(terminal[bucket_name], f"source_summary.terminal_buckets.{bucket_name}")
        mass = _number(
            _required(bucket, "mass_kg", f"source_summary.terminal_buckets.{bucket_name}"),
            f"source_summary.terminal_buckets.{bucket_name}.mass_kg",
        )
        if mass < 0:
            raise ValueError(f"source_summary.terminal_buckets.{bucket_name}.mass_kg cannot be negative")
        fraction = _fraction(
            _required(bucket, "fraction", f"source_summary.terminal_buckets.{bucket_name}"),
            f"source_summary.terminal_buckets.{bucket_name}.fraction",
        )
        buckets[bucket_name] = {"mass_kg": mass, "fraction": fraction}

    rows = _list(_required(summary, "source_rows", "source_summary"), "source_summary.source_rows")
    if not rows:
        raise ValueError("source_summary.source_rows must not be empty")
    normalized_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_mass_total = 0.0
    maximum_source_unknown = 0.0
    for index, raw in enumerate(rows):
        row = _object(raw, f"source_summary.source_rows[{index}]")
        source_id = _string(
            _required(row, "source_id", f"source_summary.source_rows[{index}]"),
            f"source_summary.source_rows[{index}].source_id",
        )
        if source_id in seen:
            raise ValueError(f"duplicate source_summary source_id: {source_id}")
        seen.add(source_id)
        _policy(
            _required(row, "denominator_policy", f"source_summary.source_rows[{index}]"),
            f"source_summary.source_rows[{index}].denominator_policy",
        )
        source_mass = _number(
            _required(row, "initial_mass_kg", f"source_summary.source_rows[{index}]"),
            f"source_summary.source_rows[{index}].initial_mass_kg",
        )
        if source_mass <= 0:
            raise ValueError(f"source_summary.source_rows[{index}].initial_mass_kg must be positive")
        unknown = _fraction(
            _required(row, "unknown_fraction_max", f"source_summary.source_rows[{index}]"),
            f"source_summary.source_rows[{index}].unknown_fraction_max",
        )
        source_mass_total += source_mass
        maximum_source_unknown = max(maximum_source_unknown, unknown)
        normalized_rows.append(
            {
                "source_id": source_id,
                "initial_mass_kg": source_mass,
                "unknown_fraction_max": unknown,
                "denominator_policy": DENOMINATOR_POLICY,
            }
        )
    if not _close(source_mass_total, initial, tolerance):
        raise ValueError("source_summary.source_rows do not close the initial-mass denominator")

    unknown_input = _object(
        _required(summary, "unknown_bound", "source_summary"),
        "source_summary.unknown_bound",
    )
    _policy(
        _required(unknown_input, "denominator_policy", "source_summary.unknown_bound"),
        "source_summary.unknown_bound.denominator_policy",
    )
    observed = _fraction(
        _required(unknown_input, "observed_fraction", "source_summary.unknown_bound"),
        "source_summary.unknown_bound.observed_fraction",
    )
    worst = _fraction(
        _required(unknown_input, "worst_case_fraction", "source_summary.unknown_bound"),
        "source_summary.unknown_bound.worst_case_fraction",
    )
    limit = _number(
        _required(unknown_input, "limit", "source_summary.unknown_bound"),
        "source_summary.unknown_bound.limit",
    )
    if limit != UNKNOWN_FRACTION_LIMIT:
        raise ValueError("source_summary.unknown_bound.limit must remain the fixed 1% limit")
    includes_censored = _boolean(
        _required(unknown_input, "includes_right_censored_mass", "source_summary.unknown_bound"),
        "source_summary.unknown_bound.includes_right_censored_mass",
    )
    if not includes_censored:
        raise ValueError("source_summary.unknown_bound must include right-censored mass")
    expected_observed = buckets["unknown"]["mass_kg"] / initial
    if not _close(observed, expected_observed, tolerance / initial):
        raise ValueError("source_summary.unknown_bound.observed_fraction is not bound to unknown mass")
    if worst < observed or worst < maximum_source_unknown:
        raise ValueError("source_summary.unknown_bound.worst_case_fraction understates source unknown bounds")

    mass = {
        "initial_mass_kg": initial,
        "closure_tolerance_kg": tolerance,
        "denominator_policy": DENOMINATOR_POLICY,
        **buckets,
    }
    unknown_bound = {
        "denominator_policy": DENOMINATOR_POLICY,
        "observed_fraction": observed,
        "worst_case_fraction": worst,
        "limit": limit,
        "includes_right_censored_mass": includes_censored,
    }
    source_coverage = {
        "schema": SOURCE_SUMMARY_SCHEMA,
        "family": family,
        "case_id": case_id,
        "denominator_policy": DENOMINATOR_POLICY,
        "source_count": len(normalized_rows),
        "initial_mass_kg": initial,
        "source_mass_sum_kg": source_mass_total,
        "maximum_source_unknown_fraction": maximum_source_unknown,
        "source_unknown_gate_pass": maximum_source_unknown <= UNKNOWN_FRACTION_LIMIT,
        "rows": normalized_rows,
    }
    return mass, unknown_bound, source_coverage, family, case_id


def _transfer_matrix(value: Any, family: str, case_id: str) -> dict[str, Any]:
    matrix = _object(value, "transfer_matrix")
    _schema(matrix, TRANSFER_MATRIX_SCHEMA, "transfer_matrix")
    _validate_component_identity(matrix, "transfer_matrix", family, case_id)
    _policy(
        _required(matrix, "denominator_policy", "transfer_matrix"),
        "transfer_matrix.denominator_policy",
    )
    orientation = _string(
        _required(matrix, "orientation", "transfer_matrix"),
        "transfer_matrix.orientation",
    )
    if orientation != "rows_origin_columns_terminal":
        raise ValueError("transfer_matrix.orientation must be rows_origin_columns_terminal")
    origins = _list(_required(matrix, "origin_labels", "transfer_matrix"), "transfer_matrix.origin_labels")
    terminals = _list(
        _required(matrix, "terminal_labels", "transfer_matrix"),
        "transfer_matrix.terminal_labels",
    )
    if origins != list(BUCKETS) or terminals != list(BUCKETS):
        raise ValueError("transfer_matrix axes must explicitly use source, destination and unknown order")
    values = _list(_required(matrix, "mass_kg", "transfer_matrix"), "transfer_matrix.mass_kg")
    if len(values) != len(BUCKETS):
        raise ValueError("transfer_matrix.mass_kg must have exactly three rows")
    normalized: list[list[float]] = []
    for row_index, raw_row in enumerate(values):
        row = _list(raw_row, f"transfer_matrix.mass_kg[{row_index}]")
        if len(row) != len(BUCKETS):
            raise ValueError("transfer_matrix.mass_kg must have exactly three columns")
        normalized_row = []
        for column_index, raw in enumerate(row):
            amount = _number(raw, f"transfer_matrix.mass_kg[{row_index}][{column_index}]")
            if amount < 0:
                raise ValueError("transfer_matrix masses cannot be negative")
            normalized_row.append(amount)
        normalized.append(normalized_row)
    return {
        "orientation": orientation,
        "row_labels": list(BUCKETS),
        "column_labels": list(BUCKETS),
        "mass_kg": normalized,
    }


def _event_map(value: Any, family: str, case_id: str) -> dict[str, Any]:
    events = _object(value, "events")
    _schema(events, EVENTS_SCHEMA, "events")
    _validate_component_identity(events, "events", family, case_id)
    output: dict[str, Any] = {}
    for event_name in EVENTS:
        event = _object(_required(events, event_name, "events"), f"events.{event_name}")
        definition = _string(
            _required(event, "definition", f"events.{event_name}"),
            f"events.{event_name}.definition",
        )
        _policy(
            _required(event, "denominator_policy", f"events.{event_name}"),
            f"events.{event_name}.denominator_policy",
        )
        cdf_policy = _policy(
            _required(event, "cdf_denominator_policy", f"events.{event_name}"),
            f"events.{event_name}.cdf_denominator_policy",
        )
        times = _list(
            _required(event, "time_s", f"events.{event_name}"),
            f"events.{event_name}.time_s",
        )
        lowers = _list(
            _required(event, "lower", f"events.{event_name}"),
            f"events.{event_name}.lower",
        )
        uppers = _list(
            _required(event, "upper", f"events.{event_name}"),
            f"events.{event_name}.upper",
        )
        if not times or len(times) != len(lowers) or len(lowers) != len(uppers):
            raise ValueError(f"events.{event_name} CDF arrays must be non-empty and have equal lengths")
        normalized_times = [_number(item, f"events.{event_name}.time_s[{i}]") for i, item in enumerate(times)]
        normalized_lower = [_fraction(item, f"events.{event_name}.lower[{i}]") for i, item in enumerate(lowers)]
        normalized_upper = [_fraction(item, f"events.{event_name}.upper[{i}]") for i, item in enumerate(uppers)]

        censor = _object(
            _required(event, "censor", f"events.{event_name}"),
            f"events.{event_name}.censor",
        )
        censor_type = _string(
            _required(censor, "type", f"events.{event_name}.censor"),
            f"events.{event_name}.censor.type",
        )
        if censor_type not in ("none", "right"):
            raise ValueError(f"events.{event_name}.censor.type must be 'none' or 'right'")
        censor_fraction = _fraction(
            _required(censor, "fraction", f"events.{event_name}.censor"),
            f"events.{event_name}.censor.fraction",
        )
        censor_policy = _string(
            _required(censor, "policy", f"events.{event_name}.censor"),
            f"events.{event_name}.censor.policy",
        )
        expected_policy = (
            "no_censoring"
            if censor_type == "none"
            else "right_censored_mass_remains_in_denominator"
        )
        if censor_policy != expected_policy:
            raise ValueError(f"events.{event_name}.censor.policy does not match censor.type")
        if censor_type == "none" and censor_fraction != 0.0:
            raise ValueError(f"events.{event_name}.censor.fraction must be zero for no censoring")
        if censor_type == "right" and censor_fraction <= 0.0:
            raise ValueError(f"events.{event_name}.censor.fraction must be positive for right censoring")
        counts_as_acceptance = _boolean(
            _required(censor, "counts_as_acceptance", f"events.{event_name}.censor"),
            f"events.{event_name}.censor.counts_as_acceptance",
        )
        if counts_as_acceptance:
            raise ValueError(f"events.{event_name}.censor.counts_as_acceptance must be false")
        output[event_name] = {
            "definition": definition,
            "denominator_policy": DENOMINATOR_POLICY,
            "cdf": {
                "time_s": normalized_times,
                "lower": normalized_lower,
                "upper": normalized_upper,
                "denominator_policy": cdf_policy,
            },
            "censor": {
                "type": censor_type,
                "fraction": censor_fraction,
                "policy": expected_policy,
                "counts_as_acceptance": False,
            },
        }
    return output


def _path_error(value: Any, family: str, case_id: str) -> dict[str, Any]:
    path = _object(value, "path_error")
    _schema(path, PATH_ERROR_SCHEMA, "path_error")
    _validate_component_identity(path, "path_error", family, case_id)
    _policy(
        _required(path, "denominator_policy", "path_error"),
        "path_error.denominator_policy",
    )
    coverage_policy = _string(
        _required(path, "coverage_policy", "path_error"),
        "path_error.coverage_policy",
    )
    if coverage_policy != PATH_COVERAGE_POLICY:
        raise ValueError(f"path_error.coverage_policy must be {PATH_COVERAGE_POLICY!r}")
    maximum = _number(
        _required(path, "maximum_abs_error_m", "path_error"),
        "path_error.maximum_abs_error_m",
    )
    tolerance = _number(
        _required(path, "tolerance_m", "path_error"),
        "path_error.tolerance_m",
    )
    if maximum < 0 or tolerance < 0:
        raise ValueError("path_error magnitudes cannot be negative")
    coverage = _fraction(
        _required(path, "common_reliable_mass_coverage", "path_error"),
        "path_error.common_reliable_mass_coverage",
    )
    minimum = _fraction(
        _required(path, "minimum_common_reliable_mass_coverage", "path_error"),
        "path_error.minimum_common_reliable_mass_coverage",
    )
    return {
        "denominator_policy": DENOMINATOR_POLICY,
        "coverage_policy": PATH_COVERAGE_POLICY,
        "maximum_abs_error_m": maximum,
        "tolerance_m": tolerance,
        "common_reliable_mass_coverage": coverage,
        "minimum_common_reliable_mass_coverage": minimum,
    }


def _family_fields(value: Any) -> tuple[str, str, dict[str, Any]]:
    fields = _object(value, "family_fields")
    _schema(fields, FAMILY_FIELDS_SCHEMA, "family_fields")
    family, case_id = _identity(fields, "family_fields")
    family_specific = _object(
        _required(fields, "family_specific", "family_fields"),
        "family_fields.family_specific",
    )
    if not family_specific:
        raise ValueError("family_fields.family_specific must not be empty")
    forbidden = sorted(CLAIM_FIELDS.intersection(fields))
    if forbidden:
        raise ValueError("family_fields cannot carry qualification or execution claims: " + ", ".join(forbidden))
    return family, case_id, deepcopy(family_specific)


def adapt_material_output(
    source_summary: dict[str, Any],
    transfer_matrix: dict[str, Any],
    events: dict[str, Any],
    path_error: dict[str, Any],
    family_fields: dict[str, Any],
) -> dict[str, Any]:
    """Normalize five complete JSON components into the v1 output contract.

    The positional components are intentional: there are no optional legacy
    inputs or fallback field names.  Missing data raises ``ValueError``.
    Scientific gate failures in otherwise well-formed data remain in the
    returned diagnostic receipt with ``passed=False``.
    """
    components = {
        "source_summary": source_summary,
        "transfer_matrix": transfer_matrix,
        "events": events,
        "path_error": path_error,
        "family_fields": family_fields,
    }
    for name, component in components.items():
        _assert_json_like(component, name)

    family, case_id, family_specific = _family_fields(family_fields)
    source_mass, unknown_bound, source_coverage, source_family, source_case = _source_summary(source_summary)
    if source_family != family or source_case != case_id:
        raise ValueError("source_summary family/case identity does not match family_fields")
    normalized_matrix = _transfer_matrix(transfer_matrix, family, case_id)
    normalized_events = _event_map(events, family, case_id)
    normalized_path = _path_error(path_error, family, case_id)

    payload = {
        "schema": OUTPUT_SCHEMA,
        "family": family,
        "case_id": case_id,
        "diagnostic_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "mass": source_mass,
        "transfer_matrix": normalized_matrix,
        "events": normalized_events,
        "unknown_bound": unknown_bound,
        "path_error": normalized_path,
        "family_specific": family_specific,
    }
    result = evaluate_material_output(payload)

    # These are non-qualifying, source-coverage extensions.  They preserve the
    # complete denominator audit without asking the target contract to infer
    # per-source rows from an aggregate unknown fraction.
    result["source_coverage"] = source_coverage
    result["adapter"] = {
        "schema": ADAPTER_SCHEMA,
        "input_schemas": {
            "source_summary": SOURCE_SUMMARY_SCHEMA,
            "transfer_matrix": TRANSFER_MATRIX_SCHEMA,
            "events": EVENTS_SCHEMA,
            "path_error": PATH_ERROR_SCHEMA,
            "family_fields": FAMILY_FIELDS_SCHEMA,
        },
        "normalization": "explicit_fields_only_no_legacy_fallbacks",
    }
    result["execution_constraints"]["json_source_only"] = True
    result["execution_constraints"]["hdf5_opened"] = False
    result["execution_constraints"]["solver_started"] = False
    result["execution_constraints"]["training_started"] = False
    result["execution_constraints"]["registry_mutation"] = 0
    result["execution_constraints"]["ledger_mutation"] = 0
    result["execution_constraints"]["t2_credit_registered"] = 0
    if (
        result.get("diagnostic_only") is not True
        or result.get("qualification_claim") != "none"
        or result.get("qualification_credit") != 0
    ):
        raise AssertionError("adapter emitted a non-diagnostic or nonzero qualification result")
    return result


def normalize_material_output(
    source_summary: dict[str, Any],
    transfer_matrix: dict[str, Any],
    events: dict[str, Any],
    path_error: dict[str, Any],
    family_fields: dict[str, Any],
) -> dict[str, Any]:
    """Explicit-name alias for :func:`adapt_material_output`."""
    return adapt_material_output(source_summary, transfer_matrix, events, path_error, family_fields)


__all__ = [
    "ADAPTER_SCHEMA",
    "EVENTS_SCHEMA",
    "FAMILY_FIELDS_SCHEMA",
    "PATH_ERROR_SCHEMA",
    "SOURCE_SUMMARY_SCHEMA",
    "TRANSFER_MATRIX_SCHEMA",
    "adapt_material_output",
    "normalize_material_output",
]
