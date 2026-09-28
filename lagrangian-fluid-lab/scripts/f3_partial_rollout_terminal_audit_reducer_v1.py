#!/usr/bin/env python3
"""Reduce partial F3 fresh-nonce rollout observations to a terminal audit.

This module is intentionally independent from the F3 terminal verifiers and
launchers.  It consumes only:

* a bounded ``core.rollout.progress.v1`` JSON sidecar;
* ``lstat`` metadata for the declared trajectory path; and
* the fact that the evaluation JSON is absent (also established with
  ``lstat``; the evaluation JSON is never opened).

It never opens HDF5, trajectory, checkpoint, or evaluation contents.  It does
not inspect or use a PID, process state, or process-proof file.  A progress
sidecar is an observation of a live/partial computation, never terminal
evidence.  Every accepted observation therefore emits
``blocked_partial_or_missing_terminal`` with zero credit.

The command-line interface prints a small JSON report by default.  An input
bundle may be supplied with ``--input``; otherwise the six current residual
and raw fresh-nonce namespaces are used as read-only defaults.  ``--output``
creates a new report file and never overwrites an existing file.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]

REPORT_SCHEMA = "core.f3.partial_rollout_terminal_audit_reducer.v1"
REPORT_ID = "f3-partial-rollout-terminal-audit-reducer-v1"
INPUT_SCHEMA = "core.f3.partial_rollout_terminal_audit_input.v1"
PROGRESS_SCHEMA = "core.rollout.progress.v1"

SEEDS = (17, 29, 43)
MODEL_KINDS = ("graph_residual", "graph_raw")
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = TRANSITIONS + 1

MAX_JSON_BYTES = 256 * 1024
MAX_JSON_DEPTH = 48
MAX_JSON_ARRAY_ITEMS = 1024
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEED_RE = re.compile(r"17|29|43")
FORBIDDEN_NAMESPACE_WORDS = ("partial", "legacy", "unknown")
PROGRESS_SUFFIX = "-evaluation-progress.json"
TRAJECTORY_SUFFIX = "-trajectory.h5"
EVALUATION_SUFFIX = "-evaluation.json"

STATUS = "blocked_partial_or_missing_terminal"

# These are the six fresh namespaces produced by the diagnostic rollouts.  A
# caller can replace them through an input bundle; keeping the default here
# makes the reducer directly useful without discovering arbitrary namespaces.
DEFAULT_NONCES: dict[tuple[str, int], str] = {
    ("graph_residual", 17): "f4b93914eea211e957eafa63b577c57b",
    ("graph_residual", 29): "1ec294efc2e953eafba49f2c161ba4e5",
    ("graph_residual", 43): "bb7d2304f4896d5e37ac9d5ffb1c795e",
    ("graph_raw", 17): "d8f2a6c0b4e97135f0c2d8a4e6b1937c",
    ("graph_raw", 29): "a9c3e7f1b5d02864e2a6c9f3b7d10485",
    ("graph_raw", 43): "e1b7d4a9c2f60835b9e3d7a1c5f02468",
}

DEFAULT_COMPLETED_FRAMES = {
    ("graph_residual", 17): 250,
    ("graph_residual", 29): 250,
    ("graph_residual", 43): 225,
    ("graph_raw", 17): 150,
    ("graph_raw", 29): 150,
    ("graph_raw", 43): 125,
}


class ReducerError(ValueError):
    """Malformed, unsafe, or contract-incompatible reducer input."""


def _fail(message: str) -> None:
    raise ReducerError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_json_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _walk_json(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        _fail(f"{name} exceeds maximum JSON nesting depth")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string object key")
            _walk_json(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_JSON_ARRAY_ITEMS:
            _fail(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _walk_json(item, f"{name}[{index}]", depth + 1)
        return
    _fail(f"{name} contains unsupported type {type(value).__name__}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _strict_int(value: Any, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        _fail(f"{name} must be an integer <= {maximum}")
    return value


def _strict_exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be a boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be an integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _safe_absolute_path(value: Any, name: str) -> Path:
    text = _string(value, name)
    path = Path(text)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    if text != os.path.normpath(text):
        _fail(f"{name} must use a normalized lexical path")
    if text != os.path.abspath(text):
        _fail(f"{name} must use a canonical absolute path")
    if text != os.path.sep and text.endswith(os.path.sep):
        _fail(f"{name} must not have a trailing separator")
    if any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} must not contain path traversal or alias components")
    return path


def _model_token(model_kind: str) -> str:
    if model_kind == "graph_residual":
        return "graph-residual"
    if model_kind == "graph_raw":
        return "graph-raw"
    _fail(f"unsupported model_kind: {model_kind!r}")


def _namespace_from_progress_path(path: Path, model_kind: str, seed: int) -> tuple[Path, str]:
    token = _model_token(model_kind)
    name = path.name
    if not name.endswith(PROGRESS_SUFFIX):
        _fail(f"progress path does not end in {PROGRESS_SUFFIX}")
    namespace_name = name[: -len(PROGRESS_SUFFIX)]
    lowered_namespace = namespace_name.lower()
    if any(word in lowered_namespace for word in FORBIDDEN_NAMESPACE_WORDS):
        _fail("progress namespace is partial, legacy, or unknown")
    pattern = (
        rf"^f3-{re.escape(token)}500-hidden16-seed(?P<seed>{SEED_RE.pattern})"
        rf"-full835-nonce(?P<nonce>[0-9a-f]{{32}})$"
    )
    match = re.fullmatch(pattern, namespace_name)
    if match is None:
        _fail("progress path is not a fixed fresh full835 nonce namespace")
    observed_seed = int(match.group("seed"))
    if observed_seed != seed:
        _fail(f"progress namespace seed drift: observed={observed_seed} expected={seed}")
    nonce = match.group("nonce")
    if nonce == "0" * 32:
        _fail("progress namespace nonce must be non-zero")
    namespace = path.with_name(namespace_name)
    return namespace, nonce


def _derived_path(namespace: Path, suffix: str) -> Path:
    return namespace.with_name(namespace.name + suffix)


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _component_snapshot(
    path: Path, name: str, *, allow_missing_leaf: bool = False
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Snapshot every existing path component without following symlinks."""
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    parts = path.parts[1:]
    current = Path(path.anchor or os.path.sep)
    snapshot: list[tuple[str, tuple[int, ...]]] = []
    for index, part in enumerate(parts):
        current /= part
        is_leaf = index == len(parts) - 1
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if allow_missing_leaf and is_leaf:
                return tuple(snapshot)
            _fail(f"{name} has a missing path component: {current}")
        except OSError as error:
            _fail(f"{name} component inspection failed: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink path component: {current}")
        if not is_leaf and not stat.S_ISDIR(info.st_mode):
            _fail(f"{name} has a non-directory parent component: {current}")
        snapshot.append((str(current), _stat_identity(info)))
    return tuple(snapshot)


