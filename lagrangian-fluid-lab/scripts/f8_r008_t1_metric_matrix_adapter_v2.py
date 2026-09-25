"""Evaluate frozen R008 15-case metric/comparison gates for v2 case results.

This additive matrix adapter consumes the exact per-case output shape from the
held-FD B/C/D v2 verifier. It validates each result's claimed closure and metric
contract, but does not reopen case bundles or independently authenticate caller
receipts. Native-integrity and final T1 adjudication remain separate gates.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

import numpy as np

from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_bundle_v2
from scripts import f8_r008_native_fluid_table_schema_review_v2 as table_review
from scripts import f8_r008_native_fluid_table_metric_review_v2 as metric_review_v2
from scripts import f8_r008_native_fluid_table_v2 as table_v2
from scripts import f8_r008_per_case_bundle_verifier_v1 as bundle_v1
from scripts import f8_r008_t1_metric_adapter_v1 as metric_v1
from scripts import f8_r008_t1_metric_adapter_review_v1 as metric_v1_review


SCHEMA = "core.cfd.f8.r008_t1_metric_matrix_adapter.v2"
SCOPE_ID = metric_v1.SCOPE_ID
HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
CASE_RESULT_SCHEMA = metric_bundle_v2.SCHEMA
TABLE_SCHEMA = "core.cfd.f8.r008_native_fluid_frame_table.v2"
STAGES = ("B", "C", "D")
MAX_AUDIT_RECEIPT_BYTES = 1024 * 1024
MAX_AUDIT_SOURCE_LOG_BYTES = 256 * 1024 * 1024
SOLVER_TIMESTEP_AUDIT_SCHEMA = "core.cfd.f8.r008_solver_timestep_audit.v2"
SOLVER_TIMESTEP_AUDIT_FIELDS = frozenset({
    "schema", "status", "case_id", "max_solver_dt_s", "checks", "source_log",
})
SOLVER_TIMESTEP_AUDIT_CHECKS = frozenset({"finite_positive_max_step"})
SOLVER_TIMESTEP_SOURCE_LOG_FIELDS = frozenset({"path", "bytes", "sha256"})
CASE_RESULT_FIELDS = frozenset({
    "schema", "case_id", "provenance_chain_references_closed",
    "definition_control_bindings_match_frozen_pack_and_source_bytes",
    "native_fluid_table", "case_metrics", "stage_statuses", "receipt_sha256",
    "manifest_sha256", "native_table_review_receipt_sha256",
    "native_table_review_authenticity", "metric_review_receipt_sha256",
    "metric_review_authenticity", "reviewed_metric_code_sources_match",
    "loaded_module_code_identity_verified", "authorization_authenticity",
    "runtime_environment_assumption", "native_integrity_evaluated",
    "metrics_evaluated", "metric_gates_passed", "readiness_pass",
    "T1_numerical", "qualification_credit",
})


class NativeFluidMetricMatrixError(ValueError):
    """The v2 case-result set does not match the frozen 15-row R008 matrix."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeFluidMetricMatrixError(message)


def _is_integer_zero(value: Any) -> bool:
    return type(value) is int and value == 0


def _single_component(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value)
             and not Path(value).is_absolute()
             and value not in {".", ".."}
             and "/" not in value and "\\" not in value
             and "\x00" not in value,
             f"{label} must be a single relative filename")
    return value


