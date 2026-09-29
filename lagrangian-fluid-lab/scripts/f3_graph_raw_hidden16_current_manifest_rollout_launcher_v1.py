#!/usr/bin/env python3
"""Plan and verify the bounded F3 graph_raw hidden16 full835 contract.

This module is intentionally smaller in authority than a runtime launcher.
It binds the current canonical manifest, an explicit v3 ``core.training.v1``
receipt, and the declared checkpoint identity, then produces a fresh
per-seed namespace and a canonical future evaluator command digest.  The
default and only implemented mode is non-launching planning.  The
``execute_plan`` entry point exists as an explicit deny boundary: a future
audited capability may be added behind it, but this contract never starts,
stops, or restarts a process.

The terminal verifier consumes only the bounded receipt JSON.  It validates
the process-exit and independent-validator claims carried by that receipt,
but never opens a checkpoint, HDF5/trajectory, evaluation, or progress
artifact.  All outcomes are diagnostic-only and permanently zero-credit.
No registry, ledger, denominator, gate, completion, or PLAN file is touched.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL = "graph_raw"
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836
CHUNK_SIZE = 34560
PROGRESS_EVERY = 25
GPU_COUNT = 8

MANIFEST_SCHEMA = "core.dataset.v2"
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
SCHEMA = "core.f3.graph_raw.hidden16.current_manifest_rollout_contract.v1"
REPORT_ID = "f3-graph-raw-hidden16-current-manifest-rollout-contract-v1"
PLAN_SCHEMA = "core.f3.graph_raw.hidden16.current_manifest_rollout_plan.v1"
TERMINAL_RECEIPT_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest_full835_terminal_receipt.v1"
)
TERMINAL_REPORT_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest_terminal_verifier.v1"
)
PROCESS_EXIT_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest_process_exit.v1"
)
VALIDATOR_SCHEMA = "core.f3.full_rollout_receipt_hdf5_validation.v1"
EXECUTE_CAPABILITY_SCHEMA = (
    "core.f3.graph_raw.hidden16.audited_execute_capability.v1"
)
ROLLOUT_SNAPSHOT_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest_rollout_snapshot.v1"
)
ROLLOUT_RECONCILIATION_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest_rollout_reconciliation.v1"
)

DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-FULL835-ROLLOUT-CONTRACT-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_RE = re.compile(
    r"^f3-graph_raw500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-"
    r"(?P<date>20[0-9]{6})-v3$"
)
RECEIPT_NAME_RE = re.compile(
    r"^f3-graph_raw500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-"
    r"(?P<date>20[0-9]{6})-v3-training\.json$"
)
CHECKPOINT_NAME_RE = re.compile(
    r"^f3-graph_raw500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-"
    r"(?P<date>20[0-9]{6})-v3-checkpoint\.pt$"
)

ZERO_CREDIT: dict[str, Any] = {
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

ALLOWED_AUTHORITY_KEYS = frozenset(
    {
        "diagnostic_only",
        "zero_credit_only",
        "formal",
        "formal_admission",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "qualification_credit",
        "credit",
        "formal_release",
        "manifest_formal_release",
        "validation_formal_eligible",
        "progress_is_not_completion",
        "future_state_inputs",
        "source_bound",
        "launch_allowed",
        "runtime_started",
        "queue_submissions",
        "registry_writes",
        "ledger_writes",
        "denominator_writes",
        "gate_writes",
        "completion_writes",
        "process_exit",
        "process_exit_proof",
        "validator",
        "validator_receipt",
    }
)


class ContractError(ValueError):
    """Malformed, drifting, unsafe, or authorizing input."""


LauncherError = ContractError
VerifierError = ContractError


def _fail(message: str) -> None:
    raise ContractError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
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


def _reject_unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown field(s): {unknown}")


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
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


def _reject_authority_aliases(value: Any, name: str = "value") -> None:
    """Reject unrecognised formal/credit/process aliases recursively."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = key.lower()
            if (
                ("credit" in lowered or "formal" in lowered or "pid" in lowered
                 or "process_id" in lowered)
                and key not in ALLOWED_AUTHORITY_KEYS
            ):
                _fail(f"{name}.{key} is an unknown authority/process alias")
            _reject_authority_aliases(item, f"{name}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_authority_aliases(item, f"{name}[{index}]")


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        if key in value:
            _exact(value, key, expected, name)


def _absolute_path(value: Path | str, name: str, *, root: Path | None = None) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        if root is None:
            _fail(f"{name} must be absolute")
        candidate = root / candidate
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a lexical path alias")
    normalized = Path(os.path.normpath(str(candidate)))
    if str(candidate) != str(normalized):
        _fail(f"{name} uses a lexical path alias")
    if str(normalized) != "/" and str(normalized).endswith(os.sep):
        _fail(f"{name} has a trailing separator")
    return normalized


def _assert_no_symlink_components(path: Path, name: str, *, allow_missing_leaf: bool = False) -> None:
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


def _read_bounded_json(path: Path | str, *, root: Path, name: str, max_bytes: int) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = _absolute_path(path, name, root=root)
    _assert_no_symlink_components(candidate, name)
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
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != identity:
            _fail(f"{name} changed before bounded read")
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        closed = os.fstat(fd)
        if (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns) != identity or total != before.st_size:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name} after bounded read: {error}")
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity:
        _fail(f"{name} changed after bounded read")
    raw = b"".join(chunks)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ContractError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    payload = dict(_mapping(payload, name))
    _walk_json(payload, name)
    _reject_authority_aliases(payload, name)
    return payload, {
        "path": str(candidate),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "opened": True,
        "schema": payload.get("schema"),
    }


def _metadata(path: Path, name: str, *, allow_leaf_symlink: bool = False) -> dict[str, Any]:
    """Stat a small input identity without opening its content."""

    path = _absolute_path(path, name)
    _assert_no_symlink_components(path.parent, f"{name} parent")
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if stat.S_ISLNK(info.st_mode):
        if not allow_leaf_symlink:
            _fail(f"{name} is a symlink")
        try:
            target = path.resolve(strict=True)
        except OSError as error:
            _fail(f"cannot resolve {name}: {error}")
        _assert_no_symlink_components(target, f"{name} target")
        info = os.lstat(target)
        resolved = str(target)
    else:
        resolved = str(path)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    return {
        "path": str(path),
        "resolved_path": resolved,
        "bytes": int(info.st_size),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "mtime_ns": int(info.st_mtime_ns),
        "content_opened": False,
    }


def _validate_nonce(value: Any, name: str = "nonce") -> str:
    nonce = _string(value, name)
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail(f"{name} must be a non-zero 32-character lowercase hexadecimal value")
    return nonce


def _validate_seed(value: Any) -> int:
    seed = _int(value, "seed")
    if seed not in SEEDS:
        _fail(f"seed must be one of {SEEDS}")
    return seed


def _validate_run_id(value: Any, seed: int, name: str = "run_id") -> tuple[str, str]:
    run_id = _string(value, name)
    match = RUN_ID_RE.fullmatch(run_id)
    if match is None or int(match.group("seed")) != seed:
        _fail(f"{name} is not the current-manifest v3 identity for seed {seed}")
    return run_id, match.group("date")


