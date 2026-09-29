#!/usr/bin/env python3
"""Receipt-bound, diagnostic-only admission for residual/hidden16 seed29.

This is a narrow admission boundary around the existing current-manifest
residual training and full835 rollout contracts.  It binds the source bytes,
manifest/training/checkpoint identities, command/environment, scheduler-owned
GPU identity, and one exclusive namespace.  A receipt can be consumed once,
but the returned capability is deliberately non-authorizing: this module has
no subprocess path and cannot mint a terminal receipt.

The implementation is intentionally fail-closed.  It does not infer a
training receipt, probe an implicit GPU authority, reopen a path after a
stable descriptor read, or treat a declaration as a process/HDF5 proof.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import sys
import tempfile
from typing import Any

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - the lab venv supplies cryptography.
    Ed25519PublicKey = None  # type: ignore[assignment,misc]

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher
try:
    from scripts import f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1 as identity
except (ImportError, ValueError):
    identity = None  # type: ignore[assignment]


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 29
GPU_INDEX = 5
MODEL = launcher.MODEL
HIDDEN = launcher.HIDDEN
UPDATES = launcher.UPDATES
CASE_ID = launcher.CASE_ID
SPLIT = launcher.SPLIT
TRANSITIONS = launcher.TRANSITIONS
FRAMES = launcher.FRAMES
RUN_ID = (
    identity._expected_run_id(SEED)
    if identity is not None
    else f"f3-graph_residual500-hidden16-currentmanifest-seed{SEED}-20260929-v3"
)
MANIFEST_SCHEMA = launcher.MANIFEST_SCHEMA
TRAINING_SCHEMA = launcher.TRAINING_SCHEMA
CHECKPOINT_SCHEMA = launcher.CHECKPOINT_SCHEMA

SCHEMA = "core.f3.graph_residual.hidden16.seed29.diagnostic_admission.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
CONSUMED_SCHEMA = f"{SCHEMA}.consumed"
REPORT_ID = "f3-graph-residual-hidden16-seed29-diagnostic-admission-v1"
DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_TRAINING = Path(
    f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{SEED}-20260929-v3-training.json"
)
DEFAULT_CHECKPOINT = Path(
    f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{SEED}-20260929-v3-checkpoint.pt"
)
DEFAULT_REPORT = LAB_ROOT / "reports" / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED29-DIAGNOSTIC-ADMISSION-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
GPU_UUID_RE = re.compile(r"^GPU-[0-9A-Fa-f-]{8,}$")
PCI_BUS_RE = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]$")
CURRENT_HOST = socket.gethostname()
LOGICAL_GPU_INDEX = 0
CUDA_DEVICE_ORDER = "PCI_BUS_ID"

NAMESPACE_MARKER = ".diagnostic-admission-marker.json"
RECEIPT_NAME = ".diagnostic-admission-receipt.json"
CONSUMPTION_LOCK = ".diagnostic-admission-consumption.lock"
CONSUMED_MARKER = ".diagnostic-admission-consumed"
STATE_NAME = ".diagnostic-admission-state.json"

AUTHORITY_SCHEMA = f"{SCHEMA}.non_authorizing_boundary"
EXTERNAL_AUTHORITY_SCHEMA = f"{SCHEMA}.external_scheduler_authority.v1"
EXTERNAL_CLAIM_SCHEMA = f"{SCHEMA}.external_scheduler_claim.v1"
EXTERNAL_AUTHORITY_DOMAIN = b"CORE-F3-GRAPH-RESIDUAL-SEED29-EXTERNAL-AUTHORITY-V1\0"
TRUSTED_SCHEDULER_PUBLIC_KEY_PATH = Path("/etc/dual-sph/scheduler-ed25519-public.key")
EXTERNAL_SCHEDULER_ROOT = Path("/var/lib/dual-sph/f3-seed29-scheduler")

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


if identity is None:
    class _IdentityFallback:
        """Local metadata fallback when the optional shared HDF5 ABI is unavailable.

        It preserves the residual training/resource contract but deliberately
        does not claim that HDF5 terminal validation succeeded.
        """

        IdentityError = ValueError
        MIN_GPU_FREE_MIB = 8 * 1024
        MIN_CPU_COUNT = 4
        MAX_LOAD_PER_CPU = 2.0
        MIN_DISK_FREE_BYTES = 2 * 1024**3

        @staticmethod
        def _expected_run_id(seed: int) -> str:
            return f"f3-graph_residual500-hidden16-currentmanifest-seed{seed}-20260929-v3"

        @staticmethod
        def _validate_current_training_receipt(
            payload: Mapping[str, Any],
            source: Mapping[str, Any],
            *,
            receipt_path: Path,
            checkpoint_path: Path,
            seed: int,
            run_id: str,
            manifest_sha256: str,
        ) -> dict[str, Any]:
            return launcher._validate_training_receipt(
                payload,
                source,
                root=LAB_ROOT,
                seed=seed,
                run_id=run_id,
                manifest_sha256=manifest_sha256,
                checkpoint_path=checkpoint_path,
            )

        @classmethod
        def probe_resource_admission(
            cls,
            gpu_index: int,
            *,
            gpu_rows: Mapping[int, Mapping[str, Any]] | None = None,
            cpu_count: int | None = None,
            load_1m: float | None = None,
            tmp_free_bytes: int | None = None,
            root_free_bytes: int | None = None,
            probe_errors: Sequence[str] = (),
        ) -> dict[str, Any]:
            reasons = [str(item) for item in probe_errors]
            row = None if gpu_rows is None else gpu_rows.get(gpu_index)
            if row is None:
                gpu = {"total_mib": 0, "used_mib": 0, "free_mib": 0}
                reasons.append(f"GPU {gpu_index} is absent from the bounded VRAM probe")
            else:
                gpu = {
                    "total_mib": int(row.get("total_mib", 0)),
                    "used_mib": int(row.get("used_mib", 0)),
                    "free_mib": int(row.get("free_mib", 0)),
                }
                if gpu["used_mib"] + gpu["free_mib"] > gpu["total_mib"]:
                    raise ValueError("GPU used/free memory exceeds total memory")
            if gpu["free_mib"] < cls.MIN_GPU_FREE_MIB:
                reasons.append(f"GPU {gpu_index} free VRAM is below {cls.MIN_GPU_FREE_MIB} MiB")
            cpu_count = os.cpu_count() or 0 if cpu_count is None else cpu_count
            load_1m = float(os.getloadavg()[0]) if load_1m is None else load_1m
            if tmp_free_bytes is None:
                tmp_free_bytes = int(shutil.disk_usage("/tmp").free)
            if root_free_bytes is None:
                root_free_bytes = int(shutil.disk_usage(LAB_ROOT).free)
            if cpu_count < cls.MIN_CPU_COUNT:
                reasons.append(f"CPU count {cpu_count} is below {cls.MIN_CPU_COUNT}")
            if not math.isfinite(load_1m) or load_1m < 0:
                reasons.append("CPU load average is not finite and non-negative")
                load_per_cpu = float("inf")
            else:
                load_per_cpu = load_1m / max(cpu_count, 1)
                if load_per_cpu > cls.MAX_LOAD_PER_CPU:
                    reasons.append(f"CPU load per logical core exceeds {cls.MAX_LOAD_PER_CPU}")
            if tmp_free_bytes < cls.MIN_DISK_FREE_BYTES:
                reasons.append("/tmp free space is below the bounded I/O threshold")
            if root_free_bytes < cls.MIN_DISK_FREE_BYTES:
                reasons.append("root free space is below the bounded I/O threshold")
            return {
                "schema": "core.f3.graph_residual.hidden16.current_manifest.resource_admission.v1",
                "gpu_index": gpu_index,
                "gpu": gpu,
                "cpu": {"logical_count": cpu_count, "load_1m": load_1m, "load_per_logical_core": load_per_cpu},
                "io": {"tmp_free_bytes": tmp_free_bytes, "root_free_bytes": root_free_bytes, "minimum_free_bytes": cls.MIN_DISK_FREE_BYTES},
                "status": "admitted" if not reasons else "blocked",
                "admitted": not reasons,
                "blocked_reasons": reasons,
                "content_opened": False,
            }

    identity = _IdentityFallback()

SOURCE_RELATIVE_PATHS = {
    "rollout_launcher": Path("scripts/f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1.py"),
    "training_evidence": Path("scripts/f3_graph_residual_hidden16_current_manifest_training_evidence_v1.py"),
    "terminal_identity": Path("scripts/f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1.py"),
    "terminal_bridge": Path("scripts/f3_graph_residual_hidden16_current_manifest_terminal_execution_bridge_v1.py"),
    "terminal_runtime": Path("scripts/f3_graph_residual_hidden16_terminal_runtime_verifier_v1.py"),
    "core_learning": Path("scripts/core_learning.py"),
    "hdf5_validator": Path("scripts/f3_full_rollout_receipt_hdf5_validator_v1.py"),
}


class AdmissionError(ValueError):
    """Malformed, drifting, reused, or non-authorizing admission input."""


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
    candidate = Path(raw)
    if not candidate.is_absolute() or any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} must be absolute and lexical-alias free")
    if Path(os.path.normpath(raw)) != candidate:
        _fail(f"{name} uses a lexical path alias")
    return candidate


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
    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode), int(info.st_nlink),
        int(info.st_size), int(info.st_mtime_ns), int(info.st_ctime_ns),
    )


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


def _read_bound(path: Path | str, name: str, *, max_bytes: int, parse_json: bool = False) -> tuple[bytes, dict[str, Any], dict[str, Any] | None]:
    candidate = _absolute(path, f"{name}.path")
    if max_bytes < 1:
        _fail(f"{name} max_bytes must be positive")
    parent_fd, parent_identity = _open_parent(candidate.parent, name)
    leaf_fd: int | None = None
    try:
        before = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{name} must be a regular single-link file")
        if before.st_size < 1 or before.st_size > max_bytes:
            _fail(f"{name} is outside the bounded size")
        leaf_fd = os.open(candidate.name, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        opened = os.fstat(leaf_fd)
        if _signature(opened) != _signature(before):
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
        if total != before.st_size or _signature(after_fd) != _signature(before) or _signature(after_path) != _signature(before):
            _fail(f"{name} changed during stable descriptor read")
        parent_after = os.fstat(parent_fd)
        if (int(parent_after.st_dev), int(parent_after.st_ino)) != parent_identity:
            _fail(f"{name} parent changed during stable descriptor read")
        raw = b"".join(chunks)
        descriptor = {
            "path": str(candidate),
            "dev": int(before.st_dev),
            "ino": int(before.st_ino),
            "bytes": int(before.st_size),
            "mode": int(stat.S_IMODE(before.st_mode)),
            "uid": int(before.st_uid),
            "gid": int(before.st_gid),
            "nlink": int(before.st_nlink),
            "mtime_ns": int(before.st_mtime_ns),
            "ctime_ns": int(before.st_ctime_ns),
            "parent_dev": parent_identity[0],
            "parent_ino": parent_identity[1],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "stable_fd": True,
            "fd_identity_stable": True,
            "path_reopened": False,
            "content_opened": True,
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


def _write_exclusive(path: Path, raw: bytes, *, mode: int = 0o600) -> dict[str, Any]:
    candidate = _absolute(path, "exclusive output")
    parent_fd, parent_identity = _open_parent(candidate.parent, "exclusive output")
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
        if (int(parent_after.st_dev), int(parent_after.st_ino)) != parent_identity:
            _fail("exclusive output parent changed")
        os.fsync(parent_fd)
        return {
            "path": str(candidate), "dev": int(info.st_dev), "ino": int(info.st_ino),
            "bytes": int(info.st_size), "mode": int(stat.S_IMODE(info.st_mode)),
            "uid": int(info.st_uid), "gid": int(info.st_gid), "nlink": int(info.st_nlink),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    except FileExistsError:
        _fail(f"refusing to overwrite existing file: {candidate}")
    except OSError as error:
        _fail(f"cannot write exclusive output: {error}")
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)


def _mkdir_exclusive(path: Path) -> dict[str, Any]:
    candidate = _absolute(path, "exclusive namespace")
    parent_fd, parent_identity = _open_parent(candidate.parent, "exclusive namespace")
    try:
        os.mkdir(candidate.name, 0o700, dir_fd=parent_fd)
        info = os.stat(candidate.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid() or info.st_gid != os.getgid() or info.st_nlink != 2:
            _fail("exclusive namespace identity drifted")
        os.fsync(parent_fd)
        return {
            "path": str(candidate), "dev": int(info.st_dev), "ino": int(info.st_ino),
            "mode": int(stat.S_IMODE(info.st_mode)), "uid": int(info.st_uid),
            "gid": int(info.st_gid), "nlink": int(info.st_nlink),
            "parent_dev": parent_identity[0], "parent_ino": parent_identity[1],
        }
    except FileExistsError:
        _fail(f"refusing to reuse existing namespace: {candidate}")
    except OSError as error:
        _fail(f"cannot create exclusive namespace: {error}")
    finally:
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
    """Bind an externally reserved owner-only namespace without creating it."""

    candidate = _absolute(path, "reserved namespace")
    _reject_symlinks(candidate, "reserved namespace")
    try:
        info = os.lstat(candidate)
        parent = os.lstat(candidate.parent)
    except OSError as error:
        _fail(f"reserved namespace is not externally present: {error}")
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        _fail("reserved namespace must be a real directory")
    if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid() or info.st_gid != os.getgid():
        _fail("reserved namespace must be owner-only and owned by the current account")
    if info.st_nlink < 2 or not stat.S_ISDIR(parent.st_mode):
        _fail("reserved namespace directory identity is not stable")
    return {
        "path": str(candidate),
        "dev": int(info.st_dev),
        "ino": int(info.st_ino),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "parent_dev": int(parent.st_dev),
        "parent_ino": int(parent.st_ino),
    }


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


def _read_trusted_scheduler_key() -> tuple[bytes, dict[str, Any]]:
    key_path = _absolute(TRUSTED_SCHEDULER_PUBLIC_KEY_PATH, "trusted scheduler public key")
    _reject_symlinks(key_path, "trusted scheduler public key")
    raw, descriptor, _ = _read_bound(key_path, "trusted scheduler public key", max_bytes=64)
    if len(raw) != 32:
        _fail("trusted scheduler public key must be exactly 32 bytes")
    if descriptor["mode"] & 0o022:
        _fail("trusted scheduler public key is group/other writable")
    return raw, descriptor


def _authority_namespace(value: Any) -> dict[str, Any]:
    claim = dict(_mapping(value, "external_authority.namespace"))
    _unknown(
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


@dataclass(frozen=True)
class ReservedPlan:
    root: Path
    seed: int
    run_id: str
    nonce: str
    manifest: Path
    manifest_binding: Mapping[str, Any]
    manifest_file: Mapping[str, Any]
    training_receipt: Path
    training_binding: Mapping[str, Any]
    training_file: Mapping[str, Any]
    checkpoint: Mapping[str, Any]
    output_namespace: Path
    outputs: Mapping[str, Path]
    command: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    command_sha256: str
    gpu_index: int


def _plan_binding(
    plan: ReservedPlan | None = None,
    *,
    root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    training: Mapping[str, Any] | None = None,
    checkpoint: Mapping[str, Any] | None = None,
    namespace: Path | None = None,
    outputs: Mapping[str, Path] | None = None,
    command: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    if plan is not None:
        manifest = {
            "path": str(plan.manifest),
            "binding": dict(plan.manifest_binding),
            "file": dict(plan.manifest_file),
        }
        training = {
            "path": str(plan.training_receipt),
            "binding": dict(plan.training_binding),
            "file": dict(plan.training_file),
        }
        checkpoint = dict(plan.checkpoint)
        namespace = plan.output_namespace
        root = plan.root
        outputs = plan.outputs
        command = plan.command
        env = plan.env
        nonce = plan.nonce
    if any(value is None for value in (root, manifest, training, checkpoint, namespace, outputs, command, env, nonce)):
        _fail("plan binding requires a complete reserved plan")
    return {
        "schema": f"{EXTERNAL_AUTHORITY_SCHEMA}.plan",
        "root": str(root),
        "seed": SEED,
        "run_id": RUN_ID,
        "nonce": nonce,
        "manifest": dict(manifest),
        "training_receipt": dict(training),
        "checkpoint": dict(checkpoint),
        "namespace": str(namespace),
        "outputs": {key: str(value) for key, value in outputs.items()},
        "command": list(command),
        "env_overrides": dict(env),
        "command_sha256": canonical_digest(
            {
                "argv": list(command),
                "cwd": str(root),
                "env_overrides": dict(env),
                "seed": SEED,
                "gpu_index": GPU_INDEX,
            }
        ),
    }


def _plan_binding_digest(binding: Mapping[str, Any]) -> str:
    return canonical_digest(_plan_binding(binding) if isinstance(binding, ReservedPlan) else binding)


def _build_reserved_plan(
    root: Path | str,
    *,
    manifest: Path | str,
    training_receipt: Path | str,
    checkpoint: Path | str | None,
    nonce: str,
    namespace: Path,
    gpu_index: int,
    python_executable: Path | str | None = None,
) -> ReservedPlan:
    """Construct plan identity around a namespace reserved by the scheduler."""

    if gpu_index != GPU_INDEX:
        _fail("reserved plan GPU index is not seed29 GPU5")
    root_path = _absolute(root, "root")
    _reject_symlinks(root_path, "root")
    if not root_path.is_dir():
        _fail("root must be an existing directory")
    selected_nonce = _validate_nonce(nonce)
    namespace_path = _absolute(namespace, "reserved namespace")
    expected_namespace = _namespace(namespace_path.parent, selected_nonce)
    if namespace_path != expected_namespace:
        _fail("reserved namespace is not the fixed residual seed29 namespace")
    manifest_path = _absolute(manifest, "manifest")
    if manifest_path != root_path / launcher.MANIFEST_RELATIVE:
        _fail("manifest path is not the fixed current canonical manifest")
    _manifest_raw, manifest_file, manifest_payload = _read_bound(
        manifest_path, "manifest", max_bytes=MAX_JSON_BYTES, parse_json=True
    )
    assert manifest_payload is not None
    try:
        manifest_binding = launcher._manifest_binding(manifest_payload, manifest_file, path=manifest_path)
    except launcher.LauncherError as error:
        _fail(str(error))
    training_path = _absolute(training_receipt, "training_receipt")
    checkpoint_path = _absolute(
        checkpoint if checkpoint is not None else DEFAULT_CHECKPOINT,
        "checkpoint",
    )
    if training_path.name != f"{RUN_ID}-training.json" or checkpoint_path.name != f"{RUN_ID}-checkpoint.pt":
        _fail("training/checkpoint filenames do not bind the residual v3 run")
    _training_raw, training_file, training_payload = _read_bound(
        training_path, "training_receipt", max_bytes=MAX_JSON_BYTES, parse_json=True
    )
    assert training_payload is not None
    try:
        training_binding = identity._validate_current_training_receipt(
            training_payload,
            training_file,
            receipt_path=training_path,
            checkpoint_path=checkpoint_path,
            seed=SEED,
            run_id=RUN_ID,
            manifest_sha256=manifest_binding["canonical_sha256"],
        )
    except (identity.IdentityError, launcher.LauncherError) as error:
        _fail(str(error))
    checkpoint_file = _file_descriptor(
        checkpoint_path, "checkpoint", max_bytes=MAX_CHECKPOINT_BYTES
    )
    if (
        checkpoint_file["sha256"] != training_binding["checkpoint"]["sha256"]
        or checkpoint_file["bytes"] != training_binding["checkpoint"]["bytes"]
    ):
        _fail("checkpoint content identity disagrees with training receipt")
    executable = _absolute(
        python_executable if python_executable is not None else root_path / ".venv" / "bin" / "python",
        "python_executable",
    )
    executable_file = _file_descriptor(executable, "Python executable", max_bytes=MAX_EXECUTABLE_BYTES)
    if not executable_file["mode"] & 0o111:
        _fail("Python executable is not executable")
    outputs = launcher._output_paths(namespace_path, root_path, SEED, selected_nonce)
    if any(os.path.lexists(path) for path in outputs.values()):
        _fail("reserved rollout output already exists")
    command = launcher._build_command(
        root=root_path,
        python=executable,
        manifest=manifest_path,
        checkpoint=checkpoint_path,
        outputs=outputs,
    )
    env = {
        "CUDA_VISIBLE_DEVICES": str(GPU_INDEX),
        "CUDA_DEVICE_ORDER": CUDA_DEVICE_ORDER,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    command_sha256 = canonical_digest(
        {"argv": list(command), "cwd": str(root_path), "env_overrides": env, "seed": SEED, "gpu_index": GPU_INDEX}
    )
    return ReservedPlan(
        root=root_path,
        seed=SEED,
        run_id=RUN_ID,
        nonce=selected_nonce,
        manifest=manifest_path,
        manifest_binding=manifest_binding,
        manifest_file=manifest_file,
        training_receipt=training_path,
        training_binding=training_binding,
        training_file=training_file,
        checkpoint={**training_binding["checkpoint"], "file": checkpoint_file},
        output_namespace=namespace_path,
        outputs=outputs,
        command=tuple(command),
        cwd=root_path,
        env=env,
        command_sha256=command_sha256,
        gpu_index=GPU_INDEX,
    )


def _validate_external_authority(
    path: Path | str,
    *,
    nonce: str,
    namespace_descriptor: Mapping[str, Any],
    plan_sha256: str,
    resource_snapshot: Mapping[str, Any],
    expected_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify a scheduler-owned signed reservation; never create one locally."""

    authority_path = _external_scheduler_path(path, "external scheduler authority")
    raw, descriptor, payload = _read_bound(
        authority_path,
        "external scheduler authority",
        max_bytes=256 * 1024,
        parse_json=True,
    )
    if payload is None:
        _fail("external scheduler authority payload is absent")
    _unknown(
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
    owner = dict(_mapping(payload.get("owner"), "external_authority.owner"))
    _unknown(owner, {"uid", "gid", "host"}, "external_authority.owner")
    _exact(owner, "uid", os.getuid(), "external_authority.owner")
    _exact(owner, "gid", os.getgid(), "external_authority.owner")
    _exact(owner, "host", CURRENT_HOST, "external_authority.owner")
    scheduler = dict(_mapping(payload.get("scheduler"), "external_authority.scheduler"))
    _unknown(scheduler, {"uid", "gid", "host", "role"}, "external_authority.scheduler")
    _int(scheduler.get("uid"), "external_authority.scheduler.uid")
    _int(scheduler.get("gid"), "external_authority.scheduler.gid")
    _string(scheduler.get("host"), "external_authority.scheduler.host")
    _exact(scheduler, "role", "external_scheduler", "external_authority.scheduler")
    if canonical_json(_authority_namespace(payload.get("namespace"))) != canonical_json(dict(namespace_descriptor)):
        _fail("external scheduler authority namespace inode binding drifted")
    _exact(payload, "nonce", _validate_nonce(nonce), "external scheduler authority")
    _exact(payload, "plan_sha256", _sha(plan_sha256, "plan_sha256"), "external scheduler authority")
    _exact(
        payload,
        "resource_snapshot_sha256",
        canonical_digest(resource_snapshot),
        "external scheduler authority",
    )
    gpu = dict(_mapping(payload.get("gpu"), "external_authority.gpu"))
    _exact(gpu, "physical_index", GPU_INDEX, "external_authority.gpu")
    if canonical_json(_gpu_identity(gpu)) != canonical_json(
        _gpu_identity(_mapping(resource_snapshot.get("gpu"), "resource_admission.gpu"))
    ):
        _fail("external scheduler authority GPU identity binding drifted")
    _exact(payload, "gpu_identity_sha256", canonical_digest(_gpu_identity(gpu)), "external_authority")
    consume_path = _external_scheduler_path(payload.get("consume_path"), "external scheduler consume path")
    namespace_path = Path(namespace_descriptor["path"])
    if consume_path == authority_path or _under(consume_path, namespace_path):
        _fail("external scheduler consume path is not independent of the namespace")
    _string(payload.get("key_id"), "external_authority.key_id")
    _exact(payload, "signature_algorithm", "ed25519", "external_authority")
    signature_text = _string(payload.get("signature_base64"), "external_authority.signature_base64")
    try:
        signature = base64.b64decode(signature_text.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as error:
        _fail(f"external scheduler authority signature is not strict base64: {error}")
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != signature_text:
        _fail("external scheduler authority signature is not canonical Ed25519")
    public_key, key_descriptor = _read_trusted_scheduler_key()
    key_id = hashlib.sha256(public_key).hexdigest()
    _exact(payload, "key_id", key_id, "external_authority")
    if Ed25519PublicKey is None:
        _fail("cryptography Ed25519 verifier is unavailable")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature,
            _authority_signing_message(_authority_unsigned(payload)),
        )
    except Exception as error:
        _fail(f"external scheduler authority signature verification failed: {error}")
    metadata = {
        "schema": EXTERNAL_AUTHORITY_SCHEMA,
        "path": str(authority_path),
        "file": dict(descriptor),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "document_sha256": canonical_digest(_authority_unsigned(payload)),
        "authority_id": authority_id,
        "key_id": key_id,
        "consume_path": str(consume_path),
        "key_file": {
            "path": str(TRUSTED_SCHEDULER_PUBLIC_KEY_PATH),
            "file": dict(key_descriptor),
            "sha256": hashlib.sha256(public_key).hexdigest(),
        },
    }
    if expected_meta is not None and canonical_json(dict(expected_meta)) != canonical_json(metadata):
        _fail("external scheduler authority descriptor drifted from the receipt")
    return metadata


def _source_descriptor(root: Path, relative: Path, name: str) -> dict[str, Any]:
    path = root / relative
    if not _under(path, root) or not _under(path.parent, root):
        _fail(f"{name} escapes the lab root")
    _raw, descriptor, _ = _read_bound(path, name, max_bytes=MAX_SOURCE_BYTES)
    return descriptor


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
    _unknown(payload, {"schema", "gpu_index", "gpu", "cpu", "io", "status", "admitted", "blocked_reasons", "content_opened", "owner"}, "resource_admission")
    _exact(payload, "schema", "core.f3.graph_residual.hidden16.current_manifest.resource_admission.v1", "resource_admission")
    _exact(payload, "gpu_index", GPU_INDEX, "resource_admission")
    _exact(payload, "status", "admitted", "resource_admission")
    _exact(payload, "admitted", True, "resource_admission")
    _exact(payload, "content_opened", False, "resource_admission")
    reasons = payload.get("blocked_reasons")
    if not isinstance(reasons, list) or reasons:
        _fail("resource_admission.blocked_reasons must be empty")
    gpu = dict(_mapping(payload.get("gpu"), "resource_admission.gpu"))
    _unknown(gpu, {"total_mib", "used_mib", "free_mib", "physical_index", "uuid", "pci_bus_id", "logical_index", "cuda_visible_devices", "cuda_device", "cuda_device_order", "identity_source", "identity_attested", "identity_sha256"}, "resource_admission.gpu")
    for key in ("total_mib", "used_mib", "free_mib"):
        _int(gpu.get(key), f"resource_admission.gpu.{key}")
    if gpu["used_mib"] + gpu["free_mib"] > gpu["total_mib"] or gpu["free_mib"] < identity.MIN_GPU_FREE_MIB:
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
        _fail("command environment is not the fixed no-inheritance allowlist")
    core = {"policy": "allowlist_only_no_ambient_inheritance", "inherit": False, "variables": expected}
    return {**core, "sha256": canonical_digest(core)}


def _descriptor_equal(observed: Mapping[str, Any], expected: Mapping[str, Any], name: str) -> None:
    for key in ("path", "dev", "ino", "bytes", "mode", "uid", "gid", "nlink", "mtime_ns", "ctime_ns", "parent_dev", "parent_ino", "sha256"):
        if observed.get(key) != expected.get(key):
            _fail(f"{name} identity drifted at {key}")


def _file_descriptor(path: Path, name: str, *, max_bytes: int) -> dict[str, Any]:
    return _read_bound(path, name, max_bytes=max_bytes)[1]


@dataclass(frozen=True)
class AdmissionCapability:
    receipt: Mapping[str, Any]
    receipt_path: Path
    lock_path: Path
    consumed_marker: Path
    seal: str
    external_claim_path: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_path": str(self.receipt_path),
            "receipt_sha256": self.receipt.get("receipt_sha256"),
            "lock_path": str(self.lock_path),
            "consumed_marker": str(self.consumed_marker),
            "external_claim_path": None if self.external_claim_path is None else str(self.external_claim_path),
            "seal": self.seal,
            "diagnostic_only": True,
            "popen_authorized": False,
            "launch_allowed": False,
            "formal_promotion_allowed": False,
            "credit": 0,
        }


