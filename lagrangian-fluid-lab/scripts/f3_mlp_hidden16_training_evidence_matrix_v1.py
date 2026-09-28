#!/usr/bin/env python3
"""Bind the independent F3 MLP/hidden16 three-seed training matrix.

This adapter is intentionally metadata-only.  It reads bounded JSON receipts
and a bounded JSON reference matrix, validates declared identities, and never
opens a checkpoint, HDF5, trajectory, manifest, or progress artifact.  A
successful bind remains diagnostic-only and has zero formal/T1/T2/qualification
authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA = "core.f3.mlp.hidden16.training_evidence_matrix.v1"
REFERENCE_SCHEMA = "core.f3.mlp.hidden16.training_matrix.v1"
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
INITIALIZATION_SCHEMA = "core.training.initialization_evidence.v1"
NORMALIZATION_SCHEMA = "core.training.normalization_evidence.v1"
REPORT_ID = "f3-mlp-hidden16-training-evidence-matrix-v1"
LAB_ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 29, 43)
MODEL_KIND = "mlp"
HIDDEN = 16
UPDATES = 500
PARAMETER_COUNT = 1574
MAX_JSON_BYTES = 1 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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
    "reports/F3-MLP-HIDDEN16-SEEDS17-29-43-TRAINING-2026-09-28.json"
)
DEFAULT_RECEIPTS = {
    seed: Path(f"/tmp/f3-mlp500-hidden16-seed{seed}-20260928-training.json")
    for seed in SEEDS
}

# These are the protocol fields shared by the three runs.  Operational
# scheduling fields are validated separately because an evidence matrix must
# bind each receipt's complete config identity without pretending that a
# milestone-evaluation switch changes the model protocol.
STATIC_CONFIG: dict[str, Any] = {
    "centers_per_update": 256,
    "checkpoint_every": 500,
    "gradient_clipping": None,
    "hidden": HIDDEN,
    "history_states": 1,
    "initialization": "core.paired_initialization.common_encoder_head.v1",
    "learning_rate": 0.001,
    "log_every": 100,
    "manifest_formal_release": False,
    "max_neighbors": 192,
    "model_kind": MODEL_KIND,
    "normalization_source_split": "train",
    "optimizer": "Adam",
    "radius_over_h": 2.0,
    "target_normalization": "raw_dual_increment_train_shared",
    "updates": UPDATES,
    "validation_case_count": 4,
    "validation_centers": 256,
    "validation_family_counts": {"F3": 4},
    "validation_formal_eligible": False,
    "validation_transition_count": 4,
}
OPERATIONAL_CONFIG_KEYS = {
    "evaluate_milestones",
    "milestone_evaluation_mode",
    "validation_every",
}
DYNAMIC_CONFIG_KEYS = {"manifest_sha256", "paired_seed", "run_id", "sampler_seed", "seed"}

# The normalization evidence is a bounded identity contract, not a request to
# inspect the underlying dataset.  These values are copied from the declared
# training evidence contract and are compared structurally and by digest.
TRAIN_CASE_IDS = (
    "F3_DEV_06_a0p940625",
    "F3_DEV_07_a0p946875",
    "F3_DEV_09_a0p959375",
    "F3_DEV_10_a0p965625",
    "F3_DEV_11_a0p971875",
    "F3_DEV_12_a0p978125",
    "F3_DEV_14_a0p990625",
    "F3_DEV_15_a0p996875",
    "F3_DEV_16_a1p003125",
    "F3_DEV_17_a1p009375",
    "F3_DEV_19_a1p021875",
    "F3_DEV_20_a1p028125",
    "F3_DEV_21_a1p034375",
    "F3_DEV_22_a1p040625",
    "F3_DEV_24_a1p053125",
    "F3_DEV_25_a1p059375",
)
TRAIN_BINDINGS = tuple(
    {"case_id": case_id, "frame": frame}
    for case_id, frame in zip(
        TRAIN_CASE_IDS,
        (0, 56, 111, 167, 222, 278, 334, 389, 445, 500, 556, 612, 667, 723, 778, 834),
    )
)
NORMALIZATION_KEYS = {
    "available_transition_count",
    "requested_maximum_transitions",
    "schema",
    "selected_case_ids",
    "selected_transition_bindings",
    "selected_transition_count",
    "selected_transition_counts",
    "selection_policy",
    "selection_seed",
    "source_split",
    "target_reference",
    "train_case_ids",
}


class MatrixError(ValueError):
    """A malformed, incomplete, drifting, or unsafe evidence input."""


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


def _strict_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be boolean")
    return value


def _strict_int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


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


def _identity_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _resolve_path(root: Path, value: Path | str) -> Path:
    if not isinstance(value, (Path, str)):
        _fail(f"input path must be a path string: {value!r}")
    path = Path(value).expanduser()
    if ".." in path.parts:
        _fail(f"input path must not contain parent traversal: {path}")
    return (path if path.is_absolute() else root / path).resolve()


def _display_path(root: Path, path: Path) -> str:
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
        "exists": path.is_file(),
        "opened": opened,
        "bytes": None,
        "sha256": None,
        "schema": None,
    }
    if path.is_file():
        try:
            ref["bytes"] = path.stat().st_size
            # Only a bounded JSON input is ever read.  A declared checkpoint
            # or HDF5 path therefore remains metadata-only even on errors.
            if path.suffix.lower() == ".json" and path.stat().st_size <= MAX_JSON_BYTES:
                ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    if error:
        ref["error"] = error
    return ref


def read_bounded_json(root: Path, value: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one strict, small JSON object and no other artifact type."""

    path = _resolve_path(root, value)
    if path.suffix.lower() != ".json":
        _fail(f"only .json inputs are accepted: {path}")
    if path.is_symlink():
        _fail(f"symlink input is not accepted: {path}")
    if not path.is_file():
        _fail(f"missing JSON input: {path}")
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        _fail(f"JSON input exceeds {MAX_JSON_BYTES} bytes: {path}")
    raw = path.read_bytes()
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
    config = _mapping(receipt["config"], f"{name}.config")
    if config["manifest_formal_release"] is not False or config["validation_formal_eligible"] is not False:
        _fail(f"{name}.config formal markers must be false")
    evidence = _mapping(receipt["evidence"], f"{name}.evidence")
    prior = _mapping(evidence["residual_prior"], f"{name}.evidence.residual_prior")
    if prior.get("enabled") is not False or prior.get("execution_calls") != 0 or prior.get("rows") != 0:
        _fail(f"{name}.evidence.residual_prior must be disabled and zero")


