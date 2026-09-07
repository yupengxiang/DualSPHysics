#!/usr/bin/env python3
"""Bounded convergence and sensitivity audit for independent material tracers.

This is deliberately a numerical-consistency probe, not a physical-validation
claim.  It repeats the same solver export with several saved-frame cadences,
tracer integration substep counts, and mass-weighted seed counts.  Every
setting is compared with the solver particle carrying the selected initial
identity.  The audit therefore exposes interpolation/support failures and
cadence sensitivity before a production material-transport target is frozen.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time as wall_time

import h5py
import numpy as np

try:
    from scripts.boundary_sidecars import sidecar_provider
    from scripts.passive_tracers import advect_hdf5, weighted_stratified_seeds
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from boundary_sidecars import sidecar_provider
    from passive_tracers import advect_hdf5, weighted_stratified_seeds


LAB = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"
DEFAULT_REPORT = LAB / "campaigns" / "v0.1-candidate" / "r3-g2-tracer-convergence.json"

# One representative physical case per currently selected T1 family.  The
# matrix is intentionally bounded; it is not a claim that three cases cover a
# production family.  W06 is used for F2 because its output cadence is an
# order of magnitude finer than the F1/F3 development exports.
DEFAULT_CASES = (
    "F1_twin_obstacle",
    "W06_standard_slow_center",
    "F3_transverse_slosh",
)
DEFAULT_COUNTS = (16, 32, 64)
DEFAULT_FRAME_STRIDES = (1, 2, 5)
DEFAULT_SUBSTEPS = (1, 4)


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float | None:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    finite = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not finite.any():
        return None
    return float(np.sum(values[finite] * weights[finite]) / np.sum(weights[finite]))


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float | None:
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    finite = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not finite.any():
        return None
    order = np.argsort(values[finite])
    ordered_values = values[finite][order]
    ordered_weights = weights[finite][order]
    cumulative = np.cumsum(ordered_weights)
    target = float(np.clip(quantile, 0.0, 1.0)) * cumulative[-1]
    return float(ordered_values[np.searchsorted(cumulative, target, side="left")])


def _frame_indices(frame_count: int, stride: int) -> np.ndarray:
    if int(stride) < 1:
        raise ValueError("frame stride must be positive")
    indices = list(range(0, int(frame_count), int(stride)))
    if indices[-1] != int(frame_count) - 1:
        indices.append(int(frame_count) - 1)
    return np.asarray(indices, dtype=int)


def _solver_reference(h5_path: Path, seed_indices: np.ndarray, stride: int):
    with h5py.File(Path(h5_path), "r") as h5:
        indices = _frame_indices(len(h5["time"]), stride)
        position = h5["position"][indices][:, seed_indices].astype(np.float64)
        valid = h5["valid"][indices][:, seed_indices].astype(bool)
        valid &= h5["type"][indices][:, seed_indices] == 3
        time = h5["time"][indices].astype(np.float64)
    return time, position, valid


def _trajectory_summary(trace: dict, reference_position: np.ndarray,
                        reference_valid: np.ndarray, seeds: dict, dp: float,
                        elapsed_seconds: float, boundary_available: bool = False) -> dict:
    if trace["position"].shape != reference_position.shape:
        raise ValueError("tracer and solver reference axes do not match")
    solver_valid = reference_valid & np.asarray(trace["reliability_history"], dtype=bool)
    finite = np.all(np.isfinite(trace["position"]), axis=-1)
    valid = solver_valid & finite
    error = np.linalg.norm(trace["position"] - reference_position, axis=-1)
    weights = np.broadcast_to(np.asarray(seeds["mass_weight"], dtype=float), error.shape)
    flat = valid.ravel()
    final_weights = weights[-1]
    final_valid = valid[-1]
    support = np.asarray(trace["nearest_support_distance"], dtype=float)
    support_finite = support[np.isfinite(support)]
    visible = np.asarray(trace["minimum_visible_neighbours"], dtype=float)
    visible_finite = visible[np.isfinite(visible)]
    flat_error = error.ravel()[flat]
    flat_weights = weights.ravel()[flat]
    weighted_squared_error = _weighted_mean((flat_error / dp) ** 2, flat_weights)
    endpoint_squared_error = _weighted_mean(
        (error[-1, final_valid] / dp) ** 2, final_weights[final_valid])
    represented_mass = float(np.sum(seeds["mass_weight"]))
    closure_error = represented_mass - float(seeds["initial_fluid_mass"])
    mass_weighted_final_reliability = float(
        np.sum(final_weights * np.asarray(trace["reliable"], dtype=float))
        / max(represented_mass, 1e-30)
    )
    mass_weighted_valid_fraction = float(
        np.sum(weights * valid.astype(float))
        / max(represented_mass * error.shape[0], 1e-30)
    )
    return {
        "seed_count": int(len(seeds["indices"])),
        "represented_initial_mass_kg": represented_mass,
        "mass_weight_closure_error_kg": closure_error,
        "mass_weight_closure_relative_error": abs(closure_error) / max(float(seeds["initial_fluid_mass"]), 1e-30),
        "reliable_final_fraction_by_count": float(np.mean(trace["reliable"])),
        "reliable_final_fraction_by_initial_mass": mass_weighted_final_reliability,
        "solver_valid_fraction": float(np.mean(valid)),
        "solver_valid_fraction_by_initial_mass": mass_weighted_valid_fraction,
        "position_rmse_over_dp": float(np.sqrt(weighted_squared_error))
        if weighted_squared_error is not None else None,
        "position_ade_over_dp": _weighted_mean(flat_error / dp, flat_weights),
        "endpoint_rmse_over_dp": float(np.sqrt(endpoint_squared_error))
        if endpoint_squared_error is not None else None,
        "endpoint_p95_over_dp": _weighted_quantile(error[-1, final_valid] / dp,
                                                   final_weights[final_valid], 0.95),
        "support_median_over_dp": float(np.median(support_finite) / dp) if support_finite.size else None,
        "support_p95_over_dp": float(np.quantile(support_finite, 0.95) / dp) if support_finite.size else None,
        "minimum_visible_neighbours": int(np.min(visible_finite)) if visible_finite.size else None,
        "saved_cadence_median_s": float(np.median(np.diff(trace["time"]))),
        "wall_geometry_available": bool(boundary_available),
        "wall_crossing_rejections": int(np.asarray(trace["wall_crossing"], dtype=bool).sum()),
        "elapsed_seconds": float(elapsed_seconds),
    }


def _common_time_pairs(first_time: np.ndarray, second_time: np.ndarray, tolerance: float = 1e-8):
    """Return exact (within tolerance) time-index pairs in chronological order."""
    first_time = np.asarray(first_time, dtype=float)
    second_time = np.asarray(second_time, dtype=float)
    pairs = []
    for i, value in enumerate(first_time):
        j = int(np.searchsorted(second_time, value))
        candidates = [candidate for candidate in (j - 1, j) if 0 <= candidate < len(second_time)]
        if not candidates:
            continue
        best = min(candidates, key=lambda candidate: abs(second_time[candidate] - value))
        if abs(second_time[best] - value) <= tolerance:
            pairs.append((i, best))
    return pairs


def compare_traces(first: dict, second: dict, dp: float) -> dict:
    """Compare two settings on their common saved times and reliable seeds."""
    pairs = _common_time_pairs(first["time"], second["time"])
    errors = []
    endpoint = None
    for first_index, second_index in pairs:
        reliable = (np.asarray(first["reliability_history"], dtype=bool)[first_index]
                    & np.asarray(second["reliability_history"], dtype=bool)[second_index])
        if not reliable.any():
            continue
        delta = np.linalg.norm(first["position"][first_index, reliable]
                               - second["position"][second_index, reliable], axis=1)
        errors.extend(delta.tolist())
        if first_index == len(first["time"]) - 1 or second_index == len(second["time"]) - 1:
            endpoint = delta
    values = np.asarray(errors, dtype=float)
    endpoint_values = np.asarray(endpoint if endpoint is not None else [], dtype=float)
    return {
        "common_time_samples": int(len(pairs)),
        "trajectory_delta_rmse_over_dp": float(np.sqrt(np.mean(values ** 2)) / dp) if values.size else None,
        "trajectory_delta_p95_over_dp": float(np.quantile(values, 0.95) / dp) if values.size else None,
        "endpoint_delta_rmse_over_dp": float(np.sqrt(np.mean(endpoint_values ** 2)) / dp)
        if endpoint_values.size else None,
    }


def _initial_fluid_mass(h5_path: Path) -> float:
    with h5py.File(Path(h5_path), "r") as h5:
        mask = h5["valid"][0] & (h5["type"][0] == 3)
        return float(np.sum(h5["mass"][0, mask]))


def run_case(case: dict, h5_path: Path, *, counts=DEFAULT_COUNTS,
             frame_strides=DEFAULT_FRAME_STRIDES, substeps=DEFAULT_SUBSTEPS,
             sidecar_path: Path | None = None):
    dp = float(case["numerics"]["particle_spacing_m"])
    initial_mass = _initial_fluid_mass(h5_path)
    barrier = sidecar_provider(sidecar_path) if sidecar_path is not None else None
    traces = {}
    records = []
    for count in counts:
        seeds = weighted_stratified_seeds(h5_path, maximum=int(count))
        seeds["initial_fluid_mass"] = initial_mass
        for stride in frame_strides:
            for integration_substeps in substeps:
                started = wall_time.perf_counter()
                trace = advect_hdf5(
                    h5_path,
                    seeds["position"],
                    neighbours=24,
                    regularization=0.1 * dp,
                    maximum_support_distance=1.75 * dp,
                    frame_stride=int(stride),
                    substeps_per_interval=int(integration_substeps),
                    barrier_provider=barrier,
                )
                elapsed = wall_time.perf_counter() - started
                reference_time, reference_position, reference_valid = _solver_reference(
                    h5_path, seeds["indices"], int(stride))
                if not np.allclose(reference_time, trace["time"], atol=1e-10, rtol=0):
                    raise ValueError("tracer time axis differs from solver reference")
                key = (int(count), int(stride), int(integration_substeps))
                traces[key] = trace
                records.append({
                    "seed_count": int(count),
                    "frame_stride": int(stride),
                    "tracer_substeps_per_saved_interval": int(integration_substeps),
                    "summary": _trajectory_summary(
                        trace, reference_position, reference_valid, seeds, dp, elapsed,
                        boundary_available=sidecar_path is not None),
                })

        # Explicitly expose the otherwise easy-to-miss distinction between
        # integration refinement and saved-cadence refinement.
        reference_key = (int(count), 1, max(int(value) for value in substeps))
        reference_trace = traces[reference_key]
        for record in records:
            if record["seed_count"] != int(count):
                continue
            key = (int(count), record["frame_stride"], record["tracer_substeps_per_saved_interval"])
            record["difference_from_stride1_max_substeps"] = compare_traces(
                traces[key], reference_trace, dp)
        for stride in frame_strides:
            if (int(count), int(stride), 1) in traces and (int(count), int(stride), max(substeps)) in traces:
                low = traces[(int(count), int(stride), 1)]
                high = traces[(int(count), int(stride), max(substeps))]
                for record in records:
                    if (record["seed_count"], record["frame_stride"],
                        record["tracer_substeps_per_saved_interval"]) == (int(count), int(stride), 1):
                        record["substep_refinement_delta"] = compare_traces(low, high, dp)
    return records


def _load_cases(manifest_path: Path, selected_ids: tuple[str, ...]):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    records = {record["case_id"]: record for record in manifest["cases"]}
    missing = sorted(set(selected_ids) - set(records))
    if missing:
        raise ValueError(f"cases missing from release manifest: {missing}")
    selected = []
    for case_id in selected_ids:
        record = records[case_id]
        path = manifest_path.parent / record["hdf5"]
        if not path.is_file():
            raise FileNotFoundError(path)
        selected.append((record, path))
    return selected


def build_report(manifest_path: Path = DEFAULT_MANIFEST, selected_ids: tuple[str, ...] = DEFAULT_CASES,
                 *, counts=DEFAULT_COUNTS, frame_strides=DEFAULT_FRAME_STRIDES,
                 substeps=DEFAULT_SUBSTEPS, sidecar_dir: Path | None = None) -> dict:
    selected = _load_cases(manifest_path, selected_ids)
    case_reports = {}
    for case, path in selected:
        sidecar_path = None
        if sidecar_dir is not None:
            sidecar_path = Path(sidecar_dir).resolve() / f"{case['case_id']}.h5"
            if not sidecar_path.is_file():
                raise FileNotFoundError(sidecar_path)
        records = run_case(case, path, counts=counts, frame_strides=frame_strides,
                           substeps=substeps, sidecar_path=sidecar_path)
        case_reports[case["case_id"]] = {
            "family": case["family"],
            "mechanism": case["physics"].get("mechanism"),
            "hdf5": str(path.relative_to(Path(manifest_path).resolve().parent)),
            "particle_spacing_m": float(case["numerics"]["particle_spacing_m"]),
            "boundary_sidecar": str(sidecar_path.relative_to(LAB)) if sidecar_path else "missing; numerical probe runs without wall visibility",
            "settings": records,
        }
    return {
        "schema_version": 1,
        "scope": "R3 G2 independent tracer convergence and sensitivity addendum",
        "execution_status": "complete",
        "acceptance_status": "candidate_wall_aware_geometry_only" if sidecar_dir else "candidate_only",
        "non_claim": "same-solver numerical consistency; not external physical validation",
        "matrix": {
            "case_ids": list(selected_ids),
            "tracer_counts": [int(value) for value in counts],
            "frame_strides": [int(value) for value in frame_strides],
            "tracer_substeps_per_saved_interval": [int(value) for value in substeps],
            "neighbours": 24,
            "regularization_over_dp": 0.1,
            "maximum_support_over_dp": 1.75,
            "mass_closure_relative_tolerance": 1e-6,
            "wall_visibility": sidecar_dir is not None,
            "sidecar_directory": str(Path(sidecar_dir).resolve().relative_to(LAB)) if sidecar_dir else None,
        },
        "interpretation": {
            "substeps": "compare 1 vs the largest configured substep count at the same saved cadence; substeps cannot recover omitted solver output times",
            "cadence": "compare frame_stride 1/2/5 against the finest saved cadence at common times; any drift is an observation-cadence sensitivity",
            "mass": "all reported averages use source-stratified initial mass weights; identity comparison uses the selected initial solver particle indices",
            "reliability": "both count-weighted and initial-mass-weighted reliability are reported so high-mass failed tracers cannot be hidden by a count fraction",
            "release_gate": "no setting is promoted to a material benchmark target until every admitted case has boundary triangles and a declared destination specification",
        },
        "cases": case_reports,
        "open_blockers": [
            "destination regions and material task labels are absent from the development pilot",
            "the matrix has one representative case per selected T1 family, not production family coverage",
            "small spill-tail accuracy still requires higher tracer counts and importance sampling on accepted cases",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--case", dest="cases", action="append", default=None,
                        help="case ID; may be repeated (default: one representative F1/F2/F3 case)")
    parser.add_argument("--counts", nargs="+", type=int, default=list(DEFAULT_COUNTS))
    parser.add_argument("--frame-strides", nargs="+", type=int, default=list(DEFAULT_FRAME_STRIDES))
    parser.add_argument("--substeps", nargs="+", type=int, default=list(DEFAULT_SUBSTEPS))
    parser.add_argument("--sidecar-dir", type=Path, default=None,
                        help="optional finite-boundary sidecar directory for wall-aware tracing")
    args = parser.parse_args()
    case_ids = tuple(args.cases) if args.cases else DEFAULT_CASES
    report = build_report(args.manifest.resolve(), case_ids, counts=tuple(args.counts),
                          frame_strides=tuple(args.frame_strides), substeps=tuple(args.substeps),
                          sidecar_dir=args.sidecar_dir.resolve() if args.sidecar_dir else None)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "report": str(args.report),
        "cases": list(case_ids),
        "setting_count": sum(len(case["settings"]) for case in report["cases"].values()),
        "acceptance_status": report["acceptance_status"],
    }, indent=2))


if __name__ == "__main__":
    main()
