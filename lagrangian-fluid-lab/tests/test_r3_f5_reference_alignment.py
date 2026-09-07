from __future__ import annotations

import numpy as np
import pytest

from scripts.r3_f5_reference_alignment import align_run, load_reference


def test_load_reference_retains_duplicate_rows_and_aggregates_for_interp(tmp_path):
    path = tmp_path / "reference.txt"
    path.write_text(
        "time [s] wg1 wg2 wg3 wg4 runup\n"
        "0 0 0 0 0 0.25\n"
        "1 0.01 0.02 0.03 0.04 0.25\n"
        "1 0.03 0.04 0.05 0.06 0.25\n"
        "2 0 0 0 0 0.25\n"
    )

    report = load_reference(path)

    assert report["original_rows"] == 4
    assert report["unique_time_rows"] == 3
    assert report["duplicate_transition_count"] == 1
    assert report["duplicate_time_values_s"] == [1.0]
    np.testing.assert_allclose(report["data"][1, 1:5], [0.02, 0.03, 0.04, 0.05])


def test_align_run_uses_per_gauge_initial_baseline(tmp_path):
    reference = {
        "data": np.asarray([
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.25],
            [1.0, 0.01, 0.02, 0.03, 0.04, 0.25],
            [2.0, 0.0, 0.0, 0.0, 0.0, 0.25],
        ])
    }
    gauges = {}
    for index, name in enumerate(("WG1", "WG2", "WG3", "WG4")):
        path = tmp_path / f"{name}.csv"
        baseline = 0.20 + index * 0.01
        path.write_text(
            "time [s];swlx [m];swly [m];swlz [m]\n"
            f"0;3.1;0.18;{baseline}\n"
            f"1;3.1;0.18;{baseline + 0.01 * (index + 1)}\n"
            f"2;3.1;0.18;{baseline}\n"
        )
        gauges[name] = {"path": str(path)}
    run = {
        "label": "medium",
        "dp_m": 0.025,
        "status": "completed",
        "external_gauge_summary": {"gauges": gauges},
        "output_dir": str(tmp_path),
    }

    report = align_run(run, reference)

    assert report["fixed_zero_offset"]["mean_rmse_m"] == pytest.approx(0.0)
    assert all(item["status"] == "computed" for item in report["fixed_zero_offset"]["gauges"].values())
    assert report["local_shift_diagnostic"]["best_offset_s"] is None
