#!/usr/bin/env python3
"""Bounded, non-authorizing intake for the F8/R008 terminal-evidence matrix.

The intake joins the frozen R008 15-row scope to the checked-in
Definition/control metadata and to the existing target/readiness, causal, and
trusted-worker contract reports.  It accepts only bounded JSON and metadata;
it never follows a Definition/control reference and never opens a BI4/HDF5,
solver frame, worker, queue, GPU, kernel, or fanotify artifact.

The default report is deliberately useful while evidence is absent: every
row is retained in the exact frozen denominator and is marked
``missing``/``unresolved``.  Static receipts, CPU preflight, or caller claims
cannot be promoted to solver completion, readiness, T1, formal admission, or
qualification credit by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SCOPE = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "t1-scope-design-v1/receipt.json"
)
DEFAULT_DEFINITION_CONTROL_PACK = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "definition-control-pack-v1/receipt.json"
)
DEFAULT_PARAMETER_CONTRACT = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json"
)
DEFAULT_TARGET_READINESS = Path(
    "reports/F8-R008-TARGET-KERNEL-READINESS-PROJECTION-V1-2026-09-28.json"
)
DEFAULT_CAUSAL_WITNESS = Path(
    "reports/F8-R008-TERMINAL-CONFORMANCE-CAUSAL-WITNESS-V1.json"
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
DEFAULT_TRUSTED_REPLAY = Path(
    "reports/F8-R008-TRUSTED-WORKER-RUNTIME-REPLAY-LEDGER-BINDING-V1.json"
)
DEFAULT_PROVENANCE_SCHEMA = Path(
    "reports/F8-R008-PER-CASE-PROVENANCE-SCHEMA-V1-2026-09-24.json"
)
DEFAULT_REPORT = Path(
    "reports/F8-R008-TERMINAL-EVIDENCE-MATRIX-INTAKE-V1-2026-09-28.json"
)

REPORT_SCHEMA = "core.cfd.f8.r008_terminal_evidence_matrix_intake_report.v1"
REPORT_RECORD_ID = "f8-r008-terminal-evidence-matrix-intake-v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SCOPE_SCHEMA = "core.cfd.f8.t1_scope_design.v1"
PACK_SCHEMA = "core.cfd.f8.r008_definition_control_pack.v1"
PARAMETER_SCHEMA = "core.cfd.f8.parameter_contract.v1"
TARGET_READINESS_SCHEMA = "core.cfd.f8.r008.target_kernel_readiness_projection_report.v1"
CAUSAL_SCHEMA = "core.cfd.f8.r008_terminal_conformance_causal_witness_report.v1"
IDENTITY_SCHEMA = "core.cfd.f8.r008_trusted_identity_contract_report.v1"
HANDOFF_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_handoff_report.v1"
POSTRUN_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_postrun_matrix_claim_report.v1"
REPLAY_SCHEMA = "core.cfd.f8.r008_trusted_worker_runtime_replay_ledger_binding_report.v1"
PROVENANCE_SCHEMA = "core.cfd.f8.r008_per_case_provenance_contract.v1"

TERMINAL_EVIDENCE_SCHEMA = "core.cfd.f8.r008_terminal_evidence_matrix_claim.v1"
TERMINAL_EVIDENCE_RECORD_ID = "f8-r008-terminal-evidence-matrix-claim-v1"

CASE_COUNT = 15
MAX_JSON_BYTES = 512 * 1024
MAX_DECLARED_REF_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,191}\Z", re.ASCII)

FROZEN_ROW_FIELDS = frozenset({
    "alpha", "case_id", "cflnumber", "compare_to", "control_amplitude_m_s2",
    "control_samples_per_period", "dp_m", "expected_observation_output_count",
    "kind", "native_output_dt_s", "native_output_samples_per_period",
    "observation_cycles", "observation_end_output_index", "observation_end_s",
    "observation_start_output_index", "observation_start_s", "omega_rad_s",
    "period_s", "q", "qualification_only",
})
REF_FIELDS = frozenset({"bytes", "path", "role", "sha256"})
METADATA_REF_FIELDS = frozenset({"bytes", "path", "sha256"})

PIN_GROUP_FIELDS = frozenset({"bound", "trusted", "claims"})
SOURCE_CLAIM_FIELDS = frozenset({
    "source_binary_sha256", "source_commit", "source_tree_sha256",
})
RUNTIME_CLAIM_FIELDS = frozenset({
    "process_generation_id", "runtime_code_sha256", "runtime_manifest_sha256",
})
ABI_CLAIM_FIELDS = frozenset({"abi_sha256", "fanotify_profile_sha256"})
TARGET_CLAIM_FIELDS = frozenset({
    "build_id", "config_sha256", "kernel_release", "uapi_sha256",
})

BCDMARKER_FIELDS = frozenset({
    "manifest_schema", "manifest_sha256", "provenance_bound", "receipt_schema",
    "receipt_sha256", "status", "trusted",
})
METRIC_MARKER_FIELDS = frozenset({
    "metric_result_sha256", "status", "t1_numerical", "trusted",
})
PROVENANCE_MARKER_FIELDS = frozenset({
    "chain_closed", "source_identity_verified", "status", "trusted",
})

ATTEMPT_AND_METRIC_SCHEMAS = {
    "B_receipt": "core.cfd.f8.r008_materialization_receipt.v1",
    "B_manifest": "core.cfd.f8.r008_materialization_output_manifest.v1",
    "C_receipt": "core.cfd.f8.r008_solver_attempt_receipt.v1",
    "C_manifest": "core.cfd.f8.r008_raw_solver_manifest.v1",
    "D_receipt": "core.cfd.f8.r008_decode_table_provenance.v1",
    "D_manifest": "core.cfd.f8.r008_decode_outputs_manifest.v1",
    "D_frame_manifest": "core.cfd.f8.r008_decoded_frame_manifest.v1",
    "native_table": "core.cfd.f8.r008_native_fluid_frame_table.v2",
    "metric_matrix": "core.cfd.f8.r008_t1_metric_matrix_adapter.v5",
}

MUTATIONS_ZERO = {
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "registry_mutation": 0,
}

PROHIBITED_OPERATIONS = [
    "production_bi4_hdf5_or_solver_frame_read",
    "privileged_probe",
    "fanotify_or_kernel_probe",
    "native_or_solver",
    "worker_gpu_or_queue",
]

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class TerminalEvidenceMatrixIntakeError(ValueError):
    """A bounded intake input or report violates the frozen contract."""

    def __init__(self, message: str, *, code: str = "invalid_input") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, *, code: str = "invalid_input") -> None:
    raise TerminalEvidenceMatrixIntakeError(message, code=code)


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
        value.st_dev, value.st_ino, value.st_mode, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns, value.st_nlink,
    )


def _canonical_input_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = LAB_ROOT / path
    if path.as_posix() != str(path) or any(part in {"", ".", ".."} for part in path.parts[1:]):
        _fail(f"input path is not canonical: {value}", code="path_traversal")
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
            raise TerminalEvidenceMatrixIntakeError(
                f"could not inspect input path: {path}", code="path_inspection"
            ) from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"input path contains a symlink: {path}", code="symlink_path")


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _read_bounded_json(
    value: str | Path,
    *,
    label: str,
    limit: int = MAX_JSON_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _canonical_input_path(value)
    _assert_no_symlink_components(path)
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    except FileNotFoundError as error:
        _fail(f"{label} is missing: {_display_path(path)}", code="missing_input")
        raise AssertionError from error
    except OSError as error:
        _fail(f"{label} cannot be opened safely: {_display_path(path)}", code="unsafe_input")
        raise AssertionError from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{label} must be a single-link regular file", code="unsafe_input")
        if before.st_size <= 0 or before.st_size > limit:
            _fail(f"{label} exceeds the bounded JSON limit", code="oversize")
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
        named = os.stat(path, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named):
            _fail(f"{label} changed while being read", code="input_drift")
        raw = b"".join(chunks)
    except TerminalEvidenceMatrixIntakeError:
        raise
    except OSError as error:
        _fail(f"{label} could not be read safely", code="read_error")
        raise AssertionError from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    try:
        parsed = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except TerminalEvidenceMatrixIntakeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not strict UTF-8 JSON", code="invalid_json")
        raise AssertionError from error
    if type(parsed) is not dict:
        _fail(f"{label} must be a JSON object", code="json_not_object")
    return parsed, {
        "path": _display_path(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _require(condition: bool, message: str, *, code: str = "invalid_input") -> None:
    if not condition:
        _fail(message, code=code)


def _require_keys(value: Any, expected: set[str] | frozenset[str], label: str) -> None:
    _require(type(value) is dict and set(value) == set(expected), f"{label} fields differ")


def _sha256(value: Any, label: str) -> str:
    _require(type(value) is str and SHA256_RE.fullmatch(value) is not None,
             f"{label} is not lowercase SHA-256")
    return value


def _finite_number(value: Any, label: str, *, positive: bool = False) -> float:
    _require(type(value) in (int, float) and not isinstance(value, bool),
             f"{label} must be a JSON number")
    result = float(value)
    _require(math.isfinite(result) and (not positive or result > 0.0),
             f"{label} is outside the finite numeric domain")
    return result


def _bounded_integer(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{label} must be a bounded integer")
    return value


def _reference(value: Any, label: str, *, expected_role: str | None = None) -> dict[str, Any]:
    _require_keys(value, REF_FIELDS, label)
    _require(type(value["path"]) is str and value["path"]
             and not Path(value["path"]).is_absolute()
             and ".." not in Path(value["path"]).parts
             and "\\" not in value["path"], f"{label}.path is unsafe")
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_DECLARED_REF_BYTES,
             f"{label}.bytes is outside the bounded metadata domain")
    _sha256(value["sha256"], f"{label}.sha256")
    _require(type(value["role"]) is str and value["role"], f"{label}.role is malformed")
    if expected_role is not None:
        _require(value["role"] == expected_role, f"{label}.role differs")
    return {key: value[key] for key in sorted(REF_FIELDS)}


def _metadata_reference(value: Any, label: str) -> dict[str, Any]:
    """Validate a bounded JSON file reference without inventing an artifact role."""
    _require_keys(value, METADATA_REF_FIELDS, label)
    _require(type(value["path"]) is str and value["path"]
             and not Path(value["path"]).is_absolute()
             and ".." not in Path(value["path"]).parts
             and "\\" not in value["path"], f"{label}.path is unsafe")
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= MAX_JSON_BYTES,
             f"{label}.bytes is outside the bounded JSON domain")
    _sha256(value["sha256"], f"{label}.sha256")
    return {key: value[key] for key in sorted(METADATA_REF_FIELDS)}


def _validate_dependency(
    path: str | Path,
    *,
    label: str,
    schema: str,
    allowed_statuses: set[str],
    same_scope: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    value, reference = _read_bounded_json(path, label=label)
    _require(value.get("schema") == schema, f"{label}.schema differs")
    if same_scope:
        _require(value.get("scope_id") == SCOPE_ID, f"{label}.scope_id differs")
    _require(value.get("status") in allowed_statuses, f"{label}.status is not recognized")
    return value, {
        **reference,
        "schema": value["schema"],
        "record_id": value.get("record_id"),
        "scope_id": value.get("scope_id"),
        "status": value["status"],
    }


def _validate_frozen_scope(scope: Mapping[str, Any]) -> list[dict[str, Any]]:
    _require(scope.get("schema") == SCOPE_SCHEMA, "frozen R008 scope schema differs")
    _require(scope.get("scope_id") == SCOPE_ID, "frozen R008 scope differs")
    _require(scope.get("qualification_only") is True, "frozen scope is not qualification-only")
    matrix = scope.get("matrix")
    _require(type(matrix) is dict, "frozen R008 matrix is missing")
    _require(matrix.get("case_count") == CASE_COUNT, "frozen R008 matrix case_count differs")
    _require(matrix.get("all_rows_are_qualification_only") is True,
             "frozen R008 matrix is not qualification-only")
    rows = matrix.get("rows")
    _require(type(rows) is list and len(rows) == CASE_COUNT,
             "frozen R008 matrix must contain exactly 15 rows")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        _require_keys(row, FROZEN_ROW_FIELDS, f"frozen R008 row {index}")
        case_id = row.get("case_id")
        _require(type(case_id) is str and IDENTIFIER_RE.fullmatch(case_id) is not None,
                 f"frozen R008 row {index}.case_id is malformed")
        _require(case_id not in seen, f"duplicate frozen R008 row: {case_id}", code="duplicate_row")
        seen.add(case_id)
        _require(row["qualification_only"] is True, f"row is not qualification-only: {case_id}")
        _finite_number(row["q"], f"{case_id}.q")
        for field in (
            "alpha", "cflnumber", "control_amplitude_m_s2", "dp_m",
            "native_output_dt_s", "observation_end_s", "observation_start_s",
            "omega_rad_s", "period_s",
        ):
            _finite_number(row[field], f"{case_id}.{field}", positive=field not in {"control_amplitude_m_s2"})
        for field in (
            "control_samples_per_period", "expected_observation_output_count",
            "native_output_samples_per_period", "observation_cycles",
            "observation_end_output_index", "observation_start_output_index",
        ):
            _bounded_integer(row[field], f"{case_id}.{field}")
        _require(type(row["kind"]) is str and row["kind"], f"{case_id}.kind is malformed")
        _require(row["compare_to"] is None or (
            type(row["compare_to"]) is str and IDENTIFIER_RE.fullmatch(row["compare_to"]) is not None
        ), f"{case_id}.compare_to is malformed")
        normalized.append(dict(row))
    return normalized


def _validate_pack(
    pack: Mapping[str, Any],
    frozen_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    _require(pack.get("schema") == PACK_SCHEMA, "Definition/control pack schema differs")
    _require(pack.get("scope_id") == SCOPE_ID, "Definition/control pack scope differs")
    cases = pack.get("cases")
    _require(type(cases) is list, "Definition/control pack cases are missing")
    qualifying = [row for row in cases if type(row) is dict and row.get("qualification_only") is True]
    _require(len(qualifying) == CASE_COUNT,
             "Definition/control pack must contain exactly the 15 qualification rows")
    by_id: dict[str, dict[str, Any]] = {}
    for row in qualifying:
        case_id = row.get("case_id")
        _require(type(case_id) is str and case_id not in by_id,
                 "Definition/control pack has duplicate qualification row", code="duplicate_row")
        by_id[case_id] = row
    frozen_ids = [row["case_id"] for row in frozen_rows]
    _require(set(by_id) == set(frozen_ids),
             "Definition/control pack qualification IDs differ from frozen R008 matrix",
             code="row_drift")
    expected_root = (
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
        "definition-control-pack-v1/qualification/"
    )
    for frozen in frozen_rows:
        case_id = frozen["case_id"]
        row = by_id[case_id]
        _require(row.get("qualification_only") is True, f"pack row is not qualification-only: {case_id}")
        for field in (
            "alpha", "case_id", "cflnumber", "compare_to", "control_samples_per_period",
            "dp_m", "expected_observation_output_count", "kind", "native_output_dt_s",
            "native_output_samples_per_period", "observation_end_s", "observation_start_s",
            "omega_rad_s", "period_s", "q",
        ):
            left, right = row.get(field), frozen.get(field)
            if type(left) in (int, float) and type(right) in (int, float):
                equal = math.isclose(float(left), float(right), rel_tol=1e-15, abs_tol=1e-15)
            else:
                equal = left == right
            _require(equal, f"Definition/control row drift: {case_id}.{field}", code="row_drift")
        definition = _reference(row.get("definition"), f"{case_id}.definition",
                                expected_role="fresh R008 per-case Definition XML")
        control = _reference(row.get("control"), f"{case_id}.control",
                             expected_role="fresh R008 per-case acceleration CSV colocated with Definition")
        for ref, suffix in ((definition, ".xml"), (control, ".csv")):
            _require(ref["path"].startswith(expected_root + case_id + "/"),
                     f"{case_id} input reference escapes its qualification namespace")
            _require(ref["path"].endswith(suffix), f"{case_id} input reference suffix differs")
        by_id[case_id] = {
            "case_id": case_id,
            "q": row["q"],
            "definition": definition,
            "control": control,
        }
    return {case_id: by_id[case_id] for case_id in frozen_ids}


def _validate_parameter_contract(value: Mapping[str, Any]) -> None:
    _require(value.get("schema") == PARAMETER_SCHEMA, "R001 parameter contract schema differs")
    _require(value.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
             "R001 parameter contract scope differs")
    _require(value.get("status") == "pre_admission_static_contract_frozen",
             "R001 parameter contract is not the frozen static contract")
    _require(value.get("qualification_credit") == 0, "parameter contract carries credit")


def _validate_non_authorizing_boundary(value: Mapping[str, Any], label: str) -> None:
    boundary = value.get("non_authorizing_boundary")
    _require(type(boundary) is dict, f"{label} non-authorizing boundary is missing")
    for field in ("diagnostic_only", "readiness_pass", "T1_numerical"):
        _require(boundary.get(field) is (field == "diagnostic_only"),
                 f"{label}.{field} crossed the non-authorizing boundary")
    for field in ("qualification_credit", "completion_mutation", "denominator_mutation",
                  "gate_mutation", "ledger_mutation", "registry_mutation"):
        if field in boundary:
            _require(boundary[field] == 0, f"{label}.{field} is non-zero")


def _validate_target_readiness(value: Mapping[str, Any]) -> None:
    _require(value.get("schema") == TARGET_READINESS_SCHEMA, "target/readiness projection schema differs")
    _require(value.get("scope_id") == SCOPE_ID, "target/readiness projection scope differs")
    _require(value.get("status") == "diagnostic_only_target_kernel_readiness_blocked",
             "target/readiness projection status differs")
    auth = value.get("authorization")
    _require(type(auth) is dict and auth.get("diagnostic_only") is True
             and auth.get("readiness_pass") is False and auth.get("T1_numerical") is False
             and auth.get("formal_admission") is False and auth.get("qualification_credit") == 0,
             "target/readiness projection authorization crossed its boundary")
    target = value.get("target_kernel")
    _require(type(target) is dict and target.get("all_pins_complete") is False
             and target.get("external_evidence_complete") is False,
             "target/readiness projection unexpectedly claims complete target pins")
    pins = target.get("pins")
    _require(type(pins) is dict and set(pins) == {
        "build_id_pinned", "config_pinned", "kernel_release_pinned",
        "source_commit_pinned", "source_tree_pinned", "uapi_pinned",
    } and all(flag is False for flag in pins.values()),
             "target/readiness projection target pins are not fail-closed")
    trusted = value.get("trusted_runtime")
    _require(type(trusted) is dict
             and trusted.get("execution_authority") is False
             and trusted.get("production_authority_authenticated") is False
             and trusted.get("production_runtime_identity_authenticated") is False
             and trusted.get("runtime_measured") is False,
             "target/readiness projection trusted runtime is not fail-closed")
    validation = value.get("validation")
    _require(type(validation) is dict and validation.get("readiness_v8_zero_credit_preserved") is True
             and validation.get("target_abi_conformance") is False
             and validation.get("target_kernel_runtime_conformance") is False,
             "target/readiness projection validation boundary differs")


def _validate_causal_witness(value: Mapping[str, Any]) -> None:
    _require(value.get("schema") == CAUSAL_SCHEMA, "causal witness schema differs")
    _require(value.get("scope_id") == SCOPE_ID
             and value.get("status") == "synthetic_only_static_non_authorizing_contract",
             "causal witness is not the static non-authorizing report")
    _validate_non_authorizing_boundary(value, "causal witness")
    witness = value.get("causal_witness")
    _require(type(witness) is dict and witness.get("runtime_source_authenticated") is False,
             "causal witness runtime source is unexpectedly authenticated")
    trust = value.get("trust_boundary")
    _require(type(trust) is dict and trust.get("trusted_authority_present") is False,
             "causal witness trusted authority is unexpectedly present")
    _require("fanotify_or_kernel_probe" in value.get("prohibited_operations", [])
             and "native_or_solver" in value.get("prohibited_operations", []),
             "causal witness prohibited operation boundary differs")


def _validate_trusted_contract(value: Mapping[str, Any], *, schema: str, status: str, label: str) -> None:
    _require(value.get("schema") == schema and value.get("scope_id") == SCOPE_ID
             and value.get("status") == status, f"{label} identity/status differs")
    _validate_non_authorizing_boundary(value, label)
    _require("worker_gpu_or_queue" in value.get("prohibited_operations", [])
             or "kernel_or_solver_access" in value.get("prohibited_operations", [])
             or "solver_or_native_execution" in value.get("prohibited_operations", []),
             f"{label} prohibited operation boundary differs")


def _validate_postrun_contract(value: Mapping[str, Any]) -> None:
    _validate_trusted_contract(
        value, schema=POSTRUN_SCHEMA,
        status="synthetic_only_non_authorizing_postrun_matrix_claim_binding_design",
        label="trusted postrun contract",
    )
    matrix = value.get("matrix_contract")
    _require(type(matrix) is dict and matrix.get("case_count") == CASE_COUNT
             and matrix.get("missing_or_extra_rows") == "reject"
             and matrix.get("production_bundle_read") is False
             and matrix.get("postrun_case_worker_called") is False
             and matrix.get("postrun_matrix_worker_called") is False,
             "trusted postrun matrix contract differs")


def _validate_provenance_schema(value: Mapping[str, Any]) -> None:
    _require(value.get("schema") == PROVENANCE_SCHEMA, "B/C/D provenance schema differs")
    _require(value.get("scope_id") == SCOPE_ID, "B/C/D provenance scope differs")
    for section, receipt_schema in (
        ("stage_B_materialization", ATTEMPT_AND_METRIC_SCHEMAS["B_receipt"]),
        ("stage_C_solver_attempt", ATTEMPT_AND_METRIC_SCHEMAS["C_receipt"]),
        ("stage_D_decode_table_provenance", ATTEMPT_AND_METRIC_SCHEMAS["D_receipt"]),
    ):
        section_value = value.get(section)
        _require(type(section_value) is dict and section_value.get("receipt_schema") == receipt_schema,
                 f"{section} receipt schema differs")
    table = value["stage_D_decode_table_provenance"].get("table_schema")
    _require(type(table) is dict and table.get("schema") == ATTEMPT_AND_METRIC_SCHEMAS["native_table"],
             "native table schema differs")
    verifier = value.get("verifier_result")
    _require(type(verifier) is dict and verifier.get("readiness_pass") is False
             and verifier.get("qualification_credit") == 0
             and verifier.get("failed_or_missing_attempt_remains_in_15_row_denominator") is True,
             "B/C/D provenance verifier boundary differs")


def _empty_terminal_evidence_input() -> dict[str, Any]:
    return {"present": False, "path": None, "bytes": None, "sha256": None}


def _validate_claim_group(
    value: Any,
    expected_fields: frozenset[str],
    claim_fields: frozenset[str],
    label: str,
) -> dict[str, Any]:
    _require_keys(value, PIN_GROUP_FIELDS, label)
    _require(type(value["bound"]) is bool and type(value["trusted"]) is bool,
             f"{label}.bound/trusted must be boolean")
    claims = value["claims"]
    _require_keys(claims, claim_fields, f"{label}.claims")
    for key, item in claims.items():
        _require(item is None or type(item) is str, f"{label}.claims.{key} must be string or null")
        if item is not None and (key.endswith("sha256") or key in {"abi_sha256", "uapi_sha256", "config_sha256"}):
            _sha256(item, f"{label}.claims.{key}")
    if value["trusted"]:
        _require(value["bound"], f"{label} cannot be trusted without binding")
        _require(all(item is not None for item in claims.values()),
                 f"{label} trusted claim has missing pin")
    return {"bound": value["bound"], "trusted": value["trusted"], "claims": dict(claims)}


def _empty_pin_group(claim_fields: frozenset[str]) -> dict[str, Any]:
    return {"bound": False, "trusted": False, "claims": {key: None for key in sorted(claim_fields)}}


def _empty_bcd(stage: str) -> dict[str, Any]:
    schemas = {
        "B": (ATTEMPT_AND_METRIC_SCHEMAS["B_receipt"], ATTEMPT_AND_METRIC_SCHEMAS["B_manifest"]),
        "C": (ATTEMPT_AND_METRIC_SCHEMAS["C_receipt"], ATTEMPT_AND_METRIC_SCHEMAS["C_manifest"]),
        "D": (ATTEMPT_AND_METRIC_SCHEMAS["D_receipt"], ATTEMPT_AND_METRIC_SCHEMAS["D_manifest"]),
    }
    receipt_schema, manifest_schema = schemas[stage]
    return {
        "manifest_schema": manifest_schema,
        "manifest_sha256": None,
        "provenance_bound": False,
        "receipt_schema": receipt_schema,
        "receipt_sha256": None,
        "status": "missing",
        "trusted": False,
    }


def _empty_metric() -> dict[str, Any]:
    return {"metric_result_sha256": None, "status": "missing", "t1_numerical": False, "trusted": False}


def _empty_provenance() -> dict[str, Any]:
    return {"chain_closed": False, "source_identity_verified": False, "status": "missing", "trusted": False}


def _validate_marker(value: Any, expected_fields: frozenset[str], label: str) -> dict[str, Any]:
    _require_keys(value, expected_fields, label)
    return dict(value)


def _validate_terminal_evidence_document(
    value: Mapping[str, Any], frozen_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    expected = {"case_count", "input_origin", "record_id", "rows", "schema", "scope_id", "status"}
    _require_keys(value, expected, "terminal evidence input")
    _require(value.get("schema") == TERMINAL_EVIDENCE_SCHEMA
             and value.get("record_id") == TERMINAL_EVIDENCE_RECORD_ID
             and value.get("scope_id") == SCOPE_ID
             and value.get("case_count") == CASE_COUNT,
             "terminal evidence input identity differs")
    _require(value.get("input_origin") in {
        "trusted_production_terminal_evidence", "synthetic_static_receipt", "cpu_preflight",
    }, "terminal evidence input origin is unsupported")
    _require(value.get("status") in {"partial", "complete_claim", "missing"},
             "terminal evidence input status is unsupported")
    rows = value.get("rows")
    _require(type(rows) is list and len(rows) <= CASE_COUNT,
             "terminal evidence input row count is outside the bounded domain")
    result: dict[str, dict[str, Any]] = {}
    expected_row_fields = {
        "abi", "B", "C", "D", "case_id", "metric", "provenance", "q",
        "runtime", "source", "target", "terminal_status",
    }
    for index, row in enumerate(rows):
        _require_keys(row, expected_row_fields, f"terminal evidence row {index}")
        case_id = row["case_id"]
        _require(case_id in frozen_by_id, f"terminal evidence row has unknown case: {case_id}", code="row_drift")
        _require(case_id not in result, f"duplicate terminal evidence row: {case_id}", code="duplicate_row")
        _require(row["q"] == frozen_by_id[case_id]["q"], f"terminal evidence q drift: {case_id}", code="row_drift")
        _require(row["terminal_status"] in {"missing", "partial", "complete", "failed"},
                 f"terminal evidence terminal_status is unsupported: {case_id}")
        for name, fields in (
            ("source", SOURCE_CLAIM_FIELDS), ("runtime", RUNTIME_CLAIM_FIELDS),
            ("abi", ABI_CLAIM_FIELDS), ("target", TARGET_CLAIM_FIELDS),
        ):
            _validate_claim_group(row[name], fields, fields, f"terminal evidence {case_id}.{name}")
        for stage in ("B", "C", "D"):
            _validate_marker(row[stage], BCDMARKER_FIELDS, f"terminal evidence {case_id}.{stage}")
        _validate_marker(row["metric"], METRIC_MARKER_FIELDS, f"terminal evidence {case_id}.metric")
        _validate_marker(row["provenance"], PROVENANCE_MARKER_FIELDS, f"terminal evidence {case_id}.provenance")
        row_copy = dict(row)
        row_copy["_input_origin"] = value["input_origin"]
        result[case_id] = row_copy
    return result


def _row_from_claim(
    frozen: Mapping[str, Any], pack_row: Mapping[str, Any], *, scope_ref: Mapping[str, Any],
    pack_ref: Mapping[str, Any], parameter_ref: Mapping[str, Any], row_index: int,
    claim: Mapping[str, Any] | None,
) -> dict[str, Any]:
    case_id = frozen["case_id"]
    refs = {
        "control": dict(pack_row["control"]),
        "definition": dict(pack_row["definition"]),
        "definition_control_pack": dict(pack_ref),
        "parameter_contract": dict(parameter_ref),
        "scope_row": {**dict(scope_ref), "row_index": row_index},
    }
    source = _empty_pin_group(SOURCE_CLAIM_FIELDS)
    runtime = _empty_pin_group(RUNTIME_CLAIM_FIELDS)
    abi = _empty_pin_group(ABI_CLAIM_FIELDS)
    target = _empty_pin_group(TARGET_CLAIM_FIELDS)
    bcd = {stage: _empty_bcd(stage) for stage in ("B", "C", "D")}
    metric = _empty_metric()
    provenance = _empty_provenance()
    terminal_status = "missing"
    claimed_terminal_status: str | None = None
    claim_origin: str | None = None
    if claim is not None:
        claim_origin = claim.get("_input_origin")
        claimed_terminal_status = claim["terminal_status"]
        terminal_status = (
            "missing" if claimed_terminal_status == "missing"
            else "unresolved"
        )
        for name, target_group in (
            ("source", source), ("runtime", runtime), ("abi", abi), ("target", target),
        ):
            target_group.update({
                # This intake records caller claims but never promotes them
                # into trusted pins or runtime identity.
                "bound": False,
                "trusted": False,
                "claims": dict(claim[name]["claims"]),
            })
        bcd = {
            stage: {
                **dict(claim[stage]), "provenance_bound": False, "trusted": False,
            }
            for stage in ("B", "C", "D")
        }
        metric = {**dict(claim["metric"]), "t1_numerical": False, "trusted": False}
        provenance = {
            **dict(claim["provenance"]),
            "chain_closed": False, "source_identity_verified": False, "trusted": False,
        }
        # The intake is not an execution verifier. Even a fully populated
        # caller claim remains unresolved and cannot become solver completion.
        terminal_status = "missing" if claimed_terminal_status == "missing" else "unresolved"
    return {
        "case_id": case_id,
        "q": frozen["q"],
        "kind": frozen["kind"],
        "frozen_row": dict(frozen),
        "input_refs": refs,
        "terminal_status": terminal_status,
        "claimed_terminal_status": claimed_terminal_status,
        "claim_input_origin": claim_origin,
        "source_pins": source,
        "runtime_pins": runtime,
        "abi_pins": abi,
        "target_pins": target,
        "B": bcd["B"],
        "C": bcd["C"],
        "D": bcd["D"],
        "metric": metric,
        "provenance": provenance,
        "solver_completion_verified": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "formal": False,
        "qualification_credit": 0,
    }


def _dependency_refs(
    target: Mapping[str, Any], target_ref: Mapping[str, Any],
    causal: Mapping[str, Any], causal_ref: Mapping[str, Any],
    identity: Mapping[str, Any], identity_ref: Mapping[str, Any],
    handoff: Mapping[str, Any], handoff_ref: Mapping[str, Any],
    postrun: Mapping[str, Any], postrun_ref: Mapping[str, Any],
    replay: Mapping[str, Any], replay_ref: Mapping[str, Any],
    provenance: Mapping[str, Any], provenance_ref: Mapping[str, Any],
) -> dict[str, Any]:
    def one(value: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "path": reference["path"], "bytes": reference["bytes"], "sha256": reference["sha256"],
            "schema": value.get("schema"), "record_id": value.get("record_id"),
            "scope_id": value.get("scope_id"), "status": value.get("status"),
        }
    return {
        "target_readiness_projection": one(target, target_ref),
        "causal_witness": one(causal, causal_ref),
        "trusted_identity_contract": one(identity, identity_ref),
        "trusted_handoff_contract": one(handoff, handoff_ref),
        "trusted_postrun_contract": one(postrun, postrun_ref),
        "trusted_replay_contract": one(replay, replay_ref),
        "B_C_D_provenance_schema": one(provenance, provenance_ref),
    }


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "readiness_pass": False,
        "T1_numerical": False,
        "formal": False,
        "qualification_credit": 0,
        "execution_authority": False,
        "solver_completion_verified": False,
    }


def build_report(
    *,
    scope_path: str | Path = DEFAULT_SCOPE,
    definition_control_pack_path: str | Path = DEFAULT_DEFINITION_CONTROL_PACK,
    parameter_contract_path: str | Path = DEFAULT_PARAMETER_CONTRACT,
    target_readiness_path: str | Path = DEFAULT_TARGET_READINESS,
    causal_witness_path: str | Path = DEFAULT_CAUSAL_WITNESS,
    trusted_identity_path: str | Path = DEFAULT_TRUSTED_IDENTITY,
    trusted_handoff_path: str | Path = DEFAULT_TRUSTED_HANDOFF,
    trusted_postrun_path: str | Path = DEFAULT_TRUSTED_POSTRUN,
    trusted_replay_path: str | Path = DEFAULT_TRUSTED_REPLAY,
    provenance_schema_path: str | Path = DEFAULT_PROVENANCE_SCHEMA,
    terminal_evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build one deterministic, diagnostic-only 15-row intake report."""
    scope, scope_ref = _read_bounded_json(scope_path, label="frozen R008 scope")
    frozen_rows = _validate_frozen_scope(scope)
    pack, pack_ref = _read_bounded_json(definition_control_pack_path, label="Definition/control pack")
    pack_rows = _validate_pack(pack, frozen_rows)
    parameter, parameter_ref = _read_bounded_json(parameter_contract_path, label="R001 parameter contract")
    _validate_parameter_contract(parameter)

    target, target_ref = _validate_dependency(
        target_readiness_path, label="target/readiness projection",
        schema=TARGET_READINESS_SCHEMA,
        allowed_statuses={"diagnostic_only_target_kernel_readiness_blocked"},
    )
    _validate_target_readiness(target)
    causal, causal_ref = _validate_dependency(
        causal_witness_path, label="causal witness", schema=CAUSAL_SCHEMA,
        allowed_statuses={"synthetic_only_static_non_authorizing_contract"},
    )
    _validate_causal_witness(causal)
    identity, identity_ref = _validate_dependency(
        trusted_identity_path, label="trusted identity contract", schema=IDENTITY_SCHEMA,
        allowed_statuses={"synthetic_only_non_authorizing_contract_design"},
    )
    _validate_trusted_contract(
        identity, schema=IDENTITY_SCHEMA,
        status="synthetic_only_non_authorizing_contract_design", label="trusted identity contract",
    )
    handoff, handoff_ref = _validate_dependency(
        trusted_handoff_path, label="trusted handoff contract", schema=HANDOFF_SCHEMA,
        allowed_statuses={"synthetic_only_non_authorizing_handoff_contract_design"},
    )
    _validate_trusted_contract(
        handoff, schema=HANDOFF_SCHEMA,
        status="synthetic_only_non_authorizing_handoff_contract_design", label="trusted handoff contract",
    )
    postrun, postrun_ref = _validate_dependency(
        trusted_postrun_path, label="trusted postrun contract", schema=POSTRUN_SCHEMA,
        allowed_statuses={"synthetic_only_non_authorizing_postrun_matrix_claim_binding_design"},
    )
    _validate_postrun_contract(postrun)
    replay, replay_ref = _validate_dependency(
        trusted_replay_path, label="trusted replay contract", schema=REPLAY_SCHEMA,
        allowed_statuses={"synthetic_only_non_authorizing_replay_ledger_contract_design"},
    )
    _validate_trusted_contract(
        replay, schema=REPLAY_SCHEMA,
        status="synthetic_only_non_authorizing_replay_ledger_contract_design", label="trusted replay contract",
    )
    provenance, provenance_ref = _validate_dependency(
        provenance_schema_path, label="B/C/D provenance schema", schema=PROVENANCE_SCHEMA,
        allowed_statuses={"static_contract_for_review_not_execution_authority"},
    )
    _validate_provenance_schema(provenance)

    evidence_meta = _empty_terminal_evidence_input()
    claims: dict[str, dict[str, Any]] = {}
    frozen_by_id = {row["case_id"]: row for row in frozen_rows}
    if terminal_evidence_path is not None:
        evidence, evidence_meta = _read_bounded_json(
            terminal_evidence_path, label="terminal evidence input",
        )
        claims = _validate_terminal_evidence_document(evidence, frozen_by_id)
        evidence_meta = {"present": True, **evidence_meta}

    rows = [
        _row_from_claim(
            frozen, pack_rows[frozen["case_id"]], scope_ref=scope_ref, pack_ref=pack_ref,
            parameter_ref=parameter_ref, row_index=index, claim=claims.get(frozen["case_id"]),
        )
        for index, frozen in enumerate(frozen_rows)
    ]
    missing_count = sum(row["terminal_status"] == "missing" for row in rows)
    unresolved_count = sum(row["terminal_status"] == "unresolved" for row in rows)
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": "diagnostic_only_terminal_evidence_matrix_blocked",
        "scope_id": SCOPE_ID,
        "matrix_contract": {
            "case_count": CASE_COUNT,
            "case_ids": [row["case_id"] for row in frozen_rows],
            "q_values_by_case": {row["case_id"]: row["q"] for row in frozen_rows},
            "exact_15_rows": True,
            "scope_ref": dict(scope_ref),
            "definition_control_pack_ref": dict(pack_ref),
            "parameter_contract_ref": dict(parameter_ref),
        },
        "schema_bindings": {
            "attempt_receipts_and_manifests": dict(ATTEMPT_AND_METRIC_SCHEMAS),
            "provenance_contract": PROVENANCE_SCHEMA,
            "metric_matrix_adapter": ATTEMPT_AND_METRIC_SCHEMAS["metric_matrix"],
        },
        "dependencies": _dependency_refs(
            target, target_ref, causal, causal_ref, identity, identity_ref,
            handoff, handoff_ref, postrun, postrun_ref, replay, replay_ref,
            provenance, provenance_ref,
        ),
        "terminal_evidence_input": evidence_meta,
        "rows": rows,
        "summary": {
            "missing_rows": missing_count,
            "unresolved_rows": unresolved_count,
            "solver_completion_verified_rows": 0,
            "readiness_rows": 0,
            "T1_rows": 0,
            "formal_rows": 0,
            "qualification_credit": 0,
        },
        "authorization": _authorization(),
        "mutations": dict(MUTATIONS_ZERO),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "read_policy": {
            "bounded_json_only": True,
            "small_file_metadata_only": True,
            "definition_control_content_read": False,
            "production_bi4_hdf5_read": False,
            "solver_frame_read": False,
            "privileged_probe": False,
            "fanotify_kernel_native_solver_worker_gpu_queue": False,
        },
    }


