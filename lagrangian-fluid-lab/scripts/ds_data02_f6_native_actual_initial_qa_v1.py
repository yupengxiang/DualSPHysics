"""DS-DATA-02 F6 Prospective Angular Release Native Initial QA Evaluator.

Evaluates official GenCase outputs from preflight 017 across coarse, medium, and fine:
1. Executes official PartVTK_linux64 with:
   -filedata gen.bi4 -filexml gen.xml -savecsv {attempt_root}/initial -vars:+all -onlytype:+all -csvsep:1 -threads:2
2. Checks actual typed particle counts (Fixed, Floating, Fluid) vs exact expected counts.
3. Checks particle UID (Idp) uniqueness and consecutive range [0, Np - 1].
4. Audits rigid body:
   - Mass: 128.0 kg
   - Centroid: [2.4, 1.2, 1.08] m (tolerance <= 3e-6 m)
   - Continuous box bounds: strictly inside [2.0, 0.8, 0.88] .. [2.8, 1.6, 1.28]
   - Discrete inertia tensor: converges to [8.53333, 8.53333, 13.6533] kg*m^2
5. Audits fluid:
   - Fluid native total mass: 5120.0 kg (tolerance <= 0.01 kg)
6. Audits tank wall:
   - 5 finite faces (x_low, x_high, y_low, y_high, z_low) coverage > 0
7. Computes minimum body-fluid Euclidean clearance distance without subsampling (all XYZ pairs via cKDTree).
8. Particle velocity verification & architecture proof:
   - Verifies GenCase PartVTK particle velocities are zero.
   - Cites DualSPHysics initialization architecture:
     * src/source/JSph.cpp:1162 loading fobj->fomega = ToTFloat3(fblock.GetAngularVelini())
     * src/source/JSphCpuSingle.cpp:1084-1086 / src/source/JSphGpu_ker.cu:2049-2051 updating
       vr = v_lin + omega x dist during solver initialization and step.
     * Non-zero initial node velocity verification requires auditing solver Frame 0 (Part_0000.bi4),
       not GenCase alone.
9. Verifies XML configuration:
   - angularvelini: [0.08, 0.12, 0.06] rad/s
   - translationDOF: [1, 1, 1], rotationDOF: [1, 1, 1] (free 6DOF, NOT 1-DOF heave)
   - TimeMax: 12.0 s (full 12s, NOT 3s window)
   - ViscoTreatment: 2 (Laminar+SPS), Visco: 1e-6 (physical kinematic viscosity nu)
10. Compares fluid and fixed boundary VTK payloads with frozen parent cases.
11. Binds preflight 017 source execution receipts:
    - Coarse: 0.472s, Medium: 0.610s, Fine: 1.508s (all returncode 0).
12. Records prospective excitation [0.08, 0.12, 0.06] rad/s as UNTESTED HYPOTHESIS.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import resource
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import numpy as np
from scipy.spatial import cKDTree

# Import read-only helper from existing body cellcenter transform script
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ds_data02_f6_body_cellcenter_transform_v1 import _iter_partvtk, _vtk_points_payload


SCHEMA_MANIFEST = "ds02.f6.angular-release-initial-qa-manifest.v1"
SCHEMA_REPORT = "ds02.f6.angular-release-initial-qa-report.v1"
SCHEMA_REQUEST = "ds02.runner-request.v2"
RECIPE_ID = "F6_ANGULAR_RELEASE_INITIAL_QA_001"

ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
ROOTLAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON_BIN = ROOTLAB / ".venv/bin/python"

OFFICIAL_BIN = ROOTLAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
PARTVTK = OFFICIAL_BIN / "PartVTK_linux64"
GENCASE = OFFICIAL_BIN / "GenCase_linux64"

ROOT_INPUTS_DIR = ROOTLAB / "campaigns/ds-data-02/families/F6/handoff_20261003/root_angular_release_native_inputs_017"
SCOPE_ROOT = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_angular_release_native_initial_qa_001"
REQUESTS_ROOT = SCOPE_ROOT / "requests"
MANIFEST_PATH = SCOPE_ROOT / "manifest.json"
BINDINGS_PATH = SCOPE_ROOT / "bindings.json"

ROLES = ("coarse", "medium", "fine")
TOLERANCE_M = 3e-6

# Frozen physical parameters
BODY_LOW = [2.0, 0.8, 0.88]
BODY_HIGH = [2.8, 1.6, 1.28]
BODY_CENTER = [2.4, 1.2, 1.08]
BODY_MASS_KG = 128.0
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
        "parent_def": ROOTLAB / "campaigns/ds-data-02/families/F6/handoff_20261003/body_cellcenter_transform_001/cases/coarse/F6_BODY_CELLCENTER_TRANSFORM_DP025_Def.xml",
        "parent_fluid_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_TRANSFORM_DP025/F6_BODY_CELLCENTER_TRANSFORM_DP025_NATIVE_INITIAL_004/native/F6_BODY_CELLCENTER_TRANSFORM_DP025_Fluid.vtk",
        "parent_bound_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_TRANSFORM_DP025/F6_BODY_CELLCENTER_TRANSFORM_DP025_NATIVE_INITIAL_004/native/F6_BODY_CELLCENTER_TRANSFORM_DP025_Bound.vtk",
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
        "parent_def": ROOTLAB / "campaigns/ds-data-02/families/F6/handoff_20261003/root_centered_known_wall_initial_009/F6_BODY_CELLCENTER_WALLREPAIRED_DP020_Def.xml",
        "parent_fluid_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_WALLREPAIRED_DP020/root-centered-known-ywall-native-initial-009/native/F6_BODY_CELLCENTER_WALLREPAIRED_DP020_Fluid.vtk",
        "parent_bound_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_WALLREPAIRED_DP020/root-centered-known-ywall-native-initial-009/native/F6_BODY_CELLCENTER_WALLREPAIRED_DP020_Bound.vtk",
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
        "parent_def": ROOTLAB / "campaigns/ds-data-02/families/F6/handoff_20261003/body_cellcenter_transform_001/cases/fine/F6_BODY_CELLCENTER_TRANSFORM_DP0125_Def.xml",
        "parent_fluid_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_TRANSFORM_DP0125/F6_BODY_CELLCENTER_TRANSFORM_DP0125_NATIVE_INITIAL_004/native/F6_BODY_CELLCENTER_TRANSFORM_DP0125_Fluid.vtk",
        "parent_bound_vtk": DATA_ROOT / "families/F6/F6_BODY_CELLCENTER_TRANSFORM_DP0125/F6_BODY_CELLCENTER_TRANSFORM_DP0125_NATIVE_INITIAL_004/native/F6_BODY_CELLCENTER_TRANSFORM_DP0125_Bound.vtk",
    },
}


class InitialQAError(RuntimeError):
    """Raised when initial QA preflight fails."""


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
    raise InitialQAError(f"No CSV output found for stem: {stem}")


def _run_partvtk(
    bi4_path: Path, xml_path: Path, output_root: Path, threads: int = 2
) -> tuple[Path, dict[str, Any]]:
    output_root.mkdir(parents=True, exist_ok=True)
    partvtk_stem = output_root / "initial"
    stdout_log = output_root / "PartVTK.stdout.log"

    command = [
        str(PARTVTK.resolve()),
        "-filedata",
        str(bi4_path.resolve()),
        "-filexml",
        str(xml_path.resolve()),
        "-savecsv",
        str(partvtk_stem.resolve()),
        "-vars:+all",
        "-onlytype:+all",
        "-csvsep:1",
        "-threads:2",
    ]

    started = time.monotonic()
    with stdout_log.open("w", encoding="utf-8") as stream:
        res = subprocess.run(
            command,
            cwd=output_root,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    elapsed = time.monotonic() - started

    csv_path = _find_csv(partvtk_stem)
    receipt = {
        "command": command,
        "returncode": res.returncode,
        "elapsed_seconds": elapsed,
        "stdout": str(stdout_log.resolve()),
        "stdout_sha256": sha256_file(stdout_log),
        "csv": str(csv_path.resolve()),
        "csv_sha256": sha256_file(csv_path),
    }
    if res.returncode != 0:
        raise InitialQAError(f"PartVTK failed with returncode {res.returncode}")
    return csv_path, receipt


def _parse_and_audit_csv(
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
        raise InitialQAError(f"PartVTK CSV header missing needle in {needles}: {headers}")

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

        # Map type
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

    total_body_mass = float(np.sum(body_m_arr)) if len(body_m_arr) > 0 else 0.0
    body_centroid = (
        np.sum(body_arr * body_m_arr[:, None], axis=0) / total_body_mass
        if total_body_mass > 0
        else np.zeros(3)
    )

    # Discrete inertia tensor
    diff = body_arr - body_centroid[None, :]
    Ixx = float(np.sum(body_m_arr * (diff[:, 1] ** 2 + diff[:, 2] ** 2)))
    Iyy = float(np.sum(body_m_arr * (diff[:, 0] ** 2 + diff[:, 2] ** 2)))
    Izz = float(np.sum(body_m_arr * (diff[:, 0] ** 2 + diff[:, 1] ** 2)))
    Ixy = float(-np.sum(body_m_arr * diff[:, 0] * diff[:, 1]))
    Ixz = float(-np.sum(body_m_arr * diff[:, 0] * diff[:, 2]))
    Iyz = float(-np.sum(body_m_arr * diff[:, 1] * diff[:, 2]))

    body_low_actual = [float(np.min(body_arr[:, a])) for a in range(3)] if len(body_arr) > 0 else []
    body_high_actual = [float(np.max(body_arr[:, a])) for a in range(3)] if len(body_arr) > 0 else []

    strictly_inside_box = bool(
        len(body_arr) > 0
        and all(body_low_actual[a] > BODY_LOW[a] - 1e-6 for a in range(3))
        and all(body_high_actual[a] < BODY_HIGH[a] + 1e-6 for a in range(3))
    )

    # Particle initial velocity check (in GenCase output)
    max_body_vel = float(np.max(np.abs(body_v_arr))) if len(body_v_arr) > 0 else 0.0
    body_particles_zero_vel_gencase = max_body_vel < 1e-9

    # Minimum body-fluid clearance distance via cKDTree (no subsampling)
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

    # Verification gates
    centroid_err = [float(body_centroid[a] - BODY_CENTER[a]) for a in range(3)]
    centroid_match = all(abs(e) <= TOLERANCE_M for e in centroid_err)
    mass_match = abs(total_body_mass - BODY_MASS_KG) <= 1e-6
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
        "rigid_body": {
            "particle_count": len(body_points),
            "expected_count": floating_expected,
            "total_mass_kg": total_body_mass,
            "expected_mass_kg": BODY_MASS_KG,
            "mass_match": mass_match,
            "centroid_m": body_centroid.tolist(),
            "expected_centroid_m": BODY_CENTER,
            "centroid_error_m": centroid_err,
            "centroid_match": centroid_match,
            "bounds_actual_low_m": body_low_actual,
            "bounds_actual_high_m": body_high_actual,
            "strictly_inside_continuous_box": strictly_inside_box,
            "discrete_inertia_kg_m2": {
                "Ixx": Ixx,
                "Iyy": Iyy,
                "Izz": Izz,
                "Ixy": Ixy,
                "Ixz": Ixz,
                "Iyz": Iyz,
            },
            "continuous_inertia_kg_m2": BODY_INERTIA,
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
        "velocity_propagation_proof": {
            "gencase_particle_velocity": "0.0 m/s (GenCase stores body omega in XML execution/particles/floating but does not propagate local node velocities in BI4)",
            "solver_initialization_site": "src/source/JSph.cpp:1162 loading fobj->fomega = ToTFloat3(fblock.GetAngularVelini())",
            "solver_kernel_site": "src/source/JSphCpuSingle.cpp:1084-1086 / src/source/JSphGpu_ker.cu:2049-2051 updating vr = v_lin + omega x (pos - fcenter)",
            "verification_requirement": "Verification of non-zero particle node velocities requires auditing solver Frame 0 (Part_0000.bi4), not GenCase alone.",
        },
        "untested_hypothesis_status": {
            "angular_excitation_candidate": "[0.08, 0.12, 0.06] rad/s is an UNTESTED HYPOTHESIS, not guaranteed convergence or cure.",
            "operator_stability": "The frozen 5% macro operator remains unchanged; future solver evaluation is required.",
        },
        "checks_passed": bool(
            counts_match
            and all_uids_unique
            and mass_match
            and centroid_match
            and strictly_inside_box
            and fluid_mass_match
            and wall_5faces_covered
            and (min_clearance_m > 0.0)
            and body_particles_zero_vel_gencase
        ),
    }


def _verify_generated_xml(xml_path: Path) -> dict[str, Any]:
    root = ET.parse(xml_path).getroot()
    fl_part = root.find(".//execution/particles/floating")
    if fl_part is None:
        fl_part = root.find(".//particles/floating")
    if fl_part is None:
        raise InitialQAError(f"Generated XML lacks floating particles block: {xml_path}")

    omega_node = fl_part.find("angularvelini")
    if omega_node is None:
        # Check casedef/floatings/floating
        omega_node = root.find(".//casedef/floatings/floating/angularvelini")
    if omega_node is None:
        raise InitialQAError(f"Generated XML lacks angularvelini: {xml_path}")

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

    # Parameters
    params = {
        p.get("key"): p.get("value")
        for p in root.findall(".//execution/parameters/parameter")
    }
    time_max = float(params.get("TimeMax", "0"))
    visco_treatment = int(params.get("ViscoTreatment", "0"))
    visco = float(params.get("Visco", "0"))

    # DOF check in casedef
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


def run_case_qa(role: str, output_root: Path, skip_partvtk_if_exists: bool = False) -> dict[str, Any]:
    if role not in CASE_CONFIGS:
        raise InitialQAError(f"Unknown role: {role}")
    cfg = CASE_CONFIGS[role]
    case_id = cfg["case_id"]
    preflight_dir = cfg["preflight_dir"]
    bi4_path = preflight_dir / f"{case_id}.bi4"
    xml_path = preflight_dir / f"{case_id}.xml"

    if not bi4_path.is_file():
        raise InitialQAError(f"GenCase preflight BI4 missing: {bi4_path}")
    if not xml_path.is_file():
        raise InitialQAError(f"GenCase preflight XML missing: {xml_path}")

    output_root.mkdir(parents=True, exist_ok=True)
    existing_csv = None
    if skip_partvtk_if_exists:
        try:
            existing_csv = _find_csv(output_root / "initial")
        except InitialQAError:
            existing_csv = None

    if existing_csv and existing_csv.is_file():
        csv_path = existing_csv
        partvtk_receipt = {"reused_existing_csv": str(csv_path.resolve())}
    else:
        csv_path, partvtk_receipt = _run_partvtk(bi4_path, xml_path, output_root, threads=2)

    # Perform CSV audit
    csv_audit = _parse_and_audit_csv(csv_path, role, cfg)

    # Perform XML audit
    xml_audit = _verify_generated_xml(xml_path)

    # Compare with frozen parent
    parent_compare = _compare_with_frozen_parent(cfg, preflight_dir)

    # Read preflight 017 execution receipt
    preflight_receipt_path = cfg["preflight_receipt"]
    preflight_receipt_data = _json_read(preflight_receipt_path) if preflight_receipt_path.is_file() else {}

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
        "partvtk_execution": partvtk_receipt,
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
        "overall_initial_qa_passed": bool(
            csv_audit["checks_passed"]
            and xml_audit["all_xml_checks_passed"]
            and parent_compare["fluid_payload_byte_identical"]
            and parent_compare["fixed_prefix_payload_byte_identical"]
        ),
    }

    report_out = output_root / "f6_angular_release_initial_qa_report.json"
    _json_write(report_out, report)
    return report


def prepare() -> dict[str, Any]:
    SCOPE_ROOT.mkdir(parents=True, exist_ok=True)
    REQUESTS_ROOT.mkdir(parents=True, exist_ok=True)

    bindings: dict[str, Any] = {
        "schema": "ds02.f6.angular-release-initial-qa-bindings.v1",
        "recipe_id": RECIPE_ID,
        "family_id": "F6",
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

    requests: dict[str, str] = {}

    for role in ROLES:
        cfg = CASE_CONFIGS[role]
        case_id = cfg["case_id"]
        dp_str = cfg["dp_str"]
        preflight_receipt = cfg["preflight_receipt"]
        bi4_path = cfg["preflight_dir"] / f"{case_id}.bi4"
        xml_path = cfg["preflight_dir"] / f"{case_id}.xml"
        parent_def = cfg["parent_def"]

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
            },
            "parent_case": {
                "definition": str(parent_def.resolve()),
                "definition_sha256": sha256_file(parent_def),
                "fluid_vtk": str(cfg["parent_fluid_vtk"].resolve()),
                "fluid_vtk_sha256": sha256_file(cfg["parent_fluid_vtk"]),
                "bound_vtk": str(cfg["parent_bound_vtk"].resolve()),
                "bound_vtk_sha256": sha256_file(cfg["parent_bound_vtk"]),
            },
            "expected_counts": cfg["expected_counts"],
        }

        # Request 1: Direct official PartVTK execution request (ready for ROOT dispatch)
        partvtk_req_path = REQUESTS_ROOT / f"{case_id}_PARTVTK.json"
        partvtk_input_files = [
            str(PARTVTK.resolve()),
            str(bi4_path.resolve()),
            str(xml_path.resolve()),
            str(preflight_receipt.resolve()),
        ]
        partvtk_input_hashes = {p: sha256_file(p) for p in partvtk_input_files}
        partvtk_request = {
            "schema": SCHEMA_REQUEST,
            "family_id": "F6",
            "case_id": case_id,
            "attempt_id": f"root-angular-release-dp{dp_str}-actual-partvtk-initial-018",
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": 2147483648,
            "cwd": str(cfg["preflight_dir"].resolve()),
            "worktree_root": str(ROOT.resolve()),
            "command": [
                str(PARTVTK.resolve()),
                "-filedata",
                str(bi4_path.resolve()),
                "-filexml",
                str(xml_path.resolve()),
                "-savecsv",
                "{attempt_root}/initial",
                "-vars:+all",
                "-onlytype:+all",
                "-csvsep:1",
                "-threads:2",
            ],
            "input_files": partvtk_input_files,
            "input_sha256": partvtk_input_hashes,
            "launch_allowed": False,
            "root_review_required": True,
            "q_n": "not_assessed",
            "independent_case_count_increment": 0,
            "purpose": (
                f"Official PartVTK extraction for {case_id} (DP={cfg['dp_m']} m) "
                "from verified preflight 017 BI4/XML; 2 threads, <=2 GiB; root dispatch only."
            ),
        }
        _json_write(partvtk_req_path, partvtk_request)

        # Request 2: Evaluator QA script execution request (ready for ROOT dispatch)
        qa_req_path = REQUESTS_ROOT / f"{case_id}_INITIAL_QA.json"
        qa_input_files = [
            str(PYTHON_BIN),
            str(Path(__file__).resolve()),
            str(PARTVTK.resolve()),
            str(bi4_path.resolve()),
            str(xml_path.resolve()),
            str(preflight_receipt.resolve()),
            str(MANIFEST_PATH.resolve()),
            str(parent_def.resolve()),
            str(cfg["parent_fluid_vtk"].resolve()),
            str(cfg["parent_bound_vtk"].resolve()),
        ]
        qa_input_hashes = {p: sha256_file(p) for p in qa_input_files if Path(p).is_file()}
        qa_request = {
            "schema": SCHEMA_REQUEST,
            "family_id": "F6",
            "case_id": case_id,
            "attempt_id": f"root-angular-release-dp{dp_str}-actual-initial-qa-018",
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
            "input_files": qa_input_files,
            "input_sha256": qa_input_hashes,
            "launch_allowed": False,
            "root_review_required": True,
            "q_n": "not_assessed",
            "independent_case_count_increment": 0,
            "purpose": (
                f"F6 prospective angular release native actual initial QA evaluation for {role} (DP={cfg['dp_m']} m): "
                "PartVTK CSV parse, typed counts, UID uniqueness, mass/inertia/centroid, "
                "cKDTree exact min body-fluid clearance, wall 5 faces, velocity propagation proof; "
                "2 threads, <=1800s, <=2 GiB; root review & dispatch only."
            ),
        }
        _json_write(qa_req_path, qa_request)
        requests[f"{role}_partvtk"] = str(partvtk_req_path.resolve())
        requests[f"{role}_qa"] = str(qa_req_path.resolve())

    _json_write(BINDINGS_PATH, bindings)

    manifest: dict[str, Any] = {
        "schema": SCHEMA_MANIFEST,
        "recipe_id": RECIPE_ID,
        "family_id": "F6",
        "candidate": "Full 12s, unconstrained free 6DOF, initial angular velocity vector [0.08, 0.12, 0.06] rad/s",
        "preflight_017_source": {
            "coarse_dp025": {
                "elapsed_s": CASE_CONFIGS["coarse"]["preflight_017_elapsed_s"],
                "returncode": 0,
                "receipt": str(CASE_CONFIGS["coarse"]["preflight_receipt"].resolve()),
            },
            "medium_dp020": {
                "elapsed_s": CASE_CONFIGS["medium"]["preflight_017_elapsed_s"],
                "returncode": 0,
                "receipt": str(CASE_CONFIGS["medium"]["preflight_receipt"].resolve()),
            },
            "fine_dp0125": {
                "elapsed_s": CASE_CONFIGS["fine"]["preflight_017_elapsed_s"],
                "returncode": 0,
                "receipt": str(CASE_CONFIGS["fine"]["preflight_receipt"].resolve()),
            },
        },
        "bindings_file": str(BINDINGS_PATH.resolve()),
        "bindings_sha256": sha256_file(BINDINGS_PATH),
        "requests": requests,
        "untested_hypothesis_notice": (
            "Prospective excitation candidate [0.08, 0.12, 0.06] rad/s is an UNTESTED HYPOTHESIS. "
            "It does not guarantee macroscopic signal, numerical convergence, or threshold satisfaction. "
            "The frozen 5% relative RMSE macro operator remains unchanged."
        ),
        "velocity_propagation_notice": (
            "GenCase BI4 stores floating body angular velocity in XML, but individual particle velocities remain 0. "
            "DualSPHysics solver loads fomega at JSph.cpp:1162 and updates particle velocities vr = v_lin + omega x dist "
            "at JSphCpuSingle.cpp:1084-1086 / JSphGpu_ker.cu:2049-2051 during initialization and execution. "
            "Verifying non-zero initial particle velocities requires auditing solver Frame 0 (Part_0000.bi4)."
        ),
        "errata_reference": str(
            (
                ROOT
                / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/f6_existing_floating_descriptive_analysis_001/analysis-summary-errata.json"
            ).resolve()
        ),
        "q_n_status": "not_assessed",
        "launch_allowed": False,
        "root_review_required": True,
    }
    _json_write(MANIFEST_PATH, manifest)

    # Recompute hashes for manifests inside requests
    for req_key, req_file_str in requests.items():
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
        "requests": requests,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("prepare")

    rc = sub.add_parser("run-case")
    rc.add_argument("--role", choices=ROLES, required=True)
    rc.add_argument("--output-root", type=Path, required=True)
    rc.add_argument("--skip-partvtk-if-exists", action="store_true")

    args = parser.parse_args(argv)
    if args.action == "prepare":
        res = prepare()
    else:
        res = run_case_qa(args.role, args.output_root, args.skip_partvtk_if_exists)

    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
