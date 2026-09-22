"""Registered fixed-denominator scoring and validation-only model selection.

Raw errors remain uncapped. The bounded selection score penalizes every failed
or absent frame at the maximum value, so losing observations cannot help it.
"""
from __future__ import annotations
import math
import numpy as np

SCHEMA = "core.scoring_protocol.v1"
PROTOCOL = {
    "schema": SCHEMA,
    "frame_penalty": 1.0,
    "position_scale": "registered characteristic geometry length in metres",
    "velocity_scale": "sqrt(gravity magnitude * registered characteristic length)",
    "frame_score": "mean(min(position_rmse/length,1), min(velocity_rmse/speed,1))",
    "missing_failed_nonfinite_frame_score": 1.0,
    "case_denominator": "all registered future frames, excluding initial state",
    "aggregation": "case mean within family, then equal-weight family mean",
    "selection": "complete case fraction descending, score ascending, update ascending",
    "eligible_checkpoint_updates": [8000, 16000, 24000, 32000],
    "selection_split": "validation",
    "confidence_interval_unit": "independent physical case, never frame or particle",
}


def score_case(position_rmse, velocity_rmse, *, expected_frames, length_m,
               speed_mps, executed=True, failure_category=None):
    if isinstance(expected_frames, bool) or int(expected_frames) != expected_frames or expected_frames < 1:
        raise ValueError("expected_frames must be a positive integer")
    if not all(math.isfinite(v) and v > 0 for v in (length_m, speed_mps)):
        raise ValueError("normalization scales must be finite and positive")
    x, v = np.asarray(position_rmse, dtype=float), np.asarray(velocity_rmse, dtype=float)
    if x.ndim != 1 or v.shape != x.shape or len(x) > expected_frames:
        raise ValueError("one matched error per registered frame is required")
    if not executed and len(x):
        raise ValueError("unexecuted case cannot contain predictions")
    if np.any(x < 0) or np.any(v < 0):
        raise ValueError("RMSE cannot be negative")
    good = np.isfinite(x) & np.isfinite(v)
    # A nonfinite state terminates an autonomous trajectory. Later finite data
    # cannot silently restart it or restore credit.
    first_bad = int(np.flatnonzero(~good)[0]) if np.any(~good) else len(x)
    scores = np.ones(int(expected_frames), dtype=float)
    scores[:first_bad] = .5 * (np.minimum(x[:first_bad] / length_m, 1.) +
                              np.minimum(v[:first_bad] / speed_mps, 1.))
    complete = bool(executed and first_bad == expected_frames and failure_category is None)
    category = failure_category or (None if complete else "missing_execution" if not executed
                                  else "nonfinite_state" if first_bad < len(x) else "missing_frames")
    return {"expected_frames": int(expected_frames), "finite_prefix_frames": first_bad,
            "executed": bool(executed), "complete": complete, "failure_category": category,
            "first_failure_frame": None if complete else first_bad + 1,
            "selection_score": float(scores.mean()),
            "raw_position_rmse_frame_mean_m": float(x[:first_bad].mean()) if first_bad else None,
            "raw_velocity_rmse_frame_mean_mps": float(v[:first_bad].mean()) if first_bad else None,
            "raw_error_coverage": first_bad / expected_frames}


def aggregate_cases(registry, results):
    """registry maps case ID to family; absent results remain in its denominator."""
    if not registry or set(results) - set(registry):
        raise ValueError("empty registry or unregistered case results")
    families = {}
    for case_id, family in registry.items():
        row = results.get(case_id)
        families.setdefault(family, []).append(row)
    summaries = {}
    for family, rows in sorted(families.items()):
        summaries[family] = {
            "case_count": len(rows),
            "complete_fraction": sum(bool(r and r["complete"]) for r in rows) / len(rows),
            "selection_score": sum(float(r["selection_score"]) if r else 1. for r in rows) / len(rows),
            "missing_execution": sum(not r or not r["executed"] for r in rows),
        }
    return {"families": summaries, "registered_cases": len(registry),
            "complete_fraction": float(np.mean([r["complete_fraction"] for r in summaries.values()])),
            "selection_score": float(np.mean([r["selection_score"] for r in summaries.values()])),
            "missing_execution": sum(r["missing_execution"] for r in summaries.values())}


def select_checkpoint(candidates):
    if not candidates:
        raise ValueError("no checkpoint candidates")
    if sorted(row["update"] for row in candidates) != PROTOCOL["eligible_checkpoint_updates"]:
        raise ValueError("all four registered checkpoints must be evaluated exactly once")
    for row in candidates:
        if row.get("split") != "validation" or row["update"] not in PROTOCOL["eligible_checkpoint_updates"]:
            raise ValueError("only registered validation checkpoints are eligible")
        if row["metrics"]["missing_execution"]:
            raise ValueError("execute every registered validation case before selection")
        if not all(math.isfinite(row["metrics"][key]) and 0 <= row["metrics"][key] <= 1
                   for key in ("complete_fraction", "selection_score")):
            raise ValueError("invalid checkpoint selection metrics")
    return min(candidates, key=lambda r: (-r["metrics"]["complete_fraction"],
                                        r["metrics"]["selection_score"], r["update"]))


def bootstrap_case_interval(registry, results, *, physical_case_ids, draws=2000, seed=17):
    """Stratified physical-case cluster bootstrap of the family macro score.

    Multiple views of the same physical process share a bootstrap draw. Missing
    executions keep their penalty, exactly as in the point estimate.
    """
    point = aggregate_cases(registry, results)
    if set(physical_case_ids) != set(registry) or draws < 2:
        raise ValueError("every registered case needs a physical lineage; draws >= 2")
    clusters, owners = {}, {}
    for case, family in registry.items():
        physical = physical_case_ids[case]
        if not physical or owners.setdefault(physical, family) != family:
            raise ValueError("physical case cannot belong to multiple mechanism families")
        clusters.setdefault(family, {}).setdefault(physical, []).append(
            float(results[case]["selection_score"]) if case in results else 1.)
    rng = np.random.default_rng(seed)
    sampled = np.zeros(int(draws))
    counts = {}
    physical_point = []
    for family, groups in sorted(clusters.items()):
        # Collapse views before sampling so adding crops/resolutions does not
        # increase the effective sample size of an existing physical process.
        values = np.array([np.mean(v) for _, v in sorted(groups.items())])
        counts[family] = len(values)
        physical_point.append(float(values.mean()))
        sampled += values[rng.integers(0, len(values), (int(draws), len(values)))].mean(axis=1)
    sampled /= len(clusters)
    lower, upper = np.quantile(sampled, [.025, .975])
    return {"method": "physical_case_cluster_bootstrap_stratified_by_family",
            "confidence": .95, "lower": float(lower), "upper": float(upper),
            "point_estimate": float(np.mean(physical_point)),
            "registered_view_point_estimate": point["selection_score"], "draws": int(draws), "seed": seed,
            "independent_cases_by_family": counts,
            "insufficient_within_family_variation": any(n < 2 for n in counts.values())}
