#!/usr/bin/env python3
"""Source-bound reference observers and strict v4-label adaptation.

This v6 module is an additive development interface.  It does not modify the
consumed v4/v5 operators or read a scientific trajectory while preparing a
reference.  The real F2-S1 path consumes the already completed scientific-scan
JSON sidecar; point-cloud operators are calibrated independently on a small
manufactured fixture.

The v4 label sidecar has a deliberately coarse ``0/1`` first-passage censor
field.  ``adapt_v4_label_payload`` preserves that provenance and only refines
states when the sidecar (or an explicitly supplied auxiliary observation)
contains enough evidence.  It never guesses initially-inside or failure from
the coarse censor bit.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ds_data02_stage2_native_replay_v5 import (  # noqa: E402
    FIRST_PASSAGE_STATUSES,
    NativeReplayBindingError,
)


OBSERVER_CONFIG_SCHEMA = "ds02.stage2.reference-observer-config.v1"
OBSERVER_RESULT_SCHEMA = "ds02.stage2.reference-observer-result.v1"
CALIBRATION_SCHEMA = "ds02.stage2.reference-observer-calibration.v1"
V4_ADAPTER_SCHEMA = "ds02.stage2.v4-label-adapter.v1"
_HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")


class ObserverBindingError(NativeReplayBindingError):
    """A source, shape, scale, time, or observer binding is not trustworthy."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObserverBindingError(f"{name} must be finite numeric data")
    result = float(value)
    if not math.isfinite(result):
        raise ObserverBindingError(f"{name} must be finite numeric data")
    return result


def _finite_array(value: Any, shape: tuple[int, ...] | None, name: str) -> np.ndarray:
    try:
        result = np.asarray(value, dtype="float64")
    except (TypeError, ValueError) as error:
        raise ObserverBindingError(f"{name} must be numeric") from error
    if shape is not None and result.shape != shape:
        raise ObserverBindingError(f"{name} shape {result.shape} differs from {shape}")
    if not np.isfinite(result).all():
        raise ObserverBindingError(f"{name} contains non-finite data")
    return result


