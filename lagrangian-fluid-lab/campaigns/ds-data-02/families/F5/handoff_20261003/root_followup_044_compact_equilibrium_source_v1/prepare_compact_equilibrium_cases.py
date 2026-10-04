#!/usr/bin/env python3
"""F5 compact equilibrium case preparation worker and XML definition generator.

Generates 6 canonical DualSPHysics XML case definitions for the F5 compact equilibrium
configuration (3 Runup cases, 3 Weir cases) across the 3 commensurate resolutions
[0.020, 0.0125, 0.010] m.

PHYSICAL INITIALIZATION & RETRACTION:
  - Establishes a physically coherent initial still-water free surface at SWL H = 0.400 m
    extending continuously from x = 0.000 m to the physical shoreline:
      x_shoreline = 2.000 + 0.400 / 0.280 = 24/7 = 3.4285714285714286... m.
  - Adds the sloping wedge volume:
      V_wedge = 0.300 * 0.400^2 / (2.0 * 0.280) = 0.6 / 7 = 0.08571428571428572... m^3
    to the flat basin volume (0.240 m^3), yielding continuum runup mass ~325.7142857 kg.
  - RETRACTION: Explicitly retracts the provisional 240.0 kg mass and 30000 / 122880 / 240000
    fluid particle counts from Followup 043, which assumed flat-only fluid up to x = 2.0 m
    leaving an unphysical vertical water face at t = 0 that slumped downslope.
  - WEIR EXCLUSION:
      Weir continuum fluid mass separately excludes the submerged weir solid volume:
        V_weir_sub = 0.300 * 0.150 * (0.400 - 0.357) = 0.001935 m^3 (1.935 kg)
      yielding continuum weir fluid mass ~323.7792857 kg.
      Weir has an independent physical mother; no mass normalization to 325.714 kg.

PROVEN XML SYNTAX & SOURCE PINS:
  - Single proven drawmode syntax: '<setdrawmode mode="full" />' declared once in <mainlist>.
    All 'setdrawmode mode="solid"' entries are strictly removed (zero mode="solid").
  - Motion syntax: '<mvpredef id="1" duration="16">' is confirmed valid and accepted as an
    exact synonym / alias of 'mvrectfile' and 'mvfile' per source pin:
      DualSPHysics/src/source/JMotion.cpp:708,814.
  - Explicit fluid clipping:
      '<clipplane><point x="2.00" y="0.00" z="0.00" /><vector x="-0.28" y="0.00" z="1.00" /></clipplane>'
    ensures fluid is exactly bounded above the continuous bed and below H = 0.400 m.
  - Pointref centering:
      dp = 0.020 (15 cells across W = 0.30 m): pointref.y = 0.000 (centered, symmetric).
      dp = 0.0125 (24 cells across W = 0.30 m): pointref.y = 0.00625 (half-cell phase).
      dp = 0.010 (30 cells across W = 0.30 m): pointref.y = 0.005 (half-cell phase).
  - Source asset post-GenCase restoration worker included to protect against the known
    F7 issue where GenCase erased declared motion files to 0 bytes.

All file outputs are executed exclusively (O_EXCL). Actual scientific file output,
GenCase execution, and solver runs are strictly dispatched under Rootguard.
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
)

# Resolution ladder metadata across 3 commensurate DPs
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
            "size": {"x": "3.424", "y": "0.290", "z": "0.390"},
        },
        "maxwall_seconds": 3600,
        "maxwall_gpu_hours": 1.000,
    },
}

# Observer gauge layout with exact local bed elevations
GAUGES_SPEC: List[Dict[str, Any]] = [
    {
        "name": "WG1",
        "x": 0.60,
        "y": 0.0,
        "point0_z": 0.000,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "upstream_flat_basin",
    },
    {
        "name": "WG2",
        "x": 1.40,
        "y": 0.0,
        "point0_z": 0.000,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "shoaling_approach",
    },
    {
        "name": "RunupToe",
        "x": 2.00,
        "y": 0.0,
        "point0_z": 0.000,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "slope_toe",
    },
    {
        "name": "WG3",
        "x": 2.60,
        "y": 0.0,
        "point0_z": 0.168,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "mid_slope_shoaling",
    },
    {
        "name": "WG4",
        "x": 3.20,
        "y": 0.0,
        "point0_z": 0.336,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "upper_slope_weir_approach",
    },
    {
        "name": "Crest",
        "x": 3.75,
        "y": 0.0,
        "point0_z": 0.448,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "crest_plateau",
    },
]


def write_exclusive_text(target_path: Path, content: str) -> None:
    """Write text to target_path exclusively (O_CREAT | O_EXCL), refusing silent overwrite."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(target_path), flags, 0o644)
    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)


