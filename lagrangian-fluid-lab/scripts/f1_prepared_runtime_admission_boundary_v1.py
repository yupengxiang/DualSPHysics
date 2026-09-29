#!/usr/bin/env python3
"""Verify the bounded F1 prepared-to-runtime admission interface.

This module is intentionally narrower than the F1 readiness bridge.  It does
not re-audit qualification evidence.  It derives a stable row-binding view
from the current prepared matrix and job manifest, then checks the shape of a
future, non-authorizing runtime-admission envelope.  A caller-supplied flag is
never treated as a trusted root, runtime identity, observer instance, or
execution authorization.

Only four bounded JSON metadata files are opened.  Paths stored inside those
files are metadata and are never followed, opened, stat'ed, hashed, or
decoded.  The module never launches or stops GenCase, native code, solver,
worker, GPU, or queue and never writes PLAN, registry, ledger, denominator,
gate, or completion state.
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
REPORT_SCHEMA = "core.f1.prepared_runtime_admission_boundary_report.v1"
REQUEST_SCHEMA = "core.f1.prepared_runtime_admission_request.v1"
RECORD_ID = "f1-prepared-runtime-admission-boundary-v1"
BOUNDARY_ID = "F1_H1_prepared_to_runtime_admission_v1"
SCOPE_ID = "F1_single_obstacle_height_range_v1"
PREPARED_REVISION = "F1_H1_geometry_observer_qualification_v1"
OBSERVER_REVISION = PREPARED_REVISION
EXPECTED_CELLS = 15
OBSERVED_AT_UTC = "2026-09-29T00:00:00Z"
MAX_JSON_BYTES = 256 * 1024
SHA256_HEX = frozenset("0123456789abcdef")

MATRIX_SCHEMA = "core.f1.qualification.v1"
JOBS_SCHEMA = "core.cfd.jobs.v1"
DESIGN_SCHEMA = "core.f1.qualification.v1"
CALIBRATION_SCHEMA = "core.f1.observer.calibration.v1"
REQUIRED_OUTPUTS = (
    "product/result.json",
    "product/trajectory.h5",
    "product/audit.json",
    "product/observations.json",
)

DEPENDENCY_SPECS: dict[str, dict[str, Any]] = {
    "prepared_matrix": {
        "path": Path("campaigns/core-v1/cfd/prepared/F1_H1_qualification/prepared-matrix.json"),
        "schema": MATRIX_SCHEMA,
        "role": "current F1 prepared matrix metadata",
    },
    "jobs_manifest": {
        "path": Path("campaigns/core-v1/cfd/f1-reference-qualification-jobs.json"),
        "schema": JOBS_SCHEMA,
        "role": "current F1 prepared-only job manifest",
    },
    "qualification_design": {
        "path": Path("campaigns/core-v1/cfd/f1-reference-qualification-design.json"),
        "schema": DESIGN_SCHEMA,
        "role": "current F1 Definition and observer metadata",
    },
    "observer_calibration": {
        "path": Path("campaigns/core-v1/cfd/f1-observer-calibration.json"),
        "schema": CALIBRATION_SCHEMA,
        "role": "current manufactured observer calibration metadata",
    },
}

BLOCKER_CODES = (
    "admission_envelope_absent",
    "prepared_rows_have_no_runtime_admission_receipt",
    "external_source_identity_attestation_absent",
    "runtime_observer_instance_unattested",
    "terminal_output_contract_not_closed",
    "fresh_root_execution_authority_absent",
)

AUTHORIZATION = {
    "diagnostic_only": True,
    "prepared_to_runtime_admitted": False,
    "launch_admitted": False,
    "execution_authorized": False,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
    "registry_eligible": False,
}

MUTATIONS = {
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "queue_mutation": 0,
    "registry_mutation": 0,
}

READ_POLICY = {
    "bounded_json_allowlist_only": True,
    "max_json_bytes": MAX_JSON_BYTES,
    "nested_artifact_paths_followed": False,
    "prepared_cell_json_opened": False,
    "runtime_result_audit_observation_trajectory_opened": False,
    "xml_or_native_input_opened": False,
    "solver_worker_native_gpu_queue": False,
    "registry_ledger_denominator_gate_plan_write": False,
}

SIDE_EFFECTS = {
    "bounded_json_inputs_opened": True,
    "prepared_cell_json_opened": False,
    "runtime_artifacts_opened": False,
    "production_hdf5_opened": False,
    "production_bi4_opened": False,
    "solver_started": False,
    "worker_started": False,
    "native_started": False,
    "gpu_started": False,
    "queue_started": False,
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "registry_mutation": 0,
}

PROHIBITED_OPERATIONS = (
    "nested_prepared_or_runtime_artifact_path_follow_or_open",
    "production_hdf5_bi4_trajectory_read_or_hash",
    "xml_native_or_solver_input_execution",
    "solver_worker_native_gpu_queue_start",
    "caller_claim_promoted_to_trusted_root_or_execution_authority",
    "registry_ledger_denominator_gate_plan_completion_mutation",
    "preparation_promoted_to_formal_T1_T2_or_credit",
)

REQUEST_KEYS = frozenset(
    {
        "schema",
        "request_id",
        "boundary_id",
        "scope_id",
        "prepared_revision",
        "matrix_sha256",
        "design_sha256",
        "observer_binding",
        "source_identity",
        "rows",
        "terminal_contract",
        "authorization",
    }
)
OBSERVER_KEYS = frozenset(
    {"revision_id", "code_sha256", "observable_names_sha256", "runtime_instance_attested"}
)
SOURCE_KEYS = frozenset(
    {
        "definition_sha256",
        "core_manifest_sha256",
        "known_inputs_sha256",
        "solver_binary_sha256",
        "runtime_identity_sha256",
        "per_cell_source_hashes",
        "trusted_root_attested",
    }
)
ROW_KEYS = frozenset(
    {"index", "case_id", "prepared_path_metadata", "prepared_row_sha256", "job_id", "required_outputs", "namespace_id"}
)
TERMINAL_KEYS = frozenset(
    {"required_outputs", "terminal_evidence_schema", "missing_outputs_are_failure", "no_survivor_renormalization"}
)
AUTHORIZATION_KEYS = frozenset({"fresh_root_review", "execution_authorized"})


class AdmissionBoundaryError(ValueError):
    """A bounded input or non-authorizing admission contract is invalid."""


def _fail(message: str) -> None:
    raise AdmissionBoundaryError(f"fail-closed: {message}")


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
    # Normalize lexically only.  Resolving symlinks here would hide a symlink
    # component before _assert_no_symlink_components() can reject it.
    path = Path(os.path.abspath(os.fspath(path)))
    try:
        path.relative_to(root)
    except ValueError:
        _fail(f"JSON dependency escapes root: {value}")
    if any(part in {".", ".."} for part in Path(value).parts):
        _fail(f"non-canonical JSON dependency path: {value}")
    if path.suffix.lower() != ".json":
        _fail(f"non-JSON dependency rejected before open: {value}")
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
            raise AdmissionBoundaryError(f"fail-closed: cannot inspect dependency path {path}") from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"symlink dependency component rejected: {path}")


def _read_bounded_json(root: Path, value: str | Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    path = _safe_json_path(root, value)
    _assert_no_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except (FileNotFoundError, OSError) as error:
        raise AdmissionBoundaryError(f"fail-closed: JSON dependency is unavailable: {_display_path(root, path)}") from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"JSON dependency is not a single-link regular file: {_display_path(root, path)}")
        if before.st_size <= 0 or before.st_size > MAX_JSON_BYTES:
            _fail(f"JSON dependency exceeds bounded limit: {_display_path(root, path)}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(64 * 1024, remaining))
            if not block:
                _fail(f"JSON dependency was truncated while read: {_display_path(root, path)}")
            chunks.append(block)
            remaining -= len(block)
        if os.read(descriptor, 1) != b"":
            _fail(f"JSON dependency grew while read: {_display_path(root, path)}")
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named):
            _fail(f"JSON dependency changed while read: {_display_path(root, path)}")
        raw = b"".join(chunks)
    except AdmissionBoundaryError:
        raise
    except OSError as error:
        raise AdmissionBoundaryError(f"fail-closed: JSON dependency read failed: {path}") from error
    finally:
        os.close(descriptor)

    try:
        value_obj = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except AdmissionBoundaryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise AdmissionBoundaryError(f"fail-closed: invalid strict JSON dependency: {path}") from error
    if type(value_obj) is not dict:
        _fail(f"JSON dependency must be an object: {_display_path(root, path)}")
    _check_finite(value_obj, role)
    return value_obj, {
        "role": role,
        "path": _display_path(root, path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_opened": True,
        "nested_artifact_paths_followed": False,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _require_text(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} must be a non-empty string")
    return value


def _require_sha256(value: Any, label: str) -> str:
    _require(type(value) is str and len(value) == 64 and all(char in SHA256_HEX for char in value), f"{label} is not SHA-256")
    return value


def _canonical_digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_dependencies(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    root = root.resolve()
    payloads: dict[str, dict[str, Any]] = {}
    references: dict[str, dict[str, Any]] = {}
    for key, spec in DEPENDENCY_SPECS.items():
        payload, reference = _read_bounded_json(root, spec["path"], role=spec["role"])
        _require(payload.get("schema") == spec["schema"], f"{key} schema drift")
        payloads[key] = payload
        references[key] = {**reference, "expected_schema": spec["schema"]}
    return payloads, references


def _validate_prepared_context(
    payloads: Mapping[str, Mapping[str, Any]], references: Mapping[str, Mapping[str, Any]], root: Path = LAB_ROOT
) -> dict[str, Any]:
    matrix = payloads["prepared_matrix"]
    _require(matrix.get("revision_id") == PREPARED_REVISION, "prepared matrix revision drift")
    _require(matrix.get("complete") is True, "prepared matrix is not complete")
    _require(matrix.get("qualification_claim") == "none", "prepared matrix qualification promotion")
    _require(type(matrix.get("design_sha256")) is str, "prepared matrix design digest missing")
    design_sha256 = _require_sha256(matrix["design_sha256"], "prepared matrix design_sha256")
    cells = matrix.get("cells")
    _require(type(cells) is list and len(cells) == EXPECTED_CELLS, "prepared matrix row count drift")

    jobs = payloads["jobs_manifest"]
    _require(jobs.get("revision_id") == PREPARED_REVISION, "jobs revision drift")
    _require(jobs.get("job_count") == EXPECTED_CELLS, "jobs denominator drift")
    _require(jobs.get("execution_status") == "prepared_only; canary gate required before qualification", "jobs are not prepared-only")
    _require(jobs.get("qualification_claim") == "none", "jobs qualification promotion")
    _require(jobs.get("design_sha256") == design_sha256, "matrix/job design digest drift")
    _require(jobs.get("matrix_sha256") == references["prepared_matrix"]["sha256"], "job matrix raw digest drift")
    jobs_rows = jobs.get("jobs")
    _require(type(jobs_rows) is list and len(jobs_rows) == EXPECTED_CELLS, "jobs row count drift")

    design = payloads["qualification_design"]
    _require(design.get("family") == "F1", "Definition family drift")
    _require(design.get("scope_id") == SCOPE_ID, "Definition scope drift")
    _require(design.get("revision_id") == PREPARED_REVISION, "Definition revision drift")
    _require(design.get("candidate_status") == "pre_registered_unqualified", "Definition status promotion")
    _require(design.get("cell_count") == EXPECTED_CELLS and type(design.get("cells")) is list, "Definition denominator drift")
    _require(len(design["cells"]) == EXPECTED_CELLS and design.get("qualification_claim") == "none", "Definition claim drift")
    _require(type(design.get("observer")) is dict, "Definition observer missing")
    _require(design["observer"].get("revision_id") == OBSERVER_REVISION, "Definition observer revision drift")

    calibration = payloads["observer_calibration"]
    _require(calibration.get("family") == "F1", "observer calibration family drift")
    _require(calibration.get("revision_id") == OBSERVER_REVISION, "observer calibration revision drift")
    _require(calibration.get("passed") is True, "observer calibration pass drift")
    _require(calibration.get("qualification_claim") == "none; manufactured observer calibration", "observer calibration promotion")
    observer_code_sha256 = _require_sha256(calibration.get("observer_code_sha256"), "observer_code_sha256")
    observable_names = design["observer"].get("observable_names")
    _require(type(observable_names) is list and observable_names and all(type(item) is str for item in observable_names), "observer observable layout drift")
    observable_names_sha256 = _canonical_digest({"observable_names": observable_names})

    rows: list[dict[str, Any]] = []
    for index, (cell, job, design_cell) in enumerate(zip(cells, jobs_rows, design["cells"], strict=True)):
        _require(type(cell) is dict and cell.get("index") == index, f"prepared row index drift at {index}")
        _require(cell.get("preflight_pass") is True and cell.get("static_quality_pass") is True and cell.get("mass_gate_pass") is True, f"prepared row gate drift at {index}")
        case_id = _require_text(cell.get("case_id"), f"prepared row case_id[{index}]")
        prepared_path = _require_text(cell.get("prepared"), f"prepared row path[{index}]")
        _require(type(job) is dict and job.get("index") == index, f"job index drift at {index}")
        _require(job.get("job_id") == f"f1-h1-qualification-cell-{index:02d}", f"job id drift at {index}")
        _require(job.get("prepared") == prepared_path, f"prepared/job path binding drift at {index}")
        required_outputs = job.get("required_outputs")
        _require(required_outputs == list(REQUIRED_OUTPUTS), f"runtime output contract drift at {index}")
        _require(type(design_cell) is dict and design_cell.get("case_id") == case_id, f"Definition/prepared case binding drift at {index}")
        _require(design_cell.get("qualified") is False and design_cell.get("qualification_claim") == "none", f"Definition row promotion at {index}")
        rows.append(
            {
                "index": index,
                "case_id": case_id,
                "prepared_path_metadata": _display_path(root, Path(prepared_path)),
                "prepared_row_sha256": _canonical_digest(cell),
                "job_id": job["job_id"],
                "required_outputs": list(REQUIRED_OUTPUTS),
                "runtime_receipt_required": True,
                "prepared_cell_json_opened": False,
                "runtime_artifacts_opened": False,
            }
        )

    return {
        "scope_id": SCOPE_ID,
        "prepared_revision": PREPARED_REVISION,
        "prepared_rows": EXPECTED_CELLS,
        "matrix_sha256": references["prepared_matrix"]["sha256"],
        "design_sha256": design_sha256,
        "observer_revision": OBSERVER_REVISION,
        "observer_code_sha256": observer_code_sha256,
        "observable_names_sha256": observable_names_sha256,
        "rows": rows,
    }


def validate_admission_request(request: Mapping[str, Any], prepared_context: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a future non-authorizing request without trusting it.

    The return value is an observation only.  Even a shape-valid request is
    never a launch authorization because source-root and runtime attestation
    must come from an external trusted authority, not from this JSON envelope.
    """

    _require(type(request) is dict and set(request) == REQUEST_KEYS, "admission envelope fields differ")
    _require(request.get("schema") == REQUEST_SCHEMA, "admission envelope schema drift")
    _require(request.get("boundary_id") == BOUNDARY_ID, "admission boundary drift")
    _require(request.get("scope_id") == prepared_context["scope_id"], "admission scope drift")
    _require(request.get("prepared_revision") == prepared_context["prepared_revision"], "admission prepared revision drift")
    _require(request.get("matrix_sha256") == prepared_context["matrix_sha256"], "admission matrix digest drift")
    _require(request.get("design_sha256") == prepared_context["design_sha256"], "admission design digest drift")
    _require_text(request.get("request_id"), "request_id")

    observer = request.get("observer_binding")
    _require(type(observer) is dict and set(observer) == OBSERVER_KEYS, "observer binding fields differ")
    _require(observer.get("revision_id") == prepared_context["observer_revision"], "observer binding revision drift")
    _require(observer.get("code_sha256") == prepared_context["observer_code_sha256"], "observer code digest drift")
    _require(observer.get("observable_names_sha256") == prepared_context["observable_names_sha256"], "observer layout digest drift")
    _require(observer.get("runtime_instance_attested") is False, "caller cannot attest runtime observer instance")

    source = request.get("source_identity")
    _require(type(source) is dict and set(source) == SOURCE_KEYS, "source identity fields differ")
    for key in ("definition_sha256", "core_manifest_sha256", "known_inputs_sha256", "solver_binary_sha256", "runtime_identity_sha256"):
        _require_sha256(source.get(key), f"source identity {key}")
    per_cell = source.get("per_cell_source_hashes")
    _require(type(per_cell) is list and len(per_cell) == EXPECTED_CELLS, "per-cell source hash count drift")
    for index, item in enumerate(per_cell):
        _require(type(item) is dict and set(item) == {"index", "sha256"}, f"per-cell source hash fields differ at {index}")
        _require(item.get("index") == index, f"per-cell source hash index drift at {index}")
        _require_sha256(item.get("sha256"), f"per-cell source hash[{index}]")
    _require(source.get("trusted_root_attested") is False, "caller cannot attest trusted source root")

    rows = request.get("rows")
    _require(type(rows) is list and len(rows) == EXPECTED_CELLS, "admission row count drift")
    expected_rows = prepared_context["rows"]
    for index, (row, expected) in enumerate(zip(rows, expected_rows, strict=True)):
        _require(type(row) is dict and set(row) == ROW_KEYS, f"admission row fields differ at {index}")
        for key in ("index", "case_id", "prepared_row_sha256", "job_id"):
            _require(row.get(key) == expected[key], f"admission row binding drift at {index}: {key}")
        _require(row.get("prepared_path_metadata") == expected["prepared_path_metadata"], f"admission path metadata drift at {index}")
        _require(row.get("required_outputs") == list(REQUIRED_OUTPUTS), f"admission outputs drift at {index}")
        namespace_id = _require_text(row.get("namespace_id"), f"namespace_id[{index}]")
        _require("/" not in namespace_id and "\\" not in namespace_id and namespace_id not in {".", ".."}, f"namespace path-like token at {index}")

    terminal = request.get("terminal_contract")
    _require(type(terminal) is dict and set(terminal) == TERMINAL_KEYS, "terminal contract fields differ")
    _require(terminal.get("required_outputs") == list(REQUIRED_OUTPUTS), "terminal required outputs drift")
    _require(terminal.get("terminal_evidence_schema") == "core.f1.runtime.terminal_evidence.v1", "terminal evidence schema drift")
    _require(terminal.get("missing_outputs_are_failure") is True, "missing-output fail-closed policy drift")
    _require(terminal.get("no_survivor_renormalization") is True, "survivor renormalization policy drift")

    authorization = request.get("authorization")
    _require(type(authorization) is dict and set(authorization) == AUTHORIZATION_KEYS, "request authorization fields differ")
    _require(authorization.get("fresh_root_review") is False, "caller cannot declare fresh root review")
    _require(authorization.get("execution_authorized") is False, "caller cannot declare execution authorization")

    return {
        "contract_valid": True,
        "prepared_rows_bound": EXPECTED_CELLS,
        "runtime_observer_instance_attested": False,
        "trusted_source_root_attested": False,
        "terminal_evidence_present": False,
        "fresh_root_review": False,
        "execution_authorized": False,
        "launch_admitted": False,
        "formal": False,
        "T1_numerical": False,
        "credit": 0,
    }


