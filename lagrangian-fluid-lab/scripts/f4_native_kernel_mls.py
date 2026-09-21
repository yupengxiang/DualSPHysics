"""Independent F4 native-kernel MLS material reconstruction.

This module is a research backend for the F4 resting-pool family.  It is
deliberately separate from :mod:`scripts.core_material` and has no T1/T2
qualification status.  The only state which can enter a reconstruction is a
single, explicitly selected current native frame:

``position, velocity, mass, density, valid, fluid mask``.

The model does not read a later frame, a predicted density, or a solver
particle identity.  A source particle contributes its native volume
``mass / density`` multiplied by the normalised three-dimensional quintic
Wendland kernel.  A weighted affine moving-least-squares fit then evaluates
the velocity at the query.  Support is the complete compact kernel ball; it
is not a nearest-neighbour or Shepard-distance cap.

The official DualSPHysics run records bind the kernel name and cite Wendland
(1995), DOI ``10.1007/BF02123482``.  The 3-D normalisation below is also
numerically checked against the official F4 run record (``awen=245355.2`` at
``h=0.011941``).  The formula is recorded in every result/spec so a later
backend cannot silently change it.

Only CPU work is performed here.  No campaign ledger, slot, or GPU is
accessed by the module.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import time
from typing import Callable, Iterable, Mapping, Sequence

import h5py
import numpy as np
from scipy.spatial import cKDTree


SCHEMA = "core.material.f4.native_kernel_mls.v1"
BACKEND = "f4_native_kernel_mls_wendland_mass_density_v1"
QUALIFICATION_CLAIM = "none"

# The temporal material tracer is versioned separately from the static MLS
# reconstruction.  A trace is therefore comparable and resumable without
# changing the meaning of an older manufactured or dense-frame receipt.
TRACE_SCHEMA = "core.material.f4.native_kernel_mls.trace.v1"
TRACE_BACKEND = "f4_native_kernel_mls_causal_current_volume_rk4_v1"
# v2 uses content-addressed generation files.  The old v1 fixed-name NPZ
# remains readable only through its already-written receipt; new traces never
# overwrite the generation named by their last published manifest.
TRACE_CHECKPOINT_SCHEMA = "core.material.f4.native_kernel_mls.checkpoint.v2"
TRACE_CHECKPOINT_FIELDS = (
    "position", "permanent_unknown", "contact_time", "upward_time",
    "return_time", "residence_s", "contacted", "upward", "returned",
    "residual_estimate_mps", "error_upper_bound_mps",
    "path_error_estimate_m", "path_error_budget_m",
)
TRACE_HISTORY_FIELDS = (
    "time", "position", "reliable", "permanent_unknown", "destination_member",
    "contact_time", "upward_time", "return_time", "residence_s",
    "contacted", "upward", "returned", "event_status",
    "residual_estimate_mps", "error_upper_bound_mps",
    "path_error_estimate_m", "path_error_budget_m",
    "unknown_mass", "reliable_mass", "contact_mass", "upward_mass",
    "return_mass", "destination_mass", "mass_closure_error",
)
TRACE_EVENT_DEFINITION = {
    "interface_plane_z_m": 0.18,
    "contact": "continuous downward crossing from z>plane to z<=plane on a usable RK4 segment",
    "upward": "continuous upward crossing after contact from z<=plane to z>plane",
    "return": "continuous downward crossing after upward event from z>plane to z<=plane",
    "destination": "closed box low=[0,0,0], high=[1.2,0.4,0.18] m",
    "residence": "linear RK segment time inside destination box after contact; right-censored if no return",
    "unusable_segment": "no event update; query becomes permanent_unknown",
}

WENDLAND_FORMULA = {
    "family": "quintic_wendland_c2",
    "source": "Wendland 1995, Piecewise polynomial, positive definite and compactly supported radial functions of minimal degree",
    "doi": "10.1007/BF02123482",
    "official_run_binding": "DualSPHysics Run.out: Kernel=\"Wendland\"; Kernel: Quintic Wendland",
    "official_run_path": "campaigns/core-v1/runtime/attempts/f4-resting-pool-qualification-cell-14/20260919T184548-9bb5d3e36d4b/product/solver/Run.out",
    "official_run_3d_awen": 245355.2,
    "official_run_h_rounded_m": 0.011941,
    "dimension": 3,
    "argument": "q=r/h",
    "support": "0 <= q <= 2",
    "expression": "W(r,h)=21/(16*pi*h^3)*(1-q/2)^4*(1+2*q)",
    "normalisation": "21/(16*pi*h^3)",
    "outside_support": 0.0,
}

INPUT_POLICY = {
    "public_current_inputs": ["position", "velocity", "mass", "density", "valid", "fluid_mask"],
    "density_mode": "native_current_only",
    "density_source": "same selected H5 frame; no predicted or future density",
    "mass_source": "same selected H5 frame",
    "future_state": "forbidden",
    "native_particle_id": "not used for query identity or termination",
    "model_density_estimation": "not implemented; a future estimator requires a new backend version",
}

# These are numerical support checks owned by this backend.  They are not the
# old F3/F4 reconstruction gate and are not a T2 qualification rule.
MLS_GATE = {
    "minimum_support_count": 4,
    "minimum_effective_sample_size": 4.0,
    "minimum_geometry_rank": 4,
    "maximum_condition_number": 1.0e10,
    "svd_relative_cutoff": 1.0e-12,
}
MANUFACTURED_ERROR_TOLERANCE_MPS = 1.0e-9
CONNECTIVITY_DIAGNOSTIC = {
    "backend": "f4_native_support_connectivity_diagnostic_v1",
    "purpose": "current-support connectivity and velocity-branch evidence; diagnostic only",
    "edge_radius": "1.5*dp_m",
    "source_labels": "not read; no initial Mk/particle-id partition",
    "ambiguity_rule": "branch separation >= 2*within RMS and >= 0.05 m/s, or >=2 current components",
    "gate_effect": "none",
}

F4_DP_M = 0.0075
F4_H_M = 0.011941277883
F4_SOURCE_SIZE_M = np.array([0.26, 0.16, 0.14], dtype=np.float64)
F4_SOURCE_LOW_Q05_M = np.array([0.36, 0.12, 0.40], dtype=np.float64)
F4_DESTINATION_LOW_M = np.array([0.0, 0.0, 0.0], dtype=np.float64)
F4_DESTINATION_HIGH_M = np.array([1.2, 0.4, 0.6], dtype=np.float64)

DENSE_SOURCE_H5 = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/runtime/attempts/"
    "f4-resting-pool-native-dense-002-canary-s0p3-center-q0p5/"
    "20260919T185855-d91665790347/product/trajectory.h5"
)
DENSE_PREPARED_XML = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/prepared/"
    "F4_resting_pool_center_native_dense_002_canary/generated/"
    "F4_RESTING_POOL_CENTER_NATIVE_DENSE_002_CANARY.xml"
)


def sha256_file(path: str | Path) -> str:
    """Hash a file in bounded chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _array_hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for value in arrays:
        array = np.ascontiguousarray(np.asarray(value))
        digest.update(_canonical({"dtype": array.dtype.str, "shape": array.shape}).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def _json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _finite_vector(name: str, value, shape: tuple[int, ...]) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite with shape {shape}")
    return np.array(array, dtype=np.float64, copy=True)


def _read_frame_array(dataset, index: int, name: str) -> np.ndarray:
    if dataset.ndim < 1:
        raise ValueError(f"{name} must have a frame dimension")
    if index < 0 or index >= dataset.shape[0]:
        raise IndexError(f"frame index {index} is outside {name} with {dataset.shape[0]} frames")
    return np.asarray(dataset[index])


class NativeCurrentFrame:
    """Immutable arrays for one current native solver frame.

    Invalid rows may carry solver padding values and are excluded by ``valid``
    and ``fluid_mask``.  Every selected row still has to contain finite,
    positive mass and density; silently replacing either with a model estimate
    would violate the input contract.
    """

    __slots__ = (
        "position", "velocity", "mass", "density", "valid", "fluid_mask",
        "source_row", "frame_index", "time_s", "source_path", "source_sha256",
    )

    def __init__(
        self,
        position,
        velocity,
        mass,
        density,
        *,
        valid=None,
        fluid_mask=None,
        frame_index: int | None = None,
        time_s: float | None = None,
        source_path: str | None = None,
        source_sha256: str | None = None,
    ):
        position = np.asarray(position, dtype=np.float64)
        velocity = np.asarray(velocity, dtype=np.float64)
        mass = np.asarray(mass, dtype=np.float64)
        density = np.asarray(density, dtype=np.float64)
        if position.ndim != 2 or position.shape[1:] != (3,):
            raise ValueError("position must have shape [N,3]")
        n = len(position)
        if velocity.shape != (n, 3):
            raise ValueError("velocity must have shape [N,3]")
        if mass.shape != (n,) or density.shape != (n,):
            raise ValueError("mass and density must have shape [N]")
        if valid is None:
            valid = np.ones(n, dtype=bool)
        else:
            valid = np.asarray(valid, dtype=bool)
            if valid.shape != (n,):
                raise ValueError("valid must have shape [N]")
        if fluid_mask is None:
            fluid_mask = np.ones(n, dtype=bool)
        else:
            fluid_mask = np.asarray(fluid_mask, dtype=bool)
            if fluid_mask.shape != (n,):
                raise ValueError("fluid_mask must have shape [N]")
        selected = valid & fluid_mask
        if not np.any(selected):
            raise ValueError("current frame contains no valid fluid rows")
        for name, array in (("position", position), ("velocity", velocity),
                            ("mass", mass), ("density", density)):
            if not np.isfinite(array[selected]).all():
                raise ValueError(f"selected current {name} contains nonfinite values")
        if np.any(mass[selected] <= 0.0) or np.any(density[selected] <= 0.0):
            raise ValueError("selected current mass and density must be positive")
        if frame_index is not None and (isinstance(frame_index, bool) or int(frame_index) != frame_index or frame_index < 0):
            raise ValueError("frame_index must be a nonnegative integer")
        if time_s is not None and not np.isfinite(float(time_s)):
            raise ValueError("time_s must be finite")
        self.position = np.array(position, dtype=np.float64, copy=True)
        self.velocity = np.array(velocity, dtype=np.float64, copy=True)
        self.mass = np.array(mass, dtype=np.float64, copy=True)
        self.density = np.array(density, dtype=np.float64, copy=True)
        self.valid = np.array(valid, dtype=bool, copy=True)
        self.fluid_mask = np.array(fluid_mask, dtype=bool, copy=True)
        self.source_row = np.flatnonzero(selected).astype(np.int64)
        self.frame_index = None if frame_index is None else int(frame_index)
        self.time_s = None if time_s is None else float(time_s)
        self.source_path = None if source_path is None else str(source_path)
        self.source_sha256 = source_sha256
        for name in ("position", "velocity", "mass", "density", "valid", "fluid_mask", "source_row"):
            getattr(self, name).setflags(write=False)

    @property
    def fluid_position(self) -> np.ndarray:
        return self.position[self.source_row]

    @property
    def fluid_velocity(self) -> np.ndarray:
        return self.velocity[self.source_row]

    @property
    def fluid_mass(self) -> np.ndarray:
        return self.mass[self.source_row]

    @property
    def fluid_density(self) -> np.ndarray:
        return self.density[self.source_row]

    @property
    def fluid_volume(self) -> np.ndarray:
        return self.fluid_mass / self.fluid_density


class NativeCurrentFrameProvider:
    """Read one explicitly selected H5 frame, with no future-state API."""

    REQUIRED_DATASETS = ("position", "velocity", "mass", "density", "valid")

    def __init__(self, source: str | Path, *, fluid_type: int | None = 3, type_dataset: str = "type"):
        self.source = Path(source)
        self.fluid_type = fluid_type
        self.type_dataset = str(type_dataset)
        if not self.source.exists():
            raise FileNotFoundError(self.source)
        self.source_sha256 = sha256_file(self.source)

    def read_current(self, frame_index: int = 0) -> NativeCurrentFrame:
        """Return only the selected frame and close the HDF5 handle."""
        with h5py.File(self.source, "r") as handle:
            missing = [name for name in self.REQUIRED_DATASETS if name not in handle]
            if missing:
                raise ValueError(f"native source is missing required datasets: {missing}")
            index = int(frame_index)
            position = _read_frame_array(handle["position"], index, "position")
            velocity = _read_frame_array(handle["velocity"], index, "velocity")
            mass = _read_frame_array(handle["mass"], index, "mass")
            density = _read_frame_array(handle["density"], index, "density")
            valid = _read_frame_array(handle["valid"], index, "valid")
            if self.fluid_type is None:
                fluid_mask = np.ones(len(position), dtype=bool)
            else:
                if self.type_dataset not in handle:
                    raise ValueError(f"fluid_type={self.fluid_type} requires dataset {self.type_dataset!r}")
                particle_type = _read_frame_array(handle[self.type_dataset], index, self.type_dataset)
                if particle_type.shape != (len(position),):
                    raise ValueError(f"{self.type_dataset} must have shape [N] per frame")
                fluid_mask = particle_type == self.fluid_type
            time_s = None
            if "time" in handle:
                times = np.asarray(handle["time"])
                if times.ndim != 1 or index >= len(times):
                    raise ValueError("time must be one-dimensional and cover selected frame")
                time_s = float(times[index])
        return NativeCurrentFrame(
            position, velocity, mass, density, valid=valid, fluid_mask=fluid_mask,
            frame_index=index, time_s=time_s, source_path=str(self.source),
            source_sha256=self.source_sha256,
        )

    def current_times(self) -> np.ndarray:
        """Read only the public time coordinate, never a future field."""
        with h5py.File(self.source, "r") as handle:
            if "time" not in handle:
                raise ValueError("native source is missing the time coordinate")
            times = np.asarray(handle["time"], dtype=np.float64)
        if times.ndim != 1 or len(times) == 0 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0.0):
            raise ValueError("time must be finite, one-dimensional, and strictly increasing")
        times.setflags(write=False)
        return times


