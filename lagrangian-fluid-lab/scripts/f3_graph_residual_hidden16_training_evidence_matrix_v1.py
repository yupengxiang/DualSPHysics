#!/usr/bin/env python3
"""Bind an independent F3 graph_residual/hidden16 three-seed matrix.

The adapter accepts only bounded JSON receipts and a compact JSON reference
matrix.  It never opens a checkpoint, case HDF5, trajectory, progress file,
manifest, or solver output.  A successful bind is diagnostic-only: it cannot
authorize formal runs, T1/T2, qualification, denominators, registries,
ledgers, or credit.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Mapping, Sequence


SCHEMA = "core.f3.graph_residual.hidden16.training_evidence_matrix.v1"
REFERENCE_SCHEMA = "core.f3.graph_residual.hidden16.training_matrix.v1"
TRAINING_SCHEMA = "core.training.v1"
EVIDENCE_SCHEMA = "core.training.evidence.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
INITIALIZATION_SCHEMA = "core.training.initialization_evidence.v1"
NORMALIZATION_SCHEMA = "core.training.normalization_evidence.v1"
PRIOR_SCHEMA = "core.training.prior_evidence.v1"
REPORT_ID = "f3-graph-residual-hidden16-training-evidence-matrix-v1"
LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL_KIND = "graph_residual"
HIDDEN = 16
UPDATES = 500
PARAMETER_COUNT = 6086
NORMALIZATION_TRANSITIONS = 16
PRIOR_ROWS = 17_280_000
MAX_JSON_BYTES = 1 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SOURCE_METADATA_KEYS = frozenset({"path", "exists", "opened", "bytes", "sha256", "schema"})
DANGEROUS_OUTPUT_SUFFIXES = frozenset({".bin", ".ckpt", ".h5", ".hdf5", ".npy", ".npz", ".pt", ".pth"})
DANGEROUS_OUTPUT_TOKENS = (
    "checkpoint",
    "trajectory",
    "progress",
    "manifest",
    "ledger",
    "registry",
    "gate",
    "receipt",
)
REPORT_ENVELOPE_KEYS = frozenset(
    {
        "schema",
        "report_id",
        "observed_at_utc",
        "status",
        "fail_closed",
        "source_bound",
        "diagnostic_only",
        "formal",
        "formal_eligible",
        "qualification",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification_credit",
        "credit",
        "formal_training_runs_expected",
        "formal_training_runs_counted",
        "training_evidence_counted_as_formal_runs",
        "t1_case_runs_counted",
        "t2_macro_families_counted",
        "expected_contract",
        "reference_training_matrix",
        "runs",
        "shared_config",
        "checks",
        "errors",
        "authorization",
        "input_boundary",
        "side_effects",
        "scope_note",
    }
)
SCOPE_NOTE = "bounded JSON receipt/schema/hash metadata only; diagnostic and non-authorizing"
PLACEHOLDER_WORDS = (
    "placeholder",
    "dummy",
    "todo",
    "changeme",
    "unknown",
    "example",
)
OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
DEFAULT_REFERENCE = Path(
    "reports/F3-GRAPH-RESIDUAL-HIDDEN16-SEEDS17-29-43-TRAINING-2026-09-28.json"
)
DEFAULT_RECEIPTS = {
    seed: Path(f"/tmp/f3-graph-residual500-hidden16-seed{seed}-20260928-training.json")
    for seed in SEEDS
}

STATIC_CONFIG: dict[str, Any] = {
    "centers_per_update": 256,
    "checkpoint_every": 500,
    "evaluate_milestones": True,
    "gradient_clipping": None,
    "hidden": HIDDEN,
    "history_states": 1,
    "initialization": "core.paired_initialization.common_encoder_head.v1",
    "learning_rate": 0.001,
    "log_every": 100,
    "manifest_formal_release": False,
    "max_neighbors": 192,
    "milestone_evaluation_mode": "in_process",
    "model_kind": MODEL_KIND,
    "normalization_source_split": "train",
    "optimizer": "Adam",
    "radius_over_h": 2.0,
    "target_normalization": "raw_dual_increment_train_shared",
    "updates": UPDATES,
    "validation_case_count": 4,
    "validation_centers": 256,
    "validation_every": 1000,
    "validation_family_counts": {"F3": 4},
    "validation_formal_eligible": False,
    "validation_transition_count": 4,
}
DYNAMIC_CONFIG_KEYS = {"manifest_sha256", "paired_seed", "run_id", "sampler_seed", "seed"}
REFERENCE_SHARED_CONFIG: dict[str, Any] = copy.deepcopy(STATIC_CONFIG)
REFERENCE_SHARED_CONFIG.update(
    {
        "normalization_selection_policy": "deterministic_evenly_spaced_train_transitions_v1",
        "normalization_target_reference": "raw_dual_increment_train_shared",
        "normalization_transitions": NORMALIZATION_TRANSITIONS,
    }
)


class MatrixError(ValueError):
    """A malformed, incomplete, drifting, or unsafe evidence input."""


def _expected_run_id(seed: int) -> str:
    """Return the exact run-id emitted by the hidden16 residual trainer."""

    return f"f3-graph-residual500-hidden16-seed{seed}-20260928"


def _fail(message: str) -> None:
    raise MatrixError(f"fail-closed: {message}")


def _reject_json_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _walk_json(value: Any, name: str = "value") -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(f"{name} has a non-string key")
            _walk_json(item, f"{name}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _walk_json(item, f"{name}[{index}]")
        return
    _fail(f"{name} has unsupported type {type(value).__name__}")


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


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be boolean")
    return value


def _finite_nonnegative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{name} must be a finite nonnegative number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        _fail(f"{name} must be a finite nonnegative number")
    return number


def _not_placeholder(value: str, name: str) -> str:
    lowered = value.lower()
    if any(word in lowered for word in PLACEHOLDER_WORDS):
        _fail(f"{name} contains a placeholder marker")
    return value


def _sha256(value: Any, name: str) -> str:
    text = _string(value, name)
    if not SHA256_RE.fullmatch(text) or len(set(text)) == 1:
        _fail(f"{name} must be a non-placeholder lowercase SHA-256")
    return text


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def identity_sha256(value: Any) -> str:
    """Return the stable SHA-256 identity of a JSON metadata projection."""

    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _resolve_path(root: Path, value: Path | str) -> Path:
    if not isinstance(value, (Path, str)):
        _fail(f"input path must be a path string: {value!r}")
    path = Path(value).expanduser()
    if ".." in path.parts:
        _fail(f"input path must not contain parent traversal: {path}")
    return path if path.is_absolute() else Path(root) / path


def _reject_symlink_components(path: Path) -> None:
    """Reject symlinks before opening a path, including parent components."""

    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor or os.curdir)
    for component in absolute.parts[1:] if absolute.is_absolute() else absolute.parts:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as error:
            _fail(f"cannot inspect input path component {current}: {error}")
        if stat.S_ISLNK(info.st_mode):
            _fail(f"symlink path component is not accepted: {current}")


def _read_bounded_bytes(path: Path) -> bytes:
    """Read at most MAX_JSON_BYTES from a regular, no-follow file."""

    _reject_symlink_components(path)
    if not hasattr(os, "O_NOFOLLOW"):
        _fail("platform does not provide O_NOFOLLOW")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        _fail(f"cannot open bounded JSON input {path}: {error}")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            _fail(f"bounded JSON input must be a regular file: {path}")
        if info.st_size > MAX_JSON_BYTES:
            _fail(f"JSON input exceeds {MAX_JSON_BYTES} bytes: {path}")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_JSON_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                _fail(f"JSON input exceeds {MAX_JSON_BYTES} bytes while reading: {path}")
        return b"".join(chunks)
    except OSError as error:
        _fail(f"cannot read bounded JSON input {path}: {error}")
    finally:
        os.close(descriptor)


def _display_path(root: Path, path: Path) -> str:
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _source_ref(
    root: Path,
    path: Path,
    *,
    opened: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "path": _display_path(root, path),
        "exists": False,
        "opened": opened,
        "bytes": None,
        "sha256": None,
        "schema": None,
    }
    try:
        _reject_symlink_components(path)
        info = os.lstat(path)
        if stat.S_ISREG(info.st_mode):
            ref["exists"] = True
            ref["bytes"] = info.st_size
            # Only small JSON receipts are opened.  Declared checkpoint/HDF5
            # paths remain metadata-only even when a caller supplies them.
            if path.suffix.lower() == ".json" and info.st_size <= MAX_JSON_BYTES:
                raw = _read_bounded_bytes(path)
                ref["bytes"] = len(raw)
                ref["sha256"] = hashlib.sha256(raw).hexdigest()
    except (OSError, MatrixError):
        pass
    if error:
        ref["error"] = error
    return ref


def read_bounded_json(root: Path, value: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one strict, small JSON object; no other artifact type is opened."""

    path = _resolve_path(root, value)
    if path.suffix.lower() != ".json":
        _fail(f"only .json inputs are accepted: {path}")
    raw = _read_bounded_bytes(path)
    if not raw:
        _fail(f"empty JSON input: {path}")
    try:
        value_obj = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except MatrixError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"invalid UTF-8 JSON {path}: {error}")
    _walk_json(value_obj, str(path))
    payload = dict(_mapping(value_obj, str(path)))
    return payload, {
        "path": _display_path(root, path),
        "exists": True,
        "opened": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema": payload.get("schema"),
    }


