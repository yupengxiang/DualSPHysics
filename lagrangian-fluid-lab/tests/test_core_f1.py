from pathlib import Path
import xml.etree.ElementTree as ET

from scripts.l2_f1r_audit import apply_runtime_domain_repair, F1_WALL_SPEC
from scripts.l2_f1r_h1_canary import _canonical_without_runtime_domain
from scripts.finite_wall_audit import wall_penetration, segment_crossing_events
from scripts.core_f1 import (
    F1_EVENT_WINDOW_S,
    F1_MAX_EVENT_WINDOW_S,
    F1_NATIVE_OUTPUT_INTERVAL_S,
    F1_OUTPUT_INTERVAL_S,
    F1_RESOLUTIONS,
    _f1_native_box,
    f1_config,
    f1_water_height,
    qualification_design,
    reference_definition,
)
import numpy as np


def test_domain_repair_preserves_every_non_domain_input(tmp_path):
    source = Path(__file__).resolve().parents[1] / "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F1_obstacle_nominal_Def.xml"
    target = tmp_path / "case.xml"
    apply_runtime_domain_repair(source, target, zmax=1.8)
    assert _canonical_without_runtime_domain(source) == _canonical_without_runtime_domain(target)
    assert ET.parse(target).find(".//simulationdomain/posmax").attrib["z"] == "1.8"


def test_f1_audit_distinguishes_obstacle_and_open_tank_top():
    positions = np.array([[.74,.2,.1],[.2,.2,1.5]])
    report = wall_penetration(positions, np.ones(2), F1_WALL_SPEC, 1e-8)
    assert report["obstacle_penetration_count"] == 1
    events = segment_crossing_events(np.array([[.65,.2,.2]]), np.array([[.85,.2,.2]]), F1_WALL_SPEC, 1e-8)
    assert any(event["kind"] == "obstacle" for event in events)


def test_f1_reference_card_has_frozen_13_plus_2_mass_passing_cells():
    design = qualification_design()
    assert design["cell_count"] == 15
    assert design["static_mass_check"]["pass"] is True
    assert all(row["mass_gate_pass"] for row in design["static_mass_check"]["rows"])
    assert max(abs(row["source_mass_relative_error"])
               for row in design["static_mass_check"]["rows"]) < .025
    assert design["registered_window"]["initial_time_max_s"] == F1_EVENT_WINDOW_S
    assert design["registered_window"]["maximum_extended_time_max_s"] == F1_MAX_EVENT_WINDOW_S
    assert design["mass_policy"].find("no mass rescaling") >= 0


def test_f1_height_coordinate_and_temporal_cells_are_explicit():
    assert f1_water_height(0.0) == .40
    assert f1_water_height(.5) == .46
    assert f1_water_height(1.0) == .52
    internal = f1_config(.0075, .5, stage="qualification",
                         design_cell="internal_time", temporal_variant="internal_time")
    output = f1_config(.0075, .5, stage="qualification",
                       design_cell="native_output", temporal_variant="native_output")
    assert internal["cfl"] == .1
    assert internal["output_interval_s"] == F1_OUTPUT_INTERVAL_S
    assert output["cfl"] == .2
    assert output["output_interval_s"] == F1_NATIVE_OUTPUT_INTERVAL_S
    assert internal["continuum_geometry"]["unchanged"] is True
    assert "native DBC" in internal["boundary_semantics"]


def test_f1_cell_centre_initialization_is_recorded_and_mass_is_native(tmp_path):
    source = Path(__file__).resolve().parents[1] / "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F1_obstacle_nominal_Def.xml"
    target = tmp_path / "reference_Def.xml"
    config = f1_config(.0075, .5, stage="canary")
    audit = reference_definition(config, source, target)
    assert audit["physical_geometry_unchanged"] is True
    assert audit["mass_rescaling"] is False
    root = ET.parse(target).getroot()
    fluid = root.find(".//casedef/geometry/commands/mainlist/drawbox")
    # The first drawbox is the registered cell-centre fluid representation.
    assert np.allclose([float(fluid.find("point").get(axis)) for axis in "xyz"], [.045, .045, .045])
    assert np.allclose([float(fluid.find("size").get(axis)) for axis in "xyz"], [.3375, .315, .45])
    native = _f1_native_box([.04, .04, .04], [.34, .32, .46], .0075)
    assert native["particle_count"] == 46 * 43 * 61
    assert native["discrete_mass_kg"] == native["particle_count"] * .0075**3 * 1000
