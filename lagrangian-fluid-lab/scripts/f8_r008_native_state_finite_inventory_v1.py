"""Synthetic-input inventory diagnostics for the F8 R008 finite-value scope.

This additive v1 freezes which values the R008 finite scan must account for:
the three per-particle floating state arrays, the integer particle-ID array,
all floating BI4 metadata values, and all seven numeric acceleration-control
columns. It is intentionally not wired into native-integrity adjudication and
does not authenticate caller-supplied frozen case parameters.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
from typing import Any

from scripts import f8_r008_native_state_finite_scan_v1 as state_scan
from scripts import f8_r008_safe_bi4_decoder_v1 as decoder


SCHEMA = "core.cfd.f8.r008_native_state_finite_inventory.v1"
CONTROL_HEADER = (
    "#Time", "LinearAccX", "LinearAccY", "LinearAccZ",
    "AngularAccX", "AngularAccY", "AngularAccZ",
)
CONTROL_SAMPLES_PER_PERIOD = 64
MAX_CONTROL_ROWS = 1497  # Exact maximum across the frozen 15-row qualification matrix.
MAX_CONTROL_BYTES = 1024 * 1024
FLOAT_METADATA_TYPES = frozenset({11, 12, 22, 23})

STATE_ARRAYS = {
    "Pos": {"type_code": 22, "dtype": "<f4", "components": 3, "unit": "m",
            "semantic": "solver-saved particle position"},
    "Posd": {"type_code": 23, "dtype": "<f8", "components": 3, "unit": "m",
             "semantic": "solver-saved particle position"},
    "Vel": {"type_code": 22, "dtype": "<f4", "components": 3, "unit": "m/s",
            "semantic": "solver-saved particle velocity"},
    "Rhop": {"type_code": 11, "dtype": "<f4", "components": 1, "unit": "kg/m^3",
             "semantic": "solver-saved particle density"},
}
CONTROL_UNITS = ("s", "m/s^2", "m/s^2", "m/s^2", "rad/s^2", "rad/s^2", "rad/s^2")
CONTROL_SEMANTICS = (
    "simulation time at which the following accelerations apply",
    "x linear acceleration control", "y linear acceleration control", "z linear acceleration control",
    "x angular acceleration control", "y angular acceleration control", "z angular acceleration control",
)
_ROOT_METADATA_SEMANTICS = {
    "Data2dPosY": ("m", "out-of-plane coordinate for a 2D case"),
    "CasePosMin": ("m", "initial case bounding-box minimum"),
    "CasePosMax": ("m", "initial case bounding-box maximum"),
    "MapPosMin": ("m", "solver map bounding-box minimum"),
    "MapPosMax": ("m", "solver map bounding-box maximum"),
    "PeriXinc": ("m", "periodic-image translation vector along x"),
    "PeriYinc": ("m", "periodic-image translation vector along y"),
    "PeriZinc": ("m", "periodic-image translation vector along z"),
    "ViscoValue": ("native-model-dependent", "configured viscosity value; interpreted by ViscoType, not converted here"),
    "ViscoBoundFactor": ("dimensionless", "boundary-viscosity multiplier"),
    "Dp": ("m", "configured particle spacing"),
    "H": ("m", "configured smoothing length"),
    "B": ("native-model-dependent", "equation-of-state coefficient as stored by the solver"),
    "Rhop0": ("kg/m^3", "configured reference density"),
    "Gamma": ("dimensionless", "configured equation-of-state exponent"),
    "MassBound": ("kg", "configured bound-particle mass"),
    "MassFluid": ("kg", "configured fluid-particle mass"),
}
_PART_METADATA_SEMANTICS = {
    "TimeStep": ("s", "simulation time represented by this saved PART"),
    "RunTime": ("s", "elapsed solver runtime recorded for this PART"),
    "DomainMin": ("m", "PART computational-domain minimum"),
    "DomainMax": ("m", "PART computational-domain maximum"),
}


class NativeStateFiniteInventoryError(ValueError):
    """A synthetic R008 finite-inventory input violates the frozen shape."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeStateFiniteInventoryError(message)


