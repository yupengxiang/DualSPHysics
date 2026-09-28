#!/usr/bin/env python3
"""Bind the F3 ``graph_raw`` hidden16 three-seed rollout matrix.

This is a read-only, JSON-bound diagnostic adapter.  It accepts the small
``core.training.v1`` receipts and the bounded terminal rollout summaries
written for the hidden16 runs.  It never opens a manifest, case HDF5,
checkpoint, trajectory, or progress file.  The large ``core.evaluation.v1``
payload and the progress/trajectory artifacts remain declared terminal
artifacts, not adapter inputs.

The adapter is intentionally fail-closed.  A missing seed, a hidden/config
drift, a non-terminal rollout, a stale checkpoint binding, a reused output
namespace, a future-state claim, or any formal/credit marker closes the
matrix.  A successful result is still diagnostic-only and cannot mutate or
authorize any campaign state.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "core.f3.graph_raw.hidden16.cross_seed_rollout_consistency.v1"
REPORT_SCHEMA = "core.f3.graph_raw.hidden16.cross_seed_rollout_consistency_report.v1"
REPORT_ID = "f3-graph-raw-hidden16-cross-seed-rollout-consistency-v1"
LAB_ROOT = Path(__file__).resolve().parents[1]

SEEDS = (17, 29, 43)
EXPECTED_TRANSITIONS = 835
EXPECTED_FRAMES = 836
EXPECTED_HIDDEN = 16
EXPECTED_UPDATES = 500
EXPECTED_MODEL = "graph_raw"
EXPECTED_CASE_ID = "F3_DEV_00_a0p903125"
MAX_JSON_BYTES = 1 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OUTPUT_PREFIX_RE = re.compile(
    r"^/[^\x00]*f3-graph-raw500-hidden16-seed(?P<seed>[0-9]+)-full835-[^/]+$"
)
JSON_SUFFIXES = {".json", ".jsonl"}
DISALLOWED_SUFFIXES = {".h5", ".hdf5", ".pt", ".pth", ".ckpt", ".bin"}

TRAINING_MATRIX_SCHEMA = "core.f3.graph_raw.hidden16.training_matrix.v1"
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
INITIALIZATION_SCHEMA = "core.training.initialization_evidence.v1"

DEFAULT_OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
DEFAULT_TRAINING_MATRIX = Path(
    "reports/F3-GRAPH-RAW-HIDDEN16-SEEDS17-29-43-TRAINING-2026-09-28.json"
)
DEFAULT_TRAINING = {
    seed: Path(f"/tmp/f3-graph-raw500-hidden16-seed{seed}-20260928-training.json")
    for seed in SEEDS
}
# The seed29 path is the existing observed candidate.  It is intentionally
# the older non-hidden16 report so that the checked-in report records the
# real configuration drift instead of inventing a missing hidden16 receipt.
DEFAULT_ROLLOUT = {
    17: Path(
        "reports/F3-GRAPH-RAW-HIDDEN16-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json"
    ),
    29: Path("reports/F3-GRAPH-RAW-SEED29-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json"),
    43: Path(
        "reports/F3-GRAPH-RAW-HIDDEN16-SEED43-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json"
    ),
}

REQUIRED_TRAINING_CONFIG = {
    "centers_per_update": 256,
    "checkpoint_every": 500,
    "evaluate_milestones": True,
    "gradient_clipping": None,
    "hidden": EXPECTED_HIDDEN,
    "history_states": 1,
    "initialization": "core.paired_initialization.common_encoder_head.v1",
    "learning_rate": 0.001,
    "log_every": 100,
    "manifest_formal_release": False,
    "max_neighbors": 192,
    "milestone_evaluation_mode": "in_process",
    "normalization_source_split": "train",
    "optimizer": "Adam",
    "radius_over_h": 2.0,
    "target_normalization": "raw_dual_increment_train_shared",
    "updates": EXPECTED_UPDATES,
    "validation_case_count": 4,
    "validation_centers": 256,
    "validation_every": 500,
    "validation_family_counts": {"F3": 4},
    "validation_formal_eligible": False,
    "validation_transition_count": 4,
}


class ConsistencyError(ValueError):
    """A malformed, incomplete, or unsafe consistency input."""


def _fail(message: str) -> None:
    raise ConsistencyError(f"fail-closed: {message}")


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


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or "\x00" in value or (nonempty and not value):
        _fail(f"{name} must be a {'non-empty ' if nonempty else ''}string")
    return value


def _identifier(value: Any, name: str) -> str:
    text = _string(value, name)
    if "/" in text or "\\" in text:
        _fail(f"{name} must not contain path separators")
    return text


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _strict_int(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum or (
        maximum is not None and value > maximum
    ):
        bound = f" in [{minimum}, {maximum}]" if maximum is not None else f" >= {minimum}"
        _fail(f"{name} must be an integer{bound}")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _declared_path(value: Any, name: str) -> str:
    path = _string(value, name)
    if any(part == ".." for part in Path(path).parts):
        _fail(f"{name} must not contain parent traversal")
    return path


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _read_bounded_json(root: Path, path_value: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if path.suffix.lower() in DISALLOWED_SUFFIXES:
        _fail(f"disallowed non-JSON input was requested: {path}")
    if path.suffix.lower() not in JSON_SUFFIXES:
        _fail(f"input must be a JSON file: {path}")
    if not path.is_file():
        _fail(f"missing JSON receipt: {path}")
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        _fail(f"JSON receipt exceeds bounded input limit: {path} ({size} bytes)")
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ConsistencyError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read strict UTF-8 JSON {path}: {error}")
    _check_finite(value, str(path))
    result = dict(_mapping(value, str(path)))
    return result, {
        "path": _display_path(root, path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": result.get("schema"),
        "opened": True,
    }


def _source_ref_for_payload(payload: Mapping[str, Any], path: str) -> dict[str, Any]:
    raw = canonical_json(payload).encode("utf-8")
    return {
        "path": path,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload.get("schema"),
        "opened": False,
    }


def _missing_ref(root: Path, path_value: Path | str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = root / path
    return {
        "path": _display_path(root, path.resolve()),
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "schema": None,
        "opened": False,
    }


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


def _require_zero(value: Mapping[str, Any], key: str, name: str) -> None:
    if key not in value or type(value[key]) is not int or value[key] != 0:
        _fail(f"{name}.{key} must be integer zero")


def _require_false(value: Mapping[str, Any], key: str, name: str) -> None:
    if key not in value or type(value[key]) is not bool or value[key] is not False:
        _fail(f"{name}.{key} must be false")


def _validate_training_markers(receipt: Mapping[str, Any], name: str) -> None:
    config = _mapping(receipt.get("config"), f"{name}.config")
    _require_false(config, "manifest_formal_release", f"{name}.config")
    _require_false(config, "validation_formal_eligible", f"{name}.config")
    evidence = _mapping(receipt.get("evidence"), f"{name}.evidence")
    _require_false(
        _mapping(evidence.get("residual_prior"), f"{name}.evidence.residual_prior"),
        "enabled",
        f"{name}.evidence.residual_prior",
    )


def _training_shared_config(config: Mapping[str, Any], normalization: Mapping[str, Any]) -> dict[str, Any]:
    seed_specific = {"paired_seed", "run_id", "sampler_seed", "seed"}
    result = {key: copy.deepcopy(value) for key, value in config.items() if key not in seed_specific}
    result["normalization_transitions"] = normalization["requested_maximum_transitions"]
    return result


def validate_training_receipt(receipt: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Validate one bounded ``core.training.v1`` receipt without opening its checkpoint."""

    value = _mapping(receipt, f"training[{seed}]")
    if value.get("schema") != TRAINING_SCHEMA:
        _fail(f"training[{seed}].schema must be {TRAINING_SCHEMA}")
    if value.get("status") not in {None, "completed"} or value.get("evidence_status") != "complete":
        _fail(f"training[{seed}] must have complete evidence and, when present, completed status")
    if value.get("model_kind") != EXPECTED_MODEL:
        _fail(f"training[{seed}].model_kind must be {EXPECTED_MODEL}")
    if _strict_int(value.get("seed"), f"training[{seed}].seed") != seed:
        _fail(f"training[{seed}].seed does not match requested seed")
    if _strict_int(value.get("completed_updates"), f"training[{seed}].completed_updates") != EXPECTED_UPDATES:
        _fail(f"training[{seed}].completed_updates must be {EXPECTED_UPDATES}")

    config = _mapping(value.get("config"), f"training[{seed}].config")
    for key, expected in REQUIRED_TRAINING_CONFIG.items():
        if config.get(key) != expected:
            _fail(
                f"training[{seed}].config.{key} drifts: "
                f"observed={config.get(key)!r} expected={expected!r}"
            )
    if _strict_int(config.get("seed"), f"training[{seed}].config.seed") != seed:
        _fail(f"training[{seed}].config.seed does not match seed")
    if _strict_int(config.get("paired_seed"), f"training[{seed}].config.paired_seed") != seed:
        _fail(f"training[{seed}].config.paired_seed does not match seed")
    if _strict_int(config.get("sampler_seed"), f"training[{seed}].config.sampler_seed") != seed:
        _fail(f"training[{seed}].config.sampler_seed does not match seed")
    expected_run_id = f"graph_raw-hidden16-seed{seed}"
    if config.get("run_id") != expected_run_id or value.get("run_id") != expected_run_id:
        _fail(f"training[{seed}] run_id does not bind the hidden16 seed")
    manifest_sha = _sha256(config.get("manifest_sha256"), f"training[{seed}].config.manifest_sha256")

    evidence = _mapping(value.get("evidence"), f"training[{seed}].evidence")
    if evidence.get("schema") != "core.training.evidence.v1" or evidence.get("status") != "complete":
        _fail(f"training[{seed}].evidence must be complete core.training.evidence.v1")
    initialization = _mapping(evidence.get("initialization"), f"training[{seed}].evidence.initialization")
    if initialization.get("schema") != INITIALIZATION_SCHEMA or initialization.get("status") != "captured":
        _fail(f"training[{seed}] initialization evidence is incomplete")
    if initialization.get("model_kind") != EXPECTED_MODEL or initialization.get("seed") != seed:
        _fail(f"training[{seed}] initialization model/seed drifts")
    if initialization.get("hidden") != EXPECTED_HIDDEN:
        _fail(f"training[{seed}] initialization hidden drifts")
    parameter_count = _strict_int(value.get("parameter_count"), f"training[{seed}].parameter_count", minimum=1)
    if initialization.get("parameter_count") != parameter_count:
        _fail(f"training[{seed}] initialization parameter count drifts")
    _sha256(initialization.get("parameter_digest"), f"training[{seed}].evidence.initialization.parameter_digest")

    normalization = _mapping(evidence.get("normalization"), f"training[{seed}].evidence.normalization")
    if normalization.get("schema") != "core.training.normalization_evidence.v1":
        _fail(f"training[{seed}] normalization evidence schema drifts")
    if normalization.get("requested_maximum_transitions") != 16:
        _fail(f"training[{seed}] normalization transition count must be 16")
    if normalization.get("selected_transition_count") != 16:
        _fail(f"training[{seed}] selected normalization transition count must be 16")
    if normalization.get("selection_policy") != "deterministic_evenly_spaced_train_transitions_v1":
        _fail(f"training[{seed}] normalization selection policy drifts")
    if normalization.get("source_split") != "train":
        _fail(f"training[{seed}] normalization source split drifts")
    if normalization.get("target_reference") != "raw_dual_increment_train_shared":
        _fail(f"training[{seed}] normalization target reference drifts")
    _validate_training_markers(value, f"training[{seed}]")

    checkpoint = _mapping(value.get("checkpoint"), f"training[{seed}].checkpoint")
    if checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        _fail(f"training[{seed}].checkpoint.schema must be {CHECKPOINT_SCHEMA}")
    checkpoint_path = _declared_path(checkpoint.get("path"), f"training[{seed}].checkpoint.path")
    checkpoint_sha = _sha256(checkpoint.get("sha256"), f"training[{seed}].checkpoint.sha256")
    if checkpoint.get("update") != EXPECTED_UPDATES:
        _fail(f"training[{seed}].checkpoint.update must be {EXPECTED_UPDATES}")
    if value.get("checkpoint_verified") is not True:
        _fail(f"training[{seed}].checkpoint_verified must be true")

    return {
        "seed": seed,
        "schema": TRAINING_SCHEMA,
        "run_id": expected_run_id,
        "model_kind": EXPECTED_MODEL,
        "hidden": EXPECTED_HIDDEN,
        "updates": EXPECTED_UPDATES,
        "parameter_count": parameter_count,
        "checkpoint": {
            "schema": CHECKPOINT_SCHEMA,
            "path": checkpoint_path,
            "sha256": checkpoint_sha,
            "update": EXPECTED_UPDATES,
        },
        "manifest_sha256": manifest_sha,
        "shared_config": _training_shared_config(config, normalization),
        "initialization_parameter_digest": initialization["parameter_digest"],
        "diagnostic_markers": {
            "manifest_formal_release": False,
            "validation_formal_eligible": False,
            "residual_prior_enabled": False,
        },
    }


