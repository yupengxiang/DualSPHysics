#!/usr/bin/env python3
"""Core ML baselines: train, profile, autonomous rollout, and evaluation.

The trainer samples only loss centers. Every graph update receives the full
current particle field and the exact two-hop halo needed by those centers.
Normalization statistics are computed from train transitions only, while
validation/test states are read only by the rollout/evaluation commands.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import resource
import sys
import tempfile
import time

import h5py
import numpy as np
import torch

# Support both ``python -m scripts.core_learning`` and direct script paths.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_contract import apply_prediction
from scripts.core_dataset import CoreDataset
from scripts.core_physics import frame_physics
from scripts.core_models import (MODEL_KINDS, AnalyticPredictor, Normalization,
                                  DualIncrementModel, ModelPredictor, node_features, tensors)

TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
PROFILE_SCHEMA = "core.profile.v1"
ROLLOUT_SCHEMA = "core.rollout.v1"
DEFAULT_UPDATES = 32000
DEFAULT_CENTERS = 256
DEFAULT_HIDDEN = 64
DEFAULT_LR = 1e-3
DEFAULT_MAX_NEIGHBORS = 64
ANALYTIC_BASELINES = ("constant_velocity", "known_force")
MILESTONE_UPDATES = (8000, 16000, 24000, 32000)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _default_progress_path(output):
    """Return the live progress sidecar for a training receipt.

    The receipt is intentionally written only after a run has reached its
    requested update count.  A small sidecar gives the scheduler an atomic,
    inspectable heartbeat while the worker is still doing full-field graph
    updates.  Keeping it next to the receipt also makes resumed runs easy to
    identify without adding another campaign-level path convention.
    """
    if output is None:
        return None
    output = Path(output)
    return output.with_name(output.stem + "-progress.json")


def _milestone_evaluation_path(checkpoint_path):
    """Sidecar path used to survive a kill between rollout and main save."""
    checkpoint_path = Path(checkpoint_path)
    return checkpoint_path.with_name(checkpoint_path.stem + ".evaluation.json")


def seed_everything(seed):
    """Seed all generators before constructing a model or optimizer."""
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise ValueError("seed must be an integer")
    seed = int(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    return seed


def capture_rng_state():
    result = {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.get_rng_state(),
    }
    if torch.cuda.is_available():
        result["torch_cuda"] = torch.cuda.get_rng_state_all()
    return result


def restore_rng_state(state):
    if not state:
        return
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"])
    if torch.cuda.is_available() and state.get("torch_cuda") is not None:
        torch.cuda.set_rng_state_all(state["torch_cuda"])


class RunningMoments:
    """Numerically stable streaming mean/variance over final-axis columns."""

    def __init__(self, width):
        self.count = 0
        self.mean = np.zeros(width, dtype=np.float64)
        self.m2 = np.zeros(width, dtype=np.float64)

    def update(self, values):
        values = np.asarray(values, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != len(self.mean) or not np.isfinite(values).all():
            raise ValueError("moment batch must be finite [rows,width]")
        if not len(values):
            return
        count = len(values)
        mean = values.mean(axis=0)
        delta = mean - self.mean
        centered = values - mean
        batch_m2 = np.sum(centered * centered, axis=0)
        total = self.count + count
        self.m2 += batch_m2 + delta * delta * (self.count * count / total if self.count else 0.0)
        self.mean += delta * (count / total)
        self.count = total

    def finish(self, *, minimum_std=1e-6):
        if self.count < 1:
            raise ValueError("cannot normalize an empty train sample")
        variance = np.maximum(self.m2 / max(self.count, 1), 0.0)
        return self.mean.copy(), np.maximum(np.sqrt(variance), minimum_std)


def _transition_indices(dataset, case_ids, maximum, seed):
    transitions = []
    for case_id in case_ids:
        if dataset.record(case_id)["split"] != "train":
            raise ValueError("normalization and training transitions must be train split")
        frames = len(dataset.times(case_id)) - 1
        transitions.extend((case_id, frame) for frame in range(frames))
    if not transitions:
        raise ValueError("train split has no transitions")
    if maximum is None:
        return transitions
    if isinstance(maximum, bool) or int(maximum) < 1:
        raise ValueError("normalization transition bound must be positive")
    maximum = int(maximum)
    if maximum >= len(transitions):
        return transitions
    # Evenly spaced deterministic coverage avoids concentrating statistics in
    # one case while keeping full F3 normalization bounded and reproducible.
    positions = np.linspace(0, len(transitions) - 1, maximum).round().astype(np.int64)
    positions = np.unique(positions)
    return [transitions[int(i)] for i in positions]


def compute_normalization(dataset, *, model_kind="graph_raw", case_ids=None,
                          maximum_transitions=256, seed=0):
    """Compute train-only feature/target statistics for one baseline kind."""
    if model_kind not in MODEL_KINDS:
        raise ValueError(f"unknown model kind {model_kind}")
    case_ids = tuple(case_ids or dataset.case_ids("train"))
    transitions = _transition_indices(dataset, case_ids, maximum_transitions, seed)
    feature_stats, target_stats = RunningMoments(23), RunningMoments(6)
    for case_id, frame in transitions:
        state, known, dt, target = dataset.training_transition(case_id, frame)
        features, _ = node_features(state, known, dt)
        target_array = np.column_stack((target.displacement, target.delta_velocity))
        # The raw six-vector target scale is shared by raw and residual
        # baselines. The residual route subtracts its known-force prior only
        # after this train-only scale has been fixed, preserving fair units.
        feature_stats.update(features)
        target_stats.update(target_array)
    feature_mean, feature_std = feature_stats.finish()
    target_mean, target_std = target_stats.finish()
    return Normalization(feature_mean.astype(np.float32), feature_std.astype(np.float32),
                         target_mean.astype(np.float32), target_std.astype(np.float32))


# Descriptive aliases used by workers and tests.
fit_normalization = compute_normalization


class TransitionSampler:
    """Deterministic train transition/center sampler with resumable state."""

    def __init__(self, dataset, *, case_ids=None, centers_per_update=DEFAULT_CENTERS, seed=0):
        if isinstance(centers_per_update, bool) or int(centers_per_update) < 1:
            raise ValueError("centers_per_update must be positive")
        self.dataset = dataset
        self.case_ids = tuple(case_ids or dataset.case_ids("train"))
        if not self.case_ids:
            raise ValueError("train split has no cases")
        self.transitions = []
        for case_id in self.case_ids:
            if dataset.record(case_id)["split"] != "train":
                raise ValueError("sampler may draw train cases only")
            self.transitions.extend((case_id, frame) for frame in range(len(dataset.times(case_id)) - 1))
        if not self.transitions:
            raise ValueError("train split has no transitions")
        self.centers_per_update = int(centers_per_update)
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.draws = 0

    def sample(self):
        case_id, frame = self.transitions[int(self.rng.integers(len(self.transitions)))]
        state, known, dt, target = self.dataset.training_transition(case_id, frame)
        count = min(self.centers_per_update, state.count)
        centers = self.rng.choice(state.count, count, replace=False).astype(np.int64)
        self.draws += 1
        return case_id, frame, state, known, dt, target, centers

    def state_dict(self):
        return {
            "version": "core.sampler.v1",
            "seed": self.seed,
            "case_ids": list(self.case_ids),
            "centers_per_update": self.centers_per_update,
            "draws": self.draws,
            "rng_state": self.rng.bit_generator.state,
        }

    def load_state_dict(self, state):
        if tuple(state.get("case_ids", ())) != self.case_ids or int(state["centers_per_update"]) != self.centers_per_update:
            raise ValueError("checkpoint sampler does not match current train cases/centers")
        self.rng.bit_generator.state = state["rng_state"]
        self.draws = int(state.get("draws", 0))


class FixedValidationSet:
    """A small, immutable validation transition/center denominator."""

    def __init__(self, dataset, *, maximum_transitions=4, centers=DEFAULT_CENTERS):
        if isinstance(maximum_transitions, bool) or int(maximum_transitions) < 0:
            raise ValueError("validation transition bound must be nonnegative")
        if isinstance(centers, bool) or int(centers) < 1:
            raise ValueError("validation centers must be positive")
        self.dataset = dataset
        rows = []
        for case_id in dataset.case_ids("validation"):
            rows.extend((case_id, frame) for frame in range(len(dataset.times(case_id)) - 1))
        if maximum_transitions and len(rows) > int(maximum_transitions):
            positions = np.linspace(0, len(rows) - 1, int(maximum_transitions)).round().astype(np.int64)
            rows = [rows[int(i)] for i in np.unique(positions)]
        self.rows = tuple(rows)
        self.centers = int(centers)

    def evaluate(self, model, normalization, model_kind, device):
        if not self.rows:
            return {"available": False, "transition_count": 0, "center_count": 0}
        model_was_training = model.training
        model.eval()
        losses = []
        center_count = 0
        try:
            with torch.no_grad():
                for case_id, frame in self.rows:
                    state, known, dt, target = self.dataset.supervised_transition(case_id, frame)
                    args, prior, _ = tensors(state, known, dt, device)
                    args = (normalization.normalize_features(args[0]), *args[1:])
                    count = min(self.centers, state.count)
                    center_count = max(center_count, count)
                    centers = torch.linspace(0, state.count - 1, count, device=device).round().long()
                    prediction = model(*args, centers=centers)
                    target_tensor = _target_tensor(state, known, dt, target, prior,
                                                   model_kind, device, normalization)[centers]
                    losses.append(float(torch.mean((prediction - target_tensor) ** 2).cpu()))
        finally:
            model.train(model_was_training)
        return {
            "available": True, "transition_count": len(self.rows), "center_count": int(center_count),
            "mse": float(np.mean(losses)), "rmse": float(np.sqrt(np.mean(losses))),
            "case_frames": [{"case_id": case_id, "frame": int(frame)} for case_id, frame in self.rows],
        }


def _atomic_torch_save(payload, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        torch.save(payload, temporary)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_training_checkpoint(path, *, model, optimizer, sampler, normalization,
                             update, config, seed, validation=None, history=None,
                             validation_history=None, milestone_checkpoints=None,
                             milestone_evaluations=None, milestone_evaluation_plan=None,
                             milestone_selection=None):
    """Persist model, optimizer, normalization, RNG and sampler atomically."""
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "model_kind": model.kind,
        "hidden": int(model.hidden),
        "seed": int(seed),
        "update": int(update),
        "config": json.loads(canonical(config)),
        "normalization": normalization.as_dict(),
        "model_state": model.state_dict(),
        "state_dict": model.state_dict(),
        "optimizer_state": optimizer.state_dict() if optimizer is not None else None,
        "sampler_state": sampler.state_dict() if sampler is not None else None,
        "rng_state": capture_rng_state(),
        "torch_version": torch.__version__,
        "validation": validation or {},
        # Keep the execution ledger in every resumable checkpoint. A killed
        # worker can therefore continue without silently dropping prior
        # validation rows or registered milestone artifacts.
        "history": list(history or []),
        "validation_history": list(validation_history or []),
        "milestone_checkpoints": list(milestone_checkpoints or []),
        "milestone_evaluations": list(milestone_evaluations or []),
        "milestone_evaluation_plan": list(milestone_evaluation_plan or []),
        "milestone_selection": milestone_selection,
    }
    _atomic_torch_save(payload, path)
    return {"path": str(Path(path)), "sha256": sha256_file(path), "bytes": Path(path).stat().st_size,
            "update": int(update), "schema": CHECKPOINT_SCHEMA}


def load_training_checkpoint(path, *, model=None, optimizer=None, sampler=None,
                             map_location="cpu", restore_rng=True):
    payload = torch.load(Path(path), map_location=map_location, weights_only=False)
    if payload.get("schema") != CHECKPOINT_SCHEMA:
        raise ValueError("unsupported Core checkpoint schema")
    if model is not None:
        if model.kind != payload["model_kind"] or int(model.hidden) != int(payload["hidden"]):
            raise ValueError("checkpoint model configuration mismatch")
        model.load_state_dict(payload.get("model_state", payload["state_dict"]))
    if optimizer is not None and payload.get("optimizer_state") is not None:
        optimizer.load_state_dict(payload["optimizer_state"])
    if sampler is not None and payload.get("sampler_state") is not None:
        sampler.load_state_dict(payload["sampler_state"])
    if restore_rng:
        restore_rng_state(payload.get("rng_state"))
    return payload


def _target_tensor(state, known, dt, target, prior, model_kind, device, normalization):
    target_array = np.column_stack((target.displacement, target.delta_velocity))
    if model_kind == "graph_residual":
        target_array = target_array - prior.detach().cpu().numpy()
    target_tensor = torch.as_tensor(target_array, dtype=torch.float32, device=device)
    return normalization.normalize_target(target_tensor)


def train_model(dataset, *, model_kind="graph_raw", seed=17, updates=DEFAULT_UPDATES,
                centers_per_update=DEFAULT_CENTERS, hidden=DEFAULT_HIDDEN,
                learning_rate=DEFAULT_LR, device="cpu", normalization=None,
                normalization_transitions=256, checkpoint=None, output=None,
                run_id=None, checkpoint_every=8000, resume=None, log_every=1000,
                validation_every=1000, validation_transitions=4,
                validation_centers=DEFAULT_CENTERS, progress_output=None,
                evaluate_milestones=True):
    """Train one complete baseline and return a ``core.training.v1`` receipt."""
    if model_kind not in MODEL_KINDS:
        raise ValueError(f"unknown model kind {model_kind}")
    if isinstance(updates, bool) or int(updates) < 1:
        raise ValueError("updates must be positive")
    if float(learning_rate) <= 0:
        raise ValueError("learning rate must be positive")
    updates, centers_per_update, hidden = int(updates), int(centers_per_update), int(hidden)
    device = torch.device(device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    seed = seed_everything(seed)
    train_cases = dataset.case_ids("train")
    validation_cases = tuple(dataset.case_ids("validation"))
    validation_registry = {case_id: dataset.record(case_id)["family"] for case_id in validation_cases}
    validation_family_counts = Counter(validation_registry.values())
    validation_formal_eligible = (
        len(validation_cases) >= 12 and len(validation_family_counts) >= 3
        and min(validation_family_counts.values(), default=0) >= 4
    )
    if normalization is None:
        normalization = compute_normalization(dataset, model_kind=model_kind,
                                              case_ids=train_cases,
                                              maximum_transitions=normalization_transitions,
                                              seed=seed)
    # Seed is intentionally set immediately before construction on a fresh
    # run, so every requested seed identifies the initial weights exactly.
    model = DualIncrementModel(model_kind, hidden=hidden).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
    sampler = TransitionSampler(dataset, case_ids=train_cases,
                                centers_per_update=centers_per_update, seed=seed)
    fixed_validation = FixedValidationSet(dataset, maximum_transitions=validation_transitions,
                                          centers=validation_centers)
    run_id = run_id or f"{model_kind}-seed{seed}"
    start_update = 0
    history = []
    validation_history = []
    milestone_checkpoints = []
    milestone_evaluations = []
    milestone_evaluation_plan = []
    milestone_selection = None
    milestone_selection_error = None
    if resume is not None:
        payload = load_training_checkpoint(resume, model=model, optimizer=optimizer,
                                           sampler=sampler, map_location=device, restore_rng=True)
        saved_norm = Normalization.from_dict(payload["normalization"])
        if normalization.as_dict() != saved_norm.as_dict():
            raise ValueError("resume normalization differs from current train-only statistics")
        start_update = int(payload["update"])
        if payload["model_kind"] != model_kind or int(payload["seed"]) != seed:
            raise ValueError("resume model/seed differs from requested run")
        if start_update > updates:
            raise ValueError("resume checkpoint is beyond requested update count")
        history = list(payload.get("history", []))
        validation_history = list(payload.get("validation_history", []))
        milestone_checkpoints = list(payload.get("milestone_checkpoints", []))
        milestone_evaluations = list(payload.get("milestone_evaluations", []))
        milestone_evaluation_plan = list(payload.get("milestone_evaluation_plan", []))
        milestone_selection = payload.get("milestone_selection")
        previous_config = payload.get("config", {})
        previous_updates = int(previous_config.get("updates", start_update))
        previous_log_every = max(1, int(previous_config.get("log_every", 1000)))
        previous_validation_every = int(previous_config.get("validation_every", 1000))
        # A bounded canary often logs/validates its terminal update even when
        # that update is not on the formal cadence. If the canary is resumed
        # into a longer run, discard only that segment-terminal row so the
        # combined ledger is byte-for-byte equivalent to an uninterrupted run.
        if previous_updates < updates and previous_updates not in MILESTONE_UPDATES:
            if previous_updates % previous_log_every:
                history = [row for row in history if int(row.get("update", -1)) != previous_updates]
            if previous_validation_every <= 0 or previous_updates % previous_validation_every:
                validation_history = [row for row in validation_history
                                      if int(row.get("update", -1)) != previous_updates]
        # A worker may have been killed after publishing a milestone file but
        # before the following main checkpoint. Reconstruct that self-entry
        # from the resume path so later receipts retain the full ledger.
        if start_update in MILESTONE_UPDATES and not any(
                int(item.get("update", -1)) == start_update for item in milestone_checkpoints):
            resume_path = Path(resume)
            milestone_checkpoints.append({
                "path": str(resume_path), "sha256": sha256_file(resume_path),
                "bytes": resume_path.stat().st_size, "update": start_update,
                "schema": CHECKPOINT_SCHEMA,
            })
        # Older checkpoints predate the persistent enqueue plan. Rebuild it
        # from the already published milestone artifacts on resume.
        planned_updates = {int(item.get("update", -1)) for item in milestone_evaluation_plan}
        for item in milestone_checkpoints:
            update = int(item.get("update", -1))
            if update in MILESTONE_UPDATES and update not in planned_updates:
                milestone_evaluation_plan.append({
                    "update": update, "split": "validation", "status": "pending",
                    "required": True, "qualification_only": not validation_formal_eligible,
                    "formal_eligible": validation_formal_eligible,
                    "validation_case_ids": list(validation_cases),
                    "validation_family_counts": dict(sorted(validation_family_counts.items())),
                    "checkpoint": item,
                })
    config = {
        "model_kind": model_kind, "seed": seed, "updates": updates,
        "centers_per_update": centers_per_update, "hidden": hidden,
        "learning_rate": float(learning_rate), "optimizer": "Adam",
        "radius_over_h": 2.0, "max_neighbors": DEFAULT_MAX_NEIGHBORS,
        "history_states": 1, "normalization_source_split": "train",
        "target_normalization": "raw_dual_increment_train_shared",
        "gradient_clipping": None,
        "log_every": int(log_every), "checkpoint_every": int(checkpoint_every),
        "validation_every": int(validation_every),
        "validation_transition_count": len(fixed_validation.rows),
        "validation_centers": int(validation_centers),
        "validation_case_count": len(validation_cases),
        "validation_family_counts": dict(sorted(validation_family_counts.items())),
        "validation_formal_eligible": validation_formal_eligible,
        "evaluate_milestones": bool(evaluate_milestones),
        "milestone_evaluation_mode": "in_process" if evaluate_milestones else "deferred",
    }
    checkpoint = Path(checkpoint) if checkpoint is not None else Path(f"{run_id}.pt")

    def record_milestone_evaluation(report):
        """Append one update exactly once and close its persistent queue row."""
        update = int(report["update"])
        if any(int(item.get("update", -1)) == update for item in milestone_evaluations):
            return False
        milestone_evaluations.append(report)
        for plan in milestone_evaluation_plan:
            if int(plan.get("update", -1)) == update:
                plan["status"] = "completed"
                plan["evaluation"] = {
                    "update": update,
                    "checkpoint_sha256": report["checkpoint"]["sha256"],
                    "validation_case_count": report["validation_case_count"],
                    "metrics": report["metrics"],
                }
                break
        return True

    def refresh_milestone_selection():
        nonlocal milestone_selection, milestone_selection_error
        milestone_selection, milestone_selection_error = select_completed_milestones(
            milestone_evaluations)

    # A worker can die after publishing a milestone checkpoint but before the
    # following main checkpoint. Resume consumes those durable queue entries
    # before taking another optimizer step. A completed update is recognized
    # by its ledger row, so kill/resume cannot count a rollout twice.
    if evaluate_milestones:
        for milestone in sorted(milestone_checkpoints, key=lambda item: int(item.get("update", -1))):
            update = int(milestone.get("update", -1))
            if update not in MILESTONE_UPDATES:
                continue
            if any(int(item.get("update", -1)) == update for item in milestone_evaluations):
                continue
            sidecar = _milestone_evaluation_path(milestone["path"])
            if sidecar.is_file():
                try:
                    cached = json.loads(sidecar.read_text())
                    if (int(cached.get("update", -1)) == update
                            and cached.get("checkpoint", {}).get("sha256") == milestone.get("sha256")):
                        record_milestone_evaluation(cached)
                        for plan in milestone_evaluation_plan:
                            if int(plan.get("update", -1)) == update:
                                plan["evaluation_path"] = str(sidecar)
                                break
                        continue
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    # A partial sidecar is harmless; the exact checkpoint is
                    # re-evaluated and a fresh atomic sidecar replaces it.
                    pass
            report = evaluate_milestone(dataset, milestone, device=device,
                                        chunk_size=centers_per_update, run_id=run_id)
            record_milestone_evaluation(report)
        refresh_milestone_selection()

    progress_path = (Path(progress_output) if progress_output is not None
                     else _default_progress_path(output))
    started = time.perf_counter()
    formal_milestones = {step for step in MILESTONE_UPDATES if step <= updates}
    model.train()

    def publish_progress(*, status, update, loss_mse=None, case_id=None, frame=None,
                         neighbor_truncation_fraction=None, error=None):
        """Atomically publish the latest inexpensive worker progress record."""
        if progress_path is None:
            return
        record = {
            "schema": "core.training.progress.v1", "run_id": run_id,
            "model_kind": model_kind, "seed": int(seed), "status": status,
            "update": int(update), "requested_updates": int(updates),
            "elapsed_seconds": float(time.perf_counter() - started),
            "device": str(device), "checkpoint": str(checkpoint),
        }
        if loss_mse is not None:
            record["loss_mse"] = float(loss_mse)
        if case_id is not None:
            record["last_case_id"] = str(case_id)
        if frame is not None:
            record["last_frame"] = int(frame)
        if neighbor_truncation_fraction is not None:
            record["neighbor_truncation_fraction"] = float(neighbor_truncation_fraction)
        if error is not None:
            record["error"] = str(error)
        atomic_json(progress_path, record)

    publish_progress(status="running", update=start_update)
    for update in range(start_update + 1, updates + 1):
        case_id, frame, state, known, dt, target, centers = sampler.sample()
        args, prior, diagnostics = tensors(state, known, dt, device)
        if normalization is not None:
            args = (normalization.normalize_features(args[0]), *args[1:])
        centers_t = torch.as_tensor(centers, dtype=torch.long, device=device)
        optimizer.zero_grad(set_to_none=True)
        prediction = model(*args, centers=centers_t)
        target_tensor = _target_tensor(state, known, dt, target, prior, model_kind, device, normalization)[centers_t]
        loss = torch.mean((prediction - target_tensor) ** 2)
        if not torch.isfinite(loss):
            raise FloatingPointError(f"nonfinite training loss at update {update}")
        loss.backward()
        optimizer.step()
        if update == 1 or update % max(1, int(log_every)) == 0 or update == updates:
            history.append({"update": update, "loss_mse": float(loss.detach().cpu()),
                            "case_id": str(case_id), "frame": int(frame),
                            "neighbor_truncation_fraction": diagnostics["neighbor_truncation_fraction"]})
            publish_progress(status="running", update=update,
                             loss_mse=float(loss.detach().cpu()), case_id=case_id,
                             frame=frame,
                             neighbor_truncation_fraction=diagnostics["neighbor_truncation_fraction"])
        validation = None
        if int(validation_every) > 0 and (update % int(validation_every) == 0 or update == updates):
            validation = fixed_validation.evaluate(model, normalization, model_kind, device)
            validation["update"] = update
            validation_history.append(validation)
        if update in formal_milestones:
            suffix = checkpoint.suffix or ".pt"
            milestone_path = checkpoint.with_name(checkpoint.stem + f".step-{update:08d}" + suffix)
            info = save_training_checkpoint(milestone_path, model=model, optimizer=optimizer, sampler=sampler,
                                            normalization=normalization, update=update, config=config, seed=seed,
                                            validation=validation, history=history,
                                            validation_history=validation_history,
                                            milestone_checkpoints=milestone_checkpoints,
                                            milestone_evaluations=milestone_evaluations,
                                            milestone_evaluation_plan=milestone_evaluation_plan,
                                            milestone_selection=milestone_selection)
            milestone_checkpoints.append(info)
            milestone_evaluation_plan.append({
                "update": update, "split": "validation", "status": "pending", "required": True,
                "qualification_only": not validation_formal_eligible,
                "formal_eligible": validation_formal_eligible,
                "validation_case_ids": list(validation_cases),
                "validation_family_counts": dict(sorted(validation_family_counts.items())),
                "checkpoint": info,
            })
            if evaluate_milestones:
                # Evaluate the exact in-memory state that was just published;
                # the checkpoint hash remains the durable identity used by
                # resume and by the later four-checkpoint selector.
                publish_progress(status="milestone_validation", update=update)
                predictor = ModelPredictor(model, device=device,
                                           chunk_size=centers_per_update,
                                           normalization=normalization)
                evaluation = evaluate_milestone(
                    dataset, info, predictor=predictor, device=device,
                    chunk_size=centers_per_update, run_id=run_id,
                )
                evaluation_path = _milestone_evaluation_path(info["path"])
                atomic_json(evaluation_path, evaluation)
                record_milestone_evaluation(evaluation)
                for plan in milestone_evaluation_plan:
                    if int(plan.get("update", -1)) == update:
                        plan["evaluation_path"] = str(evaluation_path)
                        break
                refresh_milestone_selection()
                model.train()
                publish_progress(status="running", update=update)
        if checkpoint is not None and (update == updates or update % max(1, int(checkpoint_every)) == 0):
            save_training_checkpoint(checkpoint, model=model, optimizer=optimizer, sampler=sampler,
                                     normalization=normalization, update=update, config=config, seed=seed,
                                     validation=validation, history=history,
                                     validation_history=validation_history,
                                     milestone_checkpoints=milestone_checkpoints,
                                     milestone_evaluations=milestone_evaluations,
                                     milestone_evaluation_plan=milestone_evaluation_plan,
                                     milestone_selection=milestone_selection)
    elapsed = time.perf_counter() - started
    checkpoint_info = save_training_checkpoint(checkpoint, model=model, optimizer=optimizer, sampler=sampler,
                                               normalization=normalization, update=updates,
                                               config=config, seed=seed,
                                               validation=(validation_history[-1] if validation_history else None),
                                               history=history, validation_history=validation_history,
                                               milestone_checkpoints=milestone_checkpoints,
                                               milestone_evaluations=milestone_evaluations,
                                               milestone_evaluation_plan=milestone_evaluation_plan,
                                               milestone_selection=milestone_selection)
    result = {
        "schema": TRAINING_SCHEMA, "run_id": run_id, "model_kind": model_kind, "seed": seed,
        "device": str(device), "torch_version": torch.__version__, "host": platform.node(),
        "parameter_count": int(sum(p.numel() for p in model.parameters())),
        "completed_updates": updates, "checkpoint_verified": bool(checkpoint_info["sha256"]),
        "checkpoint": checkpoint_info, "normalization": normalization.as_dict(),
        "milestone_updates": [int(item["update"]) for item in milestone_checkpoints],
        "milestone_checkpoints": milestone_checkpoints,
        "milestone_evaluation_plan": milestone_evaluation_plan,
        "milestone_selection": milestone_selection,
        "milestone_selection_error": milestone_selection_error,
        "checkpoints": milestone_checkpoints + [checkpoint_info],
        "sampler": {"case_count": len(train_cases), "transition_count": len(sampler.transitions),
                     "centers_per_update": centers_per_update, "draws": sampler.draws},
        "config": config, "history": history, "validation_history": validation_history,
        "milestone_evaluations": milestone_evaluations,
        "progress_path": str(progress_path) if progress_path is not None else None,
        "wall_seconds": elapsed,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }
    if device.type == "cuda":
        result["peak_gpu_memory_bytes"] = int(torch.cuda.max_memory_allocated(device))
    else:
        result["peak_gpu_memory_bytes"] = 0
    publish_progress(status="completed", update=updates,
                     loss_mse=(history[-1]["loss_mse"] if history else None),
                     case_id=(history[-1].get("case_id") if history else None),
                     frame=(history[-1].get("frame") if history else None),
                     neighbor_truncation_fraction=(history[-1].get("neighbor_truncation_fraction")
                                                   if history else None))
    if output is not None:
        atomic_json(output, result)
    return result


def _build_predictor_from_checkpoint(checkpoint, device, chunk_size=256):
    # Checkpoint evaluation is inference-only; load weights on CPU first so a
    # GPU evaluator does not depend on cross-device state-dict copying.
    payload = load_training_checkpoint(checkpoint, map_location="cpu", restore_rng=False)
    model = DualIncrementModel(payload["model_kind"], hidden=int(payload["hidden"]))
    model.load_state_dict(payload.get("model_state", payload["state_dict"]))
    normalization = Normalization.from_dict(payload["normalization"])
    return ModelPredictor(model, device=device, chunk_size=chunk_size, normalization=normalization), payload


def _build_predictor_from_baseline(baseline):
    """Build a no-training analytic predictor for denominator diagnostics."""
    if baseline not in ANALYTIC_BASELINES:
        raise ValueError(f"unknown analytic baseline {baseline}")
    predictor = AnalyticPredictor(baseline)
    return predictor, {"model_kind": "analytic", "baseline": predictor.kind,
                       "training": False, "checkpoint": None}


def _memory_snapshot():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {"peak_rss_mib": float(usage.ru_maxrss / 1024), "cpu_seconds": float(usage.ru_utime + usage.ru_stime)}
    if torch.cuda.is_available():
        result["peak_gpu_memory_bytes"] = int(torch.cuda.max_memory_allocated())
    return result


def profile_case(dataset, case_id, *, model_kind="graph_raw", steps=10, hidden=DEFAULT_HIDDEN,
                 device="cpu", chunk_size=256, seed=17):
    """Run bounded inference timing on one complete current particle field."""
    if int(steps) < 1:
        raise ValueError("profile steps must be positive")
    if torch.device(device).type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    seed_everything(seed)
    if torch.device(device).type == "cuda":
        torch.cuda.reset_peak_memory_stats(torch.device(device))
    model = DualIncrementModel(model_kind, hidden=hidden)
    predictor = ModelPredictor(model, device=device, chunk_size=chunk_size)
    times = dataset.times(case_id)
    current = dataset.read_state(case_id, 0)
    known = dataset.known_inputs(case_id)
    measurements = []
    for step in range(min(int(steps), len(times) - 1)):
        started = time.perf_counter()
        prediction = predictor.predict_step(current, known, float(times[step + 1] - times[step]))
        current = apply_prediction(current, prediction, float(times[step + 1] - times[step]))
        measurements.append(time.perf_counter() - started)
    memory = _memory_snapshot()
    return {
        "schema": PROFILE_SCHEMA, "case_id": case_id, "model_kind": model_kind,
        "seed": int(seed), "device": str(device), "hidden": int(hidden),
        "particles": current.count, "steps_requested": int(steps), "steps_completed": len(measurements),
        "step_seconds": measurements, "mean_step_seconds": float(np.mean(measurements)),
        "p50_step_seconds": float(np.percentile(measurements, 50)),
        "p95_step_seconds": float(np.percentile(measurements, 95)),
        "diagnostics": {"full_field": True, "radius_over_h": 2.0, "max_neighbors": DEFAULT_MAX_NEIGHBORS,
                        "loss_centers": None, "autonomous_state_feedback": True},
        "resource": memory,
    }


def rollout_case(dataset, case_id, predictor, *, maximum_steps=None, trajectory_output=None):
    """Autonomously roll from frame zero; references are read only for scoring."""
    times = dataset.times(case_id)
    known = dataset.known_inputs(case_id)
    current = dataset.read_state(case_id, 0)
    total_steps = len(times) - 1 if maximum_steps is None else min(int(maximum_steps), len(times) - 1)
    if total_steps < 1:
        raise ValueError("rollout requires at least one transition")
    position_rmse = [None] * total_steps
    velocity_rmse = [None] * total_steps
    position_ade = [None] * total_steps
    velocity_ade = [None] * total_steps
    position_sq_sum = velocity_sq_sum = 0.0
    position_norm_sum = velocity_norm_sum = 0.0
    position_component_count = velocity_component_count = 0
    position_fde = velocity_fde = None
    executed = 0
    attempted = False
    failure_category = None
    first_failure_frame = None
    physics_frames = [None] * total_steps
    trajectory = None
    if trajectory_output is not None:
        trajectory_path = Path(trajectory_output)
        trajectory_path.parent.mkdir(parents=True, exist_ok=True)
        trajectory = h5py.File(trajectory_path, "w")
        trajectory.attrs.update(
            schema_version=1, state_schema="core.state.native_velocity.v1",
            velocity_semantics="native saved numerical velocity",
            future_state_inputs=False, autonomous_prediction=True,
            identity_semantics="particle_zone,particle_id",
        )
        trajectory.create_dataset("time", data=times[: total_steps + 1])
        # Unexecuted frames stay NaN/invalid after a failure.  They are never
        # silently mistaken for a predicted zero state by downstream material
        # or physics readers.
        trajectory.create_dataset("position", shape=(total_steps + 1, current.count, 3),
                                  dtype="f4", fillvalue=np.nan)
        trajectory.create_dataset("velocity", shape=(total_steps + 1, current.count, 3),
                                  dtype="f4", fillvalue=np.nan)
        trajectory.create_dataset("particle_id", data=current.particle_id)
        trajectory.create_dataset("particle_zone", data=current.particle_zone)
        trajectory.create_dataset("mass", data=current.mass)
        trajectory.create_dataset("valid", shape=(total_steps + 1, current.count),
                                  dtype="bool", fillvalue=False)
        trajectory["position"][0] = current.position
        trajectory["velocity"][0] = current.velocity
        trajectory["valid"][0] = current.valid
    try:
        for step in range(total_steps):
            attempted = True
            try:
                dt = float(times[step + 1] - times[step])
                previous = current
                prediction = predictor.predict_step(previous, known, dt)
                if (not np.isfinite(prediction.displacement).all()
                        or not np.isfinite(prediction.delta_velocity).all()):
                    raise FloatingPointError("nonfinite model prediction")
                current = apply_prediction(previous, prediction, dt)
            except FloatingPointError:
                failure_category, first_failure_frame = "nonfinite_prediction", step + 1
                break
            except ValueError as error:
                failure_category, first_failure_frame = "invalid_model_state", step + 1
                break
            except Exception:
                failure_category, first_failure_frame = "model_execution_error", step + 1
                break
            try:
                reference = dataset.read_state(case_id, step + 1)
            except Exception:
                failure_category, first_failure_frame = "reference_read_error", step + 1
                break
            position_error = current.position - reference.position
            velocity_error = current.velocity - reference.velocity
            if not np.isfinite(position_error).all() or not np.isfinite(velocity_error).all():
                failure_category, first_failure_frame = "nonfinite_error", step + 1
                break
            try:
                physics_frames[step] = frame_physics(previous, current, reference, known.geometry)
            except Exception:
                failure_category, first_failure_frame = "physics_diagnostic_error", step + 1
                break
            position_norm = np.linalg.norm(position_error, axis=-1)
            velocity_norm = np.linalg.norm(velocity_error, axis=-1)
            position_rmse[step] = float(np.sqrt(np.mean(position_error ** 2)))
            velocity_rmse[step] = float(np.sqrt(np.mean(velocity_error ** 2)))
            position_ade[step] = float(np.mean(position_norm))
            velocity_ade[step] = float(np.mean(velocity_norm))
            position_sq_sum += float(np.sum(position_error ** 2))
            velocity_sq_sum += float(np.sum(velocity_error ** 2))
            position_norm_sum += float(np.sum(position_norm))
            velocity_norm_sum += float(np.sum(velocity_norm))
            position_component_count += int(position_error.size)
            velocity_component_count += int(velocity_error.size)
            position_fde, velocity_fde = position_ade[step], velocity_ade[step]
            executed += 1
            if trajectory is not None:
                trajectory["position"][step + 1] = current.position
                trajectory["velocity"][step + 1] = current.velocity
                trajectory["valid"][step + 1] = current.valid
    finally:
        if trajectory is not None:
            trajectory.close()
    if executed == total_steps:
        failure_category = None
        first_failure_frame = None
    position_rmse_scalar = (float(np.sqrt(position_sq_sum / position_component_count))
                            if position_component_count else None)
    velocity_rmse_scalar = (float(np.sqrt(velocity_sq_sum / velocity_component_count))
                            if velocity_component_count else None)
    completed_physics = [row for row in physics_frames if row is not None]
    wall_rows = [row["wall_chord"] for row in completed_physics]
    wall_counts = [row["particle_count"] for row in wall_rows
                   if isinstance(row.get("particle_count"), (int, np.integer))]
    wall_masses = [row["mass_kg"] for row in wall_rows
                   if isinstance(row.get("mass_kg"), (int, float, np.integer, np.floating))]
    physics_summary = {
        "expected_frames": total_steps,
        "completed_frames": len(completed_physics),
        "mass_error_abs_max_kg": (max(abs(row["mass_error_kg"]) for row in completed_physics)
                                   if completed_physics else None),
        "kinetic_energy_error_abs_max_j": (
            max(abs(row["kinetic_energy_error_j"]) for row in completed_physics)
            if completed_physics else None),
        "validity_mismatch_frames": sum(row["validity_mismatch_count"] > 0 for row in completed_physics),
        "changed_particle_mass_frames": sum(row["changed_particle_mass_count"] > 0 for row in completed_physics),
        "wall_chord_statuses": sorted({row["status"] for row in wall_rows}),
        "wall_chord_particle_count": int(sum(wall_counts)) if wall_counts else 0,
        "wall_chord_mass_kg": float(sum(wall_masses)) if wall_masses else 0.0,
    }
    length_m, speed_mps = _characteristic_scales(known)
    return {
        "schema": ROLLOUT_SCHEMA, "case_id": case_id, "frames_predicted": executed,
        "frames_expected": total_steps, "frames_executed": executed,
        "expected_frames": total_steps, "executed": bool(attempted),
        "particles": current.count, "position_rmse_m": position_rmse_scalar,
        "position_ade_m": (float(position_norm_sum / executed / current.count) if executed else None),
        "position_fde_m": position_fde,
        "velocity_rmse_mps": velocity_rmse_scalar,
        "velocity_ade_mps": (float(velocity_norm_sum / executed / current.count) if executed else None),
        "velocity_fde_mps": velocity_fde,
        "length_m": length_m, "speed_mps": speed_mps,
        # Frame arrays deliberately retain the expected denominator after an
        # early failure; missing frames are explicit nulls.
        "position_rmse": position_rmse, "velocity_rmse": velocity_rmse,
        "position_ade": position_ade, "velocity_ade": velocity_ade,
        "physics": {"frames": physics_frames, "summary": physics_summary},
        "failure_category": failure_category, "first_failure_frame": first_failure_frame,
        "trajectory_output": str(trajectory_output) if trajectory_output is not None else None,
        "autonomous": True, "future_state_inputs": False,
    }


def _characteristic_scales(known):
    vertices = known.geometry.triangles.reshape(-1, 3)
    length_m = max(float(np.ptp(vertices, axis=0).max()) if len(vertices)
                   else float(known.numerics["dp_m"]), float(known.numerics["dp_m"]))
    gravity = np.asarray(known.physics.get("gravity_mps2", [0.0, 0.0, -9.81]), dtype=float)
    gravity_mps2 = float(np.linalg.norm(gravity))
    if not np.isfinite(gravity_mps2) or gravity_mps2 <= 0:
        raise ValueError("known gravity must have a positive finite magnitude")
    return length_m, float(np.sqrt(gravity_mps2 * length_m))


def _checkpoint_reference(item):
    if isinstance(item, (str, Path)):
        return {"path": str(item)}
    if isinstance(item, dict) and isinstance(item.get("path"), (str, Path)):
        return dict(item)
    raise ValueError("checkpoint references require a path")


def checkpoint_refs_from_receipt(receipt):
    """Extract exactly one hashed formal milestone checkpoint per update."""
    if isinstance(receipt, (str, Path)):
        receipt = json.loads(Path(receipt).read_text())
    rows = receipt.get("checkpoints") if isinstance(receipt, dict) else None
    if not isinstance(rows, list):
        raise ValueError("training receipt has no checkpoint ledger")
    selected = []
    for update in MILESTONE_UPDATES:
        matches = [row for row in rows if int(row.get("update", -1)) == update]
        # The final update can appear once as a milestone and once as the
        # ordinary final checkpoint. Prefer the explicit step-tagged artifact.
        tagged = [row for row in matches if f"step-{update:08d}" in str(row.get("path", ""))]
        matches = tagged or matches
        if len(matches) != 1:
            raise ValueError(f"training receipt must contain one milestone checkpoint at update {update}")
        selected.append(_checkpoint_reference(matches[0]))
    return selected


def _failed_rollout_receipt(dataset, case_id, error):
    """Make setup failures scoreable without dropping their frame denominator."""
    times = dataset.times(case_id)
    known = dataset.known_inputs(case_id)
    length_m, speed_mps = _characteristic_scales(known)
    expected = max(0, len(times) - 1)
    return {
        "schema": ROLLOUT_SCHEMA, "case_id": case_id,
        "frames_predicted": 0, "frames_expected": expected, "frames_executed": 0,
        "expected_frames": expected, "executed": False, "particles": None,
        "position_rmse": [None] * expected, "velocity_rmse": [None] * expected,
        "position_ade": [None] * expected, "velocity_ade": [None] * expected,
        "length_m": length_m, "speed_mps": speed_mps,
        "failure_category": "rollout_setup_error", "first_failure_frame": 1 if expected else None,
        "failure_detail": f"{type(error).__name__}: {error}",
        "physics": {"frames": [None] * expected,
                    "summary": {"expected_frames": expected, "completed_frames": 0}},
        "autonomous": True, "future_state_inputs": False,
    }


def evaluate_milestone(dataset, checkpoint, *, predictor=None, device="cpu",
                       chunk_size=DEFAULT_CENTERS, run_id=None):
    """Evaluate one saved milestone over every registered validation case.

    This is the per-milestone operation used by ``train_model``.  It keeps the
    full validation denominator and returns a durable report even when an
    individual autonomous rollout fails.  ``evaluate_checkpoints`` later
    consumes these four reports through the frozen checkpoint selector.
    """
    from scripts.core_evaluation import PROTOCOL, aggregate_cases, score_case

    ref = _checkpoint_reference(checkpoint)
    path = Path(ref["path"])
    observed_hash = sha256_file(path)
    expected_hash = ref.get("sha256")
    if expected_hash and expected_hash != observed_hash:
        raise ValueError(f"checkpoint hash mismatch: {path}")
    payload = None
    if predictor is None:
        predictor, payload = _build_predictor_from_checkpoint(path, device, chunk_size)
    validation_cases = tuple(dataset.case_ids("validation"))
    if not validation_cases:
        raise ValueError("milestone evaluation requires validation cases")
    registry = {case_id: dataset.record(case_id)["family"] for case_id in validation_cases}
    family_counts = Counter(registry.values())
    formal_eligible = (
        len(validation_cases) >= 12 and len(family_counts) >= 3
        and min(family_counts.values(), default=0) >= 4
    )
    fixed_denominator = {}
    for case_id in validation_cases:
        known = dataset.known_inputs(case_id)
        length_m, speed_mps = _characteristic_scales(known)
        fixed_denominator[case_id] = {
            "expected_frames": len(dataset.times(case_id)) - 1,
            "length_m": length_m, "speed_mps": speed_mps,
        }
    case_rows, scores = {}, {}
    for case_id in validation_cases:
        try:
            rollout = rollout_case(dataset, case_id, predictor)
        except Exception as error:
            rollout = _failed_rollout_receipt(dataset, case_id, error)
        denominator = fixed_denominator[case_id]
        score = score_case(
            rollout["position_rmse"], rollout["velocity_rmse"],
            expected_frames=denominator["expected_frames"],
            length_m=denominator["length_m"], speed_mps=denominator["speed_mps"],
            executed=rollout["executed"], failure_category=rollout.get("failure_category"),
        )
        scores[case_id] = score
        case_rows[case_id] = {"score": score, "rollout": rollout}
    checkpoint_info = {
        "path": str(path), "sha256": observed_hash, "bytes": path.stat().st_size,
        "update": int(payload["update"] if payload is not None else ref.get("update", -1)),
        "schema": CHECKPOINT_SCHEMA, "checkpoint_verified": True,
    }
    if checkpoint_info["update"] < 0:
        raise ValueError("milestone checkpoint requires an update number")
    model_kind = (payload.get("model_kind") if payload is not None else
                  getattr(getattr(predictor, "model", None), "kind", None))
    seed = payload.get("seed") if payload is not None else None
    hidden = (int(payload["hidden"]) if payload is not None else
              int(getattr(getattr(predictor, "model", None), "hidden", 0)))
    return {
        "schema": "core.milestone_evaluation.v1", "run_id": run_id,
        "update": checkpoint_info["update"], "split": "validation",
        "test_included": False, "qualification_only": not formal_eligible,
        "formal_eligible": formal_eligible,
        "validation_case_count": len(validation_cases),
        "validation_family_counts": dict(sorted(family_counts.items())),
        "protocol": PROTOCOL, "fixed_denominator": fixed_denominator,
        "family_registry": registry, "checkpoint": checkpoint_info,
        "model_kind": model_kind, "seed": seed, "hidden": hidden,
        "metrics": aggregate_cases(registry, scores),
        "case_count": len(case_rows), "cases": case_rows,
        "autonomous": True, "future_state_inputs": False,
    }


def select_completed_milestones(evaluations):
    """Select the formal checkpoint only after all four reports are present."""
    from scripts.core_evaluation import PROTOCOL, select_checkpoint

    candidates = [item for item in evaluations
                  if int(item.get("update", -1)) in PROTOCOL["eligible_checkpoint_updates"]]
    if sorted(int(item.get("update", -1)) for item in candidates) != PROTOCOL["eligible_checkpoint_updates"]:
        return None, "four registered milestone evaluations are not complete"
    if not all(item.get("formal_eligible", False) for item in candidates):
        return None, "milestone evaluation is qualification-only; formal selection is withheld"
    try:
        selected = select_checkpoint(candidates)
    except ValueError as error:
        return None, str(error)
    return {
        "update": int(selected["update"]),
        "checkpoint": selected["checkpoint"],
        "metrics": selected["metrics"],
        "split": "validation",
    }, None


def evaluate_checkpoints(dataset, checkpoints, *, device="cpu", chunk_size=DEFAULT_CENTERS,
                         run_id=None, qualification_only=False):
    """Roll every formal checkpoint over every validation case and select one.

    This is deliberately a validation-only operation. The registered scoring
    module supplies the fixed denominator and refuses incomplete checkpoint
    sets; no test case is accepted by this interface.
    """
    from scripts.core_evaluation import PROTOCOL, aggregate_cases, score_case, select_checkpoint

    refs = [_checkpoint_reference(item) for item in checkpoints]
    if len(refs) != len(MILESTONE_UPDATES):
        raise ValueError("formal checkpoint evaluation requires four milestone checkpoints")
    validation_cases = tuple(dataset.case_ids("validation"))
    if not validation_cases:
        raise ValueError("formal checkpoint evaluation requires validation cases")
    registry = {case_id: dataset.record(case_id)["family"] for case_id in validation_cases}
    family_counts = Counter(registry.values())
    if not qualification_only:
        if len(validation_cases) < 12 or len(family_counts) < 3 or min(family_counts.values()) < 4:
            raise ValueError(
                "formal Core evaluation requires at least 3 families with 4 validation cases each; "
                "use qualification_only=True for a diagnostic fixture")
    physical_case_ids = {case_id: dataset.record(case_id)["physical_case_id"] for case_id in validation_cases}
    fixed_denominator = {}
    for case_id in validation_cases:
        known = dataset.known_inputs(case_id)
        length_m, speed_mps = _characteristic_scales(known)
        fixed_denominator[case_id] = {
            "expected_frames": len(dataset.times(case_id)) - 1,
            "length_m": length_m, "speed_mps": speed_mps,
        }

    candidates = []
    model_identity = None
    for ref in refs:
        path = Path(ref["path"])
        observed_hash = sha256_file(path)
        expected_hash = ref.get("sha256")
        if expected_hash and expected_hash != observed_hash:
            raise ValueError(f"checkpoint hash mismatch: {path}")
        predictor, payload = _build_predictor_from_checkpoint(path, device, chunk_size)
        identity = (payload.get("model_kind"), int(payload.get("seed", -1)), int(payload["hidden"]))
        if model_identity is None:
            model_identity = identity
        elif identity != model_identity:
            raise ValueError("formal checkpoints do not belong to one training run")
        case_rows, scores = {}, {}
        for case_id in validation_cases:
            try:
                rollout = rollout_case(dataset, case_id, predictor)
            except Exception as error:
                rollout = _failed_rollout_receipt(dataset, case_id, error)
            denominator = fixed_denominator[case_id]
            score = score_case(
                rollout["position_rmse"], rollout["velocity_rmse"],
                expected_frames=denominator["expected_frames"],
                length_m=denominator["length_m"], speed_mps=denominator["speed_mps"],
                executed=rollout["executed"], failure_category=rollout.get("failure_category"),
            )
            scores[case_id] = score
            case_rows[case_id] = {"score": score, "rollout": rollout}
        metrics = aggregate_cases(registry, scores)
        checkpoint_info = {
            "path": str(path), "sha256": observed_hash, "bytes": path.stat().st_size,
            "update": int(payload["update"]), "schema": CHECKPOINT_SCHEMA,
            "checkpoint_verified": True,
        }
        candidates.append({
            "update": int(payload["update"]), "split": "validation", "metrics": metrics,
            "checkpoint": checkpoint_info, "case_count": len(case_rows), "cases": case_rows,
        })

    selection = None
    selection_error = None
    try:
        chosen = select_checkpoint(candidates)
        selection = {
            "update": chosen["update"], "checkpoint": chosen["checkpoint"],
            "metrics": chosen["metrics"], "split": "validation",
        }
    except ValueError as error:
        selection_error = str(error)
    return {
        "schema": "core.checkpoint_evaluation.v1",
        "run_id": run_id,
        "model_kind": model_identity[0] if model_identity else None,
        "seed": model_identity[1] if model_identity else None,
        "hidden": model_identity[2] if model_identity else None,
        "split": "validation", "test_included": False,
        "qualification_only": bool(qualification_only),
        "formal_eligible": not bool(qualification_only),
        "validation_case_count": len(validation_cases),
        "validation_family_counts": dict(sorted(family_counts.items())),
        "protocol": PROTOCOL, "fixed_denominator": fixed_denominator,
        "physical_case_ids": physical_case_ids, "family_registry": registry,
        "checkpoints": candidates, "checkpoint_count": len(candidates),
        "selection": selection, "selection_error": selection_error,
        "autonomous": True, "future_state_inputs": False,
    }


def _dataset(args):
    # F1/F4 production registrations carry CFD preparation metadata around
    # trajectories.  Keep the regular F3 reader as the fast path while letting
    # the dedicated adapter normalize those source records before training or
    # evaluation opens any HDF5 handle.
    try:
        from scripts.core_cfd_dataset import open_dataset
    except ImportError:
        open_dataset = None
    if open_dataset is not None:
        return open_dataset(args.manifest, args.data_root)
    return CoreDataset(args.manifest, args.data_root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--manifest", type=Path, required=True)
    train.add_argument("--data-root", type=Path, required=True)
    train.add_argument("--model", "--model-kind", dest="model_kind", choices=MODEL_KINDS, required=True)
    train.add_argument("--seed", type=int, required=True)
    train.add_argument("--updates", type=int, default=DEFAULT_UPDATES)
    train.add_argument("--centers", "--centers-per-update", type=int, default=DEFAULT_CENTERS)
    train.add_argument("--hidden", type=int, default=DEFAULT_HIDDEN)
    train.add_argument("--learning-rate", type=float, default=DEFAULT_LR)
    train.add_argument("--normalization-transitions", type=int, default=256)
    train.add_argument("--checkpoint", type=Path)
    train.add_argument("--resume", type=Path)
    train.add_argument("--run-id")
    train.add_argument("--checkpoint-every", type=int, default=8000)
    train.add_argument("--log-every", type=int, default=1000)
    train.add_argument("--validation-every", type=int, default=1000)
    train.add_argument("--validation-transitions", type=int, default=4)
    train.add_argument("--validation-centers", type=int, default=DEFAULT_CENTERS)
    train.add_argument("--device", default="cpu")
    train.add_argument("--evaluate-milestones", dest="evaluate_milestones", action="store_true",
                       default=True,
                       help="roll every validation case at each 8/16/24/32k checkpoint")
    train.add_argument("--no-evaluate-milestones", dest="evaluate_milestones", action="store_false",
                       help="defer milestone rollouts to a scheduler consumer")
    train.add_argument("--progress-output", type=Path,
                       help="atomic live progress sidecar (defaults beside --output)")
    train.add_argument("--output", type=Path, required=True)

    profile = sub.add_parser("profile")
    profile.add_argument("--manifest", type=Path, required=True)
    profile.add_argument("--data-root", type=Path, required=True)
    profile.add_argument("--case-id", "--case", required=True)
    profile.add_argument("--model", "--model-kind", dest="model_kind", choices=MODEL_KINDS, default="graph_raw")
    profile.add_argument("--seed", type=int, default=17)
    profile.add_argument("--steps", type=int, default=10)
    profile.add_argument("--hidden", type=int, default=DEFAULT_HIDDEN)
    profile.add_argument("--chunk-size", type=int, default=DEFAULT_CENTERS)
    profile.add_argument("--device", default="cpu")
    profile.add_argument("--output", type=Path, required=True)

    for name in ("rollout", "evaluate"):
        command = sub.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--data-root", type=Path, required=True)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--checkpoint", type=Path)
        source.add_argument("--baseline", choices=ANALYTIC_BASELINES,
                            help="run a no-training analytic baseline")
        command.add_argument("--case-id", "--case", action="append")
        command.add_argument("--split", choices=("train", "validation", "test", "id_test", "ood_test"), default="test")
        command.add_argument("--maximum-steps", "--max-steps", type=int)
        command.add_argument("--chunk-size", type=int, default=DEFAULT_CENTERS)
        command.add_argument("--device", default="cpu")
        command.add_argument("--trajectory-output", type=Path)
        command.add_argument("--trajectory-output-dir", type=Path,
                             help="write one complete public-State HDF5 per selected case")
        command.add_argument("--output", type=Path, required=True)

    checkpoint_eval = sub.add_parser("evaluate-checkpoints")
    checkpoint_eval.add_argument("--manifest", type=Path, required=True)
    checkpoint_eval.add_argument("--data-root", type=Path, required=True)
    checkpoint_source = checkpoint_eval.add_mutually_exclusive_group(required=True)
    checkpoint_source.add_argument("--checkpoint", type=Path, action="append",
                                  help="repeat exactly four times for 8/16/24/32k milestones")
    checkpoint_source.add_argument("--training-receipt", type=Path,
                                  help="read the four hashed milestone paths from a training receipt")
    checkpoint_eval.add_argument("--run-id")
    checkpoint_eval.add_argument("--qualification-only", action="store_true",
                                help="allow a small non-formal validation fixture; never trains or uses test cases")
    checkpoint_eval.add_argument("--chunk-size", type=int, default=DEFAULT_CENTERS)
    checkpoint_eval.add_argument("--device", default="cpu")
    checkpoint_eval.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "train":
        if args.checkpoint is None:
            args.checkpoint = args.output.with_suffix(".pt")
        with _dataset(args) as dataset:
            result = train_model(dataset, model_kind=args.model_kind, seed=args.seed, updates=args.updates,
                                 centers_per_update=args.centers, hidden=args.hidden,
                                 learning_rate=args.learning_rate, device=args.device,
                                 normalization_transitions=args.normalization_transitions,
                                 checkpoint=args.checkpoint, output=args.output, run_id=args.run_id,
                                 checkpoint_every=args.checkpoint_every, resume=args.resume, log_every=args.log_every,
                                 validation_every=args.validation_every,
                                 validation_transitions=args.validation_transitions,
                                 validation_centers=args.validation_centers,
                                 progress_output=args.progress_output,
                                 evaluate_milestones=args.evaluate_milestones)
    elif args.command == "profile":
        with _dataset(args) as dataset:
            result = profile_case(dataset, args.case_id, model_kind=args.model_kind, steps=args.steps,
                                  hidden=args.hidden, device=args.device, chunk_size=args.chunk_size, seed=args.seed)
        atomic_json(args.output, result)
    elif args.command == "evaluate-checkpoints":
        refs = (checkpoint_refs_from_receipt(args.training_receipt)
                if args.training_receipt is not None else args.checkpoint)
        with _dataset(args) as dataset:
            result = evaluate_checkpoints(dataset, refs, device=args.device,
                                          chunk_size=args.chunk_size, run_id=args.run_id,
                                          qualification_only=args.qualification_only)
        atomic_json(args.output, result)
    else:
        with _dataset(args) as dataset:
            if args.checkpoint is not None:
                predictor, payload = _build_predictor_from_checkpoint(args.checkpoint, args.device, args.chunk_size)
                source_checkpoint = str(args.checkpoint)
            else:
                predictor, payload = _build_predictor_from_baseline(args.baseline)
                source_checkpoint = None
            case_ids = args.case_id or dataset.case_ids(args.split)
            if not case_ids:
                raise ValueError("no rollout cases selected")
            if args.trajectory_output is not None and args.trajectory_output_dir is not None:
                raise ValueError("--trajectory-output and --trajectory-output-dir are mutually exclusive")
            if args.trajectory_output is not None and len(case_ids) != 1:
                raise ValueError("--trajectory-output requires exactly one case; use --trajectory-output-dir for many")

            def case_trajectory_path(case_id):
                if args.trajectory_output_dir is not None:
                    args.trajectory_output_dir.mkdir(parents=True, exist_ok=True)
                    safe_case_id = "".join(char if (char.isalnum() or char in "-_.") else "_"
                                            for char in str(case_id))
                    return args.trajectory_output_dir / f"{safe_case_id}.h5"
                return args.trajectory_output

            results = {case_id: rollout_case(dataset, case_id, predictor,
                                              maximum_steps=args.maximum_steps,
                                              trajectory_output=case_trajectory_path(case_id))
                       for case_id in case_ids}
            result = {"schema": "core.evaluation.v1" if args.command == "evaluate" else ROLLOUT_SCHEMA,
                      "model_kind": payload["model_kind"], "checkpoint": source_checkpoint,
                      "baseline": payload.get("baseline"), "training": payload.get("training", True),
                      "case_count": len(results), "cases": results,
                      "autonomous": True, "future_state_inputs": False}
        atomic_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("cases", "history", "checkpoints")}, indent=2))
    if args.command == "evaluate-checkpoints" and result.get("selection") is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