def wendland_quintic_c2_3d(distance, h: float) -> np.ndarray:
    """Evaluate the normalised 3-D quintic Wendland kernel."""
    h = float(h)
    if not np.isfinite(h) or h <= 0.0:
        raise ValueError("h must be finite and positive")
    distance = np.asarray(distance, dtype=np.float64)
    if not np.isfinite(distance).all() or np.any(distance < 0.0):
        raise ValueError("distance must be finite and nonnegative")
    q = distance / h
    inside = q <= 2.0
    t = np.maximum(1.0 - 0.5 * q, 0.0)
    value = (21.0 / (16.0 * np.pi * h**3)) * t**4 * (1.0 + 2.0 * q)
    return np.where(inside, value, 0.0)


def wendland_normalisation_3d(h: float) -> float:
    h = float(h)
    if not np.isfinite(h) or h <= 0.0:
        raise ValueError("h must be finite and positive")
    return 21.0 / (16.0 * np.pi * h**3)


def _validate_walls(walls) -> np.ndarray:
    if walls is None:
        return np.empty((0, 3, 3), dtype=np.float64)
    value = np.asarray(walls, dtype=np.float64)
    if value.size == 0:
        return np.empty((0, 3, 3), dtype=np.float64)
    if value.ndim != 3 or value.shape[1:] != (3, 3) or not np.isfinite(value).all():
        raise ValueError("walls must be finite triangles with shape [T,3,3]")
    return np.array(value, dtype=np.float64, copy=True)


def _segment_hits_triangle(query: np.ndarray, points: np.ndarray, triangle: np.ndarray) -> np.ndarray:
    """Moller-Trumbore segment/triangle test for one query and many endpoints."""
    if len(points) == 0:
        return np.empty(0, dtype=bool)
    edge1 = triangle[1] - triangle[0]
    edge2 = triangle[2] - triangle[0]
    direction = points - query[None, :]
    pvec = np.cross(direction, edge2[None, :])
    determinant = np.einsum("j,ij->i", edge1, pvec)
    scale = max(1.0, float(np.linalg.norm(edge1) * np.linalg.norm(edge2)))
    tolerance = 32.0 * np.finfo(np.float64).eps * scale
    nonparallel = np.abs(determinant) > tolerance
    inverse = np.zeros_like(determinant)
    inverse[nonparallel] = 1.0 / determinant[nonparallel]
    offset = query[None, :] - triangle[0][None, :]
    u = inverse * np.einsum("ij,ij->i", offset, pvec)
    qvec = np.cross(offset, edge1[None, :])
    v = inverse * np.einsum("ij,ij->i", direction, qvec)
    t = inverse * np.einsum("j,ij->i", edge2, qvec)
    # Endpoints on a wall are retained.  Only a proper interior crossing is
    # blocked, which is the useful rule for an open finite triangle set.
    endpoint_tolerance = 64.0 * np.finfo(np.float64).eps
    return (
        nonparallel
        & (u >= -endpoint_tolerance)
        & (v >= -endpoint_tolerance)
        & (u + v <= 1.0 + endpoint_tolerance)
        & (t > endpoint_tolerance)
        & (t < 1.0 - endpoint_tolerance)
    )


def _visible_endpoints(query: np.ndarray, points: np.ndarray, walls: np.ndarray) -> np.ndarray:
    if len(walls) == 0 or len(points) == 0:
        return np.ones(len(points), dtype=bool)
    blocked = np.zeros(len(points), dtype=bool)
    for triangle in walls:
        blocked |= _segment_hits_triangle(query, points, triangle)
    return ~blocked


def _union_find_component_count(points: np.ndarray, radius: float) -> int:
    """Count local geometric components without using solver/source labels."""
    if len(points) == 0:
        return 0
    parent = np.arange(len(points), dtype=np.int64)

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = int(parent[value])
        return value

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            return
        if root_left < root_right:
            parent[root_right] = root_left
        else:
            parent[root_left] = root_right

    tree = cKDTree(points)
    for left, right in tree.query_pairs(radius, p=2.0, eps=0.0, output_type="set"):
        union(int(left), int(right))
    return len({find(int(index)) for index in range(len(points))})


def _two_branch_velocity_diagnostic(values: np.ndarray) -> tuple[float, float, int]:
    """Return 2-means branch separation, within RMS, and usable branch count."""
    if len(values) < 8 or not np.isfinite(values).all():
        return math.nan, math.nan, 0
    values = np.asarray(values, dtype=np.float64)
    centered = values - np.mean(values, axis=0)
    _, _, vectors = np.linalg.svd(centered, full_matrices=False)
    axis = vectors[0] if len(vectors) else np.array([1.0, 0.0, 0.0])
    projection = values @ axis
    centers = np.array([np.min(projection), np.max(projection)], dtype=np.float64)
    for _ in range(12):
        assignment = np.abs(projection[:, None] - centers[None, :]).argmin(axis=1)
        if np.all(assignment == assignment[0]):
            return math.nan, math.nan, 0
        updated = np.array([
            np.mean(projection[assignment == group]) if np.any(assignment == group) else centers[group]
            for group in (0, 1)
        ])
        if np.allclose(updated, centers, rtol=0.0, atol=1.0e-14):
            centers = updated
            break
        centers = updated
    sizes = np.bincount(assignment, minlength=2)
    if np.any(sizes < 4):
        return math.nan, math.nan, 0
    separation = float(np.linalg.norm(np.mean(values[assignment == 0], axis=0) - np.mean(values[assignment == 1], axis=0)))
    within = values.copy()
    for group in (0, 1):
        within[assignment == group] -= np.mean(values[assignment == group], axis=0)
    rms = float(np.sqrt(np.mean(np.sum(within * within, axis=1))))
    return separation, rms, 2


def support_connectivity_diagnostic(
    query,
    frame: NativeCurrentFrame,
    *,
    h: float,
    dp_m: float,
    walls=None,
) -> dict[str, np.ndarray]:
    """Inspect current compact supports for disconnected geometry/velocity branches.

    This is evidence only.  It never changes MLS support, reliability, or
    query identity.  Components are found from current particle positions
    using a public ``1.5*dp_m`` graph radius; no initial source label or
    solver particle id is read.
    """
    if not np.isfinite(float(dp_m)) or float(dp_m) <= 0.0:
        raise ValueError("dp_m must be finite and positive")
    query = np.asarray(query, dtype=np.float64)
    if query.ndim != 2 or query.shape[1:] != (3,) or not np.isfinite(query).all():
        raise ValueError("query must be finite with shape [Q,3]")
    triangles = _validate_walls(walls)
    points = frame.fluid_position
    values = frame.fluid_velocity
    tree = cKDTree(points)
    component_count = np.zeros(len(query), dtype=np.int64)
    candidate_count = np.zeros(len(query), dtype=np.int64)
    visible_count = np.zeros(len(query), dtype=np.int64)
    distance_gap = np.full(len(query), np.nan, dtype=np.float64)
    branch_separation = np.full(len(query), np.nan, dtype=np.float64)
    branch_within_rms = np.full(len(query), np.nan, dtype=np.float64)
    branch_count = np.zeros(len(query), dtype=np.int8)
    edge_radius = 1.5 * float(dp_m)
    for row, pool in enumerate(tree.query_ball_point(query, r=2.0 * float(h), eps=0.0, workers=1, return_sorted=True)):
        candidate = np.asarray(pool, dtype=np.int64)
        candidate_count[row] = len(candidate)
        if len(candidate) == 0:
            continue
        visible = _visible_endpoints(query[row], points[candidate], triangles)
        candidate = candidate[visible]
        visible_count[row] = len(candidate)
        if len(candidate) == 0:
            continue
        local_points = points[candidate]
        local_values = values[candidate]
        component_count[row] = _union_find_component_count(local_points, edge_radius)
        distances = np.linalg.norm(local_points - query[row], axis=1)
        if len(distances) > 1:
            ordered = np.sort(distances)
            distance_gap[row] = float(np.max(np.diff(ordered)))
        branch_separation[row], branch_within_rms[row], branch_count[row] = _two_branch_velocity_diagnostic(local_values)
    return {
        "component_count": component_count,
        "candidate_count": candidate_count,
        "visible_count": visible_count,
        "distance_gap_max_m": distance_gap,
        "velocity_branch_separation_mps": branch_separation,
        "velocity_branch_within_rms_mps": branch_within_rms,
        "velocity_branch_count": branch_count,
        "connectivity_edge_radius_m": np.asarray(edge_radius),
    }


def reconstruction_error_budget(
    reconstruction: ReconstructionResult,
    *,
    hessian_bound_mps_per_m2: float | None = None,
    velocity_branch_separation_mps=None,
    velocity_branch_within_rms_mps=None,
    support_component_count=None,
) -> dict[str, np.ndarray]:
    """Return explicit error evidence without turning it into reliability.

    For a smooth manufactured field with a supplied Hessian norm bound ``H``,
    the reported Taylor remainder is ``0.5*H*mu2`` and is multiplied by the
    measured local condition amplification.  It is a conditional analytic
    bound: callers must bind ``H`` to the stated field/domain.  A support with
    two current velocity branches gets an ambiguity lower bound of half the
    branch separation; this is a discontinuity diagnostic, not an estimate of
    one hidden interface truth.
    """
    diagnostics = reconstruction.diagnostics
    residual = np.asarray(diagnostics["weighted_reconstruction_error_mps"], dtype=np.float64)
    moment2 = np.asarray(diagnostics["weighted_second_moment_m2"], dtype=np.float64)
    condition = np.asarray(diagnostics["condition_number"], dtype=np.float64)
    amplification = np.maximum(1.0, np.where(np.isfinite(condition), condition, np.inf))
    if hessian_bound_mps_per_m2 is None:
        smooth_upper = np.full(len(residual), np.nan, dtype=np.float64)
        bound_status = "no_analytic_hessian_bound_supplied"
    else:
        hessian = float(hessian_bound_mps_per_m2)
        if not np.isfinite(hessian) or hessian < 0.0:
            raise ValueError("hessian_bound_mps_per_m2 must be finite and nonnegative")
        smooth_upper = 0.5 * hessian * moment2 * amplification
        bound_status = "conditional_taylor_remainder_with_measured_condition_amplification"
    if velocity_branch_separation_mps is None:
        branch_lower = np.zeros(len(residual), dtype=np.float64)
    else:
        branch = np.asarray(velocity_branch_separation_mps, dtype=np.float64)
        if branch.shape != (len(residual),):
            raise ValueError("velocity_branch_separation_mps must have shape [Q]")
        if velocity_branch_within_rms_mps is None:
            within = np.full(len(residual), np.nan, dtype=np.float64)
        else:
            within = np.asarray(velocity_branch_within_rms_mps, dtype=np.float64)
            if within.shape != (len(residual),):
                raise ValueError("velocity_branch_within_rms_mps must have shape [Q]")
        if support_component_count is None:
            components = np.ones(len(residual), dtype=np.int64)
        else:
            components = np.asarray(support_component_count, dtype=np.int64)
            if components.shape != (len(residual),):
                raise ValueError("support_component_count must have shape [Q]")
        ambiguous = (
            np.isfinite(branch)
            & (branch >= 0.05)
            & ((components >= 2) | (np.isfinite(within) & (branch >= 2.0 * np.maximum(within, 1.0e-15))))
        )
        branch_lower = np.where(ambiguous, 0.5 * branch, 0.0)
    return {
        "residual_estimate_mps": residual,
        "smooth_upper_bound_mps": smooth_upper,
        "ambiguity_lower_bound_mps": branch_lower,
        "lower_bound_mps": branch_lower,
        "upper_bound_mps": smooth_upper,
        "bound_status": np.asarray(bound_status, dtype=object),
    }


@dataclass(frozen=True)
class ReconstructionResult:
    velocity: np.ndarray
    reliable: np.ndarray
    diagnostics: dict[str, np.ndarray]

    def __post_init__(self):
        for value in (self.velocity, self.reliable, *self.diagnostics.values()):
            if isinstance(value, np.ndarray):
                value.setflags(write=False)


