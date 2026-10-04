#!/usr/bin/env python3
"""Synthetic test suite for F5 Root Followup 042 prospective fallback fix v1.

Verifies:
  1. Bed profile geometry formulas and plateau crest elevation (z = 0.840 m).
  2. Watertight 60-triangle continuous bed mesh synthesis and official hash binding.
  3. Single-wave packet forcing physics, stroke bound, and quiescent tail.
  4. Eulerian observer layout alignment (point0.z == z_bed, no subterranean embedding).
  5. Commensurate spatial particle scaling across dp=0.050, 0.025, 0.010 m.
  6. Structural integrity and schema validity across all 6 XML case definitions.
  7. Strict Rootguard runner request governance (launch_allowed == False, launch_owner == 'root').
  8. Absence of unauthorized actual scientific outputs outside Rootguard.
"""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from generate_continuous_bed_stl import (
    BED_PROFILE_NODES,
    OFFICIAL_BED_STL_SHA256,
    build_bed_triangles,
    compute_bed_elevation,
    verify_mesh_topology,
)
from generate_single_packet_motion import (
    generate_motion_table,
    validate_motion_series,
)
from prepare_fallback_cases import (
    CORRECTED_GAUGES,
    NOMINAL_FLUID_MASS_KG,
    RESOLUTIONS,
    build_case_xml,
)

SCOPE_DIR = Path(__file__).parent


class TestBedProfileGeometry:
    """Validate continuous flume bed geometry and authentic profile nodes."""

    def test_key_longitudinal_elevations(self) -> None:
        """Verify elevations along continuous profile with zero extrapolation error."""
        # Flat entrance floor
        assert compute_bed_elevation(-1.10) == pytest.approx(0.000, abs=1e-6)
        assert compute_bed_elevation(0.00) == pytest.approx(0.000, abs=1e-6)
        assert compute_bed_elevation(3.55) == pytest.approx(0.000, abs=1e-6)

        # Ramp section (slope m = 0.280)
        assert compute_bed_elevation(4.35) == pytest.approx(0.224, abs=1e-4)  # (4.35-3.55)*0.280
        assert compute_bed_elevation(5.15) == pytest.approx(0.448, abs=1e-4)
        assert compute_bed_elevation(5.45) == pytest.approx(0.532, abs=1e-4)  # 0.448 + (5.45-5.15)*0.280
        assert compute_bed_elevation(6.55) == pytest.approx(0.840, abs=1e-4)

        # Authentic crest plateau (NOT extrapolated 0.882)
        assert compute_bed_elevation(6.70) == pytest.approx(0.840, abs=1e-6)
        assert compute_bed_elevation(7.15) == pytest.approx(0.840, abs=1e-6)

        # Downstream slope and floor
        assert compute_bed_elevation(9.45) == pytest.approx(0.370, abs=1e-4)
        assert compute_bed_elevation(10.50) == pytest.approx(0.080, abs=1e-4)
        assert compute_bed_elevation(10.85) == pytest.approx(0.080, abs=1e-4)

    def test_triangle_mesh_topology(self) -> None:
        """Verify synthesized 60-triangle mesh dimensions and facet count."""
        report = verify_mesh_topology()
        assert report["facets_count"] == 60
        assert report["crest_elevation_m"] == pytest.approx(0.840, abs=1e-6)
        assert report["is_watertight_candidate"] is True

    def test_official_bed_stl_sha256_binding(self) -> None:
        """Verify official immutable hash string is properly bound."""
        assert len(OFFICIAL_BED_STL_SHA256) == 64
        assert OFFICIAL_BED_STL_SHA256 == (
            "93cf180ae6d5439d3ed3e2787b390d3b1268d76f0069dbdeaa10b18bf3314621"
        )


class TestSinglePacketForcing:
    """Validate finite wave packet kinematics and non-reflective tail."""

    def test_motion_table_properties(self) -> None:
        table = generate_motion_table(total_time=16.0, dt=0.025, t_gen=7.50)
        assert len(table) == 641  # 16.0 / 0.025 + 1

        # Check boundary condition at t=0
        t0, x0 = table[0]
        assert t0 == 0.0
        assert x0 == pytest.approx(0.0, abs=1e-12)

        # Check quiescent tail for t >= 7.5 s
        for t, x in table:
            if t >= 7.50:
                assert abs(x) < 1e-12, f"Paddle non-stationary at t={t}: x={x}"

    def test_motion_series_validation(self) -> None:
        table = generate_motion_table(total_time=16.0, dt=0.025, t_gen=7.50)
        report = validate_motion_series(table, t_gen=7.50, max_stroke=0.030)
        assert report["is_quiescent_verified"] is True
        assert report["peak_stroke_m"] <= 0.030
        assert report["max_velocity_m_s"] < 0.20