def _validate_summary_diagnostic_markers(value: Mapping[str, Any], name: str) -> None:
    if value.get("diagnostic_only") is not True:
        _fail(f"{name}.diagnostic_only must be true")
    if value.get("formal_eligible") is not False:
        _fail(f"{name}.formal_eligible must be false")
    if value.get("future_state_inputs") is not False:
        _fail(f"{name}.future_state_inputs must be false")
    _require_zero(value, "qualification_credit", name)
    qualification = _mapping(value.get("qualification"), f"{name}.qualification")
    for key in ("T1_numerical", "T2_macro", "T2_path", "formal_eligible", "formal_training"):
        _require_false(qualification, key, f"{name}.qualification")
    _require_zero(qualification, "qualification_credit", f"{name}.qualification")
    if "credit" in qualification:
        _require_zero(qualification, "credit", f"{name}.qualification")

    side_effects = _mapping(value.get("side_effects"), f"{name}.side_effects")
    for key in (
        "completion_mutation",
        "diagnostic_counted_as_T1_or_T2",
        "formal_training_counted",
        "future_state_inputs",
        "manifest_modified",
        "production_hdf5_modified",
        "rollout_inputs_read_only",
        "source_modified_by_rollout",
    ):
        if key == "rollout_inputs_read_only":
            if side_effects.get(key) is not True:
                _fail(f"{name}.side_effects.{key} must be true")
        else:
            _require_false(side_effects, key, f"{name}.side_effects")
    for key in ("registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation"):
        if key in side_effects:
            if type(side_effects[key]) is int and side_effects[key] == 0:
                continue
            if type(side_effects[key]) is bool and side_effects[key] is False:
                continue
            _fail(f"{name}.side_effects.{key} must be zero/false")