class NativeKernelMLS:
    """Complete-support, native-volume weighted affine MLS backend."""

    def __init__(
        self,
        h: float,
        *,
        minimum_support_count: int = MLS_GATE["minimum_support_count"],
        minimum_effective_sample_size: float = MLS_GATE["minimum_effective_sample_size"],
        maximum_condition_number: float = MLS_GATE["maximum_condition_number"],
        svd_relative_cutoff: float = MLS_GATE["svd_relative_cutoff"],
    ):
        self.h = float(h)
        if not np.isfinite(self.h) or self.h <= 0.0:
            raise ValueError("h must be finite and positive")
        self.minimum_support_count = int(minimum_support_count)
        self.minimum_effective_sample_size = float(minimum_effective_sample_size)
        self.maximum_condition_number = float(maximum_condition_number)
        self.svd_relative_cutoff = float(svd_relative_cutoff)
        if self.minimum_support_count < 4:
            raise ValueError("minimum_support_count must support a 3-D affine basis")
        if not np.isfinite(self.minimum_effective_sample_size) or self.minimum_effective_sample_size < 1:
            raise ValueError("minimum_effective_sample_size must be finite and >= 1")
        if not np.isfinite(self.maximum_condition_number) or self.maximum_condition_number <= 1:
            raise ValueError("maximum_condition_number must be finite and > 1")
        if not np.isfinite(self.svd_relative_cutoff) or not 0 < self.svd_relative_cutoff < 1:
            raise ValueError("svd_relative_cutoff must be in (0,1)")

    @property
    def binding(self) -> dict:
        return {
            "schema": SCHEMA,
            "backend": BACKEND,
            "qualification_claim": QUALIFICATION_CLAIM,
            "h_m": self.h,
            "support_radius_m": 2.0 * self.h,
            "weights": "(mass/density)*Wendland_quintic_c2_3d(distance,h)",
            "kernel": dict(WENDLAND_FORMULA),
            "fit": "weighted_affine_MLS_in_scaled_offsets_[1,dx/h,dy/h,dz/h]",
            "support_selection": "all_valid_fluid_rows_within_2h_after_optional_finite_wall_visibility",
            "connectivity_diagnostic": dict(CONNECTIVITY_DIAGNOSTIC),
            "gate": {
                "minimum_support_count": self.minimum_support_count,
                "minimum_effective_sample_size": self.minimum_effective_sample_size,
                "minimum_geometry_rank": 4,
                "maximum_condition_number": self.maximum_condition_number,
                "svd_relative_cutoff": self.svd_relative_cutoff,
            },
            "input_policy": dict(INPUT_POLICY),
        }

    def reconstruct(self, query, frame: NativeCurrentFrame, *, walls=None) -> ReconstructionResult:
        query = np.asarray(query, dtype=np.float64)
        if query.ndim != 2 or query.shape[1:] != (3,) or not np.isfinite(query).all():
            raise ValueError("query must be finite with shape [Q,3]")
        if not isinstance(frame, NativeCurrentFrame):
            raise TypeError("reconstruct requires NativeCurrentFrame from the current-frame provider")
        triangles = _validate_walls(walls)
        count = len(query)
        prediction = np.full((count, 3), np.nan, dtype=np.float64)
        reliable = np.zeros(count, dtype=bool)
        support_count = np.zeros(count, dtype=np.int64)
        candidate_count = np.zeros(count, dtype=np.int64)
        wall_rejected = np.zeros(count, dtype=np.int64)
        effective = np.full(count, np.nan, dtype=np.float64)
        rank = np.zeros(count, dtype=np.int8)
        condition = np.full(count, np.inf, dtype=np.float64)
        residual = np.full(count, np.nan, dtype=np.float64)
        weight_sum = np.zeros(count, dtype=np.float64)
        volume_sum = np.zeros(count, dtype=np.float64)
        native_mass_sum = np.zeros(count, dtype=np.float64)
        second_moment = np.full(count, np.nan, dtype=np.float64)
        support_min = np.full(count, np.nan, dtype=np.float64)
        support_max = np.full(count, np.nan, dtype=np.float64)
        singular_values = np.full((count, 4), np.nan, dtype=np.float64)
        reason = np.full(count, "no_support", dtype=object)
        if count == 0:
            return ReconstructionResult(prediction, reliable, self._diagnostics(
                support_count, candidate_count, wall_rejected, effective, rank,
                condition, residual, weight_sum, volume_sum, native_mass_sum,
                second_moment, support_min, support_max, singular_values, reason, triangles,
            ))
        points = frame.fluid_position
        values = frame.fluid_velocity
        volumes = frame.fluid_volume
        masses = frame.fluid_mass
        tree = cKDTree(points)
        pools = tree.query_ball_point(query, r=2.0 * self.h, p=2.0, eps=0.0, workers=1, return_sorted=True)
        for row, pool in enumerate(pools):
            candidate = np.asarray(pool, dtype=np.int64)
            candidate_count[row] = len(candidate)
            if len(candidate) == 0:
                continue
            visible = _visible_endpoints(query[row], points[candidate], triangles)
            wall_rejected[row] = int(np.count_nonzero(~visible))
            candidate = candidate[visible]
            if len(candidate) == 0:
                reason[row] = "wall_occluded"
                continue
            delta = points[candidate] - query[row]
            distance2 = np.einsum("ij,ij->i", delta, delta)
            distance = np.sqrt(np.maximum(distance2, 0.0))
            kernel = wendland_quintic_c2_3d(distance, self.h)
            weights = volumes[candidate] * kernel
            keep = np.isfinite(weights) & (weights > 0.0)
            candidate = candidate[keep]
            delta = delta[keep]
            distance2 = distance2[keep]
            distance = distance[keep]
            weights = weights[keep]
            if len(candidate) == 0:
                reason[row] = "zero_weight"
                continue
            support_count[row] = len(candidate)
            weight_total = float(np.sum(weights))
            weight_sum[row] = weight_total
            volume_sum[row] = float(np.sum(volumes[candidate]))
            native_mass_sum[row] = float(np.sum(masses[candidate]))
            second_moment[row] = float(np.sum(weights * distance2) / weight_total)
            support_min[row] = float(np.min(distance))
            support_max[row] = float(np.max(distance))
            effective[row] = weight_total * weight_total / float(np.sum(weights * weights))
            design = np.column_stack((np.ones(len(candidate)), delta / self.h))
            square_root = np.sqrt(weights)
            weighted_design = design * square_root[:, None]
            weighted_values = values[candidate] * square_root[:, None]
            try:
                _, singular, _ = np.linalg.svd(weighted_design, full_matrices=False)
                singular_values[row, :len(singular)] = singular
                cutoff = singular[0] * self.svd_relative_cutoff if len(singular) else np.inf
                rank[row] = int(np.count_nonzero(singular > cutoff)) if len(singular) else 0
                condition[row] = float(singular[0] / singular[-1]) if len(singular) == 4 and singular[-1] > cutoff else np.inf
                coefficients, _, _, _ = np.linalg.lstsq(
                    weighted_design, weighted_values, rcond=self.svd_relative_cutoff
                )
                prediction[row] = coefficients[0]
                fitted = design @ coefficients
                residual[row] = math.sqrt(float(np.sum(weights * np.sum((fitted - values[candidate]) ** 2, axis=1)) / weight_total))
            except np.linalg.LinAlgError:
                reason[row] = "svd_failure"
                continue
            finite_prediction = np.isfinite(prediction[row]).all()
            if not finite_prediction:
                reason[row] = "nonfinite_prediction"
            elif rank[row] < 4:
                reason[row] = "rank_deficient"
            elif condition[row] > self.maximum_condition_number:
                reason[row] = "ill_conditioned"
            elif effective[row] < self.minimum_effective_sample_size:
                reason[row] = "low_effective_sample_size"
            elif support_count[row] < self.minimum_support_count:
                reason[row] = "insufficient_support"
            else:
                reliable[row] = True
                reason[row] = "reliable"
        diagnostics = self._diagnostics(
            support_count, candidate_count, wall_rejected, effective, rank,
            condition, residual, weight_sum, volume_sum, native_mass_sum,
            second_moment, support_min, support_max, singular_values, reason, triangles,
        )
        return ReconstructionResult(prediction, reliable, diagnostics)

    @staticmethod
    def _diagnostics(
        support_count, candidate_count, wall_rejected, effective, rank,
        condition, residual, weight_sum, volume_sum, native_mass_sum,
        second_moment, support_min, support_max, singular_values, reason, triangles,
    ) -> dict[str, np.ndarray]:
        return {
            "support_count": np.asarray(support_count),
            "candidate_count": np.asarray(candidate_count),
            "wall_rejected_count": np.asarray(wall_rejected),
            "effective_sample_size": np.asarray(effective),
            "geometry_rank": np.asarray(rank),
            "condition_number": np.asarray(condition),
            "weighted_reconstruction_error_mps": np.asarray(residual),
            "weight_sum": np.asarray(weight_sum),
            "support_volume_sum_m3": np.asarray(volume_sum),
            "support_native_mass_sum_kg": np.asarray(native_mass_sum),
            "weighted_second_moment_m2": np.asarray(second_moment),
            "support_distance_min_m": np.asarray(support_min),
            "support_distance_max_m": np.asarray(support_max),
            "singular_values": np.asarray(singular_values),
            "failure_reason": np.asarray(reason, dtype=object),
            "visibility_mode": np.asarray(
                "finite_wall_visibility" if len(triangles) else "no_wall_geometry",
                dtype=object,
            ),
        }


def _segment_box_interval(start: np.ndarray, end: np.ndarray, low: np.ndarray, high: np.ndarray):
    """Return the closed-box interval occupied by a linear segment."""
    lower, upper = 0.0, 1.0
    for axis in range(3):
        delta = float(end[axis] - start[axis])
        if abs(delta) <= np.finfo(np.float64).eps:
            if start[axis] < low[axis] or start[axis] > high[axis]:
                return None
            continue
        first = (low[axis] - start[axis]) / delta
        last = (high[axis] - start[axis]) / delta
        if first > last:
            first, last = last, first
        lower = max(lower, first)
        upper = min(upper, last)
        if upper < lower:
            return None
    return max(0.0, lower), min(1.0, upper)


def _crossing_fraction(start_z: float, end_z: float, plane_z: float) -> float:
    denominator = float(end_z - start_z)
    if abs(denominator) <= np.finfo(np.float64).eps:
        return 0.0
    return float(np.clip((plane_z - start_z) / denominator, 0.0, 1.0))


class NativeMaterialEventTracker:
    """Continuous F4 event observer owned by the native trace backend.

    The tracker consumes only the segment accepted by the integrator.  It has
    no solver identity or source-label partition and its arrays are included
    in the atomic checkpoint state.
    """

    def __init__(self, count: int, *, plane_z: float = 0.18,
                 destination_low=(0.0, 0.0, 0.0),
                 destination_high=(1.2, 0.4, 0.18)):
        self.count = int(count)
        if self.count <= 0:
            raise ValueError("event tracker count must be positive")
        self.plane_z = float(plane_z)
        self.destination_low = _finite_vector("destination_low", destination_low, (3,))
        self.destination_high = _finite_vector("destination_high", destination_high, (3,))
        if np.any(self.destination_high <= self.destination_low):
            raise ValueError("destination_high must exceed destination_low")

    def initial_state(self) -> dict[str, np.ndarray]:
        n = self.count
        return {
            "contact_time": np.full(n, np.nan, dtype=np.float64),
            "upward_time": np.full(n, np.nan, dtype=np.float64),
            "return_time": np.full(n, np.nan, dtype=np.float64),
            "residence_s": np.zeros(n, dtype=np.float64),
            "contacted": np.zeros(n, dtype=bool),
            "upward": np.zeros(n, dtype=bool),
            "returned": np.zeros(n, dtype=bool),
        }

    def advance(self, state, start, end, velocity_start, velocity_end,
                segment_time: float, dt: float, usable) -> None:
        start = np.asarray(start, dtype=np.float64)
        end = np.asarray(end, dtype=np.float64)
        velocity_start = np.asarray(velocity_start, dtype=np.float64)
        velocity_end = np.asarray(velocity_end, dtype=np.float64)
        usable = np.asarray(usable, dtype=bool)
        expected = (self.count, 3)
        if start.shape != expected or end.shape != expected:
            raise ValueError("event segment positions must have shape [N,3]")
        if velocity_start.shape != expected or velocity_end.shape != expected:
            raise ValueError("event segment velocities must have shape [N,3]")
        if usable.shape != (self.count,) or not np.isfinite(segment_time) or not np.isfinite(dt) or dt <= 0:
            raise ValueError("event segment time and usable mask are invalid")
        for index in np.flatnonzero(usable):
            z0 = float(start[index, 2])
            z1 = float(end[index, 2])
            vz = 0.5 * float(velocity_start[index, 2] + velocity_end[index, 2])
            contact_fraction = None
            if (not state["contacted"][index] and z0 > self.plane_z
                    and z1 <= self.plane_z and vz < 0.0):
                contact_fraction = _crossing_fraction(z0, z1, self.plane_z)
                state["contact_time"][index] = segment_time + contact_fraction * dt
                state["contacted"][index] = True
            if (state["contacted"][index] and not state["upward"][index]
                    and z0 <= self.plane_z and z1 > self.plane_z and vz > 0.0):
                fraction = _crossing_fraction(z0, z1, self.plane_z)
                state["upward_time"][index] = segment_time + fraction * dt
                state["upward"][index] = True
            if (state["upward"][index] and not state["returned"][index]
                    and z0 > self.plane_z and z1 <= self.plane_z and vz < 0.0):
                fraction = _crossing_fraction(z0, z1, self.plane_z)
                state["return_time"][index] = segment_time + fraction * dt
                state["returned"][index] = True
            interval = _segment_box_interval(
                start[index], end[index], self.destination_low, self.destination_high,
            )
            if interval is not None and state["contacted"][index]:
                lower, upper = interval
                if contact_fraction is not None:
                    lower = max(lower, contact_fraction)
                if upper > lower:
                    state["residence_s"][index] += (upper - lower) * dt


def _native_event_status(state: Mapping[str, np.ndarray]) -> np.ndarray:
    status = np.zeros(len(state["permanent_unknown"]), dtype=np.int8)
    status[state["contacted"]] = 1
    status[state["upward"]] = 2
    status[state["returned"]] = 3
    status[state["permanent_unknown"]] = 4
    return status


