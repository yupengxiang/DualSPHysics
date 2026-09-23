from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import f8_r005_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
RECEIPT = LAB / design.ROOT / "static-design-review-v1/receipt.json"


def receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_r005_static_review_is_passed_and_zero_credit() -> None:
    value = receipt()
    assert value["schema"] == design.SCHEMA
    assert value["scope_id"] == design.SCOPE
    assert value["status"] == "r005_static_design_review_passed_inputs_not_authorized"
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["static_constraint_gaps"] == []
    assert value["next_automatic_step"]["kind"] == "one-time r005 static input materialization"


def test_r004_root_causes_are_bound_to_native_evidence() -> None:
    value = receipt()
    cause = value["retained_r004_failure_evidence"]
    assert cause["status"] == "cpu_native_preflight_failed_hard_audit"
    assert cause["native_boundary_normals"] is None
    assert cause["observed_bound_vtk_points"] == 512
    assert cause["observed_bound_vtk_z_planes_m"] == [-0.0525]
    assert len(value["closed_prior_execution_scopes"]) == 4
    assert all(item["same_input_retry_forbidden"] for item in value["closed_prior_execution_scopes"])


def test_r005_definition_includes_both_walls_inside_domain_and_requests_normals() -> None:
    value = design.definition_xml(design.parameters())
    root = ET.fromstring(value)
    geometry = root.find("./casedef/geometry")
    assert geometry is not None
    definition = geometry.find("./definition")
    assert definition is not None
    point_min = float(definition.find("./pointmin").get("z"))
    point_max = float(definition.find("./pointmax").get("z"))
    assert math.isclose(point_min, -0.0525, abs_tol=1e-14)
    assert math.isclose(point_max, 0.06, abs_tol=1e-14)

    normal_list = geometry.find("./commands/list[@name='GeometryForNormals']")
    assert normal_list is not None
    assert normal_list.find("./setnormalinvert[@invert='true']") is not None
    assert normal_list.find("./shapeout[@file='hdp']") is not None
    assert normal_list.find("./setshapemode").text.strip() == "actual | bound"
    assert geometry.find("./commands/mainlist/runlist[@name='GeometryForNormals']") is not None
    wall_boxes = [normal_list.find("./drawbox"), geometry.find("./commands/mainlist/drawbox[1]")]
    assert all(box is not None and box.findtext("./boxfill") == "top|bottom" for box in wall_boxes)
    assert all(math.isclose(float(box.find("./point").get("z")), -0.0525, abs_tol=1e-14) for box in wall_boxes)
    assert all(math.isclose(float(box.find("./size").get("z")), 0.105, abs_tol=1e-14) for box in wall_boxes)

    normals = root.find("./casedef/normals[@active='true']/norgeometry")
    assert normals is not None
    assert normals.find("./geometryfile").get("file") == "[CaseName]_hdp_Actual.vtk"
    assert float(normals.find("./distanceh").get("v")) == 3.0
    assert normals.find("./svshapes").get("v") == "true"


def test_r005_keeps_registered_fluid_and_exact_control_table() -> None:
    values = design.parameters()
    root = ET.fromstring(design.definition_xml(values))
    fluid = root.find("./casedef/geometry/commands/mainlist/drawbox[2]")
    assert fluid is not None
    assert fluid.findtext("./boxfill") == "solid"
    assert math.isclose(float(fluid.find("./point").get("z")), -0.045, abs_tol=1e-14)
    assert math.isclose(float(fluid.find("./size").get("z")), 0.09, abs_tol=1e-14)
    assert 'value="F8_OPC_q0p500_r005_acceleration.csv"' in design.definition_xml(values)
    assert "acceleration/" not in design.definition_xml(values)
    assert design.acceleration_csv(values).encode("utf-8") == (LAB / design.R004_CONTROL).read_bytes()


def test_r004_binary_vtk_reader_recovers_the_single_lower_wall_plane() -> None:
    count, planes = design.vtk_z_planes(LAB / design.R004_BOUND_VTK)
    assert count == 512
    assert planes == [-0.0525]


def test_r005_review_bindings_and_nonexecution_record() -> None:
    value = receipt()
    for item in value["bindings"]:
        path = LAB / item["path"]
        assert path.is_file()
        assert design.sha256(path) == item["sha256"]
        assert path.stat().st_size == item["bytes"]
    assert value["precommitted_input_bytes"]["materialized"] is False
    assert value["precommitted_input_bytes"]["definition_sha256"] == design.sha256_bytes(
        design.definition_xml(design.parameters()).encode("utf-8")
    )
    assert value["precommitted_input_bytes"]["control_sha256"] == design.sha256_bytes(
        design.acceleration_csv(design.parameters()).encode("utf-8")
    )
    assert all(value["execution_controls"][key] is False for key in (
        "gencase_invoked", "native_decode_invoked", "solver_invoked", "gpu_started", "worker_started"
    ))
    assert value["execution_controls"]["queue_mutation"] == 0


def test_static_review_writer_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    assert design.write_review(target)["schema"] == design.SCHEMA
    with pytest.raises(FileExistsError, match="immutable F8 r005 static review"):
        design.write_review(target)
