#!/usr/bin/env python3
"""Evaluate frozen F8 R008 case metrics from a semantically verified v2 table FD.

This adapter deliberately does not open a table by pathname and does not call
the v1 GenCase-bound readers. The caller must keep the verified, read-only D
table descriptor open and pass the complete result from the v2 table verifier.
Density and valid are not metric inputs, but their semantic verification is a
required precondition. This module grants no T1 or qualification credit.
"""
from __future__ import annotations

import json
import fcntl
import math
import os
import stat
from pathlib import Path
from typing import Any, Mapping

import h5py
import numpy as np

from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_t1_metric_adapter_v1 as metric_v1
from scripts.f8_observation_window_parser_v2 import select_closed_native_window
from scripts.f8_womersley_oracle import (
    ChannelParameters,
    cross_sectional_flux_per_width,
    steady_velocity,
)


SCHEMA = "core.cfd.f8.r008_t1_metric_adapter.v2"
SCOPE_ID = metric_v1.SCOPE_ID
LAB = metric_v1.LAB
MAX_TABLE_BYTES = table_v2.MAX_TABLE_FILE_BYTES
MAX_HARMONIC_PLANES = 128
MAX_SELECTED_TIME_PARTICLE_CELLS = 3_000_000


class NativeFluidMetricAdapterError(ValueError):
    """The verified v2 table cannot be reduced under the frozen R008 metric contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeFluidMetricAdapterError(message)


def _identity(st: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)


def _attr_text(value: Any, name: str) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise NativeFluidMetricAdapterError(f"metric table {name} attribute is not valid UTF-8") from error
    _require(isinstance(value, str), f"metric table {name} attribute is not text")
    return value


def _frozen_inputs(case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    metric_v1._assert_frozen_inputs()
    from scripts import f8_r008_t1_metric_adapter_review_v1 as metric_v1_review

    review_receipt = metric_v1_review.verify_receipt()
    reviewer = review_receipt.get("reviewer", {})
    _require(review_receipt.get("status") == "independent_static_review_passed_no_execution"
             and reviewer.get("model") == "gpt-5.6-terra"
             and reviewer.get("reasoning_effort") == "high"
             and reviewer.get("verdict") == "PASS",
             "reused v1 metric helpers are not bound to the immutable Terra High v1 review")
    scope = json.loads(metric_v1.FROZEN_SCOPE_RECEIPT.read_text(encoding="utf-8"))
    parameters = json.loads(metric_v1.FROZEN_PARAMETER_CONTRACT.read_text(encoding="utf-8"))
    _require(scope.get("scope_id") == SCOPE_ID and isinstance(scope.get("matrix"), dict),
             "frozen R008 metric scope is malformed")
    rows = scope["matrix"].get("rows")
    _require(isinstance(rows, list), "frozen R008 metric rows are absent")
    matches = [row for row in rows if isinstance(row, dict) and row.get("case_id") == case_id]
    _require(len(matches) == 1, "case_id is not exactly one row in the frozen R008 qualification matrix")
    _require(isinstance(parameters, dict)
             and parameters.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
             "pinned F8 parameter contract is malformed")
    return matches[0], parameters


def _validate_table_verification(
    verified: Mapping[str, Any], *, case_id: str, expected_bytes: int, expected_sha256: str,
) -> tuple[int, int]:
    required_true = (
        "full_time_axis_matches", "fluid_id_projection_matches",
        "position_velocity_density_mass_recomputed", "all_valid",
    )
    _require(verified.get("schema") == table_v2.SCHEMA
             and verified.get("table_schema") == table_v2.TABLE_SCHEMA
             and verified.get("case_id") == case_id
             and verified.get("table_bytes") == expected_bytes
             and verified.get("table_sha256") == expected_sha256
             and all(verified.get(key) is True for key in required_true)
             and verified.get("native_integrity_evaluated") is False
             and verified.get("T1_numerical") is False
             and verified.get("qualification_credit") == 0,
             "metric adapter requires the complete zero-credit native-table v2 semantic verification result")
    time_rows, particle_count = verified.get("time_rows"), verified.get("fluid_particle_count")
    _require(isinstance(time_rows, int) and not isinstance(time_rows, bool)
             and 2 <= time_rows <= table_v2.MAX_TIME_ROWS
             and isinstance(particle_count, int) and not isinstance(particle_count, bool)
             and 1 <= particle_count <= table_v2.MAX_PARTICLE_ROWS
             and time_rows * particle_count <= table_v2.MAX_TIME_PARTICLE_CELLS,
             "verified table dimensions are outside the v2 resource bounds")
    _require(verified.get("raw_frames_recomputed") == time_rows,
             "native-table verification did not recompute every raw source frame")
    return time_rows, particle_count


def _metric_values(
    times: np.ndarray,
    particle_ids: np.ndarray,
    initial_z: np.ndarray,
    mass: np.ndarray,
    selected_velocity: np.ndarray,
    case_row: Mapping[str, Any],
    parameters: Mapping[str, Any],
    maximum_saved_output_dt_s: float,
) -> dict[str, Any]:
    geometry = parameters["geometry_and_fluid"]
    forcing = parameters["parameterization"]
    gates = parameters["error_gates"]
    half_height = float(geometry["half_height_m"])
    viscosity = float(geometry["kinematic_viscosity_m2_s"])
    acceleration = float(forcing["acceleration_amplitude_m_s2"])
    omega = float(case_row["omega_rad_s"])
    period = float(case_row["period_s"])
    samples_per_period = int(case_row["native_output_samples_per_period"])
    cycles = int(case_row["observation_cycles"])
    _require(math.isclose(2.0 * math.pi / period, omega, rel_tol=1e-12, abs_tol=1e-12),
             "frozen case period and angular frequency disagree")
    _require(selected_velocity.shape == (cycles * samples_per_period + 1, len(particle_ids), 3),
             "selected native velocity window has unexpected shape")

    plane_indices, plane_z = metric_v1.assign_plane_cohorts(
        initial_z, particle_ids, float(case_row["dp_m"]), half_height,
    )
    _require(1 < len(plane_z) <= MAX_HARMONIC_PLANES,
             "frozen profile has an unsupported number of registered z planes")
    profile = metric_v1.mass_weighted_velocity_profile(
        selected_velocity, np.broadcast_to(mass, (len(selected_velocity), len(mass))),
        plane_indices, len(plane_z),
    )
    selected_times = np.asarray(times, dtype=np.float64)
    _require(selected_times.shape == (len(selected_velocity),),
             "selected time and velocity window lengths differ")

    interior = np.arange(1, len(plane_z) - 1, dtype=np.int64)
    oracle_parameters = ChannelParameters(half_height, viscosity, omega, acceleration)
    reference = steady_velocity(selected_times, plane_z[interior], oracle_parameters)
    observed_coefficients = [
        metric_v1.fit_harmonic_coefficients(selected_times, profile[:, index], omega)
        for index in range(len(plane_z))
    ]
    reference_coefficients = [
        metric_v1.fit_harmonic_coefficients(selected_times, reference[:, local], omega)
        for local, _index in enumerate(interior)
    ]
    amplitude_errors: list[float] = []
    phase_errors: list[float] = []
    for local, plane_index in enumerate(interior):
        observed = observed_coefficients[int(plane_index)]
        expected = reference_coefficients[local]
        _require(expected["amplitude_m_s"] > 0.0,
                 "continuum profile amplitude is non-positive at an interior plane")
        amplitude_errors.append(abs(observed["amplitude_m_s"] - expected["amplitude_m_s"])
                                / expected["amplitude_m_s"])
        phase_errors.append(metric_v1.wrapped_phase_difference(
            observed["phase_rad"], expected["phase_rad"],
        ))

    instantaneous_flux = np.asarray([
        cross_sectional_flux_per_width(plane_z, row) for row in profile
    ], dtype=np.float64)
    cycle_means = metric_v1.three_cycle_mean_fluxes(
        selected_times, instantaneous_flux, period, samples_per_period,
    )
    u_ref = acceleration / omega
    flux_ratio = float(np.max(np.abs(cycle_means)) / (u_ref * 2.0 * half_height))

    # The table verifier proves mass is the exact B/C-derived invariant on all
    # rows. Reuse that verified vector for each selected row without allocating
    # a full time-by-particle mass array.
    mass_denominator = float(np.sum(mass, dtype=np.float64)) * len(selected_velocity)
    transverse_sum = 0.0
    for velocity_row in selected_velocity:
        row = np.asarray(velocity_row, dtype=np.float64)
        _require(row.shape == (len(mass), 3) and np.isfinite(row).all(),
                 "selected velocity row is malformed or non-finite")
        transverse_sum += float(np.sum(
            np.asarray(mass, dtype=np.float64)
            * (row[:, 1] ** 2 + row[:, 2] ** 2), dtype=np.float64,
        ))
    transverse_rms = math.sqrt(transverse_sum / mass_denominator)
    transverse_ratio = transverse_rms / u_ref
    center_series = np.asarray([np.interp(0.0, plane_z, row) for row in profile])
    center_coefficients = metric_v1.fit_harmonic_coefficients(selected_times, center_series, omega)

    metrics = {
        "profile_amplitude_relative_error_max": float(max(amplitude_errors)),
        "profile_phase_absolute_error_max_rad": float(max(phase_errors)),
        "cycle_mean_fluxes_m3_s_per_m": cycle_means.tolist(),
        "cycle_mean_flux_ratio": flux_ratio,
        "transverse_velocity_rms_m_s": transverse_rms,
        "transverse_velocity_rms_ratio": transverse_ratio,
        "u_ref_m_s": u_ref,
    }
    metric_gates = {
        "profile_amplitude": metrics["profile_amplitude_relative_error_max"]
        <= float(gates["profile_amplitude_relative_max"]),
        "profile_phase": metrics["profile_phase_absolute_error_max_rad"]
        <= float(gates["profile_phase_absolute_max_rad"]),
        "cycle_mean_flux": flux_ratio <= float(gates["cycle_mean_flux_over_uref_area_max"]),
        "transverse_velocity_rms": transverse_ratio
        <= float(gates["transverse_velocity_rms_over_uref_max"]),
    }
    coefficient_fields = (
        "mean_m_s", "sine_coefficient_a_m_s", "cosine_coefficient_b_m_s",
        "amplitude_m_s", "phase_rad",
    )
    return {
        "case_id": str(case_row["case_id"]),
        "selected_time_s": selected_times.tolist(),
        "maximum_saved_output_dt_s": float(maximum_saved_output_dt_s),
        "profile_z_m": plane_z.tolist(),
        "plane_coefficients": {
            field: [float(value[field]) for value in observed_coefficients]
            for field in coefficient_fields
        },
        "center_coefficients": center_coefficients,
        "metrics": metrics,
        "metric_gates": metric_gates,
        "metric_gates_passed": all(metric_gates.values()),
    }


def evaluate_case_metrics_fd(
    table_fd: int,
    *,
    table_verification: Mapping[str, Any],
    expected_table_bytes: int,
    expected_table_sha256: str,
) -> dict[str, Any]:
    """Compute one case's metric gates from the same held D-table descriptor.

    ``table_verification`` must be the direct zero-credit result of
    ``verify_native_fluid_table_fd``. The caller owns ``table_fd`` and must keep
    it open until the enclosing B/C/D chain is revalidated.
    """
    _require(isinstance(expected_table_bytes, int) and not isinstance(expected_table_bytes, bool)
             and 0 < expected_table_bytes <= MAX_TABLE_BYTES,
             "expected v2 table byte count is malformed")
    _require(isinstance(expected_table_sha256, str)
             and bool(table_v2.SHA256_RE.fullmatch(expected_table_sha256)),
             "expected v2 table SHA-256 is malformed")
    case_id = table_verification.get("case_id") if isinstance(table_verification, Mapping) else None
    _require(isinstance(case_id, str) and bool(case_id),
             "v2 semantic verification result has no case identity")
    time_rows, particle_count = _validate_table_verification(
        table_verification, case_id=case_id, expected_bytes=expected_table_bytes,
        expected_sha256=expected_table_sha256,
    )
    case_row, parameter_contract = _frozen_inputs(case_id)

    before = os.fstat(table_fd)
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and before.st_size == expected_table_bytes,
             "metric table FD is not the expected single-link regular file")
    try:
        access_mode = fcntl.fcntl(table_fd, fcntl.F_GETFL) & os.O_ACCMODE
    except OSError as error:
        raise NativeFluidMetricAdapterError("metric table FD access mode could not be verified") from error
    _require(access_mode == os.O_RDONLY,
             "metric adapter requires a read-only held table FD")
    file_obj = os.fdopen(os.dup(table_fd), "rb", buffering=0)
    try:
        with h5py.File(file_obj, "r", driver="fileobj") as handle:
            _require(_attr_text(handle.attrs.get("f8_table_schema"), "f8_table_schema") == table_v2.TABLE_SCHEMA
                     and _attr_text(handle.attrs.get("scope_id"), "scope_id") == SCOPE_ID
                     and _attr_text(handle.attrs.get("case_id"), "case_id") == case_id,
                     "metric table root identity differs from its verified R008 case")
            _require(set(handle.keys()) == {
                "time", "particle_id", "position", "velocity", "density", "mass", "valid",
            }, "metric table dataset links differ from the closed v2 schema")
            time_ds, ids_ds = handle["time"], handle["particle_id"]
            pos_ds, velocity_ds, mass_ds = handle["position"], handle["velocity"], handle["mass"]
            _require(time_ds.shape == (time_rows,) and time_ds.dtype == np.dtype("<f8")
                     and ids_ds.shape == (particle_count,) and ids_ds.dtype == np.dtype("<u4")
                     and pos_ds.shape == (time_rows, particle_count, 3)
                     and pos_ds.dtype == np.dtype("<f8")
                     and velocity_ds.shape == (time_rows, particle_count, 3)
                     and velocity_ds.dtype == np.dtype("<f4")
                     and mass_ds.shape == (time_rows, particle_count)
                     and mass_ds.dtype == np.dtype("<f4"),
                     "metric table dimensions or dtype differ from verified v2 semantics")
            times = np.asarray(time_ds[:], dtype=np.float64)
            ids = np.asarray(ids_ds[:], dtype=np.uint32)
            initial_z = np.asarray(pos_ds[0, :, 2], dtype=np.float64)
            mass = np.asarray(mass_ds[0, :], dtype=np.float64)
            _require(times[0] == 0.0 and np.isfinite(times).all()
                     and np.all(np.diff(times) > 0.0)
                     and np.isfinite(initial_z).all()
                     and np.isfinite(mass).all() and np.all(mass > 0.0),
                     "verified metric axes contain invalid native values")
            selected_times, selected_indices = select_closed_native_window(
                times, np.arange(time_rows, dtype=np.float64),
                start_s=float(case_row["observation_start_s"]),
                end_s=float(case_row["observation_end_s"]),
                period_s=float(case_row["period_s"]),
                output_samples_per_period=int(case_row["native_output_samples_per_period"]),
                cycles=int(case_row["observation_cycles"]),
            )
            row_indices = selected_indices.astype(np.int64)
            _require(np.array_equal(row_indices, np.arange(row_indices[0], row_indices[-1] + 1)),
                     "frozen observation window does not map to contiguous native rows")
            _require(len(row_indices) * particle_count <= MAX_SELECTED_TIME_PARTICLE_CELLS,
                     "selected metric window exceeds the bounded time-particle working set")
            selected_velocity = np.empty(
                (len(row_indices), particle_count, 3), dtype=np.float32,
            )
            for output_index, source_index in enumerate(row_indices):
                selected_velocity[output_index] = velocity_ds[int(source_index), :, :]
            computed = _metric_values(
                selected_times, ids, initial_z, mass, selected_velocity,
                case_row, parameter_contract, float(np.max(np.diff(times))),
            )
    finally:
        file_obj.close()

    after = os.fstat(table_fd)
    _require(_identity(before) == _identity(after)
             and table_v2._sha256_fd(table_fd, expected_table_bytes) == expected_table_sha256,
             "v2 table changed while case metrics were read")
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "frozen_scope_receipt_sha256": metric_v1.FROZEN_INPUT_SHA256["scope"],
        "parameter_contract_sha256": metric_v1.FROZEN_INPUT_SHA256["parameter_contract"],
        "case_id": case_id,
        "status": "case_metric_gates_evaluated_native_integrity_pending",
        "source_table_schema": table_v2.TABLE_SCHEMA,
        "source_table_bytes": expected_table_bytes,
        "source_table_sha256": expected_table_sha256,
        "semantic_source_checks": {
            "B_C_D_chain_required_by_caller": True,
            "full_time_axis_matches": True,
            "fluid_id_projection_matches": True,
            "position_velocity_density_mass_recomputed": True,
            "all_valid": True,
            "density_used_as_metric_input": False,
        },
        **computed,
        "solver_max_dt_s": None,
        "solver_timestep_audit": None,
        "native_integrity_gates_evaluated": False,
        "full_t1_decision": False,
        "qualification_credit": 0,
    }


__all__ = [
    "NativeFluidMetricAdapterError", "SCHEMA", "evaluate_case_metrics_fd",
]
