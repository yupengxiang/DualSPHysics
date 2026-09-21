import json
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts.f4_native_kernel_mls import (
    BACKEND,
    DENSE_SOURCE_H5,
    F4_H_M,
    INPUT_POLICY,
    NativeCurrentFrame,
    NativeCurrentFrameProvider,
    NativeKernelMLS,
    run_manufactured_qualification,
    sha256_file,
    trace_native_material,
    wendland_normalisation_3d,
    wendland_quintic_c2_3d,
    write_dense_canary_spec,
)


def _small_frame():
    axes = np.linspace(-0.04, 0.04, 5)
    position = np.stack(np.meshgrid(axes, axes, axes, indexing="ij"), axis=-1).reshape(-1, 3)
    velocity = np.column_stack((position[:, 0], 2.0 * position[:, 1], -position[:, 2]))
    return NativeCurrentFrame(
        position,
        velocity,
        np.full(len(position), 1.0e-3),
        np.full(len(position), 1000.0),
    )


def test_wendland_formula_and_official_f4_normalisation():
    # DualSPHysics' official F4 Run.out prints awen=245355.2 for the rounded
    # h=0.011941.  The exact 3-D normalisation is the same value to run-file
    # precision; the integral check guards against a missing h^-3 factor.
    assert wendland_normalisation_3d(0.011941) == pytest.approx(245355.2, rel=1e-4)
    h = 0.07
    radius = np.linspace(0.0, 2.0 * h, 200001)
    integral = np.trapezoid(4.0 * np.pi * radius**2 * wendland_quintic_c2_3d(radius, h), radius)
    assert integral == pytest.approx(1.0, rel=2e-7)
    assert wendland_quintic_c2_3d(np.array([2.0 * h, 2.01 * h]), h)[1] == 0.0


def test_current_frame_is_immutable_and_backend_is_volume_weighted():
    frame = _small_frame()
    with pytest.raises(ValueError):
        frame.position[0, 0] = 3.0
    query = np.array([[0.0, 0.0, 0.0]])
    result = NativeKernelMLS(0.045).reconstruct(query, frame)
    assert result.reliable.tolist() == [True]
    np.testing.assert_allclose(result.velocity, [[0.0, 0.0, 0.0]], atol=1e-12)
    assert result.diagnostics["support_count"][0] > 4
    assert result.diagnostics["weight_sum"][0] > 0.0
    assert result.diagnostics["support_volume_sum_m3"][0] > 0.0
    assert result.diagnostics["failure_reason"].tolist() == ["reliable"]


def test_provider_requires_native_current_density_and_has_no_future_api(tmp_path):
    path = tmp_path / "native.h5"
    points = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.0, 0.01, 0.0], [0.0, 0.0, 0.01]])
    with h5py.File(path, "w") as handle:
        handle["time"] = [0.0, 0.1]
        handle["position"] = np.stack((points, points + 0.001))
        handle["velocity"] = np.stack((np.zeros_like(points), np.ones_like(points)))
        handle["mass"] = np.full((2, len(points)), 1.0e-3)
        handle["density"] = np.full((2, len(points)), 1000.0)
        handle["valid"] = np.ones((2, len(points)), dtype=bool)
        handle["type"] = np.full((2, len(points)), 3, dtype=np.int32)
    provider = NativeCurrentFrameProvider(path, fluid_type=3)
    frame = provider.read_current(0)
    assert frame.frame_index == 0
    assert frame.time_s == 0.0
    assert frame.source_sha256 == sha256_file(path)
    assert not hasattr(provider, "future")
    assert not hasattr(frame, "future")
    with h5py.File(path, "r+") as handle:
        del handle["density"]
    with pytest.raises(ValueError, match="density"):
        NativeCurrentFrameProvider(path, fluid_type=3).read_current(0)


