"""Versioned, provider-free inputs and native-velocity particle updates.

These contracts describe numerical estimates, not material or experimental
truth. A predictor receives immutable arrays and prescribed inputs only; a
trajectory reader is deliberately absent from every prediction interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

import numpy as np

STATE_VERSION = "core.state.native_velocity.v1"
INPUT_VERSION = "core.inputs.v1"
PREDICTION_VERSION = "core.prediction.dual_increment.v1"
PRESCRIBED_GEOMETRY_VERSION = "core.prescribed_geometry.v1"
PRESCRIBED_ROTATION_VERSION = "core.prescribed_rotation.v1"
# DualSPHysics' arbitrary-axis MatrixRot convention has the opposite signed
# Rodrigues angle from Core's default right-handed axis convention.  Keep the
# native convention explicit in the public motion metadata.
DUALSPHYSICS_MVROTFILE_ROTATION_VERSION = "core.dualsphysics.mvrotfile.v1"
_PRESCRIBED_ROTATION_SIGNS = {
    PRESCRIBED_ROTATION_VERSION: 1.0,
    DUALSPHYSICS_MVROTFILE_ROTATION_VERSION: -1.0,
}

# KnownInputs is the only information boundary visible to a predictor.  Keep
# physical metadata such as ``reference_density_kgm3`` legal, but reject
# common aliases that could smuggle a future/reference particle state into the
# serialized contract.  The previous substring list caught
# ``future_fluid_velocity`` while allowing the equally dangerous generic
# ``future_state`` and ``future_velocity`` keys.
_FORBIDDEN_CAUSAL_KEY_EXACT = frozenset({
    "future", "state", "reference", "target",
    "future_state", "future_position", "future_velocity", "future_acceleration",
    "future_density", "future_mass", "future_reference", "future_trajectory",
    "reference_state", "reference_position", "reference_velocity",
    "reference_acceleration", "target_state", "target_position", "target_velocity",
    "target_acceleration", "trajectory", "trajectory_path", "trajectory_h5",
    "trajectory_reader",
})


def _forbidden_causal_key(normalized: str) -> bool:
    """Return whether a metadata key can carry a future/reference state.

    Prefix checks cover names such as ``future_state_position`` without
    rejecting the legitimate material property ``reference_density_kgm3``.
    ``_json_value`` recurses through nested mappings, so the same boundary
    applies regardless of where a caller tries to hide the field.
    """
    compact = normalized.replace("_", "")
    return bool(
        normalized in _FORBIDDEN_CAUSAL_KEY_EXACT
        or compact in {"futurestate", "futureposition", "futurevelocity",
                       "futureacceleration", "referencestate", "targetstate"}
        or normalized.startswith((
            "future_state_", "future_fluid_", "future_body_",
            "reference_state_", "target_state_", "trajectory_",
        ))
    )


def _array(value, *, dtype=None):
    result = np.array(value, dtype=dtype, copy=True)
    result.setflags(write=False)
    return result


def _json_value(value):
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("metadata keys must be strings")
            normalized = key.lower().replace("-", "_")
            if _forbidden_causal_key(normalized) or any(term in normalized for term in ("reader", "provider")):
                raise ValueError("future/reference/provider state is forbidden in known inputs")
            result[key] = _json_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)) and math.isfinite(value):
        return float(value)
    raise ValueError("known metadata must contain finite JSON values, never callable providers")


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class State:
    time_s: float
    position: np.ndarray
    velocity: np.ndarray
    particle_id: np.ndarray
    particle_zone: np.ndarray
    mass: np.ndarray
    valid: np.ndarray

    def __post_init__(self):
        for name in ("position", "velocity", "mass"):
            object.__setattr__(self, name, _array(getattr(self, name), dtype=np.float64))
        for name in ("particle_id", "particle_zone"):
            original = np.asarray(getattr(self, name))
            if original.dtype.kind not in "iu":
                raise ValueError("particle identities must be integers")
            object.__setattr__(self, name, _array(original, dtype=np.int64))
        original = np.asarray(self.valid)
        if original.dtype.kind not in "biu" or not np.isin(original, [0, 1]).all():
            raise ValueError("valid must be an explicit boolean mask")
        object.__setattr__(self, "valid", _array(original, dtype=bool))
        object.__setattr__(self, "time_s", float(self.time_s))
        validate_state(self)

    @property
    def count(self):
        return len(self.particle_id)

    @property
    def time(self):
        """Public contract alias for the saved state time in seconds."""
        return self.time_s

    @property
    def velocity_native_estimate(self):
        """The saved native numerical velocity, kept separate from displacement."""
        return self.velocity

    def select(self, indices):
        return State(self.time_s, self.position[indices], self.velocity[indices],
                     self.particle_id[indices], self.particle_zone[indices],
                     self.mass[indices], self.valid[indices])


def validate_state(state: State, *, require_complete=False):
    if not isinstance(state, State) or not math.isfinite(state.time_s):
        raise ValueError("State with a finite time is required")
    n = len(state.particle_id)
    if n == 0 or state.position.shape != (n, 3) or state.velocity.shape != (n, 3):
        raise ValueError("state position/velocity must preserve [N,3]")
    if any(getattr(state, name).shape != (n,) for name in ("particle_id", "particle_zone", "mass", "valid")):
        raise ValueError("identity, mass and validity axes must agree")
    if len(np.unique(np.column_stack((state.particle_zone, state.particle_id)), axis=0)) != n:
        raise ValueError("composite particle identities must be unique")
    active = state.valid
    if not active.any() or (require_complete and not active.all()):
        raise ValueError("complete active state required; survivor filtering is forbidden")
    if (not np.isfinite(state.position[active]).all() or not np.isfinite(state.velocity[active]).all()
            or not np.isfinite(state.mass[active]).all() or np.any(state.mass[active] <= 0)):
        raise ValueError("active native state must be finite with positive mass")
    return state


@dataclass(frozen=True)
class FiniteGeometry:
    triangles: np.ndarray
    component_id: np.ndarray
    body_id: np.ndarray
    wall_velocity: np.ndarray
    coordinate_frame: str
    version: str = "core.finite_geometry.v1"
    # Internal, immutable rigid-motion context used only when this snapshot
    # came from PrescribedGeometry.at().  It is intentionally omitted from
    # as_dict(): the public known-input contract serializes the declared
    # motion schedule, never a per-step provider or inferred state.
    rigid_axis_point: object = field(default=None, repr=False, compare=False)
    rigid_angular_velocity: object = field(default=None, repr=False, compare=False)
    rigid_mask: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        for name in ("triangles", "wall_velocity"):
            object.__setattr__(self, name, _array(getattr(self, name), dtype=np.float64))
        for name in ("component_id", "body_id"):
            object.__setattr__(self, name, _array(getattr(self, name), dtype=np.int64))
        for name in ("rigid_axis_point", "rigid_angular_velocity"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _array(value, dtype=np.float64))
        if self.rigid_mask is not None:
            object.__setattr__(self, "rigid_mask", _array(self.rigid_mask, dtype=bool))
        self.validate()

    def validate(self):
        m = len(self.triangles)
        if (self.version != "core.finite_geometry.v1" or not self.coordinate_frame
                or self.triangles.shape != (m, 3, 3) or self.wall_velocity.shape != (m, 3)
                or self.component_id.shape != (m,) or self.body_id.shape != (m,)):
            raise ValueError("invalid finite triangle geometry contract")
        if not np.isfinite(self.triangles).all() or not np.isfinite(self.wall_velocity).all():
            raise ValueError("nonfinite geometry")
        if (self.rigid_axis_point is None) != (self.rigid_angular_velocity is None):
            raise ValueError("rigid geometry context requires both axis point and angular velocity")
        if self.rigid_axis_point is not None:
            if (self.rigid_axis_point.shape != (3,) or self.rigid_angular_velocity.shape != (3,)
                    or not np.isfinite(self.rigid_axis_point).all()
                    or not np.isfinite(self.rigid_angular_velocity).all()):
                raise ValueError("invalid rigid geometry context")
            if self.rigid_mask is not None and self.rigid_mask.shape != (m,):
                raise ValueError("rigid geometry mask must preserve the triangle axis")
        elif self.rigid_mask is not None:
            raise ValueError("rigid geometry mask requires rigid motion context")
        if m and np.any(np.linalg.norm(np.cross(self.triangles[:, 1] - self.triangles[:, 0],
                                               self.triangles[:, 2] - self.triangles[:, 0]), axis=1) <= 1e-15):
            raise ValueError("degenerate finite triangle")
        return self

    def as_dict(self):
        return {"version": self.version, "coordinate_frame": self.coordinate_frame,
                **{name: getattr(self, name).tolist() for name in
                   ("triangles", "component_id", "body_id", "wall_velocity")}}

    def wall_velocity_at(self, surface_points, triangle_index):
        """Return wall speed at exact surface points on one triangle.

        Static faces retain their declared per-triangle velocity.  A dynamic
        rigid snapshot evaluates the prescribed angular velocity at each
        closest point, so velocity varies with radius instead of being frozen
        to the triangle centroid.
        """
        points = np.asarray(surface_points, dtype=np.float64)
        if points.shape[-1] != 3:
            raise ValueError("surface points must end in a three-vector")
        if self.rigid_axis_point is None or (self.rigid_mask is not None
                                             and not bool(self.rigid_mask[int(triangle_index)])):
            return np.broadcast_to(self.wall_velocity[int(triangle_index)], points.shape).copy()
        omega = np.broadcast_to(self.rigid_angular_velocity, points.shape)
        return np.cross(omega, points - self.rigid_axis_point)

    @classmethod
    def from_wall_spec(cls, wall_spec, *, coordinate_frame):
        """Triangulate declared finite box faces; an open top has no triangle."""
        if wall_spec.get("obstacles"):
            raise ValueError("obstacles require explicit triangles; box proxy is forbidden")
        bounds = wall_spec["container_interior"]
        low = np.array([bounds[k] for k in ("xmin", "ymin", "zmin")], float)
        high = np.array([bounds[k] for k in ("xmax", "ymax", "zmax")], float)
        if not np.isfinite([low, high]).all() or np.any(high <= low):
            raise ValueError("invalid finite wall extents")
        axes = {"left": (0, 0), "right": (0, 1), "front": (1, 0),
                "back": (1, 1), "bottom": (2, 0), "top": (2, 1)}
        closed, opened = set(wall_spec["closed_faces"]), set(wall_spec.get("open_faces", ()))
        if closed & opened or not closed | opened <= set(axes):
            raise ValueError("contradictory solid/open faces")
        triangles, components = [], []
        for component, name in enumerate(axes):
            if name not in closed:
                continue
            axis, side = axes[name]
            other = [i for i in range(3) if i != axis]
            vertices = []
            for u, v in ((0, 0), (1, 0), (1, 1), (0, 1)):
                point = low.copy(); point[axis] = (low if side == 0 else high)[axis]
                point[other[0]] = (low if u == 0 else high)[other[0]]
                point[other[1]] = (low if v == 0 else high)[other[1]]
                vertices.append(point)
            for ids in ((0, 1, 2), (0, 2, 3)):
                triangle = np.array([vertices[i] for i in ids])
                normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
                if normal[axis] * (1 if side == 0 else -1) < 0:
                    triangle = triangle[[0, 2, 1]]
                triangles.append(triangle); components.append(component)
        t = np.array(triangles, dtype=float).reshape(-1, 3, 3)
        return cls(t, np.array(components, dtype=np.int64), np.zeros(len(t), dtype=np.int64),
                   np.zeros((len(t), 3)), coordinate_frame)


@dataclass(frozen=True)
class PrescribedGeometry:
    """Finite geometry whose rigid pose is supplied by a declared schedule.

    The schedule is part of the known-input contract.  It contains only the
    prescribed body pose (an angle about a fixed axis), so evaluating
    :meth:`at` never reads a fluid trajectory or a reference state.  Triangles
    are stored in their world pose at ``time_s == 0``; only ``moving_body_id``
    is rotated.  A finite geometry is materialized for every feature call so
    nearest-wall features see both the current cup pose and its current wall
    velocity.
    """

    triangles: np.ndarray
    component_id: np.ndarray
    body_id: np.ndarray
    wall_velocity: np.ndarray
    coordinate_frame: str
    sample_times: np.ndarray
    sample_angles_degrees: np.ndarray
    axis_point: np.ndarray
    axis_direction: np.ndarray
    moving_body_id: int = 0
    version: str = PRESCRIBED_GEOMETRY_VERSION
    motion_version: str = PRESCRIBED_ROTATION_VERSION
    motion_sha256: str = ""
    _angular_velocity_rad_s: np.ndarray = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        for name in ("triangles", "wall_velocity", "sample_times", "sample_angles_degrees",
                     "axis_point", "axis_direction"):
            object.__setattr__(self, name, _array(getattr(self, name), dtype=np.float64))
        for name in ("component_id", "body_id"):
            object.__setattr__(self, name, _array(getattr(self, name), dtype=np.int64))
        object.__setattr__(self, "moving_body_id", int(self.moving_body_id))
        object.__setattr__(self, "motion_sha256", str(self.motion_sha256 or ""))
        self.validate()
        # A speed schedule is explicitly derived from the declared pose file;
        # it is never estimated from a reference HDF5 trajectory.
        angular = self.rotation_sign * np.gradient(
            self.sample_angles_degrees * np.pi / 180.0,
            self.sample_times, edge_order=1)
        angular = _array(angular, dtype=np.float64)
        object.__setattr__(self, "_angular_velocity_rad_s", angular)

    def validate(self):
        m = len(self.triangles)
        if (self.version != PRESCRIBED_GEOMETRY_VERSION
                or self.motion_version not in _PRESCRIBED_ROTATION_SIGNS
                or not self.coordinate_frame
                or self.triangles.shape != (m, 3, 3)
                or self.wall_velocity.shape != (m, 3)
                or self.component_id.shape != (m,)
                or self.body_id.shape != (m,)
                or self.sample_times.ndim != 1
                or self.sample_angles_degrees.shape != self.sample_times.shape
                or len(self.sample_times) < 2
                or self.axis_point.shape != (3,)
                or self.axis_direction.shape != (3,)):
            raise ValueError("invalid prescribed finite geometry contract")
        if (not np.isfinite(self.triangles).all() or not np.isfinite(self.wall_velocity).all()
                or not np.isfinite(self.sample_times).all()
                or not np.isfinite(self.sample_angles_degrees).all()
                or not np.isfinite(self.axis_point).all()
                or not np.isfinite(self.axis_direction).all()):
            raise ValueError("nonfinite prescribed geometry")
        if self.motion_sha256 and (len(self.motion_sha256) != 64
                                   or any(c not in "0123456789abcdef" for c in self.motion_sha256.lower())):
            raise ValueError("prescribed motion SHA-256 must be hexadecimal")
        if np.any(np.diff(self.sample_times) <= 0):
            raise ValueError("prescribed geometry times must increase strictly")
        norm = float(np.linalg.norm(self.axis_direction))
        if norm <= 1e-15:
            raise ValueError("prescribed rotation axis must be nonzero")
        if m == 0 or not np.any(self.body_id == self.moving_body_id):
            raise ValueError("prescribed rotation body has no finite triangles")
        if np.any(np.linalg.norm(np.cross(self.triangles[:, 1] - self.triangles[:, 0],
                                          self.triangles[:, 2] - self.triangles[:, 0]), axis=1) <= 1e-15):
            raise ValueError("degenerate prescribed finite triangle")
        return self

    @property
    def rotation_sign(self):
        """Signed pose multiplier for the declared motion angle.

        The default Core schedule is a right-handed Rodrigues rotation about
        ``axis_direction``.  DualSPHysics' native arbitrary-axis
        ``JMatrix4::MatrixRot(angle, p1, p2)`` represents the same axis with
        the opposite signed angle, so its motion version carries ``-1``.
        """
        return _PRESCRIBED_ROTATION_SIGNS[self.motion_version]

    @property
    def moving_mask(self):
        return self.body_id == self.moving_body_id

    def _rotation(self, time_s):
        if not np.isfinite(time_s):
            raise ValueError("prescribed geometry time must be finite")
        angle = (self.rotation_sign
                 * float(np.interp(float(time_s), self.sample_times,
                                   self.sample_angles_degrees)) * np.pi / 180.0)
        axis = self.axis_direction / np.linalg.norm(self.axis_direction)
        skew = np.array([[0., -axis[2], axis[1]],
                         [axis[2], 0., -axis[0]],
                         [-axis[1], axis[0], 0.]])
        return (np.eye(3) * np.cos(angle) + (1. - np.cos(angle)) * np.outer(axis, axis)
                + np.sin(angle) * skew)

    def world_from_body_at(self, time_s):
        """Return the prescribed homogeneous world-from-body pose."""
        rotation = self._rotation(time_s)
        result = np.eye(4, dtype=np.float64)
        result[:3, :3] = rotation
        result[:3, 3] = self.axis_point - rotation @ self.axis_point
        result.setflags(write=False)
        return result

    def at(self, time_s):
        """Materialize current triangles and prescribed wall velocity."""
        rotation = self._rotation(time_s)
        result = np.array(self.triangles, dtype=np.float64, copy=True)
        moving = self.moving_mask
        relative = result[moving] - self.axis_point
        result[moving] = relative @ rotation.T + self.axis_point
        wall = np.array(self.wall_velocity, dtype=np.float64, copy=True)
        angular_speed = float(np.interp(float(time_s), self.sample_times,
                                        self._angular_velocity_rad_s))
        omega = (self.axis_direction / np.linalg.norm(self.axis_direction)) * angular_speed
        centres = result[moving].mean(axis=1)
        wall[moving] = np.cross(np.broadcast_to(omega, centres.shape), centres - self.axis_point)
        return FiniteGeometry(result, self.component_id, self.body_id, wall, self.coordinate_frame,
                              rigid_axis_point=self.axis_point,
                              rigid_angular_velocity=omega,
                              rigid_mask=self.moving_mask)

    def as_dict(self):
        return {
            "version": self.version,
            "coordinate_frame": self.coordinate_frame,
            "triangles": self.triangles.tolist(),
            "component_id": self.component_id.tolist(),
            "body_id": self.body_id.tolist(),
            "wall_velocity": self.wall_velocity.tolist(),
            "prescribed_motion": {
                "version": self.motion_version,
                "time_s": self.sample_times.tolist(),
                "angle_degrees": self.sample_angles_degrees.tolist(),
                "axis_point": self.axis_point.tolist(),
                "axis_direction": self.axis_direction.tolist(),
                "moving_body_id": self.moving_body_id,
                "sha256": self.motion_sha256,
                "wall_velocity_semantics": "exact prescribed rigid velocity at closest surface point",
                "semantics": "declared rigid cup pose and derived wall velocity; no reference trajectory",
            },
        }


@dataclass(frozen=True)
class PrescribedControl:
    samples: np.ndarray
    centre: tuple = (.45, 0., 0.)
    semantics: str = "dualsphysics_f3_accinput_v1"
    _compiled: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        from scripts.f3_control import AccelerationControl
        control = AccelerationControl(self.samples)
        if self.semantics != "dualsphysics_f3_accinput_v1":
            raise ValueError("unknown prescribed control semantics")
        if np.asarray(self.centre).shape != (3,) or not np.isfinite(self.centre).all():
            raise ValueError("invalid control centre")
        object.__setattr__(self, "samples", _array(control.values))
        object.__setattr__(self, "centre", tuple(float(x) for x in self.centre))
        # The acceleration schedule is immutable metadata. Compile its
        # cumulative integral once so each causal feature call only brackets
        # the current time and interpolates six columns; no future state is
        # introduced by this cache.
        object.__setattr__(self, "_compiled", control)

    def acceleration(self, state):
        return self._compiled.body_acceleration(
            state.time_s, state.position, state.velocity, centre=self.centre)

    def at(self, time_s):
        return self._compiled.at(time_s)

    def as_dict(self):
        return {"samples": self.samples.tolist(), "centre": list(self.centre), "semantics": self.semantics}


@dataclass(frozen=True)
class KnownInputs:
    geometry: FiniteGeometry | PrescribedGeometry
    control: PrescribedControl
    physics: Mapping
    numerics: Mapping
    coordinate_frame: str
    contract_version: str = INPUT_VERSION

    def __post_init__(self):
        if type(self.geometry) not in (FiniteGeometry, PrescribedGeometry) or type(self.control) is not PrescribedControl:
            raise ValueError("known inputs require finite or prescribed geometry and prescribed arrays; providers are forbidden")
        if self.contract_version != INPUT_VERSION or self.geometry.coordinate_frame != self.coordinate_frame:
            raise ValueError("input version/coordinate frame mismatch")
        object.__setattr__(self, "physics", _freeze(_json_value(self.physics)))
        object.__setattr__(self, "numerics", _freeze(_json_value(self.numerics)))
        for key in ("dp_m", "h_m"):
            if key not in self.numerics or not math.isfinite(self.numerics[key]) or self.numerics[key] <= 0:
                raise ValueError("positive dp_m/h_m required")

    def geometry_at(self, time_s):
        """Return the finite geometry visible to a causal predictor now."""
        if type(self.geometry) is PrescribedGeometry:
            return self.geometry.at(time_s)
        if not math.isfinite(float(time_s)):
            raise ValueError("geometry time must be finite")
        return self.geometry

    @property
    def current_geometry(self):
        """Public name used by model adapters for the prescribed geometry."""
        return self.geometry

    @property
    def prescribed_control(self):
        """Public name used by model adapters for known controls."""
        return self.control

    def as_dict(self):
        return {"contract_version": self.contract_version, "coordinate_frame": self.coordinate_frame,
                "geometry": self.geometry.as_dict(), "control": self.control.as_dict(),
                "physics": _json_value(self.physics), "numerics": _json_value(self.numerics)}


def contract_hash(inputs: KnownInputs):
    return hashlib.sha256(json.dumps(inputs.as_dict(), sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class StepPrediction:
    displacement: np.ndarray
    delta_velocity: np.ndarray
    diagnostics: Mapping = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "displacement", _array(self.displacement, dtype=np.float64))
        object.__setattr__(self, "delta_velocity", _array(self.delta_velocity, dtype=np.float64))
        object.__setattr__(self, "diagnostics", _freeze(_json_value(self.diagnostics)))

    @property
    def displacement_m(self):
        """Displacement increment in metres."""
        return self.displacement

    @property
    def delta_velocity_mps(self):
        """Native velocity increment in metres per second."""
        return self.delta_velocity


@runtime_checkable
class Predictor(Protocol):
    """Minimal causal inference interface used by an autonomous rollout.

    A predictor sees one committed current ``State``, immutable ``KnownInputs``
    and the requested interval.  It returns independent displacement and
    native velocity increments.  The protocol intentionally has no reference
    state, trajectory reader or target argument.
    """

    def predict_step(self, state: State, known: KnownInputs, dt: float) -> StepPrediction:
        ...


def _validate_dt(state: State, dt: float) -> float:
    """Validate a positive interval that advances the public state clock."""
    if isinstance(dt, (bool, np.bool_)):
        raise ValueError("positive advancing dt required")
    try:
        value = float(dt)
    except (TypeError, ValueError) as error:
        raise ValueError("positive advancing dt required") from error
    if not math.isfinite(value) or value <= 0 or state.time_s + value <= state.time_s:
        raise ValueError("positive advancing dt required")
    return value


def validate_prediction(state: State, prediction: StepPrediction, dt: float | None = None):
    """Validate one complete-axis prediction before it reaches ``commit``.

    Inactive rows are outside the current lifecycle and may carry NaNs in a
    native source.  Active rows must always be finite; the complete array
    shape is retained so a predictor cannot silently drop or reorder IDs.
    """
    validate_state(state)
    if dt is not None:
        _validate_dt(state, dt)
    if not isinstance(prediction, StepPrediction):
        raise ValueError("StepPrediction required")
    if (prediction.displacement.shape != state.position.shape
            or prediction.delta_velocity.shape != state.velocity.shape):
        raise ValueError("prediction must preserve the complete particle axis")
    if not all(np.isfinite(value[state.valid]).all() for value in
               (prediction.displacement, prediction.delta_velocity)):
        raise ValueError("nonfinite active model prediction")
    return prediction


def commit(state: State, prediction: StepPrediction, dt: float):
    """Commit independent displacement and native velocity increments.

    The velocity field is updated from ``delta_velocity`` directly.  It is
    never reconstructed as ``displacement / dt``; saved native numerical
    velocity therefore remains a separate prediction target.
    """
    validate_state(state)
    dt = _validate_dt(state, dt)
    validate_prediction(state, prediction)
    return State(state.time_s + dt, state.position + prediction.displacement,
                 state.velocity + prediction.delta_velocity, state.particle_id,
                 state.particle_zone, state.mass, state.valid)


def apply_prediction(state: State, prediction: StepPrediction, dt: float):
    """Backward-compatible alias for :func:`commit`.

    Older diagnostics import ``apply_prediction``.  Keeping it as a thin alias
    prevents two subtly different state update paths from emerging.
    """
    return commit(state, prediction, dt)


def reference_displacement_oracle(state: State, following: State) -> StepPrediction:
    """Build privileged reference increments from two consecutive states.

    This helper is for scoring and contract diagnostics only.  It is kept
    separate from a predictor so future state can be used to form the target
    without ever crossing the predictor input boundary.  The displacement and
    native velocity increment are copied independently from the two saved
    states, preserving the distinction between ``dx`` and ``dv``.
    """
    validate_state(state)
    validate_state(following)
    dt = following.time_s - state.time_s
    _validate_dt(state, dt)
    if not all(np.array_equal(getattr(state, key), getattr(following, key)) for key in
               ("particle_id", "particle_zone", "mass", "valid")):
        raise ValueError("oracle identity/lifecycle/mass change requires a different task contract")
    return StepPrediction(following.position - state.position,
                          following.velocity - state.velocity,
                          {"oracle": "reference_displacement", "privileged_reference": True})


def updater_oracle(state: State, following: State):
    """Privileged reference increments pass through the actual public updater."""
    prediction = reference_displacement_oracle(state, following)
    dt = following.time_s - state.time_s
    updated = commit(state, prediction, dt)
    mask = state.valid
    return {"schema": "core.updater_oracle.v1", "particle_count": state.count,
            "dt_s": float(dt),
            "position_max_abs_error": float(np.max(np.abs(updated.position[mask] - following.position[mask]))),
            "native_velocity_max_abs_error": float(np.max(np.abs(updated.velocity[mask] - following.velocity[mask]))),
            "privileged_reference_increments": True, "learned_model_qualified": False,
            "velocity_semantics": STATE_VERSION}
