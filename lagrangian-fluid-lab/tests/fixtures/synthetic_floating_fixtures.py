"""Synthetic floating-node fixtures for testing DS-DATA-02 F6 SO(3) Geometry Orientation Reader.

Provides deterministic, synthetic mock datasets:
1. Rigid pure rotation fixture: known angle and axis, verifies Kabsch recovery to machine precision.
2. Reflection fixture: verifies proper det(R) = +1 enforcement and reflection detection.
3. Non-rigid deformation fixture: verifies that rigidity RMS residual strictly flags deformation.
4. UID permutation fixture: verifies node matching invariant to row order.
5. Full window 241-frame fixture: simulates continuous physical motion across 0..12s,
   verifying SLERP cross-DP comparison and FloatingInfo centroid validation.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Sequence

import numpy as np


def generate_box_nodes(
    nx: int = 8,
    ny: int = 8,
    nz: int = 4,
    box_size: tuple[float, float, float] = (0.8, 0.8, 0.4),
    center: tuple[float, float, float] = (2.4, 1.2, 1.08),
    start_idp: int = 73441,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate discrete 3D lattice of nodes within a box.

    Returns:
      (idps, coords) where idps is (N,) int64 array and coords is (N, 3) float64 array.
    """
    lx, ly, lz = box_size
    cx, cy, cz = center

    xs = np.linspace(cx - lx / 2.0, cx + lx / 2.0, nx)
    ys = np.linspace(cy - ly / 2.0, cy + ly / 2.0, ny)
    zs = np.linspace(cz - lz / 2.0, cz + lz / 2.0, nz)

    grid_x, grid_y, grid_z = np.meshgrid(xs, ys, zs, indexing="ij")
    coords = np.column_stack([grid_x.ravel(), grid_y.ravel(), grid_z.ravel()])

    n_points = coords.shape[0]
    idps = np.arange(start_idp, start_idp + n_points, dtype=np.int64)

    return idps, coords


def write_synthetic_partvtk_csv(
    path: Path,
    time_s: float,
    idps: Sequence[int],
    coords: np.ndarray,
    target_mk: int = 60,
    target_type: int = 2,
    shuffle_rows: bool = False,
) -> Path:
    """Write PartVTK floating CSV matching Root export 028 format.

    Header lines:
      Line 1: TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid
      Line 2: <time_s>,<Np>,<Np>,0,0,<Np>,0
      Line 3: <blank>
      Line 4: Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Type,Mk,
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    n_nodes = len(idps)

    indices = list(range(n_nodes))
    if shuffle_rows:
        np.random.seed(42)
        np.random.shuffle(indices)

    with path.open("w", encoding="utf-8") as f:
        # Line 1: metadata header
        f.write("TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid\n")
        # Line 2: metadata values
        f.write(f"{time_s:.6f},{n_nodes},{n_nodes},0,0,{n_nodes},0\n")
        # Line 3: blank line
        f.write("\n")
        # Line 4: column headers
        f.write("Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Type,Mk,\n")

        # Node rows
        for idx in indices:
            x, y, z = coords[idx]
            idp = idps[idx]
            f.write(f"  {x:.7E},  {y:.7E},  {z:.7E},0,{idp},{target_type},{target_mk},\n")

    return path


def write_synthetic_floating_info_csv(
    path: Path,
    times: np.ndarray,
    centers: np.ndarray,
) -> Path:
    """Write synthetic official FloatingInfo_mk60.csv file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "part",
        "time [s]",
        "fvel.x [m/s]",
        "fvel.y [m/s]",
        "fvel.z [m/s]",
        "fomega.x [rad/s]",
        "fomega.y [rad/s]",
        "fomega.z [rad/s]",
        "center.x [m]",
        "center.y [m]",
        "center.z [m]",
        "surge [m]",
        "sway [m]",
        "heave [m]",
        "roll [deg]",
        "pitch [deg]",
        "yaw [deg]",
    ]

    c0 = centers[0]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)

        for i, t in enumerate(times):
            c = centers[i]
            surge = c[0] - c0[0]
            sway = c[1] - c0[1]
            heave = c[2] - c0[2]

            row = [
                str(i),
                f"{t:.6f}",
                "0.0",
                "0.0",
                "0.0",
                "0.0",
                "0.0",
                "0.0",
                f"{c[0]:.6f}",
                f"{c[1]:.6f}",
                f"{c[2]:.6f}",
                f"{surge:.6f}",
                f"{sway:.6f}",
                f"{heave:.6f}",
                "0.0",
                "0.0",
                "0.0",
            ]
            writer.writerow(row)

    return path


def create_rigid_rotation_fixture(
    dir_path: Path,
    angle_rad: float = 0.35,
    axis: tuple[float, float, float] = (1.0, 2.0, 3.0),
    translation: tuple[float, float, float] = (0.05, -0.02, 0.08),
) -> tuple[np.ndarray, np.ndarray, Path, Path]:
    """Generate Frame 0 (initial) and Frame 1 with a known rigid rotation and translation."""
    idps, p0 = generate_box_nodes()
    p_c0 = np.mean(p0, axis=0)

    # Normalize axis
    ax = np.array(axis, dtype=np.float64)
    ax /= np.linalg.norm(ax)

    # Rodrigues' formula for known rotation
    k_mat = np.array(
        [[0.0, -ax[2], ax[1]], [ax[2], 0.0, -ax[0]], [-ax[1], ax[0], 0.0]], dtype=np.float64
    )
    r_true = (
        np.eye(3)
        + math.sin(angle_rad) * k_mat
        + (1.0 - math.cos(angle_rad)) * (k_mat @ k_mat)
    )

    t_vec = np.array(translation, dtype=np.float64)
    q_c = p_c0 + t_vec
    p1 = ((p0 - p_c0) @ r_true.T) + q_c

    f0_csv = write_synthetic_partvtk_csv(dir_path / "PartFloating_0000.csv", 0.0, idps, p0)
    f1_csv = write_synthetic_partvtk_csv(dir_path / "PartFloating_0001.csv", 0.05, idps, p1)

    return r_true, t_vec, f0_csv, f1_csv


