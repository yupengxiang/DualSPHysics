#!/usr/bin/env python3
"""DS-DATA-02 F1 input generator and preflight.

The module is deliberately a *definition* tool.  It writes DualSPHysics
Definition XML files, static provenance/preflight records, and a request for
the shared runner.  It never invokes GenCase or DualSPHysics.  In particular,
the files produced by this module are not production evidence until a shared
runner receipt binds the generated XML to an actual attempt.

F1 has two physical backgrounds:

``eccentric_obstacle``
    The official ``main/01_DamBreak`` geometry, retaining its finite bottom
    and four side walls and its slightly off-centre solid obstacle.

``asymmetric_dual_channel``
    A 3-D, finite-wall derivative of the official
    ``mdbc/04_Dambreak`` geometry.  A longitudinal separator creates two
    resolvable channels and ends downstream, so the channels rejoin.  The
    lower/upper channel widths are explicit physical inputs; changing mDBC
    settings alone never creates a second background.

The official source definitions and successful v5.4 canary logs are read from
the historical read-only lab.  They are hashed into every generated sidecar
and into the runner request.  The default output for a future run lives under
the external DS-DATA-02 attempt root, while committed design artefacts live in
``campaigns/ds-data-02/families/F1``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ds-data-02.f1.generator.v1"
FAMILY_ID = "F1"
G = 9.81
RHO0 = 1000.0

SCRIPT_PATH = Path(__file__).resolve()
CURRENT_WORKTREE = SCRIPT_PATH.parents[2]
DEFAULT_READ_ONLY_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
if not DEFAULT_READ_ONLY_LAB.is_dir():
    DEFAULT_READ_ONLY_LAB = CURRENT_WORKTREE / "lagrangian-fluid-lab"
DEFAULT_DATA_ATTEMPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/case/attempt"
)
FAMILY_DIR = CURRENT_WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1"

RESOLUTION_ORDER = ("coarse", "medium", "fine")
DP_BY_BACKGROUND = {
    # The official main mother was successfully generated and solved at
    # 0.020 m.  The smaller values resolve the 0.120 m obstacle width with
    # 8 and 12 points across it.
    "eccentric_obstacle": {"coarse": 0.020, "medium": 0.015, "fine": 0.010},
    # The mDBC mother was successfully generated and solved at 0.020 m.  The
    # separator is 0.060 m thick; the medium/fine values add local samples.
    "asymmetric_dual_channel": {"coarse": 0.020, "medium": 0.012, "fine": 0.008},
}


def _q(value: float) -> str:
    """Stable decimal formatting for Definition XML and JSON identifiers."""

    return f"{value:.9f}".rstrip("0").rstrip(".") or "0"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _relative_or_absolute(path: Path, root: Path | None = None) -> str:
    path = path.resolve()
    if root is not None:
        try:
            return path.relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


def _git_commit(worktree: Path = CURRENT_WORKTREE) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"
    return proc.stdout.strip()


@dataclass(frozen=True)
class MotherSpec:
    key: str
    source_definition: str
    gencase_log: str
    solver_log: str
    particle_stats_csv: str
    source: str
    source_case: str
    boundary: str
    tank_extent_m: tuple[float, float, float]
    fluid_extent_m: tuple[float, float, float]
    fluid_particles: int
    fixed_particles: int
    total_particles: int
    successful_dp_m: float
    successful_tmax_s: float
    successful_tout_s: float
    complete_source_tmax_s: float
    complete_source_tout_s: float
    initial_flow_direction: str
    wall_faces: tuple[str, ...]
    open_top: bool


MOTHERS: dict[str, MotherSpec] = {
    "eccentric_obstacle": MotherSpec(
        key="eccentric_obstacle",
        source_definition="vendor/official/DualSPHysics_v5.4/examples/main/01_DamBreak/CaseDambreak_Def.xml",
        gencase_log="campaigns/ds-data-01/d02/canaries/F1_main_dambreak3d/gencase.stdout.log",
        solver_log="campaigns/ds-data-01/d02/canaries/F1_main_dambreak3d/solver.stdout.log",
        particle_stats_csv="campaigns/ds-data-01/d02/canaries/F1_main_dambreak3d/attempt-001/csv/Particles_stats.csv",
        source="main/01_DamBreak",
        source_case="CaseDambreak",
        boundary="DBC",
        tank_extent_m=(1.6, 0.67, 0.4),
        fluid_extent_m=(0.4, 0.67, 0.3),
        fluid_particles=9600,
        fixed_particles=7846,
        total_particles=17446,
        successful_dp_m=0.02,
        successful_tmax_s=0.6,
        successful_tout_s=0.1,
        complete_source_tmax_s=1.6,
        complete_source_tout_s=0.01,
        initial_flow_direction="+x",
        wall_faces=("bottom", "left", "right", "front", "back"),
        open_top=True,
    ),
    "asymmetric_dual_channel": MotherSpec(
        key="asymmetric_dual_channel",
        source_definition="vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml",
        gencase_log="campaigns/ds-data-01/d02/canaries/F1_mdbc_dambreak3d/gencase.stdout.log",
        solver_log="campaigns/ds-data-01/d02/canaries/F1_mdbc_dambreak3d/solver.stdout.log",
        particle_stats_csv="campaigns/ds-data-01/d02/canaries/F1_mdbc_dambreak3d/attempt-001/csv/Particles_stats.csv",
        source="mdbc/04_Dambreak",
        source_case="CaseDamBreak3D",
        boundary="mDBC",
        tank_extent_m=(3.22, 1.0, 1.0),
        # The source fill box is clipped by the 3.22 m tank wall.  This is
        # the actual initial fluid extent in the successful Dp=0.02 run.
        fluid_extent_m=(1.228, 1.0, 0.55),
        fluid_particles=79380,
        fixed_particles=93042,
        total_particles=172422,
        successful_dp_m=0.02,
        successful_tmax_s=0.6,
        successful_tout_s=0.1,
        complete_source_tmax_s=6.0,
        complete_source_tout_s=0.01,
        initial_flow_direction="-x",
        wall_faces=("bottom", "left", "right", "front", "back"),
        open_top=True,
    ),
}


def _lab_root(value: str | Path | None) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    return DEFAULT_READ_ONLY_LAB.resolve()


def mother_evidence(lab_root: str | Path | None = None, *, strict: bool = True) -> dict[str, Any]:
    """Return the byte-bound official source and historical-run evidence.

    ``strict`` is intentionally true for campaign generation: a definition
    cannot be submitted without the source XML and both actual logs.  Tests
    may use ``strict=False`` to inspect the schema on a machine without the
    historical external tree.
    """

    root = _lab_root(lab_root)
    rows: list[dict[str, Any]] = []
    for spec in MOTHERS.values():
        paths = {
            "source_definition": root / spec.source_definition,
            "gencase_log": root / spec.gencase_log,
            "solver_log": root / spec.solver_log,
            "particle_stats_csv": root / spec.particle_stats_csv,
        }
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing and strict:
            raise FileNotFoundError(
                f"F1 official evidence missing for {spec.key}: "
                + ", ".join(f"{name}={paths[name]}" for name in missing)
            )
        row: dict[str, Any] = {
            "mother_id": f"official_v54_{spec.key}",
            "source": spec.source,
            "source_case": spec.source_case,
            "source_definition": _relative_or_absolute(paths["source_definition"], root),
            "gencase_log": _relative_or_absolute(paths["gencase_log"], root),
            "solver_log": _relative_or_absolute(paths["solver_log"], root),
            "source_definition_sha256": sha256_file(paths["source_definition"])
            if paths["source_definition"].is_file()
            else None,
            "gencase_log_sha256": sha256_file(paths["gencase_log"])
            if paths["gencase_log"].is_file()
            else None,
            "solver_log_sha256": sha256_file(paths["solver_log"])
            if paths["solver_log"].is_file()
            else None,
            "particle_stats_csv_sha256": sha256_file(paths["particle_stats_csv"])
            if paths["particle_stats_csv"].is_file()
            else None,
            "actual_successful_run": {
                "solver_dimension": "3D",
                "coordinate_components": 3,
                "dp_m": spec.successful_dp_m,
                "tank_extent_m": list(spec.tank_extent_m),
                "nominal_initial_fluid_fill_box_extent_m": list(spec.fluid_extent_m),
                # These are the actual initial fluid extrema reported by the
                # historical PartVtk statistics (the lattice is inset by
                # one particle spacing at finite walls).  Keeping both the
                # nominal command box and the realised bounds prevents a
                # volume/initialisation discrepancy being hidden by metadata.
                "initial_particle_bounds_m": (
                    [[0.03, 0.03, 0.03], [0.41, 0.65, 0.31]]
                    if spec.key == "eccentric_obstacle"
                    else [[2.02, 0.02, 0.02], [3.20, 0.98, 0.54]]
                ),
                "initial_particle_extent_m": (
                    [0.38, 0.62, 0.28]
                    if spec.key == "eccentric_obstacle"
                    else [1.18, 0.96, 0.52]
                ),
                "initial_fluid_extent_m": (
                    [0.38, 0.62, 0.28]
                    if spec.key == "eccentric_obstacle"
                    else [1.18, 0.96, 0.52]
                ),
                "initial_particle_stats_csv": _relative_or_absolute(paths["particle_stats_csv"], root),
                "fluid_particles": spec.fluid_particles,
                "fixed_particles": spec.fixed_particles,
                "total_particles": spec.total_particles,
                "boundary": spec.boundary,
                "finite_wall_faces": list(spec.wall_faces),
                "open_top": spec.open_top,
                "initial_flow_direction": spec.initial_flow_direction,
                "time_max_s": spec.successful_tmax_s,
                "time_out_s": spec.successful_tout_s,
                "frame_count": 7,
                "complete_event_evidence": False,
            },
            "official_source_parameters": {
                "time_max_s": spec.complete_source_tmax_s,
                "time_out_s": spec.complete_source_tout_s,
                "complete_event_window_role": "source_recipe_upper_bound",
            },
        }
        rows.append(row)
    return {
        "schema": "ds-data-02.f1.source-audit.v1",
        "family_id": FAMILY_ID,
        "generated_at_utc": _utc_now(),
        "read_only_lab_root": str(root),
        "mother_cases": rows,
        "interpretation": {
            "dimension": "Both successful canaries are actual 3-D solver runs; the main run has lateral y extent and the mDBC run has a 3-D tank plus finite geometry normals.",
            "canary_boundary": "The historical 0.6 s, seven-frame runs prove executable scale and identity retention only. They are not complete release-to-remerge event evidence.",
            "finite_walls": "Both mothers retain bottom, left, right, front and back walls; the top is open. No open top is treated as an outlet.",
            "reuse_policy": "The main XML/DBC recipe supplies the eccentric obstacle background. The mDBC XML/solver recipe supplies the numerical boundary strategy for the explicit dual-channel geometry.",
        },
    }


def _parameter_rows(values: Mapping[str, Any]) -> str:
    return "\n".join(
        f'            <parameter key="{key}" value="{value}" />'
        for key, value in values.items()
    )


def _eccentric_xml(case: Mapping[str, Any]) -> str:
    g = case["geometry"]
    p = case["solver_parameters"]
    return f'''<?xml version="1.0" encoding="UTF-8" ?>
<!-- DS-DATA-02 F1 generated definition; GenCase/solver has not run. -->
<!-- mechanism=eccentric_obstacle; physical_case_id={case["physical_case_id"]}; resolution={case["resolution"]} -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <rhopgradient value="2" />
      <hswl value="0" auto="true" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="20" />
      <speedsound value="0" auto="true" />
      <coefh value="1.0" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="240" fluidcount="9" />
    <geometry>
      <definition dp="{_q(case["dp_m"])}" units_comment="metres (m)">
        <pointmin x="-0.05" y="-0.05" z="-0.05" />
        <pointmax x="2" y="1" z="1" />
      </definition>
      <commands>
        <mainlist>
          <setshapemode>dp | bound</setshapemode>
          <setdrawmode mode="full" />
          <setmkfluid mk="0" />
          <drawbox>
            <boxfill>solid</boxfill>
            <point x="0" y="0" z="0" />
            <size x="{_q(g["fluid_length_m"])}" y="{_q(g["tank_width_m"])}" z="{_q(g["initial_depth_m"])}" />
          </drawbox>
          <setmkbound mk="0" />
          <drawbox>
            <boxfill>bottom | left | right | front | back</boxfill>
            <point x="0" y="0" z="0" />
            <size x="{_q(g["tank_length_m"])}" y="{_q(g["tank_width_m"])}" z="{_q(g["tank_height_m"])}" />
          </drawbox>
          <setmkvoid />
          <drawbox>
            <boxfill>solid</boxfill>
            <point x="{_q(g["obstacle_x_m"])}" y="{_q(g["obstacle_y_m"])}" z="0" />
            <size x="{_q(g["obstacle_length_m"])}" y="{_q(g["obstacle_width_m"])}" z="{_q(g["obstacle_height_m"])}" />
          </drawbox>
          <setmkbound mk="1" />
          <drawbox>
            <boxfill>top | left | right | front | back</boxfill>
            <point x="{_q(g["obstacle_x_m"])}" y="{_q(g["obstacle_y_m"])}" z="0" />
            <size x="{_q(g["obstacle_length_m"])}" y="{_q(g["obstacle_width_m"])}" z="{_q(g["obstacle_height_m"])}" />
          </drawbox>
        </mainlist>
      </commands>
    </geometry>
  </casedef>
  <execution>
    <parameters>
{_parameter_rows(p)}
      <simulationdomain>
        <posmin x="default - 25%" y="default - 25%" z="default - 25%" />
        <posmax x="default + 25%" y="default + 25%" z="default + 75%" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
'''


def _dual_xml(case: Mapping[str, Any]) -> str:
    g = case["geometry"]
    p = case["solver_parameters"]
    # The mDBC mother uses the same actual/bound normal construction.  A
    # single outer tank drawbox and one separator drawbox are sufficient for
    # the explicit finite-wall geometry here; no periodic faces are present.
    return f'''<?xml version="1.0" encoding="UTF-8" ?>
<!-- DS-DATA-02 F1 generated definition; GenCase/solver has not run. -->
<!-- mechanism=asymmetric_dual_channel; physical_case_id={case["physical_case_id"]}; resolution={case["resolution"]} -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <rhopgradient value="2" />
      <hswl value="0" auto="true" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="20" />
      <speedsound value="0" auto="true" />
      <hdp value="2" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="241" fluidcount="9" />
    <geometry>
      <definition dp="{_q(case["dp_m"])}" units_comment="metres (m)">
        <pointref x="0" y="0" z="0" />
        <pointmin x="-1" y="-1" z="-1" />
        <pointmax x="3.3" y="1.1" z="1.1" />
      </definition>
      <commands>
        <list name="GeometryForNormals">
          <setactive drawpoints="0" drawshapes="1" />
          <setshapemode>actual | bound</setshapemode>
          <setmkbound mk="0" />
          <setnormalinvert invert="true" />
          <drawbox>
            <boxfill>all^top</boxfill>
            <point x="0" y="0" z="0" />
            <endpoint x="{_q(g["tank_length_m"])}" y="{_q(g["tank_width_m"])}" z="{_q(g["tank_height_m"])}" />
            <layers vdp="-0.5" />
          </drawbox>
          <setnormalinvert invert="false" />
          <setmkbound mk="1" />
          <drawbox>
            <boxfill>all^bottom</boxfill>
            <point x="{_q(g["separator_start_x_m"])}" y="{_q(g["separator_y_m"])}" z="0" />
            <endpoint x="{_q(g["separator_end_x_m"])}" y="{_q(g["separator_y_m"] + g["separator_thickness_m"])}" z="{_q(g["separator_height_m"])}" />
            <layers vdp="0.5" />
          </drawbox>
          <shapeout file="hdp" />
          <resetdraw />
        </list>
        <mainlist>
          <runlist name="GeometryForNormals" />
          <setdrawmode mode="full" />
          <setmkbound mk="0" />
          <drawbox>
            <boxfill>all^top</boxfill>
            <point x="0" y="0" z="0" />
            <endpoint x="{_q(g["tank_length_m"])}" y="{_q(g["tank_width_m"])}" z="{_q(g["tank_height_m"])}" />
            <layers vdp="0,1,2" />
          </drawbox>
          <setmkvoid />
          <drawbox>
            <boxfill>solid</boxfill>
            <point x="{_q(g["separator_start_x_m"])}" y="{_q(g["separator_y_m"])}" z="0" />
            <endpoint x="{_q(g["separator_end_x_m"])}" y="{_q(g["separator_y_m"] + g["separator_thickness_m"])}" z="{_q(g["separator_height_m"])}" />
          </drawbox>
          <setmkbound mk="1" />
          <drawbox>
            <boxfill>all^bottom</boxfill>
            <point x="{_q(g["separator_start_x_m"])}" y="{_q(g["separator_y_m"])}" z="0" />
            <endpoint x="{_q(g["separator_end_x_m"])}" y="{_q(g["separator_y_m"] + g["separator_thickness_m"])}" z="{_q(g["separator_height_m"])}" />
            <layers vdp="0,-1,-2" />
          </drawbox>
          <setmkfluid mk="0" />
          <fillbox x="2.1" y="0.1" z="0.2">
            <modefill>void</modefill>
            <point x="{_q(g["reservoir_start_x_m"])}" y="0" z="0" />
            <size x="{_q(g["reservoir_length_m"])}" y="{_q(g["tank_width_m"])}" z="{_q(g["initial_depth_m"])}" />
          </fillbox>
        </mainlist>
      </commands>
    </geometry>
    <normals active="true">
      <norgeometry>
        <geometryfile file="[CaseName]_hdp_Actual.vtk" />
        <distanceh v="2.0" />
        <svshapes v="true" />
      </norgeometry>
    </normals>
  </casedef>
  <execution>
    <parameters>
{_parameter_rows(p)}
      <simulationdomain>
        <posmin x="default - 25%" y="default - 25%" z="default - 25%" />
        <posmax x="default + 25%" y="default + 25%" z="default + 50%" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
'''


def _solver_parameters(background: str, time_max_s: float, time_out_s: float) -> dict[str, Any]:
    if background == "eccentric_obstacle":
        return {
            "SavePosDouble": 0,
            "StepAlgorithm": 1,
            "VerletSteps": 40,
            "Kernel": 1,
            "ViscoTreatment": 1,
            "Visco": 0.1,
            "ViscoBoundFactor": 1,
            "DensityDT": 2,
            "DensityDTvalue": 0.1,
            "Shifting": 0,
            "RigidAlgorithm": 1,
            "FtPause": 0,
            "CoefDtMin": 0.05,
            "DtIni": 0,
            "DtMin": 0,
            "DtFixed": 0,
            "DtAllParticles": 0,
            "TimeMax": _q(time_max_s),
            "TimeOut": _q(time_out_s),
            "MinFluidStop": 0,
            "RhopOutMin": 700,
            "RhopOutMax": 1300,
        }
    if background == "asymmetric_dual_channel":
        return {
            "SavePosDouble": 0,
            "Boundary": 2,
            "SlipMode": 1,
            "NoPenetration": 0,
            "StepAlgorithm": 2,
            "VerletSteps": 40,
            "Kernel": 2,
            "ViscoTreatment": 1,
            "Visco": 0.01,
            "ViscoBoundFactor": 1,
            "DensityDT": 3,
            "DensityDTvalue": 0.1,
            "Shifting": 0,
            "RigidAlgorithm": 1,
            "FtPause": 0,
            "CoefDtMin": 0.05,
            "DtIni": 0,
            "DtMin": 0,
            "DtFixed": 0,
            "DtAllParticles": 0,
            "TimeMax": _q(time_max_s),
            "TimeOut": _q(time_out_s),
            "RhopOutMin": 700,
            "RhopOutMax": 1300,
            "WrnPartsOut": 1,
            "MinFluidStop": 0,
        }
    raise ValueError(f"unknown F1 background: {background}")


def _nominal_case_values(background: str, h_ratio: float = 1.0) -> dict[str, Any]:
    if background == "eccentric_obstacle":
        return {
            "h_ratio": h_ratio,
            "obstacle_offset_y_m": -0.035,
            "obstacle_width_m": 0.12,
            "reservoir_length_m": 0.40,
        }
    if background == "asymmetric_dual_channel":
        return {
            "h_ratio": h_ratio,
            "lower_channel_width_m": 0.34,
            "separator_thickness_m": 0.06,
            "separator_length_m": 0.80,
            "reservoir_length_m": 1.12,
        }
    raise ValueError(f"unknown F1 background: {background}")


def _case_geometry(background: str, values: Mapping[str, Any]) -> dict[str, Any]:
    if background == "eccentric_obstacle":
        tank_l, tank_w, tank_h = MOTHERS[background].tank_extent_m
        offset = float(values.get("obstacle_offset_y_m", -0.035))
        obstacle_width = float(values.get("obstacle_width_m", 0.12))
        obstacle_y = tank_w / 2.0 + offset - obstacle_width / 2.0
        obstacle_x = 0.90
        obstacle_h = 0.45
        fluid_l = float(values.get("reservoir_length_m", 0.40))
        h_ratio = float(values.get("h_ratio", 1.0))
        initial_depth = 0.30 * h_ratio
        if not (0 < obstacle_y < tank_w - obstacle_width):
            raise ValueError("eccentric obstacle leaves the finite side walls")
        if not (0 < initial_depth < tank_h):
            raise ValueError("initial H/H0 is outside the tank")
        return {
            "tank_length_m": tank_l,
            "tank_width_m": tank_w,
            "tank_height_m": tank_h,
            "fluid_length_m": fluid_l,
            "initial_depth_m": initial_depth,
            "obstacle_x_m": obstacle_x,
            "obstacle_y_m": obstacle_y,
            "obstacle_length_m": 0.12,
            "obstacle_width_m": obstacle_width,
            "obstacle_height_m": obstacle_h,
            "obstacle_offset_y_m": offset,
            "initial_fluid_volume_m3": fluid_l * tank_w * initial_depth,
            "finite_wall_faces": list(MOTHERS[background].wall_faces),
            "open_top": True,
        }
    if background == "asymmetric_dual_channel":
        tank_l, tank_w, tank_h = MOTHERS[background].tank_extent_m
        lower = float(values.get("lower_channel_width_m", 0.34))
        thickness = float(values.get("separator_thickness_m", 0.06))
        separator_length = float(values.get("separator_length_m", 0.80))
        reservoir_length = float(values.get("reservoir_length_m", 1.12))
        h_ratio = float(values.get("h_ratio", 1.0))
        initial_depth = 0.55 * h_ratio
        separator_start = 1.25
        separator_end = separator_start + separator_length
        reservoir_start = tank_l - reservoir_length
        if not (0.20 <= lower <= 0.60):
            raise ValueError("lower channel width is outside the resolvable design range")
        if not (0.04 <= thickness <= 0.10):
            raise ValueError("separator thickness is outside the design range")
        if not (0.50 <= separator_length <= 1.10):
            raise ValueError("separator length is outside the design range")
        if not (0.90 <= reservoir_length <= 1.30):
            raise ValueError("reservoir length is outside the design range")
        if separator_end >= reservoir_start:
            raise ValueError("dual-channel separator overlaps the initial reservoir")
        if lower + thickness >= tank_w:
            raise ValueError("dual-channel separator leaves no upper channel")
        if not (0 < initial_depth < tank_h):
            raise ValueError("initial H/H0 is outside the tank")
        return {
            "tank_length_m": tank_l,
            "tank_width_m": tank_w,
            "tank_height_m": tank_h,
            "reservoir_start_x_m": reservoir_start,
            "reservoir_length_m": reservoir_length,
            "initial_depth_m": initial_depth,
            "separator_start_x_m": separator_start,
            "separator_end_x_m": separator_end,
            "separator_length_m": separator_length,
            "separator_y_m": lower,
            "separator_thickness_m": thickness,
            "separator_height_m": 0.70,
            "channel_width_lower_m": lower,
            "channel_width_upper_m": tank_w - lower - thickness,
            "channel_width_ratio_lower_to_upper": lower / (tank_w - lower - thickness),
            "initial_fluid_volume_m3": reservoir_length * tank_w * initial_depth,
            "finite_wall_faces": list(MOTHERS[background].wall_faces) + ["separator_top", "separator_sides"],
            "open_top": True,
        }
    raise ValueError(f"unknown F1 background: {background}")


def _event_window(background: str) -> dict[str, Any]:
    spec = MOTHERS[background]
    H0 = _nominal_case_values(background)["h_ratio"] * (0.30 if background == "eccentric_obstacle" else 0.55)
    t_char = math.sqrt(H0 / G)
    if background == "eccentric_obstacle":
        phases = {
            "release": 0.0,
            "first_obstacle_interaction": 0.45,
            "downstream_arrival": 0.95,
            "remerge_or_return_flow": 1.35,
            "window_end": 1.60,
        }
    else:
        phases = {
            "release": 0.0,
            "first_separator_interaction": 0.65,
            "downstream_remerge": 1.60,
            "return_flow_observable": 3.50,
            "window_end": 6.00,
        }
    return {
        "characteristic_length_m": H0,
        "characteristic_velocity_m_s": math.sqrt(G * H0),
        "characteristic_time_s": t_char,
        "complete_event_window_s": spec.complete_source_tmax_s,
        "save_interval_s": spec.complete_source_tout_s,
        "phase_targets_s": phases,
        "phase_basis": "front travel and remerge milestones are conservative registration targets; acceptance requires observed native data, not these estimates.",
    }


def _observables(background: str) -> dict[str, Any]:
    if background == "eccentric_obstacle":
        split_regions = ["left_of_obstacle", "right_of_obstacle"]
    else:
        split_regions = ["lower_channel", "upper_channel"]
    return {
        "primary": [
            "free_surface_front_quantiles_x_y_z",
            "fluid_center_of_mass_xyz",
            "split_fraction_time_series",
            "downstream_finite_plane_first_arrival_and_net_mass",
            "three_dimensional_mass_and_kinetic_energy_distribution",
        ],
        "secondary": ["velocity_quantiles", "return_flow_fraction", "initial_mass_and_volume_error"],
        "split_regions": split_regions,
        "finite_downstream_plane": {"axis": "x", "placement_rule": "after_remerge_zone_before_downstream_wall", "crossings": "signed_net_and_separate_recrossings"},
        "native_labels": [
            "source_label",
            "destination_time_series",
            "first_passage_interval",
            "residence_time",
            "final_category",
            "failure_reason",
            "unknown_mass",
        ],
        "time_window_required": "release, first interaction, bypass/split, downstream arrival, remerge, and at least one observable return-flow event",
    }


def _error_budget(background: str) -> dict[str, Any]:
    H0 = 0.30 if background == "eccentric_obstacle" else 0.55
    return {
        "status": "starting_engineering_budget_pending_reference_matrix",
        "macro_observable_relative_error": 0.05,
        "event_time_error_fraction_of_characteristic_time": 0.02,
        "event_time_error_absolute_seconds_at_nominal_H0": 0.02 * math.sqrt(H0 / G),
        "save_fraction_of_total_error_budget_max": 0.20,
        "integration_fraction_of_total_error_budget_max": 0.20,
        "applicability": {
            "macro": "5% applies to fixed physical windows and volume-integrated/quantile observables once initial mass and geometry are within the initialization budget.",
            "event_time": "2% applies to first-arrival/remerge/return markers scaled by sqrt(H0/g); it is not a universal per-particle trajectory tolerance and does not certify unresolved local chaos.",
        },
    }


def _validate_background_resolution(background: str, resolution: str) -> None:
    if background not in MOTHERS:
        raise ValueError(f"background must be one of {sorted(MOTHERS)}")
    if resolution not in RESOLUTION_ORDER:
        raise ValueError(f"resolution must be one of {RESOLUTION_ORDER}")


def make_case(
    background: str,
    resolution: str,
    *,
    case_id: str | None = None,
    physical_case_id: str | None = None,
    paired_background_id: str | None = None,
    values: Mapping[str, Any] | None = None,
    lab_root: str | Path | None = None,
    strict_source: bool = True,
) -> dict[str, Any]:
    """Build a fully expanded case dictionary without writing or executing it."""

    _validate_background_resolution(background, resolution)
    values_all = dict(_nominal_case_values(background))
    values_all.update(values or {})
    geometry = _case_geometry(background, values_all)
    event = _event_window(background)
    spec = MOTHERS[background]
    cid = case_id or f"F1_{background}_{resolution}"
    pid = physical_case_id or f"{cid}_physical"
    pair = paired_background_id or f"{pid}_pair"
    dp = DP_BY_BACKGROUND[background][resolution]
    feature = 0.12 if background == "eccentric_obstacle" else geometry["separator_thickness_m"]
    solver = _solver_parameters(background, event["complete_event_window_s"], event["save_interval_s"])
    source = mother_evidence(lab_root, strict=strict_source)
    source_row = next(row for row in source["mother_cases"] if row["source"] == spec.source)
    return {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "case_id": cid,
        "physical_case_id": pid,
        "lineage_group_id": f"F1_{background}_v1",
        "paired_background_id": pair,
        "mechanism_id": background,
        "geometry_family_id": f"F1_GEOM_{background.upper()}_V1",
        "control_family_id": f"F1_CONTROL_{background.upper()}_V1",
        "recipe_id": "F1_DBC_ECCENTRIC_V1" if background == "eccentric_obstacle" else "F1_MDBC_DUAL_CHANNEL_V1",
        "view_id": "native_full_state",
        "attempt_id": None,
        "background": background,
        "resolution": resolution,
        "resolution_role": "reference_matrix" if cid.startswith("F1_REF_") else "planned_production_resolution",
        "dp_m": dp,
        "feature_scale_m": feature,
        "feature_samples": feature / dp,
        "parameter_values": values_all,
        "geometry": geometry,
        "event_window": event,
        "observables": _observables(background),
        "error_budget": _error_budget(background),
        "solver_parameters": solver,
        "source_mother": source_row,
        "generation_status": "definition_only_not_gencase_run",
        "production_status": "not_produced",
        "qualification_status": "unqualified_until_native_reference_evidence",
    }


def write_case(case: Mapping[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """Write one Definition XML and its immutable input sidecar."""

    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    background = str(case["background"])
    xml = _eccentric_xml(case) if background == "eccentric_obstacle" else _dual_xml(case)
    xml_path = out / f"{case['case_id']}_Def.xml"
    meta_path = out / f"{case['case_id']}.metadata.json"
    xml_path.write_text(xml, encoding="utf-8")
    result = dict(case)
    result["definition_path"] = str(xml_path)
    result["definition_sha256"] = sha256_file(xml_path)
    result["metadata_path"] = str(meta_path)
    # Do not put the metadata hash in itself; the runner hashes both files.
    meta_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["metadata_sha256"] = sha256_file(meta_path)
    return result


def preflight_definition(
    definition_path: str | Path,
    metadata_path: str | Path | None = None,
    *,
    require_source_evidence: bool = True,
) -> dict[str, Any]:
    """Audit a generated Definition XML without invoking any solver binary."""

    path = Path(definition_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    root = ET.parse(path).getroot()
    errors: list[str] = []
    warnings: list[str] = []
    casedef = root.find("casedef")
    if casedef is None:
        errors.append("missing casedef")
    geometry = casedef.find("geometry") if casedef is not None else None
    definition = geometry.find("definition") if geometry is not None else None
    commands = geometry.find("commands") if geometry is not None else None
    if definition is None:
        errors.append("missing geometry/definition")
    if commands is None:
        errors.append("missing geometry/commands")
    dp = None
    extent_ok = False
    if definition is not None:
        try:
            dp = float(definition.attrib["dp"])
            pmin = [float(definition.find("pointmin").attrib[k]) for k in ("x", "y", "z")]
            pmax_node = definition.find("pointmax")
            if pmax_node is None:
                errors.append("missing pointmax")
            else:
                pmax = [float(pmax_node.attrib[k]) for k in ("x", "y", "z")]
                extent_ok = all(math.isfinite(a) and math.isfinite(b) and b > a for a, b in zip(pmin, pmax))
                if not extent_ok:
                    errors.append("non-positive or non-finite 3-D definition extent")
        except (KeyError, TypeError, ValueError, AttributeError):
            errors.append("invalid 3-D definition attributes")
    if dp is None or not math.isfinite(dp) or dp <= 0:
        errors.append("dp must be finite and positive")

    parameter_values: dict[str, str] = {}
    parameter_root = root.find("./execution/parameters")
    if parameter_root is None:
        errors.append("missing execution/parameters")
    else:
        for node in parameter_root.findall("parameter"):
            if "key" in node.attrib and "value" in node.attrib:
                parameter_values[node.attrib["key"]] = node.attrib["value"]
    try:
        time_max = float(parameter_values["TimeMax"])
        time_out = float(parameter_values["TimeOut"])
        if time_max <= 0 or time_out <= 0 or time_out >= time_max:
            errors.append("invalid TimeMax/TimeOut")
        if math.isclose(time_max, 0.6, rel_tol=0, abs_tol=1e-12):
            errors.append("0.6 s canary window cannot be used as the F1 complete event window")
    except (KeyError, ValueError):
        errors.append("missing or invalid TimeMax/TimeOut")

    commands_text = ET.tostring(commands, encoding="unicode") if commands is not None else ""
    wall_tokens = ("bottom", "left", "right", "front", "back")
    wall_draws = [
        node
        for node in (commands.findall(".//drawbox") if commands is not None else [])
        if (
            "bottom" in node.findtext("boxfill", default="")
            and all(token in node.findtext("boxfill", default="") for token in wall_tokens[1:])
        )
        or "all^top" in node.findtext("boxfill", default="")
    ]
    if not wall_draws:
        errors.append("no finite bottom plus four side wall drawbox found")
    if "periodic" in commands_text.lower():
        errors.append("periodic topology is not permitted by the F1 finite-wall backgrounds")
    if "drawbox" not in commands_text or "setmkfluid" not in commands_text:
        errors.append("missing fluid or geometry draw commands")
    if "#" in commands_text:
        errors.append("unexpanded GenCase variable remains in definition")

    metadata: dict[str, Any] | None = None
    if metadata_path is None:
        guess = path.with_name(path.name.replace("_Def.xml", ".metadata.json"))
        metadata_path = guess if guess.is_file() else None
    if metadata_path is not None:
        metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        if metadata.get("generation_status") != "definition_only_not_gencase_run":
            errors.append("metadata generation status does not identify an unrun definition")
        if metadata.get("production_status") == "produced":
            errors.append("definition metadata incorrectly claims production")
        if metadata.get("family_id") != FAMILY_ID:
            errors.append("metadata family_id is not F1")
        samples = float(metadata.get("feature_samples", 0.0))
        background = metadata.get("background")
        minimum_samples = 6.0 if background == "eccentric_obstacle" else 3.0
        if samples < minimum_samples:
            errors.append(f"feature resolution {samples:.3g} is below the {minimum_samples:g}-sample floor")
        if metadata.get("source_mother", {}).get("source_definition_sha256") is None:
            errors.append("official source Definition hash is absent")
        if require_source_evidence:
            for key in ("source_definition_sha256", "gencase_log_sha256", "solver_log_sha256"):
                if not metadata.get("source_mother", {}).get(key):
                    errors.append(f"official source evidence hash missing: {key}")
        if metadata.get("event_window", {}).get("complete_event_window_s") != time_max:
            errors.append("XML TimeMax is not bound to the registered complete event window")
    elif require_source_evidence:
        errors.append("generated metadata sidecar is required for F1 source and event binding")

    status = "pass" if not errors else "fail"
    return {
        "schema": "ds-data-02.f1.input-preflight.v1",
        "definition_path": str(path),
        "definition_sha256": sha256_file(path),
        "status": status,
        "solver_invoked": False,
        "gencase_invoked": False,
        "checks": {
            "three_dimensional_extent": extent_ok,
            "finite_wall_faces": bool(wall_draws),
            "complete_event_window_bound": not any("TimeMax" in error or "0.6" in error for error in errors),
            "no_periodic_topology": "periodic" not in commands_text.lower(),
            "feature_resolution": not any("feature resolution" in error for error in errors),
            "official_lineage": not any("official source" in error for error in errors),
        },
        "errors": errors,
        "warnings": warnings,
        "metadata_path": str(metadata_path) if metadata_path is not None else None,
        "parameter_values": parameter_values,
    }


def reference_matrix(
    output_dir: str | Path,
    *,
    lab_root: str | Path | None = None,
    strict_source: bool = True,
) -> dict[str, Any]:
    """Write the required 2 backgrounds × 3 resolutions preflight matrix."""

    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for background in ("eccentric_obstacle", "asymmetric_dual_channel"):
        pid = f"F1_REF_{'ECC' if background == 'eccentric_obstacle' else 'DUAL'}_NOMINAL"
        for resolution in RESOLUTION_ORDER:
            cid = f"{pid}_{resolution.upper()}"
            case = make_case(
                background,
                resolution,
                case_id=cid,
                physical_case_id=pid,
                paired_background_id="F1_REF_PAIR_NOMINAL",
                lab_root=lab_root,
                strict_source=strict_source,
            )
            rows.append(write_case(case, out))
    result = {
        "schema": "ds-data-02.f1.reference-matrix.v1",
        "family_id": FAMILY_ID,
        "generated_at_utc": _utc_now(),
        "status": "definitions_written_preflight_only",
        "qualification_claim": "none",
        "matrix": [
            {
                "case_id": row["case_id"],
                "physical_case_id": row["physical_case_id"],
                "background": row["background"],
                "resolution": row["resolution"],
                "dp_m": row["dp_m"],
                "feature_scale_m": row["feature_scale_m"],
                "feature_samples": row["feature_samples"],
                "complete_event_window_s": row["event_window"]["complete_event_window_s"],
                "save_interval_s": row["event_window"]["save_interval_s"],
                "definition_path": row["definition_path"],
                "definition_sha256": row["definition_sha256"],
                "metadata_path": row["metadata_path"],
                "metadata_sha256": row["metadata_sha256"],
                "solver_status": "not_run",
                "native_evidence": None,
            }
            for row in rows
        ],
        "resolution_identity_rule": "The three resolutions share a physical_case_id and are numerical views, not three independent physical cases.",
        "all_preflight": True,
    }
    reports = []
    for row in rows:
        report = preflight_definition(row["definition_path"], row["metadata_path"], require_source_evidence=strict_source)
        reports.append(report)
    result["preflight"] = reports
    result["all_preflight"] = all(report["status"] == "pass" for report in reports)
    matrix_path = out / "reference_matrix.json"
    matrix_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["path"] = str(matrix_path)
    result["sha256"] = sha256_file(matrix_path)
    return result


def integration_save_plan(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir).expanduser().resolve()
    plan = {
        "schema": "ds-data-02.f1.integration-save-study.v1",
        "family_id": FAMILY_ID,
        "status": "planned_not_run",
        "qualification_claim": "none",
        "background": "asymmetric_dual_channel",
        "physical_case_id": "F1_REF_DUAL_NOMINAL",
        "resolution": "medium",
        "reason_selected": "mDBC dual-channel geometry has the larger wall-normal stencil and the longer complete event window; it is the sensitivity case.",
        "controls": [
            {
                "control_id": "dual_native_dt_save010",
                "purpose": "reference adaptive integration and official save cadence",
                "solver_parameter_overrides": {"DtFixed": 0, "DtIni": 0, "DtMin": 0},
                "time_out_s": 0.01,
            },
            {
                "control_id": "dual_fixed_dt_half_save010",
                "purpose": "independent integration check at half the nominal initial step after runner records native DtIni",
                "solver_parameter_overrides": {"DtFixed": "runner_bound_half_native_DtIni", "DtIni": 0, "DtMin": 0},
                "time_out_s": 0.01,
            },
            {
                "control_id": "dual_native_dt_save005",
                "purpose": "independent output cadence check with identical integration controls",
                "solver_parameter_overrides": {"DtFixed": 0, "DtIni": 0, "DtMin": 0},
                "time_out_s": 0.005,
            },
        ],
        "comparison": {
            "same_geometry_and_initial_state": True,
            "same_background_recipe": True,
            "integrator_and_save_are_separate_factors": True,
            "acceptable_starting_budget": {"macro_relative": 0.05, "event_time_fraction_of_sqrt_H_over_g": 0.02},
            "save_and_integration_budget_each_max_fraction": 0.20,
            "promotion": "Record native dt statistics and compare macro observables plus event markers; do not call a downsampled trajectory an integration study.",
        },
    }
    path = out / "integration_save_plan.json"
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    plan["path"] = str(path)
    plan["sha256"] = sha256_file(path)
    return plan


def _candidate_records() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for background in ("eccentric_obstacle", "asymmetric_dual_channel"):
        short = "ECC" if background == "eccentric_obstacle" else "DUAL"
        background_ordinal = 0
        for index, h_ratio in enumerate((0.9, 1.0, 1.1)):
            for geom_index in range(2):
                if background == "eccentric_obstacle":
                    offsets = (-0.070, 0.035)
                    widths = (0.10, 0.12)
                    reservoirs = (0.35, 0.45)
                    for width_index, width in enumerate(widths):
                        for reservoir_index, reservoir in enumerate(reservoirs):
                            # Two offsets × two obstacle widths × two reservoir
                            # lengths × three H/H0 values = 24 physical cases.
                            offset = offsets[geom_index]
                            background_ordinal += 1
                            ordinal = background_ordinal
                            pid = f"F1_{short}_P{ordinal:02d}"
                            rows.append(
                                _registry_row(
                                    background,
                                    pid,
                                    h_ratio,
                                    {
                                        "obstacle_offset_y_m": offset,
                                        "obstacle_width_m": width,
                                        "reservoir_length_m": reservoir,
                                    },
                                    f"F1_PAIR_{ordinal:02d}",
                                )
                            )
                else:
                    # Two asymmetry levels × two separator lengths × two
                    # reservoir lengths × three H/H0 values = 24 cases.
                    lower_values = (0.34, 0.46)
                    lengths = (0.65, 0.95)
                    reservoirs = (1.00, 1.20)
                    lower = lower_values[geom_index]
                    for length in lengths:
                        for reservoir in reservoirs:
                            background_ordinal += 1
                            ordinal = background_ordinal
                            pid = f"F1_{short}_P{ordinal:02d}"
                            rows.append(
                                _registry_row(
                                    background,
                                    pid,
                                    h_ratio,
                                    {
                                        "lower_channel_width_m": lower,
                                        "separator_length_m": length,
                                        "reservoir_length_m": reservoir,
                                    },
                                    f"F1_PAIR_{ordinal:02d}",
                                )
                            )
    # The loops above intentionally enumerate H as the outer key in the
    # physics input, but the unique identifiers are sufficient for paired
    # backgrounds.  Keep exactly 24 per background and 48 total.
    return rows


def _registry_row(background: str, pid: str, h_ratio: float, values: Mapping[str, Any], pair: str) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.case-registration.v1",
        "case_id": pid,
        "physical_case_id": pid,
        "lineage_group_id": f"F1_{background}_v1",
        "paired_background_id": pair,
        "family_id": FAMILY_ID,
        "mechanism_id": background,
        "geometry_family_id": f"F1_GEOM_{background.upper()}_V1",
        "control_family_id": f"F1_CONTROL_{background.upper()}_V1",
        "recipe_id": "F1_DBC_ECCENTRIC_V1" if background == "eccentric_obstacle" else "F1_MDBC_DUAL_CHANNEL_V1",
        "view_id": "native_full_state",
        "attempt_id": None,
        "status": "pre_registered",
        "production": False,
        "qualification": "none",
        "requested_resolution_set": list(RESOLUTION_ORDER),
        "parameter_values": {"h_ratio": h_ratio, **dict(values)},
        "event_window_s": MOTHERS[background].complete_source_tmax_s,
        "source_evidence_required": True,
        "native_hdf5": None,
        "labels": None,
        "preview": None,
    }


def preregister(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = _candidate_records()
    if len(rows) != 48:
        raise AssertionError(f"expected 48 pre-registered physical cases, got {len(rows)}")
    counts = {background: sum(row["mechanism_id"] == background for row in rows) for background in MOTHERS}
    if counts != {"eccentric_obstacle": 24, "asymmetric_dual_channel": 24}:
        raise AssertionError(f"unexpected background registration counts: {counts}")
    path = out / "case_registry.jsonl"
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    result = {
        "schema": "ds-data-02.f1.pre-registration.v1",
        "family_id": FAMILY_ID,
        "status": "candidate_physics_registered_only",
        "qualification_claim": "none",
        "production_claim": "none",
        "independent_physical_case_count": len(rows),
        "background_counts": counts,
        "resolution_views_are_not_independent_cases": True,
        "path": str(path),
        "sha256": sha256_file(path),
        "records_have_no_solver_or_hdf5_receipts": True,
    }
    return result


def write_family_design(
    family_dir: str | Path,
    *,
    lab_root: str | Path | None = None,
    strict_source: bool = True,
) -> dict[str, Any]:
    """Materialise committed F1 design artefacts and six reference definitions."""

    family = Path(family_dir).expanduser().resolve()
    family.mkdir(parents=True, exist_ok=True)
    evidence = mother_evidence(lab_root, strict=strict_source)
    (family / "source_audit.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    matrix = reference_matrix(family / "definitions", lab_root=lab_root, strict_source=strict_source)
    save_plan = integration_save_plan(family)
    registration = preregister(family)
    card = {
        "schema": "ds-data-02.f1.family-card.v1",
        "family_id": FAMILY_ID,
        "status": "definition_ready_waiting_shared_runner",
        "qualification_claim": "none",
        "production_claim": "none",
        "mechanisms": ["eccentric_obstacle", "asymmetric_dual_channel"],
        "mother_sources": [row["source"] for row in evidence["mother_cases"]],
        "reference_matrix": "definitions/reference_matrix.json",
        "reference_matrix_shape": "2 backgrounds x 3 resolutions",
        "candidate_physical_cases": 48,
        "reference_physical_case_count": 2,
        "event_windows_s": {key: spec.complete_source_tmax_s for key, spec in MOTHERS.items()},
        "error_budget": {key: _error_budget(key) for key in MOTHERS},
        "integration_save_plan": "integration_save_plan.json",
        "raw_output_root": str(DEFAULT_DATA_ATTEMPT),
        "next_executable_task": "obtain shared CPU reservation, run GenCase for six definitions, audit generated XML/particle counts, then submit solver cases through the shared runner",
        "created_at_utc": _utc_now(),
    }
    (family / "family_card.json").write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recipes = {
        "schema": "ds-data-02.f1.qualified-recipes.v1",
        "family_id": FAMILY_ID,
        "status": "planned_unqualified",
        "recipes": [
            {
                "recipe_id": "F1_DBC_ECCENTRIC_V1",
                "background": "eccentric_obstacle",
                "qualified": False,
                "required_scope": "recipe+eccentric_geometry+1.6s_event+primary_observables+resolution",
            },
            {
                "recipe_id": "F1_MDBC_DUAL_CHANNEL_V1",
                "background": "asymmetric_dual_channel",
                "qualified": False,
                "required_scope": "recipe+asymmetric_dual_channel_geometry+6s_event+primary_observables+resolution",
            },
        ],
        "qualification_gate": "native reference evidence and Q-I/Q-N audit; Q-E is optional and no model evaluation is involved",
    }
    (family / "qualified_recipes.json").write_text(json.dumps(recipes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    split_plan = {
        "schema": "ds-data-02.f1.split-plan.v1",
        "family_id": FAMILY_ID,
        "status": "planned_no_cases_assigned",
        "grouping_key": "physical_case_id/lineage_group_id",
        "holdouts": {
            "geometry": "reserve obstacle-width/offset and lower-channel-width/length combinations for geometry holdout",
            "control": "reserve one integration/save control group; controls never count as physical cases",
        },
        "leakage_rule": "resolution views, restarts, windows, and format copies stay in the same physical group",
        "assigned": False,
    }
    (family / "split_plan.json").write_text(json.dumps(split_plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    handoff = f"""# F1 DS-DATA-02 handoff

