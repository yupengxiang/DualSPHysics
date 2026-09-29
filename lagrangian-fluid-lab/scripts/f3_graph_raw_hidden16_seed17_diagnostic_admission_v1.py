#!/usr/bin/env python3
"""Receipt-bound, diagnostic-only admission for the graph_raw seed17 canary.

This module is deliberately narrower than a production scheduler.  It can
mint one bounded, zero-credit receipt and consume it once.  The receipt binds
the current manifest, training receipt, checkpoint bytes, core-learning
source, validator sources, GPU-2 resource snapshot, exact evaluator argv,
the full835 identity, and an exclusive namespace marker.  Consumption is an
atomic filesystem event; a second consumer is rejected.

No solver, worker, queue, registry, ledger, denominator, gate, completion,
or PLAN state is read or written.  This contract never starts a process.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import errno
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

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - the bounded lab venv supplies cryptography.
    Ed25519PublicKey = None  # type: ignore[assignment,misc]

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_raw_hidden16_current_manifest_audited_executor_v1 as resource
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
MANIFEST_SCHEMA = launcher.MANIFEST_SCHEMA
TRAINING_SCHEMA = launcher.TRAINING_SCHEMA
CHECKPOINT_SCHEMA = launcher.CHECKPOINT_SCHEMA

SCHEMA = "core.f3.graph_raw.hidden16.seed17.diagnostic_admission.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
CONSUMED_SCHEMA = f"{SCHEMA}.consumed"
REPORT_ID = "f3-graph-raw-hidden16-seed17-diagnostic-admission-v1"
DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_TRAINING = Path(
    "/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"
)
DEFAULT_REPORT = LAB_ROOT / "reports" / "F3-GRAPH-RAW-HIDDEN16-SEED17-DIAGNOSTIC-ADMISSION-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
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
EXTERNAL_AUTHORITY_DOMAIN = b"CORE-F3-GRAPH-RAW-SEED17-EXTERNAL-AUTHORITY-V1\0"
# These are deployment trust anchors, not request parameters.  A production
# scheduler must install them outside the lab/tmp trees with owner-only write
# access.  The test suite monkeypatches the paths to a synthetic scheduler
# fixture; no production receipt is minted from that fixture.
TRUSTED_SCHEDULER_PUBLIC_KEY_PATH = Path(
    "/etc/dual-sph/scheduler-ed25519-public.key"
)
EXTERNAL_SCHEDULER_ROOT = Path("/var/lib/dual-sph/f3-seed17-scheduler")
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

SOURCE_RELATIVE_PATHS = {
    "core_learning": Path("scripts/core_learning.py"),
    "hdf5_validator": Path("scripts/f3_full_rollout_receipt_hdf5_validator_v1.py"),
    "hardened_validator": Path("scripts/f3_graph_terminal_validator_security_hardening_v1.py"),
    "terminal_artifact_validator": Path(
        "scripts/f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1.py"
    ),
}


class AdmissionError(ValueError):
    """Malformed, drifting, reused, or unsafe diagnostic admission."""


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
    if os.path.normpath(raw) != raw:
        _fail(f"{name} uses a lexical path alias")
    path = Path(raw)
    if path.anchor != "/" or not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} must be absolute and lexical-alias free")
    return path


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _reject_symlink_components(path: Path, name: str, *, allow_missing_leaf: bool = False) -> None:
    current = Path(path.anchor or "/")
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


def _open_parent_directory(path: Path | str, name: str) -> tuple[int, dict[str, int]]:
    """Open every directory component with O_NOFOLLOW and retain its fd."""

    candidate = _absolute(path, name)
    _reject_symlink_components(candidate, name)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd: int | None = None
    try:
        fd = os.open("/", flags)
        for part in candidate.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            _fail(f"{name} is not a directory")
        return fd, {
            "dev": int(info.st_dev),
            "ino": int(info.st_ino),
            "uid": int(info.st_uid),
            "gid": int(info.st_gid),
        }
    except AdmissionError:
        if fd is not None:
            os.close(fd)
        raise
    except OSError as error:
        if fd is not None:
            os.close(fd)
        _fail(f"cannot open {name} without following links: {error}")


def _assert_parent_unchanged(path: Path, parent_identity: Mapping[str, int], name: str) -> None:
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name} parent after access: {error}")
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or int(info.st_dev) != int(parent_identity["dev"])
        or int(info.st_ino) != int(parent_identity["ino"])
    ):
        _fail(f"{name} parent changed during access")


def _read_file(path: Path | str, name: str, *, max_bytes: int, parse_json: bool = False) -> tuple[bytes, dict[str, Any], dict[str, Any] | None]:
    candidate = _absolute(path, name)
    parent_fd, parent_identity = _open_parent_directory(candidate.parent, f"{name} parent")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        before = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{name} must be a regular non-symlink single-link file")
        if before.st_size < 1 or before.st_size > max_bytes:
            _fail(f"{name} is outside the bounded size")
        fd = os.open(candidate.name, flags, dir_fd=parent_fd)
        opened = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != identity:
            _fail(f"{name} changed before read")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        closed = os.fstat(fd)
        if (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns) != identity or total != before.st_size:
            _fail(f"{name} changed during read")
        after = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity:
            _fail(f"{name} changed after read")
        _assert_parent_unchanged(candidate.parent, parent_identity, name)
        _reject_symlink_components(candidate, name)
    except OSError as error:
        _fail(f"cannot read {name} without following links: {error}")
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)
    raw = b"".join(chunks)
    descriptor = {
        "path": str(candidate),
        "dev": int(before.st_dev),
        "ino": int(before.st_ino),
        "bytes": int(len(raw)),
        "mode": int(stat.S_IMODE(before.st_mode)),
        "uid": int(before.st_uid),
        "gid": int(before.st_gid),
        "nlink": int(before.st_nlink),
        "mtime_ns": int(before.st_mtime_ns),
        "parent_dev": int(parent_identity["dev"]),
        "parent_ino": int(parent_identity["ino"]),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
    }
    payload: dict[str, Any] | None = None
    if parse_json:
        try:
            loaded = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
        except (UnicodeError, json.JSONDecodeError, AdmissionError, RecursionError) as error:
            _fail(f"invalid {name}: {error}")
        _walk_json(loaded, name)
        payload = dict(_mapping(loaded, name))
    return raw, descriptor, payload


def _mkdir_exclusive(path: Path | str, *, mode: int = 0o700) -> dict[str, Any]:
    candidate = _absolute(path, "exclusive directory")
    parent_fd, parent_identity = _open_parent_directory(candidate.parent, "exclusive directory parent")
    try:
        os.mkdir(candidate.name, mode, dir_fd=parent_fd)
        info = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != mode:
            _fail(f"exclusive directory {candidate} owner/mode drifted")
        if info.st_uid != os.getuid() or info.st_gid != os.getgid():
            _fail(f"exclusive directory {candidate} owner drifted")
        _assert_parent_unchanged(candidate.parent, parent_identity, "exclusive directory")
        os.fsync(parent_fd)
    except FileExistsError:
        _fail(f"refusing to reuse existing directory: {candidate}")
    except OSError as error:
        _fail(f"cannot create exclusive directory {candidate}: {error}")
    finally:
        os.close(parent_fd)
    return {
        "path": str(candidate),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "parent_dev": int(parent_identity["dev"]),
        "parent_ino": int(parent_identity["ino"]),
    }


def _write_exclusive(path: Path, raw: bytes, *, mode: int = 0o600) -> dict[str, Any]:
    path = _absolute(path, "exclusive output")
    parent_fd, parent_identity = _open_parent_directory(path.parent, "exclusive output parent")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd: int | None = None
    try:
        fd = os.open(path.name, flags, mode, dir_fd=parent_fd)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != mode
            or info.st_uid != os.getuid()
            or info.st_gid != os.getgid()
            or info.st_nlink != 1
            or info.st_size != len(raw)
        ):
            _fail(f"exclusive file {path} owner/mode/link drifted")
        _assert_parent_unchanged(path.parent, parent_identity, "exclusive output")
        os.fsync(parent_fd)
    except FileExistsError:
        _fail(f"refusing to overwrite existing file: {path}")
    except OSError as error:
        _fail(f"cannot write exclusive file {path}: {error}")
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)
    return {
        "path": str(path),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "bytes": int(info.st_size),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "mtime_ns": int(info.st_mtime_ns),
        "parent_dev": int(parent_identity["dev"]),
        "parent_ino": int(parent_identity["ino"]),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _validate_nonce(value: Any) -> str:
    nonce = _string(value, "nonce")
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail("nonce must be a non-zero lowercase 32-hex value")
    return nonce


def _namespace(output_root: Path | str, nonce: str) -> Path:
    root = _absolute(output_root, "output_root")
    temp = Path(tempfile.gettempdir()).resolve()
    _reject_symlink_components(root, "output_root")
    if not root.is_dir():
        _fail("output_root must be an existing directory")
    if not _under(root, temp):
        _fail("output_root must remain under /tmp")
    return root / f"f3-graph_raw500-hidden16-currentmanifest-seed{SEED}-full835-nonce{nonce}"


def _existing_namespace_descriptor(path: Path | str) -> dict[str, Any]:
    """Describe a scheduler-reserved namespace without creating or replacing it."""

    candidate = _absolute(path, "scheduler-reserved namespace")
    _reject_symlink_components(candidate, "scheduler-reserved namespace")
    try:
        info = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect scheduler-reserved namespace: {error}")
    if not stat.S_ISDIR(info.st_mode):
        _fail("scheduler-reserved namespace must be a directory")
    if stat.S_IMODE(info.st_mode) != 0o700:
        _fail("scheduler-reserved namespace must be mode 0700")
    if info.st_uid != os.getuid() or info.st_gid != os.getgid():
        _fail("scheduler-reserved namespace owner drifted")
    if info.st_nlink < 2:
        _fail("scheduler-reserved namespace link count is invalid")
    parent_fd, parent_identity = _open_parent_directory(
        candidate.parent, "scheduler-reserved namespace parent"
    )
    try:
        current = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(current.st_mode)
            or stat.S_IMODE(current.st_mode) != 0o700
            or current.st_uid != os.getuid()
            or current.st_gid != os.getgid()
            or current.st_dev != info.st_dev
            or current.st_ino != info.st_ino
        ):
            _fail("scheduler-reserved namespace changed during inspection")
        _assert_parent_unchanged(candidate.parent, parent_identity, "scheduler-reserved namespace")
    except OSError as error:
        _fail(f"cannot inspect scheduler-reserved namespace parent: {error}")
    finally:
        os.close(parent_fd)
    return {
        "path": str(candidate),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "parent_dev": int(parent_identity["dev"]),
        "parent_ino": int(parent_identity["ino"]),
    }


def _source_descriptor(root: Path, relative: Path, name: str) -> dict[str, Any]:
    path = root / relative
    if not _under(path, root):
        _fail(f"{name} escapes the lab root")
    if not _under(path.resolve(strict=False), root):
        _fail(f"{name} resolves outside the lab root")
    _raw, descriptor, _ = _read_file(path, name, max_bytes=MAX_SOURCE_BYTES)
    return descriptor


def _checkpoint_descriptor(path: Path) -> dict[str, Any]:
    _raw, descriptor, _ = _read_file(path, "checkpoint", max_bytes=MAX_CHECKPOINT_BYTES)
    return descriptor


def _validate_owner(value: Any, name: str) -> dict[str, Any]:
    owner = dict(_mapping(value, name))
    _reject_unknown(owner, {"uid", "gid", "host", "scope", "snapshot_nonce"}, name)
    _exact(owner, "uid", os.getuid(), name)
    _exact(owner, "gid", os.getgid(), name)
    _exact(owner, "host", CURRENT_HOST, name)
    _exact(owner, "scope", "scheduler_owned_diagnostic_snapshot", name)
    _validate_nonce(owner.get("snapshot_nonce"))
    return owner


def _gpu_identity(gpu: Mapping[str, Any]) -> dict[str, Any]:
    identity = {
        "physical_index": gpu.get("physical_index"),
        "uuid": gpu.get("uuid"),
        "pci_bus_id": gpu.get("pci_bus_id"),
        "logical_index": gpu.get("logical_index"),
        "cuda_visible_devices": gpu.get("cuda_visible_devices"),
        "cuda_device": gpu.get("cuda_device"),
        "cuda_device_order": gpu.get("cuda_device_order"),
    }
    _int(identity["physical_index"], "resource_admission.gpu.physical_index")
    if identity["physical_index"] != GPU_INDEX:
        _fail("GPU physical index is not bound to GPU2")
    uuid = _string(identity["uuid"], "resource_admission.gpu.uuid")
    if GPU_UUID_RE.fullmatch(uuid) is None or len(set(uuid.upper())) <= 2:
        _fail("resource_admission.gpu.uuid is not a stable non-placeholder UUID")
    pci = _string(identity["pci_bus_id"], "resource_admission.gpu.pci_bus_id")
    if PCI_BUS_RE.fullmatch(pci) is None:
        _fail("resource_admission.gpu.pci_bus_id is not canonical")
    _exact(identity, "logical_index", LOGICAL_GPU_INDEX, "resource_admission.gpu")
    _exact(identity, "cuda_visible_devices", str(GPU_INDEX), "resource_admission.gpu")
    _exact(identity, "cuda_device", "cuda:0", "resource_admission.gpu")
    _exact(identity, "cuda_device_order", CUDA_DEVICE_ORDER, "resource_admission.gpu")
    return identity


def _validate_resource(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    _reject_unknown(
        payload,
        {"schema", "gpu_index", "gpu", "cpu", "io", "thresholds", "status", "admitted", "blocked_reasons", "content_opened", "owner"},
        "resource_admission",
    )
    _exact(payload, "schema", resource.ADMISSION_SCHEMA, "resource_admission")
    _exact(payload, "gpu_index", GPU_INDEX, "resource_admission")
    _exact(payload, "status", "admitted", "resource_admission")
    _bool(payload.get("admitted"), "resource_admission.admitted")
    if not payload["admitted"]:
        _fail("GPU2 resource snapshot is not admitted")
    _exact(payload, "content_opened", False, "resource_admission")
    blocked = payload.get("blocked_reasons")
    if not isinstance(blocked, list) or blocked:
        _fail("resource_admission.blocked_reasons must be empty for an admitted snapshot")
    gpu = _mapping(payload.get("gpu"), "resource_admission.gpu")
    _reject_unknown(
        gpu,
        {
            "total_mib", "used_mib", "free_mib", "physical_index", "uuid",
            "pci_bus_id", "logical_index", "cuda_visible_devices",
            "cuda_device", "cuda_device_order", "identity_source",
            "identity_attested", "identity_sha256",
        },
        "resource_admission.gpu",
    )
    for key in ("total_mib", "used_mib", "free_mib"):
        _int(gpu.get(key), f"resource_admission.gpu.{key}")
    if gpu["used_mib"] + gpu["free_mib"] > gpu["total_mib"]:
        _fail("GPU2 used/free VRAM exceeds total VRAM")
    gpu_identity = _gpu_identity(gpu)
    _exact(gpu, "identity_source", "scheduler_owned_snapshot", "resource_admission.gpu")
    _exact(gpu, "identity_attested", True, "resource_admission.gpu")
    _exact(gpu, "identity_sha256", canonical_digest(gpu_identity), "resource_admission.gpu")
    _validate_owner(payload.get("owner"), "resource_admission.owner")
    return payload


def _command_digest(argv: Sequence[str], cwd: str, env: Mapping[str, str]) -> str:
    return canonical_digest({"argv": list(argv), "cwd": cwd, "env_overrides": dict(env), "gpu_index": GPU_INDEX, "seed": SEED, "case_id": CASE_ID, "split": SPLIT, "transitions": TRANSITIONS, "frames": FRAMES})


def _plan_binding(plan: launcher.RolloutPlan) -> dict[str, Any]:
    """Return the exact scheduler-visible plan identity used by the signature."""

    env = dict(plan.env)
    env["CUDA_DEVICE_ORDER"] = CUDA_DEVICE_ORDER
    rollout_snapshot = launcher.rollout_plan_snapshot(plan)
    return {
        "schema": f"{EXTERNAL_AUTHORITY_SCHEMA}.plan",
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
        },
        "checkpoint": dict(plan.checkpoint),
        "checkpoint_metadata": dict(plan.checkpoint_metadata),
        "namespace": str(plan.namespace),
        "outputs": {key: str(value) for key, value in plan.outputs.items()},
        "command": list(plan.command),
        "env_overrides": env,
        "command_sha256": _command_digest(plan.command, str(plan.root), env),
        "launcher_command_sha256": str(plan.command_sha256),
        "rollout_snapshot": rollout_snapshot,
        "rollout_snapshot_sha256": launcher.rollout_plan_snapshot_digest(plan),
    }


def _plan_binding_digest(plan: launcher.RolloutPlan) -> str:
    return canonical_digest(_plan_binding(plan))


def _build_reserved_plan(
    root: Path,
    *,
    manifest: Path | str,
    training_receipt: Path | str,
    checkpoint: Path | str | None,
    nonce: str,
    namespace: Path,
    gpu_index: int,
) -> launcher.RolloutPlan:
    """Build launcher identity against a shadow path, then bind reserved paths.

    The existing launcher intentionally rejects reused namespaces.  A
    scheduler, however, must reserve the namespace before signing its inode.
    The shadow plan therefore exercises the unchanged launcher parser while
    this admission contract replaces only the path-bearing plan fields with
    the already-reserved namespace and rechecks every output collision.
    """

    with tempfile.TemporaryDirectory(
        prefix="f3-graph-raw-seed17-plan-",
        dir=tempfile.gettempdir(),
    ) as shadow_root_text:
        shadow_namespace = Path(shadow_root_text) / namespace.name
        plan = launcher.build_plan(
            root,
            seed=SEED,
            manifest=manifest,
            training_receipt=training_receipt,
            checkpoint=checkpoint,
            nonce=nonce,
            output_namespace=shadow_namespace,
            gpu_index=gpu_index,
        )
    outputs = launcher._output_paths(
        namespace,
        root,
        SEED,
        nonce,
        plan.manifest_sha256,
    )
    for name, output in outputs.items():
        if name == "namespace":
            continue
        launcher._absolute_path(output, f"output.{name}")
        launcher._assert_no_symlink_components(output.parent, f"output.{name} parent")
        if os.path.lexists(output):
            _fail(f"refusing to reuse reserved output.{name}: {output}")
    command = launcher._command_for(
        root=root,
        python=Path(plan.command[0]),
        manifest=plan.manifest,
        checkpoint=Path(str(plan.checkpoint["path"])),
        outputs=outputs,
    )
    command_sha256 = launcher.canonical_digest(
        {
            "argv": list(command),
            "cwd": str(root),
            "env_overrides": dict(plan.env),
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
        }
    )
    return replace(
        plan,
        namespace=namespace,
        outputs=outputs,
        command=command,
        command_sha256=command_sha256,
    )


def _external_scheduler_root() -> Path:
    root = _absolute(EXTERNAL_SCHEDULER_ROOT, "external scheduler root")
    _reject_symlink_components(root, "external scheduler root")
    if not root.is_dir():
        _fail("external scheduler root is not an existing directory")
    return root


def _external_scheduler_path(value: Path | str, name: str) -> Path:
    root = _external_scheduler_root()
    candidate = _absolute(value, name)
    if candidate == root or not _under(candidate, root):
        _fail(f"{name} must remain under the external scheduler root")
    _reject_symlink_components(candidate.parent, f"{name} parent")
    return candidate


def _authority_signing_message(unsigned: Mapping[str, Any]) -> bytes:
    return EXTERNAL_AUTHORITY_DOMAIN + canonical_json(dict(unsigned)).encode("utf-8")


def _authority_unsigned(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in document.items()
        if key != "signature_base64"
    }


def _authority_namespace_claim(value: Any) -> dict[str, Any]:
    claim = dict(_mapping(value, "external_authority.namespace"))
    _reject_unknown(
        claim,
        {"path", "dev", "ino", "mode", "uid", "gid", "nlink", "parent_dev", "parent_ino"},
        "external_authority.namespace",
    )
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
    _reject_unknown(owner, {"uid", "gid", "host"}, name)
    _int(owner.get("uid"), f"{name}.uid")
    _int(owner.get("gid"), f"{name}.gid")
    _string(owner.get("host"), f"{name}.host")
    return owner


def _authority_gpu(value: Any) -> dict[str, Any]:
    gpu = dict(_mapping(value, "external_authority.gpu"))
    _reject_unknown(
        gpu,
        {
            "physical_index", "uuid", "pci_bus_id", "logical_index",
            "cuda_visible_devices", "cuda_device", "cuda_device_order",
        },
        "external_authority.gpu",
    )
    return _gpu_identity(gpu)


def _read_trusted_scheduler_key() -> tuple[bytes, dict[str, Any]]:
    key_path = _absolute(TRUSTED_SCHEDULER_PUBLIC_KEY_PATH, "trusted scheduler public key")
    _reject_symlink_components(key_path, "trusted scheduler public key")
    raw, descriptor, _ = _read_file(
        key_path,
        "trusted scheduler public key",
        max_bytes=64,
        parse_json=False,
    )
    if len(raw) != 32:
        _fail("trusted scheduler public key must be exactly 32 bytes")
    if descriptor["mode"] & 0o022:
        _fail("trusted scheduler public key is group/other writable")
    return raw, descriptor


def _validate_external_authority(
    path: Path | str,
    *,
    nonce: str,
    namespace_descriptor: Mapping[str, Any],
    plan_sha256: str,
    resource_snapshot: Mapping[str, Any],
    expected_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify an external signed reservation and return receipt metadata.

    The authority is intentionally not mintable by this module.  Its public
    key is a deployment trust anchor, while the signed document is an
    external scheduler reservation.  The local receipt is never sufficient
    to substitute for either one.
    """

    authority_path = _external_scheduler_path(path, "external scheduler authority")
    raw, descriptor, payload = _read_file(
        authority_path,
        "external scheduler authority",
        max_bytes=256 * 1024,
        parse_json=True,
    )
    if payload is None:
        _fail("external scheduler authority payload is absent")
    _reject_unknown(
        payload,
        {
            "schema", "authority_id", "state", "one_shot", "owner", "scheduler",
            "namespace", "nonce", "plan_sha256", "resource_snapshot_sha256",
            "gpu", "gpu_identity_sha256", "consume_path", "key_id",
            "signature_algorithm", "signature_base64",
        },
        "external scheduler authority",
    )
    _exact(payload, "schema", EXTERNAL_AUTHORITY_SCHEMA, "external scheduler authority")
    authority_id = _sha(payload.get("authority_id"), "external_authority.authority_id")
    _exact(payload, "state", "issued", "external scheduler authority")
    _exact(payload, "one_shot", True, "external scheduler authority")
    owner = _authority_owner(payload.get("owner"), "external_authority.owner")
    _exact(owner, "uid", os.getuid(), "external_authority.owner")
    _exact(owner, "gid", os.getgid(), "external_authority.owner")
    _exact(owner, "host", CURRENT_HOST, "external_authority.owner")
    scheduler_raw = dict(_mapping(payload.get("scheduler"), "external_authority.scheduler"))
    _reject_unknown(scheduler_raw, {"uid", "gid", "host", "role"}, "external_authority.scheduler")
    _int(scheduler_raw.get("uid"), "external_authority.scheduler.uid")
    _int(scheduler_raw.get("gid"), "external_authority.scheduler.gid")
    _string(scheduler_raw.get("host"), "external_authority.scheduler.host")
    _exact(scheduler_raw, "role", "external_scheduler", "external_authority.scheduler")

    claimed_namespace = _authority_namespace_claim(payload.get("namespace"))
    if canonical_json(claimed_namespace) != canonical_json(dict(namespace_descriptor)):
        _fail("external scheduler authority namespace inode binding drifted")
    _exact(payload, "nonce", _validate_nonce(nonce), "external scheduler authority")
    _exact(payload, "plan_sha256", _sha(plan_sha256, "plan_sha256"), "external scheduler authority")
    resource_digest = _sha(
        payload.get("resource_snapshot_sha256"),
        "external_authority.resource_snapshot_sha256",
    )
    if resource_digest != canonical_digest(resource_snapshot):
        _fail("external scheduler authority resource snapshot binding drifted")
    gpu_identity = _authority_gpu(payload.get("gpu"))
    resource_gpu = _gpu_identity(_mapping(resource_snapshot.get("gpu"), "resource_admission.gpu"))
    if canonical_json(gpu_identity) != canonical_json(resource_gpu):
        _fail("external scheduler authority GPU identity binding drifted")
    _exact(
        payload,
        "gpu_identity_sha256",
        canonical_digest(gpu_identity),
        "external_authority",
    )
    consume_path = _external_scheduler_path(
        payload.get("consume_path"), "external scheduler consume path"
    )
    if consume_path == authority_path or _under(consume_path, Path(namespace_descriptor["path"])):
        _fail("external scheduler consume path is not independent of the local namespace")
    _string(payload.get("key_id"), "external_authority.key_id")
    _exact(payload, "signature_algorithm", "ed25519", "external_authority")
    signature_text = _string(payload.get("signature_base64"), "external_authority.signature_base64")
    try:
        signature = base64.b64decode(signature_text.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        _fail(f"external scheduler authority signature is not strict base64: {error}")
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != signature_text:
        _fail("external scheduler authority signature is not canonical Ed25519")
    public_key_bytes, key_descriptor = _read_trusted_scheduler_key()
    key_id = hashlib.sha256(public_key_bytes).hexdigest()
    _exact(payload, "key_id", key_id, "external_authority")
    if Ed25519PublicKey is None:
        _fail("cryptography Ed25519 verifier is unavailable")
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature,
            _authority_signing_message(_authority_unsigned(payload)),
        )
    except Exception as error:
        # ``InvalidSignature`` is deliberately normalized to the same
        # fail-closed error as malformed key material.
        _fail(f"external scheduler authority signature verification failed: {error}")

    unsigned_digest = canonical_digest(_authority_unsigned(payload))
    metadata = {
        "schema": EXTERNAL_AUTHORITY_SCHEMA,
        "path": str(authority_path),
        "file": dict(descriptor),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "document_sha256": unsigned_digest,
        "authority_id": authority_id,
        "key_id": key_id,
        "consume_path": str(consume_path),
        "key_file": {
            "path": str(TRUSTED_SCHEDULER_PUBLIC_KEY_PATH),
            "file": dict(key_descriptor),
            "sha256": hashlib.sha256(public_key_bytes).hexdigest(),
        },
    }
    if expected_meta is not None and canonical_json(dict(expected_meta)) != canonical_json(metadata):
        _fail("external scheduler authority descriptor drifted from the receipt")
    return metadata