def _validate_normalization(value: Mapping[str, Any], seed: int, name: str) -> Mapping[str, Any]:
    if set(value) != NORMALIZATION_KEYS:
        _fail(f"{name} keys drift")
    if value.get("schema") != NORMALIZATION_SCHEMA:
        _fail(f"{name}.schema drifts")
    _strict_int(value.get("available_transition_count"), f"{name}.available_transition_count", 16)
    if (
        value.get("requested_maximum_transitions") != 16
        or value.get("selected_transition_count") != 16
        or value.get("selection_policy") != "deterministic_evenly_spaced_train_transitions_v1"
        or value.get("selection_seed") != seed
        or value.get("source_split") != "train"
        or value.get("target_reference") != "raw_dual_increment_train_shared"
        or value.get("selected_case_ids") != list(TRAIN_CASE_IDS)
        or value.get("train_case_ids") != list(TRAIN_CASE_IDS)
        or value.get("selected_transition_bindings") != list(TRAIN_BINDINGS)
        or value.get("selected_transition_counts") != {case_id: 1 for case_id in TRAIN_CASE_IDS}
    ):
        _fail(f"{name} identity drifts")
    return value


def _run_id(seed: int) -> str:
    return f"f3-mlp500-hidden16-seed{seed}-20260928"


def _checkpoint_path(seed: int) -> str:
    return f"f3-mlp500-hidden16-seed{seed}-20260928-checkpoint.pt"


