"""Independent material tracing for the core campaign.

The tracer axis in this module is an independent geometric seed axis.  It is
never indexed by a solver particle id and a lost source particle therefore
does not terminate a seed.  A reference provider may read the two native
frames needed for a current interpolation; the field object handed to the
tracer contains only the current ``x``/``v`` arrays and a CPU cKDTree.

This is a candidate material diagnostic.  It deliberately does not touch a
campaign ledger, acquire a slot, start a GPU job, or claim T2 qualification.
The HDF5 stream is committed one saved frame at a time.  An atomic checkpoint
sidecar is written before each HDF5 row, so a process killed between a dataset
resize and the HDF5 commit can resume from the last complete state.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import time

import h5py
import numpy as np
from scipy.spatial import cKDTree

from scripts.f3_material_neighbors import _visible_support
from scripts.passive_tracers import (
    _normalise_support_gate,
    _support_gate_pass,
    _support_metrics,
    box_surface_triangles,
    spacetime_swept_wall_blocked,
)


SCHEMA = "core.material.v2"
CHECKPOINT_SCHEMA = "core.material.checkpoint.v1"
NEIGHBOUR_BACKEND = "f3_ckdtree_visible_shepard_distance_v1"
NEIGHBOURS = 24
# H2 is a pre-registered single variant.  It keeps the F3 visible-support
# search and Shepard weights unchanged and only increases the retained
# nearest-neighbour cap.  Do not turn this into a parameter sweep.
H2_NEIGHBOUR_BACKEND = "f3_ckdtree_visible_shepard_distance_k48_v1"
H2_NEIGHBOURS = 48
H1_ERROR_BACKEND = "f3_ckdtree_visible_shepard_query_error_bound_v1"
H1_NEIGHBOURS = 24
# F4 repair candidates are separately versioned and are not threshold changes.
# ``f4_ess32_v2`` retains the same visible Shepard weights and fixed gate while
# expanding the support cap to the smallest pre-registered F4 candidate that
# clears the manufactured ESS false positive.  ``f4_affine_bound_v2`` retains
# k=24 and adds the existing local affine query-bias estimate to the same fixed
# reconstruction gate.  Neither candidate is qualified until a real F4
# short-window canary passes the unchanged 1% unknown budget.
F4_ESS32_BACKEND = "f4_ckdtree_visible_shepard_ess32_v2"
F4_ESS32_NEIGHBOURS = 32
F4_AFFINE_BACKEND = "f4_ckdtree_visible_shepard_affine_bound_v2"
F4_AFFINE_NEIGHBOURS = 24
# F4 v3 is a new composition, not a threshold or cadence revision.  It is
# deliberately registered under its own namespace so old variants retain
# byte-for-byte dispatch semantics and provenance.
F4_V3_BACKEND = "f4_ckdtree_visible_shepard_ess32_affine_bound_v3"
F4_V3_NEIGHBOURS = 32
F4_V3_ERROR_ESTIMATOR = "residual_plus_local_affine_query_bias"
NEIGHBOUR_VARIANTS = {
    "baseline24": (NEIGHBOUR_BACKEND, NEIGHBOURS),
    "h2_k48": (H2_NEIGHBOUR_BACKEND, H2_NEIGHBOURS),
    "h1_affine_bound": (H1_ERROR_BACKEND, H1_NEIGHBOURS),
    "f4_ess32_v2": (F4_ESS32_BACKEND, F4_ESS32_NEIGHBOURS),
    "f4_affine_bound_v2": (F4_AFFINE_BACKEND, F4_AFFINE_NEIGHBOURS),
    "f4_supportcap_affine_query_bound_v3": (F4_V3_BACKEND, F4_V3_NEIGHBOURS),
}
ERROR_ESTIMATORS = {
    "baseline24": "local_residual",
    "h2_k48": "local_residual",
    "h1_affine_bound": "residual_plus_local_affine_query_bias",
    "f4_ess32_v2": "local_residual",
    "f4_affine_bound_v2": "residual_plus_local_affine_query_bias",
    "f4_supportcap_affine_query_bound_v3": F4_V3_ERROR_ESTIMATOR,
}
REGULARIZATION_M = 0.004
MAXIMUM_SUPPORT_DISTANCE_M = 0.03
GATE = {
    "minimum_effective_sample_size": 4.0,
    "minimum_geometry_rank": 3,
    "minimum_anisotropy": 0.005,
    "maximum_reconstruction_error_mps": 0.05 * np.sqrt(9.81 * 0.09),
}
CHECKPOINT_FIELDS = (
    "position",
    "reliable",
    "first_passage",
    "return_time",
    "residence",
    "residence_left",
    "residence_right",
    "returned",
)
HISTORY_FIELDS = ("time",) + CHECKPOINT_FIELDS

# F4 is a separate qualification family.  These values are copied from the
# migration specification and are deliberately kept independent of the F3
# half-space source definition above.
F4_SCHEMA = "core.material.f4.resting_pool.v2"
F4_CHECKPOINT_SCHEMA = "core.material.f4.checkpoint.v1"
F4_SCOPE_ID = "F4_drop_resting_pool_x_v2"
F4_REVISION_ID = "F4_resting_pool_13plus2_v2"
F4_RECIPE_ID = "F4_resting_pool_mdbc_native_v2"
F4_INTERFACE_Z_M = 0.18
F4_GRAVITY_TIME_S = 0.3497487083913345
F4_INITIAL_HORIZON_S = 4.34
F4_MAXIMUM_HORIZON_S = 8.68
F4_SOURCE_SIZE_M = np.array([0.26, 0.16, 0.14], dtype=np.float64)
F4_DESTINATION_LOW_M = np.array([0.0, 0.0, 0.0], dtype=np.float64)
F4_DESTINATION_SIZE_M = np.array([1.2, 0.4, 0.18], dtype=np.float64)
F4_WALL_HIGH_M = np.array([1.2, 0.4, 0.6], dtype=np.float64)
F4_CHECKPOINT_FIELDS = (
    "position",
    "reliable",
    "contact_time",
    "upward_time",
    "return_time",
    "residence",
    "contacted",
    "upward",
    "returned",
)
F4_HISTORY_FIELDS = ("time",) + F4_CHECKPOINT_FIELDS


def digest(path):
    """Return a SHA256 for a file without reading it all into memory."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash_array(value):
    array = np.asarray(value)
    if array.dtype.kind in "OUS":
        payload = _canonical([_json_scalar(item) for item in array.reshape(-1)]).encode()
    else:
        array = np.ascontiguousarray(array)
        payload = _canonical({"dtype": array.dtype.str, "shape": array.shape}).encode() + array.tobytes()
    return hashlib.sha256(payload).hexdigest()


def _json_scalar(value):
    """Convert a numpy scalar (including byte strings) to JSON data."""
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8")
    if isinstance(value, np.generic):
        return value.item()
    return value


def _positive_integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _neighbour_variant(value):
    """Resolve one registered support-cap variant, without free-form sweeps."""
    if value not in NEIGHBOUR_VARIANTS:
        raise ValueError(f"unknown neighbour variant: {value!r}")
    backend, neighbours = NEIGHBOUR_VARIANTS[value]
    return value, backend, neighbours, ERROR_ESTIMATORS[value]


def _backend_for_neighbours(neighbours):
    """Return the provenance name for a direct CurrentField sample."""
    neighbours = _positive_integer(neighbours, "neighbours")
    for backend, registered in NEIGHBOUR_VARIANTS.values():
        if neighbours == registered:
            return backend
    return f"{NEIGHBOUR_BACKEND}_unregistered_k{neighbours}"


def _local_affine_query_bias(query, position, velocity, selected, distance2, weights, interpolated):
    """Estimate Shepard query bias from a weighted local affine fit.

    The existing reconstruction metric is the fit residual at the support
    samples.  This companion evaluates that same fit at the tracer query and
    compares it with the Shepard value.  H1 uses the conservative sum of the
    sample residual and this query-bias estimate; it does not remove or relax
    the existing reconstruction gate.
    """
    count = len(query)
    safe_weights = np.where(np.isfinite(distance2), weights, 0.0)
    weight_sum = safe_weights.sum(axis=1)
    local_position = np.asarray(position[selected], dtype=np.float64)
    local_velocity = np.asarray(velocity[selected], dtype=np.float64)
    center = np.divide(
        np.sum(local_position * safe_weights[..., None], axis=1),
        np.maximum(weight_sum, np.finfo(np.float64).tiny)[:, None],
    )
    offsets = local_position - center[:, None, :]
    design = np.concatenate((np.ones((count, local_position.shape[1], 1)), offsets), axis=2)
    square_root = np.sqrt(safe_weights)[..., None]
    coefficients = np.matmul(
        np.linalg.pinv(design * square_root), local_velocity * square_root
    )
    query_design = np.concatenate((np.ones((count, 1)), query - center), axis=1)
    affine_at_query = np.einsum("qi,qij->qj", query_design, coefficients)
    bias = np.linalg.norm(interpolated - affine_at_query, axis=1)
    bias[weight_sum <= 0.0] = np.inf
    return bias


def _validate_walls(walls):
    value = np.asarray(walls, dtype=np.float64)
    if value.size == 0:
        return np.empty((0, 3, 3), dtype=np.float64)
    if value.ndim != 3 or value.shape[1:] != (3, 3) or not np.isfinite(value).all():
        raise ValueError("walls must be finite triangles with shape [T,3,3]")
    return np.array(value, dtype=np.float64, copy=True)


def _validate_seeds(initial):
    value = np.asarray(initial, dtype=np.float64)
    if value.ndim != 2 or value.shape[1:] != (3,) or not len(value):
        raise ValueError("initial seeds must have shape [N,3] and N>0")
    if not np.isfinite(value).all():
        raise ValueError("initial seeds must be finite")
    return np.array(value, dtype=np.float64, copy=True)


def continuous_source_labels(initial, *, axis=0, boundary=0.0):
    """Define source halves from the continuous seed coordinate.

    The boundary is right-closed: ``x < boundary`` is source 0 and
    ``x >= boundary`` is source 1.  This definition is independent of native
    particle identities and is recorded in every material output.
    """
    points = _validate_seeds(initial)
    if isinstance(axis, bool) or not isinstance(axis, (int, np.integer)) or not 0 <= axis < 3:
        raise ValueError("source axis must be 0, 1, or 2")
    if not np.isfinite(boundary):
        raise ValueError("source boundary must be finite")
    return (points[:, int(axis)] >= float(boundary)).astype(np.int8)


def source_definition(*, axis=0, boundary=0.0):
    if isinstance(axis, bool) or not isinstance(axis, (int, np.integer)) or not 0 <= axis < 3:
        raise ValueError("source axis must be 0, 1, or 2")
    if not np.isfinite(boundary):
        raise ValueError("source boundary must be finite")
    return {
        "kind": "continuous_halfspace",
        "axis": int(axis),
        "boundary_m": float(boundary),
        "boundary_policy": "source_1_if_coordinate_ge_boundary",
        "source_0": "coordinate < boundary",
        "source_1": "coordinate >= boundary",
    }