def _environment_snapshot(env: Mapping[str, str]) -> dict[str, Any]:
    effective = dict(env)
    expected = {
        "CUDA_VISIBLE_DEVICES": str(GPU_INDEX),
        "CUDA_DEVICE_ORDER": CUDA_DEVICE_ORDER,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if effective != expected:
        _fail("environment is not the minimal fixed allowlist")
    snapshot = {
        "policy": "allowlist_only_no_ambient_inheritance",
        "inherit": False,
        "variables": effective,
    }
    snapshot["sha256"] = canonical_digest(snapshot)
    return snapshot


def _executable_descriptor(path: Path | str) -> dict[str, Any]:
    candidate = _absolute(path, "Python executable")
    if not candidate.is_file():
        _fail("Python executable is not an existing file")
    _raw, descriptor, _ = _read_file(
        candidate,
        "Python executable",
        max_bytes=MAX_EXECUTABLE_BYTES,
        parse_json=False,
    )
    if not (descriptor["mode"] & 0o111):
        _fail("Python executable is not executable")
    return descriptor


def _identity_core(
    *,
    root: Path,
    plan: launcher.RolloutPlan,
    manifest_descriptor: Mapping[str, Any],
    training_descriptor: Mapping[str, Any],
    checkpoint_descriptor: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    resource_snapshot: Mapping[str, Any],
    executable_descriptor: Mapping[str, Any],
    namespace_descriptor: Mapping[str, Any],
    namespace: Path,
    nonce: str,
    external_authority: Mapping[str, Any],
) -> dict[str, Any]:
    env = dict(plan.env)
    env["CUDA_DEVICE_ORDER"] = CUDA_DEVICE_ORDER
    command = list(plan.command)
    environment = _environment_snapshot(env)
    gpu = dict(_mapping(resource_snapshot["gpu"], "resource_admission.gpu"))
    rollout_snapshot = launcher.rollout_plan_snapshot(plan)
    return {
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seed": SEED,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "run_id": plan.run_id,
        "plan_sha256": _plan_binding_digest(plan),
        "rollout_snapshot": rollout_snapshot,
        "rollout_snapshot_sha256": launcher.rollout_plan_snapshot_digest(plan),
        "root": str(root),
        "manifest": {
            "path": str(plan.manifest),
            "canonical_sha256": plan.manifest_sha256,
            "file": dict(manifest_descriptor),
        },
        "training_receipt": {
            "path": str(plan.training_receipt),
            "file": dict(training_descriptor),
        },
        "checkpoint": {
            "path": str(plan.checkpoint["path"]),
            "declared_sha256": str(plan.checkpoint["sha256"]),
            "sha256": str(checkpoint_descriptor["sha256"]),
            "bytes": int(checkpoint_descriptor["bytes"]),
            "file": dict(checkpoint_descriptor),
        },
        "source_sha256": {key: dict(value) for key, value in sources.items()},
        "resource_snapshot": dict(resource_snapshot),
        "gpu": gpu,
        "gpu_identity_sha256": canonical_digest(_gpu_identity(gpu)),
        "command": {
            "argv": command,
            "cwd": str(root),
            "env_overrides": env,
            "sha256": _command_digest(command, str(root), env),
        },
        "environment": environment,
        "executable": {
            "path": str(command[0]),
            "file": dict(executable_descriptor),
            "sha256": str(executable_descriptor["sha256"]),
        },
        "owner": {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "host": CURRENT_HOST,
        },
        "namespace_descriptor": dict(namespace_descriptor),
        "namespace": str(namespace),
        "nonce": nonce,
        "external_authority": dict(external_authority),
    }


def _reconcile_plan_reread(
    plan: launcher.RolloutPlan,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Reread plan inputs through stable descriptors before any admission state."""

    _manifest_raw, manifest_descriptor, manifest_payload = _read_file(
        plan.manifest,
        "final current manifest",
        max_bytes=MAX_JSON_BYTES,
        parse_json=True,
    )
    del _manifest_raw
    _training_raw, training_descriptor, training_payload = _read_file(
        plan.training_receipt,
        "final training receipt",
        max_bytes=MAX_JSON_BYTES,
        parse_json=True,
    )
    del _training_raw
    checkpoint_descriptor = _checkpoint_descriptor(Path(str(plan.checkpoint["path"])))
    if manifest_payload is None or training_payload is None:
        _fail("final RolloutPlan reread payload is absent")
    reconciliation = launcher.reconcile_plan_snapshot(
        plan,
        manifest_descriptor=manifest_descriptor,
        manifest_payload=manifest_payload,
        training_descriptor=training_descriptor,
        training_payload=training_payload,
        checkpoint_descriptor=checkpoint_descriptor,
    )
    return (
        reconciliation,
        manifest_descriptor,
        training_descriptor,
        checkpoint_descriptor,
    )


def _reconcile_receipt_snapshot(
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Reread receipt inputs and cross-bind them to its sealed plan snapshot."""

    snapshot = launcher.validate_rollout_plan_snapshot(
        identity.get("rollout_snapshot"),
        "identity.rollout_snapshot",
    )
    manifest_record = _mapping(snapshot["manifest"], "identity.rollout_snapshot.manifest")
    training_record = _mapping(
        snapshot["training_receipt"],
        "identity.rollout_snapshot.training_receipt",
    )
    checkpoint_record = _mapping(
        snapshot["checkpoint"],
        "identity.rollout_snapshot.checkpoint",
    )
    manifest = _absolute(manifest_record["path"], "rollout snapshot manifest")
    training = _absolute(training_record["path"], "rollout snapshot training receipt")
    checkpoint = _absolute(checkpoint_record["path"], "rollout snapshot checkpoint")
    root = _absolute(snapshot["root"], "rollout snapshot root")
    for path, name in (
        (manifest, "manifest"),
        (training, "training receipt"),
        (checkpoint, "checkpoint"),
    ):
        if not _under(path, root) and not _under(path, Path("/tmp")):
            _fail(f"{name} escapes bounded roots")
    _manifest_raw, manifest_descriptor, manifest_payload = _read_file(
        manifest,
        "final current manifest",
        max_bytes=MAX_JSON_BYTES,
        parse_json=True,
    )
    del _manifest_raw
    _training_raw, training_descriptor, training_payload = _read_file(
        training,
        "final training receipt",
        max_bytes=MAX_JSON_BYTES,
        parse_json=True,
    )
    del _training_raw
    checkpoint_descriptor = _checkpoint_descriptor(checkpoint)
    if manifest_payload is None or training_payload is None:
        _fail("final receipt reread payload is absent")
    return launcher.reconcile_rollout_snapshot(
        snapshot,
        manifest_descriptor=manifest_descriptor,
        manifest_payload=manifest_payload,
        training_descriptor=training_descriptor,
        training_payload=training_payload,
        checkpoint_descriptor=checkpoint_descriptor,
        expected_snapshot_sha256=identity.get("rollout_snapshot_sha256"),
    )


def _marker_core(identity_digest: str, namespace: Path, nonce: str) -> dict[str, Any]:
    return {
        "schema": f"{SCHEMA}.namespace_marker",
        "namespace": str(namespace),
        "nonce": nonce,
        "identity_sha256": identity_digest,
        "diagnostic_only": True,
        "one_shot": True,
    }


@dataclass(frozen=True)
class AdmissionCapability:
    receipt: Mapping[str, Any]
    receipt_path: Path
    consumed_marker: Path
    lock_path: Path
    seal: str
    external_claim_path: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_path": str(self.receipt_path),
            "consumed_marker": str(self.consumed_marker),
            "external_claim_path": None if self.external_claim_path is None else str(self.external_claim_path),
            "receipt_sha256": self.receipt.get("receipt_sha256"),
            "seal": self.seal,
            "diagnostic_only": True,
            "popen_authorized": False,
            "launch_allowed": False,
            "formal_promotion_allowed": False,
            "credit": 0,
        }


def mint_admission(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipt: Path | str = DEFAULT_TRAINING,
    checkpoint: Path | str | None = None,
    nonce: str | None = None,
    output_root: Path | str = "/tmp",
    resource_admission: Mapping[str, Any] | None = None,
    external_authority: Path | str | None = None,
    scheduler_authority: Path | str | None = None,
) -> dict[str, Any]:
    """Mint one strict receipt after external scheduler attestation.

    The scheduler must reserve the namespace before this function is called.
    A local caller cannot create or substitute the authority document.
    """

    root_path = _absolute(root, "root")
    _reject_symlink_components(root_path, "root")
    if not root_path.is_dir() or stat.S_ISLNK(os.lstat(root_path).st_mode):
        _fail("root must be an existing directory")
    selected_nonce = _validate_nonce(nonce if nonce is not None else secrets.token_hex(16))
    namespace = _namespace(output_root, selected_nonce)
    _reject_symlink_components(namespace.parent, "namespace parent")

    if resource_admission is None:
        _fail("scheduler-owned GPU UUID/PCI snapshot is required; implicit probing is disabled")
    resource_snapshot = _validate_resource(resource_admission)
    if external_authority is not None and scheduler_authority is not None:
        _fail("provide only one external scheduler authority path")
    authority_path = external_authority if external_authority is not None else scheduler_authority

    # launcher is the existing identity authority for current-manifest v3,
    # exact command construction, and seed17/checkpoint cross-binding.
    plan = _build_reserved_plan(
        root_path,
        manifest=manifest,
        training_receipt=training_receipt,
        checkpoint=checkpoint,
        nonce=selected_nonce,
        namespace=namespace,
        gpu_index=GPU_INDEX,
    )
    if authority_path is None:
        _fail("external scheduler authority is required; local receipt fields are not authority")
    # This is the final stable reread boundary.  It must precede both the
    # external authority validation/consumption path and every namespace state
    # write, so a plan/input mismatch cannot leave a locally issued receipt.
    (
        rollout_reconciliation,
        manifest_descriptor,
        training_descriptor,
        checkpoint_descriptor,
    ) = _reconcile_plan_reread(plan)
    namespace_descriptor = _existing_namespace_descriptor(namespace)
    authority_metadata = _validate_external_authority(
        authority_path,
        nonce=selected_nonce,
        namespace_descriptor=namespace_descriptor,
        plan_sha256=_plan_binding_digest(plan),
        resource_snapshot=resource_snapshot,
    )
    sources = {key: _source_descriptor(root_path, relative, key) for key, relative in SOURCE_RELATIVE_PATHS.items()}
    executable_path = _absolute(plan.command[0], "Python executable")
    if not _under(executable_path, root_path):
        _fail("Python executable escapes the lab root")
    executable_descriptor = _executable_descriptor(executable_path)
    identity = _identity_core(
        root=root_path,
        plan=plan,
        manifest_descriptor=manifest_descriptor,
        training_descriptor=training_descriptor,
        checkpoint_descriptor=checkpoint_descriptor,
        sources=sources,
        resource_snapshot=resource_snapshot,
        executable_descriptor=executable_descriptor,
        namespace_descriptor=namespace_descriptor,
        namespace=namespace,
        nonce=selected_nonce,
        external_authority=authority_metadata,
    )
    if rollout_reconciliation["plan_sha256"] != launcher.rollout_plan_snapshot_digest(plan):
        _fail("final RolloutPlan reconciliation digest drifted before namespace state")
    identity_digest = canonical_digest(identity)
    marker_core = _marker_core(identity_digest, namespace, selected_nonce)
    marker_raw = (canonical_json(marker_core) + "\n").encode("utf-8")
    marker_path = namespace / ".diagnostic-admission-marker.json"
    marker_descriptor = _write_exclusive(marker_path, marker_raw, mode=0o600)
    receipt_path = namespace / ".diagnostic-admission-receipt.json"
    state_path = namespace / STATE_NAME
    lock_path = namespace / CONSUMPTION_LOCK_NAME
    consumed_path = namespace / CONSUMED_NAME
    state_core = {
        "schema": f"{SCHEMA}.state",
        "state": "issued",
        "identity_sha256": identity_digest,
        "namespace": str(namespace),
        "nonce": selected_nonce,
        "namespace_marker": {
            "dev": marker_descriptor["dev"],
            "ino": marker_descriptor["ino"],
            "sha256": marker_descriptor["sha256"],
            "payload_sha256": hashlib.sha256(marker_raw).hexdigest(),
        },
        "lock_path": str(lock_path),
        "consumed_marker": str(consumed_path),
        "external_claim_path": authority_metadata["consume_path"],
        "owner": {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "host": CURRENT_HOST,
        },
        **ZERO_CREDIT,
    }
    state_raw = (canonical_json(state_core) + "\n").encode("utf-8")
    state_descriptor = _write_exclusive(state_path, state_raw, mode=0o600)
    receipt_core: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "issued",
        "receipt_version": 1,
        "report_id": REPORT_ID,
        "identity": identity,
        "identity_sha256": identity_digest,
        "namespace_marker": {
            **marker_descriptor,
            "path": str(marker_path),
            "payload_sha256": hashlib.sha256(marker_raw).hexdigest(),
        },
        "receipt_path": str(receipt_path),
        "consumption": {
            "one_shot": True,
            "state": "issued",
            "consumed": False,
            "state_file": {
                **state_descriptor,
                "path": str(state_path),
                "payload_sha256": hashlib.sha256(state_raw).hexdigest(),
            },
            "lock_path": str(lock_path),
            "consumed_marker": str(consumed_path),
            "external_claim_path": authority_metadata["consume_path"],
        },
        "diagnostic_execute_only": True,
        "authority": {
            "schema": AUTHORITY_SCHEMA,
            "receipt_authorizes_popen": False,
            "diagnostic_execute_allowed": False,
            "launch_allowed": False,
            "formal_promotion_allowed": False,
            "credit_promotion_allowed": False,
            "external_gate_required": True,
            "formal_state_touched": False,
            "credit": 0,
        },
        **ZERO_CREDIT,
    }
    receipt_core["receipt_sha256"] = canonical_digest(receipt_core)
    receipt_raw = (canonical_json(receipt_core) + "\n").encode("utf-8")
    receipt_descriptor = _write_exclusive(receipt_path, receipt_raw, mode=0o600)
    result = dict(receipt_core)
    result["receipt_file"] = receipt_descriptor
    validate_receipt(result, check_files=True, allow_consumed=False)
    return result