def _validate_training_receipt(receipt: Mapping[str, Any], seed: int) -> dict[str, Any]:
    name = f"training[{seed}]"
    if receipt.get("schema") != TRAINING_SCHEMA:
        _fail(f"{name}.schema must be {TRAINING_SCHEMA}")
    if receipt.get("evidence_status") != "complete":
        _fail(f"{name}.evidence_status must be complete")
    if "status" in receipt and receipt["status"] not in (None, "completed"):
        _fail(f"{name}.status must be completed when present")
    if receipt.get("model_kind") != MODEL_KIND:
        _fail(f"{name}.model_kind must be {MODEL_KIND}")
    if receipt.get("seed") != seed or receipt.get("completed_updates") != UPDATES:
        _fail(f"{name} seed/updates drift")
    parameter_count = _strict_int(receipt.get("parameter_count"), f"{name}.parameter_count", 1)
    if parameter_count != PARAMETER_COUNT:
        _fail(f"{name}.parameter_count must be {PARAMETER_COUNT}")
    if receipt.get("checkpoint_verified") is not True:
        _fail(f"{name}.checkpoint_verified must be true (declared metadata only)")

    config = _mapping(receipt.get("config"), f"{name}.config")
    expected_keys = set(STATIC_CONFIG) | OPERATIONAL_CONFIG_KEYS | DYNAMIC_CONFIG_KEYS
    if set(config) != expected_keys:
        _fail(f"{name}.config keys drift")
    for key, expected in STATIC_CONFIG.items():
        if config.get(key) != expected:
            _fail(f"{name}.config.{key} drifts")
    if type(config.get("evaluate_milestones")) is not bool:
        _fail(f"{name}.config.evaluate_milestones must be boolean")
    if config.get("milestone_evaluation_mode") not in ("in_process", "deferred"):
        _fail(f"{name}.config.milestone_evaluation_mode drifts")
    _strict_int(config.get("validation_every"), f"{name}.config.validation_every", 0)
    if config.get("seed") != seed or config.get("paired_seed") != seed or config.get("sampler_seed") != seed:
        _fail(f"{name}.config seed bindings drift")
    run_id = _run_id(seed)
    if config.get("run_id") != run_id or receipt.get("run_id") != run_id:
        _fail(f"{name}.run_id drifts")
    manifest_sha = _sha256(config.get("manifest_sha256"), f"{name}.config.manifest_sha256")

    evidence = _mapping(receipt.get("evidence"), f"{name}.evidence")
    if evidence.get("schema") != "core.training.evidence.v1" or evidence.get("status") != "complete":
        _fail(f"{name}.evidence schema/status is incomplete")
    initialization = _mapping(evidence.get("initialization"), f"{name}.evidence.initialization")
    if initialization.get("schema") != INITIALIZATION_SCHEMA or initialization.get("status") != "captured":
        _fail(f"{name}.initialization evidence is incomplete")
    if (
        initialization.get("model_kind") != MODEL_KIND
        or initialization.get("seed") != seed
        or initialization.get("hidden") != HIDDEN
        or initialization.get("parameter_count") != parameter_count
        or initialization.get("constructed_before_first_update") is not True
        or initialization.get("construction_update") != 0
    ):
        _fail(f"{name}.initialization evidence drifts")
    parameter_digest = _sha256(initialization.get("parameter_digest"), f"{name}.initialization.parameter_digest")

    normalization = _mapping(evidence.get("normalization"), f"{name}.evidence.normalization")
    _validate_normalization(normalization, seed, f"{name}.normalization")

    checkpoint = _mapping(receipt.get("checkpoint"), f"{name}.checkpoint")
    if checkpoint.get("schema") != CHECKPOINT_SCHEMA or checkpoint.get("update") != UPDATES:
        _fail(f"{name}.checkpoint schema/update drifts")
    checkpoint_path = _not_placeholder(_string(checkpoint.get("path"), f"{name}.checkpoint.path"), f"{name}.checkpoint.path")
    if (
        not checkpoint_path.startswith("/")
        or ".." in Path(checkpoint_path).parts
        or Path(checkpoint_path).name != _checkpoint_path(seed)
    ):
        _fail(f"{name}.checkpoint.path is not the expected declared MLP hidden16 seed namespace")
    checkpoint_sha = _sha256(checkpoint.get("sha256"), f"{name}.checkpoint.sha256")
    _validate_zero_authority_markers(receipt, name)

    shared_config = copy.deepcopy(STATIC_CONFIG)
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
        "config_identity_sha256": _identity_sha256(config),
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
        "normalization": copy.deepcopy(normalization),
        "normalization_identity_sha256": _identity_sha256(normalization),
        "shared_config": shared_config,
        "formal_eligible": False,
        "qualification_credit": 0,
    }