def _blockers() -> list[dict[str, str]]:
    details = {
        "admission_envelope_absent": "no future prepared-to-runtime admission envelope is present; the verifier has no request to authorize",
        "prepared_rows_have_no_runtime_admission_receipt": "the 15 prepared row bindings declare required runtime products only as metadata; no runtime admission receipt is available",
        "external_source_identity_attestation_absent": "Core manifest, known_inputs, solver binary, runtime identity, and per-cell source hashes have no independently trusted root attestation",
        "runtime_observer_instance_unattested": "manufactured observer calibration is not a runtime observer instance binding and cannot authorize a worker",
        "terminal_output_contract_not_closed": "result/audit/observations/trajectory terminal evidence is not present at this pre-run boundary; missing output must remain fail-closed",
        "fresh_root_execution_authority_absent": "fresh root review and execution authorization are intentionally absent; caller JSON cannot mint either authority",
    }
    return [{"code": code, "severity": "high", "detail": details[code]} for code in BLOCKER_CODES]


def build_report(root: str | Path = LAB_ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    payloads, references = _load_dependencies(root)
    prepared_context = _validate_prepared_context(payloads, references, root)
    report = {
        "schema": REPORT_SCHEMA,
        "record_id": RECORD_ID,
        "created_at": OBSERVED_AT_UTC,
        "scope_id": SCOPE_ID,
        "status": "blocked_fail_closed",
        "decision": "bounded_f1_prepared_to_runtime_admission_boundary_projection",
        "boundary": {
            "boundary_id": BOUNDARY_ID,
            "input_class": "prepared_metadata_only",
            "prepared_rows": EXPECTED_CELLS,
            "runtime_rows_admitted": 0,
            "admission_envelope_present": False,
            "admission_contract_valid": False,
            "prepared_row_bindings_derived": True,
            "runtime_receipts_present": False,
            "nested_artifact_paths_followed": False,
        },
        "read_policy": dict(READ_POLICY),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "dependencies": references,
        "prepared_context": prepared_context,
        "admission": {
            "request_schema": REQUEST_SCHEMA,
            "request_present": False,
            "request_contract_valid": False,
            "prepared_rows_bound": 0,
            "source_identity_attested": False,
            "runtime_observer_instance_attested": False,
            "terminal_evidence_present": False,
            "fresh_root_review": False,
            "execution_authorized": False,
            "launch_admitted": False,
            "formal": False,
            "T1_numerical": False,
            "credit": 0,
        },
        "checks": {
            "prepared_matrix_contract_bound": True,
            "jobs_manifest_contract_bound": True,
            "definition_observer_revision_bound": True,
            "observer_calibration_not_promoted": True,
            "matrix_job_row_bindings_exact": True,
            "required_runtime_outputs_declared": True,
            "prepared_cell_json_not_opened": True,
            "runtime_artifacts_not_opened": True,
            "admission_envelope_present": False,
            "source_identity_attested": False,
            "runtime_observer_instance_attested": False,
            "terminal_evidence_present": False,
            "fresh_root_review": False,
            "execution_authorized": False,
            "formal": False,
            "T1_numerical": False,
            "qualification_credit_added": False,
        },
        "blockers": _blockers(),
        "authorization": dict(AUTHORIZATION),
        "mutations": dict(MUTATIONS),
        "side_effects": dict(SIDE_EFFECTS),
        "validation": {
            "contract_valid": True,
            "blocked": True,
            "blockers_nonempty": True,
            "prepared_not_promoted": True,
            "caller_cannot_mint_authority": True,
            "observer_calibration_not_promoted": True,
            "formal_not_promoted": True,
            "credit_zero": True,
        },
        "next_safe_action": (
            "先由独立 trusted root 发布与当前 Definition/observer/source closure 绑定的非授权 admission envelope；"
            "再由外部 authority verifier 认证 source/runtime identity 和 fresh namespace。此边界本身只能检查"
            "prepared row binding 与 output contract，不能把 caller JSON 转成 execution authorization，也不能启动任何 workload。"
        ),
    }
    validate_report(report)
    return report


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "record_id", "created_at", "scope_id", "status", "decision", "boundary", "read_policy",
        "prohibited_operations", "dependencies", "prepared_context", "admission", "checks", "blockers",
        "authorization", "mutations", "side_effects", "validation", "next_safe_action",
    }
    _require(type(report) is dict and set(report) == required, "report fields differ")
    _require(report["schema"] == REPORT_SCHEMA and report["record_id"] == RECORD_ID, "report identity drift")
    _require(report["created_at"] == OBSERVED_AT_UTC and report["scope_id"] == SCOPE_ID, "report scope/time drift")
    _require(report["status"] == "blocked_fail_closed" and report["decision"] == "bounded_f1_prepared_to_runtime_admission_boundary_projection", "report status drift")
    _require(report["read_policy"] == READ_POLICY, "read policy drift")
    _require(report["prohibited_operations"] == list(PROHIBITED_OPERATIONS), "prohibited operation inventory drift")
    _require(report["authorization"] == AUTHORIZATION, "authorization promotion detected")
    _require(report["mutations"] == MUTATIONS and report["side_effects"] == SIDE_EFFECTS, "mutation/side-effect boundary drift")

    boundary = report["boundary"]
    _require(boundary == {
        "boundary_id": BOUNDARY_ID,
        "input_class": "prepared_metadata_only",
        "prepared_rows": EXPECTED_CELLS,
        "runtime_rows_admitted": 0,
        "admission_envelope_present": False,
        "admission_contract_valid": False,
        "prepared_row_bindings_derived": True,
        "runtime_receipts_present": False,
        "nested_artifact_paths_followed": False,
    }, "boundary promotion or drift")

    dependencies = report["dependencies"]
    _require(type(dependencies) is dict and set(dependencies) == set(DEPENDENCY_SPECS), "dependency inventory drift")
    for key, spec in DEPENDENCY_SPECS.items():
        ref = dependencies[key]
        _require(ref.get("path") == spec["path"].as_posix(), f"dependency path drift: {key}")
        _require(ref.get("expected_schema") == spec["schema"] and ref.get("role") == spec["role"], f"dependency contract drift: {key}")
        _require(ref.get("content_opened") is True and ref.get("nested_artifact_paths_followed") is False, f"dependency access drift: {key}")
        _require_sha256(ref.get("sha256"), f"dependency digest: {key}")

    context = report["prepared_context"]
    _require(context.get("scope_id") == SCOPE_ID and context.get("prepared_revision") == PREPARED_REVISION, "prepared context identity drift")
    _require(context.get("prepared_rows") == EXPECTED_CELLS, "prepared context denominator drift")
    _require_sha256(context.get("matrix_sha256"), "prepared context matrix digest")
    _require_sha256(context.get("design_sha256"), "prepared context design digest")
    _require(context.get("observer_revision") == OBSERVER_REVISION, "prepared context observer drift")
    _require_sha256(context.get("observer_code_sha256"), "prepared context observer code digest")
    _require_sha256(context.get("observable_names_sha256"), "prepared context observer layout digest")
    rows = context.get("rows")
    _require(type(rows) is list and len(rows) == EXPECTED_CELLS, "prepared context rows drift")
    for index, row in enumerate(rows):
        _require(type(row) is dict, f"prepared context row type drift at {index}")
        _require(row.get("index") == index and row.get("job_id") == f"f1-h1-qualification-cell-{index:02d}", f"prepared context row identity drift at {index}")
        _require_text(row.get("case_id"), f"prepared context case id[{index}]")
        _require_text(row.get("prepared_path_metadata"), f"prepared context path[{index}]")
        _require_sha256(row.get("prepared_row_sha256"), f"prepared context row digest[{index}]")
        _require(row.get("required_outputs") == list(REQUIRED_OUTPUTS), f"prepared context output drift at {index}")
        _require(row.get("runtime_receipt_required") is True and row.get("prepared_cell_json_opened") is False and row.get("runtime_artifacts_opened") is False, f"prepared context access drift at {index}")

    admission = report["admission"]
    _require(admission == {
        "request_schema": REQUEST_SCHEMA,
        "request_present": False,
        "request_contract_valid": False,
        "prepared_rows_bound": 0,
        "source_identity_attested": False,
        "runtime_observer_instance_attested": False,
        "terminal_evidence_present": False,
        "fresh_root_review": False,
        "execution_authorized": False,
        "launch_admitted": False,
        "formal": False,
        "T1_numerical": False,
        "credit": 0,
    }, "admission promotion or drift")

    checks = report["checks"]
    _require(type(checks) is dict and all(type(value) is bool for value in checks.values()), "check projection is not boolean")
    for key in (
        "prepared_matrix_contract_bound", "jobs_manifest_contract_bound", "definition_observer_revision_bound",
        "observer_calibration_not_promoted", "matrix_job_row_bindings_exact", "required_runtime_outputs_declared",
        "prepared_cell_json_not_opened", "runtime_artifacts_not_opened",
    ):
        _require(checks.get(key) is True, f"positive boundary check lost: {key}")
    for key in (
        "admission_envelope_present", "source_identity_attested", "runtime_observer_instance_attested",
        "terminal_evidence_present", "fresh_root_review", "execution_authorized", "formal", "T1_numerical",
        "qualification_credit_added",
    ):
        _require(checks.get(key) is False, f"boundary gate promoted: {key}")

    blockers = report["blockers"]
    _require(type(blockers) is list and [item.get("code") for item in blockers] == list(BLOCKER_CODES), "blocker inventory drift")
    _require(all(item.get("severity") == "high" and item.get("detail") for item in blockers), "blocker detail drift")
    _require(report["validation"] == {
        "contract_valid": True,
        "blocked": True,
        "blockers_nonempty": True,
        "prepared_not_promoted": True,
        "caller_cannot_mint_authority": True,
        "observer_calibration_not_promoted": True,
        "formal_not_promoted": True,
        "credit_zero": True,
    }, "validation projection drift")
    _require_text(report["next_safe_action"], "next_safe_action")
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
    context = report["prepared_context"]
    return f"""# F1 prepared → runtime admission boundary V1

状态：`{report['status']}`。

这是一个比 readiness bridge 更窄的接口组件：它只从当前 F1 prepared matrix、prepared-only job manifest、Definition 和 observer calibration 的 bounded JSON 元数据推导 15 行 row binding，并定义未来 admission envelope 的严格字段边界。不打开 cell `prepared.json`、result/audit/observations/trajectory，不跟随嵌套路径，不启动 GenCase/native/solver/worker/GPU/queue，也不修改 PLAN、registry、ledger、denominator、gate 或 completion。

## 当前接口投影

- boundary：`{report['boundary']['boundary_id']}`；prepared rows=`{context['prepared_rows']}`，runtime rows admitted=`0`。
- matrix/design digest 和 observer revision/code/layout digest 已从 bounded metadata 绑定；这不是 trusted source/runtime attestation。
- 15 个 `prepared_row_sha256` 已派生用于未来逐行 admission binding；当前没有 admission envelope、runtime receipt、trusted root review 或 execution authorization。
- 所有 caller-supplied authority 均拒绝晋级；`formal=false`、`T1=false`、`credit=0`。

## 未闭合的边界条件

{chr(10).join(f"- `{item['code']}`：{item['detail']}" for item in report['blockers'])}

此提交只建立可复用的 fail-closed contract checker。即使未来 envelope 形状完整，本组件也不会把 JSON 中的布尔声明当作 trusted root、runtime observer 或 execution authority；这些必须由独立外部 authority verifier 提供。

机器报告：`F1-PREPARED-RUNTIME-ADMISSION-BOUNDARY-V1-2026-09-29.json`。
"""


def write_outputs(report: Mapping[str, Any], output: str | Path, zh_output: str | Path) -> tuple[Path, Path]:
    validate_report(report)
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    zh_payload = _zh_report(report).encode("utf-8")
    return _write_immutable(output, payload), _write_immutable(zh_output, zh_payload)


def verify_report(path: str | Path) -> dict[str, Any]:
    value, _reference = _read_bounded_json(LAB_ROOT, path, role="checked-in F1 admission boundary report")
    validate_report(value)
    expected = build_report()
    if value != expected:
        raise AdmissionBoundaryError("fail-closed: checked-in F1 admission boundary report differs from current metadata")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zh-output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(args.root)
    write_outputs(report, args.output, args.zh_output)
    print(json.dumps({"status": report["status"], "report": str(args.output)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
