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
from typing import Mapping

import numpy as np

STATE_VERSION = "core.state.native_velocity.v1"
INPUT_VERSION = "core.inputs.v1"
PREDICTION_VERSION = "core.prediction.dual_increment.v1"


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
            if any(term in normalized for term in (
                "future_fluid", "future_body", "reference_state", "target_state", "reader", "provider"
            )):
                raise ValueError("reference/provider state is forbidden in known inputs")
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

    def __post_init__(self):
        for name in ("triangles", "wall_velocity"):
            object.__setattr__(self, name, _array(getattr(self, name), dtype=np.float64))
        for name in ("component_id", "body_id"):
            object.__setattr__(self, name, _array(getattr(self, name), dtype=np.int64))
        self.validate()

    def validate(self):
        m = len(self.triangles)
        if (self.version != "core.finite_geometry.v1" or not self.coordinate_frame
                or self.triangles.shape != (m, 3, 3) or self.wall_velocity.shape != (m, 3)
                or self.component_id.shape != (m,) or self.body_id.shape != (m,)):
            raise ValueError("invalid finite triangle geometry contract")
        if not np.isfinite(self.triangles).all() or not np.isfinite(self.wall_velocity).all():
            raise ValueError("nonfinite geometry")
        if m and np.any(np.linalg.norm(np.cross(self.triangles[:, 1] - self.triangles[:, 0],
                                               self.triangles[:, 2] - self.triangles[:, 0]), axis=1) <= 1e-15):
            raise ValueError("degenerate finite triangle")
        return self

    def as_dict(self):
        return {"version": self.version, "coordinate_frame": self.coordinate_frame,
                **{name: getattr(self, name).tolist() for name in
                   ("triangles", "component_id", "body_id", "wall_velocity")}}

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
    geometry: FiniteGeometry
    control: PrescribedControl
    physics: Mapping
    numerics: Mapping
    coordinate_frame: str
    contract_version: str = INPUT_VERSION

    def __post_init__(self):
        if type(self.geometry) is not FiniteGeometry or type(self.control) is not PrescribedControl:
            raise ValueError("known inputs require finite geometry and prescribed arrays; providers are forbidden")
        if self.contract_version != INPUT_VERSION or self.geometry.coordinate_frame != self.coordinate_frame:
            raise ValueError("input version/coordinate frame mismatch")
        object.__setattr__(self, "physics", _freeze(_json_value(self.physics)))
        object.__setattr__(self, "numerics", _freeze(_json_value(self.numerics)))
        for key in ("dp_m", "h_m"):
            if key not in self.numerics or not math.isfinite(self.numerics[key]) or self.numerics[key] <= 0:
                raise ValueError("positive dp_m/h_m required")

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


def apply_prediction(state: State, prediction: StepPrediction, dt: float):
    """Commit both estimates without projection or a velocity finite difference."""
    validate_state(state)
    if not math.isfinite(dt) or dt <= 0 or state.time_s + dt <= state.time_s:
        raise ValueError("positive advancing dt required")
    if not isinstance(prediction, StepPrediction):
        raise ValueError("StepPrediction required")
    if prediction.displacement.shape != state.position.shape or prediction.delta_velocity.shape != state.velocity.shape:
        raise ValueError("prediction must preserve the complete particle axis")
    if not all(np.isfinite(value[state.valid]).all() for value in
               (prediction.displacement, prediction.delta_velocity)):
        raise ValueError("nonfinite active model prediction")
    return State(state.time_s + dt, state.position + prediction.displacement,
                 state.velocity + prediction.delta_velocity, state.particle_id,
                 state.particle_zone, state.mass, state.valid)


def updater_oracle(state: State, following: State):
    """Privileged reference increments pass through the actual public updater."""
    if not all(np.array_equal(getattr(state, key), getattr(following, key)) for key in
               ("particle_id", "particle_zone", "mass", "valid")):
        raise ValueError("oracle identity/lifecycle/mass change requires a different task contract")
    prediction = StepPrediction(following.position - state.position,
                                following.velocity - state.velocity)
    updated = apply_prediction(state, prediction, following.time_s - state.time_s)
    mask = state.valid
    return {"schema": "core.updater_oracle.v1", "particle_count": state.count,
            "position_max_abs_error": float(np.max(np.abs(updated.position[mask] - following.position[mask]))),
            "native_velocity_max_abs_error": float(np.max(np.abs(updated.velocity[mask] - following.velocity[mask]))),
            "privileged_reference_increments": True, "learned_model_qualified": False,
            "velocity_semantics": STATE_VERSION}