def create_reflection_fixture(
    dir_path: Path,
) -> tuple[Path, Path]:
    """Generate Frame 0 and Frame 1 with an improper reflection (det = -1)."""
    idps, p0 = generate_box_nodes()
    p_c0 = np.mean(p0, axis=0)

    # Reflection matrix across XY plane: z -> -z
    r_reflect = np.diag([1.0, 1.0, -1.0])
    p1 = ((p0 - p_c0) @ r_reflect.T) + p_c0

    f0_csv = write_synthetic_partvtk_csv(dir_path / "PartFloating_0000.csv", 0.0, idps, p0)
    f1_csv = write_synthetic_partvtk_csv(dir_path / "PartFloating_0001.csv", 0.05, idps, p1)

    return f0_csv, f1_csv


def create_nonrigid_deformation_fixture(
    dir_path: Path,
    amplitude: float = 0.04,
) -> tuple[Path, Path]:
    """Generate Frame 0 and Frame 1 where nodes undergo non-rigid deformation."""
    idps, p0 = generate_box_nodes()
    p_c0 = np.mean(p0, axis=0)

    # Non-linear deformation: stretch corners sinusoidally
    p1 = p0.copy()
    p1[:, 0] += amplitude * np.sin(2.0 * np.pi * (p0[:, 1] - p_c0[1]) / 0.8)
    p1[:, 2] += amplitude * np.cos(2.0 * np.pi * (p0[:, 0] - p_c0[0]) / 0.8)

    f0_csv = write_synthetic_partvtk_csv(dir_path / "PartFloating_0000.csv", 0.0, idps, p0)
    f1_csv = write_synthetic_partvtk_csv(dir_path / "PartFloating_0001.csv", 0.05, idps, p1)

    return f0_csv, f1_csv


def create_uid_permutation_fixture(
    dir_path: Path,
    angle_rad: float = 0.25,
) -> tuple[np.ndarray, Path, Path]:
    """Generate Frame 0 and Frame 1 where Frame 1 has rows shuffled (permuted UIDs)."""
    idps, p0 = generate_box_nodes()
    p_c0 = np.mean(p0, axis=0)

    # Rotation around Y axis
    r_true = np.array(
        [
            [math.cos(angle_rad), 0.0, math.sin(angle_rad)],
            [0.0, 1.0, 0.0],
            [-math.sin(angle_rad), 0.0, math.cos(angle_rad)],
        ],
        dtype=np.float64,
    )
    p1 = ((p0 - p_c0) @ r_true.T) + p_c0

    f0_csv = write_synthetic_partvtk_csv(dir_path / "PartFloating_0000.csv", 0.0, idps, p0)
    f1_csv = write_synthetic_partvtk_csv(
        dir_path / "PartFloating_0001.csv", 0.05, idps, p1, shuffle_rows=True
    )

    return r_true, f0_csv, f1_csv


def create_full_window_fixture(
    dir_path: Path,
    n_frames: int = 241,
    dt: float = 0.05,
) -> tuple[list[Path], Path]:
    """Generate a complete 241-frame PartVTK series (0.0s to 12.0s) and FloatingInfo CSV."""
    idps, p0 = generate_box_nodes()
    p_c0 = np.mean(p0, axis=0)

    times = np.linspace(0.0, (n_frames - 1) * dt, n_frames)
    centers: list[np.ndarray] = []
    csv_paths: list[Path] = []

    part_dir = dir_path / "partvtk_series"
    part_dir.mkdir(parents=True, exist_ok=True)

    for i, t in enumerate(times):
        # Oscillatory motion
        theta = 0.08 * math.sin(1.2 * t)  # pitch rotation around Y axis
        r_mat = np.array(
            [
                [math.cos(theta), 0.0, math.sin(theta)],
                [0.0, 1.0, 0.0],
                [-math.sin(theta), 0.0, math.cos(theta)],
            ],
            dtype=np.float64,
        )

        c_t = p_c0 + np.array(
            [0.04 * math.sin(0.6 * t), 0.0, 0.06 * math.cos(0.9 * t) - 0.06],
            dtype=np.float64,
        )
        centers.append(c_t)

        p_t = ((p0 - p_c0) @ r_mat.T) + c_t
        csv_p = part_dir / f"PartFloating_{i:04d}.csv"
        write_synthetic_partvtk_csv(csv_p, t, idps, p_t)
        csv_paths.append(csv_p)

    centers_arr = np.array(centers, dtype=np.float64)
    fi_path = dir_path / "FloatingInfo_mk60.csv"
    write_synthetic_floating_info_csv(fi_path, times, centers_arr)

    return csv_paths, fi_path
