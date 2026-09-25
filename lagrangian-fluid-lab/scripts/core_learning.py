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
from collections.abc import Mapping
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import subprocess
import sys
import tempfile
import time

import h5py
import numpy as np
import torch

# Support both ``python -m scripts.core_learning`` and direct script paths.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_contract import commit
from scripts.core_dataset import CoreDataset
from scripts.core_physics import frame_physics
from scripts.core_models import (MODEL_KINDS, AnalyticPredictor, Normalization,
                                  INITIALIZATION_VERSION, DualIncrementModel,
                                  ModelPredictor, node_features, tensors)

TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
PROFILE_SCHEMA = "core.profile.v1"
ROLLOUT_SCHEMA = "core.rollout.v1"
EVIDENCE_SCHEMA = "core.training.evidence.v1"
INITIALIZATION_EVIDENCE_SCHEMA = "core.training.initialization_evidence.v1"
NORMALIZATION_EVIDENCE_SCHEMA = "core.training.normalization_evidence.v1"
PRIOR_EVIDENCE_SCHEMA = "core.training.prior_evidence.v1"
DEFAULT_UPDATES = 32000
DEFAULT_CENTERS = 256
DEFAULT_HIDDEN = 64
DEFAULT_LR = 1e-3
DEFAULT_MAX_NEIGHBORS = 64
ANALYTIC_BASELINES = ("constant_velocity", "known_force")
MILESTONE_UPDATES = (8000, 16000, 24000, 32000)
SCIENTIFIC_STATUS_NOT_ASSESSED = "not_assessed"

# Keep the direct learning/evaluation boundary aligned with the formal
# capacity contract in core_formal_planner.py.  These are deliberately local
# constants so a caller cannot omit the planner's denominator requirements by
# invoking this module without the planner CLI.
FORMAL_MIN_FAMILIES = 3
FORMAL_MIN_VALIDATION_PER_FAMILY = 4
FORMAL_MIN_TEST_PER_FAMILY = 12


def _strict_integer(value, name):
    """Accept integer counters without truncating malformed receipt values."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    return int(value)


def _finite_scalar_sequence(values, expected):
    """Return whether an error sequence covers the requested horizon finitely."""
    if not isinstance(values, (list, tuple)) or len(values) != int(expected):
        return False
    return all(isinstance(value, (int, float, np.integer, np.floating))
               and np.isfinite(float(value)) for value in values)


def rollout_completion_semantics(*, expected_frames, frames_executed,
                                failure_category, position_rmse,
                                velocity_rmse):
    """Separate execution/finite completion from scientific validity.

    ``failure_category`` belongs to the execution/reader path.  A physical
    diagnostic such as a saved-chord wall event is deliberately not inferred
    here; the raw autonomous rollout therefore reports
    ``scientific_status=not_assessed``.  A released scientific protocol may
    add a separate status and category without changing the numerical score.
    """
    expected = _strict_integer(expected_frames, "expected_frames")
    completed = _strict_integer(frames_executed, "frames_executed")
    if expected < 0 or completed < 0 or completed > expected:
        raise ValueError("invalid rollout completion counts")
    execution_complete = bool(expected > 0 and completed == expected and failure_category is None)
    finite_rollout_complete = bool(
        execution_complete
        and _finite_scalar_sequence(position_rmse, expected)
        and _finite_scalar_sequence(velocity_rmse, expected)
    )
    return {
        "execution_complete": execution_complete,
        "finite_rollout_complete": finite_rollout_complete,
        "scientific_status": SCIENTIFIC_STATUS_NOT_ASSESSED,
        "scientific_failure_category": None,
        "scientific_first_failure_frame": None,
    }


def _execution_summary(case_rows):
    """Summarize product-readable execution gates without changing scores.

    ``executed`` means an autonomous attempt produced a score row, including a
    scientifically negative result.  Missing setup/queue execution has
    ``executed=False`` and remains outside the executed-case count while still
    retaining its fixed denominator in ``score``.
    """
    rows = list(case_rows.values()) if isinstance(case_rows, dict) else list(case_rows)
    attempted = []
    missing = 0
    complete = 0
    finite = 0
    scientific_negative = 0
    scientific_status_counts = Counter()
    for row in rows:
        rollout = row.get("rollout", row) if isinstance(row, dict) else {}
        score = row.get("score", {}) if isinstance(row, dict) else {}
        is_executed = bool(score.get("executed", rollout.get("executed", False)))
        if not is_executed:
            missing += 1
        else:
            attempted.append(row)
        if rollout.get("execution_complete") is True:
            complete += 1
        if rollout.get("finite_rollout_complete") is True:
            finite += 1
        status = rollout.get("scientific_status", SCIENTIFIC_STATUS_NOT_ASSESSED)
        scientific_status_counts[str(status)] += 1
        if is_executed and status == "failed":
            scientific_negative += 1
    return {
        "registered_case_count": len(rows),
        "executed_case_count": len(attempted),
        "missing_execution_case_count": int(missing),
        "execution_complete_case_count": int(complete),
        "finite_rollout_complete_case_count": int(finite),
        "scientifically_negative_executed_case_count": int(scientific_negative),
        "scientific_status_counts": dict(sorted(scientific_status_counts.items())),
    }


def formal_evaluation_gate(*, registered_case_ids, selected_case_ids=None,
                           split="test", maximum_steps=None,
                           test_family_counts=None, validation_family_counts=None):
    """Validate the immutable scope of a direct formal evaluation.

    This is deliberately pure: the caller supplies the case registry observed
    from the released manifest.  In particular, an explicit case list is not
    allowed to redefine the denominator, and a rollout horizon is not allowed
    to redefine the registered future-frame count.  The family denominators
    are required inputs rather than inferred from a selected case list, so a
    small ``formal_release`` fixture cannot bypass the planner capacity
    contract.
    """
    registered = tuple(registered_case_ids)
    try:
        registered_set = set(registered)
    except TypeError as error:
        raise ValueError("formal evaluation case IDs must be hashable") from error
    if not registered:
        raise ValueError("formal evaluation requires registered test cases")
    if len(registered_set) != len(registered):
        raise ValueError("formal evaluation registry contains duplicate cases")
    if split != "test":
        raise ValueError("formal evaluation requires split='test'")
    if maximum_steps is not None:
        raise ValueError("formal evaluation forbids maximum_steps")

    test_counts = _strict_formal_family_counts(
        test_family_counts, "test family denominator")
    validation_counts = _strict_formal_family_counts(
        validation_family_counts, "validation family denominator")
    if not test_counts or not validation_counts:
        raise ValueError("formal evaluation requires non-empty family denominators")
    if sum(test_counts.values()) != len(registered):
        raise ValueError(
            "test family denominator must sum to every registered test case")
    if set(test_counts) != set(validation_counts):
        raise ValueError(
            "validation and test family denominators must contain the same families")
    if len(test_counts) < FORMAL_MIN_FAMILIES:
        raise ValueError(
            f"formal evaluation requires at least {FORMAL_MIN_FAMILIES} T1 families")
    undersized_validation = {
        family: count for family, count in validation_counts.items()
        if count < FORMAL_MIN_VALIDATION_PER_FAMILY
    }
    if undersized_validation:
        raise ValueError(
            "formal evaluation requires at least "
            f"{FORMAL_MIN_VALIDATION_PER_FAMILY} validation cases per family; "
            f"found {undersized_validation}")
    undersized_test = {
        family: count for family, count in test_counts.items()
        if count < FORMAL_MIN_TEST_PER_FAMILY
    }
    if undersized_test:
        raise ValueError(
            "formal evaluation requires at least "
            f"{FORMAL_MIN_TEST_PER_FAMILY} test cases per family; "
            f"found {undersized_test}")

    if selected_case_ids is None:
        selected = registered
    elif isinstance(selected_case_ids, str):
        selected = (selected_case_ids,)
    else:
        selected = tuple(selected_case_ids)
    try:
        selected_set = set(selected)
    except TypeError as error:
        raise ValueError("formal evaluation case IDs must be hashable") from error
    if len(selected_set) != len(selected):
        raise ValueError("formal evaluation case selection contains duplicate cases")
    unknown = [case_id for case_id in selected if case_id not in registered_set]
    if unknown:
        raise ValueError(f"formal evaluation contains unknown case(s): {unknown}")
    if selected_set != registered_set or len(selected) != len(registered):
        raise ValueError("formal evaluation requires every registered test case")
    return {
        "split": "test",
        "registered_case_ids": registered,
        "case_ids": selected,
        "registered_case_count": len(registered),
        "maximum_steps": None,
        "test_family_counts": dict(sorted(test_counts.items())),
        "validation_family_counts": dict(sorted(validation_counts.items())),
        "minimum_families": FORMAL_MIN_FAMILIES,
        "minimum_validation_cases_per_family": FORMAL_MIN_VALIDATION_PER_FAMILY,
        "minimum_test_cases_per_family": FORMAL_MIN_TEST_PER_FAMILY,
    }


def _strict_formal_family_counts(value, name):
    """Validate a planner-bound family denominator without coercion."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping of string families to integer counts")
    counts = {}
    for family, count in value.items():
        if not isinstance(family, str) or not family.strip():
            raise ValueError(f"{name} family IDs must be non-empty strings")
        if isinstance(count, (bool, np.bool_)) or not isinstance(count, (int, np.integer)):
            raise ValueError(f"{name} counts must be integers")
        count = int(count)
        if count < 0:
            raise ValueError(f"{name} counts must be nonnegative")
        counts[family] = count
    return counts


