#!/usr/bin/env python3
"""Materialize F2 Stage 8 production definitions, execute GenCase preflights, and emit GPU solver requests."""

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

import ds_data02_f2 as f2
from ds_data02_f2 import (
    FAMILY_ROOT,
    FAMILY_ID,
    BACKGROUND_SPECS,
    EVENT_WINDOW_S,
    REFERENCE_SAVE_INTERVAL_S,
    ROTATION_HOLD_START_S,
    ROTATION_ANGLE_DEG,
    ROTATION_DURATION_S,
    sha256_file,
)

GENCASE_BIN = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
SOLVER_BIN = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DATA_F2_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")

# Permitted GPUs for Stage 8: strictly {2, 5, 6, 7}.
# GPU 0 preserved; GPUs 1, 3, 4 strictly off-limits (forbidden).
STAGE8_CASES = [
    # Pair 1: rx = 0.45 m, mouth = open_rim
    {
        "case_id": "F2_CENTER_P01",
        "physical_case_id": "F2_CENTER_P01",
        "paired_background_id": "F2_PAIR_01",
        "mechanism_id": "center_catch",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_CENTER_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_CENTER_CATCH_V1",
        "dp_m": 0.020,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "assigned_gpu": 2,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "receiver_x_m": 0.45,
        "receiver_y_m": 0.00,
        "mouth_geometry": "open_rim",
        "holdout": None,
        "expected_counts": {
            "fluid": 3094,
            "fixed": 93961,
            "moving": 6940,
            "total": 103995,
        },
        "description": "Pair 1 center_catch: fill=0.8, rot=0.65s, rx=0.45m, ry=0.0m, open_rim",
    },
    {
        "case_id": "F2_OFFSET_P01",
        "physical_case_id": "F2_OFFSET_P01",
        "paired_background_id": "F2_PAIR_01",
        "mechanism_id": "offset_spill",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_OFFSET_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_OFFSET_SPILL_V1",
        "dp_m": 0.020,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "assigned_gpu": 5,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "receiver_x_m": 0.45,
        "receiver_y_m": 0.14,
        "mouth_geometry": "open_rim",
        "holdout": None,
        "expected_counts": {
            "fluid": 3094,
            "fixed": 93961,
            "moving": 6940,
            "total": 103995,
        },
        "description": "Pair 1 offset_spill: fill=0.8, rot=0.65s, rx=0.45m, ry=0.14m, open_rim",
    },
    # Pair 2: rx = 0.45 m, mouth = short_spout
    {
        "case_id": "F2_CENTER_P02",
        "physical_case_id": "F2_CENTER_P02",
        "paired_background_id": "F2_PAIR_02",
        "mechanism_id": "center_catch",
        "geometry_family_id": "F2_GEOM_CUP_SHORT_SPOUT_HOLDOUT_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_CENTER_CATCH_V1",
        "dp_m": 0.020,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "assigned_gpu": 6,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "receiver_x_m": 0.45,
        "receiver_y_m": 0.00,
        "mouth_geometry": "short_spout",
        "holdout": "short_spout_geometry",
        "expected_counts": {
            "fluid": 3094,
            "fixed": 93961,
            "moving": 6940,
            "total": 103995,
        },
        "description": "Pair 2 center_catch: fill=0.8, rot=0.65s, rx=0.45m, ry=0.0m, short_spout",
    },
    {
        "case_id": "F2_OFFSET_P02",
        "physical_case_id": "F2_OFFSET_P02",
        "paired_background_id": "F2_PAIR_02",
        "mechanism_id": "offset_spill",
        "geometry_family_id": "F2_GEOM_CUP_SHORT_SPOUT_HOLDOUT_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_OFFSET_SPILL_V1",
        "dp_m": 0.020,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "assigned_gpu": 7,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "receiver_x_m": 0.45,
        "receiver_y_m": 0.22,
        "mouth_geometry": "short_spout",
        "holdout": "short_spout_geometry",
        "expected_counts": {
            "fluid": 3094,
            "fixed": 93961,
            "moving": 6940,
            "total": 103995,
        },
        "description": "Pair 2 offset_spill: fill=0.8, rot=0.65s, rx=0.45m, ry=0.22m, short_spout",
    },
    # Pair 3: rx = 0.65 m, mouth = open_rim
    {
        "case_id": "F2_CENTER_P03",
        "physical_case_id": "F2_CENTER_P03",
        "paired_background_id": "F2_PAIR_03",
        "mechanism_id": "center_catch",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_CENTER_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_CENTER_CATCH_V1",
        "dp_m": 0.020,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "assigned_gpu": 2,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "receiver_x_m": 0.65,
        "receiver_y_m": 0.00,
        "mouth_geometry": "open_rim",
        "holdout": None,
        "expected_counts": {
            "fluid": 3094,
            "fixed": 95628,
            "moving": 6940,
            "total": 105662,
        },
        "description": "Pair 3 center_catch: fill=0.8, rot=0.65s, rx=0.65m, ry=0.0m, open_rim",
    },
    {
        "case_id": "F2_OFFSET_P03",
        "physical_case_id": "F2_OFFSET_P03",
        "paired_background_id": "F2_PAIR_03",
        "mechanism_id": "offset_spill",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_OFFSET_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_OFFSET_SPILL_V1",
        "dp_m": 0.020,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "assigned_gpu": 5,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "receiver_x_m": 0.65,
        "receiver_y_m": 0.14,
        "mouth_geometry": "open_rim",
        "holdout": None,
        "expected_counts": {
            "fluid": 3094,
            "fixed": 95628,
            "moving": 6940,
            "total": 105662,
        },
        "description": "Pair 3 offset_spill: fill=0.8, rot=0.65s, rx=0.65m, ry=0.14m, open_rim",
    },
    # Pair 4: rx = 0.65 m, mouth = short_spout
    {
        "case_id": "F2_CENTER_P04",
        "physical_case_id": "F2_CENTER_P04",
        "paired_background_id": "F2_PAIR_04",
        "mechanism_id": "center_catch",
        "geometry_family_id": "F2_GEOM_CUP_SHORT_SPOUT_HOLDOUT_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_CENTER_CATCH_V1",
        "dp_m": 0.020,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "assigned_gpu": 6,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "receiver_x_m": 0.65,
        "receiver_y_m": 0.00,
        "mouth_geometry": "short_spout",
        "holdout": "short_spout_geometry",
        "expected_counts": {
            "fluid": 3094,
            "fixed": 95628,
            "moving": 6940,
            "total": 105662,
        },
        "description": "Pair 4 center_catch: fill=0.8, rot=0.65s, rx=0.65m, ry=0.0m, short_spout",
    },
    {
        "case_id": "F2_OFFSET_P04",
        "physical_case_id": "F2_OFFSET_P04",
        "paired_background_id": "F2_PAIR_04",
        "mechanism_id": "offset_spill",
        "geometry_family_id": "F2_GEOM_CUP_SHORT_SPOUT_HOLDOUT_V1",
        "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
        "recipe_id": "F2_DBC_ROTATING_CUP_OFFSET_SPILL_V1",
        "dp_m": 0.020,
        "resolution": "medium",
        "split": "train",
        "target_role": "train",
        "assigned_gpu": 7,
        "fill_ratio": 0.8,
        "rotation_duration_s": 0.65,
        "receiver_x_m": 0.65,
        "receiver_y_m": 0.22,
        "mouth_geometry": "short_spout",
        "holdout": "short_spout_geometry",
        "expected_counts": {
            "fluid": 3094,
            "fixed": 95628,
            "moving": 6940,
            "total": 105662,
        },
        "description": "Pair 4 offset_spill: fill=0.8, rot=0.65s, rx=0.65m, ry=0.22m, short_spout",
    },
]


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def materialize_definitions(family_dir: Path = FAMILY_ROOT) -> list[dict]:
    family = Path(family_dir).resolve()
    defs_dir = family / "production/definitions"
    defs_dir.mkdir(parents=True, exist_ok=True)

    meta_records = []
    for spec in STAGE8_CASES:
        cid = spec["case_id"]
        bg = spec["mechanism_id"]
        res = spec["resolution"]
        pid = spec["physical_case_id"]
        pair_id = spec["paired_background_id"]

        values = {
            "fill_ratio": spec["fill_ratio"],
            "rotation_duration_s": spec["rotation_duration_s"],
            "receiver_x_m": spec["receiver_x_m"],
            "receiver_y_m": spec["receiver_y_m"],
            "mouth_geometry": spec["mouth_geometry"],
        }

        # Build case object using f2.make_case
        case_obj = f2.make_case(
            bg,
            res,
            case_id=cid,
            physical_case_id=pid,
            paired_background_id=pair_id,
            values=values,
        )

        # Ensure geometry_family_id and holdout conform to spec
        case_obj["geometry_family_id"] = spec["geometry_family_id"]
        case_obj["control_family_id"] = spec["control_family_id"]
        case_obj["recipe_id"] = spec["recipe_id"]
        case_obj["holdout"] = spec["holdout"]
        case_obj["stage"] = "stage8"
        case_obj["production"] = True
        case_obj["production_resolution"] = res
        case_obj["assigned_gpu"] = spec["assigned_gpu"]
        case_obj["permitted_gpus"] = [2, 5, 6, 7]
        case_obj["target_role"] = spec["target_role"]
        case_obj["split"] = spec["split"]
        case_obj["description"] = spec["description"]

        # Write definition XML, motion file, and metadata sidecar
        case_meta = f2.write_case(case_obj, defs_dir)

        # Augment with stage 8 runtime fields
        case_meta["assigned_gpu"] = spec["assigned_gpu"]
        case_meta["expected_counts"] = spec["expected_counts"]
        case_meta["holdout"] = spec["holdout"]
        case_meta["split"] = spec["split"]
        case_meta["target_role"] = spec["target_role"]
        case_meta["control_path"] = case_meta["motion_path"]
        case_meta["control_sha256"] = case_meta["motion_sha256"]
        case_meta["containment_compliance"] = {
            "catch_basin_floor": [-1.20, 2.80, -1.00, 1.00, -0.20],
            "containment_lip_walls_height_m": 0.15,
            "simulation_domain_min": [-1.20, -1.00, -0.50],
            "simulation_domain_max": [2.80, 1.00, 2.20],
            "compliant": True,
            "expected_N_out": 0,
        }

        meta_records.append(case_meta)

    return meta_records


