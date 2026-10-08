from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_fluid_owner_authority_audit_v3.py"
REQUEST_DIR = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f6-fluid-owner-authority-audit-v3-root-forward-103-001"
)
REQUEST = REQUEST_DIR / "f6-fluid-owner-authority-audit-v3-request.json"
MANIFEST = REQUEST_DIR / "f6-fluid-owner-authority-audit-v3-manifest.json"


def module():
    spec = importlib.util.spec_from_file_location(
        "f6_fluid_owner_authority_audit_v3", SCRIPT
    )
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_real_six_source_defs_use_source_only_projection():
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ds02.stage2.f6.fluid-owner-authority-audit.manifest.v3"
    assert len(manifest["rows"]) == 6
    for row in manifest["rows"]:
        source = Path(row["source_definition"]["path"])
        projected = loaded.source_xml_projection(
            source, f"{row['sentinel_id']}/{row['grid_id']} source Def"
        )
        assert projected["source_particles_present"] is False
        assert projected["source_massfluid_present"] is False
        assert projected["particle_summary"] is None
        assert projected["body_mass_kg"] == pytest.approx(128.0)
        assert projected["fluid_drawboxes"]


def test_real_six_generated_xmls_supply_particle_summary():
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for row in manifest["rows"]:
        generated = Path(row["generated_xml"]["path"])
        summary = loaded.xml_summary(
            generated, f"{row['sentinel_id']}/{row['grid_id']} generated"
        )
        assert summary["counts"]["fluid"] > 0
        assert summary["massfluid_kg"] > 0
        assert summary["fluid_sample_mass_kg"] > 0


def test_actual_source_and_generated_contracts_audit_without_native_payloads(tmp_path: Path):
    loaded = module()
    report = loaded.audit(MANIFEST, tmp_path / "f6-fluid-owner-authority-audit-v3.json")
    assert report["schema"].endswith(".v3")
    assert report["status"] == "COMPLETED_F6_FLUID_OWNER_AUTHORITY_XML_SOURCE_PROJECTION_AUDIT"
    assert len(report["rows"]) == 6
    assert all(
        row["source_projection"]["source_particles_present"] is False
        for row in report["rows"]
    )
    assert all(row["generated_particle_summary"]["counts"]["fluid"] > 0 for row in report["rows"])
    assert report["scope"]["source_def_projection_only"] is True
    assert report["scope"]["vtk_opened"] is False
    assert report["scope"]["bi4_opened"] is False
    assert report["scope"]["hdf5_opened"] is False
    assert report["scientific_status"] == {
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "physical_fate": "UNKNOWN",
        "dynamics": "UNKNOWN",
    }


def test_request_binds_v3_source_projection_and_forbids_native_payloads():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["case_id"] == "STAGE2_F6_FLUID_OWNER_AUTHORITY_AUDIT_V3"
    assert request["request_schema"].endswith(".v3-request.v1")
    assert request["command"][1].endswith("ds_data02_stage2_f6_fluid_owner_authority_audit_v3.py")
    assert request["command"][3] == str(MANIFEST.resolve())
    assert request["deferred_input_file_count"] == 0
    assert request["vtk_read"] is False
    assert request["bi4_read"] is False
    assert request["hdf5_read"] is False
    assert request["solver_launch"] is False
    assert request["gencase_launch"] is False
    assert request["guard_policy"]["source_def_no_generated_particle_sections"] is True
    assert request["source_binding"]["source_projection_policy"]["generated_xml_requires_particle_and_massfluid_summary"] is True
    assert all(not path.lower().endswith((".h5", ".hdf5", ".bi4", ".vtk")) for path in request["input_files"])


def test_v3_schema_does_not_reuse_v2():
    loaded = module()
    assert loaded.SCHEMA == "ds02.stage2.f6.fluid-owner-authority-audit.v3"


def test_nonfinite_number_is_rejected():
    loaded = module()
    with pytest.raises(ValueError):
        loaded.num("nan", "fixture")
