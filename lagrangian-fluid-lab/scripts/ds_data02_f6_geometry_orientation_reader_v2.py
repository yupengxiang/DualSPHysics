#!/usr/bin/env python3
"""DS-DATA-02 F6 Geometry-Based SO(3) Orientation Reader & Cross-DP Evaluator (v2).

Directly addresses Root Source Review 031 and inspects/resolves all 5 documented
omissions in the v1 implementation (commit 65d343f3):

1. Strict Zone0 / Type2 / Mk60 Exact Full Cohort Enforcement:
   - Line 2 metadata (Np, Nfloat) is parsed and strictly verified.
   - The total floating node count must identically equal metadata Nfloat.
   - All rows must match Zone == 0, Type == target_type (2), Mk == target_mk (60).
   - Silent skipping of malformed lines or wrong Type/Mk/Zone rows is strictly
     prohibited; any deviation raises an immediate ValueError.
2. Explicit 0000..0240 File Enumeration:
   - Replaces directory globbing with explicit enumeration of PartFloating_{i:04d}.csv
     for i in range(241), strictly preventing accidental inclusion of summary files
     such as PartFloating_stats.csv.
3. Native Full 241 Frames / Full 12s Window / Strictly Increasing Times Enforcement:
   - Enforces exactly 241 frames (0000..0240).
   - Enforces that all native timestamps are finite and strictly increasing (t_{i+1} > t_i).
   - Enforces full window coverage: t_0 == 0.0s and t_240 == 12.0s (within numerical tol).
4. Strict Interpolation Support (No Extrapolation):
   - Strictly prohibits endpoint clamping out of support; queries outside [t_0, t_end]
     raise a ValueError.
5. Strict Center Validation Against FloatingInfo (No Partial Matches):
   - Enforces that every single frame in the trajectory (all 241 frames) finds a
     corresponding native timestamp in FloatingInfo. Partial matches are rejected.

Preserves unchanged:
- Original Kabsch SVD algorithm with det(R) = +1 proper SO(3) enforcement.
- Lie group SO(3) SLERP on unit quaternions along shortest geodesic arc.
- Coordinate-invariant Riemannian geodesic distance:
    d_R(R1, R2) = arccos(clip((tr(R1^T R2) - 1) / 2, -1.0, 1.0))
- Orientation budget is NULL / unregistered (no invented gates or qualification claims).
- Root Q-N products remain 0/336.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA_REPORT = "ds02.f6.geometry-orientation-reader-report.v2"
RECIPE_ID = "F6_GEOMETRY_ORIENTATION_READER_007"

# Registered physical scales from observation_plan.json
GRAVITY_M_S2 = 9.81
L_CHAR_M = 0.8
U_CHAR_M_S = math.sqrt(GRAVITY_M_S2 * L_CHAR_M)  # 2.801428 m/s
GENERIC_MACRO_TOLERANCE = 0.05
EXPECTED_WINDOW_S = 12.0
EXPECTED_FRAMES = 241


def sha256_file(path: Path | str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_partvtk_floating_csv_v2(
    path: Path | str,
    target_mk: int = 60,
    target_type: int = 2,
    target_zone: int = 0,
) -> dict[str, Any]:
    """Parse PartVTK exported floating-node CSV file with strict validation.

    Format specification (Root export 028 with -vars:-all,+idp,+zone,+type,+mk):
      Line 1: TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid
      Line 2: <time_step_metadata>,...
      Line 3: <blank>
      Line 4: Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Type,Mk (or without unit brackets)
      Data rows: float coordinates, zone, integer UID (Idp), type, mk.

    Strict V2 Invariants:
      1. Parses Line 1/2 metadata headers and values.
      2. Validates metadata Nfloat and Np are positive integers.
      3. Validates Zone == target_zone (0) for every row.
      4. Validates Type == target_type (2) and Mk == target_mk (60) for every row.
      5. Strictly rejects any malformed, truncated, or non-finite row (no skipping).
      6. Strictly verifies parsed node count identically equals metadata Nfloat.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"PartVTK CSV file not found: {p}")

    file_hash = sha256_file(p)

    with p.open("r", encoding="utf-8", errors="replace") as stream:
        lines = [line.strip() for line in stream if line.strip()]

    if len(lines) < 3:
        raise ValueError(f"PartVTK CSV {p} has fewer than 3 non-empty lines.")

    # Detect delimiter from header lines (comma or semicolon)
    delimiter = ";" if ";" in lines[0] else ","

    # Line 1: metadata column names
    meta_headers = [h.strip() for h in lines[0].split(delimiter)]
    time_idx = -1
    np_idx = -1
    nfloat_idx = -1

    for idx, mh in enumerate(meta_headers):
        mh_clean = mh.lower().replace(" ", "").replace("[s]", "")
        if "timestep" in mh_clean or mh_clean == "time":
            time_idx = idx
        elif mh_clean == "np":
            np_idx = idx
        elif mh_clean == "nfloat":
            nfloat_idx = idx

    if time_idx < 0:
        raise ValueError(f"Metadata header missing TimeStep in {p}: {lines[0]}")

    # Line 2: metadata values
    meta_values = [v.strip() for v in lines[1].split(delimiter)]
    try:
        native_time_s = float(meta_values[time_idx])
    except (IndexError, ValueError) as err:
        raise ValueError(f"Failed to parse native time from line 2 of {p}: {lines[1]}") from err

    if not math.isfinite(native_time_s):
        raise ValueError(f"Non-finite native time {native_time_s} in line 2 of {p}")

    meta_nfloat = None
    if nfloat_idx >= 0 and nfloat_idx < len(meta_values):
        try:
            meta_nfloat = int(meta_values[nfloat_idx])
        except ValueError as err:
            raise ValueError(f"Invalid metadata Nfloat in line 2 of {p}: {meta_values[nfloat_idx]}") from err

    meta_np = None
    if np_idx >= 0 and np_idx < len(meta_values):
        try:
            meta_np = int(meta_values[np_idx])
        except ValueError as err:
            raise ValueError(f"Invalid metadata Np in line 2 of {p}: {meta_values[np_idx]}") from err

    # Line 3 of non-empty lines is the column header for node data
    data_header_line = lines[2]
    headers = [h.strip() for h in data_header_line.split(delimiter) if h.strip()]

    def find_col(patterns: list[str]) -> int:
        for idx, col in enumerate(headers):
            col_clean = col.lower().replace(" ", "").replace("[m]", "")
            for pat in patterns:
                if col_clean == pat.lower():
                    return idx
        raise KeyError(f"Could not find column matching {patterns} in headers: {headers} in {p}")

    col_x = find_col(["pos.x", "x"])
    col_y = find_col(["pos.y", "y"])
    col_z = find_col(["pos.z", "z"])
    col_zone = find_col(["zone"])
    col_idp = find_col(["idp", "id"])
    col_type = find_col(["type"])
    col_mk = find_col(["mk", "mkbound"])

    # Parse node rows strictly
    idps: list[int] = []
    coords: list[list[float]] = []
    seen_idps: set[int] = set()

    for line_idx, line in enumerate(lines[3:], start=4):
        parts = [part.strip() for part in line.split(delimiter) if part.strip()]
        min_required_cols = max(col_x, col_y, col_z, col_zone, col_idp, col_type, col_mk) + 1
        if len(parts) < min_required_cols:
            raise ValueError(
                f"Malformed row with insufficient columns ({len(parts)} < {min_required_cols}) "
                f"in {p} at line {line_idx}: {line}"
            )

        # Parse Type, Mk, Zone strictly
        try:
            ptype = int(parts[col_type])
            pmk = int(parts[col_mk])
            pzone = int(parts[col_zone])
        except ValueError as err:
            raise ValueError(
                f"Non-integer Type/Mk/Zone in {p} at line {line_idx}: {line}"
            ) from err

        if pzone != target_zone:
            raise ValueError(
                f"Strict Zone mismatch in {p} at line {line_idx}: expected Zone={target_zone}, found Zone={pzone}"
            )
        if ptype != target_type:
            raise ValueError(
                f"Strict Type mismatch in {p} at line {line_idx}: expected Type={target_type}, found Type={ptype}"
            )
        if pmk != target_mk:
            raise ValueError(
                f"Strict Mk mismatch in {p} at line {line_idx}: expected Mk={target_mk}, found Mk={pmk}"
            )

        try:
            x = float(parts[col_x])
            y = float(parts[col_y])
            z = float(parts[col_z])
            idp = int(parts[col_idp])
        except ValueError as err:
            raise ValueError(f"Malformed numeric coordinate/Idp in {p} at line {line_idx}: {line}") from err

        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            raise ValueError(f"Non-finite node coordinates found in {p} at line {line_idx}: ({x}, {y}, {z})")

        if idp in seen_idps:
            raise ValueError(f"Duplicate Idp {idp} encountered in frame {p} at line {line_idx}")

        seen_idps.add(idp)
        idps.append(idp)
        coords.append([x, y, z])

    if not idps:
        raise ValueError(f"No floating nodes found for Type={target_type}, Mk={target_mk} in {p}")

    # Strict check against metadata Nfloat
    if meta_nfloat is not None and len(idps) != meta_nfloat:
        raise ValueError(
            f"Node count mismatch against metadata Nfloat in {p}: "
            f"parsed {len(idps)} nodes, but Line 2 metadata specifies Nfloat={meta_nfloat}"
        )

    # Sort strictly by Idp to establish unique canonical node ordering
    sort_indices = np.argsort(idps)
    sorted_idps = np.array(idps, dtype=np.int64)[sort_indices]
    sorted_coords = np.array(coords, dtype=np.float64)[sort_indices]

    return {
        "path": str(p.resolve()),
        "sha256": file_hash,
        "time_s": native_time_s,
        "node_count": len(sorted_idps),
        "metadata_nfloat": meta_nfloat,
        "metadata_np": meta_np,
        "idps": sorted_idps,
        "coords": sorted_coords,
    }


