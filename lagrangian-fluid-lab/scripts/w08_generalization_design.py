#!/usr/bin/env python3
"""Generate causal single-axis and two-axis generalization studies for W08."""

from __future__ import annotations

import argparse
import hashlib
import json
from itertools import product
from pathlib import Path
from typing import Any

try:  # package import under pytest
    from scripts.w07_mechanism_screen import FAMILY_SPECS
    from scripts.protocol_metrics import validate_split_lineage
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from w07_mechanism_screen import FAMILY_SPECS
    from protocol_metrics import validate_split_lineage


STUDIES = {
    "F1": {
        "baseline_category": {"obstacle_topology": "single"},
        "single_axes": ["wet_bed_ratio", "blockage_ratio"],
        "joint_axes": ["wet_bed_ratio", "blockage_ratio"],
        "topology_holdout": "twin",
    },
    "F2": {
        "baseline_category": {"mouth_topology": "straight"},
        "single_axes": ["rotation_duration_s", "receiver_offset_over_mouth"],
        "joint_axes": ["receiver_distance_over_mouth", "receiver_offset_over_mouth"],
        "topology_holdout": "spout",
    },
    "F3": {
        "baseline_category": {"baffle_topology": "center"},
        "single_axes": ["forcing_frequency_ratio", "baffle_height_over_depth"],
        "joint_axes": ["amplitude_over_length", "forcing_frequency_ratio"],
        "topology_holdout": "perforated_proxy",
    },
    "F6": {
        "baseline_category": {"body_configuration": "single_free"},
        "single_axes": ["body_density_ratio", "entry_froude"],
        "joint_axes": ["body_density_ratio", "entry_froude"],
        "topology_holdout": "twin_free",
    },
}

SINGLE_LEVELS = {
    "train": [0.20, 0.35, 0.50, 0.65, 0.80],
    "interpolation": [0.275, 0.425, 0.575, 0.725],
    "extrapolation": [0.05, 0.95],
}


# Topology holdouts are kept in a separate namespace from the 204 continuous
# intervention cards.  This prevents a materialized topology case from being
# mistaken for one of the continuous-axis execution units while still giving
# G3 a declared W08 card to link to concrete solver evidence.
TOPOLOGY_HOLDOUT_PHYSICS = {
    "wet_bed_ratio": 0.0,
    "blockage_ratio": 0.25,
    "obstacle_eccentricity": 0.0,
    "release_aspect_ratio": 0.73913,
    "obstacle_topology": "twin",
    "geometry_variant": "staggered_0p09x0p10_obstacles",
}


def topology_holdout_cards() -> list[dict[str, Any]]:
    """Return explicit topology declarations outside the continuous card set."""
    family = "F1"
    physics = dict(TOPOLOGY_HOLDOUT_PHYSICS)
    sig = signature(family, physics)
    return [{
        "card_id": "W08_F1_topology_twin_00",
        "family": family,
        "study_id": "W08_F1_topology_holdout",
        "paired_background_id": "background_F1_topology_holdout_staggered_v1",
        "physical_case_id": f"physical_W08_F1_topology_twin_{sig}",
        "lineage_group_id": f"lineage_W08_F1_topology_twin_{sig}",
        "split": "topology_extrapolation",
        "physics": physics,
        "normalized_intervention": {"obstacle_topology": "twin"},
        "simulation_signature": sig,
        "execution_unit_id": f"sim_W08_F1_topology_twin_{sig}",
        "execution_status": "planned_not_run",
        "formal_production_authorized": False,
        "materialization_case_id": "W08_F1_topology_twin_obstacle_00",
        "definition": (
            "campaigns/v0.1-candidate/cases/w08/topology/F1_twin_obstacle/"
            "W08_F1_topology_twin_obstacle_Def.xml"
        ),
        "provenance_status": "declared_independent_geometry",
    }]


def scale(family: str, axis: str, unit_value: float) -> float:
    low, high = FAMILY_SPECS[family]["continuous"][axis]
    return float(f"{low + unit_value * (high - low):.6g}")


def baseline(family: str) -> dict[str, Any]:
    physics = {
        axis: scale(family, axis, 0.5)
        for axis in FAMILY_SPECS[family]["continuous"]
    }
    physics.update(STUDIES[family]["baseline_category"])
    return physics


