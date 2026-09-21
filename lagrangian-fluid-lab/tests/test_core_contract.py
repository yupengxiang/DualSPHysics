import copy
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.core_contract import (FiniteGeometry, KnownInputs, PrescribedControl, State,
                                   StepPrediction, apply_prediction, commit, contract_hash,
                                   updater_oracle)
from scripts.core_dataset import (CoreDataset, import_f3_manifest, new_scope_split,
                                  sha256_file, validate_manifest)


def example_state(time=0.):
    return State(time, np.array([[0., 0., .1], [.01, 0., .1]]), np.zeros((2, 3)),
                 np.array([11, 12]), np.zeros(2, dtype=int), np.ones(2), np.ones(2, dtype=bool))


def example_known():
    spec = {"container_interior": {"xmin": -1., "xmax": 1., "ymin": -1., "ymax": 1., "zmin": 0., "zmax": 1.},
            "closed_faces": ["left", "right", "front", "back", "bottom"], "open_faces": ["top"], "obstacles": []}
    return KnownInputs(FiniteGeometry.from_wall_spec(spec, coordinate_frame="test"),
                       PrescribedControl(np.array([[0., 0., 0., -9.81, 0., 0., 0.], [2., 0., 0., -9.81, 0., 0., 0.]])),
                       {"reference_density_kgm3": 1000.}, {"dp_m": .01, "h_m": .016}, "test")


def tiny_manifest(tmp_path):
    state = example_state()
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as handle:
        handle["time"] = [0., .01]
        handle["position"] = np.stack((state.position, state.position + .003))
        handle["velocity"] = np.stack((state.velocity, state.velocity + .7))
        handle["particle_id"] = state.particle_id
        handle["particle_zone"] = state.particle_zone
        handle["mass"] = state.mass
        handle["valid"] = np.stack((state.valid, state.valid))
    known = example_known()
    return {"schema": "core.dataset.v1", "cases": [{"case_id": "tiny", "physical_case_id": "tiny", "lineage_group_id": "tiny",
        "family": "F3", "split": "train", "hdf5": "data.h5", "sha256": sha256_file(path),
        "bytes": path.stat().st_size, "known_inputs": known.as_dict(), "known_inputs_sha256": contract_hash(known)}]}


def test_actual_updater_preserves_independent_native_velocity():
    state = example_state()
    prediction = StepPrediction(np.full((2, 3), .003), np.full((2, 3), .7))
    following = commit(state, prediction, .01)
    assert np.allclose(following.velocity, .7)
    assert following.time == following.time_s == .01
    assert np.array_equal(following.velocity_native_estimate, following.velocity)
    assert np.array_equal(prediction.displacement_m, prediction.displacement)
    assert np.array_equal(prediction.delta_velocity_mps, prediction.delta_velocity)
    known = example_known()
    assert known.current_geometry is known.geometry
    assert known.prescribed_control is known.control
    assert not np.allclose(following.velocity, prediction.displacement / .01)
    oracle = updater_oracle(state, following)
    assert oracle["position_max_abs_error"] == 0.
    assert oracle["native_velocity_max_abs_error"] == 0.
    assert oracle["learned_model_qualified"] is False
    with pytest.raises(ValueError, match="nonfinite"):
        apply_prediction(state, StepPrediction(np.full((2, 3), np.nan), np.zeros((2, 3))), .01)
    assert np.allclose(state.position[:, 2], .1)
    with pytest.raises(ValueError):
        state.position[0, 0] = 4.


def test_geometry_is_finite_and_open_top_absent():
    geometry = example_known().geometry
    assert geometry.triangles.shape == (10, 3, 3)
    assert len(np.unique(geometry.component_id)) == 5
    assert not np.any(np.all(geometry.triangles[:, :, 2] == 1., axis=1))
    with pytest.raises(ValueError, match="degenerate"):
        FiniteGeometry(np.zeros((1, 3, 3)), [0], [0], [[0., 0., 0.]], "test")


def test_known_input_cannot_carry_a_reader_or_future_reference():
    known = example_known()
    for forbidden in ({"future_fluid_velocity": [1, 2, 3]}, {"callback": lambda: 1}, {"reader": object()}):
        with pytest.raises(ValueError):
            KnownInputs(known.geometry, known.control, forbidden, known.numerics, known.coordinate_frame)
    with pytest.raises(ValueError, match="providers"):
        KnownInputs(known.geometry, lambda: "reference", {}, known.numerics, known.coordinate_frame)
    original = known.control.samples.copy()
    assert np.array_equal(known.control.samples, original)


def test_known_input_rejects_generic_future_state_aliases_recursively():
    """The causal boundary must reject aliases beyond future_fluid_*.

    ``reference_density_kgm3`` remains valid physical metadata, while generic
    future/reference particle-state fields are rejected even when nested.
    """
    known = example_known()
    for forbidden in (
        {"future_state": [1, 2, 3]},
        {"future_velocity": [1, 2, 3]},
        {"future_state_position": [1, 2, 3]},
        {"nested": {"target_state": {"position": [1, 2, 3]}}},
        {"nested": {"reference": {"position": [1, 2, 3]}}},
        {"futureState": {"position": [1, 2, 3]}},
        {"trajectory_path": "future.h5"},
    ):
        with pytest.raises(ValueError, match="future/reference"):
            KnownInputs(known.geometry, known.control, forbidden,
                        known.numerics, known.coordinate_frame)
    KnownInputs(known.geometry, known.control,
                {"reference_density_kgm3": 1000.0},
                known.numerics, known.coordinate_frame)


