#!/usr/bin/env python3
"""Run a bounded 32k-update optimizer resource probe.

The probe is deliberately a synthetic, CPU-only benchmark.  It runs only
after a release-candidate record proves the schema/data gate, and it writes a
resource measurement rather than a ``core.training.v1`` receipt.  It never
opens trajectories, writes checkpoints, submits jobs, or contributes to the
formal 3-model-by-3-seed denominator.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import sys
import time
from typing import Any, Mapping, Sequence

import torch

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_models import FEATURE_DIM, DualIncrementModel
from scripts.core_strict_json import (
    absolute_path_without_following_leaf,
    read_bounded_raw_json,
    strict_json_object,
)


SCHEMA = "core.formal_resource_dryrun.v1"
FORMAL_UPDATES = 32000
FORMAL_JOB_COUNT = 9
MILESTONES = (8000, 16000, 24000, 32000)
DATA_BLOCKERS = {
    "MANIFEST_CONTRACT_INVALID",
    "SPLIT_SHAPE_REQUIRED",
    "HARD_AUDIT_GAP",
    "STRUCTURAL_AUDIT_GAP",
    "STRUCTURAL_RECEIPT_BINDING_GAP",
    "AUDIT_BINDING_GAP",
}


def _load_candidate(path: str | Path) -> Mapping[str, Any]:
    resolved = absolute_path_without_following_leaf(path)
    raw = read_bounded_raw_json(resolved, label="resource probe candidate")
    payload = strict_json_object(raw, label="resource probe candidate")
    if payload.get("schema") != "core.formal_release_candidate.v1":
        raise ValueError("resource probe requires core.formal_release_candidate.v1")
    if payload.get("data_contract_ready") is not True:
        raise ValueError("schema/data gate is not ready; resource probe was not started")
    if payload.get("formal_release") is not False:
        raise ValueError("resource probe cannot run against a formal release")
    if payload.get("formal_job_count") != 0:
        raise ValueError("resource probe candidate has a nonzero formal job count")
    blockers = set(payload.get("data_blocker_codes", ()))
    if blockers & DATA_BLOCKERS:
        raise ValueError(f"resource probe data blockers remain: {sorted(blockers & DATA_BLOCKERS)}")

    admission = payload.get("admission_observation")
    if not isinstance(admission, Mapping):
        raise ValueError("resource probe requires an explicit admission observation")
    denominator = admission.get("production_denominator")
    if not isinstance(denominator, Mapping):
        raise ValueError("resource probe requires an explicit production denominator")
    counts = {
        name: denominator.get(name)
        for name in (
            "included_case_count",
            "hard_integrity_pass_bound_count",
            "structural_pass_bound_count",
        )
    }
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
           for value in counts.values()):
        raise ValueError("resource probe requires positive integer production denominator counts")
    if counts["hard_integrity_pass_bound_count"] != counts["included_case_count"]:
        raise ValueError("resource probe requires complete hard-audit denominator")
    if counts["structural_pass_bound_count"] != counts["included_case_count"]:
        raise ValueError("resource probe requires complete structural-audit denominator")
    return payload


def run_dryrun(candidate: Mapping[str, Any], *, updates: int = FORMAL_UPDATES,
               centers_per_update: int = 256, hidden: int = 64,
               seed: int = 17, threads: int = 1) -> dict[str, Any]:
    if int(updates) != FORMAL_UPDATES:
        raise ValueError("the resource frontier probe must target exactly 32000 updates")
    if int(centers_per_update) < 1 or int(hidden) < 1:
        raise ValueError("centers_per_update and hidden must be positive")
    if int(threads) < 1:
        raise ValueError("threads must be positive")
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(int(threads))
    try:
        torch.manual_seed(int(seed))
        model = DualIncrementModel("mlp", hidden=int(hidden)).to("cpu")
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        features = torch.randn(int(centers_per_update), FEATURE_DIM)
        positions = torch.randn(int(centers_per_update), 3)
        neighbors = torch.zeros((int(centers_per_update), 1), dtype=torch.int64)
        targets = torch.randn(int(centers_per_update), 6)
        centers = torch.arange(int(centers_per_update), dtype=torch.int64)
        started = time.perf_counter()
        milestone_observations: list[dict[str, Any]] = []
        for update in range(1, FORMAL_UPDATES + 1):
            optimizer.zero_grad(set_to_none=True)
            prediction = model(features, positions, neighbors, 0.01194127788262211,
                               centers=centers)
            loss = torch.mean((prediction - targets) ** 2)
            loss.backward()
            optimizer.step()
            if update in MILESTONES:
                milestone_observations.append({
                    "update": update,
                    "elapsed_seconds": time.perf_counter() - started,
                    "loss_mse": float(loss.detach().cpu()),
                })
        elapsed = time.perf_counter() - started
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return {
            "schema": SCHEMA,
            "mode": "synthetic_optimizer_frontier_probe",
            "status": "completed",
            "dry_run": True,
            "formal_release": False,
            "formal_training": False,
            "formal_job_count": 0,
            "required_formal_job_count": FORMAL_JOB_COUNT,
            "diagnostic_runs_counted_as_formal": False,
            "candidate_record_id": candidate.get("record_id"),
            "candidate_data_contract_ready": True,
            "protocol": {
                "updates_requested": FORMAL_UPDATES,
                "updates_completed": FORMAL_UPDATES,
                "model_kind": "mlp",
                "seed": int(seed),
                "centers_per_update": int(centers_per_update),
                "hidden": int(hidden),
                "learning_rate": 1e-3,
                "optimizer": "Adam",
                "device": "cpu",
                "torch_threads": int(threads),
                "synthetic_input": True,
            },
            "milestones": milestone_observations,
            "resource": {
                "wall_seconds": elapsed,
                "updates_per_second": FORMAL_UPDATES / elapsed if elapsed > 0 else None,
                "peak_rss_mib": usage.ru_maxrss / 1024.0,
                "user_cpu_seconds": usage.ru_utime,
                "system_cpu_seconds": usage.ru_stime,
            },
            "execution_constraints": {
                "trajectory_files_opened": False,
                "future_state_inputs": False,
                "formal_runs_started": 0,
                "gpu_started": False,
                "solver_started": False,
                "submitted": False,
                "central_registry_mutation": 0,
                "central_ledger_mutation": 0,
                "checkpoint_written": False,
                "training_receipt_written": False,
            },
            "interpretation": (
                "A 32000-update synthetic MLP optimizer probe establishes a bounded CPU frontier. "
                "It does not prove full-field graph memory, trajectory IO, or formal training capacity."
            ),
        }
    finally:
        torch.set_num_threads(previous_threads)


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"resource measurement is immutable and already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                  ensure_ascii=False, allow_nan=False) + "\n",
                       encoding="utf-8")
    partial.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--centers-per-update", type=int, default=256)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--threads", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    candidate = _load_candidate(args.candidate)
    result = run_dryrun(
        candidate, centers_per_update=args.centers_per_update,
        hidden=args.hidden, threads=args.threads)
    write_json(args.output, result)
    print(json.dumps({
        "schema": result["schema"],
        "status": result["status"],
        "dry_run": result["dry_run"],
        "formal_job_count": result["formal_job_count"],
        "updates_completed": result["protocol"]["updates_completed"],
        "wall_seconds": result["resource"]["wall_seconds"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