def _validate_fixed_denominator(case_ids, fixed_denominator):
    """Reject a missing, partial, or malformed registered frame denominator."""
    case_ids = tuple(case_ids)
    if not isinstance(fixed_denominator, dict):
        raise ValueError("fixed evaluation denominator is required")
    try:
        if set(fixed_denominator) != set(case_ids):
            raise ValueError("fixed evaluation denominator must cover every registered case")
    except TypeError as error:
        raise ValueError("fixed evaluation denominator case IDs must be hashable") from error
    for case_id in case_ids:
        row = fixed_denominator.get(case_id)
        if not isinstance(row, dict):
            raise ValueError(f"fixed evaluation denominator is missing case {case_id}")
        expected_frames = _strict_integer(row.get("expected_frames"),
                                          f"expected_frames for case {case_id}")
        if expected_frames < 1:
            raise ValueError(f"expected_frames for case {case_id} must be positive")
        for name in ("length_m", "speed_mps"):
            value = row.get(name)
            if not isinstance(value, (int, float, np.integer, np.floating)) \
                    or not np.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"fixed evaluation denominator has invalid {name} for case {case_id}")
    return fixed_denominator


def _fixed_denominator_for_cases(dataset, case_ids):
    fixed_denominator = {}
    for case_id in case_ids:
        expected_frames = len(dataset.times(case_id)) - 1
        length_m, speed_mps = _characteristic_scales(dataset.known_inputs(case_id))
        fixed_denominator[case_id] = {
            "expected_frames": expected_frames,
            "length_m": length_m,
            "speed_mps": speed_mps,
        }
    return _validate_fixed_denominator(case_ids, fixed_denominator)


def _finite_summary(case_rows):
    """Expose finite completion separately from execution and score status."""
    rows = list(case_rows.values()) if isinstance(case_rows, dict) else list(case_rows)
    finite = sum(row.get("rollout", {}).get("finite_rollout_complete") is True
                 for row in rows if isinstance(row, dict))
    return {
        "registered_case_count": len(rows),
        "finite_rollout_complete_case_count": int(finite),
        "finite_rollout_incomplete_case_count": int(len(rows) - finite),
        "all_registered_rollouts_finite": bool(rows) and finite == len(rows),
    }


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _dataset_manifest_sha256(dataset):
    """Return the immutable dataset identity when the reader exposes one."""
    value = getattr(dataset, "manifest_sha256", None)
    if isinstance(value, str) and len(value) == 64:
        try:
            int(value, 16)
        except ValueError:
            pass
        else:
            return value
    return None


def _manifest_formal_release(dataset):
    """Fail closed until a V13 verified-reader capability is implemented.

    The legacy Mapping/path reader exposes manifest metadata and strict
    content hashes, but does not bind the same-FD snapshot, broker, and worker
    identities required for formal admission.  A ``formal_release`` boolean
    is therefore descriptive only and cannot authorize training or scoring.
    """
    return False


def _formal_validation_eligible(dataset, validation_cases, family_counts):
    return bool(
        _manifest_formal_release(dataset)
        and len(validation_cases) >= FORMAL_MIN_FAMILIES * FORMAL_MIN_VALIDATION_PER_FAMILY
        and len(family_counts) >= FORMAL_MIN_FAMILIES
        and min(family_counts.values(), default=0) >= FORMAL_MIN_VALIDATION_PER_FAMILY
    )


def _geometry_at(known, time_s):
    """Resolve geometry under both the current and legacy Core input APIs.

    The v3 reproduction bundle exposes a finite ``KnownInputs.geometry``
    field and has no ``geometry_at`` method.  Newer inputs may expose the
    method for prescribed motion.  This helper preserves the newer dynamic
    behavior while keeping scoring/setup compatible with the immutable legacy
    bundle contract; it never synthesizes geometry from a reference state.
    """
    resolver = getattr(known, "geometry_at", None)
    if callable(resolver):
        return resolver(time_s)
    geometry = getattr(known, "geometry", None)
    if geometry is None:
        raise AttributeError("known inputs require geometry or geometry_at")
    if not math.isfinite(float(time_s)):
        raise ValueError("geometry time must be finite")
    return geometry


class _LegacyKnownInputsProxy:
    """Expose the current causal view over a finite legacy input object."""

    __slots__ = ("_known",)

    def __init__(self, known):
        self._known = known

    def __getattr__(self, name):
        return getattr(self._known, name)

    def geometry_at(self, time_s):
        return _geometry_at(self._known, time_s)


def _known_inputs_for_learning(known):
    """Bridge only the legacy finite-geometry method name at the ML boundary."""
    return known if callable(getattr(known, "geometry_at", None)) else _LegacyKnownInputsProxy(known)


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


def model_parameter_digest(model):
    """Hash the constructed parameter/buffer state in deterministic key order.

    The digest is captured immediately after model construction and before the
    first optimizer step.  It intentionally includes buffers such as
    ``target_scale`` because they are part of the inference contract.
    """
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(str(name).encode())
        digest.update(b"\0")
        digest.update(str(tensor.dtype).encode())
        digest.update(b"\0")
        digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode())
        digest.update(b"\0")
        digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def restore_rng_state(state):
    if not state:
        return
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    # ``train_model`` loads a resume checkpoint with ``map_location=device``.
    # On CUDA that also maps the serialized RNG byte tensors onto the GPU,
    # while ``torch.set_rng_state`` deliberately accepts only a CPU
    # ``ByteTensor``.  Normalize both CPU and CUDA RNG payloads at the restore
    # boundary so a checkpoint can be resumed on the device it was scheduled
    # for without changing the recorded RNG bytes.
    def _cpu_rng_state(value):
        if not isinstance(value, torch.Tensor):
            raise TypeError("checkpoint RNG state must be a torch Tensor")
        if value.dtype != torch.uint8:
            raise TypeError("checkpoint RNG state must have torch.uint8 dtype")
        value = value.detach().to(device="cpu").contiguous()
        if value.ndim != 1:
            raise ValueError("checkpoint RNG state must be a one-dimensional byte tensor")
        return value

    torch.set_rng_state(_cpu_rng_state(state["torch"]))
    if torch.cuda.is_available() and state.get("torch_cuda") is not None:
        cuda_states = state["torch_cuda"]
        if not isinstance(cuda_states, (list, tuple)):
            raise TypeError("checkpoint CUDA RNG state must be a tensor sequence")
        torch.cuda.set_rng_state_all([_cpu_rng_state(item) for item in cuda_states])


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


def _normalization_evidence(case_ids, transitions, maximum_transitions, seed,
                            available_transition_count=None):
    counts = {str(case_id): 0 for case_id in case_ids}
    bindings = []
    for case_id, frame in transitions:
        case_id = str(case_id)
        counts[case_id] = counts.get(case_id, 0) + 1
        bindings.append({"case_id": case_id, "frame": int(frame)})
    return {
        "schema": NORMALIZATION_EVIDENCE_SCHEMA,
        "source_split": "train",
        "target_reference": "raw_dual_increment_train_shared",
        "selection_seed": int(seed),
        "requested_maximum_transitions": None if maximum_transitions is None else int(maximum_transitions),
        "available_transition_count": int(
            len(transitions) if available_transition_count is None else available_transition_count
        ),
        "selected_transition_count": len(bindings),
        "train_case_ids": [str(case_id) for case_id in case_ids],
        "selected_case_ids": list(dict.fromkeys(item["case_id"] for item in bindings)),
        "selected_transition_counts": counts,
        "selected_transition_bindings": bindings,
        "selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
    }


