import importlib.util
from pathlib import Path

import h5py
import numpy as np


SCRIPT = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F2/f2_handoff_20261002_event_audit.py"
SPEC = importlib.util.spec_from_file_location("f2_event_audit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_first_passage_uses_native_consecutive_frame_bracket(tmp_path):
    path = tmp_path / "labels.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=np.array([0.0, 0.01, 0.02], dtype=np.float64))
        events = np.array(
            [(0.004, 1, 1, 0, 0, 7, 1, 0, 0.1, 0, 1)],
            dtype=[
                ("time_s", "f8"), ("event_code", "i2"), ("direction", "i1"),
                ("particle_index", "i8"), ("zone", "i8"), ("idp", "i8"),
                ("source_mk", "i4"), ("source_layer_index", "i4"),
                ("mass_kg", "f8"), ("frame_before", "i8"), ("frame_after", "i8"),
            ],
        )
        handle.create_dataset("events", data=events)

    result = MODULE.event_bracket_rows(path, {"cup_departure": 1, "receiver_entry": 3})

    observed = result["events"]["cup_departure"]
    assert observed["bracket_left_s"] == 0.0
    assert observed["bracket_right_s"] == 0.01
    assert observed["bracket_width_s"] == 0.01
    assert observed["bracket_half_width_s"] == 0.005
    assert result["events"]["receiver_entry"]["status"] == "right_censored_or_not_observed"


def test_owner_binding_keeps_grid_phase_out_of_physical_identity():
    binding = MODULE.canonical_physical_binding(
        {
            "physical_case_id": "P",
            "physical_condition_hash_declared": "physical-hash",
            "physical_binding_sha256": "binding-hash",
            "source_motion": {"sha256": "motion-hash"},
            "physical_binding": {
                "geometry_family_id": "G",
                "control_family_id": "C",
                "geometry": {"continuous_size_m": [1.0, 1.0, 1.0], "grid_origin_m": [0.01, 0.02, 0.03]},
                "initial_state": {"initial_mass_total_kg": 1.0},
                "parameters": {"amplitude": 1.0},
            },
        }
    )

    assert binding["physical_condition_hash_declared"] == "physical-hash"
    assert binding["motion_source_sha256"] == "motion-hash"
    assert "grid_origin_m" in binding["geometry"]
    # The caller can inspect and classify grid phase; it is never hashed by this helper.
    assert binding["physical_binding_sha256"] == "binding-hash"
