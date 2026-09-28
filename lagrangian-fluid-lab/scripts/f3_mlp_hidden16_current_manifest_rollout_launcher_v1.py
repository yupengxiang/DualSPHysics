#!/usr/bin/env python3
"""Parameterized, diagnostic-only F3 MLP hidden16 rollout adapter.

The historical ``f3_mlp_hidden16_diagnostic_rollout_launcher_v1`` is kept
unchanged because it intentionally binds the 2026-09-28 training matrix,
history summaries, checkpoint names, and dataset path.  This additive adapter
is the current-manifest entry point.  It requires an explicit manifest,
completed training receipt, checkpoint, run id, nonce, and output namespace;
none of those values are inferred from the historical V1 artifacts.

The adapter reuses the historical launcher's stable-FD, exact-command,
procfs-binding, natural-exit, and zero-credit execution engine.  Its default
mode is a dry run.  ``--execute`` is the only path that can start one
diagnostic evaluator.  It never kills or restarts a process and never writes a
registry, ledger, denominator, gate, or PLAN file.

The training receipt is bounded JSON metadata only.  The manifest is read and
canonically hashed exactly as ``CoreDataset`` binds it; the checkpoint is only
stat'd and is never opened by this adapter.  The terminal callback opens only
the evaluator's fresh evaluation/HDF5 outputs to create the independent
validator receipt and trajectory metadata.  All accepted evidence remains
diagnostic-only and permanently zero-credit.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_full_rollout_receipt_hdf5_validator_v1 as validator
from scripts import f3_mlp_hidden16_diagnostic_rollout_launcher_v1 as legacy


LAB_ROOT = Path(__file__).resolve().parents[1]
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836
CHUNK_SIZE = 34560
PROGRESS_EVERY = 25
GPU_COUNT = 8

TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
VALIDATOR_SCHEMA = validator.SCHEMA
SCHEMA = "core.f3.mlp.hidden16.current_manifest_rollout_launcher_plan.v1"
TRAJECTORY_METADATA_SCHEMA = "core.f3.mlp.hidden16.current_manifest.trajectory_metadata.v1"
MAX_TRAINING_RECEIPT_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_PROCESS_PROOF_NAME_BYTES = 180
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

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

# Re-export the execution-contract constants that callers of the historical
# launcher commonly use, while keeping the current adapter's schema separate.
LauncherError = legacy.LauncherError


def _fail(message: str) -> None:
    raise LauncherError(f"fail-closed: {message}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    text = _string(value, name)
    if SHA256_RE.fullmatch(text) is None:
        _fail(f"{name} must be a lowercase SHA-256 digest")
    return text


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


def _walk_finite(value: Any, name: str = "value", depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
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
            _walk_finite(item, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_ARRAY_ITEMS:
            _fail(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _walk_finite(item, f"{name}[{index}]", depth + 1)
        return
    _fail(f"{name} contains unsupported type {type(value).__name__}")


def _absolute_path(value: Path | str, name: str, *, root: Path | None = None) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        if root is None:
            _fail(f"{name} must be absolute")
        candidate = root / candidate
    normalized = os.path.normpath(str(candidate))
    if str(candidate) != normalized:
        _fail(f"{name} uses a lexical path alias")
    path = Path(normalized)
    if "." in path.parts or ".." in path.parts:
        _fail(f"{name} contains a path alias component")
    if str(path) != "/" and str(path).endswith("/"):
        _fail(f"{name} must not have a trailing separator")
    return path


def _root_path(value: Path | str) -> Path:
    path = _absolute_path(os.path.abspath(os.fspath(value)), "root")
    # The legacy engine snapshots every root directory component before it
    # launches.  Perform the same check while building the current plan.
    legacy._directory_snapshot(path, "root")
    return path


def _read_bounded_json(
    path: Path | str,
    *,
    root: Path,
    name: str,
    max_bytes: int,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Read one small JSON object with an identity check around the read."""

    candidate = _absolute_path(path, name, root=root)
    info = legacy._regular_single_link(candidate, name)
    assert info is not None
    if info.st_size > max_bytes:
        _fail(f"{name} exceeds {max_bytes} bytes")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    chunks: list[bytes] = []
    try:
        opened = os.fstat(fd)
        expected_identity = legacy._file_identity(info)
        if legacy._file_identity(opened) != expected_identity:
            _fail(f"{name} changed before bounded read")
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        if total > max_bytes:
            _fail(f"{name} exceeds {max_bytes} bytes")
        closed = os.fstat(fd)
        if legacy._file_identity(closed) != expected_identity:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot re-stat {name}: {error}")
    if legacy._file_identity(after) != expected_identity:
        _fail(f"{name} changed after bounded read")
    raw = b"".join(chunks)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=legacy._reject_duplicate_keys,
            parse_constant=legacy._reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, LauncherError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    payload = _mapping(payload, name)
    _walk_finite(payload, name)
    return payload, {
        "path": str(candidate),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _canonical_manifest_sha(payload: Mapping[str, Any]) -> str:
    """Match ``CoreDataset.manifest_sha256``'s canonical JSON hash."""

    try:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        _fail(f"manifest cannot be canonically hashed: {error}")
    return hashlib.sha256(encoded).hexdigest()


def _validate_run_id(value: Any) -> str:
    run_id = _string(value, "run_id")
    if len(run_id.encode("utf-8")) > 128 or RUN_ID_RE.fullmatch(run_id) is None:
        _fail("run_id must be a short lexical identifier without path separators")
    return run_id


def _validate_seed(value: Any) -> int:
    seed = _strict_int(value, "seed", 0)
    if seed > 2**31 - 1:
        _fail("seed exceeds the supported signed 32-bit range")
    return seed


def _validate_nonce(value: Any) -> str:
    nonce = _string(value, "nonce")
    if legacy.NONCE_RE.fullmatch(nonce) is None or nonce == "0" * 32:
        _fail("nonce must be a non-zero 32-character lowercase hexadecimal value")
    return nonce


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    for key, expected in ZERO_CREDIT.items():
        if key in value:
            _exact(value, key, expected, name)


def _checkpoint_metadata(value: Any, name: str) -> dict[str, Any]:
    item = _mapping(value, name)
    _exact(item, "schema", CHECKPOINT_SCHEMA, name)
    _exact(item, "update", UPDATES, name)
    path = _absolute_path(_string(item.get("path"), f"{name}.path"), f"{name}.path")
    if path.suffix.lower() == ".json":
        _fail(f"{name}.path must not point to a JSON receipt")
    result = {
        "path": str(path),
        "sha256": _sha(item.get("sha256"), f"{name}.sha256"),
        "bytes": _strict_int(item.get("bytes"), f"{name}.bytes", 1),
    }
    return result


def _validate_training_receipt(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    root: Path,
    seed: int,
    run_id: str,
    manifest_sha256: str,
    checkpoint_path: Path,
) -> dict[str, Any]:
    name = "training_receipt"
    _exact(payload, "schema", TRAINING_SCHEMA, name)
    # ``core_learning.train`` emits ``evidence_status``/``completed_updates``
    # as its terminal status and does not add a redundant top-level
    # ``status`` field.  Accept that native shape; if an intake wrapper adds
    # ``status``, it must still be the same completed state.
    if "status" in payload:
        _exact(payload, "status", "completed", name)
    _exact(payload, "evidence_status", "complete", name)
    _exact(payload, "checkpoint_verified", True, name)
    _exact(payload, "model_kind", MODEL, name)
    _exact(payload, "seed", seed, name)
    _exact(payload, "completed_updates", UPDATES, name)
    _exact(payload, "run_id", run_id, name)
    _zero_credit(payload, name)
    config = _mapping(payload.get("config"), f"{name}.config")
    _exact(config, "manifest_sha256", manifest_sha256, f"{name}.config")
    _exact(config, "model_kind", MODEL, f"{name}.config")
    _exact(config, "hidden", HIDDEN, f"{name}.config")
    _exact(config, "updates", UPDATES, f"{name}.config")
    _exact(config, "run_id", run_id, f"{name}.config")
    _exact(config, "seed", seed, f"{name}.config")
    _exact(config, "manifest_formal_release", False, f"{name}.config")
    _exact(config, "validation_formal_eligible", False, f"{name}.config")
    for key in ("paired_seed", "sampler_seed"):
        if key in config:
            _exact(config, key, seed, f"{name}.config")

    checkpoint = _checkpoint_metadata(payload.get("checkpoint"), f"{name}.checkpoint")
    if Path(checkpoint["path"]) != checkpoint_path:
        _fail("training receipt checkpoint path differs from --checkpoint")
    if Path(checkpoint["path"]) == Path(source["path"]):
        _fail("training receipt checkpoint aliases the training receipt")
    checkpoint_info = legacy._regular_single_link(checkpoint_path, "checkpoint input")
    assert checkpoint_info is not None
    if checkpoint_info.st_size != checkpoint["bytes"]:
        _fail("checkpoint bytes differ from the completed training receipt")

    checkpoints = payload.get("checkpoints")
    if checkpoints is not None:
        if not isinstance(checkpoints, list) or not checkpoints:
            _fail("training_receipt.checkpoints must be a non-empty array")
        terminal = None
        for index, value in enumerate(checkpoints):
            terminal = _checkpoint_metadata(value, f"{name}.checkpoints[{index}]")
        if terminal != checkpoint:
            _fail("training receipt terminal checkpoint identity drifts")

    return {
        "run_id": run_id,
        "checkpoint": checkpoint,
        "training_receipt": {
            "path": str(source["path"]),
            "sha256": source["sha256"],
            "bytes": source["bytes"],
        },
    }


def _proof_filename(run_id: str, nonce: str, manifest_sha256: str) -> str:
    digest = hashlib.sha256(
        f"{run_id}\0{nonce}\0{manifest_sha256}".encode("utf-8")
    ).hexdigest()[:32]
    filename = f"F3-MLP-HIDDEN16-CURRENT-MANIFEST-{digest}-PROCESS-EXIT-PROOF-V1.json"
    if len(filename.encode("utf-8")) > MAX_PROCESS_PROOF_NAME_BYTES:
        _fail("generated process proof filename exceeds the bounded name limit")
    return filename


def _output_paths(namespace: Path, root: Path, proof_filename: str) -> dict[str, Path]:
    prefix = str(namespace)
    return {
        "namespace": namespace,
        "evaluation": Path(prefix + "-evaluation.json"),
        "trajectory": Path(prefix + "-trajectory.h5"),
        "progress": Path(prefix + "-evaluation-progress.json"),
        "log": Path(prefix + "-evaluation.log"),
        "artifact_identity": Path(prefix + "-artifact-identity.json"),
        "validator": Path(prefix + "-hdf5-validation.json"),
        "process_proof": root / "reports" / proof_filename,
    }


def _trajectory_metadata_path(namespace: Path) -> Path:
    return Path(str(namespace) + "-trajectory-metadata.json")


def _validate_output_namespace(namespace: Path, root: Path) -> None:
    allowed_parents = (Path("/tmp"), root / "reports")
    if namespace in allowed_parents or not any(parent in namespace.parents for parent in allowed_parents):
        _fail("output_namespace must remain under /tmp or root/reports")


def _validate_outputs(
    outputs: Mapping[str, Path],
    trajectory_metadata: Path,
    *,
    root: Path,
) -> None:
    expected_proof_parent = root / "reports"
    for name, path in outputs.items():
        if name == "process_proof" and path.parent != expected_proof_parent:
            _fail("process proof must remain in root/reports")
        _absolute = legacy._absolute_text(str(path), f"output.{name}")
        if _absolute != path:
            _fail(f"output.{name} path normalization drifted")
        legacy._collision(path, f"output.{name}")
    legacy._collision(trajectory_metadata, "output.trajectory_metadata")


@dataclass(frozen=True)
class CurrentManifestRolloutPlan:
    root: Path
    seed: int
    run_id: str
    nonce: str
    manifest: Path
    manifest_sha256: str
    manifest_file_sha256: str
    checkpoint_path: Path
    checkpoint: Mapping[str, Any]
    training_receipt: Path
    training_receipt_sha256: str
    output_namespace: Path
    trajectory_metadata: Path
    outputs: Mapping[str, Path]
    command: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    command_sha256: str
    gpu_index: int
    training_receipt_snapshot: Mapping[str, Any]
    legacy_plan: Any
    proof_filename: str

    @property
    def namespace(self) -> Path:
        return self.output_namespace

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "status": "dry_run_ready",
            "mode": "dry_run",
            "launched": False,
            "seed": self.seed,
            "run_id": self.run_id,
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "case_id": CASE_ID,
            "split": SPLIT,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "gpu_index": self.gpu_index,
            "manifest": str(self.manifest),
            "manifest_sha256": self.manifest_sha256,
            "manifest_file_sha256": self.manifest_file_sha256,
            "checkpoint": dict(self.checkpoint),
            "training_receipt": str(self.training_receipt),
            "training_receipt_sha256": self.training_receipt_sha256,
            "output_namespace": str(self.output_namespace),
            "namespace_nonce": self.nonce,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "env_overrides": dict(self.env),
            "command_sha256": self.command_sha256,
            "outputs": {key: str(value) for key, value in self.outputs.items()},
            "trajectory_metadata": str(self.trajectory_metadata),
            "process_proof_filename": self.proof_filename,
            **ZERO_CREDIT,
            "zero_credit_only": True,
            "side_effects": {
                "processes_started": 0,
                "processes_stopped": 0,
                "processes_restarted": 0,
                "registry_writes": 0,
                "ledger_writes": 0,
                "denominator_writes": 0,
                "gate_writes": 0,
                "plan_writes": 0,
            },
            "input_boundary": {
                "bounded_training_receipt_opened": True,
                "manifest_content_opened": True,
                "checkpoint_content_opened": False,
                "evaluation_content_opened": False,
                "trajectory_hdf5_opened": False,
                "runtime_started": False,
                "queue_submissions": 0,
            },
        }


