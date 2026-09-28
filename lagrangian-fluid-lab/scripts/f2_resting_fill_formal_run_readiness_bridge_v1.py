#!/usr/bin/env python3
"""Build a bounded, non-authorizing F2 resting-fill formal-run projection.

This bridge joins the existing F2 static full-cup preparation, admission,
root-review, smoke-receipt, and Core-interface metadata into one explicit
15-row readiness view.  It reads only a fixed allow-list of bounded JSON
files.  It never follows artifact paths recorded inside those JSON files and
never opens, stats, hashes, or decodes production HDF5, BI4, trajectory,
solver, native, worker, GPU, or queue artifacts.

The resulting report is deliberately fail-closed.  A prepared input is not a
runtime result; a historical hard failure is not a pass; and a static anchor
is not F2 T1/T2 credit.  The bridge only describes what evidence is present
and what must be obtained under a future, separately authorized run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.f2.resting_fill.formal_run_readiness_bridge.v1"
REPORT_SCHEMA = "core.f2.resting_fill.formal_run_readiness_bridge_report.v1"
RECORD_ID = "f2-resting-fill-formal-run-readiness-bridge-v1"
SCOPE_ID = "F2_static_full_cup_volume_hold_x_v1"
CANDIDATE_ID = "F2_static_full_cup_volume_hold"
OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
MAX_JSON_BYTES = 256 * 1024
SHA256_HEX = frozenset("0123456789abcdef")

DEFAULT_REPORT = LAB_ROOT / "reports/F2-RESTING-FILL-FORMAL-RUN-READINESS-BRIDGE-V1-2026-09-28.json"
DEFAULT_ZH_REPORT = LAB_ROOT / "reports/F2-RESTING-FILL-FORMAL-RUN-READINESS-BRIDGE-V1-2026-09-28.zh-CN.md"

DEPENDENCY_SPECS: dict[str, dict[str, Any]] = {
    "candidate_card": {
        "path": Path("campaigns/core-v1/cfd/f2-static-full-cup-volume-hold-candidate-v1.json"),
        "schema": "core.f2.static_full_cup_volume_candidate.v1",
        "role": "15-cell static candidate contract",
    },
    "matrix_preparation": {
        "path": Path("campaigns/core-v1/cfd/f2-static-full-cup-matrix-prepared-v4/matrix-preparation.json"),
        "schema": "core.f2.static_full_cup.matrix_preparation.v1",
        "role": "v4 CPU/native preparation aggregate",
    },
    "preparation_audit": {
        "path": Path("campaigns/core-v1/cfd/f2-static-full-cup-matrix-prepared-v4/matrix-preparation-audit.json"),
        "schema": "core.f2.static_full_cup.matrix_preparation_audit.v1",
        "role": "v4 preparation audit",
    },
    "qualification_admission": {
        "path": Path("campaigns/core-v1/cfd/f2-static-full-cup-qualification-admission-v1.json"),
        "schema": "core.f2.static_full_cup.qualification_admission.v1",
        "role": "formal runtime product/admission contract",
    },
    "root_review": {
        "path": Path("campaigns/core-v1/cfd/f2-static-full-cup-root-review-v1.json"),
        "schema": "core.f2.static_full_cup.root_review.v1",
        "role": "CPU-only preparation/decode root review",
    },
    "runtime_smoke_review": {
        "path": Path("campaigns/core-v1/cfd/f2-static-full-cup-runtime-root-review-smoke-v1.json"),
        "schema": "core.root_review.v1",
        "role": "historical one-cell runtime-smoke review",
    },
    "qualification_receipt": {
        "path": Path("campaigns/core-v1/cfd/f2-static-full-cup-qualification-receipt-smoke-cell-00-v1.json"),
        "schema": "core.f2.static_full_cup.qualification_receipt.v1",
        "role": "15-row historical qualification receipt",
    },
    "static_anchor": {
        "path": Path("campaigns/core-v1/cfd/f2-full-cup-v3-static-hold-root-integration-v1.json"),
        "schema": "core.f2.static_hold_root_integration.v1",
        "role": "static nominal anchor receipt",
    },
    "scope_review": {
        "path": Path("campaigns/core-v1/cfd/f2-static-full-cup-root-scope-review-v1.json"),
        "schema": "core.scope_review.v1",
        "role": "Core third-family scope decision",
    },
    "core_interface": {
        "path": Path("campaigns/core-v1/cfd/f2-real-qualification-interface.json"),
        "schema": "core.dataset.v1",
        "role": "existing non-formal Core interface metadata",
    },
}

BLOCKER_CODES = (
    "static_scope_not_core_third_family",
    "future_formal_runtime_admission_missing",
    "cell_00_historical_hard_failure",
    "fourteen_runtime_rows_missing",
    "core_formal_interface_not_released",
    "t1_runtime_evidence_incomplete",
    "t2_material_evidence_absent",
)

AUTHORIZATION = {
    "diagnostic_only": True,
    "readiness_projection_only": True,
    "formal_run_ready": False,
    "formal": False,
    "formal_eligible": False,
    "qualification": False,
    "T1": False,
    "T2": False,
    "T2_macro": False,
    "qualification_credit": 0,
    "T2_credit": 0,
    "credit": 0,
    "execution_authorized": False,
    "registry_eligible": False,
}

MUTATIONS = {
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "job_spec_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "queue_mutation": 0,
    "registry_mutation": 0,
}

READ_POLICY = {
    "bounded_json_allowlist_only": True,
    "max_json_bytes": MAX_JSON_BYTES,
    "production_hdf5_bi4_trajectory_opened": False,
    "production_hdf5_bi4_trajectory_stat_or_hash": False,
    "nested_artifact_paths_followed": False,
    "xml_or_native_input_opened": False,
    "solver_worker_native_gpu_queue": False,
    "registry_ledger_denominator_gate_plan_write": False,
}

SIDE_EFFECTS = {
    "bounded_json_inputs_opened": True,
    "production_hdf5_opened": False,
    "production_bi4_opened": False,
    "production_trajectory_opened": False,
    "production_artifact_stat_or_hash": False,
    "solver_started": False,
    "worker_started": False,
    "native_started": False,
    "gpu_started": False,
    "queue_started": False,
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "job_spec_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "registry_mutation": 0,
}

PROHIBITED_OPERATIONS = (
    "production_hdf5_bi4_trajectory_read_or_hash",
    "xml_native_or_solver_input_execution",
    "solver_worker_native_gpu_queue_start",
    "registry_ledger_denominator_gate_plan_mutation",
    "preparation_or_historical_failure_promoted_to_T1_or_T2",
)


class ReadinessBridgeError(ValueError):
    """A bounded input or fail-closed report contract is invalid."""


def _fail(message: str) -> None:
    raise ReadinessBridgeError(f"fail-closed: {message}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    _fail(f"non-standard JSON constant is not allowed: {token}")


def _check_finite(value: Any, label: str) -> None:
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            _fail(f"{label} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _check_finite(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_finite(item, f"{label}[{index}]")


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_json_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    if any(part in {"", ".", ".."} for part in path.parts[1:]):
        _fail(f"non-canonical JSON input path: {value}")
    if path.suffix.lower() != ".json":
        _fail(f"non-JSON input rejected before read: {value}")
    return path


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ReadinessBridgeError(f"fail-closed: cannot inspect path {path}") from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"symlink component rejected: {path}")


def _read_bounded_json(root: Path, value: str | Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _safe_json_path(root, value)
    _assert_no_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except (FileNotFoundError, OSError) as error:
        _fail(f"JSON input is unavailable: {_display_path(root, path)}")
        raise AssertionError from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"JSON input is not a single-link regular file: {_display_path(root, path)}")
        if before.st_size <= 0 or before.st_size > MAX_JSON_BYTES:
            _fail(f"JSON input exceeds bounded limit: {_display_path(root, path)}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(64 * 1024, remaining))
            if not block:
                _fail(f"JSON input was truncated while read: {_display_path(root, path)}")
            chunks.append(block)
            remaining -= len(block)
        if os.read(descriptor, 1) != b"":
            _fail(f"JSON input grew while read: {_display_path(root, path)}")
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named):
            _fail(f"JSON input changed while read: {_display_path(root, path)}")
        raw = b"".join(chunks)
    except ReadinessBridgeError:
        raise
    except OSError as error:
        raise ReadinessBridgeError(f"fail-closed: JSON input read failed: {path}") from error
    finally:
        os.close(descriptor)

    try:
        value_obj = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ReadinessBridgeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessBridgeError(f"fail-closed: invalid strict JSON input: {path}") from error
    if type(value_obj) is not dict:
        _fail(f"JSON input must be an object: {_display_path(root, path)}")
    _check_finite(value_obj, role)
    return value_obj, {
        "role": role,
        "path": _display_path(root, path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
        "nested_artifact_paths_followed": False,
    }


def _read_dependencies(
    root: Path,
    dependency_paths: Mapping[str, str | Path] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    payloads: dict[str, dict[str, Any]] = {}
    references: dict[str, dict[str, Any]] = {}
    overrides = dependency_paths or {}
    for key, spec in DEPENDENCY_SPECS.items():
        value = overrides.get(key, spec["path"])
        payload, reference = _read_bounded_json(root, value, role=spec["role"])
        if payload.get("schema") != spec["schema"]:
            _fail(f"{key} schema drift: {payload.get('schema')!r}")
        references[key] = {
            **reference,
            "expected_schema": spec["schema"],
        }
        payloads[key] = payload
    return payloads, references


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _is_false_or_zero(value: Any) -> bool:
    return value is False or (type(value) is int and value == 0)


def _validate_static_contracts(
    payloads: Mapping[str, Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]],
) -> None:
    candidate = payloads["candidate_card"]
    _require(candidate.get("family") == "F2", "candidate family drift")
    _require(candidate.get("candidate_id") == CANDIDATE_ID, "candidate id drift")
    _require(candidate.get("scope_id") == SCOPE_ID, "candidate scope drift")
    _require(candidate.get("qualification_only") is True, "candidate qualification_only drift")
    _require(candidate.get("qualified") is False, "candidate qualified marker drift")
    _require(str(candidate.get("qualification_claim", "")).startswith("none"), "candidate qualification claim drift")
    _require(candidate.get("launch_policy", {}).get("qualification_claim_allowed_now") is False, "candidate launch policy drift")

    matrix = payloads["matrix_preparation"]
    _require(matrix.get("family") == "F2" and matrix.get("candidate_id") == CANDIDATE_ID, "preparation identity drift")
    _require(matrix.get("scope_id") == SCOPE_ID, "preparation scope drift")
    _require(matrix.get("registered_cell_count") == 15, "preparation denominator drift")
    _require(matrix.get("prepared_cell_count") == 15, "prepared count drift")
    _require(matrix.get("failed_cell_count") == 0 and matrix.get("unattempted_cell_count") == 0, "preparation failure count drift")
    _require(matrix.get("candidate_matrix_inputs_materialized") is True, "prepared input materialization drift")
    _require(matrix.get("candidate_matrix_jobs_materialized") is False, "job materialization must remain false")
    _require(str(matrix.get("qualification_claim", "")).startswith("none"), "preparation qualification claim drift")
    matrix_cells = matrix.get("cells")
    _require(type(matrix_cells) is list and len(matrix_cells) == 15, "preparation cell rows drift")
    for index, cell in enumerate(matrix_cells):
        _require(cell.get("index") == index, f"preparation index drift at {index}")
        _require(cell.get("status") == "prepared", f"preparation status drift at {index}")
        _require(cell.get("attempted") is True and cell.get("preflight_pass") is True, f"preparation preflight drift at {index}")
        _require(cell.get("hash_closure_pass") is True and cell.get("failure") is None, f"preparation hash closure drift at {index}")

    audit = payloads["preparation_audit"]
    _require(audit.get("family") == "F2" and audit.get("candidate_id") == CANDIDATE_ID, "preparation audit identity drift")
    _require(audit.get("scope_id") == SCOPE_ID, "preparation audit scope drift")
    _require(audit.get("registered_cell_count") == 15 and audit.get("prepared_cell_count") == 15, "preparation audit count drift")
    _require(audit.get("failed_cell_count") == 0 and audit.get("fixed_failure_denominator") is True, "preparation audit denominator drift")
    _require(audit.get("read_only_audit") is True and audit.get("scientific_results_present") is False, "preparation audit scientific-claim drift")
    _require(audit.get("T1_numerical") is False, "preparation audit T1 drift")

    admission = payloads["qualification_admission"]
    _require(admission.get("family") == "F2" and admission.get("scope_id") == SCOPE_ID, "admission identity drift")
    controls = admission.get("admission_controls")
    _require(type(controls) is dict, "admission controls missing")
    for key in ("solver_launch_allowed", "gpu_launch_allowed", "job_spec_creation_allowed", "queue_mutation_allowed", "ledger_mutation_allowed", "registry_mutation_allowed"):
        _require(controls.get(key) is False, f"admission control drift: {key}")
    runtime_contract = admission.get("required_runtime_product_per_cell")
    _require(runtime_contract.get("fixed_denominator") == 15, "runtime product denominator drift")
    _require(runtime_contract.get("trajectory_hdf5") is True and runtime_contract.get("trajectory_sha256_and_bytes") is True, "runtime product identity contract drift")
    _require(runtime_contract.get("missing_or_failed_rows_retained") is True, "runtime failure retention drift")
    future_review = admission.get("future_job_review")
    _require(future_review.get("root_review_required_before_any_solver_or_gpu_submission") is True, "future root-review contract drift")
    _require(future_review.get("registry_scope_registration_deferred") is True, "registry deferral drift")

    root_review = payloads["root_review"]
    _require(root_review.get("family") == "F2" and root_review.get("scope_id") == SCOPE_ID, "root review identity drift")
    _require(root_review.get("status") == "approved_for_cpu_only_prepare_decode_pending_execution", "root review status drift")
    root_decision = root_review.get("root_review_decision")
    for key in ("solver_allowed", "gpu_allowed", "matrix_job_creation_allowed", "central_registry_mutation_allowed", "central_ledger_mutation_allowed"):
        _require(root_decision.get(key) is False, f"root review execution drift: {key}")
    _require(root_decision.get("cpu_only_full_matrix_prepare_decode_allowed_subsequently") is True, "CPU preparation scope drift")

    smoke_review = payloads["runtime_smoke_review"]
    _require(smoke_review.get("family") == "F2" and smoke_review.get("scope_id") == SCOPE_ID, "smoke review identity drift")
    _require(smoke_review.get("decision") == "approved_for_runtime_smoke", "smoke review decision drift")
    _require(smoke_review.get("authorized_cell_indices") == [0], "smoke review cell scope drift")
    policy = smoke_review.get("execution_policy")
    _require(policy.get("smoke_only") is True and policy.get("candidate_scope_pass_does_not_register_t1") is True, "smoke review policy drift")
    _require(policy.get("missing_or_failed_rows_remain_in_denominator") is True, "smoke denominator policy drift")

    anchor = payloads["static_anchor"]
    _require(anchor.get("family") is None or anchor.get("family") == "F2", "anchor family drift")
    _require(anchor.get("hard_integrity_pass") is True and anchor.get("event_window_complete") is True, "anchor evidence drift")
    _require(anchor.get("static_settled") is True, "anchor settled marker drift")
    _require("T1" in str(anchor.get("qualification_claim", "")), "anchor claim boundary drift")

    scope_review = payloads["scope_review"]
    _require(scope_review.get("schema") == "core.scope_review.v1", "scope review schema drift")
    _require(
        scope_review.get("candidate_sha256") == references["candidate_card"]["sha256"],
        "scope review candidate digest drift",
    )
    _require(scope_review.get("core_third_family_admitted") is False, "static third-family admission drift")
    _require(scope_review.get("static_qualification_matrix_launch_admitted") is False, "static matrix launch admission drift")

    interface = payloads["core_interface"]
    _require(interface.get("schema") == "core.dataset.v1", "Core interface schema drift")
    _require(interface.get("formal_release") is False, "Core formal-release marker drift")
    _require(type(interface.get("cases")) is list and len(interface["cases"]) == 1, "Core interface case-count drift")


def _runtime_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    _require(payload.get("family") == "F2" and payload.get("candidate_id") == CANDIDATE_ID, "runtime receipt identity drift")
    _require(payload.get("scope_id") == SCOPE_ID, "runtime receipt scope drift")
    _require(payload.get("registered_cell_count") == 15 and payload.get("fixed_failure_denominator") is True, "runtime receipt denominator drift")
    _require(payload.get("T1_numerical") is False, "runtime receipt T1 drift")
    _require(payload.get("candidate_scope_pass") is False, "runtime receipt candidate pass drift")
    rows = payload.get("cells")
    _require(type(rows) is list and len(rows) == 15, "runtime receipt row count drift")
    projection: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        _require(row.get("index") == index, f"runtime receipt index drift at {index}")
        status = row.get("status")
        _require(status in {"failed_static_gate", "missing_runtime_product"}, f"runtime receipt status drift at {index}")
        _require(row.get("passed") is False, f"runtime receipt pass marker drift at {index}")
        categories = row.get("failure_categories")
        _require(type(categories) is list and categories, f"runtime receipt failure categories missing at {index}")
        projection.append(
            {
                "index": index,
                "case_id": row.get("case_id"),
                "design_cell": row.get("design_cell"),
                "q": row.get("q"),
                "dp_m": row.get("dp_m"),
                "preparation_evidence": "prepared_input_only_not_T1",
                "historical_runtime_status": status,
                "historical_failure_categories": list(categories),
                "trajectory_content_opened_by_bridge": False,
                "formal_run_readiness": "blocked_by_historical_failure" if status == "failed_static_gate" else "blocked_by_missing_runtime_evidence",
                "T1_numerical": False,
                "T2": False,
                "qualification_credit": 0,
                "credit": 0,
            }
        )
    failed = [row for row in projection if row["historical_runtime_status"] == "failed_static_gate"]
    missing = [row for row in projection if row["historical_runtime_status"] == "missing_runtime_product"]
    _require(len(failed) == 1 and failed[0]["index"] == 0, "historical failed-row denominator drift")
    _require(len(missing) == 14, "historical missing-row denominator drift")
    return {
        "registered_rows": 15,
        "historical_runtime_pass_rows": 0,
        "historical_failed_rows": len(failed),
        "missing_runtime_rows": len(missing),
        "formal_evidence_complete": False,
        "rows": projection,
    }


def _blockers(runtime: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "code": "static_scope_not_core_third_family",
            "severity": "high",
            "detail": "scope review keeps fixed zero-motion resting-fill as prerequisite_only; it is not admitted as the Core third T1 family.",
        },
        {
            "code": "future_formal_runtime_admission_missing",
            "severity": "high",
            "detail": "the qualification admission and root review allow preparation/decode only; the historical runtime review is smoke-only for cell 0 and does not authorize a 15-cell formal run.",
        },
        {
            "code": "cell_00_historical_hard_failure",
            "severity": "high",
            "detail": "cell 0 is retained as failed_static_gate with cup closed-face endpoint, saved-chord, open-cup escape, and spatial-comparison failures.",
        },
        {
            "code": "fourteen_runtime_rows_missing",
            "severity": "high",
            "detail": f"the fixed 15-row denominator retains {runtime['missing_runtime_rows']} missing runtime products; prepared inputs do not fill those rows.",
        },
        {
            "code": "core_formal_interface_not_released",
            "severity": "high",
            "detail": "the existing Core interface is a one-case formal_release=false metadata interface, not a formal 15-cell F2 release.",
        },
        {
            "code": "t1_runtime_evidence_incomplete",
            "severity": "high",
            "detail": "no complete 15-cell runtime/observer/temporal/held-out evidence chain is bound; T1 remains false and credit remains zero.",
        },
        {
            "code": "t2_material_evidence_absent",
            "severity": "high",
            "detail": "no independent F2 material-sidecar/training/reproduction evidence is bound; preparation and historical failure are not T2 evidence.",
        },
    ]


def build_report(
    root: str | Path = LAB_ROOT,
    *,
    dependency_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Build the current bounded F2 readiness projection without execution."""

    root_path = Path(root).resolve()
    payloads, references = _read_dependencies(root_path, dependency_paths)
    _validate_static_contracts(payloads, references)
    runtime = _runtime_projection(payloads["qualification_receipt"])
    blockers = _blockers(runtime)
    checks = {
        "candidate_contract_bound": True,
        "fifteen_prepared_input_rows_bound": True,
        "fixed_fifteen_row_denominator_bound": True,
        "preparation_is_not_runtime": True,
        "historical_anchor_excluded_from_numerator": True,
        "historical_cell_00_failure_bound": True,
        "fourteen_runtime_rows_missing": True,
        "future_formal_runtime_admission": False,
        "core_formal_interface_released": False,
        "static_scope_is_core_third_family": False,
        "t1_runtime_evidence_complete": False,
        "t2_material_evidence_present": False,
    }
    report = {
        "schema": REPORT_SCHEMA,
        "record_id": RECORD_ID,
        "created_at": OBSERVED_AT_UTC,
        "scope_id": SCOPE_ID,
        "status": "blocked_fail_closed",
        "decision": "bounded_f2_resting_fill_formal_run_readiness_projection",
        "read_policy": dict(READ_POLICY),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "dependencies": references,
        "evidence": {
            "candidate": {
                "candidate_id": CANDIDATE_ID,
                "scope_id": SCOPE_ID,
                "qualification_only": payloads["candidate_card"]["qualification_only"],
                "qualified": payloads["candidate_card"]["qualified"],
                "qualification_claim": payloads["candidate_card"]["qualification_claim"],
            },
            "preparation": {
                "registered_cells": 15,
                "prepared_cells": 15,
                "failed_preparation_cells": 0,
                "unattempted_cells": 0,
                "jobs_materialized": False,
                "solver_invoked": False,
                "gpu_invoked": False,
                "evidence_class": "preparation_only_not_T1_or_T2",
            },
            "static_anchor": {
                "hard_integrity_pass": True,
                "event_window_complete": True,
                "static_settled": True,
                "numerator_eligible": False,
                "qualification_credit": 0,
                "claim": payloads["static_anchor"]["qualification_claim"],
            },
            "runtime": runtime,
            "scope_review": {
                "decision": payloads["scope_review"]["decision"],
                "core_third_family_admitted": False,
                "static_matrix_launch_admitted": False,
            },
            "core_interface": {
                "schema": payloads["core_interface"]["schema"],
                "formal_release": False,
                "case_count": 1,
            },
        },
        "checks": checks,
        "blockers": blockers,
        "readiness": {
            "preparation": {
                "required_cells": 15,
                "prepared_cells": 15,
                "pass": True,
            },
            "future_formal_run": {
                "admission_ready": False,
                "runtime_evidence_ready": False,
                "formal_run_ready": False,
                "reason": "new scope/root authorization and a fresh, complete 15-cell runtime evidence chain are required",
            },
            "formal_qualification": {
                "T1_numerical": False,
                "T2": False,
                "qualification_credit": 0,
                "credit": 0,
            },
        },
        "authorization": dict(AUTHORIZATION),
        "mutations": dict(MUTATIONS),
        "side_effects": dict(SIDE_EFFECTS),
        "validation": {
            "contract_valid": True,
            "blocked": True,
            "blockers_nonempty": True,
            "preparation_not_promoted": True,
            "historical_failure_not_promoted": True,
        },
        "next_safe_action": (
            "先由独立 root review 重新确认一个不继承 cell-00 失败边界的 F2 Definition/物理 scope，"
            "再取得 fresh 15-cell runtime admission；每个 cell 必须绑定 prepared hash、case_id、"
            "native identity、trajectory/observer/temporal evidence，并重新运行本 bridge。"
            "在此之前不得启动 solver、worker、native、GPU 或 queue，也不得把 preparation/历史失败计作 T1/T2。"
        ),
    }
    validate_report(report)
    return report


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "record_id", "created_at", "scope_id", "status", "decision",
        "read_policy", "prohibited_operations", "dependencies", "evidence", "checks",
        "blockers", "readiness", "authorization", "mutations", "side_effects",
        "validation", "next_safe_action",
    }
    if type(report) is not dict or set(report) != required:
        raise ReadinessBridgeError("fail-closed: report fields differ")
    if report["schema"] != REPORT_SCHEMA or report["record_id"] != RECORD_ID:
        raise ReadinessBridgeError("fail-closed: report identity drift")
    if report["created_at"] != OBSERVED_AT_UTC or report["scope_id"] != SCOPE_ID:
        raise ReadinessBridgeError("fail-closed: report scope/time drift")
    if report["status"] != "blocked_fail_closed" or report["decision"] != "bounded_f2_resting_fill_formal_run_readiness_projection":
        raise ReadinessBridgeError("fail-closed: report status drift")
    if report["read_policy"] != READ_POLICY or report["prohibited_operations"] != list(PROHIBITED_OPERATIONS):
        raise ReadinessBridgeError("fail-closed: read policy drift")
    if report["authorization"] != AUTHORIZATION:
        raise ReadinessBridgeError("fail-closed: authorization promotion detected")
    if report["mutations"] != MUTATIONS or report["side_effects"] != SIDE_EFFECTS:
        raise ReadinessBridgeError("fail-closed: mutation/side-effect boundary drift")
    if set(report["dependencies"]) != set(DEPENDENCY_SPECS):
        raise ReadinessBridgeError("fail-closed: dependency inventory drift")
    for key, spec in DEPENDENCY_SPECS.items():
        ref = report["dependencies"][key]
        if ref.get("expected_schema") != spec["schema"] or ref.get("role") != spec["role"]:
            raise ReadinessBridgeError(f"fail-closed: dependency contract drift: {key}")
        if ref.get("path") != spec["path"].as_posix():
            raise ReadinessBridgeError(f"fail-closed: dependency path drift: {key}")
        if ref.get("content_opened") is not True or ref.get("nested_artifact_paths_followed") is not False:
            raise ReadinessBridgeError(f"fail-closed: dependency access boundary drift: {key}")
        digest = ref.get("sha256")
        if type(digest) is not str or len(digest) != 64 or any(char not in SHA256_HEX for char in digest):
            raise ReadinessBridgeError(f"fail-closed: dependency digest drift: {key}")
    checks = report["checks"]
    if type(checks) is not dict or not all(type(value) is bool for value in checks.values()):
        raise ReadinessBridgeError("fail-closed: check projection is not boolean")
    for key in (
        "candidate_contract_bound", "fifteen_prepared_input_rows_bound", "fixed_fifteen_row_denominator_bound",
        "preparation_is_not_runtime", "historical_anchor_excluded_from_numerator", "historical_cell_00_failure_bound",
        "fourteen_runtime_rows_missing",
    ):
        if checks.get(key) is not True:
            raise ReadinessBridgeError(f"fail-closed: positive evidence check lost: {key}")
    for key in (
        "future_formal_runtime_admission", "core_formal_interface_released", "static_scope_is_core_third_family",
        "t1_runtime_evidence_complete", "t2_material_evidence_present",
    ):
        if checks.get(key) is not False:
            raise ReadinessBridgeError(f"fail-closed: closed gate promoted: {key}")
    blockers = report["blockers"]
    if type(blockers) is not list or [item.get("code") for item in blockers] != list(BLOCKER_CODES):
        raise ReadinessBridgeError("fail-closed: blocker inventory drift")
    if not all(item.get("severity") == "high" and item.get("detail") for item in blockers):
        raise ReadinessBridgeError("fail-closed: blocker severity/detail drift")
    evidence = report["evidence"]
    runtime = evidence.get("runtime")
    if runtime.get("registered_rows") != 15 or runtime.get("historical_runtime_pass_rows") != 0:
        raise ReadinessBridgeError("fail-closed: runtime denominator projection drift")
    if runtime.get("historical_failed_rows") != 1 or runtime.get("missing_runtime_rows") != 14:
        raise ReadinessBridgeError("fail-closed: runtime failure/missing projection drift")
    rows = runtime.get("rows")
    if type(rows) is not list or len(rows) != 15 or [row.get("index") for row in rows] != list(range(15)):
        raise ReadinessBridgeError("fail-closed: case denominator rows drift")
    if any(row.get("T1_numerical") is not False or row.get("T2") is not False or row.get("credit") != 0 for row in rows):
        raise ReadinessBridgeError("fail-closed: case-level promotion detected")
    if sum(row.get("historical_runtime_status") == "failed_static_gate" for row in rows) != 1:
        raise ReadinessBridgeError("fail-closed: failed row count drift")
    if sum(row.get("historical_runtime_status") == "missing_runtime_product" for row in rows) != 14:
        raise ReadinessBridgeError("fail-closed: missing row count drift")
    readiness = report["readiness"]
    if readiness["preparation"] != {"required_cells": 15, "prepared_cells": 15, "pass": True}:
        raise ReadinessBridgeError("fail-closed: preparation readiness drift")
    if readiness["future_formal_run"]["formal_run_ready"] is not False or readiness["future_formal_run"]["admission_ready"] is not False:
        raise ReadinessBridgeError("fail-closed: formal-run readiness promotion detected")
    if readiness["formal_qualification"] != {"T1_numerical": False, "T2": False, "qualification_credit": 0, "credit": 0}:
        raise ReadinessBridgeError("fail-closed: formal qualification drift")
    validation = report["validation"]
    if validation != {
        "contract_valid": True,
        "blocked": True,
        "blockers_nonempty": True,
        "preparation_not_promoted": True,
        "historical_failure_not_promoted": True,
    }:
        raise ReadinessBridgeError("fail-closed: validation boundary drift")
    if not isinstance(report["next_safe_action"], str) or not report["next_safe_action"]:
        raise ReadinessBridgeError("fail-closed: next safe action missing")
    return dict(report)


