"""Synthetic floating-node fixtures for testing DS-DATA-02 F6 SO(3) Geometry Orientation Reader v2.

Directly supports testing the 5 documented omissions resolved in v2:
1. Strict Zone0 / Type2 / Mk60 exact full cohort verification (and negative corrupt/wrong type/mk/zone fixtures).
2. Explicit 0000..0240 enumeration (including presence of PartFloating_stats.csv in the directory).
3. Full 241 frames, finite, strictly increasing times, [0, 12s] window coverage (and negative non-increasing/truncated fixtures).
4. No extrapolation beyond support (negative out-of-support query test).
5. 100% full FloatingInfo match (and negative partial-match fixture).
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


def write_synthetic_partvtk_csv_v2(
    path: Path,
    time_s: float,
    idps: Sequence[int],
    coords: np.ndarray,
    target_mk: int = 60,
    target_type: int = 2,
    target_zone: int = 0,
    meta_nfloat_override: int | None = None,
    corrupt_line: str | None = None,
    inject_wrong_type: int | None = None,
    inject_wrong_mk: int | None = None,
    inject_wrong_zone: int | None = None,
    shuffle_rows: bool = False,
) -> Path:
    """Write PartVTK floating CSV matching Root export 028 format with configurable injections."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_nodes = len(idps)
    meta_nfloat = meta_nfloat_override if meta_nfloat_override is not None else n_nodes

    indices = list(range(n_nodes))
    if shuffle_rows:
        np.random.seed(42)
        np.random.shuffle(indices)

    with path.open("w", encoding="utf-8") as f:
        # Line 1: metadata header
        f.write("TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid\n")
        # Line 2: metadata values
        f.write(f"{time_s:.6f},{meta_nfloat},{meta_nfloat},0,0,{meta_nfloat},0\n")
        # Line 3: blank line
        f.write("\n")
        # Line 4: column headers
        f.write("Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Type,Mk,\n")

        # Node rows
        for i, idx in enumerate(indices):
            x, y, z = coords[idx]
            idp = idps[idx]
            row_type = inject_wrong_type if (inject_wrong_type is not None and i == 0) else target_type
            row_mk = inject_wrong_mk if (inject_wrong_mk is not None and i == 0) else target_mk
            row_zone = inject_wrong_zone if (inject_wrong_zone is not None and i == 0) else target_zone

            f.write(f"  {x:.7E},  {y:.7E},  {z:.7E},{row_zone},{idp},{row_type},{row_mk},\n")

        if corrupt_line:
            f.write(f"{corrupt_line}\n")

    return path


def write_synthetic_floating_info_csv_v2(
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


def create_full_window_fixture_v2(
    dir_path: Path,
    n_frames: int = 241,
    dt: float = 0.05,
    include_stats_csv: bool = True,
) -> tuple[list[Path], Path]:
    """Generate a complete 241-frame PartVTK series (0.0s to 12.0s) and FloatingInfo CSV.

    Also optionally writes PartFloating_stats.csv into the directory to verify that
    explicit enumeration does NOT include it.
    """
    idps, p0 = generate_box_nodes()
    p_c0 = np.mean(p0, axis=0)

    times = np.linspace(0.0, (n_frames - 1) * dt, n_frames)
    centers: list[np.ndarray] = []
    csv_paths: list[Path] = []

    part_dir = dir_path / "partvtk_series"
    part_dir.mkdir(parents=True, exist_ok=True)

    # Write PartFloating_stats.csv to test omission 2
    if include_stats_csv:
        stats_path = part_dir / "PartFloating_stats.csv"
        with stats_path.open("w", encoding="utf-8") as f:
            f.write("Part;Time;TotalNodes;FloatingNodes;MinX;MaxX\n")
            f.write("0;0.0;256;256;2.0;2.8\n")

    for i, t in enumerate(times):
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
        write_synthetic_partvtk_csv_v2(csv_p, t, idps, p_t)
        csv_paths.append(csv_p)

    centers_arr = np.array(centers, dtype=np.float64)
    fi_path = dir_path / "FloatingInfo_mk60.csv"
    write_synthetic_floating_info_csv_v2(fi_path, times, centers_arr)

    return csv_paths, fi_path