def _declared_artifact(value: Mapping[str, Any], name: str, suffix: str) -> dict[str, Any]:
    path = _declared_path(value.get("path"), f"{name}.path")
    if not path.startswith("/"):
        _fail(f"{name}.path must be absolute")
    if not path.endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    return {
        "path": path,
        "bytes": _strict_int(value.get("bytes"), f"{name}.bytes", minimum=1),
        "sha256": _sha256(value.get("sha256"), f"{name}.sha256"),
    }


def _extract_rollout_receipt_artifact(evaluation: Mapping[str, Any], name: str) -> dict[str, Any]:
    receipt = evaluation.get("receipt")
    if not isinstance(receipt, Mapping):
        # Older summaries used flat names.  The current hidden16 summaries use
        # the nested receipt object; accepting the alias keeps the boundary
        # explicit without opening the large receipt itself.
        receipt = {
            "path": evaluation.get("receipt_path"),
            "bytes": evaluation.get("receipt_bytes"),
            "sha256": evaluation.get("receipt_sha256"),
        }
    return _declared_artifact(receipt, f"{name}.receipt", "-evaluation.json")


def _validate_output_identity(
    evaluation: Mapping[str, Any],
    trajectory: Mapping[str, Any],
    seed: int,
    name: str,
) -> dict[str, Any]:
    receipt = _extract_rollout_receipt_artifact(evaluation, name)
    prefix = receipt["path"][: -len("-evaluation.json")]
    match = OUTPUT_PREFIX_RE.fullmatch(prefix)
    if match is None or int(match.group("seed")) != seed:
        _fail(f"{name} output prefix is not a fresh hidden16 seed namespace")
    trajectory_artifact = _declared_artifact(trajectory, f"{name}.trajectory", "-trajectory.h5")
    progress = _mapping(evaluation.get("progress"), f"{name}.progress")
    progress_artifact = _declared_artifact(progress, f"{name}.progress", "-evaluation-progress.json")
    expected_trajectory = prefix + "-trajectory.h5"
    expected_progress = prefix + "-evaluation-progress.json"
    if trajectory_artifact["path"] != expected_trajectory:
        _fail(f"{name}.trajectory path is not derived from the evaluation receipt")
    if progress_artifact["path"] != expected_progress:
        _fail(f"{name}.progress path is not derived from the evaluation receipt")
    return {
        "evaluation": receipt,
        "trajectory": trajectory_artifact,
        "progress": progress_artifact,
        "prefix": prefix,
    }