def _trace_query_grid(count: int, q: float) -> np.ndarray:
    count = int(count)
    n = int(round(count ** (1.0 / 3.0)))
    if n ** 3 != count or n < 2:
        raise ValueError("query_count must be a perfect cube with side >= 2")
    q = float(q)
    if not np.isfinite(q) or not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0,1]")
    low = np.array([0.25 + 0.22 * q, 0.12, 0.40], dtype=np.float64)
    axes = [lo + (np.arange(n, dtype=np.float64) + 0.5) * size / n
            for lo, size in zip(low, F4_SOURCE_SIZE_M)]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def _trace_checkpoint_paths(output: Path) -> tuple[Path, Path]:
    return (
        Path(str(output) + ".checkpoint.npz"),
        Path(str(output) + ".checkpoint.json"),
    )


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _trace_binding(*, source: Path, source_sha256: str, h: float, query_count: int,
                   q: float, substeps: int, fluid_type: int | None,
                   hessian_bound_mps_per_m2: float | None, walls: np.ndarray) -> dict:
    return {
        "schema": TRACE_SCHEMA,
        "backend": TRACE_BACKEND,
        "static_backend": BACKEND,
        "qualification_claim": QUALIFICATION_CLAIM,
        "source_h5": str(source),
        "source_sha256": source_sha256,
        "h_m": float(h),
        "query_count": int(query_count),
        "q": float(q),
        "substeps": int(substeps),
        "fluid_type": fluid_type,
        "causal_policy": {
            "frame_for_interval": "current frame i only for [time_i,time_i+1]",
            "rk_stages": "all four stages use the same current native frame i",
            "future_velocity": "forbidden",
            "future_density": "forbidden",
            "predicted_density": "forbidden",
        },
        "integration": "classical explicit RK4 with fixed current-frame field over each native interval",
        "temporal_accuracy": {
            "current_frame_field_hold": "piecewise-constant native field over each saved interval; cross-frame field time accuracy is first-order hold",
            "rk4_scope": "RK4 improves spatial integration of the frozen current-frame velocity field only; it does not make the overall native-frame temporal interpolation fourth-order",
        },
        "unknown_policy": "any failed support stage becomes permanent_unknown and is excluded from later event updates",
        "event_definition": dict(TRACE_EVENT_DEFINITION),
        "query_identity": "independent geometric seed; native particle_id and initial Mk are not used",
        "query_mass": "equal positive mass; all seeds remain in denominator, including permanent_unknown",
        "error_budget": {
            "reconstruction_residual": "weighted affine MLS fit residual is an estimate only",
            "analytic_upper_bound": "0.5*Hessian_bound*weighted_second_moment*condition_amplification when an independent H bound is supplied",
            "real_source_status": "unavailable_without_an_independent_native_field_Hessian_bound",
            "material_reliability": "not_assessed_by_numerical_support_gate",
            "hessian_bound_mps_per_m2": hessian_bound_mps_per_m2,
        },
        "walls": {
            "mode": "finite triangle visibility",
            "triangle_count": int(len(walls)),
            "geometry_sha256": _array_hash(walls),
        },
        "checkpoint": {
            "schema": TRACE_CHECKPOINT_SCHEMA,
            "ordering": "atomic checkpoint state is written before each HDF5 frame append",
            "resume_source_of_truth": "checkpoint state; HDF5 is truncated to checkpoint frame before rewrite",
        },
    }


