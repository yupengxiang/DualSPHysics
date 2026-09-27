#!/usr/bin/env python3
"""Diagnostic F3 graph-raw training-stability candidate.

This module is intentionally isolated from ``core_learning.py``.  It reuses
the public Core dataset/model/training building blocks and adds exactly one
optional operation between ``loss.backward()`` and ``optimizer.step()``:
global L2 gradient-norm clipping.  ``gradient_clip_norm=None`` follows the
same update order as the baseline and is the default.

The candidate is diagnostic-only.  It never edits a manifest, registry,
ledger, denominator, gate, or production HDF5, and its bounded CLI refuses a
formal manifest and requires an explicit maximum evaluation horizon.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path
import resource
import time

import numpy as np
import torch

# Support both ``python -m scripts...`` and direct script paths.
if __package__ in (None, ""):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_dataset import CoreDataset
from scripts.core_learning import (TransitionSampler, atomic_json,
                                    compute_normalization, evaluate,
                                    load_training_checkpoint,
                                    model_parameter_digest, save_training_checkpoint,
                                    seed_everything, sha256_file)
from scripts.core_models import DualIncrementModel, ModelPredictor, Normalization, tensors
from scripts.f3_rollout_metric_summarizer_v1 import summarize_evaluation


SCHEMA = "core.f3.long_horizon_training_candidate.v1"
TRAINING_SCHEMA = "core.f3.long_horizon_training_candidate.training.v1"
CANDIDATE_ID = "graph_raw_global_gradient_clip_norm"
DEFAULT_GRADIENT_CLIP_NORM = None
DEFAULT_MODEL_KIND = "graph_raw"
DEFAULT_UPDATES = 500
DEFAULT_CENTERS = 256
DEFAULT_HIDDEN = 8
DEFAULT_LEARNING_RATE = 1e-3
DEFAULT_NORMALIZATION_TRANSITIONS = 16
DEFAULT_MAX_NEIGHBORS = 192
DEFAULT_MAXIMUM_STEPS = 50


def canonical_json(value) -> str:
    """Serialize a receipt payload with the repository's stable JSON style."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _strict_positive_int(value, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    value = int(value)
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def validate_gradient_clip_norm(value):
    """Validate the sole candidate knob; ``None`` means baseline behavior."""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError("gradient_clip_norm must be a positive finite number or None")
    value = float(value)
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError("gradient_clip_norm must be a positive finite number or None")
    return value


def _current_gradient_norm(parameters) -> float:
    """Return the finite global L2 norm of currently populated gradients."""
    squared = None
    for parameter in parameters:
        gradient = parameter.grad
        if gradient is None:
            continue
        value = torch.sum(gradient.detach() * gradient.detach())
        squared = value if squared is None else squared + value
    if squared is None:
        return 0.0
    norm = torch.sqrt(squared)
    result = float(norm.detach().cpu())
    if not np.isfinite(result):
        raise FloatingPointError("nonfinite gradient norm")
    return result


def clip_gradients(model, max_norm: float) -> dict:
    """Clip all model gradients once and return auditable pre/post norms."""
    max_norm = validate_gradient_clip_norm(max_norm)
    if max_norm is None:
        raise ValueError("clip_gradients requires an enabled clipping bound")
    pre_clip = float(torch.nn.utils.clip_grad_norm_(
        model.parameters(), max_norm=max_norm, error_if_nonfinite=True))
    if not np.isfinite(pre_clip):
        raise FloatingPointError("nonfinite pre-clipping gradient norm")
    post_clip = _current_gradient_norm(model.parameters())
    return {
        "pre_clip_l2": pre_clip,
        "post_clip_l2": post_clip,
        "clipped": bool(pre_clip > max_norm),
        "max_norm": max_norm,
    }


def _raw_target_tensor(target, normalization: Normalization, device):
    target_array = np.column_stack((target.displacement, target.delta_velocity))
    target_tensor = torch.as_tensor(target_array, dtype=torch.float32, device=device)
    return normalization.normalize_target(target_tensor)