def _sequence(value: Any, name: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ObserverBindingError(f"{name} must be a sequence")
    return list(value)


def _chronological_times(times: Any, name: str = "times_s") -> np.ndarray:
    values = _finite_array(times, None, name).reshape(-1)
    if not len(values) or np.any(np.diff(values) <= 0):
        raise ObserverBindingError(f"{name} must be strictly increasing")
    return values


def _strict_brackets(value: Any) -> list[list[float]]:
    if value is None:
        return []
    brackets = _sequence(value, "saved_brackets")
    result: list[list[float]] = []
    previous_start = -math.inf
    previous_end = -math.inf
    for index, pair in enumerate(brackets):
        values = _sequence(pair, f"saved_brackets[{index}]")
        if len(values) != 2:
            raise ObserverBindingError(f"saved_brackets[{index}] needs two endpoints")
        left, right = (_finite(values[0], f"saved_brackets[{index}][0]"),
                       _finite(values[1], f"saved_brackets[{index}][1]"))
        if not right > left:
            raise ObserverBindingError(f"saved_brackets[{index}] is not increasing")
        if left < previous_start or left < previous_end:
            raise ObserverBindingError("saved brackets must be chronological and non-overlapping")
        result.append([left, right])
        previous_start, previous_end = left, right
    return result


def classify_first_passage_v6(*, initially_inside: bool = False,
                              saved_brackets: Sequence[Sequence[float]] | None = None,
                              crossing_times_s: Sequence[float] | None = None,
                              crossing_count: int | None = None,
                              failed_before_observation: bool = False,
                              event_time_s: float | None = None,
                              hidden_recross_status: str = "UNRESOLVED") -> dict[str, Any]:
    """Classify a first passage using chronological candidates and brackets.

    The earliest candidate determines the first bracket.  Two candidates in
    that bracket are intrinsically ambiguous even when the caller forgets an
    ambiguity flag.  Candidate order is checked instead of silently sorting,
    so a wrong first-order input is visible.  A supplied event time must equal
    the earliest candidate (within a fixed numerical roundoff), which catches
    a wrong-time interpolation while retaining later repeated crossings.
    """
    if not isinstance(initially_inside, bool) or not isinstance(failed_before_observation, bool):
        raise ObserverBindingError("first-passage flags must be boolean")
    if hidden_recross_status not in ("UNRESOLVED", "AUDITED_NONE", "AUDITED_PRESENT"):
        raise ObserverBindingError("unsupported hidden_recross_status")
    brackets = _strict_brackets(saved_brackets)
    raw_candidates = [] if crossing_times_s is None else _sequence(crossing_times_s, "crossing_times_s")
    candidates = [_finite(item, "crossing_times_s") for item in raw_candidates]
    if any(right <= left for left, right in zip(candidates, candidates[1:])):
        raise ObserverBindingError("crossing_times_s must be strictly chronological (min-first order)")
    if crossing_count is not None:
        if isinstance(crossing_count, bool) or not isinstance(crossing_count, int) or crossing_count < 0:
            raise ObserverBindingError("crossing_count must be a nonnegative integer")
        if candidates and crossing_count != len(candidates):
            raise ObserverBindingError("crossing_count differs from crossing candidate count")
    for candidate in candidates:
        if not any(left <= candidate <= right for left, right in brackets):
            raise ObserverBindingError("crossing candidate is outside all saved brackets")

    if initially_inside:
        status = "initially_inside"
        event_time = None
        first_bracket = None
    elif candidates:
        first = candidates[0]
        containing = [pair for pair in brackets if pair[0] <= first <= pair[1]]
        if not containing:
            raise ObserverBindingError("earliest crossing has no saved bracket")
        first_bracket = containing[0]
        in_first = [value for value in candidates if first_bracket[0] <= value <= first_bracket[1]]
        if len(in_first) > 1:
            status = "ambiguous_multiple_crossing"
            event_time = None
        else:
            status = "observed"
            if event_time_s is None:
                event_time = first
            else:
                event_time = _finite(event_time_s, "event_time_s")
                if not math.isclose(event_time, first, rel_tol=0.0, abs_tol=1e-12):
                    raise ObserverBindingError("event_time_s differs from earliest crossing candidate")
            if not first_bracket[0] <= event_time <= first_bracket[1]:
                raise ObserverBindingError("event_time_s is outside the first saved bracket")
    elif failed_before_observation:
        status = "failed_before_observation"
        event_time = None
        first_bracket = brackets[0] if brackets else None
    else:
        status = "right_censored"
        event_time = None
        first_bracket = brackets[0] if brackets else None

    if status != "observed" and event_time_s is not None:
        raise ObserverBindingError(f"{status} must not carry a numeric event time")
    if status == "initially_inside" and event_time_s is not None:
        raise ObserverBindingError("initially_inside must not carry a numeric event time")
    return {
        "status": status,
        "event_time_s": event_time,
        "event_time_interval_s": first_bracket,
        "saved_brackets": brackets,
        "crossing_candidate_times_s": candidates,
        "crossing_count": crossing_count if crossing_count is not None else len(candidates),
        "hidden_recross_status": hidden_recross_status,
        "first_passage_numeric_observed": status == "observed",
    }


def _vector_rows(value: Any, name: str, width: int = 3) -> np.ndarray:
    rows = _finite_array(value, None, name)
    if rows.ndim != 2 or rows.shape[1] != width:
        raise ObserverBindingError(f"{name} must have shape (n,{width})")
    if not len(rows):
        raise ObserverBindingError(f"{name} must not be empty")
    return rows


def adapt_v4_label_payload(payload: Mapping[str, Any], *, event_index: int = 0,
                           initial_inside: Sequence[bool] | None = None,
                           failed_before_observation: Sequence[bool] | None = None,
                           crossing_candidates_s: Sequence[Sequence[float]] | None = None,
                           hidden_recross_status: str = "UNRESOLVED") -> dict[str, Any]:
    """Adapt one v4 event axis without hiding its binary-censor limitation.

    ``payload`` is a mapping of arrays read from the v4 sidecar; this function
    intentionally does not open a real label file.  ``initial_inside`` and
    ``failed_before_observation`` are optional auxiliary evidence.  Without
    them a v4 ``censor=1`` remains a conservative right-censored state and
    the result records that initially-inside/failed-before-observation are
    pending rather than inventing either label.
    """
    if not isinstance(payload, Mapping) or payload.get("schema") not in (None, "ds02.stage2.observation-labels.v2"):
        raise ObserverBindingError("unsupported v4 label payload schema")
    def required(name: str) -> np.ndarray:
        if name not in payload:
            raise ObserverBindingError(f"v4 payload is missing {name}")
        result = np.asarray(payload[name])
        if result.ndim != 1:
            raise ObserverBindingError(f"v4 payload {name} must be one-dimensional")
        return result
    censor = required("first_passage_censor")
    intervals = np.asarray(payload.get("first_passage_interval"))
    chord = required("first_passage_chord_time")
    counts = required("crossing_count")
    if intervals.ndim != 3 or intervals.shape[0] != len(censor) or intervals.shape[2] != 2:
        raise ObserverBindingError("v4 first_passage_interval must have shape (n,event,2)")
    if event_index < 0 or event_index >= intervals.shape[1]:
        raise ObserverBindingError("event_index is outside v4 event axis")
    n = len(censor)
    for name, values in (("chord", chord), ("crossing_count", counts)):
        if len(values) != n:
            raise ObserverBindingError(f"v4 {name} length differs from censor")
    def optional_bool(value: Sequence[bool] | None, name: str) -> list[bool] | None:
        if value is None:
            return None
        values = list(value)
        if len(values) != n or any(not isinstance(item, (bool, np.bool_)) for item in values):
            raise ObserverBindingError(f"{name} must contain n booleans")
        return [bool(item) for item in values]
    inside = optional_bool(initial_inside, "initial_inside")
    failed = optional_bool(failed_before_observation, "failed_before_observation")
    candidates = None if crossing_candidates_s is None else list(crossing_candidates_s)
    if candidates is not None and len(candidates) != n:
        raise ObserverBindingError("crossing_candidates_s length differs from v4 identities")
    records = []
    pending_reasons = set()
    for index in range(n):
        censor_value = int(censor[index])
        count_value = int(counts[index])
        if censor_value not in (0, 1) or count_value < 0:
            raise ObserverBindingError("v4 censor/count contains an invalid value")
        pair = intervals[index, event_index]
        bracket = [] if not np.isfinite(pair).all() else [[float(pair[0]), float(pair[1])]]
        candidate = None if candidates is None else list(candidates[index])
        if candidate is None and count_value > 1:
            # The v4 sidecar proves repetition, but not the order inside the
            # saved bracket.  Keep it explicitly ambiguous.
            candidate = [float(pair[0]), float(pair[1])] if bracket else []
        if candidate is None and censor_value == 0 and count_value == 1:
            if not math.isfinite(float(chord[index])):
                raise ObserverBindingError("v4 observed row has no finite chord time")
            candidate = [float(chord[index])]
        if candidate is not None and count_value == 0 and candidate:
            raise ObserverBindingError("v4 candidate list is nonempty while crossing_count is zero")
        if candidate is not None and count_value and len(candidate) != count_value:
            raise ObserverBindingError("v4 candidate list differs from crossing_count")
        if inside is None and count_value == 0 and censor_value:
            pending_reasons.update(("initially_inside_not_encoded", "failed_before_observation_not_encoded"))
        if failed is not None and failed[index] and count_value:
            raise ObserverBindingError("failed_before_observation cannot have a crossing")
        if censor_value == 0 and count_value == 0:
            raise ObserverBindingError("v4 observed censor bit has zero crossing count")
        if censor_value == 1 and count_value > 0:
            # A v4 producer can retain repeated crossings while its binary
            # censor bit remains non-observed; strict adapter exposes this.
            if candidate is None:
                pending_reasons.add("repeated_crossing_order_not_encoded")
        event_time = None if not math.isfinite(float(chord[index])) else float(chord[index])
        if censor_value == 1 or count_value > 1:
            event_time = None
        record = classify_first_passage_v6(
            initially_inside=inside[index] if inside is not None else False,
            saved_brackets=bracket,
            crossing_times_s=candidate,
            crossing_count=count_value,
            failed_before_observation=failed[index] if failed is not None else False,
            event_time_s=event_time if censor_value == 0 else None,
            hidden_recross_status=hidden_recross_status,
        )
        record.update({
            "identity_index": index,
            "v4_censor": censor_value,
            "v4_censor_semantics": "0=observed_saved_chord;1=not_observed_or_censored",
            "v4_source_schema": "ds02.stage2.observation-labels.v2",
        })
        records.append(record)
    adapter_status = "COMPLETE_DEVELOPMENT_ADAPTER" if not pending_reasons else (
        "PARTIAL_DEVELOPMENT_ADAPTER_PENDING_AUXILIARY_STATE_EVIDENCE")
    return {
        "schema": V4_ADAPTER_SCHEMA,
        "event_index": event_index,
        "records": records,
        "adapter_status": adapter_status,
        "pending_reasons": sorted(pending_reasons),
        "source_limitation": (
            "v4 binary censor cannot distinguish initially_inside from "
            "failed_before_observation without explicit auxiliary evidence"),
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
    }


def validate_observer_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping) or config.get("schema") != OBSERVER_CONFIG_SCHEMA:
        raise ObserverBindingError("unsupported observer config schema")
    if not isinstance(config.get("physical_case_id"), str) or not config["physical_case_id"]:
        raise ObserverBindingError("observer config needs physical_case_id")
    source = config.get("source_binding")
    if not isinstance(source, Mapping) or not isinstance(source.get("scan_path"), str):
        raise ObserverBindingError("observer source_binding.scan_path is required")
    scan_hash = source.get("scan_sha256")
    if not isinstance(scan_hash, str) or not _HEX64.fullmatch(scan_hash):
        raise ObserverBindingError("observer source_binding.scan_sha256 must be SHA-256")
    window = _finite_array(config.get("time_window_s"), (2,), "time_window_s")
    if not window[1] > window[0]:
        raise ObserverBindingError("time_window_s must increase")
    control = _finite(config.get("control_duration_s"), "control_duration_s")
    if not 0 < control <= window[1] - window[0]:
        raise ObserverBindingError("control_duration_s must be positive and inside the baseline")
    scales = config.get("fixed_physical_scales")
    if not isinstance(scales, Mapping):
        raise ObserverBindingError("fixed_physical_scales is required")
    for name in ("position_scale_m", "mass_scale_m", "feature_time_s"):
        if _finite(scales.get(name), f"fixed_physical_scales.{name}") <= 0:
            raise ObserverBindingError(f"fixed_physical_scales.{name} must be nonzero")
    queries = _chronological_times(config.get("query_times_s"), "query_times_s")
    if queries[0] < window[0] or queries[-1] > window[1]:
        raise ObserverBindingError("query_times_s must lie within time_window_s")
    policy = config.get("cross_grid_policy")
    if not isinstance(policy, Mapping) or policy.get("identity_binding") != "source_region_and_mass_distribution":
        raise ObserverBindingError("cross-grid policy must avoid typed particle-ID fitting")
    quantiles = config.get("mass_quantiles")
    if not isinstance(quantiles, Sequence) or isinstance(quantiles, (str, bytes)) or not quantiles:
        raise ObserverBindingError("mass_quantiles are required")
    for index, value in enumerate(quantiles):
        q = _finite(value, f"mass_quantiles[{index}]")
        if not 0 <= q <= 1:
            raise ObserverBindingError("mass quantiles must lie in [0,1]")
    distribution = config.get("mass_distribution")
    if not isinstance(distribution, Mapping):
        raise ObserverBindingError("mass_distribution config is required")
    edges = _chronological_times(distribution.get("normalized_bin_edges"), "normalized_bin_edges")
    if len(edges) < 2:
        raise ObserverBindingError("mass distribution needs at least two bin edges")
    if config.get("tolerance_profile", {}).get("mutable", True):
        raise ObserverBindingError("observer tolerance profile must be frozen")
    return dict(config, _validated_query_times_s=queries.tolist(),
                _validated_bin_edges=edges.tolist())


