#!/usr/bin/env python3
"""Plan a bounded, diagnostic-only F3 MLP hidden16 campaign.

This is a read-only scheduling boundary.  It opens only the explicitly
provided manifest JSON and training-identity JSON.  HDF5 inputs, checkpoints,
the solver, workers, GPU state, registries, ledgers, gates, and PLAN are not
opened or touched.  The resulting schedule is a dry-run plan: it contains 32
cases x seeds 17/29/43, split into seed-isolated batches of at most eight
cases, with fresh output namespaces and GPU-slot hints for a future executor.

The schedule is permanently diagnostic-only and zero-credit.  It is not a
terminal receipt and it does not authorize execution.
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
EXPECTED_CASE_COUNT = 32
MAX_BATCH_SIZE = 8
GPU_COUNT = 8
DEFAULT_OUTPUT_BYTES_PER_CASE = 1024 * 1024 * 1024
MAX_OUTPUT_BYTES_PER_CASE = 64 * 1024 * 1024 * 1024

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_TRAINING_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096

MANIFEST_SCHEMA = "core.dataset.v2"
TRAINING_SCHEMA = "core.f3.mlp.hidden16.current_manifest_training_evidence.v1"
SCHEMA = "core.f3.mlp.hidden16.current_manifest.bounded_campaign_schedule.v1"
REPORT_ID = "f3-mlp-hidden16-current-manifest-bounded-campaign-schedule-v1"
CASE_ID_RE = re.compile(r"^F3_DEV_[0-9]{2}_[A-Za-z0-9p]+$")
RUN_ID_RE = re.compile(
    r"^f3-mlp500-hidden16-currentmanifest-seed(?P<seed>17|29|43)-20[0-9]{6}$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
DATE_RE = re.compile(r"^20[0-9]{6}$")

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


class ScheduleError(ValueError):
    """Malformed, drifting, duplicated, or path-conflicting input."""


def _fail(message: str) -> None:
    raise ScheduleError(f"fail-closed: {message}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str, minimum: int = 0) -> int:
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
    if len(raw) > 1 and raw.endswith(os.sep):
        _fail(f"{name} must not have a trailing separator")
    candidate = Path(raw)
    if not candidate.is_absolute():
        _fail(f"{name} must be absolute")
    normalized = os.path.normpath(str(candidate))
    if str(candidate) != normalized:
        _fail(f"{name} uses a lexical path alias")
    if any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} contains a lexical path alias")
    return Path(normalized)


def _reject_symlink_components(path: Path, name: str) -> None:
    current = Path(path.anchor or "/")
    for part in path.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as error:
            _fail(f"cannot inspect {name}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component")


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size)


def _read_bounded_json(
    path: Path | str,
    *,
    name: str,
    max_bytes: int,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Read one regular JSON source with identity checks around the read."""

    candidate = _absolute_path(path, name)
    _reject_symlink_components(candidate, name)
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
        descriptor = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    chunks: list[bytes] = []
    try:
        opened = os.fstat(descriptor)
        expected = _file_identity(before)
        if _file_identity(opened) != expected:
            _fail(f"{name} changed before bounded read")
        total = 0
        while total <= max_bytes:
            block = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        closed = os.fstat(descriptor)
        if _file_identity(closed) != expected or total != before.st_size:
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(descriptor)
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
    except (UnicodeError, json.JSONDecodeError, ScheduleError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    payload = _mapping(payload, name)
    _walk_json(payload, name)
    return payload, {
        "path": str(candidate),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _canonical_sha(value: Any) -> str:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        _fail(f"value cannot be canonically hashed: {error}")
    return hashlib.sha256(raw).hexdigest()


def _zero_credit(value: Mapping[str, Any], name: str, *, require_diagnostic: bool = True) -> None:
    if require_diagnostic:
        _exact(value, "diagnostic_only", True, name)
    elif "diagnostic_only" in value:
        _exact(value, "diagnostic_only", True, name)
    for key, expected in ZERO_CREDIT.items():
        if key in {"diagnostic_only", "formal_eligible"}:
            continue
        if key in value:
            _exact(value, key, expected, name)


def _validate_identity_record(value: Mapping[str, Any], name: str, *, update: int | None = None) -> dict[str, Any]:
    path = _absolute_path(value.get("path"), f"{name}.path")
    result = {
        "path": str(path),
        "bytes": _integer(value.get("bytes"), f"{name}.bytes", 1),
        "sha256": _sha(value.get("sha256"), f"{name}.sha256"),
    }
    if update is not None:
        _exact(value, "update", update, name)
        result["update"] = update
    return result


def _validate_manifest(
    payload: Mapping[str, Any], *, source: Mapping[str, Any], path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _exact(payload, "schema", MANIFEST_SCHEMA, "manifest")
    _exact(payload, "case_count", EXPECTED_CASE_COUNT, "manifest")
    _exact(payload, "formal_release", False, "manifest")
    for key in ("formal", "formal_eligible"):
        if payload.get(key) is True:
            _fail(f"formal manifest field {key}=true is not accepted")
    if not _string(payload.get("dataset_id"), "manifest.dataset_id").startswith("F3_"):
        _fail("manifest.dataset_id is not an F3 dataset")
    _sha(payload.get("source_manifest_sha256"), "manifest.source_manifest_sha256")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != EXPECTED_CASE_COUNT:
        _fail("manifest must contain exactly 32 cases")
    cases: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    seen_physical_ids: set[str] = set()
    seen_hdf5: set[str] = set()
    seen_case_sha: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        case = _mapping(raw_case, f"manifest.cases[{index}]")
        name = f"manifest.cases[{index}]"
        case_id = _string(case.get("case_id"), f"{name}.case_id")
        if CASE_ID_RE.fullmatch(case_id) is None:
            _fail(f"{name}.case_id is invalid")
        physical_case_id = _string(case.get("physical_case_id"), f"{name}.physical_case_id")
        if physical_case_id != case_id:
            _fail(f"{name}.physical_case_id is not bound to case_id")
        if case_id in seen_case_ids or physical_case_id in seen_physical_ids:
            _fail("manifest contains duplicate case identity")
        seen_case_ids.add(case_id)
        seen_physical_ids.add(physical_case_id)
        _exact(case, "family", "F3", name)
        split = _string(case.get("split"), f"{name}.split")
        if split not in {"train", "validation", "test"}:
            _fail(f"{name}.split is invalid")
        hdf5 = _string(case.get("hdf5"), f"{name}.hdf5")
        relative = Path(hdf5)
        if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
            _fail(f"{name}.hdf5 must be a relative alias-free path")
        if hdf5 in seen_hdf5:
            _fail("manifest contains a duplicate HDF5 metadata path conflict")
        seen_hdf5.add(hdf5)
        case_sha = _sha(case.get("sha256"), f"{name}.sha256")
        if case_sha in seen_case_sha:
            _fail("manifest contains a duplicate case artifact identity")
        seen_case_sha.add(case_sha)
        _exact(case, "qualification_case", False, name)
        cases.append(
            {
                "index": index,
                "case_id": case_id,
                "physical_case_id": physical_case_id,
                "family": "F3",
                "split": split,
                "evaluation_role": _string(case.get("evaluation_role"), f"{name}.evaluation_role"),
                "hdf5": hdf5,
                "hdf5_bytes": _integer(case.get("bytes"), f"{name}.bytes", 1),
                "hdf5_sha256": case_sha,
                "known_inputs_sha256": _sha(
                    case.get("known_inputs_sha256"), f"{name}.known_inputs_sha256"
                ),
                "lineage_group_id": _sha(
                    case.get("lineage_group_id"), f"{name}.lineage_group_id"
                ),
                "scope_id": _string(case.get("scope_id"), f"{name}.scope_id"),
            }
        )
    return cases, {
        "schema": MANIFEST_SCHEMA,
        "dataset_id": payload["dataset_id"],
        "case_count": EXPECTED_CASE_COUNT,
        "formal_release": False,
        "source": dict(source),
        "canonical_sha256": _canonical_sha(payload),
        "path": str(path),
    }


def _validate_training(
    payload: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _exact(payload, "schema", TRAINING_SCHEMA, "training_identity")
    _exact(payload, "report_id", "f3-mlp-hidden16-current-manifest-training-evidence-v1", "training_identity")
    _exact(payload, "status", "diagnostic_bound", "training_identity")
    _exact(payload, "source_bound", True, "training_identity")
    _exact(payload, "fail_closed", False, "training_identity")
    _exact(payload, "model", MODEL, "training_identity")
    _exact(payload, "hidden", HIDDEN, "training_identity")
    _exact(payload, "updates", UPDATES, "training_identity")
    _exact(payload, "errors", [], "training_identity")
    _zero_credit(payload, "training_identity")
    for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
        _exact(payload, key, False, "training_identity")
    for key in ("credit", "qualification_credit", "formal_training_runs_counted", "t1_case_runs_counted", "t2_macro_families_counted"):
        _exact(payload, key, 0, "training_identity")

    manifest_binding = _mapping(payload.get("manifest"), "training_identity.manifest")
    _exact(manifest_binding, "path", manifest["path"], "training_identity.manifest")
    _exact(manifest_binding, "sha256", manifest["source"]["sha256"], "training_identity.manifest")
    _exact(manifest_binding, "bytes", manifest["source"]["bytes"], "training_identity.manifest")
    _exact(manifest_binding, "canonical_sha256", manifest["canonical_sha256"], "training_identity.manifest")
    _exact(manifest_binding, "opened", True, "training_identity.manifest")

    runs_value = payload.get("runs")
    if not isinstance(runs_value, list) or len(runs_value) != len(SEEDS):
        _fail("training_identity.runs must contain exactly three seed identities")
    runs: list[dict[str, Any]] = []
    seen_seeds: set[int] = set()
    seen_run_ids: set[str] = set()
    seen_receipt_paths: set[str] = set()
    seen_receipt_hashes: set[str] = set()
    seen_checkpoint_paths: set[str] = set()
    seen_checkpoint_hashes: set[str] = set()
    for index, raw_run in enumerate(runs_value):
        run = _mapping(raw_run, f"training_identity.runs[{index}]")
        name = f"training_identity.runs[{index}]"
        seed = _integer(run.get("seed"), f"{name}.seed")
        if seed not in SEEDS or seed in seen_seeds:
            _fail("training identity contains duplicate or unexpected seed")
        seen_seeds.add(seed)
        _exact(run, "status", "bound", name)
        source_record = _mapping(run.get("source"), f"{name}.source")
        source_identity = _validate_identity_record(source_record, f"{name}.source")
        _exact(source_record, "schema", "core.training.v1", f"{name}.source")
        _exact(source_record, "opened", True, f"{name}.source")
        evidence = _mapping(run.get("evidence"), f"{name}.evidence")
        _exact(evidence, "schema", "core.training.v1", f"{name}.evidence")
        _exact(evidence, "model", MODEL, f"{name}.evidence")
        _exact(evidence, "hidden", HIDDEN, f"{name}.evidence")
        _exact(evidence, "updates", UPDATES, f"{name}.evidence")
        _exact(evidence, "seed", seed, f"{name}.evidence")
        _exact(evidence, "completed", True, f"{name}.evidence")
        _exact(evidence, "manifest_sha256", manifest["canonical_sha256"], f"{name}.evidence")
        _zero_credit(_mapping(evidence.get("zero_credit"), f"{name}.evidence.zero_credit"), f"{name}.evidence.zero_credit")
        run_id = _string(evidence.get("run_id"), f"{name}.evidence.run_id")
        match = RUN_ID_RE.fullmatch(run_id)
        if match is None or int(match.group("seed")) != seed:
            _fail(f"{name}.evidence.run_id is not bound to seed {seed}")
        if run_id in seen_run_ids:
            _fail("training identity contains duplicate run_id")
        seen_run_ids.add(run_id)
        checkpoint_record = _mapping(evidence.get("checkpoint_identity"), f"{name}.evidence.checkpoint_identity")
        checkpoint = _validate_identity_record(checkpoint_record, f"{name}.evidence.checkpoint_identity", update=UPDATES)
        _exact(checkpoint_record, "schema", "core.checkpoint.v1", f"{name}.evidence.checkpoint_identity")
        receipt_record = _mapping(evidence.get("receipt_identity"), f"{name}.evidence.receipt_identity")
        receipt = _validate_identity_record(receipt_record, f"{name}.evidence.receipt_identity")
        if source_identity != receipt:
            _fail(f"{name} source and receipt identities drift")
        if receipt["path"] in seen_receipt_paths or receipt["sha256"] in seen_receipt_hashes:
            _fail("training identity contains duplicate receipt path or digest")
        if checkpoint["path"] in seen_checkpoint_paths or checkpoint["sha256"] in seen_checkpoint_hashes:
            _fail("training identity contains duplicate checkpoint path or digest")
        if checkpoint["path"] == receipt["path"]:
            _fail(f"{name} checkpoint and receipt paths conflict")
        seen_receipt_paths.add(receipt["path"])
        seen_receipt_hashes.add(receipt["sha256"])
        seen_checkpoint_paths.add(checkpoint["path"])
        seen_checkpoint_hashes.add(checkpoint["sha256"])
        runs.append(
            {
                "seed": seed,
                "run_id": run_id,
                "training_receipt": receipt,
                "checkpoint": checkpoint,
            }
        )
    if tuple(sorted(seen_seeds)) != SEEDS:
        _fail("training identity must cover exactly seeds 17, 29, and 43")
    return sorted(runs, key=lambda item: item["seed"]), {
        "schema": TRAINING_SCHEMA,
        "report_id": payload["report_id"],
        "source": dict(source),
        "status": payload["status"],
        "source_bound": True,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seeds": list(SEEDS),
        "runs": runs,
    }


def _validate_id(value: str, name: str) -> str:
    if ID_RE.fullmatch(value) is None:
        _fail(f"{name} is not a safe identifier")
    return value


def _validate_date(value: str) -> str:
    if DATE_RE.fullmatch(value) is None:
        _fail("plan_date must use YYYYMMDD")
    return value


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    if not result:
        _fail("case identifier produced an empty slug")
    return result


def _nonce(*, campaign_id: str, manifest_sha256: str, case_id: str, seed: int, run_id: str) -> str:
    raw = f"{SCHEMA}|{campaign_id}|{manifest_sha256}|{case_id}|{seed}|{run_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def _path_conflicts(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _gib(byte_count: int) -> float:
    return round(byte_count / (1024**3), 3)


def _check_output_root(output_root: Path) -> None:
    _reject_symlink_components(output_root, "output_root")
    if os.path.lexists(output_root) and not output_root.is_dir():
        _fail("output_root exists but is not a directory")


def _assert_fresh_planned_paths(
    *,
    output_root: Path,
    manifest_path: Path,
    training_path: Path,
    batches: Sequence[Mapping[str, Any]],
) -> None:
    planned: list[Path] = [manifest_path, training_path]
    for batch in batches:
        planned.append(Path(str(batch["output_report"])))
        planned.append(Path(str(batch["markdown_report"])))
        for job in batch["jobs"]:
            planned.append(Path(str(job["output_namespace"])))
    seen: set[str] = set()
    for path in planned[2:]:
        if str(path) in seen:
            _fail("planned output paths are not unique")
        seen.add(str(path))
        if os.path.lexists(path):
            _fail(f"planned output path already exists: {path}")
        if _path_conflicts(path, manifest_path) or _path_conflicts(path, training_path):
            _fail(f"planned output path conflicts with an input identity: {path}")
    for index, first in enumerate(planned[2:]):
        for second in planned[2 : index + 2]:
            if _path_conflicts(first, second):
                _fail(f"planned output path overlaps another namespace/report: {first}")
    if _path_conflicts(output_root, manifest_path) and output_root == manifest_path:
        _fail("output_root conflicts with manifest input")
    if _path_conflicts(output_root, training_path) and output_root == training_path:
        _fail("output_root conflicts with training identity input")


def _source_summary(manifest: Mapping[str, Any], training: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "manifest": {
            "path": manifest["path"],
            "bytes": manifest["source"]["bytes"],
            "sha256": manifest["source"]["sha256"],
            "canonical_sha256": manifest["canonical_sha256"],
            "schema": manifest["schema"],
            "case_count": manifest["case_count"],
            "formal_release": False,
        },
        "training_identity": {
            "path": training["source"]["path"],
            "bytes": training["source"]["bytes"],
            "sha256": training["source"]["sha256"],
            "schema": training["schema"],
            "status": training["status"],
            "seeds": list(SEEDS),
        },
    }


def build_schedule(
    *,
    manifest: Path | str,
    training_identity: Path | str,
    output_root: Path | str,
    campaign_id: str,
    plan_date: str,
    batch_size: int = MAX_BATCH_SIZE,
    estimated_output_bytes_per_case: int = DEFAULT_OUTPUT_BYTES_PER_CASE,
) -> dict[str, Any]:
    """Build a schedule without creating namespaces or starting any process."""

    campaign_id = _validate_id(campaign_id, "campaign_id")
    plan_date = _validate_date(plan_date)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
        _fail(f"batch_size must be an integer in [1, {MAX_BATCH_SIZE}]")
    if type(estimated_output_bytes_per_case) is not int or not 1 <= estimated_output_bytes_per_case <= MAX_OUTPUT_BYTES_PER_CASE:
        _fail("estimated_output_bytes_per_case is outside the bounded planning range")

    manifest_path = _absolute_path(manifest, "manifest")
    training_path = _absolute_path(training_identity, "training_identity")
    if manifest_path == training_path:
        _fail("manifest and training identity paths conflict")
    manifest_payload, manifest_source = _read_bounded_json(
        manifest_path, name="manifest", max_bytes=MAX_JSON_BYTES
    )
    cases, manifest_meta = _validate_manifest(
        manifest_payload, source=manifest_source, path=manifest_path
    )
    training_payload, training_source = _read_bounded_json(
        training_path, name="training_identity", max_bytes=MAX_TRAINING_BYTES
    )
    training_meta, training_summary = _validate_training(
        training_payload,
        source=training_source,
        manifest=manifest_meta,
    )
    output_root_path = _absolute_path(output_root, "output_root")
    _check_output_root(output_root_path)

    run_by_seed = {int(run["seed"]): run for run in training_meta}
    batches: list[dict[str, Any]] = []
    all_jobs: list[dict[str, Any]] = []
    batch_count_per_seed = (EXPECTED_CASE_COUNT + batch_size - 1) // batch_size
    for seed in SEEDS:
        run = run_by_seed[seed]
        for batch_index in range(batch_count_per_seed):
            start = batch_index * batch_size
            selected = cases[start : start + batch_size]
            if not selected:
                continue
            batch_id = f"{campaign_id}-seed{seed}-batch{batch_index:02d}"
            _validate_id(batch_id, "batch_id")
            batch_report = output_root_path / "batch-reports" / f"{batch_id}.json"
            markdown_report = output_root_path / "batch-reports" / f"{batch_id}.zh-CN.md"
            jobs: list[dict[str, Any]] = []
            for slot, case in enumerate(selected):
                case_id = str(case["case_id"])
                nonce = _nonce(
                    campaign_id=campaign_id,
                    manifest_sha256=str(manifest_meta["canonical_sha256"]),
                    case_id=case_id,
                    seed=seed,
                    run_id=str(run["run_id"]),
                )
                namespace = output_root_path / "namespaces" / (
                    f"{batch_id}-slot{slot:02d}-case{int(case['index']):02d}-"
                    f"{_slug(case_id)}-{nonce}"
                )
                job = {
                    "job_id": f"{batch_id}-slot{slot:02d}-case{int(case['index']):02d}",
                    "case_index": int(case["index"]),
                    "case_id": case_id,
                    "seed": seed,
                    "split": case["split"],
                    "gpu_slot": slot,
                    "gpu_index": slot,
                    "run_id": run["run_id"],
                    "training_receipt": dict(run["training_receipt"]),
                    "checkpoint_identity": dict(run["checkpoint"]),
                    "output_namespace": str(namespace),
                    "output_paths": {
                        "evaluation": str(namespace / "evaluation.json"),
                        "trajectory": str(namespace / "trajectory.h5"),
                        "progress": str(namespace / "progress.json"),
                        "terminal_receipt": str(namespace / "terminal-receipt.json"),
                        "process_proof": str(namespace / "process-exit-proof.json"),
                    },
                    "estimated_output_space_bytes": estimated_output_bytes_per_case,
                    "execution": {
                        "launch_allowed": False,
                        "executor": "f3_mlp_hidden16_current_manifest_diagnostic_batch_v1.py",
                        "mode": "schedule_only",
                        "diagnostic_only": True,
                        "formal": False,
                        "credit": 0,
                    },
                    **ZERO_CREDIT,
                }
                jobs.append(job)
                all_jobs.append(job)
            batches.append(
                {
                    "batch_id": batch_id,
                    "seed": seed,
                    "batch_index": batch_index,
                    "case_count": len(jobs),
                    "case_ids": [job["case_id"] for job in jobs],
                    "seed_isolated": True,
                    "gpu_slot_mapping": [
                        {
                            "case_id": job["case_id"],
                            "job_id": job["job_id"],
                            "gpu_slot": job["gpu_slot"],
                            "gpu_index": job["gpu_index"],
                        }
                        for job in jobs
                    ],
                    "output_report": str(batch_report),
                    "markdown_report": str(markdown_report),
                    "output_space": {
                        "estimated_bytes": len(jobs) * estimated_output_bytes_per_case,
                        "estimated_gib": _gib(len(jobs) * estimated_output_bytes_per_case),
                        "per_case_bytes": estimated_output_bytes_per_case,
                        "method": "fixed planning envelope; no HDF5 or checkpoint content opened",
                    },
                    "jobs": jobs,
                    **ZERO_CREDIT,
                }
            )

    _assert_fresh_planned_paths(
        output_root=output_root_path,
        manifest_path=manifest_path,
        training_path=training_path,
        batches=batches,
    )
    expected_pairs = {(case["case_id"], seed) for case in cases for seed in SEEDS}
    observed_pairs = {(job["case_id"], job["seed"]) for job in all_jobs}
    if observed_pairs != expected_pairs or len(all_jobs) != EXPECTED_CASE_COUNT * len(SEEDS):
        _fail("schedule does not cover exactly 32 cases x seeds 17, 29, 43")

    report = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "status": "dry_run_schedule_ready",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_bound": True,
        "campaign": {
            "campaign_id": campaign_id,
            "plan_date": plan_date,
            "model": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "batch_size_max": batch_size,
            "gpu_count": GPU_COUNT,
            "seed_independence": True,
            "launch_allowed": False,
        },
        "sources": _source_summary(manifest_meta, training_summary),
        "cases": cases,
        "batches": batches,
        "coverage": {
            "case_count": EXPECTED_CASE_COUNT,
            "seed_count": len(SEEDS),
            "seeds": list(SEEDS),
            "job_count": len(all_jobs),
            "batch_count": len(batches),
            "batch_count_per_seed": batch_count_per_seed,
            "max_cases_per_batch": max(len(batch["jobs"]) for batch in batches),
            "exact_case_seed_coverage": True,
            "duplicate_case_seed_pairs": 0,
            "mixed_seed_batches": 0,
            "unique_batch_ids": len({batch["batch_id"] for batch in batches}),
            "unique_batch_output_reports": len({batch["output_report"] for batch in batches}),
            "unique_output_namespaces": len({job["output_namespace"] for job in all_jobs}),
        },
        "output_space": {
            "estimated_bytes_per_case": estimated_output_bytes_per_case,
            "estimated_bytes_per_batch_max": batch_size * estimated_output_bytes_per_case,
            "estimated_bytes_total": len(all_jobs) * estimated_output_bytes_per_case,
            "estimated_gib_total": _gib(len(all_jobs) * estimated_output_bytes_per_case),
            "planned_output_root": str(output_root_path),
            "method": "fixed planning envelope; no HDF5 or checkpoint content opened",
        },
        "input_boundary": {
            "manifest_json_opened": True,
            "training_identity_json_opened": True,
            "hdf5_content_opened": False,
            "checkpoint_content_opened": False,
            "gpu_started": False,
            "solver_started": False,
            "worker_started": False,
            "registry_read": False,
            "ledger_read": False,
            "gate_read": False,
            "plan_read": False,
        },
        "side_effects": {
            "gpu_processes_started": 0,
            "solver_processes_started": 0,
            "worker_processes_started": 0,
            "existing_processes_stopped": 0,
            "existing_processes_restarted": 0,
            "formal_registry_writes": 0,
            "formal_ledger_writes": 0,
            "formal_gate_writes": 0,
            "plan_writes": 0,
        },
        **ZERO_CREDIT,
    }
    validate_report(report)
    return report


def validate_report(report: Mapping[str, Any]) -> None:
    _exact(report, "schema", SCHEMA, "report")
    _exact(report, "status", "dry_run_schedule_ready", "report")
    _exact(report, "source_bound", True, "report")
    _zero_credit(report, "report")
    campaign = _mapping(report.get("campaign"), "report.campaign")
    _exact(campaign, "seed_independence", True, "report.campaign")
    _exact(campaign, "launch_allowed", False, "report.campaign")
    _exact(campaign, "gpu_count", GPU_COUNT, "report.campaign")
    batch_size = _integer(campaign.get("batch_size_max"), "report.campaign.batch_size_max", 1)
    if batch_size > MAX_BATCH_SIZE:
        _fail("report batch size exceeds bounded maximum")
    sources = _mapping(report.get("sources"), "report.sources")
    manifest = _mapping(sources.get("manifest"), "report.sources.manifest")
    _exact(manifest, "case_count", EXPECTED_CASE_COUNT, "report.sources.manifest")
    _exact(manifest, "formal_release", False, "report.sources.manifest")
    _sha(manifest.get("sha256"), "report.sources.manifest.sha256")
    _sha(manifest.get("canonical_sha256"), "report.sources.manifest.canonical_sha256")
    training = _mapping(sources.get("training_identity"), "report.sources.training_identity")
    if tuple(training.get("seeds", ())) != SEEDS:
        _fail("report training identity seed set drifted")
    _sha(training.get("sha256"), "report.sources.training_identity.sha256")
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        _fail("report must contain exactly 32 cases")
    case_ids = [str(_mapping(case, "report.cases[]")["case_id"]) for case in cases]
    if len(set(case_ids)) != EXPECTED_CASE_COUNT:
        _fail("report case identities are not unique")
    batches = report.get("batches")
    if not isinstance(batches, list) or not batches:
        _fail("report must contain batches")
    pairs: set[tuple[str, int]] = set()
    batch_ids: set[str] = set()
    batch_reports: set[str] = set()
    namespaces: set[str] = set()
    for batch_index, raw_batch in enumerate(batches):
        batch = _mapping(raw_batch, f"report.batches[{batch_index}]")
        batch_id = _string(batch.get("batch_id"), f"report.batches[{batch_index}].batch_id")
        if batch_id in batch_ids:
            _fail("report batch IDs are not unique")
        batch_ids.add(batch_id)
        seed = _integer(batch.get("seed"), f"report.batches[{batch_index}].seed")
        if seed not in SEEDS:
            _fail("report batch has an unexpected seed")
        _exact(batch, "seed_isolated", True, f"report.batches[{batch_index}]")
        jobs = batch.get("jobs")
        if not isinstance(jobs, list) or not 1 <= len(jobs) <= batch_size:
            _fail("report batch has an invalid bounded job count")
        report_path = _absolute_path(batch.get("output_report"), f"report.batches[{batch_index}].output_report")
        if str(report_path) in batch_reports:
            _fail("report batch output reports are not unique")
        batch_reports.add(str(report_path))
        slots: set[int] = set()
        for job_index, raw_job in enumerate(jobs):
            job = _mapping(raw_job, f"report.batches[{batch_index}].jobs[{job_index}]")
            job_seed = _integer(job.get("seed"), "job.seed")
            if job_seed != seed:
                _fail("a batch mixes seed identities")
            case_id = _string(job.get("case_id"), "job.case_id")
            pair = (case_id, job_seed)
            if pair in pairs:
                _fail("report contains a duplicate case/seed pair")
            pairs.add(pair)
            slot = _integer(job.get("gpu_slot"), "job.gpu_slot")
            gpu = _integer(job.get("gpu_index"), "job.gpu_index")
            if slot != gpu or gpu >= GPU_COUNT or gpu in slots:
                _fail("report GPU slot mapping is invalid or duplicated")
            slots.add(gpu)
            namespace = _absolute_path(job.get("output_namespace"), "job.output_namespace")
            if str(namespace) in namespaces:
                _fail("report output namespaces are not unique")
            namespaces.add(str(namespace))
            _zero_credit(job, "job")
            execution = _mapping(job.get("execution"), "job.execution")
            _exact(execution, "launch_allowed", False, "job.execution")
            _exact(execution, "diagnostic_only", True, "job.execution")
        _zero_credit(batch, f"report.batches[{batch_index}]")
    expected = {(case_id, seed) for case_id in case_ids for seed in SEEDS}
    if pairs != expected:
        _fail("report does not cover exactly 32 cases x seeds 17, 29, 43")
    coverage = _mapping(report.get("coverage"), "report.coverage")
    _exact(coverage, "job_count", EXPECTED_CASE_COUNT * len(SEEDS), "report.coverage")
    _exact(coverage, "batch_count", len(batches), "report.coverage")
    _exact(coverage, "duplicate_case_seed_pairs", 0, "report.coverage")
    _exact(coverage, "mixed_seed_batches", 0, "report.coverage")
    boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
    for key in ("hdf5_content_opened", "checkpoint_content_opened", "gpu_started", "solver_started", "worker_started", "registry_read", "ledger_read", "gate_read", "plan_read"):
        _exact(boundary, key, False, "report.input_boundary")
    effects = _mapping(report.get("side_effects"), "report.side_effects")
    for key, value in effects.items():
        if type(value) is not int or value != 0:
            _fail(f"report.side_effects.{key} must remain zero")


def render_markdown(report: Mapping[str, Any]) -> str:
    campaign = report["campaign"]
    sources = report["sources"]
    coverage = report["coverage"]
    lines = [
        "# F3 MLP hidden16 current-manifest bounded campaign schedule",
        "",
        f"- 状态：`{report['status']}`；campaign=`{campaign['campaign_id']}`",
        f"- 覆盖：`{coverage['case_count']}` cases × seeds `{','.join(str(seed) for seed in coverage['seeds'])}` = `{coverage['job_count']}` jobs",
        f"- 批次：`{coverage['batch_count']}` 个；每批最多 `{coverage['max_cases_per_batch']}` 个 case；seed 隔离=`{campaign['seed_independence']}`",
        f"- 预计输出空间：约 `{report['output_space']['estimated_gib_total']} GiB`（固定规划包络，不读取 HDF5/checkpoint 内容）",
        "",
        "## Source identity",
        "",
        f"- manifest：`{sources['manifest']['path']}`",
        f"- manifest raw SHA-256：`{sources['manifest']['sha256']}`",
        f"- manifest canonical SHA-256：`{sources['manifest']['canonical_sha256']}`",
        f"- training identity：`{sources['training_identity']['path']}`",
        f"- training identity SHA-256：`{sources['training_identity']['sha256']}`",
        "",
        "## Batch schedule",
        "",
        "| batch | seed | cases | GPU slots | output report |",
        "|---|---:|---:|---|---|",
    ]
    for batch in report["batches"]:
        slots = ",".join(str(item["gpu_index"]) for item in batch["gpu_slot_mapping"])
        lines.append(
            f"| `{batch['batch_id']}` | {batch['seed']} | {batch['case_count']} | `{slots}` | `{batch['output_report']}` |"
        )
    lines.extend(
        [
            "",
            "## Fail-closed boundary",
            "",
            "- 计划器只打开显式 manifest/training identity JSON；不打开 HDF5 或 checkpoint 内容。",
            "- 不启动 GPU、solver、worker，不停止或重启既有进程。",
            "- 所有 job 都是 `schedule_only`、`diagnostic_only=true`、`formal=false`、`credit=0`；本报告不是 terminal receipt。",
            "- 不读取或写入 formal registry、ledger、gate 或 PLAN；后续 executor 必须重新进行显存、namespace、新鲜性和终态回执检查。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_new(path: Path, content: str) -> None:
    _reject_symlink_components(path, "output")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError:
        _fail(f"refusing to overwrite existing output: {path}")
    except OSError as error:
        _fail(f"cannot create output {path}: {error}")
    try:
        offset = 0
        while offset < len(encoded):
            offset += os.write(descriptor, encoded[offset:])
    finally:
        os.close(descriptor)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--training-identity")
    parser.add_argument("--output-root")
    parser.add_argument("--campaign-id")
    parser.add_argument("--plan-date", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    parser.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE)
    parser.add_argument(
        "--estimated-output-bytes-per-case",
        type=int,
        default=DEFAULT_OUTPUT_BYTES_PER_CASE,
    )
    parser.add_argument("--output")
    parser.add_argument("--markdown-output")
    parser.add_argument("--verify-report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report:
            report, source = _read_bounded_json(
                args.verify_report, name="schedule_report", max_bytes=MAX_REPORT_BYTES
            )
            validate_report(report)
            print(json.dumps({"status": "verified", "report": source["path"], "report_sha256": source["sha256"]}, sort_keys=True))
            return 0
        required = {
            "--manifest": args.manifest,
            "--training-identity": args.training_identity,
            "--output-root": args.output_root,
            "--campaign-id": args.campaign_id,
            "--output": args.output,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ScheduleError(f"missing required arguments: {', '.join(missing)}")
        report = build_schedule(
            manifest=args.manifest,
            training_identity=args.training_identity,
            output_root=args.output_root,
            campaign_id=args.campaign_id,
            plan_date=args.plan_date,
            batch_size=args.batch_size,
            estimated_output_bytes_per_case=args.estimated_output_bytes_per_case,
        )
        output = _absolute_path(args.output, "output")
        markdown = _absolute_path(args.markdown_output, "markdown_output") if args.markdown_output else None
        input_paths = [Path(report["sources"]["manifest"]["path"]), Path(report["sources"]["training_identity"]["path"])]
        targets = [output] + ([markdown] if markdown else [])
        for target in targets:
            if any(_path_conflicts(target, source_path) for source_path in input_paths):
                _fail(f"output target conflicts with an input identity: {target}")
            for batch in report["batches"]:
                if _path_conflicts(target, Path(batch["output_report"])) or _path_conflicts(target, Path(batch["markdown_report"])):
                    _fail(f"output target conflicts with a batch report: {target}")
                for job in batch["jobs"]:
                    if _path_conflicts(target, Path(job["output_namespace"])):
                        _fail(f"output target conflicts with a planned namespace: {target}")
        if markdown is not None and output == markdown:
            _fail("JSON and Markdown output paths conflict")
        _write_new(output, json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        if markdown is not None:
            _write_new(markdown, render_markdown(report))
        print(json.dumps({
            "status": report["status"],
            "output": str(output),
            "markdown_output": str(markdown) if markdown else None,
            "batches": report["coverage"]["batch_count"],
            "jobs": report["coverage"]["job_count"],
            "credit": report["credit"],
        }, sort_keys=True))
        return 0
    except (ScheduleError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
