from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "nativefluid_bed_support_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("f5_nativefluid_bed_support_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_x_projection_retains_outside_y_while_footprint_bins_are_bounded() -> None:
    metrics = MODULE.frame_metrics(
        frame_index=400,
        time_s=8.0,
        positions=np.asarray(
            [
                [0.0, 0.00, -0.05],  # x/y footprint
                [0.0, 0.16, -0.05],  # outside bed y, inside flume y
                [0.0, 0.19, -0.05],  # outside flume y
                [4.9, 0.00, -0.05],  # outside bed x domain
                [0.0, 0.00, np.nan],  # retained native row, no geometry distance
            ],
            dtype=np.float64,
        ),
        valid=np.ones(5, dtype=np.uint8),
        particle_type=np.full(5, 3, dtype=np.int8),
        mass=np.arange(1.0, 6.0),
        particle_ids=np.arange(10, 15, dtype=np.uint32),
    )

    assert metrics["valid_type3_native_count"] == 5
    assert metrics["finite_position_count_valid_type3"] == 4
    assert metrics["x_projection_evaluable_count"] == 3
    assert metrics["bed_footprint_evaluable_count"] == 1
    assert metrics["x_projection_outside_bed_y_count"] == 2
    assert metrics["x_projection_outside_bed_y_inside_flume_count"] == 1
    assert metrics["x_projection_outside_flume_y_count"] == 1
    assert metrics["x_projection_depth_bins"]["0.02m"]["count"] == 3
    assert metrics["x_projection_depth_bins"]["0.04m"]["count"] == 3
    assert metrics["bed_footprint_depth_bins"]["0.02m"]["count"] == 1
    assert metrics["bed_footprint_depth_bins"]["0.04m"]["count"] == 1
    assert metrics["outside_bed_y_fraction_of_x_projection"] == 2.0 / 3.0
    assert metrics["denominator_policy"]["no_mask_or_drop"] is True


def test_h5_xdmf_time_axis_verification_is_explicit_and_strict() -> None:
    matching = MODULE.verify_time_axes(
        np.asarray([0.0, 1.0, 2.0]),
        np.asarray([0.0, 1.0, 2.0 + 5.0e-10]),
    )
    assert matching["match"] is True
    assert np.isclose(matching["max_abs_difference_s"], 5.0e-10)

    mismatch = MODULE.verify_time_axes(
        np.asarray([0.0, 1.0, 2.0]),
        np.asarray([0.0, 1.0, 2.0 + 2.0e-9]),
    )
    assert mismatch["match"] is False
    assert mismatch["reason"] == "time_axis_value_mismatch"
