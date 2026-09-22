from __future__ import annotations

import numpy as np
import pytest
import hashlib
import json
from pathlib import Path

from scripts.f8_womersley_oracle import (
    SCHEMA,
    ChannelParameters,
    acceleration,
    cross_sectional_flux_per_width,
    harmonic_velocity_amplitude,
    steady_velocity,
    zero_mean_cycle_flux,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
    "reference-oracle-v1/contract.json"
)


def _parameters() -> ChannelParameters:
    return ChannelParameters(
        half_height_m=0.045,
        kinematic_viscosity_m2_s=0.0005,
        omega_rad_s=4.0,
        acceleration_amplitude_m_s2=0.01,
    )


def test_schema_and_derived_scales_are_explicit() -> None:
    parameters = _parameters()
    assert SCHEMA == "core.reference.f8_womersley_oracle.v1"
    assert parameters.period_s == pytest.approx(2.0 * np.pi / 4.0)
    assert parameters.viscous_diffusion_time_s == pytest.approx(4.05)
    assert parameters.alpha == pytest.approx(0.045 * np.sqrt(4.0 / 0.0005))


def test_static_contract_closes_oracle_and_preserves_no_admission_state() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["schema"] == "core.cfd.f8.reference_oracle_contract.v1"
    assert contract["status"] == "static_reference_only_no_admission"
    assert contract["qualification_credit"] == 0
    assert all(value is False for key, value in contract["execution_controls"].items()
               if isinstance(value, bool))
    assert all(value == 0 for key, value in contract["execution_controls"].items()
               if key.endswith("_mutation"))
    for binding in (contract["bindings"]["implementation"], contract["bindings"]["test"]):
        path = ROOT / binding["path"]
        assert path.stat().st_size == binding["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]


def test_wall_no_slip_and_centerline_symmetry_hold() -> None:
    parameters = _parameters()
    z = np.linspace(-parameters.half_height_m, parameters.half_height_m, 101)
    amplitude = harmonic_velocity_amplitude(
        z, half_height_m=parameters.half_height_m,
        kinematic_viscosity_m2_s=parameters.kinematic_viscosity_m2_s,
        omega_rad_s=parameters.omega_rad_s,
        acceleration_amplitude_m_s2=parameters.acceleration_amplitude_m_s2)
    assert amplitude[0] == pytest.approx(0.0j, abs=1e-13)
    assert amplitude[-1] == pytest.approx(0.0j, abs=1e-13)
    assert np.allclose(amplitude, amplitude[::-1])
    assert steady_velocity(0.0, z, parameters).shape == z.shape


def test_low_frequency_limit_recovers_quasisteady_poiseuille_profile() -> None:
    half_height = 0.045
    nu = 0.0005
    acceleration_amplitude = 0.01
    omega = 1e-5
    z = np.linspace(-half_height, half_height, 51)
    amplitude = harmonic_velocity_amplitude(
        z, half_height_m=half_height, kinematic_viscosity_m2_s=nu,
        omega_rad_s=omega, acceleration_amplitude_m_s2=acceleration_amplitude)
    expected = acceleration_amplitude * (half_height**2 - z**2) / (2.0 * nu)
    # A sine forcing has a -pi/2 complex phase in the quasisteady limit;
    # therefore the positive Poiseuille profile is -imag(U), not real(U).
    assert np.max(np.abs(-amplitude.imag - expected)) / np.max(expected) < 1e-6
    assert np.max(np.abs(amplitude.real)) / np.max(expected) < 3e-5


def test_sine_forcing_and_cycle_mean_flux_are_zero_mean() -> None:
    parameters = _parameters()
    times = np.array([0.0, parameters.period_s / 4.0,
                      parameters.period_s / 2.0])
    assert acceleration(times, parameters) == pytest.approx([0.0, 0.01, 0.0], abs=1e-12)
    z = np.linspace(-parameters.half_height_m, parameters.half_height_m, 401)
    assert abs(zero_mean_cycle_flux(z, parameters, samples=256)) < 1e-12
    quarter_cycle_flux = cross_sectional_flux_per_width(
        z, steady_velocity(parameters.period_s / 4.0, z, parameters))
    half_cycle_flux = cross_sectional_flux_per_width(
        z, steady_velocity(3.0 * parameters.period_s / 4.0, z, parameters))
    assert quarter_cycle_flux > 0.0
    assert half_cycle_flux < 0.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"half_height_m": 0.0}, "half_height_m"),
        ({"kinematic_viscosity_m2_s": -1.0}, "kinematic_viscosity_m2_s"),
        ({"omega_rad_s": 0.0}, "omega_rad_s"),
        ({"acceleration_amplitude_m_s2": np.nan}, "acceleration_amplitude_m_s2"),
    ],
)
def test_invalid_parameters_fail_closed(kwargs, message: str) -> None:
    values = {
        "half_height_m": 0.045,
        "kinematic_viscosity_m2_s": 0.0005,
        "omega_rad_s": 4.0,
        "acceleration_amplitude_m_s2": 0.01,
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        ChannelParameters(**values)


def test_invalid_grid_and_samples_fail_closed() -> None:
    parameters = _parameters()
    with pytest.raises(ValueError, match="within the channel walls"):
        steady_velocity(0.0, [0.0, 0.05], parameters)
    with pytest.raises(ValueError, match="strictly increasing"):
        cross_sectional_flux_per_width([0.0, 0.0], [0.0, 1.0])
    with pytest.raises(ValueError, match="eight cycle"):
        zero_mean_cycle_flux(np.linspace(-0.045, 0.045, 5), parameters, samples=4)
