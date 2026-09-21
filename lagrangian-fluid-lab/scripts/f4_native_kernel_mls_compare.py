"""Compare two completed causal native MLS material traces.

This is a read-only postprocess companion for the full 0.3 s s2/s4 jobs.  It
requires both traces to bind the same source H5, 512 independent seeds,
current-frame-only density/velocity access, and the same event definition.  It
compares endpoint mass fractions, framewise permanent-unknown mass, event CDF
bounds, all-source residence bounds, and the common reliable path.

The result is diagnostic only.  Numerical support success is kept separate
from material reliability, and no T2 status is inferred from a comparison.
Residence is reported as cumulative destination-box time within the observed
window.  A seed that loses support has a lower bound from the observed
segments and a conservative upper bound through the end of that window;
eventual residence beyond the window remains right-censored.
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


SCHEMA = "core.material.f4.native_kernel_mls.comparison.v2"
TRACE_SCHEMA = "core.material.f4.native_kernel_mls.trace.v1"
QUANTILES = np.linspace(0.05, 0.95, 19, dtype=np.float64)


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


def _weighted_cdf(event_time: np.ndarray, weight: np.ndarray, mask: np.ndarray, denominator: float) -> dict:
    mask = np.asarray(mask, dtype=bool) & np.isfinite(event_time)
    if denominator <= 0.0 or not np.any(mask):
        return {"time_s": [], "mass_fraction": [], "event_mass_fraction": 0.0}
    order = np.argsort(event_time[mask], kind="mergesort")
    times = event_time[mask][order]
    fractions = np.cumsum(weight[mask][order]) / denominator
    return {
        "time_s": times.tolist(),
        "mass_fraction": fractions.tolist(),
        "event_mass_fraction": float(fractions[-1]),
    }


def _weighted_event_quantiles(event_time: np.ndarray, weight: np.ndarray, mask: np.ndarray, denominator: float) -> dict:
    mask = np.asarray(mask, dtype=bool) & np.isfinite(event_time)
    if denominator <= 0.0 or not np.any(mask):
        return {str(float(q)): None for q in QUANTILES}
    values = event_time[mask]
    values_weight = weight[mask]
    order = np.argsort(values, kind="mergesort")
    values = values[order]
    cumulative = np.cumsum(values_weight[order]) / denominator
    result = {}
    for quantile in QUANTILES:
        index = np.flatnonzero(cumulative >= quantile)
        result[str(float(quantile))] = float(values[index[0]]) if len(index) else None
    return result


def _unknown_window(trace: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return final unknown, first unknown index, and earliest possible time.

    The trace only records frame-level permanence.  If a support stage fails
    while advancing an interval, the event can first have happened after the
    preceding committed frame.  Using that frame time is conservative and
    does not invent an event time.
    """
    history = np.asarray(trace["unknown_history"], dtype=bool)
    times = np.asarray(trace["time"], dtype=np.float64)
    count = history.shape[1]
    first_index = np.full(count, -1, dtype=np.int64)
    for index in range(count):
        candidates = np.flatnonzero(history[:, index])
        if len(candidates):
            first_index[index] = int(candidates[0])
    possible_from = np.full(count, np.nan, dtype=np.float64)
    for index, first in enumerate(first_index):
        if first >= 0:
            possible_from[index] = times[max(0, first - 1)]
    return history[-1], first_index, possible_from


