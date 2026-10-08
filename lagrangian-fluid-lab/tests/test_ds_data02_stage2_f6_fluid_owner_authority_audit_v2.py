from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_fluid_owner_authority_audit_v2.py"
REQUEST = (
    ROOT / "campaigns/ds-data-02/stage2/requests/"
    / "f6-fluid-owner-authority-audit-v2-root-forward-097-001/"
    / "f6-fluid-owner-authority-audit-v2-request.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f6_fluid_owner_authority_audit_v2", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_sample_mass_gate_uses_discrete_target_only():
    loaded = module()
    assert loaded.classify_sample(5120.0, 5120.0)["gate"] == "PASS_TARGET_ONE_PERCENT_DIAGNOSTIC"
    coarse = loaded.classify_sample(5078.125, 5120.0)
    fine = loaded.classify_sample(4904.952, 5120.0)
    assert coarse["error_percent"] == pytest.approx(-0.81787109375)
    assert coarse["gate"] == "PASS_TARGET_ONE_PERCENT_DIAGNOSTIC"
    assert fine["error_percent"] == pytest.approx(-4.20015625)
    assert fine["gate"] == "HARDFAIL_TARGET_OVER_TWO_PERCENT"
    assert "continuum" in fine["basis"]


def test_xml_summary_marks_fluid_drawbox_as_producer_selector(tmp_path: Path):
    loaded = module()
    xml = tmp_path / "case.xml"
    xml.write_text(
        "<case><casedef><definition dp='0.02'/><massbody value='128'/><center x='2.4' y='1.2' z='1.08'/>"
        "<inertia x='8.53333333333' y='8.53333333333' z='13.6533333333'/></casedef>"
        "<particles><fixed count='2'/><floating count='3'/><fluid count='4'/></particles>"
        "<massfluid value='0.5'/><commands><mainlist><setmkfluid mk='0'/><drawbox><boxfill>solid</boxfill>"
        "<point x='0' y='0' z='0'/><size x='1' y='2' z='3'/></drawbox></mainlist></commands></case>",
        encoding="utf-8",
    )
    result = loaded.xml_summary(xml, "fixture")
    assert result["fluid_sample_mass_kg"] == pytest.approx(2.0)
    assert result["fluid_drawboxes"][0]["volume_m3"] == pytest.approx(6.0)
    assert result["fluid_drawboxes"][0]["boxfill"] == "solid"


def test_xml_comment_is_not_owner_authority(tmp_path: Path):
    loaded = module()
    xml = tmp_path / "case.xml"
    xml.write_text(
        "<case><casedef><definition dp='0.02'/><massbody value='128'/><center x='2.4' y='1.2' z='1.08'/>"
        "<inertia x='8.53333333333' y='8.53333333333' z='13.6533333333'/></casedef>"
        "<particles><fluid count='1'/></particles><massfluid value='1'/><commands><mainlist>"
        "<setmkfluid mk='0'/><drawbox cmt='continuous owner volume'><boxfill>solid</boxfill>"
        "<point x='0' y='0' z='0'/><size x='1' y='1' z='1'/></drawbox></mainlist></commands></case>",
        encoding="utf-8",
    )
    result = loaded.xml_summary(xml, "fixture")
    assert "continu" in result["fluid_drawboxes"][0]["comment"]
    assert loaded.SCHEMA.endswith(".v2")


def test_request_has_no_native_payloads_or_launches():
    request = json.loads(REQUEST.read_text())
    assert request["deferred_input_file_count"] == 0
    assert request["vtk_read"] is False
    assert request["bi4_read"] is False
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert request["gencase_launch"] is False
    assert request["source_binding"]["physical_body_mass_kg"] == pytest.approx(128.0)


def test_manifest_preserves_six_rows_and_unknown_owner_policy():
    request = json.loads(REQUEST.read_text())
    manifest = json.loads((REQUEST.parent / "f6-fluid-owner-authority-audit-v2-manifest.json").read_text())
    assert len(manifest["rows"]) == 6
    assert manifest["read_policy"]["xml_json_only"] is True
    assert request["guard_policy"]["continuous_fluid_owner_unknown_without_source_declaration"] is True
    assert request["guard_policy"]["comments_are_not_owner_authority"] is True
    assert manifest["owner_authority_policy"]["drawbox_comments_are_not_authority"] is True
    assert manifest["owner_authority_policy"]["unlinked_contract_status"] == "UNKNOWN_NO_LINKED_CONTINUOUS_OWNER_CONTRACT"


def test_nonfinite_number_is_rejected():
    loaded = module()
    with pytest.raises(ValueError):
        loaded.num("nan", "fixture")


def test_missing_file_is_rejected(tmp_path: Path):
    loaded = module()
    with pytest.raises(ValueError, match="not a regular file"):
        loaded.require_file(tmp_path / "missing.xml", "fixture")
