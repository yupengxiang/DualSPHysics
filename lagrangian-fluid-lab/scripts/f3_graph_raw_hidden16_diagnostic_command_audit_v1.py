#!/usr/bin/env python3
"""Read-only audit of the graph_raw seed17 diagnostic evaluate command.

This contract is intentionally additive and independent of the graph_raw
runner and terminal execution bridges.  It binds one current-manifest v3
training receipt, its declared checkpoint identity, the exact ``evaluate``
argv produced by the existing bounded identity contract, the
``CUDA_VISIBLE_DEVICES`` to ``cuda:0`` mapping, a fresh full835 namespace and
all prospective output names, plus the current ``core_learning.py`` source
hash.

The audit opens only bounded JSON inputs and the source text needed for the
requested source hash.  The checkpoint is inspected with ``lstat`` only; its
content is never opened.  HDF5, trajectory, evaluation and progress content
is never opened.  No evaluator, subprocess, solver, worker, GPU workload or
queue is started, and no registry/ledger/gate/completion/PLAN state is
written.  Static identity binding is therefore diagnostic evidence only:
readiness, launch and credit remain false/zero.
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
import secrets
import stat
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_raw_hidden16_current_manifest_rollout_launcher_v1 as rollout


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 17
GPU_INDEX = 4
MODEL = rollout.MODEL
HIDDEN = rollout.HIDDEN
UPDATES = rollout.UPDATES
CASE_ID = rollout.CASE_ID
SPLIT = rollout.SPLIT
TRANSITIONS = rollout.TRANSITIONS
FRAMES = rollout.FRAMES

SCHEMA = "core.f3.graph_raw.hidden16.current_manifest.diagnostic_command_audit.v1"
REPORT_ID = "f3-graph-raw-hidden16-diagnostic-command-audit-seed17-v1"
DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_TRAINING_RECEIPT = Path(
    "/tmp/f3-graph_raw500-hidden16-currentmanifest-seed17-20260929-v3-training.json"
)
DEFAULT_OUTPUT_ROOT = Path("/tmp")
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RAW-HIDDEN16-DIAGNOSTIC-COMMAND-AUDIT-SEED17-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")

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


class AuditError(ValueError):
    """Malformed, drifting, unsafe or authorizing input."""


def _fail(message: str) -> None:
    raise AuditError(f"fail-closed: {message}")


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
    result = _string(value, name)
    if SHA256_RE.fullmatch(result) is None or len(set(result)) == 1:
        _fail(f"{name} must be a non-placeholder lowercase SHA-256 digest")
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


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _absolute_path(value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    path = Path(raw)
    if not path.is_absolute():
        _fail(f"{name} must be absolute")
    if any(part in {".", ".."} for part in path.parts):
        _fail(f"{name} contains a lexical path alias")
    normalized = Path(os.path.normpath(str(path)))
    if normalized != path:
        _fail(f"{name} uses a lexical path alias")
    return path


def _reject_symlink_components(path: Path, name: str, *, allow_missing_leaf: bool = False) -> None:
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


def _validate_nonce(value: Any) -> str:
    nonce = _string(value, "nonce")
    if NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail("nonce must be a non-zero 32-character lowercase hexadecimal value")
    return nonce


def _read_source_identity(path: Path) -> dict[str, Any]:
    """Read/hash only the source file, with descriptor stability checks."""

    path = _absolute_path(path, "core_learning.py")
    _reject_symlink_components(path.parent, "core_learning.py parent")
    try:
        before = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect core_learning.py: {error}")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        _fail("core_learning.py must be a regular non-symlink file")
    if before.st_nlink != 1:
        _fail("core_learning.py must have exactly one hardlink")
    if before.st_size > MAX_SOURCE_BYTES:
        _fail("core_learning.py exceeds the bounded source size")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open core_learning.py for the requested source hash: {error}")
    digest = hashlib.sha256()
    total = 0
    try:
        opened = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != identity:
            _fail("core_learning.py changed before the bounded source read")
        while total <= MAX_SOURCE_BYTES:
            block = os.read(fd, min(1024 * 1024, MAX_SOURCE_BYTES + 1 - total))
            if not block:
                break
            digest.update(block)
            total += len(block)
        closed = os.fstat(fd)
        if (closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns) != identity:
            _fail("core_learning.py changed during the bounded source read")
        if total != before.st_size:
            _fail("core_learning.py read length differs from its stat identity")
    except OSError as error:
        _fail(f"cannot read core_learning.py: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(path)
    except OSError as error:
        _fail(f"cannot inspect core_learning.py after the source read: {error}")
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ):
        _fail("core_learning.py changed after the bounded source read")
    return {
        "path": str(path),
        "bytes": int(before.st_size),
        "sha256": digest.hexdigest(),
        "mode": int(stat.S_IMODE(before.st_mode)),
        "mtime_ns": int(before.st_mtime_ns),
        "device": int(before.st_dev),
        "inode": int(before.st_ino),
        "content_opened": True,
    }


def _option(command: Sequence[str], option: str, name: str) -> str:
    positions = [index for index, token in enumerate(command) if token == option]
    if len(positions) != 1 or positions[0] + 1 >= len(command):
        _fail(f"{name} must contain exactly one {option} value")
    value = command[positions[0] + 1]
    if not isinstance(value, str) or not value:
        _fail(f"{name} {option} value must be a non-empty string")
    return value


def _audit_command(plan: Any, *, source: Mapping[str, Any], gpu_index: int) -> dict[str, Any]:
    command = tuple(plan.command)
    if len(command) < 4 or command[1] != "-u" or command[3] != "evaluate":
        _fail("exact command is not the bounded core_learning evaluate command")
    if command[2] != source["path"]:
        _fail("exact command does not bind core_learning.py source path")
    forbidden = {"--execute", "kill", "pkill", "stop", "restart"}
    if forbidden.intersection(command):
        _fail("exact evaluate command contains a forbidden execution-control token")
    expected = {
        "--manifest": str(plan.manifest),
        "--data-root": str(plan.root),
        "--checkpoint": str(plan.checkpoint["path"]),
        "--case-id": CASE_ID,
        "--split": SPLIT,
        "--maximum-steps": str(TRANSITIONS),
        "--chunk-size": str(rollout.CHUNK_SIZE),
        "--device": "cuda:0",
        "--progress-every": str(rollout.PROGRESS_EVERY),
        "--trajectory-output": str(plan.outputs["trajectory"]),
        "--progress-output": str(plan.outputs["progress"]),
        "--output": str(plan.outputs["evaluation"]),
    }
    for option, value in expected.items():
        if _option(command, option, "exact evaluate command") != value:
            _fail(f"exact evaluate command {option} drifts from the bound identity")
    if "--diagnostic" not in command:
        _fail("exact evaluate command must include --diagnostic")
    if command.count("--diagnostic") != 1:
        _fail("exact evaluate command must contain one --diagnostic marker")
    env = dict(plan.env)
    if env != {"CUDA_VISIBLE_DEVICES": str(gpu_index), "PYTHONDONTWRITEBYTECODE": "1"}:
        _fail("environment overrides drift from the exact GPU/device contract")
    if env["CUDA_VISIBLE_DEVICES"] != str(gpu_index):
        _fail("CUDA_VISIBLE_DEVICES does not bind the requested physical GPU")
    if _option(command, "--device", "exact evaluate command") != "cuda:0":
        _fail("evaluate device must remain logical cuda:0")
    command_sha256 = canonical_digest(
        {
            "argv": list(command),
            "cwd": str(plan.root),
            "env_overrides": env,
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
        }
    )
    if command_sha256 != plan.command_sha256:
        _fail("exact command digest does not match the launcher identity")
    return {
        "argv": list(command),
        "cwd": str(plan.root),
        "env_overrides": env,
        "command_sha256": command_sha256,
        "diagnostic_marker": True,
        "device_mapping": {
            "CUDA_VISIBLE_DEVICES": str(gpu_index),
            "logical_device": "cuda:0",
            "physical_gpu_index": gpu_index,
            "mapping": "cuda:0 -> physical GPU %d" % gpu_index,
        },
    }


def _freshness(plan: Any) -> dict[str, Any]:
    namespace_exists = os.path.lexists(plan.namespace)
    outputs: dict[str, Any] = {}
    for name, path in sorted(plan.outputs.items()):
        outputs[name] = {
            "path": str(path),
            "exists_before_audit": os.path.lexists(path),
            "fresh": not os.path.lexists(path),
        }
    return {
        "namespace": {
            "path": str(plan.namespace),
            "exists_before_audit": namespace_exists,
            "fresh": not namespace_exists,
        },
        "namespace_nonce": plan.nonce,
        "outputs": outputs,
        "all_paths_fresh": (not namespace_exists) and all(
            item["fresh"] for item in outputs.values()
        ),
        "namespace_created_by_audit": False,
        "output_files_created_by_audit": 0,
    }


def _blockers() -> list[str]:
    return [
        "this read-only command audit has no evaluator execution authority",
        "independent production terminal HDF5/artifact validator capability is not admitted",
        "sealed real Popen/wait process proof is not available before execution",
        "scheduler-owned one-shot namespace/output reservation is not externally attested",
        "checkpoint content SHA-256 is receipt-declared only; this audit does not open checkpoint content",
        "fresh GPU/CPU/I/O resource admission and physical-device reservation are not granted by this static audit",
    ]


def _identity_summary(plan: Any, manifest: Mapping[str, Any], manifest_source: Mapping[str, Any], training: Mapping[str, Any], training_source: Mapping[str, Any], checkpoint_stat: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    checkpoint = dict(plan.checkpoint)
    return {
        "manifest": {
            "path": str(plan.manifest),
            "schema": manifest.get("schema"),
            "canonical_sha256": plan.manifest_sha256,
            "file_sha256": plan.manifest_file_sha256,
            "file_bytes": int(manifest_source["bytes"]),
            "formal_release": manifest.get("formal_release"),
            "case_count": manifest.get("case_count"),
        },
        "training_receipt": {
            "path": str(plan.training_receipt),
            "schema": training.get("schema"),
            "file_sha256": plan.training_receipt_sha256,
            "file_bytes": int(training_source["bytes"]),
            "evidence_status": training.get("evidence_status"),
            "run_id": plan.run_id,
            "model_kind": training.get("model_kind"),
            "seed": training.get("seed"),
            "completed_updates": training.get("completed_updates"),
            "checkpoint_verified": training.get("checkpoint_verified"),
            "content_opened": True,
        },
        "checkpoint": {
            "declared": checkpoint,
            "stat_only": dict(checkpoint_stat),
            "declared_sha256_bound": True,
            "declared_bytes_bound": True,
            "content_opened": False,
            "content_sha256_revalidated": False,
        },
        "core_learning_source": dict(source),
    }


def _base_report(*, blockers: Sequence[str], error: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "status": "blocked_fail_closed",
        "mode": "read_only_seed17_diagnostic_command_audit",
        "source_bound": False,
        "training_identity_bound": False,
        "checkpoint_identity_bound": False,
        "source_hash_bound": False,
        "command_identity_bound": False,
        "namespace_identity_bound": False,
        "contract_bound": False,
        "readiness_pass": False,
        "launch_allowed": False,
        "terminal_validator_admitted": False,
        "process_proof_admitted": False,
        "popen_attempts": 0,
        "process_evidence_verified": 0,
        "terminal_evidence_verified": 0,
        "expected_contract": {
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seed": SEED,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "fresh_32_hex_nonce": True,
            "diagnostic_marker_required": True,
            "zero_credit_only": True,
        },
        "blocked_reasons": list(blockers),
        "input_boundary": {
            "bounded_manifest_json_opened": False,
            "bounded_training_receipt_json_opened": False,
            "core_learning_source_opened": False,
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "progress_content_opened": False,
            "trajectory_hdf5_content_opened": False,
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
            "namespace_created": 0,
            "output_files_created": 0,
        },
        **ZERO_CREDIT,
    }
    if error:
        report["blocked_reasons"].append(error)
    return report


def build_report(
    root: Path | str = LAB_ROOT,
    *,
    manifest: Path | str = DEFAULT_MANIFEST,
    training_receipt: Path | str = DEFAULT_TRAINING_RECEIPT,
    checkpoint: Path | str | None = None,
    nonce: str | None = None,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    gpu_index: int = GPU_INDEX,
) -> dict[str, Any]:
    """Build a single seed17 audit without creating a namespace or launching."""

    report = _base_report(blockers=_blockers())
    try:
        root_path = _absolute_path(root, "root")
        manifest_path = _absolute_path(manifest, "manifest")
        training_path = _absolute_path(training_receipt, "training_receipt")
        output_root_path = _absolute_path(output_root, "output_root")
        if type(gpu_index) is not int or not 0 <= gpu_index < rollout.GPU_COUNT:
            _fail(f"gpu_index must be an integer in [0, {rollout.GPU_COUNT})")
        selected_nonce = _validate_nonce(nonce if nonce is not None else secrets.token_hex(16))
        manifest_payload, manifest_source = rollout._read_bounded_json(
            manifest_path,
            root=root_path,
            name="manifest",
            max_bytes=rollout.MAX_MANIFEST_BYTES,
        )
        training_payload, training_source = rollout._read_bounded_json(
            training_path,
            root=root_path,
            name="training_receipt",
            max_bytes=MAX_JSON_BYTES,
        )
        declared_checkpoint = checkpoint
        if declared_checkpoint is None:
            declared_checkpoint = _mapping(
                training_payload.get("checkpoint"), "training_receipt.checkpoint"
            ).get("path")
        checkpoint_path = _absolute_path(declared_checkpoint, "checkpoint")
        namespace = output_root_path / (
            f"f3-graph_raw500-hidden16-currentmanifest-seed{SEED}-full835-nonce{selected_nonce}"
        )
        plan = rollout.build_plan(
            root_path,
            seed=SEED,
            manifest=manifest_path,
            training_receipt=training_path,
            checkpoint=checkpoint_path,
            nonce=selected_nonce,
            output_namespace=namespace,
            gpu_index=gpu_index,
        )
        source = _read_source_identity(root_path / "scripts" / "core_learning.py")
        source_metadata = plan.core_learning_metadata
        for key in ("bytes", "mode", "mtime_ns"):
            if int(source[key]) != int(source_metadata[key]):
                _fail(f"core_learning.py {key} drifted between identity checks")
        command = _audit_command(plan, source=source, gpu_index=gpu_index)
        freshness = _freshness(plan)
        if not freshness["all_paths_fresh"]:
            _fail("namespace or prospective output path is not fresh")
        checkpoint_stat = dict(plan.checkpoint_metadata)
        identity = _identity_summary(
            plan,
            manifest_payload,
            manifest_source,
            training_payload,
            training_source,
            checkpoint_stat,
            source,
        )
        report.update(
            {
                "source_bound": True,
                "training_identity_bound": True,
                "checkpoint_identity_bound": True,
                "source_hash_bound": True,
                "command_identity_bound": True,
                "namespace_identity_bound": True,
                "contract_bound": True,
                "identity": identity,
                "exact_evaluate_command": command,
                "fresh_namespace_and_outputs": freshness,
                "device_mapping": command["device_mapping"],
                "readiness_projection": {
                    "readiness_pass": False,
                    "launch_allowed": False,
                    "resource_admission_granted": False,
                    "terminal_validator_admitted": False,
                    "process_proof_admitted": False,
                    "scheduler_namespace_reserved": False,
                },
            }
        )
        report["input_boundary"].update(
            {
                "bounded_manifest_json_opened": True,
                "bounded_training_receipt_json_opened": True,
                "core_learning_source_opened": True,
            }
        )
        return report
    except (AuditError, rollout.ContractError, OSError, TypeError, ValueError) as error:
        report["blocked_reasons"].append(str(error))
        return report


def _reject_authority_aliases(value: Any, name: str = "value") -> None:
    allowed = {
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "completion_writes",
        "credit",
        "denominator_writes",
        "formal",
        "formal_release",
        "formal_eligible",
        "gate_writes",
        "launch_allowed",
        "ledger_writes",
        "plan_writes",
        "process_evidence_verified",
        "processes_restarted",
        "processes_started",
        "processes_stopped",
        "qualification",
        "qualification_credit",
        "queue_submissions",
        "registry_writes",
        "terminal_evidence_verified",
        "terminal_validator_admitted",
        "zero_credit_only",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = key.lower()
            if (
                ("credit" in lowered or "formal" in lowered or "pid" in lowered or "process_id" in lowered)
                and key not in allowed
            ):
                _fail(f"{name}.{key} is an unknown authority/process alias")
            _reject_authority_aliases(item, f"{name}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_authority_aliases(item, f"{name}[{index}]")


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        _exact(value, key, expected, name)


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _walk_json(report, "report")
        _reject_authority_aliases(report, "report")
        _exact(report, "schema", SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_fail_closed", "report")
        for key in (
            "source_bound",
            "training_identity_bound",
            "checkpoint_identity_bound",
            "source_hash_bound",
            "command_identity_bound",
            "namespace_identity_bound",
            "contract_bound",
            "readiness_pass",
            "launch_allowed",
            "terminal_validator_admitted",
            "process_proof_admitted",
        ):
            if key not in report or type(report[key]) is not bool:
                _fail(f"report.{key} must be boolean")
        _exact(report, "readiness_pass", False, "report")
        _exact(report, "launch_allowed", False, "report")
        _exact(report, "terminal_validator_admitted", False, "report")
        _exact(report, "process_proof_admitted", False, "report")
        _exact(report, "popen_attempts", 0, "report")
        _exact(report, "process_evidence_verified", 0, "report")
        _exact(report, "terminal_evidence_verified", 0, "report")
        _zero_credit(report, "report")
        blockers = report.get("blocked_reasons")
        if not isinstance(blockers, list) or not blockers or any(not isinstance(item, str) for item in blockers):
            _fail("report.blocked_reasons must be a non-empty string list")
        contract = _mapping(report.get("expected_contract"), "report.expected_contract")
        for key, expected in (
            ("model_kind", MODEL),
            ("hidden", HIDDEN),
            ("updates", UPDATES),
            ("seed", SEED),
            ("case_id", CASE_ID),
            ("split", SPLIT),
            ("transitions", TRANSITIONS),
            ("frames", FRAMES),
            ("fresh_32_hex_nonce", True),
            ("diagnostic_marker_required", True),
            ("zero_credit_only", True),
        ):
            _exact(contract, key, expected, "report.expected_contract")
        boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
        for key in (
            "checkpoint_content_opened",
            "evaluation_content_opened",
            "progress_content_opened",
            "trajectory_hdf5_content_opened",
            "runtime_started",
        ):
            _exact(boundary, key, False, "report.input_boundary")
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
            "plan_writes",
            "namespace_created",
            "output_files_created",
        ):
            if key not in side_effects or side_effects[key] not in (False, 0):
                _fail(f"report.side_effects.{key} must remain false/zero")
        if report.get("source_bound"):
            identity = _mapping(report.get("identity"), "report.identity")
            source = _mapping(identity.get("core_learning_source"), "report.identity.core_learning_source")
            _sha(source.get("sha256"), "report.identity.core_learning_source.sha256")
            if source.get("content_opened") is not True:
                _fail("source identity must record the requested source read")
            checkpoint = _mapping(identity.get("checkpoint"), "report.identity.checkpoint")
            if checkpoint.get("content_opened") is not False:
                _fail("checkpoint content must remain unopened")
            command = _mapping(report.get("exact_evaluate_command"), "report.exact_evaluate_command")
            _exact(command, "diagnostic_marker", True, "report.exact_evaluate_command")
            argv = command.get("argv")
            if not isinstance(argv, list) or not argv:
                _fail("report.exact_evaluate_command.argv must be a non-empty list")
            if "--diagnostic" not in argv:
                _fail("report exact argv must contain --diagnostic")
            mapping = _mapping(report.get("device_mapping"), "report.device_mapping")
            _exact(mapping, "logical_device", "cuda:0", "report.device_mapping")
            if mapping.get("physical_gpu_index") != GPU_INDEX:
                _fail("report.device_mapping physical GPU must remain GPU4 for seed17")
            freshness = _mapping(
                report.get("fresh_namespace_and_outputs"),
                "report.fresh_namespace_and_outputs",
            )
            _exact(freshness, "all_paths_fresh", True, "report.fresh_namespace_and_outputs")
    except (AuditError, TypeError, AttributeError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_raw hidden16 seed17 diagnostic command audit",
        "",
        f"- status: `{report.get('status')}`",
        f"- source_bound: `{report.get('source_bound')}`",
        f"- readiness_pass: `{report.get('readiness_pass')}`",
        f"- launch_allowed: `{report.get('launch_allowed')}`",
        f"- credit: `{report.get('credit')}`",
        "- contract: `graph_raw`, hidden `16`, seed `17`, updates `500`, test case `F3_DEV_00_a0p903125`, `835 transitions / 836 frames`",
        "- device mapping: physical GPU `4` exposed as logical `cuda:0` through `CUDA_VISIBLE_DEVICES=4`",
        "- boundary: bounded manifest/training JSON plus source hash; checkpoint is stat-only; HDF5/checkpoint/evaluation/progress content is not opened",
        "- side effects: no evaluator/Popen/solver/worker/GPU/queue; no registry/ledger/gate/completion/PLAN writes",
        "",
        "## Fail-closed blockers",
        "",
    ]
    for blocker in report.get("blocked_reasons", []):
        if isinstance(blocker, str):
            lines.append(f"- {blocker}")
    command = report.get("exact_evaluate_command")
    if isinstance(command, Mapping):
        lines.extend(
            [
                "",
                "## Exact command",
                "",
                "```text",
                " ".join(str(token) for token in command.get("argv", [])),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--training-receipt", type=Path, default=DEFAULT_TRAINING_RECEIPT)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--nonce")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--gpu-index", type=int, default=GPU_INDEX)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--execute", action="store_true", help="always rejected")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.execute:
            _fail("--execute is forbidden; this module is a read-only audit")
        if args.verify_report is not None:
            payload, _source = rollout._read_bounded_json(
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
        report = build_report(
            root=args.root,
            manifest=args.manifest,
            training_receipt=args.training_receipt,
            checkpoint=args.checkpoint,
            nonce=args.nonce,
            output_root=args.output_root,
            gpu_index=args.gpu_index,
        )
        errors = validate_report(report)
        if errors:
            _fail("generated report failed validation: " + "; ".join(errors))
        _write_json(args.report_output, report)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (AuditError, rollout.ContractError, OSError, TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
