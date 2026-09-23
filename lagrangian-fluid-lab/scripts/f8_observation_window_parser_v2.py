"""Closed, native-row-only F8 observation-window selector.

The caller supplies one native time axis and an aligned value array. This
module selects an inclusive, exactly three-period window and refuses missing,
duplicated, off-grid, or non-finite rows. It never interpolates or extrapolates.
"""
from __future__ import annotations

import math

import numpy as np


ABSOLUTE_TIME_TOLERANCE_S = 1e-12


def select_closed_native_window(
    times_s: np.ndarray,
    values: np.ndarray,
    *,
    start_s: float,
    end_s: float,
    period_s: float,
    output_samples_per_period: int,
    cycles: int = 3,
    atol_s: float = ABSOLUTE_TIME_TOLERANCE_S,
) -> tuple[np.ndarray, np.ndarray]:
    """Return only exact native rows in inclusive ``[start_s, end_s]``.

    The expected cadence is ``period_s / output_samples_per_period``. Both
    window endpoints must lie on that cadence and the selected count must be
    ``cycles * output_samples_per_period + 1``. ``values`` may have any shape
    after its leading time axis; no missing row is synthesized.
    """
    times = np.asarray(times_s, dtype=np.float64)
    data = np.asarray(values, dtype=np.float64)
    if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all():
        raise ValueError("native times must be a finite one-dimensional array with at least two rows")
    if data.ndim < 1 or data.shape[0] != len(times):
        raise ValueError("native value rows must match the time axis")
    if not np.isfinite(data).all():
        raise ValueError("native values contain non-finite entries; preserve the case as failed")
    if np.any(np.diff(times) <= 0.0):
        raise ValueError("native times must be strictly increasing")
    if not all(math.isfinite(value) for value in (start_s, end_s, period_s, atol_s)):
        raise ValueError("window, period, and tolerance must be finite")
    if period_s <= 0.0 or end_s <= start_s or atol_s < 0.0:
        raise ValueError("period must be positive, end must follow start, and tolerance nonnegative")
    if isinstance(output_samples_per_period, bool) or int(output_samples_per_period) != output_samples_per_period or output_samples_per_period < 1:
        raise ValueError("output_samples_per_period must be a positive integer")
    if isinstance(cycles, bool) or int(cycles) != cycles or cycles < 1:
        raise ValueError("cycles must be a positive integer")

    expected_duration = int(cycles) * period_s
    if not math.isclose(end_s - start_s, expected_duration, rel_tol=0.0, abs_tol=atol_s):
        raise ValueError("window duration is not the requested whole number of periods")

    dt_s = period_s / int(output_samples_per_period)
    first_grid_index = round(start_s / dt_s)
    last_grid_index = round(end_s / dt_s)
    if not (
        math.isclose(first_grid_index * dt_s, start_s, rel_tol=0.0, abs_tol=atol_s)
        and math.isclose(last_grid_index * dt_s, end_s, rel_tol=0.0, abs_tol=atol_s)
    ):
        raise ValueError("both inclusive window endpoints must be on the native output grid")

    inside = (times >= start_s - atol_s) & (times <= end_s + atol_s)
    selected_times = times[inside]
    selected_values = data[inside]
    expected_count = int(cycles) * int(output_samples_per_period) + 1
    if len(selected_times) != expected_count:
        raise ValueError(f"closed native window has {len(selected_times)} rows; expected {expected_count}")
    expected_times = start_s + np.arange(expected_count, dtype=np.float64) * dt_s
    if not np.allclose(selected_times, expected_times, rtol=0.0, atol=atol_s):
        raise ValueError("closed native window has missing, duplicated, or off-cadence rows")
    if not (
        math.isclose(float(selected_times[0]), start_s, rel_tol=0.0, abs_tol=atol_s)
        and math.isclose(float(selected_times[-1]), end_s, rel_tol=0.0, abs_tol=atol_s)
    ):
        raise ValueError("closed native window does not contain both requested endpoints")
    return selected_times.copy(), selected_values.copy()
