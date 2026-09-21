"""Registered fixed-denominator scoring and validation-only model selection.

Raw errors remain uncapped. The bounded selection score penalizes every failed
or absent frame at the maximum value, so losing observations cannot help it.
"""
from __future__ import annotations
from collections.abc import Mapping
import math
from numbers import Real
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


def _strict_integer(value, name):
    """Accept integer counters without truncating malformed numeric values."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _strict_nonnegative_integer(value, name):
    value = _strict_integer(value, name)
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _strict_bool(value, name):
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be a boolean")
    return bool(value)


def _finite_real(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    return value


def _unit_interval(value, name):
    value = _finite_real(value, name)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1]")
    return value


def _stable_sort_key(value):
    return (type(value).__module__, type(value).__qualname__, repr(value))


def _validated_registry(registry):
    if not isinstance(registry, Mapping) or not registry:
        raise ValueError("empty registry")
    try:
        items = list(registry.items())
        set(registry)
    except (TypeError, ValueError) as error:
        raise ValueError("registry keys must be hashable") from error
    for case_id, family in items:
        try:
            hash(case_id)
            hash(family)
        except TypeError as error:
            raise ValueError("case IDs and families must be hashable") from error
        if case_id is None or family is None:
            raise ValueError("registered cases require case IDs and families")
        if isinstance(case_id, str) and not case_id:
            raise ValueError("registered cases require non-empty case IDs")
        if isinstance(family, str) and not family:
            raise ValueError("registered cases require non-empty families")
    return items


def _validated_case_result(row, case_id):
    """Validate the score fields consumed by summary/selection code.

    Missing rows are represented by ``None`` and are handled by the caller as
    all-penalty, unexecuted registered cases.  A present row must be a finite,
    bounded score produced by the evaluator; malformed summaries are rejected
    instead of being allowed to create a favorable aggregate or CI.
    """
    if row is None:
        return None
    if not isinstance(row, Mapping):
        raise ValueError(f"case {case_id!r} result must be a mapping")
    required = ("complete", "executed", "selection_score")
    missing = [key for key in required if key not in row]
    if missing:
        raise ValueError(f"case {case_id!r} result is missing {', '.join(missing)}")
    complete = _strict_bool(row["complete"], f"case {case_id!r} complete")
    executed = _strict_bool(row["executed"], f"case {case_id!r} executed")
    selection_score = _unit_interval(
        row["selection_score"], f"case {case_id!r} selection_score")
    if not executed and selection_score != PROTOCOL["frame_penalty"]:
        raise ValueError(f"unexecuted case {case_id!r} must receive the fixed penalty")
    if complete and not executed:
        raise ValueError(f"unexecuted case {case_id!r} cannot be complete")
    failure_category = row.get("failure_category")
    if failure_category is not None and (
            not isinstance(failure_category, str) or not failure_category):
        raise ValueError(f"case {case_id!r} has an invalid failure category")
    if not complete and failure_category is None:
        raise ValueError(f"incomplete case {case_id!r} requires a failure category")
    if complete and failure_category is not None:
        raise ValueError(f"complete case {case_id!r} cannot have a failure category")

    # Validate optional score metadata when present, without making the
    # aggregation API depend on fields that existing callers do not consume.
    if "expected_frames" in row:
        expected_frames = _strict_integer(
            row["expected_frames"], f"case {case_id!r} expected_frames")
        if expected_frames < 1:
            raise ValueError(f"case {case_id!r} expected_frames must be positive")
    if "finite_prefix_frames" in row:
        finite_prefix = _strict_integer(
            row["finite_prefix_frames"], f"case {case_id!r} finite_prefix_frames")
        expected_frames = row.get("expected_frames")
        if expected_frames is not None:
            expected_frames = _strict_integer(
                expected_frames, f"case {case_id!r} expected_frames")
            if not 0 <= finite_prefix <= expected_frames:
                raise ValueError(f"case {case_id!r} finite prefix exceeds its denominator")
        elif finite_prefix < 0:
            raise ValueError(f"case {case_id!r} finite prefix must be non-negative")
    if "raw_error_coverage" in row:
        _unit_interval(row["raw_error_coverage"], f"case {case_id!r} raw_error_coverage")
    for key in ("raw_position_rmse_frame_mean_m", "raw_velocity_rmse_frame_mean_mps"):
        if key in row and row[key] is not None and _finite_real(row[key], f"case {case_id!r} {key}") < 0:
            raise ValueError(f"case {case_id!r} {key} cannot be negative")
    if "first_failure_frame" in row and row["first_failure_frame"] is not None:
        first_failure = _strict_integer(
            row["first_failure_frame"], f"case {case_id!r} first_failure_frame")
        if first_failure < 1:
            raise ValueError(f"case {case_id!r} first_failure_frame must be positive")
    return {"complete": complete, "executed": executed,
            "selection_score": selection_score}


def _validated_case_rows(registry, results):
    items = _validated_registry(registry)
    if not isinstance(results, Mapping):
        raise ValueError("case results must be a mapping")
    try:
        extra = set(results) - set(registry)
    except (TypeError, ValueError) as error:
        raise ValueError("case result keys must be hashable") from error
    if extra:
        raise ValueError("unregistered case results")
    rows = {
        case_id: _validated_case_result(results.get(case_id), case_id)
        for case_id, _family in items
    }
    return items, rows


def _aggregate_validated_rows(items, rows):
    families = {}
    for case_id, family in items:
        families.setdefault(family, []).append(rows[case_id])
    summaries = {}
    for family in sorted(families, key=_stable_sort_key):
        family_rows = families[family]
        case_count = len(family_rows)
        summaries[family] = {
            "case_count": case_count,
            "complete_fraction": sum(
                bool(row and row["complete"]) for row in family_rows) / case_count,
            "selection_score": sum(
                row["selection_score"] if row is not None
                else PROTOCOL["frame_penalty"]
                for row in family_rows) / case_count,
            "missing_execution": sum(
                row is None or not row["executed"] for row in family_rows),
        }
    return {
        "families": summaries,
        "registered_cases": len(items),
        "complete_fraction": float(np.mean(
            [row["complete_fraction"] for row in summaries.values()])),
        "selection_score": float(np.mean(
            [row["selection_score"] for row in summaries.values()])),
        "missing_execution": sum(
            row["missing_execution"] for row in summaries.values()),
    }


def summarize_case_scores(registry, results):
    """Strictly summarize registered case scores using the frozen denominator."""
    items, rows = _validated_case_rows(registry, results)
    return _aggregate_validated_rows(items, rows)


def score_case(position_rmse, velocity_rmse, *, expected_frames, length_m,
               speed_mps, executed=True, failure_category=None):
    expected_frames = _strict_integer(expected_frames, "expected_frames")
    if expected_frames < 1:
        raise ValueError("expected_frames must be a positive integer")
    length_m = _finite_real(length_m, "length_m")
    speed_mps = _finite_real(speed_mps, "speed_mps")
    if length_m <= 0 or speed_mps <= 0:
        raise ValueError("normalization scales must be finite and positive")
    executed = _strict_bool(executed, "executed")
    if failure_category is not None and (
            not isinstance(failure_category, str) or not failure_category):
        raise ValueError("failure_category must be a non-empty string or None")
    x, v = np.asarray(position_rmse, dtype=float), np.asarray(velocity_rmse, dtype=float)
    if x.ndim != 1 or v.shape != x.shape or len(x) > expected_frames:
        raise ValueError("one matched error per registered frame is required")
    if not executed and len(x):
        # A setup failure still carries one explicit placeholder per
        # registered future frame so the fixed denominator survives into the
        # evaluator.  Those placeholders are deliberately non-finite and are
        # treated as missing execution below; finite values would be a
        # prediction and therefore violate the unexecuted contract.
        if len(x) != int(expected_frames) or np.isfinite(x).any() or np.isfinite(v).any():
            raise ValueError("unexecuted case cannot contain predictions")
    if np.any(np.isfinite(x) & (x < 0)) or np.any(np.isfinite(v) & (v < 0)):
        raise ValueError("RMSE cannot be negative")
    good = np.isfinite(x) & np.isfinite(v)
    # A nonfinite state terminates an autonomous trajectory. Later finite data
    # cannot silently restart it or restore credit.
    first_bad = int(np.flatnonzero(~good)[0]) if np.any(~good) else len(x)
    scores = np.ones(int(expected_frames), dtype=float)
    scores[:first_bad] = .5 * (np.minimum(x[:first_bad] / length_m, 1.) +
                              np.minimum(v[:first_bad] / speed_mps, 1.))
    complete = bool(executed and first_bad == expected_frames and failure_category is None)
    category = failure_category if failure_category is not None else (
        None if complete else "missing_execution" if not executed
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
    return summarize_case_scores(registry, results)


def _validated_selection_metrics(metrics, *, allow_legacy=False):
    if not isinstance(metrics, Mapping):
        raise ValueError("checkpoint metrics must be a mapping")
    has_registered_cases = "registered_cases" in metrics
    has_families = "families" in metrics
    if not has_registered_cases and not has_families:
        if not allow_legacy:
            raise ValueError("checkpoint metrics must retain the registered denominator")
        # Older milestone receipts were already admitted by the formal
        # milestone path but only persisted the selector fields.  Keep that
        # narrow compatibility path; new aggregate summaries must carry the
        # complete denominator below.
        return {
            "registered_cases": None,
            "family_counts": None,
            "complete_fraction": _unit_interval(
                metrics.get("complete_fraction"), "complete_fraction"),
            "selection_score": _unit_interval(
                metrics.get("selection_score"), "selection_score"),
            "missing_execution": _strict_nonnegative_integer(
                metrics.get("missing_execution"), "missing_execution"),
        }
    if has_registered_cases != has_families:
        raise ValueError("checkpoint metrics must retain the complete denominator")
    registered_cases = _strict_integer(
        metrics.get("registered_cases"), "registered_cases")
    if registered_cases < 1:
        raise ValueError("registered_cases must be positive")
    families = metrics.get("families")
    if not isinstance(families, Mapping) or not families:
        raise ValueError("checkpoint metrics must retain family summaries")
    family_counts = {}
    family_complete = []
    family_scores = []
    family_missing = 0
    for family, summary in families.items():
        if not isinstance(summary, Mapping):
            raise ValueError("checkpoint family summary must be a mapping")
        case_count = _strict_integer(
            summary.get("case_count"), f"family {family!r} case_count")
        if case_count < 1:
            raise ValueError("family case_count must be positive")
        complete_fraction = _unit_interval(
            summary.get("complete_fraction"),
            f"family {family!r} complete_fraction")
        selection_score = _unit_interval(
            summary.get("selection_score"),
            f"family {family!r} selection_score")
        missing_execution = _strict_nonnegative_integer(
            summary.get("missing_execution"),
            f"family {family!r} missing_execution")
        if not 0 <= missing_execution <= case_count:
            raise ValueError("family missing_execution is outside its denominator")
        family_counts[family] = case_count
        family_complete.append(complete_fraction)
        family_scores.append(selection_score)
        family_missing += missing_execution

    if sum(family_counts.values()) != registered_cases:
        raise ValueError("checkpoint metrics family denominator mismatch")
    complete_fraction = _unit_interval(
        metrics.get("complete_fraction"), "complete_fraction")
    selection_score = _unit_interval(
        metrics.get("selection_score"), "selection_score")
    missing_execution = _strict_nonnegative_integer(
        metrics.get("missing_execution"), "missing_execution")
    if not 0 <= missing_execution <= registered_cases:
        raise ValueError("missing_execution is outside the registered denominator")
    if not math.isclose(complete_fraction, float(np.mean(family_complete)),
                        rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("checkpoint complete_fraction is not the family macro")
    if not math.isclose(selection_score, float(np.mean(family_scores)),
                        rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("checkpoint selection_score is not the family macro")
    if missing_execution != family_missing:
        raise ValueError("checkpoint missing_execution does not match families")
    return {
        "registered_cases": registered_cases,
        "family_counts": family_counts,
        "complete_fraction": complete_fraction,
        "selection_score": selection_score,
        "missing_execution": missing_execution,
    }


def select_checkpoint(candidates):
    try:
        candidates = list(candidates)
    except TypeError as error:
        raise ValueError("checkpoint candidates must be iterable") from error
    if not candidates:
        raise ValueError("no checkpoint candidates")
    updates = []
    for row in candidates:
        if not isinstance(row, Mapping):
            raise ValueError("checkpoint candidate must be a mapping")
        updates.append(_strict_integer(row.get("update"), "checkpoint update"))
    if sorted(updates) != PROTOCOL["eligible_checkpoint_updates"]:
        raise ValueError("all four registered checkpoints must be evaluated exactly once")
    denominator = None
    for row, update in zip(candidates, updates):
        if row.get("split") != "validation" or update not in PROTOCOL["eligible_checkpoint_updates"]:
            raise ValueError("only registered validation checkpoints are eligible")
        if "test_included" in row and _strict_bool(
                row["test_included"], "test_included"):
            raise ValueError("checkpoint selection must exclude test data")
        formal_eligible = False
        if "formal_eligible" in row:
            formal_eligible = _strict_bool(row["formal_eligible"], "formal_eligible")
        metrics = _validated_selection_metrics(
            row.get("metrics"), allow_legacy=formal_eligible)
        signature = (metrics["registered_cases"], metrics["family_counts"])
        if denominator is None:
            denominator = signature
        elif signature != denominator:
            raise ValueError("checkpoint candidates do not share one registered denominator")
        if metrics["missing_execution"] != 0:
            raise ValueError("execute every registered validation case before selection")
    return min(candidates, key=lambda r: (-r["metrics"]["complete_fraction"],
                                        r["metrics"]["selection_score"], r["update"]))


def bootstrap_case_interval(registry, results, *, physical_case_ids, draws=2000, seed=17):
    """Stratified physical-case cluster bootstrap of the family macro score.

    Multiple views of the same physical process share a bootstrap draw. Missing
    executions keep their penalty, exactly as in the point estimate.
    """
    items, rows = _validated_case_rows(registry, results)
    point = _aggregate_validated_rows(items, rows)
    draws = _strict_integer(draws, "draws")
    if draws < 2:
        raise ValueError("every registered case needs a physical lineage; draws >= 2")
    if not isinstance(physical_case_ids, Mapping):
        raise ValueError("physical_case_ids must be a mapping")
    try:
        physical_keys = set(physical_case_ids)
        registry_keys = set(registry)
    except (TypeError, ValueError) as error:
        raise ValueError("physical case keys must be hashable") from error
    if physical_keys != registry_keys:
        raise ValueError("every registered case needs a physical lineage")
    if seed is not None:
        seed = _strict_integer(seed, "seed")
    clusters, owners = {}, {}
    for case, family in items:
        physical = physical_case_ids[case]
        try:
            hash(physical)
        except TypeError as error:
            raise ValueError("physical case IDs must be hashable") from error
        if physical is None or (isinstance(physical, str) and not physical):
            raise ValueError("physical case IDs must be non-empty")
        if isinstance(physical, Real) and not isinstance(physical, (bool, np.bool_)) \
                and not math.isfinite(float(physical)):
            raise ValueError("physical case IDs must be finite")
        if physical in owners and owners[physical] != family:
            raise ValueError("physical case cannot belong to multiple mechanism families")
        owners[physical] = family
        clusters.setdefault(family, {}).setdefault(physical, []).append(
            PROTOCOL["frame_penalty"] if rows[case] is None
            else rows[case]["selection_score"])
    rng = np.random.default_rng(seed)
    sampled = np.zeros(draws)
    counts = {}
    physical_point = []
    for family in sorted(clusters, key=_stable_sort_key):
        groups = clusters[family]
        # Collapse views before sampling so adding crops/resolutions does not
        # increase the effective sample size of an existing physical process.
        values = np.array([
            np.mean(v) for _, v in sorted(groups.items(), key=lambda item: _stable_sort_key(item[0]))
        ])
        counts[family] = len(values)
        physical_point.append(float(values.mean()))
        sampled += values[rng.integers(0, len(values), (draws, len(values)))].mean(axis=1)
    sampled /= len(clusters)
    lower, upper = np.quantile(sampled, [.025, .975])
    return {"method": "physical_case_cluster_bootstrap_stratified_by_family",
            "confidence": .95, "lower": float(lower), "upper": float(upper),
            "point_estimate": float(np.mean(physical_point)),
            "registered_view_point_estimate": point["selection_score"], "draws": draws, "seed": seed,
            "independent_cases_by_family": counts,
            "insufficient_within_family_variation": any(n < 2 for n in counts.values())}
