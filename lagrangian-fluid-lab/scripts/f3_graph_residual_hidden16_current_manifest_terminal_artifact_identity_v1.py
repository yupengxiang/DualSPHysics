#!/usr/bin/env python3
"""Diagnostic-only terminal artifact identity boundary for F3 graph_residual.

This additive contract is deliberately separate from the current residual
launcher, matrix, intake, and historical verifier.  It reuses the launcher's
read-only current-manifest/training identity checks, then defines the exact
cross-bindings a future terminal receipt must satisfy:

* current-manifest graph_residual/hidden16, seeds 17/29/43, 500 updates;
* a fresh per-seed full835 namespace and 32-hex nonce;
* a real ``subprocess.Popen``/``wait`` process proof for the exact command;
* an independent HDF5 validator receipt for 835 transitions/836 frames; and
* one consistent identity for checkpoint, evaluation, trajectory, and
  validator artifacts.

No evaluator, solver, worker, GPU workload, or queue is started here.  The
terminal capability is not admitted, so ``execute_plan`` fails before Popen.
All reports remain diagnostic-only and zero-credit.  The artifact validator
below checks a future receipt's shape and cross-bindings; it does not open an
HDF5 file itself and does not turn declared evidence into formal credit.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
from typing import Any

import h5py

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_residual_hidden16_current_manifest_rollout_launcher_v1 as launcher


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
DEFAULT_GPU_INDICES = {17: 4, 29: 5, 43: 6}
MODEL = launcher.MODEL
HIDDEN = launcher.HIDDEN
UPDATES = launcher.UPDATES
CASE_ID = launcher.CASE_ID
SPLIT = launcher.SPLIT
TRANSITIONS = launcher.TRANSITIONS
FRAMES = launcher.FRAMES
GPU_COUNT = launcher.GPU_COUNT
PLAN_DATE = "20260929"

SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.terminal_artifact_identity.v1"
PLAN_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.audited_terminal_plan.v1"
REPORT_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.terminal_artifact_identity_report.v1"
REPORT_ID = "f3-graph-residual-hidden16-current-manifest-terminal-artifact-identity-v1"
PROCESS_PROOF_SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.process_proof.v2"
HDF5_VALIDATOR_SCHEMA = launcher.VALIDATOR_SCHEMA
TERMINAL_CAPABILITY_SCHEMA = (
    "core.f3.graph_residual.hidden16.current_manifest.terminal_hdf5_artifact_capability.v1"
)
SEALED_LIFECYCLE_SCHEMA = (
    "core.f3.graph_residual.hidden16.current_manifest.sealed_popen_wait_lifecycle.v1"
)

DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_RECEIPTS = {
    seed: Path(
        f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{seed}-{PLAN_DATE}-v3-training.json"
    )
    for seed in SEEDS
}
DEFAULT_CHECKPOINTS = {
    seed: Path(
        f"/tmp/f3-graph_residual500-hidden16-currentmanifest-seed{seed}-{PLAN_DATE}-v3-checkpoint.pt"
    )
    for seed in SEEDS
}
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-TERMINAL-ARTIFACT-IDENTITY-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_ARTIFACT_BYTES = 1 << 50
MAX_HDF5_LINKS = 8192

MIN_GPU_FREE_MIB = 8 * 1024
MIN_CPU_COUNT = 4
MAX_LOAD_PER_CPU = 2.0
MIN_DISK_FREE_BYTES = 2 * 1024**3

ZERO_CREDIT: dict[str, Any] = {
    "diagnostic_only": True,
    "zero_credit_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}


class IdentityError(ValueError):
    """Malformed, drifting, unsafe, or authorizing input."""


def _fail(message: str) -> None:
    raise IdentityError(f"fail-closed: {message}")


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
    normalized = Path(os.path.normpath(str(candidate)))
    if candidate != normalized or any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a lexical path alias")
    return normalized


def _filesystem_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    """Return the immutable-ish identity fields used around one safe read."""

    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _directory_flags() -> int:
    required = getattr(os, "O_DIRECTORY", 0)
    if required == 0:
        _fail("platform does not expose O_DIRECTORY")
    return os.O_RDONLY | required | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_artifact_parent(path: Path, name: str) -> tuple[int, list[int]]:
    """Open every parent component without following a directory symlink."""

    flags = _directory_flags()
    opened: list[int] = []
    try:
        current = os.open(os.sep, flags)
        opened.append(current)
        for component in path.parts[1:-1]:
            next_fd = os.open(component, flags, dir_fd=current)
            opened.append(next_fd)
            current = next_fd
        return current, opened
    except OSError as error:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        _fail(f"{name} parent contains a symlink or unsafe directory: {error}")


def _reject_unsafe_hdf5_links(handle: h5py.File) -> int:
    """Reject external/soft links, external storage, and virtual datasets."""

    pending: list[h5py.Group] = [handle]
    visited_groups: set[int] = set()
    visited_links = 0
    while pending:
        group = pending.pop()
        group_id = int(group.id.id)
        if group_id in visited_groups:
            continue
        visited_groups.add(group_id)
        for member in group.keys():
            visited_links += 1
            if visited_links > MAX_HDF5_LINKS:
                _fail("HDF5 link count exceeds the bounded limit")
            link = group.get(member, getlink=True)
            if not isinstance(link, h5py.HardLink):
                _fail(f"HDF5 contains a non-hard link at {member!r}")
            obj = group.get(member)
            if isinstance(obj, h5py.Group):
                pending.append(obj)
            elif isinstance(obj, h5py.Dataset):
                if bool(getattr(obj, "is_virtual", False)):
                    _fail(f"HDF5 contains a virtual dataset at {member!r}")
                external_storage = getattr(obj, "external", None)
                if external_storage:
                    _fail(f"HDF5 contains externally stored dataset at {member!r}")
            else:
                _fail(f"HDF5 contains an unsupported object at {member!r}")
    return visited_links


def _inspect_hdf5_descriptor(fd: int, name: str) -> dict[str, Any]:
    """Inspect HDF5 from the already-open descriptor, never from its path."""

    try:
        os.lseek(fd, 0, os.SEEK_SET)
        stream = os.fdopen(os.dup(fd), "rb", closefd=True)
        with stream:
            with h5py.File(stream, "r") as handle:
                links = _reject_unsafe_hdf5_links(handle)
    except (OSError, ValueError, RuntimeError) as error:
        _fail(f"{name} is not a safe physical-link HDF5 snapshot: {error}")
    return {
        "physical_hdf5": True,
        "hard_link_count": links,
        "external_links_rejected": True,
        "soft_links_rejected": True,
        "external_storage_rejected": True,
        "virtual_datasets_rejected": True,
    }


def read_bound_artifact(
    path: Path | str,
    *,
    expected_sha256: str,
    expected_bytes: int,
    name: str = "artifact",
    hdf5: bool = False,
) -> dict[str, Any]:
    """Read/hash one stable single-link artifact through descriptor handles.

    The digest and byte count come from the same descriptor used for the
    optional HDF5 inspection.  Parent/leaf symlinks, hard links, descriptor
    replacement, and pathname drift are all fail-closed.  HDF5 is inspected
    only through the bound descriptor, and every link must be a physical hard
    link with no external storage or VDS.
    """

    candidate = _absolute_path(path, f"{name}.path")
    expected_sha256 = _sha(expected_sha256, f"{name}.sha256")
    expected_bytes = _int(expected_bytes, f"{name}.bytes", 1)
    if expected_bytes > MAX_ARTIFACT_BYTES:
        _fail(f"{name}.bytes exceeds the bounded artifact limit")
    parent_fd, opened = _open_artifact_parent(candidate, name)
    leaf_fd: int | None = None
    before: os.stat_result | None = None
    digest = hashlib.sha256()
    total = 0
    hdf5_identity: dict[str, Any] | None = None
    try:
        try:
            leaf_fd = os.open(
                candidate.name,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except OSError as error:
            _fail(f"{name} cannot be opened without following links: {error}")
        before = os.fstat(leaf_fd)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{name} must be a regular file")
        if before.st_nlink != 1:
            _fail(f"{name} must have exactly one hard link")
        if before.st_size != expected_bytes:
            _fail(f"{name}.bytes disagrees with the bound descriptor")
        if before.st_size < 1 or before.st_size > MAX_ARTIFACT_BYTES:
            _fail(f"{name} is outside the bounded artifact size")

        while True:
            block = os.read(leaf_fd, min(1024 * 1024, MAX_ARTIFACT_BYTES - total))
            if not block:
                break
            digest.update(block)
            total += len(block)
            if total > MAX_ARTIFACT_BYTES:
                _fail(f"{name} exceeds the bounded artifact limit")
        if total != before.st_size:
            _fail(f"{name} changed while it was being read")
        if hdf5:
            hdf5_identity = _inspect_hdf5_descriptor(leaf_fd, name)
        after_fd = os.fstat(leaf_fd)
        if _filesystem_identity(after_fd) != _filesystem_identity(before):
            _fail(f"{name} descriptor identity changed during validation")
    except OSError as error:
        _fail(f"{name} cannot be read safely: {error}")
    finally:
        if leaf_fd is not None:
            try:
                os.close(leaf_fd)
            except OSError:
                pass
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass

    try:
        after_path = os.lstat(candidate)
    except OSError as error:
        _fail(f"{name} path changed after descriptor validation: {error}")
    if (
        before is None
        or not stat.S_ISREG(after_path.st_mode)
        or after_path.st_nlink != 1
        or _filesystem_identity(after_path) != _filesystem_identity(before)
    ):
        _fail(f"{name} path identity drifted after descriptor validation")
    observed_sha256 = digest.hexdigest()
    if observed_sha256 != expected_sha256:
        _fail(f"{name}.sha256 disagrees with the bound descriptor")
    return {
        "path": str(candidate),
        "sha256": observed_sha256,
        "bytes": total,
        "identity": {
            "st_dev": int(before.st_dev),
            "st_ino": int(before.st_ino),
            "st_mode": int(before.st_mode),
            "st_nlink": int(before.st_nlink),
            "st_size": int(before.st_size),
            "st_mtime_ns": int(before.st_mtime_ns),
            "st_ctime_ns": int(before.st_ctime_ns),
        },
        "hdf5": hdf5_identity,
    }


def _read_bounded_json(path: Path | str, *, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = _absolute_path(path, name)
    try:
        before = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    if before.st_size > MAX_JSON_BYTES:
        _fail(f"{name} exceeds bounded size {MAX_JSON_BYTES}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    try:
        raw = os.read(fd, MAX_JSON_BYTES + 1)
        after_fd = os.fstat(fd)
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name} after read: {error}")
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    identity_fd = (after_fd.st_dev, after_fd.st_ino, after_fd.st_size, after_fd.st_mtime_ns)
    if identity_before != identity_after or identity_before != identity_fd or len(raw) != before.st_size:
        _fail(f"{name} changed during bounded read")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, IdentityError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    _walk_json(payload, name)
    if not isinstance(payload, dict):
        _fail(f"{name} must contain a JSON object")
    return payload, {
        "path": str(candidate),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload.get("schema"),
    }


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        if key in value:
            _exact(value, key, expected, name)


def _validate_nonce(value: Any, name: str) -> str:
    nonce = _string(value, name)
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail(f"{name} must be a non-zero 32-character lowercase hexadecimal value")
    return nonce


def _admission_from_values(
    *,
    gpu_index: int,
    gpu_row: Mapping[str, Any] | None,
    cpu_count: int,
    load_1m: float,
    tmp_free_bytes: int,
    root_free_bytes: int,
    probe_errors: Sequence[str] = (),
) -> dict[str, Any]:
    reasons = [str(item) for item in probe_errors]
    if gpu_row is None:
        gpu = {"total_mib": 0, "used_mib": 0, "free_mib": 0}
        reasons.append(f"GPU {gpu_index} is absent from the bounded VRAM probe")
    else:
        gpu = {
            "total_mib": _int(gpu_row.get("total_mib"), "gpu.total_mib"),
            "used_mib": _int(gpu_row.get("used_mib"), "gpu.used_mib"),
            "free_mib": _int(gpu_row.get("free_mib"), "gpu.free_mib"),
        }
        if gpu["used_mib"] + gpu["free_mib"] > gpu["total_mib"]:
            _fail("GPU used/free memory exceeds total memory")
    if gpu["free_mib"] < MIN_GPU_FREE_MIB:
        reasons.append(f"GPU {gpu_index} free VRAM is below {MIN_GPU_FREE_MIB} MiB")
    if cpu_count < MIN_CPU_COUNT:
        reasons.append(f"CPU count {cpu_count} is below {MIN_CPU_COUNT}")
    if not math.isfinite(load_1m) or load_1m < 0:
        reasons.append("CPU load average is not finite and non-negative")
        load_per_cpu = float("inf")
    else:
        load_per_cpu = load_1m / max(cpu_count, 1)
        if load_per_cpu > MAX_LOAD_PER_CPU:
            reasons.append(f"CPU load per logical core exceeds {MAX_LOAD_PER_CPU}")
    if tmp_free_bytes < MIN_DISK_FREE_BYTES:
        reasons.append("/tmp free space is below the bounded I/O threshold")
    if root_free_bytes < MIN_DISK_FREE_BYTES:
        reasons.append("root free space is below the bounded I/O threshold")
    return {
        "schema": "core.f3.graph_residual.hidden16.current_manifest.resource_admission.v1",
        "gpu_index": gpu_index,
        "gpu": gpu,
        "cpu": {
            "logical_count": cpu_count,
            "load_1m": load_1m,
            "load_per_logical_core": load_per_cpu,
        },
        "io": {
            "tmp_free_bytes": tmp_free_bytes,
            "root_free_bytes": root_free_bytes,
            "minimum_free_bytes": MIN_DISK_FREE_BYTES,
        },
        "status": "admitted" if not reasons else "blocked",
        "admitted": not reasons,
        "blocked_reasons": reasons,
        "content_opened": False,
    }


def _query_gpu_rows() -> tuple[dict[int, dict[str, int]], list[str]]:
    command = (
        "nvidia-smi",
        "--query-gpu=index,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    )
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        return {}, [f"nvidia-smi admission probe failed: {error}"]
    if result.returncode != 0:
        return {}, [f"nvidia-smi admission probe returned {result.returncode}"]
    rows: dict[int, dict[str, int]] = {}
    errors: list[str] = []
    for line in result.stdout.splitlines():
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 4:
            errors.append("nvidia-smi returned a malformed GPU row")
            continue
        try:
            index, total, used, free = (int(item) for item in fields)
        except ValueError:
            errors.append("nvidia-smi returned a non-integer GPU row")
            continue
        if index in rows or min(total, used, free) < 0 or used + free > total:
            errors.append(f"nvidia-smi returned an invalid row for GPU {index}")
            continue
        rows[index] = {"total_mib": total, "used_mib": used, "free_mib": free}
    if not rows:
        errors.append("nvidia-smi returned no usable GPU rows")
    return rows, errors


def probe_resource_admission(
    gpu_index: int,
    *,
    gpu_rows: Mapping[int, Mapping[str, Any]] | None = None,
    probe_errors: Sequence[str] = (),
    cpu_count: int | None = None,
    load_1m: float | None = None,
    tmp_free_bytes: int | None = None,
    root_free_bytes: int | None = None,
) -> dict[str, Any]:
    """Collect read-only resource metadata; never starts a workload."""

    if type(gpu_index) is not int or not 0 <= gpu_index < GPU_COUNT:
        _fail(f"gpu_index must be an integer in [0, {GPU_COUNT})")
    if gpu_rows is None:
        gpu_rows, query_errors = _query_gpu_rows()
        probe_errors = tuple(probe_errors) + tuple(query_errors)
    if cpu_count is None:
        cpu_count = os.cpu_count() or 0
    if load_1m is None:
        try:
            load_1m = float(os.getloadavg()[0])
        except (AttributeError, OSError):
            load_1m = float("nan")
    if tmp_free_bytes is None:
        try:
            tmp_free_bytes = int(shutil.disk_usage("/tmp").free)
        except OSError as error:
            probe_errors = tuple(probe_errors) + (f"/tmp disk probe failed: {error}",)
            tmp_free_bytes = 0
    if root_free_bytes is None:
        try:
            root_free_bytes = int(shutil.disk_usage(LAB_ROOT).free)
        except OSError as error:
            probe_errors = tuple(probe_errors) + (f"root disk probe failed: {error}",)
            root_free_bytes = 0
    return _admission_from_values(
        gpu_index=gpu_index,
        gpu_row=None if gpu_rows is None else gpu_rows.get(gpu_index),
        cpu_count=cpu_count,
        load_1m=load_1m,
        tmp_free_bytes=tmp_free_bytes,
        root_free_bytes=root_free_bytes,
        probe_errors=probe_errors,
    )


@dataclass(frozen=True)
class AuditedPlan:
    base: Any
    gpu_index: int
    admission: Mapping[str, Any]
    plan_digest: str

    @property
    def seed(self) -> int:
        return self.base.seed

    @property
    def nonce(self) -> str:
        return self.base.nonce

    @property
    def namespace(self) -> Path:
        return self.base.output_namespace

    @property
    def outputs(self) -> Mapping[str, Path]:
        return self.base.outputs

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "status": "audited_identity_ready",
            "executor_schema": SCHEMA,
            "seed": self.seed,
            "run_id": self.base.run_id,
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "manifest_sha256": self.base.manifest_binding["canonical_sha256"],
            "training_receipt_sha256": self.base.training_binding["sha256"],
            "checkpoint": dict(self.base.checkpoint),
            "namespace": str(self.namespace),
            "namespace_nonce": self.nonce,
            "command": list(self.base.command),
            "command_sha256": self.base.command_sha256,
            "gpu_index": self.gpu_index,
            "admission": dict(self.admission),
            "plan_digest": self.plan_digest,
            "launch_allowed": False,
            "terminal_capability_admitted": False,
            **ZERO_CREDIT,
        }


def _plan_digest(base: Any, gpu_index: int, admission: Mapping[str, Any]) -> str:
    return canonical_digest(
        {
            "schema": PLAN_SCHEMA,
            "run_id": base.run_id,
            "seed": base.seed,
            "nonce": base.nonce,
            "namespace": str(base.output_namespace),
            "manifest_sha256": base.manifest_binding["canonical_sha256"],
            "training_receipt_sha256": base.training_binding["sha256"],
            "checkpoint": dict(base.checkpoint),
            "command": list(base.command),
            "command_sha256": base.command_sha256,
            "cwd": str(base.cwd),
            "env": dict(base.env),
            "gpu_index": gpu_index,
            "admission": dict(admission),
        }
    )


def build_audited_plan(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    manifest: Path | str,
    training_receipt: Path | str,
    checkpoint: Path | str,
    run_id: str,
    nonce: str,
    output_namespace: Path | str,
    gpu_index: int,
    admission: Mapping[str, Any],
    python_executable: Path | str | None = None,
) -> AuditedPlan:
    """Bind one current-manifest plan without starting the evaluator."""

    if seed not in SEEDS:
        _fail(f"seed must be one of {SEEDS}")
    nonce = _validate_nonce(nonce, "nonce")
    if set(admission) - {"schema", "gpu_index", "gpu", "cpu", "io", "status", "admitted", "blocked_reasons", "content_opened"}:
        _fail("admission contains unknown fields")
    base = _build_current_manifest_plan(
        root,
        seed=seed,
        manifest=manifest,
        checkpoint=checkpoint,
        training_receipt=training_receipt,
        run_id=run_id,
        nonce=nonce,
        output_namespace=output_namespace,
        gpu_index=gpu_index,
        python_executable=python_executable,
    )
    if base.nonce != nonce or base.seed != seed:
        _fail("launcher plan identity drifted from the audited seed/nonce")
    if base.command_sha256 != launcher._command_digest(base.command, cwd=base.cwd, env=base.env):
        _fail("launcher command digest is not self-consistent")
    return AuditedPlan(
        base=base,
        gpu_index=gpu_index,
        admission=dict(admission),
        plan_digest=_plan_digest(base, gpu_index, admission),
    )


def _expected_run_id(seed: int) -> str:
    return f"f3-graph_residual500-hidden16-currentmanifest-seed{seed}-{PLAN_DATE}-v3"


def _fresh_namespace(seed: int, nonce: str, output_root: Path | str) -> Path:
    root = _absolute_path(output_root, "output_root")
    return root / f"f3-graph-residual500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"


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
    """Bind current core_learning identity while allowing its diagnostics."""

    _exact(payload, "schema", launcher.TRAINING_SCHEMA, "training_receipt")
    _exact(payload, "evidence_status", "complete", "training_receipt")
    _exact(payload, "model_kind", MODEL, "training_receipt")
    _exact(payload, "seed", seed, "training_receipt")
    _exact(payload, "run_id", run_id, "training_receipt")
    _exact(payload, "completed_updates", UPDATES, "training_receipt")
    _exact(payload, "parameter_count", launcher.PARAMETER_COUNT, "training_receipt")
    _exact(payload, "checkpoint_verified", True, "training_receipt")
    _zero_credit(payload, "training_receipt")
    config = _mapping(payload.get("config"), "training_receipt.config")
    if dict(config) != launcher._expected_config(manifest_sha256, seed, run_id):
        _fail("training_receipt.config does not exactly bind current manifest, v3 model, and seed")

    checkpoint = _mapping(payload.get("checkpoint"), "training_receipt.checkpoint")
    _exact(checkpoint, "schema", launcher.CHECKPOINT_SCHEMA, "training_receipt.checkpoint")
    _exact(checkpoint, "update", UPDATES, "training_receipt.checkpoint")
    declared_checkpoint = _absolute_path(
        checkpoint.get("path"), "training_receipt.checkpoint.path"
    )
    if declared_checkpoint != checkpoint_path:
        _fail("training_receipt.checkpoint.path drifts from the explicit current checkpoint")
    checkpoint_sha = _sha(checkpoint.get("sha256"), "training_receipt.checkpoint.sha256")
    checkpoint_bytes = _int(checkpoint.get("bytes"), "training_receipt.checkpoint.bytes", 1)
    launcher._metadata_only(
        checkpoint_path,
        "checkpoint input",
        expected_bytes=checkpoint_bytes,
    )

    evidence = _mapping(payload.get("evidence"), "training_receipt.evidence")
    _exact(evidence, "schema", "core.training.evidence.v1", "training_receipt.evidence")
    _exact(evidence, "status", "complete", "training_receipt.evidence")
    initialization = _mapping(
        evidence.get("initialization"), "training_receipt.evidence.initialization"
    )
    init_name = "training_receipt.evidence.initialization"
    _exact(initialization, "schema", "core.training.initialization_evidence.v1", init_name)
    _exact(initialization, "status", "captured", init_name)
    _exact(initialization, "model_kind", MODEL, init_name)
    _exact(initialization, "hidden", HIDDEN, init_name)
    _exact(initialization, "parameter_count", launcher.PARAMETER_COUNT, init_name)
    _exact(initialization, "seed", seed, init_name)
    _exact(initialization, "constructed_before_first_update", True, init_name)
    _sha(initialization.get("parameter_digest"), f"{init_name}.parameter_digest")
    normalization = _mapping(
        evidence.get("normalization"), "training_receipt.evidence.normalization"
    )
    norm_name = "training_receipt.evidence.normalization"
    _exact(normalization, "schema", "core.training.normalization_evidence.v1", norm_name)
    _exact(normalization, "requested_maximum_transitions", 16, norm_name)
    _exact(normalization, "selected_transition_count", 16, norm_name)
    _exact(normalization, "selection_seed", seed, norm_name)
    _exact(normalization, "source_split", "train", norm_name)
    _exact(normalization, "target_reference", "raw_dual_increment_train_shared", norm_name)
    prior = _mapping(evidence.get("residual_prior"), "training_receipt.evidence.residual_prior")
    prior_name = "training_receipt.evidence.residual_prior"
    _exact(prior, "schema", "core.training.prior_evidence.v1", prior_name)
    _exact(prior, "enabled", True, prior_name)
    _exact(prior, "history_complete", True, prior_name)
    _exact(prior, "execution_calls", UPDATES, prior_name)
    _exact(prior, "rows", 17_280_000, prior_name)
    _exact(prior, "finite", True, prior_name)
    if _string(source.get("path"), "training_receipt.source.path") != str(receipt_path):
        _fail("training_receipt source path changed during bounded read")
    return {
        "path": str(receipt_path),
        "sha256": _sha(source.get("sha256"), "training_receipt.source.sha256"),
        "bytes": _int(source.get("bytes"), "training_receipt.source.bytes", 1),
        "schema": launcher.TRAINING_SCHEMA,
        "run_id": run_id,
        "seed": seed,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "manifest_sha256": manifest_sha256,
        "checkpoint": {
            "schema": launcher.CHECKPOINT_SCHEMA,
            "path": str(declared_checkpoint),
            "sha256": checkpoint_sha,
            "bytes": checkpoint_bytes,
            "update": UPDATES,
        },
    }


def _build_current_manifest_plan(
    root: Path | str,
    *,
    seed: int,
    manifest: Path | str,
    checkpoint: Path | str,
    training_receipt: Path | str,
    run_id: str,
    nonce: str,
    output_namespace: Path | str,
    gpu_index: int,
    python_executable: Path | str | None,
) -> Any:
    """Construct the launcher's plan with the current receipt adapter."""

    root_path = launcher._root_path(root)
    if seed not in SEEDS:
        _fail(f"seed must be one of {SEEDS}")
    if launcher.RUN_ID_RE.fullmatch(run_id) is None:
        _fail("run_id is not the explicit current-manifest v3 identity")
    if type(gpu_index) is not int or not 0 <= gpu_index < GPU_COUNT:
        _fail(f"gpu_index must be an integer in [0, {GPU_COUNT})")
    manifest_path = launcher._absolute_path(manifest, "manifest", root=root_path)
    if manifest_path != root_path / launcher.MANIFEST_RELATIVE:
        _fail("manifest path is not the fixed current canonical manifest")
    manifest_payload, manifest_source = launcher._read_bounded_json(
        manifest_path, root=root_path, name="manifest", limit=launcher.MAX_MANIFEST_BYTES
    )
    manifest_binding = launcher._manifest_binding(manifest_payload, manifest_source, path=manifest_path)
    training_path = launcher._absolute_path(training_receipt, "training_receipt", root=root_path)
    checkpoint_path = launcher._absolute_path(checkpoint, "checkpoint", root=root_path)
    if training_path.name != f"{run_id}-training.json":
        _fail("training_receipt filename does not bind the explicit v3 run_id")
    if checkpoint_path.name != f"{run_id}-checkpoint.pt":
        _fail("checkpoint filename does not bind the explicit v3 run_id")
    training_payload, training_source = launcher._read_bounded_json(
        training_path, root=root_path, name="training_receipt", limit=launcher.MAX_JSON_BYTES
    )
    training_binding = _validate_current_training_receipt(
        training_payload,
        training_source,
        receipt_path=training_path,
        checkpoint_path=checkpoint_path,
        seed=seed,
        run_id=run_id,
        manifest_sha256=manifest_binding["canonical_sha256"],
    )
    nonce = _validate_nonce(nonce, "nonce")
    namespace = launcher._namespace(
        seed,
        nonce,
        launcher._absolute_path(output_namespace, "output_namespace"),
        root_path,
    )
    outputs = launcher._output_paths(namespace, root_path, seed, nonce)
    launcher._check_output_collisions(outputs, root_path)
    python = launcher._absolute_path(
        python_executable if python_executable is not None else root_path / ".venv" / "bin" / "python",
        "python_executable",
        root=root_path,
    )
    core_learning = root_path / "scripts" / "core_learning.py"
    launcher._metadata_only(python, "Python executable", allow_leaf_symlink=True)
    launcher._metadata_only(core_learning, "core_learning.py")
    command = launcher._build_command(
        root=root_path,
        python=python,
        manifest=manifest_path,
        checkpoint=checkpoint_path,
        outputs=outputs,
    )
    env = {"CUDA_VISIBLE_DEVICES": str(gpu_index), "PYTHONDONTWRITEBYTECODE": "1"}
    command_sha256 = launcher._command_digest(command, cwd=root_path, env=env)
    return launcher.CurrentManifestRolloutPlan(
        root=root_path,
        seed=seed,
        run_id=run_id,
        nonce=nonce,
        manifest=manifest_path,
        manifest_binding=manifest_binding,
        training_receipt=training_path,
        training_binding=training_binding,
        checkpoint_path=checkpoint_path,
        checkpoint=training_binding["checkpoint"],
        output_namespace=namespace,
        outputs=outputs,
        command=command,
        cwd=root_path,
        env=env,
        command_sha256=command_sha256,
        gpu_index=gpu_index,
    )


