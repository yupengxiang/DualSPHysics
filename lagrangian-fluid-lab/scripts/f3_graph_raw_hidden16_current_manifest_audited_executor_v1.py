#!/usr/bin/env python3
"""Audited, diagnostic-only executor boundary for one F3 graph_raw canary.

This file is intentionally additive.  It does not change the existing
graph_raw matrix/intake contracts, Core registry, ledger, denominator, gate,
completion snapshot, or PLAN history.

The boundary is split into four explicit stages:

1. reuse the bounded current-manifest identity contract to bind the three
   graph_raw seed receipts and their declared checkpoints;
2. capture fresh per-seed namespaces, exact evaluator argv/env digests, and a
   read-only GPU/CPU/I/O admission snapshot;
3. re-check every input and output identity immediately before a future
   execution; and
4. only after a separately reviewed terminal HDF5/artifact capability exists,
   call the real ``subprocess.Popen`` and ``wait`` path.

The terminal capability is deliberately not implemented/admitted here.  Thus
the current report is always blocked fail-closed and no evaluator is started.
The unreachable execution path is still specified so that a future review can
prove that process evidence can only be minted from a real Popen/wait
lifecycle.  No caller-supplied PID, return code, or synthetic receipt is
accepted as process proof.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import hmac
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
from typing import Any, Callable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_raw_hidden16_current_manifest_rollout_launcher_v1 as identity


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
DEFAULT_GPU_INDICES = {17: 4, 29: 5, 43: 6}
MODEL = identity.MODEL
HIDDEN = identity.HIDDEN
UPDATES = identity.UPDATES
CASE_ID = identity.CASE_ID
SPLIT = identity.SPLIT
TRANSITIONS = identity.TRANSITIONS
FRAMES = identity.FRAMES
GPU_COUNT = identity.GPU_COUNT

SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.audited_executor_canary.v1"
PLAN_SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.audited_executor_plan.v1"
ADMISSION_SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.resource_admission.v1"
PROCESS_PROOF_SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.process_proof.v1"
REPORT_SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.audited_executor_report.v1"
REPORT_ID = "f3-graph-raw-hidden16-current-manifest-audited-executor-canary-v1"
TERMINAL_CAPABILITY_SCHEMA = (
    "core.f3.graph_raw.hidden16.current_manifest.terminal_hdf5_artifact_capability.v1"
)

DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_RECEIPTS = {
    seed: Path(
        f"/tmp/f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json"
    )
    for seed in SEEDS
}
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-AUDITED-EXECUTOR-CANARY-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")

# These are admission thresholds, not claims about formal capacity.  A plan
# can be built when a threshold is not met, but it can never be executed.
MIN_GPU_FREE_MIB = 8 * 1024
MIN_CPU_COUNT = 4
MAX_LOAD_PER_CPU = 2.0
MIN_DISK_FREE_BYTES = 2 * 1024**3

# Capture the real implementation once.  The execution seam is deliberately
# not injectable: a caller that replaces ``subprocess.Popen`` after import,
# or passes a factory argument, must never be able to mint process evidence.
_REAL_POPEN = subprocess.Popen
_PROCESS_RECORD_SECRET = secrets.token_bytes(32)

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

ALLOWED_AUTHORITY_KEYS = frozenset(
    {
        "diagnostic_only",
        "zero_credit_only",
        "formal",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
        "qualification_credit",
        "credit",
        "launch_allowed",
        "runtime_started",
        "processes_started",
        "processes_stopped",
        "processes_restarted",
        "process_exit",
        "process_exit_proof",
        "terminal_receipt",
        "validator_receipt",
        "validator_artifact",
        "artifact_identity",
        "source_bound",
    }
)


class ExecutorError(ValueError):
    """Malformed, drifting, unsafe, or authorizing input."""


def _fail(message: str) -> None:
    raise ExecutorError(f"fail-closed: {message}")


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
    """Reject unknown fields that could be mistaken for authority/proof."""

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


def _is_under(path: Path, roots: Sequence[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


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


def _regular_identity(path: Path, name: str, *, allow_leaf_symlink: bool = False) -> dict[str, Any]:
    _reject_symlink_components(path.parent, f"{name} parent")
    try:
        leaf = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    target_path = path
    if stat.S_ISLNK(leaf.st_mode):
        if not allow_leaf_symlink:
            _fail(f"{name} is a symlink")
        try:
            target_path = path.resolve(strict=True)
        except OSError as error:
            _fail(f"cannot resolve {name}: {error}")
        _reject_symlink_components(target_path.parent, f"{name} target parent")
    try:
        target = os.stat(target_path)
        parent = os.stat(path.parent)
    except OSError as error:
        _fail(f"cannot stat {name}: {error}")
    if not stat.S_ISREG(target.st_mode) or target.st_nlink != 1:
        _fail(f"{name} must resolve to a regular single-link file")
    return {
        "path": str(path),
        "leaf": {
            "dev": int(leaf.st_dev),
            "ino": int(leaf.st_ino),
            "mode": int(stat.S_IMODE(leaf.st_mode)),
            "nlink": int(leaf.st_nlink),
            "size": int(leaf.st_size),
            "mtime_ns": int(leaf.st_mtime_ns),
        },
        "target_path": str(target_path),
        "target": {
            "dev": int(target.st_dev),
            "ino": int(target.st_ino),
            "mode": int(stat.S_IMODE(target.st_mode)),
            "nlink": int(target.st_nlink),
            "size": int(target.st_size),
            "mtime_ns": int(target.st_mtime_ns),
        },
        "parent": {
            "dev": int(parent.st_dev),
            "ino": int(parent.st_ino),
            "mode": int(stat.S_IMODE(parent.st_mode)),
            "nlink": int(parent.st_nlink),
        },
        "allow_leaf_symlink": bool(allow_leaf_symlink),
    }


def _assert_snapshot(snapshot: Mapping[str, Any], name: str) -> None:
    path = _absolute_path(snapshot.get("path"), f"{name}.path")
    current = _regular_identity(
        path,
        name,
        allow_leaf_symlink=bool(snapshot.get("allow_leaf_symlink", False)),
    )
    if current != dict(snapshot):
        _fail(f"{name} changed after the audited plan was built")


def _read_bounded_json(path: Path | str, *, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = _absolute_path(path, name)
    _reject_symlink_components(candidate, name)
    try:
        before = os.lstat(candidate)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{name} must be a regular single-link file")
        if before.st_size > MAX_JSON_BYTES:
            _fail(f"{name} exceeds bounded size {MAX_JSON_BYTES}")
        fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    try:
        opened = os.fstat(fd)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_opened = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        if identity_opened != identity_before:
            _fail(f"{name} changed before bounded read")
        raw = os.read(fd, MAX_JSON_BYTES + 1)
        closed = os.fstat(fd)
        identity_closed = (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns)
        if identity_closed != identity_before or len(raw) != before.st_size:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name} after bounded read: {error}")
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity_before:
        _fail(f"{name} changed after bounded read")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ExecutorError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    _walk_json(payload, name)
    if not isinstance(payload, dict):
        _fail(f"{name} must contain a JSON object")
    _reject_authority_aliases(payload, name)
    return payload, {
        "path": str(candidate),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload.get("schema"),
    }


def _query_gpu_rows() -> tuple[dict[int, dict[str, int]], list[str]]:
    command = (
        "nvidia-smi",
        "--query-gpu=index,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    )
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
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
            errors.append(f"nvidia-smi returned an invalid GPU row for index {index}")
            continue
        rows[index] = {"total_mib": total, "used_mib": used, "free_mib": free}
    if not rows:
        errors.append("nvidia-smi returned no usable GPU rows")
    return rows, errors


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
    reasons = list(probe_errors)
    if gpu_row is None:
        reasons.append(f"GPU {gpu_index} is absent from the bounded VRAM probe")
        gpu = {"total_mib": 0, "used_mib": 0, "free_mib": 0}
    else:
        gpu = {
            "total_mib": _int(gpu_row.get("total_mib"), "gpu.total_mib"),
            "used_mib": _int(gpu_row.get("used_mib"), "gpu.used_mib"),
            "free_mib": _int(gpu_row.get("free_mib"), "gpu.free_mib"),
        }
        if gpu["used_mib"] + gpu["free_mib"] > gpu["total_mib"]:
            _fail("GPU used/free memory exceeds total memory")
    if gpu["free_mib"] < MIN_GPU_FREE_MIB:
        reasons.append(
            f"GPU {gpu_index} free VRAM {gpu['free_mib']} MiB is below {MIN_GPU_FREE_MIB} MiB"
        )
    if cpu_count < MIN_CPU_COUNT:
        reasons.append(f"CPU count {cpu_count} is below {MIN_CPU_COUNT}")
    if not math.isfinite(load_1m) or load_1m < 0:
        reasons.append("CPU load average is not finite and non-negative")
        load_per_cpu = float("inf")
    else:
        load_per_cpu = load_1m / max(cpu_count, 1)
        if load_per_cpu > MAX_LOAD_PER_CPU:
            reasons.append(
                f"CPU load per logical core {load_per_cpu:.6f} exceeds {MAX_LOAD_PER_CPU}"
            )
    if tmp_free_bytes < MIN_DISK_FREE_BYTES:
        reasons.append("/tmp free space is below the bounded I/O admission threshold")
    if root_free_bytes < MIN_DISK_FREE_BYTES:
        reasons.append("root free space is below the bounded I/O admission threshold")
    return {
        "schema": ADMISSION_SCHEMA,
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
        "thresholds": {
            "minimum_gpu_free_mib": MIN_GPU_FREE_MIB,
            "minimum_cpu_count": MIN_CPU_COUNT,
            "maximum_load_per_logical_core": MAX_LOAD_PER_CPU,
        },
        "status": "admitted" if not reasons else "blocked",
        "admitted": not reasons,
        "blocked_reasons": reasons,
        "content_opened": False,
    }


def probe_resource_admission(
    gpu_index: int,
    *,
    root: Path | str = LAB_ROOT,
    gpu_rows: Mapping[int, Mapping[str, Any]] | None = None,
    probe_errors: Sequence[str] = (),
    cpu_count: int | None = None,
    load_1m: float | None = None,
    tmp_free_bytes: int | None = None,
    root_free_bytes: int | None = None,
) -> dict[str, Any]:
    """Collect only bounded GPU/CPU/I/O admission metadata."""

    if type(gpu_index) is not int or not 0 <= gpu_index < GPU_COUNT:
        _fail(f"gpu_index must be an integer in [0, {GPU_COUNT})")
    root_path = _absolute_path(root, "root")
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
            root_free_bytes = int(shutil.disk_usage(root_path).free)
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


def _validate_nonce(value: Any, name: str) -> str:
    nonce = _string(value, name)
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail(f"{name} must be a non-zero 32-character lowercase hexadecimal value")
    return nonce


def _validate_namespace(namespace: Path, *, seed: int, nonce: str, fresh: bool) -> None:
    expected = f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-full835-nonce{nonce}"
    if namespace.name != expected:
        _fail("output namespace is not bound to the fixed seed/full835/nonce identity")
    if Path("/tmp") not in namespace.parents:
        _fail("output namespace must remain under /tmp")
    _reject_symlink_components(namespace.parent, "output namespace parent")
    if fresh and os.path.lexists(namespace):
        _fail(f"refusing to reuse existing output namespace: {namespace}")


def _validate_bounded_input_paths(plan: identity.RolloutPlan) -> None:
    root = plan.root
    if not _is_under(plan.manifest, (root,)):
        _fail("manifest escapes the current lab root")
    if not _is_under(plan.training_receipt, (root, Path("/tmp"))):
        _fail("training receipt escapes the bounded lab/tmp roots")
    checkpoint_path = Path(str(plan.checkpoint["path"]))
    if not _is_under(checkpoint_path, (root, Path("/tmp"))):
        _fail("checkpoint escapes the bounded lab/tmp roots")


@dataclass(frozen=True)
class AuditedPlan:
    identity_plan: identity.RolloutPlan
    gpu_index: int
    admission: Mapping[str, Any]
    input_snapshots: Mapping[str, Mapping[str, Any]]
    exact_command_digest: str
    audited_plan_digest: str

    @property
    def namespace(self) -> Path:
        return self.identity_plan.namespace

    @property
    def outputs(self) -> Mapping[str, Path]:
        return self.identity_plan.outputs

    def as_dict(self) -> dict[str, Any]:
        plan = self.identity_plan.as_dict()
        plan.update(
            {
                "schema": PLAN_SCHEMA,
                "status": "audited_plan_ready",
                "executor_schema": SCHEMA,
                "gpu_index": self.gpu_index,
                "admission": dict(self.admission),
                "input_snapshots": {
                    key: dict(value) for key, value in self.input_snapshots.items()
                },
                "exact_command_digest": self.exact_command_digest,
                "audited_plan_digest": self.audited_plan_digest,
                "terminal_capability_schema": TERMINAL_CAPABILITY_SCHEMA,
                "terminal_capability_admitted": False,
                "launch_allowed": False,
                **ZERO_CREDIT,
            }
        )
        return plan


def _exact_command_digest(plan: identity.RolloutPlan, gpu_index: int) -> str:
    payload = {
        "argv": list(plan.command),
        "cwd": str(plan.root),
        "env_overrides": dict(plan.env),
        "gpu_index": gpu_index,
        "model_kind": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }
    return canonical_digest(payload)


def build_audited_plan(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    manifest: Path | str,
    training_receipt: Path | str,
    checkpoint: Path | str | None,
    nonce: str,
    output_namespace: Path | str,
    gpu_index: int,
    admission: Mapping[str, Any] | None = None,
) -> AuditedPlan:
    """Bind one seed without starting a process or creating a namespace."""

    nonce = _validate_nonce(nonce, "nonce")
    plan = identity.build_plan(
        root,
        seed=seed,
        manifest=manifest,
        training_receipt=training_receipt,
        checkpoint=checkpoint,
        nonce=nonce,
        output_namespace=output_namespace,
        gpu_index=gpu_index,
    )
    _validate_bounded_input_paths(plan)
    _validate_namespace(plan.namespace, seed=seed, nonce=nonce, fresh=True)
    if admission is None:
        admission = probe_resource_admission(gpu_index, root=plan.root)
    _exact(admission, "schema", ADMISSION_SCHEMA, "admission")
    _exact(admission, "gpu_index", gpu_index, "admission")
    _bool(admission.get("admitted"), "admission.admitted")
    snapshots = {
        "python": _regular_identity(Path(plan.command[0]), "Python executable", allow_leaf_symlink=True),
        "core_learning": _regular_identity(Path(plan.command[2]), "core_learning.py"),
        "manifest": _regular_identity(plan.manifest, "manifest"),
        "training_receipt": _regular_identity(plan.training_receipt, "training receipt"),
        "checkpoint": _regular_identity(Path(str(plan.checkpoint["path"])), "checkpoint"),
    }
    exact_digest = _exact_command_digest(plan, gpu_index)
    audited_digest = canonical_digest(
        {
            "plan_schema": PLAN_SCHEMA,
            "identity_plan": plan.as_dict(),
            "input_snapshots": snapshots,
            "admission": dict(admission),
            "exact_command_digest": exact_digest,
        }
    )
    return AuditedPlan(
        identity_plan=plan,
        gpu_index=gpu_index,
        admission=dict(admission),
        input_snapshots=snapshots,
        exact_command_digest=exact_digest,
        audited_plan_digest=audited_digest,
    )


def _validate_outputs_fresh(plan: AuditedPlan) -> None:
    _validate_namespace(plan.namespace, seed=plan.identity_plan.seed, nonce=plan.identity_plan.nonce, fresh=True)
    for name, path in plan.outputs.items():
        if name == "namespace":
            continue
        if os.path.lexists(path):
            _fail(f"output.{name} already exists; refusing namespace/output reuse")


def _revalidate_for_execution(
    plan: AuditedPlan,
    *,
    admission_probe: Callable[[int], Mapping[str, Any]] | None = None,
) -> Mapping[str, Any]:
    if type(plan) is not AuditedPlan:
        _fail("execution requires an AuditedPlan minted by build_audited_plan")
    _validate_bounded_input_paths(plan.identity_plan)
    expected_digest = _exact_command_digest(plan.identity_plan, plan.gpu_index)
    if expected_digest != plan.exact_command_digest:
        _fail("exact command digest drifted from the audited plan")
    if plan.identity_plan.command_sha256 != identity.canonical_digest(
        {
            "argv": list(plan.identity_plan.command),
            "cwd": str(plan.identity_plan.root),
            "env_overrides": dict(plan.identity_plan.env),
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
        }
    ):
        _fail("identity command digest drifted from the bounded identity contract")
    for name, snapshot in plan.input_snapshots.items():
        _assert_snapshot(snapshot, name)
    _validate_outputs_fresh(plan)
    current_admission = (
        probe_resource_admission(plan.gpu_index, root=plan.identity_plan.root)
        if admission_probe is None
        else dict(admission_probe(plan.gpu_index))
    )
    _exact(current_admission, "schema", ADMISSION_SCHEMA, "current_admission")
    _exact(current_admission, "gpu_index", plan.gpu_index, "current_admission")
    if not current_admission.get("admitted"):
        _fail("resource admission is not currently safe for execution")
    return current_admission


class _ExecutionRecord:
    """Immutable in-memory witness minted only after the real Popen/wait path.

    The constructor is intentionally unusable by callers.  A future admitted
    runtime path must create this object through ``_new_execution_record``
    after it has captured the exact process and identity fields.  A mapping,
    PID, return code, or fake/subclassed process can therefore never be
    promoted into a process proof by ``build_process_proof``.
    """

    __slots__ = (
        "plan_digest",
        "process",
        "evaluator_pid",
        "evaluator_returncode",
        "wait_returncode",
        "waited",
        "command",
        "command_sha256",
        "cwd",
        "env_overrides",
        "namespace",
        "namespace_nonce",
        "manifest_sha256",
        "manifest_file_sha256",
        "training_receipt",
        "training_receipt_sha256",
        "checkpoint_path",
        "checkpoint_sha256",
        "checkpoint_bytes",
        "_seal_digest",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("_ExecutionRecord is an internal sealed witness")

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("_ExecutionRecord is immutable")


def _record_payload(record: _ExecutionRecord) -> dict[str, Any]:
    return {
        "plan_digest": record.plan_digest,
        "process_object_id": id(record.process),
        "process_type": f"{type(record.process).__module__}.{type(record.process).__qualname__}",
        "evaluator_pid": record.evaluator_pid,
        "evaluator_returncode": record.evaluator_returncode,
        "wait_returncode": record.wait_returncode,
        "waited": record.waited,
        "command": list(record.command),
        "command_sha256": record.command_sha256,
        "cwd": record.cwd,
        "env_overrides": dict(record.env_overrides),
        "namespace": record.namespace,
        "namespace_nonce": record.namespace_nonce,
        "manifest_sha256": record.manifest_sha256,
        "manifest_file_sha256": record.manifest_file_sha256,
        "training_receipt": record.training_receipt,
        "training_receipt_sha256": record.training_receipt_sha256,
        "checkpoint_path": record.checkpoint_path,
        "checkpoint_sha256": record.checkpoint_sha256,
        "checkpoint_bytes": record.checkpoint_bytes,
    }


def _record_digest(payload: Mapping[str, Any]) -> str:
    return hmac.new(
        _PROCESS_RECORD_SECRET,
        canonical_json(dict(payload)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _new_execution_record(
    plan: AuditedPlan,
    process: subprocess.Popen[Any],
    wait_returncode: int,
) -> _ExecutionRecord:
    """Create the only record shape accepted by ``build_process_proof``."""

    checkpoint = plan.identity_plan.checkpoint
    record = object.__new__(_ExecutionRecord)
    values = {
        "plan_digest": plan.audited_plan_digest,
        "process": process,
        "evaluator_pid": int(process.pid),
        "evaluator_returncode": int(process.returncode),
        "wait_returncode": int(wait_returncode),
        "waited": True,
        "command": tuple(plan.identity_plan.command),
        "command_sha256": plan.exact_command_digest,
        "cwd": str(plan.identity_plan.root),
        "env_overrides": dict(plan.identity_plan.env),
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.identity_plan.nonce,
        "manifest_sha256": plan.identity_plan.manifest_sha256,
        "manifest_file_sha256": plan.identity_plan.manifest_file_sha256,
        "training_receipt": str(plan.identity_plan.training_receipt),
        "training_receipt_sha256": plan.identity_plan.training_receipt_sha256,
        "checkpoint_path": str(checkpoint["path"]),
        "checkpoint_sha256": str(checkpoint["sha256"]),
        "checkpoint_bytes": int(checkpoint["bytes"]),
    }
    for name, value in values.items():
        object.__setattr__(record, name, value)
    object.__setattr__(record, "_seal_digest", _record_digest(_record_payload(record)))
    return record


def _reject_injected_popen(popen_factory: Any) -> None:
    if popen_factory is not None and popen_factory is not _REAL_POPEN:
        _fail("caller-supplied, fake, or injected Popen is not admitted")


# No runtime capability is installed in this diagnostic-only module.  There
# is intentionally no mutable token that a caller can monkeypatch into an
# executable authority; enabling the future path requires a separately
# reviewed code change.


def _run_popen_wait(
    plan: AuditedPlan,
    *,
    terminal_capability: object | None = None,
    popen_factory: Any = None,
    admission_probe: Callable[[int], Mapping[str, Any]] | None = None,
) -> _ExecutionRecord:
    """The only future process-start path; currently always fail-closed.

    The argument is retained solely so tests and callers receive an explicit
    rejection when they try to inject a factory or self-declared capability.
    The current contract has no executable capability, so this function never
    reaches the real Popen call and never creates an output log.
    """

    _reject_injected_popen(popen_factory)
    if terminal_capability is not None:
        _fail("caller-supplied terminal capability cannot authorize Popen")
    _fail(
        f"{TERMINAL_CAPABILITY_SCHEMA} is not admitted; no real Popen/wait witness "
        "can be created in the diagnostic-only boundary"
    )

    # The code below documents the reviewed future lifecycle.  It is
    # unreachable while the capability is uninstalled; importantly, it uses
    # the captured real Popen object and the sealed record factory rather than
    # any caller-provided process fields or factory.
    _revalidate_for_execution(plan, admission_probe=admission_probe)
    log_path = plan.outputs["log"]
    try:
        log_fd = os.open(
            log_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
    except OSError as error:
        _fail(f"cannot create exclusive evaluator log: {error}")
    log_file = os.fdopen(log_fd, "wb", closefd=True)
    environment = os.environ.copy()
    environment.update({str(k): str(v) for k, v in plan.identity_plan.env.items()})
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
        _fail("real Popen did not return the exact captured subprocess.Popen type")
    if tuple(process.args) != tuple(plan.identity_plan.command):
        _fail("real Popen args drifted from the exact audited command")
    if process.pid <= 0:
        _fail("real Popen returned an invalid evaluator PID")
    wait_returncode = process.wait()
    if type(wait_returncode) is not int:
        _fail("Popen.wait() did not return an integer return code")
    if process.returncode != wait_returncode:
        _fail("Popen.returncode drifted from the observed wait return code")
    if process.poll() != wait_returncode:
        _fail("Popen process was not observed reaped after wait")
    return _new_execution_record(plan, process, wait_returncode)


def build_process_proof(plan: AuditedPlan, record: Any) -> dict[str, Any]:
    """Mint proof only from an immutable, sealed real-Popen/wait witness."""

    if type(record) is not _ExecutionRecord:
        _fail("process proof requires a sealed record from the real Popen/wait path")
    try:
        sealed_digest = record._seal_digest
        payload_digest = _record_digest(_record_payload(record))
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        _fail(f"process proof sealed record is malformed: {error}")
    if sealed_digest != payload_digest:
        _fail("process proof sealed record integrity check failed")
    if record.plan_digest != plan.audited_plan_digest:
        _fail("process proof record is bound to a different audited plan")
    if type(record.process) is not _REAL_POPEN:
        _fail("process proof process is not the captured real subprocess.Popen type")
    if not record.waited:
        _fail("process proof lacks an observed wait lifecycle")
    if record.evaluator_returncode != record.wait_returncode:
        _fail("process proof return codes disagree")
    if record.evaluator_returncode != 0:
        _fail("non-zero evaluator return code cannot produce a successful process proof")
    if record.process.returncode != record.wait_returncode or record.process.poll() != record.wait_returncode:
        _fail("process proof process was not naturally reaped by the observed wait")
    expected_checkpoint = plan.identity_plan.checkpoint
    expected_values = {
        "command": tuple(plan.identity_plan.command),
        "command_sha256": plan.exact_command_digest,
        "cwd": str(plan.identity_plan.root),
        "env_overrides": dict(plan.identity_plan.env),
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.identity_plan.nonce,
        "manifest_sha256": plan.identity_plan.manifest_sha256,
        "manifest_file_sha256": plan.identity_plan.manifest_file_sha256,
        "training_receipt": str(plan.identity_plan.training_receipt),
        "training_receipt_sha256": plan.identity_plan.training_receipt_sha256,
        "checkpoint_path": str(expected_checkpoint["path"]),
        "checkpoint_sha256": str(expected_checkpoint["sha256"]),
        "checkpoint_bytes": int(expected_checkpoint["bytes"]),
    }
    for field, expected in expected_values.items():
        if getattr(record, field) != expected:
            _fail(f"process proof {field} drifted from the audited plan")
    return {
        "schema": PROCESS_PROOF_SCHEMA,
        "status": "natural_exit_verified",
        "model": MODEL,
        "seed": plan.identity_plan.seed,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.identity_plan.nonce,
        "audited_plan_digest": plan.audited_plan_digest,
        "manifest_sha256": record.manifest_sha256,
        "manifest_file_sha256": record.manifest_file_sha256,
        "training_receipt": record.training_receipt,
        "training_receipt_sha256": record.training_receipt_sha256,
        "checkpoint_path": record.checkpoint_path,
        "checkpoint_sha256": record.checkpoint_sha256,
        "checkpoint_bytes": record.checkpoint_bytes,
        "command": list(record.command),
        "command_sha256": record.command_sha256,
        "cwd": record.cwd,
        "env_overrides": dict(record.env_overrides),
        "evaluator_pid": record.evaluator_pid,
        "evaluator_returncode": record.evaluator_returncode,
        "wait_returncode": record.wait_returncode,
        "wait_observed": True,
        "diagnostic_only": True,
        "credit": 0,
    }


def execute_plan(
    plan: AuditedPlan,
    *,
    terminal_capability: object | None = None,
    popen_factory: Any = None,
    admission_probe: Callable[[int], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reject all caller-supplied execution authority before any side effect."""

    _reject_injected_popen(popen_factory)
    if terminal_capability is not None:
        _fail("caller-supplied terminal capability cannot authorize Popen")
    _fail(
        f"{TERMINAL_CAPABILITY_SCHEMA} is not admitted; terminal HDF5/artifact identity "
        "closure is not safely implemented, so no evaluator was started"
    )
    record = _run_popen_wait(
        plan,
        terminal_capability=terminal_capability,
        popen_factory=popen_factory,
        admission_probe=admission_probe,
    )
    proof = build_process_proof(plan, record)
    # This branch is unreachable until the capability is separately reviewed;
    # it intentionally does not mint a terminal receipt or formal credit.
    return {"status": "process_exit_verified_diagnostic", "process_proof": proof, **ZERO_CREDIT}