def _interpolate_rows(times: np.ndarray, rows: Sequence[Mapping[str, Any]], query_times: Sequence[float]) -> list[dict[str, Any]]:
    queries = _finite_array(query_times, None, "query_times_s").reshape(-1)
    if len(queries) and (queries[0] < times[0] or queries[-1] > times[-1]):
        raise ObserverBindingError("query time requests extrapolation")
    if len(queries) and np.any(np.diff(queries) < 0):
        raise ObserverBindingError("query_times_s must be nondecreasing")
    keys = ("active_fluid_mass_kg", "active_fluid_com_m", "active_fluid_mean_velocity_m_s",
            "active_fluid_kinetic_energy_J")
    arrays = {key: [_finite_array(row.get(key), (3,), f"{key}[{i}]") if key.endswith("_m") or key.endswith("_m_s")
                    else _finite(row.get(key), f"{key}[{i}]") for i, row in enumerate(rows)] for key in keys}
    result: list[dict[str, Any]] = []
    for query in queries:
        index = int(np.searchsorted(times, query, side="left"))
        if index == 0:
            left = right = 0
        elif index == len(times):
            left = right = len(times) - 1
        elif math.isclose(float(times[index]), float(query), rel_tol=0.0, abs_tol=1e-14):
            left = right = index
        else:
            left, right = index - 1, index
        fraction = 0.0 if left == right else (float(query) - times[left]) / (times[right] - times[left])
        record: dict[str, Any] = {"time_s": float(query),
                                  "saved_bracket_s": [float(times[left]), float(times[right])],
                                  "interpolation": "saved_frame_exact" if left == right else "linear_saved_frame_bracket"}
        for key in keys:
            left_value, right_value = arrays[key][left], arrays[key][right]
            if isinstance(left_value, np.ndarray):
                value = left_value + fraction * (right_value - left_value)
                record[key] = value.tolist()
            else:
                record[key] = float(left_value + fraction * (right_value - left_value))
        result.append(record)
    return result


