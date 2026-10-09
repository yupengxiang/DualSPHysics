from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/f2_coarse_active_stream_result_sidecar_v1.py"


def module():
    spec = importlib.util.spec_from_file_location("f2_result_sidecar_v1_test", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def synthetic_report():
    case = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
    native_mass = 0.000681472010910511
    xml_whole = 18.910848
    excluded = 153 * native_mass
    rows = [{"case_key": case, "idp": index, "motive": 1} for index in range(153)]
    return {
        "schema": "ds02.stage2.f2.coarse-active-stream.v8",
        "status": "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_V8_EXACT_NATIVE_MASS_BITS",
        "case_key": case,
        "physical_case_id": case,
        "input_stability": {"all_equal": True},
        "active_fluid_stream": {
            "frame_count": 401,
            "xml_whole_initial_fluid_mass_kg": xml_whole,
            "native_whole_initial_fluid_mass_kg": 27750 * native_mass,
            "native_massfluid_kg": native_mass,
            "massfluid_bit_gate": {
                "expected_bits_hex": "000000009a54463f",
                "all_frames_exact_match": True,
                "absolute_tolerance": None,
                "mass_rescaling": False,
            },
        },
        "native_identity_join": {"rows": rows},
        "mass_and_material": {
            "native_excluded_mass_lower_bound_kg": excluded,
            "unknown_identity_mass_screen": {
                "whole_initial_fraction_max": 0.003,
                "observed_native_lower_bound_fraction": excluded / xml_whole,
                "screen_result_only": False,
            },
        },
        "claim_boundary": {
            "physical_destination_or_legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
    }


def synthetic_receipt(root: Path):
    case = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095"
    return {
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "output_root": str(root),
        "request": {
            "request_schema": "ds02.stage2.f2.coarse-active-stream.v8-request.v1",
            "physical_case_id": case,
            "output": {"schema": "ds02.stage2.f2.coarse-active-stream.v8"},
        },
    }


def test_sidecar_preserves_frozen_xml_screen_failure_and_unknown_qualification(tmp_path):
    loaded = module()
    report_path = tmp_path / "v8.json"
    receipt_path = tmp_path / "execution-receipt.json"
    output_path = tmp_path / "sidecar.json"
    report_path.write_text(json.dumps(synthetic_report()), encoding="utf-8")
    receipt_path.write_text(json.dumps(synthetic_receipt(tmp_path)), encoding="utf-8")
    result = loaded.sidecar(report_path, receipt_path, output_path)
    assert result["status"] == "V8_STREAM_SOURCE_CLOSED_UNKNOWN_MASS_SCREEN_FAIL"
    sidecar = json.loads(output_path.read_text(encoding="utf-8"))
    product = sidecar["product"]
    assert product["native_omission_count"] == 153
    assert product["observed_unknown_identity_lower_bound_fraction_xml"] > 0.003
    assert product["mass_screen"] == "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003"
    assert sidecar["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert sidecar["read_policy"]["raw_bi4_opened"] is False


def test_sidecar_rejects_report_that_claims_mass_screen_pass(tmp_path):
    loaded = module()
    report = synthetic_report()
    report["mass_and_material"]["unknown_identity_mass_screen"]["screen_result_only"] = True
    report_path = tmp_path / "v8.json"
    receipt_path = tmp_path / "execution-receipt.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    receipt_path.write_text(json.dumps(synthetic_receipt(tmp_path)), encoding="utf-8")
    with pytest.raises(loaded.SidecarError, match="does not preserve"):
        loaded.sidecar(report_path, receipt_path, tmp_path / "sidecar.json")


def test_sidecar_rejects_wrong_case_identity(tmp_path):
    loaded = module()
    report = synthetic_report()
    report["native_identity_join"]["rows"][0]["case_key"] = "OTHER_CASE"
    report_path = tmp_path / "v8.json"
    receipt_path = tmp_path / "execution-receipt.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    receipt_path.write_text(json.dumps(synthetic_receipt(tmp_path)), encoding="utf-8")
    with pytest.raises(loaded.SidecarError, match="not unique case-qualified"):
        loaded.sidecar(report_path, receipt_path, tmp_path / "sidecar.json")
