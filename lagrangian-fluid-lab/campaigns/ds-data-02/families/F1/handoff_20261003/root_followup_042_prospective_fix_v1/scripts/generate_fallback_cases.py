#!/usr/bin/env python3
"""Programmatic generator for Family F1 Followup 042 prospective fallback suite.

Generates:
1. 6 XML definitions using proven thick DBC solid slabs from root_thick_dbc.
2. 6 definition metadata JSONs separating predicted vs actuals, reporting native weights.
3. Updated fallback_reference_matrix.json retracting unsupported claims and unauthorized gate.
4. 2 label event configurations preserving existing native operators and unknown codes.
5. 6 GenCase preflight runner requests (schema: ds02.runner-request.v2, -threads:4 matching reservation).
6. 6 prospective solver runner requests (schema: ds02.runner-request.v2, launch_allowed: false).
7. Comprehensive manifest.json.
"""

from __future__ import annotations

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
PYTHON_BIN = f"{WORKTREE_ROOT}/lagrangian-fluid-lab/.venv/bin/python"
STRICT_DISPATCH_ENTRY = f"{INTEGRATION_ROOT}/lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
RUNTIME_V2_SCRIPT = f"{INTEGRATION_ROOT}/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PREPWORKER_SCRIPT = f"{SCRIPTS_DIR}/rootguard_prepworker.py"


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def compute_native_particle_weight(rho0: float, dp: float) -> float:
    """Compute single-precision float32 native weight matching DualSPHysics representation."""
    import struct
    exact_continuous = rho0 * (dp ** 3)
    packed = struct.pack("f", float(exact_continuous))
    return struct.unpack("f", packed)[0]


def _q(value: float) -> str:
    return format(float(value), ".16g")


ECC_CONFIG: dict[str, Any] = {
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
        {"token": "FINE", "dp": 1.0 / 300.0, "counts_xyz": (120, 201, 45)},
    ],
}

