#!/usr/bin/env python3
"""Bind F3 MLP/hidden16 training receipts to an explicitly supplied manifest.

This is an additive, non-authorizing intake boundary.  It consumes only three
bounded JSON training receipts and one explicitly supplied manifest path.  It
hashes and parses the manifest, validates declared receipt/checkpoint identity
metadata, and never opens checkpoint or HDF5 content.  It does not import or
rewrite the historical V1 training matrix, summaries, registry, ledger, or
formal gates.

The only successful status is ``diagnostic_bound``.  Every report is
diagnostic-only and zero-credit; an incomplete or drifting input set is
``blocked_fail_closed``.
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
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
SCHEMA = "core.f3.mlp.hidden16.current_manifest_training_evidence.v1"
REPORT_ID = "f3-mlp-hidden16-current-manifest-training-evidence-v1"

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_ARRAY_ITEMS = 4096
MAX_STRING_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PROTECTED_V1_MATRIX = (
    LAB_ROOT / "reports/F3-MLP-HIDDEN16-TRAINING-EVIDENCE-MATRIX-V1-2026-09-28.json"
).resolve()


class IntakeError(ValueError):
    """Malformed, unsafe, incomplete, or cross-file-inconsistent input."""


def _fail(message: str) -> None:
    raise IntakeError(f"fail-closed: {message}")


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


def _sha256(value: Any, name: str) -> str:
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


def _reject_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor or os.curdir)
    components = absolute.parts[1:] if absolute.is_absolute() else absolute.parts
    for component in components:
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
    if isinstance(value, Path):
        raw = str(value)
    elif isinstance(value, str):
        raw = value
    else:
        _fail(f"{name} must be a path")
    if not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    candidate = Path(raw).expanduser()
    if ".." in candidate.parts:
        _fail(f"{name} contains a lexical parent traversal")
    path = Path(os.path.abspath(candidate if candidate.is_absolute() else root / candidate))
    allowed_roots = (Path(os.path.abspath(root)), Path("/tmp"))
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        _fail(f"{name} escapes bounded input roots")
    _reject_symlink_components(path)
    return path


def _read_bounded_bytes(
    root: Path,
    value: Path | str,
    *,
    name: str,
    max_bytes: int,
    require_json_suffix: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    path = _resolve_input_path(root, value, name)
    if require_json_suffix and path.suffix.lower() != ".json":
        _fail(f"{name} must be a JSON file")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        _fail(f"{name} cannot be opened: {error}")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{name} is not a regular file")
        if before.st_size > max_bytes:
            _fail(f"{name} exceeds bounded size {max_bytes}")
        raw = b""
        while len(raw) <= max_bytes:
            block = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - len(raw)))
            if not block:
                break
            raw += block
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            _fail(f"{name} changed while being read")
    except OSError as error:
        _fail(f"{name} cannot be read: {error}")
    finally:
        os.close(descriptor)
    if len(raw) > max_bytes:
        _fail(f"{name} exceeds bounded size {max_bytes}")
    return raw, {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "opened": True,
    }


def read_bounded_json(
    root: Path | str,
    value: Path | str,
    *,
    name: str = "input",
    max_bytes: int = MAX_JSON_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one bounded JSON object and return payload plus actual file identity."""

    root_path = Path(root).expanduser()
    raw, source = _read_bounded_bytes(
        root_path,
        value,
        name=name,
        max_bytes=max_bytes,
    )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{name} is not valid UTF-8 JSON: {error}")
    _walk_json(payload, name)
    if not isinstance(payload, dict):
        _fail(f"{name} must contain a JSON object")
    source["schema"] = payload.get("schema")
    return payload, source


def _validate_zero_credit(receipt: Mapping[str, Any], name: str) -> None:
    for key in (
        "formal",
        "formal_eligible",
        "qualification",
        "T1_numerical",
        "T2_macro",
        "T2_path",
    ):
        if key in receipt and receipt[key] is not False:
            _fail(f"{name}.{key} must be false")
    for key in ("credit", "qualification_credit"):
        if key in receipt and (type(receipt[key]) is not int or receipt[key] != 0):
            _fail(f"{name}.{key} must be integer zero")
    config = _mapping(receipt.get("config"), f"{name}.config")
    _exact(config, "manifest_formal_release", False, f"{name}.config")
    _exact(config, "validation_formal_eligible", False, f"{name}.config")
    if "diagnostic_only" in receipt:
        _exact(receipt, "diagnostic_only", True, name)


