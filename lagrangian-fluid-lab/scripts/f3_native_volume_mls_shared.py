"""Shared current-field contract for the native-volume MLS backend.

The F3 temporal reference provider already has native ``mass`` and
``density`` arrays, while :mod:`scripts.core_material`'s predicted-state
contract currently exposes only ``mass``.  This module is the small boundary
between those two source families.  Both families must arrive at the MLS
backend as the same immutable field object, with an explicit density
semantics string.

There is deliberately no density fallback here.  In particular, an
``x``/``v``-only predicted state cannot be silently routed through the legacy
Shepard sampler, and a reference CFD density cannot be looked up while
adapting a model state.  The model adapter consumes one already-produced
``core_contract.State`` and a density estimate for that same state only.
It has no HDF5 handle, reference provider, or future-frame method.

This is a material-side interface candidate.  It does not change the frozen
F3 v1/v2/v3 runners and does not grant qualification.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


SCHEMA = "core.material.f3.native_volume_mls.shared_current_field.v1"
BACKEND = "f3_native_volume_mls_wendland_mass_density_shared_current_v1"
REFERENCE_ROLE = "reference_native"
MODEL_ROLE = "predicted_model"
ROLES = frozenset((REFERENCE_ROLE, MODEL_ROLE))


def _finite_float_array(name: str, value: Any, shape: tuple[int, ...] | None = None) -> np.ndarray:
    if value is None:
        raise ValueError(f"{name} is required; no implicit density or volume is allowed")
    array = np.asarray(value, dtype=np.float64)
    if shape is not None and array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    return np.array(array, dtype=np.float64, copy=True)


def _boolean_array(name: str, value: Any, shape: tuple[int, ...]) -> np.ndarray:
    array = np.asarray(value)
    if array.shape != shape or array.dtype.kind not in "biu" or not np.isin(array, [0, 1]).all():
        raise ValueError(f"{name} must be an explicit boolean mask with shape {shape}")
    return np.array(array, dtype=bool, copy=True)


def _text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _frame_index(value: Any) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise TypeError("frame_index must be an integer")
    value = int(value)
    if value < 0:
        raise ValueError("frame_index must be nonnegative")
    return value


@dataclass(frozen=True)
class NativeVolumeField:
    """One current material field accepted by native-volume MLS.

    ``native_indices`` is only a row locator for the saved support cloud.  It
    is not a tracer identity and is never used to terminate a material seed.
    Arrays are copied and made read-only in ``__post_init__``.  The object is
    intentionally source-agnostic after construction: the MLS routine sees
    the same ``position``, ``velocity``, ``mass``, ``density``, ``valid`` and
    ``volume`` attributes for reference and model inputs.
    """

    position: np.ndarray
    velocity: np.ndarray
    mass: np.ndarray
    density: np.ndarray
    valid: np.ndarray
    provider_role: str
    source_semantics: str
    density_semantics: str
    frame_index: int = 0
    time_s: float = 0.0
    density_time_s: float | None = None
    native_indices: np.ndarray | None = None

    def __post_init__(self):
        position = _finite_float_array("position", self.position)
        if position.ndim != 2 or position.shape[1:] != (3,):
            raise ValueError("position must have shape [N,3]")
        n = len(position)
        velocity = _finite_float_array("velocity", self.velocity, position.shape)
        mass = _finite_float_array("mass", self.mass, (n,))
        density = _finite_float_array("density", self.density, (n,))
        if np.any(mass <= 0.0):
            raise ValueError("mass must be positive")
        if np.any(density <= 0.0):
            raise ValueError("density must be positive")
        valid = _boolean_array("valid", self.valid, (n,))
        if not np.any(valid):
            raise ValueError("at least one current valid support row is required")
        role = _text("provider_role", self.provider_role)
        if role not in ROLES:
            raise ValueError(f"provider_role must be one of {sorted(ROLES)}")
        source = _text("source_semantics", self.source_semantics)
        density_source = _text("density_semantics", self.density_semantics)
        # A model field may use only an explicitly named estimate produced for
        # that model state.  This prevents a native/reference density from
        # being smuggled in under a generic model adapter call.
        if role == MODEL_ROLE and not density_source.startswith("model_"):
            raise ValueError(
                "predicted_model density_semantics must name a model estimate "
                "with the 'model_' prefix; native/reference density is forbidden"
            )
        if role == MODEL_ROLE and any(term in source.lower() for term in ("reference", "cfd", "native_h5")):
            raise ValueError("predicted_model source_semantics cannot identify a reference CFD source")
        time_s = float(self.time_s)
        if not np.isfinite(time_s):
            raise ValueError("time_s must be finite")
        density_time_s = time_s if self.density_time_s is None else float(self.density_time_s)
        if not np.isfinite(density_time_s):
            raise ValueError("density_time_s must be finite")
        tolerance = max(1.0e-12, 32.0 * np.finfo(np.float64).eps * max(1.0, abs(time_s)))
        if abs(density_time_s - time_s) > tolerance:
            raise ValueError(
                "density_time_s must equal the current field time; future/reference density "
                "cannot be supplied to the predicted model adapter"
            )
        index = _frame_index(self.frame_index)
        if self.native_indices is None:
            native_indices = np.arange(n, dtype=np.int64)
        else:
            original = np.asarray(self.native_indices)
            if original.shape != (n,) or original.dtype.kind not in "iu":
                raise ValueError("native_indices must be an integer array with shape [N]")
            if np.any(original < 0):
                raise ValueError("native_indices must be nonnegative")
            native_indices = np.array(original, dtype=np.int64, copy=True)
        volume = mass / density
        for array in (position, velocity, mass, density, valid, native_indices, volume):
            array.setflags(write=False)
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "velocity", velocity)
        object.__setattr__(self, "mass", mass)
        object.__setattr__(self, "density", density)
        object.__setattr__(self, "valid", valid)
        object.__setattr__(self, "native_indices", native_indices)
        object.__setattr__(self, "provider_role", role)
        object.__setattr__(self, "source_semantics", source)
        object.__setattr__(self, "density_semantics", density_source)
        object.__setattr__(self, "frame_index", index)
        object.__setattr__(self, "time_s", time_s)
        object.__setattr__(self, "density_time_s", density_time_s)
        object.__setattr__(self, "_volume", volume)

    @property
    def volume(self) -> np.ndarray:
        """Current particle volumes ``m/rho`` with no source-side lookup."""
        return self._volume

    @property
    def count(self) -> int:
        return len(self.position)

    @property
    def binding(self) -> dict[str, Any]:
        """Serializable source and causality metadata for a trace binding."""
        return {
            "schema": SCHEMA,
            "backend": BACKEND,
            "provider_role": self.provider_role,
            "source_semantics": self.source_semantics,
            "density_semantics": self.density_semantics,
            "frame_index": self.frame_index,
            "time_s": self.time_s,
            "density_time_s": self.density_time_s,
            "future_state_inputs": False,
            "reference_density_fallback": False,
            "legacy_shepard_fallback": False,
            "native_particle_id_is_tracer_identity": False,
        }


def from_reference_frame(
    frame: Any,
    *,
    source_semantics: str,
    density_semantics: str = "native_saved_density",
) -> NativeVolumeField:
    """Adapt one v1/v2/v3-style native reference frame.

    The frame must already be bounded to the caller's registered current
    interval.  This adapter does not open a source or fetch another frame.
    ``density_semantics`` is explicit so an interpolated endpoint pair can be
    labelled differently from a native saved frame.
    """
    required = ("position", "velocity", "mass", "density", "valid")
    missing = [name for name in required if not hasattr(frame, name)]
    if missing:
        raise ValueError(f"reference frame is missing native fields: {missing}")
    return NativeVolumeField(
        frame.position,
        frame.velocity,
        frame.mass,
        frame.density,
        frame.valid,
        provider_role=REFERENCE_ROLE,
        source_semantics=source_semantics,
        density_semantics=density_semantics,
        frame_index=getattr(frame, "frame_index", 0),
        time_s=getattr(frame, "time_s", 0.0),
        density_time_s=getattr(frame, "time_s", 0.0),
        native_indices=getattr(frame, "native_indices", None),
    )


def from_predicted_state(
    state: Any,
    density_estimate: Any = None,
    *,
    density_semantics: str = "model_density_estimate_v1",
    source_semantics: str = "predicted_current_state",
    frame_index: int = 0,
    density_time_s: float | None = None,
) -> NativeVolumeField:
    """Adapt one current model ``State`` plus its explicit density estimate.

    ``core_contract.State`` intentionally has no density field today.  The
    estimate is therefore a required, same-frame input supplied by the model
    implementation or a separately versioned public estimator.  Its
    ``density_time_s`` argument is mandatory and must equal ``state.time_s``.
    The function
    accepts no source path/provider and never reads an endpoint or future
    frame.  Calling it without density fails instead of silently switching to
    Shepard or using reference CFD density.
    """
    required = ("position", "velocity", "mass", "valid", "time_s")
    missing = [name for name in required if not hasattr(state, name)]
    if missing:
        raise TypeError(f"predicted state is missing fields: {missing}")
    # Import lazily so this shared material boundary does not make the generic
    # contract import the F3 backend at module import time.
    from scripts.core_contract import State, validate_state

    if not isinstance(state, State):
        raise TypeError("state must be a core_contract.State")
    validate_state(state)
    if density_estimate is None:
        raise ValueError(
            "predicted native-volume MLS requires an explicit current-state "
            "density_estimate; core.state.native_velocity.v1 has no density dataset"
        )
    if density_time_s is None:
        raise ValueError(
            "predicted native-volume MLS requires density_time_s for the same current State"
        )
    return NativeVolumeField(
        state.position,
        state.velocity,
        state.mass,
        density_estimate,
        state.valid,
        provider_role=MODEL_ROLE,
        source_semantics=source_semantics,
        density_semantics=density_semantics,
        frame_index=frame_index,
        time_s=state.time_s,
        density_time_s=density_time_s,
    )


def shared_backend_contract() -> dict[str, Any]:
    """Return the public contract metadata used by registrations and tests."""
    return {
        "schema": SCHEMA,
        "backend": BACKEND,
        "required_arrays": {
            "position": "[N,3] finite current support positions",
            "velocity": "[N,3] finite current support velocities",
            "mass": "[N] finite positive current support mass",
            "density": "[N] finite positive current support density or explicit model estimate",
            "valid": "[N] explicit boolean current support mask",
        },
        "provider_roles": sorted(ROLES),
        "model_adapter": {
            "input": "one core_contract.State plus density_estimate and density_time_s for that same state",
            "density_semantics_prefix": "model_",
            "density_time_binding": "density_time_s must equal State.time_s",
            "future_state_inputs": False,
            "reference_source_access": False,
            "implicit_mass_over_density": False,
        },
        "backend_weight_binding": "(mass/density)*Wendland_quintic_c2_3d(distance,h)",
        "legacy_shepard_backend": "f3_ckdtree_visible_shepard_distance_v1",
        "qualification_claim": "none",
    }
