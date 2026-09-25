#!/usr/bin/env python3
"""Adapt a real Core training receipt into a capacity-only evidence record.

This module is deliberately read-only.  It consumes a completed
``core.training.v1`` receipt and a small execution sidecar, verifies the
receipt's actual 32,000-update frontier, its four Core milestone checkpoints,
the released reader manifest, and the current learning source closure.  It
does not start a worker, open a trajectory, write a checkpoint, or count a
training run.

The adapter exists at the boundary between resource evidence and formal
admission.  A CPU synthetic dry run, a short graph probe, or a 1,000-update
pilot can still be useful diagnostics, but none of them can satisfy this
schema.  The sidecar must explicitly attest to native full-field input,
non-synthetic execution, a CUDA device, and the Core dual-increment model
adapter.  All paths are resolved against an explicit data root and all
declared hashes are rechecked before a record can be marked valid.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_formal_planner import REQUIRED_CODE_FILES
from scripts.core_strict_json import (
    absolute_path_without_following_leaf,
    read_bounded_raw_json,
    strict_json_object,
)


SCHEMA = "core.formal_capacity_evidence.v1"
EXECUTION_SCHEMA = "core.formal_capacity_execution.v1"
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
SOURCE_CLOSURE_SCHEMA = "core.formal_source_closure.v1"
MODEL_ADAPTER_SCHEMA = "core.dual_increment.model_adapter.v1"
MODEL_VERSION = "core.dual_increment.v1"
FORMAL_UPDATES = 32000
MILESTONES = (8000, 16000, 24000, 32000)
GRAPH_MODELS = {"graph_raw", "graph_residual"}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical(value).encode("utf-8"))


def _valid_sha(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0


def _resolve(value: str | Path, *, root: Path, base: Path | None = None) -> Path:
    """Resolve root-relative references before receipt-local fallbacks.

    Core manifests use paths relative to ``data_root``.  Runtime receipts may
    use a path relative to the receipt directory, so the latter remains a
    fallback.  Choosing the root-relative candidate first avoids a same-name
    file in a nested directory shadowing a portable manifest reference.
    """
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return absolute_path_without_following_leaf(candidate)
    options = [absolute_path_without_following_leaf(root / candidate)]
    if base is not None:
        options.append(absolute_path_without_following_leaf(base / candidate))
    for option in options:
        if option.exists():
            return option
    return options[0]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_json(source: str | Path | Mapping[str, Any], *, root: Path,
               base: Path | None = None
               ) -> tuple[dict[str, Any], Path | None, str, int | None]:
    if isinstance(source, Mapping):
        payload = dict(source)
        return payload, None, canonical_sha256(payload), None
    path = _resolve(source, root=root, base=base)
    raw = read_bounded_raw_json(path, label=f"capacity input {path}")
    payload = strict_json_object(raw, label=f"capacity input {path}")
    return payload, path, sha256_bytes(raw), len(raw)


def _ref(path: Path, root: Path, *, digest: str | None = None,
         byte_count: int | None = None) -> dict[str, Any]:
    return {
        "path": _relative(path, root),
        "sha256": digest if digest is not None else sha256_file(path),
        "bytes": byte_count if byte_count is not None else path.stat().st_size,
    }


def _portable_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _record_failure(failures: list[dict[str, Any]], code: str, message: str) -> None:
    failures.append({"code": code, "message": message})


def _file_ref(
    reference: Mapping[str, Any], *, root: Path, base: Path | None,
    failures: list[dict[str, Any]], role: str, require_portable: bool = False,
    require_bytes: bool = False,
) -> tuple[Path | None, dict[str, Any] | None]:
    path_value = reference.get("path")
    declared_sha = reference.get("sha256")
    if require_portable and not _portable_path(path_value):
        _record_failure(failures, "CAPACITY_RELATIVE_PATH", f"{role} path must be relative and cannot escape data_root")
    if not isinstance(path_value, str) or not path_value:
        _record_failure(failures, "CAPACITY_PATH_BINDING", f"{role} has no path")
        return None, None
    path = _resolve(path_value, root=root, base=base)
    result: dict[str, Any] = {"role": role, "path": _relative(path, root),
                              "declared_sha256": declared_sha}
    if not path.is_file():
        _record_failure(failures, "CAPACITY_PATH_BINDING", f"{role} is missing: {path}")
        return None, result
    observed = sha256_file(path)
    result["sha256"] = observed
    result["bytes"] = path.stat().st_size
    if not _valid_sha(declared_sha) or observed.lower() != str(declared_sha).lower():
        _record_failure(failures, "CAPACITY_HASH_BINDING", f"{role} SHA-256 mismatch or declaration missing: {path}")
        return path, result
    expected_bytes = reference.get("bytes")
    if require_bytes and (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0):
        _record_failure(
            failures, "CAPACITY_CHECKPOINT_SEMANTICS",
            f"{role} requires a nonnegative integer byte declaration: {path}")
    if expected_bytes is not None and expected_bytes != result["bytes"]:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} byte count differs from declaration: {path}")
    return path, result


def _load_checkpoint(path: Path, *, expected_update: int,
                     model_kind: str, seed: int, run_id: str | None,
                     failures: list[dict[str, Any]], role: str) -> dict[str, Any]:
    """Check the serialized checkpoint identity without altering it."""
    try:
        import torch

        payload = torch.load(path, map_location="cpu", weights_only=False)
    except Exception as error:  # torch reports several version-specific errors
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} cannot be read: {error}")
        return {"path": str(path), "readable": False}
    if not isinstance(payload, Mapping):
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} is not a checkpoint mapping")
        return {"path": str(path), "readable": False}
    if payload.get("schema") != CHECKPOINT_SCHEMA:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} has unsupported checkpoint schema")
    if payload.get("update") != expected_update:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} update does not match {expected_update}")
    if payload.get("model_kind") != model_kind or payload.get("seed") != seed:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} model/seed identity differs from receipt")
    config = payload.get("config")
    if not isinstance(config, Mapping):
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} has no config mapping")
    elif run_id is not None and config.get("run_id") not in (None, run_id):
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} run_id differs from receipt")
    if payload.get("optimizer_state") is None:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} has no optimizer_state")
    if payload.get("sampler_state") is None:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} has no sampler_state")
    if payload.get("rng_state") is None:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} has no rng_state")
    if payload.get("evidence_status") != "complete":
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} evidence_status is not complete")
    return {
        "path": str(path), "readable": True, "schema": payload.get("schema"),
        "update": payload.get("update"), "model_kind": payload.get("model_kind"),
        "seed": payload.get("seed"), "evidence_status": payload.get("evidence_status"),
    }


def _verify_source_closure(source: Any, *, root: Path, code_root: Path,
                           execution: Mapping[str, Any],
                           failures: list[dict[str, Any]]) -> dict[str, Any]:
    if source is None:
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", "a current formal source closure is required")
        return {"bound": False, "valid": False}
    try:
        payload, path, source_digest, _ = _load_json(source, root=root)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", f"cannot load source closure: {error}")
        return {"bound": True, "valid": False}
    if payload.get("schema") != SOURCE_CLOSURE_SCHEMA or payload.get("complete") is not True:
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", "source closure schema or complete flag is invalid")
    if payload.get("required_files") != list(REQUIRED_CODE_FILES):
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", "source closure required_files do not match the formal planner closure")
    if payload.get("missing_files") not in (None, []):
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", "source closure declares missing files")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", "source closure has no files")
        files = []
    normalized: list[dict[str, Any]] = []
    declared_names: list[Any] = []
    for item in files:
        if not isinstance(item, Mapping):
            _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", "source closure contains a non-object file row")
            continue
        relative = item.get("relative_path")
        declared_names.append(relative)
        if relative not in REQUIRED_CODE_FILES:
            _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", f"unexpected source closure path: {relative}")
            continue
        candidate = (code_root / str(relative)).resolve()
        if not candidate.is_file():
            _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", f"source closure file is missing: {relative}")
            continue
        observed = sha256_file(candidate)
        if observed != item.get("sha256"):
            _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", f"source closure hash mismatch: {relative}")
        declared_bytes = item.get("bytes")
        if (isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int)
                or declared_bytes < 0 or declared_bytes != candidate.stat().st_size):
            _record_failure(failures, "CAPACITY_SOURCE_CLOSURE",
                            f"source closure byte count mismatch: {relative}")
        normalized.append({"relative_path": str(relative), "sha256": observed,
                           "bytes": candidate.stat().st_size})
    names = {item["relative_path"] for item in normalized}
    if declared_names != list(REQUIRED_CODE_FILES):
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", "source closure files must match the formal planner closure exactly once and in order")
    for required in REQUIRED_CODE_FILES:
        if required not in names:
            _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", f"source closure is missing {required}")
    closure_hash = canonical_sha256([
        {"relative_path": item["relative_path"], "sha256": item["sha256"]}
        for item in normalized
    ])
    if payload.get("closure_sha256") != closure_hash:
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE", "source closure digest does not match its file rows")
    declared_execution = execution.get("source_closure_sha256")
    if not _valid_sha(declared_execution) or declared_execution != closure_hash:
        _record_failure(failures, "CAPACITY_SOURCE_CLOSURE",
                        "execution sidecar source closure is missing or differs from closure record")
    result = {
        "bound": True, "valid": not any(item["code"] == "CAPACITY_SOURCE_CLOSURE" for item in failures),
        "path": _relative(path, root) if path is not None else "<in-memory>",
        "sha256": source_digest,
        "closure_sha256": closure_hash, "files": normalized,
    }
    return result


def _verify_manifest(source: Any, *, root: Path, receipt: Mapping[str, Any],
                     execution: Mapping[str, Any],
                     failures: list[dict[str, Any]]) -> dict[str, Any]:
    if source is None:
        _record_failure(failures, "CAPACITY_MANIFEST_BINDING", "a released reader manifest is required")
        return {"bound": False, "valid": False}
    try:
        manifest, path, raw_sha, _ = _load_json(source, root=root)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        _record_failure(failures, "CAPACITY_MANIFEST_BINDING", f"cannot load reader manifest: {error}")
        return {"bound": True, "valid": False}
    if manifest.get("schema") not in {"core.dataset.v1", "core.dataset.v2"}:
        _record_failure(failures, "CAPACITY_MANIFEST_BINDING", "reader manifest schema is not a Core dataset schema")
    if manifest.get("formal_release") is not True:
        _record_failure(failures, "CAPACITY_MANIFEST_BINDING", "reader manifest does not declare formal_release=true")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or not rows:
        _record_failure(failures, "CAPACITY_MANIFEST_BINDING", "reader manifest has no cases")
    canonical_sha = canonical_sha256(manifest)
    declared = receipt.get("config", {}).get("manifest_sha256") if isinstance(receipt.get("config"), Mapping) else None
    sidecar_declared = execution.get("manifest_sha256")
    acceptable = {raw_sha, canonical_sha}
    for value, role in ((declared, "receipt"), (sidecar_declared, "execution")):
        if not _valid_sha(value):
            _record_failure(failures, "CAPACITY_MANIFEST_BINDING",
                            f"{role} manifest hash declaration is missing or malformed")
        elif value not in acceptable:
            _record_failure(failures, "CAPACITY_MANIFEST_BINDING",
                            f"{role} manifest hash differs from reader manifest")
    return {
        "bound": True, "valid": not any(item["code"] == "CAPACITY_MANIFEST_BINDING" for item in failures),
        "path": _relative(path, root) if path is not None else "<in-memory>",
        "sha256": raw_sha, "canonical_sha256": canonical_sha,
        "formal_release": manifest.get("formal_release"), "case_count": len(rows) if isinstance(rows, list) else 0,
    }


def inspect_capacity_evidence(
    receipt: str | Path | Mapping[str, Any], *,
    execution: str | Path | Mapping[str, Any] | None,
    manifest: str | Path | Mapping[str, Any] | None,
    source_closure: str | Path | Mapping[str, Any] | None,
    data_root: str | Path,
    code_root: str | Path,
) -> dict[str, Any]:
    """Return a read-only capacity observation; never launch or count a job."""
    root = Path(data_root).expanduser().resolve()
    code = Path(code_root).expanduser().resolve()
    failures: list[dict[str, Any]] = []
    try:
        receipt_payload, receipt_path, receipt_sha, receipt_bytes = _load_json(receipt, root=root)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        _record_failure(failures, "CAPACITY_RECEIPT_SCHEMA", f"cannot load training receipt: {error}")
        return _result(None, None, failures, root=root)
    if receipt_payload.get("schema") != TRAINING_SCHEMA:
        _record_failure(failures, "CAPACITY_RECEIPT_SCHEMA", "receipt schema is not core.training.v1")
    try:
        execution_payload, execution_path, execution_sha, execution_bytes = _load_json(
            execution, root=root, base=receipt_path.parent if receipt_path else None
        ) if execution is not None else ({}, None, canonical_sha256({}), None)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        _record_failure(failures, "CAPACITY_EXECUTION_EVIDENCE", f"cannot load execution sidecar: {error}")
        execution_payload, execution_path = {}, None
    if execution is None:
        _record_failure(failures, "CAPACITY_EXECUTION_EVIDENCE", "real full-field execution sidecar is required")

    config = receipt_payload.get("config")
    if not isinstance(config, Mapping):
        config = {}
        _record_failure(failures, "CAPACITY_RECEIPT_SCHEMA", "training receipt has no config mapping")
    model_kind = receipt_payload.get("model_kind", config.get("model_kind"))
    seed = receipt_payload.get("seed", config.get("seed"))
    run_id = receipt_payload.get("run_id", config.get("run_id"))
    if model_kind not in GRAPH_MODELS:
        _record_failure(failures, "CAPACITY_MODEL_ADAPTER", "capacity evidence requires a graph_raw or graph_residual model")
    if not isinstance(seed, int) or isinstance(seed, bool):
        _record_failure(failures, "CAPACITY_RECEIPT_SCHEMA", "receipt seed is missing or not an integer")
    completed = receipt_payload.get("completed_updates")
    if completed != FORMAL_UPDATES or config.get("updates") != FORMAL_UPDATES:
        _record_failure(failures, "CAPACITY_UPDATE_FRONTIER", "receipt and config must both complete exactly 32000 updates")
    if receipt_payload.get("device", "").split(":", 1)[0] != "cuda":
        _record_failure(failures, "CAPACITY_EXECUTION_EVIDENCE", "capacity evidence must come from a CUDA execution")
    if receipt_payload.get("checkpoint_verified") is not True:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", "receipt checkpoint_verified must be true")
    evidence = receipt_payload.get("evidence")
    if receipt_payload.get("evidence_status") != "complete" or not isinstance(evidence, Mapping) or evidence.get("status") != "complete":
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", "training evidence must be complete")
    sampler = receipt_payload.get("sampler")
    if not isinstance(sampler, Mapping) or sampler.get("draws") != FORMAL_UPDATES:
        _record_failure(failures, "CAPACITY_UPDATE_FRONTIER", "sampler draw count must equal 32000 updates")

    execution_model = execution_payload.get("schema")
    if execution_model != EXECUTION_SCHEMA:
        _record_failure(failures, "CAPACITY_EXECUTION_EVIDENCE", "execution sidecar schema is invalid")
    constraints = execution_payload.get("execution_constraints")
    if not isinstance(constraints, Mapping):
        constraints = execution_payload
    required_false = {
        "synthetic_input": False, "formal_training": False,
        "formal_job_count": 0, "formal_runs_started": 0,
        "solver_started": False, "submitted": False,
        "central_registry_mutation": 0, "central_ledger_mutation": 0,
    }
    for key, expected in required_false.items():
        if constraints.get(key) != expected:
            _record_failure(failures, "CAPACITY_EXECUTION_EVIDENCE", f"execution constraint {key} must be {expected!r}")
    for key in ("full_particle_axis", "trajectory_files_opened", "checkpoint_written"):
        if constraints.get(key) is not True:
            _record_failure(failures, "CAPACITY_EXECUTION_EVIDENCE", f"execution constraint {key} must be true")
    if constraints.get("updates_completed") != FORMAL_UPDATES:
        _record_failure(failures, "CAPACITY_UPDATE_FRONTIER", "execution sidecar updates_completed must be 32000")
    if execution_payload.get("model_kind") not in (None, model_kind):
        _record_failure(failures, "CAPACITY_MODEL_ADAPTER", "execution model_kind differs from receipt")
    adapter = execution_payload.get("model_adapter")
    if not isinstance(adapter, Mapping) or adapter.get("schema") != MODEL_ADAPTER_SCHEMA or adapter.get("model_version") != MODEL_VERSION:
        _record_failure(failures, "CAPACITY_MODEL_ADAPTER", "execution sidecar is not bound to the Core dual-increment model adapter")
    elif adapter.get("model_kind") not in (None, model_kind):
        _record_failure(failures, "CAPACITY_MODEL_ADAPTER", "model adapter kind differs from receipt")
    resource = execution_payload.get("resource")
    if not isinstance(resource, Mapping):
        _record_failure(failures, "CAPACITY_RESOURCE_METRICS", "execution sidecar has no resource metrics")
        resource = {}
    if not _finite_positive(resource.get("wall_seconds")) or not _finite_positive(resource.get("peak_gpu_memory_bytes")):
        _record_failure(failures, "CAPACITY_RESOURCE_METRICS", "wall_seconds and peak_gpu_memory_bytes must be finite positive values")

    final_ref = receipt_payload.get("checkpoint")
    checkpoint_refs: list[tuple[int, Mapping[str, Any], str]] = []
    if isinstance(final_ref, Mapping):
        checkpoint_refs.append((FORMAL_UPDATES, final_ref, "final checkpoint"))
    else:
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", "receipt has no final checkpoint reference")
    milestone_refs = receipt_payload.get("milestone_checkpoints")
    by_update: dict[int, Mapping[str, Any]] = {}
    if isinstance(milestone_refs, list):
        for item in milestone_refs:
            if isinstance(item, Mapping) and isinstance(item.get("update"), int):
                by_update[int(item["update"])] = item
    if set(by_update) != set(MILESTONES):
        _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", "receipt must bind exactly the four 8k/16k/24k/32k milestone checkpoints")
    for update in MILESTONES:
        if update in by_update:
            checkpoint_refs.append((update, by_update[update], f"milestone checkpoint {update}"))
    checkpoint_observations: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for update, reference, role in checkpoint_refs:
        path, observed = _file_ref(
            reference, root=root, base=receipt_path.parent if receipt_path else None,
            failures=failures, role=role, require_bytes=True
        )
        if path is None or observed is None:
            continue
        if path in seen_paths and role != "final checkpoint":
            _record_failure(failures, "CAPACITY_CHECKPOINT_SEMANTICS", f"{role} reuses a prior checkpoint path")
        seen_paths.add(path)
        checkpoint_observations.append({
            "update": update, "role": role, "reference": observed,
            "payload": _load_checkpoint(path, expected_update=update,
                                         model_kind=str(model_kind), seed=int(seed) if isinstance(seed, int) else -1,
                                         run_id=str(run_id) if run_id is not None else None,
                                         failures=failures, role=role),
        })

    manifest_observation = _verify_manifest(
        manifest, root=root, receipt=receipt_payload,
        execution=execution_payload, failures=failures)
    closure_observation = _verify_source_closure(
        source_closure, root=root, code_root=code,
        execution=execution_payload, failures=failures)
    return _result(
        receipt_payload, receipt_path, failures, root=root,
        execution=execution_payload, execution_path=execution_path,
        receipt_reference=(
            _ref(receipt_path, root, digest=receipt_sha, byte_count=receipt_bytes)
            if receipt_path is not None and receipt_bytes is not None else None
        ),
        execution_reference=(
            _ref(execution_path, root, digest=execution_sha, byte_count=execution_bytes)
            if execution_path is not None and execution_bytes is not None else None
        ),
        manifest=manifest_observation, source_closure=closure_observation,
        checkpoints=checkpoint_observations, resource=dict(resource),
        observed_update_frontier=int(completed) if isinstance(completed, int) else 0,
    )


def _result(
    receipt: Mapping[str, Any] | None, receipt_path: Path | None,
    failures: Sequence[Mapping[str, Any]], *, root: Path,
    execution: Mapping[str, Any] | None = None, execution_path: Path | None = None,
    receipt_reference: Mapping[str, Any] | None = None,
    execution_reference: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
    source_closure: Mapping[str, Any] | None = None,
    checkpoints: Sequence[Mapping[str, Any]] = (), resource: Mapping[str, Any] | None = None,
    observed_update_frontier: int = 0,
) -> dict[str, Any]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for failure in failures:
        row = {"code": str(failure.get("code")), "message": str(failure.get("message"))}
        key = (row["code"], row["message"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    unique.sort(key=lambda item: (item["code"], item["message"]))
    valid = not unique
    receipt_ref = dict(receipt_reference) if receipt_reference is not None else None
    if receipt_ref is None and receipt_path is not None and receipt_path.is_file():
        receipt_ref = _ref(receipt_path, root)
    execution_ref = dict(execution_reference) if execution_reference is not None else None
    if execution_ref is None and execution_path is not None and execution_path.is_file():
        execution_ref = _ref(execution_path, root)
    return {
        "schema": SCHEMA,
        "status": "ready" if valid else "blocked",
        "valid": valid,
        "formal_capacity_evidence": valid,
        "formal_training": False,
        "formal_job_count": 0,
        "formal_runs_counted": 0,
        "diagnostic_runs_counted_as_formal": False,
        "observed_update_frontier": int(observed_update_frontier),
        "formal_update_target": FORMAL_UPDATES,
        "receipt": receipt_ref,
        "execution": execution_ref,
        "manifest": dict(manifest or {"bound": False, "valid": False}),
        "source_closure": dict(source_closure or {"bound": False, "valid": False}),
        "checkpoints": list(checkpoints),
        "resource": dict(resource or {}),
        "blocker_codes": sorted({str(item["code"]) for item in unique}),
        "blockers": unique,
        "execution_constraints": {
            "read_only": True,
            "trajectory_files_opened": bool((execution or {}).get("execution_constraints", {}).get("trajectory_files_opened") is True),
            "future_state_inputs": False,
            "formal_runs_started": 0,
            "gpu_started": False,
            "solver_started": False,
            "submitted": False,
            "central_registry_mutation": 0,
            "central_ledger_mutation": 0,
            "checkpoint_written": False,
            "training_receipt_written": False,
        },
        "interpretation": (
            "A valid record is a read-only adapter over a real 32000-update full-field CUDA receipt. "
            "It proves resource/checkpoint capacity for admission review only; it never counts a formal "
            "model-seed run or authorizes submission."
        ),
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"capacity evidence output is immutable and already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                  ensure_ascii=False, allow_nan=False) + "\n",
                       encoding="utf-8")
    partial.replace(target)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-closure", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = inspect_capacity_evidence(
        args.receipt, execution=args.execution, manifest=args.manifest,
        source_closure=args.source_closure, data_root=args.data_root,
        code_root=args.code_root)
    write_json(args.output, report)
    print(json.dumps({
        "schema": report["schema"], "status": report["status"],
        "formal_capacity_evidence": report["formal_capacity_evidence"],
        "observed_update_frontier": report["observed_update_frontier"],
        "blocker_codes": report["blocker_codes"],
    }, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
