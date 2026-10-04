#!/usr/bin/env python3
"""Synthetic unit test suite for F5 compact fallback prospective recipe v1.

Verifies:
  1. Compact physical continuous bed profile nodes, continuity, and slope m = 0.280.
  2. Watertight 52-triangle compact continuous bed STL synthesis.
  3. Observer wave probe local bed elevation alignment (no sub-bed embedding).
  4. Finite wave packet motion properties (smooth start/end, max stroke <= 0.03 m, quiescent tail).
  5. Unequal-r resolution ladder (0.02, 0.0125, 0.01) and particle lattice counts.
  6. Generated XML definitions structure, valid 'full' drawmode syntax, and 3D sidewalls.
  7. Runner request governance (launch_allowed: false, budget limits, qualification counts).

All tests run on synthetic fixtures without executing external scientific workflows or GPUs.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from generate_compact_continuous_bed_stl import (
    COMPACT_BED_PROFILE_NODES,
    build_compact_bed_triangles,
    compute_bed_elevation,
    generate_stl_ascii_text,
    get_observer_bed_elevations,
    verify_mesh_topology,
)
from generate_compact_packet_motion import (
    evaluate_motion_profile,
    generate_motion_table,
    validate_motion_series,
)
from prepare_compact_fallback_cases import (
    GAUGES_SPEC,
    RESOLUTIONS,
    build_xml_definition,
    stage_all_case_definitions,
)


def test_continuous_bed_profile_geometry() -> None:
    """Validate 2D profile continuity, monotonically increasing x, and authentic slope."""
    nodes = COMPACT_BED_PROFILE_NODES
    assert len(nodes) == 7

    # Check monotonicity of x
    for i in range(len(nodes) - 1):
        assert nodes[i + 1][0] > nodes[i][0]

    # Upstream flat basin under fluid
    assert nodes[0] == (-0.20, 0.000)
    assert nodes[1] == (2.00, 0.000)

    # Slope toe to crest
    slope = (nodes[3][1] - nodes[1][1]) / (nodes[3][0] - nodes[1][0])
    assert abs(slope - 0.280) < 1e-6, f"Slope should be 0.280, got {slope}"

    # Crest plateau
    assert nodes[3] == (3.60, 0.448)
    assert nodes[4] == (3.90, 0.448)

    # Downslope to receiving basin
    assert nodes[5] == (4.40, 0.050)
    assert nodes[6] == (4.80, 0.050)


def test_bed_elevation_interpolation() -> None:
    """Validate piecewise linear interpolation along longitudinal axis."""
    # Upstream flat bed
    assert abs(compute_bed_elevation(-0.20) - 0.000) < 1e-6
    assert abs(compute_bed_elevation(0.50) - 0.000) < 1e-6
    assert abs(compute_bed_elevation(2.00) - 0.000) < 1e-6

    # Sloping section
    z_mid = compute_bed_elevation(2.80)
    expected_mid = (2.80 - 2.00) * 0.280
    assert abs(z_mid - expected_mid) < 1e-6

    # Crest plateau
    assert abs(compute_bed_elevation(3.60) - 0.448) < 1e-6
    assert abs(compute_bed_elevation(3.75) - 0.448) < 1e-6
    assert abs(compute_bed_elevation(3.90) - 0.448) < 1e-6

    # Receiving basin
    assert abs(compute_bed_elevation(4.60) - 0.050) < 1e-6


def test_observer_bed_alignment_no_subbed() -> None:
    """Verify all Eulerian wave probes have point0.z strictly equal to true local bed elevation."""
    for gauge in GAUGES_SPEC:
        x = float(gauge["x"])
        point0_z = float(gauge["point0_z"])
        z_bed = compute_bed_elevation(x)

        # Baseline must exactly match local bed elevation
        assert abs(point0_z - z_bed) < 1e-6, (
            f"Gauge {gauge['name']} point0_z={point0_z} does not match bed {z_bed}"
        )
        # Baseline must NOT be below the bed
        assert point0_z >= z_bed - 1e-9, (
            f"Gauge {gauge['name']} is embedded below bed: point0_z={point0_z} < z_bed={z_bed}"
        )
        # Sensor column must extend upward into air
        assert float(gauge["point2_z"]) > point0_z


def test_motion_packet_properties() -> None:
    """Verify finite single-wave packet starts/ends at zero with quiescent tail."""
    table = generate_motion_table()
    assert len(table) == 641  # 16.0 s at 40 Hz + 1 point

    report = validate_motion_series(table)
    assert report["is_valid"] is True
    assert report["peak_excursion_m"] <= 0.030
    assert report["max_tail_residual_m"] < 1e-12

    # Verify smooth start
    t0, x0 = table[0]
    t1, x1 = table[1]
    assert t0 == 0.0 and abs(x0) < 1e-12
    assert abs(x1) < 0.001  # Gentle initial displacement

    # Verify quiescent tail for t >= 5.0 s
    for t, x in table:
        if t >= 5.0:
            assert abs(x) < 1e-12, f"Non-zero motion during quiescent tail at t={t}: {x}"


def test_compact_bed_triangles_topology() -> None:
    """Verify 52-triangle watertight compact bed mesh topology."""
    report = verify_mesh_topology()
    assert report["facets_count"] == 52
    assert report["is_watertight_candidate"] is True
    assert abs(report["bounds_m"]["x"][0] - (-0.20)) < 1e-6
    assert abs(report["bounds_m"]["x"][1] - 4.80) < 1e-6
    assert abs(report["bounds_m"]["y"][0] - (-0.15)) < 1e-6
    assert abs(report["bounds_m"]["y"][1] - 0.15) < 1e-6
    assert abs(report["crest_elevation_m"] - 0.448) < 1e-6

    # Verify STL text format
    stl_text = generate_stl_ascii_text("test_bed")
    assert stl_text.startswith("solid test_bed")
    assert stl_text.endswith("endsolid test_bed\n")
    assert stl_text.count("facet normal") == 52
    assert stl_text.count("outer loop") == 52
    assert stl_text.count("endloop") == 52
    assert stl_text.count("vertex") == 52 * 3


def test_unequal_r_resolution_ladder() -> None:
    """Verify the 3-resolution ladder [0.02, 0.0125, 0.01] and particle predictions."""
    assert len(RESOLUTIONS) == 3
    assert set(RESOLUTIONS.keys()) == {"dp020", "dp0125", "dp010"}

    # Refinement ratios
    assert RESOLUTIONS["dp020"]["ratio_to_fine"] == 2.0
    assert RESOLUTIONS["dp020"]["ratio_to_medium"] == 1.6
    assert RESOLUTIONS["dp0125"]["ratio_to_fine"] == 1.25
    assert RESOLUTIONS["dp010"]["ratio_to_fine"] == 1.0

    # Theoretical Cartesian lattice fluid particles
    # Vol = 2.00 * 0.30 * 0.40 = 0.240 m^3
    assert RESOLUTIONS["dp010"]["theoretical_fluid_lattice_particles"] == 240000
    assert RESOLUTIONS["dp0125"]["theoretical_fluid_lattice_particles"] == 122880
    assert RESOLUTIONS["dp020"]["theoretical_fluid_lattice_particles"] == 30000

    # Maxwall budget bounds
    fine_maxwall_gpu_h = (
        RESOLUTIONS["dp010"]["maxwall_seconds"] / 3600.0 * 2  # Runup + Weir
    )
    assert fine_maxwall_gpu_h <= 2.0, f"Fine pair maxwall too high: {fine_maxwall_gpu_h}"


def test_xml_generation_and_validity(tmp_path: Path) -> None:
    """Verify XML generation for all 6 cases with valid drawmode syntax and boundaries."""
    manifest = stage_all_case_definitions(tmp_path)
    assert manifest["summary"]["total_cases"] == 6

    for case in manifest["cases"]:
        xml_file = tmp_path / case["xml_relpath"]
        assert xml_file.is_file()

        # Parse XML
        tree = ET.parse(xml_file)
        root = tree.getroot()
        assert root.tag == "case"

        # Check definition
        dp_attr = root.find("casedef/geometry/definition").attrib["dp"]
        assert float(dp_attr) == pytest.approx(case["dp_m"])

        # Check drawmode syntax: full used for triangles and STL, solid restored for walls
        commands = root.find("casedef/geometry/commands/mainlist")
        drawmodes = [el.attrib.get("mode") for el in commands.findall("setdrawmode")]
        assert "full" in drawmodes, "Proven valid 'full' drawmode must be used"
        assert "solid" in drawmodes, "Valid 'solid' drawmode must be used"

        # Check 3D sidewalls at y = -0.15 and y = 0.15
        sidewall_l = commands.find("drawbox[@cmt='finite_sidewall_left']")
        sidewall_r = commands.find("drawbox[@cmt='finite_sidewall_right']")
        assert sidewall_l is not None
        assert sidewall_r is not None
        assert sidewall_l.find("point").attrib["y"] == "-0.18"
        assert sidewall_r.find("point").attrib["y"] == "0.15"

        # Check weir presence
        weir_boxes = [
            b for b in commands.findall("drawbox") if "weir" in b.attrib.get("cmt", "")
        ]
        if case["mechanism"] == "weir_overtopping":
            assert len(weir_boxes) == 3, "Weir case must have left, right, and notch segments"
        else:
            assert len(weir_boxes) == 0, "Runup case must not have weir segments"

        # Check gauges
        gauges = root.findall("execution/special/gauges/swl")
        assert len(gauges) == 6
        for g in gauges:
            name = g.attrib["name"]
            spec = next(s for s in GAUGES_SPEC if s["name"] == name)
            assert float(g.find("point0").attrib["z"]) == pytest.approx(spec["point0_z"])


def test_runner_requests_governance() -> None:
    """Verify all runner request JSON files adhere to strict governance rules."""
    req_dir = Path(__file__).parent / "requests"
    req_files = list(req_dir.glob("*.json"))
    assert len(req_files) == 3, f"Expected 3 request files, found {len(req_files)}"

    for rf in req_files:
        data = json.loads(rf.read_text(encoding="utf-8"))
        assert data["schema"] == "ds02.runner-request.v2"
        assert data["family_id"] == "F5"
        # Strict rule: launch_allowed must be false for scoped source work
        assert data["governance"]["launch_allowed"] is False
        assert data["governance"]["launch_owner"] == "root"

    # Solver request specific checks
    solver_req = json.loads(
        (req_dir / "F5_COMPACT_FALLBACK_SOLVER_3DP_REQUEST.json").read_text(encoding="utf-8")
    )
    b_acc = solver_req["budget_accounting"]
    assert b_acc["campaign_budget_gpu_hours"] == 96.0
    assert b_acc["charged_gpu_hours"] == 66.7
    assert b_acc["remaining_reserve_gpu_hours"] == 29.3
    assert b_acc["fine_pair_maxwall_gpu_hours"] <= 2.00
    assert b_acc["total_ladder_maxwall_gpu_hours"] <= 3.50


def test_compact_fallback_specification() -> None:
    """Verify compact fallback specification schema and parameters."""
    spec_path = Path(__file__).parent / "compact_fallback_specification.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    assert spec["schema"] == "ds02.f5.compact-fallback-specification.v1"
    assert spec["family_id"] == "F5"
    assert spec["physical_dimensions"]["flume_width_m"] == 0.30
    assert spec["physical_dimensions"]["fluid_length_m"] == 2.00
    assert spec["physical_dimensions"]["representative_depth_H_m"] == 0.40
    assert spec["physical_dimensions"]["nominal_fluid_mass_kg"] == 240.0
    assert spec["continuous_bed"]["slope_m"] == 0.280
    assert spec["continuous_bed"]["drawmode_syntax"] == "full"
    assert len(spec["resolutions_ladder"]) == 4  # policy + 3 resolutions
    assert len(spec["observer_specification"]["gauges"]) == 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
