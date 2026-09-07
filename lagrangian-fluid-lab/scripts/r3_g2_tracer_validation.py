#!/usr/bin/env python3
"""Close the R3 material-tracer acceptance gaps with adversarial and real probes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import numpy as np

try:
    from scripts.passive_tracers import (
        advect_hdf5,
        box_surface_triangles,
        corresponding_segments_blocked,
        rigid_barrier_provider,
        segment_visibility,
        shepard_velocity,
        weighted_stratified_seeds,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from passive_tracers import (
        advect_hdf5,
        box_surface_triangles,
        corresponding_segments_blocked,
        rigid_barrier_provider,
        segment_visibility,
        shepard_velocity,
        weighted_stratified_seeds,
    )
try:
    from scripts.protocol_metrics import mass_fraction_tv
    from scripts.w06_rotating_pour import body_positions, inside_aabb
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from protocol_metrics import mass_fraction_tv
    from w06_rotating_pour import body_positions, inside_aabb


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
REPORT = CAMPAIGN / "r3-g2-tracer-validation.json"
W06_REPORT = CAMPAIGN / "w06-rotating-pour.json"
W06_DATA = CAMPAIGN / "data" / "w06"
RELEASE_MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"
DP = 0.025


def adversarial_visibility_audit() -> dict:
    wall = box_surface_triangles([0.0, -1.0, -1.0], [0.0, 1.0, 1.0], sides=("xmin",))
    query = np.asarray([[-0.01, 0.0, 0.0]])
    samples = np.asarray([[-0.02, 0.0, 0.0], [0.01, 0.0, 0.0]])
    values = np.asarray([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]])
    legacy, _ = shepard_velocity(query, samples, values, neighbours=2, regularization=0.001)
    corrected, _, visible = shepard_velocity(
        query, samples, values, neighbours=2, regularization=0.001,
        barrier_triangles=wall, return_diagnostics=True,
    )

    # Two finite panels leave an actual aperture around y=0.  This catches an
    # over-conservative implementation that treats every wall plane as infinite.
    lower_panel = box_surface_triangles(
        [0.0, -1.0, -1.0], [0.0, -0.15, 1.0], sides=("xmin",))
    upper_panel = box_surface_triangles(
        [0.0, 0.15, -1.0], [0.0, 1.0, 1.0], sides=("xmin",))
    aperture = np.concatenate((lower_panel, upper_panel))
    through_aperture = bool(segment_visibility(
        [[-0.1, 0.0, 0.0]], [[0.1, 0.0, 0.0]], aperture)[0, 0])

    start = np.asarray([[-0.1, 0.5, 0.0], [-0.1, 0.0, 0.0]])
    end = np.asarray([[0.1, 0.5, 0.0], [0.1, 0.0, 0.0]])
    crossing = corresponding_segments_blocked(start, end, aperture)

    # Removing a separator must create visibility.  No t=0 connectivity label
    # is retained, so new physical contact remains possible.
    separated = bool(segment_visibility(
        [[-0.1, 0.5, 0.0]], [[0.1, 0.5, 0.0]], aperture)[0, 0])
    after_removal = bool(segment_visibility(
        [[-0.1, 0.5, 0.0]], [[0.1, 0.5, 0.0]], np.empty((0, 3, 3)))[0, 0])
    return {
        "wall_side_counterexample": {
            "legacy_interpolated_x_velocity_m_per_s": float(legacy[0, 0]),
            "wall_aware_interpolated_x_velocity_m_per_s": float(corrected[0, 0]),
            "visible_sample_count": int(visible[0]),
            "pass": bool(abs(corrected[0, 0]) < 1e-12 and legacy[0, 0] > 1.0),
        },
        "finite_aperture": {
            "line_of_sight_through_real_gap": through_aperture,
            "wall_crossing_rejected": bool(crossing[0]),
            "gap_crossing_retained": bool(not crossing[1]),
            "pass": bool(through_aperture and crossing[0] and not crossing[1]),
        },
        "new_contact": {
            "visible_with_separator": separated,
            "visible_after_separator_removed": after_removal,
            "pass": bool(not separated and after_removal),
        },
    }


def moving_wall_audit() -> dict:
    body = box_surface_triangles([0.0, -0.1, 0.0], [0.2, 0.1, 0.3], sides=("xmin",))
    transform0 = np.eye(4)
    transform1 = np.eye(4)
    transform1[0, 3] = 0.4
    midpoint = 0.5 * body + 0.5 * (body + np.asarray([0.4, 0.0, 0.0]))
    # Exercise the same provider contract used by the HDF5 advector without
    # relying on any particular DualSPHysics case.
    with h5py.File("/tmp/r3_g2_moving_wall.h5", "w", driver="core", backing_store=False) as h5:
        h5.create_dataset("control/body", data=np.asarray([transform0, transform1]))
        provider = rigid_barrier_provider("control/body", body)
        actual = provider(h5, 0, 1, 0.5)
    error = float(np.max(np.abs(actual - midpoint)))
    return {
        "intermediate_geometry": "linearly interpolated transformed wall vertices at every tracer substep",
        "midpoint_max_abs_error_m": error,
        "pass": error < 1e-12,
    }


def cadence_integration_audit() -> dict:
    # Integral of u(t)=t^2 from 0 to 1.  Linear interpolation between saved
    # velocities makes Heun exact for that interpolant, so extra tracer
    # substeps cannot repair information absent from a coarse saved cadence.
    truth = 1.0 / 3.0
    results = {}
    for saved_intervals in (2, 4, 10):
        time = np.linspace(0.0, 1.0, saved_intervals + 1)
        estimate = float(np.trapezoid(time * time, time))
        results[str(saved_intervals)] = {
            "saved_velocity_interval_s": 1.0 / saved_intervals,
            "tracer_substeps_per_saved_interval": [1, 2, 4],
            "position_for_each_substep_count_m": [estimate, estimate, estimate],
            "absolute_error_m": abs(estimate - truth),
        }
    return {
        "analytic_velocity": "u(t)=t^2 m/s",
        "exact_final_position_m": truth,
        "result": results,
        "conclusion": "saved velocity cadence and tracer integration substeps are independent controls",
        "pass": results["4"]["absolute_error_m"] < results["2"]["absolute_error_m"],
    }


def cup_barrier_provider(h5_path: Path, cup_width: float, receiver_x: float, receiver_y: float):
    cup = box_surface_triangles(
        [0.0, -0.15, 0.65], [cup_width, 0.15, 1.10],
        sides=("zmin", "xmin", "xmax", "ymin", "ymax"),
    )
    receiver = box_surface_triangles(
        [receiver_x, receiver_y - 0.30, 0.0],
        [receiver_x + 1.10, receiver_y + 0.30, 0.45],
        sides=("zmin", "xmin", "xmax", "ymin", "ymax"),
    )
    tray = box_surface_triangles(
        [-0.60, -0.55, -0.20], [2.0, 0.55, -0.10], sides=("zmax",),
    )
    with h5py.File(h5_path, "r") as h5:
        if "control/cup_world_from_body" not in h5:
            raise ValueError("rotating-cup transform is required for wall-aware tracing")
    return rigid_barrier_provider("control/cup_world_from_body", cup, np.concatenate((receiver, tray)))


def tracer_destination_fractions(trace: dict, seeds: dict, record: dict, h5_path: Path) -> dict:
    weights = seeds["mass_weight"]
    reliable = trace["reliable"]
    world = trace["position"][-1]
    with h5py.File(h5_path, "r") as h5:
        transform = h5["control/cup_world_from_body"][-1]
    cup = body_positions(world, transform)
    retained = reliable & inside_aabb(
        cup, [0.025, -0.145, 0.675], [record["cup_width"] - 0.025, 0.145, 1.075])
    captured = reliable & inside_aabb(
        world,
        [record["receiver_x"] + 0.025, record["receiver_y"] - 0.275, 0.025],
        [record["receiver_x"] + 1.075, record["receiver_y"] + 0.275, 0.425],
    )
    spilled = reliable & ~retained & ~captured & (world[:, 2] < -0.10)
    unclassified = reliable & ~retained & ~captured & ~spilled
    unavailable = ~reliable
    masks = (captured, retained, spilled, unclassified, unavailable)
    names = ("captured", "retained", "spilled_to_tray", "inflight_or_unclassified", "unavailable")
    total = float(weights.sum())
    weighted = {name: float(weights[mask].sum() / total) for name, mask in zip(names, masks)}
    unweighted = {name: float(mask.mean()) for name, mask in zip(names, masks)}
    return {
        "weighted_mass_fraction": weighted,
        "unweighted_count_fraction": unweighted,
        "mass_fraction_closure_error": abs(sum(weighted.values()) - 1.0),
    }


def reference_fractions(record: dict) -> dict:
    source = record["final_mass_fraction"]
    return {
        "captured": source["captured"],
        "retained": source["retained"],
        "spilled_to_tray": source["spilled_to_tray"],
        "inflight_or_unclassified": source["inflight_or_unclassified"],
        "unavailable": source["numerically_missing"],
    }


def release_sidecar_coverage(manifest_path: Path = RELEASE_MANIFEST) -> dict:
    """Report which released fluid cases have an existing linked sidecar.

    F6's body-only pilot is intentionally outside this count.  The result is
    descriptive: a sidecar supplies candidate finite geometry, not a released
    material-destination contract.
    """
    manifest_path = Path(manifest_path).resolve()
    release_root = manifest_path.parent
    payload = json.loads(manifest_path.read_text())
    fluid_records = [record for record in payload.get("cases", [])
                     if record.get("family") in {"F1", "F2", "F3"}]
    rows = []
    for record in fluid_records:
        relative = (record.get("geometry") or {}).get("boundary_sidecar")
        declared = isinstance(relative, str) and bool(relative)
        path = (release_root / relative).resolve() if declared else None
        contained = False
        if path is not None:
            try:
                path.relative_to(release_root)
                contained = True
            except ValueError:
                contained = False
        rows.append({
            "case_id": record.get("case_id"),
            "declared": declared,
            "path_within_release_root": contained,
            "exists": bool(path is not None and contained and path.is_file()),
        })
    existing = [row for row in rows if row["exists"]]
    return {
        "scope": "released F1/F2/F3 fluid cases",
        "case_count": len(rows),
        "declared_count": sum(row["declared"] for row in rows),
        "existing_count": len(existing),
        "all_cases_have_existing_sidecar": bool(rows) and len(existing) == len(rows),
        "cases": rows,
    }


def trace_actual(count: int, wall_aware: bool, h5_path: Path, record: dict) -> dict:
    seeds = weighted_stratified_seeds(h5_path, maximum=count)
    provider = cup_barrier_provider(
        h5_path, record["cup_width"], record["receiver_x"], record["receiver_y"],
    ) if wall_aware else None
    trace = advect_hdf5(
        h5_path, seeds["position"], neighbours=24, regularization=0.1 * DP,
        maximum_support_distance=1.75 * DP, substeps_per_interval=1,
        barrier_provider=provider,
    )
    destinations = tracer_destination_fractions(trace, seeds, record, h5_path)
    reference = reference_fractions(record)
    support = trace["nearest_support_distance"]
    visible = trace["minimum_visible_neighbours"]
    return {
        "tracer_count": count,
        "wall_aware": wall_aware,
        "represented_initial_mass_kg": seeds["represented_initial_mass"],
        "reliable_final_count": int(trace["reliable"].sum()),
        "reliable_final_fraction_by_count": float(trace["reliable"].mean()),
        "maximum_support_distance_m": float(np.nanmax(support)),
        "minimum_visible_particle_count": int(visible.min()) if wall_aware else None,
        "wall_crossing_rejections": int(trace["wall_crossing"].sum()),
        "destinations": destinations,
        "full_particle_reference_mass_fraction": reference,
        "mass_fraction_total_variation": mass_fraction_tv(
            reference, destinations["weighted_mass_fraction"]),
    }


def actual_pour_audit(counts: list[int]) -> dict:
    case_id = "W06_standard_slow_center"
    h5_path = W06_DATA / f"{case_id}.h5"
    report = json.loads(W06_REPORT.read_text())
    record = report["cases"][case_id]
    wall_aware = [trace_actual(count, True, h5_path, record) for count in counts]
    legacy_count = 32 if 32 in counts else counts[0]
    legacy = trace_actual(legacy_count, False, h5_path, record)
    return {
        "case_id": case_id,
        "fluid_spatial_resolution_m": DP,
        "saved_velocity_cadence_s": 0.01,
        "tracer_integration_substeps_per_saved_interval": 1,
        "tracer_counts": counts,
        "wall_geometry": "open-top moving cup plus fixed open-top receiver and tray surfaces",
        "legacy_no_wall_visibility": legacy,
        "wall_aware_count_sensitivity": wall_aware,
        "interpretation": "same-solver consistency only; not external physical validation",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", type=int, nargs="+", default=[16, 32, 64])
    parser.add_argument("--skip-actual", action="store_true")
    args = parser.parse_args()
    payload = {
        "schema_version": 1,
        "acceptance_scope": "R3 G2 material tracing gap closure",
        "adversarial_visibility": adversarial_visibility_audit(),
        "moving_wall": moving_wall_audit(),
        "cadence_vs_integration": cadence_integration_audit(),
        "actual_rotating_pour": None if args.skip_actual else actual_pour_audit(args.counts),
        "boundary_sidecar_coverage": release_sidecar_coverage(),
        "validation_claim": "numerical material-tracing consistency; no experimental ground-truth claim",
        "open_blockers": [
            "the current 12 F1/F2/F3 fluid cases have linked candidate sidecars, but future admitted cases (including F6) need the same geometry contract",
            "material destination specifications and open-face/rim semantics are not yet linked to the release manifest",
            "resolution and saved-cadence convergence must be repeated on the selected physical matrix",
            "small spill-tail accuracy needs more tracer-count evidence than this 16/32/64 development probe",
        ],
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