def compute_normalization(dataset, *, model_kind="graph_raw", case_ids=None,
                          maximum_transitions=256, seed=0, return_audit=False):
    """Compute train-only feature/target statistics for one baseline kind.

    ``return_audit=True`` adds the exact train case/frame bindings used for
    the statistics.  The default return value remains the historical
    :class:`Normalization` object for old callers.
    """
    if model_kind not in MODEL_KINDS:
        raise ValueError(f"unknown model kind {model_kind}")
    case_ids = tuple(case_ids or dataset.case_ids("train"))
    transitions = _transition_indices(dataset, case_ids, maximum_transitions, seed)
    available_transition_count = len(transitions) if maximum_transitions is None else len(
        _transition_indices(dataset, case_ids, None, seed)
    )
    feature_stats, target_stats = RunningMoments(23), RunningMoments(6)
    for case_id, frame in transitions:
        state, known, dt, target = dataset.training_transition(case_id, frame)
        known = _known_inputs_for_learning(known)
        features, _ = node_features(state, known, dt)
        target_array = np.column_stack((target.displacement, target.delta_velocity))
        # The raw six-vector target scale is shared by raw and residual
        # baselines. The residual route subtracts its known-force prior only
        # after this train-only scale has been fixed, preserving fair units.
        feature_stats.update(features)
        target_stats.update(target_array)
    feature_mean, feature_std = feature_stats.finish()
    target_mean, target_std = target_stats.finish()
    normalization = Normalization(feature_mean.astype(np.float32), feature_std.astype(np.float32),
                                  target_mean.astype(np.float32), target_std.astype(np.float32))
    if return_audit:
        return normalization, _normalization_evidence(
            case_ids, transitions, maximum_transitions, seed,
            available_transition_count=available_transition_count,
        )
    return normalization


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
        known = _known_inputs_for_learning(known)
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
                    known = _known_inputs_for_learning(known)
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
                             milestone_selection=None, evidence=None):
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
    if evidence is None:
        # Direct legacy callers remain loadable, but a collector must never
        # infer initialization/prior facts from such a checkpoint.
        payload["evidence_status"] = "missing_legacy"
    else:
        payload["evidence"] = json.loads(canonical(evidence))
        payload["evidence_status"] = "complete" if evidence.get("status") == "complete" else "incomplete"
    _atomic_torch_save(payload, path)
    return {"path": str(Path(path)), "sha256": sha256_file(path), "bytes": Path(path).stat().st_size,
            "update": int(update), "schema": CHECKPOINT_SCHEMA}


def load_training_checkpoint(path, *, model=None, optimizer=None, sampler=None,
                             map_location="cpu", restore_rng=True):
    payload = torch.load(Path(path), map_location=map_location, weights_only=False)
    if payload.get("schema") != CHECKPOINT_SCHEMA:
        raise ValueError("unsupported Core checkpoint schema")
    if "evidence" not in payload:
        payload["evidence_status"] = "missing_legacy"
    elif payload.get("evidence_status") is None:
        payload["evidence_status"] = "complete" if payload["evidence"].get("status") == "complete" else "incomplete"
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


class PriorExecutionAudit:
    """Small persistent audit of the SI known-force residual prior."""

    def __init__(self, model_kind, *, history_complete=True, previous=None):
        self.enabled = model_kind == "graph_residual"
        self.history_complete = bool(history_complete)
        previous = previous if isinstance(previous, dict) else {}
        self.execution_calls = int(previous.get("execution_calls", 0))
        self.rows = int(previous.get("rows", 0))
        self.finite = bool(previous.get("finite", True))
        self.dx_abs_max = float(previous.get("dx_abs_max_m", 0.0))
        self.dv_abs_max = float(previous.get("dv_abs_max_mps", 0.0))
        self.dx_abs_sum = float(previous.get("dx_abs_sum_m", 0.0))
        self.dv_abs_sum = float(previous.get("dv_abs_sum_mps", 0.0))
        self.last_update = previous.get("last_update")

    def record(self, prior, *, update, case_id, frame):
        if not self.enabled:
            return
        values = prior.detach().to("cpu").numpy()
        if values.ndim != 2 or values.shape[1] != 6:
            raise ValueError("known-force prior must have shape [N,6]")
        finite = bool(np.isfinite(values).all())
        self.execution_calls += 1
        self.rows += int(len(values))
        self.finite = bool(self.finite and finite)
        if finite:
            dx = np.abs(values[:, :3])
            dv = np.abs(values[:, 3:])
            self.dx_abs_max = max(self.dx_abs_max, float(dx.max(initial=0.0)))
            self.dv_abs_max = max(self.dv_abs_max, float(dv.max(initial=0.0)))
            self.dx_abs_sum += float(dx.sum())
            self.dv_abs_sum += float(dv.sum())
        self.last_update = {"update": int(update), "case_id": str(case_id), "frame": int(frame)}

    def as_dict(self):
        return {
            "schema": PRIOR_EVIDENCE_SCHEMA,
            "enabled": bool(self.enabled),
            "history_complete": bool(self.history_complete),
            "units": {"displacement": "m", "delta_velocity": "m/s"},
            "execution_calls": int(self.execution_calls),
            "rows": int(self.rows),
            "finite": bool(self.finite),
            "dx_abs_max_m": float(self.dx_abs_max),
            "dv_abs_max_mps": float(self.dv_abs_max),
            "dx_abs_sum_m": float(self.dx_abs_sum),
            "dv_abs_sum_mps": float(self.dv_abs_sum),
            "last_update": self.last_update,
            "semantic": "graph_residual subtracts this SI prior before shared raw-target normalization; predictor adds it back",
        }


