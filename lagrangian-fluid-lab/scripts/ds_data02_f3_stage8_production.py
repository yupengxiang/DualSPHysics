#!/usr/bin/env python3
"""Materialize F3 Stage 8 production definitions, execute GenCase preflights, and emit GPU solver requests."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_f3 import (
    FAMILY_ROOT,
    sha256_file,
)

GENCASE_BIN = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
SOLVER_BIN = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DATA_F3_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")

STAGE8_DUAL_CASES = [
    {
        "case_id": "F3_NEW_DUAL_AXIS_PHASE_00",
        "paired_background_id": "dual_axis_phase_paired_background_00",
        "mechanism_id": "dual_axis_phase",
        "geometry_family_id": "F3_CELL3_PLAIN",
        "control_family_id": "F3_CTRL_DUAL_AXIS_PHASE",
        "dp_m": 0.0075,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "ax_g": 0.060,
        "ay_g": 0.040,
        "phi_rad": math.pi / 2.0,  # 90 deg (quadrature)
        "assigned_gpu": 2,
        "description": "Baseline weak-drive dual-axis sloshing in quadrature; exact anchor to qualified reference",
    },
    {
        "case_id": "F3_NEW_DUAL_AXIS_PHASE_01",
        "paired_background_id": "dual_axis_phase_paired_background_01",
        "mechanism_id": "dual_axis_phase",
        "geometry_family_id": "F3_CELL3_PLAIN",
        "control_family_id": "F3_CTRL_DUAL_AXIS_PHASE",
        "dp_m": 0.0075,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "ax_g": 0.060,
        "ay_g": 0.040,
        "phi_rad": math.pi / 3.0,  # 60 deg
        "assigned_gpu": 5,
        "description": "Weak-drive dual-axis sloshing with 60-degree inter-axis phase shift",
    },
    {
        "case_id": "F3_NEW_DUAL_AXIS_PHASE_02",
        "paired_background_id": "dual_axis_phase_paired_background_02",
        "mechanism_id": "dual_axis_phase",
        "geometry_family_id": "F3_CELL3_PLAIN",
        "control_family_id": "F3_CTRL_DUAL_AXIS_PHASE",
        "dp_m": 0.0075,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "ax_g": 0.045,
        "ay_g": 0.030,
        "phi_rad": math.pi / 2.0,  # 90 deg
        "assigned_gpu": 6,
        "description": "Reduced weak-drive amplitude (75% of containment bound) in quadrature",
    },
    {
        "case_id": "F3_NEW_DUAL_AXIS_PHASE_03",
        "paired_background_id": "dual_axis_phase_paired_background_03",
        "mechanism_id": "dual_axis_phase",
        "geometry_family_id": "F3_CELL3_PLAIN",
        "control_family_id": "F3_CTRL_DUAL_AXIS_PHASE",
        "dp_m": 0.0075,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "ax_g": 0.050,
        "ay_g": 0.035,
        "phi_rad": math.pi / 4.0,  # 45 deg
        "assigned_gpu": 7,
        "description": "Intermediate weak-drive amplitude with 45-degree diagonal inter-axis phase",
    },
]

STAGE8_BAFFLE_CASES = [
    {
        "case_id": "F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_00",
        "paired_background_id": "eccentric_baffle_exchange_paired_background_00",
        "mechanism_id": "eccentric_baffle_exchange",
        "geometry_family_id": "F3_BAFFLE_ECCENTRIC_CHANNEL",
        "control_family_id": "F3_CTRL_MOVING_TANK_WORLD",
        "dp_m": 0.008,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "X_m": 0.018,
        "Y_m": 0.012,
        "phi_rad": math.pi / 3.0,  # 60 deg
        "ramp_time_s": 0.8,
        "assigned_gpu": 2,
        "description": "Weak moving-tank world excitation with eccentric baffle exchange; ax<=0.056g, ay<=0.026g",
    },
    {
        "case_id": "F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_01",
        "paired_background_id": "eccentric_baffle_exchange_paired_background_01",
        "mechanism_id": "eccentric_baffle_exchange",
        "geometry_family_id": "F3_BAFFLE_ECCENTRIC_CHANNEL",
        "control_family_id": "F3_CTRL_MOVING_TANK_WORLD",
        "dp_m": 0.008,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "X_m": 0.018,
        "Y_m": 0.012,
        "phi_rad": math.pi / 2.0,  # 90 deg
        "ramp_time_s": 0.8,
        "assigned_gpu": 5,
        "description": "Weak moving-tank world excitation with 90-degree transverse phase; ax<=0.056g, ay<=0.029g",
    },
    {
        "case_id": "F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_02",
        "paired_background_id": "eccentric_baffle_exchange_paired_background_02",
        "mechanism_id": "eccentric_baffle_exchange",
        "geometry_family_id": "F3_BAFFLE_ECCENTRIC_CHANNEL",
        "control_family_id": "F3_CTRL_MOVING_TANK_WORLD",
        "dp_m": 0.008,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "X_m": 0.014,
        "Y_m": 0.009,
        "phi_rad": math.pi / 3.0,  # 60 deg
        "ramp_time_s": 0.8,
        "assigned_gpu": 6,
        "description": "Gentle weak moving-tank excitation (78% amplitude); ax<=0.044g, ay<=0.020g",
    },
    {
        "case_id": "F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_03",
        "paired_background_id": "eccentric_baffle_exchange_paired_background_03",
        "mechanism_id": "eccentric_baffle_exchange",
        "geometry_family_id": "F3_BAFFLE_ECCENTRIC_CHANNEL",
        "control_family_id": "F3_CTRL_MOVING_TANK_WORLD",
        "dp_m": 0.008,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "X_m": 0.015,
        "Y_m": 0.010,
        "phi_rad": math.pi / 4.0,  # 45 deg
        "ramp_time_s": 0.8,
        "assigned_gpu": 7,
        "description": "Weak moving-tank excitation with 45-degree diagonal trajectory; ax<=0.047g, ay<=0.026g",
    },
]

ALL_STAGE8_CASES = STAGE8_DUAL_CASES + STAGE8_BAFFLE_CASES


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_dual_axis_control(path: Path, ax_g: float, ay_g: float, phi_rad: float) -> dict:
    omega = 2.0 * math.pi / 1.9
    rows = 2001
    dt = 10.0 / (rows - 1)
    lines = ["#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"]
    
    ax_max = 0.0
    ay_max = 0.0
    for i in range(rows):
        t = i * dt
        if t <= 0.5:
            env = 0.5 * (1.0 - math.cos(math.pi * t / 0.5))
        elif t <= 8.0:
            env = 1.0
        elif t <= 8.5:
            phase = (t - 8.0) / 0.5
            env = 0.5 * (1.0 + math.cos(math.pi * phase))
        else:
            env = 0.0

        ax = ax_g * 9.81 * env * math.sin(omega * t)
        ay = ay_g * 9.81 * env * math.sin(omega * t + phi_rad)
        az = -9.81
        ax_max = max(ax_max, abs(ax))
        ay_max = max(ay_max, abs(ay))
        lines.append(f"{t:.5f};{ax:.10g};{ay:.10g};{az:.10g};0;0;0")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "rows": rows,
        "time_window_s": [0.0, 10.0],
        "sample_interval_s": dt,
        "drive_stop_s": 8.0,
        "reflow_tail_end_s": 10.0,
        "ax_max_m_s2": ax_max,
        "ay_max_m_s2": ay_max,
        "ax_max_g": ax_max / 9.81,
        "ay_max_g": ay_max / 9.81,
    }


def build_dual_axis_xml(case: dict, control_filename: str) -> str:
    dp = case["dp_m"]
    return f"""<?xml version='1.0' encoding='utf-8'?>
