#!/usr/bin/env python3
"""Join the checked-in F8/R008 evidence into a non-authorizing next-step view.

This bridge is intentionally additive.  It does not replace the existing
target-kernel intake/local inventory, readiness-v8 audit, BI4/native-table
reviews, metric adapters, native-integrity registry, or terminal-matrix
contracts.  It verifies that their current bounded reports still agree, then
emits one deterministic admission projection and a per-case terminal
verification plan.

Only bounded regular JSON/source files are read.  The bridge never follows a
target-kernel artifact reference, opens production BI4/HDF5/solver frames, or
invokes privileged probes, native/solver/worker/GPU/queue code.  A successful
bridge run therefore means "the next evidence request is well-defined", not
that runtime execution is authorized or that T1 is complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f8_r008_native_integrity_registry_v1 as native_registry


SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"

SCHEMA = "core.cfd.f8.r008_admission_verification_bridge.v1"
REPORT_SCHEMA = "core.cfd.f8.r008_admission_verification_bridge_report.v1"
RECORD_ID = "f8-r008-admission-verification-bridge-v1"
REPORT_RECORD_ID = "f8-r008-admission-verification-bridge-report-v1"
STATUS = "diagnostic_only_admission_verification_blocked"

DEFAULT_REPORT = Path(
    "reports/F8-R008-ADMISSION-VERIFICATION-BRIDGE-V1-2026-09-29-RERUN1.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F8-R008-ADMISSION-VERIFICATION-BRIDGE-V1-2026-09-29-RERUN1.zh-CN.md"
)

MAX_INPUT_BYTES = 2 * 1024 * 1024
SHA256_HEX = frozenset("0123456789abcdef")

AUTHORIZATION = {
    "diagnostic_only": True,
    "readiness_pass": False,
    "T1_numerical": False,
    "formal": False,
    "formal_eligible": False,
    "execution_authority": False,
    "capability_minted": False,
    "qualification_credit": 0,
}

MUTATIONS = {
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "registry_mutation": 0,
}

READ_POLICY = {
    "bounded_canonical_json_and_source_reads_only": True,
    "small_file_metadata_only": True,
    "production_bi4_hdf5_or_solver_frame_read": False,
    "privileged_probe": False,
    "fanotify_or_kernel_probe": False,
    "native_or_solver": False,
    "worker_gpu_or_queue": False,
    "registry_ledger_gate_completion_write": False,
}

PROHIBITED_OPERATIONS = [
    "production_bi4_hdf5_or_solver_frame_read",
    "privileged_probe",
    "fanotify_or_kernel_probe",
    "native_or_solver",
    "worker_gpu_or_queue",
    "registry_ledger_gate_completion_mutation",
]

SIDE_EFFECTS = {
    "completion_mutation": 0,
    "gate_mutation": 0,
    "gpu_started": False,
    "kernel_started": False,
    "ledger_mutation": 0,
    "native_started": False,
    "plan_mutation": 0,
    "privileged_probe_started": False,
    "queue_started": False,
    "registry_mutation": 0,
    "solver_started": False,
    "system_write": 0,
    "worker_started": False,
}


class AdmissionVerificationBridgeError(ValueError):
    """A bridge input is missing, stale, malformed, or overclaims authority."""

    def __init__(self, message: str, *, code: str = "invalid_bridge_input") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, *, code: str = "invalid_bridge_input") -> None:
    raise AdmissionVerificationBridgeError(message, code=code)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}", code="duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    _fail(f"non-standard JSON constant is not permitted: {token}", code="non_strict_json")


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _canonical_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = LAB_ROOT / path
    if path.as_posix() != str(path) or any(part in {"", ".", ".."} for part in path.parts[1:]):
        _fail(f"input path is not canonical: {value}", code="path_traversal")
    return path


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise AdmissionVerificationBridgeError(
                f"could not inspect input path: {path}", code="path_inspection"
            ) from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"input path contains a symlink: {path}", code="symlink_path")


def _read_bounded(path: str | Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    target = _canonical_path(path)
    _assert_no_symlink_components(target)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(target), flags)
    except FileNotFoundError as error:
        _fail(f"{label} is missing: {_display_path(target)}", code="missing_input")
        raise AssertionError from error
    except OSError as error:
        _fail(f"{label} cannot be opened safely: {_display_path(target)}", code="unsafe_input")
        raise AssertionError from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{label} must be a single-link regular file", code="unsafe_input")
        if before.st_size <= 0 or before.st_size > MAX_INPUT_BYTES:
            _fail(f"{label} exceeds the bounded read limit", code="oversize")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(64 * 1024, remaining))
            if not block:
                _fail(f"{label} was truncated while being read", code="input_drift")
            chunks.append(block)
            remaining -= len(block)
        if os.read(descriptor, 1) != b"":
            _fail(f"{label} grew while being read", code="input_drift")
        after = os.fstat(descriptor)
        named = os.stat(target, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named):
            _fail(f"{label} changed while being read", code="input_drift")
        raw = b"".join(chunks)
    except AdmissionVerificationBridgeError:
        raise
    except OSError as error:
        _fail(f"{label} could not be read safely", code="read_error")
        raise AssertionError from error
    finally:
        os.close(descriptor)

    return raw, {
        "path": _display_path(target),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _read_json(path: str | Path, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = _read_bounded(path, label=label)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except AdmissionVerificationBridgeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not strict UTF-8 JSON", code="invalid_json")
        raise AssertionError from error
    if type(value) is not dict:
        _fail(f"{label} must be a JSON object", code="json_not_object")
    return value, reference


def _sha256(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in SHA256_HEX for char in value):
        _fail(f"{label} is not lowercase SHA-256", code="digest_format")
    return value


def _require(condition: bool, message: str, *, code: str = "invalid_bridge_input") -> None:
    if not condition:
        _fail(message, code=code)


def _ref(
    value: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    key: str,
    expected_schema: str | None = None,
    expected_record_id: str | None = None,
    expected_status: str | None = None,
    scope: str = "optional",
) -> dict[str, Any]:
    _require(type(value.get("schema")) is str, f"{key} schema is missing")
    _require(type(value.get("record_id")) is str, f"{key} record_id is missing")
    if expected_schema is not None:
        _require(value["schema"] == expected_schema, f"{key} schema drift")
    if expected_record_id is not None:
        _require(value["record_id"] == expected_record_id, f"{key} record_id drift")
    if expected_status is not None:
        _require(value.get("status") == expected_status, f"{key} status drift")
    if scope == "required":
        _require(value.get("scope_id") == SCOPE_ID, f"{key} scope drift", code="scope_drift")
    elif scope == "absent":
        _require("scope_id" not in value, f"{key} unexpectedly declares a scope")
    else:
        if "scope_id" in value:
            _require(value["scope_id"] == SCOPE_ID, f"{key} scope drift", code="scope_drift")
    return {
        **dict(reference),
        "record_id": value["record_id"],
        "schema": value["schema"],
        "scope_id": value.get("scope_id"),
        "status": value.get("status"),
    }


DEPENDENCY_SPECS: dict[str, dict[str, Any]] = {
    "target_kernel_evidence_intake": {
        "path": "reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json",
        "schema": "core.cfd.f8.r008.target_kernel_evidence_intake_report.v1",
        "record_id": "f8-r008-target-kernel-evidence-intake-report-v1",
        "status": "blocked_missing_external_target_evidence",
        "scope": "absent",
    },
    "target_kernel_local_inventory": {
        "path": "reports/F8-R008-TARGET-KERNEL-LOCAL-INVENTORY-V1-2026-09-28.json",
        "schema": "core.cfd.f8.r008.target_kernel_local_inventory_report.v1",
        "record_id": "f8-r008-target-kernel-local-inventory-v1",
        "status": "diagnostic_only_local_target_kernel_inventory_incomplete",
        "scope": "required",
    },
    "target_kernel_readiness_projection": {
        "path": "reports/F8-R008-TARGET-KERNEL-READINESS-PROJECTION-V1-2026-09-28.json",
        "schema": "core.cfd.f8.r008.target_kernel_readiness_projection_report.v1",
        "record_id": "f8-r008-target-kernel-readiness-projection-v1",
        "status": "diagnostic_only_target_kernel_readiness_blocked",
        "scope": "required",
    },
    "readiness_v8": {
        "path": (
            "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
            "t1-execution-readiness-audit-v8/receipt.json"
        ),
        "schema": "core.cfd.f8.r008_execution_readiness_audit.v8",
        "record_id": "f8-r008-execution-readiness-audit-v8",
        "status": "static_selector_domain_bound_full_runtime_readiness_blocked",
        "scope": "required",
    },
    "terminal_matrix": {
        "path": "reports/F8-R008-TERMINAL-EVIDENCE-MATRIX-INTAKE-V1-2026-09-28.json",
        "schema": "core.cfd.f8.r008_terminal_evidence_matrix_intake_report.v1",
        "record_id": "f8-r008-terminal-evidence-matrix-intake-v1",
        "status": "diagnostic_only_terminal_evidence_matrix_blocked",
        "scope": "required",
    },
    "terminal_matrix_consistency": {
        "path": "reports/F8-R008-TERMINAL-MATRIX-READINESS-CONSISTENCY-V1-2026-09-28.json",
        "schema": "core.cfd.f8.r008_terminal_matrix_readiness_consistency_report.v1",
        "record_id": "f8-r008-terminal-matrix-readiness-consistency-v1",
        "status": "diagnostic_only_terminal_matrix_readiness_consistency_blocked",
        "scope": "required",
    },
    "trusted_identity": {
        "path": "reports/F8-R008-TRUSTED-AUTHORITY-WORKER-RUNTIME-IDENTITY-CONTRACT-V1.json",
        "schema": "core.cfd.f8.r008_trusted_identity_contract_report.v1",
        "record_id": "f8-r008-trusted-identity-contract-report-v1",
        "status": "synthetic_only_non_authorizing_contract_design",
        "scope": "required",
    },
    "trusted_handoff": {
        "path": "reports/F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-CONTRACT-V1.json",
        "schema": "core.cfd.f8.r008_trusted_worker_runtime_handoff_report.v1",
        "record_id": "f8-r008-trusted-worker-runtime-handoff-report-v1",
        "status": "synthetic_only_non_authorizing_handoff_contract_design",
        "scope": "required",
    },
    "trusted_postrun": {
        "path": "reports/F8-R008-TRUSTED-WORKER-RUNTIME-POSTRUN-MATRIX-CLAIM-ADAPTER-V1.json",
        "schema": "core.cfd.f8.r008_trusted_worker_runtime_postrun_matrix_claim_report.v1",
        "record_id": "f8-r008-trusted-worker-runtime-postrun-matrix-claim-report-v1",
        "status": "synthetic_only_non_authorizing_postrun_matrix_claim_binding_design",
        "scope": "required",
    },
    "safe_bi4_review": {
        "path": (
            "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
            "safe-bi4-decoder-review-v1/receipt.json"
        ),
        "schema": "core.cfd.f8.r008_safe_bi4_decoder_review.v1",
        "record_id": "f8-r008-safe-bi4-decoder-review-v1",
        "status": "static_safe_decoder_review_passed_no_native_execution",
        "scope": "required",
    },
    "native_table_metric_review": {
        "path": (
            "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
            "native-fluid-table-schema-v2/metric-review-v2/receipt.json"
        ),
        "schema": "core.cfd.f8.r008_native_fluid_table_metric_implementation_review.v2",
        "record_id": "f8-r008-native-fluid-table-metric-implementation-review-v2",
        "status": "static_metric_implementation_review_passed_no_execution_or_t1_credit",
        "scope": "absent",
    },
    "metric_matrix_review": {
        "path": (
            "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
            "native-fluid-table-schema-v2/metric-matrix-review-v3/receipt.json"
        ),
        "schema": "core.cfd.f8.r008_t1_metric_matrix_implementation_review.v3",
        "record_id": "f8-r008-t1-metric-matrix-implementation-review-v3",
        "status": "static_implementation_review_passed_no_execution_or_t1_credit",
        "scope": "absent",
    },
}

SOURCE_COMPONENTS = {
    "target_kernel_evidence_intake": "scripts/f8_r008_target_kernel_evidence_intake_v1.py",
    "target_kernel_local_inventory": "scripts/f8_r008_target_kernel_local_inventory_v1.py",
    "target_kernel_readiness_projection": "scripts/f8_r008_target_kernel_readiness_projection_v1.py",
    "terminal_matrix_intake": "scripts/f8_r008_terminal_evidence_matrix_intake_v1.py",
    "terminal_matrix_consistency": "scripts/f8_r008_terminal_matrix_readiness_consistency_v1.py",
    "native_integrity_registry": "scripts/f8_r008_native_integrity_registry_v1.py",
    "safe_bi4_decoder": "scripts/f8_r008_safe_bi4_decoder_v1.py",
    "safe_bi4_metadata_binding": "scripts/f8_r008_safe_bi4_metadata_binding_v1.py",
    "native_table_metric_bundle_verifier": "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
    "metric_matrix_adapter_v5": "scripts/f8_r008_t1_metric_matrix_adapter_v5.py",
    "bridge": "scripts/f8_r008_admission_verification_bridge_v1.py",
}

REVIEW_EVIDENCE_PATHS = {
    "safe_bi4_review": (
        "scripts/f8_r008_safe_bi4_decoder_v1.py",
        "scripts/f8_r008_bi4_format_static_audit_v3.py",
    ),
    "native_table_metric_review": (
        "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v1.py",
    ),
    "metric_matrix_review": (
        "scripts/f8_r008_t1_metric_matrix_adapter_v2.py",
        "scripts/f8_r008_native_fluid_table_metric_bundle_verifier_v2.py",
        "scripts/f8_r008_t1_metric_adapter_v2.py",
    ),
}

BLOCKER_CODES = (
    "target_kernel_external_evidence_incomplete",
    "target_kernel_source_build_identity_unproven",
    "trusted_runtime_identity_and_source_callgraph_unverified",
    "native_integrity_15_by_8_cells_unverified",
    "r008_15_case_t1_terminal_evidence_missing",
)


def _load_dependencies(
    dependency_paths: Mapping[str, str | Path] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    paths = dict(dependency_paths or {})
    values: dict[str, dict[str, Any]] = {}
    refs: dict[str, dict[str, Any]] = {}
    for key, spec in DEPENDENCY_SPECS.items():
        path = paths.get(key, spec["path"])
        value, reference = _read_json(path, label=f"dependency {key}")
        refs[key] = _ref(
            value,
            reference,
            key=key,
            expected_schema=spec["schema"],
            expected_record_id=spec["record_id"],
            expected_status=spec["status"],
            scope=spec["scope"],
        )
        values[key] = value
    return values, refs


def _load_sources() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, path in SOURCE_COMPONENTS.items():
        _raw, reference = _read_bounded(path, label=f"source component {key}")
        result[key] = reference
    return result


def _validate_zero_authority(value: Mapping[str, Any], key: str) -> None:
    authorization = value.get("authorization")
    if type(authorization) is dict:
        for field, expected in AUTHORIZATION.items():
            if field in authorization:
                _require(authorization[field] == expected, f"{key} authorization overclaim: {field}", code="authorization_drift")
    for field in ("readiness_pass", "T1_numerical", "formal"):
        if field in value:
            _require(value[field] is False, f"{key} top-level authorization overclaim: {field}", code="authorization_drift")
    execution_authority = value.get("execution_authority")
    if type(execution_authority) is bool:
        _require(execution_authority is False, f"{key} top-level authorization overclaim: execution_authority", code="authorization_drift")
    elif type(execution_authority) is dict:
        for field in ("solver", "worker", "gpu", "queue", "native", "privileged_probe"):
            if field in execution_authority:
                _require(execution_authority[field] is False, f"{key} execution authority overclaim: {field}", code="authorization_drift")
    if "qualification_credit" in value:
        _require(value["qualification_credit"] == 0, f"{key} qualification credit overclaim", code="authorization_drift")


def _validate_dependency_semantics(
    values: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], dict[str, float], dict[str, Any]]:
    for key, value in values.items():
        _validate_zero_authority(value, key)

    local = values["target_kernel_local_inventory"]
    local_validation = local.get("validation")
    _require(type(local_validation) is dict, "local inventory validation is missing")
    _require(local_validation.get("required_pins_complete") is False, "local inventory promotes complete pins", code="authorization_drift")
    _require(local_validation.get("source_commit_proven") is False, "local inventory promotes source commit", code="authorization_drift")
    _require(local_validation.get("source_tree_proven") is False, "local inventory promotes source tree", code="authorization_drift")
    _require(local_validation.get("build_id_proven") is False, "local inventory promotes build id", code="authorization_drift")

    readiness = values["target_kernel_readiness_projection"]
    target_kernel = readiness.get("target_kernel")
    trusted_runtime = readiness.get("trusted_runtime")
    readiness_validation = readiness.get("validation")
    _require(type(target_kernel) is dict and type(trusted_runtime) is dict and type(readiness_validation) is dict,
             "target-kernel readiness projection is incomplete")
    _require(target_kernel.get("external_evidence_complete") is False, "target-kernel evidence unexpectedly complete", code="authorization_drift")
    _require(target_kernel.get("all_pins_complete") is False, "target-kernel pins unexpectedly complete", code="authorization_drift")
    _require(readiness_validation.get("source_callgraph_conformance") is False, "source callgraph unexpectedly proven", code="authorization_drift")
    _require(readiness_validation.get("target_kernel_runtime_conformance") is False, "kernel runtime conformance unexpectedly proven", code="authorization_drift")
    _require(trusted_runtime.get("production_authority_authenticated") is False, "production authority unexpectedly authenticated", code="authorization_drift")
    _require(trusted_runtime.get("production_runtime_identity_authenticated") is False, "production runtime identity unexpectedly authenticated", code="authorization_drift")

    matrix = values["terminal_matrix"]
    matrix_summary = matrix.get("summary")
    matrix_contract = matrix.get("matrix_contract")
    _require(type(matrix_summary) is dict and type(matrix_contract) is dict, "terminal matrix summary is incomplete")
    _require(matrix_summary.get("missing_rows") == native_registry.CASE_COUNT, "terminal matrix denominator is not the frozen 15 rows", code="denominator_drift")
    _require(matrix_summary.get("T1_rows") == 0 and matrix_summary.get("formal_rows") == 0, "terminal matrix contains a promoted row", code="authorization_drift")

    consistency = values["terminal_matrix_consistency"]
    matrix_binding = consistency.get("matrix_binding")
    attempt_binding = consistency.get("attempt_terminal_binding")
    cross_binding = consistency.get("cross_binding")
    _require(type(matrix_binding) is dict and type(attempt_binding) is dict and type(cross_binding) is dict,
             "terminal consistency projection is incomplete")
    _require(matrix_binding.get("case_count") == native_registry.CASE_COUNT, "terminal consistency case count drift", code="denominator_drift")
    _require(matrix_binding.get("rows_bound") == native_registry.CASE_COUNT, "terminal consistency rows are not fully bound", code="denominator_drift")
    _require(matrix_binding.get("rows_exact_and_unique") is True, "terminal consistency rows are not exact", code="denominator_drift")
    _require(attempt_binding.get("present") is False, "attempt projection unexpectedly present", code="authorization_drift")
    _require(attempt_binding.get("terminal_markers_bound") is False, "terminal markers unexpectedly bound", code="authorization_drift")
    _require(cross_binding.get("consistent") is False, "terminal consistency unexpectedly passed", code="authorization_drift")
    _require(cross_binding.get("blockers") == [
        "attempt_evidence_missing",
        "attempt_nonce_markers_missing",
        "terminal_markers_missing",
    ], "terminal consistency blocker set drift")

    frozen_case_ids = tuple(native_registry.frozen_qualification_case_ids())
    _require(frozen_case_ids == native_registry.EXPECTED_QUALIFICATION_CASE_IDS, "native registry denominator drift", code="denominator_drift")
    consistency_case_ids = tuple(matrix_binding.get("case_ids", ()))
    _require(consistency_case_ids == frozen_case_ids, "terminal/native case denominator differs", code="denominator_drift")

    rows = matrix.get("rows")
    _require(type(rows) is list and len(rows) == native_registry.CASE_COUNT, "terminal matrix rows are missing")
    row_by_id: dict[str, Mapping[str, Any]] = {}
    q_by_case: dict[str, float] = {}
    for row in rows:
        _require(type(row) is dict and type(row.get("case_id")) is str, "terminal matrix row is malformed")
        case_id = row["case_id"]
        _require(case_id not in row_by_id, "terminal matrix contains duplicate case id", code="denominator_drift")
        row_by_id[case_id] = row
        _require(type(row.get("q")) in (int, float) and not isinstance(row.get("q"), bool), f"terminal matrix q is malformed: {case_id}")
        q_by_case[case_id] = float(row["q"])
    _require(tuple(row_by_id) == frozen_case_ids, "terminal matrix case order differs from frozen denominator", code="denominator_drift")

    terminal_rows = attempt_binding.get("rows")
    _require(type(terminal_rows) is list and len(terminal_rows) == native_registry.CASE_COUNT, "terminal consistency rows are missing")
    terminal_by_id = {row.get("case_id"): row for row in terminal_rows if type(row) is dict}
    _require(tuple(terminal_by_id) == frozen_case_ids, "terminal verification row order differs from frozen denominator", code="denominator_drift")
    for case_id in frozen_case_ids:
        row = terminal_by_id[case_id]
        _require(row.get("marker_status") == "missing", f"terminal marker status is not missing: {case_id}")
        _require(row.get("terminal_markers_bound") is False, f"terminal marker unexpectedly bound: {case_id}", code="authorization_drift")

    _require(refs["terminal_matrix"]["sha256"] == consistency["input_refs"]["terminal_matrix"]["sha256"], "terminal matrix digest is not rebound")
    _require(refs["target_kernel_readiness_projection"]["sha256"] == consistency["input_refs"]["target_readiness"]["sha256"], "target readiness digest is not rebound")
    _require(refs["trusted_handoff"]["sha256"] == consistency["input_refs"]["trusted_handoff"]["sha256"], "handoff digest is not rebound")
    _require(refs["trusted_identity"]["sha256"] == consistency["input_refs"]["trusted_identity"]["sha256"], "identity digest is not rebound")

    review_checks: dict[str, Any] = {}
    for review_key, required_paths in REVIEW_EVIDENCE_PATHS.items():
        review = values[review_key]
        evidence = review.get("evidence")
        _require(type(evidence) is list, f"{review_key} evidence list is missing")
        by_path = {
            item.get("path"): item
            for item in evidence
            if type(item) is dict and type(item.get("path")) is str
        }
        matches: list[dict[str, Any]] = []
        for path in required_paths:
            item = by_path.get(path)
            _require(type(item) is dict, f"{review_key} does not bind {path}", code="source_digest_drift")
            source_key = next((key for key, source in SOURCE_COMPONENTS.items() if source == path), None)
            if source_key is not None:
                _require(item.get("bytes") == refs["_sources"][source_key]["bytes"] and item.get("sha256") == refs["_sources"][source_key]["sha256"],
                         f"{review_key} source digest drift: {path}", code="source_digest_drift")
            matches.append({"path": path, "bytes": item.get("bytes"), "sha256": item.get("sha256")})
        review_checks[review_key] = {
            "review_status": review.get("status"),
            "execution_boundary_zero": True,
            "source_bindings_match": True,
            "matched_paths": matches,
        }

    return list(frozen_case_ids), q_by_case, {
        "review_checks": review_checks,
        "row_by_id": row_by_id,
        "target_kernel": target_kernel,
        "trusted_runtime": trusted_runtime,
        "readiness_validation": readiness_validation,
        "matrix_summary": matrix_summary,
        "matrix_contract": matrix_contract,
        "matrix_binding": matrix_binding,
        "attempt_binding": attempt_binding,
        "cross_binding": cross_binding,
    }


def _frozen_denominator_refs() -> dict[str, dict[str, Any]]:
    scope_path = native_registry.bundle.FROZEN_SCOPE_RECEIPT.relative_to(LAB_ROOT).as_posix()
    pack_path = native_registry.bundle.FROZEN_DEFINITION_PACK.relative_to(LAB_ROOT).as_posix()
    result: dict[str, dict[str, Any]] = {}
    for key, path in (("scope_receipt", scope_path), ("definition_control_pack", pack_path)):
        _raw, reference = _read_bounded(path, label=f"frozen denominator {key}")
        result[key] = reference
    return result


def _native_registry_projection(case_ids: list[str]) -> dict[str, Any]:
    _require(tuple(case_ids) == native_registry.EXPECTED_QUALIFICATION_CASE_IDS, "native registry case IDs drift", code="denominator_drift")
    gate_registry = [
        {
            "gate_id": gate_id,
            "definition_status": definition_status,
            "outcomes": list(outcomes),
        }
        for gate_id, definition_status, outcomes in native_registry.GATE_REGISTRY
    ]
    registry_bytes = json.dumps(gate_registry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": native_registry.SCHEMA,
        "case_count": native_registry.CASE_COUNT,
        "gate_count": native_registry.GATE_COUNT,
        "denominator_cells": native_registry.CASE_COUNT * native_registry.GATE_COUNT,
        "case_ids": list(case_ids),
        "gate_ids": list(native_registry.GATE_IDS),
        "gate_registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "open_gate_ids": [
            gate_id for gate_id, definition_status, _outcomes in native_registry.GATE_REGISTRY
            if definition_status == "open"
        ],
        "aggregation_only": True,
        "evidence_bindings_verified": False,
        "native_integrity_evaluated": False,
        "T1_numerical": False,
        "readiness_pass": False,
        "qualification_credit": 0,
        "next_step": "supply one independently bound gate result for every case/gate cell, preserving all 120 cells",
    }


def _verification_plan(case_ids: list[str], q_by_case: Mapping[str, float]) -> dict[str, Any]:
    stages = [
        {
            "stage": "B",
            "name": "materialization",
            "required_evidence": "trusted B receipt plus output manifest bound to the frozen Definition/control inputs",
            "current_status": "not_verified",
        },
        {
            "stage": "C",
            "name": "solver_execution",
            "required_evidence": "trusted C receipt, process journal, runtime configuration, complete solver frame manifest, and normal completion",
            "current_status": "not_verified",
        },
        {
            "stage": "D",
            "name": "native_table_and_metric_verification",
            "required_evidence": "safe BI4/native table provenance, source/runtime identity, timestep adjudication, and reviewed metric result",
            "current_status": "not_verified",
        },
        {
            "stage": "terminal",
            "name": "terminal_and_final_fput_verification",
            "required_evidence": "trusted attempt/nonce markers, terminal supervisor evidence, fanotify/final-fput causal witness, and terminal matrix binding",
            "current_status": "not_verified",
        },
    ]
    rows = [
        {
            "case_id": case_id,
            "q": q_by_case[case_id],
            "current_status": "blocked_missing_execution_evidence",
            "B": "not_verified",
            "C": "not_verified",
            "D": "not_verified",
            "terminal": "missing",
            "native_integrity_gate_cells": native_registry.GATE_COUNT,
            "qualification_credit": 0,
            "next_action": "obtain an independently authorized B→C→D attempt bundle and terminal receipt for this exact case id",
        }
        for case_id in case_ids
    ]
    return {
        "case_count": len(case_ids),
        "case_ids": case_ids,
        "stages": stages,
        "rows": rows,
        "ordering": "B_then_C_then_D_then_terminal_then_T1_adjudication",
        "execution_authority_granted": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


def build_report(
    *,
    dependency_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    values, refs = _load_dependencies(dependency_paths)
    sources = _load_sources()
    refs_with_sources = dict(refs)
    refs_with_sources["_sources"] = sources
    case_ids, q_by_case, observed = _validate_dependency_semantics(values, refs_with_sources)
    denominator_refs = _frozen_denominator_refs()
    native_projection = _native_registry_projection(case_ids)

    blockers = [
        {
            "code": BLOCKER_CODES[0],
            "severity": "high",
            "detail": "The external target-kernel evidence intake remains blocked and no complete external source/UAPI/config/build identity set is bound.",
            "evidence": [refs["target_kernel_evidence_intake"]["path"], refs["target_kernel_readiness_projection"]["path"]],
        },
        {
            "code": BLOCKER_CODES[1],
            "severity": "high",
            "detail": "The local inventory proves only the running release/config and bounded UAPI sample; source commit/tree and build identity remain unproven.",
            "evidence": [refs["target_kernel_local_inventory"]["path"]],
        },
        {
            "code": BLOCKER_CODES[2],
            "severity": "high",
            "detail": "The trusted authority/worker/runtime artifacts are synthetic-only and source-callgraph/target-kernel runtime conformance are still false.",
            "evidence": [refs["trusted_identity"]["path"], refs["trusted_handoff"]["path"], refs["target_kernel_readiness_projection"]["path"]],
        },
        {
            "code": BLOCKER_CODES[3],
            "severity": "high",
            "detail": "The native registry fixes 15×8=120 cells but only defines the aggregation contract; no bound native-integrity evidence evaluates those cells.",
            "evidence": [sources["native_integrity_registry"]["path"], denominator_refs["scope_receipt"]["path"], denominator_refs["definition_control_pack"]["path"]],
        },
        {
            "code": BLOCKER_CODES[4],
            "severity": "high",
            "detail": "All 15 terminal rows remain missing: no trusted B/C/D attempt projection, nonce markers, terminal supervisor/final-fput evidence, or real T1 result exists.",
            "evidence": [refs["terminal_matrix"]["path"], refs["terminal_matrix_consistency"]["path"]],
        },
    ]

    dependency_output = {key: value for key, value in refs.items()}
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "scope_id": SCOPE_ID,
        "status": STATUS,
        "admission": {
            "static_dependency_chain_bound": True,
            "source_contracts_bound": True,
            "target_kernel_static_pin_complete": False,
            "target_kernel_source_integrity_verified": False,
            "source_callgraph_conformance": False,
            "trusted_runtime_identity_verified": False,
            "native_integrity_verified": False,
            "terminal_matrix_complete": False,
            "t1_execution_chain_ready": False,
            "next_step": "collect separately authorized target/runtime/native/terminal evidence, then re-run this bridge before any T1 adjudication",
        },
        "authorization": dict(AUTHORIZATION),
        "blockers": blockers,
        "dependencies": dependency_output,
        "source_contracts": {
            "status": "repository_static_sources_bound_target_source_not_proven",
            "target_source_tree_proven": False,
            "target_source_commit_proven": False,
            "runtime_loaded_identity_proven": False,
            "components": sources,
            "reviewed_static_components": observed["review_checks"],
        },
        "target_kernel": {
            "local_inventory_status": values["target_kernel_local_inventory"]["status"],
            "external_intake_status": values["target_kernel_evidence_intake"]["status"],
            "readiness_projection_status": values["target_kernel_readiness_projection"]["status"],
            "kernel_release_observed": values["target_kernel_local_inventory"]["validation"]["kernel_release_observed"],
            "matching_config_observed": values["target_kernel_local_inventory"]["validation"]["matching_config_observed"],
            "uapi_sample_complete": values["target_kernel_local_inventory"]["validation"]["uapi_sample_complete"],
            "source_commit_proven": False,
            "source_tree_proven": False,
            "build_id_proven": False,
            "all_required_pins_complete": False,
            "runtime_conformance": False,
        },
        "runtime_and_terminal": {
            "production_authority_authenticated": False,
            "production_runtime_identity_authenticated": False,
            "runtime_measured": False,
            "source_callgraph_conformance": False,
            "target_kernel_runtime_conformance": False,
            "terminal_causal_witness_authenticated": False,
            "terminal_attempt_projection_present": observed["attempt_binding"]["present"],
            "terminal_markers_bound": observed["attempt_binding"]["terminal_markers_bound"],
            "terminal_rows_missing": observed["attempt_binding"]["case_count"],
        },
        "native_integrity": native_projection,
        "t1_execution_chain": _verification_plan(case_ids, q_by_case),
        "verification": {
            "dependency_count": len(dependency_output),
            "dependency_digests_recomputed": True,
            "reviewed_source_digests_rechecked": True,
            "frozen_denominator_rechecked": True,
            "case_count": len(case_ids),
            "native_gate_count": native_registry.GATE_COUNT,
            "native_cell_count": native_registry.CASE_COUNT * native_registry.GATE_COUNT,
            "terminal_rows_bound": observed["matrix_binding"]["rows_bound"],
            "terminal_rows_with_markers": 0,
            "static_consistency_passed": True,
            "runtime_verification_passed": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        },
        "read_policy": dict(READ_POLICY),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "mutations": dict(MUTATIONS),
        "side_effects": dict(SIDE_EFFECTS),
    }


def validate_report(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(type(value) is dict, "bridge report must be a builtin object")
    expected_top = {
        "admission", "authorization", "blockers", "dependencies", "native_integrity",
        "prohibited_operations", "mutations", "read_policy", "record_id", "runtime_and_terminal",
        "schema", "scope_id", "side_effects", "source_contracts", "status", "t1_execution_chain",
        "target_kernel", "verification",
    }
    _require(set(value) == expected_top, "bridge report fields differ")
    _require(value["schema"] == REPORT_SCHEMA and value["record_id"] == REPORT_RECORD_ID, "bridge report identity drift")
    _require(value["scope_id"] == SCOPE_ID and value["status"] == STATUS, "bridge report scope/status drift")
    _require(value["authorization"] == AUTHORIZATION, "bridge authorization boundary drift", code="authorization_drift")
    _require(value["mutations"] == MUTATIONS and value["side_effects"] == SIDE_EFFECTS, "bridge mutation boundary drift")
    _require(value["prohibited_operations"] == PROHIBITED_OPERATIONS, "bridge prohibited-operation boundary drift")
    _require(value["read_policy"] == READ_POLICY, "bridge read-policy boundary drift")
    _require(type(value["dependencies"]) is dict and len(value["dependencies"]) == len(DEPENDENCY_SPECS), "bridge dependency inventory drift")
    for key, spec in DEPENDENCY_SPECS.items():
        ref = value["dependencies"].get(key)
        _require(type(ref) is dict, f"bridge dependency is missing: {key}")
        _require(ref.get("path") == spec["path"], f"bridge dependency path drift: {key}")
        _sha256(ref.get("sha256"), f"bridge dependency digest: {key}")
        _require(type(ref.get("bytes")) is int and ref["bytes"] > 0, f"bridge dependency byte count: {key}")
        _require(ref.get("schema") == spec["schema"] and ref.get("record_id") == spec["record_id"], f"bridge dependency identity drift: {key}")
        _require(ref.get("status") == spec["status"], f"bridge dependency status drift: {key}")
    source_contracts = value["source_contracts"]
    _require(type(source_contracts) is dict and source_contracts.get("target_source_tree_proven") is False and source_contracts.get("runtime_loaded_identity_proven") is False,
             "source contract boundary drift", code="authorization_drift")
    native = value["native_integrity"]
    _require(type(native) is dict and native.get("case_count") == native_registry.CASE_COUNT and native.get("gate_count") == native_registry.GATE_COUNT,
             "native registry denominator drift", code="denominator_drift")
    _require(native.get("denominator_cells") == 120 and native.get("native_integrity_evaluated") is False and native.get("qualification_credit") == 0,
             "native integrity boundary drift", code="authorization_drift")
    plan = value["t1_execution_chain"]
    _require(type(plan) is dict and plan.get("case_count") == 15 and tuple(plan.get("case_ids", ())) == native_registry.EXPECTED_QUALIFICATION_CASE_IDS,
             "T1 case denominator drift", code="denominator_drift")
    _require(plan.get("T1_numerical") is False and plan.get("qualification_credit") == 0, "T1 plan boundary drift", code="authorization_drift")
    rows = plan.get("rows")
    _require(type(rows) is list and len(rows) == 15 and tuple(row.get("case_id") for row in rows) == native_registry.EXPECTED_QUALIFICATION_CASE_IDS,
             "T1 verification rows drift", code="denominator_drift")
    _require(value["verification"].get("static_consistency_passed") is True and value["verification"].get("runtime_verification_passed") is False,
             "bridge verification boundary drift")
    _require(all(item.get("severity") == "high" for item in value["blockers"]), "bridge blockers lost severity")
    return dict(value)


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    value, _reference = _read_json(path, label="bridge report")
    validate_report(value)
    expected = build_report()
    _require(value == expected, "checked-in bridge report differs from current bounded evidence", code="report_digest_drift")
    return value


def _write_immutable(path: Path, payload: bytes) -> None:
    target = _canonical_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.fspath(target), flags, 0o644)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
    finally:
        os.close(descriptor)


def _zh_report(value: Mapping[str, Any]) -> str:
    blockers = "\n".join(
        f"- `{item['code']}`：{item['detail']}"
        for item in value["blockers"]
    )
    return f"""# F8/R008 admission/verification bridge V1

