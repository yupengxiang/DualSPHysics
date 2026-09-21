"""F3 native-volume MLS feasibility candidate.

This module is an independent, CPU-only feasibility backend for the accepted
F3 native reference HDF5 files.  It reads only the selected current native
frame (position, velocity, mass, density, valid, and fluid type) and weights a
complete compact Wendland support by ``mass / density``.  It does not use
native particle identity for seed identity, source grouping, or termination.

The short trace is diagnostic evidence only.  It binds the registered F3
geometry and the original F3 support gate as a comparison field, while the
native-volume MLS numerical support checks have their own versioned binding.
No ledger, scheduler slot, GPU, or CFD solver is touched by this module.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import re
import signal
import time
from typing import Mapping

import h5py
import numpy as np
from scipy.spatial import cKDTree

from scripts.passive_tracers import box_surface_triangles, segment_visibility


SCHEMA = "core.material.f3.native_volume_mls.v1"
BACKEND = "f3_native_volume_mls_wendland_mass_density_v1"
TRACE_SCHEMA = "core.material.f3.native_volume_mls.trace.v1"
TRACE_BACKEND = "f3_native_volume_mls_current_frame_rk4_v1"
QUALIFICATION_CLAIM = "none"

F3_COEFH = 0.91924
F3_FLUID_TYPE = 3
F3_WALL_LOW_M = np.array([-0.45, -0.09, 0.0], dtype=np.float64)
F3_WALL_HIGH_M = np.array([0.45, 0.09, 0.51], dtype=np.float64)
F3_SOURCE_LOW_M = np.array([-0.45, -0.09, 0.0], dtype=np.float64)
F3_SOURCE_SIZE_M = np.array([0.9, 0.18, 0.09], dtype=np.float64)
F3_OUTPUT_INTERVAL_S = 0.01
F3_KERNEL_ID = 2
F3_KERNEL_NAME = "Wendland"

# This is copied from the registered F3 material diagnostic specification for
# comparison only.  The candidate does not silently reinterpret a Shepard
# residual threshold as a native MLS qualification gate.
F3_ORIGINAL_GATE = {
    "minimum_effective_sample_size": 4.0,
    "minimum_geometry_rank": 3,
    "minimum_anisotropy": 0.005,
    "maximum_reconstruction_error_mps": 0.05 * math.sqrt(9.81 * 0.09),
    "maximum_support_distance_m": 0.03,
}

# Candidate checks are numerical support checks for this version.  They are
# deliberately versioned separately from F3_ORIGINAL_GATE.
MLS_GATE = {
    "minimum_support_count": 4,
    "minimum_effective_sample_size": 4.0,
    "minimum_geometry_rank": 4,
    "maximum_condition_number": 1.0e10,
    "svd_relative_cutoff": 1.0e-12,
}

WENDLAND_FORMULA = {
    "family": "quintic_wendland_c2",
    "dimension": 3,
    "argument": "q=r/h",
    "support": "0 <= q <= 2",
    "expression": "W(r,h)=21/(16*pi*h^3)*(1-q/2)^4*(1+2*q)",
    "normalisation": "21/(16*pi*h^3)",
    "official_f3_binding": "generated F3 XML parameter Kernel=2 (Wendland)",
}

HISTORY_DATASETS = (
    "time", "position", "reliable", "permanent_unknown", "first_passage",
    "return_time", "residence_opposite", "returned", "support_count",
    "effective_sample_size", "geometry_rank", "condition_number",
    "anisotropy", "reconstruction_error_mps", "old_gate_pass",
    "candidate_support_pass", "candidate_count", "wall_rejected_count",
    "native_mass_kg", "seed_mass_closure_error",
)

CHECKPOINT_SCHEMA = "core.material.f3.native_volume_mls.checkpoint.v1"
CHECKPOINT_FIELDS = (
    "position", "reliable", "permanent_unknown", "first_passage", "return_time",
    "residence_opposite", "residence_left", "residence_right", "returned",
    "failure_reason",
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def array_hash(*values: np.ndarray) -> str:
    digest = hashlib.sha256()
    for value in values:
        array = np.ascontiguousarray(np.asarray(value))
        digest.update(canonical({"dtype": array.dtype.str, "shape": array.shape}).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def _finite_array(name: str, value, shape: tuple[int, ...] | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if shape is not None and array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    return np.array(array, dtype=np.float64, copy=True)


def _positive_integer(value, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or int(value) < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def h_from_dp(dp_m: float) -> float:
    dp_m = float(dp_m)
    if not np.isfinite(dp_m) or dp_m <= 0.0:
        raise ValueError("dp_m must be finite and positive")
    return F3_COEFH * math.sqrt(3.0) * dp_m


def wendland_quintic_c2_3d(distance, h: float) -> np.ndarray:
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


def f3_walls() -> np.ndarray:
    return np.asarray(
        box_surface_triangles(F3_WALL_LOW_M, F3_WALL_HIGH_M,
                              sides=("xmin", "xmax", "ymin", "ymax", "zmin")),
        dtype=np.float64,
    )


def seeds_f3(count: int = 512) -> np.ndarray:
    count = int(count)
    if count not in (512, 4096):
        raise ValueError("F3 candidate seed count must be 512 or 4096")
    shape = {512: (16, 8, 4), 4096: (32, 16, 8)}[count]
    axes = [low + (np.arange(n, dtype=np.float64) + 0.5) * size / n
            for low, size, n in zip(F3_SOURCE_LOW_M, F3_SOURCE_SIZE_M, shape)]
    return np.ascontiguousarray(
        np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3),
        dtype=np.float64,
    )


def source_labels(initial: np.ndarray) -> np.ndarray:
    initial = _finite_array("initial", initial)
    return (initial[:, 0] >= 0.0).astype(np.int8)


def _segment_visibility(query: np.ndarray, points: np.ndarray, walls: np.ndarray) -> np.ndarray:
    if len(walls) == 0 or len(points) == 0:
        return np.ones(len(points), dtype=bool)
    # passive_tracers.segment_visibility accepts a batch of query points;
    # this backend evaluates one query row at a time.
    return np.asarray(segment_visibility(np.asarray(query, dtype=np.float64)[None, :],
                                         points, walls), dtype=bool)[0]


class F3CurrentFrame:
    """Immutable current native fluid arrays; no provider or future frame."""

    __slots__ = ("position", "velocity", "mass", "density", "valid", "frame_index", "time_s")

    def __init__(self, position, velocity, mass, density, valid, *, frame_index: int, time_s: float):
        position = _finite_array("position", position)
        velocity = _finite_array("velocity", velocity, position.shape)
        mass = _finite_array("mass", mass, (len(position),))
        density = _finite_array("density", density, (len(position),))
        valid = np.asarray(valid, dtype=bool)
        if valid.shape != (len(position),):
            raise ValueError("valid must have shape [N]")
        if np.any(mass <= 0.0) or np.any(density <= 0.0):
            raise ValueError("current native mass and density must be positive")
        self.position = np.array(position, copy=True)
        self.velocity = np.array(velocity, copy=True)
        self.mass = np.array(mass, copy=True)
        self.density = np.array(density, copy=True)
        self.valid = np.array(valid, copy=True)
        for value in (self.position, self.velocity, self.mass, self.density, self.valid):
            value.setflags(write=False)
        self.frame_index = int(frame_index)
        self.time_s = float(time_s)

    @property
    def volume(self) -> np.ndarray:
        return self.mass / self.density


class F3ReferenceProvider:
    """Sequential two-frame cache whose field() exposes one current frame."""

    provider_role = "reference_native_saved_frames"

    def __init__(self, source: str | Path, *, fluid_type: int = F3_FLUID_TYPE, max_cache: int = 2):
        self.source = Path(source).resolve()
        self.source_sha256 = sha256_file(self.source)
        self.h5 = h5py.File(self.source, "r")
        self.fluid_type = int(fluid_type)
        self.cache: OrderedDict[int, F3CurrentFrame] = OrderedDict()
        required = {"time", "position", "velocity", "mass", "density", "valid", "type"}
        missing = sorted(required - set(self.h5))
        if missing:
            self.close()
            raise ValueError(f"F3 source is missing native datasets: {missing}")
        self.times = np.asarray(self.h5["time"][:], dtype=np.float64)
        if (self.times.ndim != 1 or len(self.times) < 2 or not np.isfinite(self.times).all()
                or np.any(np.diff(self.times) <= 0.0)):
            self.close()
            raise ValueError("F3 source time must be strictly increasing")
        n = self.h5["position"].shape[1]
        expected_shapes = {
            "position": (len(self.times), n, 3),
            "velocity": (len(self.times), n, 3),
            "mass": (len(self.times), n),
            "density": (len(self.times), n),
            "valid": (len(self.times), n),
            "type": (len(self.times), n),
        }
        for name, shape in expected_shapes.items():
            if self.h5[name].shape != shape:
                self.close()
                raise ValueError(f"F3 source {name} has shape {self.h5[name].shape}, expected {shape}")
        self.particle_count = int(n)
        self.frame_count = int(len(self.times))
        self.max_cache = _positive_integer(max_cache, "max_cache")
        self.loaded_indices: list[int] = []

    def frame(self, index: int) -> F3CurrentFrame:
        index = int(index)
        if not 0 <= index < self.frame_count:
            raise IndexError(f"F3 frame {index} is outside 0..{self.frame_count - 1}")
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        h = self.h5
        position = np.asarray(h["position"][index], dtype=np.float64)
        velocity = np.asarray(h["velocity"][index], dtype=np.float64)
        mass = np.asarray(h["mass"][index], dtype=np.float64)
        density = np.asarray(h["density"][index], dtype=np.float64)
        valid = np.asarray(h["valid"][index], dtype=bool)
        fluid = np.asarray(h["type"][index], dtype=np.float64) == self.fluid_type
        valid &= fluid
        valid &= np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
        valid &= np.isfinite(mass) & (mass > 0.0) & np.isfinite(density) & (density > 0.0)
        frame = F3CurrentFrame(
            position[valid], velocity[valid], mass[valid], density[valid],
            np.ones(int(np.count_nonzero(valid)), dtype=bool),
            frame_index=index, time_s=float(self.times[index]),
        )
        self.cache[index] = frame
        self.cache.move_to_end(index)
        self.loaded_indices.append(index)
        while len(self.cache) > self.max_cache:
            self.cache.popitem(last=False)
        return frame

    def close(self) -> None:
        handle = getattr(self, "h5", None)
        if handle is not None:
            handle.close()
            self.h5 = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


class MLSResult:
    __slots__ = ("velocity", "support_count", "candidate_count", "wall_rejected_count",
                 "effective_sample_size", "geometry_rank", "condition_number", "anisotropy",
                 "reconstruction_error_mps", "reliable", "old_gate_pass", "candidate_support_pass",
                 "failure_reason")

    def __init__(self, velocity, support_count, candidate_count, wall_rejected_count,
                 effective_sample_size, geometry_rank, condition_number, anisotropy,
                 reconstruction_error_mps, reliable, old_gate_pass, candidate_support_pass,
                 failure_reason):
        self.velocity = velocity
        self.support_count = support_count
        self.candidate_count = candidate_count
        self.wall_rejected_count = wall_rejected_count
        self.effective_sample_size = effective_sample_size
        self.geometry_rank = geometry_rank
        self.condition_number = condition_number
        self.anisotropy = anisotropy
        self.reconstruction_error_mps = reconstruction_error_mps
        self.reliable = reliable
        self.old_gate_pass = old_gate_pass
        self.candidate_support_pass = candidate_support_pass
        self.failure_reason = failure_reason


class F3NativeVolumeMLS:
    """F3-specific native-volume affine MLS reconstruction."""

    def __init__(self, h_m: float, *, gate: dict | None = None):
        self.h_m = float(h_m)
        if not np.isfinite(self.h_m) or self.h_m <= 0.0:
            raise ValueError("h_m must be finite and positive")
        self.gate = dict(MLS_GATE if gate is None else gate)
        if self.gate["minimum_support_count"] < 4:
            raise ValueError("minimum_support_count must support 3-D affine MLS")

    @property
    def binding(self) -> dict:
        return {
            "schema": SCHEMA,
            "backend": BACKEND,
            "h_m": self.h_m,
            "support_radius_m": 2.0 * self.h_m,
            "weights": "(mass/density)*Wendland_quintic_c2_3d(distance,h)",
            "kernel": dict(WENDLAND_FORMULA),
            "fit": "weighted_affine_MLS_SVD_on_[1,dx/h,dy/h,dz/h]",
            "support_selection": "all_current_valid_fluid_rows_within_2h_after_F3_finite_wall_visibility",
            "candidate_gate": dict(self.gate),
            "original_f3_gate_comparison": dict(F3_ORIGINAL_GATE),
            "future_state": "forbidden",
            "native_particle_id": "not used for query identity or termination",
        }

    def reconstruct(self, query: np.ndarray, frame: F3CurrentFrame, walls: np.ndarray) -> MLSResult:
        query = _finite_array("query", query)
        if query.ndim != 2 or query.shape[1:] != (3,):
            raise ValueError("query must have shape [Q,3]")
        points, values, volumes = frame.position, frame.velocity, frame.volume
        count = len(query)
        prediction = np.full((count, 3), np.nan, dtype=np.float64)
        support_count = np.zeros(count, dtype=np.int64)
        candidate_count = np.zeros(count, dtype=np.int64)
        wall_rejected_count = np.zeros(count, dtype=np.int64)
        effective = np.full(count, np.nan, dtype=np.float64)
        rank = np.zeros(count, dtype=np.int8)
        condition = np.full(count, np.inf, dtype=np.float64)
        anisotropy = np.zeros(count, dtype=np.float64)
        residual = np.full(count, np.inf, dtype=np.float64)
        reliable = np.zeros(count, dtype=bool)
        old_pass = np.zeros(count, dtype=bool)
        reason = np.full(count, "no_support", dtype=object)
        tree = cKDTree(points)
        pools = tree.query_ball_point(query, r=2.0 * self.h_m, p=2.0, eps=0.0,
                                      workers=1, return_sorted=True)
        for row, pool in enumerate(pools):
            candidate = np.asarray(pool, dtype=np.int64)
            candidate_count[row] = len(candidate)
            if not len(candidate):
                continue
            visible = _segment_visibility(query[row], points[candidate], walls)
            wall_rejected_count[row] = int(np.count_nonzero(~visible))
            candidate = candidate[visible]
            if not len(candidate):
                reason[row] = "wall_occluded"
                continue
            delta = points[candidate] - query[row]
            distance2 = np.einsum("ij,ij->i", delta, delta)
            distance = np.sqrt(np.maximum(distance2, 0.0))
            weights = volumes[candidate] * wendland_quintic_c2_3d(distance, self.h_m)
            keep = np.isfinite(weights) & (weights > 0.0)
            candidate, delta, distance2, distance, weights = (value[keep] for value in
                                                               (candidate, delta, distance2, distance, weights))
            if not len(candidate):
                reason[row] = "zero_weight"
                continue
            support_count[row] = len(candidate)
            weight_total = float(weights.sum())
            effective[row] = weight_total * weight_total / float(np.sum(weights * weights))
            center = np.sum(points[candidate] * weights[:, None], axis=0) / weight_total
            centered = points[candidate] - center
            covariance = (centered * weights[:, None]).T @ centered / weight_total
            eig = np.linalg.eigvalsh(covariance)
            largest = float(np.max(eig))
            tol = max(largest * 1e-8, 1e-14)
            positive = eig[eig > tol]
            rank_cov = len(positive)
            anisotropy[row] = float(positive.min() / largest) if rank_cov and largest > 0 else 0.0
            design = np.column_stack((np.ones(len(candidate)), delta / self.h_m))
            sqrt_w = np.sqrt(weights)
            weighted_design = design * sqrt_w[:, None]
            weighted_values = values[candidate] * sqrt_w[:, None]
            try:
                _, singular, _ = np.linalg.svd(weighted_design, full_matrices=False)
                cutoff = singular[0] * float(self.gate["svd_relative_cutoff"])
                rank[row] = int(np.count_nonzero(singular > cutoff))
                condition[row] = (float(singular[0] / singular[-1])
                                  if len(singular) == 4 and singular[-1] > cutoff else np.inf)
                coefficients, _, _, _ = np.linalg.lstsq(
                    weighted_design, weighted_values, rcond=float(self.gate["svd_relative_cutoff"])
                )
                prediction[row] = coefficients[0]
                fit = design @ coefficients
                residual[row] = math.sqrt(float(np.sum(weights * np.sum((fit - values[candidate]) ** 2, axis=1)) / weight_total))
            except np.linalg.LinAlgError:
                reason[row] = "svd_failure"
                continue
            finite = np.isfinite(prediction[row]).all() and np.isfinite(residual[row])
            candidate_ok = (
                finite
                and rank[row] >= int(self.gate["minimum_geometry_rank"])
                and effective[row] >= float(self.gate["minimum_effective_sample_size"])
                and support_count[row] >= int(self.gate["minimum_support_count"])
                and condition[row] <= float(self.gate["maximum_condition_number"])
            )
            reliable[row] = candidate_ok
            reason[row] = "reliable" if candidate_ok else (
                "rank_deficient" if rank[row] < int(self.gate["minimum_geometry_rank"])
                else "low_effective_sample_size" if effective[row] < float(self.gate["minimum_effective_sample_size"])
                else "insufficient_support" if support_count[row] < int(self.gate["minimum_support_count"])
                else "ill_conditioned" if condition[row] > float(self.gate["maximum_condition_number"])
                else "nonfinite_fit"
            )
            old_pass[row] = (
                finite
                and effective[row] >= F3_ORIGINAL_GATE["minimum_effective_sample_size"]
                and rank_cov >= F3_ORIGINAL_GATE["minimum_geometry_rank"]
                and anisotropy[row] >= F3_ORIGINAL_GATE["minimum_anisotropy"]
                and residual[row] <= F3_ORIGINAL_GATE["maximum_reconstruction_error_mps"]
                and float(np.min(distance)) <= F3_ORIGINAL_GATE["maximum_support_distance_m"]
            )
        return MLSResult(
            prediction, support_count, candidate_count, wall_rejected_count,
            effective, rank, condition, anisotropy, residual, reliable, old_pass,
            reliable.copy(), reason,
        )


def _crossing_fraction(x0: float, x1: float) -> float:
    delta = float(x1 - x0)
    if abs(delta) <= np.finfo(np.float64).eps:
        return 0.0
    return float(np.clip(-x0 / delta, 0.0, 1.0))


def _advance_events(state: dict[str, np.ndarray], start: np.ndarray, end: np.ndarray,
                    segment_time: float, dt: float, usable: np.ndarray, origin: np.ndarray) -> None:
    side0 = start[:, 0] >= 0.0
    side1 = end[:, 0] >= 0.0
    changed = side0 != side1
    fraction = np.asarray([_crossing_fraction(a, b) if c else 0.0
                           for a, b, c in zip(start[:, 0], end[:, 0], changed)], dtype=np.float64)
    first = np.isnan(state["first_passage"])
    crossing = usable & changed & (side1 != origin) & first
    state["first_passage"][crossing] = segment_time + fraction[crossing] * dt
    returning = usable & changed & (side1 == origin) & ~first & ~state["returned"]
    state["return_time"][returning] = segment_time + fraction[returning] * dt
    state["returned"][returning] = True
    # Residence is time spent in the opposite x half; linear path gives the
    # exact fraction for each accepted RK segment.
    left_fraction = np.where(changed, np.where(~side0, fraction, 1.0 - fraction), (~side0).astype(float))
    right_fraction = np.where(changed, np.where(side0, fraction, 1.0 - fraction), side0.astype(float))
    left_fraction = np.where(usable, left_fraction, 0.0)
    right_fraction = np.where(usable, right_fraction, 0.0)
    state["residence_left"] += left_fraction * dt
    state["residence_right"] += right_fraction * dt
    state["residence_opposite"] += np.where(origin, left_fraction, right_fraction) * dt


def _new_state(initial: np.ndarray, labels: np.ndarray) -> dict[str, np.ndarray]:
    n = len(initial)
    return {
        "position": np.array(initial, copy=True),
        "reliable": np.zeros(n, dtype=bool),
        "permanent_unknown": np.ones(n, dtype=bool),
        "first_passage": np.full(n, np.nan, dtype=np.float64),
        "return_time": np.full(n, np.nan, dtype=np.float64),
        "residence_opposite": np.zeros(n, dtype=np.float64),
        "residence_left": np.zeros(n, dtype=np.float64),
        "residence_right": np.zeros(n, dtype=np.float64),
        "returned": np.zeros(n, dtype=bool),
        "origin": labels.astype(bool),
    }


def _trace_binding(source: Path, provider: F3ReferenceProvider, tracer: F3NativeVolumeMLS,
                   initial: np.ndarray, labels: np.ndarray, substeps: int,
                   stop_after: int, walls: np.ndarray) -> dict:
    return {
        "schema": TRACE_SCHEMA,
        "backend": TRACE_BACKEND,
        "static_backend": tracer.binding,
        "source_h5": str(source.resolve()),
        "source_sha256": provider.source_sha256,
        "source_semantics": provider.provider_role,
        "frame_policy": "current native frame only; all RK stages for interval i use frame i",
        "future_velocity": "forbidden",
        "future_density": "forbidden",
        "substeps": int(substeps),
        "stop_after": int(stop_after),
        "query_count": int(len(initial)),
        "seed_hash": array_hash(initial, labels),
        "source_definition": {
            "kind": "continuous_halfspace",
            "axis": 0,
            "boundary_m": 0.0,
            "source_0": "x < 0",
            "source_1": "x >= 0",
        },
        "walls_sha256": array_hash(walls),
        "event_definition": {
            "first_passage": "continuous crossing of x=0 into opposite source half on accepted linear RK segment",
            "return": "first later crossing back to the seed's origin half",
            "residence": "accepted segment time in the opposite source half",
        },
        "checkpoint": {
            "schema": CHECKPOINT_SCHEMA,
            "ordering": "HDF5 frame append and flush, immutable generation publish, then atomic manifest replace",
            "resume_source_of_truth": "last manifest generation; HDF5 is truncated to its committed frame",
            "generation_policy": "content-addressed NPZ generations are never overwritten",
        },
        "qualification_claim": QUALIFICATION_CLAIM,
        "material_reliability": "not established by numerical support diagnostics",
    }


def _create_output(handle, initial, labels, tracer_ids, binding, nframes, n):
    handle.attrs["schema"] = TRACE_SCHEMA
    handle.attrs["trace_backend"] = TRACE_BACKEND
    handle.attrs["binding"] = canonical(binding)
    handle.attrs["committed"] = -1
    handle.attrs["checkpoint_schema"] = CHECKPOINT_SCHEMA
    handle.attrs["checkpoint_manifest"] = ""
    handle.attrs["qualification_claim"] = QUALIFICATION_CLAIM
    handle.attrs["material_reliability"] = "not_established_by_numerical_support"
    handle.create_dataset("initial_position", data=initial)
    handle.create_dataset("source_label", data=labels)
    handle.create_dataset("tracer_id", data=np.asarray(tracer_ids, dtype=h5py.string_dtype("utf-8")))
    specs = {
        "time": ((), "f8"),
        "position": ((n, 3), "f8"),
        "reliable": ((n,), "?"),
        "permanent_unknown": ((n,), "?"),
        "first_passage": ((n,), "f8"),
        "return_time": ((n,), "f8"),
        "residence_opposite": ((n,), "f8"),
        "returned": ((n,), "?"),
        "support_count": ((n,), "i8"),
        "effective_sample_size": ((n,), "f8"),
        "geometry_rank": ((n,), "i1"),
        "condition_number": ((n,), "f8"),
        "anisotropy": ((n,), "f8"),
        "reconstruction_error_mps": ((n,), "f8"),
        "old_gate_pass": ((n,), "?"),
        "candidate_support_pass": ((n,), "?"),
        "candidate_count": ((n,), "i8"),
        "wall_rejected_count": ((n,), "i8"),
        "native_mass_kg": ((), "f8"),
        "seed_mass_closure_error": ((), "f8"),
    }
    for name, (shape, dtype) in specs.items():
        handle.create_dataset(name, shape=(0,) + shape, maxshape=(None,) + shape,
                              dtype=dtype, chunks=(1,) + shape)
    handle.create_dataset("failure_reason", shape=(0, n), maxshape=(None, n),
                          dtype=h5py.string_dtype("utf-8"), chunks=(1, n))
    handle.flush()


def _append_frame(handle, frame: int, time_s: float, values: dict):
    frame = int(frame)
    for name in HISTORY_DATASETS + ("failure_reason",):
        handle[name].resize(frame + 1, axis=0)
        handle[name][frame] = time_s if name == "time" else values[name]
    handle.attrs["committed"] = frame
    handle.flush()


def _fsync_directory(path: Path) -> None:
    """Best-effort directory durability for atomic generation publication."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_hdf5(handle) -> None:
    """Flush HDF5 and its VFD when h5py exposes a file descriptor."""
    handle.flush()
    try:
        fd = handle.id.get_vfd_handle()
        if isinstance(fd, tuple):
            fd = fd[0]
        if isinstance(fd, int) and fd >= 0:
            os.fsync(fd)
    except (AttributeError, OSError, TypeError, ValueError):
        # The HDF5 VFD may not expose a POSIX descriptor.  HDF5 flush remains
        # the available durability operation in that environment.
        pass