def observe_scientific_scan(scan_path: Path | str, config: Mapping[str, Any], *, query_times_s: Sequence[float] | None = None) -> dict[str, Any]:
    """Observe only the completed scan sidecar, never its HDF5 trajectory."""
    validated = validate_observer_config(config)
    path = Path(scan_path).resolve()
    expected_path = Path(str(validated["source_binding"]["scan_path"])).resolve()
    if path != expected_path:
        raise ObserverBindingError("scan path differs from frozen observer config")
    if sha256(path) != validated["source_binding"]["scan_sha256"]:
        raise ObserverBindingError("scientific scan hash differs from frozen observer config")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise ObserverBindingError("unsupported scientific scan schema")
    if payload.get("physical_case_id") != validated["physical_case_id"]:
        raise ObserverBindingError("scientific scan case differs from observer config")
    times = _chronological_times(payload.get("time_s"), "scan.time_s")
    macros = payload.get("macros")
    if not isinstance(macros, list) or len(macros) != len(times):
        raise ObserverBindingError("scan macro/time axes differ")
    for index, row in enumerate(macros):
        if not isinstance(row, Mapping) or not math.isclose(_finite(row.get("time_s"), f"scan.macros[{index}].time_s"), times[index], rel_tol=0.0, abs_tol=1e-12):
            raise ObserverBindingError("scan macro time axis differs from source time axis")
    frozen_queries = np.asarray(validated["_validated_query_times_s"], dtype="float64")
    queries = frozen_queries if query_times_s is None else _finite_array(query_times_s, None, "query_times_s").reshape(-1)
    if not np.array_equal(queries, frozen_queries):
        raise ObserverBindingError("query times differ from frozen shared observer times")
    observations = _interpolate_rows(times, macros, queries.tolist())
    ledgers = payload.get("type_ledgers", {})
    fluid = ledgers.get("fluid", {}) if isinstance(ledgers, Mapping) else {}
    initial_mass = _finite(fluid.get("typed_initial_mass_kg"), "fluid.typed_initial_mass_kg")
    missing_records = payload.get("missing_id_records", [])
    missing_initial_mass = sum(_finite(item.get("initial_mass_kg"), "missing.initial_mass_kg")
                               for item in missing_records if isinstance(item, Mapping))
    for row in observations:
        row["active_fluid_mass_fraction"] = row["active_fluid_mass_kg"] / initial_mass
        row["missing_mass_kg"] = max(0.0, initial_mass - row["active_fluid_mass_kg"])
        row["missing_mass_bucket"] = "unresolved_missing_identity_mass"
    return {
        "schema": OBSERVER_RESULT_SCHEMA,
        "physical_case_id": validated["physical_case_id"],
        "source": {"path": str(path), "sha256": sha256(path), "read_scope": "scientific_scan_sidecar_only",
                   "trajectory_hdf5_read": False},
        "baseline": {"time_window_s": validated["time_window_s"],
                     "control_duration_s": validated["control_duration_s"],
                     "initial_fluid_mass_kg": initial_mass,
                     "missing_identity_initial_mass_kg": missing_initial_mass},
        "observations": observations,
        "mass_quantile_front": {"status": "PENDING_PARTICLE_DISTRIBUTION_WINDOW",
                                "reason": "scan sidecar stores COM/velocity/KE macros but no particle spatial distribution"},
        "fixed_scale_mass_distribution": {"status": "PENDING_PARTICLE_DISTRIBUTION_WINDOW",
                                           "reason": "no spatial bins are inferred from a macro-only sidecar"},
        "cross_grid_identity": validated["cross_grid_policy"]["identity_binding"],
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
        "model_invoked": False,
    }


