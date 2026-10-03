from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest
import numpy as np

SCRIPT = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F2/f2_rv4eq_fine_dense_full4001_event_semantics_v8.py"
SPEC = importlib.util.spec_from_file_location("f2_event_semantics_v8", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v8_operator_hash_and_exact_v6_binding():
    assert MODULE.V6_CODE_SHA256 == "e200b886adfd3b4dc69c7e4f281df401d30436be1cba4bf0871f355129f626b9"
    assert MODULE.OPERATOR_VERSION == "f2-moving-cup-local-z-top-v8-native-mass-bound"
    spec = MODULE.operator_spec()
    assert spec["schema"] == "ds-data-02.f2.event-semantics.v8"
    assert spec["native_weight_authority"]["native_header_bound_mass_kg"] == MODULE.NATIVE_FLOAT32_MASSFLUID_KG


def test_v8_aperture_uses_frozen_v6_interpolated_pose():
    origin = np.asarray([0.0, 0.0, 0.0])
    axis = np.asarray([0.0, 1.0, 0.0])
    low = np.asarray([0.0, 0.0, 0.0])
    high = np.asarray([1.0, 1.0, 1.0])
    previous_body = np.asarray([[0.5, 0.5, 0.9]])
    current_body = np.asarray([[1.2, 0.5, 1.1]])
    previous_world = MODULE.v6_module._inverse_rotate(previous_body, origin, axis, 0.0)
    current_world = MODULE.v6_module._inverse_rotate(current_body, origin, axis, -0.4)
    previous_margin = np.asarray([-0.1])
    current_margin = np.asarray([0.1])

    crossing = MODULE.v6_module._interpolated_top_aperture(
        previous_world, current_world, previous_margin, current_margin,
        0.0, 0.4, origin, axis, low, high, 0.01,
    )
    assert bool(crossing[0])
    assert current_body[0, 0] > high[0]