class CurrentField:
    """An isolated current field with one cached CPU spatial index.

    The constructor copies all arrays.  It has no HDF5 handle, reference
    provider, particle id, or future frame.  Sampling uses the exact F3
    visible-neighbour support search and weights ``1/(d^2+eps^2)``.
    """

    provider_role = "current"

    def __init__(self, position, velocity, valid=None):
        position = np.asarray(position, dtype=np.float64)
        velocity = np.asarray(velocity, dtype=np.float64)
        if position.ndim != 2 or position.shape[1:] != (3,) or velocity.shape != position.shape:
            raise ValueError("position and velocity must both have shape [N,3]")
        if valid is None:
            valid = np.ones(len(position), dtype=bool)
        valid = np.asarray(valid, dtype=bool)
        if valid.shape != (len(position),):
            raise ValueError("valid must have shape [N]")
        good = valid & np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
        self.position = np.array(position[good], dtype=np.float64, copy=True)
        self.velocity = np.array(velocity[good], dtype=np.float64, copy=True)
        self.position.setflags(write=False)
        self.velocity.setflags(write=False)
        self.valid_count = int(good.sum())
        self.input_count = int(len(position))
        self.tree = cKDTree(self.position) if self.valid_count else None

    def sample(
        self,
        query,
        walls=None,
        neighbours=NEIGHBOURS,
        regularization=REGULARIZATION_M,
        *,
        gate=GATE,
        error_estimator="local_residual",
        return_diagnostics=False,
    ):
        """Sample velocity and support quality at independent tracer points.

        The legacy three-value return remains ``(velocity, distance, gate)``.
        Set ``return_diagnostics`` to obtain the complete support diagnostics
        used in the material result.
        """
        query = np.asarray(query, dtype=np.float64)
        if query.ndim != 2 or query.shape[1:] != (3,):
            raise ValueError("query must have shape [Q,3]")
        walls = _validate_walls(np.empty((0, 3, 3)) if walls is None else walls)
        neighbours = _positive_integer(neighbours, "neighbours")
        if error_estimator not in ("local_residual", "residual_plus_local_affine_query_bias"):
            raise ValueError(f"unknown error estimator: {error_estimator!r}")
        if not np.isfinite(regularization) or regularization <= 0:
            raise ValueError("regularization must be finite and positive")
        n = len(query)
        velocity = np.full((n, 3), np.nan, dtype=np.float64)
        support = np.full(n, np.inf, dtype=np.float64)
        passed = np.zeros(n, dtype=bool)
        diagnostics = {
            "effective_sample_size": np.zeros(n, dtype=np.float64),
            "geometry_rank": np.zeros(n, dtype=np.int8),
            "anisotropy": np.zeros(n, dtype=np.float64),
            "interpolation_reconstruction_error_mps": np.full(n, np.inf, dtype=np.float64),
            "local_affine_query_bias_mps": np.full(n, np.inf, dtype=np.float64),
            "estimated_interpolation_error_mps": np.full(n, np.inf, dtype=np.float64),
            "visible_neighbours": np.zeros(n, dtype=np.int64),
            "selected_visible_neighbours": np.zeros(n, dtype=np.int64),
            "visibility_search_width": np.zeros(n, dtype=np.int64),
            "visibility_search_exhaustive": np.zeros(n, dtype=bool),
        }
        finite_query = np.isfinite(query).all(axis=1)
        if self.tree is not None and finite_query.any():
            rows = np.flatnonzero(finite_query)
            k = min(neighbours, self.valid_count)
            selected, distance2, visible, width, exhaustive = _visible_support(
                self.tree, query[rows], self.position, walls, k
            )
            epsilon2 = float(regularization) ** 2
            weights = np.where(np.isfinite(distance2), 1.0 / (distance2 + epsilon2), 0.0)
            denominator = weights.sum(axis=1)
            interpolated = np.divide(
                (weights[..., None] * self.velocity[selected]).sum(axis=1),
                denominator[:, None],
                out=np.full((len(rows), 3), np.nan, dtype=np.float64),
                where=denominator[:, None] > 0,
            )
            metric = _support_metrics(query[rows], self.position, self.velocity, selected, distance2, weights)
            metric["interpolation_reconstruction_error_mps"] = metric["interpolation_reconstruction_error"]
            estimated_error = metric["interpolation_reconstruction_error"].copy()
            if error_estimator == "residual_plus_local_affine_query_bias":
                affine_bias = _local_affine_query_bias(
                    query[rows], self.position, self.velocity, selected, distance2, weights, interpolated
                )
                estimated_error = estimated_error + affine_bias
            else:
                affine_bias = np.zeros(len(rows), dtype=np.float64)
            support[rows] = np.sqrt(np.maximum(0.0, distance2.min(axis=1)))
            velocity[rows] = interpolated
            diagnostics["effective_sample_size"][rows] = metric["effective_sample_size"]
            diagnostics["geometry_rank"][rows] = metric["geometry_rank"]
            diagnostics["anisotropy"][rows] = metric["anisotropy"]
            diagnostics["interpolation_reconstruction_error_mps"][rows] = metric[
                "interpolation_reconstruction_error"
            ]
            diagnostics["local_affine_query_bias_mps"][rows] = affine_bias
            diagnostics["estimated_interpolation_error_mps"][rows] = estimated_error
            diagnostics["visible_neighbours"][rows] = visible
            diagnostics["selected_visible_neighbours"][rows] = np.isfinite(distance2).sum(axis=1)
            diagnostics["visibility_search_width"][rows] = width
            diagnostics["visibility_search_exhaustive"][rows] = exhaustive
            gate_metric = dict(metric)
            gate_metric["interpolation_reconstruction_error_mps"] = estimated_error
            passed[rows] = _support_gate_pass(gate_metric, _normalise_support_gate(gate))
        diagnostics["support_distance"] = support
        diagnostics["error_estimator"] = error_estimator
        backend = _backend_for_neighbours(neighbours)
        diagnostics["visibility_mode"] = (
            f"{backend}_finite_barrier" if len(walls) else f"{backend}_no_barrier"
        )
        diagnostics["backend"] = backend
        diagnostics["shepard_weight"] = "1/(distance_squared+regularization_squared)"
        if return_diagnostics:
            return velocity, support, passed, diagnostics
        return velocity, support, passed


class ReferenceFrames:
    """Reference provider with a strict two-frame read cache.

    ``field(i, alpha)`` can only use native frames ``i`` and ``i+1``.  The
    provider never builds an aligned future trajectory; only the current
    interpolation receives a ``CurrentField`` copy.
    """

    provider_role = "reference"

    def __init__(self, source, *, max_cache=2, fluid_type=3):
        self.source = Path(source)
        self.h5 = h5py.File(self.source, "r")
        self.cache = OrderedDict()
        self.max_cache = _positive_integer(max_cache, "max_cache")
        self.fluid_type = fluid_type
        required = {"time", "position", "velocity", "valid"}
        if not required <= set(self.h5):
            self.close()
            raise ValueError("reference source requires time, position, velocity, and valid datasets")
        self.times = np.asarray(self.h5["time"], dtype=np.float64)
        self._validate_layout()
        self.source_sha256 = digest(self.source)
        self.loaded_indices = []
        self.read_count = 0

    def _validate_layout(self):
        times = self.times
        if len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            self.close()
            raise ValueError("reference time must be strictly increasing and finite")
        n = self.h5["position"].shape[1]
        if self.h5["position"].shape != (len(times), n, 3) or self.h5["velocity"].shape != (len(times), n, 3):
            self.close()
            raise ValueError("reference position/velocity must have shape [frames,particles,3]")
        if self.h5["valid"].shape != (len(times), n):
            self.close()
            raise ValueError("reference valid must have shape [frames,particles]")
        if "type" in self.h5:
            if self.h5["type"].shape not in ((n,), (len(times), n)):
                self.close()
                raise ValueError("reference type must be static or frame-indexed")
            self.zone_dataset = "type"
            self.zone_value = self.fluid_type
        elif "particle_zone" in self.h5:
            if self.h5["particle_zone"].shape != (n,):
                self.close()
                raise ValueError("reference particle_zone must have shape [particles]")
            self.zone_dataset = "particle_zone"
            self.zone_value = None
        else:
            self.zone_dataset = None
            self.zone_value = None
        self.particle_count = n

    def _check_index(self, index):
        if isinstance(index, bool) or not isinstance(index, (int, np.integer)):
            raise TypeError("frame index must be an integer")
        index = int(index)
        if not 0 <= index < len(self.times):
            raise IndexError("frame index outside reference source")
        return index

    def frame(self, index):
        index = self._check_index(index)
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        h = self.h5
        position = np.asarray(h["position"][index], dtype=np.float64)
        velocity = np.asarray(h["velocity"][index], dtype=np.float64)
        valid = np.asarray(h["valid"][index], dtype=bool)
        if self.zone_dataset == "type":
            zone = np.asarray(h["type"][index] if h["type"].ndim == 2 else h["type"][:])
            valid &= zone == self.zone_value
        elif self.zone_dataset == "particle_zone":
            # Native core F3 particle_zone 0 is fluid.  A file with a type
            # dataset has already taken the explicit type==3 path above.
            valid &= np.asarray(h["particle_zone"][:]) == 0
        valid &= np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
        position.setflags(write=False)
        velocity.setflags(write=False)
        valid.setflags(write=False)
        value = (position, velocity, valid)
        self.cache[index] = value
        self.cache.move_to_end(index)
        self.loaded_indices.append(index)
        self.read_count += 1
        while len(self.cache) > self.max_cache:
            self.cache.popitem(last=False)
        return value

    def field(self, index, alpha=0.0):
        index = self._check_index(index)
        if not np.isfinite(alpha) or not 0.0 <= alpha <= 1.0:
            raise ValueError("interpolation alpha must be in [0,1]")
        if alpha == 0.0:
            position, velocity, valid = self.frame(index)
            return CurrentField(position, velocity, valid)
        if index + 1 >= len(self.times):
            raise IndexError("future bracket is unavailable at the last frame")
        first = self.frame(index)
        second = self.frame(index + 1)
        common = first[2] & second[2]
        position = (1.0 - alpha) * first[0] + alpha * second[0]
        velocity = (1.0 - alpha) * first[1] + alpha * second[1]
        return CurrentField(position, velocity, common)

    def current(self, index):
        return self.field(index, 0.0)

    def close(self):
        handle = getattr(self, "h5", None)
        if handle is not None:
            handle.close()
            self.h5 = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PredictedCurrent:
    """Prediction-side provider exposing one current ``x``/``v`` only."""

    provider_role = "predicted"

    def __init__(self, position, velocity, valid=None):
        self._field = CurrentField(position, velocity, valid)

    def current(self):
        return self._field

    def field(self, index=0, alpha=0.0):
        if index not in (0, None) or alpha not in (0, 0.0):
            raise PermissionError("predicted provider cannot access a future frame")
        return self._field

    def future(self, *_args, **_kwargs):
        raise PermissionError("predicted provider cannot access a future frame")


def _h5_attr_text(value):
    """Normalize a scalar HDF5 text attribute without accepting arrays."""
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8")
    if isinstance(value, np.ndarray):
        if value.ndim != 0:
            raise ValueError("HDF5 contract attributes must be scalar")
        return _h5_attr_text(value.item())
    return str(value)


