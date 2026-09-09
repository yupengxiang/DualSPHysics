import numpy as np
import pytest

from scripts.finite_wall_audit import (
    segment_crossing_events,
    wall_penetration,
    outside_runtime_domain_mask,
)


SPEC = {
    "container_interior": dict(xmin=0, xmax=1.2, ymin=0, ymax=0.4, zmin=0, zmax=0.6),
    "open_faces": ["top"],
}


@pytest.mark.parametrize(
    "zs", [[0.002, -0.006], [0.002, -0.002, -0.006], [0.002, 0, -0.002, -0.006]]
)
def test_subdivision_preserves_nominal_crossing(zs):
    points = np.array([[0.6, 0.2, z] for z in zs])
    events = [
        event
        for a, b in zip(points[:-1], points[1:])
        for event in segment_crossing_events(a[None], b[None], SPEC, 0.0051)
    ]
    assert len(events) == 1
    assert events[0]["face"] == "bottom"
    assert events[0]["crossing_position_m"] == pytest.approx([0.6, 0.2, 0])
    assert (
        wall_penetration(points[-1:], np.ones(1), SPEC, 0.0051)[
            "outside_closed_container_count"
        ]
        == 1
    )


@pytest.mark.parametrize("zs", [[0.002, 0, 0.002], [-0.002, -0.006], [-0.006, 0.002]])
def test_contact_initial_outside_and_reentry_are_not_new_outward_crossings(zs):
    points = np.array([[0.6, 0.2, z] for z in zs])
    assert not [
        e
        for a, b in zip(points[:-1], points[1:])
        for e in segment_crossing_events(a[None], b[None], SPEC, 0.0051)
    ]


def test_missing_runtime_domain_is_unknown():
    points = np.array([[0.6, 0.2, 0.1]])
    assert outside_runtime_domain_mask(points, None, 0.0051) is None
    result = wall_penetration(points, np.ones(1), SPEC, 0.0051)
    assert result["runtime_domain_status"] == "not_checked"
    assert result["runtime_domain_outside_count"] is None
    assert result["runtime_domain_outside_mass_kg"] is None


def test_tolerance_does_not_extend_wall_above_open_rim():
    first = np.array([[1.19, 0.2, 0.601]])
    second = np.array([[1.21, 0.2, 0.601]])
    assert segment_crossing_events(first, second, SPEC, 0.0051) == []
    assert (
        wall_penetration(second, np.ones(1), SPEC, 0.0051)[
            "outside_closed_container_count"
        ]
        == 0
    )
