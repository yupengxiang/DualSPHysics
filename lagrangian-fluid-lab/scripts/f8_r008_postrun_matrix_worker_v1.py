"""Compose frozen F8 R008 matrix diagnostics with 15 single-case bridges.

For each frozen row this module invokes the single-case bridge, then obtains a
fresh full v2 verifier result for matrix-v5 and joins the two paths by exact
metric and digest comparisons. This module does not launch or schedule solver
work, write receipts/ledgers, or award qualification credit. Per-case artifacts
already published before a later failure are retained; callers must inspect
fixed output names before retrying.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from typing import Any, Mapping

from scripts import f8_r008_postrun_case_worker_v1 as case_worker
from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_bundle
from scripts import f8_r008_t1_metric_matrix_adapter_v5 as matrix_v5


SCHEMA = "core.cfd.f8.r008_postrun_matrix_worker.v1"
CASE_COUNT = 15
STAGES = ("B", "C", "D")
SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
CASE_INPUT_FIELDS = frozenset({
    "bundle_roots", "trusted_authorization_bytes", "trusted_authorization_sha256",
    "expected_authorization_envelopes", "trusted_table_review_receipt_bytes",
    "trusted_table_review_receipt_sha256", "trusted_metric_review_receipt_bytes",
    "trusted_metric_review_receipt_sha256", "trusted_code_review_receipt_bytes",
    "trusted_runtime_assumption", "output_directory_fd",
})
WORKER_RESULT_FIELDS = frozenset({
    "schema", "status", "case_id", "trajectory_schema", "trajectory_binding",
    "split", "case_metrics", "metric_gates_passed",
    "provenance_chain_references_closed_before_and_after", "receipt_sha256",
    "manifest_sha256", "native_fluid_table_bytes", "native_fluid_table_sha256",
    "external_authorization_authenticated", "supervisor_identity_authenticated",
    "loaded_module_code_identity_verified", "native_integrity_evaluated",
    "native_integrity_pass", "T1_numerical", "readiness_pass", "formal_eligible",
    "solver_invoked", "worker_or_scheduler_launch_invoked", "gpu_or_queue_invoked",
    "qualification_credit",
})
OUTPUT_FIELDS = frozenset({
    "schema", "status", "case_count", "case_ids", "case_failure_denominator_fixed",
    "case_results", "metric_matrix_v5", "matrix_case_bindings_match_postrun_bridges",
    "qualification_boundaries",
})
MATRIX_V5_QUALIFICATION_BOUNDARIES = {
    "input_evidence_authenticated": False,
    "execution_source_identity_verified": False,
    "runtime_configuration_verified": False,
    "effective_step_algorithm_verified": False,
    "native_integrity_evaluated": False,
    "native_integrity_adjudicated": False,
    "normal_completion_verified": False,
    "solver_completion_verified": False,
    "solver_timestep_adjudicated": False,
    "T1_numerical": False,
    "readiness_pass": False,
    "qualification_credit": 0,
}


class PostrunMatrixWorkerError(ValueError):
    """The 15-case post-run composition is incomplete or inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PostrunMatrixWorkerError(message)