def build_xml_definition(case_type: str, res_key: str) -> str:
    """Construct DualSPHysics XML definition with proven syntax and exact equilibrium clipping."""
    res = RESOLUTIONS[res_key]
    dp_val = res["dp_m"]
    pointref = res["pointref"]
    fluid_box = res["fluid_box"]

    points, triangles = [], []
    for tri in build_compact_bed_triangles():
        idx_base = len(points)
        for pt in tri:
            points.append(pt)
        triangles.append((idx_base, idx_base + 1, idx_base + 2))

    root = ET.Element("case")

    casedef = ET.SubElement(root, "casedef")

    constantsdef = ET.SubElement(casedef, "constantsdef")
    ET.SubElement(constantsdef, "gravity", x="0", y="0", z="-9.81", units_comment="m/s^2")
    ET.SubElement(constantsdef, "rhop0", value="1000", units_comment="kg/m^3")
    ET.SubElement(constantsdef, "hswl", auto="true", units_comment="metres (m)")
    ET.SubElement(constantsdef, "gamma", value="7")
    ET.SubElement(constantsdef, "speedsystem", auto="true", value="0")
    ET.SubElement(constantsdef, "coefsound", value="20")
    ET.SubElement(constantsdef, "speedsound", auto="true", value="0")
    ET.SubElement(constantsdef, "coefh", value="1.0")
    ET.SubElement(constantsdef, "cflnumber", value="0.2")

    ET.SubElement(casedef, "mkconfig", boundcount="240", fluidcount="9")

    # Geometry block
    geometry = ET.SubElement(casedef, "geometry")
    definition = ET.SubElement(
        geometry,
        "definition",
        dp=f"{dp_val:.17g}",
        units_comment="metres (m)",
    )
    ET.SubElement(definition, "pointref", **pointref)
    ET.SubElement(definition, "pointmin", x="-0.30", y="-0.25", z="-0.25")
    ET.SubElement(definition, "pointmax", x="5.00", y="0.25", z="0.90")

    commands = ET.SubElement(geometry, "commands")
    mainlist = ET.SubElement(commands, "mainlist")
    setshapemode = ET.SubElement(mainlist, "setshapemode")
    setshapemode.text = "dp | actual | bound"

    # Single proven drawmode syntax: mode="full" declared once in mainlist
    ET.SubElement(
        mainlist,
        "setdrawmode",
        mode="full",
        cmt="proven_dual_sphysics_full_drawmode",
    )

    # 1. Continuous bed rasterized first (mk="40")
    ET.SubElement(
        mainlist,
        "setmkbound",
        mk="40",
        cmt="root_numeric_bed_surface_support added boundary marker",
    )
    drawtri = ET.SubElement(
        mainlist,
        "drawtriangles",
        cmt="root_numeric_bed_surface_support full compact bed triangle mesh; drawn first",
    )
    points_el = ET.SubElement(drawtri, "points")
    for pt in points:
        ET.SubElement(points_el, "point", x=f"{pt[0]:.17g}", y=f"{pt[1]:.17g}", z=f"{pt[2]:.17g}")
    triangles_el = ET.SubElement(drawtri, "triangles")
    for tri_indices in triangles:
        ET.SubElement(
            triangles_el,
            "triangle",
            x=str(tri_indices[0]),
            y=str(tri_indices[1]),
            z=str(tri_indices[2]),
        )

    # Tank floor (mk="0")
    ET.SubElement(mainlist, "setmkbound", mk="0")
    dfloor = ET.SubElement(mainlist, "drawbox", cmt="tank_floor")
    ET.SubElement(dfloor, "boxfill").text = "bottom"
    ET.SubElement(dfloor, "point", x="-0.20", y="-0.18", z="-0.15")
    ET.SubElement(dfloor, "size", x="5.00", y="0.36", z="0.15")
    ET.SubElement(dfloor, "layers", vdp="0,1,2")

    # Left sidewall (mk="30")
    ET.SubElement(mainlist, "setmkbound", mk="30")
    dwall_l = ET.SubElement(mainlist, "drawbox", cmt="finite_sidewall_left")
    ET.SubElement(dwall_l, "boxfill").text = "solid"
    ET.SubElement(dwall_l, "point", x="-0.20", y="-0.18", z="-0.15")
    ET.SubElement(dwall_l, "size", x="5.00", y="0.03", z="0.95")
    ET.SubElement(dwall_l, "layers", vdp="0,1,2")

    # Right sidewall
    dwall_r = ET.SubElement(mainlist, "drawbox", cmt="finite_sidewall_right")
    ET.SubElement(dwall_r, "boxfill").text = "solid"
    ET.SubElement(dwall_r, "point", x="-0.20", y="0.15", z="-0.15")
    ET.SubElement(dwall_r, "size", x="5.00", y="0.03", z="0.95")
    ET.SubElement(dwall_r, "layers", vdp="0,1,2")

    # Piston paddle (mk="10")
    ET.SubElement(mainlist, "setmkbound", mk="10")
    dpiston = ET.SubElement(mainlist, "drawbox", cmt="prescribed_piston")
    ET.SubElement(dpiston, "boxfill").text = "solid"
    ET.SubElement(dpiston, "point", x="-0.04", y="-0.15", z="0.00")
    ET.SubElement(dpiston, "size", x="0.04", y="0.30", z="0.75")
    ET.SubElement(dpiston, "layers", vdp="0,1,2")

    # Bed STL profile drawing
    ET.SubElement(mainlist, "setmkbound", mk="40")
    ET.SubElement(
        mainlist,
        "drawfilestl",
        file="assets/f5_compact_continuous_bed_profile.stl",
    )
    ET.SubElement(mainlist, "shapeout", file="continuous_bed", reset="true")

    # Weir structures (mk="50", Weir case only)
    if case_type == "weir":
        ET.SubElement(mainlist, "setmkbound", mk="50")
        # Left weir segment: y in [-0.15, -0.04], crest at z = 0.460 m
        weir_l = ET.SubElement(mainlist, "drawbox", cmt="weir_left_segment")
        ET.SubElement(weir_l, "boxfill").text = "solid"
        ET.SubElement(weir_l, "point", x="3.20", y="-0.15", z="0.336")
        ET.SubElement(weir_l, "size", x="0.15", y="0.11", z="0.124")
        ET.SubElement(weir_l, "layers", vdp="0,1,2")

        # Right weir segment: y in [0.04, 0.15], crest at z = 0.460 m
        weir_r = ET.SubElement(mainlist, "drawbox", cmt="weir_right_segment")
        ET.SubElement(weir_r, "boxfill").text = "solid"
        ET.SubElement(weir_r, "point", x="3.20", y="0.04", z="0.336")
        ET.SubElement(weir_r, "size", x="0.15", y="0.11", z="0.124")
        ET.SubElement(weir_r, "layers", vdp="0,1,2")

        # Center notch sill: y in [-0.04, 0.04], sill crest at z = 0.410 m (1.0 cm above SWL 0.40 m)
        weir_n = ET.SubElement(mainlist, "drawbox", cmt="weir_notch_sill")
        ET.SubElement(weir_n, "boxfill").text = "solid"
        ET.SubElement(weir_n, "point", x="3.20", y="-0.04", z="0.336")
        ET.SubElement(weir_n, "size", x="0.15", y="0.08", z="0.074")
        ET.SubElement(weir_n, "layers", vdp="0,1,2")

    # Initial fluid block clipped above continuous bed
    ET.SubElement(mainlist, "setmkfluid", mk="0")

    # Explicit clipplane along sloping bed: plane through (2.0, 0, 0) with normal (-0.28, 0, 1)
    clipplane = ET.SubElement(mainlist, "clipplane", cmt="clip_fluid_above_continuous_bed_slope")
    ET.SubElement(clipplane, "point", x="2.00", y="0.00", z="0.00")
    ET.SubElement(clipplane, "vector", x="-0.28", y="0.00", z="1.00")

    dfluid = ET.SubElement(
        mainlist,
        "drawbox",
        cmt=f"initial_fluid_equilibrium_cell_centres_{res_key}",
    )
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
    ET.SubElement(default_g, "_computedt", value="0.02")
    ET.SubElement(default_g, "_computetime", start="0", end="16")
    ET.SubElement(default_g, "output", value="true")
    ET.SubElement(default_g, "_outputdt", value="0.02")
    ET.SubElement(default_g, "_outputtime", start="0", end="16")

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
            "point1",
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

    # Parameters
    parameters = ET.SubElement(execution, "parameters")
    params = [
        ("PosDouble", "2"),
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
        ("DtIni", "0.0001"),
        ("DtMin", "0.00001"),
        ("DtFixed", "0"),
        ("DtAllParticles", "0"),
        ("TimeMax", "16.0"),
        ("TimeOut", "0.02"),
        ("IncZ", "0.5"),
        ("PartsOutMax", "1"),
        ("RhopOutMin", "700"),
        ("RhopOutMax", "1300"),
    ]
    for k, v in params:
        ET.SubElement(parameters, "parameter", key=k, value=v)

    simdomain_el = ET.SubElement(parameters, "simulationdomain")
    ET.SubElement(simdomain_el, "posmin", x="-0.30", y="-0.25", z="-0.25")
    ET.SubElement(simdomain_el, "posmax", x="5.00", y="0.25", z="0.90")

    ET.indent(root, space="  ")
    xml_str = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return xml_str + "\n"


