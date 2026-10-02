#!/usr/bin/env python3
"""Attribute missing initial mDBC normal data in the F1 finite-center case.

This is a read-only audit of the initial ``CfgInit_Normals*.vtk`` files written
by the solver.  The VTK files contain finite ``Normal`` and ``NormalSize``
arrays, but a zero ``NormalSize`` is the native representation of no normal
data.  The audit keeps that distinction explicit and maps those rows back to
the typed native boundary populations and the finite physical faces declared
by the F1 GenCase XML.

The audit does not repair the XML, regenerate a case, launch a solver, infer a
normal from a nearby layer, or grant Q-N/production status.  A face row can
have non-zero support elsewhere while still containing a missing-normal
layer; the report records both the total candidate rows and the unique
surface attribution so edge/vertex overlaps cannot be counted as a second
failure.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import resource
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))


SCHEMA = "ds02.f1.finite-center.initial-normal-attribution.v1"
AXES = ("x", "y", "z")
DEFAULT_NORMAL_SIZE_TOLERANCE = 1.0e-8

# These are the continuous physical faces in F1's GeometryForNormals.  The
# outer ``all^top`` has five faces (the top is the open free surface); the
# separator ``all^bottom`` has four side faces (its bottom is intentionally
# excluded).  Values are copied from the immutable generated XML semantics,
# not inferred from extrema of this VTK file.
FACE_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "outer_x_low", "population": "outer_wall", "mk": 10,
     "axis": 0, "target": 0.0, "tangent": (1, 2),
     "low": (-0.005, -0.005), "high": (1.005, 1.0)},
    {"name": "outer_x_high", "population": "outer_wall", "mk": 10,
     "axis": 0, "target": 3.23, "tangent": (1, 2),
     "low": (-0.005, -0.005), "high": (1.005, 1.0)},
    {"name": "outer_y_low", "population": "outer_wall", "mk": 10,
     "axis": 1, "target": -0.005, "tangent": (0, 2),
     "low": (0.0, -0.005), "high": (3.23, 1.0)},
    {"name": "outer_y_high", "population": "outer_wall", "mk": 10,
     "axis": 1, "target": 1.005, "tangent": (0, 2),
     "low": (0.0, -0.005), "high": (3.23, 1.0)},
    {"name": "outer_z_low", "population": "outer_wall", "mk": 10,
     "axis": 2, "target": -0.005, "tangent": (0, 1),
     "low": (0.0, -0.005), "high": (3.23, 1.005)},
    {"name": "separator_x_low", "population": "separator", "mk": 11,
     "axis": 0, "target": 1.25, "tangent": (1, 2),
     "low": (0.34, 0.0), "high": (0.4, 0.7)},
    {"name": "separator_x_high", "population": "separator", "mk": 11,
     "axis": 0, "target": 2.05, "tangent": (1, 2),
     "low": (0.34, 0.0), "high": (0.4, 0.7)},
    {"name": "separator_y_low", "population": "separator", "mk": 11,
     "axis": 1, "target": 0.34, "tangent": (0, 2),
     "low": (1.25, 0.0), "high": (2.05, 0.7)},
    {"name": "separator_y_high", "population": "separator", "mk": 11,
     "axis": 1, "target": 0.4, "tangent": (0, 2),
     "low": (1.25, 0.0), "high": (2.05, 0.7)},
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _vtk_array(raw: bytes, pattern: bytes, *, width: int, label: str) -> tuple[np.ndarray, re.Match[bytes]]:
    match = re.search(pattern, raw)
    if match is None:
        raise ValueError(f"{label} header not found")
    count = int(match.group(1))
    offset = match.end()
    stop = offset + count * width * 4
    if stop > len(raw):
        raise ValueError(f"{label} payload is truncated")
    array = np.frombuffer(raw, dtype=">f4", count=count * width, offset=offset)
    return array.reshape(count, width).copy(), match


def read_initial_normals_vtk(path: Path) -> dict[str, Any]:
    """Read the binary arrays used by the solver's initial normal report."""

    raw = path.read_bytes()
    points, points_header = _vtk_array(
        raw, rb"POINTS\s+(\d+)\s+float\s*\r?\n", width=3, label="POINTS"
    )
    normals, normal_header = _vtk_array(
        raw, rb"Normal\s+3\s+(\d+)\s+float\s*\r?\n", width=3, label="Normal"
    )
    normal_size, normal_size_header = _vtk_array(
        raw, rb"NormalSize\s+1\s+(\d+)\s+float\s*\r?\n", width=1, label="NormalSize"
    )
    # ``NormalSize`` is a scalar, so flatten the (N, 1) representation.
    normal_size = normal_size[:, 0]
    mk_header = re.search(rb"Mk\s+1\s+(\d+)\s+short\s*\r?\n", raw)
    if mk_header is None:
        raise ValueError("Mk header not found")
    mk_count = int(mk_header.group(1))
    mk_offset = mk_header.end()
    mk_stop = mk_offset + mk_count * 2
    if mk_stop > len(raw):
        raise ValueError("Mk payload is truncated")
    mk = np.frombuffer(raw, dtype=">i2", count=mk_count, offset=mk_offset).copy()

    lengths = {"points": len(points), "normal": len(normals),
               "normal_size": len(normal_size), "mk": len(mk)}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"VTK array lengths differ: {lengths}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "file_size_bytes": len(raw),
        "points": points,
        "normals": normals,
        "normal_size": normal_size,
        "mk": mk,
        "headers": {
            "points_offset": points_header.end(),
            "normal_offset": normal_header.end(),
            "normal_size_offset": normal_size_header.end(),
            "mk_offset": mk_header.end(),
        },
    }


