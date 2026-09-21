#!/usr/bin/env python3
"""CPU/native preflight for the independent F1 suspended-obstacle scope.

This scope changes the physical geometry: the obstacle is free-standing with a
0.06 m fluid gap below it.  It is therefore a new F1 physical hypothesis,
not another H1--H4 boundary-orientation retry.  The script only materializes
one q=0.5, dp=0.0075 anchor, runs GenCase, decodes the native ``.bi4`` and
writes an audit.  It never starts DualSPHysics, submits a job, or writes the
central registry/ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.core_cfd import native_frame
from scripts.r4_f6_mdbc_runtime_zero_normal_audit import read_binary_vtk


SOURCE = LAB / (
    "campaigns/core-v1/cfd/f1-h2-bottom-contact-forensics-v1/candidate/"
    "CORE_F1_H2_mdbc_obstacle_q0p50000000_h0p46000000_"
    "dp0p007500000000_canary_bottom_face_Def.xml"
)
OUT = LAB / "campaigns/core-v1/cfd/f1-suspended-obstacle-gap-scope-v1"
GENCASE = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
DP = 0.0075
OBSTACLE_LOW = np.array([0.68, 0.15, 0.06])
OBSTACLE_SIZE = np.array([0.12, 0.10, 0.34])
OBSTACLE_HIGH = OBSTACLE_LOW + OBSTACLE_SIZE
TANK_LOW = np.array([0.0, 0.0, 0.0])
TANK_HIGH = np.array([1.2, 0.4, 0.6])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _attrs(node: ET.Element, values: np.ndarray) -> None:
    node.attrib.update({axis: f"{float(value):.17g}" for axis, value in zip("xyz", values)})


def _point(node: ET.Element) -> np.ndarray:
    return np.array([float(node.get(axis, "nan")) for axis in "xyz"])


def patch_definition(target: Path) -> dict:
    """Move both the obstacle void and boundary shell; keep tank/fluid inputs fixed."""
    root = ET.parse(SOURCE).getroot()
    geometry = root.find("./casedef/geometry")
    commands = geometry.find("./commands") if geometry is not None else None
    normal_list = commands.find("./list[@name='GeometryForNormals']") if commands is not None else None
    mainlist = commands.find("./mainlist") if commands is not None else None
    if normal_list is None or mainlist is None:
        raise ValueError("source lacks GeometryForNormals/mainlist")

    # The normal geometry is the continuum obstacle.  Insert an explicit
    # false inversion immediately before it; the tank's true inversion stays.
    normal_obstacle = None
    for node in normal_list:
        if node.tag != "drawbox":
            continue
        fill = {part.strip() for part in (node.findtext("./boxfill") or "").split("|")}
        point = node.find("./point")
        if point is not None and fill == {"bottom", "top", "left", "right", "front", "back"}:
            if abs(float(point.get("x", "nan")) - .68) < 1e-10 and abs(float(point.get("y", "nan")) - .15) < 1e-10:
                normal_obstacle = node
                break
    if normal_obstacle is None:
        raise ValueError("normal obstacle drawbox not found")
    normal_obstacle.find("./point").attrib.update({"z": f"{OBSTACLE_LOW[2]:.17g}"})
    normal_obstacle.find("./size").attrib.update({"z": f"{OBSTACLE_SIZE[2]:.17g}"})
    index = list(normal_list).index(normal_obstacle)
    normal_list.insert(index, ET.Element("setnormalinvert", {"invert": "false"}))

    # The H2 source has one mkvoid obstacle volume and one mkbound volume.
    # Move both.  The void keeps the new gap fluid-filled; the solid-side
    # boundary shell uses the existing H4 recipe and remains mDBC-compatible.
    current_mk: str | None = None
    changed: list[dict] = []
    for node in mainlist:
        if node.tag == "setmkvoid":
            current_mk = "void"
            continue
        if node.tag == "setmkbound":
            current_mk = node.get("mk")
            continue
        if node.tag != "drawbox" or current_mk not in {"void", "1"}:
            continue
        point = node.find("./point")
        size = node.find("./size")
        layers = node.find("./layers")
        if point is None or size is None:
            continue
        old_point = _point(point)
        if abs(old_point[0] - (.68 - DP / 2)) > 1e-8 or abs(old_point[1] - (.15 - DP / 2)) > 1e-8:
            continue
        if current_mk == "void":
            _attrs(point, OBSTACLE_LOW - DP / 2)
            _attrs(size, OBSTACLE_SIZE + DP)
            if layers is not None:
                layers.set("vdp", "0,1,2")
        else:
            _attrs(point, OBSTACLE_LOW + DP / 2)
            _attrs(size, OBSTACLE_SIZE - DP)
            if layers is not None:
                layers.set("vdp", "0,-1,-2")
        changed.append({"kind": current_mk, "old_point": old_point.tolist(), "new_point": _point(point).tolist()})
    if {item["kind"] for item in changed} != {"void", "1"}:
        raise ValueError(f"expected both obstacle volumes, got {changed}")

    target.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="    ")
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return {
        "continuum_geometry": {
            "tank_low_m": TANK_LOW.tolist(), "tank_high_m": TANK_HIGH.tolist(),
            "obstacle_low_m": OBSTACLE_LOW.tolist(), "obstacle_high_m": OBSTACLE_HIGH.tolist(),
            "bottom_fluid_gap_m": float(OBSTACLE_LOW[2] - TANK_LOW[2]),
        },
        "normal_change": {"obstacle_all_faces_setnormalinvert": False, "tank_inner_faces_unchanged": True},
        "mainlist_changes": changed,
        "source_sha256": sha256(SOURCE),
    }


def _sign_counts(values: np.ndarray) -> dict[str, int]:
    signs, counts = np.unique(np.sign(values), return_counts=True)
    return {"negative": int(counts[signs < 0].sum()) if np.any(signs < 0) else 0,
            "zero": int(counts[signs == 0].sum()) if np.any(signs == 0) else 0,
            "positive": int(counts[signs > 0].sum()) if np.any(signs > 0) else 0}


def _face(points: np.ndarray, normals: np.ndarray, obstacle: np.ndarray, axis: int,
          support_plane: float, interface_plane: float, sign: int, label: str) -> dict:
    other = [item for item in range(3) if item != axis]
    interior = obstacle.copy()
    for item in other:
        interior &= (points[:, item] > OBSTACLE_LOW[item] + 3 * DP) & (points[:, item] < OBSTACLE_HIGH[item] - 3 * DP)
    interior &= np.abs(points[:, axis] - support_plane) <= 1.0e-7
    values = normals[interior, axis]
    return {
        "label": label, "count": int(len(values)), "expected_sign": sign,
        "observed_sign_counts": _sign_counts(values),
        "uniform_expected_sign": bool(len(values) > 0 and np.all(np.sign(values) == sign)),
        "support_plane_m": support_plane,
        "interface_plane_m": interface_plane,
        "interface_plane_error_max_m": float(np.max(np.abs((points[interior] + normals[interior])[:, axis] - interface_plane))) if len(values) else None,
    }


def main() -> int:
    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"refusing to overwrite existing output: {OUT}")
    if not SOURCE.is_file() or not GENCASE.is_file() or not DECODER.is_file():
        raise SystemExit("missing source, GenCase or native decoder")
    OUT.mkdir(parents=True)
    definition = OUT / "CORE_F1_suspended_obstacle_gap_q0p50000000_h0p46000000_dp0p007500000000_Def.xml"
    changes = patch_definition(definition)
    prefix = OUT / "generated/CORE_F1_suspended_obstacle_gap_q0p50000000_h0p46000000_dp0p007500000000"
    log = OUT / "gencase.log"
    command = [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"]
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=OUT, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(f"GenCase failed with return code {result.returncode}")
    bound = read_binary_vtk(prefix.with_name(prefix.name + "_Bound.vtk"))
    fluid = read_binary_vtk(prefix.with_name(prefix.name + "_Fluid.vtk"))
    points = np.asarray(bound["points"], dtype=float)
    normals = np.asarray(bound["point_data"]["Normal"], dtype=float)
    mk = np.asarray(bound["point_data"]["Mk"], dtype=int)
    obstacle = mk == 18
    with tempfile.TemporaryDirectory(prefix="core-f1-suspended-native-") as temp:
        ids, pos, vel, rho, metadata, info, arrays = native_frame(prefix.with_suffix(".bi4"), Path(temp) / "native", DECODER)
        native = {
            "total_particles": int(len(ids)),
            "fluid_particles": int(metadata.get("CaseNfluid", 0)),
            "boundary_particles": int(metadata.get("CaseNfixed", 0)),
            "unique_ids": bool(len(np.unique(ids)) == len(ids)),
            "finite_initial_arrays": bool(all(np.isfinite(x).all() for x in (pos, vel, rho))),
            "normal_file_present": bool((arrays / "BoundNor.bin").is_file()),
            "native_metadata": metadata,
            "native_info": info,
        }
    support = {"left": float(points[obstacle, 0].min()), "right": float(points[obstacle, 0].max()),
               "front": float(points[obstacle, 1].min()), "back": float(points[obstacle, 1].max()),
               "bottom": float(points[obstacle, 2].min()), "top": float(points[obstacle, 2].max())}
    faces = {
        "left": _face(points, normals, obstacle, 0, support["left"], float(OBSTACLE_LOW[0]), -1, "fluid on -x"),
        "right": _face(points, normals, obstacle, 0, support["right"], float(OBSTACLE_HIGH[0]), +1, "fluid on +x"),
        "front": _face(points, normals, obstacle, 1, support["front"], float(OBSTACLE_LOW[1]), -1, "fluid on -y"),
        "back": _face(points, normals, obstacle, 1, support["back"], float(OBSTACLE_HIGH[1]), +1, "fluid on +y"),
        "bottom": _face(points, normals, obstacle, 2, support["bottom"], float(OBSTACLE_LOW[2]), -1, "fluid below gap"),
        "top": _face(points, normals, obstacle, 2, support["top"], float(OBSTACLE_HIGH[2]), +1, "fluid above obstacle"),
    }
    fluid_points = np.asarray(fluid["points"], dtype=float)
    boundary_keys = {tuple(np.round(point, 8)) for point in points}
    audit = {
        "schema": "core.f1.suspended_obstacle_gap.cpu_native_preflight.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_kind": "CPU GenCase plus native .bi4 decode; solver/GPU not run",
        "scope_id": "F1_suspended_obstacle_gap_v1",
        "revision_id": "F1_suspended_obstacle_gap_mdbc_v1",
        "candidate_changes": changes,
        "generated_counts": {
            "boundary_particles": int(len(points)), "fluid_particles_vtk": int(len(fluid_points)),
            "mk_counts": {str(int(value)): int(count) for value, count in zip(*np.unique(mk, return_counts=True))},
        },
        "native_initial": native,
        "normal_contract": {
            "normal_count": int(len(normals)),
            "zero_normal_count": int(np.sum(np.linalg.norm(normals, axis=1) <= 1.0e-10)),
            "all_faces_nonempty": bool(all(item["count"] > 0 for item in faces.values())),
            "all_face_signs_pass": bool(all(item["uniform_expected_sign"] for item in faces.values())),
            "faces": faces,
        },
        "geometry_contract": {
            "exact_fluid_boundary_overlap_count": int(sum(tuple(np.round(point, 8)) in boundary_keys for point in fluid_points)),
            # The reference F1 fill starts at x=.04 and ends at x=.38; it does
            # not initially wet the obstacle footprint.  Accessibility is
            # therefore a geometry claim, not an assertion that an initial
            # fluid particle already occupies the gap.  The generated obstacle
            # shell must stay at/above the suspended bottom plane, leaving the
            # tank volume below it available to the later flow.
            "gap_is_fluid_accessible": bool(
                len(points[obstacle]) > 0
                and float(points[obstacle, 2].min()) >= float(OBSTACLE_LOW[2])
                and float(points[obstacle, 2].min()) < float(OBSTACLE_LOW[2] + 2 * DP)
            ),
        },
        "hashes": {
            "source_definition": sha256(SOURCE), "candidate_definition": sha256(definition),
            "gencase_log": sha256(log), "bound_vtk": sha256(prefix.with_name(prefix.name + "_Bound.vtk")),
            "fluid_vtk": sha256(prefix.with_name(prefix.name + "_Fluid.vtk")),
            "hdp_actual_vtk": sha256(prefix.with_name(prefix.name + "_hdp_Actual.vtk")),
            "native_bi4": sha256(prefix.with_suffix(".bi4")), "gencase_binary": sha256(GENCASE),
            "decoder": sha256(DECODER),
        },
        "gpu_launched": False,
        "solver_run": False,
        "ledger_written": False,
        "registry_written": False,
    }
    audit["preflight_pass"] = bool(
        native["unique_ids"] and native["finite_initial_arrays"] and native["normal_file_present"]
        and audit["normal_contract"]["zero_normal_count"] == 0
        and audit["normal_contract"]["all_faces_nonempty"]
        and audit["normal_contract"]["all_face_signs_pass"]
        and audit["geometry_contract"]["exact_fluid_boundary_overlap_count"] == 0
        and audit["geometry_contract"]["gap_is_fluid_accessible"]
    )
    write_json(OUT / "cpu-native-preflight.json", audit)
    case_id = "CORE_F1_G1_suspended_obstacle_gap_q0p50000000_h0p46000000_dp0p007500000000_canary"
    solver = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
    fluid_count = int(len(fluid_points))
    sampling_box = {
        "continuous_low_m": [0.04, 0.04, 0.04], "continuous_size_m": [0.34, 0.32, 0.46],
        "first_center_m": [0.04125, 0.04125, 0.04125], "draw_size_m": [0.3375, 0.315, 0.45],
        "counts": [46, 43, 61], "particle_count": fluid_count,
        "continuous_mass_kg": 50.048, "discrete_mass_kg": fluid_count * DP ** 3 * 1000.0,
        "native_cell_centre_sampling": True, "mkfluid": 0,
    }
    source_error = float(sampling_box["discrete_mass_kg"] / sampling_box["continuous_mass_kg"] - 1.0)
    runtime_domain = {"xmin": -0.3, "xmax": 1.5, "ymin": -0.099375, "ymax": 0.496875, "zmin": -0.15, "zmax": 1.8}
    wall_spec = {
        "container_interior": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4, "zmin": 0.0, "zmax": 0.6},
        "closed_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"],
        "obstacles": [{"id": "suspended_center_obstacle", "xmin": 0.68, "xmax": 0.8, "ymin": 0.15, "ymax": 0.25, "zmin": 0.06, "zmax": 0.4}],
        "runtime_domain": runtime_domain,
    }
    config = {
        "schema": "core.cfd.v1", "family": "F1", "scope_id": audit["scope_id"],
        "revision_id": audit["revision_id"], "case_id": case_id,
        "recipe_id": "F1_G1_suspended_obstacle_mdbc_v1", "recipe": "mdbc_native",
        "stage": "canary", "design_cell": "spatial", "temporal_variant": None,
        "qualification_claim": "none", "qualified": False,
        "parameter": {"name": "initial_water_height_m", "q": 0.5, "value": 0.46, "candidate_range": [0.4, 0.52], "mapping": "h(q)=0.40+0.12*q m"},
        "dp_m": DP, "fluid_box": {"low": [0.04, 0.04, 0.04], "size": [0.34, 0.32, 0.46], "mkfluid": 0},
        "initialization_rule": {"name": "cell_centre_drawbox_sampling", "mass_rescaling": False, "continuum_box_preserved": True},
        "continuum_geometry": {
            "tank": {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.6]},
            "obstacle": {"id": "suspended_center_obstacle", "low": [0.68, 0.15, 0.06], "size": [0.12, 0.1, 0.34]},
            "density_kg_m3": 1000.0, "unchanged": False, "geometry_revision": "bottom_gap_0p06m",
        },
        "gravity_m_s2": [0.0, 0.0, -9.81], "initial_velocity_m_s": [0.0, 0.0, 0.0],
        "wall_bounds": wall_spec["container_interior"], "closed_faces": wall_spec["closed_faces"], "open_faces": wall_spec["open_faces"],
        "wall_spec": wall_spec, "runtime_domain_zmax_m": 1.8,
        "boundary_semantics": "mDBC no-slip with free-standing solid-side obstacle shell; no threshold relaxation",
        "source_definition": str(definition.resolve()), "cfl": 0.2, "output_interval_s": 0.02, "time_max_s": 2.2,
        "event_window": {"initial_time_max_s": 2.2, "maximum_extended_time_max_s": 4.4, "output_interval_s": 0.02, "extension_policy": "one whole-scope doubling only if right-censored after hard pass", "completion_required_for_qualification": True},
        "physical_case_id": "L2_C1_F1_suspended_obstacle_gap", "lineage_group_id": "L2_C1_F1_suspended_obstacle_gap_height_range",
        "source_label_semantics": "new physical geometry identity, no material qualification",
        "mechanism_class": "physical_geometry_free_standing_obstacle", "mechanism_class_attempt": 1,
        "solver_arguments": ["-mdbc_noslip:1"],
    }
    input_paths = [definition, log, prefix.with_suffix(".bi4"), prefix.with_suffix(".xml"),
                   prefix.with_name(prefix.name + "_Bound.vtk"), prefix.with_name(prefix.name + "_Fluid.vtk"),
                   prefix.with_name(prefix.name + "_hdp_Actual.vtk")]
    prepared = {
        "schema": "core.cfd.v1", "created_at": datetime.now(timezone.utc).isoformat(), "config": config,
        "sampling": {"fluid_boxes": [sampling_box], "expected_fluid_particles": fluid_count, "total_continuous_mass_kg": 50.048, "total_discrete_mass_kg": sampling_box["discrete_mass_kg"]},
        "mass_preflight": {"source_relative_errors": [source_error], "max_abs_source_relative_error": abs(source_error), "total_discrete_mass_kg": sampling_box["discrete_mass_kg"], "total_continuous_mass_kg": 50.048, "total_relative_error": source_error, "source_error_max": 0.025, "total_error_max": 0.03, "mass_rescaling": False, "mass_gate_pass": bool(abs(source_error) <= 0.025)},
        "native_initial": {"total_particles": native["total_particles"], "boundary_particles": native["boundary_particles"], "fluid_particles": native["fluid_particles"], "normal_count": int(len(normals)), "zero_boundary_normals": int(audit["normal_contract"]["zero_normal_count"]), "unique_ids": native["unique_ids"], "finite_initial_arrays": native["finite_initial_arrays"], "normal_file_present": native["normal_file_present"], "initial_state_pass": bool(native["unique_ids"] and native["finite_initial_arrays"] and native["normal_file_present"] and audit["normal_contract"]["zero_normal_count"] == 0)},
        "preflight_pass": bool(audit["preflight_pass"]), "generated_prefix": str(prefix.resolve()),
        "source_template": str(SOURCE.resolve()), "source_template_sha256": sha256(SOURCE),
        "definition_audit": changes, "resolved_runtime_domain": runtime_domain,
        "inputs": {str(path.resolve()): sha256(path) for path in input_paths},
        "solver_binary": str(solver.resolve()), "solver_sha256": sha256(solver), "decoder": str(DECODER.resolve()), "decoder_sha256": sha256(DECODER),
        "solver_arguments": ["-mdbc_noslip:1"], "qualification_claim": "none; one G1 anchor preparation, not range or qualification evidence",
        "central_registry_mutated": False, "central_ledger_mutated": False,
    }
    write_json(OUT / "prepared.json", prepared)
    print(json.dumps({"status": "cpu_native_preflight", "preflight_pass": audit["preflight_pass"],
                      "fluid_particles": audit["native_initial"]["fluid_particles"],
                      "boundary_particles": audit["native_initial"]["boundary_particles"],
                      "all_face_signs_pass": audit["normal_contract"]["all_face_signs_pass"],
                      "gap_is_fluid_accessible": audit["geometry_contract"]["gap_is_fluid_accessible"]}, indent=2))
    return 0 if audit["preflight_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
