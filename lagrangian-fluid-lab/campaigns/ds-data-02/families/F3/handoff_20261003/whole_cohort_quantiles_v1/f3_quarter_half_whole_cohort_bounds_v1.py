#!/usr/bin/env python3
"""Compare the terminal F3 HALF/QUARTER labels with censor-safe quantiles.

This is a F3-specific diagnostic producer.  It reads the two small, immutable
typed-label HDF5 artifacts and the already produced HALF/QUARTER comparison,
then writes an additive error table for the registered transport observables.
The q-levels are declared in the contract before the run.  A censored identity
is retained in the initial cohort: assigning it to the window end gives the
earliest possible event time and assigning it to ``+inf`` gives the latest
possible event time.  The resulting interval is a conservative whole-cohort
bound; it is not a Q-N gate.

The producer never starts a solver, converter, or label materializer, and it
does not edit either consumed HDF5 or comparison JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


SCHEMA = "ds02.f3.quarter-half-whole-cohort-bounds.v1"
CANONICAL_INITIAL_MASS_KG = 14.58
EVENT_TIME_FRACTION = 0.02
INTEGRATION_SHARE = 0.20
EXPECTED_EVENT_IDS = ["left_right_exchange", "front_back_exchange", "top_open_exit"]
REGISTERED_OBSERVABLES = [
    "finite_x0_left_right_exchange",
    "finite_y0_front_back_exchange",
    "finite_top_exit",
    "unknown_mass",
    "region_mass",
    "centre_of_mass",
    "height_quantiles",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def require_binding(path_value: str | Path, expected_sha: str, label: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    actual = sha256(path)
    if actual != expected_sha:
        raise ValueError(f"{label} digest changed: expected {expected_sha}, got {actual}")
    return path


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if np.isfinite(value) else None


def weighted_quantile(values: np.ndarray, weights: np.ndarray, fraction: float) -> float:
    """Return the left-continuous weighted empirical quantile."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if not 0.0 < fraction < 1.0:
        raise ValueError("quantile fractions must lie strictly between zero and one")
    valid = np.isfinite(weights) & (weights > 0) & (~np.isnan(values))
    if not np.any(valid):
        raise ValueError("weighted quantile has no positive finite mass")
    values, weights = values[valid], weights[valid]
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    rank = fraction * float(cumulative[-1])
    index = int(np.searchsorted(cumulative, rank, side="left"))
    return float(values[order[min(index, len(order) - 1)]])


def conservative_quantile_bounds(
    intervals: np.ndarray,
    chord_times: np.ndarray,
    censor: np.ndarray,
    unresolved: np.ndarray,
    weights: np.ndarray,
    window_end_s: float,
    fractions: list[float],
) -> dict[str, Any]:
    """Compute conditional values and whole-cohort censor bounds.

    For an observed, resolved event the lower/upper saved-frame bracket is
    retained.  A right-censored event is no earlier than the final saved
    frame, so ``window_end_s`` is its lower bound and ``+inf`` its upper
    bound.  An unresolved native interval has no finite lower/upper event-time
    support and is represented by ``[0,+inf]``.  The initial fluid mass remains
    the denominator for every quantile.
    """
    intervals = np.asarray(intervals, dtype=float)
    chord_times = np.asarray(chord_times, dtype=float)
    censor = np.asarray(censor, dtype=bool)
    unresolved = np.asarray(unresolved, dtype=bool)
    weights = np.asarray(weights, dtype=float)
    if intervals.shape != (len(weights), 2):
        raise ValueError("first-passage intervals do not match the identity axis")
    if chord_times.shape != (len(weights),) or censor.shape != (len(weights),):
        raise ValueError("first-passage arrays do not match the identity axis")
    observed = (~censor) & (~unresolved)
    if np.any((~censor) & (~np.isfinite(intervals).all(axis=1))):
        raise ValueError("an observed event has a non-finite interval")
    if np.any(observed & (intervals[:, 0] > intervals[:, 1])):
        raise ValueError("an observed event has an inverted interval")

    lower = np.where(unresolved, 0.0, np.where(observed, intervals[:, 0], window_end_s))
    upper = np.where(observed, intervals[:, 1], np.inf)
    selected = observed & np.isfinite(chord_times)
    conditional = {
        "observed_count": int(np.sum(selected)),
        "observed_mass_kg": float(np.sum(weights[selected])),
        "censored_or_unresolved_count": int(np.sum(~selected)),
        "censored_or_unresolved_mass_kg": float(np.sum(weights[~selected])),
        "quantiles": [],
        "semantics": "conditional on observed resolved first-passage identities; not a whole-cohort estimate",
    }
    bounds = []
    for fraction in fractions:
        conditional_row = {
            "fraction": float(fraction),
            "lower_bracket_s": _as_float(weighted_quantile(intervals[selected, 0], weights[selected], fraction)) if np.any(selected) else None,
            "chord_time_s": _as_float(weighted_quantile(chord_times[selected], weights[selected], fraction)) if np.any(selected) else None,
            "upper_bracket_s": _as_float(weighted_quantile(intervals[selected, 1], weights[selected], fraction)) if np.any(selected) else None,
        }
        conditional["quantiles"].append(conditional_row)
        lower_value = weighted_quantile(lower, weights, fraction)
        upper_value = weighted_quantile(upper, weights, fraction)
        bounds.append({
            "fraction": float(fraction),
            "lower_s": float(lower_value),
            "upper_s": _as_float(upper_value),
            "upper_is_unbounded": bool(not np.isfinite(upper_value)),
            "semantics": "whole initial fluid cohort; censored identities remain in denominator",
        })
    return {
        "conditional_observed": conditional,
        "whole_cohort_conservative_bounds": bounds,
        "unresolved_count": int(np.sum(unresolved)),
        "unresolved_mass_kg": float(np.sum(weights[unresolved])),
    }


