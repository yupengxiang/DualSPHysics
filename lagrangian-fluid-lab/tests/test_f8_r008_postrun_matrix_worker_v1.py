from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path

import pytest

from scripts import f8_r008_core_trajectory_adapter_v1 as trajectory_adapter
from scripts import f8_r008_native_fluid_table_metric_bundle_verifier_v2 as metric_bundle
from scripts import f8_r008_postrun_case_worker_v1 as case_worker
from scripts import f8_r008_postrun_matrix_worker_v1 as matrix_worker
from scripts import f8_r008_t1_metric_matrix_adapter_v5 as matrix_v5
from tests import test_f8_r008_t1_metric_matrix_adapter_v5 as matrix_fixtures


def _inputs(tmp_path: Path):
    prepared = matrix_fixtures._prepared(tmp_path)
    case_ids = [case_id for case_id in prepared["case_results"]]
    case_inputs = {}
    output_fds = []
    root_to_case = {}
    for case_id in case_ids:
        roots = {
            stage: f"/synthetic-r008/{case_id}/{stage}"
            for stage in ("B", "C", "D")
        }
        root_to_case[tuple(roots[stage] for stage in ("B", "C", "D"))] = case_id
        output_dir = tmp_path / f"out-{len(output_fds):02d}"
        output_dir.mkdir(mode=0o700)
        output_fd = os.open(
            output_dir,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        output_fds.append(output_fd)
        case_inputs[case_id] = {
            "bundle_roots": roots,
            "trusted_authorization_bytes": {stage: b"synthetic-auth" for stage in roots},
            "trusted_authorization_sha256": {stage: "a" * 64 for stage in roots},
            "expected_authorization_envelopes": {stage: {} for stage in roots},
            "trusted_table_review_receipt_bytes": b"synthetic-table-review",
            "trusted_table_review_receipt_sha256": "b" * 64,
            "trusted_metric_review_receipt_bytes": b"synthetic-metric-review",
            "trusted_metric_review_receipt_sha256": "c" * 64,
            "trusted_code_review_receipt_bytes": b"synthetic-code-review",
            "trusted_runtime_assumption": {},
            "output_directory_fd": output_fd,
        }
    return prepared, case_ids, case_inputs, output_fds, root_to_case


def _patch_synthetic_workers(
    monkeypatch, prepared, root_to_case, *, mismatch_case=None,
    bad_trajectory_sha_case=None, replace_earlier_on_case=None, case_inputs=None,
):
    original_results = prepared["case_results"]
    worker_calls = []

    def verify_bundle(roots, **_kwargs):
        case_id = root_to_case[tuple(roots[stage] for stage in ("B", "C", "D"))]
        return copy.deepcopy(original_results[case_id])

    def materialize(*, case_id, output_directory_fd, **_kwargs):
        worker_calls.append(case_id)
        try:
            payload = f"synthetic-core-trajectory:{case_id}".encode()
            fd = os.open(
                trajectory_adapter.OUTPUT_FILENAME,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=output_directory_fd,
            )
            try:
                assert os.write(fd, payload) == len(payload)
            finally:
                os.close(fd)
            result = original_results[case_id]
            table = result["native_fluid_table"]
            metrics = result["case_metrics"]
            case_input = {
                "schema": case_worker.SCHEMA,
                "status": "diagnostic_postrun_trajectory_and_v2_metrics_revalidated",
                "case_id": case_id,
                "trajectory_schema": trajectory_adapter.CORE_TRAJECTORY_SCHEMA,
                "trajectory_binding": {
                    "path": trajectory_adapter.OUTPUT_FILENAME,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                "split": "qualification",
                "case_metrics": copy.deepcopy(metrics),
                "metric_gates_passed": metrics["metric_gates_passed"],
                "provenance_chain_references_closed_before_and_after": True,
                "receipt_sha256": copy.deepcopy(result["receipt_sha256"]),
                "manifest_sha256": copy.deepcopy(result["manifest_sha256"]),
                "native_fluid_table_bytes": table["table_bytes"],
                "native_fluid_table_sha256": table["table_sha256"],
                "external_authorization_authenticated": False,
                "supervisor_identity_authenticated": False,
                "loaded_module_code_identity_verified": False,
                "native_integrity_evaluated": False,
                "native_integrity_pass": False,
                "T1_numerical": False,
                "readiness_pass": False,
                "formal_eligible": False,
                "solver_invoked": False,
                "worker_or_scheduler_launch_invoked": False,
                "gpu_or_queue_invoked": False,
                "qualification_credit": 0,
            }
            if case_id == bad_trajectory_sha_case:
                case_input["trajectory_binding"]["sha256"] = "f" * 64
            if case_id == mismatch_case:
                case_input["native_fluid_table_sha256"] = "f" * 64
            if replace_earlier_on_case is not None and case_id == replace_earlier_on_case:
                earlier_id = next(
                    candidate for candidate in original_results
                    if candidate != replace_earlier_on_case
                )
                earlier_dir_fd = case_inputs[earlier_id]["output_directory_fd"]
                replacement_name = "synthetic-replacement.h5"
                replacement_fd = os.open(
                    replacement_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=earlier_dir_fd,
                )
                try:
                    replacement = f"synthetic-core-trajectory:{earlier_id}".encode()
                    assert os.write(replacement_fd, replacement) == len(replacement)
                finally:
                    os.close(replacement_fd)
                os.replace(
                    replacement_name,
                    trajectory_adapter.OUTPUT_FILENAME,
                    src_dir_fd=earlier_dir_fd,
                    dst_dir_fd=earlier_dir_fd,
                )
            return case_input
        finally:
            os.close(output_directory_fd)

    monkeypatch.setattr(metric_bundle, "verify_native_fluid_table_chain_and_metrics",
                        verify_bundle)
    monkeypatch.setattr(case_worker, "materialize_postrun_case_worker_v1", materialize)
    return worker_calls


def _evaluate(prepared, case_inputs):
    return matrix_worker.materialize_postrun_matrix_worker_v1(
        case_inputs,
        solver_timestep_sources=prepared["solver_timestep_sources"],
        runparts_raw_by_case=prepared["runparts_raw_by_case"],
        effective_step_algorithm_claims=prepared["effective_step_algorithm_claims"],
        runtime_completion_evidence=prepared["runtime_completion_evidence"],
    )


def test_composes_exact_fifteen_bridges_with_fresh_v2_results_and_matrix_v5(
    tmp_path, monkeypatch,
):
    prepared, case_ids, case_inputs, output_fds, roots = _inputs(tmp_path)
    worker_calls = _patch_synthetic_workers(monkeypatch, prepared, roots)
    try:
        result = _evaluate(prepared, case_inputs)
        assert result["schema"] == matrix_worker.SCHEMA
        assert result["status"] == (
            "diagnostic_frozen_15_case_matrix_and_core_trajectories_materialized"
        )
        assert result["case_count"] == 15
        assert result["case_ids"] == case_ids
        assert result["case_failure_denominator_fixed"] is True
        assert result["matrix_case_bindings_match_postrun_bridges"] is True
        assert result["metric_matrix_v5"]["case_ids"] == case_ids
        assert result["metric_matrix_v5"]["qualification_boundaries"] == (
            matrix_worker.MATRIX_V5_QUALIFICATION_BOUNDARIES
        )
        assert result["qualification_boundaries"]["solver_invoked"] is False
        assert result["qualification_boundaries"]["worker_or_scheduler_launch_invoked"] is False
        assert result["qualification_boundaries"]["gpu_or_queue_invoked"] is False
        assert worker_calls == case_ids
        assert set(result["case_results"]) == set(case_ids)
        for case_input in case_inputs.values():
            path = Path(os.readlink(f"/proc/self/fd/{case_input['output_directory_fd']}"))
            assert (path / trajectory_adapter.OUTPUT_FILENAME).is_file()
    finally:
        for output_fd in output_fds:
            os.close(output_fd)


def test_rejects_missing_case_before_materializing_any_artifact(tmp_path, monkeypatch):
    prepared, case_ids, case_inputs, output_fds, roots = _inputs(tmp_path)
    worker_calls = _patch_synthetic_workers(monkeypatch, prepared, roots)
    try:
        incomplete = dict(case_inputs)
        incomplete.pop(case_ids[-1])
        with pytest.raises(matrix_worker.PostrunMatrixWorkerError,
                           match="exactly the frozen 15-case key set"):
            _evaluate(prepared, incomplete)
        assert worker_calls == []
    finally:
        for output_fd in output_fds:
            os.close(output_fd)


def test_rejects_aliased_output_directory_inodes_before_materializing(tmp_path, monkeypatch):
    prepared, case_ids, case_inputs, output_fds, roots = _inputs(tmp_path)
    worker_calls = _patch_synthetic_workers(monkeypatch, prepared, roots)
    aliased_fd = os.dup(case_inputs[case_ids[0]]["output_directory_fd"])
    output_fds.append(aliased_fd)
    try:
        aliased = dict(case_inputs)
        aliased[case_ids[1]] = {
            **case_inputs[case_ids[1]],
            "output_directory_fd": aliased_fd,
        }
        with pytest.raises(matrix_worker.PostrunMatrixWorkerError,
                           match="distinct output directory inode"):
            _evaluate(prepared, aliased)
        assert worker_calls == []
    finally:
        for output_fd in output_fds:
            os.close(output_fd)


def test_digest_mismatch_fails_closed_and_keeps_published_artifact(tmp_path, monkeypatch):
    prepared, case_ids, case_inputs, output_fds, roots = _inputs(tmp_path)
    _patch_synthetic_workers(
        monkeypatch, prepared, roots, mismatch_case=case_ids[0],
    )
    try:
        with pytest.raises(matrix_worker.PostrunMatrixWorkerError,
                           match="bridge/result or published-file binding mismatch"):
            _evaluate(prepared, case_inputs)
        output_dir = Path(os.readlink(f"/proc/self/fd/{output_fds[0]}"))
        assert (output_dir / trajectory_adapter.OUTPUT_FILENAME).is_file()
    finally:
        for output_fd in output_fds:
            os.close(output_fd)


def test_rejects_wrong_trajectory_sha_and_keeps_published_artifact(tmp_path, monkeypatch):
    prepared, case_ids, case_inputs, output_fds, roots = _inputs(tmp_path)
    _patch_synthetic_workers(
        monkeypatch, prepared, roots, bad_trajectory_sha_case=case_ids[0],
    )
    try:
        with pytest.raises(matrix_worker.PostrunMatrixWorkerError,
                           match="bridge/result or published-file binding mismatch"):
            _evaluate(prepared, case_inputs)
        output_dir = Path(os.readlink(f"/proc/self/fd/{output_fds[0]}"))
        assert (output_dir / trajectory_adapter.OUTPUT_FILENAME).is_file()
    finally:
        for output_fd in output_fds:
            os.close(output_fd)


def test_rejects_earlier_same_content_inode_replacement_during_later_case(
    tmp_path, monkeypatch,
):
    prepared, case_ids, case_inputs, output_fds, roots = _inputs(tmp_path)
    _patch_synthetic_workers(
        monkeypatch, prepared, roots,
        replace_earlier_on_case=case_ids[1], case_inputs=case_inputs,
    )
    try:
        with pytest.raises(matrix_worker.PostrunMatrixWorkerError,
                           match="final 15-case matrix/result or trajectory-file binding failed"):
            _evaluate(prepared, case_inputs)
    finally:
        for output_fd in output_fds:
            os.close(output_fd)


@pytest.mark.parametrize(
    "field",
    tuple(matrix_worker.MATRIX_V5_QUALIFICATION_BOUNDARIES),
)
def test_rejects_every_positive_nested_matrix_v5_boundary(field):
    case_ids = matrix_worker._case_ids()
    result = {name: None for name in matrix_v5.OUTPUT_FIELDS}
    result.update({
        "schema": matrix_v5.SCHEMA,
        "status": "frozen_15_case_composed_diagnostics_only_no_qualification",
        "case_count": 15,
        "case_ids": case_ids,
        "case_failure_denominator_fixed": True,
        "qualification_boundaries": copy.deepcopy(
            matrix_worker.MATRIX_V5_QUALIFICATION_BOUNDARIES
        ),
    })
    result["qualification_boundaries"][field] = (
        1 if field == "qualification_credit" else True
    )
    with pytest.raises(matrix_worker.PostrunMatrixWorkerError,
                       match="nested qualification boundaries"):
        matrix_worker._verify_matrix_result(result, case_ids)


def test_output_schema_matches_frozen_contract():
    assert matrix_worker.OUTPUT_FIELDS == {
        "schema", "status", "case_count", "case_ids", "case_failure_denominator_fixed",
        "case_results", "metric_matrix_v5", "matrix_case_bindings_match_postrun_bridges",
        "qualification_boundaries",
    }
    assert matrix_worker.CASE_COUNT == 15
    assert matrix_worker._case_ids() == matrix_v5._frozen_rows()[0]