def execute_plan(plan: AuditedPlan) -> dict[str, Any]:
    """Reject every execution request without an injectable authority seam.

    This diagnostic module intentionally has no capability object, no
    ``popen_factory`` parameter, and no subprocess execution path.  A future
    trusted runtime may produce a sealed witness in a separate integration;
    a caller cannot manufacture one by importing this module.
    """

    del plan
    _fail(
        f"{TERMINAL_CAPABILITY_SCHEMA} is not implemented/admitted; "
        "no evaluator was started and no Popen/wait witness can be minted here"
    )


ARTIFACT_KEYS = frozenset({"path", "sha256", "bytes"})
PROCESS_KEYS = frozenset(
    {
        "schema",
        "producer",
        "evidence_kind",
        "synthetic",
        "popen_called",
        "wait_called",
        "wait_returncode",
        "exit_status_verified",
        "plan_digest",
        "manifest_sha256",
        "training_receipt_sha256",
        "checkpoint",
        "namespace",
        "namespace_nonce",
        "command_sha256",
        "cwd",
        "env",
        "argv",
        "sealed_lifecycle",
    }
)
SEALED_LIFECYCLE_KEYS = frozenset(
    {
        "schema",
        "producer",
        "sealed",
        "popen_called",
        "wait_called",
        "wait_returncode",
        "reaped",
        "natural_exit",
        "argv",
        "cwd",
        "env",
        "binding_sha256",
    }
)
VALIDATOR_KEYS = frozenset(
    {
        "schema",
        "producer",
        "independent",
        "synthetic",
        "passed",
        "complete",
        "hdf5_content_opened",
        "trajectory_content_opened",
        "expected_transitions",
        "frames_executed",
        "trajectory_transitions",
        "trajectory_frames",
        "tail_frame_count",
        "trajectory_artifact",
        "evaluation_artifact",
        "validator_returncode",
    }
)
EVIDENCE_KEYS = frozenset(
    {
        "schema",
        "status",
        "seed",
        "run_id",
        "namespace",
        "namespace_nonce",
        "namespace_fresh",
        "model_kind",
        "hidden",
        "updates",
        "case_id",
        "split",
        "transitions",
        "frames",
        "plan_digest",
        "manifest_sha256",
        "training_receipt_sha256",
        "checkpoint",
        "command_sha256",
        "process_proof",
        "evaluation_artifact",
        "trajectory_artifact",
        "hdf5_validator",
    }
)


