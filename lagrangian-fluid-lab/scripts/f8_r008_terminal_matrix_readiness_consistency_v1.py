#!/usr/bin/env python3
"""Bind the F8/R008 terminal matrix to readiness and trusted-runtime projections.

This is a bounded, non-authorizing consistency bridge.  It consumes only the
small JSON reports produced by the terminal-matrix intake, target-kernel
readiness projection, trusted identity/handoff contracts, and (when present)
the JSON-only attempt-evidence binding.  It never follows a referenced
Definition, BI4, HDF5, solver-frame, kernel, native, worker, GPU, queue, or
ledger path.

The bridge deliberately keeps two different claims separate:

* static scope/readiness/identity/handoff contracts can be mutually bound; and
* per-case attempt, nonce, and terminal markers still need a bounded attempt
  projection.  Missing or drifting markers fail closed and cannot become
  solver completion, readiness, T1, formal admission, or credit.

The default repository state has no checked-in attempt-evidence projection.
Consequently ``build_report()`` returns a deterministic blocked report with
the complete 15-row denominator, diagnostic-only flags, zero credit, and zero
mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TERMINAL_MATRIX = Path(
    "reports/F8-R008-TERMINAL-EVIDENCE-MATRIX-INTAKE-V1-2026-09-28.json"
)
DEFAULT_TARGET_READINESS = Path(
    "reports/F8-R008-TARGET-KERNEL-READINESS-PROJECTION-V1-2026-09-28.json"
)
DEFAULT_TRUSTED_IDENTITY = Path(
    "reports/F8-R008-TRUSTED-AUTHORITY-WORKER-RUNTIME-IDENTITY-CONTRACT-V1.json"
)
DEFAULT_TRUSTED_HANDOFF = Path(
    "reports/F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-CONTRACT-V1.json"
)
DEFAULT_TRUSTED_POSTRUN = Path(
    "reports/F8-R008-TRUSTED-WORKER-RUNTIME-POSTRUN-MATRIX-CLAIM-ADAPTER-V1.json"
)
DEFAULT_ATTEMPT_EVIDENCE = Path(
    "reports/F8-R008-ATTEMPT-EVIDENCE-BINDING-V1.json"
)
DEFAULT_REPORT = Path(
    "reports/F8-R008-TERMINAL-MATRIX-READINESS-CONSISTENCY-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F8-R008-TERMINAL-MATRIX-READINESS-CONSISTENCY-V1-2026-09-28.zh-CN.md"
)

REPORT_SCHEMA = "core.cfd.f8.r008_terminal_matrix_readiness_consistency_report.v1"
REPORT_RECORD_ID = "f8-r008-terminal-matrix-readiness-consistency-v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"

MATRIX_SCHEMA = "core.cfd.f8.r008_terminal_evidence_matrix_intake_report.v1"
MATRIX_RECORD_ID = "f8-r008-terminal-evidence-matrix-intake-v1"
MATRIX_STATUS = "diagnostic_only_terminal_evidence_matrix_blocked"
READINESS_SCHEMA = "core.cfd.f8.r008.target_kernel_readiness_projection_report.v1"
READINESS_RECORD_ID = "f8-r008-target-kernel-readiness-projection-v1"
READINESS_STATUS = "diagnostic_only_target_kernel_readiness_blocked"
IDENTITY_SCHEMA = "core.cfd.f8.r008_trusted_identity_contract_report.v1"
IDENTITY_RECORD_ID = "f8-r008-trusted-identity-contract-report-v1"
IDENTITY_STATUS = "synthetic_only_non_authorizing_contract_design"
HANDOFF_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_handoff_report.v1"
HANDOFF_CONTRACT_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_handoff_contract.v1"
HANDOFF_RECORD_ID = "f8-r008-trusted-worker-runtime-handoff-report-v1"
HANDOFF_STATUS = "synthetic_only_non_authorizing_handoff_contract_design"
POSTRUN_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_postrun_matrix_claim_report.v1"
POSTRUN_CONTRACT_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_postrun_matrix_claim_adapter.v1"
POSTRUN_RECORD_ID = "f8-r008-trusted-worker-runtime-postrun-matrix-claim-report-v1"
POSTRUN_STATUS = "synthetic_only_non_authorizing_postrun_matrix_claim_binding_design"
ATTEMPT_SCHEMA = "core.cfd.f8.r008_attempt_evidence_binding.v1"

STATUS_BLOCKED = "diagnostic_only_terminal_matrix_readiness_consistency_blocked"
STATUS_STATIC = "diagnostic_only_terminal_matrix_readiness_consistent_non_authorizing"

MAX_JSON_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
NONCE_RE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)

CASE_IDS = (
    "space-q0-dp0p0090", "space-q0-dp0p0075", "space-q0-dp0p0060",
    "space-q0p5-dp0p0090", "space-q0p5-dp0p0075", "space-q0p5-dp0p0060",
    "space-q1-dp0p0090", "space-q1-dp0p0075", "space-q1-dp0p0060",
    "internal-q0p25-dp0p0075", "internal-q0p25-dp0p0060",
    "internal-q0p75-dp0p0075", "internal-q0p75-dp0p0060",
    "time-q0p5-dp0p0075-cfl0p1", "cadence-q0p5-dp0p0075-output128",
)
Q_VALUES = (
    0.0, 0.0, 0.0, 0.5, 0.5, 0.5, 1.0, 1.0, 1.0,
    0.25, 0.25, 0.75, 0.75, 0.5, 0.5,
)
Q_BY_CASE = dict(zip(CASE_IDS, Q_VALUES))

MATRIX_TOP_FIELDS = frozenset({
    "authorization", "dependencies", "matrix_contract", "mutations",
    "prohibited_operations", "read_policy", "record_id", "rows", "schema",
    "schema_bindings", "scope_id", "status", "summary",
    "terminal_evidence_input",
})
MATRIX_ROW_FIELDS = frozenset({
    "B", "C", "D", "T1_numerical", "abi_pins", "case_id",
    "claim_input_origin", "claimed_terminal_status", "formal", "frozen_row",
    "input_refs", "kind", "metric", "provenance", "q", "qualification_credit",
    "readiness_pass", "runtime_pins", "solver_completion_verified", "source_pins",
    "target_pins", "terminal_status",
})
FROZEN_ROW_FIELDS = frozenset({
    "alpha", "case_id", "cflnumber", "compare_to", "control_amplitude_m_s2",
    "control_samples_per_period", "dp_m", "expected_observation_output_count",
    "kind", "native_output_dt_s", "native_output_samples_per_period",
    "observation_cycles", "observation_end_output_index", "observation_end_s",
    "observation_start_output_index", "observation_start_s", "omega_rad_s",
    "period_s", "q", "qualification_only",
})
MARKER_FIELDS = frozenset({
    "manifest_schema", "manifest_sha256", "provenance_bound", "receipt_schema",
    "receipt_sha256", "status", "trusted",
})
PIN_GROUP_FIELDS = frozenset({"bound", "trusted", "claims"})

READINESS_TOP_FIELDS = frozenset({
    "authorization", "blocking_gaps", "causal_witness", "inputs", "record_id",
    "schema", "scope_id", "side_effects", "status", "target_kernel",
    "trusted_runtime", "validation",
})
IDENTITY_TOP_FIELDS = frozenset({
    "constraints", "contract_schema", "input_boundary", "integration_boundary",
    "non_authorizing_boundary", "prohibited_operations", "record_id", "schema",
    "scope_id", "status", "verified_chain",
})
HANDOFF_TOP_FIELDS = frozenset({
    "contract_schema", "fail_closed_constraints", "handoff_bindings",
    "input_boundary", "integration_boundary", "non_authorizing_boundary",
    "prohibited_operations", "record_id", "schema", "scope_id", "status",
})
POSTRUN_TOP_FIELDS = frozenset({
    "case_claim_requirements", "case_claim_schema", "contract_schema",
    "delegated_verifiers", "matrix_contract", "matrix_rejection_rules",
    "non_authorizing_boundary", "prohibited_operations", "record_id", "schema",
    "scope_id", "status",
})

ATTEMPT_TOP_FIELDS = frozenset({
    "all_non_null_refs_bound_to_supplied_raw_bytes",
    "all_stage_status_claims_have_receipt_or_not_run",
    "artifact_producer_authenticated", "attempt_count", "attempt_ledger_complete",
    "attempt_ledger_raw_sha256", "attempt_ledger_ref", "attempt_outcomes_resolved",
    "case_count", "case_rows", "c_v5_process_journal_check_count",
    "c_v5_process_journal_nonce_bindings_match_ledger", "descriptor_root_authenticated",
    "qualification_adjudicated", "qualification_credit",
    "qualification_matrix_raw_sha256", "raw_object_bytes", "raw_object_count",
    "raw_reference_count", "referenced_stage_receipt_status_claims_match_projection",
    "schema", "scope_id", "stage_bundle_semantics_verified",
    "stage_receipt_status_binding_count", "stage_receipt_status_bindings",
    "process_journal_semantics_verified", "T1_numerical",
    "unbound_non_not_run_stage_status_count",
})
ATTEMPT_CASE_FIELDS = frozenset({
    "attempts", "case_id", "case_outcome", "qualification_row_sha256",
    "qualifying_attempt_id",
})
ATTEMPT_FIELDS = frozenset({
    "actual_frame_ordinals", "actual_time_axis_ieee754_hex", "attempt_id",
    "attempt_ledger_event_seqs", "attempt_ledger_registration_seq", "attempt_outcome",
    "case_id", "definition_control_raw_bindings_verified",
    "expected_frame_count", "failure_class", "failure_position",
    "gencase_execution_semantics_verified", "loaded_module_code_identity_verified",
    "materialization_binary_semantics_verified", "native_table_content_matches_C_raw_frames",
    "nonce_hex", "qualification_adjudicated", "qualification_credit",
    "qualification_row_sha256", "schema", "scope_id", "solver_execution_semantics_verified",
    "stage_bundle_refs", "stage_receipt_statuses", "T1_numerical",
})

ZERO_MUTATIONS = {
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "registry_mutation": 0,
}
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
READ_POLICY = {
    "bounded_canonical_json_only": True,
    "small_file_metadata_only": True,
    "production_bi4_hdf5_read": False,
    "solver_frame_read": False,
    "privileged_probe": False,
    "fanotify_or_kernel_probe": False,
    "native_or_solver": False,
    "worker_gpu_or_queue": False,
    "registry_ledger_gate_write": False,
}
PROHIBITED_OPERATIONS = [
    "production_bi4_hdf5_or_solver_frame_read",
    "privileged_probe",
    "fanotify_or_kernel_probe",
    "native_or_solver",
    "worker_gpu_or_queue",
    "registry_ledger_gate_mutation",
]

IDENTITY_CHAIN = [
    "explicit_trust_root_to_active_key",
    "active_key_to_authority_worker_runtime_assertion",
    "authority_to_worker_parent_binding",
    "worker_to_runtime_parent_binding",
    "worker_and_runtime_host_identity_binding",
    "worker_and_runtime_code_identity_binding",
]
HANDOFF_BINDINGS = [
    "explicit_identity_bundle_sha256_and_active_key_id",
    "authority_binding_to_worker_and_runtime_subject",
    "synthetic_scope_attempt_case_nonce_and_bounded_epoch_window",
    "worker_and_runtime_code_identity_claims",
    "source_and_runtime_manifest_hash_claims",
    "definition_control_initial_state_and_configuration_hashes",
    "declared_output_manifest_schema_and_artifact_names",
    "active_key_signature_over_the_exact_handoff_payload",
]
READINESS_GAPS = [
    "external_target_evidence_missing",
    "target_kernel_identity_pins_incomplete",
    "causal_witness_static_only_untrusted",
    "untrusted_authority_runtime_identity",
    "target_abi_conformance_missing",
    "source_callgraph_conformance_missing",
    "target_kernel_runtime_conformance_missing",
]

IDENTITY_BOUNDARY = {
    "T1_numerical": False,
    "capability_minted": False,
    "diagnostic_only": True,
    "execution_authority": False,
    "formal_admission": False,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "qualification_credit": 0,
    "readiness_pass": False,
    "registry_mutation": 0,
}
HANDOFF_BOUNDARY = {
    "T1_numerical": False,
    "capability_minted": False,
    "denominator_mutation": 0,
    "diagnostic_only": True,
    "execution_authority": False,
    "formal_admission": False,
    "formal_eligible": False,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "qualification_credit": 0,
    "readiness_pass": False,
    "registry_mutation": 0,
}
POSTRUN_BOUNDARY = {
    "T1_numerical": False,
    "capability_minted": False,
    "diagnostic_only": True,
    "execution_authority": False,
    "formal": False,
    "formal_eligible": False,
    "gate_mutation": 0,
    "qualification_credit": 0,
    "readiness_pass": False,
    "real_ledger_mutation": 0,
    "registry_mutation": 0,
}

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class TerminalMatrixReadinessConsistencyError(ValueError):
    """A bounded input or consistency report violates this contract."""

    def __init__(self, message: str, *, code: str = "invalid_input") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, *, code: str = "invalid_input") -> None:
    raise TerminalMatrixReadinessConsistencyError(message, code=code)


def canonical_json_bytes(value: Any, *, label: str = "value") -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError, RecursionError) as error:
        raise TerminalMatrixReadinessConsistencyError(
            f"{label} is not canonical JSON serializable", code="non_canonical_json"
        ) from error


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(value: Any, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} is not a lowercase SHA-256", code="digest_drift")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}", code="duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    _fail(f"non-standard JSON constant is not permitted: {token}", code="non_strict_json")


def _canonical_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        if path.as_posix() != str(path) or any(part in {"", ".", ".."} for part in path.parts):
            _fail(f"input path is not canonical: {value}", code="path_traversal")
        return path
    if path.as_posix() != str(path) or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        _fail(f"input path is not canonical: {value}", code="path_traversal")
    return LAB_ROOT / path


def _display_path(path: Path) -> str:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        return absolute.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return absolute.as_posix()


def _assert_no_symlink_components(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise TerminalMatrixReadinessConsistencyError(
                f"could not inspect input path: {path}", code="path_inspection"
            ) from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"input path contains a symlink: {path}", code="symlink_path")


def _read_bounded_json(
    value: str | Path,
    *,
    label: str,
    optional: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    target = _canonical_path(value)
    _assert_no_symlink_components(target)
    display = _display_path(target)
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(target), os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    except FileNotFoundError as error:
        if optional:
            return None, {
                "path": display, "present": False, "bytes": None, "sha256": None,
                "schema": None, "record_id": None, "scope_id": None, "status": "missing",
            }
        _fail(f"{label} is missing: {display}", code="missing_input")
        raise AssertionError from error
    except OSError as error:
        _fail(f"{label} cannot be opened safely: {display}", code="input_open")
        raise AssertionError from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{label} must be a regular file", code="not_regular_file")
        if before.st_nlink != 1:
            _fail(f"{label} must have exactly one hard link", code="hardlink")
        if before.st_size > MAX_JSON_BYTES:
            _fail(f"{label} exceeds the bounded JSON limit", code="oversize")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, MAX_JSON_BYTES + 1 - total))
            if not block:
                break
            total += len(block)
            if total > MAX_JSON_BYTES:
                _fail(f"{label} exceeds the bounded JSON limit", code="oversize")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(target, follow_symlinks=False)
        identity = lambda item: (
            item.st_dev, item.st_ino, item.st_mode, item.st_size,
            item.st_mtime_ns, item.st_ctime_ns, item.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or total != before.st_size:
            _fail(f"{label} changed while being read", code="input_drift")
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TerminalMatrixReadinessConsistencyError(
            f"{label} is not strict JSON", code="invalid_json"
        ) from error
    if type(parsed) is not dict:
        _fail(f"{label} root must be an object", code="object_required")
    ref = {
        "path": display,
        "present": True,
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "schema": parsed.get("schema", parsed.get("contract_schema")),
        "record_id": parsed.get("record_id"),
        "scope_id": parsed.get("scope_id"),
        "status": parsed.get("status"),
    }
    return parsed, ref


def _exact(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(expected):
        _fail(f"{label} fields are not exact", code="fields_drift")
    return value


def _bool(value: Any, label: str) -> None:
    if type(value) is not bool:
        _fail(f"{label} must be a builtin boolean", code="type_drift")


def _nonempty_string(value: Any, label: str) -> None:
    if type(value) is not str or not value:
        _fail(f"{label} must be a non-empty string", code="type_drift")


def _identifier(value: Any, label: str) -> None:
    if type(value) is not str or IDENTIFIER_RE.fullmatch(value) is None:
        _fail(f"{label} is not a bounded identifier", code="marker_drift")


def _metadata_ref(value: Any, label: str) -> None:
    row = _exact(value, frozenset({"bytes", "path", "sha256"}), label)
    _nonempty_string(row["path"], f"{label}.path")
    if type(row["bytes"]) is not int or row["bytes"] <= 0:
        _fail(f"{label}.bytes is malformed", code="metadata_drift")
    _sha256_text(row["sha256"], f"{label}.sha256")


def _dependency_ref(value: Any, label: str) -> None:
    row = _exact(
        value,
        frozenset({"bytes", "path", "record_id", "schema", "scope_id", "sha256", "status"}),
        label,
    )
    _metadata_ref({key: row[key] for key in ("bytes", "path", "sha256")}, label)
    _nonempty_string(row["schema"], f"{label}.schema")
    if row["record_id"] is not None:
        _nonempty_string(row["record_id"], f"{label}.record_id")
    if row["scope_id"] is not None and row["scope_id"] != SCOPE_ID:
        _fail(f"{label}.scope_id drifted", code="scope_drift")
    _nonempty_string(row["status"], f"{label}.status")


def _same_ref(value: Mapping[str, Any], observed: Mapping[str, Any], label: str) -> None:
    _dependency_ref(value, label)
    for key in ("bytes", "sha256", "schema", "record_id", "scope_id", "status"):
        if value[key] != observed[key]:
            _fail(f"{label}.{key} differs from the loaded bounded projection", code="dependency_drift")


def _validate_matrix(value: Any) -> dict[str, Any]:
    report = _exact(value, MATRIX_TOP_FIELDS, "terminal matrix report")
    if report["schema"] != MATRIX_SCHEMA or report["record_id"] != MATRIX_RECORD_ID or report["status"] != MATRIX_STATUS:
        _fail("terminal matrix report identity drifted", code="matrix_identity_drift")
    if report["scope_id"] != SCOPE_ID:
        _fail("terminal matrix scope drifted", code="scope_drift")

    contract = _exact(
        report["matrix_contract"],
        frozenset({"case_count", "case_ids", "definition_control_pack_ref", "exact_15_rows", "parameter_contract_ref", "q_values_by_case", "scope_ref"}),
        "terminal matrix contract",
    )
    if contract["case_count"] != 15 or contract["exact_15_rows"] is not True:
        _fail("terminal matrix denominator is not exactly 15", code="matrix_scope_drift")
    if contract["case_ids"] != list(CASE_IDS) or set(contract["q_values_by_case"]) != set(CASE_IDS):
        _fail("terminal matrix case set drifted", code="matrix_scope_drift")
    for case_id, expected_q in Q_BY_CASE.items():
        if contract["q_values_by_case"][case_id] != expected_q:
            _fail(f"terminal matrix q drifted for {case_id}", code="matrix_scope_drift")
    for name in ("scope_ref", "definition_control_pack_ref", "parameter_contract_ref"):
        _metadata_ref(contract[name], f"terminal matrix.{name}")

    dependencies = _exact(
        report["dependencies"],
        frozenset({
            "B_C_D_provenance_schema", "causal_witness", "target_readiness_projection",
            "trusted_handoff_contract", "trusted_identity_contract", "trusted_postrun_contract",
            "trusted_replay_contract",
        }),
        "terminal matrix dependencies",
    )
    for name, ref in dependencies.items():
        _dependency_ref(ref, f"terminal matrix.dependencies.{name}")

    rows = report["rows"]
    if type(rows) is not list or len(rows) != len(CASE_IDS):
        _fail("terminal matrix rows are not exactly 15", code="matrix_scope_drift")
    seen: set[str] = set()
    normalized_rows: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        item = _exact(row, MATRIX_ROW_FIELDS, f"terminal matrix row {index}")
        case_id = item["case_id"]
        if case_id not in CASE_IDS or case_id in seen:
            _fail(f"terminal matrix row identity drifted: {case_id}", code="matrix_row_drift")
        seen.add(case_id)
        if item["q"] != Q_BY_CASE[case_id] or item["kind"] != item["frozen_row"].get("kind"):
            _fail(f"terminal matrix row q/kind drifted: {case_id}", code="matrix_row_drift")
        frozen = _exact(item["frozen_row"], FROZEN_ROW_FIELDS, f"terminal matrix {case_id}.frozen_row")
        if frozen["case_id"] != case_id or frozen["q"] != Q_BY_CASE[case_id] or frozen["qualification_only"] is not True:
            _fail(f"terminal matrix frozen row drifted: {case_id}", code="matrix_row_drift")
        for stage in ("B", "C", "D"):
            marker = _exact(item[stage], MARKER_FIELDS, f"terminal matrix {case_id}.{stage}")
            if marker["status"] not in {"missing", "unresolved"} or marker["trusted"] is not False or marker["provenance_bound"] is not False:
                _fail(f"terminal matrix {case_id}.{stage} crossed its non-authorizing boundary", code="terminal_marker_drift")
            if marker["manifest_sha256"] is not None or marker["receipt_sha256"] is not None:
                _fail(f"terminal matrix {case_id}.{stage} contains an unbound digest", code="terminal_marker_drift")
        for name in ("source_pins", "runtime_pins", "abi_pins", "target_pins"):
            group = _exact(item[name], PIN_GROUP_FIELDS, f"terminal matrix {case_id}.{name}")
            _bool(group["bound"], f"{name}.bound")
            _bool(group["trusted"], f"{name}.trusted")
            if group["trusted"] or group["bound"]:
                _fail(f"terminal matrix {case_id}.{name} was promoted", code="terminal_marker_drift")
            if type(group["claims"]) is not dict:
                _fail(f"terminal matrix {case_id}.{name}.claims is malformed", code="terminal_marker_drift")
        for name in ("metric", "provenance"):
            section = item[name]
            expected_fields = (
                frozenset({"metric_result_sha256", "status", "t1_numerical", "trusted"})
                if name == "metric"
                else frozenset({"chain_closed", "source_identity_verified", "status", "trusted"})
            )
            section = _exact(section, expected_fields, f"terminal matrix {case_id}.{name}")
            if section.get("trusted") is not False:
                _fail(f"terminal matrix {case_id}.{name} crossed its boundary", code="terminal_marker_drift")
            if name == "metric" and section["t1_numerical"] is not False:
                _fail(f"terminal matrix {case_id}.metric crossed its boundary", code="terminal_marker_drift")
            if name == "provenance" and (section["chain_closed"] is not False or section["source_identity_verified"] is not False):
                _fail(f"terminal matrix {case_id}.provenance crossed its boundary", code="terminal_marker_drift")
        if item["terminal_status"] not in {"missing", "unresolved"}:
            _fail(f"terminal matrix terminal status drifted: {case_id}", code="terminal_marker_drift")
        if item["claimed_terminal_status"] is not None and item["claimed_terminal_status"] not in {"missing", "partial", "complete", "failed", "unresolved"}:
            _fail(f"terminal matrix claimed terminal marker is malformed: {case_id}", code="terminal_marker_drift")
        if item["solver_completion_verified"] is not False or item["readiness_pass"] is not False or item["T1_numerical"] is not False or item["formal"] is not False or item["qualification_credit"] != 0:
            _fail(f"terminal matrix authorization crossed its boundary: {case_id}", code="authorization_drift")
        normalized_rows[case_id] = item
    if seen != set(CASE_IDS):
        _fail("terminal matrix does not cover the exact frozen case set", code="matrix_scope_drift")

    authorization = _exact(
        report["authorization"],
        frozenset({"diagnostic_only", "readiness_pass", "T1_numerical", "formal", "qualification_credit", "execution_authority", "solver_completion_verified"}),
        "terminal matrix authorization",
    )
    expected_authorization = {
        "diagnostic_only": True,
        "readiness_pass": False,
        "T1_numerical": False,
        "formal": False,
        "qualification_credit": 0,
        "execution_authority": False,
        "solver_completion_verified": False,
    }
    if authorization != expected_authorization:
        _fail("terminal matrix authorization boundary was promoted", code="authorization_drift")
    if report["mutations"] != ZERO_MUTATIONS:
        _fail("terminal matrix mutations are non-zero", code="side_effect_drift")
    policy = report["read_policy"]
    expected_policy = {
        "bounded_json_only": True,
        "definition_control_content_read": False,
        "fanotify_kernel_native_solver_worker_gpu_queue": False,
        "privileged_probe": False,
        "production_bi4_hdf5_read": False,
        "small_file_metadata_only": True,
        "solver_frame_read": False,
    }
    if policy != expected_policy:
        _fail("terminal matrix read policy was promoted", code="read_policy_drift")
    summary = report["summary"]
    if type(summary) is not dict or set(summary) != {"T1_rows", "formal_rows", "missing_rows", "qualification_credit", "readiness_rows", "solver_completion_verified_rows", "unresolved_rows"} or summary.get("missing_rows", 0) + summary.get("unresolved_rows", 0) != 15 or summary.get("qualification_credit") != 0 or summary.get("solver_completion_verified_rows") != 0 or summary.get("readiness_rows") != 0 or summary.get("T1_rows") != 0 or summary.get("formal_rows") != 0:
        _fail("terminal matrix summary crossed its boundary", code="authorization_drift")
    schema_bindings = _exact(report["schema_bindings"], frozenset({"attempt_receipts_and_manifests", "metric_matrix_adapter", "provenance_contract"}), "terminal matrix schema bindings")
    if schema_bindings["metric_matrix_adapter"] != "core.cfd.f8.r008_t1_metric_matrix_adapter.v5" or schema_bindings["provenance_contract"] != "core.cfd.f8.r008_per_case_provenance_contract.v1":
        _fail("terminal matrix schema bindings drifted", code="matrix_scope_drift")
    _exact(schema_bindings["attempt_receipts_and_manifests"], frozenset({"B_manifest", "B_receipt", "C_manifest", "C_receipt", "D_frame_manifest", "D_manifest", "D_receipt", "metric_matrix", "native_table"}), "terminal matrix attempt schema bindings")
    terminal_input = _exact(report["terminal_evidence_input"], frozenset({"bytes", "path", "present", "sha256"}), "terminal matrix evidence input")
    if terminal_input != {"bytes": None, "path": None, "present": False, "sha256": None}:
        _fail("terminal matrix evidence input was unexpectedly promoted", code="terminal_marker_drift")
    return {"value": report, "dependencies": dependencies, "rows": normalized_rows}


def _validate_readiness(value: Any) -> dict[str, Any]:
    report = _exact(value, READINESS_TOP_FIELDS, "target/readiness projection")
    if report["schema"] != READINESS_SCHEMA or report["record_id"] != READINESS_RECORD_ID or report["scope_id"] != SCOPE_ID or report["status"] != READINESS_STATUS:
        _fail("target/readiness projection identity drifted", code="readiness_identity_drift")
    auth = _exact(
        report["authorization"],
        frozenset({"T1_numerical", "capability_minted", "diagnostic_only", "execution_authority", "formal_admission", "qualification_credit", "readiness_pass"}),
        "readiness authorization",
    )
    expected_auth = {
        "T1_numerical": False,
        "capability_minted": False,
        "diagnostic_only": True,
        "execution_authority": False,
        "formal_admission": False,
        "qualification_credit": 0,
        "readiness_pass": False,
    }
    if auth != expected_auth:
        _fail("readiness authorization crossed its boundary", code="authorization_drift")
    side = report["side_effects"]
    expected_side = {
        "completion_mutation": 0, "gate_mutation": 0, "gpu_started": False,
        "kernel_started": False, "ledger_mutation": 0, "native_started": False,
        "plan_mutation": 0, "privileged_probe_started": False, "queue_started": False,
        "registry_mutation": 0, "worker_started": False,
    }
    if side != expected_side:
        _fail("readiness side effects are non-zero", code="side_effect_drift")
    target = _exact(report["target_kernel"], frozenset({"all_pins_complete", "build_id", "config_sha256", "external_evidence_complete", "kernel_release", "pins", "source_commit", "source_tree_sha256", "uapi_sha256"}), "readiness target kernel")
    pins = _exact(target["pins"], frozenset({"build_id_pinned", "config_pinned", "kernel_release_pinned", "source_commit_pinned", "source_tree_pinned", "uapi_pinned"}), "readiness target pins")
    if any(pin is not False for pin in pins.values()) or target["all_pins_complete"] is not False or target["external_evidence_complete"] is not False:
        _fail("readiness target pins were promoted", code="readiness_drift")
    if any(target[key] is not None for key in ("build_id", "config_sha256", "kernel_release", "source_commit", "source_tree_sha256", "uapi_sha256")):
        _fail("readiness target identity contains unexpected evidence", code="readiness_drift")
    gaps = report["blocking_gaps"]
    if type(gaps) is not list or [item.get("code") for item in gaps] != READINESS_GAPS:
        _fail("readiness blocker inventory drifted", code="readiness_drift")
    if any(_exact(item, frozenset({"code", "detail", "severity"}), "readiness blocker") ["severity"] != "high" for item in gaps):
        _fail("readiness blocker severity drifted", code="readiness_drift")
    trusted = _exact(report["trusted_runtime"], frozenset({"execution_authority", "handoff_contract_report_sha256", "identity_contract_report_sha256", "production_authority_authenticated", "production_runtime_identity_authenticated", "runtime_measured"}), "readiness trusted runtime")
    for key in ("handoff_contract_report_sha256", "identity_contract_report_sha256"):
        _sha256_text(trusted[key], f"readiness trusted runtime.{key}")
    for key in ("execution_authority", "production_authority_authenticated", "production_runtime_identity_authenticated", "runtime_measured"):
        if trusted[key] is not False:
            _fail(f"readiness trusted runtime.{key} was promoted", code="authorization_drift")
    validation = _exact(report["validation"], frozenset({"blockers", "causal_witness_refs_bound", "external_target_evidence_complete", "intake_report_digest_bound", "intake_report_schema_valid", "r008_scope_bound", "readiness_v8_zero_credit_preserved", "source_callgraph_conformance", "target_abi_conformance", "target_kernel_pin_set_complete", "target_kernel_runtime_conformance", "trusted_authority_runtime_identity_verified"}), "readiness validation")
    if validation["blockers"] != READINESS_GAPS:
        _fail("readiness validation blockers drifted", code="readiness_drift")
    expected_true = {"causal_witness_refs_bound", "intake_report_digest_bound", "intake_report_schema_valid", "r008_scope_bound", "readiness_v8_zero_credit_preserved"}
    for key, item in validation.items():
        if key == "blockers":
            continue
        if item is not (key in expected_true):
            _fail(f"readiness validation.{key} drifted", code="readiness_drift")
    inputs = _exact(report["inputs"], frozenset({"causal_witness", "readiness_audit_v8", "target_kernel_evidence_intake", "trusted_identity_contract", "trusted_worker_runtime_handoff"}), "readiness inputs")
    for name, ref in inputs.items():
        _dependency_ref(ref, f"readiness.inputs.{name}")
    _sha256_text(report["causal_witness"]["report_sha256"], "readiness causal witness digest")
    if report["causal_witness"]["scope_id"] != SCOPE_ID or report["causal_witness"]["runtime_source_authenticated"] is not False or report["causal_witness"]["trusted_authority_present"] is not False or report["causal_witness"]["target_kernel_conformance"] is not False:
        _fail("readiness causal witness was promoted", code="readiness_drift")
    return {"value": report, "trusted_runtime": trusted, "inputs": inputs}


def _validate_identity(value: Any) -> dict[str, Any]:
    report = _exact(value, IDENTITY_TOP_FIELDS, "trusted identity contract")
    if report["schema"] != IDENTITY_SCHEMA or report["contract_schema"] != "core.cfd.f8.r008_trusted_authority_worker_runtime_identity_contract.v1" or report["record_id"] != IDENTITY_RECORD_ID or report["scope_id"] != SCOPE_ID or report["status"] != IDENTITY_STATUS:
        _fail("trusted identity contract identity drifted", code="identity_drift")
    if report["verified_chain"] != IDENTITY_CHAIN:
        _fail("trusted identity chain inventory drifted", code="identity_drift")
    boundary = _exact(report["non_authorizing_boundary"], frozenset(IDENTITY_BOUNDARY), "trusted identity boundary")
    if boundary != IDENTITY_BOUNDARY:
        _fail("trusted identity authorization boundary was promoted", code="authorization_drift")
    input_boundary = report["input_boundary"]
    if type(input_boundary) is not dict or input_boundary.get("synthetic_only") is not True or input_boundary.get("input_origin") != "synthetic_fixture" or input_boundary.get("default_trust_root") is not False:
        _fail("trusted identity input boundary drifted", code="identity_drift")
    return {"value": report}


def _validate_handoff(value: Any) -> dict[str, Any]:
    report = _exact(value, HANDOFF_TOP_FIELDS, "trusted handoff contract")
    if report["schema"] != HANDOFF_SCHEMA or report["contract_schema"] != HANDOFF_CONTRACT_SCHEMA or report["record_id"] != HANDOFF_RECORD_ID or report["scope_id"] != SCOPE_ID or report["status"] != HANDOFF_STATUS:
        _fail("trusted handoff contract identity drifted", code="handoff_drift")
    if report["handoff_bindings"] != HANDOFF_BINDINGS:
        _fail("trusted handoff binding inventory drifted", code="handoff_drift")
    boundary = _exact(report["non_authorizing_boundary"], frozenset(HANDOFF_BOUNDARY), "trusted handoff boundary")
    if boundary != HANDOFF_BOUNDARY:
        _fail("trusted handoff authorization boundary was promoted", code="authorization_drift")
    input_boundary = report["input_boundary"]
    if type(input_boundary) is not dict or input_boundary.get("synthetic_only") is not True or input_boundary.get("input_origin") != "synthetic_fixture" or input_boundary.get("production_paths_read") is not False or input_boundary.get("identity_contract_reused") is not True:
        _fail("trusted handoff input boundary drifted", code="handoff_drift")
    constraints = report["fail_closed_constraints"]
    if type(constraints) is not dict or constraints.get("production_identity") != "not_authenticated" or constraints.get("runtime") != "not_measured" or constraints.get("replay") != "single_use_claim_only_no_consumer":
        _fail("trusted handoff fail-closed boundary drifted", code="handoff_drift")
    return {"value": report}


def _validate_postrun(value: Any) -> dict[str, Any]:
    report = _exact(value, POSTRUN_TOP_FIELDS, "trusted postrun contract")
    if report["schema"] != POSTRUN_SCHEMA or report["contract_schema"] != POSTRUN_CONTRACT_SCHEMA or report["record_id"] != POSTRUN_RECORD_ID or report["scope_id"] != SCOPE_ID or report["status"] != POSTRUN_STATUS:
        _fail("trusted postrun contract identity drifted", code="postrun_drift")
    boundary = _exact(report["non_authorizing_boundary"], frozenset(POSTRUN_BOUNDARY), "trusted postrun boundary")
    if boundary != POSTRUN_BOUNDARY:
        _fail("trusted postrun authorization boundary was promoted", code="authorization_drift")
    matrix = _exact(report["matrix_contract"], frozenset({"case_count", "case_ids_source", "missing_or_extra_rows", "postrun_case_worker_called", "postrun_matrix_worker_called", "production_bundle_read", "required_input"}), "trusted postrun matrix contract")
    if matrix["case_count"] != 15 or matrix["missing_or_extra_rows"] != "reject" or matrix["postrun_case_worker_called"] is not False or matrix["postrun_matrix_worker_called"] is not False or matrix["production_bundle_read"] is not False:
        _fail("trusted postrun matrix contract drifted", code="postrun_drift")
    delegated = _exact(report["delegated_verifiers"], frozenset({"update_308", "update_309"}), "trusted postrun delegated verifiers")
    if delegated["update_308"].get("contract") != HANDOFF_CONTRACT_SCHEMA or delegated["update_309"].get("used_for") != "one in-memory synthetic replay transition per frozen case":
        _fail("trusted postrun delegated verifier drifted", code="postrun_drift")
    return {"value": report}


def _validate_attempt(value: Any) -> dict[str, Any]:
    report = _exact(value, ATTEMPT_TOP_FIELDS, "attempt evidence binding")
    if report["schema"] != ATTEMPT_SCHEMA or report["scope_id"] != SCOPE_ID or report["case_count"] != 15:
        _fail("attempt evidence binding identity drifted", code="attempt_drift")
    _sha256_text(report["qualification_matrix_raw_sha256"], "attempt matrix digest")
    _sha256_text(report["attempt_ledger_raw_sha256"], "attempt ledger digest")
    if type(report["case_rows"]) is not list or len(report["case_rows"]) != 15:
        _fail("attempt evidence case rows are not exactly 15", code="attempt_drift")
    seen: set[str] = set()
    attempts_by_case: dict[str, list[dict[str, Any]]] = {}
    seen_attempt_ids: set[str] = set()
    seen_nonces: set[str] = set()
    for index, row in enumerate(report["case_rows"]):
        item = _exact(row, ATTEMPT_CASE_FIELDS, f"attempt case row {index}")
        case_id = item["case_id"]
        if case_id not in CASE_IDS or case_id in seen:
            _fail(f"attempt case row identity drifted: {case_id}", code="attempt_drift")
        seen.add(case_id)
        if type(item["attempts"]) is not list or item["case_outcome"] != "unresolved" or item["qualifying_attempt_id"] is not None:
            _fail(f"attempt case outcome crossed its boundary: {case_id}", code="authorization_drift")
        _sha256_text(item["qualification_row_sha256"], f"attempt {case_id}.qualification_row_sha256")
        normalized_attempts: list[dict[str, Any]] = []
        for ordinal, attempt in enumerate(item["attempts"]):
            attempt_row = _exact(attempt, ATTEMPT_FIELDS, f"attempt {case_id}[{ordinal}]")
            if attempt_row["schema"] != "core.cfd.f8.r008_per_case_attempt_verification.v2" or attempt_row["scope_id"] != SCOPE_ID or attempt_row["case_id"] != case_id:
                _fail(f"attempt {case_id} identity drifted", code="attempt_drift")
            _identifier(attempt_row["attempt_id"], f"attempt {case_id}.attempt_id")
            if type(attempt_row["nonce_hex"]) is not str or NONCE_RE.fullmatch(attempt_row["nonce_hex"]) is None:
                _fail(f"attempt {case_id}.nonce_hex is malformed", code="attempt_marker_drift")
            if attempt_row["attempt_id"] in seen_attempt_ids or attempt_row["nonce_hex"] in seen_nonces:
                _fail(f"attempt ID/nonce is reused: {case_id}", code="attempt_marker_drift")
            seen_attempt_ids.add(attempt_row["attempt_id"])
            seen_nonces.add(attempt_row["nonce_hex"])
            if attempt_row["qualification_row_sha256"] != item["qualification_row_sha256"] or attempt_row["attempt_outcome"] != "unresolved" or attempt_row["failure_class"] != "unresolved_evidence" or attempt_row["failure_position"] is not None or attempt_row["qualification_adjudicated"] is not False or attempt_row["T1_numerical"] is not False or attempt_row["qualification_credit"] != 0:
                _fail(f"attempt {case_id} crossed its diagnostic boundary", code="authorization_drift")
            for field in ("definition_control_raw_bindings_verified", "materialization_binary_semantics_verified", "gencase_execution_semantics_verified", "solver_execution_semantics_verified", "native_table_content_matches_C_raw_frames", "loaded_module_code_identity_verified"):
                if attempt_row[field] is not False:
                    _fail(f"attempt {case_id}.{field} was promoted", code="attempt_drift")
            statuses = _exact(attempt_row["stage_receipt_statuses"], frozenset({"B", "C", "D"}), f"attempt {case_id}.stage_receipt_statuses")
            if any(status not in {"not_run", "passed", "failed", "incomplete", "timeout", "oom", "signaled"} for status in statuses.values()):
                _fail(f"attempt {case_id} stage status drifted", code="attempt_marker_drift")
            normalized_attempts.append(attempt_row)
        attempts_by_case[case_id] = normalized_attempts
    if seen != set(CASE_IDS):
        _fail("attempt evidence does not cover the exact case set", code="attempt_drift")
    if report["attempt_count"] != sum(len(items) for items in attempts_by_case.values()):
        _fail("attempt evidence attempt_count drifted", code="attempt_drift")
    for field in ("attempt_ledger_complete", "artifact_producer_authenticated", "descriptor_root_authenticated", "stage_bundle_semantics_verified", "process_journal_semantics_verified", "attempt_outcomes_resolved", "qualification_adjudicated", "T1_numerical"):
        if report[field] is not False:
            _fail(f"attempt evidence {field} was promoted", code="authorization_drift")
    if report["qualification_credit"] != 0:
        _fail("attempt evidence credit was promoted", code="authorization_drift")
    return {"value": report, "attempts_by_case": attempts_by_case}


def _input_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": value["path"], "present": value["present"], "bytes": value["bytes"],
        "sha256": value["sha256"], "schema": value["schema"],
        "record_id": value["record_id"], "scope_id": value["scope_id"],
        "status": value["status"],
    }


def _row_digest(row: Mapping[str, Any]) -> str:
    return _sha256(canonical_json_bytes(dict(row), label="terminal matrix row"))


def _attempt_marker_rows(
    matrix_rows: Mapping[str, Mapping[str, Any]],
    attempts: Mapping[str, list[Mapping[str, Any]]],
    *,
    attempt_present: bool,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for case_id in CASE_IDS:
        row = matrix_rows[case_id]
        attempt_rows = attempts.get(case_id, [])
        marker_rows = []
        for attempt in attempt_rows:
            marker_rows.append({
                "attempt_id": attempt["attempt_id"],
                "nonce_hex": attempt["nonce_hex"],
                # The UPDATE-333-style attempt binding intentionally does not
                # promote ledger terminal claims into this V2 result.  Keep
                # the absent marker explicit instead of inferring completion.
                "claimed_terminal_outcome": attempt.get("claimed_terminal_outcome"),
                "attempt_outcome": attempt["attempt_outcome"],
                "attempt_events_closed": attempt.get("attempt_events_closed", False),
                "process_terminals_closed": attempt.get("process_terminals_closed", False),
                "stage_receipt_statuses": dict(attempt["stage_receipt_statuses"]),
            })
        matrix_claim = row["claimed_terminal_status"]
        marker_status = "missing" if not marker_rows else "unresolved"
        matrix_claim_bound = (
            matrix_claim is not None and bool(marker_rows)
            and all(item["claimed_terminal_outcome"] in {None, matrix_claim} for item in marker_rows)
        )
        terminal_bound = bool(marker_rows) and all(
            item["claimed_terminal_outcome"] is not None and item["attempt_events_closed"] is True
            for item in marker_rows
        )
        result.append({
            "case_id": case_id,
            "matrix_row_sha256": _row_digest(row),
            "matrix_terminal_status": row["terminal_status"],
            "matrix_claimed_terminal_status": matrix_claim,
            "attempt_projection_present": attempt_present,
            "attempt_count": len(marker_rows),
            "attempt_markers": marker_rows,
            "attempt_nonce_markers_bound": bool(marker_rows),
            "terminal_markers_bound": terminal_bound,
            "matrix_claim_bound": matrix_claim_bound,
            "consistent": bool(marker_rows) and matrix_claim_bound and terminal_bound,
            "marker_status": marker_status,
        })
    return result


def _build_from_values(
    matrix: Mapping[str, Any], matrix_ref: Mapping[str, Any],
    readiness: Mapping[str, Any], readiness_ref: Mapping[str, Any],
    identity: Mapping[str, Any], identity_ref: Mapping[str, Any],
    handoff: Mapping[str, Any], handoff_ref: Mapping[str, Any],
    postrun: Mapping[str, Any], postrun_ref: Mapping[str, Any],
    attempt: Mapping[str, Any] | None, attempt_ref: Mapping[str, Any],
) -> dict[str, Any]:
    matrix_checked = _validate_matrix(matrix)
    readiness_checked = _validate_readiness(readiness)
    identity_checked = _validate_identity(identity)
    handoff_checked = _validate_handoff(handoff)
    postrun_checked = _validate_postrun(postrun)
    attempt_checked = _validate_attempt(attempt)["attempts_by_case"] if attempt is not None else {case_id: [] for case_id in CASE_IDS}

    dependencies = matrix_checked["dependencies"]
    for name, value, ref in (
        ("target_readiness_projection", readiness, readiness_ref),
        ("trusted_identity_contract", identity, identity_ref),
        ("trusted_handoff_contract", handoff, handoff_ref),
        ("trusted_postrun_contract", postrun, postrun_ref),
    ):
        _same_ref(dependencies[name], ref, f"terminal matrix.dependencies.{name}")
        expected_schema = value.get("schema", value.get("contract_schema"))
        if dependencies[name]["path"] != ref["path"] or dependencies[name]["schema"] != expected_schema or dependencies[name]["scope_id"] != SCOPE_ID:
            _fail(f"terminal matrix dependency {name} does not bind its projection", code="dependency_drift")

    readiness_trusted = readiness_checked["trusted_runtime"]
    if readiness_trusted["identity_contract_report_sha256"] != identity_ref["sha256"] or readiness_trusted["handoff_contract_report_sha256"] != handoff_ref["sha256"]:
        _fail("readiness trusted identity/handoff digests drifted", code="cross_binding_drift")
    readiness_inputs = readiness_checked["inputs"]
    for name, ref in (("trusted_identity_contract", identity_ref), ("trusted_worker_runtime_handoff", handoff_ref)):
        if readiness_inputs[name]["path"] != ref["path"] or readiness_inputs[name]["sha256"] != ref["sha256"] or readiness_inputs[name]["bytes"] != ref["bytes"]:
            _fail(f"readiness input {name} differs from the loaded projection", code="cross_binding_drift")
    if postrun["matrix_contract"]["case_count"] != 15:
        _fail("postrun matrix denominator differs from terminal matrix", code="cross_binding_drift")
    if matrix_ref["scope_id"] != SCOPE_ID or readiness_ref["scope_id"] != SCOPE_ID or identity_ref["scope_id"] != SCOPE_ID or handoff_ref["scope_id"] != SCOPE_ID or postrun_ref["scope_id"] != SCOPE_ID:
        _fail("one or more F8 projections are outside R008", code="scope_drift")

    marker_rows = _attempt_marker_rows(
        matrix_checked["rows"], attempt_checked,
        attempt_present=attempt is not None,
    )
    marker_bound = bool(attempt is not None and all(item["attempt_nonce_markers_bound"] for item in marker_rows))
    terminal_bound = bool(attempt is not None and all(item["terminal_markers_bound"] for item in marker_rows))
    row_consistent = bool(attempt is not None and all(item["consistent"] for item in marker_rows))
    blockers: list[str] = []
    if attempt is None:
        blockers.extend(["attempt_evidence_missing", "attempt_nonce_markers_missing", "terminal_markers_missing"])
    else:
        if not marker_bound:
            blockers.append("attempt_nonce_markers_missing")
        if not terminal_bound:
            blockers.append("terminal_markers_unresolved")
        if not row_consistent:
            blockers.append("matrix_attempt_terminal_cross_binding_incomplete")

    static_bindings = {
        "r008_scope_bound": True,
        "matrix_15_case_scope_bound": True,
        "matrix_rows_exact_and_unique": True,
        "target_readiness_projection_bound": True,
        "trusted_issuer_worker_runtime_contract_bound": True,
        "trusted_handoff_matrix_contract_bound": True,
        "diagnostic_zero_credit_flags_consistent": True,
        "attempt_nonce_terminal_markers_bound": marker_bound,
        "terminal_matrix_rows_consistent_with_attempts": row_consistent,
    }
    binding_core = {
        "scope_id": SCOPE_ID,
        "matrix_report_sha256": matrix_ref["sha256"],
        "target_readiness_report_sha256": readiness_ref["sha256"],
        "trusted_identity_report_sha256": identity_ref["sha256"],
        "trusted_handoff_report_sha256": handoff_ref["sha256"],
        "trusted_postrun_report_sha256": postrun_ref["sha256"],
        "attempt_evidence_report_sha256": attempt_ref["sha256"] if attempt is not None else None,
        "case_ids": list(CASE_IDS),
        "static_bindings": static_bindings,
        "blockers": blockers,
    }
    cross_binding = {
        **binding_core,
        "consistent": not blockers,
    }
    cross_binding["binding_sha256"] = _sha256(
        canonical_json_bytes(cross_binding, label="cross-binding projection")
    )
    report = {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": STATUS_BLOCKED if blockers else STATUS_STATIC,
        "scope_id": SCOPE_ID,
        "input_refs": {
            "terminal_matrix": _input_descriptor(matrix_ref),
            "target_readiness": _input_descriptor(readiness_ref),
            "trusted_identity": _input_descriptor(identity_ref),
            "trusted_handoff": _input_descriptor(handoff_ref),
            "trusted_postrun": _input_descriptor(postrun_ref),
            "attempt_evidence": _input_descriptor(attempt_ref),
        },
        "matrix_binding": {
            "case_count": 15,
            "case_ids": list(CASE_IDS),
            "q_values_by_case": dict(Q_BY_CASE),
            "rows_bound": len(marker_rows),
            "rows_exact_and_unique": True,
            "matrix_terminal_status_counts": {
                status: sum(row["matrix_terminal_status"] == status for row in marker_rows)
                for status in ("missing", "unresolved")
            },
        },
        "target_readiness_binding": {
            "scope_bound": True,
            "projection_status": readiness["status"],
            "target_kernel_pins_complete": readiness["target_kernel"]["all_pins_complete"],
            "readiness_pass": readiness["authorization"]["readiness_pass"],
            "T1_numerical": readiness["authorization"]["T1_numerical"],
            "formal_admission": readiness["authorization"]["formal_admission"],
            "qualification_credit": readiness["authorization"]["qualification_credit"],
            "trusted_identity_digest_bound": readiness_trusted["identity_contract_report_sha256"] == identity_ref["sha256"],
            "trusted_handoff_digest_bound": readiness_trusted["handoff_contract_report_sha256"] == handoff_ref["sha256"],
        },
        "trusted_runtime_binding": {
            "identity_contract_schema": identity["contract_schema"],
            "identity_verified_chain": list(identity["verified_chain"]),
            "handoff_contract_schema": handoff["contract_schema"],
            "handoff_bindings": list(handoff["handoff_bindings"]),
            "postrun_contract_schema": postrun["contract_schema"],
            "issuer_worker_runtime_identity_bound": True,
            "production_identity_authenticated": False,
            "production_runtime_identity_authenticated": False,
            "runtime_measured": False,
            "execution_authority": False,
        },
        "attempt_terminal_binding": {
            "present": attempt is not None,
            "schema": attempt["schema"] if attempt is not None else None,
            "case_count": 15,
            "attempt_count": sum(item["attempt_count"] for item in marker_rows),
            "attempt_nonce_markers_bound": marker_bound,
            "terminal_markers_bound": terminal_bound,
            "rows_consistent": row_consistent,
            "rows": marker_rows,
        },
        "cross_binding": cross_binding,
        "authorization": dict(AUTHORIZATION),
        "mutations": dict(ZERO_MUTATIONS),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "read_policy": dict(READ_POLICY),
    }
    validate_report(report)
    return report


def build_report(
    *,
    terminal_matrix_path: str | Path = DEFAULT_TERMINAL_MATRIX,
    target_readiness_path: str | Path = DEFAULT_TARGET_READINESS,
    trusted_identity_path: str | Path = DEFAULT_TRUSTED_IDENTITY,
    trusted_handoff_path: str | Path = DEFAULT_TRUSTED_HANDOFF,
    trusted_postrun_path: str | Path = DEFAULT_TRUSTED_POSTRUN,
    attempt_evidence_path: str | Path | None = DEFAULT_ATTEMPT_EVIDENCE,
) -> dict[str, Any]:
    """Recompute the bounded consistency report from JSON projections only."""
    matrix, matrix_ref = _read_bounded_json(terminal_matrix_path, label="terminal matrix projection")
    readiness, readiness_ref = _read_bounded_json(target_readiness_path, label="target/readiness projection")
    identity, identity_ref = _read_bounded_json(trusted_identity_path, label="trusted identity projection")
    handoff, handoff_ref = _read_bounded_json(trusted_handoff_path, label="trusted handoff projection")
    postrun, postrun_ref = _read_bounded_json(trusted_postrun_path, label="trusted postrun projection")
    attempt: dict[str, Any] | None = None
    if attempt_evidence_path is not None:
        attempt, attempt_ref = _read_bounded_json(
            attempt_evidence_path,
            label="attempt evidence projection",
            optional=True,
        )
    else:
        attempt_ref = {
            "path": None, "present": False, "bytes": None, "sha256": None,
            "schema": None, "record_id": None, "scope_id": None, "status": "missing",
        }
    return _build_from_values(
        matrix or {}, matrix_ref,
        readiness or {}, readiness_ref,
        identity or {}, identity_ref,
        handoff or {}, handoff_ref,
        postrun or {}, postrun_ref,
        attempt, attempt_ref,
    )


def _validate_input_ref(value: Any, label: str, *, optional: bool) -> None:
    row = _exact(value, frozenset({"bytes", "path", "present", "record_id", "schema", "scope_id", "sha256", "status"}), label)
    _bool(row["present"], f"{label}.present")
    if row["present"]:
        _metadata_ref({key: row[key] for key in ("bytes", "path", "sha256")}, label)
        _nonempty_string(row["schema"], f"{label}.schema")
        _nonempty_string(row["status"], f"{label}.status")
        if row["scope_id"] not in {None, SCOPE_ID}:
            _fail(f"{label}.scope_id drifted", code="scope_drift")
    else:
        if not optional or any(row[key] is not None for key in ("bytes", "sha256", "schema", "record_id", "scope_id")) or row["status"] != "missing":
            _fail(f"{label} missing marker is malformed", code="input_ref_drift")
        if row["path"] is not None and type(row["path"]) is not str:
            _fail(f"{label}.path is malformed", code="input_ref_drift")


def validate_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a parsed report without touching any external artifact."""
    if type(value) is not dict:
        _fail("report root must be an object", code="invalid_report")
    expected = frozenset({
        "authorization", "attempt_terminal_binding", "cross_binding", "input_refs",
        "matrix_binding", "mutations", "prohibited_operations", "read_policy",
        "record_id", "schema", "scope_id", "status", "target_readiness_binding",
        "trusted_runtime_binding",
    })
    report = _exact(value, expected, "consistency report")
    if report["schema"] != REPORT_SCHEMA or report["record_id"] != REPORT_RECORD_ID or report["scope_id"] != SCOPE_ID or report["status"] not in {STATUS_BLOCKED, STATUS_STATIC}:
        _fail("consistency report identity drifted", code="report_identity_drift")
    if report["authorization"] != AUTHORIZATION or report["mutations"] != ZERO_MUTATIONS or report["prohibited_operations"] != PROHIBITED_OPERATIONS or report["read_policy"] != READ_POLICY:
        _fail("consistency report non-authorizing boundary drifted", code="authorization_drift")
    refs = _exact(report["input_refs"], frozenset({"attempt_evidence", "target_readiness", "terminal_matrix", "trusted_handoff", "trusted_identity", "trusted_postrun"}), "consistency input refs")
    for name in refs:
        _validate_input_ref(refs[name], f"consistency input_refs.{name}", optional=name == "attempt_evidence")
    matrix = _exact(report["matrix_binding"], frozenset({"case_count", "case_ids", "matrix_terminal_status_counts", "q_values_by_case", "rows_bound", "rows_exact_and_unique"}), "matrix binding")
    if matrix["case_count"] != 15 or matrix["case_ids"] != list(CASE_IDS) or matrix["q_values_by_case"] != Q_BY_CASE or matrix["rows_bound"] != 15 or matrix["rows_exact_and_unique"] is not True:
        _fail("consistency matrix binding drifted", code="matrix_scope_drift")
    if type(matrix["matrix_terminal_status_counts"]) is not dict or set(matrix["matrix_terminal_status_counts"]) != {"missing", "unresolved"}:
        _fail("consistency matrix status counts drifted", code="matrix_scope_drift")
    readiness = _exact(report["target_readiness_binding"], frozenset({"T1_numerical", "formal_admission", "projection_status", "qualification_credit", "readiness_pass", "scope_bound", "target_kernel_pins_complete", "trusted_handoff_digest_bound", "trusted_identity_digest_bound"}), "target readiness binding")
    if readiness["scope_bound"] is not True or readiness["projection_status"] != READINESS_STATUS or readiness["readiness_pass"] is not False or readiness["T1_numerical"] is not False or readiness["formal_admission"] is not False or readiness["qualification_credit"] != 0 or readiness["target_kernel_pins_complete"] is not False or readiness["trusted_identity_digest_bound"] is not True or readiness["trusted_handoff_digest_bound"] is not True:
        _fail("consistency readiness binding crossed its boundary", code="readiness_drift")
    trusted = _exact(report["trusted_runtime_binding"], frozenset({"execution_authority", "handoff_bindings", "handoff_contract_schema", "identity_contract_schema", "identity_verified_chain", "issuer_worker_runtime_identity_bound", "postrun_contract_schema", "production_identity_authenticated", "production_runtime_identity_authenticated", "runtime_measured"}), "trusted runtime binding")
    if trusted["identity_verified_chain"] != IDENTITY_CHAIN or trusted["handoff_bindings"] != HANDOFF_BINDINGS or trusted["issuer_worker_runtime_identity_bound"] is not True or any(trusted[key] is not False for key in ("production_identity_authenticated", "production_runtime_identity_authenticated", "runtime_measured", "execution_authority")):
        _fail("trusted runtime binding drifted", code="identity_drift")
    attempt = _exact(report["attempt_terminal_binding"], frozenset({"attempt_count", "attempt_nonce_markers_bound", "case_count", "present", "rows", "rows_consistent", "schema", "terminal_markers_bound"}), "attempt terminal binding")
    if attempt["case_count"] != 15 or type(attempt["rows"]) is not list or len(attempt["rows"]) != 15:
        _fail("attempt terminal matrix rows are not exactly 15", code="attempt_marker_drift")
    if attempt["present"] is False:
        if attempt["schema"] is not None or attempt["attempt_count"] != 0 or attempt["attempt_nonce_markers_bound"] is not False or attempt["terminal_markers_bound"] is not False or attempt["rows_consistent"] is not False:
            _fail("missing attempt projection was promoted", code="attempt_marker_drift")
    elif type(attempt["schema"]) is not str or attempt["schema"] != ATTEMPT_SCHEMA:
        _fail("attempt projection schema drifted", code="attempt_marker_drift")
    row_ids: set[str] = set()
    for index, row in enumerate(attempt["rows"]):
        item = _exact(row, frozenset({"attempt_count", "attempt_markers", "attempt_nonce_markers_bound", "attempt_projection_present", "case_id", "consistent", "marker_status", "matrix_claim_bound", "matrix_claimed_terminal_status", "matrix_row_sha256", "matrix_terminal_status", "terminal_markers_bound"}), f"attempt marker row {index}")
        if item["case_id"] not in CASE_IDS or item["case_id"] in row_ids:
            _fail("attempt marker row set drifted", code="attempt_marker_drift")
        row_ids.add(item["case_id"])
        _sha256_text(item["matrix_row_sha256"], f"attempt marker {item['case_id']}.matrix_row_sha256")
        if item["matrix_terminal_status"] not in {"missing", "unresolved"} or type(item["attempt_markers"]) is not list:
            _fail(f"attempt marker row malformed: {item['case_id']}", code="attempt_marker_drift")
    if row_ids != set(CASE_IDS):
        _fail("attempt marker rows do not cover the exact matrix", code="attempt_marker_drift")
    cross = _exact(report["cross_binding"], frozenset({"attempt_evidence_report_sha256", "binding_sha256", "blockers", "case_ids", "consistent", "matrix_report_sha256", "scope_id", "static_bindings", "target_readiness_report_sha256", "trusted_handoff_report_sha256", "trusted_identity_report_sha256", "trusted_postrun_report_sha256"}), "cross binding")
    if cross["scope_id"] != SCOPE_ID or cross["case_ids"] != list(CASE_IDS) or type(cross["blockers"]) is not list or type(cross["consistent"]) is not bool:
        _fail("cross binding identity is malformed", code="cross_binding_drift")
    for key in ("matrix_report_sha256", "target_readiness_report_sha256", "trusted_identity_report_sha256", "trusted_handoff_report_sha256", "trusted_postrun_report_sha256"):
        _sha256_text(cross[key], f"cross binding.{key}")
    if cross["attempt_evidence_report_sha256"] is not None:
        _sha256_text(cross["attempt_evidence_report_sha256"], "cross binding.attempt_evidence_report_sha256")
    static = cross["static_bindings"]
    if type(static) is not dict or set(static) != {"attempt_nonce_terminal_markers_bound", "diagnostic_zero_credit_flags_consistent", "matrix_15_case_scope_bound", "matrix_rows_exact_and_unique", "r008_scope_bound", "target_readiness_projection_bound", "terminal_matrix_rows_consistent_with_attempts", "trusted_handoff_matrix_contract_bound", "trusted_issuer_worker_runtime_contract_bound"}:
        _fail("cross binding static field inventory drifted", code="cross_binding_drift")
    for key, item in static.items():
        _bool(item, f"cross binding.static_bindings.{key}")
    core = dict(cross)
    core.pop("binding_sha256")
    if _sha256(canonical_json_bytes(core, label="cross binding")) != cross["binding_sha256"]:
        _fail("cross binding digest is not recomputable", code="digest_drift")
    expected_consistent = not bool(cross["blockers"])
    if cross["consistent"] is not expected_consistent:
        _fail("cross binding status does not match blockers", code="cross_binding_drift")
    if report["status"] == STATUS_BLOCKED and not cross["blockers"]:
        _fail("blocked report has no blocker", code="cross_binding_drift")
    if report["status"] == STATUS_STATIC and cross["blockers"]:
        _fail("static report retains blockers", code="cross_binding_drift")
    return report


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    value, _ = _read_bounded_json(path, label="consistency report")
    if value is None:
        _fail("consistency report is missing", code="missing_input")
    validate_report(value)
    expected = build_report()
    if value != expected:
        _fail("checked-in consistency report does not equal build_report()", code="report_binding_drift")
    return value