def _reference_shared_config() -> dict[str, Any]:
    return copy.deepcopy(STATIC_CONFIG)


def _validate_reference_matrix(value: Mapping[str, Any]) -> tuple[str, dict[int, Mapping[str, Any]]]:
    if value.get("schema") != REFERENCE_SCHEMA:
        _fail(f"reference matrix schema must be {REFERENCE_SCHEMA}")
    if value.get("report_id") != "f3-mlp-hidden16-seeds17-29-43-training-2026-09-28":
        _fail("reference matrix report_id drifts")
    if value.get("diagnostic_only") is not True or value.get("formal_eligible") is not False or value.get("model") != MODEL_KIND:
        _fail("reference matrix authorization markers drift")
    manifest_sha = _sha256(value.get("manifest_sha256"), "reference.manifest_sha256")
    shared = _mapping(value.get("shared_config"), "reference.shared_config")
    if dict(shared) != _reference_shared_config():
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
    runs = value.get("runs")
    if not isinstance(runs, list) or len(runs) != len(SEEDS):
        _fail("reference matrix must contain exactly three runs")
    result: dict[int, Mapping[str, Any]] = {}
    required_hashes = {
        "checkpoint_sha256",
        "training_receipt_sha256",
        "progress_receipt_sha256",
        "initialization_parameter_digest",
        "config_identity_sha256",
        "normalization_identity_sha256",
    }
    for row in runs:
        item = _mapping(row, "reference.run")
        seed = item.get("seed")
        if type(seed) is not int or seed in result or seed not in SEEDS:
            _fail("reference matrix seed set is not exactly 17, 29, 43")
        if (
            item.get("run_id") != _run_id(seed)
            or item.get("model_kind") != MODEL_KIND
            or item.get("hidden") != HIDDEN
            or item.get("completed_updates") != UPDATES
            or item.get("parameter_count") != PARAMETER_COUNT
            or item.get("checkpoint_verified") is not True
        ):
            _fail(f"reference run {seed} training identity drifts")
        if item.get("checkpoint_path") != _checkpoint_path(seed):
            _fail(f"reference run {seed} checkpoint path identity drifts")
        for key in required_hashes:
            _sha256(item.get(key), f"reference.run[{seed}].{key}")
        if item.get("normalization_transition_count") != 16:
            _fail(f"reference run {seed} normalization count drifts")
        result[seed] = item
    if set(result) != set(SEEDS):
        _fail("reference matrix seed set is incomplete")
    return manifest_sha, result


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason, "observed": observed, "expected": expected}