def _event_cdf_bounds(
    event_time: np.ndarray,
    weight: np.ndarray,
    select: np.ndarray,
    final_unknown: np.ndarray,
    unknown_possible_from: np.ndarray,
    observation_end: float,
    denominator: float,
) -> dict:
    """Report an event-time CDF with lower/upper mass bounds.

    Finite event times are observed values, including values observed before a
    later support failure.  An unknown seed without an observed event may have
    an event after its last committed reliable frame, so its mass enters the
    upper CDF from that time onward.  A fully reliable no-event seed is simply
    right-censored at the observation end and does not enter the upper bound
    inside this window.
    """
    event_time = np.asarray(event_time, dtype=np.float64)
    weight = np.asarray(weight, dtype=np.float64)
    select = np.asarray(select, dtype=bool)
    final_unknown = np.asarray(final_unknown, dtype=bool)
    finite = select & np.isfinite(event_time)
    possible = select & final_unknown & ~finite & np.isfinite(unknown_possible_from)
    source_mass = float(denominator)
    if source_mass <= 0.0:
        return {
            "time_s": [],
            "lower_mass_fraction": [],
            "upper_mass_fraction": [],
            "event_mass_fraction": 0.0,
            "upper_event_mass_fraction": 0.0,
            "unknown_unresolved_mass_fraction": 0.0,
            "reliable_no_event_right_censored_mass_fraction": 0.0,
        }
    candidate = [0.0, float(observation_end)]
    candidate.extend(event_time[finite].tolist())
    candidate.extend(unknown_possible_from[possible].tolist())
    times = np.unique(np.asarray(candidate, dtype=np.float64))
    times.sort()
    lower = np.asarray([
        float(np.sum(weight[finite & (event_time <= time)]) / source_mass)
        for time in times
    ])
    upper = lower + np.asarray([
        float(np.sum(weight[possible & (unknown_possible_from <= time)]) / source_mass)
        for time in times
    ])
    observed_mass = float(np.sum(weight[finite]) / source_mass)
    unresolved_mass = float(np.sum(weight[possible]) / source_mass)
    reliable_no_event = select & ~final_unknown & ~finite
    return {
        "time_s": times.tolist(),
        "lower_mass_fraction": lower.tolist(),
        "upper_mass_fraction": upper.tolist(),
        "mass_fraction": lower.tolist(),
        "event_mass_fraction": observed_mass,
        "upper_event_mass_fraction": observed_mass + unresolved_mass,
        "unknown_unresolved_mass_fraction": unresolved_mass,
        "reliable_no_event_right_censored_mass_fraction": float(
            np.sum(weight[reliable_no_event]) / source_mass
        ),
    }


def _interval_cdf(
    lower_value: np.ndarray,
    upper_value: np.ndarray,
    weight: np.ndarray,
    select: np.ndarray,
    denominator: float,
) -> dict:
    """CDF bounds for per-seed intervals using the complete source mass.

    At threshold x, a seed is definitely in the CDF when upper <= x and may
    be in it when lower <= x.  This includes exact zero intervals from seeds
    that never contact the destination box.
    """
    lower_value = np.asarray(lower_value, dtype=np.float64)
    upper_value = np.asarray(upper_value, dtype=np.float64)
    weight = np.asarray(weight, dtype=np.float64)
    select = np.asarray(select, dtype=bool)
    finite = select & np.isfinite(lower_value) & np.isfinite(upper_value)
    source_mass = float(denominator)
    if source_mass <= 0.0 or not np.any(finite):
        return {
            "value_s": [],
            "lower_mass_fraction": [],
            "upper_mass_fraction": [],
            "mass_fraction": [],
            "zero_mass_fraction_lower": 0.0,
            "zero_mass_fraction_upper": 0.0,
        }
    lower_value = np.maximum(lower_value, 0.0)
    upper_value = np.maximum(upper_value, lower_value)
    candidate = np.concatenate((np.array([0.0]), lower_value[finite], upper_value[finite]))
    values = np.unique(candidate)
    values.sort()
    lower_cdf = np.asarray([
        float(np.sum(weight[finite & (upper_value <= value)]) / source_mass)
        for value in values
    ])
    upper_cdf = np.asarray([
        float(np.sum(weight[finite & (lower_value <= value)]) / source_mass)
        for value in values
    ])
    return {
        "value_s": values.tolist(),
        "lower_mass_fraction": lower_cdf.tolist(),
        "upper_mass_fraction": upper_cdf.tolist(),
        "mass_fraction": lower_cdf.tolist(),
        "zero_mass_fraction_lower": float(
            np.sum(weight[finite & (upper_value == 0.0)]) / source_mass
        ),
        "zero_mass_fraction_upper": float(
            np.sum(weight[finite & (lower_value == 0.0)]) / source_mass
        ),
    }


def _percentile(values: np.ndarray, percentile: float):
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    return None if len(values) == 0 else float(np.percentile(values, percentile))


