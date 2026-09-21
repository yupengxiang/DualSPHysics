#!/usr/bin/env python3
"""CPU-only H1 boundary repair preparation for the F2 static full-cup cell.

H1 changes only the numerical boundary formulation from native DBC to mDBC
with explicit normal geometry.  The v4 cell-0 fluid lattice, cup/receiver/
tray geometry, mass policy and 0.60 s window remain bound to the original
preparation.  This module never invokes the solver, CUDA, queue, ledger or
registry; it emits a separate repair-preflight lineage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd


SCHEMA = "core.f2.static_full_cup.boundary_repair_prepared.v1"
SOURCE_SCHEMA = "core.f2.static_full_cup.matrix_cell_prepared.v1"
SCOPE_ID = "F2_static_full_cup_volume_hold_x_v1"
REPAIR_ID = "F2_static_full_cup_boundary_mdbc_h1_v1"
CELL_INDEX = 0
TIME_MAX_S = 0.60
DECODER_RELATIVE = "campaigns/l1-resume/artifacts/bi4_dump"
GENCASE_RELATIVE = "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
SOLVER_RELATIVE = "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _set_parameter(root: ET.Element, key: str, value: str | int | float) -> None:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        raise ValueError(f"missing execution parameter {key}")
    node.set("value", str(value))


def _copy_node(node: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(node, encoding="unicode"))


def _normal_geometry(commands: ET.Element) -> tuple[ET.Element, int]:
    main = commands.find("mainlist")
    if main is None:
        raise ValueError("missing mainlist")
    normal = ET.Element("list", {"name": "GeometryForNormals"})
    ET.SubElement(normal, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    ET.SubElement(normal, "setshapemode").text = "actual | bound"
    ET.SubElement(normal, "setnormalinvert", {"invert": "true"})
    count = 0
    nodes = list(main)
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if node.tag == "setmkbound" and index + 1 < len(nodes) and nodes[index + 1].tag == "drawbox":
            ET.SubElement(normal, "setmkbound", {"mk": node.get("mk", "0")})
            draw = _copy_node(nodes[index + 1])
            layers = draw.find("layers")
            if layers is None:
                layers = ET.SubElement(draw, "layers")
            layers.set("vdp", "-0.5")
            normal.append(draw)
            count += 1
            index += 2
            continue
        index += 1
    if count == 0:
        raise ValueError("no boundary drawboxes available for normal geometry")
    ET.SubElement(normal, "shapeout", {"file": "hdp"})
    ET.SubElement(normal, "resetdraw")
    return normal, count


def rewrite_definition(source: Path, target: Path) -> dict[str, Any]:
    tree = ET.parse(source)
    root = tree.getroot()
    for key, value in {"Boundary": 2, "SlipMode": 1, "SavePosDouble": 2,
                       "TimeMax": TIME_MAX_S, "TimeOut": 0.02, "PartsOutMax": 1}.items():
        _set_parameter(root, key, value)
    commands = root.find(".//geometry/commands")
    if commands is None:
        raise ValueError("missing geometry commands")
    old = commands.find("GeometryForNormals")
    if old is not None:
        commands.remove(old)
    normal, boundary_box_count = _normal_geometry(commands)
    commands.insert(0, normal)
    main = commands.find("mainlist")
    if main is None:
        raise ValueError("missing mainlist")
    if main.find("runlist") is None:
        main.insert(0, ET.Element("runlist", {"name": "GeometryForNormals"}))
    casedef = root.find("casedef")
    if casedef is None:
        raise ValueError("missing casedef")
    old_normals = casedef.find("normals")
    if old_normals is not None:
        casedef.remove(old_normals)
    normals = ET.SubElement(casedef, "normals", {"active": "true"})
    norgeometry = ET.SubElement(normals, "norgeometry")
    ET.SubElement(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    ET.SubElement(norgeometry, "distanceh", {"v": "3.0"})
    ET.SubElement(norgeometry, "svshapes", {"v": "true"})
    ET.indent(tree, space="  ")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "source_definition": str(source.resolve()),
        "source_definition_sha256": digest(source),
        "definition": str(target.resolve()),
        "definition_sha256": digest(target),
        "changed_numeric_boundary": {"Boundary": 2, "SlipMode": 1, "TimeMax": TIME_MAX_S, "TimeOut": 0.02},
        "normal_geometry": {"boundary_box_count": boundary_box_count, "distanceh": 3.0,
                            "shapeout": "hdp", "normal_invert": True, "surface_velocity_shapes": True},
        "fluid_and_continuum_geometry_unchanged": True,
        "mass_rescaling": False,
        "qualification_claim": "none; H1 CPU/native repair preflight only",
    }


def prepare(*, lab: Path, source_prepared: Path, output: Path) -> dict[str, Any]:
    lab, source_prepared, output = map(Path, (lab, source_prepared, output))
    lab = lab.resolve()
    source_prepared = source_prepared.resolve()
    output = output.resolve()
    source = _load(source_prepared)
    if source.get("schema") != SOURCE_SCHEMA or int(source.get("index", -1)) != CELL_INDEX:
        raise ValueError("source is not the pinned v4 cell-0 preparation")
    if source.get("scope_id") != SCOPE_ID or source.get("preflight_pass") is not True:
        raise ValueError("source v4 preparation is not passed")
    for key in ("solver_invoked", "gpu_invoked", "queue_mutated", "ledger_mutated", "registry_mutated", "mass_rescaling"):
        if source.get(key) is not False:
            raise ValueError(f"source execution control is open: {key}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"repair output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source_definition = Path(source["definition_audit"]["definition"]).resolve()
    source_motion = source_definition.parent / source["definition_audit"]["motion_file_name"]
    definition = output / f"{source['case_id']}_H1_mdbc_Def.xml"
    definition_audit = rewrite_definition(source_definition, definition)
    motion = output / source_motion.name
    shutil.copyfile(source_motion, motion)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / f"{source['case_id']}_H1_mdbc"
    command = [str(binaries / "GenCase_linux64"), str(definition.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError("H1 GenCase failed; inspect gencase.log")
    generated_xml = prefix.with_suffix(".xml")
    if not generated_xml.is_file() or not prefix.with_suffix(".bi4").is_file():
        raise RuntimeError("H1 GenCase did not create native outputs")
    decoder = lab / DECODER_RELATIVE
    with tempfile.TemporaryDirectory(prefix="f2-h1-mdbc-preflight-") as temp:
        ids, positions, velocities, density, metadata, _info, arrays = core_cfd.native_frame(
            prefix.with_suffix(".bi4"), Path(temp) / "native", decoder)
        fluid_count = int(metadata["CaseNfluid"])
        generated = ET.parse(generated_xml).getroot()
        fluid_groups = generated.findall(".//particles/fluid")
        expected_fluid = int(source["sampling"]["particle_count"])
        boundary_count = int(metadata.get("CaseNfixed", 0)) + int(metadata.get("CaseNmoving", 0))
        normals_path = arrays / "BoundNor.bin"
        normals = np.fromfile(normals_path, np.float32).reshape(-1, 3) if normals_path.exists() else np.empty((0, 3))
        checks = {
            "generated_fluid_particle_count_unchanged": len(fluid_groups) == 1 and int(fluid_groups[0].get("count", -1)) == expected_fluid,
            "native_fluid_particle_count_unchanged": fluid_count == expected_fluid,
            "native_ids_unique": len(np.unique(ids)) == len(ids),
            "native_arrays_finite": bool(np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all()),
            "mdbc_normals_present": normals_path.is_file(),
            "mdbc_normals_shape_matches_boundary": len(normals) == boundary_count,
            "mdbc_normals_nonzero_finite": bool(len(normals) == boundary_count and len(normals) > 0
                                                  and np.isfinite(normals).all()
                                                  and float(np.linalg.norm(normals, axis=1).min()) > 0.0),
        }
        sampling = source["sampling"]
        mass = {
            "source_relative_error": float(sampling["discrete_to_continuum_mass_error"]),
            "mass_rescaling": False,
            "mass_gate_pass": abs(float(sampling["discrete_to_continuum_mass_error"])) <= 0.03,
        }
        checks["mass_representation_gate"] = bool(mass["mass_gate_pass"])
        native = {"total_particles": int(len(ids)), "fluid_particles": fluid_count,
                  "boundary_particles": boundary_count, "normal_count": int(len(normals)),
                  "zero_boundary_normals": int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10)) if len(normals) else None,
                  "initial_fluid_speed_max_m_s": float(np.linalg.norm(velocities[-expected_fluid:], axis=1).max(initial=0.0))}
    inputs = {str(path.resolve()): digest(path) for path in output.rglob("*") if path.is_file()}
    for path in (source_prepared, source_definition, decoder, binaries / "GenCase_linux64", binaries / "DualSPHysics5.4_linux64"):
        inputs[str(path.resolve())] = digest(path)
    prepared = {
        "schema": SCHEMA, "created_at": stamp(), "family": "F2", "scope_id": SCOPE_ID,
        "repair_id": REPAIR_ID, "cell_index": CELL_INDEX, "case_id": source["case_id"],
        "source_prepared": ref(source_prepared, "v4 DBC cell-0 preparation"),
        "source_prepared_sha256": digest(source_prepared), "definition_audit": definition_audit,
        "generated_prefix": str(prefix.resolve()), "motion": ref(motion, "zero-angle motion"),
        "sampling": sampling, "native_initial": native, "mass_preflight": mass,
        "checks": checks, "preflight_pass": bool(all(checks.values())),
        "inputs": inputs, "solver_binary": str((binaries / "DualSPHysics5.4_linux64").resolve()),
        "solver_sha256": digest(binaries / "DualSPHysics5.4_linux64"), "decoder": str(decoder.resolve()),
        "decoder_sha256": digest(decoder), "solver_arguments": ["-mdbc_noslip:1"],
        "solver_invoked": False, "gpu_invoked": False, "queue_mutated": False,
        "ledger_mutated": False, "registry_mutated": False, "qualification_claim": "none; H1 CPU/native repair preflight only",
        "qualified": False,
    }
    write_json(output / "prepared.json", prepared)
    return prepared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--source-prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    value = prepare(lab=args.lab_root, source_prepared=args.source_prepared, output=args.output)
    print(json.dumps({"repair_id": value["repair_id"], "preflight_pass": value["preflight_pass"],
                      "qualification_claim": value["qualification_claim"], "checks": value["checks"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