def _artifact(
    value: Any,
    *,
    expected_path: Path,
    name: str,
    verify_snapshot: bool = False,
    hdf5: bool = False,
) -> dict[str, Any]:
    item = _mapping(value, name)
    _unknown(item, ARTIFACT_KEYS, name)
    path = _absolute_path(item.get("path"), f"{name}.path")
    if path != expected_path:
        _fail(f"{name}.path is not bound to the fresh audited plan")
    result = {
        "path": str(path),
        "sha256": _sha(item.get("sha256"), f"{name}.sha256"),
        "bytes": _int(item.get("bytes"), f"{name}.bytes", 1),
    }
    if verify_snapshot:
        read_bound_artifact(
            path,
            expected_sha256=result["sha256"],
            expected_bytes=result["bytes"],
            name=name,
            hdf5=hdf5,
        )
    return result


def _validate_plan_input_snapshots(plan: AuditedPlan) -> None:
    """Re-bind all plan source files before any terminal identity is considered."""

    read_bound_artifact(
        plan.base.manifest,
        expected_sha256=plan.base.manifest_binding["raw_sha256"],
        expected_bytes=plan.base.manifest_binding["bytes"],
        name="audited_plan.manifest",
    )
    read_bound_artifact(
        plan.base.training_receipt,
        expected_sha256=plan.base.training_binding["sha256"],
        expected_bytes=plan.base.training_binding["bytes"],
        name="audited_plan.training_receipt",
    )
    read_bound_artifact(
        plan.base.checkpoint["path"],
        expected_sha256=plan.base.checkpoint["sha256"],
        expected_bytes=plan.base.checkpoint["bytes"],
        name="audited_plan.checkpoint",
    )


