#!/usr/bin/env python3
"""Fail-closed bridge contract for one diagnostic graph_raw terminal run.

This module is intentionally additive.  It composes the existing audited
executor, current-manifest rollout launcher, and synthetic terminal-artifact
validator contracts without changing any of them.  The current repository
does not contain an admitted production HDF5 validator capability: the
existing terminal validator is explicitly synthetic-only.  Consequently the
bridge always stops before ``subprocess.Popen`` and emits zero-credit,
diagnostic-only planning evidence.

The future one-shot path is specified nevertheless.  If a separately
reviewed production validator capability is ever installed, it must pass all
of these gates in order:

1. the audited plan has a fresh, single-use nonce namespace;
2. manifest, training receipt, checkpoint, command, and source identities
   still match the plan;
3. GPU/CPU/I/O admission is re-probed immediately before launch;
4. the exact evaluator is started once with the real ``subprocess.Popen``
   class and naturally reaped with ``wait``;
5. an independent read-only HDF5 validator binds every evaluator artifact by
   path/SHA/bytes and binds graph_raw/test/835 transitions/836 frames,
   nonce, case, manifest, receipt, checkpoint, and command identities.

No caller-supplied PID, return code, synthetic validator report, or fake
Popen object can mint process or terminal evidence.  This file never stops
or restarts another job and never writes registry, ledger, denominator, gate,
completion, or PLAN state.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_raw_hidden16_current_manifest_audited_executor_v1 as executor
from scripts import f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1 as synthetic_validator


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = executor.SEEDS
DEFAULT_GPU_INDICES = executor.DEFAULT_GPU_INDICES
MODEL = executor.MODEL
HIDDEN = executor.HIDDEN
UPDATES = executor.UPDATES
CASE_ID = executor.CASE_ID
SPLIT = executor.SPLIT
TRANSITIONS = executor.TRANSITIONS
FRAMES = executor.FRAMES
GPU_COUNT = executor.GPU_COUNT

SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.terminal_execution_bridge.v1"
PLAN_SCHEMA = f"{SCHEMA}.plan"
PROCESS_EVIDENCE_SCHEMA = f"{SCHEMA}.process_evidence"
TERMINAL_ATTESTATION_SCHEMA = f"{SCHEMA}.production_terminal_validator_attestation"
DIAGNOSTIC_EVIDENCE_SCHEMA = f"{SCHEMA}.diagnostic_evidence"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-graph-raw-hidden16-current-manifest-terminal-execution-bridge-v1"

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
    / "F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-TERMINAL-EXECUTION-BRIDGE-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")

# The bridge never launches in the current diagnostic-only release.  If a
# separately reviewed runtime is added later, it must use this captured class
# directly; caller-supplied factories and monkeypatched subprocess modules are
# not allowed to mint process evidence.
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

REPORT_AUTHORITY_KEYS = frozenset(
    {
        "formal",
        "formal_eligible",
        "qualification",
        "qualification_credit",
        "credit",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "launch_allowed",
        "runtime_started",
        "processes_started",
        "processes_stopped",
        "processes_restarted",
        "registry_writes",
        "ledger_writes",
        "denominator_writes",
        "gate_writes",
        "completion_writes",
        "plan_writes",
    }
)


class BridgeError(ValueError):
    """Malformed, drifting, unsafe, or authorizing input."""


def _fail(message: str) -> None:
    raise BridgeError(f"fail-closed: {message}")


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
        _fail(f"{name} contains unsupported keys: {unknown}")


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
    path = Path(value)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} contains a lexical path alias")
    return path


def _reject_symlink_components(path: Path, name: str, *, include_leaf: bool = True) -> None:
    path = _absolute_path(path, name)
    components = path if include_leaf else path.parent
    current = Path(path.anchor)
    for part in components.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _directory_flags() -> int:
    if not getattr(os, "O_DIRECTORY", 0):
        _fail("platform does not expose O_DIRECTORY for safe artifact reads")
    return (
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _read_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_directory_chain(path: Path, name: str) -> int:
    """Hold every parent directory descriptor without following symlinks."""

    _absolute_path(path, name)
    current_fd: int | None = None
    try:
        current_fd = os.open(Path(path.anchor or "/"), _directory_flags())
        for component in path.parts[1:]:
            next_fd = os.open(component, _directory_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as error:
        if current_fd is not None:
            try:
                os.close(current_fd)
            except OSError:
                pass
        _fail(f"cannot open descriptor chain for {name}: {error}")
    except BaseException:
        if current_fd is not None:
            try:
                os.close(current_fd)
            except OSError:
                pass
        raise


def _read_artifact_snapshot(path: Path, name: str, expected_bytes: int) -> bytes:
    """Read one artifact from a held descriptor, never by reopening its path.

    The descriptor is opened with ``O_NOFOLLOW`` after every parent directory
    is walked through a held descriptor.  The bytes are hashed by the caller
    from this one read.  A final pathname identity check is only an additional
    drift detector; it is never used as a substitute for descriptor binding.
    """

    path = _absolute_path(path, name)
    _reject_symlink_components(path, name)
    if type(expected_bytes) is not int or expected_bytes < 1:
        _fail(f"{name}.bytes must be a positive integer")
    parent_fd: int | None = None
    leaf_fd: int | None = None
    before: os.stat_result | None = None
    bound_path: os.stat_result | None = None
    chunks: list[bytes] = []
    try:
        parent_fd = _open_directory_chain(path.parent, f"{name} parent")
        leaf_fd = os.open(path.name, _read_flags(), dir_fd=parent_fd)
        before = os.fstat(leaf_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{name} must be a regular single-link file")
        if before.st_size <= 0 or before.st_size > MAX_ARTIFACT_BYTES:
            _fail(f"{name} has an unsafe size")
        if int(before.st_size) != expected_bytes:
            _fail(f"{name}.bytes disagrees with the descriptor identity")
        expected_identity = _stat_identity(before)
        total = 0
        while True:
            block = os.read(leaf_fd, min(1024 * 1024, MAX_ARTIFACT_BYTES + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > MAX_ARTIFACT_BYTES:
                _fail(f"{name} exceeds the bounded read size")
        after_fd = os.fstat(leaf_fd)
        if _stat_identity(after_fd) != expected_identity or total != int(before.st_size):
            _fail(f"{name} changed during descriptor read")
        bound_path = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if _stat_identity(bound_path) != expected_identity:
            _fail(f"{name} path identity changed before descriptor release")
    except OSError as error:
        _fail(f"cannot read {name} from the bound descriptor: {error}")
    finally:
        if leaf_fd is not None:
            try:
                os.close(leaf_fd)
            except OSError:
                pass
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass
    if before is None:
        _fail(f"{name} did not produce a descriptor identity")
    if bound_path is None:
        _fail(f"{name} did not produce a bound pathname identity")
    try:
        after_path = os.lstat(path)
    except OSError as error:
        _fail(f"{name} path changed after descriptor read: {error}")
    if _stat_identity(after_path) != _stat_identity(before):
        _fail(f"{name} path identity changed after descriptor read")
    raw = b"".join(chunks)
    if len(raw) != expected_bytes:
        _fail(f"{name} read byte count disagrees with the bound descriptor")
    return raw


def _sha256_file(path: Path, name: str, expected_bytes: int) -> str:
    raw = _read_artifact_snapshot(path, name, expected_bytes)
    return hashlib.sha256(raw).hexdigest()


def _validate_nonce(value: Any, name: str) -> str:
    nonce = _string(value, name)
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail(f"{name} must be a non-zero 32-character lowercase hexadecimal value")
    return nonce


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        _exact(value, key, expected, name)


@dataclass(frozen=True)
class BridgePlan:
    """A bounded, non-launching composition of the existing audited plan."""

    audited_plan: executor.AuditedPlan
    bridge_plan_digest: str

    @property
    def namespace(self) -> Path:
        return self.audited_plan.namespace

    @property
    def outputs(self) -> Mapping[str, Path]:
        return self.audited_plan.outputs

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "status": "fresh_diagnostic_plan_ready",
            "bridge_schema": SCHEMA,
            "audited_plan": self.audited_plan.as_dict(),
            "bridge_plan_digest": self.bridge_plan_digest,
            "production_validator_capability_admitted": False,
            "launch_allowed": False,
            "single_use_namespace": True,
            "namespace_exists_at_plan_time": self.namespace.exists(),
            "execution_requires": [
                "resource_re_admission",
                "real_subprocess.Popen_and_wait",
                "independent_production_hdf5_validator",
            ],
            **ZERO_CREDIT,
        }


def _plan_digest_payload(plan: executor.AuditedPlan) -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "audited_plan": plan.as_dict(),
        "terminal_validator_schema": TERMINAL_ATTESTATION_SCHEMA,
        "required_model": MODEL,
        "required_hidden": HIDDEN,
        "required_updates": UPDATES,
        "required_case_id": CASE_ID,
        "required_split": SPLIT,
        "required_transitions": TRANSITIONS,
        "required_frames": FRAMES,
    }


def build_bridge_plan(
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
) -> BridgePlan:
    """Build a fresh plan while opening only bounded identity metadata."""

    audited = executor.build_audited_plan(
        root,
        seed=seed,
        manifest=manifest,
        training_receipt=training_receipt,
        checkpoint=checkpoint,
        nonce=nonce,
        output_namespace=output_namespace,
        gpu_index=gpu_index,
        admission=admission,
    )
    if audited.identity_plan.launch_allowed:
        _fail("underlying rollout identity unexpectedly admits launch")
    if audited.identity_plan.as_dict().get("formal", False):
        _fail("formal identity is not admissible for a diagnostic bridge")
    if audited.namespace.exists():
        _fail("fresh bridge namespace already exists")
    for name, path in audited.outputs.items():
        if name == "namespace":
            continue
        if os.path.lexists(path):
            _fail(f"fresh bridge output already exists: {name}")
    digest = canonical_digest(_plan_digest_payload(audited))
    return BridgePlan(audited_plan=audited, bridge_plan_digest=digest)


def _revalidate_bridge_plan(
    plan: BridgePlan,
    *,
    admission_probe: Callable[[int], Mapping[str, Any]] | None = None,
) -> Mapping[str, Any]:
    if type(plan) is not BridgePlan:
        _fail("execution requires a BridgePlan minted by build_bridge_plan")
    expected_digest = canonical_digest(_plan_digest_payload(plan.audited_plan))
    if expected_digest != plan.bridge_plan_digest:
        _fail("bridge plan digest drifted")
    if plan.audited_plan.identity_plan.launch_allowed:
        _fail("audited plan is not non-authorizing")
    return executor._revalidate_for_execution(
        plan.audited_plan,
        admission_probe=admission_probe,
    )


def _artifact_paths(plan: BridgePlan) -> dict[str, Path]:
    return {
        "trajectory": plan.outputs["trajectory"],
        "evaluation": plan.outputs["evaluation"],
        "progress": plan.outputs["progress"],
    }


def _validate_attestation_artifact(
    value: Any,
    name: str,
    expected_path: Path,
    *,
    expected_suffix: str,
) -> dict[str, Any]:
    item = _mapping(value, name)
    _reject_unknown(item, {"path", "sha256", "bytes"}, name)
    path = _absolute_path(item.get("path"), f"{name}.path")
    if path != expected_path:
        _fail(f"{name}.path differs from the fresh audited output")
    if path.suffix.lower() != expected_suffix:
        _fail(f"{name}.path must end with {expected_suffix}")
    digest = _sha(item.get("sha256"), f"{name}.sha256")
    size = _int(item.get("bytes"), f"{name}.bytes", 1)
    observed = _sha256_file(path, name, size)
    if observed != digest:
        _fail(f"{name}.sha256 disagrees with the read-only artifact")
    return {"path": str(path), "sha256": digest, "bytes": size}


def validate_terminal_attestation(
    plan: BridgePlan,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an independent production-validator result, without authorizing it.

    The current synthetic validator cannot satisfy this shape.  This function
    is intentionally non-authorizing; ``build_diagnostic_evidence`` also
    requires the private production capability, which is currently ``None``.
    """

    item = _mapping(value, "terminal_attestation")
    _walk_json(item, "terminal_attestation")
    _reject_unknown(
        item,
        {
            "schema",
            "status",
            "validator_id",
            "validator_version",
            "independent_validator",
            "production_artifact_opened",
            "synthetic_only",
            "real_producer_proof",
            "real_terminal_proof",
            "model_kind",
            "hidden",
            "seed",
            "case_id",
            "split",
            "transitions",
            "frames",
            "namespace",
            "namespace_nonce",
            "manifest_sha256",
            "training_receipt_sha256",
            "checkpoint_sha256",
            "audited_plan_digest",
            "command_sha256",
            "artifacts",
            "hdf5_binding",
            "validator_attestation_sha256",
        },
        "terminal_attestation",
    )
    _exact(item, "schema", TERMINAL_ATTESTATION_SCHEMA, "terminal_attestation")
    _exact(item, "status", "validated_real_evaluator_artifacts", "terminal_attestation")
    validator_id = _string(item.get("validator_id"), "terminal_attestation.validator_id")
    if "synthetic" in validator_id.lower() or validator_id in {
        synthetic_validator.REPORT_ID,
        synthetic_validator.REPORT_SCHEMA,
    }:
        _fail("synthetic validator identity cannot authorize a production attestation")
    _string(item.get("validator_version"), "terminal_attestation.validator_version")
    _exact(item, "independent_validator", True, "terminal_attestation")
    _exact(item, "production_artifact_opened", True, "terminal_attestation")
    _exact(item, "synthetic_only", False, "terminal_attestation")
    _exact(item, "real_producer_proof", True, "terminal_attestation")
    _exact(item, "real_terminal_proof", True, "terminal_attestation")
    _exact(item, "model_kind", MODEL, "terminal_attestation")
    _exact(item, "hidden", HIDDEN, "terminal_attestation")
    _exact(item, "seed", plan.audited_plan.identity_plan.seed, "terminal_attestation")
    _exact(item, "case_id", CASE_ID, "terminal_attestation")
    _exact(item, "split", SPLIT, "terminal_attestation")
    _exact(item, "transitions", TRANSITIONS, "terminal_attestation")
    _exact(item, "frames", FRAMES, "terminal_attestation")
    _exact(item, "namespace", str(plan.namespace), "terminal_attestation")
    _exact(item, "namespace_nonce", plan.audited_plan.identity_plan.nonce, "terminal_attestation")
    _exact(item, "manifest_sha256", plan.audited_plan.identity_plan.manifest_sha256, "terminal_attestation")
    _exact(item, "training_receipt_sha256", plan.audited_plan.identity_plan.training_receipt_sha256, "terminal_attestation")
    _exact(
        item,
        "checkpoint_sha256",
        str(plan.audited_plan.identity_plan.checkpoint["sha256"]),
        "terminal_attestation",
    )
    _exact(item, "audited_plan_digest", plan.audited_plan.audited_plan_digest, "terminal_attestation")
    _exact(item, "command_sha256", plan.audited_plan.exact_command_digest, "terminal_attestation")

    artifacts = _mapping(item.get("artifacts"), "terminal_attestation.artifacts")
    _reject_unknown(artifacts, {"trajectory", "evaluation", "progress"}, "terminal_attestation.artifacts")
    bound_artifacts = {
        "trajectory": _validate_attestation_artifact(
            artifacts.get("trajectory"),
            "terminal_attestation.artifacts.trajectory",
            _artifact_paths(plan)["trajectory"],
            expected_suffix=".h5",
        ),
        "evaluation": _validate_attestation_artifact(
            artifacts.get("evaluation"),
            "terminal_attestation.artifacts.evaluation",
            _artifact_paths(plan)["evaluation"],
            expected_suffix=".json",
        ),
        "progress": _validate_attestation_artifact(
            artifacts.get("progress"),
            "terminal_attestation.artifacts.progress",
            _artifact_paths(plan)["progress"],
            expected_suffix=".json",
        ),
    }
    hdf5 = _mapping(item.get("hdf5_binding"), "terminal_attestation.hdf5_binding")
    _reject_unknown(
        hdf5,
        {"path", "sha256", "bytes", "transitions", "frames", "nonce", "case_id"},
        "terminal_attestation.hdf5_binding",
    )
    _exact(hdf5, "path", bound_artifacts["trajectory"]["path"], "terminal_attestation.hdf5_binding")
    _exact(hdf5, "sha256", bound_artifacts["trajectory"]["sha256"], "terminal_attestation.hdf5_binding")
    _exact(hdf5, "bytes", bound_artifacts["trajectory"]["bytes"], "terminal_attestation.hdf5_binding")
    _exact(hdf5, "transitions", TRANSITIONS, "terminal_attestation.hdf5_binding")
    _exact(hdf5, "frames", FRAMES, "terminal_attestation.hdf5_binding")
    _exact(hdf5, "nonce", plan.audited_plan.identity_plan.nonce, "terminal_attestation.hdf5_binding")
    _exact(hdf5, "case_id", CASE_ID, "terminal_attestation.hdf5_binding")

    attestation_digest = _sha(
        item.get("validator_attestation_sha256"),
        "terminal_attestation.validator_attestation_sha256",
    )
    core = dict(item)
    core.pop("validator_attestation_sha256")
    if attestation_digest != canonical_digest(core):
        _fail("terminal attestation digest does not bind its complete content")
    return {
        **dict(item),
        "artifacts": bound_artifacts,
        "hdf5_binding": dict(hdf5),
        "validator_attestation_sha256": attestation_digest,
    }


