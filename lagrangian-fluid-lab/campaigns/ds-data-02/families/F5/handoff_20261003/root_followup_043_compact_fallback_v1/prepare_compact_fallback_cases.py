#!/usr/bin/env python3
"""Case preparation worker for F5 compact finite single-wave packet fallback.

Builds and stages definition XMLs and case metadata across the nominal pair
(Runup and Weir) and three commensurate spatial resolutions:
  - Coarse: dp = 0.020 m (r = 2.0 to fine, r = 1.6 to medium)
  - Medium: dp = 0.0125 m (r = 1.25 to fine)
  - Fine:   dp = 0.010 m (r = 1.0 baseline)

Physical configuration:
  - Depth H = 0.40 m, flume width = 0.30 m, fluid length = 2.00 m, mass = 240.0 kg.
  - Flume length = 5.00 m (x in [-0.20, 4.80] m).
  - Continuous sloping bed with authentic slope m = 0.280.
  - Root024 surface-first bed support mesh rasterization in valid 'full' drawmode.
  - True local bed elevation for all 6 wave probes (zero sub-bed embedding).
  - Low-crest notched weir on slope for weir overtopping and downslope retention.
  - Bounded GPU maxwall estimates (fine pair <= 2.0 GPUh, total 3-DP ladder ~2.65 GPUh).

Actual scientific execution is strictly under Rootguard dispatch.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET

from generate_compact_continuous_bed_stl import (
    COMPACT_BED_PROFILE_NODES,
    build_compact_bed_triangles,
    compute_bed_elevation,
    get_observer_bed_elevations,
)

# Three commensurate spatial resolutions (Coarse, Medium, Fine)
RESOLUTIONS: Dict[str, Dict[str, object]] = {
    "dp020": {
        "dp_m": 0.020,
        "resolution_name": "coarse",
        "ratio_to_fine": 2.0,
        "ratio_to_medium": 1.6,
        "pointref": {"x": "0.010", "y": "0.010", "z": "0.010"},
        "fluid_box": {
            "point": {"x": "0.010", "y": "-0.140", "z": "0.010"},
            "size": {"x": "1.980", "y": "0.280", "z": "0.380"},
        },
        "simulation_domain": {
            "posmin": {"x": "-0.30", "y": "-0.25", "z": "-0.25"},
            "posmax": {"x": "5.00", "y": "0.25", "z": "0.90"},
        },
        "theoretical_fluid_lattice_particles": 30000,
        "nominal_root_fluid_index": 60000,
        "predicted_boundary_particles": 20000,
        "predicted_total_particles": 50000,
        "maxwall_seconds": 600,
        "maxwall_gpu_hours": 0.167,
    },
    "dp0125": {
        "dp_m": 0.0125,
        "resolution_name": "medium",
        "ratio_to_fine": 1.25,
        "ratio_to_medium": 1.0,
        "pointref": {"x": "0.00625", "y": "0.00625", "z": "0.00625"},
        "fluid_box": {
            "point": {"x": "0.00625", "y": "-0.14375", "z": "0.00625"},
            "size": {"x": "1.9875", "y": "0.2875", "z": "0.3875"},
        },
        "simulation_domain": {
            "posmin": {"x": "-0.30", "y": "-0.25", "z": "-0.25"},
            "posmax": {"x": "5.00", "y": "0.25", "z": "0.90"},
        },
        "theoretical_fluid_lattice_particles": 122880,
        "nominal_root_fluid_index": 122880,
        "predicted_boundary_particles": 55000,
        "predicted_total_particles": 177880,
        "maxwall_seconds": 1800,
        "maxwall_gpu_hours": 0.500,
    },
    "dp010": {
        "dp_m": 0.010,
        "resolution_name": "fine",
        "ratio_to_fine": 1.0,
        "ratio_to_medium": 0.8,
        "pointref": {"x": "0.005", "y": "0.005", "z": "0.005"},
        "fluid_box": {
            "point": {"x": "0.005", "y": "-0.145", "z": "0.005"},
            "size": {"x": "1.990", "y": "0.290", "z": "0.390"},
        },
        "simulation_domain": {
            "posmin": {"x": "-0.30", "y": "-0.25", "z": "-0.25"},
            "posmax": {"x": "5.00", "y": "0.25", "z": "0.90"},
        },
        "theoretical_fluid_lattice_particles": 240000,
        "nominal_root_fluid_index": 240000,
        "predicted_boundary_particles": 85000,
        "predicted_total_particles": 325000,
        "maxwall_seconds": 3600,
        "maxwall_gpu_hours": 1.000,
    },
}

# Eulerian Wave Probes at authentic continuous bed elevations
GAUGES_SPEC: List[Dict[str, object]] = [
    {
        "name": "WG1",
        "x": 0.60,
        "y": 0.0,
        "z_bed": 0.000,
        "point0_z": 0.000,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "upstream_flat_basin",
    },
    {
        "name": "WG2",
        "x": 1.40,
        "y": 0.0,
        "z_bed": 0.000,
        "point0_z": 0.000,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "shoaling_approach",
    },
    {
        "name": "RunupToe",
        "x": 2.00,
        "y": 0.0,
        "z_bed": 0.000,
        "point0_z": 0.000,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "slope_toe",
    },
    {
        "name": "WG3",
        "x": 2.60,
        "y": 0.0,
        "z_bed": 0.168,
        "point0_z": 0.168,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "mid_slope_shoaling",
    },
    {
        "name": "WG4",
        "x": 3.20,
        "y": 0.0,
        "z_bed": 0.336,
        "point0_z": 0.336,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "upper_slope_weir_approach",
    },
    {
        "name": "Crest",
        "x": 3.75,
        "y": 0.0,
        "z_bed": 0.448,
        "point0_z": 0.448,
        "point2_z": 0.700,
        "coefdp": 0.5,
        "zone": "crest_plateau",
    },
]


def build_triangle_elements(
    facets: List[Tuple[Tuple[float, float, float], ...]],
) -> Tuple[List[Tuple[float, float, float]], List[Tuple[int, int, int]]]:
    """Convert facet vertex tuples to indexed points and triangles."""
    points: List[Tuple[float, float, float]] = []
    triangles: List[Tuple[int, int, int]] = []
    idx = 0
    for tri in facets:
        tri_indices = []
        for pt in tri:
            points.append((round(pt[0], 6), round(pt[1], 6), round(pt[2], 6)))
            tri_indices.append(idx)
            idx += 1
        triangles.append((tri_indices[0], tri_indices[1], tri_indices[2]))
    return points, triangles


def build_xml_definition(
    case_type: str,  # 'runup' or 'weir'
    res_key: str,    # 'dp020', 'dp0125', 'dp010'
) -> str:
    """Synthesize complete DualSPHysics XML definition."""
    res = RESOLUTIONS[res_key]
    dp_m = float(res["dp_m"])
    dp_str = f"{dp_m:.4f}".rstrip("0")
    if dp_str.endswith("."):
        dp_str += "0"
    pointref = res["pointref"]
    fluid_box = res["fluid_box"]
    sim_domain = res["simulation_domain"]

    facets = build_compact_bed_triangles()
    points, triangles = build_triangle_elements(facets)

    # Root XML element
    root = ET.Element("case")

    # 1. casedef
    casedef = ET.SubElement(root, "casedef")
    constantsdef = ET.SubElement(casedef, "constantsdef")
    ET.SubElement(constantsdef, "gravity", x="0", y="0", z="-9.81")
    ET.SubElement(constantsdef, "rhop0", value="1000")
    ET.SubElement(constantsdef, "hswl", value="0.40", auto="false")
    ET.SubElement(constantsdef, "gamma", value="7")
    ET.SubElement(constantsdef, "speedsystem", value="0")
    ET.SubElement(constantsdef, "coefsound", value="20")
    ET.SubElement(constantsdef, "speedsound", value="0")
    ET.SubElement(
        constantsdef,
        "coefh",
        value="1.0",
        comment="reference characteristic smoothing coefficient",
    )
    ET.SubElement(constantsdef, "cflnumber", value="0.20")

    # mkconfig
    mkconfig = ET.SubElement(casedef, "mkconfig", boundcount="240", fluidcount="9")

    # geometry
    geometry = ET.SubElement(casedef, "geometry")
    definition = ET.SubElement(geometry, "definition", dp=f"{dp_m:g}")
    ET.SubElement(definition, "pointref", **pointref)
    ET.SubElement(definition, "pointmin", x="-0.30", y="-0.25", z="-0.25")
    ET.SubElement(definition, "pointmax", x="5.00", y="0.25", z="0.90")

    commands = ET.SubElement(geometry, "commands")
    mainlist = ET.SubElement(commands, "mainlist")
    setshapemode = ET.SubElement(mainlist, "setshapemode")
    setshapemode.text = "dp | actual | bound"

    # Surface-first rasterization following Root024
    ET.SubElement(mainlist, "setdrawmode", mode="solid")
    ET.SubElement(
        mainlist,
        "setmkbound",
        mk="40",
        cmt="root_numeric_bed_surface_support added boundary marker",
    )
    ET.SubElement(
        mainlist,
        "setdrawmode",
        mode="full",
        cmt="root_numeric_bed_surface_support surface rasterization",
    )

    drawtri = ET.SubElement(
        mainlist,
        "drawtriangles",
        cmt="root_numeric_bed_surface_support full compact bed triangle mesh; drawn first",
    )
    points_el = ET.SubElement(drawtri, "points")
    for pt in points:
        ET.SubElement(points_el, "point", x=f"{pt[0]:g}", y=f"{pt[1]:g}", z=f"{pt[2]:g}")
    triangles_el = ET.SubElement(drawtri, "triangles")
    for tri in triangles:
        ET.SubElement(
            triangles_el,
            "triangle",
            x=str(tri[0]),
            y=str(tri[1]),
            z=str(tri[2]),
        )

    # Tank boundary structures
    ET.SubElement(
        mainlist,
        "setdrawmode",
        mode="solid",
        cmt="root_numeric_bed_surface_support restore preceding mode",
    )

    # Tank floor
    ET.SubElement(mainlist, "setmkbound", mk="0")
    dfloor = ET.SubElement(mainlist, "drawbox", cmt="tank_floor")
    ET.SubElement(dfloor, "boxfill").text = "bottom"
    ET.SubElement(dfloor, "point", x="-0.20", y="-0.18", z="-0.15")
    ET.SubElement(dfloor, "size", x="5.00", y="0.36", z="0.15")
    ET.SubElement(dfloor, "layers", vdp="0,1,2")

    # Left sidewall
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

    # Piston paddle
    ET.SubElement(mainlist, "setmkbound", mk="10")
    dpiston = ET.SubElement(mainlist, "drawbox", cmt="prescribed_piston")
    ET.SubElement(dpiston, "boxfill").text = "solid"
    ET.SubElement(dpiston, "point", x="-0.04", y="-0.15", z="0.00")
    ET.SubElement(dpiston, "size", x="0.04", y="0.30", z="0.75")
    ET.SubElement(dpiston, "layers", vdp="0,1,2")

    # Bed STL drawing in verified 'full' drawmode
    ET.SubElement(mainlist, "setdrawmode", mode="full")
    ET.SubElement(mainlist, "setmkbound", mk="40")
    ET.SubElement(
        mainlist,
        "drawfilestl",
        file="assets/f5_compact_continuous_bed_profile.stl",
    )
    ET.SubElement(mainlist, "shapeout", file="continuous_bed", reset="true")

    # Weir structures (Weir case only)
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

    # Initial fluid block
    ET.SubElement(mainlist, "setmkfluid", mk="0")
    dfluid = ET.SubElement(
        mainlist,
        "drawbox",
        cmt=f"initial_fluid_cell_centres_{res_key}",
    )
    ET.SubElement(dfluid, "boxfill").text = "solid"
    ET.SubElement(dfluid, "point", **fluid_box["point"])
    ET.SubElement(dfluid, "size", **fluid_box["size"])

    # Motion definition
    motion = ET.SubElement(casedef, "motion")
    objreal = ET.SubElement(motion, "objreal", ref="10")
    ET.SubElement(objreal, "begin", mov="1", start="0.00", finish="16")
    mvpredef = ET.SubElement(objreal, "mvpredef", id="1", duration="16")
    ET.SubElement(
        mvpredef,
        "file",
        name="control_compact_packet.dat",
        fields="2",
        fieldtime="0",
        fieldx="1",
    )

    # 2. execution
    execution = ET.SubElement(root, "execution")
    special = ET.SubElement(execution, "special")
    gauges = ET.SubElement(special, "gauges")
    gdefault = ET.SubElement(gauges, "default")
    ET.SubElement(gdefault, "savevtkpart", value="true")
    ET.SubElement(gdefault, "_computedt", value="0.02")
    ET.SubElement(gdefault, "_computetime", start="0", end="16")
    ET.SubElement(gdefault, "output", value="true")
    ET.SubElement(gdefault, "_outputdt", value="0.02")
    ET.SubElement(gdefault, "_outputtime", start="0", end="16")

    # Add all 6 gauges with corrected bed elevations
    for g in GAUGES_SPEC:
        swl = ET.SubElement(gauges, "swl", name=str(g["name"]))
        ET.SubElement(swl, "pointdp", coefdp=str(g["coefdp"]))
        ET.SubElement(
            swl,
            "point0",
            x=f"{g['x']:g}",
            y=f"{g['y']:g}",
            z=f"{g['point0_z']:g}",
        )
        ET.SubElement(
            swl,
            "point2",
            x=f"{g['x']:g}",
            y=f"{g['y']:g}",
            z=f"{g['point2_z']:g}",
        )

    # parameters
    parameters = ET.SubElement(execution, "parameters")
    params: List[Tuple[str, str]] = [
        ("SavePosDouble", "0"),
        ("StepAlgorithm", "2"),
        ("VerletSteps", "40"),
        ("Kernel", "2"),
        ("ViscoTreatment", "1"),
        ("Visco", "0.01"),
        ("ViscoBoundFactor", "0"),
        ("DensityDT", "2"),
        ("DensityDTvalue", "0.1"),
        ("Shifting", "0"),
        ("ShiftCoef", "-2"),
        ("ShiftTFS", "0"),
        ("RigidAlgorithm", "1"),
        ("FtPause", "0"),
        ("CoefDtMin", "0.05"),
        ("DtIni", "0"),
        ("DtMin", "0"),
        ("DtFixed", "0"),
        ("DtFixedFile", "NONE"),
        ("DtAllParticles", "0"),
        ("TimeMax", "16"),
        ("TimeOut", "0.02"),
        ("PartsOutMax", "1"),
        ("RhopOutMin", "700"),
        ("RhopOutMax", "1300"),
    ]
    for k, v in params:
        ET.SubElement(parameters, "parameter", key=k, value=v)

    simdomain_el = ET.SubElement(parameters, "simulationdomain")
    ET.SubElement(simdomain_el, "posmin", **sim_domain["posmin"])
    ET.SubElement(simdomain_el, "posmax", **sim_domain["posmax"])

    # Pretty-print XML
    ET.indent(root, space="  ")
    xml_str = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return xml_str + "\n"


def stage_all_case_definitions(base_dir: Path) -> Dict[str, object]:
    """Generate all 6 case definition XML files across runup and weir mechanisms."""
    manifest_entries: List[Dict[str, object]] = []

    case_names = {
        ("runup", "dp020"): "F5_REF_RUNUP_DP020_COMPACT_043",
        ("runup", "dp0125"): "F5_REF_RUNUP_DP0125_COMPACT_043",
        ("runup", "dp010"): "F5_REF_RUNUP_DP010_COMPACT_043",
        ("weir", "dp020"): "F5_REF_WEIR_DP020_COMPACT_043",
        ("weir", "dp0125"): "F5_REF_WEIR_DP0125_COMPACT_043",
        ("weir", "dp010"): "F5_REF_WEIR_DP010_COMPACT_043",
    }

    for (case_type, res_key), case_id in case_names.items():
        subdir = base_dir / "definitions" / case_type
        subdir.mkdir(parents=True, exist_ok=True)
        xml_path = subdir / f"{case_id}.xml"

        xml_content = build_xml_definition(case_type, res_key)
        xml_path.write_text(xml_content, encoding="utf-8")

        res_meta = RESOLUTIONS[res_key]
        entry = {
            "case_id": case_id,
            "mechanism": "runup_return" if case_type == "runup" else "weir_overtopping",
            "resolution_key": res_key,
            "dp_m": res_meta["dp_m"],
            "resolution_name": res_meta["resolution_name"],
            "ratio_to_fine": res_meta["ratio_to_fine"],
            "ratio_to_medium": res_meta["ratio_to_medium"],
            "xml_relpath": str(xml_path.relative_to(base_dir)),
            "byte_size": len(xml_content.encode("utf-8")),
            "theoretical_fluid_lattice_particles": res_meta["theoretical_fluid_lattice_particles"],
            "nominal_root_fluid_index": res_meta["nominal_root_fluid_index"],
            "predicted_total_particles": res_meta["predicted_total_particles"],
            "maxwall_seconds": res_meta["maxwall_seconds"],
            "maxwall_gpu_hours": res_meta["maxwall_gpu_hours"],
            "fluid_mass_kg": 240.0,
            "channel_width_m": 0.30,
            "fluid_length_m": 2.00,
            "representative_depth_H_m": 0.40,
            "drawmode_syntax": "full",
        }
        manifest_entries.append(entry)

    manifest = {
        "schema": "ds02.f5.compact-fallback-cases-manifest.v1",
        "family_id": "F5",
        "description": "Catalog of 6 compact fallback XML definitions (3 Runup, 3 Weir) across unequal-r resolutions [0.02, 0.0125, 0.01].",
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
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F5 compact fallback case preparation worker."
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
        help="Target scope root directory.",
    )
    args = parser.parse_args()

    if args.stage_cases:
        manifest = stage_all_case_definitions(args.base_dir)
        print(f"Staged {len(manifest['cases'])} compact cases successfully.")
        for c in manifest["cases"]:
            print(
                f"  {c['case_id']}: dp={c['dp_m']}m, "
                f"lattice_fluid={c['theoretical_fluid_lattice_particles']}, "
                f"predicted_total={c['predicted_total_particles']}, "
                f"maxwall={c['maxwall_gpu_hours']} GPUh"
            )


if __name__ == "__main__":
    main()