def _zh_report(report: Mapping[str, Any]) -> str:
    cross = report["cross_binding"]
    attempt = report["attempt_terminal_binding"]
    blockers = "、".join(cross["blockers"]) if cross["blockers"] else "无"
    return """# F8/R008 terminal matrix ↔ readiness/handoff consistency bridge V1

- 状态：`{status}`
- scope：`{scope}`
- 固定矩阵：15/15 行，case-id 与 q 映射精确绑定。
- target/readiness：`{readiness_status}`；readiness/T1/formal 均为 `false`，credit 为 `0`。
- trusted issuer→worker→runtime：只绑定 synthetic contract projection；production identity、runtime measurement 与 execution authority 均为 `false`。
- attempt/nonce/terminal projection：`present={attempt_present}`、attempt 数量 `{attempt_count}`、nonce markers bound=`{nonce_bound}`、terminal markers bound=`{terminal_bound}`。
- fail-closed blockers：{blockers}
- mutation：completion/denominator/gate/ledger/plan/registry 全部为 `0`。

本 bridge 只读取 bounded strict JSON 和小文件元数据；不读取 production BI4/HDF5/solver frames，不执行 privileged probe、fanotify/kernel/native/solver/worker/GPU/queue，也不写 registry、ledger、denominator、gate、completion 或 PLAN。`build_report()` 是该机器报告的唯一重算来源。
""".format(
        status=report["status"], scope=report["scope_id"],
        readiness_status=report["target_readiness_binding"]["projection_status"],
        attempt_present=attempt["present"], attempt_count=attempt["attempt_count"],
        nonce_bound=attempt["attempt_nonce_markers_bound"],
        terminal_bound=attempt["terminal_markers_bound"], blockers=blockers,
    )