def _validate_source_metadata(
    value: Any,
    expected_schema: str,
    name: str,
    *,
    allow_error: bool = False,
) -> bool:
    """Validate provenance emitted by read_bounded_json, without opening files."""

    source = _mapping(value, name)
    keys = set(source)
    if "error" in source:
        if not allow_error or keys != SOURCE_METADATA_KEYS | {"error"}:
            _fail(f"{name} error metadata is not allowed for a bound source")
        _string(source.get("error"), f"{name}.error")
        path = _string(source.get("path"), f"{name}.path")
        if path.lower().endswith(".json") is False or "://" in path or ".." in Path(path).parts:
            _fail(f"{name}.path is not a safe JSON path")
        if type(source.get("exists")) is not bool or source.get("opened") is not False:
            _fail(f"{name}.error metadata exists/opened markers drift")
        if source.get("bytes") is not None:
            _strict_int(source.get("bytes"), f"{name}.bytes")
            if source["bytes"] > MAX_JSON_BYTES:
                _fail(f"{name}.bytes exceeds bounded JSON limit")
        if source.get("sha256") is not None:
            _sha256(source.get("sha256"), f"{name}.sha256")
        if source.get("schema") is not None:
            _string(source.get("schema"), f"{name}.schema")
        return False
    if keys != SOURCE_METADATA_KEYS:
        _fail(f"{name} metadata keys are incomplete or unexpected")
    path = _string(source.get("path"), f"{name}.path")
    if path.lower().endswith(".json") is False or "://" in path or ".." in Path(path).parts:
        _fail(f"{name}.path is not a safe bounded JSON path")
    if source.get("exists") is not True or source.get("opened") is not True:
        _fail(f"{name}.exists/opened must be true for bound JSON")
    size = _strict_int(source.get("bytes"), f"{name}.bytes", 1)
    if size > MAX_JSON_BYTES:
        _fail(f"{name}.bytes exceeds bounded JSON limit")
    _sha256(source.get("sha256"), f"{name}.sha256")
    if source.get("schema") != expected_schema:
        _fail(f"{name}.schema must be {expected_schema}")
    return True


def _require_false(value: Mapping[str, Any], key: str, name: str) -> None:
    if key in value and value[key] is not False:
        _fail(f"{name}.{key} must be false")


def _require_zero(value: Mapping[str, Any], key: str, name: str) -> None:
    if key in value and (type(value[key]) is not int or value[key] != 0):
        _fail(f"{name}.{key} must be integer zero")


def _validate_zero_authority_markers(receipt: Mapping[str, Any], name: str) -> None:
    for key in ("formal", "formal_eligible", "qualification", "T1_numerical", "T2_macro", "T2_path"):
        _require_false(receipt, key, name)
    for key in ("credit", "qualification_credit"):
        _require_zero(receipt, key, name)
    config = _mapping(receipt.get("config"), f"{name}.config")
    if config.get("manifest_formal_release") is not False:
        _fail(f"{name}.config.manifest_formal_release must be false")
    if config.get("validation_formal_eligible") is not False:
        _fail(f"{name}.config.validation_formal_eligible must be false")


def _normalization_identity(normalization: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": normalization["schema"],
        "available_transition_count": normalization["available_transition_count"],
        "requested_maximum_transitions": normalization["requested_maximum_transitions"],
        "selected_transition_count": normalization["selected_transition_count"],
        "selection_policy": normalization["selection_policy"],
        "selection_seed": normalization["selection_seed"],
        "source_split": normalization["source_split"],
        "target_reference": normalization["target_reference"],
    }


def _prior_identity(prior: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": prior["schema"],
        "enabled": prior["enabled"],
        "history_complete": prior["history_complete"],
        "units": copy.deepcopy(prior["units"]),
        "execution_calls": prior["execution_calls"],
        "rows": prior["rows"],
        "finite": prior["finite"],
        "semantic": prior["semantic"],
        "dx_abs_max_m": prior["dx_abs_max_m"],
        "dv_abs_max_mps": prior["dv_abs_max_mps"],
        "dx_abs_sum_m": prior["dx_abs_sum_m"],
        "dv_abs_sum_mps": prior["dv_abs_sum_mps"],
        "last_update": copy.deepcopy(prior["last_update"]),
    }


def _validate_normalization(normalization: Mapping[str, Any], seed: int, name: str) -> dict[str, Any]:
    if normalization.get("schema") != NORMALIZATION_SCHEMA:
        _fail(f"{name}.normalization schema drifts")
    _strict_int(
        normalization.get("available_transition_count"),
        f"{name}.normalization.available_transition_count",
        NORMALIZATION_TRANSITIONS,
    )
    requested = _strict_int(
        normalization.get("requested_maximum_transitions"),
        f"{name}.normalization.requested_maximum_transitions",
        NORMALIZATION_TRANSITIONS,
    )
    selected = _strict_int(
        normalization.get("selected_transition_count"),
        f"{name}.normalization.selected_transition_count",
        NORMALIZATION_TRANSITIONS,
    )
    selection_seed = _strict_int(normalization.get("selection_seed"), f"{name}.normalization.selection_seed")
    if (
        requested != NORMALIZATION_TRANSITIONS
        or selected != NORMALIZATION_TRANSITIONS
        or normalization.get("selection_policy") != "deterministic_evenly_spaced_train_transitions_v1"
        or selection_seed != seed
        or normalization.get("source_split") != "train"
        or normalization.get("target_reference") != "raw_dual_increment_train_shared"
    ):
        _fail(f"{name}.normalization identity drifts")
    identity = _normalization_identity(normalization)
    return {"identity": identity, "identity_sha256": identity_sha256(identity)}


