#!/usr/bin/env python3
"""Plan a bounded F3 graph_residual/hidden16 current-manifest matrix.

This is an additive, non-launching planner.  It binds the current canonical
manifest to the graph_residual hidden16/500-update contract inherited from the
historical three-seed training matrix and emits three training plans plus the
32-case x 3-seed case matrix.  Current training receipts, when present, are
read as bounded JSON identity metadata only.  Missing or drifting receipts are
fail-closed: the plans remain diagnostic-only, launch_allowed is false, and
all credit and formal markers stay zero.

The planner never opens, stats, or hashes a checkpoint, case HDF5, trajectory,
evaluation, or progress artifact.  It never starts, stops, or restarts a
process and never writes a registry, ledger, denominator, gate, or completion
record.  The checked-in report is therefore a planning/identity artifact, not
terminal runtime evidence.
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
import tempfile
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f3_graph_residual_hidden16_training_evidence_matrix_v1 as historical


SEEDS = tuple(historical.SEEDS)
MODEL = historical.MODEL_KIND
HIDDEN = historical.HIDDEN
UPDATES = historical.UPDATES
PARAMETER_COUNT = historical.PARAMETER_COUNT
NORMALIZATION_TRANSITIONS = historical.NORMALIZATION_TRANSITIONS
PRIOR_ROWS = historical.PRIOR_ROWS
TRANSITIONS = 835
FRAMES = 836
GPU_COUNT = 8
BATCH_SIZE = 8
EXPECTED_CASE_COUNT = 32
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
DATE_RE = re.compile(r"^20[0-9]{6}$")
CASE_ID_RE = re.compile(r"^F3_DEV_[0-9]{2}_[A-Za-z0-9p]+$")
RUN_ID_RE = re.compile(
    r"^f3-graph[_-]residual500-hidden16-currentmanifest-seed"
    r"(?P<seed>17|29|43)-(?P<date>20[0-9]{6})(?P<variant>-v[0-9]+)?$"
)
OLD_RUN_ID_RE = re.compile(
    r"^f3-graph-residual500-hidden16-seed"
    r"(?P<seed>17|29|43)-20[0-9]{6}$"
)

SCHEMA = "core.f3.graph_residual.hidden16.current_manifest.case_matrix.v1"
REPORT_ID = "f3-graph-residual-hidden16-current-manifest-case-matrix-v1"
HISTORICAL_SCHEMA = historical.REFERENCE_SCHEMA
TRAINING_SCHEMA = historical.TRAINING_SCHEMA
CHECKPOINT_SCHEMA = historical.CHECKPOINT_SCHEMA
EVIDENCE_SCHEMA = historical.EVIDENCE_SCHEMA
INITIALIZATION_SCHEMA = historical.INITIALIZATION_SCHEMA
NORMALIZATION_SCHEMA = historical.NORMALIZATION_SCHEMA
PRIOR_SCHEMA = historical.PRIOR_SCHEMA
STATIC_CONFIG = dict(historical.STATIC_CONFIG)
REFERENCE_SHARED_CONFIG = dict(historical.REFERENCE_SHARED_CONFIG)

DEFAULT_HISTORICAL_MATRIX = (
    LAB_ROOT / "reports/F3-GRAPH-RESIDUAL-HIDDEN16-SEEDS17-29-43-TRAINING-2026-09-28.json"
)
DEFAULT_MANIFEST = LAB_ROOT / "campaigns/core-v1/f3-dataset-v2.json"
DEFAULT_OUTPUT = (
    LAB_ROOT
    / "reports/F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-2026-09-29.json"
)
DEFAULT_MARKDOWN_OUTPUT = DEFAULT_OUTPUT.with_suffix(".zh-CN.md")

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
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        _fail(f"{name} is oversized")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be boolean")
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
    if normalized != os.sep and normalized.endswith(os.sep):
        _fail(f"{name} has a trailing separator")
    return Path(normalized)


def _reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor or os.curdir)
    for component in absolute.parts[1:] if absolute.is_absolute() else absolute.parts:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as error:
            _fail(f"cannot inspect path component {current}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"symlink path component is not accepted: {current}")


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size)


def _read_bounded_json(
    path: Path | str,
    *,
    name: str,
    max_bytes: int,
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Read one bounded, regular, single-link JSON object."""

    candidate = _absolute_path(path, name)
    _reject_symlink_components(candidate)
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
            block = os.read(descriptor, min(64 * 1024, max_bytes + 1 - total))
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
    except (UnicodeError, json.JSONDecodeError, MatrixError, RecursionError) as error:
        _fail(f"invalid bounded {name}: {error}")
    payload = _mapping(payload, name)
    _walk_json(payload, name)
    return payload, {
        "path": str(candidate),
        "exists": True,
        "opened": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload.get("schema"),
    }


def _missing_source(path: Path | str, error: Exception) -> dict[str, Any]:
    try:
        candidate = _absolute_path(path, "missing_source")
    except MatrixError:
        candidate = Path(os.fspath(path))
    result = {
        "path": str(candidate),
        "exists": False,
        "opened": False,
        "bytes": None,
        "sha256": None,
        "schema": None,
        "error": str(error),
    }
    try:
        info = os.lstat(candidate)
    except OSError:
        return result
    if stat.S_ISREG(info.st_mode):
        result["exists"] = True
        result["bytes"] = info.st_size
    else:
        result["error"] = f"source is not a regular file: {candidate}"
    return result


def _status_source(path: Path | str, status: str) -> dict[str, Any]:
    """Record an explicit runtime state without opening or stat-ing its artifacts."""

    return {
        "path": str(path),
        "exists": None,
        "opened": False,
        "bytes": None,
        "sha256": None,
        "schema": None,
        "status_hint": status,
    }


def _canonical_sha(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        _fail(f"value cannot be canonically encoded: {error}")
    return hashlib.sha256(raw).hexdigest()


def _zero_credit(value: Mapping[str, Any], name: str) -> None:
    _exact(value, "diagnostic_only", True, name)
    for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
        if key in value:
            _exact(value, key, False, name)
    for key in ("credit", "qualification_credit"):
        if key in value:
            _exact(value, key, 0, name)


def _safe_relative_metadata(value: Any, name: str) -> str:
    path = _string(value, name)
    candidate = Path(path)
    if candidate.is_absolute() or any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} must be a relative alias-free path")
    return path


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
        _fail(f"{name}.split is not supported")
    hdf5 = _safe_relative_metadata(case.get("hdf5"), f"{name}.hdf5")
    hdf5_bytes = _strict_int(case.get("bytes"), f"{name}.bytes", 1)
    provenance = _mapping(case.get("provenance"), f"{name}.provenance")
    hdf5_sha_value = case.get("sha256")
    if hdf5_sha_value is None:
        hdf5_sha_value = provenance.get("sha256")
    hdf5_sha = _sha(hdf5_sha_value, f"{name}.sha256")
    known_inputs = _mapping(case.get("known_inputs_ref"), f"{name}.known_inputs_ref")
    _exact(known_inputs, "contract_version", "core.inputs.v1", f"{name}.known_inputs_ref")
    known_inputs_sha_value = case.get("known_inputs_sha256")
    if known_inputs_sha_value is None:
        known_inputs_sha_value = known_inputs.get("known_inputs_sha256")
    known_inputs_sha = _sha(known_inputs_sha_value, f"{name}.known_inputs_sha256")
    _safe_relative_metadata(
        _mapping(known_inputs.get("geometry"), f"{name}.known_inputs_ref.geometry").get("path"),
        f"{name}.known_inputs_ref.geometry.path",
    )
    _safe_relative_metadata(
        _mapping(known_inputs.get("control"), f"{name}.known_inputs_ref.control").get("path"),
        f"{name}.known_inputs_ref.control.path",
    )
    _exact(case, "qualification_case", False, name)
    return {
        "index": index,
        "case_id": case_id,
        "physical_case_id": case_id,
        "family": "F3",
        "split": split,
        "evaluation_role": _string(case.get("evaluation_role"), f"{name}.evaluation_role"),
        "hdf5": hdf5,
        "hdf5_sha256": hdf5_sha,
        "hdf5_bytes": hdf5_bytes,
        "known_inputs_sha256": known_inputs_sha,
        "lineage_group_id": _sha(case.get("lineage_group_id"), f"{name}.lineage_group_id"),
        "scope_id": _string(case.get("scope_id"), f"{name}.scope_id"),
    }