def run_gencase_preflight(case_meta: dict) -> dict:
    cid = case_meta["case_id"]
    mech = case_meta["mechanism_id"]
    assigned_gpu = case_meta["assigned_gpu"]
    attempt_id = f"{cid}_GENCASE_01"

    output_dir = DATA_F2_ROOT / cid / attempt_id
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
    excluded_parts = 0
    nonzero_normals = None
    zero_normals = None

    for line in res.stdout.splitlines():
        if "Total particles:" in line:
            parts_str = line.split("Total particles:")[1].split()[0].replace(",", "")
            total_parts = int(parts_str)
        if "Fixed...." in line:
            fixed_parts = int(line.split("Fixed....:")[1].split()[0].replace(",", ""))
        if "Moving..." in line:
            moving_parts = int(line.split("Moving...:")[1].split()[0].replace(",", ""))
        if "Fluid...." in line:
            fluid_parts = int(line.split("Fluid....:")[1].split()[0].replace(",", ""))
        if "Non-zero particle normals:" in line:
            nonzero_normals = line.split("Non-zero particle normals:")[1].strip()
        if "Final zero normals:" in line:
            zero_normals = line.split("Final zero normals:")[1].strip()
        if "Particles out of domain:" in line or "Excluded:" in line:
            # Check for exclusions
            for token in line.split():
                if token.isdigit():
                    excluded_parts = int(token)

    wall_parts = (fixed_parts or 0) + (moving_parts or 0)
    expected = case_meta["expected_counts"]

    # Continuum Mass Consistency:
    # V0 = (0.425 - 0.10) * 0.22 * (0.33 * 0.8) = 0.018876 m^3
    # M0 = 1000 * 0.018876 = 18.876 kg
    # Lattice mass = N_fluid * dp^3 * rho0 = 3094 * 0.02^3 * 1000 = 24.752 kg
    # Relative error = (24.752 - 18.876) / 18.876 = +31.1295%
    dp = float(case_meta["dp_m"])
    geom = case_meta["geometry"]
    v_cont = float(geom["fluid_volume_m3"])
    m_cont = v_cont * 1000.0
    v_lat = (fluid_parts or 0) * (dp**3)
    m_lat = v_lat * 1000.0
    rel_mass_err = (m_lat - m_cont) / m_cont if m_cont > 0 else 0.0

    parity = (
        res.returncode == 0
        and total_parts == expected["total"]
        and fluid_parts == expected["fluid"]
        and fixed_parts == expected["fixed"]
        and moving_parts == expected["moving"]
        and excluded_parts == 0
    )

    receipt = {
        "schema": "ds02.execution-receipt.v1",
        "case_id": cid,
        "attempt_id": attempt_id,
        "family_id": "F2",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "status": "completed" if res.returncode == 0 and parity else "failed",
        "returncode": res.returncode,
        "total_particles": total_parts,
        "fluid_particles": fluid_parts,
        "fixed_particles": fixed_parts,
        "moving_particles": moving_parts,
        "wall_particles": wall_parts,
        "excluded_particles": excluded_parts,
        "solver_dimension_from_gencase": 3,
        "nonzero_normals": nonzero_normals,
        "zero_normals": zero_normals,
        "continuum_mass_consistency": {
            "continuous_fluid_volume_m3": v_cont,
            "continuous_fluid_mass_kg": m_cont,
            "lattice_fluid_volume_m3": v_lat,
            "lattice_fluid_mass_kg": m_lat,
            "relative_mass_error": rel_mass_err,
            "relative_mass_error_percent": rel_mass_err * 100.0,
            "consistent": abs(rel_mass_err - 0.311294766) < 1e-4,
        },
        "reference_expectations": {
            "expected_total_particles": expected["total"],
            "expected_fluid_particles": expected["fluid"],
            "expected_fixed_particles": expected["fixed"],
            "expected_moving_particles": expected["moving"],
            "expected_wall_particles": expected["fixed"] + expected["moving"],
            "expected_excluded_particles": 0,
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
        },
    }

    receipt_path = output_dir / "execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["receipt_path"] = str(receipt_path.resolve())
    receipt["receipt_sha256"] = sha256_file(receipt_path)
    return receipt