def _validate_process_proof(value: Any, plan: AuditedPlan) -> dict[str, Any]:
    proof = _mapping(value, "process_proof")
    _unknown(proof, PROCESS_KEYS, "process_proof")
    _exact(proof, "schema", PROCESS_PROOF_SCHEMA, "process_proof")
    _exact(proof, "producer", "subprocess.Popen", "process_proof")
    _exact(proof, "evidence_kind", "runtime_process_observation", "process_proof")
    _exact(proof, "synthetic", False, "process_proof")
    _exact(proof, "popen_called", True, "process_proof")
    _exact(proof, "wait_called", True, "process_proof")
    _exact(proof, "wait_returncode", 0, "process_proof")
    _exact(proof, "exit_status_verified", True, "process_proof")
    _exact(proof, "plan_digest", plan.plan_digest, "process_proof")
    _exact(
        proof,
        "manifest_sha256",
        plan.base.manifest_binding["canonical_sha256"],
        "process_proof",
    )
    _exact(proof, "training_receipt_sha256", plan.base.training_binding["sha256"], "process_proof")
    _exact(proof, "namespace", str(plan.namespace), "process_proof")
    _exact(proof, "namespace_nonce", plan.nonce, "process_proof")
    _exact(proof, "command_sha256", plan.base.command_sha256, "process_proof")
    _exact(proof, "cwd", str(plan.base.cwd), "process_proof")
    environment = _mapping(proof.get("env"), "process_proof.env")
    _unknown(environment, frozenset(plan.base.env), "process_proof.env")
    if dict(environment) != dict(plan.base.env):
        _fail("process_proof.env drifted from the audited launch environment")
    checkpoint = _artifact(
        proof.get("checkpoint"),
        expected_path=Path(plan.base.checkpoint["path"]),
        name="process_proof.checkpoint",
    )
    if checkpoint != {
        key: plan.base.checkpoint[key] for key in ("path", "sha256", "bytes")
    }:
        _fail("process_proof.checkpoint drifted from the audited training identity")
    if list(proof.get("argv", [])) != list(plan.base.command):
        _fail("process_proof.argv drifted from the exact audited command")
    lifecycle = _mapping(proof.get("sealed_lifecycle"), "process_proof.sealed_lifecycle")
    _unknown(lifecycle, SEALED_LIFECYCLE_KEYS, "process_proof.sealed_lifecycle")
    _exact(lifecycle, "schema", SEALED_LIFECYCLE_SCHEMA, "process_proof.sealed_lifecycle")
    _exact(lifecycle, "producer", "audited_runtime_sealed_witness", "process_proof.sealed_lifecycle")
    _exact(lifecycle, "sealed", True, "process_proof.sealed_lifecycle")
    _exact(lifecycle, "popen_called", True, "process_proof.sealed_lifecycle")
    _exact(lifecycle, "wait_called", True, "process_proof.sealed_lifecycle")
    _exact(lifecycle, "wait_returncode", 0, "process_proof.sealed_lifecycle")
    _exact(lifecycle, "reaped", True, "process_proof.sealed_lifecycle")
    _exact(lifecycle, "natural_exit", True, "process_proof.sealed_lifecycle")
    if list(lifecycle.get("argv", [])) != list(plan.base.command):
        _fail("process_proof.sealed_lifecycle.argv drifted from the audited command")
    _exact(lifecycle, "cwd", str(plan.base.cwd), "process_proof.sealed_lifecycle")
    lifecycle_env = _mapping(lifecycle.get("env"), "process_proof.sealed_lifecycle.env")
    _unknown(lifecycle_env, frozenset(plan.base.env), "process_proof.sealed_lifecycle.env")
    if dict(lifecycle_env) != dict(plan.base.env):
        _fail("process_proof.sealed_lifecycle.env drifted from the audited environment")
    lifecycle_binding = {
        "schema": SEALED_LIFECYCLE_SCHEMA,
        "producer": "audited_runtime_sealed_witness",
        "sealed": True,
        "popen_called": True,
        "wait_called": True,
        "wait_returncode": 0,
        "reaped": True,
        "natural_exit": True,
        "argv": list(plan.base.command),
        "cwd": str(plan.base.cwd),
        "env": dict(plan.base.env),
        "plan_digest": plan.plan_digest,
        "manifest_sha256": plan.base.manifest_binding["canonical_sha256"],
        "training_receipt_sha256": plan.base.training_binding["sha256"],
        "checkpoint": checkpoint,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
    }
    _exact(
        lifecycle,
        "binding_sha256",
        canonical_digest(lifecycle_binding),
        "process_proof.sealed_lifecycle",
    )
    _fail(
        "process proof is declaration-only; no in-memory sealed real Popen/wait "
        "witness is admitted by the residual identity boundary"
    )


