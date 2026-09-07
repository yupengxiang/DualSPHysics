#!/usr/bin/env python3
"""Pure-Python R5 G4 training and artifact contract.

This module is deliberately independent of the R4 trainer and of ML/GPU
libraries.  A future trainer can import it before constructing a model, while
an audit or result collector can use the same helpers without importing
PyTorch.  The contract makes the current sidecar-aware widths explicit:

* direct routes consume 115 features;
* ``local_interaction`` consumes those 115 features plus an 8-wide local
  interaction extension, for a 123-wide model input.

The historical 43/51-wide artifacts are not another input variant.  They are
legacy artifacts and are rejected by the R5 validation helpers.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CONTRACT_ID = "r5-g4-input-v1"
FEATURE_LAYOUT_ID = "r5-g4-feature-layout-v1"
MISSING_MASK_POLICY_ID = "r5-g4-missing-masks-v1"
BOUNDARY_ENCODING_ID = "r5-g4-boundary-set-v1"
TARGET_SEMANTICS_ID = "r5-g4-target-semantics-v1"
ROLLOUT_STATE_ID = "r5-g4-rollout-state-v1"
DETERMINISM_POLICY_ID = "r5-g4-cuda-determinism-v1"

ROUTES = (
    "particle_mlp",
    "deepset_context",
    "local_interaction",
    "physics_residual",
)
DIRECT_ROUTES = ("particle_mlp", "deepset_context", "physics_residual")
LOCAL_ROUTE = "local_interaction"

BASE_FEATURE_WIDTH = 43
BOUNDARY_COMPONENT_FEATURE_FIELDS = (
    "presence",
    "distance",
    "normal_x",
    "normal_y",
    "normal_z",
    "type",
    "wall_velocity_x",
    "wall_velocity_y",
    "wall_velocity_z",
)
BOUNDARY_COMPONENT_WIDTH = len(BOUNDARY_COMPONENT_FEATURE_FIELDS)
MAX_BOUNDARY_COMPONENTS = 8
COMPONENT_BLOCK_WIDTH = BOUNDARY_COMPONENT_WIDTH * MAX_BOUNDARY_COMPONENTS
ACTIVE_FEATURE_WIDTH = BASE_FEATURE_WIDTH + COMPONENT_BLOCK_WIDTH
LOCAL_FEATURE_WIDTH = 8
LOCAL_MODEL_INPUT_WIDTH = ACTIVE_FEATURE_WIDTH + LOCAL_FEATURE_WIDTH
HISTORICAL_FEATURE_WIDTHS = (43, 51)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised by the strict validators when a contract gate is not met."""

    def __init__(self, message: str, errors: Sequence[Mapping[str, Any]] = ()):
        self.errors = [dict(error) for error in errors]
        super().__init__(message)


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


def canonical_json(value: Any) -> str:
    """Serialize a JSON-compatible object deterministically for hashing."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def sha256_file(path: str | Path) -> str:
    """Hash a file without importing any experiment or ML dependency."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _feature_field(
    name: str,
    start: int,
    end: int,
    *,
    source: str,
    scaling: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "start": start,
        "end": end,
        "width": end - start,
        "source": source,
        "scaling": scaling,
    }


BASE_FEATURE_LAYOUT = (
    _feature_field(
        "centered_xyz", 0, 3, source="current target position minus initial-mass-weighted current-context COM", scaling="/length_scale",
    ),
    _feature_field(
        "target_velocity_scaled", 3, 6, source="current target velocity state", scaling="velocity * dt / dp",
    ),
    _feature_field(
        "context_com_velocity_scaled", 6, 9, source="initial-mass-weighted current-context COM velocity", scaling="velocity * dt / dp",
    ),
    _feature_field(
        "initial_density_pressure_mass", 9, 12, source="frame-zero material attributes", scaling="rho/rho_ref, p/p_scale, m/median(m0)-1",
    ),
    _feature_field(
        "gravity", 12, 15, source="declared current-case gravity", scaling="gravity * dt^2 / dp",
    ),
    _feature_field(
        "static_physics", 15, 18, source="declared density, viscosity and gravity-presence summary", scaling="contract-defined dimensionless values",
    ),
    _feature_field(
        "current_prescribed_control", 18, 28, source="known prescribed control at current physical time", scaling="contract-defined angle/pose/angular-velocity normalization",
    ),
    _feature_field(
        "current_boundary_summary", 28, 35, source="current boundary availability and world-space bounds", scaling="availability bit plus bounds / length_scale",
    ),
    _feature_field(
        "family_one_hot", 35, 41, source="case family", scaling="one-hot",
    ),
    _feature_field(
        "elapsed_time", 41, 42, source="current physical time", scaling="time / time_scale",
    ),
    _feature_field(
        "dt", 42, 43, source="current step duration", scaling="dt / time_scale",
    ),
)


BOUNDARY_COMPONENT_ENCODING = {
    "id": BOUNDARY_ENCODING_ID,
    "kind": "finite_component_set",
    "key_fields": ["type", "component_id"],
    "ordering": "lexicographic_by_(type,component_id)",
    "slot_count": MAX_BOUNDARY_COMPONENTS,
    "slot_width": BOUNDARY_COMPONENT_WIDTH,
    "slot_stride": BOUNDARY_COMPONENT_WIDTH,
    "feature_fields": list(BOUNDARY_COMPONENT_FEATURE_FIELDS),
    "component_id_in_vector": False,
    "component_key_in_sidecar_metadata": True,
    "duplicate_policy": "reject_duplicate_(type,component_id)",
    "overflow_policy": "reject_more_than_8_components",
    "absent_slot_policy": "all_zero_with_presence_zero",
    "field_missing_policy": "reject_missing_or_nonfinite_present-component_fields",
}


