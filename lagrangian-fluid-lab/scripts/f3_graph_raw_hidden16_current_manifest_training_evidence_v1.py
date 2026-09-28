#!/usr/bin/env python3
"""Bound F3 graph_raw hidden16 current-manifest training evidence.

This is an additive, non-authorizing intake boundary.  It opens only the
explicit current manifest and the three explicit ``core.training.v1`` receipt
JSON files, each under a bounded byte budget.  Checkpoint, HDF5, trajectory,
and progress content is never opened or stat'ed, and no process or GPU is
started.  A missing, running, partial, drifting, or unknown-field receipt is
reported as ``blocked_fail_closed``.

The intake is deliberately separate from the current-manifest case matrix:
the matrix plans future diagnostic rollouts, while this report binds only the
training identity that those plans may reference.  All successful bindings
remain diagnostic-only and zero-credit.
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
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL = "graph_raw"
HIDDEN = 16
UPDATES = 500
MANIFEST_SCHEMA = "core.dataset.v2"
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
SCHEMA = "core.f3.graph_raw.hidden16.current_manifest_training_evidence.v1"
REPORT_ID = "f3-graph-raw-hidden16-current-manifest-training-evidence-v1"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(
    r"^f3-graph_raw500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-"
    r"(?P<date>20[0-9]{6})-v3$"
)
RECEIPT_NAME_RE = re.compile(
    r"^f3-graph_raw500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-"
    r"(?P<date>20[0-9]{6})-v3-training\.json$"
)
CHECKPOINT_NAME_RE = re.compile(
    r"^f3-graph_raw500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-"
    r"(?P<date>20[0-9]{6})-v3-checkpoint\.pt$"
)
TERMINAL_STATUSES = frozenset({"complete", "completed", "terminal_completed", "exited_successfully"})

STATIC_CONFIG: dict[str, Any] = {
    "centers_per_update": 256,
    "checkpoint_every": 500,
    "evaluate_milestones": False,
    "gradient_clipping": None,
    "hidden": HIDDEN,
    "history_states": 1,
    "initialization": "core.paired_initialization.common_encoder_head.v1",
    "learning_rate": 0.001,
    "log_every": 100,
    "manifest_formal_release": False,
    "max_neighbors": 192,
    "milestone_evaluation_mode": "deferred",
    "model_kind": MODEL,
    "normalization_source_split": "train",
    "optimizer": "Adam",
    "radius_over_h": 2.0,
    "target_normalization": "raw_dual_increment_train_shared",
    "updates": UPDATES,
    "validation_case_count": 4,
    "validation_centers": 256,
    "validation_every": 0,
    "validation_family_counts": {"F3": 4},
    "validation_formal_eligible": False,
    "validation_transition_count": 4,
}

DEFAULT_RECEIPTS = {
    seed: f"/tmp/f3-graph_raw500-hidden16-currentmanifest-seed{seed}-20260929-v3-training.json"
    for seed in SEEDS
}
DEFAULT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
DEFAULT_OUTPUT = LAB_ROOT / "reports" / "F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29.json"
DEFAULT_MARKDOWN_OUTPUT = DEFAULT_OUTPUT.with_suffix(".zh-CN.md")

ZERO_CREDIT = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "credit": 0,
    "qualification_credit": 0,
}


class IntakeError(ValueError):
    """Malformed, drifting, unsafe, or non-authorizing input."""


def _fail(message: str) -> None:
    raise IntakeError(f"fail-closed: {message}")


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


def _integer(value: Any, name: str, minimum: int = 0) -> int:
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
        _fail(f"{name}.{key} must be {expected!r}")


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail(f"{name} contains unknown field(s): {', '.join(unknown)}")


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


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor or os.curdir)
    for component in path.parts[1:] if path.is_absolute() else path.parts:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as error:
            _fail(f"cannot inspect input path component {current}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"symlink path component is not accepted: {current}")


def _resolve_input_path(root: Path, value: Path | str, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    candidate = Path(raw)
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a lexical path alias")
    path = Path(os.path.normpath(str(candidate if candidate.is_absolute() else root / candidate)))
    root_path = Path(os.path.normpath(str(root)))
    allowed_roots = (root_path, Path("/tmp"))
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        _fail(f"{name} escapes bounded input roots")
    _reject_symlink_components(path)
    return path


def _read_bounded_bytes(root: Path, value: Path | str, *, name: str, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    path = _resolve_input_path(root, value, name)
    if path.suffix.lower() != ".json":
        _fail(f"{name} must be a JSON file")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        _fail(f"{name} cannot be opened: {error}")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{name} must be a regular single-link file")
        if before.st_size > max_bytes:
            _fail(f"{name} exceeds bounded size {max_bytes}")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            block = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or total != before.st_size:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"{name} cannot be read: {error}")
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if len(raw) > max_bytes:
        _fail(f"{name} exceeds bounded size {max_bytes}")
    return raw, {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "opened": True}


def read_bounded_json(root: Path | str, value: Path | str, *, name: str, max_bytes: int) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, source = _read_bounded_bytes(Path(root), value, name=name, max_bytes=max_bytes)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, IntakeError, RecursionError) as error:
        _fail(f"{name} is not valid bounded UTF-8 JSON: {error}")
    _walk_json(payload, name)
    if not isinstance(payload, dict):
        _fail(f"{name} must contain a JSON object")
    source["schema"] = payload.get("schema")
    return payload, source


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        _fail(f"value cannot be canonically hashed: {error}")
    return hashlib.sha256(raw).hexdigest()


def _authority_markers(value: Mapping[str, Any], name: str) -> None:
    for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
        if key in value:
            _exact(value, key, False, name)
    for key in ("credit", "qualification_credit"):
        if key in value:
            _exact(value, key, 0, name)
    if "diagnostic_only" in value:
        _exact(value, "diagnostic_only", True, name)


def _validate_manifest(payload: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown(
        payload,
        {"schema", "case_count", "dataset_id", "formal_release", "input_asset_policy", "source_manifest_sha256", "cases", "source_qualification_claims"},
        "manifest",
    )
    _exact(payload, "schema", MANIFEST_SCHEMA, "manifest")
    _exact(payload, "case_count", 32, "manifest")
    _exact(payload, "dataset_id", "F3_registered32_core_native_v2", "manifest")
    _exact(payload, "formal_release", False, "manifest")
    _sha(payload.get("source_manifest_sha256"), "manifest.source_manifest_sha256")
    return {
        "schema": payload["schema"],
        "dataset_id": payload["dataset_id"],
        "case_count": payload["case_count"],
        "formal_release": payload["formal_release"],
        "source_manifest_sha256": payload["source_manifest_sha256"],
        "raw": dict(source),
    }


def _declared_checkpoint(value: Mapping[str, Any], *, seed: int, date: str, name: str) -> dict[str, Any]:
    _reject_unknown(value, {"bytes", "path", "schema", "sha256", "update"}, name)
    _exact(value, "schema", CHECKPOINT_SCHEMA, name)
    _exact(value, "update", UPDATES, name)
    path = _string(value.get("path"), f"{name}.path")
    path_obj = Path(path)
    if not path_obj.is_absolute() or any(part in {".", ".."} for part in path_obj.parts) or path_obj.suffix.lower() == ".json":
        _fail(f"{name}.path must be an absolute lexical-safe non-JSON path")
    match = CHECKPOINT_NAME_RE.fullmatch(path_obj.name)
    if match is None or int(match.group("seed")) != seed or match.group("date") != date:
        _fail(f"{name}.path drifted from seed{seed} current-manifest run {date}")
    return {
        "schema": CHECKPOINT_SCHEMA,
        "path": path,
        "bytes": _integer(value.get("bytes"), f"{name}.bytes", minimum=1),
        "sha256": _sha(value.get("sha256"), f"{name}.sha256"),
        "update": UPDATES,
    }


def _validate_config(value: Mapping[str, Any], *, seed: int, run_id: str, manifest_sha256: str, name: str) -> dict[str, Any]:
    expected_keys = set(STATIC_CONFIG) | {"manifest_sha256", "paired_seed", "run_id", "sampler_seed", "seed"}
    _reject_unknown(value, expected_keys, name)
    if set(value) != expected_keys:
        _fail(f"{name} keys drift")
    for key, expected in STATIC_CONFIG.items():
        if value.get(key) != expected:
            _fail(f"{name}.{key} drifts")
    _exact(value, "manifest_sha256", manifest_sha256, name)
    _exact(value, "run_id", run_id, name)
    for key in ("seed", "paired_seed", "sampler_seed"):
        _exact(value, key, seed, name)
    return dict(value)


def _validate_evidence(value: Mapping[str, Any], *, seed: int, parameter_count: int, name: str) -> None:
    _reject_unknown(value, {"schema", "status", "initialization", "normalization", "residual_prior", "resume_semantics"}, name)
    _exact(value, "schema", "core.training.evidence.v1", name)
    _exact(value, "status", "complete", name)
    initialization = _mapping(value.get("initialization"), f"{name}.initialization")
    _reject_unknown(initialization, {"constructed_before_first_update", "construction_update", "hidden", "model_kind", "parameter_count", "parameter_digest", "schema", "seed", "status"}, f"{name}.initialization")
    _exact(initialization, "schema", "core.training.initialization_evidence.v1", f"{name}.initialization")
    _exact(initialization, "status", "captured", f"{name}.initialization")
    _exact(initialization, "constructed_before_first_update", True, f"{name}.initialization")
    _exact(initialization, "construction_update", 0, f"{name}.initialization")
    _exact(initialization, "hidden", HIDDEN, f"{name}.initialization")
    _exact(initialization, "model_kind", MODEL, f"{name}.initialization")
    _exact(initialization, "seed", seed, f"{name}.initialization")
    _exact(initialization, "parameter_count", parameter_count, f"{name}.initialization")
    _sha(initialization.get("parameter_digest"), f"{name}.initialization.parameter_digest")
    normalization = _mapping(value.get("normalization"), f"{name}.normalization")
    _reject_unknown(normalization, {"available_transition_count", "requested_maximum_transitions", "schema", "selected_case_ids", "selected_transition_bindings", "selected_transition_count", "selected_transition_counts", "selection_policy", "selection_seed", "source_split", "target_reference", "train_case_ids"}, f"{name}.normalization")
    _exact(normalization, "schema", "core.training.normalization_evidence.v1", f"{name}.normalization")
    _exact(normalization, "requested_maximum_transitions", 16, f"{name}.normalization")
    _exact(normalization, "selected_transition_count", 16, f"{name}.normalization")
    _exact(normalization, "selection_policy", "deterministic_evenly_spaced_train_transitions_v1", f"{name}.normalization")
    _exact(normalization, "selection_seed", seed, f"{name}.normalization")
    _exact(normalization, "source_split", "train", f"{name}.normalization")
    _exact(normalization, "target_reference", "raw_dual_increment_train_shared", f"{name}.normalization")
    if "residual_prior" in value:
        prior = _mapping(value["residual_prior"], f"{name}.residual_prior")
        _reject_unknown(prior, {"dv_abs_max_mps", "dv_abs_sum_mps", "dx_abs_max_m", "dx_abs_sum_m", "enabled", "execution_calls", "finite", "history_complete", "last_update", "rows", "schema", "semantic", "units"}, f"{name}.residual_prior")
    if "resume_semantics" in value:
        resume = _mapping(value["resume_semantics"], f"{name}.resume_semantics")
        _reject_unknown(resume, {"construction_digest_preserved_across_resume", "loaded_weights_are_not_initial"}, f"{name}.resume_semantics")


def _validate_receipt(receipt: Mapping[str, Any], source: Mapping[str, Any], *, seed: int, manifest_meta: Mapping[str, Any]) -> dict[str, Any]:
    name = f"seed{seed}"
    allowed = {
        "checkpoint", "checkpoint_verified", "checkpoints", "completed_updates", "config", "device", "evidence", "evidence_status",
        "history", "host", "milestone_checkpoints", "milestone_evaluation_plan", "milestone_evaluations", "milestone_selection",
        "milestone_selection_error", "milestone_updates", "model", "model_kind", "normalization", "parameter_count",
        "peak_gpu_memory_bytes", "peak_rss_mib", "progress_path", "run_id", "sampler", "schema", "seed", "status",
        "torch_version", "validation_history", "wall_seconds", "diagnostic_only", "formal", "formal_eligible", "T1_numerical",
        "T2_macro", "T2_path", "qualification", "credit", "qualification_credit",
    }
    _reject_unknown(receipt, allowed, name)
    _exact(receipt, "schema", TRAINING_SCHEMA, name)
    _exact(receipt, "evidence_status", "complete", name)
    if "status" in receipt:
        _exact(receipt, "status", "completed", name)
    _exact(receipt, "model_kind", MODEL, name)
    if "model" in receipt:
        _exact(receipt, "model", MODEL, name)
    _exact(receipt, "seed", seed, name)
    _exact(receipt, "completed_updates", UPDATES, name)
    _exact(receipt, "checkpoint_verified", True, name)
    _authority_markers(receipt, name)
    run_id = _string(receipt.get("run_id"), f"{name}.run_id")
    run_match = RUN_ID_RE.fullmatch(run_id)
    if run_match is None or int(run_match.group("seed")) != seed:
        _fail(f"{name}.run_id is not the current-manifest v3 identity for seed {seed}")
    receipt_match = RECEIPT_NAME_RE.fullmatch(Path(str(source["path"])).name)
    if receipt_match is None or int(receipt_match.group("seed")) != seed or receipt_match.group("date") != run_match.group("date"):
        _fail(f"{name} receipt path drifted from run_id")
    config = _validate_config(receipt.get("config"), seed=seed, run_id=run_id, manifest_sha256=str(manifest_meta["canonical_sha256"]), name=f"{name}.config")
    parameter_count = _integer(receipt.get("parameter_count"), f"{name}.parameter_count", minimum=1)
    checkpoint = _declared_checkpoint(_mapping(receipt.get("checkpoint"), f"{name}.checkpoint"), seed=seed, date=run_match.group("date"), name=f"{name}.checkpoint")
    if checkpoint["path"] == source["path"]:
        _fail(f"{name}.checkpoint.path aliases the training receipt")
    checkpoints = receipt.get("checkpoints")
    if checkpoints is not None:
        if not isinstance(checkpoints, list) or not checkpoints:
            _fail(f"{name}.checkpoints must be a non-empty array")
        terminal = _declared_checkpoint(_mapping(checkpoints[-1], f"{name}.checkpoints[-1]"), seed=seed, date=run_match.group("date"), name=f"{name}.checkpoints[-1]")
        if terminal != checkpoint:
            _fail(f"{name}.checkpoint identity drifts from terminal checkpoints entry")
    _validate_evidence(_mapping(receipt.get("evidence"), f"{name}.evidence"), seed=seed, parameter_count=parameter_count, name=f"{name}.evidence")
    return {
        "seed": seed,
        "status": "bound",
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "completed": True,
        "run_id": run_id,
        "receipt_identity": {"path": source["path"], "bytes": source["bytes"], "sha256": source["sha256"]},
        "checkpoint_identity": checkpoint,
        "manifest_identity": {
            "path": manifest_meta["raw"]["path"],
            "bytes": manifest_meta["raw"]["bytes"],
            "raw_sha256": manifest_meta["raw"]["sha256"],
            "canonical_sha256": manifest_meta["canonical_sha256"],
        },
        "config_identity": {"model_kind": config["model_kind"], "hidden": config["hidden"], "updates": config["updates"], "run_id": config["run_id"], "manifest_sha256": config["manifest_sha256"]},
        **ZERO_CREDIT,
    }


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason, "observed": observed, "expected": expected}


def _empty_source(value: Path | str | None) -> dict[str, Any]:
    return {"path": str(value) if value is not None else "<missing>", "bytes": None, "sha256": None, "opened": False}


def _manifest_record(source: Mapping[str, Any] | None, payload: Mapping[str, Any] | None, canonical_sha256: str | None) -> dict[str, Any]:
    result = dict(source or {})
    result.setdefault("path", "<missing>")
    result.setdefault("bytes", None)
    result.setdefault("sha256", None)
    result.setdefault("opened", False)
    result["schema"] = payload.get("schema") if payload is not None else None
    result["dataset_id"] = payload.get("dataset_id") if payload is not None else None
    result["canonical_sha256"] = canonical_sha256
    return result


def build_report(
    manifest_path: Path | str,
    training_receipts: Mapping[int, Path | str],
    *,
    root: Path | str = LAB_ROOT,
    seed_statuses: Mapping[int, str] | None = None,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a bounded current-manifest diagnostic report."""

    root_path = Path(root)
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    manifest_payload: Mapping[str, Any] | None = None
    manifest_source: Mapping[str, Any] | None = None
    manifest_meta: dict[str, Any] | None = None
    manifest_canonical_sha256: str | None = None
    try:
        manifest_payload, manifest_source = read_bounded_json(root_path, manifest_path, name="manifest", max_bytes=MAX_MANIFEST_BYTES)
        manifest_canonical_sha256 = _canonical_sha256(manifest_payload)
        manifest_meta = _validate_manifest(manifest_payload, manifest_source)
        manifest_meta["canonical_sha256"] = manifest_canonical_sha256
        checks.extend([
            _check("manifest_raw_identity", True, "raw manifest bytes were hashed from the explicit path", manifest_source["sha256"], "actual manifest file SHA-256"),
            _check("manifest_canonical_identity", True, "canonical manifest payload identity was computed without opening dataset content", manifest_canonical_sha256, "canonical manifest SHA-256"),
        ])
    except IntakeError as error:
        errors.append(str(error))
        try:
            resolved = _resolve_input_path(root_path, manifest_path, "manifest")
        except IntakeError:
            resolved = Path(str(manifest_path))
        manifest_source = _empty_source(resolved)
        checks.append(_check("manifest_raw_identity", False, "explicit manifest could not be read and hashed", None, "bounded current manifest JSON"))
    manifest_record = _manifest_record(manifest_source, manifest_payload, manifest_canonical_sha256)
    manifest_ok = manifest_meta is not None and manifest_canonical_sha256 is not None

    receipt_keys = sorted(training_receipts.keys(), key=lambda item: (type(item).__name__, repr(item))) if isinstance(training_receipts, Mapping) else []
    exact_seed_set = isinstance(training_receipts, Mapping) and set(training_receipts) == set(SEEDS)
    checks.insert(0, _check("exact_seed_set", exact_seed_set, "receipt slots must contain exactly seeds 17, 29, and 43", receipt_keys, list(SEEDS)))
    if not exact_seed_set:
        errors.append(f"fail-closed: training receipt seed set drift: observed {receipt_keys}, expected {list(SEEDS)}")
    statuses = dict(seed_statuses or {})
    if set(statuses) - set(SEEDS):
        errors.append(f"fail-closed: status slots must use only seeds {list(SEEDS)}")
    rows: list[dict[str, Any]] = []
    projections: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        value = training_receipts.get(seed) if isinstance(training_receipts, Mapping) else None
        hint = statuses.get(seed)
        row: dict[str, Any] = {"seed": seed, "status": "missing" if value is None else "rejected", "source": _empty_source(value), "blocked_reasons": []}
        if value is None:
            message = f"fail-closed: missing training receipt for seed {seed}"
            row["blocked_reasons"].append(message)
            errors.append(message)
            rows.append(row)
            continue
        if hint and hint not in TERMINAL_STATUSES:
            message = f"fail-closed: seed{seed} declared status {hint!r} is non-terminal"
            row["status"] = "blocked"
            row["blocked_reasons"].append(message)
            errors.append(message)
            rows.append(row)
            continue
        try:
            receipt, source = read_bounded_json(root_path, value, name=f"training receipt seed{seed}", max_bytes=MAX_JSON_BYTES)
            row["source"] = source
            if manifest_meta is None:
                _fail("current manifest identity is unavailable")
            projection = _validate_receipt(receipt, source, seed=seed, manifest_meta=manifest_meta)
            projections[seed] = projection
            row["status"] = "bound"
            row["evidence"] = projection
        except IntakeError as error:
            message = str(error)
            if "No such file or directory" in message:
                row["status"] = "missing"
            row["blocked_reasons"].append(message)
            errors.append(f"seed{seed}: {message}")
        rows.append(row)

    manifest_match = manifest_ok and len(projections) == len(SEEDS) and all(
        item["manifest_identity"]["canonical_sha256"] == manifest_canonical_sha256
        and item["manifest_identity"]["raw_sha256"] == manifest_record["sha256"]
        and item["manifest_identity"]["bytes"] == manifest_record["bytes"]
        for item in projections.values()
    )
    checks.append(_check("manifest_canonical_and_raw_cross_binding", manifest_match, "every accepted run carries the actual manifest raw and canonical identities", sorted({item["manifest_identity"]["canonical_sha256"] for item in projections.values()}), {"canonical_sha256": manifest_canonical_sha256, "raw_sha256": manifest_record["sha256"], "bytes": manifest_record["bytes"]}))
    if not manifest_match:
        errors.append("fail-closed: receipt identities do not cross-bind to the current manifest canonical and raw identity")

    run_ids = [projections[seed]["run_id"] for seed in SEEDS if seed in projections]
    receipt_ids = [projections[seed]["receipt_identity"]["sha256"] for seed in SEEDS if seed in projections]
    checkpoint_ids = [(projections[seed]["checkpoint_identity"]["path"], projections[seed]["checkpoint_identity"]["sha256"]) for seed in SEEDS if seed in projections]
    identity_ok = len(projections) == len(SEEDS) and len(set(run_ids)) == len(SEEDS) and len(set(receipt_ids)) == len(SEEDS) and len(set(checkpoint_ids)) == len(SEEDS)
    checks.append(_check("unique_run_receipt_checkpoint_identity", identity_ok, "run_id, receipt-file, and declared checkpoint identities are unique", {"run_ids": run_ids, "receipt_sha256": receipt_ids, "checkpoint_path_sha256": checkpoint_ids}, "three independent seed identities"))
    if not identity_ok:
        errors.append("fail-closed: run, receipt, or declared checkpoint identity is duplicated or incomplete")
    protocol_ok = len(projections) == len(SEEDS) and all(item["model"] == MODEL and item["hidden"] == HIDDEN and item["updates"] == UPDATES and item["completed"] is True for item in projections.values())
    checks.append(_check("graph_raw_hidden16_completed_protocol", protocol_ok, "all accepted receipts declare completed graph_raw hidden16 500-update training", [{"seed": item["seed"], "model": item["model"], "hidden": item["hidden"], "updates": item["updates"], "completed": item["completed"]} for item in projections.values()], {"model": MODEL, "hidden": HIDDEN, "updates": UPDATES, "completed": True}))
    zero_credit_ok = all(item.get("diagnostic_only") is True and item.get("formal") is False and item.get("T1_numerical") is False and item.get("T2_macro") is False and item.get("T2_path") is False and item.get("credit") == 0 for item in projections.values()) and len(projections) == len(SEEDS)
    checks.append(_check("zero_credit_non_authorizing", zero_credit_ok, "all accepted receipt metadata remains diagnostic-only and zero-credit", zero_credit_ok, True))
    if not zero_credit_ok:
        errors.append("fail-closed: receipt zero-credit contract is incomplete")
    errors = list(dict.fromkeys(errors))
    all_bound = manifest_ok and exact_seed_set and len(projections) == len(SEEDS) and manifest_match and identity_ok and protocol_ok and zero_credit_ok and not errors
    if not all_bound:
        for row in rows:
            if row["status"] == "bound":
                row["status"] = "blocked"
                row["blocked_reasons"].append("fail-closed: current-manifest intake did not bind as one complete set")
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc or datetime.now(timezone.utc).isoformat(),
        "status": "diagnostic_bound" if all_bound else "blocked_fail_closed",
        "fail_closed": not all_bound,
        "source_bound": all_bound,
        **ZERO_CREDIT,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seeds": list(SEEDS),
        "formal_training_runs_counted": 0,
        "t1_case_runs_counted": 0,
        "t2_macro_families_counted": 0,
        "manifest": manifest_record,
        "runs": rows,
        "checks": checks,
        "errors": errors,
        "authorization": {key: ZERO_CREDIT[key] for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification", "credit", "qualification_credit")},
        "input_boundary": {
            "bounded_json_only": True,
            "bounded_manifest_json_opened": bool(manifest_record.get("opened")),
            "bounded_training_receipts_json_opened": sum(1 for row in rows if row["source"].get("opened")),
            "checkpoint_content_opened": False,
            "checkpoint_lstat_performed": False,
            "hdf5_content_opened": False,
            "trajectory_content_opened": False,
            "progress_content_opened": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_read": False,
            "ledger_read": False,
        },
        "side_effects": {
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
            "runtime_started": False,
            "checkpoint_opened": False,
            "hdf5_opened": False,
            "progress_opened": False,
        },
        "scope_note": "additive bounded graph_raw current-manifest training-evidence intake; no formal/T1/T2/credit authority",
    }
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate report authority and boundary markers without opening inputs."""

    errors: list[str] = []
    try:
        _walk_json(report, "report")
    except IntakeError as error:
        errors.append(str(error))
    if report.get("schema") != SCHEMA:
        errors.append("report schema drift")
    if report.get("report_id") != REPORT_ID:
        errors.append("report id drift")
    source_bound = report.get("source_bound") is True
    if report.get("status") != ("diagnostic_bound" if source_bound else "blocked_fail_closed"):
        errors.append("status/source_bound mismatch")
    if report.get("fail_closed") is not (not source_bound):
        errors.append("fail_closed/source_bound mismatch")
    for key, expected in ZERO_CREDIT.items():
        if report.get(key) != expected:
            errors.append(f"{key} must be {expected!r}")
    if report.get("model") != MODEL or report.get("hidden") != HIDDEN or report.get("updates") != UPDATES:
        errors.append("graph_raw hidden16 protocol drift")
    manifest = report.get("manifest")
    if not isinstance(manifest, Mapping):
        errors.append("manifest must be an object")
    else:
        for key in ("path", "bytes", "sha256", "canonical_sha256"):
            if key not in manifest:
                errors.append(f"manifest.{key} missing")
        if manifest.get("opened") is True:
            if type(manifest.get("bytes")) is not int or manifest["bytes"] < 1:
                errors.append("manifest.bytes must be positive when opened")
            for key in ("sha256", "canonical_sha256"):
                try:
                    _sha(manifest.get(key), f"manifest.{key}")
                except IntakeError as error:
                    errors.append(str(error))
    runs = report.get("runs")
    if not isinstance(runs, list) or len(runs) != len(SEEDS):
        errors.append("runs must contain exactly three seed rows")
    else:
        observed = {row.get("seed") for row in runs if isinstance(row, Mapping)}
        if observed != set(SEEDS):
            errors.append("runs must cover exactly seeds 17, 29, and 43")
    boundary = report.get("input_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("input_boundary must be an object")
    else:
        for key in ("checkpoint_content_opened", "checkpoint_lstat_performed", "hdf5_content_opened", "trajectory_content_opened", "progress_content_opened", "gpu_started", "solver_started", "registry_read", "ledger_read"):
            if boundary.get(key) is not False:
                errors.append(f"input_boundary.{key} must be false")
    side_effects = report.get("side_effects")
    if not isinstance(side_effects, Mapping):
        errors.append("side_effects must be an object")
    else:
        for key in ("registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation", "completion_mutation"):
            if side_effects.get(key) != 0:
                errors.append(f"side_effects.{key} must be zero")
        for key in ("runtime_started", "checkpoint_opened", "hdf5_opened", "progress_opened"):
            if side_effects.get(key) is not False:
                errors.append(f"side_effects.{key} must be false")
    return list(dict.fromkeys(errors))


def _safe_output_path(root: Path, value: Path | str) -> Path:
    path = _resolve_input_path(root, value, "output")
    if path.suffix.lower() != ".json":
        _fail("output must use the .json suffix")
    if not path.parent.is_dir():
        _fail("output parent directory must already exist")
    return path


def write_report(report: Mapping[str, Any], output: Path | str, *, root: Path | str = LAB_ROOT) -> Path:
    target = _safe_output_path(Path(root), output)
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except OSError as error:
        _fail(f"output refuses overwrite or cannot be created: {error}")
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def render_markdown(report: Mapping[str, Any]) -> str:
    manifest = _mapping(report.get("manifest"), "report.manifest")
    lines = [
        "# F3 graph_raw hidden16 current-manifest training evidence",
        "",
        f"- 状态：`{report['status']}`；source-bound：`{report['source_bound']}`；diagnostic-only：`{report['diagnostic_only']}`",
        f"- 当前 manifest：`{manifest.get('path')}`；raw SHA：`{manifest.get('sha256')}`；canonical SHA：`{manifest.get('canonical_sha256')}`",
        f"- 协议：`{MODEL}` / hidden `{HIDDEN}` / updates `{UPDATES}`；seed `{','.join(str(seed) for seed in SEEDS)}`",
        f"- formal/T1/T2/qualification：全部 `false`；credit：`{report['credit']}`",
        "- 边界：只读取 bounded manifest 与 training receipt JSON；不打开 checkpoint、HDF5、trajectory 或 progress，不启动/控制 GPU。",
        "",
        "| seed | status | receipt | checkpoint declared |",
        "|---:|---|---|---|",
    ]
    for row in report["runs"]:
        evidence = row.get("evidence", {}) if isinstance(row, Mapping) else {}
        checkpoint = evidence.get("checkpoint_identity", {}) if isinstance(evidence, Mapping) else {}
        lines.append(f"| {row.get('seed')} | `{row.get('status')}` | `{row.get('source', {}).get('path')}` | `{checkpoint.get('path', '—')}` |")
    lines.extend(["", str(report.get("scope_note", "")), ""])
    return "\n".join(lines)


def _parse_bindings(values: Sequence[str], *, label: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"--{label} must use SEED=VALUE")
        seed_text, value = item.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise ValueError(f"--{label} seed must be an integer: {seed_text!r}") from error
        if seed in result:
            raise ValueError(f"duplicate --{label} seed: {seed}")
        if not value:
            raise ValueError(f"--{label} value must be non-empty for seed {seed}")
        result[seed] = value
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="explicit current canonical manifest JSON path")
    parser.add_argument("--training-receipt", "--seed-receipt", action="append", default=[], metavar="SEED=PATH", help="explicit current v3 core.training.v1 receipt path; repeat for seeds 17, 29, and 43")
    parser.add_argument("--seed-status", action="append", default=[], metavar="SEED=STATUS", help="optional declared status; running/partial/missing values fail closed before receipt reads")
    parser.add_argument("--root", default=str(LAB_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--verify-report")
    args = parser.parse_args(argv)
    try:
        if args.verify_report:
            payload, _ = read_bounded_json(args.root, args.verify_report, name="report", max_bytes=MAX_REPORT_BYTES)
            report_errors = validate_report(payload)
            if report_errors:
                print(json.dumps({"status": "invalid", "errors": report_errors}, ensure_ascii=False))
                return 2
            print(json.dumps({"status": "verified", "report": args.verify_report, "intake_status": payload["status"]}, ensure_ascii=False))
            return 0
        receipts = _parse_bindings(args.training_receipt, label="training-receipt") if args.training_receipt else dict(DEFAULT_RECEIPTS)
        statuses = _parse_bindings(args.seed_status, label="seed-status") if args.seed_status else {}
        report = build_report(args.manifest, receipts, root=args.root, seed_statuses=statuses)
        output = write_report(report, args.output, root=args.root)
        markdown_path = _resolve_input_path(Path(args.root), args.markdown_output, "markdown_output")
        if markdown_path.suffix.lower() != ".md" or markdown_path.exists():
            _fail("markdown_output must be a new .md path")
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
        report_errors = validate_report(report)
        print(json.dumps({"status": report["status"], "source_bound": report["source_bound"], "output": str(output), "report_errors": report_errors}, ensure_ascii=False))
        return 0 if report["status"] == "diagnostic_bound" and not report_errors else 2
    except (IntakeError, OSError, ValueError) as error:
        print(json.dumps({"status": "blocked_fail_closed", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
