#!/usr/bin/env python3
"""Typed-state audit for PartVTK's mass-bearing stats sidecar.

PartVTK's ``initial_all.csv`` has type and coordinates but no mass column;
``initial_stats_stats.csv`` records the per-particle mass.  This additive
wrapper combines those two immutable outputs, retaining the type-2 particle
mass sum as a separate field from the native ``massbody`` contract.
"""

from __future__ import annotations

import csv
import importlib.util
import math
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V6 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v6.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v6", V6)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load PartVTK wrapper: {V6}")
MODULE_V6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V6)
MODULE = MODULE_V6.MODULE
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.commensurate_mother.partvtk_002.audit.v1"


def _column(header: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        if name in header:
            return header.index(name)
    for i, cell in enumerate(header):
        if any(name in cell for name in names):
            return i
    return None


def _stats_particle_mass(csv_path: Path) -> tuple[float, str]:
    stats_path = csv_path.with_name(csv_path.name.replace("_initial_all.csv", "_initial_stats_stats.csv"))
    rows = list(csv.reader(stats_path.read_text(encoding="utf-8", errors="replace").splitlines()))
    header_index = next((i for i, row in enumerate(rows) if row and any("mass_mean" in cell.lower() for cell in row)), None)
    if header_index is None:
        raise ValueError(f"PartVTK mass stats header not found: {stats_path}")
    header = [cell.strip().lower() for cell in rows[header_index]]
    mass_col = _column(header, ("mass_mean",))
    if mass_col is None:
        raise ValueError(f"PartVTK mass stats column not found: {stats_path}")
    for row in rows[header_index + 1:]:
        if len(row) <= mass_col:
            continue
        try:
            value = float(row[mass_col])
        except ValueError:
            continue
        if math.isfinite(value) and value > 0:
            return value, str(stats_path.resolve())
    raise ValueError(f"PartVTK mass stats data not found: {stats_path}")


def _partvtk_counts(csv_path: Path) -> dict[str, object]:
    rows = list(csv.reader(csv_path.read_text(encoding="utf-8", errors="replace").splitlines()))
    header_index = next((i for i, row in enumerate(rows) if row and any("type" in cell.lower() for cell in row)), None)
    if header_index is None:
        raise ValueError(f"PartVTK CSV type header not found: {csv_path}")
    header = [cell.strip().lower() for cell in rows[header_index]]
    type_col = _column(header, ("type",))
    x_col, y_col, z_col = (_column(header, (axis,)) for axis in ("pos.x", "pos.y", "pos.z"))
    if type_col is None:
        raise ValueError(f"PartVTK CSV type column not found: {header}")
    counts = {key: 0 for key in ("fixed", "moving", "floating", "fluid", "unknown")}
    points: list[tuple[float, float, float]] = []
    for row in rows[header_index + 1:]:
        if not row or len(row) <= type_col:
            continue
        type_value = row[type_col].strip().lower()
        key = {"0": "fixed", "1": "moving", "2": "floating", "3": "fluid", "fixed": "fixed", "moving": "moving", "floating": "floating", "fluid": "fluid"}.get(type_value, "unknown")
        counts[key] += 1
        if x_col is not None and y_col is not None and z_col is not None and len(row) > max(x_col, y_col, z_col):
            try:
                points.append((float(row[x_col]), float(row[y_col]), float(row[z_col])))
            except ValueError:
                pass
    particle_mass, mass_source = _stats_particle_mass(csv_path)
    masses = {key: count * particle_mass for key, count in counts.items()}
    return {
        "header": header,
        "rows_read": len(rows[header_index + 1:]),
        "counts": counts,
        "mass_by_type_kg": masses,
        "particle_mass_kg": particle_mass,
        "mass_source": mass_source,
        "finite_positions": bool(points) and all(math.isfinite(value) for point in points for value in point),
        "point_bounds_m": [[min(point[axis] for point in points), max(point[axis] for point in points)] for axis in range(3)] if points else None,
    }


MODULE._partvtk_counts = _partvtk_counts


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["audit", "make-solver-requests"])
    args = parser.parse_args()
    result = MODULE.audit() if args.action == "audit" else MODULE.make_solver_requests()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