def _difference(base: float | None, variant: float | None, *, units: str, canonical_mass: float) -> dict[str, Any]:
    if base is None or variant is None:
        return {
            "base": base,
            "variant": variant,
            "absolute_error": None,
            "relative_to_base": None,
            "native_mass_normalized_error": None,
            "normalization_note": "not available for this artifact/operator",
            "units": units,
        }
    delta = float(variant - base)
    mass_units = units in {"kg", "kg*s", "kg_fraction"}
    normalized_delta = delta if units == "kg_fraction" else (delta / canonical_mass if mass_units else None)
    return {
        "base": float(base),
        "variant": float(variant),
        "absolute_error": delta,
        "relative_to_base": None if base == 0 else float(delta / abs(base)),
        "native_mass_normalized_error": normalized_delta,
        "normalization_note": (
            "absolute mass delta divided by canonical continuum mass 14.58 kg"
            if units == "kg" else
            "kg*s delta divided by canonical 14.58 kg; result has seconds dimension"
            if units == "kg*s" else
            "fraction is native mass divided by canonical continuum mass"
            if units == "kg_fraction" else
            "mass normalization is dimensionally invalid for a time or count observable"
        ),
        "units": units,
    }


def _row(observable_id: str, base: float | None, variant: float | None, units: str, *, canonical_mass: float) -> dict[str, Any]:
    result = {"observable_id": observable_id}
    result.update(_difference(base, variant, units=units, canonical_mass=canonical_mass))
    return result


