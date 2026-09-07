#!/usr/bin/env python3
"""Audit the semantic meaning of finite MkCells boundary sidecars.

The finite-triangle sidecar is deliberately generated from ``MkCells.vtk``.
That file is sufficient to prevent an *infinite-plane* wall assumption, but it
does not by itself say which logical faces were requested by the GenCase
definition.  In particular, a box with an open top can still contain narrow
boundary-particle rim caps around that top edge.  This audit keeps those two
levels separate:

* ``boxfill`` is the declared logical geometry (closed/open faces);
* VTK cells are the generated particle-shell geometry (including edge caps);
* sidecar labels are checked against the generated ``Type``/``Mk`` mapping.

The result is an engineering/semantic audit, not a physical validation.  It
intentionally fails the wall-visibility semantic gate when an undeclared face
has substantial generated coverage or when an implicit supporting cap cannot be
explained by an explicit component policy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

import h5py
import numpy as np

try:
    from scripts.boundary_sidecars import boundary_triangles, read_binary_vtk_polydata
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from boundary_sidecars import boundary_triangles, read_binary_vtk_polydata


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
DEFAULT_MANIFEST = LAB / "release" / "v0.1-development" / "manifest.json"
DEFAULT_REPORT = CAMPAIGN / "r3-g2-boundary-semantics.json"

FACE_NAMES = ("bottom", "left", "right", "front", "back", "top")
FACE_AXIS = {
    "left": (0, 0), "right": (0, 1),
    "front": (1, 0), "back": (1, 1),
    "bottom": (2, 0), "top": (2, 1),
}
VTK_TYPE = {"fixed": 0, "moving": 1}


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _attr_text(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.decode()
    return str(value) if value is not None else None


def _vector(element: ET.Element, name: str) -> np.ndarray:
    child = element.find(name)
    if child is None:
        raise ValueError(f"drawbox is missing <{name}>")
    try:
        return np.asarray([float(child.attrib[axis]) for axis in "xyz"], dtype=float)
    except (KeyError, ValueError) as error:
        raise ValueError(f"drawbox <{name}> has invalid xyz coordinates") from error


def parse_definition(path: Path) -> dict[str, Any]:
    """Extract boundary drawboxes and their declared logical face sets."""
    path = Path(path)
    root = ET.parse(path).getroot()
    definition = root.find(".//definition")
    if definition is None or "dp" not in definition.attrib:
        raise ValueError(f"definition lacks particle spacing: {path}")
    mainlist = root.find(".//mainlist")
    if mainlist is None:
        raise ValueError(f"definition lacks geometry mainlist: {path}")

    current: tuple[str, int | None] | None = None
    pending_void = False
    boxes: list[dict[str, Any]] = []
    for child in list(mainlist):
        tag = _tag(child)
        if tag == "setmkbound":
            try:
                mkbound = int(child.attrib["mk"])
            except (KeyError, ValueError) as error:
                raise ValueError(f"invalid setmkbound in {path}") from error
            current = ("boundary", mkbound)
            continue
        elif tag == "setmkvoid":
            current = ("void", None)
            # GenCase uses a void drawbox immediately before the boundary
            # drawbox for a solid insert/obstacle.  Retain that context until
            # the next boundary drawbox instead of treating it as a wall face.
            pending_void = True
            continue
        elif tag == "setmkfluid":
            try:
                current = ("fluid", int(child.attrib["mk"]))
            except (KeyError, ValueError) as error:
                raise ValueError(f"invalid setmkfluid in {path}") from error
            pending_void = False
            continue
        elif tag != "drawbox" or current is None:
            continue
        boxfill_node = child.find("boxfill")
        if boxfill_node is None or boxfill_node.text is None:
            raise ValueError(f"drawbox lacks boxfill in {path}")
        faces = tuple(token.strip().lower() for token in boxfill_node.text.split("|") if token.strip())
        unknown_faces = sorted(set(faces) - set(FACE_NAMES) - {"solid"})
        if unknown_faces:
            raise ValueError(f"unknown boxfill faces {unknown_faces} in {path}")
        if current[0] == "boundary":
            if "solid" in faces:
                raise ValueError(f"boundary drawbox unexpectedly uses solid fill in {path}")
            point = _vector(child, "point")
            size = _vector(child, "size")
            if np.any(size <= 0):
                raise ValueError(f"boundary drawbox has non-positive size in {path}")
            boxes.append({
                "ordinal": len(boxes),
                "mkbound": int(current[1]),
                "declared_faces": list(faces),
                "declared_open_faces": [face for face in FACE_NAMES if face not in faces],
                "point_m": point.tolist(),
                "size_m": size.tolist(),
                "void_context": bool(pending_void),
            })
            pending_void = False
    return {
        "path": str(path),
        "particle_spacing_m": float(definition.attrib["dp"]),
        "boundary_boxes": boxes,
    }


def generated_boundary_mapping(path: Path) -> dict[int, dict[str, Any]]:
    """Map source ``mkbound`` to generated VTK Mk and Type labels."""
    root = ET.parse(Path(path)).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError(f"generated XML lacks particles summary: {path}")
    mapping: dict[int, dict[str, Any]] = {}
    for child in list(particles):
        tag = _tag(child)
        if tag not in VTK_TYPE:
            continue
        try:
            mkbound = int(child.attrib["mkbound"])
            vtk_mk = int(child.attrib["mk"])
        except (KeyError, ValueError) as error:
            raise ValueError(f"invalid {tag} boundary summary in {path}") from error
        if mkbound in mapping:
            raise ValueError(f"duplicate mkbound={mkbound} in {path}")
        mapping[mkbound] = {
            "vtk_mk": vtk_mk,
            "vtk_type": VTK_TYPE[tag],
            "particle_role": tag,
            "particle_count": int(child.attrib.get("count", 0)),
            "motion_ref": child.attrib.get("refmotion"),
        }
    if not mapping:
        raise ValueError(f"generated XML has no fixed or moving boundary mapping: {path}")
    return mapping


def _union_area_ratio(rectangles: list[tuple[float, float, float, float]],
                      lower: np.ndarray, upper: np.ndarray) -> float:
    """Compute exact union area of axis-aligned projected polygon bounds."""
    clipped: list[tuple[float, float, float, float]] = []
    for a0, a1, b0, b1 in rectangles:
        a0, a1 = max(float(lower[0]), a0), min(float(upper[0]), a1)
        b0, b1 = max(float(lower[1]), b0), min(float(upper[1]), b1)
        if a1 > a0 and b1 > b0:
            clipped.append((a0, a1, b0, b1))
    face_area = float(np.prod(np.asarray(upper) - np.asarray(lower)))
    if face_area <= 0 or not clipped:
        return 0.0
    xs = sorted({float(lower[0]), float(upper[0]), *[value for r in clipped for value in r[:2]]})
    ys = sorted({float(lower[1]), float(upper[1]), *[value for r in clipped for value in r[2:]]})
    area = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            xm, ym = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            if any(a0 <= xm <= a1 and b0 <= ym <= b1 for a0, a1, b0, b1 in clipped):
                area += (x1 - x0) * (y1 - y0)
    return float(np.clip(area / face_area, 0.0, 1.0))


def _face_observations(parsed: dict[str, Any], *, vtk_mk: int, box: dict[str, Any],
                       particle_spacing_m: float) -> dict[str, dict[str, Any]]:
    """Estimate generated coverage for each logical box face.

    GenCase emits a finite particle shell, often with two layers around a
    surface.  We therefore use a generous plane tolerance and union projected
    polygon extents rather than counting cells.  The result is a diagnostic
    classification, not a reconstruction of the CAD surface.
    """
    points = np.asarray(parsed["points"], dtype=float)
    cells = parsed["cells"]
    kinds = np.asarray(parsed["type"])
    mks = np.asarray(parsed["mk"])
    lower = np.asarray(box["point_m"], dtype=float)
    upper = lower + np.asarray(box["size_m"], dtype=float)
    candidate_indices = np.flatnonzero(np.isin(kinds, (0, 1)) & (mks == int(vtk_mk)))
    tolerance = max(1.5 * float(particle_spacing_m), 1e-6)
    result: dict[str, dict[str, Any]] = {}
    for face in FACE_NAMES:
        axis, side = FACE_AXIS[face]
        other = [index for index in range(3) if index != axis]
        target = (lower if side == 0 else upper)[axis]
        rectangles: list[tuple[float, float, float, float]] = []
        for index in candidate_indices:
            polygon = points[cells[int(index)]]
            if len(polygon) < 3:
                continue
            normal = np.cross(polygon[1] - polygon[0], polygon[2] - polygon[0])
            normal_size = np.linalg.norm(normal)
            if normal_size <= 1e-12 or int(np.argmax(np.abs(normal))) != axis:
                continue
            centroid = polygon.mean(axis=0)
            if abs(float(centroid[axis]) - float(target)) > tolerance:
                continue
            rectangles.append((
                float(np.min(polygon[:, other[0]])), float(np.max(polygon[:, other[0]])),
                float(np.min(polygon[:, other[1]])), float(np.max(polygon[:, other[1]])),
            ))
        ratio = _union_area_ratio(rectangles, lower[other], upper[other])
        declared = face in box["declared_faces"]
        if ratio >= 0.5:
            classification = "declared_surface_observed" if declared else "implicit_cap_or_supporting_surface"
        elif rectangles:
            classification = "edge_or_rim_only"
        else:
            classification = "not_observed"
        result[face] = {
            "declared": declared,
            "observed_polygon_count": len(rectangles),
            "projected_coverage_ratio": ratio,
            "classification": classification,
        }
    return result


def _case_paths(record: dict[str, Any]) -> dict[str, Path]:
    family, case_id = record["family"], record["case_id"]
    if family == "F2":
        base = CAMPAIGN / "cases" / "w06"
        generated = CAMPAIGN / "artifacts" / "w06" / case_id / "generated"
    else:
        base = LAB / "cases" / family / case_id
        generated = base / "generated"
    return {
        "definition": base / f"{case_id}_Def.xml",
        "generated_xml": generated / f"{case_id}.xml",
        "vtk": generated / f"{case_id}_MkCells.vtk" if family != "F2" else generated / f"{case_id}_MkCells.vtk",
    }


def audit_case(record: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    """Audit one release record and return JSON-serializable diagnostics."""
    paths = _case_paths(record)
    definition = parse_definition(paths["definition"])
    mapping = generated_boundary_mapping(paths["generated_xml"])
    parsed = read_binary_vtk_polydata(paths["vtk"])
    expected = boundary_triangles(parsed)
    sidecar_rel = (record.get("geometry") or {}).get("boundary_sidecar")
    sidecar_path = Path(manifest_path).resolve().parent / sidecar_rel if isinstance(sidecar_rel, str) else None
    issues: list[str] = []
    if sidecar_path is None or not sidecar_path.is_file():
        issues.append("linked boundary sidecar is missing")

    vtk_boundary = np.isin(np.asarray(parsed["type"]), (0, 1))
    vtk_mk_counts = {
        str(int(mk)): int(np.sum(vtk_boundary & (np.asarray(parsed["mk"]) == mk)))
        for mk in sorted(set(np.asarray(parsed["mk"])[vtk_boundary].tolist()))
    }
    vtk_type_by_mk = {
        str(int(mk)): sorted(set(np.asarray(parsed["type"])[vtk_boundary & (np.asarray(parsed["mk"]) == mk)].tolist()))
        for mk in sorted(set(np.asarray(parsed["mk"])[vtk_boundary].tolist()))
    }
    mapping_issues = []
    for box in definition["boundary_boxes"]:
        item = mapping.get(int(box["mkbound"]))
        if item is None:
            mapping_issues.append(f"mkbound={box['mkbound']} has no generated XML mapping")
            continue
        vtk_mk = int(item["vtk_mk"])
        observed_type = vtk_type_by_mk.get(str(vtk_mk), [])
        if not observed_type:
            mapping_issues.append(f"mkbound={box['mkbound']} maps to absent VTK Mk={vtk_mk}")
        elif observed_type != [int(item["vtk_type"])] or (int(item["vtk_type"]) not in observed_type):
            mapping_issues.append(
                f"mkbound={box['mkbound']} expected VTK Type={item['vtk_type']} but observed {observed_type}"
            )
        box["vtk_mapping"] = item
        box["face_observations"] = _face_observations(
            parsed, vtk_mk=vtk_mk, box=box, particle_spacing_m=definition["particle_spacing_m"]
        )

    sidecar_summary: dict[str, Any] | None = None
    sidecar_mk_counts: dict[str, int] = {}
    sidecar_type_by_mk: dict[str, list[int]] = {}
    if sidecar_path is not None and sidecar_path.is_file():
        try:
            with h5py.File(sidecar_path, "r") as sidecar:
                sidecar_triangles = np.asarray(sidecar["triangles_world"][:], dtype=float)
                sidecar_mk = np.asarray(sidecar["triangle_mk"][:])
                sidecar_type = np.asarray(sidecar["triangle_type"][:])
                sidecar_time = np.asarray(sidecar["time"][:], dtype=float)
                # ``build_world_series`` stores fixed triangles first and
                # moving triangles second, while VTK preserves source-cell
                # order.  Compare against the sidecar's documented canonical
                # ordering rather than mistaking that harmless reorder for a
                # geometry mismatch.
                canonical_order = np.concatenate((
                    np.flatnonzero(expected["type"] == 0),
                    np.flatnonzero(expected["type"] == 1),
                ))
                expected_canonical = expected["triangles"][canonical_order]
                sidecar_summary = {
                    "path": str(sidecar_path.relative_to(LAB)),
                    "case_id": _attr_text(sidecar.attrs.get("case_id")),
                    "coordinate_frame": _attr_text(sidecar.attrs.get("coordinate_frame")),
                    "schema_version": _attr_text(sidecar.attrs.get("schema_version")),
                    "frame_count": int(len(sidecar_time)),
                    "triangle_count": int(sidecar_triangles.shape[1]),
                    "static_triangle_count": int(np.sum(sidecar_type == 0)),
                    "moving_triangle_count": int(np.sum(sidecar_type == 1)),
                    "frame0_matches_vtk_local_geometry": bool(
                        sidecar_triangles.ndim == 4 and len(expected["triangles"]) == sidecar_triangles.shape[1]
                        and np.allclose(sidecar_triangles[0], expected_canonical, atol=1e-12, rtol=0)
                    ),
                    "static_max_frame_displacement_m": None,
                    "moving_min_frame_displacement_m": None,
                    "moving_max_frame_displacement_m": None,
                }
                for mk in sorted(set(sidecar_mk.tolist())):
                    sidecar_mk_counts[str(int(mk))] = int(np.sum(sidecar_mk == mk))
                    sidecar_type_by_mk[str(int(mk))] = sorted(set(sidecar_type[sidecar_mk == mk].tolist()))
                if sidecar_triangles.ndim == 4 and len(sidecar_triangles) > 1:
                    displacement = np.linalg.norm(sidecar_triangles[1:] - sidecar_triangles[:-1], axis=(-1, -2))
                    static = displacement[:, sidecar_type == 0]
                    moving = displacement[:, sidecar_type == 1]
                    if static.size:
                        sidecar_summary["static_max_frame_displacement_m"] = float(np.max(static))
                    if moving.size:
                        sidecar_summary["moving_min_frame_displacement_m"] = float(np.min(moving))
                        sidecar_summary["moving_max_frame_displacement_m"] = float(np.max(moving))
        except (OSError, KeyError, ValueError) as error:
            issues.append(f"sidecar unreadable: {error}")
    expected_mk_counts = {str(int(mk)): int(np.sum(expected["mk"] == mk)) for mk in sorted(set(expected["mk"].tolist()))}
    expected_type_by_mk = {
        str(int(item["vtk_mk"])): [int(item["vtk_type"])]
        for item in mapping.values()
    }
    labels_match = bool(
        sidecar_summary is not None
        and sidecar_mk_counts == expected_mk_counts
        and all(sidecar_type_by_mk.get(mk) == expected_type_by_mk.get(mk)
                for mk in expected_mk_counts)
    )

    declared_face_failures = []
    implicit_closures = []
    open_face_rim_only = []
    for box in definition["boundary_boxes"]:
        observations = box.get("face_observations", {})
        for face, observation in observations.items():
            if observation["declared"] and observation["projected_coverage_ratio"] < 0.5:
                declared_face_failures.append(f"mkbound={box['mkbound']}:{face}")
            if not observation["declared"] and observation["classification"] == "implicit_cap_or_supporting_surface":
                implicit_closures.append({
                    "mkbound": box["mkbound"], "face": face,
                    "role": "solid_obstacle" if box["void_context"] else "component",
                    "coverage_ratio": observation["projected_coverage_ratio"],
                })
            if not observation["declared"] and observation["classification"] == "edge_or_rim_only":
                open_face_rim_only.append({"mkbound": box["mkbound"], "face": face})

    static_boxes = [box for box in definition["boundary_boxes"]
                    if box.get("vtk_mapping", {}).get("vtk_type") == 0]
    moving_boxes = [box for box in definition["boundary_boxes"]
                    if box.get("vtk_mapping", {}).get("vtk_type") == 1]
    dynamic_semantics_pass = True
    if moving_boxes:
        dynamic_semantics_pass = bool(
            sidecar_summary and sidecar_summary["moving_triangle_count"] > 0
            and sidecar_summary["moving_max_frame_displacement_m"] is not None
            and sidecar_summary["moving_max_frame_displacement_m"] > 1e-12
        )
    elif sidecar_summary:
        dynamic_semantics_pass = sidecar_summary["moving_triangle_count"] == 0

    result = {
        "case_id": record["case_id"],
        "family": record["family"],
        "source_definition": str(paths["definition"].relative_to(LAB)),
        "source_generated_xml": str(paths["generated_xml"].relative_to(LAB)),
        "source_vtk": str(paths["vtk"].relative_to(LAB)),
        "particle_spacing_m": definition["particle_spacing_m"],
        "boundary_boxes": definition["boundary_boxes"],
        "generated_mk_mapping": {str(key): value for key, value in mapping.items()},
        "vtk_boundary_polygon_count": int(np.sum(vtk_boundary)),
        "vtk_boundary_polygon_counts_by_mk": vtk_mk_counts,
        "vtk_types_by_mk": vtk_type_by_mk,
        "expected_sidecar_triangle_count": int(len(expected["triangles"])),
        "sidecar": sidecar_summary,
        "sidecar_triangle_counts_by_mk": sidecar_mk_counts,
        "sidecar_types_by_mk": sidecar_type_by_mk,
        "checks": {
            "source_mk_mapping_pass": not mapping_issues,
            "sidecar_labels_match_vtk": labels_match,
            "declared_faces_recovered": not declared_face_failures,
            "static_moving_semantics_pass": dynamic_semantics_pass,
            "open_face_policy_explicit": not implicit_closures,
        },
        "declared_face_failures": declared_face_failures,
        "implicit_closures_requiring_policy": implicit_closures,
        "open_faces_with_rim_only_geometry": open_face_rim_only,
        "issues": issues + mapping_issues,
    }
    result["structural_semantics_pass"] = bool(
        not result["issues"] and result["checks"]["source_mk_mapping_pass"]
        and result["checks"]["sidecar_labels_match_vtk"]
        and result["checks"]["declared_faces_recovered"]
        and result["checks"]["static_moving_semantics_pass"]
    )
    # An undeclared full cap is deliberately not silently accepted.  It may be
    # correct (e.g. a baffle seated on the floor), but requires a component-level
    # policy before a wall-aware material target is frozen.
    result["wall_visibility_semantics_pass"] = bool(
        result["structural_semantics_pass"] and result["checks"]["open_face_policy_explicit"]
    )
    return result


def build_report(manifest_path: Path = DEFAULT_MANIFEST,
                 report_path: Path = DEFAULT_REPORT) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    records = [record for record in manifest.get("cases", []) if record.get("family") in {"F1", "F2", "F3"}]
    cases = [audit_case(record, manifest_path) for record in records]
    report = {
        "schema_version": 1,
        "scope": "R3 G2 logical boundary/open-face semantics against MkCells and finite sidecars",
        "execution_status": "complete",
        "acceptance_status": "candidate_semantics_only",
        "source_contract": {
            "Type": {"0": "fixed boundary", "1": "prescribed moving boundary", "3": "fluid surface excluded"},
            "Mk": "generated XML particles mapping is authoritative for source mkbound to VTK Mk",
            "logical_faces": "boxfill names are requested faces; omitted names are logical openings",
            "coverage_heuristic": "projected union coverage >= 0.5 is treated as a full generated face; lower coverage is edge/rim only",
        },
        "case_count": len(cases),
        "cases": cases,
        "summary": {
            "structural_semantics_pass_count": sum(case["structural_semantics_pass"] for case in cases),
            "wall_visibility_semantics_pass_count": sum(case["wall_visibility_semantics_pass"] for case in cases),
            "implicit_closure_case_count": sum(bool(case["implicit_closures_requiring_policy"]) for case in cases),
            "moving_case_count": sum(any(box.get("vtk_mapping", {}).get("vtk_type") == 1 for box in case["boundary_boxes"]) for case in cases),
        },
        "conclusion": [
            "Type/Mk labels and static versus prescribed-moving mapping are auditable against generated XML and VTK.",
            "Finite sidecars preserve actual boundary-particle shell geometry, but omitted logical faces may retain narrow rim caps.",
            "Obstacle/baffle bases can show an undeclared generated cap; this is potentially supported by a floor, but requires an explicit component policy.",
            "No sidecar should be promoted to a formal wall-aware material target until open-face and implicit-support policies are recorded.",
        ],
    }
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = build_report(args.manifest, args.report)
    print(json.dumps({
        "case_count": report["case_count"],
        "structural_semantics_pass_count": report["summary"]["structural_semantics_pass_count"],
        "wall_visibility_semantics_pass_count": report["summary"]["wall_visibility_semantics_pass_count"],
        "report": str(Path(args.report).resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
