#!/usr/bin/env python3
"""Aggregate six learned runs with simple and low-resolution SPH anchors."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def mean_std(values):
    values = np.asarray(values, dtype=float)
    return {"mean": float(values.mean()), "sample_std": float(values.std(ddof=1)) if len(values) > 1 else 0.0, "values": values.tolist()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--w05", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runs = [json.loads(path.read_text()) for path in sorted(args.results_dir.glob("*.json"))]
    if len(runs) != 6:
        raise ValueError(f"expected six learning runs, found {len(runs)}")
    grouped = defaultdict(list)
    for run in runs:
        grouped[run["route"]].append(run)
    learned = {}
    for route, route_runs in grouped.items():
        cases = sorted(route_runs[0]["test_rollout"])
        learned[route] = {
            "seeds": sorted(run["seed"] for run in route_runs),
            "parameter_count": route_runs[0]["parameter_count"],
            "training_seconds": mean_std([run["training_seconds"] for run in route_runs]),
            "inference_seconds": mean_std([run["inference_seconds"] for run in route_runs]),
            "peak_gpu_memory_bytes": max(run["peak_gpu_memory_bytes"] for run in route_runs),
            "test_cases": {
                case: {
                    "autonomous_rmse_over_dp": mean_std([run["test_rollout"][case]["learned_rmse_over_dp"] for run in route_runs]),
                    "autonomous_fde_m": mean_std([run["test_rollout"][case]["learned_fde_m"] for run in route_runs]),
                }
                for case in cases
            },
        }
    first = runs[0]
    simple = {
        case: {
            "constant_velocity_rmse_over_dp": metrics["constant_velocity_rmse_over_dp"],
            "constant_velocity_fde_m": metrics["constant_velocity_fde_m"],
        }
        for case, metrics in first["test_rollout"].items()
    }
    w05 = json.loads(args.w05.read_text())
    external = w05["external_validation"]
    low_resolution_sph = {
        "track": "external physical observables; not particle-corresponded rollout",
        "nine_run_validation_campaign_gpu_seconds": w05["resource_summary"]["successful_solver_gpu_seconds"],
        "F1_Test02_dp0.04": external["F1"]["coarse"],
        "F3_Test10_dp0.008": external["F3"]["coarse"],
        "F6_Fekken_dp0.10": external["F6"]["coarse"],
    }
    payload = {
        "schema_version": 1,
        "scope": "W12 real development baselines",
        "simple_baseline": simple,
        "low_resolution_sph_baseline": low_resolution_sph,
        "learned_baselines": learned,
        "comparability_warning": "SPH external-observable metrics and learned particle-rollout metrics are separate tracks and must not be ranked in one scalar table.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