def _h5_attr_bool(value, name):
    """Read a strict HDF5 boolean attribute."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer, float, np.floating)) and value in (0, 1):
        return bool(value)
    text = _h5_attr_text(value).lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise ValueError(f"{name} must be a boolean HDF5 attribute")


class StateH5Provider:
    """Read the complete predicted State H5 contract one current frame at a time.

    ``core_learning.rollout_case`` writes this contract with native velocity,
    composite ``(particle_zone, particle_id)`` identity, and explicit
    ``valid`` masks.  This reader intentionally does not expose a trajectory
    array to a sampler.  ``frame`` returns one immutable frame, while
    ``field(i, alpha)`` reads only the explicitly requested local bracket.
    ``future()`` is forbidden so a caller cannot accidentally use an
    unrequested future state as a model input.
    """

    provider_role = "predicted"
    state_schema = "core.state.native_velocity.v1"

    def __init__(self, source, *, max_cache=2, require_complete=True):
        self.source = Path(source)
        self.h5 = h5py.File(self.source, "r")
        self.cache = OrderedDict()
        self.max_cache = _positive_integer(max_cache, "max_cache")
        self.require_complete = bool(require_complete)
        required = {"time", "position", "velocity", "particle_id", "particle_zone", "mass", "valid"}
        if not required <= set(self.h5):
            self.close()
            missing = ", ".join(sorted(required - set(self.h5)))
            raise ValueError(f"predicted State H5 is missing datasets: {missing}")
        attrs = self.h5.attrs
        schema_version = attrs.get("schema_version", None)
        if schema_version is None or int(schema_version) != 1:
            self.close()
            raise ValueError("predicted State H5 must declare schema_version=1")
        if _h5_attr_text(attrs.get("state_schema", "")) != self.state_schema:
            self.close()
            raise ValueError("predicted State H5 has the wrong state_schema")
        try:
            future_inputs = _h5_attr_bool(attrs["future_state_inputs"], "future_state_inputs")
            autonomous = _h5_attr_bool(attrs["autonomous_prediction"], "autonomous_prediction")
        except KeyError as error:
            self.close()
            raise ValueError("predicted State H5 must declare future_state_inputs and autonomous_prediction") from error
        if future_inputs or not autonomous:
            self.close()
            raise ValueError("predicted State H5 must be autonomous and must not use future state inputs")
        identity = _h5_attr_text(attrs.get("identity_semantics", ""))
        if identity != "particle_zone,particle_id":
            self.close()
            raise ValueError("predicted State H5 has unsupported identity semantics")
        if _h5_attr_text(attrs.get("velocity_semantics", "")) != "native saved numerical velocity":
            self.close()
            raise ValueError("predicted State H5 has unsupported velocity semantics")
        self.times = np.asarray(self.h5["time"], dtype=np.float64)
        self._validate_layout()
        self.source_sha256 = digest(self.source)
        self.loaded_indices = []
        self.read_count = 0

    def _validate_layout(self):
        times = self.times
        if len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            self.close()
            raise ValueError("predicted State H5 time must be strictly increasing and finite")
        position = self.h5["position"]
        velocity = self.h5["velocity"]
        valid = self.h5["valid"]
        if position.ndim != 3 or position.shape[0] != len(times) or position.shape[2:] != (3,):
            self.close()
            raise ValueError("predicted position must have shape [frames,particles,3]")
        n = position.shape[1]
        if velocity.shape != position.shape or valid.shape != (len(times), n):
            self.close()
            raise ValueError("predicted velocity/valid axes do not match position")
        valid_values = np.asarray(valid)
        if valid_values.dtype.kind not in "biu" or not np.isin(valid_values, [0, 1]).all():
            self.close()
            raise ValueError("predicted valid must be an explicit boolean mask")
        if self.h5["particle_id"].shape != (n,) or self.h5["particle_zone"].shape != (n,):
            self.close()
            raise ValueError("predicted particle identity arrays must have shape [particles]")
        if self.h5["mass"].shape != (n,):
            self.close()
            raise ValueError("predicted State H5 mass must be a static [particles] array")
        particle_id = np.asarray(self.h5["particle_id"], dtype=np.int64)
        particle_zone = np.asarray(self.h5["particle_zone"], dtype=np.int64)
        if len(np.unique(np.column_stack((particle_zone, particle_id)), axis=0)) != n:
            self.close()
            raise ValueError("predicted State H5 has duplicate composite particle identity")
        mass = np.asarray(self.h5["mass"], dtype=np.float64)
        if not np.isfinite(mass).all() or np.any(mass <= 0):
            self.close()
            raise ValueError("predicted State H5 mass must be finite and positive")
        if self.require_complete and not np.asarray(valid, dtype=bool).all():
            self.close()
            raise ValueError("complete predicted State H5 required; invalid/unexecuted frames are forbidden")
        # Validate active data without requiring an eager copy of the whole
        # trajectory.  A failed rollout may retain invalid rows, but it may
        # never hide non-finite values behind a true valid mask.
        for index in range(len(times)):
            mask = np.asarray(valid[index], dtype=bool)
            if (not np.isfinite(position[index][mask]).all()
                    or not np.isfinite(velocity[index][mask]).all()):
                self.close()
                raise ValueError(f"predicted State H5 has non-finite active values at frame {index}")
        self.particle_count = n
        self.particle_id = particle_id
        self.particle_zone = particle_zone
        self.mass = mass
        for value in (self.particle_id, self.particle_zone, self.mass):
            value.setflags(write=False)

    def _check_index(self, index):
        if isinstance(index, bool) or not isinstance(index, (int, np.integer)):
            raise TypeError("frame index must be an integer")
        index = int(index)
        if not 0 <= index < len(self.times):
            raise IndexError("frame index outside predicted State H5")
        return index

    def frame(self, index):
        index = self._check_index(index)
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        position = np.asarray(self.h5["position"][index], dtype=np.float64)
        velocity = np.asarray(self.h5["velocity"][index], dtype=np.float64)
        valid = np.asarray(self.h5["valid"][index], dtype=bool)
        valid &= np.isfinite(position).all(axis=1) & np.isfinite(velocity).all(axis=1)
        position.setflags(write=False)
        velocity.setflags(write=False)
        valid.setflags(write=False)
        value = (position, velocity, valid)
        self.cache[index] = value
        self.cache.move_to_end(index)
        self.loaded_indices.append(index)
        self.read_count += 1
        while len(self.cache) > self.max_cache:
            self.cache.popitem(last=False)
        return value

    def state(self, index):
        """Return one immutable ``core_contract.State`` frame."""
        from scripts.core_contract import State

        index = self._check_index(index)
        position, velocity, valid = self.frame(index)
        return State(
            float(self.times[index]), position, velocity, self.particle_id,
            self.particle_zone, self.mass, valid,
        )

    def field(self, index, alpha=0.0):
        index = self._check_index(index)
        if not np.isfinite(alpha) or not 0.0 <= alpha <= 1.0:
            raise ValueError("interpolation alpha must be in [0,1]")
        first = self.frame(index)
        if alpha == 0.0:
            return CurrentField(*first)
        if index + 1 >= len(self.times):
            raise IndexError("future bracket is unavailable at the last predicted frame")
        second = self.frame(index + 1)
        common = first[2] & second[2]
        position = (1.0 - alpha) * first[0] + alpha * second[0]
        velocity = (1.0 - alpha) * first[1] + alpha * second[1]
        return CurrentField(position, velocity, common)

    def current(self, index=0):
        return self.field(index, 0.0)

    def future(self, *_args, **_kwargs):
        raise PermissionError("predicted State provider cannot access an implicit future state")

    def close(self):
        handle = getattr(self, "h5", None)
        if handle is not None:
            handle.close()
            self.h5 = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


PredictedStateH5Provider = StateH5Provider
PredictedStateH5Frames = StateH5Provider
PredictedStateProvider = StateH5Provider


def validate_predicted_state_h5(source, *, require_complete=True):
    """Return a compact receipt after validating luna_ml's State H5 output."""
    with StateH5Provider(source, require_complete=require_complete) as provider:
        return {
            "schema": provider.state_schema,
            "provider_role": provider.provider_role,
            "source_sha256": provider.source_sha256,
            "frames": int(len(provider.times)),
            "particles": int(provider.particle_count),
            "time_start_s": float(provider.times[0]),
            "time_end_s": float(provider.times[-1]),
            "require_complete": bool(require_complete),
            "future_state_inputs": False,
            "autonomous_prediction": True,
        }


def read_predicted_state_h5(source, index=0, *, require_complete=True):
    """Read one public State frame while keeping the HDF5 handle scoped."""
    with StateH5Provider(source, require_complete=require_complete) as provider:
        return provider.state(index)


read_state_h5 = read_predicted_state_h5


def _box_definition(kind, low, size, **extra):
    low = np.asarray(low, dtype=np.float64)
    size = np.asarray(size, dtype=np.float64)
    if low.shape != (3,) or size.shape != (3,) or not np.isfinite(low).all() or not np.isfinite(size).all() or np.any(size <= 0):
        raise ValueError("box low and size must be finite three-vectors with positive size")
    result = {
        "kind": str(kind),
        "box_low_m": low.tolist(),
        "box_size_m": size.tolist(),
        "box_high_m": (low + size).tolist(),
        "boundary_policy": "closed_box_membership",
    }
    result.update(extra)
    return result


def _f4_q(q):
    try:
        value = float(q)
    except (TypeError, ValueError):
        raise ValueError("F4 q must be finite and in [0,1]") from None
    if isinstance(q, (bool, np.bool_)) or not np.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("F4 q must be finite and in [0,1]")
    return value


def f4_source_region(q=0.5):
    """Return the continuous falling-drop source box for F4 q."""
    q = _f4_q(q)
    left = 0.25 + 0.22 * q
    return _box_definition(
        "continuous_drop_box", [left, 0.12, 0.4], F4_SOURCE_SIZE_M,
        source_role="falling liquid drop, initial fluid box",
        initial_velocity_mps=[0.0, 0.0, -0.5],
        drop_left_x_m=left,
        q=q,
    )


def f4_destination_region():
    """Return the continuous resting-pool destination box."""
    return _box_definition(
        "continuous_resting_pool_box", F4_DESTINATION_LOW_M, F4_DESTINATION_SIZE_M,
        destination_role="resting basin liquid and post-contact destination volume",
        pool_free_surface_z_m=F4_INTERFACE_Z_M,
    )


def f4_resting_pool_definition(q=0.5, dp_m=None):
    """Return the immutable JSON-ready F4 overlay definition.

    ``dp_m`` is metadata only: material sampling uses the saved native H5 and
    never synthesizes a field from resolution.  It is accepted here so a
    queued matrix cell can bind its source definition exactly.
    """
    q = _f4_q(q)
    if dp_m is not None:
        try:
            dp_value = float(dp_m)
        except (TypeError, ValueError):
            raise ValueError("dp_m must be finite and positive when supplied") from None
        if not np.isfinite(dp_value) or dp_value <= 0:
            raise ValueError("dp_m must be finite and positive when supplied")
    else:
        dp_value = None
    source = f4_source_region(q)
    destination = f4_destination_region()
    return {
        "family_id": "F4",
        "scope_id": F4_SCOPE_ID,
        "revision_id": F4_REVISION_ID,
        "recipe_id": F4_RECIPE_ID,
        "recipe": "mdbc_native",
        "stage": "qualification_only",
        "q": q,
        "dp_m": dp_value,
        "source_definition": source,
        "destination_definition": destination,
        "wall_bounds_m": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0, "zmax": 0.6},
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "event_definition": {
            "path_interpolation": "continuous_linear_segment_per_tracer_substep",
            "contact": {"interface_plane_z_m": F4_INTERFACE_Z_M, "direction": "downward", "requires_vertical_velocity_mps_lt": 0.0},
            "upward_propagation": {"interface_plane_z_m": F4_INTERFACE_Z_M, "direction": "upward", "requires_vertical_velocity_mps_gt": 0.0},
            "return": {"interface_plane_z_m": F4_INTERFACE_Z_M, "direction": "downward", "requires_vertical_velocity_mps_lt": 0.0},
            "residence": {"definition": "time inside destination box after contact, right-censored if unresolved"},
            "post_return_window": {
                "gravity_time_s": F4_GRAVITY_TIME_S,
                "initial_horizon_s": F4_INITIAL_HORIZON_S,
                "maximum_extended_horizon_s": F4_MAXIMUM_HORIZON_S,
                "extension_policy": "double whole scope once if any required event is right-censored; never shorten",
                "completion_required": True,
            },
        },
        "source_labels": "continuous source-box membership; native Mk and particle_id are not material truth",
        "seed_identity": "independent seed-XXXXXX ids, never native particle_id",
    }


def _box_membership(points, region):
    points = _validate_seeds(points)
    low = np.asarray(region["box_low_m"], dtype=np.float64)
    high = low + np.asarray(region["box_size_m"], dtype=np.float64)
    return np.all((points >= low) & (points <= high), axis=1)


def f4_source_membership(points, q=0.5):
    return _box_membership(points, f4_source_region(q))


def f4_destination_membership(points):
    return _box_membership(points, f4_destination_region())


def f4_continuous_source_labels(points, q=0.5, *, require_source=False):
    """Label continuous F4 regions: 1 drop, 0 resting pool, -1 outside."""
    points = _validate_seeds(points)
    source = f4_source_membership(points, q)
    destination = f4_destination_membership(points)
    if np.any(source & destination):
        raise ValueError("F4 source and destination boxes overlap")
    labels = np.full(len(points), -1, dtype=np.int8)
    labels[destination] = 0
    labels[source] = 1
    if require_source and np.any(~source):
        raise ValueError("all F4 material seeds must lie inside the continuous source drop box")
    return labels


f4_source_labels = f4_continuous_source_labels


def seeds_f4(count=512, q=0.5):
    """Return equal-volume independent seeds inside the F4 source drop."""
    if count not in (512, 4096):
        raise ValueError("F4 seed count must be 512 or 4096")
    q = _f4_q(q)
    n = {512: 8, 4096: 16}[int(count)]
    low = np.asarray(f4_source_region(q)["box_low_m"], dtype=np.float64)
    size = F4_SOURCE_SIZE_M
    axes = [lo + (np.arange(n) + 0.5) * width / n for lo, width in zip(low, size)]
    return np.ascontiguousarray(np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3), dtype=np.float64)