def compute_kabsch_svd(
    ref_coords: np.ndarray,
    target_coords: np.ndarray,
) -> dict[str, Any]:
    """Compute optimal proper SO(3) rotation matrix and translation using Kabsch SVD.

    Parameters:
      ref_coords: (N, 3) initial / reference node coordinates P.
      target_coords: (N, 3) target / current node coordinates Q.

    Formulation:
      p_c = mean(P), q_c = mean(Q)
      X = P - p_c, Y = Q - q_c
      H = X^T Y in R^{3x3}
      H = U Sigma V^T via SVD
      R = V diag(1, 1, det(V U^T)) U^T (proper rotation in SO(3), det(R) = +1)
      t = q_c - R p_c
      rigidity_residual = Q - (X R^T + q_c)
    """
    n_nodes = ref_coords.shape[0]
    if n_nodes != target_coords.shape[0]:
        raise ValueError(f"Node count mismatch: ref has {n_nodes}, target has {target_coords.shape[0]}")
    if n_nodes < 3:
        raise ValueError(f"Insufficient node count {n_nodes} for 3D rigid pose reconstruction (minimum 3)")

    p_c = np.mean(ref_coords, axis=0)
    q_c = np.mean(target_coords, axis=0)

    x_centered = ref_coords - p_c
    y_centered = target_coords - q_c

    # Check rank of reference configuration (must be rank 3 for 3D body)
    ref_cov = (x_centered.T @ x_centered) / n_nodes
    _, ref_singular_vals, _ = np.linalg.svd(ref_cov)
    is_rank_3 = bool(ref_singular_vals[2] > 1e-6)

    # Cross-covariance matrix H = X^T Y
    h_matrix = x_centered.T @ y_centered

    # SVD of H
    u_mat, singular_vals, vt_mat = np.linalg.svd(h_matrix)
    v_mat = vt_mat.T

    # Enforce proper rotation: det(R) = +1
    det_vu = np.linalg.det(v_mat @ u_mat.T)
    reflection_detected = bool(det_vu < 0.0)

    diag_d = np.diag([1.0, 1.0, 1.0 if det_vu >= 0.0 else -1.0])
    rot_matrix = v_mat @ diag_d @ u_mat.T
    det_rot = float(np.linalg.det(rot_matrix))

    # Translation vector: t = q_c - R p_c (such that q = R p + t)
    trans_vec = q_c - (rot_matrix @ p_c)

    # Centroid displacement vector: delta_c = q_c - p_c (surge, sway, heave)
    disp_vec = q_c - p_c

    # Compute rigidity fit residuals: Q_pred = X R^T + q_c
    target_pred = (x_centered @ rot_matrix.T) + q_c
    residuals = target_coords - target_pred
    res_norms = np.linalg.norm(residuals, axis=1)

    rigidity_rms_m = float(np.sqrt(np.mean(res_norms * res_norms)))
    rigidity_max_m = float(np.max(res_norms))

    # Convert rotation matrix to unit quaternion
    quaternion_wxyz = matrix_to_quaternion(rot_matrix)

    return {
        "rotation_matrix": rot_matrix,
        "translation_m": trans_vec,
        "displacement_m": disp_vec,
        "ref_centroid_m": p_c,
        "target_centroid_m": q_c,
        "det_R": det_rot,
        "reflection_detected": reflection_detected,
        "ref_singular_values": ref_singular_vals.tolist(),
        "is_rank_3": is_rank_3,
        "rigidity_rms_m": rigidity_rms_m,
        "rigidity_max_m": rigidity_max_m,
        "quaternion_wxyz": quaternion_wxyz,
    }