def _publish_progress(path: Path | None, *, status: str, update: int,
                      requested_updates: int, started: float, device: str,
                      checkpoint: Path, loss_mse: float | None = None,
                      case_id: str | None = None, frame: int | None = None,
                      error: str | None = None) -> None:
    if path is None:
        return
    payload = {
        "schema": "core.f3.long_horizon_training_candidate.progress.v1",
        "status": status,
        "update": int(update),
        "requested_updates": int(requested_updates),
        "elapsed_seconds": float(time.perf_counter() - started),
        "device": str(device),
        "checkpoint": str(checkpoint),
    }
    if loss_mse is not None:
        payload["loss_mse"] = float(loss_mse)
    if case_id is not None:
        payload["last_case_id"] = str(case_id)
    if frame is not None:
        payload["last_frame"] = int(frame)
    if error is not None:
        payload["error"] = str(error)
    atomic_json(path, payload)


def train_candidate(dataset, *, model_kind=DEFAULT_MODEL_KIND, seed=17,
                    updates=DEFAULT_UPDATES, centers_per_update=DEFAULT_CENTERS,
                    hidden=DEFAULT_HIDDEN, learning_rate=DEFAULT_LEARNING_RATE,
                    normalization_transitions=DEFAULT_NORMALIZATION_TRANSITIONS,
                    max_neighbors=DEFAULT_MAX_NEIGHBORS, device="cpu",
                    gradient_clip_norm=DEFAULT_GRADIENT_CLIP_NORM,
                    checkpoint=None, output=None, progress_output=None,
                    log_every=100):
    """Train the bounded diagnostic candidate and write an inference checkpoint.

    The no-clip path is deliberately kept in the same operation order as the
    baseline: seed, train-only normalization, reseed, model/Adam construction,
    sampler draw, forward, raw-target MSE, backward, optimizer step.
    """
    if model_kind != DEFAULT_MODEL_KIND:
        raise ValueError("this sidecar is only for graph_raw")
    if dataset.manifest.get("formal_release") is True:
        raise ValueError("diagnostic candidate refuses a formal manifest")
    seed = seed_everything(seed)
    updates = _strict_positive_int(updates, "updates")
    centers_per_update = _strict_positive_int(centers_per_update, "centers_per_update")
    hidden = _strict_positive_int(hidden, "hidden")
    max_neighbors = _strict_positive_int(max_neighbors, "max_neighbors")
    if isinstance(normalization_transitions, bool):
        raise ValueError("normalization_transitions must be positive or None")
    if normalization_transitions is not None:
        normalization_transitions = _strict_positive_int(
            normalization_transitions, "normalization_transitions")
    if not np.isfinite(float(learning_rate)) or float(learning_rate) <= 0.0:
        raise ValueError("learning_rate must be positive and finite")
    gradient_clip_norm = validate_gradient_clip_norm(gradient_clip_norm)
    device = torch.device(device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")

    train_cases = tuple(dataset.case_ids("train"))
    if not train_cases:
        raise ValueError("train split has no cases")
    normalization, normalization_audit = compute_normalization(
        dataset, model_kind=model_kind, case_ids=train_cases,
        maximum_transitions=normalization_transitions, seed=seed,
        return_audit=True)

    # The second seed boundary is part of the baseline pairing contract.
    seed_everything(seed)
    model = DualIncrementModel(model_kind, hidden=hidden).to(device)
    initialization_digest = model_parameter_digest(model)
    optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
    sampler = TransitionSampler(dataset, case_ids=train_cases,
                                centers_per_update=centers_per_update, seed=seed)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    checkpoint = Path(checkpoint) if checkpoint is not None else Path(
        f"f3-{CANDIDATE_ID}-seed{seed}.pt")
    progress_path = Path(progress_output) if progress_output is not None else None
    run_id = f"{CANDIDATE_ID}-seed{seed}"
    config = {
        "candidate_id": CANDIDATE_ID,
        "model_kind": model_kind,
        "seed": int(seed),
        "updates": int(updates),
        "centers_per_update": int(centers_per_update),
        "hidden": int(hidden),
        "learning_rate": float(learning_rate),
        "optimizer": "Adam",
        "normalization_source_split": "train",
        "normalization_transitions": normalization_transitions,
        "target_normalization": "raw_dual_increment_train_shared",
        "max_neighbors": int(max_neighbors),
        "gradient_clipping": (None if gradient_clip_norm is None else {
            "kind": "global_l2",
            "max_norm": float(gradient_clip_norm),
        }),
        "run_id": run_id,
        "diagnostic_only": True,
    }
    started = time.perf_counter()
    history = []
    gradient_history = []
    _publish_progress(progress_path, status="running", update=0,
                      requested_updates=updates, started=started,
                      device=str(device), checkpoint=checkpoint)

    try:
        model.train()
        for update in range(1, updates + 1):
            case_id, frame, state, known, dt, target, centers = sampler.sample()
            args, _prior, diagnostics = tensors(
                state, known, dt, device, max_neighbors=max_neighbors)
            args = (normalization.normalize_features(args[0]), *args[1:])
            centers_t = torch.as_tensor(centers, dtype=torch.long, device=device)
            optimizer.zero_grad(set_to_none=True)
            prediction = model(*args, centers=centers_t)
            target_tensor = _raw_target_tensor(target, normalization, device)[centers_t]
            loss = torch.mean((prediction - target_tensor) ** 2)
            if not torch.isfinite(loss):
                raise FloatingPointError(f"nonfinite training loss at update {update}")
            loss.backward()
            if gradient_clip_norm is None:
                gradient_row = {
                    "update": int(update),
                    "enabled": False,
                }
            else:
                gradient_row = {
                    "update": int(update),
                    "enabled": True,
                    **clip_gradients(model, gradient_clip_norm),
                }
            optimizer.step()
            gradient_history.append(gradient_row)
            if update == 1 or update % max(1, int(log_every)) == 0 or update == updates:
                row = {
                    "update": int(update),
                    "loss_mse": float(loss.detach().cpu()),
                    "case_id": str(case_id),
                    "frame": int(frame),
                    "neighbor_truncation_fraction": float(
                        diagnostics["neighbor_truncation_fraction"]),
                }
                history.append(row)
                _publish_progress(
                    progress_path, status="running", update=update,
                    requested_updates=updates, started=started,
                    device=str(device), checkpoint=checkpoint,
                    loss_mse=row["loss_mse"], case_id=case_id, frame=frame)
    except Exception as error:
        _publish_progress(progress_path, status="failed", update=len(gradient_history),
                          requested_updates=updates, started=started,
                          device=str(device), checkpoint=checkpoint, error=str(error))
        raise

    elapsed = time.perf_counter() - started
    evidence = {
        "schema": "core.training.evidence.v1",
        "status": "complete",
        "initialization": {
            "status": "captured",
            "model_kind": model_kind,
            "seed": int(seed),
            "hidden": int(hidden),
            "constructed_before_first_update": True,
            "construction_update": 0,
            "parameter_count": int(sum(parameter.numel() for parameter in model.parameters())),
            "parameter_digest": initialization_digest,
        },
        "normalization": normalization_audit,
        "residual_prior": {
            "enabled": False,
            "history_complete": True,
            "semantic": "graph_raw has no residual prior",
        },
        "candidate": {
            "gradient_clipping": config["gradient_clipping"],
            "diagnostic_only": True,
        },
    }
    checkpoint_info = save_training_checkpoint(
        checkpoint, model=model, optimizer=optimizer, sampler=sampler,
        normalization=normalization, update=updates, config=config, seed=seed,
        history=history, evidence=evidence)
    clipping_rows = [row for row in gradient_history if row["enabled"]]
    if clipping_rows:
        pre_norms = [float(row["pre_clip_l2"]) for row in clipping_rows]
        post_norms = [float(row["post_clip_l2"]) for row in clipping_rows]
        clipping_summary = {
            "enabled": True,
            "max_norm": float(gradient_clip_norm),
            "updates": len(clipping_rows),
            "clipped_updates": sum(bool(row["clipped"]) for row in clipping_rows),
            "clip_fraction": sum(bool(row["clipped"]) for row in clipping_rows) / len(clipping_rows),
            "pre_clip_l2_max": max(pre_norms),
            "pre_clip_l2_mean": float(np.mean(pre_norms)),
            "post_clip_l2_max": max(post_norms),
            "post_clip_l2_mean": float(np.mean(post_norms)),
        }
    else:
        clipping_summary = {
            "enabled": False,
            "max_norm": None,
            "updates": int(updates),
            "clipped_updates": 0,
            "clip_fraction": 0.0,
        }
    result = {
        "schema": TRAINING_SCHEMA,
        "diagnostic_only": True,
        "candidate_id": CANDIDATE_ID,
        "run_id": run_id,
        "model_kind": model_kind,
        "seed": int(seed),
        "device": str(device),
        "parameter_count": int(sum(parameter.numel() for parameter in model.parameters())),
        "completed_updates": int(updates),
        "checkpoint": checkpoint_info,
        "normalization": normalization.as_dict(),
        "normalization_audit": normalization_audit,
        "config": config,
        "history": history,
        "gradient_clipping": clipping_summary,
        "gradient_history": gradient_history,
        "wall_seconds": float(elapsed),
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "evidence_status": "complete",
        "formal_eligible": False,
        "qualification_credit": 0,
        "future_state_inputs": False,
    }
    if device.type == "cuda":
        result["peak_gpu_memory_bytes"] = int(torch.cuda.max_memory_allocated(device))
    else:
        result["peak_gpu_memory_bytes"] = 0
    _publish_progress(
        progress_path, status="completed", update=updates,
        requested_updates=updates, started=started, device=str(device),
        checkpoint=checkpoint, loss_mse=(history[-1]["loss_mse"] if history else None),
        case_id=(history[-1]["case_id"] if history else None),
        frame=(history[-1]["frame"] if history else None))
    if output is not None:
        atomic_json(Path(output), result)
    return result


def evaluate_candidate(dataset, checkpoint, *, case_id, device="cpu",
                       chunk_size=34560, maximum_steps=DEFAULT_MAXIMUM_STEPS,
                       trajectory_output=None, progress_output=None,
                       evaluation_output=None, progress_every=25):
    """Run exactly one bounded diagnostic autonomous evaluation."""
    maximum_steps = _strict_positive_int(maximum_steps, "maximum_steps")
    payload = load_training_checkpoint(checkpoint, map_location="cpu",
                                       restore_rng=False)
    if payload.get("model_kind") != DEFAULT_MODEL_KIND:
        raise ValueError("candidate checkpoint is not graph_raw")
    config = payload.get("config")
    if not isinstance(config, Mapping) or config.get("candidate_id") != CANDIDATE_ID:
        raise ValueError("checkpoint is not bound to this candidate")
    model = DualIncrementModel(payload["model_kind"], hidden=int(payload["hidden"]))
    model.load_state_dict(payload.get("model_state", payload["state_dict"]))
    normalization = Normalization.from_dict(payload["normalization"])
    bound_max_neighbors = _strict_positive_int(config["max_neighbors"], "max_neighbors")
    predictor = ModelPredictor(
        model, device=device, chunk_size=_strict_positive_int(chunk_size, "chunk_size"),
        normalization=normalization, max_neighbors=bound_max_neighbors)
    result = evaluate(
        dataset, predictor, split="test", case_ids=[str(case_id)],
        maximum_steps=maximum_steps, diagnostic=True,
        model_kind=payload["model_kind"], checkpoint=checkpoint,
        training=True, trajectory_output_for_case=(
            lambda _case_id: trajectory_output) if trajectory_output is not None else None,
        progress_output_for_case=(
            lambda _case_id: progress_output) if progress_output is not None else None,
        progress_every=progress_every)
    if evaluation_output is not None:
        atomic_json(Path(evaluation_output), result)
    return result


def _metric_at(values, step: int):
    if not isinstance(values, list) or len(values) < step:
        return None
    value = values[step - 1]
    return None if value is None else float(value)


def _load_baseline_metrics(path: Path, *, step: int) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    evaluation = payload.get("evaluation", payload)
    if "metric_summary" in evaluation:
        summary = evaluation["metric_summary"]
        position = evaluation.get("position_rmse_m", {})
        velocity = evaluation.get("velocity_rmse_mps", {})
        return {
            "path": str(path),
            "sha256": sha256_file(path),
            "selection_score": float(summary["selection_score"]),
            "position_rmse_step_m": float(position[f"step_{step}"]),
            "velocity_rmse_step_mps": float(velocity[f"step_{step}"]),
            "position_rmse_frame_mean_m": float(position["frame_mean"]),
            "velocity_rmse_frame_mean_mps": float(velocity["frame_mean"]),
        }
    raise ValueError("baseline reference does not expose bounded metric_summary")


def build_diagnostic_receipt(*, manifest_path, dataset, case_id, training,
                             training_output, evaluation, evaluation_output,
                             trajectory_output, progress_output, baseline_path,
                             chunk_size, maximum_steps, full_horizon_reference=None):
    """Build a fail-closed, diagnostic-only receipt from completed artifacts."""
    if training.get("diagnostic_only") is not True or training.get("formal_eligible") is not False:
        raise ValueError("training result is not diagnostic-only")
    if evaluation.get("formal_eligible") is not False or evaluation.get("future_state_inputs") is not False:
        raise ValueError("evaluation is not diagnostic-only/casual")
    case_id = str(case_id)
    row = evaluation.get("cases", {}).get(case_id)
    if not isinstance(row, dict):
        raise ValueError("evaluation does not contain requested case")
    rollout = row.get("rollout", row)
    summary = summarize_evaluation(evaluation)
    summary_case = next(item for item in summary["cases"] if item["case_id"] == case_id)
    per_step = {item["step"]: item for item in summary_case["per_step"]}
    if maximum_steps not in per_step:
        raise ValueError("metric summary does not cover requested bounded step")
    metric = per_step[maximum_steps]
    baseline = _load_baseline_metrics(Path(baseline_path), step=maximum_steps)
    selection_score = summary_case.get("selection_score")
    if selection_score is None:
        raise ValueError("metric summary does not expose a selection score")
    finite_rows = [item for item in summary_case["per_step"]
                   if item["position_rmse_m"] is not None]
    if not finite_rows:
        raise ValueError("metric summary has no finite metric prefix")
    candidate_metrics = {
        "selection_score": float(selection_score),
        "position_rmse_step_m": float(metric["position_rmse_m"]),
        "velocity_rmse_step_mps": float(metric["velocity_rmse_mps"]),
        "position_rmse_frame_mean_m": float(np.mean(
            [item["position_rmse_m"] for item in finite_rows])),
        "velocity_rmse_frame_mean_mps": float(np.mean(
            [item["velocity_rmse_mps"] for item in finite_rows])),
    }
    strictly_better = all(
        candidate_metrics[key] <= baseline[key]
        for key in (
            "position_rmse_step_m", "velocity_rmse_step_mps",
            "position_rmse_frame_mean_m", "velocity_rmse_frame_mean_mps"))
    # The registered score is a penalty: lower is better (see
    # ``core_evaluation.PROTOCOL['selection']``).
    strictly_better = bool(strictly_better and candidate_metrics["selection_score"] < baseline["selection_score"])
    decision = "retained_for_followup" if strictly_better else "rejected_not_better_than_raw500"
    source_record = dataset.record(case_id)
    times = dataset.times(case_id)
    first_state = dataset.read_state(case_id, 0)
    manifest_path = Path(manifest_path)
    source = {
        "manifest": str(manifest_path),
        "manifest_file_sha256": sha256_file(manifest_path),
        "dataset_manifest_sha256": getattr(dataset, "manifest_sha256", None),
        "case_id": case_id,
        "case_source_sha256": source_record.get("sha256"),
        "particles": int(first_state.count),
        "expected_transitions": int(len(times) - 1),
        "expected_frames": int(len(times) - 1),
    }
    def artifact(path):
        if path is None:
            return None
        path = Path(path)
        return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}

    receipt = {
        "schema": SCHEMA,
        "diagnostic_only": True,
        "candidate": {
            "id": CANDIDATE_ID,
            "strategy": "optional_global_l2_gradient_norm_clipping",
            "default_gradient_clip_norm": None,
            "requested_gradient_clip_norm": training["config"]["gradient_clipping"],
            "default_behavior_unchanged": True,
            "training_update_insertion": "after_backward_before_optimizer_step",
        },
        "source": source,
        "protocol": {
            "model_kind": training["model_kind"],
            "seed": training["seed"],
            "hidden": training["config"]["hidden"],
            "updates": training["completed_updates"],
            "centers_per_update": training["config"]["centers_per_update"],
            "normalization_transitions": training["config"]["normalization_transitions"],
            "max_neighbors": training["config"]["max_neighbors"],
            "learning_rate": training["config"]["learning_rate"],
            "chunk_size": int(chunk_size),
            "device": training["device"],
            "maximum_steps": int(maximum_steps),
            "future_state_inputs": False,
            "autonomous": True,
        },
        "training": {
            "receipt": artifact(training_output),
            "completed_updates": training["completed_updates"],
            "wall_seconds": training["wall_seconds"],
            "peak_rss_mib": training["peak_rss_mib"],
            "peak_gpu_memory_bytes": training["peak_gpu_memory_bytes"],
            "parameter_count": training["parameter_count"],
            "checkpoint": artifact(training["checkpoint"]["path"]),
            "evidence_status": training["evidence_status"],
            "gradient_clipping": training["gradient_clipping"],
        },
        "evaluation": {
            "receipt": artifact(evaluation_output),
            "status": row.get("failure_category") == "maximum_steps_limit" and "bounded_complete" or row.get("failure_category"),
            "requested_maximum_steps": int(maximum_steps),
            "frames_executed": int(rollout.get("frames_executed", 0)),
            "failure_category": rollout.get("failure_category"),
            "requested_window_execution_complete": bool(rollout.get("frames_executed") == maximum_steps),
            "trajectory": artifact(trajectory_output),
            "progress": artifact(progress_output),
            "metrics": candidate_metrics,
            "metric_summary": summary,
        },
        "comparison_to_raw500_bounded": {
            "baseline": baseline,
            "candidate": candidate_metrics,
            "selection_score_delta": candidate_metrics["selection_score"] - baseline["selection_score"],
            "position_rmse_step_delta_m": candidate_metrics["position_rmse_step_m"] - baseline["position_rmse_step_m"],
            "velocity_rmse_step_delta_mps": candidate_metrics["velocity_rmse_step_mps"] - baseline["velocity_rmse_step_mps"],
            "decision_rule": "strictly lower selection penalty and no worse bounded/frame-mean position or velocity RMSE",
            "candidate_better": strictly_better,
        },
        "long_horizon_context": {
            "full_horizon_candidate_rollout_started": False,
            "full_horizon_reference": full_horizon_reference,
            "bounded_result_must_not_be_extrapolated": True,
        },
        "decision": {
            "candidate_status": decision,
            "interpretation": (
                "bounded candidate is not better than the raw500 bounded reference"
                if not strictly_better else
                "bounded candidate is better on the registered bounded comparison; full-horizon follow-up remains unqualified"),
            "retain_as_current_formal_candidate": False,
            "accepted_for_formal_training": False,
        },
        "qualification": {
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "qualification_credit": 0,
        },
        "side_effects": {
            "production_algorithm_modified": False,
            "production_hdf5_modified": False,
            "manifest_modified": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "solver_started": False,
            "worker_started": False,
            "queue_mutation": 0,
            "future_state_inputs": False,
        },
    }
    return receipt