<!-- DS-DATA-02 F3 Stage 8 Production: dual_axis_phase weak-drive containment -->
<!-- Physical case: {case["case_id"]}; dp={dp}m; ax<={case["ax_g"]}g; ay<={case["ay_g"]}g -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" comment="Gravitational acceleration" units_comment="m/s^2" />
      <rhop0 value="1000" comment="Reference density of the fluid" units_comment="kg/m^3" />
      <rhopgradient value="2" comment="Initial density gradient 1:Rhop0, 2:Water column, 3:Max. water height (default=2)" />
      <hswl value="0" auto="true" comment="Maximum still water level to calculate speedofsound using coefsound" units_comment="metres (m)" />
      <gamma value="7" comment="Polytropic constant for water used in the state equation" />
      <speedsystem value="0" auto="true" comment="Maximum system speed (by default the dam-break propagation is used)" />
      <coefsound value="30" comment="Coefficient to multiply speedsystem" />
      <speedsound value="0" auto="true" comment="Speed of sound to use in the simulation (by default speedofsound=coefsound*speedsystem)" />
      <coefh value="0.91924" comment="Coefficient to calculate the smoothing length (h=coefh*sqrt(3*dp^2) in 3D)" />
      <cflnumber value="0.05" comment="Coefficient to multiply dt" />
    </constantsdef>
    <mkconfig boundcount="240" fluidcount="9" />
    <geometry>
      <definition dp="{dp:.4f}" units_comment="metres (m)">
        <pointref x="0.00375" y="0.00375" z="0.00375" />
        <pointmin x="-1" y="-.2" z="-1" />
        <pointmax x="1" y=".2" z="1" />
      </definition>
      <commands>
        <list name="GeometryForNormals">
          <setactive drawpoints="0" drawshapes="1" />
          <setshapemode>actual | bound</setshapemode>
          <setnormalinvert invert="true" />
          <setmkbound mk="0" />
          <drawbox>
            <boxfill>all^top</boxfill>
            <point x="-0.45" y="-0.09" z="0" />
            <size x="0.9" y="0.18" z="0.51" />
            <layers vdp="0" />
          </drawbox>
          <shapeout file="hdp" />
          <resetdraw />
        </list>
        <mainlist>
          <runlist name="GeometryForNormals" />
          <setdrawmode mode="full" />
          <setmkfluid mk="0" />
          <drawbox>
            <boxfill>solid</boxfill>
            <point x="-0.44625" y="-0.08625" z="0.00375" />
            <size x="0.8925" y="0.1725" z="0.0825" />
          </drawbox>
          <setmkbound mk="0" />
          <drawbox>
            <boxfill>all^top</boxfill>
            <point x="-0.45375" y="-0.09375" z="-0.00375" />
            <size x="0.9075" y="0.1875" z="0.51375" />
            <layers vdp="0,1,2" />
          </drawbox>
        </mainlist>
      </commands>
    </geometry>
    <normals active="true">
      <norgeometry>
        <geometryfile file="[CaseName]_hdp_Actual.vtk" />
        <distanceh v="3.0" />
        <svshapes v="true" />
      </norgeometry>
    </normals>
  </casedef>
  <execution>
    <special>
      <accinputs>
        <accinput mkfluid="0">
          <acccentre x="0.45" y="0" z="0" comment="Center of acceleration" units_comment="metres (m)" />
          <globalgravity value="0" comment="Global gravity enabled (1) or disabled (0)" />
          <acctimesfile value="{control_filename}" comment="File with linear and angular acceleration data" />
        </accinput>
      </accinputs>
    </special>
    <parameters>
      <parameter key="SavePosDouble" value="2" comment="Saves particle position using double precision (default=0)" />
      <parameter key="StepAlgorithm" value="2" comment="Step Algorithm 1:Verlet, 2:Symplectic (default=1)" />
      <parameter key="VerletSteps" value="40" comment="Verlet only: Number of steps to apply Euler timestepping (default=40)" />
      <parameter key="Kernel" value="2" comment="Interaction Kernel 1:Cubic Spline, 2:Wendland (default=2)" />
      <parameter key="ViscoTreatment" value="1" comment="Viscosity formulation 1:Artificial, 2:Laminar+SPS, 3:Laminar (default=1)" />
      <parameter key="Visco" value="0.05" comment="Viscosity value" />
      <parameter key="ViscoBoundFactor" value="1" comment="Multiply viscosity value with boundary (default=1)" />
      <parameter key="DensityDT" value="3" comment="Density Diffusion Term 0:None, 1:Molteni, 2:Fourtakas, 3:Fourtakas(full)" />
      <parameter key="DensityDTvalue" value="0.1" comment="DDT value (default=0.1)" />
      <parameter key="Shifting" value="0" comment="Shifting mode" />
      <parameter key="ShiftCoef" value="-2" comment="Coefficient for shifting computation" />
      <parameter key="ShiftTFS" value="0" comment="Threshold to detect free surface" />
      <parameter key="RigidAlgorithm" value="1" comment="Rigid Algorithm" />
      <parameter key="FtPause" value="0.0" comment="Time to freeze the floatings at simulation start" units_comment="seconds" />
      <parameter key="CoefDtMin" value="0.05" comment="Coefficient to calculate minimum time step" />
      <parameter key="DtIni" value="0" comment="Initial time step" units_comment="seconds" />
      <parameter key="DtMin" value="0" comment="Minimum time step" units_comment="seconds" />
      <parameter key="DtFixed" value="0" comment="Fixed Dt value" units_comment="seconds" />
      <parameter key="DtFixedFile" value="NONE" comment="Dt values loaded from file" />
      <parameter key="DtAllParticles" value="0" comment="Velocity of particles used to calculate DT" />
      <parameter key="TimeMax" value="10.0" comment="Time of simulation" units_comment="seconds" />
      <parameter key="TimeOut" value="0.0025" comment="Time out data" units_comment="seconds" />
      <parameter key="PartsOutMax" value="1" comment="Excluded particle fraction allowed" units_comment="decimal" />
      <parameter key="RhopOutMin" value="700" comment="Minimum rhop valid" units_comment="kg/m^3" />
      <parameter key="RhopOutMax" value="1300" comment="Maximum rhop valid" units_comment="kg/m^3" />
      <simulationdomain comment="Defines domain of simulation">
        <posmin x="default-150%" y="default-150%" z="default-150%" />
        <posmax x="default+150%" y="default+150%" z="default+150%" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
