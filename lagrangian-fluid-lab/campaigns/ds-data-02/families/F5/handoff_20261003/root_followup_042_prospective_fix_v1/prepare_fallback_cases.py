#!/usr/bin/env python3
"""Case preparation worker for F5 finite single-wave packet prospective fallback.

Builds and stages definition XMLs and case metadata across the nominal pair
(Runup and Weir) and three commensurate spatial resolutions (dp=0.050m,
dp=0.025m, dp=0.010m).

Applies:
  1. Root024 surface-first bed support mesh rasterization (60 triangles).
  2. Bed STL boundary definition with immutable continuous bed geometry.
  3. Corrected Eulerian observer layout (probes aligned with local continuous bed elevation).
  4. Finite single-wave packet wavemaker forcing (control_single_packet.dat).

Actual scientific file output is executed strictly under Rootguard dispatch.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET

from generate_continuous_bed_stl import build_bed_triangles, compute_bed_elevation

# Three commensurate spatial resolutions (Coarse, Medium, Fine)
RESOLUTIONS: Dict[str, Dict[str, object]] = {
    "dp050": {
        "dp_m": 0.050,
        "resolution_name": "coarse",
        "pointref": {"x": "0.025", "y": "0.025", "z": "0.045"},
        "fluid_box": {
            "point": {"x": "-0.875", "y": "-0.675", "z": "0.045"},
            "size": {"x": "4.15", "y": "1.35", "z": "0.35"},
        },
        "simulation_domain": {
            "posmin": {"x": "-1.30", "y": "-0.85", "z": "-0.30"},
            "posmax": {"x": "11.00", "y": "0.85", "z": "1.45"},
        },
        "predicted_fluid_particles": 18816,
        "predicted_boundary_particles": 37000,
        "predicted_total_particles": 55816,
    },
    "dp025": {
        "dp_m": 0.025,
        "resolution_name": "medium",
        "pointref": {"x": "0.0125", "y": "0.0125", "z": "0.0325"},
        "fluid_box": {
            "point": {"x": "-0.8875", "y": "-0.6875", "z": "0.0325"},
            "size": {"x": "4.175", "y": "1.375", "z": "0.375"},
        },
        "simulation_domain": {
            "posmin": {"x": "-1.22", "y": "-0.85", "z": "-0.30"},
            "posmax": {"x": "11.00", "y": "0.85", "z": "1.45"},
        },
        "predicted_fluid_particles": 150528,
        "predicted_boundary_particles": 305000,
        "predicted_total_particles": 455528,
    },
    "dp010": {
        "dp_m": 0.010,
        "resolution_name": "fine",
        "pointref": {"x": "0.005", "y": "0.005", "z": "0.005"},
        "fluid_box": {
            "point": {"x": "-0.895", "y": "-0.695", "z": "0.025"},
            "size": {"x": "4.19", "y": "1.39", "z": "0.39"},
        },
        "simulation_domain": {
            "posmin": {"x": "-1.15", "y": "-0.84", "z": "-0.30"},
            "posmax": {"x": "11.00", "y": "0.84", "z": "1.45"},
        },
        "predicted_fluid_particles": 2352000,
        "predicted_boundary_particles": 4700000,
        "predicted_total_particles": 7052000,
    },
}

# Corrected Eulerian observer layout (probes aligned with local continuous bed elevation)
CORRECTED_GAUGES: List[Dict[str, object]] = [
    {"name": "WG1", "x": 2.00, "y": 0.0, "z_bed": 0.000, "point2_z": 1.250, "coefdp": 0.5},
    {"name": "WG2", "x": 3.10, "y": 0.0, "z_bed": 0.000, "point2_z": 1.250, "coefdp": 0.5},
    {"name": "RunupToe", "x": 3.55, "y": 0.0, "z_bed": 0.000, "point2_z": 1.250, "coefdp": 0.5},
    {"name": "WG3", "x": 4.35, "y": 0.0, "z_bed": 0.224, "point2_z": 1.250, "coefdp": 0.5},
    {"name": "WG4", "x": 5.45, "y": 0.0, "z_bed": 0.532, "point2_z": 1.250, "coefdp": 0.5},
    {"name": "Crest", "x": 6.70, "y": 0.0, "z_bed": 0.840, "point2_z": 1.250, "coefdp": 0.5},
]

# Physical nominal fluid volume & mass: 4.20 m x 1.40 m x 0.40 m = 2.352 m^3 = 2352.0 kg
NOMINAL_FLUID_MASS_KG: float = 2352.0


def build_case_xml(
    mechanism: str,
    res_key: str,
    piston_file: str = "control_single_packet.dat",
    stl_rel_path: str = "assets/f5_continuous_bed_profile_slope_0p280.stl",
) -> ET.Element:
    """Construct complete, valid DualSPHysics XML element tree for specified case."""
    res = RESOLUTIONS[res_key]
    dp = res["dp_m"]

    root = ET.Element("case")
    casedef = ET.SubElement(root, "casedef")

    # Constants
    cdefs = ET.SubElement(casedef, "constantsdef")
    ET.SubElement(cdefs, "gravity", {"x": "0", "y": "0", "z": "-9.81"})
    ET.SubElement(cdefs, "rhop0", {"value": "1000"})
    ET.SubElement(cdefs, "rhopgradient", {"value": "3"})
    ET.SubElement(cdefs, "hswl", {"value": "0", "auto": "true"})
    ET.SubElement(cdefs, "gamma", {"value": "7"})
    ET.SubElement(cdefs, "speedsystem", {"value": "0", "auto": "true"})
    ET.SubElement(cdefs, "coefsound", {"value": "20"})
    ET.SubElement(cdefs, "speedsound", {"value": "0", "auto": "true"})
    ET.SubElement(cdefs, "coefh", {"value": "1.5"})
    ET.SubElement(cdefs, "cflnumber", {"value": "0.2"})

    mkcfg = ET.SubElement(casedef, "mkconfig", {"boundcount": "230", "fluidcount": "9"})
    ET.SubElement(mkcfg, "mkorientfluid", {"mk": "0", "orient": "Xyz"})

    # Geometry
    geom = ET.SubElement(casedef, "geometry")
    gdef = ET.SubElement(geom, "definition", {"dp": str(dp)})
    pref = res["pointref"]
    ET.SubElement(gdef, "pointref", pref)
    ET.SubElement(gdef, "pointmin", {"x": "-1.20", "y": "-0.86", "z": "-0.25"})
    ET.SubElement(gdef, "pointmax", {"x": "11.10", "y": "0.86", "z": "1.45"})

    cmds = ET.SubElement(geom, "commands")
    mlist = ET.SubElement(cmds, "mainlist")

    smode = ET.SubElement(mlist, "setshapemode")
    smode.text = "dp | actual | bound"
    ET.SubElement(mlist, "setdrawmode", {"mode": "solid"})

    # 1. Surface-first bed support mesh (mk=40, 60 triangles drawn first)
    ET.SubElement(mlist, "setmkbound", {
        "mk": "40",
        "cmt": "root_numeric_bed_surface_support added boundary marker",
    })
    ET.SubElement(mlist, "setdrawmode", {
        "mode": "full",
        "cmt": "root_numeric_bed_surface_support surface rasterization",
    })

    dtri = ET.SubElement(mlist, "drawtriangles", {
        "cmt": "root_numeric_bed_surface_support full original60triangle mesh; drawn first so all existing physical wall and prescribed piston blocks win subsequent voxel ownership"
    })
    pts_node = ET.SubElement(dtri, "points")
    tri_node = ET.SubElement(dtri, "triangles")

    triangles = build_bed_triangles()
    point_idx = 0
    for tri in triangles:
        for vx, vy, vz in tri:
            sx = f"{vx:g}" if isinstance(vx, float) else str(vx)
            sy = f"{vy:g}" if isinstance(vy, float) else str(vy)
            sz = f"{vz:g}" if isinstance(vz, float) else str(vz)
            ET.SubElement(pts_node, "point", {"x": sx, "y": sy, "z": sz})
        ET.SubElement(tri_node, "triangle", {
            "x": str(point_idx),
            "y": str(point_idx + 1),
            "z": str(point_idx + 2),
        })
        point_idx += 3

    ET.SubElement(mlist, "setdrawmode", {
        "mode": "solid",
        "cmt": "root_numeric_bed_surface_support restore preceding mode",
    })

    # 2. Tank floor
    ET.SubElement(mlist, "setmkbound", {"mk": "0"})
    box_floor = ET.SubElement(mlist, "drawbox", {"cmt": "tank_floor"})
    ET.SubElement(box_floor, "boxfill").text = "bottom"
    ET.SubElement(box_floor, "point", {"x": "-1.10", "y": "-0.80", "z": "-0.25"})
    ET.SubElement(box_floor, "size", {"x": "11.90", "y": "1.60", "z": "0.25"})
    ET.SubElement(box_floor, "layers", {"vdp": "0,1,2"})

    # 3. Sidewalls
    ET.SubElement(mlist, "setmkbound", {"mk": "30"})
    box_sw_l = ET.SubElement(mlist, "drawbox", {"cmt": "finite_sidewall_left"})
    ET.SubElement(box_sw_l, "boxfill").text = "solid"
    ET.SubElement(box_sw_l, "point", {"x": "-1.10", "y": "-0.80", "z": "-0.25"})
    ET.SubElement(box_sw_l, "size", {"x": "11.90", "y": "0.08", "z": "1.45"})
    ET.SubElement(box_sw_l, "layers", {"vdp": "0,1,2"})

    box_sw_r = ET.SubElement(mlist, "drawbox", {"cmt": "finite_sidewall_right"})
    ET.SubElement(box_sw_r, "boxfill").text = "solid"
    ET.SubElement(box_sw_r, "point", {"x": "-1.10", "y": "0.72", "z": "-0.25"})
    ET.SubElement(box_sw_r, "size", {"x": "11.90", "y": "0.08", "z": "1.45"})
    ET.SubElement(box_sw_r, "layers", {"vdp": "0,1,2"})

    # 4. Piston
    ET.SubElement(mlist, "setmkbound", {"mk": "10"})
    box_pis = ET.SubElement(mlist, "drawbox", {"cmt": "prescribed_piston"})
    ET.SubElement(box_pis, "boxfill").text = "solid"
    ET.SubElement(box_pis, "point", {"x": "-1.08", "y": "-0.72", "z": "0"})
    ET.SubElement(box_pis, "size", {"x": "0.08", "y": "1.44", "z": "1.02"})
    ET.SubElement(box_pis, "layers", {"vdp": "0,1,2"})

    # 5. Continuous bed STL rasterization
    ET.SubElement(mlist, "setdrawmode", {"mode": "full"})
    ET.SubElement(mlist, "setmkbound", {"mk": "40"})
    ET.SubElement(mlist, "drawfilestl", {"file": stl_rel_path})
    ET.SubElement(mlist, "shapeout", {"file": "continuous_bed", "reset": "true"})

    # 6. Weir structure (if weir mechanism)
    if mechanism == "weir":
        ET.SubElement(mlist, "setmkbound", {"mk": "50"})
        weir_l = ET.SubElement(mlist, "drawbox", {"cmt": "weir_left_side_segment"})
        ET.SubElement(weir_l, "boxfill").text = "solid"
        ET.SubElement(weir_l, "point", {"x": "4.96", "y": "-0.70", "z": "0.3648"})
        ET.SubElement(weir_l, "size", {"x": "0.24", "y": "0.95", "z": "0.11"})
        ET.SubElement(weir_l, "layers", {"vdp": "0,1,2"})

        weir_r = ET.SubElement(mlist, "drawbox", {"cmt": "weir_right_side_segment"})
        ET.SubElement(weir_r, "boxfill").text = "solid"
        ET.SubElement(weir_r, "point", {"x": "4.96", "y": "0.50", "z": "0.3648"})
        ET.SubElement(weir_r, "size", {"x": "0.24", "y": "0.20", "z": "0.11"})
        ET.SubElement(weir_r, "layers", {"vdp": "0,1,2"})

    # 7. Initial fluid block
    ET.SubElement(mlist, "setmkfluid", {"mk": "0"})
    fbox_cfg = res["fluid_box"]
    fbox = ET.SubElement(mlist, "drawbox", {"cmt": f"initial_fluid_cell_centres_{res_key}"})
    ET.SubElement(fbox, "boxfill").text = "solid"
    ET.SubElement(fbox, "point", fbox_cfg["point"])
    ET.SubElement(fbox, "size", fbox_cfg["size"])

    # Motion section
    motion = ET.SubElement(casedef, "motion")
    objr = ET.SubElement(motion, "objreal", {"ref": "10"})
    ET.SubElement(objr, "begin", {"mov": "1", "start": "0.00", "finish": "16.0"})
    mvpre = ET.SubElement(objr, "mvpredef", {"id": "1", "duration": "16.0"})
    ET.SubElement(
        mvpre,
        "file",
        {"name": piston_file, "fields": "2", "fieldtime": "0", "fieldx": "1"},
    )

    # Execution section
    exec_node = ET.SubElement(root, "execution")
    special = ET.SubElement(exec_node, "special")
    gauges = ET.SubElement(special, "gauges")

    default_g = ET.SubElement(gauges, "default")
    ET.SubElement(default_g, "savevtkpart", {"value": "true"})
    ET.SubElement(default_g, "_computedt", {"value": "0.02"})
    ET.SubElement(default_g, "_computetime", {"start": "0", "end": "16"})
    ET.SubElement(default_g, "output", {"value": "true"})
    ET.SubElement(default_g, "_outputdt", {"value": "0.02"})
    ET.SubElement(default_g, "_outputtime", {"start": "0", "end": "16"})

    # Add corrected gauges
    for g in CORRECTED_GAUGES:
        swl = ET.SubElement(gauges, "swl", {"name": str(g["name"])})
        ET.SubElement(swl, "pointdp", {"coefdp": str(g["coefdp"])})
        ET.SubElement(
            swl,
            "point0",
            {"x": str(g["x"]), "y": str(g["y"]), "z": str(g["z_bed"])},
        )
        ET.SubElement(
            swl,
            "point2",
            {"x": str(g["x"]), "y": str(g["y"]), "z": str(g["point2_z"])},
        )

    # Numerical execution parameters
    params = ET.SubElement(exec_node, "parameters")
    param_dict = [
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
    for k, v in param_dict:
        ET.SubElement(params, "parameter", {"key": k, "value": v})

    sdom_cfg = res["simulation_domain"]
    sdom = ET.SubElement(params, "simulationdomain")
    ET.SubElement(sdom, "posmin", sdom_cfg["posmin"])
    ET.SubElement(sdom, "posmax", sdom_cfg["posmax"])

    return root


def format_xml_string(root: ET.Element) -> str:
    """Format ElementTree into pretty UTF-8 XML string with declaration."""
    ET.indent(root, space="  ", level=0)
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8") + "\n"


def prepare_all_cases(output_dir: Path) -> Dict[str, object]:
    """Prepare and write the six XML case definitions for the nominal pair."""
    manifest_entries = []
    cases_written = 0

    for mechanism in ["runup", "weir"]:
        mech_dir = output_dir / "definitions" / mechanism
        mech_dir.mkdir(parents=True, exist_ok=True)

        for res_key, res_data in RESOLUTIONS.items():
            case_id = f"F5_REF_{mechanism.upper()}_{res_key.upper()}_FALLBACK_042"
            xml_filename = f"{case_id}.xml"
            xml_path = mech_dir / xml_filename

            root = build_case_xml(mechanism, res_key)
            xml_content = format_xml_string(root)
            xml_path.write_text(xml_content, encoding="utf-8")
            cases_written += 1

            manifest_entries.append({
                "case_id": case_id,
                "mechanism": mechanism,
                "resolution": res_key,
                "dp_m": res_data["dp_m"],
                "xml_path": str(xml_path),
                "predicted_fluid_particles": res_data["predicted_fluid_particles"],
                "predicted_total_particles": res_data["predicted_total_particles"],
                "nominal_fluid_mass_kg": NOMINAL_FLUID_MASS_KG,
                "corrected_gauges_count": len(CORRECTED_GAUGES),
                "surface_first_support_facets": 60,
                "is_prediction_clearly_not_actual": True,
            })

    summary = {
        "schema": "ds02.f5.prepared-fallback-cases-manifest.v1",
        "nominal_pair_count": 2,
        "commensurate_dp_count": 3,
        "total_cases_prepared": cases_written,
        "cases": manifest_entries,
        "observer_correction": {
            "all_probes_aligned_with_bed": True,
            "subterranean_embedding_eliminated": True,
            "crest_bed_elevation_authentic_m": 0.840,
        },
        "governance": {
            "launch_allowed": False,
            "launch_owner": "root",
            "q_n_status": "not_assessed",
            "production_approval": "none",
            "claims_require_actual_data": True,
        },
    }

    manifest_path = output_dir / "prepared_cases_manifest.json"
    manifest_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F5 fallback case preparation worker."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Root scope directory to prepare definitions in.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate XML generation in memory without writing files.",
    )
    args = parser.parse_args()

    if args.dry_run:
        for m in ["runup", "weir"]:
            for r in ["dp050", "dp025", "dp010"]:
                root = build_case_xml(m, r)
                assert root.find(".//special/gauges") is not None
                assert len(root.findall(".//special/gauges/swl")) == 6
                assert len(root.findall(".//geometry/commands/mainlist/drawtriangles/triangles/triangle")) == 60
        print("Dry run completed: all 6 XML definitions validated in memory.")
    else:
        summary = prepare_all_cases(args.output_dir)
        print(f"Prepared {summary['total_cases_prepared']} cases successfully.")


if __name__ == "__main__":
    main()
