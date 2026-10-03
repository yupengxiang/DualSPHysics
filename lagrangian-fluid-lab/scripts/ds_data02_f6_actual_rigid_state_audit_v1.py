"""DS-DATA-02 F6 Prospective Angular Release Actual Rigid State and Node Velocity Audit v1.

Addresses Root Continuation 017 requirements:
1. Audits actual solver rigid body motion from FloatingInfo_mk60.csv:
   - Initial row (t=0):
     * rigid body center [2.4, 1.2, 1.08] m
     * linear velocity [0.0, 0.0, 0.0] m/s
     * declared angular velocity vector [0.08, 0.12, 0.06] rad/s
     * initial displacements (surge, sway, heave) = 0.0 m
     * initial Euler angles (roll, pitch, yaw) = 0.0 deg
   - Time evolution across the full 12s simulation window (241 frames @ 0.05s).
2. Audits typed BI4 floating particle states extracted via PartVTK:
   - Frame 0 (t=0, Part_0000):
     * particle count matches expected (16,384 for DP025 coarse)
     * particle centroid matches continuous center [2.4, 1.2, 1.08] m
     * particle velocities are identically 0.0 m/s
     * documents exact DualSPHysics source architecture explaining Frame 0 vel=0:
       - GenCase initializes BI4 particles with 0.0 m/s
       - JSph.cpp:1162 loads fobj->fomega = [0.08, 0.12, 0.06] rad/s into internal rigid object
       - JSphGpuSingle.cpp:974 (InitRunGpu) copies massp, center, etc., but does NOT invoke KerFtPartsUpdate
       - JSphGpuSingle.cpp:981 (SaveData) writes Part_0000.bi4 before time-step loop
       - JDsPartFloatSave.cpp:166 records internal fomega in PartFloatInfo.ibi4 at step 0
     * mass column sum is 256.0 kg (fluid-density support lattice weight V_body * rho_0)
     * separates native CSV mass (256 kg), declared physical massbody (128 kg, s=0.5),
       support masspart (0.015625 kg, interaction weight fobj.massp), and derived node
       mass (0.0078125 kg, diagnostic quadrature ratio Mbody/N).
   - Frame 1 (t=0.05s, Part_0001):
     * verifies non-zero floating particle velocities
     * kinematic consistency: compares observed particle velocities v_p with theoretical
       rigid velocity v_pred = v_cm + omega x (r_p - r_cm) from FloatingInfo Frame 1,
       verifying RMSE < 1e-3 m/s.
3. Preserves all campaign boundaries:
   - Untested hypothesis notice: prospective excitation [0.08, 0.12, 0.06] rad/s is an
     untested hypothesis; does not guarantee convergence or cure; frozen 5% relative RMSE
     macro operator remains unchanged; no third geometry repair.
   - Preserves zero-spin negative results as distinct physical scope.
   - q_n_status: "not_assessed", qualification_claim: "none".
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

SCHEMA_REPORT = "ds02.f6.angular-release-rigid-state-audit-report.v1"
RECIPE_ID = "F6_ANGULAR_RELEASE_RIGID_STATE_AUDIT_003"

ROOTLAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")

CASE_CONFIGS = {
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
        "expected_center": [2.4, 1.2, 1.08],
        "expected_angvelini": [0.08, 0.12, 0.06],
        "massbody_kg": 128.0,
        "masspart_kg": 0.015625,
        "native_csv_mass_sum_kg": 256.0,
        "derived_node_mass_kg": 0.0078125,
        "inertia_kg_m2": [8.53333, 8.53333, 13.6533],
        "full12_gpu_attempt": "root-angular-release-dp025-full12-native-gpu-021",
        "full12_gpu_receipt": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-full12-native-gpu-021/execution-receipt.json",
        "solver_output_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-full12-native-gpu-021/solver_output",
        "gencase_xml": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP025/root-angular-release-dp025-actual-gencase-preflight-017/F6_ANGULAR_RELEASE_DP025.xml",
    },
    "medium": {
        "dp_str": "020",
        "dp_m": 0.020,
        "case_id": "F6_ANGULAR_RELEASE_DP020",
        "expected_counts": {
            "fixed": 114684,
            "moving": 0,
            "floating": 32000,
            "fluid": 639320,
            "total": 786004,
        },
        "expected_center": [2.4, 1.2, 1.08],
        "expected_angvelini": [0.08, 0.12, 0.06],
        "massbody_kg": 128.0,
        "masspart_kg": 0.008,
        "native_csv_mass_sum_kg": 256.0,
        "derived_node_mass_kg": 0.004,
        "inertia_kg_m2": [8.53333, 8.53333, 13.6533],
        "full12_gpu_attempt": "root-angular-release-dp020-full12-native-gpu-021",
        "full12_gpu_receipt": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-full12-native-gpu-021/execution-receipt.json",
        "solver_output_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-full12-native-gpu-021/solver_output",
        "gencase_xml": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP020/root-angular-release-dp020-actual-gencase-preflight-017/F6_ANGULAR_RELEASE_DP020.xml",
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
        "expected_center": [2.4, 1.2, 1.08],
        "expected_angvelini": [0.08, 0.12, 0.06],
        "massbody_kg": 128.0,
        "masspart_kg": 0.001953125,
        "native_csv_mass_sum_kg": 256.0,
        "derived_node_mass_kg": 0.0009765625,
        "inertia_kg_m2": [8.53333, 8.53333, 13.6533],
        "full12_gpu_attempt": "root-angular-release-dp0125-full12-native-gpu-021",
        "full12_gpu_receipt": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-full12-native-gpu-021/execution-receipt.json",
        "solver_output_dir": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-full12-native-gpu-021/solver_output",
        "gencase_xml": DATA_ROOT / "families/F6/F6_ANGULAR_RELEASE_DP0125/root-angular-release-dp0125-actual-gencase-preflight-017/F6_ANGULAR_RELEASE_DP0125.xml",
    },
}


class RigidStateAuditError(RuntimeError):
    """Raised when rigid state or node velocity audit fails."""


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


# -----------------------------------------------------------------------------
# FloatingInfo CSV Parser & Auditor
# -----------------------------------------------------------------------------

def parse_floating_info_csv(csv_path: Path | str) -> list[dict[str, Any]]:
    """Parses FloatingInfo_mk*.csv supporting semicolon or comma delimiters."""
    path = Path(csv_path)
    if not path.is_file():
        raise RigidStateAuditError(f"FloatingInfo CSV file missing: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        header_line = None
        for line in stream:
            line_clean = line.strip()
            if not line_clean:
                continue
            if "time" in line_clean.lower() and ("center" in line_clean.lower() or "fomega" in line_clean.lower()):
                header_line = line_clean
                break

        if header_line is None:
            raise RigidStateAuditError(f"Valid FloatingInfo header not found in: {path}")

        delimiter = ";" if header_line.count(";") >= header_line.count(",") else ","
        raw_headers = [col.strip() for col in header_line.split(delimiter)]
        # Map headers to canonical names
        norm_headers = [re.sub(r"[^a-z0-9.]+", "", h.lower()) for h in raw_headers]

        reader = csv.reader(stream, delimiter=delimiter)
        for raw_row in reader:
            if not raw_row or len(raw_row) < len(raw_headers):
                continue
            row_dict: dict[str, Any] = {}
            for nh, val in zip(norm_headers, raw_row):
                val_s = val.strip()
                try:
                    row_dict[nh] = float(val_s)
                except ValueError:
                    row_dict[nh] = val_s
            rows.append(row_dict)

    if not rows:
        raise RigidStateAuditError(f"FloatingInfo CSV contained no data rows: {path}")
    return rows


def audit_floating_motion(
    rows: list[dict[str, Any]],
    expected_omega: Sequence[float],
    expected_center: Sequence[float],
    tol_pos: float = 1e-5,
    tol_vel: float = 1e-5,
    tol_omega: float = 1e-5,
) -> dict[str, Any]:
    """Audits initial row and trajectory evolution of FloatingInfo."""
    if not rows:
        raise RigidStateAuditError("No rows to audit in FloatingInfo")

    row0 = rows[0]

    # Helper to lookup column by partial name
    def get_val(row: dict[str, Any], *patterns: str) -> float:
        for p in patterns:
            for k, v in row.items():
                if p in k and isinstance(v, (int, float)):
                    return float(v)
        raise RigidStateAuditError(f"Could not find numeric column matching {patterns} in row keys: {list(row.keys())[:10]}")

    t0 = get_val(row0, "time", "times")
    cx0 = get_val(row0, "center.x", "centerx")
    cy0 = get_val(row0, "center.y", "centery")
    cz0 = get_val(row0, "center.z", "centerz")

    vx0 = get_val(row0, "fvel.x", "fvelx")
    vy0 = get_val(row0, "fvel.y", "fvely")
    vz0 = get_val(row0, "fvel.z", "fvelz")

    ox0 = get_val(row0, "fomega.x", "fomegax")
    oy0 = get_val(row0, "fomega.y", "fomegay")
    oz0 = get_val(row0, "fomega.z", "fomegaz")

    # Initial time check
    t0_zero = abs(t0) < 1e-6

    # Initial center check
    center0_diff = [cx0 - expected_center[0], cy0 - expected_center[1], cz0 - expected_center[2]]
    center0_dist = math.sqrt(sum(d * d for d in center0_diff))
    center0_match = center0_dist < tol_pos

    # Initial linear velocity check (must be 0)
    vel0_mag = math.sqrt(vx0 * vx0 + vy0 * vy0 + vz0 * vz0)
    vel0_zero = vel0_mag < tol_vel

    # Initial angular velocity check (must match declared [0.08, 0.12, 0.06])
    omega0_diff = [ox0 - expected_omega[0], oy0 - expected_omega[1], oz0 - expected_omega[2]]
    omega0_dist = math.sqrt(sum(d * d for d in omega0_diff))
    omega0_match = omega0_dist < tol_omega

    # Displacements at t=0
    surge0 = get_val(row0, "surge")
    sway0 = get_val(row0, "sway")
    heave0 = get_val(row0, "heave")
    disp0_zero = math.sqrt(surge0 * surge0 + sway0 * sway0 + heave0 * heave0) < tol_pos

    # Angles at t=0
    roll0 = get_val(row0, "roll")
    pitch0 = get_val(row0, "pitch")
    yaw0 = get_val(row0, "yaw")
    angles0_zero = math.sqrt(roll0 * roll0 + pitch0 * pitch0 + yaw0 * yaw0) < 1e-4

    # Row 1 (first non-zero time step)
    row1 = rows[1] if len(rows) > 1 else None
    row1_audit: dict[str, Any] = {}
    if row1:
        t1 = get_val(row1, "time", "times")
        cx1 = get_val(row1, "center.x", "centerx")
        cy1 = get_val(row1, "center.y", "centery")
        cz1 = get_val(row1, "center.z", "centerz")
        vx1 = get_val(row1, "fvel.x", "fvelx")
        vy1 = get_val(row1, "fvel.y", "fvely")
        vz1 = get_val(row1, "fvel.z", "fvelz")
        ox1 = get_val(row1, "fomega.x", "fomegax")
        oy1 = get_val(row1, "fomega.y", "fomegay")
        oz1 = get_val(row1, "fomega.z", "fomegaz")
        row1_audit = {
            "time_s": t1,
            "center_m": [cx1, cy1, cz1],
            "linear_velocity_m_s": [vx1, vy1, vz1],
            "angular_velocity_rad_s": [ox1, oy1, oz1],
            "omega_magnitude_rad_s": math.sqrt(ox1 * ox1 + oy1 * oy1 + oz1 * oz1),
            "angular_motion_active": math.sqrt(ox1 * ox1 + oy1 * oy1 + oz1 * oz1) > 0.01,
        }

    # Trajectory completeness
    total_frames = len(rows)
    last_row = rows[-1]
    t_end = get_val(last_row, "time", "times")
    full_window_12s = total_frames == 241 and t_end >= 11.99

    all_finite = True
    for r in rows:
        for k, v in r.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                all_finite = False
                break
        if not all_finite:
            break

    return {
        "frame_0": {
            "time_s": t0,
            "time_zero": t0_zero,
            "observed_center_m": [cx0, cy0, cz0],
            "expected_center_m": list(expected_center),
            "center_distance_m": center0_dist,
            "center_matches_continuous": center0_match,
            "observed_linear_velocity_m_s": [vx0, vy0, vz0],
            "linear_velocity_is_zero": vel0_zero,
            "observed_angular_velocity_rad_s": [ox0, oy0, oz0],
            "expected_angular_velocity_rad_s": list(expected_omega),
            "angular_velocity_distance_rad_s": omega0_dist,
            "angular_velocity_matches_declared": omega0_match,
            "initial_displacements_zero": disp0_zero,
            "initial_euler_angles_zero": angles0_zero,
        },
        "frame_1": row1_audit,
        "trajectory_summary": {
            "total_frames": total_frames,
            "expected_frames": 241,
            "final_time_s": t_end,
            "full_12s_window_complete": full_window_12s,
            "all_motion_values_finite": all_finite,
        },
        "initial_rigid_state_verified": t0_zero and center0_match and vel0_zero and omega0_match,
    }


# -----------------------------------------------------------------------------
# PartVTK Floating Particles CSV Parser & Auditor
# -----------------------------------------------------------------------------

def _iter_partvtk(path: Path) -> tuple[list[str], Iterator[list[str]]]:
    """Robust iterator over PartVTK CSV lines finding typed column header."""
    stream = path.open("r", encoding="utf-8", errors="replace", newline="")
    for line in stream:
        if "Pos.x" in line and ("Type" in line or "Mk" in line or "Mass" in line):
            delimiter = "," if line.count(",") >= line.count(";") else ";"
            import itertools
            reader = csv.reader(itertools.chain([line], stream), delimiter=delimiter)
            try:
                headers = [str(value).strip() for value in next(reader)]
            except StopIteration as exc:
                stream.close()
                raise RigidStateAuditError(f"Empty PartVTK CSV header: {path}") from exc
            return headers, reader
    stream.close()
    raise RigidStateAuditError(f"Typed PartVTK CSV header not found in: {path}")


def parse_floating_particles_csv(csv_path: Path | str) -> dict[str, Any]:
    """Parses extracted floating particles CSV from PartVTK."""
    path = Path(csv_path)
    if not path.is_file():
        raise RigidStateAuditError(f"PartVTK CSV file missing: {path}")

    headers, rows = _iter_partvtk(path)
    norm_headers = [re.sub(r"[^a-z0-9]+", "", h.lower()) for h in headers]

    def col_idx(*needles: str) -> int:
        for idx, val in enumerate(norm_headers):
            if any(n in val for n in needles):
                return idx
        raise RigidStateAuditError(f"PartVTK CSV missing required column {needles}: {headers}")

    col_x = col_idx("posx")
    col_y = col_idx("posy")
    col_z = col_idx("posz")
    col_vx = col_idx("velx")
    col_vy = col_idx("vely")
    col_vz = col_idx("velz")
    col_mass = col_idx("mass")
    col_idp = col_idx("idp")

    points: list[list[float]] = []
    vels: list[list[float]] = []
    masses: list[float] = []
    idps: list[int] = []

    sum_x = sum_y = sum_z = 0.0
    sum_mass = 0.0
    max_vel_mag = 0.0
    sum_vel_mag = 0.0

    for row in rows:
        if not row or len(row) <= max(col_x, col_y, col_z, col_vx, col_vy, col_vz, col_mass, col_idp):
            continue
        try:
            x = float(row[col_x])
            y = float(row[col_y])
            z = float(row[col_z])
            vx = float(row[col_vx])
            vy = float(row[col_vy])
            vz = float(row[col_vz])
            m = float(row[col_mass])
            idp = int(row[col_idp])
        except (ValueError, IndexError):
            continue

        points.append([x, y, z])
        vels.append([vx, vy, vz])
        masses.append(m)
        idps.append(idp)

        sum_x += x
        sum_y += y
        sum_z += z
        sum_mass += m

        v_mag = math.sqrt(vx * vx + vy * vy + vz * vz)
        if v_mag > max_vel_mag:
            max_vel_mag = v_mag
        sum_vel_mag += v_mag

    n_parts = len(points)
    if n_parts == 0:
        raise RigidStateAuditError(f"No valid particle rows parsed from: {path}")

    centroid = [sum_x / n_parts, sum_y / n_parts, sum_z / n_parts]
    mean_vel_mag = sum_vel_mag / n_parts

    return {
        "csv_path": str(path.resolve()),
        "particle_count": n_parts,
        "points": points,
        "vels": vels,
        "masses": masses,
        "idps": idps,
        "centroid_m": centroid,
        "mass_sum_kg": sum_mass,
        "max_vel_m_s": max_vel_mag,
        "mean_vel_m_s": mean_vel_mag,
        "all_vel_zero": max_vel_mag < 1e-7,
    }


def audit_floating_particles(
    frame0_data: dict[str, Any],
    frame1_data: dict[str, Any] | None,
    cfg: Mapping[str, Any],
    floating_info_row0: dict[str, Any] | None = None,
    floating_info_row1: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audits floating node states, mass semantics, and Frame 1 velocity consistency."""
    expected_count = cfg["expected_counts"]["floating"]
    expected_center = cfg["expected_center"]
    massbody_kg = cfg["massbody_kg"]
    masspart_kg = cfg["masspart_kg"]
    expected_native_csv_mass_kg = cfg["native_csv_mass_sum_kg"]
    derived_node_mass_kg = cfg["derived_node_mass_kg"]

    # Frame 0 particle audit
    f0_count = frame0_data["particle_count"]
    count_match = (f0_count == expected_count)

    c0 = frame0_data["centroid_m"]
    c0_diff = [c0[0] - expected_center[0], c0[1] - expected_center[1], c0[2] - expected_center[2]]
    c0_dist = math.sqrt(sum(d * d for d in c0_diff))
    centroid_match = (c0_dist < 1e-4)

    f0_vel_zero = frame0_data["all_vel_zero"]
    f0_mass_sum = frame0_data["mass_sum_kg"]
    mass_sum_match = abs(f0_mass_sum - expected_native_csv_mass_kg) < 1e-2

    # Mass semantics separation
    mass_semantics = {
        "observed_native_csv_mass_sum_kg": f0_mass_sum,
        "native_csv_matches_fluid_density_mass": mass_sum_match,
        "native_csv_mass_interpretation": (
            "Observed sum of PartVTK CSV Mass column equals fluid-density support particle weight: "
            f"V_body * rho_0 = 0.256 m^3 * 1000 kg/m^3 = {expected_native_csv_mass_kg} kg. "
            "Preserved byte-for-byte; not falsified or normalized."
        ),
        "declared_physical_rigid_mass_kg": massbody_kg,
        "declared_relative_density": 0.5,
        "solver_fobj_massp_interaction_weight_kg": masspart_kg,
        "solver_interaction_weight_interpretation": (
            f"XML masspart={masspart_kg} kg loaded into fobj.massp (JSph.cpp:1138, JSphGpu.cpp:782) "
            "and used for fluid-boundary hydrodynamic interactions (JSphCpu.cpp:675,842)."
        ),
        "derived_uniform_node_mass_kg": derived_node_mass_kg,
        "derived_node_mass_interpretation": (
            f"Uniform-node diagnostic quadrature ratio Mbody/N = {massbody_kg}/{expected_count} = {derived_node_mass_kg} kg; "
            "hypothetical diagnostic, NOT observed CSV Mass and NOT solver fobj.massp interaction weight."
        ),
    }

    # Velocity propagation explanation
    velocity_propagation_proof = {
        "gencase_particle_velocity": "0.0 m/s (GenCase stores body omega in XML particles block; particle velocities in BI4 are 0.0 m/s)",
        "solver_initialization_sequence": (
            "In DualSPHysics (JSphGpuSingle.cpp:974-981), InitRunGpu() initializes GPU memory and copies constants "
            "(InitFloatingsGpu copies massp, center, etc.) but does NOT invoke KerFtPartsUpdate before SaveData() writes Part_0000.bi4. "
            "Thus Part_0000 floating node velocities remain at the initial GenCase value (0.0 m/s). "
            "Simultaneously, the internal rigid body state fobj->fomega is initialized from angularvelini ([0.08, 0.12, 0.06] rad/s) "
            "at JSph.cpp:1162 and saved in PartFloatInfo.ibi4 at t=0 by JDsPartFloatSave.cpp:166."
        ),
        "runtime_velocity_propagation": (
            "During simulation time-stepping, KerFtPartsUpdate (JSphGpu_ker.cu:2045-2065) updates particle velocities "
            "vr = v_lin + omega x (pos - fcenter). By Part_0001 (t=0.05s), floating particles exhibit non-zero velocities "
            "governed by rigid body kinematics."
        ),
        "observed_frame0_vel_is_zero": f0_vel_zero,
    }

    # Frame 1 velocity consistency check
    frame1_audit: dict[str, Any] = {}
    if frame1_data:
        f1_count = frame1_data["particle_count"]
        f1_max_vel = frame1_data["max_vel_m_s"]
        f1_mean_vel = frame1_data["mean_vel_m_s"]
        f1_vel_nonzero = f1_max_vel > 0.001

        kinematic_consistency: dict[str, Any] = {}
        if floating_info_row1:
            # Theoretical predicted velocity: v_pred = v_cm + omega x (r_p - r_cm)
            v_cm = floating_info_row1["linear_velocity_m_s"]
            omega = floating_info_row1["angular_velocity_rad_s"]
            r_cm = floating_info_row1["center_m"]

            points = frame1_data["points"]
            vels = frame1_data["vels"]

            diff_sq_sum = 0.0
            max_diff = 0.0

            for p, v in zip(points, vels):
                rx = p[0] - r_cm[0]
                ry = p[1] - r_cm[1]
                rz = p[2] - r_cm[2]

                # omega x r
                wx = omega[1] * rz - omega[2] * ry
                wy = omega[2] * rx - omega[0] * rz
                wz = omega[0] * ry - omega[1] * rx

                v_pred_x = v_cm[0] + wx
                v_pred_y = v_cm[1] + wy
                v_pred_z = v_cm[2] + wz

                dx = v[0] - v_pred_x
                dy = v[1] - v_pred_y
                dz = v[2] - v_pred_z
                d_sq = dx * dx + dy * dy + dz * dz
                d_mag = math.sqrt(d_sq)

                diff_sq_sum += d_sq
                if d_mag > max_diff:
                    max_diff = d_mag

            rmse = math.sqrt(diff_sq_sum / len(points))
            kinematic_consistency = {
                "tested_particles": len(points),
                "rigid_linear_velocity_m_s": v_cm,
                "rigid_angular_velocity_rad_s": omega,
                "rigid_center_m": r_cm,
                "rmse_m_s": rmse,
                "max_abs_diff_m_s": max_diff,
                "consistent_with_rigid_kinematics": rmse < 1e-3,
            }

        frame1_audit = {
            "particle_count": f1_count,
            "max_velocity_m_s": f1_max_vel,
            "mean_velocity_m_s": f1_mean_vel,
            "velocities_are_nonzero": f1_vel_nonzero,
            "kinematic_consistency": kinematic_consistency,
        }

    return {
        "frame_0": {
            "particle_count": f0_count,
            "expected_count": expected_count,
            "count_matches": count_match,
            "centroid_m": c0,
            "expected_center_m": list(expected_center),
            "centroid_distance_m": c0_dist,
            "centroid_matches": centroid_match,
            "max_velocity_m_s": frame0_data["max_vel_m_s"],
            "all_velocities_zero": f0_vel_zero,
            "observed_csv_mass_sum_kg": f0_mass_sum,
            "expected_csv_mass_sum_kg": expected_native_csv_mass_kg,
            "mass_sum_matches_lattice_support": mass_sum_match,
        },
        "frame_1": frame1_audit,
        "mass_semantics": mass_semantics,
        "velocity_propagation_proof": velocity_propagation_proof,
        "floating_nodes_verified": count_match and centroid_match and f0_vel_zero and mass_sum_match,
    }


