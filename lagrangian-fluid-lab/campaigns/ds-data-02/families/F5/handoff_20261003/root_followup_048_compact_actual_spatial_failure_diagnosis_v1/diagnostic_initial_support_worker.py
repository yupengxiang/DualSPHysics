#!/usr/bin/env python3
"""Root-Guarded Diagnostic Worker: F5 Compact Initial Particle Support & Hollow Bed Diagnosis.

Audits completed official Round 054 CSV exports to establish:
1. Exact particle inventory across all Types (0: Fixed, 1: Moving, 3: Fluid) and Mks.
2. Fluid bed-clearance distribution z - z_bed(x).
3. Nearest boundary neighbor distance for all fluid particles.
4. Boundary kernel support completeness within radius r <= 2h.
5. Hollow bed cavity test: counts of particles inside the interior bed solid region.
6. Sidewall boundary layer thickness in y.

GOVERNANCE & AUDIT SCOPE:
- Pure read-only CPU audit of existing CSV exports.
- Strictly labeled: DIAGNOSTIC ONLY, NOT Q-N, NO PRODUCTION APPROVAL.
- Preserves raw IDs, weights, current input hashes, and all 13 official CSV payload columns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np


def sha256_file(path: Path | str) -> str:
    """Compute sha256 hex digest of file in 64 KiB blocks."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_bed_elevation(x: np.ndarray) -> np.ndarray:
    """Compute continuous bed surface elevation z_bed(x) along longitudinal flume."""
    # Profile nodes:
    # x in [-0.20, 2.00]: z = 0.000
    # x in [2.00, 3.60]: slope m = 0.280 (reaches 0.448)
    # x in [3.60, 3.90]: plateau z = 0.448
    # x in [3.90, 4.40]: downslope to z = 0.050
    # x in [4.40, 4.80]: basin z = 0.050
    z = np.zeros_like(x)
    
    # Flat basin
    mask_flat = (x >= -0.20) & (x < 2.00)
    z[mask_flat] = 0.000
    
    # Upward slope
    mask_slope = (x >= 2.00) & (x < 3.60)
    z[mask_slope] = 0.280 * (x[mask_slope] - 2.00)
    
    # Crest plateau
    mask_crest = (x >= 3.60) & (x < 3.90)
    z[mask_crest] = 0.448
    
    # Downslope
    mask_down = (x >= 3.90) & (x < 4.40)
    t = (x[mask_down] - 3.90) / 0.50
    z[mask_down] = 0.448 + t * (0.050 - 0.448)
    
    # Receiving basin
    mask_basin = x >= 4.40
    z[mask_basin] = 0.050
    
    return z


