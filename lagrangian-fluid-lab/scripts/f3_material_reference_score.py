"""Prospectively defined, unknown-aware F3 material diagnostics, not qualification.

The thresholds below are new CFD material definitions. They are not the older
manufactured calibration tolerances. Matrix coverage and quadrature are pending.
"""
import numpy as np

from scripts.f3_material_labels import residence_times


THRESHOLDS = {
    "mass_closure_relative": 1e-12,
    "unknown_fraction_per_source": .01,
    "terminal_and_passage_bound_difference": .02,
    "mean_residence_bound_difference_s": .167,
    "observed_event_weighted_mae_s": .02,
    "path_rms_m": .003, "path_p95_m": .006, "path_max_m": .012,
    "temporal_budget_fraction": .2,
}


def validate_seeds(seeds):
    ids = np.asarray(seeds["tracer_id"])
    p = np.asarray(seeds["initial_position"], dtype=float)
    w = np.asarray(seeds["mass_fraction"], dtype=float)
    source = np.asarray(seeds["source_label"])
    if (ids.ndim != 1 or not len(ids) or ids.dtype.kind not in "SU" or np.any(ids == "")
            or len(np.unique(ids)) != len(ids)
            or p.shape != (len(ids), 3) or w.shape != ids.shape or source.shape != ids.shape
            or not np.isfinite(p).all() or not np.isfinite(w).all() or np.any(w <= 0)
            or abs(w.sum() - 1.) > THRESHOLDS["mass_closure_relative"]
            or set(source.tolist()) != {0, 1}
            or not np.array_equal(source, (p[:, 0] >= 0).astype(int))):
        raise ValueError("invalid immutable seed IDs, physical points, source halves or mass weights")
    return ids, p, w, source


def label_trace(trace, seeds):
    """Keep observed arrivals after later failure; failed no-events are censored.

    Events use the declared saved-frame piecewise-linear path. A missing endpoint
    makes its entire residence interval unknown. No substep event truth is claimed.
    """
    # A labelled result is a snapshot; editing a caller's working trajectory
    # later must not silently change the positions behind already-derived labels.
    trace = {k: np.array(v, copy=True) if isinstance(v, np.ndarray) else v for k, v in trace.items()}
    seeds = {k: np.array(v, copy=True) for k, v in seeds.items()}
    ids, initial, weights, source = validate_seeds(seeds)
    time = np.asarray(trace["time"], dtype=float)
    p = np.asarray(trace["position"], dtype=float)
    reliable = np.asarray(trace["reliability_history"])
    if (time.ndim != 1 or len(time) < 2 or time[0] != 0 or not np.isfinite(time).all()
            or np.any(np.diff(time) <= 0) or p.shape != (len(time), len(ids), 3)
            or reliable.shape != p.shape[:2] or reliable.dtype.kind != "b" or not reliable[0].all()
            or np.any(reliable[1:] & ~reliable[:-1]) or not np.isfinite(p[reliable]).all()
            or not np.array_equal(p[0], initial)):
        raise ValueError("invalid full seed axis, time, initial points or cumulative reliability")
    first = np.full(len(ids), np.nan)
    for frame in range(1, len(time)):
        opposite = (p[frame, :, 0] >= 0) != source
        selected = reliable[frame-1] & reliable[frame] & opposite & np.isnan(first)
        x0, x1 = p[frame-1, selected, 0], p[frame, selected, 0]
        alpha = np.divide(-x0, x1-x0, out=np.zeros_like(x0), where=x1 != x0)
        first[selected] = time[frame-1] + np.clip(alpha, 0, 1) * (time[frame]-time[frame-1])
    failed = ~reliable[-1]
    failure_frame = np.where(failed, np.argmax(~reliable, axis=0), -1)
    failure_time = np.where(failed, time[np.maximum(failure_frame, 0)], np.nan)
    last_trusted = np.where(failed, time[np.maximum(failure_frame-1, 0)], time[-1])
    reason = np.full(len(ids), "none", dtype="U40")
    for j in np.flatnonzero(failed):
        interval = failure_frame[j]-1
        reason[j] = "tracer_unknown"
        if "wall_crossing" in trace and trace["wall_crossing"][interval, j]:
            reason[j] = "wall_contact_or_crossing"
        elif "nearest_support_distance" in trace and not np.isfinite(trace["nearest_support_distance"][interval, j]):
            reason[j] = "support_nonfinite"
        elif "nearest_support_distance" in trace and trace["nearest_support_distance"][interval, j] > .03:
            reason[j] = "support_distance_exceedance"
        elif "support_gate_pass" in trace and not trace["support_gate_pass"][interval, j]:
            reason[j] = "support_gate_failure"
    event_status = np.where(np.isfinite(first), "observed",
                            np.where(reliable[-1], "valid_no_event", "censored"))
    terminal = np.where(reliable[-1], (p[-1, :, 0] >= 0).astype(int), 2)
    left, right, unknown = residence_times(time, p, reliable)
    return {**trace, **seeds, "time": time, "position": p,
            "reliability_history": reliable, "first_passage_s": first,
            "first_passage_status": event_status, "terminal_label": terminal,
            "first_failure_frame": failure_frame, "first_failure_time_s": failure_time,
            "last_trusted_time_s": last_trusted, "first_failure_reason": reason,
            "residence_left_s": left, "residence_right_s": right,
            "residence_unknown_s": unknown}


