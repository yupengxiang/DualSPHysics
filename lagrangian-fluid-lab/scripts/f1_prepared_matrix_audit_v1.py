#!/usr/bin/env python3
"""Independently audit the prepared F1 15-cell input matrix.

This auditor is intentionally preparation-only.  It re-reads the bounded F1
matrix and its per-cell job JSON contracts, re-hashes only the prepared JSON
inputs, and checks the fixed 15-row input/denominator identity.  Paths inside
prepared JSON (including solver, decoder, BI4, HDF5, trajectory, and other
nested artifacts) are metadata and are never followed, opened, stat'ed, or
hashed.

The result is diagnostic evidence, not a runtime receipt.  The auditor never
launches or controls a solver, worker, native decoder, GPU, queue, registry,
ledger, denominator, gate, or PLAN, and it never grants formal, T1, T2, or
qualification credit.
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
EXPECTED_CELLS = 15
MAX_JSON_BYTES = 256 * 1024
SHA256_HEX = frozenset("0123456789abcdef")
MATRIX_SCHEMA = "core.f1.qualification.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REPORT_SCHEMA = "core.f1.prepared_matrix_audit.v1"
DEFAULT_MATRIX = LAB_ROOT / "campaigns/core-v1/cfd/prepared/F1_H1_qualification/prepared-matrix.json"
DEFAULT_JOBS = LAB_ROOT / "campaigns/core-v1/cfd/f1-reference-qualification-jobs.json"


class AuditError(ValueError):
    """Raised when an F1 preparation contract is invalid or unsafe to read."""


def _fail(message: str) -> None:
    raise AuditError(f"fail-closed: {message}")


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


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise AuditError(f"fail-closed: cannot inspect path {path}") from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"symlink component rejected: {path}")


def _safe_json_path(base: Path, value: str | Path, *, role: str) -> Path:
    raw = Path(value)
    if any(part in {"", ".", ".."} for part in raw.parts[1:]):
        _fail(f"non-canonical {role} path: {value}")
    path = raw if raw.is_absolute() else base / raw
    path = Path(os.path.abspath(os.fspath(path)))
    if path.suffix.lower() != ".json":
        _fail(f"non-JSON {role} rejected: {value}")
    _assert_no_symlink_components(path)
    return path


def _under(path: Path, root: Path, *, role: str) -> Path:
    path = Path(os.path.abspath(os.fspath(path)))
    root = Path(os.path.abspath(os.fspath(root)))
    try:
        path.relative_to(root)
    except ValueError as error:
        raise AuditError(f"fail-closed: {role} escapes allowed root: {path}") from error
    _assert_no_symlink_components(path)
    return path


def _read_bounded_json(path: Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _assert_no_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except (FileNotFoundError, OSError) as error:
        raise AuditError(f"fail-closed: {role} is unavailable: {path}") from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{role} is not a regular file: {path}")
        if before.st_size > MAX_JSON_BYTES:
            _fail(f"{role} exceeds bounded JSON limit: {path}")
        chunks: list[bytes] = []
        remaining = MAX_JSON_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if _identity(before) != _identity(after):
            _fail(f"{role} changed while being read: {path}")
        raw = b"".join(chunks)
        if len(raw) > MAX_JSON_BYTES:
            _fail(f"{role} exceeds bounded JSON limit: {path}")
    except OSError as error:
        raise AuditError(f"fail-closed: cannot read {role}: {path}") from error
    finally:
        os.close(descriptor)

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditError(f"fail-closed: invalid JSON in {role}: {path}") from error
    if type(value) is not dict:
        _fail(f"{role} must be a JSON object: {path}")
    _check_finite(value, role)
    return value, {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _require_sha256(value: Any, label: str) -> str:
    _require(type(value) is str and len(value) == 64 and all(char in SHA256_HEX for char in value), f"{label} is not a SHA-256 digest")
    return value


def _require_false_or_zero(payload: Mapping[str, Any], key: str, *, label: str) -> None:
    if key not in payload:
        return
    value = payload[key]
    _require(value is False or (type(value) is int and value == 0), f"{label}.{key} claims execution or mutation")


def _prepared_path(matrix_root: Path, value: Any, *, label: str) -> Path:
    _require(type(value) is str, f"{label} prepared path missing")
    path = _safe_json_path(matrix_root, value, role=f"{label} prepared")
    return _under(path, matrix_root, role=f"{label} prepared")


def _job_path(jobs_root: Path, value: Any, *, label: str) -> Path:
    _require(type(value) is str, f"{label} job path missing")
    path = _safe_json_path(jobs_root, value, role=f"{label} job")
    return _under(path, jobs_root, role=f"{label} job")


def _validate_matrix(matrix: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    _require(matrix.get("schema") == MATRIX_SCHEMA, "unexpected F1 matrix schema")
    _require(matrix.get("revision_id") == "F1_H1_geometry_observer_qualification_v1", "F1 matrix revision drift")
    _require(matrix.get("complete") is True, "F1 matrix is not complete")
    _require(matrix.get("qualification_claim") == "none", "F1 matrix qualification claim drift")
    _require(matrix.get("cell_count", EXPECTED_CELLS) in {EXPECTED_CELLS, None}, "F1 matrix cell count drift")
    rows = matrix.get("cells")
    _require(type(rows) is list and len(rows) == EXPECTED_CELLS, "F1 matrix does not close 15 cells")
    for index, row in enumerate(rows):
        _require(type(row) is dict, f"F1 matrix row {index} is not an object")
        _require(row.get("index") == index, f"F1 matrix row index drift at {index}")
        _require(type(row.get("case_id")) is str and row["case_id"], f"F1 matrix case id missing at {index}")
        _require(row.get("preflight_pass") is True, f"F1 matrix preflight drift at {index}")
        _require(row.get("static_quality_pass") is True, f"F1 matrix static-quality drift at {index}")
        _require(row.get("mass_gate_pass") is True, f"F1 matrix mass gate drift at {index}")
        _require(type(row.get("design_cell")) is str and row["design_cell"], f"F1 matrix design cell missing at {index}")
        _require(type(row.get("dp_m")) in {int, float} and type(row.get("dp_m")) is not bool, f"F1 matrix dp missing at {index}")
        _require(type(row.get("prepared")) is str and Path(row["prepared"]).suffix.lower() == ".json", f"F1 matrix prepared path missing at {index}")
    for key in ("solver_invoked", "worker_started", "native_started", "gpu_invoked"):
        _require_false_or_zero(matrix, key, label="F1 matrix")
    for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation"):
        _require_false_or_zero(matrix, key, label="F1 matrix")
    return rows


def _validate_prepared_payload(
    prepared: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    index: int,
) -> None:
    _require(prepared.get("schema") == "core.cfd.v1", f"prepared schema drift at {index}")
    config = prepared.get("config")
    _require(type(config) is dict, f"prepared config missing at {index}")
    _require(config.get("family") == "F1", f"prepared family drift at {index}")
    _require(config.get("stage") == "qualification", f"prepared stage drift at {index}")
    _require(config.get("qualification_claim") == "none", f"prepared config claim drift at {index}")
    _require(config.get("qualified") is False, f"prepared qualification promotion at {index}")
    _require(config.get("case_id") == row.get("case_id"), f"prepared case id drift at {index}")
    _require(config.get("design_cell") == row.get("design_cell"), f"prepared design cell drift at {index}")
    parameter = config.get("parameter")
    _require(type(parameter) is dict, f"prepared parameter missing at {index}")
    _require(parameter.get("q") == row.get("q"), f"prepared q drift at {index}")
    _require(config.get("dp_m") == row.get("dp_m"), f"prepared dp drift at {index}")
    _require(prepared.get("preflight_pass") is True, f"prepared preflight drift at {index}")
    _require(type(prepared.get("qualification_claim")) is str and prepared["qualification_claim"].startswith("none"), f"prepared claim missing at {index}")
    native = prepared.get("native_initial")
    _require(type(native) is dict and native.get("initial_state_pass") is True, f"prepared native preflight drift at {index}")
    mass = prepared.get("mass_preflight")
    _require(type(mass) is dict and mass.get("mass_gate_pass") is True, f"prepared mass gate drift at {index}")
    definition_audit = prepared.get("definition_audit")
    _require(type(definition_audit) is dict and definition_audit.get("mass_rescaling") is False, f"prepared mass-rescaling drift at {index}")
    inputs = prepared.get("inputs")
    _require(type(inputs) is dict, f"prepared input inventory missing at {index}")
    # The inventory is intentionally metadata-only.  Do not follow any of its paths.
    for key in ("solver_binary", "decoder", "generated_prefix", "source_template"):
        _require(type(prepared.get(key)) is str and prepared[key], f"prepared {key} metadata missing at {index}")


def _validate_job_contract(
    job: Mapping[str, Any],
    matrix_row: Mapping[str, Any],
    prepared_path: Path,
    prepared_digest: str,
    *,
    index: int,
) -> None:
    _require(job.get("schema") == JOB_SCHEMA, f"job schema drift at {index}")
    expected_job_id = f"f1-h1-qualification-cell-{index:02d}"
    _require(job.get("job_id") == expected_job_id, f"job id drift at {index}")
    _require(job.get("category") == "qualification", f"job category drift at {index}")
    _require(job.get("qualification_claim") == "none", f"job claim drift at {index}")
    _require(job.get("prepared_case_id") == matrix_row.get("case_id"), f"job case id drift at {index}")
    outputs = job.get("required_outputs")
    _require(type(outputs) is list, f"job output contract missing at {index}")
    for required in ("product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"):
        _require(required in outputs, f"job output contract drift at {index}: {required}")
    input_files = job.get("input_files")
    _require(type(input_files) is list, f"job input contract missing at {index}")
    prepared_entries = [item for item in input_files if isinstance(item, dict) and item.get("path") == str(prepared_path)]
    _require(len(prepared_entries) == 1, f"job prepared input binding is not unique at {index}")
    _require(prepared_entries[0].get("sha256") == prepared_digest, f"job prepared input hash mismatch at {index}")
    validation = job.get("static_validation")
    _require(type(validation) is dict, f"job static validation missing at {index}")
    _require(validation.get("case_id") == matrix_row.get("case_id"), f"job static case id drift at {index}")
    _require(validation.get("static_quality_pass") is True and validation.get("preflight_pass") is True, f"job static validation drift at {index}")
    _require(validation.get("qualification_claim") == "none", f"job static claim drift at {index}")
    for key in ("solver_invoked", "worker_started", "native_started", "gpu_invoked"):
        _require_false_or_zero(job, key, label=f"job {index}")
    for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation", "gate_mutation"):
        _require_false_or_zero(job, key, label=f"job {index}")


def _write_immutable(path: str | Path, payload: bytes) -> Path:
    target = Path(path).absolute()
    if target.suffix.lower() != ".json":
        _fail(f"non-JSON output rejected: {path}")
    _assert_no_symlink_components(target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
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


def validate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "source_report", "jobs_manifest", "family", "revision_id",
        "registered_cell_count", "prepared_cell_count", "failed_cell_count",
        "unattempted_cell_count", "prepared_input_hash_closure", "cells",
        "execution_controls", "formal_runtime_rows", "formal_failed_rows",
        "missing_runtime_rows", "fixed_failure_denominator", "survivor_renormalization",
        "T1_numerical", "T2_macro", "T2_path", "T2", "qualification_credit", "credit",
        "qualification_claim", "scientific_results_present", "read_only_audit",
    }
    if type(report) is not dict or set(report) != required:
        raise AuditError("fail-closed: audit report fields differ")
    _require(report["schema"] == REPORT_SCHEMA, "audit report schema drift")
    _require(report["family"] == "F1", "audit family drift")
    _require(report["revision_id"] == "F1_H1_geometry_observer_qualification_v1", "audit revision drift")
    for key in ("registered_cell_count", "prepared_cell_count"):
        _require(report[key] == EXPECTED_CELLS, f"audit {key} drift")
    for key in ("failed_cell_count", "unattempted_cell_count", "formal_runtime_rows", "formal_failed_rows", "missing_runtime_rows", "qualification_credit", "credit"):
        _require(report[key] == 0 if key in {"failed_cell_count", "unattempted_cell_count", "formal_runtime_rows", "formal_failed_rows", "qualification_credit", "credit"} else report[key] == EXPECTED_CELLS, f"audit {key} drift")
    _require(report["fixed_failure_denominator"] is True, "audit denominator is not fixed")
    _require(report["survivor_renormalization"] is False, "audit survivor renormalization drift")
    for key in ("T1_numerical", "T2_macro", "T2_path", "T2", "scientific_results_present"):
        _require(report[key] is False, f"audit scientific promotion: {key}")
    _require(report["qualification_claim"].startswith("none;"), "audit qualification claim drift")
    _require(report["read_only_audit"] is True, "audit read-only marker drift")
    closure = report["prepared_input_hash_closure"]
    _require(type(closure) is dict, "audit hash closure missing")
    _require(closure == {"required_cells": EXPECTED_CELLS, "verified_cells": EXPECTED_CELLS, "pass": True}, "audit hash closure drift")
    cells = report["cells"]
    _require(type(cells) is list and len(cells) == EXPECTED_CELLS, "audit cells drift")
    _require([cell.get("index") for cell in cells] == list(range(EXPECTED_CELLS)), "audit cell indexes drift")
    _require(all(cell.get("prepared_input_hash_bound") is True for cell in cells), "audit cell hash binding drift")
    controls = report["execution_controls"]
    expected_controls = {
        "preparation_only": True,
        "nested_artifact_paths_followed": False,
        "production_hdf5_opened": False,
        "production_bi4_opened": False,
        "production_trajectory_opened": False,
        "solver_invoked": False,
        "worker_started": False,
        "native_started": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "gate_mutation": 0,
        "plan_mutation": 0,
    }
    _require(controls == expected_controls, "audit execution boundary drift")
    return dict(report)


def audit_matrix(
    matrix_path: str | Path = DEFAULT_MATRIX,
    jobs_manifest_path: str | Path = DEFAULT_JOBS,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """Audit F1 prepared inputs and job metadata without opening runtime artifacts."""

    matrix_path = _safe_json_path(Path.cwd(), matrix_path, role="F1 matrix")
    jobs_manifest_path = _safe_json_path(Path.cwd(), jobs_manifest_path, role="F1 jobs manifest")
    matrix_root = matrix_path.parent
    jobs_root = jobs_manifest_path.parent
    matrix, matrix_ref = _read_bounded_json(matrix_path, role="F1 matrix")
    jobs_manifest, jobs_ref = _read_bounded_json(jobs_manifest_path, role="F1 jobs manifest")
    rows = _validate_matrix(matrix)

    _require(jobs_manifest.get("schema") == "core.cfd.jobs.v1", "unexpected F1 jobs manifest schema")
    _require(jobs_manifest.get("revision_id") == matrix.get("revision_id"), "F1 jobs revision drift")
    _require(jobs_manifest.get("job_count") == EXPECTED_CELLS, "F1 jobs denominator is not 15")
    _require(jobs_manifest.get("execution_status") == "prepared_only; canary gate required before qualification", "F1 jobs execution status drift")
    _require(jobs_manifest.get("qualification_claim") == "none", "F1 jobs qualification claim drift")
    _require(jobs_manifest.get("canary_dependency") == "f1-h1-reference-fullwindow-canary-001", "F1 canary dependency drift")
    _require(jobs_manifest.get("matrix_sha256") == matrix_ref["sha256"], "F1 jobs matrix hash drift")
    job_rows = jobs_manifest.get("jobs")
    _require(type(job_rows) is list and len(job_rows) == EXPECTED_CELLS, "F1 jobs do not close 15 rows")

    checked_cells: list[dict[str, Any]] = []
    for index, (row, job_row) in enumerate(zip(rows, job_rows)):
        _require(type(job_row) is dict and job_row.get("index") == index, f"F1 job manifest row drift at {index}")
        prepared_path = _prepared_path(matrix_root, row.get("prepared"), label=f"matrix row {index}")
        summary_prepared = _prepared_path(matrix_root, job_row.get("prepared"), label=f"job manifest row {index}")
        _require(summary_prepared == prepared_path, f"F1 prepared path binding drift at {index}")
        job_path = _job_path(jobs_root, job_row.get("path"), label=f"job manifest row {index}")
        prepared, prepared_ref = _read_bounded_json(prepared_path, role=f"F1 prepared cell {index}")
        _validate_prepared_payload(prepared, row, index=index)
        job, job_ref = _read_bounded_json(job_path, role=f"F1 job contract {index}")
        _validate_job_contract(job, row, prepared_path, prepared_ref["sha256"], index=index)
        checked_cells.append({
            "index": index,
            "case_id": row["case_id"],
            "design_cell": row["design_cell"],
            "q": row.get("q"),
            "dp_m": row["dp_m"],
            "prepared": prepared_ref,
            "job_contract": job_ref,
            "prepared_input_hash_bound": True,
            "required_runtime_outputs_metadata_only": True,
        })

    report = {
        "schema": REPORT_SCHEMA,
        "source_report": matrix_ref,
        "jobs_manifest": jobs_ref,
        "family": "F1",
        "revision_id": matrix["revision_id"],
        "registered_cell_count": EXPECTED_CELLS,
        "prepared_cell_count": EXPECTED_CELLS,
        "failed_cell_count": 0,
        "unattempted_cell_count": 0,
        "prepared_input_hash_closure": {
            "required_cells": EXPECTED_CELLS,
            "verified_cells": len(checked_cells),
            "pass": len(checked_cells) == EXPECTED_CELLS,
        },
        "cells": checked_cells,
        "execution_controls": {
            "preparation_only": True,
            "nested_artifact_paths_followed": False,
            "production_hdf5_opened": False,
            "production_bi4_opened": False,
            "production_trajectory_opened": False,
            "solver_invoked": False,
            "worker_started": False,
            "native_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "plan_mutation": 0,
        },
        "formal_runtime_rows": 0,
        "formal_failed_rows": 0,
        "missing_runtime_rows": EXPECTED_CELLS,
        "fixed_failure_denominator": True,
        "survivor_renormalization": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "T2": False,
        "qualification_credit": 0,
        "credit": 0,
        "qualification_claim": "none; F1 prepared input closure only; no solver/runtime evidence",
        "scientific_results_present": False,
        "read_only_audit": True,
    }
    validate_report(report)
    if output is not None:
        payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        _write_immutable(output, payload)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--jobs-manifest", type=Path, default=DEFAULT_JOBS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit_matrix(args.matrix, args.jobs_manifest, args.output)
    print(json.dumps({
        "schema": report["schema"],
        "prepared_cell_count": report["prepared_cell_count"],
        "prepared_input_hash_closure": report["prepared_input_hash_closure"],
        "formal_runtime_rows": report["formal_runtime_rows"],
        "T1_numerical": report["T1_numerical"],
        "T2": report["T2"],
        "credit": report["credit"],
        "output": str(args.output) if args.output is not None else None,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
