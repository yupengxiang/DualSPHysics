#!/usr/bin/env python3
"""Write a hash-bound prescribed Pump control sidecar for a trajectory.

This is a read-only-to-input, fail-closed postprocessor.  It reads an existing
trajectory's time axis and writes an independent HDF5 control attachment with
only the time and prescribed-control datasets determined by the immutable
official Pump XML.  It never copies fluid state, runs GenCase/solver/GPU,
fabricates torque, infers future CFD state, or overwrites an existing output.

The output is an interface artifact, not CFD evidence: it cannot establish
that a solver followed the prescribed motion or that the pump torque is
physically independent of another family.  Those remain root-review gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_contract import DUALSPHYSICS_MVROTFILE_ROTATION_VERSION
from scripts.f7_pump_geometry_adapter_v1 import (
    DEFAULT_DEFINITION,
    parse_pump_definition,
    pump_angle_degrees,
    pump_angular_velocity_degrees_per_second,
)


SCHEMA = "core.f7.pump.causal_sidecar.v1"
BODY_FRAME_DATASET = "control/pump_world_from_body"
ANGULAR_CONTROL_DATASET = "control/pump_angular_velocity_rad_s"
ANGLE_DATASET = "control/pump_angle_rad"
ACCELERATION_DATASET = "control/pump_angular_acceleration_rad_s2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_array(value: np.ndarray) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(repr(tuple(array.shape)).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def _rotation_about_axis(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / np.linalg.norm(axis)
    skew = np.asarray([
        [0.0, -axis[2], axis[1]],
        [axis[2], 0.0, -axis[0]],
        [-axis[1], axis[0], 0.0],
    ])
    return (
        np.eye(3) * np.cos(angle_rad)
        + (1.0 - np.cos(angle_rad)) * np.outer(axis, axis)
        + np.sin(angle_rad) * skew
    )


def _world_from_body(axis_point: np.ndarray, axis_direction: np.ndarray,
                     angle_degrees: float, rotation_sign: float) -> np.ndarray:
    rotation = _rotation_about_axis(
        axis_direction, rotation_sign * np.deg2rad(float(angle_degrees))
    )
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = rotation
    result[:3, 3] = axis_point - rotation @ axis_point
    return result


def _angular_acceleration(time_s: float, contract: dict[str, Any], sign: float) -> float:
    start = float(contract["begin_start_s"])
    finish = float(contract["finish_s"])
    first = contract["segments"][0]
    first_end = start + float(first["duration_s"])
    if time_s <= start or time_s >= finish or time_s > first_end:
        return 0.0
    return sign * np.deg2rad(float(first["acceleration_deg_s2"]))


def _read_time(handle: h5py.File, trajectory: Path) -> np.ndarray:
    if "time" not in handle:
        raise ValueError(f"trajectory has no /time dataset: {trajectory}")
    times = np.asarray(handle["time"][:], dtype=np.float64)
    if times.ndim != 1 or len(times) < 2 or not np.isfinite(times).all():
        raise ValueError("trajectory /time must be finite, one-dimensional, and have at least two frames")
    if np.any(np.diff(times) <= 0) or times[0] < 0:
        raise ValueError("trajectory /time must be strictly increasing from a nonnegative time")
    if "position" not in handle:
        raise ValueError("trajectory must contain /position before controls can be attached")
    if handle["position"].shape[0] != len(times):
        raise ValueError("trajectory /position frame count does not match /time")
    return times


def build_control_arrays(times: np.ndarray, contract: dict[str, Any]) -> dict[str, np.ndarray]:
    """Evaluate exact prescribed controls at the trajectory's saved times."""
    times = np.asarray(times, dtype=np.float64)
    max_time = float(contract["time_max_s"])
    if times[-1] > max_time + 1e-10:
        raise ValueError("trajectory extends beyond the official Pump TimeMax")
    sign = -1.0 if contract["motion_version"] == DUALSPHYSICS_MVROTFILE_ROTATION_VERSION else 1.0
    axis_point = np.asarray(contract["axis_point_m"], dtype=np.float64)
    axis_direction = np.asarray(contract["axis_direction_m"], dtype=np.float64)
    axis_unit = axis_direction / np.linalg.norm(axis_direction)
    angles = np.asarray([pump_angle_degrees(t, contract) for t in times], dtype=np.float64)
    angular_speed = np.asarray([
        sign * np.deg2rad(pump_angular_velocity_degrees_per_second(t, contract))
        for t in times
    ], dtype=np.float64)
    transforms = np.asarray([
        _world_from_body(axis_point, axis_direction, angle, sign)
        for angle in angles
    ], dtype=np.float64)
    acceleration = np.asarray([
        sign * axis_unit * _angular_acceleration(t, contract, 1.0)
        for t in times
    ], dtype=np.float64)
    angular = angular_speed[:, None] * axis_unit[None, :]
    if not (np.isfinite(transforms).all() and np.isfinite(angular).all()
            and np.isfinite(acceleration).all()):
        raise ValueError("derived Pump controls are nonfinite")
    return {
        "transforms": transforms,
        "angles_rad": np.deg2rad(sign * angles),
        "angular_velocity_rad_s": angular,
        "angular_acceleration_rad_s2": acceleration,
    }


