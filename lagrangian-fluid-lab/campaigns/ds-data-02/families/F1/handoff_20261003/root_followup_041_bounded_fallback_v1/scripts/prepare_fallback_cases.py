#!/usr/bin/env python3
"""Programmatic generator for Family F1 prospective fallback definitions, metadata, and runner requests.

Generates the complete set of XML definitions, metadata sidecars, label configs,
and Root strict dispatcher requests for the legal fallback pair:
1. F1_FALLBACK_ECC_V1 (Eccentric Obstacle Transport Fallback, H0=0.15m)
2. F1_FALLBACK_DUAL_V1 (Asymmetric Dual-Channel Transport Fallback, H0=0.30m)

Uses proven thick DBC solid slabs from root_thick_dbc and exact commensurate
cell-centered particle lattices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
from xml.dom import minidom


BASE_DIR = Path(__file__).resolve().parents[1]
DEFINITIONS_DIR = BASE_DIR / "definitions"
LABELS_DIR = BASE_DIR / "labels"
REQUESTS_DIR = BASE_DIR / "requests"
SCRIPTS_DIR = BASE_DIR / "scripts"

WORKTREE_ROOT = "/home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics"
INTEGRATION_ROOT = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics"
DATA_ROOT = "/home/jade/Projects/DualSPHysics-data/ds-data-02"
OFFICIAL_BIN_DIR = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux"
GENCASE_BIN = f"{OFFICIAL_BIN_DIR}/GenCase_linux64"
SOLVER_BIN = f"{OFFICIAL_BIN_DIR}/DualSPHysics5.4_linux64"
PARTVTK_BIN = f"{OFFICIAL_BIN_DIR}/PartVTK_linux64"
PYTHON_BIN = "/usr/bin/python3.10"
STRICT_DISPATCH_ENTRY = f"{INTEGRATION_ROOT}/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME_V2_SCRIPT = f"{INTEGRATION_ROOT}/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
THICK_DBC_BASE_SCRIPT = f"{INTEGRATION_ROOT}/lagrangian-fluid-lab/scripts/ds_data02_f1_eccentric_thick_boundary.py"


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def prettify_xml(elem: ET.Element) -> str:
    rough_string = ET.tostring(elem, "utf-8")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def _q(val: float) -> str:
    return format(float(val), ".16g")


# -----------------------------------------------------------------------------
# Case 1: F1_FALLBACK_ECC_V1
# -----------------------------------------------------------------------------
ECC_CONFIG = {
    "case_id_base": "F1_FALLBACK_ECC",
    "mechanism_id": "eccentric_obstacle",
    "physical_case_id": "F1_FALLBACK_ECC_V1",
    "h0_m": 0.150,
    "fluid_length_m": 0.400,
    "fluid_width_m": 0.670,
    "fluid_height_m": 0.150,
    "tank_length_m": 1.600,
    "tank_width_m": 0.670,
    "tank_height_m": 0.400,
    "obstacle_x_m": 0.900,
    "obstacle_y_m": 0.240,
    "obstacle_length_m": 0.120,
    "obstacle_width_m": 0.120,
    "obstacle_height_m": 0.450,
    "time_max_s": 1.60,
    "resolutions": [
        {"token": "COARSE", "dp": 0.010, "counts_xyz": (40, 67, 15)},
        {"token": "MEDIUM", "dp": 0.005, "counts_xyz": (80, 134, 30)},
        {"token": "FINE", "dp": 0.0033333333333333335, "counts_xyz": (120, 201, 45)},
    ],
}


# -----------------------------------------------------------------------------
# Case 2: F1_FALLBACK_DUAL_V1
# -----------------------------------------------------------------------------
DUAL_CONFIG = {
    "case_id_base": "F1_FALLBACK_DUAL",
    "mechanism_id": "asymmetric_dual_channel",
    "physical_case_id": "F1_FALLBACK_DUAL_V1",
    "h0_m": 0.300,
    "fluid_x_start_m": 2.200,
    "fluid_length_m": 1.000,
    "fluid_width_m": 1.000,
    "fluid_height_m": 0.300,
    "tank_length_m": 3.200,
    "tank_width_m": 1.000,
    "tank_height_m": 0.800,
    "separator_x_start_m": 1.200,
    "separator_length_m": 0.800,
    "separator_y_start_m": 0.340,
    "separator_thickness_m": 0.060,
    "separator_height_m": 0.700,
    "time_max_s": 4.00,
    "resolutions": [
        {"token": "COARSE", "dp": 0.020, "counts_xyz": (50, 50, 15)},
        {"token": "MEDIUM", "dp": 0.010, "counts_xyz": (100, 100, 30)},
        {"token": "FINE", "dp": 0.005, "counts_xyz": (200, 200, 60)},
    ],
}


def build_ecc_xml(res: dict[str, Any]) -> ET.Element:
    dp = res["dp"]
    token = res["token"]
    case = ET.Element("case")
    casedef = ET.SubElement(case, "casedef")

    constantsdef = ET.SubElement(casedef, "constantsdef")
    ET.SubElement(constantsdef, "gravity", {"x": "0", "y": "0", "z": "-9.81"})
    ET.SubElement(constantsdef, "rhop0", {"value": "1000"})
    ET.SubElement(constantsdef, "rhopgradient", {"value": "2"})
    ET.SubElement(constantsdef, "hswl", {"value": "0", "auto": "true"})
    ET.SubElement(constantsdef, "gamma", {"value": "7"})
    ET.SubElement(constantsdef, "speedsystem", {"value": "0", "auto": "true"})
    ET.SubElement(constantsdef, "coefsound", {"value": "20"})
    ET.SubElement(constantsdef, "speedsound", {"value": "0", "auto": "true"})
    ET.SubElement(constantsdef, "coefh", {"value": "1.0"})
    ET.SubElement(constantsdef, "cflnumber", {"value": "0.2"})

    ET.SubElement(casedef, "mkconfig", {"boundcount": "240", "fluidcount": "9"})

    geometry = ET.SubElement(casedef, "geometry")
    definition = ET.SubElement(geometry, "definition", {"dp": _q(dp), "units_comment": "metres (m)"})
    ET.SubElement(definition, "pointref", {"x": _q(dp / 2), "y": _q(dp / 2), "z": _q(dp / 2)})
    ET.SubElement(definition, "pointmin", {"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(definition, "pointmax", {"x": "2", "y": "1", "z": "1"})

    commands = ET.SubElement(geometry, "commands")
    mainlist = ET.SubElement(commands, "mainlist")

    setshapemode = ET.SubElement(mainlist, "setshapemode")
    setshapemode.text = "dp | actual | bound"
    setdrawmode = ET.SubElement(mainlist, "setdrawmode", {"mode": "full"})
    ET.SubElement(mainlist, "setmkbound", {"mk": "0"})

    # Outer wall slabs (5 faces)
    # x_low
    b_x_low = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support x_low"})
    ET.SubElement(b_x_low, "boxfill").text = "solid"
    ET.SubElement(b_x_low, "point", {"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_x_low, "size", {"x": _q(2.0 * dp), "y": _q(0.67 + 5.0 * dp), "z": _q(0.40 + 5.0 * dp)})

    # x_high
    b_x_high = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support x_high"})
    ET.SubElement(b_x_high, "boxfill").text = "solid"
    ET.SubElement(b_x_high, "point", {"x": _q(1.60 + 0.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_x_high, "size", {"x": _q(2.0 * dp), "y": _q(0.67 + 5.0 * dp), "z": _q(0.40 + 5.0 * dp)})

    # y_low
    b_y_low = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support y_low"})
    ET.SubElement(b_y_low, "boxfill").text = "solid"
    ET.SubElement(b_y_low, "point", {"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_y_low, "size", {"x": _q(1.60 + 5.0 * dp), "y": _q(2.0 * dp), "z": _q(0.40 + 5.0 * dp)})

    # y_high
    b_y_high = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support y_high"})
    ET.SubElement(b_y_high, "boxfill").text = "solid"
    ET.SubElement(b_y_high, "point", {"x": _q(-2.5 * dp), "y": _q(0.67 + 0.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_y_high, "size", {"x": _q(1.60 + 5.0 * dp), "y": _q(2.0 * dp), "z": _q(0.40 + 5.0 * dp)})

    # z_low
    b_z_low = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support z_low"})
    ET.SubElement(b_z_low, "boxfill").text = "solid"
    ET.SubElement(b_z_low, "point", {"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_z_low, "size", {"x": _q(1.60 + 5.0 * dp), "y": _q(0.67 + 5.0 * dp), "z": _q(2.0 * dp)})

    # Obstacle void
    ET.SubElement(mainlist, "setmkvoid")
    b_obs_v = ET.SubElement(mainlist, "drawbox", {"cmt": "frozen ECC obstacle physical solid"})
    ET.SubElement(b_obs_v, "boxfill").text = "solid"
    ET.SubElement(b_obs_v, "point", {"x": "0.9", "y": "0.24", "z": "0"})
    ET.SubElement(b_obs_v, "size", {"x": "0.12", "y": "0.12", "z": "0.45"})

    # Obstacle internal support slabs (5 faces)
    ET.SubElement(mainlist, "setmkbound", {"mk": "1"})
    # obs x_low
    o_xl = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support x_low"})
    ET.SubElement(o_xl, "boxfill").text = "solid"
    ET.SubElement(o_xl, "point", {"x": _q(0.90 + 0.5 * dp), "y": _q(0.24 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(o_xl, "size", {"x": _q(2.0 * dp), "y": _q(0.12 - dp), "z": _q(0.45 - dp)})

    # obs x_high
    o_xh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support x_high"})
    ET.SubElement(o_xh, "boxfill").text = "solid"
    ET.SubElement(o_xh, "point", {"x": _q(1.02 - 2.5 * dp), "y": _q(0.24 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(o_xh, "size", {"x": _q(2.0 * dp), "y": _q(0.12 - dp), "z": _q(0.45 - dp)})

    # obs y_low
    o_yl = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support y_low"})
    ET.SubElement(o_yl, "boxfill").text = "solid"
    ET.SubElement(o_yl, "point", {"x": _q(0.90 + 0.5 * dp), "y": _q(0.24 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(o_yl, "size", {"x": _q(0.12 - dp), "y": _q(2.0 * dp), "z": _q(0.45 - dp)})

    # obs y_high
    o_yh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support y_high"})
    ET.SubElement(o_yh, "boxfill").text = "solid"
    ET.SubElement(o_yh, "point", {"x": _q(0.90 + 0.5 * dp), "y": _q(0.36 - 2.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(o_yh, "size", {"x": _q(0.12 - dp), "y": _q(2.0 * dp), "z": _q(0.45 - dp)})

    # obs z_high
    o_zh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support z_high"})
    ET.SubElement(o_zh, "boxfill").text = "solid"
    ET.SubElement(o_zh, "point", {"x": _q(0.90 + 0.5 * dp), "y": _q(0.24 + 0.5 * dp), "z": _q(0.45 - 2.5 * dp)})
    ET.SubElement(o_zh, "size", {"x": _q(0.12 - dp), "y": _q(0.12 - dp), "z": _q(2.0 * dp)})

    # Fluid column (controlled depth H0 = 0.15m)
    ET.SubElement(mainlist, "setmkfluid", {"mk": "0"})
    nx, ny, nz = res["counts_xyz"]
    b_fluid = ET.SubElement(mainlist, "drawbox", {"cmt": "v1 fallback controlled fluid cell centres"})
    ET.SubElement(b_fluid, "boxfill").text = "solid"
    ET.SubElement(b_fluid, "point", {"x": _q(dp / 2), "y": _q(dp / 2), "z": _q(dp / 2)})
    ET.SubElement(b_fluid, "size", {"x": _q((nx - 1) * dp), "y": _q((ny - 1) * dp), "z": _q((nz - 1) * dp)})

    # Execution parameters
    execution = ET.SubElement(case, "execution")
    params = ET.SubElement(execution, "parameters")
    param_dict = {
        "Boundary": "1",
        "SavePosDouble": "1",
        "StepAlgorithm": "1",
        "VerletSteps": "40",
        "Kernel": "1",
        "ViscoTreatment": "1",
        "Visco": "0.1",
        "ViscoBoundFactor": "1",
        "DensityDT": "2",
        "DensityDTvalue": "0.1",
        "Shifting": "0",
        "RigidAlgorithm": "1",
        "FtPause": "0",
        "CoefDtMin": "0.05",
        "DtIni": "0",
        "DtMin": "0",
        "DtFixed": "0",
        "DtAllParticles": "0",
        "TimeMax": "1.6",
        "TimeOut": "0.01",
        "MinFluidStop": "0",
        "RhopOutMin": "700",
        "RhopOutMax": "1300",
    }
    for k, v in param_dict.items():
        ET.SubElement(params, "parameter", {"key": k, "value": v})

    simdom = ET.SubElement(params, "simulationdomain")
    ET.SubElement(simdom, "posmin", {"x": "default - 25%", "y": "default - 25%", "z": "default - 25%"})
    ET.SubElement(simdom, "posmax", {"x": "default + 25%", "y": "default + 25%", "z": "default + 75%"})

    return case


def build_dual_xml(res: dict[str, Any]) -> ET.Element:
    dp = res["dp"]
    token = res["token"]
    case = ET.Element("case")
    casedef = ET.SubElement(case, "casedef")

    constantsdef = ET.SubElement(casedef, "constantsdef")
    ET.SubElement(constantsdef, "gravity", {"x": "0", "y": "0", "z": "-9.81"})
    ET.SubElement(constantsdef, "rhop0", {"value": "1000"})
    ET.SubElement(constantsdef, "rhopgradient", {"value": "2"})
    ET.SubElement(constantsdef, "hswl", {"value": "0", "auto": "true"})
    ET.SubElement(constantsdef, "gamma", {"value": "7"})
    ET.SubElement(constantsdef, "speedsystem", {"value": "0", "auto": "true"})
    ET.SubElement(constantsdef, "coefsound", {"value": "20"})
    ET.SubElement(constantsdef, "speedsound", {"value": "0", "auto": "true"})
    ET.SubElement(constantsdef, "coefh", {"value": "1.0"})
    ET.SubElement(constantsdef, "cflnumber", {"value": "0.2"})

    ET.SubElement(casedef, "mkconfig", {"boundcount": "240", "fluidcount": "9"})

    geometry = ET.SubElement(casedef, "geometry")
    definition = ET.SubElement(geometry, "definition", {"dp": _q(dp), "units_comment": "metres (m)"})
    ET.SubElement(definition, "pointref", {"x": _q(dp / 2), "y": _q(dp / 2), "z": _q(dp / 2)})
    ET.SubElement(definition, "pointmin", {"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(definition, "pointmax", {"x": "4", "y": "2", "z": "2"})

    commands = ET.SubElement(geometry, "commands")
    mainlist = ET.SubElement(commands, "mainlist")

    setshapemode = ET.SubElement(mainlist, "setshapemode")
    setshapemode.text = "dp | actual | bound"
    setdrawmode = ET.SubElement(mainlist, "setdrawmode", {"mode": "full"})
    ET.SubElement(mainlist, "setmkbound", {"mk": "0"})

    # Outer wall slabs (5 faces)
    # Tank L=3.20, W=1.00, H=0.80
    # x_low
    b_x_low = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support x_low"})
    ET.SubElement(b_x_low, "boxfill").text = "solid"
    ET.SubElement(b_x_low, "point", {"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_x_low, "size", {"x": _q(2.0 * dp), "y": _q(1.00 + 5.0 * dp), "z": _q(0.80 + 5.0 * dp)})

    # x_high
    b_x_high = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support x_high"})
    ET.SubElement(b_x_high, "boxfill").text = "solid"
    ET.SubElement(b_x_high, "point", {"x": _q(3.20 + 0.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_x_high, "size", {"x": _q(2.0 * dp), "y": _q(1.00 + 5.0 * dp), "z": _q(0.80 + 5.0 * dp)})

    # y_low
    b_y_low = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support y_low"})
    ET.SubElement(b_y_low, "boxfill").text = "solid"
    ET.SubElement(b_y_low, "point", {"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_y_low, "size", {"x": _q(3.20 + 5.0 * dp), "y": _q(2.0 * dp), "z": _q(0.80 + 5.0 * dp)})

    # y_high
    b_y_high = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support y_high"})
    ET.SubElement(b_y_high, "boxfill").text = "solid"
    ET.SubElement(b_y_high, "point", {"x": _q(-2.5 * dp), "y": _q(1.00 + 0.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_y_high, "size", {"x": _q(3.20 + 5.0 * dp), "y": _q(2.0 * dp), "z": _q(0.80 + 5.0 * dp)})

    # z_low
    b_z_low = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick outer support z_low"})
    ET.SubElement(b_z_low, "boxfill").text = "solid"
    ET.SubElement(b_z_low, "point", {"x": _q(-2.5 * dp), "y": _q(-2.5 * dp), "z": _q(-2.5 * dp)})
    ET.SubElement(b_z_low, "size", {"x": _q(3.20 + 5.0 * dp), "y": _q(1.00 + 5.0 * dp), "z": _q(2.0 * dp)})

    # Separator void
    # Separator x in [1.20, 2.00], y in [0.34, 0.40], z in [0.00, 0.70]
    ET.SubElement(mainlist, "setmkvoid")
    b_sep_v = ET.SubElement(mainlist, "drawbox", {"cmt": "asymmetric separator physical solid"})
    ET.SubElement(b_sep_v, "boxfill").text = "solid"
    ET.SubElement(b_sep_v, "point", {"x": "1.2", "y": "0.34", "z": "0"})
    ET.SubElement(b_sep_v, "size", {"x": "0.8", "y": "0.06", "z": "0.7"})

    # Separator internal solid slabs (5 faces)
    ET.SubElement(mainlist, "setmkbound", {"mk": "1"})
    # sep x_low
    s_xl = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support x_low"})
    ET.SubElement(s_xl, "boxfill").text = "solid"
    ET.SubElement(s_xl, "point", {"x": _q(1.20 + 0.5 * dp), "y": _q(0.34 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(s_xl, "size", {"x": _q(2.0 * dp), "y": _q(0.06 - dp), "z": _q(0.70 - dp)})

    # sep x_high
    s_xh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support x_high"})
    ET.SubElement(s_xh, "boxfill").text = "solid"
    ET.SubElement(s_xh, "point", {"x": _q(2.00 - 2.5 * dp), "y": _q(0.34 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(s_xh, "size", {"x": _q(2.0 * dp), "y": _q(0.06 - dp), "z": _q(0.70 - dp)})

    # sep y_low
    s_yl = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support y_low"})
    ET.SubElement(s_yl, "boxfill").text = "solid"
    ET.SubElement(s_yl, "point", {"x": _q(1.20 + 0.5 * dp), "y": _q(0.34 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(s_yl, "size", {"x": _q(0.80 - dp), "y": _q(min(2.0 * dp, 0.06 - dp)), "z": _q(0.70 - dp)})

    # sep y_high
    s_yh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support y_high"})
    ET.SubElement(s_yh, "boxfill").text = "solid"
    ET.SubElement(s_yh, "point", {"x": _q(1.20 + 0.5 * dp), "y": _q(0.40 - min(2.5 * dp, 0.06 - 0.5 * dp)), "z": _q(0.5 * dp)})
    ET.SubElement(s_yh, "size", {"x": _q(0.80 - dp), "y": _q(min(2.0 * dp, 0.06 - dp)), "z": _q(0.70 - dp)})

    # sep z_high
    s_zh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support z_high"})
    ET.SubElement(s_zh, "boxfill").text = "solid"
    ET.SubElement(s_zh, "point", {"x": _q(1.20 + 0.5 * dp), "y": _q(0.34 + 0.5 * dp), "z": _q(0.70 - 2.5 * dp)})
    ET.SubElement(s_zh, "size", {"x": _q(0.80 - dp), "y": _q(0.06 - dp), "z": _q(2.0 * dp)})

    # Fluid column (x in [2.20, 3.20], y in [0.00, 1.00], z in [0.00, 0.30])
    ET.SubElement(mainlist, "setmkfluid", {"mk": "0"})
    nx, ny, nz = res["counts_xyz"]
    b_fluid = ET.SubElement(mainlist, "drawbox", {"cmt": "v1 fallback controlled dual fluid cell centres"})
    ET.SubElement(b_fluid, "boxfill").text = "solid"
    ET.SubElement(b_fluid, "point", {"x": _q(2.20 + dp / 2), "y": _q(dp / 2), "z": _q(dp / 2)})
    ET.SubElement(b_fluid, "size", {"x": _q((nx - 1) * dp), "y": _q((ny - 1) * dp), "z": _q((nz - 1) * dp)})

    # Execution parameters
    execution = ET.SubElement(case, "execution")
    params = ET.SubElement(execution, "parameters")
    param_dict = {
        "Boundary": "1",
        "SavePosDouble": "1",
        "StepAlgorithm": "1",
        "VerletSteps": "40",
        "Kernel": "1",
        "ViscoTreatment": "1",
        "Visco": "0.1",
        "ViscoBoundFactor": "1",
        "DensityDT": "2",
        "DensityDTvalue": "0.1",
        "Shifting": "0",
        "RigidAlgorithm": "1",
        "FtPause": "0",
        "CoefDtMin": "0.05",
        "DtIni": "0",
        "DtMin": "0",
        "DtFixed": "0",
        "DtAllParticles": "0",
        "TimeMax": "4.0",
        "TimeOut": "0.01",
        "MinFluidStop": "0",
        "RhopOutMin": "700",
        "RhopOutMax": "1300",
    }
    for k, v in param_dict.items():
        ET.SubElement(params, "parameter", {"key": k, "value": v})

    simdom = ET.SubElement(params, "simulationdomain")
    ET.SubElement(simdom, "posmin", {"x": "default - 25%", "y": "default - 25%", "z": "default - 25%"})
    ET.SubElement(simdom, "posmax", {"x": "default + 25%", "y": "default + 25%", "z": "default + 75%"})

    return case


def build_metadata(cfg: dict[str, Any], res: dict[str, Any], def_path: Path, def_sha: str) -> dict[str, Any]:
    token = res["token"]
    dp = res["dp"]
    h0 = cfg["h0_m"]
    g = 9.81
    char_time = math.sqrt(h0 / g)
    char_vel = math.sqrt(2 * g * h0)
    event_budget = 0.02 * char_time
    save_budget = 0.2 * event_budget
    counts = res["counts_xyz"]
    fluid_particles = math.prod(counts)
    fluid_mass = fluid_particles * 1000.0 * (dp ** 3)

    case_id = f"{cfg['case_id_base']}_{token}"

    is_ecc = cfg["mechanism_id"] == "eccentric_obstacle"

    if is_ecc:
        geometry_spec = {
            "tank_length_m": cfg["tank_length_m"],
            "tank_width_m": cfg["tank_width_m"],
            "tank_height_m": cfg["tank_height_m"],
            "fluid_length_m": cfg["fluid_length_m"],
            "initial_depth_m": cfg["fluid_height_m"],
            "initial_fluid_volume_m3": cfg["fluid_length_m"] * cfg["fluid_width_m"] * cfg["fluid_height_m"],
            "obstacle_x_m": cfg["obstacle_x_m"],
            "obstacle_y_m": cfg["obstacle_y_m"],
            "obstacle_length_m": cfg["obstacle_length_m"],
            "obstacle_width_m": cfg["obstacle_width_m"],
            "obstacle_height_m": cfg["obstacle_height_m"],
            "open_top": True,
            "finite_wall_faces": ["bottom", "left", "right", "front", "back"],
        }
        phase_targets = {
            "release": 0.0,
            "first_obstacle_interaction": 0.40,
            "channel_transit": 0.60,
            "downstream_arrival": 0.85,
            "remerge_or_return_flow": 1.25,
            "window_end": cfg["time_max_s"],
        }
    else:
        geometry_spec = {
            "tank_length_m": cfg["tank_length_m"],
            "tank_width_m": cfg["tank_width_m"],
            "tank_height_m": cfg["tank_height_m"],
            "fluid_length_m": cfg["fluid_length_m"],
            "initial_depth_m": cfg["fluid_height_m"],
            "initial_fluid_volume_m3": cfg["fluid_length_m"] * cfg["fluid_width_m"] * cfg["fluid_height_m"],
            "separator_start_x_m": cfg["separator_x_start_m"],
            "separator_length_m": cfg["separator_length_m"],
            "separator_y_m": cfg["separator_y_start_m"],
            "separator_thickness_m": cfg["separator_thickness_m"],
            "separator_height_m": cfg["separator_height_m"],
            "channel_width_lower_m": 0.34,
            "channel_width_upper_m": 0.60,
            "channel_width_ratio_lower_to_upper": 0.34 / 0.60,
            "open_top": True,
            "finite_wall_faces": ["bottom", "left", "right", "front", "back", "separator_top", "separator_sides"],
        }
        phase_targets = {
            "release": 0.0,
            "first_separator_interaction": 0.35,
            "channel_exit_remerge": 1.00,
            "downstream_wall_impact": 1.40,
            "return_flow_observable": 2.60,
            "window_end": cfg["time_max_s"],
        }

    meta = {
        "schema": "ds02.f1.fallback.metadata.v1",
        "family_id": "F1",
        "case_id": case_id,
        "mechanism_id": cfg["mechanism_id"],
        "physical_case_id": cfg["physical_case_id"],
        "resolution_token": token,
        "dp_m": dp,
        "counts_xyz": list(counts),
        "fluid_particles": fluid_particles,
        "fluid_mass_kg": fluid_mass,
        "definition_path": str(def_path),
        "definition_sha256": def_sha,
        "generation_status": "definition_ready_for_root_gencase_preflight",
        "error_budget": {
            "macro_observable_relative_error": 0.05,
            "event_time_error_fraction_of_characteristic_time": 0.02,
            "event_time_error_absolute_seconds": event_budget,
            "save_quantization_budget_s": save_budget,
            "integration_fraction_of_total_error_budget_max": 0.2,
            "save_fraction_of_total_error_budget_max": 0.2,
            "event_time_scale": {
                "definition": "T=sqrt(H0/g)",
                "nominal_H0_m": h0,
                "characteristic_time_s": char_time,
                "characteristic_velocity_m_s": char_vel,
                "starting_absolute_budget_s": event_budget,
                "event_control_time_out_s": 0.001 if h0 >= 0.30 else 0.0005,
                "reference_matrix_time_out_s": 0.01,
            },
            "applicability": {
                "macro": "5% applies to fixed physical windows and volume-integrated/quantile observables once initial mass and geometry are within initialization budget.",
                "event_time": "2% applies to first-arrival/remerge/return markers scaled by sqrt(H0/g). Complete event control is required before timing qualification.",
            },
            "status": "prospective_physically_scaled_fallback_budget",
        },
        "event_window": {
            "characteristic_length_m": h0,
            "characteristic_time_s": char_time,
            "characteristic_velocity_m_s": char_vel,
            "complete_event_window_s": cfg["time_max_s"],
            "save_interval_s": 0.01,
            "phase_targets_s": phase_targets,
            "phase_basis": "front travel and remerge milestones are conservative registration targets; acceptance requires observed native data.",
        },
        "geometry": geometry_spec,
        "claim_boundary": {
            "q_n": "not_granted",
            "production_approval": "none",
            "policy": "Prospective fallback definition and preflight registration; no retrospective gate relaxation or claims from code/metadata alone.",
        },
    }
    return meta


def write_label_configs() -> dict[str, str]:
    LABELS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Eccentric obstacle label config
    ecc_label = {
        "schema": "ds-data-02.static-event-config.v1",
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "physical_case_id": "F1_FALLBACK_ECC_V1",
        "source_regions": [
            {
                "id": "initial_reservoir_lower",
                "bounds": [[-0.05, 0.45], [-0.05, 0.335], [-0.05, 0.20]],
            },
            {
                "id": "initial_reservoir_upper",
                "bounds": [[-0.05, 0.45], [0.335, 0.72], [-0.05, 0.20]],
            },
        ],
        "destination_regions": [
            {
                "id": "upstream",
                "bounds": [[0.0, 0.90], [0.0, 0.67], [0.0, 0.40]],
            },
            {
                "id": "lower_channel",
                "bounds": [[0.90, 1.02], [0.0, 0.24], [0.0, 0.40]],
            },
            {
                "id": "upper_channel",
                "bounds": [[0.90, 1.02], [0.36, 0.67], [0.0, 0.40]],
            },
            {
                "id": "downstream",
                "bounds": [[1.02, 1.60], [0.0, 0.67], [0.0, 0.40]],
            },
        ],
        "events": [
            {
                "id": "lower_channel_entry",
                "axis": 0,
                "value": 0.90,
                "aperture_bounds": [[0.0, 0.24], [0.0, 0.40]],
            },
            {
                "id": "upper_channel_entry",
                "axis": 0,
                "value": 0.90,
                "aperture_bounds": [[0.36, 0.67], [0.0, 0.40]],
            },
            {
                "id": "downstream_arrival",
                "axis": 0,
                "value": 1.20,
                "aperture_bounds": [[0.0, 0.67], [0.0, 0.40]],
            },
        ],
        "interpretation": "Canonical native destination and passage apertures for F1 eccentric obstacle fallback; unknown includes outside tank; no posthoc projection.",
        "claim_boundary": "Actual saved-chord labels only; no Q-N or production",
    }
    ecc_label_path = LABELS_DIR / "eccentric_fallback_event_config.json"
    with open(ecc_label_path, "w", encoding="utf-8") as f:
        f.write(canonical_json(ecc_label))

    # 2. Dual channel label config
    dual_label = {
        "schema": "ds-data-02.static-event-config.v1",
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "physical_case_id": "F1_FALLBACK_DUAL_V1",
        "source_regions": [
            {
                "id": "initial_reservoir_lower",
                "bounds": [[2.15, 3.25], [-0.05, 0.50], [-0.05, 0.35]],
            },
            {
                "id": "initial_reservoir_upper",
                "bounds": [[2.15, 3.25], [0.50, 1.05], [-0.05, 0.35]],
            },
        ],
        "destination_regions": [
            {
                "id": "upstream",
                "bounds": [[2.00, 3.20], [0.0, 1.00], [0.0, 0.80]],
            },
            {
                "id": "lower_channel",
                "bounds": [[1.20, 2.00], [0.0, 0.34], [0.0, 0.80]],
            },
            {
                "id": "upper_channel",
                "bounds": [[1.20, 2.00], [0.40, 1.00], [0.0, 0.80]],
            },
            {
                "id": "downstream",
                "bounds": [[0.00, 1.20], [0.0, 1.00], [0.0, 0.80]],
            },
        ],
        "events": [
            {
                "id": "lower_channel_entry",
                "axis": 0,
                "value": 2.00,
                "aperture_bounds": [[0.0, 0.34], [0.0, 0.80]],
            },
            {
                "id": "upper_channel_entry",
                "axis": 0,
                "value": 2.00,
                "aperture_bounds": [[0.40, 1.00], [0.0, 0.80]],
            },
            {
                "id": "downstream_remerge",
                "axis": 0,
                "value": 1.20,
                "aperture_bounds": [[0.0, 1.00], [0.0, 0.80]],
            },
            {
                "id": "downstream_arrival",
                "axis": 0,
                "value": 0.30,
                "aperture_bounds": [[0.0, 1.00], [0.0, 0.80]],
            },
        ],
        "interpretation": "Canonical native destination and passage apertures for F1 asymmetric dual-channel fallback; unknown includes outside tank; no posthoc projection.",
        "claim_boundary": "Actual saved-chord labels only; no Q-N or production",
    }
    dual_label_path = LABELS_DIR / "dual_channel_fallback_event_config.json"
    with open(dual_label_path, "w", encoding="utf-8") as f:
        f.write(canonical_json(dual_label))

    return {
        "eccentric": str(ecc_label_path),
        "dual": str(dual_label_path),
        "eccentric_sha256": sha256_file(ecc_label_path),
        "dual_sha256": sha256_file(dual_label_path),
    }


def write_runner_requests(definitions: list[dict[str, Any]]) -> list[Path]:
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    generated = []

    # Get real SHAs for static tools
    gencase_sha = sha256_file(GENCASE_BIN)
    solver_sha = sha256_file(SOLVER_BIN)
    strict_dispatch_sha = sha256_file(STRICT_DISPATCH_ENTRY)
    runtime_v2_sha = sha256_file(RUNTIME_V2_SCRIPT)
    python_sha = sha256_file(PYTHON_BIN)

    for item in definitions:
        case_id = item["case_id"]
        def_path = item["def_path"]
        meta_path = item["meta_path"]
        def_sha = item["def_sha"]
        meta_sha = item["meta_sha"]
        res = item["res"]
        cfg = item["cfg"]
        dp = res["dp"]
        token = res["token"]
        is_ecc = cfg["mechanism_id"] == "eccentric_obstacle"

        # 1. GenCase Preflight Request (CPU)
        attempt_id_gencase = f"root-{case_id.lower().replace('_', '-')}-gencase-preflight-001"
        gencase_req = {
            "schema": "ds02.runner.request.v2",
            "family_id": "F1",
            "case_id": case_id,
            "variant_id": "fallback-v1-commensurate",
            "resolution_token": token,
            "attempt_id": attempt_id_gencase,
            "kind": "cpu",
            "cpu_task_kind": "gencase",
            "cpu_threads": 4,
            "max_wall_seconds": 600,
            "estimated_storage_bytes": 1073741824,
            "cwd": WORKTREE_ROOT,
            "worktree_root": WORKTREE_ROOT,
            "command": [
                GENCASE_BIN,
                str(def_path),
                f"{{attempt_root}}/{case_id}",
                "-save:all",
            ],
            "input_files": [
                GENCASE_BIN,
                str(def_path),
                str(meta_path),
                STRICT_DISPATCH_ENTRY,
                RUNTIME_V2_SCRIPT,
            ],
            "input_hashes": {
                GENCASE_BIN: gencase_sha,
                str(def_path): def_sha,
                str(meta_path): meta_sha,
                STRICT_DISPATCH_ENTRY: strict_dispatch_sha,
                RUNTIME_V2_SCRIPT: runtime_v2_sha,
            },
            "raw_output_root": f"{DATA_ROOT}/families/F1/{case_id}/{attempt_id_gencase}",
            "purpose": f"Bounded CPU GenCase preflight verification for {case_id} ({token}, dp={dp}m); audits zero dropped particles and 3D solid DBC packing.",
            "parent_review_required": True,
            "q_n_status": "not_assessed",
            "production_claim": "none",
            "strict_dispatch": {
                "entrypoint": STRICT_DISPATCH_ENTRY,
                "entrypoint_sha256": strict_dispatch_sha,
                "runtime_v2": RUNTIME_V2_SCRIPT,
                "runtime_v2_sha256": runtime_v2_sha,
                "validation": "all input_files have matching input_hashes; strict guard and runtime are immutable inputs",
            },
            "physical_binding": {
                "physical_case_id": cfg["physical_case_id"],
                "mechanism_id": cfg["mechanism_id"],
                "continuous_fluid_mass_kg": item["fluid_mass"],
                "boundary_method": "DBC",
                "mass_normalization": "forbidden",
                "support_side_semantics": "outer outside tank; obstacle/separator inside continuous solid",
            },
            "expected_initial": {
                "fluid_particles": item["fluid_particles"],
                "fluid_mass_kg": item["fluid_mass"],
                "counts_xyz": list(res["counts_xyz"]),
                "dp_m": dp,
            },
        }

        gencase_req_path = REQUESTS_DIR / f"{case_id}_gencase_request.json"
        with open(gencase_req_path, "w", encoding="utf-8") as f:
            f.write(canonical_json(gencase_req))
        generated.append(gencase_req_path)

        # 2. Solver Execution Request (GPU, ready for shared runner)
        attempt_id_solver = f"root-{case_id.lower().replace('_', '-')}-solver-run-001"
        solver_req = {
            "schema": "ds02.runner.request.v2",
            "family_id": "F1",
            "case_id": case_id,
            "variant_id": "fallback-v1-commensurate",
            "resolution_token": token,
            "attempt_id": attempt_id_solver,
            "kind": "gpu",
            "cpu_task_kind": "solver",
            "cpu_threads": 1,
            "max_wall_seconds": 1800 if token != "FINE" else 3600,
            "estimated_storage_bytes": 8589934592 if token != "FINE" else 34359738368,
            "estimated_peak_gpu_mib": 4096 if token != "FINE" else 8192,
            "cwd": OFFICIAL_BIN_DIR,
            "worktree_root": WORKTREE_ROOT,
            "command": [
                SOLVER_BIN,
                f"{DATA_ROOT}/families/F1/{case_id}/{attempt_id_gencase}/{case_id}",
                f"{{attempt_root}}/{case_id}",
                f"-tmax:{cfg['time_max_s']}",
                "-tout:0.01",
            ],
            "input_files": [
                SOLVER_BIN,
                str(def_path),
                str(meta_path),
                STRICT_DISPATCH_ENTRY,
                RUNTIME_V2_SCRIPT,
            ],
            "input_hashes": {
                SOLVER_BIN: solver_sha,
                str(def_path): def_sha,
                str(meta_path): meta_sha,
                STRICT_DISPATCH_ENTRY: strict_dispatch_sha,
                RUNTIME_V2_SCRIPT: runtime_v2_sha,
            },
            "raw_output_root": f"{DATA_ROOT}/families/F1/{case_id}/{attempt_id_solver}",
            "purpose": f"Official GPU DualSPHysics solver complete-window simulation for {case_id} ({token}, tmax={cfg['time_max_s']}s); registered for Root strict dispatcher.",
            "parent_review_required": True,
            "q_n_status": "not_assessed",
            "production_claim": "none",
            "strict_dispatch": {
                "entrypoint": STRICT_DISPATCH_ENTRY,
                "entrypoint_sha256": strict_dispatch_sha,
                "runtime_v2": RUNTIME_V2_SCRIPT,
                "runtime_v2_sha256": runtime_v2_sha,
                "validation": "all input_files have matching input_hashes; strict guard and runtime are immutable inputs",
            },
            "physical_binding": {
                "physical_case_id": cfg["physical_case_id"],
                "mechanism_id": cfg["mechanism_id"],
                "continuous_fluid_mass_kg": item["fluid_mass"],
                "boundary_method": "DBC",
                "time_max_s": cfg["time_max_s"],
                "time_out_s": 0.01,
            },
        }

        solver_req_path = REQUESTS_DIR / f"{case_id}_solver_request.json"
        with open(solver_req_path, "w", encoding="utf-8") as f:
            f.write(canonical_json(solver_req))
        generated.append(solver_req_path)

    return generated


def main() -> None:
    DEFINITIONS_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/5] Writing canonical label configs...")
    label_info = write_label_configs()

    print("[2/5] Generating XML definitions and metadata sidecars...")
    definitions_record = []
    matrix_cases = []

    # Process Eccentric Obstacle Fallback
    for res in ECC_CONFIG["resolutions"]:
        token = res["token"]
        case_id = f"{ECC_CONFIG['case_id_base']}_{token}"
        xml_elem = build_ecc_xml(res)
        xml_path = DEFINITIONS_DIR / f"{case_id}_Def.xml"
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(prettify_xml(xml_elem))

        def_sha = sha256_file(xml_path)
        meta_dict = build_metadata(ECC_CONFIG, res, xml_path, def_sha)
        meta_path = DEFINITIONS_DIR / f"{case_id}.metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(canonical_json(meta_dict))
        meta_sha = sha256_file(meta_path)

        rec = {
            "case_id": case_id,
            "cfg": ECC_CONFIG,
            "res": res,
            "def_path": xml_path,
            "def_sha": def_sha,
            "meta_path": meta_path,
            "meta_sha": meta_sha,
            "fluid_particles": meta_dict["fluid_particles"],
            "fluid_mass": meta_dict["fluid_mass_kg"],
        }
        definitions_record.append(rec)
        matrix_cases.append({
            "case_id": case_id,
            "mechanism_id": ECC_CONFIG["mechanism_id"],
            "physical_case_id": ECC_CONFIG["physical_case_id"],
            "resolution_token": token,
            "dp_m": res["dp"],
            "fluid_particles": meta_dict["fluid_particles"],
            "fluid_mass_kg": meta_dict["fluid_mass_kg"],
            "definition_sha256": def_sha,
            "metadata_sha256": meta_sha,
        })
        print(f"  - Generated {case_id}: {meta_dict['fluid_particles']} particles, {meta_dict['fluid_mass_kg']:.3f} kg (dp={res['dp']})")

    # Process Dual Channel Fallback
    for res in DUAL_CONFIG["resolutions"]:
        token = res["token"]
        case_id = f"{DUAL_CONFIG['case_id_base']}_{token}"
        xml_elem = build_dual_xml(res)
        xml_path = DEFINITIONS_DIR / f"{case_id}_Def.xml"
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(prettify_xml(xml_elem))

        def_sha = sha256_file(xml_path)
        meta_dict = build_metadata(DUAL_CONFIG, res, xml_path, def_sha)
        meta_path = DEFINITIONS_DIR / f"{case_id}.metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(canonical_json(meta_dict))
        meta_sha = sha256_file(meta_path)

        rec = {
            "case_id": case_id,
            "cfg": DUAL_CONFIG,
            "res": res,
            "def_path": xml_path,
            "def_sha": def_sha,
            "meta_path": meta_path,
            "meta_sha": meta_sha,
            "fluid_particles": meta_dict["fluid_particles"],
            "fluid_mass": meta_dict["fluid_mass_kg"],
        }
        definitions_record.append(rec)
        matrix_cases.append({
            "case_id": case_id,
            "mechanism_id": DUAL_CONFIG["mechanism_id"],
            "physical_case_id": DUAL_CONFIG["physical_case_id"],
            "resolution_token": token,
            "dp_m": res["dp"],
            "fluid_particles": meta_dict["fluid_particles"],
            "fluid_mass_kg": meta_dict["fluid_mass_kg"],
            "definition_sha256": def_sha,
            "metadata_sha256": meta_sha,
        })
        print(f"  - Generated {case_id}: {meta_dict['fluid_particles']} particles, {meta_dict['fluid_mass_kg']:.3f} kg (dp={res['dp']})")

    # Write Reference Matrix
    print("[3/5] Writing fallback reference matrix...")
    ref_matrix = {
        "schema": "ds02.f1.fallback.reference-matrix.v1",
        "family_id": "F1",
        "legal_fallback_pair": {
            "eccentric_obstacle": {
                "physical_case_id": "F1_FALLBACK_ECC_V1",
                "h0_m": 0.150,
                "mass_kg": 40.200,
                "time_max_s": 1.60,
                "char_time_s": math.sqrt(0.150 / 9.81),
                "event_budget_s": 0.02 * math.sqrt(0.150 / 9.81),
                "macro_budget": 0.05,
                "cases": [c for c in matrix_cases if c["mechanism_id"] == "eccentric_obstacle"],
            },
            "asymmetric_dual_channel": {
                "physical_case_id": "F1_FALLBACK_DUAL_V1",
                "h0_m": 0.300,
                "mass_kg": 300.000,
                "time_max_s": 4.00,
                "char_time_s": math.sqrt(0.300 / 9.81),
                "event_budget_s": 0.02 * math.sqrt(0.300 / 9.81),
                "macro_budget": 0.05,
                "cases": [c for c in matrix_cases if c["mechanism_id"] == "asymmetric_dual_channel"],
            },
        },
        "all_cases": matrix_cases,
        "labels": label_info,
    }
    matrix_path = DEFINITIONS_DIR / "fallback_reference_matrix.json"
    with open(matrix_path, "w", encoding="utf-8") as f:
        f.write(canonical_json(ref_matrix))

    print("[4/5] Authoring Root strict dispatcher runner requests...")
    requests_generated = write_runner_requests(definitions_record)
    print(f"  - Generated {len(requests_generated)} runner requests.")

    print("[5/5] Generating manifest...")
    manifest = {
        "schema": "ds02.f1.bounded-fallback-v1.manifest",
        "scope": "handoff_20261003/root_followup_041_bounded_fallback_v1",
        "family_id": "F1",
        "pair_count": 1,
        "mechanisms": ["eccentric_obstacle", "asymmetric_dual_channel"],
        "physical_cases": ["F1_FALLBACK_ECC_V1", "F1_FALLBACK_DUAL_V1"],
        "resolution_tiers": 3,
        "total_registered_cases": len(matrix_cases),
        "reference_matrix": str(matrix_path),
        "reference_matrix_sha256": sha256_file(matrix_path),
        "definitions": [
            {
                "case_id": rec["case_id"],
                "definition": str(rec["def_path"]),
                "definition_sha256": rec["def_sha"],
                "metadata": str(rec["meta_path"]),
                "metadata_sha256": rec["meta_sha"],
            }
            for rec in definitions_record
        ],
        "labels": label_info,
        "requests": [str(p) for p in requests_generated],
        "claim_boundary": "prospective authoring and synthetic tests only; all scientific generation pending Root strict dispatcher guard",
    }
    manifest_path = BASE_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(canonical_json(manifest))

    print(f"[Done] Handoff scope manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