def _trace_state_hash(state: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name in TRACE_CHECKPOINT_FIELDS:
        array = np.ascontiguousarray(np.asarray(state[name]))
        digest.update(name.encode("utf-8"))
        digest.update(_canonical({"dtype": array.dtype.str, "shape": array.shape}).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def _trace_checkpoint_write(output: Path, binding: Mapping, frame: int,
                            state: Mapping[str, np.ndarray], seed_hash: str,
                            *, fault_after_publish: bool = False) -> dict:
    """Publish a durable checkpoint without replacing the previous generation.

    The NPZ name contains the committed frame and state hash.  A crash after
    this generation is renamed but before the manifest replace leaves the old
    manifest and old generation intact, so resume can still use the last
    committed state.  The fault flag is a test-only SIGKILL injection at that
    exact publication window.
    """
    _, manifest_path = _trace_checkpoint_paths(output)
    state_sha256 = _trace_state_hash(state)
    generation = output.with_name(
        f"{output.name}.checkpoint.{int(frame):08d}.{state_sha256[:24]}.npz"
    )
    if not generation.exists():
        temporary = generation.with_name(
            generation.name + f".partial.{os.getpid()}.npz"
        )
        np.savez_compressed(temporary, **{name: np.asarray(state[name]) for name in TRACE_CHECKPOINT_FIELDS})
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, generation)
    else:
        # A same-name generation is expected to be identical.  Never silently
        # republish a corrupted orphan under a valid manifest.
        with np.load(generation, allow_pickle=False) as archive:
            existing = {name: np.array(archive[name], copy=True) for name in TRACE_CHECKPOINT_FIELDS}
        if _trace_state_hash(existing) != state_sha256:
            raise ValueError("existing native trace checkpoint generation is corrupt")
    generation_file_sha256 = sha256_file(generation)
    if fault_after_publish:
        os.kill(os.getpid(), signal.SIGKILL)
    record = {
        "schema": TRACE_CHECKPOINT_SCHEMA,
        "binding_sha256": hashlib.sha256(_canonical(binding).encode()).hexdigest(),
        "seed_hash": seed_hash,
        "committed_frame": int(frame),
        "fields": list(TRACE_CHECKPOINT_FIELDS),
        "state_sha256": state_sha256,
        "file_sha256": generation_file_sha256,
        "checkpoint_npz": str(generation),
        "generation": generation.name,
    }
    _atomic_text(manifest_path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def _trace_checkpoint_read(output: Path, binding: Mapping, seed_hash: str):
    _, manifest_path = _trace_checkpoint_paths(output)
    if not manifest_path.exists():
        return None
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_binding = hashlib.sha256(_canonical(binding).encode()).hexdigest()
    if (record.get("schema") != TRACE_CHECKPOINT_SCHEMA
            or record.get("binding_sha256") != expected_binding
            or record.get("seed_hash") != seed_hash
            or record.get("fields") != list(TRACE_CHECKPOINT_FIELDS)):
        raise ValueError("native trace checkpoint provenance mismatch")
    npz_path = Path(record.get("checkpoint_npz", ""))
    if not npz_path.exists() or npz_path.parent.resolve() != output.parent.resolve():
        raise ValueError("native trace checkpoint generation is missing")
    if not npz_path.name.startswith(output.name + ".checkpoint."):
        raise ValueError("native trace checkpoint generation name is invalid")
    if sha256_file(npz_path) != record.get("file_sha256"):
        raise ValueError("native trace checkpoint file hash mismatch")
    with np.load(npz_path, allow_pickle=False) as archive:
        state = {name: np.array(archive[name], copy=True) for name in TRACE_CHECKPOINT_FIELDS}
    if _trace_state_hash(state) != record.get("state_sha256"):
        raise ValueError("native trace checkpoint state hash mismatch")
    return int(record["committed_frame"]), state, record


def _trace_seed_hash(initial: np.ndarray, mass: np.ndarray, labels: np.ndarray, tracer_ids: np.ndarray) -> str:
    return _array_hash(initial, mass, labels.astype(str), tracer_ids.astype(str))


def _trace_create_output(handle, initial, query_mass, labels, tracer_ids, binding, seed_hash):
    n = len(initial)
    handle.attrs["schema"] = TRACE_SCHEMA
    handle.attrs["trace_backend"] = TRACE_BACKEND
    handle.attrs["binding"] = _canonical(binding)
    handle.attrs["binding_sha256"] = hashlib.sha256(_canonical(binding).encode()).hexdigest()
    handle.attrs["seed_hash"] = seed_hash
    handle.attrs["checkpoint_schema"] = TRACE_CHECKPOINT_SCHEMA
    handle.attrs["committed"] = -1
    handle.attrs["qualification_claim"] = QUALIFICATION_CLAIM
    handle.attrs["material_reliability"] = "not_assessed_by_numerical_support_gate"
    handle.create_dataset("initial_position", data=initial)
    handle.create_dataset("query_mass", data=query_mass)
    handle.create_dataset("source_label", data=np.asarray(labels, dtype=h5py.string_dtype("utf-8")))
    handle.create_dataset("tracer_id", data=np.asarray(tracer_ids, dtype=h5py.string_dtype("utf-8")))
    for name in TRACE_HISTORY_FIELDS:
        if name in {"time", "unknown_mass", "reliable_mass", "contact_mass", "upward_mass",
                    "return_mass", "destination_mass", "mass_closure_error"}:
            shape, dtype = (), "f8"
        elif name in {"reliable", "permanent_unknown", "destination_member", "contacted", "upward", "returned"}:
            shape, dtype = (n,), "?"
        elif name == "event_status":
            shape, dtype = (n,), "i1"
        elif name == "position":
            shape, dtype = (n, 3), "f8"
        else:
            shape, dtype = (n,), "f8"
        handle.create_dataset(name, shape=(0,) + shape, maxshape=(None,) + shape,
                              dtype=dtype, chunks=(1,) + shape)
    handle.flush()


def _trace_validate_output(handle, initial, query_mass, labels, tracer_ids, binding, seed_hash):
    expected = _canonical(binding)
    if (handle.attrs.get("schema") != TRACE_SCHEMA
            or handle.attrs.get("trace_backend") != TRACE_BACKEND
            or handle.attrs.get("binding") != expected
            or handle.attrs.get("seed_hash") != seed_hash):
        raise ValueError("native trace output provenance mismatch")
    for name in ("initial_position", "query_mass", "source_label", "tracer_id") + TRACE_HISTORY_FIELDS:
        if name not in handle:
            raise ValueError(f"native trace output missing dataset {name}")
    if not np.array_equal(handle["initial_position"][:], initial) or not np.array_equal(handle["query_mass"][:], query_mass):
        raise ValueError("native trace seed metadata mismatch")
    stored_labels = np.asarray(handle["source_label"].asstr()[:])
    stored_ids = np.asarray(handle["tracer_id"].asstr()[:])
    if not np.array_equal(stored_labels, labels.astype(str)) or not np.array_equal(stored_ids, tracer_ids.astype(str)):
        raise ValueError("native trace seed identity mismatch")


def _trace_frame_values(state: Mapping[str, np.ndarray], query_mass: np.ndarray,
                        tracker: NativeMaterialEventTracker) -> dict[str, object]:
    unknown = np.asarray(state["permanent_unknown"], dtype=bool)
    reliable = ~unknown
    position = np.asarray(state["position"], dtype=np.float64)
    destination = (
        np.all(position >= tracker.destination_low[None, :], axis=1)
        & np.all(position <= tracker.destination_high[None, :], axis=1)
    )
    total = float(np.sum(query_mass))
    unknown_mass = float(np.sum(query_mass[unknown]))
    reliable_mass = float(np.sum(query_mass[reliable]))
    contact_mass = float(np.sum(query_mass[reliable & state["contacted"]]))
    upward_mass = float(np.sum(query_mass[reliable & state["upward"]]))
    return_mass = float(np.sum(query_mass[reliable & state["returned"]]))
    destination_mass = float(np.sum(query_mass[reliable & destination]))
    return {
        "time": None,
        "position": position,
        "reliable": reliable,
        "permanent_unknown": unknown,
        "destination_member": destination,
        "contact_time": np.asarray(state["contact_time"]),
        "upward_time": np.asarray(state["upward_time"]),
        "return_time": np.asarray(state["return_time"]),
        "residence_s": np.asarray(state["residence_s"]),
        "contacted": np.asarray(state["contacted"]),
        "upward": np.asarray(state["upward"]),
        "returned": np.asarray(state["returned"]),
        "event_status": _native_event_status(state),
        "residual_estimate_mps": np.asarray(state["residual_estimate_mps"]),
        "error_upper_bound_mps": np.asarray(state["error_upper_bound_mps"]),
        "path_error_estimate_m": np.asarray(state["path_error_estimate_m"]),
        "path_error_budget_m": np.asarray(state["path_error_budget_m"]),
        "unknown_mass": unknown_mass,
        "reliable_mass": reliable_mass,
        "contact_mass": contact_mass,
        "upward_mass": upward_mass,
        "return_mass": return_mass,
        "destination_mass": destination_mass,
        "mass_closure_error": total - unknown_mass - reliable_mass,
    }


def _trace_append_frame(handle, frame: int, time_s: float, values: Mapping[str, object]):
    frame = int(frame)
    for name in TRACE_HISTORY_FIELDS:
        handle[name].resize(frame + 1, axis=0)
    for name in TRACE_HISTORY_FIELDS:
        value = time_s if name == "time" else values[name]
        handle[name][frame] = value
    handle.attrs["committed"] = frame
    handle.flush()


def _trace_truncate_to(handle, frame_count: int) -> None:
    for name in TRACE_HISTORY_FIELDS:
        handle[name].resize(int(frame_count), axis=0)
    handle.attrs["committed"] = int(frame_count - 1)
    handle.flush()


def _trace_max_update(target: np.ndarray, candidate: np.ndarray) -> None:
    finite = np.isfinite(candidate)
    target[finite] = np.where(
        np.isfinite(target[finite]),
        np.maximum(target[finite], candidate[finite]),
        candidate[finite],
    )


def _trace_stage(backend: NativeKernelMLS, query: np.ndarray, frame: NativeCurrentFrame,
                 active: np.ndarray, walls: np.ndarray,
                 hessian_bound_mps_per_m2: float | None):
    count = len(query)
    velocity = np.full((count, 3), np.nan, dtype=np.float64)
    reliable = np.zeros(count, dtype=bool)
    residual = np.full(count, np.nan, dtype=np.float64)
    upper = np.full(count, np.nan, dtype=np.float64)
    indices = np.flatnonzero(active)
    if len(indices) == 0:
        return velocity, reliable, residual, upper
    result = backend.reconstruct(query[indices], frame, walls=walls)
    velocity[indices] = result.velocity
    reliable[indices] = result.reliable
    residual[indices] = result.diagnostics["weighted_reconstruction_error_mps"]
    budget = reconstruction_error_budget(
        result, hessian_bound_mps_per_m2=hessian_bound_mps_per_m2,
    )
    upper[indices] = budget["upper_bound_mps"]
    return velocity, reliable, residual, upper


def _trace_cdf(event_time: np.ndarray, weight: np.ndarray, mask: np.ndarray, denominator: float) -> dict:
    mask = np.asarray(mask, dtype=bool) & np.isfinite(event_time)
    if denominator <= 0.0 or not np.any(mask):
        return {"time_s": [], "mass_fraction": [], "event_mass_fraction": 0.0}
    order = np.argsort(event_time[mask], kind="mergesort")
    values = event_time[mask][order]
    fractions = np.cumsum(weight[mask][order]) / denominator
    return {
        "time_s": values.tolist(),
        "mass_fraction": fractions.tolist(),
        "event_mass_fraction": float(fractions[-1]),
    }


def _trace_summary(output: Path, source: Path, binding: Mapping, labels: np.ndarray,
                   query_mass: np.ndarray, execution: Mapping) -> dict:
    with h5py.File(output, "r") as handle:
        committed = int(handle.attrs.get("committed", -1))
        if committed < 0:
            raise ValueError("native trace has no committed frame")
        final_time = float(handle["time"][committed])
        reliable = np.asarray(handle["reliable"][committed], dtype=bool)
        position = np.asarray(handle["position"][committed], dtype=np.float64)
        destination = np.asarray(handle["destination_member"][committed], dtype=bool)
        contact = np.asarray(handle["contacted"][committed], dtype=bool)
        upward = np.asarray(handle["upward"][committed], dtype=bool)
        returned = np.asarray(handle["returned"][committed], dtype=bool)
        contact_time = np.asarray(handle["contact_time"][committed], dtype=np.float64)
        upward_time = np.asarray(handle["upward_time"][committed], dtype=np.float64)
        return_time = np.asarray(handle["return_time"][committed], dtype=np.float64)
        residence = np.asarray(handle["residence_s"][committed], dtype=np.float64)
        residual = np.asarray(handle["residual_estimate_mps"][committed], dtype=np.float64)
        upper = np.asarray(handle["error_upper_bound_mps"][committed], dtype=np.float64)
        path_estimate = np.asarray(handle["path_error_estimate_m"][committed], dtype=np.float64)
        path_budget = np.asarray(handle["path_error_budget_m"][committed], dtype=np.float64)
    total = float(np.sum(query_mass))
    rows = []
    for source_label in np.unique(labels.astype(str)):
        select = labels.astype(str) == source_label
        source_mass = float(np.sum(query_mass[select]))
        source_reliable = select & reliable
        source_unknown = select & ~reliable
        source_contact = source_reliable & contact
        source_upward = source_reliable & upward
        source_return = source_reliable & returned
        source_destination = source_reliable & destination
        closure = float(np.sum(query_mass[select & reliable]) + np.sum(query_mass[source_unknown])) / source_mass if source_mass else 0.0
        rows.append({
            "source": source_label,
            "initial_mass_fraction": source_mass / total if total else 0.0,
            "unknown_fraction": float(np.sum(query_mass[source_unknown]) / source_mass) if source_mass else 0.0,
            "unknown_fraction_max": float(np.sum(query_mass[source_unknown]) / source_mass) if source_mass else 0.0,
            "reliable_path_coverage": float(np.sum(query_mass[source_reliable]) / source_mass) if source_mass else 0.0,
            "contact_fraction": float(np.sum(query_mass[source_contact]) / source_mass) if source_mass else 0.0,
            "upward_fraction": float(np.sum(query_mass[source_upward]) / source_mass) if source_mass else 0.0,
            "return_fraction": float(np.sum(query_mass[source_return]) / source_mass) if source_mass else 0.0,
            "observed_contact_fraction": float(np.sum(query_mass[select & contact]) / source_mass) if source_mass else 0.0,
            "observed_upward_fraction": float(np.sum(query_mass[select & upward]) / source_mass) if source_mass else 0.0,
            "observed_return_fraction": float(np.sum(query_mass[select & returned]) / source_mass) if source_mass else 0.0,
            "destination_mass_fraction": float(np.sum(query_mass[source_destination]) / source_mass) if source_mass else 0.0,
            "outside_destination_mass_fraction": float(np.sum(query_mass[source_reliable & ~destination]) / source_mass) if source_mass else 0.0,
            "mass_closure_fraction": closure,
            "mass_closure_error": closure - 1.0,
            "contact_cdf": _trace_cdf(contact_time, query_mass, source_contact, source_mass),
            "upward_cdf": _trace_cdf(upward_time, query_mass, source_upward, source_mass),
            "return_cdf": _trace_cdf(return_time, query_mass, source_return, source_mass),
            "residence_cdf": _trace_cdf(residence, query_mass, source_contact, source_mass),
            "residence_mean_s": float(np.sum(query_mass[select] * residence[select]) / source_mass) if source_mass else 0.0,
            "right_censored_fraction": float(np.sum(query_mass[select & ~returned]) / source_mass) if source_mass else 0.0,
            "error_budget": {
                "reconstruction_residual_p95_mps": _percentile(residual[select], 95),
                "analytic_upper_bound_p95_mps": _percentile(upper[select], 95),
                "path_error_estimate_p95_m": _percentile(path_estimate[select], 95),
                "path_error_budget_p95_m": _percentile(path_budget[select], 95),
                "analytic_upper_bound_available": bool(np.any(np.isfinite(upper[select]))),
            },
        })
    complete = bool(np.any(reliable) and np.all((~reliable) | returned))
    return {
        "schema": TRACE_SCHEMA,
        "trace_backend": TRACE_BACKEND,
        "static_backend": BACKEND,
        "qualification_claim": QUALIFICATION_CLAIM,
        "source": str(source),
        "source_sha256": sha256_file(source),
        "binding": _json_value(binding),
        "output_h5": str(output),
        "output_sha256": sha256_file(output),
        "committed_frame": committed,
        "committed_time_s": final_time,
        "by_source": rows,
        "mass_closed": all(abs(row["mass_closure_error"]) <= 1.0e-12 for row in rows),
        "unknown_gate_pass": all(row["unknown_fraction_max"] <= 0.01 for row in rows),
        "common_reliable_path_coverage": float(np.sum(query_mass[reliable]) / total) if total else 0.0,
        "event_window_complete": complete,
        "event_window_status": "complete" if complete else "right_censored_or_unresolved",
        "material_reliability_status": "not_assessed; numerical support reliability is not a material truth claim",
        "execution": _json_value(execution),
    }


def trace_native_material(
    source: str | Path,
    output: str | Path,
    *,
    h: float = F4_H_M,
    fluid_type: int | None = 3,
    query_count: int = 512,
    q: float = 0.5,
    substeps: int = 4,
    stop_after: int | None = None,
    resume: bool = False,
    kill_after: int | None = None,
    kill_after_checkpoint_publish: int | None = None,
    hessian_bound_mps_per_m2: float | None = None,
    walls=None,
    summary_output: str | Path | None = None,
) -> dict:
    """Run or resume a causal RK4 material trace on native current frames.

    A native interval is integrated with four RK stages at a fixed current
    frame.  This deliberately gives the backend no access to frame ``i+1``
    fields.  The checkpoint is committed before its corresponding HDF5 frame;
    resume truncates the HDF5 history to that checkpoint and rewrites the
    frame, so a process kill between the two writes is equivalent to a clean
    run.
    """
    source = Path(source)
    output = Path(output)
    if not source.exists():
        raise FileNotFoundError(source)
    if not np.isfinite(float(h)) or float(h) <= 0.0:
        raise ValueError("h must be finite and positive")
    substeps = int(substeps)
    if substeps <= 0:
        raise ValueError("substeps must be a positive integer")
    query_count = int(query_count)
    if query_count <= 0:
        raise ValueError("query_count must be positive")
    if stop_after is not None and int(stop_after) < 0:
        raise ValueError("stop_after must be nonnegative")
    if kill_after is not None and int(kill_after) < 0:
        raise ValueError("kill_after must be nonnegative")
    if kill_after_checkpoint_publish is not None and int(kill_after_checkpoint_publish) < 0:
        raise ValueError("kill_after_checkpoint_publish must be nonnegative")
    if hessian_bound_mps_per_m2 is not None and (
            not np.isfinite(float(hessian_bound_mps_per_m2)) or float(hessian_bound_mps_per_m2) < 0.0):
        raise ValueError("hessian_bound_mps_per_m2 must be finite and nonnegative")
    walls = f4_resting_pool_walls() if walls is None else _validate_walls(walls)
    provider = NativeCurrentFrameProvider(source, fluid_type=fluid_type)
    times = provider.current_times()
    last_frame = len(times) - 1 if stop_after is None else min(int(stop_after), len(times) - 1)
    initial = _trace_query_grid(query_count, q)
    query_mass = np.full(query_count, 1.0 / query_count, dtype=np.float64)
    labels = np.full(query_count, f"drop_q{float(q):.6g}", dtype=object)
    tracer_ids = np.asarray([f"seed-{index:06d}" for index in range(query_count)], dtype=object)
    seed_hash = _trace_seed_hash(initial, query_mass, labels, tracer_ids)
    binding = _trace_binding(
        source=source, source_sha256=provider.source_sha256, h=h, query_count=query_count,
        q=q, substeps=substeps, fluid_type=fluid_type,
        hessian_bound_mps_per_m2=hessian_bound_mps_per_m2, walls=walls,
    )
    binding_text = _canonical(binding)
    backend = NativeKernelMLS(h)
    tracker = NativeMaterialEventTracker(query_count)
    started = time.monotonic()
    usage_start = resource.getrusage(resource.RUSAGE_SELF)
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = _trace_checkpoint_read(output, binding, seed_hash) if resume else None
    if resume and checkpoint is None:
        raise ValueError("--resume requires a complete native trace checkpoint")
    if not resume and output.exists():
        raise FileExistsError(f"refusing to overwrite existing trace: {output}")

    if checkpoint is None:
        state = tracker.initial_state()
        frame0 = provider.read_current(0)
        initial_reconstruction = backend.reconstruct(initial, frame0, walls=walls)
        state["position"] = np.array(initial, copy=True)
        state["permanent_unknown"] = ~initial_reconstruction.reliable
        state["residual_estimate_mps"] = np.asarray(
            initial_reconstruction.diagnostics["weighted_reconstruction_error_mps"], dtype=np.float64,
        )
        initial_budget = reconstruction_error_budget(
            initial_reconstruction, hessian_bound_mps_per_m2=hessian_bound_mps_per_m2,
        )
        state["error_upper_bound_mps"] = np.asarray(initial_budget["upper_bound_mps"], dtype=np.float64)
        state["path_error_estimate_m"] = np.zeros(query_count, dtype=np.float64)
        state["path_error_budget_m"] = np.zeros(query_count, dtype=np.float64)
        with h5py.File(output, "w") as handle:
            _trace_create_output(handle, initial, query_mass, labels, tracer_ids, binding, seed_hash)
        checkpoint_frame = 0
        with h5py.File(output, "r+") as handle:
            _trace_checkpoint_write(
                output, binding, checkpoint_frame, state, seed_hash,
                fault_after_publish=kill_after_checkpoint_publish == checkpoint_frame,
            )
            if kill_after == checkpoint_frame:
                os.kill(os.getpid(), signal.SIGKILL)
            values = _trace_frame_values(state, query_mass, tracker)
            _trace_append_frame(handle, checkpoint_frame, float(times[0]), values)
        start_frame = 1
    else:
        checkpoint_frame, state, _ = checkpoint
        if checkpoint_frame < 0 or checkpoint_frame >= len(times):
            raise ValueError("native trace checkpoint frame is outside source time axis")
        with h5py.File(output, "r+") as handle:
            _trace_validate_output(handle, initial, query_mass, labels, tracer_ids, binding, seed_hash)
            # The checkpoint is the durable source of truth.  Any HDF5 row at
            # or after it may have been partially appended before a kill.
            _trace_truncate_to(handle, checkpoint_frame)
            values = _trace_frame_values(state, query_mass, tracker)
            _trace_append_frame(handle, checkpoint_frame, float(times[checkpoint_frame]), values)
        start_frame = checkpoint_frame + 1

    if start_frame <= last_frame:
        with h5py.File(output, "r+") as handle:
            for end_frame in range(start_frame, last_frame + 1):
                current_index = end_frame - 1
                frame = provider.read_current(current_index)
                frame_dt = float(times[end_frame] - times[current_index])
                sub_dt = frame_dt / substeps
                frame_residual = np.full(query_count, np.nan, dtype=np.float64)
                frame_upper = np.full(query_count, np.nan, dtype=np.float64)
                frame_error = np.zeros(query_count, dtype=np.float64)
                for substep in range(substeps):
                    old_position = np.array(state["position"], copy=True)
                    active0 = ~state["permanent_unknown"]
                    k1, good1, residual1, upper1 = _trace_stage(
                        backend, old_position, frame, active0, walls, hessian_bound_mps_per_m2,
                    )
                    _trace_max_update(frame_residual, residual1)
                    _trace_max_update(frame_upper, upper1)
                    q2 = old_position + 0.5 * sub_dt * np.nan_to_num(k1, nan=0.0, posinf=0.0, neginf=0.0)
                    k2, good2, residual2, upper2 = _trace_stage(
                        backend, q2, frame, active0 & good1, walls, hessian_bound_mps_per_m2,
                    )
                    _trace_max_update(frame_residual, residual2)
                    _trace_max_update(frame_upper, upper2)
                    q3 = old_position + 0.5 * sub_dt * np.nan_to_num(k2, nan=0.0, posinf=0.0, neginf=0.0)
                    k3, good3, residual3, upper3 = _trace_stage(
                        backend, q3, frame, active0 & good1 & good2, walls, hessian_bound_mps_per_m2,
                    )
                    _trace_max_update(frame_residual, residual3)
                    _trace_max_update(frame_upper, upper3)
                    q4 = old_position + sub_dt * np.nan_to_num(k3, nan=0.0, posinf=0.0, neginf=0.0)
                    k4, good4, residual4, upper4 = _trace_stage(
                        backend, q4, frame, active0 & good1 & good2 & good3, walls, hessian_bound_mps_per_m2,
                    )
                    _trace_max_update(frame_residual, residual4)
                    _trace_max_update(frame_upper, upper4)
                    usable = active0 & good1 & good2 & good3 & good4
                    candidate = old_position + (sub_dt / 6.0) * (
                        np.nan_to_num(k1, nan=0.0, posinf=0.0, neginf=0.0)
                        + 2.0 * np.nan_to_num(k2, nan=0.0, posinf=0.0, neginf=0.0)
                        + 2.0 * np.nan_to_num(k3, nan=0.0, posinf=0.0, neginf=0.0)
                        + np.nan_to_num(k4, nan=0.0, posinf=0.0, neginf=0.0)
                    )
                    euler = old_position + sub_dt * np.nan_to_num(k1, nan=0.0, posinf=0.0, neginf=0.0)
                    local_error = np.linalg.norm(candidate - euler, axis=1)
                    state["path_error_budget_m"][usable] += local_error[usable]
                    frame_error[usable] = np.maximum(frame_error[usable], local_error[usable])
                    tracker.advance(
                        state, old_position, candidate, k1, k4,
                        float(times[current_index] + (substep * sub_dt)), sub_dt, usable,
                    )
                    state["position"] = np.where(usable[:, None], candidate, old_position)
                    state["permanent_unknown"] |= active0 & ~usable
                state["residual_estimate_mps"] = frame_residual
                state["error_upper_bound_mps"] = frame_upper
                state["path_error_estimate_m"] = frame_error
                _trace_checkpoint_write(
                    output, binding, end_frame, state, seed_hash,
                    fault_after_publish=kill_after_checkpoint_publish == end_frame,
                )
                if kill_after == end_frame:
                    os.kill(os.getpid(), signal.SIGKILL)
                values = _trace_frame_values(state, query_mass, tracker)
                _trace_append_frame(handle, end_frame, float(times[end_frame]), values)

    usage_end = resource.getrusage(resource.RUSAGE_SELF)
    execution = {
        "device": "CPU",
        "gpu_started": False,
        "ledger_mutation": 0,
        "slot_acquired": False,
        "wall_seconds": time.monotonic() - started,
        "cpu_user_seconds": usage_end.ru_utime - usage_start.ru_utime,
        "cpu_system_seconds": usage_end.ru_stime - usage_start.ru_stime,
        "peak_rss_mib": usage_end.ru_maxrss / 1024.0,
        "resume": bool(resume),
        "stop_after": int(last_frame),
        "substeps": substeps,
    }
    result = _trace_summary(output, source, binding, labels, query_mass, execution)
    result["checkpoint_manifest"] = str(_trace_checkpoint_paths(output)[1])
    result["code_sha256"] = sha256_file(Path(__file__))
    if summary_output is None:
        summary_output = Path(str(output) + ".summary.json")
    summary_output = Path(summary_output)
    _atomic_text(summary_output, json.dumps(_json_value(result), indent=2, sort_keys=True) + "\n")
    return result


def _lattice(low: Sequence[float], high: Sequence[float], spacing: float) -> np.ndarray:
    low = np.asarray(low, dtype=np.float64)
    high = np.asarray(high, dtype=np.float64)
    axes = [np.arange(lo, hi + spacing * 0.5, spacing, dtype=np.float64) for lo, hi in zip(low, high)]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def _volume_frame(position: np.ndarray, velocity: np.ndarray, *, volume: float = 1.0e-6, density: float = 1000.0) -> NativeCurrentFrame:
    return NativeCurrentFrame(
        position, velocity,
        np.full(len(position), volume * density, dtype=np.float64),
        np.full(len(position), density, dtype=np.float64),
    )


def _constant_field(points: np.ndarray) -> np.ndarray:
    return np.broadcast_to(np.array([0.23, -0.11, 0.07], dtype=np.float64), points.shape).copy()


def _affine_field(points: np.ndarray) -> np.ndarray:
    matrix = np.array([[0.4, -0.2, 0.1], [0.05, 0.3, -0.25], [-0.15, 0.08, 0.35]], dtype=np.float64)
    return np.array([0.23, -0.11, 0.07], dtype=np.float64) + points @ matrix.T


def _quadratic_field(points: np.ndarray) -> np.ndarray:
    """Smooth non-affine field with a known Hessian norm bound."""
    value = _affine_field(points)
    value[:, 0] += 0.5 * 4.0 * points[:, 0] ** 2
    value[:, 1] += 0.5 * 3.0 * points[:, 1] ** 2
    value[:, 2] += 0.5 * 2.0 * points[:, 2] ** 2
    return value


def _square_wall(z: float = 0.0, extent: float = 0.11) -> np.ndarray:
    a = np.array([-extent, -extent, z], dtype=np.float64)
    b = np.array([extent, -extent, z], dtype=np.float64)
    c = np.array([extent, extent, z], dtype=np.float64)
    d = np.array([-extent, extent, z], dtype=np.float64)
    return np.asarray([[a, b, c], [a, c, d]], dtype=np.float64)


def _wall_with_opening(z: float = 0.0, outer: float = 0.11, half_opening: float = 0.025) -> np.ndarray:
    # Four rectangular strips leave a square opening centered at x=y=0.
    zvec = lambda x, y: np.array([x, y, z], dtype=np.float64)
    tris = []
    for y0, y1, x0, x1 in [
        (-outer, -half_opening, -outer, outer),
        (half_opening, outer, -outer, outer),
        (-half_opening, half_opening, -outer, -half_opening),
        (-half_opening, half_opening, half_opening, outer),
    ]:
        a, b, c, d = zvec(x0, y0), zvec(x1, y0), zvec(x1, y1), zvec(x0, y1)
        tris.extend(((a, b, c), (a, c, d)))
    return np.asarray(tris, dtype=np.float64)


def f4_resting_pool_walls() -> np.ndarray:
    """The F4 basin's bottom and four closed sides; the top remains open."""
    low = F4_DESTINATION_LOW_M
    high = F4_DESTINATION_HIGH_M
    x0, y0, z0 = low
    x1, y1, z1 = high
    faces = [
        ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)),
        ((x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)),
        ((x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)),
        ((x0, y0, z0), (x0, y0, z1), (x1, y0, z1), (x1, y0, z0)),
        ((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)),
    ]
    result = []
    for a, b, c, d in faces:
        result.extend(((a, b, c), (a, c, d)))
    return np.asarray(result, dtype=np.float64)