def _stable_read_at(parent_fd: int, name: str, *, max_bytes: int, label: str) -> bytes:
    name = _single_component(name, label)
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_NONBLOCK", 0))
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise NativeFluidMetricMatrixError(f"{label} is not safely openable") from error
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and 0 < before.st_size <= max_bytes,
                 f"{label} must be a bounded single-link regular file")
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(_file_identity(before) == _file_identity(named),
                 f"{label} path changed while opening")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(fd, min(64 * 1024, remaining))
            _require(bool(block), f"{label} was truncated while being read")
            chunks.append(block)
            remaining -= len(block)
        _require(os.read(fd, 1) == b"", f"{label} grew while being read")
        after = os.fstat(fd)
        named_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(_file_identity(before) == _file_identity(after)
                 == _file_identity(named_after), f"{label} changed while being read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _stable_hash_at(
    parent_fd: int, name: str, *, expected_bytes: int, max_bytes: int, label: str,
) -> dict[str, Any]:
    name = _single_component(name, label)
    _require(isinstance(expected_bytes, int) and not isinstance(expected_bytes, bool)
             and 0 < expected_bytes <= max_bytes,
             f"{label} byte binding is outside its fixed resource limit")
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
             | getattr(os, "O_NONBLOCK", 0))
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise NativeFluidMetricMatrixError(f"{label} is not safely openable") from error
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and 0 < before.st_size <= max_bytes
                 and before.st_size == expected_bytes,
                 f"{label} must be a bounded single-link regular file matching its byte binding")
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(_file_identity(before) == _file_identity(named),
                 f"{label} path changed while opening")
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            block = os.read(fd, min(1024 * 1024, remaining))
            _require(bool(block), f"{label} was truncated while being hashed")
            digest.update(block)
            remaining -= len(block)
        _require(os.read(fd, 1) == b"", f"{label} grew while being hashed")
        after = os.fstat(fd)
        named_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(_file_identity(before) == _file_identity(after)
                 == _file_identity(named_after), f"{label} changed while being hashed")
        return {"bytes": before.st_size, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)


def _read_bounded_audit(path: Path | str, case_id: str) -> tuple[float, dict[str, Any]]:
    """Read an immutable audit receipt without following links or unbounded JSON input."""
    report_path = Path(path)
    if not report_path.is_absolute():
        report_path = Path.cwd() / report_path
    _require(".." not in report_path.parts,
             "solver timestep audit path cannot contain parent traversal")
    try:
        parent_fd, parent_path = bundle_v1._open_absolute_directory(report_path.parent)
    except (OSError, ValueError) as error:
        raise NativeFluidMetricMatrixError(
            "solver timestep audit parent must be a real, no-follow directory path"
        ) from error
    try:
        audit_name = _single_component(report_path.name, "solver timestep audit path")
        payload = _stable_read_at(
            parent_fd, audit_name, max_bytes=MAX_AUDIT_RECEIPT_BYTES,
            label="solver timestep audit",
        )
        try:
            receipt = bundle_v1._parse_json(payload, "solver timestep audit")
        except ValueError as error:
            raise NativeFluidMetricMatrixError(
                "solver timestep audit is not bounded valid UTF-8 JSON"
            ) from error
        _require(isinstance(receipt, dict) and set(receipt) == SOLVER_TIMESTEP_AUDIT_FIELDS
                 and receipt.get("schema") == SOLVER_TIMESTEP_AUDIT_SCHEMA
                 and receipt.get("status") == "passed"
                 and receipt.get("case_id") == case_id
                 and isinstance(receipt.get("checks"), dict)
                 and set(receipt["checks"]) == SOLVER_TIMESTEP_AUDIT_CHECKS
                 and all(value is True for value in receipt["checks"].values()),
                 "solver timestep audit is absent, failed, or bound to another case")
        max_step_claim = receipt.get("max_solver_dt_s")
        _require(type(max_step_claim) in {int, float},
                 "solver timestep audit max_solver_dt_s must be a JSON number")
        maximum_step = metric_v1._finite_scalar(
            max_step_claim, "max_solver_dt_s", positive=True,
        )
        source = receipt.get("source_log")
        _require(isinstance(source, dict) and set(source) == SOLVER_TIMESTEP_SOURCE_LOG_FIELDS
                 and isinstance(source.get("path"), str)
                 and isinstance(source.get("bytes"), int) and not isinstance(source.get("bytes"), bool)
                 and _hex64(source.get("sha256")),
                 "solver timestep audit must bind a well-formed native source log")
        source_name = _single_component(source["path"], "bound solver timestep source log path")
        source_binding = _stable_hash_at(
            parent_fd, source_name, expected_bytes=source["bytes"],
            max_bytes=MAX_AUDIT_SOURCE_LOG_BYTES,
            label="bound solver timestep source log",
        )
        _require(source_binding["sha256"] == source["sha256"],
                 "bound native solver timestep source log changed")

        audit_reference_path = str(Path(parent_path) / audit_name)
        source_reference_path = str(Path(parent_path) / source_name)
        return maximum_step, {
            "path": audit_reference_path,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "source_log": {
                "path": source_reference_path,
                **source_binding,
            },
        }
    finally:
        os.close(parent_fd)


