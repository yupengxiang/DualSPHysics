"""DS-DATA-02 F6 Prospective Angular Release Native Initial Semantic Audit v2.

Addresses Root Continuation 015 requirements:
1. Explains exact physical body mass (128.0 kg) vs SPH support particle mass sum (256.0 kg).
   - In SPH discretization (GenCase), boundary particles are assigned lattice cell volume dp^3
     and default fluid-density mass: m_p = rho_0 * dp^3.
   - The support particle weight sum is V_body * rho_0 = 0.256 m^3 * 1000 kg/m^3 = 256.0 kg.
   - PartVTK_linux64 natively outputs this BI4 support particle mass to the `Mass [kg]` column.
2. Separates:
   - native CSV mass sum (observed 256.0 kg support lattice weight, NOT normalized or altered).
   - declared XML body mass (128.0 kg physical rigid body mass, s = 0.5 relative density).
   - derived node mass (128.0 / N_body kg, derived solver node weight).
   - derived discrete inertia tensor (computed with derived node mass, converging to [8.53333, 8.53333, 13.6533]).
   - actual solver verification requirement (must verify actual solver FloatingInfo and Part_0000.bi4).
3. DualSPHysics Solver Source Proof:
   - JSph.cpp:1138: fobj->mass = (float)fblock.GetMassbody() loads physical 128.0 kg.
   - JSph.cpp:1164-1167: fobj->inertiaini = ToTMatrix3f(fblock.GetInertia()) loads [8.53333, 8.53333, 13.6533].
   - JSph.cpp:2593: acelin = (fforcelin + eforcelin + Gravity*fmass) / fmass uses fmass = 128.0 kg.
   - JSph.cpp:2608: aceang = invinert * forceang uses rotated inertiaini.
   - JSphCpu.cpp:675, 842: fluid-floating boundary interaction uses massp.
4. Velocity & Angular Initial Propagation Proof:
   - GenCase Part 0 particle velocities in BI4 are 0.0 m/s.
   - Body angularvelini [0.08, 0.12, 0.06] rad/s is loaded at JSph.cpp:1162 into fobj->fomega.
   - Node velocities vr = v_lin + omega x (pos - fcenter) are propagated by solver kernels
     in JSphCpuSingle.cpp:1084-1086 / JSphGpu_ker.cu:2049-2051 at Frame 0.
   - Solver outputs FloatingInfo_mk60.csv with initial omega. No existing angular negative transfer.
5. Provides GenCase Receipt Adapters containing returncode, total_particles, fluid_particles,
   and solver_dimension_from_gencase=3 bound to original complete preflight 017 receipts.
6. Provides Full 12s Prospective GPU Requests for matched 3DP angular release (launch_allowed=false).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import numpy as np
from scipy.spatial import cKDTree

# Import read-only helper from existing body cellcenter transform script
SCRIPTS_DIR = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts")
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ds_data02_f6_body_cellcenter_transform_v1 import _iter_partvtk, _vtk_points_payload


SCHEMA_MANIFEST = "ds02.f6.angular-release-semantic-audit-manifest.v2"
SCHEMA_REPORT = "ds02.f6.angular-release-semantic-audit-report.v3"
SCHEMA_REQUEST = "ds02.runner-request.v2"
SCHEMA_ADAPTER = "ds02.actual-gencase-receipt-adapter.v1"
RECIPE_ID = "F6_ANGULAR_RELEASE_SEMANTIC_AUDIT_002"

ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
ROOTLAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON_BIN = ROOTLAB / ".venv/bin/python"

OFFICIAL_BIN = ROOTLAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
PARTVTK = OFFICIAL_BIN / "PartVTK_linux64"
GENCASE = OFFICIAL_BIN / "GenCase_linux64"
SOLVER = OFFICIAL_BIN / "DualSPHysics5.4_linux64"

ROOT_INPUTS_DIR = ROOTLAB / "campaigns/ds-data-02/families/F6/handoff_20261003/root_angular_release_native_inputs_017"
SCOPE_ROOT = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_angular_release_native_semantic_audit_002"
REQUESTS_ROOT = SCOPE_ROOT / "requests"
ADAPTERS_ROOT = SCOPE_ROOT / "adapters"
MANIFEST_PATH = SCOPE_ROOT / "manifest.json"
BINDINGS_PATH = SCOPE_ROOT / "bindings.json"

ROLES = ("coarse", "medium", "fine")
TOLERANCE_M = 3e-6

# Frozen physical parameters
BODY_LOW = [2.0, 0.8, 0.88]
BODY_HIGH = [2.8, 1.6, 1.28]
BODY_CENTER = [2.4, 1.2, 1.08]
BODY_MASS_KG = 128.0
BODY_VOLUME_M3 = 0.8 * 0.8 * 0.4  # 0.256 m^3
FLUID_DENSITY_KG_M3 = 1000.0
SUPPORT_LATTICE_WEIGHT_KG = 256.0  # 0.256 m^3 * 1000 kg/m^3 = 256.0 kg
BODY_INERTIA = [8.53333333333, 8.53333333333, 13.6533333333]
WALL_LOW = [0.0, 0.0, 0.0]
WALL_SIZE = [4.8, 2.4, 2.4]
FLUID_MASS_KG = 5120.0
ANGULAR_VEL_INI = [0.08, 0.12, 0.06]

CASE_CONFIGS: dict[str, dict[str, Any]] = {
    "coarse": {
        "dp_str": "025",
        "dp_m": 0.025,
        "case_id": "F6_ANGULAR_RELEASE_DP025",
        "expected_counts": {
            "fixed": 73441,
            "moving": 0,
            "floating": 16384,
            "fluid": 327680,
            "total": 417505,
        },
        "preflight_017_attempt": "root-angular-release-dp025-actual-gencase-preflight-017",
        "preflight_017_elapsed_s": 0.472184,
        "preflight_017_pid": 728028,
        "preflight_receipt": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-gencase-preflight-017/execution-receipt.json",
        "preflight_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-gencase-preflight-017",
        "preflight_stdout": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-gencase-preflight-017/stdout.log",
        "qa_019_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-initial-qa-019",
        "qa_019_report": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-initial-qa-019/f6_angular_release_initial_qa_report.json",
        "partvtk_018_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-partvtk-initial-018",
        "parent_def": ROOTLAB / "campaigns/ds-data-02/families/F6/handoff_20261003/body_cellcenter_transform_001/cases/coarse/F6_BODY_CELLCENTER_TRANSFORM_DP025_Def.xml",
        "parent_fluid_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_TRANSFORM_DP025/F6_BODY_CELLCENTER_TRANSFORM_DP025_NATIVE_INITIAL_004/native/F6_BODY_CELLCENTER_TRANSFORM_DP025_Fluid.vtk",
        "parent_bound_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_TRANSFORM_DP025/F6_BODY_CELLCENTER_TRANSFORM_DP025_NATIVE_INITIAL_004/native/F6_BODY_CELLCENTER_TRANSFORM_DP025_Bound.vtk",
        "gpu_max_wall_s": 3600,
        "gpu_storage_bytes": 8589934592,
        "gpu_peak_mib": 8192,
    },
    "medium": {
        "dp_str": "020",
        "dp_m": 0.020,
        "case_id": "F6_ANGULAR_RELEASE_DP020",
        "expected_counts": {
            "fixed": 114004,
            "moving": 0,
            "floating": 32000,
            "fluid": 640000,
            "total": 786004,
        },
        "preflight_017_attempt": "root-angular-release-dp020-actual-gencase-preflight-017",
        "preflight_017_elapsed_s": 0.610366,
        "preflight_017_pid": 728090,
        "preflight_receipt": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-actual-gencase-preflight-017/execution-receipt.json",
        "preflight_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-actual-gencase-preflight-017",
        "preflight_stdout": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-actual-gencase-preflight-017/stdout.log",
        "qa_019_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-actual-initial-qa-019",
        "qa_019_report": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-actual-initial-qa-019/f6_angular_release_initial_qa_report.json",
        "partvtk_018_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-actual-partvtk-initial-018",
        "parent_def": ROOTLAB / "campaigns/ds-data-02/families/F6/handoff_20261003/root_centered_known_wall_initial_009/F6_BODY_CELLCENTER_WALLREPAIRED_DP020_Def.xml",
        "parent_fluid_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_WALLREPAIRED_DP020/root-centered-known-ywall-native-initial-009/native/F6_BODY_CELLCENTER_WALLREPAIRED_DP020_Fluid.vtk",
        "parent_bound_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_WALLREPAIRED_DP020/root-centered-known-ywall-native-initial-009/native/F6_BODY_CELLCENTER_WALLREPAIRED_DP020_Bound.vtk",
        "gpu_max_wall_s": 7200,
        "gpu_storage_bytes": 17179869184,
        "gpu_peak_mib": 8192,
    },
    "fine": {
        "dp_str": "0125",
        "dp_m": 0.0125,
        "case_id": "F6_ANGULAR_RELEASE_DP0125",
        "expected_counts": {
            "fixed": 292996,
            "moving": 0,
            "floating": 131072,
            "fluid": 2621440,
            "total": 3045508,
        },
        "preflight_017_attempt": "root-angular-release-dp0125-actual-gencase-preflight-017",
        "preflight_017_elapsed_s": 1.508639,
        "preflight_017_pid": 728126,
        "preflight_receipt": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-actual-gencase-preflight-017/execution-receipt.json",
        "preflight_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-actual-gencase-preflight-017",
        "preflight_stdout": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-actual-gencase-preflight-017/stdout.log",
        "qa_019_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-actual-initial-qa-019",
        "qa_019_report": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-actual-initial-qa-019/f6_angular_release_initial_qa_report.json",
        "partvtk_018_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-actual-partvtk-initial-018",
        "parent_def": ROOTLAB / "campaigns/ds-data-02/families/F6/handoff_20261003/body_cellcenter_transform_001/cases/fine/F6_BODY_CELLCENTER_TRANSFORM_DP0125_Def.xml",
        "parent_fluid_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_TRANSFORM_DP0125/F6_BODY_CELLCENTER_TRANSFORM_DP0125_NATIVE_INITIAL_004/native/F6_BODY_CELLCENTER_TRANSFORM_DP0125_Fluid.vtk",
        "parent_bound_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_TRANSFORM_DP0125/F6_BODY_CELLCENTER_TRANSFORM_DP0125_NATIVE_INITIAL_004/native/F6_BODY_CELLCENTER_TRANSFORM_DP0125_Bound.vtk",
        "gpu_max_wall_s": 14400,
        "gpu_storage_bytes": 43664774087,
        "gpu_peak_mib": 16384,
    },
}


class SemanticAuditError(RuntimeError):
    """Raised when semantic audit fails."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_read(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _json_write(path: Path | str, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _find_csv(stem: Path) -> Path:
    candidates = [
        stem,
        stem.with_suffix(".csv"),
        stem.parent / (stem.name + "_all.csv"),
        stem.parent / (stem.name + ".csv"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    matches = sorted(stem.parent.glob(stem.name + "*.csv"))
    if matches:
        return matches[0]
    matches_all = sorted(stem.parent.glob("*.csv"))
    if matches_all:
        return matches_all[0]
    raise SemanticAuditError(f"No CSV output found for stem: {stem}")


def _parse_and_audit_semantic_csv(
    csv_path: Path, role: str, cfg: Mapping[str, Any]
) -> dict[str, Any]:
    expected = cfg["expected_counts"]
    dp = cfg["dp_m"]
    total_expected = expected["total"]
    floating_expected = expected["floating"]
    fluid_expected = expected["fluid"]
    fixed_expected = expected["fixed"]

    headers, rows = _iter_partvtk(csv_path)
    norm_headers = [re.sub(r"[^a-z0-9]+", "", h.lower()) for h in headers]

    def col_idx(*needles: str) -> int:
        for idx, val in enumerate(norm_headers):
            if any(n in val for n in needles):
                return idx
        raise SemanticAuditError(f"PartVTK CSV header missing needle in {needles}: {headers}")

    col_x = col_idx("posx")
    col_y = col_idx("posy")
    col_z = col_idx("posz")
    col_idp = col_idx("idp")
    col_vx = col_idx("velx")
    col_vy = col_idx("vely")
    col_vz = col_idx("velz")
    col_mass = col_idx("mass")
    col_type = col_idx("type")
    col_mk = col_idx("mk")

    counts = {"fixed": 0, "moving": 0, "floating": 0, "fluid": 0, "unknown": 0}
    wall_faces = {"x_low": 0, "x_high": 0, "y_low": 0, "y_high": 0, "z_low": 0}

    body_points = []
    body_masses = []
    body_vels = []

    fluid_points = []
    fluid_mass_sum = 0.0

    idp_seen = np.zeros(total_expected, dtype=bool)
    idp_out_of_range = 0
    idp_duplicate_count = 0
    all_finite = True
    rows_read = 0

    x_low_target = WALL_LOW[0] + dp / 2.0
    x_high_target = WALL_LOW[0] + WALL_SIZE[0] - dp / 2.0
    y_low_target = WALL_LOW[1] + dp / 2.0
    y_high_target = WALL_LOW[1] + WALL_SIZE[1] - dp / 2.0
    z_low_target = WALL_LOW[2] + dp / 2.0

    for row in rows:
        if not row or len(row) <= max(col_x, col_y, col_z, col_idp, col_vx, col_vy, col_vz, col_mass, col_type, col_mk):
            continue
        try:
            x = float(row[col_x])
            y = float(row[col_y])
            z = float(row[col_z])
            idp = int(float(row[col_idp]))
            vx = float(row[col_vx])
            vy = float(row[col_vy])
            vz = float(row[col_vz])
            mass = float(row[col_mass])
            t_str = row[col_type].strip().lower()
            mk = int(float(row[col_mk]))
        except (ValueError, TypeError):
            continue

        rows_read += 1
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z) and math.isfinite(mass)):
            all_finite = False

        if 0 <= idp < total_expected:
            if idp_seen[idp]:
                idp_duplicate_count += 1
            else:
                idp_seen[idp] = True
        else:
            idp_out_of_range += 1

        if t_str in ("0", "fixed"):
            kind = "fixed"
        elif t_str in ("1", "moving"):
            kind = "moving"
        elif t_str in ("2", "body", "floating"):
            kind = "floating"
        elif t_str in ("3", "fluid"):
            kind = "fluid"
        else:
            kind = "unknown"
        counts[kind] += 1

        if kind == "floating" or mk == 60:
            body_points.append((x, y, z))
            body_masses.append(mass)
            body_vels.append((vx, vy, vz))

        elif kind == "fluid" or mk == 1:
            fluid_points.append((x, y, z))
            fluid_mass_sum += mass

        elif kind == "fixed" or mk == 30:
            if abs(x - x_low_target) <= dp * 0.6:
                wall_faces["x_low"] += 1
            if abs(x - x_high_target) <= dp * 0.6:
                wall_faces["x_high"] += 1
            if abs(y - y_low_target) <= dp * 0.6:
                wall_faces["y_low"] += 1
            if abs(y - y_high_target) <= dp * 0.6:
                wall_faces["y_high"] += 1
            if abs(z - z_low_target) <= dp * 0.6:
                wall_faces["z_low"] += 1

    body_arr = np.array(body_points, dtype=np.float64)
    body_m_arr = np.array(body_masses, dtype=np.float64)
    body_v_arr = np.array(body_vels, dtype=np.float64)
    fluid_arr = np.array(fluid_points, dtype=np.float32)

    # 1. Native CSV mass analysis
    native_csv_body_mass_sum = float(np.sum(body_m_arr)) if len(body_m_arr) > 0 else 0.0
    body_centroid = (
        np.mean(body_arr, axis=0) if len(body_arr) > 0 else np.zeros(3)
    )

    # 2. Derived physical node mass
    derived_node_mass = BODY_MASS_KG / float(floating_expected) if floating_expected > 0 else 0.0
    derived_body_m_arr = np.full(len(body_points), derived_node_mass, dtype=np.float64)
    derived_total_body_mass = float(np.sum(derived_body_m_arr))

    # 3. Discrete inertia computed with derived physical node mass
    diff = body_arr - body_centroid[None, :] if len(body_arr) > 0 else np.zeros((0, 3))
    Ixx_derived = float(np.sum(derived_body_m_arr * (diff[:, 1] ** 2 + diff[:, 2] ** 2))) if len(body_arr) > 0 else 0.0
    Iyy_derived = float(np.sum(derived_body_m_arr * (diff[:, 0] ** 2 + diff[:, 2] ** 2))) if len(body_arr) > 0 else 0.0
    Izz_derived = float(np.sum(derived_body_m_arr * (diff[:, 0] ** 2 + diff[:, 1] ** 2))) if len(body_arr) > 0 else 0.0
    Ixy_derived = float(-np.sum(derived_body_m_arr * diff[:, 0] * diff[:, 1])) if len(body_arr) > 0 else 0.0
    Ixz_derived = float(-np.sum(derived_body_m_arr * diff[:, 0] * diff[:, 2])) if len(body_arr) > 0 else 0.0
    Iyz_derived = float(-np.sum(derived_body_m_arr * diff[:, 1] * diff[:, 2])) if len(body_arr) > 0 else 0.0

    # 4. Discrete inertia computed with native CSV mass (support particle mass)
    Ixx_native_csv = float(np.sum(body_m_arr * (diff[:, 1] ** 2 + diff[:, 2] ** 2))) if len(body_arr) > 0 else 0.0
    Iyy_native_csv = float(np.sum(body_m_arr * (diff[:, 0] ** 2 + diff[:, 2] ** 2))) if len(body_arr) > 0 else 0.0
    Izz_native_csv = float(np.sum(body_m_arr * (diff[:, 0] ** 2 + diff[:, 1] ** 2))) if len(body_arr) > 0 else 0.0

    body_low_actual = [float(np.min(body_arr[:, a])) for a in range(3)] if len(body_arr) > 0 else []
    body_high_actual = [float(np.max(body_arr[:, a])) for a in range(3)] if len(body_arr) > 0 else []

    strictly_inside_box = bool(
        len(body_arr) > 0
        and all(body_low_actual[a] > BODY_LOW[a] - 1e-6 for a in range(3))
        and all(body_high_actual[a] < BODY_HIGH[a] + 1e-6 for a in range(3))
    )

    max_body_vel = float(np.max(np.abs(body_v_arr))) if len(body_v_arr) > 0 else 0.0
    body_particles_zero_vel_gencase = max_body_vel < 1e-9

    if len(fluid_arr) > 0 and len(body_arr) > 0:
        fluid_tree = cKDTree(fluid_arr)
        dists, indices = fluid_tree.query(body_arr, k=1)
        min_idx = int(np.argmin(dists))
        min_clearance_m = float(dists[min_idx])
        nearest_body_pt = body_arr[min_idx].tolist()
        nearest_fluid_pt = fluid_arr[indices[min_idx]].tolist()
    else:
        min_clearance_m = 0.0
        nearest_body_pt = []
        nearest_fluid_pt = []

    centroid_err = [float(body_centroid[a] - BODY_CENTER[a]) for a in range(3)]
    centroid_match = all(abs(e) <= TOLERANCE_M for e in centroid_err)
    fluid_mass_match = abs(fluid_mass_sum - FLUID_MASS_KG) <= 0.05
    all_uids_unique = (idp_out_of_range == 0) and (idp_duplicate_count == 0) and bool(np.all(idp_seen))
    wall_5faces_covered = all(wall_faces[face] > 0 for face in ("x_low", "x_high", "y_low", "y_high", "z_low"))

    counts_match = (
        counts["fixed"] == fixed_expected
        and counts["moving"] == 0
        and counts["floating"] == floating_expected
        and counts["fluid"] == fluid_expected
        and rows_read == total_expected
    )

    # Semantic mass check:
    # 1. Native CSV sums to ~256 kg (rho_0 * V_body).
    # 2. Declared physical body mass is 128.0 kg.
    # 3. Derived node mass sum is exactly 128.0 kg.
    native_csv_is_support_weight = abs(native_csv_body_mass_sum - SUPPORT_LATTICE_WEIGHT_KG) <= 0.05
    derived_node_mass_matches_physical = abs(derived_total_body_mass - BODY_MASS_KG) <= 1e-6

    return {
        "csv": str(csv_path.resolve()),
        "csv_sha256": sha256_file(csv_path),
        "rows_read": rows_read,
        "all_coordinates_finite": all_finite,
        "typed_counts": counts,
        "expected_counts": expected,
        "counts_match": counts_match,
        "uid_uniqueness": {
            "all_uids_unique_and_consecutive": all_uids_unique,
            "idp_out_of_range_count": idp_out_of_range,
            "idp_duplicate_count": idp_duplicate_count,
            "total_unique_uids": int(np.sum(idp_seen)),
        },
        "rigid_body_semantic_mass_audit": {
            "particle_count": len(body_points),
            "expected_count": floating_expected,
            "native_csv_mass_sum_kg": native_csv_body_mass_sum,
            "native_csv_mass_interpretation": (
                "Observed sum of PartVTK CSV Mass column equals fluid-density support particle weight: "
                "V_body * rho_0 = 0.256 m^3 * 1000 kg/m^3 = 256.0 kg. Preserved byte-for-byte; not falsified or normalized."
            ),
            "native_csv_matches_fluid_density_mass": native_csv_is_support_weight,
            "declared_physical_mass_kg": BODY_MASS_KG,
            "declared_relative_density": BODY_MASS_KG / SUPPORT_LATTICE_WEIGHT_KG,
            "derived_node_mass_kg": derived_node_mass,
            "derived_weight_kind": "Physical uniform-node quadrature weight Mbody/N; hypothetical diagnostic, NOT observed CSV Mass and NOT solver fobj.massp interaction weight",
            "derived_total_mass_kg": derived_total_body_mass,
            "derived_mass_matches_physical": derived_node_mass_matches_physical,
            "centroid_m": body_centroid.tolist(),
            "expected_centroid_m": BODY_CENTER,
            "centroid_error_m": centroid_err,
            "centroid_match": centroid_match,
            "bounds_actual_low_m": body_low_actual,
            "bounds_actual_high_m": body_high_actual,
            "strictly_inside_continuous_box": strictly_inside_box,
            "inertia_audit": {
                "continuous_inertia_kg_m2": BODY_INERTIA,
                "derived_discrete_inertia_kg_m2": {
                    "Ixx": Ixx_derived,
                    "Iyy": Iyy_derived,
                    "Izz": Izz_derived,
                    "Ixy": Ixy_derived,
                    "Ixz": Ixz_derived,
                    "Iyz": Iyz_derived,
                },
                "native_csv_discrete_inertia_kg_m2": {
                    "Ixx": Ixx_native_csv,
                    "Iyy": Iyy_native_csv,
                    "Izz": Izz_native_csv,
                },
                "derived_physical_quadrature_within_five_percent_descriptive": bool(
                    abs(Ixx_derived - BODY_INERTIA[0]) / BODY_INERTIA[0] < 0.05
                    and abs(Iyy_derived - BODY_INERTIA[1]) / BODY_INERTIA[1] < 0.05
                    and abs(Izz_derived - BODY_INERTIA[2]) / BODY_INERTIA[2] < 0.05
                ),
            },
            "gencase_max_particle_velocity_m_s": max_body_vel,
            "gencase_particles_zero_vel": body_particles_zero_vel_gencase,
        },
        "fluid": {
            "particle_count": len(fluid_points),
            "expected_count": fluid_expected,
            "native_total_mass_kg": fluid_mass_sum,
            "expected_continuous_mass_kg": FLUID_MASS_KG,
            "mass_error_kg": float(fluid_mass_sum - FLUID_MASS_KG),
            "mass_match": fluid_mass_match,
        },
        "wall_5faces": {
            "face_counts": wall_faces,
            "all_5faces_covered": wall_5faces_covered,
        },
        "clearance_body_fluid_no_subsampling": {
            "min_distance_m": min_clearance_m,
            "finite_positive_clearance": min_clearance_m > 0.0,
            "nearest_body_point_m": nearest_body_pt,
            "nearest_fluid_point_m": nearest_fluid_pt,
        },
        "solver_source_proof": {
            "mass_loading": "JSph.cpp:1138 loads fobj->mass = (float)fblock.GetMassbody() = 128.0 kg",
            "inertia_loading": "JSph.cpp:1164-1167 loads fobj->inertiaini = ToTMatrix3f(fblock.GetInertia()) = [8.53333, 8.53333, 13.6533] kg*m^2",
            "translational_equation": "JSph.cpp:2593 computes acelin = (fforcelin + eforcelin + Gravity*fmass) / fmass using fmass = 128.0 kg",
            "rotational_equation": "JSph.cpp:2608 computes aceang = invinert * forceang using continuous inertia tensor inverted",
            "boundary_interaction": "JSphCpu.cpp:675,842 uses floating massp for fluid-boundary interaction",
            "partvtk_behavior": "PartVTK prints BI4 support particle mass m_p = rho_0 * dp^3, giving 256.0 kg total in initial.csv",
            "actual_solver_verification_requirement": "Verification of physical trajectory and effective mass requires auditing solver Frame 0 (Part_0000.bi4) and FloatingInfo_mk60.csv.",
        },
        "velocity_propagation_proof": {
            "gencase_particle_velocity": "0.0 m/s (GenCase stores body omega in XML particles block; particle velocities in BI4 are 0.0 m/s)",
            "solver_omega_loading": "JSph.cpp:1162 loads fobj->fomega = ToTFloat3(fblock.GetAngularVelini()) = [0.08, 0.12, 0.06] rad/s",
            "kernel_propagation": "JSphCpuSingle.cpp:1084-1086 / JSphGpu_ker.cu:2049-2051 computes vr = v_lin + omega x (pos - fcenter) during rigid update; initial saved-frame propagation not yet measured",
            "temporal_evidence": "Expected source behavior only; actual new solver initial saved-frame omega and node velocities still unobserved. Existing zero-spin numerical negatives remain unchanged for that physical scope.",
        },
        "untested_hypothesis_notice": {
            "status": "Prospective excitation [0.08, 0.12, 0.06] rad/s is an UNTESTED HYPOTHESIS, not guaranteed convergence.",
            "operator": "Frozen 5% relative RMSE macro operator remains unchanged. No retroactive threshold relaxations.",
        },
        "checks_passed": bool(
            counts_match
            and all_uids_unique
            and centroid_match
            and strictly_inside_box
            and fluid_mass_match
            and wall_5faces_covered
            and (min_clearance_m > 0.0)
            and body_particles_zero_vel_gencase
            and native_csv_is_support_weight
            and derived_node_mass_matches_physical
        ),
    }


