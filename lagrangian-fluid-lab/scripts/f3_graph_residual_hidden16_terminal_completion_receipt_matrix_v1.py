#!/usr/bin/env python3
"""Bind the F3 graph_residual/hidden16 full835 terminal receipt matrix.

This module is deliberately a receipt adapter, not a rollout validator.  It
reads only the bounded JSON terminal-completion receipts supplied by the
caller.  It never opens a checkpoint, an evaluation/progress/trajectory
artifact, an HDF5 file, a manifest, or a solver output.  In particular, a
PID, a progress file, or a partial receipt can never be promoted to terminal
completion.

The accepted per-seed receipt is the canonical
``core.f3.graph_residual.hidden16.seed{seed}.full835.terminal_completion_receipt.v1``
shape documented by ``_validate_receipt`` below.  This intentionally does not
accept the graph_raw matrix schema, hidden=8 historical summaries, or legacy
shape aliases.  A successful matrix is diagnostic-only and zero-credit; it
does not mutate or authorize any campaign state.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]

REPORT_SCHEMA = (
    "core.f3.graph_residual.hidden16."
    "terminal_completion_receipt_matrix.v1"
)
REPORT_ID = "f3-graph-residual-hidden16-terminal-completion-receipt-matrix-v1"
RECEIPT_SCHEMA_RE = re.compile(
    r"^core\.f3\.graph_residual\.hidden16\.seed(?P<seed>17|29|43)\."
    r"full835\.terminal_completion_receipt\.v1$"
)
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
EVALUATION_SCHEMA = "core.evaluation.v1"

SEEDS = (17, 29, 43)
MODEL_KIND = "graph_residual"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"

MAX_JSON_BYTES = 256 * 1024
MAX_JSON_DEPTH = 64
MAX_DECLARED_BYTES = 1 << 50
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NAMESPACE_RE = re.compile(
    r"^(?P<directory>/.*?/)?"
    r"f3-graph-residual500-hidden16-seed(?P<seed>17|29|43)-full835-"
    r"nonce(?P<nonce>[0-9a-f]{32})$"
)
FORBIDDEN_ARTIFACT_WORDS = (
    "evaluation",
    "progress",
    "trajectory",
    "hdf5",
    "manifest",
    "solver",
    "running",
    "partial",
    "pending",
    "legacy",
)
CHECKPOINT_SUFFIXES = frozenset({".pt", ".pth", ".ckpt"})
REPORT_JSON_SUFFIX = ".json"
REPORT_MARKDOWN_SUFFIX = ".zh-CN.md"
REPORT_JSON_FILENAME = (
    "F3-GRAPH-RESIDUAL-HIDDEN16-TERMINAL-COMPLETION-"
    "RECEIPT-MATRIX-V1-2026-09-28.json"
)
REPORT_MARKDOWN_FILENAME = REPORT_JSON_FILENAME.removesuffix(REPORT_JSON_SUFFIX) + REPORT_MARKDOWN_SUFFIX
REPORT_OUTPUT_FILENAMES = frozenset({REPORT_JSON_FILENAME, REPORT_MARKDOWN_FILENAME})

RECEIPT_TOP_LEVEL_KEYS = frozenset(
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
        "model_kind",
        "hidden",
        "updates",
        "case_id",
        "split",
        "transitions",
        "frames",
        "terminal_markers",
        "checkpoint",
        "training_receipt",
        "evaluation",
        "trajectory",
        "progress",
        "hdf5_validator",
        "side_effects",
        "input_boundary",
    }
)
REPORT_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "status",
        "fail_closed",
        "diagnostic_only",
        "formal",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "qualification_credit",
        "credit",
        "expected_contract",
        "seed_matrix",
        "checks",
        "blocked_reasons",
        "terminal_sources",
        "side_effects",
        "input_boundary",
        "interpretation",
        "observed_at_utc",
        "source_bound",
    }
)

DEFAULT_OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
DEFAULT_TERMINAL_PATHS: dict[int, Path] = {
    seed: LAB_ROOT
    / f"reports/F3-GRAPH-RESIDUAL-HIDDEN16-SEED{seed}-"
    "TERMINAL-COMPLETION-RECEIPT-V1-2026-09-28.json"
    for seed in SEEDS
}


class MatrixError(ValueError):
    """Malformed, incomplete, unsafe, or conflicting matrix evidence."""


def _fail(message: str) -> None:
    raise MatrixError(f"fail-closed: {message}")


def _reject_json_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _strict_sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA256_RE.fullmatch(text) is None:
        _fail(f"{name} must be a lowercase SHA-256 hexadecimal digest")
    return text


def _check_exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if isinstance(expected, bool) and type(observed) is not bool:
        _fail(f"{name}.{key} must be a boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be an integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _reject_nonzero_credit_or_formal_claim(value: Any, name: str = "receipt") -> None:
    """Reject promotion markers anywhere in a supplied receipt."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = key.lower()
            if "credit" in lowered:
                if type(item) is not int or item != 0:
                    _fail(f"{name}.{key} must be integer zero")
            if lowered in {
                "formal",
                "formal_eligible",
                "formal_training",
                "t1_numerical",
                "t2_macro",
                "t2_path",
                "qualification",
            }:
                if isinstance(item, Mapping):
                    _reject_nonzero_credit_or_formal_claim(item, f"{name}.{key}")
                elif type(item) is not bool or item is not False:
                    _fail(f"{name}.{key} must be false")
            if lowered == "diagnostic_only":
                if type(item) is not bool or item is not True:
                    _fail(f"{name}.{key} must be true")
            _reject_nonzero_credit_or_formal_claim(item, f"{name}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_nonzero_credit_or_formal_claim(item, f"{name}[{index}]")


def _lexical_path(root: Path, value: Path | str, name: str) -> Path:
    if not isinstance(value, (Path, str)):
        _fail(f"{name} must be a path string")
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path without NUL")
    raw_path = Path(raw)
    if ".." in raw_path.parts:
        _fail(f"{name} contains parent traversal")
    root_abs = Path(os.path.abspath(os.fspath(root)))
    candidate = Path(os.path.abspath(raw if raw_path.is_absolute() else root_abs / raw))
    try:
        candidate.relative_to(root_abs)
    except ValueError:
        _fail(f"{name} escapes the bounded root")
    if candidate == root_abs:
        _fail(f"{name} must identify a file below the bounded root")
    return candidate


def _relative_components(root: Path, value: Path | str, name: str) -> tuple[Path, tuple[str, ...]]:
    candidate = _lexical_path(root, value, name)
    root_abs = Path(os.path.abspath(os.fspath(root)))
    relative = candidate.relative_to(root_abs)
    components = relative.parts
    if not components or any(component in {"", ".", ".."} for component in components):
        _fail(f"{name} has unsafe path components")
    return candidate, components


def _report_output_components(
    root: Path,
    value: Path | str,
    name: str,
) -> tuple[Path, tuple[str, ...]]:
    """Allow only the two checked-in report destinations below ``reports``."""

    candidate, components = _relative_components(root, value, name)
    if len(components) != 2 or components[0] != "reports":
        _fail(f"{name} must be a direct file below lab_root/reports")
    if candidate.name not in REPORT_OUTPUT_FILENAMES:
        _fail(f"{name} must use one of the fixed report filenames {sorted(REPORT_OUTPUT_FILENAMES)!r}")
    return candidate, components


def _open_directory_chain(root: Path, components: Sequence[str], name: str) -> tuple[int, list[int]]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(os.fspath(root), flags)
    except OSError as error:
        _fail(f"{name} root directory cannot be opened without following links: {error}")
    opened = [root_fd]
    current = root_fd
    try:
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            _fail(f"{name} root is not a directory")
        for component in components:
            next_fd = os.open(component, flags, dir_fd=current)
            opened.append(next_fd)
            current = next_fd
        return current, opened
    except (OSError, MatrixError) as error:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(error, MatrixError):
            raise
        _fail(f"{name} contains a symlink or unsafe directory component: {error}")


def _read_bounded_json(root: Path, value: Path | str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one receipt through descriptor-relative O_NOFOLLOW traversal."""

    candidate, components = _relative_components(root, value, name)
    if candidate.suffix.lower() != ".json":
        _fail(f"{name} must use a JSON suffix")
    lowered_name = candidate.name.lower()
    # Receipt inputs must not be an evaluation/progress/trajectory/HDF5 file.
    # This is an additional guard against accidentally consuming a live output.
    if any(token in lowered_name for token in FORBIDDEN_ARTIFACT_WORDS):
        _fail(f"{name} names a forbidden live/artifact file")

    parent_fd = -1
    file_fd = -1
    opened: list[int] = []
    try:
        parent_fd, opened = _open_directory_chain(root, components[:-1], name)
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(components[-1], file_flags, dir_fd=parent_fd)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.EMLINK}:
                _fail(f"{name} is a symlink and cannot be consumed")
            _fail(f"{name} cannot be opened safely: {error}")
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{name} must be a regular file with one link")
        if before.st_size > MAX_JSON_BYTES:
            _fail(f"{name} exceeds bounded limit {MAX_JSON_BYTES} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(64 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                _fail(f"{name} exceeds bounded limit {MAX_JSON_BYTES} bytes")
        after = os.fstat(file_fd)
        identity_fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in identity_fields):
            _fail(f"{name} changed while it was being read (TOCTOU)")
        raw = b"".join(chunks)
        if len(raw) != after.st_size:
            _fail(f"{name} size changed while it was being read")
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except MatrixError:
            raise
        except (UnicodeError, json.JSONDecodeError) as error:
            _fail(f"{name} is not strict UTF-8 JSON: {error}")
        _walk_json(payload, name)
        payload = dict(_mapping(payload, name))
        return payload, {
            "path": candidate.relative_to(Path(os.path.abspath(os.fspath(root)))).as_posix(),
            "exists": True,
            "opened": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "schema": payload.get("schema"),
        }
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _source_metadata(root: Path, value: Path | str | None) -> dict[str, Any]:
    if value is None:
        return {"path": None, "exists": False, "opened": False, "bytes": None, "sha256": None, "schema": None}
    candidate = _lexical_path(root, value, "terminal receipt path")
    try:
        info = os.lstat(candidate)
        exists = True
    except FileNotFoundError:
        exists = False
        info = None
    except OSError:
        exists = True
        info = None
    return {
        "path": candidate.relative_to(Path(os.path.abspath(os.fspath(root)))).as_posix(),
        "exists": exists,
        "opened": False,
        "bytes": int(info.st_size) if info is not None and stat.S_ISREG(info.st_mode) else None,
        "sha256": None,
        "schema": None,
    }


def _declared_path(value: Any, name: str, suffix: str | None = None) -> str:
    path = _string(value, name)
    path_obj = Path(path)
    if not path_obj.is_absolute() or ".." in path_obj.parts:
        _fail(f"{name} must be absolute and contain no parent traversal")
    if suffix is not None and path_obj.suffix.lower() != suffix.lower():
        _fail(f"{name} must end with {suffix}")
    return path


def _declared_artifact(value: Any, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    artifact = _mapping(value, name)
    path = _declared_path(artifact.get("path"), f"{name}.path", suffix)
    byte_count = _strict_int(artifact.get("bytes"), f"{name}.bytes", 1)
    if byte_count > MAX_DECLARED_BYTES:
        _fail(f"{name}.bytes exceeds the declared bound")
    sha = _strict_sha(artifact.get("sha256"), f"{name}.sha256")
    return {"path": path, "bytes": byte_count, "sha256": sha}


def _declared_checkpoint(value: Any, seed: int, name: str) -> dict[str, Any]:
    checkpoint = _mapping(value, name)
    result = _declared_artifact(checkpoint, name)
    if Path(result["path"]).suffix.lower() not in CHECKPOINT_SUFFIXES:
        _fail(f"{name}.path must use a checkpoint suffix")
    for key, expected in (
        ("schema", CHECKPOINT_SCHEMA),
        ("model_kind", MODEL_KIND),
        ("seed", seed),
        ("hidden", HIDDEN),
        ("update", UPDATES),
        ("content_opened", False),
        ("stat_only", True),
    ):
        _check_exact(checkpoint, key, expected, name)
    if f"seed{seed}" not in Path(result["path"]).name:
        _fail(f"{name}.path is not bound to seed{seed}")
    if "hidden16" not in Path(result["path"]).name or "500" not in Path(result["path"]).name:
        _fail(f"{name}.path does not identify the hidden16 update-500 checkpoint")
    return {**result, "schema": CHECKPOINT_SCHEMA, "model_kind": MODEL_KIND, "seed": seed, "hidden": HIDDEN, "update": UPDATES}


def _declared_training(value: Any, seed: int, checkpoint: Mapping[str, Any], name: str) -> dict[str, Any]:
    training = _mapping(value, name)
    result = _declared_artifact(training, name, suffix=".json")
    for key, expected in (
        ("schema", TRAINING_SCHEMA),
        ("model_kind", MODEL_KIND),
        ("seed", seed),
        ("hidden", HIDDEN),
        ("completed_updates", UPDATES),
        ("checkpoint_verified", True),
        ("status", "completed"),
    ):
        _check_exact(training, key, expected, name)
    if f"seed{seed}" not in Path(result["path"]).name or "500" not in Path(result["path"]).name:
        _fail(f"{name}.path is not bound to seed{seed} update-500 training")
    for key, expected in (("checkpoint_sha256", checkpoint["sha256"]), ("checkpoint_update", UPDATES)):
        _check_exact(training, key, expected, name)
    nested = training.get("checkpoint")
    if nested is not None:
        nested_map = _mapping(nested, f"{name}.checkpoint")
        _check_exact(nested_map, "path", checkpoint["path"], f"{name}.checkpoint")
        _check_exact(nested_map, "sha256", checkpoint["sha256"], f"{name}.checkpoint")
        _check_exact(nested_map, "update", UPDATES, f"{name}.checkpoint")
    return {**result, "schema": TRAINING_SCHEMA, "model_kind": MODEL_KIND, "seed": seed, "hidden": HIDDEN, "completed_updates": UPDATES, "checkpoint_sha256": checkpoint["sha256"]}


def _namespace_from_evaluation(value: Any, seed: int, name: str) -> tuple[dict[str, Any], str, str]:
    evaluation = _mapping(value, name)
    result = _declared_artifact(evaluation, name, suffix=".json")
    path = result["path"]
    if not path.endswith("-evaluation.json"):
        _fail(f"{name}.path must end with -evaluation.json")
    prefix = path[: -len("-evaluation.json")]
    match = NAMESPACE_RE.fullmatch(prefix)
    if match is None or int(match.group("seed")) != seed:
        _fail(f"{name}.path is not a fresh seed{seed} full835 namespace")
    nonce = match.group("nonce")
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        _fail(f"{name}.path does not contain a fixed-format namespace nonce")
    _check_exact(evaluation, "namespace", prefix, name)
    _check_exact(evaluation, "namespace_fresh", True, name)
    _check_exact(evaluation, "namespace_nonce", nonce, name)
    for key, expected in (
        ("schema", EVALUATION_SCHEMA),
        ("model_kind", MODEL_KIND),
        ("seed", seed),
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
    ):
        _check_exact(evaluation, key, expected, name)
    return {
        **result,
        "schema": EVALUATION_SCHEMA,
        "model_kind": MODEL_KIND,
        "seed": seed,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "evaluation_mode": "diagnostic",
        "diagnostic": True,
        "autonomous": True,
        "maximum_steps": TRANSITIONS,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "execution_complete": True,
        "finite_rollout_complete": True,
        "future_state_inputs": False,
        "namespace": prefix,
        "namespace_fresh": True,
        "namespace_nonce": nonce,
    }, prefix, nonce


def _namespace_artifact(value: Any, expected_path: str, name: str, suffix: str) -> dict[str, Any]:
    artifact = _declared_artifact(value, name, suffix=suffix)
    if artifact["path"] != expected_path:
        _fail(f"{name}.path is not derived from the evaluation namespace")
    for key, expected in (("content_opened", False), ("stat_only", True)):
        _check_exact(_mapping(value, name), key, expected, name)
    return {**artifact, "content_opened": False, "stat_only": True}


def _validate_validator(value: Any, seed: int, name: str) -> dict[str, Any]:
    validator = _mapping(value, name)
    result = _declared_artifact(validator, name, suffix=".json")
    if f"seed{seed}" not in Path(result["path"]).name:
        _fail(f"{name}.path is not bound to seed{seed}")
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
        _check_exact(validator, key, expected, name)
    return {
        **result,
        "schema": VALIDATOR_SCHEMA,
        "passed": True,
        "complete": True,
        "case_id": CASE_ID,
        "expected_transitions": TRANSITIONS,
        "frames_executed": FRAMES,
        "trajectory_frames": FRAMES,
        "trajectory_transitions": TRANSITIONS,
        "tail_frame_count": 0,
        "qualification_credit": 0,
    }


def _validate_effects(value: Any, name: str) -> dict[str, Any]:
    effects = _mapping(value, name)
    false_keys = (
        "manifest_opened",
        "case_hdf5_opened",
        "checkpoint_opened",
        "trajectory_hdf5_opened",
        "progress_opened",
        "runtime_started",
        "solver_started",
        "worker_started",
        "gpu_started",
        "queue_started",
        "matrix_hdf5_opened",
    )
    zero_keys = (
        "registry_mutation",
        "ledger_mutation",
        "denominator_mutation",
        "gate_mutation",
        "completion_mutation",
        "queue_submissions",
    )
    for key in false_keys:
        if key not in effects:
            _fail(f"{name}.{key} is missing")
        _strict_bool(effects[key], f"{name}.{key}")
        if effects[key] is not False:
            _fail(f"{name}.{key} must be false")
    for key in zero_keys:
        if key not in effects:
            _fail(f"{name}.{key} is missing")
        _strict_int(effects[key], f"{name}.{key}")
        if effects[key] != 0:
            _fail(f"{name}.{key} must be zero")
    if "rollout_inputs_read_only" in effects:
        _check_exact(effects, "rollout_inputs_read_only", True, name)
    return {key: effects[key] for key in (*false_keys, *zero_keys) if key in effects} | {
        key: effects[key] for key in ("rollout_inputs_read_only",) if key in effects
    }


def _validate_input_boundary(value: Any, name: str) -> dict[str, Any]:
    boundary = _mapping(value, name)
    for key in (
        "checkpoint_content_opened",
        "trajectory_hdf5_content_opened",
        "progress_content_opened",
        "hdf5_content_opened",
        "manifest_content_opened",
        "runtime_started",
        "solver_started",
        "worker_started",
        "gpu_started",
    ):
        if key not in boundary:
            _fail(f"{name}.{key} is missing")
        _strict_bool(boundary[key], f"{name}.{key}")
        if boundary[key] is not False:
            _fail(f"{name}.{key} must be false")
    if "queue_submissions" not in boundary:
        _fail(f"{name}.queue_submissions is missing")
    _check_exact(boundary, "queue_submissions", 0, name)
    if "bounded_json_only" in boundary:
        _check_exact(boundary, "bounded_json_only", True, name)
    return dict(boundary)


def _validate_receipt(value: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    """Validate and normalize one canonical terminal receipt."""

    receipt = _mapping(value, name)
    unknown = sorted(set(receipt) - set(RECEIPT_TOP_LEVEL_KEYS))
    if unknown:
        _fail(f"{name} contains unknown or alias top-level field(s): {unknown}")
    expected_schema = (
        f"core.f3.graph_residual.hidden16.seed{seed}."
        "full835.terminal_completion_receipt.v1"
    )
    _check_exact(value, "schema", expected_schema, name)
    schema_match = RECEIPT_SCHEMA_RE.fullmatch(str(value["schema"]))
    if schema_match is None or int(schema_match.group("seed")) != seed:
        _fail(f"{name}.schema is not the exact seed{seed} canonical schema")
    for key, expected in (
        ("status", "completed_diagnostic"),
        ("source_bound", True),
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("T1_numerical", False),
        ("T2_macro", False),
        ("T2_path", False),
        ("qualification", False),
        ("qualification_credit", 0),
        ("credit", 0),
        ("seed", seed),
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
    ):
        _check_exact(value, key, expected, name)
    _reject_nonzero_credit_or_formal_claim(value, name)

    terminal = _mapping(value.get("terminal_markers"), f"{name}.terminal_markers")
    for key, expected in (
        ("terminal", True),
        ("execution_complete", True),
        ("finite_rollout_complete", True),
        ("terminal_status", "completed"),
        ("future_state_inputs", False),
    ):
        _check_exact(terminal, key, expected, f"{name}.terminal_markers")

    checkpoint = _declared_checkpoint(value.get("checkpoint"), seed, f"{name}.checkpoint")
    training = _declared_training(
        value.get("training_receipt"), seed, checkpoint, f"{name}.training_receipt"
    )
    evaluation, prefix, namespace_nonce = _namespace_from_evaluation(
        value.get("evaluation"), seed, f"{name}.evaluation"
    )
    trajectory = _namespace_artifact(
        value.get("trajectory"), prefix + "-trajectory.h5", f"{name}.trajectory", ".h5"
    )
    progress = _namespace_artifact(
        value.get("progress"), prefix + "-evaluation-progress.json", f"{name}.progress", ".json"
    )
    _check_exact(_mapping(value["progress"], f"{name}.progress"), "completion_not_inferred", True, f"{name}.progress")
    effects = _validate_effects(value.get("side_effects"), f"{name}.side_effects")
    boundary = _validate_input_boundary(value.get("input_boundary"), f"{name}.input_boundary")

    validator_value = value.get("hdf5_validator")
    validator = None if validator_value is None else _validate_validator(
        validator_value, seed, f"{name}.hdf5_validator"
    )

    return {
        "schema": expected_schema,
        "report_id": _string(value.get("report_id"), f"{name}.report_id"),
        "seed": seed,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "status": "completed_diagnostic",
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "future_state_inputs": False,
        },
        "checkpoint": checkpoint,
        "training_receipt": training,
        "evaluation": evaluation,
        "trajectory": trajectory,
        "progress": {**progress, "completion_not_inferred": True},
        "hdf5_validator": validator,
        "validator_bound": validator is not None,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "side_effects": effects,
        "input_boundary": boundary,
        "output_namespace": prefix,
        "namespace_nonce": namespace_nonce,
    }


def _check(name: str, passed: bool, reason: str, *, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason, "observed": observed, "expected": expected}


def _empty_side_effects() -> dict[str, Any]:
    return {
        "manifest_opened": False,
        "case_hdf5_opened": False,
        "checkpoint_opened": False,
        "trajectory_hdf5_opened": False,
        "progress_opened": False,
        "runtime_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "matrix_hdf5_opened": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
        "queue_submissions": 0,
        "rollout_inputs_read_only": True,
    }


def _empty_input_boundary() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "max_json_bytes": MAX_JSON_BYTES,
        "checkpoint_content_opened": False,
        "trajectory_hdf5_content_opened": False,
        "progress_content_opened": False,
        "hdf5_content_opened": False,
        "manifest_content_opened": False,
        "runtime_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_submissions": 0,
    }


def _append_error(errors: list[str], message: str) -> None:
    if message not in errors:
        errors.append(message)


def evaluate_payloads(
    receipts: Mapping[int, Mapping[str, Any]],
    sources: Mapping[int, Mapping[str, Any]] | None = None,
    *,
    source_errors: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a matrix from in-memory bounded receipt JSON objects."""

    sources = dict(sources or {})
    errors = list(source_errors)
    rows: list[dict[str, Any]] = []
    valid: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        row: dict[str, Any] = {
            "seed": seed,
            "status": "missing",
            "source": sources.get(seed),
            "projection": None,
            "blocked_reasons": [],
        }
        payload = receipts.get(seed)
        if payload is None:
            reason = f"missing future terminal completion receipt for seed {seed}"
            row["blocked_reasons"].append(reason)
            _append_error(errors, reason)
        else:
            try:
                projection = _validate_receipt(payload, seed, f"seed{seed}")
            except (MatrixError, KeyError, TypeError, RecursionError) as error:
                reason = str(error)
                row["status"] = "rejected"
                row["blocked_reasons"].append(reason)
                _append_error(errors, reason)
            else:
                valid[seed] = projection
                row["status"] = "bound_terminal"
                row["projection"] = projection
        rows.append(row)

    exact_seeds = set(valid) == set(SEEDS)
    if not exact_seeds:
        _append_error(errors, f"terminal seed set incomplete: observed {sorted(valid)} expected {list(SEEDS)}")

    signature = {
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }
    observed_signatures = {
        str(seed): {key: projection.get(key) for key in signature}
        for seed, projection in valid.items()
    }
    shared_config = exact_seeds and all(
        {key: projection.get(key) for key in signature} == signature
        for projection in valid.values()
    )
    if not shared_config:
        _append_error(errors, "seed receipts do not share the exact graph_residual hidden16 configuration")

    checkpoint_paths: set[str] = set()
    checkpoint_shas: set[str] = set()
    training_paths: set[str] = set()
    training_shas: set[str] = set()
    identity_ok = bool(valid)
    for seed, projection in valid.items():
        checkpoint = projection["checkpoint"]
        training = projection["training_receipt"]
        if checkpoint["path"] in checkpoint_paths or checkpoint["sha256"] in checkpoint_shas:
            identity_ok = False
            _append_error(errors, f"seed{seed} reuses another seed's checkpoint path or SHA identity")
        if training["path"] in training_paths or training["sha256"] in training_shas:
            identity_ok = False
            _append_error(errors, f"seed{seed} reuses another seed's training path or SHA identity")
        checkpoint_paths.add(checkpoint["path"])
        checkpoint_shas.add(checkpoint["sha256"])
        training_paths.add(training["path"])
        training_shas.add(training["sha256"])
        if training["checkpoint_sha256"] != checkpoint["sha256"]:
            identity_ok = False
            _append_error(errors, f"seed{seed} training/checkpoint SHA identity is inconsistent")
    if not exact_seeds:
        identity_ok = False
    if not identity_ok:
        _append_error(errors, "training receipt/checkpoint identities are incomplete or reused")

    namespaces = [projection["output_namespace"] for projection in valid.values()]
    nonces = [projection["namespace_nonce"] for projection in valid.values()]
    namespace_ok = (
        exact_seeds
        and len(namespaces) == len(set(namespaces))
        and len(nonces) == len(set(nonces))
        and all(projection["evaluation"]["namespace_fresh"] is True for projection in valid.values())
    )
    if not namespace_ok:
        _append_error(errors, "full835 diagnostic output namespaces are missing or reused")

    terminal_ok = exact_seeds and all(
        projection["terminal_markers"]["terminal"]
        and projection["terminal_markers"]["execution_complete"]
        and projection["terminal_markers"]["finite_rollout_complete"]
        and projection["transitions"] == TRANSITIONS
        and projection["frames"] == FRAMES
        for projection in valid.values()
    )
    if not terminal_ok:
        _append_error(errors, "not every seed has terminal 835-transition/836-frame markers")

    validator_ok = exact_seeds and all(
        projection["hdf5_validator"] is None
        or (
            projection["hdf5_validator"]["passed"] is True
            and projection["hdf5_validator"]["complete"] is True
            and projection["hdf5_validator"]["qualification_credit"] == 0
        )
        for projection in valid.values()
    )
    if not validator_ok:
        _append_error(errors, "an optional HDF5 validator receipt is malformed or nonzero-credit")

    zero_credit = exact_seeds and all(
        projection["diagnostic_only"] is True
        and projection["formal"] is False
        and projection["formal_eligible"] is False
        and projection["qualification_credit"] == 0
        and projection["credit"] == 0
        for projection in valid.values()
    )
    if not zero_credit:
        _append_error(errors, "terminal receipts are not uniformly diagnostic-only and zero-credit")

    all_bound = (
        exact_seeds
        and shared_config
        and identity_ok
        and namespace_ok
        and terminal_ok
        and validator_ok
        and zero_credit
        and not errors
    )
    for row in rows:
        if row["status"] == "bound_terminal":
            row["status"] = "bound_terminal_diagnostic" if all_bound else "bound_terminal"
            if not all_bound:
                row["blocked_reasons"].extend(errors)
                row["blocked_reasons"] = list(dict.fromkeys(row["blocked_reasons"]))

    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "bound_terminal_diagnostic" if all_bound else "blocked_fail_closed",
        "fail_closed": not all_bound,
        "source_bound": all_bound,
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
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seeds": list(SEEDS),
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "terminal_status": "completed",
            "diagnostic_namespace_per_seed": True,
            "progress_or_pid_is_not_completion": True,
            "hdf5_validator_optional": True,
        },
        "seed_matrix": rows,
        "checks": [
            _check("terminal_seed_set_exact", exact_seeds, "all three future terminal receipts are bound", observed=sorted(valid), expected=list(SEEDS)),
            _check("shared_model_configuration", shared_config, "all seeds use graph_residual hidden16 update-500 on the fixed F3 case", observed=observed_signatures, expected=signature),
            _check("training_checkpoint_identity", identity_ok, "training receipt and checkpoint path/SHA identities are seed-bound and unique"),
            _check("terminal_835_transitions_836_frames", terminal_ok, "every seed is terminal at 835 transitions and 836 frames"),
            _check("unique_full835_diagnostic_namespace", namespace_ok, "every seed has a distinct explicit-fresh full835 diagnostic namespace", observed=sorted(namespaces), expected="three distinct namespaces and nonces"),
            _check("optional_hdf5_validator_receipt", validator_ok, "validator receipt is absent or independently bound, complete, and zero-credit"),
            _check("diagnostic_zero_credit", zero_credit, "formal/T1/T2/qualification are false and all credit is zero"),
        ],
        "blocked_reasons": list(dict.fromkeys(errors)),
        "terminal_sources": {str(seed): sources.get(seed) for seed in SEEDS},
        "side_effects": _empty_side_effects(),
        "input_boundary": _empty_input_boundary(),
        "interpretation": (
            "This matrix consumes bounded terminal-receipt JSON only. It never "
            "opens HDF5, evaluation, progress, trajectory, checkpoint, manifest, "
            "solver, GPU, worker, queue, registry, ledger, denominator, gate, "
            "completion, or PLAN artifacts. Missing future receipts remain blocked."
        ),
    }


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    terminal_paths: Mapping[int, Path | str | None] = DEFAULT_TERMINAL_PATHS,
    observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC,
) -> dict[str, Any]:
    """Read only explicitly selected bounded terminal receipt JSON files."""

    root = Path(os.path.abspath(os.fspath(lab_root)))
    receipts: dict[int, Mapping[str, Any]] = {}
    sources: dict[int, Mapping[str, Any]] = {}
    errors: list[str] = []
    failures: dict[int, str] = {}
    path_rejections: set[int] = set()
    for seed in SEEDS:
        path = terminal_paths.get(seed)
        if path is None:
            sources[seed] = _source_metadata(root, None)
            reason = f"missing configured future terminal receipt for seed {seed}"
            errors.append(reason)
            failures[seed] = reason
            continue
        try:
            payload, source = _read_bounded_json(root, path, f"seed{seed} terminal receipt")
            receipts[seed] = payload
            sources[seed] = source
        except (MatrixError, OSError, ValueError, TypeError, RecursionError) as error:
            try:
                sources[seed] = _source_metadata(root, path)
            except MatrixError:
                path_rejections.add(seed)
                sources[seed] = {"path": str(path), "exists": False, "opened": False, "bytes": None, "sha256": None, "schema": None}
            reason = f"seed{seed} terminal receipt: {error}"
            errors.append(reason)
            failures[seed] = reason
    report = evaluate_payloads(receipts, sources, source_errors=errors)
    for row in report["seed_matrix"]:
        seed = row["seed"]
        if seed in failures:
            row["status"] = (
                "rejected"
                if seed in path_rejections or sources.get(seed, {}).get("exists")
                else "missing"
            )
            row["blocked_reasons"] = [failures[seed]]
    report["observed_at_utc"] = _string(observed_at_utc, "observed_at_utc")
    return report