def _positive_finite(value: Any, label: str) -> float:
    _require(type(value) in (int, float), f"{label} must be a positive finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise NativeStateFiniteInventoryError(
            f"{label} must be a positive finite number"
        ) from error
    _require(math.isfinite(number) and number > 0,
             f"{label} must be a positive finite number")
    return number


def _one_value(item: decoder.ItemRecord, name: str, type_code: int) -> Any:
    matches = [entry for entry in item.values if entry.name == name]
    _require(len(matches) == 1 and matches[0].type_code == type_code,
             f"raw BI4 {item.name}.{name} is missing, duplicated, or mistyped")
    return matches[0].value


def _validate_native_array_inventory(scan: decoder.ScanResult, case_np: int) -> decoder.ItemRecord:
    _require(type(case_np) is int and 0 < case_np <= decoder.MAX_ARRAY_COUNT,
             "frozen CaseNp is outside the reviewed BI4 particle bound")
    root = scan.root
    _require(root.name == "JPartDataBi4" and not root.arrays and len(root.children) == 1,
             "raw BI4 must have one JPartDataBi4 root and one PART item")
    part = root.children[0]
    _require(part.name.startswith("PART_") and not part.children,
             "raw BI4 child is not one flat PART item")
    _require(_one_value(root, "CaseNp", 10) == case_np,
             "raw BI4 CaseNp differs from the frozen case population")
    _require(_one_value(part, "Npok", 8) == case_np,
             "raw BI4 Npok differs from the frozen R008 frame population")
    _one_value(part, "TimeStep", 12)

    names = [array.name for array in part.arrays]
    _require(len(names) == len(set(names)), "raw BI4 PART contains duplicate array names")
    position_names = [name for name in ("Pos", "Posd") if names.count(name) == 1]
    _require(len(position_names) == 1 and names.count("Vel") == 1
             and names.count("Rhop") == 1 and names.count("Idp") == 1,
             "raw BI4 PART lacks exactly one required position, velocity, density, or ID array")
    expected_names = {position_names[0], "Vel", "Rhop", "Idp"}
    _require(set(names) == expected_names and len(scan.arrays) == len(part.arrays)
             and all(array.item_path == (root.name, part.name) for array in scan.arrays),
             "raw BI4 PART has an unclassified extension array or misplaced array")

    idp = next(array for array in part.arrays if array.name == "Idp")
    _require(idp.type_code == 8 and idp.count == case_np and idp.byte_count == case_np * 4,
             "raw BI4 Idp must be one uint32 identifier per frozen particle")
    for name in expected_names - {"Idp"}:
        array = next(array for array in part.arrays if array.name == name)
        contract = STATE_ARRAYS[name]
        _require(array.type_code == contract["type_code"] and array.count == case_np,
                 f"raw BI4 {name} type or particle population differs from inventory")
        _require(array.byte_count == case_np * contract["components"] * (4 if contract["dtype"] == "<f4" else 8),
                 f"raw BI4 {name} byte extent differs from inventory")
    return part