def run_bounded_candidate(*, manifest_path, data_root, case_id,
                          baseline_path, checkpoint, training_output,
                          evaluation_output, receipt_output, trajectory_output,
                          progress_output=None, training_progress_output=None,
                          model_kind=DEFAULT_MODEL_KIND, seed=17,
                          updates=DEFAULT_UPDATES, centers_per_update=DEFAULT_CENTERS,
                          hidden=DEFAULT_HIDDEN, learning_rate=DEFAULT_LEARNING_RATE,
                          normalization_transitions=DEFAULT_NORMALIZATION_TRANSITIONS,
                          max_neighbors=DEFAULT_MAX_NEIGHBORS, device="cpu",
                          gradient_clip_norm=DEFAULT_GRADIENT_CLIP_NORM,
                          chunk_size=34560, maximum_steps=DEFAULT_MAXIMUM_STEPS,
                          progress_every=25):
    """Execute training plus one bounded evaluation and write the receipt."""
    with CoreDataset(manifest_path, data_root) as dataset:
        training = train_candidate(
            dataset, model_kind=model_kind, seed=seed, updates=updates,
            centers_per_update=centers_per_update, hidden=hidden,
            learning_rate=learning_rate,
            normalization_transitions=normalization_transitions,
            max_neighbors=max_neighbors, device=device,
            gradient_clip_norm=gradient_clip_norm, checkpoint=checkpoint,
            output=training_output, progress_output=training_progress_output)
        evaluation = evaluate_candidate(
            dataset, checkpoint, case_id=case_id, device=device,
            chunk_size=chunk_size, maximum_steps=maximum_steps,
            trajectory_output=trajectory_output, progress_output=progress_output,
            evaluation_output=evaluation_output, progress_every=progress_every)
        receipt = build_diagnostic_receipt(
            manifest_path=manifest_path, dataset=dataset, case_id=case_id,
            training=training, training_output=training_output,
            evaluation=evaluation, evaluation_output=evaluation_output,
            trajectory_output=trajectory_output, progress_output=progress_output,
            baseline_path=baseline_path, chunk_size=chunk_size,
            maximum_steps=maximum_steps,
            full_horizon_reference={
                "report": "reports/CORE-CONTINUATION-STATUS-2026-09-28-UPDATE-262.zh-CN.md",
                "known_position_rmse_step835_m": 7.0245020288875075,
                "known_velocity_rmse_step835_mps": 14.443016181997502,
            })
    atomic_json(Path(receipt_output), receipt)
    return receipt


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--data-root", type=Path, required=True)
    run.add_argument("--case-id", required=True)
    run.add_argument("--baseline-reference", type=Path, required=True)
    run.add_argument("--checkpoint", type=Path, required=True)
    run.add_argument("--training-output", type=Path, required=True)
    run.add_argument("--evaluation-output", type=Path, required=True)
    run.add_argument("--receipt-output", type=Path, required=True)
    run.add_argument("--trajectory-output", type=Path, required=True)
    run.add_argument("--progress-output", type=Path)
    run.add_argument("--training-progress-output", type=Path)
    run.add_argument("--model", dest="model_kind", default=DEFAULT_MODEL_KIND,
                     choices=(DEFAULT_MODEL_KIND,))
    run.add_argument("--seed", type=int, default=17)
    run.add_argument("--updates", type=int, default=DEFAULT_UPDATES)
    run.add_argument("--centers", type=int, default=DEFAULT_CENTERS)
    run.add_argument("--hidden", type=int, default=DEFAULT_HIDDEN)
    run.add_argument("--learning-rate", type=float, default=DEFAULT_LEARNING_RATE)
    run.add_argument("--normalization-transitions", type=int,
                     default=DEFAULT_NORMALIZATION_TRANSITIONS)
    run.add_argument("--max-neighbors", type=int, default=DEFAULT_MAX_NEIGHBORS)
    run.add_argument("--gradient-clip-norm", type=float, default=None,
                     help="optional global L2 bound; omitted means baseline update behavior")
    run.add_argument("--chunk-size", type=int, default=34560)
    run.add_argument("--maximum-steps", type=int, default=DEFAULT_MAXIMUM_STEPS)
    run.add_argument("--device", default="cpu")
    run.add_argument("--progress-every", type=int, default=25)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command != "run":
        raise ValueError("unsupported command")
    receipt = run_bounded_candidate(
        manifest_path=args.manifest, data_root=args.data_root, case_id=args.case_id,
        baseline_path=args.baseline_reference, checkpoint=args.checkpoint,
        training_output=args.training_output, evaluation_output=args.evaluation_output,
        receipt_output=args.receipt_output, trajectory_output=args.trajectory_output,
        progress_output=args.progress_output,
        training_progress_output=args.training_progress_output,
        model_kind=args.model_kind, seed=args.seed, updates=args.updates,
        centers_per_update=args.centers, hidden=args.hidden,
        learning_rate=args.learning_rate,
        normalization_transitions=args.normalization_transitions,
        max_neighbors=args.max_neighbors, device=args.device,
        gradient_clip_norm=args.gradient_clip_norm, chunk_size=args.chunk_size,
        maximum_steps=args.maximum_steps, progress_every=args.progress_every)
    print(json.dumps({
        "schema": receipt["schema"],
        "candidate_status": receipt["decision"]["candidate_status"],
        "candidate_better": receipt["comparison_to_raw500_bounded"]["candidate_better"],
        "qualification_credit": receipt["qualification"]["qualification_credit"],
        "receipt": str(args.receipt_output),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
