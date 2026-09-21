"""Qualification-only adapter checks for the prepared F2/F4 engineering cases.

These tests deliberately use the prepared metadata and a tiny native HDF5
fixture.  They do not open a solver output from a running job and they never
put either qualification case into a train, normalization, or checkpoint
selection path.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil

import h5py
import numpy as np
import pytest

from scripts.core_cfd_dataset import (CoreCFDDataset,
                                      known_inputs_from_cfd_config)
from scripts.core_contract import PrescribedGeometry
from scripts.core_dataset import sha256_file
from scripts.core_learning import compute_normalization


LAB = Path(__file__).resolve().parents[1]
F2_PREPARED = LAB / (
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_canary_v3/prepared.json"
)
F4_PREPARED = LAB / (
    "campaigns/core-v1/cfd/prepared/"
    "F4_tallwall120_q075_dp005_canary_v1_preparation_retry/prepared.json"
)


def _native_fixture(path: Path, *, future_reference: bool = False,
                    changed_id: bool = False) -> Path:
    """Write a two-frame complete-particle-axis native source."""
    position = np.asarray([
        [[.10, .10, .10], [.20, .10, .10]],
        [[.11, .10, .10], [.20, .10, .10]],
    ], dtype=np.float64)
    velocity = np.asarray([
        [[1., 0., 0.], [0., 0., 0.]],
        [[1., 0., 0.], [0., 0., 0.]],
    ], dtype=np.float64)
    particle_id = np.asarray([1, 2], dtype=np.int64)
    valid = np.asarray([[True, True], [True, True]], dtype=bool)
    if changed_id:
        # Identity is a full-axis lifecycle field.  A disappearance on the
        # following committed frame must be rejected by updater_oracle.
        valid[1, 1] = False
    with h5py.File(path, "w") as handle:
        handle["time"] = [0., .01]
        handle["position"] = position
        handle["velocity"] = velocity
        handle["particle_id"] = particle_id
        handle["particle_zone"] = [0, 0]
        handle["mass"] = [1., 1.]
        handle["valid"] = valid
        if future_reference:
            # This field resembles a future/reference control record.  The
            # CFD adapter must never inspect it when constructing KnownInputs.
            handle["future/reference_cup_pose"] = np.full((2, 4, 4), 17., dtype=float)
    return path


def _f2_config_in(root: Path) -> dict:
    """Copy only the immutable F2 XML/motion assets needed by the adapter."""
    prepared = json.loads(F2_PREPARED.read_text())
    config = copy.deepcopy(prepared["config"])
    source_dir = F2_PREPARED.parent
    definition = source_dir / Path(config["definition_audit"]["definition"]).name
    motion = source_dir / Path(config["definition_audit"]["motion_file"]).name
    shutil.copy2(definition, root / definition.name)
    shutil.copy2(motion, root / motion.name)
    # Keep the source and audited generated definition portable for the
    # temporary data root.  The copied bytes retain their registered hashes.
    config["source_definition"] = definition.name
    config["definition_audit"]["definition"] = definition.name
    config["definition_audit"]["motion_file"] = motion.name
    return config


def test_prepared_f2_exposes_motion_catchment_and_pointwise_wall_speed():
    """The prepared dynamic F2 row must not collapse to its old static source."""
    prepared = json.loads(F2_PREPARED.read_text())
    config = prepared["config"]
    known = known_inputs_from_cfd_config(config, family="F2", data_root=LAB)
    assert isinstance(known.geometry, PrescribedGeometry)
    assert known.physics["geometry_motion_semantics"] == (
        "declared_f2_rotation_pose_and_wall_velocity")
    assert known.physics["geometry_motion_sha256"] == (
        config["definition_audit"]["motion_sha256"])

    initial = known.geometry_at(0.0)
    moved = known.geometry_at(.85)
    catchment = initial.body_id == 3
    assert int(catchment.sum()) == 8  # four finite side faces, two triangles each
    assert float(initial.triangles[catchment, :, 2].max()) == pytest.approx(.6)
    np.testing.assert_array_equal(initial.triangles[catchment], moved.triangles[catchment])
    np.testing.assert_array_equal(moved.wall_velocity[catchment], 0.)

    # Fluid-facing catchment normals point inward on all four finite sides;
    # the open top contributes no triangle.
    triangles = initial.triangles[catchment]
    normals = np.cross(triangles[:, 1] - triangles[:, 0],
                       triangles[:, 2] - triangles[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    assert {tuple(np.round(vector, 8)) for vector in normals} == {
        (1., 0., 0.), (-1., 0., 0.), (0., 1., 0.), (0., -1., 0.)
    }

    moving_index = int(np.flatnonzero(moved.body_id == 0)[-1])
    points = moved.triangles[moving_index, :2]
    observed = moved.wall_velocity_at(points, moving_index)
    expected = np.cross(np.broadcast_to(moved.rigid_angular_velocity, points.shape),
                        points - known.geometry.axis_point)
    np.testing.assert_allclose(observed, expected)
    assert np.linalg.norm(observed[0] - observed[1]) > 1e-8


def test_f2_reader_oracle_uses_full_axis_and_keeps_qualification_out_of_training(tmp_path):
    config = _f2_config_in(tmp_path)
    hdf5 = _native_fixture(tmp_path / "f2-native.h5", future_reference=True)
    source = {
        "schema": "core.cfd.v1", "dataset_id": "f2-qualification-fixture",
        "cases": [{"case_id": "f2-catchment", "family": "F2",
                    "prepared_record": {"config": config},
                    "hdf5": hdf5.name, "sha256": sha256_file(hdf5)}],
    }
    with CoreCFDDataset(source, tmp_path) as data:
        assert data.case_ids("qualification") == ("f2-catchment",)
        assert data.case_ids("train") == ()
        known = data.known_inputs("f2-catchment")
        assert isinstance(known.geometry, PrescribedGeometry)
        oracle = data.oracle("f2-catchment", 0)
        assert oracle["particle_count"] == 2
        assert oracle["position_max_abs_error"] == 0.
        assert oracle["native_velocity_max_abs_error"] == 0.
        assert data.read_log[-2:] == [("f2-catchment", 0), ("f2-catchment", 1)]
        with pytest.raises(ValueError, match="train cases only"):
            data.training_transition("f2-catchment", 0)
        with pytest.raises(ValueError, match="train split"):
            compute_normalization(data, case_ids=("f2-catchment",),
                                  maximum_transitions=1)


def test_audited_f2_motion_rejects_tampered_xml_and_conflicting_sidecar(tmp_path):
    config = _f2_config_in(tmp_path)
    definition = tmp_path / config["definition_audit"]["definition"]
    original = definition.read_text()
    definition.write_text(original.replace(
        'axisp2 x="0" y="1" z="0.65"',
        'axisp2 x="0" y="1" z="0.66"', 1))
    with pytest.raises(ValueError, match="definition XML hash mismatch"):
        known_inputs_from_cfd_config(config, family="F2", data_root=tmp_path)

    conflict_root = tmp_path / "conflict"
    conflict_root.mkdir()
    conflict = _f2_config_in(conflict_root)
    xml_motion = conflict_root / Path(conflict["definition_audit"]["motion_file"]).name
    alternate = conflict_root / "alternate-motion.dat"
    alternate.write_text(xml_motion.read_text().replace("-105.000000000", "-104.000000000"))
    conflict["definition_audit"]["motion_file"] = alternate.name
    conflict["definition_audit"]["motion_sha256"] = sha256_file(alternate)
    with pytest.raises(ValueError, match="motion conflicts with XML mvrotfile"):
        known_inputs_from_cfd_config(conflict, family="F2", data_root=conflict_root)


def test_f4_prepared_geometry_uses_declared_tall_wall_and_oracle_rejects_axis_change(tmp_path):
    prepared = json.loads(F4_PREPARED.read_text())
    config = prepared["config"]
    known = known_inputs_from_cfd_config(config, family="F4", data_root=LAB)
    assert type(known.geometry).__name__ == "FiniteGeometry"
    assert float(known.geometry.triangles[:, :, 2].max()) == pytest.approx(1.2)
    assert float(known.geometry.triangles[:, :, 2].max()) != pytest.approx(.6)
    assert known.physics["physical_kinematic_viscosity_m2_s"] == pytest.approx(1e-6)

    hdf5 = _native_fixture(tmp_path / "f4-native.h5")
    source = {
        "schema": "core.cfd.v1", "dataset_id": "f4-qualification-fixture",
        "cases": [{"case_id": "f4-tallwall", "family": "F4",
                    "prepared_record": {"config": config},
                    "hdf5": hdf5.name, "sha256": sha256_file(hdf5)}],
    }
    with CoreCFDDataset(source, tmp_path) as data:
        assert data.case_ids("qualification") == ("f4-tallwall",)
        assert data.oracle("f4-tallwall", 0)["particle_count"] == 2

    changed = _native_fixture(tmp_path / "f4-changed.h5", changed_id=True)
    changed_source = copy.deepcopy(source)
    changed_source["cases"][0]["hdf5"] = changed.name
    changed_source["cases"][0]["sha256"] = sha256_file(changed)
    with CoreCFDDataset(changed_source, tmp_path) as data:
        with pytest.raises(ValueError, match="identity/lifecycle/mass change"):
            data.oracle("f4-tallwall", 0)