def _validate_prior(prior: Mapping[str, Any], name: str) -> dict[str, Any]:
    if prior.get("schema") != PRIOR_SCHEMA:
        _fail(f"{name}.residual_prior schema drifts")
    if type(prior.get("enabled")) is not bool or prior.get("enabled") is not True:
        _fail(f"{name}.residual_prior must be enabled with complete history")
    if type(prior.get("history_complete")) is not bool or prior.get("history_complete") is not True:
        _fail(f"{name}.residual_prior must be enabled with complete history")
    if prior.get("units") != {"displacement": "m", "delta_velocity": "m/s"}:
        _fail(f"{name}.residual_prior units drift")
    execution_calls = _strict_int(prior.get("execution_calls"), f"{name}.residual_prior.execution_calls")
    rows = _strict_int(prior.get("rows"), f"{name}.residual_prior.rows")
    if execution_calls != UPDATES or rows != PRIOR_ROWS:
        _fail(f"{name}.residual_prior execution/row identity drifts")
    if type(prior.get("finite")) is not bool or prior.get("finite") is not True:
        _fail(f"{name}.residual_prior.finite must be true")
    if prior.get("semantic") != (
        "graph_residual subtracts this SI prior before shared raw-target normalization; "
        "predictor adds it back"
    ):
        _fail(f"{name}.residual_prior.semantic drifts")
    last_update = _mapping(prior.get("last_update"), f"{name}.residual_prior.last_update")
    if _strict_int(last_update.get("update"), f"{name}.residual_prior.last_update.update") != UPDATES:
        _fail(f"{name}.residual_prior.last_update.update drifts")
    _not_placeholder(_string(last_update.get("case_id"), f"{name}.residual_prior.last_update.case_id"),
                     f"{name}.residual_prior.last_update.case_id")
    _strict_int(last_update.get("frame"), f"{name}.residual_prior.last_update.frame")
    for key in ("dx_abs_max_m", "dv_abs_max_mps", "dx_abs_sum_m", "dv_abs_sum_mps"):
        _finite_nonnegative(prior.get(key), f"{name}.residual_prior.{key}")
    identity = _prior_identity(prior)
    return {"identity": identity, "identity_sha256": identity_sha256(identity)}