def _validate_pin_group(value: Any, claim_fields: frozenset[str], label: str) -> None:
    _validate_claim_group(value, claim_fields, claim_fields, label)


def _validate_report(value: Any) -> dict[str, Any]:
    expected = {
        "authorization", "dependencies", "matrix_contract", "mutations", "prohibited_operations",
        "read_policy", "record_id", "rows", "schema", "schema_bindings", "scope_id", "status",
        "summary", "terminal_evidence_input",
    }
    _require_keys(value, expected, "terminal evidence matrix report")
    _require(value["schema"] == REPORT_SCHEMA and value["record_id"] == REPORT_RECORD_ID
             and value["scope_id"] == SCOPE_ID
             and value["status"] == "diagnostic_only_terminal_evidence_matrix_blocked",
             "terminal evidence matrix report identity differs")
    matrix = value["matrix_contract"]
    _require_keys(matrix, {
        "case_count", "case_ids", "q_values_by_case", "exact_15_rows", "scope_ref",
        "definition_control_pack_ref", "parameter_contract_ref",
    }, "report matrix_contract")
    _require(matrix["case_count"] == CASE_COUNT and matrix["exact_15_rows"] is True,
             "report matrix denominator is not exactly 15")
    case_ids = matrix["case_ids"]
    _require(type(case_ids) is list and len(case_ids) == CASE_COUNT
             and len(set(case_ids)) == CASE_COUNT
             and all(type(item) is str for item in case_ids),
             "report matrix case IDs are not unique exact rows")
    _require(type(matrix["q_values_by_case"]) is dict
             and set(matrix["q_values_by_case"]) == set(case_ids),
             "report matrix q projection differs")
    _metadata_reference(matrix["scope_ref"], "report matrix.scope_ref")
    _metadata_reference(matrix["definition_control_pack_ref"], "report matrix.definition_control_pack_ref")
    _metadata_reference(matrix["parameter_contract_ref"], "report matrix.parameter_contract_ref")
    _require(type(value["rows"]) is list and len(value["rows"]) == CASE_COUNT,
             "report rows are not exactly 15")
    seen: set[str] = set()
    row_fields = {
        "B", "C", "D", "T1_numerical", "abi_pins", "case_id", "claim_input_origin",
        "claimed_terminal_status", "formal", "frozen_row", "input_refs", "kind", "metric",
        "provenance", "q", "qualification_credit", "readiness_pass", "runtime_pins",
        "solver_completion_verified", "source_pins", "target_pins", "terminal_status",
    }
    for index, row in enumerate(value["rows"]):
        _require_keys(row, row_fields, f"report row {index}")
        case_id = row["case_id"]
        _require(case_id in set(case_ids) and case_id not in seen,
                 f"report row IDs are missing/duplicate: {case_id}", code="duplicate_row")
        seen.add(case_id)
        _require(row["q"] == matrix["q_values_by_case"][case_id], f"report q drift: {case_id}")
        _require(row["terminal_status"] in {"missing", "unresolved"},
                 f"report terminal status crossed unresolved boundary: {case_id}")
        _require(row["solver_completion_verified"] is False and row["readiness_pass"] is False
                 and row["T1_numerical"] is False and row["formal"] is False
                 and row["qualification_credit"] == 0,
                 f"report row authorization crossed boundary: {case_id}")
        _require_keys(row["frozen_row"], FROZEN_ROW_FIELDS, f"report row {case_id}.frozen_row")
        _reference(row["input_refs"]["definition"], f"report row {case_id}.input_refs.definition")
        _reference(row["input_refs"]["control"], f"report row {case_id}.input_refs.control")
        _metadata_reference(
            row["input_refs"]["definition_control_pack"],
            f"report row {case_id}.input_refs.definition_control_pack",
        )
        _metadata_reference(
            row["input_refs"]["parameter_contract"],
            f"report row {case_id}.input_refs.parameter_contract",
        )
        scope_row_ref = row["input_refs"]["scope_row"]
        _require(type(scope_row_ref) is dict
                 and set(scope_row_ref) == set(METADATA_REF_FIELDS) | {"row_index"},
                 f"report row {case_id}.input_refs.scope_row fields differ")
        _metadata_reference(
            {key: scope_row_ref[key] for key in METADATA_REF_FIELDS},
            f"report row {case_id}.input_refs.scope_row",
        )
        _require(type(scope_row_ref["row_index"]) is int and scope_row_ref["row_index"] >= 0,
                 f"report row {case_id}.input_refs.scope_row.row_index is malformed")
        _validate_pin_group(row["source_pins"], SOURCE_CLAIM_FIELDS, f"report row {case_id}.source_pins")
        _validate_pin_group(row["runtime_pins"], RUNTIME_CLAIM_FIELDS, f"report row {case_id}.runtime_pins")
        _validate_pin_group(row["abi_pins"], ABI_CLAIM_FIELDS, f"report row {case_id}.abi_pins")
        _validate_pin_group(row["target_pins"], TARGET_CLAIM_FIELDS, f"report row {case_id}.target_pins")
        for stage in ("B", "C", "D"):
            _require_keys(row[stage], BCDMARKER_FIELDS, f"report row {case_id}.{stage}")
            _require(row[stage]["trusted"] is False and row[stage]["provenance_bound"] is False,
                     f"report row {case_id}.{stage} crossed trust boundary")
        _require_keys(row["metric"], METRIC_MARKER_FIELDS, f"report row {case_id}.metric")
        _require(row["metric"]["trusted"] is False and row["metric"]["t1_numerical"] is False,
                 f"report row {case_id}.metric crossed trust boundary")
        _require_keys(row["provenance"], PROVENANCE_MARKER_FIELDS, f"report row {case_id}.provenance")
        _require(row["provenance"]["trusted"] is False and row["provenance"]["chain_closed"] is False,
                 f"report row {case_id}.provenance crossed trust boundary")
    _require(seen == set(case_ids), "report rows do not cover the exact matrix")
    _require(value["authorization"] == _authorization(), "report authorization boundary was promoted")
    _require(value["mutations"] == MUTATIONS_ZERO, "report mutation boundary is non-zero")
    _require(value["prohibited_operations"] == PROHIBITED_OPERATIONS,
             "report prohibited operation boundary differs")
    policy = value["read_policy"]
    _require(type(policy) is dict and all(policy.get(key) is expected_value for key, expected_value in {
        "bounded_json_only": True, "small_file_metadata_only": True,
        "definition_control_content_read": False, "production_bi4_hdf5_read": False,
        "solver_frame_read": False, "privileged_probe": False,
        "fanotify_kernel_native_solver_worker_gpu_queue": False,
    }.items()), "report read policy crossed boundary")
    summary = value["summary"]
    _require(type(summary) is dict and summary.get("qualification_credit") == 0
             and summary.get("solver_completion_verified_rows") == 0
             and summary.get("readiness_rows") == 0 and summary.get("T1_rows") == 0
             and summary.get("formal_rows") == 0,
             "report summary crossed authorization boundary")
    return value