def _validate_manifest(payload: Mapping[str, Any], source: Mapping[str, Any], *, path: Path) -> str:
    _exact(payload, "schema", MANIFEST_SCHEMA, "manifest")
    _exact(payload, "case_count", 32, "manifest")
    _exact(payload, "dataset_id", "F3_registered32_core_native_v2", "manifest")
    _exact(payload, "formal_release", False, "manifest")
    if path.name != "f3-dataset-v2.json":
        _fail("manifest is not the fixed current canonical manifest filename")
    # The raw source SHA and canonical manifest SHA are intentionally kept as
    # separate identities: pretty-printed JSON normally has different raw
    # bytes from its canonical encoding.
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _declared_artifact(value: Any, name: str, *, suffix: str | None = None, require_bytes: bool = True) -> dict[str, Any]:
    item = _mapping(value, name)
    allowed = {"path", "sha256", "bytes", "schema", "update"}
    _reject_unknown(item, allowed, name)
    path = _absolute_path(_string(item.get("path"), f"{name}.path"), f"{name}.path")
    if suffix is not None and path.suffix.lower() != suffix.lower():
        _fail(f"{name}.path must end with {suffix}")
    result: dict[str, Any] = {
        "path": str(path),
        "sha256": _sha(item.get("sha256"), f"{name}.sha256"),
    }
    if "bytes" in item and item.get("bytes") is not None:
        result["bytes"] = _int(item.get("bytes"), f"{name}.bytes", 1)
    elif require_bytes:
        _fail(f"{name}.bytes is missing")
    if "schema" in item:
        result["schema"] = _string(item["schema"], f"{name}.schema")
    if "update" in item:
        result["update"] = _int(item["update"], f"{name}.update", 0)
    return result


def _validate_training_receipt(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    seed: int,
    manifest_sha256: str,
    checkpoint_path: Path,
) -> dict[str, Any]:
    name = f"training_receipt.seed{seed}"
    _exact(payload, "schema", TRAINING_SCHEMA, name)
    _exact(payload, "evidence_status", "complete", name)
    if "status" in payload:
        _exact(payload, "status", "completed", name)
    _exact(payload, "model_kind", MODEL, name)
    _exact(payload, "seed", seed, name)
    _exact(payload, "completed_updates", UPDATES, name)
    _exact(payload, "checkpoint_verified", True, name)
    _zero_credit(payload, name)
    run_id, date = _validate_run_id(payload.get("run_id"), seed, f"{name}.run_id")
    receipt_name = Path(str(source["path"])).name
    receipt_match = RECEIPT_NAME_RE.fullmatch(receipt_name)
    if receipt_match is None or int(receipt_match.group("seed")) != seed or receipt_match.group("date") != date:
        _fail(f"{name} source path is not the matching v3 training receipt")
    config = _mapping(payload.get("config"), f"{name}.config")
    for key, expected in (
        ("manifest_sha256", manifest_sha256),
        ("model_kind", MODEL),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("run_id", run_id),
        ("seed", seed),
        ("manifest_formal_release", False),
        ("validation_formal_eligible", False),
    ):
        _exact(config, key, expected, f"{name}.config")
    checkpoint_value = _mapping(payload.get("checkpoint"), f"{name}.checkpoint")
    _exact(checkpoint_value, "schema", CHECKPOINT_SCHEMA, f"{name}.checkpoint")
    _exact(checkpoint_value, "update", UPDATES, f"{name}.checkpoint")
    checkpoint = _declared_artifact(checkpoint_value, f"{name}.checkpoint", suffix=".pt")
    checkpoint_name = Path(checkpoint["path"]).name
    checkpoint_match = CHECKPOINT_NAME_RE.fullmatch(checkpoint_name)
    if checkpoint_match is None or int(checkpoint_match.group("seed")) != seed or checkpoint_match.group("date") != date:
        _fail(f"{name}.checkpoint.path is not the matching v3 checkpoint")
    if Path(checkpoint["path"]) != checkpoint_path:
        _fail(f"{name}.checkpoint.path differs from explicit checkpoint identity")
    if checkpoint["path"] == source["path"]:
        _fail(f"{name}.checkpoint.path aliases the training receipt")
    checkpoint_meta = _metadata(checkpoint_path, f"{name}.checkpoint")
    if checkpoint_meta["bytes"] != checkpoint["bytes"]:
        _fail(f"{name}.checkpoint.bytes differs from stat-only checkpoint metadata")
    checkpoints = payload.get("checkpoints")
    if checkpoints is not None:
        if not isinstance(checkpoints, list) or not checkpoints:
            _fail(f"{name}.checkpoints must be a non-empty array")
        terminal = _declared_artifact(checkpoints[-1], f"{name}.checkpoints[-1]", suffix=".pt")
        if terminal != checkpoint:
            _fail(f"{name}.checkpoints terminal identity drifts")
    return {
        "run_id": run_id,
        "date": date,
        "manifest_sha256": manifest_sha256,
        "training_receipt": {
            "path": str(source["path"]),
            "sha256": str(source["sha256"]),
            "bytes": int(source["bytes"]),
        },
        "checkpoint": checkpoint,
        "checkpoint_metadata": checkpoint_meta,
    }


def _namespace_for(seed: int, nonce: str, output_root: Path) -> Path:
    return output_root / (
        f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    )


def _validate_namespace_shape(namespace: Path, seed: int, nonce: str) -> None:
    if not namespace.is_absolute():
        _fail("output_namespace must be absolute")
    if any(part in {".", ".."} for part in namespace.parts):
        _fail("output_namespace contains a lexical path alias")
    expected_name = (
        f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    )
    if namespace.name != expected_name:
        _fail("output_namespace is not bound to seed/full835/nonce")
    if Path("/tmp") not in namespace.parents and namespace.parent != Path("/tmp"):
        _fail("output_namespace must remain under /tmp")
    _assert_no_symlink_components(namespace.parent, "output_namespace parent")


def _validate_namespace(namespace: Path, seed: int, nonce: str) -> None:
    _validate_namespace_shape(namespace, seed, nonce)
    if os.path.lexists(namespace):
        _fail(f"refusing to reuse existing output namespace: {namespace}")


def _proof_filename(seed: int, nonce: str, manifest_sha256: str) -> str:
    digest = hashlib.sha256(
        f"{MODEL}\0{HIDDEN}\0{UPDATES}\0{seed}\0{nonce}\0{manifest_sha256}".encode()
    ).hexdigest()[:32]
    return f"F3-GRAPH-RAW-HIDDEN16-SEED{seed}-{digest}-PROCESS-EXIT-PROOF-V3.json"


def _output_paths(namespace: Path, root: Path, seed: int, nonce: str, manifest_sha256: str) -> dict[str, Path]:
    prefix = str(namespace)
    return {
        "namespace": namespace,
        "evaluation": Path(prefix + "-evaluation.json"),
        "trajectory": Path(prefix + "-trajectory.h5"),
        "progress": Path(prefix + "-evaluation-progress.json"),
        "log": Path(prefix + "-evaluation.log"),
        "validator": Path(prefix + "-hdf5-validation.json"),
        "terminal_receipt": Path(prefix + "-terminal-receipt.json"),
        "process_proof": root / "reports" / _proof_filename(seed, nonce, manifest_sha256),
    }


def _validate_output_paths(paths: Mapping[str, Path], root: Path) -> None:
    for name, path in paths.items():
        if name == "process_proof" and path.parent != root / "reports":
            _fail("process proof must remain under root/reports")
        _absolute_path(path, f"output.{name}")
        _assert_no_symlink_components(path.parent, f"output.{name} parent")
        if os.path.lexists(path):
            _fail(f"refusing to reuse existing output.{name}: {path}")


def _command_for(
    *,
    root: Path,
    python: Path,
    manifest: Path,
    checkpoint: Path,
    outputs: Mapping[str, Path],
) -> tuple[str, ...]:
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