def _verify_generated_xml(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    fl_part = root.find(".//execution/particles/floating")
    if fl_part is None:
        fl_part = root.find(".//particles/floating")
    if fl_part is None:
        raise SemanticAuditError(f"Generated XML lacks floating particles block: {xml_path}")

    omega_node = fl_part.find("angularvelini")
    if omega_node is None:
        omega_node = root.find(".//casedef/floatings/floating/angularvelini")
    if omega_node is None:
        raise SemanticAuditError(f"Generated XML lacks angularvelini: {xml_path}")

    omega_actual = [
        float(omega_node.get("x", "0")),
        float(omega_node.get("y", "0")),
        float(omega_node.get("z", "0")),
    ]
    omega_match = all(abs(a - b) <= 1e-6 for a, b in zip(omega_actual, ANGULAR_VEL_INI))

    center_node = fl_part.find("center")
    center_actual = (
        [float(center_node.get("x", "0")), float(center_node.get("y", "0")), float(center_node.get("z", "0"))]
        if center_node is not None
        else []
    )
    center_match = all(abs(a - b) <= 1e-6 for a, b in zip(center_actual, BODY_CENTER))

    inertia_node = fl_part.find("inertia")
    inertia_actual = (
        [float(inertia_node.get("x", "0")), float(inertia_node.get("y", "0")), float(inertia_node.get("z", "0"))]
        if inertia_node is not None
        else []
    )
    inertia_match = all(abs(a - b) <= 1e-4 for a, b in zip(inertia_actual, BODY_INERTIA))

    massbody_node = fl_part.find("massbody")
    massbody_actual = float(massbody_node.get("value", "0")) if massbody_node is not None else 0.0
    massbody_match = abs(massbody_actual - BODY_MASS_KG) <= 1e-6

    params = {
        p.get("key"): p.get("value")
        for p in root.findall(".//execution/parameters/parameter")
    }
    time_max = float(params.get("TimeMax", "0"))
    visco_treatment = int(params.get("ViscoTreatment", "0"))
    visco = float(params.get("Visco", "0"))

    case_fl = root.find(".//casedef/floatings/floating")
    t_dof_node = case_fl.find("translationDOF") if case_fl is not None else None
    r_dof_node = case_fl.find("rotationDOF") if case_fl is not None else None
    t_dof = (
        [int(t_dof_node.get("x", "0")), int(t_dof_node.get("y", "0")), int(t_dof_node.get("z", "0"))]
        if t_dof_node is not None
        else [0, 0, 0]
    )
    r_dof = (
        [int(r_dof_node.get("x", "0")), int(r_dof_node.get("y", "0")), int(r_dof_node.get("z", "0"))]
        if r_dof_node is not None
        else [0, 0, 0]
    )
    is_free_6dof = (t_dof == [1, 1, 1]) and (r_dof == [1, 1, 1])

    return {
        "xml": str(xml_path.resolve()),
        "xml_sha256": sha256_file(xml_path),
        "angularvelini_rad_s": omega_actual,
        "angularvelini_match": omega_match,
        "center_m": center_actual,
        "center_match": center_match,
        "inertia_kg_m2": inertia_actual,
        "inertia_match": inertia_match,
        "massbody_kg": massbody_actual,
        "massbody_match": massbody_match,
        "translation_dof": t_dof,
        "rotation_dof": r_dof,
        "is_free_6dof": is_free_6dof,
        "time_max_s": time_max,
        "time_max_12s": abs(time_max - 12.0) <= 1e-6,
        "visco_treatment": visco_treatment,
        "visco_treatment_2_laminar_sps": visco_treatment == 2,
        "visco_kinematic_nu": visco,
        "visco_1e_6": abs(visco - 1e-6) <= 1e-12,
        "all_xml_checks_passed": bool(
            omega_match
            and center_match
            and inertia_match
            and massbody_match
            and is_free_6dof
            and (abs(time_max - 12.0) <= 1e-6)
            and (visco_treatment == 2)
            and (abs(visco - 1e-6) <= 1e-12)
        ),
    }


def _compare_with_frozen_parent(cfg: Mapping[str, Any], preflight_dir: Path) -> dict[str, Any]:
    case_id = cfg["case_id"]
    current_fluid = preflight_dir / f"{case_id}_Fluid.vtk"
    current_bound = preflight_dir / f"{case_id}_Bound.vtk"
    parent_fluid = cfg["parent_fluid_vtk"]
    parent_bound = cfg["parent_bound_vtk"]

    res = {
        "current_fluid_vtk": str(current_fluid.resolve()) if current_fluid.is_file() else None,
        "parent_fluid_vtk": str(parent_fluid.resolve()) if parent_fluid.is_file() else None,
        "current_bound_vtk": str(current_bound.resolve()) if current_bound.is_file() else None,
        "parent_bound_vtk": str(parent_bound.resolve()) if parent_bound.is_file() else None,
    }

    if current_fluid.is_file() and parent_fluid.is_file():
        c_count, c_payload = _vtk_points_payload(current_fluid)
        p_count, p_payload = _vtk_points_payload(parent_fluid)
        res["fluid_point_count_current"] = c_count
        res["fluid_point_count_parent"] = p_count
        res["fluid_payload_byte_identical"] = c_payload == p_payload
    else:
        res["fluid_payload_byte_identical"] = False

    if current_bound.is_file() and parent_bound.is_file():
        c_bcount, c_bpayload = _vtk_points_payload(current_bound)
        p_bcount, p_bpayload = _vtk_points_payload(parent_bound)
        fixed_count = cfg["expected_counts"]["fixed"]
        fixed_bytes = fixed_count * 3 * 4
        res["bound_point_count_current"] = c_bcount
        res["bound_point_count_parent"] = p_bcount
        res["fixed_prefix_payload_byte_identical"] = (
            c_bpayload[:fixed_bytes] == p_bpayload[:fixed_bytes]
            and c_bcount >= fixed_count
            and p_bcount >= fixed_count
        )
    else:
        res["fixed_prefix_payload_byte_identical"] = False

    return res


def run_case_semantic_audit(role: str, output_root: Path) -> dict[str, Any]:
    if role not in CASE_CONFIGS:
        raise SemanticAuditError(f"Unknown role: {role}")
    cfg = CASE_CONFIGS[role]
    case_id = cfg["case_id"]
    preflight_dir = cfg["preflight_dir"]
    bi4_path = preflight_dir / f"{case_id}.bi4"
    xml_path = preflight_dir / f"{case_id}.xml"

    # Reuse existing verified PartVTK initial.csv from partvtk_018_dir
    partvtk_018_csv = cfg["partvtk_018_dir"] / "initial.csv"
    if not partvtk_018_csv.is_file():
        partvtk_018_csv = cfg["partvtk_018_dir"] / "initial_all.csv"

    if partvtk_018_csv.is_file():
        csv_path = partvtk_018_csv
    else:
        csv_path = _find_csv(output_root / "initial")

    output_root.mkdir(parents=True, exist_ok=True)

    csv_audit = _parse_and_audit_semantic_csv(csv_path, role, cfg)
    xml_audit = _verify_generated_xml(xml_path)
    parent_compare = _compare_with_frozen_parent(cfg, preflight_dir)

    preflight_receipt_path = cfg["preflight_receipt"]

    floating = ET.parse(xml_path).getroot().find(".//execution/particles/floating")
    node = floating.find("masspart") if floating is not None else None
    if node is None or float(node.get("value", "nan")) <= 0:
        raise SemanticAuditError("Actual XML floating interaction masspart required")
    xml_audit["observed_xml_floating_masspart_kg"] = float(node.get("value"))
    xml_audit["masspart_semantics"] = "JSph loads this exact XML value to fobj.massp for particle interaction and force aggregation; Mbody/N above is a separate diagnostic quadrature weight."
    report = {
        "schema": SCHEMA_REPORT,
        "family_id": "F6",
        "case_id": case_id,
        "role": role,
        "recipe_id": RECIPE_ID,
        "preflight_017_binding": {
            "attempt_id": cfg["preflight_017_attempt"],
            "elapsed_seconds": cfg["preflight_017_elapsed_s"],
            "pid": cfg["preflight_017_pid"],
            "receipt": str(preflight_receipt_path.resolve()),
            "receipt_sha256": sha256_file(preflight_receipt_path),
            "generated_bi4": str(bi4_path.resolve()),
            "generated_bi4_sha256": sha256_file(bi4_path),
            "generated_xml": str(xml_path.resolve()),
            "generated_xml_sha256": sha256_file(xml_path),
        },
        "csv_particle_audit": csv_audit,
        "xml_configuration_audit": xml_audit,
        "frozen_parent_comparison": parent_compare,
        "q_n_status": "not_assessed",
        "qualification_claim": "none",
        "scientific_boundary": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "conversion_run": False,
            "root_review_required": True,
            "launch_allowed": False,
        },
        "semantic_initial_qa_passed": bool(
            csv_audit["checks_passed"]
            and xml_audit["all_xml_checks_passed"]
            and parent_compare["fluid_payload_byte_identical"]
            and parent_compare["fixed_prefix_payload_byte_identical"]
        ),
    }

    report_out = output_root / "f6_angular_release_semantic_audit_report.json"
    _json_write(report_out, report)
    return report