def _validate_file_descriptor_shape(value: Any, name: str) -> dict[str, Any]:
    descriptor = dict(_mapping(value, name))
    _reject_unknown(
        descriptor,
        {"path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "parent_dev", "parent_ino", "sha256", "content_opened"},
        name,
    )
    _absolute(descriptor.get("path"), f"{name}.path")
    _int(descriptor.get("dev"), f"{name}.dev")
    _int(descriptor.get("ino"), f"{name}.ino")
    _int(descriptor.get("bytes"), f"{name}.bytes", 1)
    _int(descriptor.get("mode"), f"{name}.mode")
    _int(descriptor.get("uid"), f"{name}.uid")
    _int(descriptor.get("gid"), f"{name}.gid")
    _exact(descriptor, "nlink", 1, name)
    _int(descriptor.get("mtime_ns"), f"{name}.mtime_ns")
    _int(descriptor.get("parent_dev"), f"{name}.parent_dev")
    _int(descriptor.get("parent_ino"), f"{name}.parent_ino")
    _sha(descriptor.get("sha256"), f"{name}.sha256")
    _exact(descriptor, "content_opened", True, name)
    return descriptor


def _validate_external_authority_metadata(
    value: Any,
    *,
    namespace: Path,
) -> dict[str, Any]:
    metadata = dict(_mapping(value, "identity.external_authority"))
    _reject_unknown(
        metadata,
        {
            "schema", "path", "file", "payload_sha256", "document_sha256",
            "authority_id", "key_id", "consume_path", "key_file",
        },
        "identity.external_authority",
    )
    _exact(metadata, "schema", EXTERNAL_AUTHORITY_SCHEMA, "identity.external_authority")
    authority_path = _external_scheduler_path(
        metadata.get("path"), "identity.external_authority.path"
    )
    authority_file = _validate_file_descriptor_shape(
        metadata.get("file"), "identity.external_authority.file"
    )
    if authority_file["path"] != str(authority_path):
        _fail("identity.external_authority.file.path is inconsistent")
    _sha(metadata.get("payload_sha256"), "identity.external_authority.payload_sha256")
    _sha(metadata.get("document_sha256"), "identity.external_authority.document_sha256")
    _sha(metadata.get("authority_id"), "identity.external_authority.authority_id")
    _sha(metadata.get("key_id"), "identity.external_authority.key_id")
    consume_path = _external_scheduler_path(
        metadata.get("consume_path"), "identity.external_authority.consume_path"
    )
    if consume_path == authority_path or _under(consume_path, namespace):
        _fail("identity.external_authority.consume_path is not independent")
    key_file = dict(_mapping(metadata.get("key_file"), "identity.external_authority.key_file"))
    _reject_unknown(key_file, {"path", "file", "sha256"}, "identity.external_authority.key_file")
    _exact(key_file, "path", str(TRUSTED_SCHEDULER_PUBLIC_KEY_PATH), "identity.external_authority.key_file")
    key_descriptor = _validate_file_descriptor_shape(
        key_file.get("file"), "identity.external_authority.key_file.file"
    )
    if key_descriptor["path"] != key_file["path"]:
        _fail("identity.external_authority.key_file.file.path is inconsistent")
    _sha(key_file.get("sha256"), "identity.external_authority.key_file.sha256")
    return metadata


def _validate_namespace_descriptor(value: Any, namespace: Path) -> dict[str, Any]:
    descriptor = dict(_mapping(value, "identity.namespace_descriptor"))
    _reject_unknown(
        descriptor,
        {"path", "dev", "ino", "mode", "uid", "gid", "nlink", "parent_dev", "parent_ino"},
        "identity.namespace_descriptor",
    )
    _exact(descriptor, "path", str(namespace), "identity.namespace_descriptor")
    _int(descriptor.get("dev"), "identity.namespace_descriptor.dev")
    _int(descriptor.get("ino"), "identity.namespace_descriptor.ino")
    _exact(descriptor, "mode", 0o700, "identity.namespace_descriptor")
    _exact(descriptor, "uid", os.getuid(), "identity.namespace_descriptor")
    _exact(descriptor, "gid", os.getgid(), "identity.namespace_descriptor")
    _int(descriptor.get("nlink"), "identity.namespace_descriptor.nlink", 2)
    _int(descriptor.get("parent_dev"), "identity.namespace_descriptor.parent_dev")
    _int(descriptor.get("parent_ino"), "identity.namespace_descriptor.parent_ino")
    return descriptor


def _validate_identity_shape(identity: Mapping[str, Any]) -> None:
    _reject_unknown(
        identity,
        {
            "model_kind", "hidden", "updates", "seed", "case_id", "split", "transitions",
            "frames", "run_id", "root", "manifest", "training_receipt", "checkpoint",
            "source_sha256", "resource_snapshot", "gpu", "gpu_identity_sha256", "command",
            "environment", "executable", "owner", "namespace_descriptor", "namespace", "nonce",
            "plan_sha256", "rollout_snapshot", "rollout_snapshot_sha256",
            "external_authority",
        },
        "identity",
    )
    _exact(identity, "model_kind", MODEL, "identity")
    _exact(identity, "hidden", HIDDEN, "identity")
    _exact(identity, "updates", UPDATES, "identity")
    _exact(identity, "seed", SEED, "identity")
    _exact(identity, "case_id", CASE_ID, "identity")
    _exact(identity, "split", SPLIT, "identity")
    _exact(identity, "transitions", TRANSITIONS, "identity")
    _exact(identity, "frames", FRAMES, "identity")
    _sha(identity.get("plan_sha256"), "identity.plan_sha256")
    rollout_snapshot = launcher.validate_rollout_plan_snapshot(
        identity.get("rollout_snapshot"),
        "identity.rollout_snapshot",
    )
    rollout_snapshot_sha256 = _sha(
        identity.get("rollout_snapshot_sha256"),
        "identity.rollout_snapshot_sha256",
    )
    if rollout_snapshot_sha256 != launcher.canonical_digest(rollout_snapshot):
        _fail("identity.rollout_snapshot_sha256 does not bind the stable snapshot")
    _validate_nonce(identity.get("nonce"))
    namespace = _absolute(identity.get("namespace"), "identity.namespace")
    expected_name = f"f3-graph_raw500-hidden16-currentmanifest-seed{SEED}-full835-nonce{identity['nonce']}"
    if namespace.name != expected_name or not _under(namespace, Path(tempfile.gettempdir()).resolve()):
        _fail("identity.namespace is not the fresh seed17/full835 nonce namespace")
    root = _absolute(identity.get("root"), "identity.root")
    _reject_symlink_components(root, "identity.root")
    _validate_namespace_descriptor(identity.get("namespace_descriptor"), namespace)
    _validate_external_authority_metadata(
        identity.get("external_authority"),
        namespace=namespace,
    )
    owner = dict(_mapping(identity.get("owner"), "identity.owner"))
    _reject_unknown(owner, {"uid", "gid", "host"}, "identity.owner")
    _exact(owner, "uid", os.getuid(), "identity.owner")
    _exact(owner, "gid", os.getgid(), "identity.owner")
    _exact(owner, "host", CURRENT_HOST, "identity.owner")
    resource_snapshot = _validate_resource(
        _mapping(identity.get("resource_snapshot"), "identity.resource_snapshot")
    )
    gpu = dict(_mapping(identity.get("gpu"), "identity.gpu"))
    _gpu_identity(gpu)
    _exact(gpu, "identity_sha256", canonical_digest(_gpu_identity(gpu)), "identity.gpu")
    if canonical_digest(_gpu_identity(gpu)) != _sha(
        identity.get("gpu_identity_sha256"), "identity.gpu_identity_sha256"
    ):
        _fail("identity GPU UUID/PCI mapping digest drifted")
    if canonical_json(gpu) != canonical_json(resource_snapshot["gpu"]):
        _fail("identity GPU snapshot differs from the owner resource snapshot")
    manifest = dict(_mapping(identity.get("manifest"), "identity.manifest"))
    _reject_unknown(manifest, {"path", "canonical_sha256", "file"}, "identity.manifest")
    manifest_path = _absolute(manifest.get("path"), "identity.manifest.path")
    _sha(manifest.get("canonical_sha256"), "identity.manifest.canonical_sha256")
    _validate_file_descriptor_shape(manifest.get("file"), "identity.manifest.file")
    training = dict(_mapping(identity.get("training_receipt"), "identity.training_receipt"))
    _reject_unknown(training, {"path", "file"}, "identity.training_receipt")
    _absolute(training.get("path"), "identity.training_receipt.path")
    _validate_file_descriptor_shape(training.get("file"), "identity.training_receipt.file")
    checkpoint = dict(_mapping(identity.get("checkpoint"), "identity.checkpoint"))
    _reject_unknown(
        checkpoint,
        {"path", "declared_sha256", "sha256", "bytes", "file"},
        "identity.checkpoint",
    )
    _absolute(checkpoint.get("path"), "identity.checkpoint.path")
    _sha(checkpoint.get("declared_sha256"), "identity.checkpoint.declared_sha256")
    _sha(checkpoint.get("sha256"), "identity.checkpoint.sha256")
    _int(checkpoint.get("bytes"), "identity.checkpoint.bytes", 1)
    _validate_file_descriptor_shape(checkpoint.get("file"), "identity.checkpoint.file")
    source_sha = _mapping(identity.get("source_sha256"), "identity.source_sha256")
    if set(source_sha) != set(SOURCE_RELATIVE_PATHS):
        _fail("identity.source_sha256 does not cover every pinned source")
    for key, value in source_sha.items():
        item = _validate_file_descriptor_shape(value, f"identity.source_sha256.{key}")
        if Path(item["path"]) != root / SOURCE_RELATIVE_PATHS[key]:
            _fail(f"identity.source_sha256.{key}.path is not rooted in the bound lab")
    command = _mapping(identity.get("command"), "identity.command")
    _reject_unknown(command, {"argv", "cwd", "env_overrides", "sha256"}, "identity.command")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) for item in argv):
        _fail("identity.command.argv must be a non-empty string list")
    _exact(command, "cwd", identity.get("root"), "identity.command")
    env = _mapping(command.get("env_overrides"), "identity.command.env_overrides")
    _exact(env, "CUDA_VISIBLE_DEVICES", str(GPU_INDEX), "identity.command.env_overrides")
    _exact(env, "CUDA_DEVICE_ORDER", CUDA_DEVICE_ORDER, "identity.command.env_overrides")
    _exact(env, "PYTHONDONTWRITEBYTECODE", "1", "identity.command.env_overrides")
    if set(env) != {"CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER", "PYTHONDONTWRITEBYTECODE"}:
        _fail("identity command environment contains an unbound ambient variable")
    _sha(command.get("sha256"), "identity.command.sha256")
    if command["sha256"] != _command_digest(argv, command["cwd"], env):
        _fail("identity exact command digest mismatch")
    expected = {
        "--case-id": CASE_ID,
        "--split": SPLIT,
        "--maximum-steps": str(TRANSITIONS),
        "--device": "cuda:0",
    }
    for option, value in expected.items():
        positions = [i for i, item in enumerate(argv) if item == option]
        if len(positions) != 1 or positions[0] + 1 >= len(argv) or argv[positions[0] + 1] != value:
            _fail(f"identity command is not bound to {option}={value}")
    if argv[-1] != "--diagnostic" or "--diagnostic" in argv[:-1]:
        _fail("identity command must end with one --diagnostic flag")
    executable = dict(_mapping(identity.get("executable"), "identity.executable"))
    _reject_unknown(executable, {"path", "file", "sha256"}, "identity.executable")
    executable_path = _absolute(executable.get("path"), "identity.executable.path")
    if executable_path != Path(argv[0]) or not _under(executable_path, root):
        _fail("identity executable path is not the bound root-local argv[0]")
    _sha(executable.get("sha256"), "identity.executable.sha256")
    executable_file = _validate_file_descriptor_shape(
        executable.get("file"), "identity.executable.file"
    )
    if executable_file["path"] != str(executable_path) or executable_file["sha256"] != executable["sha256"]:
        _fail("identity executable content snapshot is inconsistent")
    if not (executable_file["mode"] & 0o111):
        _fail("identity executable snapshot is not executable")
    environment = dict(_mapping(identity.get("environment"), "identity.environment"))
    _reject_unknown(environment, {"policy", "inherit", "variables", "sha256"}, "identity.environment")
    _exact(environment, "policy", "allowlist_only_no_ambient_inheritance", "identity.environment")
    _exact(environment, "inherit", False, "identity.environment")
    variables = _mapping(environment.get("variables"), "identity.environment.variables")
    if canonical_json(dict(variables)) != canonical_json(dict(env)):
        _fail("identity environment snapshot differs from command environment")
    _exact(
        environment,
        "sha256",
        canonical_digest({
            "policy": environment["policy"],
            "inherit": environment["inherit"],
            "variables": dict(variables),
        }),
        "identity.environment",
    )

    snapshot_manifest = _mapping(rollout_snapshot["manifest"], "identity.rollout_snapshot.manifest")
    snapshot_training = _mapping(
        rollout_snapshot["training_receipt"],
        "identity.rollout_snapshot.training_receipt",
    )
    snapshot_checkpoint = _mapping(
        rollout_snapshot["checkpoint"],
        "identity.rollout_snapshot.checkpoint",
    )
    if snapshot_manifest["path"] != manifest["path"]:
        _fail("identity rollout snapshot manifest path drifted")
    if snapshot_manifest["canonical_sha256"] != manifest["canonical_sha256"]:
        _fail("identity rollout snapshot manifest digest drifted")
    if snapshot_manifest["file_sha256"] != manifest["file"]["sha256"]:
        _fail("identity rollout snapshot manifest file digest drifted")
    if snapshot_training["path"] != training["path"]:
        _fail("identity rollout snapshot training path drifted")
    if snapshot_training["file_sha256"] != training["file"]["sha256"]:
        _fail("identity rollout snapshot training file digest drifted")
    if snapshot_checkpoint["path"] != checkpoint["path"]:
        _fail("identity rollout snapshot checkpoint path drifted")
    if snapshot_checkpoint["sha256"] != checkpoint["sha256"]:
        _fail("identity rollout snapshot checkpoint digest drifted")
    if snapshot_checkpoint["bytes"] != checkpoint["bytes"]:
        _fail("identity rollout snapshot checkpoint bytes drifted")
    if rollout_snapshot["root"] != identity["root"]:
        _fail("identity rollout snapshot root drifted")
    if rollout_snapshot["namespace"] != identity["namespace"]:
        _fail("identity rollout snapshot namespace drifted")
    if rollout_snapshot["nonce"] != identity["nonce"]:
        _fail("identity rollout snapshot nonce drifted")
    if rollout_snapshot["command"] != command["argv"]:
        _fail("identity rollout snapshot command drifted")
    expected_snapshot_env = dict(rollout_snapshot["env_overrides"])
    expected_snapshot_env["CUDA_DEVICE_ORDER"] = CUDA_DEVICE_ORDER
    if canonical_json(expected_snapshot_env) != canonical_json(dict(env)):
        _fail("identity rollout snapshot environment drifted")