def _validate_manifest(
    payload: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    _exact(payload, "schema", "core.dataset.v2", "manifest")
    _exact(payload, "case_count", EXPECTED_CASE_COUNT, "manifest")
    _exact(payload, "formal_release", False, "manifest")
    _exact(payload, "dataset_id", "F3_registered32_core_native_v2", "manifest")
    _exact(payload, "input_asset_policy", "content_addressed_compressed_npz", "manifest")
    source_manifest_sha = _sha(payload.get("source_manifest_sha256"), "manifest.source_manifest_sha256")
    cases_value = payload.get("cases")
    if not isinstance(cases_value, list) or len(cases_value) != EXPECTED_CASE_COUNT:
        _fail("manifest.cases must contain exactly 32 cases")
    cases = [
        _validate_case(_mapping(case, f"manifest.cases[{index}"), index)
        for index, case in enumerate(cases_value)
    ]
    case_ids = [case["case_id"] for case in cases]
    if len(set(case_ids)) != EXPECTED_CASE_COUNT:
        _fail("manifest case identifiers are not unique")
    artifact_ids = [case["hdf5_sha256"] for case in cases]
    if len(set(artifact_ids)) != EXPECTED_CASE_COUNT:
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


def _validate_historical_matrix(
    payload: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    current_manifest_sha256: str,
) -> dict[str, Any]:
    _exact(payload, "schema", HISTORICAL_SCHEMA, "historical_matrix")
    _exact(payload, "model", MODEL, "historical_matrix")
    _exact(payload, "diagnostic_only", True, "historical_matrix")
    _exact(payload, "formal_eligible", False, "historical_matrix")
    _sha(payload.get("manifest_sha256"), "historical_matrix.manifest_sha256")
    if payload["manifest_sha256"] != current_manifest_sha256:
        _fail("historical_matrix manifest_sha256 does not equal current canonical manifest")
    shared_config = _mapping(payload.get("shared_config"), "historical_matrix.shared_config")
    if dict(shared_config) != REFERENCE_SHARED_CONFIG:
        _fail("historical_matrix.shared_config drifts from graph_residual hidden16 contract")
    qualification = _mapping(payload.get("qualification"), "historical_matrix.qualification")
    _exact(qualification, "training_evidence_complete", True, "historical_matrix.qualification")
    _exact(qualification, "qualification", False, "historical_matrix.qualification")
    _exact(qualification, "t1", False, "historical_matrix.qualification")
    _exact(qualification, "t2", False, "historical_matrix.qualification")
    _exact(qualification, "credit", 0, "historical_matrix.qualification")
    runs = payload.get("runs")
    if not isinstance(runs, list) or len(runs) != len(SEEDS):
        _fail("historical_matrix.runs must contain exactly three seeds")
    observed: set[int] = set()
    for index, item in enumerate(runs):
        row = _mapping(item, f"historical_matrix.runs[{index}]")
        seed = _strict_int(row.get("seed"), f"historical_matrix.runs[{index}].seed")
        if seed not in SEEDS or seed in observed:
            _fail("historical_matrix seed set must be exactly 17, 29, 43")
        observed.add(seed)
        run_id = _string(row.get("run_id"), f"historical_matrix.runs[{index}].run_id")
        match = OLD_RUN_ID_RE.fullmatch(run_id)
        if match is None or int(match.group("seed")) != seed:
            _fail(f"historical_matrix run {seed} has an invalid historical run_id")
        _exact(row, "completed_updates", UPDATES, f"historical_matrix.runs[{index}]")
        _exact(row, "parameter_count", PARAMETER_COUNT, f"historical_matrix.runs[{index}]")
        _exact(row, "checkpoint_verified", True, f"historical_matrix.runs[{index}]")
        for key in (
            "checkpoint_sha256",
            "training_receipt_sha256",
            "initialization_parameter_digest",
            "normalization_identity_sha256",
            "residual_prior_identity_sha256",
        ):
            _sha(row.get(key), f"historical_matrix.runs[{index}].{key}")
    if observed != set(SEEDS):
        _fail("historical_matrix does not cover exactly seeds 17, 29, 43")
    return {
        "schema": HISTORICAL_SCHEMA,
        "source": dict(source),
        "manifest_sha256": current_manifest_sha256,
        "shared_config": dict(shared_config),
        "seed_count": len(SEEDS),
        "reference_report_id": _string(payload.get("report_id"), "historical_matrix.report_id"),
    }


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    if not result:
        _fail("identifier produced an empty namespace slug")
    return result


def _nonce(*parts: object) -> str:
    material = "|".join(str(part) for part in parts).encode("utf-8")
    value = hashlib.sha256(material).hexdigest()[:32]
    if NONCE_RE.fullmatch(value) is None or int(value, 16) == 0:
        _fail("deterministic namespace nonce is invalid")
    return value


def _command_digest(command: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> str:
    return _canonical_sha({"argv": list(command), "cwd": str(cwd), "env_overrides": dict(env)})


def _run_id(seed: int, plan_date: str) -> str:
    return f"f3-graph_residual500-hidden16-currentmanifest-seed{seed}-{plan_date}"


def _explicit_training_identity(
    receipt_path: Path,
    *,
    seed: int,
    plan_date: str,
) -> tuple[str, Path]:
    """Derive a run id and unique output prefix from an explicit receipt path."""

    suffix = "-training.json"
    if not receipt_path.name.endswith(suffix):
        _fail(f"seed{seed} explicit receipt must end with -training.json")
    prefix = receipt_path.name[: -len(suffix)]
    match = RUN_ID_RE.fullmatch(prefix)
    if match is None or int(match.group("seed")) != seed or match.group("date") != plan_date:
        _fail(f"seed{seed} explicit receipt filename does not bind current run/date")
    return prefix, receipt_path.with_name(prefix)


def _expected_config(manifest_sha256: str, seed: int, run_id: str) -> dict[str, Any]:
    config = dict(STATIC_CONFIG)
    config.update(
        {
            "manifest_sha256": manifest_sha256,
            "paired_seed": seed,
            "run_id": run_id,
            "sampler_seed": seed,
            "seed": seed,
        }
    )
    return config


def _launch_config(
    manifest_sha256: str,
    seed: int,
    run_id: str,
    *,
    deferred_validation: bool,
) -> dict[str, Any]:
    config = _expected_config(manifest_sha256, seed, run_id)
    if deferred_validation:
        config["validation_every"] = 0
        config["evaluate_milestones"] = False
        config["milestone_evaluation_mode"] = "deferred"
    return config


def _training_plan(
    *,
    root: Path,
    manifest_path: Path,
    manifest_sha256: str,
    seed: int,
    ordinal: int,
    plan_date: str,
    python_executable: Path,
    explicit_receipt_path: Path | None = None,
) -> dict[str, Any]:
    explicit = explicit_receipt_path is not None
    if explicit:
        run_id, namespace = _explicit_training_identity(
            explicit_receipt_path,
            seed=seed,
            plan_date=plan_date,
        )
        receipt_output = explicit_receipt_path
        checkpoint_output = namespace.with_name(namespace.name + "-checkpoint.pt")
        progress_output = namespace.with_name(namespace.name + "-training-progress.json")
    else:
        run_id = _run_id(seed, plan_date)
        namespace = Path(
            "/tmp"
            f"/f3-graph_residual500-hidden16-currentmanifest-training-{plan_date}-"
            f"seed{seed}-{_nonce(SCHEMA, 'training', manifest_sha256, seed, run_id)}"
        )
        receipt_output = namespace / "training.json"
        checkpoint_output = namespace / "checkpoint.pt"
        progress_output = namespace / "training-progress.json"
    deferred_validation = explicit
    launch_config = _launch_config(
        manifest_sha256,
        seed,
        run_id,
        deferred_validation=deferred_validation,
    )
    nonce = _nonce(SCHEMA, "training", manifest_sha256, seed, run_id)
    outputs = {
        "training_receipt": receipt_output,
        "checkpoint": checkpoint_output,
        "progress": progress_output,
    }
    command = (
        str(python_executable),
        "-u",
        str(root / "scripts" / "core_learning.py"),
        "train",
        "--manifest",
        str(manifest_path),
        "--data-root",
        str(root),
        "--model",
        MODEL,
        "--seed",
        str(seed),
        "--updates",
        str(UPDATES),
        "--centers",
        str(STATIC_CONFIG["centers_per_update"]),
        "--hidden",
        str(HIDDEN),
        "--learning-rate",
        str(STATIC_CONFIG["learning_rate"]),
        "--normalization-transitions",
        str(NORMALIZATION_TRANSITIONS),
        "--max-neighbors",
        str(STATIC_CONFIG["max_neighbors"]),
        "--checkpoint",
        str(outputs["checkpoint"]),
        "--run-id",
        run_id,
        "--checkpoint-every",
        str(STATIC_CONFIG["checkpoint_every"]),
        "--log-every",
        str(STATIC_CONFIG["log_every"]),
        "--validation-every",
        str(launch_config["validation_every"]),
        "--validation-transitions",
        str(STATIC_CONFIG["validation_transition_count"]),
        "--validation-centers",
        str(STATIC_CONFIG["validation_centers"]),
        "--no-evaluate-milestones" if deferred_validation else "--evaluate-milestones",
        "--device",
        "cuda:0",
        "--progress-output",
        str(outputs["progress"]),
        "--output",
        str(outputs["training_receipt"]),
    )
    env = {"CUDA_VISIBLE_DEVICES": str(ordinal % GPU_COUNT), "PYTHONDONTWRITEBYTECODE": "1"}
    return {
        "job_id": f"f3-graph_residual-hidden16-currentmanifest-training-seed{seed}",
        "ordinal": ordinal,
        "seed": seed,
        "run_id": run_id,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "parameter_count": PARAMETER_COUNT,
        "manifest_sha256": manifest_sha256,
        "shared_config": dict(REFERENCE_SHARED_CONFIG),
        "launch_config": launch_config,
        "config_profile": "v3_deferred_validation" if deferred_validation else "historical_reference",
        "output_namespace": str(namespace),
        "namespace_kind": "prefix" if explicit else "directory",
        "namespace_nonce": nonce,
        "namespace_freshness_attested": False,
        "namespace_reuse_allowed": False,
        "command": list(command),
        "cwd": str(root),
        "env_overrides": env,
        "command_sha256": _command_digest(command, cwd=root, env=env),
        "outputs": {key: str(value) for key, value in outputs.items()},
        "status": "missing",
        "receipt_observed": False,
        "receipt": None,
        "checkpoint": {
            "schema": CHECKPOINT_SCHEMA,
            "path": str(outputs["checkpoint"]),
            "sha256": None,
            "bytes": None,
            "update": UPDATES,
            "observed": False,
        },
        "launch_allowed": False,
        **ZERO_CREDIT,
        "zero_credit_only": True,
    }


def _validate_training_receipt(
    payload: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    seed = int(plan["seed"])
    name = f"training_receipt.seed{seed}"
    _walk_json(payload, name)
    _exact(payload, "schema", TRAINING_SCHEMA, name)
    _exact(payload, "evidence_status", "complete", name)
    _exact(payload, "status", "completed", name)
    _exact(payload, "model_kind", MODEL, name)
    _exact(payload, "seed", seed, name)
    _exact(payload, "completed_updates", UPDATES, name)
    _exact(payload, "parameter_count", PARAMETER_COUNT, name)
    _exact(payload, "checkpoint_verified", True, name)
    run_id = _string(payload.get("run_id"), f"{name}.run_id")
    if run_id != plan["run_id"]:
        _fail(f"{name}.run_id does not bind current-manifest plan")
    config = _mapping(payload.get("config"), f"{name}.config")
    expected_config = _mapping(plan.get("launch_config"), f"{name}.launch_config")
    if dict(config) != expected_config:
        _fail(f"{name}.config does not exactly bind model/config/seed/current manifest")
    for key in ("diagnostic_only", "formal", "formal_eligible", "qualification", "T1_numerical", "T2_macro", "T2_path"):
        if key in payload:
            if key == "diagnostic_only":
                _exact(payload, key, True, name)
            else:
                _exact(payload, key, False, name)
    for key in ("credit", "qualification_credit"):
        if key in payload:
            _exact(payload, key, 0, name)

    evidence = _mapping(payload.get("evidence"), f"{name}.evidence")
    _exact(evidence, "schema", EVIDENCE_SCHEMA, f"{name}.evidence")
    _exact(evidence, "status", "complete", f"{name}.evidence")
    initialization = _mapping(evidence.get("initialization"), f"{name}.evidence.initialization")
    _exact(initialization, "schema", INITIALIZATION_SCHEMA, f"{name}.initialization")
    _exact(initialization, "status", "captured", f"{name}.initialization")
    _exact(initialization, "model_kind", MODEL, f"{name}.initialization")
    _exact(initialization, "hidden", HIDDEN, f"{name}.initialization")
    _exact(initialization, "parameter_count", PARAMETER_COUNT, f"{name}.initialization")
    _exact(initialization, "seed", seed, f"{name}.initialization")
    _exact(initialization, "constructed_before_first_update", True, f"{name}.initialization")
    _sha(initialization.get("parameter_digest"), f"{name}.initialization.parameter_digest")

    normalization = _mapping(evidence.get("normalization"), f"{name}.evidence.normalization")
    _exact(normalization, "schema", NORMALIZATION_SCHEMA, f"{name}.normalization")
    _exact(normalization, "requested_maximum_transitions", NORMALIZATION_TRANSITIONS, f"{name}.normalization")
    _exact(normalization, "selected_transition_count", NORMALIZATION_TRANSITIONS, f"{name}.normalization")
    _exact(normalization, "selection_policy", REFERENCE_SHARED_CONFIG["normalization_selection_policy"], f"{name}.normalization")
    _exact(normalization, "selection_seed", seed, f"{name}.normalization")
    _exact(normalization, "source_split", "train", f"{name}.normalization")
    _exact(normalization, "target_reference", REFERENCE_SHARED_CONFIG["normalization_target_reference"], f"{name}.normalization")
    _strict_int(normalization.get("available_transition_count"), f"{name}.normalization.available_transition_count", NORMALIZATION_TRANSITIONS)

    prior = _mapping(evidence.get("residual_prior"), f"{name}.evidence.residual_prior")
    _exact(prior, "schema", PRIOR_SCHEMA, f"{name}.residual_prior")
    _exact(prior, "enabled", True, f"{name}.residual_prior")
    _exact(prior, "history_complete", True, f"{name}.residual_prior")
    _exact(prior, "units", {"delta_velocity": "m/s", "displacement": "m"}, f"{name}.residual_prior")
    _exact(prior, "execution_calls", UPDATES, f"{name}.residual_prior")
    _exact(prior, "rows", PRIOR_ROWS, f"{name}.residual_prior")
    _exact(prior, "finite", True, f"{name}.residual_prior")
    _exact(
        prior,
        "semantic",
        "graph_residual subtracts this SI prior before shared raw-target normalization; predictor adds it back",
        f"{name}.residual_prior",
    )
    last_update = _mapping(prior.get("last_update"), f"{name}.residual_prior.last_update")
    _exact(last_update, "update", UPDATES, f"{name}.residual_prior.last_update")
    _string(last_update.get("case_id"), f"{name}.residual_prior.last_update.case_id")
    _strict_int(last_update.get("frame"), f"{name}.residual_prior.last_update.frame")
    for key in ("dx_abs_max_m", "dv_abs_max_mps", "dx_abs_sum_m", "dv_abs_sum_mps"):
        value = prior.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
            _fail(f"{name}.residual_prior.{key} must be finite and nonnegative")

    checkpoint = _mapping(payload.get("checkpoint"), f"{name}.checkpoint")
    _exact(checkpoint, "schema", CHECKPOINT_SCHEMA, f"{name}.checkpoint")
    _exact(checkpoint, "update", UPDATES, f"{name}.checkpoint")
    checkpoint_path = _string(checkpoint.get("path"), f"{name}.checkpoint.path")
    checkpoint_path_obj = Path(checkpoint_path)
    if not checkpoint_path_obj.is_absolute() or ".." in checkpoint_path_obj.parts or checkpoint_path_obj.suffix != ".pt":
        _fail(f"{name}.checkpoint.path is unsafe")
    if checkpoint_path != plan["outputs"]["checkpoint"]:
        _fail(f"{name}.checkpoint.path does not bind planned namespace")
    checkpoint_sha = _sha(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")
    checkpoint_bytes = _strict_int(checkpoint.get("bytes"), f"{name}.checkpoint.bytes", 1)
    source_path = _string(source.get("path"), f"{name}.source.path")
    if source_path != plan["outputs"]["training_receipt"]:
        _fail(f"{name}.source.path does not bind planned namespace")
    return {
        "schema": TRAINING_SCHEMA,
        "path": source_path,
        "bytes": _strict_int(source.get("bytes"), f"{name}.source.bytes", 1),
        "sha256": _sha(source.get("sha256"), f"{name}.source.sha256"),
        "opened": True,
        "run_id": run_id,
        "seed": seed,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "manifest_sha256": plan["manifest_sha256"],
        "checkpoint": {
            "schema": CHECKPOINT_SCHEMA,
            "path": checkpoint_path,
            "bytes": checkpoint_bytes,
            "sha256": checkpoint_sha,
            "update": UPDATES,
            "observed": True,
        },
        "initialization_parameter_digest": initialization["parameter_digest"],
        "normalization_identity_sha256": _canonical_sha(
            {
                "schema": normalization["schema"],
                "available_transition_count": normalization["available_transition_count"],
                "requested_maximum_transitions": normalization["requested_maximum_transitions"],
                "selected_transition_count": normalization["selected_transition_count"],
                "selection_policy": normalization["selection_policy"],
                "selection_seed": normalization["selection_seed"],
                "source_split": normalization["source_split"],
                "target_reference": normalization["target_reference"],
            }
        ),
        "residual_prior_identity_sha256": _canonical_sha(
            {
                "schema": prior["schema"],
                "enabled": prior["enabled"],
                "history_complete": prior["history_complete"],
                "units": prior["units"],
                "execution_calls": prior["execution_calls"],
                "rows": prior["rows"],
                "finite": prior["finite"],
                "semantic": prior["semantic"],
                "dx_abs_max_m": prior["dx_abs_max_m"],
                "dv_abs_max_mps": prior["dv_abs_max_mps"],
                "dx_abs_sum_m": prior["dx_abs_sum_m"],
                "dv_abs_sum_mps": prior["dv_abs_sum_mps"],
                "last_update": prior["last_update"],
            }
        ),
    }


def _case_plan(
    *,
    root: Path,
    manifest_path: Path,
    manifest_sha256: str,
    case: Mapping[str, Any],
    training: Mapping[str, Any],
    ordinal: int,
    plan_date: str,
    python_executable: Path,
) -> dict[str, Any]:
    seed = int(training["seed"])
    case_id = str(case["case_id"])
    nonce = _nonce(SCHEMA, "case", manifest_sha256, case_id, seed, training["run_id"])
    namespace = Path(
        "/tmp"
        f"/f3-graph-residual500-hidden16-currentmanifest-case-matrix-{plan_date}-"
        f"case{int(case['index']):02d}-{_slug(case_id)}-seed{seed}-full835-{nonce}"
    )
    outputs = {
        "evaluation": namespace / "evaluation.json",
        "trajectory": namespace / "trajectory.h5",
        "progress": namespace / "progress.json",
        "validator": namespace / "hdf5-validation.json",
        "artifact_identity": namespace / "artifact-identity.json",
        "trajectory_metadata": namespace / "trajectory-metadata.json",
        "process_proof": root
        / "reports"
        / f"F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-CASE{int(case['index']):02d}-SEED{seed}-PROCESS-EXIT-PROOF-V1.json",
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
        str(training["outputs"]["checkpoint"]),
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
    env = {"CUDA_VISIBLE_DEVICES": str(ordinal % GPU_COUNT), "PYTHONDONTWRITEBYTECODE": "1"}
    status = "dry_run_ready" if training["status"] == "bound_complete" else "blocked_missing_training_receipt"
    return {
        "job_id": f"f3-graph-residual-hidden16-currentmanifest-case{int(case['index']):02d}-seed{seed}",
        "ordinal": ordinal,
        "batch_index": ordinal // BATCH_SIZE,
        "batch_slot": ordinal % BATCH_SIZE,
        "gpu_index": ordinal % GPU_COUNT,
        "seed": seed,
        "run_id": training["run_id"],
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "parameter_count": PARAMETER_COUNT,
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
        "training_receipt": training["receipt"],
        "checkpoint": training["checkpoint"],
        "output_namespace": str(namespace),
        "namespace_nonce": nonce,
        "namespace_freshness_attested": False,
        "namespace_reuse_allowed": False,
        "command": list(command),
        "cwd": str(root),
        "env_overrides": env,
        "command_sha256": _command_digest(command, cwd=root, env=env),
        "outputs": {key: str(value) for key, value in outputs.items()},
        "status": status,
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


def _validate_training_plan(plan: Mapping[str, Any], *, root: Path, manifest_sha256: str, plan_date: str) -> None:
    name = f"training_plans[{plan.get('ordinal', '?')}]"
    seed = _strict_int(plan.get("seed"), f"{name}.seed")
    if seed not in SEEDS:
        _fail(f"{name}.seed is outside exact seed set")
    _exact(plan, "model", MODEL, name)
    _exact(plan, "hidden", HIDDEN, name)
    _exact(plan, "updates", UPDATES, name)
    _exact(plan, "parameter_count", PARAMETER_COUNT, name)
    _exact(plan, "manifest_sha256", manifest_sha256, name)
    expected_run_id = _string(plan.get("run_id"), f"{name}.run_id")
    run_match = RUN_ID_RE.fullmatch(expected_run_id)
    if run_match is None or int(run_match.group("seed")) != seed or run_match.group("date") != plan_date:
        _fail(f"{name}.run_id does not bind seed/date")
    status = plan.get("status")
    if status not in {"missing", "running", "rejected", "bound_complete"}:
        _fail(f"{name}.status is invalid")
    _exact(plan, "launch_allowed", False, name)
    _zero_credit(plan, name)
    _exact(plan, "receipt_observed", status == "bound_complete", name)
    namespace = _absolute_path(plan.get("output_namespace"), f"{name}.output_namespace")
    nonce = _string(plan.get("namespace_nonce"), f"{name}.namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None:
        _fail(f"{name} namespace/nonce identity is invalid")
    namespace_kind = plan.get("namespace_kind")
    if namespace_kind not in {"directory", "prefix"}:
        _fail(f"{name}.namespace_kind is invalid")
    if namespace_kind == "directory":
        if not namespace.name.startswith("f3-graph_residual500-hidden16-currentmanifest-training-") or not namespace.name.endswith(nonce):
            _fail(f"{name}.output_namespace directory identity drifts")
    else:
        if not namespace.name.startswith("f3-graph_residual500-hidden16-currentmanifest-seed"):
            _fail(f"{name}.output_namespace prefix identity drifts")
    _exact(plan, "cwd", str(root), name)
    command = plan.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        _fail(f"{name}.command must be a non-empty argv")
    env = _mapping(plan.get("env_overrides"), f"{name}.env_overrides")
    _exact(env, "CUDA_VISIBLE_DEVICES", str(int(plan["ordinal"]) % GPU_COUNT), f"{name}.env_overrides")
    _exact(env, "PYTHONDONTWRITEBYTECODE", "1", f"{name}.env_overrides")
    _exact(plan, "command_sha256", _command_digest(command, cwd=root, env=dict(env)), name)
    launch_config = _mapping(plan.get("launch_config"), f"{name}.launch_config")
    profile = _string(plan.get("config_profile"), f"{name}.config_profile")
    if profile not in {"historical_reference", "v3_deferred_validation"}:
        _fail(f"{name}.config_profile is invalid")
    if dict(launch_config) != _launch_config(
        manifest_sha256,
        seed,
        expected_run_id,
        deferred_validation=profile == "v3_deferred_validation",
    ):
        _fail(f"{name}.launch_config drifts")
    for flag, value in (
        ("--model", MODEL),
        ("--seed", str(seed)),
        ("--updates", str(UPDATES)),
        ("--hidden", str(HIDDEN)),
        ("--normalization-transitions", str(NORMALIZATION_TRANSITIONS)),
        ("--run-id", expected_run_id),
        ("--validation-every", str(launch_config["validation_every"])),
    ):
        if command.count(flag) != 1 or command[command.index(flag) + 1] != value:
            _fail(f"{name}.command {flag} identity drifts")
    milestone_flag = "--no-evaluate-milestones" if profile == "v3_deferred_validation" else "--evaluate-milestones"
    if milestone_flag not in command or ("--evaluate-milestones" in command and "--no-evaluate-milestones" in command):
        _fail(f"{name}.command milestone mode drifts")
    outputs = _mapping(plan.get("outputs"), f"{name}.outputs")
    for key in ("training_receipt", "checkpoint", "progress"):
        output = _absolute_path(outputs.get(key), f"{name}.outputs.{key}")
        if namespace_kind == "directory" and output.parent != namespace:
            _fail(f"{name}.outputs.{key} escaped namespace")
    if namespace_kind == "prefix":
        expected_outputs = {
            "training_receipt": str(namespace) + "-training.json",
            "checkpoint": str(namespace) + "-checkpoint.pt",
            "progress": str(namespace) + "-training-progress.json",
        }
        if {key: outputs[key] for key in expected_outputs} != expected_outputs:
            _fail(f"{name}.prefix outputs drift")
    checkpoint = _mapping(plan.get("checkpoint"), f"{name}.checkpoint")
    _exact(checkpoint, "schema", CHECKPOINT_SCHEMA, f"{name}.checkpoint")
    _exact(checkpoint, "path", outputs["checkpoint"], f"{name}.checkpoint")
    _exact(checkpoint, "update", UPDATES, f"{name}.checkpoint")
    _exact(checkpoint, "observed", status == "bound_complete", f"{name}.checkpoint")
    if status != "bound_complete":
        if checkpoint.get("sha256") is not None or checkpoint.get("bytes") is not None:
            _fail(f"{name}.missing checkpoint cannot carry observed identity")
        if plan.get("receipt") is not None:
            _fail(f"{name}.missing training plan cannot carry a receipt")
        _mapping(plan.get("receipt_source"), f"{name}.receipt_source")
    else:
        receipt = _mapping(plan.get("receipt"), f"{name}.receipt")
        _exact(receipt, "schema", TRAINING_SCHEMA, f"{name}.receipt")
        _exact(receipt, "path", outputs["training_receipt"], f"{name}.receipt")
        _sha(receipt.get("sha256"), f"{name}.receipt.sha256")
        _strict_int(receipt.get("bytes"), f"{name}.receipt.bytes", 1)
        _exact(checkpoint, "observed", True, f"{name}.checkpoint")
        _sha(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")
        _strict_int(checkpoint.get("bytes"), f"{name}.checkpoint.bytes", 1)


def _validate_case_plan(plan: Mapping[str, Any], *, root: Path, manifest_path: str, manifest_sha256: str) -> None:
    name = f"plans[{plan.get('ordinal', '?')}]"
    seed = _strict_int(plan.get("seed"), f"{name}.seed")
    if seed not in SEEDS:
        _fail(f"{name}.seed is outside exact seed set")
    case_id = _string(plan.get("case_id"), f"{name}.case_id")
    if CASE_ID_RE.fullmatch(case_id) is None:
        _fail(f"{name}.case_id is invalid")
    _exact(plan, "model", MODEL, name)
    _exact(plan, "hidden", HIDDEN, name)
    _exact(plan, "updates", UPDATES, name)
    _exact(plan, "parameter_count", PARAMETER_COUNT, name)
    _exact(plan, "manifest_sha256", manifest_sha256, name)
    _exact(plan, "launch_allowed", False, name)
    _exact(plan, "terminal_receipt_observed", False, name)
    _zero_credit(plan, name)
    status = plan.get("status")
    if status not in {"dry_run_ready", "blocked_missing_training_receipt"}:
        _fail(f"{name}.status is invalid")
    nonce = _string(plan.get("namespace_nonce"), f"{name}.namespace_nonce")
    if NONCE_RE.fullmatch(nonce) is None:
        _fail(f"{name}.namespace_nonce is invalid")
    namespace = _absolute_path(plan.get("output_namespace"), f"{name}.output_namespace")
    marker = f"case{int(plan.get('case_index')):02d}-{_slug(case_id)}-seed{seed}-full835-"
    if not namespace.name.startswith("f3-graph-residual500-hidden16-currentmanifest-case-matrix-") or marker not in namespace.name or not namespace.name.endswith(nonce):
        _fail(f"{name}.output_namespace is not bound to case/seed/full835/nonce")
    _exact(plan, "cwd", str(root), name)
    command = plan.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        _fail(f"{name}.command must be a non-empty argv")
    env = _mapping(plan.get("env_overrides"), f"{name}.env_overrides")
    _exact(env, "CUDA_VISIBLE_DEVICES", str(int(plan["ordinal"]) % GPU_COUNT), f"{name}.env_overrides")
    _exact(env, "PYTHONDONTWRITEBYTECODE", "1", f"{name}.env_overrides")
    _exact(plan, "command_sha256", _command_digest(command, cwd=root, env=dict(env)), name)
    for flag, value in (("--manifest", manifest_path), ("--case-id", case_id), ("--maximum-steps", str(TRANSITIONS))):
        if command.count(flag) != 1 or command[command.index(flag) + 1] != value:
            _fail(f"{name}.command {flag} identity drifts")
    if "--diagnostic" not in command:
        _fail(f"{name}.command must remain diagnostic-only")
    outputs = _mapping(plan.get("outputs"), f"{name}.outputs")
    for key in ("evaluation", "trajectory", "progress", "validator", "artifact_identity", "trajectory_metadata"):
        output = _absolute_path(outputs.get(key), f"{name}.outputs.{key}")
        if output.parent != namespace:
            _fail(f"{name}.outputs.{key} escaped namespace")
    process_proof = _absolute_path(outputs.get("process_proof"), f"{name}.outputs.process_proof")
    if process_proof.parent != root / "reports" or "GRAPH-RESIDUAL" not in process_proof.name:
        _fail(f"{name}.outputs.process_proof escaped graph_residual report scope")
    checkpoint = _mapping(plan.get("checkpoint"), f"{name}.checkpoint")
    _exact(checkpoint, "schema", CHECKPOINT_SCHEMA, f"{name}.checkpoint")
    receipt = plan.get("training_receipt")
    if status == "blocked_missing_training_receipt":
        if receipt is not None:
            _fail(f"{name}.blocked plan must not contain a training receipt")
        if checkpoint.get("observed") is not False:
            _fail(f"{name}.blocked plan checkpoint cannot be observed")
    else:
        _mapping(receipt, f"{name}.training_receipt")
        if checkpoint.get("observed") is not True:
            _fail(f"{name}.ready plan must bind an observed checkpoint identity")


def _identity_records(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for plan in report["training_plans"]:
        records.append(
            {
                "kind": "training",
                "job_id": plan["job_id"],
                "seed": plan["seed"],
                "namespace": plan["output_namespace"],
                "nonce": plan["namespace_nonce"],
                "command_sha256": plan["command_sha256"],
            }
        )
    for plan in report["plans"]:
        records.append(
            {
                "kind": "case",
                "job_id": plan["job_id"],
                "case_id": plan["case_id"],
                "seed": plan["seed"],
                "namespace": plan["output_namespace"],
                "nonce": plan["namespace_nonce"],
                "command_sha256": plan["command_sha256"],
            }
        )
    return records


def validate_report(report: Mapping[str, Any]) -> None:
    """Fail-closed validation of a generated report without opening sources."""

    _exact(report, "schema", SCHEMA, "report")
    _exact(report, "report_id", REPORT_ID, "report")
    status = report.get("status")
    if status not in {"dry_run_matrix_ready", "blocked_fail_closed"}:
        _fail("report.status is invalid")
    source_bound = report.get("source_bound")
    if type(source_bound) is not bool:
        _fail("report.source_bound must be boolean")
    _exact(report, "fail_closed", not source_bound, "report")
    _exact(report, "status", "dry_run_matrix_ready" if source_bound else "blocked_fail_closed", "report")
    _zero_credit(report, "report")
    _string(report.get("observed_at_utc"), "report.observed_at_utc")
    _exact(report, "formal_training_runs_expected", len(SEEDS), "report")
    for key in ("formal_training_runs_counted", "t1_case_runs_counted", "t2_macro_families_counted"):
        _exact(report, key, 0, "report")

    expected = _mapping(report.get("expected_contract"), "report.expected_contract")
    _exact(expected, "model_kind", MODEL, "report.expected_contract")
    _exact(expected, "hidden", HIDDEN, "report.expected_contract")
    _exact(expected, "updates", UPDATES, "report.expected_contract")
    _exact(expected, "parameter_count", PARAMETER_COUNT, "report.expected_contract")
    _exact(expected, "seeds", list(SEEDS), "report.expected_contract")
    _exact(expected, "case_count", EXPECTED_CASE_COUNT, "report.expected_contract")
    _exact(expected, "case_seed_job_count", EXPECTED_CASE_COUNT * len(SEEDS), "report.expected_contract")
    _exact(expected, "total_planned_jobs", len(SEEDS) + EXPECTED_CASE_COUNT * len(SEEDS), "report.expected_contract")
    _exact(expected, "transitions", TRANSITIONS, "report.expected_contract")
    _exact(expected, "frames", FRAMES, "report.expected_contract")
    _exact(expected, "zero_credit_only", True, "report.expected_contract")
    if dict(expected["shared_config"]) != REFERENCE_SHARED_CONFIG:
        _fail("report.expected_contract.shared_config drifts")

    manifest = _mapping(report.get("manifest"), "report.manifest")
    manifest_sha = _sha(manifest.get("canonical_sha256"), "report.manifest.canonical_sha256")
    _exact(manifest, "case_count", EXPECTED_CASE_COUNT, "report.manifest")
    raw = _mapping(manifest.get("raw"), "report.manifest.raw")
    _absolute_path(raw.get("path"), "report.manifest.raw.path")
    _strict_int(raw.get("bytes"), "report.manifest.raw.bytes", 1)
    _sha(raw.get("sha256"), "report.manifest.raw.sha256")
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        _fail("report.cases must contain exactly 32 cases")
    case_ids: set[str] = set()
    for item in cases:
        case = _mapping(item, "report.cases[]")
        case_id = _string(case.get("case_id"), "report.cases[].case_id")
        if CASE_ID_RE.fullmatch(case_id) is None or case_id in case_ids:
            _fail("report case identifiers are invalid or duplicated")
        case_ids.add(case_id)

    training_plans = report.get("training_plans")
    if not isinstance(training_plans, list) or len(training_plans) != len(SEEDS):
        _fail("report.training_plans must contain exactly three plans")
    training_by_seed: dict[int, Mapping[str, Any]] = {}
    namespaces: set[str] = set()
    nonces: set[str] = set()
    commands: set[str] = set()
    plan_date = _string(report.get("plan_date"), "report.plan_date")
    if DATE_RE.fullmatch(plan_date) is None:
        _fail("report.plan_date is invalid")
    for item in training_plans:
        plan = _mapping(item, "report.training_plans[]")
        _validate_training_plan(plan, root=Path(report["root"]), manifest_sha256=manifest_sha, plan_date=plan_date)
        seed = int(plan["seed"])
        if seed in training_by_seed:
            _fail("training plan seed coverage is duplicated")
        training_by_seed[seed] = plan
        for key, collection in (("output_namespace", namespaces), ("namespace_nonce", nonces), ("command_sha256", commands)):
            value = str(plan[key])
            if value in collection:
                _fail(f"training plan {key} identity is duplicated")
            collection.add(value)
    if set(training_by_seed) != set(SEEDS):
        _fail("training plan seed coverage is not exactly 17, 29, 43")

    plans = report.get("plans")
    if not isinstance(plans, list) or len(plans) != EXPECTED_CASE_COUNT * len(SEEDS):
        _fail("report.plans must contain exactly 96 case plans")
    combinations: set[tuple[str, int]] = set()
    for item in plans:
        plan = _mapping(item, "report.plans[]")
        _validate_case_plan(plan, root=Path(report["root"]), manifest_path=str(raw["path"]), manifest_sha256=manifest_sha)
        case_id = str(plan["case_id"])
        seed = int(plan["seed"])
        if case_id not in case_ids:
            _fail("case plan references a case outside the current manifest")
        if seed not in training_by_seed:
            _fail("case plan references a seed outside the training plan")
        combination = (case_id, seed)
        if combination in combinations:
            _fail("case plan case x seed identity is duplicated")
        combinations.add(combination)
        for key, collection in (("output_namespace", namespaces), ("namespace_nonce", nonces), ("command_sha256", commands)):
            value = str(plan[key])
            if value in collection:
                _fail(f"matrix {key} identity is duplicated")
            collection.add(value)
        expected_status = "dry_run_ready" if training_by_seed[seed]["status"] == "bound_complete" else "blocked_missing_training_receipt"
        _exact(plan, "status", expected_status, f"case plan {case_id}/seed{seed}")
    if combinations != {(case_id, seed) for case_id in case_ids for seed in SEEDS}:
        _fail("report does not provide exact 32-case x 3-seed coverage")

    training_receipts = _mapping(report.get("training_receipts"), "report.training_receipts")
    _exact(training_receipts, "required_count", len(SEEDS), "report.training_receipts")
    observed_training = sum(plan["status"] == "bound_complete" for plan in training_plans)
    _exact(training_receipts, "observed_count", observed_training, "report.training_receipts")
    _exact(training_receipts, "missing_count", len(SEEDS) - observed_training, "report.training_receipts")
    _exact(
        training_receipts,
        "status",
        "complete" if observed_training == len(SEEDS) else "running_or_missing_or_rejected_current_manifest_receipts",
        "report.training_receipts",
    )
    terminal = _mapping(report.get("terminal_receipts"), "report.terminal_receipts")
    _exact(terminal, "required_count", EXPECTED_CASE_COUNT * len(SEEDS), "report.terminal_receipts")
    _exact(terminal, "observed_count", 0, "report.terminal_receipts")
    _exact(terminal, "missing_count", EXPECTED_CASE_COUNT * len(SEEDS), "report.terminal_receipts")
    _exact(terminal, "status", "missing_real_terminal_receipts", "report.terminal_receipts")

    coverage = _mapping(report.get("coverage"), "report.coverage")
    _exact(coverage, "cases", EXPECTED_CASE_COUNT, "report.coverage")
    _exact(coverage, "seeds", list(SEEDS), "report.coverage")
    _exact(coverage, "case_jobs", EXPECTED_CASE_COUNT * len(SEEDS), "report.coverage")
    _exact(coverage, "training_jobs", len(SEEDS), "report.coverage")
    _exact(coverage, "total_jobs", len(SEEDS) + EXPECTED_CASE_COUNT * len(SEEDS), "report.coverage")
    _exact(coverage, "unique_namespaces", len(namespaces), "report.coverage")
    _exact(coverage, "unique_nonces", len(nonces), "report.coverage")
    _exact(coverage, "unique_command_identities", len(commands), "report.coverage")
    _exact(report, "matrix_sha256", _canonical_sha(_identity_records(report)), "report")

    blocked_reasons = report.get("blocked_reasons")
    if not isinstance(blocked_reasons, list) or any(not isinstance(item, str) for item in blocked_reasons):
        _fail("report.blocked_reasons must be an array of strings")
    if source_bound and blocked_reasons:
        _fail("bound report cannot carry blocked reasons")
    if not source_bound and not blocked_reasons:
        _fail("blocked report must explain missing or rejected training receipts")
    errors = report.get("errors")
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        _fail("report.errors must be an array of strings")
    if source_bound and errors:
        _fail("bound report.errors must be empty")
    if not source_bound and not errors:
        _fail("blocked report.errors must not be empty")

    boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
    required_boundary = {
        "bounded_manifest_json_opened": True,
        "bounded_historical_matrix_json_opened": True,
        "bounded_training_receipt_json_opened": observed_training,
        "checkpoint_content_opened": False,
        "case_hdf5_content_opened": False,
        "trajectory_content_opened": False,
        "evaluation_content_opened": False,
        "progress_content_opened": False,
        "checkpoint_lstat_performed": False,
        "case_hdf5_lstat_performed": False,
        "gpu_started": False,
        "queue_started": False,
        "runtime_started": False,
    }
    if dict(boundary) != required_boundary:
        _fail("report.input_boundary drifts")
    side_effects = _mapping(report.get("side_effects"), "report.side_effects")
    required_side_effects = {
        "processes_started": 0,
        "processes_stopped": 0,
        "processes_restarted": 0,
        "registry_writes": 0,
        "ledger_writes": 0,
        "denominator_writes": 0,
        "gate_writes": 0,
        "completion_writes": 0,
        "plan_writes": 0,
    }
    if dict(side_effects) != required_side_effects:
        _fail("report.side_effects drifts")


def build_report(
    *,
    root: Path | str,
    manifest: Path | str,
    historical_matrix: Path | str,
    plan_date: str,
    python_executable: Path | str | None = None,
    seed_receipts: Mapping[int, Path | str] | None = None,
    seed_statuses: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    root_path = _absolute_path(root, "root")
    manifest_path = _absolute_path(manifest, "manifest")
    historical_path = _absolute_path(historical_matrix, "historical_matrix")
    if DATE_RE.fullmatch(plan_date) is None:
        _fail("plan_date must be YYYYMMDD in the 20xx range")
    manifest_payload, manifest_source = _read_bounded_json(
        manifest_path, name="manifest", max_bytes=MAX_MANIFEST_BYTES
    )
    manifest_sha256 = _canonical_sha(manifest_payload)
    cases, manifest_meta = _validate_manifest(manifest_payload, source=manifest_source)
    historical_payload, historical_source = _read_bounded_json(
        historical_path, name="historical_matrix", max_bytes=MAX_JSON_BYTES
    )
    historical_meta = _validate_historical_matrix(
        historical_payload,
        source=historical_source,
        current_manifest_sha256=manifest_sha256,
    )
    python_path = _absolute_path(
        python_executable if python_executable is not None else root_path / ".venv" / "bin" / "python",
        "python_executable",
    )
    supplied = {} if seed_receipts is None else dict(seed_receipts)
    unknown_seeds = set(supplied) - set(SEEDS)
    if unknown_seeds:
        _fail(f"seed receipt map contains unsupported seeds: {sorted(unknown_seeds)}")
    statuses = {} if seed_statuses is None else dict(seed_statuses)
    unknown_status_seeds = set(statuses) - set(SEEDS)
    if unknown_status_seeds:
        _fail(f"seed status map contains unsupported seeds: {sorted(unknown_status_seeds)}")
    invalid_statuses = set(statuses.values()) - {"running", "missing", "terminal"}
    if invalid_statuses:
        _fail(f"seed status map contains unsupported states: {sorted(invalid_statuses)}")

    training_plans: list[dict[str, Any]] = []
    errors: list[str] = []
    for ordinal, seed in enumerate(SEEDS):
        explicit_path = None
        if seed in supplied:
            explicit_path = _absolute_path(supplied[seed], f"seed{seed}.training_receipt")
        plan = _training_plan(
            root=root_path,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            seed=seed,
            ordinal=ordinal,
            plan_date=plan_date,
            python_executable=python_path,
            explicit_receipt_path=explicit_path,
        )
        receipt_path = supplied.get(seed, plan["outputs"]["training_receipt"])
        expected_path = Path(plan["outputs"]["training_receipt"])
        status_hint = statuses.get(seed)
        if status_hint in {"running", "missing"}:
            plan["status"] = status_hint
            plan["receipt_observed"] = False
            plan["receipt"] = None
            plan["receipt_source"] = _status_source(expected_path, status_hint)
            errors.append(f"seed{seed} current-manifest training receipt is explicitly {status_hint}; no terminal receipt was opened")
            training_plans.append(plan)
            continue
        try:
            candidate_path = _absolute_path(receipt_path, f"seed{seed}.training_receipt")
            if candidate_path != expected_path:
                _fail(f"seed{seed} receipt path must equal planned namespace output")
            payload, source = _read_bounded_json(
                candidate_path,
                name=f"seed{seed}.training_receipt",
                max_bytes=MAX_JSON_BYTES,
            )
            identity = _validate_training_receipt(payload, source, plan=plan)
            plan["status"] = "bound_complete"
            plan["receipt_observed"] = True
            plan["receipt"] = {
                "schema": identity["schema"],
                "path": identity["path"],
                "bytes": identity["bytes"],
                "sha256": identity["sha256"],
                "opened": True,
            }
            plan["receipt_source"] = source
            plan["checkpoint"] = dict(identity["checkpoint"])
        except (MatrixError, OSError, TypeError, ValueError) as error:
            source = _missing_source(expected_path, error)
            plan["status"] = "rejected" if source.get("exists") is True else "missing"
            plan["receipt_observed"] = False
            plan["receipt"] = None
            plan["receipt_source"] = source
            errors.append(f"seed{seed} current-manifest training receipt: {error}")
        training_plans.append(plan)

    training_by_seed = {int(plan["seed"]): plan for plan in training_plans}
    case_plans: list[dict[str, Any]] = []
    ordinal = 0
    for case in cases:
        for seed in SEEDS:
            case_plans.append(
                _case_plan(
                    root=root_path,
                    manifest_path=manifest_path,
                    manifest_sha256=manifest_sha256,
                    case=case,
                    training=training_by_seed[seed],
                    ordinal=ordinal,
                    plan_date=plan_date,
                    python_executable=python_path,
                )
            )
            ordinal += 1
    training_bound = all(plan["status"] == "bound_complete" for plan in training_plans)
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "plan_date": plan_date,
        "status": "dry_run_matrix_ready" if training_bound else "blocked_fail_closed",
        "fail_closed": not training_bound,
        "source_bound": training_bound,
        "root": str(root_path),
        **ZERO_CREDIT,
        "formal_training_runs_expected": len(SEEDS),
        "formal_training_runs_counted": 0,
        "t1_case_runs_counted": 0,
        "t2_macro_families_counted": 0,
        "expected_contract": {
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "parameter_count": PARAMETER_COUNT,
            "seeds": list(SEEDS),
            "shared_config": dict(REFERENCE_SHARED_CONFIG),
            "case_count": EXPECTED_CASE_COUNT,
            "case_seed_job_count": EXPECTED_CASE_COUNT * len(SEEDS),
            "total_planned_jobs": len(SEEDS) + EXPECTED_CASE_COUNT * len(SEEDS),
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "bounded_json_only": True,
            "current_manifest_required": True,
            "real_training_receipts_required": True,
            "zero_credit_only": True,
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
        "historical_training_matrix": historical_meta,
        "training_plans": training_plans,
        "cases": cases,
        "plans": case_plans,
        "coverage": {
            "cases": EXPECTED_CASE_COUNT,
            "seeds": list(SEEDS),
            "case_jobs": len(case_plans),
            "training_jobs": len(training_plans),
            "total_jobs": len(case_plans) + len(training_plans),
            "unique_namespaces": len({item["output_namespace"] for item in training_plans + case_plans}),
            "unique_nonces": len({item["namespace_nonce"] for item in training_plans + case_plans}),
            "unique_command_identities": len({item["command_sha256"] for item in training_plans + case_plans}),
            "gpu_slots": {
                str(gpu): sum(item["gpu_index"] == gpu for item in case_plans)
                + sum(int(item["ordinal"]) % GPU_COUNT == gpu for item in training_plans)
                for gpu in range(GPU_COUNT)
            },
        },
        "training_receipts": {
            "required_count": len(SEEDS),
            "observed_count": sum(plan["status"] == "bound_complete" for plan in training_plans),
            "missing_count": sum(plan["status"] != "bound_complete" for plan in training_plans),
            "status": "complete" if training_bound else "running_or_missing_or_rejected_current_manifest_receipts",
        },
        "terminal_receipts": {
            "required_count": len(case_plans),
            "observed_count": 0,
            "missing_count": len(case_plans),
            "status": "missing_real_terminal_receipts",
            "paths": [],
            "note": "This planner did not launch any case rollout; every future case needs independent terminal and validator evidence.",
        },
        "matrix_sha256": "",
        "input_boundary": {
            "bounded_manifest_json_opened": True,
            "bounded_historical_matrix_json_opened": True,
            "bounded_training_receipt_json_opened": sum(plan["status"] == "bound_complete" for plan in training_plans),
            "checkpoint_content_opened": False,
            "case_hdf5_content_opened": False,
            "trajectory_content_opened": False,
            "evaluation_content_opened": False,
            "progress_content_opened": False,
            "checkpoint_lstat_performed": False,
            "case_hdf5_lstat_performed": False,
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
            {"check": "current_canonical_manifest", "passed": True, "observed": manifest_sha256},
            {"check": "historical_graph_residual_config", "passed": True, "observed": dict(REFERENCE_SHARED_CONFIG)},
            {"check": "exact_32_case_manifest", "passed": True, "observed": EXPECTED_CASE_COUNT},
            {"check": "exact_three_seed_training_plan", "passed": True, "observed": list(SEEDS)},
            {"check": "unique_namespace_nonce_command_identity", "passed": True, "observed": len(case_plans) + len(training_plans)},
            {"check": "diagnostic_only_zero_credit", "passed": True, "observed": True},
            {"check": "current_training_receipts", "passed": training_bound, "observed": sum(plan["status"] == "bound_complete" for plan in training_plans)},
            {"check": "real_terminal_receipts", "passed": False, "observed": 0},
        ],
        "errors": errors,
        "blocked_reasons": [] if training_bound else [
            "current-manifest graph_residual hidden16 training receipts are incomplete or rejected"
        ],
        "interpretation": "This is a bounded current-manifest identity and dry-run planning matrix only. It is never runtime evidence, never authorizes launch, and cannot increase formal training, T1/T2, qualification, denominator, registry, ledger, gate, or completion state.",
    }
    report["matrix_sha256"] = _canonical_sha(_identity_records(report))
    validate_report(report)
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    training_receipts = report["training_receipts"]
    terminal = report["terminal_receipts"]
    lines = [
        "# F3 graph_residual hidden16 current-manifest case matrix",
        "",
        f"- 状态：`{report['status']}`；source-bound=`{report['source_bound']}`；fail-closed=`{report['fail_closed']}`",
        f"- 覆盖：training `{coverage['training_jobs']}` + case `{coverage['cases']} × {len(SEEDS)} = {coverage['case_jobs']}`，总计划 `{coverage['total_jobs']}`",
        f"- 唯一性：namespace `{coverage['unique_namespaces']}/{coverage['total_jobs']}`，nonce `{coverage['unique_nonces']}/{coverage['total_jobs']}`，command SHA `{coverage['unique_command_identities']}/{coverage['total_jobs']}`",
        "- 运行权限：所有 training/case plan 均 `launch_allowed=false`；diagnostic-only；formal/T1/T2/qualification=false；credit=0",
        f"- current-manifest training receipts：需要 `{training_receipts['required_count']}`，已绑定 `{training_receipts['observed_count']}`，缺失/拒绝 `{training_receipts['missing_count']}`",
        f"- terminal receipts：需要 `{terminal['required_count']}`，当前 `{terminal['observed_count']}`，缺失 `{terminal['missing_count']}`；本轮未启动 GPU/queue/runtime",
        "",
        "## 绑定来源",
        "",
        f"- current canonical manifest：`{report['manifest']['canonical_sha256']}`；raw bytes `{report['manifest']['raw']['bytes']}`",
        f"- historical graph_residual matrix：`{report['historical_training_matrix']['source']['path']}`；只作为 hidden16/500-update/config reference，不冒充 current receipt",
        "- checkpoint、case HDF5、trajectory、evaluation、progress 均未打开、未 stat、未 hash",
        "",
        "## Training identity",
        "",
        "| seed | 状态 | run_id | receipt | checkpoint |",
        "|---:|---|---|---|---|",
    ]
    for item in report["training_plans"]:
        checkpoint = item["checkpoint"]
        lines.append(
            f"| {item['seed']} | `{item['status']}` | `{item['run_id']}` | `{'observed' if item['receipt_observed'] else 'missing'}` | `{'observed' if checkpoint['observed'] else 'planned-only'}` |"
        )
    lines.extend(
        [
            "",
            "## 32-case coverage",
            "",
            "| # | case | split | role | HDF5 metadata bytes |",
            "|---:|---|---|---|---:|",
        ]
    )
    for case in report["cases"]:
        lines.append(
            f"| {case['index']:02d} | `{case['case_id']}` | `{case['split']}` | `{case['evaluation_role']}` | {case['hdf5_bytes']} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "这是只读 bounded JSON identity binding 和 dry-run matrix。缺少真实 current-manifest training receipt 时整体 fail-closed；即使 training identity 完整，96 个 case 仍等待独立自然退出、evaluation、HDF5 validator、artifact identity 与 process proof，不能直接计入 Core。",
            "",
        ]
    )
    return "\n".join(lines)


def _safe_output_path(path: Path | str, *, root: Path, suffix: str) -> Path:
    candidate = _absolute_path(path, "output")
    reports = root / "reports"
    if candidate.parent != reports:
        _fail("output must stay in the graph_residual report directory")
    if candidate.suffix != suffix:
        _fail(f"output must use {suffix} suffix")
    if not candidate.name.startswith("F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-CASE-MATRIX-"):
        _fail("output name must remain graph_residual-specific")
    return candidate


def _write_text(text: str, path: Path | str, *, root: Path, suffix: str) -> None:
    candidate = _safe_output_path(path, root=root, suffix=suffix)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(candidate.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{candidate.name}.", dir=str(candidate.parent), text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, candidate)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _parse_seed_receipts(values: Sequence[str]) -> dict[int, Path | str]:
    result: dict[int, Path | str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError("--seed-receipt must use SEED=PATH")
        seed_text, path = item.split("=", 1)
        seed = int(seed_text)
        if seed in result:
            raise ValueError(f"duplicate seed receipt: {seed}")
        if seed not in SEEDS:
            raise ValueError(f"unsupported seed receipt: {seed}")
        result[seed] = path
    return result


def _parse_seed_statuses(values: Sequence[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError("--seed-status must use SEED=running|missing|terminal")
        seed_text, status = item.split("=", 1)
        seed = int(seed_text)
        if seed in result:
            raise ValueError(f"duplicate seed status: {seed}")
        if seed not in SEEDS:
            raise ValueError(f"unsupported seed status: {seed}")
        if status not in {"running", "missing", "terminal"}:
            raise ValueError(f"unsupported seed status: {status}")
        result[seed] = status
    return result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(LAB_ROOT))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--historical-matrix", default=str(DEFAULT_HISTORICAL_MATRIX))
    parser.add_argument("--seed-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--seed-status", action="append", default=[], metavar="SEED=running|missing|terminal")
    parser.add_argument("--plan-date", default="20260929")
    parser.add_argument("--python-executable")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--verify-report")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.verify_report:
            report_path = _absolute_path(args.verify_report, "verify_report")
            payload, source = _read_bounded_json(report_path, name="matrix_report", max_bytes=MAX_REPORT_BYTES)
            validate_report(payload)
            print(json.dumps({"status": "verified", "report": source["path"], "report_sha256": source["sha256"]}, sort_keys=True))
            return 0
        seed_receipts = _parse_seed_receipts(args.seed_receipt)
        seed_statuses = _parse_seed_statuses(args.seed_status)
        root = _absolute_path(args.root, "root")
        report = build_report(
            root=root,
            manifest=args.manifest,
            historical_matrix=args.historical_matrix,
            plan_date=args.plan_date,
            python_executable=args.python_executable,
            seed_receipts=seed_receipts,
            seed_statuses=seed_statuses,
        )
        output = _safe_output_path(args.output, root=root, suffix=".json")
        _write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", output, root=root, suffix=".json")
        markdown = None
        if args.markdown_output:
            markdown = _safe_output_path(args.markdown_output, root=root, suffix=".md")
            _write_text(render_markdown(report), markdown, root=root, suffix=".md")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "source_bound": report["source_bound"],
                    "output": str(output),
                    "markdown_output": str(markdown) if markdown else None,
                    "training_receipts_observed": report["training_receipts"]["observed_count"],
                    "case_jobs": report["coverage"]["case_jobs"],
                    "credit": report["credit"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (MatrixError, OSError, TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
