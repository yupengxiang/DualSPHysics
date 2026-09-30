from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts.ds_data02_f3_preview import render


def test_f3_preview_renders_actual_saved_frames_without_loading_trajectory(tmp_path: Path) -> None:
    source = tmp_path / "trajectory.h5"
    metadata = {
        "physical_binding": {
            "geometry": {
                "tank": {"low_m": [-0.45, -0.09, 0.0], "size_m": [0.9, 0.18, 0.51]},
            },
        },
    }
    frames, particles = 4, 6
    with h5py.File(source, "w") as h:
        h.create_dataset("time", data=np.arange(frames, dtype=float))
        h.create_dataset("valid", data=np.ones((frames, particles), dtype=bool))
        h.create_dataset("type", data=np.asarray([[0, 0, 0, 3, 3, 3]] * frames, dtype=np.int8))
        h.create_dataset("mass", data=np.full((frames, particles), 0.5, dtype=np.float32))
        position = np.zeros((frames, particles, 3), dtype=np.float32)
        position[:, :, 0] = np.asarray([-0.4, -0.2, 0.0, 0.1, 0.2, 0.3])
        position[:, :, 1] = 0.01
        position[:, :, 2] = 0.04
        h.create_dataset("position", data=position)
        h.attrs["coordinate_frame"] = "DualSPHysics case Cartesian coordinates (x,y,z)"
    report = render(source, metadata, tmp_path / "preview.png", max_points=100)
    assert report["status"] == "actual_saved_state_png_rendered"
    assert report["frames"] == frames
    assert report["particles"] == particles
    assert report["selected_frames"] == [0, 1, 2, 3]
    assert report["fluid_counts"] == [3, 3, 3, 3]
    assert report["initial_fluid_mass_kg"] == 1.5
    assert (tmp_path / "preview.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_f3_preview_uses_recorded_conversion_hash_without_rehashing_source(tmp_path: Path) -> None:
    source = tmp_path / "trajectory.h5"
    report_path = tmp_path / "conversion-report.json"
    metadata = {"physical_binding": {"geometry": {"tank": {"low_m": [-1, -1, -1], "size_m": [2, 2, 2]}}}}
    with h5py.File(source, "w") as h:
        h.create_dataset("time", data=np.asarray([0.0, 1.0]))
        h.create_dataset("valid", data=np.ones((2, 1), dtype=bool))
        h.create_dataset("type", data=np.full((2, 1), 3, dtype=np.int8))
        h.create_dataset("mass", data=np.ones((2, 1), dtype=np.float32))
        h.create_dataset("position", data=np.zeros((2, 1, 3), dtype=np.float32))
        h.attrs["coordinate_frame"] = "frame"
    report_path.write_text(json.dumps({"output_sha256": "a" * 64}))
    result = render(source, metadata, tmp_path / "preview.png", report_path=report_path)
    assert result["source_sha256"] == "a" * 64
    assert result["source_sha256_status"] == "conversion_report_output_sha256"
