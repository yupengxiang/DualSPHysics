from __future__ import annotations

import h5py
import numpy as np
import pytest

from scripts.boundary_sidecars import audit_sidecar
from scripts.r3_g2_tracer_neighbor_sensitivity import (
    DEFAULT_BASELINE,
    build_settings,
    render_conclusion_zh,
    run_case,
    validate_sidecar_against_solver,
)


def _make_solver_h5(path):
    times = np.asarray([0.0, 0.5, 1.0])
    positions0 = np.asarray([
        [0.00, 0.00, 0.00], [0.10, 0.00, 0.00],
        [0.00, 0.10, 0.00], [0.10, 0.10, 0.00],
        [0.00, 0.00, 0.10], [0.10, 0.00, 0.10],
        [0.00, 0.10, 0.10], [0.10, 0.10, 0.10],
    ])
    position = positions0[None, ...] + np.asarray([0.0, 0.01, 0.02])[:, None, None]
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=times)
        h5.create_dataset("valid", data=np.ones((3, 8), dtype=bool))
        h5.create_dataset("type", data=np.full((3, 8), 3, dtype=np.int8))
        h5.create_dataset("position", data=position)
        h5.create_dataset("velocity", data=np.full((3, 8, 3), [0.02, 0.0, 0.0]))
        h5.create_dataset("mass", data=np.ones((3, 8), dtype=np.float64))
        h5.create_dataset("mk", data=np.zeros((3, 8), dtype=np.int16))
        h5.create_dataset("particle_id", data=np.arange(8, dtype=np.int64))
        h5.create_dataset("particle_zone", data=np.zeros(8, dtype=np.int16))


def _make_sidecar(path):
    triangles = np.asarray([[
        [[10.0, 10.0, 10.0], [10.0, 11.0, 10.0], [10.0, 10.0, 11.0]],
    ]] * 3, dtype=np.float64)
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 0.5, 1.0])
        h5.create_dataset("triangles_world", data=triangles)
        h5.create_dataset("triangle_mk", data=[0])
        h5.create_dataset("triangle_type", data=np.asarray([0], dtype=np.int8))
        h5.attrs["schema_version"] = "boundary-sidecar-v1"
        h5.attrs["case_id"] = "tiny"
        h5.attrs["coordinate_frame"] = "world"


def test_default_settings_are_one_factor_at_a_time_and_include_all_knobs():
    settings = build_settings()
    assert len(settings) == 6
    assert settings[0] == DEFAULT_BASELINE
    assert {item["varied_parameter"] for item in settings[1:]} == {
        "neighbours", "regularization_over_dp", "substeps_per_interval"
    }
    assert {item["neighbours"] for item in settings} == {12, 24, 48}
    assert {item["regularization_over_dp"] for item in settings} == {0.05, 0.1, 0.2}
    assert {item["substeps_per_interval"] for item in settings} == {1, 4}


def test_full_factorial_inserts_baseline_when_axes_omit_it():
    settings = build_settings((8,), (0.2,), (2,), full_factorial=True)
    assert settings[0] == DEFAULT_BASELINE
    assert len(settings) == 2
    assert settings[1]["varied_parameter"] == "full_factorial"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"neighbours": [0]}, "neighbours"),
        ({"regularization_over_dp": [0.0]}, "regularization_over_dp"),
        ({"substeps": [0]}, "substeps"),
    ],
)
def test_setting_axes_reject_nonpositive_inputs(kwargs, message):
    with pytest.raises(ValueError, match=message):
        build_settings(**kwargs)


def test_sidecar_validation_checks_schema_case_and_time_axis(tmp_path):
    solver = tmp_path / "solver.h5"
    sidecar = tmp_path / "sidecar.h5"
    _make_solver_h5(solver)
    _make_sidecar(sidecar)
    summary = validate_sidecar_against_solver(sidecar, solver, "tiny")
    assert summary["time_matches_solver"] is True
    assert summary["all_frames_finite"] is True
    assert summary["all_frames_nondegenerate"] is True
    assert audit_sidecar(sidecar)["triangle_count"] == 1
    with h5py.File(sidecar, "r+") as h5:
        h5["time"][1] = 0.4
    with pytest.raises(ValueError, match="time axes differ"):
        validate_sidecar_against_solver(sidecar, solver, "tiny")


def test_run_case_records_wall_aware_parameter_sensitivity(tmp_path):
    solver = tmp_path / "solver.h5"
    sidecar = tmp_path / "sidecar.h5"
    _make_solver_h5(solver)
    _make_sidecar(sidecar)
    case = {"case_id": "tiny", "family": "F1", "numerics": {"particle_spacing_m": 0.1}}
    settings = build_settings((4, 8), (0.1, 0.2), (1, 4))
    report = run_case(case, solver, sidecar, settings=settings, seed_count=4)
    assert report["boundary_sidecar_audit"]["time_matches_solver"] is True
    assert [item["configuration"]["label"] for item in report["settings"]] == [
        "baseline", "neighbours_4", "neighbours_8", "regularization_0.2dp", "substeps_1"
    ]
    assert all(item["summary"]["wall_geometry_available"] for item in report["settings"])
    assert all("trajectory_delta_rmse_over_dp" in item["relative_to_baseline"]
               for item in report["settings"])


def test_conclusion_explicitly_keeps_candidate_only_status():
    report = {
        "design": {"setting_count_per_case": 6, "total_run_count": 18, "seed_count": 16,
                   "frame_stride": 1, "maximum_support_over_dp": 1.75},
        "summary": {"all_sidecars_time_aligned": True,
                    "all_sidecars_finite_and_nondegenerate": True,
                    "perturbation_count": 15,
                    "max_trajectory_delta_from_baseline_over_dp": 0.42},
    }
    conclusion = render_conclusion_zh(report)
    assert "candidate-only" in conclusion
    assert "不接受任何生产示踪配置为真值" in conclusion
    assert "0.420 dp" in conclusion
