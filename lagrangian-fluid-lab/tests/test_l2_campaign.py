from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts import l2_campaign
from scripts.l2_reader import case_metadata, load_manifest, read_frame


def test_hdf5_inspection_rejects_missing_and_accepts_minimal(tmp_path: Path):
    missing = l2_campaign.inspect_hdf5(tmp_path / "missing.h5")
    assert missing["structural_pass"] is False
    path = tmp_path / "case.h5"
    with h5py.File(path, "w") as handle:
        handle["time"] = np.array([0.0, 0.1])
        handle["position"] = np.zeros((2, 2, 3), dtype=np.float32)
        handle["velocity"] = np.zeros((2, 2, 3), dtype=np.float32)
        handle["mass"] = np.ones((2, 2), dtype=np.float32)
        handle["particle_id"] = np.array([1, 2], dtype=np.uint32)
        handle["valid"] = np.ones((2, 2), dtype=bool)
    report = l2_campaign.inspect_hdf5(path, full_scan=True, wall_bounds=l2_campaign.F3_WALL_BOUNDS)
    assert report["structural_pass"] is True
    assert report["frame_count"] == 2
    assert report["particle_count"] == 2


def test_reader_resolves_case_and_frame(tmp_path: Path):
    lab_root = tmp_path / "lab"
    data = lab_root / "data"
    data.mkdir(parents=True)
    path = data / "toy.h5"
    with h5py.File(path, "w") as handle:
        handle["time"] = np.array([0.0, 0.1])
        handle["position"] = np.arange(12, dtype=np.float32).reshape(2, 2, 3)
        handle["velocity"] = np.ones((2, 2, 3), dtype=np.float32)
        handle["valid"] = np.ones((2, 2), dtype=bool)
        handle["particle_id"] = np.array([3, 4], dtype=np.uint32)
    manifest_path = lab_root / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema": "l2.f3.canonical_manifest.v1",
        "repository_root": str(lab_root),
        "cases": [{"case_id": "toy", "hdf5": "data/toy.h5", "sha256": "x"}],
    }))
    manifest = load_manifest(manifest_path)
    frame = read_frame(manifest, "toy", 1, fields=("position", "valid"))
    assert frame["time"] == 0.1
    assert frame["position"].shape == (2, 3)
    assert frame["valid"].all()
    assert case_metadata(manifest, "toy")["datasets"]["position"] == [2, 2, 3]


def test_failure_summary_separates_wall_and_runtime():
    record = l2_campaign.summarize_replay_case("run", "route", 1, {
        "case_id": "case",
        "status": "failed",
        "expected_frames": 10,
        "saved_frames": 8,
        "hard_wall_passed": False,
        "first_failure": {"kind": "hard_wall_or_crossing", "time_s": 0.2,
                           "first_crossing": {"kind": "closed_face", "face": "left"}},
        "terminal_failure": {"kind": "runtime_or_nonfinite_failure"},
        "metrics_mean": {"unmatched_support_mass": 0.5},
    })
    assert record["rollout_complete"] is False
    assert record["first_crossing_face"] == "left"
    assert record["finite_failure_observed"] is True
    assert record["unmatched_support_mass_fraction"] == 0.5
