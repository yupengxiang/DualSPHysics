from __future__ import annotations

import h5py
import numpy as np
from pathlib import Path
import shutil

import pytest

from scripts.core_cfd_dataset import (CoreCFDDataset, adapt_manifest,
                                      geometry_from_cfd_config,
                                      known_inputs_from_cfd_config, sha256_file)
from scripts.core_contract import PrescribedGeometry
from scripts.f7_pump_geometry_adapter_v1 import COORDINATE_FRAME, PUMP_RELATIVE_DIR


LAB = Path(__file__).resolve().parents[1]


def _config():
    return {
        "family": "F7",
        "scope_id": "F7_pump_recirculation_x_v1",
        "case_id": "F7_pump_adapter_contract_test",
        "coordinate_frame": COORDINATE_FRAME,
        "dp_m": 0.0075,
        "time_max_s": 1.0,
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "pump": {
            "definition": f"{PUMP_RELATIVE_DIR}/CasePump_Def.xml",
            "fixed_geometry": f"{PUMP_RELATIVE_DIR}/pump_fixed.vtk",
            "moving_geometry": f"{PUMP_RELATIVE_DIR}/pump_moving.vtk",
            "motion_sample_interval_s": 0.25,
        },
    }


def test_f7_official_pump_is_wired_into_core_geometry_contract():
    geometry = geometry_from_cfd_config(_config(), data_root=LAB)
    assert isinstance(geometry, PrescribedGeometry)
    assert geometry.coordinate_frame == COORDINATE_FRAME
    assert geometry.moving_body_id == 2
    assert geometry.triangles.shape == (58707, 3, 3)
    assert geometry.motion_sha256
    assert geometry.sample_times[-1] == 1.0


def test_f7_known_inputs_preserve_pump_motion_semantics_without_runtime():
    known = known_inputs_from_cfd_config(_config(), family="F7", data_root=LAB)
    assert isinstance(known.geometry, PrescribedGeometry)
    assert known.physics["family"] == "F7"
    assert known.physics["geometry_motion_semantics"] == (
        "declared_f7_pump_rotation_pose_and_wall_velocity"
    )
    assert known.physics["geometry_motion_sha256"] == known.geometry.motion_sha256


def test_f7_requires_explicit_pump_assets_and_root(tmp_path):
    config = _config()
    config.pop("pump")
    with pytest.raises(ValueError, match="explicit pump asset mapping"):
        geometry_from_cfd_config(config, data_root=LAB)
    with pytest.raises(ValueError, match="explicit data_root"):
        geometry_from_cfd_config(_config())


def test_non_f7_config_cannot_enter_pump_adapter():
    config = _config()
    config["family"] = "F4"
    with pytest.raises(ValueError, match="family=F7"):
        geometry_from_cfd_config(config, data_root=LAB)


def test_f7_source_manifest_crosses_core_adapter_boundary_without_runtime(tmp_path):
    source_dir = tmp_path / PUMP_RELATIVE_DIR
    source_dir.mkdir(parents=True)
    for name in ("CasePump_Def.xml", "pump_fixed.vtk", "pump_moving.vtk"):
        shutil.copyfile(LAB / PUMP_RELATIVE_DIR / name, source_dir / name)
    path = tmp_path / "trajectory.h5"
    position = np.zeros((2, 2, 3), dtype=float)
    velocity = np.zeros_like(position)
    with h5py.File(path, "w") as handle:
        handle["time"] = [0.0, 0.01]
        handle["position"] = position
        handle["velocity"] = velocity
        handle["particle_id"] = [1, 2]
        handle["particle_zone"] = [1, 1]
        handle["mass"] = [1.0, 1.0]
        handle["valid"] = [[True, True], [True, True]]
    payload = {
        "schema": "core.cfd.v1",
        "cases": [{
            "case_id": "f7-adapter-contract",
            "physical_case_id": "f7-adapter-contract",
            "lineage_group_id": "f7-adapter-contract",
            "family": "F7",
            "split": "train",
            "hdf5": "trajectory.h5",
            "sha256": sha256_file(path),
            "prepared": {"config": _config()},
        }],
    }

    canonical = adapt_manifest(payload, tmp_path)
    assert canonical["cases"][0]["family"] == "F7"
    assert canonical["cases"][0]["known_inputs"]["geometry"]["prescribed_motion"]["sha256"]
    with CoreCFDDataset(payload, tmp_path) as data:
        state = data.read_state("f7-adapter-contract", 0)
        assert state.count == 2