def _target_tensor(state, known, dt, target, prior, model_kind, device, normalization,
                   prior_audit=None, *, update=None, case_id=None, frame=None):
    target_array = np.column_stack((target.displacement, target.delta_velocity))
    if model_kind == "graph_residual":
        if prior_audit is not None:
            prior_audit.record(prior, update=update, case_id=case_id, frame=frame)
        # Subtract the SI-unit prior before the single raw-target train scale
        # is applied.  Prediction reverses this exact order: denormalize the
        # residual, then add the SI prior.
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
    validation_formal_eligible = _formal_validation_eligible(
        dataset, validation_cases, validation_family_counts)
    normalization_audit = None
    if normalization is None:
        normalization, normalization_audit = compute_normalization(
            dataset, model_kind=model_kind, case_ids=train_cases,
            maximum_transitions=normalization_transitions, seed=seed,
            return_audit=True)
    else:
        # A caller-supplied scale predates the auditable training path. Keep
        # accepting it, but never claim that its train transition sampling is
        # known from the final arrays.
        normalization_audit = {
            "schema": NORMALIZATION_EVIDENCE_SCHEMA,
            "status": "missing_external_statistics_provenance",
            "source_split": normalization.source_split,
            "target_reference": normalization.target_reference,
            "train_case_ids": [str(case_id) for case_id in train_cases],
            "selected_transition_count": None,
            "selected_transition_bindings": [],
        }
    # Reseed immediately before construction as an explicit protocol boundary:
    # normalization/reader work can never consume the model initialization
    # stream, and every requested seed identifies the initial weights exactly.
    seed_everything(seed)
    model = DualIncrementModel(model_kind, hidden=hidden).to(device)
    constructed_parameter_digest = model_parameter_digest(model)
    initialization_evidence = {
        "schema": INITIALIZATION_EVIDENCE_SCHEMA,
        "status": "captured",
        "model_kind": model_kind,
        "seed": int(seed),
        "hidden": int(hidden),
        "constructed_before_first_update": True,
        "construction_update": 0,
        "parameter_count": int(sum(parameter.numel() for parameter in model.parameters())),
        "parameter_digest": constructed_parameter_digest,
    }
    optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
    sampler = TransitionSampler(dataset, case_ids=train_cases,
                                centers_per_update=centers_per_update, seed=seed)
    fixed_validation = FixedValidationSet(dataset, maximum_transitions=validation_transitions,
                                          centers=validation_centers)
    run_id = run_id or f"{model_kind}-seed{seed}"
    dataset_manifest_sha256 = _dataset_manifest_sha256(dataset)
    start_update = 0
    history = []
    validation_history = []
    milestone_checkpoints = []
    milestone_evaluations = []
    milestone_evaluation_plan = []
    milestone_selection = None
    milestone_selection_error = None
    prior_audit = PriorExecutionAudit(model_kind)
    if resume is not None:
        payload = load_training_checkpoint(resume, model=model, optimizer=optimizer,
                                           sampler=sampler, map_location=device, restore_rng=True)
        saved_norm = Normalization.from_dict(payload["normalization"])
        if normalization.as_dict() != saved_norm.as_dict():
            raise ValueError("resume normalization differs from current train-only statistics")
        saved_evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        saved_norm_audit = saved_evidence.get("normalization")
        if isinstance(saved_norm_audit, dict) and saved_norm_audit.get("status") not in {
                "missing_external_statistics_provenance", "missing_legacy"}:
            if canonical(saved_norm_audit) != canonical(normalization_audit):
                raise ValueError("resume normalization sampling evidence differs from current train-only statistics")
        saved_initialization = saved_evidence.get("initialization")
        valid_saved_digest = (
            isinstance(saved_initialization, dict)
            and saved_initialization.get("status") == "captured"
            and isinstance(saved_initialization.get("parameter_digest"), str)
            and len(saved_initialization["parameter_digest"]) == 64
        )
        if valid_saved_digest and saved_initialization["parameter_digest"] != constructed_parameter_digest:
            raise ValueError("resume initialization evidence digest does not match the seeded construction")
        loaded_parameter_digest = model_parameter_digest(model)
        if valid_saved_digest:
            initialization_evidence = dict(saved_initialization)
        else:
            # The digest of the loaded trained weights is diagnostic only. It
            # must never be relabeled as the model's construction digest.
            initialization_evidence = {
                "schema": INITIALIZATION_EVIDENCE_SCHEMA,
                "status": "missing_legacy",
                "model_kind": model_kind,
                "seed": int(seed),
                "hidden": int(hidden),
                "constructed_before_first_update": False,
                "construction_update": None,
                "parameter_count": int(sum(parameter.numel() for parameter in model.parameters())),
                "parameter_digest": None,
            }
        initialization_evidence["resume"] = {
            "resumed": True,
            "start_update": int(payload.get("update", 0)),
            "loaded_parameter_digest": loaded_parameter_digest,
            "loaded_digest_is_initial": False,
            "initial_digest_reused": bool(valid_saved_digest),
            "source_checkpoint": str(Path(resume)),
        }
        saved_prior = saved_evidence.get("residual_prior")
        if isinstance(saved_prior, dict) and saved_prior.get("schema") == PRIOR_EVIDENCE_SCHEMA:
            prior_audit = PriorExecutionAudit(model_kind,
                                              history_complete=bool(saved_prior.get("history_complete", False)),
                                              previous=saved_prior)
        else:
            prior_audit = PriorExecutionAudit(model_kind, history_complete=False)
        start_update = int(payload["update"])
        if payload["model_kind"] != model_kind or int(payload["seed"]) != seed:
            raise ValueError("resume model/seed differs from requested run")
        previous_config = payload.get("config", {})
        saved_run_id = previous_config.get("run_id")
        if saved_run_id is not None and str(saved_run_id) != str(run_id):
            raise ValueError("resume checkpoint belongs to a different run_id")
        saved_manifest_sha256 = previous_config.get("manifest_sha256")
        if (saved_manifest_sha256 is not None and dataset_manifest_sha256 is not None
                and saved_manifest_sha256 != dataset_manifest_sha256):
            raise ValueError("resume checkpoint belongs to a different dataset manifest")
        saved_learning_rate = previous_config.get("learning_rate")
        if saved_learning_rate is not None:
            try:
                learning_rate_matches = math.isclose(
                    float(saved_learning_rate), float(learning_rate), rel_tol=0.0, abs_tol=0.0)
            except (TypeError, ValueError):
                learning_rate_matches = False
            if not learning_rate_matches:
                raise ValueError("resume learning rate differs from checkpoint")
        if previous_config.get("initialization") != INITIALIZATION_VERSION:
            raise ValueError("resume checkpoint uses a different initialization contract")
        if int(previous_config.get("paired_seed", -1)) != seed:
            raise ValueError("resume checkpoint paired seed differs from requested seed")
        if int(previous_config.get("sampler_seed", -1)) != seed:
            raise ValueError("resume checkpoint sampler seed differs from requested seed")
        if start_update > updates:
            raise ValueError("resume checkpoint is beyond requested update count")
        history = list(payload.get("history", []))
        validation_history = list(payload.get("validation_history", []))
        milestone_checkpoints = list(payload.get("milestone_checkpoints", []))
        milestone_evaluations = []
        for saved_evaluation in payload.get("milestone_evaluations", []):
            try:
                update = int(saved_evaluation.get("update", -1))
                checkpoint_reference = _milestone_checkpoint_for_update(
                    milestone_checkpoints, update)
                milestone_evaluations.append(_validate_milestone_evaluation(
                    saved_evaluation, dataset=dataset,
                    checkpoint=checkpoint_reference,
                    validation_cases=validation_cases,
                    validation_registry=validation_registry,
                ))
            except (AttributeError, KeyError, TypeError, ValueError):
                # Re-evaluate a malformed historical sidecar from its bound
                # checkpoint below instead of allowing it into selection.
                continue
        milestone_evaluation_plan = list(payload.get("milestone_evaluation_plan", []))
        milestone_selection = payload.get("milestone_selection")
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
        "initialization": INITIALIZATION_VERSION,
        "paired_seed": int(seed),
        "sampler_seed": int(seed),
        "gradient_clipping": None,
        "log_every": int(log_every), "checkpoint_every": int(checkpoint_every),
        "validation_every": int(validation_every),
        "validation_transition_count": len(fixed_validation.rows),
        "validation_centers": int(validation_centers),
        "validation_case_count": len(validation_cases),
        "validation_family_counts": dict(sorted(validation_family_counts.items())),
        "validation_formal_eligible": validation_formal_eligible,
        "run_id": run_id,
        "manifest_sha256": dataset_manifest_sha256,
        "manifest_formal_release": _manifest_formal_release(dataset),
        "evaluate_milestones": bool(evaluate_milestones),
        "milestone_evaluation_mode": "in_process" if evaluate_milestones else "deferred",
    }
    checkpoint = Path(checkpoint) if checkpoint is not None else Path(f"{run_id}.pt")

    def training_evidence(completed_updates=None):
        """Return evidence for the checkpoint's actual update frontier.

        ``updates`` is the requested terminal length of the run.  Milestone
        checkpoints are intentionally published before that frontier (for
        example at 8k in a 32k run), so residual-prior execution evidence must
        be checked against the update represented by this checkpoint rather
        than against the eventual run length.  A caller that does not provide
        a frontier is retained for the final receipt path and uses the
        requested terminal update.
        """
        evidence_update = int(updates if completed_updates is None else completed_updates)
        normalization_complete = (
            isinstance(normalization_audit, dict)
            and normalization_audit.get("schema") == NORMALIZATION_EVIDENCE_SCHEMA
            and normalization_audit.get("status") != "missing_external_statistics_provenance"
            and isinstance(normalization_audit.get("selected_transition_count"), int)
            and normalization_audit.get("selected_transition_count", 0) > 0
            and list(normalization_audit.get("train_case_ids", [])) == list(train_cases)
        )
        prior = prior_audit.as_dict()
        prior_complete = (not prior_audit.enabled or (
            prior_audit.history_complete and prior_audit.finite
            and prior_audit.execution_calls == evidence_update
        ))
        status = "complete" if (
            initialization_evidence.get("status") == "captured"
            and normalization_complete and prior_complete
        ) else "incomplete"
        return {
            "schema": EVIDENCE_SCHEMA,
            "status": status,
            "initialization": dict(initialization_evidence),
            "normalization": normalization_audit,
            "residual_prior": prior,
            "resume_semantics": {
                "loaded_weights_are_not_initial": True,
                "construction_digest_preserved_across_resume": (
                    initialization_evidence.get("status") == "captured"
                    and initialization_evidence.get("parameter_digest") is not None
                ),
            },
        }

    def record_milestone_evaluation(report):
        """Append one update exactly once and close its persistent queue row."""
        update = int(report["update"])
        checkpoint_reference = _milestone_checkpoint_for_update(
            milestone_checkpoints, update)
        _validate_milestone_evaluation(
            report, dataset=dataset,
            checkpoint=checkpoint_reference,
            validation_cases=validation_cases,
            validation_registry=validation_registry,
        )
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
                    if int(cached.get("update", -1)) == update:
                        checkpoint_reference = _milestone_checkpoint_for_update(
                            milestone_checkpoints, update)
                        _validate_milestone_evaluation(
                            cached, dataset=dataset, checkpoint=checkpoint_reference,
                            validation_cases=validation_cases,
                            validation_registry=validation_registry,
                        )
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
        target_tensor = _target_tensor(
            state, known, dt, target, prior, model_kind, device, normalization,
            prior_audit=prior_audit, update=update, case_id=case_id, frame=frame,
        )[centers_t]
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
                                            milestone_selection=milestone_selection,
                                            evidence=training_evidence(update))
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
                                     milestone_selection=milestone_selection,
                                     evidence=training_evidence(update))
    elapsed = time.perf_counter() - started
    checkpoint_info = save_training_checkpoint(checkpoint, model=model, optimizer=optimizer, sampler=sampler,
                                               normalization=normalization, update=updates,
                                               config=config, seed=seed,
                                               validation=(validation_history[-1] if validation_history else None),
                                               history=history, validation_history=validation_history,
                                               milestone_checkpoints=milestone_checkpoints,
                                               milestone_evaluations=milestone_evaluations,
                                               milestone_evaluation_plan=milestone_evaluation_plan,
                                               milestone_selection=milestone_selection,
                                               evidence=training_evidence(updates))
    result = {
        "schema": TRAINING_SCHEMA, "run_id": run_id, "model_kind": model_kind, "seed": seed,
        "device": str(device), "torch_version": torch.__version__, "host": platform.node(),
        "parameter_count": int(sum(p.numel() for p in model.parameters())),
        "completed_updates": updates, "checkpoint_verified": bool(checkpoint_info["sha256"]),
        "checkpoint": checkpoint_info, "normalization": normalization.as_dict(),
        "evidence": training_evidence(updates),
        "evidence_status": training_evidence(updates)["status"],
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
    known = _known_inputs_for_learning(dataset.known_inputs(case_id))
    measurements = []
    for step in range(min(int(steps), len(times) - 1)):
        started = time.perf_counter()
        prediction = predictor.predict_step(current, known, float(times[step + 1] - times[step]))
        current = commit(current, prediction, float(times[step + 1] - times[step]))
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


def rollout_case(dataset, case_id, predictor, *, maximum_steps=None, trajectory_output=None,
                 progress_output=None, progress_every=25):
    """Autonomously roll from frame zero; references are read only for scoring."""
    if isinstance(progress_every, bool) or int(progress_every) < 1:
        raise ValueError("progress_every must be a positive integer")
    progress_every = int(progress_every)
    times = dataset.times(case_id)
    known = _known_inputs_for_learning(dataset.known_inputs(case_id))
    current = dataset.read_state(case_id, 0)
    total_steps = len(times) - 1 if maximum_steps is None else min(int(maximum_steps), len(times) - 1)
    if total_steps < 1:
        raise ValueError("rollout requires at least one transition")
    progress_path = Path(progress_output) if progress_output is not None else None
    progress_started = time.perf_counter()

    def publish_progress(status, *, error=None):
        """Publish a small atomic sidecar while a large trajectory stays open."""
        if progress_path is None:
            return
        payload = {
            "schema": "core.rollout.progress.v1", "case_id": str(case_id),
            "status": str(status), "completed_frames": int(executed),
            "expected_frames": int(total_steps), "frames_expected": int(total_steps),
            "frames_executed": int(executed), "particles": int(current.count),
            "elapsed_seconds": float(time.perf_counter() - progress_started),
            "time_s": float(current.time_s), "trajectory_output": (
                str(trajectory_output) if trajectory_output is not None else None),
            "progress_every": progress_every, "autonomous": True,
            "future_state_inputs": False,
        }
        payload.update(rollout_completion_semantics(
            expected_frames=total_steps, frames_executed=executed,
            failure_category=failure_category,
            position_rmse=position_rmse, velocity_rmse=velocity_rmse,
        ))
        if failure_category is not None:
            payload["failure_category"] = failure_category
            payload["first_failure_frame"] = first_failure_frame
        if error is not None:
            payload["error"] = str(error)
        atomic_json(progress_path, payload)

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
    publish_progress("running")
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
                current = commit(previous, prediction, dt)
            except FloatingPointError:
                failure_category, first_failure_frame = "nonfinite_prediction", step + 1
                publish_progress("failed")
                break
            except ValueError as error:
                failure_category, first_failure_frame = "invalid_model_state", step + 1
                publish_progress("failed", error=error)
                break
            except Exception:
                failure_category, first_failure_frame = "model_execution_error", step + 1
                publish_progress("failed")
                break
            try:
                reference = dataset.read_state(case_id, step + 1)
            except Exception:
                failure_category, first_failure_frame = "reference_read_error", step + 1
                publish_progress("failed")
                break
            position_error = current.position - reference.position
            velocity_error = current.velocity - reference.velocity
            if not np.isfinite(position_error).all() or not np.isfinite(velocity_error).all():
                failure_category, first_failure_frame = "nonfinite_error", step + 1
                publish_progress("failed")
                break
            try:
                # A prescribed moving wall is a public schedule, so both
                # endpoint poses are causal known inputs.  Supplying both
                # snapshots lets the versioned saved-step physics diagnostic
                # use its swept finite-wall operator; legacy geometry remains
                # static and produces the same chord result.
                geometry_previous = _geometry_at(known, previous.time_s)
                geometry_current = _geometry_at(known, current.time_s)
                # Retain the public schedule as the first argument when it is
                # available.  This lets the diagnostic report its declared
                # rotation axis/angle while using the already materialized
                # current endpoint, without consulting any reference state.
                geometry_contract = getattr(known, "geometry", geometry_previous)
                physics_frames[step] = frame_physics(previous, current, reference,
                                                      geometry_contract, geometry_current)
            except Exception:
                failure_category, first_failure_frame = "physics_diagnostic_error", step + 1
                publish_progress("failed")
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
            if executed % progress_every == 0:
                publish_progress("running")
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
    publish_progress("completed" if executed == total_steps else "failed")
    length_m, speed_mps = _characteristic_scales(known)
    completion = rollout_completion_semantics(
        expected_frames=total_steps, frames_executed=executed,
        failure_category=failure_category,
        position_rmse=position_rmse, velocity_rmse=velocity_rmse,
    )
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
        **completion,
        "trajectory_output": str(trajectory_output) if trajectory_output is not None else None,
        "progress_output": str(progress_output) if progress_output is not None else None,
        "progress_every": progress_every,
        "autonomous": True, "future_state_inputs": False,
    }


