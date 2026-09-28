#!/usr/bin/env python3
"""Produce one fresh F3 MLP hidden16 artifact-identity sidecar.

This module is the post-terminal producer consumed by the hardened MLP
diagnostic launcher.  It does not launch, stop, inspect, or restart a
process.  It also does not parse the evaluation JSON or the trajectory HDF5:
those two artifacts are opened only as stable byte streams for an independent
SHA-256/byte-count binding.  The independent validator receipt is bounded
JSON and is parsed strictly for its 835-transition/836-frame completion
contract.

The default command-line mode is a non-writing dry-run.  A sidecar is only
written with ``--write`` and only at the exact canonical fresh ``/tmp`` path
for the supplied non-zero nonce.  Every result is diagnostic-only and
zero-credit.  No formal, T1, T2, qualification, or credit authority can be
introduced through this sidecar.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
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
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836

TRAINING_SCHEMA = "core.f3.mlp.hidden16.training_evidence_matrix.v1"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
IDENTITY_SCHEMA_PREFIX = "core.f3.mlp.hidden16.seed"
IDENTITY_SCHEMA_SUFFIX = ".evaluator_artifact_identity.v1"
IDENTITY_STATUS = "completed_diagnostic"
TRAINING_MATRIX_FILENAME = "F3-MLP-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.json"
HISTORY_FILENAME = "F3-MLP-HIDDEN16-SEED{seed}-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json"

MAX_BOUNDED_JSON_BYTES = 1 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(r"^f3-mlp500-hidden16-seed(?:17|29|43)-20260928$")

ZERO_CREDIT_FIELDS = {
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}

IDENTITY_KEYS = frozenset(
    {
        "schema",
        "status",
        "seed",
        "run_id",
        "namespace",
        "namespace_nonce",
        "manifest_sha256",
        "training_manifest_sha256",
        "training_receipt_sha256",
        "diagnostic_only",
        *ZERO_CREDIT_FIELDS,
        "checkpoint",
        "evaluation",
        "trajectory",
        "validator",
    }
)
ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes"})

VALIDATOR_KEYS = frozenset(
    {
        "schema",
        "passed",
        "fail_closed",
        "diagnostic_only",
        "synthetic_only",
        "production_artifacts_touched",
        "qualification_credit",
        "case_id",
        "evaluation_json",
        "trajectory_hdf5",
        "expected_transitions",
        "frames_executed",
        "complete",
        "incomplete",
        "failure_category",
        "checks",
        "row_fields_checked",
    }
)
VALIDATOR_CHECK_KEYS = frozenset(
    {
        "case_binding",
        "shape",
        "time",
        "valid",
        "future_state_inputs",
        "completion_semantics",
        "trajectory_frames",
        "trajectory_transitions",
        "executed_frame_count",
        "tail_frame_count",
        "particle_count",
        "time_start",
        "time_end",
    }
)
FORBIDDEN_AUTHORITY_ALIASES = frozenset(
    {
        "formal",
        "formal_eligible",
        "qualification",
        "credit",
        "T1_numerical",
        "T2_macro",
        "T2_path",
    }
)


class SidecarError(ValueError):
    """An unsafe, incomplete, or drifting sidecar input."""


def _fail(message: str) -> None:
    raise SidecarError(f"fail-closed: {message}")


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


def _sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA256_RE.fullmatch(text) is None:
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return text


def _unknown(value: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    extra = sorted(set(value) - set(allowed))
    if extra:
        _fail(f"{name} contains unknown fields: {extra}")


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


def _absolute_clean(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    if not raw.startswith("/"):
        _fail(f"{name} must be absolute")
    if raw != os.path.normpath(raw):
        _fail(f"{name} uses a lexical path alias")
    if raw != "/" and raw.endswith("/"):
        _fail(f"{name} must not have a trailing separator")
    path = Path(raw)
    if "." in path.parts or ".." in path.parts:
        _fail(f"{name} contains path traversal or alias components")
    return path


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


def _component_snapshot(path: Path, name: str, *, allow_missing_leaf: bool = False) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Snapshot every component and reject symlinked parents."""

    current = Path(path.anchor or "/")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    snapshot: list[tuple[str, tuple[int, ...]]] = []
    for index, part in enumerate(parts):
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return tuple(snapshot)
            _fail(f"{name} has a missing path component: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            _fail(f"{name} has a non-directory parent: {current}")
        snapshot.append((str(current), _stat_identity(info)))
    return tuple(snapshot)


def _regular_single_link(path: Path, name: str) -> os.stat_result:
    _component_snapshot(path, name)
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if stat.S_ISLNK(info.st_mode):
        _fail(f"{name} is a symlink")
    if not stat.S_ISREG(info.st_mode):
        _fail(f"{name} is not a regular file")
    if info.st_nlink != 1:
        _fail(f"{name} is a hardlink with {info.st_nlink} links")
    if info.st_size <= 0:
        _fail(f"{name} must not be empty")
    return info


def _open_read_only(path: Path, name: str, before: os.stat_result) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    try:
        opened = os.fstat(descriptor)
    except OSError as error:
        os.close(descriptor)
        _fail(f"cannot stat opened {name}: {error}")
    if _stat_identity(opened) != _stat_identity(before):
        os.close(descriptor)
        _fail(f"{name} changed during open")
    return descriptor


def _stream_file(path: Path | str, name: str) -> dict[str, Any]:
    """Hash one stable regular file without interpreting its contents."""

    candidate = _absolute_clean(path, name)
    components_before = _component_snapshot(candidate, name)
    before = _regular_single_link(candidate, name)
    descriptor = _open_read_only(candidate, name, before)
    digest = hashlib.sha256()
    count = 0
    try:
        while True:
            try:
                chunk = os.read(descriptor, 1024 * 1024)
            except OSError as error:
                _fail(f"cannot read {name}: {error}")
            if not chunk:
                break
            digest.update(chunk)
            count += len(chunk)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after_path = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot re-stat {name}: {error}")
    components_after = _component_snapshot(candidate, name)
    if _stat_identity(after_fd) != _stat_identity(before) or _stat_identity(after_path) != _stat_identity(before):
        _fail(f"{name} changed while hashing")
    if components_after != components_before:
        _fail(f"{name} parent path changed while hashing")
    if count != before.st_size:
        _fail(f"{name} byte count drifted while hashing")
    return {"path": str(candidate), "sha256": digest.hexdigest(), "bytes": count}


def _read_bounded_json(path: Path | str, name: str) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Read one small receipt with stable metadata and strict JSON parsing."""

    candidate = _absolute_clean(path, name)
    components_before = _component_snapshot(candidate, name)
    before = _regular_single_link(candidate, name)
    if before.st_size > MAX_BOUNDED_JSON_BYTES:
        _fail(f"{name} exceeds {MAX_BOUNDED_JSON_BYTES} bytes")
    descriptor = _open_read_only(candidate, name, before)
    raw_parts: list[bytes] = []
    count = 0
    try:
        while count <= MAX_BOUNDED_JSON_BYTES:
            try:
                chunk = os.read(descriptor, min(65536, MAX_BOUNDED_JSON_BYTES + 1 - count))
            except OSError as error:
                _fail(f"cannot read {name}: {error}")
            if not chunk:
                break
            raw_parts.append(chunk)
            count += len(chunk)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if count > MAX_BOUNDED_JSON_BYTES:
        _fail(f"{name} exceeds {MAX_BOUNDED_JSON_BYTES} bytes")
    try:
        after_path = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot re-stat {name}: {error}")
    components_after = _component_snapshot(candidate, name)
    if _stat_identity(after_fd) != _stat_identity(before) or _stat_identity(after_path) != _stat_identity(before):
        _fail(f"{name} changed while reading")
    if components_after != components_before:
        _fail(f"{name} parent path changed while reading")
    raw = b"".join(raw_parts)
    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, SidecarError) as error:
        _fail(f"invalid {name}: {error}")
    payload = _mapping(parsed, name)
    _walk_json(payload, name)
    return payload, {"path": str(candidate), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _validate_nonce(value: Any) -> str:
    nonce = _string(value, "namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None:
        _fail("namespace_nonce must be exactly 32 lowercase hexadecimal characters")
    if nonce == "0" * 32:
        _fail("namespace_nonce must be non-zero")
    return nonce


def _validate_seed(value: Any) -> int:
    seed = _strict_int(value, "seed")
    if seed not in SEEDS:
        _fail(f"seed must be one of {SEEDS}")
    return seed


def _root_path(value: Path | str) -> Path:
    root = _absolute_clean(value, "root")
    _component_snapshot(root, "root")
    try:
        info = os.lstat(root)
    except OSError as error:
        _fail(f"cannot inspect root: {error}")
    if not stat.S_ISDIR(info.st_mode):
        _fail("root must be a directory")
    return root


def _fresh_paths(seed: int, nonce: str) -> dict[str, Path]:
    namespace = Path(f"/tmp/f3-mlp500-hidden16-seed{seed}-full835-nonce{nonce}")
    return {
        "namespace": namespace,
        "evaluation": Path(str(namespace) + "-evaluation.json"),
        "trajectory": Path(str(namespace) + "-trajectory.h5"),
        "validator": Path(str(namespace) + "-hdf5-validation.json"),
        "sidecar": Path(str(namespace) + "-artifact-identity.json"),
    }


def _canonical_input(value: Path | str | None, expected: Path, name: str) -> Path:
    candidate = expected if value is None else _absolute_clean(value, name)
    if candidate != expected:
        _fail(f"{name} is not the canonical fresh namespace path")
    return candidate


def _zero_credit(value: Mapping[str, Any], name: str, *, require: bool = True) -> None:
    for key, expected in ZERO_CREDIT_FIELDS.items():
        if key == "qualification" and isinstance(value.get(key), Mapping):
            nested = value[key]
            for nested_key, nested_expected in (
                ("formal_training", False),
                ("formal_eligible", False),
                ("T1_numerical", False),
                ("T2_macro", False),
                ("T2_path", False),
                ("qualification", False),
                ("qualification_credit", 0),
                ("credit", 0),
            ):
                if nested_key in nested:
                    _exact(nested, nested_key, nested_expected, f"{name}.qualification")
            continue
        if require or key in value:
            _exact(value, key, expected, name)


def _artifact(value: Any, name: str) -> dict[str, Any]:
    item = _mapping(value, name)
    _unknown(item, ARTIFACT_KEYS, name)
    return {
        "path": str(_absolute_clean(_string(item.get("path"), f"{name}.path"), f"{name}.path")),
        "sha256": _sha(item.get("sha256"), f"{name}.sha256"),
        "bytes": _strict_int(item.get("bytes"), f"{name}.bytes", 1),
    }


def _metadata_artifact(value: Any, name: str, *, suffix: str) -> dict[str, Any]:
    item = _mapping(value, name)
    path = _absolute_clean(_string(item.get("path"), f"{name}.path"), f"{name}.path")
    if not str(path).endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    result = {
        "path": str(path),
        "sha256": _sha(item.get("sha256"), f"{name}.sha256"),
    }
    if "bytes" in item:
        result["bytes"] = _strict_int(item["bytes"], f"{name}.bytes", 1)
    return result


def _read_training_context(root: Path, seed: int) -> dict[str, Any]:
    matrix_path = root / "reports" / TRAINING_MATRIX_FILENAME
    matrix, _matrix_source = _read_bounded_json(matrix_path, "training_matrix")
    _exact(matrix, "schema", TRAINING_SCHEMA, "training_matrix")
    _exact(matrix, "source_bound", True, "training_matrix")
    _exact(matrix, "diagnostic_only", True, "training_matrix")
    _zero_credit(matrix, "training_matrix")
    shared = _mapping(matrix.get("shared_config"), "training_matrix.shared_config")
    for key, expected in (("model_kind", MODEL), ("hidden", HIDDEN), ("updates", UPDATES)):
        _exact(shared, key, expected, "training_matrix.shared_config")
    rows = matrix.get("runs")
    if not isinstance(rows, list) or len(rows) != len(SEEDS):
        _fail("training_matrix.runs must contain exactly the three registered seeds")
    selected: Mapping[str, Any] | None = None
    for index, value in enumerate(rows):
        row = _mapping(value, f"training_matrix.runs[{index}]")
        row_seed = _validate_seed(row.get("seed"))
        if row_seed == seed:
            if selected is not None:
                _fail(f"training_matrix contains duplicate seed{seed}")
            selected = row
    if selected is None:
        _fail(f"training_matrix does not contain seed{seed}")
    _exact(selected, "status", "bound_complete", f"training_matrix.seed{seed}")
    source = _mapping(selected.get("source"), f"training_matrix.seed{seed}.source")
    source_path = _absolute_clean(_string(source.get("path"), f"training_matrix.seed{seed}.source.path"), f"training_matrix.seed{seed}.source.path")
    _exact(source, "schema", "core.training.v1", f"training_matrix.seed{seed}.source")
    source_sha = _sha(source.get("sha256"), f"training_matrix.seed{seed}.source.sha256")
    source_bytes = _strict_int(source.get("bytes"), f"training_matrix.seed{seed}.source.bytes", 1)
    source_info = _regular_single_link(source_path, f"training_matrix.seed{seed}.source")
    if source_info.st_size != source_bytes:
        _fail(f"training_matrix.seed{seed}.source.bytes drift")

    evidence = _mapping(selected.get("evidence"), f"training_matrix.seed{seed}.evidence")
    for key, expected in (
        ("model_kind", MODEL),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("run_id", f"f3-mlp500-hidden16-seed{seed}-20260928"),
        ("evidence_status", "complete"),
        ("formal_eligible", False),
    ):
        _exact(evidence, key, expected, f"training_matrix.seed{seed}.evidence")
    checkpoint = _metadata_artifact(evidence.get("checkpoint"), f"training_matrix.seed{seed}.checkpoint", suffix=".pt")
    _sha(evidence.get("manifest_sha256"), f"training_matrix.seed{seed}.manifest_sha256")
    if "update" in evidence["checkpoint"]:
        _exact(evidence["checkpoint"], "update", UPDATES, f"training_matrix.seed{seed}.checkpoint")
    return {
        "run_id": f"f3-mlp500-hidden16-seed{seed}-20260928",
        "training_manifest_sha256": _sha(evidence.get("manifest_sha256"), f"training_matrix.seed{seed}.manifest_sha256"),
        "training_receipt": {"path": str(source_path), "sha256": source_sha, "bytes": source_bytes},
        "checkpoint": checkpoint,
    }


def _read_history_context(root: Path, seed: int, training: Mapping[str, Any]) -> dict[str, Any]:
    history_path = root / "reports" / HISTORY_FILENAME.format(seed=seed)
    history, _history_source = _read_bounded_json(history_path, f"history_summary.seed{seed}")
    expected_schema = f"core.f3.mlp.hidden16.seed{seed}.full835_rollout_diagnostic.summary.v1"
    _exact(history, "schema", expected_schema, f"history_summary.seed{seed}")
    _exact(history, "status", "completed", f"history_summary.seed{seed}")
    _exact(history, "diagnostic_only", True, f"history_summary.seed{seed}")
    _zero_credit(history, f"history_summary.seed{seed}")
    protocol = _mapping(history.get("protocol"), f"history_summary.seed{seed}.protocol")
    for key, expected in (
        ("model", MODEL),
        ("seed", seed),
        ("training_updates", UPDATES),
        ("hidden", HIDDEN),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("maximum_steps", TRANSITIONS),
        ("diagnostic", True),
        ("autonomous", True),
        ("future_state_inputs", False),
    ):
        _exact(protocol, key, expected, f"history_summary.seed{seed}.protocol")
    evaluation = _mapping(history.get("evaluation"), f"history_summary.seed{seed}.evaluation")
    for key, expected in (
        ("status", "completed"),
        ("transitions_executed", TRANSITIONS),
        ("trajectory_frames_including_initial", FRAMES),
        ("finite_rollout_complete", True),
        ("future_state_inputs", False),
    ):
        _exact(evaluation, key, expected, f"history_summary.seed{seed}.evaluation")
    source = _mapping(history.get("source"), f"history_summary.seed{seed}.source")
    manifest = source.get("manifest")
    if isinstance(manifest, Mapping):
        manifest_sha = _sha(manifest.get("sha256"), f"history_summary.seed{seed}.source.manifest.sha256")
    else:
        manifest_sha = _sha(source.get("manifest_sha256"), f"history_summary.seed{seed}.source.manifest_sha256")
    history_checkpoint = _metadata_artifact(history.get("checkpoint"), f"history_summary.seed{seed}.checkpoint", suffix=".pt")
    training_checkpoint = dict(training["checkpoint"])
    if history_checkpoint["path"] != training_checkpoint["path"] or history_checkpoint["sha256"] != training_checkpoint["sha256"]:
        _fail(f"seed{seed} checkpoint identity drifts between training and history")
    if "bytes" in training_checkpoint and "bytes" in history_checkpoint and training_checkpoint["bytes"] != history_checkpoint["bytes"]:
        _fail(f"seed{seed} checkpoint byte identity drifts between training and history")
    return {"manifest_sha256": manifest_sha, "checkpoint": history_checkpoint}


def _validate_validator_receipt(payload: Mapping[str, Any], expected: Mapping[str, Path], name: str) -> None:
    _unknown(payload, VALIDATOR_KEYS, name)
    aliases = sorted(FORBIDDEN_AUTHORITY_ALIASES.intersection(payload))
    if aliases:
        _fail(f"{name} contains forbidden authority aliases: {aliases}")
    _exact(payload, "schema", VALIDATOR_SCHEMA, name)
    for key, expected_value in (
        ("passed", True),
        ("fail_closed", False),
        ("diagnostic_only", True),
        ("synthetic_only", False),
        ("production_artifacts_touched", False),
        ("qualification_credit", 0),
        ("case_id", CASE_ID),
        ("expected_transitions", TRANSITIONS),
        ("frames_executed", TRANSITIONS),
        ("complete", True),
        ("incomplete", False),
        ("failure_category", None),
    ):
        _exact(payload, key, expected_value, name)
    if _absolute_clean(_string(payload.get("evaluation_json"), f"{name}.evaluation_json"), f"{name}.evaluation_json") != expected["evaluation"]:
        _fail(f"{name}.evaluation_json drifts from fresh namespace")
    if _absolute_clean(_string(payload.get("trajectory_hdf5"), f"{name}.trajectory_hdf5"), f"{name}.trajectory_hdf5") != expected["trajectory"]:
        _fail(f"{name}.trajectory_hdf5 drifts from fresh namespace")
    checks = _mapping(payload.get("checks"), f"{name}.checks")
    _unknown(checks, VALIDATOR_CHECK_KEYS, f"{name}.checks")
    for key, expected_value in (
        ("case_binding", True),
        ("shape", True),
        ("time", True),
        ("valid", True),
        ("future_state_inputs", True),
        ("completion_semantics", True),
        ("trajectory_frames", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
        ("executed_frame_count", FRAMES),
        ("tail_frame_count", 0),
    ):
        _exact(checks, key, expected_value, f"{name}.checks")
    rows = payload.get("row_fields_checked")
    if not isinstance(rows, list) or any(not isinstance(item, str) or not item for item in rows):
        _fail(f"{name}.row_fields_checked must be a string list")


def _validate_identity_structure(identity: Mapping[str, Any], *, seed: int, nonce: str, paths: Mapping[str, Path]) -> dict[str, Any]:
    _unknown(identity, IDENTITY_KEYS, "identity")
    expected_schema = f"{IDENTITY_SCHEMA_PREFIX}{seed}{IDENTITY_SCHEMA_SUFFIX}"
    for key, expected in (
        ("schema", expected_schema),
        ("status", IDENTITY_STATUS),
        ("seed", seed),
        ("run_id", f"f3-mlp500-hidden16-seed{seed}-20260928"),
        ("namespace", str(paths["namespace"])),
        ("namespace_nonce", nonce),
        ("diagnostic_only", True),
    ):
        _exact(identity, key, expected, "identity")
    _zero_credit(identity, "identity")
    for key in ("manifest_sha256", "training_manifest_sha256", "training_receipt_sha256"):
        _sha(identity.get(key), f"identity.{key}")
    expected_suffixes = {
        "checkpoint": ".pt",
        "evaluation": "-evaluation.json",
        "trajectory": "-trajectory.h5",
        "validator": "-hdf5-validation.json",
    }
    normalized: dict[str, Any] = {}
    for key, suffix in expected_suffixes.items():
        item = _artifact(identity.get(key), f"identity.{key}")
        if not item["path"].endswith(suffix):
            _fail(f"identity.{key}.path must end with {suffix}")
        expected_path = paths["evaluation"] if key == "evaluation" else paths["trajectory"] if key == "trajectory" else paths["validator"] if key == "validator" else None
        if expected_path is not None and Path(item["path"]) != expected_path:
            _fail(f"identity.{key}.path is not the canonical fresh namespace path")
        normalized[key] = item
    return normalized


def validate_identity(
    identity: Mapping[str, Any],
    *,
    root: Path | str = LAB_ROOT,
    seed: int,
    nonce: str,
    verify_files: bool = True,
) -> dict[str, Any]:
    """Validate an identity and optionally re-hash all four artifact files."""

    _root_path(root)
    seed = _validate_seed(seed)
    nonce = _validate_nonce(nonce)
    paths = _fresh_paths(seed, nonce)
    normalized = _validate_identity_structure(identity, seed=seed, nonce=nonce, paths=paths)
    if verify_files:
        for key in ("checkpoint", "evaluation", "trajectory", "validator"):
            observed = _stream_file(normalized[key]["path"], f"identity.{key}")
            if observed["sha256"] != normalized[key]["sha256"]:
                _fail(f"identity.{key}.sha256 drift")
            if observed["bytes"] != normalized[key]["bytes"]:
                _fail(f"identity.{key}.bytes drift")
    return normalized


def build_identity(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    nonce: str,
    evaluation_json: Path | str | None = None,
    trajectory_hdf5: Path | str | None = None,
    validator_receipt: Path | str | None = None,
) -> dict[str, Any]:
    """Build a strict identity without writing it anywhere."""

    root_path = _root_path(root)
    seed = _validate_seed(seed)
    nonce = _validate_nonce(nonce)
    paths = _fresh_paths(seed, nonce)
    evaluation_path = _canonical_input(evaluation_json, paths["evaluation"], "evaluation_json")
    trajectory_path = _canonical_input(trajectory_hdf5, paths["trajectory"], "trajectory_hdf5")
    validator_path = _canonical_input(validator_receipt, paths["validator"], "validator_receipt")

    # The bounded receipt is parsed before the large byte streams, but the
    # validator itself is also streamed below so its identity is independent
    # of any declared metadata in the receipt.
    validator_payload, _validator_read_meta = _read_bounded_json(validator_path, "validator_receipt")
    _validate_validator_receipt(
        validator_payload,
        {"evaluation": evaluation_path, "trajectory": trajectory_path},
        "validator_receipt",
    )

    training = _read_training_context(root_path, seed)
    history = _read_history_context(root_path, seed, training)
    checkpoint = dict(history["checkpoint"])
    checkpoint_observed = _stream_file(checkpoint["path"], "checkpoint")
    if checkpoint_observed["sha256"] != checkpoint["sha256"]:
        _fail("checkpoint.sha256 drift from training/history metadata")
    if "bytes" in checkpoint and checkpoint_observed["bytes"] != checkpoint["bytes"]:
        _fail("checkpoint.bytes drift from training/history metadata")
    checkpoint["bytes"] = checkpoint_observed["bytes"]

    evaluation = _stream_file(evaluation_path, "evaluation_json")
    trajectory = _stream_file(trajectory_path, "trajectory_hdf5")
    validator = _stream_file(validator_path, "validator_receipt")
    identity: dict[str, Any] = {
        "schema": f"{IDENTITY_SCHEMA_PREFIX}{seed}{IDENTITY_SCHEMA_SUFFIX}",
        "status": IDENTITY_STATUS,
        "seed": seed,
        "run_id": training["run_id"],
        "namespace": str(paths["namespace"]),
        "namespace_nonce": nonce,
        "manifest_sha256": history["manifest_sha256"],
        "training_manifest_sha256": training["training_manifest_sha256"],
        "training_receipt_sha256": training["training_receipt"]["sha256"],
        "diagnostic_only": True,
        **ZERO_CREDIT_FIELDS,
        "checkpoint": checkpoint,
        "evaluation": evaluation,
        "trajectory": trajectory,
        "validator": validator,
    }
    _validate_identity_structure(identity, seed=seed, nonce=nonce, paths=paths)
    return identity


def _exclusive_json_write(path: Path, payload: Mapping[str, Any]) -> Path:
    expected = _fresh_paths(int(payload["seed"]), str(payload["namespace_nonce"]))["sidecar"]
    candidate = _absolute_clean(path, "output")
    if candidate != expected:
        _fail("output is not the canonical fresh /tmp sidecar path")
    _component_snapshot(candidate, "output", allow_missing_leaf=True)
    if os.path.lexists(candidate):
        _fail("refusing to overwrite an existing sidecar")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags, 0o644)
    except OSError as error:
        _fail(f"cannot create sidecar: {error}")
    try:
        offset = 0
        while offset < len(raw):
            try:
                offset += os.write(descriptor, raw[offset:])
            except OSError as error:
                _fail(f"cannot write sidecar: {error}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return candidate


def write_identity(
    identity: Mapping[str, Any],
    *,
    root: Path | str = LAB_ROOT,
    seed: int,
    nonce: str,
    output: Path | str | None = None,
) -> Path:
    """Write only a previously-built identity at its canonical fresh path."""

    _root_path(root)
    seed = _validate_seed(seed)
    nonce = _validate_nonce(nonce)
    paths = _fresh_paths(seed, nonce)
    # Re-hash at the write boundary as well.  This keeps a caller from
    # mutating a previously-built mapping (or supplying a forged mapping) and
    # still obtaining a positive sidecar.
    validate_identity(identity, root=root, seed=seed, nonce=nonce, verify_files=True)
    validator_payload, _validator_meta = _read_bounded_json(paths["validator"], "validator_receipt")
    _validate_validator_receipt(
        validator_payload,
        {"evaluation": paths["evaluation"], "trajectory": paths["trajectory"]},
        "validator_receipt",
    )
    return _exclusive_json_write(paths["sidecar"] if output is None else _absolute_clean(output, "output"), identity)


def _json_line(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--seed", type=int, required=True, choices=SEEDS)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--evaluation-json", type=Path, default=None)
    parser.add_argument("--trajectory-hdf5", type=Path, default=None)
    parser.add_argument("--validator-receipt", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--write", action="store_true", help="write the canonical fresh sidecar; default is dry-run")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        identity = build_identity(
            args.root,
            seed=args.seed,
            nonce=args.nonce,
            evaluation_json=args.evaluation_json,
            trajectory_hdf5=args.trajectory_hdf5,
            validator_receipt=args.validator_receipt,
        )
        target = _fresh_paths(args.seed, _validate_nonce(args.nonce))["sidecar"]
        if args.output is not None and _absolute_clean(args.output, "output") != target:
            _fail("output is not the canonical fresh /tmp sidecar path")
        if args.write:
            written = write_identity(identity, root=args.root, seed=args.seed, nonce=args.nonce, output=args.output)
            result = {"status": "written", "write": True, "output": str(written), "identity": identity}
        else:
            result = {"status": "dry_run_ready", "write": False, "output": str(target), "identity": identity}
        print(_json_line(result))
        return 0
    except SidecarError as error:
        print(
            json.dumps(
                {"status": "blocked_fail_closed", "diagnostic_only": True, "credit": 0, "write": False, "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
