#!/usr/bin/env python3
"""Measure a conservative angular-momentum diagnostic on the isolated F7 canary.

This is an evidence-preserving diagnostic, not a torque estimator and not a
Core qualification step.  It compares the fluid angular momentum resolved by
the existing trajectory with the prescribed pump motion.  A direct torque
dataset is intentionally required separately; this module never promotes a
finite-difference response into a physical torque claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


LAB = Path(__file__).resolve().parents[1]
CANARY = LAB / "campaigns/core-v1/evidence/f7-pump-runtime-canary-dp0020-t0p55"
TRAJECTORY = CANARY / "trajectory.h5"
CONTROL = CANARY / "control-sidecar.h5"
DEFAULT_OUTPUT = CANARY / "angular-momentum-diagnostic-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path, role: str) -> dict[str, Any]:
    return {"path": str(path.relative_to(LAB)), "sha256": sha256(path),
            "bytes": path.stat().st_size, "role": role}


def _require_shape(name: str, value: np.ndarray, shape: tuple[int, ...]) -> None:
    if value.shape != shape:
        raise ValueError(f"{name} has shape {value.shape}, expected {shape}")


def build_diagnostic(trajectory: Path = TRAJECTORY, control: Path = CONTROL) -> dict[str, Any]:
    with h5py.File(trajectory, "r") as source:
        time = np.asarray(source["time"][:], dtype=np.float64)
        position = np.asarray(source["position"][:], dtype=np.float64)
        velocity = np.asarray(source["velocity"][:], dtype=np.float64)
        mass = np.asarray(source["mass"][:], dtype=np.float64)
        valid = np.asarray(source["valid"][:], dtype=bool)
        particle_id = np.asarray(source["particle_id"][:])
    with h5py.File(control, "r") as source:
        control_time = np.asarray(source["time"][:], dtype=np.float64)
        angular_velocity = np.asarray(
            source["control/pump_angular_velocity_rad_s"][:], dtype=np.float64)
        angular_acceleration = np.asarray(
            source["control/pump_angular_acceleration_rad_s2"][:], dtype=np.float64)

    frames = len(time)
    particles = len(particle_id)
    _require_shape("position", position, (frames, particles, 3))
    _require_shape("velocity", velocity, (frames, particles, 3))
    _require_shape("mass", mass, (frames, particles))
    _require_shape("valid", valid, (frames, particles))
    _require_shape("control_time", control_time, (frames,))
    _require_shape("angular_velocity", angular_velocity, (frames, 3))
    _require_shape("angular_acceleration", angular_acceleration, (frames, 3))
    if not np.isfinite(np.concatenate((time, control_time, position.ravel(),
                                      velocity.ravel(), mass.ravel(),
                                      angular_velocity.ravel(),
                                      angular_acceleration.ravel()))).all():
        raise ValueError("diagnostic inputs contain non-finite values")
    if np.any(np.diff(time) <= 0) or not np.array_equal(time, control_time):
        raise ValueError("trajectory and control time axes are not identical and increasing")
    if np.any(mass[valid] <= 0) or len(np.unique(particle_id)) != particles:
        raise ValueError("invalid fluid mass or particle identity axis")

    active = np.linalg.norm(angular_velocity, axis=1) > 1.0e-10
    if not np.any(active):
        raise ValueError("canary has no nonzero prescribed pump motion")
    axis_vectors = angular_velocity[active]
    axis = axis_vectors[-1] / np.linalg.norm(axis_vectors[-1])
    axis_alignment = np.abs(axis_vectors @ axis / np.linalg.norm(axis_vectors, axis=1))
    if np.min(axis_alignment) < 1.0 - 1.0e-10:
        raise ValueError("prescribed pump axis changes within the canary")

    angular_momentum = np.zeros((frames, 3), dtype=np.float64)
    centers = np.zeros((frames, 3), dtype=np.float64)
    fluid_mass = np.zeros(frames, dtype=np.float64)
    for frame in range(frames):
        mask = valid[frame]
        if not np.any(mask):
            raise ValueError(f"frame {frame} contains no valid fluid particles")
        weights = mass[frame, mask]
        center = np.average(position[frame, mask], axis=0, weights=weights)
        centers[frame] = center
        fluid_mass[frame] = np.sum(weights)
        angular_momentum[frame] = np.sum(
            np.cross(position[frame, mask] - center, velocity[frame, mask])
            * weights[:, None], axis=0)

    projected = angular_momentum @ axis
    d_projected = np.full(frames, np.nan, dtype=np.float64)
    d_projected[1:] = np.diff(projected) / np.diff(time)
    active_intervals = active[1:] | active[:-1]
    response = d_projected[1:][active_intervals]
    response = response[np.isfinite(response)]
    motion_start = int(np.flatnonzero(active)[0])
    response_after_motion = d_projected[motion_start + 1:]
    response_after_motion = response_after_motion[np.isfinite(response_after_motion)]

    # This is deliberately diagnostic-only.  The finite-difference response
    # is useful for root review but does not measure wall reaction torque.
    return {
        "schema": "core.f7.pump.angular_momentum_diagnostic.v1",
        "status": "diagnostic_only_torque_unresolved",
        "candidate_id": "F7_pump_prescribed_internal_rotor_recirculation_v1",
        "qualification_claim": "none",
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "physical_torque_claim": False,
        "independence_established": False,
        "inputs": {
            "trajectory": binding(trajectory, "isolated F7 canary fluid trajectory"),
            "control_sidecar": binding(control, "prescribed pump motion control sidecar"),
        },
        "shape": {"frames": frames, "fluid_particles": particles},
        "time": {"start_s": float(time[0]), "end_s": float(time[-1]),
                 "complete_axis": True, "native_frame_count": frames},
        "pump_motion": {
            "axis_unit": axis.tolist(),
            "nonzero_motion_observed": True,
            "motion_start_frame": motion_start,
            "max_angular_speed_rad_s": float(np.max(np.linalg.norm(angular_velocity, axis=1))),
            "max_angular_acceleration_rad_s2": float(np.max(np.linalg.norm(angular_acceleration, axis=1))),
        },
        "fluid_angular_momentum": {
            "axis_projection": projected.tolist(),
            "finite_difference_axis_torque_proxy": [
                None if not np.isfinite(value) else float(value) for value in d_projected
            ],
            "fluid_mass_min_kg": float(np.min(fluid_mass)),
            "fluid_mass_max_kg": float(np.max(fluid_mass)),
            "max_abs_proxy_during_motion": float(np.max(np.abs(response))) if len(response) else 0.0,
            "max_abs_proxy_after_motion_start": float(np.max(np.abs(response_after_motion)))
            if len(response_after_motion) else 0.0,
        },
        "gates": {
            "trajectory_control_hash_bound": True,
            "time_axis_identical": True,
            "finite_arrays": True,
            "particle_identity_unique": True,
            "nonzero_motion_observed": True,
            "finite_difference_response_observed": bool(len(response_after_motion) and np.any(np.abs(response_after_motion) > 0)),
            "direct_torque_dataset_present": False,
            "torque_provenance_verified": False,
            "pump_independence_gate": False,
        },
        "interpretation": [
            "The canary contains nonzero prescribed motion and a measurable fluid angular-momentum response proxy.",
            "The proxy is derived from saved fluid states and is not a wall-reaction torque dataset.",
            "The result cannot establish independence from F6 or authorize F7 Definition/preflight/solver work.",
        ],
        "protected_state_mutation": {
            "registry": 0, "ledger": 0, "matrix": 0, "denominator": 0,
            "queue": 0, "qualification_credit": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, default=TRAJECTORY)
    parser.add_argument("--control", type=Path, default=CONTROL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_diagnostic(args.trajectory, args.control)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "status", "qualification_credit", "gates")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
