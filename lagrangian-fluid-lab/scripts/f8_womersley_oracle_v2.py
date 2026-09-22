#!/usr/bin/env python3
"""Startup-transient extension of the F8 Womersley reference oracle.

The v1 steady harmonic oracle remains immutable.  This adapter adds the
zero-initial-velocity startup solution for the same channel and forcing, so
the viscous diffusion scale ``H**2/nu`` can be tested without opening CFD
output.  It is still a continuum reference and does not authorize a solver.
"""
from __future__ import annotations

import math

import numpy as np

from scripts.f8_womersley_oracle import (
    SCHEMA as STEADY_SCHEMA,
    ChannelParameters,
    harmonic_velocity_amplitude,
    steady_velocity,
)


SCHEMA = "core.reference.f8_womersley_oracle.v2"
STARTUP_SERIES = "zero_initial_velocity_even_cosine_series.v1"


def startup_velocity(t_s, z, parameters: ChannelParameters, *, terms: int = 256) -> np.ndarray:
    """Evaluate the zero-initial-velocity transient plus forced response.

    For ``lambda_n=(n+1/2)*pi/H``, the constant forcing expansion coefficient
    is ``2*(-1)**n/(H*lambda_n)``.  Each mode is the exact convolution of a
    sinusoid with ``exp(-nu*lambda_n**2*t)``.  A scalar time returns ``[Z]``;
    a vector of times returns ``[T,Z]``.
    """
    if isinstance(terms, (bool, np.bool_)) or not isinstance(terms, (int, np.integer)):
        raise ValueError("terms must be an integer")
    terms = int(terms)
    if terms < 8:
        raise ValueError("at least eight startup series terms are required")
    t = np.asarray(t_s, dtype=float)
    z = np.asarray(z, dtype=float)
    if not np.isfinite(t).all() or not np.isfinite(z).all():
        raise ValueError("startup time and z samples must be finite")
    if np.any(t < 0):
        raise ValueError("startup time cannot be negative")
    if z.ndim != 1 or np.any(np.abs(z) > parameters.half_height_m * (1.0 + 1e-12)):
        raise ValueError("startup z samples must be a one-dimensional in-domain grid")

    lam = (np.arange(terms, dtype=float) + 0.5) * math.pi / parameters.half_height_m
    decay = parameters.kinematic_viscosity_m2_s * lam**2
    coefficients = (2.0 * np.where(np.arange(terms) % 2 == 0, 1.0, -1.0)
                    / (parameters.half_height_m * lam))
    spatial = np.cos(lam[:, None] * z[None, :])
    time = t.reshape(-1)
    numerator = (
        decay[:, None] * np.sin(parameters.omega_rad_s * time)[None, :]
        - parameters.omega_rad_s * np.cos(parameters.omega_rad_s * time)[None, :]
        + parameters.omega_rad_s * np.exp(-decay[:, None] * time[None, :])
    )
    modal = (parameters.acceleration_amplitude_m_s2 * coefficients[:, None]
             * numerator / (decay[:, None] ** 2 + parameters.omega_rad_s ** 2))
    result = (modal.T @ spatial).reshape(time.shape + (len(z),))
    if t.ndim == 0:
        return result[0]
    return result


def startup_to_steady_error(t_s, z, parameters: ChannelParameters, *, terms: int = 256) -> float:
    """Return the relative sup-norm difference from the steady oracle."""
    transient = startup_velocity(t_s, z, parameters, terms=terms)
    steady = steady_velocity(t_s, z, parameters)
    scale = max(float(np.max(np.abs(steady))), 1e-15)
    return float(np.max(np.abs(transient - steady)) / scale)


__all__ = [
    "SCHEMA", "STARTUP_SERIES", "STEADY_SCHEMA", "ChannelParameters",
    "harmonic_velocity_amplitude", "startup_to_steady_error", "startup_velocity",
]