def _fixed_populations(generated_xml: Path) -> dict[int, dict[str, int]]:
    root = ET.parse(generated_xml).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles element")
    populations: dict[int, dict[str, int]] = {}
    for fixed in particles.findall("fixed"):
        mk = int(fixed.attrib["mk"])
        populations[mk] = {
            "mkbound": int(fixed.attrib.get("mkbound", "-1")),
            "begin": int(fixed.attrib.get("begin", "-1")),
            "count": int(fixed.attrib["count"]),
        }
    if not populations:
        raise ValueError("generated XML has no fixed particle population records")
    return populations


def _face_mask(points: np.ndarray, mk: np.ndarray, spec: dict[str, Any], *, tolerance_m: float) -> np.ndarray:
    axis = int(spec["axis"])
    tangent = tuple(int(value) for value in spec["tangent"])
    mask = (mk == int(spec["mk"])) & np.isfinite(points).all(axis=1)
    mask &= np.abs(points[:, axis] - float(spec["target"])) <= tolerance_m
    for index, coordinate in enumerate(tangent):
        mask &= points[:, coordinate] >= float(spec["low"][index]) - tolerance_m
        mask &= points[:, coordinate] <= float(spec["high"][index]) + tolerance_m
    return mask


def _position_bounds(points: np.ndarray) -> list[list[float]] | None:
    if not len(points):
        return None
    return [points.min(axis=0).astype(float).tolist(), points.max(axis=0).astype(float).tolist()]


def _unique_layers(values: np.ndarray, *, digits: int = 8) -> list[dict[str, Any]]:
    if not len(values):
        return []
    rounded = np.round(values.astype(np.float64), digits)
    unique, counts = np.unique(rounded, return_counts=True)
    order = np.argsort(unique)
    return [{"coordinate_m": float(unique[i]), "count": int(counts[i])} for i in order]