def _validate_marker(receipt: Mapping[str, Any]) -> dict[str, Any]:
    marker = dict(_mapping(receipt.get("namespace_marker"), "namespace_marker"))
    _reject_unknown(
        marker,
        {"path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "parent_dev", "parent_ino", "sha256", "payload_sha256"},
        "namespace_marker",
    )
    marker_path = _absolute(marker.get("path"), "namespace_marker.path")
    namespace = _absolute(_mapping(receipt.get("identity"), "identity").get("namespace"), "identity.namespace")
    if marker_path.parent != namespace or marker_path.name != NAMESPACE_MARKER_NAME:
        _fail("namespace marker is not inside the bound namespace")
    _reject_symlink_components(marker_path, "namespace marker")
    for key, expected in (
        ("mode", 0o600),
        ("uid", os.getuid()),
        ("gid", os.getgid()),
        ("nlink", 1),
    ):
        _exact(marker, key, expected, "namespace_marker")
    for key in ("dev", "ino", "bytes", "mtime_ns", "parent_dev", "parent_ino"):
        _int(marker.get(key), f"namespace_marker.{key}", 1 if key != "bytes" else 1)
    _sha(marker.get("sha256"), "namespace_marker.sha256")
    _sha(marker.get("payload_sha256"), "namespace_marker.payload_sha256")
    raw, descriptor, payload = _read_file(marker_path, "namespace marker", max_bytes=64 * 1024, parse_json=True)
    if payload is None:
        _fail("namespace marker payload is absent")
    for key in ("path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "parent_dev", "parent_ino", "sha256"):
        if descriptor.get(key) != marker[key]:
            _fail(f"namespace marker {key} drifted")
    expected_payload_sha = marker.get("payload_sha256")
    if expected_payload_sha != hashlib.sha256(raw).hexdigest():
        _fail("namespace marker payload SHA drifted")
    _exact(payload, "schema", f"{SCHEMA}.namespace_marker", "namespace marker")
    _exact(payload, "namespace", str(namespace), "namespace marker")
    _exact(payload, "nonce", _mapping(receipt["identity"], "identity")["nonce"], "namespace marker")
    _exact(payload, "identity_sha256", receipt["identity_sha256"], "namespace marker")
    _exact(payload, "diagnostic_only", True, "namespace marker")
    _exact(payload, "one_shot", True, "namespace marker")
    return descriptor


def _validate_written_descriptor(
    value: Any,
    name: str,
    *,
    expected_path: Path,
    expected_mode: int = 0o600,
) -> dict[str, Any]:
    descriptor = dict(_mapping(value, name))
    _reject_unknown(
        descriptor,
        {"path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "parent_dev", "parent_ino", "sha256", "payload_sha256", "content_opened"},
        name,
    )
    _exact(descriptor, "path", str(expected_path), name)
    _int(descriptor.get("dev"), f"{name}.dev")
    _int(descriptor.get("ino"), f"{name}.ino")
    _int(descriptor.get("bytes"), f"{name}.bytes", 1)
    _exact(descriptor, "mode", expected_mode, name)
    _exact(descriptor, "uid", os.getuid(), name)
    _exact(descriptor, "gid", os.getgid(), name)
    _exact(descriptor, "nlink", 1, name)
    _int(descriptor.get("mtime_ns"), f"{name}.mtime_ns")
    _int(descriptor.get("parent_dev"), f"{name}.parent_dev")
    _int(descriptor.get("parent_ino"), f"{name}.parent_ino")
    _sha(descriptor.get("sha256"), f"{name}.sha256")
    if "payload_sha256" in descriptor:
        _sha(descriptor.get("payload_sha256"), f"{name}.payload_sha256")
    if "content_opened" in descriptor:
        _exact(descriptor, "content_opened", True, name)
    return descriptor


def _validate_authority(receipt: Mapping[str, Any]) -> None:
    authority = dict(_mapping(receipt.get("authority"), "authority"))
    _reject_unknown(
        authority,
        {"schema", "receipt_authorizes_popen", "diagnostic_execute_allowed", "launch_allowed", "formal_promotion_allowed", "credit_promotion_allowed", "external_gate_required", "formal_state_touched", "credit"},
        "authority",
    )
    _exact(authority, "schema", AUTHORITY_SCHEMA, "authority")
    for key in (
        "receipt_authorizes_popen",
        "diagnostic_execute_allowed",
        "launch_allowed",
        "formal_promotion_allowed",
        "credit_promotion_allowed",
        "formal_state_touched",
    ):
        _exact(authority, key, False, "authority")
    _exact(authority, "external_gate_required", True, "authority")
    _exact(authority, "credit", 0, "authority")


def _validate_state_file(
    receipt: Mapping[str, Any],
    *,
    namespace: Path,
    marker: Mapping[str, Any],
) -> dict[str, Any]:
    consumption = _mapping(receipt["consumption"], "consumption")
    state_info = dict(_mapping(consumption.get("state_file"), "consumption.state_file"))
    state_path = namespace / STATE_NAME
    descriptor = _validate_written_descriptor(
        state_info,
        "consumption.state_file",
        expected_path=state_path,
    )
    _sha(state_info.get("payload_sha256"), "consumption.state_file.payload_sha256")
    raw, current_descriptor, payload = _read_file(
        state_path,
        "admission state",
        max_bytes=64 * 1024,
        parse_json=True,
    )
    for key in descriptor:
        if key != "payload_sha256" and current_descriptor.get(key) != descriptor[key]:
            _fail(f"admission state {key} drifted")
    if hashlib.sha256(raw).hexdigest() != state_info["payload_sha256"]:
        _fail("admission state payload SHA drifted")
    if payload is None:
        _fail("admission state payload is absent")
    _reject_unknown(
        payload,
        {
            "schema", "state", "identity_sha256", "namespace", "nonce",
            "namespace_marker", "lock_path", "consumed_marker",
            "external_claim_path", "owner", *ZERO_CREDIT,
        },
        "admission state",
    )
    _exact(payload, "schema", f"{SCHEMA}.state", "admission state")
    _exact(payload, "state", "issued", "admission state")
    _exact(payload, "identity_sha256", receipt["identity_sha256"], "admission state")
    _exact(payload, "namespace", str(namespace), "admission state")
    _exact(payload, "nonce", _mapping(receipt["identity"], "identity")["nonce"], "admission state")
    state_marker = _mapping(payload.get("namespace_marker"), "admission state.namespace_marker")
    for key in ("dev", "ino", "sha256", "payload_sha256"):
        _exact(state_marker, key, marker[key] if key != "payload_sha256" else marker["payload_sha256"], "admission state.namespace_marker")
    _exact(payload, "lock_path", str(namespace / CONSUMPTION_LOCK_NAME), "admission state")
    _exact(payload, "consumed_marker", str(namespace / CONSUMED_NAME), "admission state")
    _exact(
        payload,
        "external_claim_path",
        _mapping(receipt["consumption"], "consumption")["external_claim_path"],
        "admission state",
    )
    owner = dict(_mapping(payload.get("owner"), "admission state.owner"))
    _reject_unknown(owner, {"uid", "gid", "host"}, "admission state.owner")
    _exact(owner, "uid", os.getuid(), "admission state.owner")
    _exact(owner, "gid", os.getgid(), "admission state.owner")
    _exact(owner, "host", CURRENT_HOST, "admission state.owner")
    for key, expected in ZERO_CREDIT.items():
        _exact(payload, key, expected, "admission state")
    return current_descriptor


def _validate_lock_file(
    receipt: Mapping[str, Any],
    *,
    namespace: Path,
    marker: Mapping[str, Any],
) -> dict[str, Any]:
    lock_path = namespace / CONSUMPTION_LOCK_NAME
    raw, descriptor, payload = _read_file(
        lock_path,
        "consumption lock",
        max_bytes=64 * 1024,
        parse_json=True,
    )
    del raw
    _validate_written_descriptor(descriptor, "consumption lock", expected_path=lock_path)
    if payload is None:
        _fail("consumption lock payload is absent")
    _reject_unknown(
        payload,
        {
            "schema", "state", "identity_sha256", "namespace", "nonce",
            "namespace_marker", "external_claim", "owner", *ZERO_CREDIT,
        },
        "consumption lock",
    )
    _exact(payload, "schema", f"{SCHEMA}.lock", "consumption lock")
    _exact(payload, "state", "locked", "consumption lock")
    _exact(payload, "identity_sha256", receipt["identity_sha256"], "consumption lock")
    _exact(payload, "namespace", str(namespace), "consumption lock")
    _exact(payload, "nonce", _mapping(receipt["identity"], "identity")["nonce"], "consumption lock")
    lock_marker = _mapping(payload.get("namespace_marker"), "consumption lock.namespace_marker")
    for key in ("dev", "ino"):
        _exact(lock_marker, key, marker[key], "consumption lock.namespace_marker")
    lock_claim = dict(_mapping(payload.get("external_claim"), "consumption lock.external_claim"))
    _reject_unknown(lock_claim, {"path", "authority_id", "document_sha256"}, "consumption lock.external_claim")
    _exact(
        lock_claim,
        "path",
        _mapping(receipt["consumption"], "consumption")["external_claim_path"],
        "consumption lock.external_claim",
    )
    authority = _mapping(_mapping(receipt["identity"], "identity")["external_authority"], "identity.external_authority")
    _exact(lock_claim, "authority_id", authority["authority_id"], "consumption lock.external_claim")
    _exact(lock_claim, "document_sha256", authority["document_sha256"], "consumption lock.external_claim")
    owner = dict(_mapping(payload.get("owner"), "consumption lock.owner"))
    _reject_unknown(owner, {"uid", "gid", "host"}, "consumption lock.owner")
    _exact(owner, "uid", os.getuid(), "consumption lock.owner")
    _exact(owner, "gid", os.getgid(), "consumption lock.owner")
    _exact(owner, "host", CURRENT_HOST, "consumption lock.owner")
    for key, expected in ZERO_CREDIT.items():
        _exact(payload, key, expected, "consumption lock")
    return descriptor


def _validate_consumed_marker(
    receipt: Mapping[str, Any],
    *,
    namespace: Path,
    marker: Mapping[str, Any],
) -> dict[str, Any]:
    consumed_path = namespace / CONSUMED_NAME
    raw, descriptor, payload = _read_file(
        consumed_path,
        "consumed marker",
        max_bytes=64 * 1024,
        parse_json=True,
    )
    _validate_written_descriptor(descriptor, "consumed marker", expected_path=consumed_path)
    if payload is None:
        _fail("consumed marker payload is absent")
    _reject_unknown(
        payload,
        {
            "schema", "state", "receipt_sha256", "identity_sha256", "receipt_path",
            "namespace", "nonce", "namespace_marker", "external_claim", "lock",
            "consumed_at_ns", "owner", *ZERO_CREDIT,
        },
        "consumed marker",
    )
    _exact(payload, "schema", CONSUMED_SCHEMA, "consumed marker")
    _exact(payload, "state", "consumed", "consumed marker")
    _exact(payload, "receipt_sha256", receipt["receipt_sha256"], "consumed marker")
    _exact(payload, "identity_sha256", receipt["identity_sha256"], "consumed marker")
    _exact(payload, "receipt_path", receipt["receipt_path"], "consumed marker")
    _exact(payload, "namespace", str(namespace), "consumed marker")
    _exact(payload, "nonce", _mapping(receipt["identity"], "identity")["nonce"], "consumed marker")
    consumed_marker = _mapping(payload.get("namespace_marker"), "consumed marker.namespace_marker")
    for key in ("dev", "ino"):
        _exact(consumed_marker, key, marker[key], "consumed marker.namespace_marker")
    consumed_claim = dict(_mapping(payload.get("external_claim"), "consumed marker.external_claim"))
    _reject_unknown(
        consumed_claim,
        {"path", "authority_id", "document_sha256"},
        "consumed marker.external_claim",
    )
    _exact(
        consumed_claim,
        "path",
        _mapping(receipt["consumption"], "consumption")["external_claim_path"],
        "consumed marker.external_claim",
    )
    authority = _mapping(_mapping(receipt["identity"], "identity")["external_authority"], "identity.external_authority")
    _exact(consumed_claim, "authority_id", authority["authority_id"], "consumed marker.external_claim")
    _exact(consumed_claim, "document_sha256", authority["document_sha256"], "consumed marker.external_claim")
    _validate_written_descriptor(
        _mapping(payload.get("lock"), "consumed marker.lock"),
        "consumed marker.lock",
        expected_path=namespace / CONSUMPTION_LOCK_NAME,
    )
    _int(payload.get("consumed_at_ns"), "consumed marker.consumed_at_ns", 1)
    owner = dict(_mapping(payload.get("owner"), "consumed marker.owner"))
    _reject_unknown(owner, {"uid", "gid", "host"}, "consumed marker.owner")
    _exact(owner, "uid", os.getuid(), "consumed marker.owner")
    _exact(owner, "gid", os.getgid(), "consumed marker.owner")
    _exact(owner, "host", CURRENT_HOST, "consumed marker.owner")
    for key, expected in ZERO_CREDIT.items():
        _exact(payload, key, expected, "consumed marker")
    return descriptor


def _validate_external_claim(
    receipt: Mapping[str, Any],
    *,
    path: Path | str,
) -> dict[str, Any]:
    """Validate the durable scheduler-ledger claim for this receipt."""

    claim_path = _external_scheduler_path(path, "external scheduler consume claim")
    raw, descriptor, payload = _read_file(
        claim_path,
        "external scheduler consume claim",
        max_bytes=64 * 1024,
        parse_json=True,
    )
    del raw
    _validate_written_descriptor(
        descriptor,
        "external scheduler consume claim",
        expected_path=claim_path,
    )
    if payload is None:
        _fail("external scheduler consume claim payload is absent")
    _reject_unknown(
        payload,
        {
            "schema", "state", "authority_id", "authority_document_sha256",
            "receipt_sha256", "identity_sha256", "receipt_path", "namespace",
            "nonce", "namespace_descriptor", "claim_path", "claimed_at_ns",
            "owner", *ZERO_CREDIT,
        },
        "external scheduler consume claim",
    )
    identity = _mapping(receipt["identity"], "identity")
    authority = _mapping(identity["external_authority"], "identity.external_authority")
    namespace = _absolute(identity["namespace"], "identity.namespace")
    _exact(payload, "schema", EXTERNAL_CLAIM_SCHEMA, "external scheduler consume claim")
    _exact(payload, "state", "consumed", "external scheduler consume claim")
    _exact(payload, "authority_id", authority["authority_id"], "external scheduler consume claim")
    _exact(
        payload,
        "authority_document_sha256",
        authority["document_sha256"],
        "external scheduler consume claim",
    )
    _exact(payload, "receipt_sha256", receipt["receipt_sha256"], "external scheduler consume claim")
    _exact(payload, "identity_sha256", receipt["identity_sha256"], "external scheduler consume claim")
    _exact(payload, "receipt_path", receipt["receipt_path"], "external scheduler consume claim")
    _exact(payload, "namespace", str(namespace), "external scheduler consume claim")
    _exact(payload, "nonce", identity["nonce"], "external scheduler consume claim")
    _exact(payload, "claim_path", str(claim_path), "external scheduler consume claim")
    claim_namespace = _authority_namespace_claim(payload.get("namespace_descriptor"))
    if canonical_json(claim_namespace) != canonical_json(identity["namespace_descriptor"]):
        _fail("external scheduler consume claim namespace binding drifted")
    _int(payload.get("claimed_at_ns"), "external scheduler consume claim.claimed_at_ns", 1)
    owner = _authority_owner(payload.get("owner"), "external scheduler consume claim.owner")
    _exact(owner, "uid", os.getuid(), "external scheduler consume claim.owner")
    _exact(owner, "gid", os.getgid(), "external scheduler consume claim.owner")
    _exact(owner, "host", CURRENT_HOST, "external scheduler consume claim.owner")
    for key, expected in ZERO_CREDIT.items():
        _exact(payload, key, expected, "external scheduler consume claim")
    return descriptor


def validate_receipt(
    receipt: Mapping[str, Any],
    *,
    check_files: bool = True,
    allow_consumed: bool = False,
) -> list[str]:
    """Return strict validation errors; never grants formal credit."""

    errors: list[str] = []
    try:
        _walk_json(receipt, "receipt")
        allowed = set(ZERO_CREDIT) | {
            "schema", "status", "receipt_version", "report_id", "identity", "identity_sha256",
            "namespace_marker", "receipt_path", "consumption", "diagnostic_execute_only",
            "authority", "receipt_sha256", "receipt_file",
        }
        _reject_unknown(receipt, allowed, "receipt")
        _exact(receipt, "schema", SCHEMA, "receipt")
        _exact(receipt, "status", "issued", "receipt")
        _exact(receipt, "receipt_version", 1, "receipt")
        _exact(receipt, "report_id", REPORT_ID, "receipt")
        _exact(receipt, "diagnostic_execute_only", True, "receipt")
        for key, expected in ZERO_CREDIT.items():
            _exact(receipt, key, expected, "receipt")
        _validate_authority(receipt)
        identity = _mapping(receipt.get("identity"), "identity")
        _validate_identity_shape(identity)
        if check_files:
            _validate_external_authority(
                _mapping(identity["external_authority"], "identity.external_authority")["path"],
                nonce=identity["nonce"],
                namespace_descriptor=identity["namespace_descriptor"],
                plan_sha256=identity["plan_sha256"],
                resource_snapshot=identity["resource_snapshot"],
                expected_meta=identity["external_authority"],
            )
        identity_digest = _sha(receipt.get("identity_sha256"), "receipt.identity_sha256")
        if identity_digest != canonical_digest(identity):
            _fail("receipt.identity_sha256 does not bind identity")
        consumption = _mapping(receipt.get("consumption"), "consumption")
        _exact(consumption, "one_shot", True, "consumption")
        _exact(consumption, "state", "issued", "consumption")
        _exact(consumption, "consumed", False, "consumption")
        _reject_unknown(
            consumption,
            {
                "one_shot", "state", "consumed", "state_file", "lock_path",
                "consumed_marker", "external_claim_path",
            },
            "consumption",
        )
        namespace = _absolute(identity["namespace"], "identity.namespace")
        _exact(consumption, "lock_path", str(namespace / CONSUMPTION_LOCK_NAME), "consumption")
        authority_meta = _mapping(identity["external_authority"], "identity.external_authority")
        _exact(
            consumption,
            "external_claim_path",
            authority_meta["consume_path"],
            "consumption",
        )
        consumed_marker = _absolute(consumption.get("consumed_marker"), "consumption.consumed_marker")
        if consumed_marker != namespace / CONSUMED_NAME:
            _fail("consumed marker escapes namespace")
        marker_descriptor = _validate_marker(receipt) if check_files else None
        if check_files and marker_descriptor is not None:
            _validate_state_file(receipt, namespace=namespace, marker=receipt["namespace_marker"])
        receipt_digest = _sha(receipt.get("receipt_sha256"), "receipt.receipt_sha256")
        core = {key: value for key, value in receipt.items() if key not in {"receipt_sha256", "receipt_file"}}
        if receipt_digest != canonical_digest(core):
            _fail("receipt.receipt_sha256 does not bind receipt bytes")
        if check_files:
            receipt_path = _absolute(receipt.get("receipt_path"), "receipt_path")
            if receipt_path != namespace / RECEIPT_NAME:
                _fail("receipt_path is not the bound namespace receipt")
            _raw, descriptor, file_payload = _read_file(receipt_path, "admission receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
            expected_file_payload = {key: value for key, value in receipt.items() if key != "receipt_file"}
            if file_payload != expected_file_payload:
                _fail("admission receipt file payload drifted")
            _validate_written_descriptor(descriptor, "admission receipt", expected_path=receipt_path)
            comparable_descriptor = {
                key: value for key, value in descriptor.items() if key != "content_opened"
            }
            if "receipt_file" in receipt and receipt["receipt_file"] != comparable_descriptor:
                _fail("admission receipt file descriptor drifted")
            if marker_descriptor is None:
                _fail("namespace marker was not checked")
            external_claim_path = _external_scheduler_path(
                consumption["external_claim_path"],
                "external scheduler consume claim",
            )
            external_claim_exists = os.path.lexists(external_claim_path)
            if external_claim_exists:
                _validate_external_claim(receipt, path=external_claim_path)
                if not allow_consumed:
                    _fail("external scheduler authority has already been consumed")
            lock_path = namespace / CONSUMPTION_LOCK_NAME
            lock_exists = os.path.lexists(lock_path)
            consumed_exists = os.path.lexists(consumed_marker)
            if lock_exists:
                lock_descriptor = _validate_lock_file(
                    receipt,
                    namespace=namespace,
                    marker=receipt["namespace_marker"],
                )
            else:
                lock_descriptor = None
            if consumed_exists:
                if lock_descriptor is None:
                    _fail("consumed marker exists without its owner lock")
                _validate_consumed_marker(
                    receipt,
                    namespace=namespace,
                    marker=receipt["namespace_marker"],
                )
            if (lock_exists or consumed_exists) and not allow_consumed:
                _fail("single-use admission has already been consumed or locked")
    except (AdmissionError, TypeError, AttributeError, KeyError, OSError) as error:
        errors.append(str(error))
    return errors


def load_receipt(path: Path | str, *, allow_consumed: bool = False) -> dict[str, Any]:
    receipt_path = _absolute(path, "admission receipt")
    _raw, descriptor, payload = _read_file(receipt_path, "admission receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    del descriptor
    if payload is None:
        _fail("admission receipt is not a JSON object")
    if str(payload.get("receipt_path")) != str(receipt_path):
        _fail("admission receipt path is not bound to the loaded path")
    errors = validate_receipt(payload, check_files=True, allow_consumed=allow_consumed)
    if errors:
        _fail("; ".join(errors))
    return payload


def _capability_seal(receipt: Mapping[str, Any], consumed_descriptor: Mapping[str, Any]) -> str:
    return canonical_digest({
        "receipt_sha256": receipt["receipt_sha256"],
        "receipt_path": receipt["receipt_path"],
        "consumed_marker": consumed_descriptor,
        "diagnostic_only": True,
        "credit": 0,
    })


def consume_receipt(path: Path | str) -> AdmissionCapability:
    """Atomically consume the external reservation and local receipt once."""

    receipt_path = _absolute(path, "admission receipt")
    receipt = load_receipt(receipt_path, allow_consumed=False)
    identity = _mapping(receipt["identity"], "identity")
    namespace = _absolute(identity["namespace"], "identity.namespace")
    marker = _mapping(receipt["namespace_marker"], "namespace_marker")
    namespace_descriptor = _mapping(identity["namespace_descriptor"], "identity.namespace_descriptor")
    authority = _mapping(identity["external_authority"], "identity.external_authority")
    _validate_external_authority(
        authority["path"],
        nonce=identity["nonce"],
        namespace_descriptor=namespace_descriptor,
        plan_sha256=identity["plan_sha256"],
        resource_snapshot=identity["resource_snapshot"],
        expected_meta=authority,
    )
    external_claim_path = _external_scheduler_path(
        authority["consume_path"], "external scheduler consume claim"
    )
    external_claim_raw = (canonical_json({
        "schema": EXTERNAL_CLAIM_SCHEMA,
        "state": "consumed",
        "authority_id": authority["authority_id"],
        "authority_document_sha256": authority["document_sha256"],
        "receipt_sha256": receipt["receipt_sha256"],
        "identity_sha256": receipt["identity_sha256"],
        "receipt_path": str(receipt_path),
        "namespace": str(namespace),
        "nonce": identity["nonce"],
        "namespace_descriptor": dict(namespace_descriptor),
        "claim_path": str(external_claim_path),
        "claimed_at_ns": time.time_ns(),
        "owner": {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "host": CURRENT_HOST,
        },
        **ZERO_CREDIT,
    }) + "\n").encode()
    try:
        _write_exclusive(external_claim_path, external_claim_raw, mode=0o600)
    except AdmissionError as error:
        if "refusing to overwrite" in str(error) or "already exists" in str(error):
            _fail("external scheduler authority has already been consumed")
        raise
    consumed_path = namespace / CONSUMED_NAME
    lock_path = namespace / CONSUMPTION_LOCK_NAME
    lock_raw = (canonical_json({
        "schema": f"{SCHEMA}.lock",
        "state": "locked",
        "identity_sha256": receipt["identity_sha256"],
        "namespace": str(namespace),
        "nonce": identity["nonce"],
        "namespace_marker": {
            "dev": marker["dev"],
            "ino": marker["ino"],
        },
        "external_claim": {
            "path": str(external_claim_path),
            "authority_id": authority["authority_id"],
            "document_sha256": authority["document_sha256"],
        },
        "owner": {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "host": CURRENT_HOST,
        },
        **ZERO_CREDIT,
    }) + "\n").encode()
    try:
        lock_descriptor = _write_exclusive(lock_path, lock_raw, mode=0o600)
    except AdmissionError as error:
        if "refusing to overwrite" in str(error) or "already exists" in str(error):
            _fail("single-use admission has already been consumed or locked")
        raise
    receipt = load_receipt(receipt_path, allow_consumed=True)
    raw = (canonical_json({
        "schema": CONSUMED_SCHEMA,
        "state": "consumed",
        "receipt_sha256": receipt["receipt_sha256"],
        "identity_sha256": receipt["identity_sha256"],
        "receipt_path": str(receipt_path),
        "namespace": str(namespace),
        "nonce": identity["nonce"],
        "namespace_marker": {
            "dev": marker["dev"],
            "ino": marker["ino"],
        },
        "external_claim": {
            "path": str(external_claim_path),
            "authority_id": authority["authority_id"],
            "document_sha256": authority["document_sha256"],
        },
        "lock": lock_descriptor,
        "consumed_at_ns": time.time_ns(),
        "owner": {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "host": CURRENT_HOST,
        },
        "diagnostic_only": True,
        **ZERO_CREDIT,
    }) + "\n").encode()
    descriptor = _write_exclusive(consumed_path, raw, mode=0o600)
    if consumed_path.parent != namespace:
        _fail("consumed marker escaped namespace")
    seal = _capability_seal(receipt, descriptor)
    return AdmissionCapability(
        receipt=receipt,
        receipt_path=receipt_path,
        consumed_marker=consumed_path,
        lock_path=lock_path,
        seal=seal,
        external_claim_path=external_claim_path,
    )


def revalidate_receipt(
    receipt: Mapping[str, Any],
    *,
    resource_admission: Mapping[str, Any] | None = None,
    check_files: bool = True,
) -> dict[str, Any]:
    """Re-read every bound source and require exact identity equality."""

    errors = validate_receipt(receipt, check_files=check_files, allow_consumed=True)
    if errors:
        _fail("receipt validation failed: " + "; ".join(errors))
    identity = _mapping(receipt["identity"], "identity")
    root = _absolute(identity["root"], "identity.root")
    manifest = _absolute(_mapping(identity["manifest"], "identity.manifest")["path"], "manifest")
    training = _absolute(_mapping(identity["training_receipt"], "identity.training_receipt")["path"], "training receipt")
    checkpoint = _absolute(_mapping(identity["checkpoint"], "identity.checkpoint")["path"], "checkpoint")
    for path, name in ((manifest, "manifest"), (training, "training receipt"), (checkpoint, "checkpoint")):
        if not _under(path, root) and not _under(path, Path("/tmp")):
            _fail(f"{name} escapes bounded roots")
    _, manifest_descriptor, manifest_payload = _read_file(manifest, "current manifest", max_bytes=MAX_JSON_BYTES, parse_json=True)
    _, training_descriptor, training_payload = _read_file(training, "training receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    checkpoint_descriptor = _checkpoint_descriptor(checkpoint)
    if manifest_payload is None or training_payload is None:
        _fail("bound JSON payload is absent")
    expected_manifest = _mapping(identity["manifest"], "identity.manifest")
    expected_training = _mapping(identity["training_receipt"], "identity.training_receipt")
    expected_checkpoint = _mapping(identity["checkpoint"], "identity.checkpoint")
    if manifest_descriptor != expected_manifest["file"]:
        _fail("current manifest file identity drifted")
    if hashlib.sha256(canonical_json(manifest_payload).encode()).hexdigest() != expected_manifest["canonical_sha256"]:
        _fail("current manifest canonical SHA drifted")
    if training_descriptor != expected_training["file"]:
        _fail("training receipt file identity drifted")
    if checkpoint_descriptor != expected_checkpoint["file"] or checkpoint_descriptor["sha256"] != expected_checkpoint["sha256"]:
        _fail("checkpoint identity drifted")
    executable = _mapping(identity["executable"], "identity.executable")
    current_executable = _executable_descriptor(executable["path"])
    if current_executable != executable["file"]:
        _fail("Python executable identity drifted")
    sources = _mapping(identity["source_sha256"], "identity.source_sha256")
    for key, relative in SOURCE_RELATIVE_PATHS.items():
        current = _source_descriptor(root, relative, key)
        if current != sources[key]:
            _fail(f"{key} source identity drifted")
    if resource_admission is None:
        _fail("scheduler-owned GPU UUID/PCI snapshot is required; implicit probing is disabled")
    current_resource = _validate_resource(resource_admission)
    if canonical_json(current_resource) != canonical_json(identity["resource_snapshot"]):
        _fail("GPU2 resource snapshot drifted from the receipt")
    command = _mapping(identity["command"], "identity.command")
    argv = command["argv"]
    if command["sha256"] != _command_digest(argv, command["cwd"], command["env_overrides"]):
        _fail("exact command digest drifted")
    return {"status": "revalidated", "resource_snapshot": current_resource, "identity_sha256": receipt["identity_sha256"], "receipt_sha256": receipt["receipt_sha256"], **ZERO_CREDIT}


def build_report(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipt: Path | str = DEFAULT_TRAINING,
    checkpoint: Path | str | None = None,
    nonce: str | None = None,
    output_root: Path | str = "/tmp",
    resource_admission: Mapping[str, Any] | None = None,
    external_authority: Path | str | None = None,
    scheduler_authority: Path | str | None = None,
) -> dict[str, Any]:
    try:
        receipt = mint_admission(
            root,
            manifest=manifest,
            training_receipt=training_receipt,
            checkpoint=checkpoint,
            nonce=nonce,
            output_root=output_root,
            resource_admission=resource_admission,
            external_authority=external_authority,
            scheduler_authority=scheduler_authority,
        )
        identity = dict(receipt["identity"])
        report = {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "admission_granted": False,
            "receipt_bound_capability_issued": False,
            "diagnostic_execute_only": True,
            "diagnostic_execute_allowed": False,
            "execution_capability_admitted": False,
            "launch_allowed": False,
            "source_bound": True,
            "receipt_path": receipt["receipt_path"],
            "receipt_sha256": receipt["receipt_sha256"],
            "namespace": identity["namespace"],
            "namespace_nonce": identity["nonce"],
            "namespace_marker": receipt["namespace_marker"],
            "resource_snapshot": identity["resource_snapshot"],
            "identity": identity,
            "single_use": True,
            "receipt_mode": 0o600,
            "namespace_mode": 0o700,
            "popen_attempted": False,
            "processes_started": 0,
            "formal_state_touched": False,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
            "blocked_reasons": [
                "terminal Popen/wait and artifact proof are not admitted",
                "production HDF5 link inventory and validator proof are not admitted",
                "formal/credit promotion requires an external Core gate and ledger",
            ],
            **ZERO_CREDIT,
        }
        return report
    except (AdmissionError, launcher.ContractError, OSError, ValueError) as error:
        return {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "admission_granted": False,
            "receipt_bound_capability_issued": False,
            "diagnostic_execute_only": True,
            "diagnostic_execute_allowed": False,
            "execution_capability_admitted": False,
            "launch_allowed": False,
            "source_bound": False,
            "popen_attempted": False,
            "processes_started": 0,
            "formal_state_touched": False,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
            "blocked_reasons": [str(error)],
            **ZERO_CREDIT,
        }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        allowed = set(ZERO_CREDIT) | {
            "schema", "report_id", "status", "admission_granted", "receipt_bound_capability_issued",
            "diagnostic_execute_only", "diagnostic_execute_allowed", "execution_capability_admitted",
            "launch_allowed", "source_bound", "receipt_path",
            "receipt_sha256", "namespace", "namespace_nonce", "namespace_marker", "resource_snapshot",
            "identity", "single_use", "receipt_mode", "namespace_mode", "popen_attempted",
            "processes_started", "formal_state_touched", "registry_writes", "ledger_writes",
            "denominator_writes", "gate_writes", "completion_writes", "plan_writes", "blocked_reasons",
        }
        _reject_unknown(report, allowed, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        status = report.get("status")
        if status not in {"receipt_bound_admission_ready", "blocked_fail_closed"}:
            _fail("report.status is invalid")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        for key in ("diagnostic_execute_only", "launch_allowed", "formal_state_touched"):
            _exact(report, key, True if key == "diagnostic_execute_only" else False, "report")
        _exact(report, "diagnostic_execute_allowed", False, "report")
        _exact(report, "execution_capability_admitted", False, "report")
        _exact(report, "popen_attempted", False, "report")
        _exact(report, "processes_started", 0, "report")
        for key in ("registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"):
            _exact(report, key, 0, "report")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a string list")
        if status == "receipt_bound_admission_ready":
            _exact(report, "admission_granted", True, "report")
            _exact(report, "receipt_bound_capability_issued", True, "report")
            _exact(report, "diagnostic_execute_allowed", False, "report")
            _exact(report, "source_bound", True, "report")
            _exact(report, "single_use", True, "report")
            _exact(report, "receipt_mode", 0o600, "report")
            _exact(report, "namespace_mode", 0o700, "report")
            _sha(report.get("receipt_sha256"), "report.receipt_sha256")
            _validate_nonce(report.get("namespace_nonce"))
            _validate_identity_shape(_mapping(report.get("identity"), "report.identity"))
        elif status == "blocked_fail_closed":
            _exact(report, "admission_granted", False, "report")
            _exact(report, "receipt_bound_capability_issued", False, "report")
    except (AdmissionError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join([
        "# F3 graph_raw seed17 diagnostic admission",
        "",
        f"- status: `{report.get('status')}`",
        f"- admission granted: `{report.get('admission_granted')}`",
        f"- diagnostic execute only: `{report.get('diagnostic_execute_only')}`",
        f"- namespace: `{report.get('namespace')}`",
        f"- receipt: `{report.get('receipt_path')}`",
        "- identity: graph_raw / hidden16 / seed17 / test / 835 transitions / 836 frames",
        "- GPU: physical GPU2 exposed as logical cuda:0; exact resource snapshot bound",
        "- source pins: manifest, training receipt, checkpoint, core_learning, validators",
        "- one-shot mode: external scheduler-signed reservation and independent ledger claim are required; execution capability not admitted",
        "- subprocess/Popen: not attempted; formal/registry/ledger/gate/completion/PLAN: untouched",
        "- credit: `0`",
        "",
        "## Blockers",
        "",
        *[f"- {item}" for item in report.get("blocked_reasons", [])],
        "",
    ])


def _write_report(path: Path, payload: Mapping[str, Any], text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_exclusive(path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), mode=0o640)
    _write_exclusive(path.with_suffix(".zh-CN.md"), text.encode(), mode=0o640)


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
            _raw, _descriptor, payload = _read_file(args.verify_report, "report", max_bytes=MAX_JSON_BYTES, parse_json=True)
            if payload is None:
                _fail("report is not a JSON object")
            errors = validate_report(payload)
            if errors:
                print(canonical_json({"valid": False, "errors": errors}))
                return 1
            print(canonical_json({"valid": True, "schema": REPORT_SCHEMA}))
            return 0
        report = build_report(root=args.root, manifest=args.manifest, training_receipt=args.training_receipt, checkpoint=args.checkpoint, nonce=args.nonce, output_root=args.output_root)
        _write_report(args.report_output, report, render_markdown(report))
        print(canonical_json(report))
        return 0 if report["status"] == "receipt_bound_admission_ready" else 2
    except (AdmissionError, launcher.ContractError, OSError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
