#!/usr/bin/env python3
"""Receipt-bound, zero-credit admission for residual/hidden16 seed43.

This is a diagnostic boundary, not a scheduler.  It accepts only an
externally signed reservation for a scheduler-owned namespace and resource
snapshot.  The local receipt binds the current-manifest v3 training receipt,
checkpoint bytes, source descriptors, exact evaluator command/environment,
GPU identity, and namespace inode.  Consumption is one-shot and creates an
independent claim, but the returned capability never authorizes Popen or
formal/Core state changes.

No implicit GPU probe, local authority promotion, process declaration, or
terminal receipt is accepted.  Missing or drifting evidence fails closed.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import sys
import tempfile
import time
from typing import Any

try:  # The production trust boundary is unavailable unless this is present.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - exercised only by a missing dependency.
    Ed25519PublicKey = None  # type: ignore[assignment,misc]

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher
from scripts import f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1 as identity


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 43
GPU_INDEX = 6
MODEL = launcher.MODEL
HIDDEN = launcher.HIDDEN
UPDATES = launcher.UPDATES
CASE_ID = launcher.CASE_ID
SPLIT = launcher.SPLIT
TRANSITIONS = launcher.TRANSITIONS
FRAMES = launcher.FRAMES
RUN_ID = f"f3-graph_residual500-hidden16-currentmanifest-seed{SEED}-20260929-v3"
MANIFEST_SCHEMA = launcher.MANIFEST_SCHEMA
TRAINING_SCHEMA = launcher.TRAINING_SCHEMA
CHECKPOINT_SCHEMA = launcher.CHECKPOINT_SCHEMA

SCHEMA = "core.f3.graph_residual.hidden16.seed43.diagnostic_admission.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
CONSUMED_SCHEMA = f"{SCHEMA}.consumed"
REPORT_ID = "f3-graph-residual-hidden16-seed43-diagnostic-admission-v1"
DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_TRAINING = Path(
    f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{SEED}-20260929-v3-training.json"
)
DEFAULT_CHECKPOINT = Path(
    f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{SEED}-20260929-v3-checkpoint.pt"
)
DEFAULT_REPORT = LAB_ROOT / "reports" / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED43-DIAGNOSTIC-ADMISSION-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
MIN_GPU_FREE_MIB = 8 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
GPU_UUID_RE = re.compile(r"^GPU-[0-9A-Fa-f-]{8,}$")
PCI_BUS_RE = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]$")

NAMESPACE_MARKER_NAME = ".diagnostic-admission-marker.json"
RECEIPT_NAME = ".diagnostic-admission-receipt.json"
STATE_NAME = ".diagnostic-admission-state.json"
CONSUMPTION_LOCK_NAME = ".diagnostic-admission-consumption.lock"
CONSUMED_NAME = ".diagnostic-admission-consumed"
LOGICAL_GPU_INDEX = 0
CUDA_DEVICE_ORDER = "PCI_BUS_ID"

AUTHORITY_SCHEMA = f"{SCHEMA}.non_authorizing_boundary"
EXTERNAL_AUTHORITY_SCHEMA = f"{SCHEMA}.external_scheduler_authority.v1"
EXTERNAL_CLAIM_SCHEMA = f"{SCHEMA}.external_scheduler_claim.v1"
EXTERNAL_AUTHORITY_DOMAIN = b"CORE-F3-GRAPH-RESIDUAL-SEED43-EXTERNAL-AUTHORITY-V1\0"
TRUSTED_SCHEDULER_PUBLIC_KEY_PATH = Path("/etc/dual-sph/scheduler-ed25519-public.key")
EXTERNAL_SCHEDULER_ROOT = Path("/var/lib/dual-sph/f3-residual-seed43-scheduler")
CURRENT_HOST = socket.gethostname()

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

# These are shared residual contracts read by this seed-specific boundary;
# none of them is modified by this module.
SOURCE_RELATIVE_PATHS = {
    "core_learning": Path("scripts/core_learning.py"),
    "rollout_launcher": Path("scripts/f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1.py"),
    "terminal_identity": Path("scripts/f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1.py"),
    "terminal_bridge": Path("scripts/f3_graph_residual_hidden16_current_manifest_terminal_execution_bridge_v1.py"),
    "terminal_runtime": Path("scripts/f3_graph_residual_hidden16_terminal_runtime_verifier_v1.py"),
    "hdf5_validator": Path("scripts/f3_full_rollout_receipt_hdf5_validator_v1.py"),
}


class AdmissionError(ValueError):
    """Malformed, drifting, replayed, or non-authorizing admission input."""


def _fail(message: str) -> None:
    raise AdmissionError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


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


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be boolean")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    result = _string(value, name)
    if SHA_RE.fullmatch(result) is None or len(set(result)) == 1:
        _fail(f"{name} must be a non-placeholder lowercase SHA-256")
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


def _unknown(value: Mapping[str, Any], allowed: set[str] | frozenset[str], name: str) -> None:
    extra = sorted(set(value) - set(allowed))
    if extra:
        _fail(f"{name} contains unknown fields: {extra}")


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
        _fail(f"{name} exceeds maximum depth")
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


def _absolute(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    path = Path(raw)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} must be absolute and lexical-alias free")
    if Path(os.path.normpath(raw)) != path:
        _fail(f"{name} uses a lexical path alias")
    return path


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlinks(path: Path, name: str, *, allow_missing_leaf: bool = False) -> None:
    current = Path(path.anchor or os.sep)
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for index, part in enumerate(parts):
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return
            _fail(f"{name} has a missing component: {current}")
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")


def _signature(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (int(info.st_dev), int(info.st_ino), int(info.st_mode), int(info.st_nlink), int(info.st_size), int(info.st_mtime_ns), int(info.st_ctime_ns))


def _open_parent(path: Path, name: str) -> tuple[int, tuple[int, int]]:
    _reject_symlinks(path, f"{name} parent")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        fd = os.open("/", flags)
        for part in path.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            _fail(f"{name} parent is not a directory")
        return fd, (int(info.st_dev), int(info.st_ino))
    except AdmissionError:
        if fd is not None:
            os.close(fd)
        raise
    except OSError as error:
        if fd is not None:
            os.close(fd)
        _fail(f"cannot open {name} parent without following links: {error}")


def _read_file(path: Path | str, name: str, *, max_bytes: int, parse_json: bool = False) -> tuple[bytes, dict[str, Any], dict[str, Any] | None]:
    candidate = _absolute(path, f"{name}.path")
    parent_fd, parent_id = _open_parent(candidate.parent, name)
    leaf_fd: int | None = None
    try:
        before = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{name} must be a regular single-link file")
        if before.st_size < 1 or before.st_size > max_bytes:
            _fail(f"{name} is outside the bounded size")
        leaf_fd = os.open(candidate.name, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        opened = os.fstat(leaf_fd)
        expected = _signature(before)
        if _signature(opened) != expected:
            _fail(f"{name} changed before read")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            block = os.read(leaf_fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after_fd = os.fstat(leaf_fd)
        after_path = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        parent_after = os.fstat(parent_fd)
        if total != before.st_size or _signature(after_fd) != expected or _signature(after_path) != expected:
            _fail(f"{name} changed during stable descriptor read")
        if (int(parent_after.st_dev), int(parent_after.st_ino)) != parent_id:
            _fail(f"{name} parent changed during stable descriptor read")
        raw = b"".join(chunks)
        descriptor = {
            "path": str(candidate), "dev": int(before.st_dev), "ino": int(before.st_ino),
            "bytes": int(before.st_size), "mode": int(stat.S_IMODE(before.st_mode)),
            "uid": int(before.st_uid), "gid": int(before.st_gid), "nlink": int(before.st_nlink),
            "mtime_ns": int(before.st_mtime_ns), "ctime_ns": int(before.st_ctime_ns),
            "parent_dev": parent_id[0], "parent_ino": parent_id[1],
            "sha256": hashlib.sha256(raw).hexdigest(), "stable_fd": True,
            "fd_identity_stable": True, "path_reopened": False, "content_opened": True,
        }
    except OSError as error:
        _fail(f"cannot read {name} safely: {error}")
    finally:
        if leaf_fd is not None:
            os.close(leaf_fd)
        os.close(parent_fd)
    payload: dict[str, Any] | None = None
    if parse_json:
        try:
            loaded = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
        except (UnicodeError, json.JSONDecodeError, AdmissionError, RecursionError) as error:
            _fail(f"invalid {name}: {error}")
        _walk_json(loaded, name)
        payload = dict(_mapping(loaded, name))
    return raw, descriptor, payload


def _file_descriptor(path: Path, name: str, *, max_bytes: int) -> dict[str, Any]:
    return _read_file(path, name, max_bytes=max_bytes)[1]


def _write_exclusive(path: Path, raw: bytes, *, mode: int = 0o600) -> dict[str, Any]:
    candidate = _absolute(path, "exclusive output")
    parent_fd, parent_id = _open_parent(candidate.parent, "exclusive output")
    fd: int | None = None
    try:
        fd = os.open(candidate.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0), mode, dir_fd=parent_fd)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        info = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        parent_after = os.fstat(parent_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != mode or info.st_uid != os.getuid() or info.st_gid != os.getgid() or info.st_size != len(raw):
            _fail(f"exclusive output {candidate} identity drifted")
        if (int(parent_after.st_dev), int(parent_after.st_ino)) != parent_id:
            _fail("exclusive output parent changed")
        os.fsync(parent_fd)
        return {
            "path": str(candidate), "dev": int(info.st_dev), "ino": int(info.st_ino),
            "bytes": int(info.st_size), "mode": int(stat.S_IMODE(info.st_mode)),
            "uid": int(info.st_uid), "gid": int(info.st_gid), "nlink": int(info.st_nlink),
            "mtime_ns": int(info.st_mtime_ns), "ctime_ns": int(info.st_ctime_ns),
            "parent_dev": parent_id[0], "parent_ino": parent_id[1],
            "sha256": hashlib.sha256(raw).hexdigest(), "stable_fd": True,
            "fd_identity_stable": True, "path_reopened": False, "content_opened": True,
        }
    except FileExistsError:
        _fail(f"refusing to overwrite existing file: {candidate}")
    except OSError as error:
        _fail(f"cannot write exclusive output: {error}")
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)


def _validate_nonce(value: Any, name: str = "nonce") -> str:
    nonce = _string(value, name)
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail(f"{name} must be a non-zero lowercase 32-hex value")
    return nonce


def _namespace(output_root: Path | str, nonce: str) -> Path:
    root = _absolute(output_root, "output_root")
    _reject_symlinks(root, "output_root")
    if not root.is_dir() or not _under(root, Path("/tmp")):
        _fail("output_root must be an existing directory under /tmp")
    return root / f"f3-graph-residual500-hidden16-currentmanifest-seed{SEED}-full835-nonce{nonce}"


def _existing_namespace_descriptor(path: Path | str) -> dict[str, Any]:
    candidate = _absolute(path, "scheduler-reserved namespace")
    _reject_symlinks(candidate, "scheduler-reserved namespace")
    info = os.lstat(candidate)
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        _fail("scheduler-reserved namespace must be a mode-0700 directory")
    if info.st_uid != os.getuid() or info.st_gid != os.getgid() or info.st_nlink < 2:
        _fail("scheduler-reserved namespace owner/link identity drifted")
    parent_fd, parent_id = _open_parent(candidate.parent, "scheduler-reserved namespace")
    try:
        current = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        if current.st_dev != info.st_dev or current.st_ino != info.st_ino:
            _fail("scheduler-reserved namespace changed during inspection")
    finally:
        os.close(parent_fd)
    return {"path": str(candidate), "dev": int(info.st_dev), "ino": int(info.st_ino), "mode": int(stat.S_IMODE(info.st_mode)), "uid": int(info.st_uid), "gid": int(info.st_gid), "nlink": int(info.st_nlink), "parent_dev": parent_id[0], "parent_ino": parent_id[1]}


def _source_descriptor(root: Path, relative: Path, name: str) -> dict[str, Any]:
    path = root / relative
    if not _under(path, root) or not _under(path.parent, root):
        _fail(f"{name} escapes the lab root")
    return _file_descriptor(path, name, max_bytes=MAX_SOURCE_BYTES)


def _validate_owner(value: Any, name: str) -> dict[str, Any]:
    owner = dict(_mapping(value, name))
    _unknown(owner, {"uid", "gid", "host", "scope", "snapshot_nonce"}, name)
    _exact(owner, "uid", os.getuid(), name)
    _exact(owner, "gid", os.getgid(), name)
    _exact(owner, "host", CURRENT_HOST, name)
    _exact(owner, "scope", "scheduler_owned_diagnostic_snapshot", name)
    _validate_nonce(owner.get("snapshot_nonce"), f"{name}.snapshot_nonce")
    return owner


def _gpu_identity(gpu: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: gpu.get(key) for key in ("physical_index", "uuid", "pci_bus_id", "logical_index", "cuda_visible_devices", "cuda_device", "cuda_device_order")}
    _exact(result, "physical_index", GPU_INDEX, "resource_admission.gpu")
    uuid = _string(result.get("uuid"), "resource_admission.gpu.uuid")
    if GPU_UUID_RE.fullmatch(uuid) is None or len(set(uuid.upper())) <= 2:
        _fail("resource_admission.gpu.uuid is not a stable GPU UUID")
    pci = _string(result.get("pci_bus_id"), "resource_admission.gpu.pci_bus_id")
    if PCI_BUS_RE.fullmatch(pci) is None:
        _fail("resource_admission.gpu.pci_bus_id is not canonical")
    _exact(result, "logical_index", LOGICAL_GPU_INDEX, "resource_admission.gpu")
    _exact(result, "cuda_visible_devices", str(GPU_INDEX), "resource_admission.gpu")
    _exact(result, "cuda_device", "cuda:0", "resource_admission.gpu")
    _exact(result, "cuda_device_order", CUDA_DEVICE_ORDER, "resource_admission.gpu")
    return result


def _validate_resource(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    _unknown(payload, {"schema", "gpu_index", "gpu", "cpu", "io", "thresholds", "status", "admitted", "blocked_reasons", "content_opened", "owner"}, "resource_admission")
    _exact(payload, "schema", "core.f3.graph_residual.hidden16.current_manifest.resource_admission.v1", "resource_admission")
    _exact(payload, "gpu_index", GPU_INDEX, "resource_admission")
    _exact(payload, "status", "admitted", "resource_admission")
    _exact(payload, "admitted", True, "resource_admission")
    _exact(payload, "content_opened", False, "resource_admission")
    if not isinstance(payload.get("blocked_reasons"), list) or payload["blocked_reasons"]:
        _fail("resource_admission.blocked_reasons must be empty")
    gpu = dict(_mapping(payload.get("gpu"), "resource_admission.gpu"))
    _unknown(gpu, {"total_mib", "used_mib", "free_mib", "physical_index", "uuid", "pci_bus_id", "logical_index", "cuda_visible_devices", "cuda_device", "cuda_device_order", "identity_source", "identity_attested", "identity_sha256"}, "resource_admission.gpu")
    for key in ("total_mib", "used_mib", "free_mib"):
        _int(gpu.get(key), f"resource_admission.gpu.{key}")
    if gpu["used_mib"] + gpu["free_mib"] > gpu["total_mib"] or gpu["free_mib"] < MIN_GPU_FREE_MIB:
        _fail("resource_admission GPU VRAM is not safely admitted")
    gpu_identity = _gpu_identity(gpu)
    _exact(gpu, "identity_source", "scheduler_owned_snapshot", "resource_admission.gpu")
    _exact(gpu, "identity_attested", True, "resource_admission.gpu")
    _exact(gpu, "identity_sha256", canonical_digest(gpu_identity), "resource_admission.gpu")
    _validate_owner(payload.get("owner"), "resource_admission.owner")
    return payload


def _environment(env: Mapping[str, str]) -> dict[str, Any]:
    expected = {"CUDA_VISIBLE_DEVICES": str(GPU_INDEX), "CUDA_DEVICE_ORDER": CUDA_DEVICE_ORDER, "PYTHONDONTWRITEBYTECODE": "1"}
    if dict(env) != expected:
        _fail("environment is not the fixed allowlist")
    core = {"policy": "allowlist_only_no_ambient_inheritance", "inherit": False, "variables": expected}
    return {**core, "sha256": canonical_digest(core)}


def _command_digest(argv: Sequence[str], cwd: str, env: Mapping[str, str]) -> str:
    return canonical_digest({"argv": list(argv), "cwd": cwd, "env_overrides": dict(env), "seed": SEED, "gpu_index": GPU_INDEX, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES})


def _plan_binding(plan: Any) -> dict[str, Any]:
    env = dict(plan.env)
    return {
        "schema": f"{EXTERNAL_AUTHORITY_SCHEMA}.plan",
        "root": str(plan.root), "seed": int(plan.seed), "run_id": str(plan.run_id), "nonce": str(plan.nonce),
        "manifest": {"path": str(plan.manifest), "canonical_sha256": str(plan.manifest_binding["canonical_sha256"]), "file_sha256": str(plan.manifest_binding["raw_sha256"])},
        "training_receipt": {"path": str(plan.training_receipt), "file_sha256": str(plan.training_binding["sha256"])},
        "checkpoint": dict(plan.checkpoint), "namespace": str(plan.output_namespace),
        "outputs": {key: str(value) for key, value in plan.outputs.items()}, "command": list(plan.command),
        "env_overrides": env, "command_sha256": _command_digest(plan.command, str(plan.root), env),
        "launcher_command_sha256": str(plan.command_sha256),
    }


def _plan_binding_digest(plan: Any) -> str:
    return canonical_digest(_plan_binding(plan))


def _build_reserved_plan(root: Path, *, manifest: Path | str, training_receipt: Path | str, checkpoint: Path | str | None, nonce: str, namespace: Path, gpu_index: int, python_executable: Path | str | None = None) -> Any:
    """Build the current-manifest identity against a shadow namespace.

    The scheduler has already created ``namespace``.  The shadow plan lets
    the shared launcher validate the training/checkpoint contract without
    asking this admission module to create or replace the reserved directory.
    """
    if gpu_index != GPU_INDEX:
        _fail("reserved plan GPU index is not seed43 GPU6")
    executable = Path(python_executable) if python_executable is not None else root / ".venv" / "bin" / "python"
    with tempfile.TemporaryDirectory(prefix="f3-residual-seed43-plan-", dir="/tmp") as shadow:
        shadow_namespace = Path(shadow) / namespace.name
        base = identity._build_current_manifest_plan(
            root,
            seed=SEED,
            manifest=manifest,
            checkpoint=checkpoint if checkpoint is not None else DEFAULT_CHECKPOINT,
            training_receipt=training_receipt,
            run_id=RUN_ID,
            nonce=nonce,
            output_namespace=shadow_namespace,
            gpu_index=GPU_INDEX,
            python_executable=executable,
        )
    outputs = launcher._output_paths(namespace, root, SEED, nonce)
    for name, output in outputs.items():
        if name != "namespace" and os.path.lexists(output):
            _fail(f"refusing to reuse reserved output.{name}: {output}")
    command = launcher._build_command(root=root, python=Path(base.command[0]), manifest=base.manifest, checkpoint=Path(base.checkpoint["path"]), outputs=outputs)
    env = {"CUDA_VISIBLE_DEVICES": str(GPU_INDEX), "CUDA_DEVICE_ORDER": CUDA_DEVICE_ORDER, "PYTHONDONTWRITEBYTECODE": "1"}
    command_sha256 = launcher._command_digest(command, cwd=root, env=env)
    return replace(base, output_namespace=namespace, outputs=outputs, command=command, env=env, command_sha256=command_sha256)


def _external_scheduler_root() -> Path:
    root = _absolute(EXTERNAL_SCHEDULER_ROOT, "external scheduler root")
    _reject_symlinks(root, "external scheduler root")
    if not root.is_dir():
        _fail("external scheduler root is not an existing directory")
    return root


def _external_scheduler_path(value: Path | str, name: str) -> Path:
    root = _external_scheduler_root()
    candidate = _absolute(value, name)
    if candidate == root or not _under(candidate, root):
        _fail(f"{name} must remain under the external scheduler root")
    _reject_symlinks(candidate.parent, f"{name} parent")
    return candidate


def _authority_signing_message(unsigned: Mapping[str, Any]) -> bytes:
    return EXTERNAL_AUTHORITY_DOMAIN + canonical_json(dict(unsigned)).encode("utf-8")


def _authority_unsigned(document: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "signature_base64"}


def _authority_namespace_claim(value: Any) -> dict[str, Any]:
    claim = dict(_mapping(value, "external_authority.namespace"))
    _unknown(claim, {"path", "dev", "ino", "mode", "uid", "gid", "nlink", "parent_dev", "parent_ino"}, "external_authority.namespace")
    _absolute(claim.get("path"), "external_authority.namespace.path")
    for key in ("dev", "ino", "mode", "uid", "gid", "nlink", "parent_dev", "parent_ino"):
        _int(claim.get(key), f"external_authority.namespace.{key}")
    _exact(claim, "mode", 0o700, "external_authority.namespace")
    _exact(claim, "uid", os.getuid(), "external_authority.namespace")
    _exact(claim, "gid", os.getgid(), "external_authority.namespace")
    if claim["nlink"] < 2:
        _fail("external_authority.namespace.nlink must be >= 2")
    return claim


def _authority_owner(value: Any, name: str) -> dict[str, Any]:
    owner = dict(_mapping(value, name))
    _unknown(owner, {"uid", "gid", "host"}, name)
    _int(owner.get("uid"), f"{name}.uid")
    _int(owner.get("gid"), f"{name}.gid")
    _string(owner.get("host"), f"{name}.host")
    return owner


def _authority_gpu(value: Any) -> dict[str, Any]:
    return _gpu_identity(_mapping(value, "external_authority.gpu"))


def _read_trusted_scheduler_key() -> tuple[bytes, dict[str, Any]]:
    path = _absolute(TRUSTED_SCHEDULER_PUBLIC_KEY_PATH, "trusted scheduler public key")
    _reject_symlinks(path, "trusted scheduler public key")
    raw, descriptor, _ = _read_file(path, "trusted scheduler public key", max_bytes=64)
    if len(raw) != 32 or descriptor["mode"] & 0o022:
        _fail("trusted scheduler public key must be 32 owner-only bytes")
    return raw, descriptor


def _validate_external_authority(path: Path | str, *, nonce: str, namespace_descriptor: Mapping[str, Any], plan_sha256: str, resource_snapshot: Mapping[str, Any], expected_meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    authority_path = _external_scheduler_path(path, "external scheduler authority")
    raw, descriptor, payload = _read_file(authority_path, "external scheduler authority", max_bytes=256 * 1024, parse_json=True)
    if payload is None:
        _fail("external scheduler authority payload is absent")
    _unknown(payload, {"schema", "authority_id", "state", "one_shot", "owner", "scheduler", "namespace", "nonce", "plan_sha256", "resource_snapshot_sha256", "gpu", "gpu_identity_sha256", "consume_path", "key_id", "signature_algorithm", "signature_base64"}, "external scheduler authority")
    _exact(payload, "schema", EXTERNAL_AUTHORITY_SCHEMA, "external scheduler authority")
    authority_id = _sha(payload.get("authority_id"), "external_authority.authority_id")
    _exact(payload, "state", "issued", "external scheduler authority")
    _exact(payload, "one_shot", True, "external scheduler authority")
    owner = _authority_owner(payload.get("owner"), "external_authority.owner")
    _exact(owner, "uid", os.getuid(), "external_authority.owner")
    _exact(owner, "gid", os.getgid(), "external_authority.owner")
    _exact(owner, "host", CURRENT_HOST, "external_authority.owner")
    scheduler = dict(_mapping(payload.get("scheduler"), "external_authority.scheduler"))
    _unknown(scheduler, {"uid", "gid", "host", "role"}, "external_authority.scheduler")
    _int(scheduler.get("uid"), "external_authority.scheduler.uid")
    _int(scheduler.get("gid"), "external_authority.scheduler.gid")
    _string(scheduler.get("host"), "external_authority.scheduler.host")
    _exact(scheduler, "role", "external_scheduler", "external_authority.scheduler")
    if canonical_json(_authority_namespace_claim(payload.get("namespace"))) != canonical_json(dict(namespace_descriptor)):
        _fail("external scheduler authority namespace inode binding drifted")
    _exact(payload, "nonce", _validate_nonce(nonce), "external scheduler authority")
    _exact(payload, "plan_sha256", _sha(plan_sha256, "plan_sha256"), "external scheduler authority")
    _exact(payload, "resource_snapshot_sha256", canonical_digest(resource_snapshot), "external scheduler authority")
    gpu = _authority_gpu(payload.get("gpu"))
    resource_gpu = _gpu_identity(_mapping(resource_snapshot.get("gpu"), "resource_admission.gpu"))
    if canonical_json(gpu) != canonical_json(resource_gpu):
        _fail("external scheduler authority GPU identity binding drifted")
    _exact(payload, "gpu_identity_sha256", canonical_digest(gpu), "external scheduler authority")
    claim = _external_scheduler_path(payload.get("consume_path"), "external scheduler consume path")
    if claim == authority_path or _under(claim, Path(namespace_descriptor["path"])):
        _fail("external scheduler consume path is not independent")
    key_id = _string(payload.get("key_id"), "external_authority.key_id")
    _exact(payload, "signature_algorithm", "ed25519", "external_authority")
    signature_text = _string(payload.get("signature_base64"), "external_authority.signature_base64")
    try:
        signature = base64.b64decode(signature_text.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        _fail(f"external scheduler authority signature is not strict base64: {error}")
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != signature_text:
        _fail("external scheduler authority signature is not canonical Ed25519")
    public_key, key_descriptor = _read_trusted_scheduler_key()
    _exact(payload, "key_id", hashlib.sha256(public_key).hexdigest(), "external_authority")
    if Ed25519PublicKey is None:
        _fail("cryptography Ed25519 verifier is unavailable")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, _authority_signing_message(_authority_unsigned(payload)))
    except Exception as error:
        _fail(f"external scheduler authority signature verification failed: {error}")
    metadata = {
        "schema": EXTERNAL_AUTHORITY_SCHEMA, "path": str(authority_path), "file": dict(descriptor),
        "payload_sha256": hashlib.sha256(raw).hexdigest(), "document_sha256": canonical_digest(_authority_unsigned(payload)),
        "authority_id": authority_id, "key_id": key_id, "consume_path": str(claim),
        "key_file": {"path": str(TRUSTED_SCHEDULER_PUBLIC_KEY_PATH), "file": dict(key_descriptor), "sha256": hashlib.sha256(public_key).hexdigest()},
    }
    if expected_meta is not None and canonical_json(dict(expected_meta)) != canonical_json(metadata):
        _fail("external scheduler authority descriptor drifted from the receipt")
    return metadata


def _identity_core(*, root: Path, plan: Any, manifest_descriptor: Mapping[str, Any], training_descriptor: Mapping[str, Any], checkpoint_descriptor: Mapping[str, Any], executable_descriptor: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]], resource_snapshot: Mapping[str, Any], namespace_descriptor: Mapping[str, Any], external_authority: Mapping[str, Any]) -> dict[str, Any]:
    gpu = dict(_mapping(resource_snapshot["gpu"], "resource_admission.gpu"))
    return {
        "model_kind": MODEL, "hidden": HIDDEN, "updates": UPDATES, "seed": SEED, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES,
        "run_id": plan.run_id, "plan_sha256": _plan_binding_digest(plan), "root": str(root),
        "manifest": {"path": str(plan.manifest), "canonical_sha256": plan.manifest_binding["canonical_sha256"], "file": dict(manifest_descriptor)},
        "training_receipt": {"path": str(plan.training_receipt), "binding": dict(plan.training_binding), "file": dict(training_descriptor)},
        "checkpoint": {"path": str(plan.checkpoint["path"]), "declared_sha256": str(plan.checkpoint["sha256"]), "sha256": str(checkpoint_descriptor["sha256"]), "bytes": int(checkpoint_descriptor["bytes"]), "file": dict(checkpoint_descriptor)},
        "source_sha256": {key: dict(value) for key, value in sources.items()}, "resource_snapshot": dict(resource_snapshot), "gpu": gpu, "gpu_identity_sha256": canonical_digest(_gpu_identity(gpu)),
        "command": {"argv": list(plan.command), "cwd": str(root), "env_overrides": dict(plan.env), "sha256": _command_digest(plan.command, str(root), plan.env)},
        "environment": _environment(plan.env), "executable": {"path": str(plan.command[0]), "file": dict(executable_descriptor), "sha256": str(executable_descriptor["sha256"])},
        "namespace_descriptor": dict(namespace_descriptor), "namespace": str(plan.output_namespace), "nonce": plan.nonce, "external_authority": dict(external_authority), "formal_state_touched": False,
    }


@dataclass(frozen=True)
class AdmissionCapability:
    receipt: Mapping[str, Any]
    receipt_path: Path
    consumed_marker: Path
    lock_path: Path
    seal: str
    external_claim_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {"receipt_path": str(self.receipt_path), "consumed_marker": str(self.consumed_marker), "lock_path": str(self.lock_path), "external_claim_path": str(self.external_claim_path), "receipt_sha256": self.receipt.get("receipt_sha256"), "seal": self.seal, "diagnostic_only": True, "popen_authorized": False, "launch_allowed": False, "formal_promotion_allowed": False, "credit": 0}


def mint_admission(root: Path | str = LAB_ROOT, *, manifest: Path | str = DEFAULT_MANIFEST, training_receipt: Path | str = DEFAULT_TRAINING, checkpoint: Path | str | None = None, nonce: str | None = None, output_root: Path | str = "/tmp", resource_admission: Mapping[str, Any] | None = None, external_authority: Path | str | None = None, scheduler_authority: Path | str | None = None, python_executable: Path | str | None = None) -> dict[str, Any]:
    root_path = _absolute(root, "root")
    _reject_symlinks(root_path, "root")
    if not root_path.is_dir():
        _fail("root must be an existing directory")
    selected_nonce = _validate_nonce(nonce if nonce is not None else secrets.token_hex(16))
    if resource_admission is None:
        _fail("scheduler-owned GPU UUID/PCI snapshot is required; implicit probing is disabled")
    resource_snapshot = _validate_resource(resource_admission)
    if external_authority is not None and scheduler_authority is not None:
        _fail("provide only one external scheduler authority path")
    authority_path = external_authority if external_authority is not None else scheduler_authority
    if authority_path is None:
        _fail("external scheduler authority is required; local receipt fields are not authority")
    namespace = _namespace(output_root, selected_nonce)
    namespace_descriptor = _existing_namespace_descriptor(namespace)
    plan = _build_reserved_plan(root_path, manifest=manifest, training_receipt=training_receipt, checkpoint=checkpoint, nonce=selected_nonce, namespace=namespace, gpu_index=GPU_INDEX, python_executable=python_executable)
    authority_meta = _validate_external_authority(authority_path, nonce=selected_nonce, namespace_descriptor=namespace_descriptor, plan_sha256=_plan_binding_digest(plan), resource_snapshot=resource_snapshot)
    manifest_raw, manifest_descriptor, manifest_payload = _read_file(plan.manifest, "current manifest", max_bytes=MAX_JSON_BYTES, parse_json=True)
    del manifest_raw
    if manifest_payload is None:
        _fail("manifest payload is absent")
    training_raw, training_descriptor, training_payload = _read_file(plan.training_receipt, "training receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    del training_raw
    if training_payload is None:
        _fail("training receipt payload is absent")
    del training_payload
    checkpoint_descriptor = _file_descriptor(Path(plan.checkpoint["path"]), "checkpoint", max_bytes=MAX_CHECKPOINT_BYTES)
    if checkpoint_descriptor["sha256"] != plan.checkpoint["sha256"] or checkpoint_descriptor["bytes"] != plan.checkpoint["bytes"]:
        _fail("checkpoint content identity differs from the training receipt")
    sources = {key: _source_descriptor(root_path, relative, key) for key, relative in SOURCE_RELATIVE_PATHS.items()}
    executable = _file_descriptor(Path(plan.command[0]), "Python executable", max_bytes=MAX_EXECUTABLE_BYTES)
    if not executable["mode"] & 0o111:
        _fail("Python executable is not executable")
    # Build the identity once; do not read a path again merely to manufacture
    # a descriptor.  The executable record is patched with the descriptor just
    # captured above before hashing the identity.
    core = _identity_core(root=root_path, plan=plan, manifest_descriptor=manifest_descriptor, training_descriptor=training_descriptor, checkpoint_descriptor=checkpoint_descriptor, executable_descriptor=executable, sources=sources, resource_snapshot=resource_snapshot, namespace_descriptor=namespace_descriptor, external_authority=authority_meta)
    identity_sha = canonical_digest(core)
    marker_core = {"schema": f"{SCHEMA}.namespace_marker", "namespace": str(namespace), "nonce": selected_nonce, "identity_sha256": identity_sha, "diagnostic_only": True, "one_shot": True}
    marker_raw = (canonical_json(marker_core) + "\n").encode()
    marker_path = namespace / NAMESPACE_MARKER_NAME
    marker_descriptor = _write_exclusive(marker_path, marker_raw)
    state_path = namespace / STATE_NAME
    lock_path = namespace / CONSUMPTION_LOCK_NAME
    consumed_path = namespace / CONSUMED_NAME
    state_core = {"schema": f"{SCHEMA}.state", "state": "issued", "identity_sha256": identity_sha, "namespace": str(namespace), "nonce": selected_nonce, "namespace_marker": {key: marker_descriptor[key] for key in ("dev", "ino", "sha256")}, "lock_path": str(lock_path), "consumed_marker": str(consumed_path), "external_claim_path": authority_meta["consume_path"], "owner": {"uid": os.getuid(), "gid": os.getgid(), "host": CURRENT_HOST}, **ZERO_CREDIT}
    state_raw = (canonical_json(state_core) + "\n").encode()
    state_descriptor = _write_exclusive(state_path, state_raw)
    receipt_core: dict[str, Any] = {
        "schema": SCHEMA, "status": "issued", "receipt_version": 1, "report_id": REPORT_ID, "identity": core, "identity_sha256": identity_sha,
        "namespace_marker": {**marker_descriptor, "path": str(marker_path), "payload_sha256": hashlib.sha256(marker_raw).hexdigest()}, "receipt_path": str(namespace / RECEIPT_NAME),
        "consumption": {"one_shot": True, "state": "issued", "consumed": False, "state_file": {**state_descriptor, "path": str(state_path), "payload_sha256": hashlib.sha256(state_raw).hexdigest()}, "lock_path": str(lock_path), "consumed_marker": str(consumed_path), "external_claim_path": authority_meta["consume_path"]},
        "diagnostic_execute_only": True, "terminal_receipt_minting": False,
        "authority": {"schema": AUTHORITY_SCHEMA, "receipt_authorizes_popen": False, "diagnostic_execute_allowed": False, "launch_allowed": False, "formal_promotion_allowed": False, "credit_promotion_allowed": False, "external_gate_required": True, "formal_state_touched": False, "credit": 0},
        **ZERO_CREDIT,
    }
    receipt_core["receipt_sha256"] = canonical_digest(receipt_core)
    receipt_raw = (canonical_json(receipt_core) + "\n").encode()
    receipt_descriptor = _write_exclusive(namespace / RECEIPT_NAME, receipt_raw)
    result = dict(receipt_core)
    result["receipt_file"] = receipt_descriptor
    errors = validate_receipt(result, check_files=True)
    if errors:
        _fail("minted receipt failed self-validation: " + "; ".join(errors))
    return result


def _descriptor_equal(observed: Mapping[str, Any], expected: Mapping[str, Any], name: str) -> None:
    keys = ("path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "ctime_ns", "parent_dev", "parent_ino", "sha256")
    for key in keys:
        if observed.get(key) != expected.get(key):
            _fail(f"{name} identity drifted at {key}")


def _validate_file_descriptor(value: Any, name: str, expected_path: Path) -> dict[str, Any]:
    descriptor = dict(_mapping(value, name))
    _exact(descriptor, "path", str(expected_path), name)
    _absolute(descriptor.get("path"), f"{name}.path")
    _int(descriptor.get("dev"), f"{name}.dev")
    _int(descriptor.get("ino"), f"{name}.ino")
    _int(descriptor.get("bytes"), f"{name}.bytes", 1)
    mode = descriptor.get("mode")
    if type(mode) is not int or mode <= 0 or mode > 0o7777:
        _fail(f"{name}.mode must be a positive permission mode")
    _exact(descriptor, "uid", os.getuid(), name)
    _exact(descriptor, "gid", os.getgid(), name)
    _exact(descriptor, "nlink", 1, name)
    _int(descriptor.get("mtime_ns"), f"{name}.mtime_ns")
    _int(descriptor.get("ctime_ns"), f"{name}.ctime_ns")
    _int(descriptor.get("parent_dev"), f"{name}.parent_dev")
    _int(descriptor.get("parent_ino"), f"{name}.parent_ino")
    _sha(descriptor.get("sha256"), f"{name}.sha256")
    _exact(descriptor, "stable_fd", True, name)
    _exact(descriptor, "fd_identity_stable", True, name)
    _exact(descriptor, "path_reopened", False, name)
    _exact(descriptor, "content_opened", True, name)
    return descriptor


def _validate_written(value: Any, name: str, expected_path: Path) -> dict[str, Any]:
    descriptor = _validate_file_descriptor(value, name, expected_path)
    _exact(descriptor, "mode", 0o600, name)
    return descriptor


def _validate_identity_shape(value: Any) -> dict[str, Any]:
    core = dict(_mapping(value, "receipt.identity"))
    _unknown(core, {"model_kind", "hidden", "updates", "seed", "case_id", "split", "transitions", "frames", "run_id", "plan_sha256", "root", "manifest", "training_receipt", "checkpoint", "source_sha256", "resource_snapshot", "gpu", "gpu_identity_sha256", "command", "environment", "executable", "namespace_descriptor", "namespace", "nonce", "external_authority", "formal_state_touched"}, "receipt.identity")
    for key, expected in {"model_kind": MODEL, "hidden": HIDDEN, "updates": UPDATES, "seed": SEED, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES, "run_id": RUN_ID, "formal_state_touched": False}.items():
        _exact(core, key, expected, "receipt.identity")
    _sha(core.get("plan_sha256"), "receipt.identity.plan_sha256")
    root = _absolute(core.get("root"), "receipt.identity.root")
    manifest = dict(_mapping(core.get("manifest"), "receipt.identity.manifest"))
    _exact(manifest, "path", str(root / launcher.MANIFEST_RELATIVE), "receipt.identity.manifest")
    _sha(manifest.get("canonical_sha256"), "receipt.identity.manifest.canonical_sha256")
    _validate_file_descriptor(manifest.get("file"), "receipt.identity.manifest.file", Path(manifest["path"]))
    training = dict(_mapping(core.get("training_receipt"), "receipt.identity.training_receipt"))
    _string(training.get("path"), "receipt.identity.training_receipt.path")
    training_binding = dict(_mapping(training.get("binding"), "receipt.identity.training_receipt.binding"))
    _sha(training_binding.get("sha256"), "receipt.identity.training_receipt.binding.sha256")
    _validate_file_descriptor(training.get("file"), "receipt.identity.training_receipt.file", Path(training["path"]))
    checkpoint = dict(_mapping(core.get("checkpoint"), "receipt.identity.checkpoint"))
    _string(checkpoint.get("path"), "receipt.identity.checkpoint.path")
    _sha(checkpoint.get("declared_sha256"), "receipt.identity.checkpoint.declared_sha256")
    _sha(checkpoint.get("sha256"), "receipt.identity.checkpoint.sha256")
    _int(checkpoint.get("bytes"), "receipt.identity.checkpoint.bytes", 1)
    _validate_file_descriptor(checkpoint.get("file"), "receipt.identity.checkpoint.file", Path(checkpoint["path"]))
    sources = dict(_mapping(core.get("source_sha256"), "receipt.identity.source_sha256"))
    if set(sources) != set(SOURCE_RELATIVE_PATHS):
        _fail("receipt.identity.source_sha256 source set drifted")
    for name, descriptor in sources.items():
        _validate_file_descriptor(descriptor, f"receipt.identity.source_sha256.{name}", root / SOURCE_RELATIVE_PATHS[name])
    resource_snapshot = _validate_resource(_mapping(core.get("resource_snapshot"), "receipt.identity.resource_snapshot"))
    gpu = _gpu_identity(_mapping(core.get("gpu"), "receipt.identity.gpu"))
    _exact(core, "gpu_identity_sha256", canonical_digest(gpu), "receipt.identity")
    if canonical_json(gpu) != canonical_json(_gpu_identity(resource_snapshot["gpu"])):
        _fail("receipt.identity.gpu differs from resource snapshot")
    command = dict(_mapping(core.get("command"), "receipt.identity.command"))
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        _fail("receipt.identity.command.argv must be a non-empty string list")
    env = dict(_mapping(command.get("env_overrides"), "receipt.identity.command.env_overrides"))
    _environment(env)
    _exact(command, "cwd", str(root), "receipt.identity.command")
    _exact(command, "sha256", _command_digest(argv, str(root), env), "receipt.identity.command")
    environment = dict(_mapping(core.get("environment"), "receipt.identity.environment"))
    _exact(environment, "sha256", canonical_digest({key: value for key, value in environment.items() if key != "sha256"}), "receipt.identity.environment")
    executable = dict(_mapping(core.get("executable"), "receipt.identity.executable"))
    _exact(executable, "path", argv[0], "receipt.identity.executable")
    _sha(executable.get("sha256"), "receipt.identity.executable.sha256")
    _validate_file_descriptor(executable.get("file"), "receipt.identity.executable.file", Path(executable["path"]))
    namespace = _absolute(core.get("namespace"), "receipt.identity.namespace")
    _validate_nonce(core.get("nonce"), "receipt.identity.nonce")
    namespace_descriptor = dict(_mapping(core.get("namespace_descriptor"), "receipt.identity.namespace_descriptor"))
    _exact(namespace_descriptor, "path", str(namespace), "receipt.identity.namespace_descriptor")
    _exact(namespace_descriptor, "mode", 0o700, "receipt.identity.namespace_descriptor")
    _exact(namespace_descriptor, "uid", os.getuid(), "receipt.identity.namespace_descriptor")
    _exact(namespace_descriptor, "gid", os.getgid(), "receipt.identity.namespace_descriptor")
    _validate_external_metadata(core.get("external_authority"), namespace)
    return core


def _validate_external_metadata(value: Any, namespace: Path) -> dict[str, Any]:
    meta = dict(_mapping(value, "receipt.identity.external_authority"))
    _unknown(meta, {"schema", "path", "file", "payload_sha256", "document_sha256", "authority_id", "key_id", "consume_path", "key_file"}, "receipt.identity.external_authority")
    _exact(meta, "schema", EXTERNAL_AUTHORITY_SCHEMA, "receipt.identity.external_authority")
    _absolute(meta.get("path"), "receipt.identity.external_authority.path")
    _external_scheduler_path(meta.get("consume_path"), "receipt.identity.external_authority.consume_path")
    _sha(meta.get("payload_sha256"), "receipt.identity.external_authority.payload_sha256")
    _sha(meta.get("document_sha256"), "receipt.identity.external_authority.document_sha256")
    _sha(meta.get("authority_id"), "receipt.identity.external_authority.authority_id")
    _string(meta.get("key_id"), "receipt.identity.external_authority.key_id")
    _validate_written(meta.get("file"), "receipt.identity.external_authority.file", Path(meta["path"]))
    key_file = dict(_mapping(meta.get("key_file"), "receipt.identity.external_authority.key_file"))
    _validate_written(key_file.get("file"), "receipt.identity.external_authority.key_file.file", Path(key_file["path"]))
    _sha(key_file.get("sha256"), "receipt.identity.external_authority.key_file.sha256")
    if _under(Path(meta["consume_path"]), namespace):
        _fail("external consume path escaped independent namespace")
    return meta


def _validate_authority(value: Any) -> None:
    authority = dict(_mapping(value, "receipt.authority"))
    _unknown(authority, {"schema", "receipt_authorizes_popen", "diagnostic_execute_allowed", "launch_allowed", "formal_promotion_allowed", "credit_promotion_allowed", "external_gate_required", "formal_state_touched", "credit"}, "receipt.authority")
    _exact(authority, "schema", AUTHORITY_SCHEMA, "receipt.authority")
    for key in ("receipt_authorizes_popen", "diagnostic_execute_allowed", "launch_allowed", "formal_promotion_allowed", "credit_promotion_allowed", "formal_state_touched"):
        _exact(authority, key, False, "receipt.authority")
    _exact(authority, "external_gate_required", True, "receipt.authority")
    _exact(authority, "credit", 0, "receipt.authority")


def _validate_marker(receipt: Mapping[str, Any], namespace: Path) -> None:
    marker = dict(_mapping(receipt.get("namespace_marker"), "receipt.namespace_marker"))
    path = namespace / NAMESPACE_MARKER_NAME
    _validate_written(marker, "receipt.namespace_marker", path)
    raw, current, payload = _read_file(path, "namespace marker", max_bytes=MAX_JSON_BYTES, parse_json=True)
    _descriptor_equal(current, marker, "namespace marker")
    if hashlib.sha256(raw).hexdigest() != marker.get("payload_sha256"):
        _fail("namespace marker payload SHA drifted")
    if payload is None:
        _fail("namespace marker payload is absent")
    _unknown(payload, {"schema", "namespace", "nonce", "identity_sha256", "diagnostic_only", "one_shot"}, "namespace marker")
    _exact(payload, "schema", f"{SCHEMA}.namespace_marker", "namespace marker")
    _exact(payload, "namespace", str(namespace), "namespace marker")
    _exact(payload, "nonce", _mapping(receipt["identity"], "identity")["nonce"], "namespace marker")
    _exact(payload, "identity_sha256", receipt["identity_sha256"], "namespace marker")
    _exact(payload, "diagnostic_only", True, "namespace marker")
    _exact(payload, "one_shot", True, "namespace marker")


def validate_receipt(receipt: Mapping[str, Any], *, check_files: bool = True, allow_consumed: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(receipt, "receipt")
        allowed = set(ZERO_CREDIT) | {"schema", "status", "receipt_version", "report_id", "identity", "identity_sha256", "namespace_marker", "receipt_path", "consumption", "diagnostic_execute_only", "terminal_receipt_minting", "authority", "receipt_sha256", "receipt_file"}
        _unknown(receipt, allowed, "receipt")
        _exact(receipt, "schema", SCHEMA, "receipt")
        _exact(receipt, "status", "issued", "receipt")
        _exact(receipt, "receipt_version", 1, "receipt")
        _exact(receipt, "report_id", REPORT_ID, "receipt")
        _exact(receipt, "diagnostic_execute_only", True, "receipt")
        _exact(receipt, "terminal_receipt_minting", False, "receipt")
        for key, expected in ZERO_CREDIT.items():
            _exact(receipt, key, expected, "receipt")
        _validate_authority(receipt.get("authority"))
        core = _validate_identity_shape(receipt.get("identity"))
        _sha(receipt.get("identity_sha256"), "receipt.identity_sha256")
        _exact(receipt, "identity_sha256", canonical_digest(core), "receipt")
        namespace = _absolute(core["namespace"], "identity.namespace")
        nonce = _validate_nonce(core["nonce"], "identity.nonce")
        _exact(receipt, "receipt_path", str(namespace / RECEIPT_NAME), "receipt")
        consumption = dict(_mapping(receipt.get("consumption"), "receipt.consumption"))
        _unknown(consumption, {"one_shot", "state", "consumed", "state_file", "lock_path", "consumed_marker", "external_claim_path"}, "receipt.consumption")
        _exact(consumption, "one_shot", True, "receipt.consumption")
        _exact(consumption, "state", "issued", "receipt.consumption")
        _bool(consumption.get("consumed"), "receipt.consumption.consumed")
        _exact(consumption, "lock_path", str(namespace / CONSUMPTION_LOCK_NAME), "receipt.consumption")
        _exact(consumption, "consumed_marker", str(namespace / CONSUMED_NAME), "receipt.consumption")
        _external_scheduler_path(consumption.get("external_claim_path"), "receipt.consumption.external_claim_path")
        marker = _mapping(receipt.get("namespace_marker"), "receipt.namespace_marker")
        _validate_written(marker, "receipt.namespace_marker", namespace / NAMESPACE_MARKER_NAME)
        receipt_sha = _sha(receipt.get("receipt_sha256"), "receipt.receipt_sha256")
        receipt_core = {key: value for key, value in receipt.items() if key not in {"receipt_sha256", "receipt_file"}}
        _exact({"digest": canonical_digest(receipt_core)}, "digest", receipt_sha, "receipt digest")
        if check_files:
            _validate_external_authority(_mapping(core["external_authority"], "identity.external_authority")["path"], nonce=nonce, namespace_descriptor=core["namespace_descriptor"], plan_sha256=core["plan_sha256"], resource_snapshot=core["resource_snapshot"], expected_meta=core["external_authority"])
            _validate_marker(receipt, namespace)
            state_path = namespace / STATE_NAME
            state_info = _mapping(consumption.get("state_file"), "receipt.consumption.state_file")
            _validate_written(state_info, "receipt.consumption.state_file", state_path)
            state_raw, state_desc, state_payload = _read_file(state_path, "admission state", max_bytes=64 * 1024, parse_json=True)
            _descriptor_equal(state_desc, state_info, "admission state")
            if hashlib.sha256(state_raw).hexdigest() != state_info.get("payload_sha256"):
                _fail("admission state payload SHA drifted")
            if state_payload is None:
                _fail("admission state payload is absent")
            _exact(state_payload, "schema", f"{SCHEMA}.state", "admission state")
            _exact(state_payload, "identity_sha256", receipt["identity_sha256"], "admission state")
            _exact(state_payload, "namespace", str(namespace), "admission state")
            _exact(state_payload, "nonce", nonce, "admission state")
            for key, expected in ZERO_CREDIT.items():
                _exact(state_payload, key, expected, "admission state")
            receipt_raw, receipt_desc, file_payload = _read_file(namespace / RECEIPT_NAME, "admission receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
            if file_payload is None:
                _fail("admission receipt payload is absent")
            receipt_file_payload = {key: value for key, value in receipt.items() if key != "receipt_file"}
            if canonical_json(file_payload) != canonical_json(receipt_file_payload):
                _fail("admission receipt file payload differs from loaded receipt")
            receipt_file = receipt.get("receipt_file")
            if receipt_file is not None:
                receipt_file_descriptor = _validate_written(receipt_file, "receipt.receipt_file", namespace / RECEIPT_NAME)
                _descriptor_equal(receipt_desc, receipt_file_descriptor, "admission receipt")
                if hashlib.sha256(receipt_raw).hexdigest() != receipt_file_descriptor["sha256"]:
                    _fail("admission receipt file SHA drifted")
            lock_exists = os.path.lexists(namespace / CONSUMPTION_LOCK_NAME)
            consumed_exists = os.path.lexists(namespace / CONSUMED_NAME)
            if lock_exists != consumed_exists:
                _fail("one-shot lock and consumed marker are not paired")
            if (lock_exists or consumed_exists) and not allow_consumed:
                _fail("single-use admission has already been consumed")
            if consumed_exists:
                for path, label in ((namespace / CONSUMPTION_LOCK_NAME, "consumption lock"), (namespace / CONSUMED_NAME, "consumed marker")):
                    raw, desc, payload = _read_file(path, label, max_bytes=64 * 1024, parse_json=True)
                    del raw, desc
                    if payload is None:
                        _fail(f"{label} payload is absent")
                    _exact(payload, "receipt_sha256", receipt["receipt_sha256"], label)
                    _exact(payload, "namespace", str(namespace), label)
                    _exact(payload, "nonce", nonce, label)
                    for key, expected in ZERO_CREDIT.items():
                        _exact(payload, key, expected, label)
    except (AdmissionError, TypeError, KeyError, AttributeError, IndexError, OSError, ValueError) as error:
        errors.append(str(error))
    return errors


def load_receipt(path: Path | str, *, allow_consumed: bool = False) -> dict[str, Any]:
    candidate = _absolute(path, "admission receipt")
    _raw, _descriptor, payload = _read_file(candidate, "admission receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    if payload is None:
        _fail("admission receipt is not a JSON object")
    _exact(payload, "receipt_path", str(candidate), "admission receipt")
    errors = validate_receipt(payload, check_files=True, allow_consumed=allow_consumed)
    if errors:
        _fail("; ".join(errors))
    return payload


def revalidate_receipt(receipt: Mapping[str, Any], *, resource_admission: Mapping[str, Any] | None = None, check_files: bool = True) -> dict[str, Any]:
    errors = validate_receipt(receipt, check_files=check_files, allow_consumed=True)
    if errors:
        _fail("receipt validation failed: " + "; ".join(errors))
    core = _mapping(receipt["identity"], "receipt.identity")
    root = _absolute(core["root"], "identity.root")
    plan = _build_reserved_plan(root, manifest=core["manifest"]["path"], training_receipt=core["training_receipt"]["path"], checkpoint=core["checkpoint"]["path"], nonce=core["nonce"], namespace=Path(core["namespace"]), gpu_index=GPU_INDEX, python_executable=core["executable"]["path"])
    if _plan_binding_digest(plan) != core["plan_sha256"]:
        _fail("plan identity drifted from the receipt")
    for name, descriptor, limit in [("manifest", core["manifest"]["file"], MAX_JSON_BYTES), ("training receipt", core["training_receipt"]["file"], MAX_JSON_BYTES), ("checkpoint", core["checkpoint"]["file"], MAX_CHECKPOINT_BYTES), ("Python executable", core["executable"]["file"], MAX_EXECUTABLE_BYTES)]:
        observed = _file_descriptor(Path(descriptor["path"]), name, max_bytes=limit)
        _descriptor_equal(observed, descriptor, name)
    for name, descriptor in dict(core["source_sha256"]).items():
        _descriptor_equal(_file_descriptor(Path(descriptor["path"]), f"source.{name}", max_bytes=MAX_SOURCE_BYTES), descriptor, f"source.{name}")
    namespace_desc = _existing_namespace_descriptor(Path(core["namespace"]))
    for key in ("path", "dev", "ino", "mode", "uid", "gid", "nlink", "parent_dev", "parent_ino"):
        _exact(core["namespace_descriptor"], key, namespace_desc[key], "namespace descriptor")
    resource_snapshot = _validate_resource(resource_admission if resource_admission is not None else _mapping(core["resource_snapshot"], "identity.resource_snapshot"))
    if canonical_json(resource_snapshot) != canonical_json(core["resource_snapshot"]):
        _fail("resource snapshot drifted from the receipt")
    return {"status": "revalidated", "resource_snapshot": resource_snapshot, "identity_sha256": receipt["identity_sha256"], "receipt_sha256": receipt["receipt_sha256"], **ZERO_CREDIT}


def consume_receipt(path: Path | str) -> AdmissionCapability:
    receipt_path = _absolute(path, "admission receipt")
    receipt = load_receipt(receipt_path)
    core = _mapping(receipt["identity"], "identity")
    revalidate_receipt(receipt, resource_admission=core["resource_snapshot"])
    authority = _mapping(core["external_authority"], "identity.external_authority")
    _validate_external_authority(authority["path"], nonce=core["nonce"], namespace_descriptor=core["namespace_descriptor"], plan_sha256=core["plan_sha256"], resource_snapshot=core["resource_snapshot"], expected_meta=authority)
    claim_path = _external_scheduler_path(authority["consume_path"], "external scheduler consume claim")
    claim_raw = (canonical_json({"schema": EXTERNAL_CLAIM_SCHEMA, "state": "consumed", "authority_id": authority["authority_id"], "authority_document_sha256": authority["document_sha256"], "receipt_sha256": receipt["receipt_sha256"], "identity_sha256": receipt["identity_sha256"], "receipt_path": str(receipt_path), "namespace": core["namespace"], "nonce": core["nonce"], "claim_path": str(claim_path), "claimed_at_ns": time.time_ns(), "namespace_descriptor": dict(core["namespace_descriptor"]), "owner": {"uid": os.getuid(), "gid": os.getgid(), "host": CURRENT_HOST}, **ZERO_CREDIT}) + "\n").encode()
    try:
        _write_exclusive(claim_path, claim_raw)
    except AdmissionError as error:
        if "overwrite" in str(error):
            _fail("external scheduler authority has already been consumed")
        raise
    namespace = Path(core["namespace"])
    marker = _mapping(receipt["namespace_marker"], "namespace_marker")
    lock_path = namespace / CONSUMPTION_LOCK_NAME
    lock_raw = (canonical_json({"schema": f"{SCHEMA}.lock", "state": "locked", "receipt_sha256": receipt["receipt_sha256"], "identity_sha256": receipt["identity_sha256"], "namespace": str(namespace), "nonce": core["nonce"], "namespace_marker": {"dev": marker["dev"], "ino": marker["ino"]}, "external_claim": {"path": str(claim_path), "authority_id": authority["authority_id"], "document_sha256": authority["document_sha256"]}, "owner": {"uid": os.getuid(), "gid": os.getgid(), "host": CURRENT_HOST}, **ZERO_CREDIT}) + "\n").encode()
    lock_descriptor = _write_exclusive(lock_path, lock_raw)
    consumed_path = namespace / CONSUMED_NAME
    consumed_raw = (canonical_json({"schema": CONSUMED_SCHEMA, "state": "consumed", "receipt_sha256": receipt["receipt_sha256"], "identity_sha256": receipt["identity_sha256"], "receipt_path": str(receipt_path), "namespace": str(namespace), "nonce": core["nonce"], "namespace_marker": {"dev": marker["dev"], "ino": marker["ino"]}, "external_claim": {"path": str(claim_path), "authority_id": authority["authority_id"], "document_sha256": authority["document_sha256"]}, "lock": lock_descriptor, "consumed_at_ns": time.time_ns(), "owner": {"uid": os.getuid(), "gid": os.getgid(), "host": CURRENT_HOST}, **ZERO_CREDIT}) + "\n").encode()
    consumed_descriptor = _write_exclusive(consumed_path, consumed_raw)
    seal = canonical_digest({"receipt_sha256": receipt["receipt_sha256"], "consumed_marker": consumed_descriptor, "claim": str(claim_path), "diagnostic_only": True, "credit": 0})
    return AdmissionCapability(receipt=receipt, receipt_path=receipt_path, consumed_marker=consumed_path, lock_path=lock_path, seal=seal, external_claim_path=claim_path)


def _report_base(*, blocked: Sequence[str], source_bound: bool = False, receipt: Mapping[str, Any] | None = None, resource_snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"schema": REPORT_SCHEMA, "report_id": REPORT_ID, "status": "blocked_fail_closed", "admission_granted": False, "receipt_bound_capability_issued": False, "diagnostic_execute_only": True, "diagnostic_execute_allowed": False, "execution_capability_admitted": False, "launch_allowed": False, "source_bound": source_bound, "receipt_path": None if receipt is None else receipt.get("receipt_path"), "receipt_sha256": None if receipt is None else receipt.get("receipt_sha256"), "namespace": None if receipt is None else receipt.get("identity", {}).get("namespace"), "resource_snapshot": resource_snapshot, "single_use": True, "receipt_mode": 0o600, "namespace_mode": 0o700, "popen_attempted": False, "processes_started": 0, "formal_state_touched": False, "registry_writes": 0, "ledger_writes": 0, "denominator_writes": 0, "gate_writes": 0, "completion_writes": 0, "plan_writes": 0, "blocked_reasons": list(dict.fromkeys(str(item) for item in blocked if item)), **ZERO_CREDIT}
    if receipt is not None:
        result["identity"] = dict(receipt["identity"])
    return result


def build_report(root: Path | str = LAB_ROOT, *, manifest: Path | str = DEFAULT_MANIFEST, training_receipt: Path | str = DEFAULT_TRAINING, checkpoint: Path | str | None = None, nonce: str | None = None, output_root: Path | str = "/tmp", resource_admission: Mapping[str, Any] | None = None, external_authority: Path | str | None = None, scheduler_authority: Path | str | None = None) -> dict[str, Any]:
    try:
        receipt = mint_admission(root, manifest=manifest, training_receipt=training_receipt, checkpoint=checkpoint, nonce=nonce, output_root=output_root, resource_admission=resource_admission, external_authority=external_authority, scheduler_authority=scheduler_authority)
        return _report_base(blocked=("terminal Popen/wait and artifact proof are not admitted", "formal/credit promotion requires an external Core gate and ledger"), source_bound=True, receipt=receipt, resource_snapshot=receipt["identity"]["resource_snapshot"])
    except (AdmissionError, identity.IdentityError, launcher.LauncherError, OSError, ValueError) as error:
        return _report_base(blocked=(str(error),))


def validate_report(report: Mapping[str, Any]) -> list[str]:
    try:
        _walk_json(report, "report")
        allowed = set(ZERO_CREDIT) | {"schema", "report_id", "status", "admission_granted", "receipt_bound_capability_issued", "diagnostic_execute_only", "diagnostic_execute_allowed", "execution_capability_admitted", "launch_allowed", "source_bound", "receipt_path", "receipt_sha256", "namespace", "resource_snapshot", "identity", "single_use", "receipt_mode", "namespace_mode", "popen_attempted", "processes_started", "formal_state_touched", "registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes", "blocked_reasons"}
        _unknown(report, allowed, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        for key, expected in {"admission_granted": False, "receipt_bound_capability_issued": False, "diagnostic_execute_only": True, "diagnostic_execute_allowed": False, "execution_capability_admitted": False, "launch_allowed": False, "popen_attempted": False, "formal_state_touched": False}.items():
            _exact(report, key, expected, "report")
        _exact(report, "processes_started", 0, "report")
        for key in ("registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"):
            _exact(report, key, 0, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a non-empty string list")
        if report.get("source_bound"):
            _sha(report.get("receipt_sha256"), "report.receipt_sha256")
            _absolute(report.get("receipt_path"), "report.receipt_path")
            _absolute(report.get("namespace"), "report.namespace")
    except (AdmissionError, TypeError, KeyError) as error:
        return [str(error)]
    return []


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join(["# F3 graph_residual hidden16 seed43 diagnostic admission", "", f"- status: `{report.get('status')}`", f"- source bound: `{report.get('source_bound')}`", f"- receipt: `{report.get('receipt_path')}`", "- admission: external scheduler signature + independent one-shot claim required", "- execution: no Popen/wait path is admitted; terminal receipts are not minted", "- GPU: physical GPU6 / logical cuda:0 is a snapshot binding only, never live evidence", "- formal/registry/ledger/denominator/gate/completion/PLAN writes: `0`; credit: `0`", "", "## Blockers", "", *[f"- {item}" for item in report.get("blocked_reasons", []) if isinstance(item, str)], ""])


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    _write_exclusive(path, (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), mode=0o640)
    _write_exclusive(path.with_suffix(".zh-CN.md"), render_markdown(report).encode(), mode=0o640)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--training-receipt", type=Path, default=DEFAULT_TRAINING)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--nonce", default=None)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            _raw, _descriptor, payload = _read_file(_absolute(args.verify_report, "report"), "report", max_bytes=MAX_JSON_BYTES, parse_json=True)
            if payload is None:
                _fail("report is not a JSON object")
            errors = validate_report(payload)
            print(canonical_json({"schema": REPORT_SCHEMA, "valid": not errors, "errors": errors}))
            return 0 if not errors else 1
        report = build_report(root=args.root, manifest=args.manifest, training_receipt=args.training_receipt, checkpoint=args.checkpoint, nonce=args.nonce, output_root=args.output_root)
        _write_report(args.report_output, report)
        print(canonical_json(report))
        return 2
    except (AdmissionError, OSError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