def _write_immutable(path: str | Path, payload: bytes) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(target), flags, 0o644)
    except FileExistsError:
        raise
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
    finally:
        os.close(descriptor)
    return target


def _zh_report(report: Mapping[str, Any]) -> str:
    blocker_lines = "\n".join(
        f"- `{item['code']}`：{item['detail']}"
        for item in report["blockers"]
    )
    runtime = report["evidence"]["runtime"]
    preparation = report["evidence"]["preparation"]
    return f"""# F2 resting-fill formal-run readiness/evidence bridge V1

状态：`{report['status']}`。

本 bridge 只读取固定 allow-list 的 bounded JSON，并把 F2 static full-cup resting-fill 的 preparation、历史 runtime receipt、admission 和 Core interface metadata 串成一个 15 行证据投影。它不打开或统计生产 HDF5/BI4/trajectory，不启动 solver、worker、native、GPU、queue，也不修改 registry、ledger、denominator、gate 或 PLAN。

## 当前已经绑定

- v4 CPU/native preparation：15/15 输入行完成 hash/preflight closure；这仍是 preparation-only，不是 T1/T2。
- 固定失败分母：15 行保持不变；cell 0 是历史 `failed_static_gate`，其余 14 行是 `missing_runtime_product`。
- 静态 nominal anchor：历史 hard-integrity/event/static-settled 事实仅作为 anchor，明确排除 numerator。
- Core interface：现有接口只有 1 个 case 且 `formal_release=false`。

## 未闭合 blocker

{blocker_lines}

因此：prepared={preparation['prepared_cells']}/{preparation['registered_cells']}，historical failed={runtime['historical_failed_rows']}，missing runtime={runtime['missing_runtime_rows']}；`formal_run_ready=false`、`T1=false`、`T2=false`、credit=0。不能把 preparation 或 historical hard failure 当成成功。

下一步必须先获得新的物理 scope/独立 root review 与 fresh 15-cell runtime admission，再为每个 cell 绑定 prepared hash、case_id、native identity、trajectory/observer/temporal evidence，随后重新运行 bridge。

机器报告：`F2-RESTING-FILL-FORMAL-RUN-READINESS-BRIDGE-V1-2026-09-28.json`。
"""


def write_outputs(report: Mapping[str, Any], output: str | Path, zh_output: str | Path) -> tuple[Path, Path]:
    validate_report(report)
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    zh_payload = _zh_report(report).encode("utf-8")
    return _write_immutable(output, payload), _write_immutable(zh_output, zh_payload)


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    value, _reference = _read_bounded_json(LAB_ROOT, path, role="checked-in bridge report")
    validate_report(value)
    expected = build_report()
    if value != expected:
        raise ReadinessBridgeError("fail-closed: checked-in bridge report differs from current bounded evidence")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    args = parser.parse_args(argv)
    report = build_report(args.root)
    write_outputs(report, args.output, args.zh_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
