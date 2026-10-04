#!/usr/bin/env python3
"""F5 compact equilibrium patched case definition synthesizer.

Generates the 6 patched DualSPHysics XML case definitions for the F5 compact equilibrium
configuration (3 Runup cases, 3 Weir cases) across 3 commensurate resolutions
[0.020, 0.0125, 0.010] m.

Incorporates all source-contract fixes:
  1. Clipplane vector sign inversion fix:
       Changes vector from (-0.28, 0, 1.00) to (0.28, 0, -1.00).
       In GenCase (JClipShape::ClipPoint, 0x4f6a30), points with (p - pt).v > 0 are discarded.
       The normal (0.28, 0, -1.00) points into the bed beneath the slope, ensuring that points
       above the bed (z >= 0.28*(x - 2)) satisfy (p - pt).v <= 0 and are retained.
  2. SWL gauge point contract fix:
       Removes superfluous/invalid <point1> from all <swl> gauges. Per JDsGaugeSystem.cpp:284-288,
       <swl> reads only <point0> and <point2>.
  3. Gauge default interval activation:
       Removes leading underscores from <_computedt>, <_computetime>, <_outputdt>, <_outputtime>.
       Per JDsGaugeSystem.cpp:253, tags with leading underscores are ignored by the parser.
  4. Preserves all Root048 parser fixes:
       - <hswl auto="true" value="0" /> (satisfies JCaseCtes::ReadXmlElementAuto)
       - <rhopgradient value="2" /> (hydrostatic water column density gradient)
       - <parameter key="SavePosDouble" value="1" /> (replaces deprecated PosDouble)
       - <parameter key="MinFluidStop" value="0" /> (replaces deprecated PartsOutMax)
       - <parameter key="Boundary" value="1" /> (explicit DBC)
       - <parameter key="DtIni" value="0" /> and <parameter key="DtMin" value="0" />
       - Removal of <parameter key="IncZ" /> to prevent fatal conflict with <simulationdomain> (JSph.cpp:846)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
import xml.etree.ElementTree as ET


COMPACT_BED_PROFILE_NODES: List[Tuple[float, float]] = [
    (-0.20, 0.000),
    (2.00, 0.000),
    (3.00, 0.280),
    (3.60, 0.448),
    (3.90, 0.448),
    (4.40, 0.050),
    (4.80, 0.050),
]

FLUME_WIDTH_M: float = 0.300
Y_HALF_M: float = FLUME_WIDTH_M / 2.0  # 0.150 m
BED_SUB_Z_M: float = -0.150
BED_SLOPE_M: float = 0.280


def compute_bed_elevation(x: float) -> float:
    """Calculates continuous bed elevation z [m] at coordinate x [m]."""
    if x <= 2.000:
        return 0.000
    elif x <= 3.600:
        return 0.280 * (x - 2.000)
    elif x <= 3.900:
        return 0.448
    elif x <= 4.400:
        return 0.448 - (0.448 - 0.050) / (4.400 - 3.900) * (x - 3.900)
    else:
        return 0.050


def build_compact_bed_triangles() -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
    """Synthesizes watertight triangle mesh for the continuous bed solid."""
    nodes = COMPACT_BED_PROFILE_NODES
    n = len(nodes)
    points: List[Tuple[float, float, float]] = []
    triangles: List[Tuple[int, int, int]] = []

    def add_tri(p1: Tuple[float, float, float], p2: Tuple[float, float, float], p3: Tuple[float, float, float]):
        base = len(points)
        points.extend([p1, p2, p3])
        triangles.append((base, base + 1, base + 2))

    def add_quad(p1, p2, p3, p4):
        add_tri(p1, p2, p3)
        add_tri(p1, p3, p4)

    # Top surface (n-1 quads)
    for i in range(n - 1):
        x1, z1 = nodes[i]
        x2, z2 = nodes[i + 1]
        add_quad((x1, -Y_HALF_M, z1), (x2, -Y_HALF_M, z2), (x2, Y_HALF_M, z2), (x1, Y_HALF_M, z1))

    # Bottom surface at z = -0.15 m
    for i in range(n - 1):
        x1, _ = nodes[i]
        x2, _ = nodes[i + 1]
        add_quad((x2, -Y_HALF_M, BED_SUB_Z_M), (x1, -Y_HALF_M, BED_SUB_Z_M), (x1, Y_HALF_M, BED_SUB_Z_M), (x2, Y_HALF_M, BED_SUB_Z_M))

    # Left sidewall (y = -0.15 m)
    for i in range(n - 1):
        x1, z1 = nodes[i]
        x2, z2 = nodes[i + 1]
        add_quad((x1, -Y_HALF_M, BED_SUB_Z_M), (x2, -Y_HALF_M, BED_SUB_Z_M), (x2, -Y_HALF_M, z2), (x1, -Y_HALF_M, z1))

    # Right sidewall (y = +0.15 m)
    for i in range(n - 1):
        x1, z1 = nodes[i]
        x2, z2 = nodes[i + 1]
        add_quad((x2, Y_HALF_M, BED_SUB_Z_M), (x1, Y_HALF_M, BED_SUB_Z_M), (x1, Y_HALF_M, z1), (x2, Y_HALF_M, z2))

    # Upstream front face (x = -0.20 m)
    x0, z0 = nodes[0]
    add_quad((x0, Y_HALF_M, BED_SUB_Z_M), (x0, -Y_HALF_M, BED_SUB_Z_M), (x0, -Y_HALF_M, z0), (x0, Y_HALF_M, z0))

    # Downstream back face (x = 4.80 m)
    xe, ze = nodes[-1]
    add_quad((xe, -Y_HALF_M, BED_SUB_Z_M), (xe, Y_HALF_M, BED_SUB_Z_M), (xe, Y_HALF_M, ze), (xe, -Y_HALF_M, ze))

    return points, triangles


RESOLUTIONS: Dict[str, Dict[str, Any]] = {
    "dp020": {
        "dp_m": 0.020,
        "resolution_name": "coarse",
        "ratio_to_fine": 2.0,
        "ratio_to_medium": 1.6,
        "cells_y": 15,
        "pointref": {"x": "0.010", "y": "0.000", "z": "0.010"},
        "fluid_box": {
            "point": {"x": "0.010", "y": "-0.140", "z": "0.010"},
            "size": {"x": "3.42", "y": "0.280", "z": "0.380"},
        },
        "maxwall_seconds": 600,
        "maxwall_gpu_hours": 0.167,
    },
    "dp0125": {
        "dp_m": 0.0125,
        "resolution_name": "medium",
        "ratio_to_fine": 1.25,
        "ratio_to_medium": 1.0,
        "cells_y": 24,
        "pointref": {"x": "0.00625", "y": "0.00625", "z": "0.00625"},
        "fluid_box": {
            "point": {"x": "0.00625", "y": "-0.14375", "z": "0.00625"},
            "size": {"x": "3.4225", "y": "0.2875", "z": "0.3875"},
        },
        "maxwall_seconds": 1800,
        "maxwall_gpu_hours": 0.500,
    },
    "dp010": {
        "dp_m": 0.010,
        "resolution_name": "fine",
        "ratio_to_fine": 1.0,
        "ratio_to_medium": 0.8,
        "cells_y": 30,
        "pointref": {"x": "0.005", "y": "0.005", "z": "0.005"},
        "fluid_box": {
            "point": {"x": "0.005", "y": "-0.145", "z": "0.005"},
            "size": {"x": "3.425", "y": "0.290", "z": "0.390"},
        },
        "maxwall_seconds": 3600,
        "maxwall_gpu_hours": 1.000,
    },
}

GAUGES_SPEC: List[Dict[str, Any]] = [
    {"name": "WG1", "x": 0.60, "y": 0.0, "point0_z": 0.000, "point2_z": 0.70, "coefdp": 0.5},
    {"name": "WG2", "x": 1.40, "y": 0.0, "point0_z": 0.000, "point2_z": 0.70, "coefdp": 0.5},
    {"name": "RunupToe", "x": 2.00, "y": 0.0, "point0_z": 0.000, "point2_z": 0.70, "coefdp": 0.5},
    {"name": "WG3", "x": 2.60, "y": 0.0, "point0_z": 0.168, "point2_z": 0.70, "coefdp": 0.5},
    {"name": "WG4", "x": 3.20, "y": 0.0, "point0_z": 0.336, "point2_z": 0.70, "coefdp": 0.5},
    {"name": "Crest", "x": 3.75, "y": 0.0, "point0_z": 0.448, "point2_z": 0.70, "coefdp": 0.5},
]


def indent_xml(elem: ET.Element, level: int = 0) -> None:
    """Standard XML pretty-print indenter."""
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for subelem in elem:
            indent_xml(subelem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def generate_patched_case_xml(
    mechanism: str,
    res_key: str,
    bed_points: List[Tuple[float, float, float]],
    bed_triangles: List[Tuple[int, int, int]],
) -> str:
    """Synthesizes the patched DualSPHysics XML definition string for one case."""
    res_cfg = RESOLUTIONS[res_key]
    dp = res_cfg["dp_m"]
    pointref = res_cfg["pointref"]
    fluid_box = res_cfg["fluid_box"]

    root = ET.Element("case")
    casedef = ET.SubElement(root, "casedef")

    # Constants definition with exact parser requirements
    constantsdef = ET.SubElement(casedef, "constantsdef")
    ET.SubElement(constantsdef, "gravity", x="0", y="0", z="-9.81", units_comment="m/s^2")
    ET.SubElement(constantsdef, "rhop0", value="1000", units_comment="kg/m^3")
    ET.SubElement(constantsdef, "hswl", auto="true", value="0", units_comment="metres (m)")
    ET.SubElement(constantsdef, "gamma", value="7")
    ET.SubElement(constantsdef, "speedsystem", auto="true", value="0")
    ET.SubElement(constantsdef, "coefsound", value="20")
    ET.SubElement(constantsdef, "speedsound", auto="true", value="0")
    ET.SubElement(constantsdef, "coefh", value="1.0")
    ET.SubElement(constantsdef, "cflnumber", value="0.2")
    ET.SubElement(constantsdef, "rhopgradient", value="2")

    # MkConfig: 240 bounds, 9 fluids
    ET.SubElement(casedef, "mkconfig", boundcount="240", fluidcount="9")

    # Geometry section
    geometry = ET.SubElement(casedef, "geometry")
    definition = ET.SubElement(geometry, "definition", dp=str(dp), units_comment="metres (m)")
    ET.SubElement(definition, "pointref", **pointref)
    ET.SubElement(definition, "pointmin", x="-0.30", y="-0.25", z="-0.25")
    ET.SubElement(definition, "pointmax", x="5.00", y="0.25", z="0.90")

    commands = ET.SubElement(geometry, "commands")
    mainlist = ET.SubElement(commands, "mainlist")

    ET.SubElement(mainlist, "setshapemode").text = "dp | actual | bound"
    ET.SubElement(mainlist, "setdrawmode", mode="full", cmt="proven_dual_sphysics_full_drawmode")

    # Continuous bed surface mesh support (mk=40)
    ET.SubElement(mainlist, "setmkbound", mk="40", cmt="root_numeric_bed_surface_support added boundary marker")
    dtri = ET.SubElement(mainlist, "drawtriangles", cmt="root_numeric_bed_surface_support full compact bed triangle mesh; drawn first")
    pts_el = ET.SubElement(dtri, "points")
    for pt in bed_points:
        ET.SubElement(pts_el, "point", x=f"{pt[0]:.17g}", y=f"{pt[1]:.17g}", z=f"{pt[2]:.17g}")
    tri_el = ET.SubElement(dtri, "triangles")
    for tr in bed_triangles:
        ET.SubElement(tri_el, "triangle", x=str(tr[0]), y=str(tr[1]), z=str(tr[2]))

    # Tank floor (mk=0)
    ET.SubElement(mainlist, "setmkbound", mk="0")
    dfloor = ET.SubElement(mainlist, "drawbox", cmt="tank_floor")
    ET.SubElement(dfloor, "boxfill").text = "bottom"
    ET.SubElement(dfloor, "point", x="-0.20", y="-0.18", z="-0.15")
    ET.SubElement(dfloor, "size", x="5.00", y="0.36", z="0.15")
    ET.SubElement(dfloor, "layers", vdp="0,1,2")

    # Sidewalls (mk=30)
    ET.SubElement(mainlist, "setmkbound", mk="30")
    dleft = ET.SubElement(mainlist, "drawbox", cmt="finite_sidewall_left")
    ET.SubElement(dleft, "boxfill").text = "solid"
    ET.SubElement(dleft, "point", x="-0.20", y="-0.18", z="-0.15")
    ET.SubElement(dleft, "size", x="5.00", y="0.03", z="0.95")
    ET.SubElement(dleft, "layers", vdp="0,1,2")

    dright = ET.SubElement(mainlist, "drawbox", cmt="finite_sidewall_right")
    ET.SubElement(dright, "boxfill").text = "solid"
    ET.SubElement(dright, "point", x="-0.20", y="0.15", z="-0.15")
    ET.SubElement(dright, "size", x="5.00", y="0.03", z="0.95")
    ET.SubElement(dright, "layers", vdp="0,1,2")

    # Moving piston (mk=10)
    ET.SubElement(mainlist, "setmkbound", mk="10")
    dpiston = ET.SubElement(mainlist, "drawbox", cmt="prescribed_piston")
    ET.SubElement(dpiston, "boxfill").text = "solid"
    ET.SubElement(dpiston, "point", x="-0.04", y="-0.15", z="0.00")
    ET.SubElement(dpiston, "size", x="0.04", y="0.30", z="0.75")
    ET.SubElement(dpiston, "layers", vdp="0,1,2")

    # Continuous bed profile STL reference
    ET.SubElement(mainlist, "setmkbound", mk="40")
    ET.SubElement(mainlist, "drawfilestl", file="assets/f5_compact_continuous_bed_profile.stl")
    ET.SubElement(mainlist, "shapeout", file="continuous_bed", reset="true")

    # For weir cases: submerged weir structure (mk=50)
    if mechanism == "weir":
        ET.SubElement(mainlist, "setmkbound", mk="50")
        weir_l = ET.SubElement(mainlist, "drawbox", cmt="weir_left_segment")
        ET.SubElement(weir_l, "boxfill").text = "solid"
        ET.SubElement(weir_l, "point", x="3.20", y="-0.15", z="0.336")
        ET.SubElement(weir_l, "size", x="0.15", y="0.11", z="0.124")
        ET.SubElement(weir_l, "layers", vdp="0,1,2")

        weir_r = ET.SubElement(mainlist, "drawbox", cmt="weir_right_segment")
        ET.SubElement(weir_r, "boxfill").text = "solid"
        ET.SubElement(weir_r, "point", x="3.20", y="0.04", z="0.336")
        ET.SubElement(weir_r, "size", x="0.15", y="0.11", z="0.124")
        ET.SubElement(weir_r, "layers", vdp="0,1,2")

        weir_n = ET.SubElement(mainlist, "drawbox", cmt="weir_notch_sill")
        ET.SubElement(weir_n, "boxfill").text = "solid"
        ET.SubElement(weir_n, "point", x="3.20", y="-0.04", z="0.336")
        ET.SubElement(weir_n, "size", x="0.15", y="0.08", z="0.074")
        ET.SubElement(weir_n, "layers", vdp="0,1,2")

    # Initial fluid block clipped above continuous bed
    ET.SubElement(mainlist, "setmkfluid", mk="0")

    # PATCHED CLIPPLANE: Plane through (2.00, 0, 0) with normal (0.28, 0, -1.00)
    # In GenCase (JClipShape::ClipPoint, 0x4f6a30), points with (p - pt).v > 0 are discarded.
    # Therefore v = (0.28, 0, -1.00) points downward into the bed, discarding z < 0.28*(x - 2)
    # and cleanly retaining all fluid with z >= 0.28*(x - 2) and upstream x in [0, 2].
    clipplane = ET.SubElement(mainlist, "clipplane", cmt="clip_fluid_above_continuous_bed_slope_patched_sign")
    ET.SubElement(clipplane, "point", x="2.00", y="0.00", z="0.00")
    ET.SubElement(clipplane, "vector", x="0.28", y="0.00", z="-1.00")

    dfluid = ET.SubElement(mainlist, "drawbox", cmt=f"initial_fluid_equilibrium_cell_centres_{res_key}")
    ET.SubElement(dfluid, "boxfill").text = "solid"
    ET.SubElement(dfluid, "point", **fluid_box["point"])
    ET.SubElement(dfluid, "size", **fluid_box["size"])

    # Reset clipplane after fluid generation
    ET.SubElement(mainlist, "clipreset")

    # Motion definition pinned to JMotion.cpp:708,814 (mvpredef is exact synonym of mvrectfile)
    motion = ET.SubElement(casedef, "motion")
    objreal = ET.SubElement(motion, "objreal", ref="10")
    ET.SubElement(objreal, "begin", mov="1", start="0.00", finish="16")
    mvpredef = ET.SubElement(objreal, "mvpredef", id="1", duration="16")
    ET.SubElement(
        mvpredef,
        "file",
        name="assets/f5_compact_packet_motion.dat",
        fields="2",
        fieldtime="0",
        fieldx="1",
    )

    # Execution configuration
    execution = ET.SubElement(root, "execution")
    special = ET.SubElement(execution, "special")
    gauges_el = ET.SubElement(special, "gauges")
    default_g = ET.SubElement(gauges_el, "default")
    ET.SubElement(default_g, "savevtkpart", value="true")
    # PATCHED GAUGES: Active canonical tags (no leading underscores)
    ET.SubElement(default_g, "computedt", value="0.02")
    ET.SubElement(default_g, "computetime", start="0", end="16")
    ET.SubElement(default_g, "output", value="true")
    ET.SubElement(default_g, "outputdt", value="0.02")
    ET.SubElement(default_g, "outputtime", start="0", end="16")

    # PATCHED SWL GAUGES: Only point0 and point2 are defined; superfluous point1 removed
    for g in GAUGES_SPEC:
        swl = ET.SubElement(gauges_el, "swl", name=g["name"])
        ET.SubElement(swl, "pointdp", coefdp=str(g["coefdp"]))
        ET.SubElement(
            swl,
            "point0",
            x=f"{g['x']:.17g}",
            y=f"{g['y']:.17g}",
            z=f"{g['point0_z']:.17g}",
        )
        ET.SubElement(
            swl,
            "point2",
            x=f"{g['x']:.17g}",
            y=f"{g['y']:.17g}",
            z=f"{g['point2_z']:.17g}",
        )

    # Parameters section with modern, clean keywords
    parameters = ET.SubElement(execution, "parameters")
    params = [
        ("SavePosDouble", "1"),
        ("StepAlgorithm", "2"),
        ("VerletSteps", "40"),
        ("Kernel", "2"),
        ("ViscoTreatment", "1"),
        ("Visco", "0.01"),
        ("ViscoBoundFactor", "1"),
        ("DensityDT", "2"),
        ("DensityDTvalue", "0.1"),
        ("Shifting", "0"),
        ("RigidAlgorithm", "1"),
        ("FtPause", "0.0"),
        ("CoefDtMin", "0.05"),
        ("DtIni", "0"),
        ("DtMin", "0"),
        ("DtFixed", "0"),
        ("DtAllParticles", "0"),
        ("TimeMax", "16.0"),
        ("TimeOut", "0.02"),
        ("RhopOutMin", "700"),
        ("RhopOutMax", "1300"),
    ]
    for k, v in params:
        ET.SubElement(parameters, "parameter", key=k, value=v)

    # Simulation domain (must not be accompanied by IncZ per JSph.cpp:846)
    simdom = ET.SubElement(parameters, "simulationdomain")
    ET.SubElement(simdom, "posmin", x="-0.30", y="-0.25", z="-0.25")
    ET.SubElement(simdom, "posmax", x="5.00", y="0.25", z="0.90")

    ET.SubElement(parameters, "parameter", key="Boundary", value="1")
    ET.SubElement(parameters, "parameter", key="MinFluidStop", value="0")

    indent_xml(root)
    xml_header = '<?xml version="1.0" encoding="UTF-8" ?>\n'
    return xml_header + ET.tostring(root, encoding="utf-8").decode("utf-8") + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate patched F5 compact equilibrium XML definitions.")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "definitions")
    args = parser.parse_args()

    out_dir = args.output_dir
    runup_dir = out_dir / "runup"
    weir_dir = out_dir / "weir"
    runup_dir.mkdir(parents=True, exist_ok=True)
    weir_dir.mkdir(parents=True, exist_ok=True)

    bed_pts, bed_tris = build_compact_bed_triangles()

    manifest: Dict[str, Any] = {}
    for mech, mdir in [("runup", runup_dir), ("weir", weir_dir)]:
        for res_key, res_cfg in RESOLUTIONS.items():
            dp_str = "DP0125" if res_key == "dp0125" else f"DP{int(round(res_cfg['dp_m']*1000)):03d}"
            case_name = f"F5_REF_{mech.upper()}_{dp_str}_EQUILIBRIUM_045_PATCHED"
            xml_text = generate_patched_case_xml(mech, res_key, bed_pts, bed_tris)
            xml_path = mdir / f"{case_name}.xml"
            with xml_path.open("w", encoding="utf-8") as f:
                f.write(xml_text)
            sha = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
            manifest[case_name] = {
                "file": str(xml_path),
                "mechanism": mech,
                "resolution": res_key,
                "dp_m": res_cfg["dp_m"],
                "sha256": sha,
            }
            print(f"Authored {xml_path.name} (SHA256: {sha[:16]}...)")

    manifest_path = out_dir / "patched_definitions_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"Authored manifest: {manifest_path}")


if __name__ == "__main__":
    main()