"""


def build_baffle_motion(path: Path, X_m: float, Y_m: float, phi_rad: float, ramp_time_s: float = 0.8) -> dict:
    omega = 2.0 * math.pi / 1.9
    rows = 2001
    dt = 10.0 / (rows - 1)
    lines = []
    
    t_vals = [i * dt for i in range(rows)]
    x_vals = []
    y_vals = []
    
    for t in t_vals:
        if t <= ramp_time_s:
            env = 0.5 * (1.0 - math.cos(math.pi * t / ramp_time_s))
        elif t <= 8.0:
            env = 1.0
        elif t <= 8.5:
            phase = (t - 8.0) / 0.5
            env = 0.5 * (1.0 + math.cos(math.pi * phase))
        else:
            env = 0.0

        x = X_m * env * math.sin(omega * t)
        y = Y_m * env * math.sin(omega * t + phi_rad)
        x_vals.append(x)
        y_vals.append(y)
        lines.append(f"{t:.5f} {x:.10g} {y:.10g} 0")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    
    # Compute numerical acceleration
    vx = [(x_vals[i+1] - x_vals[i]) / dt for i in range(rows - 1)]
    vy = [(y_vals[i+1] - y_vals[i]) / dt for i in range(rows - 1)]
    ax = [(vx[i+1] - vx[i]) / dt for i in range(rows - 2)]
    ay = [(vy[i+1] - vy[i]) / dt for i in range(rows - 2)]
    ax_max = max(abs(a) for a in ax)
    ay_max = max(abs(a) for a in ay)

    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "rows": rows,
        "time_window_s": [0.0, 10.0],
        "sample_interval_s": dt,
        "drive_stop_s": 8.0,
        "reflow_tail_end_s": 10.0,
        "ax_max_m_s2": ax_max,
        "ay_max_m_s2": ay_max,
        "ax_max_g": ax_max / 9.81,
        "ay_max_g": ay_max / 9.81,
    }


def build_baffle_xml(case: dict, motion_filename: str) -> str:
    dp = case["dp_m"]
    return f"""<?xml version='1.0' encoding='utf-8'?>