状态：`{value['status']}`。

本 bridge 只把既有 bounded static evidence 串成下一步 admission/terminal verification projection；不授予执行权限，不判定 T1，不写 registry、ledger、gate、completion 或 PLAN。

## 已绑定的静态链

- target-kernel evidence intake、local inventory、readiness v8 与 target-kernel readiness projection；
- trusted authority/worker/runtime identity、handoff、post-run contract；
- safe BI4 review、native-table/metric review、15-case metric-matrix review；
- 固定 R008 15-case matrix 与 native-integrity 15×8（120 cells）registry。

source contract 仅证明仓库内 reviewed implementation bytes 当前一致；target source tree/commit、loaded runtime identity、target-kernel ABI/runtime conformance 仍未证明。

## 当前真实 blocker

{blockers}

## 明确的下一步

`t1_execution_chain` 为每个 case 固定 B → C → D → terminal → T1 adjudication 顺序。当前 15/15 case 的 B、C、D 未验证，terminal marker 全部缺失，120 个 native-integrity cells 只有 registry 定义而没有 evidence binding。

因此本报告保持 `readiness_pass=false`、`T1_numerical=false`、`qualification_credit=0`，且所有 mutation/执行副作用均为零。后续若获得独立授权，必须先取得 target/source/runtime/native/terminal receipts，再重新运行本 bridge；GPU 显存可用并不替代这些身份与完整性证据。

机器报告：[F8-R008-ADMISSION-VERIFICATION-BRIDGE-V1-2026-09-28.json](F8-R008-ADMISSION-VERIFICATION-BRIDGE-V1-2026-09-28.json)。
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    args = parser.parse_args(argv)
    value = build_report()
    validate_report(value)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_immutable(args.output, payload)
    _write_immutable(args.zh_output, _zh_report(value).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
