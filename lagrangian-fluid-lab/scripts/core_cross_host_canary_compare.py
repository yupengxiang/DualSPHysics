#!/usr/bin/env python3
"""Compare two ``core.cross_host_canary.v1`` reports.

The canary stores SHA-256 digests and finite summary statistics for its tensors;
it does not store the tensor elements.  This comparator therefore makes exact
identity, version, input, stage-order, digest, and summary comparisons, while
refusing to invent an elementwise maximum error from unequal digests.  A
digest mismatch is reported as requiring a controlled element trace.  The
20-step diagnostic remains separate from the full 835-frame reproduction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from numbers import Integral, Real
from pathlib import Path
import re
import sys
from typing import Any

import numpy as np


REPORT_SCHEMA = "core.cross_host_canary.v1"
COMPARISON_SCHEMA = "core.cross_host_canary_comparison.v1"
ELEMENT_TRACE_SCHEMA = "core.cross_host_canary.element_trace.v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
POSITION_ATOL_M = 1.0e-5
VELOCITY_ATOL_MPS = 1.0e-4
RELATIVE_TOLERANCE = 1.0e-4

# These are the stable runtime fields. Host-local executable paths, hostnames,
# UUIDs, device names, capabilities, and memory are reported separately and
# are intentionally not treated as matched-stack identity.
SOFTWARE_ENVIRONMENT_FIELDS = (
    "python",
    "torch_version",
    "torch_cuda_version",
    "requested_device",
    "cublas_workspace_config",
    "cuda_launch_blocking",
    "deterministic_requested",
    "deterministic_algorithms_enabled",
    "deterministic_warn_only",
    "cudnn_deterministic",
    "cudnn_benchmark",
    "torch_tf32_cudnn",
    "torch_tf32_matmul",
)

REQUIRED_BUNDLE_DIGESTS = ("manifest", "checkpoint", "core_models")
REQUIRED_CASE_IDENTITY = (
    "physical_case_id",
    "lineage_group_id",
    "family",
    "split",
    "hdf5_sha256_declared",
    "known_inputs_sha256",
)
DIGEST_STAT_FIELDS = ("min", "max", "mean", "rms", "max_abs")
DIGEST_FIELDS = ("sha256", "dtype", "shape", "finite", *DIGEST_STAT_FIELDS)

MEASUREMENT_LIMITS = {
    "exactly_computable_from_current_report": [
        "report schema/status/completed-step identity",
        "model, manifest, checkpoint, module, case, and known-input hash identity",
        "stable software/runtime version and deterministic-flag identity",
        "initial and per-step time equality",
        "digest equality, dtype, shape, finite flag, and finite summary-statistic deltas",
        "first differing recorded stage in the ordered CPU/encoder/aggregate/output trace",
    ],
    "not_computable_from_current_report": [
        "elementwise maximum position or velocity error when a digest differs",
        "the index or particle responsible for a digest mismatch",
        "a distribution or percentile of elementwise errors",
        "whether an unequal graph aggregate came from message-MLP arithmetic or reduction order",
    ],
    "controlled_output_needed_for_elementwise_error": [
        "emit raw position/velocity or a fixed, documented full-field element trace for each compared frame",
        "emit the fixed chunk/layer message tensor plus reduction numerator and valid-count before aggregate",
        "emit normalized prediction and prior-restored displacement/velocity tensors with the same index map",
    ],
}


ELEMENT_STATE_FIELDS = ("particle_id", "particle_zone", "mass", "valid")
ELEMENT_IDENTITY_FIELDS = (
    "schema",
    "case_id",
    "model_kind",
    "maximum_steps",
    "expected_frames",
    "chunk_size",
)
ELEMENT_TRACE_MAP_ROLES = (
    "node.destination_index",
    "node.source_index",
    "node.destination_position",
    "edge.neighbor_index",
    "edge.valid_mask",
    "edge.source_position",
    "edge.destination_index_valid",
    "edge.neighbor_index_valid",
    "edge.slot_index_valid",
)
ELEMENT_TRACE_NUMERIC_ROLES = (
    "edge.input_valid_edges",
    "message.raw_valid_edges",
    "aggregate.values",
    "update.updated_node_embedding",
)


def _element_side_summary(path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path) if path.is_file() else None,
        "schema": metadata.get("schema"),
        "status": metadata.get("status"),
        "case_id": metadata.get("case_id"),
        "model_kind": metadata.get("model_kind"),
        "completed_steps": metadata.get("completed_steps"),
        "expected_frames": metadata.get("expected_frames"),
        "array_store": metadata.get("array_store", {}).get("sha256")
        if isinstance(metadata.get("array_store"), dict) else None,
    }


def _finite_or_none(value: float) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def _array_index(array: np.ndarray, flat_index: int) -> list[int]:
    if array.ndim == 0:
        return []
    return [int(item) for item in np.unravel_index(int(flat_index), array.shape)]


def _element_array_error(
    left: Any,
    right: Any,
    *,
    path: str,
    atol: float | None = None,
    rtol: float | None = None,
    exact_required: bool = False,
) -> dict[str, Any]:
    """Compare captured arrays and calculate finite elementwise metrics.

    ``left`` is the reference side for relative and registered-tolerance
    calculations.  The comparator never silently broadcasts or flattens
    arrays with different shapes.
    """
    a, b = np.asarray(left), np.asarray(right)
    result: dict[str, Any] = {
        "path": path,
        "shape_equal": a.shape == b.shape,
        "dtype_equal": a.dtype == b.dtype,
        "left_dtype": str(a.dtype),
        "right_dtype": str(b.dtype),
        "left_shape": [int(item) for item in a.shape],
        "right_shape": [int(item) for item in b.shape],
        "exact_equal": False,
        "finite": False,
    }
    if a.shape != b.shape:
        return result
    if a.dtype.kind in "fc" and not np.isfinite(a).all():
        result["left_finite"] = False
        result["right_finite"] = bool(np.isfinite(b).all()) if b.dtype.kind in "fc" else True
        return result
    if b.dtype.kind in "fc" and not np.isfinite(b).all():
        result["left_finite"] = True
        result["right_finite"] = False
        return result
    result["left_finite"] = True
    result["right_finite"] = True
    result["finite"] = True
    exact = bool(np.array_equal(a, b))
    result["exact_equal"] = exact
    if exact_required or a.dtype.kind in "biu" or b.dtype.kind in "biu":
        result["max_abs_error"] = 0.0 if exact else None
        result["max_relative_error"] = 0.0 if exact else None
        result["relative_error_unbounded"] = False
        result["violation_count"] = 0 if exact else None
        result["max_tolerance_ratio"] = 0.0 if exact else None
        result["argmax_index"] = None
        return result

    af = np.asarray(a, dtype=np.float64)
    bf = np.asarray(b, dtype=np.float64)
    difference = np.abs(bf - af)
    if difference.size == 0:
        result.update({
            "max_abs_error": 0.0,
            "mean_abs_error": 0.0,
            "rms_error": 0.0,
            "max_relative_error": 0.0,
            "relative_error_unbounded": False,
            "argmax_index": None,
        })
    else:
        flat_index = int(np.argmax(difference))
        reference_abs = np.abs(af)
        nonzero = reference_abs > 0.0
        unbounded = bool(np.any((~nonzero) & (difference > 0.0)))
        if np.any(nonzero):
            max_relative = float(np.max(difference[nonzero] / reference_abs[nonzero]))
        else:
            max_relative = 0.0
        result.update({
            "max_abs_error": float(np.max(difference)),
            "mean_abs_error": float(np.mean(difference)),
            "rms_error": float(np.sqrt(np.mean((bf - af) ** 2))),
            "max_relative_error": None if unbounded else max_relative,
            "relative_error_unbounded": unbounded,
            "argmax_index": _array_index(a, flat_index),
        })
    if atol is not None and rtol is not None:
        limit = float(atol) + float(rtol) * np.abs(af)
        violation = difference > limit
        ratio = np.divide(difference, limit, out=np.zeros_like(difference), where=limit > 0.0)
        result["atol"] = float(atol)
        result["rtol"] = float(rtol)
        result["violation_count"] = int(np.count_nonzero(violation))
        result["max_tolerance_ratio"] = _finite_or_none(float(np.max(ratio))) if ratio.size else 0.0
    else:
        result["violation_count"] = None
        result["max_tolerance_ratio"] = None
    return result


def _load_element_metadata(path: Path) -> tuple[dict[str, Any], Path, list[str]]:
    errors: list[str] = []
    try:
        metadata = json.loads(path.read_text(), parse_constant=_reject_constant)
    except Exception as error:  # pragma: no cover - filesystem/CLI path
        return {}, path, [f"load_element_trace:{path}:{type(error).__name__}:{error}"]
    if not isinstance(metadata, dict):
        return {}, path, [f"invalid_element_trace_root:{path}"]
    if metadata.get("schema") != ELEMENT_TRACE_SCHEMA:
        errors.append(f"invalid_element_trace_schema:{path}")
    if metadata.get("status") != "complete":
        errors.append(f"incomplete_element_trace:{path}")
    store = metadata.get("array_store")
    if not isinstance(store, dict):
        errors.append(f"missing_element_array_store:{path}")
        return metadata, path, errors
    store_ref = store.get("path")
    if not isinstance(store_ref, str) or not store_ref:
        errors.append(f"invalid_element_array_path:{path}")
        return metadata, path, errors
    store_path = Path(store_ref)
    if not store_path.is_absolute():
        store_path = path.parent / store_path
    store_path = store_path.resolve()
    if not store_path.is_file():
        errors.append(f"missing_element_array_file:{store_path}")
    elif not _valid_sha(store.get("sha256")):
        errors.append(f"invalid_element_array_sha:{path}")
    elif _sha256(store_path) != store.get("sha256"):
        errors.append(f"element_array_sha_mismatch:{path}")
    arrays = store.get("arrays")
    if not isinstance(arrays, dict) or not arrays:
        errors.append(f"missing_element_array_specs:{path}")
    else:
        for name, spec in arrays.items():
            if not isinstance(name, str) or not name or not isinstance(spec, dict):
                errors.append(f"invalid_element_array_spec:{path}:{name}")
                continue
            if not _valid_sha(spec.get("sha256")) or not isinstance(spec.get("dtype"), str):
                errors.append(f"invalid_element_array_digest:{path}:{name}")
            shape = spec.get("shape")
            if not isinstance(shape, list) or not all(_is_integral(item) and int(item) >= 0 for item in shape):
                errors.append(f"invalid_element_array_shape:{path}:{name}")
    if not isinstance(metadata.get("steps"), list):
        errors.append(f"missing_element_steps:{path}")
    state_arrays = metadata.get("state_arrays")
    if not isinstance(state_arrays, dict):
        errors.append(f"missing_element_state_arrays:{path}")
    return metadata, store_path, errors


def _element_identity(
    left: dict[str, Any],
    right: dict[str, Any],
    left_report: dict[str, Any],
    right_report: dict[str, Any],
) -> dict[str, Any]:
    mismatches: list[str] = []
    errors: list[str] = []
    transparency: dict[str, Any] = {}
    for key in ELEMENT_IDENTITY_FIELDS:
        left_value = left.get("canary_schema") if key == "schema" else left.get(key)
        right_value = right.get("canary_schema") if key == "schema" else right.get(key)
        left_report_value = left_report.get("schema") if key == "schema" else left_report.get(key)
        right_report_value = right_report.get("schema") if key == "schema" else right_report.get(key)
        if left_value != right_value:
            mismatches.append(key)
        if left_value != left_report_value:
            mismatches.append(f"left:{key}:canary")
        if right_value != right_report_value:
            mismatches.append(f"right:{key}:canary")
    for key in ("maximum_steps", "expected_frames", "chunk_size"):
        if not _is_integral(left.get(key)) or int(left.get(key)) < 1:
            errors.append(f"invalid_element_identity:left:{key}")
        if not _is_integral(right.get(key)) or int(right.get(key)) < 1:
            errors.append(f"invalid_element_identity:right:{key}")
    for label, metadata, report in (("left", left, left_report), ("right", right, right_report)):
        witness = metadata.get("capture_transparency")
        witness_result = witness.get("original_model_forward_vs_capture_forward") if isinstance(witness, dict) else None
        witness_ok = bool(
            isinstance(witness, dict)
            and witness.get("schema") == "core.cross_host_canary.capture_transparency.v1"
            and witness.get("step") == 0
            and isinstance(witness_result, dict)
            and witness_result.get("exact_equal") is True
            and witness_result.get("max_abs_error") == 0.0
        )
        transparency[label] = {
            "present": isinstance(witness, dict),
            "schema": witness.get("schema") if isinstance(witness, dict) else None,
            "exact_equal": witness_result.get("exact_equal") if isinstance(witness_result, dict) else None,
            "max_abs_error": witness_result.get("max_abs_error") if isinstance(witness_result, dict) else None,
            "passed": witness_ok,
        }
        if not witness_ok:
            errors.append(f"invalid_capture_transparency:{label}")
        meta_bundle = metadata.get("bundle")
        report_bundle = report.get("bundle")
        if not isinstance(meta_bundle, dict) or not isinstance(report_bundle, dict):
            errors.append(f"missing_element_bundle:{label}")
            continue
        for section in ("expected", "observed"):
            a = meta_bundle.get("identity", {}).get(section) if isinstance(meta_bundle.get("identity"), dict) else None
            b = report_bundle.get("identity", {}).get(section) if isinstance(report_bundle.get("identity"), dict) else None
            if a != b:
                mismatches.append(f"{label}:bundle:{section}:canary")
        meta_case, report_case = metadata.get("case"), report.get("case")
        if not isinstance(meta_case, dict) or not isinstance(report_case, dict):
            errors.append(f"missing_element_case:{label}")
        elif meta_case != report_case:
            # Report paths and unrelated provenance are intentionally absent
            # from the sidecar case identity; compare only registered fields.
            for key in REQUIRED_CASE_IDENTITY:
                if meta_case.get(key) != report_case.get(key):
                    mismatches.append(f"{label}:case:{key}:canary")
    return {
        "passed": not mismatches and not errors,
        "mismatches": sorted(set(mismatches)),
        "errors": errors,
        "capture_transparency": transparency,
    }


def _store_array(store: Any, metadata: dict[str, Any], name: Any, cache: dict[str, np.ndarray], errors: list[str]) -> np.ndarray | None:
    if not isinstance(name, str):
        errors.append("invalid_element_array_name")
        return None
    if name in cache:
        return cache[name]
    specs = metadata.get("array_store", {}).get("arrays", {})
    spec = specs.get(name) if isinstance(specs, dict) else None
    if not isinstance(spec, dict):
        errors.append(f"missing_element_array_spec:{name}")
        return None
    try:
        if name not in store.files:
            errors.append(f"missing_element_array:{name}")
            return None
        value = np.ascontiguousarray(np.asarray(store[name]))
    except Exception as error:  # pragma: no cover - corrupt artifact path
        errors.append(f"read_element_array:{name}:{type(error).__name__}:{error}")
        return None
    expected_shape = spec.get("shape")
    if expected_shape != [int(item) for item in value.shape]:
        errors.append(f"element_array_shape_mismatch:{name}")
    if spec.get("dtype") != str(value.dtype):
        errors.append(f"element_array_dtype_mismatch:{name}")
    if _valid_sha(spec.get("sha256")):
        observed = hashlib.sha256(value.view(np.uint8)).hexdigest()
        if observed != spec.get("sha256"):
            errors.append(f"element_array_digest_mismatch:{name}")
    else:
        errors.append(f"invalid_element_array_sha:{name}")
    if value.dtype.kind in "fc" and not np.isfinite(value).all():
        errors.append(f"nonfinite_element_array:{name}")
    cache[name] = value
    return value


def _sidecar_role(metadata: dict[str, Any], step_index: int, role: str) -> str | None:
    steps = metadata.get("steps")
    if not isinstance(steps, list) or step_index >= len(steps) or not isinstance(steps[step_index], dict):
        return None
    arrays = steps[step_index].get("arrays")
    return arrays.get(role) if isinstance(arrays, dict) else None


def _sidecar_layer_role(metadata: dict[str, Any], step_index: int, layer_index: int, role: str) -> str | None:
    steps = metadata.get("steps")
    if not isinstance(steps, list) or step_index >= len(steps) or not isinstance(steps[step_index], dict):
        return None
    layers = steps[step_index].get("layers")
    if not isinstance(layers, list):
        return None
    for layer in layers:
        if isinstance(layer, dict) and layer.get("layer") == layer_index:
            arrays = layer.get("arrays")
            return arrays.get(role) if isinstance(arrays, dict) else None
    return None


def _compare_element_traces(
    left_path: Path,
    right_path: Path,
    left_report: dict[str, Any],
    right_report: dict[str, Any],
) -> dict[str, Any]:
    left_meta, left_store_path, left_errors = _load_element_metadata(left_path)
    right_meta, right_store_path, right_errors = _load_element_metadata(right_path)
    load_errors = left_errors + right_errors
    identity = _element_identity(left_meta, right_meta, left_report, right_report)
    all_errors = load_errors + identity["errors"]
    result: dict[str, Any] = {
        "schema": ELEMENT_TRACE_SCHEMA,
        "left": _element_side_summary(left_path, left_meta) if left_meta else {"path": str(left_path)},
        "right": _element_side_summary(right_path, right_meta) if right_meta else {"path": str(right_path)},
        "identity": identity,
        "errors": all_errors,
        "state": {"frames": [], "identity": {"passed": False, "mismatches": []}},
        "steps": [],
        "first_difference": None,
        "tolerance_status": "undetermined_invalid_element_trace",
        "tolerance_passed": False,
        "passed": False,
        "scope": "20-step diagnostic only; not an 835-frame reproduction",
    }
    if all_errors:
        return result
    try:
        left_store = np.load(left_store_path, allow_pickle=False)
        right_store = np.load(right_store_path, allow_pickle=False)
    except Exception as error:  # pragma: no cover - corrupt artifact path
        result["errors"].append(f"open_element_array_store:{type(error).__name__}:{error}")
        return result

    left_cache: dict[str, np.ndarray] = {}
    right_cache: dict[str, np.ndarray] = {}
    compare_errors: list[str] = []
    first_difference: dict[str, Any] | None = None
    state_metrics: dict[str, list[dict[str, Any]]] = {"position": [], "velocity": []}
    try:
        left_state_names = left_meta["state_arrays"]
        right_state_names = right_meta["state_arrays"]
        state_identity: dict[str, Any] = {"passed": True, "fields": {}, "mismatches": []}
        for field in ("frame_time_s", "position", "velocity", *ELEMENT_STATE_FIELDS):
            left_name, right_name = left_state_names.get(field), right_state_names.get(field)
            if not isinstance(left_name, str) or not isinstance(right_name, str):
                state_identity["passed"] = False
                state_identity["mismatches"].append(f"missing:{field}")
                continue
            la = _store_array(left_store, left_meta, left_name, left_cache, compare_errors)
            ra = _store_array(right_store, right_meta, right_name, right_cache, compare_errors)
            if la is None or ra is None:
                state_identity["passed"] = False
                continue
            exact_required = field not in ("position", "velocity")
            metric = _element_array_error(la, ra, path=f"state.{field}", exact_required=exact_required)
            state_identity["fields"][field] = metric
            # Position/velocity are the values being measured under the
            # registered tolerances; they are allowed to differ here.
            if exact_required and not metric["exact_equal"]:
                state_identity["passed"] = False
                state_identity["mismatches"].append(field)
        result["state"]["identity"] = state_identity

        left_position = _store_array(left_store, left_meta, left_state_names.get("position"), left_cache, compare_errors)
        right_position = _store_array(right_store, right_meta, right_state_names.get("position"), right_cache, compare_errors)
        left_velocity = _store_array(left_store, left_meta, left_state_names.get("velocity"), left_cache, compare_errors)
        right_velocity = _store_array(right_store, right_meta, right_state_names.get("velocity"), right_cache, compare_errors)
        if left_position is None or right_position is None or left_velocity is None or right_velocity is None:
            result["errors"].extend(compare_errors)
            return result
        if left_position.ndim != 3 or left_velocity.ndim != 3 or left_position.shape[0] != left_velocity.shape[0]:
            result["errors"].append("invalid_element_state_shape")
            return result
        expected_frames = int(left_report.get("expected_frames", 0))
        if left_position.shape[0] != expected_frames or right_position.shape != left_position.shape:
            result["errors"].append("element_state_frame_shape_mismatch")
            return result
        for frame in range(expected_frames):
            pmetric = _element_array_error(
                left_position[frame], right_position[frame],
                path=f"state.position[{frame}]", atol=POSITION_ATOL_M, rtol=RELATIVE_TOLERANCE,
            )
            vmetric = _element_array_error(
                left_velocity[frame], right_velocity[frame],
                path=f"state.velocity[{frame}]", atol=VELOCITY_ATOL_MPS, rtol=RELATIVE_TOLERANCE,
            )
            state_metrics["position"].append(pmetric)
            state_metrics["velocity"].append(vmetric)
        result["state"]["frames"] = [
            {"frame": frame, "position": state_metrics["position"][frame], "velocity": state_metrics["velocity"][frame]}
            for frame in range(expected_frames)
        ]
        result["state"]["max_position_abs_error_m"] = max(
            metric.get("max_abs_error", 0.0) or 0.0 for metric in state_metrics["position"]
        )
        result["state"]["max_velocity_abs_error_mps"] = max(
            metric.get("max_abs_error", 0.0) or 0.0 for metric in state_metrics["velocity"]
        )
        result["state"]["position_violation_count"] = sum(metric.get("violation_count") or 0 for metric in state_metrics["position"])
        result["state"]["velocity_violation_count"] = sum(metric.get("violation_count") or 0 for metric in state_metrics["velocity"])

        left_steps, right_steps = left_meta.get("steps"), right_meta.get("steps")
        if not isinstance(left_steps, list) or not isinstance(right_steps, list) or len(left_steps) != len(right_steps):
            result["errors"].append("element_step_count_mismatch")
            return result

        def record_first(path: str, metric: dict[str, Any], *, step: int, frame: int, category: str) -> None:
            nonlocal first_difference
            if first_difference is None and not metric.get("exact_equal", False):
                first_difference = {"category": category, "step": step, "frame": frame, "path": path, "evidence": metric}

        for step_index in range(len(left_steps)):
            frame = step_index + 1
            step_result: dict[str, Any] = {"step": step_index, "frame": frame, "stages": [], "first_difference": None}
            ordered_roles: list[tuple[str, str, bool]] = [
                ("trace.normalized_features", "trace", False),
                ("trace.encoder.values", "trace", False),
            ]
            for layer_index in range(2):
                for role in ELEMENT_TRACE_MAP_ROLES:
                    ordered_roles.append((role, f"layer[{layer_index}]", True))
                for role in ELEMENT_TRACE_NUMERIC_ROLES:
                    ordered_roles.append((role, f"layer[{layer_index}]", False))
            ordered_roles.extend([
                ("trace.head.input", "trace", False),
                ("trace.head.raw_output", "trace", False),
                ("trace.head.normalized_output", "trace", False),
                ("trace.head.target_space", "trace", False),
                ("trace.prior", "trace", False),
                ("trace.prediction_with_prior", "trace", False),
            ])
            for role, section, exact_required in ordered_roles:
                if section == "trace":
                    left_name = _sidecar_role(left_meta, step_index, role)
                    right_name = _sidecar_role(right_meta, step_index, role)
                else:
                    layer_index = int(section[6:-1])
                    left_name = _sidecar_layer_role(left_meta, step_index, layer_index, role)
                    right_name = _sidecar_layer_role(right_meta, step_index, layer_index, role)
                if left_name is None and right_name is None:
                    continue
                if left_name is None or right_name is None:
                    metric = {"path": f"steps[{step_index}].{section}.{role}", "exact_equal": False, "missing_side": True}
                    compare_errors.append(f"missing_element_trace_role:{metric['path']}")
                else:
                    la = _store_array(left_store, left_meta, left_name, left_cache, compare_errors)
                    ra = _store_array(right_store, right_meta, right_name, right_cache, compare_errors)
                    metric = _element_array_error(
                        la, ra, path=f"steps[{step_index}].{section}.{role}", exact_required=exact_required
                    ) if la is not None and ra is not None else {
                        "path": f"steps[{step_index}].{section}.{role}", "exact_equal": False,
                    }
                step_result["stages"].append(metric)
                record_first(metric["path"], metric, step=step_index, frame=frame, category="element_trace")
            # Commit is after head/prior and is retained as the final stage.
            for field, metrics in (("position", state_metrics["position"]), ("velocity", state_metrics["velocity"])):
                metric = metrics[frame]
                commit_metric = dict(metric)
                commit_metric["path"] = f"steps[{step_index}].commit.{field}"
                step_result["stages"].append(commit_metric)
                record_first(commit_metric["path"], commit_metric, step=step_index, frame=frame, category="commit")
            step_result["first_difference"] = next(
                (metric for metric in step_result["stages"] if not metric.get("exact_equal", False)), None
            )
            result["steps"].append(step_result)

        result["first_difference"] = first_difference
        result["errors"].extend(compare_errors)
        finite_state = all(
            metric.get("finite", False)
            for field_metrics in state_metrics.values() for metric in field_metrics
        )
        violations = result["state"]["position_violation_count"] + result["state"]["velocity_violation_count"]
        if not identity["passed"] or not state_identity["passed"] or compare_errors or not finite_state:
            result["tolerance_status"] = "undetermined_invalid_element_trace"
        elif violations:
            result["tolerance_status"] = "violated_registered_tolerance"
        else:
            result["tolerance_status"] = "within_registered_tolerance"
        result["tolerance_passed"] = result["tolerance_status"] == "within_registered_tolerance"
        result["exact_match"] = bool(
            identity["passed"] and not compare_errors and finite_state
            and result["first_difference"] is None
        )
        result["passed"] = bool(
            identity["passed"] and state_identity["passed"] and not compare_errors
            and finite_state and result["tolerance_passed"]
        )
    finally:
        left_store.close()
        right_store.close()
    return result


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _load_report(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(), parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("report root must be an object")
    return value


def _is_real(value: Any) -> bool:
    return isinstance(value, (Real,)) and not isinstance(value, (bool,))


def _is_integral(value: Any) -> bool:
    return isinstance(value, Integral) and not isinstance(value, bool)


def _finite(value: Any) -> bool:
    return _is_real(value) and math.isfinite(float(value))


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _digest_summary(value: Any) -> dict[str, Any] | None:
    """Return a validated digest, or ``None`` for malformed input.

    Validation is intentionally strict: a missing summary must not be treated
    as equal merely because both reports omitted it.
    """
    if not isinstance(value, dict):
        return None
    if set(DIGEST_FIELDS) - set(value):
        return None
    if not _valid_sha(value.get("sha256")) or not isinstance(value.get("dtype"), str):
        return None
    shape = value.get("shape")
    if (
        not isinstance(shape, list)
        or not shape
        or not all(_is_integral(item) and int(item) >= 0 for item in shape)
    ):
        return None
    if not isinstance(value.get("finite"), bool):
        return None
    for key in DIGEST_STAT_FIELDS:
        item = value.get(key)
        if value["finite"]:
            if item is not None and not _finite(item):
                return None
        elif item is not None:
            return None
    if value["finite"] and value.get("max_abs") is not None and float(value["max_abs"]) < 0:
        return None
    if value["finite"] and value.get("rms") is not None and float(value["rms"]) < 0:
        return None
    return value


def _summary_delta(left: dict[str, Any], right: dict[str, Any]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for key in DIGEST_STAT_FIELDS:
        a, b = left.get(key), right.get(key)
        if a is None or b is None:
            result[key] = None if a == b else None
        else:
            result[key] = float(b) - float(a)
    return result


def _compare_digest(
    left: Any,
    right: Any,
    *,
    path: str,
    errors: list[str],
) -> dict[str, Any]:
    left_value = _digest_summary(left)
    right_value = _digest_summary(right)
    if left_value is None:
        errors.append(f"invalid_digest:left:{path}")
    if right_value is None:
        errors.append(f"invalid_digest:right:{path}")
    if left_value is None or right_value is None:
        return {
            "exact_equal": False,
            "sha_equal": False,
            "metadata_equal": False,
            "summary_equal": False,
            "elementwise_error_available": False,
            "max_elementwise_abs_error": None,
            "path": path,
        }

    metadata_equal = (
        left_value["dtype"] == right_value["dtype"]
        and left_value["shape"] == right_value["shape"]
    )
    sha_equal = left_value["sha256"] == right_value["sha256"]
    summary_equal = all(left_value.get(key) == right_value.get(key) for key in DIGEST_STAT_FIELDS)
    finite_equal = left_value["finite"] == right_value["finite"]
    if sha_equal and (not metadata_equal or not summary_equal or not finite_equal):
        errors.append(f"digest_self_inconsistent:{path}")
    exact_equal = bool(sha_equal and metadata_equal and summary_equal and finite_equal)
    return {
        "path": path,
        "exact_equal": exact_equal,
        "sha_equal": sha_equal,
        "metadata_equal": metadata_equal,
        "summary_equal": summary_equal,
        "elementwise_error_available": exact_equal,
        # Equal digests are the only case in which this report can establish
        # zero error. Unequal digests do not provide an elementwise bound.
        "max_elementwise_abs_error": 0.0 if exact_equal else None,
        "left_sha256": left_value["sha256"],
        "right_sha256": right_value["sha256"],
        "left_dtype": left_value["dtype"],
        "right_dtype": right_value["dtype"],
        "left_shape": left_value["shape"],
        "right_shape": right_value["shape"],
        "summary_delta_right_minus_left": _summary_delta(left_value, right_value),
        "left_finite": left_value["finite"],
        "right_finite": right_value["finite"],
    }


def _scalar_compare(left: Any, right: Any, *, path: str, errors: list[str]) -> dict[str, Any]:
    valid = _finite(left) and _finite(right)
    if not valid:
        errors.append(f"invalid_scalar:{path}")
    equal = bool(valid and float(left) == float(right))
    return {
        "equal": equal,
        "left": left,
        "right": right,
        "delta_right_minus_left": float(right) - float(left) if valid else None,
    }


def _module_hashes(environment: Any, key: str, *, side: str, errors: list[str]) -> dict[str, str]:
    values = environment.get(key) if isinstance(environment, dict) else None
    if not isinstance(values, list):
        errors.append(f"missing_environment:{side}:{key}")
        return {}
    result: dict[str, str] = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("module"), str) or not _valid_sha(item.get("sha256")):
            errors.append(f"invalid_environment_module:{side}:{key}")
            continue
        result[item["module"]] = item["sha256"]
    return result


def _driver_version(environment: Any, *, side: str, errors: list[str]) -> str | None:
    query = environment.get("driver_query") if isinstance(environment, dict) else None
    if not isinstance(query, dict) or not query.get("available"):
        errors.append(f"missing_environment:{side}:driver_query")
        return None
    text = query.get("stdout")
    if not isinstance(text, str) or not text.strip():
        errors.append(f"invalid_environment:{side}:driver_query")
        return None
    first = text.strip().splitlines()[0].split(",", 1)[0].strip()
    if not first:
        errors.append(f"invalid_environment:{side}:driver_version")
        return None
    return first


def _report_side_summary(report: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "schema": report.get("schema"),
        "status": report.get("status"),
        "case_id": report.get("case_id"),
        "model_kind": report.get("model_kind"),
        "completed_steps": report.get("completed_steps"),
        "expected_frames": report.get("expected_frames"),
    }


def _compare_identity(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    errors: list[str],
) -> tuple[dict[str, Any], list[str]]:
    mismatches: list[str] = []
    for key in ("schema", "case_id", "model_kind", "maximum_steps", "expected_frames", "chunk_size"):
        a, b = left.get(key), right.get(key)
        equal = a == b
        if not equal:
            mismatches.append(key)

    for label, report in (("left", left), ("right", right)):
        if report.get("schema") != REPORT_SCHEMA:
            errors.append(f"invalid_schema:{label}")
        if report.get("status") != "complete":
            errors.append(f"incomplete_report:{label}")
        if not _is_integral(report.get("maximum_steps")) or int(report["maximum_steps"]) < 1:
            errors.append(f"invalid_maximum_steps:{label}")
        if not _is_integral(report.get("expected_frames")) or int(report["expected_frames"]) < 2:
            errors.append(f"invalid_expected_frames:{label}")
        elif int(report["expected_frames"]) != int(report.get("maximum_steps", -1)) + 1:
            errors.append(f"invalid_frame_identity:{label}")
        if not _is_integral(report.get("completed_steps")) or int(report["completed_steps"]) < 0:
            errors.append(f"invalid_completed_steps:{label}")
        elif int(report["completed_steps"]) != int(report.get("maximum_steps", -2)):
            errors.append(f"incomplete_steps:{label}")
        if report.get("autonomous") is not True:
            errors.append(f"invalid_autonomous_flag:{label}")
        if report.get("future_state_inputs") is not False:
            errors.append(f"future_state_inputs:{label}")

        protocol = report.get("comparison_protocol")
        if not isinstance(protocol, dict) or protocol.get("tolerances_frozen") is not True:
            errors.append(f"invalid_comparison_protocol:{label}")

        read_log = report.get("read_log")
        if not isinstance(read_log, list):
            errors.append(f"invalid_read_log:{label}")
        else:
            for entry in read_log:
                if not isinstance(entry, list) or len(entry) != 2 or entry[0] != report.get("case_id") or entry[1] != 0:
                    errors.append(f"future_or_invalid_read:{label}")
                    break

    left_protocol, right_protocol = left.get("comparison_protocol"), right.get("comparison_protocol")
    protocol_fields = (
        "schema",
        "identity_time_mass_valid",
        "position_absolute_tolerance_m",
        "velocity_absolute_tolerance_mps",
        "relative_tolerance",
        "tolerances_frozen",
    )
    protocol_comparison: dict[str, Any] = {}
    if isinstance(left_protocol, dict) and isinstance(right_protocol, dict):
        for key in protocol_fields:
            equal = left_protocol.get(key) == right_protocol.get(key)
            protocol_comparison[key] = {"equal": equal, "left": left_protocol.get(key), "right": right_protocol.get(key)}
            if not equal:
                mismatches.append(f"comparison_protocol:{key}")

    bundle_checks: dict[str, Any] = {}
    for label, report in (("left", left), ("right", right)):
        bundle = report.get("bundle")
        identity = bundle.get("identity") if isinstance(bundle, dict) else None
        expected = identity.get("expected") if isinstance(identity, dict) else None
        observed = identity.get("observed") if isinstance(identity, dict) else None
        if not isinstance(expected, dict) or not isinstance(observed, dict):
            errors.append(f"missing_bundle_identity:{label}")
            continue
        checks: dict[str, Any] = {}
        for key in REQUIRED_BUNDLE_DIGESTS:
            expected_hash = expected.get(key)
            observed_item = observed.get(key)
            observed_hash = observed_item.get("sha256") if isinstance(observed_item, dict) else None
            valid = _valid_sha(expected_hash) and _valid_sha(observed_hash)
            equal = bool(valid and expected_hash == observed_hash)
            checks[key] = {"valid": valid, "equal": equal, "expected": expected_hash, "observed": observed_hash}
            if not valid:
                errors.append(f"invalid_bundle_hash:{label}:{key}")
            elif not equal:
                errors.append(f"bundle_observed_mismatch:{label}:{key}")
        bundle_checks[label] = checks

    left_case, right_case = left.get("case"), right.get("case")
    case_comparison: dict[str, Any] = {}
    if not isinstance(left_case, dict) or not isinstance(right_case, dict):
        errors.append("missing_case_identity")
    else:
        for key in REQUIRED_CASE_IDENTITY:
            equal = left_case.get(key) == right_case.get(key)
            case_comparison[key] = {"equal": equal, "left": left_case.get(key), "right": right_case.get(key)}
            if not equal:
                mismatches.append(f"case:{key}")
        for label, case in (("left", left_case), ("right", right_case)):
            for key in ("hdf5_sha256_declared", "known_inputs_sha256"):
                if not _valid_sha(case.get(key)):
                    errors.append(f"invalid_case_hash:{label}:{key}")

    identity = {
        "report_fields": {
            key: {"equal": left.get(key) == right.get(key), "left": left.get(key), "right": right.get(key)}
            for key in ("schema", "case_id", "model_kind", "maximum_steps", "expected_frames", "chunk_size")
        },
        "protocol": protocol_comparison,
        "bundle": bundle_checks,
        "case": case_comparison,
        "mismatches": mismatches,
        "passed": not mismatches and not any(item.startswith(("invalid_", "missing_", "incomplete_", "future_")) for item in errors),
    }
    return identity, mismatches


def _compare_environment(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    errors: list[str],
) -> tuple[dict[str, Any], list[str]]:
    mismatches: list[str] = []
    left_env, right_env = left.get("environment"), right.get("environment")
    if not isinstance(left_env, dict) or not isinstance(right_env, dict):
        errors.append("missing_environment")
        return {"software": {}, "hardware": {}, "mismatches": ["missing_environment"]}, ["missing_environment"]

    software: dict[str, Any] = {}
    for key in SOFTWARE_ENVIRONMENT_FIELDS:
        a, b = left_env.get(key), right_env.get(key)
        equal = a == b
        software[key] = {"equal": equal, "left": a, "right": b}
        if not equal:
            mismatches.append(f"software:{key}")

    left_driver = _driver_version(left_env, side="left", errors=errors)
    right_driver = _driver_version(right_env, side="right", errors=errors)
    driver_equal = left_driver == right_driver and left_driver is not None
    software["driver_version"] = {"equal": driver_equal, "left": left_driver, "right": right_driver}
    if not driver_equal:
        mismatches.append("software:driver_version")

    modules: dict[str, Any] = {}
    for key in ("modules_before_model", "modules_after_inputs"):
        left_hashes = _module_hashes(left_env, key, side="left", errors=errors)
        right_hashes = _module_hashes(right_env, key, side="right", errors=errors)
        module_mismatches = sorted(set(left_hashes) | set(right_hashes))
        module_mismatches = [name for name in module_mismatches if left_hashes.get(name) != right_hashes.get(name)]
        modules[key] = {
            "equal": not module_mismatches,
            "left": left_hashes,
            "right": right_hashes,
            "mismatches": module_mismatches,
        }
        if module_mismatches:
            mismatches.append(f"modules:{key}")

    left_cuda, right_cuda = left_env.get("cuda"), right_env.get("cuda")
    hardware = {
        "left": {
            "hostname": left_env.get("hostname"),
            "cuda_visible_devices": left_env.get("cuda_visible_devices"),
            "cuda": left_cuda,
            "device_name": left_cuda.get("device_name") if isinstance(left_cuda, dict) else None,
            "device_capability": left_cuda.get("device_capability") if isinstance(left_cuda, dict) else None,
        },
        "right": {
            "hostname": right_env.get("hostname"),
            "cuda_visible_devices": right_env.get("cuda_visible_devices"),
            "cuda": right_cuda,
            "device_name": right_cuda.get("device_name") if isinstance(right_cuda, dict) else None,
            "device_capability": right_cuda.get("device_capability") if isinstance(right_cuda, dict) else None,
        },
        "host_specific_fields_ignored_for_identity": [
            "hostname",
            "python_executable",
            "cuda_visible_devices",
            "cuda.device_name",
            "cuda.device_capability",
            "cuda.total_memory_bytes",
            "cuda.multi_processor_count",
        ],
    }
    environment = {
        "software": software,
        "modules": modules,
        "hardware": hardware,
        "mismatches": mismatches,
        "passed": not mismatches,
    }
    return environment, mismatches


def _compare_state(
    left: Any,
    right: Any,
    *,
    path: str,
    errors: list[str],
) -> tuple[dict[str, Any], list[str]]:
    mismatches: list[str] = []
    if not isinstance(left, dict) or not isinstance(right, dict):
        errors.append(f"missing_state:{path}")
        return {"mismatches": [path]}, [path]
    left_time, right_time = left.get("time_s"), right.get("time_s")
    if not _finite(left_time) or not _finite(right_time):
        errors.append(f"invalid_state_time:{path}")
        time_comparison = {"equal": False, "left": left_time, "right": right_time, "delta_right_minus_left": None}
    else:
        time_comparison = {
            "equal": float(left_time) == float(right_time),
            "left": left_time,
            "right": right_time,
            "delta_right_minus_left": float(right_time) - float(left_time),
        }
        if not time_comparison["equal"]:
            mismatches.append(f"{path}.time_s")
    result: dict[str, Any] = {"time_s": time_comparison}
    for field in ("position", "velocity"):
        comparison = _compare_digest(left.get(field), right.get(field), path=f"{path}.{field}", errors=errors)
        result[field] = comparison
        if not comparison["exact_equal"]:
            mismatches.append(f"{path}.{field}")
    result["mismatches"] = mismatches
    return result, mismatches


def _compare_trace(
    left: Any,
    right: Any,
    *,
    path: str,
    errors: list[str],
) -> tuple[dict[str, Any], list[str]]:
    mismatches: list[str] = []
    mismatch_counts: dict[str, int] = {}
    first: dict[str, Any] | None = None

    def record(stage: str, comparison: dict[str, Any] | None = None) -> None:
        nonlocal first
        mismatches.append(stage)
        category = stage.rsplit(".", 1)[-1]
        mismatch_counts[category] = mismatch_counts.get(category, 0) + 1
        if first is None:
            first = {"path": stage, "evidence": comparison}

    if not isinstance(left, dict) or not isinstance(right, dict):
        errors.append(f"missing_trace:{path}")
        record(path)
        return {"mismatches": mismatches, "mismatch_counts": mismatch_counts, "first_mismatch": first}, mismatches

    left_cpu, right_cpu = left.get("cpu"), right.get("cpu")
    if not isinstance(left_cpu, dict) or not isinstance(right_cpu, dict):
        errors.append(f"missing_trace_cpu:{path}")
        record(f"{path}.cpu")
    else:
        for field in ("features", "neighbors"):
            comparison = _compare_digest(
                left_cpu.get(field), right_cpu.get(field), path=f"{path}.cpu.{field}", errors=errors
            )
            if not comparison["exact_equal"]:
                record(f"{path}.cpu.{field}", comparison)
        for field in ("neighbor_diagnostics", "active_neighbor_count"):
            if left_cpu.get(field) != right_cpu.get(field):
                record(f"{path}.cpu.{field}", {"left": left_cpu.get(field), "right": right_cpu.get(field)})

    comparison = _compare_digest(
        left.get("normalized_features"),
        right.get("normalized_features"),
        path=f"{path}.normalized_features",
        errors=errors,
    )
    if not comparison["exact_equal"]:
        record(f"{path}.normalized_features", comparison)

    left_chunks, right_chunks = left.get("chunks"), right.get("chunks")
    if not isinstance(left_chunks, list) or not isinstance(right_chunks, list):
        errors.append(f"invalid_trace_chunks:{path}")
        record(f"{path}.chunks")
    else:
        if len(left_chunks) != len(right_chunks):
            record(f"{path}.chunks.length", {"left": len(left_chunks), "right": len(right_chunks)})
        for index, (left_chunk, right_chunk) in enumerate(zip(left_chunks, right_chunks)):
            chunk_path = f"{path}.chunks[{index}]"
            if not isinstance(left_chunk, dict) or not isinstance(right_chunk, dict):
                errors.append(f"invalid_trace_chunk:{chunk_path}")
                record(chunk_path)
                continue
            for field in ("start", "stop"):
                if left_chunk.get(field) != right_chunk.get(field):
                    record(f"{chunk_path}.{field}", {"left": left_chunk.get(field), "right": right_chunk.get(field)})
            # Keep this order aligned with _trace_forward: the layer
            # aggregates are produced before the head's normalized output.
            # If both differ, the earliest aggregate is the useful causal
            # boundary; checking normalized_output first would hide it.
            comparison = _compare_digest(
                left_chunk.get("encoder"),
                right_chunk.get("encoder"),
                path=f"{chunk_path}.encoder",
                errors=errors,
            ) if left_chunk.get("encoder") is not None or right_chunk.get("encoder") is not None else {
                "exact_equal": True,
                "sha_equal": True,
                "metadata_equal": True,
                "summary_equal": True,
                "elementwise_error_available": True,
                "max_elementwise_abs_error": 0.0,
                "path": f"{chunk_path}.encoder",
            }
            if not comparison["exact_equal"]:
                record(f"{chunk_path}.encoder", comparison)
            left_layers, right_layers = left_chunk.get("layers"), right_chunk.get("layers")
            if not isinstance(left_layers, list) or not isinstance(right_layers, list):
                errors.append(f"invalid_trace_layers:{chunk_path}")
                record(f"{chunk_path}.layers")
                continue
            if len(left_layers) != len(right_layers):
                record(f"{chunk_path}.layers.length", {"left": len(left_layers), "right": len(right_layers)})
            for layer_index, (left_layer, right_layer) in enumerate(zip(left_layers, right_layers)):
                layer_path = f"{chunk_path}.layers[{layer_index}]"
                if not isinstance(left_layer, dict) or not isinstance(right_layer, dict):
                    errors.append(f"invalid_trace_layer:{layer_path}")
                    record(layer_path)
                    continue
                for field in ("layer", "destination", "destination_count", "source_count", "valid_neighbor_entries"):
                    if left_layer.get(field) != right_layer.get(field):
                        record(f"{layer_path}.{field}", {"left": left_layer.get(field), "right": right_layer.get(field)})
                comparison = _compare_digest(
                    left_layer.get("aggregate"),
                    right_layer.get("aggregate"),
                    path=f"{layer_path}.aggregate",
                    errors=errors,
                )
                if not comparison["exact_equal"]:
                    record(f"{layer_path}.aggregate", comparison)
            for field in ("normalized_output", "output"):
                comparison = _compare_digest(
                    left_chunk.get(field),
                    right_chunk.get(field),
                    path=f"{chunk_path}.{field}",
                    errors=errors,
                ) if left_chunk.get(field) is not None or right_chunk.get(field) is not None else {
                    "exact_equal": True,
                    "sha_equal": True,
                    "metadata_equal": True,
                    "summary_equal": True,
                    "elementwise_error_available": True,
                    "max_elementwise_abs_error": 0.0,
                    "path": f"{chunk_path}.{field}",
                }
                if not comparison["exact_equal"]:
                    record(f"{chunk_path}.{field}", comparison)
    return {
        "trace_exact_match": not mismatches,
        "mismatches": mismatches,
        "mismatch_counts": mismatch_counts,
        "first_mismatch": first,
    }, mismatches


def compare_reports(
    left_path: Path,
    right_path: Path,
    left_element_trace_path: Path | None = None,
    right_element_trace_path: Path | None = None,
) -> dict[str, Any]:
    """Compare canary reports and optional element-trace sidecars.

    Without sidecars this retains the digest-only v1 behavior.  When both
    sidecars are supplied, native state errors are measured elementwise under
    the frozen registered tolerances; bitwise identity remains reported
    separately so a small tolerated difference is not mislabeled exact.
    """
    top_errors: list[str] = []
    try:
        left = _load_report(left_path)
    except Exception as error:  # pragma: no cover - CLI/filesystem path
        left = {}
        top_errors.append(f"load_left:{type(error).__name__}:{error}")
    try:
        right = _load_report(right_path)
    except Exception as error:  # pragma: no cover - CLI/filesystem path
        right = {}
        top_errors.append(f"load_right:{type(error).__name__}:{error}")

    errors = list(top_errors)
    identity, identity_mismatches = _compare_identity(left, right, errors=errors)
    environment, environment_mismatches = _compare_environment(left, right, errors=errors)

    initial_result: dict[str, Any] = {}
    initial_mismatches: list[str] = []
    if left and right:
        initial_result, initial_mismatches = _compare_state(
            left.get("initial_state"),
            right.get("initial_state"),
            path="initial_state",
            errors=errors,
        )

    left_steps, right_steps = left.get("steps"), right.get("steps")
    step_results: list[dict[str, Any]] = []
    step_mismatches: list[str] = []
    if not isinstance(left_steps, list) or not isinstance(right_steps, list):
        errors.append("missing_steps")
    else:
        if len(left_steps) != len(right_steps):
            step_mismatches.append("steps.length")
        for index in range(max(len(left_steps), len(right_steps))):
            if index >= len(left_steps) or index >= len(right_steps):
                step_mismatches.append(f"steps[{index}].missing_side")
                step_results.append({"index": index, "mismatches": ["missing_side"]})
                continue
            left_step, right_step = left_steps[index], right_steps[index]
            step_path = f"steps[{index}]"
            current_mismatches: list[str] = []
            if not isinstance(left_step, dict) or not isinstance(right_step, dict):
                errors.append(f"invalid_step:{step_path}")
                current_mismatches.append("invalid_step")
                step_results.append({"index": index, "mismatches": current_mismatches})
                step_mismatches.extend(f"{step_path}.{item}" for item in current_mismatches)
                continue
            for field in ("step", "frame"):
                if left_step.get(field) != right_step.get(field):
                    current_mismatches.append(field)
            dt = _scalar_compare(left_step.get("dt_s"), right_step.get("dt_s"), path=f"{step_path}.dt_s", errors=errors)
            if not dt["equal"]:
                current_mismatches.append("dt_s")
            state_before, before_mismatches = _compare_state(
                left_step.get("state_before"),
                right_step.get("state_before"),
                path=f"{step_path}.state_before",
                errors=errors,
            )
            current_mismatches.extend(before_mismatches)
            trace, trace_mismatches = _compare_trace(
                left_step.get("trace"),
                right_step.get("trace"),
                path=f"{step_path}.trace",
                errors=errors,
            )
            current_mismatches.extend(trace_mismatches)

            left_prediction = left_step.get("prediction") if isinstance(left_step.get("prediction"), dict) else {}
            right_prediction = right_step.get("prediction") if isinstance(right_step.get("prediction"), dict) else {}
            prediction: dict[str, Any] = {}
            for field in ("displacement", "delta_velocity"):
                comparison = _compare_digest(
                    left_prediction.get(field),
                    right_prediction.get(field),
                    path=f"{step_path}.prediction.{field}",
                    errors=errors,
                )
                prediction[field] = comparison
                if not comparison["exact_equal"]:
                    current_mismatches.append(f"prediction.{field}")

            state_after, after_mismatches = _compare_state(
                left_step.get("state_after"),
                right_step.get("state_after"),
                path=f"{step_path}.state_after",
                errors=errors,
            )
            current_mismatches.extend(after_mismatches)
            step_mismatches.extend(f"{step_path}.{item}" for item in current_mismatches)
            step_results.append({
                "index": index,
                "step": left_step.get("step"),
                "frame": left_step.get("frame"),
                "dt_s": dt,
                "state_before": state_before,
                "trace": trace,
                # These four entries are the only direct state/prediction
                # differences the v1 report can expose per step.
                "position_velocity_differences": {
                    "prediction_displacement": prediction["displacement"],
                    "prediction_delta_velocity": prediction["delta_velocity"],
                    "state_after_position": state_after.get("position"),
                    "state_after_velocity": state_after.get("velocity"),
                },
                "prediction": prediction,
                "state_after": state_after,
                "mismatches": current_mismatches,
                "exact_match": not current_mismatches,
            })

    element_trace: dict[str, Any] | None = None
    if (left_element_trace_path is None) != (right_element_trace_path is None):
        errors.append("both_element_trace_sidecars_required")
    elif left_element_trace_path is not None and right_element_trace_path is not None:
        try:
            element_trace = _compare_element_traces(
                Path(left_element_trace_path), Path(right_element_trace_path), left, right
            )
            if element_trace.get("errors"):
                errors.extend(f"element_trace:{item}" for item in element_trace["errors"])
        except Exception as error:  # pragma: no cover - defensive corrupt-artifact path
            errors.append(f"element_trace_compare:{type(error).__name__}:{error}")
            element_trace = {
                "schema": ELEMENT_TRACE_SCHEMA,
                "passed": False,
                "tolerance_passed": False,
                "tolerance_status": "undetermined_invalid_element_trace",
                "errors": [f"{type(error).__name__}: {error}"],
            }

    trace_exact_match = not initial_mismatches and not step_mismatches and not errors
    identity_ok = bool(identity.get("passed"))
    environment_ok = bool(environment.get("passed"))
    if errors:
        decision = "invalid_report"
    elif identity_mismatches:
        decision = "identity_mismatch"
    elif environment_mismatches:
        decision = "environment_mismatch"
    elif element_trace is not None and not element_trace.get("identity", {}).get("passed", False):
        decision = "element_trace_identity_mismatch"
    elif element_trace is not None and element_trace.get("tolerance_status") == "within_registered_tolerance":
        if trace_exact_match and element_trace.get("exact_match", False):
            decision = "exact_match"
        elif trace_exact_match:
            decision = "element_trace_within_registered_tolerance"
        else:
            decision = "digest_difference_within_registered_tolerance"
    elif element_trace is not None and element_trace.get("tolerance_status") == "violated_registered_tolerance":
        decision = "elementwise_tolerance_violation"
    elif not trace_exact_match:
        decision = "digest_difference_requires_element_output"
    else:
        decision = "exact_match"

    first_trace_difference: dict[str, Any] | None = None
    if initial_mismatches:
        first_trace_difference = {
            "category": "initial_state",
            "path": initial_mismatches[0],
            "evidence": initial_result.get(initial_mismatches[0].split(".")[-1]),
        }
    else:
        for step in step_results:
            if step.get("mismatches"):
                first_path = step["mismatches"][0]
                evidence: Any = None
                trace_first = step.get("trace", {}).get("first_mismatch")
                if trace_first and first_path in step.get("trace", {}).get("mismatches", []):
                    evidence = trace_first.get("evidence")
                first_trace_difference = {
                    "category": "step_trace",
                    "step": step.get("step"),
                    "frame": step.get("frame"),
                    "path": first_path,
                    "evidence": evidence,
                }
                break

    if identity_mismatches:
        first_difference = {"category": "identity", "path": identity_mismatches[0]}
    elif environment_mismatches:
        first_difference = {"category": "environment", "path": environment_mismatches[0]}
    else:
        first_difference = first_trace_difference

    bitwise_passed = bool(not errors and identity_ok and environment_ok and trace_exact_match)
    comparison_passed = (
        bitwise_passed if element_trace is None
        else bool(
            not errors and identity_ok and environment_ok
            and element_trace.get("identity", {}).get("passed", False)
            and element_trace.get("tolerance_passed", False)
        )
    )
    return {
        "schema": COMPARISON_SCHEMA,
        "protocol": {
            "canary_schema": REPORT_SCHEMA,
            "diagnostic_maximum_steps": 20,
            "full_reproduction_not_claimed": True,
            "digest_comparison": "SHA-256 plus dtype/shape/finite/summary validation",
            "elementwise_tolerance_evaluable": element_trace is not None and not errors,
        },
        "passed": comparison_passed,
        "bitwise_exact": bitwise_passed,
        "element_trace_passed": bool(element_trace is not None and element_trace.get("tolerance_passed", False)),
        "decision": decision,
        "identity_passed": identity_ok and not identity_mismatches,
        "environment_passed": environment_ok and not environment_mismatches,
        "trace_exact_match": trace_exact_match,
        "numerical_tolerance_status": (
            element_trace.get("tolerance_status") if element_trace is not None
            else ("satisfied_by_exact_digest_equality" if trace_exact_match
                  else "undetermined_without_elementwise_output")
        ),
        "left": _report_side_summary(left, left_path) if left else {"path": str(left_path)},
        "right": _report_side_summary(right, right_path) if right else {"path": str(right_path)},
        "identity": identity,
        "environment": environment,
        "initial_state": initial_result,
        "steps": step_results,
        "first_difference": first_difference,
        "first_trace_difference": first_trace_difference,
        "element_trace": element_trace,
        "errors": errors,
        "measurement_limits": MEASUREMENT_LIMITS,
        "scientific_claim": "none; bounded 20-step runtime diagnostic only",
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True, help="first canary.json, usually Ada")
    parser.add_argument("--right", type=Path, required=True, help="second canary.json, usually H200")
    parser.add_argument("--left-element-trace", type=Path, help="Ada element_trace.v1 metadata JSON")
    parser.add_argument("--right-element-trace", type=Path, help="H200 element_trace.v1 metadata JSON")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = compare_reports(
        args.left,
        args.right,
        args.left_element_trace,
        args.right_element_trace,
    )
    write_json(args.output, report)
    print(json.dumps({
        "output": str(args.output),
        "passed": report["passed"],
        "decision": report["decision"],
        "first_difference": report["first_difference"],
    }, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
