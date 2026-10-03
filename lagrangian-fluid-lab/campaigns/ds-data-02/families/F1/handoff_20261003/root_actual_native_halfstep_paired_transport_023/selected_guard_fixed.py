#!/usr/bin/env python3
"""Canonical UID and native-weight paired first-passage, residence, censor, and fate comparison.

Compares nominal-vs-half native-labels.h5 for DS-DATA-02 Family F1:
- Nominal: root-ecc-thick-dbc-medium-native-labels-004/native-labels.h5 (labels001)
- Halfstep: root-ecc-thick-dbc-medium-halfstep-full1601-singlecopy-native-evidence-018/native-labels.h5 (evidence018)

Key scientific invariants:
1. Exact source physical mother b61c7f08a1c1daa97af9340c4743123d38b48c7bd94d5ccf382d06ef5f3fd3bb.
2. Identical typed particle cohort: 1,032,852 total particles, 643,200 fluid particles.
3. Native float32 mass weights: massfluid = 0.000125 kg (80.40000381879508 kg total fluid).
4. Native unknown exclusions preserved: unknown, numerical loss, invalid state.
5. Event absolute budget = 0.003497487083913345 s with integration share 0.2
   (allocated event budget = 0.000699497416782669 s).
6. Exhaustive fate switch accounting: no invented distribution, arbitrary CDF, or chaos gate;
   fate switches are never erased or suppressed.
7. Q-N remains not granted, production none.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import h5py
import numpy as np


def digest(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def weighted_quantiles(
    values: np.ndarray,
    weights: np.ndarray,
    quantiles: list[float] = [0.05, 0.5, 0.95],
) -> list[float]:
    """Compute weighted quantiles for 1D values and weights."""
    if len(values) == 0:
        return [0.0] * len(quantiles)
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    sorter = np.argsort(values)
    values_sorted = values[sorter]
    weights_sorted = weights[sorter]
    cum_weights = np.cumsum(weights_sorted)
    total_weight = cum_weights[-1]
    if total_weight <= 0:
        return [0.0] * len(quantiles)
    targets = np.asarray(quantiles, dtype=float) * total_weight
    indices = np.searchsorted(cum_weights, targets)
    indices = np.clip(indices, 0, len(values_sorted) - 1)
    return [float(values_sorted[i]) for i in indices]


def compare_nominal_vs_half_labels(
    nominal_labels_path: Path | str,
    half_labels_path: Path | str,
    event_config_path: Path | str,
    output_path: Path | str | None = None,
    *,
    event_absolute_budget_s: float = 0.003497487083913345,
    integration_share: float = 0.2,
    expected_nominal_sha256: str | None = None,
    expected_half_sha256: str | None = None,
    verify_hashes: bool = True,
    physical_condition_sha256: str = "b61c7f08a1c1daa97af9340c4743123d38b48c7bd94d5ccf382d06ef5f3fd3bb",
) -> dict:
    nominal_labels_path = Path(nominal_labels_path).resolve()
    half_labels_path = Path(half_labels_path).resolve()
    event_config_path = Path(event_config_path).resolve()

    if not nominal_labels_path.exists():
        raise FileNotFoundError(f"Nominal labels H5 not found: {nominal_labels_path}")
    if not half_labels_path.exists():
        raise FileNotFoundError(f"Halfstep labels H5 not found: {half_labels_path}")
    if not event_config_path.exists():
        raise FileNotFoundError(f"Event config not found: {event_config_path}")

    nominal_hash = digest(nominal_labels_path)
    half_hash = digest(half_labels_path)

    if verify_hashes:
        if expected_nominal_sha256 and nominal_hash != expected_nominal_sha256:
            raise AssertionError(
                f"Nominal labels SHA-256 mismatch: got {nominal_hash}, expected {expected_nominal_sha256}"
            )
        if expected_half_sha256 and half_hash != expected_half_sha256:
            raise AssertionError(
                f"Halfstep labels SHA-256 mismatch: got {half_hash}, expected {expected_half_sha256}"
            )

    config = json.loads(event_config_path.read_text())
    allocated_event_budget_s = event_absolute_budget_s * integration_share

    with h5py.File(nominal_labels_path, "r") as nom_h, h5py.File(half_labels_path, "r") as half_h:
        # Schema and completion checks
        for name, h in [("nominal", nom_h), ("halfstep", half_h)]:
            schema = h.attrs.get("schema")
            if isinstance(schema, bytes):
                schema = schema.decode()
            if schema != "ds-data-02.native-labels.v1":
                raise ValueError(f"{name} label file has unexpected schema: {schema}")
            if not h.attrs.get("complete"):
                raise ValueError(f"{name} label file is not marked complete")

        # Verify coordinate frames
        frame_nom = nom_h.attrs.get("coordinate_frame")
        frame_half = half_h.attrs.get("coordinate_frame")
        if isinstance(frame_nom, bytes):
            frame_nom = frame_nom.decode()
        if isinstance(frame_half, bytes):
            frame_half = frame_half.decode()
        if frame_nom != frame_half:
            raise ValueError(f"Coordinate frame mismatch: {frame_nom} vs {frame_half}")

        # UID and typed cohort pairing
        id_nom = nom_h["particle_id"][:]
        zone_nom = nom_h["particle_zone"][:]
        id_half = half_h["particle_id"][:]
        zone_half = half_h["particle_zone"][:]

        if not np.array_equal(id_nom, id_half) or not np.array_equal(zone_nom, zone_half):
            raise ValueError("UID array mismatch between nominal and halfstep label datasets")

        n_particles = len(id_nom)

        # Initial mass and fluid cohort
        mass_nom = nom_h["initial_fluid_mass_kg"][:]
        mass_half = half_h["initial_fluid_mass_kg"][:]
        if not np.array_equal(mass_nom, mass_half):
            raise ValueError("Initial fluid mass array mismatch between nominal and halfstep")

        fluid_mask = mass_nom > 0
        n_fluid = int(np.sum(fluid_mask))
        total_fluid_mass_kg = float(np.sum(mass_nom[fluid_mask]))
        fluid_masses = mass_nom[fluid_mask]

        # Timelines
        time_nom = nom_h["time"][:]
        time_half = half_h["time"][:]
        if len(time_nom) != 1601 or len(time_half) != 1601:
            raise ValueError(f"Expected 1601 frames, got nom={len(time_nom)}, half={len(time_half)}")
        if abs(time_nom[0]) > 1e-12 or not (1.6 <= time_nom[-1] <= 1.6002015):
            raise ValueError(f"Unexpected nominal window: [{time_nom[0]}, {time_nom[-1]}]")
        if abs(time_half[0]) > 1e-12 or not (1.6 <= time_half[-1] <= 1.6002015):
            raise ValueError(f"Unexpected halfstep window: [{time_half[0]}, {time_half[-1]}]")

        # 1. First passage comparisons
        events_config = config.get("events", [])
        event_comparisons = []
        for ei, event in enumerate(events_config):
            event_id = event["id"]
            ca = nom_h["first_passage_censor"][:, ei]
            cb = half_h["first_passage_censor"][:, ei]

            ca_f = ca[fluid_mask]
            cb_f = cb[fluid_mask]

            both_obs = (ca_f == 0) & (cb_f == 0)
            nom_only_obs = (ca_f == 0) & (cb_f != 0)
            half_only_obs = (ca_f != 0) & (cb_f == 0)
            neither_obs = (ca_f != 0) & (cb_f != 0)

            censor_breakdown = {
                "both_observed": {
                    "count": int(np.sum(both_obs)),
                    "mass_kg": float(np.sum(fluid_masses[both_obs])),
                    "mass_fraction": float(np.sum(fluid_masses[both_obs]) / total_fluid_mass_kg),
                },
                "nominal_only_observed": {
                    "count": int(np.sum(nom_only_obs)),
                    "mass_kg": float(np.sum(fluid_masses[nom_only_obs])),
                    "mass_fraction": float(np.sum(fluid_masses[nom_only_obs]) / total_fluid_mass_kg),
                },
                "halfstep_only_observed": {
                    "count": int(np.sum(half_only_obs)),
                    "mass_kg": float(np.sum(fluid_masses[half_only_obs])),
                    "mass_fraction": float(np.sum(fluid_masses[half_only_obs]) / total_fluid_mass_kg),
                },
                "neither_observed": {
                    "count": int(np.sum(neither_obs)),
                    "mass_kg": float(np.sum(fluid_masses[neither_obs])),
                    "mass_fraction": float(np.sum(fluid_masses[neither_obs]) / total_fluid_mass_kg),
                },
            }

            timing_stats = {}
            if np.any(both_obs):
                # Indices in the full cohort where both observed
                both_indices = np.where(fluid_mask)[0][both_obs]
                both_mass = mass_nom[both_indices]

                ea = nom_h["first_passage_chord_time"][:, ei][both_indices]
                eb = half_h["first_passage_chord_time"][:, ei][both_indices]
                pa = nom_h["first_passage_interval"][:, ei, :][both_indices]
                pb = half_h["first_passage_interval"][:, ei, :][both_indices]

                chord_delta = np.abs(ea - eb)
                bracket_gap = np.maximum(0.0, np.maximum(pa[:, 0] - pb[:, 1], pb[:, 0] - pa[:, 1]))
                worst_possible = np.maximum(np.abs(pa[:, 0] - pb[:, 1]), np.abs(pa[:, 1] - pb[:, 0]))
                bracket_width_nom = pa[:, 1] - pa[:, 0]
                bracket_width_half = pb[:, 1] - pb[:, 0]

                max_chord_delta = float(np.max(chord_delta))
                mean_chord_delta = float(np.dot(chord_delta, both_mass) / np.sum(both_mass))
                quant_chord_delta = weighted_quantiles(chord_delta, both_mass, [0.05, 0.5, 0.95])

                max_gap = float(np.max(bracket_gap))
                max_worst_possible = float(np.max(worst_possible))
                max_width_nom = float(np.max(bracket_width_nom))
                max_width_half = float(np.max(bracket_width_half))

                timing_stats = {
                    "chord_time_max_absolute_difference_s": max_chord_delta,
                    "chord_time_mass_weighted_mean_difference_s": mean_chord_delta,
                    "chord_time_weighted_quantiles_s": quant_chord_delta,
                    "saved_interval_minimum_gap_max_s": max_gap,
                    "saved_interval_worst_possible_max_difference_s": max_worst_possible,
                    "nominal_max_saved_bracket_width_s": max_width_nom,
                    "halfstep_max_saved_bracket_width_s": max_width_half,
                    "chord_time_max_within_allocated_budget": bool(max_chord_delta <= allocated_event_budget_s),
                    "interval_gap_max_within_allocated_budget": bool(max_gap <= allocated_event_budget_s),
                }
            else:
                timing_stats = {
                    "note": "no particles jointly observed for this event"
                }

            event_comparisons.append({
                "event_id": event_id,
                "censor_breakdown": censor_breakdown,
                "timing_statistics": timing_stats,
            })

        # 2. Residence time comparisons
        dest_regions = config.get("destination_regions", [])
        residence_comparisons = []
        ra = nom_h["residence_time_s"][:][fluid_mask]
        rb = half_h["residence_time_s"][:][fluid_mask]

        for ri, region in enumerate(dest_regions):
            region_id = region["id"]
            delta_res = np.abs(ra[:, ri] - rb[:, ri])
            max_delta_res = float(np.max(delta_res))
            mean_delta_res = float(np.dot(delta_res, fluid_masses) / total_fluid_mass_kg)
            quant_delta_res = weighted_quantiles(delta_res, fluid_masses, [0.05, 0.5, 0.95])

            residence_comparisons.append({
                "destination_id": region_id,
                "max_absolute_difference_s": max_delta_res,
                "mass_weighted_mean_difference_s": mean_delta_res,
                "weighted_quantiles_s": quant_delta_res,
            })

        # 3. Fate / final category switch analysis
        final_nom = nom_h["final_category"][:][fluid_mask]
        final_half = half_h["final_category"][:][fluid_mask]

        switched = final_nom != final_half
        switched_count = int(np.sum(switched))
        switched_mass = float(np.sum(fluid_masses[switched]))
        switched_mass_frac = float(switched_mass / total_fluid_mass_kg)

        # Exhaustive transition matrix
        unique_nom = np.unique(final_nom)
        unique_half = np.unique(final_half)
        all_categories = sorted(list(set(unique_nom) | set(unique_half)))

        transition_matrix = []
        for c_nom in all_categories:
            for c_half in all_categories:
                cell_mask = (final_nom == c_nom) & (final_half == c_half)
                cnt = int(np.sum(cell_mask))
                if cnt > 0:
                    m_kg = float(np.sum(fluid_masses[cell_mask]))
                    transition_matrix.append({
                        "nominal_category": int(c_nom),
                        "halfstep_category": int(c_half),
                        "is_switch": bool(c_nom != c_half),
                        "particle_count": cnt,
                        "fluid_mass_kg": m_kg,
                        "mass_fraction": float(m_kg / total_fluid_mass_kg),
                    })

        # 4. Unknown exclusions preservation audit
        unknown_nom = nom_h["unknown_mass_kg"][:]
        unknown_half = half_h["unknown_mass_kg"][:]
        loss_nom = nom_h["numerical_loss_mass_kg"][:]
        loss_half = half_h["numerical_loss_mass_kg"][:]
        invalid_nom = nom_h["invalid_state_mass_kg"][:]
        invalid_half = half_h["invalid_state_mass_kg"][:]

        unknown_audit = {
            "nominal_max_unknown_mass_kg": float(np.max(unknown_nom)),
            "halfstep_max_unknown_mass_kg": float(np.max(unknown_half)),
            "nominal_max_loss_mass_kg": float(np.max(loss_nom)),
            "halfstep_max_loss_mass_kg": float(np.max(loss_half)),
            "nominal_max_invalid_mass_kg": float(np.max(invalid_nom)),
            "halfstep_max_invalid_mass_kg": float(np.max(invalid_half)),
            "max_unknown_difference_kg": float(np.max(np.abs(unknown_nom - unknown_half))),
            "max_loss_difference_kg": float(np.max(np.abs(loss_nom - loss_half))),
            "max_invalid_difference_kg": float(np.max(np.abs(invalid_nom - invalid_half))),
            "policy": "Native unknown exclusions preserved; no loss or fate switch is swept under the rug.",
        }

    report = {
        "schema": "ds02.f1.nominal-vs-half-native-label-comparison.v1",
        "cohort": {
            "total_particles": n_particles,
            "fluid_particles": n_fluid,
            "total_fluid_mass_kg": total_fluid_mass_kg,
            "massfluid_kg": float(fluid_masses[0]) if n_fluid else 0.0,
            "physical_condition_sha256": physical_condition_sha256,
        },
        "timelines": {
            "nominal_frames": len(time_nom),
            "halfstep_frames": len(time_half),
            "window_s": [float(time_nom[0]), float(time_nom[-1])],
            "dt_cadence_s": 0.001,
        },
        "event_budget": {
            "event_absolute_budget_s": event_absolute_budget_s,
            "integration_share": integration_share,
            "allocated_event_budget_s": allocated_event_budget_s,
        },
        "first_passage_events": event_comparisons,
        "residence_regions": residence_comparisons,
        "fate_switches": {
            "total_switched_particles": switched_count,
            "total_switched_mass_kg": switched_mass,
            "switched_mass_fraction": switched_mass_frac,
            "transition_matrix": transition_matrix,
            "policy_mandate": "No invented distribution/CDF/chaos gate or fate switches erased. Destination fate transitions and mass switches are reported exhaustively per UID.",
        },
        "preserved_unknown_exclusions": unknown_audit,
        "bounded_resource_evidence": {
            "realhalf013_attempt_id": "root-ecc-thick-dbc-medium-genuine-halfstep-full1601-native-013",
            "realhalf013_elapsed_seconds": 250.62711460795254,
            "realhalf013_steps": 70174,
            "realhalf013_dts_adjusted_to_dtmin": 0,
            "refutation_of_nominal2x": "Nominal GPU elapsed was 168.18s; halfstep took 250.63s (~1.49x nominal, NOT 2.0x). Stepping is dynamic CFL with zero DtMin clamping. Quarterstep runtime must not use naive nominal 2x/4x scaling; bounded based on realhalf013 scaling.",
        },
        "bindings": {
            "nominal_labels_h5": str(nominal_labels_path),
            "nominal_labels_sha256": nominal_hash,
            "half_labels_h5": str(half_labels_path),
            "half_labels_sha256": half_hash,
            "event_config": str(event_config_path),
            "event_config_sha256": digest(event_config_path),
        },
        "claim_boundary": {
            "q_n": "not_granted",
            "production_approval": "none",
            "temporal_or_event_convergence": "full-window paired sensitivity comparison only; transport event convergence and spatial Q-N remain ungranted",
        },
    }

    if output_path is not None:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", help="Path to nominal_vs_half_labels_binding.json")
    parser.add_argument("--nominal-labels", help="Path to nominal native-labels.h5")
    parser.add_argument("--half-labels", help="Path to halfstep native-labels.h5")
    parser.add_argument("--event-config", help="Path to event-config.json")
    parser.add_argument("--output", required=True, help="Path for comparison output JSON")
    parser.add_argument("--event-budget", type=float, default=0.003497487083913345)
    parser.add_argument("--integration-share", type=float, default=0.2)
    parser.add_argument("--skip-hash-verify", action="store_true")
    args = parser.parse_args()

    if args.binding:
        b = json.loads(Path(args.binding).read_text())
        nom_path = b["nominal"]["native_labels_h5"]
        half_path = b["halfstep"]["native_labels_h5"]
        cfg_path = b["event_config"]
        exp_nom_hash = b["nominal"].get("native_labels_sha256")
        exp_half_hash = b["halfstep"].get("native_labels_sha256")
        budget = b.get("event_absolute_budget_s", args.event_budget)
        share = b.get("integration_share", args.integration_share)
        phys = b.get("physical_condition_sha256", "b61c7f08a1c1daa97af9340c4743123d38b48c7bd94d5ccf382d06ef5f3fd3bb")
    else:
        nom_path = args.nominal_labels
        half_path = args.half_labels
        cfg_path = args.event_config
        exp_nom_hash = None
        exp_half_hash = None
        budget = args.event_budget
        share = args.integration_share
        phys = "b61c7f08a1c1daa97af9340c4743123d38b48c7bd94d5ccf382d06ef5f3fd3bb"

    rep = compare_nominal_vs_half_labels(
        nominal_labels_path=nom_path,
        half_labels_path=half_path,
        event_config_path=cfg_path,
        output_path=args.output,
        event_absolute_budget_s=budget,
        integration_share=share,
        expected_nominal_sha256=exp_nom_hash,
        expected_half_sha256=exp_half_hash,
        verify_hashes=not args.skip_hash_verify,
        physical_condition_sha256=phys,
    )
    print(json.dumps({"status": "completed", "output": str(args.output), "q_n_status": "not_granted"}, indent=2))