class TestObserverGaugeAlignment:
    """Verify Eulerian observer alignment with continuous bed elevation."""

    def test_no_subterranean_embedding(self) -> None:
        """Ensure all wave gauge baseline point0.z coordinates equal z_bed."""
        for g in CORRECTED_GAUGES:
            x = float(g["x"])
            z_expected = compute_bed_elevation(x)
            assert float(g["z_bed"]) == pytest.approx(z_expected, abs=1e-4)

        # Specific probe assertions
        gauge_map = {g["name"]: g for g in CORRECTED_GAUGES}
        assert gauge_map["WG1"]["z_bed"] == 0.000
        assert gauge_map["WG2"]["z_bed"] == 0.000
        assert gauge_map["RunupToe"]["z_bed"] == 0.000
        assert gauge_map["WG3"]["z_bed"] == 0.224
        assert gauge_map["WG4"]["z_bed"] == 0.532
        assert gauge_map["Crest"]["z_bed"] == 0.840  # Authentic plateau


class TestCommensurateScaling:
    """Verify spatial particle scaling and fluid mass conservation."""

    def test_dp_ladder_fluid_particles(self) -> None:
        vol = 4.20 * 1.40 * 0.40  # 2.352 m^3
        mass = vol * 1000.0  # 2352.0 kg
        assert mass == pytest.approx(NOMINAL_FLUID_MASS_KG, abs=1e-6)

        # dp=0.050 m
        coarse_n = RESOLUTIONS["dp050"]["predicted_fluid_particles"]
        assert coarse_n == int(round((4.20 / 0.05) * (1.40 / 0.05) * (0.40 / 0.05)))
        assert coarse_n == 18816

        # dp=0.025 m
        medium_n = RESOLUTIONS["dp025"]["predicted_fluid_particles"]
        assert medium_n == int(round((4.20 / 0.025) * (1.40 / 0.025) * (0.40 / 0.025)))
        assert medium_n == 150528

        # dp=0.010 m
        fine_n = RESOLUTIONS["dp010"]["predicted_fluid_particles"]
        assert fine_n == int(round((4.20 / 0.010) * (1.40 / 0.010) * (0.40 / 0.010)))
        assert fine_n == 2352000

        # Commensurate ratios: (0.05/0.025)^3 = 8, (0.025/0.01)^3 = 15.625
        assert medium_n / coarse_n == 8.0
        assert fine_n / medium_n == 15.625


class TestXMLDefinitions:
    """Verify structural validity and physical content of prepared XML definitions."""

    @pytest.mark.parametrize("mechanism", ["runup", "weir"])
    @pytest.mark.parametrize("res_key", ["dp050", "dp025", "dp010"])
    def test_xml_structure_and_parameters(self, mechanism: str, res_key: str) -> None:
        case_id = f"F5_REF_{mechanism.upper()}_{res_key.upper()}_FALLBACK_042"
        xml_file = SCOPE_DIR / "definitions" / mechanism / f"{case_id}.xml"
        assert xml_file.is_file(), f"Missing XML definition: {xml_file}"

        tree = ET.parse(xml_file)
        root = tree.getroot()

        # Check surface-first 60-triangle bed support
        dtri = root.find(".//geometry/commands/mainlist/drawtriangles")
        assert dtri is not None, "Missing drawtriangles element"
        triangles = dtri.findall("./triangles/triangle")
        assert len(triangles) == 60, f"Expected 60 bed triangles, got {len(triangles)}"
        points = dtri.findall("./points/point")
        assert len(points) == 180, f"Expected 180 bed points, got {len(points)}"

        # Check motion references single-packet file
        pfile = root.find(".//casedef/motion/objreal/mvpredef/file")
        assert pfile is not None
        assert pfile.get("name") == "control_single_packet.dat"

        # Check 6 corrected gauges
        gauges = root.findall(".//execution/special/gauges/swl")
        assert len(gauges) == 6
        gauge_names = [g.get("name") for g in gauges]
        assert gauge_names == ["WG1", "WG2", "RunupToe", "WG3", "WG4", "Crest"]

        # Check weir segments if weir case
        if mechanism == "weir":
            weir_boxes = root.findall(".//geometry/commands/mainlist/drawbox[@cmt]")
            weir_cmts = [b.get("cmt") for b in weir_boxes if "weir_" in str(b.get("cmt"))]
            assert "weir_left_side_segment" in weir_cmts
            assert "weir_right_side_segment" in weir_cmts


class TestRunnerRequestsGovernance:
    """Validate Rootguard governance across all runner requests."""

    @pytest.mark.parametrize("req_name", [
        "F5_FALLBACK_PREPARATION_REQUEST",
        "F5_FALLBACK_GENCASE_3DP_REQUEST",
        "F5_FALLBACK_SOLVER_3DP_REQUEST",
    ])
    def test_request_governance(self, req_name: str) -> None:
        req_file = SCOPE_DIR / "requests" / f"{req_name}.json"
        assert req_file.is_file(), f"Missing runner request: {req_file}"

        req = json.loads(req_file.read_text(encoding="utf-8"))
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["governance"]["launch_allowed"] is False
        assert req["governance"]["launch_owner"] == "root"


class TestNoUnauthorizedScientificOutputs:
    """Verify that no actual scientific binaries or arrays were generated outside Rootguard."""

    def test_clean_workspace(self) -> None:
        forbidden_extensions = [".bi4", ".h5part", ".csv", ".stl", ".vtk"]
        for p in SCOPE_DIR.rglob("*"):
            if p.is_file():
                assert p.suffix not in forbidden_extensions, (
                    f"Forbidden scientific output file found: {p}"
                )
