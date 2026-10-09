from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
WORKER_PATH = REFERENCE / "stage2_bi4_official_writer_calibration_worker_v2.py"
BUILDER_PATH = REFERENCE / "stage2_bi4_official_writer_calibration_request_v2.py"
CONTRACT_PATH = REFERENCE / "stage2_bi4_official_writer_calibration_contract_v2.json"
FIXTURE_PATH = REFERENCE / "stage2_bi4_official_fixture_writer_v2.cpp"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v2_validator_runs_asymmetric_golden_and_all_negative_mutations():
    worker = _load(WORKER_PATH, "stage2_bi4_official_writer_calibration_worker_v2_test")
    result = worker._self_test()
    assert result["status"] == "PASS"
    assert result["compiled_writer_invoked"] is False
    assert result["bi4_dump_invoked"] is False
    assert result["production_payload_read"] is False
    assert result["qualification_credit"] == 0
    cases = {case["name"]: case for case in result["cases"]}
    assert cases["real_validator_accepts_asymmetric_golden"]["status"] == "PASS"
    assert cases["full_role_counts_and_mk_mapping"]["status"] == "PASS"
    negative = cases["all_contract_negative_mutations_rejected"]
    assert negative["status"] == "PASS"
    assert len(negative["detail"]) == 6
    assert {item["status"] for item in negative["detail"]} == {"REJECTED_BY_ACTUAL_VALIDATOR"}


def test_v2_builder_and_worker_manifest_have_recursive_source_closure(tmp_path):
    builder = _load(BUILDER_PATH, "stage2_bi4_official_writer_calibration_request_v2_test")
    request_path = tmp_path / "request.json"
    manifest_path = tmp_path / "manifest.json"
    request = builder.build(
        output_request=request_path,
        output_manifest=manifest_path,
        case_id="TEST_F1_BI4_CALIBRATION_V2",
        attempt_id="test-f1-bi4-calibration-v2-001",
    )
    assert request["variant_schema"] == "ds02.stage2.f1.bi4-official-writer-calibration-request.v2"
    assert request["status"] == "READY_FOR_PARENT_GUARDED_CPU_MANUFACTURED_BI4_CALIBRATION_V2"
    assert request["execution_allowed"] is False
    assert request["native_payload_read"] is False
    assert request["qualification_credit"] == 0
    assert request["command"][0] == "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
    assert any(path.endswith("RunExceptionDef.h") for path in request["input_files"])
    assert any(path.endswith("stage2_bi4_official_fixture_writer_v2.cpp") for path in request["input_files"])
    assert any(path.endswith("stage2_bi4_official_writer_calibration_worker_v2.py") for path in request["input_files"])
    assert not [path for path in request["input_files"] if Path(path).suffix.lower() in {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}]

    worker = _load(WORKER_PATH, "stage2_bi4_official_writer_calibration_worker_v2_closure_test")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    before, records = worker._guard_source_records(manifest)
    worker._assert_quoted_include_closure(records)
    assert len(before) == len(manifest["source_files"])
    assert manifest["schema"] == "ds02.stage2.f1.bi4-official-writer-calibration-manifest.v2"


def test_v2_command_guard_streams_and_caps_child_log(tmp_path):
    worker = _load(WORKER_PATH, "stage2_bi4_official_writer_calibration_worker_v2_stream_test")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    log = tmp_path / "child.log"
    result = worker._run_command(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 2000000)"],
        cwd=tmp_path,
        log=log,
        timeout_s=10.0,
        scratch_root=scratch,
        scratch_cap=16 * 1024 * 1024,
    )
    assert result["returncode"] == 0
    assert result["streaming_log_drain"] is True
    assert result["log_capped"] is True
    assert result["log_total_bytes_seen"] == 2_000_000
    assert log.stat().st_size <= worker.MAX_LOG_BYTES


def test_v2_contract_keeps_science_qualification_unknown_and_asymmetric_values():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    assert contract["scope"]["scientific_credit"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert contract["manufactured_particles"]["positions_m"][0] == [-3.125, 4.5, 0.25]
    assert contract["manufactured_particles"]["velocities_m_per_s"][4] == [-2.0, 3.5, 0.125]
    assert "writer.ConfigParticles" in fixture
    assert "writer.AddPartData" in fixture
    assert "writer.SaveFilePart" in fixture
    assert "const unsigned idp[np]={10u,11u,20u,100u,101u,102u}" in fixture
