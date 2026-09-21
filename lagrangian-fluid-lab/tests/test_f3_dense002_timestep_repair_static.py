"""Static numerical checks for the F3 dense cadence repair proposal."""

import numpy as np

from scripts.f3_dense002_timestep_repair_static_v1 import (
    CADENCE_TOLERANCE_S,
    EXPECTED_INTERVALS,
    OUTPUT_INTERVAL_S,
    TARGET_STEPS,
    static_schedule,
)


def test_float32_rounded_old_proposal_fails_the_registered_gate():
    dt_ini = 0.0004424539307483203
    old_coef = float(np.float32(OUTPUT_INTERVAL_S / TARGET_STEPS / dt_ini))
    old_dt = dt_ini * old_coef
    schedule = static_schedule(
        old_dt,
        interval_s=OUTPUT_INTERVAL_S,
        intervals=EXPECTED_INTERVALS,
        tolerance_s=CADENCE_TOLERANCE_S,
    )
    assert schedule["bad_count"] > 0
    assert schedule["max_abs_error_us"] > 20.0
    assert schedule["step_count_max"] == TARGET_STEPS + 1


def test_explicit_double_candidate_passes_the_static_complete_window():
    target_dt = OUTPUT_INTERVAL_S / TARGET_STEPS
    candidate_dt = float(np.nextafter(np.float32(target_dt), np.float32(np.inf)))
    schedule = static_schedule(
        candidate_dt,
        interval_s=OUTPUT_INTERVAL_S,
        intervals=EXPECTED_INTERVALS,
        tolerance_s=CADENCE_TOLERANCE_S,
    )
    assert schedule["bad_count"] == 0
    assert schedule["max_abs_error_us"] < 1.0
    assert schedule["step_count_min"] == TARGET_STEPS
    assert schedule["step_count_max"] == TARGET_STEPS


def test_candidate_remains_below_the_terminal_baseline_floor():
    baseline_dt = 2.212269686706988e-05
    target_dt = OUTPUT_INTERVAL_S / TARGET_STEPS
    candidate_dt = float(np.nextafter(np.float32(target_dt), np.float32(np.inf)))
    assert target_dt < candidate_dt < baseline_dt
