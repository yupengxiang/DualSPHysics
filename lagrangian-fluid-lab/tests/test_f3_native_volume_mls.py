"""CPU unit tests for the independent F3 native-volume MLS candidate."""

import h5py
import numpy as np
import json
from collections import Counter
from pathlib import Path
import subprocess
import sys

from scripts.f3_native_volume_mls import (
    F3CurrentFrame,
    F3NativeVolumeMLS,
    F3ReferenceProvider,
    _advance_rk4,
    _new_state,
    f3_walls,
    seeds_f3,
    source_labels,
    wendland_quintic_c2_3d,
)


def _affine_frame():
    axis = np.linspace(-0.12, 0.12, 7)
    position = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1).reshape(-1, 3)
    x, y, z = position.T
    velocity = np.column_stack((1.0 + 2.0 * x - y + 0.5 * z,
                                -0.25 + x + 3.0 * y - 2.0 * z,
                                0.75 - 2.0 * x + 0.25 * y + 4.0 * z))
    mass = np.full(len(position), 1.0e-3)
    density = np.full(len(position), 1000.0)
    return F3CurrentFrame(position, velocity, mass, density,
                          np.ones(len(position), dtype=bool), frame_index=0, time_s=0.0)


def test_wendland_is_compact_and_positive():
    values = wendland_quintic_c2_3d(np.array([0.0, 0.5, 2.0, 2.01]), 1.0)
    assert values[0] > values[1] > 0.0
    assert values[2] == 0.0
    assert values[3] == 0.0


def test_native_volume_affine_mls_reconstructs_affine_field():
    frame = _affine_frame()
    backend = F3NativeVolumeMLS(0.14)
    query = np.array([[0.013, -0.021, 0.017], [-0.04, 0.03, -0.02]])
    result = backend.reconstruct(query, frame, np.empty((0, 3, 3), dtype=np.float64))
    x, y, z = query.T
    expected = np.column_stack((1.0 + 2.0 * x - y + 0.5 * z,
                                -0.25 + x + 3.0 * y - 2.0 * z,
                                0.75 - 2.0 * x + 0.25 * y + 4.0 * z))
    assert result.reliable.all()
    assert np.allclose(result.velocity, expected, atol=1e-12, rtol=0.0)
    assert np.max(result.reconstruction_error_mps) < 1e-12
    assert np.all(result.geometry_rank == 4)


def test_rk4_censors_outward_intermediate_stage_at_closed_wall():
    axes = [
        np.array([0.41, 0.42, 0.43, 0.44, 0.4475]),
        np.array([-0.02, 0.0, 0.02]),
        np.array([0.08, 0.10, 0.12]),
    ]
    position = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    velocity = np.tile([1.0, 0.0, 0.0], (len(position), 1))
    frame = F3CurrentFrame(
        position,
        velocity,
        np.full(len(position), 1.0e-3),
        np.full(len(position), 1000.0),
        np.ones(len(position), dtype=bool),
        frame_index=0,
        time_s=0.0,
    )
    tracer = F3NativeVolumeMLS(0.02)
    query = np.asarray([[0.449, 0.0, 0.10]])
    assert tracer.reconstruct(query, frame, f3_walls()).reliable.all()

    state = _new_state(query, np.asarray([1], dtype=np.int8))
    state["reliable"][:] = True
    state["failure_reason"] = np.asarray(["reliable"], dtype=object)
    diagnostics = {"stage_failure_counts": Counter()}
    _advance_rk4(state, tracer, frame, f3_walls(), 0.0, 0.004, diagnostics)

    assert not state["reliable"][0]
    assert state["permanent_unknown"][0]
    assert state["failure_reason"][0] == "wall_occluded"
    np.testing.assert_array_equal(state["position"], query)
    assert diagnostics["stage_failure_counts"]["wall_occluded"] == 2


def test_seed_identity_is_geometric_and_source_balanced():
    seeds = seeds_f3(512)
    labels = source_labels(seeds)
    assert len(np.unique(seeds, axis=0)) == 512
    assert np.count_nonzero(labels == 0) == 256
    assert np.count_nonzero(labels == 1) == 256


