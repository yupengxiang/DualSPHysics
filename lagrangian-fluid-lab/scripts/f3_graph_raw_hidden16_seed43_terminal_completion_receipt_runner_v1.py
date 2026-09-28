#!/usr/bin/env python3
"""Bind the existing F3 graph_raw/hidden16 seed43 full835 terminal summary.

This runner is intentionally seed43-specific and read-only with respect to the
experiment inputs.  It does not start, stop, or restart a job.  It first binds
the already-produced bounded diagnostic summary and verifies the bytes and
SHA-256 of the training/evaluation JSON receipts.  Checkpoint, trajectory,
progress, HDF5, manifest, and solver artifacts are never opened; their paths
are checked with ``lstat`` only.  A complete result remains diagnostic-only and
never changes formal, T1, T2, registry, ledger, denominator, or gate state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
from pathlib import Path
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FILENAME = "F3-GRAPH-RAW-HIDDEN16-SEED43-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json"
REPORT_FILENAME = "F3-GRAPH-RAW-HIDDEN16-SEED43-TERMINAL-COMPLETION-RECEIPT-V1-2026-09-28.json"
ZH_REPORT_FILENAME = (
    "F3-GRAPH-RAW-HIDDEN16-SEED43-TERMINAL-COMPLETION-RECEIPT-V1-2026-09-28.zh-CN.md"
)
REPORT_SCHEMA = "core.f3.graph_raw.hidden16.seed43.terminal_completion_receipt.v1"
REPORT_ID = "f3-graph-raw-hidden16-seed43-terminal-completion-receipt-v1"
SUMMARY_SCHEMA = "core.f3.graph_raw.hidden16.full835.rollout_diagnostic.summary.v1"
SUMMARY_MAX_BYTES = 256 * 1024
SHA256_RE = set("0123456789abcdef")
MODEL_KIND = "graph_raw"
SEED = 43
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
DEFAULT_SUMMARY = LAB_ROOT / "reports" / SUMMARY_FILENAME
DEFAULT_REPORT = LAB_ROOT / "reports" / REPORT_FILENAME
DEFAULT_ZH_REPORT = LAB_ROOT / "reports" / ZH_REPORT_FILENAME
CASE_ID = "F3_DEV_00_a0p903125"
DEFAULT_TRAINING = Path("/tmp/f3-graph-raw500-hidden16-seed43-20260928-training.json")
DEFAULT_EVALUATION = Path(
    "/tmp/f3-graph-raw500-hidden16-seed43-full835-20260928-evaluation.json"
)
DEFAULT_VALIDATOR = Path(
    "/tmp/f3-graph-raw500-hidden16-seed43-full835-20260928-hdf5-validation.json"
)
DEFAULT_CHECKPOINT = Path("/tmp/f3-graph-raw500-hidden16-seed43-20260928-checkpoint.pt")
DEFAULT_TRAJECTORY = Path(
    "/tmp/f3-graph-raw500-hidden16-seed43-full835-20260928-trajectory.h5"
)
DEFAULT_TERMINAL_SUMMARY = DEFAULT_SUMMARY


class ClosureError(ValueError):
    """A fail-closed terminal binding error."""


class ReceiptError(ClosureError):
    """An explicit seed43 receipt input failed validation."""


def _reject_constant(token: str) -> None:
    raise ClosureError(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            # The pre-existing seed43 diagnostic summary has one legacy
            # top-level ``qualification`` scalar followed by its structured
            # qualification object.  Accept only that known shape so the
            # seed43-specific runner can reconcile the already-produced
            # artifacts without editing the historical summary.  Every other
            # duplicate remains fail-closed.
            if (
                key == "qualification"
                and result[key] is False
                and isinstance(value, Mapping)
                and all(
                    value.get(field) is False
                    for field in (
                        "formal_training",
                        "formal_eligible",
                        "T1_numerical",
                        "T2_macro",
                        "T2_path",
                    )
                )
                and value.get("qualification_credit") == 0
            ):
                result[key] = value
                continue
            raise ClosureError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _summary_pairs(
    pairs: list[tuple[str, Any]], duplicate_records: list[dict[str, Any]]
) -> dict[str, Any]:
    """Allow only the known legacy qualification alias in the source summary."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key not in result:
            result[key] = value
            continue
        duplicate_records.append(
            {
                "key": key,
                "first_type": type(result[key]).__name__,
                "duplicate_type": type(value).__name__,
            }
        )
        if (
            len(duplicate_records) == 1
            and key == "qualification"
            and result[key] is False
            and isinstance(value, Mapping)
        ):
            result[key] = value
            continue
        raise ClosureError(f"unexpected duplicate JSON key: {key}")
    return result


