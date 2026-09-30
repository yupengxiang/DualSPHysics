from __future__ import annotations

import numpy as np

from scripts.f2_native_observations import _event_rows, _physical_and_numerical_hashes


def test_event_crossing_is_interpolated_and_pre_hold_crossing_is_excluded() -> None:
    times = np.asarray([0.49, 0.50, 0.51, 0.52])
    margin = np.asarray([[-0.1], [0.1], [-0.1], [0.1]])
    valid = np.ones_like(margin, dtype=bool)
    rows = _event_rows(
        code=3,
        direction=1,
        times=times,
        margin=margin,
        aperture=None,
        valid=valid,
        mass=np.asarray([2.0]),
        zone=np.asarray([4]),
        idp=np.asarray([9]),
        source_mk=np.asarray([2]),
        source_layer=np.asarray([1]),
        start_time=0.50,
    )
    assert len(rows) == 1
    assert rows[0][0] == 0.515
    assert rows[0][8] == 2.0


def test_physical_hash_is_stable_when_only_numerical_recipe_changes() -> None:
    owner = {
        "family_id": "F2",
        "physical_case_id": "F2_TEST",
        "geometry_family_id": "G",
        "geometry": {"cup_low_m": [0.0, 0.0, 0.0]},
        "parameter_values": {"receiver_y_m": 0.2},
        "event_window": {"complete_event_window_s": 4.0},
        "control_family_id": "C",
        "resolution": "coarse",
        "solver_parameters": {"DtFixed": 0.0, "TimeOut": 0.01},
    }
    attrs = {"motion_control_copied_sha256": "a" * 64, "source_format": "native", "resolution": "coarse"}
    first = _physical_and_numerical_hashes(owner, attrs)
    owner["solver_parameters"]["DtFixed"] = 1.0e-5
    second = _physical_and_numerical_hashes(owner, attrs)
    assert first["physical_condition_sha256"] == second["physical_condition_sha256"]
    assert first["numerical_recipe_sha256"] != second["numerical_recipe_sha256"]
