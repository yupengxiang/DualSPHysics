#!/usr/bin/env python3
"""Run corrected, small learned baselines for the R3 G4 audit.

This is deliberately a development experiment, not a benchmark trainer.  It
keeps the old weak baselines available while making the causal input contract
explicit:

* centering is computed from the complete current particle context;
* the velocity supplied during training is the same state variable used by a
  rollout (initial solver velocity, then the previous predicted displacement);
* elapsed time is independent of the file's final timestamp;
* future fluid state is never read during an autonomous rollout;
* prescribed controls may be read at the current known time, while a free
  body's future state is never used;
* clipping is optional and its trigger rate is reported rather than hidden;
* all errors use the same vector-RMSE convention.

When a release record links a validated boundary sidecar, the model receives
the current frame's finite-triangle world-space AABB summary and an
availability bit.  Records without a sidecar retain the explicit zero/missing
fallback (or a legacy static bounds summary); a linked but invalid sidecar is
an input-contract error rather than a silent fallback.
"""

from __future__ import annotations

import argparse
import json
import random
import string
import time
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import torch
from torch import nn


FAMILY_INDEX = {"F1": 0, "F2": 1, "F3": 2, "F4": 3, "F5": 4, "F6": 5}
ROUTES = ("particle_mlp", "deepset_context", "local_interaction", "physics_residual")
CONTROL_WIDTH = 10
BOUNDARY_WIDTH = 7
BOUNDARY_COMPONENT_FEATURE_FIELDS = (
    "presence", "distance", "normal_x", "normal_y", "normal_z", "type",
    "wall_velocity_x", "wall_velocity_y", "wall_velocity_z",
)
BOUNDARY_COMPONENT_WIDTH = len(BOUNDARY_COMPONENT_FEATURE_FIELDS)
MAX_BOUNDARY_COMPONENTS = 8
PHYSICS_WIDTH = 3
LOCAL_WIDTH = 8
NEIGHBORS = 8
OUTPUT_CAP = 8.0

FORBIDDEN_FUTURE_STATE_KEYS = frozenset({
    "future_fluid_state", "future_free_body_state", "future_state", "next_state",
    "future_position", "future_velocity", "future_density", "future_pressure",
    "free_body_future", "fluid_future", "fluid_state_t1", "free_body_state_t1",
    "particle_velocity_t1", "body_pose_t1", "future_fluid_velocity",
    "future_free_body_velocity", "future_body_pose",
})


class ParticleMLP(nn.Module):
    """Per-particle direct displacement predictor (weak learned baseline)."""

    def __init__(self, inputs: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(inputs, hidden), nn.SiLU(),
            nn.Linear(hidden, hidden), nn.SiLU(),
            nn.Linear(hidden, 3),
        )

    def forward(self, features: torch.Tensor, local: torch.Tensor | None = None) -> torch.Tensor:
        return self.net(features)


class DeepSetContext(nn.Module):
    """Global set-context route retained from W12."""

    def __init__(self, inputs: int, hidden: int):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(inputs, hidden), nn.SiLU(),
            nn.Linear(hidden, hidden), nn.SiLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(2 * hidden, hidden), nn.SiLU(), nn.Linear(hidden, 3),
        )

    def forward(self, features: torch.Tensor, local: torch.Tensor | None = None) -> torch.Tensor:
        encoded = self.encoder(features)
        context = encoded.mean(dim=0, keepdim=True).expand_as(encoded)
        return self.decoder(torch.cat((encoded, context), dim=-1))


class LocalInteraction(nn.Module):
    """Direct displacement route with an explicit local neighbour summary."""

    def __init__(self, inputs: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(inputs + LOCAL_WIDTH, hidden), nn.SiLU(),
            nn.Linear(hidden, hidden), nn.SiLU(),
            nn.Linear(hidden, 3),
        )

    def forward(self, features: torch.Tensor, local: torch.Tensor | None = None) -> torch.Tensor:
        if local is None:
            raise ValueError("local interaction route requires neighbour features")
        return self.net(torch.cat((features, local), dim=-1))


class PhysicsResidual(nn.Module):
    """Predict normalized acceleration and integrate it semi-implicitly."""

    def __init__(self, inputs: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(inputs, hidden), nn.SiLU(),
            nn.Linear(hidden, hidden), nn.SiLU(),
            nn.Linear(hidden, 3),
        )

    def forward(self, features: torch.Tensor, local: torch.Tensor | None = None) -> torch.Tensor:
        return self.net(features)


def model_for(route: str, inputs: int, hidden: int) -> nn.Module:
    if route == "particle_mlp":
        return ParticleMLP(inputs, hidden)
    if route == "deepset_context":
        return DeepSetContext(inputs, hidden)
    if route == "local_interaction":
        return LocalInteraction(inputs, hidden)
    if route == "physics_residual":
        return PhysicsResidual(inputs, hidden)
    raise ValueError(f"unknown route {route}")


def _as_vector(value: Any, default: tuple[float, float, float]) -> np.ndarray:
    if value is None:
        return np.asarray(default, dtype=np.float32)
    array = np.asarray(value, dtype=np.float32).reshape(-1)
    if array.size != 3 or not np.isfinite(array).all():
        return np.asarray(default, dtype=np.float32)
    return array


