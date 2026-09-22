#!/usr/bin/env python3
"""Pure parser/observable functions for an F8 decoded observation payload."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np


SCHEMA = "core.cfd.f8.observation_parser.v1"
REQUIRED = (
    "time_s", "center_velocity_mps", "profile_z_m",
    "profile_velocity_mps", "mean_flux_m3_s_per_m",
)


@dataclass(frozen=True)
class Observation:
    time_s: np.ndarray
    center_velocity_mps: np.ndarray
    profile_z_m: np.ndarray
    profile_velocity_mps: np.ndarray
    mean_flux_m3_s_per_m: np.ndarray


def parse_observation_payload(payload: Mapping[str, object]) -> Observation:
    if not isinstance(payload, Mapping) or any(key not in payload for key in REQUIRED):
        raise ValueError("F8 observation payload is missing required arrays")
    time = np.array(payload["time_s"], dtype=float, copy=True)
    center = np.array(payload["center_velocity_mps"], dtype=float, copy=True)
    z = np.array(payload["profile_z_m"], dtype=float, copy=True)
    profile = np.array(payload["profile_velocity_mps"], dtype=float, copy=True)
    flux = np.array(payload["mean_flux_m3_s_per_m"], dtype=float, copy=True)
    if time.ndim != 1 or center.shape != time.shape or flux.shape != time.shape:
        raise ValueError("F8 time-series arrays must share shape [T]")
    if z.ndim != 1 or profile.shape != (len(time), len(z)):
        raise ValueError("F8 profile arrays must have shape [T,Z]")
    arrays = (time, center, z, profile, flux)
    if any(not np.isfinite(array).all() for array in arrays):
        raise ValueError("F8 observation arrays must be finite")
    if len(time) < 4 or len(z) < 2:
        raise ValueError("F8 observation payload is too short")
    if np.any(np.diff(time) <= 0) or np.any(np.diff(z) <= 0):
        raise ValueError("F8 time and profile grids must be strictly increasing")
    for array in arrays:
        array.setflags(write=False)
    return Observation(time, center, z, profile, flux)


def fit_harmonic(time_s, signal, omega_rad_s: float, *, start_time_s: float = 0.0) -> dict[str, float]:
    """Fit ``mean + amplitude*sin(omega*t + phase)`` without time shifting."""
    time = np.asarray(time_s, dtype=float)
    values = np.asarray(signal, dtype=float)
    if time.ndim != 1 or values.shape != time.shape or len(time) < 4:
        raise ValueError("harmonic fit requires matching one-dimensional arrays")
    if not np.isfinite(time).all() or not np.isfinite(values).all():
        raise ValueError("harmonic fit inputs must be finite")
    try:
        omega = float(omega_rad_s)
        start = float(start_time_s)
    except (TypeError, ValueError) as error:
        raise ValueError("harmonic fit parameters must be finite") from error
    if not math.isfinite(omega) or omega <= 0 or not math.isfinite(start):
        raise ValueError("harmonic fit parameters must be finite and omega positive")
    mask = time >= start
    if int(mask.sum()) < 4:
        raise ValueError("harmonic fit window requires at least four samples")
    selected_time, selected_values = time[mask], values[mask]
    design = np.column_stack((
        np.ones(len(selected_time)),
        np.sin(omega * selected_time),
        np.cos(omega * selected_time),
    ))
    coefficients, _, rank, _ = np.linalg.lstsq(design, selected_values, rcond=None)
    if rank < 3:
        raise ValueError("harmonic fit design is rank deficient")
    sine, cosine = float(coefficients[1]), float(coefficients[2])
    return {
        "mean": float(coefficients[0]),
        "amplitude": float(np.hypot(sine, cosine)),
        "phase_rad": float(np.arctan2(cosine, sine)),
        "sample_count": int(len(selected_time)),
        "time_shift_fitting": False,
    }


__all__ = ["SCHEMA", "REQUIRED", "Observation", "fit_harmonic", "parse_observation_payload"]
