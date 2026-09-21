from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import f2_static_full_cup_boundary_repair_h2_definition_v1 as writer


def test_authorization_is_exact_one_canary_and_bottom_clearance_is_reviewed():
    authorization = writer.verify_authorization()
    review = authorization["root_review"]
    assert review["decision"]["scope"] == "exactly one q=0.0, dp=0.010 H2 canary; no matrix expansion"
    assert review["decision"]["fresh_definition_write_allowed"] is True
    assert review["decision"]["solver_allowed"] is False
    assert review["decision"]["gpu_allowed"] is False
    assert review["decision"]["queue_mutation_allowed"] == 0
    assert review["decision"]["ledger_mutation_allowed"] == 0
    assert review["decision"]["registry_mutation_allowed"] == 0
    assert writer.FLUID_LOW[2] == pytest.approx(writer.CUP_LOW[2] + writer.CLEARANCE_M)
    assert writer.FLUID_FIRST_CENTER[2] == pytest.approx(writer.FLUID_LOW[2] + writer.DP_M / 2.0)


def test_writer_materializes_fresh_boundary2_inputs_and_compact_receipt(tmp_path: Path):
    output = tmp_path / "input"
    receipt = writer.write_inputs(output)
    definition_path = output / writer.DEFINITION_NAME
    motion_path = output / writer.MOTION_NAME
    receipt_path = output / writer.RECEIPT_NAME
    assert definition_path.is_file() and motion_path.is_file() and receipt_path.is_file()
    assert receipt["case_id"] == writer.CASE_ID
    assert receipt["revision_id"] == writer.REVISION_ID
    assert receipt["continuous_fluid"]["clearance_m"] == pytest.approx(0.039)
    assert receipt["continuous_fluid"]["low_m"] == pytest.approx([0.039, -0.111, 0.689])
    assert receipt["sampling"]["first_center_m"] == pytest.approx([0.044, -0.106, 0.694])
    assert receipt["sampling"]["draw_size_m"] == pytest.approx([0.34, 0.21, 0.29])
    assert receipt["sampling"]["counts"] == [35, 22, 30]
    assert receipt["sampling"]["particle_count"] == 23100
    assert abs(receipt["sampling"]["mass_error_relative"]) <= 0.03
    assert receipt["boundary"] == {
        "Boundary": 2,
        "explicit_normals": True,
        "geometry_normals_distanceh": 3.0,
        "solver_mdbc_noslip_argument": "-mdbc_noslip:1",
    }

    root = ET.parse(definition_path).getroot()
    params = {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}
    assert params["Boundary"] == "2"
    assert root.find("./casedef/normals[@active='true']/norgeometry/distanceh").get("v") == "3.0"
    source = root.find("./casedef/geometry/commands/mainlist/drawbox[last()]")
    assert [float(source.find("point").get(axis)) for axis in "xyz"] == pytest.approx([0.044, -0.106, 0.694])
    assert [float(source.find("size").get(axis)) for axis in "xyz"] == pytest.approx([0.34, 0.21, 0.29])
    assert root.find("./casedef/motion/objreal/mvrotfile/file").get("name") == writer.MOTION_NAME
    assert writer.verify_receipt(receipt_path)["ok"] is True

    stored = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert stored["authorization"]["gencase_invoked"] is False
    assert stored["authorization"]["native_decode_invoked"] is False
    assert stored["authorization"]["solver_invoked"] is False
    assert stored["authorization"]["gpu_started"] is False
    assert stored["authorization"]["qualification_credit"] == 0


def test_writer_is_deterministic_and_rejects_source_definition_identity(tmp_path: Path):
    output = tmp_path / "input"
    first = writer.write_inputs(output)
    definition_bytes = (output / writer.DEFINITION_NAME).read_bytes()
    motion_bytes = (output / writer.MOTION_NAME).read_bytes()
    receipt_bytes = (output / writer.RECEIPT_NAME).read_bytes()
    second = writer.write_inputs(output)
    assert second["definition"]["sha256"] == first["definition"]["sha256"]
    assert second["motion"]["sha256"] == first["motion"]["sha256"]
    assert (output / writer.DEFINITION_NAME).read_bytes() == definition_bytes
    assert (output / writer.MOTION_NAME).read_bytes() == motion_bytes
    assert (output / writer.RECEIPT_NAME).read_bytes() == receipt_bytes
    assert first["fresh_identity"]["old_definition_reused"] is False
    assert first["fresh_identity"]["old_trajectory_reused"] is False
    assert first["source_template_sha256"] != first["definition"]["sha256"]
