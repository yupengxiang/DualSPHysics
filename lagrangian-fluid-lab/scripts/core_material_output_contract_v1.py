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
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


SCHEMA = "core.material.output_contract.v1"
OUTPUT_SCHEMA = SCHEMA
UNKNOWN_FRACTION_LIMIT = 0.01
MASS_CLOSURE_TOLERANCE_KG = 1.0e-9
DENOMINATOR_POLICY = "all_initial_mass"
PATH_COVERAGE_POLICY = "common_reliable_mass_over_all_initial_mass"
BUCKETS = ("source", "destination", "unknown")
EVENTS = ("first_passage", "return", "residence")
ADMISSION_SCHEMA = "core.material.output_admission.v1"
MATERIAL_ADMISSION_SCHEMA = ADMISSION_SCHEMA
ROOT_ADMISSION_SCHEMA = "core.material.root_admission.v1"
ROOT_PHYSICAL_CASE_ID = "__root__"
WINDOW_TOLERANCE_S = 1.0e-9
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CASE_ARTIFACT_ROLES = frozenset({"source_window", "material_output", "checkpoint"})


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


def _normalized_ids(value: Any, name: str) -> tuple[str, ...]:
    """Normalize an externally supplied denominator without trusting its order."""
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{name} must be a non-empty collection of ids")
    if not value:
        raise ValueError(f"{name} must not be empty")
    values = [_require_string(item, f"{name}[{index}]") for index, item in enumerate(value)]
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(values))


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("admission binding is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_root(value: Any) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError("artifact_root must be a path")
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("artifact_root must be an existing directory")
    return root


def _verify_artifact(
    value: Any,
    *,
    root: Path,
    name: str,
    expected_role: str | None = None,
    expected_physical_case_id: str | None = None,
) -> dict[str, Any]:
    """Verify one relative, content-addressed artifact without following root escapes."""
    binding = _require_object(value, name)
    artifact_id = _require_string(binding.get("artifact_id"), f"{name}.artifact_id")
    role = _require_string(binding.get("role"), f"{name}.role")
    if expected_role is not None and role != expected_role:
        raise ValueError(f"{name}.role must be {expected_role!r}")
    if role not in _CASE_ARTIFACT_ROLES and role != "root_admission":
        raise ValueError(f"{name}.role is not a registered artifact role")
    physical_case_id = _require_string(
        binding.get("physical_case_id"), f"{name}.physical_case_id"
    )
    if expected_physical_case_id is not None and physical_case_id != expected_physical_case_id:
        raise ValueError(
            f"{name}.physical_case_id does not match {expected_physical_case_id!r}"
        )
    path_text = _require_string(binding.get("path"), f"{name}.path")
    path = Path(path_text).expanduser()
    if path.is_absolute():
        raise ValueError(f"{name}.path must be relative to artifact_root")
    resolved = (root / path).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{name}.path escapes artifact_root") from exc
    if not resolved.is_file():
        raise ValueError(f"{name}.path does not name a regular file")
    declared_bytes = _positive_integer(binding.get("bytes"), f"{name}.bytes")
    declared_sha256 = _sha256(binding.get("sha256"), f"{name}.sha256")
    actual_bytes = resolved.stat().st_size
    if declared_bytes != actual_bytes:
        raise ValueError(f"{name}.bytes does not match the artifact")
    actual_sha256 = _file_sha256(resolved)
    if declared_sha256 != actual_sha256:
        raise ValueError(f"{name}.sha256 does not match the artifact")
    return {
        "artifact_id": artifact_id,
        "role": role,
        "physical_case_id": physical_case_id,
        "path": relative.as_posix(),
        "sha256": actual_sha256,
        "bytes": actual_bytes,
    }


def _source_coverage_gate(
    payload: dict[str, Any],
    base: dict[str, Any],
    required_source_ids: tuple[str, ...],
) -> tuple[bool, list[str], dict[str, Any]]:
    coverage = payload.get("source_coverage")
    failures: list[str] = []
    if not isinstance(coverage, dict):
        return False, ["source_coverage_missing"], {"source_count": 0, "rows": []}

    try:
        if coverage.get("denominator_policy") != DENOMINATOR_POLICY:
            failures.append("source_denominator_policy")
        if coverage.get("family") != base["family"]:
            failures.append("source_coverage_family")
        if coverage.get("case_id") != base["case_id"]:
            failures.append("source_coverage_case_id")
        declared = coverage.get("required_source_ids")
        if declared != list(required_source_ids):
            failures.append("source_denominator_ids")
        rows = coverage.get("rows")
        if not isinstance(rows, list) or not rows:
            failures.append("source_rows_missing")
            rows = []
        seen: set[str] = set()
        total_mass = 0.0
        maximum_unknown = 0.0
        normalized_rows: list[dict[str, Any]] = []
        for index, raw in enumerate(rows):
            row = _require_object(raw, f"source_coverage.rows[{index}]")
            source_id = _require_string(
                row.get("source_id"), f"source_coverage.rows[{index}].source_id"
            )
            if source_id in seen:
                failures.append("source_row_duplicate")
            seen.add(source_id)
            if row.get("denominator_policy") != DENOMINATOR_POLICY:
                failures.append("source_row_denominator_policy")
            source_mass = _finite_number(
                row.get("initial_mass_kg"),
                f"source_coverage.rows[{index}].initial_mass_kg",
            )
            if source_mass <= 0:
                failures.append("source_row_mass")
            unknown = _bounded(
                row.get("unknown_fraction_max"),
                f"source_coverage.rows[{index}].unknown_fraction_max",
            )
            total_mass += source_mass
            maximum_unknown = max(maximum_unknown, unknown)
            normalized_rows.append(
                {
                    "source_id": source_id,
                    "initial_mass_kg": source_mass,
                    "unknown_fraction_max": unknown,
                    "denominator_policy": DENOMINATOR_POLICY,
                }
            )
        if seen != set(required_source_ids):
            failures.append("source_row_coverage")
        initial_mass = base["mass"]["initial_mass_kg"]
        if not _close(total_mass, initial_mass, MASS_CLOSURE_TOLERANCE_KG):
            failures.append("source_denominator_mass_closure")
        if maximum_unknown > UNKNOWN_FRACTION_LIMIT:
            failures.append("source_unknown_gate")
        for field, expected in (
            ("source_count", len(required_source_ids)),
            ("initial_mass_kg", initial_mass),
            ("source_mass_sum_kg", total_mass),
        ):
            if field in coverage:
                actual = coverage[field]
                if field == "source_count":
                    if isinstance(actual, bool) or not isinstance(actual, int) or actual != expected:
                        failures.append(f"source_coverage_{field}")
                elif not _close(_finite_number(actual, f"source_coverage.{field}"), expected, MASS_CLOSURE_TOLERANCE_KG):
                    failures.append(f"source_coverage_{field}")
    except ValueError as exc:
        failures.append(str(exc))
        normalized_rows = []
        total_mass = 0.0
        maximum_unknown = 1.0

    normalized = {
        "schema": coverage.get("schema"),
        "denominator_policy": coverage.get("denominator_policy"),
        "required_source_ids": list(required_source_ids),
        "source_count": len(normalized_rows),
        "source_mass_sum_kg": total_mass,
        "maximum_source_unknown_fraction": maximum_unknown,
        "rows": normalized_rows,
    }
    return not failures, sorted(set(failures)), normalized


def _full_window_gate(
    payload: dict[str, Any],
    base: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    expected_full_window_s: float,
) -> tuple[bool, list[str], dict[str, Any] | None]:
    failures: list[str] = []
    window = payload.get("full_window")
    if not isinstance(window, dict):
        return False, ["full_window_missing"], None
    start = end = observed_start = observed_end = None
    frame_start = frame_end = frame_count = None
    source_id = material_id = None
    try:
        if window.get("required") is not True:
            failures.append("full_window_not_required")
        if window.get("complete") is not True:
            failures.append("full_window_incomplete")
        start = _finite_number(window.get("start_s"), "full_window.start_s")
        end = _finite_number(window.get("end_s"), "full_window.end_s")
        observed_start = _finite_number(
            window.get("observed_start_s"), "full_window.observed_start_s"
        )
        observed_end = _finite_number(
            window.get("observed_end_s"), "full_window.observed_end_s"
        )
        if not _close(start, 0.0, WINDOW_TOLERANCE_S):
            failures.append("full_window_start")
        if not _close(observed_start, start, WINDOW_TOLERANCE_S):
            failures.append("full_window_observed_start")
        if not _close(end, expected_full_window_s, WINDOW_TOLERANCE_S):
            failures.append("full_window_registered_end")
        if not _close(observed_end, end, WINDOW_TOLERANCE_S):
            failures.append("full_window_observed_end")
        family_window_key = "full_window_s" if base["family"] == "F3" else "event_window_s"
        family_window = _finite_number(
            base["family_specific"].get(family_window_key),
            f"family_specific.{family_window_key}",
        )
        if not _close(family_window, expected_full_window_s, WINDOW_TOLERANCE_S):
            failures.append("full_window_family_binding")
        frame_start = window.get("frame_start")
        frame_end = window.get("frame_end")
        frame_count = window.get("frame_count")
        if isinstance(frame_start, bool) or not isinstance(frame_start, int) or frame_start != 0:
            failures.append("full_window_frame_start")
        if isinstance(frame_end, bool) or not isinstance(frame_end, int) or frame_end < 1:
            failures.append("full_window_frame_end")
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 2:
            failures.append("full_window_frame_count")
        elif (
            isinstance(frame_start, int)
            and isinstance(frame_end, int)
            and frame_end >= 1
            and frame_count != frame_end - frame_start + 1
        ):
            failures.append("full_window_frame_count_binding")
        if window.get("native_rows_exact") is not True:
            failures.append("full_window_native_rows")
        if window.get("no_stride_or_synthetic_cadence") is not True:
            failures.append("full_window_cadence")
        source_id = _require_string(window.get("source_artifact_id"), "full_window.source_artifact_id")
        material_id = _require_string(
            window.get("material_artifact_id"), "full_window.material_artifact_id"
        )
        source = artifacts.get(source_id)
        material = artifacts.get(material_id)
        if source is None or source.get("role") != "source_window":
            failures.append("full_window_source_artifact_binding")
        if material is None or material.get("role") != "material_output":
            failures.append("full_window_material_artifact_binding")
        if source is not None and window.get("source_artifact_sha256") != source["sha256"]:
            failures.append("full_window_source_hash_binding")
        if material is not None and window.get("material_artifact_sha256") != material["sha256"]:
            failures.append("full_window_material_hash_binding")
        for event_name in EVENTS:
            event = base["events"][event_name]
            if event["censor"]["type"] != "none":
                failures.append(f"full_window_{event_name}_right_censored")
    except ValueError as exc:
        failures.append(str(exc))
        start = end = observed_start = observed_end = None
        frame_start = frame_end = frame_count = None
        source_id = material_id = None
    normalized = {
        "required": window.get("required"),
        "complete": window.get("complete"),
        "start_s": start,
        "end_s": end,
        "observed_start_s": observed_start,
        "observed_end_s": observed_end,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "frame_count": frame_count,
        "source_artifact_id": source_id,
        "material_artifact_id": material_id,
        "native_rows_exact": window.get("native_rows_exact"),
        "no_stride_or_synthetic_cadence": window.get("no_stride_or_synthetic_cadence"),
    }
    return not failures, sorted(set(failures)), normalized


def _root_admission_gate(
    root_admission: Any,
    *,
    root: Path,
    registered_physical_case_ids: tuple[str, ...],
    required_source_ids: tuple[str, ...],
    expected_full_window_s: float,
    binding_digest: str | None,
    used_artifact_ids: set[str],
    used_artifact_paths: set[str],
    used_artifact_hashes: set[str],
) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []
    if not isinstance(root_admission, dict):
        return False, ["root_admission_missing"], {}
    try:
        if root_admission.get("schema") != ROOT_ADMISSION_SCHEMA:
            failures.append("root_admission_schema")
        if root_admission.get("granted") is not True:
            failures.append("root_admission_not_granted")
        if root_admission.get("status") not in ("approved", "accepted"):
            failures.append("root_admission_status")
        if root_admission.get("T2_macro") is True or root_admission.get("qualified_T2_macro") is True:
            failures.append("root_admission_cannot_claim_t2")
        if root_admission.get("physical_case_ids") != list(registered_physical_case_ids):
            failures.append("root_admission_case_denominator")
        if root_admission.get("required_source_ids") != list(required_source_ids):
            failures.append("root_admission_source_denominator")
        declared_window = _finite_number(
            root_admission.get("full_window_s"), "root_admission.full_window_s"
        )
        if not _close(declared_window, expected_full_window_s, WINDOW_TOLERANCE_S):
            failures.append("root_admission_full_window")
        if binding_digest is None or root_admission.get("output_binding_sha256") != binding_digest:
            failures.append("root_admission_output_binding")
        artifact = _verify_artifact(
            root_admission.get("artifact"),
            root=root,
            name="root_admission.artifact",
            expected_role="root_admission",
            expected_physical_case_id=ROOT_PHYSICAL_CASE_ID,
        )
        if artifact["artifact_id"] in used_artifact_ids:
            failures.append("root_admission_artifact_reused")
        if artifact.get("path") in used_artifact_paths:
            failures.append("root_admission_artifact_path_reused")
        if artifact.get("sha256") in used_artifact_hashes:
            failures.append("root_admission_artifact_hash_reused")
        used_artifact_ids.add(artifact["artifact_id"])
        used_artifact_paths.add(artifact["path"])
        used_artifact_hashes.add(artifact["sha256"])
    except (ValueError, OSError) as exc:
        failures.append(str(exc))
        artifact = {}
    normalized = {
        "schema": root_admission.get("schema"),
        "granted": root_admission.get("granted"),
        "status": root_admission.get("status"),
        "physical_case_ids": root_admission.get("physical_case_ids"),
        "required_source_ids": root_admission.get("required_source_ids"),
        "full_window_s": root_admission.get("full_window_s"),
        "output_binding_sha256": root_admission.get("output_binding_sha256"),
        "artifact": artifact,
    }
    return not failures, sorted(set(failures)), normalized


def audit_material_output_contract(
    outputs: Any,
    *,
    registered_physical_case_ids: Any,
    required_source_ids: Any,
    artifact_root: str | Path,
    expected_full_window_s: Any,
    root_admission: Any,
) -> dict[str, Any]:
    """Audit a complete material-output collection without granting macro T2.

    ``evaluate_material_output`` is intentionally a single-case diagnostic
    contract.  This firewall is the only helper in this module that may inspect
    a collection.  Its denominators are supplied externally: a sidecar cannot
    shrink them by declaring a smaller list.  Every physical case must appear
    exactly once, every registered source must appear exactly once per case,
    every artifact is re-hashed under ``artifact_root``, and a separately
    supplied root-admission receipt must bind the resulting case/artifact/window
    digest.  A passing audit is an admission/readiness observation only;
    ``T2_macro`` remains false and no registry or ledger is touched.
    """
    registered_ids = _normalized_ids(registered_physical_case_ids, "registered_physical_case_ids")
    source_ids = _normalized_ids(required_source_ids, "required_source_ids")
    root = _artifact_root(artifact_root)
    expected_window = _finite_number(expected_full_window_s, "expected_full_window_s")
    if expected_window <= 0:
        raise ValueError("expected_full_window_s must be positive")
    if not isinstance(outputs, list):
        raise ValueError("outputs must be a list; one sidecar is not a collection admission")

    physical_ids = [
        item.get("physical_case_id") if isinstance(item, dict) else None for item in outputs
    ]
    valid_physical_ids = [item for item in physical_ids if isinstance(item, str) and item.strip()]
    physical_unique = len(valid_physical_ids) == len(set(valid_physical_ids)) == len(outputs)
    case_ids = [item.get("case_id") if isinstance(item, dict) else None for item in outputs]
    case_unique = (
        len(case_ids) == len(set(case_ids))
        and all(isinstance(item, str) and item.strip() for item in case_ids)
    )
    registered_coverage = set(valid_physical_ids) == set(registered_ids) and len(outputs) == len(registered_ids)

    case_reports: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    used_artifact_ids: set[str] = set()
    used_artifact_paths: set[str] = set()
    used_artifact_hashes: set[str] = set()
    for index, raw in enumerate(outputs):
        failures: list[str] = []
        if not isinstance(raw, dict):
            case_reports.append(
                {"index": index, "physical_case_id": None, "case_id": None, "passed": False,
                 "failure_reasons": ["output_not_object"], "gates": {}}
            )
            continue
        physical_case_id = raw.get("physical_case_id")
        case_id = raw.get("case_id")
        try:
            physical_case_id = _require_string(physical_case_id, f"outputs[{index}].physical_case_id")
            case_id = _require_string(case_id, f"outputs[{index}].case_id")
            base = evaluate_material_output(raw)
            base_pass = bool(base["passed"])
            if not base_pass:
                failures.extend(f"base_{reason}" for reason in base["failure_reasons"])
            if raw.get("diagnostic_only") is not True or raw.get("qualification_claim") != "none":
                failures.append("diagnostic_or_claimed_output")
            source_pass, source_failures, source_summary = _source_coverage_gate(
                raw, base, source_ids
            )
            failures.extend(source_failures)
            artifact_rows = raw.get("artifact_bindings")
            artifacts: dict[str, dict[str, Any]] = {}
            artifact_gate_pass = True
            if not isinstance(artifact_rows, list) or not artifact_rows:
                failures.append("artifact_bindings_missing")
                artifact_gate_pass = False
            else:
                for artifact_index, artifact_row in enumerate(artifact_rows):
                    try:
                        normalized = _verify_artifact(
                            artifact_row,
                            root=root,
                            name=f"outputs[{index}].artifact_bindings[{artifact_index}]",
                            expected_physical_case_id=physical_case_id,
                        )
                        if normalized["artifact_id"] in used_artifact_ids:
                            raise ValueError("artifact_id is reused across material cases")
                        if normalized["path"] in used_artifact_paths:
                            raise ValueError("artifact path is reused across material cases")
                        if normalized["sha256"] in used_artifact_hashes:
                            raise ValueError("artifact hash is reused across material cases")
                        used_artifact_ids.add(normalized["artifact_id"])
                        used_artifact_paths.add(normalized["path"])
                        used_artifact_hashes.add(normalized["sha256"])
                        artifacts[normalized["artifact_id"]] = normalized
                    except (ValueError, OSError) as exc:
                        failures.append(str(exc))
                        artifact_gate_pass = False
            roles = {item["role"] for item in artifacts.values()}
            if not {"source_window", "material_output"} <= roles:
                failures.append("required_artifact_roles_missing")
                artifact_gate_pass = False
            window_pass, window_failures, window_summary = _full_window_gate(
                raw, base, artifacts, expected_window
            )
            failures.extend(window_failures)
            if source_pass is False:
                failures.extend(f"source_{reason}" for reason in source_failures)
            case_pass = not failures
            if case_pass and window_summary is not None:
                source_artifact = artifacts[window_summary["source_artifact_id"]]
                material_artifact = artifacts[window_summary["material_artifact_id"]]
                bindings.append(
                    {
                        "physical_case_id": physical_case_id,
                        "case_id": case_id,
                        "family": base["family"],
                        "source_artifact_sha256": source_artifact["sha256"],
                        "material_artifact_sha256": material_artifact["sha256"],
                        "full_window": window_summary,
                    }
                )
            case_reports.append(
                {
                    "index": index,
                    "physical_case_id": physical_case_id,
                    "case_id": case_id,
                    "family": base.get("family"),
                    "passed": case_pass,
                    "failure_reasons": sorted(set(failures)),
                    "gates": {
                        "base_output_contract": base_pass,
                        "source_coverage": source_pass,
                        "artifact_hash_bytes": artifact_gate_pass,
                        "full_window_binding": window_pass,
                    },
                    "source_coverage": source_summary,
                    "full_window": window_summary,
                    "artifacts": sorted(artifacts.values(), key=lambda item: item["artifact_id"]),
                }
            )
        except (ValueError, OSError) as exc:
            failures.append(str(exc))
            case_reports.append(
                {
                    "index": index,
                    "physical_case_id": physical_case_id,
                    "case_id": case_id,
                    "passed": False,
                    "failure_reasons": sorted(set(failures)),
                    "gates": {},
                }
            )

    output_binding_digest = None
    if len(bindings) == len(outputs) and all(item["passed"] for item in case_reports):
        output_binding_digest = _canonical_digest(sorted(bindings, key=lambda item: item["physical_case_id"]))
    root_pass, root_failures, root_summary = _root_admission_gate(
        root_admission,
        root=root,
        registered_physical_case_ids=registered_ids,
        required_source_ids=source_ids,
        expected_full_window_s=expected_window,
        binding_digest=output_binding_digest,
        used_artifact_ids=used_artifact_ids,
        used_artifact_paths=used_artifact_paths,
        used_artifact_hashes=used_artifact_hashes,
    )
    all_source_pass = bool(case_reports) and all(
        report.get("gates", {}).get("source_coverage") is True for report in case_reports
    )
    all_artifact_pass = bool(case_reports) and all(
        report.get("gates", {}).get("artifact_hash_bytes") is True for report in case_reports
    )
    all_window_pass = bool(case_reports) and all(
        report.get("gates", {}).get("full_window_binding") is True for report in case_reports
    )
    base_pass = bool(case_reports) and all(
        report.get("gates", {}).get("base_output_contract") is True for report in case_reports
    )
    gates = {
        "diagnostic_sidecar_block": True,
        "physical_case_uniqueness": physical_unique and case_unique,
        "registered_physical_case_coverage": registered_coverage,
        "source_coverage": all_source_pass,
        "artifact_hash_bytes": all_artifact_pass,
        "root_admission": root_pass,
        "full_window_binding": all_window_pass,
        "base_output_contract": base_pass,
    }
    failures = [name for name, passed in gates.items() if not passed]
    if not physical_unique:
        failures.append("duplicate_or_missing_physical_case_id")
    if not case_unique:
        failures.append("duplicate_or_missing_case_id")
    if not registered_coverage:
        failures.append("registered_physical_case_denominator")
    failures.extend(f"root_{reason}" for reason in root_failures)
    return {
        "schema": ADMISSION_SCHEMA,
        "status": "admission_ready_but_non_qualifying" if not failures else "blocked_for_macro_t2",
        "diagnostic_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "admission_pass": not failures,
        "macro_t2_upgrade_blocked": True,
        "failure_reasons": sorted(set(failures)),
        "gates": gates,
        "registered_physical_case_ids": list(registered_ids),
        "required_source_ids": list(source_ids),
        "expected_full_window_s": expected_window,
        "physical_case_ids": sorted(item for item in valid_physical_ids),
        "case_count": len(outputs),
        "case_reports": case_reports,
        "output_binding_sha256": output_binding_digest,
        "root_admission": root_summary,
        "execution_constraints": {
            "json_source_only": True,
            "solver_started": False,
            "gpu_started": False,
            "training_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit_registered": 0,
        },
    }


def audit_material_output_admission(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Explicit-name alias for :func:`audit_material_output_contract`."""
    return audit_material_output_contract(*args, **kwargs)


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
    "ADMISSION_SCHEMA",
    "DENOMINATOR_POLICY",
    "EVENTS",
    "MATERIAL_ADMISSION_SCHEMA",
    "MASS_CLOSURE_TOLERANCE_KG",
    "OUTPUT_SCHEMA",
    "PATH_COVERAGE_POLICY",
    "ROOT_ADMISSION_SCHEMA",
    "ROOT_PHYSICAL_CASE_ID",
    "SCHEMA",
    "UNKNOWN_FRACTION_LIMIT",
    "WINDOW_TOLERANCE_S",
    "audit_material_output_admission",
    "audit_material_output_contract",
    "evaluate_material_output",
    "validate_material_output",
    "validate_material_output_diagnostic",
]