def _validate_hdf5_validator(value: Any, plan: AuditedPlan, trajectory: Mapping[str, Any], evaluation: Mapping[str, Any]) -> dict[str, Any]:
    validator = _mapping(value, "hdf5_validator")
    _unknown(validator, VALIDATOR_KEYS, "hdf5_validator")
    _exact(validator, "schema", HDF5_VALIDATOR_SCHEMA, "hdf5_validator")
    _exact(validator, "producer", "independent_hdf5_validator", "hdf5_validator")
    _exact(validator, "independent", True, "hdf5_validator")
    _exact(validator, "synthetic", False, "hdf5_validator")
    _exact(validator, "passed", True, "hdf5_validator")
    _exact(validator, "complete", True, "hdf5_validator")
    _exact(validator, "hdf5_content_opened", True, "hdf5_validator")
    _exact(validator, "trajectory_content_opened", True, "hdf5_validator")
    _exact(validator, "expected_transitions", TRANSITIONS, "hdf5_validator")
    _exact(validator, "frames_executed", FRAMES, "hdf5_validator")
    _exact(validator, "trajectory_transitions", TRANSITIONS, "hdf5_validator")
    _exact(validator, "trajectory_frames", FRAMES, "hdf5_validator")
    _exact(validator, "tail_frame_count", 1, "hdf5_validator")
    _exact(validator, "validator_returncode", 0, "hdf5_validator")
    validator_trajectory = _artifact(
        validator.get("trajectory_artifact"),
        expected_path=Path(trajectory["path"]),
        name="hdf5_validator.trajectory_artifact",
    )
    validator_evaluation = _artifact(
        validator.get("evaluation_artifact"),
        expected_path=Path(evaluation["path"]),
        name="hdf5_validator.evaluation_artifact",
    )
    if validator_trajectory != dict(trajectory):
        _fail("hdf5_validator.trajectory_artifact differs from trajectory identity")
    if validator_evaluation != dict(evaluation):
        _fail("hdf5_validator.evaluation_artifact differs from evaluation identity")
    return {**dict(validator), "trajectory_artifact": validator_trajectory, "evaluation_artifact": validator_evaluation}