def _identity_core(*, root: Path, manifest: Mapping[str, Any], training: Mapping[str, Any], checkpoint: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]], executable: Mapping[str, Any], command: Sequence[str], env: Mapping[str, str], namespace: Path, namespace_descriptor: Mapping[str, Any], nonce: str, resource_admission: Mapping[str, Any], outputs: Mapping[str, Path], plan_sha256: str, external_authority: Mapping[str, Any]) -> dict[str, Any]:
    env_snapshot = _environment(env)
    return {
        "root": str(root), "seed": SEED, "run_id": RUN_ID, "model_kind": MODEL,
        "hidden": HIDDEN, "updates": UPDATES, "case_id": CASE_ID, "split": SPLIT,
        "transitions": TRANSITIONS, "frames": FRAMES,
        "manifest": dict(manifest), "training_receipt": dict(training), "checkpoint": dict(checkpoint),
        "source_files": {key: dict(value) for key, value in sources.items()},
        "executable": dict(executable),
        "command": {"argv": list(command), "cwd": str(root), "env_overrides": dict(env), "sha256": canonical_digest({"argv": list(command), "cwd": str(root), "env_overrides": dict(env), "seed": SEED, "gpu_index": GPU_INDEX})},
        "outputs": {key: str(value) for key, value in outputs.items()},
        "plan_sha256": plan_sha256,
        "environment": env_snapshot,
        "resource_admission": dict(resource_admission),
        "gpu": dict(resource_admission["gpu"]),
        "gpu_identity_sha256": canonical_digest(_gpu_identity(resource_admission["gpu"])),
        "namespace": str(namespace), "namespace_descriptor": dict(namespace_descriptor), "nonce": nonce,
        "external_authority": dict(external_authority),
        "formal_state_touched": False,
    }