def test_manufactured_qualification_covers_geometry_and_mass(tmp_path):
    result = run_manufactured_qualification(tmp_path / "manufactured.json")
    assert result["backend"] == BACKEND
    assert result["qualification_claim"] == "none"
    assert result["all_cases_passed"] is True
    assert result["mass_closure_abs_error_max"] == 0.0
    rows = {row["id"]: row for row in result["cases"]}
    assert rows["constant_interior"]["unknown_fraction"] == 0.0
    assert rows["affine_interior"]["unknown_fraction"] == 0.0
    assert rows["wall_two_sides"]["wall_rejected_total"] > 0
    assert rows["wall_opening"]["cross_side_visible_count"] > 0
    assert rows["separated_liquid_clouds"]["unknown_fraction"] == pytest.approx(1.0 / 3.0)
    assert rows["near_separated_velocity_branches"]["connectivity_component_count_max"] == 2
    assert rows["near_separated_velocity_branches"]["velocity_branch_separation_max_mps"] == pytest.approx(0.6)
    assert rows["support_rank_deficient"]["reason_counts"]["rank_deficient"] == 1
    assert rows["support_empty"]["reason_counts"]["no_support"] == 1
    assert rows["quadratic_nonaffine_interior"]["error_budget"]["bound_applicable"] is True
    assert rows["quadratic_nonaffine_interior"]["error_budget"]["true_error_within_upper_bound"] is True
    assert rows["near_separated_velocity_branches"]["error_budget"]["lower_bound_p95_mps"] == pytest.approx(0.3)
    saved = json.loads((tmp_path / "manufactured.json").read_text())
    assert saved["code_sha256"] == result["code_sha256"]
    assert saved["input_policy"] == INPUT_POLICY


def test_dense_spec_is_frozen_and_cpu_only(tmp_path):
    if not DENSE_SOURCE_H5.exists():
        pytest.skip("dense F4 source is not present in this checkout")
    output = tmp_path / "spec.json"
    spec = write_dense_canary_spec(output)
    assert spec["source_sha256"] == sha256_file(DENSE_SOURCE_H5)
    assert spec["h_m"] == F4_H_M
    assert spec["source_time_policy"]["frame_indices"] == [0, 80, 81, 82, 150]
    assert spec["resource_estimate"]["gpu"] is False
    assert spec["resource_estimate"]["ledger"] is False
    assert spec["qualification_claim"] == "none"
    argv = spec["argv"]
    assert "--dense-output" in argv
    assert "--frame-indices" in argv
    assert json.loads(output.read_text())["code_sha256"] == spec["code_sha256"]


def _write_trace_source(path, *, frames=5, invalidate_frame_one=False, velocity=(0.0, 0.0, 0.01)):
    axes_x = np.arange(0.30, 0.681, 0.03)
    axes_y = np.arange(0.08, 0.321, 0.03)
    axes_z = np.arange(0.24, 0.701, 0.03)
    points = np.stack(np.meshgrid(axes_x, axes_y, axes_z, indexing="ij"), axis=-1).reshape(-1, 3)
    values = np.broadcast_to(np.asarray(velocity, dtype=np.float64), points.shape).copy()
    with h5py.File(path, "w") as handle:
        handle["time"] = np.arange(frames, dtype=np.float64) * 0.05
        handle["position"] = np.broadcast_to(points, (frames, len(points), 3)).copy()
        handle["velocity"] = np.broadcast_to(values, (frames, len(points), 3)).copy()
        handle["mass"] = np.full((frames, len(points)), 1.0e-3, dtype=np.float64)
        density = np.full((frames, len(points)), 1000.0, dtype=np.float64)
        if invalidate_frame_one:
            density[1] = 0.0
        handle["density"] = density
        handle["valid"] = np.ones((frames, len(points)), dtype=bool)
        handle["type"] = np.full((frames, len(points)), 3, dtype=np.int16)


def test_trace_is_causal_and_emits_budget_mass_and_events(tmp_path):
    source = tmp_path / "source.h5"
    _write_trace_source(source, frames=3, invalidate_frame_one=True)
    output = tmp_path / "trace.h5"
    result = trace_native_material(
        source, output, h=0.09, query_count=8, substeps=2, stop_after=1,
    )
    assert result["committed_frame"] == 1
    assert result["mass_closed"] is True
    assert result["material_reliability_status"].startswith("not_assessed")
    assert result["by_source"][0]["unknown_fraction"] == 0.0
    assert result["by_source"][0]["error_budget"]["analytic_upper_bound_available"] is False
    with h5py.File(output, "r") as handle:
        assert handle.attrs["trace_backend"] == "f4_native_kernel_mls_causal_current_volume_rk4_v1"
        assert handle["time"].shape[0] == 2
        assert np.all(handle["reliable"][1])
        assert np.allclose(handle["position"][1, :, 2], handle["position"][0, :, 2] + 0.0005, atol=1e-12)
        assert handle["mass_closure_error"][1] == pytest.approx(0.0)


