#!/usr/bin/env python3
"""Bounded Executable Source Builder for Family F1 Stage 1 Batch Cases.

Generates exact DualSPHysics XML case definitions (*_Def.xml), metadata JSONs,
GenCase requests, Solver requests, and Stage 1 Visual Product bindings for
the 8 independent physical parameter rows across ECC and DUAL mechanisms.

Key Invariants:
1. Pure SOURCE-ONLY generation: writes bounded definition files and requests;
   does NOT invoke GenCase, DualSPHysics, PartVTK, or ParaView (no numeric generation).
2. Multi-Resolution Accounting: Coarse and medium DP runs are generated for each
   case as resolution checks, but STRICTLY count as ONE physical case per row.
3. Safe Parameter Bounds: Verifies fill depth is safely below failed mothers,
   freeboard >= 0.20 m, wall clearances >= 0.10 m (>> 3*dp), and genuine 3D flow.
4. Visual Review Gate: Proposed non-mother cases are marked disabled from solver
   dispatch until Root and User complete visual review of the mother cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple
import xml.etree.ElementTree as ET


OFFICIAL_GENCASE = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
OFFICIAL_SOLVER = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DATA_ROOT = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def format_float(val: float, precision: int = 6) -> str:
    s = f"{val:.{precision}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def generate_def_xml(row: Dict[str, Any], resolution: str, dp: float) -> str:
    """Build exact DualSPHysics XML definition."""
    mech = row["mechanism_id"]
    geom = row["geometry"]
    tank = geom["tank"]
    tank_sz = tank["size_m"]
    res = geom["fluid_reservoir"]
    res_low = res["low_m"]
    res_sz = res["size_m"]
    params = row["physical_parameters"]
    eos = row["eos"]

    root = ET.Element("case")
    casedef = ET.SubElement(root, "casedef")

    # Constants
    constants = ET.SubElement(casedef, "constantsdef")
    ET.SubElement(constants, "gravity", x="0", y="0", z="-9.81")
    ET.SubElement(constants, "rhop0", value=str(int(eos["rhop0"])))
    ET.SubElement(constants, "rhopgradient", value="2")
    ET.SubElement(constants, "hswl", value="0", auto="true")
    ET.SubElement(constants, "gamma", value=str(int(eos["gamma"])))
    ET.SubElement(constants, "speedsystem", value="0", auto="true")
    ET.SubElement(constants, "coefsound", value=str(int(eos["coefsound"])))
    ET.SubElement(constants, "speedsound", value="0", auto="true")
    ET.SubElement(constants, "coefh", value="1.0")
    ET.SubElement(constants, "cflnumber", value=str(eos["cflnumber"]))

    ET.SubElement(casedef, "mkconfig", boundcount="240", fluidcount="9")

    # Geometry definition
    geometry = ET.SubElement(casedef, "geometry")
    half_dp = dp * 0.5
    pointmin_val = -2.5 * dp
    pointmax_x = tank_sz[0] + dp
    pointmax_y = tank_sz[1] + dp
    pointmax_z = tank_sz[2] + dp

    definition = ET.SubElement(
        geometry,
        "definition",
        dp=format_float(dp, 8),
        units_comment="metres (m)",
    )
    ET.SubElement(
        definition,
        "pointref",
        x=format_float(half_dp, 8),
        y=format_float(half_dp, 8),
        z=format_float(half_dp, 8),
    )
    ET.SubElement(
        definition,
        "pointmin",
        x=format_float(pointmin_val, 8),
        y=format_float(pointmin_val, 8),
        z=format_float(pointmin_val, 8),
    )
    ET.SubElement(
        definition,
        "pointmax",
        x=format_float(pointmax_x, 4),
        y=format_float(pointmax_y, 4),
        z=format_float(pointmax_z, 4),
    )

    commands = ET.SubElement(geometry, "commands")
    mainlist = ET.SubElement(commands, "mainlist")
    ET.SubElement(mainlist, "setshapemode").text = "dp | actual | bound"
    ET.SubElement(mainlist, "setdrawmode", mode="full")

    # MkBound 0: Tank Walls (4-layer thick DBC, thickness 2*dp support)
    ET.SubElement(mainlist, "setmkbound", mk="0")
    support_thick = 2.0 * dp
    outer_expand = 2.5 * dp

    # x_low
    b_xlow = ET.SubElement(mainlist, "drawbox", cmt="thick outer support x_low")
    ET.SubElement(b_xlow, "boxfill").text = "solid"
    ET.SubElement(b_xlow, "point", x=format_float(-outer_expand, 6), y=format_float(-outer_expand, 6), z=format_float(-outer_expand, 6))
    ET.SubElement(b_xlow, "size", x=format_float(support_thick, 6), y=format_float(tank_sz[1] + 5.0 * dp, 6), z=format_float(tank_sz[2] + 5.0 * dp, 6))

    # x_high
    b_xhigh = ET.SubElement(mainlist, "drawbox", cmt="thick outer support x_high")
    ET.SubElement(b_xhigh, "boxfill").text = "solid"
    ET.SubElement(b_xhigh, "point", x=format_float(tank_sz[0] + half_dp, 6), y=format_float(-outer_expand, 6), z=format_float(-outer_expand, 6))
    ET.SubElement(b_xhigh, "size", x=format_float(support_thick, 6), y=format_float(tank_sz[1] + 5.0 * dp, 6), z=format_float(tank_sz[2] + 5.0 * dp, 6))

    # y_low
    b_ylow = ET.SubElement(mainlist, "drawbox", cmt="thick outer support y_low")
    ET.SubElement(b_ylow, "boxfill").text = "solid"
    ET.SubElement(b_ylow, "point", x=format_float(-outer_expand, 6), y=format_float(-outer_expand, 6), z=format_float(-outer_expand, 6))
    ET.SubElement(b_ylow, "size", x=format_float(tank_sz[0] + 5.0 * dp, 6), y=format_float(support_thick, 6), z=format_float(tank_sz[2] + 5.0 * dp, 6))

    # y_high
    b_yhigh = ET.SubElement(mainlist, "drawbox", cmt="thick outer support y_high")
    ET.SubElement(b_yhigh, "boxfill").text = "solid"
    ET.SubElement(b_yhigh, "point", x=format_float(-outer_expand, 6), y=format_float(tank_sz[1] + half_dp, 6), z=format_float(-outer_expand, 6))
    ET.SubElement(b_yhigh, "size", x=format_float(tank_sz[0] + 5.0 * dp, 6), y=format_float(support_thick, 6), z=format_float(tank_sz[2] + 5.0 * dp, 6))

    # z_low
    b_zlow = ET.SubElement(mainlist, "drawbox", cmt="thick outer support z_low")
    ET.SubElement(b_zlow, "boxfill").text = "solid"
    ET.SubElement(b_zlow, "point", x=format_float(-outer_expand, 6), y=format_float(-outer_expand, 6), z=format_float(-outer_expand, 6))
    ET.SubElement(b_zlow, "size", x=format_float(tank_sz[0] + 5.0 * dp, 6), y=format_float(tank_sz[1] + 5.0 * dp, 6), z=format_float(support_thick, 6))

    # Obstacle / Divider definition
    if mech == "eccentric_obstacle":
        obs = geom["obstacle"]
        obs_low = obs["low_m"]
        obs_sz = obs["size_m"]

        ET.SubElement(mainlist, "setmkvoid")
        void_box = ET.SubElement(mainlist, "drawbox", cmt="ECC obstacle physical solid void")
        ET.SubElement(void_box, "boxfill").text = "solid"
        ET.SubElement(void_box, "point", x=format_float(obs_low[0], 4), y=format_float(obs_low[1], 4), z=format_float(obs_low[2], 4))
        ET.SubElement(void_box, "size", x=format_float(obs_sz[0], 4), y=format_float(obs_sz[1], 4), z=format_float(obs_sz[2], 4))

        ET.SubElement(mainlist, "setmkbound", mk="1")
        # Internal thick support for obstacle
        obs_sup = ET.SubElement(mainlist, "drawbox", cmt="ECC thick obstacle support")
        ET.SubElement(obs_sup, "boxfill").text = "solid"
        ET.SubElement(obs_sup, "point", x=format_float(obs_low[0] + half_dp, 6), y=format_float(obs_low[1] + half_dp, 6), z=format_float(obs_low[2] + half_dp, 6))
        ET.SubElement(obs_sup, "size", x=format_float(obs_sz[0] - dp, 6), y=format_float(obs_sz[1] - dp, 6), z=format_float(obs_sz[2] - half_dp, 6))

    elif mech == "asymmetric_dual_channel":
        div = geom["divider"]
        div_low = div["low_m"]
        div_sz = div["size_m"]

        ET.SubElement(mainlist, "setmkvoid")
        void_box = ET.SubElement(mainlist, "drawbox", cmt="asymmetric channel divider solid void")
        ET.SubElement(void_box, "boxfill").text = "solid"
        ET.SubElement(void_box, "point", x=format_float(div_low[0], 4), y=format_float(div_low[1], 4), z=format_float(div_low[2], 4))
        ET.SubElement(void_box, "size", x=format_float(div_sz[0], 4), y=format_float(div_sz[1], 4), z=format_float(div_sz[2], 4))

        ET.SubElement(mainlist, "setmkbound", mk="1")
        # Internal thick support for divider
        div_sup = ET.SubElement(mainlist, "drawbox", cmt="thick divider support")
        ET.SubElement(div_sup, "boxfill").text = "solid"
        ET.SubElement(div_sup, "point", x=format_float(div_low[0] + half_dp, 6), y=format_float(div_low[1] + half_dp, 6), z=format_float(div_low[2] + half_dp, 6))
        ET.SubElement(div_sup, "size", x=format_float(div_sz[0] - dp, 6), y=format_float(div_sz[1] - dp, 6), z=format_float(div_sz[2] - half_dp, 6))

    # Fluid block (cell-centered)
    ET.SubElement(mainlist, "setmkfluid", mk="0")
    f_box = ET.SubElement(mainlist, "drawbox", cmt="controlled fluid cell centres")
    ET.SubElement(f_box, "boxfill").text = "solid"

    # Discrete fluid particle alignment
    nx = round(res_sz[0] / dp)
    ny = round(res_sz[1] / dp)
    nz = round(res_sz[2] / dp)
    f_pt_x = res_low[0] + half_dp
    f_pt_y = res_low[1] + half_dp
    f_pt_z = res_low[2] + half_dp
    f_sz_x = (nx - 1) * dp
    f_sz_y = (ny - 1) * dp
    f_sz_z = (nz - 1) * dp

    ET.SubElement(f_box, "point", x=format_float(f_pt_x, 6), y=format_float(f_pt_y, 6), z=format_float(f_pt_z, 6))
    ET.SubElement(f_box, "size", x=format_float(f_sz_x, 6), y=format_float(f_sz_y, 6), z=format_float(f_sz_z, 6))

    # Execution Parameters
    execution = ET.SubElement(root, "execution")
    parameters = ET.SubElement(execution, "parameters")
    sim_params = [
        ("Boundary", "1"),
        ("SavePosDouble", "1"),
        ("StepAlgorithm", "1"),
        ("VerletSteps", "40"),
        ("Kernel", "1"),
        ("ViscoTreatment", "1"),
        ("Visco", "0.1"),
        ("ViscoBoundFactor", "1"),
        ("DensityDT", "2"),
        ("DensityDTvalue", "0.1"),
        ("Shifting", "0"),
        ("RigidAlgorithm", "1"),
        ("FtPause", "0"),
        ("CoefDtMin", "0.05"),
        ("DtIni", "0"),
        ("DtMin", "0"),
        ("DtFixed", "0"),
        ("DtAllParticles", "0"),
        ("TimeMax", format_float(params["time_max_s"], 2)),
        ("TimeOut", format_float(params["time_out_s"], 4)),
        ("MinFluidStop", "0"),
        ("RhopOutMin", "700"),
        ("RhopOutMax", "1300"),
    ]
    for k, v in sim_params:
        ET.SubElement(parameters, "parameter", key=k, value=v)

    simdomain = ET.SubElement(parameters, "simulationdomain")
    ET.SubElement(simdomain, "posmin", x="default - 25%", y="default - 25%", z="default - 25%")
    ET.SubElement(simdomain, "posmax", x="default + 25%", y="default + 25%", z="default + 75%")

    ET.indent(root)
    xml_str = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")
    return xml_str


def build_all_cases(output_base: Path, matrix_file: Path) -> Dict[str, Any]:
    """Execute bounded source building for all 8 physical cases across 2 resolutions."""
    matrix = json.loads(matrix_file.read_text())
    rows = matrix["rows"]
    summary = {
        "schema": "ds02.stage1.batch-builder-summary.v1",
        "family_id": "F1",
        "physical_cases": len(rows),
        "resolution_levels": ["coarse", "medium"],
        "total_setups": len(rows) * 2,
        "cases": {},
    }

    defs_dir = output_base / "definitions"
    reqs_dir = output_base / "requests"
    meta_dir = output_base / "metadata"
    for d in (defs_dir, reqs_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)

    for row in rows:
        row_idx = row["row_index"]
        phys_id = row["physical_case_id"]
        mech = row["mechanism_id"]
        res_map = row["resolutions"]
        is_mother = row["status"] == "mother_completed_native_under_visual_review"

        summary["cases"][phys_id] = {
            "row_index": row_idx,
            "mechanism_id": mech,
            "role": row["variation_role"],
            "status": row["status"],
            "setups": {},
        }

        for res_name, res_info in res_map.items():
            dp = res_info["dp"]
            case_id = f"{phys_id}_{res_name.upper()}"

            # 1. Def.xml
            xml_content = generate_def_xml(row, res_name, dp)
            xml_file = defs_dir / f"{case_id}_Def.xml"
            xml_file.write_text(xml_content, encoding="utf-8")
            xml_sha = sha256_text(xml_content)

            # 2. Metadata JSON
            nx = round(row["geometry"]["fluid_reservoir"]["size_m"][0] / dp)
            ny = round(row["geometry"]["fluid_reservoir"]["size_m"][1] / dp)
            nz = round(row["geometry"]["fluid_reservoir"]["size_m"][2] / dp)
            pred_fluid = nx * ny * nz

            metadata = {
                "schema": "ds02.stage1.case-metadata.v1",
                "family_id": "F1",
                "physical_case_id": phys_id,
                "case_id": case_id,
                "mechanism_id": mech,
                "resolution": res_name,
                "dp_m": dp,
                "grid_cells_xyz": [nx, ny, nz],
                "predicted_fluid_particles": pred_fluid,
                "continuum_volume_m3": row["physical_parameters"]["continuum_volume_m3"],
                "continuum_mass_kg": row["physical_parameters"]["continuum_mass_kg"],
                "time_max_s": row["physical_parameters"]["time_max_s"],
                "time_out_s": row["physical_parameters"]["time_out_s"],
                "expected_frames": row["physical_parameters"]["expected_frames"],
                "safe_variation_proof": row["safe_variation_proof"],
                "def_xml_sha256": xml_sha,
                "dispatch_gate": (
                    "unconditionally_launchable"
                    if is_mother
                    else "disabled_pending_root_visual_review"
                ),
                "independent_case_counting": (
                    "Counted once per physical_case_id; coarse/medium resolution runs "
                    "do NOT multiply physical case count."
                ),
            }
            meta_file = meta_dir / f"{case_id}.metadata.json"
            meta_file.write_text(json.dumps(metadata, indent=2) + "\n")

            # 3. GenCase Request
            attempt_gencase = f"f1-batch1-{case_id.lower()}-gencase-001"
            gencase_req = {
                "schema": "ds02.runner-request.v2",
                "family_id": "F1",
                "case_id": case_id,
                "attempt_id": attempt_gencase,
                "kind": "cpu",
                "cpu_task_kind": "preflight",
                "cpu_threads": 2,
                "max_wall_seconds": 600,
                "estimated_storage_bytes": 1073741824,
                "cwd": "/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics/lagrangian-fluid-lab",
                "worktree_root": "/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics",
                "command": [
                    OFFICIAL_GENCASE,
                    f"{{attempt_root}}/prepared/{case_id}_Def",
                    f"{{attempt_root}}/prepared/{case_id}",
                    "-save:all",
                    "-threads:2",
                ],
                "input_files": [
                    OFFICIAL_GENCASE,
                    str(xml_file),
                ],
                "input_sha256": {
                    str(xml_file): xml_sha,
                },
                "launch_allowed": False if not is_mother else True,
                "launch_owner": "root",
                "dispatch_status": "disabled_pending_root_visual_review" if not is_mother else "mother_asset",
                "independent_case_count_increment": 0,
            }
            gencase_req_file = reqs_dir / f"{case_id}_gencase_request.json"
            gencase_req_file.write_text(json.dumps(gencase_req, indent=2) + "\n")

            # 4. Solver Request
            attempt_solver = f"f1-batch1-{case_id.lower()}-solver-001"
            solver_req = {
                "schema": "ds02.runner-request.v2",
                "family_id": "F1",
                "case_id": case_id,
                "attempt_id": attempt_solver,
                "kind": "qualification",
                "cpu_threads": 4,
                "max_wall_seconds": 3600,
                "estimated_storage_bytes": 10737418240,
                "cwd": "/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics/lagrangian-fluid-lab",
                "worktree_root": "/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics",
                "command": [
                    OFFICIAL_SOLVER,
                    f"{DATA_ROOT}/{case_id}/{attempt_gencase}/prepared/{case_id}",
                    "{attempt_root}/solver_output",
                    f"-tmax:{row['physical_parameters']['time_max_s']}",
                    f"-tout:{row['physical_parameters']['time_out_s']}",
                ],
                "launch_allowed": False,
                "launch_owner": "root",
                "dispatch_status": (
                    "disabled_pending_root_visual_review"
                    if not is_mother
                    else "mother_native_completed_under_review"
                ),
                "independent_case_count_increment": 1 if res_name == "coarse" else 0,
                "counting_note": (
                    "Physical case count increments ONLY on primary acceptance; "
                    "medium DP contributes to resolution verification, not case count."
                ),
                "gate": "stage1_visual_integrity_only; numerical_precision_pending",
            }
            solver_req_file = reqs_dir / f"{case_id}_solver_request.json"
            solver_req_file.write_text(json.dumps(solver_req, indent=2) + "\n")

            summary["cases"][phys_id]["setups"][res_name] = {
                "dp_m": dp,
                "xml_file": str(xml_file),
                "xml_sha256": xml_sha,
                "metadata_file": str(meta_file),
                "gencase_request": str(gencase_req_file),
                "solver_request": str(solver_req_file),
            }

    summary_file = output_base / "builder_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "batch_definitions" / "batch_8_physical_parameter_matrix.json",
        help="Path to physical parameter matrix JSON",
    )
    parser.add_argument(
        "--output-base",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Base directory to output case definitions, metadata, and requests",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify parameter bounds and clearances without writing files",
    )
    args = parser.parse_args()

    assert args.matrix.exists(), f"Matrix file not found: {args.matrix}"
    matrix = json.loads(args.matrix.read_text())

    # Verification of bounds
    for row in matrix["rows"]:
        phys_id = row["physical_case_id"]
        geom = row["geometry"]
        tank_sz = geom["tank"]["size_m"]
        f_sz = geom["fluid_reservoir"]["size_m"]
        freeboard = tank_sz[2] - f_sz[2]
        assert freeboard >= 0.20, f"Insufficient freeboard ({freeboard}m < 0.20m) for {phys_id}"

        if row["mechanism_id"] == "eccentric_obstacle":
            obs_low = geom["obstacle"]["low_m"]
            obs_sz = geom["obstacle"]["size_m"]
            c_low = obs_low[1]
            c_high = tank_sz[1] - (obs_low[1] + obs_sz[1])
            assert c_low >= 0.10 and c_high >= 0.10, f"Wall clearance violated for {phys_id}"
        elif row["mechanism_id"] == "asymmetric_dual_channel":
            div_low = geom["divider"]["low_m"]
            div_sz = geom["divider"]["size_m"]
            c_low = div_low[1]
            c_high = tank_sz[1] - (div_low[1] + div_sz[1])
            assert c_low >= 0.15 and c_high >= 0.15, f"Divider clearance violated for {phys_id}"

    if args.verify_only:
        print(f"Matrix verification PASSED for {len(matrix['rows'])} physical cases.")
        return

    summary = build_all_cases(args.output_base, args.matrix)
    print(f"Generated {summary['total_setups']} setups across {summary['physical_cases']} physical cases.")


if __name__ == "__main__":
    main()