def build_plan(
    root: Path | str = LAB_ROOT,
    *,
    seed: int,
    manifest: Path | str,
    checkpoint: Path | str,
    training_receipt: Path | str,
    run_id: str,
    nonce: str,
    output_namespace: Path | str,
    gpu_index: int = 0,
    python_executable: Path | str | None = None,
) -> CurrentManifestRolloutPlan:
    """Build a non-launching current-manifest rollout plan."""

    root = _root_path(root)
    seed = _validate_seed(seed)
    run_id = _validate_run_id(run_id)
    nonce = _validate_nonce(nonce)
    if type(gpu_index) is not int or not 0 <= gpu_index < GPU_COUNT:
        _fail(f"gpu_index must be an integer in [0, {GPU_COUNT})")

    manifest_path = _absolute_path(manifest, "manifest", root=root)
    checkpoint_path = _absolute_path(checkpoint, "checkpoint", root=root)
    training_path = _absolute_path(training_receipt, "training_receipt", root=root)
    namespace = _absolute_path(output_namespace, "output_namespace", root=root)
    _validate_output_namespace(namespace, root)

    manifest_payload, manifest_source = _read_bounded_json(
        manifest_path,
        root=root,
        name="manifest",
        max_bytes=MAX_MANIFEST_BYTES,
    )
    if manifest_payload.get("formal_release") is True:
        _fail("current-manifest diagnostic launcher refuses a formal_release manifest")
    manifest_sha256 = _canonical_manifest_sha(manifest_payload)

    training_payload, training_source = _read_bounded_json(
        training_path,
        root=root,
        name="training_receipt",
        max_bytes=MAX_TRAINING_RECEIPT_BYTES,
    )
    training = _validate_training_receipt(
        training_payload,
        training_source,
        root=root,
        seed=seed,
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        checkpoint_path=checkpoint_path,
    )

    python = _absolute_path(
        python_executable if python_executable is not None else root / ".venv" / "bin" / "python",
        "python_executable",
        root=root,
    )
    core_learning = root / "scripts" / "core_learning.py"
    root_identity = tuple(legacy._directory_snapshot(root, "root"))
    input_snapshots = {
        "interpreter": legacy._input_snapshot(python, "Python executable", allow_leaf_symlink=True),
        "core_learning": legacy._input_snapshot(core_learning, "core_learning.py", allow_leaf_symlink=False),
        "manifest": legacy._input_snapshot(manifest_path, "manifest input", allow_leaf_symlink=False),
        "checkpoint": legacy._input_snapshot(checkpoint_path, "checkpoint input", allow_leaf_symlink=False),
    }
    training_snapshot = legacy._input_snapshot(
        training_path, "training receipt input", allow_leaf_symlink=False
    )

    proof_filename = _proof_filename(run_id, nonce, manifest_sha256)
    outputs = _output_paths(namespace, root, proof_filename)
    trajectory_metadata = _trajectory_metadata_path(namespace)
    _validate_outputs(outputs, trajectory_metadata, root=root)

    command = (
        str(python),
        "-u",
        str(core_learning),
        "evaluate",
        "--manifest",
        str(manifest_path),
        "--data-root",
        str(root),
        "--checkpoint",
        str(checkpoint_path),
        "--case-id",
        CASE_ID,
        "--split",
        SPLIT,
        "--maximum-steps",
        str(TRANSITIONS),
        "--chunk-size",
        str(CHUNK_SIZE),
        "--device",
        "cuda:0",
        "--progress-every",
        str(PROGRESS_EVERY),
        "--trajectory-output",
        str(outputs["trajectory"]),
        "--progress-output",
        str(outputs["progress"]),
        "--output",
        str(outputs["evaluation"]),
        "--diagnostic",
    )
    env = {"CUDA_VISIBLE_DEVICES": str(gpu_index), "PYTHONDONTWRITEBYTECODE": "1"}
    site_packages = legacy._venv_site_packages(python)
    if site_packages is not None:
        env["PYTHONPATH"] = site_packages
    command_sha256 = legacy._canonical_digest(
        {"argv": list(command), "cwd": str(root), "env_overrides": env}
    )

    legacy_plan = legacy.RolloutPlan(
        root=root,
        seed=seed,
        nonce=nonce,
        namespace=namespace,
        run_id=run_id,
        command=command,
        cwd=root,
        env=env,
        command_sha256=command_sha256,
        outputs=outputs,
        manifest_sha256=manifest_sha256,
        training_manifest_sha256=manifest_sha256,
        training_receipt_sha256=training_source["sha256"],
        checkpoint=training["checkpoint"],
        history_summary=training_path,
        training_matrix=training_path,
        proof_output=outputs["process_proof"],
        root_identity=root_identity,
        input_snapshots=input_snapshots,
    )
    return CurrentManifestRolloutPlan(
        root=root,
        seed=seed,
        run_id=run_id,
        nonce=nonce,
        manifest=manifest_path,
        manifest_sha256=manifest_sha256,
        manifest_file_sha256=manifest_source["sha256"],
        checkpoint_path=checkpoint_path,
        checkpoint=training["checkpoint"],
        training_receipt=training_path,
        training_receipt_sha256=training_source["sha256"],
        output_namespace=namespace,
        trajectory_metadata=trajectory_metadata,
        outputs=outputs,
        command=command,
        cwd=root,
        env=env,
        command_sha256=command_sha256,
        gpu_index=gpu_index,
        training_receipt_snapshot=training_snapshot,
        legacy_plan=legacy_plan,
        proof_filename=proof_filename,
    )


