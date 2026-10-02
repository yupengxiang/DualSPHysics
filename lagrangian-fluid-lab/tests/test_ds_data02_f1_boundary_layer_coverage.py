from __future__ import annotations

import numpy as np

from scripts.ds_data02_f1_boundary_layer_coverage import _layer_rows


def test_layer_rows_keeps_offset_layers_and_exact_plane_absence() -> None:
    points = np.asarray([
        [-0.015, 0.0, 0.0], [-0.005, 0.0, 0.0], [0.005, 0.0, 0.0],
        [-0.015, 1.0, 0.0], [-0.005, 1.0, 0.0], [0.005, 1.0, 0.0],
    ])
    spec = {"name": "outer_x_low", "axis": 0, "target": 0.0,
            "tangent": (1, 2), "low": (0.0, 0.0), "high": (1.0, 0.0)}
    row = _layer_rows(points, spec, width_m=0.04)
    assert row["exact_plane_point_count_within_band_tolerance"] == 0
    assert len(row["layers_in_band"]) == 3
    assert row["nearest_layer"]["coordinate_m"] == -0.005
    assert row["band_union_point_count"] == 6


def test_layer_rows_does_not_report_outside_band_as_coverage() -> None:
    points = np.asarray([[0.05, 0.0, 0.0], [0.05, 1.0, 0.0]])
    spec = {"name": "outer_x_low", "axis": 0, "target": 0.0,
            "tangent": (1, 2), "low": (0.0, 0.0), "high": (1.0, 0.0)}
    row = _layer_rows(points, spec, width_m=0.04)
    assert row["layers_in_band"] == []
    assert row["band_union_point_count"] == 0
    assert row["band_union_finite_rectangle_coverage"] is False