<!-- DS-DATA-02 F3 Stage 8 Production: eccentric_baffle_exchange weak-drive containment -->
<!-- Physical case: {case["case_id"]}; dp={dp}m; X={case["X_m"]}m; Y={case["Y_m"]}m; phi={case["phi_rad"]:.4f}rad -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <rhopgradient value="2" />
      <hswl value="0" auto="true" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="30" />
      <speedsound value="0" auto="true" />
      <coefh value="0.91924" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="240" fluidcount="9" />
    <geometry>
      <definition dp="{dp:.4f}" units_comment="metres (m)">
        <pointref x="0.004" y="0.004" z="0.004" />
        <pointmin x="-0.6" y="-0.25" z="-0.1" />
        <pointmax x="0.6" y="0.25" z="0.7" />
      </definition>
      <commands>
        <list name="GeometryForNormals">
          <setactive drawpoints="0" drawshapes="1" />
          <setshapemode>actual | bound</setshapemode>
          <setnormalinvert invert="true" />
          <setmkbound mk="0" />
          <drawbox>
            <boxfill>all^top</boxfill>
            <point x="-0.45" y="-0.1" z="0" />
            <size x="0.9" y="0.2" z="0.508" />
            <layers vdp="-0.5" />
          </drawbox>
          <setnormalinvert invert="false" />
          <setmkbound mk="1" />
          <drawbox>
            <boxfill>bottom | top | left | right | front | back</boxfill>
            <point x="-0.012" y="-0.092" z="0" />
            <size x="0.024" y="0.087" z="0.30" />
            <layers vdp="-0.5" />
          </drawbox>
          <drawbox>
            <boxfill>bottom | top | left | right | front | back</boxfill>
            <point x="-0.012" y="0.045" z="0" />
            <size x="0.024" y="0.047" z="0.30" />
            <layers vdp="-0.5" />
          </drawbox>
          <shapeout file="hdp" />
          <resetdraw />
        </list>
        <mainlist>
          <runlist name="GeometryForNormals" />
          <setshapemode>dp | bound</setshapemode>
          <setdrawmode mode="full" />
          <setmkbound mk="0" />
          <drawbox>
            <boxfill>bottom | left | right | front | back</boxfill>
            <point x="-0.45" y="-0.1" z="0" />
            <size x="0.9" y="0.2" z="0.508" />
            <layers vdp="0,1,2,3" />
          </drawbox>
          <setmkbound mk="1" />
          <drawbox>
            <boxfill>bottom | top | left | right | front | back</boxfill>
            <point x="-0.012" y="-0.092" z="0" />
            <size x="0.024" y="0.087" z="0.30" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkbound mk="1" />
          <drawbox>
            <boxfill>bottom | top | left | right | front | back</boxfill>
            <point x="-0.012" y="0.045" z="0" />
            <size x="0.024" y="0.047" z="0.30" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkfluid mk="0" />
          <fillbox x="-0.3" y="0.02" z="0.05">
            <modefill>void</modefill>
            <point x="-0.45" y="-0.092" z="0" />
            <size x="0.9" y="0.184" z="0.14" />
          </fillbox>
          <shapeout file="" />
        </mainlist>
      </commands>
    </geometry>
    <normals active="true">
      <norgeometry>
        <geometryfile file="[CaseName]_hdp_Actual.vtk" />
        <distanceh v="3.0" />
        <svshapes v="true" />
      </norgeometry>
    </normals>
    <motion>
      <objreal ref="0">
        <begin mov="1" start="0" finish="10.0" />
        <mvfile id="1" duration="10.0">
          <file name="{motion_filename}" fields="4" fieldtime="0" fieldx="1" fieldy="2" fieldz="3" />
        </mvfile>
      </objreal>
    </motion>
  </casedef>
  <execution>
    <parameters>
      <parameter key="SavePosDouble" value="2" />
      <parameter key="Boundary" value="2" />
      <parameter key="SlipMode" value="2" />
      <parameter key="NoPenetration" value="1" />
      <parameter key="StepAlgorithm" value="2" />
      <parameter key="VerletSteps" value="40" />
      <parameter key="Kernel" value="2" />
      <parameter key="ViscoTreatment" value="1" />
      <parameter key="Visco" value="0.05" />
      <parameter key="ViscoBoundFactor" value="1" />
      <parameter key="DensityDT" value="3" />
      <parameter key="DensityDTvalue" value="0.1" />
      <parameter key="Shifting" value="0" />
      <parameter key="ShiftCoef" value="-2" />
      <parameter key="ShiftTFS" value="0" />
      <parameter key="RigidAlgorithm" value="1" />
      <parameter key="FtPause" value="0.0" />
      <parameter key="CoefDtMin" value="0.05" />
      <parameter key="DtIni" value="0" />
      <parameter key="DtMin" value="0" />
      <parameter key="DtFixed" value="0" />
      <parameter key="DtAllParticles" value="0" />
      <parameter key="TimeMax" value="10.0" />
      <parameter key="TimeOut" value="0.0025" />
      <parameter key="PartsOutMax" value="1" />
      <parameter key="RhopOutMin" value="700" />
      <parameter key="RhopOutMax" value="1300" />
      <parameter key="MinFluidStop" value="0" />
      <simulationdomain>
        <posmin x="default-150%" y="default-150%" z="default-150%" />
        <posmax x="default+150%" y="default+150%" z="default+150%" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