class _RealProcessRecord:
    """Immutable witness produced only by the direct real-Popen/wait path."""

    __slots__ = (
        "process",
        "evaluator_pid",
        "returncode",
        "wait_returncode",
        "waited",
        "audited_plan_digest",
        "bridge_plan_digest",
        "command",
        "command_sha256",
        "cwd",
        "env_overrides",
        "namespace",
        "namespace_nonce",
        "manifest_sha256",
        "manifest_file_sha256",
        "training_receipt_sha256",
        "checkpoint_path",
        "checkpoint_sha256",
        "checkpoint_bytes",
        "_seal_digest",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("_RealProcessRecord is an internal sealed witness")

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("_RealProcessRecord is immutable")


def _record_payload(record: _RealProcessRecord) -> dict[str, Any]:
    return {
        "process_object_id": id(record.process),
        "process_type": f"{type(record.process).__module__}.{type(record.process).__qualname__}",
        "evaluator_pid": record.evaluator_pid,
        "returncode": record.returncode,
        "wait_returncode": record.wait_returncode,
        "waited": record.waited,
        "audited_plan_digest": record.audited_plan_digest,
        "bridge_plan_digest": record.bridge_plan_digest,
        "command": list(record.command),
        "command_sha256": record.command_sha256,
        "cwd": record.cwd,
        "env_overrides": dict(record.env_overrides),
        "namespace": record.namespace,
        "namespace_nonce": record.namespace_nonce,
        "manifest_sha256": record.manifest_sha256,
        "manifest_file_sha256": record.manifest_file_sha256,
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


def _new_real_process_record(
    plan: BridgePlan,
    process: subprocess.Popen[Any],
    wait_returncode: int,
) -> _RealProcessRecord:
    checkpoint = plan.audited_plan.identity_plan.checkpoint
    record = object.__new__(_RealProcessRecord)
    values = {
        "process": process,
        "evaluator_pid": int(process.pid),
        "returncode": int(process.returncode),
        "wait_returncode": int(wait_returncode),
        "waited": True,
        "audited_plan_digest": plan.audited_plan.audited_plan_digest,
        "bridge_plan_digest": plan.bridge_plan_digest,
        "command": tuple(plan.audited_plan.identity_plan.command),
        "command_sha256": plan.audited_plan.exact_command_digest,
        "cwd": str(plan.audited_plan.identity_plan.root),
        "env_overrides": dict(plan.audited_plan.identity_plan.env),
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.audited_plan.identity_plan.nonce,
        "manifest_sha256": plan.audited_plan.identity_plan.manifest_sha256,
        "manifest_file_sha256": plan.audited_plan.identity_plan.manifest_file_sha256,
        "training_receipt_sha256": plan.audited_plan.identity_plan.training_receipt_sha256,
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


def _validate_real_process_record(plan: BridgePlan, record: Any) -> _RealProcessRecord:
    if type(record) is not _RealProcessRecord:
        _fail("process evidence requires a sealed record from the real Popen/wait path")
    try:
        sealed_digest = record._seal_digest
        payload_digest = _record_digest(_record_payload(record))
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        _fail(f"process evidence sealed record is malformed: {error}")
    if sealed_digest != payload_digest:
        _fail("process evidence sealed record integrity check failed")
    if type(record.process) is not _REAL_POPEN:
        _fail("process evidence process is not the captured real subprocess.Popen type")
    if record.audited_plan_digest != plan.audited_plan.audited_plan_digest:
        _fail("process evidence record is bound to a different audited plan")
    if record.bridge_plan_digest != plan.bridge_plan_digest:
        _fail("process evidence record is bound to a different bridge plan")
    if not record.waited:
        _fail("process evidence lacks an observed wait lifecycle")
    if record.returncode != record.wait_returncode or record.returncode != 0:
        _fail("process evidence return codes are not a successful natural exit")
    if record.process.returncode != record.wait_returncode or record.process.poll() != record.wait_returncode:
        _fail("process evidence process was not naturally reaped by the observed wait")
    identity_plan = plan.audited_plan.identity_plan
    checkpoint = identity_plan.checkpoint
    expected = {
        "command": tuple(identity_plan.command),
        "command_sha256": plan.audited_plan.exact_command_digest,
        "cwd": str(identity_plan.root),
        "env_overrides": dict(identity_plan.env),
        "namespace": str(plan.namespace),
        "namespace_nonce": identity_plan.nonce,
        "manifest_sha256": identity_plan.manifest_sha256,
        "manifest_file_sha256": identity_plan.manifest_file_sha256,
        "training_receipt_sha256": identity_plan.training_receipt_sha256,
        "checkpoint_path": str(checkpoint["path"]),
        "checkpoint_sha256": str(checkpoint["sha256"]),
        "checkpoint_bytes": int(checkpoint["bytes"]),
    }
    for field, expected_value in expected.items():
        if getattr(record, field) != expected_value:
            _fail(f"process evidence {field} drifted from the audited plan")
    return record


def _run_real_popen_wait(
    plan: BridgePlan,
    *,
    popen_factory: Any = None,
    admission_probe: Callable[[int], Mapping[str, Any]] | None = None,
) -> _RealProcessRecord:
    """Unreachable today; the guarded future real-Popen/wait path."""

    _reject_injected_popen(popen_factory)
    _fail("production HDF5 validator capability is not admitted; Popen was not attempted")

    # The following is deliberately unreachable until a separately reviewed
    # capability is installed.  It still documents the only allowed lifecycle:
    # direct captured Popen, exact argv/cwd, wait, then sealed-record minting.
    _revalidate_bridge_plan(plan, admission_probe=admission_probe)
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
    environment.update({str(k): str(v) for k, v in plan.audited_plan.identity_plan.env.items()})
    try:
        process = _REAL_POPEN(
            list(plan.audited_plan.identity_plan.command),
            cwd=str(plan.audited_plan.identity_plan.root),
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
        _fail("Popen did not return the captured real subprocess.Popen type")
    if process.args != list(plan.audited_plan.identity_plan.command):
        _fail("Popen args differ from the exact audited command")
    if type(process.pid) is not int or process.pid <= 0:
        _fail("Popen returned an invalid evaluator PID")
    wait_returncode = process.wait()
    if type(wait_returncode) is not int:
        _fail("Popen.wait did not return an integer return code")
    if process.returncode != wait_returncode or process.poll() != wait_returncode:
        _fail("Popen did not provide a consistent naturally reaped return code")
    if wait_returncode != 0:
        _fail("non-zero evaluator return code cannot produce diagnostic evidence")
    return _new_real_process_record(plan, process, wait_returncode)


def _process_evidence_from_real_record(
    plan: BridgePlan,
    record: Any,
) -> dict[str, Any]:
    record = _validate_real_process_record(plan, record)
    return {
        "schema": PROCESS_EVIDENCE_SCHEMA,
        "status": "natural_exit_verified",
        "model": MODEL,
        "seed": plan.audited_plan.identity_plan.seed,
        "namespace": str(plan.namespace),
        "namespace_nonce": plan.audited_plan.identity_plan.nonce,
        "audited_plan_digest": plan.audited_plan.audited_plan_digest,
        "manifest_sha256": record.manifest_sha256,
        "manifest_file_sha256": record.manifest_file_sha256,
        "training_receipt_sha256": record.training_receipt_sha256,
        "checkpoint_path": record.checkpoint_path,
        "checkpoint_sha256": record.checkpoint_sha256,
        "checkpoint_bytes": record.checkpoint_bytes,
        "command": list(record.command),
        "command_sha256": record.command_sha256,
        "cwd": record.cwd,
        "env_overrides": dict(record.env_overrides),
        "evaluator_pid": record.evaluator_pid,
        "evaluator_returncode": record.returncode,
        "wait_returncode": record.returncode,
        "wait_observed": True,
        "real_popen_type": True,
        "diagnostic_only": True,
        "credit": 0,
    }


def validate_process_evidence(plan: BridgePlan, value: Any) -> dict[str, Any]:
    """Only a sealed in-memory witness can be normalized as process evidence."""

    return _process_evidence_from_real_record(plan, value)


def build_diagnostic_evidence(
    plan: BridgePlan,
    process_record: Any,
    terminal_attestation: Mapping[str, Any],
    *,
    _capability: object | None = None,
) -> dict[str, Any]:
    """Combine proofs only from a future sealed witness and capability.

    A serialized mapping is never accepted here.  The current capability is
    deliberately absent, so this function remains non-authorizing and cannot
    start a process or promote caller-supplied PID/returncode fields.
    """

    if _capability is not None:
        _fail("caller-supplied terminal capability cannot mint diagnostic evidence")
    process = validate_process_evidence(plan, process_record)
    _fail("production validator capability is not admitted; evidence cannot be minted")
    terminal = validate_terminal_attestation(plan, terminal_attestation)
    return {
        "schema": DIAGNOSTIC_EVIDENCE_SCHEMA,
        "status": "diagnostic_natural_exit_and_terminal_artifacts_verified",
        "bridge_plan_digest": plan.bridge_plan_digest,
        "process_evidence": process,
        "terminal_attestation": terminal,
        **ZERO_CREDIT,
    }


def execute_diagnostic_one_shot(
    plan: BridgePlan,
    *,
    popen_factory: Any = None,
    admission_probe: Callable[[int], Mapping[str, Any]] | None = None,
    terminal_validator: Callable[[BridgePlan, Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attempt one diagnostic run; current safety gates always reject first.

    ``popen_factory`` is retained to make the negative fake-Popen contract
    explicit in tests.  In the current state it is never called.
    """

    _reject_injected_popen(popen_factory)
    _revalidate_bridge_plan(plan, admission_probe=admission_probe)
    _fail(
        "existing terminal_artifact_validator_v1 is synthetic-only; production HDF5 "
        "validator capability is not admitted, so Popen was not attempted"
    )
    if terminal_validator is None:
        _fail("independent production HDF5 validator callback is required")
    record = _run_real_popen_wait(
        plan,
        popen_factory=popen_factory,
        admission_probe=admission_probe,
    )
    process = _process_evidence_from_real_record(plan, record)
    terminal = terminal_validator(plan, process)
    return build_diagnostic_evidence(
        plan,
        record,
        terminal,
    )


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
    execute_requested: bool = False,
    gpu_rows: Mapping[int, Mapping[str, Any]] | None = None,
    probe_errors: Sequence[str] = (),
    cpu_count: int | None = None,
    load_1m: float | None = None,
    tmp_free_bytes: int | None = None,
    root_free_bytes: int | None = None,
) -> dict[str, Any]:
    """Build the bounded dry-run/explicit-rejection report; never launches."""

    root_path = Path(root)
    manifest_path = Path(manifest)
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
            (nonces or {}).get(seed, secrets.token_hex(16)),
            f"nonce.seed{seed}",
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

    common_blockers = [
        "production HDF5 validator capability is not admitted",
        "existing terminal_artifact_validator_v1 is synthetic-only and cannot validate production evaluator artifacts",
        "no process or terminal evidence was minted",
    ]
    if execute_requested:
        common_blockers.append("explicit diagnostic execute is rejected before Popen while the production validator gate is closed")
    else:
        common_blockers.append("default mode is dry-run and does not attempt Popen")

    rows: list[dict[str, Any]] = []
    plans: list[BridgePlan] = []
    for seed in SEEDS:
        gpu_index = selected_gpu[seed]
        admission = executor.probe_resource_admission(
            gpu_index,
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
            plan = build_bridge_plan(
                root_path,
                seed=seed,
                manifest=manifest_path,
                training_receipt=training_receipts[seed],
                checkpoint=None if checkpoints is None else checkpoints[seed],
                nonce=selected_nonces[seed],
                output_namespace=namespace,
                gpu_index=gpu_index,
                admission=admission,
            )
            plans.append(plan)
            rows.append(
                {
                    "seed": seed,
                    "status": "blocked_fail_closed",
                    "run_id": plan.audited_plan.identity_plan.run_id,
                    "manifest": str(plan.audited_plan.identity_plan.manifest),
                    "manifest_sha256": plan.audited_plan.identity_plan.manifest_sha256,
                    "training_receipt": str(plan.audited_plan.identity_plan.training_receipt),
                    "training_receipt_sha256": plan.audited_plan.identity_plan.training_receipt_sha256,
                    "checkpoint": dict(plan.audited_plan.identity_plan.checkpoint),
                    "namespace": str(plan.namespace),
                    "namespace_nonce": plan.audited_plan.identity_plan.nonce,
                    "gpu_index": gpu_index,
                    "admission": dict(plan.audited_plan.admission),
                    "bridge_plan_digest": plan.bridge_plan_digest,
                    "audited_plan_digest": plan.audited_plan.audited_plan_digest,
                    "exact_command_digest": plan.audited_plan.exact_command_digest,
                    "fresh_namespace": True,
                    "resource_re_admission_required": True,
                    "popen_attempted": False,
                    "process_evidence": None,
                    "terminal_attestation": None,
                    "diagnostic_evidence": None,
                    "blocked_reasons": list(common_blockers),
                }
            )
        except (BridgeError, executor.ExecutorError, executor.identity.ContractError, OSError, ValueError) as error:
            rows.append(
                {
                    "seed": seed,
                    "status": "blocked_fail_closed",
                    "manifest": str(manifest_path),
                    "training_receipt": str(training_receipts[seed]),
                    "namespace": str(namespace),
                    "namespace_nonce": selected_nonces[seed],
                    "gpu_index": gpu_index,
                    "admission": admission,
                    "fresh_namespace": False,
                    "resource_re_admission_required": True,
                    "popen_attempted": False,
                    "process_evidence": None,
                    "terminal_attestation": None,
                    "diagnostic_evidence": None,
                    "blocked_reasons": list(common_blockers) + [str(error)],
                }
            )

    report = {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_fail_closed",
        "mode": "explicit_execute_rejected" if execute_requested else "dry_run",
        "execute_requested": bool(execute_requested),
        "source_bound": len(plans) == len(SEEDS),
        "fresh_namespaces_verified": len(plans),
        "fresh_namespaces_expected": len(SEEDS),
        "exact_identity_plans_verified": len(plans),
        "resource_re_admission_required": True,
        "production_validator_capability_admitted": False,
        "independent_hdf5_validator_admitted": False,
        "popen_attempts": 0,
        "popen_waits": 0,
        "process_evidence_verified": 0,
        "terminal_evidence_verified": 0,
        "diagnostic_evidence_verified": 0,
        "launch_allowed": False,
        "terminal_artifact_validator_schema": synthetic_validator.REPORT_SCHEMA,
        "terminal_artifact_validator_is_synthetic_only": True,
        "expected_contract": {
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "seeds": list(SEEDS),
            "fresh_namespace": True,
            "exact_command_manifest_training_checkpoint_identity": True,
            "resource_re_admission": True,
            "real_popen_wait_natural_exit": True,
            "independent_hdf5_path_sha_bytes_binding": True,
            "synthetic_validator_can_authorize": False,
        },
        "seed_rows": rows,
        "blocked_reasons": sorted(
            set(common_blockers)
            | {
                str(reason)
                for row in rows
                for reason in row.get("blocked_reasons", [])
                if reason not in common_blockers
            }
        ),
        "side_effects": {
            "runtime_started": False,
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "popen_attempts": 0,
            "popen_waits": 0,
            "solver_started": False,
            "worker_started": False,
            "gpu_used_for_execution": False,
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


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _reject_unknown(
            report,
            {
                "schema",
                "report_id",
                "status",
                "mode",
                "execute_requested",
                "source_bound",
                "fresh_namespaces_verified",
                "fresh_namespaces_expected",
                "exact_identity_plans_verified",
                "resource_re_admission_required",
                "production_validator_capability_admitted",
                "independent_hdf5_validator_admitted",
                "popen_attempts",
                "popen_waits",
                "process_evidence_verified",
                "terminal_evidence_verified",
                "diagnostic_evidence_verified",
                "launch_allowed",
                "terminal_artifact_validator_schema",
                "terminal_artifact_validator_is_synthetic_only",
                "expected_contract",
                "seed_rows",
                "blocked_reasons",
                "side_effects",
                *ZERO_CREDIT.keys(),
            },
            "report",
        )
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        if report.get("mode") not in {"dry_run", "explicit_execute_rejected"}:
            _fail("report.mode is not a bounded mode")
        _bool(report.get("execute_requested"), "report.execute_requested")
        for key in (
            "production_validator_capability_admitted",
            "independent_hdf5_validator_admitted",
            "launch_allowed",
            "terminal_artifact_validator_is_synthetic_only",
        ):
            expected = key == "terminal_artifact_validator_is_synthetic_only"
            _exact(report, key, expected, "report")
        for key in (
            "popen_attempts",
            "popen_waits",
            "process_evidence_verified",
            "terminal_evidence_verified",
            "diagnostic_evidence_verified",
        ):
            _exact(report, key, 0, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        _exact(report, "fresh_namespaces_expected", len(SEEDS), "report")
        _exact(report, "resource_re_admission_required", True, "report")
        rows = report.get("seed_rows")
        if not isinstance(rows, list) or len(rows) != len(SEEDS):
            _fail("report.seed_rows must contain exactly three rows")
        row_seeds: list[int] = []
        for index, row_value in enumerate(rows):
            row = _mapping(row_value, f"report.seed_rows[{index}]")
            _exact(row, "status", "blocked_fail_closed", f"report.seed_rows[{index}]")
            seed = _int(row.get("seed"), f"report.seed_rows[{index}].seed")
            row_seeds.append(seed)
            _exact(row, "popen_attempted", False, f"report.seed_rows[{index}]")
            for key in ("process_evidence", "terminal_attestation", "diagnostic_evidence"):
                _exact(row, key, None, f"report.seed_rows[{index}]")
        if sorted(row_seeds) != list(SEEDS):
            _fail("report.seed_rows has the wrong seed set")
        side_effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key, expected in {
            "runtime_started": False,
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "popen_attempts": 0,
            "popen_waits": 0,
            "solver_started": False,
            "worker_started": False,
            "gpu_used_for_execution": False,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        }.items():
            _exact(side_effects, key, expected, f"report.side_effects")
        reasons = report.get("blocked_reasons")
        if not isinstance(reasons, list) or not reasons or any(not isinstance(item, str) for item in reasons):
            _fail("report.blocked_reasons must be a non-empty string list")
    except (BridgeError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_raw hidden16 terminal execution bridge",
        "",
        f"- status: `{report.get('status')}`",
        f"- mode: `{report.get('mode')}`",
        f"- launch_allowed: `{report.get('launch_allowed')}`",
        f"- fresh identity plans: `{report.get('fresh_namespaces_verified')}/{report.get('fresh_namespaces_expected')}`",
        "- Popen attempts/waits: `0/0`; process evidence: `0`; terminal evidence: `0`",
        "- terminal validator: existing v1 is synthetic-only and not execution authority",
        "- formal/credit: `false/0`",
        "",
        "## Safety boundary",
        "",
        "- default dry-run; explicit execute is rejected before Popen",
        "- no existing job is stopped or restarted",
        "- no registry, ledger, denominator, gate, completion, or PLAN writes",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {reason}" for reason in report.get("blocked_reasons", []))
    return "\n".join(lines) + "\n"


def _read_bounded_json(path: Path, name: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    if len(raw) > MAX_JSON_BYTES:
        _fail(f"{name} exceeds the bounded JSON size")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"cannot parse {name}: {error}")
    result = _mapping(value, name)
    _walk_json(result, name)
    return dict(result)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--training-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--checkpoint", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--nonce", action="append", default=[], metavar="SEED=HEX32")
    parser.add_argument("--gpu-index", action="append", default=[], metavar="SEED=GPU")
    parser.add_argument("--output-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument("--verify-report", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="reject explicitly before Popen unless a future production validator is admitted")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report is not None:
            payload = _read_bounded_json(Path(args.verify_report), "report")
            errors = validate_report(payload)
            if errors:
                _fail("; ".join(errors))
            print(canonical_json({"status": "verified", "report": str(args.verify_report)}))
            return 0
        receipt_bindings = _parse_bindings(args.training_receipt, "training-receipt") if args.training_receipt else dict(DEFAULT_RECEIPTS)
        checkpoint_bindings = _parse_bindings(args.checkpoint, "checkpoint") if args.checkpoint else None
        nonce_bindings = _parse_bindings(args.nonce, "nonce") if args.nonce else None
        gpu_bindings = _parse_gpu_bindings(args.gpu_index) if args.gpu_index else None
        report = build_report(
            args.root,
            manifest=args.manifest,
            training_receipts=receipt_bindings,
            checkpoints=checkpoint_bindings,
            nonces=nonce_bindings,
            gpu_indices=gpu_bindings,
            output_root=args.output_root,
            execute_requested=args.execute,
        )
        _write_json(args.report_output, report)
        if args.markdown_output is not None:
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
        print(canonical_json(report))
        return 0
    except (BridgeError, executor.ExecutorError, executor.identity.ContractError, OSError, TypeError, ValueError) as error:
        report = {
            "schema": REPORT_SCHEMA,
            "report_id": REPORT_ID,
            "status": "blocked_fail_closed",
            "mode": "explicit_execute_rejected" if args.execute else "dry_run",
            "execute_requested": bool(args.execute),
            "source_bound": False,
            "fresh_namespaces_verified": 0,
            "fresh_namespaces_expected": len(SEEDS),
            "exact_identity_plans_verified": 0,
            "resource_re_admission_required": True,
            "production_validator_capability_admitted": False,
            "independent_hdf5_validator_admitted": False,
            "popen_attempts": 0,
            "popen_waits": 0,
            "process_evidence_verified": 0,
            "terminal_evidence_verified": 0,
            "diagnostic_evidence_verified": 0,
            "launch_allowed": False,
            "terminal_artifact_validator_schema": synthetic_validator.REPORT_SCHEMA,
            "terminal_artifact_validator_is_synthetic_only": True,
            "expected_contract": {},
            "seed_rows": [
                {
                    "seed": seed,
                    "status": "blocked_fail_closed",
                    "popen_attempted": False,
                    "process_evidence": None,
                    "terminal_attestation": None,
                    "diagnostic_evidence": None,
                    "blocked_reasons": [str(error)],
                }
                for seed in SEEDS
            ],
            "blocked_reasons": [str(error), "bridge report construction failed closed"],
            "side_effects": {
                "runtime_started": False,
                "processes_started": 0,
                "processes_stopped": 0,
                "processes_restarted": 0,
                "popen_attempts": 0,
                "popen_waits": 0,
                "solver_started": False,
                "worker_started": False,
                "gpu_used_for_execution": False,
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
        _write_json(args.report_output, report)
        if args.markdown_output is not None:
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
        print(canonical_json(report))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
