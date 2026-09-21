import json
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
PREPARED = LAB / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_v2/prepared.json"
JOB = LAB / "campaigns/core-v1/cfd/f2-resting-fill-side-wet-full-cup-closed-catchment-mdbc-v2-final-job.json"


def _load():
    return json.loads(PREPARED.read_text())


def test_full_cup_catchment_mdbc_cpu_preflight_is_frozen():
    prepared = _load()
    config = prepared["config"]
    native = prepared["native_initial"]
    assert prepared["preflight_pass"] is True
    assert config["stage"] == "repair_canary"
    assert config["split"] == "qualification_only"
    assert config["qualification_only"] is True
    assert config["physical_geometry_changed"] is True
    assert config["mass_rescaling"] is False
    assert config["repair_candidate_id"] == "closed_external_catchment_full_cup_mdbc"
    assert native["fluid_particles"] == 54720
    assert native["expected_fluid_particles"] == 54720
    assert native["native_sampling_matches_passed_static"] is True
    assert native["normal_count"] == native["boundary_particles"]
    assert native["zero_boundary_normals"] == 0
    assert native["normal_preflight_pass"] is True
    assert prepared["mass_preflight"]["mass_gate_pass"] is True
    assert prepared["mass_preflight"]["mass_rescaling"] is False


def test_catchment_contract_keeps_real_floor_plane_and_open_top():
    config = _load()["config"]
    catchment = config["catchment"]
    spec = config["catchment_wall_spec"]
    assert catchment["mkbound"] == 3
    assert catchment["floor_material_mkbound"] == 2
    assert catchment["closed_faces"] == ["bottom", "left", "right", "front", "back"]
    assert catchment["open_faces"] == ["top"]
    assert spec["floor"]["fluid_facing_surface_z_m"] == -0.2
    assert spec["floor"]["nominal_outer_low_z_m"] == -0.2
    assert spec["floor"]["solid_slab_thickness_m"] == 0.0
    assert spec["surface_convention"] == "continuous source planes; no inward layer-center shrink"


def test_definition_contains_matching_wall_and_normal_geometry():
    prepared = _load()
    xml_path = Path(prepared["definition_audit"]["definition"])
    root = ET.parse(xml_path).getroot()
    assert root.find(".//execution/parameters/parameter[@key='Boundary']").get("value") == "2"
    normals = root.find(".//geometry/commands/list[@name='GeometryForNormals']")
    assert normals is not None
    assert len(normals.findall("setmkbound")) == 4
    assert len(normals.findall("drawbox")) == 4
    assert normals.find("shapeout").get("file") == "hdp"
    assert root.find(".//normals/norgeometry/distanceh").get("v") == "3.0"
    assert root.find(".//normals/norgeometry/svshapes").get("v") == "true"
    main = root.find(".//geometry/commands/mainlist")
    assert main.find("runlist").get("name") == "GeometryForNormals"
    wall_draws = [
        node for node in main.findall("drawbox")
        if (node.findtext("boxfill") or "").strip() == "left | right | front | back"
    ]
    assert len(wall_draws) == 1


def test_job_is_full_window_candidate_only_and_uses_f2_audit():
    job = json.loads(JOB.read_text())
    assert job["qualification_only"] is True
    assert job["split"] == "qualification_only"
    assert job["registered_window_s"] == 2.5
    assert job["maximum_extended_window_s"] == 5.0
    assert job["argv"][1].endswith("scripts/core_f2_qualification.py")
    assert job["required_outputs"] == [
        "product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"
    ]
    assert job["normal_preflight"]["required_zero_boundary_normals"] == 0
    assert job["qualification_claim"] == "none"
    assert job["physical_geometry_changed"] is True
    assert job["initial_condition_changed"] is False
    assert job["mass_rescaling"] is False
