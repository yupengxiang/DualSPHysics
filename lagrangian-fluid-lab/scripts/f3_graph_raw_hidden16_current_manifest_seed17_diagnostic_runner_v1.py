#!/usr/bin/env python3
"""Bounded single-seed diagnostic runner for graph_raw hidden16.

This is an additive, one-seed boundary.  It consumes only the current v3
training receipt, its declared stat-only checkpoint metadata, the current
manifest, and a read-only GPU-2 resource admission snapshot.  It reuses the
existing rollout launcher's command builder so that the command is exactly
the same ``core_learning.py evaluate`` command (835 transitions / 836
frames, ``--diagnostic`` and ``--device cuda:0``), with
``CUDA_VISIBLE_DEVICES=2`` in the environment.

The default mode is a dry-run.  The namespace is atomically reserved under
``/tmp`` and a bounded identity report is written, but no evaluator is
started.  Diagnostic execution has two independent deny gates: caller
supplied process/capability objects are never accepted, and this module does
not currently contain an executable capability.  If a future separately
reviewed change installs that private capability, execution still requires a
fresh reservation, stable input descriptor snapshots, a real captured
``subprocess.Popen``/``wait`` lifecycle, natural return code zero, the
independent F3 HDF5 validator, hardened HDF5 link checks, and exact
cross-binding of evaluation/trajectory/progress/validator artifacts before a
zero-credit diagnostic receipt can be minted.

No solver, worker, queue, registry, ledger, denominator, gate, completion,
or PLAN state is touched.  This file never stops or restarts another job and
never performs a batch launch.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

import h5py

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as hdf5_validator
from scripts import f3_graph_raw_hidden16_current_manifest_audited_executor_v1 as admission
from scripts import f3_graph_raw_hidden16_current_manifest_rollout_launcher_v1 as launcher


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 17
GPU_INDEX = 2
MODEL = launcher.MODEL
HIDDEN = launcher.HIDDEN
UPDATES = launcher.UPDATES
CASE_ID = launcher.CASE_ID
SPLIT = launcher.SPLIT
TRANSITIONS = launcher.TRANSITIONS
FRAMES = launcher.FRAMES
CHUNK_SIZE = launcher.CHUNK_SIZE
PROGRESS_EVERY = launcher.PROGRESS_EVERY

MANIFEST_SCHEMA = launcher.MANIFEST_SCHEMA
TRAINING_SCHEMA = launcher.TRAINING_SCHEMA
CHECKPOINT_SCHEMA = launcher.CHECKPOINT_SCHEMA
REPORT_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest.seed17.diagnostic_runner.report.v1"
)
PLAN_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest.seed17.diagnostic_runner.plan.v1"
)
RESERVATION_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest.seed17.diagnostic_runner.namespace_reservation.v1"
)
VALIDATOR_ARTIFACT_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest.seed17.diagnostic_validator_artifact.v1"
)
DIAGNOSTIC_RECEIPT_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest.seed17.diagnostic_receipt.v1"
)
REPORT_ID = "f3-graph-raw-hidden16-current-manifest-seed17-diagnostic-runner-v1"

DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_TRAINING_RECEIPT = Path(
    "/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"
)
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RAW-HIDDEN16-SEED17-DIAGNOSTIC-RUNNER-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_HDF5_BYTES = 32 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")

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

# Captured at import time.  A caller cannot replace subprocess.Popen after
# import and then promote the replacement into process evidence.
_REAL_POPEN = subprocess.Popen
_PROCESS_RECORD_SECRET = secrets.token_bytes(32)

# Deliberately absent.  Installing this is a separately reviewed code change;
# a JSON field, boolean, object, or callback supplied by a caller can never
# install it.
_DIAGNOSTIC_EXECUTE_CAPABILITY: object | None = None


class RunnerError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing input."""


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
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}; observed {observed!r}")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        _fail(f"{name} contains unknown fields: {unknown}")


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