def write_report(
    path: str | Path = DEFAULT_REPORT,
    *,
    zh_path: str | Path = DEFAULT_ZH_REPORT,
    **kwargs: Any,
) -> dict[str, Any]:
    report = build_report(**kwargs)
    output = _canonical_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    zh_output = _canonical_path(zh_path)
    zh_output.parent.mkdir(parents=True, exist_ok=True)
    zh_output.write_text(_zh_report(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write-report", nargs="?", const=DEFAULT_REPORT.as_posix(), metavar="REPORT")
    group.add_argument("--print-report", action="store_true")
    group.add_argument("--verify-report", nargs="?", const=DEFAULT_REPORT.as_posix(), metavar="REPORT")
    parser.add_argument("--zh-report", default=DEFAULT_ZH_REPORT.as_posix(), metavar="ZH_REPORT")
    parser.add_argument("--attempt-evidence", default=DEFAULT_ATTEMPT_EVIDENCE.as_posix(), metavar="JSON")
    args = parser.parse_args(argv)
    kwargs = {"attempt_evidence_path": args.attempt_evidence}
    if args.write_report:
        value = write_report(args.write_report, zh_path=args.zh_report, **kwargs)
    elif args.print_report:
        value = build_report(**kwargs)
    else:
        if args.attempt_evidence != DEFAULT_ATTEMPT_EVIDENCE.as_posix():
            parser.error("--attempt-evidence cannot be combined with --verify-report")
        value = verify_report(args.verify_report)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHORIZATION", "CASE_IDS", "DEFAULT_REPORT", "DEFAULT_ZH_REPORT",
    "READ_POLICY", "REPORT_SCHEMA", "STATUS_BLOCKED", "STATUS_STATIC",
    "SCOPE_ID", "TerminalMatrixReadinessConsistencyError", "build_report",
    "canonical_json_bytes", "validate_report", "verify_report", "write_report",
]
