from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import f8_r008_definition_control_pack_v1 as pack
from scripts import f8_r008_definition_geometry_audit_v1 as audit
from scripts import f8_t1_scope_design_v1 as scope


def _case(case_id: str = "space-q0p5-dp0p0075") -> dict:
    return next(row for row in scope.qualification_matrix() if row["case_id"] == case_id)


def _definition(case: dict | None = None) -> bytes:
    row = _case() if case is None else case
    name = f"F8_OPC_{row['case_id']}_acceleration.csv"
    return pack.render_definition(row, name)


def _mutate(payload: bytes, path: str, attr: str, value: str) -> bytes:
    root = ET.fromstring(payload)
    node = root.find(path)
    assert node is not None
    node.set(attr, value)
    return ET.tostring(root, encoding="utf-8")


def test_audits_all_47_frozen_definitions_and_keeps_runtime_normals_unverified() -> None:
    receipt = audit.audit_frozen_geometry_pack()
    assert receipt["status"] == "static_frozen_definition_geometry_passed_runtime_geometry_unverified"
    assert receipt["definition_count"] == 47
    assert {item["case_id"] for item in receipt["case_summaries"]} == {
        row["case_id"] for row in scope.qualification_matrix() + scope.production_manifest()
    }
    assert all(item["outer_domain_clearance_dp"] == 2.0 for item in receipt["case_summaries"])
    assert all(item["four_layer_support_rule_passes"] for item in receipt["case_summaries"])
    assert all(item["native_normal_vectors_verified"] is False for item in receipt["case_summaries"])
    assert receipt["native_geometry_generated"] is False
    assert receipt["gencase_invoked"] is False
    assert receipt["qualification_credit"] == 0
    assert receipt["frozen_scope_boundary_contract"] == audit.EXPECTED_BOUNDARY_CONTRACT
    assert receipt["boundary_semantics_source"]["Boundary_2_means_mDBC"] is True
    assert receipt["boundary_semantics_source"]["XYPeriodic_zero_value_uses_presence_semantics"] is True
    assert "not interpreted as absence" in receipt["boundary_semantics_note"]


def test_static_geometry_recomputes_domain_walls_and_fluid_box() -> None:
    case = _case()
    result = audit.audit_definition_geometry(_definition(case), case)
    assert result["domain_z_bounds_m"] == pytest.approx([-0.09, 0.09])
    assert result["wall_box_reference_z_bounds_m"] == pytest.approx([-0.0525, 0.0525])
    assert result["fluid_z_bounds_m"] == pytest.approx([-0.045, 0.045])
    assert result["requested_wall_plane_offsets_dp"] == [1.0, 2.0, 3.0, 4.0]
    assert result["normal_shape_inversion_declared"] is True
    assert result["native_normal_vectors_verified"] is False


@pytest.mark.parametrize(
    ("path", "attr", "value", "message"),
    [
        ("./casedef/geometry/definition/pointmax", "z", "0.1", "pointmax"),
        ("./casedef/geometry/commands/list[@name='GeometryForNormals']/setnormalinvert", "invert", "false", "setnormalinvert"),
        ("./casedef/geometry/commands/mainlist/drawbox[1]/layers", "vdp", "0,1,2", "layers"),
        ("./casedef/geometry/commands/mainlist/drawbox[2]/size", "z", "0.08", "size"),
        ("./casedef/normals", "active", "false", "attributes differ"),
        ("./execution/parameters/parameter[@key='XYPeriodic']", "value", "1", "periodicity"),
        ("./execution/parameters/parameter[@key='Boundary']", "value", "1", "boundary"),
    ],
)
def test_static_geometry_mutations_fail_closed(path: str, attr: str, value: str, message: str) -> None:
    case = _case()
    mutated = _mutate(_definition(case), path, attr, value)
    with pytest.raises(audit.DefinitionGeometryAuditError, match=message):
        audit.audit_definition_geometry(mutated, case)


def test_materialized_file_hash_must_match_the_frozen_pack() -> None:
    receipt = audit.audit_frozen_geometry_pack()
    binding = next(
        item["definition"]
        for item in pack.build_pack()["cases"]
        if item["case_id"] == receipt["case_summaries"][0]["case_id"]
    )
    payload = (pack.LAB / Path(binding["path"])).read_bytes()
    assert audit.audit_definition_geometry(payload, _case(receipt["case_summaries"][0]["case_id"]))["case_id"] == binding["path"].split("/")[-2]


def test_frozen_definition_hash_and_relative_path_drift_fail_closed() -> None:
    case = next(item for item in pack.build_pack()["cases"] if item["case_id"] == _case()["case_id"])
    binding = dict(case["definition"])
    binding["sha256"] = "0" * 64
    with pytest.raises(audit.DefinitionGeometryAuditError, match="bytes differ from hash-closed pack"):
        audit._read_frozen_definition(binding)
    binding["path"] = "../outside.xml"
    with pytest.raises(audit.DefinitionGeometryAuditError, match="safe relative path"):
        audit._read_frozen_definition(binding)