MISSING_MASK_POLICY = {
    "id": MISSING_MASK_POLICY_ID,
    "representation": "in_band_presence_masks_plus_zero_fill",
    "masks": [
        {
            "name": "control_angle_present",
            "location": "current_prescribed_control[0]",
            "meaning": "the current prescribed angle/control record is available",
            "zero_fill": "all control values use the documented zero convention",
        },
        {
            "name": "control_schedule_available",
            "location": "current_prescribed_control[9]",
            "meaning": "the current prescribed control schedule is valid and available",
            "zero_fill": "control fields are zero when unavailable",
        },
        {
            "name": "boundary_summary_available",
            "location": "current_boundary_summary[0]",
            "meaning": "the current boundary summary is valid and available",
            "zero_fill": "six bounds are zero when unavailable",
        },
        {
            "name": "boundary_component_presence",
            "location": "boundary_component_slot[s][0]",
            "meaning": "canonical slot s contains a valid finite component",
            "zero_fill": "the remaining eight values in an absent slot are zero",
        },
        {
            "name": "local_neighbour_support_fraction",
            "location": "local_interaction_extension[7]",
            "meaning": "fraction of finite neighbours contributing to the local summary; zero means no finite support",
            "zero_fill": "all local summary values are zero when no finite support exists",
        },
    ],
    "field_level_missing": "not represented by NaN or an implicit zero; a present component with a missing/nonfinite required field is rejected",
}


TARGET_SEMANTICS = {
    "particle_mlp": {
        "id": "direct_next_velocity_scaled_v1",
        "kind": "next_velocity_scaled",
        "shape": [3],
        "formula": "y_t = v_(t+1) * dt / dp",
        "units": "dimensionless normalized velocity-step quantity",
        "prediction_is": "next solver velocity state, represented after dt/dp scaling",
    },
    "deepset_context": {
        "id": "direct_next_velocity_scaled_v1",
        "kind": "next_velocity_scaled",
        "shape": [3],
        "formula": "y_t = v_(t+1) * dt / dp",
        "units": "dimensionless normalized velocity-step quantity",
        "prediction_is": "next solver velocity state, represented after dt/dp scaling",
    },
    "local_interaction": {
        "id": "direct_next_velocity_scaled_v1",
        "kind": "next_velocity_scaled",
        "shape": [3],
        "formula": "y_t = v_(t+1) * dt / dp",
        "units": "dimensionless normalized velocity-step quantity",
        "prediction_is": "next solver velocity state, represented after dt/dp scaling",
    },
    "physics_residual": {
        "id": "acceleration_residual_dt2_over_dp_v1",
        "kind": "acceleration_residual",
        "shape": [3],
        "formula": "y_t = ((v_(t+1) - v_t) / dt) * dt^2 / dp",
        "units": "dimensionless normalized acceleration residual",
        "prediction_is": "acceleration residual integrated from the current velocity state",
    },
}


ROLLOUT_STATE = {
    "id": ROLLOUT_STATE_ID,
    "initialization": "position and velocity from solver frame zero; mass from frame-zero material state",
    "state_variables": ["position", "velocity", "mass", "current_frame", "current_time"],
    "teacher_forcing": "training reads the current solver state at frame t and labels frame t+1",
    "autonomous_update": "after frame zero, position and velocity are replaced only by the model's own predicted state",
    "known_inputs": "current state, current prescribed control, current boundary geometry, current dt, and frozen initial material attributes",
    "forbidden_inputs": [
        "future fluid position",
        "future fluid velocity",
        "future density",
        "future pressure",
        "future free-body pose or velocity",
    ],
    "integrator_id": "trapezoid_predicted_velocity_v1",
    "integrator": "v_next = route-specific decoded state; x_next = x_t + 0.5 * (v_t + v_next) * dt",
    "metrics_may_read_future_reference": True,
    "future_reference_is_model_input": False,
}


ROUTE_WIDTHS = {
    "particle_mlp": {
        "base_feature_width": ACTIVE_FEATURE_WIDTH,
        "local_extension_width": 0,
        "model_input_width": ACTIVE_FEATURE_WIDTH,
        "local_extension": None,
    },
    "deepset_context": {
        "base_feature_width": ACTIVE_FEATURE_WIDTH,
        "local_extension_width": 0,
        "model_input_width": ACTIVE_FEATURE_WIDTH,
        "local_extension": None,
    },
    "local_interaction": {
        "base_feature_width": ACTIVE_FEATURE_WIDTH,
        "local_extension_width": LOCAL_FEATURE_WIDTH,
        "model_input_width": LOCAL_MODEL_INPUT_WIDTH,
        "local_extension": {
            "name": "local_neighbour_summary",
            "start": ACTIVE_FEATURE_WIDTH,
            "end": LOCAL_MODEL_INPUT_WIDTH,
            "width": LOCAL_FEATURE_WIDTH,
            "fields": [
                "mean_relative_position_x",
                "mean_relative_position_y",
                "mean_relative_position_z",
                "mean_relative_velocity_x",
                "mean_relative_velocity_y",
                "mean_relative_velocity_z",
                "mean_distance_over_dp",
                "finite_neighbour_fraction",
            ],
            "encoding": "inverse-distance-weighted top-k finite neighbours",
        },
    },
    "physics_residual": {
        "base_feature_width": ACTIVE_FEATURE_WIDTH,
        "local_extension_width": 0,
        "model_input_width": ACTIVE_FEATURE_WIDTH,
        "local_extension": None,
    },
}


ARTIFACT_BINDING_FIELDS = (
    "input_contract_id",
    "input_contract_hash",
    "contract_hash",
    "feature_layout_hash",
    "target_semantics_hash",
    "rollout_state_hash",
    "trainer_sha256",
    "config_sha256",
    "data_sha256",
)
REQUIRED_HASH_FIELDS = (
    "trainer_sha256",
    "config_sha256",
    "data_sha256",
)


