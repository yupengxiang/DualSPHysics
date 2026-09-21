import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import core_f3_cfd_source as source
from scripts.core_runtime import validate_spec


def test_source_matrix_is_minimal_and_exact():
    cases = source.source_cases()
    assert list(cases) == [
        "f3_production_amp0p95_native010",
        "f3_fine_amp0p95_native010",
        "f3_production_amp1p05_native010",
        "f3_fine_amp1p05_native010",
        "f3_production_amp1p1_native002",
    ]
    rows = [row for case in cases.values() for row in case["matrix_rows"]]
    assert sorted(rows) == [16, 17, 18, 19, 20, 21, 22, 23, 26, 27]
    assert cases["f3_production_amp0p95_native010"]["q"] == pytest.approx(.25)
    assert cases["f3_production_amp0p95_native010"]["drive_amplitude"] == pytest.approx(.95)
    assert cases["f3_production_amp1p05_native010"]["q"] == pytest.approx(.75)
    assert cases["f3_production_amp1p1_native002"]["q"] == pytest.approx(1.)
    assert cases["f3_production_amp1p1_native002"]["output_interval_s"] == pytest.approx(.002)
    assert all(case["time_max_s"] == pytest.approx(8.35) for case in cases.values())


def test_prepare_production_amp095_is_hash_bound_and_fresh(tmp_path):
    output = tmp_path / "prepared"
    record = source.prepare_case("f3_production_amp0p95_native010", output)
    assert record["status"] == "prepared_only"
    assert record["launch_allowed"] is False
    assert record["qualification_claim"] == source.QUALIFICATION_ONLY
    assert record["config"]["q"] == pytest.approx(.25)
    assert record["config"]["drive_amplitude"] == pytest.approx(.95)
    assert record["config"]["output_interval_s"] == pytest.approx(.01)
    assert record["config"]["time_max_s"] == pytest.approx(8.35)
    assert record["mass_preflight"]["pass"]
    assert record["native_initial"]["fluid_particles"] == 34560
    assert record["source_provenance"]["proposal_sha256"] == source.PROPOSAL_SHA256
    assert record["control_generation"]["generated_sha256"] == "b199cb21d5f930682e84918b846fd9ee522eb0bad766f9e7aed2e7f71d8fc63c"
    root = ET.parse(output / "F3_CELL3_plain_0p0075.xml").getroot()
    values = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    assert values["TimeMax"] == "8.35"
    assert values["TimeOut"] == "0.01"
    assert values["CoefDtMin"] == "0.05"
    assert record["config"]["cadence"] == "native"
    with pytest.raises(FileExistsError):
        source.prepare_case("f3_production_amp0p95_native010", output)


def test_job_spec_is_core_runtime_compatible(tmp_path):
    prepared = source.prepare_case("f3_production_amp0p95_native010", tmp_path / "prepared")
    prepared_path = tmp_path / "prepared" / "prepared.json"
    spec = source.make_job(prepared_path, tmp_path / "job.json",
                           job_id="cfd-f3-source-test-v1", host="ada")
    assert spec["schema"] == source.JOB_SCHEMA
    assert spec["qualification_claim"] == source.QUALIFICATION_ONLY
    assert spec["central_ledger_mutation"] == 0
    assert spec["gpu_started"] is False
    assert spec["argv"][-1] == "{attempt_dir}/product"
    assert "-gpu:0" not in spec["argv"]
    assert any(item["path"] == str(prepared_path.resolve()) for item in spec["input_files"])
    assert any(item["path"].endswith("core_f3_cfd_source.py") for item in spec["input_files"])
    validate_spec(json.loads(json.dumps(spec)))


def test_run_requires_scheduler_assigned_cuda_without_launch(tmp_path, monkeypatch):
    source.prepare_case("f3_production_amp0p95_native010", tmp_path / "prepared")
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    with pytest.raises(ValueError, match="exactly one CUDA_VISIBLE_DEVICES"):
        source.run_case(tmp_path / "prepared" / "prepared.json", tmp_path / "product")
    assert not (tmp_path / "product").exists()