def _sorted_keys(value: Mapping[int, Any]) -> list[Any]:
    return sorted(value, key=lambda item: (type(item).__name__, repr(item)))


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
    exact_seed_set = observed_set == expected_set
    observed_keys = _sorted_keys(training_receipts)
    checks.append(_check("exact_seed_set", exact_seed_set, "training receipts must contain exactly seeds 17, 29, and 43", observed_keys, list(SEEDS)))
    if not exact_seed_set:
        errors.append(f"training seed set drift: observed {observed_keys} expected {list(SEEDS)}")

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
    checks.append(_check("reference_training_matrix_schema", reference_ok, "independent MLP hidden16 training matrix identity is valid"))

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
                projections[seed] = projection
                row["evidence"] = projection
                if not isinstance(training_sources.get(seed), Mapping):
                    _fail(f"seed{seed} training source metadata is missing")
                source_sha = training_sources[seed].get("sha256")
                _sha256(source_sha, f"seed{seed} training source.sha256")
                if reference_ok:
                    if seed not in reference_rows:
                        _fail(f"seed{seed} is absent from reference matrix")
                    reference = reference_rows[seed]
                    if source_sha != reference["training_receipt_sha256"]:
                        _fail(f"seed{seed} training receipt SHA drifts from reference matrix")
                    if projection["manifest_sha256"] != reference_manifest_sha:
                        _fail(f"seed{seed} manifest SHA drifts from reference matrix")
                    if projection["checkpoint"]["sha256"] != reference["checkpoint_sha256"]:
                        _fail(f"seed{seed} checkpoint SHA drifts from reference matrix")
                    if projection["checkpoint"]["path"] != f"/tmp/{reference['checkpoint_path']}":
                        _fail(f"seed{seed} checkpoint path drifts from reference matrix")
                    if projection["initialization"]["parameter_digest"] != reference["initialization_parameter_digest"]:
                        _fail(f"seed{seed} initialization digest drifts from reference matrix")
                    if projection["config_identity_sha256"] != reference["config_identity_sha256"]:
                        _fail(f"seed{seed} training config identity drifts from reference matrix")
                    if projection["normalization_identity_sha256"] != reference["normalization_identity_sha256"]:
                        _fail(f"seed{seed} normalization identity drifts from reference matrix")
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
    checks.append(_check("common_config", shared_config_ok, "all three receipts share one MLP hidden16 protocol configuration"))
    if not shared_config_ok:
        errors.append("training receipts do not provide one common MLP hidden16 configuration")

    manifest_shas = [projections[seed]["manifest_sha256"] for seed in SEEDS if seed in projections]
    manifest_unique = len(manifest_shas) == len(SEEDS) and len(set(manifest_shas)) == 1
    checks.append(_check("common_manifest_identity", manifest_unique, "all three receipts bind one manifest identity"))
    if not manifest_unique:
        errors.append("training receipts do not provide one common manifest identity")

    checkpoint_paths = [projections[seed]["checkpoint"]["path"] for seed in SEEDS if seed in projections]
    checkpoint_shas = [projections[seed]["checkpoint"]["sha256"] for seed in SEEDS if seed in projections]
    checkpoint_unique = (
        len(checkpoint_paths) == len(set(checkpoint_paths)) == len(SEEDS)
        and len(checkpoint_shas) == len(set(checkpoint_shas)) == len(SEEDS)
    )
    checks.append(_check("checkpoint_path_sha_unique", checkpoint_unique, "declared checkpoint path/SHA pairs are distinct per seed"))
    if not checkpoint_unique:
        errors.append("checkpoint path or SHA is duplicated/drifting across seeds")

    all_bound = (
        not errors
        and exact_seed_set
        and reference_ok
        and len(projections) == len(SEEDS)
        and shared_config_ok
        and manifest_unique
        and checkpoint_unique
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
            "parameter_count": PARAMETER_COUNT,
            "seeds": list(SEEDS),
            "evidence_status": "complete",
            "shared_config": STATIC_CONFIG,
            "normalization_transitions": 16,
            "checkpoint_content_opened": False,
            "hdf5_content_opened": False,
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
            "qualification": False,
            "qualification_credit": 0,
            "credit": 0,
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
            "manifest_opened": False,
            "checkpoint_opened": False,
            "hdf5_opened": False,
            "trajectory_opened": False,
            "progress_opened": False,
        },
        "scope_note": "bounded JSON receipt/schema/hash metadata only; independent MLP diagnostic and non-authorizing",
    }
    return report