def signature(family: str, physics: dict[str, Any]) -> str:
    payload = json.dumps({"family": family, "physics": physics}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def paired_background_id(family: str) -> str:
    """Identify the fixed baseline context used by a family's interventions.

    A background is deliberately shared by the family's studies and can
    therefore occur in several splits.  It is not a physical case and must
    not be used as the split key.
    """
    return f"background_{family}_{signature(family, baseline(family))}"


def make_card(
    family: str,
    study: str,
    ordinal: int,
    split: str,
    physics: dict[str, Any],
    normalized_intervention: dict[str, float],
) -> dict[str, Any]:
    sig = signature(family, physics)
    physical_case_id = f"physical_{family}_{sig}"
    lineage_group_id = f"lineage_{physical_case_id}"
    return {
        "card_id": f"W08_{family}_{study}_{ordinal:02d}",
        "family": family,
        "study_id": f"W08_{family}_{study}",
        "paired_background_id": paired_background_id(family),
        "physical_case_id": physical_case_id,
        "lineage_group_id": lineage_group_id,
        "split": split,
        "physics": physics,
        "normalized_intervention": normalized_intervention,
        "simulation_signature": sig,
        "execution_unit_id": f"sim_{family}_{sig}",
        "execution_status": "planned_not_run",
        "formal_production_authorized": False,
    }


def single_axis_cards(family: str, axis: str) -> list[dict[str, Any]]:
    cards = []
    ordinal = 0
    for split, levels in SINGLE_LEVELS.items():
        for level in levels:
            physics = baseline(family)
            physics[axis] = scale(family, axis, level)
            cards.append(make_card(family, f"single_{axis}", ordinal, split, physics, {axis: level}))
            ordinal += 1
    return cards


def joint_axis_cards(family: str, axes: list[str]) -> list[dict[str, Any]]:
    axis_a, axis_b = axes
    points: list[tuple[str, float, float]] = []
    points += [("train", a, b) for a, b in product([0.3, 0.5, 0.7], repeat=2)]
    points += [("interpolation", a, b) for a, b in product([0.4, 0.6], repeat=2)]
    points += [("single_axis_extrapolation", a, b) for a, b in product([0.1, 0.9], [0.3, 0.5, 0.7])]
    points += [("single_axis_extrapolation", a, b) for a, b in product([0.3, 0.5, 0.7], [0.1, 0.9])]
    points += [("joint_extrapolation", a, b) for a, b in product([0.1, 0.9], repeat=2)]
    cards = []
    for ordinal, (split, value_a, value_b) in enumerate(points):
        physics = baseline(family)
        physics[axis_a] = scale(family, axis_a, value_a)
        physics[axis_b] = scale(family, axis_b, value_b)
        cards.append(
            make_card(
                family,
                f"joint_{axis_a}__{axis_b}",
                ordinal,
                split,
                physics,
                {axis_a: value_a, axis_b: value_b},
            )
        )
    return cards


def build_cards() -> list[dict[str, Any]]:
    cards = []
    for family, study in STUDIES.items():
        for axis in study["single_axes"]:
            cards.extend(single_axis_cards(family, axis))
        cards.extend(joint_axis_cards(family, study["joint_axes"]))
    return cards


def audit(cards: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(cards) == 204
    assert len({card["card_id"] for card in cards}) == len(cards)
    # Use the same W10 primitive used by release records.  It checks both the
    # release lineage and (when present) the exact physical case.  The latter
    # catches a bad relabelling where two cards retain different lineage IDs
    # but describe the same physical state in different splits.
    validate_split_lineage(cards)

    split_by_signature: dict[str, set[str]] = {}
    for card in cards:
        split_by_signature.setdefault(card["execution_unit_id"], set()).add(card["split"])
    leakage = {key: sorted(value) for key, value in split_by_signature.items() if len(value) > 1}
    assert not leakage, f"identical physical states cross splits: {leakage}"

    split_by_physical_case: dict[str, set[str]] = {}
    lineage_by_physical_case: dict[str, set[str]] = {}
    studies_by_physical_case: dict[str, set[str]] = {}
    for card in cards:
        physical_case = card["physical_case_id"]
        split_by_physical_case.setdefault(physical_case, set()).add(card["split"])
        lineage_by_physical_case.setdefault(physical_case, set()).add(card["lineage_group_id"])
        studies_by_physical_case.setdefault(physical_case, set()).add(card["study_id"])
    physical_case_leakage = {
        key: sorted(value) for key, value in split_by_physical_case.items() if len(value) > 1
    }
    assert not physical_case_leakage, f"physical case crosses splits: {physical_case_leakage}"
    assert all(len(value) == 1 for value in lineage_by_physical_case.values()), (
        "one physical case must map to one lineage group"
    )
    split_by_lineage: dict[str, set[str]] = {}
    for card in cards:
        split_by_lineage.setdefault(card["lineage_group_id"], set()).add(card["split"])
    lineage_leakage = {key: sorted(value) for key, value in split_by_lineage.items() if len(value) > 1}
    assert not lineage_leakage, f"lineage crosses splits: {lineage_leakage}"

    backgrounds_by_family: dict[str, set[str]] = {}
    studies_by_background: dict[str, set[str]] = {}
    for card in cards:
        backgrounds_by_family.setdefault(card["family"], set()).add(card["paired_background_id"])
        studies_by_background.setdefault(card["paired_background_id"], set()).add(card["study_id"])
    assert all(len(value) == 1 for value in backgrounds_by_family.values()), (
        "each family must keep one fixed paired background across its studies"
    )

    for family, study in STUDIES.items():
        for axis in study["single_axes"]:
            subset = [c for c in cards if c["study_id"] == f"W08_{family}_single_{axis}"]
            fixed_axes = set(FAMILY_SPECS[family]["continuous"]) - {axis}
            for fixed in fixed_axes:
                assert len({c["physics"][fixed] for c in subset}) == 1
            train = [c["normalized_intervention"][axis] for c in subset if c["split"] == "train"]
            interp = [c["normalized_intervention"][axis] for c in subset if c["split"] == "interpolation"]
            extra = [c["normalized_intervention"][axis] for c in subset if c["split"] == "extrapolation"]
            assert all(min(train) < value < max(train) for value in interp)
            assert all(value < min(train) or value > max(train) for value in extra)

    return {
        "cards": len(cards),
        "unique_execution_units": len(split_by_signature),
        "duplicate_cards_reusable_within_split": len(cards) - len(split_by_signature),
        "cross_split_signature_leakage": leakage,
        "cross_split_physical_case_leakage": physical_case_leakage,
        "cross_split_lineage_leakage": lineage_leakage,
        "physical_case_count": len(split_by_physical_case),
        "physical_cases_reused_across_studies": sum(len(value) > 1 for value in studies_by_physical_case.values()),
        "paired_background_count": len(studies_by_background),
        "paired_backgrounds_by_family": {
            family: {
                "ids": sorted(ids),
                "study_count": len({card["study_id"] for card in cards if card["family"] == family}),
                "split_reuse_is_intentional": True,
            }
            for family, ids in sorted(backgrounds_by_family.items())
        },
        "families": sorted(STUDIES),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", type=Path, required=True)
    args = parser.parse_args()
    campaign_dir = args.campaign_dir.resolve()
    cards = build_cards()
    audit_result = audit(cards)
    design = {
        "schema_version": 1,
        "scope": "controlled W08 design cards, not solver jobs",
        "split_unit": "physical_case_id and its lineage_group_id; all temporal windows and material subsets inherit the simulation split",
        "identity_semantics": {
            "study_id": "causal intervention protocol; groups cards that vary one or two named axes",
            "paired_background_id": "fixed baseline context shared by a family's intervention studies; reuse across splits is intentional",
            "physical_case_id": "canonical exact physical parameter state; duplicate study cards may reference the same case",
            "lineage_group_id": "release lineage rooted at one physical case; resolutions, windows, numerics, and derived products stay in its split",
            "execution_unit_id": "deduplicated solver execution for an exact physical state",
        },
        "study_count": 12,
        "card_count": len(cards),
        "topology_holdout_card_count": len(topology_holdout_cards()),
        "topology_holdout_cards": topology_holdout_cards(),
        "studies": STUDIES,
        "cards": cards,
    }
    report = {
        "schema_version": 1,
        "audit": audit_result,
        "single_axis_protocol": SINGLE_LEVELS,
        "two_axis_protocol": {
            "train": "3x3 interior grid at normalized 0.3/0.5/0.7",
            "interpolation": "four cell centers at normalized 0.4/0.6",
            "single_axis_extrapolation": "one axis at 0.1/0.9 while the other remains in the training grid",
            "joint_extrapolation": "four 0.1/0.9 corners",
        },
        "topology_holdouts": {family: spec["topology_holdout"] for family, spec in STUDIES.items()},
        "topology_holdout_cards": topology_holdout_cards(),
        "topology_materialization": {
            "manifest": "campaigns/v0.1-candidate/cases/w08/topology-holdout-materializations.json",
            "formal_release": False,
            "status": "candidate_evidence_indexed",
            "interpretation": "separate from the 204 continuous-axis cards; physical/reference acceptance remains required",
        },
        "release_constraints": [
            "No random frame split.",
            "All windows, particles, tracers, and derived targets from one simulation inherit one split.",
            "Replicate resolutions and numerical variants stay grouped with the same physical lineage.",
            "The same physical_case_id and lineage_group_id must never occur in more than one split; paired_background_id may be reused across splits as a fixed intervention background.",
            "Topology holdouts are separate from continuous-axis claims and are not silently pooled.",
        ],
        "execution_decision": "continuous_cards_planned_not_run; topology_holdout_candidate_materialization_tracked_separately",
    }
    out = campaign_dir / "cases" / "w08"
    out.mkdir(parents=True, exist_ok=True)
    (out / "controlled-generalization-design.json").write_text(json.dumps(design, indent=2) + "\n")
    (campaign_dir / "w08-generalization-audit.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
