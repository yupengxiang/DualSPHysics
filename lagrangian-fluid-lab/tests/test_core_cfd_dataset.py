import json
from pathlib import Path

import h5py
import numpy as np
import pytest

import scripts.core_cfd_dataset as cfd_dataset_module
from scripts.core_cfd_dataset import (CoreCFDDataset, adapt_manifest,
                                      geometry_from_cfd_config, known_inputs_from_cfd_config,
                                      open_dataset)
from scripts.core_contract import (DUALSPHYSICS_MVROTFILE_ROTATION_VERSION,
                                   PrescribedGeometry, State)
from scripts.core_dataset import sha256_file
from scripts.core_f2 import static_config
from scripts.core_models import node_features


def _trajectory(path):
    position = np.array([[[.1, .1, .1], [.2, .1, .1]],
                         [[.11, .1, .1], [.2, .1, .1]]], dtype=float)
    velocity = np.array([[[1., 0., 0.], [0., 0., 0.]],
                         [[1., 0., 0.], [0., 0., 0.]]], dtype=float)
    with h5py.File(path, "w") as handle:
        handle["time"] = [0., .01]
        handle["position"] = position
        handle["velocity"] = velocity
        handle["particle_id"] = [1, 2]
        handle["particle_zone"] = [0, 0]
        handle["mass"] = [1., 1.]
        handle["valid"] = [[True, True], [True, True]]


def _prepared(family):
    if family == "F1":
        return {
            "config": {
                "family": "F1", "scope_id": "F1_test", "case_id": "f1",
                "recipe_id": "f1_recipe", "dp_m": .01,
                "gravity_m_s2": [0., 0., -9.81], "stage": "production",
                "time_max_s": .2,
                "wall_spec": {
                    "container_interior": {"xmin": 0., "xmax": 1., "ymin": 0., "ymax": 1.,
                                           "zmin": 0., "zmax": 1.},
                    "closed_faces": ["left", "right", "front", "back", "bottom"],
                    "open_faces": ["top"],
                    "obstacles": [{"id": "block", "xmin": .4, "xmax": .6,
                                   "ymin": .4, "ymax": .6, "zmin": 0., "zmax": .3}],
                },
                "physical_case_id": "f1-physical", "lineage_group_id": "f1-lineage",
            }
        }
    return {
        "config": {
            "family": "F4", "scope_id": "F4_test", "case_id": "f4",
            "recipe_id": "f4_recipe", "dp_m": .01,
            "gravity_m_s2": [0., 0., -9.81], "stage": "production",
            "time_max_s": .2, "wall_bounds": {"xmin": 0., "xmax": 1., "ymin": 0., "ymax": 1.,
                                                   "zmin": 0., "zmax": 1.},
            "closed_faces": ["left", "right", "front", "back", "bottom"],
            "open_faces": ["top"], "physical_case_id": "f4-physical",
            "lineage_group_id": "f4-lineage",
        }
    }


def test_cfd_adapter_builds_causal_inputs_and_full_public_state(tmp_path):
    hdf5 = tmp_path / "trajectory.h5"
    _trajectory(hdf5)
    source = {
        "schema": "core.cfd.dataset.v1", "dataset_id": "synthetic-cfd",
        "cases": [{"case_id": "f1", "family": "F1", "split": "train",
                   "prepared_record": _prepared("F1"), "hdf5": "trajectory.h5",
                   "sha256": sha256_file(hdf5)}],
    }
    manifest = adapt_manifest(source, tmp_path)
    row = manifest["cases"][0]
    assert row["split"] == "train" and row["qualification_case"] is False
    assert row["known_inputs"]["geometry"]["body_id"]
    with CoreCFDDataset(source, tmp_path) as data:
        current, known, dt, target = data.training_transition("f1", 0)
        assert current.position.shape == current.velocity.shape == (2, 3)
        assert current.particle_id.tolist() == [1, 2]
        assert current.particle_zone.tolist() == [0, 0]
        assert current.mass.tolist() == [1., 1.]
        assert current.valid.tolist() == [True, True]
        assert dt == pytest.approx(.01)
        assert target.displacement.shape == (2, 3)
        assert known.physics["family"] == "F1"


