"""CPU contract tests for the preregistered F4 cadence pair."""

import json
from pathlib import Path

import h5py
import numpy as np

from scripts import f4_tallwall120_frame_stride_view as stride_view


def _small_source(path: Path) -> None:
    frames, particles = 5, 3
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=np.arange(frames, dtype=np.float64) * 0.004)
        h5.create_dataset("position", data=np.arange(frames * particles * 3, dtype=np.float64).reshape(frames, particles, 3))
        h5.create_dataset("velocity", data=np.ones((frames, particles, 3), dtype=np.float32))
        h5.create_dataset("valid", data=np.ones((frames, particles), dtype=bool))
        h5.create_dataset("type", data=np.full((frames, particles), 3, dtype=np.int16))
        h5.create_dataset("particle_id", data=np.arange(particles, dtype=np.uint32))


def test_stride_view_copies_exact_rows_without_interpolation(tmp_path):
    source = tmp_path / "source.h5"
    output = tmp_path / "view.h5"
    _small_source(source)

    record = stride_view.build_view(source, output, stride=2)

    assert record["view"]["exact_rows_no_interpolation"] is True
    assert record["view"]["source_frame_indices"] == [0, 2, 4]
    with h5py.File(source, "r") as src, h5py.File(output, "r") as view:
        np.testing.assert_array_equal(view["time"][:], src["time"][::2])
        np.testing.assert_array_equal(view["position"][:], src["position"][::2])
        np.testing.assert_array_equal(view["velocity"][:], src["velocity"][::2])
        np.testing.assert_array_equal(view["valid"][:], src["valid"][::2])
        np.testing.assert_array_equal(view["view_source_frame_index"][:], [0, 2, 4])
        assert view.attrs["view_stride"] == 2
        assert bool(view.attrs["view_exact_rows_no_interpolation"]) is True


def test_cadence_jobs_hold_material_step_scale_and_bind_view():
    root = Path(__file__).resolve().parents[1]
    dense = json.loads((root / "campaigns/core-v1/material/jobs/core-f4-tallwall120-material-cadence-native004-s2-canary-v1.json").read_text())
    view = json.loads((root / "campaigns/core-v1/material/jobs/core-f4-tallwall120-material-cadence-stride5-s10-canary-v1.json").read_text())

    assert dense["study_id"] == view["study_id"]
    assert dense["qualification_only"] is True
    assert view["qualification_only"] is True
    assert dense["qualification_claim"] == view["qualification_claim"] == "none"
    assert dense["central_ledger_mutation"] == view["central_ledger_mutation"] == 0
    assert dense["gpu_started"] is False and view["gpu_started"] is False
    assert dense["argv"][-4:] == ["--substeps", "2", "--stop-after", "100"]
    assert view["argv"][-4:] == ["--substeps", "10", "--stop-after", "20"]
    assert dense["event_window"]["requested_window_s"] == view["event_window"]["requested_window_s"]
    assert view["source"]["reference"]["frame_stride_view"] is True
    assert view["source"]["reference"]["parent_source_sha256"] == dense["source"]["reference"]["sha256"]
    assert dense["backend"]["support_gate"] == view["backend"]["support_gate"]
