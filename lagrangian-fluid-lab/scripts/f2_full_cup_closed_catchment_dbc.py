#!/usr/bin/env python3
"""Prepare the F2 full-cup moving catchment DBC boundary-formulation canary.

This is an independent physical scope.  It starts from the passed full-cup
v3 native initial state, keeps the cup, receiver, tray and prescribed motion,
adds four fixed outer-catchment walls, and changes only the boundary
formulation from the failed mDBC candidate to native DBC.  Preparation is
CPU-only; the worker
job uses the existing F2 qualification runner so its moving-body and
catchment-aware hard audit remains the single runtime audit owner.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

# Resolve code from this frozen source tree.  Asset paths are always explicit
# lab-root paths; do not insert a changing lab checkout ahead of this module.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_qualification as f2q


SCHEMA = "core.f2.full_cup_closed_catchment_dbc_boundary_repair.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REVISION_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2"
SCOPE_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_boundary_formulation_x_v1"
CASE_ID = "CORE_F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_q0p50000000_dp0p007500000000_canary_v2"
JOB_ID = "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-canary-v2-001"
DP_M = 0.0075
Q = 0.5
ROTATION_DURATION_S = 0.85
ANGLE_DEGREES = -105.0
MOTION_START_S = 0.50
TIME_MAX_S = 2.50
MAXIMUM_EXTENDED_TIME_S = 5.00
OUTPUT_INTERVAL_S = 0.01
RUNTIME_DOMAIN = {
    "posmin": [-0.70, -0.65, -0.40],
    "posmax": [2.20, 0.80, 2.40],
    "baseline_zmax_m": 1.80,
    "changed_zmax_m": 2.40,
    "change_is_computational_only": True,
}
STATIC_RELATIVE = "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_canary_v3/prepared.json"
STATIC_INTEGRATION_RELATIVE = "campaigns/core-v1/cfd/f2-full-cup-v3-static-hold-root-integration-v1.json"


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _set_parameter(root: ET.Element, key: str, value: str | int | float) -> None:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        params = root.find(".//execution/parameters")
        if params is None:
            raise ValueError(f"missing execution parameters for {key}")
        node = ET.SubElement(params, "parameter", {"key": key})
    node.set("value", str(value))


def _drawbox(parent: ET.Element, fill: str, low: list[float], size: list[float], layers: str) -> ET.Element:
    draw = ET.SubElement(parent, "drawbox")
    ET.SubElement(draw, "boxfill").text = fill
    ET.SubElement(draw, "point", {axis: f"{float(value):.17g}" for axis, value in zip("xyz", low)})
    ET.SubElement(draw, "size", {axis: f"{float(value):.17g}" for axis, value in zip("xyz", size)})
    ET.SubElement(draw, "layers", {"vdp": layers})
    return draw


def _append_catchment_walls(root: ET.Element, catchment: dict) -> dict:
    """Add four fixed side walls after the retained tray bottom."""
    main = root.find(".//geometry/commands/mainlist")
    if main is None:
        raise ValueError("source definition has no geometry mainlist")
    nodes = list(main)
    insert_at = None
    for index, node in enumerate(nodes):
        if node.tag == "setmkbound" and node.get("mk") == str(int(catchment["floor_material_mkbound"])):
            if index + 1 < len(nodes) and nodes[index + 1].tag == "drawbox":
                if (nodes[index + 1].findtext("boxfill") or "").strip() == "bottom":
                    insert_at = index + 2
                    break
    if insert_at is None:
        raise ValueError("retained tray bottom drawbox not found")
    wall_set = ET.Element("setmkbound", {"mk": str(int(catchment["mkbound"]))})
    wall_draw = ET.Element("drawbox")
    ET.SubElement(wall_draw, "boxfill").text = "left | right | front | back"
    ET.SubElement(wall_draw, "point", {axis: f"{float(value):.17g}" for axis, value in zip("xyz", catchment["low"])})
    ET.SubElement(wall_draw, "size", {axis: f"{float(value):.17g}" for axis, value in zip("xyz", catchment["size"])})
    ET.SubElement(wall_draw, "layers", {"vdp": "0,1,2"})
    main.insert(insert_at, wall_set)
    main.insert(insert_at + 1, wall_draw)
    return {
        "mkbound": int(catchment["mkbound"]),
        "floor_mkbound": int(catchment["floor_material_mkbound"]),
        "drawn_faces": ["left", "right", "front", "back"],
        "top_open": True,
        "retained_tray_bottom": True,
    }


def _dynamic_motion(path: Path) -> None:
    f2q._dynamic_motion(path, ROTATION_DURATION_S, ANGLE_DEGREES)


def _native_initial(prefix: Path, decoder: Path, expected_fluid: int, static_prefix: Path) -> dict:
    """Decode the DBC initial state and compare its fluid lattice to v3.

    DBC has no mDBC normal file.  The normal completeness gate is therefore
    explicitly not applicable; native identity, finite arrays, sampling and
    mass remain mandatory.
    """
    with tempfile.TemporaryDirectory(prefix="f2-full-cup-dbc-preflight-") as folder:
        ids, pos, vel, rho, metadata, _, arrays = core_cfd.native_frame(prefix.with_suffix(".bi4"), Path(folder) / "native", decoder)
        boundary_count = sum(int(metadata.get(name, 0)) for name in ("CaseNfixed", "CaseNmoving", "CaseNfloat"))
        fluid_count = int(metadata.get("CaseNfluid", 0))
        fluid_begin = boundary_count
        fluid_pos = pos[fluid_begin:fluid_begin + fluid_count]
        static_ids, static_pos, static_vel, static_rho, static_meta, _, _ = core_cfd.native_frame(
            static_prefix.with_suffix(".bi4"), Path(folder) / "static", decoder
        )
        static_boundary = sum(int(static_meta.get(name, 0)) for name in ("CaseNfixed", "CaseNmoving", "CaseNfloat"))
        static_fluid_count = int(static_meta.get("CaseNfluid", 0))
        static_fluid_pos = static_pos[static_boundary:static_boundary + static_fluid_count]
        same_fluid_initial = bool(
            len(fluid_pos) == len(static_fluid_pos)
            and np.array_equal(fluid_pos, static_fluid_pos)
            and np.max(np.abs(vel[fluid_begin:fluid_begin + fluid_count]), initial=0.0) <= 1e-12
            and np.isfinite(pos).all() and np.isfinite(vel).all() and np.isfinite(rho).all()
        )
        return {
            "total_particles": int(len(ids)),
            "fixed_particles": int(metadata.get("CaseNfixed", 0)),
            "moving_particles": int(metadata.get("CaseNmoving", 0)),
            "boundary_particles": boundary_count,
            "fluid_particles": fluid_count,
            "expected_fluid_particles": int(expected_fluid),
            "unique_ids": bool(len(np.unique(ids)) == len(ids)),
            "finite_initial_arrays": bool(np.isfinite(pos).all() and np.isfinite(vel).all() and np.isfinite(rho).all()),
            "initial_fluid_zero_velocity": bool(np.max(np.abs(vel[fluid_begin:fluid_begin + fluid_count]), initial=0.0) <= 1e-12),
            "native_sampling_matches_passed_static": same_fluid_initial,
            "normal_count": 0,
            "zero_boundary_normals": None,
            "normal_preflight_pass": None,
            "normal_preflight_applicability": "not_applicable_for_DBC",
        }


def prepare_canary(lab: Path, output: Path) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    static_path = lab / STATIC_RELATIVE
    static = json.loads(static_path.read_text())
    if not static.get("preflight_pass") or not static.get("qualification_only"):
        raise ValueError("passed full-cup static v3 prepared input is unavailable")
    static_definition = Path(static["definition_audit"]["definition"])
    if not static_definition.is_file():
        static_definition = lab / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_canary_v3/CORE_F2_resting_fill_side_wet_full_cup_q0p50000000_dp0p007500000000_canary_v3_Def.xml"
    tree = ET.parse(static_definition)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("static full-cup definition has no geometry definition")
    definition.set("dp", f"{DP_M:.17g}")
    pointmax = definition.find("pointmax")
    if pointmax is None:
        raise ValueError("static full-cup definition has no pointmax")
    pointmax.set("z", f"{RUNTIME_DOMAIN['posmax'][2]:.17g}")
    catchment = copy.deepcopy(f2q.F2_CATCHMENT_GEOMETRY)
    catchment_spec = f2q._catchment_wall_spec(catchment, static["config"]["tray"], dp_m=DP_M)
    wall_recipe = _append_catchment_walls(root, catchment)
    boundary_recipe = {
        "boundary_method": "DBC",
        "boundary_parameter": 1,
        "normal_preflight_applicability": "not_applicable_for_DBC",
        "moving_wall_velocity": "solver mvrotfile rigid-body velocity about y through pivot z=0.65",
        "normal_geometry_insertion": False,
    }
    motion = root.find(".//mvrotfile")
    if motion is None or motion.find("file") is None:
        raise ValueError("static full-cup definition has no motion block")
    motion.set("duration", f"{TIME_MAX_S:.17g}")
    motion.find("file").set("name", f"{CASE_ID}_motion.dat")
    for begin in root.findall(".//begin"):
        begin.set("finish", f"{TIME_MAX_S:.17g}")
    for key, value in (("Boundary", 1), ("SlipMode", 1), ("TimeMax", TIME_MAX_S), ("TimeOut", OUTPUT_INTERVAL_S),
                       ("DtIni", 0.0), ("DtMin", 0.0), ("DtFixed", 0.0)):
        _set_parameter(root, key, value)
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None or domain.find("posmin") is None or domain.find("posmax") is None:
        raise ValueError("static full-cup definition has no simulation domain")
    for name, values in (("posmin", RUNTIME_DOMAIN["posmin"]), ("posmax", RUNTIME_DOMAIN["posmax"])):
        node = domain.find(name)
        for axis, value in zip("xyz", values):
            node.set(axis, f"{float(value):.17g}")
    ET.indent(tree, space="    ")
    definition_path = output / f"{CASE_ID}_Def.xml"
    tree.write(definition_path, encoding="utf-8", xml_declaration=True)
    motion_path = output / f"{CASE_ID}_motion.dat"
    _dynamic_motion(motion_path)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / CASE_ID
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(definition_path.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"GenCase failed; inspect {output / 'gencase.log'}")
    generated_path = prefix.with_suffix(".xml")
    generated = ET.parse(generated_path).getroot()
    resolved_domain = f2q._runtime_domain_from_xml(generated)
    expected_domain = {"posmin": [float(x) for x in RUNTIME_DOMAIN["posmin"]], "posmax": [float(x) for x in RUNTIME_DOMAIN["posmax"]]}
    if resolved_domain != expected_domain:
        raise ValueError(f"resolved runtime domain differs: {resolved_domain} != {expected_domain}")
    fluid_groups = generated.findall(".//particles/fluid")
    expected_fluid = int(static["sampling"]["expected_fluid_particles"])
    generated_fluid_count = int(sum(int(group.get("count", 0)) for group in fluid_groups))
    if generated_fluid_count != expected_fluid:
        raise ValueError(f"full-cup fluid count changed: {generated_fluid_count} != {expected_fluid}")
    native = _native_initial(prefix, lab / "campaigns/l1-resume/artifacts/bi4_dump", expected_fluid, Path(static["generated_prefix"]))
    sampling = copy.deepcopy(static["sampling"])
    mass = copy.deepcopy(static["mass_preflight"])
    static_receipt = lab / STATIC_INTEGRATION_RELATIVE
    config = copy.deepcopy(static["config"])
    config.update({
        "schema": "core.cfd.v1",
        "family": "F2",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "recipe_id": "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_repair_v1",
        "recipe": "native_dbc",
        "stage": "repair_canary",
        "split": "qualification_only",
        "qualification_only": True,
        "qualified": False,
        "parameter": {"name": "rotation_duration_s", "q": Q, "value": ROTATION_DURATION_S, "candidate_range": [0.50, 1.20], "held_out": False},
        "dp_m": DP_M,
        "cfl": 0.2,
        "time_control": {"cflnumber": 0.2, "DtIni": 0.0, "DtMin": 0.0, "DtFixed": 0.0},
        "time_max_s": TIME_MAX_S,
        "maximum_extended_time_s": MAXIMUM_EXTENDED_TIME_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "angle_degrees": ANGLE_DEGREES,
        "motion_start_s": MOTION_START_S,
        "runtime_domain": copy.deepcopy(RUNTIME_DOMAIN),
        "wall_bounds": {
            "xmin": RUNTIME_DOMAIN["posmin"][0], "xmax": RUNTIME_DOMAIN["posmax"][0],
            "ymin": RUNTIME_DOMAIN["posmin"][1], "ymax": RUNTIME_DOMAIN["posmax"][1],
            "zmin": RUNTIME_DOMAIN["posmin"][2], "zmax": RUNTIME_DOMAIN["posmax"][2],
        },
        "physical_case_id": "F2_resting_fill_side_wet_full_cup_closed_catchment_boundary_formulation_v1",
        "lineage_group_id": SCOPE_ID,
        "control_semantics": "prescribed centered rotation starts at 0.50 s; DBC uses the native mvrotfile rigid-body motion",
        "boundary_method": 1,
        "repair_candidate_id": "moving_boundary_formulation_dbc",
        "physical_geometry_changed": True,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "source_definition": str(static_definition),
        "source_geometry_contract": {
            "fluid_initial_state": "exact v3 full-cup native lattice and fixed continuous volume; static predecessor is hash-bound",
            "cup": "passed full-cup v3 finite moving cup, unchanged",
            "receiver": "registered finite fixed receiver, unchanged",
            "tray_floor": "registered boxfill=bottom tray floor mkbound=2 retained at source plane z=-0.20 m",
            "catchment_side_walls": "new fixed mkbound=3 left/right/front/back walls over the tray footprint; top remains open",
            "motion": "prescribed centered rotation, y axis through z=0.65, q=0.5 duration 0.85 s, unchanged control family",
        },
        "catchment": catchment,
        "catchment_wall_spec": catchment_spec,
        "catchment_event_window_estimate": f2q._catchment_event_window_estimate(ROTATION_DURATION_S),
        "catchment_observer_candidate": f2q._catchment_observer_candidate(),
        "observer_revision": f2q.F2_OBSERVER_REVISION_ID,
        "event_window": f2q.event_window(TIME_MAX_S, MAXIMUM_EXTENDED_TIME_S),
        "static_predecessor": {
            "prepared": str((lab / STATIC_RELATIVE).resolve()),
            "prepared_sha256": core_cfd.digest(static_path),
            "integration_receipt": str(static_receipt.resolve()),
            "integration_receipt_sha256": core_cfd.digest(static_receipt) if static_receipt.is_file() else None,
            "hard_integrity_pass": True,
            "event_window_complete": True,
            "native_fluid_particles": expected_fluid,
            "mass_rescaling": False,
            "qualification_claim": "static nominal canary only; no moving or range qualification",
        },
        "wall_audit_contract": {
            "cup": {"frame": "moving cup body frame", "closed_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"], "saved_chord_and_endpoint_hard": True},
            "receiver": {"frame": "world", "closed_faces": ["bottom", "left", "right", "front", "back"], "open_faces": ["top"], "saved_chord_and_endpoint_hard": True},
            "tray": {"frame": "world", "closed_faces": ["bottom"], "open_faces": ["top", "left", "right", "front", "back"], "saved_chord_and_endpoint_hard": True},
            "catchment": {"frame": "world", "closed_faces": ["left", "right", "front", "back"], "open_faces": ["top"], "floor_source_plane_z_m": -0.20, "saved_chord_and_endpoint_hard": True},
            "ownership": "open-top ownership is separate; side entry and recontact cannot be hidden by ownership",
            "geometry_audit_owner": "core_f2_qualification.audit_dynamic",
        },
        "qualification_inheritance": "none; independent full-cup closed-catchment DBC boundary-formulation canary",
        "qualification_claim": "none; independent full-cup closed-catchment DBC moving canary only",
        "repair_hypothesis": {
            "id": "moving_boundary_formulation_dbc",
            "mechanism_class": "boundary_formulation",
            "single_variable_change": "Boundary 2 mDBC -> Boundary 1 DBC",
            "cfl_unchanged_from_mdbc_baseline": 0.2,
            "same_as_cfl010": False,
            "rationale": "CFL=0.10 removed all native exclusions but left full-vector cup and receiver closed-face entries; verified mDBC normals and motion sign make another normal/sign edit unsupported.",
            "negative_evidence_preserved": "CFL=0.10 mDBC hard failures remain the parent negative result; no threshold or ownership gate change",
        },
        "evidence_basis": {
            "cfl010_prepared": str((lab / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_cfl010_v1/prepared.json").resolve()),
            "cfl010_prepared_sha256": core_cfd.digest(lab / "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_closed_catchment_mdbc_cfl010_v1/prepared.json"),
            "cfl010_result": str((lab / "campaigns/core-v1/cfd/f2-cfl010-completed-v1/result.json").resolve()),
            "cfl010_result_sha256": core_cfd.digest(lab / "campaigns/core-v1/cfd/f2-cfl010-completed-v1/result.json"),
            "cfl010_full_vector_forensics": str((lab / "campaigns/core-v1/cfd/f2-cfl010-completed-v1/moving-cup-entry-forensics-v2.json").resolve()),
            "cfl010_full_vector_forensics_sha256": core_cfd.digest(lab / "campaigns/core-v1/cfd/f2-cfl010-completed-v1/moving-cup-entry-forensics-v2.json"),
            "mdbc_contact_preflight": str((lab / "campaigns/core-v1/cfd/f2-full-cup-closed-catchment-mdbc-v2-motion-contact-preflight-v1.json").resolve()),
            "mdbc_contact_preflight_sha256": core_cfd.digest(lab / "campaigns/core-v1/cfd/f2-full-cup-closed-catchment-mdbc-v2-motion-contact-preflight-v1.json"),
            "first_cfl010_cup_event_s": 0.840022688448976,
            "first_cfl010_receiver_event_s": 0.9500128284032898,
            "cfl010_native_exclusions": 0,
        },
    })
    definition_audit = {
        "source_definition": str(static_definition),
        "source_definition_sha256": core_cfd.digest(static_definition),
        "definition": str(definition_path.resolve()),
        "definition_sha256": core_cfd.digest(definition_path),
        "motion_file": str(motion_path.resolve()),
        "motion_sha256": core_cfd.digest(motion_path),
        "changed_fields": [
            "new fixed catchment side walls mkbound=3 over retained tray footprint",
            "Boundary=1 native DBC; no mDBC normal geometry or -mdbc_noslip argument",
            "full-window TimeMax=2.50 and TimeOut=0.01",
            "runtime domain zmax=2.40",
            "prescribed centered rotation replaces v3 zero-motion hold",
            "CFL=0.20 retained from the mDBC baseline; this is not a CFL retry",
        ],
        "unchanged_fields": [
            "v3 full-cup continuous volume and native fluid lattice",
            "cup/receiver/tray source geometry and tray floor plane",
            "gravity, EOS, viscosity, no mass rescaling",
        ],
        "qualification_claim": "none",
    }
    # Replace the inherited static metadata with the exact dynamic definition
    # and motion hashes; the static predecessor remains separately bound above.
    config["definition_audit"] = copy.deepcopy(definition_audit)
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": _stamp(),
        "config": config,
        "sampling": sampling,
        "mass_preflight": mass,
        "native_initial": native,
        "resolved_runtime_domain": resolved_domain,
        "dynamic_canary_preflight": {
            "generated_fluid_count": generated_fluid_count,
            "expected_fluid_count": expected_fluid,
            "native_initial_state_finite_unique": native["unique_ids"] and native["finite_initial_arrays"],
            "native_sampling_matches_passed_static": native["native_sampling_matches_passed_static"],
            "mdbc_normals_complete_nonzero": None,
            "normal_preflight_applicability": "not_applicable_for_DBC",
            "zero_boundary_normals": None,
            "catchment_wall_particles_present": native["fixed_particles"] > 0,
            "registered_full_window_s": TIME_MAX_S,
            "maximum_extended_window_s": MAXIMUM_EXTENDED_TIME_S,
            "motion_duration_s": ROTATION_DURATION_S,
        },
        "definition_audit": definition_audit,
        "wall_recipe": wall_recipe,
        "boundary_recipe": boundary_recipe,
        "preflight_pass": bool(
            generated_fluid_count == expected_fluid
            and native["unique_ids"]
            and native["finite_initial_arrays"]
            and native["initial_fluid_zero_velocity"]
            and native["native_sampling_matches_passed_static"]
            and mass["mass_gate_pass"]
        ),
        "generated_prefix": str(prefix.resolve()),
        "source_template": str(static_definition),
        "source_template_sha256": core_cfd.digest(static_definition),
        "solver_binary": str(binaries / "DualSPHysics5.4_linux64"),
        "solver_sha256": core_cfd.digest(binaries / "DualSPHysics5.4_linux64"),
        "decoder": str(lab / "campaigns/l1-resume/artifacts/bi4_dump"),
        "decoder_sha256": core_cfd.digest(lab / "campaigns/l1-resume/artifacts/bi4_dump"),
        "solver_arguments": [],
        "qualification_only": True,
        "qualification_claim": "none; independent full-cup closed-catchment DBC moving canary only",
    }
    prepared["inputs"] = {str(path.resolve()): core_cfd.digest(path) for path in output.rglob("*") if path.is_file()}
    _write_json(output / "prepared.json", prepared)
    return prepared


def make_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    config = prepared.get("config", {})
    if not prepared.get("preflight_pass"):
        raise ValueError("F2 full-cup catchment DBC preflight failed")
    if config.get("repair_candidate_id") != "moving_boundary_formulation_dbc":
        raise ValueError("prepared input is not the DBC boundary-formulation candidate")
    if config.get("qualification_only") is not True or config.get("split") != "qualification_only":
        raise ValueError("repair canary must remain qualification_only")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    runner = lab / "scripts/core_f2_qualification.py"
    generator = lab / "scripts/f2_full_cup_closed_catchment_dbc.py"
    input_files = [{"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)}]
    for path, sha256 in sorted(prepared.get("inputs", {}).items()):
        if path != str(prepared_path):
            input_files.append({"path": path, "sha256": sha256})
    for path in (solver, decoder, runner, generator):
        item = {"path": str(path), "sha256": core_cfd.digest(path)}
        if not any(existing["path"] == item["path"] for existing in input_files):
            input_files.append(item)
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": JOB_ID,
        "logical_id": JOB_ID,
        "attempt_role": "full_cup_closed_catchment_dbc_boundary_formulation_canary",
        "category": "f2_dynamic_full_cup_closed_catchment_dbc_boundary_repair_canary",
        "host": "h200",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(runner), "--lab-root", str(lab), "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "split": "qualification_only",
        "qualification_status": "candidate-only; independent DBC boundary-formulation scope remains unqualified",
        "launch_recommendation": "root review/queue only; do not infer 13+2 or T1 qualification from this canary",
        "input_files": input_files,
        "prepared_case_id": config["case_id"],
        "registered_window_s": TIME_MAX_S,
        "maximum_extended_window_s": MAXIMUM_EXTENDED_TIME_S,
        "motion_start_s": MOTION_START_S,
        "rotation_duration_s": ROTATION_DURATION_S,
        "angle_degrees": ANGLE_DEGREES,
        "scope_id": config["scope_id"],
        "revision_id": config["revision_id"],
        "family": "F2",
        "repair_candidate_id": config["repair_candidate_id"],
        "physical_geometry_changed": True,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "boundary_method": "native DBC Boundary=1; no -mdbc_noslip argument",
        "normal_preflight": {
            "applicability": "not_applicable_for_DBC",
            "reason": "DBC does not consume the mDBC normal/ghost field",
        },
        "geometry_contract": {
            "catchment_continuous_low_m": list(config["catchment"]["low"]),
            "catchment_continuous_size_m": list(config["catchment"]["size"]),
            "catchment_closed_faces": list(config["catchment"]["closed_faces"]),
            "catchment_open_faces": list(config["catchment"]["open_faces"]),
            "catchment_wall_mkbound": int(config["catchment"]["mkbound"]),
            "retained_tray_floor_mkbound": int(config["catchment"]["floor_material_mkbound"]),
            "floor_fluid_facing_surface_z_m": float(config["catchment_wall_spec"]["floor"]["fluid_facing_surface_z_m"]),
            "floor_outer_low_z_m": float(config["catchment_wall_spec"]["floor"]["nominal_outer_low_z_m"]),
            "surface_convention": config["catchment_wall_spec"]["surface_convention"],
        },
        "observer_contract": config["wall_audit_contract"],
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0; output is attempt_dir/product",
    }
    _write_json(output, spec)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = args.lab_root.resolve()
    if args.command == "prepare":
        result = prepare_canary(lab, args.output)
    else:
        result = make_job(args.prepared, lab, args.output)
    print(json.dumps({key: result.get(key) for key in ("preflight_pass", "qualification_only", "prepared_case_id", "job_id", "zero_boundary_normals", "mdbc_normals_complete_nonzero") if key in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
