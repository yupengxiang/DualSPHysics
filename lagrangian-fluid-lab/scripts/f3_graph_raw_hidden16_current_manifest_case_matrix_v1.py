#!/usr/bin/env python3
"""Build and verify a bounded F3 graph_raw hidden16 case matrix.

This is an additive, non-launching planner.  It opens only the current
canonical manifest and the already-bound graph_raw training-evidence JSON.
Checkpoint, evaluation, trajectory, progress, and case-HDF5 content are
never opened.  The output is a diagnostic-only identity matrix: every plan
is launch-blocked until a future executor independently admits fresh output
namespaces, VRAM/host-I/O capacity, and real terminal receipts.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL_KIND = "graph_raw"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
EXPECTED_CASE_COUNT = 32
GPU_COUNT = 8
BATCH_SIZE = 8
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 1 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
DATE_RE = re.compile(r"^20[0-9]{6}$")
CASE_ID_RE = re.compile(r"^F3_DEV_[0-9]{2}_[A-Za-z0-9p]+$")

SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.case_matrix.v1"
TRAINING_SCHEMA = "core.f3.graph_raw.hidden16.training_evidence_matrix.v1"
REPORT_ID = "f3-graph-raw-hidden16-current-manifest-case-matrix-v1"
TRAINING_REPORT_ID = "f3-graph-raw-hidden16-training-evidence-matrix-v1"
EXPLICIT_TRAINING_REPORT_ID = "f3-graph-raw-hidden16-current-manifest-explicit-training-receipts-v1"
TERMINAL_TRAINING_STATUSES = frozenset({"complete", "completed", "terminal_completed", "exited_successfully"})
EXPLICIT_RUN_ID_RE = re.compile(
    r"^(?:graph_raw-hidden16-seed(?P<legacy>17|29|43)|"
    r"f3-graph_raw500-hidden16-currentmanifest-seed(?P<v3>17|29|43)-20[0-9]{6}-v3)$"
)

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
    "model_kind": MODEL_KIND,
    "normalization_selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
    "normalization_source_split": "train",
    "normalization_target_reference": "raw_dual_increment_train_shared",
    "normalization_transitions": 16,
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


class MatrixError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing input."""


def _fail(message: str) -> None:
    raise MatrixError(f"fail-closed: {message}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    result = _string(value, name)
    if SHA256_RE.fullmatch(result) is None or len(set(result)) == 1:
        _fail(f"{name} must be a non-placeholder lowercase SHA-256 digest")
    return result


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if isinstance(expected, bool) and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}")


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


