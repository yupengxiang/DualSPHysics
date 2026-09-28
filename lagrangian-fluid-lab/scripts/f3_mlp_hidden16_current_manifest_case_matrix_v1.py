#!/usr/bin/env python3
"""Build and verify the bounded F3 MLP hidden16 32-case matrix.

This is an additive, non-launching planner.  It binds the current-manifest
JSON and the already-bound three-seed training-evidence report, then emits
96 deterministic dry-run plans (32 cases x seeds 17/29/43).  It never opens,
stats, or hashes a production HDF5, checkpoint, evaluation, or trajectory.
The planned GPU slots are scheduling hints only; no process is started,
stopped, or restarted and every plan remains diagnostic-only and zero-credit.

The checked-in report is intentionally not a terminal receipt.  A future
batch executor must perform its own fresh namespace/VRAM admission and create
96 independent terminal receipts before any runtime result can be considered.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
GPU_COUNT = 8
BATCH_SIZE = 8
EXPECTED_CASE_COUNT = 32
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
DATE_RE = re.compile(r"^20[0-9]{6}$")
RUN_ID_RE = re.compile(
    r"^f3-mlp500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-(?P<date>20[0-9]{6})$"
)
CASE_ID_RE = re.compile(r"^F3_DEV_[0-9]{2}_[A-Za-z0-9p]+$")

SCHEMA = "core.f3.mlp.hidden16.current_manifest.case_matrix.v1"
MANIFEST_IDENTITY_SCHEMA = (
    "core.f3.mlp.hidden16.current_manifest.identity_projection.v1"
)
TRAINING_SCHEMA = "core.f3.mlp.hidden16.current_manifest_training_evidence.v1"
REPORT_ID = "f3-mlp-hidden16-current-manifest-case-matrix-v1"

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


class MatrixError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing input."""


def _fail(message: str) -> None:
    raise MatrixError(f"fail-closed: {message}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    result = _string(value, name)
    if SHA256_RE.fullmatch(result) is None:
        _fail(f"{name} must be a lowercase SHA-256 digest")
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
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _walk_json(value: Any, name: str = "value", depth: int = 0) -> None:
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
    normalized = os.path.normpath(str(candidate))
    if str(candidate) != normalized:
        _fail(f"{name} uses a lexical path alias")
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a path alias component")
    if normalized != "/" and normalized.endswith(os.sep):
        _fail(f"{name} has a trailing separator")
    return Path(normalized)


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size)


