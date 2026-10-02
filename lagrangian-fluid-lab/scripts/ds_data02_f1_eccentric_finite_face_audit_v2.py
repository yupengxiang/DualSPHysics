#!/usr/bin/env python3
"""F1 ECC finite-face audit v2 with the obstacle-floor intersection removed.

The v1 audit intentionally remains as negative evidence.  In v2 the tank
floor is decomposed into four exposed rectangular patches around the
eccentric obstacle footprint; the coincident obstacle bottom is not demanded
to contain tank-wall particles.  All other face checks use the shared
finite-face sampler unchanged.
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


def face_definitions() -> dict[str, list[dict[str, Any]]]:
    # Tangential bounds are physical surfaces.  The floor is exposed only
    # outside the obstacle footprint x=[.9,1.02], y=[.24,.36].
    return {
        "outer_x_low": [{"axis": 0, "plane": 0.0, "low": [0.0, 0.0], "high": [0.67, 0.4]}],
        "outer_x_high": [{"axis": 0, "plane": 1.6, "low": [0.0, 0.0], "high": [0.67, 0.4]}],
        "outer_y_low": [{"axis": 1, "plane": 0.0, "low": [0.0, 0.0], "high": [1.6, 0.4]}],
        "outer_y_high": [{"axis": 1, "plane": 0.67, "low": [0.0, 0.0], "high": [1.6, 0.4]}],
        "outer_z_low": [
            {"axis": 2, "plane": 0.0, "low": [0.0, 0.0], "high": [0.9, 0.67]},
            {"axis": 2, "plane": 0.0, "low": [1.02, 0.0], "high": [1.6, 0.67]},
            {"axis": 2, "plane": 0.0, "low": [0.9, 0.0], "high": [1.02, 0.24]},
            {"axis": 2, "plane": 0.0, "low": [0.9, 0.36], "high": [1.02, 0.67]},
        ],
        "obstacle_x_low": [{"axis": 0, "plane": 0.9, "low": [0.24, 0.0], "high": [0.36, 0.45]}],
        "obstacle_x_high": [{"axis": 0, "plane": 1.02, "low": [0.24, 0.0], "high": [0.36, 0.45]}],
        "obstacle_y_low": [{"axis": 1, "plane": 0.24, "low": [0.9, 0.0], "high": [1.02, 0.45]}],
        "obstacle_y_high": [{"axis": 1, "plane": 0.36, "low": [0.9, 0.0], "high": [1.02, 0.45]}],
        "obstacle_z_high": [{"axis": 2, "plane": 0.45, "low": [0.9, 0.24], "high": [1.02, 0.36]}],
    }


def aggregate_patch_results(patches: list[dict[str, Any]], definitions: list[dict[str, Any]]) -> dict[str, Any]:
    worst_patch = max(enumerate(patches), key=lambda item: item[1]["maximum_distance_m"] or -1)
    return {
        "patches": patches,
        "patch_count": len(patches),
        "physical_surface_samples": sum(item["physical_surface_samples"] for item in patches),
        "native_near_plane_points_sum": sum(item["native_near_plane_points"] for item in patches),
        "uncovered_surface_samples": sum(item["uncovered_surface_samples"] for item in patches),
        "maximum_distance_m": worst_patch[1]["maximum_distance_m"],
        "worst_patch_index": worst_patch[0],
        "worst_physical_point_m": worst_patch[1]["worst_physical_point_m"],
        "covered": all(item["covered"] for item in patches),
        "physical_face_definition": definitions,
    }


def audit_case(case: dict[str, Any], face_coverage: Callable[..., dict[str, Any]], bound_vtk_points: Callable[..., Any]) -> dict[str, Any]:
    source = Path(case["bound_vtk"])
    before = digest(source)
    points, particle_types = bound_vtk_points(source)
    selected = (particle_types == 0) | (particle_types == 1)
    selected_points = points[selected]
    result_faces: dict[str, dict[str, Any]] = {}
    for name, definitions in face_definitions().items():
        patches = [
            face_coverage(
                selected_points,
                normal_axis=definition["axis"],
                plane_m=definition["plane"],
                tangential_low_m=definition["low"],
                tangential_high_m=definition["high"],
                dp_m=float(case["dp_m"]),
            )
            for definition in definitions
        ]
        result_faces[name] = aggregate_patch_results(patches, definitions)
    after = digest(source)
    if before != after:
        raise RuntimeError(f"immutable Bound.vtk changed during audit: {source}")
    outer_names = [name for name in result_faces if name.startswith("outer_")]
    obstacle_names = [name for name in result_faces if name.startswith("obstacle_")]
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
        "faces": result_faces,
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
        "schema": "ds02.f1.eccentric-finite-face-audit.v2",
        "family_id": manifest["family_id"],
        "mechanism_id": manifest["mechanism_id"],
        "continuous_geometry": manifest["continuous_geometry"],
        "cases": audited,
        "all_cases_source_unchanged": all(row["source_unchanged"] for row in audited),
        "all_cases_outer_five_covered": all(row["all_five_outer_faces_covered"] for row in audited),
        "all_cases_obstacle_five_covered": all(row["all_five_obstacle_faces_covered"] for row in audited),
        "floor_intersection_treatment": "outer z=0 is four exposed patches outside obstacle x=[0.9,1.02], y=[0.24,0.36]; obstacle bottom is coincident with tank floor",
        "q_n_status": "not_assessed",
        "production_approval": "none",
        "limitations": [
            "Finite physical surfaces are sampled through the shared helper at spacing no larger than dp, including patch interiors, edges and corners.",
            "This checks native Bound.vtk particle support only; solver normal vectors, hydrodynamic accuracy, trajectory events and Q-N remain separate.",
            "No trajectory HDF5 is opened or hashed by this audit.",
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
