from __future__ import annotations

import numpy as np
import pytest

from scripts.f8_observation_window_parser_v2 import select_closed_native_window


def _window(samples_per_period: int) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    period = 1.25
    dt = period / samples_per_period
    start = 10.0 * dt
    count = 3 * samples_per_period + 1
    selected = start + np.arange(count) * dt
    all_times = np.concatenate(([start - dt], selected, [selected[-1] + dt]))
    values = np.column_stack((all_times, all_times**2))
    return all_times, values, start, float(selected[-1]), period


@pytest.mark.parametrize("samples_per_period", [64, 128])
def test_selects_exact_inclusive_three_period_native_window(samples_per_period: int) -> None:
    times, values, start, end, period = _window(samples_per_period)
    observed_times, observed_values = select_closed_native_window(
        times, values, start_s=start, end_s=end, period_s=period,
        output_samples_per_period=samples_per_period,
    )
    assert len(observed_times) == 3 * samples_per_period + 1
    assert observed_times[0] == start
    assert observed_times[-1] == end
    assert np.array_equal(observed_values, values[1:-1])


def test_rejects_missing_endpoint_or_internal_native_row() -> None:
    times, values, start, end, period = _window(64)
    with pytest.raises(ValueError, match="expected 193"):
        select_closed_native_window(
            times[:-2], values[:-2], start_s=start, end_s=end, period_s=period,
            output_samples_per_period=64,
        )
    with pytest.raises(ValueError, match="expected 193"):
        select_closed_native_window(
            np.delete(times, 20), np.delete(values, 20, axis=0), start_s=start,
            end_s=end, period_s=period, output_samples_per_period=64,
        )


def test_rejects_off_grid_or_non_three_period_window() -> None:
    times, values, start, end, period = _window(64)
    with pytest.raises(ValueError, match="whole number of periods"):
        select_closed_native_window(
            times, values, start_s=start, end_s=end - 1e-4, period_s=period,
            output_samples_per_period=64,
        )
    with pytest.raises(ValueError, match="both inclusive window endpoints"):
        select_closed_native_window(
            times, values, start_s=start + 1e-4, end_s=end + 1e-4, period_s=period,
            output_samples_per_period=64,
        )


def test_rejects_nonmonotone_time_and_nonfinite_values() -> None:
    times, values, start, end, period = _window(64)
    duplicate = times.copy()
    duplicate[5] = duplicate[4]
    with pytest.raises(ValueError, match="strictly increasing"):
        select_closed_native_window(
            duplicate, values, start_s=start, end_s=end, period_s=period,
            output_samples_per_period=64,
        )
    invalid = values.copy()
    invalid[10, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        select_closed_native_window(
            times, invalid, start_s=start, end_s=end, period_s=period,
            output_samples_per_period=64,
        )
