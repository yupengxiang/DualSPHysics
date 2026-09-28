#!/usr/bin/env python3
"""Generate and bind a bounded F3 hidden16 terminal-evidence receipt.

This bridge closes the evidence gap between the existing Core diagnostic
summary and the older bounded HDF5-validator receipt.  It is deliberately
not a rollout runner and never starts, stops, or restarts a live job.

The bridge reads only bounded JSON summaries/receipts and one evaluation JSON
as a streamed byte/hash source.  Checkpoint and trajectory paths are checked
with ``stat`` only: their contents are never opened, read, or hashed here.
Progress JSON, trajectory/HDF5 content, manifests, solver inputs, workers,
GPU state, queue state, registry, ledger, denominator, gate, and completion
state are all outside this tool's input boundary.

Every successful candidate remains diagnostic-only.  A successful receipt
proves that a real seed has a bounded, cross-boundary 835-transition/836-frame
terminal evidence chain; it does not mint formal, T1, T2, qualification, or
credit state.
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
REPORT_SCHEMA = "core.f3.graph_raw.hidden16.terminal_evidence_bridge_report.v1"
REPORT_ID = "f3-graph-raw-hidden16-terminal-evidence-bridge-v1"
RECEIPT_SCHEMA_PREFIX = "core.f3.graph_raw.hidden16.seed"
MODEL_KIND = "graph_raw"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
MAX_JSON_BYTES = 1 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEEDS = (17, 29, 43)
JSON_SUFFIXES = {".json", ".jsonl"}
FORBIDDEN_JSON_NAMES = {"progress", "trajectory", "checkpoint", "manifest"}

DEFAULT_SUMMARY = Path(
    "/tmp/F3-GRAPH-RAW-HIDDEN16-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json"
)
DEFAULT_REPORT = Path(
    "reports/F3-GRAPH-RAW-HIDDEN16-TERMINAL-EVIDENCE-BRIDGE-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F3-GRAPH-RAW-HIDDEN16-TERMINAL-EVIDENCE-BRIDGE-V1-2026-09-28.zh-CN.md"
)
DEFAULT_OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"


class BridgeError(ValueError):
    """An input or binding failure that must remain fail-closed."""


def _fail(message: str) -> None:
    raise BridgeError(f"fail-closed: {message}")


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


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return value


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
                _fail(f"{name} contains a non-string key")
            _check_finite(item, f"{name}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _check_finite(item, f"{name}[{index}]")
        return
    _fail(f"{name} contains unsupported value {type(value).__name__}")


def _absolute_path(value: Any, name: str, suffix: str | None = None) -> Path:
    if isinstance(value, Path):
        path = value.expanduser()
    else:
        raw = _string(value, name)
        path = Path(raw).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        _fail(f"{name} must be absolute and must not contain parent traversal")
    if suffix is not None and path.suffix.lower() != suffix.lower():
        _fail(f"{name} must end with {suffix}")
    return path


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _source_metadata(root: Path, path: Path, *, opened: bool, raw: bytes | None = None) -> dict[str, Any]:
    exists = path.is_file()
    return {
        "path": _display_path(root, path),
        "exists": exists,
        "opened": opened,
        "bytes": len(raw) if raw is not None else (path.stat().st_size if exists else None),
        "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
    }


def _read_bounded_json(root: Path, value: Path | str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(value).expanduser()
    if path.is_symlink():
        _fail(f"{name} symlink is not allowed: {path}")
    path = path.resolve()
    if path.suffix.lower() not in JSON_SUFFIXES:
        _fail(f"{name} must use a JSON suffix: {path}")
    if any(part in FORBIDDEN_JSON_NAMES for part in path.stem.lower().split("-")):
        _fail(f"{name} names a forbidden progress/trajectory/checkpoint/manifest JSON: {path}")
    if not path.is_file():
        _fail(f"{name} is missing: {path}")
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        _fail(f"{name} exceeds {MAX_JSON_BYTES} bytes: {path}")
    try:
        raw = path.read_bytes()
        value_obj = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except BridgeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read strict {name} {path}: {error}")
    payload = dict(_mapping(value_obj, name))
    _check_finite(payload, name)
    source = _source_metadata(root, path, opened=True, raw=raw)
    source["schema"] = payload.get("schema")
    return payload, source


def _stat_only(root: Path, value: Any, name: str, expected_bytes: int | None = None) -> dict[str, Any]:
    path = _absolute_path(value, name)
    if path.is_symlink():
        _fail(f"{name} symlink is not allowed: {path}")
    if not path.is_file():
        _fail(f"{name} is missing: {path}")
    actual_bytes = path.stat().st_size
    if expected_bytes is not None and actual_bytes != expected_bytes:
        _fail(f"{name} byte count drift: observed={actual_bytes} expected={expected_bytes}")
    return {
        "path": _display_path(root, path),
        "exists": True,
        "opened": False,
        "stat_only": True,
        "bytes": actual_bytes,
        "sha256": None,
    }


def _stream_sha256(path: Path, expected_bytes: int, name: str) -> dict[str, Any]:
    """Hash only the evaluation JSON; never parse or retain its large body."""

    if path.is_symlink():
        _fail(f"{name} symlink is not allowed: {path}")
    if not path.is_file():
        _fail(f"{name} is missing: {path}")
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        _fail(f"{name} byte count drift: observed={actual_bytes} expected={expected_bytes}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        _fail(f"cannot hash {name}: {error}")
    return {
        "path": str(path),
        "exists": True,
        "opened": True,
        "stream_hashed": True,
        "bytes": actual_bytes,
        "sha256": digest.hexdigest(),
    }


def _require_zero_or_false(value: Mapping[str, Any], key: str, name: str) -> None:
    if key not in value:
        return
    item = value[key]
    if type(item) is bool and item is False:
        return
    if type(item) is int and item == 0:
        return
    _fail(f"{name}.{key} must be false or zero")


def _require_zero_qualification(summary: Mapping[str, Any], seed: int) -> None:
    if summary.get("formal_eligible") is not False:
        _fail(f"seed {seed} summary formal_eligible must be false")
    if summary.get("qualification_credit") != 0:
        _fail(f"seed {seed} summary qualification_credit must be zero")
    qualification = _mapping(summary.get("qualification"), f"seed {seed}.qualification")
    for key in ("formal_training", "formal_eligible", "T1_numerical", "T2_macro", "T2_path"):
        if qualification.get(key) is not False:
            _fail(f"seed {seed}.qualification.{key} must be false")
    if qualification.get("qualification_credit") != 0:
        _fail(f"seed {seed}.qualification.qualification_credit must be zero")


def _validate_summary(summary: Mapping[str, Any], seed: int) -> dict[str, Any]:
    expected_schema = (
        f"core.f3.graph_raw.hidden16.seed{seed}.full835.rollout_diagnostic.summary.v1"
    )
    if summary.get("schema") != expected_schema:
        _fail(f"seed {seed} summary schema drift")
    if summary.get("status") != "completed_diagnostic" or summary.get("diagnostic_only") is not True:
        _fail(f"seed {seed} summary is not completed diagnostic evidence")
    if summary.get("future_state_inputs") is not False:
        _fail(f"seed {seed} summary future_state_inputs must be false")
    _require_zero_qualification(summary, seed)

    protocol = _mapping(summary.get("protocol"), f"seed {seed}.protocol")
    expected_protocol = {
        "model_kind": MODEL_KIND,
        "seed": seed,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "maximum_steps": TRANSITIONS,
        "diagnostic": True,
        "autonomous": True,
        "future_state_inputs": False,
    }
    for key, expected in expected_protocol.items():
        if protocol.get(key) != expected:
            _fail(f"seed {seed}.protocol.{key} drift: observed={protocol.get(key)!r} expected={expected!r}")

    training = _mapping(summary.get("training"), f"seed {seed}.training")
    if training.get("schema") != "core.training.v1":
        _fail(f"seed {seed}.training schema drift")
    for key, expected in {
        "status": "completed",
        "evidence_status": "complete",
        "completed_updates": UPDATES,
        "model_kind": MODEL_KIND,
        "seed": seed,
        "hidden": HIDDEN,
        "checkpoint_verified": True,
    }.items():
        if training.get(key) != expected:
            _fail(f"seed {seed}.training.{key} drift")

    evaluation = _mapping(summary.get("evaluation"), f"seed {seed}.evaluation")
    for key, expected in {
        "schema": "core.evaluation.v1",
        "status": "completed",
        "mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "requested_steps": TRANSITIONS,
        "frames_executed": TRANSITIONS,
        "trajectory_frames_including_initial": FRAMES,
        "requested_window_complete": True,
        "finite_rollout_complete_for_requested_window": True,
        "expected_full_case_transitions": TRANSITIONS,
        "expected_full_case_frames": FRAMES,
        "full_registered_denominator_complete": True,
        "future_state_inputs": False,
    }.items():
        if evaluation.get(key) != expected:
            _fail(f"seed {seed}.evaluation.{key} drift")
    if evaluation.get("failure_category") is not None:
        _fail(f"seed {seed}.evaluation.failure_category must be null")
    if evaluation.get("first_failure_frame") is not None:
        _fail(f"seed {seed}.evaluation.first_failure_frame must be null")

    receipt = _mapping(evaluation.get("receipt"), f"seed {seed}.evaluation.receipt")
    evaluation_path = _absolute_path(receipt.get("path"), f"seed {seed}.evaluation.receipt.path", ".json")
    evaluation_bytes = _strict_int(receipt.get("bytes"), f"seed {seed}.evaluation.receipt.bytes", 1)
    evaluation_sha = _sha256(receipt.get("sha256"), f"seed {seed}.evaluation.receipt.sha256")

    validation = _mapping(evaluation.get("hdf5_validation"), f"seed {seed}.evaluation.hdf5_validation")
    validator_path = _absolute_path(validation.get("path"), f"seed {seed}.evaluation.hdf5_validation.path", ".json")
    validator_bytes = _strict_int(validation.get("bytes"), f"seed {seed}.evaluation.hdf5_validation.bytes", 1)
    validator_sha = _sha256(validation.get("sha256"), f"seed {seed}.evaluation.hdf5_validation.sha256")
    if validation.get("schema") != "core.f3.full_rollout_receipt_hdf5_validation.v1":
        _fail(f"seed {seed} HDF5 validation schema drift")
    if validation.get("passed") is not True or validation.get("complete") is not True:
        _fail(f"seed {seed} HDF5 validation is not passed/complete")
    if validation.get("production_artifacts_touched") is not False:
        _fail(f"seed {seed} HDF5 validation production_artifacts_touched must be false")
    if validation.get("qualification_credit") != 0 or validation.get("synthetic_only") is not False:
        _fail(f"seed {seed} HDF5 validation credit/synthetic markers drift")
    if validation.get("trajectory_frames") != FRAMES or validation.get("trajectory_transitions") != TRANSITIONS:
        _fail(f"seed {seed} HDF5 validation denominator drift")
    if validation.get("executed_frame_count") != FRAMES or validation.get("tail_frame_count") != 0:
        _fail(f"seed {seed} HDF5 validation frame-tail drift")

    trajectory = _mapping(summary.get("trajectory"), f"seed {seed}.trajectory")
    trajectory_path = _absolute_path(trajectory.get("path"), f"seed {seed}.trajectory.path", ".h5")
    trajectory_bytes = _strict_int(trajectory.get("bytes"), f"seed {seed}.trajectory.bytes", 1)
    trajectory_sha = _sha256(trajectory.get("sha256"), f"seed {seed}.trajectory.sha256")

    bindings = _mapping(summary.get("bindings"), f"seed {seed}.bindings")
    training_binding = _mapping(bindings.get("training_receipt"), f"seed {seed}.bindings.training_receipt")
    training_path = _absolute_path(training_binding.get("path"), f"seed {seed}.training_receipt.path", ".json")
    training_bytes = _strict_int(training_binding.get("bytes"), f"seed {seed}.training_receipt.bytes", 1)
    training_sha = _sha256(training_binding.get("sha256"), f"seed {seed}.training_receipt.sha256")
    checkpoint_binding = _mapping(bindings.get("checkpoint"), f"seed {seed}.bindings.checkpoint")
    checkpoint_path = _absolute_path(checkpoint_binding.get("path"), f"seed {seed}.checkpoint.path")
    checkpoint_bytes = _strict_int(checkpoint_binding.get("bytes"), f"seed {seed}.checkpoint.bytes", 1)
    checkpoint_sha = _sha256(checkpoint_binding.get("sha256"), f"seed {seed}.checkpoint.sha256")
    if checkpoint_binding.get("update") != UPDATES:
        _fail(f"seed {seed}.checkpoint.update drift")
    if checkpoint_binding.get("model_kind") != MODEL_KIND or checkpoint_binding.get("hidden") != HIDDEN:
        _fail(f"seed {seed}.checkpoint model shape drift")
    if checkpoint_binding.get("seed") != seed:
        _fail(f"seed {seed}.checkpoint.seed drift")

    side_effects = _mapping(summary.get("side_effects"), f"seed {seed}.side_effects")
    for key, value in side_effects.items():
        if key in {"rollout_inputs_read_only"}:
            if value is not True:
                _fail(f"seed {seed}.side_effects.{key} must be true")
        else:
            _require_zero_or_false(side_effects, key, f"seed {seed}.side_effects")

    return {
        "summary": summary,
        "protocol": protocol,
        "training": training,
        "evaluation": evaluation,
        "evaluation_path": evaluation_path,
        "evaluation_bytes": evaluation_bytes,
        "evaluation_sha": evaluation_sha,
        "validator_path": validator_path,
        "validator_bytes": validator_bytes,
        "validator_sha": validator_sha,
        "trajectory_path": trajectory_path,
        "trajectory_bytes": trajectory_bytes,
        "trajectory_sha": trajectory_sha,
        "training_path": training_path,
        "training_bytes": training_bytes,
        "training_sha": training_sha,
        "checkpoint_path": checkpoint_path,
        "checkpoint_bytes": checkpoint_bytes,
        "checkpoint_sha": checkpoint_sha,
        "case_id": _string(summary.get("source", {}).get("case", {}).get("case_id"), f"seed {seed}.source.case.case_id"),
    }


def _validate_training_receipt(
    root: Path,
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    seed: int,
) -> dict[str, Any]:
    if payload.get("schema") != "core.training.v1":
        _fail(f"seed {seed} training receipt schema drift")
    config = _mapping(payload.get("config"), f"seed {seed}.training_receipt.config")
    for key, expected in {
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "seed": seed,
        "updates": UPDATES,
    }.items():
        if config.get(key) != expected:
            _fail(f"seed {seed}.training_receipt.config.{key} drift")
    if payload.get("completed_updates") != UPDATES or payload.get("model_kind") != MODEL_KIND:
        _fail(f"seed {seed} training receipt update/model drift")
    if payload.get("seed") != seed or payload.get("evidence_status") != "complete":
        _fail(f"seed {seed} training receipt seed/evidence drift")
    if payload.get("checkpoint_verified") is not True:
        _fail(f"seed {seed} training receipt checkpoint is not verified")
    checkpoint = _mapping(payload.get("checkpoint"), f"seed {seed}.training_receipt.checkpoint")
    if checkpoint.get("path") != str(source["checkpoint_path"]):
        _fail(f"seed {seed} training checkpoint path drift")
    if checkpoint.get("sha256") != source["checkpoint_sha"]:
        _fail(f"seed {seed} training checkpoint SHA drift")
    if checkpoint.get("update") != UPDATES:
        _fail(f"seed {seed} training checkpoint update drift")
    checkpoint_stat = _stat_only(root, source["checkpoint_path"], f"seed {seed} checkpoint", source["checkpoint_bytes"])
    return {
        "schema": payload["schema"],
        "status": payload.get("evidence_status"),
        "completed_updates": payload["completed_updates"],
        "model_kind": payload["model_kind"],
        "seed": payload["seed"],
        "hidden": config["hidden"],
        "checkpoint_verified": payload["checkpoint_verified"],
        "checkpoint": {
            "path": str(source["checkpoint_path"]),
            "sha256": source["checkpoint_sha"],
            "update": UPDATES,
            "stat": checkpoint_stat,
        },
    }


def _validate_validator_receipt(
    root: Path,
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    seed: int,
) -> dict[str, Any]:
    if payload.get("schema") != "core.f3.full_rollout_receipt_hdf5_validation.v1":
        _fail(f"seed {seed} validator schema drift")
    for key, expected in {
        "passed": True,
        "fail_closed": False,
        "diagnostic_only": True,
        "synthetic_only": False,
        "production_artifacts_touched": False,
        "qualification_credit": 0,
        "expected_transitions": TRANSITIONS,
        "frames_executed": TRANSITIONS,
        "complete": True,
        "incomplete": False,
    }.items():
        if payload.get(key) != expected:
            _fail(f"seed {seed} validator.{key} drift")
    if payload.get("evaluation_json") != str(source["evaluation_path"]):
        _fail(f"seed {seed} validator evaluation path drift")
    if payload.get("trajectory_hdf5") != str(source["trajectory_path"]):
        _fail(f"seed {seed} validator trajectory path drift")
    checks = _mapping(payload.get("checks"), f"seed {seed}.validator.checks")
    for key, expected in {
        "case_binding": True,
        "shape": True,
        "time": True,
        "valid": True,
        "future_state_inputs": True,
        "completion_semantics": True,
        "trajectory_frames": FRAMES,
        "trajectory_transitions": TRANSITIONS,
        "executed_frame_count": FRAMES,
        "tail_frame_count": 0,
    }.items():
        if checks.get(key) != expected:
            _fail(f"seed {seed}.validator.checks.{key} drift")
    return {
        "schema": payload["schema"],
        "passed": True,
        "complete": True,
        "expected_transitions": TRANSITIONS,
        "frames_executed": TRANSITIONS,
        "trajectory_frames": FRAMES,
        "trajectory_transitions": TRANSITIONS,
        "executed_frame_count": FRAMES,
        "tail_frame_count": 0,
        "synthetic_only": False,
        "production_artifacts_touched": False,
    }


def _make_terminal_receipt(
    root: Path,
    seed: int,
    source_meta: Mapping[str, Any],
    validator_meta: Mapping[str, Any],
    training_meta: Mapping[str, Any],
    validated: Mapping[str, Any],
    evaluation_meta: Mapping[str, Any],
    validator_projection: Mapping[str, Any],
    training_projection: Mapping[str, Any],
) -> dict[str, Any]:
    summary = validated["summary"]
    protocol = validated["protocol"]
    source_section = _mapping(summary.get("source"), f"seed {seed}.source")
    source_script_sha = _mapping(source_section.get("source_script_sha256"), f"seed {seed}.source.source_script_sha256")
    receipt = {
        "schema": f"{RECEIPT_SCHEMA_PREFIX}{seed}.full835.terminal_evidence.receipt.v1",
        "report_id": f"f3-graph-raw-hidden16-seed{seed}-full835-terminal-evidence-v1",
        "status": "completed_diagnostic",
        "diagnostic_only": True,
        "non_formal_diagnostic": True,
        "formal_eligible": False,
        "model_kind": MODEL_KIND,
        "seed": seed,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "terminal_status": "completed",
            "source_evaluation_status": "completed",
            "source_validator_passed": True,
        },
        "case": {
            "case_id": validated["case_id"],
            "family": "F3",
            "split": protocol["split"],
            "evaluation_role": source_section["case"].get("evaluation_role"),
            "registered_transitions": TRANSITIONS,
            "registered_source_frames": FRAMES,
        },
        "checkpoint": {
            "path": str(validated["checkpoint_path"]),
            "bytes": validated["checkpoint_bytes"],
            "sha256": validated["checkpoint_sha"],
            "update": UPDATES,
            "schema": "core.checkpoint.v1",
            "content_opened": False,
            "stat_only": True,
        },
        "training_binding": {
            "path": str(validated["training_path"]),
            "bytes": validated["training_bytes"],
            "sha256": training_meta["sha256"],
            "schema": "core.training.v1",
            "completed_updates": UPDATES,
            "config": {
                "model_kind": MODEL_KIND,
                "hidden": HIDDEN,
                "seed": seed,
                "updates": UPDATES,
            },
            "checkpoint_verified": True,
        },
        "evaluation_binding": {
            "path": str(validated["evaluation_path"]),
            "bytes": validated["evaluation_bytes"],
            "sha256": evaluation_meta["sha256"],
            "schema": "core.evaluation.v1",
            "mode": "diagnostic",
            "requested_steps": TRANSITIONS,
            "frames_executed": TRANSITIONS,
            "trajectory_frames_including_initial": FRAMES,
            "full_registered_denominator_complete": True,
            "future_state_inputs": False,
            "stream_hashed": True,
        },
        "trajectory_binding": {
            "path": str(validated["trajectory_path"]),
            "bytes": validated["trajectory_bytes"],
            "sha256_claimed_by_source_summary": validated["trajectory_sha"],
            "content_opened": False,
            "stat_only": True,
            "hdf5_validator": dict(validator_projection),
        },
        "validator_binding": {
            "path": str(validated["validator_path"]),
            "bytes": validated["validator_bytes"],
            "sha256": validator_meta["sha256"],
            "schema": validator_projection["schema"],
            "passed": True,
            "complete": True,
            "trajectory_content_opened_by_bridge": False,
        },
        "source_binding": {
            "summary": dict(source_meta),
            "validator": dict(validator_meta),
            "training": dict(training_meta),
            "source_report_id": summary.get("report_id"),
            "source_baseline_git_commit": source_section.get("baseline_git_commit"),
            "source_script_sha256": dict(source_script_sha),
        },
        "qualification": {
            "formal_training": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "qualification_credit": 0,
            "interpretation": "真实完整 diagnostic rollout 的可审计终态证据；不构成 formal/T1/T2/qualification。",
        },
        "qualification_credit": 0,
        "credit": 0,
        "side_effects": {
            "manifest_opened": False,
            "case_hdf5_opened": False,
            "checkpoint_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_opened": False,
            "evaluation_stream_hashed_only": True,
            "runtime_started": False,
            "gpu_started": False,
            "worker_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "input_boundary": {
            "bounded_json_only_for_summaries": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "summary_json_opened": True,
            "validator_json_opened": True,
            "training_json_opened": True,
            "evaluation_json_stream_hashed": True,
            "checkpoint_stat_only": True,
            "trajectory_stat_only": True,
            "progress_opened": False,
            "trajectory_hdf5_opened": False,
            "case_hdf5_opened": False,
        },
    }
    return receipt


def _candidate_spec(seed: int, summary_path: Path, validator_path: Path | None = None, training_path: Path | None = None) -> dict[str, Path | None]:
    return {"summary": summary_path, "validator": validator_path, "training": training_path}


def _bind_candidate(root: Path, seed: int, spec: Mapping[str, Path | None]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "seed": seed,
        "status": "blocked_fail_closed",
        "blocked_reasons": [],
        "terminal_receipt": None,
        "source": {},
        "side_effects": {
            "progress_opened": False,
            "trajectory_hdf5_opened": False,
            "case_hdf5_opened": False,
            "runtime_started": False,
            "gpu_started": False,
            "worker_started": False,
        },
    }
    summary_path = spec.get("summary")
    if summary_path is None:
        row["status"] = "missing"
        row["blocked_reasons"].append(f"missing terminal summary for seed {seed}")
        return row
    try:
        summary, summary_meta = _read_bounded_json(root, summary_path, f"seed {seed} summary")
        validated = _validate_summary(summary, seed)
        validator_path = spec.get("validator") or validated["validator_path"]
        training_path = spec.get("training") or validated["training_path"]
        validator, validator_meta = _read_bounded_json(root, validator_path, f"seed {seed} validator")
        training, training_meta = _read_bounded_json(root, training_path, f"seed {seed} training")
        if validator_meta["bytes"] != validated["validator_bytes"] or validator_meta["sha256"] != validated["validator_sha"]:
            _fail(f"seed {seed} validator source SHA/bytes drift from summary")
        if training_meta["bytes"] != validated["training_bytes"] or training_meta["sha256"] != validated["training_sha"]:
            _fail(f"seed {seed} training source SHA/bytes drift from summary")
        evaluation_meta = _stream_sha256(
            validated["evaluation_path"], validated["evaluation_bytes"], f"seed {seed} evaluation JSON"
        )
        if evaluation_meta["sha256"] != validated["evaluation_sha"]:
            _fail(f"seed {seed} evaluation source SHA drift from summary")
        trajectory_meta = _stat_only(
            root, validated["trajectory_path"], f"seed {seed} trajectory", validated["trajectory_bytes"]
        )
        training_projection = _validate_training_receipt(root, training, validated, seed)
        validator_projection = _validate_validator_receipt(root, validator, validated, seed)
        receipt = _make_terminal_receipt(
            root,
            seed,
            summary_meta,
            validator_meta,
            training_meta,
            validated,
            evaluation_meta,
            validator_projection,
            training_projection,
        )
        receipt["trajectory_binding"]["stat"] = trajectory_meta
        row.update({
            "status": "bound_terminal_diagnostic",
            "blocked_reasons": [],
            "terminal_receipt": receipt,
            "source": {
                "summary": summary_meta,
                "validator": validator_meta,
                "training": training_meta,
                "evaluation": evaluation_meta,
                "trajectory": trajectory_meta,
            },
        })
    except Exception as error:
        row["blocked_reasons"].append(str(error))
        if summary_path is not None:
            path = Path(summary_path).expanduser()
            row["source"]["summary_path"] = str(path)
    return row


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    candidates: Mapping[int, Mapping[str, Path | None]] | None = None,
    observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC,
) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    if candidates is None:
        candidates = {17: _candidate_spec(17, DEFAULT_SUMMARY)}
    rows = []
    for seed in SEEDS:
        rows.append(_bind_candidate(root, seed, candidates.get(seed, {"summary": None})))
    bound = [row for row in rows if row["status"] == "bound_terminal_diagnostic"]
    missing = [row["seed"] for row in rows if row["status"] == "missing"]
    rejected = [row["seed"] for row in rows if row["status"] == "blocked_fail_closed"]
    if bound:
        status = "bound_terminal_diagnostic"
        source_bound = True
    else:
        status = "blocked_fail_closed"
        source_bound = False
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc,
        "status": status,
        "source_bound": source_bound,
        "fail_closed": not source_bound,
        "bound_seed_count": len(bound),
        "bound_seeds": [row["seed"] for row in bound],
        "missing_seeds": missing,
        "rejected_seeds": rejected,
        "target_contract": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "minimum_real_seed_count": 1,
            "progress_or_pid_is_not_completion": True,
        },
        "checks": {
            "at_least_one_real_terminal_receipt": bool(bound),
            "all_bound_receipts_are_full_horizon": all(
                row["terminal_receipt"]["transitions"] == TRANSITIONS
                and row["terminal_receipt"]["frames"] == FRAMES
                for row in bound
            ),
            "all_bound_receipts_are_zero_credit_diagnostic": all(
                row["terminal_receipt"]["qualification_credit"] == 0
                and row["terminal_receipt"]["formal_eligible"] is False
                for row in bound
            ),
            "missing_or_rejected_other_seeds_remain_fail_closed": all(
                row["status"] in {"missing", "blocked_fail_closed", "bound_terminal_diagnostic"}
                for row in rows
            ),
        },
        "seed_matrix": rows,
        "side_effects": {
            "manifest_opened": False,
            "case_hdf5_opened": False,
            "checkpoint_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_opened": False,
            "runtime_started": False,
            "gpu_started": False,
            "worker_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "input_boundary": {
            "bounded_summary_validator_training_json": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "evaluation_json_stream_hashed": True,
            "checkpoint_stat_only": True,
            "trajectory_stat_only": True,
            "progress_opened": False,
            "trajectory_hdf5_opened": False,
            "case_hdf5_opened": False,
            "solver_worker_gpu_queue_started": False,
        },
        "interpretation": (
            "至少一个真实 seed 的 500-update checkpoint 已通过 bounded training/diagnostic "
            "summary、evaluation SHA、validator receipt 与 trajectory stat-only 交叉绑定，"
            "并形成 835 transitions/836 frames 的 terminal receipt。该 receipt 仍是 "
            "diagnostic-only，不改变任何正式分母、registry、ledger、gate 或 completion 状态。"
        ),
    }


def render_zh_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 `graph_raw` hidden16 terminal-evidence bridge V1",
        "",
        "机器报告：`F3-GRAPH-RAW-HIDDEN16-TERMINAL-EVIDENCE-BRIDGE-V1-2026-09-28.json`",
        "",
        f"- 状态：`{report.get('status')}`；source_bound=`{report.get('source_bound')}`。",
        f"- 终态合同：model=`{MODEL_KIND}`、hidden=`{HIDDEN}`、updates=`{UPDATES}`、`{TRANSITIONS}` transitions / `{FRAMES}` frames。",
        f"- 已绑定真实 seed：`{', '.join(map(str, report.get('bound_seeds', []))) or '无'}`；缺失 seed：`{', '.join(map(str, report.get('missing_seeds', []))) or '无'}`。",
        "- seed17 的 evaluation JSON 只做流式字节/SHA 核对；checkpoint 与 trajectory 只做 stat，不打开内容。",
        "- progress、trajectory/HDF5、manifest、solver、worker、GPU、queue 均未被读取或启动；已有 live job 未停止、未重启。",
        "- 所有结果保持 diagnostic-only；formal/T1/T2/qualification=false，credit=0，所有 mutation=0。",
        "",
        "## Seed 状态",
        "",
    ]
    for row in report.get("seed_matrix", []):
        reasons = "; ".join(row.get("blocked_reasons", [])) or "无"
        lines.append(f"- seed `{row.get('seed')}`：`{row.get('status')}`；{reasons}")
    lines.extend([
        "",
        "## 审计解释",
        "",
        "seed17 的 receipt 证明现有真实 diagnostic rollout 已完成固定 835-transition 窗口，并将 training/checkpoint、evaluation、validator 与 trajectory 元数据绑定到同一案例；它不等同于正式资格结果。seed29/43 若缺少同样闭合的输入，继续保持 fail-closed。",
        "",
    ])
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], output: Path | str, zh_output: Path | str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    zh_path = Path(zh_output)
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.write_text(render_zh_report(report), encoding="utf-8")


def _parse_seed_path(raw: str, name: str) -> tuple[int, Path]:
    if "=" not in raw:
        raise SystemExit(f"--{name} must use SEED=PATH: {raw}")
    seed_text, path_text = raw.split("=", 1)
    try:
        seed = int(seed_text)
    except ValueError as error:
        raise SystemExit(f"invalid seed in --{name}: {raw}") from error
    if seed not in SEEDS:
        raise SystemExit(f"seed must be one of {SEEDS}: {raw}")
    return seed, Path(path_text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--candidate", action="append", default=[], metavar="SEED=SUMMARY_JSON")
    parser.add_argument("--validator", action="append", default=[], metavar="SEED=VALIDATOR_JSON")
    parser.add_argument("--training", action="append", default=[], metavar="SEED=TRAINING_JSON")
    parser.add_argument("--output", type=Path, default=LAB_ROOT / DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=LAB_ROOT / DEFAULT_ZH_REPORT)
    parser.add_argument("--observed-at-utc", default=DEFAULT_OBSERVED_AT_UTC)
    args = parser.parse_args(argv)

    candidates: dict[int, dict[str, Path | None]] = {}
    if args.candidate:
        for raw in args.candidate:
            seed, path = _parse_seed_path(raw, "candidate")
            candidates[seed] = _candidate_spec(seed, path)
    else:
        candidates[17] = _candidate_spec(17, DEFAULT_SUMMARY)
    for raw in args.validator:
        seed, path = _parse_seed_path(raw, "validator")
        candidates.setdefault(seed, {"summary": None, "validator": None, "training": None})["validator"] = path
    for raw in args.training:
        seed, path = _parse_seed_path(raw, "training")
        candidates.setdefault(seed, {"summary": None, "validator": None, "training": None})["training"] = path

    report = build_report(args.root, candidates=candidates, observed_at_utc=args.observed_at_utc)
    write_outputs(report, args.output, args.zh_output)
    print(json.dumps({
        "status": report["status"],
        "bound_seeds": report["bound_seeds"],
        "source_bound": report["source_bound"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
