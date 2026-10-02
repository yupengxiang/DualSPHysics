from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F2/f2_handoff_20261002_event_semantics_v6.py"
SPEC = importlib.util.spec_from_file_location("f2_event_semantics_v6", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_crossing_aperture_uses_interpolated_pose_when_endpoint_is_outside():
    origin = np.asarray([0.0, 0.0, 0.0])
    axis = np.asarray([0.0, 1.0, 0.0])
    low = np.asarray([0.0, 0.0, 0.0])
    high = np.asarray([1.0, 1.0, 1.0])
    previous_body = np.asarray([[0.5, 0.5, 0.9]])
    current_body = np.asarray([[1.2, 0.5, 1.1]])
    previous_world = MODULE._inverse_rotate(previous_body, origin, axis, 0.0)
    current_world = MODULE._inverse_rotate(current_body, origin, axis, -0.4)
    previous_margin = np.asarray([-0.1])
    current_margin = np.asarray([0.1])

    crossing = MODULE._interpolated_top_aperture(
        previous_world, current_world, previous_margin, current_margin,
        0.0, 0.4, origin, axis, low, high, 0.01,
    )

    assert bool(crossing[0])
    assert current_body[0, 0] > high[0]  # endpoint-only membership would reject it


def test_v6_operator_hash_is_distinct_and_manifest_bound():
    manifest = __import__("json").loads(
        (SCRIPT.parent / "handoff_20261002/event_semantics_v6/operator_manifest.json").read_text()
    )
    assert MODULE.operator_hash() == manifest["operator_sha256"]
    assert MODULE.operator_hash() != "728c3224fa58164ff6cb2cd6dcacf3e2505a998fe35343104d112429c205c100"
