#!/usr/bin/env python3
"""Verify the F1 normal-geometry phase coincidence before a second repair.

This is a read-only preflight.  It compares the actual ``*_hdp_Actual.vtk``
planes from the distanceh=3 GenCase output with the missing native normal
layers recorded by the completed hard-gate audit.  It never infers a normal,
changes a definition, regenerates GenCase, or launches a solver.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import resource
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

SCHEMA = "ds02.f1.finite-center.normal-plane-phase-preflight.v1"
COINCIDENCE_TOLERANCE_M = 2.0e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rusage() -> dict[str, float]:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "self_user_seconds": float(self_usage.ru_utime),
        "self_system_seconds": float(self_usage.ru_stime),
        "children_user_seconds": float(child_usage.ru_utime),
        "children_system_seconds": float(child_usage.ru_stime),
        "combined_user_seconds": float(self_usage.ru_utime + child_usage.ru_utime),
        "combined_system_seconds": float(self_usage.ru_stime + child_usage.ru_stime),
        "max_rss_kib_self": float(self_usage.ru_maxrss),
        "max_rss_kib_children": float(child_usage.ru_maxrss),
    }


def read_binary_vtk_points(path: Path) -> np.ndarray:
    """Read only the legacy binary VTK POINTS block."""

    raw = path.read_bytes()
    match = re.search(rb"POINTS\s+(\d+)\s+float\r?\n", raw)
    if match is None:
        raise ValueError(f"{path}: POINTS float header not found")
    count = int(match.group(1))
    start = match.end()
    stop = start + count * 3 * 4
    if stop > len(raw):
        raise ValueError(f"{path}: truncated POINTS payload")
    points = np.frombuffer(raw, dtype=">f4", count=count * 3, offset=start)
    return points.astype(np.float64, copy=False).reshape(count, 3)


def _definition_semantics(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    normal_list = root.find("./casedef/geometry/commands/list[@name='GeometryForNormals']")
    if normal_list is None:
        raise ValueError(f"{path}: GeometryForNormals missing")
    draws = normal_list.findall("drawbox")
    if len(draws) != 2:
        raise ValueError(f"{path}: expected two normal drawboxes, found {len(draws)}")
    layers = [draw.find("layers") for draw in draws]
    if any(layer is None for layer in layers):
        raise ValueError(f"{path}: normal drawbox layer declaration missing")
    point_rows = []
    for draw in draws:
        point = draw.find("point")
        endpoint = draw.find("endpoint")
        if point is None or endpoint is None:
            raise ValueError(f"{path}: normal drawbox bounds missing")
        point_rows.append({
            "point_m": [float(point.attrib[axis]) for axis in ("x", "y", "z")],
            "endpoint_m": [float(endpoint.attrib[axis]) for axis in ("x", "y", "z")],
        })
    return {
        "outer_vdp": layers[0].attrib.get("vdp"),
        "separator_vdp": layers[1].attrib.get("vdp"),
        "normal_drawboxes": point_rows,
        "distanceh": root.find("./casedef/normals/norgeometry/distanceh").attrib.get("v"),
        "svshapes": root.find("./casedef/normals/norgeometry/svshapes").attrib.get("v"),
    }


def _axis_plane(points: np.ndarray, *, axis: int, population: str) -> dict[str, Any]:
    if population == "outer":
        mask = (
            (points[:, 0] <= 0.01)
            | (points[:, 0] >= 3.22)
            | (points[:, 1] <= 0.01)
            | (points[:, 1] >= 0.99)
            | (points[:, 2] <= 0.01)
            | (points[:, 2] >= 0.99)
        )
    elif population == "separator":
        mask = (
            (points[:, 0] >= 1.20) & (points[:, 0] <= 2.10)
            & (points[:, 1] >= 0.30) & (points[:, 1] <= 0.42)
            & (points[:, 2] >= -0.01) & (points[:, 2] <= 0.71)
        )
    else:
        raise ValueError(population)
    values = points[mask, axis]
    if len(values) == 0:
        raise ValueError(f"no {population} points available for axis {axis}")
    unique = np.unique(np.round(values, 8))
    return {
        "population": population,
        "axis": "xyz"[axis],
        "point_count": int(len(values)),
        "min_m": float(values.min()),
        "max_m": float(values.max()),
        "unique_planes_m": [float(value) for value in unique],
    }


def _plane_for_face(points: np.ndarray, face: str) -> dict[str, Any]:
    mapping = {
        "outer_x_low": ("outer", 0, "min_m"), "outer_x_high": ("outer", 0, "max_m"),
        "outer_y_low": ("outer", 1, "min_m"), "outer_y_high": ("outer", 1, "max_m"),
        "outer_z_low": ("outer", 2, "min_m"),
        "separator_x_low": ("separator", 0, "min_m"), "separator_x_high": ("separator", 0, "max_m"),
        "separator_y_low": ("separator", 1, "min_m"), "separator_y_high": ("separator", 1, "max_m"),
        "separator_z_high": ("separator", 2, "max_m"),
    }
    population, axis, bound = mapping[face]
    summary = _axis_plane(points, axis=axis, population=population)
    summary["face"] = face
    summary["actual_plane_m"] = summary[bound]
    return summary


def _face_physical_targets(definition: dict[str, Any]) -> dict[str, float]:
    outer, separator = definition["normal_drawboxes"]
    op, oe = outer["point_m"], outer["endpoint_m"]
    sp, se = separator["point_m"], separator["endpoint_m"]
    return {
        "outer_x_low": op[0], "outer_x_high": oe[0],
        "outer_y_low": op[1], "outer_y_high": oe[1], "outer_z_low": op[2],
        "separator_x_low": sp[0], "separator_x_high": se[0],
        "separator_y_low": sp[1], "separator_y_high": se[1],
        "separator_z_high": se[2],
    }


def preflight(*, definition_path: Path, hdp_path: Path, prior_result_path: Path, output: Path) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    before = _rusage()
    definition = _definition_semantics(definition_path)
    prior = json.loads(prior_result_path.read_text())
    faces = prior["native_result"]["finite_face_attribution"]
    hdp_points = read_binary_vtk_points(hdp_path)
    physical_targets = _face_physical_targets(definition)
    rows = []
    for face in faces:
        name = face["name"]
        actual = _plane_for_face(hdp_points, name)
        residual_layers = [float(row["coordinate_m"]) for row in face["residual_coordinate_layers_m"]]
        coincidences = [
            {"residual_layer_m": value, "delta_to_actual_plane_m": float(value - actual["actual_plane_m"]), "coincident": abs(value - actual["actual_plane_m"]) <= COINCIDENCE_TOLERANCE_M}
            for value in residual_layers
        ]
        rows.append({
            "face": name,
            "population": face["population"],
            "current_vdp": definition["outer_vdp"] if face["population"] == "outer_wall" else definition["separator_vdp"],
            "declared_physical_plane_m": physical_targets[name],
            "actual_hdp_plane": actual,
            "missing_residual_layers_m": residual_layers,
            "phase_coincidences": coincidences,
            "any_phase_coincidence_confirmed": any(item["coincident"] for item in coincidences),
            "actual_plane_offset_from_declared_physical_m": float(actual["actual_plane_m"] - physical_targets[name]),
        })
    report = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_boundary": "Read-only phase-coincidence diagnosis; no repair, solver, Q-N, or production claim.",
        "inputs": {
            "definition_path": str(definition_path),
            "definition_sha256": sha256(definition_path),
            "hdp_path": str(hdp_path),
            "hdp_sha256": sha256(hdp_path),
            "prior_result_path": str(prior_result_path),
            "prior_result_sha256": sha256(prior_result_path),
        },
        "definition": definition,
        "hdp_actual": {
            "point_count": int(len(hdp_points)),
            "bounds_m": [hdp_points.min(axis=0).astype(float).tolist(), hdp_points.max(axis=0).astype(float).tolist()],
            "unique_axis_values_m": {axis: [float(value) for value in np.unique(np.round(hdp_points[:, index], 8))] for index, axis in enumerate("xyz")},
        },
        "face_analysis": rows,
        "decision": {
            "current_vdp_phase_coincidence_confirmed": bool(any(row["any_phase_coincidence_confirmed"] for row in rows)),
            "outer_x_low_and_separator_y_high_confirmed": bool(all(next(row for row in rows if row["face"] == name)["any_phase_coincidence_confirmed"] for name in ("outer_x_low", "separator_y_high"))),
            "candidate_hypothesis": "Set only GeometryForNormals outer and separator layers to vdp=0, which targets the declared physical planes while preserving mainlist/native fluid geometry.",
            "candidate_change_authorized_by_evidence": bool(all(next(row for row in rows if row["face"] == name)["any_phase_coincidence_confirmed"] for name in ("outer_x_low", "separator_y_high"))),
        },
        "resource_usage": {"before": before, "after": _rusage()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--hdp", type=Path, required=True)
    parser.add_argument("--prior-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = preflight(definition_path=args.definition, hdp_path=args.hdp, prior_result_path=args.prior_result, output=args.output)
    print(json.dumps(report["decision"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