def _snapshot_exact_mapping(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    try:
        result = dict(value)
    except (TypeError, ValueError) as error:
        raise PostrunMatrixWorkerError(f"{label} cannot be snapshotted") from error
    _require(set(result) == expected,
             f"{label} must contain exactly the frozen 15-case key set")
    return result


def _case_ids() -> list[str]:
    try:
        case_ids, _rows = matrix_v5._frozen_rows()
    except Exception as error:
        raise PostrunMatrixWorkerError(
            f"frozen R008 matrix rows could not be loaded: {error}"
        ) from error
    _require(len(case_ids) == CASE_COUNT and len(set(case_ids)) == CASE_COUNT,
             "frozen R008 denominator is not exactly 15 unique cases")
    return case_ids


def _snapshot_case_inputs(
    value: Any,
    case_ids: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    rows = _snapshot_exact_mapping(value, set(case_ids), "case_worker_inputs")
    snapshots: dict[str, dict[str, Any]] = {}
    output_fds: dict[str, int] = {}
    seen_fds: set[int] = set()
    seen_directories: set[tuple[int, int]] = set()
    try:
        for case_id in case_ids:
            row = rows[case_id]
            _require(isinstance(row, Mapping) and set(row) == CASE_INPUT_FIELDS,
                     f"case_worker_inputs[{case_id}] has an unexpected field set")
            try:
                snapshot = copy.deepcopy(dict(row))
            except Exception as error:
                raise PostrunMatrixWorkerError(
                    f"case_worker_inputs[{case_id}] cannot be snapshotted"
                ) from error
            output_fd = row["output_directory_fd"]
            _require(type(output_fd) is int and output_fd >= 0,
                     f"case_worker_inputs[{case_id}] output FD must be a nonnegative integer")
            _require(output_fd not in seen_fds,
                     "each frozen case must use a distinct output directory FD")
            seen_fds.add(output_fd)
            try:
                case_worker._validate_output_directory_fd(output_fd)
                info = os.fstat(output_fd)
                identity = (info.st_dev, info.st_ino)
                _require(identity not in seen_directories,
                         "each frozen case must use a distinct output directory inode")
                seen_directories.add(identity)
                case_worker._require_output_absent(output_fd)
                held_fd = os.dup(output_fd)
            except PostrunMatrixWorkerError:
                raise
            except OSError as error:
                raise PostrunMatrixWorkerError(
                    f"case_worker_inputs[{case_id}] output directory is not safely held"
                ) from error
            snapshots[case_id] = snapshot
            output_fds[case_id] = held_fd
    except BaseException:
        for held_fd in output_fds.values():
            try:
                os.close(held_fd)
            except OSError:
                pass
        raise
    return snapshots, output_fds


def _canonical_metric_sha256(metrics: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            metrics, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PostrunMatrixWorkerError("case metrics are not canonical JSON") from error
    return hashlib.sha256(payload).hexdigest()


def _verify_case_worker_result(
    result: Any,
    *,
    case_id: str,
    case_result: Mapping[str, Any],
) -> dict[str, Any]:
    _require(type(result) is dict and set(result) == WORKER_RESULT_FIELDS
             and result.get("schema") == case_worker.SCHEMA
             and result.get("status")
             == "diagnostic_postrun_trajectory_and_v2_metrics_revalidated"
             and result.get("case_id") == case_id
             and result.get("trajectory_schema")
             == case_worker.trajectory_adapter.CORE_TRAJECTORY_SCHEMA
             and result.get("split") == "qualification"
             and result.get("provenance_chain_references_closed_before_and_after") is True
             and result.get("external_authorization_authenticated") is False
             and result.get("supervisor_identity_authenticated") is False
             and result.get("loaded_module_code_identity_verified") is False
             and result.get("native_integrity_evaluated") is False
             and result.get("native_integrity_pass") is False
             and result.get("T1_numerical") is False
             and result.get("readiness_pass") is False
             and result.get("formal_eligible") is False
             and result.get("solver_invoked") is False
             and result.get("worker_or_scheduler_launch_invoked") is False
             and result.get("gpu_or_queue_invoked") is False
             and type(result.get("qualification_credit")) is int
             and result["qualification_credit"] == 0,
             f"single-case bridge result is malformed or overstates trust: {case_id}")

    binding = result.get("trajectory_binding")
    _require(type(binding) is dict and set(binding) == {"path", "bytes", "sha256"}
             and binding.get("path") == case_worker.trajectory_adapter.OUTPUT_FILENAME
             and type(binding.get("bytes")) is int and binding["bytes"] > 0
             and type(binding.get("sha256")) is str
             and SHA256.fullmatch(binding["sha256"]) is not None,
             f"single-case trajectory binding is malformed: {case_id}")

    expected_receipts = case_result.get("receipt_sha256")
    expected_manifests = case_result.get("manifest_sha256")
    table = case_result.get("native_fluid_table")
    metrics = case_result.get("case_metrics")
    _require(type(expected_receipts) is dict and set(expected_receipts) == set(STAGES)
             and type(expected_manifests) is dict and set(expected_manifests) == set(STAGES)
             and type(table) is dict and type(metrics) is dict,
             f"matrix-v5 case input lacks exact validated v2 references: {case_id}")
    _require(result.get("receipt_sha256") == expected_receipts
             and result.get("manifest_sha256") == expected_manifests
             and result.get("native_fluid_table_sha256") == table.get("table_sha256")
             and result.get("native_fluid_table_bytes") == table.get("table_bytes")
             and result.get("case_metrics") == metrics
             and result.get("metric_gates_passed") is metrics.get("metric_gates_passed"),
             f"single-case bridge differs from the matrix-v5 input for {case_id}")

    return {
        "trajectory_binding": dict(binding),
        "case_metrics": copy.deepcopy(metrics),
        "metric_result_sha256": _canonical_metric_sha256(metrics),
        "metric_gates_passed": metrics.get("metric_gates_passed"),
        "receipt_sha256": dict(expected_receipts),
        "manifest_sha256": dict(expected_manifests),
        "native_fluid_table_bytes": table["table_bytes"],
        "native_fluid_table_sha256": table["table_sha256"],
        "qualification_credit": 0,
    }


def _verify_matrix_bindings(
    matrix_result: Mapping[str, Any],
    case_results: Mapping[str, Mapping[str, Any]],
    bridges: Mapping[str, Mapping[str, Any]],
    case_ids: list[str],
) -> None:
    projection = matrix_result.get("matrix_v4_observations")
    _require(type(projection) is dict
             and type(projection.get("case_result_bindings")) is dict
             and set(projection["case_result_bindings"]) == set(case_ids),
             "matrix-v5 output lacks the exact 15 original case-result bindings")
    for case_id in case_ids:
        original = case_results[case_id]
        table = original["native_fluid_table"]
        expected = {
            "metric_result_sha256": bridges[case_id]["metric_result_sha256"],
            "receipt_sha256": bridges[case_id]["receipt_sha256"],
            "manifest_sha256": bridges[case_id]["manifest_sha256"],
            "native_fluid_table_sha256": bridges[case_id]["native_fluid_table_sha256"],
        }
        _require(projection["case_result_bindings"][case_id] == expected
                 and original["case_metrics"] == bridges[case_id]["case_metrics"]
                 and table["table_bytes"] == bridges[case_id]["native_fluid_table_bytes"],
                 f"matrix-v5 and post-run bridge are not bound to the same case: {case_id}")


def _verify_matrix_result(result: Any, case_ids: list[str]) -> None:
    _require(type(result) is dict and set(result) == matrix_v5.OUTPUT_FIELDS
             and result.get("schema") == matrix_v5.SCHEMA
             and result.get("status")
             == "frozen_15_case_composed_diagnostics_only_no_qualification"
             and result.get("case_count") == CASE_COUNT
             and result.get("case_ids") == case_ids
             and result.get("case_failure_denominator_fixed") is True,
             "matrix-v5 result is malformed or has a changed 15-case denominator")
    boundaries = result.get("qualification_boundaries")
    _require(type(boundaries) is dict
             and set(boundaries) == set(MATRIX_V5_QUALIFICATION_BOUNDARIES)
             and all(type(boundaries[name]) is bool and boundaries[name] is False
                     for name in MATRIX_V5_QUALIFICATION_BOUNDARIES
                     if name != "qualification_credit")
             and type(boundaries.get("qualification_credit")) is int
             and boundaries["qualification_credit"] == 0
             and boundaries == MATRIX_V5_QUALIFICATION_BOUNDARIES,
             "matrix-v5 nested qualification boundaries are not exact false/zero")


def materialize_postrun_matrix_worker_v1(
    case_worker_inputs: Mapping[str, Mapping[str, Any]],
    *,
    solver_timestep_sources: Mapping[str, os.PathLike[str] | str],
    runparts_raw_by_case: Mapping[str, bytes],
    effective_step_algorithm_claims: Mapping[str, str],
    runtime_completion_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Run the diagnostic 15-case matrix and materialize each Core trajectory.

    No solver/worker is launched. Caller-owned output directory FDs remain
    open; this function uses held duplicates and passes one disposable duplicate
    per case to the reviewed single-case bridge. All matrix inputs are checked
    before the first artifact is written. If a later case fails, previously
    published qualification artifacts are retained and must be inspected before
    any retry.
    """
    case_ids = _case_ids()
    output_fds: dict[str, int] = {}
    artifact_fds: dict[str, int] = {}
    artifact_identities: dict[str, tuple[int, int, int]] = {}
    bridge_bindings: dict[str, dict[str, Any]] = {}
    try:
        cases, output_fds = _snapshot_case_inputs(case_worker_inputs, case_ids)
        # Validate every matrix-wide diagnostic input before publishing any
        # trajectory. Full case-result validation is possible only after each
        # completed B/C/D chain has been freshly reverified below.
        matrix_inputs = matrix_v5._snapshot_inputs(
            case_results={case_id: {} for case_id in case_ids},
            solver_timestep_sources=solver_timestep_sources,
            runparts_raw_by_case=runparts_raw_by_case,
            effective_step_algorithm_claims=effective_step_algorithm_claims,
            runtime_completion_evidence=runtime_completion_evidence,
            case_ids=case_ids,
        )
        bridge_results: dict[str, dict[str, Any]] = {}
        verified_case_results: dict[str, dict[str, Any]] = {}
        for case_id in case_ids:
            case_row = cases[case_id]
            call_inputs = {
                key: value for key, value in case_row.items()
                if key != "output_directory_fd"
            }
            worker_fd = os.dup(output_fds[case_id])
            try:
                worker_result = case_worker.materialize_postrun_case_worker_v1(
                    **call_inputs,
                    case_id=case_id,
                    output_directory_fd=worker_fd,
                )
            except Exception as error:
                raise PostrunMatrixWorkerError(
                    f"post-run case {case_id} failed; earlier artifacts, if any, were retained; "
                    "inspect each fixed output name before retrying"
                ) from error
            try:
                roots = call_inputs["bundle_roots"]
                raw_case_result = metric_bundle.verify_native_fluid_table_chain_and_metrics(
                    roots,
                    trusted_authorization_bytes=call_inputs["trusted_authorization_bytes"],
                    trusted_authorization_sha256=call_inputs[
                        "trusted_authorization_sha256"
                    ],
                    expected_authorization_envelopes=call_inputs[
                        "expected_authorization_envelopes"
                    ],
                    trusted_table_review_receipt_bytes=call_inputs[
                        "trusted_table_review_receipt_bytes"
                    ],
                    trusted_table_review_receipt_sha256=call_inputs[
                        "trusted_table_review_receipt_sha256"
                    ],
                    trusted_metric_review_receipt_bytes=call_inputs[
                        "trusted_metric_review_receipt_bytes"
                    ],
                    trusted_metric_review_receipt_sha256=call_inputs[
                        "trusted_metric_review_receipt_sha256"
                    ],
                    trusted_code_review_receipt_bytes=call_inputs[
                        "trusted_code_review_receipt_bytes"
                    ],
                    trusted_runtime_assumption=call_inputs["trusted_runtime_assumption"],
                )
                case_worker._verify_v2_result(raw_case_result, case_id)
            except Exception as error:
                raise PostrunMatrixWorkerError(
                    f"post-run case {case_id} full v2 verifier recheck failed; "
                    "all published artifacts are retained; inspect fixed output names "
                    "before retrying"
                ) from error
            verified_case_results[case_id] = raw_case_result
            try:
                bridge_results[case_id] = _verify_case_worker_result(
                    worker_result, case_id=case_id, case_result=raw_case_result,
                )
                artifact_fd, artifact_info = case_worker._open_final_artifact(
                    output_fds[case_id], bridge_results[case_id]["trajectory_binding"],
                )
                artifact_fds[case_id] = artifact_fd
                artifact_identities[case_id] = (
                    artifact_info.st_dev, artifact_info.st_ino, artifact_info.st_size,
                )
                bridge_bindings[case_id] = bridge_results[case_id]["trajectory_binding"]
            except Exception as error:
                raise PostrunMatrixWorkerError(
                    f"post-run case {case_id} bridge/result or published-file binding mismatch; "
                    "the published artifact is retained and must be inspected before retrying"
                ) from error

        try:
            matrix_result = matrix_v5.evaluate_metric_matrix_v5(
                verified_case_results,
                solver_timestep_sources=matrix_inputs[1],
                runparts_raw_by_case=matrix_inputs[2],
                effective_step_algorithm_claims=matrix_inputs[3],
                runtime_completion_evidence=matrix_inputs[4],
            )
        except Exception as error:
            raise PostrunMatrixWorkerError(
                "15-case matrix-v5 recomputation failed after per-case materialization; "
                "all published artifacts are retained and must be inspected before retrying"
            ) from error
        try:
            _verify_matrix_result(matrix_result, case_ids)
            _verify_matrix_bindings(
                matrix_result, verified_case_results, bridge_results, case_ids,
            )
            for case_id in case_ids:
                final_fd, final_info = case_worker._open_final_artifact(
                    output_fds[case_id], bridge_bindings[case_id],
                )
                try:
                    current_identity = (
                        final_info.st_dev, final_info.st_ino, final_info.st_size,
                    )
                    _require(current_identity == artifact_identities[case_id],
                             f"published trajectory inode changed before matrix return: {case_id}")
                finally:
                    os.close(final_fd)
        except Exception as error:
            raise PostrunMatrixWorkerError(
                "final 15-case matrix/result or trajectory-file binding failed; "
                "all published artifacts "
                "are retained and must be inspected before retrying"
            ) from error
        output = {
            "schema": SCHEMA,
            "status": "diagnostic_frozen_15_case_matrix_and_core_trajectories_materialized",
            "case_count": CASE_COUNT,
            "case_ids": list(case_ids),
            "case_failure_denominator_fixed": True,
            "case_results": bridge_results,
            "metric_matrix_v5": matrix_result,
            "matrix_case_bindings_match_postrun_bridges": True,
            "qualification_boundaries": {
                "input_evidence_authenticated": False,
                "execution_source_identity_verified": False,
                "supervisor_identity_authenticated": False,
                "runtime_configuration_verified": False,
                "native_integrity_evaluated": False,
                "native_integrity_adjudicated": False,
                "normal_completion_verified": False,
                "solver_completion_verified": False,
                "solver_timestep_adjudicated": False,
                "T1_numerical": False,
                "readiness_pass": False,
                "formal_eligible": False,
                "solver_invoked": False,
                "worker_or_scheduler_launch_invoked": False,
                "gpu_or_queue_invoked": False,
                "qualification_credit": 0,
            },
        }
        _require(set(output) == OUTPUT_FIELDS,
                 "internal post-run matrix output fields drifted from v1 contract")
        return output
    finally:
        for artifact_fd in artifact_fds.values():
            try:
                os.close(artifact_fd)
            except OSError:
                pass
        for output_fd in output_fds.values():
            try:
                os.close(output_fd)
            except OSError:
                pass


__all__ = [
    "PostrunMatrixWorkerError", "SCHEMA", "materialize_postrun_matrix_worker_v1",
]