def _contract_spec() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "feature_layout_id": FEATURE_LAYOUT_ID,
        "base_feature_width": BASE_FEATURE_WIDTH,
        "active_base_feature_width": ACTIVE_FEATURE_WIDTH,
        "local_extension_width": LOCAL_FEATURE_WIDTH,
        "historical_feature_widths_rejected": list(HISTORICAL_FEATURE_WIDTHS),
        "feature_layout": {
            "base": [dict(field) for field in BASE_FEATURE_LAYOUT],
            "boundary_component_block": dict(BOUNDARY_COMPONENT_ENCODING),
            "routes": _deepcopy(ROUTE_WIDTHS),
        },
        "boundary_component_encoding": _deepcopy(BOUNDARY_COMPONENT_ENCODING),
        "missing_mask_policy": _deepcopy(MISSING_MASK_POLICY),
        "target_semantics": _deepcopy(TARGET_SEMANTICS),
        "rollout_state": _deepcopy(ROLLOUT_STATE),
        "artifact_binding": {
            "required_fields": list(ARTIFACT_BINDING_FIELDS),
            "hash_algorithm": "sha256",
            "hash_encoding": "lowercase_hex_64",
            "data_hash_semantics": "hash of the exact data manifest/content used by the run",
        },
        "checkpoint_policy": {
            "modes": ["inference_only", "resume_training"],
            "inference_only": {
                "required": ["checkpoint_mode", "resume_capable", "state_dict"],
                "resume_capable_value": False,
                "optimizer_state_allowed": False,
            },
            "resume_training": {
                "required": [
                    "checkpoint_mode",
                    "resume_capable",
                    "state_dict",
                    "optimizer_state_dict",
                    "scheduler_state_dict",
                    "rng_state",
                    "epoch",
                    "best_metric",
                ],
                "resume_capable_value": True,
            },
        },
        "cuda_determinism_policy": {
            "id": DETERMINISM_POLICY_ID,
            "record_required_for": "every result and checkpoint, including CPU runs",
            "strict_cuda_fields": [
                "mode",
                "device_type",
                "seed",
                "torch_deterministic_algorithms",
                "cudnn_deterministic",
                "cudnn_benchmark",
                "cublas_workspace_config",
            ],
        },
    }


CONTRACT_SPEC = _contract_spec()
CONTRACT_HASH = sha256_json(CONTRACT_SPEC)


def contract_snapshot() -> dict[str, Any]:
    """Return the complete machine-readable contract, including its hash."""

    snapshot = _deepcopy(CONTRACT_SPEC)
    snapshot["contract_hash"] = CONTRACT_HASH
    return snapshot


def write_contract_snapshot(path: str | Path) -> Path:
    """Write a deterministic contract snapshot for a campaign artifact."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(contract_snapshot(), indent=2, sort_keys=True) + "\n")
    return destination


def load_contract_snapshot(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ContractError("contract snapshot must be a JSON object")
    return payload


def _route(route: Any) -> str:
    value = str(route)
    if value not in ROUTES:
        raise ContractError(f"unknown G4 route: {route!r}")
    return value


def route_width(route: str) -> int:
    """Return the model input width, including a route-specific extension."""

    return int(ROUTE_WIDTHS[_route(route)]["model_input_width"])


def route_contract(route: str) -> dict[str, Any]:
    """Return the route-specific view of the shared R5 contract."""

    route = _route(route)
    layout = {
        "contract_id": CONTRACT_ID,
        "feature_layout_id": FEATURE_LAYOUT_ID,
        "base": [dict(field) for field in BASE_FEATURE_LAYOUT],
        "boundary_component_block": _deepcopy(BOUNDARY_COMPONENT_ENCODING),
        "route": route,
        "route_width": _deepcopy(ROUTE_WIDTHS[route]),
    }
    target = _deepcopy(TARGET_SEMANTICS[route])
    rollout = _deepcopy(ROLLOUT_STATE)
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "contract_hash": CONTRACT_HASH,
        "route": route,
        "feature_layout_id": FEATURE_LAYOUT_ID,
        "feature_layout_hash": sha256_json(layout),
        "feature_layout": layout,
        "target_semantics_id": target["id"],
        "target_semantics_hash": sha256_json(target),
        "target_semantics": target,
        "rollout_state_id": ROLLOUT_STATE_ID,
        "rollout_state_hash": sha256_json(rollout),
        "rollout_state": rollout,
        "boundary_component_encoding_id": BOUNDARY_ENCODING_ID,
        "missing_mask_policy_id": MISSING_MASK_POLICY_ID,
        "base_feature_width": ACTIVE_FEATURE_WIDTH,
        "local_extension_width": int(ROUTE_WIDTHS[route]["local_extension_width"]),
        "model_input_width": route_width(route),
    }


def target_semantics(route: str) -> dict[str, Any]:
    return _deepcopy(TARGET_SEMANTICS[_route(route)])


def feature_layout(route: str) -> dict[str, Any]:
    return _deepcopy(route_contract(route)["feature_layout"])


def _normalise_device_type(device: Any) -> str:
    value = str(device or "cpu").lower().split(":", 1)[0]
    if value == "gpu":
        value = "cuda"
    return value


def make_cuda_determinism_policy(
    device: str = "cpu",
    *,
    seed: int | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Create an explicit deterministic-policy record without touching CUDA."""

    device_type = _normalise_device_type(device)
    if device_type == "cuda":
        return {
            "policy_id": DETERMINISM_POLICY_ID,
            "mode": "strict" if strict else "best_effort",
            "device_type": "cuda",
            "seed": seed,
            "torch_deterministic_algorithms": "error" if strict else "warn",
            "cudnn_deterministic": bool(strict),
            "cudnn_benchmark": False,
            "cublas_workspace_config": ":4096:8" if strict else None,
            "notes": "policy record only; caller must apply it before constructing CUDA tensors",
        }
    return {
        "policy_id": DETERMINISM_POLICY_ID,
        "mode": "not_applicable_cpu" if device_type == "cpu" else "best_effort",
        "device_type": device_type,
        "seed": seed,
        "torch_deterministic_algorithms": "not_applicable" if device_type == "cpu" else "warn",
        "cudnn_deterministic": False,
        "cudnn_benchmark": False,
        "cublas_workspace_config": None,
        "notes": "policy record only; no runtime backend is invoked by this contract module",
    }


