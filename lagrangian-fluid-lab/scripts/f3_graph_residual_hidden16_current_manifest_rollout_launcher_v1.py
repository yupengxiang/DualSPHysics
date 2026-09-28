#!/usr/bin/env python3
"""Bounded current-manifest graph_residual/hidden16 full835 contract.

This module is the current-manifest counterpart of the historical
graph_residual terminal contracts.  It intentionally stops at two safe
boundaries:

* :func:`build_plan` reads the fixed current manifest and one explicit v3
  ``core.training.v1`` receipt as bounded JSON.  It only performs metadata
  checks on the declared checkpoint and constructs one fresh full835 command
  identity.  It never starts, stops, or restarts a process.
* :func:`verify_terminal_receipt` consumes one bounded terminal receipt and
  performs ``lstat``-only checks on the declared output artifacts.  It never
  opens checkpoint, HDF5, trajectory, evaluation, or progress content.

The contract is diagnostic-only and permanently zero-credit.  A future
executor may be connected only behind an independently audited execute
capability; this file deliberately has no process-launch path.  In
particular, ``launch_allowed`` is always false and preparation cannot be
mistaken for terminal evidence.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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

SEEDS = (17, 29, 43)
GPU_COUNT = 8
MODEL = "graph_residual"
HIDDEN = 16
UPDATES = 500
PARAMETER_COUNT = 6086
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836
CHUNK_SIZE = 34560
PROGRESS_EVERY = 25

MANIFEST_RELATIVE = Path("campaigns/core-v1/f3-dataset-v2.json")
MANIFEST_SCHEMA = "core.dataset.v2"
MANIFEST_DATASET_ID = "F3_registered32_core_native_v2"
CURRENT_CANONICAL_MANIFEST_SHA256 = "5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768"
CURRENT_MANIFEST_RAW_SHA256 = "8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680"

TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
SCHEMA = "core.f3.graph_residual.hidden16.current_manifest_rollout_launcher_plan.v1"
TERMINAL_RECEIPT_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.full835_terminal_receipt.v1"
PROCESS_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.process_exit_proof.v1"
REPORT_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.full835_rollout_contract.v1"
REPORT_ID = "f3-graph-residual-hidden16-current-manifest-full835-rollout-contract-v1"

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
MAX_DECLARED_BYTES = 1 << 50
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(
    r"^f3-graph_residual500-hidden16-currentmanifest-seed"
    r"(?P<seed>17|29|43)-(?P<date>20[0-9]{6})-v3$"
)
NAMESPACE_RE = re.compile(
    r"^f3-graph-residual500-hidden16-currentmanifest-seed"
    r"(?P<seed>17|29|43)-full835-nonce(?P<nonce>[0-9a-f]{32})$"
)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

ZERO_CREDIT = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}

STATIC_CONFIG: dict[str, Any] = {
    "centers_per_update": 256,
    "checkpoint_every": 500,
    "evaluate_milestones": False,
    "gradient_clipping": None,
    "hidden": HIDDEN,
    "history_states": 1,
    "initialization": "core.paired_initialization.common_encoder_head.v1",
    "learning_rate": 0.001,
    "log_every": 100,
    "manifest_formal_release": False,
    "max_neighbors": 192,
    "milestone_evaluation_mode": "deferred",
    "model_kind": MODEL,
    "normalization_source_split": "train",
    "optimizer": "Adam",
    "radius_over_h": 2.0,
    "target_normalization": "raw_dual_increment_train_shared",
    "updates": UPDATES,
    "validation_case_count": 4,
    "validation_centers": 256,
    "validation_every": 0,
    "validation_family_counts": {"F3": 4},
    "validation_formal_eligible": False,
    "validation_transition_count": 4,
}

TERMINAL_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "status",
        "source_bound",
        "diagnostic_only",
        "formal",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "qualification_credit",
        "credit",
        "seed",
        "run_id",
        "namespace",
        "namespace_nonce",
        "model_kind",
        "hidden",
        "updates",
        "case_id",
        "split",
        "transitions",
        "frames",
        "manifest_sha256",
        "training_receipt",
        "checkpoint",
        "command",
        "process_exit_proof",
        "terminal_markers",
        "evaluation",
        "trajectory",
        "progress",
        "hdf5_validator",
        "side_effects",
        "input_boundary",
    }
)
ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes", "content_opened", "stat_only"})
EVALUATION_KEYS = ARTIFACT_KEYS | frozenset(
    {
        "schema",
        "model_kind",
        "seed",
        "hidden",
        "updates",
        "case_id",
        "split",
        "evaluation_mode",
        "diagnostic",
        "autonomous",
        "maximum_steps",
        "transitions",
        "frames",
        "execution_complete",
        "finite_rollout_complete",
        "future_state_inputs",
        "status",
        "namespace",
        "namespace_fresh",
        "namespace_nonce",
    }
)
VALIDATOR_KEYS = ARTIFACT_KEYS | frozenset(
    {
        "schema",
        "passed",
        "complete",
        "diagnostic_only",
        "case_id",
        "expected_transitions",
        "frames_executed",
        "trajectory_frames",
        "trajectory_transitions",
        "tail_frame_count",
        "qualification_credit",
        "credit",
        "production_artifacts_touched",
        "actual_future_state_inputs",
    }
)


class LauncherError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing launcher input."""