def _validate_training_receipt(receipt: Mapping[str, Any], seed: int) -> dict[str, Any]:
    name = f"training[{seed}]"
    _walk_json(receipt, name)
    if receipt.get("schema") != TRAINING_SCHEMA:
        _fail(f"{name}.schema must be {TRAINING_SCHEMA}")
    if receipt.get("evidence_status") != "complete":
        _fail(f"{name}.evidence_status must be complete")
    if receipt.get("status") not in (None, "completed"):
        _fail(f"{name}.status must be completed when present")
    if receipt.get("model_kind") != MODEL_KIND:
        _fail(f"{name}.model_kind must be {MODEL_KIND}")
    receipt_seed = _strict_int(receipt.get("seed"), f"{name}.seed")
    completed_updates = _strict_int(receipt.get("completed_updates"), f"{name}.completed_updates")
    if receipt_seed != seed or completed_updates != UPDATES:
        _fail(f"{name} seed/updates drift")
    if "requested_updates" in receipt and _strict_int(receipt["requested_updates"], f"{name}.requested_updates") != UPDATES:
        _fail(f"{name}.requested_updates drifts")
    parameter_count = _strict_int(receipt.get("parameter_count"), f"{name}.parameter_count", 1)
    if parameter_count != PARAMETER_COUNT:
        _fail(f"{name}.parameter_count must be {PARAMETER_COUNT}")
    if receipt.get("checkpoint_verified") is not True:
        _fail(f"{name}.checkpoint_verified must be true (declared metadata only)")

    config = _mapping(receipt.get("config"), f"{name}.config")
    expected_keys = set(STATIC_CONFIG) | DYNAMIC_CONFIG_KEYS
    if set(config) != expected_keys:
        _fail(f"{name}.config keys drift")
    for key in (
        "centers_per_update",
        "checkpoint_every",
        "hidden",
        "history_states",
        "log_every",
        "max_neighbors",
        "updates",
        "validation_case_count",
        "validation_centers",
        "validation_every",
        "validation_transition_count",
        "paired_seed",
        "sampler_seed",
        "seed",
    ):
        _strict_int(config.get(key), f"{name}.config.{key}")
    for key, expected in STATIC_CONFIG.items():
        if config.get(key) != expected:
            _fail(f"{name}.config.{key} drifts")
    if config["seed"] != seed or config["paired_seed"] != seed or config["sampler_seed"] != seed:
        _fail(f"{name}.config seed bindings drift")
    run_id = _expected_run_id(seed)
    if config.get("run_id") != run_id or receipt.get("run_id") != run_id:
        _fail(f"{name}.run_id drifts")
    manifest_sha = _sha256(config.get("manifest_sha256"), f"{name}.config.manifest_sha256")

    evidence = _mapping(receipt.get("evidence"), f"{name}.evidence")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("status") != "complete":
        _fail(f"{name}.evidence schema/status is incomplete")
    initialization = _mapping(evidence.get("initialization"), f"{name}.evidence.initialization")
    if initialization.get("schema") != INITIALIZATION_SCHEMA or initialization.get("status") != "captured":
        _fail(f"{name}.initialization evidence is incomplete")
    if (
        initialization.get("model_kind") != MODEL_KIND
        or initialization.get("constructed_before_first_update") is not True
    ):
        _fail(f"{name}.initialization evidence drifts")
    if _strict_int(initialization.get("seed"), f"{name}.initialization.seed") != seed:
        _fail(f"{name}.initialization evidence seed drifts")
    if _strict_int(initialization.get("hidden"), f"{name}.initialization.hidden") != HIDDEN:
        _fail(f"{name}.initialization evidence hidden drifts")
    if _strict_int(initialization.get("parameter_count"), f"{name}.initialization.parameter_count") != parameter_count:
        _fail(f"{name}.initialization evidence parameter count drifts")
    if _strict_int(initialization.get("construction_update"), f"{name}.initialization.construction_update") != 0:
        _fail(f"{name}.initialization construction update drifts")
    parameter_digest = _sha256(
        initialization.get("parameter_digest"),
        f"{name}.initialization.parameter_digest",
    )

    normalization = _mapping(evidence.get("normalization"), f"{name}.evidence.normalization")
    normalization_projection = _validate_normalization(normalization, seed, name)
    prior = _mapping(evidence.get("residual_prior"), f"{name}.evidence.residual_prior")
    prior_projection = _validate_prior(prior, name)

    checkpoint = _mapping(receipt.get("checkpoint"), f"{name}.checkpoint")
    if checkpoint.get("schema") != CHECKPOINT_SCHEMA or _strict_int(checkpoint.get("update"), f"{name}.checkpoint.update") != UPDATES:
        _fail(f"{name}.checkpoint schema/update drifts")
    checkpoint_path = _not_placeholder(
        _string(checkpoint.get("path"), f"{name}.checkpoint.path"),
        f"{name}.checkpoint.path",
    )
    expected_prefix = f"f3-graph-residual500-hidden16-seed{seed}-"
    if (
        not checkpoint_path.startswith("/")
        or ".." in Path(checkpoint_path).parts
        or not checkpoint_path.endswith("-checkpoint.pt")
        or expected_prefix not in checkpoint_path
    ):
        _fail(f"{name}.checkpoint.path is not the expected declared hidden16 residual namespace")
    checkpoint_sha = _sha256(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")
    _validate_zero_authority_markers(receipt, name)

    shared_config = {key: copy.deepcopy(value) for key, value in config.items() if key not in DYNAMIC_CONFIG_KEYS}
    shared_config.update(
        {
            "normalization_selection_policy": normalization["selection_policy"],
            "normalization_source_split": normalization["source_split"],
            "normalization_target_reference": normalization["target_reference"],
            "normalization_transitions": normalization["selected_transition_count"],
        }
    )
    return {
        "seed": seed,
        "run_id": run_id,
        "schema": TRAINING_SCHEMA,
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "evidence_status": "complete",
        "parameter_count": parameter_count,
        "manifest_sha256": manifest_sha,
        "checkpoint": {
            "schema": CHECKPOINT_SCHEMA,
            "path": checkpoint_path,
            "sha256": checkpoint_sha,
            "update": UPDATES,
        },
        "initialization": {
            "schema": INITIALIZATION_SCHEMA,
            "status": "captured",
            "parameter_count": parameter_count,
            "parameter_digest": parameter_digest,
        },
        "normalization": normalization_projection["identity"],
        "residual_prior": prior_projection["identity"],
        "shared_config": shared_config,
        "identity": {
            "manifest_sha256": manifest_sha,
            "checkpoint_sha256": checkpoint_sha,
            "initialization_parameter_digest": parameter_digest,
            "normalization_identity_sha256": normalization_projection["identity_sha256"],
            "residual_prior_identity_sha256": prior_projection["identity_sha256"],
        },
        "formal_eligible": False,
        "qualification_credit": 0,
    }


def _validate_reference_matrix(value: Mapping[str, Any]) -> tuple[str, dict[int, Mapping[str, Any]]]:
    _walk_json(value, "reference")
    if value.get("schema") != REFERENCE_SCHEMA:
        _fail(f"reference matrix schema must be {REFERENCE_SCHEMA}")
    if value.get("report_id") != "f3-graph-residual-hidden16-seeds17-29-43-training-2026-09-28":
        _fail("reference matrix report_id drifts")
    if (
        value.get("diagnostic_only") is not True
        or value.get("formal_eligible") is not False
        or value.get("model") != MODEL_KIND
    ):
        _fail("reference matrix authorization/model markers drift")
    shared = _mapping(value.get("shared_config"), "reference.shared_config")
    if dict(shared) != REFERENCE_SHARED_CONFIG:
        _fail("reference matrix shared_config drifts")
    qualification = _mapping(value.get("qualification"), "reference.qualification")
    if (
        qualification.get("training_evidence_complete") is not True
        or qualification.get("full_rollout_evaluations") != "pending"
        or qualification.get("qualification") is not False
        or qualification.get("t1") is not False
        or qualification.get("t2") is not False
        or qualification.get("credit") != 0
    ):
        _fail("reference matrix qualification markers drift")
    manifest_sha = _sha256(value.get("manifest_sha256"), "reference.manifest_sha256")
    runs = value.get("runs")
    if not isinstance(runs, list) or len(runs) != len(SEEDS):
        _fail("reference matrix must contain exactly three runs")
    result: dict[int, Mapping[str, Any]] = {}
    for row in runs:
        item = _mapping(row, "reference.run")
        seed = _strict_int(item.get("seed"), "reference.run.seed")
        if seed in result or seed not in SEEDS:
            _fail("reference matrix seed set is not exactly 17, 29, 43")
        if item.get("run_id") != _expected_run_id(seed) or _strict_int(
            item.get("completed_updates"), f"reference.run[{seed}].completed_updates"
        ) != UPDATES:
            _fail(f"reference run {seed} identity drifts")
        if item.get("checkpoint_verified") is not True or _strict_int(
            item.get("parameter_count"), f"reference.run[{seed}].parameter_count"
        ) != PARAMETER_COUNT:
            _fail(f"reference run {seed} checkpoint/parameter metadata drifts")
        for key in (
            "checkpoint_sha256",
            "training_receipt_sha256",
            "initialization_parameter_digest",
            "normalization_identity_sha256",
            "residual_prior_identity_sha256",
        ):
            _sha256(item.get(key), f"reference.run[{seed}].{key}")
        if item.get("neighbor_truncation_fraction") != 0.0:
            _fail(f"reference run {seed} neighbor truncation drifts")
        result[seed] = item
    if set(result) != set(SEEDS):
        _fail("reference matrix seed set is incomplete")
    return manifest_sha, result


def _check(
    name: str,
    passed: bool,
    reason: str,
    observed: Any = None,
    expected: Any = None,
) -> dict[str, Any]:
    return {
        "check": name,
        "passed": bool(passed),
        "reason": reason,
        "observed": observed,
        "expected": expected,
    }


def evaluate_payloads(
    training_receipts: Mapping[int, Mapping[str, Any]],
    training_sources: Mapping[int, Mapping[str, Any]],
    reference_matrix: Mapping[str, Any] | None,
    reference_source: Mapping[str, Any] | None,
    *,
    source_errors: Sequence[str] = (),
    observed_at_utc: str = OBSERVED_AT_UTC,
) -> dict[str, Any]:
    """Build a fail-closed report from already bounded JSON payloads."""

    errors = list(source_errors)
    checks: list[dict[str, Any]] = []
    expected_set = set(SEEDS)
    observed_set = set(training_receipts)
    source_set = set(training_sources)
    exact_seed_set = observed_set == expected_set
    exact_source_set = source_set == expected_set
    checks.append(
        _check(
            "exact_seed_set",
            exact_seed_set,
            "training receipts must contain exactly seeds 17, 29, and 43",
            sorted(observed_set),
            list(SEEDS),
        )
    )
    checks.append(
        _check(
            "exact_source_seed_set",
            exact_source_set,
            "training source metadata must contain exactly seeds 17, 29, and 43",
            sorted(source_set),
            list(SEEDS),
        )
    )
    if not exact_seed_set:
        errors.append(f"training seed set drift: observed {sorted(observed_set)} expected {list(SEEDS)}")
    if not exact_source_set:
        errors.append(f"training source seed set drift: observed {sorted(source_set)} expected {list(SEEDS)}")

    reference_rows: dict[int, Mapping[str, Any]] = {}
    reference_manifest_sha: str | None = None
    reference_ok = True
    if reference_matrix is None:
        reference_ok = False
        errors.append("missing reference training matrix")
    else:
        try:
            reference_manifest_sha, reference_rows = _validate_reference_matrix(reference_matrix)
        except MatrixError as error:
            reference_ok = False
            errors.append(f"reference matrix: {error}")
    checks.append(
        _check(
            "reference_training_matrix_schema",
            reference_ok,
            "compact residual training matrix schema and identity metadata are valid",
        )
    )

    source_metadata_ok = exact_source_set
    for seed, source in training_sources.items():
        if seed not in expected_set:
            continue
        try:
            _validate_source_metadata(
                source,
                TRAINING_SCHEMA,
                f"training source[{seed}]",
                allow_error=seed not in training_receipts,
            )
        except (KeyError, MatrixError) as error:
            source_metadata_ok = False
            errors.append(f"training source[{seed}]: {error}")
    if not source_metadata_ok:
        errors.append("training source metadata contract is incomplete")
    checks.append(
        _check(
            "training_source_metadata",
            source_metadata_ok,
            "all training source references are complete bounded JSON metadata",
        )
    )

    reference_source_ok = False
    if reference_matrix is not None:
        try:
            reference_source_ok = _validate_source_metadata(
                reference_source,
                REFERENCE_SCHEMA,
                "reference source",
            )
        except (KeyError, MatrixError) as error:
            errors.append(f"reference source: {error}")
    checks.append(
        _check(
            "reference_source_metadata",
            reference_source_ok,
            "reference source is complete bounded JSON metadata",
        )
    )

    rows: list[dict[str, Any]] = []
    projections: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        row: dict[str, Any] = {
            "seed": seed,
            "status": "missing" if seed not in training_receipts else "rejected",
            "source": training_sources.get(seed),
            "blocked_reasons": [],
        }
        receipt = training_receipts.get(seed)
        if receipt is None:
            row["blocked_reasons"].append(f"missing training receipt for seed {seed}")
            errors.append(f"missing training receipt for seed {seed}")
        else:
            try:
                projection = _validate_training_receipt(receipt, seed)
                source = training_sources.get(seed)
                source_sha = _sha256(
                    source.get("sha256") if isinstance(source, Mapping) else None,
                    f"training source[{seed}].sha256",
                )
                projection["identity"]["training_receipt_sha256"] = source_sha
                if reference_ok:
                    reference = reference_rows[seed]
                    if source_sha != reference["training_receipt_sha256"]:
                        _fail(f"seed{seed} training receipt SHA drifts from reference matrix")
                    if projection["checkpoint"]["sha256"] != reference["checkpoint_sha256"]:
                        _fail(f"seed{seed} checkpoint SHA drifts from reference matrix")
                    if projection["manifest_sha256"] != reference_manifest_sha:
                        _fail(f"seed{seed} manifest SHA drifts from reference matrix")
                    if projection["initialization"]["parameter_digest"] != reference["initialization_parameter_digest"]:
                        _fail(f"seed{seed} initialization digest drifts from reference matrix")
                    if projection["identity"]["normalization_identity_sha256"] != reference["normalization_identity_sha256"]:
                        _fail(f"seed{seed} normalization identity drifts from reference matrix")
                    if projection["identity"]["residual_prior_identity_sha256"] != reference["residual_prior_identity_sha256"]:
                        _fail(f"seed{seed} residual-prior identity drifts from reference matrix")
                row["evidence"] = projection
                projections[seed] = projection
                row["status"] = "bound_complete"
            except (KeyError, MatrixError) as error:
                message = str(error)
                row["blocked_reasons"].append(message)
                errors.append(f"seed{seed}: {message}")
        rows.append(row)

    shared_configs = [projections[seed]["shared_config"] for seed in SEEDS if seed in projections]
    shared_config_ok = len(shared_configs) == len(SEEDS) and all(
        _canonical(config) == _canonical(shared_configs[0]) for config in shared_configs
    )
    checks.append(
        _check(
            "common_config",
            shared_config_ok,
            "all three receipts share one graph_residual hidden16 configuration",
        )
    )
    if not shared_config_ok:
        errors.append("training receipts do not provide one common configuration")

    manifest_shas = [projections[seed]["manifest_sha256"] for seed in SEEDS if seed in projections]
    common_manifest_ok = (
        len(manifest_shas) == len(SEEDS)
        and len(set(manifest_shas)) == 1
        and reference_manifest_sha is not None
        and manifest_shas[0] == reference_manifest_sha
    )
    checks.append(
        _check(
            "common_manifest_identity",
            common_manifest_ok,
            "all three receipts bind one reference manifest identity",
            manifest_shas,
            reference_manifest_sha,
        )
    )
    if not common_manifest_ok:
        errors.append("training receipts do not provide one common manifest identity")

    identity_rows = [projections[seed]["identity"] for seed in SEEDS if seed in projections]
    identity_complete = len(identity_rows) == len(SEEDS) and all(
        set(row) == {
            "manifest_sha256",
            "training_receipt_sha256",
            "checkpoint_sha256",
            "initialization_parameter_digest",
            "normalization_identity_sha256",
            "residual_prior_identity_sha256",
        }
        for row in identity_rows
    )
    checks.append(
        _check(
            "identity_components_complete",
            identity_complete,
            "training receipt, checkpoint, initialization, normalization, and residual-prior identities are present",
        )
    )
    if not identity_complete:
        errors.append("training identity components are incomplete")

    checkpoint_paths = [projections[seed]["checkpoint"]["path"] for seed in SEEDS if seed in projections]
    identity_values = [
        (
            projections[seed]["identity"]["manifest_sha256"],
            projections[seed]["identity"]["training_receipt_sha256"],
            projections[seed]["identity"]["checkpoint_sha256"],
            projections[seed]["identity"]["initialization_parameter_digest"],
            projections[seed]["identity"]["normalization_identity_sha256"],
        )
        for seed in SEEDS
        if seed in projections
    ]
    identity_unique = (
        len(checkpoint_paths) == len(set(checkpoint_paths)) == len(SEEDS)
        and len(identity_values) == len(set(identity_values)) == len(SEEDS)
    )
    checks.append(
        _check(
            "identity_unique_per_seed",
            identity_unique,
            "declared training/checkpoint/init/normalization identities are distinct per seed",
        )
    )
    if not identity_unique:
        errors.append("training/checkpoint/init/normalization identity is duplicated across seeds")

    all_bound = (
        not errors
        and exact_seed_set
        and exact_source_set
        and source_metadata_ok
        and reference_ok
        and reference_source_ok
        and len(projections) == len(SEEDS)
        and shared_config_ok
        and common_manifest_ok
        and identity_complete
        and identity_unique
    )
    for row in rows:
        if row["status"] == "bound_complete" and not all_bound:
            row["blocked_reasons"].append("matrix-level binding failed closed")
            row["status"] = "blocked"
    errors = list(dict.fromkeys(errors))
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc,
        "status": "training_evidence_bound_diagnostic_only" if all_bound else "blocked_fail_closed",
        "fail_closed": not all_bound,
        "source_bound": all_bound,
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "qualification": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "credit": 0,
        "formal_training_runs_expected": 9,
        "formal_training_runs_counted": 0,
        "training_evidence_counted_as_formal_runs": 0,
        "t1_case_runs_counted": 0,
        "t2_macro_families_counted": 0,
        "expected_contract": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seeds": list(SEEDS),
            "parameter_count": PARAMETER_COUNT,
            "evidence_status": "complete",
            "shared_config": REFERENCE_SHARED_CONFIG,
            "normalization_transitions": NORMALIZATION_TRANSITIONS,
            "prior_schema": PRIOR_SCHEMA,
            "manifest_identity_bound": True,
            "checkpoint_content_opened": False,
        },
        "reference_training_matrix": {
            "source": reference_source,
            "schema": REFERENCE_SCHEMA,
            "opened": reference_ok,
        },
        "runs": rows,
        "shared_config": shared_configs[0] if shared_configs and shared_config_ok else None,
        "checks": checks,
        "errors": errors,
        "authorization": {
            "formal": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
        },
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "manifest_opened": False,
            "checkpoint_opened": False,
            "checkpoint_content_opened": False,
            "case_hdf5_opened": False,
            "trajectory_hdf5_opened": False,
            "progress_opened": False,
            "gpu_started": False,
            "solver_started": False,
        },
        "side_effects": {
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": False,
            "runtime_started": False,
            "runtime_stopped": False,
            "runtime_restarted": False,
        },
        "scope_note": SCOPE_NOTE,
    }
    return report


