#!/usr/bin/env python3
"""Analytic reference for the F8 oscillatory body-force channel candidate.

The candidate is a fully filled channel with no-slip walls at ``z = +/- H``
and a spatially uniform acceleration ``a(t) = A sin(omega*t)``.  This module
provides only the continuum reference used by static/pre-admission checks; it
does not read CFD output, create a Definition, or authorize an execution.

For a complex forcing ``Re[a_hat exp(i omega t)]`` the steady harmonic
solution of ``du/dt = a(t) + nu*d2u/dz2`` is

    U(z) = a_hat/(i*omega) * (1 - cosh(k*z)/cosh(k*H)),
    k = sqrt(i*omega/nu).

The public sine-forcing helper uses ``a_hat = -i*A``.  The branch of the
complex square root is the principal branch, which has positive real part
for positive ``omega`` and gives the physically decaying wall-normal mode.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


SCHEMA = "core.reference.f8_womersley_oracle.v1"


def _positive_finite(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a positive finite number") from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def _finite_array(value, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite values")
    return result


@dataclass(frozen=True)
class ChannelParameters:
    """Frozen continuum parameters for one F8 reference configuration."""

    half_height_m: float
    kinematic_viscosity_m2_s: float
    omega_rad_s: float
    acceleration_amplitude_m_s2: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "half_height_m", _positive_finite(self.half_height_m, "half_height_m"))
        object.__setattr__(self, "kinematic_viscosity_m2_s", _positive_finite(
            self.kinematic_viscosity_m2_s, "kinematic_viscosity_m2_s"))
        object.__setattr__(self, "omega_rad_s", _positive_finite(self.omega_rad_s, "omega_rad_s"))
        amplitude = _positive_finite(self.acceleration_amplitude_m_s2,
                                     "acceleration_amplitude_m_s2")
        object.__setattr__(self, "acceleration_amplitude_m_s2", amplitude)

    @property
    def period_s(self) -> float:
        return 2.0 * math.pi / self.omega_rad_s

    @property
    def viscous_diffusion_time_s(self) -> float:
        return self.half_height_m ** 2 / self.kinematic_viscosity_m2_s

    @property
    def alpha(self) -> float:
        return self.half_height_m * math.sqrt(self.omega_rad_s / self.kinematic_viscosity_m2_s)


def _validate_z(z, half_height_m: float) -> np.ndarray:
    half_height_m = _positive_finite(half_height_m, "half_height_m")
    result = _finite_array(z, "z")
    if np.any(np.abs(result) > half_height_m * (1.0 + 1e-12)):
        raise ValueError("z samples must lie within the channel walls")
    return result


def harmonic_velocity_amplitude(z, *, half_height_m: float,
                                kinematic_viscosity_m2_s: float,
                                omega_rad_s: float,
                                acceleration_amplitude_m_s2: float) -> np.ndarray:
    """Return complex velocity amplitudes for ``A*sin(omega*t)`` forcing.

    The returned array has the same shape as ``z`` and is suitable for
    ``steady_velocity``.  Its modulus is the local velocity amplitude and its
    argument is the phase relative to ``exp(i*omega*t)``.
    """
    z = _validate_z(z, half_height_m)
    nu = _positive_finite(kinematic_viscosity_m2_s, "kinematic_viscosity_m2_s")
    omega = _positive_finite(omega_rad_s, "omega_rad_s")
    amplitude = _positive_finite(acceleration_amplitude_m_s2,
                                 "acceleration_amplitude_m_s2")
    k = np.sqrt(1j * omega / nu)
    # -i*A is the complex amplitude whose real part is A*sin(omega*t).
    forcing = -1j * amplitude
    return forcing / (1j * omega) * (1.0 - np.cosh(k * z) / np.cosh(k * float(half_height_m)))


def steady_velocity(t_s, z, parameters: ChannelParameters) -> np.ndarray:
    """Evaluate the periodic steady-state velocity field at ``t_s``."""
    t = _finite_array(t_s, "t_s")
    z = _validate_z(z, parameters.half_height_m)
    if t.ndim == 0:
        phase = np.exp(1j * parameters.omega_rad_s * float(t))
        return np.real(harmonic_velocity_amplitude(
            z, half_height_m=parameters.half_height_m,
            kinematic_viscosity_m2_s=parameters.kinematic_viscosity_m2_s,
            omega_rad_s=parameters.omega_rad_s,
            acceleration_amplitude_m_s2=parameters.acceleration_amplitude_m_s2) * phase)
    phase = np.exp(1j * parameters.omega_rad_s * t)
    amplitude = harmonic_velocity_amplitude(
        z, half_height_m=parameters.half_height_m,
        kinematic_viscosity_m2_s=parameters.kinematic_viscosity_m2_s,
        omega_rad_s=parameters.omega_rad_s,
        acceleration_amplitude_m_s2=parameters.acceleration_amplitude_m_s2)
    return np.real(phase[..., None] * amplitude[None, ...])


def acceleration(t_s, parameters: ChannelParameters) -> np.ndarray:
    """Evaluate the registered sinusoidal body acceleration."""
    t = _finite_array(t_s, "t_s")
    return parameters.acceleration_amplitude_m_s2 * np.sin(parameters.omega_rad_s * t)


def cross_sectional_flux_per_width(z, velocity) -> float:
    """Integrate velocity over ``z`` and return flux per unit span.

    The input grid must be one-dimensional and strictly increasing.  For a
    spatially uniform channel this is the flux relevant to the zero-mean
    cycle gate; no arbitrary particle or wall samples are used.
    """
    z = _finite_array(z, "z")
    velocity = _finite_array(velocity, "velocity")
    if z.ndim != 1 or velocity.shape != z.shape or len(z) < 2:
        raise ValueError("z and velocity must be matching one-dimensional arrays")
    if np.any(np.diff(z) <= 0):
        raise ValueError("z grid must be strictly increasing")
    return float(np.trapezoid(velocity, z))


def zero_mean_cycle_flux(z, parameters: ChannelParameters, *, samples: int = 512) -> float:
    """Numerically integrate one full-cycle flux; useful as a gate oracle."""
    if isinstance(samples, (bool, np.bool_)) or not isinstance(samples, (int, np.integer)):
        raise ValueError("samples must be an integer")
    if int(samples) < 8:
        raise ValueError("at least eight cycle samples are required")
    z = _validate_z(z, parameters.half_height_m)
    times = np.linspace(0.0, parameters.period_s, int(samples), endpoint=False)
    flux = np.array([
        cross_sectional_flux_per_width(z, steady_velocity(time, z, parameters))
        for time in times
    ])
    return float(np.trapezoid(np.r_[flux, flux[0]], np.r_[times, parameters.period_s]) /
                 parameters.period_s)


__all__ = [
    "SCHEMA", "ChannelParameters", "acceleration",
    "cross_sectional_flux_per_width", "harmonic_velocity_amplitude",
    "steady_velocity", "zero_mean_cycle_flux",
]