def _characteristic_scales(known):
    vertices = _geometry_at(known, 0.0).triangles.reshape(-1, 3)
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


def _verified_checkpoint_reference(item, *, expected_update=None):
    """Bind a checkpoint reference to the bytes currently on disk."""
    reference = _checkpoint_reference(item)
    path = Path(reference["path"])
    try:
        observed_bytes = path.stat().st_size
        observed_hash = sha256_file(path)
    except OSError as error:
        raise ValueError(f"milestone checkpoint is unavailable: {path}") from error
    if expected_update is not None and int(reference.get("update", -1)) != int(expected_update):
        raise ValueError("milestone checkpoint update mismatch")
    if reference.get("sha256") != observed_hash:
        raise ValueError("milestone checkpoint ledger hash mismatch")
    if reference.get("bytes") is not None:
        try:
            reference_bytes = int(reference["bytes"])
        except (TypeError, ValueError):
            reference_bytes = -1
        if reference_bytes != observed_bytes:
            raise ValueError("milestone checkpoint ledger byte count mismatch")
    verified = dict(reference)
    verified["sha256"] = observed_hash
    verified["bytes"] = observed_bytes
    return verified


def _milestone_checkpoint_for_update(milestone_checkpoints, update):
    """Resolve and verify the single ledger checkpoint for one update."""
    matches = [item for item in milestone_checkpoints
               if int(item.get("update", -1)) == int(update)]
    if len(matches) != 1:
        raise ValueError(f"milestone ledger must contain one checkpoint at update {update}")
    return _verified_checkpoint_reference(matches[0], expected_update=update)