def _parse_bindings(values: Sequence[str], label: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw in values:
        if "=" not in raw:
            _fail(f"{label} binding must use SEED=VALUE")
        seed_text, value = raw.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError:
            _fail(f"{label} seed is not an integer: {seed_text!r}")
        if seed not in SEEDS:
            _fail(f"{label} seed must be one of {SEEDS}")
        if seed in result:
            _fail(f"duplicate {label} binding for seed {seed}")
        result[seed] = value
    return result


def _parse_gpu_bindings(values: Sequence[str]) -> dict[int, int]:
    raw = _parse_bindings(values, "gpu-index")
    result: dict[int, int] = {}
    for seed, value in raw.items():
        try:
            gpu = int(value)
        except ValueError:
            _fail(f"gpu-index for seed {seed} is not an integer")
        if not 0 <= gpu < GPU_COUNT:
            _fail(f"gpu-index for seed {seed} is outside [0, {GPU_COUNT})")
        result[seed] = gpu
    return result


def build_report(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipts: Mapping[int, Path | str] = DEFAULT_RECEIPTS,
    checkpoints: Mapping[int, Path | str] | None = None,
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
    """Build the current blocked report without launching any evaluator."""

    root_path = _absolute_path(root, "root")
    manifest_path = _absolute_path(manifest, "manifest")
    if set(training_receipts) != set(SEEDS):
        _fail(f"training_receipts must cover exactly {SEEDS}")
    if checkpoints is not None and set(checkpoints) != set(SEEDS):
        _fail(f"checkpoints must cover exactly {SEEDS}")
    if nonces is not None and set(nonces) != set(SEEDS):
        _fail(f"nonces must cover exactly {SEEDS}")
    if gpu_indices is not None and set(gpu_indices) != set(SEEDS):
        _fail(f"gpu_indices must cover exactly {SEEDS}")
    selected_nonces = {
        seed: _validate_nonce(
            (nonces or {}).get(seed, secrets.token_hex(16)), f"nonce.seed{seed}"
        )
        for seed in SEEDS
    }
    if len(set(selected_nonces.values())) != len(SEEDS):
        _fail("per-seed nonces must be unique")
    selected_gpu = {
        seed: int((gpu_indices or DEFAULT_GPU_INDICES).get(seed, DEFAULT_GPU_INDICES[seed]))
        for seed in SEEDS
    }
    if len(set(selected_gpu.values())) != len(SEEDS):
        _fail("per-seed GPU assignment must be unique")

    rows: list[dict[str, Any]] = []
    plans: list[AuditedPlan] = []
    blockers = [
        f"{TERMINAL_CAPABILITY_SCHEMA} is not implemented/admitted",
        "no evaluator was started and no synthetic terminal/process receipt was minted",
    ]
    for seed in SEEDS:
        admission = probe_resource_admission(
            selected_gpu[seed],
            root=root_path,
            gpu_rows=gpu_rows,
            probe_errors=probe_errors,
            cpu_count=cpu_count,
            load_1m=load_1m,
            tmp_free_bytes=tmp_free_bytes,
            root_free_bytes=root_free_bytes,
        )
        namespace = Path(output_root) / (
            f"f3-graph_raw500-hidden16-currentmanifest-seed{seed}-full835-nonce{selected_nonces[seed]}"
        )
        try:
            plan = build_audited_plan(
                root_path,
                seed=seed,
                manifest=manifest_path,
                training_receipt=training_receipts[seed],
                checkpoint=None if checkpoints is None else checkpoints[seed],
                nonce=selected_nonces[seed],
                output_namespace=namespace,
                gpu_index=selected_gpu[seed],
                admission=admission,
            )
            plans.append(plan)
            row = {
                "seed": seed,
                "status": "blocked_fail_closed",
                "run_id": plan.identity_plan.run_id,
                "training_receipt": str(plan.identity_plan.training_receipt),
                "training_receipt_sha256": plan.identity_plan.training_receipt_sha256,
                "checkpoint": dict(plan.identity_plan.checkpoint),
                "manifest": str(plan.identity_plan.manifest),
                "manifest_sha256": plan.identity_plan.manifest_sha256,
                "namespace": str(plan.namespace),
                "namespace_nonce": plan.identity_plan.nonce,
                "gpu_index": plan.gpu_index,
                "admission": dict(plan.admission),
                "exact_command_digest": plan.exact_command_digest,
                "audited_plan_digest": plan.audited_plan_digest,
                "launch_allowed": False,
                "process_proof": None,
                "terminal_receipt": None,
                "blocked_reasons": list(blockers) + list(admission.get("blocked_reasons", [])),
            }
        except (ExecutorError, identity.ContractError, OSError, ValueError) as error:
            row = {
                "seed": seed,
                "status": "blocked_fail_closed",
                "training_receipt": str(training_receipts[seed]),
                "namespace": str(namespace),
                "namespace_nonce": selected_nonces[seed],
                "gpu_index": selected_gpu[seed],
                "admission": admission,
                "launch_allowed": False,
                "process_proof": None,
                "terminal_receipt": None,
                "blocked_reasons": list(blockers) + [str(error)],
            }
        rows.append(row)
    report = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_fail_closed",
        "mode": "audited_executor_canary_boundary",
        "source_bound": len(plans) == len(SEEDS),
        "plan_identity_bound": len(plans) == len(SEEDS),
        "launch_allowed": False,
        "terminal_capability_admitted": False,
        "terminal_receipts_verified": 0,
        "terminal_receipts_expected": len(SEEDS),
        "process_proofs_verified": 0,
        "process_proofs_expected": len(SEEDS),
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
            "diagnostic_only": True,
            "zero_credit_only": True,
        },
        "seed_rows": rows,
        "blocked_reasons": sorted(set(blockers + [reason for row in rows for reason in row["blocked_reasons"] if "terminal" not in reason and "synthetic" not in reason])),
        "input_boundary": {
            "bounded_manifest_and_training_json": True,
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "trajectory_hdf5_content_opened": False,
            "progress_content_opened": False,
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
            "plan_writes": 0,
            "synthetic_receipts_minted": 0,
        },
        **ZERO_CREDIT,
    }
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _reject_authority_aliases(report, "report")
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        _exact(report, "launch_allowed", False, "report")
        _exact(report, "terminal_capability_admitted", False, "report")
        _exact(report, "terminal_receipts_verified", 0, "report")
        _exact(report, "process_proofs_verified", 0, "report")
        _zero_credit(report, "report")
        rows = report.get("seed_rows")
        if not isinstance(rows, list) or len(rows) != len(SEEDS):
            _fail("report.seed_rows must contain exactly three rows")
        seeds = [row.get("seed") for row in rows if isinstance(row, Mapping)]
        if sorted(seeds) != list(SEEDS):
            _fail("report.seed_rows has the wrong seed set")
        for row in rows:
            if not isinstance(row, Mapping):
                _fail("report.seed_rows contains a non-object")
            _exact(row, "status", "blocked_fail_closed", f"seed{row.get('seed')}")
            _exact(row, "launch_allowed", False, f"seed{row.get('seed')}")
            _exact(row, "process_proof", None, f"seed{row.get('seed')}")
            _exact(row, "terminal_receipt", None, f"seed{row.get('seed')}")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key in (
            "runtime_started",
            "queue_submissions",
            "registry_writes",
            "ledger_writes",
            "denominator_writes",
            "gate_writes",
            "completion_writes",
            "plan_writes",
            "synthetic_receipts_minted",
        ):
            if key not in side_effects or side_effects[key] not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
    except (ExecutorError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_raw hidden16 current-manifest audited executor/canary",
        "",
        f"- status: `{report.get('status')}`",
        f"- launch_allowed: `{report.get('launch_allowed')}`",
        f"- plan identities: `{sum(1 for row in report.get('seed_rows', []) if row.get('run_id'))}/3`",
        "- process proofs: `0/3`; terminal HDF5/artifact capability: `not admitted`",
        "- protocol: `graph_raw`, hidden `16`, updates `500`, case `F3_DEV_00_a0p903125`, split `test`, `835 transitions / 836 frames`",
        "- boundary: bounded JSON/stat-only identity checks, read-only GPU/CPU/I/O admission, diagnostic-only, zero-credit",
        "",
        "| seed | GPU | namespace | status |",
        "|---:|---:|---|---|",
    ]
    for row in report.get("seed_rows", []):
        if isinstance(row, Mapping):
            lines.append(
                f"| {row.get('seed')} | {row.get('gpu_index')} | `{row.get('namespace')}` | `{row.get('status')}` |"
            )
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {item}" for item in report.get("blocked_reasons", []) if isinstance(item, str))
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
    parser.add_argument("--gpu-index", action="append", default=[], metavar="SEED=GPU")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--execute", action="store_true", help="always blocked until terminal capability is reviewed")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            report_path = Path(args.verify_report)
            if not report_path.is_absolute():
                cwd_candidate = Path.cwd() / report_path
                report_path = (
                    cwd_candidate
                    if cwd_candidate.exists()
                    else Path(args.root) / report_path
                )
            payload, _ = _read_bounded_json(report_path, name="report")
            errors = validate_report(payload)
            if errors:
                _fail("; ".join(errors))
            print(json.dumps({"status": "verified", "report": str(args.verify_report)}, ensure_ascii=False))
            return 0
        receipts = _parse_bindings(args.training_receipt, "training-receipt") if args.training_receipt else dict(DEFAULT_RECEIPTS)
        checkpoints = _parse_bindings(args.checkpoint, "checkpoint") if args.checkpoint else None
        nonces = _parse_bindings(args.nonce, "nonce") if args.nonce else None
        gpu_indices = _parse_gpu_bindings(args.gpu_index) if args.gpu_index else None
        report = build_report(
            args.root,
            manifest=args.manifest,
            training_receipts=receipts,
            checkpoints=checkpoints,
            nonces=nonces,
            gpu_indices=gpu_indices,
            output_root=args.output_root,
        )
        if args.execute:
            report["blocked_reasons"] = sorted(
                set(report["blocked_reasons"])
                | {"--execute cannot bypass the unadmitted terminal HDF5/artifact capability"}
            )
        _write_json(args.report_output, report)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (ExecutorError, identity.ContractError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked_fail_closed", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
