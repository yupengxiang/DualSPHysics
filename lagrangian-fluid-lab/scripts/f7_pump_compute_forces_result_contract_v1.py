#!/usr/bin/env python3
"""Fail-closed parser contract for a future F7 ComputeForces result.

The contract is deliberately useful before execution: it freezes the accepted
normalized fields and rejects ambiguous units, missing samples, and non-finite
values.  It does not read native data or invoke ComputeForces.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


SCHEMA = "core.f7.pump.compute_forces.result_parser.v1"
TIME_TOLERANCE_S = 1.0e-9
REQUIRED_FIELDS = (
    "time_s",
    "force_fluid_x_N",
    "force_fluid_y_N",
    "force_fluid_z_N",
    "moment_pump_axis_in_Nm",
    "moment_pump_axis_ex_Nm",
)
RAW_HEADER_MAP = {
    "time_s": "Time [s]",
    "force_fluid_x_N": "ForceFluid X [N]",
    "force_fluid_y_N": "ForceFluid Y [N]",
    "force_fluid_z_N": "ForceFluid Z [N]",
    "moment_pump_axis_in_Nm": "Moment(pump_axis_in) [Nn]",
    "moment_pump_axis_ex_Nm": "Moment(pump_axis_ex) [Nn]",
}


def validate_headers(headers: Iterable[str]) -> dict[str, Any]:
    """Require the pre-registered raw header spelling and unit mapping."""
    observed = tuple(str(header) for header in headers)
    missing = [name for name in RAW_HEADER_MAP.values() if name not in observed]
    if missing:
        raise ValueError(f"missing pre-registered ComputeForces headers: {missing}")
    if any("[Nn]" in header for header in observed if "Moment(" in header):
        # The official help uses [Nn]; acceptance is allowed only through this
        # explicit parser mapping, never through an implicit rename.
        unit_mapping = "official Moment(s) [Nn] mapped to SI N*m by this frozen parser"
    else:
        unit_mapping = "no moment fields"
    return {
        "schema": SCHEMA,
        "raw_headers": list(observed),
        "normalized_fields": list(REQUIRED_FIELDS),
        "moment_unit_mapping": unit_mapping,
        "intrinsic_semantics": "axis moves and rotates with the body",
        "extrinsic_semantics": "axis moves but does not rotate",
        "sign_convention": "right-hand rule along the declared p1-to-p2 axis",
    }


def validate_rows(rows: Iterable[Mapping[str, Any]], *, expected_times: Iterable[float]) -> dict[str, Any]:
    """Validate finite, one-to-one time-aligned normalized result rows."""
    actual = list(rows)
    expected = [float(value) for value in expected_times]
    if not actual or len(actual) != len(expected):
        raise ValueError("ComputeForces result is empty or has an incomplete frame count")
    previous = None
    for index, (row, target_time) in enumerate(zip(actual, expected)):
        if any(field not in row for field in REQUIRED_FIELDS):
            raise ValueError(f"row {index} is missing a required normalized field")
        time_s = float(row["time_s"])
        if not math.isfinite(time_s) or abs(time_s - target_time) > TIME_TOLERANCE_S:
            raise ValueError(f"row {index} is not aligned to the frozen time axis")
        if previous is not None and time_s <= previous:
            raise ValueError("ComputeForces time axis is not strictly increasing")
        previous = time_s
        for field in REQUIRED_FIELDS[1:]:
            if not math.isfinite(float(row[field])):
                raise ValueError(f"row {index} has a non-finite {field}")
    return {
        "schema": SCHEMA,
        "row_count": len(actual),
        "time_alignment_tolerance_s": TIME_TOLERANCE_S,
        "finite_required_fields": True,
        "strictly_increasing_time": True,
    }


CONTRACT = {
    "schema": SCHEMA,
    "raw_header_map": RAW_HEADER_MAP,
    "normalized_fields": list(REQUIRED_FIELDS),
    "force_units": "N",
    "moment_units": "N*m",
    "official_help_label": "Moment(s) [Nn]",
    "moment_label_policy": "accept only through this explicit parser mapping; otherwise reject",
    "time_alignment_tolerance_s": TIME_TOLERANCE_S,
    "intrinsic_axis_semantics": "axis moves and rotates with body",
    "extrinsic_axis_semantics": "axis moves but does not rotate",
    "sign_convention": "right-hand rule along p1-to-p2",
    "empty_missing_duplicate_nan_policy": "hard failure and zero credit",
}