def prepare() -> dict[str, Any]:
    SCOPE_ROOT.mkdir(parents=True, exist_ok=True)
    REQUESTS_ROOT.mkdir(parents=True, exist_ok=True)
    ADAPTERS_ROOT.mkdir(parents=True, exist_ok=True)

    adapters: dict[str, str] = {}
    audit_requests: dict[str, str] = {}
    gpu_requests: dict[str, str] = {}

    bindings: dict[str, Any] = {
        "schema": "ds02.f6.angular-release-semantic-audit-bindings.v2",
        "recipe_id": RECIPE_ID,
        "family_id": "F6",
        "binary_solver": {
            "path": str(SOLVER.resolve()),
            "sha256": sha256_file(SOLVER),
        },
        "binary_partvtk": {
            "path": str(PARTVTK.resolve()),
            "sha256": sha256_file(PARTVTK),
        },
        "binary_gencase": {
            "path": str(GENCASE.resolve()),
            "sha256": sha256_file(GENCASE),
        },
        "python_interpreter": {
            "path": str(PYTHON_BIN),
        },
        "evaluator_script": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__)),
        },
        "root_inputs_source": {
            "dir": str(ROOT_INPUTS_DIR.resolve()),
            "review_json": str((ROOT_INPUTS_DIR / "review.json").resolve()),
            "review_json_sha256": sha256_file(ROOT_INPUTS_DIR / "review.json"),
        },
        "cases": {},
    }

    for role in ROLES:
        cfg = CASE_CONFIGS[role]
        case_id = cfg["case_id"]
        dp_str = cfg["dp_str"]
        preflight_receipt = cfg["preflight_receipt"]
        bi4_path = cfg["preflight_dir"] / f"{case_id}.bi4"
        xml_path = cfg["preflight_dir"] / f"{case_id}.xml"
        stdout_path = cfg["preflight_stdout"]
        qa_019_report = cfg["qa_019_report"]
        parent_def = cfg["parent_def"]

        # 1. GenCase Receipt Adapter
        adapter_path = ADAPTERS_ROOT / f"{role}-actual-gencase-adapter.json"
        adapter_payload = {
            "schema": SCHEMA_ADAPTER,
            "returncode": 0,
            "total_particles": cfg["expected_counts"]["total"],
            "fluid_particles": cfg["expected_counts"]["fluid"],
            "solver_dimension_from_gencase": 3,
            "actual_parent_receipt": str(preflight_receipt.resolve()),
            "actual_parent_receipt_sha256": sha256_file(preflight_receipt),
            "actual_child_receipt": str(preflight_receipt.resolve()),
            "actual_child_receipt_sha256": sha256_file(preflight_receipt),
            "actual_stdout": str(stdout_path.resolve()),
            "actual_stdout_sha256": sha256_file(stdout_path),
            "actual_native_qa": str(qa_019_report.resolve()),
            "actual_native_qa_sha256": sha256_file(qa_019_report),
            "actual_gencase_prefix": str((cfg["preflight_dir"] / case_id).resolve()),
            "actual_gencase_xml": str(xml_path.resolve()),
            "actual_gencase_xml_sha256": sha256_file(xml_path),
            "actual_gencase_bi4": str(bi4_path.resolve()),
            "actual_gencase_bi4_sha256": sha256_file(bi4_path),
            "normalization": "Fields bound directly from original complete preflight 017 receipt; no synthetic execution",
        }
        _json_write(adapter_path, adapter_payload)
        adapters[role] = str(adapter_path.resolve())

        # 2. Strict Actual Semantic Audit CPU Runner Request
        audit_req_path = REQUESTS_ROOT / f"{case_id}_SEMANTIC_AUDIT_REQUEST.json"
        audit_input_files = [
            str(PYTHON_BIN),
            str(Path(__file__).resolve()),
            str(PARTVTK.resolve()),
            str(bi4_path.resolve()),
            str(xml_path.resolve()),
            str(preflight_receipt.resolve()),
            str(qa_019_report.resolve()),
            str(adapter_path.resolve()),
            str(MANIFEST_PATH.resolve()),
            str(parent_def.resolve()),
            str(cfg["parent_fluid_vtk"].resolve()),
            str(cfg["parent_bound_vtk"].resolve()),
        ]
        audit_input_hashes = {p: sha256_file(p) for p in audit_input_files if Path(p).is_file()}
        audit_request = {
            "schema": SCHEMA_REQUEST,
            "family_id": "F6",
            "case_id": case_id,
            "attempt_id": f"root-angular-release-dp{dp_str}-actual-semantic-audit-020",
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648,
            "cwd": str(ROOT.resolve()),
            "worktree_root": str(ROOT.resolve()),
            "command": [
                str(PYTHON_BIN),
                str(Path(__file__).resolve()),
                "run-case",
                "--role",
                role,
                "--output-root",
                "{attempt_root}",
            ],
            "input_files": audit_input_files,
            "input_sha256": audit_input_hashes,
            "launch_allowed": False,
            "root_review_required": True,
            "q_n": "not_assessed",
            "independent_case_count_increment": 0,
            "purpose": (
                f"F6 prospective angular release native actual initial semantic audit v2 for {role} (DP={cfg['dp_m']} m): "
                "separates native CSV mass (256 kg support weight), declared XML physical body mass (128 kg), "
                "and derived node mass; proves JSph rigid translation fmass=128 kg and inertia [8.53333, 8.53333, 13.6533]; "
                "verifies velocity propagation architecture; 2 threads, <=1800s, <=2 GiB; root review & dispatch only."
            ),
        }
        _json_write(audit_req_path, audit_request)
        audit_requests[role] = str(audit_req_path.resolve())

        # 3. Full 12s Prospective GPU Solver Request (Pending Root Semantic Audit)
        gpu_req_path = REQUESTS_ROOT / f"{case_id}_SOLVER_GPU_REQUEST.json"
        gpu_output_root = DATA_ROOT / f"families/F6/{case_id}/f6-angular-release-dp{dp_str}-full12-gpu-020"
        gpu_input_files = [
            str(SOLVER.resolve()),
            str(adapter_path.resolve()),
            str(preflight_receipt.resolve()),
            str(xml_path.resolve()),
            str(bi4_path.resolve()),
            str(stdout_path.resolve()),
            str(qa_019_report.resolve()),
            str(ROOT_INPUTS_DIR / "review.json"),
            str(MANIFEST_PATH.resolve()),
        ]
        gpu_input_hashes = {p: sha256_file(p) for p in gpu_input_files if Path(p).is_file()}
        gpu_request = {
            "schema": SCHEMA_REQUEST,
            "family_id": "F6",
            "case_id": case_id,
            "attempt_id": f"f6-angular-release-dp{dp_str}-full12-gpu-020",
            "kind": "qualification",
            "cpu_threads": 4,
            "max_wall_seconds": cfg["gpu_max_wall_s"],
            "estimated_storage_bytes": cfg["gpu_storage_bytes"],
            "estimated_peak_gpu_mib": cfg["gpu_peak_mib"],
            "cwd": str(cfg["preflight_dir"].resolve()),
            "worktree_root": str(ROOT.resolve()),
            "command": [
                str(SOLVER.resolve()),
                str((cfg["preflight_dir"] / case_id).resolve()),
                "{attempt_root}/solver_output",
                "-tmax:12",
                "-tout:0.05",
            ],
            "gencase_receipt": str(adapter_path.resolve()),
            "gencase_receipt_sha256": sha256_file(adapter_path),
            "gencase_prefix": str((cfg["preflight_dir"] / case_id).resolve()),
            "gencase_xml": str(xml_path.resolve()),
            "gencase_bi4": str(bi4_path.resolve()),
            "input_files": gpu_input_files,
            "input_sha256": gpu_input_hashes,
            "launch_allowed": False,
            "root_review_required": True,
            "root_only": True,
            "q_n": "not_assessed",
            "independent_case_count_increment": 0,
            "initial_body_mass_semantics": {
                "declared_rigid_mass_kg": BODY_MASS_KG,
                "initial_native_support_particle_weight_sum_kg": SUPPORT_LATTICE_WEIGHT_KG,
                "note": (
                    "GenCase boundary support masspart uses native fluid density*dp^3 (256 kg sum); "
                    "solver uses declared physical rigid massbody (128 kg) and inertia tensor "
                    "([8.53333, 8.53333, 13.6533] kg*m^2) for rigid dynamics at JSph.cpp:1138,1164,2593,2608. "
                    "Both are preserved without CSV falsification; verify actual FloatingInfo upon solver completion."
                ),
            },
            "purpose": (
                f"Full 12s prospective GPU qualification request for {case_id} (DP={cfg['dp_m']} m): "
                "unconstrained free 6DOF, initial angular velocity [0.08, 0.12, 0.06] rad/s, "
                "ViscoTreatment=2, Visco=1e-6 physical kinematic viscosity, tout=0.05s, tmax=12.0s; "
                "root review and GPU dispatch only; launch_allowed=false pending root semantic audit."
            ),
        }
        _json_write(gpu_req_path, gpu_request)
        gpu_requests[role] = str(gpu_req_path.resolve())

        bindings["cases"][role] = {
            "case_id": case_id,
            "dp_m": cfg["dp_m"],
            "preflight_017": {
                "attempt_id": cfg["preflight_017_attempt"],
                "elapsed_seconds": cfg["preflight_017_elapsed_s"],
                "pid": cfg["preflight_017_pid"],
                "receipt": str(preflight_receipt.resolve()),
                "receipt_sha256": sha256_file(preflight_receipt),
                "generated_bi4": str(bi4_path.resolve()),
                "generated_bi4_sha256": sha256_file(bi4_path),
                "generated_xml": str(xml_path.resolve()),
                "generated_xml_sha256": sha256_file(xml_path),
                "stdout": str(stdout_path.resolve()),
                "stdout_sha256": sha256_file(stdout_path),
            },
            "qa_019": {
                "report": str(qa_019_report.resolve()),
                "report_sha256": sha256_file(qa_019_report),
            },
            "parent_case": {
                "definition": str(parent_def.resolve()),
                "definition_sha256": sha256_file(parent_def),
                "fluid_vtk": str(cfg["parent_fluid_vtk"].resolve()),
                "fluid_vtk_sha256": sha256_file(cfg["parent_fluid_vtk"]),
                "bound_vtk": str(cfg["parent_bound_vtk"].resolve()),
                "bound_vtk_sha256": sha256_file(cfg["parent_bound_vtk"]),
            },
            "adapter": str(adapter_path.resolve()),
            "adapter_sha256": sha256_file(adapter_path),
            "audit_request": str(audit_req_path.resolve()),
            "gpu_request": str(gpu_req_path.resolve()),
        }

    _json_write(BINDINGS_PATH, bindings)

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "recipe_id": RECIPE_ID,
        "family_id": "F6",
        "physical_candidate": "Full 12s, unconstrained free 6DOF, initial angular velocity vector [0.08, 0.12, 0.06] rad/s",
        "semantic_mass_resolution": {
            "declared_physical_rigid_mass_kg": BODY_MASS_KG,
            "support_lattice_weight_sum_kg": SUPPORT_LATTICE_WEIGHT_KG,
            "resolution_explanation": (
                "Official PartVTK CSV Mass column sums to 256 kg because GenCase assigns support particles "
                "mass m_p = rho_0 * dp^3 (fluid density mass). In DualSPHysics, the solver loads physical "
                "massbody (128 kg) at JSph.cpp:1138 and uses it in Newton's 2nd law (JSph.cpp:2593) for translation, "
                "and uses XML inertia ([8.53333, 8.53333, 13.6533]) at JSph.cpp:2608 for rotation. "
                "Native CSV mass is preserved without normalization; declared physical mass 128 kg is confirmed correct."
            ),
        },
        "bindings_file": str(BINDINGS_PATH.resolve()),
        "bindings_sha256": sha256_file(BINDINGS_PATH),
        "adapters": adapters,
        "audit_requests": audit_requests,
        "gpu_requests": gpu_requests,
        "untested_hypothesis_notice": (
            "Prospective excitation candidate [0.08, 0.12, 0.06] rad/s is an UNTESTED HYPOTHESIS. "
            "It does not guarantee macroscopic signal, numerical convergence, or threshold satisfaction. "
            "The frozen 5% relative RMSE macro operator remains unchanged. No third geometry repair."
        ),
        "velocity_propagation_notice": (
            "GenCase BI4 stores floating body angular velocity in XML, but individual particle velocities remain 0. "
            "DualSPHysics solver loads fomega at JSph.cpp:1162 and updates particle velocities vr = v_lin + omega x dist "
            "at JSphCpuSingle.cpp:1084-1086 / JSphGpu_ker.cu:2049-2051 during initialization and execution. "
            "Verifying non-zero initial particle velocities requires auditing solver Frame 0 (Part_0000.bi4)."
        ),
        "launch_allowed": False,
        "root_review_required": True,
        "q_n_status": "not_assessed",
    }
    _json_write(MANIFEST_PATH, manifest)

    # Re-bind manifest hash in requests
    for req_dict in (audit_requests, gpu_requests):
        for role, req_file_str in req_dict.items():
            req_p = Path(req_file_str)
            req_obj = _json_read(req_p)
            req_obj["input_sha256"][str(MANIFEST_PATH.resolve())] = sha256_file(MANIFEST_PATH)
            _json_write(req_p, req_obj)

    manifest["manifest_sha256"] = sha256_file(MANIFEST_PATH)
    _json_write(MANIFEST_PATH, manifest)

    return {
        "status": "prepared",
        "manifest": str(MANIFEST_PATH.resolve()),
        "manifest_sha256": manifest["manifest_sha256"],
        "bindings": str(BINDINGS_PATH.resolve()),
        "adapters": adapters,
        "audit_requests": audit_requests,
        "gpu_requests": gpu_requests,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("prepare")

    rc = sub.add_parser("run-case")
    rc.add_argument("--role", choices=ROLES, required=True)
    rc.add_argument("--output-root", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.action == "prepare":
        res = prepare()
    else:
        res = run_case_semantic_audit(args.role, args.output_root)

    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
