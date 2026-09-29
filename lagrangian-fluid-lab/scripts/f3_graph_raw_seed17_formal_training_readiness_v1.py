#!/usr/bin/env python3
"""Bounded, read-only readiness audit for the next Core training unit.

The unit under review is ``graph_raw-seed17`` from Core's fixed 9-run formal
training denominator.  This module only binds existing JSON contracts,
manifests, scheduler specifications, terminal reports, and PLAN text.  It
never imports the trainer, reads HDF5/checkpoints, starts a process, touches a
GPU/queue/worker, or writes registry/ledger/denominator/gate/completion state.

The current workspace is expected to remain blocked: diagnostic/preprofile
artifacts are not promoted to formal evidence, and a missing external trust
anchor must be reported rather than guessed.  The report is therefore an
observation, not an authorization or a job specification.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
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
RUN_ID = "graph_raw-seed17"
MODEL = "graph_raw"
SEED = 17
SCHEMA = "core.f3.graph_raw.seed17.formal_training_readiness.v1"
REPORT_ID = "f3-graph-raw-seed17-formal-training-readiness-v1"

FORMAL_UPDATES = 32000
FORMAL_HIDDEN = 64
FORMAL_MILESTONES = (8000, 16000, 24000, 32000)
REQUIRED_FORMAL_RUNS = 9
REQUIRED_T1_FAMILIES = 3
REQUIRED_VALIDATION_CASES = 12

MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_PLAN_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ARTIFACT_RELS: dict[str, str] = {
    "training_contract": "campaigns/core-v1/learning/training-contract-v1/contract.json",
    "training_planning_receipt": "campaigns/core-v1/learning/training-contract-v1/planning-receipt.json",
    "formal_source_closure": "campaigns/core-v1/learning/formal-source-closure-v7-20260929/source-closure.json",
    "formal_source_closure_receipt": "campaigns/core-v1/learning/formal-source-closure-v7-20260929/receipt.json",
    "formal_training_readiness": "campaigns/core-v1/learning/formal-training-admission-readiness-luna-max-20260920.json",
    "formal_readiness_audit": "campaigns/core-v1/learning/core-formal-readiness-audit-20260924-r002.json",
    "formal_admission_audit": "campaigns/core-v1/learning/core-formal-admission-audit-20260924-r002.json",
    "formal_launch_contract": "campaigns/core-v1/learning/core-formal-launch-contract-20260921.json",
    "current_dataset_manifest": "campaigns/core-v1/f3-dataset-v2.json",
    "registry": "campaigns/core-v1/registry.json",
    "completion": "campaigns/core-v1/completion.json",
    "diagnostic_training_evidence": "reports/F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN2.json",
    "diagnostic_terminal_bridge": "reports/F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-TERMINAL-EXECUTION-BRIDGE-2026-09-29.json",
    "diagnostic_rollout_contract": "reports/F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-FULL835-ROLLOUT-CONTRACT-2026-09-29.json",
}


class ReadinessError(ValueError):
    """Malformed or unsafe bounded input."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(root.resolve().parent).as_posix()
        except ValueError:
            return str(path.resolve())


