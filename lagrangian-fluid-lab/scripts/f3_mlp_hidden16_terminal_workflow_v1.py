#!/usr/bin/env python3
"""Orchestrate one safe, diagnostic-only F3 MLP hidden16 terminal rollout.

The launcher remains the only component allowed to start the evaluator.  This
module supplies its two sealed post-terminal callbacks:

* the validator callback calls the independent read-only HDF5 validator through
  the sealed capability, then writes the canonical validator receipt and the
  bounded trajectory-metadata sidecar with exclusive/no-follow creation; and
* the identity callback delegates only to the existing artifact sidecar's
  ``build_identity``/``write_identity`` pair.

The default CLI mode is a dry-run.  ``--execute`` is the only path that calls
the launcher execution API.  This module never kills, restarts, or otherwise
controls an existing process, and it never writes a registry, ledger, or gate.
All receipts are diagnostic-only and permanently zero-credit.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from dataclasses import dataclass
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as validator
from scripts import f3_mlp_hidden16_artifact_identity_sidecar_v1 as sidecar
from scripts import f3_mlp_hidden16_diagnostic_rollout_launcher_v1 as launcher


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = tuple(launcher.SEEDS)
MODEL = launcher.MODEL
HIDDEN = launcher.HIDDEN
UPDATES = launcher.UPDATES
CASE_ID = launcher.CASE_ID
SPLIT = launcher.SPLIT
TRANSITIONS = launcher.TRANSITIONS
FRAMES = launcher.FRAMES
GPU_COUNT = launcher.GPU_COUNT

WORKFLOW_SCHEMA = "core.f3.mlp.hidden16.terminal_workflow.v1"
TRAJECTORY_METADATA_SCHEMA = "core.f3.mlp.hidden16.fresh_terminal.trajectory_metadata.v1"
VALIDATOR_SCHEMA = validator.SCHEMA
MAX_BOUNDED_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")

ZERO_CREDIT = {
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


class WorkflowError(ValueError):
    """Unsafe, incomplete, or drifting terminal workflow input."""


def _fail(message: str) -> None:
    raise WorkflowError(f"fail-closed: {message}")


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _walk(value: Any, name: str = "value", depth: int = 0) -> None:
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
            _walk(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 4096:
            _fail(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _walk(item, f"{name}[{index}]", depth + 1)
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


def _sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA256_RE.fullmatch(text) is None:
        _fail(f"{name} must be a lowercase SHA-256 digest")
    return text


def _nofollow_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        _fail("platform does not provide O_NOFOLLOW")
    return nofollow | getattr(os, "O_CLOEXEC", 0)


def _absolute_path(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw or not raw.startswith("/"):
        _fail(f"{name} must be an absolute path")
    if raw != os.path.normpath(raw) or any(part in {".", ".."} for part in Path(raw).parts):
        _fail(f"{name} uses a lexical path alias")
    if raw != "/" and raw.endswith("/"):
        _fail(f"{name} must not have a trailing separator")
    return Path(raw)


def _assert_no_symlink_components(path: Path, name: str, *, allow_missing_leaf: bool) -> None:
    path = _absolute_path(path, name)
    current = Path(path.anchor or "/")
    parts = path.parts[1:]
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


def _regular_file(path: Path, name: str, *, allow_missing: bool = False) -> os.stat_result | None:
    _assert_no_symlink_components(path, name, allow_missing_leaf=allow_missing)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if allow_missing:
            return None
        _fail(f"{name} is missing: {path}")
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"{name} is not a regular non-symlink file: {path}")
    if info.st_nlink != 1:
        _fail(f"{name} has {info.st_nlink} hard links")
    return info


def _artifact_identity(path: Path, name: str, *, max_bytes: int | None = None) -> dict[str, Any]:
    info = _regular_file(path, name)
    assert info is not None
    flags = os.O_RDONLY | _nofollow_flags()
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open {name} without following links: {error}")
    digest = hashlib.sha256()
    total = 0
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_nlink, opened.st_size) != (
            info.st_dev, info.st_ino, info.st_nlink, info.st_size
        ):
            _fail(f"{name} changed before streaming")
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                _fail(f"{name} exceeds {max_bytes} bytes")
            digest.update(chunk)
        closed = os.fstat(fd)
        if (closed.st_dev, closed.st_ino, closed.st_nlink, closed.st_size) != (
            info.st_dev, info.st_ino, info.st_nlink, info.st_size
        ):
            _fail(f"{name} changed while streaming")
    except OSError as error:
        _fail(f"cannot stream {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(path)
    except OSError as error:
        _fail(f"cannot re-stat {name}: {error}")
    if (after.st_dev, after.st_ino, after.st_nlink, after.st_size) != (
        info.st_dev, info.st_ino, info.st_nlink, info.st_size
    ):
        _fail(f"{name} changed after streaming")
    if total != info.st_size:
        _fail(f"{name} stream length does not match stat size")
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": total}


def _read_bounded_json(path: Path, name: str) -> tuple[Mapping[str, Any], dict[str, Any]]:
    info = _regular_file(path, name)
    assert info is not None
    flags = os.O_RDONLY | _nofollow_flags()
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot reopen {name}: {error}")
    chunks: list[bytes] = []
    total = 0
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_nlink, opened.st_size) != (
            info.st_dev, info.st_ino, info.st_nlink, info.st_size
        ):
            _fail(f"{name} changed before bounded read")
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BOUNDED_BYTES:
                _fail(f"{name} exceeds bounded JSON size")
            chunks.append(chunk)
        closed = os.fstat(fd)
        if (closed.st_dev, closed.st_ino, closed.st_nlink, closed.st_size) != (
            info.st_dev, info.st_ino, info.st_nlink, info.st_size
        ):
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    try:
        after = os.lstat(path)
    except OSError as error:
        _fail(f"cannot re-stat {name}: {error}")
    if (after.st_dev, after.st_ino, after.st_nlink, after.st_size) != (
        info.st_dev, info.st_ino, info.st_nlink, info.st_size
    ):
        _fail(f"{name} changed after bounded read")
    identity = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, WorkflowError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    value = _mapping(value, name)
    _walk(value, name)
    return value, identity


def _exclusive_json_write(path: Path, payload: Mapping[str, Any], name: str) -> None:
    path = _absolute_path(path, name)
    _assert_no_symlink_components(path, name, allow_missing_leaf=True)
    if os.path.lexists(path):
        _fail(f"refusing to overwrite existing {name}: {path}")
    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as error:
        _fail(f"cannot encode {name}: {error}")
    if len(encoded) > MAX_RECEIPT_BYTES:
        _fail(f"{name} exceeds bounded receipt size")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _nofollow_flags()
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as error:
        _fail(f"cannot exclusively create {name}: {error}")
    try:
        offset = 0
        while offset < len(encoded):
            written = os.write(fd, encoded[offset:])
            if written <= 0:
                _fail(f"short write while creating {name}")
            offset += written
        os.fsync(fd)
    except OSError as error:
        _fail(f"cannot write {name}: {error}")
    finally:
        os.close(fd)


def _expected_namespace(seed: int, nonce: str) -> Path:
    return Path(f"/tmp/f3-mlp500-hidden16-seed{seed}-full835-nonce{nonce}")


def _validate_seed_nonce(seed: Any, nonce: Any) -> tuple[int, str]:
    if type(seed) is not int or seed not in SEEDS:
        _fail(f"seed must be one of {SEEDS}")
    if not isinstance(nonce, str) or NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail("nonce must be a non-zero 32-character lowercase hexadecimal value")
    return seed, nonce


def trajectory_metadata_path(namespace: Path | str) -> Path:
    namespace = _absolute_path(namespace, "namespace")
    return Path(str(namespace) + "-trajectory-metadata.json")


def _capability_context(capability: Any) -> dict[str, Any]:
    try:
        root = _absolute_path(capability.root, "sealed capability.root")
        seed, nonce = _validate_seed_nonce(capability.seed, capability.nonce)
        evaluation = _absolute_path(capability.evaluation, "sealed capability.evaluation")
        trajectory = _absolute_path(capability.trajectory, "sealed capability.trajectory")
        validator_path = _absolute_path(capability.validator, "sealed capability.validator")
    except AttributeError as error:
        _fail(f"terminal callback requires the launcher sealed capability: {error}")
    namespace = _expected_namespace(seed, nonce)
    expected = {
        "evaluation": Path(str(namespace) + "-evaluation.json"),
        "trajectory": Path(str(namespace) + "-trajectory.h5"),
        "validator": Path(str(namespace) + "-hdf5-validation.json"),
    }
    for key, actual in (("evaluation", evaluation), ("trajectory", trajectory), ("validator", validator_path)):
        if actual != expected[key]:
            _fail(f"sealed capability {key} path drifts from the canonical namespace")
    return {
        "root": root,
        "seed": seed,
        "nonce": nonce,
        "namespace": namespace,
        "evaluation": evaluation,
        "trajectory": trajectory,
        "validator": validator_path,
    }


def _validate_validator_result(result: Mapping[str, Any], context: Mapping[str, Any]) -> None:
    allowed = {
        "schema", "passed", "fail_closed", "diagnostic_only", "synthetic_only",
        "production_artifacts_touched", "qualification_credit", "case_id",
        "evaluation_json", "trajectory_hdf5", "expected_transitions", "frames_executed",
        "complete", "incomplete", "failure_category", "checks", "row_fields_checked",
        "failure_reason",
    }
    extra = sorted(set(result) - allowed)
    if extra:
        _fail(f"validator result contains unknown fields: {extra}")
    _exact(result, "schema", VALIDATOR_SCHEMA, "validator result")
    for key, expected in (
        ("passed", True),
        ("fail_closed", False),
        ("diagnostic_only", True),
        ("synthetic_only", False),
        ("production_artifacts_touched", False),
        ("qualification_credit", 0),
        ("case_id", CASE_ID),
        ("evaluation_json", str(context["evaluation"])),
        ("trajectory_hdf5", str(context["trajectory"])),
        ("expected_transitions", TRANSITIONS),
        ("frames_executed", TRANSITIONS),
        ("complete", True),
        ("incomplete", False),
        ("failure_category", None),
    ):
        _exact(result, key, expected, "validator result")
    checks = _mapping(result.get("checks"), "validator result.checks")
    for key, expected in (
        ("case_binding", True),
        ("shape", True),
        ("time", True),
        ("valid", True),
        ("future_state_inputs", True),
        ("completion_semantics", True),
        ("trajectory_frames", FRAMES),
        ("trajectory_transitions", TRANSITIONS),
        ("executed_frame_count", FRAMES),
        ("tail_frame_count", 0),
    ):
        _exact(checks, key, expected, "validator result.checks")
    rows = result.get("row_fields_checked")
    if not isinstance(rows, list) or not rows or any(not isinstance(item, str) or not item for item in rows):
        _fail("validator result.row_fields_checked must be a non-empty string list")


def terminal_validator(capability: Any) -> None:
    """Run the independent validator and write only canonical sidecars.

    The only rollout paths accepted here come from the launcher's sealed
    capability.  The callback does not receive a plan, process, PID,
    checkpoint, or sidecar path.
    """

    context = _capability_context(capability)
    for key in ("evaluation", "trajectory"):
        _regular_file(context[key], f"terminal {key}")
    result = validator.run_validation(
        context["evaluation"],
        context["trajectory"],
        case_id=CASE_ID,
        expected_transitions=TRANSITIONS,
    )
    result = _mapping(result, "validator result")
    _walk(result, "validator result")
    _validate_validator_result(result, context)
    _exclusive_json_write(context["validator"], result, "validator receipt")

    trajectory = _artifact_identity(context["trajectory"], "trajectory HDF5")
    metadata = {
        "schema": TRAJECTORY_METADATA_SCHEMA,
        "seed": context["seed"],
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "namespace": str(context["namespace"]),
        "namespace_nonce": context["nonce"],
        "trajectory": trajectory,
        "stream_hash": {
            "algorithm": "sha256",
            "sha256": trajectory["sha256"],
            "bytes": trajectory["bytes"],
        },
        "diagnostic_only": True,
        "source_bound": True,
        "future_state_inputs": False,
    }
    _exclusive_json_write(
        trajectory_metadata_path(context["namespace"]),
        metadata,
        "trajectory metadata",
    )


def artifact_identity_producer(capability: Any) -> None:
    """Delegate identity creation exclusively to the existing sidecar."""

    try:
        identity = sidecar.build_identity(
            capability.root,
            seed=capability.seed,
            nonce=capability.nonce,
            evaluation_json=capability.evaluation_json,
            trajectory_hdf5=capability.trajectory_hdf5,
            validator_receipt=capability.validator_receipt,
        )
        sidecar.write_identity(
            identity,
            root=capability.root,
            seed=capability.seed,
            nonce=capability.nonce,
            output=capability.sidecar,
        )
    except AttributeError as error:
        _fail(f"artifact producer requires the launcher sealed capability: {error}")


@dataclass(frozen=True)
class TerminalWorkflowPlan:
    rollout: Any
    trajectory_metadata: Path
    gpu_index: int

    @property
    def namespace(self) -> Path:
        return self.rollout.namespace

    def as_receipt(self) -> dict[str, Any]:
        outputs = self.rollout.outputs
        return {
            "schema": WORKFLOW_SCHEMA,
            "status": "dry_run_ready",
            "mode": "dry_run",
            "launched": False,
            "seed": self.rollout.seed,
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "gpu_index": self.gpu_index,
            "namespace": str(self.rollout.namespace),
            "namespace_nonce": self.rollout.nonce,
            "command_sha256": self.rollout.command_sha256,
            "outputs": {
                "evaluation": str(outputs["evaluation"]),
                "trajectory": str(outputs["trajectory"]),
                "validator": str(outputs["validator"]),
                "trajectory_metadata": str(self.trajectory_metadata),
                "artifact_identity": str(outputs["artifact_identity"]),
                "process_proof": str(outputs["process_proof"]),
            },
            **ZERO_CREDIT,
            "side_effects": {
                "processes_started": 0,
                "processes_stopped": 0,
                "processes_restarted": 0,
                "registry_writes": 0,
                "ledger_writes": 0,
                "gate_writes": 0,
            },
        }


def build_workflow_plan(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    nonce: str | None = None,
    namespace: Path | str | None = None,
    gpu_index: int = 0,
    history_summary: Path | str | None = None,
    training_matrix: Path | str | None = None,
) -> TerminalWorkflowPlan:
    """Build a non-launching wrapper around the hardened launcher plan."""

    if nonce is None:
        nonce = os.urandom(16).hex()
    seed, nonce = _validate_seed_nonce(seed, nonce)
    if type(gpu_index) is not int or not 0 <= gpu_index < GPU_COUNT:
        _fail(f"gpu_index must be an integer in [0, {GPU_COUNT})")
    rollout = launcher.build_plan(
        root,
        seed=seed,
        nonce=nonce,
        namespace=namespace,
        gpu_index=gpu_index,
        history_summary=history_summary,
        training_matrix=training_matrix,
    )
    metadata = trajectory_metadata_path(rollout.namespace)
    if _regular_file(metadata, "trajectory metadata", allow_missing=True) is not None:
        _fail("trajectory metadata output already exists")
    return TerminalWorkflowPlan(rollout=rollout, trajectory_metadata=metadata, gpu_index=gpu_index)


def _validate_process_proof(payload: Mapping[str, Any], plan: TerminalWorkflowPlan) -> None:
    allowed = {
        "schema", "report_id", "status", "source_bound", "diagnostic_only",
        "formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path",
        "qualification", "qualification_credit", "credit", "seed", "run_id",
        "namespace", "namespace_nonce", "evaluator_alive", "launcher_alive",
        "evaluator_returncode", "launcher_returncode", "returncode",
        "evaluator_pid_observed", "launcher_pid_observed", "evaluator_reaped",
        "launcher_reaped", "command_sha256", "exit_proof_sha256",
        "evaluator_start_identity", "evaluator_end_identity", "launcher_start_identity",
        "launcher_end_identity", "manifest_sha256", "training_manifest_sha256",
        "training_receipt_sha256", "checkpoint", "evaluation", "trajectory", "validator",
    }
    extra = sorted(set(payload) - allowed)
    if extra:
        _fail(f"process proof contains unknown fields: {extra}")
    _exact(payload, "schema", f"core.f3.mlp.hidden16.seed{plan.rollout.seed}.process_exit_proof.v1", "process proof")
    for key, expected in (
        ("status", "exited_successfully"),
        ("source_bound", True),
        ("diagnostic_only", True),
        ("seed", plan.rollout.seed),
        ("run_id", plan.rollout.run_id),
        ("namespace", str(plan.rollout.namespace)),
        ("namespace_nonce", plan.rollout.nonce),
        ("evaluator_alive", False),
        ("launcher_alive", False),
        ("evaluator_returncode", 0),
        ("launcher_returncode", 0),
        ("returncode", 0),
        ("evaluator_reaped", True),
        ("launcher_reaped", True),
    ):
        _exact(payload, key, expected, "process proof")
    for key, expected in ZERO_CREDIT.items():
        _exact(payload, key, expected, "process proof")
    proof_digest = _sha(payload.get("exit_proof_sha256"), "process proof.exit_proof_sha256")
    without_digest = dict(payload)
    without_digest.pop("exit_proof_sha256", None)
    canonical = json.dumps(without_digest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if hashlib.sha256(canonical).hexdigest() != proof_digest:
        _fail("process proof self-digest is invalid")
    for key, expected in (
        ("evaluation", plan.rollout.outputs["evaluation"]),
        ("trajectory", plan.rollout.outputs["trajectory"]),
        ("validator", plan.rollout.outputs["validator"]),
    ):
        artifact = _mapping(payload.get(key), f"process proof.{key}")
        _exact(artifact, "path", str(expected), f"process proof.{key}")


def _validate_sidecar_payload(
    payload: Mapping[str, Any],
    plan: TerminalWorkflowPlan,
    *,
    trajectory: Mapping[str, Any],
    validator_receipt: Mapping[str, Any],
) -> None:
    _exact(
        payload,
        "schema",
        f"core.f3.mlp.hidden16.seed{plan.rollout.seed}.evaluator_artifact_identity.v1",
        "artifact identity",
    )
    for key, expected in (
        ("status", "completed_diagnostic"),
        ("seed", plan.rollout.seed),
        ("run_id", plan.rollout.run_id),
        ("namespace", str(plan.rollout.namespace)),
        ("namespace_nonce", plan.rollout.nonce),
        ("diagnostic_only", True),
    ):
        _exact(payload, key, expected, "artifact identity")
    for key, expected in ZERO_CREDIT.items():
        _exact(payload, key, expected, "artifact identity")
    for key, expected in (
        ("evaluation", plan.rollout.outputs["evaluation"]),
        ("trajectory", plan.rollout.outputs["trajectory"]),
        ("validator", plan.rollout.outputs["validator"]),
    ):
        artifact = _mapping(payload.get(key), f"artifact identity.{key}")
        _exact(artifact, "path", str(expected), f"artifact identity.{key}")
    sidecar_trajectory = _mapping(payload.get("trajectory"), "artifact identity.trajectory")
    if sidecar_trajectory.get("sha256") != trajectory["sha256"] or sidecar_trajectory.get("bytes") != trajectory["bytes"]:
        _fail("artifact identity trajectory identity drifts from the streamed trajectory")
    sidecar_validator = _mapping(payload.get("validator"), "artifact identity.validator")
    if sidecar_validator.get("sha256") != validator_receipt["sha256"] or sidecar_validator.get("bytes") != validator_receipt["bytes"]:
        _fail("artifact identity validator identity drifts from the validator receipt")


def _validate_metadata(payload: Mapping[str, Any], plan: TerminalWorkflowPlan, trajectory: Mapping[str, Any]) -> None:
    allowed = {
        "schema", "seed", "model", "hidden", "updates", "case_id", "split",
        "transitions", "frames", "namespace", "namespace_nonce", "trajectory",
        "stream_hash", "diagnostic_only", "source_bound", "future_state_inputs",
    }
    extra = sorted(set(payload) - allowed)
    if extra:
        _fail(f"trajectory metadata contains unknown fields: {extra}")
    for key, expected in (
        ("schema", TRAJECTORY_METADATA_SCHEMA),
        ("seed", plan.rollout.seed),
        ("model", MODEL),
        ("hidden", HIDDEN),
        ("updates", UPDATES),
        ("case_id", CASE_ID),
        ("split", SPLIT),
        ("transitions", TRANSITIONS),
        ("frames", FRAMES),
        ("namespace", str(plan.rollout.namespace)),
        ("namespace_nonce", plan.rollout.nonce),
        ("diagnostic_only", True),
        ("source_bound", True),
        ("future_state_inputs", False),
    ):
        _exact(payload, key, expected, "trajectory metadata")
    observed = _mapping(payload.get("trajectory"), "trajectory metadata.trajectory")
    if dict(observed) != dict(trajectory):
        _fail("trajectory metadata trajectory identity drifted")
    stream = _mapping(payload.get("stream_hash"), "trajectory metadata.stream_hash")
    _exact(stream, "algorithm", "sha256", "trajectory metadata.stream_hash")
    _exact(stream, "sha256", trajectory["sha256"], "trajectory metadata.stream_hash")
    _exact(stream, "bytes", trajectory["bytes"], "trajectory metadata.stream_hash")


def execute_workflow(plan: TerminalWorkflowPlan) -> dict[str, Any]:
    """Execute exactly one fresh diagnostic rollout through launcher callbacks."""

    result = launcher.execute_plan(
        plan.rollout,
        artifact_identity_path=plan.rollout.outputs["artifact_identity"],
        terminal_validator=terminal_validator,
        artifact_identity_producer=artifact_identity_producer,
    )
    if not isinstance(result, Mapping) or result.get("status") != "exited_successfully" or result.get("proof_written") is not True:
        _fail("launcher did not return a completed terminal proof")

    proof_payload, proof_identity = _read_bounded_json(plan.rollout.proof_output, "process proof")
    _validate_process_proof(proof_payload, plan)
    trajectory_identity = _artifact_identity(plan.rollout.outputs["trajectory"], "trajectory HDF5")
    validator_payload, validator_identity = _read_bounded_json(plan.rollout.outputs["validator"], "validator receipt")
    _validate_validator_result(
        validator_payload,
        {"evaluation": plan.rollout.outputs["evaluation"], "trajectory": plan.rollout.outputs["trajectory"]},
    )
    sidecar_payload, sidecar_identity = _read_bounded_json(plan.rollout.outputs["artifact_identity"], "artifact identity")
    _validate_sidecar_payload(
        sidecar_payload,
        plan,
        trajectory=trajectory_identity,
        validator_receipt=validator_identity,
    )
    metadata_payload, metadata_identity = _read_bounded_json(plan.trajectory_metadata, "trajectory metadata")
    _validate_metadata(metadata_payload, plan, trajectory_identity)

    receipt = {
        "schema": WORKFLOW_SCHEMA,
        "status": "exited_successfully",
        "mode": "execute",
        "launched": True,
        "seed": plan.rollout.seed,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "gpu_index": plan.gpu_index,
        "namespace": str(plan.rollout.namespace),
        "namespace_nonce": plan.rollout.nonce,
        "validator": validator_identity,
        "trajectory_metadata": metadata_identity,
        "artifact_identity": sidecar_identity,
        "process_proof": proof_identity,
        "trusted_process_proof_sha256": proof_identity["sha256"],
        "process_proof_declared_digest": proof_payload["exit_proof_sha256"],
        **ZERO_CREDIT,
        "side_effects": {
            "processes_started": 1,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "gate_writes": 0,
        },
    }
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_RECEIPT_BYTES:
        _fail("workflow receipt exceeds bounded size")
    return receipt


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--seed", type=int, required=True, choices=SEEDS)
    parser.add_argument("--nonce", default=None, help="new 32-character lowercase hexadecimal nonce; generated when omitted")
    parser.add_argument("--namespace", default=None)
    parser.add_argument("--gpu-index", type=int, default=0, choices=range(GPU_COUNT))
    parser.add_argument("--history-summary", type=Path, default=None)
    parser.add_argument("--training-matrix", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="explicitly launch one fresh diagnostic evaluator")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        plan = build_workflow_plan(
            args.root,
            seed=args.seed,
            nonce=args.nonce,
            namespace=args.namespace,
            gpu_index=args.gpu_index,
            history_summary=args.history_summary,
            training_matrix=args.training_matrix,
        )
        output = execute_workflow(plan) if args.execute else plan.as_receipt()
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (WorkflowError, launcher.LauncherError, OSError, RecursionError) as error:
        print(
            json.dumps(
                {
                    "schema": WORKFLOW_SCHEMA,
                    "status": "blocked_fail_closed",
                    "diagnostic_only": True,
                    "credit": 0,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
