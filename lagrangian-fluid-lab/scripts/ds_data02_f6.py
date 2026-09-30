#!/usr/bin/env python3
"""DS-DATA-02 F6 generator, bounded GenCase auditor, and request builder.

F6 is intentionally self contained.  It writes only the F6 family files and
never starts a DualSPHysics solver.  GenCase requests are ordinary JSON
requests for the shared DS-DATA-02 runtime; qualification requests are
registered for the parent process to submit through that runtime.

The two new parents are a simple six degree of freedom free body in a finite
still-water tank and a finite-tank regular-wave excitation with the same kind
of free body.  Both use the native RigidAlgorithm=1 path and contain no
Chrono/contact configuration.  The old DS-DATA-01 13.57 million-particle
floating-box trajectory is recorded as a performance reference only and is
never counted as a reusable F6 case.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA = "ds-data-02.f6.family.v1"
GENERATOR_VERSION = "ds_data02_f6.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6"
RAW_OUTPUT_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/case/attempt")
HISTORICAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
OFFICIAL_ROOT = HISTORICAL_ROOT / "vendor/official/DualSPHysics_v5.4"
BIN_ROOT = OFFICIAL_ROOT / "bin/linux"
GENCASE_BINARY = BIN_ROOT / "GenCase_linux64"
SOLVER_BINARY = BIN_ROOT / "DualSPHysics5.4_linux64"
FLOATING_INFO_BINARY = BIN_ROOT / "FloatingInfo_linux64"
COMPUTE_FORCES_BINARY = BIN_ROOT / "ComputeForces_linux64"
RUNTIME_SOURCE = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime.py")
PARENT_WINDOW_S = [0.0, 12.0]
PARENT_CONTROL_DT_S = 0.01
PARENT_CONTROL_ROWS = int(round((PARENT_WINDOW_S[1] - PARENT_WINDOW_S[0]) / PARENT_CONTROL_DT_S)) + 1
PARENT_OUTPUT_DT_S = 0.05
MIN_TRANSVERSE_LAYERS = 10

PARENT_SIMPLE_ID = "F6_SIMPLE_FREE_RESPONSE_PARENT"
PARENT_WAVE_ID = "F6_WAVE_NO_CONTACT_PARENT"

MECHANISMS: dict[str, dict[str, Any]] = {
    "simple_free_response": {
        "mechanism_id": "simple_free_response",
        "name_zh": "简单三维自由浮体响应",
        "geometry_family_id": "F6_BOX_TANK_FREE_BODY",
        "control_family_id": "F6_CTRL_INITIAL_RELEASE",
        "coordinate_frame_id": "tank_attached_inertial",
        "source_template": "main/11_Floating/CaseFloating_Def.xml",
        "description": "有限三维槽内箱浮体，初始偏离静水排水平衡后无外部驱动释放，观察 heave/roll/pitch 的衰减响应。",
        "event_sequence": ["initial_still_water", "release_at_zero", "first_downcrossing", "successive_response_peaks", "decay_tail", "final_mass_and_momentum_audit"],
    },
    "wave_no_contact": {
        "mechanism_id": "wave_no_contact",
        "name_zh": "无接触规则波浮体激励",
        "geometry_family_id": "F6_BOX_TANK_WAVE_PADDLE",
        "control_family_id": "F6_CTRL_REGULAR_PISTON_WAVE",
        "coordinate_frame_id": "world_tank_and_tank_attached_observations",
        "source_template": "main/12_FloatingWaves/CaseFloatingWavesVal2_Def.xml",
        "description": "有限三维槽内 piston regular wave 激励自由箱浮体；浮体与侧壁、挡板和 Chrono 接触均不启用。",
        "event_sequence": ["initial_still_water", "wave_ramp", "first_wave_arrival", "steady_wave_cycles", "last_cycle_and_decay", "final_mass_and_momentum_audit"],
    },
}

RESOLUTION_LADDERS: dict[str, list[dict[str, Any]]] = {
    "simple_free_response": [
        {"resolution_id": "coarse", "dp_m": 0.080, "feature_cells": 7, "purpose": "initialization and cost bound"},
        {"resolution_id": "medium", "dp_m": 0.060, "feature_cells": 10, "purpose": "parent qualification candidate"},
        {"resolution_id": "fine", "dp_m": 0.045, "feature_cells": 14, "purpose": "spatial reference"},
    ],
    "wave_no_contact": [
        {"resolution_id": "coarse", "dp_m": 0.080, "feature_cells": 7, "purpose": "initialization and cost bound"},
        {"resolution_id": "medium", "dp_m": 0.060, "feature_cells": 10, "purpose": "parent qualification candidate"},
        {"resolution_id": "fine", "dp_m": 0.045, "feature_cells": 14, "purpose": "spatial reference"},
    ],
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_relative(path: Path, root: Path = HISTORICAL_ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _runner_receipt_path(case_id: str, attempt_id: str) -> Path:
    return RAW_OUTPUT_ROOT.parent.parent / case_id / attempt_id / "execution-receipt.json"


def _compact_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "pending", "receipt_path": str(path)}
    try:
        receipt = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "unreadable", "receipt_path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    return {
        "status": receipt.get("status"),
        "receipt_path": str(path),
        "attempt_id": receipt.get("request", {}).get("attempt_id"),
        "request_sha256": receipt.get("request_sha256"),
        "runner_sha256": receipt.get("runner_sha256"),
        "git_at_launch": receipt.get("git_at_launch"),
        "input_hashes_at_launch": receipt.get("input_hashes_at_launch"),
        "input_hashes_after_run": receipt.get("input_hashes_after_run"),
        "output_root": receipt.get("output_root"),
        "command": receipt.get("command"),
        "returncode": receipt.get("returncode"),
        "termination_reason": receipt.get("termination_reason"),
        "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"),
        "total_particles": receipt.get("total_particles"),
        "fluid_particles": receipt.get("fluid_particles"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "bytes": receipt.get("bytes"),
        "stdout_sha256": receipt.get("stdout_sha256"),
    }


def _next_parent_attempt(case_id: str, maximum: int = 4) -> tuple[str, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    latest = 0
    for number in range(1, maximum + 1):
        attempt_id = f"{case_id}_GENCASE_{number:02d}"
        compact = _compact_receipt(_runner_receipt_path(case_id, attempt_id))
        if compact.get("status") == "pending":
            break
        latest = number
        attempts.append({"attempt_id": attempt_id, **compact})
        if compact.get("status") == "completed" and int(compact.get("fluid_particles") or 0) > 0:
            return attempt_id, attempts
    number = min(latest + 1, maximum)
    return f"{case_id}_GENCASE_{number:02d}", attempts


def _generated_prefix(receipt: Mapping[str, Any]) -> Path | None:
    command = receipt.get("command")
    if isinstance(command, list) and len(command) >= 3 and isinstance(command[2], str):
        return Path(command[2]).resolve()
    output_root = receipt.get("output_root")
    if isinstance(output_root, str):
        candidates = sorted(Path(output_root).glob("*.xml"))
        if candidates:
            return candidates[0].with_suffix("")
    return None


def _vtk_points(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    marker = data.find(b"POINTS ")
    if marker < 0:
        raise ValueError(f"missing VTK POINTS block: {path}")
    end = data.find(b"\n", marker)
    header = data[marker:end].split()
    if len(header) < 3 or header[2].lower() != b"float":
        raise ValueError(f"unsupported VTK point representation: {path}")
    count = int(header[1])
    start = end + 1
    values = struct.unpack_from(">" + "f" * count * 3, data, start)
    return [(float(values[i]), float(values[i + 1]), float(values[i + 2])) for i in range(0, len(values), 3)]


def _fmt(value: float) -> str:
    return f"{value:.12g}"


def _parent_specs() -> dict[str, dict[str, Any]]:
    return {
        "simple_free_response": {
            "case_id": PARENT_SIMPLE_ID,
            "mechanism_id": "simple_free_response",
            "dp_m": 0.060,
            "tank": {"length_m": 5.5, "width_m": 1.6, "height_m": 1.3},
            "water_level_m": 0.58,
            "body": {
                "kind": "box",
                "mkbound": 50,
                "point_m": [2.10, 0.50, 0.48],
                "size_m": [0.80, 0.60, 0.40],
                "mass_kg": 100.0,
                "initial_pose": {"center_m": [2.50, 0.80, 0.68], "orientation_euler_deg": [0.0, 0.0, 0.0]},
                "initial_offset_m": {"heave": 0.10, "roll": 0.0, "pitch": 0.0},
            },
            "fluid_fill": {"seed_m": [1.0, 0.80, 0.30], "point_m": [0.06, 0.06, 0.06], "size_m": [5.38, 1.48, 0.52]},
            "control": {"mode": "initial_release", "release_time_s": 0.0, "wave_height_m": 0.0, "wave_period_s": None},
            "complexity_factor": 1.05,
        },
        "wave_no_contact": {
            "case_id": PARENT_WAVE_ID,
            "mechanism_id": "wave_no_contact",
            "dp_m": 0.060,
            "tank": {"length_m": 6.0, "width_m": 1.6, "height_m": 1.3},
            "water_level_m": 0.55,
            "body": {
                "kind": "box",
                "mkbound": 50,
                "point_m": [2.60, 0.50, 0.50],
                "size_m": [0.80, 0.60, 0.40],
                "mass_kg": 95.0,
                "initial_pose": {"center_m": [3.00, 0.80, 0.70], "orientation_euler_deg": [0.0, 0.0, 0.0]},
                "initial_offset_m": {"heave": 0.15, "roll": 0.0, "pitch": 0.0},
            },
            "fluid_fill": {"seed_m": [1.0, 0.80, 0.28], "point_m": [0.12, 0.06, 0.06], "size_m": [5.78, 1.48, 0.49]},
            "paddle": {"point_m": [0.0, 0.0, 0.0], "size_m": [0.10, 1.60, 1.20], "mkbound": 10},
            "control": {"mode": "regular_piston_wave", "release_time_s": 0.0, "wave_height_m": 0.08, "wave_period_s": 1.25, "ramp_periods": 3},
            "complexity_factor": 1.20,
        },
    }


def _write_control(path: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    control = spec["control"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# DS-DATA-02 F6 control ledger; first column is physical time in seconds\n")
        writer = csv.writer(handle)
        writer.writerow(["time_s", "mode", "release_time_s", "heave_offset_m", "wave_height_m", "wave_period_s", "ramp_periods"])
        for index in range(PARENT_CONTROL_ROWS):
            time_s = index * PARENT_CONTROL_DT_S
            period = "" if control.get("wave_period_s") is None else _fmt(float(control["wave_period_s"]))
            writer.writerow([
                _fmt(time_s), control["mode"], _fmt(float(control["release_time_s"])),
                _fmt(float(spec["body"]["initial_offset_m"]["heave"])),
                _fmt(float(control["wave_height_m"])), period,
                _fmt(float(control.get("ramp_periods", 0))),
            ])
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "rows": PARENT_CONTROL_ROWS,
            "time_window_s": list(PARENT_WINDOW_S), "dt_s": PARENT_CONTROL_DT_S}


def _write_native(path: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    body = spec["body"]
    mechanism = str(spec["mechanism_id"])
    payload = {
        "schema": "ds-data-02.f6.native_input.v1",
        "family_id": "F6",
        "case_id": spec["case_id"],
        "mechanism_id": mechanism,
        "solver_dimension": 3,
        "coordinate_frame_id": MECHANISMS[mechanism]["coordinate_frame_id"],
        "solver_parameters": {
            "SavePosDouble": 1, "StepAlgorithm": 2, "Kernel": 2, "ViscoTreatment": 2,
            "Visco": 1.0e-6, "DensityDT": 2, "DensityDTvalue": 0.1, "Shifting": 0,
            "RigidAlgorithm": 1, "FtPause": 0.0, "DtFixed": 0.0, "TimeMax": PARENT_WINDOW_S[1],
            "TimeOut": PARENT_OUTPUT_DT_S, "PartsOutMax": 1.0, "RhopOutMin": 700.0, "RhopOutMax": 1300.0,
        },
        "rigid_body": {
            "floatingtype": 2,
            "body_type": "native_rigid_free_body",
            "mass_kg": body["mass_kg"],
            "volume_m3": math.prod(body["size_m"]),
            "density_ratio_to_water": body["mass_kg"] / (math.prod(body["size_m"]) * 1000.0),
            "initial_pose": body["initial_pose"],
            "required_state_fields": ["pose", "orientation", "linear_velocity", "angular_velocity", "mass", "inertia", "force", "torque"],
            "state_sources": ["generated_execution_particles.floating", "FloatingInfo", "ComputeForces"],
        },
        "fluid_ledger": {"fluidtype": 3, "density_kg_m3": 1000.0, "mass_per_particle_from_generated_xml": True},
        "contact_policy": {"chrono": False, "contact_solver": False, "RigidAlgorithm": 1, "wall_contact": "not a mechanism; body placed clear of finite walls"},
        "source_template": _source_relative(OFFICIAL_ROOT / ("examples/" + MECHANISMS[mechanism]["source_template"])),
    }
    write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}


def _write_normal(path: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    mechanism = str(spec["mechanism_id"])
    payload = {
        "schema": "ds-data-02.f6.normal_geometry_binding.v1",
        "family_id": "F6",
        "case_id": spec["case_id"],
        "mechanism_id": mechanism,
        "normal_source": "GenCase *_Actual.vtk finite geometry generated from this Definition; no post-hoc wall projection",
        "geometry_semantics": {"outer_wall": "finite bottom,left,right,front,back", "free_surface": "open top", "floating_body": "mkbound=50", "paddle": "mkbound=10" if "paddle" in spec else None},
        "normal_file_required_in_solver_request": "generated prefix + '__Actual.vtk'",
        "normal_audit": {"finite_wall_faces": ["bottom", "left", "right", "front", "back"], "body_clearance_is_physical_input": True},
    }
    write_json(path, payload)
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}


def _definition_xml(spec: Mapping[str, Any]) -> str:
    tank = spec["tank"]
    body = spec["body"]
    fluid = spec["fluid_fill"]
    mechanism = str(spec["mechanism_id"])
    dp = float(spec["dp_m"])
    body_point = body["point_m"]
    body_size = body["size_m"]
    wall_fill = "bottom|left|right|front|back"
    paddle = spec.get("paddle")
    paddle_block = ""
    if paddle:
        pp, ps = paddle["point_m"], paddle["size_m"]
        paddle_block = f'''\n                    <setdrawmode mode="full" />\n                    <setmkbound mk="{int(paddle["mkbound"])}" />\n                    <drawbox cmt="Wave piston">\n                        <boxfill>solid</boxfill>\n                        <point x="{_fmt(pp[0])}" y="{_fmt(pp[1])}" z="{_fmt(pp[2])}" />\n                        <size x="{_fmt(ps[0])}" y="{_fmt(ps[1])}" z="{_fmt(ps[2])}" />\n                    </drawbox>'''
    wave_special = ""
    if paddle:
        control = spec["control"]
        wave_special = f'''\n            <special>\n                <wavepaddles>\n                    <piston>\n                        <mkbound value="{int(paddle["mkbound"])}" />\n                        <waveorder value="2" />\n                        <start value="0" />\n                        <duration value="0" />\n                        <depth value="{_fmt(float(spec["water_level_m"]))}" />\n                        <_fixeddepth value="0" />\n                        <pistondir x="1" y="0" z="0" />\n                        <waveheight value="{_fmt(float(control["wave_height_m"]))}" />\n                        <waveperiod value="{_fmt(float(control["wave_period_s"]))}" />\n                        <phase value="0" />\n                        <ramp value="{_fmt(float(control["ramp_periods"]))}" />\n                        <savemotion periods="8" periodsteps="20" xpos="3.4" zpos="-{_fmt(float(spec["water_level_m"]))}" />\n                    </piston>\n                </wavepaddles>\n            </special>'''
    source_comment = MECHANISMS[mechanism]["source_template"]
    return f'''<?xml version="1.0" encoding="UTF-8" ?>
<!-- DS-DATA-02 F6 generated parent: {mechanism}; official syntax reference: {source_comment}. -->
<case>
    <casedef>
        <constantsdef>
            <gravity x="0" y="0" z="-9.81" units_comment="m/s^2" />
            <rhop0 value="1000" units_comment="kg/m^3" />
            <rhopgradient value="3" />
            <hswl value="0" auto="true" />
            <gamma value="7" />
            <speedsystem value="0" auto="true" />
            <coefsound value="20" />
            <speedsound value="0" auto="true" />
            <coefh value="1.2" />
            <cflnumber value="0.2" />
        </constantsdef>
        <mkconfig boundcount="230" fluidcount="9">
            <mkorientfluid mk="0" orient="Xyz" />
        </mkconfig>
        <geometry>
            <definition dp="{_fmt(dp)}">
                <pointref x="0" y="0" z="0" />
                <pointmin x="-0.2" y="-0.2" z="-0.1" />
                <pointmax x="{_fmt(float(tank["length_m"]))}" y="{_fmt(float(tank["width_m"]))}" z="{_fmt(float(tank["height_m"]))}" />
            </definition>
            <commands>
                <mainlist>
                    <setshapemode>dp | real | bound</setshapemode>
                    <setdrawmode mode="face" />{paddle_block}
                    <setmkbound mk="20" />
                    <drawbox cmt="Finite tank walls">
                        <boxfill>{wall_fill}</boxfill>
                        <point x="0" y="0" z="0" />
                        <size x="{_fmt(float(tank["length_m"]))}" y="{_fmt(float(tank["width_m"]))}" z="{_fmt(float(tank["height_m"]))}" />
                    </drawbox>
                    <setdrawmode mode="full" />
                    <setmkbound mk="{int(body["mkbound"])}" />
                    <drawbox cmt="Free rigid body">
                        <boxfill>solid</boxfill>
                        <point x="{_fmt(float(body_point[0]))}" y="{_fmt(float(body_point[1]))}" z="{_fmt(float(body_point[2]))}" />
                        <size x="{_fmt(float(body_size[0]))}" y="{_fmt(float(body_size[1]))}" z="{_fmt(float(body_size[2]))}" />
                    </drawbox>
                    <setmkfluid mk="0" />
                    <fillbox x="{_fmt(float(fluid["seed_m"][0]))}" y="{_fmt(float(fluid["seed_m"][1]))}" z="{_fmt(float(fluid["seed_m"][2]))}">
                        <modefill>void</modefill>
                        <point x="{_fmt(float(fluid["point_m"][0]))}" y="{_fmt(float(fluid["point_m"][1]))}" z="{_fmt(float(fluid["point_m"][2]))}" />
                        <size x="{_fmt(float(fluid["size_m"][0]))}" y="{_fmt(float(fluid["size_m"][1]))}" z="{_fmt(float(fluid["size_m"][2]))}" />
                    </fillbox>
                    <shapeout file="" reset="true" />
                </mainlist>
            </commands>
        </geometry>
        <floatings>
            <floating mkbound="{int(body["mkbound"])}">
                <massbody value="{_fmt(float(body["mass_kg"]))}" />
                <translationDOF x="1" y="1" z="1" />
                <rotationDOF x="1" y="1" z="1" />
            </floating>
        </floatings>
    </casedef>
    <execution>{wave_special}
        <parameters>
            <parameter key="SavePosDouble" value="1" />
            <parameter key="StepAlgorithm" value="2" />
            <parameter key="VerletSteps" value="40" />
            <parameter key="Kernel" value="2" />
            <parameter key="ViscoTreatment" value="2" />
            <parameter key="Visco" value="0.000001" />
            <parameter key="ViscoBoundFactor" value="1" />
            <parameter key="DensityDT" value="2" />
            <parameter key="DensityDTvalue" value="0.1" />
            <parameter key="Shifting" value="0" />
            <parameter key="RigidAlgorithm" value="1" comment="native SPH rigid body; external contact backend is disabled" />
            <parameter key="FtPause" value="0" />
            <parameter key="CoefDtMin" value="0.05" />
            <parameter key="DtIni" value="0" />
            <parameter key="DtMin" value="0" />
            <parameter key="DtFixed" value="0" />
            <parameter key="DtFixedFile" value="NONE" />
            <parameter key="DtAllParticles" value="0" />
            <parameter key="TimeMax" value="{_fmt(PARENT_WINDOW_S[1])}" />
            <parameter key="TimeOut" value="{_fmt(PARENT_OUTPUT_DT_S)}" />
            <parameter key="PartsOutMax" value="1" />
            <parameter key="RhopOutMin" value="700" />
            <parameter key="RhopOutMax" value="1300" />
            <simulationdomain>
                <posmin x="default" y="default" z="default" />
                <posmax x="default" y="default" z="default + 20%" />
            </simulationdomain>
        </parameters>
    </execution>
</case>
'''


def _write_definition(path: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_definition_xml(spec), encoding="utf-8")
    ET.parse(path)
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "solver_dimension_declared": 3}


def _official_template_record(spec: Mapping[str, Any]) -> dict[str, Any]:
    mechanism = str(spec["mechanism_id"])
    path = OFFICIAL_ROOT / ("examples/" + MECHANISMS[mechanism]["source_template"])
    return {"path": str(path.resolve()), "sha256": sha256_file(path) if path.is_file() else None,
            "exists": path.is_file(), "role": "syntax/provenance only; not a DS-DATA-02 case"}


def _write_parent_inputs(output_root: Path) -> dict[str, Any]:
    parent_dir = output_root / "parent_inputs"
    parents: list[dict[str, Any]] = []
    specs = _parent_specs()
    for mechanism, spec in specs.items():
        directory = parent_dir / mechanism
        definition = _write_definition(directory / f"{spec['case_id']}_Def.xml", spec)
        control = _write_control(directory / f"{spec['case_id']}_Control.csv", spec)
        native = _write_native(directory / f"{spec['case_id']}_Native.json", spec)
        normal = _write_normal(directory / f"{spec['case_id']}_Normal.json", spec)
        template = _official_template_record(spec)
        parents.append({
            "case_id": spec["case_id"], "mechanism_id": mechanism,
            "definition": definition, "control": control, "native": native, "normal": normal,
            "official_template": template, "dp_m": spec["dp_m"], "water_level_m": spec["water_level_m"],
            "tank": spec["tank"], "body": spec["body"], "fluid_fill": spec["fluid_fill"],
            "coordinate_frame_id": MECHANISMS[mechanism]["coordinate_frame_id"],
            "solver_dimension_required": 3, "no_chrono": True,
        })
    manifest = {
        "schema": "ds-data-02.f6.parent_input_manifest.v1", "family_id": "F6", "generator_version": GENERATOR_VERSION,
        "status": "definitions_frozen_parent_gencase_pending", "parents": parents,
        "hash_policy": "definition, control, native, normal, official syntax template, binary, and all generated native/normal outputs are bound in requests",
        "repair_policy": {"max_root_cause_repairs_per_parent": 2, "fallback": "official simple 3D floating box syntax; no Chrono/contact debugging"},
    }
    write_json(parent_dir / "parent_input_manifest.json", manifest)
    return manifest


def history_reuse_inventory() -> dict[str, Any]:
    old_dir = HISTORICAL_ROOT / "campaigns/ds-data-01/d05/B05_F6_floating_box_dp030"
    prepare = old_dir / "prepare-receipt.json"
    run = old_dir / "run-receipt.json"
    conversion = old_dir / "conversion-receipt.json"
    records: list[dict[str, Any]] = []
    for path in (prepare, run, conversion):
        row: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "sha256": sha256_file(path) if path.is_file() else None}
        if path.is_file():
            try:
                source = read_json(path)
                row["status"] = source.get("status")
                row["identity_count"] = source.get("identity_count", source.get("fluid_particles"))
                row["time_end_s"] = source.get("time_end", source.get("tmax"))
                row["scientific_acceptance"] = source.get("scientific_acceptance")
                row["split"] = source.get("split")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
        records.append(row)
    return {
        "schema": "ds-data-02.f6.history_reuse_inventory.v1", "family_id": "F6",
        "historical_sources": records,
        "reused_count": 0,
        "strict_equivalence": False,
        "exclusion_reason": [
            "old DS-DATA-01 candidate is a 13,577,000-identity normalized trajectory, not a DS-DATA-02 native source package",
            "time window ends at about 0.8 s and cannot cover a complete free-response decay or regular-wave event window",
            "old split is unassigned and the old campaign identity is not the F6 DS-DATA-02 lineage",
            "the old identity is retained as a cost/performance reference only; it is never rerun as the entry route and never counted as reusable",
        ],
        "official_templates": [
            _source_relative(OFFICIAL_ROOT / "examples/main/11_Floating/CaseFloating_Def.xml"),
            _source_relative(OFFICIAL_ROOT / "examples/main/12_FloatingWaves/CaseFloatingWavesVal2_Def.xml"),
        ],
        "performance_anchor": {
            "source": str(run), "solver_elapsed_seconds": 1632.445, "fluid_particles": 12957384,
            "total_particles": 15027060, "time_window_s": 0.800037, "native_bytes": 4327880749,
            "use": "conservative cost scaling only; not scientific evidence or case reuse",
        },
    }


def _event_definitions() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f6.event_definitions.v1", "family_id": "F6",
        "full_event_window_s": list(PARENT_WINDOW_S),
        "complete_window_rule": "include still-water startup, release or wave ramp, at least six distinguishable response/wave periods where the mechanism permits, and a final decay/mass audit; no 0.8 s short clip is sufficient",
        "mechanisms": [
            {
                **MECHANISMS["simple_free_response"],
                "frame": {"position": "tank-attached inertial coordinates", "control": "no translating tank; gravity is explicit", "world_transform": "identity"},
                "events": {"release": "t=0 after initial still-water particle state", "peak": "successive extrema of body heave and roll/pitch", "decay": "envelope over final three local periods", "fluid": "source region to body-side/re-entry categories from native particle state"},
            },
            {
                **MECHANISMS["wave_no_contact"],
                "frame": {"position": "world/tank geometry with tank-attached event coordinates", "control": "piston displacement prescribed in world time; inverse tank frame only for event planes", "world_transform": "p_world=R_tank p_tank+c_tank; R_tank=I for translating piston background"},
                "events": {"arrival": "first crest at x=3.4 measuring plane", "steady_cycles": "cycles after three-period ramp", "decay": "last two cycles after forcing tail", "fluid": "source side to wave/body-side/re-entry categories with censored open-top events"},
            },
        ],
        "fluid_event_labels": ["source_label", "destination_time_series", "first_passage_interval", "residence_time", "final_category", "failure_reason", "unknown_mass"],
        "rigid_state_labels": ["pose", "orientation_quaternion_or_matrix", "linear_velocity", "angular_velocity", "mass", "inertia_tensor", "force", "torque", "contact_event_flag"],
        "contact_semantics": "contact_event_flag is expected to remain false for the no-contact parent; RigidAlgorithm=1 is a native SPH rigid-body path and Chrono is absent",
    }


def _observation_plan() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f6.observation_plan.v1", "family_id": "F6",
        "physical_scales": {"length_L_m": 0.8, "velocity_U_m_s": "sqrt(g*L) for dimensionless reporting", "time_T_s": "sqrt(L/g)", "fluid_density_kg_m3": 1000.0},
        "primary_observables": ["equilibrium_draft", "heave_and_orientation", "natural_period", "wave_response_amplitude", "decay_ratio", "fluid_mass_and_momentum", "rigid_force_and_torque"],
        "secondary_observables": ["particle_type3_fluid_mass", "particle_type2_floating_mass", "fluid_source_destination", "first_passage", "residence_time", "wall_clearance", "contact_event_flag"],
        "spatial_matrix": {mechanism: RESOLUTION_LADDERS[mechanism] for mechanism in MECHANISMS},
        "independent_integrator_study": {"background": "simple_free_response", "dp_m": 0.060, "variants": [{"DtFixed": 0.0, "label": "native_adaptive"}, {"DtFixed": 0.5e-3, "label": "fixed_half_millisecond"}], "same_geometry_control_window": True, "status": "planned_pending_solver"},
        "independent_save_study": {"background": "simple_free_response", "integration": "same native adaptive integrator", "variants_s": [0.025, 0.05, 0.10], "status": "planned_pending_solver", "downsampling_is_not_integrator_evidence": True},
        "sampling": {"native_full_state": {"position_velocity_density_pressure": PARENT_OUTPUT_DT_S, "floating_info": 0.01, "forces": 0.01}, "event_detection": "linear interpolation between native frames; preserve censored and unknown categories"},
        "error_budget": {"primary_macro_observable_relative": 0.05, "event_time_relative_to_characteristic_period": 0.02, "spatial_discretization_share": 0.60, "integrator_share": 0.20, "save_sampling_share": 0.20, "freeze_before_solver": True},
        "q_status": {"Q_I": "pending actual solver/native state", "Q_N": "pending 2x3 and integrator/save comparisons", "Q_E": "optional Test14 or analytical displacement anchor; not a gate for Q-N"},
    }


def _label_schema() -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f6.label_schema.v1", "family_id": "F6", "model_runtime_loaded": False,
        "particle_rows": {"time_s": "finite increasing", "particle_id": "stable native ID", "particle_zone": "fixed/moving/floating/fluid", "type": {"2": "floating", "3": "fluid"}, "valid": "boolean", "position": "m", "velocity": "m/s", "mass": "kg", "density": "kg/m3", "pressure": "Pa"},
        "rigid_rows": {"time_s": "finite increasing", "body_id": "floating mk=60 after GenCase", "pose": "x,y,z", "orientation": "quaternion or rotation matrix", "linear_velocity": "m/s", "angular_velocity": "rad/s", "mass": "kg", "inertia": "kg*m2", "force": "N", "torque": "N*m", "contact_event_flag": "boolean"},
        "transport_rows": {"source_label": "initial region", "destination_time_series": "per-frame category", "first_passage_interval": "[t_first,t_last] or censored", "residence_time": "seconds or censored", "final_category": "end-state category", "failure_reason": "mutually exclusive reason", "unknown_mass": "kg"},
        "unknown_policy": "unknown is a recorded mass bucket and never silently assigned to no-event or final category",
    }


def _split_registry() -> list[dict[str, Any]]:
    roles = (["train"] * 24) + (["validation"] * 6) + (["id_test"] * 6) + (["parameter_ood_test"] * 6) + (["geometry_control_ood_test"] * 6)
    rows: list[dict[str, Any]] = []
    for index, role in enumerate(roles):
        mechanism = "simple_free_response" if index % 2 == 0 else "wave_no_contact"
        axis = {
            "body_density_ratio": [0.42, 0.50, 0.58, 0.66][index % 4],
            "initial_heave_offset_m": [0.04, 0.08, 0.12, 0.16][index % 4],
            "wave_height_m": 0.08 if mechanism == "wave_no_contact" else 0.0,
            "wave_period_s": 1.25 if mechanism == "wave_no_contact" else None,
            "initial_pitch_deg": [0.0, 2.0, -2.0, 4.0][index % 4],
        }
        if role == "parameter_ood_test":
            axis["body_density_ratio"] = [0.36, 0.72, 0.78][index % 3]
            axis["initial_heave_offset_m"] = [0.18, 0.22, 0.26][index % 3]
            if mechanism == "wave_no_contact":
                axis["wave_height_m"] = [0.10, 0.12, 0.14][index % 3]
        geometry_family = "box_tank_standard"
        control_family = MECHANISMS[mechanism]["control_family_id"]
        if role == "geometry_control_ood_test":
            geometry_family = ["box_tank_wide", "rounded_proxy_box", "box_tank_shallow"][index % 3]
            control_family = ["F6_CTRL_LONG_RAMP", "F6_CTRL_LOW_WAVE", "F6_CTRL_PHASE_SHIFT"][index % 3]
        # These small, deterministic phase/lateral offsets make every row a
        # genuinely distinct physical initial condition.  They are part of
        # the physical identity rather than an accidental filename suffix.
        axis["initial_lateral_offset_m"] = round((index - 23.5) * 0.002, 5)
        axis["phase_or_yaw_rad"] = round(((index % 8) - 3.5) * 0.04, 5)
        physical_spec = {"mechanism_id": mechanism, "geometry_family_id": geometry_family, "control_family_id": control_family, "axis": axis, "spatial_resolution_for_identity": "medium"}
        physical_id = f"F6_PHYS_{canonical_hash(physical_spec)[:16]}"
        lineage = f"F6_LG_{canonical_hash({**physical_spec, 'numerics': 'all resolutions and views same lineage'})[:16]}"
        paired = f"F6_PAIR_{index // 2:02d}"
        row = {
            "case_id": f"F6_{index:03d}_{mechanism}", "physical_case_id": physical_id, "lineage_group_id": lineage,
            "paired_background_id": paired, "family_id": "F6", "mechanism_id": mechanism,
            "geometry_family_id": geometry_family, "control_family_id": control_family, "recipe_id": f"F6_{mechanism}_medium_v1",
            "view_id": "full_native_state", "attempt_id": None, "status": "planned_no_solver", "split": role, "target_role": role,
            "parent_case_id": PARENT_SIMPLE_ID if mechanism == "simple_free_response" else PARENT_WAVE_ID,
            "source_provenance_id": MECHANISMS[mechanism]["source_template"], "parameters": axis,
            "nested_subsets": [name for name, limit in (("pilot_8", 8), ("pilot_24", 24), ("final_48", 48)) if index < limit],
            "solver_dimension": "pending_actual_solver_output", "scientific_status": "QI_QN_pending",
        }
        rows.append(row)
    return rows


def _family_card(history: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f6.family_card.v1", "family_id": "F6", "name": "自由浮体与水入体交互",
        "generator": {"path": str(Path(__file__).resolve()), "version": GENERATOR_VERSION},
        "status": "definitions_frozen_parent_gencase_pending", "target_independent_cases": 48, "pilot_sizes": [8, 24, 48],
        "mechanisms": MECHANISMS, "resolution_ladders": RESOLUTION_LADDERS,
        "historical_reuse": {"reused_count": history.get("reused_count", 0), "strict_equivalence_required": True, "old_f6_1357m_identity_is_not_entry": True},
        "quality_layers": {"Q_I": "actual generated 3D/native structure and rigid/fluid ledgers", "Q_N": "recipe+domain+window+observable numeric reference", "Q_E": "optional external/analytical anchor"},
        "solver_policy": "F6 owner never starts solver/GPU; only shared runtime may submit qualification requests",
        "model_runtime_loaded": False, "training_launch_allowed": False,
    }


def _qualified_recipes() -> dict[str, Any]:
    recipes = []
    for mechanism, spec in _parent_specs().items():
        recipes.append({
            "recipe_id": f"F6_{mechanism}_parent_v1", "family_id": "F6", "mechanism_id": mechanism,
            "parent_case_id": spec["case_id"], "status": "parent_gencase_pending_solver_pending", "solver_dimension_required": 3,
            "complete_event_window_s": list(PARENT_WINDOW_S), "resolution_study": RESOLUTION_LADDERS[mechanism],
            "integrator_and_save_studies": ["independent Dt study", "independent save cadence study"],
            "observables": _observation_plan()["primary_observables"], "Q_I": "pending", "Q_N": "pending", "Q_E": "optional_pending",
            "qualification_does_not_authorize_production": True,
        })
    return {"schema": "ds-data-02.f6.qualified_recipes.v1", "family_id": "F6", "recipes": recipes, "production_status": "strictly_pending_QI_QN_and_parent_process"}


def _reference_evidence(history: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f6.reference_evidence.v1", "family_id": "F6", "status": "definition_and_official_template_only",
        "official_sources": [
            {"path": str((OFFICIAL_ROOT / "examples/main/11_Floating/CaseFloating_Def.xml").resolve()), "role": "successful native 3D floating-box syntax"},
            {"path": str((OFFICIAL_ROOT / "examples/main/12_FloatingWaves/CaseFloatingWavesVal2_Def.xml").resolve()), "role": "successful native 3D piston-wave/floating syntax"},
        ],
        "historical_inventory": {"path": str((FAMILY_ROOT / "history_reuse_inventory.json").resolve()), "sha256": sha256_file(FAMILY_ROOT / "history_reuse_inventory.json") if (FAMILY_ROOT / "history_reuse_inventory.json").is_file() else None, "reused_count": history.get("reused_count", 0)},
        "evidence_layers": {"definition": "available", "GenCase": "pending shared runtime", "solver": "pending shared GPU runtime", "Q_I": "pending actual native output", "Q_N": "pending numerical comparisons", "Q_E": "optional"},
        "solver_launched_by_f6": False,
    }


def _split_plan(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "ds-data-02.f6.split_plan.v1", "family_id": "F6", "status": "candidate_development_test_split_pending_quality_gates",
        "counts": {"train": 24, "validation": 6, "id_test": 6, "parameter_ood_test": 6, "geometry_control_ood_test": 6, "total": 48},
        "nested_subsets": {"pilot_8": [row["case_id"] for row in rows[:8]], "pilot_24": [row["case_id"] for row in rows[:24]], "final_48": [row["case_id"] for row in rows]},
        "leakage_rules": ["physical_case_id is unique", "resolution/restart/window/view share parent split", "geometry OOD uses geometry_family_id", "control OOD uses control_family_id", "hidden test generation is not claimed"],
        "axis_design": {"mechanism": "two backgrounds", "density_and_draft": "body density ratio and initial heave/pitch", "wave": "height and period for wave mechanism", "geometry_holdout": "wide/shallow/rounded-proxy finite tank variants", "control_holdout": "ramp/phase/wave-control templates"},
        "rows": len(rows),
    }


def _gencase_request(parent: Mapping[str, Any], attempt_id: str) -> dict[str, Any]:
    definition = Path(parent["definition"]["path"]).resolve()
    input_files = [
        GENCASE_BINARY.resolve(), definition, Path(parent["control"]["path"]).resolve(),
        Path(parent["native"]["path"]).resolve(), Path(parent["normal"]["path"]).resolve(), Path(parent["official_template"]["path"]).resolve(),
    ]
    return {
        "schema": "ds-data-02.runner.request.v1", "family_id": "F6", "case_id": parent["case_id"], "attempt_id": attempt_id,
        "kind": "cpu", "cpu_task_kind": "gencase", "command": [str(GENCASE_BINARY.resolve()), str(definition.with_suffix("")), f"{{attempt_root}}/{parent['case_id']}", "-save:all"],
        "cwd": str(definition.parent), "max_wall_seconds": 300, "cpu_threads": 4, "estimated_storage_bytes": 256 * 1024 * 1024,
        "input_files": [str(path) for path in input_files], "worktree_root": str(REPO_ROOT.resolve()),
        "purpose": "bounded F6 parent GenCase only; no solver/GPU; verify positive fluid, actual3D, type2/type3 ledgers, transverse layers, finite walls, mass/inertia and controls",
        "expected": {"solver_dimension": 3, "minimum_transverse_layers": MIN_TRANSVERSE_LAYERS, "control_window_s": list(PARENT_WINDOW_S), "fluid_type": 3, "floating_type": 2, "no_chrono": True},
    }


def _execution_queue(output_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    for parent in manifest.get("parents", []):
        attempt_id, _ = _next_parent_attempt(str(parent["case_id"]))
        request = _gencase_request(parent, attempt_id)
        request["request_file"] = f"execution_requests/{parent['mechanism_id']}_gencase.json"
        write_json(output_root / request["request_file"], request)
        requests.append(request)
    return {
        "schema": "ds-data-02.f6.execution_queue.v1", "family_id": "F6", "cpu_parent_status": "ready_for_shared_runtime", "qualification_status": "pending_parent_gencase_audit", "production_status": "strictly_pending",
        "cpu_requests": requests, "qualification_requests": [], "qualification_request_files": [],
        "runtime": str(RUNTIME_SOURCE), "raw_output_root": str(RAW_OUTPUT_ROOT), "next_task": "submit both execution_requests through shared runtime, then run audit-parents; submit generated qualification requests only after parent structural pass",
    }


def _control_coverage(path: Path) -> dict[str, Any]:
    times: list[float] = []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.reader(handle):
                if not row or row[0].strip().startswith("#") or row[0].strip() == "time_s":
                    continue
                times.append(float(row[0].strip()))
    except (OSError, ValueError, UnicodeError) as exc:
        return {"path": str(path), "exists": path.is_file(), "error": f"{type(exc).__name__}: {exc}", "coverage_pass": False}
    monotonic = bool(times) and all(b > a for a, b in zip(times, times[1:]))
    finite = bool(times) and all(math.isfinite(value) for value in times)
    return {"path": str(path.resolve()), "exists": path.is_file(), "rows": len(times), "time_start_s": times[0] if times else None, "time_end_s": times[-1] if times else None, "monotonic": monotonic, "finite": finite, "sha256": sha256_file(path) if path.is_file() else None, "coverage_pass": bool(path.is_file() and len(times) == PARENT_CONTROL_ROWS and monotonic and finite and abs(times[0] - PARENT_WINDOW_S[0]) < 1e-9 and abs(times[-1] - PARENT_WINDOW_S[1]) < 1e-9)}


def _wall_check(definition_root: ET.Element, boundary_count: int) -> dict[str, Any]:
    mainlist = definition_root.find("./casedef/geometry/commands/mainlist")
    boxfills = [] if mainlist is None else [" ".join((node.findtext("boxfill") or "").split()) for node in mainlist.findall("drawbox")]
    required = {"bottom", "left", "right", "front", "back"}
    finite_outer = any(set(item.split("|")) == required for item in boxfills)
    return {"boundary_particles": boundary_count, "boundary_particles_positive": boundary_count > 0, "finite_outer_wall_faces": finite_outer, "open_top": True, "boxfill_operations": boxfills, "pass": bool(boundary_count > 0 and finite_outer)}


def _audit_parent(parent: Mapping[str, Any], receipt_path: Path) -> dict[str, Any]:
    compact = _compact_receipt(receipt_path)
    result: dict[str, Any] = {"case_id": parent["case_id"], "mechanism_id": parent["mechanism_id"], "receipt": compact, "receipt_sha256": sha256_file(receipt_path) if receipt_path.is_file() else None, "checks": {}, "errors": []}
    if compact.get("status") != "completed":
        result["status"] = "pending" if compact.get("status") == "pending" else "fail"
        result["errors"].append("shared runtime GenCase receipt is not completed")
        return result
    receipt = read_json(receipt_path)
    prefix = _generated_prefix(receipt)
    if prefix is None:
        result["status"] = "fail"; result["errors"].append("receipt has no generated prefix"); return result
    generated_xml = prefix.with_suffix(".xml")
    generated_vtk = prefix.with_name(prefix.name + "_All.vtk")
    generated_normal = prefix.with_name(prefix.name + "__Actual.vtk")
    try:
        root = ET.parse(generated_xml).getroot()
        constants = root.find("./execution/constants")
        particles = root.find("./execution/particles")
        if constants is None or particles is None:
            raise ValueError("generated XML has no execution/constants or particles")
        data2d = (constants.find("data2d").get("value", "true") if constants.find("data2d") is not None else "true").lower()
        fluid = particles.find("fluid")
        floating = particles.find("floating")
        if fluid is None or floating is None:
            raise ValueError("generated XML lacks fluid or floating block")
        fluid_begin, fluid_count = int(fluid.get("begin", "0")), int(fluid.get("count", "0"))
        float_begin, float_count = int(floating.get("begin", "0")), int(floating.get("count", "0"))
        boundary_count = sum(int(node.get("count", "0")) for node in particles if node.tag in {"fixed", "moving"})
        points = _vtk_points(generated_vtk)
        fluid_points = points[fluid_begin:fluid_begin + fluid_count]
        floating_points = points[float_begin:float_begin + float_count]
        y_layers = sorted({round(point[1], 8) for point in fluid_points})
        dp = float(constants.find("dp").get("value"))
        massfluid = float(constants.find("massfluid").get("value"))
        density = float(constants.find("rhop0").get("value"))
        massbody_node = floating.find("massbody")
        massbody = float(massbody_node.get("value")) if massbody_node is not None else 0.0
        center_node = floating.find("center")
        center = [float(center_node.get(axis)) for axis in ("x", "y", "z")] if center_node is not None else None
        inertia_node = floating.find("inertia")
        inertia = []
        if inertia_node is not None:
            for row_id in (1, 2, 3):
                values = inertia_node.find(f"values[@v{row_id}1]")
                if values is not None:
                    inertia.append([float(values.get(f"v{row_id}{col}")) for col in (1, 2, 3)])
        body_volume = math.prod(float(value) for value in parent["body"]["size_m"])
        body_bounds = [[min(point[axis] for point in floating_points), max(point[axis] for point in floating_points)] for axis in range(3)] if floating_points else None
        body_bottom = body_bounds[2][0] if body_bounds else None
        body_top = body_bounds[2][1] if body_bounds else None
        water_level = float(parent["water_level_m"])
        draft = max(0.0, min(water_level, body_top) - body_bottom) if body_bottom is not None and body_top is not None else 0.0
        text = generated_xml.read_text(encoding="utf-8", errors="replace").lower()
        definition_text = Path(parent["definition"]["path"]).read_text(encoding="utf-8", errors="replace").lower()
        rigid_algorithm = next((node.get("value") for node in root.findall("./execution/parameters/parameter") if node.get("key") == "RigidAlgorithm"), None)
        input_after = receipt.get("input_hashes_after_run") if isinstance(receipt.get("input_hashes_after_run"), Mapping) else {}
        declared_paths = [parent["definition"]["path"], parent["control"]["path"], parent["native"]["path"], parent["normal"]["path"], parent["official_template"]["path"], str(GENCASE_BINARY.resolve())]
        hash_binding = all(input_after.get(str(Path(path).resolve())) == sha256_file(Path(path)) for path in declared_paths)
        wall = _wall_check(ET.parse(Path(parent["definition"]["path"])).getroot(), boundary_count)
        control = _control_coverage(Path(parent["control"]["path"]))
        fluid_mass = massfluid * fluid_count
        expected_particle_mass = density * dp ** 3
        checks = {
            "positive_fluid_type3": fluid_count > 0 and int(compact.get("fluid_particles") or 0) == fluid_count,
            "positive_floating_type2": float_count > 0,
            "actual_3d": compact.get("solver_dimension_from_gencase") == 3 and data2d in {"false", "0", "no"},
            "finite_fluid_positions": bool(fluid_points) and all(math.isfinite(value) for point in fluid_points for value in point),
            "effective_transverse_layers": len(y_layers) >= MIN_TRANSVERSE_LAYERS,
            "control_coverage": bool(control.get("coverage_pass")),
            "finite_walls": wall["pass"],
            "initial_fluid_mass_positive": fluid_mass > 0,
            "fluid_particle_mass_consistent": expected_particle_mass > 0 and abs(massfluid - expected_particle_mass) / expected_particle_mass < 1e-9,
            "rigid_mass_positive": massbody > 0,
            "rigid_inertia_positive_defined": len(inertia) == 3 and all(inertia[i][i] > 0 for i in range(3)) and all(math.isfinite(v) for row in inertia for v in row),
            "draft_finite_and_bounded": math.isfinite(draft) and draft >= 0 and body_bounds is not None,
            "no_chrono_or_contact_solver": "chrono" not in definition_text and "chrono" not in text and rigid_algorithm == "1",
            "input_hash_binding": hash_binding,
            "native_normal_outputs_present": generated_xml.is_file() and prefix.with_suffix(".bi4").is_file() and generated_vtk.is_file() and generated_normal.is_file(),
        }
        result["generated"] = {"xml_path": str(generated_xml), "xml_sha256": sha256_file(generated_xml), "bi4_path": str(prefix.with_suffix(".bi4")), "vtk_path": str(generated_vtk), "normal_geometry_path": str(generated_normal), "total_particles": int(compact.get("total_particles") or 0), "fluid_particles_receipt": int(compact.get("fluid_particles") or 0), "fluid_particles_xml": fluid_count, "floating_particles_xml": float_count, "fluid_type_code": 3, "floating_type_code": 2, "solver_dimension_from_gencase": compact.get("solver_dimension_from_gencase"), "data2d": data2d, "dp_m": dp, "fluid_mass_per_particle_kg": massfluid, "initial_fluid_mass_kg": fluid_mass, "floating_mass_kg": massbody, "floating_center_m": center, "floating_inertia_kg_m2": inertia, "body_volume_m3": body_volume, "floating_density_ratio": massbody / (body_volume * density) if body_volume > 0 and density > 0 else None, "body_bounds_m": body_bounds, "initial_draft_m": draft, "transverse_layer_count": len(y_layers), "transverse_layer_coordinates_m": y_layers, "fluid_position_bounds_m": [[min(p[a] for p in fluid_points), max(p[a] for p in fluid_points)] for a in range(3)] if fluid_points else None, "type_mass_ledger": {"type_3_fluid": {"count": fluid_count, "mass_kg": fluid_mass}, "type_2_floating": {"count": float_count, "mass_kg": massbody, "inertia_kg_m2": inertia}}, "rigid_state_definition": {"pose": True, "orientation": True, "linear_velocity": True, "angular_velocity": True, "mass": True, "inertia": bool(inertia), "force": "FloatingInfo/ComputeForces postprocessor required", "torque": "FloatingInfo/ComputeForces postprocessor required", "contact_event_flag": True}}
        result["checks"] = checks
        result["control"] = control
        result["wall"] = wall
        result["mass"] = {"fluid_density_kg_m3": density, "fluid_mass_kg": fluid_mass, "floating_mass_kg": massbody, "floating_density_ratio": massbody / (body_volume * density) if body_volume > 0 else None, "inertia_kg_m2": inertia}
        result["status"] = "pass" if all(checks.values()) else "fail"
        result["errors"].extend(name for name, passed in checks.items() if not passed)
    except (OSError, ValueError, TypeError, ET.ParseError, struct.error, IndexError) as exc:
        result["status"] = "fail"; result["errors"].append(f"generated output audit error: {type(exc).__name__}: {exc}")
    return result


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _qualification_request(output_root: Path, parent: Mapping[str, Any], audit: Mapping[str, Any], history: Mapping[str, Any]) -> dict[str, Any]:
    receipt_path = Path(audit["receipt"]["receipt_path"]).resolve()
    receipt = read_json(receipt_path)
    prefix = _generated_prefix(receipt)
    if prefix is None:
        raise ValueError(f"missing generated prefix: {receipt_path}")
    actual_total = int(receipt.get("total_particles") or 0)
    actual_fluid = int(receipt.get("fluid_particles") or 0)
    anchor = history["performance_anchor"]
    ratio = actual_total / float(anchor["total_particles"])
    window_ratio = PARENT_WINDOW_S[1] / float(anchor["time_window_s"])
    complexity = float(_parent_specs()[str(parent["mechanism_id"])] ["complexity_factor"])
    estimated_gpu_seconds = max(60, math.ceil(float(anchor["solver_elapsed_seconds"]) * ratio * window_ratio * complexity))
    frames = int(round((PARENT_WINDOW_S[1] - PARENT_WINDOW_S[0]) / PARENT_OUTPUT_DT_S)) + 1
    estimated_native = max(512 * 1024 * 1024, actual_total * frames * 80)
    estimated_storage = max(2 * 1024 ** 3, math.ceil(estimated_native * 2.0))
    generated_files = [prefix.with_suffix(".xml"), prefix.with_suffix(".bi4"), prefix.with_name(prefix.name + "_All.vtk"), prefix.with_name(prefix.name + "__Actual.vtk"), prefix.with_name(prefix.name + "_Fluid.vtk")]
    input_files = [
        Path(__file__).resolve(), RUNTIME_SOURCE.resolve(), output_root / "event_definitions.json", output_root / "observation_plan.json", output_root / "split_plan.json", output_root / "parent_inputs/parent_input_manifest.json", output_root / "parent_inputs/gencase_audit.json",
        Path(parent["definition"]["path"]).resolve(), Path(parent["control"]["path"]).resolve(), Path(parent["native"]["path"]).resolve(), Path(parent["normal"]["path"]).resolve(), Path(parent["official_template"]["path"]).resolve(), GENCASE_BINARY.resolve(), receipt_path, *generated_files,
    ]
    return {
        "schema": "ds-data-02.runner.request.v1", "family_id": "F6", "case_id": parent["case_id"], "attempt_id": f"{parent['case_id']}_SOLVER_QUAL_01", "kind": "qualification",
        "command": [str(SOLVER_BINARY.resolve()), str(prefix), "{attempt_root}/solver_output", f"-tmax:{_fmt(PARENT_WINDOW_S[1])}", f"-tout:{_fmt(PARENT_OUTPUT_DT_S)}"], "cwd": str(SOLVER_BINARY.parent.resolve()), "max_wall_seconds": max(600, math.ceil(estimated_gpu_seconds * 2.0)), "cpu_threads": 4, "estimated_storage_bytes": estimated_storage, "estimated_peak_gpu_mib": 8192,
        "complete_event_window_s": list(PARENT_WINDOW_S), "output_interval_s": PARENT_OUTPUT_DT_S, "solver_dimension_required": 3, "mechanism_id": parent["mechanism_id"], "coordinate_frame_id": parent["coordinate_frame_id"], "resolution": "medium_parent",
        "gencase_receipt": str(receipt_path), "gencase_receipt_sha256": sha256_file(receipt_path), "gencase_runner_sha256": receipt.get("runner_sha256"), "parent_gencase_git_at_launch": receipt.get("git_at_launch"), "gencase_actual_particles": {"total": actual_total, "fluid": actual_fluid, "floating": int(audit["generated"]["floating_particles_xml"])},
        "input_files": [str(path.resolve()) for path in input_files], "worktree_root": str(REPO_ROOT.resolve()), "launch_commit": _git_head(), "definition_commit_binding": _git_head(),
        "recipe_id": f"F6_{parent['mechanism_id']}_medium_parent_v1", "observables": _observation_plan()["primary_observables"], "required_rigid_state": ["pose", "orientation", "linear_velocity", "angular_velocity", "mass", "inertia", "force", "torque", "contact_event_flag"],
        "postprocessing_plan": {"floating_info": [str(FLOATING_INFO_BINARY.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:60", "-savedata", "{attempt_root}/solver_output/floatinginfo/FloatingMotion"], "compute_forces": [str(COMPUTE_FORCES_BINARY.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:60", "-savecsv", "{attempt_root}/solver_output/forces/FloatingForce"], "postprocessors_are_pending_shared_cpu_execution": True},
        "cost_estimate": {"basis": "measured old DS-DATA-01 run used only as conservative performance anchor, scaled by actual GenCase particle count and requested window", "anchor_total_particles": anchor["total_particles"], "anchor_fluid_particles": anchor["fluid_particles"], "anchor_time_window_s": anchor["time_window_s"], "anchor_solver_elapsed_seconds": anchor["solver_elapsed_seconds"], "actual_total_particles": actual_total, "actual_fluid_particles": actual_fluid, "particle_ratio": ratio, "window_ratio": window_ratio, "mechanism_complexity_factor": complexity, "estimated_gpu_seconds": estimated_gpu_seconds, "estimated_native_bytes": estimated_native, "estimated_storage_bytes": estimated_storage},
        "raw_output_root": str(RAW_OUTPUT_ROOT), "event_timing_qualified": False, "qualification_scope": "parent complete-window Q-I/Q-N evidence candidate only; no production authorization and no claim that old F6 output is reused", "solver_launch_forbidden_for_f6_owner": True, "qualification_launch_authority": "shared_ds_data_02_runtime_only; root dispatches GPU", "request_note": "Submit this exact JSON through the shared runtime after verifying parent_gencase_audit. Runtime binds leased UUID, actual command, input hashes and git_at_launch. All definition/control/native/normal/generated native/normal files are hash-bound.",
    }


def _materialize_qualification_requests(output_root: Path, audit: Mapping[str, Any]) -> dict[str, Any]:
    manifest = read_json(output_root / "parent_inputs/parent_input_manifest.json")
    history = read_json(output_root / "history_reuse_inventory.json")
    requests: list[dict[str, Any]] = []; files: list[str] = []
    by_case = {str(row["case_id"]): row for row in manifest.get("parents", [])}
    for row in audit.get("parents", []):
        if not isinstance(row, Mapping) or row.get("status") != "pass":
            continue
        parent = by_case.get(str(row["case_id"]))
        if parent is None:
            continue
        request = _qualification_request(output_root, parent, row, history)
        relative = f"qualification_requests/{parent['mechanism_id']}.json"
        request["request_file"] = relative
        write_json(output_root / relative, request)
        requests.append(request); files.append(relative)
    queue_path = output_root / "execution_queue.json"
    queue = read_json(queue_path)
    queue["qualification_status"] = "ready_for_shared_gpu_dispatch" if requests else "pending_parent_gencase_audit"
    queue["qualification_requests"] = requests; queue["qualification_request_files"] = files
    queue["parent_gencase_audit"] = {"path": str((output_root / "parent_inputs/gencase_audit.json").resolve()), "sha256": sha256_file(output_root / "parent_inputs/gencase_audit.json"), "status": audit.get("status")}
    write_json(queue_path, queue)
    return {"status": queue["qualification_status"], "request_files": files, "requests": requests}


def _update_after_audit(output_root: Path, audit: Mapping[str, Any], qualification: Mapping[str, Any]) -> None:
    evidence_path = output_root / "reference_evidence.json"
    evidence = read_json(evidence_path); evidence["parent_gencase_audit"] = {"path": str((output_root / "parent_inputs/gencase_audit.json").resolve()), "sha256": sha256_file(output_root / "parent_inputs/gencase_audit.json"), "status": audit.get("status")}; evidence["qualification_requests"] = qualification.get("request_files", []); evidence["status"] = "parent_gencase_structural_pass_solver_QI_QN_pending" if audit.get("status") == "pass" else "parent_gencase_audit_pending_or_failed"; write_json(evidence_path, evidence)
    card_path = output_root / "family_card.json"; card = read_json(card_path); card["status"] = "parent_gencase_passed_solver_QI_QN_pending" if audit.get("status") == "pass" else "parent_gencase_pending_or_failed"; card["parent_gencase_audit"] = evidence["parent_gencase_audit"]; card["qualification_requests"] = qualification.get("request_files", []); write_json(card_path, card)
    recipe_path = output_root / "qualified_recipes.json"; recipes = read_json(recipe_path); rows_by_mechanism = {str(row.get("mechanism_id")): row for row in audit.get("parents", []) if isinstance(row, Mapping)}
    req_by_mechanism = {str(row.get("mechanism_id")): row for row in qualification.get("requests", []) if isinstance(row, Mapping)}
    for recipe in recipes.get("recipes", []):
        row = rows_by_mechanism.get(str(recipe.get("mechanism_id")))
        if row is None: continue
        recipe["status"] = "parent_gencase_passed_solver_pending" if row.get("status") == "pass" else "parent_gencase_audit_failed"; recipe["parent_gencase_audit"] = {"selected_attempt": row.get("selected_attempt"), "receipt_path": row.get("receipt", {}).get("receipt_path"), "checks": row.get("checks", {})}
        if str(recipe.get("mechanism_id")) in req_by_mechanism: recipe["qualification_request"] = req_by_mechanism[str(recipe["mechanism_id"])].get("request_file")
    write_json(recipe_path, recipes)
    handoff = output_root / "FAMILY_HANDOFF.md"
    text = handoff.read_text(encoding="utf-8") if handoff.is_file() else "# F6 DS-DATA-02 handoff\n"
    marker = "## Actual parent evidence"
    if marker not in text:
        text = text.rstrip() + "\n\n" + marker + "\n\n"
    lines = [f"- Parent audit status: **{audit.get('status')}**; F6 owner launched no solver/GPU.", f"- Qualification requests: {', '.join('`'+str(x)+'`' for x in qualification.get('request_files', [])) or 'none until parent audit passes'}.", "- GenCase checks include actual 3D/data2d=false, positive type-3 fluid and type-2 floating ledgers, effective transverse layers, finite walls, control coverage, draft/density ratio, rigid mass/inertia, no Chrono/contact solver, and all input hashes.", "- Q-I/Q-N/production remain pending until root dispatches complete-window solver and postprocessors; the old 13.57M-identity candidate remains excluded from reuse."]
    handoff.write_text(text.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def audit_parents(output_root: Path = FAMILY_ROOT) -> dict[str, Any]:
    manifest = read_json(output_root / "parent_inputs/parent_input_manifest.json")
    audits: list[dict[str, Any]] = []
    for parent in manifest.get("parents", []):
        selected, attempts = _next_parent_attempt(str(parent["case_id"]))
        row = _audit_parent(parent, _runner_receipt_path(str(parent["case_id"]), selected)); row["selected_attempt"] = selected; row["attempts"] = attempts; row["repair_history"] = [{"attempt_id": x["attempt_id"], "status": x.get("status"), "fluid_particles": x.get("fluid_particles"), "diagnosis": "structural GenCase failure; inspect receipt before one bounded definition repair"} for x in attempts if x.get("status") != "completed" or int(x.get("fluid_particles") or 0) <= 0]; row["repair_count"] = len(row["repair_history"]); audits.append(row)
    result = {"schema": "ds-data-02.f6.parent_gencase_audit.v1", "family_id": "F6", "status": "pass" if audits and all(row.get("status") == "pass" for row in audits) else "pending_or_fail", "solver_launched_by_f6": False, "parents": audits, "repair_policy": {"maximum_root_cause_repairs_per_parent": 2, "fallback": "official native simple floating input; no Chrono/contact debugging"}}
    audit_path = output_root / "parent_inputs/gencase_audit.json"; write_json(audit_path, result)
    manifest["status"] = "parent_gencase_audit_passed" if result["status"] == "pass" else result["status"]; manifest["gencase_audit"] = {"path": str(audit_path.resolve()), "sha256": sha256_file(audit_path)}
    for parent in manifest.get("parents", []):
        match = next((row for row in audits if row.get("case_id") == parent.get("case_id")), None)
        if match: parent["gencase_audit"] = {"status": match.get("status"), "selected_attempt": match.get("selected_attempt"), "receipt_path": match.get("receipt", {}).get("receipt_path"), "checks": match.get("checks", {})}
    write_json(output_root / "parent_inputs/parent_input_manifest.json", manifest)
    qualification = _materialize_qualification_requests(output_root, result); _update_after_audit(output_root, result, qualification)
    result["qualification"] = {"status": qualification["status"], "request_files": qualification["request_files"]}
    return result


def generate_family(output_root: Path = FAMILY_ROOT) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    history = history_reuse_inventory(); write_json(output_root / "history_reuse_inventory.json", history)
    rows = _split_registry(); manifest = _write_parent_inputs(output_root)
    write_json(output_root / "family_card.json", _family_card(history)); write_json(output_root / "event_definitions.json", _event_definitions()); write_json(output_root / "observation_plan.json", _observation_plan()); write_json(output_root / "reference_evidence.json", _reference_evidence(history)); write_json(output_root / "qualified_recipes.json", _qualified_recipes()); write_json(output_root / "split_plan.json", _split_plan(rows)); write_json(output_root / "labels/label_schema.json", _label_schema())
    queue = _execution_queue(output_root, manifest); write_json(output_root / "execution_queue.json", queue)
    (output_root / "case_registry.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    manifests = output_root / "case_manifests"; manifests.mkdir(parents=True, exist_ok=True)
    for row in rows:
        write_json(manifests / f"{row['case_id']}.json", {"schema": "ds-data-02.f6.case_manifest.v1", "case": row, "event_definitions": "../event_definitions.json", "observation_plan": "../observation_plan.json", "label_schema": "../labels/label_schema.json", "portable_copy": {"status": "not_started", "destination_root": str(RAW_OUTPUT_ROOT), "requires_actual_native_solver_output": True}})
    (output_root / "preview").mkdir(parents=True, exist_ok=True); (output_root / "preview/README.md").write_text("# F6 preview\n\nNo real preview is claimed before shared solver output. Required preview frames are still-water, release/wave arrival, peak response, and final decay, with solver/postprocessor hashes.\n", encoding="utf-8")
    (output_root / "labels").mkdir(parents=True, exist_ok=True); (output_root / "labels/README.md").write_text("# F6 labels\n\nNative fluid type-3 and floating type-2 labels plus complete rigid-body state are pending shared solver output. Unknown and censored transport mass remain explicit.\n", encoding="utf-8")
    (output_root / "FAMILY_HANDOFF.md").write_text("# F6 DS-DATA-02 checkpoint / F6 交接\n\n本 checkpoint 冻结两个真正三维、无 Chrono/contact 的 F6 parent Definition：简单自由响应与无接触规则波激励。每个 parent 有 control/native/normal 文件，GenCase 请求由 shared runtime 执行；F6 owner 不启动 solver/GPU。\n\n## Current state\n\n- 旧 DS-DATA-01 13.57M identity 浮箱轨迹已审计但 `reused_count=0`，仅用于成本锚点。\n- 两背景三分辨率、完整 0–12 s 事件窗、独立积分/保存采样计划、观测误差预算和 48 独立 nested 8/24/48 split 已冻结。\n- 最短执行链：通过 shared runtime 提交 `execution_requests/simple_free_response_gencase.json` 和 `execution_requests/wave_no_contact_gencase.json`；完成后运行 `ds_data02_f6.py audit-parents`；仅对通过的 parent 提交 qualification request。\n- Q-I、Q-N、production 严格 pending；不能用 Definition、canary、短预览或旧 training permission 代替实际 solver/native 证据。\n", encoding="utf-8")
    return {"status": "generated", "output": str(output_root), "history_reused_count": history["reused_count"], "registry_rows": len(rows), "cpu_request_files": queue["cpu_requests"]}


def validate_family(output_root: Path = FAMILY_ROOT) -> dict[str, Any]:
    required = ["family_card.json", "history_reuse_inventory.json", "event_definitions.json", "observation_plan.json", "reference_evidence.json", "qualified_recipes.json", "split_plan.json", "case_registry.jsonl", "labels/label_schema.json", "execution_queue.json", "FAMILY_HANDOFF.md", "parent_inputs/parent_input_manifest.json"]
    missing = [item for item in required if not (output_root / item).is_file()]
    errors: list[str] = []; rows: list[dict[str, Any]] = []
    registry = output_root / "case_registry.jsonl"
    if registry.is_file():
        for line_no, line in enumerate(registry.read_text(encoding="utf-8").splitlines(), 1):
            try:
                value = json.loads(line)
                if isinstance(value, dict): rows.append(value)
                else: errors.append(f"registry line {line_no} is not object")
            except json.JSONDecodeError as exc: errors.append(f"registry line {line_no}: {exc}")
    if len(rows) != 48: errors.append(f"expected 48 registry rows, got {len(rows)}")
    if len({row.get("case_id") for row in rows}) != len(rows): errors.append("case_id is not unique")
    if len({row.get("physical_case_id") for row in rows}) != len(rows): errors.append("physical_case_id is not unique")
    if Counter(row.get("split") for row in rows) != Counter({"train": 24, "validation": 6, "id_test": 6, "parameter_ood_test": 6, "geometry_control_ood_test": 6}): errors.append("split counts differ from nested 48 contract")
    if not all({"final_48"}.issubset(set(row.get("nested_subsets", []))) for row in rows): errors.append("final_48 nesting missing")
    if not all(row.get("solver_dimension") == "pending_actual_solver_output" for row in rows): errors.append("planned rows unexpectedly claim solver dimension")
    history = read_json(output_root / "history_reuse_inventory.json") if (output_root / "history_reuse_inventory.json").is_file() else {}
    if history.get("reused_count") != 0: errors.append("old F6 identity must not be counted as reused")
    for mechanism in MECHANISMS:
        definition = output_root / "parent_inputs" / mechanism
        xmls = list(definition.glob("*_Def.xml"))
        if len(xmls) != 1: errors.append(f"missing definition for {mechanism}")
        elif "chrono" in xmls[0].read_text(encoding="utf-8").lower(): errors.append(f"Chrono text found in {mechanism} definition")
    parent_audit = output_root / "parent_inputs/gencase_audit.json"
    audit_status = "pending"
    if parent_audit.is_file():
        audit = read_json(parent_audit); audit_status = str(audit.get("status"))
        if audit_status != "pass": errors.append(f"parent audit status is {audit_status}")
    queue = read_json(output_root / "execution_queue.json") if (output_root / "execution_queue.json").is_file() else {}
    qualification_files = sorted(str(path.relative_to(output_root)) for path in (output_root / "qualification_requests").glob("*.json")) if (output_root / "qualification_requests").is_dir() else []
    for path in qualification_files:
        request = read_json(output_root / path)
        if request.get("kind") != "qualification" or any(str(arg).startswith("-cpu") for arg in request.get("command", [])[1:]): errors.append(f"invalid qualification request {path}")
        if request.get("event_timing_qualified") is True: errors.append(f"qualification request overclaims event timing {path}")
    report = {"schema": "ds-data-02.f6.validation.v1", "valid": not missing and not errors, "missing": missing, "errors": errors, "registry_rows": len(rows), "split_counts": dict(Counter(row.get("split") for row in rows)), "history_reused_count": history.get("reused_count"), "parent_audit_status": audit_status, "qualification_request_files": qualification_files, "model_runtime_loaded": False, "solver_launched": False, "production_status": "pending"}
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["generate", "audit-parents", "validate"], nargs="?", default="generate")
    parser.add_argument("--output", type=Path, default=FAMILY_ROOT)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "generate": result = generate_family(args.output)
    elif args.action == "audit-parents": result = audit_parents(args.output)
    else: result = validate_family(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.report: write_json(args.report, result)
    if args.action == "audit-parents": return 0 if result.get("status") == "pass" else 1
    if args.action == "validate": return 0 if result.get("valid") else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
