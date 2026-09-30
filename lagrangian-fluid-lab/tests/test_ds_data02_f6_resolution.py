from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f6_resolution.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f6_resolution", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
F6R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F6R)


def test_resolution_plan_freezes_repaired_continuous_geometry(tmp_path: Path) -> None:
    output = tmp_path / "resolution"
    plan = F6R.prepare_resolution_study(output)
    assert plan["resolution_ids"] == ["coarse", "medium", "fine"]
    assert plan["dp_m"] == {"coarse": 0.06, "medium": 0.03, "fine": 0.02}
    assert plan["same_continuous_geometry"] is True
    assert plan["actual_final_dimensions"] == {
        "simple_free_response": [5.46, 1.56, 1.26],
        "wave_no_contact": [6.0, 1.56, 1.26],
    }
    assert ".12" not in json.dumps(plan["dp_m"])
    rows = plan["matrix"]
    assert len(rows) == 6
    for mechanism in F6R.MECHANISMS:
        mechanism_rows = [row for row in rows if row["mechanism_id"] == mechanism]
        assert len({row["physical_geometry_hash"] for row in mechanism_rows}) == 1
        assert len({tuple(row["physical_wall_size_m"]) for row in mechanism_rows}) == 1
        assert len({tuple(row["body"]["size_m"]) for row in mechanism_rows}) == 1
        assert len({row["body"]["mass_kg"] for row in mechanism_rows}) == 1
        assert all(row["request"]["attempt_id"].endswith("_GENCASE_01") for row in mechanism_rows)


def test_definitions_change_only_dp_and_pointmax_margin(tmp_path: Path) -> None:
    output = tmp_path / "resolution"
    plan = F6R.prepare_resolution_study(output)
    for mechanism in F6R.MECHANISMS:
        walls = []
        bodies = []
        fills = []
        dps = []
        for row in plan["matrix"]:
            if row["mechanism_id"] != mechanism:
                continue
            root = ET.parse(Path(row["paths"]["definition"]["path"])).getroot()
            definition = root.find("./casedef/geometry/definition")
            wall = root.find(".//drawbox[@cmt='Finite tank walls']/size")
            body = root.find(".//drawbox[@cmt='Free rigid body']/size")
            fill = root.find(".//fillbox/size")
            assert definition is not None and wall is not None and body is not None and fill is not None
            dps.append(float(definition.get("dp")))
            walls.append(tuple(float(wall.get(axis)) for axis in "xyz"))
            bodies.append(tuple(float(body.get(axis)) for axis in "xyz"))
            fills.append(tuple(float(fill.get(axis)) for axis in "xyz"))
            pointmax = definition.find("pointmax")
            assert pointmax is not None
            assert all(abs(float(pointmax.get(axis)) - float(wall.get(axis)) - float(definition.get("dp"))) < 1e-9 for axis in "xyz")
        assert dps == [0.06, 0.03, 0.02]
        assert len(set(walls)) == len(set(bodies)) == len(set(fills)) == 1


def test_request_provenance_and_partvtk_preamble_parser(tmp_path: Path) -> None:
    output = tmp_path / "resolution"
    plan = F6R.prepare_resolution_study(output)
    for row in plan["matrix"]:
        request = F6R.read_json(Path(row["request"]["path"]))
        assert request["kind"] == "cpu"
        assert request["cpu_task_kind"] == "gencase"
        assert request["cpu_threads"] == 4
        assert request["max_wall_seconds"] == 300
        assert request["estimated_storage_bytes"] == 268435456
        assert request["solver_dimension_required"] == 3
        assert all(Path(path).is_file() for path in request["input_files"])
        assert not any("RES_.12" in path for path in request["input_files"])
    sample = tmp_path / "PartVTK.csv"
    sample.write_text(
        "TimeStep [s];Np;Nbound;Nfixed;Nmoving;Nfloat;Nfluid\n"
        "0;2;1;1;0;1;1\n\n"
        "Pos.x [m];Idp;Mass [kg];Type;Mk;\n"
        "0;0;0.2;0;30;\n"
        "1;1;0.2;2;60;\n",
        encoding="utf-8",
    )
    headers, rows = F6R._parse_partvtk_csv(sample)
    assert "Type" in headers and "Mass [kg]" in headers
    assert len(rows) == 2


def test_postprocess_plan_declares_native_type_mass_and_orientation_limit(tmp_path: Path) -> None:
    # This test inspects the registered contract only.  Actual native outputs
    # are immutable external receipts and are audited by refresh-evidence.
    output = tmp_path / "resolution"
    output.mkdir()
    plan = {
        "schema": F6R.POSTPROCESS_SCHEMA,
        "unsupported": ["orientation_quaternion: FloatingInfo v5.4 native output provides roll/pitch/yaw; no quaternion field was claimed"],
    }
    F6R.write_json(output / "native_audit_plan.json", plan)
    observed = F6R.read_json(output / "native_audit_plan.json")
    assert any("quaternion" in item for item in observed["unsupported"])


def test_initial_mass_budget_separates_lattice_support_and_body_occupancy() -> None:
    case = {
        "fluid_fill": {"point_m": [0.0, 0.0, 0.0], "size_m": [0.5, 0.5, 0.5]},
        "body": {"point_m": [0.1, 0.1, 0.1], "size_m": [0.2, 0.2, 0.2]},
        "paddle": None,
    }
    points = [(x, y, z) for x in (0.1, 0.2, 0.3, 0.4) for y in (0.1, 0.2, 0.3, 0.4) for z in (0.1, 0.2, 0.3, 0.4)]
    wall = {
        "planes": {
            "x": {"low_m": 0.0, "high_m": 0.5},
            "y": {"low_m": 0.0, "high_m": 0.5},
            "bottom": {"low_m": 0.0},
        }
    }
    budget = F6R._initial_mass_budget(case, points, [], [], 0.1, 1000.0, 1.0, wall)
    assert budget["nominal_fillbox_volume_m3"] == 0.125
    assert abs(budget["occupancy_overlap_volume_m3"]["floating_body"] - 0.008) < 1e-12
    assert budget["fluid_center_lattice"]["candidate_particle_count"] == 64
    assert budget["raw_nominal_fillbox_mass_relative_error"] < budget["lattice_target_mass_relative_error"]
    assert budget["continuous_physical_fill_tolerance_pass"] is False
    assert budget["effective_center_lattice_tolerance_pass"] is False
    assert budget["support_adjusted_mass_relative_error"] == budget["lattice_target_mass_relative_error"]
    assert budget["initial_mass_tolerance_basis"] == "continuous_physical_fill_after_occupancy"
    assert budget["formula_conclusion"].startswith("the previous raw fillbox-volume denominator")