f4_source_seeds = seeds_f4


def f4_walls():
    """Registered F4 basin walls: bottom and four sides, open at the top."""
    return box_surface_triangles(F4_DESTINATION_LOW_M, F4_WALL_HIGH_M,
                                 sides=("xmin", "xmax", "ymin", "ymax", "zmin"))


# Descriptive aliases used by callers that name providers rather than states.
PredictedProvider = PredictedCurrent
ReferenceProvider = ReferenceFrames


def seeds_f3(count=512):
    """Return equal-volume independent F3 seeds for 512 or 4096 points."""
    if count not in (512, 4096):
        raise ValueError("F3 seed count must be 512 or 4096")
    shape = {512: (16, 8, 4), 4096: (32, 16, 8)}[int(count)]
    axes = [lo + (np.arange(n) + 0.5) * size / n for lo, size, n in zip((-.45, -.09, 0.0), (.9, .18, .09), shape)]
    return np.ascontiguousarray(np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3), dtype=np.float64)


def f3_walls():
    """Registered F3 static finite wall set (open top)."""
    return box_surface_triangles([-.45, -.09, 0.0], [.45, .09, .51], sides=("xmin", "xmax", "ymin", "ymax", "zmin"))


def _prepare_seed_metadata(initial, weights, labels, tracer_ids):
    initial = _validate_seeds(initial)
    n = len(initial)
    if weights is None:
        weight = np.full(n, 1.0 / n, dtype=np.float64)
    else:
        weight = np.asarray(weights, dtype=np.float64)
        if weight.shape != (n,) or not np.isfinite(weight).all() or np.any(weight < 0) or not weight.sum() > 0:
            raise ValueError("weights must be nonnegative finite values with positive total")
        weight = weight / weight.sum()
    if labels is None:
        labels = continuous_source_labels(initial)
    else:
        labels = np.asarray(labels)
        if labels.shape != (n,):
            raise ValueError("source_labels must have shape [N]")
        if labels.dtype.kind in "fc" and not np.isfinite(labels).all():
            raise ValueError("source_labels must be finite")
        labels = np.array(labels, copy=True)
    if tracer_ids is None:
        tracer_ids = np.asarray([f"seed-{i:06d}" for i in range(n)], dtype=object)
    else:
        tracer_ids = np.asarray(tracer_ids)
        if tracer_ids.shape != (n,):
            raise ValueError("tracer_ids must have shape [N]")
        tracer_ids = np.asarray([str(_json_scalar(item)) for item in tracer_ids], dtype=object)
    if len(set(tracer_ids.tolist())) != n:
        raise ValueError("tracer_ids must be unique")
    return initial, weight, labels, tracer_ids


def weighted_cdf(values, weights, *, mask=None, denominator=None):
    """Return a weighted empirical CDF for event times.

    ``denominator`` is the full source mass.  Thus right-censored and unknown
    tracer mass remain visible as a gap in the CDF instead of being silently
    renormalized away.
    """
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if values.shape != weights.shape:
        raise ValueError("values and weights must have matching shapes")
    if mask is None:
        mask = np.isfinite(values)
    mask = np.asarray(mask, dtype=bool) & np.isfinite(values) & np.isfinite(weights) & (weights >= 0)
    if denominator is None:
        denominator = float(weights.sum())
    denominator = float(denominator)
    if denominator < 0 or not np.isfinite(denominator):
        raise ValueError("CDF denominator must be finite and nonnegative")
    if denominator == 0 or not mask.any():
        return {"time_s": [], "mass_fraction": [], "lower": [], "upper": [], "event_mass_fraction": 0.0}
    order = np.argsort(values[mask], kind="mergesort")
    times = values[mask][order]
    event_weights = weights[mask][order]
    cumulative = np.cumsum(event_weights) / denominator
    unique, last = np.unique(times, return_index=False, return_counts=True)
    ends = np.cumsum(last) - 1
    cdf = cumulative[ends]
    event_fraction = float(cumulative[-1])
    return {
        "time_s": unique.tolist(),
        "mass_fraction": np.minimum(1.0, cdf).tolist(),
        "lower": np.minimum(1.0, cdf).tolist(),
        "upper": np.minimum(1.0, cdf).tolist(),
        "event_mass_fraction": min(1.0, event_fraction),
    }


first_passage_cdf = weighted_cdf


def _checkpoint_paths(output):
    output = Path(output)
    return output.with_name(output.name + ".checkpoint.npz"), output.with_name(output.name + ".checkpoint.json")


def _atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _write_checkpoint(output, binding, frame, state):
    """Atomically publish a complete state before its H5 row is committed."""
    npz_path, manifest_path = _checkpoint_paths(output)
    temporary = npz_path.with_name(npz_path.name + ".partial.npz")
    arrays = {name: np.asarray(state[name]) for name in CHECKPOINT_FIELDS}
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, npz_path)
    record = {
        "schema": CHECKPOINT_SCHEMA,
        "binding_sha256": hashlib.sha256(binding.encode()).hexdigest(),
        "committed": int(frame),
        "state_sha256": digest(npz_path),
        "fields": list(CHECKPOINT_FIELDS),
    }
    _atomic_json(manifest_path, record)


def _validate_checkpoint_state(state, fields):
    """Reject malformed recovery state before it can overwrite an HDF5 row."""
    fields = tuple(fields)
    if fields == CHECKPOINT_FIELDS:
        boolean_fields = {"reliable", "returned"}
    elif fields == F4_CHECKPOINT_FIELDS:
        boolean_fields = {"reliable", "contacted", "upward", "returned"}
    else:
        raise ValueError("unknown material checkpoint field schema")
    if tuple(state) != fields:
        raise ValueError("material checkpoint fields are incomplete")
    position = np.asarray(state["position"])
    if position.ndim != 2 or position.shape[1:] != (3,) or not np.isfinite(position).all():
        raise ValueError("material checkpoint position has an invalid shape or value")
    count = len(position)
    for name in fields:
        if name == "position":
            continue
        value = np.asarray(state[name])
        if value.shape != (count,):
            raise ValueError("material checkpoint state axes do not match position")
        if name in boolean_fields:
            if value.dtype.kind != "b":
                raise ValueError("material checkpoint boolean state must use bool dtype")
        elif np.isinf(value).any() or (name == "residence" and not np.isfinite(value).all()):
            raise ValueError("material checkpoint numeric state contains non-finite values")
    if np.any(np.asarray(state["residence"]) < 0):
        raise ValueError("material checkpoint residence cannot be negative")


def _read_checkpoint(output, binding):
    npz_path, manifest_path = _checkpoint_paths(output)
    if not manifest_path.exists() or not npz_path.exists():
        return None
    try:
        record = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("restart checkpoint manifest is not valid JSON") from error
    expected = hashlib.sha256(binding.encode()).hexdigest()
    if record.get("schema") != CHECKPOINT_SCHEMA or record.get("binding_sha256") != expected:
        raise ValueError("restart checkpoint provenance mismatch")
    if record.get("fields") != list(CHECKPOINT_FIELDS) or digest(npz_path) != record.get("state_sha256"):
        raise ValueError("restart checkpoint is incomplete or changed")
    committed = record.get("committed")
    if isinstance(committed, (bool, np.bool_)) or not isinstance(committed, (int, np.integer)) or int(committed) < 0:
        raise ValueError("restart checkpoint committed frame is invalid")
    try:
        with np.load(npz_path, allow_pickle=False) as archive:
            if tuple(archive.files) != CHECKPOINT_FIELDS:
                raise ValueError("restart checkpoint fields are incomplete")
            state = {name: np.array(archive[name], copy=True) for name in CHECKPOINT_FIELDS}
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("restart checkpoint state is unreadable") from error
    _validate_checkpoint_state(state, CHECKPOINT_FIELDS)
    return int(committed), state


def _initial_state(initial, frames, walls, neighbours, error_estimator):
    # Validate support at the initial saved instant.  This avoids reporting a
    # seed as reliable solely because it has not yet taken one integration step.
    field = frames.field(0, 0.0)
    _, support_distance, support_ok, _ = field.sample(
        initial,
        walls,
        neighbours=neighbours,
        regularization=REGULARIZATION_M,
        error_estimator=error_estimator,
        return_diagnostics=True,
    )
    support_ok &= np.isfinite(initial).all(axis=1) & (support_distance <= MAXIMUM_SUPPORT_DISTANCE_M)
    return {
        "position": np.array(initial, copy=True),
        "reliable": support_ok.astype(bool),
        "first_passage": np.full(len(initial), np.nan, dtype=np.float64),
        "return_time": np.full(len(initial), np.nan, dtype=np.float64),
        "residence": np.zeros(len(initial), dtype=np.float64),
        "residence_left": np.zeros(len(initial), dtype=np.float64),
        "residence_right": np.zeros(len(initial), dtype=np.float64),
        "returned": np.zeros(len(initial), dtype=bool),
    }


def _create_output(out, initial, weight, labels, tracer_ids, binding, definition):
    n = len(initial)
    out.attrs["schema"] = SCHEMA
    out.attrs["binding"] = binding
    out.attrs["committed"] = -1
    out.attrs["checkpoint_schema"] = CHECKPOINT_SCHEMA
    out.create_dataset("initial_position", data=initial)
    out.create_dataset("weight", data=weight)
    if labels.dtype.kind in "OUS":
        out.create_dataset("source_label", data=np.asarray([str(_json_scalar(item)) for item in labels], dtype=h5py.string_dtype("utf-8")))
    else:
        out.create_dataset("source_label", data=labels)
    out.create_dataset("tracer_id", data=np.asarray(tracer_ids, dtype=h5py.string_dtype("utf-8")))
    out.attrs["source_definition"] = json.dumps(definition, sort_keys=True)
    out.attrs["seed_identity"] = "independent_geometric_seed; no native particle id"
    for name, shape, dtype in (
        ("time", (), "f8"),
        ("position", (n, 3), "f8"),
        ("reliable", (n,), "?"),
        ("first_passage", (n,), "f8"),
        ("return_time", (n,), "f8"),
        ("residence", (n,), "f8"),
        ("residence_left", (n,), "f8"),
        ("residence_right", (n,), "f8"),
        ("returned", (n,), "?"),
    ):
        out.create_dataset(name, shape=(0,) + shape, maxshape=(None,) + shape, dtype=dtype, chunks=(1,) + shape)
    out.flush()


def _validate_resume_output(out, initial, weight, labels, tracer_ids, binding):
    if out.attrs.get("schema") != SCHEMA or out.attrs.get("binding") != binding:
        raise ValueError("restart provenance mismatch")
    for name in ("initial_position", "weight", "source_label", "tracer_id") + HISTORY_FIELDS:
        if name not in out:
            raise ValueError(f"restart output missing dataset {name}")
    if not np.array_equal(out["initial_position"][:], initial) or not np.array_equal(out["weight"][:], weight):
        raise ValueError("restart seed metadata mismatch")
    if not np.array_equal(out["source_label"][:], labels):
        raise ValueError("restart source definition mismatch")
    stored_ids = np.asarray(out["tracer_id"].asstr()[:])
    if _hash_array(stored_ids) != _hash_array(tracer_ids):
        raise ValueError("restart tracer identity mismatch")
    return int(out.attrs.get("committed", -1))


def _append_h5_frame(out, frame, frames, state):
    """Rewrite the checkpoint frame and make it the HDF5 committed prefix."""
    target = int(frame) + 1
    for name in HISTORY_FIELDS:
        out[name].resize(target, axis=0)
    values = {"time": frames.times[frame], **{name: state[name] for name in CHECKPOINT_FIELDS}}
    for name, value in values.items():
        out[name][frame] = value
    out.flush()
    out.attrs["committed"] = int(frame)
    out.flush()


def _state_from_h5(out, frame):
    return {name: np.array(out[name][frame], copy=True) for name in CHECKPOINT_FIELDS}


