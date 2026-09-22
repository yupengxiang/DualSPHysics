from __future__ import annotations

import numpy as np
import pytest

from scripts.f8_womersley_oracle import ChannelParameters
from scripts.f8_womersley_oracle_v2 import startup_to_steady_error, startup_velocity


def _parameters() -> ChannelParameters:
    return ChannelParameters(0.045, 0.0005, 4.0, 0.01)


def test_startup_is_zero_at_initial_time_and_even_in_z() -> None:
    parameters = _parameters()
    z = np.linspace(-parameters.half_height_m, parameters.half_height_m, 101)
    initial = startup_velocity(0.0, z, parameters, terms=512)
    assert np.max(np.abs(initial)) < 1e-14
    later = startup_velocity(2.0, z, parameters, terms=512)
    assert np.allclose(later, later[::-1], atol=1e-13)
    assert later[0] == pytest.approx(0.0, abs=1e-13)
    assert later[-1] == pytest.approx(0.0, abs=1e-13)


def test_startup_converges_to_steady_solution_after_diffusion_decay() -> None:
    parameters = _parameters()
    z = np.linspace(-parameters.half_height_m, parameters.half_height_m, 81)
    times = np.linspace(2.0 * parameters.viscous_diffusion_time_s,
                        2.0 * parameters.viscous_diffusion_time_s + parameters.period_s,
                        32)
    assert startup_to_steady_error(times, z, parameters, terms=512) < 0.03


def test_startup_rejects_invalid_time_and_series_size() -> None:
    parameters = _parameters()
    with pytest.raises(ValueError, match="negative"):
        startup_velocity(-1.0, [0.0], parameters)
    with pytest.raises(ValueError, match="eight"):
        startup_velocity(0.0, [0.0], parameters, terms=4)