def _label_summary(path: Path, expected_sha: str, expected_source_sha: str, expected_mass: float, window_end_s: float, qlevels: list[float]) -> dict[str, Any]:
    path = require_binding(path, expected_sha, "label artifact")
    with h5py.File(path, "r") as h5:
        required = {
            "time", "particle_id", "particle_zone", "source_label", "initial_fluid_mass_kg",
            "first_passage_interval", "first_passage_chord_time", "first_passage_censor",
            "forward_backward_mass_kg", "cumulative_net_flux_kg", "residence_time_s",
            "unknown_mass_kg", "numerical_loss_mass_kg", "invalid_state_mass_kg",
            "final_category", "unresolved_interval_time_s",
        }
        missing = sorted(required - set(h5.keys()))
        if missing:
            raise ValueError(f"{path} lacks required typed-label fields: {missing}")
        if not bool(h5.attrs.get("complete", False)):
            raise ValueError(f"typed labels are incomplete: {path}")
        source_sha = str(h5.attrs.get("source_hdf5_sha256", ""))
        if source_sha != expected_source_sha:
            raise ValueError(f"{path} source HDF5 binding changed: expected {expected_source_sha}, got {source_sha}")
        time = np.asarray(h5["time"][:], dtype=float)
        if len(time) < 2 or not np.isfinite(time).all() or np.any(np.diff(time) <= 0):
            raise ValueError("label time axis is not finite and strictly increasing")
        if time[0] > 1e-10 or time[-1] < window_end_s:
            raise ValueError("label does not cover the registered event window")
        config = json.loads(h5.attrs["config_json"])
        event_ids = [str(event["id"]) for event in config.get("events", [])]
        if event_ids != EXPECTED_EVENT_IDS:
            raise ValueError(f"unexpected F3 event operator: {event_ids}")
        mass_all = np.asarray(h5["initial_fluid_mass_kg"][:], dtype=float)
        fluid = mass_all > 0
        if not np.any(fluid) or not np.isfinite(mass_all[fluid]).all() or np.any(mass_all[fluid] <= 0):
            raise ValueError("initial fluid mass axis is not finite and positive")
        mass = mass_all[fluid]
        initial_mass_native = float(mass.sum())
        if not np.isclose(initial_mass_native, float(h5.attrs["initial_fluid_mass_kg"]), rtol=1e-12, atol=1e-12):
            raise ValueError("initial fluid mass does not close against HDF5 header")
        if not np.isclose(initial_mass_native, expected_mass, rtol=1e-12, atol=1e-12):
            raise ValueError(f"unexpected native initial mass: {initial_mass_native}")

        unresolved = np.asarray(h5["unresolved_interval_time_s"][:], dtype=float)[fluid] > 0
        intervals_all = np.asarray(h5["first_passage_interval"][:], dtype=float)[fluid]
        chord_all = np.asarray(h5["first_passage_chord_time"][:], dtype=float)[fluid]
        censor_all = np.asarray(h5["first_passage_censor"][:], dtype=bool)[fluid]
        passages: list[dict[str, Any]] = []
        for index, event_id in enumerate(event_ids):
            interval = intervals_all[:, index, :]
            chord = chord_all[:, index]
            censor = censor_all[:, index]
            observed = (~censor) & (~unresolved) & np.isfinite(chord) & np.isfinite(interval).all(axis=1)
            observed_mass = float(mass[observed].sum())
            censored = ~observed
            rows = conservative_quantile_bounds(interval, chord, censor, unresolved, mass, float(time[-1]), qlevels)
            if observed_mass:
                lower_mean = float(np.sum(interval[observed, 0] * mass[observed]) / observed_mass)
                upper_mean = float(np.sum(interval[observed, 1] * mass[observed]) / observed_mass)
                chord_mean = float(np.sum(chord[observed] * mass[observed]) / observed_mass)
            else:
                lower_mean = upper_mean = chord_mean = None
            passages.append({
                "event_id": event_id,
                "observed_count": int(np.sum(observed)),
                "observed_mass_kg": observed_mass,
                "censored_or_unresolved_count": int(np.sum(censored)),
                "censored_or_unresolved_mass_kg": float(mass[censored].sum()),
                "observed_mass_fraction_of_canonical_initial_mass": observed_mass / CANONICAL_INITIAL_MASS_KG,
                "censored_mass_fraction_of_canonical_initial_mass": float(mass[censored].sum()) / CANONICAL_INITIAL_MASS_KG,
                "mass_weighted_lower_bracket_s": lower_mean,
                "mass_weighted_upper_bracket_s": upper_mean,
                "mass_weighted_chord_time_s": chord_mean,
                "quantiles": rows,
            })

        final_category = np.asarray(h5["final_category"][:], dtype=int)[fluid]
        region_mass = {str(code): float(mass[final_category == code].sum()) for code in (1, 2)}
        residence = np.asarray(h5["residence_time_s"][:], dtype=float)[fluid]
        residence_mean = np.sum(residence * mass[:, None], axis=0) / initial_mass_native
        residence_mass_time = np.sum(residence * mass[:, None], axis=0)
        net = np.asarray(h5["cumulative_net_flux_kg"][-1], dtype=float)
        forward_backward = np.asarray(h5["forward_backward_mass_kg"][-1], dtype=float)
        return {
            "path": str(path),
            "sha256": expected_sha,
            "frames": int(len(time)),
            "time_start_s": float(time[0]),
            "time_end_s": float(time[-1]),
            "save_interval_min_s": float(np.min(np.diff(time))),
            "save_interval_max_s": float(np.max(np.diff(time))),
            "identity_count": int(len(mass_all)),
            "fluid_identity_count": int(np.sum(fluid)),
            "initial_fluid_mass_kg": initial_mass_native,
            "event_ids": event_ids,
            "passage": passages,
            "region_mass_kg": region_mass,
            "final_forward_backward_mass_kg": forward_backward.tolist(),
            "final_cumulative_net_flux_kg": net.tolist(),
            "final_unknown_mass_kg": float(np.asarray(h5["unknown_mass_kg"][-1])),
            "final_numerical_loss_mass_kg": float(np.asarray(h5["numerical_loss_mass_kg"][-1])),
            "final_invalid_state_mass_kg": float(np.asarray(h5["invalid_state_mass_kg"][-1])),
            "max_unknown_mass_kg": float(np.max(np.asarray(h5["unknown_mass_kg"][:], dtype=float))),
            "max_numerical_loss_mass_kg": float(np.max(np.asarray(h5["numerical_loss_mass_kg"][:], dtype=float))),
            "max_invalid_state_mass_kg": float(np.max(np.asarray(h5["invalid_state_mass_kg"][:], dtype=float))),
            "residence_mean_s": residence_mean.tolist(),
            "residence_mass_time_kg_s": residence_mass_time.tolist(),
            "unresolved_count": int(np.sum(unresolved)),
            "unresolved_mass_kg": float(mass[unresolved].sum()),
            "q_n_status": str(h5.attrs.get("q_n_status", "not_assessed")),
        }


