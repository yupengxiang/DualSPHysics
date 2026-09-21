"""Compare two complete-window F3 native-volume MLS traces.

The comparator keeps every independent geometric seed in the denominator.
Permanent support loss is a right-censoring mechanism for event metrics, and
does not remove a seed from source CDFs or residence statistics.  It accepts
different saved-frame cadences (for example native .002 and direct native
frame selection to nominal .01) when the initial seeds, source H5, and event
definitions match.

Different reconstruction backends are rejected unless an explicit
`temporal_method_comparison` provenance record declares a v3 linear-field
trace versus a v1/v2 current-frame-held trace.  This is a diagnostic
postprocess.  It does not infer material reliability or T2 qualification from
support agreement, CDF agreement, or common path coverage.

The `cross_scope_same_seed_axis` mode permits the same registered backend
across production/coarse/fine source scopes only when its provenance binds the
backend family, seed representation, finite-wall geometry, source hashes, and
event definition.  It does not turn a cross-resolution comparison into a
qualification claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "core.material.f3.native_volume_mls.comparison.v2"
TRACE_SCHEMA_PREFIX = "core.material.f3.native_volume_mls.trace."
QUANTILES = np.linspace(0.05, 0.95, 19, dtype=np.float64)
COMPARISON_MODES = {
    "same_source_cadence",
    "cross_scope_same_seed_axis",
    "independent_seed_axes",
    "temporal_method_comparison",
}

TEMPORAL_V3_BACKEND = "f3_native_volume_mls_temporal_linear_current_interval_rk4_v3"
CURRENT_FRAME_BACKENDS = {
    "f3_native_volume_mls_current_frame_rk4_v1",
    "f3_native_volume_mls_current_frame_rk4_v2",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _attr_json(handle, name: str):
    value = handle.attrs.get(name)
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _attr_text(handle, name: str, default: str = "") -> str:
    value = handle.attrs.get(name, default)
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _load_trace(path: str | Path) -> dict:
    path = Path(path).resolve()
    with h5py.File(path, "r") as handle:
        schema = _attr_text(handle, "schema")
        if not schema.startswith(TRACE_SCHEMA_PREFIX):
            raise ValueError(f"{path} is not an F3 native MLS trace")
        committed = int(handle.attrs.get("committed", -1))
        if committed < 0:
            raise ValueError(f"{path} has no committed frame")
        required = {
            "time", "initial_position", "source_label", "position", "reliable",
            "permanent_unknown", "first_passage", "return_time", "residence_opposite",
            "returned", "seed_mass_closure_error",
        }
        missing = sorted(required - set(handle))
        if missing:
            raise ValueError(f"{path} is missing trace datasets: {missing}")
        time = np.asarray(handle["time"][:committed + 1], dtype=np.float64)
        if (time.ndim != 1 or len(time) != committed + 1 or len(time) < 2
                or not np.isfinite(time).all() or np.any(np.diff(time) <= 0.0)):
            raise ValueError(f"{path} has invalid committed time axis")
        source_label = np.asarray(handle["source_label"][:], dtype=np.int8)
        initial_position = np.asarray(handle["initial_position"][:], dtype=np.float64)
        n = len(source_label)
        if initial_position.shape != (n, 3):
            raise ValueError(f"{path} has inconsistent initial seed shape")
        result = {
            "path": str(path),
            "sha256": sha256_file(path),
            "schema": schema,
            "trace_backend": _attr_text(handle, "trace_backend", ""),
            "binding": _attr_json(handle, "binding") or {},
            "committed": committed,
            "time": time,
            "initial_position": initial_position,
            "source_label": source_label,
            "position": np.asarray(handle["position"][committed], dtype=np.float64),
            "reliable_history": np.asarray(handle["reliable"][:committed + 1], dtype=bool),
            "unknown_history": np.asarray(handle["permanent_unknown"][:committed + 1], dtype=bool),
            "first_passage": np.asarray(handle["first_passage"][committed], dtype=np.float64),
            "return_time": np.asarray(handle["return_time"][committed], dtype=np.float64),
            "residence": np.asarray(handle["residence_opposite"][committed], dtype=np.float64),
            "returned": np.asarray(handle["returned"][committed], dtype=bool),
            "mass_closure_error": np.asarray(handle["seed_mass_closure_error"][:committed + 1], dtype=np.float64),
            "material_reliability": _attr_text(handle, "material_reliability", "unknown"),
        }
    expected = (len(time), n)
    for name in ("reliable_history", "unknown_history"):
        if result[name].shape != expected:
            raise ValueError(f"{path} has inconsistent {name} shape {result[name].shape}")
    if result["position"].shape != (n, 3):
        raise ValueError(f"{path} has inconsistent endpoint position shape")
    if not np.array_equal(result["unknown_history"], ~result["reliable_history"]):
        raise ValueError(f"{path} permanent_unknown is inconsistent with reliable")
    return result


def _load_provenance(provenance: Mapping | str | Path | None) -> dict:
    if provenance is None:
        return {}
    if isinstance(provenance, (str, Path)):
        path = Path(provenance)
        value = json.loads(path.read_text())
    else:
        value = dict(provenance)
    if not isinstance(value, dict):
        raise ValueError("comparison provenance must be a JSON object")
    return value


def _expected_hashes(provenance: dict, left: dict, right: dict) -> None:
    expected = provenance.get("expected_trace_source_sha256")
    if expected is None:
        return
    if not isinstance(expected, dict) or set(expected) != {"left", "right"}:
        raise ValueError("expected_trace_source_sha256 must contain left and right")
    for side, trace in (("left", left), ("right", right)):
        actual = trace["binding"].get("source_sha256")
        if expected[side] != actual:
            raise ValueError(
                f"provenance expected {side} source_sha256 {expected[side]!r}, got {actual!r}"
            )


def _backend_family(trace: dict) -> str:
    """Classify only the registered F3 method families used by this comparator."""
    backend = trace.get("trace_backend", "")
    if backend == TEMPORAL_V3_BACKEND:
        return "temporal_linear_v3"
    if backend in CURRENT_FRAME_BACKENDS:
        return "current_frame_hold"
    return "unknown"


def _finite_wall_signature(binding: Mapping) -> str | None:
    """Return the immutable finite-wall geometry signature, if present."""
    value = binding.get("walls_sha256")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        return None
    return value


def _validate_temporal_method_pair(left: dict, right: dict, provenance: dict,
                                   issues: list[str]) -> tuple[float, str, str]:
    """Validate the explicit v3 versus current-frame method comparison.

    The mode is intentionally narrower than cross-scope comparison: both
    traces must be the same registered source and geometric seed axis.  Only
    the temporal-field method is allowed to differ, and that difference must
    be declared in the provenance object.
    """
    if not provenance.get("allow_temporal_method_difference", False):
        issues.append("temporal_method_comparison requires allow_temporal_method_difference=true")
    expected_sources = provenance.get("expected_trace_source_sha256")
    if (not isinstance(expected_sources, dict)
            or set(expected_sources) != {"left", "right"}):
        issues.append(
            "temporal_method_comparison requires expected_trace_source_sha256 for both traces"
        )
    else:
        _expected_hashes(provenance, left, right)
    if left["binding"].get("source_sha256") != right["binding"].get("source_sha256"):
        issues.append("temporal_method_comparison requires the same source_sha256")
    families = (_backend_family(left), _backend_family(right))
    if set(families) != {"temporal_linear_v3", "current_frame_hold"}:
        issues.append(
            "temporal_method_comparison requires exactly one temporal_linear_v3 "
            "and one current_frame_hold backend"
        )
    if left.get("trace_backend") == right.get("trace_backend"):
        issues.append("temporal_method_comparison requires different registered method backends")
    expected_families = provenance.get("expected_backend_families")
    if expected_families is not None:
        if (not isinstance(expected_families, list)
                or sorted(str(value) for value in expected_families) != sorted(families)):
            issues.append("provenance expected_backend_families does not match trace backends")
    expected_backends = provenance.get("expected_trace_backends")
    if expected_backends is not None:
        if (not isinstance(expected_backends, list)
                or sorted(str(value) for value in expected_backends)
                != sorted(str(value) for value in (left.get("trace_backend"), right.get("trace_backend")))):
            issues.append("provenance expected_trace_backends does not match trace backends")

    left_wall = _finite_wall_signature(left["binding"])
    right_wall = _finite_wall_signature(right["binding"])
    expected_wall = provenance.get("expected_walls_sha256")
    if left_wall is None or right_wall is None:
        issues.append("temporal_method_comparison requires finite-wall walls_sha256 on both traces")
    elif left_wall != right_wall:
        issues.append("finite-wall walls_sha256 differs")
    if expected_wall is not None and (left_wall != expected_wall or right_wall != expected_wall):
        issues.append("provenance expected_walls_sha256 does not match both traces")

    required_event_keys = ("first_passage", "return", "residence")
    left_event = left["binding"].get("event_definition")
    right_event = right["binding"].get("event_definition")
    if not isinstance(left_event, dict) or not isinstance(right_event, dict):
        issues.append("temporal_method_comparison requires structured event_definition on both traces")
    else:
        missing_left = [key for key in required_event_keys if key not in left_event]
        missing_right = [key for key in required_event_keys if key not in right_event]
        if missing_left or missing_right:
            issues.append(
                "event_definition lacks finite crossing/residence fields: "
                f"left={missing_left}, right={missing_right}"
            )
        if left_event != right_event:
            issues.append("event_definition differs between temporal methods")
    expected_event = provenance.get("expected_event_definition")
    if expected_event is not None and (left_event != expected_event or right_event != expected_event):
        issues.append("provenance expected_event_definition does not match both traces")

    endpoint_tolerance = provenance.get("endpoint_time_tolerance_s")
    if (not isinstance(endpoint_tolerance, (int, float))
            or isinstance(endpoint_tolerance, bool)
            or not np.isfinite(endpoint_tolerance)
            or endpoint_tolerance < 0.0):
        issues.append("provenance endpoint_time_tolerance_s must be finite and nonnegative")
        endpoint_tolerance = 0.0
    return float(endpoint_tolerance), "paired_same_seed_axis", "explicitly_registered_same_source_method_difference"


def _validate_cross_scope_backend_provenance(left: dict, right: dict,
                                             provenance: dict,
                                             issues: list[str]) -> None:
    """Apply optional strict method/wall bindings for cross-scope comparisons.

    Cross-scope comparisons are used for the three F3 spatial resolutions.  The
    source H5 is allowed to differ there, but the reconstruction backend,
    finite-wall geometry, and registered seed representation must be bound by
    the comparison record.  Existing generic cross-scope callers may omit
    these fields; a v3 collection record must provide them explicitly.
    """
    expected_backend = provenance.get("expected_trace_backend")
    if expected_backend is not None:
        if not isinstance(expected_backend, str) or not expected_backend:
            issues.append("provenance expected_trace_backend must be a nonempty string")
        else:
            for side, trace in (("left", left), ("right", right)):
                if trace.get("trace_backend") != expected_backend:
                    issues.append(
                        f"provenance expected_trace_backend does not match {side} trace"
                    )

    expected_family = provenance.get("expected_backend_family")
    if expected_family is not None:
        if not isinstance(expected_family, str) or not expected_family:
            issues.append("provenance expected_backend_family must be a nonempty string")
        else:
            for side, trace in (("left", left), ("right", right)):
                if _backend_family(trace) != expected_family:
                    issues.append(
                        f"provenance expected_backend_family does not match {side} trace"
                    )

    expected_source_definition = provenance.get("expected_source_definition")
    expected_event_definition = provenance.get("expected_event_definition")
    if expected_backend == TEMPORAL_V3_BACKEND:
        if expected_source_definition is None:
            issues.append(
                "cross-scope v3 provenance requires expected_source_definition"
            )
        if expected_event_definition is None:
            issues.append(
                "cross-scope v3 provenance requires expected_event_definition"
            )
    if expected_source_definition is not None:
        if (left["binding"].get("source_definition") != expected_source_definition
                or right["binding"].get("source_definition") != expected_source_definition):
            issues.append(
                "provenance expected_source_definition does not match both traces"
            )
    if expected_event_definition is not None:
        if (left["binding"].get("event_definition") != expected_event_definition
                or right["binding"].get("event_definition") != expected_event_definition):
            issues.append(
                "provenance expected_event_definition does not match both traces"
            )

    if provenance.get("require_finite_wall_match", False):
        left_wall = _finite_wall_signature(left["binding"])
        right_wall = _finite_wall_signature(right["binding"])
        if left_wall is None or right_wall is None:
            issues.append(
                "cross-scope v3 provenance requires finite-wall walls_sha256 on both traces"
            )
        elif left_wall != right_wall:
            issues.append("cross-scope v3 provenance requires matching walls_sha256")
        expected_wall = provenance.get("expected_walls_sha256")
        if expected_wall is None:
            issues.append(
                "cross-scope v3 provenance requires expected_walls_sha256 when "
                "require_finite_wall_match=true"
            )
        elif (not isinstance(expected_wall, str) or not expected_wall
              or left_wall != expected_wall or right_wall != expected_wall):
            issues.append("provenance expected_walls_sha256 does not match both traces")

    expected_seed = provenance.get("expected_trace_seed_hash")
    if expected_seed is not None:
        if isinstance(expected_seed, dict):
            valid = (
                set(expected_seed) == {"left", "right"}
                and expected_seed["left"] == left["binding"].get("seed_hash")
                and expected_seed["right"] == right["binding"].get("seed_hash")
            )
        else:
            valid = (
                isinstance(expected_seed, str)
                and left["binding"].get("seed_hash") == expected_seed
                and right["binding"].get("seed_hash") == expected_seed
            )
        if not valid:
            issues.append("provenance expected_trace_seed_hash does not match both traces")


def _validate_pair(left: dict, right: dict, comparison_mode: str,
                   provenance: Mapping | str | Path | None = None) -> dict:
    if comparison_mode not in COMPARISON_MODES:
        raise ValueError(f"unknown comparison_mode {comparison_mode!r}")
    provenance = _load_provenance(provenance)
    if comparison_mode != "same_source_cadence":
        if not provenance:
            raise ValueError(
                f"{comparison_mode} requires explicit registered comparison provenance"
            )
        if provenance.get("comparison_mode") != comparison_mode:
            raise ValueError("provenance comparison_mode does not match requested mode")
        _expected_hashes(provenance, left, right)
    # The historical registered F3 axis is 512 seeds.  A different axis is
    # legal only when the comparison provenance names its exact cardinality;
    # this prevents a 4096 trace from being accepted by accident while
    # removing the old hard-coded rejection for an explicitly registered
    # quadrature comparison.
    expected_seed_count = 512
    if comparison_mode != "same_source_cadence" and "expected_seed_count" in provenance:
        value = provenance["expected_seed_count"]
        if (isinstance(value, bool) or not isinstance(value, (int, np.integer))
                or int(value) < 1):
            raise ValueError("provenance expected_seed_count must be a positive integer")
        expected_seed_count = int(value)
    issues = []
    lb, rb = left["binding"], right["binding"]
    if (left.get("trace_backend") != right.get("trace_backend")
            and comparison_mode != "temporal_method_comparison"):
        issues.append(
            "trace backend differs; use explicit temporal_method_comparison provenance"
        )
    for key in ("source_definition", "event_definition"):
        if lb.get(key) != rb.get(key):
            issues.append(f"binding.{key} differs")
    if comparison_mode == "same_source_cadence":
        for key in ("source_sha256", "query_count", "seed_hash"):
            if lb.get(key) != rb.get(key):
                issues.append(f"binding.{key} differs")
        if not np.array_equal(left["initial_position"], right["initial_position"]):
            issues.append("initial_position differs")
        if not np.array_equal(left["source_label"], right["source_label"]):
            issues.append("source_label differs")
        if len(left["source_label"]) != len(right["source_label"]):
            issues.append("seed-axis length differs")
        if len(left["source_label"]) != 512:
            issues.append("same_source_cadence requires the registered 512-seed axis")
        endpoint_tolerance = 1.0e-8
        seed_axis = "paired_same_seed_axis"
        source_hash_policy = "must_match"
    elif comparison_mode == "cross_scope_same_seed_axis":
        if not provenance.get("allow_source_sha_mismatch", False):
            issues.append("provenance does not explicitly allow source_sha256 mismatch")
        _validate_cross_scope_backend_provenance(left, right, provenance, issues)
        if lb.get("seed_hash") != rb.get("seed_hash"):
            issues.append("seed_hash differs; cross-scope mode requires the same registered seed axis")
        if not np.array_equal(left["initial_position"], right["initial_position"]):
            issues.append("initial_position differs; cross-scope path pairing is invalid")
        if not np.array_equal(left["source_label"], right["source_label"]):
            issues.append("source_label differs; cross-scope path pairing is invalid")
        if len(left["source_label"]) != len(right["source_label"]):
            issues.append("cross-scope same-seed mode requires equal seed axes")
        if len(left["source_label"]) != expected_seed_count:
            issues.append(
                "cross-scope mode requires the provenance-registered seed axis "
                f"of {expected_seed_count} seeds"
            )
        endpoint_tolerance = provenance.get("endpoint_time_tolerance_s")
        if (not isinstance(endpoint_tolerance, (int, float))
                or isinstance(endpoint_tolerance, bool)
                or not np.isfinite(endpoint_tolerance)
                or endpoint_tolerance < 0.0):
            issues.append("provenance endpoint_time_tolerance_s must be finite and nonnegative")
            endpoint_tolerance = 0.0
        seed_axis = "paired_same_seed_axis"
        source_hash_policy = "explicitly_registered_mismatch_allowed"
    elif comparison_mode == "temporal_method_comparison":
        left_seed_hash = lb.get("seed_hash")
        right_seed_hash = rb.get("seed_hash")
        if left_seed_hash != right_seed_hash:
            expected_seed_hashes = provenance.get("expected_trace_seed_hash")
            if not provenance.get("allow_seed_hash_representation_difference", False):
                issues.append(
                    "seed_hash differs; temporal method comparison requires explicit "
                    "seed-hash representation provenance"
                )
            elif (not isinstance(expected_seed_hashes, dict)
                  or set(expected_seed_hashes) != {"left", "right"}
                  or expected_seed_hashes["left"] != left_seed_hash
                  or expected_seed_hashes["right"] != right_seed_hash):
                issues.append(
                    "expected_trace_seed_hash must bind both differing seed-hash representations"
                )
        if not np.array_equal(left["initial_position"], right["initial_position"]):
            issues.append("initial_position differs; temporal method path pairing is invalid")
        if not np.array_equal(left["source_label"], right["source_label"]):
            issues.append("source_label differs; temporal method path pairing is invalid")
        if len(left["source_label"]) != len(right["source_label"]):
            issues.append("temporal method comparison requires equal seed axes")
        if len(left["source_label"]) != expected_seed_count:
            issues.append(
                "temporal method comparison requires the provenance-registered seed axis "
                f"of {expected_seed_count} seeds"
            )
        endpoint_tolerance, seed_axis, source_hash_policy = _validate_temporal_method_pair(
            left, right, provenance, issues
        )
    else:
        if not provenance.get("allow_seed_axis_difference", False):
            issues.append("provenance does not explicitly allow independent seed axes")
        if len(left["source_label"]) == len(right["source_label"]):
            issues.append("independent_seed_axes requires different seed-axis cardinalities")
        endpoint_tolerance = provenance.get("endpoint_time_tolerance_s")
        if endpoint_tolerance is None:
            endpoint_tolerance = 0.0
        if (not isinstance(endpoint_tolerance, (int, float))
                or isinstance(endpoint_tolerance, bool)
                or not np.isfinite(endpoint_tolerance)
                or endpoint_tolerance < 0.0):
            issues.append("provenance endpoint_time_tolerance_s must be finite and nonnegative")
            endpoint_tolerance = 0.0
        seed_axis = "independent_no_seed_pairing"
        source_hash_policy = "registered_per_trace"
    if comparison_mode != "independent_seed_axes":
        if left["position"].shape != right["position"].shape:
            issues.append("endpoint shape differs")
    elif left["position"].shape[1:] != right["position"].shape[1:]:
        issues.append("endpoint coordinate dimension differs")
    end_delta = abs(float(left["time"][-1]) - float(right["time"][-1]))
    if end_delta > float(endpoint_tolerance):
        issues.append(
            f"physical observation end differs by {end_delta:.17g}s "
            f"> registered tolerance {float(endpoint_tolerance):.17g}s"
        )
    if issues:
        raise ValueError("incompatible F3 traces: " + "; ".join(issues))
    return {
        "comparison_mode": comparison_mode,
        "method_comparison": {
            "status": (
                "explicit_temporal_method_difference"
                if comparison_mode == "temporal_method_comparison"
                else "single_backend_or_registered_scope_comparison"
            ),
            "left_backend": left.get("trace_backend"),
            "right_backend": right.get("trace_backend"),
            "qualification_effect": "none; comparison remains diagnostic-only",
        },
        "source_sha256": lb.get("source_sha256"),
        "right_source_sha256": rb.get("source_sha256"),
        "seed_hash": lb.get("seed_hash"),
        "right_seed_hash": rb.get("seed_hash"),
        "query_count": int(len(left["source_label"])),
        "right_query_count": int(len(right["source_label"])),
        "expected_seed_count": int(expected_seed_count),
        "source_definition": lb.get("source_definition"),
        "event_definition": lb.get("event_definition"),
        "left_trace_backend": left.get("trace_backend"),
        "right_trace_backend": right.get("trace_backend"),
        "left_backend_family": _backend_family(left),
        "right_backend_family": _backend_family(right),
        "left_frame_selection": lb.get("frame_selection"),
        "right_frame_selection": rb.get("frame_selection"),
        "endpoint_time_delta_s": float(float(right["time"][-1]) - float(left["time"][-1])),
        "endpoint_time_tolerance_s": float(endpoint_tolerance),
        "seed_axis_policy": seed_axis,
        "source_hash_policy": source_hash_policy,
        "provenance": provenance,
    }


def _unknown_window(trace: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    history = trace["unknown_history"]
    times = trace["time"]
    first_index = np.full(history.shape[1], -1, dtype=np.int64)
    for seed in range(history.shape[1]):
        candidates = np.flatnonzero(history[:, seed])
        if len(candidates):
            first_index[seed] = int(candidates[0])
    possible_from = np.full(history.shape[1], np.nan, dtype=np.float64)
    for seed, frame in enumerate(first_index):
        if frame >= 0:
            possible_from[seed] = times[max(0, frame - 1)]
    return history[-1], first_index, possible_from


def _event_cdf_bounds(event_time: np.ndarray, weight: np.ndarray, select: np.ndarray,
                      final_unknown: np.ndarray, unknown_possible_from: np.ndarray,
                      observation_end: float, denominator: float) -> dict:
    """Return lower/upper event CDFs using all source seeds as denominator."""
    event_time = np.asarray(event_time, dtype=np.float64)
    select = np.asarray(select, dtype=bool)
    finite = select & np.isfinite(event_time)
    unresolved = select & final_unknown & ~finite & np.isfinite(unknown_possible_from)
    candidate = np.asarray([0.0, observation_end, *event_time[finite],
                            *unknown_possible_from[unresolved]], dtype=np.float64)
    candidate = np.unique(candidate[np.isfinite(candidate)])
    candidate.sort()
    if denominator <= 0.0:
        candidate = np.empty(0, dtype=np.float64)
    lower = np.asarray([
        float(np.sum(weight[finite & (event_time <= value)]) / denominator)
        for value in candidate
    ], dtype=np.float64)
    upper = lower + np.asarray([
        float(np.sum(weight[unresolved & (unknown_possible_from <= value)]) / denominator)
        for value in candidate
    ], dtype=np.float64)
    observed = float(np.sum(weight[finite]) / denominator) if denominator else 0.0
    unresolved_mass = float(np.sum(weight[unresolved]) / denominator) if denominator else 0.0
    return {
        "time_s": candidate.tolist(),
        "lower_mass_fraction": lower.tolist(),
        "upper_mass_fraction": upper.tolist(),
        "observed_event_mass_fraction": observed,
        "upper_event_mass_fraction": observed + unresolved_mass,
        "unresolved_unknown_mass_fraction": unresolved_mass,
        "reliable_no_event_right_censored_mass_fraction": float(
            np.sum(weight[select & ~final_unknown & ~finite]) / denominator
        ) if denominator else 0.0,
    }


def _interval_cdf(lower_value: np.ndarray, upper_value: np.ndarray, weight: np.ndarray,
                  select: np.ndarray, denominator: float) -> dict:
    """Bound a CDF of per-seed residence intervals, including zero residence."""
    lower_value = np.maximum(np.nan_to_num(lower_value, nan=0.0), 0.0)
    upper_value = np.maximum(np.nan_to_num(upper_value, nan=0.0), lower_value)
    finite = select & np.isfinite(lower_value) & np.isfinite(upper_value)
    values = np.unique(np.concatenate(([0.0], lower_value[finite], upper_value[finite])))
    values.sort()
    if denominator <= 0.0:
        return {"value_s": [], "lower_mass_fraction": [], "upper_mass_fraction": [],
                "zero_mass_fraction_lower": 0.0, "zero_mass_fraction_upper": 0.0}
    lower_cdf = np.asarray([
        float(np.sum(weight[finite & (upper_value <= value)]) / denominator)
        for value in values
    ])
    upper_cdf = np.asarray([
        float(np.sum(weight[finite & (lower_value <= value)]) / denominator)
        for value in values
    ])
    return {
        "value_s": values.tolist(),
        "lower_mass_fraction": lower_cdf.tolist(),
        "upper_mass_fraction": upper_cdf.tolist(),
        "zero_mass_fraction_lower": float(np.sum(weight[finite & (upper_value == 0.0)]) / denominator),
        "zero_mass_fraction_upper": float(np.sum(weight[finite & (lower_value == 0.0)]) / denominator),
    }


def _weighted_quantiles(values: np.ndarray, weight: np.ndarray, select: np.ndarray,
                        denominator: float) -> dict:
    finite = select & np.isfinite(values)
    if denominator <= 0.0 or not np.any(finite):
        return {str(float(q)): None for q in QUANTILES}
    order = np.argsort(values[finite], kind="mergesort")
    ordered = values[finite][order]
    cumulative = np.cumsum(weight[finite][order]) / denominator
    return {
        str(float(q)): (float(ordered[np.flatnonzero(cumulative >= q)[0]])
                        if np.any(cumulative >= q) else None)
        for q in QUANTILES
    }


def _cdf_bound_at(cdf: dict, value: float) -> tuple[float, float]:
    """Evaluate a step CDF interval at ``value`` using right-continuous steps."""
    times = np.asarray(cdf.get("time_s", cdf.get("value_s", [])), dtype=np.float64)
    lower = np.asarray(cdf.get("lower_mass_fraction", []), dtype=np.float64)
    upper = np.asarray(cdf.get("upper_mass_fraction", []), dtype=np.float64)
    if len(times) == 0:
        return 0.0, 0.0
    index = int(np.searchsorted(times, value, side="right") - 1)
    if index < 0:
        return 0.0, 0.0
    return float(lower[index]), float(upper[index])


def _cdf_sup_difference(left_cdf: dict, right_cdf: dict) -> dict:
    """Bound the largest CDF difference when each CDF is an interval."""
    left_times = left_cdf.get("time_s", left_cdf.get("value_s", []))
    right_times = right_cdf.get("time_s", right_cdf.get("value_s", []))
    values = np.unique(np.asarray([*left_times, *right_times], dtype=np.float64))
    values = values[np.isfinite(values)]
    lower_difference = []
    upper_difference = []
    for value in values:
        left_lower, left_upper = _cdf_bound_at(left_cdf, float(value))
        right_lower, right_upper = _cdf_bound_at(right_cdf, float(value))
        # True right-left lies in [right_lower-left_upper, right_upper-left_lower].
        lower_difference.append(right_lower - left_upper)
        upper_difference.append(right_upper - left_lower)
    if not len(values):
        return {
            "time_or_value": [],
            "lower_difference": [],
            "upper_difference": [],
            "sup_abs_difference_bound": 0.0,
        }
    lower_difference = np.asarray(lower_difference, dtype=np.float64)
    upper_difference = np.asarray(upper_difference, dtype=np.float64)
    return {
        "time_or_value": values.tolist(),
        "lower_difference": lower_difference.tolist(),
        "upper_difference": upper_difference.tolist(),
        "sup_abs_difference_bound": float(
            max(np.max(np.abs(lower_difference)), np.max(np.abs(upper_difference)))
        ),
    }


def _source_rows(trace: dict) -> dict[str, dict]:
    n = len(trace["source_label"])
    weight = np.full(n, 1.0 / n, dtype=np.float64)
    labels = trace["source_label"]
    final_unknown, first_failure, unknown_from = _unknown_window(trace)
    final_reliable = ~final_unknown
    path_reliable = trace["reliable_history"].all(axis=0)
    end = float(trace["time"][-1])
    residence_lower = np.nan_to_num(trace["residence"], nan=0.0, posinf=0.0, neginf=0.0)
    residence_upper = residence_lower.copy()
    can_censor = final_unknown & np.isfinite(unknown_from)
    residence_upper[can_censor] += np.maximum(0.0, end - unknown_from[can_censor])
    rows = {}
    for source in np.unique(labels):
        select = labels == source
        denominator = float(np.sum(weight[select]))
        unknown_fraction = float(np.sum(weight[select & final_unknown]) / denominator)
        source_path = select & path_reliable
        source_final_reliable = select & final_reliable
        first_cdf = _event_cdf_bounds(
            trace["first_passage"], weight, select, final_unknown,
            unknown_from, end, denominator,
        )
        return_cdf = _event_cdf_bounds(
            trace["return_time"], weight, select, final_unknown,
            unknown_from, end, denominator,
        )
        residence_cdf = _interval_cdf(
            residence_lower, residence_upper, weight, select, denominator,
        )
        residence_lower_mean = float(np.sum(weight[select] * residence_lower[select]) / denominator)
        residence_upper_mean = float(np.sum(weight[select] * residence_upper[select]) / denominator)
        first_observed = select & np.isfinite(trace["first_passage"])
        return_observed = select & np.isfinite(trace["return_time"])
        rows[str(int(source))] = {
            "seed_count": int(np.count_nonzero(select)),
            "initial_mass_fraction": float(np.sum(weight[select])),
            "denominator_policy": (
                f"all independent geometric seeds in this source; "
                f"uniform per-trace weight=1/{n}"
            ),
            "final_unknown_fraction": unknown_fraction,
            "final_unknown_mass_fraction_bounds": {"lower": 0.0, "upper": unknown_fraction},
            "final_reliable_fraction": float(np.sum(weight[source_final_reliable]) / denominator),
            "common_path_single_trace_fraction": float(np.sum(weight[source_path]) / denominator),
            "first_passage_observed_fraction": float(np.sum(weight[first_observed]) / denominator),
            "first_passage_event_fraction_bounds": {
                "lower": first_cdf["observed_event_mass_fraction"],
                "upper": first_cdf["upper_event_mass_fraction"],
            },
            "first_passage_cdf_bounds": first_cdf,
            "return_observed_fraction": float(np.sum(weight[return_observed]) / denominator),
            "return_event_fraction_bounds": {
                "lower": return_cdf["observed_event_mass_fraction"],
                "upper": return_cdf["upper_event_mass_fraction"],
            },
            "return_cdf_bounds": return_cdf,
            "return_quantiles_s_observed": _weighted_quantiles(
                trace["return_time"], weight, return_observed, denominator,
            ),
            "residence_metric": "cumulative opposite-source halfspace time within observed window",
            "residence_mean_s_bounds": {
                "lower": residence_lower_mean,
                "upper": residence_upper_mean,
            },
            "residence_cdf_bounds": residence_cdf,
            "residence_zero_mass_fraction_bounds": {
                "lower": residence_cdf["zero_mass_fraction_lower"],
                "upper": residence_cdf["zero_mass_fraction_upper"],
            },
            "residence_right_censored_unknown_mass_fraction": unknown_fraction,
            "first_failure_frame": int(np.min(first_failure[select & (first_failure >= 0)]))
            if np.any(select & (first_failure >= 0)) else None,
            "first_failure_time_s": float(trace["time"][int(np.min(first_failure[select & (first_failure >= 0)]))])
            if np.any(select & (first_failure >= 0)) else None,
        }
    return rows


def _reliable_at_horizon(trace: dict, horizon: float) -> np.ndarray:
    """Return reliability at the latest committed frame no later than horizon."""
    index = int(np.searchsorted(trace["time"], horizon, side="right") - 1)
    if index < 0:
        return np.zeros(len(trace["source_label"]), dtype=bool)
    return trace["reliable_history"][:index + 1].all(axis=0)


def _path_alignment(left: dict, right: dict, horizon: float) -> dict:
    """Describe the common-time reliability alignment used for paired paths."""
    # A union of saved timestamps with right-continuous hold makes the result
    # independent of which side has the finer output cadence.  The latest
    # sample no later than a query time is used on each side.
    left_times = left["time"][left["time"] <= horizon]
    right_times = right["time"][right["time"] <= horizon]
    grid = np.unique(np.concatenate((left_times, right_times, [0.0, horizon])))
    grid = grid[np.isfinite(grid)]
    left_index = np.searchsorted(left["time"], grid, side="right") - 1
    right_index = np.searchsorted(right["time"], grid, side="right") - 1
    left_index = np.maximum(left_index, 0)
    right_index = np.maximum(right_index, 0)
    left_reliable = np.asarray([
        left["reliable_history"][:int(index) + 1].all(axis=0)
        for index in left_index
    ], dtype=bool)
    right_reliable = np.asarray([
        right["reliable_history"][:int(index) + 1].all(axis=0)
        for index in right_index
    ], dtype=bool)
    common = left_reliable & right_reliable
    return {
        "strategy": "union_of_saved_times_right_continuous_hold",
        "query_times_clipped_to_common_horizon": int(len(grid)),
        "common_horizon_s": float(horizon),
        "left_saved_time_count_in_horizon": int(len(left_times)),
        "right_saved_time_count_in_horizon": int(len(right_times)),
        "common_reliable_at_every_query_time_fraction": float(np.mean(np.all(common, axis=0))),
    }


def _path_comparison(left: dict, right: dict, horizon: float) -> dict:
    weight = np.full(len(left["source_label"]), 1.0 / len(left["source_label"]), dtype=np.float64)
    left_path = _reliable_at_horizon(left, horizon)
    right_path = _reliable_at_horizon(right, horizon)
    common_path = left_path & right_path
    union_path = left_path | right_path
    common_final = left_path & right_path
    def errors(select):
        if not np.any(select):
            return {"seed_count": 0, "weighted_rms_m": None, "weighted_p95_m": None, "max_m": None}
        error = np.linalg.norm(left["position"][select] - right["position"][select], axis=1)
        w = weight[select]
        order = np.argsort(error, kind="mergesort")
        cdf = np.cumsum(w[order]) / np.sum(w)
        return {
            "seed_count": int(np.count_nonzero(select)),
            "weighted_rms_m": float(np.sqrt(np.sum(w * error**2) / np.sum(w))),
            "weighted_p95_m": float(error[order[np.flatnonzero(cdf >= 0.95)[0]]]),
            "max_m": float(np.max(error)),
        }
    by_source = {}
    for source in np.unique(left["source_label"]):
        select = left["source_label"] == source
        by_source[str(int(source))] = {
            "seed_count": int(np.count_nonzero(select)),
            "common_full_path_fraction": float(np.sum(weight[select & common_path]) / np.sum(weight[select])),
            "union_full_path_fraction": float(np.sum(weight[select & union_path]) / np.sum(weight[select])),
            "common_final_reliable_fraction": float(np.sum(weight[select & common_final]) / np.sum(weight[select])),
            "endpoint_error_common_full_path": errors(select & common_path),
            "endpoint_error_common_final_reliable": errors(select & common_final),
        }
    return {
        "alignment": _path_alignment(left, right, horizon),
        "common_full_path_seed_count": int(np.count_nonzero(common_path)),
        "union_full_path_seed_count": int(np.count_nonzero(union_path)),
        "common_full_path_fraction": float(np.sum(weight[common_path])),
        "union_full_path_fraction": float(np.sum(weight[union_path])),
        "common_final_reliable_seed_count": int(np.count_nonzero(common_final)),
        "common_final_reliable_fraction": float(np.sum(weight[common_final])),
        "by_source": by_source,
    }


def _unknown_history(trace: dict) -> dict:
    weight = np.full(len(trace["source_label"]), 1.0 / len(trace["source_label"]), dtype=np.float64)
    fractions = np.sum(trace["unknown_history"] * weight[None, :], axis=1)
    return {"time_s": trace["time"].tolist(), "unknown_mass_fraction": fractions.tolist()}


def compare_traces(left_path: str | Path, right_path: str | Path,
                   output: str | Path | None = None, *,
                   comparison_mode: str = "same_source_cadence",
                   provenance: Mapping | str | Path | None = None) -> dict:
    left = _load_trace(left_path)
    right = _load_trace(right_path)
    binding = _validate_pair(left, right, comparison_mode, provenance)
    left_rows, right_rows = _source_rows(left), _source_rows(right)
    if set(left_rows) != set(right_rows):
        raise ValueError("source groups differ")
    source_comparison = {}
    for source in sorted(left_rows):
        l, r = left_rows[source], right_rows[source]
        first_sup = _cdf_sup_difference(
            l["first_passage_cdf_bounds"], r["first_passage_cdf_bounds"]
        )
        return_sup = _cdf_sup_difference(
            l["return_cdf_bounds"], r["return_cdf_bounds"]
        )
        residence_sup = _cdf_sup_difference(
            l["residence_cdf_bounds"], r["residence_cdf_bounds"]
        )
        source_comparison[source] = {
            "left": l,
            "right": r,
            "difference": {
                "final_unknown_fraction_right_minus_left": r["final_unknown_fraction"] - l["final_unknown_fraction"],
                "first_passage_lower_fraction_right_minus_left": r["first_passage_event_fraction_bounds"]["lower"] - l["first_passage_event_fraction_bounds"]["lower"],
                "first_passage_upper_fraction_right_minus_left": r["first_passage_event_fraction_bounds"]["upper"] - l["first_passage_event_fraction_bounds"]["upper"],
                "return_lower_fraction_right_minus_left": r["return_event_fraction_bounds"]["lower"] - l["return_event_fraction_bounds"]["lower"],
                "return_upper_fraction_right_minus_left": r["return_event_fraction_bounds"]["upper"] - l["return_event_fraction_bounds"]["upper"],
                "residence_lower_mean_s_right_minus_left": r["residence_mean_s_bounds"]["lower"] - l["residence_mean_s_bounds"]["lower"],
                "residence_upper_mean_s_right_minus_left": r["residence_mean_s_bounds"]["upper"] - l["residence_mean_s_bounds"]["upper"],
                "first_passage_cdf_sup_abs_difference_bound": first_sup["sup_abs_difference_bound"],
                "return_cdf_sup_abs_difference_bound": return_sup["sup_abs_difference_bound"],
                "residence_cdf_sup_abs_difference_bound": residence_sup["sup_abs_difference_bound"],
            },
            "cdf_sup_difference_bounds": {
                "first_passage": first_sup,
                "return": return_sup,
                "residence": residence_sup,
            },
        }
    paired_paths = comparison_mode != "independent_seed_axes"
    common_horizon = min(float(left["time"][-1]), float(right["time"][-1]))
    result = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "implementation": {
            "script": str(Path(__file__).resolve()),
            "script_sha256": sha256_file(__file__),
        },
        "comparison_mode": comparison_mode,
        "method_comparison": {
            "status": (
                "explicit_temporal_method_difference"
                if comparison_mode == "temporal_method_comparison"
                else "single_backend_or_registered_scope_comparison"
            ),
            "left_backend": left.get("trace_backend"),
            "right_backend": right.get("trace_backend"),
            "qualification_effect": "none; comparison remains diagnostic-only",
        },
        "status": "diagnostic_only",
        "qualification_claim": "none",
        "material_reliability_status": "uncalibrated; numerical support_unknown is not material reliability",
        "left": {
            "path": left["path"], "sha256": left["sha256"],
            "schema": left["schema"], "committed_frame": left["committed"],
            "time_end_s": float(left["time"][-1]),
            "frame_count": int(len(left["time"])),
            "material_reliability": left["material_reliability"],
        },
        "right": {
            "path": right["path"], "sha256": right["sha256"],
            "schema": right["schema"], "committed_frame": right["committed"],
            "time_end_s": float(right["time"][-1]),
            "frame_count": int(len(right["time"])),
            "material_reliability": right["material_reliability"],
        },
        "common_binding": binding,
        "denominator_policy": {
            "seed_count": int(len(left["source_label"]))
            if len(left["source_label"]) == len(right["source_label"]) else None,
            "left_seed_count": int(len(left["source_label"])),
            "right_seed_count": int(len(right["source_label"])),
            "source_mass": "all geometric seeds, uniform weight 1/N per trace; no source_contact subset",
            "unknown": "permanent_unknown seeds remain in every source denominator",
            "unobserved_events": "event lower bound uses finite observed event times; upper bound adds unresolved unknown mass from its first possible failure time",
            "residence": "all seeds contribute observed residence; support-loss seeds receive conservative remaining-window upper interval; reliable no-contact seeds contribute exact zero",
        },
        "source_comparison": source_comparison,
        "unknown_mass_by_frame": {"left": _unknown_history(left), "right": _unknown_history(right)},
        "mass_closure": {
            "left_max_abs_error": float(np.max(np.abs(left["mass_closure_error"]))),
            "right_max_abs_error": float(np.max(np.abs(right["mass_closure_error"]))),
        },
        "common_reliable_path": (
            _path_comparison(left, right, common_horizon)
            if paired_paths else {
                "status": "not_applicable_independent_seed_axes",
                "reason": "different seed axes are compared only by source-level macro metrics",
            }
        ),
        "comparison_limits": {
            "unknown_gate_1_percent": "reported only; this comparator does not waive or reinterpret it",
            "native_dense_vs_matched010": "right trace may use a direct selected native-frame map; no interpolation-created frame is accepted",
            "t2": "not assessed; source/trace scope and material reliability remain candidate diagnostics",
            "cdf_sup_difference": "interval bound is max(|right_lower-left_upper|, |right_upper-left_lower|) over the union step grid",
            "temporal_method": (
                "v3 versus v1/v2 differences are method diagnostics only; the mode "
                "does not make either trace native-only or qualification evidence"
            ),
        },
    }
    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(_json_value(result), indent=2, sort_keys=True) + "\n")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--comparison-mode", choices=sorted(COMPARISON_MODES),
        default="same_source_cadence",
        help="registered relation between the traces",
    )
    parser.add_argument(
        "--provenance", type=Path,
        help=("registered JSON comparison provenance (required for cross-scope, "
              "independent axes, and temporal_method_comparison)"),
    )
    args = parser.parse_args(argv)
    result = compare_traces(
        args.left, args.right, args.output,
        comparison_mode=args.comparison_mode, provenance=args.provenance,
    )
    compact = {
        "schema": result["schema"], "status": result["status"],
        "left_frames": result["left"]["frame_count"],
        "right_frames": result["right"]["frame_count"],
        "comparison_mode": result["common_binding"]["comparison_mode"],
        "common_full_path_fraction": result["common_reliable_path"].get("common_full_path_fraction"),
        "left_max_unknown": max(result["unknown_mass_by_frame"]["left"]["unknown_mass_fraction"]),
        "right_max_unknown": max(result["unknown_mass_by_frame"]["right"]["unknown_mass_fraction"]),
        "mass_closure": result["mass_closure"],
        "output": str(args.output.resolve()),
    }
    print(json.dumps(compact, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
