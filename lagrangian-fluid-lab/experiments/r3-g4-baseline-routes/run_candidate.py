#!/usr/bin/env python3
"""Run small independent candidate-only Local/Physics R3 G4 routes.

Each child sees exactly one physical GPU through ``CUDA_VISIBLE_DEVICES``.
Only physical GPUs 4 and 5 are accepted by this launcher.  The trainer is
reused read-only; outputs, checkpoints, logs, and this manifest live under
this sidecar directory and do not alter the established matrix.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


LAB = Path(__file__).resolve().parents[2]
TRAINER = LAB / "experiments" / "r3_g4_baselines.py"
MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"
ROUTES = ("local_interaction", "physics_residual")
SEEDS = (17, 29, 43)
ALLOWED_GPU_INDICES = (4, 5)


def gpu_snapshot(index: int) -> dict[str, str]:
    """Read a physical GPU row and reject any non-reserved index."""

    if index not in ALLOWED_GPU_INDICES:
        raise ValueError(f"physical GPU {index} is forbidden; allowed={ALLOWED_GPU_INDICES}")
    command = [
        "nvidia-smi",
        f"--id={index}",
        "--query-gpu=index,uuid,name,driver_version,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    fields = [field.strip() for field in completed.stdout.strip().split(",")]
    if len(fields) != 7 or int(fields[0]) != index:
        raise RuntimeError(f"unexpected nvidia-smi row for physical GPU {index}: {completed.stdout!r}")
    return {
        "index": fields[0],
        "uuid": fields[1],
        "name": fields[2],
        "driver_version": fields[3],
        "utilization_gpu_percent": fields[4],
        "memory_used_mib": fields[5],
        "memory_total_mib": fields[6],
    }


def build_command(
    route: str,
    seed: int,
    output: Path,
    checkpoint: Path,
    *,
    epochs: int,
    min_epochs: int,
    patience: int,
    max_particles: int,
    validation_particles: int,
    hidden: int,
    learning_rate: float,
    clip_dp: float,
) -> list[str]:
    if route not in ROUTES:
        raise ValueError(f"candidate runner only accepts {ROUTES}; got {route}")
    if seed not in SEEDS:
        raise ValueError(f"candidate runner only accepts seeds {SEEDS}; got {seed}")
    return [
        sys.executable,
        str(TRAINER),
        "--manifest",
        str(MANIFEST.resolve()),
        "--route",
        route,
        "--seed",
        str(seed),
        "--epochs",
        str(epochs),
        "--min-epochs",
        str(min_epochs),
        "--patience",
        str(patience),
        "--min-delta",
        "1e-5",
        "--max-particles",
        str(max_particles),
        "--validation-particles",
        str(validation_particles),
        "--hidden",
        str(hidden),
        "--learning-rate",
        str(learning_rate),
        "--clip-dp",
        str(clip_dp),
        "--device",
        "cuda",
        "--output",
        str(output),
        "--checkpoint",
        str(checkpoint),
    ]


def run_one(task: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    route = str(task["route"])
    seed = int(task["seed"])
    physical_gpu = int(task["physical_gpu_index"])
    gpu = gpu_snapshot(physical_gpu)
    output = args.results_dir / f"{route}_seed{seed}.json"
    checkpoint = args.checkpoints_dir / f"{route}_seed{seed}.pt"
    log_path = args.logs_dir / f"{route}_seed{seed}.log"
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_command(
        route,
        seed,
        output,
        checkpoint,
        epochs=args.epochs,
        min_epochs=args.min_epochs,
        patience=args.patience,
        max_particles=args.max_particles,
        validation_particles=args.validation_particles,
        hidden=args.hidden,
        learning_rate=args.learning_rate,
        clip_dp=args.clip_dp,
    )
    environment = os.environ.copy()
    # Physical index is intentionally recorded separately: the child sees its
    # selected device as cuda:0, and cannot address any other physical GPU.
    environment["CUDA_VISIBLE_DEVICES"] = str(physical_gpu)
    environment["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    environment.setdefault("OMP_NUM_THREADS", "1")
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=LAB,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    elapsed = time.perf_counter() - started
    log_path.write_text(completed.stdout)
    status = "completed" if completed.returncode == 0 and output.is_file() else "failed"
    return {
        "route": route,
        "seed": seed,
        "physical_gpu_index": physical_gpu,
        "gpu": gpu,
        "child_visible_devices": environment["CUDA_VISIBLE_DEVICES"],
        "status": status,
        "returncode": completed.returncode,
        "elapsed_seconds": elapsed,
        "output": str(output.relative_to(LAB)),
        "checkpoint": str(checkpoint.relative_to(LAB)),
        "log": str(log_path.relative_to(LAB)),
        "command": command,
        "cwd": str(LAB),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=Path(__file__).resolve().parent / "results")
    parser.add_argument("--checkpoints-dir", type=Path, default=Path(__file__).resolve().parent / "checkpoints")
    parser.add_argument("--logs-dir", type=Path, default=Path(__file__).resolve().parent / "logs")
    parser.add_argument("--run-manifest", type=Path, default=Path(__file__).resolve().parent / "run_manifest.json")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--min-epochs", type=int, default=2)
    parser.add_argument("--patience", type=int, default=1)
    parser.add_argument("--max-particles", type=int, default=64)
    parser.add_argument("--validation-particles", type=int, default=96)
    parser.add_argument("--hidden", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--clip-dp", type=float, default=0.0)
    args = parser.parse_args()
    for path in (args.results_dir, args.checkpoints_dir, args.logs_dir):
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=True)
    args.run_manifest = args.run_manifest.resolve()

    started = datetime.now(timezone.utc).isoformat()
    tasks = [
        {"route": route, "seed": seed, "physical_gpu_index": ALLOWED_GPU_INDICES[i % len(ALLOWED_GPU_INDICES)]}
        for i, (route, seed) in enumerate((route, seed) for route in ROUTES for seed in SEEDS)
    ]
    records = [run_one(task, args) for task in tasks]
    payload = {
        "schema_version": 1,
        "scope": "R3-G4 independent candidate-only baseline routes",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_ready": False,
        "routes": list(ROUTES),
        "seeds": list(SEEDS),
        "allowed_gpu_indices": list(ALLOWED_GPU_INDICES),
        "gpu_policy": "CUDA_VISIBLE_DEVICES is set to exactly physical GPU 4 or 5 per child; GPUs 0-3 are forbidden",
        "trainer": str(TRAINER.relative_to(LAB)),
        "manifest": str(MANIFEST.relative_to(LAB)),
        "budget": {
            "epochs_requested": args.epochs,
            "min_epochs": args.min_epochs,
            "patience": args.patience,
            "max_particles": args.max_particles,
            "validation_particles": args.validation_particles,
            "hidden": args.hidden,
            "clip_dp": args.clip_dp,
        },
        "runs": records,
        "status": "complete" if all(record["status"] == "completed" for record in records) else "partial_or_failed",
        "interpretation": "Route/input and stability evidence only; no ranking or physical acceptance claim.",
    }
    args.run_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.run_manifest.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": payload["status"], "runs": records}, indent=2))
    if payload["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
