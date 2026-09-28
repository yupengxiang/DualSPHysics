#!/usr/bin/env python3
"""Reconcile bounded F3 graph_raw/hidden16 terminal candidates.

This is an independent, read-only evidence boundary.  It scans only the
first-level JSON candidates in /tmp and reports/.  It never opens a manifest,
checkpoint, case HDF5, trajectory, progress file, or any other non-JSON
artifact.  A complete three-way reconciliation remains diagnostic-only and
cannot authorize training, T1/T2, qualification, credit, or gate changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA = "core.f3.graph_raw.hidden16.terminal_candidate_reconciliation.v1"
REPORT_ID = "f3-graph-raw-hidden16-terminal-candidate-reconciliation-v1"
REPORT_FILENAME = "F3-GRAPH-RAW-HIDDEN16-TERMINAL-CANDIDATE-RECONCILIATION-V1-2026-09-28.json"
REPORT_ZH_FILENAME = (
    "F3-GRAPH-RAW-HIDDEN16-TERMINAL-CANDIDATE-RECONCILIATION-V1-2026-09-28.zh-CN.md"
)
SEEDS = (17, 29, 43)
MODEL_KIND = "graph_raw"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
MAX_JSON_BYTES = 1 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEED_RE = re.compile(r"(?:^|[-_])seed(?:[-_]?)(17|29|43)(?:$|[-_.])", re.IGNORECASE)
JSON_SUFFIXES = {".json"}
EXCLUDED_NAME_PARTS = (
    "progress",
    "manifest",
    "checkpoint",
    "trajectory",
    "hdf5-validation",
    "metric-summary",
    "evidence-pack",
    "source-verify",
    "vram-launch",
    "launch",
)
CANDIDATE_TOKENS = ("training", "evaluation", "evaluate", "rollout", "terminal")
TERMINAL_SCHEMAS = {
    "core.f3.graph_raw.hidden16.terminal_candidate.v1",
    "core.f3.graph_raw.hidden16.full835.rollout_diagnostic.summary.v1",
}


class ReconciliationError(ValueError):
    """Malformed or unsafe bounded evidence input."""


class DuplicateJSONKey(ReconciliationError):
    """A JSON object contains a duplicate key."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"duplicate JSON key: {key}")