def _advance_state(state, field0, field1, walls, frame_time, dt, origin, substep, neighbours, error_estimator):
    """Advance all still-reliable seeds through one RK2 substep."""
    q = state["position"]
    active = state["reliable"]
    v0, d0, g0 = field0.sample(
        q, walls, neighbours=neighbours, regularization=REGULARIZATION_M,
        error_estimator=error_estimator,
    )
    predictor = q + np.nan_to_num(v0, nan=0.0, posinf=0.0, neginf=0.0) * dt
    v1, d1, g1 = field1.sample(
        predictor, walls, neighbours=neighbours, regularization=REGULARIZATION_M,
        error_estimator=error_estimator,
    )
    candidate = q + 0.5 * np.nan_to_num(v0 + v1, nan=0.0, posinf=0.0, neginf=0.0) * dt
    blocked = spacetime_swept_wall_blocked(q, candidate, walls, walls)
    usable = (
        active
        & g0
        & g1
        & ~blocked
        & np.isfinite(v0).all(axis=1)
        & np.isfinite(v1).all(axis=1)
        & (np.maximum(d0, d1) <= MAXIMUM_SUPPORT_DISTANCE_M)
    )
    side0 = q[:, 0] >= 0.0
    side1 = candidate[:, 0] >= 0.0
    changed = side0 != side1
    fraction = np.divide(-q[:, 0], candidate[:, 0] - q[:, 0], out=np.zeros(len(q)), where=changed)
    fraction = np.clip(fraction, 0.0, 1.0)
    pre_event = np.isfinite(state["first_passage"])
    crossing = usable & changed & (side1 != origin) & ~pre_event
    state["first_passage"][crossing] = frame_time + (substep + fraction[crossing]) * dt
    returning = usable & changed & (side1 == origin) & pre_event & ~state["returned"]
    state["return_time"][returning] = frame_time + (substep + fraction[returning]) * dt
    state["returned"][returning] = True

    # Integrate continuous half-space residence exactly for the linear RK2
    # segment.  The scalar residence field is the source-opposite duration.
    left_fraction = np.where(changed, np.where(~side0, fraction, 1.0 - fraction), (~side0).astype(float))
    right_fraction = np.where(changed, np.where(side0, fraction, 1.0 - fraction), side0.astype(float))
    left_fraction = np.where(usable, left_fraction, 0.0)
    right_fraction = np.where(usable, right_fraction, 0.0)
    state["residence_left"] += left_fraction * dt
    state["residence_right"] += right_fraction * dt
    state["residence"] += np.where(origin, left_fraction, right_fraction) * dt
    state["position"] = np.where(usable[:, None], candidate, q)
    state["reliable"] = usable


def trace(
    source,
    output,
    initial,
    walls,
    *,
    substeps=2,
    stop_after=None,
    resume=False,
    weights=None,
    source_labels=None,
    tracer_ids=None,
    source_axis=0,
    source_boundary=0.0,
    provider=None,
    kill_after=None,
    neighbour_variant="baseline24",
):
    """Trace independent seeds through native saved reference frames.

    ``stop_after`` is an inclusive native frame index, so ``stop_after=1``
    commits frames 0 and 1.  A later ``resume=True`` trims any HDF5 tail to
    the atomic sidecar checkpoint and continues to the full source window.
    ``kill_after`` is a test hook: it sends SIGKILL immediately after writing
    the selected checkpoint and before the HDF5 row, exercising independent
    process recovery.  It is never set by the normal CLI worker.
    """
    substeps = _positive_integer(substeps, "substeps")
    neighbour_variant, backend, neighbours, error_estimator = _neighbour_variant(neighbour_variant)
    initial, weight, labels, tracer_ids = _prepare_seed_metadata(initial, weights, source_labels, tracer_ids)
    walls = _validate_walls(walls)
    if not np.isfinite(source_boundary):
        raise ValueError("source boundary must be finite")
    if source_axis != 0:
        labels = continuous_source_labels(initial, axis=source_axis, boundary=source_boundary) if source_labels is None else labels
    elif source_labels is None and source_boundary != 0.0:
        labels = continuous_source_labels(initial, axis=0, boundary=source_boundary)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if kill_after is not None:
        if isinstance(kill_after, bool) or not isinstance(kill_after, (int, np.integer)) or kill_after < 0:
            raise ValueError("kill_after must be a nonnegative frame index")
        kill_after = int(kill_after)

    owns_provider = provider is None
    frames = provider if provider is not None else ReferenceFrames(source)
    source_path = Path(source) if provider is None else None
    source_hash = getattr(frames, "source_sha256", None) if source_path is not None else getattr(provider, "source_sha256", "provider-supplied")
    if not source_hash:
        source_hash = digest(source_path) if source_path is not None else "provider-supplied"
    source_semantics = "reference_native_saved_frames" if provider is None else getattr(provider, "provider_role", "provider")
    binding = {
        "schema": SCHEMA,
        "source_sha256": source_hash,
        "code_sha256": digest(Path(__file__)),
        "neighbor_code_sha256": digest(Path(__file__).with_name("f3_material_neighbors.py")),
        "passive_code_sha256": digest(Path(__file__).with_name("passive_tracers.py")),
        "initial_sha256": _hash_array(initial),
        "weight_sha256": _hash_array(weight),
        "source_label_sha256": _hash_array(labels),
        "tracer_id_sha256": _hash_array(tracer_ids),
        "walls_sha256": _hash_array(walls),
        "source_definition": source_definition(axis=source_axis, boundary=source_boundary),
        "substeps": substeps,
        "source_semantics": source_semantics,
        "backend": backend,
        "neighbour_variant": neighbour_variant,
        "neighbours": neighbours,
        "error_estimator": error_estimator,
        "regularization_m": REGULARIZATION_M,
        "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
        "support_gate": GATE,
    }
    binding_text = _canonical(binding)
    started = time.monotonic()
    timing = {"field_index": 0.0, "interpolation": 0.0, "sweep": 0.0, "write": 0.0, "checkpoint": 0.0}
    npz_path, manifest_path = _checkpoint_paths(output)
    result = None
    try:
        if resume:
            if not output.exists():
                raise FileNotFoundError(f"cannot resume missing output {output}")
            mode = "r+"
        else:
            if output.exists():
                raise FileExistsError(f"output already exists: {output}")
            if npz_path.exists() or manifest_path.exists():
                raise FileExistsError(f"stale checkpoint exists for missing output: {npz_path}")
            mode = "x"
        with h5py.File(output, mode) as out:
            if resume:
                _validate_resume_output(out, initial, weight, labels, tracer_ids, binding_text)
                checkpoint = _read_checkpoint(output, binding_text)
                if checkpoint is None:
                    committed = int(out.attrs.get("committed", -1))
                    if committed < 0:
                        raise ValueError("restart has no complete checkpoint")
                    state = _state_from_h5(out, committed)
                else:
                    committed, state = checkpoint
                if committed < 0 or committed >= len(frames.times):
                    raise ValueError("restart checkpoint frame is outside reference source")
                # Any row after the sidecar frame may have been partially
                # written when the process died; the sidecar is authoritative.
                for name in HISTORY_FIELDS:
                    out[name].resize(committed + 1, axis=0)
                _append_h5_frame(out, committed, frames, state)
            else:
                _create_output(out, initial, weight, labels, tracer_ids, binding_text, binding["source_definition"])
                t = time.monotonic()
                state = _initial_state(initial, frames, walls, neighbours, error_estimator)
                timing["field_index"] += time.monotonic() - t
                t = time.monotonic()
                _write_checkpoint(output, binding_text, 0, state)
                timing["checkpoint"] += time.monotonic() - t
                if kill_after == 0:
                    os.kill(os.getpid(), signal.SIGKILL)
                t = time.monotonic()
                _append_h5_frame(out, 0, frames, state)
                timing["write"] += time.monotonic() - t
                committed = 0

            if stop_after is not None and int(stop_after) < 0:
                raise ValueError("stop_after must be nonnegative")
            end = len(frames.times) - 1 if stop_after is None else min(int(stop_after), len(frames.times) - 1)
            if end < committed:
                end = committed
            origin = labels.astype(bool) if labels.dtype.kind in "biu" else (initial[:, int(source_axis)] >= source_boundary)
            for frame_index in range(committed, end):
                dt = (float(frames.times[frame_index + 1]) - float(frames.times[frame_index])) / substeps
                t = time.monotonic()
                field0 = frames.field(frame_index, 0.0)
                timing["field_index"] += time.monotonic() - t
                for substep in range(substeps):
                    t = time.monotonic()
                    field1 = frames.field(frame_index, (substep + 1) / substeps)
                    timing["field_index"] += time.monotonic() - t
                    t = time.monotonic()
                    _advance_state(
                        state,
                        field0,
                        field1,
                        walls,
                        float(frames.times[frame_index]),
                        dt,
                        origin,
                        substep,
                        neighbours,
                        error_estimator,
                    )
                    timing["interpolation"] += time.monotonic() - t
                    field0 = field1
                next_frame = frame_index + 1
                t = time.monotonic()
                _write_checkpoint(output, binding_text, next_frame, state)
                timing["checkpoint"] += time.monotonic() - t
                if kill_after == next_frame:
                    os.kill(os.getpid(), signal.SIGKILL)
                t = time.monotonic()
                _append_h5_frame(out, next_frame, frames, state)
                timing["write"] += time.monotonic() - t
                committed = next_frame
                if committed % 20 == 0:
                    print(json.dumps({"frame": committed, "total": len(frames.times), "unknown": float((~state["reliable"]).mean())}), flush=True)

            result = macro_summary(out)
            result.update(
                status="completed" if end == len(frames.times) - 1 else "partial",
                qualification_claim="none",
                material_reliability="not_established",
                qualified_T2_macro=False,
                qualified_T2_path=False,
                elapsed_seconds=time.monotonic() - started,
                max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                timing_seconds=timing,
                committed_frame=int(out.attrs["committed"]),
                native_frame_count=len(frames.times),
                binding=binding,
                checkpoint_manifest=str(manifest_path),
            )
            out.attrs["result"] = json.dumps(result, sort_keys=True, allow_nan=False)
    finally:
        if owns_provider:
            frames.close()
    target = output.with_suffix(".json")
    temporary = target.with_suffix(".json.partial")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, target)
    return result


def _weighted_fraction(weight, select, denominator):
    return float(weight[select].sum() / denominator) if denominator else 0.0


def macro_summary(out):
    """Summarize closure, first-passage CDF, residence, and return by source."""
    committed = int(out.attrs["committed"])
    weight = np.asarray(out["weight"][:], dtype=np.float64)
    labels = np.asarray(out["source_label"][:])
    reliable = np.asarray(out["reliable"][committed], dtype=bool)
    position = np.asarray(out["position"][committed], dtype=np.float64)
    first = np.asarray(out["first_passage"][committed], dtype=np.float64)
    returned = np.asarray(out["returned"][committed], dtype=bool)
    return_time = np.asarray(out["return_time"][committed], dtype=np.float64) if "return_time" in out else np.full(len(first), np.nan)
    residence = np.asarray(out["residence"][committed], dtype=np.float64)
    residence_left = np.asarray(out["residence_left"][committed], dtype=np.float64) if "residence_left" in out else np.zeros(len(first))
    residence_right = np.asarray(out["residence_right"][committed], dtype=np.float64) if "residence_right" in out else np.zeros(len(first))
    total_mass = float(weight.sum())
    rows = []
    for source in np.unique(labels):
        select = labels == source
        source_mass = float(weight[select].sum())
        if source_mass <= 0:
            continue
        source_value = _json_scalar(source)
        unknown_select = select & ~reliable
        terminal_left = _weighted_fraction(weight, select & reliable & (position[:, 0] < 0.0), source_mass)
        terminal_right = _weighted_fraction(weight, select & reliable & (position[:, 0] >= 0.0), source_mass)
        unknown = _weighted_fraction(weight, unknown_select, source_mass)
        event = select & np.isfinite(first)
        event_unknown = unknown_select & ~np.isfinite(first)
        no_event = select & reliable & ~np.isfinite(first)
        event_cdf = weighted_cdf(first, weight, mask=event, denominator=source_mass)
        event_cdf["unknown_upper_addition"] = unknown
        event_cdf["upper"] = [min(1.0, value + unknown) for value in event_cdf["lower"]]
        return_cdf = weighted_cdf(return_time, weight, mask=select & np.isfinite(return_time), denominator=source_mass)
        closure = terminal_left + terminal_right + unknown
        rows.append(
            {
                "source": source_value,
                "initial_mass_fraction": source_mass / total_mass if total_mass else 0.0,
                "terminal": [terminal_left, terminal_right],
                "terminal_upper": [min(1.0, terminal_left + unknown), min(1.0, terminal_right + unknown)],
                "terminal_categories": {"left": terminal_left, "right": terminal_right, "unknown": unknown},
                "unknown_fraction": unknown,
                "unknown_fraction_max": unknown,
                "unknown_fraction_monotone": True,
                "final_unknown_fraction": unknown,
                "reliable_path_coverage": _weighted_fraction(weight, select & reliable, source_mass),
                "mass_closure_fraction": closure,
                "mass_closure_error": closure - 1.0,
                "observed_first_passage_fraction": _weighted_fraction(weight, event, source_mass),
                "no_first_passage_fraction": _weighted_fraction(weight, no_event, source_mass),
                "unknown_first_passage_fraction_max": _weighted_fraction(weight, event_unknown, source_mass),
                "first_passage_cdf": event_cdf,
                "observed_return_fraction": _weighted_fraction(weight, select & returned, source_mass),
                "return_cdf": return_cdf,
                "residence_opposite_s": float(np.sum(weight[select] * residence[select]) / source_mass),
                "residence_left_s": float(np.sum(weight[select] * residence_left[select]) / source_mass),
                "residence_right_s": float(np.sum(weight[select] * residence_right[select]) / source_mass),
            }
        )
    definition = json.loads(out.attrs.get("source_definition", json.dumps(source_definition())))
    return {
        "task": "F3 x=0 crossing, opposite-half residence, return; static finite tank",
        "source_definition": definition,
        "by_source": rows,
        "mass_closed": all(abs(row["mass_closure_error"]) <= 1e-12 for row in rows),
        "unknown_gate_pass": all(row["unknown_fraction_max"] <= 0.01 for row in rows),
        "unknown_fraction_monotone": True,
        "common_reliable_path_coverage": float(weight[reliable].sum() / total_mass) if total_mass else 0.0,
        "committed_frame": committed,
        "committed_time_s": float(out["time"][committed]),
    }