def _validate_milestone_evaluation(report, *, dataset, checkpoint,
                                    validation_cases, validation_registry):
    """Fail closed on persisted milestone reports before checkpoint selection.

    Milestone sidecars are intentionally recoverable artifacts rather than
    trusted inputs.  Resume may consume one only when it binds to the exact
    checkpoint and contains every registered validation case.  This keeps a
    partial/tampered sidecar from satisfying the four-node selector.
    """
    if not isinstance(report, dict) or report.get("schema") != "core.milestone_evaluation.v1":
        raise ValueError("milestone evaluation schema mismatch")
    checkpoint = _verified_checkpoint_reference(checkpoint)
    expected_update = int(checkpoint.get("update", -1))
    if int(report.get("update", -1)) != expected_update:
        raise ValueError("milestone evaluation update mismatch")
    if report.get("split") != "validation" or report.get("test_included") is not False:
        raise ValueError("milestone evaluation must be validation-only")
    checkpoint_report = report.get("checkpoint")
    if (not isinstance(checkpoint_report, dict)
            or checkpoint_report.get("sha256") != checkpoint.get("sha256")
            or checkpoint_report.get("bytes") != checkpoint.get("bytes")):
        raise ValueError("milestone evaluation checkpoint hash mismatch")
    expected_cases = tuple(validation_cases)
    expected_set = set(expected_cases)
    if int(report.get("validation_case_count", -1)) != len(expected_cases):
        raise ValueError("milestone evaluation validation denominator mismatch")
    registry = report.get("family_registry")
    if not isinstance(registry, dict) or set(registry) != expected_set:
        raise ValueError("milestone evaluation case registry mismatch")
    if any(registry[case_id] != validation_registry[case_id] for case_id in expected_cases):
        raise ValueError("milestone evaluation family registry mismatch")
    cases = report.get("cases")
    if not isinstance(cases, dict) or set(cases) != expected_set:
        raise ValueError("milestone evaluation is missing validation cases")
    denominators = report.get("fixed_denominator")
    if not isinstance(denominators, dict) or set(denominators) != expected_set:
        raise ValueError("milestone evaluation fixed denominator mismatch")
    # Rebuild every case score from the retained rollout arrays and the
    # dataset-owned physical scales.  Checking only the aggregate is
    # insufficient: a sidecar could otherwise replace one case's score with a
    # favorable value and update the aggregate to match while leaving a
    # truncated/NaN rollout attached to that case.
    from scripts.core_evaluation import score_case
    recomputed_scores = {}
    for case_id in expected_cases:
        expected_frames = len(dataset.times(case_id)) - 1
        denominator = denominators[case_id]
        if int(denominator.get("expected_frames", -1)) != expected_frames:
            raise ValueError("milestone evaluation frame denominator mismatch")
        expected_length, expected_speed = _characteristic_scales(dataset.known_inputs(case_id))
        try:
            if (float(denominator.get("length_m")) != expected_length
                    or float(denominator.get("speed_mps")) != expected_speed):
                raise ValueError("milestone evaluation physical denominator mismatch")
        except (TypeError, ValueError):
            raise ValueError("milestone evaluation physical denominator mismatch")
        row = cases[case_id]
        score = row.get("score") if isinstance(row, dict) else None
        rollout = row.get("rollout") if isinstance(row, dict) else None
        if not isinstance(score, dict) or not isinstance(rollout, dict):
            raise ValueError("milestone evaluation case row is incomplete")
        if int(score.get("expected_frames", -1)) != expected_frames:
            raise ValueError("milestone evaluation score denominator mismatch")
        if int(rollout.get("expected_frames", -1)) != expected_frames:
            raise ValueError("milestone evaluation rollout denominator mismatch")
        for name in ("position_rmse", "velocity_rmse"):
            values = rollout.get(name)
            if not isinstance(values, list) or len(values) != expected_frames:
                raise ValueError("milestone evaluation rollout frame coverage mismatch")
        try:
            recomputed_score = score_case(
                rollout["position_rmse"], rollout["velocity_rmse"],
                expected_frames=expected_frames, length_m=expected_length,
                speed_mps=expected_speed, executed=rollout.get("executed", False),
                failure_category=rollout.get("failure_category"),
            )
        except (TypeError, ValueError, KeyError) as error:
            raise ValueError("milestone evaluation case score is invalid") from error
        if canonical(score) != canonical(recomputed_score):
            raise ValueError("milestone evaluation case score mismatch")
        recomputed_scores[case_id] = recomputed_score
    metrics = report.get("metrics")
    if not isinstance(metrics, dict) or int(metrics.get("registered_cases", -1)) != len(expected_cases):
        raise ValueError("milestone evaluation aggregate denominator mismatch")
    # Recompute the selector input from the case rows.  A persisted sidecar is
    # an input to resume/selection and can be edited independently of its case
    # records; trusting its aggregate fields would let a tampered complete rate
    # or selection score choose a different checkpoint while all denominators
    # still appear valid.  The registered evaluator remains the single source
    # of ordering and penalty semantics (including missing/nonfinite frames).
    try:
        from scripts.core_evaluation import aggregate_cases
        recomputed_metrics = aggregate_cases(
            validation_registry, recomputed_scores)
        if canonical(metrics) != canonical(recomputed_metrics):
            raise ValueError("milestone evaluation aggregate metrics mismatch")
    except ValueError:
        raise
    except (KeyError, TypeError, ZeroDivisionError) as error:
        raise ValueError("milestone evaluation aggregate metrics are invalid") from error
    summary = report.get("execution_summary")
    if not isinstance(summary, dict) or int(summary.get("registered_case_count", -1)) != len(expected_cases):
        raise ValueError("milestone evaluation execution denominator mismatch")
    return report


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
        reference = _checkpoint_reference(matches[0])
        digest = reference.get("sha256")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest.lower())):
            raise ValueError(
                f"training receipt milestone at update {update} must include a SHA-256 hash")
        selected.append(reference)
    return selected


