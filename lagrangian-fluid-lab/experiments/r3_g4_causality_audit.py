#!/usr/bin/env python3
"""Run a deterministic CPU audit of the R3 G4 causal input contract.

The audit deliberately uses a tiny synthetic trajectory.  It checks that
appending or changing future reference frames cannot change predictions in a
shared prefix, that elapsed time does not use the file endpoint, that frame
zero control features do not use frame one, and that clipping disclosures
contain both a trigger count and its denominator.  A synthetic HDF5 also
contains a changing future free-body trajectory; the loader must ignore it.

This is an input/implementation diagnostic, not a physical acceptance run.
It never invokes CUDA and its only persistent output is the requested JSON
report.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile
from typing import Any

import h5py
import numpy as np
import torch
from torch import nn


LAB = Path(__file__).resolve().parents[1]
BASELINE_PATH = LAB / "experiments" / "r3_g4_baselines.py"
CURRENT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-g4-sidecar-baseline-audit.json"


def load_baseline_module():
    """Load the baseline by path so this probe works from any cwd."""

    spec = importlib.util.spec_from_file_location("r3_g4_baselines_for_causality", BASELINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load baseline module: {BASELINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_case(module: Any, frames: int = 6) -> dict[str, Any]:
    """Build a finite, sidecar-aware tiny case with a known prefix."""

    particles = 3
    time = np.arange(frames, dtype=np.float64) * 0.1
    initial = np.asarray(
        [[0.0, 0.0, 0.0], [0.2, 0.0, 0.0], [0.0, 0.2, 0.0]],
        dtype=np.float32,
    )
    initial_velocity = np.asarray(
        [[0.2, 0.0, 0.0], [0.1, 0.1, 0.0], [0.0, 0.2, 0.0]],
        dtype=np.float32,
    )
    acceleration = np.asarray([0.05, -0.03, 0.02], dtype=np.float32)
    position = np.stack(
        [initial + initial_velocity * float(t) + 0.5 * acceleration * float(t) ** 2 for t in time],
        axis=0,
    )
    velocity = np.stack(
        [initial_velocity + acceleration * float(t) for t in time],
        axis=0,
    )
    mass = np.asarray([1.0, 2.0, 3.0], dtype=np.float32)
    controls = np.zeros((frames, module.CONTROL_WIDTH), dtype=np.float32)
    controls[:, 0] = 1.0
    controls[:, 1] = np.sin(np.deg2rad(np.arange(frames, dtype=np.float32) * 5.0))
    controls[:, 2] = np.cos(np.deg2rad(np.arange(frames, dtype=np.float32) * 5.0))
    controls[:, 3] = np.arange(frames, dtype=np.float32) * 0.01
    controls[:, 6] = 0.1
    controls[:, 9] = 1.0
    boundary = np.zeros((frames, module.BOUNDARY_WIDTH), dtype=np.float32)
    boundary[:, 0] = 1.0
    boundary[:, 1] = -0.4 + np.arange(frames, dtype=np.float32) * 0.01
    boundary[:, 2] = 0.4 + np.arange(frames, dtype=np.float32) * 0.01
    boundary[:, 3] = -0.3
    boundary[:, 4] = 0.3
    boundary[:, 5] = -0.2
    boundary[:, 6] = 0.2
    return {
        "case_id": "synthetic_g4", "family": "F2", "split": "test", "background_id": "synthetic",
        "position": position.astype(np.float32), "velocity": velocity.astype(np.float32),
        "density0": np.full(particles, 1000.0, dtype=np.float32),
        "pressure0": np.zeros(particles, dtype=np.float32), "mass0": mass,
        "time": time, "dp": 0.1, "length_scale": 0.4, "time_scale": 0.2,
        "gravity": np.asarray([0.0, 0.0, -9.81], dtype=np.float32),
        "physics": np.asarray([1.0, 1.0, 0.0], dtype=np.float32),
        "controls": controls, "control_source": "known_prescribed_control_schedule",
        "control_available": True, "boundary": boundary[0].copy(),
        "boundary_by_frame": boundary, "boundary_source": "sidecar_world_triangles",
        "boundary_available": True,
        "boundary_provenance": {
            "schema_version": "boundary-sidecar-v1", "coordinate_frame": "world",
            "case_id": "synthetic_g4", "frame_count": frames, "triangle_count": 2,
            "source_geometry_sha256": "a" * 64,
        },
        "gravity_source": "manifest", "mass_initial_kg": float(mass.sum()),
    }


class _RecordingModel(nn.Module):
    """Parameter-free deterministic model used to compare shared-prefix calls."""

    def __init__(self):
        super().__init__()
        self.feature_calls: list[np.ndarray] = []
        self.raw_calls: list[np.ndarray] = []

    def forward(self, features: torch.Tensor, local: torch.Tensor | None = None) -> torch.Tensor:
        self.feature_calls.append(features.detach().cpu().numpy().copy())
        raw = torch.zeros((len(features), 3), dtype=features.dtype, device=features.device)
        raw[:, 0] = 0.25
        raw[:, 1] = -0.15
        raw[:, 2] = 0.05
        self.raw_calls.append(raw.detach().cpu().numpy().copy())
        return raw


class _ConstantModel(nn.Module):
    """Parameter-free high-output model that deterministically triggers caps."""

    def __init__(self, value: float):
        super().__init__()
        self.value = float(value)

    def forward(self, features: torch.Tensor, local: torch.Tensor | None = None) -> torch.Tensor:
        return torch.full((len(features), 3), self.value, dtype=features.dtype, device=features.device)


def _prefix_invariance(module: Any) -> dict[str, Any]:
    prefix_frames = 5
    short = synthetic_case(module, frames=prefix_frames)
    long = synthetic_case(module, frames=prefix_frames + 2)
    # Keep the common prefix fixed, then alter every future reference/control/
    # boundary value.  A rollout must not consume any of those altered values.
    long["position"][prefix_frames:] += 100.0
    long["velocity"][prefix_frames:] -= 50.0
    long["controls"][prefix_frames:] = 123.0
    long["boundary_by_frame"][prefix_frames:] = -77.0
    short_model = _RecordingModel()
    long_model = _RecordingModel()
    short_result = module.rollout(short_model, "particle_mlp", short, torch.device("cpu"), 0.0)
    long_result = module.rollout(long_model, "particle_mlp", long, torch.device("cpu"), 0.0)
    common_steps = prefix_frames - 1
    feature_diffs = [
        float(np.max(np.abs(short_model.feature_calls[index] - long_model.feature_calls[index])))
        for index in range(common_steps)
    ]
    prediction_diffs = [
        float(np.max(np.abs(short_model.raw_calls[index] - long_model.raw_calls[index])))
        for index in range(common_steps)
    ]
    return {
        "pass": bool(
            short_result["status"] == "completed"
            and long_result["status"] == "completed"
            and feature_diffs
            and prediction_diffs
            and max(feature_diffs) == 0.0
            and max(prediction_diffs) == 0.0
        ),
        "common_predicted_frames": common_steps,
        "max_feature_abs_diff": max(feature_diffs) if feature_diffs else None,
        "max_raw_prediction_abs_diff": max(prediction_diffs) if prediction_diffs else None,
        "short_frames": short_result["frames_predicted"],
        "long_frames": long_result["frames_predicted"],
    }


def _time_endpoint_invariance(module: Any) -> dict[str, Any]:
    short = synthetic_case(module, frames=5)
    long = synthetic_case(module, frames=7)
    frame = 3
    indices = np.arange(len(short["position"][frame]), dtype=np.int64)

    def features(case: dict[str, Any]) -> np.ndarray:
        device = torch.device("cpu")
        position = torch.from_numpy(case["position"][frame])
        velocity = torch.from_numpy(case["velocity"][frame])
        context_mass = torch.from_numpy(case["mass0"])
        values = module.build_features(
            case, position, velocity, position, velocity, context_mass,
            frame, indices, float(case["time"][frame + 1] - case["time"][frame]), device,
        )
        return values.numpy()

    short_features = features(short)
    long_features = features(long)
    diff = float(np.max(np.abs(short_features - long_features)))
    return {
        "pass": diff == 0.0,
        "checked_frame": frame,
        "short_endpoint_s": float(short["time"][-1]),
        "long_endpoint_s": float(long["time"][-1]),
        "max_feature_abs_diff": diff,
    }


def _control_causality(module: Any) -> dict[str, Any]:
    frames = 5
    times = np.arange(frames, dtype=np.float64) * 0.1
    translations = np.stack(
        [np.asarray([0.1 * frame, 0.02 * frame, -0.01 * frame], dtype=np.float32) for frame in range(frames)],
        axis=0,
    )
    future_mutated = translations.copy()
    future_mutated[2:] += np.asarray([7.0, 11.0, 13.0], dtype=np.float32)

    def encode(values: np.ndarray) -> np.ndarray:
        buffer = io.BytesIO()
        with h5py.File(buffer, "w") as h5:
            group = h5.create_group("control")
            group.create_dataset("cup_angle_degrees", data=np.arange(frames, dtype=np.float32) * 3.0)
            transform = np.repeat(np.eye(4, dtype=np.float32)[None, :, :], frames, axis=0)
            transform[:, :3, 3] = values
            group.create_dataset("cup_world_from_body", data=transform)
            result, source, available = module._control_features(h5, times)
            assert source == "known_prescribed_control_schedule"
            assert available
            return result.copy()

    base = encode(translations)
    mutated = encode(future_mutated)
    diff = float(np.max(np.abs(base[:2] - mutated[:2])))
    return {
        "pass": bool(diff == 0.0 and np.allclose(base[0, 6:9], 0.0)),
        "common_control_frames_checked": 2,
        "max_common_prefix_abs_diff": diff,
        "frame_zero_control_velocity": base[0, 6:9].tolist(),
        "future_mutation_start_frame": 2,
    }


def _write_trajectory(path: Path, body_offset: float) -> None:
    frames, particles = 5, 3
    time = np.arange(frames, dtype=np.float64) * 0.1
    position = np.zeros((frames, particles, 3), dtype=np.float32)
    position[:, :, 0] = np.arange(particles, dtype=np.float32)[None, :] * 0.1
    velocity = np.zeros_like(position)
    density = np.full((frames, particles), 1000.0, dtype=np.float32)
    pressure = np.zeros_like(density)
    mass = np.ones_like(density)
    valid = np.ones((frames, particles), dtype=bool)
    particle_type = np.full((frames, particles), 3, dtype=np.int32)
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=time)
        h5.create_dataset("position", data=position)
        h5.create_dataset("velocity", data=velocity)
        h5.create_dataset("density", data=density)
        h5.create_dataset("pressure", data=pressure)
        h5.create_dataset("mass", data=mass)
        h5.create_dataset("valid", data=valid)
        h5.create_dataset("type", data=particle_type)
        body = h5.create_group("free_body")
        body_position = np.zeros((frames, 1, 3), dtype=np.float32)
        body_position[0, 0, 0] = 0.5
        body_position[1:, 0, 0] = body_offset
        body.create_dataset("position", data=body_position)
        body.create_dataset("velocity", data=np.zeros_like(body_position))


def _free_body_future_ignored(module: Any) -> dict[str, Any]:
    record = {
        "case_id": "synthetic_free_body", "family": "F6", "split": "test",
        "hdf5": "trajectory.h5", "physics": {}, "geometry": {},
        "numerics": {"particle_spacing_m": 0.1},
    }
    with tempfile.TemporaryDirectory(prefix="r3-g4-causal-") as directory:
        root = Path(directory)
        manifest = root / "manifest.json"
        manifest.write_text("{}\n")
        path = root / "trajectory.h5"
        _write_trajectory(path, 1.0)
        first = module._load_case(manifest, record)
        _write_trajectory(path, 99.0)
        second = module._load_case(manifest, record)
    assert first is not None and second is not None
    device = torch.device("cpu")
    indices = np.arange(len(first["position"][0]), dtype=np.int64)
    def first_features(case: dict[str, Any]) -> np.ndarray:
        position = torch.from_numpy(case["position"][0])
        velocity = torch.from_numpy(case["velocity"][0])
        values = module.build_features(
            case, position, velocity, position, velocity, torch.from_numpy(case["mass0"]),
            0, indices, 0.1, device,
        )
        return values.numpy()
    diff = float(np.max(np.abs(first_features(first) - first_features(second))))
    return {
        "pass": diff == 0.0 and "free_body" not in first,
        "max_feature_abs_diff": diff,
        "free_body_group_exposed_to_case": "free_body" in first,
    }


def _clipping_disclosure(module: Any) -> dict[str, Any]:
    case = synthetic_case(module, frames=4)
    result = module.rollout(_ConstantModel(100.0), "particle_mlp", case, torch.device("cpu"), 0.25)
    no_clip = module.rollout(_ConstantModel(100.0), "particle_mlp", case, torch.device("cpu"), 0.0)
    count = int(result["clipped_component_count"])
    denominator = int(result["clipping_component_count"])
    saturation_count = int(result["output_saturation_count"])
    output_denominator = int(result["output_component_count"])
    fraction = float(result["clipped_component_fraction"])
    return {
        "pass": bool(
            result["status"] == "completed"
            and count > 0
            and denominator > 0
            and np.isclose(fraction, count / denominator)
            and result["clipping_triggered"]
            and saturation_count == output_denominator
            and result["output_saturation_triggered"]
            and no_clip["clip_dp"] == 0.0
            and no_clip["clipped_component_count"] == 0
            and no_clip["clipped_component_fraction"] == 0.0
        ),
        "configured_clip_dp": result["clip_dp"],
        "clipped_component_count": count,
        "clipping_component_count": denominator,
        "clipped_component_fraction": fraction,
        "clipping_trigger_rate": result["clipping_trigger_rate"],
        "output_saturation_count": saturation_count,
        "output_component_count": output_denominator,
        "output_saturation_fraction": result["output_saturation_fraction"],
        "no_clip_trigger_count": no_clip["clipped_component_count"],
    }


def _constant_velocity_policy() -> dict[str, Any]:
    report = json.loads(CURRENT_REPORT.read_text())
    policy = report.get("constant_velocity_policy", report.get("degradation_policy", ""))
    gate = report.get("constant_velocity_gate", False)
    return {
        "pass": bool(gate is False and "never a physical-scene admission gate" in policy),
        "constant_velocity_gate": gate,
        "policy": policy,
    }


def run_audit() -> dict[str, Any]:
    module = load_baseline_module()
    checks = {
        "prefix_invariance": _prefix_invariance(module),
        "time_endpoint_invariance": _time_endpoint_invariance(module),
        "prescribed_control_causality": _control_causality(module),
        "future_free_body_state_ignored": _free_body_future_ignored(module),
        "clipping_disclosure": _clipping_disclosure(module),
        "constant_velocity_not_admission_gate": _constant_velocity_policy(),
    }
    return {
        "schema_version": 1,
        "scope": "R3-G4 sidecar-aware synthetic CPU prefix and causal audit",
        "execution_status": "complete" if all(check["pass"] for check in checks.values()) else "failed",
        "device": "cpu",
        "matrix_artifact_note": "The existing 12-run GPU sidecar matrix was not rerun; this report validates the current implementation with deterministic CPU probes after the frame-zero control convention fix.",
        "checks": checks,
        "findings": [
            {
                "id": "frame_zero_control_velocity_future_leak",
                "status": "fixed",
                "detail": "Frame-zero prescribed-control velocity is explicitly zero because no past sample exists; frame one onward uses only current-minus-previous transforms.",
            },
            {
                "id": "prefix_and_endpoint_contract",
                "status": "verified_on_synthetic_case",
                "detail": "Changing/appending future reference, control, and sidecar-summary frames leaves shared-prefix features and deterministic predictions unchanged; elapsed time is absolute elapsed time divided by a case scale, not file endpoint normalization.",
            },
            {
                "id": "clipping_disclosure",
                "status": "verified",
                "detail": "Rollout reports hard displacement-clip numerator, denominator, fraction, and trigger flag separately from smooth output-cap saturation counts/rate.",
            },
            {
                "id": "constant_velocity_policy",
                "status": "diagnostic_only",
                "detail": "Constant-velocity comparisons remain per-case diagnostics and do not gate physical-scene admission.",
            },
        ],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=LAB / "campaigns/v0.1-candidate/r3-g4-prefix-causality-audit.json",
    )
    args = parser.parse_args()
    report = run_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"execution_status": report["execution_status"], "checks": report["checks"]}, indent=2))
    if report["execution_status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