def _normalise_contract_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _forbidden_future_keys(value: Any, prefix: str = "") -> list[str]:
    """Recursively find explicit fluid/free-body future-state aliases."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalise_contract_key(key)
            path = f"{prefix}.{key}" if prefix else str(key)
            if normalized in FORBIDDEN_FUTURE_STATE_KEYS:
                found.append(path)
            elif (
                any(marker in normalized for marker in ("future", "next", "_t1", "frame1"))
                and ("fluid" in normalized or "body" in normalized or "state" in normalized)
            ):
                found.append(path)
            found.extend(_forbidden_future_keys(item, path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_forbidden_future_keys(item, f"{prefix}[{index}]"))
    return found


def validate_model_input_contract(payload: Any) -> dict[str, Any]:
    """Reject future fluid/free-body state from a G4 input payload.

    Current prescribed controls (including angular velocity) are allowed.  The
    validator is intentionally usable by callers constructing dictionaries as
    well as by the HDF5 loader, and raises before a model sees a forbidden
    feature rather than merely documenting the issue after a rollout.
    """
    forbidden = _forbidden_future_keys(payload)
    if forbidden:
        raise ValueError(
            "future fluid/free-body state is forbidden in G4 model input: "
            + ", ".join(forbidden)
        )
    return {
        "valid": True,
        "forbidden_future_state_keys": [],
        "future_fluid_or_free_body_state_allowed": False,
        "allowed_control_fields": [
            "prescribed_linear_velocity_mps", "prescribed_angular_velocity_radps",
        ],
    }


# Descriptive aliases for custom producers that used the review handoff's
# terminology.
validate_g4_model_input = validate_model_input_contract
validate_model_inputs = validate_model_input_contract


def _control_features(h5: h5py.File, times: np.ndarray) -> tuple[np.ndarray, str, bool]:
    """Encode only known prescribed controls at the current physical time.

    A prescribed angular-velocity schedule is a legal control and is encoded
    directly in slots 6:9.  If no such schedule exists, the same slots retain
    the historical prescribed translational velocity derived from the current
    and previous poses (with an explicit zero convention at frame zero).
    """

    result = np.zeros((len(times), CONTROL_WIDTH), dtype=np.float32)
    if "control" not in h5:
        return result, "missing_control_group", False
    group = h5["control"]
    if "cup_angle_degrees" not in group:
        return result, "control_group_without_prescribed_angle", False
    angle = np.asarray(group["cup_angle_degrees"][:], dtype=np.float32)
    if angle.shape != (len(times),) or not np.isfinite(angle).all():
        return result, "invalid_prescribed_control", False
    result[:, 0] = 1.0
    radians = np.deg2rad(angle)
    result[:, 1] = np.sin(radians)
    result[:, 2] = np.cos(radians)
    angular = group.get("prescribed_angular_velocity_radps")
    if angular is not None and "cup_world_from_body" not in group:
        values = np.asarray(angular[:], dtype=np.float32)
        if values.shape != (len(times), 3) or not np.isfinite(values).all():
            return result, "invalid_prescribed_angular_control", False
        result[:, 6:9] = values
        result[:, 9] = 1.0
        return result, "known_prescribed_angular_control_schedule", True
    if "cup_world_from_body" in group:
        transform = np.asarray(group["cup_world_from_body"][:], dtype=np.float32)
        if transform.shape == (len(times), 4, 4) and np.isfinite(transform).all():
            result[:, 3:6] = transform[:, :3, 3]
            if angular is not None:
                values = np.asarray(angular[:], dtype=np.float32)
                if values.shape != (len(times), 3) or not np.isfinite(values).all():
                    return result, "invalid_prescribed_angular_control", False
                result[:, 6:9] = values
                result[:, 9] = 1.0
                return result, "known_prescribed_angular_control_schedule", True
            if len(times) > 1:
                dt = np.maximum(np.diff(times), 1e-9).astype(np.float32)
                result[1:, 6:9] = np.diff(result[:, 3:6], axis=0) / dt[:, None]
                # There is no past sample for frame zero.  Do not copy the
                # frame-one finite difference here: doing so makes the first
                # rollout input depend on a future prescribed control value.
                # The zero convention is explicit and remains causal.
            result[:, 9] = 1.0  # transform is present and finite
            return result, "known_prescribed_control_schedule", True
    return result, "known_prescribed_angle_only", True


def _attribute_text(value: Any, default: str = "") -> str:
    """Return an HDF5 attribute as portable text."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value) if value is not None else default


def _pairwise_bounds(triangles: np.ndarray) -> np.ndarray:
    """Summarize ``[N,3,3]`` triangles as xmin,xmax,ymin,ymax,zmin,zmax."""

    minimum = np.min(triangles, axis=(0, 1))
    maximum = np.max(triangles, axis=(0, 1))
    return np.asarray(
        [minimum[0], maximum[0], minimum[1], maximum[1], minimum[2], maximum[2]],
        dtype=np.float64,
    )


def _triangle_normal(triangle: np.ndarray) -> np.ndarray:
    triangle = np.asarray(triangle, dtype=np.float64).reshape(3, 3)
    normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
    norm = float(np.linalg.norm(normal))
    return normal / norm if norm > 1e-12 else np.zeros(3, dtype=np.float64)


def _closest_point_on_segment(point: np.ndarray, first: np.ndarray, second: np.ndarray) -> np.ndarray:
    edge = second - first
    denominator = float(np.dot(edge, edge))
    alpha = float(np.dot(point - first, edge) / denominator) if denominator > 1e-16 else 0.0
    return first + np.clip(alpha, 0.0, 1.0) * edge