def _f4_query_grid(count: int = 512, q: float = 0.5) -> np.ndarray:
    if count not in (512, 4096):
        raise ValueError("F4 query count must be 512 or 4096")
    q = float(q)
    if not np.isfinite(q) or not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0,1]")
    low = np.array([0.25 + 0.22 * q, 0.12, 0.40], dtype=np.float64)
    n = 8 if count == 512 else 16
    axes = [lo + (np.arange(n, dtype=np.float64) + 0.5) * size / n for lo, size in zip(low, F4_SOURCE_SIZE_M)]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def manufactured_cases() -> list[dict]:
    """Build deterministic analytic cases for backend qualification only."""
    interior = _lattice((-0.08, -0.08, -0.08), (0.08, 0.08, 0.08), 0.02)
    interior_queries = _lattice((-0.04, -0.04, -0.04), (0.04, 0.04, 0.04), 0.04)
    constant = _constant_field(interior)
    affine = _affine_field(interior)
    result = [
        {
            "id": "constant_interior",
            "position": interior,
            "velocity": constant,
            "query": interior_queries,
            "truth": _constant_field(interior_queries),
            "h": 0.045,
            "dp_m": 0.02,
            "walls": np.empty((0, 3, 3)),
            "expected": {"all_reliable": True, "max_error_mps": MANUFACTURED_ERROR_TOLERANCE_MPS},
        },
        {
            "id": "affine_interior",
            "position": interior,
            "velocity": affine,
            "query": interior_queries,
            "truth": _affine_field(interior_queries),
            "h": 0.045,
            "dp_m": 0.02,
            "walls": np.empty((0, 3, 3)),
            "expected": {"all_reliable": True, "max_error_mps": MANUFACTURED_ERROR_TOLERANCE_MPS},
        },
        {
            "id": "quadratic_nonaffine_interior",
            "position": interior,
            "velocity": _quadratic_field(interior),
            "query": interior_queries,
            "truth": _quadratic_field(interior_queries),
            "h": 0.045,
            "dp_m": 0.02,
            "hessian_bound_mps_per_m2": 4.0,
            "walls": np.empty((0, 3, 3)),
            "expected": {"all_reliable": True, "budget_covers_truth": True},
        },
    ]

    wall_position = _lattice((-0.08, -0.08, -0.08), (0.08, 0.08, 0.08), 0.02)
    wall_velocity = _constant_field(wall_position)
    wall_query = np.asarray([[0.0, 0.0, -0.025], [0.0, 0.0, 0.025]], dtype=np.float64)
    result.append({
        "id": "wall_two_sides",
        "position": wall_position,
        "velocity": wall_velocity,
        "query": wall_query,
        "truth": _constant_field(wall_query),
        "h": 0.045,
        "dp_m": 0.02,
        "walls": _square_wall(),
        "expected": {"all_reliable": True, "minimum_wall_rejected": 1},
    })
    result.append({
        "id": "wall_opening",
        "position": wall_position,
        "velocity": wall_velocity,
        "query": wall_query,
        "truth": _constant_field(wall_query),
        "h": 0.045,
        "dp_m": 0.02,
        "walls": _wall_with_opening(),
        "expected": {"all_reliable": True, "minimum_cross_side_visible": 1},
    })

    local = _lattice((-0.03, -0.03, -0.03), (0.03, 0.03, 0.03), 0.015)
    separated_position = np.concatenate((local + np.array([-0.13, 0.0, 0.0]), local + np.array([0.13, 0.0, 0.0])))
    separated_velocity = _constant_field(separated_position)
    separated_query = np.asarray([[-0.13, 0.0, 0.0], [0.13, 0.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float64)
    result.append({
        "id": "separated_liquid_clouds",
        "position": separated_position,
        "velocity": separated_velocity,
        "query": separated_query,
        "truth": _constant_field(separated_query),
        "h": 0.045,
        "dp_m": 0.015,
        "walls": np.empty((0, 3, 3)),
        "expected": {"first_two_reliable": True, "last_unknown": True},
    })

    # The clouds are still disconnected under the current-particle graph,
    # while their gap is smaller than 2h.  A midpoint query therefore sees two
    # velocity branches.  It is intentionally a discontinuous field with no
    # single analytic truth at the interface; this row tests that the backend
    # reports the mixing rather than inheriting a source-id partition.
    near_local = _lattice((-0.02, -0.02, -0.02), (0.02, 0.02, 0.02), 0.015)
    near_left = near_local + np.array([-0.065, 0.0, 0.0])
    near_right = near_local + np.array([0.065, 0.0, 0.0])
    near_position = np.concatenate((near_left, near_right))
    near_velocity = np.concatenate((
        np.broadcast_to(np.array([0.30, 0.0, 0.0]), near_left.shape),
        np.broadcast_to(np.array([-0.30, 0.0, 0.0]), near_right.shape),
    ))
    near_query = np.asarray([[0.0, 0.0, 0.0]], dtype=np.float64)
    result.append({
        "id": "near_separated_velocity_branches",
        "position": near_position,
        "velocity": near_velocity,
        "query": near_query,
        "truth": np.full((1, 3), np.nan, dtype=np.float64),
        "h": 0.045,
        "dp_m": 0.015,
        "walls": np.empty((0, 3, 3)),
        "truth_status": "discontinuous_interface_has_no_single_analytic_velocity",
        "expected": {"all_reliable": True, "minimum_component_count": 2, "minimum_branch_separation_mps": 0.4},
    })

    plane = _lattice((-0.06, -0.06, 0.0), (0.06, 0.06, 0.0), 0.02)
    plane_query = np.asarray([[0.0, 0.0, 0.0]], dtype=np.float64)
    result.append({
        "id": "support_rank_deficient",
        "position": plane,
        "velocity": _constant_field(plane),
        "query": plane_query,
        "truth": _constant_field(plane_query),
        "h": 0.06,
        "dp_m": 0.02,
        "walls": np.empty((0, 3, 3)),
        "expected": {"last_unknown": True, "reason": "rank_deficient"},
    })
    result.append({
        "id": "support_empty",
        "position": interior,
        "velocity": constant,
        "query": np.asarray([[1.0, 1.0, 1.0]], dtype=np.float64),
        "truth": _constant_field(np.asarray([[1.0, 1.0, 1.0]], dtype=np.float64)),
        "h": 0.045,
        "dp_m": 0.02,
        "walls": np.empty((0, 3, 3)),
        "expected": {"last_unknown": True, "reason": "no_support"},
    })
    return result


def _percentile(values: np.ndarray, percentile: float):
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    return None if len(values) == 0 else float(np.percentile(values, percentile))


def _case_row(case: Mapping, reconstruction: ReconstructionResult) -> dict:
    query = np.asarray(case["query"], dtype=np.float64)
    truth = np.asarray(case["truth"], dtype=np.float64)
    query_mass = np.ones(len(query), dtype=np.float64)
    error = np.linalg.norm(reconstruction.velocity - truth, axis=1)
    finite_error = np.isfinite(error)
    reliable = reconstruction.reliable
    total_mass = float(np.sum(query_mass))
    reliable_mass = float(np.sum(query_mass[reliable]))
    unknown_mass = float(np.sum(query_mass[~reliable]))
    mass_closure = total_mass - reliable_mass - unknown_mass
    tolerance = MANUFACTURED_ERROR_TOLERANCE_MPS
    false_safe = reliable & finite_error & (error > tolerance)
    false_alarm = (~reliable) & finite_error & (error <= tolerance)
    reasons = reconstruction.diagnostics["failure_reason"]
    reason_counts = {str(name): int(np.count_nonzero(reasons == name)) for name in np.unique(reasons)}
    wall_rejected = reconstruction.diagnostics["wall_rejected_count"]
    candidate_count = reconstruction.diagnostics["candidate_count"]
    connectivity = support_connectivity_diagnostic(
        query, _volume_frame(case["position"], case["velocity"], volume=1.0e-6),
        h=float(case["h"]), dp_m=float(case.get("dp_m", 0.02)), walls=case["walls"],
    )
    budget = reconstruction_error_budget(
        reconstruction,
        hessian_bound_mps_per_m2=case.get("hessian_bound_mps_per_m2"),
        velocity_branch_separation_mps=connectivity["velocity_branch_separation_mps"],
        velocity_branch_within_rms_mps=connectivity["velocity_branch_within_rms_mps"],
        support_component_count=connectivity["component_count"],
    )
    cross_side_visible = None
    if case["id"] in {"wall_two_sides", "wall_opening"}:
        # The manufactured wall is the z=0 plane.  This extra diagnostic is
        # deliberately case-local: the general backend reports geometry
        # agnostically, while the qualification fixture verifies that a full
        # wall blocks cross-side support and its opening does not.
        tree = cKDTree(np.asarray(case["position"], dtype=np.float64))
        cross_side_visible = 0
        for point in query:
            pool = np.asarray(tree.query_ball_point(point, r=2.0 * float(case["h"]), workers=1), dtype=np.int64)
            opposite = np.asarray(case["position"])[pool, 2] * point[2] < 0.0
            if np.any(opposite):
                cross_side_visible += int(np.count_nonzero(_visible_endpoints(
                    point, np.asarray(case["position"])[pool[opposite]], np.asarray(case["walls"]),
                )))
    return {
        "id": case["id"],
        "input_sha256": _array_hash(case["position"], case["velocity"], case["query"], case["walls"]),
        "source_count": int(len(case["position"])),
        "query_count": int(len(query)),
        "h_m": float(case["h"]),
        "dp_m": float(case.get("dp_m", 0.02)),
        "wall_triangle_count": int(len(case["walls"])),
        "truth_status": case.get("truth_status", "analytic_velocity_defined"),
        "reliable_count": int(np.count_nonzero(reliable)),
        "unknown_count": int(np.count_nonzero(~reliable)),
        "unknown_fraction": unknown_mass / total_mass if total_mass else None,
        "reliable_mass_fraction": reliable_mass / total_mass if total_mass else None,
        "mass_closure_abs_error": abs(mass_closure),
        "max_true_error_mps": float(np.max(error[finite_error])) if np.any(finite_error) else None,
        "p95_true_error_mps": _percentile(error[finite_error], 95),
        "false_safe_mass_fraction": float(np.sum(query_mass[false_safe]) / total_mass),
        "false_alarm_mass_fraction": float(np.sum(query_mass[false_alarm]) / total_mass),
        "condition_number_p95": _percentile(reconstruction.diagnostics["condition_number"], 95),
        "condition_number_max": _percentile(reconstruction.diagnostics["condition_number"], 100),
        "effective_sample_size_min": _percentile(reconstruction.diagnostics["effective_sample_size"], 0),
        "geometry_rank_min": int(np.min(reconstruction.diagnostics["geometry_rank"])),
        "support_count_min": int(np.min(reconstruction.diagnostics["support_count"])),
        "connectivity_component_count_max": int(np.max(connectivity["component_count"])),
        "connectivity_multi_component_fraction": float(np.mean(connectivity["component_count"] > 1)),
        "connectivity_distance_gap_max_m": _percentile(connectivity["distance_gap_max_m"], 100),
        "velocity_branch_separation_max_mps": _percentile(connectivity["velocity_branch_separation_mps"], 100),
        "velocity_branch_within_rms_max_mps": _percentile(connectivity["velocity_branch_within_rms_mps"], 100),
        "velocity_branch_count_max": int(np.max(connectivity["velocity_branch_count"])),
        "error_budget": {
            "residual_estimate_p95_mps": _percentile(budget["residual_estimate_mps"], 95),
            "lower_bound_p95_mps": _percentile(budget["lower_bound_mps"], 95),
            "upper_bound_p95_mps": _percentile(budget["upper_bound_mps"], 95),
            "upper_bound_max_mps": _percentile(budget["upper_bound_mps"], 100),
            "bound_status": str(budget["bound_status"].item()),
            "bound_applicable": bool(np.any(finite_error & np.isfinite(budget["upper_bound_mps"]))),
            "true_error_within_upper_bound": bool(np.all(
                (~finite_error)
                | ~np.isfinite(budget["upper_bound_mps"])
                | (error <= budget["upper_bound_mps"] + 1.0e-12)
            )),
        },
        "wall_rejected_total": int(np.sum(wall_rejected)),
        "cross_side_candidate_count": int(np.sum(candidate_count)),
        "cross_side_visible_count": cross_side_visible,
        "reason_counts": reason_counts,
        "expected": _json_value(case["expected"]),
    }


def _evaluate_expected(row: Mapping) -> dict[str, bool]:
    expected = row["expected"]
    checks = {}
    if expected.get("all_reliable"):
        checks["all_reliable"] = row["unknown_count"] == 0
        if "max_error_mps" in expected:
            checks["error_within_tolerance"] = (
                row["max_true_error_mps"] is not None
                and row["max_true_error_mps"] <= expected["max_error_mps"]
            )
    if expected.get("minimum_wall_rejected") is not None:
        checks["wall_rejected"] = row["wall_rejected_total"] >= expected["minimum_wall_rejected"]
    if expected.get("minimum_cross_side_visible") is not None:
        checks["opening_has_support"] = row["cross_side_visible_count"] >= expected["minimum_cross_side_visible"]
    if expected.get("first_two_reliable"):
        checks["clouds_reliable"] = row["reliable_count"] >= 2
    if expected.get("last_unknown"):
        checks["unsupported_unknown"] = row["unknown_count"] >= 1
    if expected.get("reason"):
        checks["failure_reason"] = row["reason_counts"].get(expected["reason"], 0) >= 1
    if expected.get("minimum_component_count") is not None:
        checks["disconnected_current_support"] = row["connectivity_component_count_max"] >= expected["minimum_component_count"]
    if expected.get("minimum_branch_separation_mps") is not None:
        checks["velocity_branches_reported"] = (
            row["velocity_branch_separation_max_mps"] is not None
            and row["velocity_branch_separation_max_mps"] >= expected["minimum_branch_separation_mps"]
        )
    if expected.get("budget_covers_truth"):
        checks["analytic_upper_bound_covers_truth"] = (
            row["error_budget"]["bound_applicable"]
            and row["error_budget"]["true_error_within_upper_bound"]
        )
    return checks


def run_manufactured_qualification(output: str | Path | None = None) -> dict:
    """Run deterministic analytic fields and optionally write a JSON receipt."""
    rows = []
    for case in manufactured_cases():
        frame = _volume_frame(case["position"], case["velocity"], volume=1.0e-6)
        reconstruction = NativeKernelMLS(case["h"]).reconstruct(case["query"], frame, walls=case["walls"])
        row = _case_row(case, reconstruction)
        row["checks"] = _evaluate_expected(row)
        row["passed"] = all(row["checks"].values())
        rows.append(row)
    result = {
        "schema": SCHEMA,
        "backend": BACKEND,
        "qualification_claim": QUALIFICATION_CLAIM,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_sha256": sha256_file(Path(__file__)),
        "formula": dict(WENDLAND_FORMULA),
        "input_policy": dict(INPUT_POLICY),
        "numerical_gate": dict(MLS_GATE),
        "manufactured_truth_tolerance_mps": MANUFACTURED_ERROR_TOLERANCE_MPS,
        "source_policy": "deterministic analytic particle velocities; no CFD frame and no future state",
        "connectivity_diagnostic": dict(CONNECTIVITY_DIAGNOSTIC),
        "cases": rows,
        "mass_closure_abs_error_max": max(row["mass_closure_abs_error"] for row in rows),
        "unknown_fraction_max": max(row["unknown_fraction"] for row in rows),
        "all_cases_passed": all(row["passed"] for row in rows),
        "t2_status": "not_evaluated",
    }
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_json_value(result), indent=2, sort_keys=True) + "\n")
    return result