def validate_terminal_artifact_identity(
    evidence: Mapping[str, Any],
    plan: AuditedPlan,
) -> dict[str, Any]:
    """Validate one future terminal envelope behind a sealed-runtime gate."""

    _walk_json(evidence, "terminal_evidence")
    _unknown(evidence, EVIDENCE_KEYS, "terminal_evidence")
    _exact(evidence, "schema", SCHEMA, "terminal_evidence")
    _exact(evidence, "status", "terminal_identity_candidate", "terminal_evidence")
    _exact(evidence, "seed", plan.seed, "terminal_evidence")
    _exact(evidence, "run_id", plan.base.run_id, "terminal_evidence")
    _exact(evidence, "namespace", str(plan.namespace), "terminal_evidence")
    _exact(evidence, "namespace_nonce", plan.nonce, "terminal_evidence")
    _exact(evidence, "namespace_fresh", True, "terminal_evidence")
    _exact(evidence, "model_kind", MODEL, "terminal_evidence")
    _exact(evidence, "hidden", HIDDEN, "terminal_evidence")
    _exact(evidence, "updates", UPDATES, "terminal_evidence")
    _exact(evidence, "case_id", CASE_ID, "terminal_evidence")
    _exact(evidence, "split", SPLIT, "terminal_evidence")
    _exact(evidence, "transitions", TRANSITIONS, "terminal_evidence")
    _exact(evidence, "frames", FRAMES, "terminal_evidence")
    _exact(evidence, "plan_digest", plan.plan_digest, "terminal_evidence")
    _exact(evidence, "manifest_sha256", plan.base.manifest_binding["canonical_sha256"], "terminal_evidence")
    _exact(evidence, "training_receipt_sha256", plan.base.training_binding["sha256"], "terminal_evidence")
    _exact(evidence, "command_sha256", plan.base.command_sha256, "terminal_evidence")
    _validate_plan_input_snapshots(plan)
    checkpoint = _mapping(evidence.get("checkpoint"), "terminal_evidence.checkpoint")
    _unknown(checkpoint, ARTIFACT_KEYS | frozenset({"schema", "update"}), "terminal_evidence.checkpoint")
    _exact(checkpoint, "schema", launcher.CHECKPOINT_SCHEMA, "terminal_evidence.checkpoint")
    _exact(checkpoint, "update", UPDATES, "terminal_evidence.checkpoint")
    expected_checkpoint = dict(plan.base.checkpoint)
    checkpoint_identity = _artifact(
        {key: checkpoint[key] for key in ARTIFACT_KEYS},
        expected_path=Path(expected_checkpoint["path"]),
        name="terminal_evidence.checkpoint",
    )
    for key in ("sha256", "bytes"):
        if checkpoint_identity[key] != expected_checkpoint[key]:
            _fail(f"terminal_evidence.checkpoint.{key} differs from training identity")
    read_bound_artifact(
        checkpoint_identity["path"],
        expected_sha256=checkpoint_identity["sha256"],
        expected_bytes=checkpoint_identity["bytes"],
        name="terminal_evidence.checkpoint",
    )
    evaluation = _artifact(
        evidence.get("evaluation_artifact"),
        expected_path=plan.outputs["evaluation"],
        name="terminal_evidence.evaluation_artifact",
        verify_snapshot=True,
    )
    trajectory = _artifact(
        evidence.get("trajectory_artifact"),
        expected_path=plan.outputs["trajectory"],
        name="terminal_evidence.trajectory_artifact",
        verify_snapshot=True,
        hdf5=True,
    )
    validator = _validate_hdf5_validator(
        evidence.get("hdf5_validator"), plan, trajectory, evaluation
    )
    process = _validate_process_proof(evidence.get("process_proof"), plan)
    return {
        "schema": SCHEMA,
        "seed": plan.seed,
        "run_id": plan.base.run_id,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.nonce,
        "process_proof_bound": True,
        "hdf5_validator_bound": True,
        "artifact_identity_bound": True,
        "terminal_identity_bound": True,
        "trusted_for_formal_credit": False,
        "process_proof": process,
        "hdf5_validator": validator,
        "evaluation_artifact": evaluation,
        "trajectory_artifact": trajectory,
        **ZERO_CREDIT,
    }