def _quantile_comparison(base: dict[str, Any], variant: dict[str, Any], qlevels: list[float], allocation_s: float) -> list[dict[str, Any]]:
    result = []
    for base_event, variant_event in zip(base["passage"], variant["passage"]):
        for bq, vq in zip(base_event["quantiles"]["whole_cohort_conservative_bounds"], variant_event["quantiles"]["whole_cohort_conservative_bounds"]):
            lower_separation = max(0.0, bq["lower_s"] - (vq["upper_s"] if vq["upper_s"] is not None else float("inf")), vq["lower_s"] - (bq["upper_s"] if bq["upper_s"] is not None else float("inf")))
            bounded = bq["upper_s"] is not None and vq["upper_s"] is not None
            maximum_separation = None if not bounded else max(
                abs(bq["lower_s"] - vq["upper_s"]),
                abs(bq["upper_s"] - vq["lower_s"]),
            )
            status = "unidentified_due_to_censoring"
            if bounded:
                status = "exceeds_allocation_for_all_interval_choices" if lower_separation > allocation_s else (
                    "within_allocation_for_all_interval_choices" if maximum_separation <= allocation_s else "unresolved_within_conservative_bounds"
                )
            result.append({
                "event_id": base_event["event_id"],
                "fraction": bq["fraction"],
                "baseline_bounds": bq,
                "variant_bounds": vq,
                "minimum_separation_s": None if not bounded else lower_separation,
                "maximum_separation_s": maximum_separation,
                "allocation_s": allocation_s,
                "status": status,
            })
    return result