def _segment_box_interval(start, end, low, size):
    """Return the closed-box parameter interval occupied by one segment."""
    start = np.asarray(start, dtype=np.float64)
    end = np.asarray(end, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    high = low + np.asarray(size, dtype=np.float64)
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


def _crossing_fraction(z0, z1, plane):
    denominator = float(z1 - z0)
    if abs(denominator) <= np.finfo(np.float64).eps:
        return 0.0
    return float(np.clip((plane - z0) / denominator, 0.0, 1.0))


class F4EventTracker:
    """Continuous F4 contact, upward, return, and residence observer.

    Events are evaluated on the linear RK2 tracer segment, not on a saved
    native-frame chord.  The observer only mutates per-seed arrays supplied in
    the state dictionary, so its state is safe to include in the atomic
    material checkpoint.
    """

    def __init__(self, count, *, definition=None):
        self.count = _positive_integer(count, "event tracker count")
        self.definition = f4_resting_pool_definition() if definition is None else definition
        self.plane_z = float(self.definition.get("event_definition", {}).get("contact", {}).get("interface_plane_z_m", F4_INTERFACE_Z_M))
        destination = self.definition.get("destination_definition", f4_destination_region())
        self.destination_low = np.asarray(destination["box_low_m"], dtype=np.float64)
        self.destination_size = np.asarray(destination["box_size_m"], dtype=np.float64)

    def initial_state(self):
        n = self.count
        return {
            "contact_time": np.full(n, np.nan, dtype=np.float64),
            "upward_time": np.full(n, np.nan, dtype=np.float64),
            "return_time": np.full(n, np.nan, dtype=np.float64),
            "residence": np.zeros(n, dtype=np.float64),
            "contacted": np.zeros(n, dtype=bool),
            "upward": np.zeros(n, dtype=bool),
            "returned": np.zeros(n, dtype=bool),
        }

    def advance(self, state, start, end, velocity_start, velocity_end, segment_time, dt, usable):
        """Update one tracer segment and return its event interval state."""
        start = np.asarray(start, dtype=np.float64)
        end = np.asarray(end, dtype=np.float64)
        velocity_start = np.asarray(velocity_start, dtype=np.float64)
        velocity_end = np.asarray(velocity_end, dtype=np.float64)
        usable = np.asarray(usable, dtype=bool)
        if start.shape != (self.count, 3) or end.shape != start.shape:
            raise ValueError("F4 event segment positions must have shape [N,3]")
        if velocity_start.shape != start.shape or velocity_end.shape != start.shape or usable.shape != (self.count,):
            raise ValueError("F4 event segment velocity/valid axes do not match")
        if not np.isfinite(segment_time) or not np.isfinite(dt) or dt <= 0:
            raise ValueError("F4 event segment time must be finite with positive duration")
        for index in np.flatnonzero(usable):
            z0 = float(start[index, 2])
            z1 = float(end[index, 2])
            vertical_velocity = 0.5 * float(velocity_start[index, 2] + velocity_end[index, 2])
            contact_fraction = None
            if (not state["contacted"][index] and z0 > self.plane_z and z1 <= self.plane_z
                    and vertical_velocity < 0.0):
                contact_fraction = _crossing_fraction(z0, z1, self.plane_z)
                state["contact_time"][index] = segment_time + contact_fraction * dt
                state["contacted"][index] = True
            if (state["contacted"][index] and not state["upward"][index]
                    and z0 <= self.plane_z and z1 > self.plane_z and vertical_velocity > 0.0):
                fraction = _crossing_fraction(z0, z1, self.plane_z)
                state["upward_time"][index] = segment_time + fraction * dt
                state["upward"][index] = True
            if (state["upward"][index] and not state["returned"][index]
                    and z0 > self.plane_z and z1 <= self.plane_z and vertical_velocity < 0.0):
                fraction = _crossing_fraction(z0, z1, self.plane_z)
                state["return_time"][index] = segment_time + fraction * dt
                state["returned"][index] = True
            interval = _segment_box_interval(start[index], end[index], self.destination_low, self.destination_size)
            if interval is not None and state["contacted"][index]:
                lower, upper = interval
                if contact_fraction is not None:
                    lower = max(lower, contact_fraction)
                if upper > lower:
                    state["residence"][index] += (upper - lower) * dt
        return state

    def update(self, start, end, velocity_start, velocity_end, segment_time, dt, usable=None):
        """Convenience API for a standalone diagnostic observer."""
        if usable is None:
            usable = np.ones(self.count, dtype=bool)
        self.advance(self._standalone_state_data, start, end, velocity_start, velocity_end, segment_time, dt, usable)
        return self._standalone_state_data

    @property
    def _standalone_state_data(self):
        if not hasattr(self, "_event_standalone_state"):
            self._event_standalone_state = self.initial_state()
        return self._event_standalone_state


def _f4_status(state):
    status = np.zeros(len(state["reliable"]), dtype=np.int8)
    status[state["contacted"]] = 1
    status[state["upward"]] = 2
    status[state["returned"]] = 3
    status[~state["reliable"]] = 4
    return status


def _f4_initial_state(initial, frames, walls, neighbours, error_estimator, tracker):
    field = frames.field(0, 0.0)
    _, support_distance, support_ok, _ = field.sample(
        initial, walls, neighbours=neighbours, regularization=REGULARIZATION_M,
        error_estimator=error_estimator, return_diagnostics=True,
    )
    support_ok &= np.isfinite(initial).all(axis=1) & (support_distance <= MAXIMUM_SUPPORT_DISTANCE_M)
    state = {
        "position": np.array(initial, copy=True),
        "reliable": support_ok.astype(bool),
    }
    state.update(tracker.initial_state())
    return state


def _f4_advance_state(state, tracker, field0, field1, walls, segment_time, dt, neighbours, error_estimator):
    q = state["position"]
    active = state["reliable"]
    v0, d0, g0 = field0.sample(
        q, walls, neighbours=neighbours, regularization=REGULARIZATION_M,
        error_estimator=error_estimator,
    )
    predictor = q + np.nan_to_num(v0, nan=0.0, posinf=0.0, neginf=0.0) * dt
    v1, d1, g1 = field1.sample(
        predictor, walls, neighbours=neighbours, regularization=REGULARIZATION_M,
        error_estimator=error_estimator,
    )
    candidate = q + 0.5 * np.nan_to_num(v0 + v1, nan=0.0, posinf=0.0, neginf=0.0) * dt
    blocked = spacetime_swept_wall_blocked(q, candidate, walls, walls)
    usable = (
        active & g0 & g1 & ~blocked
        & np.isfinite(v0).all(axis=1) & np.isfinite(v1).all(axis=1)
        & (np.maximum(d0, d1) <= MAXIMUM_SUPPORT_DISTANCE_M)
    )
    tracker.advance(state, q, candidate, v0, v1, segment_time, dt, usable)
    state["position"] = np.where(usable[:, None], candidate, q)
    state["reliable"] = usable
    return state


def _f4_checkpoint_write(output, binding, frame, state):
    npz_path, manifest_path = _checkpoint_paths(output)
    temporary = npz_path.with_name(npz_path.name + ".partial.npz")
    np.savez_compressed(temporary, **{name: np.asarray(state[name]) for name in F4_CHECKPOINT_FIELDS})
    os.replace(temporary, npz_path)
    record = {
        "schema": F4_CHECKPOINT_SCHEMA,
        "binding_sha256": hashlib.sha256(binding.encode()).hexdigest(),
        "committed": int(frame),
        "state_sha256": digest(npz_path),
        "fields": list(F4_CHECKPOINT_FIELDS),
    }
    _atomic_json(manifest_path, record)


def _f4_checkpoint_read(output, binding):
    npz_path, manifest_path = _checkpoint_paths(output)
    if not manifest_path.exists() or not npz_path.exists():
        return None
    try:
        record = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("F4 restart checkpoint manifest is not valid JSON") from error
    if (record.get("schema") != F4_CHECKPOINT_SCHEMA
            or record.get("binding_sha256") != hashlib.sha256(binding.encode()).hexdigest()):
        raise ValueError("F4 restart checkpoint provenance mismatch")
    if record.get("fields") != list(F4_CHECKPOINT_FIELDS) or digest(npz_path) != record.get("state_sha256"):
        raise ValueError("F4 restart checkpoint is incomplete or changed")
    committed = record.get("committed")
    if isinstance(committed, (bool, np.bool_)) or not isinstance(committed, (int, np.integer)) or int(committed) < 0:
        raise ValueError("F4 restart checkpoint committed frame is invalid")
    try:
        with np.load(npz_path, allow_pickle=False) as archive:
            if tuple(archive.files) != F4_CHECKPOINT_FIELDS:
                raise ValueError("F4 restart checkpoint fields are incomplete")
            state = {name: np.array(archive[name], copy=True) for name in F4_CHECKPOINT_FIELDS}
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("F4 restart checkpoint state is unreadable") from error
    _validate_checkpoint_state(state, F4_CHECKPOINT_FIELDS)
    return int(committed), state


def _f4_create_output(out, initial, weight, labels, tracer_ids, binding, definition, provider_role):
    n = len(initial)
    out.attrs["schema"] = F4_SCHEMA
    out.attrs["binding"] = binding
    out.attrs["committed"] = -1
    out.attrs["checkpoint_schema"] = F4_CHECKPOINT_SCHEMA
    out.attrs["provider_role"] = provider_role
    out.attrs["source_definition"] = json.dumps(definition, sort_keys=True)
    out.attrs["event_definition"] = json.dumps(definition["event_definition"], sort_keys=True)
    out.attrs["seed_identity"] = "independent_geometric_seed; no native particle id"
    out.create_dataset("initial_position", data=initial)
    out.create_dataset("weight", data=weight)
    if labels.dtype.kind in "OUS":
        data = np.asarray([str(_json_scalar(item)) for item in labels], dtype=h5py.string_dtype("utf-8"))
    else:
        data = labels
    out.create_dataset("source_label", data=data)
    out.create_dataset("tracer_id", data=np.asarray(tracer_ids, dtype=h5py.string_dtype("utf-8")))
    out.create_dataset("source_membership", data=f4_source_membership(initial, definition["q"]))
    out.create_dataset("destination_membership", data=f4_destination_membership(initial))
    for name, shape, dtype in (
        ("time", (), "f8"), ("position", (n, 3), "f8"), ("reliable", (n,), "?"),
        ("contact_time", (n,), "f8"), ("upward_time", (n,), "f8"),
        ("return_time", (n,), "f8"), ("residence", (n,), "f8"),
        ("contacted", (n,), "?"), ("upward", (n,), "?"),
        ("returned", (n,), "?"), ("event_status", (n,), "i1"),
    ):
        out.create_dataset(name, shape=(0,) + shape, maxshape=(None,) + shape,
                           dtype=dtype, chunks=(1,) + shape)
    out.flush()


def _f4_validate_resume_output(out, initial, weight, labels, tracer_ids, binding):
    if out.attrs.get("schema") != F4_SCHEMA or out.attrs.get("binding") != binding:
        raise ValueError("F4 restart provenance mismatch")
    for name in ("initial_position", "weight", "source_label", "tracer_id", "source_membership", "destination_membership") + F4_HISTORY_FIELDS + ("event_status",):
        if name not in out:
            raise ValueError(f"F4 restart output missing dataset {name}")
    if not np.array_equal(out["initial_position"][:], initial) or not np.array_equal(out["weight"][:], weight):
        raise ValueError("F4 restart seed metadata mismatch")
    stored_labels = out["source_label"].asstr()[:] if out["source_label"].dtype.kind in "OSU" else out["source_label"][:]
    expected_labels = np.asarray([str(_json_scalar(item)) for item in labels]) if labels.dtype.kind in "OUS" else labels
    if not np.array_equal(stored_labels, expected_labels):
        raise ValueError("F4 restart source definition mismatch")
    stored_ids = np.asarray(out["tracer_id"].asstr()[:])
    if _hash_array(stored_ids) != _hash_array(tracer_ids):
        raise ValueError("F4 restart tracer identity mismatch")
    try:
        binding_object = json.loads(binding)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("F4 restart binding is not valid JSON") from error
    if not isinstance(binding_object, dict):
        raise ValueError("F4 restart binding must be an object")
    definition = binding_object.get("f4_definition")
    if not isinstance(definition, dict) or "q" not in definition:
        raise ValueError("F4 restart binding has no source definition")
    expected_source = f4_source_membership(initial, definition["q"])
    expected_destination = f4_destination_membership(initial)
    for name, expected in (("source_membership", expected_source),
                           ("destination_membership", expected_destination)):
        stored = np.asarray(out[name][:])
        if stored.shape != expected.shape or stored.dtype.kind != "b":
            raise ValueError("F4 restart membership metadata has an invalid shape or dtype")
        if not np.array_equal(stored, expected):
            raise ValueError("F4 restart membership metadata disagrees with bound geometry")
    return int(out.attrs.get("committed", -1))


def _f4_append_frame(out, frame, frames, state):
    target = int(frame) + 1
    for name in F4_HISTORY_FIELDS + ("event_status",):
        out[name].resize(target, axis=0)
    values = {"time": float(frames.times[frame]), **{name: state[name] for name in F4_CHECKPOINT_FIELDS},
              "event_status": _f4_status(state)}
    for name, value in values.items():
        out[name][frame] = value
    out.flush()
    out.attrs["committed"] = int(frame)
    out.flush()


def _f4_state_from_h5(out, frame):
    return {name: np.array(out[name][frame], copy=True) for name in F4_CHECKPOINT_FIELDS}


def f4_event_summary(out):
    """Summarize F4 events, CDFs, closure, unknown mass, and path coverage."""
    committed = int(out.attrs["committed"])
    if committed < 0:
        raise ValueError("F4 output has no committed frame")
    weight = np.asarray(out["weight"][:], dtype=np.float64)
    labels = np.asarray(out["source_label"][:])
    if labels.dtype.kind == "S":
        labels = labels.astype(str)
    reliable = np.asarray(out["reliable"][committed], dtype=bool)
    position = np.asarray(out["position"][committed], dtype=np.float64)
    destination = f4_destination_membership(position)
    contact = np.asarray(out["contacted"][committed], dtype=bool)
    upward = np.asarray(out["upward"][committed], dtype=bool)
    returned = np.asarray(out["returned"][committed], dtype=bool)
    contact_time = np.asarray(out["contact_time"][committed], dtype=np.float64)
    upward_time = np.asarray(out["upward_time"][committed], dtype=np.float64)
    return_time = np.asarray(out["return_time"][committed], dtype=np.float64)
    residence = np.asarray(out["residence"][committed], dtype=np.float64)
    final_time = float(out["time"][committed])
    total_mass = float(weight.sum())
    rows = []
    for source in np.unique(labels):
        select = labels == source
        source_mass = float(weight[select].sum())
        if source_mass <= 0:
            continue
        unknown = select & ~reliable
        destination_mass = select & reliable & destination
        outside_mass = select & reliable & ~destination
        right_censored = select & reliable & (~returned | ((final_time - return_time) < F4_GRAVITY_TIME_S))
        contact_cdf = weighted_cdf(contact_time, weight, mask=select & reliable & np.isfinite(contact_time), denominator=source_mass)
        upward_cdf = weighted_cdf(upward_time, weight, mask=select & reliable & np.isfinite(upward_time), denominator=source_mass)
        return_cdf = weighted_cdf(return_time, weight, mask=select & reliable & np.isfinite(return_time), denominator=source_mass)
        residence_cdf = weighted_cdf(residence, weight, mask=select & reliable & contact & np.isfinite(residence), denominator=source_mass)
        unknown_fraction = _weighted_fraction(weight, unknown, source_mass)
        destination_fraction = _weighted_fraction(weight, destination_mass, source_mass)
        outside_fraction = _weighted_fraction(weight, outside_mass, source_mass)
        closure = destination_fraction + outside_fraction + unknown_fraction
        rows.append({
            "source": _json_scalar(source),
            "initial_mass_fraction": source_mass / total_mass if total_mass else 0.0,
            "destination_mass_fraction": destination_fraction,
            "outside_destination_mass_fraction": outside_fraction,
            "unknown_fraction": unknown_fraction,
            "unknown_fraction_max": unknown_fraction,
            "unknown_fraction_monotone": True,
            "final_unknown_fraction": unknown_fraction,
            "reliable_path_coverage": _weighted_fraction(weight, select & reliable, source_mass),
            "mass_closure_fraction": closure,
            "mass_closure_error": closure - 1.0,
            "contact_fraction": _weighted_fraction(weight, select & reliable & contact, source_mass),
            "upward_fraction": _weighted_fraction(weight, select & reliable & upward, source_mass),
            "return_fraction": _weighted_fraction(weight, select & reliable & returned, source_mass),
            "contact_cdf": contact_cdf,
            "upward_cdf": upward_cdf,
            "return_cdf": return_cdf,
            "residence_cdf": residence_cdf,
            "residence_mean_s": float(np.sum(weight[select] * residence[select]) / source_mass),
            "right_censored_fraction": _weighted_fraction(weight, right_censored, source_mass),
        })
    complete = bool(reliable.any() and not np.any(reliable & (~returned | ((final_time - return_time) < F4_GRAVITY_TIME_S))))
    definition = json.loads(out.attrs.get("source_definition", json.dumps(f4_resting_pool_definition())))
    return {
        "task": "F4 continuous drop source to resting-pool contact/upward/return/residence",
        "scope_id": F4_SCOPE_ID,
        "source_definition": definition,
        "by_source": rows,
        "mass_closed": all(abs(row["mass_closure_error"]) <= 1e-12 for row in rows),
        "unknown_gate_pass": all(row["unknown_fraction_max"] <= 0.01 for row in rows),
        "unknown_fraction_monotone": True,
        "common_reliable_path_coverage": float(weight[reliable].sum() / total_mass) if total_mass else 0.0,
        "event_window_complete": complete,
        "event_window_status": "complete" if complete else "right_censored_or_unresolved",
        "committed_frame": committed,
        "committed_time_s": final_time,
    }


def _f4_provider(source, provider):
    if provider is not None:
        return provider, False
    if source is None:
        raise ValueError("F4 source is required when provider is not supplied")
    with h5py.File(source, "r") as handle:
        is_state = _h5_attr_text(handle.attrs.get("state_schema", "")) == StateH5Provider.state_schema
    if is_state:
        return StateH5Provider(source), True
    return ReferenceFrames(source, fluid_type=3), True


def trace_f4_resting_pool(
    source,
    output,
    initial=None,
    *,
    q=0.5,
    seeds=512,
    walls=None,
    substeps=2,
    stop_after=None,
    resume=False,
    weights=None,
    source_labels=None,
    tracer_ids=None,
    provider=None,
    kill_after=None,
    neighbour_variant="baseline24",
    dp_m=None,
):
    """Trace F4 seeds and emit continuous resting-pool event datasets."""
    q = _f4_q(q)
    substeps = _positive_integer(substeps, "substeps")
    neighbour_variant, backend, neighbours, error_estimator = _neighbour_variant(neighbour_variant)
    if initial is None:
        initial = seeds_f4(seeds, q)
    initial = _validate_seeds(initial)
    if source_labels is None:
        source_labels = np.ones(len(initial), dtype=np.int8)
    initial, weight, labels, tracer_ids = _prepare_seed_metadata(initial, weights, source_labels, tracer_ids)
    if walls is None:
        walls = f4_walls()
    walls = _validate_walls(walls)
    if not np.isfinite(initial).all() or np.any(~f4_source_membership(initial, q)):
        raise ValueError("F4 material seeds must be inside the continuous source drop box")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if kill_after is not None:
        if isinstance(kill_after, bool) or not isinstance(kill_after, (int, np.integer)) or kill_after < 0:
            raise ValueError("kill_after must be a nonnegative frame index")
        kill_after = int(kill_after)
    owns_provider = provider is None
    frames, owns_provider = _f4_provider(source, provider)
    source_hash = getattr(frames, "source_sha256", None) or (digest(source) if source is not None else "provider-supplied")
    # Resolution is metadata for the material overlay, but it must still be
    # bound to the exact native source definition for provenance.  The
    # trajectory itself remains the sole numerical field source.
    definition = f4_resting_pool_definition(q, dp_m=dp_m)
    definition["q"] = q
    source_semantics = "predicted_state_h5" if getattr(frames, "provider_role", "reference") == "predicted" else "reference_native_saved_frames"
    binding = {
        "schema": F4_SCHEMA,
        "scope_id": F4_SCOPE_ID,
        "revision_id": F4_REVISION_ID,
        "recipe_id": F4_RECIPE_ID,
        "source_sha256": source_hash,
        "code_sha256": digest(Path(__file__)),
        "neighbor_code_sha256": digest(Path(__file__).with_name("f3_material_neighbors.py")),
        "passive_code_sha256": digest(Path(__file__).with_name("passive_tracers.py")),
        "initial_sha256": _hash_array(initial),
        "weight_sha256": _hash_array(weight),
        "source_label_sha256": _hash_array(labels),
        "tracer_id_sha256": _hash_array(tracer_ids),
        "walls_sha256": _hash_array(walls),
        "f4_definition": definition,
        "substeps": substeps,
        "source_semantics": source_semantics,
        "provider_role": getattr(frames, "provider_role", "reference"),
        "backend": backend,
        "neighbour_variant": neighbour_variant,
        "neighbours": neighbours,
        "error_estimator": error_estimator,
        "regularization_m": REGULARIZATION_M,
        "maximum_support_distance_m": MAXIMUM_SUPPORT_DISTANCE_M,
        "support_gate": GATE,
    }
    binding_text = _canonical(binding)
    started = time.monotonic()
    npz_path, manifest_path = _checkpoint_paths(output)
    result = None
    try:
        if resume:
            if not output.exists():
                raise FileNotFoundError(f"cannot resume missing output {output}")
            mode = "r+"
        else:
            if output.exists():
                raise FileExistsError(f"output already exists: {output}")
            if npz_path.exists() or manifest_path.exists():
                raise FileExistsError(f"stale checkpoint exists for missing output: {npz_path}")
            mode = "x"
        with h5py.File(output, mode) as out:
            tracker = F4EventTracker(len(initial), definition=definition)
            if resume:
                _f4_validate_resume_output(out, initial, weight, labels, tracer_ids, binding_text)
                checkpoint = _f4_checkpoint_read(output, binding_text)
                if checkpoint is None:
                    committed = int(out.attrs.get("committed", -1))
                    if committed < 0:
                        raise ValueError("F4 restart has no complete checkpoint")
                    state = _f4_state_from_h5(out, committed)
                else:
                    committed, state = checkpoint
                if committed < 0 or committed >= len(frames.times):
                    raise ValueError("F4 restart checkpoint is outside source frame range")
                for name in F4_HISTORY_FIELDS + ("event_status",):
                    out[name].resize(committed + 1, axis=0)
                _f4_append_frame(out, committed, frames, state)
            else:
                _f4_create_output(out, initial, weight, labels, tracer_ids, binding_text, definition, getattr(frames, "provider_role", "reference"))
                state = _f4_initial_state(initial, frames, walls, neighbours, error_estimator, tracker)
                _f4_checkpoint_write(output, binding_text, 0, state)
                if kill_after == 0:
                    os.kill(os.getpid(), signal.SIGKILL)
                _f4_append_frame(out, 0, frames, state)
                committed = 0
            if stop_after is not None and int(stop_after) < 0:
                raise ValueError("stop_after must be nonnegative")
            end = len(frames.times) - 1 if stop_after is None else min(int(stop_after), len(frames.times) - 1)
            if end < committed:
                end = committed
            for frame_index in range(committed, end):
                dt = (float(frames.times[frame_index + 1]) - float(frames.times[frame_index])) / substeps
                field0 = frames.field(frame_index, 0.0)
                for substep in range(substeps):
                    field1 = frames.field(frame_index, (substep + 1) / substeps)
                    _f4_advance_state(
                        state, tracker, field0, field1, walls,
                        float(frames.times[frame_index]) + substep * dt,
                        dt, neighbours, error_estimator,
                    )
                    field0 = field1
                next_frame = frame_index + 1
                _f4_checkpoint_write(output, binding_text, next_frame, state)
                if kill_after == next_frame:
                    os.kill(os.getpid(), signal.SIGKILL)
                _f4_append_frame(out, next_frame, frames, state)
                committed = next_frame
            result = f4_event_summary(out)
            result.update(
                status="completed" if end == len(frames.times) - 1 else "partial",
                qualification_claim="none",
                material_reliability="not_established",
                qualified_T2_macro=False,
                qualified_T2_path=False,
                elapsed_seconds=time.monotonic() - started,
                max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                committed_frame=int(out.attrs["committed"]),
                native_frame_count=len(frames.times),
                binding=binding,
                checkpoint_manifest=str(manifest_path),
            )
            out.attrs["result"] = json.dumps(result, sort_keys=True, allow_nan=False)
    finally:
        if owns_provider:
            frames.close()
    target = output.with_suffix(".json")
    temporary = target.with_suffix(".json.partial")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, target)
    return result


