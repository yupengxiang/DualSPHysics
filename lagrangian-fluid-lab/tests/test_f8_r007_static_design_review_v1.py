from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import f8_r006_static_design_review_v1 as r006
from scripts import f8_r007_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
RECEIPT = LAB / design.ROOT / "static-design-review-v1/receipt.json"


def receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_r007_static_review_passes_with_zero_credit_and_fresh_scope() -> None:
    value = receipt()
    assert value["schema"] == design.SCHEMA
    assert value["scope_id"] == design.SCOPE
    assert value["status"] == "r007_static_design_review_passed_inputs_not_authorized"
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["static_constraint_gaps"] == []
    assert value["next_automatic_step"]["kind"] == "one-time r007 static input materialization"
    assert len(value["closed_prior_execution_scopes"]) == 6
    assert all(item["same_input_retry_forbidden"] for item in value["closed_prior_execution_scopes"])


def test_r006_failure_evidence_is_asymmetric_and_binds_the_missing_plane() -> None:
    failure = receipt()["retained_r006_failure_evidence"]
    assert failure["status"] == "generated_geometry_failed_hard_audit"
    assert failure["generated_fixed_boundary_particles"] == 3584
    assert failure["generated_boundary_plane_particle_counts"] == {
        "-0.0750": 512, "-0.0675": 512, "-0.0600": 512, "-0.0525": 512,
        "0.0525": 512, "0.0600": 512, "0.0675": 512,
    }
    assert failure["missing_upper_outer_plane_m"] == 0.075
    assert failure["generated_fluid_particles"] == 6656
    assert failure["generated_fluid_z_bounds_m"] == [-0.045, 0.045]
    assert failure["generated_hdp_surface_z_planes_m"] == [-0.04875, 0.04875]
    assert failure["native_decode_invoked"] is False


def test_r007_changes_only_domain_bounds_and_preserves_four_layer_geometry() -> None:
    values = design.parameters()
    old_root = ET.fromstring(r006.definition_xml(values))
    new_root = ET.fromstring(design.definition_xml(values))
    old_definition = old_root.find("./casedef/geometry/definition")
    new_definition = new_root.find("./casedef/geometry/definition")
    assert old_definition is not None and new_definition is not None
    assert math.isclose(float(old_definition.find("./pointmin").get("z")), -0.0825, abs_tol=1e-14)
    assert math.isclose(float(old_definition.find("./pointmax").get("z")), 0.0825, abs_tol=1e-14)
    assert math.isclose(float(new_definition.find("./pointmin").get("z")), -0.09, abs_tol=1e-14)
    assert math.isclose(float(new_definition.find("./pointmax").get("z")), 0.09, abs_tol=1e-14)

    old_geometry = old_root.find("./casedef/geometry")
    new_geometry = new_root.find("./casedef/geometry")
    assert old_geometry is not None and new_geometry is not None
    assert ET.tostring(old_geometry.find("./commands")) == ET.tostring(new_geometry.find("./commands"))
    assert old_root.find("./casedef/constantsdef") is not None
    assert ET.tostring(old_root.find("./casedef/constantsdef")) == ET.tostring(new_root.find("./casedef/constantsdef"))
    normal_wall = new_geometry.find("./commands/list[@name='GeometryForNormals']/drawbox")
    particle_wall = new_geometry.find("./commands/mainlist/drawbox[1]")
    assert normal_wall.find("./layers[@vdp='-0.5']") is not None
    assert particle_wall.find("./layers[@vdp='0,1,2,3']") is not None


def test_r007_hard_gates_keep_the_eight_plane_four_layer_target() -> None:
    repair = receipt()["r007_mechanism_repair"]
    assert repair["new_domain_z_m"] == [-0.09, 0.09]
    assert repair["domain_clearance_beyond_outermost_layers_dp"] == {"lower": 2.0, "upper": 2.0}
    assert repair["expected_boundary_z_planes_m"] == [-0.075, -0.0675, -0.06, -0.0525, 0.0525, 0.06, 0.0675, 0.075]
    assert repair["expected_fixed_boundary_particles"] == 4096
    assert repair["expected_fluid_particles"] == 6656
    assert repair["expected_total_particles"] == 10752
    gates = " ".join(receipt()["future_cpu_native_preflight_hard_gates"])
    assert "+0.075 m" in gates
    assert "lower normals +z and upper normals -z" in gates


def test_r007_control_table_is_byte_identical_to_r006_positive_control() -> None:
    assert design.acceleration_csv(design.parameters()).encode("utf-8") == (LAB / design.R006_CONTROL).read_bytes()
    assert design.sha256_bytes(design.acceleration_csv(design.parameters()).encode("utf-8")) == (
        "bd623b5681f449804a3a2bdf61cded339e180065cf37e2d5d8b6ac92f9e3cfc1"
    )
    assert 'value="F8_OPC_q0p500_r007_acceleration.csv"' in design.definition_xml(design.parameters())


def test_review_bindings_are_hash_closed_and_no_execution_was_performed() -> None:
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
    with pytest.raises(FileExistsError, match="immutable F8 r007 static review"):
        design.write_review(target)