def run(contract_path: Path, output_path: Path) -> dict[str, Any]:
    contract_path = Path(contract_path).expanduser().resolve()
    contract = read_json(contract_path, "F3 whole-cohort contract")
    if contract.get("schema") != "ds02.f3.quarter-half-whole-cohort-contract.v1":
        raise ValueError("unexpected whole-cohort contract schema")
    if contract.get("quantile_fractions") != [0.1, 0.5, 0.9]:
        raise ValueError("q-levels must be explicitly preregistered as [0.1, 0.5, 0.9]")
    qlevels = [float(q) for q in contract["quantile_fractions"]]
    expected_mass = float(contract["canonical_initial_mass_kg"])
    if expected_mass != CANONICAL_INITIAL_MASS_KG:
        raise ValueError("this F3 producer requires the frozen 14.58 kg canonical mass")
    window_end_s = float(contract["window_s"][1])
    if window_end_s <= 0:
        raise ValueError("invalid event window")

    registration_path = require_binding(contract["registration_path"], contract["registration_sha256"], "F3 weak reference registration")
    operators_path = require_binding(contract["operators_path"], contract["operators_sha256"], "F3 weak operators")
    transport_config_path = require_binding(contract["transport_config_path"], contract["transport_config_sha256"], "F3 transport config")
    registration = read_json(registration_path, "F3 weak reference registration")
    if registration.get("observables") != REGISTERED_OBSERVABLES:
        raise ValueError("registered observable list changed")
    operators = read_json(operators_path, "F3 weak operators")
    transport_config = read_json(transport_config_path, "F3 transport config")
    if float(registration["thresholds"]["event_time_fraction_of_feature_time"]) != EVENT_TIME_FRACTION:
        raise ValueError("event-time budget changed")
    if float(registration["thresholds"]["integration_error_fraction_of_total"]) != INTEGRATION_SHARE:
        raise ValueError("integration allocation changed")
    if float(registration["physical_condition"]["geometry"]["tank_size_m"][0]) != 0.9:
        raise ValueError("physical geometry binding changed")
    if operators.get("scope", "").find("no Q-N") < 0 or transport_config.get("semantics", {}).get("unknown") is None:
        raise ValueError("transport claim boundary or unknown policy missing")

    comparison_path = require_binding(contract["comparison_path"], contract["comparison_sha256"], "existing HALF/QUARTER comparison")
    comparison = read_json(comparison_path, "existing HALF/QUARTER comparison")
    if comparison.get("qualification_status") == "pass" or comparison.get("q_n_status") == "passed":
        raise ValueError("consumed comparison already declares an invalid qualification pass")

    base = _label_summary(Path(contract["half_labels"]), contract["half_labels_sha256"], contract["half_source_hdf5_sha256"], float(contract["expected_native_mass_kg"]), window_end_s, qlevels)
    variant = _label_summary(Path(contract["quarter_labels"]), contract["quarter_labels_sha256"], contract["quarter_source_hdf5_sha256"], float(contract["expected_native_mass_kg"]), window_end_s, qlevels)
    if base["event_ids"] != variant["event_ids"] or base["frames"] != variant["frames"]:
        raise ValueError("HALF and QUARTER label axes differ")

    error_rows: list[dict[str, Any]] = []
    error_rows.append(_row("initial_fluid_mass_kg", base["initial_fluid_mass_kg"], variant["initial_fluid_mass_kg"], "kg", canonical_mass=expected_mass))
    for index, (base_event, variant_event) in enumerate(zip(base["passage"], variant["passage"])):
        event = base_event["event_id"]
        error_rows.extend([
            _row(f"{event}.observed_first_passage_count", base_event["observed_count"], variant_event["observed_count"], "count", canonical_mass=expected_mass),
            _row(f"{event}.observed_mass_kg", base_event["observed_mass_kg"], variant_event["observed_mass_kg"], "kg", canonical_mass=expected_mass),
            _row(f"{event}.censored_or_unresolved_mass_kg", base_event["censored_or_unresolved_mass_kg"], variant_event["censored_or_unresolved_mass_kg"], "kg", canonical_mass=expected_mass),
            _row(f"{event}.observed_mass_fraction_of_14.58kg", base_event["observed_mass_fraction_of_canonical_initial_mass"], variant_event["observed_mass_fraction_of_canonical_initial_mass"], "kg_fraction", canonical_mass=expected_mass),
            _row(f"{event}.censored_mass_fraction_of_14.58kg", base_event["censored_mass_fraction_of_canonical_initial_mass"], variant_event["censored_mass_fraction_of_canonical_initial_mass"], "kg_fraction", canonical_mass=expected_mass),
            _row(f"{event}.mass_weighted_lower_bracket_s", base_event["mass_weighted_lower_bracket_s"], variant_event["mass_weighted_lower_bracket_s"], "s", canonical_mass=expected_mass),
            _row(f"{event}.mass_weighted_upper_bracket_s", base_event["mass_weighted_upper_bracket_s"], variant_event["mass_weighted_upper_bracket_s"], "s", canonical_mass=expected_mass),
            _row(f"{event}.mass_weighted_chord_time_s", base_event["mass_weighted_chord_time_s"], variant_event["mass_weighted_chord_time_s"], "s", canonical_mass=expected_mass),
        ])
        for direction, direction_index in (("forward", 0), ("backward", 1)):
            error_rows.append(_row(f"{event}.{direction}_mass_kg", float(base["final_forward_backward_mass_kg"][index][direction_index]), float(variant["final_forward_backward_mass_kg"][index][direction_index]), "kg", canonical_mass=expected_mass))
        error_rows.append(_row(f"{event}.net_flux_kg", float(base["final_cumulative_net_flux_kg"][index]), float(variant["final_cumulative_net_flux_kg"][index]), "kg", canonical_mass=expected_mass))

    for code, label in (("1", "left"), ("2", "right")):
        error_rows.append(_row(f"region_mass.{label}_kg", base["region_mass_kg"][code], variant["region_mass_kg"][code], "kg", canonical_mass=expected_mass))
    for field, unit in (("final_unknown_mass_kg", "kg"), ("final_numerical_loss_mass_kg", "kg"), ("final_invalid_state_mass_kg", "kg")):
        error_rows.append(_row(field, base[field], variant[field], unit, canonical_mass=expected_mass))
    for index in range(len(base["residence_mean_s"])):
        error_rows.extend([
            _row(f"residence.region_{index + 1}.mass_weighted_mean_s", base["residence_mean_s"][index], variant["residence_mean_s"][index], "s", canonical_mass=expected_mass),
            _row(f"residence.region_{index + 1}.mass_time_kg_s", base["residence_mass_time_kg_s"][index], variant["residence_mass_time_kg_s"][index], "kg*s", canonical_mass=expected_mass),
        ])

    allocation_rows = []
    for base_event, variant_event in zip(base["passage"], variant["passage"]):
        event = base_event["event_id"]
        feature_time = base_event["mass_weighted_chord_time_s"]
        if feature_time is None:
            allocation_rows.append({"event_id": event, "status": "no_observed_feature_time", "allocation_s": None})
            continue
        allocation = EVENT_TIME_FRACTION * feature_time * INTEGRATION_SHARE
        deltas = [
            abs(float(variant_event[key]) - float(base_event[key]))
            for key in ("mass_weighted_lower_bracket_s", "mass_weighted_upper_bracket_s", "mass_weighted_chord_time_s")
            if base_event[key] is not None and variant_event[key] is not None
        ]
        maximum = max(deltas) if deltas else None
        allocation_rows.append({
            "event_id": event,
            "baseline_feature_time_s": feature_time,
            "event_time_budget_s": EVENT_TIME_FRACTION * feature_time,
            "integration_allocation_s": allocation,
            "max_observed_bracket_or_chord_delta_s": maximum,
            "allocation_ratio": None if maximum is None else maximum / allocation,
            "status": "exceeds_allocation" if maximum is not None and maximum > allocation else "within_allocation",
            "semantics": "20% of the frozen 2% event-time budget; applied only to observed bracket/chord diagnostic",
        })

    q_comparisons = []
    for b_event, v_event in zip(base["passage"], variant["passage"]):
        feature = b_event["mass_weighted_chord_time_s"]
        allocation = None if feature is None else EVENT_TIME_FRACTION * INTEGRATION_SHARE * feature
        for bq, vq in zip(b_event["quantiles"]["whole_cohort_conservative_bounds"], v_event["quantiles"]["whole_cohort_conservative_bounds"]):
            bounded = bq["upper_s"] is not None and vq["upper_s"] is not None
            minimum = None
            maximum = None
            if bounded:
                minimum = max(0.0, bq["lower_s"] - vq["upper_s"], vq["lower_s"] - bq["upper_s"])
                maximum = max(abs(bq["lower_s"] - vq["upper_s"]), abs(bq["upper_s"] - vq["lower_s"]))
            status = "unidentified_due_to_censoring"
            if bounded and allocation is not None:
                status = "exceeds_allocation_for_all_interval_choices" if minimum > allocation else (
                    "within_allocation_for_all_interval_choices" if maximum <= allocation else "unresolved_within_conservative_bounds"
                )
            conditional_delta = None
            if bq["fraction"] in [row["fraction"] for row in b_event["quantiles"]["conditional_observed"]["quantiles"]]:
                b_cond = next(row for row in b_event["quantiles"]["conditional_observed"]["quantiles"] if row["fraction"] == bq["fraction"])
                v_cond = next(row for row in v_event["quantiles"]["conditional_observed"]["quantiles"] if row["fraction"] == vq["fraction"])
                if b_cond["chord_time_s"] is not None and v_cond["chord_time_s"] is not None:
                    conditional_delta = float(v_cond["chord_time_s"] - b_cond["chord_time_s"])
            q_comparisons.append({
                "event_id": b_event["event_id"],
                "fraction": bq["fraction"],
                "conditional_observed_chord_delta_s": conditional_delta,
                "baseline_bounds": bq,
                "variant_bounds": vq,
                "minimum_separation_s": minimum,
                "maximum_separation_s": maximum,
                "allocation_s": allocation,
                "status": status,
            })

    coverage = [
        {"observable_id": "finite_x0_left_right_exchange", "status": "measured", "source": "typed labels: event bracket, first-passage mass, forward/backward/net flux; whole-cohort q bounds diagnostic"},
        {"observable_id": "finite_y0_front_back_exchange", "status": "measured", "source": "typed labels: event bracket, first-passage mass, forward/backward/net flux; whole-cohort q bounds diagnostic"},
        {"observable_id": "finite_top_exit", "status": "censored_only", "source": "typed labels contain zero observed crossings and full 14.58 kg remains censored; no exit inferred"},
        {"observable_id": "unknown_mass", "status": "measured_native_ledger", "source": "unknown/numerical-loss/invalid mass time series; zero at terminal label frame does not prove physical fate"},
        {"observable_id": "region_mass", "status": "measured", "source": "typed-label final categories 1/2, native kg and 14.58 kg denominator"},
        {"observable_id": "centre_of_mass", "status": "unavailable_in_current_label_operator", "source": "typed transport labels do not contain position/velocity arrays; no COM comparison made"},
        {"observable_id": "height_quantiles", "status": "unavailable_in_current_label_operator", "source": "typed transport labels do not contain position arrays; no height quantile comparison made"},
    ]

    report = {
        "schema": SCHEMA,
        "contract": {"path": str(contract_path), "sha256": sha256(contract_path)},
        "physical_scale": {
            "canonical_initial_mass_kg": expected_mass,
            "native_half_initial_mass_kg": base["initial_fluid_mass_kg"],
            "native_quarter_initial_mass_kg": variant["initial_fluid_mass_kg"],
            "mass_normalization_policy": "mass rows use canonical continuum 14.58 kg; time/count rows are not mass-normalized",
            "window_s": contract["window_s"],
        },
        "source_bindings": {
            "half_labels": {"path": base["path"], "sha256": base["sha256"]},
            "quarter_labels": {"path": variant["path"], "sha256": variant["sha256"]},
            "comparison": {"path": str(comparison_path), "sha256": contract["comparison_sha256"]},
            "registration": {"path": str(registration_path), "sha256": sha256(registration_path)},
            "operators": {"path": str(operators_path), "sha256": sha256(operators_path)},
            "transport_config": {"path": str(transport_config_path), "sha256": sha256(transport_config_path)},
        },
        "registered_observable_coverage": coverage,
        "baseline": base,
        "variant": variant,
        "registered_observable_error_table": error_rows,
        "observed_event_integration_allocation": allocation_rows,
        "whole_cohort_quantile_diagnostic": {
            "qlevels_preregistered": qlevels,
            "qlevel_semantics": "new F3 diagnostic registration; mass-weighted whole initial fluid cohort; censored/right-unknown retained",
            "operator_gap": "the consumed HALF/QUARTER compare reports conditional observed means/brackets, not whole-cohort first-passage quantiles",
            "comparisons": q_comparisons,
            "q_n_status": "not_assessed",
        },
        "scope_support": {
            "half_supports_structural_transport_label_scope": True,
            "half_supports_temporal_integration_scope": False,
            "reason": "two observed exchange events exceed the frozen 20% share of their 2% event-time budget; whole-cohort q bounds are mostly unresolved by censoring; top exit is fully censored",
            "independent_reference_required": True,
            "required_next_reference": "independent finer integration and/or save study with the registered event operators and the preregistered q-level diagnostic; current HALF is evidence only",
            "qualification_claim": "none",
            "q_n_status": "not_assessed",
            "production_approval": "none",
        },
        "claim_boundary": "Actual HALF/QUARTER labels and conservative quantile bounds are diagnostic evidence only; unknown/censored identities remain unknown; no Q-I/Q-N or production approval is granted.",
    }
    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite report: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.contract, args.output)
    print(json.dumps({
        "output": str(Path(args.output).resolve()),
        "registered_rows": len(report["registered_observable_error_table"]),
        "quantile_rows": len(report["whole_cohort_quantile_diagnostic"]["comparisons"]),
        "half_supports_temporal_integration_scope": report["scope_support"]["half_supports_temporal_integration_scope"],
        "q_n_status": "not_assessed",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