def _receipt_core(identity_core: Mapping[str, Any], *, namespace: Path, nonce: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "report_id": REPORT_ID, "status": "admission_issued",
        "receipt_path": str(namespace / RECEIPT_NAME), "namespace": str(namespace),
        "namespace_nonce": nonce, "identity": dict(identity_core),
        "identity_sha256": canonical_digest(identity_core),
        "consumption": {"one_shot": True, "lock_path": str(namespace / CONSUMPTION_LOCK), "consumed_marker": str(namespace / CONSUMED_MARKER), "consumed": False},
        "diagnostic_execute_only": True, "terminal_receipt_minting": False,
        **ZERO_CREDIT,
    }


def _marker(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": f"{SCHEMA}.namespace_marker", "namespace": receipt["namespace"],
        "namespace_nonce": receipt["namespace_nonce"], "receipt_sha256": receipt["receipt_sha256"],
        "identity_sha256": receipt["identity_sha256"], "one_shot": True, "diagnostic_only": True,
    }


def mint_admission(root: Path | str = LAB_ROOT, *, manifest: Path | str = DEFAULT_MANIFEST, training_receipt: Path | str = DEFAULT_TRAINING, checkpoint: Path | str | None = None, nonce: str | None = None, output_root: Path | str = "/tmp", resource_admission: Mapping[str, Any] | None = None, python_executable: Path | str | None = None, external_authority: Path | str | None = None, scheduler_authority: Path | str | None = None) -> dict[str, Any]:
    """Mint one source-bound, zero-credit receipt after external attestation.

    The namespace and signed authority are supplied by an external scheduler.
    This module never creates scheduler evidence, starts a process, or mints a
    terminal receipt.
    """

    root_path = _absolute(root, "root")
    _reject_symlinks(root_path, "root")
    if not root_path.is_dir():
        _fail("root must be an existing directory")
    selected_nonce = _validate_nonce(nonce if nonce is not None else secrets.token_hex(16))
    resource_snapshot = _validate_resource(resource_admission) if resource_admission is not None else _fail("scheduler-owned GPU UUID/PCI snapshot is required")
    if external_authority is not None and scheduler_authority is not None:
        _fail("provide only one external scheduler authority path")
    authority_path = external_authority if external_authority is not None else scheduler_authority
    if authority_path is None:
        _fail("external scheduler authority is required; local fields are not authority")
    manifest_path = _absolute(manifest, "manifest")
    expected_manifest = root_path / launcher.MANIFEST_RELATIVE
    if manifest_path != expected_manifest:
        _fail("manifest path is not the fixed current canonical manifest")
    manifest_raw, manifest_desc, manifest_payload = _read_bound(manifest_path, "manifest", max_bytes=MAX_JSON_BYTES, parse_json=True)
    del manifest_raw
    assert manifest_payload is not None
    try:
        manifest_binding = launcher._manifest_binding(manifest_payload, manifest_desc, path=manifest_path)
    except launcher.LauncherError as error:
        _fail(str(error))
    training_path = _absolute(training_receipt, "training_receipt")
    checkpoint_path = _absolute(checkpoint if checkpoint is not None else DEFAULT_CHECKPOINT, "checkpoint")
    if training_path.name != f"{RUN_ID}-training.json" or checkpoint_path.name != f"{RUN_ID}-checkpoint.pt":
        _fail("training/checkpoint filenames do not bind the current residual v3 run")
    training_raw, training_desc, training_payload = _read_bound(training_path, "training_receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    del training_raw
    assert training_payload is not None
    try:
        training_binding = identity._validate_current_training_receipt(training_payload, training_desc, receipt_path=training_path, checkpoint_path=checkpoint_path, seed=SEED, run_id=RUN_ID, manifest_sha256=manifest_binding["canonical_sha256"])
    except (identity.IdentityError, launcher.LauncherError) as error:
        _fail(str(error))
    checkpoint_raw, checkpoint_desc, _ = _read_bound(checkpoint_path, "checkpoint", max_bytes=MAX_CHECKPOINT_BYTES)
    del checkpoint_raw
    if checkpoint_desc["sha256"] != training_binding["checkpoint"]["sha256"] or checkpoint_desc["bytes"] != training_binding["checkpoint"]["bytes"]:
        _fail("checkpoint content identity disagrees with the training receipt")
    source_files = {key: _source_descriptor(root_path, relative, key) for key, relative in SOURCE_RELATIVE_PATHS.items()}
    python = _absolute(python_executable if python_executable is not None else root_path / ".venv" / "bin" / "python", "python_executable")
    executable = _file_descriptor(python, "Python executable", max_bytes=MAX_EXECUTABLE_BYTES)
    if not executable["mode"] & 0o111:
        _fail("Python executable is not executable")
    namespace = _namespace(output_root, selected_nonce)
    namespace_desc = _existing_namespace_descriptor(namespace)
    outputs = launcher._output_paths(namespace, root_path, SEED, selected_nonce)
    if any(os.path.lexists(path) for path in outputs.values()):
        _fail("a bound rollout output already exists; fresh namespace is required")
    command = launcher._build_command(root=root_path, python=python, manifest=manifest_path, checkpoint=checkpoint_path, outputs=outputs)
    env = {"CUDA_VISIBLE_DEVICES": str(GPU_INDEX), "CUDA_DEVICE_ORDER": CUDA_DEVICE_ORDER, "PYTHONDONTWRITEBYTECODE": "1"}
    plan_binding = _plan_binding(
        root=root_path,
        manifest={"path": str(manifest_path), "binding": manifest_binding, "file": manifest_desc},
        training={"path": str(training_path), "binding": training_binding, "file": training_desc},
        checkpoint={**training_binding["checkpoint"], "file": checkpoint_desc},
        namespace=namespace,
        outputs=outputs,
        command=command,
        env=env,
        nonce=selected_nonce,
    )
    authority_metadata = _validate_external_authority(
        authority_path,
        nonce=selected_nonce,
        namespace_descriptor=namespace_desc,
        plan_sha256=_plan_binding_digest(plan_binding),
        resource_snapshot=resource_snapshot,
    )
    identity_core = _identity_core(
        root=root_path,
        manifest={"path": str(manifest_path), "binding": manifest_binding, "file": manifest_desc},
        training={"path": str(training_path), "binding": training_binding, "file": training_desc},
        checkpoint={**training_binding["checkpoint"], "file": checkpoint_desc},
        sources=source_files,
        executable=executable,
        command=command,
        env=env,
        namespace=namespace,
        namespace_descriptor=namespace_desc,
        nonce=selected_nonce,
        resource_admission=resource_snapshot,
        outputs=outputs,
        plan_sha256=_plan_binding_digest(plan_binding),
        external_authority=authority_metadata,
    )
    receipt = _receipt_core(identity_core, namespace=namespace, nonce=selected_nonce)
    receipt["receipt_sha256"] = canonical_digest(receipt)
    receipt_raw = (canonical_json(receipt) + "\n").encode("utf-8")
    receipt_desc = _write_exclusive(namespace / RECEIPT_NAME, receipt_raw)
    marker = _marker(receipt)
    marker_desc = _write_exclusive(namespace / NAMESPACE_MARKER, (canonical_json(marker) + "\n").encode("utf-8"))
    receipt["receipt_descriptor"] = receipt_desc
    receipt["namespace_marker_descriptor"] = marker_desc
    # The descriptors are intentionally outside the digest to avoid a
    # self-referential receipt.  They are rechecked by load/consume.
    return receipt


def _identity_plan_binding(core: Mapping[str, Any]) -> dict[str, Any]:
    namespace = _absolute(core.get("namespace"), "receipt.identity.namespace")
    outputs_raw = _mapping(core.get("outputs"), "receipt.identity.outputs")
    outputs = {key: _absolute(value, f"receipt.identity.outputs.{key}") for key, value in outputs_raw.items()}
    command = _mapping(core.get("command"), "receipt.identity.command")
    return _plan_binding(
        root=_absolute(core.get("root"), "receipt.identity.root"),
        manifest=_mapping(core.get("manifest"), "receipt.identity.manifest"),
        training=_mapping(core.get("training_receipt"), "receipt.identity.training_receipt"),
        checkpoint=_mapping(core.get("checkpoint"), "receipt.identity.checkpoint"),
        namespace=namespace,
        outputs=outputs,
        command=tuple(command["argv"]),
        env=command["env_overrides"],
        nonce=_validate_nonce(core.get("nonce"), "receipt.identity.nonce"),
    )


def _validate_external_binding(receipt: Mapping[str, Any]) -> None:
    core = _mapping(receipt.get("identity"), "receipt.identity")
    _exact(core, "seed", SEED, "receipt.identity")
    _exact(core, "run_id", RUN_ID, "receipt.identity")
    _exact(core, "model_kind", MODEL, "receipt.identity")
    _exact(core, "hidden", HIDDEN, "receipt.identity")
    _exact(core, "updates", UPDATES, "receipt.identity")
    _exact(core, "transitions", TRANSITIONS, "receipt.identity")
    _exact(core, "frames", FRAMES, "receipt.identity")
    resource_snapshot = _validate_resource(_mapping(core.get("resource_admission"), "receipt.identity.resource_admission"))
    _exact(core, "gpu_identity_sha256", canonical_digest(_gpu_identity(_mapping(core.get("gpu"), "receipt.identity.gpu"))), "receipt.identity")
    if canonical_json(_gpu_identity(_mapping(core.get("gpu"), "receipt.identity.gpu"))) != canonical_json(_gpu_identity(resource_snapshot["gpu"])):
        _fail("receipt.identity.gpu drifted from the resource snapshot")
    plan_binding = _identity_plan_binding(core)
    _exact(core, "plan_sha256", _plan_binding_digest(plan_binding), "receipt.identity")
    namespace_descriptor = _mapping(core.get("namespace_descriptor"), "receipt.identity.namespace_descriptor")
    authority = _mapping(core.get("external_authority"), "receipt.identity.external_authority")
    _validate_external_authority(
        authority.get("path"),
        nonce=_validate_nonce(core.get("nonce"), "receipt.identity.nonce"),
        namespace_descriptor=namespace_descriptor,
        plan_sha256=core["plan_sha256"],
        resource_snapshot=resource_snapshot,
        expected_meta=authority,
    )


def _validate_shape(receipt: Mapping[str, Any], *, check_files: bool) -> None:
    allowed = set(ZERO_CREDIT) | {"schema", "report_id", "status", "receipt_path", "namespace", "namespace_nonce", "identity", "identity_sha256", "consumption", "diagnostic_execute_only", "terminal_receipt_minting", "receipt_sha256", "receipt_descriptor", "namespace_marker_descriptor"}
    _unknown(receipt, allowed, "receipt")
    _exact(receipt, "schema", SCHEMA, "receipt")
    _exact(receipt, "report_id", REPORT_ID, "receipt")
    _exact(receipt, "status", "admission_issued", "receipt")
    _exact(receipt, "diagnostic_execute_only", True, "receipt")
    _exact(receipt, "terminal_receipt_minting", False, "receipt")
    for key, expected in ZERO_CREDIT.items():
        _exact(receipt, key, expected, "receipt")
    nonce = _validate_nonce(receipt.get("namespace_nonce"), "receipt.namespace_nonce")
    namespace = _absolute(receipt.get("namespace"), "receipt.namespace")
    receipt_path = _absolute(receipt.get("receipt_path"), "receipt.receipt_path")
    _exact(receipt, "receipt_path", str(namespace / RECEIPT_NAME), "receipt")
    _exact(receipt, "namespace", str(namespace), "receipt")
    _unknown(_mapping(receipt.get("consumption"), "receipt.consumption"), {"one_shot", "lock_path", "consumed_marker", "consumed"}, "receipt.consumption")
    consumption = receipt["consumption"]
    _exact(consumption, "one_shot", True, "receipt.consumption")
    _exact(consumption, "lock_path", str(namespace / CONSUMPTION_LOCK), "receipt.consumption")
    _exact(consumption, "consumed_marker", str(namespace / CONSUMED_MARKER), "receipt.consumption")
    _bool(consumption.get("consumed"), "receipt.consumption.consumed")
    identity_core = _mapping(receipt.get("identity"), "receipt.identity")
    _exact(receipt, "identity_sha256", canonical_digest(identity_core), "receipt")
    _validate_nonce(nonce, "receipt.namespace_nonce")
    _sha(receipt.get("receipt_sha256"), "receipt.receipt_sha256")
    core = dict(receipt)
    core.pop("receipt_sha256", None)
    core.pop("receipt_descriptor", None)
    core.pop("namespace_marker_descriptor", None)
    _exact({"value": canonical_digest(core)}, "value", receipt["receipt_sha256"], "receipt digest")
    if check_files:
        marker_path = namespace / NAMESPACE_MARKER
        _raw, _descriptor, marker_payload = _read_bound(marker_path, "namespace marker", max_bytes=MAX_JSON_BYTES, parse_json=True)
        assert marker_payload is not None
        _unknown(marker_payload, {"schema", "namespace", "namespace_nonce", "receipt_sha256", "identity_sha256", "one_shot", "diagnostic_only"}, "namespace marker")
        _exact(marker_payload, "schema", f"{SCHEMA}.namespace_marker", "namespace marker")
        _exact(marker_payload, "namespace", str(namespace), "namespace marker")
        _exact(marker_payload, "namespace_nonce", nonce, "namespace marker")
        _exact(marker_payload, "receipt_sha256", receipt["receipt_sha256"], "namespace marker")
        _exact(marker_payload, "identity_sha256", receipt["identity_sha256"], "namespace marker")
        _exact(marker_payload, "one_shot", True, "namespace marker")
        _exact(marker_payload, "diagnostic_only", True, "namespace marker")


def validate_receipt(receipt: Mapping[str, Any], *, check_files: bool = True) -> list[str]:
    try:
        _walk_json(receipt, "receipt")
        _validate_shape(receipt, check_files=check_files)
        if check_files:
            _validate_external_binding(receipt)
        return []
    except (AdmissionError, TypeError, KeyError) as error:
        return [str(error)]


def load_receipt(path: Path | str, *, allow_consumed: bool = False) -> dict[str, Any]:
    candidate = _absolute(path, "admission receipt")
    _raw, _descriptor, payload = _read_bound(candidate, "admission receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    assert payload is not None
    _validate_shape(payload, check_files=True)
    _validate_external_binding(payload)
    if candidate != Path(payload["receipt_path"]):
        _fail("receipt path is not bound to its canonical namespace path")
    consumed = Path(payload["consumption"]["consumed_marker"])
    if os.path.lexists(consumed):
        if not allow_consumed:
            _fail("admission receipt has already been consumed")
        payload = dict(payload)
        payload["consumption"] = dict(payload["consumption"])
        payload["consumption"]["consumed"] = True
    return payload


def revalidate_receipt(
    receipt: Mapping[str, Any],
    *,
    resource_admission: Mapping[str, Any] | None = None,
    check_files: bool = True,
) -> dict[str, Any]:
    _validate_shape(receipt, check_files=check_files)
    if check_files:
        _validate_external_binding(receipt)
    core = _mapping(receipt["identity"], "receipt.identity")
    if resource_admission is not None:
        observed_resource = _validate_resource(resource_admission)
        if canonical_json(observed_resource) != canonical_json(core["resource_admission"]):
            _fail("resource snapshot drifted from the receipt")
    for name, descriptor in dict(core["source_files"]).items():
        observed = _file_descriptor(Path(descriptor["path"]), f"source.{name}", max_bytes=MAX_SOURCE_BYTES)
        _descriptor_equal(observed, descriptor, f"source.{name}")
    for name, descriptor, limit in (
        ("manifest", core["manifest"]["file"], MAX_JSON_BYTES),
        ("training_receipt", core["training_receipt"]["file"], MAX_JSON_BYTES),
        ("checkpoint", core["checkpoint"]["file"], MAX_CHECKPOINT_BYTES),
        ("executable", core["executable"], MAX_EXECUTABLE_BYTES),
    ):
        observed = _file_descriptor(Path(descriptor["path"]), name, max_bytes=limit)
        _descriptor_equal(observed, descriptor, name)
    namespace = Path(core["namespace"])
    _reject_symlinks(namespace, "bound namespace")
    info = os.lstat(namespace)
    descriptor = core["namespace_descriptor"]
    if not stat.S_ISDIR(info.st_mode) or int(info.st_ino) != descriptor["ino"] or int(info.st_dev) != descriptor["dev"] or int(info.st_nlink) != descriptor["nlink"]:
        _fail("bound namespace identity drifted")
    if not check_files:
        return dict(receipt)
    return dict(receipt)


def consume_receipt(path: Path | str) -> AdmissionCapability:
    receipt = load_receipt(path)
    revalidate_receipt(receipt)
    namespace = Path(receipt["namespace"])
    lock = namespace / CONSUMPTION_LOCK
    consumed = namespace / CONSUMED_MARKER
    lock_desc = _write_exclusive(lock, (canonical_json({"schema": CONSUMED_SCHEMA, "receipt_sha256": receipt["receipt_sha256"], "uid": os.getuid(), "gid": os.getgid()}) + "\n").encode("utf-8"))
    authority = _mapping(receipt["identity"].get("external_authority"), "receipt.identity.external_authority")
    claim_path = _external_scheduler_path(authority["consume_path"], "external scheduler consume path")
    claim_payload = {
        "schema": EXTERNAL_CLAIM_SCHEMA,
        "state": "consumed",
        "one_shot": True,
        "receipt_sha256": receipt["receipt_sha256"],
        "identity_sha256": receipt["identity_sha256"],
        "authority_id": authority["authority_id"],
        "namespace": str(namespace),
        "nonce": receipt["namespace_nonce"],
        "local_lock_sha256": lock_desc["sha256"],
        "owner": {"uid": os.getuid(), "gid": os.getgid(), "host": CURRENT_HOST},
        **ZERO_CREDIT,
    }
    claim_desc = _write_exclusive(
        claim_path,
        (canonical_json(claim_payload) + "\n").encode("utf-8"),
    )
    consumed_payload = {
        "schema": CONSUMED_SCHEMA,
        "receipt_sha256": receipt["receipt_sha256"],
        "lock_sha256": lock_desc["sha256"],
        "external_claim_sha256": claim_desc["sha256"],
        "uid": os.getuid(),
        "gid": os.getgid(),
        **ZERO_CREDIT,
    }
    consumed_desc = _write_exclusive(
        consumed,
        (canonical_json(consumed_payload) + "\n").encode("utf-8"),
    )
    seal = canonical_digest(
        {
            "receipt_sha256": receipt["receipt_sha256"],
            "lock": lock_desc,
            "external_claim": claim_desc,
            "consumed": consumed_desc,
            "diagnostic_only": True,
        }
    )
    return AdmissionCapability(
        receipt=receipt,
        receipt_path=Path(receipt["receipt_path"]),
        lock_path=lock,
        consumed_marker=consumed,
        seal=seal,
        external_claim_path=claim_path,
    )


def build_report(receipt_path: Path | str | None = None, *, consume_requested: bool = False) -> dict[str, Any]:
    base = {"schema": REPORT_SCHEMA, "report_id": REPORT_ID, "status": "blocked_fail_closed", "mode": "consume_request" if consume_requested else "dry_run", "receipt_path": None if receipt_path is None else str(receipt_path), "receipt_valid": False, "one_shot_consumed": False, "consume_requested": bool(consume_requested), "popen_attempted": False, "terminal_receipt_minted": False, "blocked_reasons": [], **ZERO_CREDIT}
    if receipt_path is None:
        base["blocked_reasons"] = ["admission receipt is required; no implicit receipt is minted"]
        return base
    try:
        receipt = load_receipt(receipt_path)
        revalidate_receipt(receipt)
        base.update({"receipt_valid": True, "receipt_path": receipt["receipt_path"], "identity_sha256": receipt["identity_sha256"], "namespace": receipt["namespace"], "blocked_reasons": ["admission is diagnostic-only and does not authorize Popen/wait", "terminal producer and independent HDF5 validator capabilities are not admitted", "formal/credit promotion is permanently isolated"]})
        return base
    except (AdmissionError, OSError, ValueError) as error:
        base["blocked_reasons"] = [str(error)]
        return base


def validate_report(report: Mapping[str, Any]) -> list[str]:
    try:
        _walk_json(report, "report")
        allowed = set(ZERO_CREDIT) | {"schema", "report_id", "status", "mode", "receipt_path", "receipt_valid", "one_shot_consumed", "consume_requested", "popen_attempted", "terminal_receipt_minted", "blocked_reasons", "identity_sha256", "namespace"}
        _unknown(report, allowed, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        _exact(report, "popen_attempted", False, "report")
        _exact(report, "terminal_receipt_minted", False, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a non-empty string list")
        return []
    except (AdmissionError, TypeError, KeyError) as error:
        return [str(error)]


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join([
        "# F3 graph_residual hidden16 seed29 diagnostic admission",
        "",
        f"- status: `{report.get('status')}`",
        f"- mode: `{report.get('mode')}`",
        f"- receipt valid: `{report.get('receipt_valid')}`",
        "- one-shot namespace: owner-only exclusive directory plus atomic consumption marker",
        "- execution: no Popen/wait path in this contract; terminal receipt minting is forbidden",
        "- formal/credit/registry/ledger/PLAN writes: `0`; credit: `0`",
        "",
        "## Blockers",
        "",
        *[f"- {item}" for item in report.get("blocked_reasons", []) if isinstance(item, str)],
        "",
    ])


def _read_report(path: Path) -> dict[str, Any]:
    _raw, _descriptor, payload = _read_bound(path, "report", max_bytes=MAX_JSON_BYTES, parse_json=True)
    assert payload is not None
    return payload


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-receipt", type=Path, default=None)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    parser.add_argument("--consume", action="store_true", help="report the blocked consume request; does not mint or execute")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            report = _read_report(_absolute(args.verify_report, "report"))
            errors = validate_report(report)
            print(canonical_json({"schema": REPORT_SCHEMA, "valid": not errors, "errors": errors}))
            return 0 if not errors else 1
        report = build_report(args.admission_receipt, consume_requested=args.consume)
        _write_exclusive(args.report_output, (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"), mode=0o640)
        _write_exclusive(args.report_output.with_suffix(".zh-CN.md"), render_markdown(report).encode("utf-8"), mode=0o640)
        print(canonical_json(report))
        return 2
    except (AdmissionError, OSError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