def _load_trace(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    with h5py.File(path, "r") as handle:
        if handle.attrs.get("schema") != TRACE_SCHEMA:
            raise ValueError(f"{path} is not a native MLS trace")
        committed = int(handle.attrs.get("committed", -1))
        if committed < 0:
            raise ValueError(f"{path} has no committed frame")
        required = (
            "time", "position", "query_mass", "source_label", "reliable",
            "permanent_unknown", "destination_member", "contact_time",
            "upward_time", "return_time", "residence_s", "contacted",
            "upward", "returned", "event_status", "mass_closure_error",
            "residual_estimate_mps", "path_error_budget_m",
        )
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"{path} is missing trace datasets: {missing}")
        result = {
            "path": str(path),
            "sha256": sha256_file(path),
            "binding": _attr_json(handle, "binding"),
            "binding_sha256": str(handle.attrs.get("binding_sha256", "")),
            "seed_hash": str(handle.attrs.get("seed_hash", "")),
            "committed": committed,
            "time": np.asarray(handle["time"][:committed + 1], dtype=np.float64),
            "position": np.asarray(handle["position"][committed], dtype=np.float64),
            "query_mass": np.asarray(handle["query_mass"][:], dtype=np.float64),
            "source_label": np.asarray(handle["source_label"].asstr()[:]),
            "reliable_history": np.asarray(handle["reliable"][:committed + 1], dtype=bool),
            "unknown_history": np.asarray(handle["permanent_unknown"][:committed + 1], dtype=bool),
            "destination": np.asarray(handle["destination_member"][committed], dtype=bool),
            "contact_time": np.asarray(handle["contact_time"][committed], dtype=np.float64),
            "upward_time": np.asarray(handle["upward_time"][committed], dtype=np.float64),
            "return_time": np.asarray(handle["return_time"][committed], dtype=np.float64),
            "residence": np.asarray(handle["residence_s"][committed], dtype=np.float64),
            "contacted": np.asarray(handle["contacted"][committed], dtype=bool),
            "upward": np.asarray(handle["upward"][committed], dtype=bool),
            "returned": np.asarray(handle["returned"][committed], dtype=bool),
            "event_status": np.asarray(handle["event_status"][committed], dtype=np.int8),
            "mass_closure_error": np.asarray(handle["mass_closure_error"][:committed + 1], dtype=np.float64),
            "residual": np.asarray(handle["residual_estimate_mps"][committed], dtype=np.float64),
            "path_error_budget": np.asarray(handle["path_error_budget_m"][committed], dtype=np.float64),
            "material_reliability": str(handle.attrs.get("material_reliability", "unknown")),
        }
    if result["position"].shape != (len(result["query_mass"]), 3):
        raise ValueError(f"{path} has inconsistent endpoint seed shape")
    return result


def _validate_pair(left: dict, right: dict) -> dict:
    issues = []
    left_binding = left["binding"] or {}
    right_binding = right["binding"] or {}
    for key in ("source_sha256", "h_m", "query_count", "q", "fluid_type", "event_definition"):
        if left_binding.get(key) != right_binding.get(key):
            issues.append(f"binding.{key} differs")
    if left["seed_hash"] != right["seed_hash"]:
        issues.append("seed_hash differs")
    if not np.array_equal(left["query_mass"], right["query_mass"]):
        issues.append("query_mass differs")
    if not np.array_equal(left["source_label"], right["source_label"]):
        issues.append("source_label differs")
    if not np.array_equal(left["time"], right["time"]):
        issues.append("time axis differs")
    if len(left["query_mass"]) != 512 or len(right["query_mass"]) != 512:
        issues.append("seed denominator is not 512")
    if issues:
        raise ValueError("cannot compare traces with incompatible bindings: " + "; ".join(issues))
    return {
        "source_sha256": left_binding.get("source_sha256"),
        "h_m": left_binding.get("h_m"),
        "query_count": len(left["query_mass"]),
        "q": left_binding.get("q"),
        "event_definition": left_binding.get("event_definition"),
    }