def _load_frozen_contract() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str, str, str]:
    metric_v1._assert_frozen_inputs()
    metric_v1_review.verify_receipt()
    metric_review_v2.verify_receipt()
    table_review.verify_receipt()
    scope = json.loads(metric_v1.FROZEN_SCOPE_RECEIPT.read_text(encoding="utf-8"))
    parameters = json.loads(metric_v1.FROZEN_PARAMETER_CONTRACT.read_text(encoding="utf-8"))
    _require(scope.get("scope_id") == SCOPE_ID and isinstance(scope.get("matrix"), dict),
             "frozen R008 metric scope is malformed")
    matrix = scope["matrix"]
    rows = matrix.get("rows")
    _require(isinstance(rows, list) and len(rows) == 15
             and all(isinstance(row, dict) and row.get("qualification_only") is True for row in rows)
             and len({row.get("case_id") for row in rows}) == 15,
             "frozen metric matrix is not exactly 15 unique qualification-only rows")
    predeclared = scope.get("predeclared_t1_gates", {}).get("gate_applicability_by_case_and_comparison")
    applicability = matrix.get("gate_applicability")
    _require(isinstance(predeclared, dict) and predeclared == applicability,
             "frozen metric comparison registry has conflicting copies")
    _require(isinstance(parameters, dict)
             and parameters.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
             "pinned F8 physical/numerical parameter contract is malformed")
    table_review_sha = hashlib.sha256(table_review.OUTPUT.read_bytes()).hexdigest()
    metric_review_sha = hashlib.sha256(metric_review_v2.OUTPUT.read_bytes()).hexdigest()
    return (
        scope, parameters, predeclared,
        metric_v1.FROZEN_INPUT_SHA256["scope"],
        metric_v1.FROZEN_INPUT_SHA256["parameter_contract"],
        table_review_sha, metric_review_sha,
    )


