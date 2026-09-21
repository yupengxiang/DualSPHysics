import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from scripts.core_f1 import reference_definition
from scripts.core_f1_qualification import (
    ACTUAL_DT_RATIO_MAX,
    BASE_TIME_CONTROL,
    HALF_TIME_CONTROL,
    OBSERVABLE_NAMES,
    REVISION_ID,
    aligned_difference,
    event_difference,
    formal_design,
    mdbc_repair_definition,
    manufactured_calibration,
    observer_registration,
    read_run_metrics,
)


def test_f1_manufactured_observer_calibration_passes(tmp_path):
    report = manufactured_calibration(tmp_path / "calibration.json")
    assert report["passed"] is True
    assert report["checks"]["geometry_aware_observables_present"] is True
    assert report["event_times_s"] == {
        "approach": .2, "downstream": .3, "split": .3, "rejoin": .5, "return": 1.0,
    }
    assert report["qualification_claim"].startswith("none")


def test_f1_formal_design_freezes_observer_and_actual_time_controls():
    design = formal_design()
    assert design["cell_count"] == 15
    assert design["spatial_cells"] == 13
    assert design["temporal_cells"] == 2
    assert tuple(design["observer"]["observable_names"]) == OBSERVABLE_NAMES
    assert design["observer"]["geometry"]["obstacle_source"].endswith("obstacle")
    internal = next(cell for cell in design["cells"] if cell["design_cell"] == "internal_time")
    output = next(cell for cell in design["cells"] if cell["design_cell"] == "native_output")
    assert internal["time_control"] == HALF_TIME_CONTROL
    assert output["time_control"] == BASE_TIME_CONTROL
    assert internal["cfl"] < output["cfl"]
    assert output["output_interval_s"] == pytest.approx(.004)
    assert design["preregistered_gates"]["actual_dt_ratio_max_for_internal_time"] == ACTUAL_DT_RATIO_MAX
    assert design["qualification_claim"] == "none"


def test_time_control_is_materialized_in_formal_definition(tmp_path):
    source = Path(__file__).resolve().parents[1] / "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F1_obstacle_nominal_Def.xml"
    config = next(cell for cell in formal_design()["cells"] if cell["design_cell"] == "internal_time")
    target = tmp_path / "internal_Def.xml"
    reference_definition(config, source, target)
    root = ET.parse(target).getroot()
    for key, value in HALF_TIME_CONTROL.items():
        node = root.find(f".//execution/parameters/parameter[@key='{key}']")
        assert float(node.get("value")) == pytest.approx(value)


def test_mdbc_repair_materializes_complete_boundary_recipe_without_mass_changes(tmp_path):
    source = Path(__file__).resolve().parents[1] / "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F1_obstacle_nominal_Def.xml"
    from scripts.core_f1 import f1_config

    config = f1_config(.0075, .5, stage="canary")
    target = tmp_path / "mdbc-repair_Def.xml"
    audit = mdbc_repair_definition(config, source, target)
    root = ET.parse(target).getroot()
    normal_list = root.find(".//geometry/commands/list[@name='GeometryForNormals']")
    assert normal_list is not None
    assert "top | left | right | front | back" in [
        node.findtext("boxfill") for node in normal_list.findall("drawbox")
    ]
    assert root.find(".//casedef/normals/norgeometry/svshapes[@v='true']") is not None
    pointref = root.find(".//geometry/definition/pointref")
    assert float(pointref.get("x")) == pytest.approx(.00375)
    boundary = root.find(".//geometry/commands/mainlist/drawbox[2]")
    assert boundary.find("layers").get("vdp") == "0,1,2"
    assert float(boundary.find("point").get("x")) == pytest.approx(-.00375)
    fluid = root.find(".//geometry/commands/mainlist/drawbox[1]")
    assert float(fluid.find("point").get("x")) == pytest.approx(.04125)
    assert root.find(".//execution/parameters/parameter[@key='NoPenetration']").get("value") == "1"
    assert root.find(".//execution/parameters/parameter[@key='Boundary']").get("value") == "2"
    assert audit["physical_geometry_unchanged"] is True
    assert audit["mass_rescaling"] is False


def test_f1_alignment_and_event_comparison_are_geometry_observer_specific():
    names = list(OBSERVABLE_NAMES)
    times_a = np.arange(0.0, 1.001, .02)
    times_b = np.arange(0.0, 1.001, .004)
    values_a = np.column_stack([times_a * (index + 1) for index in range(len(names))])
    values_b = np.column_stack([times_b * (index + 1) + .001 for index in range(len(names))])
    first = {"observable_names": names, "time_s": times_a.tolist(), "normalized_values": values_a.tolist()}
    second = {"observable_names": names, "time_s": times_b.tolist(), "normalized_values": values_b.tolist()}
    aligned = aligned_difference(first, second)
    assert aligned["maximum"] == pytest.approx(.001)
    assert aligned["score_frames"] == 51
    events_a = {"event_times_s": {"approach": .2, "downstream": .3, "split": .3, "rejoin": .5, "return": 1.0}}
    events_b = {"event_times_s": {"approach": .21, "downstream": .31, "split": .31, "rejoin": .51, "return": 1.01}}
    assert event_difference(events_a, events_b)["passed"] is True


def test_run_metrics_reads_actual_solver_steps_and_not_cfl(tmp_path):
    product = tmp_path / "product"
    solver = product / "solver"
    solver.mkdir(parents=True)
    (solver / "Run.csv").write_text(
        "#RunName;Steps;PhysicalTime;PartFiles\n"
        "case;220000;2.200000;551\n"
    )
    (solver / "Run.out").write_text("3 DTs adjusted to DtMin\nFinished execution (code=0)\n")
    result = read_run_metrics(product)
    assert result["available"] is True
    assert result["steps"] == 220000
    assert result["mean_solver_dt_s"] == pytest.approx(1e-5)
    assert result["part_files"] == 551
    assert result["dt_min_adjustment_warning_count"] == 1