def _failed_rollout_receipt(dataset, case_id, error):
    """Make interrupted case evaluations scoreable without dropping frames."""
    times = dataset.times(case_id)
    known = dataset.known_inputs(case_id)
    length_m, speed_mps = _characteristic_scales(known)
    expected = max(0, len(times) - 1)
    failure_category = (
        "rollout_timeout"
        if isinstance(error, (TimeoutError, subprocess.TimeoutExpired))
        else "rollout_setup_error"
    )
    completion = rollout_completion_semantics(
        expected_frames=expected, frames_executed=0,
        failure_category=failure_category,
        position_rmse=[None] * expected, velocity_rmse=[None] * expected,
    )
    return {
        "schema": ROLLOUT_SCHEMA, "case_id": case_id,
        "frames_predicted": 0, "frames_expected": expected, "frames_executed": 0,
        "expected_frames": expected, "executed": False, "particles": None,
        "position_rmse": [None] * expected, "velocity_rmse": [None] * expected,
        "position_ade": [None] * expected, "velocity_ade": [None] * expected,
        "length_m": length_m, "speed_mps": speed_mps,
        "failure_category": failure_category, "first_failure_frame": 1 if expected else None,
        **completion,
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
    formal_eligible = _formal_validation_eligible(
        dataset, validation_cases, family_counts)
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
        "execution_summary": _execution_summary(case_rows),
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


def _validation_bootstrap_receipt(registry, scores, physical_case_ids):
    """Build CI metadata only from the complete registered case registry.

    ``bootstrap_case_interval`` intentionally treats an absent result as an
    all-penalty unexecuted case for its general scoring API.  A checkpoint
    receipt must be stricter: a missing bootstrap row is an incomplete
    validation product, not an observed penalty row.  Keep this guard here so
    the four candidates cannot silently bootstrap different denominators.
    """
    from scripts.core_evaluation import bootstrap_case_interval

    try:
        registry_keys = set(registry)
        score_keys = set(scores)
        physical_keys = set(physical_case_ids)
    except (TypeError, ValueError) as error:
        raise ValueError("checkpoint bootstrap registry keys must be hashable") from error
    if score_keys != registry_keys:
        raise ValueError(
            "checkpoint bootstrap requires complete registered validation results")
    if physical_keys != registry_keys:
        raise ValueError(
            "checkpoint bootstrap requires physical IDs for every registered validation case")

    bootstrap = bootstrap_case_interval(
        registry, scores, physical_case_ids=physical_case_ids)
    independent_cases_by_family = bootstrap.get("independent_cases_by_family")
    if not isinstance(independent_cases_by_family, dict) or not independent_cases_by_family:
        raise ValueError("checkpoint bootstrap did not retain independent case counts")
    if any(not isinstance(count, int) or count < 1
           for count in independent_cases_by_family.values()):
        raise ValueError("checkpoint bootstrap has invalid independent case counts")
    independent_case_count = sum(independent_cases_by_family.values())
    return {
        **bootstrap,
        "registered_case_count": len(registry_keys),
        "independent_case_count": int(independent_case_count),
        "sample_unit": "independent physical case cluster, never frame or particle",
        "cluster_key": "physical_case_id",
        "stratified_by": "family",
        "confidence_interval": {
            "confidence": bootstrap["confidence"],
            "lower": bootstrap["lower"],
            "upper": bootstrap["upper"],
        },
    }


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
        if not _manifest_formal_release(dataset):
            raise ValueError(
                "formal Core evaluation requires a V13 verified-reader capability; "
                "the legacy CoreDataset reader is diagnostic-only")
    lineage_group_ids = {case_id: dataset.record(case_id)["lineage_group_id"]
                         for case_id in validation_cases}
    physical_case_ids = {case_id: dataset.record(case_id)["physical_case_id"]
                         for case_id in validation_cases}
    formal_eligible = bool(not qualification_only and _manifest_formal_release(dataset))
    eligibility = {
        "mode": "diagnostic" if qualification_only else "formal",
        "diagnostic_eligible": bool(qualification_only),
        "formal_eligible": formal_eligible,
    }
    fixed_denominator = {}
    for case_id in validation_cases:
        known = dataset.known_inputs(case_id)
        length_m, speed_mps = _characteristic_scales(known)
        fixed_denominator[case_id] = {
            "expected_frames": len(dataset.times(case_id)) - 1,
            "length_m": length_m, "speed_mps": speed_mps,
        }

    dataset_manifest_sha256 = _dataset_manifest_sha256(dataset)
    loaded = []
    model_identity = None
    training_identity = None
    for ref in refs:
        path = Path(ref["path"])
        observed_hash = sha256_file(path)
        expected_hash = ref.get("sha256")
        if expected_hash and expected_hash != observed_hash:
            raise ValueError(f"checkpoint hash mismatch: {path}")
        predictor, payload = _build_predictor_from_checkpoint(path, device, chunk_size)
        checkpoint_update = int(payload.get("update", -1))
        if checkpoint_update not in MILESTONE_UPDATES:
            raise ValueError(
                f"checkpoint {path} has update {checkpoint_update}; expected one of {MILESTONE_UPDATES}")
        config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        saved_manifest_sha256 = config.get("manifest_sha256")
        if saved_manifest_sha256 is not None and dataset_manifest_sha256 is not None \
                and saved_manifest_sha256 != dataset_manifest_sha256:
            raise ValueError(f"checkpoint dataset manifest mismatch: {path}")
        saved_run_id = config.get("run_id")
        if run_id is not None and saved_run_id is not None and str(saved_run_id) != str(run_id):
            raise ValueError(f"checkpoint run_id mismatch: {path}")
        if not qualification_only:
            required_binding = (
                "run_id", "manifest_sha256", "centers_per_update", "learning_rate",
                "radius_over_h", "max_neighbors", "normalization_source_split",
                "target_normalization", "updates", "initialization", "paired_seed",
                "sampler_seed",
            )
            missing_binding = [key for key in required_binding if config.get(key) is None]
            if missing_binding:
                raise ValueError(
                    f"formal checkpoint {path} lacks training binding: {', '.join(missing_binding)}")
            if config.get("manifest_sha256") != dataset_manifest_sha256:
                raise ValueError(f"formal checkpoint manifest binding mismatch: {path}")
        identity = (payload.get("model_kind"), int(payload.get("seed", -1)), int(payload["hidden"]))
        if model_identity is None:
            model_identity = identity
        elif identity != model_identity:
            raise ValueError("formal checkpoints do not belong to one training run")
        normalization_digest = hashlib.sha256(
            canonical(payload.get("normalization")).encode()).hexdigest()
        binding = (
            config.get("run_id"), config.get("manifest_sha256"),
            config.get("centers_per_update"), config.get("learning_rate"),
            config.get("radius_over_h"), config.get("max_neighbors"),
            config.get("normalization_source_split"), config.get("target_normalization"),
            config.get("updates"), config.get("initialization"),
            config.get("paired_seed"), config.get("sampler_seed"), normalization_digest,
        )
        if training_identity is None:
            training_identity = binding
        elif binding != training_identity:
            raise ValueError("formal checkpoints do not share one training/data/normalization binding")
        loaded.append((path, observed_hash, predictor, payload))

    checkpoint_updates = sorted(int(item[3]["update"]) for item in loaded)
    if checkpoint_updates != list(MILESTONE_UPDATES):
        raise ValueError(
            f"formal checkpoint set must contain exactly {MILESTONE_UPDATES}; got {checkpoint_updates}")

    candidates = []
    for path, observed_hash, predictor, payload in loaded:
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
        bootstrap = _validation_bootstrap_receipt(
            registry, scores, physical_case_ids)
        checkpoint_info = {
            "path": str(path), "sha256": observed_hash, "bytes": path.stat().st_size,
            "update": int(payload["update"]), "schema": CHECKPOINT_SCHEMA,
            "checkpoint_verified": True,
        }
        candidates.append({
            "update": int(payload["update"]), "split": "validation", "metrics": metrics,
            "checkpoint": checkpoint_info, "case_count": len(case_rows), "cases": case_rows,
            "registered_case_count": len(validation_cases),
            "fixed_denominator": fixed_denominator,
            "physical_case_ids": physical_case_ids,
            "lineage_group_ids": lineage_group_ids,
            "qualification_only": bool(qualification_only),
            "formal_eligible": formal_eligible,
            "eligibility": eligibility,
            # Descriptive validation diagnostics only.  The selector below
            # continues to consume ``metrics`` and never uses CI eligibility.
            "point_estimate": bootstrap["point_estimate"],
            "confidence_interval": bootstrap["confidence_interval"],
            "independent_case_count": bootstrap["independent_case_count"],
            "independent_cases_by_family": bootstrap["independent_cases_by_family"],
            "bootstrap": bootstrap,
            "execution_summary": _execution_summary(case_rows),
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
        "formal_eligible": formal_eligible,
        "eligibility": eligibility,
        "validation_case_count": len(validation_cases),
        "validation_family_counts": dict(sorted(family_counts.items())),
        "protocol": PROTOCOL, "fixed_denominator": fixed_denominator,
        "physical_case_ids": physical_case_ids, "lineage_group_ids": lineage_group_ids,
        "family_registry": registry,
        "checkpoints": candidates, "checkpoint_count": len(candidates),
        "execution_summaries": {
            str(candidate["update"]): candidate["execution_summary"]
            for candidate in candidates
        },
        "selection": selection, "selection_error": selection_error,
        "autonomous": True, "future_state_inputs": False,
    }


def _diagnostic_case_selection(dataset, split, case_ids):
    """Select a known diagnostic scope without changing manifest split labels."""
    available = tuple(dataset.case_ids())
    available_set = set(available)
    if case_ids is None:
        selected = tuple(dataset.case_ids(split))
    elif isinstance(case_ids, str):
        selected = (case_ids,)
    else:
        selected = tuple(case_ids)
    if not selected:
        raise ValueError("no diagnostic evaluation cases selected")
    if len(set(selected)) != len(selected):
        raise ValueError("diagnostic evaluation case selection contains duplicate cases")
    unknown = [case_id for case_id in selected if case_id not in available_set]
    if unknown:
        raise ValueError(f"diagnostic evaluation contains unknown case(s): {unknown}")
    return selected


def _pad_rollout_to_expected_frames(rollout, expected_frames, *, horizon_limited=False):
    """Retain a fixed frame denominator when a diagnostic horizon is bounded."""
    if not isinstance(rollout, dict):
        raise ValueError("rollout result must be a mapping")
    expected_frames = _strict_integer(expected_frames, "expected_frames")
    if expected_frames < 1:
        raise ValueError("expected_frames must be positive")
    result = dict(rollout)
    observed_expected = result.get("expected_frames", expected_frames)
    observed_expected = _strict_integer(observed_expected, "rollout expected_frames")
    if observed_expected < 0 or observed_expected > expected_frames:
        raise ValueError("rollout expected_frames exceeds the fixed denominator")

    for name in ("position_rmse", "velocity_rmse", "position_ade", "velocity_ade"):
        values = result.get(name, [])
        if not isinstance(values, (list, tuple)) or len(values) > expected_frames:
            raise ValueError(f"rollout {name} exceeds the fixed denominator")
        result[name] = list(values) + [None] * (expected_frames - len(values))

    physics = result.get("physics", {})
    if not isinstance(physics, dict):
        raise ValueError("rollout physics must be a mapping")
    physics = dict(physics)
    physics_frames = physics.get("frames", [])
    if not isinstance(physics_frames, (list, tuple)) or len(physics_frames) > expected_frames:
        raise ValueError("rollout physics frame coverage exceeds the fixed denominator")
    physics_frames = list(physics_frames) + [None] * (expected_frames - len(physics_frames))
    physics_summary = physics.get("summary", {})
    if not isinstance(physics_summary, dict):
        raise ValueError("rollout physics summary must be a mapping")
    physics_summary = dict(physics_summary)
    physics_summary["expected_frames"] = expected_frames
    physics_summary["completed_frames"] = sum(frame is not None for frame in physics_frames)
    physics["frames"] = physics_frames
    physics["summary"] = physics_summary
    result["physics"] = physics

    frames_executed = result.get("frames_executed", result.get("frames_predicted", 0))
    frames_executed = _strict_integer(frames_executed, "frames_executed")
    if frames_executed < 0 or frames_executed > expected_frames:
        raise ValueError("invalid rollout frame count")
    result["frames_executed"] = frames_executed
    result["frames_predicted"] = frames_executed
    result["frames_expected"] = expected_frames
    result["expected_frames"] = expected_frames

    failure_category = result.get("failure_category")
    if observed_expected < expected_frames and failure_category is None:
        failure_category = "maximum_steps_limit" if horizon_limited else "missing_frames"
        result["failure_category"] = failure_category
        result["first_failure_frame"] = frames_executed + 1
    elif failure_category is not None and result.get("first_failure_frame") is None:
        result["first_failure_frame"] = frames_executed + 1

    completion = rollout_completion_semantics(
        expected_frames=expected_frames,
        frames_executed=frames_executed,
        failure_category=failure_category,
        position_rmse=result["position_rmse"],
        velocity_rmse=result["velocity_rmse"],
    )
    result["execution_complete"] = completion["execution_complete"]
    result["finite_rollout_complete"] = completion["finite_rollout_complete"]
    result.setdefault("scientific_status", SCIENTIFIC_STATUS_NOT_ASSESSED)
    result.setdefault("scientific_failure_category", None)
    result.setdefault("scientific_first_failure_frame", None)
    return result


def evaluate(dataset, predictor, *, split="test", case_ids=None, maximum_steps=None,
             diagnostic=False, model_kind=None, checkpoint=None, baseline=None,
             training=True, trajectory_output_for_case=None,
             progress_output_for_case=None, progress_every=25):
    """Evaluate a predictor with a fixed registered denominator.

    The legacy CoreDataset reader is diagnostic-only, even when its manifest
    declares ``formal_release``.  Formal evaluation requires the not-yet-
    implemented V13 verified-reader capability.  Diagnostic results retain
    the actual manifest split labels in the receipt.
    """
    from scripts.core_evaluation import aggregate_cases, score_case

    formal_release = _manifest_formal_release(dataset)
    formal_capacity = None
    if formal_release:
        if diagnostic:
            raise ValueError("formal manifests cannot use diagnostic evaluate")
        registered_case_ids = tuple(dataset.case_ids("test"))
        validation_case_ids = tuple(dataset.case_ids("validation"))
        test_family_counts = Counter(
            dataset.record(case_id)["family"] for case_id in registered_case_ids)
        validation_family_counts = Counter(
            dataset.record(case_id)["family"] for case_id in validation_case_ids)
        scope = formal_evaluation_gate(
            registered_case_ids=registered_case_ids,
            selected_case_ids=case_ids,
            split=split,
            maximum_steps=maximum_steps,
            test_family_counts=test_family_counts,
            validation_family_counts=validation_family_counts,
        )
        selected_case_ids = tuple(scope["case_ids"])
        formal_capacity = {
            "test_family_counts": scope["test_family_counts"],
            "validation_family_counts": scope["validation_family_counts"],
            "minimum_families": scope["minimum_families"],
            "minimum_validation_cases_per_family": scope[
                "minimum_validation_cases_per_family"],
            "minimum_test_cases_per_family": scope["minimum_test_cases_per_family"],
        }
        evaluation_mode = "formal"
    else:
        if maximum_steps is not None:
            maximum_steps = _strict_integer(maximum_steps, "maximum_steps")
            if maximum_steps < 1:
                raise ValueError("maximum_steps must be positive")
        selected_case_ids = _diagnostic_case_selection(dataset, split, case_ids)
        registered_case_ids = selected_case_ids
        evaluation_mode = "diagnostic"

    case_splits = {case_id: dataset.record(case_id)["split"] for case_id in selected_case_ids}
    fixed_denominator = _fixed_denominator_for_cases(dataset, registered_case_ids)
    registry = {case_id: dataset.record(case_id)["family"] for case_id in registered_case_ids}
    case_rows, scores = {}, {}
    for case_id in selected_case_ids:
        try:
            rollout = rollout_case(
                dataset, case_id, predictor,
                maximum_steps=(None if evaluation_mode == "formal" else maximum_steps),
                trajectory_output=(trajectory_output_for_case(case_id)
                                   if trajectory_output_for_case is not None else None),
                progress_output=(progress_output_for_case(case_id)
                                 if progress_output_for_case is not None else None),
                progress_every=progress_every,
            )
        except Exception as error:
            rollout = _failed_rollout_receipt(dataset, case_id, error)
        rollout = _pad_rollout_to_expected_frames(
            rollout, fixed_denominator[case_id]["expected_frames"],
            horizon_limited=(evaluation_mode == "diagnostic" and maximum_steps is not None),
        )
        score_failure_category = rollout.get("failure_category")
        if rollout.get("scientific_status") == "failed" and score_failure_category is None:
            score_failure_category = rollout.get("scientific_failure_category") or "scientific_failure"
        if (rollout.get("execution_complete") is not True
                or rollout.get("finite_rollout_complete") is not True) \
                and score_failure_category is None:
            score_failure_category = "incomplete_rollout"
        denominator = fixed_denominator[case_id]
        score = score_case(
            rollout["position_rmse"], rollout["velocity_rmse"],
            expected_frames=denominator["expected_frames"],
            length_m=denominator["length_m"], speed_mps=denominator["speed_mps"],
            executed=rollout.get("executed", False),
            failure_category=score_failure_category,
        )
        scores[case_id] = score
        # Keep the historical direct-evaluate shape (rollout fields at the
        # case-row top level) while adding protocol-bound score/rollout views.
        case_rows[case_id] = {**rollout, "score": score, "rollout": rollout}

    aggregate = aggregate_cases(registry, scores)
    execution_summary = _execution_summary(case_rows)
    finite_summary = _finite_summary(case_rows)
    observed_splits = set(case_splits.values())
    receipt_split = (next(iter(observed_splits)) if len(observed_splits) == 1 else "mixed")
    return {
        "schema": "core.evaluation.v1",
        "evaluation_mode": evaluation_mode,
        "diagnostic": evaluation_mode == "diagnostic",
        "formal_eligible": evaluation_mode == "formal",
        "model_kind": model_kind,
        "checkpoint": str(checkpoint) if checkpoint is not None else None,
        "baseline": baseline,
        "training": bool(training),
        "split": receipt_split,
        "requested_split": split,
        "test_included": "test" in observed_splits,
        "case_splits": case_splits,
        "registered_case_ids": list(registered_case_ids),
        "selected_case_ids": list(selected_case_ids),
        "registered_case_count": len(registered_case_ids),
        "case_count": len(case_rows),
        "formal_capacity": formal_capacity,
        "expected_frames": {
            case_id: denominator["expected_frames"]
            for case_id, denominator in fixed_denominator.items()
        },
        "fixed_denominator": fixed_denominator,
        "cases": case_rows,
        "aggregate": aggregate,
        "metrics": aggregate,
        "execution_summary": execution_summary,
        "finite_summary": finite_summary,
        "maximum_steps": maximum_steps,
        "autonomous": True,
        "future_state_inputs": False,
    }


def _manifest_path(manifest, data_root):
    """Resolve a learning manifest relative to the explicit data root.

    The benchmark wrapper can be launched from a worker directory that is
    unrelated to the bundle.  Keep train, rollout, and evaluate on the same
    portable manifest contract as inspect and verify rather than letting the
    process cwd choose a different file.
    """
    if not isinstance(manifest, (str, Path)):
        return manifest
    path = Path(manifest).expanduser()
    if not path.is_absolute():
        path = Path(data_root).expanduser() / path
    return path.resolve()


def _dataset(args):
    # F1/F4 production registrations carry CFD preparation metadata around
    # trajectories.  Keep the regular F3 reader as the fast path while letting
    # the dedicated adapter normalize those source records before training or
    # evaluation opens any HDF5 handle.
    try:
        from scripts.core_cfd_dataset import open_dataset
    except ImportError:
        open_dataset = None
    manifest = _manifest_path(args.manifest, args.data_root)
    if open_dataset is not None:
        return open_dataset(manifest, args.data_root)
    return CoreDataset(manifest, args.data_root)


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
        command.add_argument("--progress-output", type=Path,
                             help="atomic per-case rollout progress sidecar")
        command.add_argument("--progress-every", type=int, default=25,
                             help="publish rollout progress every N completed frames")
        command.add_argument("--output", type=Path, required=True)
        if name == "evaluate":
            command.add_argument("--diagnostic", action="store_true",
                                 help="run a non-formal diagnostic on a non-released manifest")

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
            path_case_ids = tuple(args.case_id or dataset.case_ids(args.split))
            if not path_case_ids:
                raise ValueError("no rollout cases selected")
            if args.trajectory_output is not None and args.trajectory_output_dir is not None:
                raise ValueError("--trajectory-output and --trajectory-output-dir are mutually exclusive")
            if args.trajectory_output is not None and len(path_case_ids) != 1:
                raise ValueError("--trajectory-output requires exactly one case; use --trajectory-output-dir for many")

            def case_trajectory_path(case_id):
                if args.trajectory_output_dir is not None:
                    args.trajectory_output_dir.mkdir(parents=True, exist_ok=True)
                    safe_case_id = "".join(char if (char.isalnum() or char in "-_.") else "_"
                                            for char in str(case_id))
                    return args.trajectory_output_dir / f"{safe_case_id}.h5"
                return args.trajectory_output

            def case_progress_path(case_id):
                if args.progress_output is None:
                    return None
                safe_case_id = "".join(char if (char.isalnum() or char in "-_.") else "_"
                                        for char in str(case_id))
                if len(path_case_ids) == 1:
                    return args.progress_output
                # Multiple case rollouts need independent sidecars so a
                # scheduler never mistakes one case's heartbeat for another.
                args.progress_output.mkdir(parents=True, exist_ok=True)
                return args.progress_output / f"{safe_case_id}-progress.json"

            if args.command == "evaluate":
                result = evaluate(
                    dataset, predictor, split=args.split, case_ids=args.case_id,
                    maximum_steps=args.maximum_steps, diagnostic=args.diagnostic,
                    model_kind=payload["model_kind"], checkpoint=source_checkpoint,
                    baseline=payload.get("baseline"), training=payload.get("training", True),
                    trajectory_output_for_case=case_trajectory_path,
                    progress_output_for_case=case_progress_path,
                    progress_every=args.progress_every,
                )
            else:
                results = {case_id: rollout_case(dataset, case_id, predictor,
                                                  maximum_steps=args.maximum_steps,
                                                  trajectory_output=case_trajectory_path(case_id),
                                                  progress_output=case_progress_path(case_id),
                                                  progress_every=args.progress_every)
                           for case_id in path_case_ids}
                result = {"schema": ROLLOUT_SCHEMA,
                          "model_kind": payload["model_kind"], "checkpoint": source_checkpoint,
                          "baseline": payload.get("baseline"), "training": payload.get("training", True),
                          "case_count": len(results), "cases": results,
                          "execution_summary": _execution_summary(results),
                          "autonomous": True, "future_state_inputs": False}
        atomic_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("cases", "history", "checkpoints")}, indent=2))
    if args.command == "evaluate-checkpoints" and result.get("selection") is None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
