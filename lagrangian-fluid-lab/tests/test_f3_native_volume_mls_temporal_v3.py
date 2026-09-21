"""Analytic and recovery checks for the independent temporal F3 backend."""

import hashlib
import json
from collections import Counter
from pathlib import Path
import subprocess
import sys

import h5py
import numpy as np
import pytest

from scripts.f3_native_volume_mls_temporal_v3 import (
    F3NativeVolumeMLS,
    F3ReferenceProvider,
    F3CurrentFrame,
    MLSResult,
    _advance_rk4,
    audit_source,
    _new_state,
    _selection_hash,
)


def _source(tmp_path: Path, *, invalid_frame: int | None = None) -> Path:
    path = tmp_path / "temporal.h5"
    times = np.array([0.0, 1.0, 2.0], dtype=np.float64)
    base = np.asarray(
        [[x, y, z] for x in (-0.01, 0.0, 0.01)
         for y in (-0.01, 0.0, 0.01)
         for z in (-0.01, 0.0, 0.01)],
        dtype=np.float64,
    )
    frames, particles = len(times), len(base)
    position = np.empty((frames, particles, 3), dtype=np.float32)
    velocity = np.empty_like(position)
    for index, time_s in enumerate(times):
        # A moving support cloud with an analytic, time-linear field.
        position[index] = base + np.array([0.004 * time_s, -0.002 * time_s,
                                            0.001 * time_s], dtype=np.float64)
        velocity[index, :, 0] = 1.0 + 2.0 * time_s
        velocity[index, :, 1] = -0.5 + 0.25 * time_s
        velocity[index, :, 2] = 0.3
    valid = np.ones((frames, particles), dtype=np.uint8)
    if invalid_frame is not None:
        valid[int(invalid_frame), 0] = 0
    with h5py.File(path, "w") as handle:
        handle["time"] = times
        handle["position"] = position
        handle["velocity"] = velocity
        handle["mass"] = np.full((frames, particles), 1.0e-3, dtype=np.float32)
        handle["density"] = np.full((frames, particles), 1000.0, dtype=np.float32)
        handle["valid"] = valid
        handle["type"] = np.full((frames, particles), 3, dtype=np.int8)
    return path


def _selection(source: Path, tmp_path: Path) -> Path:
    indices = np.array([0, 1, 2], dtype=np.int64)
    value = {
        "schema": "core.material.f3.native_volume_mls.frame_selection.v1",
        "selection_id": "temporal-test-all",
        "selection_mode": "direct_native_endpoint_frames",
        "source_h5": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_frame_count": 3,
        "source_native_saved_interval_s": 1.0,
        "target_nominal_interval_s": 1.0,
        "target_time_tolerance_s": 1.0e-12,
        "logical_frame_count": 3,
        "source_frame_indices": indices.tolist(),
        "selection_sha256": _selection_hash(indices),
        "interpolation": False,
        "qualification_claim": "none",
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(value))
    return path


def _prepared(tmp_path: Path) -> Path:
    path = tmp_path / "prepared.json"
    xml = (Path(__file__).parents[1]
           / "campaigns/l1-resume/artifacts/cell3-nopen-qualification"
           / "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen"
           / "F3_CELL3_plain_0p0075_Def.xml")
    path.write_text(json.dumps({
        "dp_m": 0.0075,
        "candidate_definition": str(xml),
        "case_id": "temporal-test",
        "recipe_id": "test",
        "qualified": False,
        "formal_release": False,
        "wall_spec": {},
    }))
    return path


def test_temporal_field_is_exact_at_midpoint_and_rejects_outside_interval(tmp_path):
    source = _source(tmp_path)
    selection = _selection(source, tmp_path)
    with F3ReferenceProvider(source, frame_index_map=selection) as provider:
        midpoint = provider.field_at(0, 0.5)
        assert np.allclose(midpoint.position[:, 0],
                           (provider.frame(0).position[:, 0] + provider.frame(1).position[:, 0]) / 2.0)
        assert np.allclose(midpoint.velocity[:, 0], 2.0)
        assert np.allclose(midpoint.velocity[:, 1], -0.375)
        assert np.array_equal(midpoint.native_indices, np.arange(27))
        assert provider.field_at(0, 1.0).frame_index == provider.frame(1).frame_index
        assert np.allclose(provider.field_at(1, 1.5).velocity[:, 0], 4.0)
        with pytest.raises(ValueError, match="outside registered interval"):
            provider.field_at(0, 1.0 + 1.0e-6)


def test_temporal_provider_rejects_a_changing_native_support_mask(tmp_path):
    source = _source(tmp_path, invalid_frame=1)
    with F3ReferenceProvider(source) as provider:
        with pytest.raises(ValueError, match="identical valid fluid native rows"):
            provider.endpoint_pair(0)


