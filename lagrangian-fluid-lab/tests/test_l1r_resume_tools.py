from __future__ import annotations

from scripts import l1r_q1_official as q1
from scripts import l1r_q2_mdbc_bridge as q2


def test_q1_inventory_points_to_original_same_version_assets():
    inventory = q1.inventory_payload()
    assert inventory["version_info"]["exists"]
    assert inventory["execution_policy"]["source_modified"] is False
    assert set(inventory["cases"]) == {
        "official_dambreak3d_mdbc",
        "official_stillwedge_lr_mdbc",
        "official_stillwedge_hr_mdbc",
    }
    dam = inventory["cases"]["official_dambreak3d_mdbc"]["source_xml_summary"]
    assert dam["execution_parameters"]["Boundary"] == "2"
    assert dam["mainlist"]["layer_values"][:4] == ["0,1,2"] * 4
    assert dam["normal_geometry_files"] == ["[CaseName]_hdp_Actual.vtk"]


def test_q1_gencase_parser_reconciles_official_particle_and_normal_counts():
    text = (
        "Total particles: 1,015,809 (bound=363597 (fx=363597 mv=0 ft=0) fluid=652212)\n"
        "Non-zero particle normals: 363,597/363,597\n"
        "Final zero normals: 0/363,597 (0.0%)\n"
    )
    assert q1._parse_gencase_counts(text) == {
        "total_particles": 1015809,
        "bound_particles": 363597,
        "fluid_particles": 652212,
        "nonzero_normals": 363597,
        "normal_evaluation_particles": 363597,
        "final_zero_normals": 0,
        "normal_particles_total": 363597,
    }


def test_q2_record_declares_complete_official_recipe_without_release_authority():
    record = q2.build_record()
    assert record["phase"] == "Q2_official_recipe_bridge"
    assert record["time_max_s"] == 0.6
    assert record["mdbc_recipe"] == {
        "reference": "vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml",
        "normal_source_layers_vdp": "-0.5",
        "boundary_layers_vdp": "0,1,2",
        "normal_distance_h": 2.0,
        "svshapes": True,
        "boundary": 2,
        "slip_mode": 1,
        "no_penetration": 0,
    }
    assert record["development_authorized"] is False
    assert record["formal_release"] is False