@pytest.mark.parametrize("protected", [
    {"qualification_only": True},
    {"split": "qualification_only"},
    {"stage": "qualification"},
    {"stage": "repair_canary", "qualification_only": False},
    {"stage": "calibration"},
    {"stage": "canary"},
])
@pytest.mark.parametrize("requested_split", ["train", "validation", "test"])
def test_prepared_qualification_cannot_be_overridden_by_wrapper(tmp_path, protected, requested_split):
    hdf5 = tmp_path / "trajectory.h5"
    _trajectory(hdf5)
    prepared = _prepared("F4")
    prepared["config"].update(protected)
    source = {"schema": "core.cfd.dataset.v1", "dataset_id": "protected-lineage",
              "cases": [{"case_id": "f4", "family": "F4", "split": requested_split,
                         "qualification_only": False, "prepared_record": prepared,
                         "hdf5": "trajectory.h5", "sha256": sha256_file(hdf5)}]}
    manifest = adapt_manifest(source, tmp_path)
    assert manifest["cases"][0]["split"] == "qualification"
    assert manifest["cases"][0]["qualification_case"] is True
    with CoreCFDDataset(source, tmp_path) as data:
        assert not data.case_ids(split="train")
        assert not data.case_ids(split="validation")
        assert not data.case_ids(split="test")


def test_cfd_adapter_preserves_declared_physical_viscosity_only():
    config = _prepared("F4")["config"]
    # ``Visco`` is deliberately a numerical/artificial coefficient.  It must
    # not become a material property in KnownInputs.physics.
    config["Visco"] = 0.08
    known = known_inputs_from_cfd_config(config, family="F4")
    assert "physical_kinematic_viscosity_m2_s" not in known.physics
    assert "viscosity_formulation" not in known.physics

    config.update(physical_kinematic_viscosity_m2_s=1.0e-6,
                  viscosity_formulation="laminar")
    known = known_inputs_from_cfd_config(config, family="F4")
    assert known.physics["physical_kinematic_viscosity_m2_s"] == pytest.approx(1.0e-6)
    assert known.physics["viscosity_formulation"] == "laminar"
    assert known.physics["viscosity_source"] == (
        "declared_physical_kinematic_viscosity_m2_s")

    invalid = dict(config, viscosity_formulation="artificial")
    with pytest.raises(ValueError, match="laminar formulation"):
        known_inputs_from_cfd_config(invalid, family="F4")

    missing_value = dict(config)
    missing_value.pop("physical_kinematic_viscosity_m2_s")
    with pytest.raises(ValueError, match="requires physical_kinematic_viscosity"):
        known_inputs_from_cfd_config(missing_value, family="F4")


def test_cfd_adapter_accepts_absolute_path_under_root_and_cli_factory(tmp_path):
    hdf5 = tmp_path / "trajectory.h5"
    _trajectory(hdf5)
    source = {"schema": "core.production_design.v1", "family": "F4", "cases": [
        {"case_id": "f4", "family": "F4", "split": "validation",
         "prepared": _prepared("F4"), "trajectory": str(hdf5),
         "sha256": sha256_file(hdf5)}]}
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source))
    with open_dataset(source_path, tmp_path) as data:
        assert data.case_ids("validation") == ("f4",)
        assert data.known_inputs("f4").geometry.triangles.shape[0] == 10


def test_path_backed_cfd_manifest_rejects_duplicate_json_keys(tmp_path):
    source_path = tmp_path / "duplicate-source.json"
    source_path.write_bytes(
        b'{"schema":"core.cfd.dataset.v1","schema":"core.cfd.dataset.v2","cases":[]}')
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        open_dataset(source_path, tmp_path)


def test_path_backed_prepared_record_rejects_duplicate_json_keys(tmp_path):
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_bytes(b'{"config":{"stage":"production","stage":"canary"}}')
    source = {
        "schema": "core.cfd.dataset.v1", "family": "F4",
        "cases": [{"case_id": "f4", "family": "F4", "split": "train",
                   "prepared": prepared_path.name, "hdf5": "missing.h5"}],
    }
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        adapt_manifest(source, tmp_path)


def test_cfd_source_manifest_hash_is_bound_to_parsed_raw_bytes(tmp_path, monkeypatch):
    hdf5 = tmp_path / "trajectory.h5"
    _trajectory(hdf5)
    source = {
        "schema": "core.cfd.dataset.v1", "dataset_id": "bound-source",
        "cases": [{"case_id": "f1", "family": "F1", "split": "train",
                   "prepared_record": _prepared("F1"), "hdf5": hdf5.name,
                   "sha256": sha256_file(hdf5)}],
    }
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source))
    parsed_raw = source_path.read_bytes()
    replacement_raw = b'{"schema":"core.cfd.dataset.v1","cases":[]}'
    read_raw = cfd_dataset_module.read_bounded_raw_json
    replaced = False

    def read_then_replace(path, **kwargs):
        nonlocal replaced
        raw = read_raw(path, **kwargs)
        if Path(path) == source_path and not replaced:
            source_path.write_bytes(replacement_raw)
            replaced = True
        return raw

    monkeypatch.setattr(cfd_dataset_module, "read_bounded_raw_json", read_then_replace)
    adapted = adapt_manifest(source_path, tmp_path)
    assert replaced
    assert source_path.read_bytes() == replacement_raw
    assert adapted["source_manifest_sha256"] == cfd_dataset_module.sha256_bytes(parsed_raw)


