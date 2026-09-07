#!/usr/bin/env python3
"""Reference metric primitives for the v0.1 Lagrangian benchmark protocol."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import numpy as np


def require_strict_time(time: np.ndarray) -> None:
    time = np.asarray(time, dtype=float)
    if time.ndim != 1 or len(time) < 2 or not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0):
        raise ValueError("time must be finite, one-dimensional, and strictly increasing")


def require_finite_when_valid(values: np.ndarray, valid: np.ndarray) -> None:
    values = np.asarray(values)
    valid = np.asarray(valid, dtype=bool)
    expanded = valid[(...,) + (None,) * (values.ndim - valid.ndim)]
    expanded = np.broadcast_to(expanded, values.shape)
    if not np.all(np.isfinite(values[expanded])):
        raise ValueError("non-finite value under valid mask")


def trajectory_metrics(reference: np.ndarray, prediction: np.ndarray, valid: np.ndarray, dp: float) -> dict:
    reference = np.asarray(reference, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    valid = np.asarray(valid, dtype=bool)
    if reference.shape != prediction.shape or reference.shape[:2] != valid.shape or reference.shape[-1] != 3:
        raise ValueError("expected matching [T,N,3] positions and [T,N] valid mask")
    if not np.isfinite(dp) or dp <= 0:
        raise ValueError("dp must be positive")
    require_finite_when_valid(reference, valid)
    require_finite_when_valid(prediction, valid)
    error = np.linalg.norm(prediction - reference, axis=-1)
    per_frame = [float(np.sqrt(np.mean(error[t, valid[t]] ** 2))) if valid[t].any() else None
                 for t in range(len(valid))]
    all_error = error[valid]
    final_mask = valid[-1]
    return {
        "position_rmse_m": float(np.sqrt(np.mean(all_error ** 2))),
        "position_rmse_over_dp": float(np.sqrt(np.mean(all_error ** 2)) / dp),
        "ade_m": float(np.mean(all_error)),
        "fde_m": float(np.mean(error[-1, final_mask])) if final_mask.any() else None,
        "valid_fraction": float(valid.mean()),
        "per_frame_rmse_m": per_frame,
    }


def midpoint_kinematic_residual(position: np.ndarray, velocity: np.ndarray, time: np.ndarray, valid: np.ndarray) -> float:
    position = np.asarray(position, dtype=float)
    velocity = np.asarray(velocity, dtype=float)
    valid = np.asarray(valid, dtype=bool)
    require_strict_time(time)
    if position.shape != velocity.shape or position.shape[:2] != valid.shape:
        raise ValueError("kinematic arrays have incompatible shapes")
    residuals = []
    for i, dt in enumerate(np.diff(time)):
        common = valid[i] & valid[i + 1]
        if common.any():
            displacement = position[i + 1, common] - position[i, common]
            midpoint = 0.5 * (velocity[i + 1, common] + velocity[i, common]) * dt
            residuals.append(np.linalg.norm(displacement - midpoint, axis=1))
    if not residuals:
        raise ValueError("no adjacent valid identities")
    return float(np.median(np.concatenate(residuals)))


def mass_fraction_tv(reference: dict[str, float], prediction: dict[str, float]) -> float:
    labels = set(reference)
    if set(prediction) != labels:
        missing = sorted(labels - set(prediction))
        extra = sorted(set(prediction) - labels)
        raise ValueError(f"prediction destination labels differ; missing={missing}, extra={extra}")
    for name, distribution in (("reference", reference), ("prediction", prediction)):
        values = np.asarray(list(distribution.values()), dtype=float)
        if not np.all(np.isfinite(values)):
            raise ValueError(f"{name} destination fractions must be finite")
        if np.any(values < 0):
            raise ValueError(f"{name} destination fractions must be non-negative")
    if abs(sum(reference.values()) - 1.0) > 1e-6 or abs(sum(prediction.values()) - 1.0) > 1e-6:
        raise ValueError("destination fractions must close to one, including loss/unclassified categories")
    return 0.5 * sum(abs(reference.get(label, 0.0) - prediction.get(label, 0.0)) for label in labels)


def first_passage_metrics(reference: np.ndarray, prediction: np.ndarray) -> dict:
    reference = np.asarray(reference, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    if reference.shape != prediction.shape:
        raise ValueError("first-passage arrays must have matching shapes")
    ref_event = np.isfinite(reference)
    pred_event = np.isfinite(prediction)
    comparable = ref_event & pred_event
    return {
        "event_classification_accuracy": float(np.mean(ref_event == pred_event)),
        "time_mae_s": float(np.mean(np.abs(reference[comparable] - prediction[comparable]))) if comparable.any() else None,
        "reference_event_rate": float(ref_event.mean()),
        "prediction_event_rate": float(pred_event.mean()),
    }


def validate_split_lineage(records: Iterable[dict]) -> None:
    splits = defaultdict(set)
    for record in records:
        splits[record["lineage_group_id"]].add(record["split"])
    leaking = {key: sorted(value) for key, value in splits.items() if len(value) > 1}
    if leaking:
        raise ValueError(f"lineage crosses splits: {leaking}")


def validate_affine_transforms(transforms: np.ndarray, tolerance: float = 1e-5) -> None:
    transforms = np.asarray(transforms, dtype=float)
    if transforms.ndim != 3 or transforms.shape[1:] != (4, 4):
        raise ValueError("transform dataset must have shape [T,4,4]")
    for transform in transforms:
        if not np.all(np.isfinite(transform)):
            raise ValueError("transform entries must be finite")
        if not np.allclose(transform[3], [0, 0, 0, 1], atol=tolerance):
            raise ValueError("invalid homogeneous transform bottom row")
        rotation = transform[:3, :3]
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=tolerance) or not np.isclose(np.linalg.det(rotation), 1, atol=tolerance):
            raise ValueError("transform rotation is not proper orthonormal")


def require_event_sampling(time: np.ndarray, event_start: float, event_end: float, minimum_samples: int) -> None:
    require_strict_time(time)
    count = int(np.sum((time >= event_start) & (time <= event_end)))
    if count < minimum_samples:
        raise ValueError(f"event window has {count} samples; requires {minimum_samples}")