def _surface_rows(
    points: np.ndarray,
    mk: np.ndarray,
    missing: np.ndarray,
    *,
    tolerance_m: float,
) -> tuple[list[dict[str, Any]], Counter[tuple[str, ...]]]:
    masks: dict[str, np.ndarray] = {
        str(spec["name"]): _face_mask(points, mk, spec, tolerance_m=tolerance_m)
        for spec in FACE_SPECS
    }
    membership: Counter[tuple[str, ...]] = Counter()
    for index in np.flatnonzero(missing):
        names = tuple(name for name, mask in masks.items() if bool(mask[index]))
        membership[names] += 1

    rows: list[dict[str, Any]] = []
    for spec in FACE_SPECS:
        name = str(spec["name"])
        mask = masks[name]
        zero = mask & missing
        exclusive = int(membership.get((name,), 0))
        shared = int(zero.sum()) - exclusive
        zero_points = points[zero]
        nonzero = mask & ~missing
        rows.append({
            "name": name,
            "population": str(spec["population"]),
            "mk": int(spec["mk"]),
            "axis": AXES[int(spec["axis"])],
            "declared_plane_m": float(spec["target"]),
            "candidate_tolerance_m": float(tolerance_m),
            "candidate_point_count": int(mask.sum()),
            "candidate_missing_normal_count": int(zero.sum()),
            "candidate_nonzero_normal_count": int(nonzero.sum()),
            "candidate_missing_fraction": float(zero.sum() / mask.sum()) if mask.sum() else None,
            "exclusive_missing_normal_count": exclusive,
            "shared_edge_or_vertex_missing_normal_count": shared,
            "missing_position_bounds_m": _position_bounds(zero_points),
            "missing_coordinate_layers_m": _unique_layers(zero_points[:, int(spec["axis"])] if len(zero_points) else np.empty(0)),
            "normal_coverage_interpretation": (
                "missing normal data occurs on this face's candidate boundary rows"
                if zero.any() else "no missing normal data on candidate rows"
            ),
        })
    return rows, membership


def _population_rows(mk: np.ndarray, missing: np.ndarray) -> list[dict[str, Any]]:
    rows = []
    for value in np.unique(mk):
        population = "outer_wall" if int(value) == 10 else "separator" if int(value) == 11 else "unknown"
        mask = mk == value
        rows.append({
            "mk": int(value),
            "population": population,
            "point_count": int(mask.sum()),
            "missing_normal_count": int((mask & missing).sum()),
            "nonzero_normal_count": int((mask & ~missing).sum()),
            "missing_fraction": float((mask & missing).sum() / mask.sum()) if mask.sum() else None,
        })
    return rows


def _read_runtime_warning(run_out: Path | None) -> dict[str, Any] | None:
    if run_out is None:
        return None
    text = run_out.read_text(errors="replace")
    lines = [line.strip() for line in text.splitlines() if "without normal data" in line.lower()]
    return {
        "path": str(run_out),
        "read_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_size_bytes_at_read": run_out.stat().st_size,
        "warning_lines": lines,
        "warning_line_count": len(lines),
        "hash_bound": False,
        "interpretation": "live solver log observation; changing output is intentionally not input-hashed",
    }


def _rusage() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "self_user_seconds": float(usage.ru_utime),
        "self_system_seconds": float(usage.ru_stime),
        "children_user_seconds": float(children.ru_utime),
        "children_system_seconds": float(children.ru_stime),
        "combined_user_seconds": float(usage.ru_utime + children.ru_utime),
        "combined_system_seconds": float(usage.ru_stime + children.ru_stime),
        "max_rss_kib_self": float(usage.ru_maxrss),
        "max_rss_kib_children": float(children.ru_maxrss),
    }