def observe_point_cloud(points: Any, masses: Any, velocities: Any, *,
                        axis: int, quantiles: Sequence[float],
                        physical_scale_m: float, normalized_bin_edges: Sequence[float],
                        missing_mass_kg: float = 0.0) -> dict[str, Any]:
    """Compute grid-independent mass-weighted observables from a point cloud."""
    positions = _vector_rows(points, "points")
    velocity = _vector_rows(velocities, "velocities")
    weights = _finite_array(masses, (len(positions),), "masses")
    if np.any(weights <= 0):
        raise ObserverBindingError("known point masses must be positive")
    if isinstance(axis, bool) or not isinstance(axis, int) or axis not in (0, 1, 2):
        raise ObserverBindingError("axis must be 0, 1, or 2")
    scale = _finite(physical_scale_m, "physical_scale_m")
    if scale <= 0:
        raise ObserverBindingError("physical_scale_m must be nonzero")
    edges = _chronological_times(normalized_bin_edges, "normalized_bin_edges")
    known_mass = float(weights.sum())
    total_mass = known_mass + _finite(missing_mass_kg, "missing_mass_kg")
    if total_mass <= 0:
        raise ObserverBindingError("total mass must be positive")
    com = (positions * weights[:, None]).sum(axis=0) / known_mass
    mean_velocity = (velocity * weights[:, None]).sum(axis=0) / known_mass
    kinetic_energy = float(0.5 * (weights * (velocity * velocity).sum(axis=1)).sum())
    coordinate = positions[:, axis] / scale
    bins = np.zeros(len(edges) - 1, dtype="float64")
    for index in range(len(bins)):
        mask = (coordinate >= edges[index]) & (coordinate < edges[index + 1])
        if index == len(bins) - 1:
            mask |= coordinate == edges[index + 1]
        bins[index] = float(weights[mask].sum())
    quantile_values = {}
    order = np.argsort(coordinate, kind="stable")
    sorted_coordinates, sorted_weights = coordinate[order], weights[order]
    cumulative = np.cumsum(sorted_weights)
    for raw_q in quantiles:
        q = _finite(raw_q, "mass_quantile")
        if not 0 <= q <= 1:
            raise ObserverBindingError("mass quantile must lie in [0,1]")
        target = q * known_mass
        index = int(np.searchsorted(cumulative, target, side="left"))
        index = min(index, len(sorted_coordinates) - 1)
        quantile_values[str(q)] = float(sorted_coordinates[index] * scale)
    return {
        "schema": OBSERVER_RESULT_SCHEMA,
        "known_mass_kg": known_mass,
        "missing_mass_kg": float(missing_mass_kg),
        "total_mass_denominator_kg": total_mass,
        "mass_weighted_com_m": com.tolist(),
        "mass_weighted_mean_velocity_m_s": mean_velocity.tolist(),
        "mass_weighted_kinetic_energy_J": kinetic_energy,
        "mass_quantile_front_m": quantile_values,
        "fixed_scale_m": scale,
        "mass_distribution_normalized_edges": edges.tolist(),
        "mass_distribution_kg": bins.tolist(),
        "mass_distribution_missing_bucket_kg": float(missing_mass_kg),
        "identity_binding": "coordinates_and_mass_distribution; no particle IDs",
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
        "model_invoked": False,
    }


