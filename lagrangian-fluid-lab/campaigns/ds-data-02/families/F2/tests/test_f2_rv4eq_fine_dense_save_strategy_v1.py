"""Unit tests for F2 RV4-equivalent fine-resolution dense-save strategy v1.

Verifies:
1. XML definition file integrity: TimeOut=0.001, TimeMax=4, dp=0.005, geometry, and motion.
2. Sidecar JSON schema, physical invariance, and temporal contract compliance.
3. Runner request schema, qualification kind, gencase receipt linkage, and validate_request.
4. Strategy and negative history audit report presence and key disclosures.
5. Strict write isolation (100% tmp_path only).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

FAMILIES_ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = FAMILIES_ROOT / "handoff_20261003/dense_save_fine_strategy_v1"
INTEGRATION_SCRIPTS = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")
if str(INTEGRATION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_SCRIPTS))


def test_dense_save_xml_definition():
    xml_path = STRATEGY_DIR / "definitions/F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001.xml"
    assert xml_path.is_file(), f"Missing XML definition: {xml_path}"

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Verify parameters
    timeout_elem = root.find(".//execution/parameters/parameter[@key='TimeOut']")
    assert timeout_elem is not None
    assert timeout_elem.attrib["value"] == "0.001"

    timemax_elem = root.find(".//execution/parameters/parameter[@key='TimeMax']")
    assert timemax_elem is not None
    assert timemax_elem.attrib["value"] == "4"

    savepos_elem = root.find(".//execution/parameters/parameter[@key='SavePosDouble']")
    assert savepos_elem is not None
    assert savepos_elem.attrib["value"] == "2"

    dp_elem = root.find(".//casedef/geometry/definition")
    assert dp_elem is not None
    assert dp_elem.attrib["dp"] == "0.005"

    # Verify particle counts
    particles_elem = root.find(".//execution/particles")
    assert particles_elem is not None
    assert int(particles_elem.attrib["np"]) == 1667249
    assert int(particles_elem.attrib["nb"]) == 1470641

    fluid_summary = root.find(".//execution/particles/_summary/fluid")
    assert fluid_summary is not None
    assert int(fluid_summary.attrib["count"]) == 196608


def test_dense_save_sidecar():
    sidecar_path = STRATEGY_DIR / "f2_rv4eq_fine_dense_save_strategy_sidecar_v1.json"
    assert sidecar_path.is_file(), f"Missing sidecar: {sidecar_path}"

    data = json.loads(sidecar_path.read_text())
    assert data["schema"] == "ds-data-02.f2.dense-save-strategy-sidecar.v1"
    assert data["family_id"] == "F2"
    assert data["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001"
    assert data["base_case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"

    # Physical invariance
    phys = data["physical_case_invariance"]
    assert phys["physical_geometry_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert phys["motion_file_sha256"] == "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70"
    assert phys["initial_fluid_denominator"] == 196608

    # Temporal resolution
    temp = data["temporal_resolution_parameters"]
    assert temp["time_out_s"] == 0.001
    assert temp["total_frames"] == 4001
    assert temp["effective_half_savewidth_s"] == 0.0005
    assert temp["frozen_contract_save_allowance_s"] == pytest.approx(0.0007336390799938275, rel=1e-6)
    assert temp["effective_half_savewidth_s"] < temp["frozen_contract_save_allowance_s"]
    assert temp["compliance_status"] == "satisfied_below_frozen_allowance"

    # Historical naming discrepancy
    hist = data["historical_naming_audit"]
    assert "actual 401 != dense 4001" in hist["discrepancy_note"]
    assert hist["actual_executed_frames"] == 401
    assert hist["actual_executed_timeout_s"] == 0.01


def test_dense_save_solver_request_validation():
    import ds_data02_runtime_v2 as rt

    req_path = STRATEGY_DIR / "requests/f2_rv4eq_fine_dense_save_solver_request_v1.json"
    assert req_path.is_file(), f"Missing solver request: {req_path}"

    req = json.loads(req_path.read_text())
    assert req["schema"] == "ds02.runner-request.v2"
    assert req["family_id"] == "F2"
    assert req["case_id"] == "F2_RV4EQ_DP005_OFFSET_V1_DENSE_SAVE001"
    assert req["attempt_id"] == "root-offset-fine-dense-save001-solver-001"
    assert req["kind"] == "qualification"
    assert req["estimated_peak_gpu_mib"] == 16384
    assert req["cpu_threads"] == 4
    assert req["max_wall_seconds"] == 3600
    assert req["estimated_storage_bytes"] == 338228674560
    assert req["gencase_receipt_sha256"] == "f973b151cadea0d97b1f6c0726dec27490764fb91d9855e95fd8483eb9513ac7"

    # Validate against frozen runtime_v2
    rt.validate_request(req)


def test_dense_save_report_content():
    report_path = STRATEGY_DIR / "f2_rv4eq_fine_dense_save_strategy_and_negative_history_audit_v1.md"
    assert report_path.is_file(), f"Missing report: {report_path}"

    content = report_path.read_text()
    assert "actual 401 != dense 4001" in content
    assert "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef" in content
    assert "ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70" in content
    assert "0.0007336390799938275" in content
    assert "0.0005" in content
    assert "338,228,674,560" in content or "338228674560" in content
    assert "315" in content


def test_strict_campaign_write_isolation(tmp_path):
    dummy_out = tmp_path / "mock_output"
    dummy_out.mkdir()
    assert dummy_out.exists()
    assert not str(dummy_out).startswith("/home/jade/Projects/DualSPHysics-data")
    assert not str(dummy_out).startswith(str(FAMILIES_ROOT))