def _validate_case_result(
    case_id: str,
    row: Mapping[str, Any],
    outer: Any,
    *,
    table_review_sha256: str,
    metric_review_sha256: str,
) -> dict[str, Any]:
    _require(isinstance(outer, dict) and set(outer) == CASE_RESULT_FIELDS
             and outer.get("schema") == CASE_RESULT_SCHEMA
             and outer.get("case_id") == case_id
             and outer.get("provenance_chain_references_closed") is True
             and outer.get("definition_control_bindings_match_frozen_pack_and_source_bytes") is True
             and outer.get("reviewed_metric_code_sources_match") is True
             and outer.get("loaded_module_code_identity_verified") is False
             and outer.get("native_table_review_authenticity")
             == "caller_supplied_trust_not_authenticated_here"
             and outer.get("metric_review_authenticity")
             == "caller_supplied_trust_not_authenticated_here"
             and outer.get("authorization_authenticity") == "external_gate_not_checked_here"
             and outer.get("runtime_environment_assumption")
             == "caller_attested_not_independently_verified"
             and outer.get("native_integrity_evaluated") is False
             and outer.get("metrics_evaluated") is True
             and outer.get("readiness_pass") is False
             and outer.get("T1_numerical") is False
             and _is_integer_zero(outer.get("qualification_credit")),
             f"per-case v2 result is absent, unclosed, or overstates T1: {case_id}")
    _require(outer.get("native_table_review_receipt_sha256") == table_review_sha256
             and outer.get("metric_review_receipt_sha256") == metric_review_sha256,
             f"per-case v2 result uses a different table/metric review receipt: {case_id}")

    statuses = outer.get("stage_statuses")
    receipt_hashes, manifest_hashes = outer.get("receipt_sha256"), outer.get("manifest_sha256")
    _require(isinstance(statuses, dict) and set(statuses) == set(STAGES)
             and all(statuses[stage] == "passed" for stage in STAGES)
             and isinstance(receipt_hashes, dict) and set(receipt_hashes) == set(STAGES)
             and all(_hex64(receipt_hashes[stage]) for stage in STAGES)
             and isinstance(manifest_hashes, dict) and set(manifest_hashes) == set(STAGES)
             and all(_hex64(manifest_hashes[stage]) for stage in STAGES),
             f"per-case result lacks exact B/C/D passed status and receipt/manifest bindings: {case_id}")

    table = outer.get("native_fluid_table")
    _require(isinstance(table, dict) and table.get("schema") == "core.cfd.f8.r008_native_fluid_table_semantics.v1"
             and table.get("table_schema") == TABLE_SCHEMA and table.get("case_id") == case_id
             and all(table.get(name) is True for name in (
                 "full_time_axis_matches", "fluid_id_projection_matches",
                 "position_velocity_density_mass_recomputed", "all_valid",
             ))
             and table.get("raw_frames_recomputed") == table.get("time_rows")
             and table.get("native_integrity_evaluated") is False
             and table.get("T1_numerical") is False
             and _is_integer_zero(table.get("qualification_credit"))
             and isinstance(table.get("table_bytes"), int) and not isinstance(table["table_bytes"], bool)
             and 0 < table["table_bytes"] <= table_v2.MAX_TABLE_FILE_BYTES
             and _hex64(table.get("table_sha256")),
             f"per-case result lacks full v2 table semantic verification: {case_id}")
    time_rows, particle_count = table.get("time_rows"), table.get("fluid_particle_count")
    _require(isinstance(time_rows, int) and not isinstance(time_rows, bool)
             and 2 <= time_rows <= table_v2.MAX_TIME_ROWS
             and isinstance(particle_count, int) and not isinstance(particle_count, bool)
             and 1 <= particle_count <= table_v2.MAX_PARTICLE_ROWS
             and time_rows * particle_count <= table_v2.MAX_TIME_PARTICLE_CELLS
             and isinstance(table.get("raw_frames_recomputed"), int)
             and not isinstance(table.get("raw_frames_recomputed"), bool)
             and table["raw_frames_recomputed"] == time_rows,
             f"per-case table dimensions or recomputed-frame count are outside v2 resource bounds: {case_id}")

    case_metrics = outer.get("case_metrics")
    _require(isinstance(case_metrics, dict)
             and outer.get("metric_gates_passed") is case_metrics.get("metric_gates_passed")
             and _is_integer_zero(case_metrics.get("qualification_credit")),
             f"outer per-case metric-gate result differs from its case payload: {case_id}")
    _require(case_metrics.get("source_table_bytes") == table["table_bytes"]
             and case_metrics.get("source_table_sha256") == table["table_sha256"],
             f"case metrics are not bound to the semantically verified v2 table: {case_id}")
    checked = metric_bundle_v2._validate_case_metrics(
        case_metrics,
        case_id=case_id,
        frozen_row=row,
        table_binding={"bytes": table["table_bytes"], "sha256": table["table_sha256"]},
    )
    metric_hash = hashlib.sha256(
        json.dumps(checked, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return {
        "case_metrics": checked,
        "metric_result_sha256": metric_hash,
        "receipt_sha256": dict(receipt_hashes),
        "manifest_sha256": dict(manifest_hashes),
        "native_fluid_table_sha256": table["table_sha256"],
    }


def evaluate_metric_matrix_v2(
    case_results: Mapping[str, Mapping[str, Any]],
    *,
    solver_timestep_audits: Mapping[str, Path | str],
) -> dict[str, Any]:
    """Evaluate all 15 frozen case metrics and 8 comparisons, not full T1.

    The supplied per-case records must be the outputs of the held-FD v2
    B/C/D verifier. This function checks their structure/hashes but does not
    reopen production bundles or authenticate external caller trust. Native
    integrity and final T1 adjudication are explicitly outside its output.
    """
    (scope, parameters, applicability, scope_sha, parameter_sha,
     table_review_sha, metric_review_sha) = _load_frozen_contract()
    rows = scope["matrix"]["rows"]
    row_by_id = {str(row["case_id"]): row for row in rows}
    _require(isinstance(case_results, Mapping) and set(case_results) == set(row_by_id),
             "metric matrix requires exactly the frozen 15 case results; failures cannot be omitted")

    verified: dict[str, dict[str, Any]] = {}
    for case_id, row in row_by_id.items():
        verified[case_id] = _validate_case_result(
            case_id, row, case_results[case_id],
            table_review_sha256=table_review_sha,
            metric_review_sha256=metric_review_sha,
        )
    metrics_by_id = {case_id: item["case_metrics"] for case_id, item in verified.items()}
    all_case_metrics_passed = all(item["metric_gates_passed"] for item in metrics_by_id.values())

    comparisons = applicability.get("cross_resolution_comparisons")
    _require(isinstance(comparisons, list) and len(comparisons) == 8,
             "frozen R008 matrix must contain exactly eight cross-resolution comparisons")
    half_height = float(parameters["geometry_and_fluid"]["half_height_m"])
    production_dp = float(parameters["resolution_contract"]["production_dp_m"])
    intervals = round(2.0 * half_height / production_dp)
    common_z = -half_height + np.arange(1, intervals, dtype=np.float64) * production_dp
    cross_results = []
    for pair in comparisons:
        candidate_id = pair.get("coarse_case", pair.get("fine_case"))
        production_id = pair.get("production_case")
        _require(candidate_id in row_by_id and production_id in row_by_id,
                 f"frozen comparison references an unknown case: {pair}")
        candidate_row, production_row = row_by_id[candidate_id], row_by_id[production_id]
        _require(candidate_row["q"] == production_row["q"] == pair.get("q")
                 and candidate_row["period_s"] == production_row["period_s"]
                 and candidate_row["observation_start_s"] == production_row["observation_start_s"]
                 and candidate_row["observation_end_s"] == production_row["observation_end_s"]
                 and candidate_row["native_output_samples_per_period"]
                 == production_row["native_output_samples_per_period"],
                 f"registered cross-resolution cases do not share the frozen time/q grid: {pair}")
        candidate_times = np.asarray(metrics_by_id[candidate_id]["selected_time_s"], dtype=np.float64)
        production_times = np.asarray(metrics_by_id[production_id]["selected_time_s"], dtype=np.float64)
        _require(candidate_times.shape == production_times.shape
                 and np.allclose(candidate_times, production_times, rtol=0.0, atol=1e-12),
                 f"registered cross-resolution case outputs do not share the exact time grid: {pair}")
        comparison = metric_v1.compare_profile_coefficients(
            metrics_by_id[candidate_id], metrics_by_id[production_id], common_z,
            amplitude_relative_max=float(pair["amplitude_relative_max"]),
            phase_absolute_max_rad=float(pair["phase_absolute_max_rad"]),
        )
        comparison["passed"] = bool(
            comparison["passed"]
            and metrics_by_id[candidate_id]["metric_gates_passed"]
            and metrics_by_id[production_id]["metric_gates_passed"]
        )
        cross_results.append({
            "candidate_case_id": candidate_id,
            "production_case_id": production_id,
            **comparison,
        })
    cross_passed = all(item["passed"] for item in cross_results)

    time_comparison = applicability.get("time_step_comparison")
    _require(isinstance(time_comparison, dict), "frozen time-step comparison is absent")
    baseline_id = str(time_comparison["baseline_case_id"])
    refined_id = str(time_comparison["case_id"])
    _require(baseline_id in row_by_id and refined_id in row_by_id
             and isinstance(solver_timestep_audits, Mapping)
             and set(solver_timestep_audits) == {baseline_id, refined_id},
             "time-step comparison requires exactly the frozen baseline/refined solver audits")
    baseline_dt, baseline_audit = _read_bounded_audit(solver_timestep_audits[baseline_id], baseline_id)
    refined_dt, refined_audit = _read_bounded_audit(solver_timestep_audits[refined_id], refined_id)
    baseline_metrics, refined_metrics = metrics_by_id[baseline_id], metrics_by_id[refined_id]
    phase_difference = metric_v1.wrapped_phase_difference(
        baseline_metrics["center_coefficients"]["phase_rad"],
        refined_metrics["center_coefficients"]["phase_rad"],
    )
    time_step_passed = bool(
        baseline_metrics["metric_gates_passed"] and refined_metrics["metric_gates_passed"]
        and refined_dt < baseline_dt
        and phase_difference <= float(time_comparison["phase_difference_absolute_max_rad"])
    )

    cadence = applicability.get("output_cadence_comparison")
    _require(isinstance(cadence, dict), "frozen output-cadence comparison is absent")
    cadence_baseline_id = str(cadence["baseline_case_id"])
    dense_id = str(cadence["case_id"])
    dense_times = np.asarray(metrics_by_id[dense_id]["selected_time_s"], dtype=np.float64)
    baseline_times = np.asarray(metrics_by_id[cadence_baseline_id]["selected_time_s"], dtype=np.float64)
    downsampled = dense_times[::2]
    cadence_grid_passed = bool(
        len(downsampled) == len(baseline_times)
        and np.allclose(downsampled, baseline_times, rtol=0.0, atol=1e-12)
    )
    cadence_passed = bool(
        cadence_grid_passed
        and metrics_by_id[cadence_baseline_id]["metric_gates_passed"]
        and metrics_by_id[dense_id]["metric_gates_passed"]
    )

    return {
        "schema": SCHEMA,
        "scope_id": SCOPE_ID,
        "frozen_scope_receipt_sha256": scope_sha,
        "parameter_contract_sha256": parameter_sha,
        "table_review_receipt_sha256": table_review_sha,
        "metric_review_receipt_sha256": metric_review_sha,
        "status": "matrix_metric_and_comparison_gates_evaluated_native_integrity_pending",
        "case_count": len(row_by_id),
        "case_result_bindings": {
            case_id: {
                "metric_result_sha256": value["metric_result_sha256"],
                "receipt_sha256": value["receipt_sha256"],
                "manifest_sha256": value["manifest_sha256"],
                "native_fluid_table_sha256": value["native_fluid_table_sha256"],
            }
            for case_id, value in verified.items()
        },
        "failed_case_metric_gate_ids": [
            case_id for case_id, value in metrics_by_id.items()
            if not value["metric_gates_passed"]
        ],
        "case_metric_gates_passed": all_case_metrics_passed,
        "cross_resolution": cross_results,
        "cross_resolution_gates_passed": cross_passed,
        "time_step_comparison": {
            "baseline_case_id": baseline_id,
            "refined_case_id": refined_id,
            "baseline_solver_max_dt_s": baseline_dt,
            "refined_solver_max_dt_s": refined_dt,
            "baseline_solver_timestep_audit": baseline_audit,
            "refined_solver_timestep_audit": refined_audit,
            "wrapped_center_phase_difference_rad": phase_difference,
            "passed": time_step_passed,
        },
        "output_cadence_comparison": {
            "baseline_case_id": cadence_baseline_id,
            "dense_case_id": dense_id,
            "baseline_sample_count": len(baseline_times),
            "dense_sample_count": len(dense_times),
            "downsampled_timestamp_grid_passed": cadence_grid_passed,
            "passed": cadence_passed,
        },
        "all_metric_and_comparison_gates_passed": bool(
            all_case_metrics_passed and cross_passed and time_step_passed and cadence_passed
        ),
        "case_failure_denominator_fixed": True,
        "per_case_B_C_D_chain_reverified_by_matrix": False,
        "external_receipt_authenticity_verified_by_matrix": False,
        "native_integrity_evaluated": False,
        "full_t1_decision": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }


__all__ = ["NativeFluidMetricMatrixError", "SCHEMA", "evaluate_metric_matrix_v2"]