Status: definition ready; shared CPU GenCase reservation and runner execution are pending.

The official v5.4 mothers were read from the historical read-only lab and are
bound in `source_audit.json`.  The successful records are actual 3-D canaries:

- `main/01_DamBreak`: Dp 0.020 m, 9,600 fluid + 7,846 fixed particles,
  1.60 x 0.67 x 0.40 m tank, nominal 0.40 x 0.67 x 0.30 m initial fill;
  the realised initial particle bounds are 0.03..0.41 x 0.03..0.65 x
  0.03..0.31 m, DBC.
- `mdbc/04_Dambreak`: Dp 0.020 m, 79,380 fluid + 93,042 fixed particles,
  3.22 x 1.00 x 1.00 m tank, nominal right-side fill about 1.228 x 1.00 x
  0.55 m; realised initial particle bounds are 2.02..3.20 x 0.02..0.98 x
  0.02..0.54 m, mDBC.

The historical 0.6 s runs have seven frames and are canary evidence only.  The
reference matrix therefore binds 1.6 s for the eccentric obstacle and 6.0 s for
the dual-channel event, with the mother save cadence of 0.01 s.  It contains
two backgrounds at coarse/medium/fine Dp values chosen from local feature
scales; Dp is not a metadata-only label.

`case_registry.jsonl` has 48 candidate physical cases (24 per background).
They are pre-registrations: no row claims a solver attempt, HDF5, labels,
preview, Q-I, Q-N, or production status.  `integration_save_plan.json` keeps
the sensitive dual-channel medium case for separate native-dt, half-dt, and
save-cadence checks.  The starting engineering budgets are 5% for macro
observables and 2% of sqrt(H0/g) for event times; they are not universal SPH
tolerances.