def test_static_qualification_design_cannot_be_silently_trained(tmp_path):
    source = {"schema": "core.f1.qualification.v1", "family": "F1",
              "cells": [{"case_id": "f1-q", "stage": "qualification",
                         "family": "F1", "split": "qualification"}]}
    with pytest.raises(ValueError, match="no trajectory HDF5"):
        adapt_manifest(source, tmp_path)


def test_cfd_adapter_preserves_physical_identity_and_rejects_cross_split(tmp_path):
    hdf5 = tmp_path / "trajectory.h5"
    _trajectory(hdf5)
    sha = sha256_file(hdf5)
    prepared = _prepared("F4")
    same_physical = {
        "schema": "core.cfd.dataset.v1", "family": "F4",
        "cases": [
            {"case_id": "f4-dp-a", "family": "F4", "split": "qualification",
             "qualification_only": True, "physical_case_id": "same-process",
             "prepared_record": prepared, "hdf5": "trajectory.h5", "sha256": sha},
            {"case_id": "f4-dp-b", "family": "F4", "split": "qualification",
             "qualification_only": True, "physical_case_id": "same-process",
             "prepared_record": prepared, "hdf5": "trajectory.h5", "sha256": sha},
        ],
    }
    adapted = adapt_manifest(same_physical, tmp_path)
    assert [row["physical_case_id"] for row in adapted["cases"]] == ["same-process"] * 2

    leaked = json.loads(json.dumps(same_physical))
    leaked["cases"][1]["split"] = "validation"
    leaked["cases"][1]["qualification_only"] = False
    with pytest.raises(ValueError, match="physical case crosses splits"):
        adapt_manifest(leaked, tmp_path)

    no_hash = json.loads(json.dumps(same_physical))
    no_hash["cases"][0].pop("sha256")
    with pytest.raises(ValueError, match="declared HDF5 SHA"):
        adapt_manifest(no_hash, tmp_path)