def test_provider_exposes_only_requested_current_native_frame(tmp_path):
    path = tmp_path / "source.h5"
    position = np.array([[[0.0, 0.0, 0.05], [0.1, 0.0, 0.05],
                         [0.0, 0.1, 0.05], [0.0, 0.0, 0.15]],
                        [[0.01, 0.0, 0.05], [0.11, 0.0, 0.05],
                         [0.01, 0.1, 0.05], [0.01, 0.0, 0.15]]])
    velocity = np.zeros_like(position)
    velocity[1, :, 0] = 9.0
    mass = np.full((2, 4), 1.0e-3)
    density = np.full((2, 4), 1000.0)
    valid = np.ones((2, 4), dtype=bool)
    particle_type = np.full((2, 4), 3, dtype=np.int8)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("time", data=[0.0, 0.01])
        for name, data in (("position", position), ("velocity", velocity),
                           ("mass", mass), ("density", density),
                           ("valid", valid), ("type", particle_type)):
            handle.create_dataset(name, data=data)
    with F3ReferenceProvider(path, max_cache=1) as provider:
        current = provider.frame(0)
        assert provider.loaded_indices == [0]
        assert current.frame_index == 0
        assert np.all(current.velocity == 0.0)
        assert not hasattr(current, "provider")
        later = provider.frame(1)
        assert provider.loaded_indices == [0, 1]
        assert later.frame_index == 1
        assert np.all(later.velocity[:, 0] == 9.0)


def test_checkpoint_generation_faults_resume_to_continuous_trace(tmp_path):
    source = tmp_path / "source.h5"
    position = np.repeat(
        np.array([[[0.0, 0.0, 0.05], [0.01, 0.0, 0.05],
                  [0.0, 0.01, 0.05], [0.0, 0.0, 0.06]]], dtype=np.float32),
        3, axis=0,
    )
    with h5py.File(source, "w") as handle:
        handle["time"] = np.array([0.0, 0.01, 0.02])
        handle["position"] = position
        handle["velocity"] = np.zeros_like(position)
        handle["mass"] = np.full((3, 4), 1.0e-3, dtype=np.float32)
        handle["density"] = np.full((3, 4), 1000.0, dtype=np.float32)
        handle["valid"] = np.ones((3, 4), dtype=np.uint8)
        handle["type"] = np.full((3, 4), 3, dtype=np.int8)
    xml = (Path(__file__).parents[1]
           / "campaigns/l1-resume/artifacts/cell3-nopen-qualification"
           / "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen"
           / "F3_CELL3_plain_0p0075_Def.xml")
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps({
        "dp_m": 0.0075,
        "candidate_definition": str(xml),
        "case_id": "synthetic-checkpoint",
        "recipe_id": "test",
        "qualified": False,
        "formal_release": False,
        "wall_spec": {},
    }))
    interrupted = tmp_path / "interrupted.h5"
    command = [sys.executable, "-m", "scripts.f3_native_volume_mls",
               "--source", str(source), "--prepared", str(prepared),
               "--output", str(interrupted), "--stop-after", "2"]
    fault = subprocess.run(command + ["--kill-after-generation", "1"],
                           cwd=Path(__file__).parents[1], check=False)
    assert fault.returncode == -9
    manifest = json.loads(Path(str(interrupted) + ".checkpoint.json").read_text())
    assert manifest["committed_frame"] == 0
    with h5py.File(interrupted, "r") as handle:
        assert int(handle.attrs["committed"]) == 1
    subprocess.run(command + ["--resume"], cwd=Path(__file__).parents[1], check=True)
    continuous = tmp_path / "continuous.h5"
    subprocess.run(command[:command.index("--output")] + ["--output", str(continuous),
                   "--stop-after", "2"], cwd=Path(__file__).parents[1], check=True)
    with h5py.File(interrupted, "r") as resumed, h5py.File(continuous, "r") as clean:
        for name in ("time", "position", "reliable", "permanent_unknown",
                     "first_passage", "return_time", "residence_opposite", "returned",
                     "support_count", "effective_sample_size", "geometry_rank",
                     "condition_number", "anisotropy", "reconstruction_error_mps",
                     "old_gate_pass", "candidate_support_pass", "candidate_count",
                     "wall_rejected_count", "native_mass_kg", "seed_mass_closure_error"):
            assert np.allclose(resumed[name][:], clean[name][:], equal_nan=True)
        assert np.array_equal(np.asarray(resumed["failure_reason"], dtype="S"),
                              np.asarray(clean["failure_reason"], dtype="S"))