"""


def materialize_definitions(family_dir: Path = FAMILY_ROOT) -> list[dict]:
    family = Path(family_dir).resolve()
    prod_defs = family / "production/definitions"
    prod_defs.mkdir(parents=True, exist_ok=True)

    records = []
    for case in ALL_STAGE8_CASES:
        cid = case["case_id"]
        mech = case["mechanism_id"]

        if mech == "dual_axis_phase":
            ctrl_name = f"{cid}_Control.csv"
            ctrl_path = prod_defs / ctrl_name
            ctrl_info = build_dual_axis_control(ctrl_path, case["ax_g"], case["ay_g"], case["phi_rad"])
            xml_text = build_dual_axis_xml(case, ctrl_name)
            xml_path = prod_defs / f"{cid}_Def.xml"
            xml_path.write_text(xml_text, encoding="utf-8")
        else:
            motion_name = f"{cid}_Motion.txt"
            motion_path = prod_defs / motion_name
            ctrl_info = build_baffle_motion(motion_path, case["X_m"], case["Y_m"], case["phi_rad"], case.get("ramp_time_s", 0.8))
            xml_text = build_baffle_xml(case, motion_name)
            xml_path = prod_defs / f"{cid}_Def.xml"
            xml_path.write_text(xml_text, encoding="utf-8")

        # Canonical physical condition hash
        phys_payload = {
            "family_id": "F3",
            "case_id": cid,
            "mechanism_id": mech,
            "dp_m": case["dp_m"],
            "control_sha256": ctrl_info["sha256"],
            "definition_sha256": sha256_file(xml_path),
        }
        phys_hash = hashlib.sha256(json.dumps(phys_payload, sort_keys=True).encode("utf-8")).hexdigest()
        phys_case_id = f"physical_F3_{phys_hash[:16]}"

        meta = dict(case)
        meta["physical_case_id"] = phys_case_id
        meta["definition_path"] = str(xml_path.resolve())
        meta["definition_sha256"] = sha256_file(xml_path)
        meta["control_path"] = ctrl_info["path"]
        meta["control_sha256"] = ctrl_info["sha256"]
        meta["control_metrics"] = ctrl_info
        meta["materialized_at_utc"] = now_str()
        meta["containment_compliance"] = {
            "ax_max_g": ctrl_info["ax_max_g"],
            "ay_max_g": ctrl_info["ay_max_g"],
            "ax_bound_g": 0.06,
            "ay_bound_g": 0.04,
            "compliant": ctrl_info["ax_max_g"] <= 0.0601 and ctrl_info["ay_max_g"] <= 0.0401,
        }

        meta_path = prod_defs / f"{cid}.metadata.json"
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        records.append(meta)

    return records


def run_gencase_preflight(case_meta: dict) -> dict:
    cid = case_meta["case_id"]
    mech = case_meta["mechanism_id"]
    attempt_id = f"{cid}_GENCASE_01"
    output_dir = DATA_F3_ROOT / cid / attempt_id
    output_dir.mkdir(parents=True, exist_ok=True)

    def_xml = Path(case_meta["definition_path"])
    cwd = def_xml.parent

    cmd = [
        str(GENCASE_BIN),
        str(def_xml.with_suffix("")),
        str(output_dir / cid),
        "-save:all",
        "-threads:4",
    ]

    t0 = datetime.now(timezone.utc)
    res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    t1 = datetime.now(timezone.utc)
    elapsed = (t1 - t0).total_seconds()

    (output_dir / "stdout.log").write_text(res.stdout, encoding="utf-8")

    # Parse stdout
    total_parts = None
    fluid_parts = None
    fixed_parts = None
    moving_parts = None
    nonzero_normals = None
    zero_normals = None

    for line in res.stdout.splitlines():
        if "Total particles:" in line:
            # Total particles: 108,000 (bound=73440 (fx=73440 mv=0 ft=0) fluid=34560)
            parts_str = line.split("Total particles:")[1].split()[0].replace(",", "")
            total_parts = int(parts_str)
        if "Fixed...." in line:
            fixed_parts = int(line.split("Fixed....:")[1].split()[0].replace(",", ""))
        if "Moving..." in line:
            moving_parts = int(line.split("Moving...:")[1].split()[0].replace(",", ""))
        if "Fluid...." in line:
            fluid_parts = int(line.split("Fluid....:")[1].split()[0].replace(",", ""))
        if "Non-zero particle normals:" in line:
            # Non-zero particle normals: 73,440/73,440
            nonzero_normals = line.split("Non-zero particle normals:")[1].strip()
        if "Final zero normals:" in line:
            # Final zero normals: 0/73,440 (0.0%)
            zero_normals = line.split("Final zero normals:")[1].strip()

    wall_parts = (fixed_parts or 0) + (moving_parts or 0)

    # Reference parity checks
    if mech == "dual_axis_phase":
        expected_total = 108000
        expected_fluid = 34560
        expected_wall = 73440
    else:
        expected_total = 130768
        expected_fluid = 36736
        expected_wall = 94032

    parity = (
        res.returncode == 0
        and total_parts == expected_total
        and fluid_parts == expected_fluid
        and wall_parts == expected_wall
    )

    receipt = {
        "schema": "ds02.execution-receipt.v1",
        "case_id": cid,
        "attempt_id": attempt_id,
        "family_id": "F3",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "status": "completed" if res.returncode == 0 else "failed",
        "returncode": res.returncode,
        "total_particles": total_parts,
        "fluid_particles": fluid_parts,
        "fixed_particles": fixed_parts,
        "moving_particles": moving_parts,
        "wall_particles": wall_parts,
        "solver_dimension_from_gencase": 3,
        "nonzero_normals": nonzero_normals,
        "zero_normals": zero_normals,
        "reference_expectations": {
            "expected_total_particles": expected_total,
            "expected_fluid_particles": expected_fluid,
            "expected_wall_particles": expected_wall,
            "parity_match": parity,
        },
        "elapsed_seconds": elapsed,
        "started_at_utc": t0.isoformat(),
        "finished_at_utc": t1.isoformat(),
        "command": cmd,
        "binary_sha256": sha256_file(GENCASE_BIN),
        "definition_sha256": case_meta["definition_sha256"],
        "control_sha256": case_meta["control_sha256"],
        "output_root": str(output_dir.resolve()),
        "output_files": {
            "bi4": str((output_dir / f"{cid}.bi4").resolve()),
            "xml": str((output_dir / f"{cid}.xml").resolve()),
            "bound_vtk": str((output_dir / f"{cid}_Bound.vtk").resolve()),
            "fluid_vtk": str((output_dir / f"{cid}_Fluid.vtk").resolve()),
            "all_vtk": str((output_dir / f"{cid}_All.vtk").resolve()),
        }
    }

    receipt_path = output_dir / "execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["receipt_path"] = str(receipt_path.resolve())
    receipt["receipt_sha256"] = sha256_file(receipt_path)
    return receipt


def emit_gencase_and_solver_requests(case_meta: dict, gencase_receipt: dict, family_dir: Path = FAMILY_ROOT) -> tuple[Path, Path]:
    family = Path(family_dir).resolve()
    requests_dir = family / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)

    cid = case_meta["case_id"]
    mech = case_meta["mechanism_id"]
    assigned_gpu = case_meta["assigned_gpu"]

    def_xml = Path(case_meta["definition_path"])
    ctrl_file = Path(case_meta["control_path"])
    meta_json = def_xml.parent / f"{cid}.metadata.json"

    # 1. GenCase request JSON
    gencase_req = {
        "schema": "ds02.cpu-request.v2",
        "family_id": "F3",
        "case_id": cid,
        "attempt_id": f"{cid}_GENCASE_01",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": [
            str(GENCASE_BIN),
            str(def_xml.with_suffix("")),
            "{attempt_root}/" + cid,
            "-save:all",
            "-threads:4",
        ],
        "cwd": str(def_xml.parent),
        "max_wall_seconds": 300,
        "cpu_threads": 4,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "input_files": [
            str(GENCASE_BIN),
            str(def_xml),
            str(meta_json),
            str(ctrl_file),
        ],
        "worktree_root": str(REPO.parent),
        "purpose": "bounded native GenCase preflight only; no solver/GPU/model",
        "physical_parent_id": case_meta["physical_case_id"],
        "registry_kind": "production",
        "expected_checks": {
            "mechanism": mech,
            "registry_kind": "production",
            "physical_parent_id": case_meta["physical_case_id"],
            "resolution": case_meta["resolution"],
            "expected_dimension": 3,
            "positive_fluid_required": True,
            "expected_fluid_particles": gencase_receipt["fluid_particles"],
            "expected_total_particles": gencase_receipt["total_particles"],
        },
    }
    gencase_req_path = requests_dir / f"{cid}-gencase.json"
    gencase_req_path.write_text(json.dumps(gencase_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # 2. GPU Solver request JSON
    output_dir = Path(gencase_receipt["output_root"])
    bi4 = Path(gencase_receipt["output_files"]["bi4"])
    xml = Path(gencase_receipt["output_files"]["xml"])
    rec_path = Path(gencase_receipt.get("receipt_path") or (output_dir / "execution-receipt.json"))

    input_files = [
        str(rec_path),
        str(bi4),
        str(xml),
        str(def_xml),
        str(ctrl_file),
        str(meta_json),
    ]
    input_hashes = {p: sha256_file(Path(p)) for p in input_files}

    solver_req = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F3",
        "case_id": cid,
        "attempt_id": f"{cid}_QUALIFICATION_003",
        "physical_case_id": case_meta["physical_case_id"],
        "physical_parent_id": case_meta["physical_case_id"],
        "paired_background_id": case_meta["paired_background_id"],
        "registry_kind": "production",
        "kind": "qualification",
        "assigned_gpu": assigned_gpu,
        "permitted_gpus": [2, 5, 6, 7],
        "command": [
            str(SOLVER_BIN),
            str(output_dir / cid),
            "{attempt_root}/solver",
            "-tmax:10",
            "-tout:0.0025",
        ],
        "cwd": str(output_dir),
        "worktree_root": str(REPO.parent),
        "max_wall_seconds": 1800,
        "cpu_threads": 2,
        "estimated_storage_bytes": 24 * 1024**3,
        "estimated_peak_gpu_mib": 4096,
        "total_particles": gencase_receipt["total_particles"],
        "fluid_particles": gencase_receipt["fluid_particles"],
        "gencase_receipt": str(rec_path),
        "gencase_receipt_sha256": gencase_receipt.get("receipt_sha256") or hashlib.sha256(rec_path.read_bytes()).hexdigest(),
        "gencase_prefix": str(output_dir / cid),
        "gencase_bi4": str(bi4),
        "gencase_xml": str(xml),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "containment_contract": {
            "drive_mechanism": mech,
            "bounds": "ax <= 0.06g, ay <= 0.04g",
            "measured_ax_max_g": case_meta["control_metrics"]["ax_max_g"],
            "measured_ay_max_g": case_meta["control_metrics"]["ay_max_g"],
            "expected_N_out": 0,
        },
        "purpose": f"Stage 8 production GPU solver run on allocated GPU {assigned_gpu}",
    }
    solver_req_path = requests_dir / f"{cid}-solver.json"
    solver_req_path.write_text(json.dumps(solver_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return gencase_req_path, solver_req_path


def write_owner_metadata(case_meta: dict, gencase_receipt: dict, family_dir: Path = FAMILY_ROOT) -> Path:
    family = Path(family_dir).resolve()
    owner_dir = family / "production/owner_metadata"
    owner_dir.mkdir(parents=True, exist_ok=True)

    cid = case_meta["case_id"]
    mech = case_meta["mechanism_id"]

    owner = {
        "case_id": cid,
        "family_id": "F3",
        "mechanism_id": mech,
        "physical_case_id": case_meta["physical_case_id"],
        "paired_background_id": case_meta["paired_background_id"],
        "split": case_meta["split"],
        "target_role": case_meta["target_role"],
        "resolution": case_meta["resolution"],
        "dp_m": case_meta["dp_m"],
        "assigned_gpu": case_meta["assigned_gpu"],
        "permitted_gpus": [2, 5, 6, 7],
        "gencase_receipt": gencase_receipt.get("receipt_path") or str(Path(gencase_receipt.get("output_root", "")) / "execution-receipt.json"),
        "gencase_receipt_sha256": gencase_receipt.get("receipt_sha256") or (hashlib.sha256(Path(gencase_receipt["output_root"] + "/execution-receipt.json").read_bytes()).hexdigest() if "output_root" in gencase_receipt else ""),
        "total_particles": gencase_receipt["total_particles"],
        "fluid_particles": gencase_receipt["fluid_particles"],
        "wall_particles": gencase_receipt["wall_particles"],
        "solver_dimension": 3,
        "containment_compliance": case_meta["containment_compliance"],
        "physical_binding": {
            "schema": "ds-data-02.physical-binding.v1",
            "family_id": "F3",
            "physical_case_id": case_meta["physical_case_id"],
            "mechanism_id": mech,
            "geometry_family_id": case_meta["geometry_family_id"],
            "control_family_id": case_meta["control_family_id"],
            "density_kg_m3": 1000.0,
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "controls": {
                "boundary": "finite DBC tank, moving baffle/sway, no periodic boundaries",
                "density_dt": 2,
                "density_dt_value": 0.1,
                "kernel": 2,
                "step_algorithm": 2,
                "viscosity": 0.01,
            },
            "geometry": {
                "tank": {
                    "label": "finite tank domain",
                    "low_m": [-0.5, -0.5, -0.5],
                    "size_m": [1.0, 1.0, 1.0],
                }
            },
            "initial_state": {
                "source_regions": ["fluid_block"],
                "velocities_m_per_s": [[0.0, 0.0, 0.0]],
                "mass_policy": "native per-particle mass from BI4 header",
            },
            "parameters": {
                "drive_mechanism": mech,
                "containment_bounds": "ax <= 0.06g, ay <= 0.04g",
            },
            "event_window": {
                "time_start_s": 0.0,
                "time_end_s": 10.0,
                "sequence": ["sloshing_initiation", "baffle_interaction", "stationary_settling"],
                "expected_first_contact_range_s": [0.0, 10.0],
                "right_censor_policy": "finite 10s run retains initial fluid denominator",
            },
        },
        "written_at_utc": now_str(),
    }
    owner_path = owner_dir / f"{cid}.owner.json"
    owner_path.write_text(json.dumps(owner, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return owner_path


def update_registry_and_split_plan(meta_records: list[dict], gencase_receipts: dict[str, dict], family_dir: Path = FAMILY_ROOT) -> None:
    family = Path(family_dir).resolve()
    reg_path = family / "case_registry.jsonl"
    split_path = family / "split_plan.json"

    meta_by_id = {m["case_id"]: m for m in meta_records}

    # 1. Update case_registry.jsonl
    lines = reg_path.read_text(encoding="utf-8").splitlines()
    updated_rows = []
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        cid = row.get("case_id")
        if cid in meta_by_id:
            m = meta_by_id[cid]
            rec = gencase_receipts[cid]
            row["physical_case_id"] = m["physical_case_id"]
            row["input_definition_path"] = m["definition_path"]
            row["control_path"] = m["control_path"]
            row["control_sha256"] = m["control_sha256"]
            row["stage"] = "stage8"
            row["production"] = True
            row["production_resolution"] = m["resolution"]
            row["status"] = "gencase_completed_solver_pending"
            row["attempt_id"] = rec["attempt_id"]
            row["solver_dimension"] = 3
            row["particle_axis_count"] = rec["total_particles"]
            row["assigned_gpu"] = m["assigned_gpu"]
            row["permitted_gpus"] = [2, 5, 6, 7]
            row["containment_compliance"] = m["containment_compliance"]
            row["parameter_values"] = {k: v for k, v in m.items() if k in ("ax_g", "ay_g", "phi_rad", "X_m", "Y_m", "ramp_time_s")}
        updated_rows.append(row)

    reg_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in updated_rows) + "\n", encoding="utf-8")

    # 2. Update split_plan.json
    sp = json.loads(split_path.read_text(encoding="utf-8"))
    for slot in sp.get("new_slots", []):
        cid = slot.get("case_id")
        if cid in meta_by_id:
            m = meta_by_id[cid]
            rec = gencase_receipts[cid]
            slot["physical_case_id"] = m["physical_case_id"]
            slot["status"] = "gencase_completed_solver_pending"
            slot["attempt_id"] = rec["attempt_id"]
            slot["solver_dimension"] = 3
            slot["assigned_gpu"] = m["assigned_gpu"]
            slot["stage"] = "stage8"

    sp["stages"] = {
        "stage8": {
            "cumulative_case_count": 8,
            "incremental_case_count": 8,
            "case_ids": [m["case_id"] for m in meta_records],
            "mechanisms": {
                "dual_axis_phase": [c["case_id"] for c in STAGE8_DUAL_CASES],
                "eccentric_baffle_exchange": [c["case_id"] for c in STAGE8_BAFFLE_CASES],
            },
            "split_counts": {"train": 8},
            "containment_contract": "ax <= 0.06g, ay <= 0.04g, N_out = 0",
            "allocated_gpus": [2, 5, 6, 7],
            "gpu_allocation_map": {m["case_id"]: m["assigned_gpu"] for m in meta_records},
        }
    }
    sp["status"] = "stage8_production_gencase_preflight_passed_solvers_prepared"
    split_path.write_text(json.dumps(sp, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    print(f"[{now_str()}] === Starting Family F3 Stage 8 Production Materialization ===")
    
    # 1. Materialize definitions and control/motion files
    print(f"[{now_str()}] Materializing 8 XML definitions and motion files under production/definitions/...")
    meta_records = materialize_definitions(FAMILY_ROOT)
    print(f"[{now_str()}] Successfully materialized {len(meta_records)} definition packages.")

    # 2. Execute GenCase preflight and verify parity
    print(f"[{now_str()}] Executing GenCase preflight for all 8 Stage 8 cases...")
    gencase_receipts = {}
    preflight_summaries = []

    for m in meta_records:
        cid = m["case_id"]
        mech = m["mechanism_id"]
        print(f"[{now_str()}]   Running GenCase preflight: {cid} ({mech})...")
        rec = run_gencase_preflight(m)
        gencase_receipts[cid] = rec
        
        parity = rec["reference_expectations"]["parity_match"]
        print(f"[{now_str()}]     -> Returncode: {rec['returncode']}, Total: {rec['total_particles']}, Fluid: {rec['fluid_particles']}, Wall: {rec['wall_particles']}, Normals: {rec['nonzero_normals']}, Parity: {parity}")
        if not parity:
            raise RuntimeError(f"GenCase parity check failed for {cid}!")

        # 3. Emit requests and owner metadata
        gencase_req, solver_req = emit_gencase_and_solver_requests(m, rec, FAMILY_ROOT)
        owner_meta = write_owner_metadata(m, rec, FAMILY_ROOT)
        
        preflight_summaries.append({
            "case_id": cid,
            "mechanism": mech,
            "assigned_gpu": m["assigned_gpu"],
            "total_particles": rec["total_particles"],
            "fluid_particles": rec["fluid_particles"],
            "wall_particles": rec["wall_particles"],
            "nonzero_normals": rec["nonzero_normals"],
            "zero_normals": rec["zero_normals"],
            "reference_parity": parity,
            "gencase_receipt": rec["receipt_path"],
            "gencase_request": str(gencase_req),
            "solver_request": str(solver_req),
            "owner_metadata": str(owner_meta),
            "containment_compliance": m["containment_compliance"],
        })

    # 4. Update case_registry.jsonl and split_plan.json
    print(f"[{now_str()}] Updating case_registry.jsonl and split_plan.json...")
    update_registry_and_split_plan(meta_records, gencase_receipts, FAMILY_ROOT)

    # 5. Write preflight summary artifact
    summary_path = FAMILY_ROOT / "stage8_gencase_preflight_summary.json"
    summary_path.write_text(json.dumps(preflight_summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Written Stage 8 preflight summary to {summary_path}")

    print(f"[{now_str()}] === All 8 F3 Stage 8 cases successfully materialized, preflighted, and GPU solver requests prepared! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