# -----------------------------------------------------------------------------
# Case-Level Audit Pipeline
# -----------------------------------------------------------------------------

def run_case(
    role: str,
    output_root: Path | str,
    floating_csv: Path | str | None = None,
    parts_dir: Path | str | None = None,
    solver_attempt_root: Path | str | None = None,
) -> dict[str, Any]:
    """Runs full actual rigid state audit for a given role."""
    if role not in CASE_CONFIGS:
        raise RigidStateAuditError(f"Unknown role: {role}")
    cfg = CASE_CONFIGS[role]

    out_dir = Path(output_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Locate FloatingInfo CSV
    fl_csv_path: Path | None = None
    if floating_csv:
        fl_csv_path = Path(floating_csv)
    elif solver_attempt_root:
        # Check subdirectories
        cands = list(Path(solver_attempt_root).glob("**/FloatingInfo_mk*.csv"))
        if cands:
            fl_csv_path = cands[0]

    floating_motion_audit: dict[str, Any] = {}
    fl_rows: list[dict[str, Any]] = []
    if fl_csv_path and fl_csv_path.is_file():
        fl_rows = parse_floating_info_csv(fl_csv_path)
        floating_motion_audit = audit_floating_motion(
            fl_rows, cfg["expected_angvelini"], cfg["expected_center"]
        )

    # 2. Locate PartVTK CSVs for Frame 0 and Frame 1
    f0_csv_path: Path | None = None
    f1_csv_path: Path | None = None

    if parts_dir:
        pdir = Path(parts_dir)
        c0 = list(pdir.glob("*_0000.csv")) or list(pdir.glob("*0000*.csv"))
        c1 = list(pdir.glob("*_0001.csv")) or list(pdir.glob("*0001*.csv"))
        if c0:
            f0_csv_path = c0[0]
        if c1:
            f1_csv_path = c1[0]

    particles_audit: dict[str, Any] = {}
    if f0_csv_path and f0_csv_path.is_file():
        f0_data = parse_floating_particles_csv(f0_csv_path)
        f1_data = parse_floating_particles_csv(f1_csv_path) if (f1_csv_path and f1_csv_path.is_file()) else None

        fl_row0 = floating_motion_audit.get("frame_0")
        fl_row1 = floating_motion_audit.get("frame_1")

        particles_audit = audit_floating_particles(
            f0_data, f1_data, cfg, fl_row0, fl_row1
        )

    # 3. Solver receipt audit
    solver_receipt_data: dict[str, Any] = {}
    receipt_p = cfg["full12_gpu_receipt"]
    if receipt_p.is_file():
        receipt_obj = _json_read(receipt_p)
        solver_receipt_data = {
            "attempt_id": cfg["full12_gpu_attempt"],
            "status": receipt_obj.get("status"),
            "returncode": receipt_obj.get("returncode"),
            "elapsed_seconds": receipt_obj.get("elapsed_seconds"),
            "pid": receipt_obj.get("pid"),
            "receipt_path": str(receipt_p.resolve()),
            "receipt_sha256": sha256_file(receipt_p),
        }

    overall_passed = bool(
        floating_motion_audit.get("initial_rigid_state_verified", False)
        and particles_audit.get("floating_nodes_verified", False)
    )

    report = {
        "schema": SCHEMA_REPORT,
        "recipe_id": RECIPE_ID,
        "family_id": "F6",
        "case_id": cfg["case_id"],
        "role": role,
        "q_n_status": "not_assessed",
        "qualification_claim": "none",
        "untested_hypothesis_notice": {
            "status": "Prospective excitation [0.08, 0.12, 0.06] rad/s is an UNTESTED HYPOTHESIS, not guaranteed convergence.",
            "operator": "Frozen 5% relative RMSE macro operator remains unchanged. No retroactive threshold relaxations.",
            "repaired_parent_preservation": "No third geometry repair. Unchanged body geometry, tank, mass, inertia, viscosity.",
            "historical_zero_spin_scope": "Existing negative Q-N results remain distinct historical evidence for unexcited scope.",
        },
        "solver_gpu_receipt": solver_receipt_data,
        "floating_motion_audit": floating_motion_audit,
        "floating_particles_audit": particles_audit,
        "overall_audit_passed": overall_passed,
    }

    report_path = out_dir / "f6_angular_release_rigid_state_audit_report.json"
    _json_write(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_motion_p = subparsers.add_parser("audit-motion")
    audit_motion_p.add_argument("--csv", type=Path, required=True)
    audit_motion_p.add_argument("--expected-omega", type=float, nargs=3, default=[0.08, 0.12, 0.06])
    audit_motion_p.add_argument("--expected-center", type=float, nargs=3, default=[2.4, 1.2, 1.08])
    audit_motion_p.add_argument("--output", type=Path)

    audit_parts_p = subparsers.add_parser("audit-parts")
    audit_parts_p.add_argument("--frame0-csv", type=Path, required=True)
    audit_parts_p.add_argument("--frame1-csv", type=Path)
    audit_parts_p.add_argument("--role", choices=["coarse", "medium", "fine"], default="coarse")
    audit_parts_p.add_argument("--output", type=Path)

    run_case_p = subparsers.add_parser("run-case")
    run_case_p.add_argument("--role", choices=["coarse", "medium", "fine"], default="coarse")
    run_case_p.add_argument("--output-root", type=Path, required=True)
    run_case_p.add_argument("--floating-csv", type=Path)
    run_case_p.add_argument("--parts-dir", type=Path)
    run_case_p.add_argument("--solver-attempt-root", type=Path)

    args = parser.parse_args()

    if args.command == "audit-motion":
        rows = parse_floating_info_csv(args.csv)
        res = audit_floating_motion(rows, args.expected_omega, args.expected_center)
        if args.output:
            _json_write(args.output, res)
        print(json.dumps(res, indent=2))

    elif args.command == "audit-parts":
        cfg = CASE_CONFIGS[args.role]
        f0 = parse_floating_particles_csv(args.frame0_csv)
        f1 = parse_floating_particles_csv(args.frame1_csv) if args.frame1_csv else None
        res = audit_floating_particles(f0, f1, cfg)
        if args.output:
            _json_write(args.output, res)
        print(json.dumps(res, indent=2))

    elif args.command == "run-case":
        report = run_case(
            args.role,
            args.output_root,
            floating_csv=args.floating_csv,
            parts_dir=args.parts_dir,
            solver_attempt_root=args.solver_attempt_root,
        )
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