def validate_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an already parsed report without reading production artifacts."""
    if type(value) is not dict:
        _fail("report must be a JSON object", code="invalid_report")
    return _validate_report(value)


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    value, _ = _read_bounded_json(path, label="terminal evidence matrix report")
    return validate_report(value)


def write_report(path: str | Path = DEFAULT_REPORT, *, terminal_evidence_path: str | Path | None = None) -> dict[str, Any]:
    report = build_report(terminal_evidence_path=terminal_evidence_path)
    validate_report(report)
    output = _canonical_input_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write-report", nargs="?", const=DEFAULT_REPORT.as_posix(), metavar="REPORT")
    group.add_argument("--print-report", action="store_true")
    group.add_argument("--verify-report", nargs="?", const=DEFAULT_REPORT.as_posix(), metavar="REPORT")
    parser.add_argument("--terminal-evidence", metavar="JSON", default=None)
    args = parser.parse_args()
    if args.write_report:
        value = write_report(args.write_report, terminal_evidence_path=args.terminal_evidence)
    elif args.print_report:
        value = build_report(terminal_evidence_path=args.terminal_evidence)
    else:
        if args.terminal_evidence is not None:
            parser.error("--terminal-evidence cannot be combined with --verify-report")
        value = verify_report(args.verify_report)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
