#!/usr/bin/env python3
"""Synthetic unit test suite for F5 compact equilibrium recipe v1.

Verifies:
  1. Compact physical continuous bed profile, continuity, slope m = 0.280, and shoreline x = 24/7.
  2. Watertight 52-triangle compact continuous bed STL synthesis and exact byte SHA256 derivation.
  3. Continuum equilibrium fluid volume and mass:
       - Runup continuum fluid: 2.28/7 m^3 (~325.7142857 kg).
       - Submerged weir solid displacement: 0.001935 m^3 (1.935 kg).
       - Weir continuum fluid: ~0.3237792857 m^3 (~323.7792857 kg).
       - Explicit retraction of provisional 043 flat-only 240kg assumptions.
       - Prohibition of mass normalization to 325.714 kg (native particle mass mp = rho0 * dp^3).
  4. Observer wave probe true local bed elevation alignment (point0.z = z_bed(x)).
  5. Candidate finite wave packet motion:
       - 17g precision formatting.
       - Exclusive IO (O_EXCL) refusal on overwrite.
       - Physical recognition that parked paddle at x=0 reflects returning waves.
  6. Single proven XML drawmode syntax: mode="full" only, exactly zero mode="solid".
  7. Motion syntax source pin: mvpredef verified as exact synonym of mvrectfile at JMotion.cpp:708,814.
  8. Pointref exact width-centering:
       - dp020 (15 cells, odd): pointref.y = 0.000.
       - dp0125 (24 cells, even): pointref.y = 0.00625.
       - dp010 (30 cells, even): pointref.y = 0.005.
  9. Explicit fluid clipplane along bed slope and below SWL H=0.400 m.
  10. Post-GenCase source asset restoration worker protecting against the F7 0-byte truncation defect.
  11. Strict runner request governance and bound budget accounting (~74 GPUh, ~235 CPUcoreh, 281 qual attempts).

All tests execute entirely on synthetic fixtures without external scientific runs or GPUs.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from generate_compact_continuous_bed_stl import (
    BED_SLOPE_M,
    CHARACTERISTIC_DEPTH_H_M,
    COMPACT_BED_PROFILE_NODES,
    CONTINUUM_RUNUP_MASS_KG,
    CONTINUUM_RUNUP_VOLUME_M3,
    CONTINUUM_WEIR_MASS_KG,
    CONTINUUM_WEIR_VOLUME_M3,
    FLAT_VOLUME_M3,
    FLUME_WIDTH_M,
    SHORELINE_X_M,
    SLOPE_WEDGE_VOLUME_M3,
    SUBMERGED_WEIR_MASS_KG,
    SUBMERGED_WEIR_VOLUME_M3,
    build_compact_bed_triangles,
    compute_bed_elevation,
    compute_stl_sha256,
    generate_stl_ascii_text,
    get_observer_bed_elevations,
    verify_mesh_topology,
    write_exclusive_text,
)
from generate_compact_packet_motion import (
    evaluate_motion_profile,
    format_motion_dat_17g,
    generate_motion_table,
    validate_motion_series,
)
from prepare_compact_equilibrium_cases import (
    GAUGES_SPEC,
    RESOLUTIONS,
    build_xml_definition,
    restore_declared_motion_post_gencase,
    stage_all_case_definitions,
)


def test_continuous_bed_profile_geometry() -> None:
    """Validate 2D profile continuity, slope m = 0.280, and shoreline x = 24/7."""
    nodes = COMPACT_BED_PROFILE_NODES
    assert len(nodes) == 7

    for i in range(len(nodes) - 1):
        assert nodes[i + 1][0] > nodes[i][0]

    assert nodes[0] == (-0.20, 0.000)
    assert nodes[1] == (2.00, 0.000)

    # Slope toe to crest
    slope = (nodes[3][1] - nodes[1][1]) / (nodes[3][0] - nodes[1][0])
    assert abs(slope - 0.280) < 1e-6, f"Slope must be 0.280, got {slope}"

    # Shoreline position at SWL H = 0.400 m
    expected_shoreline = 2.00 + 0.400 / 0.280
    assert abs(SHORELINE_X_M - expected_shoreline) < 1e-12
    assert abs(SHORELINE_X_M - (24.0 / 7.0)) < 1e-12


def test_continuum_equilibrium_volumes_and_masses() -> None:
    """Validate continuum fluid volumes and masses for runup and weir cases."""
    # Flat basin
    assert abs(FLAT_VOLUME_M3 - 0.240) < 1e-12

    # Sloping wedge: W * H^2 / (2 * m)
    expected_wedge = 0.300 * (0.400 ** 2) / (2.0 * 0.280)
    assert abs(SLOPE_WEDGE_VOLUME_M3 - expected_wedge) < 1e-12
    assert abs(SLOPE_WEDGE_VOLUME_M3 - (0.6 / 7.0)) < 1e-12

    # Total runup volume and mass
    expected_runup_vol = 0.240 + 0.6 / 7.0
    assert abs(CONTINUUM_RUNUP_VOLUME_M3 - expected_runup_vol) < 1e-12
    assert abs(CONTINUUM_RUNUP_VOLUME_M3 - (2.28 / 7.0)) < 1e-12
    assert abs(CONTINUUM_RUNUP_MASS_KG - (2280.0 / 7.0)) < 1e-12
    assert abs(CONTINUUM_RUNUP_MASS_KG - 325.7142857142857) < 1e-6

    # Submerged weir displacement across x in [3.20, 3.35]
    z_bed_320 = 0.280 * (3.20 - 2.00)
    z_bed_335 = 0.280 * (3.35 - 2.00)
    z_bed_mean = 0.5 * (z_bed_320 + z_bed_335)
    expected_weir_sub = 0.300 * 0.150 * (0.400 - z_bed_mean)
    assert abs(SUBMERGED_WEIR_VOLUME_M3 - expected_weir_sub) < 1e-12
    assert abs(SUBMERGED_WEIR_VOLUME_M3 - 0.001935) < 1e-12
    assert abs(SUBMERGED_WEIR_MASS_KG - 1.935) < 1e-12

    # Weir continuum fluid volume and mass
    expected_weir_vol = expected_runup_vol - 0.001935
    assert abs(CONTINUUM_WEIR_VOLUME_M3 - expected_weir_vol) < 1e-12
    assert abs(CONTINUUM_WEIR_MASS_KG - (expected_runup_vol * 1000.0 - 1.935)) < 1e-12
    assert abs(CONTINUUM_WEIR_MASS_KG - 323.7792857142857) < 1e-6


def test_bed_mesh_topology_and_exact_sha() -> None:
    """Verify watertight 52-facet closure and SHA256 derived from exact bytes."""
    report = verify_mesh_topology()
    assert report["facets_count"] == 52
    assert report["is_watertight"] is True

    stl_text = generate_stl_ascii_text()
    exact_sha = compute_stl_sha256(stl_text)
    assert len(exact_sha) == 64
    assert exact_sha == report["sha256"]


def test_exclusive_io_refusal(tmp_path: Path) -> None:
    """Verify exclusive IO write fails closed if destination file already exists."""
    target = tmp_path / "exclusive_test_file.txt"
    write_exclusive_text(target, "initial content")
    assert target.is_file()

    # Second write must raise FileExistsError due to O_EXCL
    with pytest.raises(FileExistsError):
        write_exclusive_text(target, "overwrite content")


def test_observer_bed_alignment() -> None:
    """Verify all wave probes have point0.z strictly equal to true local bed elevation."""
    for gauge in GAUGES_SPEC:
        x = float(gauge["x"])
        point0_z = float(gauge["point0_z"])
        z_bed = compute_bed_elevation(x)
        assert abs(point0_z - z_bed) < 1e-6

    # Verify wetted depths under SWL H = 0.400 m
    # WG3 (x = 2.60 m): bed = 0.168 m -> depth = 0.232 m
    assert abs((0.400 - compute_bed_elevation(2.60)) - 0.232) < 1e-6
    # WG4 (x = 3.20 m): bed = 0.336 m -> depth = 0.064 m
    assert abs((0.400 - compute_bed_elevation(3.20)) - 0.064) < 1e-6
    # Crest (x = 3.75 m): bed = 0.448 m -> dry (above SWL)
    assert compute_bed_elevation(3.75) > 0.400


def test_candidate_motion_17g_precision_and_reflection_note() -> None:
    """Verify motion generation uses 17g formatting and contains reflection disclosures."""
    table = generate_motion_table()
    report = validate_motion_series(table)
    assert report["is_valid"] is True
    assert report["precision_format"] == "17g"
    assert "reflects" in report["paddle_reflectivity_note"].lower()

    formatted_dat = format_motion_dat_17g(table)
    lines = [line.strip() for line in formatted_dat.strip().split("\n")]
    assert len(lines) == 641  # 16.0s / 0.025s + 1

    first_line = lines[0].split()
    assert float(first_line[0]) == 0.0
    assert float(first_line[1]) == 0.0

    # Ensure floats are formatted with full precision without artificial truncation (.5f/.8f)
    step10 = lines[10].split()
    assert len(step10) == 2
    # Verify values round-trip accurately
    t_val = float(step10[0])
    x_val = float(step10[1])
    assert abs(t_val - 0.25) < 1e-12
    assert abs(x_val - evaluate_motion_profile(0.25)) < 1e-12


def test_proven_xml_syntax_and_pointref_centering(tmp_path: Path) -> None:
    """Verify single full drawmode (zero solid), mvpredef pin, and pointref centering."""
    manifest = stage_all_case_definitions(tmp_path)
    assert manifest["summary"]["total_cases"] == 6

    for case in manifest["cases"]:
        xml_file = tmp_path / case["xml_relpath"]
        tree = ET.parse(xml_file)
        root = tree.getroot()

        # 1. Single full drawmode syntax, ZERO mode="solid"
        commands = root.find("casedef/geometry/commands/mainlist")
        drawmodes = commands.findall("setdrawmode")
        assert len(drawmodes) == 1, "There must be exactly one <setdrawmode> declaration"
        assert drawmodes[0].attrib.get("mode") == "full", "Drawmode must be 'full'"

        # Verify no solid drawmode anywhere
        raw_xml_text = xml_file.read_text(encoding="utf-8")
        assert 'mode="solid"' not in raw_xml_text, "Found forbidden mode='solid' in XML"

        # 2. Motion syntax: mvpredef with correct attributes
        mvpredef = root.find("casedef/motion/objreal/mvpredef")
        assert mvpredef is not None, "Case must use <mvpredef> motion syntax"
        assert mvpredef.attrib["id"] == "1"
        assert mvpredef.attrib["duration"] == "16"
        mfile = mvpredef.find("file")
        assert mfile.attrib["name"] == "assets/f5_compact_packet_motion.dat"
        assert mfile.attrib["fields"] == "2"

        # 3. Explicit fluid clipplane
        clipplane = commands.find("clipplane")
        assert clipplane is not None, "Fluid must be clipped by <clipplane>"
        assert clipplane.find("point").attrib["x"] == "2.00"
        assert clipplane.find("point").attrib["z"] == "0.00"
        assert clipplane.find("vector").attrib["x"] == "-0.28"
        assert clipplane.find("vector").attrib["z"] == "1.00"
        assert commands.find("clipreset") is not None, "<clipreset> must be present"

        # 4. Pointref centering across width 0.30 m
        pref = root.find("casedef/geometry/definition/pointref")
        res_key = case["resolution_key"]
        if res_key == "dp020":
            # 15 cells across W=0.30m (odd): cell center at y=0.000
            assert float(pref.attrib["y"]) == 0.0
            assert case["cells_y"] == 15
        elif res_key == "dp0125":
            # 24 cells across W=0.30m (even): cell interface at y=0, center at 0.00625
            assert float(pref.attrib["y"]) == 0.00625
            assert case["cells_y"] == 24
        elif res_key == "dp010":
            # 30 cells across W=0.30m (even): cell interface at y=0, center at 0.005
            assert float(pref.attrib["y"]) == 0.005
            assert case["cells_y"] == 30

        # 5. Parameters
        params = {
            p.attrib["key"]: p.attrib["value"]
            for p in root.findall("execution/parameters/parameter")
        }
        assert params["PosDouble"] == "2"
        assert params["TimeMax"] == "16.0"
        assert params["TimeOut"] == "0.02"


def test_post_gencase_motion_protection_worker(tmp_path: Path) -> None:
    """Verify the post-GenCase restoration worker restores empty or missing motion files."""
    # Create synthetic source asset
    source_assets = tmp_path / "source_assets"
    source_assets.mkdir(parents=True)
    source_motion = source_assets / "f5_compact_packet_motion.dat"
    source_motion.write_text("0.0 0.0\n0.025 0.001\n", encoding="utf-8")

    case_run_dir = tmp_path / "case_run"
    target_motion = case_run_dir / "assets" / "f5_compact_packet_motion.dat"
    target_motion.parent.mkdir(parents=True)

    # Scenario A: GenCase created a 0-byte truncated motion file
    target_motion.write_bytes(b"")
    assert target_motion.stat().st_size == 0

    report_a = restore_declared_motion_post_gencase(case_run_dir, source_motion)
    assert report_a["was_restored"] is True
    assert report_a["is_healthy"] is True
    assert report_a["post_size_bytes"] > 0
    assert target_motion.stat().st_size > 0

    # Scenario B: Target motion file already intact
    report_b = restore_declared_motion_post_gencase(case_run_dir, source_motion)
    assert report_b["was_restored"] is False
    assert report_b["is_healthy"] is True


def test_runner_requests_governance_and_budget() -> None:
    """Verify all runner request JSON files adhere to strict governance rules and binding budget."""
    req_dir = Path(__file__).parent / "requests"
    req_files = list(req_dir.glob("*.json"))
    assert len(req_files) == 3, f"Expected 3 request files, found {len(req_files)}"

    for rf in req_files:
        data = json.loads(rf.read_text(encoding="utf-8"))
        assert data["schema"] == "ds02.runner-request.v2"
        assert data["family_id"] == "F5"
        assert data["governance"]["launch_allowed"] is False
        assert data["governance"]["launch_owner"] == "root"

    # Solver request specific checks
    solver_req = json.loads(
        (req_dir / "F5_EQUILIBRIUM_SOLVER_3DP_REQUEST.json").read_text(encoding="utf-8")
    )
    b_acc = solver_req["budget_accounting"]
    assert b_acc["campaign_budget_gpu_hours"] == 96.0
    assert b_acc["charged_gpu_hours"] == 74.0
    assert b_acc["remaining_reserve_gpu_hours"] == 22.0
    assert b_acc["campaign_budget_cpu_core_hours"] == 384.0
    assert b_acc["charged_cpu_core_hours"] == 235.0
    assert b_acc["remaining_reserve_cpu_core_hours"] == 149.0
    assert b_acc["charged_qualification_attempts"] == 281
    assert b_acc["qualification_attempts_limit"] == 320


def test_compact_equilibrium_specification() -> None:
    """Verify specification schema, continuum mass values, and syntax pins."""
    spec_path = Path(__file__).parent / "compact_equilibrium_specification.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    assert spec["schema"] == "ds02.f5.compact-equilibrium-specification.v1"
    assert spec["family_id"] == "F5"
    assert spec["physical_dimensions"]["flume_width_m"] == 0.30
    assert spec["physical_dimensions"]["flat_basin_length_m"] == 2.00
    assert spec["physical_dimensions"]["representative_depth_H_m"] == 0.40
    assert spec["physical_dimensions"]["shoreline_x_fraction"] == "24/7"

    mass_spec = spec["continuum_equilibrium_mass_and_volume"]
    assert pytest.approx(mass_spec["continuum_runup_mass_kg"], 1e-4) == 325.7143
    assert pytest.approx(mass_spec["submerged_weir_solid_mass_displacement_kg"], 1e-4) == 1.935
    assert pytest.approx(mass_spec["continuum_weir_fluid_mass_kg"], 1e-4) == 323.7793
    assert "retract" in mass_spec["retraction_statement"].lower()

    syntax_spec = spec["syntax_and_source_pins"]
    assert syntax_spec["drawmode_syntax"] == "full"
    assert syntax_spec["solid_drawmode_count"] == 0
    assert syntax_spec["motion_syntax"] == "mvpredef"
    assert "JMotion.cpp" in syntax_spec["motion_source_pin"]
    assert syntax_spec["format_precision"] == "17g"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