def _check_finite(value: Any, name: str = "value") -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ClosureError(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ClosureError(f"{name} contains a non-string key")
            _check_finite(item, f"{name}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_finite(item, f"{name}[{index}]")
        return
    raise ClosureError(f"{name} contains unsupported value {type(value).__name__}")


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
        raise ClosureError(f"{name} must be an object")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ClosureError(f"{name} must be an integer >= {minimum}")
    return value


def _sha256(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or set(value) - SHA256_RE
        or value.lower() != value
    ):
        raise ClosureError(f"{name} must be a lowercase SHA-256")
    return value


def _absolute_path(value: Any, name: str, suffix: str | None = None) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ClosureError(f"{name} must be a non-empty path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ClosureError(f"{name} must be absolute and free of parent traversal")
    if suffix is not None and path.suffix != suffix:
        raise ClosureError(f"{name} must end with {suffix}")
    return path


def _read_summary(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ClosureError(f"summary is not a regular non-symlink file: {path}")
    size = path.stat().st_size
    if size > SUMMARY_MAX_BYTES:
        raise ClosureError(f"summary exceeds bounded input size: {size}>{SUMMARY_MAX_BYTES}")
    raw = path.read_bytes()
    duplicate_records: list[dict[str, Any]] = []
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=lambda pairs: _summary_pairs(pairs, duplicate_records),
        )
    except (UnicodeError, json.JSONDecodeError, ClosureError) as error:
        raise ClosureError(f"invalid bounded summary JSON: {error}") from error
    value = dict(_mapping(value, "summary"))
    _check_finite(value, "summary")
    return value, {
        "path": str(path),
        "bytes": size,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
        "duplicate_json_keys": duplicate_records,
        "duplicate_key_policy": (
            "accepted_one_known_legacy_qualification_alias"
            if duplicate_records
            else "strict_no_duplicates"
        ),
    }


def _lstat_identity(
    path: Path,
    *,
    claim_bytes: int,
    claim_sha256: str,
    content_opened: bool,
    hash_verification: str,
) -> dict[str, Any]:
    """Return metadata without opening ``path``.

    ``content_opened`` is an explicit assertion supplied by the caller.  The
    function itself only calls ``lstat`` and therefore is safe for checkpoint,
    trajectory, progress, and HDF5 paths.
    """

    try:
        metadata = os.lstat(path)
    except OSError as error:
        return {
            "path": str(path),
            "claimed_bytes": claim_bytes,
            "claimed_sha256": claim_sha256,
            "exists": False,
            "symlink": False,
            "regular_file": False,
            "stat_bytes": None,
            "bytes_match": False,
            "content_opened": content_opened,
            "hash_verification": hash_verification,
            "error": f"{type(error).__name__}:{error}",
        }
    symlink = stat.S_ISLNK(metadata.st_mode)
    regular_file = stat.S_ISREG(metadata.st_mode)
    return {
        "path": str(path),
        "claimed_bytes": claim_bytes,
        "claimed_sha256": claim_sha256,
        "exists": True,
        "symlink": symlink,
        "regular_file": regular_file,
        "stat_bytes": metadata.st_size,
        "bytes_match": regular_file and not symlink and metadata.st_size == claim_bytes,
        "content_opened": content_opened,
        "hash_verification": hash_verification,
    }


def _hash_allowed_json(path: Path, claim: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Hash only the two explicitly permitted JSON receipt files."""

    if any(token in path.name.lower() for token in ("progress", "trajectory", "hdf5", "manifest", "checkpoint")):
        raise ClosureError(f"refusing to hash forbidden artifact as {name}: {path.name}")
    claim_bytes = _strict_int(claim.get("bytes"), f"{name}.bytes", 1)
    claim_sha = _sha256(claim.get("sha256"), f"{name}.sha256")
    stat_result = _lstat_identity(
        path,
        claim_bytes=claim_bytes,
        claim_sha256=claim_sha,
        content_opened=False,
        hash_verification="not_started",
    )
    if not stat_result["exists"] or not stat_result["regular_file"] or stat_result["symlink"]:
        stat_result["hash_verification"] = "not_attempted_missing_or_non_regular"
        return stat_result
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha = digest.hexdigest()
    stat_result["content_opened"] = True
    stat_result["actual_sha256"] = actual_sha
    stat_result["hash_match"] = actual_sha == claim_sha
    stat_result["hash_verification"] = "verified" if stat_result["hash_match"] else "sha256_mismatch"
    return stat_result


def _claim_only_artifact(summary: Mapping[str, Any], section: str, name: str) -> dict[str, Any]:
    claim = _mapping(summary.get(section), section)
    path = _absolute_path(claim.get("path"), f"{section}.path")
    claim_bytes = _strict_int(claim.get("bytes"), f"{section}.bytes", 1)
    claim_sha = _sha256(claim.get("sha256"), f"{section}.sha256")
    result = _lstat_identity(
        path,
        claim_bytes=claim_bytes,
        claim_sha256=claim_sha,
        content_opened=False,
        hash_verification="not_read_by_scope",
    )
    result["identity_role"] = name
    return result


def _claim_only_nested(summary: Mapping[str, Any], parent: str, child: str, name: str) -> dict[str, Any]:
    outer = _mapping(summary.get(parent), parent)
    claim = _mapping(outer.get(child), f"{parent}.{child}")
    path = _absolute_path(claim.get("path"), f"{parent}.{child}.path")
    claim_bytes = _strict_int(claim.get("bytes"), f"{parent}.{child}.bytes", 1)
    claim_sha = _sha256(claim.get("sha256"), f"{parent}.{child}.sha256")
    result = _lstat_identity(
        path,
        claim_bytes=claim_bytes,
        claim_sha256=claim_sha,
        content_opened=False,
        hash_verification="not_read_by_scope",
    )
    result["identity_role"] = name
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ClosureError(message)


def _validate_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    _require(
        summary.get("schema") == SUMMARY_SCHEMA,
        "summary schema drift",
    )
    _require(
        summary.get("report_id")
        == "F3-GRAPH-RAW-HIDDEN16-SEED43-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28",
        "summary report_id drift",
    )
    _require(summary.get("status") == "completed_diagnostic", "summary is not completed diagnostic")
    _require(summary.get("diagnostic_only") is True, "summary diagnostic_only must be true")
    _require(summary.get("formal_eligible") is False, "summary formal_eligible must be false")
    _require(summary.get("qualification_credit") == 0, "summary qualification_credit must be zero")
    _require(summary.get("future_state_inputs") is False, "summary future_state_inputs must be false")

    protocol = _mapping(summary.get("protocol"), "protocol")
    for key, expected in {
        "model_kind": "graph_raw",
        "seed": SEED,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "maximum_steps": TRANSITIONS,
        "diagnostic": True,
        "autonomous": True,
        "future_state_inputs": False,
    }.items():
        _require(protocol.get(key) == expected, f"protocol.{key} drift")

    training = _mapping(summary.get("training"), "training")
    for key, expected in {
        "schema": "core.training.v1",
        "status": "completed",
        "evidence_status": "complete",
        "completed_updates": UPDATES,
        "model_kind": "graph_raw",
        "seed": SEED,
        "hidden": HIDDEN,
        "checkpoint_verified": True,
    }.items():
        _require(training.get(key) == expected, f"training.{key} drift")

    evaluation = _mapping(summary.get("evaluation"), "evaluation")
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
        _require(evaluation.get(key) == expected, f"evaluation.{key} drift")
    _require(evaluation.get("failure_category") is None, "evaluation.failure_category is not null")
    _require(evaluation.get("first_failure_frame") is None, "evaluation.first_failure_frame is not null")

    coverage = _mapping(evaluation.get("raw_error_coverage"), "evaluation.raw_error_coverage")
    _require(coverage.get("numerator_transitions") == TRANSITIONS, "raw coverage numerator drift")
    _require(coverage.get("denominator_transitions") == TRANSITIONS, "raw coverage denominator drift")
    _require(coverage.get("fraction") == 1.0, "raw coverage fraction drift")

    validator = _mapping(evaluation.get("hdf5_validation"), "evaluation.hdf5_validation")
    for key, expected in {
        "schema": "core.f3.full_rollout_receipt_hdf5_validation.v1",
        "passed": True,
        "complete": True,
        "production_artifacts_touched": False,
        "qualification_credit": 0,
        "synthetic_only": False,
        "trajectory_frames": FRAMES,
        "trajectory_transitions": TRANSITIONS,
        "executed_frame_count": FRAMES,
        "tail_frame_count": 0,
    }.items():
        _require(validator.get(key) == expected, f"evaluation.hdf5_validation.{key} drift")

    selection = _mapping(summary.get("selection"), "selection")
    _require(selection.get("complete") is True, "selection.complete must be true")
    _require(selection.get("finite_prefix_frames") == TRANSITIONS, "selection finite prefix drift")
    _require(selection.get("raw_error_coverage") == 1.0, "selection raw coverage drift")

    trajectory = _mapping(summary.get("trajectory"), "trajectory")
    shapes = _mapping(trajectory.get("shapes"), "trajectory.shapes")
    _require(shapes.get("position", [None])[0] == FRAMES, "trajectory position frame marker drift")
    _require(shapes.get("velocity", [None])[0] == FRAMES, "trajectory velocity frame marker drift")
    _require(shapes.get("valid", [None])[0] == FRAMES, "trajectory valid frame marker drift")
    _require(shapes.get("time", [None])[0] == FRAMES, "trajectory time frame marker drift")

    qualification = _mapping(summary.get("qualification"), "qualification")
    for key in ("formal_training", "formal_eligible", "T1_numerical", "T2_macro", "T2_path"):
        _require(qualification.get(key) is False, f"qualification.{key} must be false")
    _require(qualification.get("qualification_credit") == 0, "qualification credit drift")

    side_effects = _mapping(summary.get("side_effects"), "side_effects")
    for key, expected in {
        "rollout_inputs_read_only": True,
        "source_modified_by_rollout": False,
        "production_hdf5_modified": False,
        "manifest_modified": False,
        "registry_mutation": 0,
        "completion_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "formal_training_counted": False,
        "diagnostic_counted_as_T1_or_T2": False,
        "future_state_inputs": False,
    }.items():
        _require(side_effects.get(key) == expected, f"side_effects.{key} drift")

    bindings = _mapping(summary.get("bindings"), "bindings")
    training_claim = _mapping(bindings.get("training_receipt"), "bindings.training_receipt")
    checkpoint_claim = _mapping(bindings.get("checkpoint"), "bindings.checkpoint")
    _require(checkpoint_claim.get("schema") == "core.checkpoint.v1", "checkpoint schema drift")
    for key, expected in {
        "update": UPDATES,
        "model_kind": "graph_raw",
        "hidden": HIDDEN,
        "seed": SEED,
        "parameter_count": 6086,
    }.items():
        _require(checkpoint_claim.get(key) == expected, f"checkpoint.{key} drift")
    _require(bindings.get("checkpoint_verified") is True, "checkpoint_verified must be true")
    _require(bindings.get("checkpoint_hash_matches_training_receipt") is True, "checkpoint/training hash binding drift")
    _require(bindings.get("evaluation_checkpoint_path_matches_training") is True, "evaluation/checkpoint path binding drift")
    _require(bindings.get("training_protocol_binding_exact") is True, "training protocol binding drift")

    return {
        "case_id": protocol.get("case_id", CASE_ID),
        "model_kind": protocol.get("model_kind"),
        "seed": protocol.get("seed"),
        "hidden": protocol.get("hidden"),
        "updates": protocol.get("updates"),
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "parameter_count": checkpoint_claim.get("parameter_count"),
        "validator": {
            "passed": validator.get("passed"),
            "complete": validator.get("complete"),
            "trajectory_frames": validator.get("trajectory_frames"),
            "trajectory_transitions": validator.get("trajectory_transitions"),
            "tail_frame_count": validator.get("tail_frame_count"),
        },
    }


def _build_default_report(
    summary_path: Path = DEFAULT_SUMMARY,
    *,
    observed_at_utc: str = "2026-09-28T00:00:00Z",
) -> dict[str, Any]:
    """Build a bounded receipt; all failures remain diagnostic and fail-closed."""

    summary_path = Path(summary_path)
    base: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc,
        "seed": SEED,
        "model_kind": "graph_raw",
        "hidden": HIDDEN,
        "updates": UPDATES,
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification_credit": 0,
        "launch": {
            "attempted": False,
            "started": False,
            "command": None,
            "output_namespace": None,
            "reason": "existing seed43 full835 completed diagnostic summary was bindable; no duplicate evaluate launched",
        },
        "scope": {
            "existing_live_job_stop_count": 0,
            "existing_live_job_restart_count": 0,
            "new_evaluation_started": False,
            "progress_content_opened": False,
            "trajectory_content_opened": False,
            "hdf5_content_opened": False,
            "manifest_content_opened": False,
            "checkpoint_content_opened": False,
            "solver_started": False,
            "worker_started": False,
            "queue_submissions": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
        },
    }
    try:
        summary, summary_identity = _read_summary(summary_path)
        markers = _validate_summary(summary)
        bindings = _mapping(summary.get("bindings"), "bindings")
        evaluation = _mapping(summary.get("evaluation"), "evaluation")
        training_receipt = _mapping(bindings.get("training_receipt"), "bindings.training_receipt")
        evaluation_receipt = _mapping(evaluation.get("receipt"), "evaluation.receipt")

        training_path = _absolute_path(training_receipt.get("path"), "training_receipt.path", ".json")
        evaluation_path = _absolute_path(evaluation_receipt.get("path"), "evaluation_receipt.path", ".json")
        training_binding = _hash_allowed_json(training_path, training_receipt, "training_receipt")
        evaluation_binding = _hash_allowed_json(evaluation_path, evaluation_receipt, "evaluation_receipt")
        checkpoint_binding = _claim_only_nested(summary, "bindings", "checkpoint", "checkpoint")
        trajectory_binding = _claim_only_artifact(summary, "trajectory", "trajectory")
        validator_binding = _claim_only_nested(summary, "evaluation", "hdf5_validation", "hdf5_validation")

        reasons: list[str] = []
        for label, binding in (
            ("training_receipt", training_binding),
            ("evaluation_receipt", evaluation_binding),
            ("checkpoint", checkpoint_binding),
            ("trajectory", trajectory_binding),
            ("hdf5_validation", validator_binding),
        ):
            if not binding.get("exists") or not binding.get("regular_file") or binding.get("symlink"):
                reasons.append(f"{label} is not a regular non-symlink file")
            if not binding.get("bytes_match"):
                reasons.append(f"{label} bytes drift")
        for label, binding in (("training_receipt", training_binding), ("evaluation_receipt", evaluation_binding)):
            if binding.get("hash_verification") != "verified":
                reasons.append(f"{label} SHA-256 drift or verification failure")
        status = "bound_existing_terminal_summary" if not reasons else "blocked_fail_closed"
        base.update(
            {
                "status": status,
                "source_summary": summary_identity,
                "terminal_markers": markers,
                "identity_bindings": {
                    "training_receipt": training_binding,
                    "evaluation_receipt": evaluation_binding,
                    "checkpoint": checkpoint_binding,
                    "trajectory": trajectory_binding,
                    "hdf5_validation": validator_binding,
                },
                "blocked_reasons": reasons,
                "source_summary_status": summary.get("status"),
            }
        )
    except (ClosureError, OSError) as error:
        base.update(
            {
                "status": "blocked_fail_closed",
                "source_summary": {"path": str(summary_path), "content_opened": False},
                "terminal_markers": None,
                "identity_bindings": {},
                "blocked_reasons": [str(error)],
                "source_summary_status": None,
            }
        )
    return base


def _read_bounded_json(path: Path, name: str, max_bytes: int) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute_path(path, name, ".json")
    if path.is_symlink() or not path.is_file():
        raise ReceiptError(f"{name} is not a regular non-symlink file")
    size = path.stat().st_size
    if size > max_bytes:
        raise ReceiptError(f"{name} exceeds bounded reader limit: {size}>{max_bytes}")
    try:
        raw = path.read_bytes()
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ClosureError) as error:
        raise ReceiptError(f"{name} is not valid bounded JSON: {error}") from error
    if not isinstance(payload, Mapping):
        raise ReceiptError(f"{name} must be a JSON object")
    _check_finite(payload, name)
    return dict(payload), {
        "path": str(path),
        "exists": True,
        "opened": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload.get("schema"),
    }


def _path_equal(left: Any, right: Path) -> bool:
    try:
        return Path(str(left)).resolve() == right.resolve()
    except (OSError, RuntimeError, TypeError):
        return False


def _explicit_stat(path: Path, name: str, expected_bytes: int | None = None) -> dict[str, Any]:
    path = _absolute_path(path, name)
    try:
        info = path.lstat()
    except OSError as error:
        raise ReceiptError(f"{name}.stat failed: {type(error).__name__}") from error
    if stat.S_ISLNK(info.st_mode):
        raise ReceiptError(f"{name}.stat symlink is not allowed")
    if not stat.S_ISREG(info.st_mode):
        raise ReceiptError(f"{name}.stat is not a regular file")
    actual_bytes = int(info.st_size)
    if expected_bytes is not None and actual_bytes != expected_bytes:
        raise ReceiptError(f"{name}.stat.bytes drift: {actual_bytes}!={expected_bytes}")
    return {
        "path": str(path),
        "exists": True,
        "opened": False,
        "bytes": actual_bytes,
        "mtime_ns": int(info.st_mtime_ns),
        "symlink": False,
    }


def _require_receipt(condition: bool, message: str) -> None:
    if not condition:
        raise ReceiptError(message)


def _explicit_report(
    *,
    training_path: Path,
    evaluation_path: Path,
    validator_path: Path,
    checkpoint_path: Path,
    trajectory_path: Path,
    terminal_summary_path: Path,
    observed_at_utc: str,
) -> dict[str, Any]:
    """Bind explicit bounded receipts used by the seed43 runner/tests."""

    training, training_source = _read_bounded_json(
        training_path, "training_receipt", 1 * 1024 * 1024
    )
    evaluation, evaluation_source = _read_bounded_json(
        evaluation_path, "evaluation", 16 * 1024 * 1024
    )
    validator, validator_source = _read_bounded_json(
        validator_path, "hdf5_validation_receipt", 1 * 1024 * 1024
    )
    terminal_summary, terminal_source = _read_bounded_json(
        terminal_summary_path, "terminal_summary", SUMMARY_MAX_BYTES
    )

    training_checkpoint = _mapping(training.get("checkpoint"), "training.checkpoint")
    checkpoint_bytes = _strict_int(
        training_checkpoint.get("bytes"), "training.checkpoint.bytes", 1
    )
    trajectory_claim = _mapping(terminal_summary.get("trajectory"), "terminal_summary.trajectory")
    trajectory_bytes = _strict_int(
        trajectory_claim.get("bytes"), "terminal_summary.trajectory.bytes", 1
    )
    checkpoint_stat = _explicit_stat(checkpoint_path, "checkpoint", checkpoint_bytes)
    trajectory_stat = _explicit_stat(trajectory_path, "trajectory", trajectory_bytes)

    _require_receipt(training.get("schema") == "core.training.v1", "training.schema drift")
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("seed", SEED),
        ("completed_updates", UPDATES),
        ("evidence_status", "complete"),
    ):
        _require_receipt(training.get(key) == expected, f"training.{key} drift")
    _require_receipt(
        training.get("checkpoint_verified") is True,
        "training.checkpoint_verified must be true",
    )
    training_config = _mapping(training.get("config"), "training.config")
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("hidden", HIDDEN),
        ("seed", SEED),
        ("updates", UPDATES),
    ):
        _require_receipt(training_config.get(key) == expected, f"training.config.{key} drift")
    _require_receipt(
        _path_equal(training_checkpoint.get("path"), checkpoint_path),
        "training.checkpoint.path drift",
    )
    _require_receipt(training_checkpoint.get("update") == UPDATES, "training.checkpoint.update drift")
    _sha256(training_checkpoint.get("sha256"), "training.checkpoint.sha256")

    _require_receipt(evaluation.get("schema") == "core.evaluation.v1", "evaluation.schema drift")
    _require_receipt(evaluation.get("diagnostic") is True, "evaluation.diagnostic must be true")
    _require_receipt(
        evaluation.get("formal_eligible") is False,
        "evaluation.formal_eligible must be false",
    )
    _require_receipt(
        evaluation.get("maximum_steps") == TRANSITIONS,
        "evaluation.maximum_steps drift",
    )
    _require_receipt(
        evaluation.get("checkpoint") == str(checkpoint_path),
        "evaluation.checkpoint path drift",
    )
    _require_receipt(
        evaluation.get("selected_case_ids") == [CASE_ID],
        "evaluation.selected_case_ids drift",
    )
    _require_receipt(
        _mapping(evaluation.get("expected_frames"), "evaluation.expected_frames").get(CASE_ID)
        == TRANSITIONS,
        "evaluation.expected_frames drift",
    )
    _require_receipt(
        _mapping(evaluation.get("fixed_denominator"), "evaluation.fixed_denominator")
        .get(CASE_ID, {})
        .get("expected_frames")
        == TRANSITIONS,
        "evaluation.fixed_denominator drift",
    )
    cases = _mapping(evaluation.get("cases"), "evaluation.cases")
    case = _mapping(cases.get(CASE_ID), "evaluation.case")
    for key, expected in (
        ("case_id", CASE_ID),
        ("executed", True),
        ("execution_complete", True),
        ("expected_frames", TRANSITIONS),
        ("frames_expected", TRANSITIONS),
        ("frames_executed", TRANSITIONS),
        ("frames_predicted", TRANSITIONS),
        ("finite_rollout_complete", True),
        ("future_state_inputs", False),
    ):
        _require_receipt(case.get(key) == expected, f"evaluation.case.{key} drift")
    _require_receipt(
        case.get("failure_category") is None,
        "evaluation.case.failure_category drift",
    )
    _require_receipt(
        case.get("first_failure_frame") is None,
        "evaluation.case.first_failure_frame drift",
    )
    _require_receipt(
        _path_equal(case.get("trajectory_output"), trajectory_path),
        "trajectory_output drift",
    )
    score = _mapping(case.get("score"), "evaluation.case.score")
    for key, expected in (
        ("executed", True),
        ("complete", True),
        ("expected_frames", TRANSITIONS),
        ("finite_prefix_frames", TRANSITIONS),
        ("raw_error_coverage", 1.0),
    ):
        _require_receipt(score.get(key) == expected, f"evaluation.case.score.{key} drift")
    execution_summary = _mapping(evaluation.get("execution_summary"), "evaluation.execution_summary")
    for key, expected in (
        ("registered_case_count", 1),
        ("executed_case_count", 1),
        ("execution_complete_case_count", 1),
        ("finite_rollout_complete_case_count", 1),
        ("missing_execution_case_count", 0),
    ):
        _require_receipt(
            execution_summary.get(key) == expected,
            f"evaluation.execution_summary.{key} drift",
        )
    _require_receipt(
        _mapping(evaluation.get("finite_summary"), "evaluation.finite_summary")
        .get("all_registered_rollouts_finite")
        is True,
        "evaluation.finite_summary drift",
    )

    _require_receipt(
        validator.get("schema") == "core.f3.full_rollout_receipt_hdf5_validation.v1",
        "validator.schema drift",
    )
    for key, expected in (
        ("case_id", CASE_ID),
        ("complete", True),
        ("passed", True),
        ("expected_transitions", TRANSITIONS),
        ("frames_executed", TRANSITIONS),
        ("production_artifacts_touched", False),
        ("qualification_credit", 0),
        ("synthetic_only", False),
    ):
        _require_receipt(validator.get(key) == expected, f"validator.{key} drift")
    _require_receipt(
        _path_equal(validator.get("evaluation_json"), evaluation_path),
        "validator.evaluation_json drift",
    )
    _require_receipt(
        _path_equal(validator.get("trajectory_hdf5"), trajectory_path),
        "validator.trajectory_hdf5 drift",
    )
    checks = _mapping(validator.get("checks"), "validator.checks")
    for key, expected in (
        ("case_binding", True),
        ("completion_semantics", True),
        ("executed_frame_count", FRAMES),
        ("future_state_inputs", True),
        ("tail_frame_count", 0),
        ("trajectory_frames", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
    ):
        _require_receipt(checks.get(key) == expected, f"validator.checks.{key} drift")

    _require_receipt(terminal_summary.get("schema") == SUMMARY_SCHEMA, "terminal_summary.schema drift")
    _require_receipt(
        terminal_summary.get("status") == "completed_diagnostic",
        "terminal_summary.status drift",
    )
    _require_receipt(
        terminal_summary.get("diagnostic_only") is True,
        "terminal_summary.diagnostic_only must be true",
    )
    _require_receipt(
        terminal_summary.get("formal_eligible") is False,
        "terminal_summary.formal_eligible must be false",
    )
    _require_receipt(
        terminal_summary.get("future_state_inputs") is False,
        "terminal_summary.future_state_inputs must be false",
    )
    _require_receipt(
        terminal_summary.get("qualification_credit", 0) == 0,
        "terminal_summary.qualification_credit drift",
    )
    protocol = _mapping(terminal_summary.get("protocol"), "terminal_summary.protocol")
    for key, expected in (
        ("model_kind", MODEL_KIND),
        ("seed", SEED),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("maximum_steps", TRANSITIONS),
        ("diagnostic", True),
        ("future_state_inputs", False),
    ):
        _require_receipt(protocol.get(key) == expected, f"terminal_summary.protocol.{key} drift")

    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc,
        "status": "completed_diagnostic_terminal_receipt_bound",
        "model_kind": MODEL_KIND,
        "seed": SEED,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "terminal_markers": {"transitions": TRANSITIONS, "frames": FRAMES},
        "identities": {
            "training": training_source,
            "evaluation": evaluation_source,
            "validator": validator_source,
            "checkpoint": {
                "path": str(checkpoint_path),
                "opened": False,
                "sha256_recomputed": False,
                "stat": checkpoint_stat,
            },
            "trajectory": {
                "path": str(trajectory_path),
                "opened": False,
                "sha256_recomputed": False,
                "stat": trajectory_stat,
            },
            "terminal_summary": terminal_source,
        },
        "new_diagnostic_evaluate_attempted": False,
        "launch": {
            "attempted": False,
            "started": False,
            "command": None,
            "output_namespace": None,
            "reason": "existing complete seed43 terminal summary bound; no duplicate evaluate",
        },
        "qualification": {
            "diagnostic_only": True,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification_credit": 0,
        },
        "side_effects": {
            "existing_live_job_stop_count": 0,
            "existing_live_job_restart_count": 0,
            "progress_content_opened": False,
            "trajectory_content_opened": False,
            "hdf5_content_opened": False,
            "manifest_content_opened": False,
            "checkpoint_content_opened": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "solver_started": False,
            "worker_started": False,
            "queue_submissions": 0,
        },
    }


def build_report(
    summary_path: Path = DEFAULT_SUMMARY,
    *,
    observed_at_utc: str = "2026-09-28T00:00:00Z",
    training_path: Path | str | None = None,
    evaluation_path: Path | str | None = None,
    validator_path: Path | str | None = None,
    checkpoint_path: Path | str | None = None,
    trajectory_path: Path | str | None = None,
    terminal_summary_path: Path | str | None = None,
) -> dict[str, Any]:
    """Public seed43-specific report builder."""

    explicit = {
        "training_path": training_path,
        "evaluation_path": evaluation_path,
        "validator_path": validator_path,
        "checkpoint_path": checkpoint_path,
        "trajectory_path": trajectory_path,
        "terminal_summary_path": terminal_summary_path,
    }
    if any(value is not None for value in explicit.values()):
        if any(value is None for value in explicit.values()):
            raise ReceiptError("explicit seed43 build_report requires all six artifact paths")
        return _explicit_report(
            training_path=Path(training_path),
            evaluation_path=Path(evaluation_path),
            validator_path=Path(validator_path),
            checkpoint_path=Path(checkpoint_path),
            trajectory_path=Path(trajectory_path),
            terminal_summary_path=Path(terminal_summary_path),
            observed_at_utc=observed_at_utc,
        )
    return _build_default_report(summary_path, observed_at_utc=observed_at_utc)


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    status = report.get("status")
    if status not in {
        "completed_diagnostic_terminal_receipt_bound",
        "bound_existing_terminal_summary",
    }:
        errors.append("status is not a bound diagnostic terminal status")
    expected_markers: Mapping[str, Any] = {
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }
    if status == "bound_existing_terminal_summary":
        expected_markers = {
            "case_id": CASE_ID,
            "model_kind": MODEL_KIND,
            "seed": SEED,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "parameter_count": 6086,
            "validator": {
                "passed": True,
                "complete": True,
                "trajectory_frames": FRAMES,
                "trajectory_transitions": TRANSITIONS,
                "tail_frame_count": 0,
            },
        }
    if report.get("terminal_markers") != expected_markers:
        errors.append("terminal markers drift")
    if report.get("new_diagnostic_evaluate_attempted", False) is not False:
        errors.append("new diagnostic evaluate was unexpectedly attempted")
    qualification = report.get("qualification")
    if isinstance(qualification, Mapping):
        if qualification.get("formal_eligible") is not False:
            errors.append("qualification.formal_eligible drift")
        if qualification.get("qualification_credit") != 0:
            errors.append("qualification.credit drift")
    side_effects = report.get("side_effects", report.get("scope", {}))
    for key in ("registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation"):
        if side_effects.get(key) != 0:
            errors.append(f"{key} is non-zero")
    return errors


def _render_zh(report: Mapping[str, Any]) -> str:
    status = report.get("status")
    markers = report.get("terminal_markers") or {}
    identities = report.get("identity_bindings") or {}
    reasons = report.get("blocked_reasons") or []
    lines = [
        "# F3 graph_raw hidden16 seed43 terminal completion receipt",
        "",
        f"状态：`{status}`。本 receipt 只绑定既有 seed43 diagnostic full835 终态，不启动新的 evaluate。",
        "",
        "## 终态 markers",
        "",
        f"- 模型：`{report.get('model_kind')}`，hidden=`{report.get('hidden')}`，seed=`{report.get('seed')}`，updates=`{report.get('updates')}`。",
        f"- 终态：`{markers.get('transitions', 'N/A')}/835 transitions`、`{markers.get('frames', 'N/A')}/836 frames`，validator=`{(markers.get('validator') or {}).get('passed', 'N/A')}`。",
        "- 结论仍为 diagnostic-only：formal/T1/T2/credit 不产生资格或积分。",
        "",
        "## identity 绑定",
        "",
    ]
    for name in ("training_receipt", "evaluation_receipt", "checkpoint", "trajectory"):
        value = identities.get(name) or {}
        lines.append(
            f"- `{name}`：`{value.get('path', 'N/A')}`，claimed bytes=`{value.get('claimed_bytes', 'N/A')}`，"
            f"stat bytes=`{value.get('stat_bytes', 'N/A')}`，content_opened=`{value.get('content_opened', 'N/A')}`，"
            f"hash=`{value.get('hash_verification', 'N/A')}`。"
        )
    lines.extend(
        [
            "",
            "## 安全边界",
            "",
            "- 本 runner 未停止或重启 existing live job；未启动新的 evaluate；输出命名空间为空。",
            "- progress、trajectory/HDF5、manifest、checkpoint 均未打开内容，仅对后者做 `lstat`/bytes 检查；training/evaluation JSON 仅用于 receipt SHA-256 核对。",
            "- registry、ledger、denominator、gate mutation 均为 `0`；formal、T1、T2、qualification、credit 均不改变。",
        ]
    )
    if reasons:
        lines.extend(["", "## fail-closed 原因", ""])
        lines.extend(f"- {reason}" for reason in reasons)
    lines.append("")
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], output: Path = DEFAULT_REPORT, zh_output: Path = DEFAULT_ZH_REPORT) -> None:
    output = Path(output)
    zh_output = Path(zh_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    zh_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    zh_output.write_text(_render_zh(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    parser.add_argument("--observed-at-utc", default="2026-09-28T00:00:00Z")
    args = parser.parse_args(argv)
    report = build_report(args.summary, observed_at_utc=args.observed_at_utc)
    write_outputs(report, args.output, args.zh_output)
    print(json.dumps({"status": report["status"], "output": str(args.output), "blocked_reasons": report["blocked_reasons"]}, ensure_ascii=False))
    return 0 if report["status"] == "bound_existing_terminal_summary" else 2


if __name__ == "__main__":
    raise SystemExit(main())
