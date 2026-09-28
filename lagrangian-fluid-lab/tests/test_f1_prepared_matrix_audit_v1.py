from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f1_prepared_matrix_audit_v1 as audit


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    matrix_root = tmp_path / "prepared" / "F1_H1_qualification"
    jobs_root = tmp_path / "f1-reference-qualification-jobs"
    matrix_root.mkdir(parents=True)
    jobs_root.mkdir(parents=True)

    rows = []
    job_rows = []
    for index in range(audit.EXPECTED_CELLS):
        case_id = f"CORE_F1_cell_{index:02d}"
        design_cell = "internal_time" if index == 13 else "native_output" if index == 14 else "spatial"
        q = index / 14
        dp_m = 0.0075
        cell_root = matrix_root / f"cell-{index:02d}"
        cell_root.mkdir()
        prepared_path = cell_root / "prepared.json"
        prepared_path.write_text(json.dumps({
            "schema": "core.cfd.v1",
            "config": {
                "family": "F1",
                "stage": "qualification",
                "qualification_claim": "none",
                "qualified": False,
                "case_id": case_id,
                "design_cell": design_cell,
                "parameter": {"q": q},
                "dp_m": dp_m,
            },
            "preflight_pass": True,
            "native_initial": {"initial_state_pass": True},
            "mass_preflight": {"mass_gate_pass": True},
            "definition_audit": {"mass_rescaling": False},
            "inputs": {"metadata_only": True},
            "solver_binary": "/metadata/solver",
            "decoder": "/metadata/decoder",
            "generated_prefix": "/metadata/generated/case",
            "source_template": "/metadata/source.xml",
            "qualification_claim": "none; preparation only",
        }, sort_keys=True))
        job_path = jobs_root / f"f1-h1-qualification-cell-{index:02d}.json"
        job_path.write_text(json.dumps({
            "schema": "core.cfd.job.v1",
            "job_id": f"f1-h1-qualification-cell-{index:02d}",
            "category": "qualification",
            "qualification_claim": "none",
            "prepared_case_id": case_id,
            "required_outputs": [
                "product/result.json",
                "product/trajectory.h5",
                "product/audit.json",
                "product/observations.json",
            ],
            "input_files": [
                {"path": str(prepared_path), "sha256": _digest(prepared_path)},
                {"path": "/metadata/solver", "sha256": "a" * 64},
                {"path": "/metadata/decoder", "sha256": "b" * 64},
            ],
            "static_validation": {
                "case_id": case_id,
                "static_quality_pass": True,
                "preflight_pass": True,
                "qualification_claim": "none",
            },
        }, sort_keys=True))
        rows.append({
            "index": index,
            "case_id": case_id,
            "q": q,
            "dp_m": dp_m,
            "design_cell": design_cell,
            "prepared": str(prepared_path),
            "preflight_pass": True,
            "static_quality_pass": True,
            "mass_gate_pass": True,
        })
        job_rows.append({
            "index": index,
            "job_id": f"f1-h1-qualification-cell-{index:02d}",
            "path": str(job_path),
            "prepared": str(prepared_path),
        })

    matrix_path = matrix_root / "prepared-matrix.json"
    matrix_path.write_text(json.dumps({
        "schema": audit.MATRIX_SCHEMA,
        "revision_id": "F1_H1_geometry_observer_qualification_v1",
        "complete": True,
        "qualification_claim": "none",
        "cells": rows,
    }, sort_keys=True))
    jobs_path = jobs_root / "f1-reference-qualification-jobs.json"
    jobs_path.write_text(json.dumps({
        "schema": "core.cfd.jobs.v1",
        "revision_id": "F1_H1_geometry_observer_qualification_v1",
        "matrix_sha256": _digest(matrix_path),
        "job_count": audit.EXPECTED_CELLS,
        "execution_status": "prepared_only; canary gate required before qualification",
        "qualification_claim": "none",
        "canary_dependency": "f1-h1-reference-fullwindow-canary-001",
        "jobs": job_rows,
    }, sort_keys=True))
    return matrix_path, jobs_path


def test_audit_closes_fifteen_prepared_rows_without_runtime_credit(tmp_path: Path) -> None:
    matrix_path, jobs_path = _fixture(tmp_path)

    report = audit.audit_matrix(matrix_path, jobs_path)

    assert report["prepared_input_hash_closure"] == {
        "required_cells": 15,
        "verified_cells": 15,
        "pass": True,
    }
    assert report["prepared_cell_count"] == 15
    assert report["formal_runtime_rows"] == 0
    assert report["missing_runtime_rows"] == 15
    assert report["fixed_failure_denominator"] is True
    assert report["T1_numerical"] is False
    assert report["T2"] is False
    assert report["credit"] == 0


def test_runtime_output_paths_are_metadata_only(tmp_path: Path) -> None:
    matrix_path, jobs_path = _fixture(tmp_path)

    report = audit.audit_matrix(matrix_path, jobs_path)

    controls = report["execution_controls"]
    assert controls["nested_artifact_paths_followed"] is False
    assert controls["production_hdf5_opened"] is False
    assert controls["production_bi4_opened"] is False
    assert controls["production_trajectory_opened"] is False
    assert all(cell["required_runtime_outputs_metadata_only"] for cell in report["cells"])


def test_prepared_hash_drift_fails_closed(tmp_path: Path) -> None:
    matrix_path, jobs_path = _fixture(tmp_path)
    prepared = Path(json.loads(matrix_path.read_text())["cells"][0]["prepared"])
    prepared.write_text(prepared.read_text() + "\n")

    with pytest.raises(audit.AuditError, match="prepared input hash mismatch"):
        audit.audit_matrix(matrix_path, jobs_path)


def test_denominator_reordering_fails_closed(tmp_path: Path) -> None:
    matrix_path, jobs_path = _fixture(tmp_path)
    matrix = json.loads(matrix_path.read_text())
    matrix["cells"][1]["index"] = 0
    matrix_path.write_text(json.dumps(matrix, sort_keys=True))

    with pytest.raises(audit.AuditError, match="matrix row index drift"):
        audit.audit_matrix(matrix_path, jobs_path)


def test_audit_output_is_immutable(tmp_path: Path) -> None:
    matrix_path, jobs_path = _fixture(tmp_path)
    output = tmp_path / "audit.json"

    report = audit.audit_matrix(matrix_path, jobs_path, output)

    assert json.loads(output.read_text()) == report
    with pytest.raises(FileExistsError):
        audit.audit_matrix(matrix_path, jobs_path, output)