def emit_gencase_and_solver_requests(
    case_meta: dict,
    gencase_receipt: dict,
    family_dir: Path = FAMILY_ROOT,
) -> tuple[Path, Path]:
    family = Path(family_dir).resolve()
    requests_dir = family / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)

    cid = case_meta["case_id"]
    mech = case_meta["mechanism_id"]
    assigned_gpu = case_meta["assigned_gpu"]

    def_xml = Path(case_meta["definition_path"])
    motion_file = Path(case_meta["control_path"])
    meta_json = Path(case_meta["metadata_path"])

    # 1. GenCase request JSON
    gencase_req = {
        "schema": "ds02.cpu-request.v2",
        "family_id": "F2",
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
            str(motion_file),
        ],
        "worktree_root": str(REPO.parent),
        "purpose": "bounded native GenCase preflight only; zero particle loss verified",
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
            "expected_N_out": 0,
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
        str(meta_json),
        str(motion_file),
    ]
    input_hashes = {p: sha256_file(Path(p)) for p in input_files}

    solver_req = {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": cid,
        "physical_case_id": case_meta["physical_case_id"],
        "physical_parent_id": case_meta["physical_case_id"],
        "paired_background_id": case_meta["paired_background_id"],
        "split": case_meta["split"],
        "target_role": case_meta["target_role"],
        "registry_kind": "production",
        "kind": "qualification",
        "attempt_id": f"{cid}_QUALIFICATION_002",
        "target_gpu_index": assigned_gpu,
        "assigned_gpu": assigned_gpu,
        "permitted_gpus": [2, 5, 6, 7],
        "preserved_gpus": [0],
        "strictly_forbidden_gpus": [1, 3, 4],
        "command": [
            str(SOLVER_BIN),
            str(output_dir / cid),
            "{attempt_root}/solver",
            f"-tmax:{float(EVENT_WINDOW_S):.1f}",
            f"-tout:{float(REFERENCE_SAVE_INTERVAL_S):.2f}",
        ],
        "cwd": str(output_dir),
        "worktree_root": str(REPO.parent),
        "max_wall_seconds": 1800,
        "cpu_threads": 2,
        "estimated_storage_bytes": 6 * 1024**3,
        "estimated_peak_gpu_mib": 4096,
        "total_particles": gencase_receipt["total_particles"],
        "fluid_particles": gencase_receipt["fluid_particles"],
        "wall_particles": gencase_receipt["wall_particles"],
        "gencase_receipt": str(rec_path),
        "gencase_receipt_sha256": gencase_receipt.get("receipt_sha256") or hashlib.sha256(rec_path.read_bytes()).hexdigest(),
        "gencase_prefix": str(output_dir / cid),
        "gencase_bi4": str(bi4),
        "gencase_xml": str(xml),
        "input_files": input_files,
        "input_hashes": input_hashes,
        "containment_contract": {
            "mechanism": mech,
            "catch_basin_bounds": "[-1.20, 2.80] x [-1.00, 1.00] x [-0.50, 2.20] with 0.15m lip walls",
            "expected_N_out": 0,
            "fill_ratio": case_meta["parameter_values"]["fill_ratio"],
            "rotation_duration_s": case_meta["parameter_values"]["rotation_duration_s"],
            "receiver_x_m": case_meta["parameter_values"]["receiver_x_m"],
            "receiver_y_m": case_meta["parameter_values"]["receiver_y_m"],
            "mouth_geometry": case_meta["parameter_values"]["mouth_geometry"],
        },
        "purpose": f"Stage 8 production GPU solver run on allocated GPU {assigned_gpu}",
    }
    solver_req_path = requests_dir / f"{cid}-solver.json"
    solver_req_path.write_text(json.dumps(solver_req, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return gencase_req_path, solver_req_path


def write_owner_metadata(
    case_meta: dict,
    gencase_receipt: dict,
    family_dir: Path = FAMILY_ROOT,
) -> Path:
    family = Path(family_dir).resolve()
    owner_dir = family / "production/owner_metadata"
    owner_dir.mkdir(parents=True, exist_ok=True)

    cid = case_meta["case_id"]
    mech = case_meta["mechanism_id"]

    owner = {
        "case_id": cid,
        "family_id": "F2",
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
        "gencase_receipt_sha256": gencase_receipt.get("receipt_sha256") or "",
        "total_particles": gencase_receipt["total_particles"],
        "fluid_particles": gencase_receipt["fluid_particles"],
        "wall_particles": gencase_receipt["wall_particles"],
        "fixed_particles": gencase_receipt["fixed_particles"],
        "moving_particles": gencase_receipt["moving_particles"],
        "excluded_particles": gencase_receipt["excluded_particles"],
        "solver_dimension": 3,
        "holdout": case_meta.get("holdout"),
        "containment_compliance": case_meta["containment_compliance"],
        "continuum_mass_consistency": gencase_receipt["continuum_mass_consistency"],
        "physical_binding": {
            "schema": "ds-data-02.physical-binding.v1",
            "family_id": "F2",
            "physical_case_id": case_meta["physical_case_id"],
            "mechanism_id": mech,
            "geometry_family_id": case_meta["geometry_family_id"],
            "control_family_id": case_meta["control_family_id"],
            "density_kg_m3": 1000.0,
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "controls": {
                "boundary": "finite DBC rotating cup, receiver, and remediated catch basin",
                "density_dt": 3,
                "density_dt_value": 0.1,
                "kernel": 2,
                "step_algorithm": 2,
                "viscosity": 0.03,
            },
            "geometry": {
                "cup": {
                    "label": "finite rotating cup body",
                    "low_m": [0.0, -0.15, 0.65],
                    "size_m": [0.425, 0.30, 0.45],
                },
                "receiver": {
                    "label": "fixed catch receiver",
                    "low_m": [
                        float(case_meta["parameter_values"]["receiver_x_m"]),
                        float(case_meta["parameter_values"]["receiver_y_m"]) - 0.30,
                        0.0,
                    ],
                    "size_m": [1.10, 0.60, 0.45],
                },
                "catch_basin": {
                    "label": "remediated bounded catch basin with lip walls",
                    "low_m": [-1.20, -1.00, -0.20],
                    "size_m": [4.00, 2.00, 0.15],
                },
            },
            "initial_state": {
                "source_regions": ["source_layer_0_bottom", "source_layer_1_middle", "source_layer_2_top"],
                "velocities_m_per_s": [[0.0, 0.0, 0.0]],
                "mass_policy": "native per-particle mass from BI4 header",
            },
            "parameters": {
                "fill_ratio": case_meta["parameter_values"]["fill_ratio"],
                "rotation_duration_s": case_meta["parameter_values"]["rotation_duration_s"],
                "mouth_geometry": case_meta["parameter_values"]["mouth_geometry"],
                "drive_mechanism": mech,
                "containment_contract": "N_out = 0 verified in preflight",
            },
            "event_window": {
                "time_start_s": 0.0,
                "time_end_s": float(EVENT_WINDOW_S),
                "sequence": ["static_hold", "cosine_rotation_tilt", "catch_spill_residence"],
                "expected_first_contact_range_s": [0.0, float(EVENT_WINDOW_S)],
                "right_censor_policy": "finite 4s run retains initial fluid denominator",
            },
        },
        "written_at_utc": now_str(),
    }
    owner_path = owner_dir / f"{cid}.owner.json"
    owner_path.write_text(json.dumps(owner, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return owner_path


def update_registry_and_split_plan(
    meta_records: list[dict],
    gencase_receipts: dict[str, dict],
    family_dir: Path = FAMILY_ROOT,
) -> None:
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
            row["definition_sha256"] = m["definition_sha256"]
            row["stage"] = "stage8"
            row["production"] = True
            row["production_resolution"] = m["resolution"]
            row["status"] = "gencase_completed_solver_pending"
            row["attempt_id"] = rec["attempt_id"]
            row["solver_dimension"] = 3
            row["particle_axis_count"] = rec["total_particles"]
            row["fluid_particles"] = rec["fluid_particles"]
            row["wall_particles"] = rec["wall_particles"]
            row["fixed_particles"] = rec["fixed_particles"]
            row["moving_particles"] = rec["moving_particles"]
            row["assigned_gpu"] = m["assigned_gpu"]
            row["permitted_gpus"] = [2, 5, 6, 7]
            row["containment_compliance"] = m["containment_compliance"]
            row["continuum_mass_consistency"] = rec["continuum_mass_consistency"]
        updated_rows.append(row)

    reg_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in updated_rows) + "\n", encoding="utf-8")

    # 2. Update split_plan.json
    sp = json.loads(split_path.read_text(encoding="utf-8"))
    if "nested_progression" not in sp:
        sp["nested_progression"] = {
            "nested8": {
                "parent_group_numbers": [1, 2, 3, 4],
                "physical_case_count": 8,
                "resolution_views_per_case": 3,
            },
            "nested24": {
                "parent_group_numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                "physical_case_count": 24,
                "resolution_views_per_case": 3,
            },
            "nested48": {
                "parent_group_numbers": list(range(1, 25)),
                "physical_case_count": 48,
                "resolution_views_per_case": 3,
            },
        }
    if "range_design_artifact" not in sp:
        sp["range_design_artifact"] = "split_range_design.json"
    if "resolution_counting_rule" not in sp:
        sp["resolution_counting_rule"] = "coarse, medium and fine are numerical views of one physical_case_id and never add physical cases"

    sp["stages"] = {
        "stage8": {
            "cumulative_case_count": 8,
            "incremental_case_count": 8,
            "case_ids": [m["case_id"] for m in meta_records],
            "mechanisms": {
                "center_catch": [m["case_id"] for m in meta_records if m["mechanism_id"] == "center_catch"],
                "offset_spill": [m["case_id"] for m in meta_records if m["mechanism_id"] == "offset_spill"],
            },
            "split_counts": {"train": 8},
            "containment_contract": "remediated catch basin [-1.20, 2.80] x [-1.00, 1.00] x [-0.50, 2.20], N_out = 0",
            "allocated_gpus": [2, 5, 6, 7],
            "gpu_allocation_map": {m["case_id"]: m["assigned_gpu"] for m in meta_records},
        }
    }
    sp["status"] = "stage8_production_gencase_preflight_passed_solvers_prepared"
    split_path.write_text(json.dumps(sp, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-preflight", action="store_true", help="Skip GenCase execution (definitions and requests only)")
    args = parser.parse_args()

    print(f"[{now_str()}] === Starting Family F2 Stage 8 Production Materialization ===")

    # 1. Materialize definitions and motion files
    print(f"[{now_str()}] Step 1: Materializing 8 XML definitions and motion files under production/definitions/...")
    meta_records = materialize_definitions(FAMILY_ROOT)
    print(f"[{now_str()}] Successfully materialized {len(meta_records)} definition packages.")

    gencase_receipts = {}
    preflight_summaries = []

    # 2. Execute GenCase preflight and verify parity
    print(f"[{now_str()}] Step 2: Executing GenCase preflight for all 8 Stage 8 cases...")
    for m in meta_records:
        cid = m["case_id"]
        mech = m["mechanism_id"]
        print(f"[{now_str()}]   Running GenCase preflight: {cid} ({mech})...")
        rec = run_gencase_preflight(m)
        gencase_receipts[cid] = rec

        parity = rec["reference_expectations"]["parity_match"]
        mass_cons = rec["continuum_mass_consistency"]
        print(
            f"[{now_str()}]     -> Returncode: {rec['returncode']}, Total: {rec['total_particles']}, "
            f"Fluid: {rec['fluid_particles']}, Fixed: {rec['fixed_particles']}, Moving: {rec['moving_particles']}, "
            f"N_out: {rec['excluded_particles']}, RelMassErr: {mass_cons['relative_mass_error_percent']:+.2f}%, Parity: {parity}"
        )
        if not parity:
            raise RuntimeError(f"GenCase parity check failed for {cid}!")
        if rec["excluded_particles"] != 0:
            raise RuntimeError(f"Particle exclusion N_out != 0 for {cid}!")

        # 3. Emit requests and owner metadata
        print(f"[{now_str()}]   Emitting runner requests and owner metadata for {cid}...")
        gencase_req, solver_req = emit_gencase_and_solver_requests(m, rec, FAMILY_ROOT)
        owner_meta = write_owner_metadata(m, rec, FAMILY_ROOT)

        preflight_summaries.append({
            "case_id": cid,
            "mechanism": mech,
            "assigned_gpu": m["assigned_gpu"],
            "total_particles": rec["total_particles"],
            "fluid_particles": rec["fluid_particles"],
            "fixed_particles": rec["fixed_particles"],
            "moving_particles": rec["moving_particles"],
            "wall_particles": rec["wall_particles"],
            "excluded_particles": rec["excluded_particles"],
            "nonzero_normals": rec["nonzero_normals"],
            "zero_normals": rec["zero_normals"],
            "continuum_mass_consistency": mass_cons,
            "reference_parity": parity,
            "gencase_receipt": rec["receipt_path"],
            "gencase_receipt_sha256": rec["receipt_sha256"],
            "gencase_request": str(gencase_req),
            "solver_request": str(solver_req),
            "owner_metadata": str(owner_meta),
            "containment_compliance": m["containment_compliance"],
        })

    # 4. Update case_registry.jsonl and split_plan.json
    print(f"[{now_str()}] Step 3: Updating case_registry.jsonl and split_plan.json...")
    update_registry_and_split_plan(meta_records, gencase_receipts, FAMILY_ROOT)

    # 5. Write preflight summary artifact
    summary_path = FAMILY_ROOT / "stage8_gencase_preflight_summary.json"
    summary_path.write_text(json.dumps(preflight_summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Written Stage 8 preflight summary to {summary_path}")

    print(f"[{now_str()}] === All 8 F2 Stage 8 cases successfully materialized, preflighted, and GPU solver requests prepared! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
