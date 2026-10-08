import copy
import importlib.util
from pathlib import Path
import sys

import h5py
import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from ds_data02_stage2_f2_s1_trajectory_labels_operator_v1 import (  # noqa: E402
    finite_crossing,
    materialize,
    validate_config,
)


def fixture(tmp_path):
    source = tmp_path / "trajectory.h5"
    # p1 deliberately re-enters the receiver aperture, p2 crosses once, and
    # p3 disappears after t=1.  The latter is an open-lifecycle censoring
    # control, never a legal-outflow label.
    positions = np.array([
        [[0.0, 0.0, 0.2], [0.0, 0.7, 0.2], [0.0, 0.0, 0.2]],
        [[2.0, 0.0, 0.2], [2.0, 0.7, 0.2], [0.5, 0.0, 0.2]],
        [[0.0, 0.0, 0.2], [2.0, 0.7, 0.2], [np.nan, np.nan, np.nan]],
        [[2.0, 0.0, 0.2], [2.0, 0.7, 0.2], [np.nan, np.nan, np.nan]],
    ])
    with h5py.File(source, "w") as h:
        h.attrs["coordinate_frame"] = "fixed_solver_frame"
        h.create_dataset("time", data=[0.0, 1.0, 2.0, 3.0])
        h.create_dataset("particle_id", data=[1, 2, 3])
        h.create_dataset("particle_zone", data=[0, 0, 0])
        h.create_dataset("initial_mk", data=[1, 2, 3])
        h.create_dataset("valid", data=[[1, 1, 1], [1, 1, 1], [1, 1, 0], [1, 1, 0]])
        h.create_dataset("position", data=positions)
        h.create_dataset("mass", data=np.array([[1.0, 2.0, 3.0]] * 4))
        h.create_dataset("type", data=np.array([[3, 3, 3]] * 4))
    source_boxes = [
        {"id": "mk1", "native_mk": 1, "bounds": [[-1, 1], [-1, 1], [-1, 1]]},
        {"id": "mk2", "native_mk": 2, "bounds": [[-1, 1], [2, 3], [-1, 1]]},
        {"id": "mk3", "native_mk": 3, "bounds": [[-1, 1], [4, 5], [-1, 1]]},
    ]
    regions = [
        {"id": "left", "bounds": [[-1, 1], [-1, 1], [-1, 1]]},
        {"id": "right", "bounds": [[1, 3], [-1, 1], [-1, 1]]},
    ]
    config = {
        "schema": "test",
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "fixed_solver_frame",
        "source_assignment": "native_initial_mk",
        "source_regions": source_boxes,
        "destination_regions": regions,
        "events": [{"id": "receiver", "axis": 0, "value": 1.0,
                    "aperture_bounds": [[-1, 1], [-1, 1]]}],
        "lifecycle_model": "open",
    }
    return source, config


def test_crossing_counts_cancellation_and_open_censoring(tmp_path):
    source, config = fixture(tmp_path)
    output = tmp_path / "labels.h5"
    report = materialize(source, output, config, particle_chunk=2)
    assert report["initial_fluid_mass_kg"] == 6
    with h5py.File(output, "r") as h:
        np.testing.assert_array_equal(h["event_crossing_counts"][:, 0], [[2, 1], [1, 0], [0, 0]])
        np.testing.assert_allclose(h["forward_backward_mass_kg"][-1, 0], [4, 1])
        assert h["cumulative_net_flux_kg"][-1, 0] == 3
        np.testing.assert_allclose(h["first_passage_interval"][0, 0], [0, 1])
        assert h["first_passage_chord_time"][0, 0] == 0.5
        assert h["first_passage_censor"][2, 0] == 1
        assert h["final_category"][2] == -1
        assert h["failure_reason"][2] == 1
        np.testing.assert_allclose(h["missing_identity_gap_bracket"][2], [1.0, 2.0])
        assert h["missing_identity_censor"][2] == 1
        assert h.attrs["missing_identity_semantics"].startswith("open-lifecycle censoring")


def test_controls_reject_alias_and_region_ambiguity(tmp_path):
    source, config = fixture(tmp_path)
    bad = copy.deepcopy(config)
    bad["destination_regions"][1]["bounds"][0] = [0.5, 3]
    with pytest.raises(ValueError, match="overlap"):
        validate_config(bad)
    with h5py.File(source, "r+") as h:
        h["particle_zone"][2] = 0
        h["particle_id"][2] = 1
    with pytest.raises(ValueError, match="typed identity"):
        materialize(source, tmp_path / "alias.h5", config)


def test_negative_axis_entry_is_the_backward_operator_column():
    p0 = np.array([[0.0, 0.0, 1.0]])
    p1 = np.array([[0.0, 0.0, -1.0]])
    forward, backward, _ = finite_crossing(
        p0, p1, {"axis": 2, "value": 0.0, "aperture_bounds": [[-1.0, 1.0], [-1.0, 1.0]]}
    )
    assert not bool(forward[0])
    assert bool(backward[0])


def test_preparation_contract_does_not_hash_h5():
    module_path = SCRIPTS / "ds_data02_stage2_f2_s1_trajectory_labels_v1.py"
    spec = importlib.util.spec_from_file_location("trajectory_worker", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    contract = (SCRIPTS.parent / "campaigns/ds-data-02/stage2/requests/"
                "f2-s1-trajectory-labels-v1/f2-s1-trajectory-source-contract-v1.json")
    original = module.sha256

    def no_h5_digest(path):
        if Path(path).suffix.lower() in {".h5", ".hdf5"}:
            raise AssertionError("prepare must not hash trajectory H5")
        return original(path)

    module.sha256 = no_h5_digest
    info = module.validate_contract(contract, read_h5=False)
    assert info["h5_content_verified"] is False
    assert info["trajectory_hdf5"]["content_read_deferred_until_guarded_run"] is True
