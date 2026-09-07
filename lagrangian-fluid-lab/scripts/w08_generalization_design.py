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
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from w07_mechanism_screen import FAMILY_SPECS


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
    return {
        "card_id": f"W08_{family}_{study}_{ordinal:02d}",
        "family": family,
        "study_id": f"W08_{family}_{study}",
        "paired_background_id": f"W08_{family}_{study}_background",
        "physical_case_id": physical_case_id,
        "lineage_group_id": physical_case_id,
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
    split_by_signature: dict[str, set[str]] = {}
    for card in cards:
        split_by_signature.setdefault(card["execution_unit_id"], set()).add(card["split"])
    leakage = {key: sorted(value) for key, value in split_by_signature.items() if len(value) > 1}
    assert not leakage, f"identical physical states cross splits: {leakage}"
    split_by_lineage: dict[str, set[str]] = {}
    for card in cards:
        split_by_lineage.setdefault(card["lineage_group_id"], set()).add(card["split"])
    lineage_leakage = {key: sorted(value) for key, value in split_by_lineage.items() if len(value) > 1}
    assert not lineage_leakage, f"lineage crosses splits: {lineage_leakage}"

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
        "cross_split_lineage_leakage": lineage_leakage,
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
        "split_unit": "physical simulation signature; all temporal windows and material subsets inherit the simulation split",
        "study_count": 12,
        "card_count": len(cards),
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
        "release_constraints": [
            "No random frame split.",
            "All windows, particles, tracers, and derived targets from one simulation inherit one split.",
            "Replicate resolutions and numerical variants stay grouped with the same physical lineage.",
            "Topology holdouts are separate from continuous-axis claims and are not silently pooled.",
        ],
        "execution_decision": "planned_not_run_until_W10_schema_and_family_resolution_gates",
    }
    out = campaign_dir / "cases" / "w08"
    out.mkdir(parents=True, exist_ok=True)
    (out / "controlled-generalization-design.json").write_text(json.dumps(design, indent=2) + "\n")
    (campaign_dir / "w08-generalization-audit.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
