from __future__ import annotations

import numpy as np
import pytest

from scripts.f8_observation_parser_v1 import fit_harmonic, parse_observation_payload


def _payload():
    time = np.linspace(0.0, 2.0 * np.pi, 128)
    z = np.linspace(-0.045, 0.045, 5)
    signal = 0.2 + 1.5 * np.sin(2.0 * time + 0.3)
    return {
        "time_s": time,
        "center_velocity_mps": signal,
        "profile_z_m": z,
        "profile_velocity_mps": np.outer(signal, np.ones(len(z))),
        "mean_flux_m3_s_per_m": 0.1 * signal,
    }


def test_parser_copies_and_freezes_all_observation_arrays() -> None:
    observation = parse_observation_payload(_payload())
    assert observation.time_s.shape == (128,)
    assert observation.profile_velocity_mps.shape == (128, 5)
    assert observation.time_s.flags.writeable is False
    assert observation.profile_velocity_mps.flags.writeable is False


def test_harmonic_fit_recovers_registered_amplitude_phase_without_time_shift() -> None:
    payload = _payload()
    result = fit_harmonic(payload["time_s"], payload["center_velocity_mps"], 2.0,
                           start_time_s=0.0)
    assert result["mean"] == pytest.approx(0.2, abs=1e-10)
    assert result["amplitude"] == pytest.approx(1.5, abs=1e-10)
    assert result["phase_rad"] == pytest.approx(0.3, abs=1e-10)
    assert result["time_shift_fitting"] is False


def test_parser_rejects_missing_nonmonotonic_or_rank_deficient_input() -> None:
    payload = _payload()
    payload.pop("mean_flux_m3_s_per_m")
    with pytest.raises(ValueError, match="missing"):
        parse_observation_payload(payload)
    payload = _payload()
    payload["time_s"][4] = payload["time_s"][3]
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_observation_payload(payload)
    with pytest.raises(ValueError, match="rank deficient"):
        fit_harmonic(np.zeros(4), np.arange(4.0), 1.0)
