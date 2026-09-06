#!/usr/bin/env python3
"""Train one small real dynamics baseline and evaluate autonomous rollout."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import h5py
import numpy as np
import torch
from torch import nn


FAMILY_INDEX = {"F1": 0, "F2": 1, "F3": 2, "F4": 3, "F5": 4, "F6": 5}


class ParticleMLP(nn.Module):
    def __init__(self, inputs: int, hidden: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(inputs, hidden), nn.SiLU(), nn.Linear(hidden, hidden), nn.SiLU(), nn.Linear(hidden, 3))

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.net(features)


class DeepSetContext(nn.Module):
    def __init__(self, inputs: int, hidden: int):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(inputs, hidden), nn.SiLU(), nn.Linear(hidden, hidden), nn.SiLU())
        self.decoder = nn.Sequential(nn.Linear(2 * hidden, hidden), nn.SiLU(), nn.Linear(hidden, 3))

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        encoded = self.encoder(features)
        context = encoded.mean(dim=0, keepdim=True).expand_as(encoded)
        return self.decoder(torch.cat((encoded, context), dim=-1))


def load_cases(lab_root: Path, manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text())
    release_root = manifest_path.parent
    cases = []
    for record in manifest["cases"]:
        path = release_root / record["hdf5"]
        with h5py.File(path, "r") as h5:
            valid = h5["valid"][:]
            particle_type = h5["type"][:]
            fluid = valid & (particle_type == 3)
            if not fluid[0].any():
                continue
            # W11 core cases are closed, so a stable fluid identity subset exists.
            stable = np.all(fluid, axis=0)
            position = h5["position"][:, stable].astype(np.float32)
            velocity = h5["velocity"][:, stable].astype(np.float32)
            time_values = h5["time"][:].astype(np.float32)
        initial_extent = np.ptp(position[0], axis=0)
        length_scale = float(max(record["numerics"]["particle_spacing_m"], np.max(initial_extent)))
        cases.append({
            "case_id": record["case_id"], "family": record["family"], "split": record["split"],
            "position": position, "velocity": velocity, "time": time_values,
            "dp": float(record["numerics"]["particle_spacing_m"]), "length_scale": length_scale,
        })
    return cases


def features(case: dict, position: torch.Tensor, velocity: torch.Tensor, frame: int) -> torch.Tensor:
    centered = (position - position.mean(dim=0, keepdim=True)) / case["length_scale"]
    dt = float(case["time"][min(frame + 1, len(case["time"]) - 1)] - case["time"][max(0, frame)])
    velocity_scaled = velocity * dt / case["dp"]
    family = torch.zeros((len(position), 6), dtype=position.dtype, device=position.device)
    family[:, FAMILY_INDEX[case["family"]]] = 1
    phase = torch.full((len(position), 1), float(case["time"][frame] / max(case["time"][-1], 1e-9)), dtype=position.dtype, device=position.device)
    return torch.cat((centered, velocity_scaled, family, phase), dim=-1)


def one_step_loss(model: nn.Module, case: dict, frame: int, indices: np.ndarray, device: torch.device) -> torch.Tensor:
    position = torch.from_numpy(case["position"][frame, indices]).to(device)
    velocity = torch.from_numpy(case["velocity"][frame, indices]).to(device)
    target = torch.from_numpy((case["position"][frame + 1, indices] - case["position"][frame, indices]) / case["dp"]).to(device)
    return torch.mean((model(features(case, position, velocity, frame)) - target) ** 2)


@torch.no_grad()
def validation_rmse(model: nn.Module, cases: list[dict], device: torch.device, maximum: int = 256) -> float:
    errors = []
    for case in cases:
        for frame in range(len(case["time"]) - 1):
            count = len(case["position"][frame])
            indices = np.linspace(0, count - 1, min(maximum, count)).round().astype(int)
            position = torch.from_numpy(case["position"][frame, indices]).to(device)
            velocity = torch.from_numpy(case["velocity"][frame, indices]).to(device)
            target = torch.from_numpy((case["position"][frame + 1, indices] - case["position"][frame, indices]) / case["dp"]).to(device)
            errors.append(torch.mean((model(features(case, position, velocity, frame)) - target) ** 2).item())
    return float(np.sqrt(np.mean(errors)))


@torch.no_grad()
def rollout(model: nn.Module, case: dict, device: torch.device) -> dict:
    position = torch.from_numpy(case["position"][0]).to(device)
    velocity = torch.from_numpy(case["velocity"][0]).to(device)
    learned_errors, constant_errors = [], []
    constant_position = position.clone()
    constant_velocity = velocity.clone()
    for frame, dt in enumerate(np.diff(case["time"])):
        displacement = torch.clamp(model(features(case, position, velocity, frame)), -5.0, 5.0) * case["dp"]
        position = position + displacement
        velocity = displacement / float(dt)
        constant_position = constant_position + constant_velocity * float(dt)
        reference = torch.from_numpy(case["position"][frame + 1]).to(device)
        learned_errors.append(torch.linalg.vector_norm(position - reference, dim=-1).cpu().numpy())
        constant_errors.append(torch.linalg.vector_norm(constant_position - reference, dim=-1).cpu().numpy())
    learned = np.concatenate(learned_errors)
    constant = np.concatenate(constant_errors)
    return {
        "frames_predicted": len(case["time"]) - 1,
        "particles": len(case["position"][0]),
        "learned_rmse_m": float(np.sqrt(np.mean(learned ** 2))),
        "learned_rmse_over_dp": float(np.sqrt(np.mean(learned ** 2)) / case["dp"]),
        "learned_fde_m": float(np.mean(learned_errors[-1])),
        "constant_velocity_rmse_m": float(np.sqrt(np.mean(constant ** 2))),
        "constant_velocity_rmse_over_dp": float(np.sqrt(np.mean(constant ** 2)) / case["dp"]),
        "constant_velocity_fde_m": float(np.mean(constant_errors[-1])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--route", choices=["particle_mlp", "deepset_context"], required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--max-particles", type=int, default=128)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)
        torch.cuda.reset_peak_memory_stats(device)
    cases = load_cases(Path.cwd(), args.manifest.resolve())
    train_cases = [case for case in cases if case["split"] == "train"]
    validation_cases = [case for case in cases if case["split"] == "validation"]
    test_cases = [case for case in cases if case["split"] == "test"]
    input_width = 13
    model = ParticleMLP(input_width, args.hidden) if args.route == "particle_mlp" else DeepSetContext(input_width, args.hidden)
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-6)
    rng = np.random.default_rng(args.seed)
    transitions = [(case, frame) for case in train_cases for frame in range(len(case["time"]) - 1)]
    start = time.perf_counter()
    history = []
    for epoch in range(args.epochs):
        rng.shuffle(transitions)
        losses = []
        model.train()
        for case, frame in transitions:
            count = len(case["position"][frame])
            indices = rng.choice(count, min(args.max_particles, count), replace=False)
            optimizer.zero_grad(set_to_none=True)
            loss = one_step_loss(model, case, frame, indices, device)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(loss.item())
        model.eval()
        val = validation_rmse(model, validation_cases, device)
        history.append({"epoch": epoch + 1, "train_mse": float(np.mean(losses)), "validation_one_step_rmse_over_dp": val})
        print(json.dumps({"route": args.route, "seed": args.seed, **history[-1]}), flush=True)
    training_seconds = time.perf_counter() - start
    model.eval()
    rollout_start = time.perf_counter()
    test_rollouts = {case["case_id"]: rollout(model, case, device) for case in test_cases}
    inference_seconds = time.perf_counter() - rollout_start
    result = {
        "schema_version": 1, "route": args.route, "seed": args.seed,
        "device": str(device), "torch_version": torch.__version__,
        "cuda_visible_device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "epochs": args.epochs, "maximum_particles_per_training_frame": args.max_particles,
        "training_transition_frames": len(transitions),
        "training_seconds": training_seconds, "inference_seconds": inference_seconds,
        "peak_gpu_memory_bytes": int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0,
        "history": history, "test_rollout": test_rollouts,
        "limitations": "tiny heterogeneous development pilot; no boundary geometry input; results are pipeline evidence, not a publishable ranking",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "route": args.route, "seed": args.seed}, args.checkpoint)


if __name__ == "__main__":
    main()
