"""Small contract tests for the forward F3-S2 source repair request."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f3_s2_source_clone_gencase_v1.py"
REQUEST = (
    Path(__file__).parents[1]
    / "campaigns/ds-data-02/stage2/requests/"
    / "f3-s2-source-clone-gencase-v1-root-forward-082-001/"
    / "f3-s2-source-clone-gencase-v1-request.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f3_s2_source_clone_gencase_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_request_defers_existing_bi4_and_binds_exact_s2_control():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    source = request["source_binding"]
    assert request["cpu_task_kind"] == "gencase"
    assert request["gencase_launch"] is True
    assert request["solver_launch"] is False
    assert request["hdf5_read"] is False
    assert source["physical_case_id"] == "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
    assert source["control"]["sha256"] == module().EXPECTED_CONTROL_SHA256
    bi4 = source["source_bi4"]["path"]
    assert bi4 not in request["input_files"]
    assert request["deferred_input_files"] == [bi4]
    assert request["deferred_input_stats"][bi4]["sha256"] == "PARENT_GUARD_COMPUTED"
    assert source["s1_receipt_used"] is False


def test_prepared_report_rejects_wrong_control(tmp_path):
    loaded = module()
    report = {
        "physical_case_id": loaded.PHYSICAL_CASE_ID,
        "xml_sha256": loaded.EXPECTED_XML_SHA256,
        "forcing_sha256": "wrong-control",
        "bi4_sha256": loaded.EXPECTED_SOURCE_BI4_SHA256,
        "physical_binding": {
            "physical_case_id": loaded.PHYSICAL_CASE_ID,
            "geometry": {"initial_fluid": {"low_m": [-0.45, -0.09, 0.0], "size_m": [0.9, 0.18, 0.09]}},
            "initial_state": {"initial_mass_total_kg": loaded.EXPECTED_CONTINUOUS_MASS_KG},
        },
    }
    path = tmp_path / "prepared-input-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="control digest"):
        loaded._source_report(path)


def test_xml_summary_keeps_discrete_mass_separate_from_owner():
    loaded = module()
    xml = """<?xml version='1.0'?>
    <case><casedef><geometry><definition dp='0.006'/></geometry>
    </casedef><execution><special><accinputs><accinput><acctimesfile value='CaseSloshingAccData.csv'/></accinput></accinputs></special>
    <particles><fixed count='2'/><fluid count='3'/></particles>
    <constants><massfluid value='0.000216'/></constants></execution></case>"""
    path = Path(__file__).with_name("_tmp_f3_s2_summary.xml")
    try:
        path.write_text(xml, encoding="utf-8")
        summary = loaded._xml_summary(path)
        assert summary["particles"]["fluid"] == 3
        assert summary["sample_fluid_mass_kg"] == pytest.approx(0.000648)
        assert summary["acctimesfile"] == "CaseSloshingAccData.csv"
    finally:
        path.unlink(missing_ok=True)
