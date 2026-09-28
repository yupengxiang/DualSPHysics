#!/usr/bin/env python3
"""Safe fresh-namespace launcher for one F3 MLP hidden16 diagnostic rollout.

This module is deliberately a command-and-process boundary, not an evaluator
or a result verifier.  Its default CLI mode is dry-run: it validates bounded
historical JSON metadata, constructs one exact ``core_learning.py evaluate``
argv, and starts nothing.  The explicit execution path never uses a shell,
never kills or restarts a process, and writes a successful process-exit proof
only after the evaluator has returned naturally and a bounded artifact-identity
sidecar has independently declared the fresh outputs.

The launcher never reads checkpoint, evaluation, trajectory, or HDF5 content.
At explicit execution it opens the four code/input targets read-only only to
pin their resolved identities, then passes those stable descriptors to the
child.  Every accepted plan and proof is diagnostic-only and permanently
zero-credit.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import secrets
import time
from typing import Any, Callable, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836
CHUNK_SIZE = 34560
PROGRESS_EVERY = 25
GPU_COUNT = 8

PLAN_SCHEMA = "core.f3.mlp.hidden16.diagnostic_rollout_launcher_plan.v1"
IDENTITY_SCHEMA_PREFIX = "core.f3.mlp.hidden16.seed"
IDENTITY_SCHEMA_SUFFIX = ".evaluator_artifact_identity.v1"
PROCESS_SCHEMA_PREFIX = "core.f3.mlp.hidden16.seed"
PROCESS_SCHEMA_SUFFIX = ".process_exit_proof.v1"
MAX_JSON_BYTES = 1 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(r"^f3-mlp500-hidden16-seed(?:17|29|43)-20260928$")

TRAINING_SCHEMA = "core.f3.mlp.hidden16.training_evidence_matrix.v1"
ROLLOUT_SCHEMA_PART = "core.f3.mlp.hidden16"
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
TRAINING_MATRIX_FILENAME = "F3-MLP-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.json"
HISTORY_FILENAME = (
    "F3-MLP-HIDDEN16-SEED{seed}-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json"
)
PROCESS_PROOF_FILENAME = (
    "F3-MLP-HIDDEN16-SEED{seed}-PROCESS-EXIT-PROOF-V1-2026-09-28.json"
)

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


class LauncherError(ValueError):
    """Malformed, aliased, reused, or non-diagnostic launcher input."""


def _fail(message: str) -> None:
    raise LauncherError(f"fail-closed: {message}")


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _walk_finite(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > 64:
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
            _walk_finite(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 4096:
            _fail(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _walk_finite(item, f"{name}[{index}]", depth + 1)
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


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA256_RE.fullmatch(text) is None:
        _fail(f"{name} must be 64 lowercase hexadecimal characters")
    return text


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    if value[key] != expected or (isinstance(expected, bool) and type(value[key]) is not bool):
        _fail(f"{name}.{key} must be {expected!r}")


def _zero_credit(value: Mapping[str, Any], name: str, *, require: bool = False) -> None:
    for key, expected in ZERO_CREDIT_FIELDS.items():
        if not (require or key in value):
            continue
        observed = value.get(key)
        # The earliest historical seed17 summary nests the qualification
        # markers under ``qualification``; accept that legacy shape only when
        # every nested authority marker is still explicitly false/zero.
        if key == "qualification" and isinstance(observed, Mapping):
            nested = dict(observed)
            for nested_key, nested_expected in ZERO_CREDIT_FIELDS.items():
                if nested_key == "qualification_credit":
                    continue
                if nested_key in nested:
                    _exact(nested, nested_key, nested_expected, f"{name}.qualification")
            if "credit" in nested:
                _exact(nested, "credit", 0, f"{name}.qualification")
            continue
        _exact(value, key, expected, name)


def _absolute_text(value: str | os.PathLike[str], name: str) -> Path:
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
        _fail(f"{name} contains a path alias component")
    return path


def _assert_no_symlink_components(path: Path, name: str, *, allow_missing_leaf: bool) -> None:
    """Reject symlink components without resolving the requested path."""

    current = Path(path.anchor or "/")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for index, part in enumerate(parts):
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return
            _fail(f"{name} has a missing path component: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            _fail(f"{name} has a non-directory parent: {current}")


def _regular_single_link(path: Path, name: str, *, allow_missing: bool = False) -> os.stat_result | None:
    _assert_no_symlink_components(path, name, allow_missing_leaf=allow_missing)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if allow_missing:
            return None
        _fail(f"{name} is missing: {path}")
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if stat.S_ISLNK(info.st_mode):
        _fail(f"{name} is a symlink: {path}")
    if not stat.S_ISREG(info.st_mode):
        _fail(f"{name} is not a regular file: {path}")
    if info.st_nlink != 1:
        _fail(f"{name} is a hardlink with {info.st_nlink} links: {path}")
    return info


def _file_identity(info: os.stat_result) -> dict[str, int]:
    """Return a bounded identity snapshot without opening file contents."""

    return {
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
        "st_mode": int(stat.S_IMODE(info.st_mode)),
        "st_nlink": int(info.st_nlink),
        "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns),
        "st_ctime_ns": int(info.st_ctime_ns),
    }


def _directory_identity(info: os.stat_result) -> dict[str, int]:
    """Return only replacement-relevant directory identity.

    Directory mtime changes whenever an unrelated child is created.  It is
    therefore intentionally excluded while device/inode/mode/link-count still
    detect parent-directory replacement and hardlink tricks.
    """

    return {
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
        "st_mode": int(stat.S_IMODE(info.st_mode)),
        "st_nlink": int(info.st_nlink),
    }


def _directory_snapshot(path: Path, name: str) -> list[dict[str, Any]]:
    """Snapshot every directory component and reject symlink parents."""

    path = _absolute_text(str(path), name)
    current = Path(path.anchor or "/")
    snapshots: list[dict[str, Any]] = []
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if not parts:
        parts = (path.anchor or "/",)
    for index, part in enumerate(parts):
        if index == 0 and part == (path.anchor or "/"):
            current = Path(path.anchor or "/")
        else:
            current /= part
        try:
            info = os.lstat(current)
        except OSError as error:
            _fail(f"cannot inspect {name} directory component {current}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink directory component: {current}")
        if not stat.S_ISDIR(info.st_mode):
            _fail(f"{name} has a non-directory component: {current}")
        snapshots.append({"path": str(current), "identity": _directory_identity(info)})
    return snapshots


def _input_snapshot(path: Path, name: str, *, allow_leaf_symlink: bool) -> dict[str, Any]:
    """Capture an immutable path/target/parent contract for an execution input."""

    path = _absolute_text(str(path), name)
    parent_snapshot = _directory_snapshot(path.parent, f"{name} parent")
    try:
        path_info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    path_is_symlink = stat.S_ISLNK(path_info.st_mode)
    if path_is_symlink and not allow_leaf_symlink:
        _fail(f"{name} is a replaceable symlink: {path}")
    if not path_is_symlink and not stat.S_ISREG(path_info.st_mode):
        _fail(f"{name} is not a regular file: {path}")
    try:
        resolved = path.resolve(strict=True) if path_is_symlink else path
    except OSError as error:
        _fail(f"cannot resolve {name}: {error}")
    resolved = _absolute_text(str(resolved), f"{name}.resolved_path")
    resolved_parent_snapshot = _directory_snapshot(resolved.parent, f"{name} resolved parent")
    resolved_info = _regular_single_link(resolved, f"{name} resolved target")
    assert resolved_info is not None
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "path_is_symlink": path_is_symlink,
        "path_identity": _file_identity(path_info),
        "resolved_parent_identity": resolved_parent_snapshot,
        "resolved_identity": _file_identity(resolved_info),
        "parent_identity": parent_snapshot,
    }


def _python_executable(path: Path) -> None:
    """Validate the interpreter and its resolved regular target.

    The conventional venv ``bin/python`` leaf symlink remains usable, but its
    parent chain and resolved target are captured by :func:`_input_snapshot`
    and the execute path later runs the already-open target FD.
    """

    _input_snapshot(path, "Python executable", allow_leaf_symlink=True)


def _collision(path: Path, name: str) -> None:
    """Reject every existing output, including dangling symlinks and hardlinks."""

    _assert_no_symlink_components(path, name, allow_missing_leaf=True)
    if not os.path.lexists(path):
        return
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect output {name}: {error}")
    if stat.S_ISLNK(info.st_mode):
        _fail(f"refusing symlink output reuse for {name}: {path}")
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        _fail(f"refusing hardlink output reuse for {name}: {path}")
    _fail(f"refusing to reuse existing output {name}: {path}")


def _bounded_json(path: Path, root: Path, name: str, *, allow_tmp: bool = False) -> tuple[Mapping[str, Any], str, int]:
    """Read only a small JSON receipt, with no content access to large artifacts."""

    path = _absolute_text(str(path), name)
    allowed_roots = [root / "reports"]
    if allow_tmp:
        allowed_roots.append(Path("/tmp"))
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        _fail(f"{name} escapes bounded JSON roots")
    info = _regular_single_link(path, name)
    assert info is not None
    if info.st_size > MAX_JSON_BYTES:
        _fail(f"{name} exceeds {MAX_JSON_BYTES} bytes")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open bounded {name}: {error}")
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_nlink, opened.st_size) != (
            info.st_dev, info.st_ino, info.st_nlink, info.st_size
        ):
            _fail(f"{name} changed during open")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_JSON_BYTES:
            chunk = os.read(fd, min(65536, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_JSON_BYTES:
            _fail(f"{name} exceeds {MAX_JSON_BYTES} bytes")
        closed_info = os.fstat(fd)
        if (closed_info.st_dev, closed_info.st_ino, closed_info.st_nlink, closed_info.st_size) != (
            info.st_dev, info.st_ino, info.st_nlink, info.st_size
        ):
            _fail(f"{name} changed after read")
        raw = b"".join(chunks)
    except OSError as error:
        _fail(f"cannot read bounded {name}: {error}")
    finally:
        os.close(fd)
    after = os.lstat(path)
    if (after.st_dev, after.st_ino, after.st_nlink, after.st_size) != (
        info.st_dev, info.st_ino, info.st_nlink, info.st_size
    ):
        _fail(f"{name} changed after close")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, LauncherError) as error:
        _fail(f"invalid bounded {name}: {error}")
    payload = _mapping(payload, name)
    _walk_finite(payload, name)
    return payload, hashlib.sha256(raw).hexdigest(), len(raw)


def _artifact(value: Any, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    item = _mapping(value, name)
    allowed = {"path", "sha256", "bytes"}
    extra = sorted(set(item) - allowed)
    if extra:
        _fail(f"{name} contains unknown fields: {extra}")
    path = _absolute_text(_string(item.get("path"), f"{name}.path"), f"{name}.path")
    if suffix is not None and not str(path).endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    return {
        "path": str(path),
        "sha256": _sha(item.get("sha256"), f"{name}.sha256"),
        "bytes": _strict_int(item.get("bytes"), f"{name}.bytes", 1),
    }


def _receipt_artifact(value: Any, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    """Extract identity from a historical receipt without imposing its extra fields."""

    item = _mapping(value, name)
    path = _absolute_text(_string(item.get("path"), f"{name}.path"), f"{name}.path")
    if suffix is not None and not str(path).endswith(suffix):
        _fail(f"{name}.path must end with {suffix}")
    declared_bytes = item.get("bytes", 1)
    return {
        "path": str(path),
        "sha256": _sha(item.get("sha256"), f"{name}.sha256"),
        "bytes": _strict_int(declared_bytes, f"{name}.bytes", 1),
    }


def _expected_run_id(seed: int) -> str:
    return f"f3-mlp500-hidden16-seed{seed}-20260928"


def _expected_checkpoint_path(seed: int) -> str:
    return f"/tmp/f3-mlp500-hidden16-seed{seed}-20260928-checkpoint.pt"


def _expected_training_path(seed: int) -> str:
    return f"/tmp/f3-mlp500-hidden16-seed{seed}-20260928-training.json"


def _expected_namespace(seed: int, nonce: str) -> str:
    return f"/tmp/f3-mlp500-hidden16-seed{seed}-full835-nonce{nonce}"


def _validate_nonce(nonce: str) -> str:
    if NONCE_RE.fullmatch(nonce) is None:
        _fail("namespace nonce must be exactly 32 lowercase hexadecimal characters")
    if nonce == "0" * 32:
        _fail("namespace nonce must be non-zero")
    return nonce


def _validate_seed(seed: int) -> int:
    if type(seed) is not int or seed not in SEEDS:
        _fail(f"seed must be one of {SEEDS}")
    return seed


def _manifest_sha(source: Mapping[str, Any], name: str) -> str:
    manifest = source.get("manifest")
    if isinstance(manifest, Mapping):
        return _sha(manifest.get("sha256"), f"{name}.manifest.sha256")
    return _sha(source.get("manifest_sha256"), f"{name}.manifest_sha256")


def _validate_history(payload: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    _exact(payload, "status", "completed", name)
    _exact(payload, "diagnostic_only", True, name)
    _zero_credit(payload, name)
    protocol = _mapping(payload.get("protocol"), f"{name}.protocol")
    for key, expected in (
        ("model", MODEL), ("seed", seed), ("training_updates", UPDATES),
        ("hidden", HIDDEN), ("case_id", CASE_ID), ("split", SPLIT),
        ("diagnostic", True), ("autonomous", True), ("future_state_inputs", False),
    ):
        _exact(protocol, key, expected, f"{name}.protocol")
    if "maximum_steps" in protocol:
        _exact(protocol, "maximum_steps", TRANSITIONS, f"{name}.protocol")
    else:
        _exact(protocol, "requested_transitions", TRANSITIONS, f"{name}.protocol")
    evaluation = _mapping(payload.get("evaluation"), f"{name}.evaluation")
    for key, expected in (
        ("status", "completed"), ("transitions_executed", TRANSITIONS),
        ("trajectory_frames_including_initial", FRAMES),
        ("finite_rollout_complete", True), ("future_state_inputs", False),
    ):
        _exact(evaluation, key, expected, f"{name}.evaluation")
    source = _mapping(payload.get("source"), f"{name}.source")
    manifest_sha = _manifest_sha(source, name)
    checkpoint_payload = payload.get("checkpoint")
    checkpoint_bytes: int | None = None
    if isinstance(checkpoint_payload, Mapping):
        checkpoint = _receipt_artifact(checkpoint_payload, f"{name}.checkpoint", suffix=".pt")
        checkpoint_bytes = checkpoint["bytes"]
    else:
        training = _mapping(payload.get("training"), f"{name}.training")
        checkpoint = {
            "path": _expected_checkpoint_path(seed),
            "sha256": _sha(training.get("checkpoint_sha256"), f"{name}.training.checkpoint_sha256"),
            "bytes": _strict_int(training.get("checkpoint_bytes"), f"{name}.training.checkpoint_bytes", 1),
        }
    checkpoint_name = Path(checkpoint["path"]).name
    if (
        f"seed{seed}" not in checkpoint_name
        or "hidden16" not in checkpoint_name
        or "500" not in checkpoint_name
    ):
        _fail(f"{name}.checkpoint.path is not seed/hidden16/update bound")
    if not RUN_ID_RE.fullmatch(_expected_run_id(seed)):
        _fail("internal run-id contract drift")
    return {
        "seed": seed,
        "run_id": _expected_run_id(seed),
        "manifest_sha256": manifest_sha,
        "checkpoint": checkpoint,
        "historical_checkpoint_bytes": checkpoint_bytes,
        "source_sha256": None,
    }


def _validate_training_matrix(payload: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    _exact(payload, "schema", TRAINING_SCHEMA, name)
    _exact(payload, "source_bound", True, name)
    _exact(payload, "diagnostic_only", True, name)
    _zero_credit(payload, name, require=True)
    shared = _mapping(payload.get("shared_config"), f"{name}.shared_config")
    for key, expected in (("model_kind", MODEL), ("hidden", HIDDEN), ("updates", UPDATES)):
        _exact(shared, key, expected, f"{name}.shared_config")
    runs = payload.get("runs")
    if not isinstance(runs, list) or len(runs) != len(SEEDS):
        _fail(f"{name}.runs must contain exactly {len(SEEDS)} rows")
    by_seed: dict[int, dict[str, Any]] = {}
    for row_value in runs:
        row = _mapping(row_value, f"{name}.run")
        row_seed = _strict_int(row.get("seed"), f"{name}.run.seed")
        if row_seed not in SEEDS or row_seed in by_seed:
            _fail(f"{name}.runs contains an invalid or duplicate seed")
        _exact(row, "status", "bound_complete", f"{name}.seed{row_seed}")
        evidence = _mapping(row.get("evidence"), f"{name}.seed{row_seed}.evidence")
        for key, expected in (
            ("model_kind", MODEL), ("hidden", HIDDEN), ("updates", UPDATES),
            ("run_id", _expected_run_id(row_seed)), ("evidence_status", "complete"),
        ):
            _exact(evidence, key, expected, f"{name}.seed{row_seed}.evidence")
        checkpoint = _receipt_artifact(evidence.get("checkpoint"), f"{name}.seed{row_seed}.checkpoint", suffix=".pt")
        checkpoint_name = Path(checkpoint["path"]).name
        if (
            f"seed{row_seed}" not in checkpoint_name
            or "hidden16" not in checkpoint_name
            or "500" not in checkpoint_name
        ):
            _fail(f"{name}.seed{row_seed}.checkpoint.path is not seed/hidden16/update bound")
        source = _mapping(row.get("source"), f"{name}.seed{row_seed}.source")
        source_path = _absolute_text(_string(source.get("path"), f"{name}.seed{row_seed}.source.path"), f"{name}.seed{row_seed}.source.path")
        if source_path.suffix != ".json":
            _fail(f"{name}.seed{row_seed}.source.path must be JSON")
        _sha(source.get("sha256"), f"{name}.seed{row_seed}.source.sha256")
        _regular_single_link(source_path, f"{name}.seed{row_seed}.source")
        manifest_sha = _sha(evidence.get("manifest_sha256"), f"{name}.seed{row_seed}.manifest_sha256")
        by_seed[row_seed] = {
            "seed": row_seed,
            "run_id": _expected_run_id(row_seed),
            "manifest_sha256": manifest_sha,
            "training_receipt": {
                "path": str(source_path),
                "sha256": source["sha256"],
                "bytes": _strict_int(source.get("bytes"), f"{name}.seed{row_seed}.source.bytes", 1),
            },
            "checkpoint": checkpoint,
        }
    if sorted(by_seed) != list(SEEDS):
        _fail(f"{name} does not contain the exact seed set {SEEDS}")
    return by_seed[seed]


def _output_paths(namespace: Path, root: Path, seed: int) -> dict[str, Path]:
    prefix = str(namespace)
    return {
        "namespace": namespace,
        "evaluation": Path(prefix + "-evaluation.json"),
        "trajectory": Path(prefix + "-trajectory.h5"),
        "progress": Path(prefix + "-evaluation-progress.json"),
        "log": Path(prefix + "-evaluation.log"),
        "artifact_identity": Path(prefix + "-artifact-identity.json"),
        "validator": Path(prefix + "-hdf5-validation.json"),
        "process_proof": root / "reports" / PROCESS_PROOF_FILENAME.format(seed=seed),
    }


def _validate_output_paths(paths: Mapping[str, Path], root: Path) -> None:
    for name, path in paths.items():
        if name == "process_proof":
            expected = root / "reports" / path.name
            if path != expected:
                _fail("process proof path is not the fixed report destination")
        else:
            _absolute_text(str(path), f"output.{name}")
        _collision(path, f"output.{name}")


@dataclass(frozen=True)
class RolloutPlan:
    root: Path
    seed: int
    nonce: str
    namespace: Path
    run_id: str
    command: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    command_sha256: str
    outputs: Mapping[str, Path]
    manifest_sha256: str
    training_manifest_sha256: str
    training_receipt_sha256: str
    checkpoint: Mapping[str, Any]
    history_summary: Path
    training_matrix: Path
    proof_output: Path
    root_identity: tuple[Mapping[str, Any], ...]
    input_snapshots: Mapping[str, Mapping[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "status": "dry_run_ready",
            "mode": "dry_run",
            "launched": False,
            "seed": self.seed,
            "run_id": self.run_id,
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "namespace": str(self.namespace),
            "namespace_nonce": self.nonce,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "env_overrides": dict(self.env),
            "command_sha256": self.command_sha256,
            "outputs": {key: str(value) for key, value in self.outputs.items()},
            "manifest_sha256": self.manifest_sha256,
            "training_manifest_sha256": self.training_manifest_sha256,
            "training_receipt_sha256": self.training_receipt_sha256,
            "checkpoint": dict(self.checkpoint),
            "history_summary": str(self.history_summary),
            "training_matrix": str(self.training_matrix),
            "proof_output": str(self.proof_output),
            "root_identity": [dict(item) for item in self.root_identity],
            "input_snapshots": {
                key: dict(value) for key, value in self.input_snapshots.items()
            },
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
            "zero_credit_only": True,
            "input_boundary": {
                "bounded_json_opened": True,
                "checkpoint_content_opened": False,
                "evaluation_content_opened": False,
                "trajectory_hdf5_opened": False,
                "manifest_content_opened": False,
                "runtime_started": False,
                "queue_submissions": 0,
            },
        }


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_directory_snapshot(
    path: Path,
    expected: Sequence[Mapping[str, Any]],
    name: str,
) -> None:
    actual = _directory_snapshot(path, name)
    if list(actual) != [dict(item) for item in expected]:
        _fail(f"{name} directory identity drifted after dry-run planning")


def _validate_input_snapshot(
    snapshot: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    allowed = {
        "path", "resolved_path", "path_is_symlink", "path_identity",
        "resolved_parent_identity", "resolved_identity", "parent_identity",
    }
    extra = sorted(set(snapshot) - allowed)
    if extra:
        _fail(f"{name} snapshot contains unknown fields: {extra}")
    path = _absolute_text(_string(snapshot.get("path"), f"{name}.path"), f"{name}.path")
    resolved_path = _absolute_text(
        _string(snapshot.get("resolved_path"), f"{name}.resolved_path"),
        f"{name}.resolved_path",
    )
    path_is_symlink = snapshot.get("path_is_symlink")
    if type(path_is_symlink) is not bool:
        _fail(f"{name}.path_is_symlink must be boolean")
    parent_identity = snapshot.get("parent_identity")
    resolved_parent_identity = snapshot.get("resolved_parent_identity")
    if not isinstance(parent_identity, list) or not isinstance(resolved_parent_identity, list):
        _fail(f"{name} parent identities must be arrays")
    normalized = {
        "path": str(path),
        "resolved_path": str(resolved_path),
        "path_is_symlink": path_is_symlink,
        "path_identity": dict(_mapping(snapshot.get("path_identity"), f"{name}.path_identity")),
        "resolved_parent_identity": [dict(_mapping(item, f"{name}.resolved_parent_identity")) for item in resolved_parent_identity],
        "resolved_identity": dict(_mapping(snapshot.get("resolved_identity"), f"{name}.resolved_identity")),
        "parent_identity": [dict(_mapping(item, f"{name}.parent_identity")) for item in parent_identity],
    }
    return normalized


def _revalidate_input_snapshot(
    snapshot: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    expected = _validate_input_snapshot(snapshot, name)
    actual = _input_snapshot(
        Path(expected["path"]),
        name,
        allow_leaf_symlink=expected["path_is_symlink"],
    )
    if actual != expected:
        _fail(f"{name} identity drifted between dry-run and execute")
    return expected


def _open_stable_input(snapshot: Mapping[str, Any], name: str) -> int:
    """Open the exact resolved target and verify its FD identity before use."""

    expected = _revalidate_input_snapshot(snapshot, name)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(expected["resolved_path"], flags)
    except OSError as error:
        _fail(f"cannot open stable {name}: {error}")
    try:
        opened = os.fstat(fd)
        if _file_identity(opened) != expected["resolved_identity"]:
            _fail(f"{name} target changed while opening stable FD")
        after = _revalidate_input_snapshot(snapshot, name)
        if after != expected:
            _fail(f"{name} path changed while opening stable FD")
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_stable_root(plan: RolloutPlan) -> int:
    _validate_directory_snapshot(plan.root, plan.root_identity, "rollout root")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(plan.root, flags)
    except OSError as error:
        _fail(f"cannot open stable rollout root: {error}")
    try:
        opened = os.fstat(fd)
        expected = dict(plan.root_identity[-1]["identity"])
        if _directory_identity(opened) != expected:
            _fail("rollout root changed while opening stable FD")
        _validate_directory_snapshot(plan.root, plan.root_identity, "rollout root")
        return fd
    except Exception:
        os.close(fd)
        raise


def _proc_fd_path(fd: int) -> str:
    if type(fd) is not int or fd < 0:
        _fail("stable input FD is invalid")
    proc_fd = Path(f"/proc/self/fd/{fd}")
    if not proc_fd.parent.exists():
        _fail("/proc/self/fd is required for stable diagnostic execution")
    return str(proc_fd)


def _stable_execution_command(
    plan: RolloutPlan,
    input_fds: Mapping[str, int],
    root_fd: int,
) -> tuple[str, ...]:
    replacements = {
        str(plan.input_snapshots["interpreter"]["path"]): _proc_fd_path(input_fds["interpreter"]),
        str(plan.input_snapshots["core_learning"]["path"]): _proc_fd_path(input_fds["core_learning"]),
        str(plan.input_snapshots["manifest"]["path"]): _proc_fd_path(input_fds["manifest"]),
        str(plan.input_snapshots["checkpoint"]["path"]): _proc_fd_path(input_fds["checkpoint"]),
        str(plan.root): _proc_fd_path(root_fd),
    }
    result = tuple(replacements.get(argument, argument) for argument in plan.command)
    logical = tuple(replacements_inverse(argument, replacements) for argument in result)
    command_sha = _canonical_digest({
        "argv": list(logical),
        "cwd": str(plan.root),
        "env_overrides": dict(plan.env),
    })
    if command_sha != plan.command_sha256:
        _fail("stable execution command drifts from the dry-run command digest")
    return result


def replacements_inverse(argument: str, replacements: Mapping[str, str]) -> str:
    """Map one stable procfs argument back to its planned logical path."""

    for original, stable in replacements.items():
        if argument == stable:
            return original
    return argument


def _fixed_input(path: Path, root: Path, filename: str, name: str) -> Path:
    path = _absolute_text(str(path), name)
    expected = root / "reports" / filename
    if path != expected:
        _fail(f"{name} must use the fixed bounded report path")
    return path


def build_plan(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    nonce: str | None = None,
    namespace: Path | str | None = None,
    gpu_index: int = 0,
    history_summary: Path | str | None = None,
    training_matrix: Path | str | None = None,
) -> RolloutPlan:
    """Validate metadata and construct a fresh, non-launching rollout plan."""

    root = _absolute_text(os.path.abspath(os.fspath(root)), "root")
    root_identity = tuple(_directory_snapshot(root, "root"))
    seed = _validate_seed(seed)
    if type(gpu_index) is not int or not 0 <= gpu_index < GPU_COUNT:
        _fail(f"gpu_index must be an integer in [0, {GPU_COUNT})")
    nonce = _validate_nonce(nonce or secrets.token_hex(16))
    expected_namespace = Path(_expected_namespace(seed, nonce))
    if namespace is not None:
        supplied = _absolute_text(os.fspath(namespace), "namespace")
        if supplied != expected_namespace:
            _fail("namespace is not the canonical seed/full835/nonce namespace")
    namespace = expected_namespace

    history_path = _fixed_input(
        Path(history_summary) if history_summary is not None else root / "reports" / HISTORY_FILENAME.format(seed=seed),
        root,
        HISTORY_FILENAME.format(seed=seed),
        "history_summary",
    )
    matrix_path = _fixed_input(
        Path(training_matrix) if training_matrix is not None else root / "reports" / TRAINING_MATRIX_FILENAME,
        root,
        TRAINING_MATRIX_FILENAME,
        "training_matrix",
    )
    history_payload, _history_sha, _history_bytes = _bounded_json(history_path, root, "history_summary")
    history = _validate_history(history_payload, seed, "history_summary")
    matrix_payload, _matrix_sha, _matrix_bytes = _bounded_json(matrix_path, root, "training_matrix")
    training = _validate_training_matrix(matrix_payload, seed, "training_matrix")
    if history["run_id"] != training["run_id"]:
        _fail("history and training run IDs drift")
    if history["checkpoint"]["path"] != training["checkpoint"]["path"] or history["checkpoint"]["sha256"] != training["checkpoint"]["sha256"]:
        _fail("history and training checkpoint identities drift")

    checkpoint_path = Path(training["checkpoint"]["path"])
    python = root / ".venv" / "bin" / "python"
    core_learning = root / "scripts" / "core_learning.py"
    manifest = root / "campaigns" / "core-v1" / "f3-dataset-v2.json"
    input_snapshots = {
        "interpreter": _input_snapshot(python, "Python executable", allow_leaf_symlink=True),
        "core_learning": _input_snapshot(core_learning, "core_learning.py", allow_leaf_symlink=False),
        "manifest": _input_snapshot(manifest, "manifest input", allow_leaf_symlink=False),
        "checkpoint": _input_snapshot(checkpoint_path, "checkpoint input", allow_leaf_symlink=False),
    }
    outputs = _output_paths(namespace, root, seed)
    _validate_output_paths(outputs, root)

    command = (
        str(python), "-u", str(core_learning), "evaluate",
        "--manifest", str(manifest), "--data-root", str(root),
        "--checkpoint", str(checkpoint_path), "--case-id", CASE_ID,
        "--split", SPLIT, "--maximum-steps", str(TRANSITIONS),
        "--chunk-size", str(CHUNK_SIZE), "--device", "cuda:0",
        "--progress-every", str(PROGRESS_EVERY),
        "--trajectory-output", str(outputs["trajectory"]),
        "--progress-output", str(outputs["progress"]),
        "--output", str(outputs["evaluation"]), "--diagnostic",
    )
    env = {"CUDA_VISIBLE_DEVICES": str(gpu_index), "PYTHONDONTWRITEBYTECODE": "1"}
    command_sha = _canonical_digest({"argv": list(command), "cwd": str(root), "env_overrides": env})
    return RolloutPlan(
        root=root,
        seed=seed,
        nonce=nonce,
        namespace=namespace,
        run_id=training["run_id"],
        command=command,
        cwd=root,
        env=env,
        command_sha256=command_sha,
        outputs=outputs,
        manifest_sha256=history["manifest_sha256"],
        training_manifest_sha256=training["manifest_sha256"],
        training_receipt_sha256=training["training_receipt"]["sha256"],
        checkpoint=training["checkpoint"],
        history_summary=history_path,
        training_matrix=matrix_path,
        proof_output=outputs["process_proof"],
        root_identity=root_identity,
        input_snapshots=input_snapshots,
    )


def _validate_identity_payload(payload: Mapping[str, Any], plan: RolloutPlan, name: str) -> dict[str, Any]:
    allowed = {
        "schema", "status", "seed", "run_id", "namespace", "namespace_nonce",
        "manifest_sha256", "training_manifest_sha256", "training_receipt_sha256",
        "checkpoint", "evaluation", "trajectory", "validator",
        "diagnostic_only", *ZERO_CREDIT_FIELDS,
    }
    extra = sorted(set(payload) - allowed)
    if extra:
        _fail(f"{name} contains unknown or pseudo-authority fields: {extra}")
    _exact(payload, "schema", f"{IDENTITY_SCHEMA_PREFIX}{plan.seed}{IDENTITY_SCHEMA_SUFFIX}", name)
    _exact(payload, "status", "completed_diagnostic", name)
    _exact(payload, "seed", plan.seed, name)
    _exact(payload, "run_id", plan.run_id, name)
    _exact(payload, "namespace", str(plan.namespace), name)
    _exact(payload, "namespace_nonce", plan.nonce, name)
    _exact(payload, "diagnostic_only", True, name)
    _zero_credit(payload, name, require=True)
    _exact(payload, "manifest_sha256", plan.manifest_sha256, name)
    _exact(payload, "training_manifest_sha256", plan.training_manifest_sha256, name)
    _exact(payload, "training_receipt_sha256", plan.training_receipt_sha256, name)
    expected = {
        "checkpoint": (plan.checkpoint["path"], ".pt"),
        "evaluation": (str(plan.outputs["evaluation"]), "-evaluation.json"),
        "trajectory": (str(plan.outputs["trajectory"]), "-trajectory.h5"),
        "validator": (str(plan.outputs["validator"]), "-hdf5-validation.json"),
    }
    result: dict[str, Any] = {}
    for key, (expected_path, suffix) in expected.items():
        item = _artifact(payload.get(key), f"{name}.{key}", suffix=suffix)
        if item["path"] != expected_path:
            _fail(f"{name}.{key}.path is not the canonical fresh-namespace path")
        _regular_single_link(Path(item["path"]), f"{name}.{key}")
        if key != "checkpoint":
            info = os.lstat(item["path"])
            if info.st_size != item["bytes"]:
                _fail(f"{name}.{key}.bytes does not match metadata")
        result[key] = item
    if result["checkpoint"] != dict(plan.checkpoint):
        _fail(f"{name}.checkpoint identity drifts from training evidence")
    return result


def load_artifact_identity(plan: RolloutPlan, path: Path | str | None = None) -> dict[str, Any]:
    """Load only the bounded post-run identity sidecar; never open large outputs."""

    candidate = Path(path) if path is not None else plan.outputs["artifact_identity"]
    candidate = _absolute_text(os.fspath(candidate), "artifact_identity")
    if candidate != plan.outputs["artifact_identity"]:
        _fail("artifact_identity path is not the canonical fresh-namespace sidecar")
    payload, _sha_value, _bytes = _bounded_json(candidate, plan.root, "artifact_identity", allow_tmp=True)
    return _validate_identity_payload(payload, plan, "artifact_identity")


def _proc_starttime_ticks(pid: int) -> int | None:
    """Read the small Linux process start-time field when procfs is available."""

    path = f"/proc/{pid}/stat"
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        raw = os.read(fd, 4096)
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        tail = raw.decode("ascii").rsplit(")", 1)[1].split()
        # After ``comm`` the first token is field 3 (state); field 22 is index
        # 19 in this tail.
        return int(tail[19])
    except (UnicodeError, IndexError, ValueError):
        return None


def _process_identity(
    pid: int,
    phase: str,
    *,
    returncode: int | None = None,
    reaped: bool | None = None,
    starttime_ticks: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "phase": phase,
        "pid": pid,
        "proc_starttime_ticks": _proc_starttime_ticks(pid) if starttime_ticks is None else starttime_ticks,
        "observed_monotonic_ns": time.monotonic_ns(),
    }
    if returncode is not None:
        result["returncode"] = returncode
    if reaped is not None:
        result["reaped"] = reaped
    return result


def _define_execution_record_type() -> tuple[type[Any], Callable[..., Any], Callable[[Any], bool]]:
    """Create a capability type whose seal is not available to callers."""

    seal = object()

    class ExecutionRecord:
        __slots__ = (
            "_seal", "_plan", "_process", "_evaluator_pid", "_evaluator_returncode",
            "_evaluator_reaped", "_launcher_pid", "_launcher_returncode", "_launcher_reaped",
            "_command_sha256", "_evaluator_start_identity", "_evaluator_end_identity",
            "_launcher_start_identity", "_launcher_end_identity", "_wait_observed", "_poll_returncode",
            "_consumed",
        )

        def __init__(self, *, _seal: object, **values: Any) -> None:
            if _seal is not seal:
                raise TypeError("execution records can only be minted by execute_plan")
            self._seal = _seal
            for key in self.__slots__:
                if key == "_seal":
                    continue
                if key not in values:
                    raise TypeError(f"missing execution record field: {key}")
                setattr(self, key, values[key])

        def consume(self) -> None:
            if self._consumed:
                _fail("execution proof capability has already been consumed")
            self._consumed = True

    def mint(**values: Any) -> Any:
        return ExecutionRecord(_seal=seal, **values)

    def is_valid(value: Any) -> bool:
        return type(value) is ExecutionRecord and getattr(value, "_seal", None) is seal

    return ExecutionRecord, mint, is_valid


_ExecutionRecord, _mint_execution_record, _is_execution_record = _define_execution_record_type()


def _validate_execution_record(plan: RolloutPlan, value: Any) -> Any:
    if not _is_execution_record(value):
        _fail("execution_record must be minted by the actual execute_plan Popen/wait path")
    if value._plan is not plan:
        _fail("execution_record is not bound to this RolloutPlan")
    if value._process is None or not isinstance(value._process, subprocess.Popen) or not value._wait_observed:
        _fail("execution_record lacks an observed Popen/wait lifecycle")
    if value._evaluator_reaped is not True or value._launcher_reaped is not True:
        _fail("execution_record is not fully reaped")
    if type(value._evaluator_pid) is not int or value._evaluator_pid < 1:
        _fail("execution_record evaluator PID is invalid")
    if type(value._launcher_pid) is not int or value._launcher_pid < 1:
        _fail("execution_record launcher PID is invalid")
    if type(value._evaluator_returncode) is not int or type(value._launcher_returncode) is not int or type(value._poll_returncode) is not int:
        _fail("execution_record return codes are not integers")
    if value._evaluator_returncode != 0 or value._launcher_returncode != 0 or value._poll_returncode != 0:
        _fail("execution_record does not prove zero return codes")
    if value._command_sha256 != plan.command_sha256:
        _fail("execution_record command digest drifts from the dry-run plan")
    for name, identity in (
        ("evaluator_start_identity", value._evaluator_start_identity),
        ("evaluator_end_identity", value._evaluator_end_identity),
        ("launcher_start_identity", value._launcher_start_identity),
        ("launcher_end_identity", value._launcher_end_identity),
    ):
        if (
            not isinstance(identity, Mapping)
            or type(identity.get("pid")) is not int
            or identity.get("pid", 0) < 1
            or type(identity.get("proc_starttime_ticks")) is not int
            or identity.get("proc_starttime_ticks", -1) < 0
        ):
            _fail(f"execution_record.{name} is missing")
    if value._evaluator_start_identity["pid"] != value._evaluator_end_identity["pid"] or value._evaluator_start_identity["proc_starttime_ticks"] != value._evaluator_end_identity["proc_starttime_ticks"]:
        _fail("evaluator start/end process identities drifted")
    if value._launcher_start_identity["pid"] != value._launcher_end_identity["pid"] or value._launcher_start_identity["proc_starttime_ticks"] != value._launcher_end_identity["proc_starttime_ticks"]:
        _fail("launcher start/end process identities drifted")
    return value


def _proof_without_digest(proof: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(proof)
    value.pop("exit_proof_sha256", None)
    return value


def build_process_exit_proof(
    plan: RolloutPlan,
    *,
    artifact_identity: Mapping[str, Any],
    execution_record: Any = None,
    evaluator_pid: int | None = None,
    evaluator_returncode: int | None = None,
    launcher_pid: int | None = None,
    launcher_returncode: int | None = None,
) -> dict[str, Any]:
    """Build a proof only from the one-shot capability minted by ``execute_plan``.

    The legacy PID/return-code parameters remain syntactically visible only so
    old callers fail with a controlled launcher error.  They are never trusted
    as evidence; a successful proof requires the sealed record created after a
    real Popen object was waited and reaped.
    """

    if execution_record is None:
        _fail("a process-exit proof requires an execution_record from execute_plan")
    if any(value is not None for value in (evaluator_pid, evaluator_returncode, launcher_pid, launcher_returncode)):
        _fail("manual PID/return-code evidence is not accepted")
    record = _validate_execution_record(plan, execution_record)
    identity = _validate_identity_payload(artifact_identity, plan, "artifact_identity")
    record.consume()
    proof: dict[str, Any] = {
        "schema": f"{PROCESS_SCHEMA_PREFIX}{plan.seed}{PROCESS_SCHEMA_SUFFIX}",
        "report_id": f"f3-mlp-hidden16-seed{plan.seed}-process-exit-proof-v1-{plan.nonce}",
        "status": "exited_successfully",
        "source_bound": True,
        "diagnostic_only": True,
        **ZERO_CREDIT_FIELDS,
        "seed": plan.seed,
        "run_id": plan.run_id,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
        "evaluator_alive": False,
        "launcher_alive": False,
        "evaluator_returncode": record._evaluator_returncode,
        "launcher_returncode": record._launcher_returncode,
        "returncode": 0,
        "evaluator_pid_observed": record._evaluator_pid,
        "launcher_pid_observed": record._launcher_pid,
        "evaluator_reaped": record._evaluator_reaped,
        "launcher_reaped": record._launcher_reaped,
        "command_sha256": record._command_sha256,
        "evaluator_start_identity": dict(record._evaluator_start_identity),
        "evaluator_end_identity": dict(record._evaluator_end_identity),
        "launcher_start_identity": dict(record._launcher_start_identity),
        "launcher_end_identity": dict(record._launcher_end_identity),
        "manifest_sha256": plan.manifest_sha256,
        "training_manifest_sha256": plan.training_manifest_sha256,
        "training_receipt_sha256": plan.training_receipt_sha256,
        "checkpoint": identity["checkpoint"],
        "evaluation": identity["evaluation"],
        "trajectory": identity["trajectory"],
        "validator": identity["validator"],
    }
    proof["exit_proof_sha256"] = _canonical_digest(_proof_without_digest(proof))
    return proof


def _exclusive_json_write(path: Path, payload: Mapping[str, Any], name: str) -> None:
    _absolute_text(str(path), name)
    _assert_no_symlink_components(path, name, allow_missing_leaf=True)
    if os.path.lexists(path):
        _collision(path, name)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as error:
        _fail(f"cannot create {name}: {error}")
    try:
        offset = 0
        while offset < len(encoded):
            offset += os.write(fd, encoded[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)


def execute_plan(
    plan: RolloutPlan,
    *,
    artifact_identity_path: Path | str | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    launcher_pid: int | None = None,
) -> dict[str, Any]:
    """Opt-in execution path; never kills/restarts and only proofs natural exit."""

    # Re-check all fresh targets and all four execution inputs immediately
    # before Popen.  The input files are then passed through inherited stable
    # FDs, so a post-check pathname replacement cannot change what executes.
    _validate_output_paths(plan.outputs, plan.root)
    actual_launcher_pid = os.getpid()
    if launcher_pid is not None and launcher_pid != actual_launcher_pid:
        _fail("launcher_pid overrides are not accepted; execute_plan observes its real process")
    _strict_int(actual_launcher_pid, "launcher_pid", 1)
    expected_input_paths = {
        "interpreter": plan.command[0],
        "core_learning": plan.command[2],
        "manifest": plan.command[plan.command.index("--manifest") + 1],
        "checkpoint": plan.command[plan.command.index("--checkpoint") + 1],
    }
    for key, expected_path in expected_input_paths.items():
        snapshot = plan.input_snapshots.get(key)
        if snapshot is None or snapshot.get("path") != expected_path:
            _fail(f"{key} snapshot does not match the dry-run command")
    if plan.cwd != plan.root:
        _fail("rollout cwd drifts from the snapshotted rollout root")
    input_fds: dict[str, int] = {}
    root_fd: int | None = None
    log_handle: Any = None
    evaluator_pid: int | None = None
    evaluator_returncode: int | None = None
    evaluator_poll_returncode: int | None = None
    evaluator_start_identity: Mapping[str, Any] | None = None
    evaluator_end_identity: Mapping[str, Any] | None = None
    launcher_start_identity = _process_identity(actual_launcher_pid, "start")
    launcher_end_identity: Mapping[str, Any] | None = None
    process: Any = None
    wait_observed = False
    stable_command: tuple[str, ...] | None = None
    log_path = plan.outputs["log"]
    try:
        root_fd = _open_stable_root(plan)
        for key in ("interpreter", "core_learning", "manifest", "checkpoint"):
            input_fds[key] = _open_stable_input(plan.input_snapshots[key], key)
        stable_command = _stable_execution_command(plan, input_fds, root_fd)
        # Re-check output names after input FD acquisition as well; this does
        # not inspect or disturb any existing process.
        _validate_output_paths(plan.outputs, plan.root)
        log_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            log_fd = os.open(log_path, log_flags, 0o644)
        except OSError as error:
            _fail(f"cannot create evaluator log: {error}")
        log_handle = os.fdopen(log_fd, "wb", closefd=True)
        environment = os.environ.copy()
        environment.update(plan.env)
        pass_fds = (root_fd, *tuple(input_fds.values()))
        process = popen_factory(
            list(stable_command),
            cwd=_proc_fd_path(root_fd),
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=pass_fds,
        )
        if not isinstance(process, subprocess.Popen):
            _fail("popen_factory did not return the actual subprocess.Popen object")
        evaluator_pid = _strict_int(getattr(process, "pid", None), "evaluator_pid", 1)
        evaluator_start_identity = _process_identity(evaluator_pid, "start")
        evaluator_returncode = process.wait()
        wait_observed = True
        if type(evaluator_returncode) is not int:
            _fail("evaluator wait() did not return an integer")
        evaluator_poll_returncode = process.poll()
        if evaluator_poll_returncode != evaluator_returncode:
            _fail("evaluator was not observed reaped after wait()")
        if getattr(process, "returncode", evaluator_returncode) != evaluator_returncode:
            _fail("evaluator process object returncode drifted after wait()")
        evaluator_end_identity = _process_identity(
            evaluator_pid,
            "end",
            returncode=evaluator_returncode,
            reaped=True,
            starttime_ticks=evaluator_start_identity["proc_starttime_ticks"],
        )
        launcher_end_identity = _process_identity(
            actual_launcher_pid,
            "end",
            returncode=0,
            reaped=True,
            starttime_ticks=launcher_start_identity["proc_starttime_ticks"],
        )
    finally:
        if log_handle is not None:
            log_handle.close()
        for fd in (root_fd, *tuple(input_fds.values())):
            if fd is not None:
                os.close(fd)
    assert evaluator_pid is not None
    assert evaluator_returncode is not None
    assert evaluator_poll_returncode is not None
    assert evaluator_start_identity is not None
    assert evaluator_end_identity is not None
    assert launcher_end_identity is not None
    if evaluator_returncode != 0:
        return {
            "schema": PLAN_SCHEMA,
            "status": "blocked_evaluator_returncode",
            "launched": True,
            "proof_written": False,
            "seed": plan.seed,
            "namespace": str(plan.namespace),
            "evaluator_pid": evaluator_pid,
            "evaluator_returncode": evaluator_returncode,
            "diagnostic_only": True,
            "credit": 0,
        }
    assert process is not None
    assert stable_command is not None
    execution_record = _mint_execution_record(
        _plan=plan,
        _process=process,
        _evaluator_pid=evaluator_pid,
        _evaluator_returncode=evaluator_returncode,
        _evaluator_reaped=True,
        _launcher_pid=actual_launcher_pid,
        _launcher_returncode=0,
        _launcher_reaped=True,
        _command_sha256=plan.command_sha256,
        _evaluator_start_identity=dict(evaluator_start_identity),
        _evaluator_end_identity=dict(evaluator_end_identity),
        _launcher_start_identity=dict(launcher_start_identity),
        _launcher_end_identity=dict(launcher_end_identity),
        _wait_observed=wait_observed,
        _poll_returncode=evaluator_poll_returncode,
        _consumed=False,
    )
    identity = load_artifact_identity(plan, artifact_identity_path)
    proof = build_process_exit_proof(
        plan,
        artifact_identity={
            "schema": f"{IDENTITY_SCHEMA_PREFIX}{plan.seed}{IDENTITY_SCHEMA_SUFFIX}",
            "status": "completed_diagnostic",
            "seed": plan.seed,
            "run_id": plan.run_id,
            "namespace": str(plan.namespace),
            "namespace_nonce": plan.nonce,
            "manifest_sha256": plan.manifest_sha256,
            "training_manifest_sha256": plan.training_manifest_sha256,
            "training_receipt_sha256": plan.training_receipt_sha256,
            "diagnostic_only": True,
            **ZERO_CREDIT_FIELDS,
            **identity,
        },
        execution_record=execution_record,
    )
    _exclusive_json_write(plan.proof_output, proof, "process_exit_proof")
    return {
        "schema": PLAN_SCHEMA,
        "status": "exited_successfully",
        "launched": True,
        "proof_written": True,
        "proof_path": str(plan.proof_output),
        "seed": plan.seed,
        "namespace": str(plan.namespace),
        "evaluator_pid": evaluator_pid,
        "evaluator_returncode": 0,
        "launcher_returncode": 0,
        "diagnostic_only": True,
        "credit": 0,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--seed", type=int, required=True, choices=SEEDS)
    parser.add_argument("--nonce", default=None, help="32 lowercase hex characters; generated only for a dry-run plan when omitted")
    parser.add_argument("--namespace", default=None, help="must equal the canonical fresh namespace for --seed/--nonce")
    parser.add_argument("--gpu-index", type=int, default=0, choices=range(GPU_COUNT))
    parser.add_argument("--history-summary", type=Path, default=None)
    parser.add_argument("--training-matrix", type=Path, default=None)
    parser.add_argument("--artifact-identity", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="explicitly opt in to one diagnostic evaluator; default is dry-run")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        plan = build_plan(
            args.root,
            seed=args.seed,
            nonce=args.nonce,
            namespace=args.namespace,
            gpu_index=args.gpu_index,
            history_summary=args.history_summary,
            training_matrix=args.training_matrix,
        )
        if not args.execute:
            print(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
            return 0
        result = execute_plan(plan, artifact_identity_path=args.artifact_identity)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0 if result["status"] == "exited_successfully" else 1
    except LauncherError as error:
        print(json.dumps({"status": "blocked_fail_closed", "credit": 0, "diagnostic_only": True, "error": str(error)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