trace_f4 = trace_f4_resting_pool


def common_path_metrics(a, b, valid_a, valid_b, weights=None):
    """Measure common reliable path mass and weighted path disagreement.

    For endpoint arrays the function preserves the original scalar behavior.
    For ``[frames,seeds,3]`` trajectories a seed belongs to the common path
    only when both trajectories are reliable at every saved frame.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    valid_a = np.asarray(valid_a, dtype=bool)
    valid_b = np.asarray(valid_b, dtype=bool)
    if a.shape != b.shape or a.ndim < 2 or a.shape[-1] != 3:
        raise ValueError("path arrays must have matching shape [...,3]")
    if valid_a.shape != valid_b.shape:
        raise ValueError("valid path masks must have matching shapes")
    if a.ndim == 2:
        if valid_a.shape != (len(a),):
            raise ValueError("endpoint valid mask must have shape [N]")
        path_common, path_union = valid_a & valid_b, valid_a | valid_b
        error = np.linalg.norm(a - b, axis=-1)
        samples = error
    else:
        if valid_a.shape != a.shape[:-1]:
            raise ValueError("trajectory valid mask must have shape [frames,N]")
        path_common = valid_a.all(axis=0) & valid_b.all(axis=0)
        path_union = valid_a.any(axis=0) | valid_b.any(axis=0)
        error = np.linalg.norm(a - b, axis=-1)
        samples = np.sqrt(np.mean(error**2, axis=0))
    n = samples.shape[0]
    if weights is None:
        weights = np.full(n, 1.0 / max(n, 1), dtype=np.float64)
    else:
        weights = np.asarray(weights, dtype=np.float64)
        if weights.shape != (n,) or not np.isfinite(weights).all() or np.any(weights < 0):
            raise ValueError("weights must have shape [N] and be nonnegative finite")
    total = float(weights.sum())
    common_mass = float(weights[path_common].sum())
    union_mass = float(weights[path_union].sum())
    result = {
        "common_mass_fraction": common_mass / total if total else 0.0,
        "union_mass_fraction": union_mass / total if total else 0.0,
        "common_reliable_path_coverage": common_mass / total if total else 0.0,
        "common_seed_count": int(path_common.sum()),
        "union_seed_count": int(path_union.sum()),
    }
    if common_mass == 0:
        return dict(result, rms=None, p95=None, maximum=None)
    common_error = samples[path_common]
    common_weight = weights[path_common]
    order = np.argsort(common_error, kind="mergesort")
    sorted_error = common_error[order]
    cumulative = np.cumsum(common_weight[order]) / common_mass
    result.update(
        rms=float(np.sqrt(np.sum(common_weight * common_error**2) / common_mass)),
        p95=float(sorted_error[min(np.searchsorted(cumulative, 0.95, side="left"), len(sorted_error) - 1)]),
        maximum=float(sorted_error[-1]),
    )
    return result


def f4_matrix(scope=F4_SCOPE_ID):
    """Return the registered fifteen-cell F4 resting-pool overlay matrix."""
    rows = []
    index = 0
    for q, dps in ((0.0, (0.01, 0.0075, 0.005)),
                   (0.5, (0.01, 0.0075, 0.005)),
                   (1.0, (0.01, 0.0075, 0.005)),
                   (0.25, (0.0075, 0.005)),
                   (0.75, (0.0075, 0.005))):
        for dp in dps:
            q_text = f"{q:.8f}".replace(".", "p")
            dp_text = f"{dp:.12f}".replace(".", "p")
            rows.append({
                "scope": scope, "scope_id": F4_SCOPE_ID, "index": index,
                "q": q, "dp_m": dp, "design_cell": "spatial",
                "case_id": f"RESTING_CORE_F4_mdbc_native_q{q_text}_dp{dp_text}_qualification",
                "prepared": f"campaigns/core-v1/cfd/prepared/F4_resting_pool_qualification_v2/cell-{index:02d}/prepared.json",
                "job_id": f"f4-h1-qualification-cell-{index:02d}",
                "solve_required": True, "material_backend": NEIGHBOUR_BACKEND,
                "neighbour_variant": "baseline24", "seeds": 512,
                "matrix_stage": "spatial",
            })
            index += 1
    for q, design_cell, suffix in ((0.5, "internal_time", "internal_time"), (0.5, "native_output", "native_output")):
        q_text = f"{q:.8f}".replace(".", "p")
        dp_text = f"{0.0075:.12f}".replace(".", "p")
        rows.append({
            "scope": scope, "scope_id": F4_SCOPE_ID, "index": index,
            "q": q, "dp_m": 0.0075, "design_cell": design_cell,
            "case_id": f"RESTING_CORE_F4_mdbc_native_q{q_text}_dp{dp_text}_qualification_{suffix}",
            "prepared": f"campaigns/core-v1/cfd/prepared/F4_resting_pool_qualification_v2/cell-{index:02d}/prepared.json",
            "job_id": f"f4-h1-qualification-cell-{index:02d}",
            "solve_required": True, "material_backend": NEIGHBOUR_BACKEND,
            "neighbour_variant": "baseline24", "seeds": 512,
            "matrix_stage": design_cell,
        })
        index += 1
    return rows


f4_scope_matrix = f4_matrix


def matrix(scope, *, subset=None):
    """Return the frozen 33-row material matrix for one scalar scope.

    The first 24 rows are the spatial/substep matrix, the next four compare
    native-dense and matched decimation at center/end point, and the final
    five are 4096-seed density checks.  ``subset=15`` is the preflight slice;
    it is a row selection only and never substitutes an interpolated result
    for the native dense solve.
    """
    if scope in ("F4", F4_SCOPE_ID):
        rows = f4_matrix(scope)
        if subset is None or subset in (15, "15", "preflight"):
            return rows
        raise ValueError("F4 matrix has one registered fifteen-cell scope")
    rows = []
    for q, dps, role in (
        (0.5, ("coarse", "production", "fine"), "center"),
        (1.0, ("coarse", "production", "fine"), "hard_endpoint"),
        (0.0, ("production", "fine"), "endpoint"),
        (0.25, ("production", "fine"), "interior"),
        (0.75, ("production", "fine"), "interior"),
    ):
        for dp in dps:
            for substeps in (2, 4):
                rows.append(
                    dict(scope=scope, q=q, q_role=role, dp=dp, substeps=substeps, seeds=512, cadence="native", solve_required=True, matrix_stage="resolution_substep")
                )
    for q, role in ((0.5, "center"), (1.0, "hard_endpoint")):
        for cadence in ("native_dense", "matched_decimation"):
            rows.append(
                dict(
                    scope=scope,
                    q=q,
                    q_role=role,
                    dp="production",
                    substeps=4,
                    seeds=512,
                    cadence=cadence,
                    dense_saved_interval_s=0.002,
                    decimate_from="native_dense" if cadence == "matched_decimation" else None,
                    solve_required=True,
                    interpolation_substitution=False,
                    matrix_stage="cadence",
                )
            )
    for q in (0.0, 0.25, 0.5, 0.75, 1.0):
        rows.append(
            dict(scope=scope, q=q, q_role="density_check", dp="production", substeps=4, seeds=4096, cadence="native", solve_required=True, matrix_stage="seed_density")
        )
    for i, row in enumerate(rows):
        row["configuration_id"] = f"{scope}-material-{i:02d}"
        row["matrix_index"] = i
    if subset is None:
        return rows
    if subset in (15, "15", "preflight"):
        # The fifteen-row preflight is a declared scientific subset: all
        # center/hard-endpoint resolution×substep rows, both center cadence
        # rows, and the center high-seed row.  It must not accidentally mean
        # ``rows[:15]`` because the latter would include three unrelated
        # interior q rows and omit the dense/decimated comparison.
        selected = [row for row in rows if row["matrix_stage"] == "resolution_substep" and row["q"] in (0.5, 1.0)]
        selected += [row for row in rows if row["matrix_stage"] == "cadence" and row["q"] == 0.5]
        selected += [row for row in rows if row["matrix_stage"] == "seed_density" and row["q"] == 0.5]
        if len(selected) != 15:
            raise RuntimeError("frozen material preflight subset is not fifteen rows")
        return selected
    raise ValueError("subset must be 15, '15', or 'preflight'")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--family", choices=("f3", "f4"), default="f3")
    parser.add_argument("--f4", dest="family", action="store_const", const="f4", help=argparse.SUPPRESS)
    parser.add_argument("--seeds", "--seed-count", dest="seeds", type=int, choices=[512, 4096], default=512)
    parser.add_argument("--q", type=float, default=0.5, help="F4 drop position in [0,1]")
    parser.add_argument("--dp-m", type=float, default=None, help="F4 native source resolution metadata for binding")
    parser.add_argument("--substeps", type=int, default=2)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--neighbour-variant",
        choices=tuple(NEIGHBOUR_VARIANTS),
        default="baseline24",
        help="registered backend variant; h2_k48 and h1_affine_bound are fixed research canaries",
    )
    parser.add_argument("--kill-after", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.family == "f4":
        result = trace_f4_resting_pool(
            args.source,
            args.output,
            seeds_f4(args.seeds, args.q),
            q=args.q,
            substeps=args.substeps,
            stop_after=args.stop_after,
            resume=args.resume,
            kill_after=args.kill_after,
            neighbour_variant=args.neighbour_variant,
            dp_m=args.dp_m,
        )
    else:
        result = trace(
            args.source,
            args.output,
            seeds_f3(args.seeds),
            f3_walls(),
            substeps=args.substeps,
            stop_after=args.stop_after,
            resume=args.resume,
            kill_after=args.kill_after,
            neighbour_variant=args.neighbour_variant,
        )
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
