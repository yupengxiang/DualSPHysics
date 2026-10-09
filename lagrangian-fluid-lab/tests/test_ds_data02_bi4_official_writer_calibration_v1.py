from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
WORKER_PATH = REFERENCE / "stage2_bi4_official_writer_calibration_worker_v1.py"
BUILDER_PATH = REFERENCE / "stage2_bi4_official_writer_calibration_request_v1.py"
CONTRACT_PATH = REFERENCE / "stage2_bi4_official_writer_calibration_contract_v1.json"
FIXTURE_PATH = REFERENCE / "stage2_bi4_official_fixture_writer_v1.cpp"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manufactured_worker_selftest_has_no_payload_or_scientific_credit():
    worker = _load(WORKER_PATH, "stage2_bi4_official_writer_calibration_worker_test")
    result = worker._self_test()
    assert result["status"] == "PASS"
    assert result["compiled_writer_invoked"] is False
    assert result["bi4_dump_invoked"] is False
    assert result["production_payload_read"] is False
    assert result["qualification_credit"] == 0


def test_builder_source_only_request_has_literal_venv_and_no_payload(tmp_path):
    builder = _load(BUILDER_PATH, "stage2_bi4_official_writer_calibration_request_test")
    request_path = tmp_path / "request.json"
    manifest_path = tmp_path / "manifest.json"
    request = builder.build(
        output_request=request_path,
        output_manifest=manifest_path,
        case_id="TEST_F1_BI4_CALIBRATION",
        attempt_id="test-f1-bi4-calibration-001",
    )
    assert request["status"] == "READY_FOR_PARENT_GUARDED_CPU_MANUFACTURED_BI4_CALIBRATION"
    assert request["execution_allowed"] is False
    assert request["native_payload_read"] is False
    assert request["qualification_credit"] == 0
    assert not [path for path in request["input_files"] if Path(path).suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}]
    assert request["command"][0] == "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
    assert "--run" in request["command"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_only_preparation"]["production_native_payload_read"] is False
    assert len(manifest["source_files"]) >= 20


def test_fixture_uses_official_writer_and_registered_role_contract():
    source = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "JPartDataBi4 writer" in source
    assert "writer.ConfigParticles" in source
    assert "writer.AddPartData" in source
    assert "writer.SaveFilePart" in source
    assert "const unsigned idp[np]={10u,11u,20u,100u,101u,102u}" in source
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert contract["scope"]["scientific_credit"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert {row["name"] for row in contract["negative_fixtures"]} >= {
        "duplicate_id",
        "wrong_units_mm_or_g",
        "swapped_x_y_components",
        "fixed_particle_in_fluid_slice",
        "nonfinite_position_or_velocity",
        "wrong_mass_fluid",
    }
