#!/usr/bin/env python3
"""Audit the native GenCase output of the F1 cell-center mother.

This is an initial-state audit only.  It reads the immutable GenCase VTK and
text outputs, checks the native fluid count/mass and center envelope, and
records the declared finite-wall/separator clearance.  It never launches a
solver and it does not issue a Q-N decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_binary_vtk_points(path: Path) -> np.ndarray:
    """Read the first binary VTK POINTS block without materialising other data."""

    raw = path.read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\r?\n", raw)
    if match is None:
        raise ValueError(f"binary POINTS header not found in {path}")
    count = int(match.group(1))
    start = match.end()
    end = start + count * 3 * 4
    if end > len(raw):
        raise ValueError(f"truncated POINTS block in {path}")
    points = np.frombuffer(raw, dtype=">f4", count=count * 3, offset=start)
    return points.astype(np.float64, copy=False).reshape(count, 3)


def parse_number(pattern: str, text: str, label: str, cast=float):
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"{label} not found in GenCase output")
    return cast(match.group(1).replace(",", ""))


def audit(gencase_root: Path, metadata_path: Path, output_path: Path) -> dict:
    metadata = json.loads(metadata_path.read_text())
    contract = metadata["continuous_contract"]
    geometry = metadata["declared_geometry"]
    out_path = next(gencase_root.glob("*.out"))
    fluid_vtk = next(gencase_root.glob("*_Fluid.vtk"))
    bound_vtk = next(gencase_root.glob("*_Bound.vtk"))
    generated_xml = next(gencase_root.glob("*.xml"))
    bi4 = next(gencase_root.glob("*.bi4"))
    text = out_path.read_text(errors="replace")
    fluid = read_binary_vtk_points(fluid_vtk)
    bound = read_binary_vtk_points(bound_vtk)

    center_low = np.asarray(
        contract.get("expected_center_envelope_low_m", contract["initial_center_envelope_low_m"]),
        dtype=float,
    )
    center_high = np.asarray(
        contract.get("expected_center_envelope_high_m", contract["initial_center_envelope_high_m"]),
        dtype=float,
    )
    dp = float(center_high[0] - center_low[0])
    nx, ny, nz = (int(x) for x in contract["expected_center_counts_xyz"])
    dp /= nx - 1
    low = center_low
    high = center_high
    reservoir_low = np.asarray(contract["reservoir_low_m"], dtype=float)
    reservoir_high = np.asarray(contract["reservoir_high_m"], dtype=float)
    tank_low = np.asarray(geometry["tank_low_m"], dtype=float)
    tank_high = np.asarray(geometry["tank_high_m"], dtype=float)
    expected = int(contract["expected_fluid_count"])
    mass_fluid = parse_number(r"MassFluid=\[([0-9eE+_.-]+)\]", text, "MassFluid")
    out_fluid = parse_number(r"Fluid\.+:\s*([0-9,]+)", text, "fluid count", int)
    out_total = parse_number(r"Total particles:\s*([0-9,]+)", text, "total count", int)
    data2d = parse_number(r"Data2D=\[([01])\]", text, "Data2D", int)

    grid_residual = np.abs((fluid - low) / dp - np.rint((fluid - low) / dp))
    finite = np.isfinite(fluid).all(axis=1)
    unique = len(np.unique(fluid, axis=0)) == len(fluid)
    fluid_bounds = [fluid.min(axis=0).tolist(), fluid.max(axis=0).tolist()]
    reservoir_inside = bool(
        np.all(fluid >= reservoir_low - 2e-6)
        and np.all(fluid <= reservoir_high + 2e-6)
    )
    expected_center_bounds = bool(
        np.all(fluid.min(axis=0) >= low - 2e-6)
        and np.all(fluid.max(axis=0) <= high + 2e-6)
    )
    # A half-cell safety margin is required at each closed outer wall.  The top
    # is intentionally open and is therefore not treated as a closed face.
    clearances = {
        "x_low_m": float(fluid[:, 0].min() - tank_low[0]),
        "x_high_m": float(tank_high[0] - fluid[:, 0].max()),
        "y_low_m": float(fluid[:, 1].min() - tank_low[1]),
        "y_high_m": float(tank_high[1] - fluid[:, 1].max()),
        "z_low_m": float(fluid[:, 2].min() - tank_low[2]),
    }
    wall_clearance = bool(all(value >= float(geometry["wall_clearance_from_fluid_centers_m"]) - 2e-6 for value in clearances.values()))
    separator_high = np.asarray(geometry["separator_high_m"], dtype=float)
    separator_clearance = bool(np.all(fluid[:, 0] >= separator_high[0] + dp / 2 - 2e-6))
    # The generated VTK is the actual initial point set.  This check records
    # the finite wall source range without inferring a solver-time boundary.
    bound_bounds = [bound.min(axis=0).tolist(), bound.max(axis=0).tolist()]
    checks = {
        "actual_3d": data2d == 0,
        "native_fluid_count_matches": len(fluid) == expected and out_fluid == expected,
        "native_mass_matches_kg": abs(len(fluid) * mass_fluid - float(contract["expected_native_mass_kg"])) <= 1e-9,
        "finite_fluid_rows": bool(finite.all()),
        "fluid_identity_positions_unique": bool(unique),
        "center_grid_envelope": expected_center_bounds,
        "continuous_reservoir_contains_centers": reservoir_inside,
        # GenCase's VTK is float32; a 1e-5 lattice residual is the expected
        # serialization roundoff for 1 cm coordinates.
        "lattice_residual": bool(float(grid_residual.max()) <= 2e-5),
        "closed_wall_clearance": wall_clearance,
        "separator_clearance": separator_clearance,
        "outer_boundary_generated": len(bound) > 0,
    }
    report = {
        "schema": "ds02.f1.finite-center-native-audit.v1",
        "case_id": metadata["case_id"],
        "physical_case_id": metadata["physical_case_id"],
        "status": "pass_initial_native_contract" if all(checks.values()) else "failed_initial_native_contract",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "checks": checks,
        "native": {
            "dimension_from_gencase": 2 if data2d else 3,
            "total_particles_from_gencase": out_total,
            "fluid_particles_from_gencase": out_fluid,
            "fluid_particles_from_vtk": len(fluid),
            "mass_fluid_kg": mass_fluid,
            "initial_fluid_mass_kg": float(len(fluid) * mass_fluid),
            "fluid_bounds_m": fluid_bounds,
            "bound_bounds_m": bound_bounds,
            "maximum_grid_residual": float(grid_residual.max()),
            "closed_wall_clearances_m": clearances,
            "separator_x_clearance_m": float(fluid[:, 0].min() - separator_high[0]),
        },
        "continuous_contract": {
            "reservoir_low_m": contract["reservoir_low_m"],
            "reservoir_high_m": contract["reservoir_high_m"],
            "reservoir_volume_m3": contract["reservoir_volume_m3"],
            "reservoir_mass_kg": contract["reservoir_mass_kg"],
            "cell_counts_xyz": contract["expected_center_counts_xyz"],
            "cell_volume_m3": dp**3,
            "quadrature_mass_error_kg": float(len(fluid) * mass_fluid - contract["expected_native_mass_kg"]),
        },
        "source_hashes": {
            "gencase_out": sha256(out_path),
            "fluid_vtk": sha256(fluid_vtk),
            "bound_vtk": sha256(bound_vtk),
            "generated_xml": sha256(generated_xml),
            "native_bi4": sha256(bi4),
            "metadata": sha256(metadata_path),
        },
        "limitations": [
            "This is a GenCase initial occupancy and finite-wall geometry preflight only.",
            "It does not launch a solver, establish complete event coverage, or assess Q-N.",
            "Open top remains a physical free surface; no birth/exit ledger is inferred from it.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gencase-root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.gencase_root, args.metadata, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(report["checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