def test_obstacle_geometry_is_explicit_finite_mesh():
    geometry = geometry_from_cfd_config(_prepared("F1")["config"])
    # Five closed tank faces plus a six-faced obstacle, each triangulated.
    assert geometry.triangles.shape == (22, 3, 3)
    assert set(geometry.body_id.tolist()) == {0, 1}
    obstacle = geometry.body_id == 1
    normals = np.cross(geometry.triangles[:, 1] - geometry.triangles[:, 0],
                       geometry.triangles[:, 2] - geometry.triangles[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    # The fluid-facing normal on the obstacle points out of the obstacle.  The
    # adjacent container wall points into the container cavity.
    assert any(np.allclose(vector, [-1., 0., 0.]) for vector in normals[obstacle])
    assert any(np.allclose(vector, [1., 0., 0.]) for vector in normals[obstacle])
    assert any(np.allclose(vector, [1., 0., 0.]) for vector in normals[~obstacle])
    assert any(np.allclose(vector, [-1., 0., 0.]) for vector in normals[~obstacle])


def _f2_prepared(tmp_path, *, dynamic=False):
    config = static_config()
    config["stage"] = "production" if dynamic else "canary"
    config["scope_id"] = "F2_dynamic_rotation_test" if dynamic else config["scope_id"]
    if dynamic:
        motion = tmp_path / "cup-motion.dat"
        motion.write_text("#Time;Degrees\n0.0;0.0\n0.5;-10.0\n1.0;-20.0\n")
        config["dynamic"] = True
        config["prescribed_motion"] = {
            "path": motion.name,
            "sha256": sha256_file(motion),
            "axis_point": [0.0, 0.0, 0.65],
            "axis_direction": [0.0, 1.0, 0.0],
            "angle_units": "degrees",
            "moving_body_id": 0,
        }
    return config


def test_f2_static_cup_is_explicit_finite_geometry_and_qualification_only(tmp_path):
    hdf5 = tmp_path / "trajectory.h5"
    _trajectory(hdf5)
    config = _f2_prepared(tmp_path)
    source = {"schema": "core.f2.static_hold.v1", "cases": [
        {"case_id": "f2-static", "family": "F2", "prepared_record": {"config": config},
         "hdf5": hdf5.name, "sha256": sha256_file(hdf5)}]}
    adapted = adapt_manifest(source, tmp_path)
    row = adapted["cases"][0]
    assert row["split"] == "qualification" and row["qualification_case"] is True
    assert len(row["known_inputs"]["geometry"]["triangles"]) == 22
    assert set(row["known_inputs"]["geometry"]["body_id"]) == {0, 1, 2}
    # Pointing at the rotating source definition for provenance must not
    # silently turn this zero-angle canary into a dynamic contract.
    lab = Path(__file__).resolve().parents[1]
    static_from_registered_source = static_config()
    assert type(known_inputs_from_cfd_config(static_from_registered_source, family="F2",
                                             data_root=lab).geometry).__name__ == "FiniteGeometry"


def test_f2_dynamic_contract_uses_declared_pose_and_wall_velocity_only(tmp_path):
    hdf5 = tmp_path / "trajectory.h5"
    _trajectory(hdf5)
    # This reference-like field is intentionally present: the adapter must
    # not use it to construct the public geometry contract.
    with h5py.File(hdf5, "a") as handle:
        handle["control/cup_world_from_body"] = np.broadcast_to(np.eye(4), (2, 4, 4))
    config = _f2_prepared(tmp_path, dynamic=True)
    source = {"schema": "core.f2.dynamic.v1", "cases": [
        {"case_id": "f2-dynamic", "family": "F2", "split": "validation",
         "prepared_record": {"config": config}, "hdf5": hdf5.name,
         "sha256": sha256_file(hdf5)}]}
    adapted = adapt_manifest(source, tmp_path)
    known_payload = adapted["cases"][0]["known_inputs"]
    assert known_payload["geometry"]["version"] == "core.prescribed_geometry.v1"
    assert known_payload["geometry"]["prescribed_motion"]["angle_degrees"][-1] == pytest.approx(-20.)
    assert (known_payload["geometry"]["prescribed_motion"]["version"]
            == DUALSPHYSICS_MVROTFILE_ROTATION_VERSION)
    with CoreCFDDataset(source, tmp_path) as data:
        known = data.known_inputs("f2-dynamic")
        assert isinstance(known.geometry, PrescribedGeometry)
        before, after = known.geometry_at(.0), known.geometry_at(.5)
        moving = before.body_id == 0
        assert not np.allclose(before.triangles[moving], after.triangles[moving])
        assert np.max(np.linalg.norm(after.wall_velocity[moving], axis=1)) > 0
        # The native mvrotfile convention is explicit: a -10 degree sidecar
        # sample about +y produces the right-handed +10 degree pose and +y
        # angular velocity used by the DualSPHysics arbitrary-axis matrix.
        expected = np.array([[np.cos(np.deg2rad(10.)), 0., np.sin(np.deg2rad(10.))],
                             [0., 1., 0.],
                             [-np.sin(np.deg2rad(10.)), 0., np.cos(np.deg2rad(10.))]])
        np.testing.assert_allclose(known.geometry.world_from_body_at(.5)[:3, :3], expected)
        centres = after.triangles[moving].mean(axis=1)
        expected_wall = np.cross(np.broadcast_to([0., np.deg2rad(20.), 0.], centres.shape),
                                 centres - known.geometry.axis_point)
        np.testing.assert_allclose(after.wall_velocity[moving], expected_wall)
        state = State(.5, np.array([[.1, 0., .8]]), np.zeros((1, 3)), [1], [0], [1.], [True])
        features, _ = node_features(state, known, .01)
        assert features.shape == (1, 23) and np.isfinite(features).all()


def test_f2_catchment_is_visible_static_and_open_above(tmp_path):
    config = _f2_prepared(tmp_path, dynamic=True)
    config["catchment"] = {"mkbound": 3}
    with pytest.raises(ValueError, match="catchment_wall_spec"):
        known_inputs_from_cfd_config(config, family="F2", data_root=tmp_path)
    config["catchment_wall_spec"] = {
        "container_interior": {"xmin": -.6, "xmax": 2., "ymin": -.55, "ymax": .55,
                               "zmin": -.2, "zmax": .6},
        "closed_faces": ["left", "right", "front", "back"], "open_faces": ["top"],
        "mkbound": 3, "floor": {"fluid_facing_surface_z_m": -.2, "material_mkbound": 2}}
    known = known_inputs_from_cfd_config(config, family="F2", data_root=tmp_path)
    before, after = known.geometry_at(0.), known.geometry_at(.5)
    walls = before.body_id == 3
    assert walls.sum() == 8
    np.testing.assert_array_equal(before.triangles[walls], after.triangles[walls])
    np.testing.assert_array_equal(after.wall_velocity[walls], 0.)
    assert not np.any(np.all(np.isclose(before.triangles[walls, :, 2], .6), axis=1))
    floor = before.body_id == 2
    assert floor.sum() == 2
    np.testing.assert_allclose(before.triangles[floor, :, 2], -.2)
    cup = before.body_id == 0
    assert not np.allclose(before.triangles[cup], after.triangles[cup])


def test_f2_dynamic_angle_only_or_missing_axis_is_rejected(tmp_path):
    config = _f2_prepared(tmp_path, dynamic=True)
    config["prescribed_motion"].pop("axis_direction")
    with pytest.raises(ValueError, match="axis_point and axis_direction"):
        geometry_from_cfd_config(config, data_root=tmp_path)