def test_temporal_audit_binds_interpolation_and_reference_only_source(tmp_path):
    source = _source(tmp_path)
    report = audit_source(source, _prepared(tmp_path))
    assert report["schema"].endswith("source_preflight.temporal.v3")
    assert report["source"]["interpolation"] is True
    assert report["source"]["interpolation_scope"] == "current_interval_endpoints_only"
    assert report["candidate_binding"]["model_source"] == "forbidden; registered reference source H5 only"
    assert report["candidate_binding"]["native_volume"].startswith("linearly interpolated")


def test_mls_reconstructs_analytic_time_linear_velocity_on_moving_support(tmp_path):
    source = _source(tmp_path)
    with F3ReferenceProvider(source) as provider:
        field = provider.field_at(0, 0.5)
        result = F3NativeVolumeMLS(0.02).reconstruct(
            np.array([[0.0, 0.0, 0.0]], dtype=np.float64),
            field,
            np.empty((0, 3, 3), dtype=np.float64),
        )
        assert bool(result.reliable[0])
        assert np.allclose(result.velocity[0], [2.0, -0.375, 0.3], atol=1.0e-12)
        assert result.support_count[0] == 27


class _UniformTracer:
    """Minimal analytic tracer for testing RK stage time requests."""

    def reconstruct(self, query, frame, walls):
        query = np.asarray(query, dtype=np.float64)
        velocity = np.repeat(frame.velocity[:1], len(query), axis=0)
        count = len(query)
        return MLSResult(
            velocity,
            np.full(count, len(frame.position), dtype=np.int64),
            np.full(count, len(frame.position), dtype=np.int64),
            np.zeros(count, dtype=np.int64),
            np.full(count, 10.0, dtype=np.float64),
            np.full(count, 4, dtype=np.int8),
            np.full(count, 2.0, dtype=np.float64),
            np.full(count, 0.5, dtype=np.float64),
            np.zeros(count, dtype=np.float64),
            np.ones(count, dtype=bool),
            np.ones(count, dtype=bool),
            np.ones(count, dtype=bool),
            np.full(count, "reliable", dtype=object),
        )


def test_rk4_uses_linear_temporal_field_and_integrates_the_analytic_velocity(tmp_path):
    source = _source(tmp_path)
    state = _new_state(np.array([[1.0, 0.0, 0.0]], dtype=np.float64), np.array([1], dtype=np.int8))
    state["reliable"][:] = True
    state["failure_reason"] = np.full(1, "reliable", dtype=object)
    diagnostics = {"stage_failure_counts": Counter()}
    with F3ReferenceProvider(source) as provider:
        _advance_rk4(
            state, _UniformTracer(), provider, np.empty((0, 3, 3), dtype=np.float64),
            0, 0.0, 1.0, diagnostics,
        )
    # u_x(t)=1+2t, so integral_0^1 u_x dt=2.
    assert np.allclose(state["position"], [[3.0, -0.375, 0.3]], atol=1.0e-12)
    assert bool(state["reliable"][0])


def test_generation_fault_resume_matches_continuous_trace(tmp_path):
    """A SIGKILL after NPZ publication leaves the old manifest resumable."""
    source = _source(tmp_path)
    prepared = _prepared(tmp_path)
    script = Path(__file__).parents[1] / "scripts/f3_native_volume_mls_temporal_v3.py"
    killed = tmp_path / "killed.h5"
    continuous = tmp_path / "continuous.h5"
    common = [
        sys.executable, "-m", "scripts.f3_native_volume_mls_temporal_v3",
        "--source", str(source), "--prepared", str(prepared),
        "--seeds", "512", "--substeps", "2", "--stop-after", "2",
    ]
    fault = subprocess.run(
        common + ["--output", str(killed), "--kill-after-generation", "1"],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
    )
    assert fault.returncode in {-9, 137}, fault.stderr
    manifest = json.loads(Path(str(killed) + ".checkpoint.json").read_text())
    assert manifest["committed_frame"] == 0
    assert len(list(tmp_path.glob("killed.h5.checkpoint.*.npz"))) >= 2
    resumed = subprocess.run(
        common + ["--output", str(killed), "--resume"],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
    )
    assert resumed.returncode == 0, resumed.stderr
    complete = subprocess.run(
        common + ["--output", str(continuous)],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
    )
    assert complete.returncode == 0, complete.stderr
    with h5py.File(killed, "r") as left, h5py.File(continuous, "r") as right:
        assert int(left.attrs["committed"]) == int(right.attrs["committed"]) == 2
        for name in ("time", "position", "reliable", "permanent_unknown", "first_passage",
                     "return_time", "residence_opposite", "returned", "support_count",
                     "effective_sample_size", "geometry_rank", "condition_number",
                     "anisotropy", "reconstruction_error_mps", "old_gate_pass",
                     "candidate_support_pass", "candidate_count", "wall_rejected_count",
                     "native_mass_kg", "seed_mass_closure_error", "failure_reason"):
            left_value, right_value = left[name][:], right[name][:]
            equal = np.array_equal(left_value, right_value)
            if not equal and left_value.dtype.kind not in "OUS" and right_value.dtype.kind not in "OUS":
                equal = np.array_equal(left_value, right_value, equal_nan=True)
            assert equal, name
