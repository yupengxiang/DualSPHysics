"""Static/CPU-only contract tests for the prospective material calibration."""

import h5py
import numpy as np

from scripts import f3_material_calibration_v2 as calibration
from scripts import f3_material_neighbors


def test_design_has_four_fixed_cases_and_physical_seeds():
    design = calibration.calibration_design()
    assert design["seeds"] == 64
    assert design["substeps"] == 2
    assert design["time_window_s"] == [0., .5]
    assert design["same_physical_seeds_across_resolutions"] is True
    assert np.asarray(design["seed_positions_m"]).shape == (64, 3)
    assert len(calibration.CONFIGURATIONS) == 4
    assert {(row["flow"], row["dp_m"]) for row in calibration.CONFIGURATIONS} == {
        ("shear", .01), ("shear", .006), ("rotation", .01), ("rotation", .006)
    }


def test_manufactured_trace_injects_prospective_backend(tmp_path, monkeypatch):
    times = np.linspace(0., .02, 3)
    points = np.asarray([[-.02, -.01, .03], [.01, .01, .04], [.02, -.02, .05]])
    path = tmp_path / "source.h5"
    with h5py.File(path, "w") as h5:
        h5["time"] = times
        h5["position"] = np.broadcast_to(points, (len(times), len(points), 3))
        h5["velocity"] = np.zeros((len(times), len(points), 3))
        h5["valid"] = np.ones((len(times), len(points)), bool)
        h5["type"] = np.full((len(times), len(points)), 3, np.int8)

    captured = {}

    def fake_advect(source, seeds, **kwargs):
        captured.update(kwargs)
        return {"position": np.zeros((3, len(seeds), 3))}

    monkeypatch.setattr(calibration, "advect_hdf5", fake_advect)
    calibration.manufactured_trace(path, calibration.seed_positions(), np.empty((0, 3, 3)))
    assert captured["velocity_interpolator"] is f3_material_neighbors.shepard_velocity_with_diagnostics
    assert captured["substeps_per_interval"] == 2
    assert captured["maximum_support_distance"] == .03