def _error(code: str, field: str, expected: Any = None, actual: Any = None, message: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "field": field}
    if expected is not None:
        result["expected"] = expected
    if actual is not None:
        result["actual"] = actual
    if message is not None:
        result["message"] = message
    return result


def _report(errors: Sequence[Mapping[str, Any]], **fields: Any) -> dict[str, Any]:
    result = {"valid": not errors, "errors": [dict(error) for error in errors]}
    result.update(fields)
    return result


def _metadata_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        result = dict(metadata)
        for key, value in payload.items():
            result.setdefault(key, value)
        return result
    return dict(payload)


def _require_sha256(metadata: Mapping[str, Any], errors: list[dict[str, Any]], field: str) -> None:
    value = metadata.get(field)
    if not is_sha256(value):
        errors.append(_error("missing_or_invalid_sha256", field, "64 lowercase hexadecimal characters", value))


def validate_cuda_determinism_policy(policy: Any, *, device: str | None = None) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not isinstance(policy, Mapping):
        errors.append(_error("missing_determinism_policy", "cuda_determinism_policy", "object", policy))
        return _report(errors)
    policy = dict(policy)
    if policy.get("policy_id") != DETERMINISM_POLICY_ID:
        errors.append(_error("determinism_policy_id_mismatch", "cuda_determinism_policy.policy_id", DETERMINISM_POLICY_ID, policy.get("policy_id")))
    policy_device = _normalise_device_type(policy.get("device_type"))
    if device is not None and policy_device != _normalise_device_type(device):
        errors.append(_error("determinism_device_mismatch", "cuda_determinism_policy.device_type", _normalise_device_type(device), policy_device))
    required = ("mode", "device_type", "seed", "torch_deterministic_algorithms", "cudnn_deterministic", "cudnn_benchmark", "cublas_workspace_config")
    for field in required:
        if field not in policy:
            errors.append(_error("missing_determinism_field", f"cuda_determinism_policy.{field}"))
    if policy_device == "cuda":
        if policy.get("mode") not in {"strict", "best_effort"}:
            errors.append(_error("invalid_cuda_determinism_mode", "cuda_determinism_policy.mode", ["strict", "best_effort"], policy.get("mode")))
        if policy.get("mode") == "strict":
            if policy.get("torch_deterministic_algorithms") != "error":
                errors.append(_error("strict_cuda_policy_not_error", "cuda_determinism_policy.torch_deterministic_algorithms", "error", policy.get("torch_deterministic_algorithms")))
            if policy.get("cudnn_deterministic") is not True:
                errors.append(_error("strict_cuda_policy_cudnn", "cuda_determinism_policy.cudnn_deterministic", True, policy.get("cudnn_deterministic")))
            if policy.get("cudnn_benchmark") is not False:
                errors.append(_error("strict_cuda_policy_benchmark", "cuda_determinism_policy.cudnn_benchmark", False, policy.get("cudnn_benchmark")))
            if policy.get("cublas_workspace_config") not in {":4096:8", ":16:8"}:
                errors.append(_error("strict_cuda_policy_cublas", "cuda_determinism_policy.cublas_workspace_config", [":4096:8", ":16:8"], policy.get("cublas_workspace_config")))
    elif policy_device == "cpu":
        if policy.get("mode") != "not_applicable_cpu":
            errors.append(_error("cpu_policy_mode_mismatch", "cuda_determinism_policy.mode", "not_applicable_cpu", policy.get("mode")))
    return _report(errors, policy=policy)


def validate_contract_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not isinstance(snapshot, Mapping):
        return _report([_error("contract_snapshot_not_object", "snapshot", "object", snapshot)])
    snapshot = dict(snapshot)
    if snapshot.get("contract_id") != CONTRACT_ID:
        errors.append(_error("contract_id_mismatch", "contract_id", CONTRACT_ID, snapshot.get("contract_id")))
    if snapshot.get("contract_hash") != CONTRACT_HASH:
        errors.append(_error("contract_hash_mismatch", "contract_hash", CONTRACT_HASH, snapshot.get("contract_hash")))
    unsigned = {key: value for key, value in snapshot.items() if key != "contract_hash"}
    if sha256_json(unsigned) != CONTRACT_HASH:
        errors.append(_error("contract_content_hash_mismatch", "contract_hash", CONTRACT_HASH, sha256_json(unsigned)))
    return _report(errors, contract_id=snapshot.get("contract_id"), contract_hash=snapshot.get("contract_hash"))


