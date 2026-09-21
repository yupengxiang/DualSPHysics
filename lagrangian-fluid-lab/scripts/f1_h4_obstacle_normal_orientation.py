#!/usr/bin/env python3
"""CPU-only static audit and candidate materialization for F1 obstacle mDBC normals.

H3 added the missing obstacle bottom face and removed the prior bottom-hole
topology, but its obstacle shell stayed on the fluid side and inherited the
tank's ``setnormalinvert=true`` state.  The resulting vectors were interpreted
as outward normals even though DualSPHysics stores a boundary-to-limit
displacement.  This module prepares one versioned candidate that places the
obstacle shell on the solid side (layers ``0,-1,-2``), uses
``setnormalinvert=false`` for every obstacle face, and leaves the tank inner
faces unchanged.  The bottom vector is therefore ``-z`` from the solid-side
particle to the z=0 interface; fluid remains accessible on ``+z``.  It does
not run DualSPHysics, submit a job, or write a ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.r4_f6_mdbc_runtime_zero_normal_audit import read_binary_vtk


SCHEMA = "core.f1.h4.obstacle_normal_orientation_static.v1"
SOURCE = LAB / (
    "campaigns/core-v1/cfd/f1-h2-bottom-contact-forensics-v1/candidate/"
    "CORE_F1_H2_mdbc_obstacle_q0p50000000_h0p46000000_"
    "dp0p007500000000_canary_bottom_face_Def.xml"
)
OUT = LAB / "campaigns/core-v1/cfd/f1-h4-obstacle-normal-orientation-v2"
GENCASE = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DP = 0.0075
OBSTACLE_LOW = np.array([0.68, 0.15, 0.0])
OBSTACLE_HIGH = np.array([0.80, 0.25, 0.34])
# Rounded support planes emitted by GenCase for the solid-side shell.
OBSTACLE_SUPPORT = {
    "left": 0.68625,
    "right": 0.79875,
    "front": 0.15375,
    "back": 0.24375,
    "bottom": 0.00375,
    "top": 0.33375,
}
TANK_LOW = np.array([0.0, 0.0, 0.0])
TANK_HIGH = np.array([1.2, 0.4, 0.6])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _xml_bytes(node: ET.Element) -> bytes:
    return ET.tostring(node, encoding="utf-8")


def patch_definition(source: Path, target: Path) -> dict[str, Any]:
    """Put obstacle particles on the solid side and point every mDBC face to its interface."""
    root = ET.parse(source).getroot()
    normal_list = root.find("./casedef/geometry/commands/list[@name='GeometryForNormals']")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if normal_list is None or mainlist is None:
        raise ValueError("source definition lacks GeometryForNormals/mainlist")

    before_main = sha256_bytes(_xml_bytes(mainlist))
    main_obstacle = None
    current_mkbound: str | None = None
    for node in list(mainlist):
        if node.tag == "setmkbound":
            current_mkbound = node.get("mk")
            continue
        if node.tag == "setmkvoid":
            current_mkbound = None
            continue
        if node.tag != "drawbox":
            continue
        point = node.find("./point")
        if point is None:
            continue
        if (
            current_mkbound == "1"
            and abs(float(point.get("x", "nan")) - (OBSTACLE_LOW[0] - DP / 2)) < 1e-10
            and abs(float(point.get("y", "nan")) - (OBSTACLE_LOW[1] - DP / 2)) < 1e-10
        ):
            main_obstacle = node
            break
    if main_obstacle is None:
        raise ValueError("H3 obstacle boundary drawbox was not found")
    # The H3 shell used layers 0,1,2 from low-dp/2.  That leaves the first
    # boundary layer on the fluid side of the nominal solid.  The official
    # fixed immersed-body recipe places the shell on the solid side using
    # low+dp/2, size-dp and layers 0,-1,-2.
    main_obstacle.find("./point").attrib.update(
        {"x": f"{OBSTACLE_LOW[0] + DP / 2:.17g}",
         "y": f"{OBSTACLE_LOW[1] + DP / 2:.17g}",
         "z": f"{OBSTACLE_LOW[2] + DP / 2:.17g}"}
    )
    main_obstacle.find("./size").attrib.update(
        {"x": f"{(OBSTACLE_HIGH[0] - OBSTACLE_LOW[0]) - DP:.17g}",
         "y": f"{(OBSTACLE_HIGH[1] - OBSTACLE_LOW[1]) - DP:.17g}",
         "z": f"{(OBSTACLE_HIGH[2] - OBSTACLE_LOW[2]) - DP:.17g}"}
    )
    main_obstacle.find("./layers").set("vdp", "0,-1,-2")
    obstacle_draw = None
    for node in list(normal_list):
        if node.tag != "drawbox":
            continue
        point = node.find("./point")
        fill = (node.findtext("./boxfill") or "").strip()
        if point is None:
            continue
        if (
            abs(float(point.get("x", "nan")) - OBSTACLE_LOW[0]) < 1e-10
            and abs(float(point.get("y", "nan")) - OBSTACLE_LOW[1]) < 1e-10
            and "bottom" in {part.strip() for part in fill.split("|")}
            and "left" in fill
        ):
            obstacle_draw = node
            break
    if obstacle_draw is None:
        raise ValueError("H3 obstacle normal drawbox was not found")

    original_fill = (obstacle_draw.findtext("./boxfill") or "").strip()
    faces = {part.strip() for part in original_fill.split("|")}
    if faces != {"bottom", "top", "left", "right", "front", "back"}:
        raise ValueError(f"unexpected H3 obstacle normal faces: {faces}")

    # With the shell on the solid side, one false-inverted draw is the
    # consistent boundary-to-interface construction for every obstacle face.
    # The bottom vector is therefore -z: the boundary particle is above the
    # contact interface and the fluid-accessible side is +z.  This is a
    # displacement vector, not a unit outward normal.  Tank inner faces stay
    # true-inverted and are not changed.
    obstacle_draw.find("./boxfill").text = "bottom | top | left | right | front | back"
    index = list(normal_list).index(obstacle_draw)
    normal_list.insert(index, ET.Element("setnormalinvert", {"invert": "false"}))
    normal_list.remove(obstacle_draw)
    normal_list.insert(index + 1, obstacle_draw)

    after_main = sha256_bytes(_xml_bytes(mainlist))
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="    ")
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return {
        "normal_change": {
            "obstacle_all_faces": {
                "setnormalinvert": False,
                "boxfill": "bottom | top | left | right | front | back",
            },
            "tank_inner_faces": {"setnormalinvert": True, "source": "unchanged"},
        },
        "mainlist_sha256_before": before_main,
        "mainlist_sha256_after": after_main,
        "mainlist_physical_shell_change": {
            "old_point": [OBSTACLE_LOW[0] - DP / 2, OBSTACLE_LOW[1] - DP / 2, OBSTACLE_LOW[2] - DP / 2],
            "old_size": [OBSTACLE_HIGH[i] - OBSTACLE_LOW[i] + DP for i in range(3)],
            "old_layers_vdp": "0,1,2",
            "new_point": [float(x) for x in OBSTACLE_LOW + DP / 2],
            "new_size": [float(OBSTACLE_HIGH[i] - OBSTACLE_LOW[i] - DP) for i in range(3)],
            "new_layers_vdp": "0,-1,-2",
            "continuum_surface_unchanged": True,
        },
        "source_obstacle_normal_boxfill": original_fill,
    }


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_log(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    out: dict[str, Any] = {}
    for key, pattern in {
        "points_loaded": r"Points loaded:\s*([0-9,]+)",
        "fixed_particles": r"Fixed\.\.\.\.\s*:\s*([0-9,]+)",
        "fluid_particles": r"Fluid\.\.\.\.\s*:\s*([0-9,]+)",
        "nonzero_normals": r"Non-zero particle normals:\s*([0-9,]+)/([0-9,]+)",
        "final_zero_normals": r"Final zero normals:\s*([0-9,]+)/([0-9,]+)",
        "normal_size_range": r"Normals size range:\s*\(([^)]+)\)",
    }.items():
        match = list(re.finditer(pattern, text))
        if not match:
            continue
        found = match[-1]
        if key in {"nonzero_normals", "final_zero_normals"}:
            out[key] = [int(found.group(1).replace(",", "")), int(found.group(2).replace(",", ""))]
        elif key == "normal_size_range":
            out[key] = [float(part.strip()) for part in found.group(1).split("-")]
        else:
            out[key] = int(found.group(1).replace(",", ""))
    return out


def _sign_counts(values: np.ndarray) -> dict[str, int]:
    signs, counts = np.unique(np.sign(values), return_counts=True)
    return {"negative": int(counts[signs < 0].sum()) if np.any(signs < 0) else 0,
            "zero": int(counts[signs == 0].sum()) if np.any(signs == 0) else 0,
            "positive": int(counts[signs > 0].sum()) if np.any(signs > 0) else 0}


def _face_contract(points: np.ndarray, normals: np.ndarray, mask: np.ndarray, axis: int,
                   expected_sign: int, expected_plane: float, label: str) -> dict[str, Any]:
    values = normals[mask, axis]
    interface = points[mask] + normals[mask]
    errors = interface[:, axis] - expected_plane
    counts = _sign_counts(values)
    return {
        "count": int(len(values)),
        "component": "xyz"[axis],
        "expected_sign": int(expected_sign),
        "observed_sign_counts": counts,
        "uniform_expected_sign": bool(len(values) > 0 and np.all(np.sign(values) == expected_sign)),
        "interface_plane_m": float(expected_plane),
        "interface_component_max_abs_error_m": float(np.max(np.abs(errors))) if len(errors) else None,
        "label": label,
    }


def audit_generated(prefix: Path, definition: Path, changes: dict[str, Any], log: Path) -> dict[str, Any]:
    bound_path = prefix.with_name(prefix.name + "_Bound.vtk")
    fluid_path = prefix.with_name(prefix.name + "_Fluid.vtk")
    hdp_path = prefix.with_name(prefix.name + "_hdp_Actual.vtk")
    if not bound_path.is_file() or not fluid_path.is_file() or not hdp_path.is_file():
        raise FileNotFoundError("GenCase output is incomplete")
    bound = read_binary_vtk(bound_path)
    fluid = read_binary_vtk(fluid_path)
    points = np.asarray(bound["points"], dtype=float)
    normals = np.asarray(bound["point_data"]["Normal"], dtype=float)
    normal_size = np.asarray(bound["point_data"]["NormalSize"], dtype=float)
    mk = np.asarray(bound["point_data"]["Mk"], dtype=int)
    boundary_keys = {tuple(np.round(point, 8)) for point in points}
    obstacle = mk == 18
    tank = mk == 17
    tol = 1.0e-6
    # Interior-only masks avoid corner averages while preserving every face
    # family, including the contact bottom whose boundary-to-interface vector
    # is -z because its shell particle is above the z=0 surface.
    faces = {
        "obstacle_left": _face_contract(points, normals,
            obstacle & (abs(points[:, 0] - OBSTACLE_SUPPORT["left"]) < tol)
            & (points[:, 1] > .16) & (points[:, 1] < .24) & (points[:, 2] > .01) & (points[:, 2] < .33), 0, -1, OBSTACLE_LOW[0], "solid side, fluid on -x"),
        "obstacle_right": _face_contract(points, normals,
            obstacle & (abs(points[:, 0] - OBSTACLE_SUPPORT["right"]) < tol)
            & (points[:, 1] > .16) & (points[:, 1] < .24) & (points[:, 2] > .01) & (points[:, 2] < .33), 0, +1, OBSTACLE_HIGH[0], "solid side, fluid on +x"),
        "obstacle_front": _face_contract(points, normals,
            obstacle & (abs(points[:, 1] - OBSTACLE_SUPPORT["front"]) < tol)
            & (points[:, 0] > .69) & (points[:, 0] < .79) & (points[:, 2] > .01) & (points[:, 2] < .33), 1, -1, OBSTACLE_LOW[1], "solid side, fluid on -y"),
        "obstacle_back": _face_contract(points, normals,
            obstacle & (abs(points[:, 1] - OBSTACLE_SUPPORT["back"]) < tol)
            & (points[:, 0] > .69) & (points[:, 0] < .79) & (points[:, 2] > .01) & (points[:, 2] < .33), 1, +1, OBSTACLE_HIGH[1], "solid side, fluid on +y"),
        "obstacle_bottom_contact": _face_contract(points, normals,
            obstacle & (abs(points[:, 2] - OBSTACLE_SUPPORT["bottom"]) < tol)
            & (points[:, 0] > .69) & (points[:, 0] < .79) & (points[:, 1] > .16) & (points[:, 1] < .24), 2, -1, OBSTACLE_LOW[2], "contact face: boundary particle is solid-side; accessible fluid is +z"),
        "obstacle_top": _face_contract(points, normals,
            obstacle & (abs(points[:, 2] - OBSTACLE_SUPPORT["top"]) < tol)
            & (points[:, 0] > .69) & (points[:, 0] < .79) & (points[:, 1] > .16) & (points[:, 1] < .24), 2, +1, OBSTACLE_HIGH[2], "solid side, fluid on +z"),
        "tank_left": _face_contract(points, normals,
            tank & (abs(points[:, 0] - (TANK_LOW[0] - 2.5 * DP)) < tol)
            & (points[:, 1] > .05) & (points[:, 1] < .35) & (points[:, 2] > .05) & (points[:, 2] < .55), 0, +1, TANK_LOW[0], "container inner wall, fluid on +x"),
        "tank_right": _face_contract(points, normals,
            tank & (abs(points[:, 0] - (TANK_HIGH[0] + 2.5 * DP)) < tol)
            & (points[:, 1] > .05) & (points[:, 1] < .35) & (points[:, 2] > .05) & (points[:, 2] < .55), 0, -1, TANK_HIGH[0], "container inner wall, fluid on -x"),
        "tank_front": _face_contract(points, normals,
            tank & (abs(points[:, 1] - (TANK_LOW[1] - 2.5 * DP)) < tol)
            & (points[:, 0] > .05) & (points[:, 0] < 1.15) & (points[:, 2] > .05) & (points[:, 2] < .55), 1, +1, TANK_LOW[1], "container inner wall, fluid on +y"),
        "tank_back": _face_contract(points, normals,
            tank & (abs(points[:, 1] - (TANK_HIGH[1] + 2.1666666666666665 * DP)) < tol)
            & (points[:, 0] > .05) & (points[:, 0] < 1.15) & (points[:, 2] > .05) & (points[:, 2] < .55), 1, -1, TANK_HIGH[1], "container inner wall, fluid on -y"),
        "tank_bottom": _face_contract(points, normals,
            tank & (abs(points[:, 2] - (TANK_LOW[2] - 2.5 * DP)) < tol)
            & (points[:, 0] > .05) & (points[:, 0] < 1.15) & (points[:, 1] > .05) & (points[:, 1] < .35), 2, +1, TANK_LOW[2], "container inner wall, fluid on +z"),
    }
    all_interface = points + normals
    normal_geometry = ET.parse(definition).getroot().find("./casedef/normals/norgeometry")
    return {
        "generated_counts": {
            "boundary_particles": int(len(points)),
            "fluid_particles": int(len(fluid["points"])),
            "mk_counts": {str(int(value)): int(count) for value, count in zip(*np.unique(mk, return_counts=True))},
        },
        "normal_contract": {
            "normal_count": int(len(normals)),
            "zero_normal_count": int(np.sum(np.linalg.norm(normals, axis=1) <= 1.0e-10)),
            "normal_size_range_m": [float(normal_size.min()), float(normal_size.max())],
            "interface_formula": "x_gamma=x_boundary+n_b; solver ghost=x_boundary+2*n_b",
            "face_checks": faces,
            "all_required_faces_nonempty": all(item["count"] > 0 for item in faces.values()),
            "all_required_face_signs_pass": all(item["uniform_expected_sign"] for item in faces.values()),
            "all_required_interface_errors_m": max(
                item["interface_component_max_abs_error_m"] or 0.0 for item in faces.values()
            ),
        },
        "geometry_contract": {
            "mainlist_sha256_before": changes["mainlist_sha256_before"],
            "mainlist_sha256_after": changes["mainlist_sha256_after"],
            "mainlist_boundary_shell_changed": changes["mainlist_sha256_before"] != changes["mainlist_sha256_after"],
            "hdp_geometry_file": str(prefix.with_name(prefix.name + "_hdp_Actual.vtk").resolve()),
            "norgeometry_present": normal_geometry is not None,
            "exact_fluid_boundary_overlap_count": int(
                sum(
                    tuple(np.round(point, 8)) in boundary_keys
                    for point in np.asarray(fluid["points"], dtype=float)
                )
            ),
            "physical_continuum_geometry_changed": False,
            "boundary_discretization_changed": True,
        },
        "source_semantics": {
            "cpu_mdbc_source": str((LAB.parent / "src/source/JSphCpu_mdbc.cpp").resolve()),
            "cpu_mdbc_source_sha256": sha256(LAB.parent / "src/source/JSphCpu_mdbc.cpp"),
            "official_solid_side_recipe": str((LAB / "campaigns/v0.1-candidate/cases/r3-fixed-box-force-gauge/fixed_box_mdbc_canonical_Def.xml").resolve()),
            "official_solid_side_recipe_sha256": sha256(LAB / "campaigns/v0.1-candidate/cases/r3-fixed-box-force-gauge/fixed_box_mdbc_canonical_Def.xml"),
            "ghost_position_source": "gpos=pos+boundnor; dpos=-boundnor; boundary-to-limit displacement",
            "normal_direction_rule": "normal points from boundary particle toward mDBC limit/interface point; it is not a unit outward normal",
            "obstacle_bottom_rule": "bottom is -z because the corrected boundary shell is on the solid side above z=0; the interface displacement points down to z=0 while fluid remains on +z",
            "obstacle_sides_top_rule": "all obstacle faces use the solid-side shell plus setnormalinvert=false construction",
            "tank_rule": "tank inner faces retain setnormalinvert=true toward fluid",
        },
        "binary": {"path": str(GENCASE.resolve()), "sha256": sha256(GENCASE)},
        "log_summary": _parse_log(log),
        "hashes": {
            "definition": sha256(definition),
            "bound": sha256(bound_path),
            "fluid": sha256(fluid_path),
            "hdp_actual": sha256(hdp_path),
            "log": sha256(log),
        },
    }


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"refusing to overwrite existing candidate root: {OUT}")
    if not SOURCE.is_file() or not GENCASE.is_file():
        raise SystemExit("missing H3 source or GenCase binary")
    OUT.mkdir(parents=True)
    definition = OUT / "CORE_F1_H4_mdbc_obstacle_normal_orientation_Def.xml"
    changes = patch_definition(SOURCE, definition)
    prefix = OUT / "generated/CORE_F1_H4_mdbc_obstacle_normal_orientation"
    log = OUT / "gencase.log"
    command = [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"]
    with log.open("w") as stream:
        proc = subprocess.run(command, cwd=OUT, stdout=stream, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise SystemExit(f"GenCase failed with {proc.returncode}: {log}")
    audit = audit_generated(prefix, definition, changes, log)
    audit.update({
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_kind": "CPU GenCase only; no solver/GPU",
        "source_definition": str(SOURCE.resolve()),
        "source_definition_sha256": sha256(SOURCE),
        "candidate_definition": str(definition.resolve()),
        "gencase_command": command,
        "candidate_changes": changes,
        "qualification_claim": "none; static repair candidate only",
        "gpu_launched": False,
        "ledger_written": False,
    })
    write_json(OUT / "static-normal-orientation-audit.json", audit)
    if not audit["normal_contract"]["all_required_face_signs_pass"]:
        raise SystemExit("static normal face contract failed; inspect audit")
    print(json.dumps({
        "status": "cpu_static_pass",
        "candidate": str(OUT),
        "boundary_particles": audit["generated_counts"]["boundary_particles"],
        "fluid_particles": audit["generated_counts"]["fluid_particles"],
        "zero_normals": audit["normal_contract"]["zero_normal_count"],
        "face_signs_pass": audit["normal_contract"]["all_required_face_signs_pass"],
        "overlap": audit["geometry_contract"]["exact_fluid_boundary_overlap_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
