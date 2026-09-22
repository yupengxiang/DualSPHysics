#!/usr/bin/env python3
"""Frozen, fail-closed energy consistency contract for F7 torque evidence."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


SCHEMA = "core.f7.pump.energy_consistency.evaluator.v1"
RELATIVE_TOLERANCE = 0.10
ABSOLUTE_FLOOR_J = 1.0e-12


def validate_energy_rows(rows: Iterable[Mapping[str, Any]], *, expected_times: Iterable[float]) -> dict[str, Any]:
    """Evaluate a pre-aligned energy sidecar without reading external files."""
    actual = list(rows)
    expected = [float(value) for value in expected_times]
    required = ("time_s", "tau_axis_Nm", "omega_rad_s", "delta_energy_fluid_J", "dissipation_J", "gravity_work_J")
    if not actual or len(actual) != len(expected):
        raise ValueError("energy sidecar is empty or incomplete")
    previous = None
    work = 0.0
    rhs = 0.0
    for index, (row, target_time) in enumerate(zip(actual, expected)):
        if any(field not in row for field in required):
            raise ValueError(f"energy row {index} is missing a required field")
        values = {field: float(row[field]) for field in required}
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError(f"energy row {index} contains a non-finite value")
        if abs(values["time_s"] - target_time) > 1.0e-9:
            raise ValueError(f"energy row {index} is not time aligned")
        if previous is not None and values["time_s"] <= previous:
            raise ValueError("energy time axis is not strictly increasing")
        previous = values["time_s"]
        work += values["tau_axis_Nm"] * values["omega_rad_s"]
        rhs += values["delta_energy_fluid_J"] + values["dissipation_J"] + values["gravity_work_J"]
    residual = work - rhs
    relative_residual = abs(residual) / max(abs(rhs), ABSOLUTE_FLOOR_J)
    if relative_residual > RELATIVE_TOLERANCE:
        raise ValueError("energy consistency residual exceeds the frozen tolerance")
    return {
        "schema": SCHEMA,
        "row_count": len(actual),
        "work_tau_dot_omega_J": work,
        "rhs_energy_balance_J": rhs,
        "residual_J": residual,
        "relative_residual": relative_residual,
        "relative_tolerance": RELATIVE_TOLERANCE,
        "absolute_floor_J": ABSOLUTE_FLOOR_J,
        "accepted": True,
    }


CONTRACT = {
    "schema": SCHEMA,
    "required_fields": ["time_s", "tau_axis_Nm", "omega_rad_s", "delta_energy_fluid_J", "dissipation_J", "gravity_work_J"],
    "equation": "integral(tau_axis_Nm * omega_rad_s dt) = delta_energy_fluid_J + dissipation_J + gravity_work_J",
    "relative_tolerance": RELATIVE_TOLERANCE,
    "absolute_floor_J": ABSOLUTE_FLOOR_J,
    "time_alignment_tolerance_s": 1.0e-9,
    "missing_nan_unaligned_policy": "hard failure and zero credit",
}