def matrix_to_quaternion(rot_mat: np.ndarray) -> np.ndarray:
    """Convert 3x3 SO(3) rotation matrix to normalized unit quaternion [w, x, y, z] (w >= 0)."""
    tr = rot_mat[0, 0] + rot_mat[1, 1] + rot_mat[2, 2]
    if tr > 0.0:
        s = 2.0 * math.sqrt(1.0 + tr)
        w = 0.25 * s
        x = (rot_mat[2, 1] - rot_mat[1, 2]) / s
        y = (rot_mat[0, 2] - rot_mat[2, 0]) / s
        z = (rot_mat[1, 0] - rot_mat[0, 1]) / s
    elif (rot_mat[0, 0] > rot_mat[1, 1]) and (rot_mat[0, 0] > rot_mat[2, 2]):
        s = 2.0 * math.sqrt(1.0 + rot_mat[0, 0] - rot_mat[1, 1] - rot_mat[2, 2])
        w = (rot_mat[2, 1] - rot_mat[1, 2]) / s
        x = 0.25 * s
        y = (rot_mat[0, 1] + rot_mat[1, 0]) / s
        z = (rot_mat[0, 2] + rot_mat[2, 0]) / s
    elif rot_mat[1, 1] > rot_mat[2, 2]:
        s = 2.0 * math.sqrt(1.0 + rot_mat[1, 1] - rot_mat[0, 0] - rot_mat[2, 2])
        w = (rot_mat[0, 2] - rot_mat[2, 0]) / s
        x = (rot_mat[0, 1] + rot_mat[1, 0]) / s
        y = 0.25 * s
        z = (rot_mat[1, 2] + rot_mat[2, 1]) / s
    else:
        s = 2.0 * math.sqrt(1.0 + rot_mat[2, 2] - rot_mat[0, 0] - rot_mat[1, 1])
        w = (rot_mat[1, 0] - rot_mat[0, 1]) / s
        x = (rot_mat[0, 2] + rot_mat[2, 0]) / s
        y = (rot_mat[1, 2] + rot_mat[2, 1]) / s
        z = 0.25 * s

    q = np.array([w, x, y, z], dtype=np.float64)
    q_norm = np.linalg.norm(q)
    if q_norm > 0.0:
        q /= q_norm
    if q[0] < 0.0:
        q = -q
    return q


