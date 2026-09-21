#!/usr/bin/env python3
"""Root-locked CPU/native preflight for one fresh submerged-orifice anchor.

The root review emitted by this module authorizes exactly one new Definition
at q=.5, dp=.0075.  ``prepare-anchor`` runs only the CPU GenCase executable
and the native BI4 decoder, then writes a hash-bound preflight record.  It
never calls DualSPHysics, touches CUDA, creates a job, or mutates queue,
ledger, registry, or qualification state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
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

from scripts.core_cfd import digest, lattice_box, native_frame, write_json
from scripts.f2_submerged_orifice_scope_v1 import (
    DEFAULT_BASE,
    EXPECTED_ROWS,
    REVISION_ID,
    SCOPE_ID,
    load_json,
    verify_bundle,
)
from scripts.finite_wall_audit import wall_penetration


ROOT_REVIEW_SCHEMA = "core.f2.submerged_orifice_transfer.root_review.v1"
PREFLIGHT_SCHEMA = "core.f2.submerged_orifice_transfer.cpu_native_preflight.v1"
ANCHOR_INDEX = 4
ANCHOR_Q = 0.5
ANCHOR_DP = 0.0075
ANCHOR_ORIFICE_HEIGHT = 0.18
CREATED_AT = "2026-09-21T00:00:00+00:00"
# Bind the fresh input to the already registered matrix row.  The row identity
# is deliberately reused as a label only; no generated asset or old Definition
# is reused, and the preflight writes a new literal Definition below.
CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial"


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else LAB_ROOT / path).resolve()


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _verify_ref(item: dict[str, Any], label: str) -> Path:
    path = Path(item.get("path", "")).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != digest(path):
        raise ValueError(f"{label} hash mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label} byte count mismatch")
    return path


def _base_paths(base: Path) -> dict[str, Path]:
    return {
        "candidate": base / "candidate-card-v1.json",
        "matrix": base / "fixed-matrix-v1.json",
        "failure": base / "failure-denominator-v1.json",
        "lineage": base / "lineage-clarification-v1.json",
        "contract": base / "root-review-contract-v1.json",
    }


def _review_bindings(base: Path) -> dict[str, Any]:
    paths = _base_paths(base)
    bundle = verify_bundle(base)
    if bundle["status"] != "root_review_only_contract_verified":
        raise ValueError("candidate bundle did not pass independent contract verification")
    rows = load_json(paths["matrix"])["rows"]
    row = next((item for item in rows if int(item["index"]) == ANCHOR_INDEX), None)
    if row is None:
        raise ValueError("authorized matrix row is missing")
    if float(row["q"]) != ANCHOR_Q or float(row["dp_m"]) != ANCHOR_DP or row["status"] != "not_started":
        raise ValueError("authorized row is not the fresh q=.5 dp=.0075 anchor")
    if row["case_id"] != CASE_ID:
        raise ValueError(f"matrix row case id mismatch: {row['case_id']} != {CASE_ID}")
    return {
        "candidate": _ref(paths["candidate"], "candidate card"),
        "matrix": _ref(paths["matrix"], "fixed 15-row matrix"),
        "failure_denominator": _ref(paths["failure"], "zero-credit failure denominator"),
        "lineage": _ref(paths["lineage"], "lineage clarification"),
        "contract": _ref(paths["contract"], "review-only contract"),
        "scope_adapter": _ref(LAB_ROOT / "scripts/f2_submerged_orifice_scope_v1.py", "scope contract adapter"),
        "preflight_adapter": _ref(Path(__file__).resolve(), "CPU/native preflight adapter"),
        "authorized_row": {
            "index": ANCHOR_INDEX,
            "q": ANCHOR_Q,
            "dp_m": ANCHOR_DP,
            "orifice_height_m": float(row["orifice_height_m"]),
            "case_id": CASE_ID,
        },
    }


def write_root_review(base: Path = DEFAULT_BASE, output: Path | None = None) -> dict[str, Any]:
    """Write a root-review decision that authorizes CPU/native preparation only."""
    base = Path(base).resolve()
    bindings = _review_bindings(base)
    prior = load_json(base / "root-review-contract-v1.json")["hash_bindings"]["prior_failures"]
    review = {
        "schema": ROOT_REVIEW_SCHEMA,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "decision": "approved_for_one_anchor_cpu_native_preflight",
        "status": "cpu_native_only_no_runtime_authority",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "authorized_anchor": True,
        "authorized_matrix_indices": [ANCHOR_INDEX],
        "authorized_case_ids": [CASE_ID],
        "authorization": {
            "cpu_gencase": True,
            "native_decode": True,
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "hash_bindings": bindings,
        "prior_failure_bindings": prior,
        "fresh_anchor": {
            "q": ANCHOR_Q,
            "dp_m": ANCHOR_DP,
            "orifice_height_m": ANCHOR_ORIFICE_HEIGHT,
            "case_id": CASE_ID,
            "definition_path": str((base / "anchor-q0p5-dp0p0075" / f"{CASE_ID}_Def.xml").resolve()),
            "generated_prefix": str((base / "anchor-q0p5-dp0p0075" / "generated" / CASE_ID).resolve()),
            "fresh_definition_required": True,
            "old_failed_input_reuse": False,
        },
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
        "protected_next_step": "run prepare-anchor once; then review the fresh CPU/native preflight before any solver decision",
        "prohibited_until_new_review": ["solver", "GPU", "job creation", "queue", "ledger", "registry", "matrix expansion"],
    }
    if output is None:
        output = base / "root-review-cpu-preflight-v1.json"
    write_json(Path(output), review)
    return review


def verify_root_review(review_path: Path, base: Path = DEFAULT_BASE) -> dict[str, Any]:
    review_path = Path(review_path).resolve()
    base = Path(base).resolve()
    review = load_json(review_path)
    if review.get("schema") != ROOT_REVIEW_SCHEMA:
        raise ValueError("root review schema mismatch")
    if review.get("decision") != "approved_for_one_anchor_cpu_native_preflight":
        raise ValueError("root review does not authorize CPU/native preflight")
    if review.get("scope_id") != SCOPE_ID or review.get("revision_id") != REVISION_ID:
        raise ValueError("root review scope/revision mismatch")
    if review.get("qualification_claim") != "none" or review.get("matrix_credit") != 0:
        raise ValueError("root review credit boundary is open")
    if review.get("authorized_anchor") is not True or review.get("authorized_matrix_indices") != [ANCHOR_INDEX]:
        raise ValueError("root review does not authorize exactly one anchor")
    auth = review.get("authorization", {})
    if auth.get("cpu_gencase") is not True or auth.get("native_decode") is not True:
        raise ValueError("root review does not authorize CPU/native preparation")
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"root review opened: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"root review opened: {key}")
    bindings = review.get("hash_bindings", {})
    expected = _review_bindings(base)
    for key in ("candidate", "matrix", "failure_denominator", "lineage", "contract", "scope_adapter", "preflight_adapter"):
        actual = bindings.get(key, {})
        _verify_ref(actual, f"root review {key}")
        if actual.get("sha256") != expected[key]["sha256"]:
            raise ValueError(f"root review {key} is stale")
    authorized = bindings.get("authorized_row", {})
    if authorized != expected["authorized_row"]:
        raise ValueError("root review authorized row binding mismatch")
    fresh = review.get("fresh_anchor", {})
    if fresh.get("case_id") != CASE_ID or fresh.get("old_failed_input_reuse") is not False:
        raise ValueError("fresh anchor identity/reuse boundary failed")
    return review


def _sub(parent: ET.Element, tag: str, attributes: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, tag, attributes or {})
    if text is not None:
        node.text = text
    return node


def _drawbox(parent: ET.Element, fill: str, low: list[float], size: list[float], layers: str | None) -> None:
    node = _sub(parent, "drawbox")
    _sub(node, "boxfill", text=fill)
    _sub(node, "point", {axis: f"{value:.17g}" for axis, value in zip("xyz", low)})
    _sub(node, "size", {axis: f"{value:.17g}" for axis, value in zip("xyz", size)})
    if layers is not None:
        _sub(node, "layers", {"vdp": layers})


def _parameter(parameters: ET.Element, key: str, value: str) -> None:
    _sub(parameters, "parameter", {"key": key, "value": value})


def write_definition(target: Path) -> dict[str, Any]:
    """Create the new q=.5, dp=.0075 Definition from literal geometry."""
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("case")
    casedef = _sub(root, "casedef")
    constants = _sub(casedef, "constantsdef")
    _sub(constants, "gravity", {"x": "0", "y": "0", "z": "-9.81"})
    _sub(constants, "rhop0", {"value": "1000"})
    _sub(constants, "rhopgradient", {"value": "2"})
    _sub(constants, "hswl", {"value": "0", "auto": "true"})
    _sub(constants, "gamma", {"value": "7"})
    _sub(constants, "speedsystem", {"value": "0", "auto": "true"})
    _sub(constants, "coefsound", {"value": "20"})
    _sub(constants, "speedsound", {"value": "0", "auto": "true"})
    _sub(constants, "coefh", {"value": "1.0"})
    _sub(constants, "cflnumber", {"value": "0.2"})
    _sub(casedef, "mkconfig", {"boundcount": "220", "fluidcount": "16"})
    geometry = _sub(casedef, "geometry")
    definition = _sub(geometry, "definition", {"dp": f"{ANCHOR_DP:.17g}"})
    _sub(definition, "pointmin", {"x": "-0.30", "y": "-0.15", "z": "-0.15"})
    _sub(definition, "pointmax", {"x": "1.90", "y": "0.65", "z": "1.20"})
    _sub(definition, "pointref", {axis: f"{ANCHOR_DP / 2:.17g}" for axis in "xyz"})
    commands = _sub(geometry, "commands")
    normals = _sub(commands, "list", {"name": "GeometryForNormals"})
    _sub(normals, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    _sub(normals, "setshapemode", text="actual | bound")
    _sub(normals, "setnormalinvert", {"invert": "true"})
    _sub(normals, "setmkbound", {"mk": "0"})
    _drawbox(normals, "bottom | left | right | front | back", [0.0, 0.0, 0.0], [1.6, 0.5, 0.8], "-0.5")
    _sub(normals, "setmkbound", {"mk": "1"})
    _sub(normals, "setnormalinvert", {"invert": "false"})
    _drawbox(normals, "bottom | top | left | right | front | back", [0.72, 0.04, ANCHOR_ORIFICE_HEIGHT], [0.06, 0.42, 0.8 - ANCHOR_ORIFICE_HEIGHT], "-0.5")
    _sub(normals, "shapeout", {"file": "hdp"})
    _sub(normals, "resetdraw")
    main = _sub(commands, "mainlist")
    _sub(main, "runlist", {"name": "GeometryForNormals"})
    _sub(main, "setshapemode", text="actual | bound")
    _sub(main, "setdrawmode", {"mode": "full"})
    _sub(main, "setmkbound", {"mk": "0"})
    _drawbox(main, "bottom | left | right | front | back", [0.0, 0.0, 0.0], [1.6, 0.5, 0.8], "0,1,2")
    _sub(main, "setmkbound", {"mk": "1"})
    _drawbox(main, "bottom | top | left | right | front | back", [0.72, 0.04, ANCHOR_ORIFICE_HEIGHT], [0.06, 0.42, 0.8 - ANCHOR_ORIFICE_HEIGHT], "0,1,2")
    _sub(main, "setmkfluid", {"mk": "0"})
    source = lattice_box([0.04, 0.04, 0.04], [0.64, 0.42, 0.36], ANCHOR_DP)
    _drawbox(main, "solid", source["first_center_m"], source["draw_size_m"], None)
    parameters_parent = _sub(root, "execution")
    parameters = _sub(parameters_parent, "parameters")
    for key, value in (
        ("SavePosDouble", "2"), ("Boundary", "2"), ("SlipMode", "1"), ("StepAlgorithm", "2"),
        ("Kernel", "2"), ("ViscoTreatment", "1"), ("Visco", "0.03"), ("ViscoBoundFactor", "1"),
        ("DensityDT", "3"), ("DensityDTvalue", "0.1"), ("Shifting", "0"), ("RigidAlgorithm", "1"),
        ("FtPause", "0"), ("CoefDtMin", "0.05"), ("DtIni", "0"), ("DtMin", "0"),
        ("DtFixed", "0"), ("DtAllParticles", "0"), ("TimeMax", "1.5"), ("TimeOut", "0.01"),
        ("PartsOutMax", "1"), ("RhopOutMin", "700"), ("RhopOutMax", "1300"), ("MinFluidStop", "0"),
    ):
        _parameter(parameters, key, value)
    domain = _sub(parameters, "simulationdomain")
    _sub(domain, "posmin", {"x": "-0.30", "y": "-0.15", "z": "-0.15"})
    _sub(domain, "posmax", {"x": "1.90", "y": "0.65", "z": "1.20"})
    normals_config = _sub(casedef, "normals", {"active": "true"})
    norgeometry = _sub(normals_config, "norgeometry")
    _sub(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    _sub(norgeometry, "distanceh", {"v": "3.0"})
    _sub(norgeometry, "svshapes", {"v": "true"})
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {"path": str(target), "sha256": digest(target), "source_sampling": source}


def _wall_spec() -> dict[str, Any]:
    return {
        "container_interior": {"xmin": 0.0, "xmax": 1.6, "ymin": 0.0, "ymax": 0.5, "zmin": 0.0, "zmax": 0.8},
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "obstacles": [{"id": "upper_gate_slab", "xmin": 0.72, "xmax": 0.78, "ymin": 0.04, "ymax": 0.46, "zmin": ANCHOR_ORIFICE_HEIGHT, "zmax": 0.8}],
        "runtime_domain": {"xmin": -0.30, "xmax": 1.90, "ymin": -0.15, "ymax": 0.65, "zmin": -0.15, "zmax": 1.20},
    }


def _generated_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles section")
    blocks = particles.findall("fluid")
    if len(blocks) != 1:
        raise ValueError("expected exactly one generated fluid block")
    fluid = blocks[0]
    fixed = particles.findall("fixed")
    if len(fixed) != 2:
        raise ValueError("expected outer and upper-gate fixed blocks")
    return {
        "total_particles": int(particles.get("np")),
        "boundary_particles": int(particles.get("nb")),
        "fluid_particles": int(fluid.get("count")),
        "outer_boundary_particles": int(fixed[0].get("count")),
        "gate_boundary_particles": int(fixed[1].get("count")),
        "fluid_begin": int(fluid.get("begin")),
    }


def prepare_anchor(base: Path = DEFAULT_BASE, review_path: Path | None = None, output: Path | None = None) -> dict[str, Any]:
    """Run only fresh CPU GenCase and native decode after root review."""
    base = Path(base).resolve()
    if review_path is None:
        review_path = base / "root-review-cpu-preflight-v1.json"
    review = verify_root_review(Path(review_path), base)
    if output is None:
        output = base / "anchor-q0p5-dp0p0075"
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"preflight output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    definition = output / f"{CASE_ID}_Def.xml"
    generation_dir = output / "generated"
    generation_dir.mkdir(parents=True, exist_ok=True)
    prefix = generation_dir / CASE_ID
    definition_record = write_definition(definition)
    binaries = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux"
    gencase = binaries / "GenCase_linux64"
    decoder = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
    if not gencase.is_file() or not decoder.is_file():
        raise FileNotFoundError("CPU GenCase or native decoder is missing")
    gencase_log = output / "gencase.log"
    command = [str(gencase), str(definition.with_suffix("")), str(prefix), "-save:all"]
    with gencase_log.open("w") as stream:
        process = subprocess.run(command, cwd=output, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"GenCase failed with return code {process.returncode}")
    generated_xml = prefix.with_suffix(".xml")
    native_bi4 = prefix.with_suffix(".bi4")
    metadata_xml = prefix.with_name(prefix.name + "_.xml")
    counts = _generated_counts(generated_xml)
    source = definition_record["source_sampling"]
    if counts["fluid_particles"] != int(source["particle_count"]):
        raise ValueError(f"generated fluid count differs: {counts['fluid_particles']} vs {source['particle_count']}")
    with tempfile.TemporaryDirectory(prefix="f2-orifice-native-") as temp:
        ids, positions, velocities, density, metadata, info, arrays = native_frame(native_bi4, Path(temp) / "initial", decoder)
        normal_file = arrays / "BoundNor.bin"
        normals = np.fromfile(normal_file, np.float32).reshape(-1, 3) if normal_file.exists() else np.empty((0, 3))
        fluid_begin = counts["fluid_begin"]
        fluid_ids = np.arange(fluid_begin, fluid_begin + counts["fluid_particles"], dtype=np.uint32)
        fluid_index = np.searchsorted(ids, fluid_ids)
        if not np.array_equal(ids[fluid_index], fluid_ids):
            raise ValueError("generated native fluid IDs do not match XML block")
        fluid_positions = positions[fluid_index]
        fluid_velocities = velocities[fluid_index]
        fluid_density = density[fluid_index]
        gate = wall_penetration(fluid_positions, np.ones(len(fluid_positions)), _wall_spec(), 1e-8)
        native = {
            "ids_unique": len(np.unique(ids)) == len(ids),
            "arrays_finite": bool(all(np.isfinite(array).all() for array in (positions, velocities, density))),
            "fluid_ids_match_generated_xml": True,
            "fluid_particles_decoded": int(len(fluid_positions)),
            "boundary_particles_decoded": int(counts["boundary_particles"]),
            "fluid_velocity_max_abs_m_s": float(np.max(np.abs(fluid_velocities), initial=0.0)),
            "fluid_density_finite": bool(np.isfinite(fluid_density).all()),
            "normal_file_present": bool(normal_file.exists()),
            "normal_count": int(len(normals)),
            "zero_boundary_normals": int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10)),
            "wall_endpoint_outer_count": int(gate["outside_closed_container_count"]),
            "gate_endpoint_penetration_count": int(gate["obstacle_penetration_count"]),
        }
    mass = float(metadata["MassFluid"]) * counts["fluid_particles"]
    continuous_mass = float(np.prod([0.64, 0.42, 0.36]) * 1000.0)
    mass_error = mass / continuous_mass - 1.0
    normal_ok = native["normal_file_present"] and native["normal_count"] == counts["boundary_particles"] and native["zero_boundary_normals"] == 0
    geometry_ok = native["wall_endpoint_outer_count"] == 0 and native["gate_endpoint_penetration_count"] == 0
    preflight_pass = bool(
        process.returncode == 0
        and native["ids_unique"]
        and native["arrays_finite"]
        and native["fluid_ids_match_generated_xml"]
        and native["fluid_particles_decoded"] == counts["fluid_particles"]
        and normal_ok
        and geometry_ok
        and abs(mass_error) <= 0.025
    )
    inputs = {}
    for path in (definition, gencase_log, generated_xml, native_bi4, metadata_xml, prefix.with_name(prefix.name + "_hdp_Actual.vtk"), prefix.with_name(prefix.name + "_Bound.vtk"), decoder):
        if path.is_file():
            inputs[str(path)] = digest(path)
    result = {
        "schema": PREFLIGHT_SCHEMA,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "status": "cpu_native_preflight_pass_anchor_only" if preflight_pass else "cpu_native_preflight_failed",
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "authorized_matrix_index": ANCHOR_INDEX,
        "case_id": CASE_ID,
        "q": ANCHOR_Q,
        "dp_m": ANCHOR_DP,
        "orifice_height_m": ANCHOR_ORIFICE_HEIGHT,
        "root_review": _ref(Path(review_path), "CPU/native-only root review"),
        "definition": _ref(definition, "fresh submerged-orifice Definition"),
        "generated_prefix": str(prefix),
        "generated_counts": counts,
        "native_initial": native,
        "mass_contract": {
            "continuous_source_mass_kg": continuous_mass,
            "discrete_native_mass_kg": mass,
            "relative_error": mass_error,
            "source_relative_error_max": 0.025,
            "pass": abs(mass_error) <= 0.025,
            "mass_rescaling": False,
            "policy": "native rho*dp^3",
        },
        "geometry_contract": {
            "new_upper_gate_slab_present": True,
            "submerged_aperture_open_below_m": ANCHOR_ORIFICE_HEIGHT,
            "initial_source_ends_before_gate": True,
            "outer_wall_endpoint_count": native["wall_endpoint_outer_count"],
            "gate_endpoint_penetration_count": native["gate_endpoint_penetration_count"],
        },
        "artifacts": {
            "definition": str(definition),
            "gencase_log": str(gencase_log),
            "native_bi4": str(native_bi4),
            "native_metadata": str(metadata_xml),
            "sha256": {path: value for path, value in inputs.items()},
        },
        "input_hashes": inputs,
        "execution_controls": {
            "cpu_gencase_invoked": True,
            "cpu_native_decode_invoked": True,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
        "solver_product_present": False,
        "preflight_pass": preflight_pass,
        "interpretation_boundary": "Fresh CPU/native input closure only; no solver trajectory, event result, qualification, or T1 credit.",
    }
    write_json(output / "preflight.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-root-review", "prepare-anchor", "verify-root-review"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write-root-review":
        result = write_root_review(args.base, args.output)
    elif args.command == "verify-root-review":
        result = verify_root_review(args.review or args.base / "root-review-cpu-preflight-v1.json", args.base)
    else:
        result = prepare_anchor(args.base, args.review, args.output)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result.get("preflight_pass", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