def command_digest(
    argv: Sequence[str],
    cwd: Path | str,
    env: Mapping[str, str],
) -> str:
    """Digest the exact launcher command identity used by ``RolloutPlan``."""

    return canonical_digest(
        {
            "argv": list(argv),
            "cwd": str(cwd),
            "env_overrides": dict(env),
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
        }
    )


@dataclass(frozen=True)
class RolloutPlan:
    root: Path
    seed: int
    run_id: str
    nonce: str
    manifest: Path
    manifest_sha256: str
    manifest_file_sha256: str
    training_receipt: Path
    training_receipt_sha256: str
    training_receipt_canonical_sha256: str
    checkpoint: Mapping[str, Any]
    checkpoint_metadata: Mapping[str, Any]
    namespace: Path
    outputs: Mapping[str, Path]
    command: tuple[str, ...]
    env: Mapping[str, str]
    command_sha256: str
    python_metadata: Mapping[str, Any]
    core_learning_metadata: Mapping[str, Any]
    stable_snapshot_sha256: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # The nested mappings are intentionally retained for compatibility with
        # the existing plan consumers.  Seal their canonical identity at plan
        # construction time so a later mutation cannot silently become the
        # "same" plan snapshot.
        object.__setattr__(
            self,
            "stable_snapshot_sha256",
            canonical_digest(_rollout_plan_snapshot(self)),
        )

    @property
    def launch_allowed(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "status": "dry_run_ready",
            "mode": "bounded_identity_plan",
            "launched": False,
            "launch_allowed": False,
            "execute_capability_required": EXECUTE_CAPABILITY_SCHEMA,
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
            "manifest": str(self.manifest),
            "manifest_sha256": self.manifest_sha256,
            "manifest_file_sha256": self.manifest_file_sha256,
            "training_receipt": str(self.training_receipt),
            "training_receipt_sha256": self.training_receipt_sha256,
            "training_receipt_canonical_sha256": self.training_receipt_canonical_sha256,
            "checkpoint": dict(self.checkpoint),
            "checkpoint_metadata": dict(self.checkpoint_metadata),
            "namespace": str(self.namespace),
            "namespace_nonce": self.nonce,
            "outputs": {key: str(value) for key, value in self.outputs.items()},
            "command": list(self.command),
            "env_overrides": dict(self.env),
            "command_sha256": self.command_sha256,
            "rollout_snapshot": rollout_plan_snapshot(self),
            "rollout_snapshot_sha256": rollout_plan_snapshot_digest(self),
            "python_metadata": dict(self.python_metadata),
            "core_learning_metadata": dict(self.core_learning_metadata),
            **ZERO_CREDIT,
            "zero_credit_only": True,
            "side_effects": {
                "processes_started": 0,
                "processes_stopped": 0,
                "processes_restarted": 0,
                "runtime_started": False,
                "queue_submissions": 0,
                "registry_writes": 0,
                "ledger_writes": 0,
                "denominator_writes": 0,
                "gate_writes": 0,
                "completion_writes": 0,
                "plan_writes": 0,
            },
            "input_boundary": {
                "bounded_json_only": True,
                "manifest_content_opened": True,
                "training_receipt_content_opened": True,
                "checkpoint_content_opened": False,
                "evaluation_content_opened": False,
                "progress_content_opened": False,
                "trajectory_hdf5_content_opened": False,
                "runtime_started": False,
            },
        }


def _rollout_plan_snapshot(plan: RolloutPlan) -> dict[str, Any]:
    """Return the immutable, scheduler-visible identity of one rollout plan."""

    return {
        "schema": ROLLOUT_SNAPSHOT_SCHEMA,
        "root": str(plan.root),
        "seed": int(plan.seed),
        "run_id": str(plan.run_id),
        "nonce": str(plan.nonce),
        "manifest": {
            "path": str(plan.manifest),
            "canonical_sha256": str(plan.manifest_sha256),
            "file_sha256": str(plan.manifest_file_sha256),
        },
        "training_receipt": {
            "path": str(plan.training_receipt),
            "file_sha256": str(plan.training_receipt_sha256),
            "canonical_sha256": str(plan.training_receipt_canonical_sha256),
        },
        "checkpoint": dict(plan.checkpoint),
        "checkpoint_metadata": dict(plan.checkpoint_metadata),
        "namespace": str(plan.namespace),
        "outputs": {key: str(value) for key, value in plan.outputs.items()},
        "command": list(plan.command),
        "env_overrides": dict(plan.env),
        "command_sha256": str(plan.command_sha256),
        "python_metadata": dict(plan.python_metadata),
        "core_learning_metadata": dict(plan.core_learning_metadata),
        "digests": {
            "manifest_canonical_sha256": str(plan.manifest_sha256),
            "manifest_file_sha256": str(plan.manifest_file_sha256),
            "training_receipt_file_sha256": str(plan.training_receipt_sha256),
            "training_receipt_canonical_sha256": str(
                plan.training_receipt_canonical_sha256
            ),
            "checkpoint_sha256": str(plan.checkpoint["sha256"]),
            "checkpoint_bytes": int(plan.checkpoint["bytes"]),
            "command_sha256": str(plan.command_sha256),
        },
    }


def rollout_plan_snapshot(plan: RolloutPlan) -> dict[str, Any]:
    """Return a detached copy of the sealed plan snapshot."""

    if not isinstance(plan, RolloutPlan):
        _fail("rollout snapshot requires a RolloutPlan")
    current = _rollout_plan_snapshot(plan)
    if canonical_digest(current) != plan.stable_snapshot_sha256:
        _fail("RolloutPlan stable snapshot was mutated after construction")
    return json.loads(canonical_json(current))


def rollout_plan_snapshot_digest(plan: RolloutPlan) -> str:
    """Return the sealed digest, rejecting mutable-plan drift first."""

    rollout_plan_snapshot(plan)
    return str(plan.stable_snapshot_sha256)