def _stream_identity(path: Path, name: str) -> dict[str, Any]:
    info = legacy._regular_single_link(path, name)
    assert info is not None
    expected = legacy._file_identity(info)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    digest = hashlib.sha256()
    total = 0
    try:
        if legacy._file_identity(os.fstat(fd)) != expected:
            _fail(f"{name} changed before streaming")
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            total += len(block)
            digest.update(block)
        if legacy._file_identity(os.fstat(fd)) != expected:
            _fail(f"{name} changed while streaming")
    except OSError as error:
        _fail(f"cannot stream {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(path)
    except OSError as error:
        _fail(f"cannot re-stat {name}: {error}")
    if legacy._file_identity(after) != expected or total != info.st_size:
        _fail(f"{name} changed after streaming")
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": total}


def _validate_capability_paths(plan: CurrentManifestRolloutPlan, capability: Any) -> None:
    expected = {
        "evaluation": plan.outputs["evaluation"],
        "trajectory": plan.outputs["trajectory"],
        "validator": plan.outputs["validator"],
    }
    for key, path in expected.items():
        try:
            observed = Path(getattr(capability, key))
        except AttributeError as error:
            _fail(f"sealed terminal capability lacks {key}: {error}")
        if observed != path:
            _fail(f"sealed terminal capability {key} path drifted")


def _write_terminal_validator(plan: CurrentManifestRolloutPlan, capability: Any) -> None:
    _validate_capability_paths(plan, capability)
    result = validator.run_validation(
        plan.outputs["evaluation"],
        plan.outputs["trajectory"],
        case_id=CASE_ID,
        expected_transitions=TRANSITIONS,
    )
    result = _mapping(result, "validator result")
    _walk_finite(result, "validator result")
    # Reuse the historical receipt validator, but feed it the explicitly
    # parameterized legacy plan rather than the old hard-coded build_plan.
    legacy._validate_completed_validator_receipt(
        result, plan.legacy_plan, "current-manifest validator"
    )
    legacy._exclusive_json_write(
        plan.outputs["validator"], result, "validator receipt"
    )
    trajectory = _stream_identity(plan.outputs["trajectory"], "trajectory HDF5")
    metadata = {
        "schema": TRAJECTORY_METADATA_SCHEMA,
        "seed": plan.seed,
        "run_id": plan.run_id,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_id": CASE_ID,
        "split": SPLIT,
        "transitions": TRANSITIONS,
        "frames": FRAMES,
        "namespace": str(plan.output_namespace),
        "namespace_nonce": plan.nonce,
        "trajectory": trajectory,
        "stream_hash": {
            "algorithm": "sha256",
            "sha256": trajectory["sha256"],
            "bytes": trajectory["bytes"],
        },
        **ZERO_CREDIT,
        "source_bound": True,
        "future_state_inputs": False,
    }
    legacy._exclusive_json_write(
        plan.trajectory_metadata, metadata, "trajectory metadata"
    )


def _write_artifact_identity(plan: CurrentManifestRolloutPlan, capability: Any) -> None:
    try:
        evaluation = Path(capability.evaluation_json)
        trajectory = Path(capability.trajectory_hdf5)
        validator_path = Path(capability.validator_receipt)
        sidecar = Path(capability.sidecar)
        checkpoint = Path(capability.checkpoint)
    except AttributeError as error:
        _fail(f"sealed artifact capability is incomplete: {error}")
    expected = {
        "evaluation": plan.outputs["evaluation"],
        "trajectory": plan.outputs["trajectory"],
        "validator": plan.outputs["validator"],
        "sidecar": plan.outputs["artifact_identity"],
        "checkpoint": plan.checkpoint_path,
    }
    observed = {
        "evaluation": evaluation,
        "trajectory": trajectory,
        "validator": validator_path,
        "sidecar": sidecar,
        "checkpoint": checkpoint,
    }
    for key, expected_path in expected.items():
        if observed[key] != expected_path:
            _fail(f"sealed artifact capability {key} path drifted")
    identity = {
        "schema": f"core.f3.mlp.hidden16.seed{plan.seed}.evaluator_artifact_identity.v1",
        "status": "completed_diagnostic",
        "seed": plan.seed,
        "run_id": plan.run_id,
        "namespace": str(plan.output_namespace),
        "namespace_nonce": plan.nonce,
        "manifest_sha256": plan.manifest_sha256,
        "training_manifest_sha256": plan.manifest_sha256,
        "training_receipt_sha256": plan.training_receipt_sha256,
        "checkpoint": dict(plan.checkpoint),
        "evaluation": _stream_identity(evaluation, "evaluation JSON"),
        "trajectory": _stream_identity(trajectory, "trajectory HDF5"),
        "validator": _stream_identity(validator_path, "validator receipt"),
        **ZERO_CREDIT,
    }
    legacy._exclusive_json_write(sidecar, identity, "artifact identity")


@contextmanager
def _bind_legacy_proof_filename(plan: CurrentManifestRolloutPlan):
    """Bind only this adapter call to its unique report filename.

    The historical engine derives its proof path from one module constant.
    Temporarily binding that constant lets the adapter reuse the hardened
    engine without changing the historical file or its normal CLI behavior.
    """

    original = legacy.PROCESS_PROOF_FILENAME
    legacy.PROCESS_PROOF_FILENAME = plan.proof_filename
    try:
        expected = legacy._output_paths(plan.output_namespace, plan.root, plan.seed)
        if expected != dict(plan.outputs):
            _fail("legacy output contract differs from the current adapter plan")
        yield
    finally:
        legacy.PROCESS_PROOF_FILENAME = original


def execute_plan(
    plan: CurrentManifestRolloutPlan,
    *,
    popen_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute exactly one fresh rollout through the legacy secure engine."""

    # The receipt is not passed to the child, but it is the source binding for
    # the checkpoint metadata.  Re-stat it so an old receipt cannot be swapped
    # after dry-run planning.
    legacy._revalidate_input_snapshot(
        plan.training_receipt_snapshot, "training receipt input"
    )
    factory = legacy.subprocess.Popen if popen_factory is None else popen_factory
    with _bind_legacy_proof_filename(plan):
        result = legacy.execute_plan(
            plan.legacy_plan,
            artifact_identity_path=plan.outputs["artifact_identity"],
            terminal_validator=lambda capability: _write_terminal_validator(plan, capability),
            artifact_identity_producer=lambda capability: _write_artifact_identity(plan, capability),
            popen_factory=factory,
        )
    if not isinstance(result, Mapping):
        _fail("legacy execution engine returned a non-object result")
    enriched = dict(result)
    enriched.update(
        {
            "schema": SCHEMA,
            "manifest": str(plan.manifest),
            "manifest_sha256": plan.manifest_sha256,
            "run_id": plan.run_id,
            "seed": plan.seed,
            "output_namespace": str(plan.output_namespace),
            "namespace_nonce": plan.nonce,
            "trajectory_metadata": str(plan.trajectory_metadata),
            **ZERO_CREDIT,
        }
    )
    if enriched.get("status") == "exited_successfully" and not plan.trajectory_metadata.is_file():
        _fail("terminal workflow did not write trajectory metadata")
    return enriched


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--training-receipt", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument(
        "--output-namespace",
        "--namespace",
        dest="output_namespace",
        type=Path,
        required=True,
    )
    parser.add_argument("--gpu-index", type=int, default=0, choices=range(GPU_COUNT))
    parser.add_argument("--python-executable", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="explicitly start one diagnostic evaluator")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        plan = build_plan(
            args.root,
            seed=args.seed,
            manifest=args.manifest,
            checkpoint=args.checkpoint,
            training_receipt=args.training_receipt,
            run_id=args.run_id,
            nonce=args.nonce,
            output_namespace=args.output_namespace,
            gpu_index=args.gpu_index,
            python_executable=args.python_executable,
        )
        result = execute_plan(plan) if args.execute else plan.as_dict()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        if args.execute and result.get("status") != "exited_successfully":
            return 1
        return 0
    except (LauncherError, OSError, RecursionError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
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