def test_portable_reader_and_train_only_boundary(tmp_path):
    manifest = tiny_manifest(tmp_path)
    path = tmp_path / "manifest.json"; path.write_text(json.dumps(manifest))
    with CoreDataset(path) as data:
        current, known, dt, target = data.training_transition("tiny", 0)
        assert current.count == 2 and dt == .01
        assert np.allclose(target.delta_velocity, .7)
        assert not hasattr(known, "read_state")
        assert data.verify_sources()["tiny"] == manifest["cases"][0]["sha256"]
        assert data.oracle("tiny")["particle_count"] == 2
    manifest["cases"][0]["split"] = "test"
    with CoreDataset(manifest, tmp_path) as data:
        with pytest.raises(ValueError, match="train"):
            data.training_transition("tiny", 0)
    manifest["cases"][0]["hdf5"] = "../outside.h5"
    with pytest.raises(ValueError, match="nonportable"):
        CoreDataset(manifest, tmp_path)


def test_reader_binds_initial_mass_and_ignores_inactive_payload_nan(tmp_path):
    manifest = tiny_manifest(tmp_path)
    path = tmp_path / "data.h5"
    with h5py.File(path, "r+") as handle:
        del handle["mass"]
        handle.create_dataset("mass", data=np.asarray([[1.0, 1.0], [1.0, np.nan]]))
        handle["valid"][1] = np.asarray([True, False])
    manifest["cases"][0]["sha256"] = sha256_file(path)
    manifest["cases"][0]["bytes"] = path.stat().st_size
    with CoreDataset(manifest, tmp_path) as data:
        state = data.read_state("tiny", 1)
        assert state.valid.tolist() == [True, False]
        assert np.array_equal(state.mass, np.ones(2))

    with h5py.File(path, "r+") as handle:
        handle["mass"][1, 0] = 1.5
    manifest["cases"][0]["sha256"] = sha256_file(path)
    manifest["cases"][0]["bytes"] = path.stat().st_size
    with CoreDataset(manifest, tmp_path) as data:
        with pytest.raises(ValueError, match="active particle masses"):
            data.read_state("tiny", 1)


@pytest.mark.parametrize("invalid_values", [
    np.asarray([[2, 1], [1, 1]], dtype=np.int64),
    np.asarray([[0.5, 1.0], [1.0, 1.0]], dtype=np.float64),
    np.asarray([[np.nan, 1.0], [1.0, 1.0]], dtype=np.float64),
])
def test_reader_rejects_nonbinary_valid_mask(tmp_path, invalid_values):
    manifest = tiny_manifest(tmp_path)
    path = tmp_path / "data.h5"
    with h5py.File(path, "r+") as handle:
        del handle["valid"]
        handle.create_dataset("valid", data=invalid_values)
    manifest["cases"][0]["sha256"] = sha256_file(path)
    manifest["cases"][0]["bytes"] = path.stat().st_size

    with CoreDataset(manifest, tmp_path) as data:
        with pytest.raises(ValueError, match="valid"):
            data.times("tiny")


def test_lineage_and_qualification_cannot_cross_splits(tmp_path):
    manifest = tiny_manifest(tmp_path)
    extra = copy.deepcopy(manifest["cases"][0]); extra.update(case_id="other", physical_case_id="other", split="validation")
    manifest["cases"].append(extra)
    with pytest.raises(ValueError, match="lineage"):
        validate_manifest(manifest)
    manifest["cases"].pop()
    manifest["cases"][0]["qualification_case"] = True
    with pytest.raises(ValueError, match="qualification"):
        validate_manifest(manifest)


def test_resolution_views_can_share_physical_identity_only_within_split(tmp_path):
    manifest = tiny_manifest(tmp_path)
    view = copy.deepcopy(manifest["cases"][0])
    view.update(case_id="view", lineage_group_id="view-lineage", split="train")
    manifest["cases"].append(view)
    validate_manifest(manifest)
    view["split"] = "validation"
    view["qualification_case"] = False
    manifest["cases"][-1] = view
    with pytest.raises(ValueError, match="physical case crosses splits"):
        validate_manifest(manifest)


def test_new_split_is_interpolation_and_extrapolation_not_qualification():
    rows = new_scope_split(.9, 1.1)
    assert [sum(row["split"] == split for row in rows) for split in ("train", "validation", "id_test", "ood_test")] == [16, 4, 6, 6]
    training = [row["parameter"] for row in rows if row["split"] == "train"]
    for row in rows:
        if row["split"] in ("validation", "id_test"):
            assert min(training) < row["parameter"] < max(training)
        if row["split"] == "ood_test":
            assert not min(training) <= row["parameter"] <= max(training)


def test_registered_f3_real_complete_axis_and_actual_updater():
    lab = Path(__file__).resolve().parents[1]
    source = lab / "campaigns/l2-multifamily/evidence/f3-canonical-manifest.json"
    if not source.is_file() or not (lab / "campaigns/l1-resume/data/continuation/F3_DEV_06_a0p940625.h5").is_file():
        pytest.skip("registered local F3 assets are not installed")
    manifest = import_f3_manifest(source, lab)
    assert [sum(row["split"] == split for row in manifest["cases"]) for split in ("train", "validation", "test")] == [16, 4, 12]
    assert all(row["evaluation_role"] == "development_extrapolation" for row in manifest["cases"] if row["split"] == "test")
    with CoreDataset(manifest, lab) as data:
        case = "F3_DEV_06_a0p940625"
        assert len(data.times(case)) == 836
        initial = data.read_state(case, 0)
        assert initial.count == 34560 and initial.valid.all()
        for frame in (0, 400, 834):
            result = data.oracle(case, frame)
            assert result["particle_count"] == 34560
            assert result["position_max_abs_error"] < 1e-12
            assert result["native_velocity_max_abs_error"] < 1e-12
