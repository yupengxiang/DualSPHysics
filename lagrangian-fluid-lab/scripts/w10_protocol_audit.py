#!/usr/bin/env python3
"""Run adversarial self-tests against the W10 protocol reference functions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from protocol_metrics import (
    mass_fraction_tv,
    midpoint_kinematic_residual,
    require_event_sampling,
    require_finite_when_valid,
    require_strict_time,
    trajectory_metrics,
    validate_affine_transforms,
    validate_split_lineage,
)


def must_reject(name, operation) -> dict:
    try:
        operation()
    except (ValueError, AssertionError) as exc:
        return {"attack": name, "detected": True, "reason": str(exc)}
    return {"attack": name, "detected": False, "reason": "accepted unexpectedly"}


def must_accept(name, operation) -> dict:
    """Record a protocol case that is valid by design.

    A paired background is a controlled nuisance context, not a physical
    lineage.  Reusing it across intervention splits is therefore expected and
    should remain a visible positive control in the W10 report.
    """
    try:
        operation()
    except (ValueError, AssertionError) as exc:
        return {"attack": name, "detected": False, "reason": f"rejected unexpectedly: {exc}"}
    return {"attack": name, "detected": True, "reason": "accepted as an intentional paired-background reuse"}


def run_attacks() -> list[dict]:
    time = np.asarray([0.0, 0.1, 0.2])
    position = np.zeros((3, 3, 3))
    velocity = np.zeros_like(position)
    position[:, 0, 0] = [0.0, 0.1, 0.2]
    position[:, 1, 0] = [1.0, 0.9, 0.8]
    position[:, 2, 1] = [0.0, 0.1, 0.2]
    velocity[:, 0, 0] = 1.0
    velocity[:, 1, 0] = -1.0
    velocity[:, 2, 1] = 1.0
    valid = np.ones((3, 3), dtype=bool)
    baseline_residual = midpoint_kinematic_residual(position, velocity, time, valid)

    shuffled_position = position.copy()
    shuffled_position[1] = shuffled_position[1, [2, 0, 1]]
    shuffled_residual = midpoint_kinematic_residual(shuffled_position, velocity, time, valid)

    transforms = np.repeat(np.eye(4)[None], 3, axis=0)
    bad_transform = transforms.copy()
    bad_transform[1, 0, 0] = 2.0
    invalid_values = position.copy()
    invalid_values[1, 0] = np.nan

    attacks = [
        must_reject("non_monotonic_time", lambda: require_strict_time([0.0, 0.2, 0.1])),
        must_reject("nan_under_valid_mask", lambda: require_finite_when_valid(invalid_values, valid)),
        must_reject("improper_moving_frame", lambda: validate_affine_transforms(bad_transform)),
        must_reject(
            "split_by_frames_or_resolution",
            lambda: validate_split_lineage([
                {"lineage_group_id": "same-physics", "split": "train"},
                {"lineage_group_id": "same-physics", "split": "test"},
            ]),
        ),
        must_reject(
            "same_physical_case_with_different_lineage_labels",
            lambda: validate_split_lineage([
                {"physical_case_id": "same-physics", "lineage_group_id": "lineage-train", "split": "train"},
                {"physical_case_id": "same-physics", "lineage_group_id": "lineage-test", "split": "test"},
            ]),
        ),
        must_accept(
            "paired_background_reuse_across_intervention_splits",
            lambda: validate_split_lineage([
                {"paired_background_id": "same-background", "physical_case_id": "train-case",
                 "lineage_group_id": "train-lineage", "split": "train"},
                {"paired_background_id": "same-background", "physical_case_id": "test-case",
                 "lineage_group_id": "test-lineage", "split": "test"},
            ]),
        ),
        must_reject(
            "survivor_renormalized_transport",
            lambda: mass_fraction_tv({"captured": 0.7, "loss": 0.3}, {"captured": 1.0}),
        ),
        must_reject("undersampled_impact_event", lambda: require_event_sampling(time, 0.09, 0.11, 3)),
        must_reject(
            "missing_predictions_encoded_as_nan",
            lambda: trajectory_metrics(position, invalid_values, valid, dp=0.1),
        ),
        {
            "attack": "per_frame_identity_permutation",
            "detected": bool(shuffled_residual > max(1e-12, 10 * baseline_residual)),
            "reason": f"midpoint residual changed from {baseline_residual:.6g} to {shuffled_residual:.6g} m",
        },
    ]
    return attacks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    attacks = run_attacks()
    report = {
        "schema_version": 1,
        "adversarial_test_count": len(attacks),
        "detected_count": sum(item["detected"] for item in attacks),
        "strict_pass": all(item["detected"] for item in attacks),
        "attacks": attacks,
    }
    if not report["strict_pass"]:
        raise SystemExit(json.dumps(report, indent=2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