def validate_input_contract_metadata(metadata: Mapping[str, Any], route: str | None = None) -> dict[str, Any]:
    """Non-throwing check for input/provenance fields used by any artifact."""

    errors: list[dict[str, Any]] = []
    if not isinstance(metadata, Mapping):
        return _report([_error("metadata_not_object", "metadata", "object", metadata)])
    metadata = _metadata_view(metadata)
    actual_route = route if route is not None else metadata.get("route")
    try:
        actual_route = _route(actual_route)
    except ContractError as error:
        errors.append(_error("missing_or_invalid_route", "route", list(ROUTES), actual_route))
        actual_route = None
    expected_width = route_width(actual_route) if actual_route is not None else None

    scalar_expectations = (
        ("schema_version", SCHEMA_VERSION),
        ("contract_schema_version", SCHEMA_VERSION),
        ("input_contract_id", CONTRACT_ID),
        ("input_contract_hash", CONTRACT_HASH),
        ("contract_hash", CONTRACT_HASH),
        ("feature_layout_id", FEATURE_LAYOUT_ID),
        ("boundary_component_encoding_id", BOUNDARY_ENCODING_ID),
        ("missing_mask_policy_id", MISSING_MASK_POLICY_ID),
        ("rollout_state_id", ROLLOUT_STATE_ID),
    )
    for field, expected in scalar_expectations:
        if metadata.get(field) != expected:
            errors.append(_error("contract_field_mismatch", field, expected, metadata.get(field)))

    if metadata.get("input_contract_hash") != metadata.get("contract_hash"):
        errors.append(_error("contract_hash_alias_mismatch", "contract_hash", metadata.get("input_contract_hash"), metadata.get("contract_hash")))

    for field in REQUIRED_HASH_FIELDS:
        _require_sha256(metadata, errors, field)

    if actual_route is not None:
        if metadata.get("route") != actual_route:
            errors.append(_error("route_mismatch", "route", actual_route, metadata.get("route")))
        expected = route_contract(actual_route)
        if metadata.get("base_feature_width") != ACTIVE_FEATURE_WIDTH:
            errors.append(_error("base_feature_width_mismatch", "base_feature_width", ACTIVE_FEATURE_WIDTH, metadata.get("base_feature_width")))
        if metadata.get("feature_layout_hash") != expected["feature_layout_hash"]:
            errors.append(_error("feature_layout_hash_mismatch", "feature_layout_hash", expected["feature_layout_hash"], metadata.get("feature_layout_hash")))
        if metadata.get("target_semantics_id") != expected["target_semantics_id"]:
            errors.append(_error("target_semantics_id_mismatch", "target_semantics_id", expected["target_semantics_id"], metadata.get("target_semantics_id")))
        if metadata.get("target_semantics_hash") != expected["target_semantics_hash"]:
            errors.append(_error("target_semantics_hash_mismatch", "target_semantics_hash", expected["target_semantics_hash"], metadata.get("target_semantics_hash")))
        if metadata.get("rollout_state_hash") != expected["rollout_state_hash"]:
            errors.append(_error("rollout_state_hash_mismatch", "rollout_state_hash", expected["rollout_state_hash"], metadata.get("rollout_state_hash")))
        if metadata.get("integrator_id") != ROLLOUT_STATE["integrator_id"]:
            errors.append(_error("integrator_id_mismatch", "integrator_id", ROLLOUT_STATE["integrator_id"], metadata.get("integrator_id")))
        if metadata.get("feature_width") != expected_width:
            code = "historical_feature_width_rejected" if metadata.get("feature_width") in HISTORICAL_FEATURE_WIDTHS else "feature_width_mismatch"
            errors.append(_error(code, "feature_width", expected_width, metadata.get("feature_width"), "legacy 43/51-wide inputs cannot be mixed with the R5 sidecar-aware contract" if code == "historical_feature_width_rejected" else None))
        if metadata.get("model_input_width") is not None and metadata.get("model_input_width") != expected_width:
            errors.append(_error("model_input_width_mismatch", "model_input_width", expected_width, metadata.get("model_input_width")))
        if metadata.get("first_linear_input_width") is not None and metadata.get("first_linear_input_width") != expected_width:
            code = "historical_checkpoint_input_width_rejected" if metadata.get("first_linear_input_width") in HISTORICAL_FEATURE_WIDTHS else "checkpoint_input_width_mismatch"
            errors.append(_error(code, "first_linear_input_width", expected_width, metadata.get("first_linear_input_width")))
    if metadata.get("seed") is not None and (not isinstance(metadata.get("seed"), int) or isinstance(metadata.get("seed"), bool)):
        errors.append(_error("invalid_seed", "seed", "integer", metadata.get("seed")))
    determinism = validate_cuda_determinism_policy(metadata.get("cuda_determinism_policy"), device=metadata.get("device"))
    errors.extend(determinism["errors"])
    return _report(errors, route=actual_route, expected_feature_width=expected_width, contract_hash=CONTRACT_HASH)


def assert_valid_input_contract_metadata(metadata: Mapping[str, Any], route: str | None = None) -> dict[str, Any]:
    report = validate_input_contract_metadata(metadata, route=route)
    if not report["valid"]:
        raise ContractError("invalid R5 G4 input contract metadata", report["errors"])
    return report