def _checkpoint_state(state: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Return a pickle-free immutable representation of trace state."""
    result = {}
    for name in CHECKPOINT_FIELDS:
        if name not in state:
            raise ValueError(f"checkpoint state is missing {name}")
        value = np.asarray(state[name])
        if name == "failure_reason":
            value = np.asarray([str(item) for item in value], dtype="U64")
        result[name] = np.ascontiguousarray(value)
    return result


def _checkpoint_state_hash(state: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name in CHECKPOINT_FIELDS:
        value = np.ascontiguousarray(np.asarray(state[name]))
        digest.update(name.encode("utf-8"))
        digest.update(canonical({"dtype": value.dtype.str, "shape": value.shape}).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def _checkpoint_paths(output: Path) -> tuple[Path, Path]:
    return (Path(str(output) + ".checkpoint.json"), output.parent)


def _checkpoint_publish(output: Path, binding: Mapping, frame: int,
                        state: Mapping[str, np.ndarray], seed_hash: str,
                        diagnostics: Mapping[str, int], *,
                        fault_after_generation: bool = False) -> dict:
    """Publish one content-addressed state generation and its manifest.

    The last manifest always points to a complete immutable generation.  The
    HDF5 frame is written before this function is called.  A kill after the
    generation rename but before manifest replacement therefore leaves the
    previous manifest usable; a kill after HDF5 append but before generation
    publication leaves an extra HDF5 row that resume truncates to the previous
    manifest frame.
    """
    manifest_path, directory = _checkpoint_paths(output)
    snapshot = _checkpoint_state(state)
    state_sha256 = _checkpoint_state_hash(snapshot)
    generation = output.with_name(
        f"{output.name}.checkpoint.{int(frame):08d}.{state_sha256[:24]}.npz"
    )
    if not generation.exists():
        temporary = generation.with_name(
            generation.name + f".partial.{os.getpid()}.npz"
        )
        np.savez_compressed(temporary, **snapshot)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, generation)
        _fsync_directory(directory)
    else:
        with np.load(generation, allow_pickle=False) as archive:
            existing = {name: np.array(archive[name], copy=True) for name in CHECKPOINT_FIELDS}
        if _checkpoint_state_hash(existing) != state_sha256:
            raise ValueError("existing native F3 checkpoint generation is corrupt")
    generation_sha256 = sha256_file(generation)
    if fault_after_generation:
        os.kill(os.getpid(), signal.SIGKILL)
    record = {
        "schema": CHECKPOINT_SCHEMA,
        "binding_sha256": hashlib.sha256(canonical(binding).encode()).hexdigest(),
        "seed_hash": seed_hash,
        "committed_frame": int(frame),
        "fields": list(CHECKPOINT_FIELDS),
        "state_sha256": state_sha256,
        "file_sha256": generation_sha256,
        "checkpoint_npz": str(generation),
        "generation": generation.name,
        "stage_failure_counts": {str(key): int(value) for key, value in diagnostics.items()},
    }
    temporary_manifest = manifest_path.with_name(
        manifest_path.name + f".partial.{os.getpid()}"
    )
    with temporary_manifest.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_manifest, manifest_path)
    _fsync_directory(directory)
    return record


def _checkpoint_read(output: Path, binding: Mapping, seed_hash: str):
    manifest_path, _ = _checkpoint_paths(output)
    if not manifest_path.exists():
        return None
    record = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_binding = hashlib.sha256(canonical(binding).encode()).hexdigest()
    if (record.get("schema") != CHECKPOINT_SCHEMA
            or record.get("binding_sha256") != expected_binding
            or record.get("seed_hash") != seed_hash
            or record.get("fields") != list(CHECKPOINT_FIELDS)):
        raise ValueError("F3 checkpoint provenance mismatch")
    generation = Path(record.get("checkpoint_npz", ""))
    if (not generation.exists() or generation.parent.resolve() != output.parent.resolve()
            or not generation.name.startswith(output.name + ".checkpoint.")):
        raise ValueError("F3 checkpoint generation is missing or outside output directory")
    if sha256_file(generation) != record.get("file_sha256"):
        raise ValueError("F3 checkpoint generation file hash mismatch")
    with np.load(generation, allow_pickle=False) as archive:
        state = {name: np.array(archive[name], copy=True) for name in CHECKPOINT_FIELDS}
    if _checkpoint_state_hash(state) != record.get("state_sha256"):
        raise ValueError("F3 checkpoint state hash mismatch")
    return int(record["committed_frame"]), state, record


def _truncate_history(handle, frame: int) -> None:
    target = max(-1, int(frame)) + 1
    for name in HISTORY_DATASETS + ("failure_reason",):
        if name in handle and handle[name].shape[0] != target:
            handle[name].resize(target, axis=0)
    handle.attrs["committed"] = int(frame)
    _fsync_hdf5(handle)


def _frame_values(state: dict, initial_result: MLSResult | None, final_result: MLSResult,
                  native_mass: float, seed_mass: np.ndarray) -> dict:
    reliable = np.asarray(state["reliable"], dtype=bool)
    values = {
        "position": state["position"],
        "reliable": reliable,
        "permanent_unknown": ~reliable,
        "first_passage": state["first_passage"],
        "return_time": state["return_time"],
        "residence_opposite": state["residence_opposite"],
        "returned": state["returned"],
        "support_count": final_result.support_count,
        "effective_sample_size": final_result.effective_sample_size,
        "geometry_rank": final_result.geometry_rank,
        "condition_number": final_result.condition_number,
        "anisotropy": final_result.anisotropy,
        "reconstruction_error_mps": final_result.reconstruction_error_mps,
        "old_gate_pass": final_result.old_gate_pass,
        "candidate_support_pass": final_result.candidate_support_pass,
        "candidate_count": final_result.candidate_count,
        "wall_rejected_count": final_result.wall_rejected_count,
        "native_mass_kg": float(native_mass),
        "seed_mass_closure_error": float(np.sum(seed_mass) - 1.0),
        "failure_reason": [str(v) for v in final_result.failure_reason],
    }
    return values


def _advance_rk4(state: dict, tracer: F3NativeVolumeMLS, frame: F3CurrentFrame,
                 walls: np.ndarray, segment_time: float, dt: float,
                 diagnostics: dict) -> MLSResult:
    q = state["position"]
    active = state["reliable"]
    k1 = tracer.reconstruct(q, frame, walls)
    k2 = tracer.reconstruct(q + 0.5 * dt * np.nan_to_num(k1.velocity), frame, walls)
    k3 = tracer.reconstruct(q + 0.5 * dt * np.nan_to_num(k2.velocity), frame, walls)
    k4 = tracer.reconstruct(q + dt * np.nan_to_num(k3.velocity), frame, walls)
    candidate = q + (dt / 6.0) * np.nan_to_num(k1.velocity + 2.0 * k2.velocity + 2.0 * k3.velocity + k4.velocity)
    usable = (
        active & k1.reliable & k2.reliable & k3.reliable & k4.reliable
        & np.isfinite(candidate).all(axis=1)
    )
    _advance_events(state, q, candidate, segment_time, dt, usable, state["origin"])
    state["position"] = np.where(usable[:, None], candidate, q)
    state["reliable"] = usable
    state["permanent_unknown"] = ~usable
    # Preserve the first failure reason observed in the interval for summary.
    reasons = np.asarray(k4.failure_reason, dtype=object)
    # Once a seed loses a stage, it remains permanently unknown.  Preserve
    # that first diagnostic instead of allowing a later reconstruction of the
    # frozen position to overwrite it with ``reliable``.
    reasons[~active] = state["failure_reason"][~active]
    reasons[usable] = "reliable"
    state["failure_reason"] = reasons
    diagnostics["stage_failure_counts"].update(str(v) for v in k1.failure_reason[active])
    diagnostics["stage_failure_counts"].update(str(v) for v in k2.failure_reason[active])
    diagnostics["stage_failure_counts"].update(str(v) for v in k3.failure_reason[active])
    diagnostics["stage_failure_counts"].update(str(v) for v in k4.failure_reason[active])
    return k4


def _summary(handle, binding: dict, labels: np.ndarray, provider: F3ReferenceProvider,
             initial_mass: np.ndarray, diagnostics: dict, started: float) -> dict:
    committed = int(handle.attrs["committed"])
    weight = np.full(len(labels), 1.0 / len(labels), dtype=np.float64)
    reliable = np.asarray(handle["reliable"][committed], dtype=bool)
    unknown = ~reliable
    first = np.asarray(handle["first_passage"][committed], dtype=np.float64)
    returned = np.asarray(handle["returned"][committed], dtype=bool)
    return_time = np.asarray(handle["return_time"][committed], dtype=np.float64)
    unknown_history = np.asarray(handle["permanent_unknown"][:committed + 1], dtype=bool)
    has_failure = np.any(unknown_history, axis=0)
    first_failure_by_seed = np.full(len(labels), -1, dtype=np.int64)
    for seed in np.flatnonzero(has_failure):
        first_failure_by_seed[seed] = int(np.flatnonzero(unknown_history[:, seed])[0])

    def quantiles(values: np.ndarray) -> dict:
        values = np.asarray(values, dtype=np.float64)
        values = values[np.isfinite(values)]
        if not len(values):
            return {"count": 0, "p50": None, "p90": None, "p95": None, "p99": None}
        q = np.quantile(values, [0.50, 0.90, 0.95, 0.99])
        return {"count": int(len(values)), "p50": float(q[0]), "p90": float(q[1]),
                "p95": float(q[2]), "p99": float(q[3])}

    rows = []
    for source in np.unique(labels):
        select = labels == source
        mass = float(weight[select].sum())
        source_unknown = select & unknown
        finite_first = select & np.isfinite(first)
        finite_return = select & np.isfinite(return_time)
        source_failure_frames = first_failure_by_seed[select & has_failure]
        source_final_reason = np.asarray(handle["failure_reason"][committed], dtype=str)[select & source_unknown]
        failure_reason_counts = Counter(str(value) for value in source_final_reason)
        source_residence = np.asarray(handle["residence_opposite"][committed], dtype=np.float64)[select]
        source_reliable = select & reliable
        source_failure_cdf = []
        if len(source_failure_frames):
            source_count = int(np.count_nonzero(select))
            for frame in sorted(set(int(value) for value in source_failure_frames)):
                source_failure_cdf.append({
                    "frame": frame,
                    "time_s": float(handle["time"][frame]),
                    "cumulative_fraction": float(np.count_nonzero(
                        select & has_failure & (first_failure_by_seed <= frame)) / source_count),
                })
        rows.append({
            "source": int(source),
            "initial_mass_fraction": float(mass),
            "unknown_fraction": float(weight[source_unknown].sum() / mass),
            "reliable_path_coverage": float(weight[select & reliable].sum() / mass),
            "observed_first_passage_fraction": float(weight[finite_first].sum() / mass),
            "observed_return_fraction": float(weight[finite_return].sum() / mass),
            "first_failure_frame": int(np.min(source_failure_frames)) if len(source_failure_frames) else None,
            "first_failure_time_s": float(handle["time"][int(np.min(source_failure_frames))]) if len(source_failure_frames) else None,
            "first_failure_cdf": source_failure_cdf,
            "old_gate_pass_fraction_final": float(weight[select & np.asarray(handle["old_gate_pass"][committed], dtype=bool)].sum() / mass),
            "candidate_support_pass_fraction_final": float(weight[select & np.asarray(handle["candidate_support_pass"][committed], dtype=bool)].sum() / mass),
            "final_failure_reason_counts": dict(failure_reason_counts),
            "first_passage_time_quantiles_s": quantiles(first[select]),
            "return_time_quantiles_s": quantiles(return_time[select]),
            "residence_opposite_quantiles_s_lower_bound": quantiles(source_residence),
            "residence_opposite_quantiles_s_reliable_only": quantiles(
                source_residence[source_reliable[select]]),
            "residence_censored_fraction": float(weight[source_unknown].sum() / mass),
            "final_support_count_min": int(np.min(np.asarray(handle["support_count"][committed], dtype=np.int64)[select])),
            "final_wall_rejected_max": int(np.max(np.asarray(handle["wall_rejected_count"][committed], dtype=np.int64)[select])),
        })
    times = np.asarray(handle["time"][:committed + 1], dtype=np.float64)
    unknown_fraction = np.asarray(handle["permanent_unknown"][:committed + 1], dtype=bool).mean(axis=1)
    return {
        "schema": "core.material.f3.native_volume_mls.short_canary_result.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "qualification_claim": "none",
        "material_reliability": "not established by numerical support diagnostics",
        "binding": binding,
        "source_window": {
            "frame_count_committed": committed + 1,
            "first_frame": int(times[0]),
            "last_frame": committed,
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "native_frame_policy": "all saved frames sequentially; no interpolation-created source frame",
        },
        "seed_count": int(len(labels)),
        "source_rows": rows,
        "mass_closed": bool(np.max(np.abs(np.asarray(handle["seed_mass_closure_error"][:committed + 1]))) <= 1e-12),
        "common_reliable_path_coverage": float(weight[reliable].sum()),
        "unknown_fraction_max": float(np.max(unknown_fraction)),
        "unknown_fraction_by_frame": {"time_s": times.tolist(), "fraction": unknown_fraction.tolist()},
        "native_mass_kg": np.asarray(handle["native_mass_kg"][:committed + 1], dtype=np.float64).tolist(),
        "native_initial_mass_kg": float(initial_mass.sum()),
        "diagnostics": {
            "stage_failure_counts": dict(diagnostics["stage_failure_counts"]),
            "loaded_frame_indices": provider.loaded_indices,
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "elapsed_seconds": time.monotonic() - started,
        },
    }


def audit_source(source: str | Path, prepared: str | Path, *, dp_m: float | None = None) -> dict:
    source = Path(source).resolve()
    prepared = Path(prepared).resolve()
    prepared_value = json.loads(prepared.read_text())
    expected_dp = float(prepared_value["dp_m"])
    if dp_m is None:
        dp_m = expected_dp
    dp_m = float(dp_m)
    if not np.isclose(dp_m, expected_dp, rtol=0.0, atol=1e-14):
        raise ValueError("candidate dp_m does not match prepared F3 source")
    h_m = h_from_dp(dp_m)
    xml_path = Path(prepared_value["candidate_definition"]).resolve()
    if not xml_path.exists():
        raise FileNotFoundError(xml_path)
    xml_text = xml_path.read_text(encoding="utf-8")
    kernel_match = re.search(r'<parameter\s+key="Kernel"\s+value="(\d+)"', xml_text)
    coef_match = re.search(r'<coefh\s+value="([0-9.]+)"', xml_text)
    kernel_id = int(kernel_match.group(1)) if kernel_match else None
    coefh = float(coef_match.group(1)) if coef_match else None
    with h5py.File(source, "r") as handle:
        required = ["time", "position", "velocity", "mass", "density", "valid", "type"]
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"F3 source is missing datasets: {missing}")
        times = np.asarray(handle["time"][:], dtype=np.float64)
        frame_count, particle_count = handle["position"].shape[:2]
        type0 = np.asarray(handle["type"][0], dtype=np.float64)
        valid0 = np.asarray(handle["valid"][0], dtype=bool)
        fluid0 = valid0 & (type0 == F3_FLUID_TYPE)
        mass0 = np.asarray(handle["mass"][0], dtype=np.float64)
        density0 = np.asarray(handle["density"][0], dtype=np.float64)
        position0 = np.asarray(handle["position"][0], dtype=np.float64)
        valid_rows = fluid0 & np.isfinite(mass0) & (mass0 > 0.0) & np.isfinite(density0) & (density0 > 0.0)
        mass_sums = [float(np.asarray(handle["mass"][i], dtype=np.float64)[fluid0].sum())
                     for i in (0, frame_count // 2, frame_count - 1)]
    seeds = seeds_f3(512)
    labels = source_labels(seeds)
    walls = f3_walls()
    return {
        "schema": "core.material.f3.native_volume_mls.source_preflight.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "preflight_passed",
        "qualification_claim": "none",
        "source": {
            "path": str(source),
            "sha256": sha256_file(source),
            "frames": int(frame_count),
            "particles_axis": int(particle_count),
            "fluid_rows_frame0": int(np.count_nonzero(valid_rows)),
            "time_start_s": float(times[0]),
            "time_end_s": float(times[-1]),
            "native_output_interval_nominal_s": F3_OUTPUT_INTERVAL_S,
            "time_step_min_s": float(np.min(np.diff(times))),
            "time_step_max_s": float(np.max(np.diff(times))),
            "datasets": required,
            "mass_dtype": "float32",
            "density_dtype": "float32",
            "current_frame_mass_density": True,
            "sampled_native_mass_sums_kg": mass_sums,
            "initial_mass_kg": float(mass0[valid_rows].sum()),
            "initial_position_bounds_m": {
                "low": position0[valid_rows].min(axis=0).tolist(),
                "high": position0[valid_rows].max(axis=0).tolist(),
            },
        },
        "prepared_case": {
            "path": str(prepared),
            "sha256": sha256_file(prepared),
            "case_id": prepared_value.get("case_id"),
            "dp_m": dp_m,
            "h_m": h_m,
            "recipe_id": prepared_value.get("recipe_id"),
            "qualified": bool(prepared_value.get("qualified", False)),
            "formal_release": bool(prepared_value.get("formal_release", False)),
            "wall_spec": prepared_value.get("wall_spec"),
        },
        "kernel_binding": {
            "xml_path": str(xml_path),
            "xml_sha256": sha256_file(xml_path),
            "kernel_id": kernel_id,
            "kernel_name": F3_KERNEL_NAME if kernel_id == F3_KERNEL_ID else None,
            "coefh": coefh,
            "h_formula": "coefh*sqrt(3*dp^2)",
            "h_m": h_m,
            "formula": dict(WENDLAND_FORMULA),
        },
        "wall_binding": {
            "geometry": "F3 finite closed bottom,left,right,front,back; top open",
            "low_m": F3_WALL_LOW_M.tolist(),
            "high_m": F3_WALL_HIGH_M.tolist(),
            "triangle_count": int(len(walls)),
            "triangles_sha256": array_hash(walls),
        },
        "source_definition": {
            "kind": "continuous_halfspace",
            "axis": 0,
            "boundary_m": 0.0,
            "source_0": "seed x < 0",
            "source_1": "seed x >= 0",
            "seed_count": 512,
            "source0_seed_count": int(np.count_nonzero(labels == 0)),
            "source1_seed_count": int(np.count_nonzero(labels == 1)),
            "identity": "independent geometric seeds; native particle_id never partitions or terminates a seed",
        },
        "original_f3_material_gate": dict(F3_ORIGINAL_GATE),
        "candidate_binding": {
            "schema": SCHEMA,
            "backend": BACKEND,
            "future_state": "forbidden",
            "native_volume": "mass/density from same current native H5 frame",
            "support": "all current valid fluid rows within 2h after finite-wall visibility",
            "fit": "weighted affine MLS SVD",
            "candidate_gate": dict(MLS_GATE),
        },
    }


def run_trace(source: str | Path, output: str | Path, prepared: str | Path, *,
              seeds: int = 512, substeps: int = 2, stop_after: int = 20,
              dp_m: float | None = None, resume: bool = False,
              kill_after_h5_append: int | None = None,
              kill_after_generation: int | None = None) -> dict:
    source = Path(source).resolve()
    output = Path(output).resolve()
    prepared = Path(prepared).resolve()
    if kill_after_h5_append is not None and int(kill_after_h5_append) < 0:
        raise ValueError("kill_after_h5_append must be nonnegative")
    if kill_after_generation is not None and int(kill_after_generation) < 0:
        raise ValueError("kill_after_generation must be nonnegative")
    if not resume and output.exists():
        raise FileExistsError(output)
    if stop_after < 1:
        raise ValueError("short canary stop_after must include at least one interval")
    audit = audit_source(source, prepared, dp_m=dp_m)
    dp_m = float(audit["prepared_case"]["dp_m"])
    h_m = float(audit["kernel_binding"]["h_m"])
    initial = seeds_f3(seeds)
    labels = source_labels(initial)
    tracer_ids = np.asarray([f"f3-seed-{i:06d}" for i in range(len(initial))], dtype=object)
    seed_hash = array_hash(initial, labels, tracer_ids.astype(str))
    weights = np.full(len(initial), 1.0 / len(initial), dtype=np.float64)
    walls = f3_walls()
    tracer = F3NativeVolumeMLS(h_m)
    started = time.monotonic()
    diagnostics = {"stage_failure_counts": Counter()}
    with F3ReferenceProvider(source) as provider:
        end = min(int(stop_after), provider.frame_count - 1)
        binding = _trace_binding(source, provider, tracer, initial, labels, substeps, end, walls)
        checkpoint = _checkpoint_read(output, binding, seed_hash) if resume else None
        if resume and checkpoint is None:
            raise ValueError("--resume requires a complete F3 checkpoint manifest")
        initial_frame = provider.frame(0)
        initial_mass = np.array(initial_frame.mass, copy=True)
        initial_result = None
        output.parent.mkdir(parents=True, exist_ok=True)
        if checkpoint is None:
            state = _new_state(initial, labels)
            initial_result = tracer.reconstruct(initial, initial_frame, walls)
            state["reliable"] = initial_result.reliable.copy()
            state["permanent_unknown"] = ~state["reliable"]
            state["failure_reason"] = np.asarray(initial_result.failure_reason, dtype=object)
            with h5py.File(output, "w") as handle:
                _create_output(handle, initial, labels, tracer_ids, binding, end + 1, len(initial))
                initial_values = _frame_values(state, initial_result, initial_result,
                                               float(initial_mass.sum()), weights)
                _append_frame(handle, 0, float(provider.times[0]), initial_values)
                _fsync_hdf5(handle)
                if kill_after_h5_append == 0:
                    os.kill(os.getpid(), signal.SIGKILL)
                record = _checkpoint_publish(
                    output, binding, 0, state, seed_hash,
                    diagnostics["stage_failure_counts"],
                    fault_after_generation=kill_after_generation == 0,
                )
                handle.attrs["checkpoint_manifest"] = str(_checkpoint_paths(output)[0])
                _fsync_hdf5(handle)
            start_frame = 1
        else:
            checkpoint_frame, state, checkpoint_record = checkpoint
            if checkpoint_frame < 0 or checkpoint_frame > end:
                raise ValueError("F3 checkpoint frame is outside requested source window")
            # Origin is a deterministic function of the immutable seed labels;
            # it is restored explicitly rather than duplicated in each NPZ.
            state["origin"] = labels.astype(bool)
            diagnostics["stage_failure_counts"].update(
                {str(key): int(value) for key, value in checkpoint_record.get("stage_failure_counts", {}).items()}
            )
            with h5py.File(output, "r+") as handle:
                expected_binding = canonical(binding)
                if (handle.attrs.get("schema") != TRACE_SCHEMA
                        or handle.attrs.get("trace_backend") != TRACE_BACKEND
                        or handle.attrs.get("binding") != expected_binding):
                    raise ValueError("F3 trace output provenance mismatch on resume")
                _truncate_history(handle, checkpoint_frame)
                handle.attrs["checkpoint_manifest"] = str(_checkpoint_paths(output)[0])
            start_frame = checkpoint_frame + 1

        with h5py.File(output, "r+") as handle:
            for next_index in range(start_frame, end + 1):
                frame_index = next_index - 1
                frame = provider.frame(frame_index)
                dt = (float(provider.times[next_index]) - float(provider.times[frame_index])) / int(substeps)
                result = None
                for substep_index in range(int(substeps)):
                    segment_time = float(provider.times[frame_index]) + substep_index * dt
                    result = _advance_rk4(state, tracer, frame, walls, segment_time, dt, diagnostics)
                if result is None:
                    raise RuntimeError("no RK stage result")
                values = _frame_values(state, initial_result, result,
                                       float(frame.mass.sum()), weights)
                _append_frame(handle, next_index, float(provider.times[next_index]), values)
                _fsync_hdf5(handle)
                if kill_after_h5_append == next_index:
                    os.kill(os.getpid(), signal.SIGKILL)
                _checkpoint_publish(
                    output, binding, next_index, state, seed_hash,
                    diagnostics["stage_failure_counts"],
                    fault_after_generation=kill_after_generation == next_index,
                )
                handle.attrs["checkpoint_manifest"] = str(_checkpoint_paths(output)[0])
                _fsync_hdf5(handle)
                print(json.dumps({"frame": next_index, "total": end, "unknown_fraction": float((~state["reliable"]).mean())}), flush=True)
            result = _summary(handle, binding, labels, provider, initial_mass, diagnostics, started)
            result["audit"] = audit
            result["resume"] = bool(resume)
            result["checkpoint_manifest"] = str(_checkpoint_paths(output)[0])
            result["code_sha256"] = sha256_file(Path(__file__))
            handle.attrs["result"] = canonical(result)
    summary_path = output.with_suffix(".summary.json")
    result["output"] = {"path": str(output), "sha256": sha256_file(output)}
    # A summary cannot safely contain its own content hash.  The returned
    # result carries the post-write hash for an external receipt, while the
    # persisted summary records only its stable path.
    result["summary"] = {"path": str(summary_path)}
    summary_path.write_text(json.dumps(json_value(result), indent=2, sort_keys=True) + "\n")
    result["summary"]["sha256"] = sha256_file(summary_path)
    return result


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--dp", type=float, default=None)
    parser.add_argument("--seeds", type=int, default=512)
    parser.add_argument("--substeps", type=int, default=2)
    parser.add_argument("--stop-after", type=int, default=20)
    parser.add_argument("--resume", action="store_true",
                        help="resume output from its last published checkpoint generation")
    parser.add_argument("--kill-after-h5-append", type=int,
                        help="test-only SIGKILL after this output frame append")
    parser.add_argument("--kill-after-generation", type=int,
                        help="test-only SIGKILL after this NPZ generation is durable and before manifest replace")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    audit = audit_source(args.source, args.prepared, dp_m=args.dp)
    if args.audit_output is not None:
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.write_text(json.dumps(json_value(audit), indent=2, sort_keys=True) + "\n")
    if args.audit_only:
        print(json.dumps(json_value(audit), sort_keys=True))
        return 0
    if args.output is None:
        parser.error("--output is required unless --audit-only is used")
    result = run_trace(args.source, args.output, args.prepared, seeds=args.seeds,
                       substeps=args.substeps, stop_after=args.stop_after, dp_m=args.dp,
                       resume=args.resume,
                       kill_after_h5_append=args.kill_after_h5_append,
                       kill_after_generation=args.kill_after_generation)
    compact = {
        "schema": result["schema"], "status": result["status"],
        "output": result["output"], "committed_frame": result["source_window"]["last_frame"],
        "time_end_s": result["source_window"]["time_end_s"],
        "unknown_fraction_max": result["unknown_fraction_max"],
        "common_reliable_path_coverage": result["common_reliable_path_coverage"],
        "mass_closed": result["mass_closed"],
    }
    print(json.dumps(json_value(compact), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
