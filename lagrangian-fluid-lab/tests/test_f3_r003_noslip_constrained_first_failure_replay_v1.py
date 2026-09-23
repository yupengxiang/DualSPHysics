"""Pure helper tests for the bounded R003 historical replay."""

import numpy as np

from scripts.f3_r003_noslip_constrained_first_failure_replay_v1 import (
    _inside_closed_domain,
    _nearest_closed_face,
    _trial,
)


def test_closed_domain_keeps_top_open_and_other_registered_faces_closed():
    assert _inside_closed_domain(np.array([0.0, 0.0, 0.60]))
    assert not _inside_closed_domain(np.array([0.451, 0.0, 0.10]))
    assert not _inside_closed_domain(np.array([0.0, 0.091, 0.10]))
    assert not _inside_closed_domain(np.array([0.0, 0.0, -0.001]))


def test_nearest_finite_face_returns_outward_normal_and_projection():
    name, foot, normal, distance = _nearest_closed_face(np.array([0.44, 0.02, 0.10]))
    assert name == "xmax"
    np.testing.assert_allclose(foot, [0.45, 0.02, 0.10], atol=0.0, rtol=0.0)
    np.testing.assert_array_equal(normal, [1.0, 0.0, 0.0])
    assert abs(distance - 0.01) < 1e-14


def test_stage_guard_rejects_before_querying_outside_domain():
    calls = []

    def evaluate(point):
        calls.append(np.array(point, copy=True))
        return {"ok": True, "velocity": np.array([1.0, 0.0, 0.0])}

    trial = _trial(
        np.array([0.449, 0.0, 0.10]), 0.004, evaluate, guard_domain=True
    )
    assert not trial["ok"]
    assert trial["reason"] == "stage_outside_domain"
    assert trial["stage"] == "k2"
    assert len(calls) == 1
