#!/usr/bin/env python3
"""CPU/native preflight for the repaired F3 mDBC baffle source.

Revision v2 is an independent prepared input.  It keeps the F3 baffle
geometry and the fixed 15-row design, but adds the geometry command list and
``<normals>`` contract required by DualSPHysics mDBC.  The preflight invokes
GenCase and the native BI4 decoder only; it never launches the solver, a GPU,
the coordinator, a ledger, or a scientific registry.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import core_cfd
from scripts import core_f3_baffled_source_scope_preflight_v1 as base


SCHEMA = base.SCHEMA
FAMILY = base.FAMILY
SCOPE_ID = base.SCOPE_ID
REVISION_ID = "F3_baffle_exchange_native_mdbc_normals_v2"
PARENT_REVISION_ID = base.REVISION_ID
QUALIFICATION_CLAIM = base.QUALIFICATION_CLAIM
NORMAL_CONTRACT = {
    "geometry_list": "GeometryForNormals",
    "outer_mkbound": "0",
    "outer_faces": "bottom | left | right | front | back",
    "baffle_mkbound": "1",
    "baffle_faces": "top | left | right | front | back",
    "shapeout": "hdp",
    "normal_layers_vdp": "-0.5",
    "distanceh": 2.0,
    "svshapes": True,
    "geometry_file": "[CaseName]_hdp_Actual.vtk",
}


def _normal_drawbox(parent: ET.Element, *, fill: str, low: np.ndarray,
                    size: np.ndarray) -> None:
    draw = ET.SubElement(parent, "drawbox")
    ET.SubElement(draw, "boxfill").text = fill
    ET.SubElement(draw, "point", {axis: f"{float(value):.17g}"
                                   for axis, value in zip("xyz", low)})
    ET.SubElement(draw, "size", {axis: f"{float(value):.17g}"
                                  for axis, value in zip("xyz", size)})
    ET.SubElement(draw, "layers", {"vdp": "-0.5"})


def _rewrite_definition_with_normals(source: Path, target: Path, *, dp_m: float,
                                     amplitude: float, output_interval_s: float,
                                     time_max_s: float, cfl: float) -> None:
    """Apply the v1 source recipe and add the official mDBC normal source."""
    base._rewrite_definition(source, target, dp_m=dp_m, amplitude=amplitude,
                             output_interval_s=output_interval_s,
                             time_max_s=time_max_s, cfl=cfl)
    tree = ET.parse(target)
    root = tree.getroot()
    geometry = root.find("./casedef/geometry")
    commands = geometry.find("commands") if geometry is not None else None
    mainlist = commands.find("mainlist") if commands is not None else None
    if commands is None or mainlist is None:
        raise ValueError("baffle definition has no geometry command lists")
    if commands.find("list[@name='GeometryForNormals']") is not None:
        raise ValueError("normal geometry list already exists")

    normal_list = ET.Element("list", {"name": "GeometryForNormals"})
    ET.SubElement(normal_list, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    ET.SubElement(normal_list, "setshapemode").text = "actual | bound"
    ET.SubElement(normal_list, "setnormalinvert", {"invert": "true"})
    ET.SubElement(normal_list, "setmkbound", {"mk": "0"})
    _normal_drawbox(normal_list, fill="bottom | left | right | front | back",
                    low=np.asarray([0.0, 0.0, 0.0]),
                    size=np.asarray([1.2, 0.4, 0.6]))
    ET.SubElement(normal_list, "setmkbound", {"mk": "1"})
    _normal_drawbox(normal_list, fill="top | left | right | front | back",
                    low=base.BAFFLE_LOW, size=base.BAFFLE_SIZE)
    ET.SubElement(normal_list, "shapeout", {"file": "hdp"})
    ET.SubElement(normal_list, "resetdraw")
    commands.insert(0, normal_list)
    mainlist.insert(0, ET.Element("runlist", {"name": "GeometryForNormals"}))
    # The normal source is separate from the particle shell.  The shell still
    # needs the official mDBC support layers so every fixed particle receives
    # a normal.  The outer wall layers point into the fluid; the internal
    # baffle layers point into its void precursor.
    main_drawboxes = mainlist.findall("drawbox")
    if len(main_drawboxes) != 4:
        raise ValueError("baffle mainlist changed while adding mDBC layers")
    outer_layers = main_drawboxes[1].find("layers")
    if outer_layers is None:
        outer_layers = ET.SubElement(main_drawboxes[1], "layers")
    outer_layers.set("vdp", "0,1,2")
    baffle_layers = main_drawboxes[3].find("layers")
    if baffle_layers is None:
        baffle_layers = ET.SubElement(main_drawboxes[3], "layers")
    baffle_layers.set("vdp", "0,-1,-2")
    boundary_shapeout = ET.Element("_shapeout", {"file": "parts"})
    mainlist.insert(list(mainlist).index(main_drawboxes[1]) + 1, boundary_shapeout)

    casedef = root.find("./casedef")
    if casedef is None:
        raise ValueError("baffle definition has no casedef")
    if casedef.find("normals") is not None:
        raise ValueError("baffle definition already has a normals block")
    normals = ET.SubElement(casedef, "normals", {"active": "true"})
    norgeometry = ET.SubElement(normals, "norgeometry")
    ET.SubElement(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    ET.SubElement(norgeometry, "distanceh", {"v": "2.0"})
    ET.SubElement(norgeometry, "svshapes", {"v": "true"})
    ET.indent(tree, space="  ")
    tree.write(target, encoding="utf-8", xml_declaration=True)


def _assert_normal_contract(definition: Path) -> dict[str, Any]:
    root = ET.parse(definition).getroot()
    normal_list = root.find("./casedef/geometry/commands/list[@name='GeometryForNormals']")
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if normal_list is None or mainlist is None:
        raise ValueError("GeometryForNormals/mainlist missing")
    runlists = [node for node in mainlist.findall("runlist") if node.get("name") == "GeometryForNormals"]
    if len(runlists) != 1 or list(mainlist).index(runlists[0]) != 0:
        raise ValueError("GeometryForNormals is not the leading mainlist runlist")
    setmk = normal_list.findall("setmkbound")
    if [node.get("mk") for node in setmk] != ["0", "1"]:
        raise ValueError("normal list must cover outer mkbound=0 then baffle mkbound=1")
    drawboxes = normal_list.findall("drawbox")
    if len(drawboxes) != 2:
        raise ValueError("normal list must have one outer and one baffle drawbox")
    fills = [" ".join((node.findtext("boxfill") or "").split()) for node in drawboxes]
    if fills != [NORMAL_CONTRACT["outer_faces"], NORMAL_CONTRACT["baffle_faces"]]:
        raise ValueError("normal list faces do not bind outer tank and baffle")
    layers = [node.find("layers") for node in drawboxes]
    if any(node is None or node.get("vdp") != "-0.5" for node in layers):
        raise ValueError("normal drawboxes must use the registered vdp=-0.5 layer")
    shapeout = normal_list.find("shapeout")
    if shapeout is None or shapeout.get("file") != "hdp":
        raise ValueError("normal list must save hdp geometry")
    normals = root.find("./casedef/normals")
    norgeometry = normals.find("norgeometry") if normals is not None else None
    geometryfile = norgeometry.find("geometryfile") if norgeometry is not None else None
    distanceh = norgeometry.find("distanceh") if norgeometry is not None else None
    svshapes = norgeometry.find("svshapes") if norgeometry is not None else None
    if (normals is None or normals.get("active") != "true" or norgeometry is None
            or geometryfile is None or geometryfile.get("file") != "[CaseName]_hdp_Actual.vtk"
            or distanceh is None or distanceh.get("v") != "2.0"
            or svshapes is None or svshapes.get("v") != "true"):
        raise ValueError("mDBC normals block is incomplete")
    return {
        **NORMAL_CONTRACT,
        "active": True,
        "normal_list_drawboxes": 2,
        "runlist_in_mainlist": True,
    }


def prepare_anchor(lab_root: Path, output: Path, *, q: float = 0.5,
                   dp_m: float = 0.0075,
                   output_interval_s: float = base.DEFAULT_OUTPUT_INTERVAL_S,
                   time_max_s: float = base.TIME_MAX_S,
                   cfl: float = base.DEFAULT_CFL) -> dict[str, Any]:
    """Create a fresh v2 prepared anchor and close its CPU/native inputs."""
    lab_root = Path(lab_root).resolve()
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"preflight output must be fresh: {output}")
    if not math.isclose(float(dp_m), 0.0075, abs_tol=1e-12):
        raise ValueError("the bounded preflight is registered only at dp=.0075")
    if not math.isclose(float(output_interval_s), 0.01, abs_tol=1e-12):
        raise ValueError("the bounded preflight is registered only at native .01 s")
    if not math.isclose(float(time_max_s), base.TIME_MAX_S, abs_tol=1e-12):
        raise ValueError("the source scope requires the complete 8.35 s window")
    amplitude = base.amplitude_from_q(q)
    source = base._lab_path(lab_root, base.BASE_DEFINITION_REL)
    solver = base._lab_path(lab_root, base.SOLVER_REL)
    gencase = base._lab_path(lab_root, base.GENCASE_REL)
    decoder = base._lab_path(lab_root, base.DECODER_REL)
    for path in (source, solver, gencase, decoder):
        if not path.is_file():
            raise FileNotFoundError(path)
    output.mkdir(parents=True, exist_ok=True)
    case_id = (f"CORE_F3_BAFFLE_EXCHANGE_q{float(q):.8f}_dp{float(dp_m):.12f}_"
               "anchor_normals_v2").replace(".", "p")
    definition = output / f"{case_id}_Def.xml"
    _rewrite_definition_with_normals(source, definition, dp_m=float(dp_m),
                                     amplitude=amplitude,
                                     output_interval_s=float(output_interval_s),
                                     time_max_s=float(time_max_s), cfl=float(cfl))
    geometry = base._assert_baffle_contract(definition, dp_m=float(dp_m))
    geometry["normal_geometry"] = _assert_normal_contract(definition)
    generated_prefix = output / "generated" / case_id
    generated_prefix.parent.mkdir(parents=True, exist_ok=True)
    log_path = output / "gencase.log"
    command = [str(gencase), str(definition.with_suffix("")), str(generated_prefix), "-save:all"]
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=output, env=base._environment(lab_root),
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"GenCase failed; inspect {log_path}")
    generated_xml = generated_prefix.with_suffix(".xml")
    generated_bi4 = generated_prefix.with_suffix(".bi4")
    generated_vtk = [generated_prefix.with_name(generated_prefix.name + suffix)
                     for suffix in ("_All.vtk", "_Bound.vtk", "_Fluid.vtk", "_MkCells.vtk")]
    normal_vtk = generated_prefix.with_name(generated_prefix.name + "_hdp_Actual.vtk")
    required_generated = [generated_xml, generated_bi4, *generated_vtk, normal_vtk]
    if not all(path.is_file() for path in required_generated):
        raise ValueError("GenCase did not produce the complete normal-aware static artifact set")
    # GenCase serializes the normal field in the native BI4 and the
    # ``*_hdp_Actual.vtk`` sidecar; it does not repeat the Def-file
    # ``casedef/normals`` element under ``execution`` in the generated XML.
    # Require the hash-bound sidecar and retain the generator's normal
    # diagnostics instead of looking for a node that GenCase never emits.
    generated_root = ET.parse(generated_xml).getroot()
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    if "Computing normals" not in log_text or "Non-zero particle normals" not in log_text:
        raise ValueError("GenCase log lacks mDBC normal-generation evidence")
    total_particles, boundary_particles, fluid_particles = base._fluid_count_from_generated(generated_xml)
    with tempfile.TemporaryDirectory(prefix="core-f3-baffle-v2-initial-") as temp:
        ids, position, velocity, density, metadata, info, arrays = core_cfd.native_frame(
            generated_bi4, Path(temp) / "native", decoder
        )
    if len(ids) != total_particles or len(np.unique(ids)) != len(ids):
        raise ValueError("native initial identities do not close or are not unique")
    if not all(np.isfinite(array).all() for array in (position, velocity, density)):
        raise ValueError("native initial state contains nonfinite values")
    if (int(metadata.get("CaseNfixed", -1)) != boundary_particles
            or int(metadata.get("CaseNfluid", -1)) != fluid_particles):
        raise ValueError("native decoder metadata disagrees with GenCase particle summary")
    fluid_velocity = velocity[boundary_particles:boundary_particles + fluid_particles]
    fluid_velocity_error = float(np.max(np.abs(fluid_velocity[:, 0] - amplitude)))
    fluid_transverse_max = float(np.max(np.abs(fluid_velocity[:, 1:])))
    if fluid_velocity_error > 1e-6 or fluid_transverse_max > 1e-6:
        raise ValueError("native initial fluid velocity does not match the new impulse axis")
    fluid_volume = float((base.BASE_FLUID_SIZE[0] - base.BAFFLE_SIZE[0])
                         * base.BASE_FLUID_SIZE[1] * base.BASE_FLUID_SIZE[2])
    continuous_mass = float(fluid_volume * base.RHO0)
    discrete_mass = float(fluid_particles * float(dp_m) ** 3 * base.RHO0)
    mass_error = discrete_mass / continuous_mass - 1.0
    mass_pass = bool(math.isfinite(mass_error) and abs(mass_error) <= 0.03)
    if not mass_pass:
        raise ValueError(f"native source mass representation failed: {mass_error}")
    files = [definition, log_path, *required_generated]
    inputs = {str(path.resolve()): base.digest(path) for path in files}
    prepared = {
        "schema": SCHEMA, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "prepared_only", "execution_status": "prepared_only",
        "launch_allowed": False, "qualification_claim": QUALIFICATION_CLAIM,
        "scope_id": SCOPE_ID, "revision_id": REVISION_ID,
        "parent_revision_id": PARENT_REVISION_ID, "case_id": case_id, "family": FAMILY,
        "source_asset_id": "f3_baffle_exchange_q0p5_dp0p0075_anchor_normals_v2",
        "parameter": {"name": "initial_impulse_velocity_x_m_s", "q": float(q),
                      "value": amplitude, "range_m_s": [0.45, 1.05],
                      "mapping": "u0_x = 0.45 + 0.60*q"},
        "recipe": {"boundary_method": 2, "solver_arguments": ["-mdbc_noslip:1"],
                   "boundary_semantics": "native mDBC/no-slip with finite outer tank and an internal mkbound=1 baffle",
                   "gravity_m_s2": [0.0, 0.0, -9.81], "dp_m": float(dp_m), "cfl": float(cfl),
                   "output_interval_s": float(output_interval_s), "time_max_s": float(time_max_s),
                   "mass_policy": "native rho*dp^3; no rescaling", "shifting": 0,
                   "visco_treatment": 1, "visco": 0.05, "normal_geometry": NORMAL_CONTRACT},
        "geometry": geometry,
        "normal_geometry": NORMAL_CONTRACT,
        "novelty_contract": {"source_repair": "explicit mDBC normal geometry for outer mkbound=0 faces and internal mkbound=1 baffle",
                              "parent_revision_id": PARENT_REVISION_ID,
                              "legacy_trajectory_reused": False, "legacy_bi4_reused": False},
        "source_provenance": {
            "legacy_definition_path": str(source), "legacy_definition_sha256": base.digest(source),
            "core_preflight_runner_path": str(Path(__file__).resolve()),
            "core_preflight_runner_sha256": base.digest(Path(__file__)),
            "parent_preflight_runner_path": str(Path(base.__file__).resolve()),
            "parent_preflight_runner_sha256": base.digest(Path(base.__file__)),
            "core_conversion_helper_path": str(Path(core_cfd.__file__).resolve()),
            "core_conversion_helper_sha256": base.digest(Path(core_cfd.__file__)),
            "solver_path": str(solver), "solver_sha256": base.digest(solver),
            "gencase_path": str(gencase), "gencase_sha256": base.digest(gencase),
            "decoder_path": str(decoder), "decoder_sha256": base.digest(decoder),
        },
        "sampling": {"continuous_fluid_box_low_m": base.BASE_FLUID_LOW.tolist(),
                     "continuous_fluid_box_size_m": base.BASE_FLUID_SIZE.tolist(),
                     "baffle_overlap_removed_from_fluid_volume_m3": float(base.BAFFLE_SIZE[0] * base.BASE_FLUID_SIZE[1] * base.BASE_FLUID_SIZE[2]),
                     "fluid_particles": fluid_particles, "boundary_particles": boundary_particles,
                     "total_particles": total_particles, "continuous_mass_kg": continuous_mass,
                     "discrete_native_mass_kg": discrete_mass, "relative_mass_error": mass_error,
                     "mass_gate_pass": mass_pass, "mass_rescaling": False},
        "native_initial": {"initial_time_s": float(info.get("TimeStep", 0.0)),
                           "fluid_particles": fluid_particles, "boundary_particles": boundary_particles,
                           "total_particles": total_particles, "unique_particle_ids": True,
                           "finite_position_velocity_density": True, "fluid_velocity_x_m_s": amplitude,
                           "fluid_velocity_max_abs_error_m_s": fluid_velocity_error,
                           "fluid_transverse_velocity_max_abs_m_s": fluid_transverse_max,
                           "initial_state_pass": True},
        "generated_prefix": str(generated_prefix.resolve()), "inputs": inputs,
        "solver_binary": str(solver), "solver_sha256": base.digest(solver),
        "decoder": str(decoder), "decoder_sha256": base.digest(decoder),
        "execution_controls": {"cpu_gencase_invoked": True, "cpu_native_decode_invoked": True,
                               "solver_invoked": False, "gpu_invoked": False,
                               "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0,
                               "qualification_numerator_credit": 0},
        "preflight_pass": True, "solver_product_present": False,
        "downstream": {"consumer": "future root-reviewed F3 baffle qualification runtime/audit only",
                       "required_before_solver": ["new root approval for this normals-aware revision",
                                                   "fresh immutable job spec bound to this prepared hash",
                                                   "15-row matrix and failure denominator remain frozen",
                                                   "runtime hard-integrity, obstacle and event/time audit"],
                       "forbidden_until_approval": ["solver", "GPU", "queue", "ledger", "registry", "material training"]},
    }
    base._write_json(output / "prepared.json", prepared)
    return prepared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--q", type=float, default=0.5)
    parser.add_argument("--dp", type=float, default=0.0075)
    args = parser.parse_args(argv)
    prepared = prepare_anchor(args.lab_root, args.output, q=args.q, dp_m=args.dp)
    print({"status": prepared["status"], "revision_id": prepared["revision_id"],
           "case_id": prepared["case_id"],
           "prepared_sha256": base.digest(args.output / "prepared.json"),
           "fluid_particles": prepared["sampling"]["fluid_particles"],
           "normal_geometry": prepared["normal_geometry"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
