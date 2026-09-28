#!/usr/bin/env python3
"""Bounded, fail-closed F4 Tallwall120 material receipt intake.

This module is an additive consumer of the existing Tallwall120 readiness,
source, authority, terminal, and sidecar-matrix receipts.  It only reads
bounded JSON under ``reports/`` and never follows receipt references to a
trajectory, BI4, solver output, or any other production artifact.  In
particular, a path ending in ``.h5``/``.hdf5`` is data, not an input to this
intake.

The report deliberately separates ``structural_intake_ready`` from launch
authority.  Even a future structurally complete receipt set remains
diagnostic-only here: ``launch_admitted``, ``worker_launch_authorized``,
``T2_macro``, ``T2_path``, and all credit fields are hard-coded false/zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = Path("reports")
OBSERVED_AT_UTC = "2026-09-29T00:00:00Z"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 64

SCHEMA = "core.material.f4.tallwall120.bounded_receipt_intake.v1"
RECORD_ID = "f4-tallwall120-material-bounded-receipt-intake-v1-2026-09-29"
FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_PREFIX = f"{SCOPE_ID}_DEV_"
CASE_COUNT = 32
CASE_IDS = tuple(f"{CASE_PREFIX}{index:02d}" for index in range(CASE_COUNT))
CASE_SPLITS = (
    "ood_test",
    "ood_test",
    "ood_test",
    "train",
    "train",
    "id_test",
    "train",
    "train",
    "validation",
    "id_test",
    "train",
    "train",
    "train",
    "validation",
    "id_test",
    "train",
    "train",
    "id_test",
    "validation",
    "train",
    "train",
    "train",
    "id_test",
    "validation",
    "train",
    "train",
    "id_test",
    "train",
    "train",
    "ood_test",
    "ood_test",
    "ood_test",
)
EXPECTED_CASE_SPLITS = dict(zip(CASE_IDS, CASE_SPLITS))
EXPECTED_SPLIT_COUNTS = {
    "train": 16,
    "validation": 4,
    "id_test": 6,
    "ood_test": 6,
}

SOURCE_SHA256 = "6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae"
SOURCE_CASE_ID = f"{SCOPE_ID}_DEV_07"
SOURCE_PATH = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
REQUIRED_EVENT_WINDOW_S = 8.68
UNKNOWN_FRACTION_MAX = 0.01
MASS_CLOSURE_ERROR_MAX = 1.0e-12
RELIABLE_COVERAGE_MIN = 1.0

INPUTS: dict[str, dict[str, Any]] = {
    "readiness_projection": {
        "path": Path("reports/F4-TALLWALL120-MATERIAL-READINESS-PROJECTION-V1-2026-09-28.json"),
        "schema": "core.material.f4.tallwall120.material_readiness_projection.v1",
    },
    "sidecar_matrix": {
        "path": Path("reports/F4-TALLWALL120-MATERIAL-SIDECAR-MATRIX-CONTRACT-V1-2026-09-28.json"),
        "schema": "core.material.f4.tallwall120.sidecar_matrix_contract.v1",
    },
    "case_sidecar_intake": {
        "path": Path("reports/F4-TALLWALL120-MATERIAL-CASE-SIDECAR-INTAKE-V1-2026-09-28.json"),
        "schema": "core.material.f4.tallwall120.case_sidecar_intake.v1",
    },
    "root_scheduler": {
        "path": Path("reports/F4-TALLWALL120-MATERIAL-ROOT-SCHEDULER-INTAKE-V1-2026-09-28.json"),
        "schema": "core.material.f4.tallwall120.root_scheduler_intake.v1",
    },
    "terminal_evidence": {
        "path": Path("reports/F4-TALLWALL120-MATERIAL-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.json"),
        "schema": "core.material.f4.tallwall120.terminal_evidence_intake.v1",
    },
    "source_drift": {
        "path": Path("reports/F4-TALLWALL120-MATERIAL-SOURCE-DRIFT-RECONCILIATION-V1-2026-09-28.json"),
        "schema": "core.material.f4.tallwall120.source_drift_reconciliation.v1",
    },
    "receipt_consistency": {
        "path": Path("reports/F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json"),
        "schema": "core.material.f4.tallwall120.receipt_consistency_audit.v1",
    },
}

DEFAULT_OUTPUT = Path(
    "reports/F4-TALLWALL120-MATERIAL-BOUNDED-RECEIPT-INTAKE-V1-2026-09-29.json"
)
DEFAULT_ZH_OUTPUT = Path(
    "reports/F4-TALLWALL120-MATERIAL-BOUNDED-RECEIPT-INTAKE-V1-2026-09-29.zh-CN.md"
)

HDF5_CONTENT_KEYS = {
    "hdf5_content_read",
    "hdf5_hash_recomputed",
    "hdf5_opened",
    "production_hdf5_content_read",
    "production_hdf5_hash_recomputed",
    "production_hdf5_opened",
    "source_hdf5_opened",
    "source_hdf5_read",
    "source_hdf5_hash_recomputed",
    "content_read_as_hdf5",
    "opened_as_hdf5",
}
EFFECT_KEYS = {
    "solver_started",
    "worker_started",
    "native_started",
    "gpu_started",
    "queue_started",
    "scheduler_started",
    "production_hdf5_mutated",
    "authority_receipt_written",
    "material_sidecar_written",
}
CREDIT_KEYS = {
    "credit",
    "qualification_credit",
    "t1_credit",
    "t2_credit",
    "formal_credit",
    "T2_credit",
}
PROMOTION_KEYS = {
    "formal",
    "formal_eligible",
    "qualification",
    "T1",
    "T2",
    "T2_macro",
    "T2_path",
    "launch_admitted",
    "worker_launch_authorized",
    "actual_sidecar_execution_allowed",
}


class F4MaterialBoundedIntakeError(ValueError):
    """Raised when the intake itself cannot safely consume its inputs."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_constant(token: str) -> Any:
    raise ValueError(f"nonfinite_json_constant:{token}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_json_key:{key}")
        result[key] = value
    return result


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("json_depth_exceeded")
    if isinstance(value, Mapping):
        for child in value.values():
            _check_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_depth(child, depth + 1)


