#!/usr/bin/env python3
"""Check W12 results and emit the candidate-design freeze decision."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def elapsed_cases(path: Path) -> tuple[int, float]:
    payload = json.loads(path.read_text())
    cases = payload.get("run_results") or payload.get("cases", []) or []
    if isinstance(cases, dict):
        cases = list(cases.values())
    return len(cases), sum(float(case.get("elapsed_seconds", 0)) for case in cases)


def learning_gate_policy() -> dict[str, object]:
    """Keep model stress tests separate from physical-scene admission.

    A constant-velocity comparison is useful for diagnosing a weak learner,
    but making it a scene gate would preferentially remove difficult yet
    scientifically valuable cases.  The data, input, and metric gates remain
    independent of this diagnostic.
    """

    return {
        "status": "diagnostic_only",
        "requirements": [
            "three seeds",
            "autonomous family-wise rollout",
            "boundary and known-control inputs",
            "report degradation relative to constant velocity",
        ],
        "scene_admission_independent": True,
        "policy": "learner degradation is a model/input diagnostic, never a physical-scene admission gate",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.lab_root.resolve()
    result_dir = root / "release/v0.1-development/baselines/results"
    runs = [json.loads(path.read_text()) for path in sorted(result_dir.glob("*.json"))]
    combinations = {(run["route"], run["seed"]) for run in runs}
    expected = {(route, seed) for route in ("particle_mlp", "deepset_context") for seed in (17, 29, 43)}
    if combinations != expected:
        raise ValueError(f"missing or extra learned runs: expected={expected}, observed={combinations}")
    for run in runs:
        values = [metric["learned_rmse_over_dp"] for metric in run["test_rollout"].values()]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"non-finite rollout metric in {run['route']} seed {run['seed']}")

    solver_sources = [
        "reports/runtime/run-summary.json",
        "reports/runtime/official-run-summary.json",
        "campaigns/v0.1-candidate/w04-calibration.json",
        "campaigns/v0.1-candidate/w05-validation-anchors.json",
        "campaigns/v0.1-candidate/w06-rotating-pour.json",
    ]
    solver_runs, solver_seconds = 0, 0.0
    source_costs = {}
    for relative in solver_sources:
        count, seconds = elapsed_cases(root / relative)
        solver_runs += count
        solver_seconds += seconds
        source_costs[relative] = {"successful_runs": count, "summed_elapsed_seconds": seconds}
    ml_train = sum(run["training_seconds"] for run in runs)
    ml_inference = sum(run["inference_seconds"] for run in runs)
    baselines = json.loads((root / "campaigns/v0.1-candidate/w12-baselines.json").read_text())

    decision = {
        "schema_version": 1,
        "decision": "do_not_freeze_formal_v0.1_yet",
        "ready_to_freeze": [
            "isolated engineering workflow and immutable attempt provenance",
            "fixed-resolution closed-domain numerical identity semantics",
            "independent passive-tracer candidate interface and reliability-mask semantics (not physical acceptance)",
            "causal namespaces, lineage-group split rule, HDF5/manifest contract, and metrics",
            "six-family candidate axes and controlled W08 intervention design",
        ],
        "not_ready_to_freeze": [
            "formal family membership and production parameter counts",
            "family-specific production particle spacing and event output cadence",
            "material-tracer wall visibility, convergence and destination closure",
            "F1 impact pressure, F2 external observation/resolution, F3 impact timing, F4 validation, F5 stable run-up, F6 three-dimensional Test 14",
            "leaderboard learning architecture: both pilot learners lack boundary geometry/local interactions and diverge on long F2 rollout",
        ],
        "minimum_next_gates": {
            "all_core_cases": ["zero unexplained numerical mass loss", "unique identity and kinematic audit", "at least 95% reliable independent tracers", "destination closure against initial mass"],
            "resolution": "top two retained resolutions must agree on declared primary observables within a pre-registered tolerance; use 5% as an initial screening threshold, not universal truth",
            "event_sampling": "at least 10 samples across the shortest scored impact/rise interval",
            "external_observation": "each retained family needs at least one case with uncertainty-aware external comparison",
            "learning": learning_gate_policy(),
        },
        "recommended_sequence": [
            "Close F2 resolution plus simple physical observation first, because its material-history task is the clearest differentiator.",
            "Repair F1/F3 event cadence and convergence, and implement the SPHERIC Test 14 three-dimensional F6 anchor.",
            "Choose an external F4 collision/impingement anchor and rebuild F5 from a stable run-up validation before admitting either family.",
            "Run a 20-30 case development tranche only for passing families, then repeat real baselines before fixing formal scale.",
        ],
        "baseline_observation": baselines,
        "resource_accounting": {
            "successful_solver_runs_accounted": solver_runs,
            "successful_solver_gpu_seconds_lower_bound": solver_seconds,
            "learned_training_gpu_seconds": ml_train,
            "learned_inference_gpu_seconds": ml_inference,
            "combined_gpu_hours_lower_bound": (solver_seconds + ml_train + ml_inference) / 3600,
            "excluded_from_lower_bound": ["failed solver attempts", "W02 runs lacking elapsed fields", "CPU preprocessing", "dependency installation"],
            "source_costs": source_costs,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, indent=2) + "\n")


if __name__ == "__main__":
    main()