def audit_single_case_csv(
    role: str,
    case_id: str,
    dp: float,
    csv_path: Path,
    mechanism: str,
) -> Dict[str, Any]:
    """Perform comprehensive support and hollow-cavity audit on a single initial CSV export."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"Initial CSV not found: {csv_path}")

    csv_sha = sha256_file(csv_path)

    # Read CSV header and extract 13 official columns
    with csv_path.open("r", encoding="utf-8") as f:
        header_line = f.readline()
        cols = next(csv.reader([header_line]))
        
        required_cols = [
            "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Zone", "Idp", "Type", "Mk",
            "Mass [kg]", "Vel.x [m/s]", "Vel.y [m/s]", "Vel.z [m/s]", "Rhop [kg/m^3]", "Press [Pa]"
        ]
        for col in required_cols:
            if col not in cols:
                raise ValueError(f"Missing required official column '{col}' in {csv_path.name}")
        
        col_indices = [cols.index(col) for col in required_cols]
        raw_data = np.loadtxt(f, delimiter=",", usecols=col_indices, ndmin=2)

    total_particles = raw_data.shape[0]
    pos = raw_data[:, 0:3]
    types = raw_data[:, 5].astype(int)
    mks = raw_data[:, 6].astype(int)
    masses = raw_data[:, 7]
    rhops = raw_data[:, 11]

    # Subsets
    is_fluid = types == 3
    is_fixed = types == 0
    is_moving = types == 1
    
    pos_fluid = pos[is_fluid]
    pos_bound = pos[is_fixed | is_moving]
    pos_bed = pos[is_fixed & (mks == 50)]
    pos_walls = pos[is_fixed & (mks == 40)]
    pos_floor = pos[is_fixed & (mks == 10)]

    # 1. Type and Mk inventory
    type_counts = {int(t): int(np.sum(types == t)) for t in np.unique(types)}
    mk_counts = {int(m): int(np.sum(mks == m)) for m in np.unique(mks)}

    # 2. Fluid Bed Clearance
    x_f, y_f, z_f = pos_fluid[:, 0], pos_fluid[:, 1], pos_fluid[:, 2]
    z_bed_at_xf = compute_bed_elevation(x_f)
    clearances = z_f - z_bed_at_xf
    min_clearance = float(np.min(clearances))
    mean_clearance = float(np.mean(clearances))

    # 3. Hollow Bed Interior Cavity Test
    # Region inside the bed polyhedron below the surface skin:
    # x in [-0.20, 4.80], y in [-0.14, 0.14], z in [-0.14, z_bed(x) - dp]
    x_all, y_all, z_all = pos[:, 0], pos[:, 1], pos[:, 2]
    z_bed_all = compute_bed_elevation(x_all)
    in_interior_void = (
        (x_all >= -0.19)
        & (x_all <= 4.79)
        & (np.abs(y_all) <= 0.14)
        & (z_all >= -0.14)
        & (z_all <= z_bed_all - 0.9 * dp)
    )
    interior_cavity_particles = int(np.sum(in_interior_void))
    bed_is_hollow_shell = bool(interior_cavity_particles == 0)

    # 4. Nearest Boundary Distance & Kernel Completeness
    # Kernel radius 2h = 2 * sqrt(3) * dp
    h_smooth = math.sqrt(3.0) * dp
    r_kernel = 2.0 * h_smooth

    # Sample fluid particles for nearest boundary distance to keep audit bounded
    # (use every k-th particle if large, or full if moderate)
    step = 1 if len(pos_fluid) <= 50000 else int(math.ceil(len(pos_fluid) / 50000))
    sample_fluid = pos_fluid[::step]
    
    # Compute distances to nearest boundary particle
    # Using spatial grid or block computation
    min_dists = []
    neighbors_in_2h = []
    
    # Simple block-vectorized distance for sample
    chunk_size = 500
    for i in range(0, len(sample_fluid), chunk_size):
        chunk = sample_fluid[i : i + chunk_size]
        # (chunk_size, 1, 3) - (1, n_bound, 3)
        diff = chunk[:, np.newaxis, :] - pos_bound[np.newaxis, :, :]
        dist_sq = np.sum(diff ** 2, axis=2)
        dists = np.sqrt(dist_sq)
        
        min_dists.extend(np.min(dists, axis=1).tolist())
        neighbors_in_2h.extend(np.sum(dists <= r_kernel, axis=1).tolist())

    min_boundary_dist_m = float(np.min(min_dists))
    mean_boundary_dist_m = float(np.mean(min_dists))
    median_neighbors_2h = float(np.median(neighbors_in_2h))
    min_neighbors_2h = int(np.min(neighbors_in_2h))

    # 5. Sidewall Layer Count
    # Sidewalls are at y in [-0.18, -0.15] and [0.15, 0.18]
    left_wall_y = pos_walls[pos_walls[:, 1] < 0, 1]
    right_wall_y = pos_walls[pos_walls[:, 1] > 0, 1]
    
    unique_left_y = len(np.unique(np.round(left_wall_y, 5)))
    unique_right_y = len(np.unique(np.round(right_wall_y, 5)))

    return {
        "role": role,
        "case_id": case_id,
        "mechanism": mechanism,
        "dp_m": dp,
        "kernel_h_m": h_smooth,
        "kernel_support_radius_2h_m": r_kernel,
        "source_csv": str(csv_path),
        "source_csv_sha256": csv_sha,
        "total_particles": total_particles,
        "fluid_particles": int(np.sum(is_fluid)),
        "fixed_particles": int(np.sum(is_fixed)),
        "moving_particles": int(np.sum(is_moving)),
        "type_counts": type_counts,
        "mk_counts": mk_counts,
        "bed_particles_mk50": int(np.sum(mks == 50)),
        "wall_particles_mk40": int(np.sum(mks == 40)),
        "floor_particles_mk10": int(np.sum(mks == 10)),
        "fluid_min_clearance_above_bed_m": min_clearance,
        "fluid_mean_clearance_above_bed_m": mean_clearance,
        "bed_interior_cavity_particles": interior_cavity_particles,
        "bed_is_hollow_shell": bed_is_hollow_shell,
        "fluid_sample_size_audited": len(sample_fluid),
        "fluid_min_boundary_distance_m": min_boundary_dist_m,
        "fluid_mean_boundary_distance_m": mean_boundary_dist_m,
        "fluid_min_neighbors_within_2h": min_neighbors_2h,
        "fluid_median_neighbors_within_2h": median_neighbors_2h,
        "sidewall_unique_y_layers_left": unique_left_y,
        "sidewall_unique_y_layers_right": unique_right_y,
        "support_diagnosis": {
            "hollow_bed_confirmed": bed_is_hollow_shell,
            "boundary_layer_count": 1 if bed_is_hollow_shell else "multi",
            "sidewall_layer_count": max(unique_left_y, unique_right_y),
            "adequate_3layer_support_established": bool(not bed_is_hollow_shell and max(unique_left_y, unique_right_y) >= 3),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F5 Compact Native Initial Support & Hollow Bed Diagnostic Worker."
    )
    parser.add_argument("--binding", required=True, help="Diagnostic binding JSON path.")
    parser.add_argument("--output-dir", required=True, help="Target output directory for diagnostic report.")
    args = parser.parse_args()

    binding_path = Path(args.binding)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    binding_data = json.loads(binding_path.read_text(encoding="utf-8"))
    
    diagnostics = []
    for c in binding_data["cases"]:
        res = audit_single_case_csv(
            role=c["role"],
            case_id=c["case_id"],
            dp=c["dp"],
            csv_path=Path(c["csv_path"]),
            mechanism=c["mechanism"],
        )
        diagnostics.append(res)

    report = {
        "schema": "ds02.f5.root-diagnostic-initial-support-report.v1",
        "governance": {
            "status": "DIAGNOSTIC ONLY",
            "q_n": "NOT GRANTED",
            "production_approval": "NONE",
            "rationale": "Direct native CSV diagnostic of particle boundary support completeness, hollow cavity presence, and layer thickness.",
        },
        "cases": diagnostics,
        "summary": {
            "all_cases_bed_is_hollow_shell": all(c["bed_is_hollow_shell"] for c in diagnostics),
            "coarse_sidewall_layers": next((c["sidewall_unique_y_layers_left"] for c in diagnostics if c["dp_m"] == 0.02), None),
            "medium_sidewall_layers": next((c["sidewall_unique_y_layers_left"] for c in diagnostics if c["dp_m"] == 0.0125), None),
            "fine_sidewall_layers": next((c["sidewall_unique_y_layers_left"] for c in diagnostics if c["dp_m"] == 0.010), None),
        },
    }

    out_json = output_dir / "f5_initial_support_diagnostic_report.json"
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    print(json.dumps({
        "status": "COMPLETED",
        "cases_audited": len(diagnostics),
        "all_cases_bed_is_hollow_shell": report["summary"]["all_cases_bed_is_hollow_shell"],
        "report_path": str(out_json),
    }))


if __name__ == "__main__":
    main()