def _build_rows(
    *,
    root: Path,
    manifest: Path,
    receipts: Mapping[int, Path],
    checkpoints: Mapping[int, Path],
    nonces: Mapping[int, str],
    gpu_indices: Mapping[int, int],
    output_root: Path,
    admission_kwargs: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[AuditedPlan]]:
    rows: list[dict[str, Any]] = []
    plans: list[AuditedPlan] = []
    for seed in SEEDS:
        gpu = gpu_indices[seed]
        admission = probe_resource_admission(gpu, **dict(admission_kwargs))
        namespace = _fresh_namespace(seed, nonces[seed], output_root)
        try:
            plan = build_audited_plan(
                root,
                seed=seed,
                manifest=manifest,
                training_receipt=receipts[seed],
                checkpoint=checkpoints[seed],
                run_id=_expected_run_id(seed),
                nonce=nonces[seed],
                output_namespace=namespace,
                gpu_index=gpu,
                admission=admission,
            )
            plans.append(plan)
            rows.append(
                {
                    "seed": seed,
                    "status": "blocked_fail_closed",
                    "source_bound": True,
                    "run_id": plan.base.run_id,
                    "manifest_sha256": plan.base.manifest_binding["canonical_sha256"],
                    "training_receipt_sha256": plan.base.training_binding["sha256"],
                    "checkpoint": dict(plan.base.checkpoint),
                    "namespace": str(plan.namespace),
                    "namespace_nonce": plan.nonce,
                    "fresh_namespace": True,
                    "gpu_index": gpu,
                    "resource_admission": dict(admission),
                    "command_sha256": plan.base.command_sha256,
                    "plan_digest": plan.plan_digest,
                    "process_proof": None,
                    "hdf5_validator": None,
                    "terminal_artifact_identity": None,
                    "launch_allowed": False,
                    "blocked_reasons": [
                        f"{TERMINAL_CAPABILITY_SCHEMA} is not implemented/admitted",
                        "no evaluator was started and no terminal artifact receipt was minted",
                    ]
                    + list(admission.get("blocked_reasons", [])),
                }
            )
        except (IdentityError, launcher.LauncherError, OSError, ValueError) as error:
            rows.append(
                {
                    "seed": seed,
                    "status": "blocked_fail_closed",
                    "source_bound": False,
                    "run_id": _expected_run_id(seed),
                    "namespace": str(namespace),
                    "namespace_nonce": nonces[seed],
                    "gpu_index": gpu,
                    "resource_admission": dict(admission),
                    "process_proof": None,
                    "hdf5_validator": None,
                    "terminal_artifact_identity": None,
                    "launch_allowed": False,
                    "blocked_reasons": [str(error)],
                }
            )
    return rows, plans