def audit(
    *,
    normals: Path,
    normals_ghost: Path,
    generated_xml: Path,
    generated_bi4: Path,
    bound_vtk: Path,
    output: Path,
    dp_m: float = 0.01,
    run_out: Path | None = None,
    normal_size_tolerance: float = DEFAULT_NORMAL_SIZE_TOLERANCE,
) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    before = _rusage()
    primary = read_initial_normals_vtk(normals)
    ghost = read_initial_normals_vtk(normals_ghost)
    points = primary["points"]
    normal = primary["normals"]
    normal_size = primary["normal_size"]
    mk = primary["mk"]
    ghost_missing = ghost["normal_size"] <= normal_size_tolerance
    missing = normal_size <= normal_size_tolerance
    if not np.array_equal(points, ghost["points"]):
        raise ValueError("CfgInit_Normals and CfgInit_NormalsGhost point arrays differ")
    if not np.array_equal(mk, ghost["mk"]):
        raise ValueError("CfgInit_Normals and CfgInit_NormalsGhost Mk arrays differ")
    if not np.array_equal(missing, ghost_missing):
        raise ValueError("normal-data masks differ between normal and ghost VTK")

    populations = _fixed_populations(generated_xml)
    xml_counts = {int(mk_value): int(data["count"]) for mk_value, data in populations.items()}
    vtk_counts = {int(value): int((mk == value).sum()) for value in np.unique(mk)}
    if any(xml_counts.get(value) != count for value, count in vtk_counts.items()):
        raise ValueError(f"fixed population counts differ: xml={xml_counts}, vtk={vtk_counts}")

    tolerance_m = float(dp_m / 2.0 + 1.0e-7)
    surface_rows, membership = _surface_rows(points, mk, missing, tolerance_m=tolerance_m)
    normal_magnitude = np.linalg.norm(normal.astype(np.float64), axis=1)
    exact_zero_vector = normal_magnitude == 0.0
    near_zero_vector = normal_magnitude <= normal_size_tolerance
    zero_values = normal_size[missing]
    dominant = sorted(
        (row for row in surface_rows if row["exclusive_missing_normal_count"] > 0),
        key=lambda row: row["exclusive_missing_normal_count"], reverse=True,
    )
    runtime_warning = _read_runtime_warning(run_out)
    after = _rusage()
    report = {
        "schema": SCHEMA,
        "case_id": generated_xml.stem,
        "physical_case_id": "F1_DUAL_FINITE_CENTER_QUADRATURE",
        "claim_boundary": "Initial native normal-data attribution only; no solver acceptance, Q-N, or production qualification.",
        "source_hashes": {
            "cfg_init_normals_vtk": primary["sha256"],
            "cfg_init_normals_ghost_vtk": ghost["sha256"],
            "generated_xml": sha256(generated_xml),
            "generated_bi4": sha256(generated_bi4),
            "bound_vtk": sha256(bound_vtk),
        },
        "source_paths": {
            "cfg_init_normals_vtk": str(normals),
            "cfg_init_normals_ghost_vtk": str(normals_ghost),
            "generated_xml": str(generated_xml),
            "generated_bi4": str(generated_bi4),
            "bound_vtk": str(bound_vtk),
        },
        "native_arrays": {
            "point_count": int(len(points)),
            "fixed_population_counts_from_xml": {str(k): v["count"] for k, v in populations.items()},
            "fixed_population_counts_from_vtk_mk": {str(k): v for k, v in sorted(vtk_counts.items())},
            "points_finite": bool(np.isfinite(points).all()),
            "normal_vectors_finite": bool(np.isfinite(normal).all()),
            "normal_size_finite": bool(np.isfinite(normal_size).all()),
            "normal_size_zero_threshold": float(normal_size_tolerance),
            "normal_size_zero_count": int(missing.sum()),
            "normal_size_nonzero_count": int((~missing).sum()),
            "normal_size_zero_min": float(zero_values.min()) if len(zero_values) else None,
            "normal_size_zero_max": float(zero_values.max()) if len(zero_values) else None,
            "normal_vector_exact_zero_count": int(exact_zero_vector.sum()),
            "normal_vector_near_zero_count": int(near_zero_vector.sum()),
            "normal_vector_near_zero_max_m": float(normal_magnitude[near_zero_vector].max()) if near_zero_vector.any() else None,
            "normal_vector_nonzero_count": int((~exact_zero_vector).sum()),
            "ghost_normal_size_zero_count": int(ghost_missing.sum()),
            "ghost_normal_vectors_finite": bool(np.isfinite(ghost["normals"]).all()),
            "normal_and_ghost_missing_masks_equal": bool(np.array_equal(missing, ghost_missing)),
        },
        "typed_population_attribution": _population_rows(mk, missing),
        "finite_face_attribution": {
            "candidate_tolerance_m": tolerance_m,
            "faces": surface_rows,
            "zero_normal_membership_histogram": [
                {"faces": list(names), "count": int(count)}
                for names, count in sorted(membership.items(), key=lambda item: (-item[1], item[0]))
            ],
            "dominant_exclusive_missing_faces": [
                {
                    "face": row["name"],
                    "population": row["population"],
                    "mk": row["mk"],
                    "exclusive_missing_normal_count": row["exclusive_missing_normal_count"],
                    "total_candidate_missing_normal_count": row["candidate_missing_normal_count"],
                    "candidate_nonzero_normal_count": row["candidate_nonzero_normal_count"],
                    "missing_coordinate_layers_m": row["missing_coordinate_layers_m"],
                    "missing_position_bounds_m": row["missing_position_bounds_m"],
                }
                for row in dominant
            ],
            "interpretation": (
                "A dominant face is attributed only from the typed Mk population, declared physical plane, "
                "and native zero-NormalSize rows. Nearby nonzero layers do not repair the missing rows. "
                "Shared edge/vertex rows are listed in the membership histogram and are not counted as a second face failure."
            ),
        },
        "runtime_warning_observation": runtime_warning,
        "checks": {
            "xml_and_vtk_fixed_counts_match": True,
            "initial_points_finite": bool(np.isfinite(points).all()),
            "initial_normal_arrays_finite": bool(np.isfinite(normal).all() and np.isfinite(normal_size).all()),
            "normal_and_ghost_masks_match": bool(np.array_equal(missing, ghost_missing)),
            "missing_normal_data_present": bool(missing.any()),
            "two_dominant_missing_faces_observed": bool({row["name"] for row in dominant[:2]} >= {"outer_x_low", "separator_y_high"}),
        },
        "resource_usage": {"before": before, "after": after},
        "limitations": [
            "The VTK Normal field is finite even when NormalSize is zero or only a 1e-9 float residual; NormalSize threshold is the native absence test.",
            "Face attribution uses declared GeometryForNormals planes and a half-dp candidate window; it does not infer a new normal or prove solver-time wall behavior.",
            "The live Run.out observation is intentionally not hash-bound; immutable source hashes cover the XML, BI4, Bound.vtk, and both initial normal VTK files.",
        ],
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normals", type=Path, required=True)
    parser.add_argument("--normals-ghost", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--generated-bi4", type=Path, required=True)
    parser.add_argument("--bound-vtk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dp", type=float, default=0.01)
    parser.add_argument("--run-out", type=Path)
    parser.add_argument("--normal-size-tolerance", type=float, default=DEFAULT_NORMAL_SIZE_TOLERANCE)
    args = parser.parse_args()
    report = audit(
        normals=args.normals,
        normals_ghost=args.normals_ghost,
        generated_xml=args.generated_xml,
        generated_bi4=args.generated_bi4,
        bound_vtk=args.bound_vtk,
        output=args.output,
        dp_m=args.dp,
        run_out=args.run_out,
        normal_size_tolerance=args.normal_size_tolerance,
    )
    print(json.dumps({
        "schema": report["schema"],
        "normal_size_zero_count": report["native_arrays"]["normal_size_zero_count"],
        "typed_population_attribution": report["typed_population_attribution"],
        "dominant_exclusive_missing_faces": report["finite_face_attribution"]["dominant_exclusive_missing_faces"],
        "q_n_status": report["q_n_status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
