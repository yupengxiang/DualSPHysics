#!/usr/bin/env python3
"""Close the F3 graph_raw/hidden16 seed29 diagnostic terminal receipt.

This runner is deliberately seed29-specific and does not import or mutate any
shared F3 bridge.  It first inspects existing full835 evaluation candidates,
reading only evaluation JSON plus the bounded seed29 training receipt.  It
never opens progress, trajectory/HDF5, manifest, or checkpoint content; those
artifacts are represented by stat-only identity records.  If explicitly
requested, it can launch one diagnostic full-horizon evaluation into a fresh
output namespace and then bind the completed evaluation markers.

Every result is diagnostic-only.  The runner never changes PLAN, registry,
ledger, denominator, gate, completion, or formal/T1/T2 credit state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Mapping, Sequence

from scripts import f3_graph_terminal_validator_security_hardening_v1 as hardening


LAB_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = Path("/tmp")
REPORT_SCHEMA = (
    "core.f3.graph_raw.hidden16.seed29.terminal_completion_receipt.v1"
)
REPORT_ID = "f3-graph-raw-hidden16-seed29-terminal-completion-receipt-v1"
MODEL_KIND = "graph_raw"
SEED = 29
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
MAX_BOUNDED_JSON_BYTES = 1 * 1024 * 1024
MAX_EVALUATION_JSON_BYTES = 32 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_GPU_INDEX = 7
MIN_FREE_VRAM_MIB = 4 * 1024

P1_SECURITY_BLOCKERS = (
    "real sealed Popen/wait witness is not independently admitted for seed29",
    "complete source/manifest/checkpoint/environment/executable identity is not sealed",
    "HDF5 external/soft/VDS rejection is not independently bound to this runner",
    "one-time output namespace reservation/consumption is not independently sealed",
)

DEFAULT_TRAINING_RECEIPT = (
    TMP_ROOT / "f3-graph-raw500-hidden16-seed29-20260928-training.json"
)
DEFAULT_NAMESPACE = (
    TMP_ROOT
    / "f3-graph-raw500-hidden16-seed29-full835-20260928-terminal-closure-v1"
)
DEFAULT_EVALUATION = Path(f"{DEFAULT_NAMESPACE}-evaluation.json")
DEFAULT_TRAJECTORY = Path(f"{DEFAULT_NAMESPACE}-trajectory.h5")
DEFAULT_PROGRESS = Path(f"{DEFAULT_NAMESPACE}-evaluation-progress.json")
DEFAULT_LOG = Path(f"{DEFAULT_NAMESPACE}-evaluation.log")
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports/F3-GRAPH-RAW-HIDDEN16-SEED29-TERMINAL-COMPLETION-RECEIPT-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = (
    LAB_ROOT
    / "reports/F3-GRAPH-RAW-HIDDEN16-SEED29-TERMINAL-COMPLETION-RECEIPT-V1-2026-09-28.zh-CN.md"
)


class RunnerError(ValueError):
    """Malformed, unsafe, incomplete, or conflicting evidence."""


def _fail(message: str) -> None:
    raise RunnerError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


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
    try:
        raw = os.fspath(value)
    except TypeError:
        _fail(f"{name} must be a path string")
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path string")
    path = Path(raw)
    if (
        not path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
        or os.path.normpath(raw) != raw
    ):
        _fail(f"{name} must be absolute and lexical-alias free")
    if suffix is not None and path.suffix.lower() != suffix.lower():
        _fail(f"{name} must end with {suffix}")
    return path


def _path_text(path: Path) -> str:
    return str(path)


def _source_ref(path: Path, *, opened: bool, raw: bytes | None = None) -> dict[str, Any]:
    try:
        metadata = os.lstat(path)
    except OSError:
        metadata = None
    exists = metadata is not None and os.path.isfile(path) and not path.is_symlink()
    return {
        "path": _path_text(path),
        "exists": exists,
        "opened": opened,
        "bytes": len(raw) if raw is not None else (metadata.st_size if exists else None),
        "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        "stable_fd": raw is not None,
        "path_reopened": False,
        "symlink": bool(metadata is not None and path.is_symlink()),
        "hardlinks": int(metadata.st_nlink) if metadata is not None else None,
    }


def _read_json(path: Path, *, max_bytes: int, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute_path(path, name, ".json")
    try:
        raw = hardening.secure_read_regular_file(
            path,
            root_value=path.parent,
            max_bytes=max_bytes,
        )
    except hardening.SecurityBoundaryError as error:
        _fail(str(error))
    if path.suffix.lower() != ".json":
        _fail(f"{name} must use a JSON suffix: {path}")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except RunnerError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read {name}: {error}")
    payload = dict(_mapping(payload, name))
    _check_finite(payload, name)
    source = _source_ref(path, opened=True, raw=raw)
    source["schema"] = payload.get("schema")
    return payload, source


def _stat_only(path: Path, *, expected_bytes: int | None = None, name: str) -> dict[str, Any]:
    path = _absolute_path(path, name)
    try:
        metadata = os.lstat(path)
    except OSError as error:
        _fail(f"{name} is missing: {path}: {error}")
    if path.is_symlink() or not os.path.isfile(path):
        _fail(f"{name} must be a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        _fail(f"{name} must have exactly one hard link: {path}")
    size = metadata.st_size
    if expected_bytes is not None and size != expected_bytes:
        _fail(f"{name} byte count drift: observed={size} expected={expected_bytes}")
    return {
        "path": str(path),
        "exists": True,
        "opened": False,
        "stat_only": True,
        "bytes": size,
        "sha256": None,
        "stable_fd": False,
        "path_reopened": False,
        "hardlinks": int(metadata.st_nlink),
    }


def _stream_sha256(path: Path, *, name: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink():
        _fail(f"{name} symlink is not allowed: {path}")
    if not path.is_file():
        _fail(f"{name} is missing: {path}")
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError as error:
        _fail(f"cannot hash {name}: {error}")
    return {
        "path": str(path),
        "exists": True,
        "opened": True,
        "stream_hashed": True,
        "bytes": size,
        "sha256": digest.hexdigest(),
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
        "formal_training_runs_counted": 0,
        "T1_numerical": False,
        "T2_macro": False,
    }


def _security_boundary() -> dict[str, Any]:
    """Describe the non-authorizing P1 boundary for this legacy runner.

    The seed29 v1 contract has no scheduler-issued admission capability.  It
    therefore remains useful as a diagnostic receipt binder, but it must never
    turn its legacy launch helper into execution authority.  The common
    hardening module is available for future integration; this runner does not
    promote a JSON declaration, GPU snapshot, or caller object into a real
    process witness.
    """

    return {
        "status": "blocked_fail_closed",
        "execution_authorized": False,
        "launch_allowed": False,
        "popen_attempted": False,
        "wait_attempted": False,
        "controls": {
            "bounded_json_stable_fd": True,
            "symlink_hardlink_toctou_for_bounded_json": True,
            "stat_only_artifact_stable_fd": False,
            "hdf5_external_soft_vds_rejected": False,
            "source_manifest_checkpoint_environment_executable_identity": False,
            "sealed_real_popen_wait": False,
            "one_time_namespace": False,
            "formal_credit_isolation": True,
        },
        "blockers": list(P1_SECURITY_BLOCKERS),
        "hardening_boundary": hardening.SCHEMA,
    }


def _training_receipt(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload, source = _read_json(
        path, max_bytes=MAX_BOUNDED_JSON_BYTES, name="seed29 training receipt"
    )
    reasons: list[str] = []
    if payload.get("schema") != "core.training.v1":
        reasons.append(f"training schema drift: {payload.get('schema')!r}")
    if payload.get("evidence_status") != "complete":
        reasons.append("training evidence_status is not complete")
    if payload.get("completed_updates") != UPDATES:
        reasons.append(f"completed_updates drift: {payload.get('completed_updates')!r}")
    if payload.get("model_kind") != MODEL_KIND:
        reasons.append(f"model_kind drift: {payload.get('model_kind')!r}")
    if payload.get("seed") != SEED:
        reasons.append(f"seed drift: {payload.get('seed')!r}")
    config = payload.get("config")
    if not isinstance(config, Mapping):
        reasons.append("training config is missing")
        config = {}
    if config.get("hidden") != HIDDEN:
        reasons.append(f"config.hidden drift: {config.get('hidden')!r}")
    if config.get("model_kind") != MODEL_KIND:
        reasons.append(f"config.model_kind drift: {config.get('model_kind')!r}")
    if config.get("seed") != SEED or config.get("paired_seed") != SEED:
        reasons.append("config seed binding drift")
    if config.get("updates") != UPDATES:
        reasons.append("config.updates drift")
    if payload.get("checkpoint_verified") is not True:
        reasons.append("checkpoint_verified must be true")
    checkpoint = payload.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        reasons.append("checkpoint binding is missing")
        checkpoint = {}
    try:
        checkpoint_path = _absolute_path(checkpoint.get("path"), "training.checkpoint.path", ".pt")
        checkpoint_sha = _sha256(checkpoint.get("sha256"), "training.checkpoint.sha256")
        checkpoint_bytes = _strict_int(checkpoint.get("bytes"), "training.checkpoint.bytes", 1)
    except RunnerError as error:
        reasons.append(str(error))
        checkpoint_path = Path("/nonexistent/seed29-checkpoint.pt")
        checkpoint_sha = None
        checkpoint_bytes = None
    checkpoint_stat: dict[str, Any] | None = None
    if not reasons or checkpoint_path.exists():
        try:
            checkpoint_stat = _stat_only(
                checkpoint_path,
                expected_bytes=checkpoint_bytes,
                name="seed29 checkpoint (stat-only)",
            )
        except RunnerError as error:
            reasons.append(str(error))
    normalized = {
        "schema": payload.get("schema"),
        "model_kind": payload.get("model_kind"),
        "seed": payload.get("seed"),
        "hidden": config.get("hidden"),
        "updates": payload.get("completed_updates"),
        "checkpoint": {
            "path": str(checkpoint_path),
            "sha256_claimed": checkpoint_sha,
            "bytes_claimed": checkpoint_bytes,
            "stat": checkpoint_stat,
            "content_opened": False,
        },
        "config": {
            "model_kind": config.get("model_kind"),
            "hidden": config.get("hidden"),
            "seed": config.get("seed"),
            "paired_seed": config.get("paired_seed"),
            "updates": config.get("updates"),
            "max_neighbors": config.get("max_neighbors"),
            "target_normalization": config.get("target_normalization"),
        },
    }
    return normalized, source, {"valid": not reasons, "reasons": reasons}


def _candidate_inventory() -> dict[str, Any]:
    """List related paths by stat only; never read progress/trajectory/etc."""

    prefix = "f3-graph-raw500-hidden16-seed29-full835-20260928"
    entries: list[dict[str, Any]] = []
    try:
        paths = sorted(TMP_ROOT.glob(prefix + "*"), key=lambda item: item.name)
    except OSError as error:
        return {"scan_error": str(error), "files": []}
    for path in paths[:128]:
        try:
            metadata = os.lstat(path)
        except OSError:
            continue
        if path.is_symlink() or not os.path.isfile(path) or metadata.st_nlink != 1:
            continue
        entries.append(
            {
                "name": path.name,
                "bytes": metadata.st_size,
                "mtime_ns": metadata.st_mtime_ns,
                "opened": False,
                "content_class": (
                    "evaluation_json_candidate"
                    if path.name.endswith("-evaluation.json")
                    else "non_terminal_stat_only"
                ),
            }
        )
    return {
        "prefix": prefix,
        "files": entries,
        "evaluation_candidates": [
            item["name"]
            for item in entries
            if item["content_class"] == "evaluation_json_candidate"
        ],
        "progress_or_trajectory_content_opened": False,
    }


def _evaluation_candidates(
    explicit: Path | None,
    inventory: Mapping[str, Any],
) -> list[Path]:
    paths: list[Path] = []
    if explicit is not None:
        paths.append(_absolute_path(explicit, "explicit seed29 evaluation"))
    for name in inventory.get("evaluation_candidates", []):
        paths.append(_absolute_path(TMP_ROOT / str(name), "seed29 inventory evaluation"))
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            result.append(path)
            seen.add(key)
    return result


def _validate_evaluation(
    path: Path,
    training: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, source = _read_json(
        path, max_bytes=MAX_EVALUATION_JSON_BYTES, name="seed29 evaluation receipt"
    )
    reasons: list[str] = []
    if payload.get("schema") != "core.evaluation.v1":
        reasons.append(f"evaluation schema drift: {payload.get('schema')!r}")
    if payload.get("model_kind") != MODEL_KIND:
        reasons.append(f"evaluation model_kind drift: {payload.get('model_kind')!r}")
    if payload.get("evaluation_mode") != "diagnostic" or payload.get("diagnostic") is not True:
        reasons.append("evaluation is not diagnostic")
    if payload.get("formal_eligible") is not False:
        reasons.append("evaluation formal_eligible must be false")
    if payload.get("future_state_inputs") is not False:
        reasons.append("evaluation future_state_inputs must be false")
    if payload.get("maximum_steps") != TRANSITIONS:
        reasons.append(f"maximum_steps drift: {payload.get('maximum_steps')!r}")
    if payload.get("checkpoint") != training["checkpoint"]["path"]:
        reasons.append("evaluation checkpoint path does not match training checkpoint")
    expected_frames = payload.get("expected_frames")
    if not isinstance(expected_frames, Mapping) or expected_frames.get(CASE_ID) != TRANSITIONS:
        reasons.append("evaluation fixed denominator is not 835")
    selected = payload.get("selected_case_ids")
    if selected != [CASE_ID]:
        reasons.append(f"selected_case_ids drift: {selected!r}")
    cases = payload.get("cases")
    if not isinstance(cases, Mapping) or CASE_ID not in cases:
        reasons.append("evaluation case is missing")
        case: Mapping[str, Any] = {}
    else:
        case = _mapping(cases[CASE_ID], "evaluation case")
    rollout = case.get("rollout")
    if not isinstance(rollout, Mapping):
        reasons.append("evaluation rollout is missing")
        rollout = {}
    for key, expected in (
        ("case_id", CASE_ID),
        ("expected_frames", TRANSITIONS),
        ("frames_expected", TRANSITIONS),
        ("frames_predicted", TRANSITIONS),
        ("frames_executed", TRANSITIONS),
    ):
        if case.get(key) != expected or rollout.get(key) != expected:
            reasons.append(f"evaluation {key} is not {expected!r}")
    for value, name in (
        (case.get("executed"), "case.executed"),
        (case.get("execution_complete"), "case.execution_complete"),
        (case.get("finite_rollout_complete"), "case.finite_rollout_complete"),
        (rollout.get("executed"), "rollout.executed"),
        (rollout.get("execution_complete"), "rollout.execution_complete"),
        (rollout.get("finite_rollout_complete"), "rollout.finite_rollout_complete"),
    ):
        if value is not True:
            reasons.append(f"{name} must be true")
    for value, name in (
        (case.get("failure_category"), "case.failure_category"),
        (case.get("first_failure_frame"), "case.first_failure_frame"),
        (rollout.get("failure_category"), "rollout.failure_category"),
        (rollout.get("first_failure_frame"), "rollout.first_failure_frame"),
    ):
        if value is not None:
            reasons.append(f"{name} must be null for terminal closure")
    for value, name in (
        (case.get("future_state_inputs"), "case.future_state_inputs"),
        (rollout.get("future_state_inputs"), "rollout.future_state_inputs"),
    ):
        if value is not False:
            reasons.append(f"{name} must be false")
    trajectory_path = rollout.get("trajectory_output")
    progress_path = rollout.get("progress_output")
    try:
        trajectory_path = _absolute_path(trajectory_path, "rollout.trajectory_output", ".h5")
        progress_path = _absolute_path(progress_path, "rollout.progress_output", ".json")
    except RunnerError as error:
        reasons.append(str(error))
        trajectory_path = Path("/nonexistent/seed29-trajectory.h5")
        progress_path = Path("/nonexistent/seed29-evaluation-progress.json")
    trajectory_stat: dict[str, Any] | None = None
    progress_stat: dict[str, Any] | None = None
    try:
        trajectory_stat = _stat_only(
            trajectory_path,
            name="seed29 trajectory (stat-only)",
        )
    except RunnerError as error:
        reasons.append(str(error))
    try:
        progress_stat = _stat_only(progress_path, name="seed29 progress (stat-only)")
    except RunnerError as error:
        reasons.append(str(error))
    if reasons:
        _fail("; ".join(reasons))
    terminal = {
        "seed": SEED,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "terminal_markers": {
            "terminal": True,
            "terminal_status": "completed",
            "execution_complete": True,
            "finite_rollout_complete": True,
            "evaluation_status": "completed_diagnostic",
            "progress_is_not_completion": True,
        },
        "training_binding": training,
        "evaluation_binding": {
            "path": str(path),
            "schema": payload["schema"],
            "bytes": source["bytes"],
            "sha256": source["sha256"],
            "content_opened": True,
            "stream_hashed": False,
            "evaluation_mode": payload["evaluation_mode"],
            "diagnostic": True,
            "formal_eligible": False,
            "maximum_steps": TRANSITIONS,
            "frames_executed": TRANSITIONS,
            "trajectory_frames_including_initial": FRAMES,
            "full_registered_denominator_complete": True,
            "future_state_inputs": False,
        },
        "trajectory_binding": {
            "path": str(trajectory_path),
            "bytes": trajectory_stat["bytes"] if trajectory_stat else None,
            "content_opened": False,
            "stat_only": True,
            "sha256": None,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
        },
        "progress_binding": {
            "path": str(progress_path),
            "bytes": progress_stat["bytes"] if progress_stat else None,
            "content_opened": False,
            "stat_only": True,
            "completion_not_inferred": True,
        },
        "diagnostic_only": True,
        "formal_eligible": False,
        "qualification": False,
        "T1_numerical": False,
        "T2_macro": False,
        "qualification_credit": 0,
        "credit": 0,
        "side_effects": _empty_side_effects(),
    }
    return terminal, source


def _base_report(
    *,
    observed_at_utc: str,
    inventory: Mapping[str, Any],
    training_source: Mapping[str, Any],
    training: Mapping[str, Any] | None,
    training_errors: Sequence[str],
    launch: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc,
        "status": "blocked_fail_closed",
        "fail_closed": True,
        "source_bound": False,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "qualification": False,
        "qualification_credit": 0,
        "credit": 0,
        "target_contract": {
            "model_kind": MODEL_KIND,
            "seed": SEED,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "terminal_status": "completed",
            "progress_or_pid_is_not_completion": True,
        },
        "candidate_inventory": dict(inventory),
        "training_source": dict(training_source),
        "training_binding": dict(training) if training is not None else None,
        "seed29_terminal_receipt": None,
        "blocked_reasons": list(training_errors),
        "launch": dict(launch),
        "security_boundary": _security_boundary(),
        "side_effects": _empty_side_effects(),
        "input_boundary": {
            "bounded_training_json_opened": bool(training_source.get("opened")),
            "evaluation_json_opened": False,
            "checkpoint_opened": False,
            "progress_opened": False,
            "trajectory_hdf5_opened": False,
            "manifest_opened": False,
            "case_hdf5_opened": False,
            "runtime_started": bool(launch.get("attempted", False)),
            "solver_worker_gpu_started": bool(launch.get("attempted", False)),
            "max_bounded_training_bytes": MAX_BOUNDED_JSON_BYTES,
            "max_evaluation_bytes": MAX_EVALUATION_JSON_BYTES,
        },
        "interpretation": (
            "This seed29-specific runner binds one diagnostic hidden16 full835 terminal. "
            "Progress/PID is never treated as completion; checkpoint and trajectory are "
            "stat-only, and no formal/T1/T2/credit or campaign mutation is produced."
        ),
    }


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    training_path: Path | str = DEFAULT_TRAINING_RECEIPT,
    evaluation_path: Path | str | None = DEFAULT_EVALUATION,
    observed_at_utc: str = "2026-09-28T00:00:00Z",
    launch: Mapping[str, Any] | None = None,
    scan_existing: bool = True,
) -> dict[str, Any]:
    del lab_root  # Paths are intentionally absolute and confined by validation.
    inventory = _candidate_inventory() if scan_existing else {
        "prefix": "scan_disabled",
        "files": [],
        "evaluation_candidates": [],
        "progress_or_trajectory_content_opened": False,
    }
    launch_info = dict(launch or {"attempted": False, "status": "not_started"})
    try:
        training, training_source, training_validation = _training_receipt(
            Path(training_path)
        )
    except RunnerError as error:
        training = None
        try:
            training_source = _source_ref(
                _absolute_path(training_path, "seed29 training receipt"),
                opened=False,
            )
        except RunnerError:
            training_source = {
                "path": str(training_path),
                "exists": False,
                "opened": False,
                "bytes": None,
                "sha256": None,
                "stable_fd": False,
                "path_reopened": False,
            }
        training_validation = {"valid": False, "reasons": [str(error)]}
    report = _base_report(
        observed_at_utc=observed_at_utc,
        inventory=inventory,
        training_source=training_source,
        training=training,
        training_errors=training_validation["reasons"],
        launch=launch_info,
    )
    if training is None or not training_validation["valid"]:
        return report
    candidates = _evaluation_candidates(
        Path(evaluation_path) if evaluation_path is not None else None,
        inventory,
    )
    rejection_reasons: list[str] = []
    for candidate in candidates:
        try:
            terminal, evaluation_source = _validate_evaluation(candidate, training)
        except RunnerError as error:
            rejection_reasons.append(f"{candidate}: {error}")
            continue
        report.update(
            {
                "status": "bound_terminal_diagnostic",
                "fail_closed": False,
                "source_bound": True,
                "seed29_terminal_receipt": terminal,
                "blocked_reasons": [],
            }
        )
        report["evaluation_source"] = evaluation_source
        report["input_boundary"].update(
            {
                "evaluation_json_opened": True,
                "checkpoint_opened": False,
                "progress_opened": False,
                "trajectory_hdf5_opened": False,
            }
        )
        report["side_effects"] = terminal["side_effects"]
        report["side_effects"]["diagnostic_evaluate_started"] = bool(
            launch_info.get("attempted", False)
        )
        return report
    if rejection_reasons:
        report["blocked_reasons"].extend(rejection_reasons)
    else:
        report["blocked_reasons"].append(
            "no bindable hidden16 seed29 full835 evaluation/terminal artifact"
        )
    if launch_info.get("status") in {"launched_pending", "running"}:
        report["status"] = "diagnostic_launch_pending"
        report["blocked_reasons"].append(
            "diagnostic evaluate is pending; PID/progress is not terminal completion"
        )
    else:
        report["status"] = (
            "diagnostic_launch_failed"
            if launch_info.get("status") == "failed"
            else "blocked_missing_terminal"
        )
    return report


def _gpu_snapshot(gpu_index: int) -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.free,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"available": False, "error": str(error), "gpu_index": gpu_index}
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 6:
            continue
        try:
            rows.append(
                {
                    "index": int(fields[0]),
                    "name": fields[1],
                    "memory_used_mib": int(fields[2]),
                    "memory_free_mib": int(fields[3]),
                    "memory_total_mib": int(fields[4]),
                    "utilization_gpu_percent": int(fields[5]),
                }
            )
        except ValueError:
            continue
    selected = next((row for row in rows if row["index"] == gpu_index), None)
    return {
        "available": result.returncode == 0 and selected is not None,
        "gpu_index": gpu_index,
        "selected": selected,
        "all_gpus": rows,
        "returncode": result.returncode,
    }


def _fresh_namespace_paths(namespace: Path) -> dict[str, Path]:
    namespace = _absolute_path(namespace, "fresh output namespace")
    if namespace == TMP_ROOT or TMP_ROOT not in namespace.parents:
        _fail("fresh output namespace must be under /tmp")
    return {
        "namespace": namespace,
        "evaluation": Path(f"{namespace}-evaluation.json"),
        "trajectory": Path(f"{namespace}-trajectory.h5"),
        "progress": Path(f"{namespace}-evaluation-progress.json"),
        "log": Path(f"{namespace}-evaluation.log"),
    }


def launch_diagnostic(
    lab_root: Path | str = LAB_ROOT,
    *,
    gpu_index: int = DEFAULT_GPU_INDEX,
    namespace: Path | str = DEFAULT_NAMESPACE,
    training_path: Path | str = DEFAULT_TRAINING_RECEIPT,
) -> dict[str, Any]:
    del lab_root, gpu_index, training_path
    paths = _fresh_namespace_paths(Path(namespace))
    collisions: list[str] = []
    for path in paths.values():
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError:
            collisions.append(str(path))
        else:
            collisions.append(str(path))
    if collisions:
        return {
            "attempted": False,
            "status": "blocked_namespace_collision",
            "namespace": str(paths["namespace"]),
            "collisions": collisions,
            "security_boundary": _security_boundary(),
            "reason": "refusing to reuse any existing output path",
        }
    return {
        "attempted": False,
        "status": "blocked_p1_security_boundary",
        "namespace": str(paths["namespace"]),
        "collisions": [],
        "security_boundary": _security_boundary(),
        "reason": "seed29 v1 has no independently sealed admission; refusing GPU/Popen execution",
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("schema drift")
    if report.get("report_id") != REPORT_ID:
        errors.append("report_id drift")
    for key, expected in (
        ("diagnostic_only", True),
        ("formal", False),
        ("formal_eligible", False),
        ("T1_numerical", False),
        ("T2_macro", False),
        ("qualification", False),
        ("qualification_credit", 0),
        ("credit", 0),
    ):
        if report.get(key) != expected:
            errors.append(f"{key} must be {expected!r}")
    target = report.get("target_contract")
    if not isinstance(target, Mapping):
        errors.append("target_contract missing")
    else:
        for key, expected in (
            ("model_kind", MODEL_KIND),
            ("seed", SEED),
            ("hidden", HIDDEN),
            ("updates", UPDATES),
            ("transitions", TRANSITIONS),
            ("frames", FRAMES),
        ):
            if target.get(key) != expected:
                errors.append(f"target_contract.{key} drift")
    terminal = report.get("seed29_terminal_receipt")
    if report.get("source_bound"):
        if report.get("status") != "bound_terminal_diagnostic":
            errors.append("bound report status drift")
        if not isinstance(terminal, Mapping):
            errors.append("bound report lacks terminal receipt")
        else:
            if terminal.get("transitions") != TRANSITIONS or terminal.get("frames") != FRAMES:
                errors.append("terminal markers drift")
            if terminal.get("diagnostic_only") is not True:
                errors.append("terminal is not diagnostic-only")
            if terminal.get("qualification_credit") != 0:
                errors.append("terminal credit drift")
    elif terminal is not None:
        errors.append("unbound report must not contain terminal receipt")
    security = report.get("security_boundary")
    if not isinstance(security, Mapping):
        errors.append("security_boundary missing")
    else:
        if security.get("status") != "blocked_fail_closed":
            errors.append("security_boundary must remain blocked_fail_closed")
        for key, expected in (
            ("execution_authorized", False),
            ("launch_allowed", False),
            ("popen_attempted", False),
            ("wait_attempted", False),
        ):
            if security.get(key) is not expected:
                errors.append(f"security_boundary.{key} must be {expected!r}")
        if tuple(security.get("blockers", ())) != P1_SECURITY_BLOCKERS:
            errors.append("security_boundary blockers drift")
    effects = report.get("side_effects")
    if isinstance(effects, Mapping):
        for key in (
            "manifest_opened",
            "case_hdf5_opened",
            "checkpoint_opened",
            "trajectory_hdf5_opened",
            "progress_opened",
            "registry_mutation",
            "ledger_mutation",
            "denominator_mutation",
            "gate_mutation",
            "completion_mutation",
        ):
            if effects.get(key) not in (False, 0):
                errors.append(f"side_effects.{key} must be false/zero")
    else:
        errors.append("side_effects missing")
    return errors


def render_zh_report(report: Mapping[str, Any]) -> str:
    terminal = report.get("seed29_terminal_receipt")
    lines = [
        "# F3 graph_raw hidden16 seed29 terminal completion receipt V1",
        "",
        "本报告仅对应 seed29，不修改共享 F3 bridge、PLAN、registry、ledger、denominator、gate 或 completion。",
        "",
        f"- 状态：`{report.get('status')}`；source_bound=`{report.get('source_bound')}`。",
        f"- 固定目标：`{MODEL_KIND}`、hidden=`{HIDDEN}`、updates=`{UPDATES}`、`{TRANSITIONS}` transitions / `{FRAMES}` frames、case=`{CASE_ID}`。",
        "- 性质：diagnostic-only；formal/T1/T2/qualification=false，credit=0，所有 campaign mutation=0。",
        "- 安全边界：未打开 progress、trajectory/HDF5、manifest 或 checkpoint 内容；trajectory/checkpoint 只做 stat/receipt identity；PID/progress 不视为完成。",
        "- P1 执行边界：没有独立 admission、sealed real Popen/wait、一次性 namespace 或完整 source/manifest/checkpoint/environment/executable identity；launch 保持 fail-closed。",
        "",
        "## 结果",
        "",
    ]
    if isinstance(terminal, Mapping):
        evaluation = terminal.get("evaluation_binding", {})
        trajectory = terminal.get("trajectory_binding", {})
        lines.extend(
            [
                "- 已绑定 seed29 hidden16 full835 diagnostic terminal。",
                f"- evaluation：`{evaluation.get('bytes')}` bytes，SHA-256 `{evaluation.get('sha256')}`。",
                f"- trajectory：`{trajectory.get('bytes')}` bytes，stat-only；marker=`{terminal.get('transitions')}/{terminal.get('frames')}`。",
                "- terminal markers：`terminal=true`、`execution_complete=true`、`finite_rollout_complete=true`。",
            ]
        )
    else:
        reasons = report.get("blocked_reasons", [])
        lines.append("- 当前没有可绑定的终态 receipt；保持 fail-closed。")
        for reason in reasons[:8]:
            lines.append(f"- blocker：{reason}")
    launch = report.get("launch", {})
    lines.extend(
        [
            "",
            "## 运行记录",
            "",
            f"- launch status：`{launch.get('status')}`；attempted=`{launch.get('attempted')}`。",
            f"- namespace：`{launch.get('namespace', str(DEFAULT_NAMESPACE))}`。",
            "- existing live jobs 未停止、未重启；若执行新 diagnostic，仅使用唯一输出 namespace。",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], output: Path | str, zh_output: Path | str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    zh_path = Path(zh_output)
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.write_text(render_zh_report(report), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--training-receipt", type=Path, default=DEFAULT_TRAINING_RECEIPT)
    parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--gpu-index", type=int, default=DEFAULT_GPU_INDEX)
    parser.add_argument("--namespace", type=Path, default=DEFAULT_NAMESPACE)
    parser.add_argument("--launch-if-missing", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    parser.add_argument("--observed-at-utc", default="2026-09-28T00:00:00Z")
    args = parser.parse_args(argv)

    report = build_report(
        args.root,
        training_path=args.training_receipt,
        evaluation_path=args.evaluation,
        observed_at_utc=args.observed_at_utc,
    )
    if not report["source_bound"] and args.launch_if_missing:
        try:
            launch = launch_diagnostic(
                args.root,
                gpu_index=args.gpu_index,
                namespace=args.namespace,
                training_path=args.training_receipt,
            )
        except RunnerError as error:
            launch = {
                "attempted": False,
                "status": "failed",
                "reason": str(error),
            }
        report = build_report(
            args.root,
            training_path=args.training_receipt,
            evaluation_path=args.evaluation,
            observed_at_utc=args.observed_at_utc,
            launch=launch,
        )
    write_outputs(report, args.output, args.zh_output)
    errors = validate_report(report)
    if errors:
        raise SystemExit("report validation failed: " + "; ".join(errors))
    print(
        json.dumps(
            {
                "status": report["status"],
                "source_bound": report["source_bound"],
                "launch": report["launch"].get("status"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