def validate_rollout_receipt(
    receipt: Mapping[str, Any],
    seed: int,
    training: Mapping[str, Any],
    training_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a small hidden16 terminal rollout summary only."""

    value = _mapping(receipt, f"rollout[{seed}]")
    accepted_schemas = {
        f"core.f3.graph_raw.hidden16.seed{seed}.full835.rollout_diagnostic.summary.v1",
        "core.f3.graph_raw.hidden16.full835.rollout_diagnostic.summary.v1",
    }
    if value.get("schema") not in accepted_schemas:
        _fail(
            f"rollout[{seed}].schema is not an accepted hidden16 terminal summary: "
            f"{value.get('schema')!r}"
        )
    if value.get("status") not in {"completed", "completed_diagnostic"}:
        _fail(f"rollout[{seed}] is not terminal completed")
    if "running" in str(value.get("status", "")).lower() or "partial" in str(value.get("status", "")).lower():
        _fail(f"rollout[{seed}] is running/partial")
    _validate_summary_diagnostic_markers(value, f"rollout[{seed}]")

    protocol = _mapping(value.get("protocol"), f"rollout[{seed}].protocol")
    if protocol.get("model_kind") != EXPECTED_MODEL:
        _fail(f"rollout[{seed}].protocol.model_kind drifts")
    if protocol.get("seed") != seed:
        _fail(f"rollout[{seed}].protocol.seed drifts")
    if protocol.get("hidden") != EXPECTED_HIDDEN:
        _fail(f"rollout[{seed}].protocol.hidden must be {EXPECTED_HIDDEN}")
    if protocol.get("updates") != EXPECTED_UPDATES:
        _fail(f"rollout[{seed}].protocol.updates must be {EXPECTED_UPDATES}")
    if protocol.get("parameter_count") != training["parameter_count"]:
        _fail(f"rollout[{seed}].protocol.parameter_count drifts from training")
    for key, expected in {
        "centers_per_update": 256,
        "learning_rate": 0.001,
        "max_neighbors": 192,
        "normalization_source_split": "train",
        "normalization_transitions": 16,
        "target_normalization": "raw_dual_increment_train_shared",
        "split": "test",
        "maximum_steps": EXPECTED_TRANSITIONS,
        "diagnostic": True,
        "autonomous": True,
        "future_state_inputs": False,
        "training_started_for_this_rollout": False,
    }.items():
        if protocol.get(key) != expected:
            _fail(f"rollout[{seed}].protocol.{key} drifts")
    if protocol.get("case_id") != EXPECTED_CASE_ID:
        _fail(f"rollout[{seed}].protocol.case_id drifts")

    training_summary = _mapping(value.get("training"), f"rollout[{seed}].training")
    for key, expected in {
        "schema": TRAINING_SCHEMA,
        "status": "completed",
        "evidence_status": "complete",
        "model_kind": EXPECTED_MODEL,
        "seed": seed,
        "hidden": EXPECTED_HIDDEN,
        "completed_updates": EXPECTED_UPDATES,
        "parameter_count": training["parameter_count"],
        "checkpoint_verified": True,
    }.items():
        if training_summary.get(key) != expected:
            _fail(f"rollout[{seed}].training.{key} is missing or drifts")
    if training_summary.get("residual_prior_enabled") is not False:
        _fail(f"rollout[{seed}].training.residual_prior_enabled must be false")

    bindings = _mapping(value.get("bindings"), f"rollout[{seed}].bindings")
    checkpoint = _mapping(bindings.get("checkpoint"), f"rollout[{seed}].bindings.checkpoint")
    if checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        _fail(f"rollout[{seed}] checkpoint schema drifts")
    rollout_checkpoint_path = _declared_path(
        checkpoint.get("path"), f"rollout[{seed}].bindings.checkpoint.path"
    )
    rollout_checkpoint_sha = _sha256(
        checkpoint.get("sha256"), f"rollout[{seed}].bindings.checkpoint.sha256"
    )
    if checkpoint.get("seed") != seed or checkpoint.get("hidden") != EXPECTED_HIDDEN:
        _fail(f"rollout[{seed}] checkpoint seed/hidden drifts")
    if checkpoint.get("model_kind") != EXPECTED_MODEL or checkpoint.get("update") != EXPECTED_UPDATES:
        _fail(f"rollout[{seed}] checkpoint model/update drifts")
    if rollout_checkpoint_path != training["checkpoint"]["path"]:
        _fail(f"rollout[{seed}] checkpoint path does not match training")
    if rollout_checkpoint_sha != training["checkpoint"]["sha256"]:
        _fail(f"rollout[{seed}] checkpoint SHA does not match training")
    for key in (
        "checkpoint_hash_matches_training_receipt",
        "checkpoint_verified",
        "evaluation_checkpoint_path_matches_training",
        "training_protocol_binding_exact",
    ):
        if bindings.get(key) is not True:
            _fail(f"rollout[{seed}].bindings.{key} must be true")
    training_binding = _mapping(bindings.get("training_receipt"), f"rollout[{seed}].bindings.training_receipt")
    if training_source is not None:
        if training_binding.get("sha256") != training_source.get("sha256"):
            _fail(f"rollout[{seed}] training receipt SHA does not match input training receipt")
        if training_binding.get("path") != training_source.get("path"):
            _fail(f"rollout[{seed}] training receipt path does not match input training receipt")

    evaluation = _mapping(value.get("evaluation"), f"rollout[{seed}].evaluation")
    for key, expected in {
        "schema": "core.evaluation.v1",
        "mode": "diagnostic",
        "diagnostic": True,
        "formal_eligible": False,
        "future_state_inputs": False,
        "status": "completed",
        "requested_steps": EXPECTED_TRANSITIONS,
        "expected_full_case_transitions": EXPECTED_TRANSITIONS,
        "expected_full_case_frames": EXPECTED_FRAMES,
        "frames_executed": EXPECTED_TRANSITIONS,
        "trajectory_frames_including_initial": EXPECTED_FRAMES,
        "requested_window_complete": True,
        "finite_rollout_complete_for_requested_window": True,
        "full_registered_denominator_complete": True,
        "failure_category": None,
        "scientific_failure_category": None,
        "scientific_status": "not_assessed",
        "split": "test",
    }.items():
        if evaluation.get(key) != expected:
            _fail(f"rollout[{seed}].evaluation.{key} is missing or drifts")
    coverage = _mapping(evaluation.get("raw_error_coverage"), f"rollout[{seed}].evaluation.raw_error_coverage")
    if coverage.get("denominator_transitions") != EXPECTED_TRANSITIONS:
        _fail(f"rollout[{seed}] raw error denominator drifts")
    if coverage.get("numerator_transitions") != EXPECTED_TRANSITIONS or coverage.get("fraction") != 1.0:
        _fail(f"rollout[{seed}] raw error coverage is partial")
    progress = _mapping(evaluation.get("progress"), f"rollout[{seed}].evaluation.progress")
    for key, expected in {
        "status": "completed",
        "expected_frames": EXPECTED_TRANSITIONS,
        "frames_executed": EXPECTED_TRANSITIONS,
        "future_state_inputs": False,
    }.items():
        if progress.get(key) != expected:
            _fail(f"rollout[{seed}].evaluation.progress.{key} drifts")
    hdf5_validation = _mapping(
        evaluation.get("hdf5_validation"), f"rollout[{seed}].evaluation.hdf5_validation"
    )
    for key, expected in {
        "schema": "core.f3.full_rollout_receipt_hdf5_validation.v1",
        "passed": True,
        "complete": True,
        "executed_frame_count": EXPECTED_FRAMES,
        "trajectory_frames": EXPECTED_FRAMES,
        "trajectory_transitions": EXPECTED_TRANSITIONS,
        "qualification_credit": 0,
        "synthetic_only": False,
    }.items():
        if hdf5_validation.get(key) != expected:
            _fail(f"rollout[{seed}].evaluation.hdf5_validation.{key} drifts")

    trajectory = _mapping(value.get("trajectory"), f"rollout[{seed}].trajectory")
    shapes = _mapping(trajectory.get("shapes"), f"rollout[{seed}].trajectory.shapes")
    for key in ("position", "velocity", "valid", "time"):
        if key not in shapes or not isinstance(shapes[key], list) or not shapes[key]:
            _fail(f"rollout[{seed}].trajectory.shapes.{key} is missing")
    if shapes["position"][0] != EXPECTED_FRAMES or shapes["velocity"][0] != EXPECTED_FRAMES:
        _fail(f"rollout[{seed}] trajectory position/velocity frame count drifts")
    if shapes["valid"][0] != EXPECTED_FRAMES or shapes["time"][0] != EXPECTED_FRAMES:
        _fail(f"rollout[{seed}] trajectory valid/time frame count drifts")
    for key in ("position_finite", "velocity_finite", "valid_all_true", "mass_finite", "mass_positive", "mass_static"):
        if trajectory.get(key) is not True:
            _fail(f"rollout[{seed}].trajectory.{key} must be true")
    trajectory_attrs = _mapping(
        trajectory.get("hdf5_attrs", {}), f"rollout[{seed}].trajectory.hdf5_attrs"
    )
    trajectory_future_state_inputs = trajectory.get(
        "future_state_inputs", trajectory_attrs.get("future_state_inputs")
    )
    if trajectory_future_state_inputs is not False:
        _fail(f"rollout[{seed}].trajectory.future_state_inputs must be false")
    outputs = _validate_output_identity(evaluation, trajectory, seed, f"rollout[{seed}]")

    return {
        "seed": seed,
        "schema": value["schema"],
        "status": "terminal_completed_diagnostic",
        "model_kind": EXPECTED_MODEL,
        "hidden": EXPECTED_HIDDEN,
        "updates": EXPECTED_UPDATES,
        "parameter_count": training["parameter_count"],
        "case_id": EXPECTED_CASE_ID,
        "checkpoint": {
            "path": rollout_checkpoint_path,
            "sha256": rollout_checkpoint_sha,
            "update": EXPECTED_UPDATES,
        },
        "terminal_receipt": outputs["evaluation"],
        "output_identity": outputs,
        "config": {
            "model_kind": EXPECTED_MODEL,
            "hidden": EXPECTED_HIDDEN,
            "updates": EXPECTED_UPDATES,
            "centers_per_update": 256,
            "learning_rate": 0.001,
            "max_neighbors": 192,
            "normalization_source_split": "train",
            "normalization_transitions": 16,
            "target_normalization": "raw_dual_increment_train_shared",
            "split": "test",
            "maximum_steps": EXPECTED_TRANSITIONS,
            "diagnostic": True,
            "autonomous": True,
            "future_state_inputs": False,
        },
    }


def _observed_rollout_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    protocol = value.get("protocol") if isinstance(value.get("protocol"), Mapping) else {}
    evaluation = value.get("evaluation") if isinstance(value.get("evaluation"), Mapping) else {}
    return {
        "schema": value.get("schema"),
        "status": value.get("status"),
        "model_kind": protocol.get("model_kind"),
        "seed": protocol.get("seed"),
        "hidden": protocol.get("hidden"),
        "updates": protocol.get("updates"),
        "maximum_steps": protocol.get("maximum_steps"),
        "evaluation_status": evaluation.get("status"),
        "frames_executed": evaluation.get("frames_executed"),
        "trajectory_frames": evaluation.get("trajectory_frames_including_initial"),
        "future_state_inputs": value.get("future_state_inputs", evaluation.get("future_state_inputs")),
    }


def _validate_training_matrix(
    matrix: Mapping[str, Any],
    training_sources: Mapping[int, Mapping[str, Any]],
    trainings: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    value = _mapping(matrix, "training_matrix")
    if value.get("schema") != TRAINING_MATRIX_SCHEMA:
        _fail(f"training_matrix.schema must be {TRAINING_MATRIX_SCHEMA}")
    if value.get("model") != EXPECTED_MODEL or value.get("diagnostic_only") is not True:
        _fail("training_matrix model/diagnostic markers drift")
    if value.get("formal_eligible") is not False:
        _fail("training_matrix.formal_eligible must be false")
    qualification = _mapping(value.get("qualification"), "training_matrix.qualification")
    if qualification.get("qualification") is not False or qualification.get("t1") is not False or qualification.get("t2") is not False:
        _fail("training_matrix qualification markers must be false")
    if qualification.get("credit") != 0:
        _fail("training_matrix credit must be zero")
    shared = _mapping(value.get("shared_config"), "training_matrix.shared_config")
    for key, expected in {
        "hidden": EXPECTED_HIDDEN,
        "updates": EXPECTED_UPDATES,
        "centers_per_update": 256,
        "learning_rate": 0.001,
        "max_neighbors": 192,
        "normalization_transitions": 16,
        "target_normalization": "raw_dual_increment_train_shared",
        "validation_transition_count": 4,
        "manifest_formal_release": False,
    }.items():
        if shared.get(key) != expected:
            _fail(f"training_matrix.shared_config.{key} drifts")
    runs = value.get("runs")
    if not isinstance(runs, list) or {row.get("seed") for row in runs if isinstance(row, Mapping)} != set(SEEDS):
        _fail("training_matrix runs must contain exactly seeds 17/29/43")
    rows = {row["seed"]: row for row in runs}
    for seed in SEEDS:
        row = _mapping(rows.get(seed), f"training_matrix.runs[{seed}]")
        if row.get("run_id") != f"graph_raw-hidden16-seed{seed}":
            _fail(f"training_matrix seed{seed} run_id drifts")
        if row.get("completed_updates") != EXPECTED_UPDATES or row.get("checkpoint_verified") is not True:
            _fail(f"training_matrix seed{seed} training completion drifts")
        if row.get("parameter_count") != trainings[seed]["parameter_count"]:
            _fail(f"training_matrix seed{seed} parameter count drifts")
        if row.get("checkpoint_sha256") != trainings[seed]["checkpoint"]["sha256"]:
            _fail(f"training_matrix seed{seed} checkpoint SHA drifts")
        if row.get("training_receipt_sha256") != training_sources[seed].get("sha256"):
            _fail(f"training_matrix seed{seed} training receipt SHA drifts")
    return {
        "schema": TRAINING_MATRIX_SCHEMA,
        "status": "bound",
        "runs": list(SEEDS),
        "shared_config": dict(shared),
    }


def _empty_side_effects() -> dict[str, Any]:
    return {
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
    }


def evaluate_payloads(
    training_receipts: Mapping[int, Mapping[str, Any]],
    rollout_receipts: Mapping[int, Mapping[str, Any]],
    *,
    training_sources: Mapping[int, Mapping[str, Any]] | None = None,
    rollout_sources: Mapping[int, Mapping[str, Any]] | None = None,
    training_matrix: Mapping[str, Any] | None = None,
    training_matrix_source: Mapping[str, Any] | None = None,
    source_errors: Sequence[str] = (),
) -> dict[str, Any]:
    """Evaluate a three-seed payload set and always return a JSON-safe report."""

    training_sources = dict(training_sources or {
        seed: _source_ref_for_payload(training_receipts[seed], f"synthetic://training/{seed}.json")
        for seed in training_receipts
    })
    rollout_sources = dict(rollout_sources or {
        seed: _source_ref_for_payload(rollout_receipts[seed], f"synthetic://rollout/{seed}.json")
        for seed in rollout_receipts
    })
    errors = list(source_errors)
    checks: list[dict[str, Any]] = []
    expected_set = set(SEEDS)
    training_set = set(training_receipts)
    rollout_set = set(rollout_receipts)
    checks.append(_check(
        "training_seed_set_exact",
        training_set == expected_set,
        "training receipt set must contain exactly seeds 17, 29, and 43",
        observed=sorted(training_set),
        expected=list(SEEDS),
    ))
    checks.append(_check(
        "rollout_seed_set_exact",
        rollout_set == expected_set,
        "rollout receipt set must contain exactly seeds 17, 29, and 43",
        observed=sorted(rollout_set),
        expected=list(SEEDS),
    ))
    if training_set != expected_set:
        errors.append(f"training seed set drift: observed {sorted(training_set)} expected {list(SEEDS)}")
    if rollout_set != expected_set:
        errors.append(f"rollout seed set drift: observed {sorted(rollout_set)} expected {list(SEEDS)}")

    normalized_training: dict[int, dict[str, Any]] = {}
    normalized_rollout: dict[int, dict[str, Any]] = {}
    seed_rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        row: dict[str, Any] = {
            "seed": seed,
            "status": "blocked",
            "training": {
                "status": "missing",
                "source": training_sources.get(seed),
            },
            "rollout": {
                "status": "missing",
                "source": rollout_sources.get(seed),
            },
            "checks": [],
            "blocked_reasons": [],
        }
        if seed in training_receipts:
            try:
                normalized_training[seed] = validate_training_receipt(training_receipts[seed], seed)
                row["training"] = {
                    "status": "bound",
                    "source": training_sources.get(seed),
                    "projection": normalized_training[seed],
                }
                row["checks"].append(_check(
                    "training_receipt_schema_and_completion",
                    True,
                    "bounded core.training.v1 receipt is complete",
                ))
            except Exception as error:
                message = str(error)
                errors.append(f"seed{seed} training: {message}")
                row["training"] = {
                    "status": "rejected",
                    "source": training_sources.get(seed),
                    "error": message,
                }
                row["blocked_reasons"].append(message)
        else:
            message = f"missing training receipt for seed {seed}"
            errors.append(message)
            row["blocked_reasons"].append(message)

        if seed in rollout_receipts and seed in normalized_training:
            try:
                normalized_rollout[seed] = validate_rollout_receipt(
                    rollout_receipts[seed],
                    seed,
                    normalized_training[seed],
                    training_sources.get(seed),
                )
                row["rollout"] = {
                    "status": "bound_terminal",
                    "source": rollout_sources.get(seed),
                    "projection": normalized_rollout[seed],
                }
                row["checks"].append(_check(
                    "terminal_rollout_receipt_schema_and_completion",
                    True,
                    "bounded hidden16 terminal rollout summary is complete",
                ))
            except Exception as error:
                message = str(error)
                errors.append(f"seed{seed} rollout: {message}")
                row["rollout"] = {
                    "status": "rejected",
                    "source": rollout_sources.get(seed),
                    "observed": _observed_rollout_projection(rollout_receipts[seed]),
                    "error": message,
                }
                row["blocked_reasons"].append(message)
        elif seed not in rollout_receipts:
            message = f"missing terminal rollout receipt for seed {seed}"
            errors.append(message)
            row["blocked_reasons"].append(message)
        else:
            message = f"rollout for seed {seed} cannot bind until training receipt is valid"
            errors.append(message)
            row["blocked_reasons"].append(message)
        seed_rows.append(row)

    if normalized_training:
        reference_config = normalized_training[min(normalized_training)]["shared_config"]
        config_match = all(
            canonical_json(item["shared_config"]) == canonical_json(reference_config)
            for item in normalized_training.values()
        ) and len(normalized_training) == len(SEEDS)
    else:
        reference_config = None
        config_match = False
    checks.append(_check(
        "shared_training_model_config",
        config_match,
        "all three training receipts share one graph_raw hidden16 configuration",
        observed=reference_config,
        expected="one identical shared config across all three seeds",
    ))
    if not config_match:
        errors.append("training receipts do not provide one identical shared model configuration")

    checkpoint_match = True
    rollout_config_match = True
    output_prefixes: list[str] = []
    for seed in SEEDS:
        training = normalized_training.get(seed)
        rollout = normalized_rollout.get(seed)
        row = seed_rows[SEEDS.index(seed)]
        if training is None or rollout is None:
            checkpoint_match = False
            rollout_config_match = False
            continue
        if rollout["checkpoint"] != {
            "path": training["checkpoint"]["path"],
            "sha256": training["checkpoint"]["sha256"],
            "update": EXPECTED_UPDATES,
        }:
            checkpoint_match = False
            message = f"seed{seed} rollout checkpoint path/SHA drift"
            errors.append(message)
            row["blocked_reasons"].append(message)
        expected_rollout_config = {
            "model_kind": EXPECTED_MODEL,
            "hidden": EXPECTED_HIDDEN,
            "updates": EXPECTED_UPDATES,
            "centers_per_update": 256,
            "learning_rate": 0.001,
            "max_neighbors": 192,
            "normalization_source_split": "train",
            "normalization_transitions": 16,
            "target_normalization": "raw_dual_increment_train_shared",
            "split": "test",
            "maximum_steps": EXPECTED_TRANSITIONS,
            "diagnostic": True,
            "autonomous": True,
            "future_state_inputs": False,
        }
        if rollout["config"] != expected_rollout_config:
            rollout_config_match = False
            message = f"seed{seed} rollout model/config drift"
            errors.append(message)
            row["blocked_reasons"].append(message)
        output_prefixes.append(rollout["output_identity"]["prefix"])
        row["checks"].extend([
            _check("training_rollout_model_seed_hidden_updates_binding", True, "training and terminal summary agree"),
            _check("training_rollout_checkpoint_path_sha_binding", rollout["checkpoint"] == {
                "path": training["checkpoint"]["path"],
                "sha256": training["checkpoint"]["sha256"],
                "update": EXPECTED_UPDATES,
            }, "checkpoint path and SHA are exact"),
            _check("terminal_835_transitions_836_frames", True, "terminal summary is complete"),
            _check("fresh_output_identity", True, "derived evaluation/trajectory/progress namespace is fresh"),
        ])
    unique_outputs = len(output_prefixes) == len(set(output_prefixes)) == len(SEEDS)
    checks.append(_check(
        "fresh_output_identity_unique_across_seeds",
        unique_outputs,
        "each seed has a distinct fresh output prefix",
        observed=sorted(output_prefixes),
        expected="three distinct prefixes",
    ))
    if not unique_outputs:
        errors.append("rollout output prefixes are missing or reused across seeds")
    if not checkpoint_match:
        errors.append("training/rollout checkpoint path+SHA binding is incomplete")
    if not rollout_config_match:
        errors.append("terminal rollout model/config binding is incomplete")

    matrix_projection: dict[str, Any] | None = None
    matrix_ok = True
    if training_matrix is None:
        matrix_ok = False
        errors.append("missing training matrix receipt")
    else:
        try:
            matrix_projection = _validate_training_matrix(
                training_matrix,
                training_sources,
                normalized_training,
            )
        except Exception as error:
            matrix_ok = False
            errors.append(f"training matrix: {error}")
    checks.append(_check(
        "training_matrix_receipt_binding",
        matrix_ok,
        "the compact three-seed training matrix agrees with each bounded training receipt",
    ))

    all_bound = (
        not errors
        and training_set == expected_set
        and rollout_set == expected_set
        and len(normalized_training) == len(SEEDS)
        and len(normalized_rollout) == len(SEEDS)
        and config_match
        and checkpoint_match
        and rollout_config_match
        and unique_outputs
        and matrix_ok
    )
    for row in seed_rows:
        if (
            row["training"]["status"] == "bound"
            and row["rollout"]["status"] == "bound_terminal"
            and all(item["passed"] for item in row["checks"] if "passed" in item)
        ):
            row["status"] = "bound_terminal_diagnostic"

    for row in seed_rows:
        if row["status"] == "blocked" and not row["blocked_reasons"]:
            row["blocked_reasons"].append("seed is not fully bound")

    deduped_errors = list(dict.fromkeys(errors))
    report: dict[str, Any] = {
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
            "model_kind": EXPECTED_MODEL,
            "hidden": EXPECTED_HIDDEN,
            "updates": EXPECTED_UPDATES,
            "seeds": list(SEEDS),
            "expected_transitions": EXPECTED_TRANSITIONS,
            "expected_frames": EXPECTED_FRAMES,
            "case_id": EXPECTED_CASE_ID,
            "terminal_status": "completed",
            "fresh_output_identity": True,
        },
        "shared_training_config": reference_config,
        "training_matrix": matrix_projection,
        "seed_matrix": seed_rows,
        "checks": checks,
        "blocked_reasons": deduped_errors,
        "side_effects": _empty_side_effects(),
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "manifest_opened": False,
            "case_hdf5_opened": False,
            "checkpoint_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_opened": False,
            "runtime_started": False,
            "gpu_started": False,
            "worker_started": False,
        },
        "training_sources": {str(seed): training_sources.get(seed) for seed in SEEDS},
        "rollout_sources": {str(seed): rollout_sources.get(seed) for seed in SEEDS},
        "training_matrix_source": training_matrix_source,
        "interpretation": (
            "This is a bounded JSON consistency binding only.  It cannot validate HDF5 content, "
            "open a checkpoint or progress file, authorize a runtime, change a denominator, or "
            "produce T1/T2/formal qualification credit."
        ),
    }
    return report


def _parse_seed_paths(values: Sequence[str], label: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"{label} must use SEED=PATH: {raw}")
        seed_text, path_text = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise SystemExit(f"{label} has invalid seed: {raw}") from error
        if seed in result or seed not in SEEDS:
            raise SystemExit(f"{label} seed must be unique and one of {SEEDS}: {raw}")
        result[seed] = Path(path_text)
    return result


def build_report(
    lab_root: Path | str = LAB_ROOT,
    *,
    training_matrix_path: Path | str = DEFAULT_TRAINING_MATRIX,
    training_paths: Mapping[int, Path | str] = DEFAULT_TRAINING,
    rollout_paths: Mapping[int, Path | str] = DEFAULT_ROLLOUT,
    observed_at_utc: str = DEFAULT_OBSERVED_AT_UTC,
) -> dict[str, Any]:
    """Read only bounded inputs and build a deterministic fail-closed report."""

    root = Path(lab_root).resolve()
    training_receipts: dict[int, Mapping[str, Any]] = {}
    rollout_receipts: dict[int, Mapping[str, Any]] = {}
    training_sources: dict[int, Mapping[str, Any]] = {}
    rollout_sources: dict[int, Mapping[str, Any]] = {}
    source_errors: list[str] = []
    for seed in SEEDS:
        path = training_paths.get(seed)
        if path is None:
            source_errors.append(f"missing configured training path for seed {seed}")
            continue
        try:
            payload, source = _read_bounded_json(root, path)
            training_receipts[seed] = payload
            training_sources[seed] = source
        except Exception as error:
            training_sources[seed] = _missing_ref(root, path)
            source_errors.append(f"seed{seed} training input: {error}")
    for seed in SEEDS:
        path = rollout_paths.get(seed)
        if path is None:
            source_errors.append(f"missing configured rollout path for seed {seed}")
            continue
        try:
            payload, source = _read_bounded_json(root, path)
            rollout_receipts[seed] = payload
            rollout_sources[seed] = source
        except Exception as error:
            rollout_sources[seed] = _missing_ref(root, path)
            source_errors.append(f"seed{seed} rollout input: {error}")

    matrix: Mapping[str, Any] | None = None
    matrix_source: Mapping[str, Any] | None = None
    try:
        matrix, matrix_source = _read_bounded_json(root, training_matrix_path)
    except Exception as error:
        matrix_source = _missing_ref(root, training_matrix_path)
        source_errors.append(f"training matrix input: {error}")

    report = evaluate_payloads(
        training_receipts,
        rollout_receipts,
        training_sources=training_sources,
        rollout_sources=rollout_sources,
        training_matrix=matrix,
        training_matrix_source=matrix_source,
        source_errors=source_errors,
    )
    report["observed_at_utc"] = observed_at_utc
    return report


def write_report(report: Mapping[str, Any], output: Path | str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(report) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--training-matrix", type=Path, default=DEFAULT_TRAINING_MATRIX)
    parser.add_argument("--training", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--rollout", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument(
        "--output",
        type=Path,
        default=LAB_ROOT / "reports/F3-GRAPH-RAW-HIDDEN16-CROSS-SEED-ROLLOUT-CONSISTENCY-V1-2026-09-28.json",
    )
    parser.add_argument("--observed-at-utc", default=DEFAULT_OBSERVED_AT_UTC)
    args = parser.parse_args(argv)
    training_paths = dict(DEFAULT_TRAINING)
    rollout_paths = dict(DEFAULT_ROLLOUT)
    if args.training:
        training_paths.update(_parse_seed_paths(args.training, "--training"))
    if args.rollout:
        rollout_paths.update(_parse_seed_paths(args.rollout, "--rollout"))
    report = build_report(
        args.root,
        training_matrix_path=args.training_matrix,
        training_paths=training_paths,
        rollout_paths=rollout_paths,
        observed_at_utc=args.observed_at_utc,
    )
    write_report(report, args.output)
    print(canonical_json(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