def _safe_relative(value: str | Path, *, field: str) -> str:
    text = str(value).replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise F4MaterialBoundedIntakeError(f"{field}:path_traversal")
    if "" in path.parts:
        raise F4MaterialBoundedIntakeError(f"{field}:empty_path_segment")
    return path.as_posix()


def _resolve_report(
    root: Path,
    value: str | Path,
    *,
    field: str,
    allowed_suffixes: frozenset[str] = frozenset({".json"}),
) -> Path:
    relative = _safe_relative(value, field=field)
    if not relative.startswith(f"{REPORTS_ROOT.as_posix()}/"):
        raise F4MaterialBoundedIntakeError(f"{field}:not_under_reports")
    if Path(relative).suffix.lower() not in allowed_suffixes:
        raise F4MaterialBoundedIntakeError(f"{field}:non_json_input")
    root = Path(root).resolve()
    candidate = root / relative
    try:
        candidate.resolve(strict=False).relative_to((root / REPORTS_ROOT).resolve())
    except ValueError as error:
        raise F4MaterialBoundedIntakeError(f"{field}:path_scope") from error
    return candidate


def _component_symlink(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            if stat.S_ISLNK(os.lstat(cursor).st_mode):
                return True
        except FileNotFoundError:
            return False
    return False


def _identity(stat_result: os.stat_result) -> tuple[int, int, int]:
    return (stat_result.st_dev, stat_result.st_ino, stat_result.st_size)


def _read_bounded_json(root: Path, name: str, spec: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    path = _resolve_report(root, spec["path"], field=f"{name}.path")
    reference: dict[str, Any] = {
        "role": name,
        "path": str(spec["path"]),
        "exists": False,
        "bytes": None,
        "sha256": None,
        "content_read": False,
        "content_hash_recomputed": False,
        "schema": None,
        "expected_schema": spec["schema"],
    }
    errors: list[str] = []
    if _component_symlink(path, root):
        reference["error"] = "symlink_path"
        return {}, reference, [f"{name}:symlink_path"]
    try:
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError:
        reference["error"] = "missing_file"
        return {}, reference, [f"{name}:missing_file"]
    except OSError as error:
        reference["error"] = f"open_error:{type(error).__name__}"
        return {}, reference, [f"{name}:safe_open"]

    try:
        before = os.fstat(fd)
        reference["exists"] = True
        reference["bytes"] = before.st_size
        if not stat.S_ISREG(before.st_mode):
            reference["error"] = "not_regular_file"
            return {}, reference, [f"{name}:not_regular_file"]
        if before.st_nlink != 1:
            reference["error"] = "hardlink_file"
            return {}, reference, [f"{name}:hardlink_file"]
        if before.st_size > MAX_JSON_BYTES:
            reference["error"] = "file_exceeds_bounded_limit"
            return {}, reference, [f"{name}:file_exceeds_bounded_limit"]
        chunks: list[bytes] = []
        remaining = MAX_JSON_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        if _identity(before) != _identity(after) or len(data) != before.st_size:
            reference["error"] = "input_drift"
            return {}, reference, [f"{name}:input_drift"]
        if len(data) > MAX_JSON_BYTES:
            reference["error"] = "file_exceeds_bounded_limit"
            return {}, reference, [f"{name}:file_exceeds_bounded_limit"]
        reference["sha256"] = _sha256(data)
        reference["content_read"] = True
        reference["content_hash_recomputed"] = True
        try:
            payload = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_strict_object,
                parse_constant=_reject_constant,
            )
            _check_depth(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            reference["error"] = str(error)
            return {}, reference, [f"{name}:strict_json"]
        if not isinstance(payload, dict):
            reference["error"] = "json_root_not_object"
            return {}, reference, [f"{name}:json_root_not_object"]
        reference["schema"] = payload.get("schema")
        if payload.get("schema") != spec["schema"]:
            errors.append(f"{name}:schema_drift")
        return payload, reference, errors
    finally:
        os.close(fd)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _check(name: str, passed: bool, *, observed: Any, expected: Any, blocker: str) -> dict[str, Any]:
    return {
        "check": name,
        "passed": bool(passed),
        "observed": observed,
        "expected": expected,
        "blocker": blocker,
    }


def _walk(value: Any, path: str = "root"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield str(key), child, child_path
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _boundary_violations(payload: Mapping[str, Any]) -> list[str]:
    violations: list[str] = []
    for key, value, path in _walk(payload):
        if key in HDF5_CONTENT_KEYS and value is True:
            violations.append(path)
        if key in EFFECT_KEYS and value is True:
            violations.append(path)
        if key in {"mutation", "registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation", "completion_mutation"}:
            if _number(value) not in {None, 0.0}:
                violations.append(path)
    return sorted(set(violations))


def _credit_violations(payload: Mapping[str, Any]) -> list[str]:
    violations: list[str] = []
    for key, value, path in _walk(payload):
        if key in CREDIT_KEYS:
            if isinstance(value, bool) and value:
                violations.append(path)
            elif _number(value) not in {None, 0.0}:
                violations.append(path)
        elif key in PROMOTION_KEYS and value is True:
            violations.append(path)
    return sorted(set(violations))


def _upstream_blockers(payload: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("blocking_reasons", "blockers", "failed_checks"):
        for value in _list(payload.get(key)):
            if isinstance(value, str):
                result.append(value)
    validation = _mapping(payload.get("validation"))
    for key in ("blockers", "input_errors", "root_receipt_errors", "scheduler_receipt_errors"):
        for value in _list(validation.get(key)):
            if isinstance(value, str):
                result.append(value)
    return sorted(set(result))


def _case_rows(matrix: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    sidecars = _mapping(matrix.get("material_sidecars"))
    cases = [item for item in _list(sidecars.get("cases")) if isinstance(item, Mapping)]
    source_binding = _mapping(matrix.get("source_binding"))
    source_rows = [item for item in _list(source_binding.get("source_matrix")) if isinstance(item, Mapping)]
    return cases, source_rows


def _case_matrix(matrix: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases, source_rows = _case_rows(matrix)
    case_by_id = {str(item.get("case_id")): item for item in cases if isinstance(item.get("case_id"), str)}
    source_by_id = {str(item.get("case_id")): item for item in source_rows if isinstance(item.get("case_id"), str)}
    duplicate_case_ids = sorted(
        case_id
        for case_id in {str(item.get("case_id")) for item in cases if isinstance(item.get("case_id"), str)}
        if sum(1 for item in cases if item.get("case_id") == case_id) > 1
    )
    rows: list[dict[str, Any]] = []
    for index, case_id in enumerate(CASE_IDS):
        case = case_by_id.get(case_id, {})
        source = source_by_id.get(case_id, {})
        observed_path = source.get("collection_source_path")
        expected_path = source.get("expected_source_path")
        observed_sha = source.get("collection_source_sha256")
        expected_sha = source.get("expected_source_sha256")
        sidecar_status = case.get("status", "missing")
        reasons: list[str] = []
        if not source:
            reasons.append("missing_source_matrix_row")
        if observed_path != expected_path:
            reasons.append("source_path_drift")
        if observed_sha != expected_sha:
            reasons.append("source_sha256_drift")
        if case_id not in case_by_id:
            reasons.append("missing_case_sidecar_projection")
        if sidecar_status != "complete":
            reasons.append("missing_or_incomplete_material_sidecar")
        markers = _mapping(case.get("material_markers"))
        if not all(
            markers.get(key) is True
            for key in (
                "mass_closure_pass",
                "unknown_fraction_pass",
                "reliable_coverage_pass",
                "right_censor_pass",
            )
        ):
            reasons.append("missing_required_material_markers")
        rows.append(
            {
                "matrix_index": index,
                "case_id": case_id,
                "split": EXPECTED_CASE_SPLITS[case_id],
                "status": "complete" if not reasons else "blocked",
                "sidecar_status": sidecar_status,
                "terminal_status": case.get("terminal_status"),
                "source": {
                    "observed_hdf5": observed_path,
                    "observed_sha256": observed_sha,
                    "expected_hdf5": expected_path,
                    "expected_sha256": expected_sha,
                    "path_exact": observed_path == expected_path,
                    "sha256_exact": observed_sha == expected_sha,
                },
                "blocking_reasons": sorted(set(reasons)),
                "credit": 0,
            }
        )
    inventory = {
        "case_projection_count": len(cases),
        "source_matrix_count": len(source_rows),
        "duplicate_case_ids": duplicate_case_ids,
        "extra_case_ids": sorted(set(case_by_id) - set(CASE_IDS)),
        "missing_case_projection_ids": [case_id for case_id in CASE_IDS if case_id not in case_by_id],
        "missing_source_matrix_ids": [case_id for case_id in CASE_IDS if case_id not in source_by_id],
    }
    return rows, inventory


def _root_scheduler_gate(root_scheduler: Mapping[str, Any]) -> dict[str, Any]:
    validation = _mapping(root_scheduler.get("validation"))
    checks = _mapping(validation.get("checks"))
    return {
        "source_identity_contract_valid": checks.get("source_identity_contract_valid") is True,
        "reader_identity_bound": checks.get("reader_identity_bound") is True,
        "fresh_root_receipt_present": checks.get("future_root_receipt_present") is True,
        "fresh_root_receipt_valid": checks.get("future_root_receipt_valid") is True,
        "scheduler_receipt_present": checks.get("future_scheduler_receipt_present") is True,
        "scheduler_receipt_valid": checks.get("future_scheduler_receipt_valid") is True,
        "pair_cross_binding_valid": checks.get("root_scheduler_pair_cross_binding_valid") is True
        or checks.get("receipt_pair_cross_binding_valid") is True,
        "scheduler_owned_host_io_valid": checks.get("scheduler_owned_host_io_reservation_valid") is True,
    }


def _terminal_gate(terminal: Mapping[str, Any]) -> dict[str, Any]:
    intake = _mapping(terminal.get("terminal_evidence_intake"))
    gate = _mapping(intake.get("gate_projection"))
    ref = _mapping(_mapping(terminal.get("fresh_attempt_contract")).get("terminal_evidence_ref"))
    return {
        "fresh_terminal_present": ref.get("exists") is True and intake.get("present") is True,
        "intake_complete": intake.get("status") == "complete",
        "event_window_complete": gate.get("event_window_complete") is True,
        "mass_closure": gate.get("mass_closure") is True,
        "unknown_gate": gate.get("unknown_gate") is True,
        "reliable_coverage": gate.get("reliable_coverage") is True,
        "right_censor_clear": gate.get("right_censor_clear") is True,
    }


def _case_sidecar_gate(case_intake: Mapping[str, Any]) -> dict[str, Any]:
    intake = _mapping(case_intake.get("case_sidecar_intake"))
    source = _mapping(case_intake.get("source_binding"))
    target = _mapping(source.get("proposal_target"))
    return {
        "present": intake.get("present") is True,
        "complete": intake.get("status") == "complete",
        "source_path_exact": target.get("source_hdf5") == SOURCE_PATH,
        "source_sha256_exact": target.get("source_sha256") == SOURCE_SHA256,
        "hdf5_content_read": _mapping(case_intake.get("input_boundary")).get("hdf5_content_read") is True,
    }


def _source_gate(
    matrix: Mapping[str, Any],
    source_drift: Mapping[str, Any],
    consistency: Mapping[str, Any],
) -> dict[str, Any]:
    source_binding = _mapping(matrix.get("source_binding"))
    reader = _mapping(source_binding.get("reader"))
    dev07 = _mapping(source_binding.get("dev07"))
    archives = _mapping(_mapping(consistency).get("archives_path_binding"))
    reconciliation = _mapping(source_drift.get("source_reconciliation"))
    rows = [row for row in _list(source_binding.get("source_matrix")) if isinstance(row, Mapping)]
    all_expected_paths = len(rows) == CASE_COUNT and all(
        isinstance(row.get("expected_source_path"), str)
        and "archives-v2" in row["expected_source_path"]
        for row in rows
    )
    all_exact = len(rows) == CASE_COUNT and all(
        row.get("source_exact") is True for row in rows
    )
    return {
        "fixed_source_matrix_present": len(rows) == CASE_COUNT,
        "expected_archives_v2_paths": all_expected_paths,
        "collection_paths_exact": all_exact,
        "dev07_path_exact": dev07.get("collection_source_hdf5") == dev07.get("proposal_source_hdf5") == SOURCE_PATH,
        "dev07_sha_exact": dev07.get("collection_source_sha256") == dev07.get("proposal_source_sha256") == SOURCE_SHA256,
        "reader_manifest_path_exact": reader.get("path_exact") is True,
        "reader_manifest_sha_exact": reader.get("sha256_exact") is True,
        "archives_receipt_path_exact": archives.get("exact_path_match") is True,
        "archives_receipt_sha_exact": archives.get("source_sha256_match") is True,
        "source_reconciliation_ready": reconciliation.get("ready") is True,
    }


def _readiness_gate(readiness: Mapping[str, Any]) -> dict[str, Any]:
    t2 = _mapping(readiness.get("t2_readiness"))
    sidecar = _mapping(readiness.get("sidecar_matrix"))
    return {
        "scope_exact": _mapping(readiness.get("scope")).get("family") == FAMILY
        and _mapping(readiness.get("scope")).get("scope_id") == SCOPE_ID,
        "status_known": readiness.get("status") in {"blocked_fail_closed", "structural_intake_ready_non_authorizing"},
        "matrix_count_32": sidecar.get("expected_case_count") == CASE_COUNT,
        "matrix_missing_count_reported": sidecar.get("missing_case_count") == CASE_COUNT,
        "formal_t2_macro_false": t2.get("formal_T2_macro") is False,
        "formal_t2_path_false": t2.get("formal_T2_path") is False,
        "launch_false": readiness.get("launch_admitted") is False,
        "credit_zero": readiness.get("credit") == 0 and readiness.get("qualification_credit") == 0,
    }


def _input_boundaries_clear(payloads: Mapping[str, Mapping[str, Any]]) -> tuple[bool, dict[str, list[str]]]:
    boundary_violations = {name: _boundary_violations(payload) for name, payload in payloads.items()}
    credit_violations = {name: _credit_violations(payload) for name, payload in payloads.items()}
    clean = not any(boundary_violations.values()) and not any(credit_violations.values())
    return clean, {"forbidden_effects": boundary_violations, "promotion_or_credit": credit_violations}


def evaluate_receipts(payloads: Mapping[str, Mapping[str, Any]], input_errors: Sequence[str] = ()) -> dict[str, Any]:
    """Evaluate already-parsed bounded receipts without touching the filesystem."""

    readiness = _mapping(payloads.get("readiness_projection"))
    matrix = _mapping(payloads.get("sidecar_matrix"))
    case_intake = _mapping(payloads.get("case_sidecar_intake"))
    root_scheduler = _mapping(payloads.get("root_scheduler"))
    terminal = _mapping(payloads.get("terminal_evidence"))
    source_drift = _mapping(payloads.get("source_drift"))
    consistency = _mapping(payloads.get("receipt_consistency"))

    case_rows, case_inventory = _case_matrix(matrix)
    root_gate = _root_scheduler_gate(root_scheduler)
    terminal_gate = _terminal_gate(terminal)
    case_gate = _case_sidecar_gate(case_intake)
    source_gate = _source_gate(matrix, source_drift, consistency)
    readiness_gate = _readiness_gate(readiness)
    boundaries_clear, boundary_details = _input_boundaries_clear(payloads)

    fixed_ids = _mapping(matrix.get("fixed_matrix")).get("case_ids")
    fixed_splits = _mapping(matrix.get("fixed_matrix")).get("case_splits")
    observed_split_counts = _mapping(_mapping(matrix.get("matrix_summary")).get("split_counts_observed"))
    sidecar_summary = _mapping(matrix.get("matrix_summary"))
    identity_checks = [
        _check(
            "fixed_32_case_denominator",
            fixed_ids == list(CASE_IDS)
            and fixed_splits == EXPECTED_CASE_SPLITS
            and matrix.get("scope", {}).get("case_count") == CASE_COUNT,
            observed={"case_count": len(fixed_ids) if isinstance(fixed_ids, list) else None, "case_ids_exact": fixed_ids == list(CASE_IDS)},
            expected={"case_count": CASE_COUNT, "split_counts": EXPECTED_SPLIT_COUNTS},
            blocker="fixed_32_case_identity_drift",
        ),
        _check(
            "fixed_split_counts",
            observed_split_counts == EXPECTED_SPLIT_COUNTS,
            observed=observed_split_counts,
            expected=EXPECTED_SPLIT_COUNTS,
            blocker="fixed_split_matrix_drift",
        ),
        _check(
            "case_projection_inventory",
            case_inventory["case_projection_count"] == CASE_COUNT
            and not case_inventory["duplicate_case_ids"]
            and not case_inventory["extra_case_ids"]
            and not case_inventory["missing_case_projection_ids"],
            observed=case_inventory,
            expected={"case_projection_count": CASE_COUNT, "duplicates": [], "extras": [], "missing": []},
            blocker="case_projection_inventory_drift",
        ),
    ]
    source_checks = [
        _check(
            "source_matrix_binding",
            source_gate["fixed_source_matrix_present"]
            and source_gate["expected_archives_v2_paths"]
            and source_gate["collection_paths_exact"]
            and source_gate["dev07_path_exact"]
            and source_gate["dev07_sha_exact"],
            observed=source_gate,
            expected={"case_count": CASE_COUNT, "archive_variant": "archives-v2", "source_sha256": SOURCE_SHA256},
            blocker="source_collection_archives_v1_vs_archives_v2_drift",
        ),
        _check(
            "reader_manifest_binding",
            source_gate["reader_manifest_path_exact"] and source_gate["reader_manifest_sha_exact"],
            observed={key: source_gate[key] for key in ("reader_manifest_path_exact", "reader_manifest_sha_exact")},
            expected={"path_exact": True, "sha256_exact": True},
            blocker="reader_manifest_sha_stale",
        ),
        _check(
            "receipt_consistency_binding",
            source_gate["archives_receipt_path_exact"] and source_gate["archives_receipt_sha_exact"],
            observed={key: source_gate[key] for key in ("archives_receipt_path_exact", "archives_receipt_sha_exact")},
            expected={"path_exact": True, "source_sha256_match": True},
            blocker="receipt_consistency_archives_path_drift",
        ),
        _check(
            "source_reconciliation_ready",
            source_gate["source_reconciliation_ready"],
            observed=source_gate["source_reconciliation_ready"],
            expected=True,
            blocker="source_drift_reconciliation_blocked",
        ),
    ]
    sidecar_checks = [
        _check(
            "sidecar_matrix_complete",
            sidecar_summary.get("observed_sidecar_count") == CASE_COUNT
            and sidecar_summary.get("complete_sidecar_count") == CASE_COUNT
            and all(row["status"] == "complete" for row in case_rows),
            observed={
                "observed_sidecar_count": sidecar_summary.get("observed_sidecar_count"),
                "complete_sidecar_count": sidecar_summary.get("complete_sidecar_count"),
                "case_statuses": sorted({row["status"] for row in case_rows}),
            },
            expected={"observed_sidecar_count": CASE_COUNT, "complete_sidecar_count": CASE_COUNT},
            blocker="missing_or_incomplete_32_case_sidecars",
        ),
        _check(
            "sidecar_material_markers_complete",
            sidecar_summary.get("full_event_window_complete_count") == CASE_COUNT
            and sidecar_summary.get("mass_closed_count") == CASE_COUNT
            and sidecar_summary.get("unknown_fraction_pass_count") == CASE_COUNT
            and sidecar_summary.get("reliable_coverage_pass_count") == CASE_COUNT
            and sidecar_summary.get("right_censor_clear_count") == CASE_COUNT,
            observed={key: sidecar_summary.get(key) for key in (
                "full_event_window_complete_count",
                "mass_closed_count",
                "unknown_fraction_pass_count",
                "reliable_coverage_pass_count",
                "right_censor_clear_count",
            )},
            expected={"all_counts": CASE_COUNT},
            blocker="missing_required_material_markers",
        ),
    ]
    authority_checks = [
        _check(
            "root_scheduler_receipt_binding",
            all(root_gate.values()),
            observed=root_gate,
            expected={key: True for key in root_gate},
            blocker="missing_or_invalid_root_scheduler_receipts",
        ),
        _check(
            "terminal_evidence_binding",
            all(terminal_gate.values()),
            observed=terminal_gate,
            expected={key: True for key in terminal_gate},
            blocker="missing_or_incomplete_terminal_evidence",
        ),
        _check(
            "dev07_case_sidecar_binding",
            case_gate["present"]
            and case_gate["complete"]
            and case_gate["source_path_exact"]
            and case_gate["source_sha256_exact"]
            and not case_gate["hdf5_content_read"],
            observed=case_gate,
            expected={"present": True, "complete": True, "source_path_exact": True, "source_sha256_exact": True},
            blocker="dev07_case_sidecar_not_bound",
        ),
    ]
    readiness_checks = [
        _check(
            "readiness_projection_binding",
            all(readiness_gate.values()),
            observed=readiness_gate,
            expected={key: True for key in readiness_gate},
            blocker="readiness_projection_drift",
        ),
        _check(
            "bounded_input_and_effect_boundary",
            boundaries_clear,
            observed=boundary_details,
            expected={"forbidden_effects": {}, "promotion_or_credit": {}},
            blocker="forbidden_effect_or_credit_observed",
        ),
    ]
    checks = identity_checks + source_checks + sidecar_checks + authority_checks + readiness_checks
    input_errors = sorted(set(str(item) for item in input_errors))
    structural_ready = not input_errors and all(check["passed"] for check in checks)
    blockers = sorted(set(input_errors + [check["blocker"] for check in checks if not check["passed"]]))
    upstream = {
        name: {
            "status": payload.get("status"),
            "blockers": _upstream_blockers(payload),
        }
        for name, payload in payloads.items()
    }
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "observed_at_utc": OBSERVED_AT_UTC,
        "status": "structural_intake_ready_non_authorizing" if structural_ready else "blocked_fail_closed",
        "decision": "diagnostic_only_bounded_receipt_intake",
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "case_count": CASE_COUNT,
            "focus": "F4 Tallwall120 material source/root/scheduler/terminal/32-case sidecar binding",
        },
        "structural_intake": {
            "structural_intake_ready": structural_ready,
            "checks": checks,
            "blocked_reasons": blockers,
        },
        "source": {
            "target_case_id": SOURCE_CASE_ID,
            "target_hdf5": SOURCE_PATH,
            "target_sha256": SOURCE_SHA256,
            "archive_variant_required": "archives-v2",
            "checks": source_gate,
        },
        "case_matrix": {
            "expected_case_count": CASE_COUNT,
            "expected_split_counts": EXPECTED_SPLIT_COUNTS,
            "case_rows": case_rows,
            "inventory": case_inventory,
            "observed_sidecar_count": sidecar_summary.get("observed_sidecar_count"),
            "complete_sidecar_count": sidecar_summary.get("complete_sidecar_count"),
            "missing_case_ids": [row["case_id"] for row in case_rows if row["status"] != "complete"],
        },
        "authority_blockers": {
            "root_scheduler": root_gate,
            "terminal": terminal_gate,
            "dev07_case_sidecar": case_gate,
            "upstream_receipts": upstream,
        },
        "required_external_receipts": [
            {
                "id": "corrected_archives_v2_collection_and_reader_binding",
                "present": source_gate["collection_paths_exact"] and source_gate["reader_manifest_sha_exact"],
                "reason": "all 32 collection rows and the reader receipt must bind the current archives-v2 path and manifest SHA",
            },
            {
                "id": "fresh_root_receipt",
                "present": root_gate["fresh_root_receipt_present"] and root_gate["fresh_root_receipt_valid"],
                "path": "campaigns/core-v1/material/evidence/f4-tallwall120-material-root-scheduler-intake-v1/fresh-root-receipt.json",
            },
            {
                "id": "scheduler_owned_host_io_reservation",
                "present": root_gate["scheduler_receipt_present"] and root_gate["scheduler_receipt_valid"] and root_gate["scheduler_owned_host_io_valid"],
                "path": "campaigns/core-v1/material/evidence/f4-tallwall120-material-root-scheduler-intake-v1/scheduler-host-io-reservation.json",
            },
            {
                "id": "fresh_dev07_terminal_evidence",
                "present": terminal_gate["fresh_terminal_present"] and terminal_gate["intake_complete"],
                "reason": "a fresh full 8.68 s terminal sidecar is required; the 4.34 s native diagnostic is not imputed",
            },
            {
                "id": "all_32_material_sidecars",
                "present": sidecar_summary.get("observed_sidecar_count") == CASE_COUNT and sidecar_summary.get("complete_sidecar_count") == CASE_COUNT,
                "reason": "one source-bound, terminal, marker-complete sidecar per fixed case is required",
            },
        ],
        "blockers": blockers,
        "authorization": {
            "structural_intake_ready": structural_ready,
            "launch_admitted": False,
            "worker_launch_authorized": False,
            "actual_sidecar_execution_allowed": False,
            "formal": False,
            "formal_eligible": False,
            "qualification": False,
            "T1": False,
            "T2": False,
            "T2_macro": False,
            "T2_path": False,
            "credit": 0,
            "qualification_credit": 0,
        },
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "max_json_depth": MAX_JSON_DEPTH,
            "production_hdf5_opened": False,
            "production_hdf5_content_read": False,
            "production_hdf5_hash_recomputed": False,
            "solver_started": False,
            "worker_started": False,
            "native_started": False,
            "gpu_started": False,
            "queue_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
    }


def build_report(root: str | Path = LAB_ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    payloads: dict[str, dict[str, Any]] = {}
    input_refs: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for name, spec in INPUTS.items():
        payload, reference, read_errors = _read_bounded_json(root, name, spec)
        payloads[name] = payload
        input_refs[name] = reference
        errors.extend(read_errors)
    report = evaluate_receipts(payloads, errors)
    report["input_refs"] = input_refs
    report["input_boundary"]["input_errors"] = sorted(set(errors))
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    if report.get("record_id") != RECORD_ID:
        errors.append("record_id")
    if report.get("status") not in {"blocked_fail_closed", "structural_intake_ready_non_authorizing"}:
        errors.append("status")
    if report.get("decision") != "diagnostic_only_bounded_receipt_intake":
        errors.append("decision")
    authorization = _mapping(report.get("authorization"))
    for key, expected in {
        "launch_admitted": False,
        "worker_launch_authorized": False,
        "actual_sidecar_execution_allowed": False,
        "formal": False,
        "formal_eligible": False,
        "qualification": False,
        "T1": False,
        "T2": False,
        "T2_macro": False,
        "T2_path": False,
        "credit": 0,
        "qualification_credit": 0,
    }.items():
        if authorization.get(key) != expected:
            errors.append(f"authorization.{key}")
    boundary = _mapping(report.get("input_boundary"))
    for key, expected in {
        "bounded_json_only": True,
        "production_hdf5_opened": False,
        "production_hdf5_content_read": False,
        "production_hdf5_hash_recomputed": False,
        "solver_started": False,
        "worker_started": False,
        "native_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "completion_mutation": 0,
    }.items():
        if boundary.get(key) != expected:
            errors.append(f"input_boundary.{key}")
    rows = _list(_mapping(report.get("case_matrix")).get("case_rows"))
    if len(rows) != CASE_COUNT or [item.get("case_id") for item in rows] != list(CASE_IDS):
        errors.append("case_matrix.case_rows")
    if len(set(report.get("blockers", []))) != len(report.get("blockers", [])):
        errors.append("blockers.duplicates")
    if report.get("status") == "blocked_fail_closed" and not report.get("blockers"):
        errors.append("blocked_without_reason")
    if not isinstance(report.get("input_refs"), Mapping) or set(report["input_refs"]) != set(INPUTS):
        errors.append("input_refs")
    return errors


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError as error:
        raise F4MaterialBoundedIntakeError(f"refusing_to_overwrite:{path}") from error
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def write_report(report: Mapping[str, Any], output: str | Path, root: str | Path = LAB_ROOT) -> Path:
    errors = validate_report(report)
    if errors:
        raise F4MaterialBoundedIntakeError("invalid report: " + ", ".join(errors))
    root = Path(root).resolve()
    path = _resolve_report(root, output, field="output")
    _write_new(path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return path


def render_markdown(report: Mapping[str, Any]) -> str:
    structural = _mapping(report.get("structural_intake"))
    auth = _mapping(report.get("authorization"))
    matrix = _mapping(report.get("case_matrix"))
    blockers = ", ".join(str(item) for item in report.get("blockers", [])) or "无"
    lines = [
        "# F4 Tallwall120 material bounded receipt intake V1",
        "",
        f"- 状态：`{report.get('status')}`。",
        f"- structural intake：`{structural.get('structural_intake_ready')}`；这是静态结构结论，不是 launch 授权。",
        f"- 固定矩阵：`{matrix.get('expected_case_count')}` cases；observed sidecars=`{matrix.get('observed_sidecar_count')}`；complete=`{matrix.get('complete_sidecar_count')}`。",
        f"- blockers：{blockers}。",
        "",
        "## 不可变授权边界",
        "",
        f"- `launch_admitted={auth.get('launch_admitted')}`，`worker_launch_authorized={auth.get('worker_launch_authorized')}`。",
        f"- `T2_macro={auth.get('T2_macro')}`，`T2_path={auth.get('T2_path')}`，`credit={auth.get('credit')}`。",
        "- 本 intake 不启动 solver、worker、native、GPU、queue，也不写 registry、ledger、denominator、gate 或 completion。",
        "",
        "## 当前仍缺的外部 receipt",
        "",
    ]
    for item in report.get("required_external_receipts", []):
        lines.append(f"- `{item.get('id')}`：present=`{item.get('present')}`。{item.get('reason', '')}")
    lines.extend(
        [
            "",
            "## 32-case sidecar binding",
            "",
            "每个 case 都必须以唯一 case_id、固定 split、archives-v2 source path/SHA、fresh namespace、完整 terminal event window 和四类 material marker 绑定；缺失、重复、partial 或 right-censored 都不能形成 T2 credit。",
            "",
            "| case | split | sidecar | source path | blockers |",
            "|---|---|---|---|---|",
        ]
    )
    for row in matrix.get("case_rows", []):
        source = _mapping(row.get("source"))
        lines.append(
            f"| `{row.get('case_id')}` | `{row.get('split')}` | `{row.get('sidecar_status')}` | `path_exact={source.get('path_exact')}, sha_exact={source.get('sha256_exact')}` | {', '.join(row.get('blocking_reasons', [])) or '无'} |"
        )
    lines.extend(
        [
            "",
            "## 输入边界",
            "",
            "- 只读取 reports 下的 bounded JSON，并做 strict JSON、大小、inode、hardlink、symlink 和 TOCTOU 检查。",
            "- production HDF5 仅作为历史 receipt 中的声明存在；本 intake 不跟随路径、不打开、不读取、不重哈希。",
            "- 历史 diagnostic 的短窗口不能被补全或推断为 8.68 s terminal evidence。",
            "",
        ]
    )
    return "\n".join(lines)


def write_markdown(report: Mapping[str, Any], output: str | Path, root: str | Path = LAB_ROOT) -> Path:
    errors = validate_report(report)
    if errors:
        raise F4MaterialBoundedIntakeError("invalid report: " + ", ".join(errors))
    root = Path(root).resolve()
    path = _resolve_report(root, output, field="markdown_output", allowed_suffixes=frozenset({".md"}))
    _write_new(path, (render_markdown(report) + "\n").encode("utf-8"))
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_ZH_OUTPUT)
    args = parser.parse_args(argv)
    report = build_report(args.root)
    write_report(report, args.output, args.root)
    write_markdown(report, args.markdown_output, args.root)
    print(json.dumps({"status": report["status"], "output": str(args.output), "markdown": str(args.markdown_output)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
