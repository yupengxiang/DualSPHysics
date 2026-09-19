"""CPU-only tests for the B1R exact material-sidecar lineage contract."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import l2_b1r_sidecar_contract as module


LAB = Path(__file__).resolve().parents[1]
F1_MKCELLS = LAB / "cases" / "F1" / "F1_center_obstacle" / "generated" / "F1_center_obstacle_MkCells.vtk"


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    case_id = "F1R_contract_fixture"
    attempt_id = "20260919T000000.000000Z-fixture"
    hdf5_path = tmp_path / f"{case_id}.h5"
    time = np.asarray([0.0, 0.5, 1.0], dtype=np.float64)
    with h5py.File(hdf5_path, "w") as handle:
        handle.attrs["case_id"] = case_id
        handle.attrs["attempt_id"] = attempt_id
        handle.attrs["family"] = "F1"
        handle.attrs["schema_version"] = 3
        handle.create_dataset("time", data=time)

    attempt_dir = tmp_path / f"{attempt_id}.complete"
    (attempt_dir / "data").mkdir(parents=True)
    (attempt_dir / "data" / "PartOut_000.obi4").write_bytes(b"fixture-PartOut")
    (attempt_dir / "attempt.json").write_text(json.dumps({
        "schema_version": 1,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "status": "completed",
        "returncode": 0,
    }), encoding="utf-8")
    vtk_path = tmp_path / f"{case_id}_MkCells.vtk"
    vtk_path.write_bytes(F1_MKCELLS.read_bytes())
    return hdf5_path, attempt_dir, vtk_path


def _generate(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    hdf5_path, attempt_dir, vtk_path = _fixture(tmp_path)
    sidecar_path = tmp_path / "new" / "F1R_contract_fixture_sidecar.h5"
    report = module.generate_sidecar(hdf5_path, vtk_path, attempt_dir, sidecar_path)
    assert report["status"] == "pass"
    return hdf5_path, attempt_dir, vtk_path, sidecar_path


def _codes(report: dict) -> set[str]:
    return {str(item["code"]) for item in report["issues"]}


def test_generate_binds_new_canary_partout_and_exact_geometry(tmp_path: Path):
    hdf5_path, attempt_dir, vtk_path, sidecar_path = _generate(tmp_path)
    report = module.validate_sidecar(hdf5_path, vtk_path, attempt_dir, sidecar_path)
    assert report["controls"] == {
        "solver_launched": False,
        "gencase_launched": False,
        "gpu_used": False,
        "inputs_read_only": True,
        "interpolation_applied": False,
        "resume_state_modified": False,
        "existing_experiment_files_modified": False,
    }
    assert report["time_axis"]["exact_equal"] is True
    assert report["geometry"]["exact_geometry_match"] is True
    assert report["attempt"]["partout_files"][0]["path"] == "data/PartOut_000.obi4"
    with h5py.File(sidecar_path, "r") as handle:
        assert handle.attrs["material_sidecar_contract"] == module.CONTRACT_SCHEMA
        assert handle.attrs["source_attempt_id"] == "20260919T000000.000000Z-fixture"
        assert handle.attrs["time_axis_policy"] == module.EXACT_TIME_POLICY
        assert handle.attrs["source_hdf5_sha256"] == module._sha256_file(hdf5_path)
        assert handle.attrs["source_mkcells_sha256"] == module._sha256_file(vtk_path)


def test_one_nanosecond_axis_change_is_rejected_without_interpolation(tmp_path: Path):
    hdf5_path, attempt_dir, vtk_path, sidecar_path = _generate(tmp_path)
    with h5py.File(sidecar_path, "r+") as handle:
        values = np.asarray(handle["time"][:], dtype=np.float64)
        values[1] += 1.0e-9
        handle["time"][:] = values
    report = module.preflight(hdf5_path, vtk_path, attempt_dir, sidecar_path=sidecar_path)
    assert report["status"] == "rejected"
    assert "time_axis_mismatch" in _codes(report)
    assert report["time_axis"]["max_abs_delta_s"] == pytest.approx(1.0e-9)
    assert report["time_axis"]["interpolation_applied"] is False
    # R5's old allclose(atol=1e-8) check would accept this perturbation; B1R
    # intentionally does not.
    assert report["time_axis"]["expected_sha256"] != report["time_axis"]["actual_sha256"]
    with pytest.raises(module.ContractViolation, match="time_axis_mismatch"):
        module.validate_sidecar(hdf5_path, vtk_path, attempt_dir, sidecar_path)


def test_old_case_id_and_old_sidecar_axis_are_both_rejected(tmp_path: Path):
    hdf5_path, attempt_dir, vtk_path = _fixture(tmp_path)
    old_sidecar = LAB / "campaigns" / "v0.1-candidate" / "sidecars" / "r5-f1" / "R4_F1_center_obstacle_medium.h5"
    report = module.preflight(hdf5_path, vtk_path, attempt_dir, sidecar_path=old_sidecar)
    assert report["status"] == "rejected"
    assert "sidecar_case_id_mismatch" in _codes(report)
    assert "time_axis_mismatch" in _codes(report)
    assert report["time_axis"]["expected_count"] == 3
    assert report["time_axis"]["actual_count"] == 1501
    assert report["controls"]["solver_launched"] is False
    assert report["controls"]["gpu_used"] is False


def test_old_boundary_geometry_is_rejected_even_when_metadata_is_retained(tmp_path: Path):
    hdf5_path, attempt_dir, vtk_path, sidecar_path = _generate(tmp_path)
    with h5py.File(sidecar_path, "r+") as handle:
        triangles = handle["triangles_world"]
        changed = np.asarray(triangles[0, 0], dtype=np.float64)
        changed[0] += 1.0e-3
        triangles[0, 0] = changed
    report = module.preflight(hdf5_path, vtk_path, attempt_dir, sidecar_path=sidecar_path)
    assert report["status"] == "rejected"
    assert "boundary_geometry_mismatch" in _codes(report)
    assert report["geometry"]["triangle_array_exact"] is False
    assert report["geometry"]["triangle_mk_exact"] is True


def test_missing_partout_is_a_bounded_rejection(tmp_path: Path):
    hdf5_path, attempt_dir, vtk_path = _fixture(tmp_path)
    (attempt_dir / "data" / "PartOut_000.obi4").unlink()
    report = module.preflight(hdf5_path, vtk_path, attempt_dir)
    assert report["status"] == "rejected"
    assert "invalid_attempt" in _codes(report)
    assert report["controls"]["resume_state_modified"] is False


def test_generate_refuses_overwrite(tmp_path: Path):
    hdf5_path, attempt_dir, vtk_path = _fixture(tmp_path)
    output = tmp_path / "existing.h5"
    output.write_bytes(b"do-not-overwrite")
    with pytest.raises(FileExistsError, match="overwrite"):
        module.generate_sidecar(hdf5_path, vtk_path, attempt_dir, output)
    assert output.read_bytes() == b"do-not-overwrite"