def _missing_or_failed_source(root: Path, value: Path | str, error: Exception) -> dict[str, Any]:
    try:
        path = _resolve_path(root, value)
    except (MatrixError, TypeError, ValueError):
        raw = Path(value).expanduser()
        path = raw if raw.is_absolute() else root / raw
        path = path.absolute()
    return _source_ref(root, path, error=str(error))


def build_report(
    training_paths: Mapping[int, Path | str] | None = None,
    reference_path: Path | str = DEFAULT_REFERENCE,
    *,
    root: Path = LAB_ROOT,
    observed_at_utc: str = OBSERVED_AT_UTC,
) -> dict[str, Any]:
    paths = dict(DEFAULT_RECEIPTS if training_paths is None else training_paths)
    receipts: dict[int, Mapping[str, Any]] = {}
    sources: dict[int, Mapping[str, Any]] = {}
    errors: list[str] = []
    for seed, path in paths.items():
        try:
            receipt, source = read_bounded_json(root, path)
            receipts[seed] = receipt
            sources[seed] = source
        except (MatrixError, OSError, TypeError, ValueError) as error:
            sources[seed] = _missing_or_failed_source(root, path, error)
            errors.append(f"seed{seed} source: {error}")
    try:
        reference, reference_source = read_bounded_json(root, reference_path)
    except (MatrixError, OSError, TypeError, ValueError) as error:
        reference = None
        reference_source = _missing_or_failed_source(root, reference_path, error)
        errors.append(f"reference source: {error}")
    return evaluate_payloads(
        receipts,
        sources,
        reference,
        reference_source,
        source_errors=errors,
        observed_at_utc=observed_at_utc,
    )


