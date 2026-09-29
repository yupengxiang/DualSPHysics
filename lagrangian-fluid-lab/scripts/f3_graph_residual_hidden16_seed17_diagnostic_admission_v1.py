#!/usr/bin/env python3
"""Receipt-bound, diagnostic-only admission for residual/hidden16 seed17.

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher
from scripts import f3_graph_residual_hidden16_current_manifest_terminal_artifact_identity_v1 as identity


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 17
GPU_INDEX = 4
MODEL = launcher.MODEL
HIDDEN = launcher.HIDDEN
UPDATES = launcher.UPDATES
CASE_ID = launcher.CASE_ID
SPLIT = launcher.SPLIT
TRANSITIONS = launcher.TRANSITIONS
FRAMES = launcher.FRAMES
RUN_ID = identity._expected_run_id(SEED)
MANIFEST_SCHEMA = launcher.MANIFEST_SCHEMA
TRAINING_SCHEMA = launcher.TRAINING_SCHEMA
CHECKPOINT_SCHEMA = launcher.CHECKPOINT_SCHEMA

SCHEMA = "core.f3.graph_residual.hidden16.seed17.diagnostic_admission.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
CONSUMED_SCHEMA = f"{SCHEMA}.consumed"
REPORT_ID = "f3-graph-residual-hidden16-seed17-diagnostic-admission-v1"
DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_TRAINING = Path(
    f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{SEED}-20260929-v3-training.json"
)
DEFAULT_CHECKPOINT = Path(
    f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{SEED}-20260929-v3-checkpoint.pt"
)
DEFAULT_REPORT = LAB_ROOT / "reports" / "F3-GRAPH-RESIDUAL-HIDDEN16-SEED17-DIAGNOSTIC-ADMISSION-2026-09-29.json"
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_path": str(self.receipt_path),
            "receipt_sha256": self.receipt.get("receipt_sha256"),
            "lock_path": str(self.lock_path),
            "consumed_marker": str(self.consumed_marker),
            "seal": self.seal,
            "diagnostic_only": True,
            "popen_authorized": False,
            "launch_allowed": False,
            "formal_promotion_allowed": False,
            "credit": 0,
        }


def _identity_core(*, root: Path, manifest: Mapping[str, Any], training: Mapping[str, Any], checkpoint: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]], executable: Mapping[str, Any], command: Sequence[str], env: Mapping[str, str], namespace: Path, namespace_descriptor: Mapping[str, Any], nonce: str, resource_admission: Mapping[str, Any]) -> dict[str, Any]:
    env_snapshot = _environment(env)
    return {
        "root": str(root), "seed": SEED, "run_id": RUN_ID, "model_kind": MODEL,
        "hidden": HIDDEN, "updates": UPDATES, "case_id": CASE_ID, "split": SPLIT,
        "transitions": TRANSITIONS, "frames": FRAMES,
        "manifest": dict(manifest), "training_receipt": dict(training), "checkpoint": dict(checkpoint),
        "source_files": {key: dict(value) for key, value in sources.items()},
        "executable": dict(executable),
        "command": {"argv": list(command), "cwd": str(root), "env_overrides": dict(env), "sha256": canonical_digest({"argv": list(command), "cwd": str(root), "env_overrides": dict(env), "seed": SEED, "gpu_index": GPU_INDEX})},
        "environment": env_snapshot,
        "resource_admission": dict(resource_admission),
        "namespace": str(namespace), "namespace_descriptor": dict(namespace_descriptor), "nonce": nonce,
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


def mint_admission(root: Path | str = LAB_ROOT, *, manifest: Path | str = DEFAULT_MANIFEST, training_receipt: Path | str = DEFAULT_TRAINING, checkpoint: Path | str | None = None, nonce: str | None = None, output_root: Path | str = "/tmp", resource_admission: Mapping[str, Any] | None = None, python_executable: Path | str | None = None) -> dict[str, Any]:
    """Mint one source-bound, zero-credit receipt without starting anything."""

    root_path = _absolute(root, "root")
    _reject_symlinks(root_path, "root")
    if not root_path.is_dir():
        _fail("root must be an existing directory")
    selected_nonce = _validate_nonce(nonce if nonce is not None else secrets.token_hex(16))
    resource_snapshot = _validate_resource(resource_admission) if resource_admission is not None else _fail("scheduler-owned GPU UUID/PCI snapshot is required")
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
    namespace_desc = _mkdir_exclusive(namespace)
    outputs = launcher._output_paths(namespace, root_path, SEED, selected_nonce)
    if any(os.path.lexists(path) for path in outputs.values()):
        _fail("a bound rollout output already exists; fresh namespace is required")
    command = launcher._build_command(root=root_path, python=python, manifest=manifest_path, checkpoint=checkpoint_path, outputs=outputs)
    env = {"CUDA_VISIBLE_DEVICES": str(GPU_INDEX), "CUDA_DEVICE_ORDER": CUDA_DEVICE_ORDER, "PYTHONDONTWRITEBYTECODE": "1"}
    identity_core = _identity_core(
        root=root_path,
        manifest={"binding": manifest_binding, "file": manifest_desc},
        training={"binding": training_binding, "file": training_desc},
        checkpoint={**training_binding["checkpoint"], "file": checkpoint_desc},
        sources=source_files,
        executable=executable,
        command=command,
        env=env,
        namespace=namespace,
        namespace_descriptor=namespace_desc,
        nonce=selected_nonce,
        resource_admission=resource_snapshot,
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
        return []
    except (AdmissionError, TypeError, KeyError) as error:
        return [str(error)]


def load_receipt(path: Path | str, *, allow_consumed: bool = False) -> dict[str, Any]:
    candidate = _absolute(path, "admission receipt")
    _raw, _descriptor, payload = _read_bound(candidate, "admission receipt", max_bytes=MAX_JSON_BYTES, parse_json=True)
    assert payload is not None
    _validate_shape(payload, check_files=True)
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


def revalidate_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    _validate_shape(receipt, check_files=True)
    core = _mapping(receipt["identity"], "receipt.identity")
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
    return dict(receipt)


def consume_receipt(path: Path | str) -> AdmissionCapability:
    receipt = load_receipt(path)
    revalidate_receipt(receipt)
    namespace = Path(receipt["namespace"])
    lock = namespace / CONSUMPTION_LOCK
    consumed = namespace / CONSUMED_MARKER
    lock_desc = _write_exclusive(lock, (canonical_json({"schema": CONSUMED_SCHEMA, "receipt_sha256": receipt["receipt_sha256"], "uid": os.getuid(), "gid": os.getgid()}) + "\n").encode("utf-8"))
    consumed_desc = _write_exclusive(consumed, (canonical_json({"schema": CONSUMED_SCHEMA, "receipt_sha256": receipt["receipt_sha256"], "lock_sha256": lock_desc["sha256"], "uid": os.getuid(), "gid": os.getgid()}) + "\n").encode("utf-8"))
    seal = canonical_digest({"receipt_sha256": receipt["receipt_sha256"], "lock": lock_desc, "consumed": consumed_desc})
    return AdmissionCapability(receipt=receipt, receipt_path=Path(receipt["receipt_path"]), lock_path=lock, consumed_marker=consumed, seal=seal)


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
        "# F3 graph_residual hidden16 seed17 diagnostic admission",
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
