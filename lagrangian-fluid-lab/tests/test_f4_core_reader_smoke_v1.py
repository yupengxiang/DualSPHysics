import hashlib
import json

import h5py
import numpy as np
import pytest

from scripts.f4_core_reader_smoke_v1 import run_smoke


def _trajectory(path, *, nan_position=False):
    position = np.array([
        [[0.1, 0.1, 0.1], [0.2, 0.1, 0.1]],
        [[0.11, 0.1, 0.1], [0.2, 0.1, 0.1]],
        [[0.12, 0.1, 0.1], [0.2, 0.1, 0.1]],
    ], dtype=float)
    if nan_position:
        position[1, 0, 0] = np.nan
    with h5py.File(path, "w") as handle:
        handle.attrs["split"] = "train"
        handle["time"] = [0.0, 0.01, 0.02]
        handle["position"] = position
        handle["velocity"] = np.zeros_like(position)
        handle["particle_id"] = [1, 2]
        handle["particle_zone"] = [0, 0]
        handle["mass"] = [1.0, 1.0]
        handle["valid"] = np.ones((3, 2), dtype=bool)


def _manifest(path, trajectory):
    config = {
        "family": "F4",
        "scope_id": "F4_smoke_test",
        "case_id": "f4-smoke",
        "recipe_id": "f4_smoke_recipe",
        "dp_m": 0.01,
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "stage": "production",
        "time_max_s": 0.02,
        "wall_bounds": {
            "xmin": 0.0, "xmax": 1.0, "ymin": 0.0, "ymax": 1.0,
            "zmin": 0.0, "zmax": 1.0,
        },
        "closed_faces": ["left", "right", "front", "back", "bottom"],
        "open_faces": ["top"],
        "physical_case_id": "f4-smoke-physical",
        "lineage_group_id": "f4-smoke-lineage",
    }
    digest = hashlib.sha256(trajectory.read_bytes()).hexdigest()
    payload = {
        "schema": "core.cfd.dataset.v1",
        "dataset_id": "f4-smoke",
        "cases": [{
            "case_id": "f4-smoke",
            "family": "F4",
            "split": "train",
            "prepared_record": {"config": config},
            "hdf5": trajectory.name,
            "sha256": digest,
        }],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_smoke_reads_all_contracts_and_stays_diagnostic(tmp_path):
    trajectory = tmp_path / "trajectory.h5"
    manifest = tmp_path / "manifest.json"
    _trajectory(trajectory)
    _manifest(manifest, trajectory)

    result = run_smoke(manifest, tmp_path)

    assert result["schema"] == "local.f4.core_reader_smoke.v1"
    assert result["case_count"] == result["source_hashes_verified"] == 1
    assert result["reader_formal_eligible"] is False
    assert result["diagnostic_only"] is True
    assert result["qualification_credit"] == 0
    assert result["split_counts"] == {"train": 1}
    case = result["cases"][0]
    assert case["frames"] == 3
    assert case["transitions"] == 2
    assert case["geometry_triangles"] == 10
    assert [sample["frame"] for sample in case["state_samples"]] == [0, 1, 2]
    assert all(sample["valid_true_equals_particle_count"] for sample in case["state_samples"])


def test_smoke_rejects_source_hash_drift(tmp_path):
    trajectory = tmp_path / "trajectory.h5"
    manifest = tmp_path / "manifest.json"
    _trajectory(trajectory)
    _manifest(manifest, trajectory)
    trajectory.write_bytes(trajectory.read_bytes() + b"drift")

    with pytest.raises(ValueError, match="hash mismatch|integrity"):
        run_smoke(manifest, tmp_path)


def test_smoke_rejects_nonfinite_sampled_state(tmp_path):
    trajectory = tmp_path / "trajectory.h5"
    manifest = tmp_path / "manifest.json"
    _trajectory(trajectory, nan_position=True)
    _manifest(manifest, trajectory)

    with pytest.raises(ValueError, match="finite"):
        run_smoke(manifest, tmp_path)