Next executable task: obtain the shared CPU reservation, run GenCase only for
the six definitions, bind actual generated XML and particle counts, then submit
the six solver jobs through the shared runner.  This worktree never starts a
GPU or solver process.
"""
    (family / "FAMILY_HANDOFF.md").write_text(handoff, encoding="utf-8")
    return {
        "family_dir": str(family),
        "source_audit": str(family / "source_audit.json"),
        "reference_matrix": str(family / "definitions/reference_matrix.json"),
        "integration_save_plan": str(family / "integration_save_plan.json"),
        "case_registry": str(family / "case_registry.jsonl"),
        "family_card": str(family / "family_card.json"),
        "registration": registration,
        "matrix": matrix,
        "save_plan": save_plan,
        "git_commit": _git_commit(),
    }


def write_runner_request(
    family_dir: str | Path,
    *,
    lab_root: str | Path | None = None,
    data_attempt_root: str | Path = DEFAULT_DATA_ATTEMPT,
    launch_commit: str | None = None,
) -> dict[str, Any]:
    """Prepare a runner-only request with launch commit and input hashes."""

    family = Path(family_dir).expanduser().resolve()
    matrix_path = family / "definitions/reference_matrix.json"
    if not matrix_path.is_file():
        raise FileNotFoundError("run reference-matrix before preparing runner request")
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    if not matrix.get("all_preflight"):
        raise ValueError("reference matrix preflight did not pass")
    source = json.loads((family / "source_audit.json").read_text(encoding="utf-8"))
    input_files: list[dict[str, Any]] = []

    def add_input(path: Path, role: str, *, root: Path | None = None) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        input_files.append(
            {
                "role": role,
                "path": _relative_or_absolute(path, root),
                "sha256": sha256_file(path),
            }
        )

    add_input(SCRIPT_PATH, "generator", root=CURRENT_WORKTREE)
    add_input(family / "source_audit.json", "source_audit", root=CURRENT_WORKTREE)
    add_input(family / "integration_save_plan.json", "integration_save_plan", root=CURRENT_WORKTREE)
    add_input(matrix_path, "reference_matrix", root=CURRENT_WORKTREE)
    add_input(family / "case_registry.jsonl", "candidate_registry", root=CURRENT_WORKTREE)
    for row in matrix["matrix"]:
        add_input(Path(row["definition_path"]), "definition_xml", root=CURRENT_WORKTREE)
        add_input(Path(row["metadata_path"]), "definition_metadata", root=CURRENT_WORKTREE)
    for mother in source["mother_cases"]:
        for role in ("source_definition", "gencase_log", "solver_log"):
            path = Path(source["read_only_lab_root"]) / mother[role]
            add_input(path, f"official_{role}")
        stats_path = Path(source["read_only_lab_root"]) / mother["actual_successful_run"]["initial_particle_stats_csv"]
        add_input(stats_path, "official_initial_particle_stats_csv")

    cases = []
    attempt_root = Path(data_attempt_root).expanduser().resolve()
    for row in matrix["matrix"]:
        case_id = row["case_id"]
        cases.append(
            {
                "case_id": case_id,
                "physical_case_id": row["physical_case_id"],
                "mechanism_id": row["background"],
                "resolution": row["resolution"],
                "definition_path": row["definition_path"],
                "definition_sha256": row["definition_sha256"],
                "action": "gencase_then_solver",
                "solver_launch_authority": "shared_ds_data_02_runner_only",
                "raw_output_root": str(attempt_root / case_id),
                "tmax_s": row["complete_event_window_s"],
                "tout_s": row["save_interval_s"],
                "attempt_id": None,
                "status": "request_pending_shared_runner",
            }
        )
    estimated: list[dict[str, Any]] = []
    for row in matrix["matrix"]:
        mother = MOTHERS[row["background"]]
        scale = (mother.successful_dp_m / row["dp_m"]) ** 3
        time_scale = row["complete_event_window_s"] / mother.successful_tmax_s
        baseline_gpu_s = (1.512507 if row["background"] == "eccentric_obstacle" else 6.648588) * scale * time_scale
        estimated.append(
            {
                "case_id": row["case_id"],
                "gpu_seconds_upper_estimate": round(baseline_gpu_s * 1.5, 3),
                "basis": "historical successful v5.4 canary simulation runtime scaled by (Dp_mother/Dp)^3 and event-window ratio, with 1.5x planning margin; measure actual runner receipt",
            }
        )
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "campaign_id": "DS-DATA-02",
        "request_id": "F1_REFERENCE_MATRIX_PENDING_ATTEMPT_IDS",
        "created_at_utc": _utc_now(),
        "launch_commit": launch_commit or _git_commit(),
        "generator_script": _relative_or_absolute(SCRIPT_PATH, CURRENT_WORKTREE),
        "read_only_lab_root": source["read_only_lab_root"],
        "raw_output_root": str(attempt_root),
        "resource_guard": {
            "solver_invoked_by_generator": False,
            "gpu_launch_allowed_here": False,
            "cpu_gencase_status": "awaiting_shared_cpu_reservation",
            "shared_runner_required": True,
            "foreign_processes_protected": True,
        },
        "source_binding": {
            "official_v54_mothers": [mother["mother_id"] for mother in source["mother_cases"]],
            "source_definition_and_actual_log_hashes_in_input_files": True,
            "canary_runs_are_not_complete_event_evidence": True,
        },
        "reference_matrix": {
            "background_count": 2,
            "resolution_count_per_background": 3,
            "case_count": len(cases),
            "physical_case_count": 2,
            "resolution_views_are_not_independent_physical_cases": True,
        },
        "cases": cases,
        "integration_save_controls": "integration_save_plan.json",
        "input_files": input_files,
        "estimated_cost": {
            "gpu_seconds_by_case": estimated,
            "reference_matrix_gpu_hours_upper_estimate": round(sum(x["gpu_seconds_upper_estimate"] for x in estimated) / 3600.0, 3),
            "cpu_gencase": "pending reservation; bounded CPU GenCase only, no solver",
            "storage": "runner must report raw bytes and refuse output outside raw_output_root",
        },
        "qualification_claim": "none_until_actual_native_receipts",
        "production_claim": "none",
    }
    path = family / "runner_request.json"
    path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    request["path"] = str(path)
    request["sha256"] = sha256_file(path)

    # The shared runtime accepts one concrete CPU request at a time.  Keep a
    # ready-to-submit coarse eccentric mother request beside the matrix
    # request.  It is intentionally GenCase-only; the parent runner will
    # replace {attempt_root} with its unique external output directory.
    first = next(row for row in matrix["matrix"] if row["case_id"] == "F1_REF_ECC_NOMINAL_COARSE")
    first_meta = Path(first["metadata_path"])
    first_mother = next(row for row in source["mother_cases"] if row["source"] == "main/01_DamBreak")
    gencase_binary = Path(source["read_only_lab_root"]) / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
    definition_prefix = str(Path(first["definition_path"]).with_suffix(""))
    # GenCase takes a Definition prefix without the .xml extension.  Its
    # output prefix is outside the worktree and is filled by the shared
    # runner, preserving raw generated XML/BI4/VTK products.
    gencase_request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": "F1_REF_ECC_NOMINAL_COARSE",
        "attempt_id": "gencase-ref-ecc-coarse-v1",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "command": [
            str(gencase_binary),
            definition_prefix,
            "{attempt_root}/F1_REF_ECC_NOMINAL_COARSE",
            "-save:all",
        ],
        "cwd": str(gencase_binary.parent),
        "max_wall_seconds": 120,
        "cpu_threads": 16,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "input_files": [
            str(Path(first["definition_path"])),
            str(first_mother_path := Path(source["read_only_lab_root"]) / first_mother["source_definition"]),
            str(Path(first_mother["gencase_log"] if Path(first_mother["gencase_log"]).is_absolute() else Path(source["read_only_lab_root"]) / first_mother["gencase_log"])),
            str(Path(first_mother["solver_log"] if Path(first_mother["solver_log"]).is_absolute() else Path(source["read_only_lab_root"]) / first_mother["solver_log"])),
            str(Path(first_mother["actual_successful_run"]["initial_particle_stats_csv"] if Path(first_mother["actual_successful_run"]["initial_particle_stats_csv"]).is_absolute() else Path(source["read_only_lab_root"]) / first_mother["actual_successful_run"]["initial_particle_stats_csv"])),
            str(first_meta),
            str(SCRIPT_PATH),
        ],
        "worktree_root": str(CURRENT_WORKTREE),
        "launch_commit": launch_commit or _git_commit(),
        "source_mother": first_mother["mother_id"],
        "definition_sha256": first["definition_sha256"],
        "generation_status": "definition_written_not_gencase_run",
        "solver_launch_forbidden": True,
        "raw_output_root": str(Path(data_attempt_root).expanduser().resolve()),
        "request_note": "Submit through scripts/ds_data02_runtime.py; do not run this argv directly. The shared runner creates the external attempt root and records the actual GenCase particle counts.",
    }
    gencase_path = family / "gencase_request.json"
    gencase_path.write_text(json.dumps(gencase_request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    request["gencase_request"] = str(gencase_path)
    request["gencase_request_sha256"] = sha256_file(gencase_path)
    return request


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("source-audit")
    p.add_argument("--lab-root", type=Path, default=None)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--allow-missing", action="store_true")
    p = sub.add_parser("generate")
    p.add_argument("--background", choices=sorted(MOTHERS), required=True)
    p.add_argument("--resolution", choices=RESOLUTION_ORDER, required=True)
    p.add_argument("--case-id", default=None)
    p.add_argument("--physical-case-id", default=None)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--lab-root", type=Path, default=None)
    p.add_argument("--allow-missing", action="store_true")
    p = sub.add_parser("preflight")
    p.add_argument("definition", type=Path)
    p.add_argument("--metadata", type=Path, default=None)
    p.add_argument("--allow-missing-source", action="store_true")
    p = sub.add_parser("design")
    p.add_argument("--family-dir", type=Path, default=FAMILY_DIR)
    p.add_argument("--lab-root", type=Path, default=None)
    p.add_argument("--allow-missing", action="store_true")
    p = sub.add_parser("runner-request")
    p.add_argument("--family-dir", type=Path, default=FAMILY_DIR)
    p.add_argument("--data-attempt-root", type=Path, default=DEFAULT_DATA_ATTEMPT)
    p.add_argument("--launch-commit", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "source-audit":
        result = mother_evidence(args.lab_root, strict=not args.allow_missing)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok", "path": str(args.output), "sha256": sha256_file(args.output)}))
        return 0
    if args.command == "generate":
        case = make_case(
            args.background,
            args.resolution,
            case_id=args.case_id,
            physical_case_id=args.physical_case_id,
            lab_root=args.lab_root,
            strict_source=not args.allow_missing,
        )
        result = write_case(case, args.output)
        print(json.dumps({"status": "definition_written", "case_id": result["case_id"], "definition": result["definition_path"], "sha256": result["definition_sha256"]}))
        return 0
    if args.command == "preflight":
        result = preflight_definition(args.definition, args.metadata, require_source_evidence=not args.allow_missing_source)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "pass" else 1
    if args.command == "design":
        result = write_family_design(args.family_dir, lab_root=args.lab_root, strict_source=not args.allow_missing)
        print(json.dumps({"status": "design_written", "family_dir": result["family_dir"], "matrix": result["reference_matrix"], "registry": result["case_registry"]}, indent=2))
        return 0
    if args.command == "runner-request":
        result = write_runner_request(args.family_dir, data_attempt_root=args.data_attempt_root, launch_commit=args.launch_commit)
        print(json.dumps({"status": "request_written", "path": result["path"], "launch_commit": result["launch_commit"], "sha256": result["sha256"]}, indent=2))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