def _validate_projection_for_report(value: Any, seed: int, name: str) -> None:
    projection = _mapping(value, name)
    for key, expected in (
        ("schema", f"core.f3.graph_residual.hidden16.seed{seed}.full835.terminal_completion_receipt.v1"),
        ("seed", seed),
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("qualification_credit", 0),
        ("credit", 0),
    ):
        _check_exact(projection, key, expected, name)
    _reject_nonzero_credit_or_formal_claim(projection, name)
    if not isinstance(projection.get("output_namespace"), str):
        _fail(f"{name}.output_namespace is missing")
    evaluation = _mapping(projection.get("evaluation"), f"{name}.evaluation")
    _check_exact(evaluation, "namespace", projection["output_namespace"], f"{name}.evaluation")
    _check_exact(evaluation, "namespace_fresh", True, f"{name}.evaluation")
    _check_exact(evaluation, "namespace_nonce", projection.get("namespace_nonce"), f"{name}.evaluation")


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate a generated report without reading any source artifact."""

    errors: list[str] = []
    try:
        _walk_json(report, "report")
        report_map = _mapping(report, "report")
        unknown = sorted(set(report_map) - set(REPORT_TOP_LEVEL_KEYS))
        if unknown:
            _fail(f"report contains unknown or alias top-level field(s): {unknown}")
        _check_exact(report, "schema", REPORT_SCHEMA, "report")
        _check_exact(report, "report_id", REPORT_ID, "report")
        source_bound = report.get("source_bound")
        if type(source_bound) is not bool:
            _fail("report.source_bound must be boolean")
        _check_exact(report, "fail_closed", not source_bound, "report")
        for key, expected in (
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
            _check_exact(report, key, expected, "report")
        expected_contract = _mapping(report.get("expected_contract"), "report.expected_contract")
        for key, expected in (
            ("model_kind", MODEL_KIND),
            ("hidden", HIDDEN),
            ("updates", UPDATES),
            ("seeds", list(SEEDS)),
            ("case_id", CASE_ID),
            ("split", SPLIT),
            ("transitions", TRANSITIONS),
            ("frames", FRAMES),
            ("terminal_status", "completed"),
            ("diagnostic_namespace_per_seed", True),
            ("progress_or_pid_is_not_completion", True),
            ("hdf5_validator_optional", True),
        ):
            _check_exact(expected_contract, key, expected, "report.expected_contract")
        rows = report.get("seed_matrix")
        if not isinstance(rows, list) or [row.get("seed") for row in rows if isinstance(row, Mapping)] != list(SEEDS):
            _fail("report.seed_matrix must contain seeds 17, 29, and 43 in order")
        for row in rows:
            row_map = _mapping(row, "report.seed_matrix row")
            seed = row_map.get("seed")
            if seed not in SEEDS:
                _fail("report.seed_matrix row has an invalid seed")
            status = row_map.get("status")
            if status not in {"missing", "rejected", "bound_terminal", "bound_terminal_diagnostic"}:
                _fail(f"report.seed_matrix seed{seed} has an invalid status")
            projection = row_map.get("projection")
            if status in {"bound_terminal", "bound_terminal_diagnostic"}:
                _validate_projection_for_report(projection, seed, f"report.seed_matrix.seed{seed}.projection")
            elif not isinstance(row_map.get("blocked_reasons"), list) or not row_map["blocked_reasons"]:
                _fail(f"report.seed_matrix seed{seed} lacks a blocker")
        checks = report.get("checks")
        if not isinstance(checks, list) or len(checks) != 7:
            _fail("report.checks must contain seven checks")
        if source_bound:
            _check_exact(report, "status", "bound_terminal_diagnostic", "report")
            if any(not isinstance(item, Mapping) or item.get("passed") is not True for item in checks):
                _fail("bound report checks must all pass")
            if any(row.get("status") != "bound_terminal_diagnostic" for row in rows):
                _fail("bound report must have three diagnostic rows")
        else:
            _check_exact(report, "status", "blocked_fail_closed", "report")
        _validate_effects(report.get("side_effects"), "report.side_effects")
        _validate_input_boundary(report.get("input_boundary"), "report.input_boundary")
        _reject_nonzero_credit_or_formal_claim(report, "report")
    except (MatrixError, KeyError, TypeError, RecursionError) as error:
        errors.append(str(error))
    return list(dict.fromkeys(errors))


def _open_parent_for_write(root: Path, output: Path | str, name: str) -> tuple[int, str]:
    _candidate, components = _report_output_components(root, output, name)
    if len(components) < 1:
        _fail(f"{name} has no filename")
    parent_fd, opened = _open_directory_chain(root, components[:-1], name)
    # The caller owns all descriptors in ``opened`` through the returned
    # parent fd; close intermediates while retaining the last directory fd.
    for descriptor in opened[:-1]:
        try:
            os.close(descriptor)
        except OSError:
            pass
    return parent_fd, components[-1]


def _validate_existing_report_destination(parent_fd: int, filename: str) -> None:
    """Accept only a previously generated report at an existing destination."""

    file_fd = -1
    try:
        try:
            file_fd = os.open(
                filename,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except OSError as error:
            _fail(f"report output cannot be reopened safely: {error}")
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail("report output is not a single-link regular file")
        if before.st_size > MAX_JSON_BYTES:
            _fail("existing report output exceeds bounded size")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(64 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                _fail("existing report output exceeds bounded size")
        after = os.fstat(file_fd)
        identity_fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in identity_fields):
            _fail("existing report output changed while it was being read (TOCTOU)")
        raw = b"".join(chunks)
        if len(raw) != after.st_size:
            _fail("existing report output size changed while it was being read")
        if filename.endswith(REPORT_JSON_SUFFIX):
            try:
                previous = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=_reject_json_constant,
                    object_pairs_hook=_reject_duplicate_keys,
                )
            except MatrixError:
                raise
            except (UnicodeError, json.JSONDecodeError) as error:
                _fail(f"existing report output is not an expected validated report: {error}")
            _walk_json(previous, "existing report output")
            previous_map = _mapping(previous, "existing report output")
            if validate_report(previous_map):
                _fail("existing report output is not an expected validated report")
        else:
            prefix = b"# F3 graph_residual hidden16 full835 "
            if not raw.startswith(prefix) or b"```json\n" not in raw or not raw.rstrip().endswith(b"```"):
                _fail("existing report output is not an expected Markdown report")
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass


def write_report(report: Mapping[str, Any], output: Path | str, *, root: Path | str = LAB_ROOT) -> None:
    """Atomically write one fixed report below ``root/reports``.

    The destination is restricted to the two checked-in report names.  An
    existing destination must be a regular file with exactly one hard link;
    symlinks, directories, devices, and hard-linked files are never replaced.
    """

    errors = validate_report(report)
    if errors:
        raise MatrixError("refusing to write invalid report: " + "; ".join(errors))
    root_path = Path(os.path.abspath(os.fspath(root)))
    parent_fd = -1
    temporary_name: str | None = None
    try:
        parent_fd, filename = _open_parent_for_write(root_path, output, "report output")
        existing = None
        try:
            existing = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode):
                _fail("report output is an existing symlink")
            if not stat.S_ISREG(existing.st_mode):
                _fail("report output is not an existing regular file")
            if existing.st_nlink != 1:
                _fail("report output is an existing hard-linked file")
            _validate_existing_report_destination(parent_fd, filename)
        if filename.endswith(REPORT_MARKDOWN_SUFFIX):
            raw = (
                "# F3 graph_residual hidden16 full835 终态回执矩阵 V1\n\n"
                "```json\n"
                + canonical_json(report)
                + "\n```\n"
            ).encode("utf-8")
        else:
            raw = (canonical_json(report) + "\n").encode("utf-8")
        if len(raw) > MAX_JSON_BYTES:
            _fail("report output exceeds bounded JSON limit")
        for _ in range(16):
            temporary_name = f".{filename}.{secrets.token_hex(12)}.tmp"
            try:
                fd = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                    0o644,
                    dir_fd=parent_fd,
                )
                break
            except FileExistsError:
                continue
        else:
            _fail("could not allocate a unique temporary report path")
        try:
            written = os.write(fd, raw)
            if written != len(raw):
                _fail("short report write")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary_name, filename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        temporary_name = None
    finally:
        if temporary_name is not None and parent_fd >= 0:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except OSError:
                pass
        if parent_fd >= 0:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _parse_seed_paths(values: Sequence[str]) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"--receipt must use SEED=PATH: {raw}")
        seed_text, path_text = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise SystemExit(f"invalid seed in --receipt: {raw}") from error
        if seed not in SEEDS:
            raise SystemExit(f"seed must be one of {SEEDS}: {raw}")
        if seed in result:
            raise SystemExit(f"duplicate seed in --receipt: {raw}")
        result[seed] = Path(path_text)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--observed-at-utc", default=DEFAULT_OBSERVED_AT_UTC)
    args = parser.parse_args(argv)
    paths: dict[int, Path | str | None] = dict(DEFAULT_TERMINAL_PATHS)
    paths.update(_parse_seed_paths(args.receipt))
    report = build_report(args.root, terminal_paths=paths, observed_at_utc=args.observed_at_utc)
    errors = validate_report(report)
    if errors:
        raise SystemExit("report validation failed: " + "; ".join(errors))
    if args.output is not None:
        write_report(report, args.output, root=args.root)
    if args.markdown_output is not None:
        write_report(report, args.markdown_output, root=args.root)
    print(canonical_json(report))
    return 0 if report["source_bound"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
