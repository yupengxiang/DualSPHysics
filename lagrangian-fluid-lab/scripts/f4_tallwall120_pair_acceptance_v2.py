"""Proposed, diagnostic-only paired acceptance metrics for F4 tallwall120.

This module is intentionally additive to the v1 sidecar validator.  It compares
two caller-supplied, JSON-like summaries and does not open HDF5, verify source
files, write receipts, or grant scientific qualification.  Source, trace,
generation, checkpoint, canonical output-manifest, and canonical summary
digests must be supplied independently by an upstream verifier.  The numerical
thresholds below are a versioned design proposal, not a registered F4
qualification policy; a diagnostic pass must not be interpreted as T2.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re


PAIR_SCHEMA = "core.material.f4.tallwall120.pair-diagnostic.v2"
RESULT_SCHEMA = "core.material.f4.tallwall120.pair-comparison.v2"
POLICY_ID = "F4_tallwall120_paired_diagnostic_proposal_v1"
GENERATION_SCHEMA = "core.material.f4.tallwall120.generation.v1"
CHECKPOINT_SCHEMA = "core.material.f4.tallwall120.checkpoint.v2"
OUTPUT_MANIFEST_SCHEMA = "core.material.f4.tallwall120.output-manifest.v1"

FAMILY = "F4"
CASE_ID = "F4_mdbc_laminar_nu1e6_tallwall120_v1"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
REVISION_ID = "F4_tallwall120_material_baseline24_v1"
RECIPE_ID = "F4_tallwall120_material_overlay_baseline24_v1"
IDENTITY = {
    "family": FAMILY,
    "case_id": CASE_ID,
    "scope_id": SCOPE_ID,
    "revision_id": REVISION_ID,
    "recipe_id": RECIPE_ID,
}

# The old F4 contract supplies the initial horizon and the one-time doubling
# rule.  T remains the initial 4.34 s horizon even when an event window extends.
T_S = 4.34
MAX_EVENT_WINDOW_S = 8.68
GRAVITY_FOLLOW_S = 0.3497487083913345
UNKNOWN_FRACTION_LIMIT = 0.01
CDF_GAP_LIMIT = 0.02
RESIDENCE_MEAN_GAP_LIMIT_S = 0.02 * T_S
EVENT_MAE_LIMIT_S = 0.0025 * T_S
DETECTION_ERROR_BUDGET_S = 0.20 * EVENT_MAE_LIMIT_S
ENDPOINT_TOLERANCE_M = 1.0e-8
SAVED_CHORD_CROSSINGS_ALLOWED = 0

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVENTS = ("contact", "upward", "return")
_CDF_NAMES = _EVENTS + ("residence",)
_GATES = (
    "identity", "source_hash_binding", "artifact_hash_bindings",
    "output_coverage", "source_denominator", "unknown_bound",
    "event_window", "right_censor_free", "cdf_gap",
    "residence_mean_gap", "event_time_mae", "event_detection_error",
    "endpoint_tolerance", "saved_chord_tolerance",
)


def _number(value, name, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def _integer(value, name, *, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _list(value, name):
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _json_like(value, path="payload", active=None):
    if active is None:
        active = set()
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        marker = id(value)
        if marker in active:
            raise ValueError(f"{path} contains a cycle")
        active.add(marker)
        try:
            for index, item in enumerate(value):
                _json_like(item, f"{path}[{index}]", active)
        finally:
            active.remove(marker)
        return
    if isinstance(value, dict):
        marker = id(value)
        if marker in active:
            raise ValueError(f"{path} contains a cycle")
        active.add(marker)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} has a non-string key")
                _json_like(item, f"{path}.{key}", active)
        finally:
            active.remove(marker)
        return
    raise ValueError(f"{path} is not JSON-like")


def _sha(value, name):
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cdf(value, name, window_end):
    value = _object(value, name)
    x = _list(value.get("x_s"), name + ".x_s")
    lower = _list(value.get("lower"), name + ".lower")
    upper = _list(value.get("upper"), name + ".upper")
    if not x or len(x) != len(lower) or len(x) != len(upper):
        raise ValueError(name + " arrays must be non-empty and aligned")
    x = [_number(item, name + ".x_s", minimum=0.0, maximum=window_end) for item in x]
    lower = [_number(item, name + ".lower", minimum=0.0, maximum=1.0) for item in lower]
    upper = [_number(item, name + ".upper", minimum=0.0, maximum=1.0) for item in upper]
    if x[0] != 0.0 or any(b <= a for a, b in zip(x, x[1:])):
        raise ValueError(name + ".x_s must start at zero and increase strictly")
    if any(lo > hi for lo, hi in zip(lower, upper)):
        raise ValueError(name + " lower bound exceeds upper bound")
    if any(b < a for a, b in zip(lower, lower[1:])) or any(b < a for a, b in zip(upper, upper[1:])):
        raise ValueError(name + " bounds must be non-decreasing")
    return {"x_s": x, "lower": lower, "upper": upper}


def _cdf_at(curve, x, bound):
    index = bisect.bisect_right(curve["x_s"], x) - 1
    return curve[bound][max(0, index)]


def _cdf_gap(left, right, window_end):
    grid = sorted(set((0.0, window_end, *left["x_s"], *right["x_s"])))
    return max(
        max(
            abs(_cdf_at(left, x, "lower") - _cdf_at(right, x, "upper")),
            abs(_cdf_at(left, x, "upper") - _cdf_at(right, x, "lower")),
        )
        for x in grid
    )


def _assert_curve_matches(actual, expected, name):
    if len(actual["x_s"]) != len(expected["x_s"]):
        raise ValueError(name + " does not contain every derived change point")
    for field in ("x_s", "lower", "upper"):
        if len(actual[field]) != len(expected[field]) or any(
            abs(left - right) > 1.0e-9 for left, right in zip(actual[field], expected[field])
        ):
            raise ValueError(name + " does not match the canonical per-tracer records")


def _derive_event_curve(records, event_name, source_mass, window_end):
    observed = []
    unresolved = []
    for tracer_id, record in records.items():
        event_time = record["event_times_s"][event_name]
        if event_time is not None:
            observed.append((event_time, record["weight_kg"]))
        elif record["unknown"] and record["first_unreliable_time_s"] is not None:
            unresolved.append((record["first_unreliable_time_s"], record["weight_kg"]))
    x_values = sorted({0.0, window_end, *(time for time, _ in observed), *(time for time, _ in unresolved)})
    lower = []
    upper = []
    for x in x_values:
        lo = sum(weight for time, weight in observed if time <= x) / source_mass
        hi = lo + sum(weight for possible, weight in unresolved if possible <= x) / source_mass
        lower.append(lo)
        upper.append(hi)
    return {"x_s": x_values, "lower": lower, "upper": upper}


def _derive_residence_curve(records, source_mass):
    intervals = [record["residence_interval_s"] | {"weight_kg": record["weight_kg"]} for record in records.values()]
    x_values = sorted({0.0, *(row["lower"] for row in intervals), *(row["upper"] for row in intervals)})
    lower = [
        sum(row["weight_kg"] for row in intervals if row["upper"] <= x) / source_mass
        for x in x_values
    ]
    upper = [
        sum(row["weight_kg"] for row in intervals if row["lower"] <= x) / source_mass
        for x in x_values
    ]
    mean = {
        "lower": sum(row["weight_kg"] * row["lower"] for row in intervals) / source_mass,
        "upper": sum(row["weight_kg"] * row["upper"] for row in intervals) / source_mass,
    }
    return {"cdf": {"x_s": x_values, "lower": lower, "upper": upper}, "mean": mean}


def _identity(value, name):
    if _object(value, name) != IDENTITY:
        raise ValueError(name + " does not match the active F4 tallwall120 scope")
    return dict(IDENTITY)


def _snapshot(value, name, identity, expected_source_sha256, expected_artifact_sha256, event_window):
    value = _object(value, name)
    if _identity(value.get("identity"), name + ".identity") != identity:
        raise ValueError(name + " identity mismatch")
    if _object(value.get("event_window"), name + ".event_window") != event_window:
        raise ValueError(name + " event window is not bound by its canonical summary")
    source_sha = _sha(value.get("source_sha256"), name + ".source_sha256")
    if source_sha != expected_source_sha256:
        raise ValueError(name + " source SHA-256 does not match the externally bound source")

    hashes = _object(value.get("artifact_hashes"), name + ".artifact_hashes")
    checked_hashes = {}
    for kind, schema in (("generation", GENERATION_SCHEMA), ("checkpoint", CHECKPOINT_SCHEMA)):
        entry = _object(hashes.get(kind), name + ".artifact_hashes." + kind)
        if entry.get("schema") != schema:
            raise ValueError(name + " " + kind + " schema mismatch")
        digest = _sha(entry.get("sha256"), kind + ".sha256")
        bound = _sha(entry.get("bound_sha256"), kind + ".bound_sha256")
        expected_digest = _sha(expected_artifact_sha256.get(kind), "externally_bound_" + kind + "_sha256")
        if digest != bound or digest != expected_digest:
            raise ValueError(name + " " + kind + " SHA-256 binding mismatch")
        if _identity(entry.get("identity"), kind + ".identity") != identity:
            raise ValueError(name + " " + kind + " identity mismatch")
        checked_hashes[kind] = digest

    trace_output_sha = _sha(value.get("trace_output_sha256"), name + ".trace_output_sha256")
    expected_trace_output_sha = _sha(
        expected_artifact_sha256.get("trace_output"), "externally_bound_trace_output_sha256"
    )
    if trace_output_sha != expected_trace_output_sha:
        raise ValueError(name + " trace output SHA-256 does not match its external binding")
    checked_hashes["trace_output"] = trace_output_sha

    manifest = _object(value.get("output_manifest"), name + ".output_manifest")
    if manifest.get("schema") != OUTPUT_MANIFEST_SCHEMA:
        raise ValueError(name + " output manifest schema mismatch")
    if _identity(manifest.get("identity"), name + ".output_manifest.identity") != identity:
        raise ValueError(name + " output manifest identity mismatch")
    manifest_body = _object(manifest.get("body"), name + ".output_manifest.body")
    manifest_artifacts = _object(manifest_body.get("artifact_hashes"), name + ".output_manifest.body.artifact_hashes")
    expected_manifest_artifacts = {
        "generation": checked_hashes["generation"],
        "checkpoint": checked_hashes["checkpoint"],
        "trace_output": checked_hashes["trace_output"],
    }
    if manifest_artifacts != expected_manifest_artifacts:
        raise ValueError(name + " output manifest does not bind generation/checkpoint/trace digests")
    manifest_digest = _sha(manifest.get("body_sha256"), name + ".output_manifest.body_sha256")
    manifest_bound = _sha(manifest.get("bound_sha256"), name + ".output_manifest.bound_sha256")
    expected_manifest_digest = _sha(
        expected_artifact_sha256.get("output_manifest"), "externally_bound_output_manifest_sha256"
    )
    if (
        _canonical_sha256(manifest_body) != manifest_digest
        or manifest_digest != manifest_bound
        or manifest_digest != expected_manifest_digest
    ):
        raise ValueError(name + " canonical output-manifest SHA-256 binding mismatch")
    if _object(manifest_body.get("event_window"), name + ".output_manifest.body.event_window") != event_window:
        raise ValueError(name + " event window is not bound by the external output manifest")
    checked_hashes["output_manifest"] = manifest_digest

    coverage = manifest_body
    if _sha(coverage.get("source_sha256"), name + ".output_coverage.source_sha256") != source_sha:
        raise ValueError(name + " output coverage source hash mismatch")
    frame_count = _integer(coverage.get("frame_count"), "frame_count", minimum=1)
    expected_frame_count = _integer(coverage.get("expected_frame_count"), "expected_frame_count", minimum=1)
    seed_count = _integer(coverage.get("seed_count"), "seed_count", minimum=1)
    expected_seed_count = _integer(coverage.get("expected_seed_count"), "expected_seed_count", minimum=1)
    start = _number(coverage.get("time_start_s"), "time_start_s", minimum=0.0)
    end = _number(coverage.get("time_end_s"), "time_end_s", minimum=0.0)
    interval = _number(coverage.get("native_output_interval_s"), "native_output_interval_s", minimum=0.0)
    if interval <= 0.0 or start != 0.0 or end != event_window["actual_endpoint_s"]:
        raise ValueError(name + " output time coverage does not match the event window")
    expected_by_endpoint = math.floor(end / interval + 0.5) + 1
    reachable_endpoint = (expected_by_endpoint - 1) * interval
    reachability_tolerance = max(1.0e-8, min(1.0e-5, interval * 0.002))
    if (
        expected_frame_count != expected_by_endpoint
        or frame_count != expected_by_endpoint
        or abs(end - reachable_endpoint) > reachability_tolerance
    ):
        raise ValueError(name + " output frame count/endpoint is not reachable from its output interval")

    endpoint_error = _number(value.get("endpoint_max_error_m"), "endpoint_max_error_m", minimum=0.0)
    crossings = _integer(value.get("saved_chord_crossings"), "saved_chord_crossings", minimum=0)
    denominator = _object(value.get("source_denominator"), name + ".source_denominator")
    summary_body = {
        "identity": identity,
        "source_sha256": source_sha,
        "event_window": event_window,
        "artifact_bindings": {
            **checked_hashes,
            "output_manifest": manifest_digest,
        },
        "endpoint_max_error_m": endpoint_error,
        "saved_chord_crossings": crossings,
        "source_denominator": denominator,
    }
    summary_digest = _canonical_sha256(summary_body)
    summary_binding = _object(value.get("summary_binding"), name + ".summary_binding")
    summary_declared = _sha(summary_binding.get("body_sha256"), name + ".summary_binding.body_sha256")
    summary_bound = _sha(summary_binding.get("bound_sha256"), name + ".summary_binding.bound_sha256")
    expected_summary = _sha(expected_artifact_sha256.get("summary"), "externally_bound_summary_sha256")
    if summary_declared != summary_digest or summary_bound != summary_digest or summary_digest != expected_summary:
        raise ValueError(name + " canonical diagnostic-summary SHA-256 binding mismatch")
    checked_hashes["summary"] = summary_digest
    if denominator.get("denominator_policy") != "all_initial_mass":
        raise ValueError(name + " source denominator must be all_initial_mass")
    total_mass = _number(denominator.get("total_initial_mass_kg"), "total_initial_mass_kg", minimum=0.0)
    if total_mass <= 0.0:
        raise ValueError(name + " total initial mass must be positive")
    source_rows = _list(denominator.get("source_rows"), name + ".source_rows")
    if not source_rows:
        raise ValueError(name + " source_rows must not be empty")

    normalized_rows = {}
    mass_sum = 0.0
    for index, row in enumerate(source_rows):
        row = _object(row, f"{name}.source_rows[{index}]")
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id must be a non-empty string")
        if source_id in normalized_rows:
            raise ValueError("duplicate source_id")
        mass = _number(row.get("initial_mass_kg"), "initial_mass_kg", minimum=0.0)
        if mass <= 0.0:
            raise ValueError("initial_mass_kg must be positive")
        if set(row) != {
            "source_id", "initial_mass_kg", "unknown_fraction_max", "tracer_records",
            "cdf_bounds", "residence_mean_s_bounds",
        }:
            raise ValueError("source row fields do not match the paired diagnostic schema")
        unknown = _number(row.get("unknown_fraction_max"), "unknown_fraction_max", minimum=0.0, maximum=1.0)
        tracer_payload = _list(row.get("tracer_records"), source_id + ".tracer_records")
        if not tracer_payload:
            raise ValueError(source_id + " tracer_records must not be empty")
        tracer_records = {}
        normalized_samples = {event_name: {} for event_name in _EVENTS}
        tracer_mass = 0.0
        unknown_mass = 0.0
        for tracer_index, tracer in enumerate(tracer_payload):
            tracer = _object(tracer, f"{source_id}.tracer_records[{tracer_index}]")
            if set(tracer) != {
                "tracer_id", "weight_kg", "unknown", "first_unreliable_time_s",
                "event_times_s", "detection_error_bounds_s", "residence_interval_s",
            }:
                raise ValueError("tracer record fields do not match the paired diagnostic schema")
            tracer_id = tracer.get("tracer_id")
            if not isinstance(tracer_id, str) or not tracer_id or tracer_id in tracer_records:
                raise ValueError("tracer_id must be non-empty and unique within its source")
            tracer_weight = _number(tracer.get("weight_kg"), "tracer weight_kg", minimum=0.0)
            if tracer_weight <= 0.0:
                raise ValueError("tracer weight_kg must be positive")
            is_unknown = tracer.get("unknown")
            if not isinstance(is_unknown, bool):
                raise ValueError("tracer unknown flag must be boolean")
            first_unreliable = tracer.get("first_unreliable_time_s")
            if first_unreliable is not None:
                first_unreliable = _number(
                    first_unreliable, "first_unreliable_time_s", minimum=0.0,
                    maximum=event_window["actual_endpoint_s"],
                )
            if not is_unknown and first_unreliable is not None:
                raise ValueError("reliable tracer cannot have a first_unreliable_time_s")
            if is_unknown and first_unreliable is None:
                raise ValueError("unknown tracer must declare its first_unreliable_time_s")
            times_payload = _object(tracer.get("event_times_s"), "event_times_s")
            errors_payload = _object(tracer.get("detection_error_bounds_s"), "detection_error_bounds_s")
            if set(times_payload) != set(_EVENTS) or set(errors_payload) != set(_EVENTS):
                raise ValueError("tracer event time/error fields must exactly name contact/upward/return")
            event_times = {}
            detection_errors = {}
            for event_name in _EVENTS:
                time_value = times_payload[event_name]
                error_value = errors_payload[event_name]
                if time_value is None:
                    if error_value is not None:
                        raise ValueError("unobserved event cannot carry a detection error bound")
                    event_times[event_name] = None
                    detection_errors[event_name] = None
                    continue
                event_time = _number(
                    time_value, event_name + "_time_s", minimum=0.0,
                    maximum=event_window["actual_endpoint_s"],
                )
                if event_time <= 0.0:
                    raise ValueError("F4 contact/upward/return events must occur after t=0")
                if is_unknown and event_time > first_unreliable:
                    raise ValueError("observed event occurs after the tracer first became unreliable")
                error = _number(error_value, event_name + "_detection_error_bound_s", minimum=0.0)
                event_times[event_name] = event_time
                detection_errors[event_name] = error
                normalized_samples[event_name][tracer_id] = {
                    "weight_kg": tracer_weight,
                    "time_s": event_time,
                    "detection_error_bound_s": error,
                }
            contact_time = event_times["contact"]
            upward_time = event_times["upward"]
            return_time = event_times["return"]
            if upward_time is not None and (contact_time is None or contact_time >= upward_time):
                raise ValueError("contact/upward event samples violate physical event order")
            if return_time is not None and (upward_time is None or upward_time >= return_time):
                raise ValueError("upward/return event samples violate physical event order")

            residence = _object(tracer.get("residence_interval_s"), "residence_interval_s")
            if set(residence) != {"lower", "upper"}:
                raise ValueError("residence interval must declare exactly lower and upper")
            residence_lower = _number(residence.get("lower"), "residence lower_s", minimum=0.0)
            residence_upper = _number(
                residence.get("upper"), "residence upper_s", minimum=residence_lower,
                maximum=event_window["actual_endpoint_s"],
            )
            if not is_unknown and residence_lower != residence_upper:
                raise ValueError("reliable tracer cannot carry a residence uncertainty interval")
            tracer_records[tracer_id] = {
                "weight_kg": tracer_weight,
                "unknown": is_unknown,
                "first_unreliable_time_s": first_unreliable,
                "event_times_s": event_times,
                "detection_error_bounds_s": detection_errors,
                "residence_interval_s": {"lower": residence_lower, "upper": residence_upper},
            }
            tracer_mass += tracer_weight
            if is_unknown:
                unknown_mass += tracer_weight
        if abs(tracer_mass - mass) > max(1.0e-12, mass * 1.0e-12):
            raise ValueError("per-tracer records do not close the all-initial-mass source denominator")
        if abs(unknown_mass / mass - unknown) > 1.0e-9:
            raise ValueError("unknown_fraction_max does not match per-tracer unknown mass")

        cdfs = _object(row.get("cdf_bounds"), source_id + ".cdf_bounds")
        if set(cdfs) != set(_CDF_NAMES):
            raise ValueError("CDF fields must exactly name contact/upward/return/residence")
        normalized_cdfs = {
            event_name: _cdf(cdfs.get(event_name), source_id + "." + event_name + ".cdf", event_window["actual_endpoint_s"])
            for event_name in _CDF_NAMES
        }
        for event_name in _EVENTS:
            _assert_curve_matches(
                normalized_cdfs[event_name],
                _derive_event_curve(tracer_records, event_name, mass, event_window["actual_endpoint_s"]),
                source_id + "." + event_name + ".cdf",
            )
        expected_residence = _derive_residence_curve(tracer_records, mass)
        _assert_curve_matches(
            normalized_cdfs["residence"], expected_residence["cdf"], source_id + ".residence.cdf"
        )
        residence_bounds = _object(row.get("residence_mean_s_bounds"), source_id + ".residence_mean_s_bounds")
        residence_lower = _number(residence_bounds.get("lower"), "residence mean lower", minimum=0.0)
        residence_upper = _number(residence_bounds.get("upper"), "residence mean upper", minimum=residence_lower)
        if (
            residence_upper > event_window["actual_endpoint_s"] + 1.0e-9
            or abs(residence_lower - expected_residence["mean"]["lower"]) > 1.0e-9
            or abs(residence_upper - expected_residence["mean"]["upper"]) > 1.0e-9
        ):
            raise ValueError("residence mean bounds do not match the canonical per-tracer residence distribution")
        for event_name, curve in normalized_cdfs.items():
            if any(hi - lo > unknown + 1.0e-9 for lo, hi in zip(curve["lower"], curve["upper"])):
                raise ValueError(event_name + " CDF uncertainty exceeds its all-initial-mass unknown bound")
        if residence_upper - residence_lower > unknown * event_window["actual_endpoint_s"] + 1.0e-9:
            raise ValueError("residence mean interval width exceeds its unknown-mass/time bound")
        normalized_rows[source_id] = {
            "initial_mass_kg": mass,
            "unknown_fraction_max": unknown,
            "cdf_bounds": normalized_cdfs,
            "residence_mean_s_bounds": {"lower": residence_lower, "upper": residence_upper},
            "event_samples": normalized_samples,
            "tracer_records": tracer_records,
        }
        mass_sum += mass
    if abs(mass_sum - total_mass) > max(1.0e-12, total_mass * 1.0e-12):
        raise ValueError(name + " source rows do not close total initial mass")
    if sum(len(row["tracer_records"]) for row in normalized_rows.values()) != seed_count:
        raise ValueError(name + " manifest seed_count does not match per-source tracer records")

    return {
        "source_sha256": source_sha,
        "artifact_hashes": checked_hashes,
        "output_coverage": {
            "complete": coverage.get("complete") is True,
            "frame_count": frame_count,
            "expected_frame_count": expected_frame_count,
            "seed_count": seed_count,
            "expected_seed_count": expected_seed_count,
            "time_start_s": start,
            "time_end_s": end,
            "native_output_interval_s": interval,
        },
        "endpoint_max_error_m": endpoint_error,
        "saved_chord_crossings": crossings,
        "total_initial_mass_kg": total_mass,
        "source_rows": normalized_rows,
    }


def _event_window(value):
    value = _object(value, "event_window")
    if _number(value.get("normalization_T_s"), "normalization_T_s", minimum=0.0) != T_S:
        raise ValueError("normalization T must be the fixed 4.34 s F4 initial horizon")
    nominal = _number(value.get("nominal_horizon_s"), "nominal_horizon_s", minimum=0.0)
    if nominal not in (T_S, MAX_EVENT_WINDOW_S):
        raise ValueError("nominal event horizon must be 4.34 s or the one-time 8.68 s extension")
    actual = _number(value.get("actual_endpoint_s"), "actual_endpoint_s", minimum=0.0)
    interval = _number(value.get("native_output_interval_s"), "native_output_interval_s", minimum=0.0)
    if interval <= 0.0 or actual < nominal or actual - nominal > interval:
        raise ValueError("actual event endpoint is outside the nominal horizon/output-interval bound")
    extension_count = _integer(value.get("extension_count"), "extension_count", minimum=0)
    extended = nominal == MAX_EVENT_WINDOW_S
    if extension_count != int(extended):
        raise ValueError("event extension count is inconsistent with nominal horizon")
    initial_censored = value.get("initial_window_censored")
    if not isinstance(initial_censored, bool) or initial_censored is not extended:
        raise ValueError("single extension is allowed only after initial-window censoring")
    expected_reason = "right_censor_at_initial_horizon" if extended else "not_needed"
    if value.get("extension_reason") != expected_reason:
        raise ValueError("event-window extension reason mismatch")
    complete = value.get("complete")
    right_censored = value.get("right_censored")
    follow_complete = value.get("post_return_follow_complete")
    if not all(isinstance(flag, bool) for flag in (complete, right_censored, follow_complete)):
        raise ValueError("event-window completion and censor fields must be boolean")
    follow = _number(value.get("post_return_follow_s"), "post_return_follow_s", minimum=0.0)
    if follow != GRAVITY_FOLLOW_S:
        raise ValueError("post-return follow window differs from registered F4 gravity time")
    return {
        "normalization_T_s": T_S,
        "nominal_horizon_s": nominal,
        "actual_endpoint_s": actual,
        "native_output_interval_s": interval,
        "extension_count": extension_count,
        "initial_window_censored": initial_censored,
        "extension_reason": expected_reason,
        "complete": complete,
        "right_censored": right_censored,
        "post_return_follow_s": follow,
        "post_return_follow_complete": follow_complete,
    }


def _compare(candidate, reference, window):
    source_ids = sorted(candidate["source_rows"])
    if source_ids != sorted(reference["source_rows"]):
        raise ValueError("candidate/reference material source sets differ")
    for source_id in source_ids:
        left = candidate["source_rows"][source_id]
        right = reference["source_rows"][source_id]
        if left["initial_mass_kg"] != right["initial_mass_kg"]:
            raise ValueError("candidate/reference initial source mass differs: " + source_id)
        if set(left["tracer_records"]) != set(right["tracer_records"]):
            raise ValueError("candidate/reference initial tracer identity sets differ: " + source_id)
        for tracer_id in left["tracer_records"]:
            if left["tracer_records"][tracer_id]["weight_kg"] != right["tracer_records"][tracer_id]["weight_kg"]:
                raise ValueError("candidate/reference initial tracer weights differ: " + source_id)

    cdf_gaps = {}
    residence_gaps = {}
    event_mae = {}
    detection_error = {}
    any_common_event = False
    every_event_group_paired = True
    maximum_cdf_gap = 0.0
    maximum_residence_gap = 0.0
    maximum_event_mae = 0.0
    maximum_detection_error = 0.0

    for source_id in source_ids:
        left = candidate["source_rows"][source_id]
        right = reference["source_rows"][source_id]
        cdf_gaps[source_id] = {}
        for event_name in _CDF_NAMES:
            gap = _cdf_gap(left["cdf_bounds"][event_name], right["cdf_bounds"][event_name], window["actual_endpoint_s"])
            cdf_gaps[source_id][event_name] = gap
            maximum_cdf_gap = max(maximum_cdf_gap, gap)

        left_bounds = left["residence_mean_s_bounds"]
        right_bounds = right["residence_mean_s_bounds"]
        residence_gap = max(
            abs(left_bounds["lower"] - right_bounds["upper"]),
            abs(left_bounds["upper"] - right_bounds["lower"]),
        )
        residence_gaps[source_id] = residence_gap
        maximum_residence_gap = max(maximum_residence_gap, residence_gap)

        event_mae[source_id] = {}
        detection_error[source_id] = {}
        for event_name in _EVENTS:
            left_samples = left["event_samples"][event_name]
            right_samples = right["event_samples"][event_name]
            left_ids = set(left_samples)
            right_ids = set(right_samples)
            common = sorted(left_ids & right_ids)
            for tracer_id in common:
                if left_samples[tracer_id]["weight_kg"] != right_samples[tracer_id]["weight_kg"]:
                    raise ValueError("paired event tracer mass differs")
            common_mass = sum(left_samples[tracer_id]["weight_kg"] for tracer_id in common)
            if not common or left_ids != right_ids:
                every_event_group_paired = False
                event_mae[source_id][event_name] = {
                    "status": "not_applicable" if not common else "incomplete_pairing",
                    "value_s": None,
                    "common_event_mass_kg": common_mass,
                    "common_event_mass_fraction": common_mass / left["initial_mass_kg"],
                    "candidate_unpaired_mass_kg": sum(
                        left_samples[key]["weight_kg"] for key in left_ids - right_ids
                    ),
                    "reference_unpaired_mass_kg": sum(
                        right_samples[key]["weight_kg"] for key in right_ids - left_ids
                    ),
                }
                detection_error[source_id][event_name] = {
                    "status": "not_applicable" if not common else "incomplete_pairing",
                    "maximum_pairwise_sum_s": None,
                }
                continue
            any_common_event = True
            weighted_error = sum(
                left_samples[tracer_id]["weight_kg"]
                * abs(left_samples[tracer_id]["time_s"] - right_samples[tracer_id]["time_s"])
                for tracer_id in common
            ) / common_mass
            maximum_pairwise = max(
                left_samples[tracer_id]["detection_error_bound_s"]
                + right_samples[tracer_id]["detection_error_bound_s"]
                for tracer_id in common
            )
            event_mae[source_id][event_name] = {
                "status": "computed",
                "value_s": weighted_error,
                "common_event_mass_kg": common_mass,
                "common_event_mass_fraction": common_mass / left["initial_mass_kg"],
            }
            detection_error[source_id][event_name] = {
                "status": "computed", "maximum_pairwise_sum_s": maximum_pairwise,
            }
            maximum_event_mae = max(maximum_event_mae, weighted_error)
            maximum_detection_error = max(maximum_detection_error, maximum_pairwise)

    return {
        "cdf_gap_by_source_event": cdf_gaps,
        "maximum_cdf_interval_gap": maximum_cdf_gap,
        "residence_mean_gap_by_source": residence_gaps,
        "maximum_residence_mean_interval_gap_s": maximum_residence_gap,
        "event_mae_by_source_event": event_mae,
        "maximum_event_mae_s": maximum_event_mae if every_event_group_paired else None,
        "any_common_observed_event": any_common_event,
        "every_source_event_group_paired": every_event_group_paired,
        "event_detection_error_by_source_event": detection_error,
        "maximum_pairwise_detection_error_sum_s": maximum_detection_error if every_event_group_paired else None,
    }


def _evaluate(payload, expected_source_sha256, expected_artifact_sha256):
    if payload.get("schema") != PAIR_SCHEMA:
        raise ValueError("unsupported F4 tallwall120 pair diagnostic schema")
    if payload.get("policy_id") != POLICY_ID:
        raise ValueError("unsupported F4 tallwall120 diagnostic policy")
    if payload.get("diagnostic_only") is not True or payload.get("qualification_claim") != "none":
        raise ValueError("paired diagnostic must remain diagnostic-only with no qualification claim")
    if payload.get("credit") != 0 or payload.get("T2_macro") is not False or payload.get("T2_path") is not False:
        raise ValueError("paired diagnostic must carry zero credit and false T2 claims")
    identity = _identity(payload.get("identity"), "identity")
    expected_source_sha256 = _sha(expected_source_sha256, "externally_bound_source_sha256")
    expected_artifact_sha256 = _object(expected_artifact_sha256, "externally_bound_artifact_sha256")
    for side in ("candidate", "reference"):
        side_hashes = _object(expected_artifact_sha256.get(side), "externally_bound_artifact_sha256." + side)
        if set(side_hashes) != {"generation", "checkpoint", "trace_output", "output_manifest", "summary"}:
            raise ValueError("external artifact bindings must name generation, checkpoint, trace_output, output_manifest, and summary")
        for kind, digest in side_hashes.items():
            _sha(digest, "externally_bound_artifact_sha256." + side + "." + kind)
    window = _event_window(payload.get("event_window"))
    candidate = _snapshot(
        payload.get("candidate"), "candidate", identity, expected_source_sha256,
        expected_artifact_sha256["candidate"], window,
    )
    reference = _snapshot(
        payload.get("reference"), "reference", identity, expected_source_sha256,
        expected_artifact_sha256["reference"], window,
    )

    coverage_ok = True
    for snapshot in (candidate, reference):
        coverage = snapshot["output_coverage"]
        coverage_ok = coverage_ok and coverage["complete"]
        coverage_ok = coverage_ok and coverage["frame_count"] == coverage["expected_frame_count"]
        coverage_ok = coverage_ok and coverage["seed_count"] == coverage["expected_seed_count"]
        coverage_ok = coverage_ok and coverage["time_start_s"] == 0.0
        coverage_ok = coverage_ok and coverage["time_end_s"] == window["actual_endpoint_s"]
        coverage_ok = coverage_ok and coverage["native_output_interval_s"] == window["native_output_interval_s"]
    coverage_ok = coverage_ok and candidate["output_coverage"] == reference["output_coverage"]

    unknown_pass = True
    maximum_unknown = 0.0
    for snapshot in (candidate, reference):
        for row in snapshot["source_rows"].values():
            maximum_unknown = max(maximum_unknown, row["unknown_fraction_max"])
            unknown_pass = unknown_pass and row["unknown_fraction_max"] <= UNKNOWN_FRACTION_LIMIT

    comparisons = _compare(candidate, reference, window)
    complete_window = window["complete"] and window["post_return_follow_complete"] and coverage_ok
    right_censor_free = not window["right_censored"] and complete_window
    event_mae_pass = (
        comparisons["every_source_event_group_paired"]
        and comparisons["maximum_event_mae_s"] <= EVENT_MAE_LIMIT_S
    )
    detection_pass = (
        comparisons["every_source_event_group_paired"]
        and comparisons["maximum_pairwise_detection_error_sum_s"] <= DETECTION_ERROR_BUDGET_S
    )
    gates = {
        "identity": True,
        "source_hash_binding": True,
        "artifact_hash_bindings": True,
        "output_coverage": coverage_ok,
        "source_denominator": True,
        "unknown_bound": unknown_pass,
        "event_window": complete_window,
        "right_censor_free": right_censor_free,
        "cdf_gap": comparisons["maximum_cdf_interval_gap"] <= CDF_GAP_LIMIT,
        "residence_mean_gap": comparisons["maximum_residence_mean_interval_gap_s"] <= RESIDENCE_MEAN_GAP_LIMIT_S,
        "event_time_mae": event_mae_pass,
        "event_detection_error": detection_pass,
        "endpoint_tolerance": max(candidate["endpoint_max_error_m"], reference["endpoint_max_error_m"]) <= ENDPOINT_TOLERANCE_M,
        "saved_chord_tolerance": max(candidate["saved_chord_crossings"], reference["saved_chord_crossings"]) <= SAVED_CHORD_CROSSINGS_ALLOWED,
    }
    return {
        "identity": identity,
        "policy": {
            "policy_id": POLICY_ID,
            "status": "proposed_not_registered",
            "normalization_T_s": T_S,
            "event_window_max_s": MAX_EVENT_WINDOW_S,
            "unknown_fraction_limit": UNKNOWN_FRACTION_LIMIT,
            "cdf_interval_gap_limit": CDF_GAP_LIMIT,
            "residence_mean_interval_gap_limit_s": RESIDENCE_MEAN_GAP_LIMIT_S,
            "event_mae_limit_s": EVENT_MAE_LIMIT_S,
            "pairwise_detection_error_budget_s": DETECTION_ERROR_BUDGET_S,
            "endpoint_tolerance_m": ENDPOINT_TOLERANCE_M,
            "saved_chord_crossings_allowed": SAVED_CHORD_CROSSINGS_ALLOWED,
            "qualification_authority": False,
        },
        "event_window": window,
        "source_hash_sha256": expected_source_sha256,
        "candidate_artifacts": candidate["artifact_hashes"],
        "reference_artifacts": reference["artifact_hashes"],
        "maximum_source_unknown_fraction": maximum_unknown,
        "comparisons": comparisons,
        "gates": gates,
        "passed": all(gates.values()),
        "diagnostic_only": True,
        "qualification_claim": "none",
        "qualification_authority": False,
        "credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "execution_constraints": {
            "json_only": True,
            "hdf5_opened": False,
            "source_file_verified_here": False,
            "artifact_files_verified_here": False,
            "external_binding_authenticity_verified_here": False,
            "external_artifact_bindings_required": True,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_touched": False,
            "registry_written": False,
            "ledger_written": False,
            "receipt_written": False,
            "qualification_credit_registered": 0,
        },
    }


def evaluate_f4_tallwall120_pair(
    payload,
    *,
    externally_bound_source_sha256=None,
    externally_bound_artifact_sha256=None,
):
    """Evaluate a synthetic/serialized F4 pair under the draft diagnostic policy.

    The source digest and per-side generation, checkpoint, trace-output,
    canonical output-manifest, and summary digests are expected from an
    upstream verifier.  This JSON-only function checks the supplied bindings
    and manifest body but cannot authenticate the verifier or native artifacts.
    Structural failures return a blocked result; numerical failures remain
    explicit false gates.
    """
    result = {
        "schema": RESULT_SCHEMA,
        "status": "diagnostic_only",
        "diagnostic_only": True,
        "passed": False,
        "policy_status": "proposed_not_registered",
        "qualification_claim": "none",
        "qualification_authority": False,
        "credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "failure_reasons": [],
        "blocking_reasons": [],
        "gates": {name: False for name in _GATES},
    }
    try:
        _json_like(payload)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        checked = _evaluate(
            payload, externally_bound_source_sha256, externally_bound_artifact_sha256
        )
    except (TypeError, ValueError) as error:
        result["failure_reasons"] = ["structural_validation"]
        result["blocking_reasons"] = [str(error)]
        return result
    result.update(checked)
    result["schema"] = RESULT_SCHEMA
    result["status"] = "diagnostic_only"
    result["policy_status"] = "proposed_not_registered"
    result["failure_reasons"] = [name for name, passed in checked["gates"].items() if not passed]
    result["blocking_reasons"] = list(result["failure_reasons"])
    return result