def _reject_constant(token: str) -> None:
    raise ReadinessError(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReadinessError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _walk_json(value: Any, *, name: str = "value", depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ReadinessError(f"{name} exceeds maximum JSON depth")
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise ReadinessError(f"{name} contains an oversized string")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReadinessError(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReadinessError(f"{name} contains a non-string key")
            _walk_json(item, name=f"{name}.{key}", depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_ARRAY_ITEMS:
            raise ReadinessError(f"{name} contains too many array items")
        for index, item in enumerate(value):
            _walk_json(item, name=f"{name}[{index}]", depth=depth + 1)
        return
    raise ReadinessError(f"{name} contains unsupported type {type(value).__name__}")


def _regular_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read one bounded regular file without following a leaf symlink."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ReadinessError(f"cannot open {path}: {error}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReadinessError(f"{path} must be a single-link regular file")
        if before.st_size > max_bytes:
            raise ReadinessError(f"{path} exceeds bounded size {max_bytes}")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            block = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after = os.fstat(descriptor)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if before_identity != after_identity or total != before.st_size:
            raise ReadinessError(f"{path} changed during bounded read")
    except OSError as error:
        raise ReadinessError(f"cannot read {path}: {error}") from error
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if len(raw) > max_bytes:
        raise ReadinessError(f"{path} exceeds bounded size {max_bytes}")
    return raw


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return Path(os.path.normpath(str(path)))


def _ref(path: Path, root: Path, *, raw: bytes | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": _relative(path, root), "exists": path.is_file()}
    if raw is not None:
        result.update({"bytes": len(raw), "sha256": _sha256(raw)})
    return result


def _load_json(path: Path, root: Path) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    if not path.is_file():
        return None, _ref(path, root), f"missing input: {_relative(path, root)}"
    try:
        raw = _regular_bytes(path, max_bytes=MAX_JSON_BYTES)
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
        _walk_json(value, name=_relative(path, root))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ReadinessError, RecursionError) as error:
        return None, _ref(path, root), f"invalid bounded JSON {_relative(path, root)}: {error}"
    if not isinstance(value, dict):
        return None, _ref(path, root, raw=raw), f"JSON root is not an object: {_relative(path, root)}"
    reference = _ref(path, root, raw=raw)
    reference["schema"] = value.get("schema")
    return value, reference, None


def _load_text(path: Path, root: Path) -> tuple[str | None, dict[str, Any], str | None]:
    if not path.is_file():
        return None, _ref(path, root), f"missing input: {_relative(path, root)}"
    try:
        raw = _regular_bytes(path, max_bytes=MAX_PLAN_BYTES)
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError, ReadinessError) as error:
        return None, _ref(path, root), f"invalid bounded text {_relative(path, root)}: {error}"
    return text, _ref(path, root, raw=raw), None


def _artifact(root: Path, rel: str) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    return _load_json(_resolve(root, rel), root)


def _sha_file(path: Path) -> tuple[str | None, int | None, str | None]:
    try:
        raw = _regular_bytes(path, max_bytes=MAX_SOURCE_BYTES)
    except (OSError, ReadinessError) as error:
        return None, None, str(error)
    return _sha256(raw), len(raw), None


def _source_closure_observation(payload: Mapping[str, Any] | None, root: Path) -> dict[str, Any]:
    if payload is None:
        return {"schema_valid": False, "complete": False, "current_hashes_match": False, "files": []}
    rows = payload.get("files")
    if not isinstance(rows, list):
        rows = []
    observed: list[dict[str, Any]] = []
    mismatches: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            mismatches.append("<non-object source closure row>")
            continue
        raw_path = row.get("path") or row.get("relative_path")
        if not isinstance(raw_path, str) or not raw_path:
            mismatches.append("<source closure row without path>")
            continue
        path = _resolve(root, raw_path)
        observed_sha, observed_bytes, error = _sha_file(path)
        declared_sha = row.get("sha256")
        declared_bytes = row.get("bytes")
        matches = (
            error is None
            and observed_sha == declared_sha
            and observed_bytes == declared_bytes
        )
        item = {
            "relative_path": row.get("relative_path", _relative(path, root)),
            "declared_sha256": declared_sha,
            "observed_sha256": observed_sha,
            "declared_bytes": declared_bytes,
            "observed_bytes": observed_bytes,
            "matches": matches,
        }
        if error:
            item["error"] = error
        observed.append(item)
        if not matches:
            mismatches.append(str(item["relative_path"]))
    return {
        "schema_valid": payload.get("schema") == "core.formal_source_closure.v2",
        "complete": payload.get("complete") is True,
        "missing_files": payload.get("missing_files"),
        "formal_release": payload.get("formal_release"),
        "formal_training_ready": payload.get("formal_training_ready"),
        "root_admission_granted": payload.get("root_admission_granted"),
        "launch_allowed": payload.get("launch_allowed"),
        "closure_sha256": payload.get("closure_sha256"),
        "current_hashes_match": not mismatches,
        "mismatched_paths": mismatches,
        "files": observed,
    }


def _training_protocol(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    training = payload.get("training") if isinstance(payload, Mapping) else None
    training = training if isinstance(training, Mapping) else {}
    return {
        "model": MODEL,
        "seed": SEED,
        "run_id": RUN_ID,
        "hidden": training.get("hidden"),
        "updates": training.get("updates"),
        "milestones": training.get("milestones"),
        "centers_per_update": training.get("loss_centers"),
        "optimizer": training.get("optimizer"),
        "learning_rate": training.get("learning_rate"),
        "normalization_source_split": training.get("normalization_source_split"),
        "target_normalization": training.get("target_normalization"),
    }


def _source_binding_observation(payload: Mapping[str, Any] | None, root: Path) -> dict[str, Any]:
    closure = payload.get("source_closure") if isinstance(payload, Mapping) else None
    closure = closure if isinstance(closure, Mapping) else {}
    rows = closure.get("source_bindings")
    rows = rows if isinstance(rows, list) else []
    observed: list[dict[str, Any]] = []
    mismatches: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            mismatches.append("<invalid source binding>")
            continue
        path = _resolve(root, row["path"])
        sha, byte_count, error = _sha_file(path)
        match = error is None and sha == row.get("sha256") and byte_count == row.get("bytes")
        item = {
            "path": row["path"],
            "declared_sha256": row.get("sha256"),
            "observed_sha256": sha,
            "declared_bytes": row.get("bytes"),
            "observed_bytes": byte_count,
            "matches": match,
        }
        if error:
            item["error"] = error
        observed.append(item)
        if not match:
            mismatches.append(row["path"])
    return {
        "declared_count": len(rows),
        "current_hashes_match": not mismatches,
        "mismatched_paths": mismatches,
        "bindings": observed,
    }


def _manifest_observation(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    cases = payload.get("cases") if isinstance(payload, Mapping) else None
    cases = cases if isinstance(cases, list) else []
    families = sorted({row.get("family") for row in cases if isinstance(row, Mapping) and isinstance(row.get("family"), str)})
    validation_counts: dict[str, int] = {}
    for row in cases:
        if not isinstance(row, Mapping) or row.get("split") != "validation":
            continue
        family = row.get("family")
        if isinstance(family, str):
            validation_counts[family] = validation_counts.get(family, 0) + 1
    return {
        "schema": payload.get("schema") if isinstance(payload, Mapping) else None,
        "case_count": payload.get("case_count") if isinstance(payload, Mapping) else None,
        "formal_release": payload.get("formal_release") if isinstance(payload, Mapping) else None,
        "source_manifest_sha256": payload.get("source_manifest_sha256") if isinstance(payload, Mapping) else None,
        "families": families,
        "family_count": len(families),
        "validation_counts": dict(sorted(validation_counts.items())),
        "validation_case_count": sum(validation_counts.values()),
    }


def _admission_observation(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"schema": None, "status": "missing", "formal_admission": False, "formal_job_count": 0, "blocker_codes": []}
    blockers = payload.get("active_blockers")
    if not isinstance(blockers, list):
        blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        blockers = []
    codes = [row.get("code") for row in blockers if isinstance(row, Mapping) and isinstance(row.get("code"), str)]
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "formal_admission": payload.get("formal_admission") is True,
        "formal_training": payload.get("formal_training") is True,
        "formal_job_count": payload.get("formal_job_count"),
        "required_formal_job_count": payload.get("required_formal_job_count"),
        "blocker_codes": sorted(set(codes)),
    }


def _launch_contract_observation(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {
            "schema": None,
            "status": "missing",
            "formal_release": False,
            "formal_job_count": 0,
            "required_formal_job_count": REQUIRED_FORMAL_RUNS,
            "launch_allowed": False,
            "formal_training": False,
            "blockers": [],
        }
    blockers = payload.get("blockers")
    blockers = blockers if isinstance(blockers, list) else []
    return {
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "formal_release": payload.get("formal_release") is True,
        "formal_job_count": payload.get("formal_job_count"),
        "required_formal_job_count": payload.get("required_formal_job_count"),
        "launch_allowed": payload.get("launch_allowed") is True,
        "formal_training": payload.get("formal_training") is True,
        "blockers": [str(value) for value in blockers if isinstance(value, str)],
    }


def _scheduler_observation(root: Path) -> tuple[dict[str, Any], list[str]]:
    directory = root / "campaigns/core-v1/runtime/specs"
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    if not directory.is_dir():
        return {"directory": _relative(directory, root), "matching_specs": [], "formal_spec_present": False}, [
            f"missing scheduler specs directory: {_relative(directory, root)}"
        ]
    for path in sorted(directory.glob("*.json")):
        payload, reference, error = _load_json(path, root)
        if error:
            errors.append(error)
            continue
        assert payload is not None
        protocol = payload.get("training_protocol")
        protocol = protocol if isinstance(protocol, Mapping) else {}
        job_id = payload.get("job_id")
        model = protocol.get("model_kind", payload.get("model_kind"))
        seed = protocol.get("seed", payload.get("seed"))
        run_id = protocol.get("run_id", payload.get("run_id"))
        target_match = (
            model == MODEL
            and (seed == SEED or run_id == RUN_ID or (isinstance(job_id, str) and RUN_ID in job_id))
        )
        if not target_match:
            continue
        records.append({
            "job_id": job_id,
            "category": payload.get("category"),
            "run_id": run_id,
            "model": model,
            "seed": seed,
            "formal_training": payload.get("formal_training"),
            "formal_admission": payload.get("formal_admission"),
            "formal_job_count": payload.get("formal_job_count"),
            "manifest_formal_release": payload.get("manifest_formal_release"),
            "launch_allowed": payload.get("launch_allowed"),
            "outputs_are_not_formal_evidence": payload.get("outputs_are_not_formal_evidence"),
            "spec": reference,
        })
    formal_specs = [
        row for row in records
        if row.get("run_id") == RUN_ID
        and row.get("formal_training") is True
        and row.get("formal_admission") is True
        and row.get("formal_job_count") == 1
        and row.get("launch_allowed") is True
    ]
    return {
        "directory": _relative(directory, root),
        "matching_spec_count": len(records),
        "matching_specs": records,
        "formal_spec_present": bool(formal_specs),
        "formal_spec_count": len(formal_specs),
        "scan_errors": errors,
    }, errors


def _terminal_observation(artifacts: Mapping[str, Any], payloads: Mapping[str, Mapping[str, Any] | None]) -> dict[str, Any]:
    names = ("diagnostic_training_evidence", "diagnostic_terminal_bridge", "diagnostic_rollout_contract")
    rows: list[dict[str, Any]] = []
    for name in names:
        payload = payloads.get(name)
        if not isinstance(payload, Mapping):
            rows.append({"artifact": name, "status": "missing", "formal": False, "credit": 0})
            continue
        rows.append({
            "artifact": name,
            "schema": payload.get("schema"),
            "status": payload.get("status"),
            "formal": payload.get("formal") is True,
            "formal_training": payload.get("formal_training") is True,
            "formal_admission": payload.get("formal_admission") is True,
            "launch_allowed": payload.get("launch_allowed") is True,
            "credit": payload.get("credit"),
            "reference": artifacts.get(name),
        })
    return {
        "contracts": rows,
        "formal_terminal_evidence_present": any(
            row.get("formal") is True
            and row.get("formal_training") is True
            and row.get("formal_admission") is True
            and row.get("launch_allowed") is True
            and row.get("credit") != 0
            for row in rows
        ),
    }


def _add_blocker(blockers: list[dict[str, Any]], code: str, message: str, evidence: Any) -> None:
    if any(row.get("code") == code for row in blockers):
        return
    blockers.append({"code": code, "message": message, "evidence": evidence})


def build_report(*, root: str | Path = LAB_ROOT, observed_at_utc: str | None = None) -> dict[str, Any]:
    root = Path(root).expanduser().resolve()
    artifacts: dict[str, dict[str, Any]] = {}
    payloads: dict[str, dict[str, Any] | None] = {}
    input_errors: list[str] = []
    for name, rel in ARTIFACT_RELS.items():
        payload, reference, error = _artifact(root, rel)
        artifacts[name] = reference
        payloads[name] = payload
        if error:
            input_errors.append(error)

    plan_path = root.parent / "PLAN.md"
    plan_text, plan_reference, plan_error = _load_text(plan_path, root)
    artifacts["plan"] = plan_reference
    if plan_error:
        input_errors.append(plan_error)
    plan_lower = plan_text.lower() if plan_text is not None else ""
    plan_observation = {
        "formal_training_zero_nine_marker": bool(
            re.search(r"(?:formal training|正式训练|训练)[^\n]{0,80}0/9", plan_lower)
        ),
        "target_run_marker": (
            RUN_ID in (plan_text or "")
            or ("graph_raw" in plan_lower and bool(re.search(r"seed\s*17", plan_lower)))
        ),
        "trust_anchor_marker": "trust anchor" in plan_lower,
    }

    source_closure = _source_closure_observation(payloads.get("formal_source_closure"), root)
    training_protocol = _training_protocol(payloads.get("training_contract"))
    training_source_binding = _source_binding_observation(payloads.get("training_contract"), root)
    manifest = _manifest_observation(payloads.get("current_dataset_manifest"))
    admission = _admission_observation(payloads.get("formal_admission_audit"))
    readiness = _admission_observation(payloads.get("formal_training_readiness"))
    launch_contract = _launch_contract_observation(payloads.get("formal_launch_contract"))
    scheduler, scheduler_errors = _scheduler_observation(root)
    terminal = _terminal_observation(artifacts, payloads)

    registry = payloads.get("registry") or {}
    training_runs = registry.get("training_runs") if isinstance(registry, Mapping) else None
    training_runs = training_runs if isinstance(training_runs, list) else []
    completion = payloads.get("completion") or {}
    blockers: list[dict[str, Any]] = []

    if manifest.get("formal_release") is not True:
        _add_blocker(blockers, "CURRENT_DATASET_NOT_FORMAL_RELEASE", "current dataset manifest is not admitted as a formal source manifest", {"formal_release": manifest.get("formal_release"), "artifact": artifacts.get("current_dataset_manifest")})
    if manifest.get("family_count", 0) < REQUIRED_T1_FAMILIES:
        _add_blocker(blockers, "T1_FAMILY_DENOMINATOR_OPEN", "formal admission still has fewer than three distinct T1 families", {"observed": manifest.get("families"), "required": REQUIRED_T1_FAMILIES})
    if manifest.get("validation_case_count", 0) < REQUIRED_VALIDATION_CASES:
        _add_blocker(blockers, "VALIDATION_DENOMINATOR_OPEN", "formal admission still has fewer than twelve validation cases", {"observed": manifest.get("validation_case_count"), "required": REQUIRED_VALIDATION_CASES})
    if not source_closure.get("schema_valid") or not source_closure.get("complete") or not source_closure.get("current_hashes_match"):
        _add_blocker(blockers, "CURRENT_SOURCE_CLOSURE_NOT_VERIFIED", "current source closure is not a complete, byte-matching closure", source_closure)
    if source_closure.get("root_admission_granted") is not True:
        _add_blocker(blockers, "FORMAL_ROOT_TRUST_ANCHOR_MISSING", "the current closure does not carry a trusted root admission", {"root_admission_granted": source_closure.get("root_admission_granted"), "launch_allowed": source_closure.get("launch_allowed")})
    if not training_source_binding.get("current_hashes_match"):
        _add_blocker(blockers, "TRAINING_CONTRACT_SOURCE_BINDINGS_STALE", "planning training contract source bindings do not match the live workspace", training_source_binding.get("mismatched_paths"))
    if payloads.get("formal_admission") is None or not admission.get("formal_admission"):
        _add_blocker(blockers, "FORMAL_ADMISSION_BLOCKED", "formal admission audit is blocked and emits no formal jobs", admission)
    if payloads.get("formal_training_readiness") is None or not readiness.get("formal_training"):
        _add_blocker(blockers, "FORMAL_TRAINING_READINESS_BLOCKED", "formal training readiness is blocked", readiness)
    if not launch_contract.get("launch_allowed"):
        _add_blocker(blockers, "FORMAL_LAUNCH_CONTRACT_BLOCKED", "formal launch contract remains proposal-only and does not authorize a job", launch_contract)
    if not scheduler.get("formal_spec_present"):
        _add_blocker(blockers, "FORMAL_SCHEDULER_SPEC_MISSING", "no current scheduler spec authorizes graph_raw-seed17 as a formal run", {"matching_spec_count": scheduler.get("matching_spec_count"), "formal_spec_count": scheduler.get("formal_spec_count")})
    if not terminal.get("formal_terminal_evidence_present"):
        _add_blocker(blockers, "FORMAL_TERMINAL_CONTRACT_MISSING", "existing graph_raw-seed17 terminal contracts are diagnostic/proposal-only and provide no formal terminal evidence", terminal)
    if RUN_ID not in [str(row) for row in training_runs]:
        _add_blocker(blockers, "FORMAL_RUN_NOT_OBSERVED", "registry contains no formal terminal record for graph_raw-seed17", {"training_runs_count": len(training_runs), "target_run": RUN_ID})
    for code in sorted(set(admission.get("blocker_codes", []) + readiness.get("blocker_codes", []))):
        if code in {"RESOURCE_FRONTIER_UNPROVEN", "RESOURCE_CAPACITY_EVIDENCE_INVALID", "FORMAL_RELEASE_REQUIRED", "ROOT_ADMISSION_REQUIRED", "LAUNCH_CONTRACT_BLOCKED", "FORMAL_READINESS_BLOCKED", "FORMAL_RUN_DENOMINATOR"}:
            _add_blocker(blockers, f"UPSTREAM_{code}", "upstream formal admission reports this blocker", {"code": code})
    if input_errors:
        _add_blocker(blockers, "BOUNDED_INPUT_ERROR", "one or more audited inputs could not be read safely", input_errors)
    if not plan_observation["formal_training_zero_nine_marker"] or not plan_observation["target_run_marker"]:
        _add_blocker(blockers, "PLAN_SCOPE_NOT_VERIFIABLE", "PLAN does not expose the expected formal-training target markers", plan_observation)

    blockers.sort(key=lambda row: row["code"])
    formal_protocol = {
        "model": MODEL,
        "seed": SEED,
        "run_id": RUN_ID,
        "updates": FORMAL_UPDATES,
        "hidden": FORMAL_HIDDEN,
        "milestones": list(FORMAL_MILESTONES),
        "required_formal_runs": REQUIRED_FORMAL_RUNS,
        "training_contract_observed": training_protocol,
        "training_contract_matches_formal_target": (
            training_protocol.get("model") == MODEL
            and training_protocol.get("seed") == SEED
            and training_protocol.get("hidden") == FORMAL_HIDDEN
            and training_protocol.get("updates") == FORMAL_UPDATES
            and training_protocol.get("milestones") == list(FORMAL_MILESTONES)
        ),
    }
    return {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "blocked_fail_closed" if blockers else "ready_to_bind_only",
        "scope": {
            "family": "F3",
            "model": MODEL,
            "seed": SEED,
            "run_id": RUN_ID,
            "purpose": "next formal training evidence-chain minimum executable unit",
        },
        "formal_protocol": formal_protocol,
        "artifacts": artifacts,
        "current_source_closure": source_closure,
        "current_dataset_manifest": manifest,
        "training_contract_source_bindings": training_source_binding,
        "formal_readiness": readiness,
        "formal_admission": admission,
        "formal_launch_contract": launch_contract,
        "scheduler": scheduler,
        "terminal": terminal,
        "plan": {"reference": artifacts.get("plan"), "markers": plan_observation},
        "registry_observation": {
            "training_runs_count": len(training_runs),
            "target_run_present": RUN_ID in [str(row) for row in training_runs],
            "completion_can_finalize": completion.get("can_finalize"),
        },
        "blockers": blockers,
        "decision": {
            "inputs_closed": not blockers,
            "formal_training_ready": False,
            "spec_created": False,
            "launch_allowed": False,
            "reason": "external formal trust anchor and upstream Core admission gates are not closed",
        },
        "zero_credit": {
            "formal": False,
            "formal_training": False,
            "T1_numerical": False,
            "T2_macro": False,
            "credit": 0,
        },
        "side_effects": {
            "trainer_imported": False,
            "optimizer_started": False,
            "process_started": False,
            "gpu_started": False,
            "queue_submitted": False,
            "worker_started": False,
            "registry_written": False,
            "ledger_written": False,
            "denominator_written": False,
            "gate_written": False,
            "completion_written": False,
            "plan_written": False,
            "update_409_written": False,
        },
        "input_boundary": {
            "bounded_json_inputs_only": True,
            "bounded_source_files_only": True,
            "plan_read_only": True,
            "checkpoint_opened": False,
            "hdf5_opened": False,
            "trajectory_opened": False,
            "progress_opened": False,
        },
        "scan_errors": scheduler_errors,
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema drift")
    scope = report.get("scope")
    if not isinstance(scope, Mapping) or scope.get("model") != MODEL or scope.get("seed") != SEED or scope.get("run_id") != RUN_ID:
        errors.append("scope identity drift")
    decision = report.get("decision")
    if not isinstance(decision, Mapping):
        errors.append("decision missing")
    else:
        for key in ("formal_training_ready", "spec_created", "launch_allowed", "inputs_closed"):
            if decision.get(key) is not False:
                errors.append(f"decision.{key} must remain false")
    zero_credit = report.get("zero_credit")
    if not isinstance(zero_credit, Mapping) or zero_credit.get("credit") != 0 or zero_credit.get("formal") is not False:
        errors.append("zero-credit authority drift")
    effects = report.get("side_effects")
    if not isinstance(effects, Mapping):
        errors.append("side effects missing")
    else:
        for key in ("trainer_imported", "optimizer_started", "process_started", "gpu_started", "queue_submitted", "worker_started", "registry_written", "ledger_written", "denominator_written", "gate_written", "completion_written", "plan_written", "update_409_written"):
            if effects.get(key) is not False:
                errors.append(f"side_effects.{key} must remain false")
    blockers = report.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        errors.append("blocked report must retain explicit blockers")
    return errors


def write_report(report: Mapping[str, Any], path: str | Path) -> Path:
    errors = validate_report(report)
    if errors:
        raise ReadinessError("refusing to write invalid report: " + "; ".join(errors))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError as error:
        raise ReadinessError(f"refuses overwrite: {path}") from error
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=LAB_ROOT / "reports/F3-GRAPH-RAW-SEED17-FORMAL-TRAINING-READINESS-2026-09-29.json",
    )
    args = parser.parse_args()
    report = build_report(root=args.root)
    write_report(report, args.output)
    print(json.dumps({"status": report["status"], "blocker_count": len(report["blockers"]), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
