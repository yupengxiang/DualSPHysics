from __future__ import annotations

import numpy as np

from scripts.ds_data02_f1_boundary_coverage import _plane_summary, _summarize_planes


def test_plane_summary_reports_finite_tangent_grid() -> None:
    points = np.asarray([
        [0.0, -0.005, -0.005], [0.0, 0.005, -0.005],
        [0.0, -0.005, 0.005], [0.0, 0.005, 0.005],
    ], dtype=float)
    row = _plane_summary(
        points, axis=0, target=0.0, tolerance=1e-9,
        tangent_axes=(1, 2), name="outer_x_low",
        expected_tangent_low=(-0.005, -0.005), expected_tangent_high=(0.005, 0.005),
    )
    assert row["point_count"] == 4
    assert row["tangent_unique_counts"] == {"first": 2, "second": 2}
    assert row["finite_rectangle_coverage"]["finite_rectangle_coverage"] is True
    assert row["tangent_steps_m"]["first"]["min_m"] == 0.01


def test_five_face_summary_does_not_count_open_top() -> None:
    points = []
    for x in (0.0, 3.23):
        for y in (-0.005, 1.005):
            for z in (-0.005, 1.0):
                points.append((x, y, z))
    for x in (0.0, 3.23):
        for y in (-0.005, 1.005):
            points.append((x, y, 1.0))
    # Add the bottom plane and omit any z=1.0 face as a target plane.
    points.extend((x, y, -0.005) for x in (0.0, 3.23) for y in (-0.005, 1.005))
    report = _summarize_planes(np.asarray(points, dtype=float), 1e-9)
    assert report["outer_five_nonempty"] is True
    assert all(name != "outer_z_high" for name in report["outer_five_point_counts"])
