from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import f8_r006_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
RECEIPT = LAB / design.ROOT / "static-design-review-v1/receipt.json"


def receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_r006_static_review_passes_with_zero_qualification_credit() -> None:
    value = receipt()
    assert value["schema"] == design.SCHEMA
    assert value["scope_id"] == design.SCOPE
    assert value["status"] == "r006_static_design_review_passed_inputs_not_authorized"
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["static_constraint_gaps"] == []
    assert value["next_automatic_step"]["kind"] == "one-time r006 static input materialization"


def test_r005_failed_output_and_hdp_surface_evidence_are_both_bound() -> None:
    value = receipt()
    failed = value["retained_r005_failure_evidence"]
    assert failed["status"] == "generated_geometry_failed_hard_audit"
    assert failed["generated_fixed_boundary_particles"] == 512
    assert failed["observed_bound_vtk_points_and_planes"] == {
        "points": 512,
        "z_planes_m": [-0.0525],
    }
    assert failed["hdp_geometry_points_and_planes"] == {
        "points": 8,
        "z_planes_m": [-0.0525, 0.0525],
    }
    assert failed["observed_maximum_normal_m"] == pytest.approx(1.63913e-9)
    assert value["closed_prior_execution_scopes"][-1]["scope_id"].endswith("R005")
    assert all(item["same_input_retry_forbidden"] for item in value["closed_prior_execution_scopes"])


def test_r006_domain_contains_four_wall_layers_and_one_dp_margin() -> None:
    root = ET.fromstring(design.definition_xml(design.parameters()))
    definition = root.find("./casedef/geometry/definition")
    assert definition is not None
    assert math.isclose(float(definition.find("./pointmin").get("z")), -0.0825, abs_tol=1e-14)
    point_max = float(definition.find("./pointmax").get("z"))
    assert math.isclose(point_max, 0.0825, abs_tol=1e-14)
    assert math.isclose((point_max - 0.075) / 0.0075, 1.0, abs_tol=1e-14)


def test_half_dp_layer_is_only_applied_to_normal_geometry() -> None:
    root = ET.fromstring(design.definition_xml(design.parameters()))
    geometry = root.find("./casedef/geometry")
    assert geometry is not None
    normal_wall = geometry.find("./commands/list[@name='GeometryForNormals']/drawbox")
    particle_wall = geometry.find("./commands/mainlist/drawbox[1]")
    assert normal_wall is not None and particle_wall is not None
    assert normal_wall.findtext("./boxfill") == "top | bottom"
    assert particle_wall.findtext("./boxfill") == "top | bottom"
    assert normal_wall.find("./layers[@vdp='-0.5']") is not None
    assert particle_wall.find("./layers[@vdp='0,1,2,3']") is not None
    for wall in (normal_wall, particle_wall):
        assert math.isclose(float(wall.find("./point").get("z")), -0.0525, abs_tol=1e-14)
        assert math.isclose(float(wall.find("./size").get("z")), 0.105, abs_tol=1e-14)


def test_physics_fluid_and_control_table_are_preserved() -> None:
    values = design.parameters()
    rendered = design.definition_xml(values)
    root = ET.fromstring(rendered)
    fluid = root.find("./casedef/geometry/commands/mainlist/drawbox[2]")
    assert fluid is not None
    assert fluid.findtext("./boxfill") == "solid"
    assert math.isclose(float(fluid.find("./point").get("z")), -0.045, abs_tol=1e-14)
    assert math.isclose(float(fluid.find("./size").get("z")), 0.09, abs_tol=1e-14)
    assert 'value="F8_OPC_q0p500_r006_acceleration.csv"' in rendered
    assert "acceleration/" not in rendered
    assert design.acceleration_csv(values).encode("utf-8") == (LAB / design.R005_CONTROL).read_bytes()
    assert root.find("./casedef/normals[@active='true']/norgeometry") is not None


def test_normal_threshold_rejects_r005_roundoff_and_is_bound_to_design() -> None:
    value = receipt()
    threshold = value["r006_mechanism_repair"]["native_normal_minimum_magnitude"]
    assert threshold == pytest.approx(0.001875)
    assert threshold > value["retained_r005_failure_evidence"]["observed_maximum_normal_m"]
    assert any("every norm is at least 0.25 dp" in gate for gate in value["future_cpu_native_preflight_hard_gates"])
    repair = value["r006_mechanism_repair"]
    assert repair["expected_boundary_z_planes_m"] == [-0.075, -0.0675, -0.06, -0.0525, 0.0525, 0.06, 0.0675, 0.075]
    assert repair["expected_fixed_boundary_particles"] == 4096
    assert repair["expected_total_particles"] == 10752
    assert repair["expected_normal_geometry_z_planes_m"] == [-0.04875, 0.04875]
    assert repair["expected_inward_normal_z_component_m"] == {
        "lower_wall_min": pytest.approx(0.001875),
        "upper_wall_max": pytest.approx(-0.001875),
    }


def test_four_boundary_layers_cover_the_registered_mdbc_support_requirement() -> None:
    rationale = receipt()["mdbc_support_rationale"]
    assert rationale["required_support_thickness_in_dp"] == pytest.approx(2 * math.sqrt(3))
    assert rationale["boundary_layers_selected"] == 4
    assert rationale["support_thickness_selected_in_dp"] >= rationale["required_support_thickness_in_dp"]
    assert len(rationale["references"]) == 2


def test_all_review_bindings_are_hash_closed() -> None:
    value = receipt()
    for item in value["bindings"]:
        path = LAB / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert design.sha256(path) == item["sha256"]
    assert value["precommitted_input_bytes"]["materialized"] is False
    assert all(value["execution_controls"][key] is False for key in (
        "definition_written", "control_written", "gencase_invoked", "native_decode_invoked",
        "solver_invoked", "gpu_started", "worker_started", "training_started",
    ))
    assert value["execution_controls"]["queue_mutation"] == 0


def test_static_review_writer_refuses_to_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    assert design.write_review(target)["schema"] == design.SCHEMA
    with pytest.raises(FileExistsError, match="immutable F8 r006 static review"):
        design.write_review(target)