def validate_rollout_plan_snapshot(
    value: Any,
    name: str = "rollout_snapshot",
) -> dict[str, Any]:
    """Validate a serialized snapshot without granting execution authority."""

    snapshot = dict(_mapping(value, name))
    _reject_unknown(
        snapshot,
        {
            "schema", "root", "seed", "run_id", "nonce", "manifest",
            "training_receipt", "checkpoint", "checkpoint_metadata", "namespace",
            "outputs", "command", "env_overrides", "command_sha256",
            "python_metadata", "core_learning_metadata", "digests",
        },
        name,
    )
    _exact(snapshot, "schema", ROLLOUT_SNAPSHOT_SCHEMA, name)
    root = _absolute_path(_string(snapshot.get("root"), f"{name}.root"), f"{name}.root")
    _validate_seed(snapshot.get("seed"))
    _validate_nonce(snapshot.get("nonce"), f"{name}.nonce")
    _string(snapshot.get("run_id"), f"{name}.run_id")
    _absolute_path(_string(snapshot.get("namespace"), f"{name}.namespace"), f"{name}.namespace")

    manifest = dict(_mapping(snapshot.get("manifest"), f"{name}.manifest"))
    _reject_unknown(manifest, {"path", "canonical_sha256", "file_sha256"}, f"{name}.manifest")
    _absolute_path(_string(manifest.get("path"), f"{name}.manifest.path"), f"{name}.manifest.path")
    _sha(manifest.get("canonical_sha256"), f"{name}.manifest.canonical_sha256")
    _sha(manifest.get("file_sha256"), f"{name}.manifest.file_sha256")

    training = dict(
        _mapping(snapshot.get("training_receipt"), f"{name}.training_receipt")
    )
    _reject_unknown(
        training,
        {"path", "file_sha256", "canonical_sha256"},
        f"{name}.training_receipt",
    )
    _absolute_path(
        _string(training.get("path"), f"{name}.training_receipt.path"),
        f"{name}.training_receipt.path",
    )
    _sha(training.get("file_sha256"), f"{name}.training_receipt.file_sha256")
    _sha(
        training.get("canonical_sha256"),
        f"{name}.training_receipt.canonical_sha256",
    )

    checkpoint = dict(_mapping(snapshot.get("checkpoint"), f"{name}.checkpoint"))
    _absolute_path(_string(checkpoint.get("path"), f"{name}.checkpoint.path"), f"{name}.checkpoint.path")
    _sha(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")
    _int(checkpoint.get("bytes"), f"{name}.checkpoint.bytes", 1)
    checkpoint_metadata = dict(
        _mapping(snapshot.get("checkpoint_metadata"), f"{name}.checkpoint_metadata")
    )
    for key in ("path", "bytes", "mode", "mtime_ns"):
        if key not in checkpoint_metadata:
            _fail(f"{name}.checkpoint_metadata.{key} is missing")
    _exact(checkpoint_metadata, "path", checkpoint["path"], f"{name}.checkpoint_metadata")
    _exact(checkpoint_metadata, "bytes", checkpoint["bytes"], f"{name}.checkpoint_metadata")

    command = snapshot.get("command")
    if not isinstance(command, list) or not command or any(
        not isinstance(item, str) or not item for item in command
    ):
        _fail(f"{name}.command must be a non-empty string list")
    env = _mapping(snapshot.get("env_overrides"), f"{name}.env_overrides")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
        _fail(f"{name}.env_overrides must contain string pairs")
    _sha(snapshot.get("command_sha256"), f"{name}.command_sha256")
    if snapshot["command_sha256"] != command_digest(command, root, env):
        _fail(f"{name}.command_sha256 does not match the exact command")

    digests = dict(_mapping(snapshot.get("digests"), f"{name}.digests"))
    _reject_unknown(
        digests,
        {
            "manifest_canonical_sha256", "manifest_file_sha256",
            "training_receipt_file_sha256", "training_receipt_canonical_sha256",
            "checkpoint_sha256", "checkpoint_bytes", "command_sha256",
        },
        f"{name}.digests",
    )
    for key in (
        "manifest_canonical_sha256", "manifest_file_sha256",
        "training_receipt_file_sha256", "training_receipt_canonical_sha256",
        "checkpoint_sha256", "command_sha256",
    ):
        _sha(digests.get(key), f"{name}.digests.{key}")
    _int(digests.get("checkpoint_bytes"), f"{name}.digests.checkpoint_bytes", 1)
    expected_digest_fields = {
        "manifest_canonical_sha256": manifest["canonical_sha256"],
        "manifest_file_sha256": manifest["file_sha256"],
        "training_receipt_file_sha256": training["file_sha256"],
        "training_receipt_canonical_sha256": training["canonical_sha256"],
        "checkpoint_sha256": checkpoint["sha256"],
        "checkpoint_bytes": checkpoint["bytes"],
        "command_sha256": snapshot["command_sha256"],
    }
    if digests != expected_digest_fields:
        _fail(f"{name}.digests are inconsistent with the snapshot fields")
    return json.loads(canonical_json(snapshot))


def reconcile_rollout_snapshot(
    snapshot: Mapping[str, Any],
    *,
    manifest_descriptor: Mapping[str, Any],
    manifest_payload: Mapping[str, Any],
    training_descriptor: Mapping[str, Any],
    training_payload: Mapping[str, Any],
    checkpoint_descriptor: Mapping[str, Any],
    expected_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    """Cross-bind a plan snapshot to a later stable descriptor reread.

    This function is deliberately data-only: it never creates a namespace,
    reads an authority, starts a process, or changes any external state.
    """

    expected = validate_rollout_plan_snapshot(snapshot)
    expected_digest = canonical_digest(expected)
    if expected_snapshot_sha256 is not None:
        _sha(expected_snapshot_sha256, "expected_snapshot_sha256")
        if expected_snapshot_sha256 != expected_digest:
            _fail("RolloutPlan snapshot digest is inconsistent with its fields")

    def _descriptor(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
        _mapping(value, name)
        _absolute_path(_string(value.get("path"), f"{name}.path"), f"{name}.path")
        _sha(value.get("sha256"), f"{name}.sha256")
        _int(value.get("bytes"), f"{name}.bytes", 1)
        return value

    observed_manifest = _descriptor(manifest_descriptor, "final manifest")
    observed_training = _descriptor(training_descriptor, "final training receipt")
    observed_checkpoint = _descriptor(checkpoint_descriptor, "final checkpoint")
    manifest_record = _mapping(expected["manifest"], "rollout_snapshot.manifest")
    training_record = _mapping(
        expected["training_receipt"], "rollout_snapshot.training_receipt"
    )
    checkpoint_record = _mapping(expected["checkpoint"], "rollout_snapshot.checkpoint")

    for label, observed, expected_path, expected_sha in (
        (
            "manifest",
            observed_manifest,
            manifest_record["path"],
            manifest_record["file_sha256"],
        ),
        (
            "training receipt",
            observed_training,
            training_record["path"],
            training_record["file_sha256"],
        ),
        (
            "checkpoint",
            observed_checkpoint,
            checkpoint_record["path"],
            checkpoint_record["sha256"],
        ),
    ):
        if observed["path"] != expected_path:
            _fail(f"{label} path drifted from the RolloutPlan snapshot")
        if observed["sha256"] != expected_sha:
            _fail(f"{label} file digest drifted from the RolloutPlan snapshot")

    manifest_canonical = canonical_digest(manifest_payload)
    if manifest_canonical != manifest_record["canonical_sha256"]:
        _fail("manifest canonical digest drifted from the RolloutPlan snapshot")
    training_canonical = canonical_digest(training_payload)
    if training_canonical != training_record["canonical_sha256"]:
        _fail("training receipt canonical digest drifted from the RolloutPlan snapshot")
    if observed_checkpoint["bytes"] != checkpoint_record["bytes"]:
        _fail("checkpoint byte count drifted from the RolloutPlan snapshot")

    checkpoint_metadata = _mapping(
        expected["checkpoint_metadata"], "rollout_snapshot.checkpoint_metadata"
    )
    for key in ("path", "bytes", "mode", "mtime_ns"):
        if observed_checkpoint.get(key) != checkpoint_metadata.get(key):
            _fail(f"checkpoint metadata field {key} drifted from the RolloutPlan snapshot")

    outputs = {
        key: Path(value)
        for key, value in _mapping(expected["outputs"], "rollout_snapshot.outputs").items()
    }
    command = expected["command"]
    expected_command = _command_for(
        root=Path(expected["root"]),
        python=Path(command[0]),
        manifest=Path(manifest_record["path"]),
        checkpoint=Path(checkpoint_record["path"]),
        outputs=outputs,
    )
    if list(expected_command) != command:
        _fail("exact command drifted from the RolloutPlan snapshot")
    observed_command_sha256 = command_digest(
        command, expected["root"], expected["env_overrides"]
    )
    if observed_command_sha256 != expected["command_sha256"]:
        _fail("command digest drifted from the RolloutPlan snapshot")

    observed_digests = {
        "manifest_canonical_sha256": manifest_canonical,
        "manifest_file_sha256": observed_manifest["sha256"],
        "training_receipt_file_sha256": observed_training["sha256"],
        "training_receipt_canonical_sha256": training_canonical,
        "checkpoint_sha256": observed_checkpoint["sha256"],
        "checkpoint_bytes": observed_checkpoint["bytes"],
        "command_sha256": observed_command_sha256,
    }
    if observed_digests != expected["digests"]:
        _fail("exact manifest/training/checkpoint/command digest set drifted")

    observed_snapshot = json.loads(canonical_json(expected))
    observed_snapshot["manifest"]["canonical_sha256"] = manifest_canonical
    observed_snapshot["manifest"]["file_sha256"] = observed_manifest["sha256"]
    observed_snapshot["training_receipt"]["file_sha256"] = observed_training["sha256"]
    observed_snapshot["training_receipt"]["canonical_sha256"] = training_canonical
    observed_snapshot["checkpoint"]["sha256"] = observed_checkpoint["sha256"]
    observed_snapshot["checkpoint"]["bytes"] = observed_checkpoint["bytes"]
    observed_snapshot["checkpoint_metadata"]["bytes"] = observed_checkpoint["bytes"]
    observed_snapshot["digests"] = observed_digests
    observed_digest = canonical_digest(observed_snapshot)
    if observed_digest != expected_digest:
        _fail("final reread plan digest drifted from the RolloutPlan snapshot")
    return {
        "schema": ROLLOUT_RECONCILIATION_SCHEMA,
        "plan_sha256": expected_digest,
        "observed_plan_sha256": observed_digest,
        "digests": observed_digests,
        "command_sha256": observed_command_sha256,
        "manifest_file_sha256": observed_manifest["sha256"],
        "training_receipt_file_sha256": observed_training["sha256"],
        "checkpoint_sha256": observed_checkpoint["sha256"],
        "checkpoint_bytes": observed_checkpoint["bytes"],
        "cross_bound": True,
        "diagnostic_only": True,
        "credit": 0,
    }


def reconcile_plan_snapshot(
    plan: RolloutPlan,
    *,
    manifest_descriptor: Mapping[str, Any],
    manifest_payload: Mapping[str, Any],
    training_descriptor: Mapping[str, Any],
    training_payload: Mapping[str, Any],
    checkpoint_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconcile a sealed ``RolloutPlan`` against a later stable reread."""

    snapshot = rollout_plan_snapshot(plan)
    return reconcile_rollout_snapshot(
        snapshot,
        manifest_descriptor=manifest_descriptor,
        manifest_payload=manifest_payload,
        training_descriptor=training_descriptor,
        training_payload=training_payload,
        checkpoint_descriptor=checkpoint_descriptor,
        expected_snapshot_sha256=rollout_plan_snapshot_digest(plan),
    )


def build_plan(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    manifest: Path | str,
    training_receipt: Path | str,
    checkpoint: Path | str | None = None,
    run_id: str | None = None,
    nonce: str,
    output_namespace: Path | str,
    gpu_index: int = 0,
    python_executable: Path | str | None = None,
) -> RolloutPlan:
    """Build one non-launching plan from explicit current-manifest identities."""

    root = _absolute_path(root, "root")
    seed = _validate_seed(seed)
    nonce = _validate_nonce(nonce)
    if type(gpu_index) is not int or not 0 <= gpu_index < GPU_COUNT:
        _fail(f"gpu_index must be an integer in [0, {GPU_COUNT})")
    manifest_path = _absolute_path(manifest, "manifest", root=root)
    training_path = _absolute_path(training_receipt, "training_receipt", root=root)
    manifest_payload, manifest_source = _read_bounded_json(
        manifest_path, root=root, name="manifest", max_bytes=MAX_MANIFEST_BYTES
    )
    manifest_sha256 = _validate_manifest(manifest_payload, manifest_source, path=manifest_path)
    training_payload, training_source = _read_bounded_json(
        training_path, root=root, name="training_receipt", max_bytes=MAX_JSON_BYTES
    )
    declared_checkpoint = checkpoint
    if declared_checkpoint is None:
        checkpoint_value = _mapping(training_payload.get("checkpoint"), "training_receipt.checkpoint")
        declared_checkpoint = checkpoint_value.get("path")
    checkpoint_path = _absolute_path(declared_checkpoint, "checkpoint", root=root)
    training = _validate_training_receipt(
        training_payload,
        training_source,
        seed=seed,
        manifest_sha256=manifest_sha256,
        checkpoint_path=checkpoint_path,
    )
    if run_id is not None and run_id != training["run_id"]:
        _fail("explicit run_id differs from the v3 training receipt")
    namespace = _absolute_path(output_namespace, "output_namespace", root=root)
    _validate_namespace(namespace, seed, nonce)
    python = _absolute_path(
        python_executable if python_executable is not None else root / ".venv" / "bin" / "python",
        "python_executable",
        root=root,
    )
    core_learning = root / "scripts" / "core_learning.py"
    python_metadata = _metadata(python, "Python executable", allow_leaf_symlink=True)
    core_learning_metadata = _metadata(core_learning, "core_learning.py")
    outputs = _output_paths(namespace, root, seed, nonce, manifest_sha256)
    _validate_output_paths(outputs, root)
    command = _command_for(
        root=root,
        python=python,
        manifest=manifest_path,
        checkpoint=checkpoint_path,
        outputs=outputs,
    )
    env = {
        "CUDA_VISIBLE_DEVICES": str(gpu_index),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    command_sha256 = command_digest(command, root, env)
    return RolloutPlan(
        root=root,
        seed=seed,
        run_id=training["run_id"],
        nonce=nonce,
        manifest=manifest_path,
        manifest_sha256=manifest_sha256,
        manifest_file_sha256=str(manifest_source["sha256"]),
        training_receipt=training_path,
        training_receipt_sha256=str(training_source["sha256"]),
        training_receipt_canonical_sha256=canonical_digest(training_payload),
        checkpoint=training["checkpoint"],
        checkpoint_metadata=training["checkpoint_metadata"],
        namespace=namespace,
        outputs=outputs,
        command=command,
        env=env,
        command_sha256=command_sha256,
        python_metadata=python_metadata,
        core_learning_metadata=core_learning_metadata,
    )


def _parse_bindings(values: Sequence[str], label: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw in values:
        if "=" not in raw:
            _fail(f"{label} binding must use SEED=PATH")
        seed_text, path = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError:
            _fail(f"{label} binding seed is not an integer: {seed_text!r}")
        seed = _validate_seed(seed)
        if seed in result:
            _fail(f"duplicate {label} binding for seed {seed}")
        result[seed] = path
    return result


def build_matrix(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str,
    training_receipts: Mapping[int, Path | str],
    checkpoints: Mapping[int, Path | str] | None = None,
    nonces: Mapping[int, str] | None = None,
    output_root: Path | str = "/tmp",
    gpu_indices: Mapping[int, int] | None = None,
) -> tuple[RolloutPlan, ...]:
    """Build the exact three-seed plan set with fresh unique namespaces."""

    root_path = _absolute_path(root, "root")
    output_root_path = _absolute_path(output_root, "output_root")
    _assert_no_symlink_components(output_root_path, "output_root")
    if set(training_receipts) != set(SEEDS):
        _fail(f"training_receipts must cover exactly {SEEDS}")
    if checkpoints is not None and set(checkpoints) != set(SEEDS):
        _fail(f"checkpoints must cover exactly {SEEDS}")
    if nonces is not None and set(nonces) != set(SEEDS):
        _fail(f"nonces must cover exactly {SEEDS}")
    selected: dict[int, str] = {}
    for seed in SEEDS:
        selected[seed] = _validate_nonce(
            nonces[seed] if nonces is not None else secrets.token_hex(16),
            f"nonce.seed{seed}",
        )
    if len(set(selected.values())) != len(SEEDS):
        _fail("per-seed nonces must be unique")
    plans: list[RolloutPlan] = []
    namespaces: set[Path] = set()
    for seed in SEEDS:
        namespace = _namespace_for(seed, selected[seed], output_root_path)
        if namespace in namespaces:
            _fail("per-seed namespaces must be unique")
        namespaces.add(namespace)
        plans.append(
            build_plan(
                root_path,
                seed=seed,
                manifest=manifest,
                training_receipt=training_receipts[seed],
                checkpoint=None if checkpoints is None else checkpoints[seed],
                nonce=selected[seed],
                output_namespace=namespace,
                gpu_index=0 if gpu_indices is None else gpu_indices.get(seed, 0),
            )
        )
    return tuple(plans)


def execute_plan(plan: RolloutPlan, capability: Mapping[str, Any] | None = None) -> None:
    """Explicit deny boundary for future execution authority.

    The current deliverable is a planning/receipt contract only.  Even a
    caller that presents a capability-shaped object cannot accidentally start
    a process until a separately reviewed executor is implemented.
    """

    if not isinstance(plan, RolloutPlan):
        _fail("execute_plan requires a RolloutPlan")
    if capability is None:
        _fail("audited execute capability is required; naked launch is forbidden")
    _fail(
        f"{EXECUTE_CAPABILITY_SCHEMA} is not admitted by this bounded contract; "
        "no process was started"
    )


def _receipt_artifact(value: Any, name: str, *, suffix: str | None = None) -> dict[str, Any]:
    artifact = _declared_artifact(value, name, suffix=suffix)
    return {
        "path": artifact["path"],
        "sha256": artifact["sha256"],
        "bytes": artifact["bytes"],
    }


def _command_option(command: Sequence[str], option: str, name: str) -> str:
    positions = [index for index, token in enumerate(command) if token == option]
    if len(positions) != 1 or positions[0] + 1 >= len(command):
        _fail(f"{name} must contain exactly one {option} option with a value")
    value = command[positions[0] + 1]
    if not isinstance(value, str) or not value:
        _fail(f"{name}.{option} value must be a non-empty string")
    return value


def _validate_namespace_claim(namespace: Any, nonce: Any, seed: int, name: str) -> tuple[str, str]:
    nonce_text = _validate_nonce(nonce, f"{name}.namespace_nonce")
    namespace_path = _absolute_path(_string(namespace, f"{name}.namespace"), f"{name}.namespace")
    # A receipt is produced after the runtime has created its namespace.  It
    # therefore uses the lexical/scope contract, but must not apply the
    # planner's fresh-output collision rejection to that existing namespace.
    _validate_namespace_shape(namespace_path, seed, nonce_text)
    # A terminal receipt names an already-created namespace, so the planner's
    # collision rule is not applicable to the receipt path itself.  Recheck
    # only lexical/scope/name identity here.
    return str(namespace_path), nonce_text


def _validate_terminal_receipt_payload(
    payload: Mapping[str, Any],
    *,
    seed: int,
    manifest_sha256: str | None = None,
    manifest_path: Path | None = None,
    expected_plan: RolloutPlan | None = None,
) -> dict[str, Any]:
    name = f"terminal_receipt.seed{seed}"
    allowed = {
        "schema", "report_id", "status", "source_bound", "seed", "run_id",
        "model", "model_kind", "hidden", "updates", "case_id", "split",
        "transitions", "frames", "namespace", "namespace_nonce", "command",
        "command_sha256", "cwd", "env_overrides", "manifest", "training_receipt",
        "checkpoint", "evaluation_artifact", "trajectory_artifact", "progress_artifact",
        "validator_artifact", "validator_receipt", "terminal_markers", "process_exit", "input_boundary",
        *ZERO_CREDIT.keys(), "zero_credit_only", "future_state_inputs",
    }
    _reject_unknown(payload, allowed, name)
    _reject_authority_aliases(payload, name)
    for key, expected in (
        ("schema", TERMINAL_RECEIPT_SCHEMA),
        ("report_id", f"f3-graph-raw-hidden16-seed{seed}-current-manifest-full835-terminal-v1"),
        ("status", "terminal_verified"),
        ("source_bound", True),
        ("seed", seed),
        ("model", MODEL),
        ("model_kind", MODEL),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("zero_credit_only", True),
        ("future_state_inputs", False),
    ):
        _exact(payload, key, expected, name)
    _zero_credit(payload, name)
    run_id, _ = _validate_run_id(payload.get("run_id"), seed, f"{name}.run_id")
    namespace, nonce = _validate_namespace_claim(
        payload.get("namespace"), payload.get("namespace_nonce"), seed, name
    )
    command = payload.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        _fail(f"{name}.command must be a non-empty string list")
    command_sha = _sha(payload.get("command_sha256"), f"{name}.command_sha256")
    env = _mapping(payload.get("env_overrides"), f"{name}.env_overrides")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
        _fail(f"{name}.env_overrides must contain string pairs")
    cwd = _absolute_path(_string(payload.get("cwd"), f"{name}.cwd"), f"{name}.cwd")
    digest = canonical_digest({
        "argv": command,
        "cwd": str(cwd),
        "env_overrides": dict(env),
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
    })
    if digest != command_sha:
        _fail(f"{name}.command_sha256 does not match canonical command identity")
    manifest = _receipt_artifact(payload.get("manifest"), f"{name}.manifest", suffix=".json")
    training_receipt = _receipt_artifact(payload.get("training_receipt"), f"{name}.training_receipt", suffix=".json")
    checkpoint = _receipt_artifact(payload.get("checkpoint"), f"{name}.checkpoint", suffix=".pt")
    if manifest_sha256 is not None and manifest["sha256"] != manifest_sha256:
        _fail(f"{name}.manifest.sha256 differs from current canonical manifest")
    checkpoint_value = _mapping(payload.get("checkpoint"), f"{name}.checkpoint")
    _exact(checkpoint_value, "update", UPDATES, f"{name}.checkpoint")
    evaluation = _receipt_artifact(payload.get("evaluation_artifact"), f"{name}.evaluation_artifact", suffix=".json")
    trajectory = _receipt_artifact(payload.get("trajectory_artifact"), f"{name}.trajectory_artifact", suffix=".h5")
    progress = _receipt_artifact(payload.get("progress_artifact"), f"{name}.progress_artifact", suffix=".json")
    validator_artifact = _receipt_artifact(payload.get("validator_artifact"), f"{name}.validator_artifact", suffix=".json")
    expected_outputs = {
        "evaluation": namespace + "-evaluation.json",
        "trajectory": namespace + "-trajectory.h5",
        "progress": namespace + "-evaluation-progress.json",
        "validator": namespace + "-hdf5-validation.json",
    }
    for artifact_name, artifact, expected_path in (
        ("evaluation_artifact", evaluation, expected_outputs["evaluation"]),
        ("trajectory_artifact", trajectory, expected_outputs["trajectory"]),
        ("progress_artifact", progress, expected_outputs["progress"]),
        ("validator_artifact", validator_artifact, expected_outputs["validator"]),
    ):
        if artifact["path"] != expected_path:
            _fail(f"{name}.{artifact_name}.path drifts from the fresh namespace")
    if manifest_path is not None and manifest["path"] != str(manifest_path):
        _fail(f"{name}.manifest.path drifts from the current canonical manifest")
    for option, expected in (
        ("--manifest", manifest["path"]),
        ("--checkpoint", checkpoint["path"]),
        ("--case-id", CASE_ID),
        ("--split", SPLIT),
        ("--maximum-steps", str(TRANSITIONS)),
        ("--chunk-size", str(CHUNK_SIZE)),
        ("--device", "cuda:0"),
        ("--trajectory-output", trajectory["path"]),
        ("--progress-output", progress["path"]),
        ("--output", evaluation["path"]),
    ):
        if _command_option(command, option, name) != expected:
            _fail(f"{name}.command {option} drifts from the bound identity")
    if "--diagnostic" not in command:
        _fail(f"{name}.command must remain diagnostic-only")
    if any(token in {"kill", "pkill", "stop", "restart", "--execute"} for token in command):
        _fail(f"{name}.command contains a forbidden process-control token")
    validator = _mapping(payload.get("validator_receipt"), f"{name}.validator_receipt")
    _reject_unknown(
        validator,
        {"schema", "status", "passed", "complete", "expected_transitions", "trajectory_transitions", "trajectory_frames", "production_artifacts_touched", "actual_future_state_inputs", "synthetic_only"},
        f"{name}.validator_receipt",
    )
    for key, expected in (
        ("schema", VALIDATOR_SCHEMA),
        ("status", "validated"),
        ("passed", True),
        ("complete", True),
        ("expected_transitions", TRANSITIONS),
        ("trajectory_transitions", TRANSITIONS),
        ("trajectory_frames", FRAMES),
        ("production_artifacts_touched", False),
        ("actual_future_state_inputs", False),
        ("synthetic_only", False),
    ):
        _exact(validator, key, expected, f"{name}.validator_receipt")
    process = _mapping(payload.get("process_exit"), f"{name}.process_exit")
    _reject_unknown(
        process,
        {"schema", "status", "evaluator_returncode", "launcher_returncode", "returncode", "evaluator_alive", "launcher_alive", "stopped_processes", "restarted_processes", "command_sha256", "observed_after_exit"},
        f"{name}.process_exit",
    )
    for key, expected in (
        ("schema", PROCESS_EXIT_SCHEMA),
        ("status", "exited_successfully"),
        ("evaluator_returncode", 0),
        ("launcher_returncode", 0),
        ("returncode", 0),
        ("evaluator_alive", False),
        ("launcher_alive", False),
        ("stopped_processes", 0),
        ("restarted_processes", 0),
        ("command_sha256", command_sha),
        ("observed_after_exit", True),
    ):
        _exact(process, key, expected, f"{name}.process_exit")
    markers = _mapping(payload.get("terminal_markers"), f"{name}.terminal_markers")
    _reject_unknown(markers, {"terminal", "execution_complete", "finite_rollout_complete", "terminal_status", "progress_is_not_completion"}, f"{name}.terminal_markers")
    for key, expected in (
        ("terminal", True),
        ("execution_complete", True),
        ("finite_rollout_complete", True),
        ("terminal_status", "completed"),
        ("progress_is_not_completion", True),
    ):
        _exact(markers, key, expected, f"{name}.terminal_markers")
    boundary = _mapping(payload.get("input_boundary"), f"{name}.input_boundary")
    for key in ("checkpoint_content_opened", "evaluation_content_opened", "progress_content_opened", "trajectory_hdf5_content_opened"):
        _exact(boundary, key, False, f"{name}.input_boundary")
    if expected_plan is not None:
        if command_sha != expected_plan.command_sha256 or namespace != str(expected_plan.namespace) or nonce != expected_plan.nonce:
            _fail(f"{name} drifts from the explicit rollout plan")
        if manifest["path"] != str(expected_plan.manifest) or checkpoint["path"] != expected_plan.checkpoint["path"]:
            _fail(f"{name} artifact identity drifts from the explicit rollout plan")
    return {
        "seed": seed,
        "run_id": run_id,
        "namespace": namespace,
        "namespace_nonce": nonce,
        "command_sha256": command_sha,
        "manifest": manifest,
        "training_receipt": training_receipt,
        "checkpoint": checkpoint,
        "evaluation_artifact": evaluation,
        "trajectory_artifact": trajectory,
        "progress_artifact": progress,
        "validator_artifact": validator_artifact,
        "validator_receipt": dict(validator),
        "process_exit": dict(process),
        "terminal_markers": dict(markers),
    }


def verify_terminal_receipt(
    receipt_path: Path | str,
    *,
    root: Path | str = LAB_ROOT,
    manifest_sha256: str | None = None,
    manifest_path: Path | str | None = None,
    expected_plan: RolloutPlan | None = None,
) -> dict[str, Any]:
    """Verify one receipt by opening only the bounded receipt JSON."""

    root_path = _absolute_path(root, "root")
    payload, source = _read_bounded_json(
        receipt_path, root=root_path, name="terminal_receipt", max_bytes=MAX_JSON_BYTES
    )
    seed = _validate_seed(payload.get("seed"))
    evidence = _validate_terminal_receipt_payload(
        payload,
        seed=seed,
        manifest_sha256=manifest_sha256,
        manifest_path=None if manifest_path is None else _absolute_path(manifest_path, "manifest", root=root_path),
        expected_plan=expected_plan,
    )
    return {
        "schema": TERMINAL_RECEIPT_SCHEMA,
        "status": "terminal_verified",
        "source": dict(source),
        "evidence": evidence,
        **ZERO_CREDIT,
    }


def _missing_row(seed: int, path: str | None, reason: str) -> dict[str, Any]:
    return {
        "seed": seed,
        "status": "missing" if path is None else "blocked_fail_closed",
        "path": path,
        "receipt": None,
        "blocked_reasons": [reason],
    }


def build_terminal_report(
    root: Path | str = LAB_ROOT,
    *,
    receipt_paths: Mapping[int, Path | str],
    manifest: Path | str | None = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Verify zero or more per-seed receipts without opening artifacts."""

    root_path = _absolute_path(root, "root")
    if set(receipt_paths) - set(SEEDS):
        _fail(f"receipt_paths contains an unknown seed: {sorted(set(receipt_paths) - set(SEEDS))}")
    manifest_source: dict[str, Any] | None = None
    manifest_sha: str | None = None
    manifest_path: Path | None = None
    blocked: list[str] = []
    if manifest is not None:
        try:
            manifest_path = _absolute_path(manifest, "manifest", root=root_path)
            manifest_payload, manifest_source = _read_bounded_json(
                manifest_path, root=root_path, name="manifest", max_bytes=MAX_MANIFEST_BYTES
            )
            manifest_sha = _validate_manifest(manifest_payload, manifest_source, path=manifest_path)
        except ContractError as error:
            blocked.append(str(error))
    rows: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    namespaces: set[str] = set()
    nonces: set[str] = set()
    digests: set[str] = set()
    for seed in SEEDS:
        path_value = receipt_paths.get(seed)
        if path_value is None:
            rows.append(_missing_row(seed, None, "terminal receipt is not configured"))
            continue
        path_text = str(path_value)
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = root_path / candidate
        if not os.path.lexists(candidate):
            reason = f"fail-closed: terminal receipt is missing: {candidate}"
            blocked.append(f"seed{seed}: {reason}")
            rows.append({"seed": seed, "status": "missing", "path": path_text, "receipt": None, "blocked_reasons": [reason]})
            continue
        try:
            result = verify_terminal_receipt(
                path_value,
                root=root_path,
                manifest_sha256=manifest_sha,
                manifest_path=manifest_path,
            )
            evidence = result["evidence"]
            if evidence["namespace"] in namespaces:
                _fail(f"seed{seed} reuses a terminal namespace")
            if evidence["namespace_nonce"] in nonces:
                _fail(f"seed{seed} reuses a terminal nonce")
            if evidence["command_sha256"] in digests:
                _fail(f"seed{seed} reuses a terminal command digest")
            namespaces.add(evidence["namespace"])
            nonces.add(evidence["namespace_nonce"])
            digests.add(evidence["command_sha256"])
            verified.append(result)
            rows.append({"seed": seed, "status": "terminal_verified", "path": path_text, "receipt": result})
        except ContractError as error:
            blocked.append(f"seed{seed}: {error}")
            rows.append(_missing_row(seed, path_text, str(error)))
    source_bound = len(verified) == len(SEEDS) and not blocked
    report = {
        "schema": TERMINAL_REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "terminal_verified_diagnostic" if source_bound else "blocked_fail_closed",
        "mode": "receipt_only_terminal_verification",
        "source_bound": source_bound,
        "launch_allowed": False,
        "formal_admission": False,
        "terminal_receipts_verified": len(verified),
        "terminal_receipts_expected": len(SEEDS),
        "manifest": manifest_source,
        "seed_rows": rows,
        "blocked_reasons": blocked,
        "expected_contract": {
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "seeds": list(SEEDS),
            "fresh_32_hex_nonce": True,
            "zero_credit_only": True,
        },
        **ZERO_CREDIT,
        "zero_credit_only": True,
        "input_boundary": {
            "bounded_json_only": True,
            "manifest_content_opened": manifest_source is not None,
            "terminal_receipt_json_opened": len(verified),
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "progress_content_opened": False,
            "trajectory_hdf5_content_opened": False,
        },
        "side_effects": {
            "runtime_started": False,
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
    }
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _exact(report, "schema", TERMINAL_REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "launch_allowed", False, "report")
        _zero_credit(report, "report")
        rows = report.get("seed_rows")
        if not isinstance(rows, list) or len(rows) != len(SEEDS):
            _fail("report.seed_rows must contain exactly three rows")
        seeds = [row.get("seed") for row in rows if isinstance(row, Mapping)]
        if sorted(seeds) != list(SEEDS):
            _fail("report.seed_rows has the wrong seed set")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in ("runtime_started", "queue_submissions", "registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"):
            if key not in side_effects:
                _fail(f"report.side_effects.{key} is missing")
            if side_effects[key] not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
    except ContractError as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    rows = report.get("seed_rows", [])
    lines = [
        "# F3 graph_raw hidden16 current-manifest full835 rollout contract",
        "",
        f"- status: `{report.get('status')}`",
        f"- launch_allowed: `{report.get('launch_allowed')}`",
        f"- terminal receipts: `{report.get('terminal_receipts_verified', 0)}/{report.get('terminal_receipts_expected', 3)}`",
        "- protocol: `graph_raw`, hidden `16`, updates `500`, case `F3_DEV_00_a0p903125`, split `test`, `835 transitions / 836 frames`",
        "- boundary: bounded JSON and stat-only small metadata; checkpoint/HDF5/trajectory/evaluation/progress content is not opened",
        "- authority: diagnostic-only; formal/T1/T2/qualification false and credit 0",
        "",
        "| seed | status | receipt |",
        "|---:|---|---|",
    ]
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, Mapping):
            lines.append(f"| {row.get('seed')} | `{row.get('status')}` | `{row.get('path')}` |" )
    blocked = report.get("blocked_reasons")
    if blocked:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in blocked if isinstance(item, str))
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--training-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--checkpoint", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--nonce", action="append", default=[], metavar="SEED=NONCE")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--seed", type=int, help="build one plan; omit for the three-seed report")
    parser.add_argument("--run-id")
    parser.add_argument("--output-namespace", type=Path)
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--python-executable", type=Path)
    parser.add_argument("--verify-terminal-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument("--execute", action="store_true", help="always rejected; requires a future audited executor")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.execute:
            _fail("naked --execute is forbidden; audited execute capability is not admitted")
        if args.verify_report is not None:
            payload, _ = _read_bounded_json(
                args.verify_report,
                root=_absolute_path(args.root, "root"),
                name="report",
                max_bytes=MAX_JSON_BYTES,
            )
            errors = validate_report(payload)
            if errors:
                _fail("; ".join(errors))
            print(json.dumps({"status": "verified", "report": str(args.verify_report)}, ensure_ascii=False))
            return 0
        if args.verify_terminal_receipt:
            receipts = _parse_bindings(args.verify_terminal_receipt, "verify-terminal-receipt")
            report = build_terminal_report(args.root, receipt_paths=receipts, manifest=args.manifest)
            _write_json(args.report_output, report)
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return 0
        training = _parse_bindings(args.training_receipt, "training-receipt") if args.training_receipt else {}
        checkpoints = _parse_bindings(args.checkpoint, "checkpoint") if args.checkpoint else {}
        nonces = _parse_bindings(args.nonce, "nonce") if args.nonce else {}
        if args.seed is not None:
            if args.output_namespace is None or len(training) != 1 or args.seed not in training:
                _fail("single-plan mode requires --seed, --output-namespace, and one matching --training-receipt")
            checkpoint = checkpoints.get(args.seed)
            nonce = nonces.get(args.seed)
            if nonce is None:
                _fail("single-plan mode requires an explicit fresh --nonce")
            plan = build_plan(
                args.root,
                seed=args.seed,
                manifest=args.manifest,
                training_receipt=training[args.seed],
                checkpoint=checkpoint,
                run_id=args.run_id,
                nonce=nonce,
                output_namespace=args.output_namespace,
                gpu_index=args.gpu_index,
                python_executable=args.python_executable,
            )
            print(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True))
            return 0
        if not training:
            # Default report is deliberately useful even before v3 receipts
            # exist: it records the fail-closed absence without guessing.
            expected = {
                seed: f"/tmp/f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json"
                for seed in SEEDS
            }
            report = build_terminal_report(args.root, receipt_paths=expected, manifest=args.manifest)
        else:
            if set(training) != set(SEEDS):
                _fail(f"matrix mode requires training receipts for exactly {SEEDS}")
            plans = build_matrix(
                args.root,
                manifest=args.manifest,
                training_receipts=training,
                checkpoints=checkpoints or None,
                nonces=nonces or None,
                output_root=args.output_root,
            )
            report = {
                "schema": TERMINAL_REPORT_SCHEMA,
                "report_id": REPORT_ID,
                "status": "dry_run_matrix_ready",
                "mode": "bounded_identity_planning",
                "source_bound": True,
                "launch_allowed": False,
                "terminal_receipts_verified": 0,
                "terminal_receipts_expected": len(SEEDS),
                "seed_rows": [{"seed": plan.seed, "status": "dry_run_ready", "plan": plan.as_dict()} for plan in plans],
                "blocked_reasons": ["real terminal receipts are absent; planning is non-authorizing"],
                **ZERO_CREDIT,
                "zero_credit_only": True,
                "side_effects": {
                    "runtime_started": False, "processes_started": 0, "processes_stopped": 0,
                    "processes_restarted": 0, "queue_submissions": 0, "registry_writes": 0,
                    "ledger_writes": 0, "denominator_writes": 0, "gate_writes": 0,
                    "completion_writes": 0, "plan_writes": 0,
                },
            }
        _write_json(args.report_output, report)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except ContractError as error:
        print(json.dumps({"status": "blocked_fail_closed", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
