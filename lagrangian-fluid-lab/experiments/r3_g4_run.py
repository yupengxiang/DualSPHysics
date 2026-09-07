#!/usr/bin/env python3
"""Launch the bounded R3 G4 matrix on the reserved physical GPUs only."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

LAB = Path(__file__).resolve().parents[1]
INVENTORY = LAB / "campaigns" / "v0.1-candidate" / "w00-inventory.json"
TRAINER = LAB / "experiments" / "r3_g4_baselines.py"
ROUTES = ("particle_mlp", "deepset_context", "local_interaction", "physics_residual")
SEEDS = (17, 29, 43)

# The repository root is the normal invocation directory; expose the custom
# lab package explicitly without modifying the upstream DualSPHysics tree.
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))


def wait_for_idle(index: int, allowed_uuids: list[str]):
    """Bounded retry for transient utilization left by a finished process."""

    last_error = None
    for _ in range(12):
        try:
            return require_idle_allowed_gpu(index, allowed_uuids)
        except RuntimeError as error:
            last_error = error
            if "is not idle" not in str(error):
                raise
            time.sleep(5)
    raise RuntimeError(f"GPU {index} did not become idle within 60 seconds: {last_error}")

try:
    from scripts.campaign_runner import require_idle_allowed_gpu
except ModuleNotFoundError:  # direct invocation from this directory
    from campaign_runner import require_idle_allowed_gpu


def task_list() -> list[dict[str, int | str]]:
    gpu_cycle = (4, 5, 6, 7)
    return [
        {"route": route, "seed": seed, "gpu_index": gpu_cycle[index % len(gpu_cycle)]}
        for index, (route, seed) in enumerate((route, seed) for route in ROUTES for seed in SEEDS)
    ]


def launch(task: dict[str, int | str], args: argparse.Namespace, allowed_uuids: list[str]) -> dict:
    route = str(task["route"])
    seed = int(task["seed"])
    gpu_index = int(task["gpu_index"])
    gpu = wait_for_idle(gpu_index, allowed_uuids)
    output = args.results_dir / f"{route}_seed{seed}.json"
    checkpoint = args.checkpoints_dir / f"{route}_seed{seed}.pt"
    log_path = args.logs_dir / f"{route}_seed{seed}.log"
    command = [
        sys.executable, str(TRAINER), "--manifest", str(args.manifest.resolve()),
        "--route", route, "--seed", str(seed), "--epochs", str(args.epochs),
        "--min-epochs", str(args.min_epochs), "--patience", str(args.patience),
        "--min-delta", str(args.min_delta), "--max-particles", str(args.max_particles),
        "--validation-particles", str(args.validation_particles), "--hidden", str(args.hidden),
        "--learning-rate", str(args.learning_rate), "--clip-dp", str(args.clip_dp),
        "--device", "cuda", "--output", str(output), "--checkpoint", str(checkpoint),
    ]
    env = os.environ.copy()
    # Restrict each child to one reserved physical GPU.  Inside that process
    # it is visible as cuda:0, while the physical index/UUID are retained here.
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    env.setdefault("OMP_NUM_THREADS", "1")
    started = time.perf_counter()
    process = subprocess.run(command, cwd=LAB, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.perf_counter() - started
    log_path.write_text(process.stdout)
    result_status = "completed" if process.returncode == 0 and output.is_file() else "failed"
    return {
        "route": route, "seed": seed, "physical_gpu_index": gpu_index, "gpu_uuid": gpu["uuid"],
        "gpu_name": gpu.get("name"), "status": result_status, "returncode": process.returncode,
        "elapsed_seconds": elapsed, "output": str(output.relative_to(LAB)),
        "checkpoint": str(checkpoint.relative_to(LAB)), "log": str(log_path.relative_to(LAB)),
        "command": command,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=LAB / "release/v0.1-development/manifest.json")
    parser.add_argument("--results-dir", type=Path, default=LAB / "experiments/r3_g4_results")
    parser.add_argument("--checkpoints-dir", type=Path, default=LAB / "release/v0.1-development/baselines/checkpoints/r3_g4")
    parser.add_argument("--logs-dir", type=Path, default=LAB / "experiments/r3_g4_logs")
    parser.add_argument("--run-manifest", type=Path, default=LAB / "experiments/r3_g4_run_manifest.json")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--min-epochs", type=int, default=3)
    parser.add_argument("--patience", type=int, default=2)
    parser.add_argument("--min-delta", type=float, default=1e-5)
    parser.add_argument("--max-particles", type=int, default=256)
    parser.add_argument("--validation-particles", type=int, default=512)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--clip-dp", type=float, default=0.0)
    args = parser.parse_args()
    # Resolve paths before changing the child working directory to LAB.  This
    # keeps relative CLI arguments from accidentally producing LAB/LAB/... and
    # makes manifest links deterministic.
    args.manifest = args.manifest.resolve()
    args.results_dir = args.results_dir.resolve()
    args.checkpoints_dir = args.checkpoints_dir.resolve()
    args.logs_dir = args.logs_dir.resolve()
    args.run_manifest = args.run_manifest.resolve()
    inventory = json.loads(INVENTORY.read_text())
    allowed = inventory["execution_policy"]["allowed_gpu_uuids"]
    args.results_dir.mkdir(parents=True, exist_ok=True)
    args.checkpoints_dir.mkdir(parents=True, exist_ok=True)
    args.logs_dir.mkdir(parents=True, exist_ok=True)
    tasks = task_list()
    records = []
    for start in range(0, len(tasks), 4):
        batch = tasks[start:start + 4]
        # Recheck each physical GPU immediately before every batch.  This is
        # intentionally serial between batches so a reused GPU is never
        # launched while a previous child still owns it.
        for task in batch:
            wait_for_idle(int(task["gpu_index"]), allowed)
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [pool.submit(launch, task, args, allowed) for task in batch]
            records.extend(future.result() for future in futures)
    payload = {
        "schema_version": 1, "scope": "R3-G4 corrected development baseline execution manifest",
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "allowed_gpu_indices": [4, 5, 6, 7],
        "config": "experiments/r3_g4_config.json", "runs": records,
        "status": "complete" if all(record["status"] == "completed" for record in records) else "partial_or_failed",
    }
    args.run_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.run_manifest.write_text(json.dumps(payload, indent=2) + "\n")
    if payload["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