def _fail(message: str) -> None:
    raise LauncherError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _walk_json(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        _fail(f"{name} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, str, int)):
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_STRING_BYTES:
            _fail(f"{name} contains an oversized string")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} contains a non-string key")
            _walk_json(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_ARRAY_ITEMS:
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
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        _fail(f"{name} is oversized")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be boolean")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA256_RE.fullmatch(text) is None:
        _fail(f"{name} must be a lowercase SHA-256 digest")
    return text


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if isinstance(expected, bool) and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _unknown(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    extra = sorted(set(value) - set(allowed))
    if extra:
        _fail(f"{name} contains unknown fields: {extra}")


def _absolute_path(value: Path | str, name: str, *, root: Path | None = None) -> Path:
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        if root is None:
            _fail(f"{name} must be absolute")
        candidate = root / candidate
    normalized = os.path.normpath(str(candidate))
    if str(candidate) != normalized:
        _fail(f"{name} uses a lexical path alias")
    path = Path(normalized)
    if any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} contains a path alias component")
    if str(path) != os.sep and str(path).endswith(os.sep):
        _fail(f"{name} has a trailing separator")
    return path


def _root_path(value: Path | str) -> Path:
    path = _absolute_path(os.path.abspath(os.fspath(value)), "root")
    if not path.is_dir():
        _fail(f"root is not a directory: {path}")
    return path


def _reject_symlink_components(
    path: Path,
    name: str,
    *,
    allow_missing_leaf: bool,
    allow_leaf_symlink: bool = False,
) -> None:
    current = Path(path.anchor or os.sep)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for index, part in enumerate(parts):
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return
            _fail(f"{name} component does not exist: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode) and not (allow_leaf_symlink and index == len(parts) - 1):
            _fail(f"{name} contains a symlink component: {current}")


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size)


def _read_bounded_json(path: Path | str, *, root: Path, name: str, limit: int) -> tuple[Mapping[str, Any], dict[str, Any]]:
    candidate = _absolute_path(path, name, root=root)
    _reject_symlink_components(candidate, name, allow_missing_leaf=False)
    try:
        before = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    if before.st_size > limit:
        _fail(f"{name} exceeds bounded size {limit}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    chunks: list[bytes] = []
    try:
        opened = os.fstat(descriptor)
        expected = _identity(before)
        if _identity(opened) != expected:
            _fail(f"{name} changed before bounded read")
        total = 0
        while total <= limit:
            block = os.read(descriptor, min(64 * 1024, limit + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        if _identity(os.fstat(descriptor)) != expected or total != before.st_size:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(descriptor)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name} after read: {error}")
    if _identity(after) != _identity(before):
        _fail(f"{name} changed after bounded read")
    raw = b"".join(chunks)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, LauncherError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    payload = _mapping(payload, name)
    _walk_json(payload, name)
    return payload, {"path": str(candidate), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "opened": True}


def _metadata_only(
    path: Path,
    name: str,
    *,
    expected_bytes: int | None = None,
    allow_leaf_symlink: bool = False,
) -> dict[str, Any]:
    """Return inode metadata without opening or hashing file content."""

    candidate = _absolute_path(path, name)
    _reject_symlink_components(
        candidate,
        name,
        allow_missing_leaf=False,
        allow_leaf_symlink=allow_leaf_symlink,
    )
    try:
        info = os.stat(candidate) if allow_leaf_symlink else os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot metadata-check {name}: {error}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    if expected_bytes is not None and info.st_size != expected_bytes:
        _fail(f"{name} byte count differs from declared identity")
    return {"path": str(candidate), "bytes": info.st_size, "mode": stat.S_IMODE(info.st_mode), "metadata_only": True}


def _validate_nonce(value: Any, name: str = "nonce") -> str:
    nonce = _string(value, name)
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail(f"{name} must be a non-zero 32-character lowercase hexadecimal value")
    return nonce


def _validate_seed(value: Any, name: str = "seed") -> int:
    seed = _strict_int(value, name)
    if seed not in SEEDS:
        _fail(f"{name} must be one of {SEEDS}")
    return seed


def _validate_run_id(value: Any, seed: int) -> str:
    run_id = _string(value, "run_id")
    match = RUN_ID_RE.fullmatch(run_id)
    if match is None or int(match.group("seed")) != seed:
        _fail("run_id must be the explicit current-manifest v3 identity for this seed")
    return run_id


def _manifest_binding(payload: Mapping[str, Any], source: Mapping[str, Any], *, path: Path) -> dict[str, Any]:
    _exact(payload, "schema", MANIFEST_SCHEMA, "manifest")
    _exact(payload, "dataset_id", MANIFEST_DATASET_ID, "manifest")
    _exact(payload, "case_count", 32, "manifest")
    _exact(payload, "formal_release", False, "manifest")
    _exact(payload, "input_asset_policy", "content_addressed_compressed_npz", "manifest")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 32:
        _fail("manifest.cases must contain exactly 32 entries")
    selected: Mapping[str, Any] | None = None
    case_ids: set[str] = set()
    for index, value in enumerate(cases):
        case = _mapping(value, f"manifest.cases[{index}]")
        case_id = _string(case.get("case_id"), f"manifest.cases[{index}].case_id")
        if case_id in case_ids:
            _fail("manifest case identifiers are not unique")
        case_ids.add(case_id)
        if case_id == CASE_ID:
            selected = case
    if selected is None:
        _fail(f"manifest does not contain fixed case {CASE_ID}")
    _exact(selected, "physical_case_id", CASE_ID, "manifest.selected_case")
    _exact(selected, "family", "F3", "manifest.selected_case")
    _exact(selected, "split", SPLIT, "manifest.selected_case")
    _exact(selected, "qualification_case", False, "manifest.selected_case")
    canonical = canonical_sha(payload)
    if canonical != CURRENT_CANONICAL_MANIFEST_SHA256:
        _fail("manifest canonical SHA differs from the fixed current canonical manifest")
    if source["sha256"] != CURRENT_MANIFEST_RAW_SHA256:
        _fail("manifest raw SHA differs from the fixed current manifest file")
    expected_path = path.parent.parent.parent / MANIFEST_RELATIVE
    if path != expected_path:
        _fail("manifest path is not the fixed campaigns/core-v1/f3-dataset-v2.json path")
    return {
        "path": str(path),
        "raw_sha256": source["sha256"],
        "bytes": source["bytes"],
        "canonical_sha256": canonical,
        "schema": payload["schema"],
        "dataset_id": payload["dataset_id"],
        "case_count": payload["case_count"],
        "case_id": CASE_ID,
        "split": SPLIT,
    }


def _expected_config(manifest_sha256: str, seed: int, run_id: str) -> dict[str, Any]:
    config = dict(STATIC_CONFIG)
    config.update({"manifest_sha256": manifest_sha256, "paired_seed": seed, "run_id": run_id, "sampler_seed": seed, "seed": seed})
    return config


def _validate_checkpoint_identity(value: Any, *, checkpoint_path: Path, seed: int, name: str) -> dict[str, Any]:
    checkpoint = _mapping(value, name)
    _unknown(checkpoint, frozenset({"schema", "path", "sha256", "bytes", "update"}), name)
    _exact(checkpoint, "schema", CHECKPOINT_SCHEMA, name)
    _exact(checkpoint, "update", UPDATES, name)
    path = _absolute_path(_string(checkpoint.get("path"), f"{name}.path"), f"{name}.path")
    if path != checkpoint_path or path.suffix.lower() != ".pt":
        _fail(f"{name}.path drifts from the explicit seed{seed} checkpoint")
    if path.name != f"{checkpoint_path.stem}.pt":
        _fail(f"{name}.path does not bind the v3 checkpoint filename")
    return {"schema": CHECKPOINT_SCHEMA, "path": str(path), "sha256": _sha(checkpoint.get("sha256"), f"{name}.sha256"), "bytes": _strict_int(checkpoint.get("bytes"), f"{name}.bytes", 1), "update": UPDATES}


def _validate_training_receipt(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    root: Path,
    seed: int,
    run_id: str,
    manifest_sha256: str,
    checkpoint_path: Path,
) -> dict[str, Any]:
    name = "training_receipt"
    _unknown(payload, frozenset({"schema", "status", "evidence_status", "model_kind", "seed", "run_id", "completed_updates", "parameter_count", "checkpoint_verified", "checkpoint", "config", "evidence", *ZERO_CREDIT}), name)
    _exact(payload, "schema", TRAINING_SCHEMA, name)
    _exact(payload, "status", "completed", name)
    _exact(payload, "evidence_status", "complete", name)
    _exact(payload, "model_kind", MODEL, name)
    _exact(payload, "seed", seed, name)
    _exact(payload, "run_id", run_id, name)
    _exact(payload, "completed_updates", UPDATES, name)
    _exact(payload, "parameter_count", PARAMETER_COUNT, name)
    _exact(payload, "checkpoint_verified", True, name)
    for key, expected in ZERO_CREDIT.items():
        if key in payload:
            _exact(payload, key, expected, name)
    config = _mapping(payload.get("config"), f"{name}.config")
    if dict(config) != _expected_config(manifest_sha256, seed, run_id):
        _fail(f"{name}.config does not exactly bind current manifest, v3 model, and seed")
    checkpoint = _validate_checkpoint_identity(payload.get("checkpoint"), checkpoint_path=checkpoint_path, seed=seed, name=f"{name}.checkpoint")
    _metadata_only(checkpoint_path, "checkpoint input", expected_bytes=checkpoint["bytes"])
    if Path(source["path"]) == checkpoint_path:
        _fail("training receipt cannot alias its checkpoint")
    evidence = _mapping(payload.get("evidence"), f"{name}.evidence")
    _exact(evidence, "schema", "core.training.evidence.v1", f"{name}.evidence")
    _exact(evidence, "status", "complete", f"{name}.evidence")
    initialization = _mapping(evidence.get("initialization"), f"{name}.evidence.initialization")
    _exact(initialization, "schema", "core.training.initialization_evidence.v1", f"{name}.evidence.initialization")
    _exact(initialization, "status", "captured", f"{name}.evidence.initialization")
    _exact(initialization, "model_kind", MODEL, f"{name}.evidence.initialization")
    _exact(initialization, "hidden", HIDDEN, f"{name}.evidence.initialization")
    _exact(initialization, "parameter_count", PARAMETER_COUNT, f"{name}.evidence.initialization")
    _exact(initialization, "seed", seed, f"{name}.evidence.initialization")
    _exact(initialization, "constructed_before_first_update", True, f"{name}.evidence.initialization")
    _sha(initialization.get("parameter_digest"), f"{name}.evidence.initialization.parameter_digest")
    normalization = _mapping(evidence.get("normalization"), f"{name}.evidence.normalization")
    _exact(normalization, "schema", "core.training.normalization_evidence.v1", f"{name}.evidence.normalization")
    _exact(normalization, "requested_maximum_transitions", 16, f"{name}.evidence.normalization")
    _exact(normalization, "selected_transition_count", 16, f"{name}.evidence.normalization")
    _exact(normalization, "selection_seed", seed, f"{name}.evidence.normalization")
    _exact(normalization, "source_split", "train", f"{name}.evidence.normalization")
    _exact(normalization, "target_reference", "raw_dual_increment_train_shared", f"{name}.evidence.normalization")
    prior = _mapping(evidence.get("residual_prior"), f"{name}.evidence.residual_prior")
    _exact(prior, "schema", "core.training.prior_evidence.v1", f"{name}.evidence.residual_prior")
    _exact(prior, "enabled", True, f"{name}.evidence.residual_prior")
    _exact(prior, "history_complete", True, f"{name}.evidence.residual_prior")
    _exact(prior, "execution_calls", UPDATES, f"{name}.evidence.residual_prior")
    _exact(prior, "rows", 17_280_000, f"{name}.evidence.residual_prior")
    _exact(prior, "finite", True, f"{name}.evidence.residual_prior")
    return {
        "path": source["path"],
        "sha256": source["sha256"],
        "bytes": source["bytes"],
        "schema": TRAINING_SCHEMA,
        "run_id": run_id,
        "seed": seed,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "manifest_sha256": manifest_sha256,
        "checkpoint": checkpoint,
    }


def _namespace(seed: int, nonce: str, value: Path, root: Path) -> Path:
    expected_name = f"f3-graph-residual500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    if value.name != expected_name or NAMESPACE_RE.fullmatch(value.name) is None:
        _fail("output namespace is not the fixed current-manifest seed/full835/nonce namespace")
    if any(token in value.name.lower() for token in ("running", "partial", "legacy", "pending")):
        _fail("output namespace contains a non-fresh state marker")
    allowed = (Path("/tmp"), root / "reports")
    if not any(value.parent == parent or parent in value.parents for parent in allowed):
        _fail("output namespace must remain under /tmp or root/reports")
    _reject_symlink_components(value.parent, "output namespace parent", allow_missing_leaf=False)
    if not value.parent.is_dir():
        _fail("output namespace parent must be an existing directory")
    if os.path.lexists(value):
        _fail("output namespace already exists; fresh namespace reuse is forbidden")
    return value


def _output_paths(namespace: Path, root: Path, seed: int, nonce: str) -> dict[str, Path]:
    prefix = str(namespace)
    return {
        "evaluation": Path(prefix + "-evaluation.json"),
        "trajectory": Path(prefix + "-trajectory.h5"),
        "progress": Path(prefix + "-evaluation-progress.json"),
        "validator": Path(prefix + "-hdf5-validation.json"),
        "artifact_identity": Path(prefix + "-artifact-identity.json"),
        "trajectory_metadata": Path(prefix + "-trajectory-metadata.json"),
        "process_proof": root / "reports" / f"F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-SEED{seed}-NONCE{nonce}-PROCESS-EXIT-PROOF-V1.json",
    }


def _check_output_collisions(outputs: Mapping[str, Path], root: Path) -> None:
    if not (root / "reports").is_dir():
        _fail("root/reports must already exist; planner will not create shared directories")
    _reject_symlink_components(root / "reports", "root/reports", allow_missing_leaf=False)
    for name, path in outputs.items():
        _absolute_path(path, f"output.{name}")
        if name == "process_proof" and path.parent != root / "reports":
            _fail("process proof escaped graph_residual reports scope")
        if os.path.lexists(path):
            _fail(f"output.{name} already exists; fresh namespace reuse is forbidden")


def _command_digest(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> str:
    return canonical_sha({"argv": list(argv), "cwd": str(cwd), "env_overrides": dict(env)})


def _build_command(*, root: Path, python: Path, manifest: Path, checkpoint: Path, outputs: Mapping[str, Path]) -> tuple[str, ...]:
    return (
        str(python),
        "-u",
        str(root / "scripts" / "core_learning.py"),
        "evaluate",
        "--manifest",
        str(manifest),
        "--data-root",
        str(root),
        "--checkpoint",
        str(checkpoint),
        "--case-id",
        CASE_ID,
        "--split",
        SPLIT,
        "--maximum-steps",
        str(TRANSITIONS),
        "--chunk-size",
        str(CHUNK_SIZE),
        "--device",
        "cuda:0",
        "--progress-every",
        str(PROGRESS_EVERY),
        "--trajectory-output",
        str(outputs["trajectory"]),
        "--progress-output",
        str(outputs["progress"]),
        "--output",
        str(outputs["evaluation"]),
        "--diagnostic",
    )


@dataclass(frozen=True)
class CurrentManifestRolloutPlan:
    root: Path
    seed: int
    run_id: str
    nonce: str
    manifest: Path
    manifest_binding: Mapping[str, Any]
    training_receipt: Path
    training_binding: Mapping[str, Any]
    checkpoint_path: Path
    checkpoint: Mapping[str, Any]
    output_namespace: Path
    outputs: Mapping[str, Path]
    command: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    command_sha256: str
    gpu_index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "status": "dry_run_ready",
            "mode": "dry_run",
            "launched": False,
            "launch_allowed": False,
            "execute_capability_required": True,
            "seed": self.seed,
            "run_id": self.run_id,
            "model": MODEL,
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "gpu_index": self.gpu_index,
            "manifest": dict(self.manifest_binding),
            "manifest_sha256": self.manifest_binding["canonical_sha256"],
            "training_receipt": dict(self.training_binding),
            "checkpoint": dict(self.checkpoint),
            "output_namespace": str(self.output_namespace),
            "namespace_nonce": self.nonce,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "env_overrides": dict(self.env),
            "command_sha256": self.command_sha256,
            "outputs": {key: str(value) for key, value in self.outputs.items()},
            **ZERO_CREDIT,
            "zero_credit_only": True,
            "side_effects": {
                "processes_started": 0,
                "processes_stopped": 0,
                "processes_restarted": 0,
                "registry_writes": 0,
                "ledger_writes": 0,
                "denominator_writes": 0,
                "gate_writes": 0,
                "completion_writes": 0,
                "plan_writes": 0,
            },
            "input_boundary": {
                "bounded_manifest_json_opened": True,
                "bounded_training_receipt_json_opened": True,
                "checkpoint_metadata_stat_only": True,
                "checkpoint_content_opened": False,
                "evaluation_content_opened": False,
                "trajectory_hdf5_opened": False,
                "progress_content_opened": False,
                "gpu_started": False,
                "runtime_started": False,
            },
        }


def build_plan(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    manifest: Path | str,
    checkpoint: Path | str,
    training_receipt: Path | str,
    run_id: str,
    nonce: str,
    output_namespace: Path | str,
    gpu_index: int = 0,
    python_executable: Path | str | None = None,
) -> CurrentManifestRolloutPlan:
    """Build one non-launching, current-manifest full835 plan."""

    root_path = _root_path(root)
    seed = _validate_seed(seed)
    run_id = _validate_run_id(run_id, seed)
    nonce = _validate_nonce(nonce)
    if type(gpu_index) is not int or not 0 <= gpu_index < GPU_COUNT:
        _fail(f"gpu_index must be an integer in [0, {GPU_COUNT})")
    manifest_path = _absolute_path(manifest, "manifest", root=root_path)
    expected_manifest = root_path / MANIFEST_RELATIVE
    if manifest_path != expected_manifest:
        _fail("manifest path is not the fixed current canonical manifest")
    manifest_payload, manifest_source = _read_bounded_json(manifest_path, root=root_path, name="manifest", limit=MAX_MANIFEST_BYTES)
    manifest_binding = _manifest_binding(manifest_payload, manifest_source, path=manifest_path)

    training_path = _absolute_path(training_receipt, "training_receipt", root=root_path)
    if training_path.name != f"{run_id}-training.json":
        _fail("training_receipt filename does not bind the explicit v3 run_id")
    checkpoint_path = _absolute_path(checkpoint, "checkpoint", root=root_path)
    if checkpoint_path.name != f"{run_id}-checkpoint.pt":
        _fail("checkpoint filename does not bind the explicit v3 run_id")
    training_payload, training_source = _read_bounded_json(training_path, root=root_path, name="training_receipt", limit=MAX_JSON_BYTES)
    training_binding = _validate_training_receipt(
        training_payload,
        training_source,
        root=root_path,
        seed=seed,
        run_id=run_id,
        manifest_sha256=manifest_binding["canonical_sha256"],
        checkpoint_path=checkpoint_path,
    )
    checkpoint = dict(training_binding["checkpoint"])
    nonce_path = _absolute_path(output_namespace, "output_namespace", root=root_path)
    namespace = _namespace(seed, nonce, nonce_path, root_path)
    outputs = _output_paths(namespace, root_path, seed, nonce)
    _check_output_collisions(outputs, root_path)

    python = _absolute_path(
        python_executable if python_executable is not None else root_path / ".venv" / "bin" / "python",
        "python_executable",
        root=root_path,
    )
    core_learning = root_path / "scripts" / "core_learning.py"
    _metadata_only(python, "Python executable", allow_leaf_symlink=True)
    _metadata_only(core_learning, "core_learning.py")
    command = _build_command(root=root_path, python=python, manifest=manifest_path, checkpoint=checkpoint_path, outputs=outputs)
    env = {"CUDA_VISIBLE_DEVICES": str(gpu_index), "PYTHONDONTWRITEBYTECODE": "1"}
    command_sha256 = _command_digest(command, cwd=root_path, env=env)
    return CurrentManifestRolloutPlan(
        root=root_path,
        seed=seed,
        run_id=run_id,
        nonce=nonce,
        manifest=manifest_path,
        manifest_binding=manifest_binding,
        training_receipt=training_path,
        training_binding=training_binding,
        checkpoint_path=checkpoint_path,
        checkpoint=checkpoint,
        output_namespace=namespace,
        outputs=outputs,
        command=command,
        cwd=root_path,
        env=env,
        command_sha256=command_sha256,
        gpu_index=gpu_index,
    )


def execute_plan(*_args: Any, **_kwargs: Any) -> None:
    """Reject execution until a separately audited capability is wired.

    Keeping this explicit function is useful to callers that know the older
    launcher API, while making accidental ``--execute``-style reuse
    impossible.  A future adapter must introduce an independently reviewed
    capability and must preserve the exact plan identity before spawning.
    """

    _fail("no audited execute capability is installed; launch_allowed remains false")


def _artifact_reference(value: Any, *, expected_path: Path, name: str, root: Path) -> dict[str, Any]:
    artifact = _mapping(value, name)
    _unknown(artifact, ARTIFACT_KEYS, name)
    path = _absolute_path(_string(artifact.get("path"), f"{name}.path"), f"{name}.path")
    if path != expected_path:
        _fail(f"{name}.path drifts from the plan namespace")
    suffix = expected_path.suffix.lower()
    if path.suffix.lower() != suffix:
        _fail(f"{name}.path suffix drifts")
    _exact(artifact, "content_opened", False, name)
    _exact(artifact, "stat_only", True, name)
    byte_count = _strict_int(artifact.get("bytes"), f"{name}.bytes", 1)
    if byte_count > MAX_DECLARED_BYTES:
        _fail(f"{name}.bytes exceeds the declared bound")
    digest = _sha(artifact.get("sha256"), f"{name}.sha256")
    _metadata_only(path, name, expected_bytes=byte_count)
    return {"path": str(path), "sha256": digest, "bytes": byte_count, "content_opened": False, "stat_only": True}


def _validate_command(value: Any, plan: CurrentManifestRolloutPlan) -> None:
    command = _mapping(value, "terminal.command")
    _unknown(command, frozenset({"argv", "cwd", "env_overrides", "sha256"}), "terminal.command")
    argv = command.get("argv")
    if not isinstance(argv, list) or tuple(argv) != plan.command:
        _fail("terminal.command.argv does not equal the planned evaluator command")
    _exact(command, "cwd", str(plan.cwd), "terminal.command")
    env = _mapping(command.get("env_overrides"), "terminal.command.env_overrides")
    if dict(env) != dict(plan.env):
        _fail("terminal.command.env_overrides drifts from the plan")
    _exact(command, "sha256", plan.command_sha256, "terminal.command")
    if canonical_sha({"argv": list(argv), "cwd": str(plan.cwd), "env_overrides": dict(env)}) != plan.command_sha256:
        _fail("terminal.command digest is not canonical")


def _validate_evaluation(value: Any, plan: CurrentManifestRolloutPlan) -> dict[str, Any]:
    evaluation = _mapping(value, "terminal.evaluation")
    _unknown(evaluation, EVALUATION_KEYS, "terminal.evaluation")
    artifact = _artifact_reference(
        {key: evaluation.get(key) for key in ARTIFACT_KEYS},
        expected_path=plan.outputs["evaluation"],
        name="terminal.evaluation",
        root=plan.root,
    )
    for key, expected in (
        ("schema", "core.evaluation.v1"),
        ("model_kind", MODEL),
        ("seed", plan.seed),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("evaluation_mode", "diagnostic"),
        ("diagnostic", True),
        ("autonomous", True),
        ("maximum_steps", TRANSITIONS),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("execution_complete", True),
        ("finite_rollout_complete", True),
        ("future_state_inputs", False),
        ("status", "completed"),
        ("namespace", str(plan.output_namespace)),
        ("namespace_fresh", True),
        ("namespace_nonce", plan.nonce),
    ):
        _exact(evaluation, key, expected, "terminal.evaluation")
    return {**artifact, "schema": "core.evaluation.v1", "status": "completed"}


def _validate_hdf5_validator(value: Any, plan: CurrentManifestRolloutPlan) -> dict[str, Any]:
    validator = _mapping(value, "terminal.hdf5_validator")
    _unknown(validator, VALIDATOR_KEYS, "terminal.hdf5_validator")
    artifact = _artifact_reference(
        {key: validator.get(key) for key in ARTIFACT_KEYS},
        expected_path=plan.outputs["validator"],
        name="terminal.hdf5_validator",
        root=plan.root,
    )
    for key, expected in (
        ("schema", VALIDATOR_SCHEMA),
        ("passed", True),
        ("complete", True),
        ("diagnostic_only", True),
        ("case_id", CASE_ID),
        ("expected_transitions", TRANSITIONS),
        ("frames_executed", FRAMES),
        ("trajectory_frames", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
        ("tail_frame_count", 0),
        ("qualification_credit", 0),
        ("production_artifacts_touched", False),
        ("actual_future_state_inputs", False),
    ):
        _exact(validator, key, expected, "terminal.hdf5_validator")
    if "credit" in validator:
        _exact(validator, "credit", 0, "terminal.hdf5_validator")
    return {**artifact, "schema": VALIDATOR_SCHEMA, "passed": True, "complete": True}


def verify_terminal_receipt(payload: Mapping[str, Any], plan: CurrentManifestRolloutPlan) -> dict[str, Any]:
    """Verify one current-manifest terminal receipt without opening artifacts."""

    _walk_json(payload, "terminal")
    _unknown(payload, TERMINAL_TOP_LEVEL_KEYS, "terminal")
    _exact(payload, "schema", TERMINAL_RECEIPT_SCHEMA, "terminal")
    _exact(payload, "report_id", f"f3-graph-residual-hidden16-current-manifest-seed{plan.seed}-full835-terminal-receipt-v1", "terminal")
    _exact(payload, "status", "terminal_verified", "terminal")
    _exact(payload, "source_bound", True, "terminal")
    for key, expected in ZERO_CREDIT.items():
        _exact(payload, key, expected, "terminal")
    for key, expected in (("seed", plan.seed), ("run_id", plan.run_id), ("namespace", str(plan.output_namespace)), ("namespace_nonce", plan.nonce), ("model_kind", MODEL), ("hidden", HIDDEN), ("updates", UPDATES), ("case_id", CASE_ID), ("split", SPLIT), ("transitions", TRANSITIONS), ("frames", FRAMES), ("manifest_sha256", plan.manifest_binding["canonical_sha256"])):
        _exact(payload, key, expected, "terminal")
    training = _mapping(payload.get("training_receipt"), "terminal.training_receipt")
    _unknown(training, frozenset({"path", "sha256", "bytes"}), "terminal.training_receipt")
    for key, expected in (("path", str(plan.training_receipt)), ("sha256", plan.training_binding["sha256"]), ("bytes", plan.training_binding["bytes"])):
        _exact(training, key, expected, "terminal.training_receipt")
    checkpoint = _mapping(payload.get("checkpoint"), "terminal.checkpoint")
    _unknown(checkpoint, frozenset({"schema", "path", "sha256", "bytes", "update"}), "terminal.checkpoint")
    for key, expected in plan.checkpoint.items():
        _exact(checkpoint, key, expected, "terminal.checkpoint")
    _validate_command(payload.get("command"), plan)
    process = _mapping(payload.get("process_exit_proof"), "terminal.process_exit_proof")
    _unknown(process, frozenset({"schema", "status", "source_bound", "seed", "run_id", "namespace", "namespace_nonce", "command_sha256", "launcher_command_sha256", "evaluator_alive", "launcher_alive", "evaluator_returncode", "launcher_returncode", "returncode", "natural_exit", "observed_after_exit"}), "terminal.process_exit_proof")
    for key, expected in (("schema", PROCESS_SCHEMA), ("status", "exited_successfully"), ("source_bound", True), ("seed", plan.seed), ("run_id", plan.run_id), ("namespace", str(plan.output_namespace)), ("namespace_nonce", plan.nonce), ("command_sha256", plan.command_sha256), ("launcher_command_sha256", plan.command_sha256), ("evaluator_alive", False), ("launcher_alive", False), ("evaluator_returncode", 0), ("launcher_returncode", 0), ("returncode", 0), ("natural_exit", True), ("observed_after_exit", True)):
        _exact(process, key, expected, "terminal.process_exit_proof")
    markers = _mapping(payload.get("terminal_markers"), "terminal.terminal_markers")
    _unknown(markers, frozenset({"terminal", "terminal_status", "execution_complete", "finite_rollout_complete", "requested_window_complete", "transitions_executed", "frames_executed", "future_state_inputs"}), "terminal.terminal_markers")
    for key, expected in (("terminal", True), ("terminal_status", "completed"), ("execution_complete", True), ("finite_rollout_complete", True), ("requested_window_complete", True), ("transitions_executed", TRANSITIONS), ("frames_executed", FRAMES), ("future_state_inputs", False)):
        _exact(markers, key, expected, "terminal.terminal_markers")
    evaluation = _validate_evaluation(payload.get("evaluation"), plan)
    artifacts = {
        "evaluation": evaluation,
        "trajectory": _artifact_reference(
            payload.get("trajectory"),
            expected_path=plan.outputs["trajectory"],
            name="terminal.trajectory",
            root=plan.root,
        ),
        "progress": _artifact_reference(
            payload.get("progress"),
            expected_path=plan.outputs["progress"],
            name="terminal.progress",
            root=plan.root,
        ),
        "hdf5_validator": _validate_hdf5_validator(payload.get("hdf5_validator"), plan),
    }
    effects = _mapping(payload.get("side_effects"), "terminal.side_effects")
    _unknown(effects, frozenset({"processes_started", "processes_stopped", "processes_restarted", "registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"}), "terminal.side_effects")
    _exact(effects, "processes_stopped", 0, "terminal.side_effects")
    _exact(effects, "processes_restarted", 0, "terminal.side_effects")
    for key in ("registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"):
        _exact(effects, key, 0, "terminal.side_effects")
    boundary = _mapping(payload.get("input_boundary"), "terminal.input_boundary")
    _unknown(boundary, frozenset({"bounded_receipt_json_opened", "checkpoint_content_opened", "evaluation_content_opened", "trajectory_hdf5_opened", "progress_content_opened", "runtime_started", "runtime_stopped", "runtime_restarted"}), "terminal.input_boundary")
    _exact(boundary, "bounded_receipt_json_opened", True, "terminal.input_boundary")
    for key in ("checkpoint_content_opened", "evaluation_content_opened", "trajectory_hdf5_opened", "progress_content_opened", "runtime_started", "runtime_stopped", "runtime_restarted"):
        _exact(boundary, key, False, "terminal.input_boundary")
    return {"status": "terminal_verified", "source_bound": True, "seed": plan.seed, "command_sha256": plan.command_sha256, "artifacts": artifacts, **ZERO_CREDIT}


def verify_terminal_receipt_file(path: Path | str, plan: CurrentManifestRolloutPlan) -> dict[str, Any]:
    payload, source = _read_bounded_json(path, root=plan.root, name="terminal_receipt", limit=MAX_JSON_BYTES)
    result = verify_terminal_receipt(payload, plan)
    result["receipt_source"] = source
    return result


def build_blocked_report(*, observed_at_utc: str | None = None) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc or datetime.now(timezone.utc).isoformat(),
        "status": "blocked_fail_closed",
        "fail_closed": True,
        "source_bound": False,
        "launch_allowed": False,
        "terminal_receipt_verified": False,
        **ZERO_CREDIT,
        "expected_contract": {
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "seeds": list(SEEDS),
            "manifest_path": str(MANIFEST_RELATIVE),
            "manifest_canonical_sha256": CURRENT_CANONICAL_MANIFEST_SHA256,
            "run_id_suffix": "-v3",
            "namespace_nonce_hex_length": 32,
            "bounded_json_only": True,
            "checkpoint_metadata_only": True,
            "zero_credit_only": True,
        },
        "blocked_reasons": [
            "no terminal receipt was supplied",
            "launch_allowed is permanently false for this dry-run contract",
            "an independently audited execute capability is required before any future process launch",
        ],
        "side_effects": {
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        "input_boundary": {
            "bounded_json_only": True,
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_content_opened": False,
            "runtime_started": False,
            "runtime_stopped": False,
            "runtime_restarted": False,
        },
        "interpretation": "This is a non-authorizing dry-run/identity contract. It does not create terminal evidence, launch GPU work, or grant formal/T1/T2/credit status.",
    }


def validate_report(report: Mapping[str, Any]) -> None:
    _unknown(report, frozenset({"schema", "report_id", "observed_at_utc", "status", "fail_closed", "source_bound", "launch_allowed", "terminal_receipt_verified", *ZERO_CREDIT, "expected_contract", "blocked_reasons", "side_effects", "input_boundary", "interpretation"}), "report")
    _exact(report, "schema", REPORT_SCHEMA, "report")
    _exact(report, "report_id", REPORT_ID, "report")
    _exact(report, "status", "blocked_fail_closed", "report")
    _exact(report, "fail_closed", True, "report")
    _exact(report, "source_bound", False, "report")
    _exact(report, "launch_allowed", False, "report")
    _exact(report, "terminal_receipt_verified", False, "report")
    for key, expected in ZERO_CREDIT.items():
        _exact(report, key, expected, "report")
    expected = _mapping(report.get("expected_contract"), "report.expected_contract")
    _exact(expected, "model", MODEL, "report.expected_contract")
    _exact(expected, "hidden", HIDDEN, "report.expected_contract")
    _exact(expected, "updates", UPDATES, "report.expected_contract")
    _exact(expected, "case_id", CASE_ID, "report.expected_contract")
    _exact(expected, "transitions", TRANSITIONS, "report.expected_contract")
    _exact(expected, "frames", FRAMES, "report.expected_contract")
    _exact(expected, "seeds", list(SEEDS), "report.expected_contract")
    reasons = report.get("blocked_reasons")
    if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
        _fail("report.blocked_reasons must be a non-empty string list")
    _walk_json(report, "report")


def _write_report(report: Mapping[str, Any], path: Path | str, root: Path) -> Path:
    target = _absolute_path(path, "output", root=root)
    if target.parent != root / "reports":
        _fail("report output must be directly under root/reports")
    if target.exists():
        _fail("report output refuses overwrite")
    target.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return target


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--training-receipt", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--nonce")
    parser.add_argument("--output-namespace", "--namespace", dest="output_namespace", type=Path)
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--python-executable", type=Path)
    parser.add_argument("--verify-terminal-receipt", type=Path)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--output-report", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            root_path = _root_path(args.root)
            report, source = _read_bounded_json(
                args.verify_report,
                root=root_path,
                name="report",
                limit=MAX_JSON_BYTES,
            )
            validate_report(report)
            print(json.dumps({"status": "verified", "report": source["path"], "credit": 0}, ensure_ascii=False, sort_keys=True))
            return 0
        supplied = [args.seed, args.manifest, args.checkpoint, args.training_receipt, args.run_id, args.nonce, args.output_namespace]
        if not any(value is not None for value in supplied):
            report = build_blocked_report()
            validate_report(report)
            if args.output_report is not None:
                _write_report(report, args.output_report, _root_path(args.root))
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
            return 2
        if any(value is None for value in supplied):
            _fail("plan identity arguments must be supplied as one complete set")
        plan = build_plan(
            args.root,
            seed=args.seed,
            manifest=args.manifest,
            checkpoint=args.checkpoint,
            training_receipt=args.training_receipt,
            run_id=args.run_id,
            nonce=args.nonce,
            output_namespace=args.output_namespace,
            gpu_index=args.gpu_index,
            python_executable=args.python_executable,
        )
        if args.verify_terminal_receipt is not None:
            result = verify_terminal_receipt_file(args.verify_terminal_receipt, plan)
        else:
            result = plan.as_dict()
        if args.output_report is not None:
            report = build_blocked_report()
            if result.get("status") == "terminal_verified":
                report = {**report, "status": "terminal_diagnostic_verified", "fail_closed": False, "source_bound": True, "terminal_receipt_verified": True, "blocked_reasons": []}
            _write_report(report, args.output_report, plan.root)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0 if result.get("status") in {"dry_run_ready", "terminal_verified"} else 2
    except (LauncherError, OSError, RecursionError, ValueError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "blocked_fail_closed", "launch_allowed": False, "diagnostic_only": True, "credit": 0, "error": str(error)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