def manufactured_observer_calibration(config: Mapping[str, Any]) -> dict[str, Any]:
    """Run an independent point-cloud calibration with hand-authored values."""
    validate_observer_config(config)
    points = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
    masses = [1.0, 2.0, 1.0]
    velocities = [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]]
    actual = observe_point_cloud(points, masses, velocities, axis=0, quantiles=[0.5, 0.75, 1.0],
                                 physical_scale_m=2.0,
                                 normalized_bin_edges=[-0.25, 0.25, 0.75, 1.25],
                                 missing_mass_kg=0.5)
    expected = {
        "mass_weighted_com_m": [1.0, 0.0, 0.0],
        "mass_weighted_mean_velocity_m_s": [0.25, 1.0, 0.75],
        "mass_weighted_kinetic_energy_J": 9.0,
        "mass_quantile_front_m": {"0.5": 1.0, "0.75": 1.0, "1.0": 2.0},
        "mass_distribution_kg": [1.0, 2.0, 1.0],
        "mass_distribution_missing_bucket_kg": 0.5,
        "total_mass_denominator_kg": 4.5,
    }
    checks = []
    for name, expected_value in expected.items():
        actual_value = actual[name]
        if isinstance(expected_value, Mapping):
            passed = (isinstance(actual_value, Mapping)
                      and set(actual_value) == set(expected_value)
                      and all(math.isclose(float(actual_value[key]), float(expected_value[key]),
                                           rel_tol=0.0, abs_tol=1e-12)
                              for key in expected_value))
        else:
            passed = bool(np.allclose(np.asarray(actual_value, dtype="float64"),
                                      np.asarray(expected_value, dtype="float64"), rtol=0.0, atol=1e-12))
        checks.append({"name": name, "status": "PASS" if passed else "FAIL",
                       "expected": expected_value, "actual": actual_value})
    failed = [row["name"] for row in checks if row["status"] != "PASS"]
    return {
        "schema": CALIBRATION_SCHEMA,
        "status": "PASS_MANUFACTURED_OBSERVER" if not failed else "FAIL_MANUFACTURED_OBSERVER",
        "checks": checks,
        "failures": failed,
        "fixture_scope": "three point cloud; fixed 2 m scale; explicit 0.5 kg missing bucket",
        "time_interpolation_scope": "validated separately by source-bound query interface",
        "model_invoked": False,
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification_status": "UNKNOWN",
    }
