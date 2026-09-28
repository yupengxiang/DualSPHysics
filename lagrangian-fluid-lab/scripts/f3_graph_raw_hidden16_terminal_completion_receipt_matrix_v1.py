#!/usr/bin/env python3
"""Bind the F3 graph_raw/hidden16 terminal-completion receipt matrix.

This is a read-only adapter for three already-produced JSON receipts or
evidence projections.  It accepts the existing seed17 terminal-evidence
bridge, the seed43 completion-receipt projection, and the future seed29
completion-receipt projection.  It reads no path named by a receipt other
than the bounded JSON input itself: checkpoint, trajectory/HDF5, manifest,
progress, solver, worker, GPU, and queue artifacts are never opened.

The complete matrix remains diagnostic-only.  It never changes registry,
ledger, denominator, gate, completion, formal, T1, T2, qualification, or
credit state.  Missing or conflicting evidence is represented as a
fail-closed report rather than being inferred from progress or a live job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]

REPORT_SCHEMA = (
    "core.f3.graph_raw.hidden16.terminal_completion_receipt_matrix.v1"
)
REPORT_ID = "f3-graph-raw-hidden16-terminal-completion-receipt-matrix-v1"
BRIDGE_SCHEMA = "core.f3.graph_raw.hidden16.terminal_evidence_bridge_report.v1"
COMPLETION_SCHEMA_RE = re.compile(
    r"^core\.f3\.graph_raw\.hidden16\.seed(?P<seed>17|29|43)\."
    r"terminal_completion_receipt\.v1$"
)
TERMINAL_RECEIPT_SCHEMA_RE = re.compile(
    r"^core\.f3\.graph_raw\.hidden16\.seed(?P<seed>17|29|43)\."
    r"full835\.terminal_evidence\.receipt\.v1$"
)

SEEDS = (17, 29, 43)
MODEL_KIND = "graph_raw"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
MAX_JSON_BYTES = 256 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OUTPUT_PREFIX_RE = re.compile(
    r"^/(?P<directory>[^\x00]*?/)??"
    r"f3-graph-raw500-hidden16-seed(?P<seed>17|29|43)-full835-[^/]+$"
)
CHECKPOINT_SUFFIXES = {".pt", ".pth", ".ckpt"}
FORBIDDEN_INPUT_TOKENS = (
    "progress",
    "trajectory",
    "checkpoint",
    "manifest",
    "hdf5",
)

DEFAULT_TERMINAL_PATHS: dict[int, Path | None] = {
    17: LAB_ROOT
    / "reports/F3-GRAPH-RAW-HIDDEN16-TERMINAL-EVIDENCE-BRIDGE-V1-2026-09-28.json",
    # Intentionally absent: a pending seed29 runner report is not a terminal
    # receipt, and the matrix must never infer completion from it.
    29: None,
    43: LAB_ROOT
    / "reports/F3-GRAPH-RAW-HIDDEN16-SEED43-TERMINAL-COMPLETION-RECEIPT-V1-2026-09-28.json",
}
DEFAULT_OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"


class MatrixError(ValueError):
    """Malformed, incomplete, unsafe, or conflicting matrix evidence."""


def _fail(message: str) -> None:
    raise MatrixError(f"fail-closed: {message}")


def _reject_constant(token: str) -> None:
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


def _check_finite(value: Any, name: str = "value") -> None:
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
            _check_finite(item, f"{name}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _check_finite(item, f"{name}[{index}]")
        return
    _fail(f"{name} contains unsupported value {type(value).__name__}")


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


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _resolve_input(root: Path, value: Path | str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    # Keep the final symlink visible to the caller.  Resolving before the
    # symlink check would silently turn an unsafe alias into an ordinary path.
    return path.absolute()


def _read_bounded_json(
    root: Path,
    value: Path | str,
    name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _resolve_input(root, value)
    if path.is_symlink():
        _fail(f"{name} symlink is not allowed: {path}")
    path = path.resolve()
    if path.suffix.lower() != ".json":
        _fail(f"{name} must use a JSON suffix: {path}")
    lowered_name = path.name.lower()
    for token in FORBIDDEN_INPUT_TOKENS:
        if token in lowered_name:
            _fail(f"{name} names a forbidden {token} artifact: {path}")
    if not path.is_file():
        _fail(f"{name} is missing: {path}")
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        _fail(f"{name} exceeds bounded limit {MAX_JSON_BYTES}: {path}")
    try:
        raw = path.read_bytes()
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except MatrixError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read strict UTF-8 {name} {path}: {error}")
    payload = dict(_mapping(payload, name))
    _check_finite(payload, name)
    return payload, {
        "path": _display_path(root, path),
        "exists": True,
        "opened": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload.get("schema"),
    }


def _missing_source(root: Path, value: Path | str | None) -> dict[str, Any]:
    if value is None:
        return {
            "path": None,
            "exists": False,
            "opened": False,
            "bytes": None,
            "sha256": None,
            "schema": None,
        }
    path = _resolve_input(root, value)
    return {
        "path": _display_path(root, path),
        "exists": path.is_file(),
        "opened": False,
        "bytes": None,
        "sha256": None,
        "schema": None,
    }


def _declared_path(value: Any, name: str, suffix: str | None = None) -> str:
    path = _string(value, name)
    path_obj = Path(path)
    if not path_obj.is_absolute() or ".." in path_obj.parts:
        _fail(f"{name} must be absolute and must not contain parent traversal")
    if suffix is not None and path_obj.suffix.lower() != suffix.lower():
        _fail(f"{name} must end with {suffix}")
    return path


def _declared_checkpoint_path(value: Any, name: str) -> str:
    path = _declared_path(value, name)
    if Path(path).suffix.lower() not in CHECKPOINT_SUFFIXES:
        _fail(f"{name} must end with a checkpoint suffix")
    return path


def _check_exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if value.get(key) != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {value.get(key)!r}")


def _validate_zero_formal_markers(value: Any, name: str) -> None:
    """Reject any nested formal/T1/T2/qualification or credit claim."""

    formal_names = {
        "formal",
        "formal_eligible",
        "formal_training",
        "t1_numerical",
        "t2_macro",
        "t2_path",
        "qualification",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = key.lower()
            if lowered == "credit" or lowered.endswith("_credit"):
                if type(item) is not int or item != 0:
                    _fail(f"{name}.{key} must be integer zero")
            if lowered in formal_names:
                if isinstance(item, Mapping):
                    _validate_zero_formal_markers(item, f"{name}.{key}")
                elif item is not False:
                    _fail(f"{name}.{key} must be false")
            if lowered == "diagnostic_only" and item is not True:
                _fail(f"{name}.{key} must be true")
            _validate_zero_formal_markers(item, f"{name}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_zero_formal_markers(item, f"{name}[{index}]")


def _validate_side_effects(value: Any, name: str) -> None:
    effects = _mapping(value, name)
    false_fields = {
        "manifest_opened",
        "case_hdf5_opened",
        "checkpoint_opened",
        "trajectory_hdf5_opened",
        "trajectory_content_opened",
        "hdf5_content_opened",
        "progress_opened",
        "progress_content_opened",
        "runtime_started",
        "solver_started",
        "worker_started",
        "gpu_started",
        "new_evaluation_started",
        "source_modified_by_rollout",
        "production_hdf5_modified",
        "manifest_modified",
        "formal_training_counted",
        "diagnostic_counted_as_t1_or_t2",
        "future_state_inputs",
    }
    zero_fields = {
        "registry_mutation",
        "ledger_mutation",
        "denominator_mutation",
        "gate_mutation",
        "completion_mutation",
        "formal_training_runs_counted",
        "queue_submissions",
        "existing_live_job_stop_count",
        "existing_live_job_restart_count",
    }
    true_read_only_fields = {"rollout_inputs_read_only"}
    true_observation_fields = {"evaluation_stream_hashed_only"}
    for key, item in effects.items():
        lowered = key.lower()
        if key in false_fields:
            if item is not False:
                _fail(f"{name}.{key} must be false")
        elif key in zero_fields:
            if type(item) is not int or item != 0:
                _fail(f"{name}.{key} must be integer zero")
        elif key in true_read_only_fields or key in true_observation_fields:
            if item is not True:
                _fail(f"{name}.{key} must be true")
        elif lowered.endswith("_mutation") or lowered.endswith("_submissions"):
            if type(item) is not int or item != 0:
                _fail(f"{name}.{key} must be integer zero")
        elif "credit" in lowered:
            if type(item) is not int or item != 0:
                _fail(f"{name}.{key} must be integer zero")
        elif lowered in {"t1_numerical", "t2_macro", "t2_path"}:
            if item is not False:
                _fail(f"{name}.{key} must be false")
        elif key == "diagnostic_evaluate_started":
            _strict_bool(item, f"{name}.{key}")


def _validate_namespace(evaluation_path: str, seed: int, name: str) -> str:
    if not evaluation_path.endswith("-evaluation.json"):
        _fail(f"{name} must end with -evaluation.json")
    prefix = evaluation_path[: -len("-evaluation.json")]
    match = OUTPUT_PREFIX_RE.fullmatch(prefix)
    if match is None or int(match.group("seed")) != seed:
        _fail(f"{name} is not a fresh hidden16 seed{seed} full835 namespace")
    return prefix


def _validate_terminal_markers(markers: Mapping[str, Any], name: str) -> None:
    for key, expected in (
        ("terminal", True),
        ("execution_complete", True),
        ("finite_rollout_complete", True),
        ("terminal_status", "completed"),
    ):
        _check_exact(markers, key, expected, name)
    if "source_evaluation_status" in markers:
        if markers["source_evaluation_status"] != "completed":
            _fail(f"{name}.source_evaluation_status must be completed")
    if "evaluation_status" in markers:
        if markers["evaluation_status"] not in {"completed", "completed_diagnostic"}:
            _fail(f"{name}.evaluation_status is not terminal")
    if "source_validator_passed" in markers and markers["source_validator_passed"] is not True:
        _fail(f"{name}.source_validator_passed must be true")


def _validate_hdf5_projection(value: Mapping[str, Any], name: str) -> None:
    for key, expected in (
        ("passed", True),
        ("complete", True),
        ("trajectory_frames", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
        ("executed_frame_count", FRAMES),
        ("tail_frame_count", 0),
    ):
        _check_exact(value, key, expected, name)
    if "qualification_credit" in value:
        _check_exact(value, "qualification_credit", 0, name)
    if "synthetic_only" in value:
        _check_exact(value, "synthetic_only", False, name)
    if "production_artifacts_touched" in value:
        _check_exact(value, "production_artifacts_touched", False, name)


def _optional_artifact_hash(
    value: Mapping[str, Any],
    keys: Sequence[str],
    name: str,
) -> str:
    for key in keys:
        if key in value:
            return _sha256(value[key], f"{name}.{key}")
    _fail(f"{name} is missing a SHA-256 claim")


def _optional_artifact_bytes(
    value: Mapping[str, Any],
    keys: Sequence[str],
    name: str,
) -> int:
    for key in keys:
        if key in value:
            return _strict_int(value[key], f"{name}.{key}", 1)
    _fail(f"{name} is missing a byte-count claim")


def _validate_nested_terminal_receipt(
    value: Mapping[str, Any],
    seed: int,
    *,
    source_kind: str,
    training_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    name = f"terminal_receipt[{seed}]"
    expected_schema = (
        f"core.f3.graph_raw.hidden16.seed{seed}.full835.terminal_evidence.receipt.v1"
    )
    training_hint = value.get("training_binding")
    runner_training_shape_hint = (
        isinstance(training_hint, Mapping)
        and "checkpoint" not in value
        and "checkpoint" in training_hint
        and "path" not in training_hint
    )
    if value.get("schema") != expected_schema:
        # The current seed29 runner's nested terminal projection is carried by
        # a schema-bound completion report but predates a nested schema field.
        if not (seed == 29 and runner_training_shape_hint and "schema" not in value):
            _fail(f"{name}.schema must be {expected_schema}")
    else:
        schema_match = TERMINAL_RECEIPT_SCHEMA_RE.fullmatch(str(value.get("schema")))
        if schema_match is None or int(schema_match.group("seed")) != seed:
            _fail(f"{name}.schema seed mismatch")
    for key, expected in (
        ("diagnostic_only", True),
        ("formal_eligible", False),
        ("seed", seed),
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("qualification_credit", 0),
        ("credit", 0),
    ):
        _check_exact(value, key, expected, name)
    training_value = _mapping(value.get("training_binding"), f"{name}.training_binding")
    runner_training_shape = (
        "checkpoint" not in value
        and "checkpoint" in training_value
        and "path" not in training_value
    )
    if "status" in value:
        _check_exact(value, "status", "completed_diagnostic", name)
    elif not runner_training_shape:
        _fail(f"{name}.status is missing")
    _validate_zero_formal_markers(value, name)
    if "future_state_inputs" in value:
        _check_exact(value, "future_state_inputs", False, name)

    markers = _mapping(value.get("terminal_markers"), f"{name}.terminal_markers")
    _validate_terminal_markers(markers, f"{name}.terminal_markers")

    if "case" in value:
        case = _mapping(value.get("case"), f"{name}.case")
    elif runner_training_shape:
        case = {
            "case_id": value.get("case_id"),
            "family": "F3",
            "split": value.get("split"),
            "registered_transitions": value.get("transitions"),
            "registered_source_frames": value.get("frames"),
        }
    else:
        _fail(f"{name}.case is missing")
    for key, expected in (
        ("case_id", CASE_ID),
        ("family", "F3"),
        ("split", SPLIT),
        ("registered_transitions", TRANSITIONS),
        ("registered_source_frames", FRAMES),
    ):
        _check_exact(case, key, expected, f"{name}.case")

    checkpoint_value = value.get("checkpoint")
    if checkpoint_value is None and runner_training_shape:
        checkpoint_value = training_value.get("checkpoint")
    checkpoint = _mapping(checkpoint_value, f"{name}.checkpoint")
    checkpoint_path = _declared_checkpoint_path(
        checkpoint.get("path"), f"{name}.checkpoint.path"
    )
    checkpoint_sha = _optional_artifact_hash(
        checkpoint,
        ("sha256", "sha256_claimed"),
        f"{name}.checkpoint",
    )
    _check_exact(checkpoint, "update", UPDATES, f"{name}.checkpoint")
    if "content_opened" in checkpoint:
        _check_exact(checkpoint, "content_opened", False, f"{name}.checkpoint")
    if "stat_only" in checkpoint:
        _check_exact(checkpoint, "stat_only", True, f"{name}.checkpoint")
    checkpoint_bytes = None
    if "bytes" in checkpoint:
        checkpoint_bytes = _strict_int(checkpoint["bytes"], f"{name}.checkpoint.bytes", 1)
    elif "bytes_claimed" in checkpoint:
        checkpoint_bytes = _strict_int(
            checkpoint["bytes_claimed"], f"{name}.checkpoint.bytes_claimed", 1
        )

    if runner_training_shape:
        for key, expected in (
            ("schema", "core.training.v1"),
            ("model_kind", MODEL_KIND),
            ("seed", seed),
            ("hidden", HIDDEN),
            ("updates", UPDATES),
        ):
            _check_exact(training_value, key, expected, f"{name}.training_binding")
        if training_source is None:
            _fail(f"{name}.training_binding lacks a source receipt identity")
        training_path = _declared_path(
            training_source.get("path"), f"{name}.training_source.path", ".json"
        )
        training_bytes = _optional_artifact_bytes(
            training_source, ("bytes", "claimed_bytes"), f"{name}.training_source"
        )
        training_sha = _optional_artifact_hash(
            training_source, ("sha256", "claimed_sha256"), f"{name}.training_source"
        )
    else:
        training_path = _declared_path(
            training_value.get("path"), f"{name}.training_binding.path", ".json"
        )
        training_bytes = _optional_artifact_bytes(
            training_value, ("bytes", "claimed_bytes"), f"{name}.training_binding"
        )
        training_sha = _optional_artifact_hash(
            training_value, ("sha256", "claimed_sha256"), f"{name}.training_binding"
        )
        for key, expected in (
            ("schema", "core.training.v1"),
            ("completed_updates", UPDATES),
            ("checkpoint_verified", True),
        ):
            _check_exact(training_value, key, expected, f"{name}.training_binding")
    training_config = _mapping(
        training_value.get("config"), f"{name}.training_binding.config"
    )
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("seed", seed),
        ("updates", UPDATES),
    ):
        _check_exact(training_config, key, expected, f"{name}.training_binding.config")
    if "max_neighbors" in training_config:
        _check_exact(training_config, "max_neighbors", 192, f"{name}.training_binding.config")
    if "target_normalization" in training_config:
        _check_exact(
            training_config,
            "target_normalization",
            "raw_dual_increment_train_shared",
            f"{name}.training_binding.config",
        )
    training_checkpoint = training_value.get("checkpoint")
    if training_checkpoint is not None:
        training_checkpoint = _mapping(
            training_checkpoint, f"{name}.training_binding.checkpoint"
        )
        training_checkpoint_path = _declared_checkpoint_path(
            training_checkpoint.get("path"),
            f"{name}.training_binding.checkpoint.path",
        )
        training_checkpoint_sha = _optional_artifact_hash(
            training_checkpoint,
            ("sha256", "sha256_claimed"),
            f"{name}.training_binding.checkpoint",
        )
        if training_checkpoint_path != checkpoint_path:
            _fail(f"{name} checkpoint path differs between receipt bindings")
        if training_checkpoint_sha != checkpoint_sha:
            _fail(f"{name} checkpoint SHA differs between receipt bindings")
        if "update" in training_checkpoint:
            _check_exact(
                training_checkpoint,
                "update",
                UPDATES,
                f"{name}.training_binding.checkpoint",
            )
    if "path" in training_value:
        if training_path != _declared_path(
            training_value.get("path"), f"{name}.training_binding.path", ".json"
        ):
            _fail(f"{name}.training_binding path normalization drift")

    evaluation = _mapping(value.get("evaluation_binding"), f"{name}.evaluation_binding")
    evaluation_path = _declared_path(
        evaluation.get("path"), f"{name}.evaluation_binding.path", ".json"
    )
    evaluation_bytes = _optional_artifact_bytes(
        evaluation, ("bytes", "claimed_bytes"), f"{name}.evaluation_binding"
    )
    evaluation_sha = _optional_artifact_hash(
        evaluation, ("sha256", "claimed_sha256"), f"{name}.evaluation_binding"
    )
    _check_exact(evaluation, "schema", "core.evaluation.v1", f"{name}.evaluation_binding")
    mode = evaluation.get("mode", evaluation.get("evaluation_mode"))
    if mode != "diagnostic":
        _fail(f"{name}.evaluation_binding must be diagnostic")
    for key, expected in (
        ("requested_steps", TRANSITIONS),
        ("maximum_steps", TRANSITIONS),
        ("frames_executed", TRANSITIONS),
        ("trajectory_frames_including_initial", FRAMES),
        ("full_registered_denominator_complete", True),
        ("future_state_inputs", False),
    ):
        if key in evaluation:
            _check_exact(evaluation, key, expected, f"{name}.evaluation_binding")
    if "diagnostic" in evaluation:
        _check_exact(evaluation, "diagnostic", True, f"{name}.evaluation_binding")
    prefix = _validate_namespace(
        evaluation_path, seed, f"{name}.evaluation_binding.path"
    )

    trajectory = _mapping(value.get("trajectory_binding"), f"{name}.trajectory_binding")
    trajectory_path = _declared_path(
        trajectory.get("path"), f"{name}.trajectory_binding.path", ".h5"
    )
    trajectory_bytes = _optional_artifact_bytes(
        trajectory, ("bytes", "claimed_bytes"), f"{name}.trajectory_binding"
    )
    if trajectory_path != prefix + "-trajectory.h5":
        _fail(f"{name}.trajectory_binding path is not derived from evaluation namespace")
    if trajectory.get("content_opened") is not False:
        _fail(f"{name}.trajectory_binding.content_opened must be false")
    if trajectory.get("stat_only") is not True:
        _fail(f"{name}.trajectory_binding.stat_only must be true")
    if trajectory.get("sha256") is not None and "sha256" in trajectory:
        _sha256(trajectory["sha256"], f"{name}.trajectory_binding.sha256")
    if trajectory.get("sha256_claimed_by_source_summary") is not None:
        _sha256(
            trajectory["sha256_claimed_by_source_summary"],
            f"{name}.trajectory_binding.sha256_claimed_by_source_summary",
        )

    progress_projection: dict[str, Any] | None = None
    if "progress_binding" in value:
        progress = _mapping(value["progress_binding"], f"{name}.progress_binding")
        progress_path = _declared_path(
            progress.get("path"), f"{name}.progress_binding.path", ".json"
        )
        if progress_path != prefix + "-evaluation-progress.json":
            _fail(f"{name}.progress_binding path is not derived from evaluation namespace")
        if progress.get("content_opened") is not False:
            _fail(f"{name}.progress_binding.content_opened must be false")
        if progress.get("stat_only") is not True:
            _fail(f"{name}.progress_binding.stat_only must be true")
        if progress.get("completion_not_inferred") is not True:
            _fail(f"{name}.progress_binding.completion_not_inferred must be true")
        progress_projection = {
            "path": progress_path,
            "bytes": _optional_artifact_bytes(
                progress, ("bytes", "claimed_bytes"), f"{name}.progress_binding"
            ),
        }

    if "validator_binding" in value:
        validator = _mapping(value["validator_binding"], f"{name}.validator_binding")
        _check_exact(validator, "passed", True, f"{name}.validator_binding")
        _check_exact(validator, "complete", True, f"{name}.validator_binding")
        if validator.get("path") is not None:
            _declared_path(validator["path"], f"{name}.validator_binding.path", ".json")
        if "sha256" in validator and validator["sha256"] is not None:
            _sha256(validator["sha256"], f"{name}.validator_binding.sha256")

    hdf5_projection = None
    if "hdf5_validator" in trajectory:
        hdf5 = _mapping(
            trajectory["hdf5_validator"], f"{name}.trajectory_binding.hdf5_validator"
        )
        _validate_hdf5_projection(
            hdf5, f"{name}.trajectory_binding.hdf5_validator"
        )
        hdf5_projection = {
            "passed": True,
            "complete": True,
            "trajectory_frames": FRAMES,
            "trajectory_transitions": TRANSITIONS,
        }

    side_effects = value.get("side_effects")
    _validate_side_effects(side_effects, f"{name}.side_effects")
    if "input_boundary" in value:
        boundary = _mapping(value["input_boundary"], f"{name}.input_boundary")
        for key in (
            "manifest_opened",
            "case_hdf5_opened",
            "checkpoint_opened",
            "trajectory_hdf5_opened",
            "progress_opened",
        ):
            if key in boundary and boundary[key] is not False:
                _fail(f"{name}.input_boundary.{key} must be false")

    return {
        "source_kind": source_kind,
        "schema": value.get("schema", expected_schema),
        "seed": seed,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "config": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "maximum_steps": TRANSITIONS,
            "diagnostic": True,
            "future_state_inputs": False,
        },
        "checkpoint": {
            "path": checkpoint_path,
            "bytes": checkpoint_bytes,
            "sha256": checkpoint_sha,
            "update": UPDATES,
        },
        "training": {
            "path": training_path,
            "bytes": training_bytes,
            "sha256": training_sha,
            "schema": "core.training.v1",
        },
        "evaluation": {
            "path": evaluation_path,
            "bytes": evaluation_bytes,
            "sha256": evaluation_sha,
            "schema": "core.evaluation.v1",
            "frames": TRANSITIONS,
        },
        "trajectory": {
            "path": trajectory_path,
            "bytes": trajectory_bytes,
            "content_opened": False,
        },
        "progress": progress_projection,
        "validator": hdf5_projection,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
        },
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification_credit": 0,
        "credit": 0,
        "output_namespace": prefix,
    }


def _validate_projection_scope(value: Mapping[str, Any], name: str) -> None:
    _validate_zero_formal_markers(value, name)
    scope = value.get("scope", value.get("side_effects"))
    _validate_side_effects(scope, f"{name}.scope")
    boundary = value.get("input_boundary")
    if boundary is not None:
        boundary = _mapping(boundary, f"{name}.input_boundary")
        for key in (
            "manifest_opened",
            "case_hdf5_opened",
            "checkpoint_opened",
            "trajectory_hdf5_opened",
            "progress_opened",
        ):
            if key in boundary and boundary[key] is not False:
                _fail(f"{name}.input_boundary.{key} must be false")
        if "queue_submissions" in boundary and boundary["queue_submissions"] != 0:
            _fail(f"{name}.input_boundary.queue_submissions must be zero")


def _artifact_claim(
    value: Mapping[str, Any],
    name: str,
    *,
    suffix: str,
    require_verified_json: bool = False,
    content_opened: bool | None = None,
) -> dict[str, Any]:
    path = _declared_path(value.get("path"), f"{name}.path", suffix)
    bytes_claim = _optional_artifact_bytes(value, ("bytes", "claimed_bytes"), name)
    sha = _optional_artifact_hash(value, ("sha256", "claimed_sha256"), name)
    if value.get("exists") is False or value.get("regular_file") is False:
        _fail(f"{name} does not identify an existing regular file")
    if value.get("symlink") is True:
        _fail(f"{name} is a symlink")
    if value.get("bytes_match") is False:
        _fail(f"{name}.bytes_match must be true")
    if require_verified_json:
        if value.get("hash_verification") != "verified":
            _fail(f"{name}.hash_verification must be verified")
        if value.get("hash_match") is False:
            _fail(f"{name}.hash_match must be true")
    if content_opened is not None and value.get("content_opened") is not content_opened:
        _fail(f"{name}.content_opened must be {content_opened}")
    return {"path": path, "bytes": bytes_claim, "sha256": sha}


def _validate_direct_completion_report(
    value: Mapping[str, Any],
    seed: int,
) -> dict[str, Any]:
    name = f"completion_report[{seed}]"
    expected_schema = (
        f"core.f3.graph_raw.hidden16.seed{seed}.terminal_completion_receipt.v1"
    )
    _check_exact(value, "schema", expected_schema, name)
    match = COMPLETION_SCHEMA_RE.fullmatch(str(value.get("schema")))
    if match is None or int(match.group("seed")) != seed:
        _fail(f"{name}.schema seed mismatch")
    _check_exact(value, "seed", seed, name)
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("diagnostic_only", True),
        ("formal_eligible", False),
        ("qualification_credit", 0),
    ):
        _check_exact(value, key, expected, name)
    if "source_bound" in value and value["source_bound"] is not True:
        _fail(f"{name}.source_bound must be true")
    if "fail_closed" in value and value["fail_closed"] is not False:
        _fail(f"{name}.fail_closed must be false")
    status = value.get("status")
    if status not in {
        "bound_existing_terminal_summary",
        "bound_terminal_diagnostic",
        "completed_diagnostic_terminal_receipt_bound",
    }:
        _fail(f"{name} is not a terminal bound status")
    _validate_projection_scope(value, name)

    nested = value.get("seed29_terminal_receipt", value.get("terminal_receipt"))
    if isinstance(nested, Mapping):
        training_source = value.get("training_source")
        if training_source is not None:
            training_source = _mapping(training_source, f"{name}.training_source")
        return _validate_nested_terminal_receipt(
            nested,
            seed,
            source_kind="completion_report_nested_receipt",
            training_source=training_source,
        )
    if nested is not None:
        _fail(f"{name}.terminal receipt must be an object")

    markers = _mapping(value.get("terminal_markers"), f"{name}.terminal_markers")
    for key, expected in (
        ("case_id", CASE_ID),
        ("model_kind", MODEL_KIND),
        ("seed", seed),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
    ):
        _check_exact(markers, key, expected, f"{name}.terminal_markers")
    validator = _mapping(markers.get("validator"), f"{name}.terminal_markers.validator")
    for key, expected in (
        ("passed", True),
        ("complete", True),
        ("trajectory_frames", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
        ("tail_frame_count", 0),
    ):
        _check_exact(validator, key, expected, f"{name}.terminal_markers.validator")

    identities = _mapping(value.get("identity_bindings"), f"{name}.identity_bindings")
    training = _artifact_claim(
        _mapping(identities.get("training_receipt"), f"{name}.identity_bindings.training_receipt"),
        f"{name}.identity_bindings.training_receipt",
        suffix=".json",
        require_verified_json=True,
        content_opened=True,
    )
    evaluation = _artifact_claim(
        _mapping(identities.get("evaluation_receipt"), f"{name}.identity_bindings.evaluation_receipt"),
        f"{name}.identity_bindings.evaluation_receipt",
        suffix=".json",
        require_verified_json=True,
        content_opened=True,
    )
    checkpoint_value = _mapping(
        identities.get("checkpoint"), f"{name}.identity_bindings.checkpoint"
    )
    checkpoint_path = _declared_checkpoint_path(
        checkpoint_value.get("path"), f"{name}.identity_bindings.checkpoint.path"
    )
    checkpoint_bytes = _optional_artifact_bytes(
        checkpoint_value,
        ("bytes", "claimed_bytes"),
        f"{name}.identity_bindings.checkpoint",
    )
    checkpoint_sha = _optional_artifact_hash(
        checkpoint_value,
        ("sha256", "claimed_sha256"),
        f"{name}.identity_bindings.checkpoint",
    )
    if checkpoint_value.get("content_opened") is not False:
        _fail(f"{name}.identity_bindings.checkpoint.content_opened must be false")
    if checkpoint_value.get("bytes_match") is False:
        _fail(f"{name}.identity_bindings.checkpoint.bytes_match must be true")
    trajectory = _artifact_claim(
        _mapping(identities.get("trajectory"), f"{name}.identity_bindings.trajectory"),
        f"{name}.identity_bindings.trajectory",
        suffix=".h5",
        content_opened=False,
    )
    validator_claim = _artifact_claim(
        _mapping(identities.get("hdf5_validation"), f"{name}.identity_bindings.hdf5_validation"),
        f"{name}.identity_bindings.hdf5_validation",
        suffix=".json",
        content_opened=False,
    )
    prefix = _validate_namespace(evaluation["path"], seed, f"{name}.evaluation path")
    if trajectory["path"] != prefix + "-trajectory.h5":
        _fail(f"{name}.trajectory path is not derived from evaluation namespace")

    return {
        "source_kind": "completion_report_projection",
        "schema": value["schema"],
        "seed": seed,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "config": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "maximum_steps": TRANSITIONS,
            "diagnostic": True,
            "future_state_inputs": False,
        },
        "checkpoint": {
            "path": checkpoint_path,
            "bytes": checkpoint_bytes,
            "sha256": checkpoint_sha,
            "update": UPDATES,
        },
        "training": {
            "path": training["path"],
            "bytes": training["bytes"],
            "sha256": training["sha256"],
            "schema": "core.training.v1",
        },
        "evaluation": {
            "path": evaluation["path"],
            "bytes": evaluation["bytes"],
            "sha256": evaluation["sha256"],
            "schema": "core.evaluation.v1",
            "frames": TRANSITIONS,
        },
        "trajectory": {
            "path": trajectory["path"],
            "bytes": trajectory["bytes"],
            "content_opened": False,
        },
        "progress": None,
        "validator": {
            "path": validator_claim["path"],
            "bytes": validator_claim["bytes"],
            "passed": True,
            "complete": True,
            "trajectory_frames": FRAMES,
            "trajectory_transitions": TRANSITIONS,
        },
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
        },
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification_credit": 0,
        "credit": 0,
        "output_namespace": prefix,
    }


def _validate_bridge_report(value: Mapping[str, Any], seed: int) -> dict[str, Any]:
    name = f"bridge_report[{seed}]"
    _check_exact(value, "schema", BRIDGE_SCHEMA, name)
    _validate_projection_scope(value, name)
    if value.get("source_bound") is not True:
        _fail(f"{name}.source_bound must be true for a bound bridge projection")
    rows = value.get("seed_matrix")
    if not isinstance(rows, list):
        _fail(f"{name}.seed_matrix must be a list")
    matching: list[Mapping[str, Any]] = []
    for index, row_value in enumerate(rows):
        row = _mapping(row_value, f"{name}.seed_matrix[{index}]")
        if row.get("seed") == seed:
            matching.append(row)
    if len(matching) != 1:
        _fail(f"{name} must contain exactly one seed{seed} row")
    row = matching[0]
    if row.get("status") != "bound_terminal_diagnostic":
        _fail(f"{name}.seed_matrix seed{seed} is not terminal-bound")
    if row.get("blocked_reasons") not in ([], None):
        _fail(f"{name}.seed_matrix seed{seed} has blocked reasons")
    _validate_side_effects(row.get("side_effects"), f"{name}.seed_matrix[{seed}].side_effects")
    receipt = _mapping(
        row.get("terminal_receipt"), f"{name}.seed_matrix[{seed}].terminal_receipt"
    )
    return _validate_nested_terminal_receipt(
        receipt, seed, source_kind="terminal_evidence_bridge_receipt"
    )


def _normalize_payload(value: Mapping[str, Any], seed: int) -> dict[str, Any]:
    schema = value.get("schema")
    if schema == BRIDGE_SCHEMA:
        return _validate_bridge_report(value, seed)
    terminal_match = TERMINAL_RECEIPT_SCHEMA_RE.fullmatch(str(schema))
    if terminal_match is not None:
        if int(terminal_match.group("seed")) != seed:
            _fail(f"terminal receipt schema seed does not match requested seed {seed}")
        return _validate_nested_terminal_receipt(
            value, seed, source_kind="standalone_terminal_receipt"
        )
    completion_match = COMPLETION_SCHEMA_RE.fullmatch(str(schema))
    if completion_match is not None:
        if int(completion_match.group("seed")) != seed:
            _fail(f"completion report schema seed does not match requested seed {seed}")
        return _validate_direct_completion_report(value, seed)
    _fail(f"seed{seed} input schema is not an accepted terminal receipt/projection")


def _validate_normalized_projection(
    value: Mapping[str, Any], seed: int, name: str
) -> None:
    """Validate the compact projection stored in the generated matrix."""

    for key, expected in (
        ("seed", seed),
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("diagnostic_only", True),
        ("formal_eligible", False),
        ("qualification_credit", 0),
        ("credit", 0),
    ):
        _check_exact(value, key, expected, name)
    _validate_zero_formal_markers(value, name)
    config = _mapping(value.get("config"), f"{name}.config")
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("maximum_steps", TRANSITIONS),
        ("diagnostic", True),
        ("future_state_inputs", False),
    ):
        _check_exact(config, key, expected, f"{name}.config")
    checkpoint = _mapping(value.get("checkpoint"), f"{name}.checkpoint")
    _declared_checkpoint_path(checkpoint.get("path"), f"{name}.checkpoint.path")
    _sha256(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")
    _check_exact(checkpoint, "update", UPDATES, f"{name}.checkpoint")
    training = _mapping(value.get("training"), f"{name}.training")
    _declared_path(training.get("path"), f"{name}.training.path", ".json")
    _strict_int(training.get("bytes"), f"{name}.training.bytes", 1)
    _sha256(training.get("sha256"), f"{name}.training.sha256")
    _check_exact(training, "schema", "core.training.v1", f"{name}.training")
    evaluation = _mapping(value.get("evaluation"), f"{name}.evaluation")
    evaluation_path = _declared_path(
        evaluation.get("path"), f"{name}.evaluation.path", ".json"
    )
    _strict_int(evaluation.get("bytes"), f"{name}.evaluation.bytes", 1)
    _sha256(evaluation.get("sha256"), f"{name}.evaluation.sha256")
    _check_exact(evaluation, "schema", "core.evaluation.v1", f"{name}.evaluation")
    _check_exact(evaluation, "frames", TRANSITIONS, f"{name}.evaluation")
    prefix = _validate_namespace(evaluation_path, seed, f"{name}.evaluation.path")
    trajectory = _mapping(value.get("trajectory"), f"{name}.trajectory")
    trajectory_path = _declared_path(
        trajectory.get("path"), f"{name}.trajectory.path", ".h5"
    )
    _strict_int(trajectory.get("bytes"), f"{name}.trajectory.bytes", 1)
    _check_exact(trajectory, "content_opened", False, f"{name}.trajectory")
    if trajectory_path != prefix + "-trajectory.h5":
        _fail(f"{name}.trajectory path is not derived from evaluation namespace")
    progress = value.get("progress")
    if progress is not None:
        progress = _mapping(progress, f"{name}.progress")
        progress_path = _declared_path(
            progress.get("path"), f"{name}.progress.path", ".json"
        )
        _strict_int(progress.get("bytes"), f"{name}.progress.bytes", 1)
        if progress_path != prefix + "-evaluation-progress.json":
            _fail(f"{name}.progress path is not derived from evaluation namespace")
    markers = _mapping(value.get("terminal_markers"), f"{name}.terminal_markers")
    _validate_terminal_markers(markers, f"{name}.terminal_markers")
    validator = value.get("validator")
    if validator is not None:
        validator = _mapping(validator, f"{name}.validator")
        for key, expected in (
            ("passed", True),
            ("complete", True),
            ("trajectory_frames", FRAMES),
            ("trajectory_transitions", TRANSITIONS),
        ):
            _check_exact(validator, key, expected, f"{name}.validator")


def _check(
    name: str,
    passed: bool,
    reason: str,
    *,
    observed: Any = None,
    expected: Any = None,
) -> dict[str, Any]:
    return {
        "check": name,
        "passed": bool(passed),
        "reason": reason,
        "observed": observed,
        "expected": expected,
    }


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
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
    }


def _empty_input_boundary() -> dict[str, Any]:
    return {
        "bounded_json_only": True,
        "max_json_bytes": MAX_JSON_BYTES,
        "manifest_opened": False,
        "case_hdf5_opened": False,
        "checkpoint_opened": False,
        "trajectory_hdf5_opened": False,
        "progress_opened": False,
        "runtime_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_submissions": 0,
    }


def evaluate_payloads(
    projections: Mapping[int, Mapping[str, Any]],
    sources: Mapping[int, Mapping[str, Any]] | None = None,
    *,
    source_errors: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a three-seed report from already normalized projections."""

    sources = dict(sources or {})
    errors = list(source_errors)
    rows: list[dict[str, Any]] = []
    valid: dict[int, Mapping[str, Any]] = {}
    for seed in SEEDS:
        row: dict[str, Any] = {
            "seed": seed,
            "status": "missing",
            "source": sources.get(seed),
            "projection": None,
            "blocked_reasons": [],
        }
        projection = projections.get(seed)
        if projection is None:
            reason = f"missing terminal completion receipt/projection for seed {seed}"
            row["blocked_reasons"].append(reason)
            errors.append(reason)
        else:
            valid[seed] = projection
            row["status"] = "bound_terminal"
            row["projection"] = projection
        rows.append(row)

    exact_seeds = set(valid) == set(SEEDS)
    if not exact_seeds:
        errors.append(
            f"terminal seed set incomplete: observed {sorted(valid)} expected {list(SEEDS)}"
        )

    signatures = {
        seed: {
            "model_kind": value.get("model_kind"),
            "hidden": value.get("hidden"),
            "updates": value.get("updates"),
            "case_id": value.get("case_id"),
            "split": value.get("split"),
            "transitions": value.get("transitions"),
            "frames": value.get("frames"),
        }
        for seed, value in valid.items()
    }
    expected_signature = {
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }
    shared_config = bool(valid) and all(
        signature == expected_signature for signature in signatures.values()
    ) and exact_seeds
    if not shared_config:
        errors.append("seed terminal receipt model/config/case signature is inconsistent")

    checkpoint_consistent = True
    for seed, projection in valid.items():
        checkpoint = projection.get("checkpoint")
        if not isinstance(checkpoint, Mapping):
            checkpoint_consistent = False
            errors.append(f"seed{seed} checkpoint binding is missing")
            continue
        if (
            not isinstance(checkpoint.get("path"), str)
            or not isinstance(checkpoint.get("sha256"), str)
            or checkpoint.get("update") != UPDATES
        ):
            checkpoint_consistent = False
            errors.append(f"seed{seed} checkpoint path/SHA/update binding is incomplete")
        if projection.get("training", {}).get("sha256") is None:
            checkpoint_consistent = False
            errors.append(f"seed{seed} training receipt SHA binding is missing")

    prefixes = [
        projection.get("output_namespace")
        for projection in valid.values()
        if isinstance(projection.get("output_namespace"), str)
    ]
    unique_namespaces = (
        len(prefixes) == len(SEEDS) == len(set(prefixes)) and exact_seeds
    )
    if not unique_namespaces:
        errors.append("terminal output namespaces are missing or reused across seeds")

    terminal_complete = bool(valid) and all(
        projection.get("transitions") == TRANSITIONS
        and projection.get("frames") == FRAMES
        and projection.get("terminal_markers", {}).get("terminal") is True
        and projection.get("terminal_markers", {}).get("execution_complete") is True
        and projection.get("terminal_markers", {}).get("finite_rollout_complete") is True
        for projection in valid.values()
    ) and exact_seeds
    if not terminal_complete:
        errors.append("not every seed has terminal 835-transition/836-frame markers")

    zero_credit = bool(valid) and all(
        projection.get("diagnostic_only") is True
        and projection.get("formal_eligible") is False
        and projection.get("qualification_credit") == 0
        and projection.get("credit") == 0
        for projection in valid.values()
    ) and exact_seeds
    if not zero_credit:
        errors.append("terminal receipts are not uniformly diagnostic-only and zero-credit")

    errors = list(dict.fromkeys(errors))
    all_bound = (
        exact_seeds
        and shared_config
        and checkpoint_consistent
        and unique_namespaces
        and terminal_complete
        and zero_credit
        and not errors
    )
    for row in rows:
        if row["status"] == "bound_terminal":
            row["status"] = "bound_terminal_diagnostic" if all_bound else "bound_terminal"
    status = "bound_terminal_diagnostic" if all_bound else "blocked_fail_closed"
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": status,
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
            "progress_or_pid_is_not_completion": True,
            "fresh_output_identity": True,
        },
        "seed_matrix": rows,
        "checks": [
            _check(
                "terminal_seed_set_exact",
                exact_seeds,
                "all three target seeds have a bound terminal receipt/projection",
                observed=sorted(valid),
                expected=list(SEEDS),
            ),
            _check(
                "shared_model_config_and_case",
                shared_config,
                "all seeds bind graph_raw hidden16 on the same case/configuration",
                observed=signatures,
                expected=expected_signature,
            ),
            _check(
                "checkpoint_path_sha_binding",
                checkpoint_consistent,
                "each seed has a complete checkpoint path/SHA/update binding",
            ),
            _check(
                "terminal_835_transitions_836_frames",
                terminal_complete,
                "every seed is terminal at 835 transitions and 836 frames",
            ),
            _check(
                "fresh_output_namespace_unique",
                unique_namespaces,
                "each seed has a distinct derived full835 output namespace",
                observed=sorted(prefixes),
                expected="three distinct namespaces",
            ),
            _check(
                "diagnostic_zero_credit",
                zero_credit,
                "formal/T1/T2/qualification are false and credit is zero",
            ),
        ],
        "blocked_reasons": errors,
        "terminal_sources": {str(seed): sources.get(seed) for seed in SEEDS},
        "side_effects": _empty_side_effects(),
        "input_boundary": _empty_input_boundary(),
        "interpretation": (
            "This report binds bounded terminal receipt/projection JSON only. "
            "It does not open HDF5, trajectory, checkpoint, manifest, or progress "
            "content and never produces formal/T1/T2/qualification credit."
        ),
    }


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    terminal_paths: Mapping[int, Path | str | None] = DEFAULT_TERMINAL_PATHS,
    observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC,
) -> dict[str, Any]:
    """Read only configured bounded JSON sources and build a fail-closed report."""

    root = Path(lab_root).resolve()
    projections: dict[int, Mapping[str, Any]] = {}
    sources: dict[int, Mapping[str, Any]] = {}
    source_errors: list[str] = []
    source_failures: dict[int, str] = {}
    for seed in SEEDS:
        path = terminal_paths.get(seed)
        if path is None:
            sources[seed] = _missing_source(root, None)
            source_errors.append(f"missing configured terminal path for seed {seed}")
            continue
        try:
            payload, source = _read_bounded_json(root, path, f"seed{seed} terminal input")
            projections[seed] = _normalize_payload(payload, seed)
            sources[seed] = source
        except Exception as error:
            sources[seed] = _missing_source(root, path)
            message = f"seed{seed} terminal input: {error}"
            source_errors.append(message)
            source_failures[seed] = message
    report = evaluate_payloads(projections, sources, source_errors=source_errors)
    for row in report["seed_matrix"]:
        seed = row["seed"]
        if seed in source_failures and terminal_paths.get(seed) is not None:
            row["status"] = "rejected"
            row["blocked_reasons"] = [source_failures[seed]]
    report["observed_at_utc"] = observed_at_utc
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate a generated report without reading any source artifact."""

    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("schema drift")
    if report.get("report_id") != REPORT_ID:
        errors.append("report_id drift")
    expected_flags = {
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
    for key, expected in expected_flags.items():
        if report.get(key) != expected:
            errors.append(f"{key} must be {expected!r}")
    expected_contract = report.get("expected_contract")
    if not isinstance(expected_contract, Mapping):
        errors.append("expected_contract missing")
    else:
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
            ("progress_or_pid_is_not_completion", True),
            ("fresh_output_identity", True),
        ):
            if expected_contract.get(key) != expected:
                errors.append(f"expected_contract.{key} drift")
    rows = report.get("seed_matrix")
    if not isinstance(rows, list) or [row.get("seed") for row in rows if isinstance(row, Mapping)] != list(SEEDS):
        errors.append("seed_matrix must contain seeds 17, 29, and 43 in order")
    else:
        for row in rows:
            if not isinstance(row, Mapping):
                errors.append("seed_matrix row is not an object")
                continue
            status = row.get("status")
            if status not in {
                "missing",
                "rejected",
                "bound_terminal",
                "bound_terminal_diagnostic",
            }:
                errors.append(f"seed{row.get('seed')} row status is invalid")
            projection = row.get("projection")
            if status in {"bound_terminal", "bound_terminal_diagnostic"}:
                if not isinstance(projection, Mapping):
                    errors.append(f"seed{row.get('seed')} bound row lacks projection")
                else:
                    try:
                        _validate_normalized_projection(
                            projection,
                            row["seed"],
                            f"report.seed_matrix[{row['seed']}].projection",
                        )
                    except (KeyError, MatrixError, TypeError) as error:
                        errors.append(str(error))
            if status in {"missing", "rejected"} and not row.get("blocked_reasons"):
                errors.append(f"seed{row.get('seed')} blocked row lacks blocker")
    side_effects = report.get("side_effects")
    try:
        _validate_side_effects(side_effects, "report.side_effects")
    except MatrixError as error:
        errors.append(str(error))
    boundary = report.get("input_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("input_boundary missing")
    else:
        for key in (
            "manifest_opened",
            "case_hdf5_opened",
            "checkpoint_opened",
            "trajectory_hdf5_opened",
            "progress_opened",
            "runtime_started",
            "solver_started",
            "worker_started",
            "gpu_started",
        ):
            if boundary.get(key) is not False:
                errors.append(f"input_boundary.{key} must be false")
        if boundary.get("queue_submissions") != 0:
            errors.append("input_boundary.queue_submissions must be zero")
    source_bound = report.get("source_bound")
    status = report.get("status")
    if type(source_bound) is not bool:
        errors.append("source_bound must be boolean")
    elif source_bound and status != "bound_terminal_diagnostic":
        errors.append("bound report status drift")
    elif not source_bound and status != "blocked_fail_closed":
        errors.append("blocked report status drift")
    if report.get("fail_closed") != (not bool(source_bound)):
        errors.append("fail_closed/source_bound mismatch")
    if source_bound is True:
        if not isinstance(rows, list) or any(
            not isinstance(row, Mapping)
            or row.get("status") != "bound_terminal_diagnostic"
            for row in rows
        ):
            errors.append("bound matrix must have three bound_terminal_diagnostic rows")
        checks = report.get("checks")
        if not isinstance(checks, list) or not checks or any(
            not isinstance(item, Mapping) or item.get("passed") is not True
            for item in checks
        ):
            errors.append("bound matrix checks must all pass")
    return errors


def write_report(report: Mapping[str, Any], output: Path | str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(report) + "\n", encoding="utf-8")


def _parse_seed_path(values: Sequence[str]) -> dict[int, Path]:
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
    parser.add_argument(
        "--receipt",
        action="append",
        default=[],
        metavar="SEED=PATH",
        help="bounded terminal receipt/evidence projection; repeat once per seed",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--observed-at-utc", default=DEFAULT_OBSERVED_AT_UTC)
    args = parser.parse_args(argv)
    paths = dict(DEFAULT_TERMINAL_PATHS)
    paths.update(_parse_seed_path(args.receipt))
    report = build_report(
        args.root,
        terminal_paths=paths,
        observed_at_utc=args.observed_at_utc,
    )
    errors = validate_report(report)
    if errors:
        raise SystemExit("report validation failed: " + "; ".join(errors))
    if args.output is not None:
        write_report(report, args.output)
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