def _dense_canary_spec(source: str | Path = DENSE_SOURCE_H5) -> dict:
    source = Path(source)
    source_sha = sha256_file(source) if source.exists() else None
    xml_sha = sha256_file(DENSE_PREPARED_XML) if DENSE_PREPARED_XML.exists() else None
    return {
        "schema": SCHEMA,
        "spec_id": "f4-native-kernel-mls-v1-dense-short-canary-s0p3-center-q0p5",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend": BACKEND,
        "qualification_claim": QUALIFICATION_CLAIM,
        "source_role": "qualification_only real F4 dense .002 s CFD source; independent backend research canary",
        "source_h5": str(source),
        "source_sha256": source_sha,
        "prepared_xml": str(DENSE_PREPARED_XML),
        "prepared_xml_sha256": xml_sha,
        "source_time_policy": {
            "frame_indices": [0, 80, 81, 82, 150],
            "reason": "bounded transition canary: initial, pre-failure, first-failure, expansion, final",
            "read_mode": "one current frame per call; no future field or density access",
            "position_policy": "independent explicit Euler: x_(i+1)=x_i+dt_i*v_i; unknown query velocity advances by zero",
            "processed_frames": "sequentially read 0..150 so query positions are current, not stale initial coordinates",
        },
        "query_definition": {
            "count": 512,
            "q": 0.5,
            "construction": "independent 8x8x8 cell-centre grid in continuous drop box low=[.36,.12,.40], size=[.26,.16,.14] m",
            "query_identity": "independent query row; native particle_id is not used",
            "query_mass": "equal unit diagnostic mass; denominator includes every query",
        },
        "kernel": dict(WENDLAND_FORMULA),
        "h_m": F4_H_M,
        "dp_m_metadata": F4_DP_M,
        "fluid_selector": {"dataset": "type", "value": 3, "meaning": "fluid rows only"},
        "walls": {
            "definition": "F4 basin bottom and four side faces; top open",
            "triangles": int(len(f4_resting_pool_walls())),
            "geometry_source": "independent fixed F4 resting-pool dimensions in this module",
        },
        "gate": dict(MLS_GATE),
        "resource_estimate": {
            "device": "CPU",
            "gpu": False,
            "ledger": False,
            "slot": False,
            "source_particle_rows": 217485,
            "query_count": 512,
            "frame_count": 151,
            "selected_output_frames": 5,
            "estimated_peak_rss_mib": 1024,
            "estimated_cpu_seconds": "60-180 for sequential 0..150 processing and five selected outputs; bounded planning estimate until measured",
            "estimated_output_bytes": "less than 2 MiB JSON for five selected frames and 512 queries",
        },
        "argv": [
            ".venv/bin/python", "-m", "scripts.f4_native_kernel_mls",
            "--dense-output", "<attempt_dir>/native_mls_canary.json",
            "--source", str(source), "--h", str(F4_H_M), "--fluid-type", "3",
            "--frame-indices", "0", "80", "81", "82", "150",
        ],
        "execution_constraints": [
            "CPU-only postprocess; do not start GPU CFD",
            "do not write campaign ledger or acquire a slot",
            "do not modify old core_material results or gates",
            "do not claim T1/T2 qualification from this canary",
        ],
        "code_sha256": sha256_file(Path(__file__)),
    }