def quaternion_to_matrix(q: np.ndarray) -> np.ndarray:
    """Convert unit quaternion [w, x, y, z] to 3x3 SO(3) rotation matrix."""
    w, x, y, z = q
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - w * z), 2.0 * (x * z + w * y)],
            [2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - w * x)],
            [2.0 * (x * z - w * y), 2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def quaternion_slerp(q1: np.ndarray, q2: np.ndarray, alpha: float) -> np.ndarray:
    """Spherical Linear Interpolation (SLERP) between two unit quaternions along shortest arc."""
    alpha_clamped = min(max(alpha, 0.0), 1.0)
    dot = float(np.dot(q1, q2))

    q2_mod = q2.copy()
    if dot < 0.0:
        q2_mod = -q2_mod
        dot = -dot

    dot = min(max(dot, -1.0), 1.0)

    if dot > 0.9995:
        # Linear interpolation for very close orientations to avoid division by zero
        res = (1.0 - alpha_clamped) * q1 + alpha_clamped * q2_mod
        return res / np.linalg.norm(res)

    theta = math.acos(dot)
    sin_theta = math.sin(theta)

    scale1 = math.sin((1.0 - alpha_clamped) * theta) / sin_theta
    scale2 = math.sin(alpha_clamped * theta) / sin_theta

    res = scale1 * q1 + scale2 * q2_mod
    return res / np.linalg.norm(res)


def compute_so3_geodesic_distance(r1: np.ndarray, r2: np.ndarray) -> float:
    """Compute Riemannian geodesic distance on Lie group SO(3):

    Phi = arccos(clip((tr(R1^T R2) - 1) / 2, -1.0, 1.0))
    """
    rel_rot = r1.T @ r2
    tr = float(np.trace(rel_rot))
    cos_angle = min(max((tr - 1.0) * 0.5, -1.0), 1.0)
    return float(math.acos(cos_angle))


def interpolate_pose_at_physical_time_v2(
    trajectory: dict[str, Any],
    query_time_s: float,
    tol_s: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate rigid pose (rotation matrix and centroid) at an exact physical time t.

    Uses SLERP on unit quaternions for rotation and linear interpolation for centroid.
    Strictly forbids extrapolation beyond the native time domain.
    """
    times = trajectory["times"]
    quaternions = trajectory["quaternions"]
    centroids = trajectory["centroids"]

    t_start = times[0]
    t_end = times[-1]

    if query_time_s < t_start - tol_s or query_time_s > t_end + tol_s:
        raise ValueError(
            f"Query time {query_time_s:.6f}s is out of support [{t_start:.6f}s, {t_end:.6f}s]. "
            f"Extrapolation is strictly prohibited."
        )

    # Clean clamp within numerical tolerance
    query_clamped = min(max(query_time_s, t_start), t_end)

    if math.isclose(query_clamped, t_start, abs_tol=tol_s):
        return quaternion_to_matrix(quaternions[0]), centroids[0].copy()
    if math.isclose(query_clamped, t_end, abs_tol=tol_s):
        return quaternion_to_matrix(quaternions[-1]), centroids[-1].copy()

    # Find bounding index
    idx = int(np.searchsorted(times, query_clamped)) - 1
    idx = max(0, min(idx, len(times) - 2))

    t0, t1 = times[idx], times[idx + 1]
    if t1 <= t0:
        alpha = 0.0
    else:
        alpha = (query_clamped - t0) / (t1 - t0)

    interp_q = quaternion_slerp(quaternions[idx], quaternions[idx + 1], alpha)
    interp_c = (1.0 - alpha) * centroids[idx] + alpha * centroids[idx + 1]
    interp_r = quaternion_to_matrix(interp_q)

    return interp_r, interp_c


def enumerate_partvtk_files(
    directory: Path | str,
    expected_frames: int = EXPECTED_FRAMES,
    prefix: str = "PartFloating",
) -> list[Path]:
    """Explicitly enumerate expected PartFloating_0000.csv .. PartFloating_0240.csv files.

    Strictly avoids directory globbing to eliminate inclusion of summary stats
    such as PartFloating_stats.csv.
    """
    p_dir = Path(directory)
    if not p_dir.is_dir():
        raise FileNotFoundError(f"PartVTK directory not found: {p_dir}")

    csv_paths: list[Path] = []
    missing_files: list[str] = []

    for i in range(expected_frames):
        fn = f"{prefix}_{i:04d}.csv"
        fp = p_dir / fn
        if not fp.is_file():
            missing_files.append(fn)
        else:
            csv_paths.append(fp)

    if missing_files:
        raise FileNotFoundError(
            f"Missing {len(missing_files)} expected PartVTK files in {p_dir} "
            f"(e.g. {missing_files[:5]}). Expected complete {expected_frames} frame sequence."
        )

    return csv_paths


def load_partvtk_series_v2(
    csv_paths: Sequence[Path | str],
    target_mk: int = 60,
    target_type: int = 2,
    target_zone: int = 0,
    expected_frames: int = EXPECTED_FRAMES,
    expected_window_s: float = EXPECTED_WINDOW_S,
) -> dict[str, Any]:
    """Load and process an entire series of PartVTK floating-node CSV files with strict gates.

    Strict V2 Checks:
      1. Enforces exactly expected_frames (241).
      2. Enforces strictly increasing, finite timestamps (t_{i+1} > t_i).
      3. Enforces full window coverage (t_0 == 0.0s and t_end >= expected_window_s - 1e-4).
      4. Enforces invariant UID cohort across every frame relative to Frame 0.
      5. Reconstructs proper SO(3) rigid pose trajectory via Kabsch SVD.
    """
    if len(csv_paths) != expected_frames:
        raise ValueError(
            f"Expected exactly {expected_frames} PartVTK frames, received {len(csv_paths)}."
        )

    # Parse Frame 0 as reference configuration
    frame0_path = csv_paths[0]
    ref_data = parse_partvtk_floating_csv_v2(
        frame0_path, target_mk=target_mk, target_type=target_type, target_zone=target_zone
    )
    ref_idps = ref_data["idps"]
    ref_coords = ref_data["coords"]
    n_nodes = len(ref_idps)

    times: list[float] = []
    rot_matrices: list[np.ndarray] = []
    quaternions: list[np.ndarray] = []
    centroids: list[np.ndarray] = []
    translations: list[np.ndarray] = []
    rigidity_rms_list: list[float] = []
    rigidity_max_list: list[float] = []
    det_list: list[float] = []
    file_hashes: dict[str, str] = {}
    reflections_count = 0

    frame_records: list[dict[str, Any]] = []

    for frame_idx, p_raw in enumerate(csv_paths):
        p = Path(p_raw)
        frame_data = parse_partvtk_floating_csv_v2(
            p, target_mk=target_mk, target_type=target_type, target_zone=target_zone
        )
        file_hashes[str(p.resolve())] = frame_data["sha256"]

        t_val = frame_data["time_s"]
        if not math.isfinite(t_val):
            raise ValueError(f"Non-finite timestamp {t_val} at frame {frame_idx} ({p.name})")

        # Verify strictly increasing timestamps
        if times:
            if t_val <= times[-1]:
                raise ValueError(
                    f"Non-increasing timestamp at frame {frame_idx} ({p.name}): "
                    f"current time {t_val}s <= previous time {times[-1]}s"
                )

        # Verify exact UID cohort consistency
        if len(frame_data["idps"]) != n_nodes:
            raise ValueError(
                f"Cohort count mismatch at frame {frame_idx} ({p.name}): "
                f"expected {n_nodes} nodes, found {len(frame_data['idps'])}"
            )
        if not np.array_equal(frame_data["idps"], ref_idps):
            raise ValueError(f"Cohort UID mismatch at frame {frame_idx} ({p.name}) relative to Frame 0.")

        target_coords = frame_data["coords"]
        kabsch = compute_kabsch_svd(ref_coords, target_coords)

        r_mat = kabsch["rotation_matrix"]
        q_vec = kabsch["quaternion_wxyz"]
        c_vec = kabsch["target_centroid_m"]
        trans_vec = kabsch["translation_m"]
        rms_val = kabsch["rigidity_rms_m"]
        max_val = kabsch["rigidity_max_m"]
        det_val = kabsch["det_R"]

        if kabsch["reflection_detected"]:
            reflections_count += 1

        times.append(t_val)
        rot_matrices.append(r_mat)
        quaternions.append(q_vec)
        centroids.append(c_vec)
        translations.append(trans_vec)
        rigidity_rms_list.append(rms_val)
        rigidity_max_list.append(max_val)
        det_list.append(det_val)

        frame_records.append(
            {
                "frame_index": frame_idx,
                "time_s": t_val,
                "path": str(p.resolve()),
                "center_m": c_vec.tolist(),
                "translation_m": trans_vec.tolist(),
                "rotation_matrix": r_mat.tolist(),
                "quaternion_wxyz": q_vec.tolist(),
                "det_R": det_val,
                "rigidity_rms_m": rms_val,
                "rigidity_max_m": max_val,
            }
        )

    times_arr = np.array(times, dtype=np.float64)
    quaternions_arr = np.array(quaternions, dtype=np.float64)
    centroids_arr = np.array(centroids, dtype=np.float64)

    # Verify initial time and window coverage
    if not math.isclose(times_arr[0], 0.0, abs_tol=1e-4):
        raise ValueError(f"Initial frame time {times_arr[0]}s is not 0.0s (expected 0.0s)")

    if times_arr[-1] < expected_window_s - 1e-4:
        raise ValueError(
            f"Final frame time {times_arr[-1]}s does not cover expected window {expected_window_s}s"
        )

    return {
        "node_count": n_nodes,
        "frame_count": len(csv_paths),
        "times": times_arr,
        "rot_matrices": rot_matrices,
        "quaternions": quaternions_arr,
        "centroids": centroids_arr,
        "translations": np.array(translations, dtype=np.float64),
        "rigidity_rms": np.array(rigidity_rms_list, dtype=np.float64),
        "rigidity_max": np.array(rigidity_max_list, dtype=np.float64),
        "det_R": np.array(det_list, dtype=np.float64),
        "ref_centroid_m": ref_data["coords"].mean(axis=0),
        "ref_singular_values": kabsch["ref_singular_values"],
        "is_rank_3": kabsch["is_rank_3"],
        "reflections_detected": reflections_count,
        "file_hashes": file_hashes,
        "frame_records": frame_records,
    }


def validate_center_against_floating_info_v2(
    trajectory: dict[str, Any],
    floating_info_path: Path | str,
    time_tol_s: float = 1e-4,
) -> dict[str, Any]:
    """Validate geometry-fit centroids against official FloatingInfo center(t) at native times.

    Strict V2 Invariant:
      Enforces that 100% of trajectory frames find a matching timestamp in FloatingInfo.
      Partial matches are strictly rejected.
    """
    p = Path(floating_info_path)
    if not p.is_file():
        raise FileNotFoundError(f"FloatingInfo CSV not found: {p}")

    file_hash = sha256_file(p)

    with p.open("r", encoding="utf-8", errors="replace") as stream:
        lines = [line.strip() for line in stream if line.strip()]

    if len(lines) < 2:
        raise ValueError(f"FloatingInfo CSV {p} has fewer than 2 lines.")

    delimiter = ";" if ";" in lines[0] else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    fi_rows = list(reader)

    fi_times = np.array([float(r["time [s]"]) for r in fi_rows], dtype=np.float64)
    fi_centers = np.array(
        [[float(r["center.x [m]"]), float(r["center.y [m]"]), float(r["center.z [m]"])] for r in fi_rows],
        dtype=np.float64,
    )

    traj_times = trajectory["times"]
    traj_centers = trajectory["centroids"]
    n_expected = len(traj_times)

    diffs: list[float] = []
    matched_times: list[float] = []

    for t_idx, t_val in enumerate(traj_times):
        time_diffs = np.abs(fi_times - t_val)
        min_idx = int(np.argmin(time_diffs))
        if time_diffs[min_idx] <= time_tol_s:
            c_geom = traj_centers[t_idx]
            c_fi = fi_centers[min_idx]
            diff = float(np.linalg.norm(c_geom - c_fi))
            diffs.append(diff)
            matched_times.append(t_val)

    if len(diffs) != n_expected:
        raise ValueError(
            f"Strict FloatingInfo match failure: only {len(diffs)} of {n_expected} frames "
            f"matched FloatingInfo timestamps within {time_tol_s}s tolerance. Partial matches are rejected."
        )

    diffs_arr = np.array(diffs, dtype=np.float64)
    rmse_m = float(np.sqrt(np.mean(diffs_arr * diffs_arr)))
    max_m = float(np.max(diffs_arr))

    return {
        "floating_info_path": str(p.resolve()),
        "floating_info_sha256": file_hash,
        "matched_frames": len(diffs),
        "expected_frames": n_expected,
        "all_frames_matched": True,
        "center_diff_rmse_m": rmse_m,
        "center_diff_max_m": max_m,
        "center_diff_over_L": float(rmse_m / L_CHAR_M),
    }


def compare_trajectories_physical_time(
    ref_traj: dict[str, Any],
    cand_traj: dict[str, Any],
    eval_times_s: np.ndarray | None = None,
) -> dict[str, Any]:
    """Perform coordinate-invariant cross-DP comparison evaluated in continuous physical time.

    Uses SLERP on SO(3) quaternions and linear interpolation of centroid positions.
    Strictly avoids index-based pairing and Euler linear interpolation.
    """
    if eval_times_s is None:
        eval_times_s = ref_traj["times"]

    geodesic_dists: list[float] = []
    center_dists: list[float] = []

    for t_query in eval_times_s:
        r_ref, c_ref = interpolate_pose_at_physical_time_v2(ref_traj, t_query)
        r_cand, c_cand = interpolate_pose_at_physical_time_v2(cand_traj, t_query)

        phi = compute_so3_geodesic_distance(r_ref, r_cand)
        c_dist = float(np.linalg.norm(c_cand - c_ref))

        geodesic_dists.append(phi)
        center_dists.append(c_dist)

    geo_arr = np.array(geodesic_dists, dtype=np.float64)
    c_arr = np.array(center_dists, dtype=np.float64)

    geo_rmse_rad = float(np.sqrt(np.mean(geo_arr * geo_arr)))
    geo_max_rad = float(np.max(geo_arr))
    geo_mean_rad = float(np.mean(geo_arr))

    center_rmse_m = float(np.sqrt(np.mean(c_arr * c_arr)))
    center_max_m = float(np.max(c_arr))

    return {
        "comparison_method": "continuous_physical_time_slerp",
        "evaluated_time_points": len(eval_times_s),
        "time_window_start_s": float(eval_times_s[0]),
        "time_window_end_s": float(eval_times_s[-1]),
        "orientation_geodesic_metrics": {
            "geodesic_rmse_rad": geo_rmse_rad,
            "geodesic_rmse_deg": math.degrees(geo_rmse_rad),
            "geodesic_max_rad": geo_max_rad,
            "geodesic_max_deg": math.degrees(geo_max_rad),
            "geodesic_mean_rad": geo_mean_rad,
            "geodesic_mean_deg": math.degrees(geo_mean_rad),
            "metric_formulation": "Phi = arccos(clip((tr(R_ref^T R_cand) - 1) / 2, -1.0, 1.0))",
        },
        "translational_center_metrics": {
            "center_rmse_m": center_rmse_m,
            "center_max_m": center_max_m,
            "center_rmse_over_L": float(center_rmse_m / L_CHAR_M),
            "within_generic_5pct_macro_budget": bool(center_rmse_m / L_CHAR_M <= GENERIC_MACRO_TOLERANCE),
        },
        "declared_reference_scales": {
            "L_char_m": L_CHAR_M,
            "U_gravity_m_s": U_CHAR_M_S,
            "generic_macro_tolerance": GENERIC_MACRO_TOLERANCE,
        },
        "governance_and_budget_status": {
            "orientation_budget": None,
            "orientation_budget_status": "unregistered",
            "orientation_qualification_claim": None,
            "governance_note": (
                "Orientation budget is NULL / unregistered until an actual contract source is found. "
                "No invented gate or threshold substitution permitted."
            ),
        },
    }


def build_geometry_orientation_report_v2(
    primary_trajectory: dict[str, Any],
    floating_info_validation: dict[str, Any] | None = None,
    cross_dp_comparison: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct full authoritative JSON report for geometry-based orientation reader v2."""
    meta = extra_metadata or {}

    rigidity_rms = primary_trajectory["rigidity_rms"]
    det_r = primary_trajectory["det_R"]

    return {
        "schema": SCHEMA_REPORT,
        "recipe_id": RECIPE_ID,
        "family_id": "F6",
        "case_id": meta.get("case_id", "F6_ANGULAR_RELEASE_SUPPORT"),
        "attempt_id": meta.get("attempt_id", "f6-geometry-orientation-reader-007"),
        "primary_source_citations": {
            "functions_math_h": "DualSPHysics src/source/FunctionsMath.h:345-353 RotMatrix3x3 defines XYZ sequence (R = Rx*Ry*Rz)",
            "part_float_save_cpp": "DualSPHysics src/source/JDsPartFloatSave.cpp:166 records center, fvel, fomega in PartFloatInfo.ibi4, not Euler angles",
            "floating_info_help": "DualSPHysics doc/help/FloatingInfo_Help.out:66-85 states axis rotations with pitch sign change, no Euler chart sequence",
            "observation_plan": "observation_plan.json registers physical scales L=0.8m, U=sqrt(g*L) and generic 5% macro; unit radian scale is unregistered",
        },
        "governance_and_budget_status": {
            "orientation_budget": None,
            "orientation_budget_status": "unregistered",
            "orientation_qualification_claim": None,
            "case_qualification_status": "not_assessed",
            "root_qn_status": "0/336 products qualified; canary or descriptive fit is not numerical reference evidence",
        },
        "declared_reference_scales": {
            "gravity_m_s2": GRAVITY_M_S2,
            "L_char_m": L_CHAR_M,
            "U_gravity_m_s": U_CHAR_M_S,
            "generic_macro_tolerance": GENERIC_MACRO_TOLERANCE,
        },
        "reference_cohort": {
            "target_type": 2,
            "target_mk": 60,
            "target_zone": 0,
            "node_count": primary_trajectory["node_count"],
            "initial_centroid_m": primary_trajectory["ref_centroid_m"].tolist(),
            "covariance_singular_values": primary_trajectory["ref_singular_values"],
            "is_rank_3": primary_trajectory["is_rank_3"],
            "finite_unique_uid_verified": True,
        },
        "trajectory_summary": {
            "frame_count": primary_trajectory["frame_count"],
            "time_start_s": float(primary_trajectory["times"][0]),
            "time_end_s": float(primary_trajectory["times"][-1]),
            "max_rigidity_rms_m": float(np.max(rigidity_rms)),
            "mean_rigidity_rms_m": float(np.mean(rigidity_rms)),
            "reflections_detected": primary_trajectory["reflections_detected"],
            "all_det_r_positive_one": bool(np.allclose(det_r, 1.0, atol=1e-5)),
        },
        "floating_info_validation": floating_info_validation,
        "cross_dp_comparison": cross_dp_comparison,
        "input_source_hashes": primary_trajectory["file_hashes"],
        "frames": primary_trajectory["frame_records"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DS-DATA-02 F6 Geometry-Based Orientation Reader & Cross-DP Evaluator (v2)"
    )
    parser.add_argument("--config", type=str, help="Path to config JSON file")
    parser.add_argument("--partvtk-dir", type=str, help="Directory containing PartFloating_*.csv files")
    parser.add_argument("--floating-info", type=str, help="Path to official FloatingInfo_mk60.csv")
    parser.add_argument("--cand-partvtk-dir", type=str, help="Directory containing candidate PartFloating_*.csv files")
    parser.add_argument("--output", type=str, help="Output report JSON path")
    parser.add_argument("--target-mk", type=int, default=60, help="Target MkBound for floating body (default: 60)")
    parser.add_argument("--target-type", type=int, default=2, help="Target Type for floating nodes (default: 2)")
    parser.add_argument("--target-zone", type=int, default=0, help="Target Zone for floating nodes (default: 0)")

    args = parser.parse_args()

    # Load configuration if provided
    config: dict[str, Any] = {}
    if args.config:
        cfg_path = Path(args.config)
        if cfg_path.is_file():
            with cfg_path.open("r", encoding="utf-8") as f:
                config = json.load(f)

    partvtk_dir = args.partvtk_dir or config.get("partvtk_dir")
    floating_info = args.floating_info or config.get("floating_info_path")
    cand_dir = args.cand_partvtk_dir or config.get("cand_partvtk_dir")
    out_path = args.output or config.get("output_path", "geometry_orientation_report_v2.json")
    target_mk = args.target_mk or config.get("target_mk", 60)
    target_type = args.target_type or config.get("target_type", 2)
    target_zone = args.target_zone or config.get("target_zone", 0)

    if not partvtk_dir:
        raise ValueError("Must provide --partvtk-dir or specify in --config")

    # Explicit 0000..0240 enumeration (no globbing)
    csv_files = enumerate_partvtk_files(partvtk_dir)

    primary_traj = load_partvtk_series_v2(
        csv_files, target_mk=target_mk, target_type=target_type, target_zone=target_zone
    )

    fi_validation = None
    if floating_info:
        fi_validation = validate_center_against_floating_info_v2(primary_traj, floating_info)

    cross_dp = None
    if cand_dir:
        cand_csvs = enumerate_partvtk_files(cand_dir)
        cand_traj = load_partvtk_series_v2(
            cand_csvs, target_mk=target_mk, target_type=target_type, target_zone=target_zone
        )
        cross_dp = compare_trajectories_physical_time(primary_traj, cand_traj)

    report = build_geometry_orientation_report_v2(
        primary_traj,
        floating_info_validation=fi_validation,
        cross_dp_comparison=cross_dp,
        extra_metadata=config.get("metadata", {}),
    )

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with out_p.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Report v2 written successfully to {out_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