def _summarize_float_metadata(
    root: decoder.ItemRecord, part: decoder.ItemRecord, source_frame_sha256: str,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    finite_count = nonfinite_count = 0
    unclassified_count = 0
    for item in (root, part):
        for value in item.values:
            if value.type_code not in FLOAT_METADATA_TYPES:
                continue
            components = value.value if isinstance(value.value, tuple) else (value.value,)
            component_finite = [math.isfinite(float(component)) for component in components]
            this_finite = sum(component_finite)
            this_nonfinite = len(component_finite) - this_finite
            finite_count += this_finite
            nonfinite_count += this_nonfinite
            semantic_map = _ROOT_METADATA_SEMANTICS if item is root else _PART_METADATA_SEMANTICS
            unit, semantic = semantic_map.get(
                value.name,
                ("unclassified", "raw BI4 floating metadata; R008 field semantics are not classified"),
            )
            classified = value.name in semantic_map
            unclassified_count += int(not classified)
            type_name, dtype, _size, _triple = decoder.VALUE_INFO[value.type_code]
            records.append({
                "item_path": [root.name, *([] if item is root else [part.name])],
                "metadata_name": value.name,
                "type_code": value.type_code,
                "type_name": type_name,
                "dtype": dtype,
                "component_count": len(components),
                "unit": unit,
                "semantic": semantic,
                "semantics_classified": classified,
                "population": "one root/PART metadata field",
                "source_frame_sha256": source_frame_sha256,
                "finite_count": this_finite,
                "nonfinite_count": this_nonfinite,
            })
    return {
        "policy": "all IEEE floating scalar/vector metadata values in the root and selected PART are included; field identity, native dtype, unit and semantic are reported per entry",
        "records": records,
        "finite_count": finite_count,
        "nonfinite_count": nonfinite_count,
        "all_floating_metadata_finite": nonfinite_count == 0,
        "unclassified_field_count": unclassified_count,
        "all_floating_metadata_semantics_classified": unclassified_count == 0,
    }


def summarize_native_frame_fd(
    raw_fd: int,
    expected_frame_sha256: str,
    *,
    case_np: int,
) -> dict[str, Any]:
    """Inventory and stream-scan one already-held synthetic/raw BI4 frame.

    This function opens no paths. Its diagnostics cover every scalar in the
    fixed R008 primary arrays, all floating root/PART metadata, and the uint32
    particle-ID shape. Unknown arrays fail closed rather than being skipped.
    Separate ``PartExtra`` files are not inputs to this API and remain
    unclassified at the bundle level.
    """
    # Never accept a caller-constructed ScanResult: rebuild every descriptor
    # and metadata field from the held bytes whose digest is checked here.
    try:
        scan = decoder.scan_bi4_fd(raw_fd, expected_frame_sha256)
    except (OSError, ValueError, OverflowError) as error:
        raise NativeStateFiniteInventoryError(
            "held raw BI4 frame did not produce an internally scanned R008 tree"
        ) from error
    part = _validate_native_array_inventory(scan, case_np)
    scanned_arrays = state_scan.summarize_native_state_fd(
        raw_fd, expected_frame_sha256, scan, case_np=case_np,
    )
    arrays = []
    for array in scanned_arrays:
        contract = STATE_ARRAYS[array["array_name"]]
        arrays.append({
            **array,
            "unit": contract["unit"],
            "semantic": contract["semantic"],
            "population": "all CaseNp particles in this native PART frame",
            "source_frame_sha256": expected_frame_sha256,
        })
    metadata = _summarize_float_metadata(scan.root, part, expected_frame_sha256)
    return {
        "schema": SCHEMA,
        "status": "diagnostic_only_not_adjudicated",
        "source_frame_sha256": expected_frame_sha256,
        "case_np_claim": case_np,
        "array_inventory": {
            "population": "all CaseNp particles in the raw PART frame",
            "identifier_array": {
            "raw_name": "Idp", "type_code": 8, "dtype": "<u4",
            "particle_count": case_np,
            "unit": "unitless",
            "semantic": "uint32 particle identity; domain/uniqueness are separate integrity checks",
            "source_frame_sha256": expected_frame_sha256,
            "finite_semantics": "integer identity; not an IEEE floating-value tally",
            },
            "state_arrays": arrays,
            "all_required_state_values_finite": all(
                item["required_state_values_finite"] for item in arrays
            ),
            "unknown_or_extension_arrays": "rejected by this fixed R008 frame inventory",
        },
        "floating_metadata": metadata,
        "extension_file_policy": (
            "PartExtra and other separate auxiliary outputs are not scanned here; "
            "their presence must remain unresolved until separately inventoried"
        ),
        "frozen_case_parameters_authenticated": False,
        "source_build_runtime_authenticated": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


def summarize_control_table_bytes(
    payload: bytes,
    *,
    expected_t_end_s: float,
    expected_period_s: float,
) -> dict[str, Any]:
    """Count finite values in all seven R008 control columns on the T/64 grid.

    The expected horizon/period are untrusted parameters here. This parser
    checks table bytes and declared coverage only; it does not prove that the
    values came from the frozen pack or that a solver consumed the table.
    """
    _require(isinstance(payload, bytes) and 0 < len(payload) <= MAX_CONTROL_BYTES,
             "control table bytes are empty or exceed the inventory bound")
    t_end = _positive_finite(expected_t_end_s, "expected T_end")
    period = _positive_finite(expected_period_s, "expected period")
    control_dt = period / CONTROL_SAMPLES_PER_PERIOD
    _require(math.isfinite(control_dt) and control_dt > 0.0,
             "period divided by 64 underflows the representable control timestep")
    tick_ratio = t_end / control_dt
    _require(math.isfinite(tick_ratio), "R008 control horizon/timestep ratio is non-finite")
    end_tick = int(round(tick_ratio))
    _require(0 < end_tick < MAX_CONTROL_ROWS
             and math.isclose(end_tick * control_dt, t_end, rel_tol=0.0, abs_tol=1e-12),
             "declared R008 control horizon is outside the frozen T/64 grid bound")

    try:
        text = payload.decode("utf-8", errors="strict")
        rows = csv.reader(io.StringIO(text, newline=""), delimiter=";", strict=True)
        header = next(rows)
        _require(tuple(header) == CONTROL_HEADER, "control table header differs from the seven-column inventory")
        counts = [0] * len(CONTROL_HEADER)
        nonfinite = [0] * len(CONTROL_HEADER)
        expected_rows = end_tick + 1
        row_count = 0
        time_axis_matches = True
        last_time: float | None = None
        for tick, fields in enumerate(rows):
            _require(row_count < MAX_CONTROL_ROWS and tick < expected_rows,
                     "control table contains more rows than the frozen R008 horizon")
            _require(len(fields) == len(CONTROL_HEADER),
                     "control table row does not contain exactly seven fields")
            values: list[float] = []
            for index, token in enumerate(fields):
                _require(token != "" and token == token.strip(),
                         "control table contains an empty or whitespace-padded numeric field")
                try:
                    value = float(token)
                except ValueError as error:
                    raise NativeStateFiniteInventoryError(
                        "control table contains a nonnumeric field"
                    ) from error
                values.append(value)
                counts[index] += 1
                if not math.isfinite(value):
                    nonfinite[index] += 1
            if math.isfinite(values[0]):
                last_time = values[0]
                time_axis_matches = time_axis_matches and math.isclose(
                    values[0], tick * control_dt, rel_tol=0.0, abs_tol=1e-12,
                )
            else:
                time_axis_matches = False
            row_count += 1
    except (UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise NativeStateFiniteInventoryError("control table is not a valid bounded UTF-8 semicolon CSV") from error

    _require(row_count == expected_rows,
             "control table row count does not cover every T/64 sample through T_end")
    per_column = [
        {
            "name": name,
            "unit": CONTROL_UNITS[index],
            "semantic": CONTROL_SEMANTICS[index],
            "numeric_text_interpreted_as": "IEEE-754 binary64",
            "source_control_sha256": hashlib.sha256(payload).hexdigest(),
            "numeric_value_count": counts[index],
            "nonfinite_count": nonfinite[index],
            "all_values_finite": counts[index] == row_count and nonfinite[index] == 0,
        }
        for index, name in enumerate(CONTROL_HEADER)
    ]
    time_coverage = bool(
        time_axis_matches and per_column[0]["all_values_finite"]
        and last_time is not None
        and math.isclose(last_time, t_end, rel_tol=0.0, abs_tol=1e-12)
    )
    return {
        "schema": SCHEMA,
        "status": "diagnostic_only_not_adjudicated",
        "source_control_sha256": hashlib.sha256(payload).hexdigest(),
        "source_control_bytes": len(payload),
        "rows": row_count,
        "columns": per_column,
        "numeric_value_count": sum(counts),
        "nonfinite_value_count": sum(nonfinite),
        "all_seven_control_columns_finite": sum(nonfinite) == 0
        and all(count == row_count for count in counts),
        "declared_t_end_s": t_end,
        "declared_period_s": period,
        "control_dt_s": control_dt,
        "time_axis_covers_zero_to_t_end_on_t_over_64_grid": time_coverage,
        "frozen_control_binding_verified": False,
        "solver_control_consumption_verified": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


__all__ = [
    "CONTROL_HEADER", "CONTROL_SAMPLES_PER_PERIOD", "MAX_CONTROL_BYTES", "MAX_CONTROL_ROWS",
    "NativeStateFiniteInventoryError", "SCHEMA", "STATE_ARRAYS",
    "summarize_control_table_bytes", "summarize_native_frame_fd",
]