def _validated(value):
    # Recompute all labels from immutable seeds/trace; stale supplied labels cannot
    # convert censored observations into negatives or erase a later failure.
    seeds = {k: value[k] for k in ("tracer_id", "initial_position", "mass_fraction", "source_label")}
    result = label_trace(value, seeds)
    for key in ("first_passage_s", "first_passage_status", "terminal_label",
                "first_failure_frame", "last_trusted_time_s", "residence_left_s",
                "residence_right_s", "residence_unknown_s"):
        if key in value:
            a, b = np.asarray(value[key]), np.asarray(result[key])
            equal = np.array_equal(a, b, equal_nan=True) if a.dtype.kind in "fc" else np.array_equal(a, b)
            if not equal:
                raise ValueError("material label differs from its trajectory: " + key)
    return result


def _cdf_bounds(value, mask, grid):
    w = np.asarray(value["mass_fraction"])[mask]
    den = w.sum()
    first = value["first_passage_s"][mask]
    censor = value["first_passage_status"][mask] == "censored"
    observed = np.isfinite(first)[None, :] & (first[None, :] <= grid[:, None])
    uncertain = censor[None, :] & (grid[:, None] > value["last_trusted_time_s"][mask][None, :])
    lower = observed @ w / den
    return lower, lower + uncertain @ w / den


def _bound_difference(a, b):
    return float(np.max(np.maximum(np.abs(a[0]-b[1]), np.abs(a[1]-b[0]))))