def write_dense_canary_spec(output: str | Path, source: str | Path = DENSE_SOURCE_H5) -> dict:
    spec = _dense_canary_spec(source)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(spec), indent=2, sort_keys=True) + "\n")
    return spec


def run_dense_canary(source: str | Path, output: str | Path, frame_indices: Iterable[int], h: float, fluid_type: int | None = 3) -> dict:
    """Run an explicitly listed CPU canary with current-frame Euler positions.

    The provider still reads one native frame at a time.  The small sequential
    loop is the material-query part of this canary, not a solver prediction:
    each step uses only the velocity reconstructed from the current frame and
    never reads future density or velocity for that step.
    """
    provider = NativeCurrentFrameProvider(source, fluid_type=fluid_type)
    queries = _f4_query_grid(512, 0.5)
    backend = NativeKernelMLS(h)
    walls = f4_resting_pool_walls()
    selected = sorted(set(int(item) for item in frame_indices))
    if not selected or selected[0] < 0:
        raise ValueError("frame_indices must contain at least one nonnegative frame")
    times = provider.current_times()
    if selected[-1] >= len(times):
        raise IndexError(f"requested frame {selected[-1]} but source has {len(times)} frames")
    selected_set = set(selected)
    current_query = np.array(queries, dtype=np.float64, copy=True)
    rows = []
    for index in range(selected[-1] + 1):
        frame = provider.read_current(index)
        reconstructed = backend.reconstruct(current_query, frame, walls=walls)
        if index not in selected_set:
            finite_velocity = np.where(reconstructed.reliable[:, None], reconstructed.velocity, 0.0)
            if index + 1 < len(times):
                current_query += float(times[index + 1] - times[index]) * finite_velocity
            continue
        reliable = reconstructed.reliable
        total = float(len(current_query))
        reasons = reconstructed.diagnostics["failure_reason"]
        connectivity = support_connectivity_diagnostic(
            current_query, frame, h=h, dp_m=F4_DP_M, walls=walls,
        )
        rows.append({
            "frame_index": index,
            "time_s": frame.time_s,
            "source_sha256": frame.source_sha256,
            "source_rows_total": int(len(frame.position)),
            "source_rows_fluid_valid": int(len(frame.source_row)),
            "query_count": len(current_query),
            "query_position_min_m": np.min(current_query, axis=0).tolist(),
            "query_position_max_m": np.max(current_query, axis=0).tolist(),
            "reliable_count": int(np.count_nonzero(reliable)),
            "unknown_count": int(np.count_nonzero(~reliable)),
            "unknown_fraction": float(np.count_nonzero(~reliable) / total),
            "mass_closed": True,
            "condition_number_p95": _percentile(reconstructed.diagnostics["condition_number"], 95),
            "condition_number_max": _percentile(reconstructed.diagnostics["condition_number"], 100),
            "effective_sample_size_p05": _percentile(reconstructed.diagnostics["effective_sample_size"], 5),
            "support_distance_p95_m": _percentile(reconstructed.diagnostics["support_distance_max_m"], 95),
            "weighted_reconstruction_error_p95_mps": _percentile(reconstructed.diagnostics["weighted_reconstruction_error_mps"], 95),
            "wall_rejected_total": int(np.sum(reconstructed.diagnostics["wall_rejected_count"])),
            "failure_reason_counts": {str(name): int(np.count_nonzero(reasons == name)) for name in np.unique(reasons)},
            "connectivity_diagnostic": {
                "backend": CONNECTIVITY_DIAGNOSTIC["backend"],
                "edge_radius_m": 1.5 * F4_DP_M,
                "multi_component_fraction": float(np.mean(connectivity["component_count"] > 1)),
                "component_count_p95": _percentile(connectivity["component_count"], 95),
                "component_count_max": int(np.max(connectivity["component_count"])),
                "distance_gap_p95_m": _percentile(connectivity["distance_gap_max_m"], 95),
                "velocity_branch_separation_p95_mps": _percentile(connectivity["velocity_branch_separation_mps"], 95),
                "velocity_branch_within_rms_p95_mps": _percentile(connectivity["velocity_branch_within_rms_mps"], 95),
                "velocity_branch_count_max": int(np.max(connectivity["velocity_branch_count"])),
            },
        })
        finite_velocity = np.where(reconstructed.reliable[:, None], reconstructed.velocity, 0.0)
        if index + 1 < len(times):
            current_query += float(times[index + 1] - times[index]) * finite_velocity
    result = {
        "schema": SCHEMA,
        "backend": BACKEND,
        "qualification_claim": QUALIFICATION_CLAIM,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_sha256": sha256_file(Path(__file__)),
        "source": str(Path(source)),
        "source_sha256": provider.source_sha256,
        "frame_indices": [row["frame_index"] for row in rows],
        "query_definition": {
            "count": 512,
            "q": 0.5,
            "construction": "independent F4 8x8x8 drop-box grid",
            "position_policy": "explicit Euler from each current-frame reconstructed velocity; unknown stays in place",
        },
        "binding": backend.binding,
        "rows": rows,
        "t2_status": "not_evaluated",
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(result), indent=2, sort_keys=True) + "\n")
    return result


def run_dense_neighborhood_diagnostic(
    source: str | Path,
    output: str | Path,
    frame_indices: Iterable[int],
    h: float = F4_H_M,
    fluid_type: int | None = 3,
) -> dict:
    """Record native support gaps and cross-source neighborhoods near contact.

    Query positions follow the same causal current-frame Euler overlay as the
    earlier short diagnostic, while source-particle gaps are measured directly
    from each saved native frame.  The initial source label is used only for
    this post-hoc mixing report; it never partitions MLS support or query
    identity.
    """
    source = Path(source)
    provider = NativeCurrentFrameProvider(source, fluid_type=fluid_type)
    selected = sorted(set(int(index) for index in frame_indices))
    if not selected or selected[0] < 0:
        raise ValueError("frame_indices must contain at least one nonnegative frame")
    times = provider.current_times()
    if selected[-1] >= len(times):
        raise IndexError(f"requested frame {selected[-1]} but source has {len(times)} frames")
    with h5py.File(source, "r") as handle:
        if "source_label_initial_mk" not in handle:
            raise ValueError("native source is missing source_label_initial_mk for the diagnostic")
        source_labels = np.asarray(handle["source_label_initial_mk"], dtype=np.int64)
    queries = _f4_query_grid(512, 0.5)
    current_query = np.array(queries, dtype=np.float64, copy=True)
    backend = NativeKernelMLS(h)
    walls = f4_resting_pool_walls()
    selected_set = set(selected)
    rows = []
    old_support_radius = 0.03
    native_support_radius = 2.0 * float(h)
    for index in range(selected[-1] + 1):
        frame = provider.read_current(index)
        reconstructed = backend.reconstruct(current_query, frame, walls=walls)
        tree = cKDTree(frame.fluid_position)
        source_labels_fluid = source_labels[frame.source_row]
        if index in selected_set:
            old_counts = np.asarray(tree.query_ball_point(
                current_query, r=old_support_radius, eps=0.0, workers=1,
                return_length=True,
            ), dtype=np.int64)
            native_counts = np.asarray(tree.query_ball_point(
                current_query, r=native_support_radius, eps=0.0, workers=1,
                return_length=True,
            ), dtype=np.int64)
            mixing = np.zeros(len(current_query), dtype=bool)
            for row, pool in enumerate(tree.query_ball_point(
                    current_query, r=native_support_radius, eps=0.0, workers=1,
                    return_sorted=True)):
                labels = np.unique(source_labels_fluid[np.asarray(pool, dtype=np.int64)])
                mixing[row] = len(labels) > 1
            drop = frame.fluid_position[source_labels_fluid == np.max(source_labels_fluid)]
            pool = frame.fluid_position[source_labels_fluid != np.max(source_labels_fluid)]
            gap = np.full(len(drop), np.nan, dtype=np.float64)
            if len(drop) and len(pool):
                gap = cKDTree(pool).query(drop, k=1, workers=1)[0]
            connectivity = support_connectivity_diagnostic(
                current_query, frame, h=h, dp_m=F4_DP_M, walls=walls,
            )
            rows.append({
                "frame_index": index,
                "time_s": float(frame.time_s),
                "source_sha256": frame.source_sha256,
                "query_position_z_p05_m": float(np.percentile(current_query[:, 2], 5)),
                "query_position_z_p50_m": float(np.percentile(current_query[:, 2], 50)),
                "query_position_z_p95_m": float(np.percentile(current_query[:, 2], 95)),
                "native_drop_pool_gap_m": {
                    "min": float(np.min(gap)) if len(gap) else None,
                    "p05": _percentile(gap, 5),
                    "p50": _percentile(gap, 50),
                    "p95": _percentile(gap, 95),
                },
                "support_radius_m": native_support_radius,
                "old_overlay_radius_m": old_support_radius,
                "query_candidate_count_old_radius_p05": _percentile(old_counts, 5),
                "query_candidate_count_old_radius_p50": _percentile(old_counts, 50),
                "query_candidate_count_old_radius_p95": _percentile(old_counts, 95),
                "query_candidate_count_native_radius_p05": _percentile(native_counts, 5),
                "query_candidate_count_native_radius_p50": _percentile(native_counts, 50),
                "query_candidate_count_native_radius_p95": _percentile(native_counts, 95),
                "query_support_cross_initial_source_fraction": float(np.mean(mixing)),
                "numerical_reliable_fraction": float(np.mean(reconstructed.reliable)),
                "weighted_reconstruction_error_p95_mps": _percentile(
                    reconstructed.diagnostics["weighted_reconstruction_error_mps"], 95,
                ),
                "weighted_reconstruction_error_max_mps": _percentile(
                    reconstructed.diagnostics["weighted_reconstruction_error_mps"], 100,
                ),
                "support_connectivity": {
                    "multi_component_fraction": float(np.mean(connectivity["component_count"] > 1)),
                    "component_count_p95": _percentile(connectivity["component_count"], 95),
                    "component_count_max": int(np.max(connectivity["component_count"])),
                    "velocity_branch_separation_p95_mps": _percentile(
                        connectivity["velocity_branch_separation_mps"], 95,
                    ),
                    "velocity_branch_within_rms_p95_mps": _percentile(
                        connectivity["velocity_branch_within_rms_mps"], 95,
                    ),
                },
            })
        finite_velocity = np.where(reconstructed.reliable[:, None], reconstructed.velocity, 0.0)
        if index + 1 < len(times):
            current_query += float(times[index + 1] - times[index]) * finite_velocity
    result = {
        "schema": SCHEMA,
        "diagnostic": "f4_native_neighbor_gap_and_current_connectivity_v1",
        "backend": BACKEND,
        "qualification_claim": QUALIFICATION_CLAIM,
        "code_sha256": sha256_file(Path(__file__)),
        "source": str(source),
        "source_sha256": provider.source_sha256,
        "frame_indices": [row["frame_index"] for row in rows],
        "query_definition": {
            "count": 512,
            "q": 0.5,
            "position_policy": "causal explicit Euler overlay using current-frame numerical support only",
            "query_identity": "independent geometric seeds; no native particle id partition",
        },
        "source_label_use": "initial label only for post-hoc gap/mixing attribution; it never filters support",
        "contact_context": {
            "pool_surface_z_m": 0.18,
            "physical_observations_contact": "5% initial-drop-mass-below-pool proxy, not first geometric contact",
            "near_contact_window": "frame 81 at .162 s precedes first saved any-drop crossing frame 85 at .170005 s and lies inside the ballistic approach interval",
        },
        "rows": rows,
        "t2_status": "not_evaluated",
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(result), indent=2, sort_keys=True) + "\n")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--manufactured-output", type=Path)
    group.add_argument("--write-canary-spec", type=Path)
    group.add_argument("--dense-output", type=Path)
    group.add_argument("--trace-output", type=Path)
    group.add_argument("--neighborhood-output", type=Path)
    parser.add_argument("--source", type=Path, default=DENSE_SOURCE_H5)
    parser.add_argument("--h", type=float, default=F4_H_M)
    parser.add_argument("--fluid-type", type=int, default=3)
    parser.add_argument("--frame-indices", type=int, nargs="+", default=[0, 80, 81, 82, 150])
    parser.add_argument("--query-count", type=int, default=512)
    parser.add_argument("--q", type=float, default=0.5)
    parser.add_argument("--substeps", type=int, default=4)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--kill-after", type=int)
    parser.add_argument("--kill-after-checkpoint-publish", type=int)
    parser.add_argument("--hessian-bound", type=float)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args(argv)
    if args.manufactured_output is not None:
        result = run_manufactured_qualification(args.manufactured_output)
    elif args.write_canary_spec is not None:
        result = write_dense_canary_spec(args.write_canary_spec, args.source)
    elif args.trace_output is not None:
        result = trace_native_material(
            args.source, args.trace_output, h=args.h, fluid_type=args.fluid_type,
            query_count=args.query_count, q=args.q, substeps=args.substeps,
            stop_after=args.stop_after, resume=args.resume, kill_after=args.kill_after,
            kill_after_checkpoint_publish=args.kill_after_checkpoint_publish,
            hessian_bound_mps_per_m2=args.hessian_bound, summary_output=args.summary_output,
        )
    elif args.neighborhood_output is not None:
        result = run_dense_neighborhood_diagnostic(
            args.source, args.neighborhood_output, args.frame_indices, args.h, args.fluid_type,
        )
    else:
        result = run_dense_canary(args.source, args.dense_output, args.frame_indices, args.h, args.fluid_type)
    print(json.dumps(_json_value(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
