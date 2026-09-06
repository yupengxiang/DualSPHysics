#!/usr/bin/env python3
"""Build the W07 six-family mechanism map and constrained candidate designs.

This stage deliberately creates *design cards*, not solver jobs.  The cards make
the intended physical axes reviewable before any formal data production begins.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


FAMILY_SPECS: dict[str, dict[str, Any]] = {
    "F1": {
        "name": "collapse_and_obstacle_transport",
        "continuous": {
            "wet_bed_ratio": (0.0, 0.35),
            "blockage_ratio": (0.0, 0.55),
            "obstacle_eccentricity": (-0.45, 0.45),
            "release_aspect_ratio": (0.5, 2.0),
        },
        "categorical": {"obstacle_topology": ["none", "single", "twin", "porous_proxy"]},
        "negative_control": {"wet_bed_ratio": 0.0, "blockage_ratio": 0.0, "obstacle_topology": "none"},
        "history_task": "source_depth_to_obstacle_branch_and_terminal_basin",
    },
    "F2": {
        "name": "rotating_cup_pouring",
        "continuous": {
            "fill_fraction": (0.30, 0.75),
            "rotation_duration_s": (0.55, 1.45),
            "final_angle_deg": (95.0, 135.0),
            "receiver_offset_over_mouth": (-0.75, 0.75),
            "receiver_distance_over_mouth": (0.6, 2.2),
        },
        "categorical": {"mouth_topology": ["straight", "rounded_lip", "spout"]},
        "negative_control": {"receiver_distance_over_mouth": 2.2, "receiver_offset_over_mouth": 0.75},
        "history_task": "initial_layer_to_retained_captured_spilled_or_returned",
    },
    "F3": {
        "name": "forced_sloshing_and_baffles",
        "continuous": {
            "fill_fraction": (0.25, 0.75),
            "amplitude_over_length": (0.005, 0.08),
            "forcing_frequency_ratio": (0.55, 1.55),
            "baffle_height_over_depth": (0.0, 0.8),
        },
        "categorical": {"baffle_topology": ["none", "center", "offset", "perforated_proxy"]},
        "negative_control": {"amplitude_over_length": 0.005, "baffle_height_over_depth": 0.0, "baffle_topology": "none"},
        "history_task": "initial_compartment_to_crossing_count_residence_and_wall_impact",
    },
    "F4": {
        "name": "colliding_and_merging_streams",
        "continuous": {
            "impact_froude": (0.5, 4.0),
            "incidence_angle_deg": (0.0, 75.0),
            "velocity_ratio": (0.35, 1.0),
            "stream_size_ratio": (0.45, 1.0),
        },
        "categorical": {"target_state": ["dry", "shallow_pool", "counter_stream"]},
        "negative_control": {"impact_froude": 0.5, "incidence_angle_deg": 0.0, "target_state": "shallow_pool"},
        "history_task": "source_stream_to_mixing_interface_ejection_and_terminal_region",
    },
    "F5": {
        "name": "overtopping_runup_and_return",
        "continuous": {
            "wave_height_over_depth": (0.05, 0.45),
            "relative_period": (0.65, 1.55),
            "beach_slope": (0.05, 0.35),
            "freeboard_over_depth": (-0.10, 0.45),
        },
        "categorical": {"crest_topology": ["smooth", "weir", "notched_weir"]},
        "negative_control": {"wave_height_over_depth": 0.05, "freeboard_over_depth": 0.45, "crest_topology": "weir"},
        "history_task": "initial_water_band_to_overtop_return_or_retention_with_first_passage",
    },
    "F6": {
        "name": "fluid_rigid_body_interaction",
        "continuous": {
            "body_density_ratio": (0.25, 1.35),
            "entry_froude": (0.0, 3.0),
            "body_aspect_ratio": (0.5, 2.0),
            "initial_pitch_deg": (-25.0, 25.0),
        },
        "categorical": {"body_configuration": ["single_free", "single_heave_only", "twin_free"]},
        "negative_control": {"body_density_ratio": 1.0, "entry_froude": 0.0, "initial_pitch_deg": 0.0},
        "history_task": "fluid_origin_to_body_contact_impulse_wake_residence_and_body_response",
    },
}


OBSERVED_EVIDENCE = {
    "F1": {
        "probe_mechanisms": ["dam_break_plain", "center_obstacle", "twin_obstacle", "opposing_columns"],
        "external_anchor": "SPHERIC Test 02 at dp=0.04/0.03/0.02 m",
        "evidence": "H2/H4 surface RMSE converged near 0.04 m; H1 and pressure errors were non-monotonic.",
        "disposition": "retain_development_macro_only",
        "blocking_gap": "impact pressure and near-gate H1 are not production validated",
    },
    "F2": {
        "probe_mechanisms": ["rotating_cup_12_case_matrix"],
        "external_anchor": None,
        "evidence": "Nine partial-capture and three complete-miss cases; five near-receiver cases have zero numerical loss.",
        "disposition": "retain_five_closed_domain_candidates",
        "blocking_gap": "cup-lip topology, resolution sensitivity, and external observation are absent",
    },
    "F3": {
        "probe_mechanisms": ["impulse_slosh", "baffled_slosh", "transverse_slosh"],
        "external_anchor": "SPHERIC Test 10 at dp=0.008/0.006/0.004 m",
        "evidence": "Fine resolution recovers the first pressure-peak magnitude (3.045 versus 3.683 kPa), but timing remains 45 ms late.",
        "disposition": "retain_fine_event_anchor",
        "blocking_gap": "coarse and medium impact pressure are unresolved",
    },
    "F4": {
        "probe_mechanisms": ["head_on_columns", "oblique_columns", "drop_onto_pool"],
        "external_anchor": None,
        "evidence": "Three qualitative topology probes completed with retained identities.",
        "disposition": "provisional_mechanism_only",
        "blocking_gap": "no external validation or resolution study",
    },
    "F5": {
        "probe_mechanisms": ["low_weir", "notched_weir", "wet_bed_overtop", "solitary_wave", "wave_runup"],
        "external_anchor": None,
        "evidence": "The coarse wave-runup probe failed catastrophically; a refined probe is exploratory only.",
        "disposition": "provisional_high_risk",
        "blocking_gap": "run-up/overtopping observation anchor and stable resolution envelope are absent",
    },
    "F6": {
        "probe_mechanisms": ["floating_box", "heavy_box_entry", "twin_floaters", "2d_floating_cylinder"],
        "external_anchor": "Fekken 2-D floating-cylinder displacement at dp=0.10/0.075/0.05 m",
        "evidence": "Displacement RMSE improved from 0.353 to 0.0765 m with refinement.",
        "disposition": "retain_limited_2d_surrogate",
        "blocking_gap": "SPHERIC Test 14 custom 3-D moving-body case remains unresolved",
    },
}


def latin_hypercube(n: int, dimensions: int, seed: int) -> np.ndarray:
    """Small deterministic LHS implementation without an extra dependency."""
    rng = np.random.default_rng(seed)
    result = np.empty((n, dimensions), dtype=np.float64)
    for axis in range(dimensions):
        result[:, axis] = (rng.permutation(n) + rng.random(n)) / n
    return result


def _rounded(value: float) -> float:
    return float(f"{value:.6g}")


def build_family_cards(family: str, n: int = 24) -> list[dict[str, Any]]:
    spec = FAMILY_SPECS[family]
    axes = list(spec["continuous"])
    lhs = latin_hypercube(n, len(axes), seed=20260907 + int(family[1:]))
    cards: list[dict[str, Any]] = []
    categories = spec["categorical"]
    cat_name, cat_values = next(iter(categories.items()))
    for i in range(n):
        physics = {}
        for j, axis in enumerate(axes):
            low, high = spec["continuous"][axis]
            physics[axis] = _rounded(low + lhs[i, j] * (high - low))
        physics[cat_name] = cat_values[i % len(cat_values)]
        role = "space_fill"
        if i == 0:
            physics.update(spec["negative_control"])
            role = "negative_control"
        elif i in (1, 2):
            role = "boundary_probe"
        cards.append(
            {
                "case_id": f"W07_{family}_{i:02d}",
                "family": family,
                "family_name": spec["name"],
                "candidate_index": i,
                "design_role": role,
                "lineage_group_id": f"W07_{family}_mechanism_screen",
                "physics": physics,
                "history_task": spec["history_task"],
                "numerics": {
                    "particle_spacing_m": None,
                    "boundary_formulation": None,
                    "note": "must be frozen only after family-specific resolution gate",
                },
                "observation": {
                    "frame_interval_s": None,
                    "event_oversampling": None,
                    "note": "must be frozen from event-time and aliasing study",
                },
                "paired_background_id": None,
                "execution_status": "planned_not_run",
            }
        )
    return cards


def assert_design(cards: list[dict[str, Any]]) -> None:
    assert len(cards) == 144
    assert len({card["case_id"] for card in cards}) == len(cards)
    for family, spec in FAMILY_SPECS.items():
        family_cards = [card for card in cards if card["family"] == family]
        assert len(family_cards) == 24
        assert sum(card["design_role"] == "negative_control" for card in family_cards) == 1
        for card in family_cards:
            for axis, (low, high) in spec["continuous"].items():
                assert low <= card["physics"][axis] <= high


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    args = parser.parse_args()
    campaign_dir = args.campaign_dir.resolve()
    cards = [card for family in FAMILY_SPECS for card in build_family_cards(family)]
    assert_design(cards)

    design = {
        "schema_version": 1,
        "campaign_id": "v0.1-candidate",
        "purpose": "reviewable constrained candidates; not an execution manifest",
        "generator": {"algorithm": "deterministic_stratified_latin_hypercube", "seed_base": 20260907},
        "candidate_count": len(cards),
        "candidates_per_family": 24,
        "cards": cards,
    }
    report = {
        "schema_version": 1,
        "scope": "W07 six-family mechanism screening; no formal production",
        "source_evidence": [
            "w01-streaming-audits.json",
            "w01-quality-strict.json",
            "w04-calibration.json",
            "w05-validation-anchors.json",
            "w06-rotating-pour.json",
        ],
        "observed_family_map": OBSERVED_EVIDENCE,
        "candidate_design": {
            "total": len(cards),
            "per_family": 24,
            "execution_status": "planned_not_run",
            "formal_production_authorized": False,
        },
        "screening_decision": {
            "retain": ["F1", "F2", "F3", "F6"],
            "provisional": ["F4", "F5"],
            "release_ready": [],
            "additional_w07_gpu_runs": 0,
            "reason": "Current gaps are validation, resolution, observation cadence, and protocol gaps; more coarse visual probes would not close them.",
        },
        "next_gate": "W08 must convert selected axes into explicit train/interpolation/extrapolation groups without authorizing the 144-card matrix.",
    }

    cases_dir = campaign_dir / "cases" / "w07"
    cases_dir.mkdir(parents=True, exist_ok=True)
    (cases_dir / "candidate-designs.json").write_text(json.dumps(design, indent=2) + "\n")
    (campaign_dir / "w07-mechanism-screen.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