def _read_bounded_json(path: Path | str, *, name: str, max_bytes: int) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Read only one bounded, regular, single-link JSON file."""

    candidate = _absolute_path(path, name)
    try:
        before = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        _fail(f"{name} must be a regular single-link file")
    if before.st_size > max_bytes:
        _fail(f"{name} exceeds bounded size {max_bytes}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    chunks: list[bytes] = []
    try:
        opened = os.fstat(fd)
        expected = _file_identity(before)
        if _file_identity(opened) != expected:
            _fail(f"{name} changed before bounded read")
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        closed = os.fstat(fd)
        if _file_identity(closed) != expected or total != before.st_size:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name} after read: {error}")
    if _file_identity(after) != _file_identity(before):
        _fail(f"{name} changed after bounded read")
    raw = b"".join(chunks)
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, MatrixError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    payload = _mapping(payload, name)
    _walk_json(payload, name)
    return payload, {
        "path": str(candidate),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _canonical_sha(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        _fail(f"value cannot be canonically encoded: {error}")
    return hashlib.sha256(raw).hexdigest()


def _zero_credit(value: Mapping[str, Any], name: str, *, require_diagnostic: bool = True) -> None:
    if require_diagnostic:
        _exact(value, "diagnostic_only", True, name)
    elif "diagnostic_only" in value:
        _exact(value, "diagnostic_only", True, name)
    for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
        if key in value:
            _exact(value, key, False, name)
    for key in ("credit", "qualification_credit"):
        if key in value:
            _exact(value, key, 0, name)


def _validate_manifest_identity(
    identity: Mapping[str, Any],
    *,
    manifest_path: Path,
    manifest_source: Mapping[str, Any],
    manifest_sha256: str,
) -> dict[str, Any]:
    _exact(identity, "schema", MANIFEST_IDENTITY_SCHEMA, "manifest_identity")
    _exact(identity, "status", "bound", "manifest_identity")
    _exact(identity, "source_bound", True, "manifest_identity")
    _zero_credit(identity, "manifest_identity")
    manifest = _mapping(identity.get("manifest"), "manifest_identity.manifest")
    raw = _mapping(manifest.get("raw"), "manifest_identity.manifest.raw")
    canonical = _mapping(manifest.get("canonical"), "manifest_identity.manifest.canonical")
    _exact(raw, "path", str(manifest_path), "manifest_identity.manifest.raw")
    _exact(raw, "sha256", manifest_source["sha256"], "manifest_identity.manifest.raw")
    _exact(raw, "bytes", manifest_source["bytes"], "manifest_identity.manifest.raw")
    _exact(canonical, "sha256", manifest_sha256, "manifest_identity.manifest.canonical")
    return {
        "raw": dict(raw),
        "canonical": dict(canonical),
    }


def _validate_case(case: Mapping[str, Any], index: int) -> dict[str, Any]:
    name = f"manifest.cases[{index}]"
    case_id = _string(case.get("case_id"), f"{name}.case_id")
    if CASE_ID_RE.fullmatch(case_id) is None:
        _fail(f"{name}.case_id is not an F3_DEV case identifier")
    if _string(case.get("physical_case_id"), f"{name}.physical_case_id") != case_id:
        _fail(f"{name}.physical_case_id is not bound to case_id")
    _exact(case, "family", "F3", name)
    split = _string(case.get("split"), f"{name}.split")
    if split not in {"train", "validation", "test"}:
        _fail(f"{name}.split is not a supported dataset split")
    hdf5 = _string(case.get("hdf5"), f"{name}.hdf5")
    if Path(hdf5).is_absolute() or any(part in {".", ".."} for part in Path(hdf5).parts):
        _fail(f"{name}.hdf5 must be a relative, alias-free metadata path")
    case_sha = _sha(case.get("sha256"), f"{name}.sha256")
    hdf5_bytes = _int(case.get("bytes"), f"{name}.bytes", minimum=1)
    known_inputs_sha = _sha(case.get("known_inputs_sha256"), f"{name}.known_inputs_sha256")
    _exact(case, "qualification_case", False, name)
    return {
        "index": index,
        "case_id": case_id,
        "physical_case_id": case_id,
        "family": "F3",
        "split": split,
        "evaluation_role": _string(case.get("evaluation_role"), f"{name}.evaluation_role"),
        "hdf5": hdf5,
        "hdf5_sha256": case_sha,
        "hdf5_bytes": hdf5_bytes,
        "known_inputs_sha256": known_inputs_sha,
        "lineage_group_id": _sha(case.get("lineage_group_id"), f"{name}.lineage_group_id"),
        "scope_id": _string(case.get("scope_id"), f"{name}.scope_id"),
    }


def _validate_manifest(payload: Mapping[str, Any], *, source: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _exact(payload, "schema", "core.dataset.v2", "manifest")
    _exact(payload, "case_count", EXPECTED_CASE_COUNT, "manifest")
    _exact(payload, "formal_release", False, "manifest")
    _exact(payload, "dataset_id", "F3_registered32_core_native_v2", "manifest")
    _exact(payload, "input_asset_policy", "content_addressed_compressed_npz", "manifest")
    source_manifest_sha = _sha(payload.get("source_manifest_sha256"), "manifest.source_manifest_sha256")
    cases_value = payload.get("cases")
    if not isinstance(cases_value, list) or len(cases_value) != EXPECTED_CASE_COUNT:
        _fail("manifest.cases must contain exactly 32 cases")
    cases = [_validate_case(_mapping(case, f"manifest.cases[{index}]"), index) for index, case in enumerate(cases_value)]
    case_ids = [case["case_id"] for case in cases]
    if len(set(case_ids)) != EXPECTED_CASE_COUNT:
        _fail("manifest case identifiers are not unique")
    case_hashes = [case["hdf5_sha256"] for case in cases]
    if len(set(case_hashes)) != EXPECTED_CASE_COUNT:
        _fail("manifest case artifact identities are not unique")
    scope_ids = {case["scope_id"] for case in cases}
    if len(scope_ids) != 1:
        _fail("F3 matrix cases must share exactly one scope_id")
    return cases, {
        "schema": payload["schema"],
        "dataset_id": payload["dataset_id"],
        "case_count": payload["case_count"],
        "source_manifest_sha256": source_manifest_sha,
        "formal_release": payload["formal_release"],
        "input_asset_policy": payload["input_asset_policy"],
        "source": dict(source),
        "scope_id": next(iter(scope_ids)),
    }


def _validate_identity_record(record: Mapping[str, Any], name: str, *, update: int | None = None) -> dict[str, Any]:
    path = _absolute_path(record.get("path"), f"{name}.path")
    digest = _sha(record.get("sha256"), f"{name}.sha256")
    size = _int(record.get("bytes"), f"{name}.bytes", minimum=1)
    result = {"path": str(path), "sha256": digest, "bytes": size}
    if update is not None:
        _exact(record, "update", update, name)
        result["update"] = update
    return result


def _validate_training(
    payload: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    manifest_identity: Mapping[str, Any],
    manifest_sha256: str,
    manifest_raw_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _exact(payload, "schema", TRAINING_SCHEMA, "training_evidence")
    _exact(payload, "report_id", "f3-mlp-hidden16-current-manifest-training-evidence-v1", "training_evidence")
    _exact(payload, "status", "diagnostic_bound", "training_evidence")
    _exact(payload, "source_bound", True, "training_evidence")
    _exact(payload, "fail_closed", False, "training_evidence")
    _exact(payload, "model", MODEL, "training_evidence")
    _exact(payload, "hidden", HIDDEN, "training_evidence")
    _exact(payload, "updates", UPDATES, "training_evidence")
    _exact(payload, "errors", [], "training_evidence")
    for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
        _exact(payload, key, False, "training_evidence")
    for key in ("credit", "qualification_credit", "formal_training_runs_counted", "t1_case_runs_counted", "t2_macro_families_counted"):
        _exact(payload, key, 0, "training_evidence")
    _exact(payload, "diagnostic_only", True, "training_evidence")
    authorization = _mapping(payload.get("authorization"), "training_evidence.authorization")
    _zero_credit(authorization, "training_evidence.authorization")
    _exact(authorization, "formal", False, "training_evidence.authorization")

    manifest = _mapping(payload.get("manifest"), "training_evidence.manifest")
    _exact(manifest, "path", manifest_identity["raw"]["path"], "training_evidence.manifest")
    _exact(manifest, "sha256", manifest_raw_sha256, "training_evidence.manifest")
    _exact(manifest, "bytes", manifest_identity["raw"]["bytes"], "training_evidence.manifest")
    _exact(manifest, "canonical_sha256", manifest_sha256, "training_evidence.manifest")
    _exact(manifest, "opened", True, "training_evidence.manifest")

    boundary = _mapping(payload.get("input_boundary"), "training_evidence.input_boundary")
    _exact(boundary, "manifest_content_opened", True, "training_evidence.input_boundary")
    for key in ("checkpoint_content_opened", "hdf5_content_opened", "gpu_started", "solver_started"):
        if key in boundary:
            _exact(boundary, key, False, "training_evidence.input_boundary")
    side_effects = _mapping(payload.get("side_effects"), "training_evidence.side_effects")
    for key in ("checkpoint_opened", "hdf5_opened", "runtime_started"):
        if key in side_effects:
            _exact(side_effects, key, False, "training_evidence.side_effects")
    for key, value in side_effects.items():
        if key.endswith("mutation"):
            _exact(side_effects, key, 0, "training_evidence.side_effects")

    runs_value = payload.get("runs")
    if not isinstance(runs_value, list) or len(runs_value) != len(SEEDS):
        _fail("training_evidence.runs must contain exactly three runs")
    runs: list[dict[str, Any]] = []
    seen_seeds: set[int] = set()
    seen_run_ids: set[str] = set()
    seen_receipts: set[str] = set()
    seen_checkpoints: set[str] = set()
    for index, row_value in enumerate(runs_value):
        row = _mapping(row_value, f"training_evidence.runs[{index}]")
        seed = _int(row.get("seed"), f"training_evidence.runs[{index}].seed", minimum=0)
        if seed not in SEEDS or seed in seen_seeds:
            _fail("training evidence seed set must be exactly 17, 29, 43")
        seen_seeds.add(seed)
        _exact(row, "status", "bound", f"training_evidence.runs[{index}]")
        source_record = _mapping(row.get("source"), f"training_evidence.runs[{index}].source")
        source_identity = _validate_identity_record(source_record, f"training_evidence.runs[{index}].source")
        _exact(source_record, "schema", "core.training.v1", f"training_evidence.runs[{index}].source")
        _exact(source_record, "opened", True, f"training_evidence.runs[{index}].source")
        evidence = _mapping(row.get("evidence"), f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "schema", "core.training.v1", f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "model", MODEL, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "hidden", HIDDEN, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "updates", UPDATES, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "seed", seed, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "completed", True, f"training_evidence.runs[{index}].evidence")
        _exact(evidence, "manifest_sha256", manifest_sha256, f"training_evidence.runs[{index}].evidence")
        _zero_credit(_mapping(evidence.get("zero_credit"), f"training_evidence.runs[{index}].evidence.zero_credit"), f"training_evidence.runs[{index}].evidence.zero_credit")
        run_id = _string(evidence.get("run_id"), f"training_evidence.runs[{index}].evidence.run_id")
        match = RUN_ID_RE.fullmatch(run_id)
        if match is None or int(match.group("seed")) != seed:
            _fail(f"training_evidence.runs[{index}] has an invalid run_id")
        checkpoint = _validate_identity_record(
            _mapping(evidence.get("checkpoint_identity"), f"training_evidence.runs[{index}].evidence.checkpoint_identity"),
            f"training_evidence.runs[{index}].evidence.checkpoint_identity",
            update=UPDATES,
        )
        checkpoint["schema"] = "core.checkpoint.v1"
        receipt = _validate_identity_record(
            _mapping(evidence.get("receipt_identity"), f"training_evidence.runs[{index}].evidence.receipt_identity"),
            f"training_evidence.runs[{index}].evidence.receipt_identity",
        )
        if source_identity["path"] != receipt["path"] or source_identity["sha256"] != receipt["sha256"]:
            _fail(f"training_evidence.runs[{index}] source and receipt identity drift")
        if seed in seen_seeds - {seed} or run_id in seen_run_ids or receipt["sha256"] in seen_receipts or checkpoint["sha256"] in seen_checkpoints:
            _fail("training evidence identities are not unique")
        seen_run_ids.add(run_id)
        seen_receipts.add(receipt["sha256"])
        seen_checkpoints.add(checkpoint["sha256"])
        runs.append({
            "seed": seed,
            "run_id": run_id,
            "run_date": match.group("date"),
            "training_receipt": receipt,
            "checkpoint": checkpoint,
        })
    if tuple(sorted(seen_seeds)) != SEEDS:
        _fail("training evidence does not cover exactly seeds 17, 29, 43")
    return sorted(runs, key=lambda item: item["seed"]), {
        "report_id": payload["report_id"],
        "schema": payload["schema"],
        "source": dict(source),
        "status": payload["status"],
        "source_bound": payload["source_bound"],
        "manifest": dict(manifest),
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seed_count": len(runs),
    }


def _planned_nonce(*, manifest_sha256: str, case_id: str, seed: int, run_id: str) -> str:
    material = f"f3-mlp-hidden16-current-manifest-case-matrix-v1|{manifest_sha256}|{case_id}|{seed}|{run_id}".encode()
    nonce = hashlib.sha256(material).hexdigest()[:32]
    if NONCE_RE.fullmatch(nonce) is None or int(nonce, 16) == 0:
        _fail("deterministic plan nonce is invalid")
    return nonce


def _case_slug(case_id: str) -> str:
    result = re.sub(r"[^A-Za-z0-9]+", "-", case_id).strip("-").lower()
    if not result:
        _fail("case identifier produced an empty namespace slug")
    return result


def _command_digest(command: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> str:
    return _canonical_sha({"argv": list(command), "cwd": str(cwd), "env_overrides": dict(env)})


def _plan_for(
    *,
    root: Path,
    manifest_path: Path,
    manifest_sha256: str,
    case: Mapping[str, Any],
    run: Mapping[str, Any],
    ordinal: int,
    plan_date: str,
    python_executable: Path,
) -> dict[str, Any]:
    seed = int(run["seed"])
    case_id = str(case["case_id"])
    nonce = _planned_nonce(
        manifest_sha256=manifest_sha256,
        case_id=case_id,
        seed=seed,
        run_id=str(run["run_id"]),
    )
    gpu_index = ordinal % GPU_COUNT
    batch_index = ordinal // BATCH_SIZE
    slot = ordinal % BATCH_SIZE
    namespace = Path(
        "/tmp"
        f"/f3-mlp500-hidden16-currentmanifest-case-matrix-{plan_date}-"
        f"case{int(case['index']):02d}-{_case_slug(case_id)}-seed{seed}-full835-{nonce}"
    )
    outputs = {
        "evaluation": namespace / "evaluation.json",
        "trajectory": namespace / "trajectory.h5",
        "progress": namespace / "progress.json",
        "validator": namespace / "hdf5-validation.json",
        "artifact_identity": namespace / "artifact-identity.json",
        "trajectory_metadata": namespace / "trajectory-metadata.json",
        "process_proof": root / "reports" / f"F3-MLP-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-CASE{int(case['index']):02d}-SEED{seed}-PROCESS-EXIT-PROOF-V1.json",
    }
    command = (
        str(python_executable),
        "-u",
        str(root / "scripts" / "core_learning.py"),
        "evaluate",
        "--manifest",
        str(manifest_path),
        "--data-root",
        str(root),
        "--checkpoint",
        str(run["checkpoint"]["path"]),
        "--case-id",
        case_id,
        "--split",
        str(case["split"]),
        "--maximum-steps",
        str(TRANSITIONS),
        "--chunk-size",
        "34560",
        "--device",
        "cuda:0",
        "--progress-every",
        "25",
        "--trajectory-output",
        str(outputs["trajectory"]),
        "--progress-output",
        str(outputs["progress"]),
        "--output",
        str(outputs["evaluation"]),
        "--diagnostic",
    )
    env = {
        "CUDA_VISIBLE_DEVICES": str(gpu_index),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    command_sha = _command_digest(command, cwd=root, env=env)
    return {
        "job_id": f"f3-mlp-hidden16-case-matrix-case{int(case['index']):02d}-seed{seed}",
        "ordinal": ordinal,
        "batch_index": batch_index,
        "batch_slot": slot,
        "gpu_index": gpu_index,
        "seed": seed,
        "run_id": run["run_id"],
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "case_index": case["index"],
        "case_id": case_id,
        "physical_case_id": case["physical_case_id"],
        "split": case["split"],
        "evaluation_role": case["evaluation_role"],
        "case_hdf5_metadata": {
            "path": case["hdf5"],
            "sha256": case["hdf5_sha256"],
            "bytes": case["hdf5_bytes"],
        },
        "known_inputs_sha256": case["known_inputs_sha256"],
        "manifest_sha256": manifest_sha256,
        "checkpoint": dict(run["checkpoint"]),
        "training_receipt": dict(run["training_receipt"]),
        "output_namespace": str(namespace),
        "namespace_nonce": nonce,
        "namespace_freshness_attested": False,
        "namespace_reuse_allowed": False,
        "command": list(command),
        "cwd": str(root),
        "env_overrides": env,
        "command_sha256": command_sha,
        "outputs": {key: str(value) for key, value in outputs.items()},
        "status": "dry_run_ready",
        "launch_allowed": False,
        "terminal_receipt_observed": False,
        "terminal_receipt_path": None,
        "resource_policy": {
            "gpu_sharing_allowed": True,
            "gpu_index_is_hint_only": True,
            "requires_future_free_vram_admission": True,
            "requires_future_cpu_io_admission": True,
            "kill_existing_processes": False,
            "restart_existing_processes": False,
        },
        **ZERO_CREDIT,
        "zero_credit_only": True,
    }


def _validate_plan(plan: Mapping[str, Any], *, root: Path, manifest_sha256: str) -> None:
    name = f"plans[{plan.get('ordinal', '?')}]"
    _exact(plan, "status", "dry_run_ready", name)
    _exact(plan, "launch_allowed", False, name)
    _exact(plan, "terminal_receipt_observed", False, name)
    _zero_credit(plan, name)
    _exact(plan, "manifest_sha256", manifest_sha256, name)
    seed = _int(plan.get("seed"), f"{name}.seed", minimum=0)
    if seed not in SEEDS:
        _fail(f"{name}.seed is outside the exact seed set")
    case_id = _string(plan.get("case_id"), f"{name}.case_id")
    if CASE_ID_RE.fullmatch(case_id) is None:
        _fail(f"{name}.case_id is invalid")
    nonce = _string(plan.get("namespace_nonce"), f"{name}.namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None:
        _fail(f"{name}.namespace_nonce is not lowercase 32-hex")
    namespace = _absolute_path(plan.get("output_namespace"), f"{name}.output_namespace")
    expected_marker = f"case{int(plan.get('case_index')):02d}-{_case_slug(case_id)}-seed{seed}-full835-"
    if not namespace.name.startswith("f3-mlp500-hidden16-currentmanifest-case-matrix-") or expected_marker not in namespace.name or not namespace.name.endswith(nonce):
        _fail(f"{name}.output_namespace is not bound to case, seed, full835, and nonce")
    command = plan.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        _fail(f"{name}.command must be a non-empty string argv")
    env = _mapping(plan.get("env_overrides"), f"{name}.env_overrides")
    _exact(env, "CUDA_VISIBLE_DEVICES", str(plan.get("gpu_index")), f"{name}.env_overrides")
    _exact(env, "PYTHONDONTWRITEBYTECODE", "1", f"{name}.env_overrides")
    _exact(plan, "cwd", str(root), name)
    expected_digest = _command_digest(command, cwd=root, env={str(key): str(value) for key, value in env.items()})
    _exact(plan, "command_sha256", expected_digest, name)
    if plan["command"].count("--case-id") != 1 or plan["command"][plan["command"].index("--case-id") + 1] != case_id:
        _fail(f"{name}.command case identity drifted")
    if "--diagnostic" not in plan["command"] or "--maximum-steps" not in plan["command"]:
        _fail(f"{name}.command is missing diagnostic/full835 arguments")
    if plan["command"][plan["command"].index("--maximum-steps") + 1] != str(TRANSITIONS):
        _fail(f"{name}.command transition target drifted")
    outputs = _mapping(plan.get("outputs"), f"{name}.outputs")
    for key in ("evaluation", "trajectory", "progress", "validator", "artifact_identity", "trajectory_metadata"):
        output = _absolute_path(outputs.get(key), f"{name}.outputs.{key}")
        if output.parent != namespace:
            _fail(f"{name}.outputs.{key} escaped output namespace")
    process_proof = _absolute_path(outputs.get("process_proof"), f"{name}.outputs.process_proof")
    if process_proof.parent != root / "reports":
        _fail(f"{name}.outputs.process_proof escaped root reports")


def validate_report(report: Mapping[str, Any]) -> None:
    """Fail-closed validation of a generated matrix report."""

    _exact(report, "schema", SCHEMA, "report")
    _exact(report, "status", "dry_run_matrix_ready", "report")
    _exact(report, "report_id", REPORT_ID, "report")
    _exact(report, "source_bound", True, "report")
    _zero_credit(report, "report")
    expected = _mapping(report.get("expected_contract"), "report.expected_contract")
    _exact(expected, "case_count", EXPECTED_CASE_COUNT, "report.expected_contract")
    _exact(expected, "seed_count", len(SEEDS), "report.expected_contract")
    _exact(expected, "matrix_job_count", EXPECTED_CASE_COUNT * len(SEEDS), "report.expected_contract")
    _exact(expected, "transitions", TRANSITIONS, "report.expected_contract")
    _exact(expected, "frames", FRAMES, "report.expected_contract")
    _exact(expected, "zero_credit_only", True, "report.expected_contract")
    manifest_binding = _mapping(report.get("manifest"), "report.manifest")
    binding_sha = _sha(manifest_binding.get("canonical_sha256"), "report.manifest.canonical_sha256")
    _exact(manifest_binding, "case_count", EXPECTED_CASE_COUNT, "report.manifest")
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        _fail("report.cases must contain exactly 32 cases")
    case_ids: set[str] = set()
    for case in cases:
        case_map = _mapping(case, "report.cases[]")
        case_id = _string(case_map.get("case_id"), "report.cases[].case_id")
        if case_id in case_ids:
            _fail("report case coverage contains duplicate case_id")
        case_ids.add(case_id)
    plans = report.get("plans")
    if not isinstance(plans, list) or len(plans) != EXPECTED_CASE_COUNT * len(SEEDS):
        _fail("report.plans must contain exactly 96 plans")
    namespaces: set[str] = set()
    nonces: set[str] = set()
    command_digests: set[str] = set()
    combinations: set[tuple[str, int]] = set()
    root = _absolute_path(report.get("root"), "report.root")
    for plan in plans:
        plan_map = _mapping(plan, "report.plans[]")
        _validate_plan(plan_map, root=root, manifest_sha256=binding_sha)
        case_id = str(plan_map["case_id"])
        seed = int(plan_map["seed"])
        if case_id not in case_ids:
            _fail("report plan references a case outside report.cases")
        key = (case_id, seed)
        if key in combinations:
            _fail("report plans contain a duplicate case x seed combination")
        combinations.add(key)
        namespace = str(plan_map["output_namespace"])
        nonce = str(plan_map["namespace_nonce"])
        digest = str(plan_map["command_sha256"])
        if namespace in namespaces or nonce in nonces or digest in command_digests:
            _fail("report plan namespace, nonce, or command identity is not unique")
        namespaces.add(namespace)
        nonces.add(nonce)
        command_digests.add(digest)
    expected_combinations = {(case_id, seed) for case_id in case_ids for seed in SEEDS}
    if combinations != expected_combinations:
        _fail("report does not provide exact 32-case x 3-seed coverage")
    receipts = _mapping(report.get("terminal_receipts"), "report.terminal_receipts")
    _exact(receipts, "required_count", 96, "report.terminal_receipts")
    _exact(receipts, "observed_count", 0, "report.terminal_receipts")
    _exact(receipts, "missing_count", 96, "report.terminal_receipts")
    _exact(receipts, "status", "missing_real_terminal_receipts", "report.terminal_receipts")
    _exact(report, "blocked_reasons", [], "report")
    boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
    _exact(boundary, "bounded_manifest_json_opened", True, "report.input_boundary")
    _exact(boundary, "bounded_training_identity_json_opened", True, "report.input_boundary")
    for key in ("checkpoint_content_opened", "evaluation_content_opened", "trajectory_content_opened", "hdf5_content_opened", "checkpoint_lstat_performed", "hdf5_lstat_performed", "gpu_started", "queue_started"):
        _exact(boundary, key, False, "report.input_boundary")
    side_effects = _mapping(report.get("side_effects"), "report.side_effects")
    for key in ("processes_started", "processes_stopped", "processes_restarted", "registry_writes", "ledger_writes", "denominator_writes", "gate_writes", "completion_writes", "plan_writes"):
        _exact(side_effects, key, 0, "report.side_effects")


def build_report(
    *,
    root: Path | str,
    manifest: Path | str,
    manifest_identity: Path | str,
    training_evidence: Path | str,
    plan_date: str,
    python_executable: Path | str | None = None,
) -> dict[str, Any]:
    root_path = _absolute_path(root, "root")
    if DATE_RE.fullmatch(plan_date) is None:
        _fail("plan_date must be YYYYMMDD in the 20xx range")
    manifest_path = _absolute_path(manifest, "manifest")
    identity_payload, identity_source = _read_bounded_json(
        manifest_identity, name="manifest_identity", max_bytes=MAX_METADATA_BYTES
    )
    manifest_payload, manifest_source = _read_bounded_json(
        manifest_path, name="manifest", max_bytes=MAX_MANIFEST_BYTES
    )
    manifest_sha256 = _canonical_sha(manifest_payload)
    identity_binding = _validate_manifest_identity(
        identity_payload,
        manifest_path=manifest_path,
        manifest_source=manifest_source,
        manifest_sha256=manifest_sha256,
    )
    cases, manifest_meta = _validate_manifest(manifest_payload, source=manifest_source)
    training_payload, training_source = _read_bounded_json(
        training_evidence, name="training_evidence", max_bytes=MAX_METADATA_BYTES
    )
    training_runs, training_meta = _validate_training(
        training_payload,
        source=training_source,
        manifest_identity=identity_binding,
        manifest_sha256=manifest_sha256,
        manifest_raw_sha256=manifest_source["sha256"],
    )
    python_path = _absolute_path(
        python_executable if python_executable is not None else root_path / ".venv" / "bin" / "python",
        "python_executable",
    )
    runs_by_seed = {int(run["seed"]): run for run in training_runs}
    plans: list[dict[str, Any]] = []
    ordinal = 0
    for case in cases:
        for seed in SEEDS:
            plans.append(
                _plan_for(
                    root=root_path,
                    manifest_path=manifest_path,
                    manifest_sha256=manifest_sha256,
                    case=case,
                    run=runs_by_seed[seed],
                    ordinal=ordinal,
                    plan_date=plan_date,
                    python_executable=python_path,
                )
            )
            ordinal += 1
    matrix_identity = [
        {
            "job_id": plan["job_id"],
            "case_id": plan["case_id"],
            "seed": plan["seed"],
            "namespace": plan["output_namespace"],
            "nonce": plan["namespace_nonce"],
            "command_sha256": plan["command_sha256"],
        }
        for plan in plans
    ]
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "status": "dry_run_matrix_ready",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root_path),
        "source_bound": True,
        "matrix_sha256": _canonical_sha(matrix_identity),
        **ZERO_CREDIT,
        "expected_contract": {
            "case_count": EXPECTED_CASE_COUNT,
            "seed_count": len(SEEDS),
            "seeds": list(SEEDS),
            "matrix_job_count": EXPECTED_CASE_COUNT * len(SEEDS),
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "batch_size": BATCH_SIZE,
            "gpu_count": GPU_COUNT,
            "bounded_json_only": True,
            "zero_credit_only": True,
        },
        "manifest_identity": {
            "projection_source": dict(identity_source),
            "binding": identity_binding,
        },
        "manifest": {
            "schema": manifest_meta["schema"],
            "dataset_id": manifest_meta["dataset_id"],
            "case_count": manifest_meta["case_count"],
            "canonical_sha256": manifest_sha256,
            "raw": dict(manifest_source),
            "source_manifest_sha256": manifest_meta["source_manifest_sha256"],
            "scope_id": manifest_meta["scope_id"],
            "formal_release": manifest_meta["formal_release"],
            "input_asset_policy": manifest_meta["input_asset_policy"],
        },
        "cases": cases,
        "training_identity": training_meta,
        "plans": plans,
        "coverage": {
            "exact_case_coverage": True,
            "exact_seed_coverage": True,
            "exact_case_seed_coverage": True,
            "cases": EXPECTED_CASE_COUNT,
            "seeds": list(SEEDS),
            "jobs": len(plans),
            "unique_namespaces": len({plan["output_namespace"] for plan in plans}),
            "unique_nonces": len({plan["namespace_nonce"] for plan in plans}),
            "unique_command_identities": len({plan["command_sha256"] for plan in plans}),
            "gpu_slots": {str(gpu): sum(plan["gpu_index"] == gpu for plan in plans) for gpu in range(GPU_COUNT)},
        },
        "scheduler": {
            "batch_size": BATCH_SIZE,
            "batch_count": len(plans) // BATCH_SIZE,
            "gpu_count": GPU_COUNT,
            "gpu_sharing_allowed": True,
            "free_vram_must_be_rechecked_before_execution": True,
            "existing_processes_must_not_be_killed_or_restarted": True,
            "planned_concurrency": BATCH_SIZE,
            "launches_performed": 0,
        },
        "terminal_receipts": {
            "required_count": len(plans),
            "observed_count": 0,
            "missing_count": len(plans),
            "status": "missing_real_terminal_receipts",
            "paths": [],
            "note": "No rollout was started; every future job needs an independent natural-exit, evaluator, validator, trajectory, and artifact receipt.",
        },
        "input_boundary": {
            "bounded_manifest_json_opened": True,
            "bounded_training_identity_json_opened": True,
            "checkpoint_content_opened": False,
            "checkpoint_lstat_performed": False,
            "evaluation_content_opened": False,
            "trajectory_content_opened": False,
            "trajectory_hdf5_opened": False,
            "hdf5_content_opened": False,
            "hdf5_lstat_performed": False,
            "gpu_started": False,
            "queue_started": False,
            "runtime_started": False,
        },
        "side_effects": {
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "denominator_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        "checks": [
            {"check": "exact_32_case_manifest", "passed": True, "observed": EXPECTED_CASE_COUNT},
            {"check": "exact_three_seed_training_identity", "passed": True, "observed": list(SEEDS)},
            {"check": "exact_32x3_matrix_coverage", "passed": True, "observed": len(plans)},
            {"check": "unique_namespace_nonce_command_identity", "passed": True, "observed": len(plans)},
            {"check": "diagnostic_only_zero_credit", "passed": True, "observed": True},
            {"check": "real_terminal_receipts", "passed": False, "observed": 0, "reason": "No rollout was launched by this bounded dry-run planner."},
        ],
        "blocked_reasons": [],
        "interpretation": "This report is a source-bound dry-run matrix only. It is not terminal runtime evidence and cannot increase formal training, T1/T2, qualification, or credit counters.",
    }
    validate_report(report)
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    cases = report["cases"]
    coverage = report["coverage"]
    receipts = report["terminal_receipts"]
    lines = [
        "# F3 MLP hidden16 current-manifest 32-case matrix",
        "",
        "- 状态：`dry_run_matrix_ready`（仅 bounded dry-run，不是 terminal evidence）",
        f"- 覆盖：`{coverage['cases']} cases × {len(SEEDS)} seeds = {coverage['jobs']} jobs`，seed=`17/29/43`",
        f"- 唯一性：namespace `{coverage['unique_namespaces']}/{coverage['jobs']}`，nonce `{coverage['unique_nonces']}/{coverage['jobs']}`，command SHA `{coverage['unique_command_identities']}/{coverage['jobs']}`",
        "- 运行权限：`launch_allowed=false`；所有计划 `diagnostic_only=true`、formal/T1/T2/qualification=`false`、credit=`0`",
        f"- 真实终态回执：需要 `{receipts['required_count']}`，当前得到 `{receipts['observed_count']}`，仍缺 `{receipts['missing_count']}`；本轮没有启动 rollout/GPU/queue",
        "",
        "## 绑定来源",
        "",
        f"- manifest canonical SHA：`{report['manifest']['canonical_sha256']}`；raw bytes：`{report['manifest']['raw']['bytes']}`",
        f"- training report：`{report['training_identity']['source']['path']}`；三 seed training identity 已绑定，checkpoint 只作为 JSON identity metadata，不曾打开",
        "- production HDF5、checkpoint、evaluation、trajectory 均未打开、未 stat、未 hash",
        "",
        "## 32-case coverage",
        "",
        "| # | case | split | evaluation role | HDF5 metadata bytes |",
        "|---:|---|---|---|---:|",
    ]
    for case in cases:
        lines.append(
            f"| {case['index']:02d} | `{case['case_id']}` | `{case['split']}` | `{case['evaluation_role']}` | {case['hdf5_bytes']} |"
        )
    lines.extend(
        [
            "",
            "## 后续执行边界",
            "",
            "JSON report 的 `plans` 数组含 96 个完整 argv/env/output namespace/command SHA 计划，按 8 个 GPU slot 分成 12 个 batch。GPU 可共享，但执行前必须重新检查显存、CPU/I/O、namespace 未占用和自然退出证据；不得杀掉或重启已有进程。",
            "",
            "该矩阵只完成由粗到细的 case×seed 计划覆盖，不代表任何真实 case-run 已完成，也不改变 Core registry、ledger、denominator、gate 或 completion。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(LAB_ROOT))
    parser.add_argument("--manifest")
    parser.add_argument("--manifest-identity")
    parser.add_argument("--training-evidence")
    parser.add_argument("--output")
    parser.add_argument("--markdown-output")
    parser.add_argument("--python-executable")
    parser.add_argument("--plan-date", default="20260929")
    parser.add_argument("--verify-report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report:
            payload, source = _read_bounded_json(
                args.verify_report, name="matrix_report", max_bytes=MAX_METADATA_BYTES * 8
            )
            validate_report(payload)
            print(json.dumps({"status": "verified", "report": source["path"], "report_sha256": source["sha256"]}, sort_keys=True))
            return 0
        required = {
            "--manifest": args.manifest,
            "--manifest-identity": args.manifest_identity,
            "--training-evidence": args.training_evidence,
            "--output": args.output,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise MatrixError(f"missing required arguments: {', '.join(missing)}")
        report = build_report(
            root=args.root,
            manifest=args.manifest,
            manifest_identity=args.manifest_identity,
            training_evidence=args.training_evidence,
            plan_date=args.plan_date,
            python_executable=args.python_executable,
        )
        output = _absolute_path(args.output, "output")
        _write_output(output, json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        markdown_path = None
        if args.markdown_output:
            markdown_path = _absolute_path(args.markdown_output, "markdown_output")
            _write_output(markdown_path, render_markdown(report))
        print(json.dumps({
            "status": report["status"],
            "output": str(output),
            "markdown_output": str(markdown_path) if markdown_path else None,
            "jobs": len(report["plans"]),
            "terminal_receipts_observed": report["terminal_receipts"]["observed_count"],
            "credit": report["credit"],
        }, sort_keys=True))
        return 0
    except (MatrixError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