def _same_lstat(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev == after.st_dev
        and before.st_ino == after.st_ino
        and before.st_mode == after.st_mode
        and before.st_nlink == after.st_nlink
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


def _lstat_metadata(path: Path, name: str) -> dict[str, Any]:
    """Return metadata without following or opening ``path``."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {
            "path": str(path),
            "exists": False,
            "lstat_only": True,
            "opened": False,
            "symlink": False,
            "regular": False,
            "hardlink": False,
        }
    except OSError as error:
        _fail(f"{name} lstat failed: {error}")
    symlink = stat.S_ISLNK(info.st_mode)
    regular = stat.S_ISREG(info.st_mode)
    return {
        "path": str(path),
        "exists": True,
        "lstat_only": True,
        "opened": False,
        "symlink": symlink,
        "regular": regular,
        "hardlink": info.st_nlink != 1,
        "bytes": int(info.st_size),
        "mode": stat.S_IMODE(info.st_mode),
        "links": int(info.st_nlink),
    }


def _read_bounded_json(path: Path, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read only a small JSON sidecar with a no-follow, identity-stable fd."""
    components_before = _component_snapshot(path, name, allow_missing_leaf=True)
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        _fail(f"{name} is missing")
    except OSError as error:
        _fail(f"{name} lstat failed: {error}")
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        _fail(f"{name} must be a regular non-symlink file")
    if before.st_nlink != 1:
        _fail(f"{name} must not be a hardlink")
    if before.st_size > MAX_JSON_BYTES:
        _fail(f"{name} exceeds bounded JSON size: {before.st_size}>{MAX_JSON_BYTES}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"{name} could not be opened safely: {error}")
    try:
        opened = os.fstat(fd)
        if not _same_lstat(before, opened):
            _fail(f"{name} changed before bounded read")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_JSON_BYTES:
            chunk = os.read(fd, min(65536, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                _fail(f"{name} exceeds bounded JSON size")
        after = os.fstat(fd)
        if not _same_lstat(opened, after):
            _fail(f"{name} changed during bounded read")
    finally:
        os.close(fd)
    try:
        after_path = os.lstat(path)
    except OSError as error:
        _fail(f"{name} could not be re-stated safely: {error}")
    if not _same_lstat(opened, after_path):
        _fail(f"{name} changed after bounded read")
    components_after = _component_snapshot(path, name)
    if components_before != components_after:
        _fail(f"{name} parent path changed during bounded read")
    raw = b"".join(chunks)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail(f"{name} is not UTF-8 JSON: {error}")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except RecursionError as error:
        _fail(f"{name} exceeds bounded JSON nesting depth: {error}")
    except json.JSONDecodeError as error:
        _fail(f"{name} is not valid JSON: {error}")
    try:
        _walk_json(value, name)
    except RecursionError as error:
        _fail(f"{name} exceeds bounded JSON nesting depth: {error}")
    payload = _mapping(value, name)
    return dict(payload), {
        "path": str(path),
        "exists": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "opened": True,
        "lstat_only": False,
        "symlink": False,
        "regular": True,
        "hardlink": False,
    }


def _validate_observation_identity(
    observation: Mapping[str, Any], *, expected_model: str, expected_seed: int
) -> tuple[Path, Path, Path, Path, str]:
    allowed = {
        "model_kind",
        "seed",
        "progress_path",
        "trajectory_path",
        "evaluation_path",
        "evaluation_missing",
    }
    unknown = set(observation) - allowed
    if unknown:
        _fail(f"observation has unknown keys: {sorted(unknown)!r}")
    _strict_exact(observation, "model_kind", expected_model, "observation")
    _strict_exact(observation, "seed", expected_seed, "observation")
    progress = _safe_absolute_path(observation.get("progress_path"), "observation.progress_path")
    trajectory = _safe_absolute_path(observation.get("trajectory_path"), "observation.trajectory_path")
    evaluation = _safe_absolute_path(observation.get("evaluation_path"), "observation.evaluation_path")
    namespace, nonce = _namespace_from_progress_path(progress, expected_model, expected_seed)
    expected_trajectory = _derived_path(namespace, TRAJECTORY_SUFFIX)
    expected_evaluation = _derived_path(namespace, EVALUATION_SUFFIX)
    if trajectory != expected_trajectory:
        _fail("trajectory path is not derived from the fresh nonce namespace")
    if evaluation != expected_evaluation:
        _fail("evaluation path is not derived from the fresh nonce namespace")
    if "evaluation_missing" in observation:
        _strict_bool(observation["evaluation_missing"], "observation.evaluation_missing")
    return progress, trajectory, evaluation, namespace, nonce


def _validate_progress(
    progress: Mapping[str, Any], *, trajectory: Path, expected_model: str, expected_seed: int
) -> tuple[int, dict[str, Any], list[str]]:
    _strict_exact(progress, "schema", PROGRESS_SCHEMA, "progress")
    _strict_exact(progress, "case_id", CASE_ID, "progress")
    _strict_exact(progress, "expected_frames", TRANSITIONS, "progress")
    _strict_exact(progress, "frames_expected", TRANSITIONS, "progress")
    _strict_exact(progress, "autonomous", True, "progress")
    _strict_exact(progress, "future_state_inputs", False, "progress")
    completed = _strict_int(
        progress.get("completed_frames"), "progress.completed_frames", maximum=TRANSITIONS
    )
    executed = _strict_int(
        progress.get("frames_executed"), "progress.frames_executed", maximum=TRANSITIONS
    )
    if completed != executed:
        _fail("progress.completed_frames disagrees with progress.frames_executed")
    trajectory_output = progress.get("trajectory_output")
    if trajectory_output != str(trajectory):
        _fail("progress.trajectory_output is not the declared trajectory path")
    model_observed = progress.get("model_kind")
    seed_observed = progress.get("seed")
    # Current core rollout progress does not carry model/seed, so these fields
    # are optional.  If a producer supplies them, they must agree exactly.
    if model_observed is not None and model_observed != expected_model:
        _fail("progress.model_kind drift")
    if seed_observed is not None and seed_observed != expected_seed:
        _fail("progress.seed drift")

    reasons = [
        "progress_is_observation_only",
        "partial_frames_below_expected" if completed < TRANSITIONS else "terminal_frame_count_not_sufficient_for_promotion",
        "execution_complete_forced_false",
        "finite_rollout_complete_forced_false",
        "evaluation_missing_or_not_read",
        "process_proof_missing",
    ]
    # Even a producer's premature/optimistic marker is never promoted.  The
    # reducer records the observed value but emits false for both terminal
    # booleans unconditionally.
    if "execution_complete" not in progress or progress.get("execution_complete") is not False:
        reasons.append("progress_execution_marker_not_false_or_missing")
    if "finite_rollout_complete" not in progress or progress.get("finite_rollout_complete") is not False:
        reasons.append("progress_finite_marker_not_false_or_missing")
    status = progress.get("status")
    if status == "completed":
        reasons.append("progress_completed_status_cannot_promote_terminal")
    elif status not in {"running", "failed"}:
        reasons.append("progress_status_not_accepted_as_terminal_evidence")
    observed = {
        "schema": PROGRESS_SCHEMA,
        "status": status,
        "completed_frames": completed,
        "frames_executed": executed,
        "expected_frames": TRANSITIONS,
        "frames_expected": TRANSITIONS,
        "execution_complete": False,
        "finite_rollout_complete": False,
        "future_state_inputs": False,
        "opened": True,
        "terminal_authority": False,
    }
    return completed, observed, list(dict.fromkeys(reasons))


def _empty_side_effects() -> dict[str, Any]:
    return {
        "runtime_started": False,
        "evaluator_started": False,
        "evaluator_stopped": False,
        "evaluator_restarted": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "live_pid_observed": False,
        "live_pid_used_as_terminal": False,
        "progress_used_as_terminal": False,
        "hdf5_opened": False,
        "trajectory_opened": False,
        "checkpoint_opened": False,
        "evaluation_opened": False,
        "process_proof_opened": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "gate_mutation": 0,
        "denominator_mutation": 0,
    }


def _input_boundary() -> dict[str, Any]:
    return {
        "progress_json_bounded_read_only": True,
        "trajectory_lstat_only": True,
        "evaluation_lstat_only": True,
        "hdf5_content_opened": False,
        "checkpoint_content_opened": False,
        "evaluation_content_opened": False,
        "live_pid_observed": False,
        "process_proof_consumed": False,
        "terminal_promotion": False,
        "credit_minted": False,
    }


def _base_row(model_kind: str, seed: int) -> dict[str, Any]:
    return {
        "model_kind": model_kind,
        "seed": seed,
        "status": STATUS,
        "terminal_status": "not_terminal",
        "terminal_promotion": False,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "observed_completed_frames": None,
        "execution_complete": False,
        "finite_rollout_complete": False,
        "evaluation_missing": True,
        "process_proof_missing": True,
        "progress": None,
        "trajectory": None,
        "evaluation": None,
        "process_proof": {
            "status": "missing",
            "missing": True,
            "opened": False,
            "consumed": False,
        },
        "blocked_reasons": [],
        "side_effects": _empty_side_effects(),
        "input_boundary": _input_boundary(),
    }


def _context_from_observation(observation: Any, expected_model: str, expected_seed: int) -> dict[str, Any]:
    row = _base_row(expected_model, expected_seed)
    if not isinstance(observation, Mapping):
        row["blocked_reasons"] = ["observation_missing_or_not_object"]
        return row
    for key in ("progress_path", "trajectory_path", "evaluation_path"):
        value = observation.get(key)
        if isinstance(value, str) and "\x00" not in value:
            row[key] = value
    return row


def audit_observation(
    observation: Mapping[str, Any], *, expected_model: str, expected_seed: int
) -> dict[str, Any]:
    """Audit one observation and always return a non-terminal row."""
    row = _context_from_observation(observation, expected_model, expected_seed)
    try:
        progress_path, trajectory_path, evaluation_path, namespace, nonce = (
            _validate_observation_identity(
                observation, expected_model=expected_model, expected_seed=expected_seed
            )
        )
        progress, progress_meta = _read_bounded_json(progress_path, "progress JSON")
        trajectory_meta = _lstat_metadata(trajectory_path, "trajectory")
        evaluation_meta = _lstat_metadata(evaluation_path, "evaluation JSON")
        completed, observed_progress, reasons = _validate_progress(
            progress,
            trajectory=trajectory_path,
            expected_model=expected_model,
            expected_seed=expected_seed,
        )
        row.update(
            {
                "namespace": str(namespace),
                "namespace_nonce": nonce,
                "observed_completed_frames": completed,
                "execution_complete": False,
                "finite_rollout_complete": False,
                "evaluation_missing": not bool(evaluation_meta.get("exists")),
                "progress": {**progress_meta, "observed": observed_progress},
                "trajectory": trajectory_meta,
                "evaluation": {
                    **evaluation_meta,
                    "missing": not bool(evaluation_meta.get("exists")),
                    "opened": False,
                    "content_opened": False,
                },
                "blocked_reasons": reasons,
            }
        )
        claimed_missing = observation.get("evaluation_missing")
        actual_missing = not bool(evaluation_meta.get("exists"))
        if claimed_missing is not None and claimed_missing != actual_missing:
            row["blocked_reasons"].append("evaluation_missing_fact_drift")
        if not trajectory_meta.get("exists"):
            row["blocked_reasons"].append("trajectory_missing")
        elif not trajectory_meta.get("regular") or trajectory_meta.get("symlink") or trajectory_meta.get("hardlink"):
            row["blocked_reasons"].append("trajectory_lstat_not_safe_regular_single_link")
        if not evaluation_meta.get("exists"):
            row["blocked_reasons"].append("evaluation_missing")
        else:
            row["blocked_reasons"].append("evaluation_present_but_never_opened")
        row["blocked_reasons"] = list(dict.fromkeys(row["blocked_reasons"]))
        return row
    except ReducerError as error:
        row["blocked_reasons"] = [str(error)]
        # Invalid namespace/path input is deliberately not dereferenced.  In
        # particular, this branch cannot turn a partial/legacy/unknown path
        # into a terminal row.
        return row


def _default_observations() -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for model_kind in MODEL_KINDS:
        token = _model_token(model_kind)
        for seed in SEEDS:
            nonce = DEFAULT_NONCES[(model_kind, seed)]
            namespace = Path(
                f"/tmp/f3-{token}500-hidden16-seed{seed}-full835-nonce{nonce}"
            )
            observations.append(
                {
                    "model_kind": model_kind,
                    "seed": seed,
                    "progress_path": str(namespace) + PROGRESS_SUFFIX,
                    "trajectory_path": str(namespace) + TRAJECTORY_SUFFIX,
                    "evaluation_path": str(namespace) + EVALUATION_SUFFIX,
                }
            )
    return observations


def _missing_row(model_kind: str, seed: int, reason: str) -> dict[str, Any]:
    row = _base_row(model_kind, seed)
    row["blocked_reasons"] = [reason, "process_proof_missing", "evaluation_missing"]
    return row


def _expected_keys() -> tuple[tuple[str, int], ...]:
    return tuple((model_kind, seed) for model_kind in MODEL_KINDS for seed in SEEDS)


def build_report(
    observations: Sequence[Mapping[str, Any]] | None = None,
    *,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the six-row fail-closed partial terminal audit."""
    supplied = list(_default_observations() if observations is None else observations)
    expected = _expected_keys()
    by_key: dict[tuple[str, int], Mapping[str, Any]] = {}
    global_reasons: list[str] = []
    for index, observation in enumerate(supplied):
        if not isinstance(observation, Mapping):
            global_reasons.append(f"observation[{index}]_not_object")
            continue
        model = observation.get("model_kind")
        seed = observation.get("seed")
        key = (model, seed) if isinstance(model, str) and type(seed) is int else None
        if key not in expected:
            global_reasons.append(f"observation[{index}]_unknown_model_or_seed")
            continue
        if key in by_key:
            global_reasons.append(f"observation[{index}]_duplicate_model_seed")
            continue
        by_key[key] = observation

    rows: list[dict[str, Any]] = []
    for model_kind, seed in expected:
        observation = by_key.get((model_kind, seed))
        if observation is None:
            row = _missing_row(model_kind, seed, "observation_missing")
        else:
            row = audit_observation(
                observation, expected_model=model_kind, expected_seed=seed
            )
        rows.append(row)
    blocked_reasons = list(dict.fromkeys(global_reasons + [reason for row in rows for reason in row["blocked_reasons"]]))
    observed_frames = {
        model_kind: {
            str(seed): next(
                row["observed_completed_frames"]
                for row in rows
                if row["model_kind"] == model_kind and row["seed"] == seed
            )
            for seed in SEEDS
        }
        for model_kind in MODEL_KINDS
    }
    report = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": STATUS,
        "fail_closed": True,
        "source_bound": False,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "expected_contract": {
            "models": list(MODEL_KINDS),
            "seeds": list(SEEDS),
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "fresh_namespace": "f3-{graph-residual|graph-raw}500-hidden16-seed{17|29|43}-full835-nonce<32 lowercase hex>",
            "terminal_status": "not_terminal",
            "progress_or_live_pid_is_not_completion": True,
        },
        "observed_completed_frames": observed_frames,
        "seed_matrix": rows,
        "blocked_reasons": blocked_reasons,
        "side_effects": _empty_side_effects(),
        "input_boundary": _input_boundary(),
        "observed_at_utc": observed_at_utc or datetime.now(timezone.utc).isoformat(),
    }
    errors = validate_report(report)
    if errors:
        raise ReducerError("internal report validation failed: " + "; ".join(errors))
    return report


ROW_REQUIRED_KEYS = frozenset(
    {
        "model_kind",
        "seed",
        "status",
        "terminal_status",
        "terminal_promotion",
        "diagnostic_only",
        "formal",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "qualification_credit",
        "credit",
        "hidden",
        "updates",
        "case_id",
        "split",
        "transitions",
        "frames",
        "observed_completed_frames",
        "execution_complete",
        "finite_rollout_complete",
        "evaluation_missing",
        "process_proof_missing",
        "progress",
        "trajectory",
        "evaluation",
        "process_proof",
        "blocked_reasons",
        "side_effects",
        "input_boundary",
    }
)
ROW_ALLOWED_KEYS = ROW_REQUIRED_KEYS | frozenset(
    {"progress_path", "trajectory_path", "evaluation_path", "namespace", "namespace_nonce"}
)
ROW_EXACT_FIELDS: tuple[tuple[str, Any], ...] = (
    ("status", STATUS),
    ("terminal_status", "not_terminal"),
    ("terminal_promotion", False),
    ("diagnostic_only", True),
    ("formal", False),
    ("formal_eligible", False),
    ("T1_numerical", False),
    ("T2_macro", False),
    ("T2_path", False),
    ("qualification", False),
    ("qualification_credit", 0),
    ("credit", 0),
    ("hidden", HIDDEN),
    ("updates", UPDATES),
    ("case_id", CASE_ID),
    ("split", SPLIT),
    ("transitions", TRANSITIONS),
    ("frames", FRAMES),
    ("execution_complete", False),
    ("finite_rollout_complete", False),
    ("process_proof_missing", True),
)


def _exact_value_matches(observed: Any, expected: Any) -> bool:
    """Match both value and scalar type so ``False`` cannot stand in for ``0``."""
    return type(observed) is type(expected) and observed == expected


def validate_report(report: Any) -> list[str]:
    """Validate that an untrusted report remains a blocked zero-credit audit."""
    errors: list[str] = []
    if not isinstance(report, Mapping):
        return ["report must be an object"]
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("schema drift")
    if report.get("status") != STATUS:
        errors.append("report status must remain blocked_partial_or_missing_terminal")
    for key, expected in (
        ("fail_closed", True),
        ("source_bound", False),
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("T1_numerical", False),
        ("T2_macro", False),
        ("T2_path", False),
        ("qualification", False),
        ("qualification_credit", 0),
        ("credit", 0),
    ):
        if not _exact_value_matches(report.get(key), expected):
            errors.append(f"{key} must be {expected!r}")
    rows = report.get("seed_matrix")
    if not isinstance(rows, list) or len(rows) != len(_expected_keys()):
        errors.append("seed_matrix must contain exactly six rows")
        return errors
    seen: set[tuple[Any, Any]] = set()
    expected_set = set(_expected_keys())
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"seed_matrix[{index}] must be an object")
            continue
        unknown_fields = [
            key for key in row if not isinstance(key, str) or key not in ROW_ALLOWED_KEYS
        ]
        if unknown_fields:
            errors.append(f"seed_matrix[{index}] has unknown fields: {unknown_fields!r}")
        missing_fields = [key for key in sorted(ROW_REQUIRED_KEYS) if key not in row]
        if missing_fields:
            errors.append(f"seed_matrix[{index}] is missing fields: {missing_fields!r}")
        key = (row.get("model_kind"), row.get("seed"))
        if key in seen:
            errors.append(f"seed_matrix[{index}] duplicates model/seed")
        seen.add(key)
        if key not in expected_set:
            errors.append(f"seed_matrix[{index}] has unknown model/seed")
        for field, expected in (("model_kind", key[0]), ("seed", key[1])) + ROW_EXACT_FIELDS:
            if field not in row:
                continue
            if not _exact_value_matches(row[field], expected):
                errors.append(f"seed_matrix[{index}].{field} must be {expected!r}")
        if "evaluation_missing" in row and type(row.get("evaluation_missing")) is not bool:
            errors.append(f"seed_matrix[{index}].evaluation_missing must be boolean")
        observed = row.get("observed_completed_frames")
        if observed is not None and (type(observed) is not int or not 0 <= observed <= TRANSITIONS):
            errors.append(f"seed_matrix[{index}].observed_completed_frames is invalid")
        if "blocked_reasons" in row and not isinstance(row.get("blocked_reasons"), list):
            errors.append(f"seed_matrix[{index}].blocked_reasons must be an array")
        if "process_proof" in row and not isinstance(row.get("process_proof"), Mapping):
            errors.append(f"seed_matrix[{index}].process_proof must be an object")
        progress = row.get("progress")
        if progress is not None:
            if not isinstance(progress, Mapping):
                errors.append(f"seed_matrix[{index}].progress must be null or an object")
            else:
                digest = progress.get("sha256")
                if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
                    errors.append(f"seed_matrix[{index}].progress.sha256 must be a SHA-256 digest")
                if not _exact_value_matches(progress.get("opened"), True):
                    errors.append(f"seed_matrix[{index}].progress.opened must be true")
        boundary = row.get("input_boundary")
        if not isinstance(boundary, Mapping):
            errors.append(f"seed_matrix[{index}] has a missing input boundary")
        else:
            for field, expected in _input_boundary().items():
                if field not in boundary:
                    errors.append(f"seed_matrix[{index}].input_boundary is missing {field}")
                elif not _exact_value_matches(boundary[field], expected):
                    errors.append(
                        f"seed_matrix[{index}].input_boundary.{field} must be {expected!r}"
                    )
            unknown_boundary = [key for key in boundary if key not in _input_boundary()]
            if unknown_boundary:
                errors.append(
                    f"seed_matrix[{index}].input_boundary has unknown fields: {unknown_boundary!r}"
                )
        row_effects = row.get("side_effects")
        if not isinstance(row_effects, Mapping):
            errors.append(f"seed_matrix[{index}] has missing side_effects")
        else:
            for field, expected in _empty_side_effects().items():
                if field not in row_effects:
                    errors.append(f"seed_matrix[{index}].side_effects is missing {field}")
                elif not _exact_value_matches(row_effects[field], expected):
                    errors.append(
                        f"seed_matrix[{index}].side_effects.{field} must be {expected!r}"
                    )
            unknown_effects = [key for key in row_effects if key not in _empty_side_effects()]
            if unknown_effects:
                errors.append(
                    f"seed_matrix[{index}].side_effects has unknown fields: {unknown_effects!r}"
                )
    if seen != expected_set:
        errors.append("seed_matrix does not cover exactly residual/raw seeds 17/29/43")
    side_effects = report.get("side_effects")
    if not isinstance(side_effects, Mapping):
        errors.append("report side_effects missing")
    else:
        for key in (
            "runtime_started",
            "evaluator_started",
            "evaluator_stopped",
            "evaluator_restarted",
            "live_pid_observed",
            "live_pid_used_as_terminal",
            "progress_used_as_terminal",
            "hdf5_opened",
            "trajectory_opened",
            "checkpoint_opened",
            "evaluation_opened",
        ):
            if side_effects.get(key) is not False:
                errors.append(f"report side_effects.{key} must be false")
    return errors


def _load_input_bundle(path: Path) -> list[Mapping[str, Any]]:
    payload, _ = _read_bounded_json(path, "input bundle")
    _strict_exact(payload, "schema", INPUT_SCHEMA, "input")
    observations = payload.get("observations")
    if not isinstance(observations, list):
        _fail("input.observations must be an array")
    if len(observations) > len(_expected_keys()) * 2:
        _fail("input.observations contains too many entries")
    result: list[Mapping[str, Any]] = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            _fail(f"input.observations[{index}] must be an object")
        result.append(observation)
    return result


def _write_new_report(path: Path, report: Mapping[str, Any]) -> None:
    if not path.is_absolute() or ".." in path.parts:
        _fail("output path must be absolute and must not contain parent traversal")
    data = (canonical_json(report) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as error:
        if error.errno == errno.EEXIST:
            _fail("output path already exists; refusing overwrite")
        _fail(f"output path could not be created: {error}")
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                _fail("output write made no progress")
            view = view[written:]
    finally:
        os.close(fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="bounded JSON observation bundle")
    parser.add_argument("--output", type=Path, help="new JSON report path; never overwritten")
    args = parser.parse_args(argv)
    try:
        observations = _load_input_bundle(args.input) if args.input is not None else None
        report = build_report(observations)
        if args.output is not None:
            _write_new_report(args.output, report)
        else:
            print(canonical_json(report))
        return 0
    except ReducerError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