DUAL_CONFIG: dict[str, Any] = {
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
    ET.SubElement(mainlist, "setdrawmode", {"mode": "full"})
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
    o_xl = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support x_low"})
    ET.SubElement(o_xl, "boxfill").text = "solid"
    ET.SubElement(o_xl, "point", {"x": _q(0.90 + 0.5 * dp), "y": _q(0.24 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(o_xl, "size", {"x": _q(2.0 * dp), "y": _q(0.12 - dp), "z": _q(0.45 - dp)})

    o_xh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support x_high"})
    ET.SubElement(o_xh, "boxfill").text = "solid"
    ET.SubElement(o_xh, "point", {"x": _q(1.02 - 2.5 * dp), "y": _q(0.24 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(o_xh, "size", {"x": _q(2.0 * dp), "y": _q(0.12 - dp), "z": _q(0.45 - dp)})

    o_yl = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support y_low"})
    ET.SubElement(o_yl, "boxfill").text = "solid"
    ET.SubElement(o_yl, "point", {"x": _q(0.90 + 0.5 * dp), "y": _q(0.24 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(o_yl, "size", {"x": _q(0.12 - dp), "y": _q(2.0 * dp), "z": _q(0.45 - dp)})

    o_yh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick obstacle support y_high"})
    ET.SubElement(o_yh, "boxfill").text = "solid"
    ET.SubElement(o_yh, "point", {"x": _q(0.90 + 0.5 * dp), "y": _q(0.36 - 2.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(o_yh, "size", {"x": _q(0.12 - dp), "y": _q(2.0 * dp), "z": _q(0.45 - dp)})

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
    ET.SubElement(mainlist, "setdrawmode", {"mode": "full"})
    ET.SubElement(mainlist, "setmkbound", {"mk": "0"})

    # Outer wall slabs (5 faces)
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
    ET.SubElement(mainlist, "setmkvoid")
    b_sep_v = ET.SubElement(mainlist, "drawbox", {"cmt": "asymmetric channel divider physical solid"})
    ET.SubElement(b_sep_v, "boxfill").text = "solid"
    ET.SubElement(b_sep_v, "point", {"x": "1.2", "y": "0.34", "z": "0"})
    ET.SubElement(b_sep_v, "size", {"x": "0.8", "y": "0.06", "z": "0.7"})

    # Separator internal support slabs (5 faces)
    ET.SubElement(mainlist, "setmkbound", {"mk": "1"})
    s_xl = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support x_low"})
    ET.SubElement(s_xl, "boxfill").text = "solid"
    ET.SubElement(s_xl, "point", {"x": _q(1.20 + 0.5 * dp), "y": _q(0.34 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(s_xl, "size", {"x": _q(2.0 * dp), "y": _q(0.06 - dp), "z": _q(0.70 - dp)})

    s_xh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support x_high"})
    ET.SubElement(s_xh, "boxfill").text = "solid"
    ET.SubElement(s_xh, "point", {"x": _q(2.00 - 2.5 * dp), "y": _q(0.34 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(s_xh, "size", {"x": _q(2.0 * dp), "y": _q(0.06 - dp), "z": _q(0.70 - dp)})

    s_yl = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support y_low"})
    ET.SubElement(s_yl, "boxfill").text = "solid"
    ET.SubElement(s_yl, "point", {"x": _q(1.20 + 0.5 * dp), "y": _q(0.34 + 0.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(s_yl, "size", {"x": _q(0.80 - dp), "y": _q(2.0 * dp), "z": _q(0.70 - dp)})

    s_yh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support y_high"})
    ET.SubElement(s_yh, "boxfill").text = "solid"
    ET.SubElement(s_yh, "point", {"x": _q(1.20 + 0.5 * dp), "y": _q(0.40 - 2.5 * dp), "z": _q(0.5 * dp)})
    ET.SubElement(s_yh, "size", {"x": _q(0.80 - dp), "y": _q(2.0 * dp), "z": _q(0.70 - dp)})

    s_zh = ET.SubElement(mainlist, "drawbox", {"cmt": "v3 thick separator support z_high"})
    ET.SubElement(s_zh, "boxfill").text = "solid"
    ET.SubElement(s_zh, "point", {"x": _q(1.20 + 0.5 * dp), "y": _q(0.34 + 0.5 * dp), "z": _q(0.70 - 2.5 * dp)})
    ET.SubElement(s_zh, "size", {"x": _q(0.80 - dp), "y": _q(0.06 - dp), "z": _q(2.0 * dp)})

    # Fluid column (controlled depth H0 = 0.30m)
    ET.SubElement(mainlist, "setmkfluid", {"mk": "0"})
    nx, ny, nz = res["counts_xyz"]
    b_fluid = ET.SubElement(mainlist, "drawbox", {"cmt": "v1 fallback controlled fluid cell centres"})
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


def format_xml(elem: ET.Element) -> str:
    raw = ET.tostring(elem, encoding="utf-8")
    parsed = minidom.parseString(raw)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def generate_all() -> None:
    DEFINITIONS_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    cases_meta: list[dict[str, Any]] = []

    # 1. Generate XML definitions and metadata for ECC
    for res in ECC_CONFIG["resolutions"]:
        cid = f"F1_FALLBACK_ECC_{res['token']}"
        xml_elem = build_ecc_xml(res)
        xml_content = format_xml(xml_elem)
        xml_path = DEFINITIONS_DIR / f"{cid}_Def.xml"
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml_content)

        xml_sha = sha256_file(xml_path)
        dp = res["dp"]
        counts = res["counts_xyz"]
        n_fluid = counts[0] * counts[1] * counts[2]
        vol = ECC_CONFIG["fluid_length_m"] * ECC_CONFIG["fluid_width_m"] * ECC_CONFIG["fluid_height_m"]
        mass = 1000.0 * vol
        native_w = compute_native_particle_weight(1000.0, dp)

        # Scale error budgets
        t_char = math.sqrt(ECC_CONFIG["h0_m"] / 9.81)
        event_time_budget = 0.02 * t_char
        save_budget = 0.20 * 0.01 * (t_char / 0.12365484170737448)  # scaled save fraction

        meta = {
            "schema": "ds02.f1.fallback.metadata.v2",
            "case_id": cid,
            "mechanism_id": ECC_CONFIG["mechanism_id"],
            "physical_case_id": ECC_CONFIG["physical_case_id"],
            "resolution_token": res["token"],
            "dp_m": dp,
            "definition_path": str(xml_path),
            "definition_sha256": xml_sha,
            "predictions": {
                "counts_xyz": list(counts),
                "predicted_fluid_particles": n_fluid,
                "theoretical_fluid_volume_m3": vol,
                "theoretical_fluid_mass_kg": mass,
                "native_weight_float32_kg": native_w,
            },
            "actual": {
                "status": "pending_rootguard_gencase_preflight",
                "actual_particles": None,
                "note": "Actual particles and execution evidence are registered strictly under Rootguard dispatch.",
            },
            "transverse_effect_descriptor": (
                "Transverse velocity vy(x,y,z,t) and lateral deflection are descriptive observables "
                "characterizing 3D asymmetric diversion; no arbitrary pass/fail velocity threshold or gate is authorized."
            ),
            "native_weights_representation": (
                "Native particle weights are stored in IEEE 754 single-precision float32 (massfluid in DualSPHysics); "
                "actual typed QA evaluates native weights from GenCase/BI4, rather than decimal rho*dp^3 exact string invariance."
            ),
            "event_window": {
                "characteristic_length_m": ECC_CONFIG["h0_m"],
                "characteristic_time_s": t_char,
                "characteristic_velocity_m_s": math.sqrt(9.81 * ECC_CONFIG["h0_m"]),
                "complete_event_window_s": ECC_CONFIG["time_max_s"],
                "save_interval_s": 0.01,
            },
            "error_budget": {
                "status": "prospective_physically_scaled_fallback_budget",
                "event_time_error_fraction_of_characteristic_time": 0.02,
                "event_time_error_absolute_seconds": event_time_budget,
                "save_fraction_of_total_error_budget_max": 0.20,
                "save_quantization_budget_s": save_budget,
                "macro_observable_relative_error": 0.05,
                "integration_fraction_of_total_error_budget_max": 0.20,
            },
            "geometry": {
                "open_top": True,
                "tank_length_m": ECC_CONFIG["tank_length_m"],
                "tank_width_m": ECC_CONFIG["tank_width_m"],
                "tank_height_m": ECC_CONFIG["tank_height_m"],
                "fluid_length_m": ECC_CONFIG["fluid_length_m"],
                "initial_depth_m": ECC_CONFIG["h0_m"],
                "obstacle_x_m": ECC_CONFIG["obstacle_x_m"],
                "obstacle_y_m": ECC_CONFIG["obstacle_y_m"],
                "obstacle_length_m": ECC_CONFIG["obstacle_length_m"],
                "obstacle_width_m": ECC_CONFIG["obstacle_width_m"],
                "obstacle_height_m": ECC_CONFIG["obstacle_height_m"],
                "finite_wall_faces": ["bottom", "left", "right", "front", "back"],
            },
            "claim_boundary": {
                "q_n": "not_granted",
                "production_approval": "none",
                "policy": "Prospective fallback definition and preflight registration; no retrospective gate relaxation or claims from code/metadata alone.",
            },
        }

        meta_path = DEFINITIONS_DIR / f"{cid}.metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        cases_meta.append(meta)

    # 2. Generate XML definitions and metadata for DUAL
    for res in DUAL_CONFIG["resolutions"]:
        cid = f"F1_FALLBACK_DUAL_{res['token']}"
        xml_elem = build_dual_xml(res)
        xml_content = format_xml(xml_elem)
        xml_path = DEFINITIONS_DIR / f"{cid}_Def.xml"
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml_content)

        xml_sha = sha256_file(xml_path)
        dp = res["dp"]
        counts = res["counts_xyz"]
        n_fluid = counts[0] * counts[1] * counts[2]
        vol = DUAL_CONFIG["fluid_length_m"] * DUAL_CONFIG["fluid_width_m"] * DUAL_CONFIG["fluid_height_m"]
        mass = 1000.0 * vol
        native_w = compute_native_particle_weight(1000.0, dp)

        # Scale error budgets
        t_char = math.sqrt(DUAL_CONFIG["h0_m"] / 9.81)
        event_time_budget = 0.02 * t_char
        save_budget = 0.20 * 0.01 * (t_char / 0.174874)

        meta = {
            "schema": "ds02.f1.fallback.metadata.v2",
            "case_id": cid,
            "mechanism_id": DUAL_CONFIG["mechanism_id"],
            "physical_case_id": DUAL_CONFIG["physical_case_id"],
            "resolution_token": res["token"],
            "dp_m": dp,
            "definition_path": str(xml_path),
            "definition_sha256": xml_sha,
            "predictions": {
                "counts_xyz": list(counts),
                "predicted_fluid_particles": n_fluid,
                "theoretical_fluid_volume_m3": vol,
                "theoretical_fluid_mass_kg": mass,
                "native_weight_float32_kg": native_w,
            },
            "actual": {
                "status": "pending_rootguard_gencase_preflight",
                "actual_particles": None,
                "note": "Actual particles and execution evidence are registered strictly under Rootguard dispatch.",
            },
            "transverse_effect_descriptor": (
                "Transverse velocity vy(x,y,z,t) and lateral deflection are descriptive observables "
                "characterizing 3D asymmetric diversion; no arbitrary pass/fail velocity threshold or gate is authorized."
            ),
            "native_weights_representation": (
                "Native particle weights are stored in IEEE 754 single-precision float32 (massfluid in DualSPHysics); "
                "actual typed QA evaluates native weights from GenCase/BI4, rather than decimal rho*dp^3 exact string invariance."
            ),
            "event_window": {
                "characteristic_length_m": DUAL_CONFIG["h0_m"],
                "characteristic_time_s": t_char,
                "characteristic_velocity_m_s": math.sqrt(9.81 * DUAL_CONFIG["h0_m"]),
                "complete_event_window_s": DUAL_CONFIG["time_max_s"],
                "save_interval_s": 0.01,
            },
            "error_budget": {
                "status": "prospective_physically_scaled_fallback_budget",
                "event_time_error_fraction_of_characteristic_time": 0.02,
                "event_time_error_absolute_seconds": event_time_budget,
                "save_fraction_of_total_error_budget_max": 0.20,
                "save_quantization_budget_s": save_budget,
                "macro_observable_relative_error": 0.05,
                "integration_fraction_of_total_error_budget_max": 0.20,
            },
            "geometry": {
                "open_top": True,
                "tank_length_m": DUAL_CONFIG["tank_length_m"],
                "tank_width_m": DUAL_CONFIG["tank_width_m"],
                "tank_height_m": DUAL_CONFIG["tank_height_m"],
                "fluid_length_m": DUAL_CONFIG["fluid_length_m"],
                "initial_depth_m": DUAL_CONFIG["h0_m"],
                "separator_x_start_m": DUAL_CONFIG["separator_x_start_m"],
                "separator_length_m": DUAL_CONFIG["separator_length_m"],
                "separator_y_start_m": DUAL_CONFIG["separator_y_start_m"],
                "separator_thickness_m": DUAL_CONFIG["separator_thickness_m"],
                "separator_height_m": DUAL_CONFIG["separator_height_m"],
                "finite_wall_faces": ["bottom", "left", "right", "front", "back"],
            },
            "claim_boundary": {
                "q_n": "not_granted",
                "production_approval": "none",
                "policy": "Prospective fallback definition and preflight registration; no retrospective gate relaxation or claims from code/metadata alone.",
            },
        }

        meta_path = DEFINITIONS_DIR / f"{cid}.metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        cases_meta.append(meta)

    # 3. Generate fallback_reference_matrix.json
    matrix = {
        "schema": "ds02.f1.fallback-reference-matrix.v2",
        "campaign": "DS-DATA-02",
        "family": "F1",
        "specification_status": "prospective_physical_fallback_v1",
        "claim_boundary": {
            "q_n": "not_granted",
            "production_approval": "none",
            "policy": "Prospective fallback pair and preflight suite; claims require observed native data.",
            "unsupported_claims_retracted": [
                "reducing H proves 75% peak kinetic suppression",
                "laminar stable stagnation",
                "guaranteed no fate switches / no overtopping / NpOut = 0",
                "invented |vy|max > 0.4 m/s gate",
            ],
        },
        "legal_fallback_pair": {
            "eccentric_obstacle": {
                "physical_case_id": "F1_FALLBACK_ECC_V1",
                "mechanism_id": "eccentric_obstacle",
                "controlled_depth_H0_m": 0.150,
                "characteristic_time_s": math.sqrt(0.150 / 9.81),
                "time_max_s": 1.60,
                "transverse_effect_descriptor": (
                    "Observational descriptive indicator characterizing 3D transverse diversion; "
                    "no arbitrary pass/fail gate authorized."
                ),
                "native_weights_reporting": "Stored in IEEE 754 float32 massfluid; actual typed QA evaluates native weights.",
                "cases": [
                    {
                        "case_id": "F1_FALLBACK_ECC_COARSE",
                        "resolution_token": "COARSE",
                        "dp_m": 0.010,
                        "counts_xyz": [40, 67, 15],
                        "predicted_fluid_particles": 40200,
                        "theoretical_mass_kg": 40.200,
                        "native_weight_float32_kg": compute_native_particle_weight(1000.0, 0.010),
                    },
                    {
                        "case_id": "F1_FALLBACK_ECC_MEDIUM",
                        "resolution_token": "MEDIUM",
                        "dp_m": 0.005,
                        "counts_xyz": [80, 134, 30],
                        "predicted_fluid_particles": 321600,
                        "theoretical_mass_kg": 40.200,
                        "native_weight_float32_kg": compute_native_particle_weight(1000.0, 0.005),
                    },
                    {
                        "case_id": "F1_FALLBACK_ECC_FINE",
                        "resolution_token": "FINE",
                        "dp_m": 1.0 / 300.0,
                        "counts_xyz": [120, 201, 45],
                        "predicted_fluid_particles": 1085400,
                        "theoretical_mass_kg": 40.200,
                        "native_weight_float32_kg": compute_native_particle_weight(1000.0, 1.0 / 300.0),
                    },
                ],
            },
            "asymmetric_dual_channel": {
                "physical_case_id": "F1_FALLBACK_DUAL_V1",
                "mechanism_id": "asymmetric_dual_channel",
                "controlled_depth_H0_m": 0.300,
                "characteristic_time_s": math.sqrt(0.300 / 9.81),
                "time_max_s": 4.00,
                "transverse_effect_descriptor": (
                    "Observational descriptive indicator characterizing 3D transverse diversion; "
                    "no arbitrary pass/fail gate authorized."
                ),
                "native_weights_reporting": "Stored in IEEE 754 float32 massfluid; actual typed QA evaluates native weights.",
                "cases": [
                    {
                        "case_id": "F1_FALLBACK_DUAL_COARSE",
                        "resolution_token": "COARSE",
                        "dp_m": 0.020,
                        "counts_xyz": [50, 50, 15],
                        "predicted_fluid_particles": 37500,
                        "theoretical_mass_kg": 300.000,
                        "native_weight_float32_kg": compute_native_particle_weight(1000.0, 0.020),
                    },
                    {
                        "case_id": "F1_FALLBACK_DUAL_MEDIUM",
                        "resolution_token": "MEDIUM",
                        "dp_m": 0.010,
                        "counts_xyz": [100, 100, 30],
                        "predicted_fluid_particles": 300000,
                        "theoretical_mass_kg": 300.000,
                        "native_weight_float32_kg": compute_native_particle_weight(1000.0, 0.010),
                    },
                    {
                        "case_id": "F1_FALLBACK_DUAL_FINE",
                        "resolution_token": "FINE",
                        "dp_m": 0.005,
                        "counts_xyz": [200, 200, 60],
                        "predicted_fluid_particles": 2400000,
                        "theoretical_mass_kg": 300.000,
                        "native_weight_float32_kg": compute_native_particle_weight(1000.0, 0.005),
                    },
                ],
            },
        },
        "budget_policy": {
            "event_time_fraction": 0.02,
            "save_quantization_fraction": 0.20,
            "macro_observable_relative_error": 0.05,
            "integration_share": 0.20,
            "time_macro_fraction": 0.01,
        },
    }
    matrix_path = DEFINITIONS_DIR / "fallback_reference_matrix.json"
    with open(matrix_path, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=2)

    # 4. Generate label event configs in labels/
    # ECC event config
    ecc_labels = {
        "schema": "ds-data-02.static-event-config.v1",
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "geometry_source": "Actual source typed geometry binding; continuous tank, reservoir, obstacle and finite observation apertures preserved",
        "physical_case_id": "F1_FALLBACK_ECC_V1",
        "source_regions": [
            {"id": "initial_lower_half", "bounds": [[-0.1, 1.7], [-0.1, 0.335], [-0.1, 0.6]]},
            {"id": "initial_upper_half", "bounds": [[-0.1, 1.7], [0.335, 0.77], [-0.1, 0.6]]},
        ],
        "destination_regions": [
            {"id": "upstream", "bounds": [[0.0, 0.90], [0.0, 0.67], [0.0, 0.40]]},
            {"id": "lower_channel", "bounds": [[0.90, 1.02], [0.0, 0.24], [0.0, 0.40]]},
            {"id": "upper_channel", "bounds": [[0.90, 1.02], [0.36, 0.67], [0.0, 0.40]]},
            {"id": "downstream", "bounds": [[1.02, 1.60], [0.0, 0.67], [0.0, 0.40]]},
        ],
        "events": [
            {"id": "lower_channel_entry", "axis": 0, "value": 0.90, "aperture_bounds": [[0.0, 0.24], [0.0, 0.40]]},
            {"id": "upper_channel_entry", "axis": 0, "value": 0.90, "aperture_bounds": [[0.36, 0.67], [0.0, 0.40]]},
            {"id": "downstream_arrival", "axis": 0, "value": 1.20, "aperture_bounds": [[0.0, 0.67], [0.0, 0.40]]},
        ],
        "interpretation": "static finite wall/channel dimensions from continuous Definition; unknown includes outside or unresolved regions; no posthoc projection",
        "limitations": [
            "closed-wall and legal-open-exit causal classification pending geometry evaluator",
            "first passage is any-direction first observed saved chord",
            "residence and hidden recrossing errors require saved-cadence study",
        ],
        "claim_boundary": "Actual saved-chord labels only; no Q-N or production",
    }
    ecc_label_path = LABELS_DIR / "eccentric_fallback_event_config.json"
    with open(ecc_label_path, "w", encoding="utf-8") as f:
        json.dump(ecc_labels, f, indent=2)

    # DUAL event config
    dual_labels = {
        "schema": "ds-data-02.static-event-config.v1",
        "frame_kind": "fixed_solver_frame",
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "geometry_source": "Actual source typed geometry binding; continuous tank, reservoir, dividing wall and finite observation apertures preserved",
        "physical_case_id": "F1_FALLBACK_DUAL_V1",
        "source_regions": [
            {"id": "initial_lower_half", "bounds": [[2.1, 3.3], [-0.1, 0.37], [-0.1, 0.4]]},
            {"id": "initial_upper_half", "bounds": [[2.1, 3.3], [0.37, 1.1], [-0.1, 0.4]]},
        ],
        "destination_regions": [
            {"id": "upstream", "bounds": [[2.00, 3.20], [0.0, 1.00], [0.0, 0.80]]},
            {"id": "lower_channel", "bounds": [[1.20, 2.00], [0.0, 0.34], [0.0, 0.80]]},
            {"id": "upper_channel", "bounds": [[1.20, 2.00], [0.40, 1.00], [0.0, 0.80]]},
            {"id": "downstream", "bounds": [[0.00, 1.20], [0.0, 1.00], [0.0, 0.80]]},
        ],
        "events": [
            {"id": "lower_channel_entry", "axis": 0, "value": 2.00, "aperture_bounds": [[0.0, 0.34], [0.0, 0.80]]},
            {"id": "upper_channel_entry", "axis": 0, "value": 2.00, "aperture_bounds": [[0.40, 1.00], [0.0, 0.80]]},
            {"id": "downstream_remerge", "axis": 0, "value": 1.20, "aperture_bounds": [[0.0, 1.00], [0.0, 0.80]]},
            {"id": "downstream_arrival", "axis": 0, "value": 0.30, "aperture_bounds": [[0.0, 1.00], [0.0, 0.80]]},
        ],
        "interpretation": "static finite wall/channel dimensions from continuous Definition; unknown includes outside or unresolved regions; no posthoc projection",
        "limitations": [
            "closed-wall and legal-open-exit causal classification pending geometry evaluator",
            "first passage is any-direction first observed saved chord",
            "residence and hidden recrossing errors require saved-cadence study",
        ],
        "claim_boundary": "Actual saved-chord labels only; no Q-N or production",
    }
    dual_label_path = LABELS_DIR / "dual_channel_fallback_event_config.json"
    with open(dual_label_path, "w", encoding="utf-8") as f:
        json.dump(dual_labels, f, indent=2)

    # 5. Generate runner requests in requests/
    # Hashes of immutable scripts and binaries
    python_sha = sha256_file(PYTHON_BIN)
    strict_sha = sha256_file(STRICT_DISPATCH_ENTRY)
    runtime_sha = sha256_file(RUNTIME_V2_SCRIPT)
    prepworker_sha = sha256_file(PREPWORKER_SCRIPT)
    gencase_sha = sha256_file(GENCASE_BIN)
    solver_sha = sha256_file(SOLVER_BIN)

    for meta in cases_meta:
        cid = meta["case_id"]
        xml_path = Path(meta["definition_path"])
        meta_path = DEFINITIONS_DIR / f"{cid}.metadata.json"
        slug = cid.lower().replace("_", "-")

        # 5a. GenCase preflight runner request
        gencase_req_id = f"root-{slug}-gencase-preflight-001"
        gencase_inputs = [
            PYTHON_BIN,
            PREPWORKER_SCRIPT,
            str(xml_path),
            str(meta_path),
            GENCASE_BIN,
            STRICT_DISPATCH_ENTRY,
            RUNTIME_V2_SCRIPT,
        ]
        gencase_input_sha = {
            PYTHON_BIN: python_sha,
            PREPWORKER_SCRIPT: prepworker_sha,
            str(xml_path): sha256_file(xml_path),
            str(meta_path): sha256_file(meta_path),
            GENCASE_BIN: gencase_sha,
            STRICT_DISPATCH_ENTRY: strict_sha,
            RUNTIME_V2_SCRIPT: runtime_sha,
        }

        gencase_req = {
            "schema": "ds02.runner-request.v2",
            "family_id": "F1",
            "case_id": cid,
            "attempt_id": gencase_req_id,
            "kind": "cpu",
            "cpu_task_kind": "gencase",
            "cpu_threads": 4,
            "max_wall_seconds": 600,
            "estimated_storage_bytes": 1073741824,
            "cwd": WORKTREE_ROOT,
            "worktree_root": WORKTREE_ROOT,
            "command": [
                PYTHON_BIN,
                PREPWORKER_SCRIPT,
                "--case-id",
                cid,
                "--attempt-root",
                "{attempt_root}",
                "--threads",
                "4",
            ],
            "independent_case_count_increment": 0,
            "production_approval": "none",
            "launch_allowed": False,
            "launch_owner": "root",
            "input_files": gencase_inputs,
            "input_sha256": gencase_input_sha,
            "predictions": meta["predictions"],
            "strict_dispatch": {
                "entrypoint": STRICT_DISPATCH_ENTRY,
                "entrypoint_sha256": strict_sha,
                "runtime_v2": RUNTIME_V2_SCRIPT,
                "runtime_v2_sha256": runtime_sha,
            },
        }

        gencase_req_path = REQUESTS_DIR / f"{cid}_gencase_request.json"
        with open(gencase_req_path, "w", encoding="utf-8") as f:
            json.dump(gencase_req, f, indent=2)

        # 5b. Solver runner request
        solver_req_id = f"root-{slug}-solver-qualification-001"
        gpu_mib = 1024 if meta["resolution_token"] == "COARSE" else (2048 if meta["resolution_token"] == "MEDIUM" else 4096)
        wall_sec = 1800 if meta["resolution_token"] == "COARSE" else (3600 if meta["resolution_token"] == "MEDIUM" else 7200)

        solver_req = {
            "schema": "ds02.runner-request.v2",
            "family_id": "F1",
            "case_id": cid,
            "attempt_id": solver_req_id,
            "kind": "qualification",
            "launch_allowed": False,
            "launch_owner": "root",
            "production_approval": "none",
            "independent_case_count_increment": 0,
            "estimated_peak_gpu_mib": gpu_mib,
            "max_wall_seconds": wall_sec,
            "estimated_storage_bytes": 10737418240,
            "cwd": WORKTREE_ROOT,
            "worktree_root": WORKTREE_ROOT,
            "command": [
                SOLVER_BIN,
                f"{{attempt_root}}/{cid}",
                "{attempt_root}",
                "-dirdataout",
                "data",
            ],
            "input_files": [
                SOLVER_BIN,
                str(xml_path),
                str(meta_path),
                STRICT_DISPATCH_ENTRY,
                RUNTIME_V2_SCRIPT,
            ],
            "input_sha256": {
                SOLVER_BIN: solver_sha,
                str(xml_path): sha256_file(xml_path),
                str(meta_path): sha256_file(meta_path),
                STRICT_DISPATCH_ENTRY: strict_sha,
                RUNTIME_V2_SCRIPT: runtime_sha,
            },
            "full_mother_window_s": meta["event_window"]["complete_event_window_s"],
            "status": "prospective_solver_request_ready_for_rootguard_dispatch_after_gencase_preflight",
        }

        solver_req_path = REQUESTS_DIR / f"{cid}_solver_request.json"
        with open(solver_req_path, "w", encoding="utf-8") as f:
            json.dump(solver_req, f, indent=2)

    # 6. Generate manifest.json
    all_files = sorted(list(BASE_DIR.glob("**/*")))
    files_record: dict[str, Any] = {}
    for p in all_files:
        if p.is_file() and p.name != "manifest.json":
            rel = str(p.relative_to(BASE_DIR))
            files_record[rel] = {
                "sha256": sha256_file(p),
                "bytes": p.stat().st_size,
            }

    manifest = {
        "schema": "ds02.f1.prospective-manifest.v2",
        "family": "F1",
        "scope": "handoff_20261003/root_followup_042_prospective_fix_v1",
        "root_review_status": "minimal_erratum_and_prospective_binding_rewrite_complete",
        "erratum_document": "ERRATUM_AND_PROSPECTIVE_BINDING_REWRITE.md",
        "unsupported_claims_retracted": [
            "reducing H proves 75% peak kinetic suppression",
            "laminar stable stagnation",
            "guaranteed no fate switches / no overtopping / NpOut = 0",
            "invented |vy|max > 0.4 m/s gate",
        ],
        "native_weights_policy": "Report native weights in float32; no continuous decimal rho*dp^3 string invariance.",
        "transverse_effect_status": "Actual 3D transverse effect descriptor pending full native GPU proof.",
        "rootguard_prepworker": "scripts/rootguard_prepworker.py",
        "definitions_count": 6,
        "gencase_requests_count": 6,
        "solver_requests_count": 6,
        "files": files_record,
        "claim_boundary": {
            "q_n": "not_granted",
            "production_approval": "none",
            "policy": "Exclusive Rootguard dispatch for all actual scientific executions.",
        },
    }

    manifest_path = BASE_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Successfully generated all 042 fallback cases in {BASE_DIR}")


if __name__ == "__main__":
    generate_all()
