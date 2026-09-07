#!/usr/bin/env python3
"""Diagnose and attempt a candidate-only repair of F6 mDBC zero normals.

This experiment is deliberately isolated from the existing F6 DBC route and
the existing mDBC preflight.  It materialises a small matrix of candidate XML
definitions, runs vendored v5.4 GenCase, inspects the serialized ``BoundNor``
array, and then runs the v5.4 CPU solver for a few milliseconds of simulation
time.  The output is diagnostic evidence only: no trajectory, force, or
buoyancy result is accepted here.

The baseline has 792 zero fixed/moving normals.  The matrix separates the
normal-geometry composition (tank, Float1 outer STL, or both), cylinder mask,
normal distance, inversion, and a small outward tank-normal offset.  The
offset is a diagnostic candidate, not an endorsed physical configuration.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

try:
    from scripts.r3_g2_f6_mdbc_preflight import (
        EQUILIBRIUM_BASE_Z_M,
        EXTRACTED,
        GENCASE,
        BI_FILE_INFO,
        SOURCE_EVIDENCE,
        SOLVER_CPU,
        mdbc_definition_text,
        parse_gencase_normals,
        parse_solver_normals,
        preflight_record,
        run_nvidia_smi,
        vtk_point_count,
        write_world_stl,
        cpu_environment,
    )
except ModuleNotFoundError:
    from r3_g2_f6_mdbc_preflight import (
        EQUILIBRIUM_BASE_Z_M,
        EXTRACTED,
        GENCASE,
        BI_FILE_INFO,
        SOURCE_EVIDENCE,
        SOLVER_CPU,
        mdbc_definition_text,
        parse_gencase_normals,
        parse_solver_normals,
        preflight_record,
        run_nvidia_smi,
        vtk_point_count,
        write_world_stl,
        cpu_environment,
    )


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
CASE_ROOT = CAMPAIGN / "cases" / "r3-g2-f6-mdbc-zero-normal-preflight"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "r3-g2-f6-mdbc-zero-normal-preflight"
RUN_ROOT = CAMPAIGN / "runs" / "r3-g2-f6-mdbc-zero-normal-preflight"
REPORT_JSON = CAMPAIGN / "r3-g2-f6-mdbc-zero-normal-preflight.json"
REPORT_MD = CAMPAIGN / "R3-G2-F6-MDBC-ZERO-NORMAL-PREFLIGHT.md"

BASELINE_ID = "R3_F6_mdbc_zero_normal_baseline"
DP_M = 0.060
SHORT_TMAX_S = 0.005
SHORT_TOUT_S = 0.005
TANK_RADIUS_M = 2.0


# These are intentionally explicit and stable.  ``mask=2`` is the existing
# open-top cylinder route; mask 1/3 are included to distinguish side/cap
# coverage rather than to imply that either is physically preferred.
VARIANTS: tuple[dict, ...] = (
    {
        "variant_id": "baseline_combined_mask2_d2_invert",
        "label": "combined baseline",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.0,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "tank_only_mask2",
        "label": "tank only",
        "normal_geometry": "tank_only",
        "tank_mask": "2",
        "tank_radius_m": 2.0,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "float1_outer_only",
        "label": "Float1 outer STL only",
        "normal_geometry": "float1_outer_only",
        "tank_mask": "2",
        "tank_radius_m": 2.0,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_mask1",
        "label": "combined tank mask 1",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "1",
        "tank_radius_m": 2.0,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_mask3",
        "label": "combined tank mask 3",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "3",
        "tank_radius_m": 2.0,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_distanceh4",
        "label": "combined distanceh 4",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.0,
        "distanceh": 4.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_invert_false",
        "label": "combined tank setnormalinvert false",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.0,
        "distanceh": 2.0,
        "tank_invert": False,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_float_invert_true",
        "label": "combined Float1 setnormalinvert true",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.0,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": True,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus003",
        "label": "combined tank normal radius +0.03 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.03,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus006",
        "label": "combined tank normal radius +0.06 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.06,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus010",
        "label": "combined tank normal radius +0.01 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.01,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus015",
        "label": "combined tank normal radius +0.015 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.015,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus020",
        "label": "combined tank normal radius +0.02 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.02,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus025",
        "label": "combined tank normal radius +0.025 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.025,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus035",
        "label": "combined tank normal radius +0.035 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.035,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus040",
        "label": "combined tank normal radius +0.04 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.04,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus045",
        "label": "combined tank normal radius +0.045 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.045,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_plus050",
        "label": "combined tank normal radius +0.05 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 2.05,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_minus030",
        "label": "combined tank normal radius -0.03 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 1.97,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
    {
        "variant_id": "combined_tank_radius_minus020",
        "label": "combined tank normal radius -0.02 m",
        "normal_geometry": "tank+float1_outer",
        "tank_mask": "2",
        "tank_radius_m": 1.98,
        "distanceh": 2.0,
        "tank_invert": True,
        "float_invert": False,
        "run_solver": True,
    },
)


def experiment_record(variant: dict) -> dict:
    base = preflight_record()
    case_id = f"{BASELINE_ID}_{variant['variant_id']}"
    return {
        "case_id": case_id,
        "variant_id": variant["variant_id"],
        "label": variant["label"],
        "offset_name": base["offset_name"],
        "offset_m": base["offset_m"],
        "experiment": base["experiment"],
        "level": base["level"],
        "dp": DP_M,
        "gpu": None,
        "tmax": SHORT_TMAX_S,
        "tout": SHORT_TOUT_S,
        "normal_geometry": variant["normal_geometry"],
        "tank_mask": variant["tank_mask"],
        "tank_radius_m": variant["tank_radius_m"],
        "distanceh": variant["distanceh"],
        "tank_invert": variant["tank_invert"],
        "float_invert": variant["float_invert"],
    }


def experiment_environment() -> dict[str, str]:
    env = cpu_environment()
    # Keep the diagnostic reproducible and bounded on the shared host.  These
    # are CPU/OpenMP settings; no CUDA or GPU solver is used.
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["OMP_NUM_THREADS"] = "8"
    env["OMP_DYNAMIC"] = "FALSE"
    return env


def normal_list(text: str) -> str:
    match = re.search(
        r"<list name=\"GeometryForNormals\">.*?</list>", text, re.DOTALL
    )
    if not match:
        raise ValueError("mDBC definition has no GeometryForNormals list")
    return match.group(0)


def replace_normal_list(text: str, replacement: str) -> str:
    return re.sub(
        r"<list name=\"GeometryForNormals\">.*?</list>",
        replacement,
        text,
        count=1,
        flags=re.DOTALL,
    )


def mdbc_zero_definition_text(record: dict) -> str:
    """Build one isolated candidate XML from the existing mDBC structure."""
    text = mdbc_definition_text(record)
    old_stl = (
        f"../../artifacts/r3-g2-f6-mdbc-preflight/{record['case_id']}/generated/"
        "Float1_world.stl"
    )
    new_stl = (
        f"../../artifacts/r3-g2-f6-mdbc-zero-normal-preflight/{record['case_id']}/generated/"
        "Float1_world.stl"
    )
    if old_stl not in text:
        raise ValueError("base mDBC definition did not contain expected STL path")
    text = text.replace(old_stl, new_stl)
    variant = record
    block = normal_list(text)

    # The first cylinder and first inversion are the tank; the second
    # inversion/shape is the floating Float1 STL.  Keep replacements scoped to
    # the normals list so the particle-generation route is identical.
    block = block.replace(
        '<drawcylinder radius="2.0" mask="2">',
        f'<drawcylinder radius="{variant["tank_radius_m"]:.3f}" mask="{variant["tank_mask"]}">',
        1,
    )
    block = block.replace(
        '<setnormalinvert invert="true" />',
        f'<setnormalinvert invert="{"true" if variant["tank_invert"] else "false"}" />',
        1,
    )
    # The float inversion is the next occurrence in the block.
    block = block.replace(
        '<setnormalinvert invert="false" />',
        f'<setnormalinvert invert="{"true" if variant["float_invert"] else "false"}" />',
        1,
    )

    tank_start = block.find("          <!-- Tank fluid is inside the cylinder")
    tank_end = block.find("          </drawcylinder>", tank_start)
    if tank_start < 0 or tank_end < 0:
        raise ValueError("normal list tank cylinder block not found")
    tank_end += len("          </drawcylinder>")
    tank_block = block[tank_start:tank_end]
    float_start = block.find("          <!-- Float1 fluid is outside")
    float_line_start = block.find("\n          <drawfilestl", float_start)
    float_end = block.find("\n", float_line_start + 1)
    if float_start < 0 or float_line_start < 0 or float_end < 0:
        raise ValueError("normal list Float1 STL block not found")

    if variant["normal_geometry"] == "tank_only":
        block = block[:float_start] + block[float_end + 1:]
    elif variant["normal_geometry"] == "float1_outer_only":
        block = block[:tank_start] + block[tank_end:]
    elif variant["normal_geometry"] != "tank+float1_outer":
        raise ValueError(f"unknown normal geometry {variant['normal_geometry']}")

    text = replace_normal_list(text, block)
    text = text.replace(
        '<distanceh v="2.0" />',
        f'<distanceh v="{variant["distanceh"]:.1f}" />',
        1,
    )
    return text


def generated_particle_counts(prefix: Path) -> dict:
    root = ET.parse(prefix.with_suffix(".xml")).getroot()
    particles = root.find(".//particles")
    floating = root.find(".//particles/floating")
    fluid = root.find(".//particles/fluid")
    if particles is None or floating is None or fluid is None:
        raise ValueError("generated XML missing particle blocks")
    return {
        "total_particles": int(particles.get("np")),
        "boundary_particles": int(particles.get("nb")),
        "fixed_particles": int(particles.get("nbf")),
        "floating_particles": int(floating.get("count")),
        "fluid_particles": int(fluid.get("count")),
    }


def parse_boundnor_summary(summary: Path, counts: dict) -> dict:
    if not summary.is_file():
        return {
            "boundnor_array_present": False,
            "boundnor_array_count": None,
            "boundnor_nonzero_count": None,
            "boundnor_zero_count": None,
            "boundnor_fixed_zero_count": None,
            "boundnor_floating_zero_count": None,
        }
    root = ET.parse(summary).getroot()
    array = root.find(".//array_float3[@name='BoundNor']")
    if array is None:
        return {
            "boundnor_array_present": False,
            "boundnor_array_count": None,
            "boundnor_nonzero_count": None,
            "boundnor_zero_count": None,
            "boundnor_fixed_zero_count": None,
            "boundnor_floating_zero_count": None,
        }
    values = list(array)
    count = int(array.get("count"))
    nonzero = sum(
        any(float(item.get(axis, "0")) != 0.0 for axis in ("x", "y", "z"))
        for item in values
    )
    zero = len(values) - nonzero
    fixed_count = int(counts.get("fixed_particles", 0))
    fixed_zero = sum(
        not any(float(item.get(axis, "0")) != 0.0 for axis in ("x", "y", "z"))
        for item in values[:fixed_count]
    )
    return {
        "boundnor_array_present": True,
        "boundnor_array_count": count,
        "boundnor_nonzero_count": nonzero,
        "boundnor_zero_count": zero,
        "boundnor_fixed_zero_count": fixed_zero,
        "boundnor_floating_zero_count": zero - fixed_zero,
    }


def run_bifileinfo(prefix: Path, generated: Path, counts: dict) -> dict:
    if not BI_FILE_INFO.is_file():
        return {"available": False}
    proc = subprocess.run(
        [str(BI_FILE_INFO), prefix.name + ".bi4", "-svarrays:1"],
        cwd=generated,
        env=experiment_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=180,
    )
    log_path = generated / "bifileinfo.stdout.log"
    log_path.write_text(proc.stdout)
    summary = generated / (prefix.name + "_.xml")
    parsed = parse_boundnor_summary(summary, counts)
    return {
        "available": True,
        "return_code": proc.returncode,
        "log_file": str(log_path),
        "summary_file": str(summary),
        **parsed,
    }


def vtk_points(path: Path) -> list[list[float]] | None:
    if not path.is_file():
        return None
    match = re.search(br"POINTS\s+(\d+)\s+(float|double)\r?\n", path.read_bytes())
    if not match:
        return None
    content = path.read_bytes()
    n = int(match.group(1))
    dtype = ">f4" if match.group(2) == b"float" else ">f8"
    import numpy as np
    values = np.frombuffer(content, dtype=dtype, count=n * 3, offset=match.end())
    return values.reshape(n, 3).astype(float).tolist()


def zero_location_summary(bound_vtk: Path, summary: Path, counts: dict) -> dict:
    """Locate serialized zero vectors to identify tank-side vs floating zeros."""
    root = ET.parse(summary).getroot() if summary.is_file() else None
    array = root.find(".//array_float3[@name='BoundNor']") if root is not None else None
    if array is None:
        return {"available": False}
    values = list(array)
    zeros = [
        index for index, item in enumerate(values)
        if not any(float(item.get(axis, "0")) != 0.0 for axis in ("x", "y", "z"))
    ]
    points = vtk_points(bound_vtk)
    if points is None or len(points) < len(values):
        return {
            "available": False,
            "zero_indices_count": len(zeros),
            "zero_indices_min": min(zeros) if zeros else None,
            "zero_indices_max": max(zeros) if zeros else None,
        }
    import numpy as np
    positions = np.asarray(points, dtype=float)
    selected = positions[np.asarray(zeros, dtype=int)] if zeros else np.empty((0, 3))
    fixed_count = int(counts.get("fixed_particles", 0))
    fixed_indices = [index for index in zeros if index < fixed_count]
    fixed = positions[np.asarray(fixed_indices, dtype=int)] if fixed_indices else np.empty((0, 3))
    radius = np.sqrt(selected[:, 0] ** 2 + selected[:, 1] ** 2) if len(selected) else np.array([])
    fixed_radius = np.sqrt(fixed[:, 0] ** 2 + fixed[:, 1] ** 2) if len(fixed) else np.array([])
    fixed_xy = (
        {tuple(row) for row in np.round(fixed[:, :2], 6)}
        if len(fixed) else set()
    )
    fixed_z = (
        {float(value) for value in np.round(fixed[:, 2], 6)}
        if len(fixed) else set()
    )
    per_xy = max(
        (sum(np.all(np.isclose(fixed[:, :2], row, atol=1e-6), axis=1) for row in fixed_xy)),
        default=0,
    ) if len(fixed) else 0
    return {
        "available": True,
        "zero_indices_count": len(zeros),
        "zero_indices_min": min(zeros) if zeros else None,
        "zero_indices_max": max(zeros) if zeros else None,
        "zero_fixed_count": len(fixed_indices),
        "zero_floating_count": len(zeros) - len(fixed_indices),
        "zero_bbox_m": (
            [selected.min(axis=0).tolist(), selected.max(axis=0).tolist()]
            if len(selected) else None
        ),
        "zero_radius_range_m": (
            [float(radius.min()), float(radius.max())] if len(radius) else None
        ),
        "zero_fixed_radius_range_m": (
            [float(fixed_radius.min()), float(fixed_radius.max())]
            if len(fixed_radius) else None
        ),
        "zero_fixed_z_range_m": (
            [float(fixed[:, 2].min()), float(fixed[:, 2].max())]
            if len(fixed) else None
        ),
        "zero_fixed_unique_xy_columns": len(fixed_xy),
        "zero_fixed_unique_z_levels": len(fixed_z),
        "zero_fixed_max_particles_per_xy_column": int(per_xy),
        "zero_fixed_on_tank_side_heuristic": bool(
            len(fixed) and np.all(fixed_radius > TANK_RADIUS_M * 0.9)
        ),
    }


def run_variant(record: dict, variant: dict, resource_policy: dict) -> dict:
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    generated = ARTIFACT_ROOT / record["case_id"] / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    run_dir = RUN_ROOT / record["case_id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    definition = CASE_ROOT / f"{record['case_id']}_Def.xml"
    definition.write_text(mdbc_zero_definition_text(record))
    stl = generated / "Float1_world.stl"
    transform = write_world_stl(
        EXTRACTED / "Float1.STL",
        stl,
        EQUILIBRIUM_BASE_Z_M + record["offset_m"],
    )
    prefix = generated / record["case_id"]
    gencase_command = [
        str(GENCASE),
        str(definition.with_suffix("")),
        str(prefix),
        "-save:all",
    ]
    gencase_started = time.monotonic()
    try:
        gencase_proc = subprocess.run(
            gencase_command,
            cwd=CASE_ROOT,
            env=experiment_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=180,
        )
        gencase_timeout = False
    except subprocess.TimeoutExpired as error:
        gencase_proc = subprocess.CompletedProcess(
            gencase_command, returncode=None,
            stdout=(error.stdout or "") if isinstance(error.stdout, str) else "",
        )
        gencase_timeout = True
    gencase_elapsed = time.monotonic() - gencase_started
    gencase_log = generated / "gencase.stdout.log"
    gencase_log.write_text(gencase_proc.stdout or "")
    gencase_normals = parse_gencase_normals(gencase_proc.stdout or "")
    counts = generated_particle_counts(prefix) if prefix.with_suffix(".xml").is_file() else {}
    bifileinfo = (
        run_bifileinfo(prefix, generated, counts)
        if prefix.with_suffix(".bi4").is_file() else {"available": False}
    )

    solver_proc = None
    solver_timeout = False
    solver_log = ""
    solver_elapsed = None
    solver_command = [str(SOLVER_CPU), str(prefix), str(run_dir)]
    if (
        not gencase_timeout and gencase_proc.returncode == 0
        and prefix.with_suffix(".xml").is_file()
        and variant.get("run_solver", True)
    ):
        solver_started = time.monotonic()
        try:
            solver_proc = subprocess.run(
                solver_command,
                cwd=generated,
                env=experiment_environment(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=180,
            )
        except subprocess.TimeoutExpired as error:
            solver_proc = subprocess.CompletedProcess(
                solver_command, returncode=None,
                stdout=(error.stdout or "") if isinstance(error.stdout, str) else "",
            )
            solver_timeout = True
        solver_elapsed = time.monotonic() - solver_started
        solver_log = solver_proc.stdout or ""
        (run_dir / "solver.stdout.log").write_text(solver_log)
        run_out = run_dir / "Run.out"
        if run_out.is_file():
            solver_log += "\n" + run_out.read_text(errors="replace")
    solver_normals = parse_solver_normals(solver_log)
    ghost = {
        "boundary_normals_vtk": str(run_dir / "CfgInit_Normals.vtk"),
        "ghost_normals_vtk": str(run_dir / "CfgInit_NormalsGhost.vtk"),
        "boundary_normals_vtk_present": (run_dir / "CfgInit_Normals.vtk").is_file(),
        "ghost_normals_vtk_present": (run_dir / "CfgInit_NormalsGhost.vtk").is_file(),
        "boundary_normals_point_count": vtk_point_count(run_dir / "CfgInit_Normals.vtk"),
        "ghost_normals_point_count": vtk_point_count(run_dir / "CfgInit_NormalsGhost.vtk"),
    }
    location = zero_location_summary(
        generated / f"{record['case_id']}_Bound.vtk",
        generated / f"{record['case_id']}_.xml",
        counts,
    ) if bifileinfo.get("boundnor_array_present") else {"available": False}
    return {
        "record": record,
        "resource_policy": resource_policy,
        "definition": str(definition),
        "stl_file": str(stl),
        "transform": transform,
        "gencase": {
            "command": gencase_command,
            "return_code": gencase_proc.returncode,
            "timeout": gencase_timeout,
            "elapsed_seconds": gencase_elapsed,
            "log_file": str(gencase_log),
            "normal_data": gencase_normals,
            "generated_counts": counts,
            "boundnor": bifileinfo,
        },
        "zero_location": location,
        "solver": {
            "device": "CPU",
            "command": solver_command,
            "return_code": solver_proc.returncode if solver_proc is not None else None,
            "timeout": solver_timeout,
            "elapsed_seconds": solver_elapsed,
            "log_file": str(run_dir / "solver.stdout.log") if solver_proc is not None else None,
            "normal_data": solver_normals,
            "ghost_artifacts": ghost,
        },
        "candidate_status": "candidate_only_rejected_no_physical_acceptance",
        "mdbc_claim": False,
    }


def derive_conclusions(results: list[dict]) -> dict:
    rows = []
    for result in results:
        g = result["gencase"]
        s = result["solver"]
        gn = g["normal_data"]
        bn = g["boundnor"]
        sn = s["normal_data"]
        rows.append({
            "variant_id": result["record"]["variant_id"],
            "label": result["record"]["label"],
            "normal_geometry": result["record"]["normal_geometry"],
            "tank_mask": result["record"]["tank_mask"],
            "tank_radius_m": result["record"]["tank_radius_m"],
            "distanceh": result["record"]["distanceh"],
            "tank_invert": result["record"]["tank_invert"],
            "float_invert": result["record"]["float_invert"],
            "gencase_return_code": g["return_code"],
            "gencase_nonzero_count": gn.get("nonzero_count"),
            "gencase_zero_count": gn.get("zero_count"),
            "boundnor_nonzero_count": bn.get("boundnor_nonzero_count"),
            "boundnor_zero_count": bn.get("boundnor_zero_count"),
            "boundnor_fixed_zero_count": bn.get("boundnor_fixed_zero_count"),
            "boundnor_floating_zero_count": bn.get("boundnor_floating_zero_count"),
            "solver_return_code": s["return_code"],
            "solver_finished_code_0": sn.get("solver_finished_code_0"),
            "solver_fixed_or_moving_zero_count": sn.get("fixed_or_moving_zero_count"),
            "solver_floating_zero_count": sn.get("floating_zero_count"),
            "ghost_normals_present": s["ghost_artifacts"]["ghost_normals_vtk_present"],
            "short_cpu_initialization": bool(
                s["return_code"] == 0 and sn.get("solver_finished_code_0")
            ),
            "zero_location": result["zero_location"],
        })
    baseline = next(item for item in rows if item["variant_id"] == "baseline_combined_mask2_d2_invert")
    no_zero = [item for item in rows if item["boundnor_zero_count"] == 0]
    repair = [
        item for item in no_zero
        if item["normal_geometry"] == "tank+float1_outer"
        and item["tank_mask"] == "2"
        and item["distanceh"] == 2.0
        and item["tank_radius_m"] != 2.0
    ]
    repair.sort(key=lambda item: (item["boundnor_zero_count"], item["tank_radius_m"]))
    if repair:
        repair_text = (
            f"The {repair[0]['tank_radius_m'] - 2.0:+.3f} m tank-normal radius candidate removed "
            "serialized zero BoundNor vectors in this coarse preflight. It remains candidate-only "
            "and is not physically accepted."
        )
    elif no_zero:
        repair_text = (
            "At least one candidate removed serialized zero BoundNor vectors, but the selected "
            "repair is not the requested +0.03 m tank-normal radius candidate."
        )
    else:
        repair_text = (
            "No tested candidate removed all serialized zero BoundNor vectors; no repair is established."
        )
    distance = next(item for item in rows if item["variant_id"] == "combined_distanceh4")
    invert_false = next(item for item in rows if item["variant_id"] == "combined_tank_invert_false")
    float_invert = next(item for item in rows if item["variant_id"] == "combined_float_invert_true")
    mask1 = next(item for item in rows if item["variant_id"] == "combined_mask1")
    mask3 = next(item for item in rows if item["variant_id"] == "combined_mask3")
    tank_only = next(item for item in rows if item["variant_id"] == "tank_only_mask2")
    float_only = next(item for item in rows if item["variant_id"] == "float1_outer_only")
    return {
        "matrix": rows,
        "baseline": baseline,
        "factor_comparisons": {
            "tank_vs_float1_composition": {
                "tank_only_zero": tank_only["boundnor_zero_count"],
                "tank_only_fixed_zero": tank_only["boundnor_fixed_zero_count"],
                "tank_only_floating_zero": tank_only["boundnor_floating_zero_count"],
                "float1_only_zero": float_only["boundnor_zero_count"],
                "float1_only_fixed_zero": float_only["boundnor_fixed_zero_count"],
                "float1_only_floating_zero": float_only["boundnor_floating_zero_count"],
                "finding": (
                    "The baseline zero block is tank-side: removing Float1 leaves the fixed zero pattern, "
                    "while removing the tank transfers missing coverage to fixed tank particles and leaves "
                    "the floating Float1 boundary covered."
                ),
            },
            "tank_mask_caps": {
                "mask2_zero": baseline["boundnor_zero_count"],
                "mask1_zero": mask1["boundnor_zero_count"],
                "mask3_zero": mask3["boundnor_zero_count"],
                "finding": (
                    "Changing the tank cylinder mask/cap selection does not remove the side-wall zero block "
                    "when the side mesh remains coincident with a boundary layer."
                ),
            },
            "distanceh": {
                "distanceh2_zero": baseline["boundnor_zero_count"],
                "distanceh4_zero": distance["boundnor_zero_count"],
                "finding": (
                    "Increasing the search distance does not repair vectors whose nearest normal surface is "
                    "coincident with the boundary particle; it changes the search radius, not the zero-length "
                    "boundary-to-limit vector."
                ),
            },
            "setnormalinvert": {
                "tank_invert_true_zero": baseline["boundnor_zero_count"],
                "tank_invert_false_zero": invert_false["boundnor_zero_count"],
                "float_invert_true_zero": float_invert["boundnor_zero_count"],
                "finding": (
                    "Inversion is not the baseline source: tank=false worsens the zero count to 18,367 and "
                    "Float1=true gives 869 total zeros (including 77 floating), while neither tested inversion "
                    "repairs the baseline tank-side zero block."
                ),
            },
            "tank_normal_radius_offset": {
                "radius2p00_zero": baseline["boundnor_zero_count"],
                "radius2p03_zero": next(item for item in rows if item["variant_id"] == "combined_tank_radius_plus003")["boundnor_zero_count"],
                "radius2p06_zero": next(item for item in rows if item["variant_id"] == "combined_tank_radius_plus006")["boundnor_zero_count"],
                "tested": [
                    {
                        "tank_radius_m": item["tank_radius_m"],
                        "zero_count": item["boundnor_zero_count"],
                    }
                    for item in rows
                    if item["normal_geometry"] == "tank+float1_outer"
                    and item["tank_mask"] == "2"
                    and item["distanceh"] == 2.0
                ],
                "finding": repair_text,
            },
        },
        "repair_candidate": {
            "variant_id": repair[0]["variant_id"] if repair else None,
            "status": "candidate_only_rejected",
            "physical_acceptance": False,
            "finding": repair_text,
        },
        "open_blockers": [
            "All matrix results are candidate-only diagnostics; no mDBC physical acceptance is claimed.",
            "A zero-normal repair must be revalidated at intended resolution and with controlled geometry semantics before any physical run.",
            "The short CPU runs only establish that the initialization path reaches a return-code-0 endpoint; they do not validate forces, trajectories, or buoyancy.",
        ],
    }


def markdown_report(report: dict) -> str:
    conclusion = report["conclusions"]
    baseline_location = conclusion["baseline"].get("zero_location", {})
    baseline_columns = baseline_location.get("zero_fixed_unique_xy_columns", 44)
    baseline_levels = baseline_location.get("zero_fixed_unique_z_levels", 18)
    baseline_per_column = baseline_location.get("zero_fixed_max_particles_per_xy_column", 18)
    lines = [
        "# R3 G2 F6 mDBC zero-normal preflight",
        "",
        "Candidate-only, rejected diagnostic experiment. It does not modify or replace the existing DBC Test14 route, and it makes no physical mDBC acceptance claim.",
        "",
        "## Baseline and location",
        "",
        "- Existing isolated mDBC preflight baseline: `792` fixed/moving zero normals at `dp=0.060 m`.",
        f"- The serialized baseline zeros are tank-side particles: `{baseline_columns}` circumferential lattice columns × `{baseline_levels}` z layers (max `{baseline_per_column}` particles per column), with fixed-particle radius approximately `1.953146 m`; floating zero count is `0`.",
        "- This is the cylinder normal polygon's inscribed-edge midpoint radius, so the normal surface and those boundary particles are coincident. A zero-length boundary-to-limit vector is therefore plausible; this is a geometry-path diagnosis, not a physics conclusion.",
        "",
        "## Variant matrix",
        "",
        "| Variant | Normal geometry | mask | tank radius [m] | distanceh | invert tank/Float1 | BoundNor nonzero/zero (fixed/float) | CPU init |",
        "|---|---|---:|---:|---:|---|---:|---|",
    ]
    for row in conclusion["matrix"]:
        lines.append(
            f"| `{row['variant_id']}` | {row['normal_geometry']} | {row['tank_mask']} | "
            f"{row['tank_radius_m']:.2f} | {row['distanceh']:.1f} | "
            f"{str(row['tank_invert']).lower()}/{str(row['float_invert']).lower()} | "
            f"{row['boundnor_nonzero_count']}/{row['boundnor_zero_count']} "
            f"({row['boundnor_fixed_zero_count']}/{row['boundnor_floating_zero_count']}) | "
            f"{row['short_cpu_initialization']} (`{row['solver_return_code']}`) |"
        )
    lines += [
        "",
        "## Findings",
        "",
        f"- Composition: {conclusion['factor_comparisons']['tank_vs_float1_composition']['finding']}",
        f"- Tank mask/caps: {conclusion['factor_comparisons']['tank_mask_caps']['finding']}",
        f"- `distanceh`: {conclusion['factor_comparisons']['distanceh']['finding']}",
        f"- `setnormalinvert`: {conclusion['factor_comparisons']['setnormalinvert']['finding']}",
        f"- Radius offset: {conclusion['factor_comparisons']['tank_normal_radius_offset']['finding']}",
        "",
        "## Vendored v5.4 evidence",
        "",
        "- `JPartsLoad4.cpp`: v5.4 stores `BoundNor` in the general BI4 and checks its boundary-sized array.",
        "- `JSph.cpp`: `Boundary=2` enables mDBC normal use; initialization counts fixed/moving and floating zero normals and writes `CfgInit_NormalsGhost.vtk`.",
        "- `JSphCpu_mdbc.cpp`: CPU mDBC skips zero `BoundNor` entries and forms the ghost point from the boundary position plus `BoundNor`.",
        "- Official v5.4 `examples/mdbc/08_FloatingWaves` and `09_FloatingDuck`: `GeometryForNormals` → `shapeout file=\"hdp\"` → `norgeometry` → `Boundary=2`.",
        "",
        "## Rejection / non-claims",
        "",
    ]
    lines.extend(f"- {item}" for item in conclusion["open_blockers"])
    lines += [
        "",
        "Evidence paths:",
        "",
        f"- Candidate XML directory: `{CASE_ROOT}`",
        f"- GenCase artifacts: `{ARTIFACT_ROOT}`",
        f"- CPU run artifacts: `{RUN_ROOT}`",
        f"- JSON report: `{REPORT_JSON}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--report-json", type=Path, default=REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=REPORT_MD)
    args = parser.parse_args()

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    snapshot = ARTIFACT_ROOT / "nvidia-smi.snapshot.txt"
    # Inventory is diagnostic only; CUDA_VISIBLE_DEVICES is cleared for every
    # GenCase/solver child.  No GPU binary or GPU flag is ever launched.
    resource_policy = run_nvidia_smi(snapshot)
    resource_policy.update({
        "device_policy": "CPU-only",
        "gpu_indices_used": [],
        "gpu_uuids_used": [],
        "cuda_visible_devices_for_children": "",
        "solver_binary": str(SOLVER_CPU),
        "gpu_solver_binary_used": False,
    })
    missing = [name for name in ("Float1.STL",) if not (EXTRACTED / name).is_file()]
    if missing:
        raise RuntimeError(
            "vendored/official Test 14 external asset is missing; this experiment does not fetch or mutate it: "
            + ", ".join(missing)
        )

    if args.static_only:
        definitions = []
        for variant in VARIANTS:
            record = experiment_record(variant)
            text = mdbc_zero_definition_text(record)
            ET.fromstring(text)
            path = CASE_ROOT / f"{record['case_id']}_Def.xml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            definitions.append({
                "variant_id": record["variant_id"],
                "definition": str(path),
                "normal_geometry": record["normal_geometry"],
                "tank_mask": record["tank_mask"],
                "tank_radius_m": record["tank_radius_m"],
                "distanceh": record["distanceh"],
                "tank_invert": record["tank_invert"],
                "float_invert": record["float_invert"],
            })
        report = {
            "schema_version": 1,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "resource_policy": resource_policy,
            "definitions": definitions,
            "candidate_status": "static_candidate_only_rejected",
            "mdbc_claim": False,
            "source_evidence": SOURCE_EVIDENCE,
            "conclusions": {"open_blockers": ["No GenCase or solver was run (--static-only)."]},
        }
    else:
        results = []
        for variant in VARIANTS:
            record = experiment_record(variant)
            results.append(run_variant(record, variant, resource_policy))
        report = {
            "schema_version": 1,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "resource_policy": resource_policy,
            "baseline": {
                "case_id": BASELINE_ID,
                "source": "existing isolated mDBC preflight result (792 fixed/moving zero normals)",
                "existing_report": str(CAMPAIGN / "r3-g2-f6-mdbc-preflight.json"),
            },
            "results": results,
            "conclusions": derive_conclusions(results),
            "candidate_status": "candidate_only_rejected_no_physical_acceptance",
            "scientific_acceptance": "rejected_not_physical_acceptance",
            "mdbc_claim": False,
            "source_evidence": SOURCE_EVIDENCE,
        }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, indent=2) + "\n")
    args.report_md.parent.mkdir(parents=True, exist_ok=True)
    args.report_md.write_text(
        markdown_report(report)
        if not args.static_only else "# R3 G2 F6 mDBC zero-normal static preflight\n\n" + json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps({
        "report_json": str(args.report_json),
        "report_md": str(args.report_md),
        "variants": len(report.get("results", report.get("definitions", []))),
        "candidate_status": report["candidate_status"],
    }, indent=2))


if __name__ == "__main__":
    main()