def _reject_constant(token: str) -> None:
    raise ReconciliationError(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKey(key)
        result[key] = value
    return result


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _check_finite(value: Any, name: str = "value") -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReconciliationError(f"{name} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReconciliationError(f"{name} contains a non-string key")
            _check_finite(item, f"{name}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _check_finite(item, f"{name}[{index}]")
        return
    raise ReconciliationError(f"{name} contains unsupported value {type(value).__name__}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReconciliationError(f"{name} must be an object")
    return value


def _display_path(root: Path, path: Path) -> str:
    resolved = path.absolute()
    try:
        return resolved.relative_to(root.absolute()).as_posix()
    except ValueError:
        return str(resolved)


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ReconciliationError(f"{name} must be a lowercase SHA-256")
    return value


def _declared_path(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReconciliationError(f"{name} must be a non-empty path string")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ReconciliationError(f"{name} must be absolute and must not contain parent traversal")
    return str(path)


def _seed_from_name(path: Path) -> int | None:
    match = SEED_RE.search(path.name)
    return int(match.group(1)) if match else None


def _is_candidate_name(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in JSON_SUFFIXES:
        return False
    if any(part in name for part in EXCLUDED_NAME_PARTS):
        return False
    if _seed_from_name(path) not in SEEDS:
        return False
    if "graph-raw" not in name and "graph_raw" not in name:
        return False
    return any(token in name for token in CANDIDATE_TOKENS)


def _category_from_name(path: Path, payload: Mapping[str, Any] | None = None) -> str | None:
    name = path.name.lower()
    schema = str((payload or {}).get("schema", "")).lower()
    if "training" in name or schema == "core.training.v1":
        return "training"
    if "evaluation" in name or "evaluate" in name or schema == "core.evaluation.v1":
        return "evaluation"
    if "rollout" in name or "terminal" in name or "full835" in name:
        return "terminal"
    if "rollout" in schema or "terminal" in schema:
        return "terminal"
    return None


def _source_ref(
    root: Path,
    path: Path,
    *,
    opened: bool,
    raw: bytes | None = None,
    schema: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    symlink = path.is_symlink()
    exists = path.is_file() and not symlink
    result: dict[str, Any] = {
        "path": _display_path(root, path),
        "exists": exists,
        "symlink": symlink,
        "opened": opened,
        "bytes": len(raw) if raw is not None else (path.stat().st_size if exists else None),
        "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        "schema": schema,
    }
    if error:
        result["error"] = error
    return result


def _find_values(value: Any, wanted_keys: set[str], found: list[tuple[str, Any]], name: str = "value") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{name}.{key}"
            if key.lower() in wanted_keys:
                found.append((path, item))
            _find_values(item, wanted_keys, found, path)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _find_values(item, wanted_keys, found, f"{name}[{index}]")


def _legacy_hidden8(path: Path, payload: Mapping[str, Any] | None) -> bool:
    name = path.name.lower().replace("_", "")
    if "hidden8" in name:
        return True
    if payload is None:
        return False
    if "hidden8" in str(payload.get("schema", "")).lower().replace("_", ""):
        return True
    found: list[tuple[str, Any]] = []
    _find_values(payload, {"hidden", "hidden_size"}, found)
    return any(type(value) is int and value == 8 for _, value in found)


def _observed(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    result: dict[str, Any] = {}
    for key in (
        "schema",
        "status",
        "model",
        "model_kind",
        "hidden",
        "seed",
        "updates",
        "completed_updates",
        "transitions",
        "frames",
        "maximum_steps",
        "requested_steps",
        "frames_executed",
        "trajectory_frames_including_initial",
        "terminal_status",
        "formal",
        "formal_eligible",
        "diagnostic_only",
        "credit",
        "qualification_credit",
    ):
        if key in payload:
            result[key] = payload[key]
    for parent in ("config", "training", "evaluation", "checkpoint", "terminal_markers", "bindings"):
        value = payload.get(parent)
        if not isinstance(value, Mapping):
            continue
        compact: dict[str, Any] = {}
        for key in (
            "model",
            "model_kind",
            "hidden",
            "seed",
            "updates",
            "completed_updates",
            "transitions",
            "frames",
            "maximum_steps",
            "requested_steps",
            "frames_executed",
            "trajectory_frames_including_initial",
            "terminal_status",
            "path",
            "sha256",
            "checkpoint_sha256",
            "training_sha256",
            "evaluation_sha256",
            "terminal",
            "execution_complete",
            "finite_rollout_complete",
        ):
            if key in value:
                compact[key] = value[key]
        if compact:
            result[parent] = compact
    return result


def _authority_reasons(payload: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []

    def walk(value: Any, name: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                child = f"{name}.{key}"
                if key in {"formal", "formal_eligible", "qualification", "T1_numerical", "T2_macro", "T2_path"}:
                    if item is not False:
                        reasons.append(f"{child}_must_be_false")
                if key in {"credit", "qualification_credit", "T1_credit", "T2_credit", "T2_macro_credit"}:
                    if type(item) is not int or item != 0:
                        reasons.append(f"{child}_must_be_zero")
                walk(item, child)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, item in enumerate(value):
                walk(item, f"{name}[{index}]")

    walk(payload, "candidate")
    return sorted(set(reasons))


def _read_candidate(root: Path, path: Path) -> dict[str, Any]:
    category = _category_from_name(path)
    source_base = {
        "path": _display_path(root, path),
        "exists": path.is_file(),
        "opened": False,
        "bytes": None,
        "sha256": None,
        "schema": None,
    }
    result: dict[str, Any] = {
        "path": _display_path(root, path),
        "category": category or "unknown",
        "payload": None,
        "source": source_base,
        "parse_status": "not_opened",
        "parse_error": None,
    }
    if path.is_symlink():
        result["parse_status"] = "rejected"
        result["parse_error"] = "symlink_json_not_allowed"
        result["source"] = _source_ref(
            root, path, opened=False, schema=None, error=result["parse_error"]
        )
        return result
    try:
        size = path.stat().st_size
    except OSError as error:
        result["parse_status"] = "rejected"
        result["parse_error"] = f"stat_failed:{type(error).__name__}"
        result["source"] = dict(source_base, error=result["parse_error"])
        return result
    if size > MAX_JSON_BYTES:
        result["parse_status"] = "rejected"
        result["parse_error"] = f"bounded_json_size_exceeded:{size}>{MAX_JSON_BYTES}"
        result["source"] = _source_ref(
            root, path, opened=False, schema=None, error=result["parse_error"]
        )
        return result
    raw: bytes | None = None
    try:
        raw = path.read_bytes()
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
        payload = dict(_mapping(payload, str(path)))
        _check_finite(payload, str(path))
    except DuplicateJSONKey as error:
        result["parse_status"] = "rejected"
        result["parse_error"] = f"duplicate_json_key:{error.key}"
        result["source"] = _source_ref(
            root, path, opened=True, raw=raw, error=result["parse_error"]
        )
        return result
    except (OSError, UnicodeError, json.JSONDecodeError, ReconciliationError) as error:
        result["parse_status"] = "rejected"
        result["parse_error"] = f"invalid_bounded_json:{type(error).__name__}:{error}"
        result["source"] = _source_ref(
            root, path, opened=True, raw=raw, error=result["parse_error"]
        )
        return result
    result["payload"] = payload
    result["parse_status"] = "parsed"
    result["source"] = _source_ref(
        root, path, opened=True, raw=raw, schema=payload.get("schema")
    )
    result["category"] = _category_from_name(path, payload) or result["category"]
    return result


def discover_candidates(
    root: Path,
    candidate_roots: Sequence[Path] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    roots = list(candidate_roots) if candidate_roots is not None else [
        Path("/tmp"),
        root / "reports",
    ]
    paths: set[Path] = set()
    scan_errors: list[str] = []
    skipped_progress = 0
    for candidate_root in roots:
        try:
            entries = sorted(candidate_root.iterdir(), key=lambda item: item.name.lower())
        except OSError as error:
            scan_errors.append(f"{candidate_root}:{type(error).__name__}:{error}")
            continue
        for path in entries:
            if path.name in {REPORT_FILENAME, REPORT_ZH_FILENAME}:
                continue
            if path.is_file() and path.name.lower().endswith("progress.json"):
                skipped_progress += 1
            if _is_candidate_name(path):
                paths.add(path.absolute())
    candidates = [_read_candidate(root, path) for path in sorted(paths, key=lambda item: str(item))]
    inventory = {
        "candidate_roots": [_display_path(root, path) for path in roots],
        "scanned_candidate_files": len(candidates),
        "bounded_json_opened": sum(1 for item in candidates if item["source"]["opened"]),
        "bounded_json_not_opened": sum(1 for item in candidates if not item["source"]["opened"]),
        "oversize_json_not_opened": sum(
            1
            for item in candidates
            if str(item.get("parse_error", "")).startswith("bounded_json_size_exceeded:")
        ),
        "progress_files_skipped": skipped_progress,
        "scan_errors": scan_errors,
    }
    return candidates, inventory


def _missing(value: Mapping[str, Any], key: str, name: str, reasons: list[str]) -> Any:
    if key not in value:
        reasons.append(f"{name}_missing")
        return None
    return value[key]


def _check_exact(
    value: Mapping[str, Any],
    key: str,
    expected: Any,
    name: str,
    reasons: list[str],
) -> Any:
    observed = _missing(value, key, name, reasons)
    if key in value and observed != expected:
        reasons.append(f"{name}_drift:observed={observed!r}:expected={expected!r}")
    return observed


def _validate_training(
    item: dict[str, Any],
    seed: int,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    payload = item.get("payload")
    reasons: list[str] = []
    if item["parse_status"] != "parsed" or not isinstance(payload, Mapping):
        return False, None, [item.get("parse_error") or "candidate_not_parsed"]
    if _legacy_hidden8(Path(item["path"]), payload):
        reasons.append("legacy_hidden8_drift")
    if payload.get("schema") != "core.training.v1":
        reasons.append(f"schema_drift:observed={payload.get('schema')!r}:expected='core.training.v1'")
    _check_exact(payload, "model_kind", MODEL_KIND, "model_kind", reasons)
    _check_exact(payload, "seed", seed, "seed", reasons)
    _check_exact(payload, "completed_updates", UPDATES, "completed_updates", reasons)
    config = payload.get("config")
    if not isinstance(config, Mapping):
        reasons.append("config_missing_or_not_object")
        config = {}
    _check_exact(config, "model_kind", MODEL_KIND, "config.model_kind", reasons)
    _check_exact(config, "hidden", HIDDEN, "config.hidden", reasons)
    _check_exact(config, "seed", seed, "config.seed", reasons)
    _check_exact(config, "updates", UPDATES, "config.updates", reasons)
    if payload.get("evidence_status") != "complete":
        reasons.append(f"evidence_status_drift:observed={payload.get('evidence_status')!r}")
    if payload.get("checkpoint_verified") is not True:
        reasons.append("checkpoint_verified_must_be_true")
    checkpoint = payload.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        reasons.append("checkpoint_binding_missing_or_not_object")
        checkpoint = {}
    checkpoint_path = _missing(checkpoint, "path", "checkpoint.path", reasons)
    checkpoint_sha = _missing(checkpoint, "sha256", "checkpoint.sha256", reasons)
    checkpoint_update = _check_exact(checkpoint, "update", UPDATES, "checkpoint.update", reasons)
    if checkpoint_path is not None:
        try:
            checkpoint_path = _declared_path(checkpoint_path, "checkpoint.path")
        except ReconciliationError as error:
            reasons.append(str(error))
    if checkpoint_sha is not None:
        try:
            checkpoint_sha = _sha256(checkpoint_sha, "checkpoint.sha256")
        except ReconciliationError as error:
            reasons.append(str(error))
    reasons.extend(_authority_reasons(payload))
    if reasons:
        return False, None, sorted(set(reasons))
    return True, {
        "source_path": item["source"]["path"],
        "source_sha256": item["source"]["sha256"],
        "checkpoint_path": checkpoint_path,
        "checkpoint_sha256": checkpoint_sha,
        "checkpoint_update": checkpoint_update,
    }, []


def _validate_evaluation(
    item: dict[str, Any],
    seed: int,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    payload = item.get("payload")
    reasons: list[str] = []
    if item["parse_status"] != "parsed" or not isinstance(payload, Mapping):
        return False, None, [item.get("parse_error") or "candidate_not_parsed"]
    if _legacy_hidden8(Path(item["path"]), payload):
        reasons.append("legacy_hidden8_drift")
    if payload.get("schema") != "core.evaluation.v1":
        reasons.append(f"schema_drift:observed={payload.get('schema')!r}:expected='core.evaluation.v1'")
    _check_exact(payload, "model_kind", MODEL_KIND, "model_kind", reasons)
    _check_exact(payload, "hidden", HIDDEN, "hidden", reasons)
    _check_exact(payload, "seed", seed, "seed", reasons)
    _check_exact(payload, "updates", UPDATES, "updates", reasons)
    _check_exact(payload, "maximum_steps", TRANSITIONS, "maximum_steps", reasons)
    transitions = payload.get("transitions", payload.get("frames_executed"))
    frames = payload.get("frames", payload.get("trajectory_frames_including_initial"))
    if transitions != TRANSITIONS:
        reasons.append(f"transitions_drift:observed={transitions!r}:expected={TRANSITIONS}")
    if frames != FRAMES:
        reasons.append(f"frames_drift:observed={frames!r}:expected={FRAMES}")
    status = payload.get("status", payload.get("evaluation_status"))
    if status not in {"completed", "completed_diagnostic"}:
        reasons.append(f"evaluation_status_not_terminal:observed={status!r}")
    reasons.extend(_authority_reasons(payload))
    if reasons:
        return False, None, sorted(set(reasons))
    return True, {
        "source_path": item["source"]["path"],
        "source_sha256": item["source"]["sha256"],
        "transitions": transitions,
        "frames": frames,
    }, []


def _binding(payload: Mapping[str, Any], kind: str) -> Mapping[str, Any] | None:
    bindings = payload.get("bindings")
    if isinstance(bindings, Mapping) and isinstance(bindings.get(kind), Mapping):
        return bindings[kind]
    direct = payload.get(kind)
    if isinstance(direct, Mapping):
        return direct
    path_key = f"{kind}_path"
    sha_key = f"{kind}_sha256"
    if path_key in payload or sha_key in payload:
        return {"path": payload.get(path_key), "sha256": payload.get(sha_key)}
    return None


def _validate_binding(
    payload: Mapping[str, Any],
    kind: str,
    reasons: list[str],
) -> dict[str, str] | None:
    value = _binding(payload, kind)
    if value is None:
        reasons.append(f"{kind}_binding_missing_or_not_object")
        return None
    path = _missing(value, "path", f"{kind}.path", reasons)
    sha = _missing(value, "sha256", f"{kind}.sha256", reasons)
    normalized: dict[str, str] = {}
    if path is not None:
        try:
            normalized["path"] = _declared_path(path, f"{kind}.path")
        except ReconciliationError as error:
            reasons.append(str(error))
    if sha is not None:
        try:
            normalized["sha256"] = _sha256(sha, f"{kind}.sha256")
        except ReconciliationError as error:
            reasons.append(str(error))
    return normalized if len(normalized) == 2 else None


def _validate_terminal(
    item: dict[str, Any],
    seed: int,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    payload = item.get("payload")
    reasons: list[str] = []
    if item["parse_status"] != "parsed" or not isinstance(payload, Mapping):
        return False, None, [item.get("parse_error") or "candidate_not_parsed"]
    if _legacy_hidden8(Path(item["path"]), payload):
        reasons.append("legacy_hidden8_drift")
    schema = payload.get("schema")
    accepted_schemas = set(TERMINAL_SCHEMAS)
    accepted_schemas.add(f"core.f3.graph_raw.hidden16.seed{seed}.full835.rollout_diagnostic.summary.v1")
    if schema not in accepted_schemas:
        reasons.append(f"schema_drift:observed={schema!r}:expected_hidden16_terminal_schema")
    _check_exact(payload, "model_kind", MODEL_KIND, "model_kind", reasons)
    _check_exact(payload, "hidden", HIDDEN, "hidden", reasons)
    _check_exact(payload, "seed", seed, "seed", reasons)
    _check_exact(payload, "updates", UPDATES, "updates", reasons)
    _check_exact(payload, "transitions", TRANSITIONS, "transitions", reasons)
    _check_exact(payload, "frames", FRAMES, "frames", reasons)
    if payload.get("status") not in {"completed", "completed_diagnostic"}:
        reasons.append(f"terminal_status_not_completed:observed={payload.get('status')!r}")
    markers = payload.get("terminal_markers")
    if not isinstance(markers, Mapping):
        reasons.append("terminal_markers_missing_or_not_object")
        markers = {}
    _check_exact(markers, "terminal", True, "terminal_markers.terminal", reasons)
    _check_exact(
        markers, "execution_complete", True, "terminal_markers.execution_complete", reasons
    )
    _check_exact(
        markers,
        "finite_rollout_complete",
        True,
        "terminal_markers.finite_rollout_complete",
        reasons,
    )
    _check_exact(
        markers, "terminal_status", "completed", "terminal_markers.terminal_status", reasons
    )
    if markers.get("progress_is_not_completion") is not True:
        reasons.append("terminal_markers.progress_is_not_completion_must_be_true")
    normalized_bindings: dict[str, dict[str, str]] = {}
    for kind in ("checkpoint", "training", "evaluation"):
        binding = _validate_binding(payload, kind, reasons)
        if binding is not None:
            normalized_bindings[kind] = binding
    output = payload.get("output")
    if not isinstance(output, Mapping):
        reasons.append("output_missing_or_not_object")
    else:
        namespace = output.get("fresh_output_namespace")
        if not isinstance(namespace, str) or f"seed{seed}" not in namespace or "hidden16" not in namespace:
            reasons.append("output.fresh_output_namespace_drift")
    for key, expected in (
        ("diagnostic_only", True),
        ("formal_eligible", False),
        ("qualification", False),
        ("T1_numerical", False),
        ("T2_macro", False),
        ("T2_path", False),
    ):
        _check_exact(payload, key, expected, key, reasons)
    if payload.get("credit") != 0 or payload.get("qualification_credit") != 0:
        reasons.append("terminal_credit_must_be_zero")
    reasons.extend(_authority_reasons(payload))
    if reasons:
        return False, None, sorted(set(reasons))
    return True, {
        "source_path": item["source"]["path"],
        "source_sha256": item["source"]["sha256"],
        "bindings": normalized_bindings,
    }, []


def _path_equal(left: str, right: str) -> bool:
    try:
        return str(Path(left).resolve()) == str(Path(right).resolve())
    except (OSError, RuntimeError):
        return left == right


def _reconcile_seed(
    seed: int,
    candidates: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    relevant = [item for item in candidates if _seed_from_name(Path(item["path"])) == seed]
    evaluated: list[dict[str, Any]] = []
    valid_by_category: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {
        "training": [],
        "evaluation": [],
        "terminal": [],
    }
    for item in relevant:
        category = item["category"]
        if category not in valid_by_category:
            continue
        if category == "training":
            valid, normalized, reasons = _validate_training(item, seed)
        elif category == "evaluation":
            valid, normalized, reasons = _validate_evaluation(item, seed)
        else:
            valid, normalized, reasons = _validate_terminal(item, seed)
        row = {
            "path": item["path"],
            "category": category,
            "parse_status": item["parse_status"],
            "validation_status": "valid" if valid else "rejected",
            "source": item["source"],
            "observed": _observed(item.get("payload")),
            "reasons": reasons,
        }
        evaluated.append(row)
        if valid and normalized is not None:
            valid_by_category[category].append((item, normalized))
    category_status: dict[str, str] = {}
    reasons: list[str] = []
    for category in ("training", "evaluation", "terminal"):
        rows = [row for row in evaluated if row["category"] == category]
        valid = valid_by_category[category]
        if len(valid) == 1:
            category_status[category] = "accepted"
        elif len(valid) > 1:
            category_status[category] = "rejected"
            reasons.append(f"duplicate_valid_{category}_candidates")
        elif rows:
            category_status[category] = "rejected"
        else:
            category_status[category] = "missing"
            reasons.append(f"missing_{category}_candidate")
    accepted = all(value == "accepted" for value in category_status.values())
    bindings: dict[str, Any] = {}
    if accepted:
        training = valid_by_category["training"][0][1]
        evaluation = valid_by_category["evaluation"][0][1]
        terminal = valid_by_category["terminal"][0][1]
        bindings = {
            "training": training,
            "evaluation": evaluation,
            "terminal": terminal,
        }
        terminal_bindings = terminal["bindings"]
        expected = {
            "checkpoint": {
                "path": training["checkpoint_path"],
                "sha256": training["checkpoint_sha256"],
            },
            "training": {
                "path": training["source_path"],
                "sha256": training["source_sha256"],
            },
            "evaluation": {
                "path": evaluation["source_path"],
                "sha256": evaluation["source_sha256"],
            },
        }
        for kind, expected_binding in expected.items():
            observed = terminal_bindings.get(kind)
            if observed is None:
                reasons.append(f"terminal_{kind}_binding_missing")
                continue
            if not _path_equal(observed["path"], expected_binding["path"]):
                reasons.append(f"{kind}_path_sha_binding_path_drift")
            if observed["sha256"] != expected_binding["sha256"]:
                reasons.append(f"{kind}_sha256_binding_drift")
        if reasons:
            accepted = False
    if not accepted and not reasons:
        reasons.append("no_complete_training_evaluation_terminal_triple")
    for row in evaluated:
        if row["validation_status"] == "valid" and not accepted:
            row["reasons"] = sorted(set(row["reasons"] + ["seed_reconciliation_not_accepted"]))
    for row in evaluated:
        for reason in row["reasons"]:
            if reason != "seed_reconciliation_not_accepted":
                reasons.append(f"{row['category']}:{reason}")
    if accepted:
        status = "accepted"
    elif not relevant:
        status = "missing"
    elif reasons:
        status = "rejected"
    elif any(value == "rejected" for value in category_status.values()):
        status = "rejected"
    else:
        status = "missing"
    return {
        "seed": seed,
        "status": status,
        "category_status": category_status,
        "candidate_count": len(evaluated),
        "candidates": sorted(evaluated, key=lambda row: (row["category"], row["path"])),
        "reasons": sorted(set(reasons)),
        "bindings": bindings,
    }


def _zero_authority() -> dict[str, Any]:
    return {
        "formal_training_runs_counted": 0,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
    }


def _side_effects() -> dict[str, Any]:
    return {
        "manifest_opened": False,
        "checkpoint_opened": False,
        "case_hdf5_opened": False,
        "trajectory_opened": False,
        "progress_opened": False,
        "runtime_started": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
    }


def build_report(
    root: Path = LAB_ROOT,
    *,
    candidate_roots: Sequence[Path] | None = None,
    observed_at_utc: str = "2026-09-28T00:00:00Z",
) -> dict[str, Any]:
    root = Path(root).resolve()
    candidates, inventory = discover_candidates(root, candidate_roots)
    seed_matrix = [_reconcile_seed(seed, candidates) for seed in SEEDS]
    source_bound = all(row["status"] == "accepted" for row in seed_matrix)
    status = (
        "bound_terminal_candidate_diagnostic_only"
        if source_bound
        else "blocked_fail_closed"
    )
    errors = [
        f"seed{row['seed']}: {reason}"
        for row in seed_matrix
        for reason in row["reasons"]
    ]
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc,
        "status": status,
        "source_bound": source_bound,
        "fail_closed": not source_bound,
        "scope": {
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "updates": UPDATES,
            "seeds": list(SEEDS),
            "transitions": TRANSITIONS,
            "frames": FRAMES,
        },
        "candidate_inventory": inventory,
        "seed_matrix": seed_matrix,
        "errors": sorted(set(errors)),
        "authorization": _zero_authority(),
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "manifest_opened": False,
            "checkpoint_opened": False,
            "case_hdf5_opened": False,
            "trajectory_opened": False,
            "progress_opened": False,
            "non_json_opened": False,
        },
        "side_effects": _side_effects(),
        "interpretation": (
            "This independent reconciliation binds only bounded training, "
            "evaluation, and terminal JSON candidates. Even a complete "
            "three-seed binding remains diagnostic-only and cannot mint "
            "formal, T1, T2, qualification, or credit."
        ),
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append("schema mismatch")
    if report.get("report_id") != REPORT_ID:
        errors.append("report_id mismatch")
    if report.get("scope") != {
        "model_kind": MODEL_KIND,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seeds": list(SEEDS),
        "transitions": TRANSITIONS,
        "frames": FRAMES,
    }:
        errors.append("scope mismatch")
    if report.get("diagnostic_only") is not True:
        errors.append("diagnostic_only must be true")
    for key in ("formal", "formal_eligible", "T1_numerical", "T2_macro", "T2_path", "qualification"):
        if report.get(key) is not False:
            errors.append(f"{key} must be false")
    for key in ("credit", "qualification_credit"):
        if report.get(key) != 0:
            errors.append(f"{key} must be zero")
    authorization = report.get("authorization")
    if not isinstance(authorization, Mapping):
        errors.append("authorization must be an object")
    else:
        if authorization.get("credit") != 0 or authorization.get("qualification_credit") != 0:
            errors.append("authorization credit must be zero")
        if authorization.get("formal_training_runs_counted") != 0:
            errors.append("formal training count must be zero")
    matrix = report.get("seed_matrix")
    if not isinstance(matrix, list) or [row.get("seed") for row in matrix] != list(SEEDS):
        errors.append("seed matrix must contain exactly seeds 17,29,43")
    else:
        for row in matrix:
            if row.get("status") not in {"accepted", "rejected", "missing"}:
                errors.append(f"seed{row.get('seed')} status invalid")
            category_status = row.get("category_status")
            if not isinstance(category_status, Mapping) or set(category_status) != {
                "training",
                "evaluation",
                "terminal",
            }:
                errors.append(f"seed{row.get('seed')} category status invalid")
    boundary = report.get("input_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("input_boundary must be an object")
    else:
        for key in (
            "manifest_opened",
            "checkpoint_opened",
            "case_hdf5_opened",
            "trajectory_opened",
            "progress_opened",
            "non_json_opened",
        ):
            if boundary.get(key) is not False:
                errors.append(f"input_boundary.{key} must be false")
    side_effects = report.get("side_effects")
    if not isinstance(side_effects, Mapping):
        errors.append("side_effects must be an object")
    else:
        for key, value in side_effects.items():
            if key.endswith("_mutation") and value != 0:
                errors.append(f"{key} must be zero")
            if key.endswith("_opened") or key.endswith("_started"):
                if value is not False:
                    errors.append(f"{key} must be false")
    source_bound = report.get("source_bound") is True
    if report.get("fail_closed") is not (not source_bound):
        errors.append("fail_closed/source_bound mismatch")
    expected_status = (
        "bound_terminal_candidate_diagnostic_only"
        if source_bound
        else "blocked_fail_closed"
    )
    if report.get("status") != expected_status:
        errors.append("status/source_bound mismatch")
    return errors


def render_zh_cn(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_raw hidden16 terminal-candidate reconciliation V1",
        "",
        f"- 状态：'{report.get('status')}'；source-bound：'{report.get('source_bound')}'。",
        "- 约束：只读取有界 JSON；不打开 manifest、checkpoint、case HDF5、trajectory 或 progress。",
        "- 固定配置：model='graph_raw'，hidden='16'，updates='500'，835 transitions / 836 frames。",
        "- 即使三 seed 全部 accepted，也只保留 diagnostic-only，formal/T1/T2/credit 均为 false/0。",
        "",
        "| seed | overall | training | evaluation | terminal | 原因摘要 |",
        "|---:|---|---|---|---|---|",
    ]
    for row in report.get("seed_matrix", []):
        reasons = "; ".join(row.get("reasons", [])) or "none"
        lines.append(
            f"| {row.get('seed')} | '{row.get('status')}' | "
            f"'{row.get('category_status', {}).get('training')}' | "
            f"'{row.get('category_status', {}).get('evaluation')}' | "
            f"'{row.get('category_status', {}).get('terminal')}' | {reasons} |"
        )
    lines.extend(
        [
            "",
            "## 边界与副作用",
            "",
            f"- 扫描候选文件：'{report.get('candidate_inventory', {}).get('scanned_candidate_files')}'；"
            f"打开有界 JSON：'{report.get('candidate_inventory', {}).get('bounded_json_opened')}'。",
            f"- 超过 1 MiB 而未打开：'{report.get('candidate_inventory', {}).get('oversize_json_not_opened')}'。",
            "- manifest/checkpoint/case HDF5/trajectory/progress：均未打开；runtime/solver/worker/GPU：均未启动。",
            "- registry/ledger/denominator/gate mutation：均为 0。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    report: Mapping[str, Any],
    output: Path | str,
    zh_output: Path | str,
) -> None:
    output_path = Path(output)
    zh_path = Path(zh_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    zh_path.write_text(render_zh_cn(report), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument(
        "--candidate-root",
        action="append",
        type=Path,
        default=None,
        help="repeatable first-level directory containing candidate JSON files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=LAB_ROOT / "reports" / REPORT_FILENAME,
    )
    parser.add_argument(
        "--zh-output",
        type=Path,
        default=LAB_ROOT / "reports" / REPORT_ZH_FILENAME,
    )
    parser.add_argument("--observed-at-utc", default="2026-09-28T00:00:00Z")
    args = parser.parse_args(argv)
    report = build_report(
        args.root,
        candidate_roots=args.candidate_root,
        observed_at_utc=args.observed_at_utc,
    )
    write_outputs(report, args.output, args.zh_output)
    errors = validate_report(report)
    if errors:
        raise SystemExit("report validation failed: " + "; ".join(errors))
    print(
        json.dumps(
            {
                "status": report["status"],
                "source_bound": report["source_bound"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["source_bound"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