def build_report(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipts: Mapping[int, Path | str] = DEFAULT_RECEIPTS,
    checkpoints: Mapping[int, Path | str] = DEFAULT_CHECKPOINTS,
    nonces: Mapping[int, str] | None = None,
    gpu_indices: Mapping[int, int] | None = None,
    output_root: Path | str = "/tmp",
    gpu_rows: Mapping[int, Mapping[str, Any]] | None = None,
    probe_errors: Sequence[str] = (),
    cpu_count: int | None = None,
    load_1m: float | None = None,
    tmp_free_bytes: int | None = None,
    root_free_bytes: int | None = None,
) -> dict[str, Any]:
    root_path = _absolute_path(root, "root")
    manifest_path = _absolute_path(manifest, "manifest")
    if set(training_receipts) != set(SEEDS) or set(checkpoints) != set(SEEDS):
        _fail(f"training_receipts and checkpoints must cover exactly {SEEDS}")
    selected_nonces = {
        seed: _validate_nonce(
            (nonces or {}).get(seed, secrets.token_hex(16)), f"nonce.seed{seed}"
        )
        for seed in SEEDS
    }
    if len(set(selected_nonces.values())) != len(SEEDS):
        _fail("per-seed nonces must be unique")
    selected_gpus = {
        seed: int((gpu_indices or DEFAULT_GPU_INDICES).get(seed, DEFAULT_GPU_INDICES[seed]))
        for seed in SEEDS
    }
    if len(set(selected_gpus.values())) != len(SEEDS):
        _fail("per-seed GPU assignments must be unique")
    rows, plans = _build_rows(
        root=root_path,
        manifest=manifest_path,
        receipts={seed: _absolute_path(training_receipts[seed], f"training_receipt.seed{seed}") for seed in SEEDS},
        checkpoints={seed: _absolute_path(checkpoints[seed], f"checkpoint.seed{seed}") for seed in SEEDS},
        nonces=selected_nonces,
        gpu_indices=selected_gpus,
        output_root=_absolute_path(output_root, "output_root"),
        admission_kwargs={
            "gpu_rows": gpu_rows,
            "probe_errors": probe_errors,
            "cpu_count": cpu_count,
            "load_1m": load_1m,
            "tmp_free_bytes": tmp_free_bytes,
            "root_free_bytes": root_free_bytes,
        },
    )
    report = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "blocked_fail_closed",
        "mode": "terminal_artifact_identity_canary_boundary",
        "source_bound": len(plans) == len(SEEDS),
        "launch_allowed": False,
        "terminal_capability_admitted": False,
        "process_proofs_verified": 0,
        "process_proofs_expected": len(SEEDS),
        "hdf5_validators_verified": 0,
        "hdf5_validators_expected": len(SEEDS),
        "terminal_artifacts_verified": 0,
        "terminal_artifacts_expected": len(SEEDS),
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
            "real_popen_wait_proof_required": True,
            "independent_hdf5_validator_required": True,
            "diagnostic_only": True,
            "zero_credit_only": True,
        },
        "seed_rows": rows,
        "blocked_reasons": sorted(
            {
                f"{TERMINAL_CAPABILITY_SCHEMA} is not implemented/admitted",
                "no evaluator was started and no terminal artifact receipt was minted",
                "independent HDF5 validator receipt is absent",
            }
            | {
                reason
                for row in rows
                for reason in row.get("blocked_reasons", [])
                if "GPU" in reason or "CPU" in reason or "space" in reason
            }
        ),
        "input_boundary": {
            "bounded_manifest_and_training_json": True,
            "checkpoint_metadata_stat_only": True,
            "evaluation_content_opened": False,
            "trajectory_hdf5_content_opened": False,
            "hdf5_validator_content_opened_by_this_contract": False,
            "resource_probe_content_opened": False,
            "runtime_started": False,
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
            "synthetic_receipts_minted": 0,
        },
        **ZERO_CREDIT,
    }
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _unknown(
            report,
            {
                "schema",
                "report_id",
                "observed_at_utc",
                "status",
                "mode",
                "source_bound",
                "launch_allowed",
                "terminal_capability_admitted",
                "process_proofs_verified",
                "process_proofs_expected",
                "hdf5_validators_verified",
                "hdf5_validators_expected",
                "terminal_artifacts_verified",
                "terminal_artifacts_expected",
                "expected_contract",
                "seed_rows",
                "blocked_reasons",
                "input_boundary",
                "side_effects",
                *ZERO_CREDIT,
            },
            "report",
        )
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        _exact(report, "launch_allowed", False, "report")
        _exact(report, "terminal_capability_admitted", False, "report")
        for key in (
            "process_proofs_verified",
            "hdf5_validators_verified",
            "terminal_artifacts_verified",
        ):
            _exact(report, key, 0, "report")
        for key in (
            "process_proofs_expected",
            "hdf5_validators_expected",
            "terminal_artifacts_expected",
        ):
            _exact(report, key, len(SEEDS), "report")
        _zero_credit(report, "report")
        expected = _mapping(report.get("expected_contract"), "report.expected_contract")
        for key, value in {
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "seeds": list(SEEDS),
            "fresh_32_hex_nonce": True,
            "real_popen_wait_proof_required": True,
            "independent_hdf5_validator_required": True,
            "diagnostic_only": True,
            "zero_credit_only": True,
        }.items():
            _exact(expected, key, value, "report.expected_contract")
        rows = report.get("seed_rows")
        if not isinstance(rows, list) or len(rows) != len(SEEDS):
            _fail("report.seed_rows must contain exactly three rows")
        if sorted(row.get("seed") for row in rows if isinstance(row, Mapping)) != list(SEEDS):
            _fail("report.seed_rows has the wrong seed set")
        for row in rows:
            if not isinstance(row, Mapping):
                _fail("report.seed_rows contains a non-object")
            _exact(row, "status", "blocked_fail_closed", f"seed{row.get('seed')}")
            _exact(row, "launch_allowed", False, f"seed{row.get('seed')}")
            _exact(row, "process_proof", None, f"seed{row.get('seed')}")
            _exact(row, "hdf5_validator", None, f"seed{row.get('seed')}")
            _exact(row, "terminal_artifact_identity", None, f"seed{row.get('seed')}")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in (
            "runtime_started",
            "processes_started",
            "processes_stopped",
            "processes_restarted",
            "queue_submissions",
            "registry_writes",
            "ledger_writes",
            "denominator_writes",
            "gate_writes",
            "completion_writes",
            "synthetic_receipts_minted",
        ):
            if side_effects.get(key) not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
    except (IdentityError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_residual hidden16 current-manifest terminal artifact identity",
        "",
        f"- status: `{report.get('status')}`",
        f"- source_bound: `{report.get('source_bound')}`",
        "- launch_allowed: `False`; process proof/HDF5 validator/artifact identity: `0/3`",
        "- protocol: `graph_residual`, hidden `16`, updates `500`, case `F3_DEV_00_a0p903125`, split `test`, `835 transitions / 836 frames`",
        "- boundary: fresh nonce + exact command/process/HDF5 identity contract, diagnostic-only, zero-credit",
        "",
        "| seed | GPU | nonce | source bound | status |",
        "|---:|---:|---|---|---|",
    ]
    for row in report.get("seed_rows", []):
        if isinstance(row, Mapping):
            lines.append(
                f"| {row.get('seed')} | {row.get('gpu_index')} | `{row.get('namespace_nonce')}` | "
                f"`{row.get('source_bound')}` | `{row.get('status')}` |"
            )
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {item}" for item in report.get("blocked_reasons", []))
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        _fail(f"refusing to overwrite existing report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_bindings(values: Sequence[str], label: str) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for raw in values:
        if "=" not in raw:
            _fail(f"{label} binding must use SEED=PATH")
        seed_text, value = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError:
            _fail(f"{label} seed is not an integer")
        if seed not in SEEDS or seed in result:
            _fail(f"{label} seed must be unique and one of {SEEDS}")
        result[seed] = Path(value)
    if set(result) != set(SEEDS):
        _fail(f"{label} must cover exactly {SEEDS}")
    return result


def _parse_nonces(values: Sequence[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw in values:
        if "=" not in raw:
            _fail("nonce binding must use SEED=NONCE")
        seed_text, nonce = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError:
            _fail("nonce seed is not an integer")
        if seed not in SEEDS or seed in result:
            _fail(f"nonce seed must be unique and one of {SEEDS}")
        result[seed] = _validate_nonce(nonce, f"nonce.seed{seed}")
    if set(result) != set(SEEDS):
        _fail(f"nonce must cover exactly {SEEDS}")
    return result


def _parse_gpus(values: Sequence[str]) -> dict[int, int]:
    result: dict[int, int] = {}
    for raw in values:
        if "=" not in raw:
            _fail("gpu-index binding must use SEED=GPU")
        seed_text, gpu_text = raw.split("=", 1)
        try:
            seed, gpu = int(seed_text), int(gpu_text)
        except ValueError:
            _fail("gpu-index bindings must be integers")
        if seed not in SEEDS or seed in result or not 0 <= gpu < GPU_COUNT:
            _fail("gpu-index binding is invalid")
        result[seed] = gpu
    if set(result) != set(SEEDS):
        _fail(f"gpu-index must cover exactly {SEEDS}")
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--training-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--checkpoint", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--nonce", action="append", default=[], metavar="SEED=NONCE")
    parser.add_argument("--gpu-index", action="append", default=[], metavar="SEED=GPU")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--execute", action="store_true", help="always blocked until terminal capability review")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            report_path = Path(args.verify_report)
            if not report_path.is_absolute():
                cwd_candidate = Path.cwd() / report_path
                report_path = cwd_candidate if cwd_candidate.exists() else Path(args.root) / report_path
            payload, _source = _read_bounded_json(report_path, name="report")
            errors = validate_report(payload)
            if errors:
                _fail("; ".join(errors))
            print(json.dumps({"status": "verified", "report": str(report_path), "credit": 0}))
            return 0
        receipts = _parse_bindings(args.training_receipt, "training-receipt") if args.training_receipt else DEFAULT_RECEIPTS
        checkpoints = _parse_bindings(args.checkpoint, "checkpoint") if args.checkpoint else DEFAULT_CHECKPOINTS
        nonces = _parse_nonces(args.nonce) if args.nonce else None
        gpus = _parse_gpus(args.gpu_index) if args.gpu_index else None
        report = build_report(
            args.root,
            manifest=args.manifest,
            training_receipts=receipts,
            checkpoints=checkpoints,
            nonces=nonces,
            gpu_indices=gpus,
            output_root=args.output_root,
        )
        if args.execute:
            report["blocked_reasons"] = sorted(
                set(report["blocked_reasons"])
                | {"--execute cannot bypass the unadmitted terminal HDF5/artifact capability"}
            )
        if validate_report(report):
            _fail("generated report failed self-validation")
        _write_json(args.report_output, report)
        if args.markdown_output.exists():
            _fail(f"refusing to overwrite existing markdown report: {args.markdown_output}")
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (IdentityError, launcher.LauncherError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked_fail_closed", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