def make_sidecar(trajectory: str | Path, output: str | Path,
                 definition: str | Path = DEFAULT_DEFINITION) -> dict[str, Any]:
    """Write only causal prescribed-control datasets bound to one trajectory."""
    source = Path(trajectory).expanduser().resolve()
    target = Path(output).expanduser().resolve()
    definition = Path(definition).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {target}")
    if source == target:
        raise ValueError("input and output trajectory must be different files")

    source_hash = sha256_file(source)
    contract = parse_pump_definition(definition)
    with h5py.File(source, "r") as source_h5:
        times = _read_time(source_h5, source)
        controls = build_control_arrays(times, contract)
        if "control" in source_h5 and any(
            name in source_h5["control"]
            for name in ("pump_world_from_body", "pump_angular_velocity_rad_s",
                         "pump_angle_rad", "pump_angular_acceleration_rad_s2")
        ):
            raise ValueError("source already contains F7 Pump control datasets")

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        if partial.exists():
            raise FileExistsError(f"refusing to reuse partial output: {partial}")
        try:
            with h5py.File(partial, "w") as target_h5:
                target_h5.create_dataset("time", data=times)
                control = target_h5.require_group("control")
                control.create_dataset("pump_world_from_body", data=controls["transforms"])
                control.create_dataset("pump_angular_velocity_rad_s", data=controls["angular_velocity_rad_s"])
                control.create_dataset("pump_angle_rad", data=controls["angles_rad"])
                control.create_dataset("pump_angular_acceleration_rad_s2", data=controls["angular_acceleration_rad_s2"])
                target_h5.attrs["f7_causal_sidecar_schema"] = SCHEMA
                target_h5.attrs["f7_source_trajectory_sha256"] = source_hash
                target_h5.attrs["f7_motion_source_sha256"] = contract["motion_sha256"]
                target_h5.attrs["f7_control_time_sha256"] = sha256_array(times)
                target_h5.attrs["f7_torque_dataset_present"] = False
                target_h5.attrs["f7_runtime_evidence"] = False
                target_h5.attrs["f7_definition_writer_invoked"] = False
                target_h5.attrs["f7_solver_invoked"] = False
            partial.replace(target)
        except Exception:
            if partial.exists():
                partial.unlink()
            raise

    output_hash = sha256_file(target)
    return {
        "schema": SCHEMA,
        "status": "interface_sidecar_written_not_runtime_evidence",
        "trajectory_source": {
            "path": str(source),
            "sha256": source_hash,
            "time_sha256": sha256_array(times),
            "frame_count": int(len(times)),
            "time_s": [float(times[0]), float(times[-1])],
        },
        "output": {"path": str(target), "sha256": output_hash},
        "motion_source": {
            "path": str(definition),
            "sha256": contract["definition_sha256"],
            "motion_sha256": contract["motion_sha256"],
            "motion_version": contract["motion_version"],
        },
        "datasets": {
            "body_frame": BODY_FRAME_DATASET,
            "angular_control": ANGULAR_CONTROL_DATASET,
            "angle": ANGLE_DATASET,
            "angular_acceleration": ACCELERATION_DATASET,
            "body_frame_sha256": sha256_array(controls["transforms"]),
            "angular_control_sha256": sha256_array(controls["angular_velocity_rad_s"]),
        },
        "torque": {
            "present": False,
            "fabricated": False,
            "required_for_physical_independence": True,
        },
        "execution_controls": {
            "input_modified": False,
            "definition_written": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = make_sidecar(args.trajectory, args.output, args.definition)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