def _source_rows(trace: dict) -> dict[str, dict]:
    weight = trace["query_mass"]
    total = float(np.sum(weight))
    labels = trace["source_label"].astype(str)
    final_unknown, _, unknown_possible_from = _unknown_window(trace)
    reliable = ~final_unknown
    observation_end = float(trace["time"][-1])
    residence_lower = np.nan_to_num(
        np.asarray(trace["residence"], dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0
    )
    residence_upper = residence_lower.copy()
    unresolved = final_unknown & np.isfinite(unknown_possible_from)
    # A failed interval has no accepted segment contribution.  The earliest
    # possible post-failure residence is therefore the preceding committed
    # frame; the whole remaining observation window is a conservative upper
    # bound for the unknown seed.
    residence_upper[unresolved] += np.maximum(
        0.0, observation_end - unknown_possible_from[unresolved]
    )
    residence_upper = np.maximum(residence_upper, residence_lower)
    rows = {}
    for source in np.unique(labels):
        select = labels == source
        source_mass = float(np.sum(weight[select]))
        source_reliable = select & reliable
        source_unknown = select & final_unknown
        source_contacted = select & np.asarray(trace["contacted"], dtype=bool)
        source_upward = select & np.asarray(trace["upward"], dtype=bool)
        source_returned = select & np.asarray(trace["returned"], dtype=bool)
        source_destination = source_reliable & trace["destination"]
        source_residence_lower = select & np.isfinite(residence_lower)
        source_right_censored_residence = source_contacted & ~source_returned
        destination_lower = float(np.sum(weight[source_destination]) / source_mass) if source_mass else 0.0
        unknown_fraction = float(np.sum(weight[source_unknown]) / source_mass) if source_mass else 0.0
        source_contact_cdf = _event_cdf_bounds(
            trace["contact_time"], weight, select, final_unknown,
            unknown_possible_from, observation_end, source_mass,
        )
        source_upward_cdf = _event_cdf_bounds(
            trace["upward_time"], weight, select, final_unknown,
            unknown_possible_from, observation_end, source_mass,
        )
        source_return_cdf = _event_cdf_bounds(
            trace["return_time"], weight, select, final_unknown,
            unknown_possible_from, observation_end, source_mass,
        )
        source_residence_cdf = _interval_cdf(
            residence_lower, residence_upper, weight, select, source_mass,
        )
        residence_mean_lower = float(
            np.sum(weight[select] * residence_lower[select]) / source_mass
        ) if source_mass else 0.0
        residence_mean_upper = float(
            np.sum(weight[select] * residence_upper[select]) / source_mass
        ) if source_mass else 0.0
        rows[source] = {
            "initial_mass_fraction": source_mass / total if total else 0.0,
            "unknown_fraction": unknown_fraction,
            "reliable_path_coverage": float(np.sum(weight[source_reliable]) / source_mass) if source_mass else 0.0,
            "contact_fraction_observed": float(np.sum(weight[source_contacted]) / source_mass) if source_mass else 0.0,
            "upward_fraction_observed": float(np.sum(weight[source_upward]) / source_mass) if source_mass else 0.0,
            "return_fraction_observed": float(np.sum(weight[source_returned]) / source_mass) if source_mass else 0.0,
            "destination_fraction_reliable": float(np.sum(weight[source_destination]) / source_mass) if source_mass else 0.0,
            "destination_fraction_bounds": {
                "lower": destination_lower,
                "upper": destination_lower + unknown_fraction,
                "unknown_endpoint_mass_fraction": unknown_fraction,
            },
            "outside_destination_fraction_reliable": float(np.sum(weight[source_reliable & ~trace["destination"]]) / source_mass) if source_mass else 0.0,
            "mass_closure_error_final": float(trace["mass_closure_error"][-1]),
            "first_contact_cdf": source_contact_cdf,
            "first_contact_quantiles_s": _weighted_event_quantiles(
                trace["contact_time"], weight,
                select & np.isfinite(trace["contact_time"]), source_mass,
            ),
            "upward_cdf": source_upward_cdf,
            "return_cdf": source_return_cdf,
            "return_quantiles_s": _weighted_event_quantiles(
                trace["return_time"], weight,
                select & np.isfinite(trace["return_time"]), source_mass,
            ),
            "residence_cdf": source_residence_cdf,
            "residence_metric": "cumulative destination-box time within observed window",
            "residence_bounds_s": {
                "lower_mean": residence_mean_lower,
                "upper_mean": residence_mean_upper,
                "lower_min": float(np.min(residence_lower[select])) if np.any(source_residence_lower) else 0.0,
                "upper_max": float(np.max(residence_upper[select])) if np.any(source_residence_lower) else 0.0,
                "unknown_interval_mass_fraction": unknown_fraction,
                "right_censored_contact_mass_fraction": float(
                    np.sum(weight[source_right_censored_residence]) / source_mass
                ) if source_mass else 0.0,
            },
            "residence_mean_s_all_seeds": residence_mean_lower,
            "residence_mean_s_all_seeds_upper_bound": residence_mean_upper,
            "residence_zero_mass_fraction_lower": source_residence_cdf["zero_mass_fraction_lower"],
            "residence_zero_mass_fraction_upper": source_residence_cdf["zero_mass_fraction_upper"],
        }
    return rows


def _common_path(left: dict, right: dict) -> dict:
    weights = left["query_mass"]
    common = left["reliable_history"].all(axis=0) & right["reliable_history"].all(axis=0)
    union = left["reliable_history"].all(axis=0) | right["reliable_history"].all(axis=0)
    total = float(np.sum(weights))
    if np.any(common):
        error = np.linalg.norm(left["position"][common] - right["position"][common], axis=1)
        common_weight = weights[common]
        weighted_rms = float(np.sqrt(np.sum(common_weight * error ** 2) / np.sum(common_weight)))
        weighted_p95 = float(np.interp(0.95, np.cumsum(common_weight[np.argsort(error)]) / np.sum(common_weight), np.sort(error)))
        max_error = float(np.max(error))
    else:
        weighted_rms = weighted_p95 = max_error = None
    return {
        "common_seed_count": int(np.count_nonzero(common)),
        "union_seed_count": int(np.count_nonzero(union)),
        "common_reliable_path_coverage": float(np.sum(weights[common]) / total) if total else 0.0,
        "union_reliable_path_coverage": float(np.sum(weights[union]) / total) if total else 0.0,
        "endpoint_position_difference_weighted_rms_m": weighted_rms,
        "endpoint_position_difference_weighted_p95_m": weighted_p95,
        "endpoint_position_difference_max_m": max_error,
    }


def compare_traces(s2_path: str | Path, s4_path: str | Path, output: str | Path | None = None) -> dict:
    left = _load_trace(s2_path)
    right = _load_trace(s4_path)
    binding = _validate_pair(left, right)
    rows_left = _source_rows(left)
    rows_right = _source_rows(right)
    if set(rows_left) != set(rows_right):
        raise ValueError("source groups differ")
    source_comparison = {}
    for source in sorted(rows_left):
        source_comparison[source] = {
            "s2": rows_left[source],
            "s4": rows_right[source],
            "difference": {
                "unknown_fraction_s4_minus_s2": rows_right[source]["unknown_fraction"] - rows_left[source]["unknown_fraction"],
                "contact_fraction_s4_minus_s2": rows_right[source]["contact_fraction_observed"] - rows_left[source]["contact_fraction_observed"],
                "return_fraction_s4_minus_s2": rows_right[source]["return_fraction_observed"] - rows_left[source]["return_fraction_observed"],
                "residence_mean_s4_minus_s2": rows_right[source]["residence_mean_s_all_seeds"] - rows_left[source]["residence_mean_s_all_seeds"],
                "residence_mean_upper_bound_s4_minus_s2": rows_right[source]["residence_mean_s_all_seeds_upper_bound"] - rows_left[source]["residence_mean_s_all_seeds_upper_bound"],
            },
        }
    left_unknown = np.sum(left["query_mass"][None, :] * left["unknown_history"], axis=1)
    right_unknown = np.sum(right["query_mass"][None, :] * right["unknown_history"], axis=1)
    result = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "qualification_claim": "none",
        "comparison_status": "diagnostic_only",
        "material_reliability_status": "uncalibrated; support_unknown is not material reliability",
        "s2": {"path": left["path"], "sha256": left["sha256"], "committed_frame": left["committed"], "committed_time_s": float(left["time"][-1]), "material_reliability": left["material_reliability"]},
        "s4": {"path": right["path"], "sha256": right["sha256"], "committed_frame": right["committed"], "committed_time_s": float(right["time"][-1]), "material_reliability": right["material_reliability"]},
        "common_binding": binding,
        "source_comparison": source_comparison,
        "unknown_fraction_by_frame": {
            "time_s": left["time"].tolist(),
            "s2": (left_unknown / np.sum(left["query_mass"])).tolist(),
            "s4": (right_unknown / np.sum(right["query_mass"])).tolist(),
            "s4_minus_s2": ((right_unknown - left_unknown) / np.sum(left["query_mass"])).tolist(),
        },
        "mass_closure": {
            "s2_max_abs_error": float(np.max(np.abs(left["mass_closure_error"]))),
            "s4_max_abs_error": float(np.max(np.abs(right["mass_closure_error"]))),
        },
        "common_reliable_path": _common_path(left, right),
        "support_and_material_policy": {
            "support_unknown": "permanent_unknown after a failed numerical RK stage; retained in 512 denominator",
            "material_reliability": "not inferred from numerical support mask or CDF agreement",
            "unknown_endpoint_bounds": "known reliable endpoint mass is a lower bound; permanent_unknown mass is added only to the upper bound",
            "event_cdf_bounds": "finite event times are observed; unresolved permanent_unknown seeds enter the upper CDF from the preceding committed frame; reliable no-event seeds remain right-censored",
            "residence_cdf_bounds": "all source mass is included; each seed contributes a cumulative observed-window residence interval [lower, upper], with zero for reliable no-contact seeds and conservative remaining-window upper mass after support loss",
            "eventual_residence": "right-censored beyond the observed window when contact occurred without return; no post-window value is imputed",
            "t2": "not evaluated; 0.3 s source is a short canary and not the registered 4.34 s qualification window",
        },
        "t2_status": "not_evaluated",
    }
    if output is not None:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_json_value(result), indent=2, sort_keys=True) + "\n")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s2", type=Path, required=True)
    parser.add_argument("--s4", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare_traces(args.s2, args.s4, args.output)
    print(json.dumps(_json_value(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