def _absolute_path(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a lexical path alias")
    normalized = Path(os.path.normpath(str(candidate)))
    if normalized != candidate:
        _fail(f"{name} uses a lexical path alias")
    return normalized


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlink_components(path: Path, name: str, *, allow_leaf: bool = False) -> None:
    current = Path(path.anchor or "/")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for index, part in enumerate(parts):
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if allow_leaf and index == len(parts) - 1:
                return
            _fail(f"{name} has a missing path component: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode) and not (allow_leaf and index == len(parts) - 1):
            _fail(f"{name} contains a symlink component: {current}")


def _stable_descriptor(path: Path | str, name: str, *, allow_leaf_symlink: bool = False) -> dict[str, Any]:
    """Capture an fd/stat descriptor without opening content."""

    candidate = _absolute_path(path, name)
    _reject_symlink_components(candidate.parent, f"{name} parent")
    try:
        before = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    resolved = candidate
    leaf_symlink = stat.S_ISLNK(before.st_mode)
    if leaf_symlink:
        if not allow_leaf_symlink:
            _fail(f"{name} is a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            _fail(f"cannot resolve {name}: {error}")
        _reject_symlink_components(resolved.parent, f"{name} target parent")
        try:
            before = os.lstat(resolved)
        except OSError as error:
            _fail(f"cannot inspect resolved {name}: {error}")
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    return {
        "path": str(candidate),
        "resolved_path": str(resolved),
        "dev": int(before.st_dev),
        "ino": int(before.st_ino),
        "bytes": int(before.st_size),
        "mode": int(stat.S_IMODE(before.st_mode)),
        "nlink": int(before.st_nlink),
        "mtime_ns": int(before.st_mtime_ns),
        "leaf_symlink": bool(leaf_symlink),
        "content_opened": False,
    }


def _descriptor_identity(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(value.get(key) for key in (
        "path", "resolved_path", "dev", "ino", "bytes", "mode", "nlink", "mtime_ns",
        "leaf_symlink",
    ))


def _read_bounded_json(path: Path | str, name: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = _absolute_path(path, name)
    _reject_symlink_components(candidate, name)
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
    except (UnicodeError, json.JSONDecodeError, RunnerError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    _walk_json(payload, name)
    if not isinstance(payload, dict):
        _fail(f"{name} must contain a JSON object")
    descriptor = {
        "path": str(candidate),
        "dev": int(before.st_dev),
        "ino": int(before.st_ino),
        "bytes": len(raw),
        "mode": int(stat.S_IMODE(before.st_mode)),
        "nlink": int(before.st_nlink),
        "mtime_ns": int(before.st_mtime_ns),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
    }
    return dict(payload), descriptor


def _validate_nonce(value: Any) -> str:
    nonce = _string(value, "namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail("namespace_nonce must be a non-zero 32-character lowercase hexadecimal value")
    return nonce


def _namespace(output_root: Path, nonce: str) -> Path:
    output_root = _absolute_path(output_root, "output_root")
    temp_root = Path(tempfile.gettempdir()).resolve()
    if output_root != temp_root and not _under(output_root, temp_root):
        _fail("output_root must remain under /tmp")
    return output_root / (
        f"f3-graph_raw500-hidden16-currentmanifest-seed{SEED}-full835-nonce{nonce}"
    )


def _reservation_payload(namespace: Path, nonce: str, plan_digest: str) -> dict[str, Any]:
    core = {
        "schema": RESERVATION_SCHEMA,
        "seed": SEED,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "namespace": str(namespace),
        "namespace_nonce": nonce,
        "plan_digest": plan_digest,
        "exclusive": True,
        "diagnostic_only": True,
    }
    return {**core, "reservation_sha256": canonical_digest(core)}


@dataclass(frozen=True)
class NamespaceReservation:
    namespace: Path
    marker: Path
    nonce: str
    payload: Mapping[str, Any]
    marker_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "namespace": str(self.namespace),
            "marker": str(self.marker),
            "nonce": self.nonce,
            "marker_sha256": self.marker_sha256,
            "payload": dict(self.payload),
            "exclusive": True,
            "reserved": True,
        }


def _reserve_namespace(namespace: Path, nonce: str, plan_digest: str) -> NamespaceReservation:
    _reject_symlink_components(namespace.parent, "namespace parent")
    if namespace.exists() or os.path.lexists(namespace):
        _fail(f"fresh namespace already exists: {namespace}")
    try:
        os.mkdir(namespace, 0o700)
    except FileExistsError:
        _fail(f"fresh namespace reservation raced with another owner: {namespace}")
    except OSError as error:
        _fail(f"cannot reserve fresh namespace: {error}")
    marker = namespace / ".reservation.json"
    payload = _reservation_payload(namespace, nonce, plan_digest)
    raw = (canonical_json(payload) + "\n").encode("utf-8")
    try:
        fd = os.open(
            marker,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        _fail(f"cannot write exclusive namespace reservation marker: {error}")
    return NamespaceReservation(
        namespace=namespace,
        marker=marker,
        nonce=nonce,
        payload=payload,
        marker_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _verify_reservation(reservation: NamespaceReservation, plan_digest: str) -> None:
    namespace = _absolute_path(reservation.namespace, "reservation.namespace")
    marker = _absolute_path(reservation.marker, "reservation.marker")
    if namespace != reservation.namespace or marker != reservation.marker:
        _fail("namespace reservation path drifted")
    if marker.parent != namespace or not namespace.is_dir():
        _fail("exclusive namespace reservation is missing")
    payload, descriptor = _read_bounded_json(marker, "namespace reservation marker", max_bytes=64 * 1024)
    _exact(payload, "schema", RESERVATION_SCHEMA, "reservation")
    _exact(payload, "seed", SEED, "reservation")
    _exact(payload, "model_kind", MODEL, "reservation")
    _exact(payload, "hidden", HIDDEN, "reservation")
    _exact(payload, "transitions", TRANSITIONS, "reservation")
    _exact(payload, "frames", FRAMES, "reservation")
    _exact(payload, "namespace", str(namespace), "reservation")
    _exact(payload, "namespace_nonce", reservation.nonce, "reservation")
    _exact(payload, "plan_digest", plan_digest, "reservation")
    _exact(payload, "exclusive", True, "reservation")
    _exact(payload, "diagnostic_only", True, "reservation")
    core = {key: payload[key] for key in payload if key != "reservation_sha256"}
    if _sha(payload.get("reservation_sha256"), "reservation.reservation_sha256") != canonical_digest(core):
        _fail("namespace reservation marker digest mismatch")
    if descriptor["sha256"] != reservation.marker_sha256:
        _fail("namespace reservation marker bytes drifted")


def _snapshot_inputs(plan: launcher.RolloutPlan) -> dict[str, dict[str, Any]]:
    checkpoint_path = Path(str(plan.checkpoint["path"]))
    checkpoint = _stable_descriptor(checkpoint_path, "checkpoint metadata", allow_leaf_symlink=False)
    if checkpoint["bytes"] != int(plan.checkpoint["bytes"]):
        _fail("checkpoint stat-only bytes differ from declared checkpoint metadata")
    checkpoint.update(
        {
            "declared_sha256": str(plan.checkpoint["sha256"]),
            "declared_bytes": int(plan.checkpoint["bytes"]),
            "content_opened": False,
        }
    )
    manifest, manifest_descriptor = _read_bounded_json(plan.manifest, "current manifest")
    training, training_descriptor = _read_bounded_json(plan.training_receipt, "v3 training receipt")
    # The launcher remains the identity authority for the exact current
    # manifest/training/checkpoint relationship.  The local reads above only
    # make the runner's descriptor snapshots explicit and auditable.
    _exact(manifest, "schema", MANIFEST_SCHEMA, "current manifest")
    _exact(training, "schema", TRAINING_SCHEMA, "v3 training receipt")
    python = _stable_descriptor(Path(plan.command[0]), "Python executable", allow_leaf_symlink=True)
    core_learning = _stable_descriptor(Path(plan.command[2]), "core_learning.py")
    return {
        "manifest": manifest_descriptor,
        "training_receipt": training_descriptor,
        "checkpoint": checkpoint,
        "python": python,
        "core_learning": core_learning,
    }


def _revalidate_input_snapshots(plan: "DiagnosticPlan") -> None:
    current = _snapshot_inputs(plan.identity_plan)
    for name, expected in plan.input_snapshots.items():
        observed = current.get(name)
        if observed is None:
            _fail(f"input snapshot {name} disappeared")
        if name in {"manifest", "training_receipt"}:
            keys = ("path", "dev", "ino", "bytes", "mode", "nlink", "mtime_ns", "sha256")
        else:
            keys = ("path", "resolved_path", "dev", "ino", "bytes", "mode", "nlink", "mtime_ns", "leaf_symlink")
        if any(observed.get(key) != expected.get(key) for key in keys):
            _fail(f"input descriptor snapshot changed: {name}")


def _exact_command_digest(plan: launcher.RolloutPlan) -> str:
    return canonical_digest(
        {
            "argv": list(plan.command),
            "cwd": str(plan.root),
            "env_overrides": dict(plan.env),
            "gpu_index": GPU_INDEX,
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
        }
    )


def _assert_exact_command(plan: launcher.RolloutPlan) -> None:
    expected = launcher.build_plan
    del expected  # Keep the command authority visibly tied to launcher.build_plan.
    command = plan.command
    if command[0] != str(Path(command[0])):
        _fail("exact command interpreter path is not lexical-stable")
    required = {
        "evaluate": 3,
        "--manifest": 4,
        "--data-root": 6,
        "--checkpoint": 8,
        "--case-id": 10,
        "--split": 12,
        "--maximum-steps": 14,
        "--chunk-size": 16,
        "--device": 18,
        "--progress-every": 20,
        "--trajectory-output": 22,
        "--progress-output": 24,
        "--output": 26,
    }
    for token, index in required.items():
        if len(command) <= index or command[index] != token:
            _fail(f"exact rollout command drifted at {token}")
    expected_values = {
        1: "-u",
        5: str(plan.manifest),
        7: str(plan.root),
        9: str(plan.checkpoint["path"]),
        11: CASE_ID,
        13: SPLIT,
        15: str(TRANSITIONS),
        17: str(CHUNK_SIZE),
        19: "cuda:0",
        21: str(PROGRESS_EVERY),
        23: str(plan.outputs["trajectory"]),
        25: str(plan.outputs["progress"]),
        27: str(plan.outputs["evaluation"]),
    }
    for index, value in expected_values.items():
        if len(command) <= index or command[index] != value:
            _fail(f"exact rollout command value drifted at argv[{index}]")
    if command[-1] != "--diagnostic" or "--diagnostic" in command[:-1]:
        _fail("exact rollout command must contain one terminal --diagnostic flag")
    if plan.env != {"CUDA_VISIBLE_DEVICES": str(GPU_INDEX), "PYTHONDONTWRITEBYTECODE": "1"}:
        _fail("exact rollout environment drifted from GPU2 diagnostic identity")


@dataclass(frozen=True)
class DiagnosticPlan:
    identity_plan: launcher.RolloutPlan
    admission: Mapping[str, Any]
    input_snapshots: Mapping[str, Mapping[str, Any]]
    reservation: NamespaceReservation
    exact_command_digest: str
    plan_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "status": "dry_run_ready",
            "seed": SEED,
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "gpu_index": GPU_INDEX,
            "run_id": self.identity_plan.run_id,
            "manifest": str(self.identity_plan.manifest),
            "manifest_sha256": self.identity_plan.manifest_sha256,
            "manifest_file_sha256": self.identity_plan.manifest_file_sha256,
            "training_receipt": str(self.identity_plan.training_receipt),
            "training_receipt_sha256": self.identity_plan.training_receipt_sha256,
            "checkpoint": dict(self.identity_plan.checkpoint),
            "checkpoint_metadata": dict(self.identity_plan.checkpoint_metadata),
            "namespace": str(self.identity_plan.namespace),
            "namespace_nonce": self.identity_plan.nonce,
            "namespace_reservation": self.reservation.as_dict(),
            "command": list(self.identity_plan.command),
            "env_overrides": dict(self.identity_plan.env),
            "command_sha256": self.identity_plan.command_sha256,
            "exact_command_digest": self.exact_command_digest,
            "admission": dict(self.admission),
            "input_snapshots": {key: dict(value) for key, value in self.input_snapshots.items()},
            "plan_digest": self.plan_digest,
            "launch_allowed": False,
            **launcher.ZERO_CREDIT,
        }


def build_plan(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipt: Path | str = DEFAULT_TRAINING_RECEIPT,
    checkpoint: Path | str | None = None,
    nonce: str | None = None,
    output_root: Path | str = "/tmp",
    resource_admission: Mapping[str, Any] | None = None,
) -> DiagnosticPlan:
    """Build and atomically reserve one seed17 dry-run namespace."""

    root_path = _absolute_path(root, "root")
    selected_nonce = _validate_nonce(nonce if nonce is not None else secrets.token_hex(16))
    namespace = _namespace(_absolute_path(output_root, "output_root"), selected_nonce)
    plan = launcher.build_plan(
        root_path,
        seed=SEED,
        manifest=manifest,
        training_receipt=training_receipt,
        checkpoint=checkpoint,
        nonce=selected_nonce,
        output_namespace=namespace,
        gpu_index=GPU_INDEX,
    )
    _assert_exact_command(plan)
    _under(plan.manifest, root_path) or _fail("current manifest escapes the lab root")
    if not _under(plan.training_receipt, root_path) and not _under(plan.training_receipt, Path("/tmp")):
        _fail("training receipt escapes the bounded lab/tmp roots")
    checkpoint_path = Path(str(plan.checkpoint["path"]))
    if not _under(checkpoint_path, root_path) and not _under(checkpoint_path, Path("/tmp")):
        _fail("checkpoint metadata escapes the bounded lab/tmp roots")
    snapshots = _snapshot_inputs(plan)
    if resource_admission is None:
        resource_admission = admission.probe_resource_admission(GPU_INDEX, root=root_path)
    resource_admission = dict(resource_admission)
    _exact(resource_admission, "schema", admission.ADMISSION_SCHEMA, "resource_admission")
    _exact(resource_admission, "gpu_index", GPU_INDEX, "resource_admission")
    _bool(resource_admission.get("admitted"), "resource_admission.admitted")
    exact_digest = _exact_command_digest(plan)
    plan_digest = canonical_digest(
        {
            "schema": PLAN_SCHEMA,
            "identity_plan": plan.as_dict(),
            "admission": resource_admission,
            "input_snapshots": snapshots,
            "exact_command_digest": exact_digest,
        }
    )
    reservation = _reserve_namespace(namespace, selected_nonce, plan_digest)
    return DiagnosticPlan(
        identity_plan=plan,
        admission=resource_admission,
        input_snapshots=snapshots,
        reservation=reservation,
        exact_command_digest=exact_digest,
        plan_digest=plan_digest,
    )


def _validate_current_admission(plan: DiagnosticPlan) -> Mapping[str, Any]:
    current = admission.probe_resource_admission(GPU_INDEX, root=plan.identity_plan.root)
    _exact(current, "schema", admission.ADMISSION_SCHEMA, "current_resource_admission")
    _exact(current, "gpu_index", GPU_INDEX, "current_resource_admission")
    if not current.get("admitted"):
        _fail("GPU2 resource admission is not currently safe for execution")
    return current


def _validate_outputs_fresh(plan: DiagnosticPlan) -> None:
    _verify_reservation(plan.reservation, plan.plan_digest)
    if not plan.identity_plan.namespace.is_dir():
        _fail("exclusive namespace reservation is not a directory")
    for name, path in plan.identity_plan.outputs.items():
        if name == "namespace":
            continue
        if os.path.lexists(path):
            _fail(f"output.{name} already exists; refusing output reuse")
        _reject_symlink_components(path.parent, f"output.{name} parent")


def _revalidate_before_popen(plan: DiagnosticPlan) -> Mapping[str, Any]:
    if type(plan) is not DiagnosticPlan:
        _fail("diagnostic execution requires a DiagnosticPlan minted by build_plan")
    _assert_exact_command(plan.identity_plan)
    if _exact_command_digest(plan.identity_plan) != plan.exact_command_digest:
        _fail("exact command digest drifted from the plan")
    _revalidate_input_snapshots(plan)
    _validate_outputs_fresh(plan)
    return _validate_current_admission(plan)


@dataclass(frozen=True)
class _RealProcessWitness:
    process: subprocess.Popen[Any]
    returncode: int
    wait_returncode: int
    command: tuple[str, ...]
    command_sha256: str
    cwd: str
    env_overrides: Mapping[str, str]
    plan_digest: str
    _seal: str


def _witness_payload(witness: _RealProcessWitness) -> dict[str, Any]:
    return {
        "process_object_id": id(witness.process),
        "process_type": f"{type(witness.process).__module__}.{type(witness.process).__qualname__}",
        "returncode": witness.returncode,
        "wait_returncode": witness.wait_returncode,
        "wait_observed": True,
        "command": list(witness.command),
        "command_sha256": witness.command_sha256,
        "cwd": witness.cwd,
        "env_overrides": dict(witness.env_overrides),
        "plan_digest": witness.plan_digest,
    }


def _reject_injected_popen(popen_factory: Any) -> None:
    if popen_factory is not None and popen_factory is not _REAL_POPEN:
        _fail("caller-supplied, fake, or injected Popen is not admitted")


def _run_real_popen_wait(plan: DiagnosticPlan, current_admission: Mapping[str, Any]) -> _RealProcessWitness:
    """Future-only real lifecycle; unreachable while capability is absent."""

    _revalidate_before_popen(plan)
    log_path = plan.identity_plan.outputs["log"]
    try:
        fd = os.open(
            log_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
    except OSError as error:
        _fail(f"cannot create exclusive diagnostic log: {error}")
    environment = os.environ.copy()
    environment.update({str(key): str(value) for key, value in plan.identity_plan.env.items()})
    log_file = os.fdopen(fd, "wb", closefd=True)
    try:
        process = _REAL_POPEN(
            list(plan.identity_plan.command),
            cwd=str(plan.identity_plan.root),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        log_file.close()
    if type(process) is not _REAL_POPEN:
        _fail("real subprocess.Popen did not return the captured Popen type")
    if process.args != list(plan.identity_plan.command):
        _fail("real Popen args differ from exact command")
    if not isinstance(process.pid, int) or process.pid <= 0:
        _fail("real Popen returned an invalid evaluator process identity")
    wait_returncode = process.wait()
    if type(wait_returncode) is not int or type(process.returncode) is not int:
        _fail("real Popen/wait did not produce an integer return code")
    if wait_returncode != process.returncode:
        _fail("Popen returncode differs from wait returncode")
    if wait_returncode != 0:
        _fail(f"diagnostic evaluator did not exit naturally with returncode 0: {wait_returncode}")
    payload = {
        "process_object_id": id(process),
        "process_type": f"{type(process).__module__}.{type(process).__qualname__}",
        "returncode": int(process.returncode),
        "wait_returncode": int(wait_returncode),
        "wait_observed": True,
        "command": list(plan.identity_plan.command),
        "command_sha256": plan.exact_command_digest,
        "cwd": str(plan.identity_plan.root),
        "env_overrides": dict(plan.identity_plan.env),
        "plan_digest": plan.plan_digest,
    }
    seal = hmac.new(
        _PROCESS_RECORD_SECRET,
        canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _RealProcessWitness(
        process=process,
        returncode=int(process.returncode),
        wait_returncode=int(wait_returncode),
        command=tuple(plan.identity_plan.command),
        command_sha256=plan.exact_command_digest,
        cwd=str(plan.identity_plan.root),
        env_overrides=dict(plan.identity_plan.env),
        plan_digest=plan.plan_digest,
        _seal=seal,
    )


def _verify_witness(witness: _RealProcessWitness, plan: DiagnosticPlan) -> None:
    if type(witness) is not _RealProcessWitness:
        _fail("terminal evidence requires an internal real Popen/wait witness")
    if type(witness.process) is not _REAL_POPEN:
        _fail("terminal evidence process is not the captured real Popen type")
    payload = _witness_payload(witness)
    expected = hmac.new(
        _PROCESS_RECORD_SECRET,
        canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    # The resource-admission field is intentionally not part of the sealed
    # process payload; it is rechecked independently before Popen.
    if not hmac.compare_digest(expected, witness._seal):
        _fail("real Popen/wait witness seal mismatch")
    if witness.command != tuple(plan.identity_plan.command) or witness.command_sha256 != plan.exact_command_digest:
        _fail("real Popen/wait witness command identity drifted")
    if witness.returncode != 0 or witness.wait_returncode != 0:
        _fail("real Popen/wait witness is not a natural returncode-zero exit")


def _read_stable_bytes(path: Path, name: str, *, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    candidate = _absolute_path(path, name)
    _reject_symlink_components(candidate, name)
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
    after = os.lstat(candidate)
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity:
        _fail(f"{name} changed after bounded read")
    raw = b"".join(chunks)
    return raw, {
        "path": str(candidate),
        "dev": int(before.st_dev),
        "ino": int(before.st_ino),
        "bytes": len(raw),
        "mode": int(stat.S_IMODE(before.st_mode)),
        "nlink": int(before.st_nlink),
        "mtime_ns": int(before.st_mtime_ns),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
    }


def _json_from_bytes(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RunnerError, RecursionError) as error:
        _fail(f"invalid {name}: {error}")
    _walk_json(value, name)
    return dict(_mapping(value, name))


def _artifact_snapshot(path: Path, name: str, *, max_bytes: int) -> tuple[dict[str, Any], bytes]:
    raw, descriptor = _read_stable_bytes(path, name, max_bytes=max_bytes)
    return descriptor, raw


def _hardened_hdf5_checks(raw: bytes) -> dict[str, Any]:
    if not 1 <= len(raw) <= MAX_HDF5_BYTES:
        _fail("trajectory HDF5 snapshot is outside the bounded size")
    required = {"time", "position", "velocity", "particle_id", "particle_zone", "valid", "mass"}
    try:
        with h5py.File(io.BytesIO(raw), "r") as handle:
            visited = 0

            def inspect_group(group: h5py.Group, prefix: str = "") -> None:
                nonlocal visited
                for key in group.keys():
                    name = f"{prefix}/{key}" if prefix else str(key)
                    visited += 1
                    if visited > 4096:
                        _fail("trajectory HDF5 contains too many links")
                    link = group.get(key, getlink=True)
                    if isinstance(link, (h5py.ExternalLink, h5py.SoftLink)):
                        _fail(f"trajectory HDF5 contains an unsafe link: {name}")
                    if not isinstance(link, h5py.HardLink):
                        _fail(f"trajectory HDF5 contains an unsupported link: {name}")
                    item = group[key]
                    if isinstance(item, h5py.Dataset) and bool(getattr(item, "is_virtual", False)):
                        _fail(f"trajectory HDF5 contains a virtual dataset: {name}")
                    if isinstance(item, h5py.Group):
                        inspect_group(item, name)

            inspect_group(handle)
            missing = sorted(required - set(handle))
            if missing:
                _fail(f"trajectory HDF5 is missing required datasets: {missing}")
            for name in required:
                link = handle.get(name, getlink=True)
                if not isinstance(link, h5py.HardLink) or not isinstance(handle[name], h5py.Dataset):
                    _fail(f"trajectory HDF5 required object is not a physical dataset: {name}")
    except RunnerError:
        raise
    except (OSError, TypeError, ValueError) as error:
        _fail(f"hardened HDF5 checks failed: {error}")
    return {
        "schema": "core.f3.hardened_hdf5_checks.v1",
        "passed": True,
        "external_links_rejected": True,
        "soft_links_rejected": True,
        "virtual_datasets_rejected": True,
        "single_physical_dataset_links_required": True,
        "required_datasets": sorted(required),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _artifact_identity(path: Path, descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": int(descriptor["bytes"]),
        "sha256": str(descriptor["sha256"]),
        "dev": int(descriptor["dev"]),
        "ino": int(descriptor["ino"]),
        "nlink": int(descriptor["nlink"]),
        "content_opened": True,
    }


def _validate_progress(progress: Mapping[str, Any], plan: DiagnosticPlan) -> None:
    _exact(progress, "schema", "core.rollout.progress.v1", "progress")
    _exact(progress, "case_id", CASE_ID, "progress")
    _exact(progress, "status", "completed", "progress")
    for key in ("completed_frames", "expected_frames", "frames_expected", "frames_executed"):
        _exact(progress, key, TRANSITIONS, "progress")
    _exact(progress, "autonomous", True, "progress")
    _exact(progress, "future_state_inputs", False, "progress")
    _exact(progress, "trajectory_output", str(plan.identity_plan.outputs["trajectory"]), "progress")
    if progress.get("execution_complete") is not True:
        _fail("progress.execution_complete must be true")
    if progress.get("finite_rollout_complete") is not True:
        _fail("progress.finite_rollout_complete must be true")


def _validate_evaluation(evaluation: Mapping[str, Any], plan: DiagnosticPlan) -> None:
    _exact(evaluation, "schema", "core.evaluation.v1", "evaluation")
    _exact(evaluation, "evaluation_mode", "diagnostic", "evaluation")
    _exact(evaluation, "diagnostic", True, "evaluation")
    _exact(evaluation, "formal_eligible", False, "evaluation")
    _exact(evaluation, "model_kind", MODEL, "evaluation")
    _exact(evaluation, "checkpoint", str(plan.identity_plan.checkpoint["path"]), "evaluation")
    _exact(evaluation, "requested_split", SPLIT, "evaluation")
    _exact(evaluation, "future_state_inputs", False, "evaluation")
    _exact(evaluation, "registered_case_count", 1, "evaluation")
    _exact(evaluation, "case_count", 1, "evaluation")
    if evaluation.get("selected_case_ids") != [CASE_ID] or evaluation.get("registered_case_ids") != [CASE_ID]:
        _fail("evaluation case identity is not the single bound seed17 case")
    expected = _mapping(evaluation.get("expected_frames"), "evaluation.expected_frames")
    _exact(expected, CASE_ID, TRANSITIONS, "evaluation.expected_frames")
    cases = _mapping(evaluation.get("cases"), "evaluation.cases")
    row = _mapping(cases.get(CASE_ID), "evaluation.case")
    for key in ("frames_expected", "expected_frames", "frames_executed"):
        _exact(row, key, TRANSITIONS, "evaluation.case")
    _exact(row, "executed", True, "evaluation.case")
    _exact(row, "execution_complete", True, "evaluation.case")
    _exact(row, "finite_rollout_complete", True, "evaluation.case")
    _exact(row, "future_state_inputs", False, "evaluation.case")
    _exact(row, "trajectory_output", str(plan.identity_plan.outputs["trajectory"]), "evaluation.case")
    _exact(row, "progress_output", str(plan.identity_plan.outputs["progress"]), "evaluation.case")
    if evaluation.get("maximum_steps") != TRANSITIONS:
        _fail("evaluation.maximum_steps is not the exact diagnostic horizon")


def _validate_terminal_artifacts(plan: DiagnosticPlan, witness: _RealProcessWitness) -> dict[str, Any]:
    _verify_witness(witness, plan)
    outputs = plan.identity_plan.outputs
    evaluation_descriptor, evaluation_raw = _artifact_snapshot(
        outputs["evaluation"], "evaluation artifact", max_bytes=MAX_JSON_BYTES
    )
    trajectory_before, trajectory_raw = _artifact_snapshot(
        outputs["trajectory"], "trajectory artifact", max_bytes=MAX_HDF5_BYTES
    )
    progress_descriptor, progress_raw = _artifact_snapshot(
        outputs["progress"], "progress artifact", max_bytes=MAX_JSON_BYTES
    )
    evaluation = _json_from_bytes(evaluation_raw, "evaluation artifact")
    progress = _json_from_bytes(progress_raw, "progress artifact")
    _validate_evaluation(evaluation, plan)
    _validate_progress(progress, plan)
    hardened = _hardened_hdf5_checks(trajectory_raw)
    try:
        independent = hdf5_validator.validate_receipt(
            outputs["evaluation"],
            outputs["trajectory"],
            case_id=CASE_ID,
            expected_transitions=TRANSITIONS,
        )
    except Exception as error:
        _fail(f"independent f3_full_rollout_receipt_hdf5_validator_v1 rejected artifacts: {error}")
    trajectory_after, trajectory_after_raw = _artifact_snapshot(
        outputs["trajectory"], "trajectory artifact after validator", max_bytes=MAX_HDF5_BYTES
    )
    if trajectory_before != trajectory_after or trajectory_raw != trajectory_after_raw:
        _fail("trajectory artifact changed across independent validator inspection")
    evaluation_after, evaluation_after_raw = _artifact_snapshot(
        outputs["evaluation"], "evaluation artifact after validator", max_bytes=MAX_JSON_BYTES
    )
    progress_after, progress_after_raw = _artifact_snapshot(
        outputs["progress"], "progress artifact after validator", max_bytes=MAX_JSON_BYTES
    )
    if evaluation_descriptor != evaluation_after or evaluation_raw != evaluation_after_raw:
        _fail("evaluation artifact changed across independent validator inspection")
    if progress_descriptor != progress_after or progress_raw != progress_after_raw:
        _fail("progress artifact changed across independent validator inspection")
    if not isinstance(independent, Mapping) or independent.get("passed") is not True:
        _fail("independent HDF5 validator did not pass")
    if independent.get("synthetic_only") is not False:
        _fail("independent HDF5 validator result must not be synthetic-only")
    if independent.get("expected_transitions") != TRANSITIONS or independent.get("frames_executed") != TRANSITIONS:
        _fail("independent HDF5 validator transition identity drifted")
    checks = _mapping(independent.get("checks"), "independent_validator.checks")
    if checks.get("trajectory_frames") != FRAMES or checks.get("trajectory_transitions") != TRANSITIONS:
        _fail("independent HDF5 validator frame identity drifted")
    if checks.get("trajectory_file_sha256") != trajectory_after["sha256"] or checks.get("trajectory_file_bytes") != trajectory_after["bytes"]:
        _fail("independent HDF5 validator trajectory artifact identity drifted")
    validator_core = {
        "schema": VALIDATOR_ARTIFACT_SCHEMA,
        "status": "validated",
        "independent_validator_schema": hdf5_validator.SCHEMA,
        "independent_validator_module": str(Path(hdf5_validator.__file__).resolve()),
        "seed": SEED,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "evaluation": _artifact_identity(outputs["evaluation"], evaluation_descriptor),
        "trajectory": _artifact_identity(outputs["trajectory"], trajectory_after),
        "progress": _artifact_identity(outputs["progress"], progress_descriptor),
        "independent_validation": dict(independent),
        "hardened_hdf5_checks": hardened,
        **ZERO_CREDIT,
    }
    validator_core["artifact_binding_sha256"] = canonical_digest(
        {
            key: validator_core[key]
            for key in ("schema", "seed", "model_kind", "case_id", "transitions", "frames", "evaluation", "trajectory", "progress", "independent_validation", "hardened_hdf5_checks")
        }
    )
    validator_path = outputs["validator"]
    if os.path.lexists(validator_path):
        _fail("validator artifact already exists; refusing reuse")
    raw_validator = (canonical_json(validator_core) + "\n").encode("utf-8")
    if len(raw_validator) > MAX_JSON_BYTES:
        _fail("validator artifact exceeds bounded size")
    try:
        fd = os.open(
            validator_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw_validator)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        _fail(f"cannot write validator artifact exclusively: {error}")
    validator_descriptor, validator_raw = _artifact_snapshot(
        validator_path, "validator artifact", max_bytes=MAX_JSON_BYTES
    )
    if validator_raw != raw_validator:
        _fail("validator artifact changed immediately after exclusive write")
    artifacts = {
        "evaluation": _artifact_identity(outputs["evaluation"], evaluation_descriptor),
        "trajectory": _artifact_identity(outputs["trajectory"], trajectory_after),
        "progress": _artifact_identity(outputs["progress"], progress_descriptor),
        "validator": _artifact_identity(outputs["validator"], validator_descriptor),
    }
    return {
        "evaluation": evaluation,
        "progress": progress,
        "independent_validation": dict(independent),
        "hardened_hdf5_checks": hardened,
        "validator_payload": validator_core,
        "artifacts": artifacts,
        "artifact_identity_sha256": canonical_digest(artifacts),
    }


def _make_diagnostic_receipt(
    plan: DiagnosticPlan,
    witness: _RealProcessWitness,
    terminal: Mapping[str, Any],
    current_admission: Mapping[str, Any],
) -> dict[str, Any]:
    artifacts = dict(terminal["artifacts"])
    receipt_core: dict[str, Any] = {
        "schema": DIAGNOSTIC_RECEIPT_SCHEMA,
        "status": "diagnostic_terminal_verified",
        "report_id": REPORT_ID,
        "seed": SEED,
        "run_id": plan.identity_plan.run_id,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "namespace": str(plan.identity_plan.namespace),
        "namespace_nonce": plan.identity_plan.nonce,
        "reservation_sha256": plan.reservation.marker_sha256,
        "manifest": {
            "path": str(plan.identity_plan.manifest),
            "canonical_sha256": plan.identity_plan.manifest_sha256,
            "file_sha256": plan.identity_plan.manifest_file_sha256,
        },
        "training_receipt": {
            "path": str(plan.identity_plan.training_receipt),
            "sha256": plan.identity_plan.training_receipt_sha256,
        },
        "checkpoint": dict(plan.identity_plan.checkpoint),
        "command": list(plan.identity_plan.command),
        "command_sha256": plan.exact_command_digest,
        "cwd": str(plan.identity_plan.root),
        "env_overrides": dict(plan.identity_plan.env),
        "plan_digest": plan.plan_digest,
        "resource_admission": dict(current_admission),
        "process_exit": {
            "real_popen_wait": True,
            "process_type": f"{type(witness.process).__module__}.{type(witness.process).__qualname__}",
            "wait_observed": True,
            "returncode": witness.returncode,
            "wait_returncode": witness.wait_returncode,
            "natural_returncode_zero": True,
            "stopped_processes": 0,
            "restarted_processes": 0,
            "command_sha256": witness.command_sha256,
        },
        "artifacts": artifacts,
        "artifact_identity_sha256": terminal["artifact_identity_sha256"],
        "validator_artifact_schema": VALIDATOR_ARTIFACT_SCHEMA,
        "independent_validator_schema": hdf5_validator.SCHEMA,
        "hardened_hdf5_checks": dict(terminal["hardened_hdf5_checks"]),
        "terminal_markers": {
            "terminal": True,
            "execution_complete": True,
            "finite_rollout_complete": True,
            "progress_is_not_completion": True,
            "synthetic_only": False,
        },
        "input_boundary": {
            "manifest_content_opened": True,
            "training_receipt_content_opened": True,
            "checkpoint_content_opened_by_runner": False,
            "evaluation_content_opened": True,
            "trajectory_hdf5_content_opened": True,
            "progress_content_opened": True,
            "validator_content_opened": True,
        },
        "side_effects": {
            "evaluator_started": True,
            "processes_started": 1,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "solver_started": False,
            "worker_started": False,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        **ZERO_CREDIT,
    }
    receipt_core["receipt_identity_sha256"] = canonical_digest(receipt_core)
    return receipt_core


def execute_diagnostic(
    plan: DiagnosticPlan,
    *,
    capability: object | None = None,
    popen_factory: Any = None,
) -> dict[str, Any]:
    """Execute one diagnostic only when the private future capability exists.

    The current capability is intentionally ``None``.  The fake-Popen seam
    exists only so tests can prove rejection before any process side effect;
    it is not an execution injection point.
    """

    _reject_injected_popen(popen_factory)
    if _DIAGNOSTIC_EXECUTE_CAPABILITY is None:
        _fail("diagnostic execute capability is not admitted; Popen was not attempted")
    if capability is not _DIAGNOSTIC_EXECUTE_CAPABILITY:
        _fail("caller-supplied diagnostic capability cannot authorize Popen")
    current = _revalidate_before_popen(plan)
    witness = _run_real_popen_wait(plan, current)
    terminal = _validate_terminal_artifacts(plan, witness)
    receipt = _make_diagnostic_receipt(plan, witness, terminal, current)
    receipt_path = plan.identity_plan.outputs["terminal_receipt"]
    if os.path.lexists(receipt_path):
        _fail("diagnostic receipt already exists; refusing reuse")
    raw = (canonical_json(receipt) + "\n").encode("utf-8")
    try:
        fd = os.open(
            receipt_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        _fail(f"cannot write diagnostic receipt exclusively: {error}")
    return receipt


def _base_blockers(admission_payload: Mapping[str, Any]) -> list[str]:
    blockers = [
        "diagnostic execute capability is not admitted",
        "independent terminal HDF5/artifact execution authority is not installed",
        "zero-credit diagnostic receipts require real Popen/wait and are not self-authorized",
    ]
    blockers.extend(str(item) for item in admission_payload.get("blocked_reasons", []) if isinstance(item, str))
    return sorted(set(blockers))


def build_report(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipt: Path | str = DEFAULT_TRAINING_RECEIPT,
    checkpoint: Path | str | None = None,
    nonce: str | None = None,
    output_root: Path | str = "/tmp",
    resource_admission: Mapping[str, Any] | None = None,
    execute_requested: bool = False,
) -> dict[str, Any]:
    """Build a dry-run report; explicit execute remains pre-Popen blocked."""

    if resource_admission is None:
        root_path = _absolute_path(root, "root")
        resource_admission = admission.probe_resource_admission(GPU_INDEX, root=root_path)
    resource_admission = dict(resource_admission)
    try:
        plan = build_plan(
            root,
            manifest=manifest,
            training_receipt=training_receipt,
            checkpoint=checkpoint,
            nonce=nonce,
            output_root=output_root,
            resource_admission=resource_admission,
        )
    except (RunnerError, launcher.ContractError, OSError, ValueError) as error:
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "mode": "diagnostic_execute_blocked" if execute_requested else "dry_run_blocked",
            "execute_requested": bool(execute_requested),
            "source_bound": False,
            "plan_identity_bound": False,
            "launch_allowed": False,
            "real_workload_started": 0,
            "popen_attempted": False,
            "wait_attempted": False,
            "namespace_reserved": False,
            "gpu_index": GPU_INDEX,
            "resource_admission": resource_admission,
            "blocked_reasons": [str(error)],
            "terminal_receipt": None,
            "input_boundary": {
                "manifest_content_opened": False,
                "training_receipt_content_opened": False,
                "checkpoint_content_opened_by_runner": False,
                "evaluation_content_opened": False,
                "trajectory_hdf5_content_opened": False,
                "progress_content_opened": False,
                "validator_content_opened": False,
            },
            "side_effects": {
                "evaluator_started": False,
                "processes_started": 0,
                "processes_stopped": 0,
                "processes_restarted": 0,
                "solver_started": False,
                "worker_started": False,
                "queue_submissions": 0,
                "registry_writes": 0,
                "ledger_writes": 0,
                "denominator_writes": 0,
                "gate_writes": 0,
                "completion_writes": 0,
                "plan_writes": 0,
            },
            **ZERO_CREDIT,
        }

    terminal_receipt = None
    execute_error = None
    if execute_requested:
        try:
            terminal_receipt = execute_diagnostic(plan)
        except (RunnerError, OSError, ValueError) as error:
            execute_error = str(error)
    blockers = _base_blockers(plan.admission)
    if execute_error:
        blockers.append(execute_error)
    report = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "dry_run_ready" if not execute_requested else "blocked_fail_closed",
        "mode": "dry_run" if not execute_requested else "diagnostic_execute_blocked",
        "execute_requested": bool(execute_requested),
        "source_bound": True,
        "plan_identity_bound": True,
        "launch_allowed": False,
        "real_workload_started": 0,
        "popen_attempted": False,
        "wait_attempted": False,
        "namespace_reserved": True,
        "seed": SEED,
        "run_id": plan.identity_plan.run_id,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "gpu_index": GPU_INDEX,
        "resource_admission": dict(plan.admission),
        "manifest": {
            "path": str(plan.identity_plan.manifest),
            "canonical_sha256": plan.identity_plan.manifest_sha256,
            "file_sha256": plan.identity_plan.manifest_file_sha256,
        },
        "training_receipt": {
            "path": str(plan.identity_plan.training_receipt),
            "sha256": plan.identity_plan.training_receipt_sha256,
        },
        "checkpoint": dict(plan.identity_plan.checkpoint),
        "namespace": str(plan.identity_plan.namespace),
        "namespace_nonce": plan.identity_plan.nonce,
        "namespace_reservation": plan.reservation.as_dict(),
        "command": list(plan.identity_plan.command),
        "env_overrides": dict(plan.identity_plan.env),
        "cwd": str(plan.identity_plan.root),
        "command_sha256": plan.exact_command_digest,
        "launcher_command_sha256": plan.identity_plan.command_sha256,
        "plan_digest": plan.plan_digest,
        "input_snapshots": {key: dict(value) for key, value in plan.input_snapshots.items()},
        "artifact_paths": {key: str(value) for key, value in plan.identity_plan.outputs.items() if key != "namespace"},
        "capabilities": {
            "diagnostic_execute_capability_admitted": False,
            "production_validator_capability_admitted": False,
            "independent_hdf5_validator_schema": hdf5_validator.SCHEMA,
            "hardened_hdf5_checks_schema": "core.f3.hardened_hdf5_checks.v1",
        },
        "terminal_receipt": terminal_receipt,
        "blocked_reasons": sorted(set(blockers)),
        "input_boundary": {
            "manifest_content_opened": True,
            "training_receipt_content_opened": True,
            "checkpoint_content_opened_by_runner": False,
            "evaluation_content_opened": False,
            "trajectory_hdf5_content_opened": False,
            "progress_content_opened": False,
            "validator_content_opened": False,
        },
        "side_effects": {
            "evaluator_started": False,
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "solver_started": False,
            "worker_started": False,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        **ZERO_CREDIT,
    }
    return report


REPORT_KEYS = frozenset(
    {
        "schema", "report_id", "status", "mode", "execute_requested", "source_bound",
        "plan_identity_bound", "launch_allowed", "real_workload_started", "popen_attempted",
        "wait_attempted", "namespace_reserved", "seed", "run_id", "model_kind", "hidden",
        "updates", "case_id", "split", "transitions", "frames", "gpu_index",
        "resource_admission", "manifest", "training_receipt", "checkpoint", "namespace",
        "namespace_nonce", "namespace_reservation", "command", "env_overrides", "cwd",
        "command_sha256", "launcher_command_sha256", "plan_digest", "input_snapshots",
        "artifact_paths", "capabilities", "terminal_receipt", "blocked_reasons",
        "input_boundary", "side_effects", *ZERO_CREDIT.keys(),
    }
)


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _reject_unknown(report, REPORT_KEYS, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        status = report.get("status")
        if status not in {"dry_run_ready", "blocked_fail_closed"}:
            _fail("report.status is invalid")
        _exact(report, "launch_allowed", False, "report")
        _exact(report, "real_workload_started", 0, "report")
        _exact(report, "popen_attempted", False, "report")
        _exact(report, "wait_attempted", False, "report")
        if report.get("namespace_reserved") not in {True, False}:
            _fail("report.namespace_reserved must be boolean")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        _exact(report, "seed", SEED, "report")
        _exact(report, "model_kind", MODEL, "report")
        _exact(report, "hidden", HIDDEN, "report")
        _exact(report, "updates", UPDATES, "report")
        _exact(report, "case_id", CASE_ID, "report")
        _exact(report, "split", SPLIT, "report")
        _exact(report, "transitions", TRANSITIONS, "report")
        _exact(report, "frames", FRAMES, "report")
        _exact(report, "gpu_index", GPU_INDEX, "report")
        command = report.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
            _fail("report.command must be a non-empty string list")
        if "--diagnostic" not in command or command[-1] != "--diagnostic":
            _fail("report.command must remain diagnostic-only")
        if len(command) < 29:
            _fail("report.command is shorter than the fixed launcher command")
        expected_options = {
            "--manifest": report.get("manifest", {}).get("path"),
            "--data-root": report.get("cwd"),
            "--checkpoint": report.get("checkpoint", {}).get("path"),
            "--case-id": CASE_ID,
            "--split": SPLIT,
            "--maximum-steps": str(TRANSITIONS),
            "--chunk-size": str(CHUNK_SIZE),
            "--device": "cuda:0",
            "--progress-every": str(PROGRESS_EVERY),
            "--trajectory-output": report.get("artifact_paths", {}).get("trajectory"),
            "--progress-output": report.get("artifact_paths", {}).get("progress"),
            "--output": report.get("artifact_paths", {}).get("evaluation"),
        }
        for option, expected_value in expected_options.items():
            positions = [index for index, item in enumerate(command) if item == option]
            if len(positions) != 1 or positions[0] + 1 >= len(command):
                _fail(f"report.command must contain exactly one {option}")
            if command[positions[0] + 1] != expected_value:
                _fail(f"report.command {option} is not cross-bound to the report identity")
        env = _mapping(report.get("env_overrides"), "report.env_overrides")
        _exact(env, "CUDA_VISIBLE_DEVICES", str(GPU_INDEX), "report.env_overrides")
        _exact(env, "PYTHONDONTWRITEBYTECODE", "1", "report.env_overrides")
        if report.get("terminal_receipt") is not None:
            _fail("dry-run report cannot contain a terminal receipt")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a non-empty string list")
        capabilities = _mapping(report.get("capabilities"), "report.capabilities")
        _exact(capabilities, "diagnostic_execute_capability_admitted", False, "report.capabilities")
        _exact(capabilities, "production_validator_capability_admitted", False, "report.capabilities")
        boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
        _exact(boundary, "checkpoint_content_opened_by_runner", False, "report.input_boundary")
        _exact(boundary, "evaluation_content_opened", False, "report.input_boundary")
        _exact(boundary, "trajectory_hdf5_content_opened", False, "report.input_boundary")
        _exact(boundary, "progress_content_opened", False, "report.input_boundary")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in (
            "evaluator_started", "solver_started", "worker_started", "processes_started",
            "processes_stopped", "processes_restarted", "queue_submissions", "registry_writes",
            "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes",
        ):
            value = side_effects.get(key)
            if value not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
    except (RunnerError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# F3 graph_raw seed17 diagnostic runner",
            "",
            f"- status: `{report.get('status')}`",
            f"- mode: `{report.get('mode')}`",
            f"- source bound: `{report.get('source_bound')}`",
            f"- GPU admission: `{report.get('resource_admission', {}).get('status')}`",
            f"- namespace reserved: `{report.get('namespace')}`",
            "- exact contract: graph_raw / hidden16 / seed17 / test / 835 transitions / 836 frames",
            "- command: `core_learning.py evaluate ... --diagnostic`, env `CUDA_VISIBLE_DEVICES=2`",
            "- real workload started: `0`; Popen/wait attempted: `0/0`; credit: `0`",
            "- independent HDF5 validator and hardened artifact capability: not admitted",
            "",
            "## Blockers",
            "",
            *[f"- {item}" for item in report.get("blocked_reasons", []) if isinstance(item, str)],
            "",
        ]
    )


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o640)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _fail(f"refusing to overwrite existing report: {path}")
    except OSError as error:
        _fail(f"cannot write report: {error}")


def _write_text_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = text.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o640)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _fail(f"refusing to overwrite existing markdown report: {path}")
    except OSError as error:
        _fail(f"cannot write markdown report: {error}")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--training-receipt", type=Path, default=DEFAULT_TRAINING_RECEIPT)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--nonce", default=None, metavar="32-HEX")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    parser.add_argument(
        "--diagnostic-execute", "--execute", dest="execute_requested", action="store_true",
        help="request the guarded diagnostic path; current capability rejects before Popen",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            report_path = args.verify_report
            if not report_path.is_absolute():
                cwd_candidate = Path.cwd() / report_path
                report_path = cwd_candidate if cwd_candidate.exists() else LAB_ROOT / report_path
            report_path = _absolute_path(report_path, "verify_report")
            raw, _ = _read_stable_bytes(report_path, "report", max_bytes=MAX_REPORT_BYTES)
            report = _json_from_bytes(raw, "report")
            errors = validate_report(report)
            if errors:
                print(canonical_json({"valid": False, "errors": errors}))
                return 1
            print(canonical_json({"valid": True, "schema": REPORT_SCHEMA}))
            return 0
        report = build_report(
            args.root,
            manifest=args.manifest,
            training_receipt=args.training_receipt,
            checkpoint=args.checkpoint,
            nonce=args.nonce,
            output_root=args.output_root,
            execute_requested=args.execute_requested,
        )
        _write_json_exclusive(args.report_output, report)
        _write_text_exclusive(args.markdown_output, render_markdown(report))
        print(canonical_json(report))
        return 0
    except (RunnerError, launcher.ContractError, OSError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