def build_artifact_metadata(
    route: str,
    seed: int,
    *,
    trainer_sha256: str,
    config_sha256: str,
    data_sha256: str,
    device: str = "cpu",
    determinism_policy: Mapping[str, Any] | None = None,
    feature_width: int | None = None,
    artifact_kind: str = "result",
    checkpoint_mode: str = "inference_only",
    run_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the common metadata block for a result or checkpoint."""

    route = _route(route)
    expected = route_contract(route)
    width = route_width(route) if feature_width is None else int(feature_width)
    policy = _deepcopy(determinism_policy) if determinism_policy is not None else make_cuda_determinism_policy(device, seed=seed)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_schema_version": SCHEMA_VERSION,
        "artifact_kind": artifact_kind,
        "route": route,
        "seed": int(seed),
        "device": str(device),
        "input_contract_id": CONTRACT_ID,
        "input_contract_hash": CONTRACT_HASH,
        "contract_hash": CONTRACT_HASH,
        "feature_layout_id": FEATURE_LAYOUT_ID,
        "feature_layout_hash": expected["feature_layout_hash"],
        "base_feature_width": ACTIVE_FEATURE_WIDTH,
        "feature_width": width,
        "model_input_width": width,
        "first_linear_input_width": width,
        "target_semantics_id": expected["target_semantics_id"],
        "target_semantics_hash": expected["target_semantics_hash"],
        "rollout_state_id": ROLLOUT_STATE_ID,
        "rollout_state_hash": expected["rollout_state_hash"],
        "integrator_id": ROLLOUT_STATE["integrator_id"],
        "boundary_component_encoding_id": BOUNDARY_ENCODING_ID,
        "missing_mask_policy_id": MISSING_MASK_POLICY_ID,
        "trainer_sha256": trainer_sha256,
        "config_sha256": config_sha256,
        "data_sha256": data_sha256,
        "checkpoint_mode": checkpoint_mode,
        "cuda_determinism_policy": policy,
    }
    if run_id is not None:
        result["run_id"] = str(run_id)
    result.update(extra)
    return result


def build_result_metadata(*args: Any, **kwargs: Any) -> dict[str, Any]:
    kwargs["artifact_kind"] = "result"
    return build_artifact_metadata(*args, **kwargs)


def build_checkpoint_metadata(*args: Any, **kwargs: Any) -> dict[str, Any]:
    kwargs["artifact_kind"] = "checkpoint"
    metadata = build_artifact_metadata(*args, **kwargs)
    mode = metadata["checkpoint_mode"]
    if mode not in {"inference_only", "resume_training"}:
        raise ContractError(f"unknown checkpoint mode: {mode!r}")
    metadata["resume_capable"] = mode == "resume_training"
    return metadata


def _validate_artifact_kind(metadata: Mapping[str, Any], expected_kind: str, errors: list[dict[str, Any]]) -> None:
    if metadata.get("artifact_kind") != expected_kind:
        errors.append(_error("artifact_kind_mismatch", "artifact_kind", expected_kind, metadata.get("artifact_kind")))


def validate_result_metadata(metadata: Mapping[str, Any], route: str | None = None) -> dict[str, Any]:
    view = _metadata_view(metadata) if isinstance(metadata, Mapping) else metadata
    common = validate_input_contract_metadata(view, route=route)
    errors = list(common["errors"])
    if isinstance(view, Mapping):
        _validate_artifact_kind(view, "result", errors)
        if "checkpoint_mode" not in view:
            errors.append(_error("missing_checkpoint_mode", "checkpoint_mode", ["inference_only", "resume_training"]))
        if "result_schema_version" in view and view.get("result_schema_version") != SCHEMA_VERSION:
            errors.append(_error("result_schema_version_mismatch", "result_schema_version", SCHEMA_VERSION, view.get("result_schema_version")))
    return _report(errors, route=common.get("route"), expected_feature_width=common.get("expected_feature_width"))


def _has_any(mapping: Mapping[str, Any], names: Sequence[str]) -> bool:
    return any(name in mapping and mapping.get(name) is not None for name in names)


def validate_checkpoint_payload(payload: Mapping[str, Any], route: str | None = None) -> dict[str, Any]:
    """Validate a checkpoint payload without deserializing or executing it."""

    if not isinstance(payload, Mapping):
        return _report([_error("checkpoint_not_object", "checkpoint", "object", payload)])
    view = _metadata_view(payload)
    common = validate_input_contract_metadata(view, route=route)
    errors = list(common["errors"])
    _validate_artifact_kind(view, "checkpoint", errors)

    state_key = next((key for key in ("state_dict", "model_state_dict", "model_state") if key in payload), None)
    if state_key is None:
        errors.append(_error("missing_model_state", "state_dict", "present", None))

    mode = view.get("checkpoint_mode")
    if mode not in {"inference_only", "resume_training"}:
        errors.append(_error("invalid_checkpoint_mode", "checkpoint_mode", ["inference_only", "resume_training"], mode))
    elif mode == "inference_only":
        if view.get("resume_capable") is not False:
            errors.append(_error("inference_only_not_explicit", "resume_capable", False, view.get("resume_capable")))
        if _has_any(payload, ("optimizer_state_dict", "scheduler_state_dict", "optimizer", "scheduler")):
            errors.append(_error("inference_only_contains_training_state", "checkpoint_mode", "no optimizer/scheduler state", mode))
    else:
        if view.get("resume_capable") is not True:
            errors.append(_error("resume_checkpoint_not_explicit", "resume_capable", True, view.get("resume_capable")))
        required = (
            "optimizer_state_dict",
            "scheduler_state_dict",
            "rng_state",
            "epoch",
            "best_metric",
        )
        for field in required:
            if field not in payload and field not in view:
                errors.append(_error("missing_resume_state", field, "present", None))
        if "epoch" in view and (not isinstance(view["epoch"], int) or isinstance(view["epoch"], bool) or view["epoch"] < 0):
            errors.append(_error("invalid_resume_epoch", "epoch", "nonnegative integer", view["epoch"]))
        if "best_metric" in view and not isinstance(view["best_metric"], (int, float)):
            errors.append(_error("invalid_best_metric", "best_metric", "number", view["best_metric"]))
    return _report(errors, route=common.get("route"), expected_feature_width=common.get("expected_feature_width"), state_key=state_key, checkpoint_mode=mode)


def _binding_view(value: Mapping[str, Any]) -> dict[str, Any]:
    return _metadata_view(value)


def validate_result_checkpoint_pair(
    result: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    route: str | None = None,
) -> dict[str, Any]:
    """Validate both artifacts and their shared provenance binding."""

    result_report = validate_result_metadata(result, route=route)
    checkpoint_report = validate_checkpoint_payload(checkpoint, route=route)
    errors = list(result_report["errors"]) + list(checkpoint_report["errors"])
    result_view = _binding_view(result) if isinstance(result, Mapping) else {}
    checkpoint_view = _binding_view(checkpoint) if isinstance(checkpoint, Mapping) else {}
    for field in ARTIFACT_BINDING_FIELDS + ("route", "seed", "feature_width", "checkpoint_mode"):
        if field in result_view and field in checkpoint_view and result_view[field] != checkpoint_view[field]:
            errors.append(_error("result_checkpoint_binding_mismatch", field, result_view[field], checkpoint_view[field]))
    if result_view.get("checkpoint_mode") == "resume_training" and checkpoint_view.get("checkpoint_mode") != "resume_training":
        errors.append(_error("result_checkpoint_mode_mismatch", "checkpoint_mode", result_view.get("checkpoint_mode"), checkpoint_view.get("checkpoint_mode")))
    return _report(errors, result=result_report, checkpoint=checkpoint_report, binding_fields=list(ARTIFACT_BINDING_FIELDS))


def assert_valid_result_checkpoint_pair(result: Mapping[str, Any], checkpoint: Mapping[str, Any], route: str | None = None) -> dict[str, Any]:
    report = validate_result_checkpoint_pair(result, checkpoint, route=route)
    if not report["valid"]:
        raise ContractError("invalid R5 G4 result/checkpoint pair", report["errors"])
    return report


def _component_key(component: Any) -> tuple[int, int]:
    if isinstance(component, Mapping):
        kind = component.get("type", component.get("boundary_type"))
        identifier = component.get("component_id", component.get("id"))
    elif isinstance(component, Sequence) and not isinstance(component, (str, bytes)) and len(component) == 2:
        kind, identifier = component
    else:
        raise ContractError("boundary component must provide type and component_id")
    if isinstance(kind, bool) or isinstance(identifier, bool):
        raise ContractError("boundary component key values must be integers")
    try:
        key = (int(kind), int(identifier))
    except (TypeError, ValueError) as error:
        raise ContractError("boundary component key values must be integers") from error
    if kind is None or identifier is None:
        raise ContractError("boundary component must provide type and component_id")
    return key


def canonical_component_keys(components: Sequence[Any]) -> tuple[tuple[int, int], ...]:
    """Return the order-independent canonical key set for boundary components."""

    keys = [_component_key(component) for component in components]
    if len(set(keys)) != len(keys):
        raise ContractError("duplicate boundary component key")
    if len(keys) > MAX_BOUNDARY_COMPONENTS:
        raise ContractError(f"at most {MAX_BOUNDARY_COMPONENTS} boundary components are supported")
    return tuple(sorted(keys))


def canonical_component_slots(components: Sequence[Any]) -> tuple[tuple[int, int] | None, ...]:
    """Return canonical fixed slots, including ``None`` padding."""

    keys = canonical_component_keys(components)
    return keys + (None,) * (MAX_BOUNDARY_COMPONENTS - len(keys))


def component_slot_map(components: Sequence[Any]) -> dict[tuple[int, int], int]:
    return {key: slot for slot, key in enumerate(canonical_component_keys(components))}


def canonicalize_boundary_components(components: Sequence[Any]) -> list[dict[str, Any]]:
    """Canonicalize component metadata without retaining source ordering."""

    keys = canonical_component_keys(components)
    return [
        {"slot": slot, "type": key[0], "component_id": key[1], "key": [key[0], key[1]]}
        for slot, key in enumerate(keys)
    ]


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _component_feature_vector(component: Any, key: tuple[int, int]) -> list[float]:
    if not isinstance(component, Mapping):
        return [1.0, 0.0, 0.0, 0.0, 0.0, float(key[0]), 0.0, 0.0, 0.0]
    raw = component.get("features")
    if isinstance(raw, Mapping):
        source = dict(component)
        source.update(raw)
        values = [source.get(field) for field in BOUNDARY_COMPONENT_FEATURE_FIELDS]
        values[0] = 1.0 if values[0] is None else values[0]
        values[5] = float(key[0]) if values[5] is None else values[5]
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        values = list(raw)
        if len(values) != BOUNDARY_COMPONENT_WIDTH:
            raise ContractError("boundary component feature vector has the wrong width")
    else:
        values = [1.0, 0.0, 0.0, 0.0, 0.0, float(key[0]), 0.0, 0.0, 0.0]
    if not all(_finite_number(value) for value in values):
        raise ContractError("present boundary component features must be finite numbers")
    if float(values[0]) != 1.0:
        raise ContractError("present boundary component presence must equal 1")
    return [float(value) for value in values]


def pack_boundary_component_set(components: Sequence[Any]) -> dict[str, Any]:
    """Pack a component set into canonical slots and a fixed-width vector.

    The returned ``flat_features`` is invariant to the input list order.  The
    component keys are retained in metadata because component identity is not
    encoded as a learned numeric feature.
    """

    entries = {_component_key(component): component for component in components}
    keys = tuple(sorted(entries))
    if len(keys) != len(components):
        raise ContractError("duplicate boundary component key")
    if len(keys) > MAX_BOUNDARY_COMPONENTS:
        raise ContractError(f"at most {MAX_BOUNDARY_COMPONENTS} boundary components are supported")
    slots: list[dict[str, Any]] = []
    flat: list[float] = []
    presence: list[int] = []
    for slot in range(MAX_BOUNDARY_COMPONENTS):
        if slot < len(keys):
            key = keys[slot]
            values = _component_feature_vector(entries[key], key)
            slots.append({"slot": slot, "key": [key[0], key[1]], "features": values})
            flat.extend(values)
            presence.append(1)
        else:
            values = [0.0] * BOUNDARY_COMPONENT_WIDTH
            slots.append({"slot": slot, "key": None, "features": values})
            flat.extend(values)
            presence.append(0)
    return {
        "encoding_id": BOUNDARY_ENCODING_ID,
        "keys": [[key[0], key[1]] for key in keys],
        "slots": slots,
        "flat_features": flat,
        "missing_masks": {"boundary_component_presence": presence},
    }


def validate_packed_boundary_component_set(packed: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if not isinstance(packed, Mapping):
        return _report([_error("packed_components_not_object", "packed", "object", packed)])
    if packed.get("encoding_id") != BOUNDARY_ENCODING_ID:
        errors.append(_error("boundary_encoding_id_mismatch", "encoding_id", BOUNDARY_ENCODING_ID, packed.get("encoding_id")))
    slots = packed.get("slots")
    if not isinstance(slots, Sequence) or isinstance(slots, (str, bytes)) or len(slots) != MAX_BOUNDARY_COMPONENTS:
        errors.append(_error("boundary_slot_count_mismatch", "slots", MAX_BOUNDARY_COMPONENTS, len(slots) if isinstance(slots, Sequence) else None))
        return _report(errors)
    keys: list[tuple[int, int]] = []
    for index, slot in enumerate(slots):
        if not isinstance(slot, Mapping) or slot.get("slot") != index:
            errors.append(_error("boundary_slot_index_mismatch", f"slots[{index}].slot", index, slot.get("slot") if isinstance(slot, Mapping) else None))
            continue
        key = slot.get("key")
        if key is None:
            if slot.get("features") != [0.0] * BOUNDARY_COMPONENT_WIDTH:
                errors.append(_error("absent_boundary_slot_not_zero", f"slots[{index}].features", [0.0] * BOUNDARY_COMPONENT_WIDTH, slot.get("features")))
            continue
        try:
            parsed = _component_key(key)
        except ContractError:
            errors.append(_error("invalid_boundary_slot_key", f"slots[{index}].key", "[type, component_id]", key))
            continue
        keys.append(parsed)
        features = slot.get("features")
        if (
            not isinstance(features, Sequence)
            or isinstance(features, (str, bytes))
            or len(features) != BOUNDARY_COMPONENT_WIDTH
        ):
            errors.append(_error("boundary_slot_feature_width_mismatch", f"slots[{index}].features", BOUNDARY_COMPONENT_WIDTH, len(features) if isinstance(features, Sequence) else None))
    if tuple(keys) != tuple(sorted(keys)):
        errors.append(_error("boundary_component_order_not_canonical", "slots[*].key", "lexicographic sorted order", [list(key) for key in keys]))
    if len(set(keys)) != len(keys):
        errors.append(_error("duplicate_boundary_component_key", "slots[*].key"))
    if packed.get("keys") != [list(key) for key in keys]:
        errors.append(_error("boundary_keys_metadata_mismatch", "keys", [list(key) for key in keys], packed.get("keys")))
    flat = packed.get("flat_features")
    if not isinstance(flat, Sequence) or isinstance(flat, (str, bytes)) or len(flat) != COMPONENT_BLOCK_WIDTH:
        errors.append(_error("boundary_flat_width_mismatch", "flat_features", COMPONENT_BLOCK_WIDTH, len(flat) if isinstance(flat, Sequence) else None))
    masks = packed.get("missing_masks")
    expected_presence = [1 if slot.get("key") is not None else 0 for slot in slots if isinstance(slot, Mapping)]
    if not isinstance(masks, Mapping) or masks.get("boundary_component_presence") != expected_presence:
        errors.append(_error("boundary_presence_mask_mismatch", "missing_masks.boundary_component_presence", expected_presence, masks.get("boundary_component_presence") if isinstance(masks, Mapping) else None))
    return _report(errors, canonical_keys=[list(key) for key in keys])


def validate_result_and_checkpoint(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Backward-friendly alias for callers that prefer a shorter name."""

    return validate_result_checkpoint_pair(*args, **kwargs)


def validate_run_metadata(metadata: Mapping[str, Any], route: str | None = None) -> dict[str, Any]:
    """Alias used by training launchers before creating a run directory."""

    return validate_input_contract_metadata(metadata, route=route)


def assert_valid_run_metadata(metadata: Mapping[str, Any], route: str | None = None) -> dict[str, Any]:
    return assert_valid_input_contract_metadata(metadata, route=route)


__all__ = [
    "ACTIVE_FEATURE_WIDTH",
    "ARTIFACT_BINDING_FIELDS",
    "BASE_FEATURE_LAYOUT",
    "BASE_FEATURE_WIDTH",
    "BOUNDARY_COMPONENT_FEATURE_FIELDS",
    "BOUNDARY_COMPONENT_WIDTH",
    "BOUNDARY_ENCODING_ID",
    "CONTRACT_HASH",
    "CONTRACT_ID",
    "CONTRACT_SPEC",
    "ContractError",
    "DIRECT_ROUTES",
    "HISTORICAL_FEATURE_WIDTHS",
    "LOCAL_FEATURE_WIDTH",
    "LOCAL_MODEL_INPUT_WIDTH",
    "MISSING_MASK_POLICY",
    "ROUTES",
    "ROLLOUT_STATE",
    "TARGET_SEMANTICS",
    "assert_valid_input_contract_metadata",
    "assert_valid_result_checkpoint_pair",
    "assert_valid_run_metadata",
    "boundary_component_encoding",
    "build_artifact_metadata",
    "build_checkpoint_metadata",
    "build_result_metadata",
    "canonical_component_keys",
    "canonical_component_slots",
    "canonical_json",
    "canonicalize_boundary_components",
    "component_slot_map",
    "contract_snapshot",
    "feature_layout",
    "is_sha256",
    "load_contract_snapshot",
    "make_cuda_determinism_policy",
    "pack_boundary_component_set",
    "route_contract",
    "route_width",
    "sha256_bytes",
    "sha256_file",
    "sha256_json",
    "sha256_text",
    "target_semantics",
    "validate_contract_snapshot",
    "validate_checkpoint_payload",
    "validate_cuda_determinism_policy",
    "validate_input_contract_metadata",
    "validate_packed_boundary_component_set",
    "validate_result_and_checkpoint",
    "validate_result_checkpoint_pair",
    "validate_result_metadata",
    "validate_run_metadata",
    "write_contract_snapshot",
]


def boundary_component_encoding() -> dict[str, Any]:
    """Return a defensive copy of the public boundary encoding definition."""

    return _deepcopy(BOUNDARY_COMPONENT_ENCODING)