def _missing_or_failed_source(root: Path, value: Path | str, error: Exception) -> dict[str, Any]:
    try:
        path = _resolve_path(root, value)
    except MatrixError:
        path = Path(str(value))
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
        except MatrixError as error:
            sources[seed] = _missing_or_failed_source(root, path, error)
            errors.append(f"seed{seed} source: {error}")
    try:
        reference, reference_source = read_bounded_json(root, reference_path)
    except MatrixError as error:
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


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate the report envelope without opening any source artifact."""

    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("report schema drift")
    if report.get("report_id") != REPORT_ID:
        errors.append("report id drift")
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
    for key in (
        "qualification_credit",
        "credit",
        "formal_training_runs_counted",
        "training_evidence_counted_as_formal_runs",
        "t1_case_runs_counted",
        "t2_macro_families_counted",
    ):
        if report.get(key) != 0:
            errors.append(f"{key} must be zero")
    authorization = report.get("authorization")
    if not isinstance(authorization, Mapping):
        errors.append("authorization must be an object")
    else:
        for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "qualification"):
            if authorization.get(key) is not False:
                errors.append(f"authorization.{key} must be false")
        if authorization.get("qualification_credit") != 0 or authorization.get("credit") != 0:
            errors.append("authorization credit must be zero")
    runs = report.get("runs")
    run_seeds = {row.get("seed") for row in runs if isinstance(row, Mapping)} if isinstance(runs, list) else set()
    if run_seeds != set(SEEDS):
        errors.append("report run seed set drift")
    side_effects = report.get("side_effects")
    if not isinstance(side_effects, Mapping):
        errors.append("side_effects must be an object")
    else:
        for key in ("registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation"):
            if side_effects.get(key) != 0:
                errors.append(f"side_effects.{key} must be zero")
        for key in (
            "completion_mutation",
            "runtime_started",
            "runtime_stopped",
            "runtime_restarted",
            "manifest_opened",
            "checkpoint_opened",
            "hdf5_opened",
            "trajectory_opened",
            "progress_opened",
        ):
            if side_effects.get(key) is not False:
                errors.append(f"side_effects.{key} must be false")
    return errors


def write_report(report: Mapping[str, Any], output: Path | str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_zh_cn(report: Mapping[str, Any]) -> str:
    rows = report.get("runs", [])
    lines = [
        "# F3 MLP hidden16 三 seed training evidence matrix V1",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- source-bound：`{report.get('source_bound')}`；fail-closed：`{report.get('fail_closed')}`",
        "- 范围：仅读取 bounded `core.training.v1` 与独立 MLP training-matrix JSON 的 schema/hash/小字段；不打开 manifest、checkpoint、case HDF5、trajectory 或 progress。",
        "- 授权：diagnostic-only；formal/T1/T2/qualification 均为 false，credit 与 formal training counted 均为 0。",
        "",
        "| seed | 状态 | model/hidden/updates | checkpoint | initialization | normalization |",
        "|---:|---|---|---|---|---|",
    ]
    for row in rows:
        evidence = row.get("evidence", {}) if isinstance(row, Mapping) else {}
        checkpoint = evidence.get("checkpoint", {}) if isinstance(evidence, Mapping) else {}
        initialization = evidence.get("initialization", {}) if isinstance(evidence, Mapping) else {}
        normalization = evidence.get("normalization", {}) if isinstance(evidence, Mapping) else {}
        lines.append(
            f"| {row.get('seed')} | `{row.get('status')}` | `mlp/16/500` | "
            f"`{checkpoint.get('path', 'missing')}` / `{checkpoint.get('sha256', 'missing')}` | "
            f"`{initialization.get('status', 'missing')}` / `{initialization.get('parameter_digest', 'missing')}` | "
            f"`{normalization.get('selected_transition_count', 'missing')}/16` |"
        )
    lines.extend([
        "",
        "本报告是独立、只读、非授权的 MLP training evidence 绑定；即使三份 receipt 完整，也不计入 formal 9 runs，不产生 T1/T2 或 qualification credit。",
        "",
    ])
    return "\n".join(lines)


def write_markdown(report: Mapping[str, Any], output: Path | str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_zh_cn(report), encoding="utf-8")


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
    parser.add_argument("--output", default="reports/F3-MLP-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.json")
    parser.add_argument("--markdown-output", default="reports/F3-MLP-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.zh-CN.md")
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
    print(json.dumps({"status": report["status"], "source_bound": report["source_bound"], "output": args.output}, ensure_ascii=False))
    return 0 if report["source_bound"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