def _checkpoint_identity(value: Any, name: str) -> dict[str, Any]:
    checkpoint = _mapping(value, name)
    _exact(checkpoint, "schema", CHECKPOINT_SCHEMA, name)
    update = _strict_int(checkpoint.get("update"), f"{name}.update")
    if update != UPDATES:
        _fail(f"{name}.update must be {UPDATES}")
    path_text = _string(checkpoint.get("path"), f"{name}.path")
    path = Path(path_text)
    if not path.is_absolute() or ".." in path.parts:
        _fail(f"{name}.path must be an absolute lexical-safe path")
    if path.suffix.lower() == ".json":
        _fail(f"{name}.path must not point to a JSON receipt")
    declared_bytes = _strict_int(checkpoint.get("bytes"), f"{name}.bytes", 1)
    digest = _sha256(checkpoint.get("sha256"), f"{name}.sha256")
    return {
        "schema": CHECKPOINT_SCHEMA,
        "path": path_text,
        "bytes": declared_bytes,
        "sha256": digest,
        "update": UPDATES,
    }


def _validate_receipt(
    receipt: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    seed: int,
    manifest_sha256: str,
) -> dict[str, Any]:
    name = f"seed{seed}"
    _walk_json(receipt, f"training receipt {seed}")
    _exact(receipt, "schema", TRAINING_SCHEMA, name)
    _exact(receipt, "evidence_status", "complete", name)
    _exact(receipt, "status", "completed", name)
    receipt_model = receipt.get("model_kind", receipt.get("model"))
    if receipt_model != MODEL:
        _fail(f"{name}.model/model_kind must be {MODEL}")
    if "model_kind" in receipt:
        _exact(receipt, "model_kind", MODEL, name)
    if "model" in receipt:
        _exact(receipt, "model", MODEL, name)
    if _strict_int(receipt.get("seed"), f"{name}.seed") != seed:
        _fail(f"{name}.seed does not match its receipt slot")
    if _strict_int(receipt.get("completed_updates"), f"{name}.completed_updates") != UPDATES:
        _fail(f"{name}.completed_updates must be {UPDATES}")
    _exact(receipt, "checkpoint_verified", True, name)

    run_id = _string(receipt.get("run_id"), f"{name}.run_id")
    config = _mapping(receipt.get("config"), f"{name}.config")
    _exact(config, "manifest_sha256", manifest_sha256, f"{name}.config")
    config_model = config.get("model_kind", config.get("model"))
    if config_model != MODEL:
        _fail(f"{name}.config.model/model_kind must be {MODEL}")
    if "model_kind" in config:
        _exact(config, "model_kind", MODEL, f"{name}.config")
    _exact(config, "hidden", HIDDEN, f"{name}.config")
    _exact(config, "updates", UPDATES, f"{name}.config")
    _exact(config, "run_id", run_id, f"{name}.config")
    _exact(config, "seed", seed, f"{name}.config")
    for key in ("paired_seed", "sampler_seed"):
        if key in config:
            _exact(config, key, seed, f"{name}.config")
    if "model" in config:
        _exact(config, "model", MODEL, f"{name}.config")

    _validate_zero_credit(receipt, name)
    checkpoint = _checkpoint_identity(receipt.get("checkpoint"), f"{name}.checkpoint")
    if checkpoint["path"] == source.get("path"):
        _fail(f"{name}.checkpoint.path aliases the training receipt")
    checkpoints = receipt.get("checkpoints")
    if checkpoints is not None:
        if not isinstance(checkpoints, list) or not checkpoints:
            _fail(f"{name}.checkpoints must be a non-empty array when present")
        for index, item in enumerate(checkpoints):
            _checkpoint_identity(item, f"{name}.checkpoints[{index}]")
        terminal = _checkpoint_identity(checkpoints[-1], f"{name}.checkpoints[-1]")
        if terminal != checkpoint:
            _fail(f"{name}.checkpoint identity drifts from terminal checkpoints entry")

    return {
        "seed": seed,
        "run_id": run_id,
        "schema": TRAINING_SCHEMA,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "completed": True,
        "manifest_sha256": manifest_sha256,
        "receipt_identity": {
            "path": source.get("path"),
            "bytes": source.get("bytes"),
            "sha256": source.get("sha256"),
        },
        "checkpoint_identity": checkpoint,
        "zero_credit": {
            "diagnostic_only": True,
            "formal": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "credit": 0,
        },
    }


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


def _empty_source(value: Path | str | None) -> dict[str, Any]:
    return {
        "path": str(value) if value is not None else "<missing>",
        "bytes": None,
        "sha256": None,
        "opened": False,
    }