def compare(first, second, *, kind="space"):
    """Compare complete source denominators; return candidate diagnostics only."""
    if kind not in ("space", "substep", "cadence", "quadrature"):
        raise ValueError("unknown material comparison kind")
    if kind == "quadrature":
        raise ValueError("quadrature selection and comparison are not registered yet")
    a, b = _validated(first), _validated(second)
    for field in ("tracer_id", "initial_position", "mass_fraction", "source_label"):
        if not np.array_equal(a[field], b[field]):
            raise ValueError("comparison changes immutable seeds or source weights: " + field)
    ta, tb = a["time"], b["time"]
    if ta[0] != tb[0] or ta[-1] != tb[-1]:
        raise ValueError("comparison changes the material time window")
    common_times, ia, ib = np.intersect1d(ta, tb, return_indices=True)
    if (kind != "cadence" and not np.array_equal(ta, tb)) or len(common_times) != min(len(ta), len(tb)):
        raise ValueError("comparison requires identical times or an exact cadence subset")
    factor = THRESHOLDS["temporal_budget_fraction"] if kind in ("substep", "cadence") else 1.
    grid = np.union1d(ta, tb)
    weights = np.asarray(a["mass_fraction"])
    rows = []
    for source in (0, 1):
        mask = np.asarray(a["source_label"]) == source
        w, den = weights[mask], float(weights[mask].sum())
        unknowns = [float(np.max((~v["reliability_history"][:, mask]) @ w / den)) for v in (a, b)]
        terminal = []
        residence = []
        for v in (a, b):
            category = v["terminal_label"][mask]
            left = float(w[category == 0].sum()/den)
            unknown = float(w[category == 2].sum()/den)
            terminal.append((left, left+unknown))
            low = np.array([np.sum(w*v[f"residence_{side}_s"][mask])/den for side in ("left", "right")])
            width = float(np.sum(w*v["residence_unknown_s"][mask])/den)
            residence.append((low, low+width))
        observed = mask & np.isfinite(a["first_passage_s"]) & np.isfinite(b["first_passage_s"])
        observed_mass = float(weights[observed].sum())
        event_mae = (float(np.sum(weights[observed]*np.abs(a["first_passage_s"][observed]-b["first_passage_s"][observed]))/observed_mass)
                     if observed_mass > 0 else None)
        row = dict(source=source, initial_mass_fraction=den,
                   unknown_fraction_max=unknowns,
                   terminal_mass_worst_bound_difference=_bound_difference(*terminal),
                   first_passage_cdf_worst_bound_difference=_bound_difference(_cdf_bounds(a, mask, grid), _cdf_bounds(b, mask, grid)),
                   mean_residence_worst_bound_difference_s=_bound_difference(*residence),
                   observed_event_weighted_mae_s=event_mae,
                   common_observed_event_mass_fraction_over_source=observed_mass/den,
                   event_time_status="observed" if event_mae is not None else "not_applicable")
        row["within_candidate_budget"] = bool(
            max(unknowns) <= THRESHOLDS["unknown_fraction_per_source"]
            and max(row["terminal_mass_worst_bound_difference"], row["first_passage_cdf_worst_bound_difference"])
                <= factor*THRESHOLDS["terminal_and_passage_bound_difference"]
            and row["mean_residence_worst_bound_difference_s"] <= factor*THRESHOLDS["mean_residence_bound_difference_s"]
            and (event_mae is None or event_mae <= factor*THRESHOLDS["observed_event_weighted_mae_s"]))
        rows.append(row)
    complete = bool(a["reliability_history"].all() and b["reliability_history"].all())
    path = None
    if complete:
        error = np.linalg.norm(a["position"][ia]-b["position"][ib], axis=-1)
        order = np.argsort(error, axis=1, kind="stable")
        sorted_error = np.take_along_axis(error, order, axis=1)
        cumulative = np.cumsum(np.broadcast_to(weights, error.shape)[np.arange(len(error))[:, None], order], axis=1)
        p95 = sorted_error[np.arange(len(error)), np.argmax(cumulative >= .95, axis=1)]
        path = dict(rms_max_m=float(np.sqrt(error**2 @ weights).max()),
                    p95_max_m=float(p95.max()), maximum_m=float(error.max()))
    path_within = bool(path is not None and len(weights) == 512
                       and path["rms_max_m"] <= factor*THRESHOLDS["path_rms_m"]
                       and path["p95_max_m"] <= factor*THRESHOLDS["path_p95_m"]
                       and path["maximum_m"] <= factor*THRESHOLDS["path_max_m"])
    return dict(schema="f3.material.comparison.v1", status="candidate", kind=kind,
                threshold_definition="new prospective CFD material definition, not manufactured calibration",
                thresholds=dict(THRESHOLDS), budget_multiplier=factor, by_source=rows,
                macro_within_candidate_budget=all(r["within_candidate_budget"] for r in rows),
                full_seed_axis_reliable=complete, seed_count=len(weights), common_time_count=len(common_times),
                path_statistics=path, path_within_candidate_budget=path_within,
                quadrature_status="pending", matrix_coverage_status="not_evaluated",
                qualified_T2_macro=False, qualified_T2_path=False,
                scope="saved-frame reconstructed numerical velocity-field material; no continuous or uncorrected physical path claim")
