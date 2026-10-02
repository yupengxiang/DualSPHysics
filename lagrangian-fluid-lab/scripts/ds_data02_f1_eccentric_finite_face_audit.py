#!/usr/bin/env python3
"""Audit finite interior coverage of the F1 eccentric-obstacle reference walls.

The audit reads only immutable GenCase ``Bound.vtk`` files.  It samples every
declared physical face on a grid whose spacing is no larger than ``dp`` and
uses the shared finite-face helper's half-cell-diagonal allowance.  This is a
native boundary-population check; it does not inspect HDF5 trajectories,
solver normals, or grant Q-N.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Callable


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def load_finite_faces_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("ds_data02_finite_faces_v1", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load finite-face helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def face_definitions() -> dict[str, dict[str, Any]]:
    # Tangential bounds are the continuous physical surfaces.  The obstacle
    # bottom is coincident with the tank floor, so the five obstacle faces are
    # its two x sides, two y sides, and top z face.
    return {
        "outer_x_low": {
            "axis": 0,
            "plane": 0.0,
            "low": [0.0, 0.0],
            "high": [0.67, 0.4],
        },
        "outer_x_high": {
            "axis": 0,
            "plane": 1.6,
            "low": [0.0, 0.0],
            "high": [0.67, 0.4],
        },
        "outer_y_low": {
            "axis": 1,
            "plane": 0.0,
            "low": [0.0, 0.0],
            "high": [1.6, 0.4],
        },
        "outer_y_high": {
            "axis": 1,
            "plane": 0.67,
            "low": [0.0, 0.0],
            "high": [1.6, 0.4],
        },
        "outer_z_low": {
            "axis": 2,
            "plane": 0.0,
            "low": [0.0, 0.0],
            "high": [1.6, 0.67],
        },
        "obstacle_x_low": {
            "axis": 0,
            "plane": 0.9,
            "low": [0.24, 0.0],
            "high": [0.36, 0.45],
        },
        "obstacle_x_high": {
            "axis": 0,
            "plane": 1.02,
            "low": [0.24, 0.0],
            "high": [0.36, 0.45],
        },
        "obstacle_y_low": {
            "axis": 1,
            "plane": 0.24,
            "low": [0.9, 0.0],
            "high": [1.02, 0.45],
        },
        "obstacle_y_high": {
            "axis": 1,
            "plane": 0.36,
            "low": [0.9, 0.0],
            "high": [1.02, 0.45],
        },
        "obstacle_z_high": {
            "axis": 2,
            "plane": 0.45,
            "low": [0.9, 0.24],
            "high": [1.02, 0.36],
        },
    }


def audit_case(case: dict[str, Any], face_coverage: Callable[..., dict[str, Any]], bound_vtk_points: Callable[..., Any]) -> dict[str, Any]:
    source = Path(case["bound_vtk"])
    before = digest(source)
    points, particle_types = bound_vtk_points(source)
    selected = (particle_types == 0) | (particle_types == 1)
    selected_points = points[selected]
    faces = face_definitions()
    result_faces: dict[str, dict[str, Any]] = {}
    for name, definition in faces.items():
        result_faces[name] = face_coverage(
            selected_points,
            normal_axis=definition["axis"],
            plane_m=definition["plane"],
            tangential_low_m=definition["low"],
            tangential_high_m=definition["high"],
            dp_m=float(case["dp_m"]),
        )
    after = digest(source)
    if before != after:
        raise RuntimeError(f"immutable Bound.vtk changed during audit: {source}")
    outer_names = [name for name in faces if name.startswith("outer_")]
    obstacle_names = [name for name in faces if name.startswith("obstacle_")]
    return {
        "case_id": case["case_id"],
        "resolution": case["resolution"],
        "dp_m": case["dp_m"],
        "source": str(source),
        "source_sha256_before": before,
        "source_sha256_after": after,
        "source_unchanged": before == after,
        "source_point_count": int(len(points)),
        "selected_boundary_point_count": int(len(selected_points)),
        "selected_particle_types": [0, 1],
        "coverage_method": {
            "helper": "ds_data02_finite_faces_v1.face_coverage",
            "surface_sampling_spacing_at_most_dp": True,
            "includes_interior_edges_and_corners": True,
            "acceptance_radius": "sqrt(3)*dp/2 plus serialization tolerance",
            "aabb_edge_only": False,
        },
        "outer_faces": {name: result_faces[name] for name in outer_names},
        "obstacle_faces": {name: result_faces[name] for name in obstacle_names},
        "all_five_outer_faces_covered": all(result_faces[name]["covered"] for name in outer_names),
        "all_five_obstacle_faces_covered": all(result_faces[name]["covered"] for name in obstacle_names),
        "normal_vectors_checked": False,
        "q_n_status": "not_assessed",
        "production_approval": "none",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--finite-faces-helper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = json.loads(args.manifest.read_text())
    helper = load_finite_faces_module(args.finite_faces_helper)
    rows = list(manifest["reference_cases"])
    event = manifest.get("event_reference")
    if event:
        rows.append({**event, "resolution": "fine_dense_save", "dp_m": 0.01})
    audited = [audit_case(row, helper.face_coverage, helper.bound_vtk_points) for row in rows]
    result = {
        "schema": "ds02.f1.eccentric-finite-face-audit.v1",
        "family_id": manifest["family_id"],
        "mechanism_id": manifest["mechanism_id"],
        "continuous_geometry": manifest["continuous_geometry"],
        "cases": audited,
        "all_cases_source_unchanged": all(row["source_unchanged"] for row in audited),
        "all_cases_outer_five_covered": all(row["all_five_outer_faces_covered"] for row in audited),
        "all_cases_obstacle_five_covered": all(row["all_five_obstacle_faces_covered"] for row in audited),
        "q_n_status": "not_assessed",
        "production_approval": "none",
        "limitations": [
            "This samples finite physical surfaces from native Bound.vtk particle support, rather than checking only AABB edges.",
            "It does not validate solver-computed normal vectors, hydrodynamic accuracy, trajectory events, or Q-N.",
            "The audit intentionally does not open or hash any trajectory HDF5 file.",
        ],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "all_cases_outer_five_covered": result["all_cases_outer_five_covered"],
        "all_cases_obstacle_five_covered": result["all_cases_obstacle_five_covered"],
        "q_n_status": result["q_n_status"],
    }))


if __name__ == "__main__":
    main()