def _manifest_record(
    source: Mapping[str, Any] | None,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = dict(source or {})
    result.setdefault("path", "<missing>")
    result.setdefault("bytes", None)
    result.setdefault("sha256", None)
    result.setdefault("opened", False)
    result["schema"] = payload.get("schema") if payload is not None else None
    return result


def build_report(
    manifest_path: Path | str,
    training_receipts: Mapping[int, Path | str],
    *,
    root: Path | str = LAB_ROOT,
    observed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build a current-manifest diagnostic report without touching binary data."""

    root_path = Path(root).expanduser()
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    manifest_payload: dict[str, Any] | None = None
    manifest_source: dict[str, Any] | None = None
    manifest_sha256: str | None = None

    try:
        manifest_payload, manifest_source = read_bounded_json(
            root_path,
            manifest_path,
            name="manifest",
            max_bytes=MAX_MANIFEST_BYTES,
        )
        manifest_sha256 = str(manifest_source["sha256"])
        checks.append(
            _check(
                "manifest_file_sha256",
                True,
                "manifest bytes were hashed from the explicit path",
                manifest_sha256,
                "lowercase SHA-256 of the actual manifest file",
            )
        )
    except IntakeError as error:
        errors.append(str(error))
        try:
            path = _resolve_input_path(root_path, manifest_path, "manifest")
            manifest_source = _empty_source(path)
        except IntakeError:
            manifest_source = _empty_source(manifest_path)
        checks.append(
            _check(
                "manifest_file_sha256",
                False,
                "explicit manifest could not be read and hashed",
                None,
                "readable bounded JSON manifest",
            )
        )

    manifest_record = _manifest_record(manifest_source, manifest_payload)
    manifest_ok = manifest_payload is not None and manifest_sha256 is not None
    if manifest_payload is not None and not isinstance(manifest_payload, Mapping):
        manifest_ok = False
        errors.append("fail-closed: manifest must be a JSON object")

    observed_keys = sorted(
        training_receipts.keys(),
        key=lambda item: (type(item).__name__, repr(item)),
    )
    exact_seed_set = set(training_receipts) == set(SEEDS)
    checks.insert(
        0,
        _check(
            "exact_seed_set",
            exact_seed_set,
            "receipt slots must contain exactly seeds 17, 29, and 43",
            observed_keys,
            list(SEEDS),
        ),
    )
    if not exact_seed_set:
        errors.append(
            f"fail-closed: training receipt seed set drift: observed {observed_keys}, expected {list(SEEDS)}"
        )

    rows: list[dict[str, Any]] = []
    projections: dict[int, dict[str, Any]] = {}
    for seed in SEEDS:
        value = training_receipts.get(seed)
        row: dict[str, Any] = {
            "seed": seed,
            "status": "missing" if value is None else "rejected",
            "source": _empty_source(value),
            "blocked_reasons": [],
        }
        if value is None:
            message = f"fail-closed: missing training receipt for seed {seed}"
            row["blocked_reasons"].append(message)
            errors.append(message)
            rows.append(row)
            continue
        try:
            receipt, source = read_bounded_json(
                root_path,
                value,
                name=f"training receipt seed{seed}",
                max_bytes=MAX_JSON_BYTES,
            )
            row["source"] = source
            if manifest_sha256 is None:
                _fail("current manifest SHA is unavailable")
            projection = _validate_receipt(
                receipt,
                source,
                seed=seed,
                manifest_sha256=manifest_sha256,
            )
            projections[seed] = projection
            row["status"] = "bound"
            row["evidence"] = projection
        except IntakeError as error:
            message = str(error)
            row["blocked_reasons"].append(message)
            errors.append(f"seed{seed}: {message}")
        rows.append(row)

    receipt_manifest_match = (
        manifest_ok
        and len(projections) == len(SEEDS)
        and all(item["manifest_sha256"] == manifest_sha256 for item in projections.values())
    )
    checks.append(
        _check(
            "manifest_sha_matches_receipts",
            receipt_manifest_match,
            "each receipt config.manifest_sha256 equals the actual manifest SHA",
            sorted({item["manifest_sha256"] for item in projections.values()}),
            [manifest_sha256] if manifest_sha256 is not None else None,
        )
    )
    if not receipt_manifest_match:
        errors.append("fail-closed: one or more receipt manifest SHA values do not match the actual manifest SHA")

    run_ids = [projections[seed]["run_id"] for seed in SEEDS if seed in projections]
    receipt_ids = [
        projections[seed]["receipt_identity"]["sha256"]
        for seed in SEEDS
        if seed in projections
    ]
    checkpoint_ids = [
        (
            projections[seed]["checkpoint_identity"]["path"],
            projections[seed]["checkpoint_identity"]["sha256"],
        )
        for seed in SEEDS
        if seed in projections
    ]
    identity_ok = (
        len(projections) == len(SEEDS)
        and len(set(run_ids)) == len(SEEDS)
        and len(set(receipt_ids)) == len(SEEDS)
        and len(set(checkpoint_ids)) == len(SEEDS)
    )
    checks.append(
        _check(
            "checkpoint_receipt_identity",
            identity_ok,
            "run, receipt-file, and declared checkpoint identities are unique and internally bound",
            {
                "run_ids": run_ids,
                "receipt_sha256": receipt_ids,
                "checkpoint_path_sha256": checkpoint_ids,
            },
            "three independent seed identities",
        )
    )
    if not identity_ok:
        errors.append("fail-closed: checkpoint or receipt identity is duplicated or incomplete")

    protocol_ok = len(projections) == len(SEEDS) and all(
        item["model"] == MODEL
        and item["hidden"] == HIDDEN
        and item["updates"] == UPDATES
        and item["completed"] is True
        for item in projections.values()
    )
    checks.append(
        _check(
            "mlp_hidden16_completed_protocol",
            protocol_ok,
            "all receipts declare completed MLP hidden16 500-update training",
            [
                {
                    "seed": item["seed"],
                    "model": item["model"],
                    "hidden": item["hidden"],
                    "updates": item["updates"],
                    "completed": item["completed"],
                }
                for item in projections.values()
            ],
            {"model": MODEL, "hidden": HIDDEN, "updates": UPDATES, "completed": True},
        )
    )
    zero_credit_ok = len(projections) == len(SEEDS) and all(
        item["zero_credit"]["diagnostic_only"] is True
        and item["zero_credit"]["formal"] is False
        and item["zero_credit"]["T1_numerical"] is False
        and item["zero_credit"]["T2_macro"] is False
        and item["zero_credit"]["T2_path"] is False
        and item["zero_credit"]["credit"] == 0
        for item in projections.values()
    )
    checks.append(
        _check(
            "zero_credit_non_authorizing",
            zero_credit_ok,
            "all accepted receipt metadata remains diagnostic-only and zero-credit",
            zero_credit_ok,
            True,
        )
    )
    if not zero_credit_ok:
        errors.append("fail-closed: receipt zero-credit contract is incomplete")

    errors = list(dict.fromkeys(errors))
    all_bound = (
        manifest_ok
        and exact_seed_set
        and len(projections) == len(SEEDS)
        and receipt_manifest_match
        and identity_ok
        and protocol_ok
        and zero_credit_ok
        and not errors
    )
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
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification": False,
        "credit": 0,
        "qualification_credit": 0,
        "formal_training_runs_counted": 0,
        "t1_case_runs_counted": 0,
        "t2_macro_families_counted": 0,
        "model": MODEL,
        "hidden": HIDDEN,
        "updates": UPDATES,
        "seeds": list(SEEDS),
        "manifest": manifest_record,
        "runs": rows,
        "checks": checks,
        "errors": errors,
        "authorization": {
            "formal": False,
            "formal_eligible": False,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "qualification": False,
            "credit": 0,
            "qualification_credit": 0,
        },
        "input_boundary": {
            "bounded_json_only": True,
            "manifest_content_opened": bool(manifest_record.get("opened")),
            "checkpoint_content_opened": False,
            "hdf5_content_opened": False,
            "gpu_started": False,
            "solver_started": False,
            "registry_read": False,
            "ledger_read": False,
            "matrix_v1_read": False,
            "history_summary_read": False,
        },
        "side_effects": {
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "matrix_v1_mutation": 0,
            "history_summary_mutation": 0,
            "runtime_started": False,
            "checkpoint_opened": False,
            "hdf5_opened": False,
        },
        "scope_note": (
            "additive bounded current-manifest diagnostic intake; no formal/T1/T2/credit authority"
        ),
    }
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    """Validate report authority markers without opening any source file."""

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
    expected_status = "diagnostic_bound" if source_bound else "blocked_fail_closed"
    if report.get("status") != expected_status:
        errors.append("status/source_bound mismatch")
    if report.get("fail_closed") is not (not source_bound):
        errors.append("fail_closed/source_bound mismatch")
    if report.get("diagnostic_only") is not True:
        errors.append("diagnostic_only must be true")
    for key in (
        "formal",
        "formal_eligible",
        "T1_numerical",
        "T2_macro",
        "T2_path",
        "qualification",
    ):
        if report.get(key) is not False:
            errors.append(f"{key} must be false")
    for key in (
        "credit",
        "qualification_credit",
        "formal_training_runs_counted",
        "t1_case_runs_counted",
        "t2_macro_families_counted",
    ):
        if type(report.get(key)) is not int or report.get(key) != 0:
            errors.append(f"{key} must be integer zero")
    authorization = report.get("authorization")
    if not isinstance(authorization, Mapping):
        errors.append("authorization must be an object")
    else:
        for key in (
            "formal",
            "formal_eligible",
            "T1_numerical",
            "T2_macro",
            "T2_path",
            "qualification",
        ):
            if authorization.get(key) is not False:
                errors.append(f"authorization.{key} must be false")
        for key in ("credit", "qualification_credit"):
            if type(authorization.get(key)) is not int or authorization.get(key) != 0:
                errors.append(f"authorization.{key} must be integer zero")
    boundary = report.get("input_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("input_boundary must be an object")
    else:
        for key in (
            "checkpoint_content_opened",
            "hdf5_content_opened",
            "gpu_started",
            "solver_started",
            "registry_read",
            "ledger_read",
            "matrix_v1_read",
            "history_summary_read",
        ):
            if boundary.get(key) is not False:
                errors.append(f"input_boundary.{key} must be false")
    side_effects = report.get("side_effects")
    if not isinstance(side_effects, Mapping):
        errors.append("side_effects must be an object")
    else:
        for key in (
            "registry_mutation",
            "ledger_mutation",
            "denominator_mutation",
            "gate_mutation",
            "matrix_v1_mutation",
            "history_summary_mutation",
        ):
            if type(side_effects.get(key)) is not int or side_effects.get(key) != 0:
                errors.append(f"side_effects.{key} must be integer zero")
        for key in ("runtime_started", "checkpoint_opened", "hdf5_opened"):
            if side_effects.get(key) is not False:
                errors.append(f"side_effects.{key} must be false")
    return list(dict.fromkeys(errors))


def _safe_output_path(root: Path, value: Path | str) -> Path:
    path = _resolve_input_path(root, value, "output")
    if path == PROTECTED_V1_MATRIX:
        _fail("refusing to overwrite the historical V1 training matrix")
    if path.suffix.lower() != ".json":
        _fail("output must use the .json suffix")
    if not path.parent.is_dir():
        _fail("output parent directory must already exist")
    return path


def write_report(report: Mapping[str, Any], output: Path | str, *, root: Path | str = LAB_ROOT) -> Path:
    """Write a new report only; never overwrite an existing path."""

    target = _safe_output_path(Path(root).expanduser(), output)
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o644,
        )
    except OSError as error:
        _fail(f"output refuses overwrite or cannot be created: {error}")
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return target


def _parse_seed_receipts(values: Sequence[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError("--training-receipt must use SEED=PATH")
        seed_text, path = item.split("=", 1)
        try:
            seed = int(seed_text)
        except ValueError as error:
            raise ValueError(f"invalid receipt seed: {seed_text!r}") from error
        if seed in result:
            raise ValueError(f"duplicate receipt seed: {seed}")
        result[seed] = path
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="explicit current manifest JSON path")
    parser.add_argument(
        "--training-receipt",
        "--seed-receipt",
        action="append",
        default=[],
        metavar="SEED=PATH",
        help="bounded core.training.v1 receipt; repeat for seeds 17, 29, and 43",
    )
    parser.add_argument("--root", default=str(LAB_ROOT))
    parser.add_argument("--output", help="optional new JSON report path; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        receipts = _parse_seed_receipts(args.training_receipt)
    except ValueError as error:
        parser.error(str(error))
    report = build_report(args.manifest, receipts, root=args.root)
    if args.output:
        try:
            output = write_report(report, args.output, root=args.root)
        except IntakeError as error:
            print(json.dumps({"status": report["status"], "error": str(error)}, ensure_ascii=False))
            return 2
        output_text = str(output)
    else:
        output_text = None
    envelope_errors = validate_report(report)
    if envelope_errors:
        print(json.dumps({"status": report["status"], "report_errors": envelope_errors}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "source_bound": report["source_bound"],
                "manifest_sha256": report["manifest"].get("sha256"),
                "output": output_text,
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "diagnostic_bound" else 2


if __name__ == "__main__":
    raise SystemExit(main())
