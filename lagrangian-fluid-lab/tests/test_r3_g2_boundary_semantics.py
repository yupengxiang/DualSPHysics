from __future__ import annotations

import json
from pathlib import Path

from scripts.r3_g2_boundary_semantics import (
    DEFAULT_MANIFEST,
    build_report,
    generated_boundary_mapping,
    parse_definition,
)


LAB = Path(__file__).resolve().parents[1]


def test_definition_parser_preserves_open_faces_and_void_context():
    obstacle = parse_definition(
        LAB / "cases" / "F1" / "F1_twin_obstacle" / "F1_twin_obstacle_Def.xml"
    )
    assert [box["mkbound"] for box in obstacle["boundary_boxes"]] == [0, 1, 2]
    assert obstacle["boundary_boxes"][0]["declared_open_faces"] == ["top"]
    assert all(box["void_context"] for box in obstacle["boundary_boxes"][1:])
    assert all("bottom" in box["declared_open_faces"] for box in obstacle["boundary_boxes"][1:])

    rotating = parse_definition(
        LAB / "campaigns" / "v0.1-candidate" / "cases" / "w06"
        / "W06_standard_slow_center_Def.xml"
    )
    assert [box["mkbound"] for box in rotating["boundary_boxes"]] == [0, 1, 2]
    assert rotating["boundary_boxes"][0]["declared_open_faces"] == ["top"]
    assert rotating["boundary_boxes"][2]["declared_faces"] == ["bottom"]
    assert not any(box["void_context"] for box in rotating["boundary_boxes"])


def test_generated_xml_keeps_fixed_and_moving_type_mapping():
    path = (
        LAB / "campaigns" / "v0.1-candidate" / "artifacts" / "w06"
        / "W06_standard_slow_center" / "generated" / "W06_standard_slow_center.xml"
    )
    mapping = generated_boundary_mapping(path)
    assert mapping[0]["vtk_mk"] == 17
    assert mapping[0]["vtk_type"] == 1
    assert mapping[0]["particle_role"] == "moving"
    assert mapping[1]["vtk_mk"] == 18
    assert mapping[1]["vtk_type"] == 0
    assert mapping[2]["vtk_mk"] == 19
    assert mapping[2]["vtk_type"] == 0


def test_selected_sidecars_pass_structural_semantics_and_expose_implicit_caps(tmp_path):
    report = build_report(DEFAULT_MANIFEST, tmp_path / "semantics.json")
    assert report["case_count"] == 12
    assert report["summary"] == {
        "structural_semantics_pass_count": 12,
        "wall_visibility_semantics_pass_count": 9,
        "implicit_closure_case_count": 3,
        "moving_case_count": 5,
    }
    cases = {case["case_id"]: case for case in report["cases"]}
    assert all(case["structural_semantics_pass"] for case in cases.values())
    assert all(case["sidecar"]["frame0_matches_vtk_local_geometry"] for case in cases.values())
    assert all(case["checks"]["sidecar_labels_match_vtk"] for case in cases.values())
    assert cases["W06_standard_slow_center"]["sidecar"]["moving_triangle_count"] == 28
    assert cases["W06_standard_slow_center"]["sidecar"]["static_triangle_count"] == 40
    assert {
        (item["mkbound"], item["face"])
        for case_id in ("F1_center_obstacle", "F1_twin_obstacle", "F3_baffled_slosh")
        for item in cases[case_id]["implicit_closures_requiring_policy"]
    } == {(1, "bottom"), (2, "bottom")}
    assert cases["F3_baffled_slosh"]["implicit_closures_requiring_policy"] == [
        {
            "mkbound": 1,
            "face": "bottom",
            "role": "baffle",
            "coverage_ratio": 1.0,
        }
    ]
    assert cases["F3_baffled_slosh"]["wall_visibility_semantics_pass"] is False
