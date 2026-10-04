#!/usr/bin/env python3
"""DS-DATA-02 F6 Standard Kabsch Proper SO(3) Evaluation Pipeline.

Reuses the proven geometry-based Kabsch SVD pose reconstruction and SLERP trajectory
comparison pipeline from owner_geometry_v1.py (Review 029 / 030):
1. SO(3) rigid pose reconstruction:
   - SVD of covariance matrix H = P_ref^T @ P_cand with uniform weights (1/N).
   - Enforces det(R) = +1 (proper rotation, no reflection).
   - Verifies rank 3 covariance.
2. Continuous SLERP trajectory comparison on Lie group SO(3):
   - Shortest geodesic arc SLERP interpolation between native timestamps.
   - Evaluated on fixed physical grid: t = 0.0, 0.05, ..., 12.0s (241 points).
3. Registered translation evaluation:
   - Evaluated against registered characteristic scale L = 0.8m.
   - Generic 5% macro tolerance: 0.04m.
4. Descriptive orientation metrics:
   - Riemannian geodesic distance Phi = arccos(clip((tr(R_ref^T R_cand) - 1) / 2, -1, 1)) [rad].
   - Geodesic RMSE, maximum, and mean reported in radians and degrees.
5. Inviolable governance:
   - Orientation budget is NULL / unregistered.
   - STRICTLY PROHIBITED: Never invent orientation 1 rad normalization or 5% SO(3) threshold.
   - q_n: "not_granted", production_approval: "none".
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import owner_geometry_v1 as owner

SCHEMA_COMPARISON = "ds02.f6.halfstep-kabsch-pose-comparison.v1"
L_CHAR_M = 0.8
GENERIC_MACRO_TOLERANCE = 0.05
EXPECTED_FRAMES = 241
EXPECTED_WINDOW_S = 12.0


def evaluate_trajectories(
    ref_trajectory: dict[str, Any],
    cand_trajectory: dict[str, Any],
    grid_times: np.ndarray | None = None,
) -> dict[str, Any]:
    """Compare reference and candidate rigid body trajectories on physical time grid."""
    if grid_times is None:
        grid_times = np.arange(EXPECTED_FRAMES, dtype=float) * 0.05

    comparison = owner.compare_trajectories_physical_time(
        ref_trajectory, cand_trajectory, grid_times
    )

    result = {
        "schema": SCHEMA_COMPARISON,
        "grid_frames": len(grid_times),
        "physical_window_s": [float(grid_times[0]), float(grid_times[-1])],
        "comparison": comparison,
        "claim_boundary": {
            "q_n": "not_granted",
            "production_approval": "none",
            "orientation_budget": None,
            "orientation_budget_status": "unregistered",
            "orientation_threshold_policy": "Strictly descriptive metrics only. Never invent 1 rad normalization or 5% SO(3) threshold.",
            "translation_reference_scale_m": L_CHAR_M,
            "translation_generic_5pct_budget_m": L_CHAR_M * GENERIC_MACRO_TOLERANCE,
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref-report", type=Path, help="Reference trajectory report JSON")
    parser.add_argument("--cand-report", type=Path, help="Candidate trajectory report JSON")
    parser.add_argument("--output", type=Path, help="Output comparison JSON path")
    args = parser.parse_args()

    if not args.ref_report or not args.cand_report:
        print("Usage: kabsch_evaluation_pipeline.py --ref-report <path> --cand-report <path> --output <path>")
        return 0

    ref_data = json.loads(args.ref_report.read_text(encoding="utf-8"))
    cand_data = json.loads(args.cand_report.read_text(encoding="utf-8"))

    ref_traj = {
        "times": np.array([f["time_s"] for f in ref_data["frames"]]),
        "centroids": np.array([f["center_m"] for f in ref_data["frames"]]),
        "quaternions": np.array([f["quaternion_wxyz"] for f in ref_data["frames"]]),
    }
    cand_traj = {
        "times": np.array([f["time_s"] for f in cand_data["frames"]]),
        "centroids": np.array([f["center_m"] for f in cand_data["frames"]]),
        "quaternions": np.array([f["quaternion_wxyz"] for f in cand_data["frames"]]),
    }

    result = evaluate_trajectories(ref_traj, cand_traj)
    output_text = json.dumps(result, indent=2) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
        print(f"Comparison report written to {args.output}")
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