def test_trace_event_tracker_records_continuous_crossing():
    from scripts.f4_native_kernel_mls import NativeMaterialEventTracker

    tracker = NativeMaterialEventTracker(1)
    state = tracker.initial_state()
    tracker.advance(
        state,
        np.array([[0.0, 0.0, 0.20]]), np.array([[0.0, 0.0, 0.10]]),
        np.array([[0.0, 0.0, -1.0]]), np.array([[0.0, 0.0, -1.0]]),
        0.0, 0.2, np.array([True]),
    )
    assert state["contacted"].tolist() == [True]
    assert state["contact_time"][0] == pytest.approx(0.04)
    assert state["residence_s"][0] == pytest.approx(0.16)
    tracker.advance(
        state,
        np.array([[0.0, 0.0, 0.10]]), np.array([[0.0, 0.0, 0.20]]),
        np.array([[0.0, 0.0, 1.0]]), np.array([[0.0, 0.0, 1.0]]),
        0.2, 0.2, np.array([True]),
    )
    assert state["upward"].tolist() == [True]
    assert state["upward_time"][0] == pytest.approx(0.36)


def test_trace_sigkill_resume_reconstructs_same_history(tmp_path):
    source = tmp_path / "source.h5"
    _write_trace_source(source, frames=5)
    killed = tmp_path / "killed.h5"
    complete = tmp_path / "complete.h5"
    command = [
        sys.executable, "-m", "scripts.f4_native_kernel_mls", "--trace-output", str(killed),
        "--source", str(source), "--h", "0.09", "--query-count", "8", "--substeps", "2",
        "--stop-after", "4", "--kill-after", "1",
    ]
    process = subprocess.run(command, cwd=Path(__file__).parents[1], capture_output=True, text=True)
    assert process.returncode < 0
    resume = subprocess.run(
        command[:-2] + ["--resume"], cwd=Path(__file__).parents[1], capture_output=True, text=True,
    )
    assert resume.returncode == 0, resume.stderr
    trace_native_material(source, complete, h=0.09, query_count=8, substeps=2, stop_after=4)
    with h5py.File(killed, "r") as left, h5py.File(complete, "r") as right:
        assert left.attrs["committed"] == right.attrs["committed"] == 4
        for name in ("time", "position", "reliable", "permanent_unknown", "destination_member",
                     "contact_time", "upward_time", "return_time", "residence_s", "contacted",
                     "upward", "returned", "event_status", "residual_estimate_mps",
                     "error_upper_bound_mps", "path_error_estimate_m", "path_error_budget_m",
                     "mass_closure_error"):
            np.testing.assert_allclose(left[name][:], right[name][:], equal_nan=True)


def test_trace_manifest_generation_fault_keeps_previous_checkpoint(tmp_path):
    source = tmp_path / "source.h5"
    _write_trace_source(source, frames=5)
    killed = tmp_path / "generation-fault.h5"
    complete = tmp_path / "generation-complete.h5"
    command = [
        sys.executable, "-m", "scripts.f4_native_kernel_mls", "--trace-output", str(killed),
        "--source", str(source), "--h", "0.09", "--query-count", "8", "--substeps", "2",
        "--stop-after", "4", "--kill-after-checkpoint-publish", "1",
    ]
    process = subprocess.run(command, cwd=Path(__file__).parents[1], capture_output=True, text=True)
    assert process.returncode < 0
    manifest_path = Path(str(killed) + ".checkpoint.json")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["committed_frame"] == 0
    old_generation = Path(manifest["checkpoint_npz"])
    assert old_generation.exists()
    published_generations = list(tmp_path.glob("generation-fault.h5.checkpoint.*.npz"))
    assert len(published_generations) >= 2
    assert all(path.exists() for path in published_generations)
    resume = subprocess.run(
        command[:-2] + ["--resume"], cwd=Path(__file__).parents[1], capture_output=True, text=True,
    )
    assert resume.returncode == 0, resume.stderr
    trace_native_material(source, complete, h=0.09, query_count=8, substeps=2, stop_after=4)
    with h5py.File(killed, "r") as left, h5py.File(complete, "r") as right:
        for name in ("time", "position", "reliable", "permanent_unknown", "destination_member",
                     "contact_time", "upward_time", "return_time", "residence_s", "contacted",
                     "upward", "returned", "event_status", "residual_estimate_mps",
                     "error_upper_bound_mps", "path_error_estimate_m", "path_error_budget_m",
                     "mass_closure_error"):
            np.testing.assert_allclose(left[name][:], right[name][:], equal_nan=True)