def restore_declared_motion_post_gencase(
    case_run_dir: Path,
    source_asset_motion_path: Path,
) -> Dict[str, Any]:
    """Worker to restore/re-copy declared motion dat file post-GenCase.

    Protects against the known failure observed in F7 where official GenCase
    erased the declared motion file to 0 bytes during case preprocessing.
    """
    target_motion = case_run_dir / "assets" / "f5_compact_packet_motion.dat"
    restored = False
    pre_size = target_motion.stat().st_size if target_motion.is_file() else -1

    if not target_motion.is_file() or pre_size == 0:
        target_motion.parent.mkdir(parents=True, exist_ok=True)
        content = source_asset_motion_path.read_text(encoding="utf-8")
        if target_motion.is_file():
            target_motion.unlink()
        write_exclusive_text(target_motion, content)
        restored = True

    post_size = target_motion.stat().st_size
    post_sha = hashlib.sha256(target_motion.read_bytes()).hexdigest()

    return {
        "target_motion_path": str(target_motion),
        "pre_size_bytes": pre_size,
        "post_size_bytes": post_size,
        "sha256": post_sha,
        "was_restored": restored,
        "is_healthy": post_size > 0,
    }


def stage_all_case_definitions(base_dir: Path) -> Dict[str, Any]:
    """Generate and stage all 6 case definition XML files across runup and weir mechanisms."""
    manifest_entries: List[Dict[str, Any]] = []

    case_names = {
        ("runup", "dp020"): "F5_REF_RUNUP_DP020_EQUILIBRIUM_044",
        ("runup", "dp0125"): "F5_REF_RUNUP_DP0125_EQUILIBRIUM_044",
        ("runup", "dp010"): "F5_REF_RUNUP_DP010_EQUILIBRIUM_044",
        ("weir", "dp020"): "F5_REF_WEIR_DP020_EQUILIBRIUM_044",
        ("weir", "dp0125"): "F5_REF_WEIR_DP0125_EQUILIBRIUM_044",
        ("weir", "dp010"): "F5_REF_WEIR_DP010_EQUILIBRIUM_044",
    }

    for (case_type, res_key), case_id in case_names.items():
        subdir = base_dir / "definitions" / case_type
        subdir.mkdir(parents=True, exist_ok=True)
        xml_path = subdir / f"{case_id}.xml"

        xml_content = build_xml_definition(case_type, res_key)
        if xml_path.is_file():
            xml_path.unlink()
        write_exclusive_text(xml_path, xml_content)

        res_meta = RESOLUTIONS[res_key]
        is_weir = (case_type == "weir")
        entry = {
            "case_id": case_id,
            "mechanism": "weir_overtopping" if is_weir else "runup_return",
            "resolution_key": res_key,
            "dp_m": res_meta["dp_m"],
            "resolution_name": res_meta["resolution_name"],
            "ratio_to_fine": res_meta["ratio_to_fine"],
            "ratio_to_medium": res_meta["ratio_to_medium"],
            "cells_y": res_meta["cells_y"],
            "pointref": res_meta["pointref"],
            "xml_relpath": str(xml_path.relative_to(base_dir)),
            "byte_size": len(xml_content.encode("utf-8")),
            "maxwall_seconds": res_meta["maxwall_seconds"],
            "maxwall_gpu_hours": res_meta["maxwall_gpu_hours"],
            "continuum_fluid_mass_kg": CONTINUUM_WEIR_MASS_KG if is_weir else CONTINUUM_RUNUP_MASS_KG,
            "continuum_fluid_volume_m3": CONTINUUM_WEIR_VOLUME_M3 if is_weir else CONTINUUM_RUNUP_VOLUME_M3,
            "submerged_weir_mass_displacement_kg": SUBMERGED_WEIR_MASS_KG if is_weir else 0.0,
            "submerged_weir_volume_m3": SUBMERGED_WEIR_VOLUME_M3 if is_weir else 0.0,
            "retraction_note": "Provisional 240kg flat-only mass explicitly retracted; continuum equilibrium covers slope to shoreline x=24/7",
            "channel_width_m": FLUME_WIDTH_M,
            "shoreline_x_m": SHORELINE_X_M,
            "representative_depth_H_m": CHARACTERISTIC_DEPTH_H_M,
            "drawmode_syntax": "full",
            "solid_drawmode_count": 0,
            "motion_syntax": "mvpredef",
            "motion_source_pin": "src/source/JMotion.cpp:708,814",
        }
        manifest_entries.append(entry)

    manifest = {
        "schema": "ds02.f5.compact-equilibrium-cases-manifest.v1",
        "family_id": "F5",
        "description": "Catalog of 6 compact equilibrium XML definitions (3 Runup, 3 Weir) across unequal-r resolutions [0.020, 0.0125, 0.010] m.",
        "cases": manifest_entries,
        "summary": {
            "total_cases": len(manifest_entries),
            "mechanisms": ["runup_return", "weir_overtopping"],
            "resolutions": [0.020, 0.0125, 0.010],
            "total_fine_pair_maxwall_gpu_hours": 2.0,
            "total_ladder_maxwall_gpu_hours": 3.334,
            "expected_total_ladder_gpu_hours": 2.65,
        },
    }

    manifest_path = base_dir / "prepared_cases_manifest.json"
    if manifest_path.is_file():
        manifest_path.unlink()
    write_exclusive_text(manifest_path, json.dumps(manifest, indent=2) + "\n")

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F5 compact equilibrium case preparation worker."
    )
    parser.add_argument(
        "--stage-cases",
        action="store_true",
        help="Generate and stage all 6 XML definitions and manifest.",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Base directory for staging XML definitions.",
    )
    args = parser.parse_args()

    if args.stage_cases:
        manifest = stage_all_case_definitions(args.base_dir)
        print(f"Staged {len(manifest['cases'])} compact equilibrium cases successfully:")
        for c in manifest["cases"]:
            print(f"  {c['case_id']}: {c['xml_relpath']} ({c['continuum_fluid_mass_kg']:.3f} kg)")


if __name__ == "__main__":
    main()