def _validate_report_projection(value: Any, name: str) -> list[str]:
    errors: list[str] = []
    try:
        projection = _mapping(value, name)
        expected_keys = {
            "seed", "run_id", "schema", "model_kind", "hidden", "updates", "evidence_status",
            "parameter_count", "manifest_sha256", "checkpoint", "initialization", "normalization",
            "residual_prior", "shared_config", "identity", "formal_eligible", "qualification_credit",
        }
        if set(projection) != expected_keys:
            _fail(f"{name} keys drift")
        seed = _strict_int(projection.get("seed"), f"{name}.seed")
        if seed not in SEEDS or projection.get("run_id") != _expected_run_id(seed):
            _fail(f"{name} seed/run identity drifts")
        if projection.get("schema") != TRAINING_SCHEMA or projection.get("model_kind") != MODEL_KIND:
            _fail(f"{name} schema/model identity drifts")
        if _strict_int(projection.get("hidden"), f"{name}.hidden") != HIDDEN:
            _fail(f"{name}.hidden drifts")
        if _strict_int(projection.get("updates"), f"{name}.updates") != UPDATES:
            _fail(f"{name}.updates drifts")
        if projection.get("evidence_status") != "complete":
            _fail(f"{name}.evidence_status drifts")
        if _strict_int(projection.get("parameter_count"), f"{name}.parameter_count") != PARAMETER_COUNT:
            _fail(f"{name}.parameter_count drifts")
        _sha256(projection.get("manifest_sha256"), f"{name}.manifest_sha256")
        if projection.get("formal_eligible") is not False or type(projection.get("qualification_credit")) is not int or projection.get("qualification_credit") != 0:
            _fail(f"{name} authorization markers drift")

        checkpoint = _mapping(projection.get("checkpoint"), f"{name}.checkpoint")
        if set(checkpoint) != {"schema", "path", "sha256", "update"}:
            _fail(f"{name}.checkpoint keys drift")
        if checkpoint.get("schema") != CHECKPOINT_SCHEMA or _strict_int(checkpoint.get("update"), f"{name}.checkpoint.update") != UPDATES:
            _fail(f"{name}.checkpoint identity drifts")
        checkpoint_path = _not_placeholder(_string(checkpoint.get("path"), f"{name}.checkpoint.path"), f"{name}.checkpoint.path")
        if not checkpoint_path.startswith("/") or ".." in Path(checkpoint_path).parts or not checkpoint_path.endswith("-checkpoint.pt"):
            _fail(f"{name}.checkpoint.path is unsafe")
        _sha256(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")

        initialization = _mapping(projection.get("initialization"), f"{name}.initialization")
        if set(initialization) != {"schema", "status", "parameter_count", "parameter_digest"}:
            _fail(f"{name}.initialization keys drift")
        if initialization.get("schema") != INITIALIZATION_SCHEMA or initialization.get("status") != "captured":
            _fail(f"{name}.initialization schema/status drifts")
        if _strict_int(initialization.get("parameter_count"), f"{name}.initialization.parameter_count") != PARAMETER_COUNT:
            _fail(f"{name}.initialization parameter count drifts")
        _sha256(initialization.get("parameter_digest"), f"{name}.initialization.parameter_digest")

        normalization = _mapping(projection.get("normalization"), f"{name}.normalization")
        if set(normalization) != {"schema", "available_transition_count", "requested_maximum_transitions", "selected_transition_count", "selection_policy", "selection_seed", "source_split", "target_reference"}:
            _fail(f"{name}.normalization keys drift")
        _validate_normalization(normalization, seed, name)

        prior = _mapping(projection.get("residual_prior"), f"{name}.residual_prior")
        if set(prior) != {"schema", "enabled", "history_complete", "units", "execution_calls", "rows", "finite", "semantic", "dx_abs_max_m", "dv_abs_max_mps", "dx_abs_sum_m", "dv_abs_sum_mps", "last_update"}:
            _fail(f"{name}.residual_prior keys drift")
        _validate_prior(prior, name)
        if dict(_mapping(projection.get("shared_config"), f"{name}.shared_config")) != REFERENCE_SHARED_CONFIG:
            _fail(f"{name}.shared_config drifts")
        identity = _mapping(projection.get("identity"), f"{name}.identity")
        if set(identity) != {"manifest_sha256", "training_receipt_sha256", "checkpoint_sha256", "initialization_parameter_digest", "normalization_identity_sha256", "residual_prior_identity_sha256"}:
            _fail(f"{name}.identity keys drift")
        for key in identity:
            _sha256(identity[key], f"{name}.identity.{key}")
        if identity["manifest_sha256"] != projection["manifest_sha256"]:
            _fail(f"{name}.identity manifest binding drifts")
        if identity["checkpoint_sha256"] != checkpoint["sha256"]:
            _fail(f"{name}.identity checkpoint binding drifts")
        if identity["initialization_parameter_digest"] != initialization["parameter_digest"]:
            _fail(f"{name}.identity initialization binding drifts")
        if identity["normalization_identity_sha256"] != identity_sha256(normalization):
            _fail(f"{name}.identity normalization binding drifts")
        if identity["residual_prior_identity_sha256"] != identity_sha256(prior):
            _fail(f"{name}.identity residual-prior binding drifts")
    except (KeyError, MatrixError) as error:
        errors.append(str(error))
    return errors


def _validate_report_checks(
    value: Any,
    required: set[str],
    *,
    require_all_passed: bool = False,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list):
        return ["checks must be an array"]
    names: set[str] = set()
    for index, item in enumerate(value):
        try:
            check = _mapping(item, f"checks[{index}]")
            if set(check) != {"check", "passed", "reason", "observed", "expected"}:
                _fail(f"checks[{index}] keys drift")
            name = _string(check.get("check"), f"checks[{index}].check")
            if name in names:
                _fail(f"duplicate check name: {name}")
            names.add(name)
            if type(check.get("passed")) is not bool:
                _fail(f"checks[{index}].passed must be boolean")
            if require_all_passed and check.get("passed") is not True:
                _fail(f"checks[{index}].passed must be true for a bound report")
            _string(check.get("reason"), f"checks[{index}].reason")
        except (KeyError, MatrixError) as error:
            errors.append(str(error))
    if names != required:
        errors.append(f"check set drift: observed {sorted(names)} expected {sorted(required)}")
    return errors


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate the report envelope without opening any source artifact."""

    errors: list[str] = []
    if not isinstance(report, Mapping):
        return ["report must be an object"]
    try:
        _walk_json(report, "report")
    except MatrixError as error:
        errors.append(str(error))
    if set(report) != REPORT_ENVELOPE_KEYS:
        errors.append("report envelope keys drift")
    if report.get("schema") != SCHEMA:
        errors.append("report schema drift")
    if report.get("report_id") != REPORT_ID:
        errors.append("report id drift")
    try:
        _string(report.get("observed_at_utc"), "observed_at_utc")
    except MatrixError as error:
        errors.append(str(error))
    if type(report.get("source_bound")) is not bool:
        errors.append("source_bound must be boolean")
    source_bound = report.get("source_bound") is True
    expected_status = "training_evidence_bound_diagnostic_only" if source_bound else "blocked_fail_closed"
    if report.get("status") != expected_status:
        errors.append("status/source_bound mismatch")
    if report.get("fail_closed") is not (not source_bound):
        errors.append("fail_closed/source_bound mismatch")
    if report.get("diagnostic_only") is not True:
        errors.append("diagnostic_only must be true")
    for key in ("formal", "formal_eligible", "qualification", "T1_numerical", "T2_macro", "T2_path"):
        if report.get(key) is not False:
            errors.append(f"{key} must be false")
    try:
        if _strict_int(report.get("formal_training_runs_expected"), "formal_training_runs_expected") != 9:
            errors.append("formal_training_runs_expected must be 9")
    except MatrixError as error:
        errors.append(str(error))
    if report.get("scope_note") != SCOPE_NOTE:
        errors.append("scope_note drift")
    for key in ("qualification_credit", "credit", "formal_training_runs_counted", "training_evidence_counted_as_formal_runs", "t1_case_runs_counted", "t2_macro_families_counted"):
        if type(report.get(key)) is not int or report.get(key) != 0:
            errors.append(f"{key} must be zero integer")

    expected = report.get("expected_contract")
    expected_keys = {"model_kind", "hidden", "updates", "seeds", "parameter_count", "evidence_status", "shared_config", "normalization_transitions", "prior_schema", "manifest_identity_bound", "checkpoint_content_opened"}
    if not isinstance(expected, Mapping) or set(expected) != expected_keys:
        errors.append("expected_contract keys drift")
    else:
        if expected.get("model_kind") != MODEL_KIND or expected.get("evidence_status") != "complete" or expected.get("prior_schema") != PRIOR_SCHEMA:
            errors.append("expected_contract model/evidence drift")
        try:
            if _strict_int(expected.get("hidden"), "expected_contract.hidden") != HIDDEN or _strict_int(expected.get("updates"), "expected_contract.updates") != UPDATES or _strict_int(expected.get("parameter_count"), "expected_contract.parameter_count") != PARAMETER_COUNT or _strict_int(expected.get("normalization_transitions"), "expected_contract.normalization_transitions") != NORMALIZATION_TRANSITIONS:
                errors.append("expected_contract numeric identity drift")
        except MatrixError as error:
            errors.append(str(error))
        if expected.get("seeds") != list(SEEDS) or expected.get("shared_config") != REFERENCE_SHARED_CONFIG or expected.get("manifest_identity_bound") is not True or expected.get("checkpoint_content_opened") is not False:
            errors.append("expected_contract identity/boundary drift")

    authorization = report.get("authorization")
    if not isinstance(authorization, Mapping) or set(authorization) != {"formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification", "qualification_credit", "credit"}:
        errors.append("authorization keys drift")
    else:
        for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
            if authorization.get(key) is not False:
                errors.append(f"authorization.{key} must be false")
        for key in ("qualification_credit", "credit"):
            if type(authorization.get(key)) is not int or authorization.get(key) != 0:
                errors.append(f"authorization.{key} must be zero integer")

    reference = report.get("reference_training_matrix")
    if not isinstance(reference, Mapping) or set(reference) != {"source", "schema", "opened"}:
        errors.append("reference_training_matrix keys drift")
    else:
        if reference.get("schema") != REFERENCE_SCHEMA or type(reference.get("opened")) is not bool:
            errors.append("reference_training_matrix identity drift")
        try:
            opened = _validate_source_metadata(reference.get("source"), REFERENCE_SCHEMA, "report.reference source", allow_error=not source_bound)
            if reference.get("opened") is not opened:
                errors.append("reference_training_matrix.opened/source mismatch")
        except (KeyError, MatrixError) as error:
            errors.append(str(error))

    runs = report.get("runs")
    required_run_keys = {"seed", "status", "source", "blocked_reasons"}
    observed_seeds: set[int] = set()
    validated_projections: dict[int, Mapping[str, Any]] = {}
    if not isinstance(runs, list) or len(runs) != len(SEEDS):
        errors.append("report runs must contain exactly three rows")
    else:
        for index, row in enumerate(runs):
            try:
                item = _mapping(row, f"runs[{index}]")
                seed = _strict_int(item.get("seed"), f"runs[{index}].seed")
                if seed not in SEEDS or seed in observed_seeds:
                    _fail(f"runs[{index}].seed set drifts")
                observed_seeds.add(seed)
                status = item.get("status")
                if status not in {"missing", "rejected", "blocked", "bound_complete"}:
                    _fail(f"runs[{index}].status drifts")
                blocked_reasons = item.get("blocked_reasons")
                if not isinstance(blocked_reasons, list) or any(not isinstance(reason, str) for reason in blocked_reasons):
                    _fail(f"runs[{index}].blocked_reasons drifts")
                source_complete = _validate_source_metadata(item.get("source"), TRAINING_SCHEMA, f"runs[{index}].source", allow_error=not source_bound)
                if source_bound and not source_complete:
                    _fail(f"runs[{index}].source must be complete when source_bound")
                has_evidence = "evidence" in item
                expected_row_keys = required_run_keys | ({"evidence"} if has_evidence else set())
                if set(item) != expected_row_keys:
                    _fail(f"runs[{index}] keys drift")
                if status == "bound_complete" and not has_evidence:
                    _fail(f"runs[{index}] bound row is missing evidence")
                if source_bound and status != "bound_complete":
                    _fail(f"runs[{index}] bound matrix has non-complete row")
                if status in {"bound_complete", "blocked"} and not source_complete:
                    _fail(f"runs[{index}] complete evidence row has incomplete source metadata")
                if status in {"missing", "rejected"} and has_evidence:
                    _fail(f"runs[{index}] rejected row must not contain evidence")
                if status == "bound_complete" and blocked_reasons:
                    _fail(f"runs[{index}] complete row must not be blocked")
                if status in {"missing", "rejected", "blocked"} and not blocked_reasons:
                    _fail(f"runs[{index}] blocked row must include a reason")
                if has_evidence:
                    projection_errors = _validate_report_projection(item["evidence"], f"runs[{index}].evidence")
                    errors.extend(projection_errors)
                    if not projection_errors:
                        validated_projections[seed] = item["evidence"]
            except (KeyError, MatrixError) as error:
                errors.append(str(error))
    if observed_seeds != set(SEEDS):
        errors.append("report run seed set drift")

    if source_bound and len(validated_projections) == len(SEEDS):
        manifests = [validated_projections[seed]["manifest_sha256"] for seed in SEEDS]
        if len(set(manifests)) != 1:
            errors.append("bound report manifest identity is not common across seeds")
        configs = [validated_projections[seed]["shared_config"] for seed in SEEDS]
        if any(dict(config) != dict(configs[0]) for config in configs[1:]):
            errors.append("bound report shared configuration is not common across seeds")
    errors.extend(
        _validate_report_checks(
            report.get("checks"),
            {"exact_seed_set", "exact_source_seed_set", "reference_training_matrix_schema", "training_source_metadata", "reference_source_metadata", "common_config", "common_manifest_identity", "identity_components_complete", "identity_unique_per_seed"},
            require_all_passed=source_bound,
        )
    )
    report_errors = report.get("errors")
    if not isinstance(report_errors, list) or any(not isinstance(item, str) for item in report_errors):
        errors.append("report.errors must be an array of strings")
    elif source_bound and report_errors:
        errors.append("bound report.errors must be empty")
    elif not source_bound and not report_errors:
        errors.append("blocked report.errors must not be empty")
    shared_config = report.get("shared_config")
    if shared_config is not None and (not isinstance(shared_config, Mapping) or dict(shared_config) != REFERENCE_SHARED_CONFIG):
        errors.append("report.shared_config drifts")
    if source_bound and shared_config is None:
        errors.append("bound report.shared_config is missing")

    boundary = report.get("input_boundary")
    boundary_keys = {"bounded_json_only", "max_json_bytes", "manifest_opened", "checkpoint_opened", "checkpoint_content_opened", "case_hdf5_opened", "trajectory_hdf5_opened", "progress_opened", "gpu_started", "solver_started"}
    if not isinstance(boundary, Mapping) or set(boundary) != boundary_keys:
        errors.append("input_boundary keys drift")
    else:
        if boundary.get("bounded_json_only") is not True or type(boundary.get("max_json_bytes")) is not int or boundary.get("max_json_bytes") != MAX_JSON_BYTES:
            errors.append("input_boundary bounded JSON contract drifts")
        for key in boundary_keys - {"bounded_json_only", "max_json_bytes"}:
            if boundary.get(key) is not False:
                errors.append(f"input_boundary.{key} must be false")

    side_effects = report.get("side_effects")
    side_effect_keys = {"registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation", "completion_mutation", "runtime_started", "runtime_stopped", "runtime_restarted"}
    if not isinstance(side_effects, Mapping) or set(side_effects) != side_effect_keys:
        errors.append("side_effects keys drift")
    else:
        for key in ("registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation"):
            if type(side_effects.get(key)) is not int or side_effects.get(key) != 0:
                errors.append(f"side_effects.{key} must be zero integer")
        for key in ("completion_mutation", "runtime_started", "runtime_stopped", "runtime_restarted"):
            if side_effects.get(key) is not False:
                errors.append(f"side_effects.{key} must be false")
    return errors


def _safe_output_path(output: Path | str, suffix: str) -> Path:
    if not isinstance(output, (Path, str)):
        _fail(f"output path must be a path string: {output!r}")
    raw = Path(output).expanduser()
    if ".." in raw.parts:
        _fail(f"output path must not contain parent traversal: {raw}")
    if raw.suffix.lower() in DANGEROUS_OUTPUT_SUFFIXES or raw.suffix.lower() != suffix:
        _fail(f"output path must use the safe {suffix} suffix: {raw}")
    lowered_name = raw.name.lower()
    if any(token in lowered_name for token in DANGEROUS_OUTPUT_TOKENS):
        _fail(f"output path names a protected artifact: {raw}")
    base = Path(os.path.abspath(Path.cwd()))
    candidate = Path(os.path.abspath(raw if raw.is_absolute() else base / raw))
    try:
        candidate.relative_to(base)
    except ValueError:
        _fail(f"output path escapes the current working directory: {raw}")
    _reject_symlink_components(candidate)
    if candidate.exists() and not stat.S_ISREG(os.lstat(candidate).st_mode):
        _fail(f"output path is not a regular file: {candidate}")
    return candidate


def _write_text_safely(text: str, output: Path | str, suffix: str) -> None:
    path = _safe_output_path(output, suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_report(report: Mapping[str, Any], output: Path | str) -> None:
    _write_text_safely(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", output, ".json")


def render_zh_cn(report: Mapping[str, Any]) -> str:
    rows = report.get("runs", [])
    lines = [
        "# F3 graph_residual hidden16 三 seed training evidence matrix V1",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- source-bound：`{report.get('source_bound')}`；fail-closed：`{report.get('fail_closed')}`",
        "- 范围：仅读取 bounded `core.training.v1` 与独立 training-matrix JSON 的 schema/hash/小字段；不打开 checkpoint、case HDF5、trajectory、progress、manifest，也不启动 GPU/solver。",
        "- 授权：diagnostic-only；formal/T1/T2/qualification 均为 false，credit 与 formal training counted 均为 0。",
        "",
        "| seed | 状态 | checkpoint SHA | init digest | normalization identity | residual prior |",
        "|---:|---|---|---|---|---|",
    ]
    for row in rows:
        evidence = row.get("evidence", {}) if isinstance(row, Mapping) else {}
        checkpoint = evidence.get("checkpoint", {}) if isinstance(evidence, Mapping) else {}
        initialization = evidence.get("initialization", {}) if isinstance(evidence, Mapping) else {}
        identity = evidence.get("identity", {}) if isinstance(evidence, Mapping) else {}
        prior = evidence.get("residual_prior", {}) if isinstance(evidence, Mapping) else {}
        lines.append(
            f"| {row.get('seed')} | `{row.get('status')}` | `{checkpoint.get('sha256', 'missing')}` | "
            f"`{initialization.get('parameter_digest', 'missing')}` | "
            f"`{identity.get('normalization_identity_sha256', 'missing')}` | "
            f"`{prior.get('enabled', 'missing')}/{prior.get('execution_calls', 'missing')}` |"
        )
    lines.extend(
        [
            "",
            "本报告是独立、只读、非授权的 graph_residual training evidence 绑定；即使三份 receipt 完整，也不计入 formal 9 runs，不产生 T1/T2 或 qualification credit。",
            "",
        ]
    )
    return "\n".join(lines)


def write_markdown(report: Mapping[str, Any], output: Path | str) -> None:
    _write_text_safely(render_zh_cn(report), output, ".md")


def _parse_seed_receipts(values: Sequence[str]) -> dict[int, Path | str]:
    result: dict[int, Path | str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError("--seed-receipt must use SEED=PATH")
        seed_text, path = item.split("=", 1)
        seed = int(seed_text)
        if seed in result:
            raise ValueError(f"duplicate seed receipt: {seed}")
        result[seed] = path
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-receipt", action="append", default=[], metavar="SEED=PATH")
    parser.add_argument("--reference-matrix", default=str(DEFAULT_REFERENCE))
    parser.add_argument(
        "--output",
        default="reports/F3-GRAPH-RESIDUAL-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.json",
    )
    parser.add_argument(
        "--markdown-output",
        default="reports/F3-GRAPH-RESIDUAL-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.zh-CN.md",
    )
    args = parser.parse_args(argv)
    try:
        paths = dict(DEFAULT_RECEIPTS)
        if args.seed_receipt:
            paths = _parse_seed_receipts(args.seed_receipt)
        report = build_report(paths, args.reference_matrix)
    except (ValueError, MatrixError) as error:
        parser.error(str(error))
    write_report(report, args.output)
    write_markdown(report, args.markdown_output)
    envelope_errors = validate_report(report)
    if envelope_errors:
        print(json.dumps({"report_errors": envelope_errors}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {"status": report["status"], "source_bound": report["source_bound"], "output": args.output},
            ensure_ascii=False,
        )
    )
    return 0 if report["source_bound"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