def _closest_point_on_triangle(point: np.ndarray, triangle: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return closest point and oriented normal on one finite triangle."""
    tri = np.asarray(triangle, dtype=np.float64).reshape(3, 3)
    a, b, c = tri
    ab, ac, ap = b - a, c - a, point - a
    normal = _triangle_normal(tri)
    d1, d2 = float(np.dot(ab, ap)), float(np.dot(ac, ap))
    if d1 <= 0.0 and d2 <= 0.0:
        return a, normal
    bp = point - b
    d3, d4 = float(np.dot(ab, bp)), float(np.dot(ac, bp))
    if d3 >= 0.0 and d4 <= d3:
        return b, normal
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        alpha = d1 / max(d1 - d3, 1e-16)
        return a + alpha * ab, normal
    cp = point - c
    d5, d6 = float(np.dot(ab, cp)), float(np.dot(ac, cp))
    if d6 >= 0.0 and d5 <= d6:
        return c, normal
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        alpha = d2 / max(d2 - d6, 1e-16)
        return a + alpha * ac, normal
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        alpha = (d4 - d3) / max((d4 - d3) + (d5 - d6), 1e-16)
        return b + alpha * (c - b), normal
    denominator = max(va + vb + vc, 1e-16)
    inverse = 1.0 / denominator
    beta, gamma = vb * inverse, vc * inverse
    return a + ab * beta + ac * gamma, normal


def _component_groups(triangle_type: np.ndarray, triangle_component: np.ndarray) -> list[tuple[int, int, np.ndarray]]:
    keys = [(int(kind), int(component)) for kind, component in zip(triangle_type, triangle_component)]
    groups = []
    for key in dict.fromkeys(keys):
        indices = np.asarray([index for index, item in enumerate(keys) if item == key], dtype=np.int64)
        groups.append((key[0], key[1], indices))
    return groups


def _boundary_component_series(sidecar_path: Path, solver_times: np.ndarray) -> list[dict[str, Any]]:
    """Read finite sidecar triangles grouped by component for model inputs."""
    with h5py.File(sidecar_path, "r") as sidecar:
        times = np.asarray(sidecar["time"][:], dtype=np.float64)
        triangles = np.asarray(sidecar["triangles_world"][:], dtype=np.float64)
        kinds = np.asarray(sidecar["triangle_type"][:], dtype=np.int8)
        components = np.asarray(
            sidecar["triangle_component"][:] if "triangle_component" in sidecar else sidecar["triangle_mk"][:],
            dtype=np.int64,
        )
    if times.shape != solver_times.shape or not np.allclose(times, solver_times, atol=1e-9, rtol=0.0):
        raise ValueError("boundary component sidecar time axis differs from solver")
    if triangles.ndim != 4 or triangles.shape[0] != len(times):
        raise ValueError("boundary component triangles have invalid shape")
    components_out = []
    for kind, component, indices in _component_groups(kinds, components):
        components_out.append({
            "component_id": int(component),
            "type": int(kind),
            "triangles_world": triangles[:, indices].copy(),
        })
    if len(components_out) > MAX_BOUNDARY_COMPONENTS:
        raise ValueError(
            f"sidecar contains {len(components_out)} components; max supported is {MAX_BOUNDARY_COMPONENTS}"
        )
    return components_out


def _boundary_component_features(case: dict[str, Any], frame: int,
                                 target_position: np.ndarray, dt: float) -> np.ndarray:
    """Build per-target, per-component distance/normal/type/wall-velocity fields."""
    targets = np.asarray(target_position, dtype=np.float64).reshape(-1, 3)
    result = np.zeros((len(targets), MAX_BOUNDARY_COMPONENTS, BOUNDARY_COMPONENT_WIDTH), dtype=np.float32)
    components = case.get("boundary_components") or []
    if not components:
        return result
    scale = max(float(case.get("length_scale", 1.0)), 1e-9)
    frame = int(frame)
    for component_index, component in enumerate(components):
        triangles = np.asarray(component["triangles_world"][frame], dtype=np.float64)
        kind = int(component["type"])
        previous = (
            np.asarray(component["triangles_world"][frame - 1], dtype=np.float64)
            if frame > 0 else triangles
        )
        wall_velocity = (triangles.mean(axis=(0, 1)) - previous.mean(axis=(0, 1))) / max(float(dt), 1e-9)
        wall_velocity_scale = float(case.get("time_scale", 1.0)) / scale
        for target_index, target in enumerate(targets):
            best_distance = np.inf
            best_normal = np.zeros(3, dtype=np.float64)
            best_point = None
            for triangle in triangles:
                point, normal = _closest_point_on_triangle(target, triangle)
                distance = float(np.linalg.norm(target - point))
                if distance < best_distance:
                    best_distance = distance
                    best_normal = normal
                    best_point = point
            if best_point is None or not np.isfinite(best_distance):
                continue
            result[target_index, component_index] = np.asarray([
                1.0,
                best_distance / scale,
                *best_normal,
                float(kind),
                *(wall_velocity * wall_velocity_scale),
            ], dtype=np.float32)
    return result


def boundary_component_features(case: dict[str, Any], frame: int,
                                target_position: Any, dt: float | None = None) -> list[list[dict[str, Any]]]:
    """Return named per-target/per-component geometry inputs.

    This is the auditable representation used to populate the fixed-width
    model block.  Each row contains presence, finite-component distance,
    oriented normal, integer boundary type, and current wall velocity.  The
    packed tensor used by ``build_features`` is just this same data padded to
    ``MAX_BOUNDARY_COMPONENTS``; no AABB-only replacement is made on the
    sidecar-aware path.
    """
    points = np.asarray(target_position, dtype=np.float64).reshape(-1, 3)
    if dt is None:
        times = np.asarray(case["time"], dtype=np.float64)
        dt = float(times[int(frame) + 1] - times[int(frame)]) if int(frame) + 1 < len(times) else 0.0
    packed = _boundary_component_features(case, int(frame), points, float(dt))
    rows: list[list[dict[str, Any]]] = []
    for target_index in range(len(points)):
        row: list[dict[str, Any]] = []
        for component_index, component in enumerate(case.get("boundary_components") or []):
            values = packed[target_index, component_index]
            length_scale = max(float(case.get("length_scale", 1.0)), 1e-9)
            time_scale = max(float(case.get("time_scale", 1.0)), 1e-9)
            wall_velocity_mps = values[6:9] * length_scale / time_scale
            row.append({
                "component_id": int(component["component_id"]),
                "distance_to_boundary_component": float(values[1] * length_scale),
                "distance_to_boundary_component_m": float(values[1] * length_scale),
                "normal": values[2:5].astype(float).tolist(),
                "boundary_normal": values[2:5].astype(float).tolist(),
                "type": int(component["type"]),
                "boundary_type": int(component["type"]),
                "wall_velocity": wall_velocity_mps.astype(float).tolist(),
                "wall_velocity_mps": wall_velocity_mps.astype(float).tolist(),
            })
        rows.append(row)
    return rows


build_boundary_component_features = boundary_component_features


def _validate_boundary_sidecar(
    sidecar_path: Path,
    record: dict[str, Any],
    solver_times: np.ndarray,
    length_scale: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Read a linked sidecar and return normalized per-frame summaries.

    The release audit proves that a sidecar is structurally sound.  This
    input-boundary check additionally proves that it belongs to this case and
    has exactly the same frame/time axis as the HDF5 trajectory consumed by
    the learner.
    """

    with h5py.File(sidecar_path, "r") as sidecar:
        required = ("time", "triangles_world", "triangle_mk", "triangle_type")
        missing = [name for name in required if name not in sidecar]
        if missing:
            raise ValueError(f"{record['case_id']}: boundary sidecar missing {missing}")
        schema = _attribute_text(sidecar.attrs.get("schema_version"))
        if schema != "boundary-sidecar-v1":
            raise ValueError(f"{record['case_id']}: unsupported boundary sidecar schema {schema!r}")
        coordinate_frame = _attribute_text(sidecar.attrs.get("coordinate_frame"))
        if coordinate_frame != "world":
            raise ValueError(f"{record['case_id']}: boundary sidecar is not in world coordinates")
        sidecar_case_id = _attribute_text(sidecar.attrs.get("case_id"))
        if sidecar_case_id != record["case_id"]:
            raise ValueError(
                f"{record['case_id']}: boundary sidecar case_id is {sidecar_case_id!r}"
            )
        source_hash = _attribute_text(sidecar.attrs.get("source_geometry_sha256"))
        if len(source_hash) != 64 or any(char not in string.hexdigits for char in source_hash):
            raise ValueError(f"{record['case_id']}: boundary sidecar source geometry hash is invalid")
        times = np.asarray(sidecar["time"][:], dtype=np.float64)
        triangles = np.asarray(sidecar["triangles_world"][:], dtype=np.float64)
        triangle_mk = np.asarray(sidecar["triangle_mk"][:])
        triangle_type = np.asarray(sidecar["triangle_type"][:])
        triangle_component = np.asarray(
            sidecar["triangle_component"][:] if "triangle_component" in sidecar else triangle_mk,
            dtype=np.int64,
        )
        if (
            times.ndim != 1
            or len(times) < 2
            or not np.all(np.isfinite(times))
            or not np.all(np.diff(times) > 0)
        ):
            raise ValueError(f"{record['case_id']}: boundary sidecar time must be finite and strictly increasing")
        if (
            solver_times.ndim != 1
            or len(solver_times) < 2
            or not np.all(np.isfinite(solver_times))
            or not np.all(np.diff(solver_times) > 0)
        ):
            raise ValueError(f"{record['case_id']}: solver time must be finite and strictly increasing")
        if len(times) != len(solver_times):
            raise ValueError(f"{record['case_id']}: boundary sidecar frame count differs from HDF5")
        if not np.allclose(times, solver_times, rtol=0.0, atol=1e-9):
            raise ValueError(f"{record['case_id']}: boundary sidecar time axis differs from HDF5")
        if triangles.ndim != 4 or triangles.shape[0] != len(times) or triangles.shape[2:] != (3, 3):
            raise ValueError(f"{record['case_id']}: triangles_world must have shape [T,N,3,3]")
        if triangles.shape[1] < 1:
            raise ValueError(f"{record['case_id']}: boundary sidecar has no triangles")
        if len(triangle_mk) != triangles.shape[1] or len(triangle_type) != triangles.shape[1]:
            raise ValueError(f"{record['case_id']}: boundary triangle labels do not match geometry")
        if len(triangle_component) != triangles.shape[1]:
            raise ValueError(f"{record['case_id']}: boundary component labels do not match geometry")
        if not np.all(np.isin(triangle_type, (0, 1))):
            raise ValueError(f"{record['case_id']}: boundary sidecar has non-boundary triangle types")
        if not np.all(np.isfinite(triangles)):
            raise ValueError(f"{record['case_id']}: boundary sidecar has non-finite triangles")
        edge1 = triangles[:, :, 1] - triangles[:, :, 0]
        edge2 = triangles[:, :, 2] - triangles[:, :, 0]
        area2 = np.linalg.norm(np.cross(edge1, edge2), axis=-1)
        if not np.all(area2 > 1e-12):
            raise ValueError(f"{record['case_id']}: boundary sidecar has degenerate triangles")
        frame_bounds = np.asarray(
            [_pairwise_bounds(frame_triangles) for frame_triangles in triangles],
            dtype=np.float32,
        )
        normalized = np.zeros((len(times), BOUNDARY_WIDTH), dtype=np.float32)
        normalized[:, 0] = 1.0
        normalized[:, 1:] = frame_bounds / max(length_scale, 1e-9)
        provenance = {
            "path": sidecar_path.name,
            "schema_version": schema,
            "coordinate_frame": coordinate_frame,
            "case_id": sidecar_case_id,
            "frame_count": int(len(times)),
            "triangle_count": int(triangles.shape[1]),
            "static_triangle_count": int(np.sum(triangle_type == 0)),
            "moving_triangle_count": int(np.sum(triangle_type == 1)),
            "component_count": int(len(np.unique(triangle_component))),
            "component_ids": [int(value) for value in np.unique(triangle_component)],
            "motion_interpolation": _attribute_text(
                sidecar.attrs.get("motion_interpolation"), "rigid_pose_or_analytic_only"
            ),
            "source_vtk": _attribute_text(sidecar.attrs.get("source_vtk"), "unknown"),
            "source_hdf5": _attribute_text(sidecar.attrs.get("source_hdf5"), "unknown"),
            "source_geometry_sha256": source_hash,
        }
    return normalized, provenance


def _boundary_features(
    record: dict[str, Any],
    h5: h5py.File,
    length_scale: float,
    manifest_path: Path | None = None,
    solver_times: np.ndarray | None = None,
) -> tuple[np.ndarray, str, bool, dict[str, Any] | None]:
    """Load sidecar summaries or a legacy static boundary fallback.

    The first return value is a ``[T,7]`` array.  Column zero is the geometry
    availability bit; the remaining columns use the pairwise
    ``xmin,xmax,ymin,ymax,zmin,zmax`` order.  A linked sidecar is strict: any
    missing, mismatched, or malformed file raises instead of being hidden as
    missing geometry.
    """

    times = np.asarray(solver_times if solver_times is not None else h5["time"][:], dtype=np.float64)
    geometry = record.get("geometry", {})
    sidecar_ref = geometry.get("boundary_sidecar")
    if sidecar_ref is not None:
        if manifest_path is None:
            raise ValueError(f"{record['case_id']}: manifest path is required for boundary sidecar")
        manifest_root = Path(manifest_path).resolve().parent
        sidecar_path = (manifest_root / str(sidecar_ref)).resolve()
        try:
            sidecar_path.relative_to(manifest_root)
        except ValueError as error:
            raise ValueError(f"{record['case_id']}: boundary sidecar escapes release root") from error
        if not sidecar_path.is_file():
            raise FileNotFoundError(f"{record['case_id']}: linked boundary sidecar not found: {sidecar_path}")
        dynamic, provenance = _validate_boundary_sidecar(sidecar_path, record, times, length_scale)
        provenance["path"] = str(sidecar_path.relative_to(manifest_root))
        return dynamic, "sidecar_world_triangles", True, provenance

    bounds = None
    source = "missing_boundary_sidecar"
    if "boundary" in h5 and "bounds" in h5["boundary"]:
        candidate = np.asarray(h5["boundary"]["bounds"][:], dtype=np.float32).reshape(-1)
        if candidate.size == 6 and np.isfinite(candidate).all():
            bounds = candidate
            source = "hdf5_boundary_bounds"
    candidate = geometry.get("boundary_bounds_m")
    if bounds is None and candidate is not None:
        array = np.asarray(candidate, dtype=np.float32).reshape(-1)
        if array.size == 6 and np.isfinite(array).all():
            bounds = array
            source = "manifest_boundary_bounds"
    result = np.zeros(BOUNDARY_WIDTH, dtype=np.float32)
    if bounds is None:
        return np.repeat(result[None, :], len(times), axis=0), source, False, None
    result[0] = 1.0
    result[1:] = bounds / max(length_scale, 1e-9)
    return np.repeat(result[None, :], len(times), axis=0), source, True, {
        "schema_version": "legacy-static-boundary-summary",
        "coordinate_frame": "unknown",
        "frame_count": int(len(times)),
        "triangle_count": 0,
        "source_geometry_sha256": None,
    }


def _load_case(manifest_path: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    validate_model_input_contract(record)
    path = manifest_path.parent / record["hdf5"]
    with h5py.File(path, "r") as h5:
        valid = np.asarray(h5["valid"][:], dtype=bool)
        particle_type = np.asarray(h5["type"][:])
        fluid = valid & (particle_type == 3)
        if not fluid[0].any():
            return None
        stable = np.all(fluid, axis=0)
        times = np.asarray(h5["time"][:], dtype=np.float64)
        position = np.asarray(h5["position"][:, stable], dtype=np.float32)
        velocity = np.asarray(h5["velocity"][:, stable], dtype=np.float32)
        density = np.asarray(h5["density"][:, stable], dtype=np.float32)
        pressure = np.asarray(h5["pressure"][:, stable], dtype=np.float32)
        mass = np.asarray(h5["mass"][:, stable], dtype=np.float32)
        controls, control_source, control_available = _control_features(h5, times)
        # These are initial-condition/material attributes.  They are frozen in
        # the rollout, so no reference future density/pressure is leaked.
        density0 = density[0].copy()
        pressure0 = pressure[0].copy()
        mass0 = mass[0].copy()
        initial_extent = np.ptp(position[0], axis=0)
        length_scale = float(max(record["numerics"]["particle_spacing_m"], np.max(initial_extent)))
        gravity_explicit = record.get("physics", {}).get("gravity_world_mps2")
        gravity = _as_vector(gravity_explicit, (0.0, 0.0, -9.81))
        gravity_source = "manifest" if gravity_explicit is not None else "default_world_z"
        rho_ref_value = record.get("physics", {}).get("fluid_density_kg_m3")
        rho_ref = float(rho_ref_value) if rho_ref_value is not None else float(np.median(density0))
        viscosity_value = record.get("physics", {}).get("dynamic_viscosity_pa_s")
        viscosity = float(viscosity_value) if viscosity_value is not None else 0.001
        physics = np.asarray(
            [rho_ref / 1000.0, viscosity / 0.001, 1.0 if gravity_explicit is not None else 0.0],
            dtype=np.float32,
        )
        boundary_by_frame, boundary_source, boundary_available, boundary_provenance = _boundary_features(
            record, h5, length_scale, manifest_path=manifest_path, solver_times=times
        )
        boundary_components = []
        sidecar_ref = (record.get("geometry") or {}).get("boundary_sidecar")
        if sidecar_ref is not None:
            sidecar_path = (manifest_path.parent / str(sidecar_ref)).resolve()
            boundary_components = _boundary_component_series(sidecar_path, times)
    if len(times) < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
        raise ValueError(f"invalid time axis in {record['case_id']}")
    dp = float(record["numerics"]["particle_spacing_m"])
    time_scale = float(np.sqrt(max(length_scale, dp) / max(abs(float(gravity[2])), 1e-6)))
    return {
        "case_id": record["case_id"],
        "family": record["family"],
        "split": record["split"],
        "background_id": record.get("lineage_group_id", record["case_id"]),
        "position": position,
        "velocity": velocity,
        "density0": density0,
        "pressure0": pressure0,
        "mass0": mass0,
        "time": times,
        "dp": dp,
        "length_scale": length_scale,
        "time_scale": time_scale,
        "gravity": gravity,
        "physics": physics,
        "controls": controls,
        "control_source": control_source,
        "control_available": control_available,
        "boundary": boundary_by_frame[0].copy(),
        "boundary_by_frame": boundary_by_frame,
        "boundary_source": boundary_source,
        "boundary_available": boundary_available,
        "boundary_provenance": boundary_provenance,
        "boundary_components": boundary_components,
        "boundary_component_feature_fields": list(BOUNDARY_COMPONENT_FEATURE_FIELDS),
        "gravity_source": gravity_source,
        "mass_initial_kg": float(np.sum(mass0)),
    }


def load_cases(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text())
    cases = []
    for record in manifest["cases"]:
        case = _load_case(manifest_path.resolve(), record)
        if case is not None:
            cases.append(case)
    return cases


def teacher_velocity(case: dict[str, Any], frame: int) -> np.ndarray:
    """Return the solver velocity used as the canonical state variable."""

    return case["velocity"][frame]


def _tensor(array: np.ndarray, device: torch.device) -> torch.Tensor:
    return torch.from_numpy(np.asarray(array, dtype=np.float32)).to(device)


def feature_width(cases: Any | None = None) -> int:
    # centered xyz, rollout-consistent velocity, initial density/pressure/mass,
    # gravity, static physics, prescribed control, current boundary summary,
    # family, elapsed time and current dt (both independent of final file
    # endpoint).  Keep the no-argument width for old custom checkpoints; the
    # actual sidecar-aware training path opts into the component block below.
    base = 3 + 3 + 3 + 3 + 3 + PHYSICS_WIDTH + CONTROL_WIDTH + BOUNDARY_WIDTH + 6 + 2
    if cases is None:
        return base
    if isinstance(cases, dict):
        cases = [cases]
    try:
        rich = any(bool(case.get("boundary_components")) for case in cases)
    except (TypeError, AttributeError):
        rich = False
    return base + MAX_BOUNDARY_COMPONENTS * BOUNDARY_COMPONENT_WIDTH if rich else base


def build_features(
    case: dict[str, Any],
    target_position: torch.Tensor,
    target_velocity: torch.Tensor,
    context_position: torch.Tensor,
    context_velocity: torch.Tensor,
    context_mass: torch.Tensor,
    frame: int,
    indices: np.ndarray,
    dt: float,
    device: torch.device,
) -> torch.Tensor:
    validate_model_input_contract(case)
    mass_total = torch.clamp(context_mass.sum(), min=1e-9)
    center = torch.sum(context_position * context_mass[:, None], dim=0, keepdim=True) / mass_total
    centered = (target_position - center) / max(case["length_scale"], 1e-9)
    velocity_scaled = target_velocity * float(dt) / case["dp"]
    center_velocity = torch.sum(context_velocity * context_mass[:, None], dim=0, keepdim=True) / mass_total
    center_velocity_scaled = center_velocity.expand_as(target_velocity) * float(dt) / case["dp"]
    density = _tensor(case["density0"][indices], device)
    pressure = _tensor(case["pressure0"][indices], device)
    mass = _tensor(case["mass0"][indices], device)
    rho_ref = float(case["physics"][0] * 1000.0)
    pressure_scale = max(rho_ref * max(abs(float(case["gravity"][2])), 1e-6) * case["length_scale"], 1e-6)
    state_scalars = torch.stack(
        ((density - rho_ref) / max(rho_ref, 1e-6), pressure / pressure_scale, mass / max(float(np.median(case["mass0"])), 1e-9) - 1.0),
        dim=-1,
    )
    gravity = _tensor(case["gravity"], device).expand_as(centered) * (float(dt) ** 2 / case["dp"])
    physics = _tensor(case["physics"], device).expand((len(target_position), PHYSICS_WIDTH))
    controls = _tensor(case["controls"][frame], device).clone()
    # Translation/velocity entries have physical units; angle and availability
    # entries are already dimensionless.  This same normalization is used in
    # training and rollout.
    controls[3:6] = controls[3:6] / max(case["length_scale"], 1e-9)
    controls[6:9] = controls[6:9] * case["time_scale"] / max(case["length_scale"], 1e-9)
    controls = controls.expand((len(target_position), CONTROL_WIDTH))
    boundary_by_frame = case.get("boundary_by_frame")
    if boundary_by_frame is None:
        boundary_values = case["boundary"]
    else:
        if not (0 <= int(frame) < len(boundary_by_frame)):
            raise IndexError(f"boundary summary frame {frame} is outside case frame axis")
        boundary_values = boundary_by_frame[int(frame)]
    boundary = _tensor(boundary_values, device).expand((len(target_position), BOUNDARY_WIDTH))
    component_values = None
    if case.get("boundary_components"):
        component_values = _boundary_component_features(
            case, frame, target_position.detach().cpu().numpy(), dt
        )
        component_tensor = _tensor(component_values.reshape(len(target_position), -1), device)
    else:
        component_tensor = None
    family = torch.zeros((len(target_position), 6), dtype=target_position.dtype, device=device)
    family[:, FAMILY_INDEX[case["family"]]] = 1.0
    elapsed = torch.full(
        (len(target_position), 1), float(case["time"][frame] / max(case["time_scale"], 1e-9)),
        dtype=target_position.dtype, device=device,
    )
    dt_feature = torch.full(
        (len(target_position), 1), float(dt / max(case["time_scale"], 1e-9)),
        dtype=target_position.dtype, device=device,
    )
    values = (centered, velocity_scaled, center_velocity_scaled, state_scalars, gravity,
              physics, controls, boundary)
    if component_tensor is not None:
        values = values + (component_tensor,)
    return torch.cat(values + (family, elapsed, dt_feature), dim=-1)


def local_neighbour_features(
    target_position: torch.Tensor,
    target_velocity: torch.Tensor,
    context_position: torch.Tensor,
    context_velocity: torch.Tensor,
    dp: float,
    dt: float,
) -> torch.Tensor:
    """Compute a fixed-size, permutation-invariant local interaction summary."""

    if context_position.numel() == 0:
        return torch.zeros((len(target_position), LOCAL_WIDTH), dtype=target_position.dtype, device=target_position.device)
    distances = torch.cdist(target_position, context_position)
    # Exclude exact self matches when training on a subset of the full context.
    distances = distances.masked_fill(distances < 1e-8, float("inf"))
    k = min(NEIGHBORS, context_position.shape[0])
    values, indices = torch.topk(distances, k=k, largest=False, dim=1)
    neighbours = context_position[indices]
    neighbour_velocity = context_velocity[indices]
    finite = torch.isfinite(values)
    weights = torch.where(finite, 1.0 / torch.clamp(values, min=1e-5), torch.zeros_like(values))
    weights = weights / torch.clamp(weights.sum(dim=1, keepdim=True), min=1e-8)
    relative_position = (neighbours - target_position[:, None, :]) / dp
    relative_velocity = (neighbour_velocity - target_velocity[:, None, :]) * float(dt) / dp
    mean_position = torch.sum(weights[..., None] * relative_position, dim=1)
    mean_velocity = torch.sum(weights[..., None] * relative_velocity, dim=1)
    mean_distance = torch.sum(torch.where(finite, values / dp, torch.zeros_like(values)), dim=1, keepdim=True) / max(k, 1)
    neighbour_fraction = torch.full(
        (len(target_position), 1), float(finite.sum(dim=1).float().mean().item() / max(context_position.shape[0], 1)),
        dtype=target_position.dtype, device=target_position.device,
    )
    return torch.cat((mean_position, mean_velocity, mean_distance, neighbour_fraction), dim=-1)


def _state_tensors(case: dict[str, Any], frame: int, indices: np.ndarray, device: torch.device):
    context_position = _tensor(case["position"][frame], device)
    # Keep the solver-provided velocity as the canonical state at every frame;
    # rollout replaces it only with the model's own predicted next velocity.
    context_velocity = _tensor(case["velocity"][frame], device)
    context_mass = _tensor(case["mass0"], device)
    target_position = context_position[indices]
    target_velocity = context_velocity[indices]
    return target_position, target_velocity, context_position, context_velocity, context_mass


def target_for(case: dict[str, Any], frame: int, indices: np.ndarray, route: str) -> torch.Tensor:
    dt = float(case["time"][frame + 1] - case["time"][frame])
    current_velocity = case["velocity"][frame, indices]
    next_velocity = case["velocity"][frame + 1, indices]
    if route == "physics_residual":
        acceleration = (next_velocity - current_velocity) / max(dt, 1e-9)
        return _tensor(acceleration * dt * dt / case["dp"], torch.device("cpu"))
    # Direct routes predict the next solver velocity, not a displacement.  The
    # rollout integrates that same state with a trapezoidal position update.
    return _tensor(next_velocity * dt / case["dp"], torch.device("cpu"))


def predict(model: nn.Module, route: str, base: torch.Tensor, local: torch.Tensor | None) -> torch.Tensor:
    # A smooth cap is part of the model definition, hence identical in train,
    # validation and rollout.  Saturation is reported per case below.
    raw = model(base, local)
    return OUTPUT_CAP * torch.tanh(raw / OUTPUT_CAP)


def raw_and_bounded_prediction(model: nn.Module, base: torch.Tensor, local: torch.Tensor | None) -> tuple[torch.Tensor, torch.Tensor]:
    raw = model(base, local)
    return raw, OUTPUT_CAP * torch.tanh(raw / OUTPUT_CAP)


def one_step_loss(model: nn.Module, route: str, case: dict[str, Any], frame: int, indices: np.ndarray, device: torch.device) -> torch.Tensor:
    dt = float(case["time"][frame + 1] - case["time"][frame])
    target_position, target_velocity, context_position, context_velocity, context_mass = _state_tensors(case, frame, indices, device)
    base = build_features(case, target_position, target_velocity, context_position, context_velocity, context_mass, frame, indices, dt, device)
    local = local_neighbour_features(target_position, target_velocity, context_position, context_velocity, case["dp"], dt) if route == "local_interaction" else None
    target = target_for(case, frame, indices, route).to(device)
    return torch.mean((predict(model, route, base, local) - target) ** 2)


@torch.no_grad()
def validation_rmse(model: nn.Module, route: str, cases: list[dict[str, Any]], device: torch.device, maximum: int) -> float:
    squared = 0.0
    count = 0
    for case in cases:
        for frame in range(len(case["time"]) - 1):
            n = len(case["position"][frame])
            indices = np.linspace(0, n - 1, min(maximum, n)).round().astype(int)
            dt = float(case["time"][frame + 1] - case["time"][frame])
            target_position, target_velocity, context_position, context_velocity, context_mass = _state_tensors(case, frame, indices, device)
            base = build_features(case, target_position, target_velocity, context_position, context_velocity, context_mass, frame, indices, dt, device)
            local = local_neighbour_features(target_position, target_velocity, context_position, context_velocity, case["dp"], dt) if route == "local_interaction" else None
            target = target_for(case, frame, indices, route).to(device)
            error = predict(model, route, base, local) - target
            squared += float(torch.sum(torch.sum(error * error, dim=-1)).item())
            count += int(error.shape[0])
    return float(np.sqrt(squared / max(count, 1)))


@torch.no_grad()
def validation_autonomous_rmse(model: nn.Module, route: str, cases: list[dict[str, Any]], device: torch.device, clip_dp: float) -> float:
    """Select checkpoints by the actual autonomous task, not teacher forcing."""

    values = []
    for case in cases:
        result = rollout(model, route, case, device, clip_dp)
        value = result.get("learned_rmse_over_dp")
        if result.get("status") == "completed" and value is not None and np.isfinite(value):
            values.append(float(value))
    return float(np.mean(values)) if values else float("inf")


def _metric(errors: list[np.ndarray], scale: float = 1.0) -> tuple[float | None, float | None, float | None]:
    norms = [np.linalg.norm(error, axis=1) for error in errors]
    all_norms = np.concatenate(norms) if norms else np.empty(0, dtype=np.float64)
    rmse = float(np.sqrt(np.mean(all_norms * all_norms)) / scale) if len(all_norms) else None
    ade = float(np.mean(all_norms)) if len(all_norms) else None
    fde = float(np.mean(norms[-1])) if norms else None
    return rmse, ade, fde


@torch.no_grad()
def rollout(model: nn.Module, route: str, case: dict[str, Any], device: torch.device, clip_dp: float) -> dict[str, Any]:
    position = _tensor(case["position"][0], device)
    velocity_state = _tensor(case["velocity"][0], device)
    learned_errors: list[np.ndarray] = []
    constant_errors: list[np.ndarray] = []
    learned_velocity_errors: list[np.ndarray] = []
    constant_velocity_errors: list[np.ndarray] = []
    learned_com_errors: list[np.ndarray] = []
    constant_com_errors: list[np.ndarray] = []
    constant_position = position.clone()
    constant_velocity = velocity_state.clone()
    clipped_components = 0
    total_components = 0
    saturated_components = 0
    total_outputs = 0
    max_raw = 0.0
    mass = _tensor(case["mass0"], device)
    mass_total = torch.clamp(mass.sum(), min=1e-9)
    status = "completed"
    for frame, dt_value in enumerate(np.diff(case["time"])):
        dt = float(dt_value)
        indices = np.arange(len(position), dtype=np.int64)
        base = build_features(case, position, velocity_state, position, velocity_state, mass, frame, indices, dt, device)
        local = local_neighbour_features(position, velocity_state, position, velocity_state, case["dp"], dt) if route == "local_interaction" else None
        raw, bounded = raw_and_bounded_prediction(model, base, local)
        if not torch.isfinite(raw).all():
            status = "nonfinite_prediction"
            break
        total_outputs += int(raw.numel())
        saturated_components += int((torch.abs(raw) > OUTPUT_CAP).sum().item())
        max_raw = max(max_raw, float(torch.max(torch.abs(raw)).item()))
        if route == "physics_residual":
            acceleration = bounded * case["dp"] / max(dt * dt, 1e-12)
            next_velocity = velocity_state + acceleration * dt
        else:
            next_velocity = bounded * case["dp"] / max(dt, 1e-12)
        displacement = 0.5 * (velocity_state + next_velocity) * dt
        normalized = displacement / case["dp"]
        total_components += int(normalized.numel())
        if clip_dp > 0:
            clipped = torch.abs(normalized) > clip_dp
            clipped_components += int(clipped.sum().item())
            normalized = torch.clamp(normalized, -clip_dp, clip_dp)
            displacement = normalized * case["dp"]
        velocity_state = next_velocity
        position = position + displacement
        constant_position = constant_position + constant_velocity * dt
        reference = _tensor(case["position"][frame + 1], device)
        reference_velocity = _tensor(case["velocity"][frame + 1], device)
        learned_errors.append((position - reference).cpu().numpy())
        constant_errors.append((constant_position - reference).cpu().numpy())
        learned_velocity_errors.append((velocity_state - reference_velocity).cpu().numpy())
        constant_velocity_errors.append((constant_velocity - reference_velocity).cpu().numpy())
        learned_com = torch.sum(position * mass[:, None], dim=0) / mass_total
        constant_com = torch.sum(constant_position * mass[:, None], dim=0) / mass_total
        reference_com = torch.sum(reference * mass[:, None], dim=0) / mass_total
        learned_com_errors.append((learned_com - reference_com)[None].cpu().numpy())
        constant_com_errors.append((constant_com - reference_com)[None].cpu().numpy())
    learned_rmse, learned_ade, learned_fde = _metric(learned_errors, case["dp"])
    constant_rmse, constant_ade, constant_fde = _metric(constant_errors, case["dp"])
    learned_velocity_rmse, learned_velocity_ade, learned_velocity_fde = _metric(learned_velocity_errors)
    constant_velocity_rmse, constant_velocity_ade, constant_velocity_fde = _metric(constant_velocity_errors)
    learned_com_rmse, learned_com_ade, learned_com_fde = _metric(learned_com_errors)
    constant_com_rmse, constant_com_ade, constant_com_fde = _metric(constant_com_errors)
    return {
        "case_id": case["case_id"], "family": case["family"], "background_id": case["background_id"],
        "split": case["split"], "frames_predicted": len(learned_errors), "frames_expected": len(case["time"]) - 1,
        "particles": len(case["position"][0]), "status": status,
        "learned_rmse_over_dp": learned_rmse, "learned_ade_m": learned_ade, "learned_fde_m": learned_fde,
        "constant_velocity_rmse_over_dp": constant_rmse, "constant_velocity_ade_m": constant_ade,
        "constant_velocity_fde_m": constant_fde,
        "learned_velocity_rmse_mps": learned_velocity_rmse, "learned_velocity_ade_mps": learned_velocity_ade,
        "learned_velocity_fde_mps": learned_velocity_fde, "constant_velocity_rmse_mps": constant_velocity_rmse,
        "constant_velocity_ade_mps": constant_velocity_ade, "constant_velocity_fde_mps": constant_velocity_fde,
        "learned_com_rmse_m": learned_com_rmse, "learned_com_ade_m": learned_com_ade,
        "learned_com_fde_m": learned_com_fde, "constant_com_rmse_m": constant_com_rmse,
        "constant_com_ade_m": constant_com_ade, "constant_com_fde_m": constant_com_fde,
        "clip_dp": clip_dp,
        "clipped_component_count": clipped_components,
        "clipping_component_count": total_components,
        "clipped_component_fraction": float(clipped_components / max(total_components, 1)),
        "clipping_trigger_rate": float(clipped_components / max(total_components, 1)),
        "clipping_triggered": bool(clipped_components),
        "output_saturation_count": saturated_components,
        "output_component_count": total_outputs,
        "output_saturation_fraction": float(saturated_components / max(total_outputs, 1)),
        "output_saturation_triggered": bool(saturated_components),
        "max_raw_model_output": max_raw,
        "control_source": case["control_source"], "boundary_source": case["boundary_source"],
        "boundary_available": case["boundary_available"], "boundary_provenance": case.get("boundary_provenance"),
        "mass_initial_kg": case["mass_initial_kg"],
        "mass_identity_preserved": status == "completed",
    }


def train(args: argparse.Namespace) -> dict[str, Any]:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)
        torch.cuda.reset_peak_memory_stats(device)
    cases = load_cases(args.manifest.resolve())
    train_cases = [case for case in cases if case["split"] == "train"]
    validation_cases = [case for case in cases if case["split"] == "validation"]
    test_cases = [case for case in cases if case["split"] == "test"]
    if not train_cases or not validation_cases or not test_cases:
        raise ValueError("manifest must contain train, validation and test fluid cases")
    model_input_width = feature_width(cases)
    model = model_for(args.route, model_input_width, args.hidden).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-6)
    rng = np.random.default_rng(args.seed)
    transitions = [(case, frame) for case in train_cases for frame in range(len(case["time"]) - 1)]
    history: list[dict[str, Any]] = []
    best_validation = float("inf")
    best_epoch = 0
    stale_epochs = 0
    start = time.perf_counter()
    for epoch in range(args.epochs):
        rng.shuffle(transitions)
        losses = []
        model.train()
        for case, frame in transitions:
            count = len(case["position"][frame])
            indices = rng.choice(count, min(args.max_particles, count), replace=False)
            optimizer.zero_grad(set_to_none=True)
            loss = one_step_loss(model, args.route, case, frame, indices, device)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.item()))
        model.eval()
        val = validation_rmse(model, args.route, validation_cases, device, args.validation_particles)
        val_autonomous = validation_autonomous_rmse(model, args.route, validation_cases, device, args.clip_dp)
        row = {
            "epoch": epoch + 1, "train_mse": float(np.mean(losses)),
            "validation_one_step_vector_rmse_over_dp": val,
            "validation_autonomous_rmse_over_dp": val_autonomous,
        }
        history.append(row)
        print(json.dumps({"route": args.route, "seed": args.seed, **row}), flush=True)
        if val_autonomous < best_validation - args.min_delta:
            best_validation = val_autonomous
            best_epoch = epoch + 1
            stale_epochs = 0
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            stale_epochs += 1
        if epoch + 1 >= args.min_epochs and stale_epochs >= args.patience:
            break
    if best_epoch:
        model.load_state_dict(best_state)
    training_seconds = time.perf_counter() - start
    model.eval()
    rollout_start = time.perf_counter()
    test_rollouts = {case["case_id"]: rollout(model, args.route, case, device, args.clip_dp) for case in test_cases}
    inference_seconds = time.perf_counter() - rollout_start
    result = {
        "schema_version": 2, "scope": "R3-G4 corrected development baseline", "route": args.route, "seed": args.seed,
        "device": str(device), "torch_version": torch.__version__,
        "cuda_visible_device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "feature_width": model_input_width, "epochs_requested": args.epochs, "epochs_run": len(history),
        "best_epoch": best_epoch, "best_validation_autonomous_rmse_over_dp": best_validation,
        "early_stopping": {"patience": args.patience, "min_epochs": args.min_epochs, "min_delta": args.min_delta},
        "maximum_particles_per_training_frame": args.max_particles,
        "validation_particles": args.validation_particles, "training_transition_frames": len(transitions),
        "training_seconds": training_seconds, "inference_seconds": inference_seconds,
        "peak_gpu_memory_bytes": int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0,
        "history": history, "test_rollout": test_rollouts,
        "input_contract": {
            "centering": "initial-mass-weighted COM of complete current particle context in both train and rollout",
            "velocity_state": "solver velocity at every teacher-forced frame; rollout starts from frame-zero solver velocity and then uses predicted next velocity",
            "time": "elapsed physical time divided by sqrt(length_scale/|g|); no division by file endpoint",
            "initial_only_state": ["density", "pressure", "mass"],
            "known_control": "current prescribed control schedule only; frame-zero derived translational velocity is zero, prescribed angular velocity is accepted directly, and no future free-body state is read",
            "prefix_invariance": "shared-prefix rollout inputs use only current predicted state, current control, current boundary summary, and elapsed time; future reference frames are not consumed",
            "boundary_geometry": "current-frame finite-triangle world-space AABB plus per-component distance, normal, type, and wall velocity from linked boundary-sidecar-v1; records without a sidecar use an explicit legacy fallback",
            "boundary_component_features": list(BOUNDARY_COMPONENT_FEATURE_FIELDS),
            "boundary_component_padding": MAX_BOUNDARY_COMPONENTS,
            "motion_interpolation": "rigid pose or analytic control only; no world-space vertex lerp",
            "prohibited_rollout_inputs": ["future reference position", "future reference velocity", "future reference density", "future free-body trajectory"],
        },
        "metric_definition": "vector RMSE = sqrt(mean(||error_xyz||^2)) / dp; ADE/FDE are mean vector norms; velocity and COM metrics use the same vector convention",
        "output_cap": {"kind": "smooth_tanh", "cap": OUTPUT_CAP, "saturation_rate_reported_per_case": True},
        "clipping": {"configured_clip_dp": args.clip_dp, "trigger_rate_reported_per_case": True, "note": "optional displacement clip is off in the declared run; smooth output cap is applied consistently in train/validation/rollout"},
        "physics_budget_scope": "diagnostic only: identity mass is preserved by construction; density/pressure are not predicted",
        "limitations": "W11 development pilot; sidecar geometry is a finite per-component candidate input and T2/T3/T4 scoring is not included; not a formal ranking or physical acceptance",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "route": args.route, "seed": args.seed, "feature_width": model_input_width}, args.checkpoint)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--route", choices=ROUTES, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--min-epochs", type=int, default=6)
    parser.add_argument("--patience", type=int, default=4)
    parser.add_argument("--min-delta", type=float, default=1e-5)
    parser.add_argument("--max-particles", type=int, default=256)
    parser.add_argument("--validation-particles", type=int, default=512)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--clip-dp", type=float, default=0.0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