def _absolute_path(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        _fail(f"{name} must be absolute")
    normalized = os.path.normpath(str(candidate))
    if str(candidate) != normalized:
        _fail(f"{name} uses a lexical path alias")
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a path alias component")
    if normalized != "/" and normalized.endswith(os.sep):
        _fail(f"{name} has a trailing separator")
    return Path(normalized)


def _resolve_input(root: Path, value: Path | str, name: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return _absolute_path(candidate, name)
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a path alias component")
    return _absolute_path(root / candidate, name)


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size)


def _read_bounded_json(path: Path | str, *, name: str, max_bytes: int) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Read one bounded regular JSON file without following a symlink."""

    candidate = _absolute_path(path, name)
    try:
        before = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    if before.st_size > max_bytes:
        _fail(f"{name} exceeds bounded size {max_bytes}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    chunks: list[bytes] = []
    try:
        opened = os.fstat(fd)
        expected = _file_identity(before)
        if _file_identity(opened) != expected:
            _fail(f"{name} changed before bounded read")
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        closed = os.fstat(fd)
        if _file_identity(closed) != expected or total != before.st_size:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name} after read: {error}")
    if _file_identity(after) != _file_identity(before):
        _fail(f"{name} changed after bounded read")
    raw = b"".join(chunks)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, MatrixError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    payload = _mapping(payload, name)
    _walk_json(payload, name)
    return payload, {
        "path": str(candidate),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _canonical_sha(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        _fail(f"value cannot be canonically encoded: {error}")
    return hashlib.sha256(raw).hexdigest()


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    _exact(value, "diagnostic_only", True, name)
    for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
        if key in value:
            _exact(value, key, False, name)
    for key in ("credit", "qualification_credit"):
        if key in value:
            _exact(value, key, 0, name)


def _validate_case(case: Mapping[str, Any], index: int) -> dict[str, Any]:
    name = f"manifest.cases[{index}]"
    case_id = _string(case.get("case_id"), f"{name}.case_id")
    if CASE_ID_RE.fullmatch(case_id) is None:
        _fail(f"{name}.case_id is not an F3_DEV case identifier")
    if _string(case.get("physical_case_id"), f"{name}.physical_case_id") != case_id:
        _fail(f"{name}.physical_case_id is not bound to case_id")
    _exact(case, "family", "F3", name)
    split = _string(case.get("split"), f"{name}.split")
    if split not in {"train", "validation", "test"}:
        _fail(f"{name}.split is not supported")
    hdf5 = _string(case.get("hdf5"), f"{name}.hdf5")
    hdf5_path = Path(hdf5)
    if hdf5_path.is_absolute() or any(part in {".", ".."} for part in hdf5_path.parts):
        _fail(f"{name}.hdf5 must be relative and alias-free")
    return {
        "index": index,
        "case_id": case_id,
        "physical_case_id": case_id,
        "family": "F3",
        "split": split,
        "evaluation_role": _string(case.get("evaluation_role"), f"{name}.evaluation_role"),
        "hdf5": hdf5,
        "hdf5_sha256": _sha(case.get("sha256"), f"{name}.sha256"),
        "hdf5_bytes": _int(case.get("bytes"), f"{name}.bytes", minimum=1),
        "known_inputs_sha256": _sha(case.get("known_inputs_sha256"), f"{name}.known_inputs_sha256"),
        "lineage_group_id": _sha(case.get("lineage_group_id"), f"{name}.lineage_group_id"),
        "scope_id": _string(case.get("scope_id"), f"{name}.scope_id"),
    }


def _validate_manifest(payload: Mapping[str, Any], source: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _exact(payload, "schema", "core.dataset.v2", "manifest")
    _exact(payload, "case_count", EXPECTED_CASE_COUNT, "manifest")
    _exact(payload, "dataset_id", "F3_registered32_core_native_v2", "manifest")
    _exact(payload, "formal_release", False, "manifest")
    _exact(payload, "input_asset_policy", "content_addressed_compressed_npz", "manifest")
    source_manifest_sha = _sha(payload.get("source_manifest_sha256"), "manifest.source_manifest_sha256")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != EXPECTED_CASE_COUNT:
        _fail("manifest.cases must contain exactly 32 cases")
    cases = [_validate_case(_mapping(item, f"manifest.cases[{index}]"), index) for index, item in enumerate(raw_cases)]
    if len({case["case_id"] for case in cases}) != EXPECTED_CASE_COUNT:
        _fail("manifest case identifiers are not unique")
    if len({case["hdf5_sha256"] for case in cases}) != EXPECTED_CASE_COUNT:
        _fail("manifest case artifact identities are not unique")
    scopes = {case["scope_id"] for case in cases}
    if len(scopes) != 1:
        _fail("manifest cases must share exactly one scope_id")
    return cases, {
        "schema": payload["schema"],
        "dataset_id": payload["dataset_id"],
        "case_count": payload["case_count"],
        "formal_release": payload["formal_release"],
        "input_asset_policy": payload["input_asset_policy"],
        "source_manifest_sha256": source_manifest_sha,
        "scope_id": next(iter(scopes)),
        "raw": dict(source),
    }


def _declared_identity(value: Mapping[str, Any], name: str, *, schema: str | None = None, update: int | None = None) -> dict[str, Any]:
    path = _absolute_path(value.get("path"), f"{name}.path")
    digest = _sha(value.get("sha256"), f"{name}.sha256")
    result: dict[str, Any] = {"path": str(path), "sha256": digest}
    if "bytes" in value and value.get("bytes") is not None:
        result["bytes"] = _int(value.get("bytes"), f"{name}.bytes", minimum=1)
    if schema is not None:
        _exact(value, "schema", schema, name)
        result["schema"] = schema
    if update is not None:
        _exact(value, "update", update, name)
        result["update"] = update
    return result


def _validate_shared_config(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    expected_keys = set(STATIC_CONFIG)
    if set(value) != expected_keys:
        _fail(f"{name} keys drift")
    for key, expected in STATIC_CONFIG.items():
        if value.get(key) != expected:
            _fail(f"{name}.{key} drifts")
    return dict(value)


def _validate_training_evidence(payload: Mapping[str, Any], *, manifest_sha256: str, source: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _exact(payload, "schema", TRAINING_SCHEMA, "training_evidence")
    _exact(payload, "report_id", TRAINING_REPORT_ID, "training_evidence")
    _exact(payload, "status", "training_evidence_bound_diagnostic_only", "training_evidence")
    _exact(payload, "source_bound", True, "training_evidence")
    _exact(payload, "fail_closed", False, "training_evidence")
    _exact(payload, "diagnostic_only", True, "training_evidence")
    if "model" in payload:
        _exact(payload, "model", MODEL_KIND, "training_evidence")
    _zero_credit(payload, "training_evidence")
    expected_contract = _mapping(payload.get("expected_contract"), "training_evidence.expected_contract")
    _exact(expected_contract, "model_kind", MODEL_KIND, "training_evidence.expected_contract")
    _exact(expected_contract, "hidden", HIDDEN, "training_evidence.expected_contract")
    _exact(expected_contract, "updates", UPDATES, "training_evidence.expected_contract")
    _exact(expected_contract, "evidence_status", "complete", "training_evidence.expected_contract")
    contract_config = _mapping(expected_contract.get("shared_config"), "training_evidence.expected_contract.shared_config")
    for key, expected in STATIC_CONFIG.items():
        if key in contract_config and contract_config.get(key) != expected:
            _fail(f"training_evidence.expected_contract.shared_config.{key} drifts")
    runs_value = payload.get("runs")
    if not isinstance(runs_value, list) or len(runs_value) != len(SEEDS):
        _fail("training_evidence.runs must contain exactly three runs")
    runs: list[dict[str, Any]] = []
    seen_seeds: set[int] = set()
    seen_receipts: set[str] = set()
    seen_checkpoints: set[str] = set()
    shared_configs: list[dict[str, Any]] = []
    for index, item in enumerate(runs_value):
        row = _mapping(item, f"training_evidence.runs[{index}]")
        seed = _int(row.get("seed"), f"training_evidence.runs[{index}].seed")
        if seed not in SEEDS or seed in seen_seeds:
            _fail("training evidence seed set must be exactly 17, 29, 43")
        seen_seeds.add(seed)
        _exact(row, "status", "bound_complete", f"training_evidence.runs[{index}]")
        source_record = _mapping(row.get("source"), f"training_evidence.runs[{index}].source")
        source_identity = _declared_identity(
            source_record,
            f"training_evidence.runs[{index}].source",
            schema="core.training.v1",
        )
        _exact(source_record, "opened", True, f"training_evidence.runs[{index}].source")
        evidence = _mapping(row.get("evidence"), f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "schema", "core.training.v1", f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "evidence_status", "complete", f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "model_kind", MODEL_KIND, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "hidden", HIDDEN, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "seed", seed, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "updates", UPDATES, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "manifest_sha256", manifest_sha256, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "formal_eligible", False, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "qualification_credit", 0, f"training_evidence.runs[{index}].evidence")
        run_id = f"graph_raw-hidden16-seed{seed}"
        _exact(evidence, "run_id", run_id, f"training_evidence.runs[{index}].evidence")
        parameter_count = _int(evidence.get("parameter_count"), f"training_evidence.runs[{index}].evidence.parameter_count", minimum=1)
        checkpoint = _declared_identity(
            _mapping(evidence.get("checkpoint"), f"training_evidence.runs[{index}].evidence.checkpoint"),
            f"training_evidence.runs[{index}].evidence.checkpoint",
            schema="core.checkpoint.v1",
            update=UPDATES,
        )
        initialization = _mapping(evidence.get("initialization"), f"training_evidence.runs[{index}].evidence.initialization")
        _exact(initialization, "schema", "core.training.initialization_evidence.v1", f"training_evidence.runs[{index}].evidence.initialization")
        _exact(initialization, "status", "captured", f"training_evidence.runs[{index}].evidence.initialization")
        initialization_digest = _sha(initialization.get("parameter_digest"), f"training_evidence.runs[{index}].evidence.initialization.parameter_digest")
        _exact(initialization, "parameter_count", parameter_count, f"training_evidence.runs[{index}].evidence.initialization")
        normalization = _mapping(evidence.get("normalization"), f"training_evidence.runs[{index}].evidence.normalization")
        _exact(normalization, "schema", "core.training.normalization_evidence.v1", f"training_evidence.runs[{index}].evidence.normalization")
        _exact(normalization, "requested_maximum_transitions", 16, f"training_evidence.runs[{index}].evidence.normalization")
        _exact(normalization, "selected_transition_count", 16, f"training_evidence.runs[{index}].evidence.normalization")
        _exact(normalization, "selection_policy", STATIC_CONFIG["normalization_selection_policy"], f"training_evidence.runs[{index}].evidence.normalization")
        _exact(normalization, "source_split", "train", f"training_evidence.runs[{index}].evidence.normalization")
        _exact(normalization, "target_reference", STATIC_CONFIG["normalization_target_reference"], f"training_evidence.runs[{index}].evidence.normalization")
        _exact(normalization, "selection_seed", seed, f"training_evidence.runs[{index}].evidence.normalization")
        shared_config = _validate_shared_config(
            _mapping(evidence.get("shared_config"), f"training_evidence.runs[{index}].evidence.shared_config"),
            f"training_evidence.runs[{index}].evidence.shared_config",
        )
        shared_configs.append(shared_config)
        if source_identity["sha256"] in seen_receipts or checkpoint["sha256"] in seen_checkpoints:
            _fail("training receipt or checkpoint identity is duplicated")
        seen_receipts.add(source_identity["sha256"])
        seen_checkpoints.add(checkpoint["sha256"])
        runs.append({
            "seed": seed,
            "run_id": run_id,
            "training_receipt": source_identity,
            "checkpoint": checkpoint,
            "parameter_count": parameter_count,
            "initialization_parameter_digest": initialization_digest,
            "shared_config": shared_config,
        })
    if tuple(sorted(seen_seeds)) != SEEDS:
        _fail("training evidence does not cover exactly seeds 17, 29, 43")
    if any(_canonical_sha(config) != _canonical_sha(shared_configs[0]) for config in shared_configs[1:]):
        _fail("training evidence shared configuration drifts across seeds")
    return sorted(runs, key=lambda row: row["seed"]), {
        "schema": TRAINING_SCHEMA,
        "report_id": TRAINING_REPORT_ID,
        "status": payload["status"],
        "source_bound": True,
        "source": dict(source),
        "manifest_sha256": manifest_sha256,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seed_count": len(runs),
        "shared_config": dict(shared_configs[0]),
        "runs": runs,
    }


def _validate_explicit_receipt(
    payload: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    seed: int,
    manifest_sha256: str,
    status_hint: str | None,
) -> dict[str, Any]:
    """Project one explicit bounded terminal training receipt.

    The receipt itself is limited to MAX_METADATA_BYTES by the caller.  This
    function only consumes declared JSON metadata; checkpoint bytes and all
    runtime artifacts remain unopened.
    """

    name = f"explicit_training[{seed}]"
    _exact(payload, "schema", "core.training.v1", name)
    observed_status = payload.get("evidence_status", payload.get("status"))
    if status_hint is not None and status_hint not in TERMINAL_TRAINING_STATUSES:
        _fail(f"{name} has non-terminal explicit status {status_hint!r}")
    if observed_status not in TERMINAL_TRAINING_STATUSES:
        _fail(f"{name} is not terminal: status={observed_status!r}")
    if status_hint is not None and observed_status not in TERMINAL_TRAINING_STATUSES:
        _fail(f"{name} receipt status disagrees with terminal status hint")
    _exact(payload, "model_kind", MODEL_KIND, name)
    _exact(payload, "seed", seed, name)
    _exact(payload, "completed_updates", UPDATES, name)
    _exact(payload, "checkpoint_verified", True, name)
    parameter_count = _int(payload.get("parameter_count"), f"{name}.parameter_count", minimum=1)
    config = _mapping(payload.get("config"), f"{name}.config")
    for key, expected in STATIC_CONFIG.items():
        if key in config and config.get(key) != expected:
            _fail(f"{name}.config.{key} drifts")
    _exact(config, "manifest_sha256", manifest_sha256, f"{name}.config")
    _exact(config, "hidden", HIDDEN, f"{name}.config")
    _exact(config, "model_kind", MODEL_KIND, f"{name}.config")
    _exact(config, "updates", UPDATES, f"{name}.config")
    for key in ("seed", "paired_seed", "sampler_seed"):
        if key in config:
            _exact(config, key, seed, f"{name}.config")
    run_id = _string(payload.get("run_id"), f"{name}.run_id")
    if EXPLICIT_RUN_ID_RE.fullmatch(run_id) is None:
        _fail(f"{name}.run_id is not an accepted hidden16 or v3 identity")
    if config.get("run_id") != run_id:
        _fail(f"{name}.config.run_id does not match receipt run_id")
    run_match = EXPLICIT_RUN_ID_RE.fullmatch(run_id)
    if run_match is None or int(run_match.group("legacy") or run_match.group("v3")) != seed:
        _fail(f"{name}.run_id seed binding drifts")

    checkpoint_value = _mapping(payload.get("checkpoint"), f"{name}.checkpoint")
    checkpoint_schema = checkpoint_value.get("schema", "core.checkpoint.v1")
    _exact({"schema": checkpoint_schema}, "schema", "core.checkpoint.v1", f"{name}.checkpoint")
    checkpoint_update = checkpoint_value.get("update", UPDATES)
    if checkpoint_update != UPDATES:
        _fail(f"{name}.checkpoint.update must be {UPDATES}")
    checkpoint = _declared_identity(
        {**checkpoint_value, "schema": checkpoint_schema, "update": checkpoint_update},
        f"{name}.checkpoint",
        schema="core.checkpoint.v1",
        update=UPDATES,
    )

    evidence = _mapping(payload.get("evidence"), f"{name}.evidence")
    _exact(evidence, "schema", "core.training.evidence.v1", f"{name}.evidence")
    _exact(evidence, "status", "complete", f"{name}.evidence")
    initialization = _mapping(evidence.get("initialization"), f"{name}.evidence.initialization")
    _exact(initialization, "schema", "core.training.initialization_evidence.v1", f"{name}.evidence.initialization")
    _exact(initialization, "status", "captured", f"{name}.evidence.initialization")
    _exact(initialization, "parameter_count", parameter_count, f"{name}.evidence.initialization")
    initialization_digest = _sha(initialization.get("parameter_digest"), f"{name}.evidence.initialization.parameter_digest")
    normalization = _mapping(evidence.get("normalization"), f"{name}.evidence.normalization")
    _exact(normalization, "schema", "core.training.normalization_evidence.v1", f"{name}.evidence.normalization")
    _exact(normalization, "requested_maximum_transitions", 16, f"{name}.evidence.normalization")
    _exact(normalization, "selected_transition_count", 16, f"{name}.evidence.normalization")
    _exact(normalization, "selection_policy", STATIC_CONFIG["normalization_selection_policy"], f"{name}.evidence.normalization")
    _exact(normalization, "source_split", "train", f"{name}.evidence.normalization")
    _exact(normalization, "target_reference", STATIC_CONFIG["normalization_target_reference"], f"{name}.evidence.normalization")
    if "selection_seed" in normalization:
        _exact(normalization, "selection_seed", seed, f"{name}.evidence.normalization")

    return {
        "seed": seed,
        "run_id": run_id,
        "training_receipt": dict(source),
        "checkpoint": checkpoint,
        "parameter_count": parameter_count,
        "initialization_parameter_digest": initialization_digest,
        "shared_config": dict(STATIC_CONFIG),
        "status": "explicit_terminal_bound",
        "terminal_status": observed_status,
    }


def _validate_explicit_receipts(
    payloads: Mapping[int, Mapping[str, Any]],
    sources: Mapping[int, Mapping[str, Any]],
    statuses: Mapping[int, str],
    *,
    manifest_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if tuple(sorted(payloads)) != SEEDS or tuple(sorted(sources)) != SEEDS or tuple(sorted(statuses)) != SEEDS:
        _fail("explicit training receipt/status bindings must cover exactly seeds 17, 29, 43")
    runs = [
        _validate_explicit_receipt(
            payloads[seed],
            source={**sources[seed], "schema": "core.training.v1", "opened": True},
            seed=seed,
            manifest_sha256=manifest_sha256,
            status_hint=statuses[seed],
        )
        for seed in SEEDS
    ]
    receipt_shas = [str(run["training_receipt"]["sha256"]) for run in runs]
    checkpoint_shas = [str(run["checkpoint"]["sha256"]) for run in runs]
    if len(set(receipt_shas)) != len(SEEDS) or len(set(checkpoint_shas)) != len(SEEDS):
        _fail("explicit training receipt/checkpoint identities are not unique")
    return runs, {
        "schema": "core.f3.graph_raw.hidden16.current_manifest.explicit_training_receipts.v1",
        "report_id": EXPLICIT_TRAINING_REPORT_ID,
        "status": "explicit_terminal_receipts_bound",
        "source_bound": True,
        "source": {
            "mode": "explicit_seed_receipts",
            "seed_sources": {str(seed): dict(sources[seed]) for seed in SEEDS},
        },
        "manifest_sha256": manifest_sha256,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seed_count": len(runs),
        "shared_config": dict(STATIC_CONFIG),
        "runs": runs,
    }


def _case_slug(case_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", case_id).strip("-").lower()
    if not slug:
        _fail("case identifier produced an empty namespace slug")
    return slug


def _planned_nonce(*, manifest_sha256: str, case_id: str, seed: int, run_id: str) -> str:
    material = f"{REPORT_ID}|{manifest_sha256}|{case_id}|{seed}|{run_id}".encode()
    nonce = hashlib.sha256(material).hexdigest()[:32]
    if NONCE_RE.fullmatch(nonce) is None or int(nonce, 16) == 0:
        _fail("deterministic plan nonce is invalid")
    return nonce


def _command_digest(command: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> str:
    return _canonical_sha({"argv": list(command), "cwd": str(cwd), "env_overrides": dict(env)})


def _plan_for(*, root: Path, manifest_path: Path, manifest_sha256: str, case: Mapping[str, Any], run: Mapping[str, Any], ordinal: int, plan_date: str, python_executable: Path) -> dict[str, Any]:
    seed = int(run["seed"])
    case_id = str(case["case_id"])
    nonce = _planned_nonce(manifest_sha256=manifest_sha256, case_id=case_id, seed=seed, run_id=str(run["run_id"]))
    gpu_index = ordinal % GPU_COUNT
    namespace = Path(
        "/tmp"
        f"/f3-graph-raw500-hidden16-currentmanifest-case-matrix-{plan_date}-"
        f"case{int(case['index']):02d}-{_case_slug(case_id)}-seed{seed}-full835-{nonce}"
    )
    outputs = {
        "evaluation": namespace / "evaluation.json",
        "trajectory": namespace / "trajectory.h5",
        "progress": namespace / "progress.json",
        "validator": namespace / "hdf5-validation.json",
        "artifact_identity": namespace / "artifact-identity.json",
        "trajectory_metadata": namespace / "trajectory-metadata.json",
        "process_proof": root / "reports" / f"F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-CASE{int(case['index']):02d}-SEED{seed}-PROCESS-EXIT-PROOF-V1.json",
    }
    command = (
        str(python_executable),
        "-u",
        str(root / "scripts" / "core_learning.py"),
        "evaluate",
        "--manifest",
        str(manifest_path),
        "--data-root",
        str(root),
        "--checkpoint",
        str(run["checkpoint"]["path"]),
        "--case-id",
        case_id,
        "--split",
        str(case["split"]),
        "--maximum-steps",
        str(TRANSITIONS),
        "--chunk-size",
        "34560",
        "--device",
        "cuda:0",
        "--progress-every",
        "25",
        "--trajectory-output",
        str(outputs["trajectory"]),
        "--progress-output",
        str(outputs["progress"]),
        "--output",
        str(outputs["evaluation"]),
        "--diagnostic",
    )
    env = {"CUDA_VISIBLE_DEVICES": str(gpu_index), "PYTHONDONTWRITEBYTECODE": "1"}
    return {
        "job_id": f"f3-graph-raw-hidden16-current-manifest-case-matrix-case{int(case['index']):02d}-seed{seed}",
        "ordinal": ordinal,
        "batch_index": ordinal // BATCH_SIZE,
        "batch_slot": ordinal % BATCH_SIZE,
        "gpu_index": gpu_index,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seed": seed,
        "run_id": run["run_id"],
        "case_index": case["index"],
        "case_id": case_id,
        "physical_case_id": case["physical_case_id"],
        "split": case["split"],
        "evaluation_role": case["evaluation_role"],
        "case_hdf5_metadata": {"path": case["hdf5"], "sha256": case["hdf5_sha256"], "bytes": case["hdf5_bytes"]},
        "known_inputs_sha256": case["known_inputs_sha256"],
        "manifest_sha256": manifest_sha256,
        "training_receipt": dict(run["training_receipt"]),
        "checkpoint": dict(run["checkpoint"]),
        "training_config": dict(run["shared_config"]),
        "output_namespace": str(namespace),
        "namespace_nonce": nonce,
        "namespace_freshness_attested": False,
        "namespace_reuse_allowed": False,
        "command": list(command),
        "cwd": str(root),
        "env_overrides": env,
        "command_sha256": _command_digest(command, cwd=root, env=env),
        "outputs": {key: str(value) for key, value in outputs.items()},
        "status": "dry_run_ready",
        "launch_allowed": False,
        "terminal_receipt_observed": False,
        "terminal_receipt_path": None,
        "resource_policy": {
            "gpu_sharing_allowed": True,
            "gpu_index_is_hint_only": True,
            "requires_future_free_vram_admission": True,
            "requires_future_cpu_io_admission": True,
            "kill_existing_processes": False,
            "restart_existing_processes": False,
        },
        **ZERO_CREDIT,
        "zero_credit_only": True,
    }


def _validate_plan(plan: Mapping[str, Any], *, root: Path, manifest_path: Path, manifest_sha256: str) -> None:
    name = f"plans[{plan.get('ordinal', '?')}]"
    _exact(plan, "status", "dry_run_ready", name)
    _exact(plan, "launch_allowed", False, name)
    _exact(plan, "terminal_receipt_observed", False, name)
    _zero_credit(plan, name)
    _exact(plan, "model_kind", MODEL_KIND, name)
    _exact(plan, "hidden", HIDDEN, name)
    _exact(plan, "updates", UPDATES, name)
    _exact(plan, "manifest_sha256", manifest_sha256, name)
    seed = _int(plan.get("seed"), f"{name}.seed")
    if seed not in SEEDS:
        _fail(f"{name}.seed is outside the exact seed set")
    run_id = _string(plan.get("run_id"), f"{name}.run_id")
    run_match = EXPLICIT_RUN_ID_RE.fullmatch(run_id)
    if run_match is None or int(run_match.group("legacy") or run_match.group("v3")) != seed:
        _fail(f"{name}.run_id is not bound to seed {seed}")
    case_id = _string(plan.get("case_id"), f"{name}.case_id")
    if CASE_ID_RE.fullmatch(case_id) is None:
        _fail(f"{name}.case_id is invalid")
    nonce = _string(plan.get("namespace_nonce"), f"{name}.namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None:
        _fail(f"{name}.namespace_nonce is invalid")
    namespace = _absolute_path(plan.get("output_namespace"), f"{name}.output_namespace")
    marker = f"case{int(plan.get('case_index')):02d}-{_case_slug(case_id)}-seed{seed}-full835-"
    if not namespace.name.startswith("f3-graph-raw500-hidden16-currentmanifest-case-matrix-") or marker not in namespace.name or not namespace.name.endswith(nonce):
        _fail(f"{name}.output_namespace is not bound to case, seed, full835, and nonce")
    command = plan.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        _fail(f"{name}.command must be a non-empty argv")
    env = _mapping(plan.get("env_overrides"), f"{name}.env_overrides")
    _exact(env, "CUDA_VISIBLE_DEVICES", str(plan.get("gpu_index")), f"{name}.env_overrides")
    _exact(env, "PYTHONDONTWRITEBYTECODE", "1", f"{name}.env_overrides")
    _exact(plan, "cwd", str(root), name)
    expected_digest = _command_digest(command, cwd=root, env={str(key): str(value) for key, value in env.items()})
    _exact(plan, "command_sha256", expected_digest, name)

    def command_value(flag: str) -> str:
        if command.count(flag) != 1 or command.index(flag) + 1 >= len(command):
            _fail(f"{name}.command must contain exactly one {flag} value")
        return command[command.index(flag) + 1]

    for flag, expected in (
        ("--manifest", str(manifest_path)),
        ("--data-root", str(root)),
        ("--checkpoint", str(_mapping(plan["checkpoint"], f"{name}.checkpoint")["path"])),
        ("--case-id", case_id),
        ("--split", str(plan["split"])),
        ("--maximum-steps", str(TRANSITIONS)),
        ("--trajectory-output", str(_mapping(plan["outputs"], f"{name}.outputs")["trajectory"])),
        ("--progress-output", str(_mapping(plan["outputs"], f"{name}.outputs")["progress"])),
        ("--output", str(_mapping(plan["outputs"], f"{name}.outputs")["evaluation"])),
    ):
        if command_value(flag) != expected:
            _fail(f"{name}.command {flag} binding drifted")
    if "evaluate" not in command or "--diagnostic" not in command:
        _fail(f"{name}.command is not a diagnostic evaluate command")
    checkpoint = _mapping(plan.get("checkpoint"), f"{name}.checkpoint")
    _exact(checkpoint, "schema", "core.checkpoint.v1", f"{name}.checkpoint")
    _exact(checkpoint, "update", UPDATES, f"{name}.checkpoint")
    _sha(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")
    training_receipt = _mapping(plan.get("training_receipt"), f"{name}.training_receipt")
    _declared_identity(training_receipt, f"{name}.training_receipt", schema="core.training.v1")
    training_config = _mapping(plan.get("training_config"), f"{name}.training_config")
    _validate_shared_config(training_config, f"{name}.training_config")
    outputs = _mapping(plan.get("outputs"), f"{name}.outputs")
    for key in ("evaluation", "trajectory", "progress", "validator", "artifact_identity", "trajectory_metadata"):
        if _absolute_path(outputs.get(key), f"{name}.outputs.{key}").parent != namespace:
            _fail(f"{name}.outputs.{key} escaped output namespace")
    if _absolute_path(outputs.get("process_proof"), f"{name}.outputs.process_proof").parent != root / "reports":
        _fail(f"{name}.outputs.process_proof escaped root reports")


def validate_report(report: Mapping[str, Any]) -> None:
    _exact(report, "schema", SCHEMA, "report")
    _exact(report, "report_id", REPORT_ID, "report")
    _exact(report, "status", "dry_run_matrix_ready", "report")
    _exact(report, "source_bound", True, "report")
    _exact(report, "launch_allowed", False, "report")
    _zero_credit(report, "report")
    expected = _mapping(report.get("expected_contract"), "report.expected_contract")
    for key, value in (("case_count", EXPECTED_CASE_COUNT), ("seed_count", len(SEEDS)), ("matrix_job_count", EXPECTED_CASE_COUNT * len(SEEDS)), ("hidden", HIDDEN), ("updates", UPDATES), ("transitions", TRANSITIONS), ("frames", FRAMES)):
        _exact(expected, key, value, "report.expected_contract")
    _exact(expected, "model_kind", MODEL_KIND, "report.expected_contract")
    _exact(expected, "zero_credit_only", True, "report.expected_contract")
    manifest = _mapping(report.get("manifest"), "report.manifest")
    manifest_sha = _sha(manifest.get("canonical_sha256"), "report.manifest.canonical_sha256")
    _exact(manifest, "case_count", EXPECTED_CASE_COUNT, "report.manifest")
    manifest_raw = _mapping(manifest.get("raw"), "report.manifest.raw")
    manifest_path = _absolute_path(manifest_raw.get("path"), "report.manifest.raw.path")
    _sha(manifest_raw.get("sha256"), "report.manifest.raw.sha256")
    _int(manifest_raw.get("bytes"), "report.manifest.raw.bytes", minimum=1)
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        _fail("report.cases must contain exactly 32 cases")
    case_ids = {str(_mapping(case, "report.cases[]")["case_id"]) for case in cases}
    if len(case_ids) != EXPECTED_CASE_COUNT:
        _fail("report case identifiers are not unique")
    training = _mapping(report.get("training_identity"), "report.training_identity")
    _exact(training, "manifest_sha256", manifest_sha, "report.training_identity")
    _exact(training, "model_kind", MODEL_KIND, "report.training_identity")
    _exact(training, "hidden", HIDDEN, "report.training_identity")
    _exact(training, "updates", UPDATES, "report.training_identity")
    training_binding = _mapping(report.get("training_binding"), "report.training_binding")
    mode = _string(training_binding.get("mode"), "report.training_binding.mode")
    if mode not in {"historical_matrix", "explicit_seed_receipts"}:
        _fail("report.training_binding.mode is unsupported")
    _exact(training_binding, "pre_terminal_fail_closed", True, "report.training_binding")
    _exact(training_binding, "max_json_bytes", MAX_METADATA_BYTES, "report.training_binding")
    plans = report.get("plans")
    if not isinstance(plans, list) or len(plans) != EXPECTED_CASE_COUNT * len(SEEDS):
        _fail("report.plans must contain exactly 96 plans")
    namespaces: set[str] = set()
    nonces: set[str] = set()
    commands: set[str] = set()
    combinations: set[tuple[str, int]] = set()
    root = _absolute_path(report.get("root"), "report.root")
    for value in plans:
        plan = _mapping(value, "report.plans[]")
        _validate_plan(plan, root=root, manifest_path=manifest_path, manifest_sha256=manifest_sha)
        key = (str(plan["case_id"]), int(plan["seed"]))
        if key in combinations:
            _fail("report plans contain a duplicate case x seed combination")
        combinations.add(key)
        for collection, field in ((namespaces, "output_namespace"), (nonces, "namespace_nonce"), (commands, "command_sha256")):
            value_text = str(plan[field])
            if value_text in collection:
                _fail(f"report plan {field} is not unique")
            collection.add(value_text)
    if combinations != {(case_id, seed) for case_id in case_ids for seed in SEEDS}:
        _fail("report does not provide exact 32-case x 3-seed coverage")
    identity_rows = [
        {
            "job_id": plan["job_id"],
            "case_id": plan["case_id"],
            "seed": plan["seed"],
            "namespace": plan["output_namespace"],
            "nonce": plan["namespace_nonce"],
            "command_sha256": plan["command_sha256"],
        }
        for plan in plans
    ]
    _exact(report, "matrix_sha256", _canonical_sha(identity_rows), "report")
    receipts = _mapping(report.get("terminal_receipts"), "report.terminal_receipts")
    _exact(receipts, "required_count", 96, "report.terminal_receipts")
    _exact(receipts, "observed_count", 0, "report.terminal_receipts")
    _exact(receipts, "missing_count", 96, "report.terminal_receipts")
    _exact(receipts, "launch_allowed", False, "report.terminal_receipts")
    _exact(receipts, "status", "missing_real_terminal_receipts_fail_closed", "report.terminal_receipts")
    boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
    _exact(boundary, "bounded_manifest_json_opened", True, "report.input_boundary")
    _exact(boundary, "bounded_training_evidence_json_opened", mode == "historical_matrix", "report.input_boundary")
    _exact(boundary, "bounded_explicit_training_receipts_json_opened", mode == "explicit_seed_receipts", "report.input_boundary")
    for key in ("checkpoint_content_opened", "checkpoint_lstat_performed", "evaluation_content_opened", "trajectory_content_opened", "trajectory_hdf5_opened", "hdf5_content_opened", "hdf5_lstat_performed", "case_hdf5_opened", "gpu_started", "queue_started", "runtime_started"):
        _exact(boundary, key, False, "report.input_boundary")
    side_effects = _mapping(report.get("side_effects"), "report.side_effects")
    for key in ("processes_started", "processes_stopped", "processes_restarted", "registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"):
        _exact(side_effects, key, 0, "report.side_effects")


def build_report(
    *,
    root: Path | str,
    manifest: Path | str,
    training_evidence: Path | str,
    plan_date: str,
    python_executable: Path | str | None = None,
    seed_receipts: Mapping[int, Path | str] | None = None,
    seed_statuses: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    root_path = _absolute_path(root, "root")
    if DATE_RE.fullmatch(plan_date) is None:
        _fail("plan_date must be YYYYMMDD")
    manifest_path = _resolve_input(root_path, manifest, "manifest")
    manifest_payload, manifest_source = _read_bounded_json(manifest_path, name="manifest", max_bytes=MAX_MANIFEST_BYTES)
    manifest_sha256 = _canonical_sha(manifest_payload)
    cases, manifest_meta = _validate_manifest(manifest_payload, manifest_source)
    explicit_binding = seed_receipts is not None or seed_statuses is not None
    if explicit_binding:
        receipt_paths = dict(seed_receipts or {})
        status_values = dict(seed_statuses or {})
        if tuple(sorted(receipt_paths)) != SEEDS:
            _fail("explicit training receipt paths must cover exactly seeds 17, 29, 43")
        if status_values and tuple(sorted(status_values)) != SEEDS:
            _fail("explicit training statuses must cover exactly seeds 17, 29, 43")
        # Check declared statuses before opening any receipt.  A running,
        # pending, unknown, or failed job must never be promoted to a bound
        # training identity or launchable case plan.
        for seed in SEEDS:
            status_hint = status_values.get(seed, "")
            if status_hint and status_hint not in TERMINAL_TRAINING_STATUSES:
                _fail(f"seed{seed} explicit status {status_hint!r} is non-terminal; receipt binding remains fail-closed")
        explicit_payloads: dict[int, Mapping[str, Any]] = {}
        explicit_sources: dict[int, Mapping[str, Any]] = {}
        for seed in SEEDS:
            receipt_path = _resolve_input(root_path, receipt_paths[seed], f"seed{seed}_receipt")
            payload, source = _read_bounded_json(receipt_path, name=f"seed{seed}_receipt", max_bytes=MAX_METADATA_BYTES)
            explicit_payloads[seed] = payload
            explicit_sources[seed] = source
            if not status_values[seed]:
                observed_status = payload.get("evidence_status", payload.get("status"))
                status_values[seed] = str(observed_status) if observed_status is not None else ""
        training_runs, training_identity = _validate_explicit_receipts(
            explicit_payloads,
            explicit_sources,
            status_values,
            manifest_sha256=manifest_sha256,
        )
    else:
        training_path = _resolve_input(root_path, training_evidence, "training_evidence")
        training_payload, training_source = _read_bounded_json(training_path, name="training_evidence", max_bytes=MAX_METADATA_BYTES)
        training_runs, training_identity = _validate_training_evidence(training_payload, manifest_sha256=manifest_sha256, source=training_source)
    python_path = _absolute_path(python_executable if python_executable is not None else root_path / ".venv" / "bin" / "python", "python_executable")
    runs_by_seed = {int(run["seed"]): run for run in training_runs}
    plans: list[dict[str, Any]] = []
    ordinal = 0
    for case in cases:
        for seed in SEEDS:
            plans.append(_plan_for(root=root_path, manifest_path=manifest_path, manifest_sha256=manifest_sha256, case=case, run=runs_by_seed[seed], ordinal=ordinal, plan_date=plan_date, python_executable=python_path))
            ordinal += 1
    identity_rows = [{"job_id": plan["job_id"], "case_id": plan["case_id"], "seed": plan["seed"], "namespace": plan["output_namespace"], "nonce": plan["namespace_nonce"], "command_sha256": plan["command_sha256"]} for plan in plans]
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "status": "dry_run_matrix_ready",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root_path),
        "source_bound": True,
        "launch_allowed": False,
        "matrix_sha256": _canonical_sha(identity_rows),
        **ZERO_CREDIT,
        "expected_contract": {
            "case_count": EXPECTED_CASE_COUNT,
            "seed_count": len(SEEDS),
            "seeds": list(SEEDS),
            "matrix_job_count": EXPECTED_CASE_COUNT * len(SEEDS),
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "batch_size": BATCH_SIZE,
            "gpu_count": GPU_COUNT,
            "bounded_json_only": True,
            "zero_credit_only": True,
        },
        "manifest": {
            "schema": manifest_meta["schema"],
            "dataset_id": manifest_meta["dataset_id"],
            "case_count": manifest_meta["case_count"],
            "canonical_sha256": manifest_sha256,
            "raw": dict(manifest_source),
            "source_manifest_sha256": manifest_meta["source_manifest_sha256"],
            "scope_id": manifest_meta["scope_id"],
            "formal_release": manifest_meta["formal_release"],
            "input_asset_policy": manifest_meta["input_asset_policy"],
        },
        "training_identity": training_identity,
        "training_binding": {
            "mode": "explicit_seed_receipts" if explicit_binding else "historical_matrix",
            "pre_terminal_fail_closed": True,
            "max_json_bytes": MAX_METADATA_BYTES,
            "explicit_statuses": {str(seed): status_values[seed] for seed in SEEDS} if explicit_binding else {},
            "note": "Explicit receipt paths are read only as bounded JSON metadata and only after all declared seed statuses are terminal.",
        },
        "cases": cases,
        "plans": plans,
        "coverage": {
            "exact_case_coverage": True,
            "exact_seed_coverage": True,
            "exact_case_seed_coverage": True,
            "cases": EXPECTED_CASE_COUNT,
            "seeds": list(SEEDS),
            "jobs": len(plans),
            "unique_namespaces": len({plan["output_namespace"] for plan in plans}),
            "unique_nonces": len({plan["namespace_nonce"] for plan in plans}),
            "unique_command_identities": len({plan["command_sha256"] for plan in plans}),
            "gpu_slots": {str(gpu): sum(plan["gpu_index"] == gpu for plan in plans) for gpu in range(GPU_COUNT)},
        },
        "scheduler": {
            "batch_size": BATCH_SIZE,
            "batch_count": len(plans) // BATCH_SIZE,
            "gpu_count": GPU_COUNT,
            "gpu_sharing_allowed": True,
            "free_vram_must_be_rechecked_before_execution": True,
            "existing_processes_must_not_be_killed_or_restarted": True,
            "planned_concurrency": BATCH_SIZE,
            "launches_performed": 0,
        },
        "terminal_receipts": {
            "required_count": len(plans),
            "observed_count": 0,
            "missing_count": len(plans),
            "status": "missing_real_terminal_receipts_fail_closed",
            "launch_allowed": False,
            "paths": [],
            "note": "No evaluator was started. Every future job needs an independent fresh namespace, natural exit, evaluator, validator, trajectory, and artifact identity receipt.",
        },
        "input_boundary": {
            "bounded_manifest_json_opened": True,
            "bounded_training_evidence_json_opened": not explicit_binding,
            "bounded_explicit_training_receipts_json_opened": explicit_binding,
            "checkpoint_content_opened": False,
            "checkpoint_lstat_performed": False,
            "evaluation_content_opened": False,
            "trajectory_content_opened": False,
            "trajectory_hdf5_opened": False,
            "hdf5_content_opened": False,
            "hdf5_lstat_performed": False,
            "case_hdf5_opened": False,
            "gpu_started": False,
            "queue_started": False,
            "runtime_started": False,
        },
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
        "checks": [
            {"check": "current_canonical_manifest_binding", "passed": True, "observed": manifest_sha256},
            {"check": "graph_raw_hidden16_training_identity", "passed": True, "observed": list(SEEDS)},
            {"check": "exact_32x3_matrix_coverage", "passed": True, "observed": len(plans)},
            {"check": "unique_namespace_nonce_command_identity", "passed": True, "observed": len(plans)},
            {"check": "diagnostic_only_zero_credit", "passed": True, "observed": True},
            {"check": "real_terminal_receipts", "passed": False, "observed": 0, "reason": "No evaluator was launched; missing receipts keep every plan fail-closed."},
        ],
        "blocked_reasons": ["real terminal receipts are absent; all 96 plans remain launch-blocked"],
        "interpretation": "This is a source-bound graph_raw hidden16 current-manifest dry-run identity matrix only. It is not terminal runtime evidence and cannot increase formal training, T1/T2, qualification, denominator, ledger, registry, gate, or completion counters.",
    }
    validate_report(report)
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report["coverage"], "report.coverage")
    terminal = _mapping(report["terminal_receipts"], "report.terminal_receipts")
    lines = [
        "# F3 graph_raw hidden16 current-manifest case matrix",
        "",
        f"- 状态：`{report['status']}`；source-bound：`{report['source_bound']}`；launch_allowed：`{report['launch_allowed']}`",
        f"- 当前 canonical manifest SHA：`{report['manifest']['canonical_sha256']}`",
        f"- 覆盖：`{coverage['cases']}` cases × seeds `{','.join(str(seed) for seed in coverage['seeds'])}` = `{coverage['jobs']}` plans",
        f"- 唯一性：namespace `{coverage['unique_namespaces']}`、nonce `{coverage['unique_nonces']}`、command identity `{coverage['unique_command_identities']}`",
        f"- 真实 terminal receipts：`{terminal['observed_count']}/{terminal['required_count']}`；`{terminal['status']}`",
        "- 边界：只打开 bounded manifest/training-evidence JSON；不打开 checkpoint、case HDF5、evaluation、trajectory 或 progress，不启动 GPU/runtime/queue。",
        "- 授权：diagnostic-only；formal/T1/T2/qualification 均为 false，credit=0；不写 registry/ledger/denominator/gate/completion。",
        "",
        "| seed | plans | checkpoints | launch |",
        "|---:|---:|---:|---|",
    ]
    for seed in SEEDS:
        rows = [plan for plan in report["plans"] if plan["seed"] == seed]
        lines.append(f"| {seed} | {len(rows)} | `{rows[0]['checkpoint']['sha256']}` | `blocked_fail_closed` |")
    lines.extend(["", report["interpretation"], ""])
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_seed_bindings(values: Sequence[str], *, label: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"--{label} must use SEED=VALUE")
        seed_text, value = item.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise ValueError(f"--{label} seed must be an integer: {seed_text!r}") from error
        if seed in result:
            raise ValueError(f"duplicate --{label} seed: {seed}")
        if not value:
            raise ValueError(f"--{label} value must be non-empty for seed {seed}")
        result[seed] = value
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(LAB_ROOT))
    parser.add_argument("--manifest", default=str(LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"))
    parser.add_argument("--training-evidence", default=str(LAB_ROOT / "reports" / "F3-GRAPH-RAW-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.json"))
    parser.add_argument("--output", default=str(LAB_ROOT / "reports" / "F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-2026-09-29.json"))
    parser.add_argument("--markdown-output", default=str(LAB_ROOT / "reports" / "F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-2026-09-29.zh-CN.md"))
    parser.add_argument("--python-executable")
    parser.add_argument("--plan-date", default="20260929")
    parser.add_argument(
        "--seed-receipt",
        action="append",
        default=[],
        metavar="SEED=PATH",
        help="optional explicit bounded core.training.v1 receipt path; repeat for seeds 17,29,43",
    )
    parser.add_argument(
        "--seed-status",
        action="append",
        default=[],
        metavar="SEED=STATUS",
        help="optional explicit status; non-terminal values fail closed before receipt reads",
    )
    parser.add_argument("--verify-report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report:
            payload, _ = _read_bounded_json(args.verify_report, name="report", max_bytes=MAX_METADATA_BYTES)
            validate_report(payload)
            print(json.dumps({"status": "verified", "report": args.verify_report, "matrix_sha256": payload.get("matrix_sha256")}, ensure_ascii=False))
            return 0
        report = build_report(
            root=args.root,
            manifest=args.manifest,
            training_evidence=args.training_evidence,
            plan_date=args.plan_date,
            python_executable=args.python_executable,
            seed_receipts=(
                _parse_seed_bindings(args.seed_receipt, label="seed-receipt")
                if args.seed_receipt
                else None
            ),
            seed_statuses=(
                _parse_seed_bindings(args.seed_status, label="seed-status")
                if args.seed_status
                else None
            ),
        )
        _write_json(Path(args.output), report)
        Path(args.markdown_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown_output).write_text(render_markdown(report), encoding="utf-8")
        print(json.dumps({"status": report["status"], "source_bound": report["source_bound"], "launch_allowed": report["launch_allowed"], "output": args.output}, ensure_ascii=False))
        return 0
    except (MatrixError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked_fail_closed", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
