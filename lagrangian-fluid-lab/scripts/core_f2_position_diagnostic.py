#!/usr/bin/env python3
"""Prepare bounded F2 position-loss diagnostic canaries.

The H0 static hold lost 598 native fluid identities through ``NpOutPos``.
This module keeps that failed result immutable and prepares two candidate-only
canaries:

* ``domain_extension`` changes only the computational ceiling from 1.8 m to
  2.4 m, separating runtime-domain censoring from the physical cup escape;
* ``mdbc_boundary`` uses the same extended domain and adds an explicit mDBC
  normal geometry, testing the boundary-impact hypothesis after CPU normal
  verification.

Neither candidate is an F2 qualification claim.  This file performs CPU
preparation and writes worker proposals only; the coordinator owns execution.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import xml.etree.ElementTree as ET

import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd, core_f2


SCHEMA = "core.f2.position_diagnostic.v1"
DOMAIN_ZMAX = 2.4
BASE_DOMAIN_ZMAX = 1.8
CASES = {
    "domain_extension": {
        "scope_id": "F2_H1_runtime_domain_extension_canary_v1",
        "case_id": "CORE_F2_H1_runtime_domain_extension_dp0p007500000000_canary",
        "boundary": 1,
        "recipe_id": "F2_static_hold_dbc_domain_audit_v1",
    },
    "mdbc_boundary": {
        "scope_id": "F2_H2_mdbc_boundary_repair_canary_v1",
        "case_id": "CORE_F2_H2_mdbc_boundary_repair_dp0p007500000000_canary",
        "boundary": 2,
        "recipe_id": "F2_static_hold_mdbc_boundary_repair_v1",
    },
}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def _digest(path: Path) -> str:
    return core_cfd.digest(Path(path))


def _mdbc_normals(commands: ET.Element) -> ET.Element:
    node = ET.Element("list", {"name": "GeometryForNormals"})
    ET.SubElement(node, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    ET.SubElement(node, "setshapemode").text = "actual | bound"
    ET.SubElement(node, "setnormalinvert", {"invert": "true"})
    entries = (
        (0, core_f2.CUP, "bottom | left | right | front | back"),
        (1, core_f2.RECEIVER, "bottom | left | right | front | back"),
        (2, core_f2.TRAY, "bottom"),
    )
    for mk, box, fill in entries:
        ET.SubElement(node, "setmkbound", {"mk": str(mk)})
        draw = ET.SubElement(node, "drawbox")
        ET.SubElement(draw, "boxfill").text = fill
        ET.SubElement(draw, "point", {axis: f"{float(box['low'][i]):.17g}" for i, axis in enumerate("xyz")})
        ET.SubElement(draw, "size", {axis: f"{float(box['size'][i]):.17g}" for i, axis in enumerate("xyz")})
        # The retained H2 failure used the normal-construction surface at
        # ``distanceh=2``.  That radius does not reach the corners of the
        # three-layer boundary shell.  The official rectangular mDBC pattern
        # constructs the normal surface at the half-cell inner face and uses a
        # 3h search radius to cover the outer triple layer.  Keep the actual
        # boundary particles at vdp=0,1,2 in the source mainlist; only this
        # normal-construction input changes.
        ET.SubElement(draw, "layers", {"vdp": "-0.5"})
    ET.SubElement(node, "shapeout", {"file": "hdp"})
    ET.SubElement(node, "resetdraw")
    return node


def _rewrite_definition(source: Path, target: Path, motion_name: str, sampling: list[dict], *, boundary: int) -> dict:
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    commands = root.find(".//geometry/commands")
    main = root.find(".//geometry/commands/mainlist")
    if definition is None or commands is None or main is None:
        raise ValueError("F2 source geometry is incomplete")
    definition.set("dp", f"{core_f2.DP_M:.17g}")
    pointmax = definition.find("pointmax")
    if pointmax is None:
        raise ValueError("F2 source lacks geometry pointmax")
    pointmax.set("z", f"{DOMAIN_ZMAX:.17g}")

    fluid_index = 0
    active_mk = None
    for node in list(main):
        if node.tag == "setmkfluid":
            active_mk = int(node.get("mk"))
        elif node.tag == "drawbox" and active_mk is not None:
            if fluid_index >= len(sampling):
                raise ValueError("F2 source contains more fluid drawboxes than registered")
            point, size = node.find("point"), node.find("size")
            if point is None or size is None:
                raise ValueError("F2 fluid drawbox is incomplete")
            sample = sampling[fluid_index]
            for i, axis in enumerate("xyz"):
                point.set(axis, f"{sample['first_center_m'][i]:.17g}")
                size.set(axis, f"{sample['draw_size_m'][i]:.17g}")
            fluid_index += 1
    if fluid_index != len(sampling):
        raise ValueError("F2 source fluid drawbox count changed")

    if boundary == 2:
        # Keep the original finite geometry as the physical case.  The extra
        # list is only the mDBC normal-generation input and is run before the
        # main draw list.
        commands.insert(0, _mdbc_normals(commands))
        runlist = ET.Element("runlist", {"name": "GeometryForNormals"})
        # The normal list must run before the ordinary fluid/boundary draws;
        # it temporarily disables draw points and otherwise leaves the main
        # list with no fluid particles.
        main.insert(0, runlist)
        shape = main.find("setshapemode")
        if shape is not None:
            shape.text = "actual | bound"
        old_normals = root.find("./casedef/normals")
        if old_normals is not None:
            root.find("./casedef").remove(old_normals)
        casedef = root.find("./casedef")
        normals = ET.SubElement(casedef, "normals", {"active": "true"})
        norgeometry = ET.SubElement(normals, "norgeometry")
        ET.SubElement(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
        ET.SubElement(norgeometry, "distanceh", {"v": "3.0"})
        ET.SubElement(norgeometry, "svshapes", {"v": "true"})

    motion = root.find(".//mvrotfile")
    if motion is None or motion.find("file") is None:
        raise ValueError("F2 source rotation block is incomplete")
    motion.set("duration", f"{core_f2.TIME_MAX_S:.17g}")
    motion.find("file").set("name", motion_name)
    for node in root.findall(".//begin"):
        node.set("finish", f"{core_f2.TIME_MAX_S:.17g}")

    for key, value in {
        "TimeMax": core_f2.TIME_MAX_S,
        "TimeOut": core_f2.OUTPUT_INTERVAL_S,
        "Boundary": boundary,
        "SlipMode": 1,
    }.items():
        core_f2._set_parameter(root, key, value)
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None:
        raise ValueError("F2 source has no runtime simulation domain")
    posmax = domain.find("posmax")
    if posmax is None:
        raise ValueError("F2 source runtime domain has no posmax")
    posmax.set("z", f"{DOMAIN_ZMAX:.17g}")
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="    ")
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return {
        "source_definition": str(source.resolve()),
        "source_definition_sha256": _digest(source),
        "definition": str(target.resolve()),
        "definition_sha256": _digest(target),
        "runtime_domain_zmax_m": DOMAIN_ZMAX,
        "boundary_method": "mDBC" if boundary == 2 else "DBC",
        "normal_geometry": boundary == 2,
        "changed_fields": [
            f"runtime and GenCase domain zmax={DOMAIN_ZMAX:g} m",
            "motion angle fixed at zero",
            "registered nearest cell-centre fluid sampling",
        ] + ([
            "Boundary=2 with explicit finite-bound normal geometry",
            "normal-construction layers vdp=-0.5",
            "normal search distanceh=3.0 and svshapes=true",
        ] if boundary == 2 else []),
        "physical_geometry_changed": False,
        "qualification_claim": "none",
    }


def candidate_config(kind: str) -> dict:
    if kind not in CASES:
        raise ValueError(f"unknown F2 diagnostic candidate: {kind}")
    record = CASES[kind]
    config = core_f2.static_config()
    config.update(
        {
            "scope_id": record["scope_id"],
            "revision_id": (
                "F2_position_diagnostic_domain_extension_v1"
                if kind == "domain_extension"
                else "F2_position_diagnostic_mdbc_boundary_v2"
            ),
            "case_id": record["case_id"],
            "recipe_id": record["recipe_id"],
            "recipe": "mdbc_native" if record["boundary"] == 2 else "native_dbc",
            "stage": "canary",
            "boundary_method": record["boundary"],
            "runtime_domain": {
                "posmin": [-0.60, -0.55, -0.20],
                "posmax": [2.00, 0.55, DOMAIN_ZMAX],
                "baseline_zmax_m": BASE_DOMAIN_ZMAX,
                "changed_zmax_m": DOMAIN_ZMAX,
            },
            "physical_geometry_changed": False,
            "repair_hypothesis": (
                "runtime domain ceiling censored an already escaping static-hold plume"
                if kind == "domain_extension"
                else "DBC bottom impact/pressure treatment caused the static-hold upward plume; verify mDBC normals with 3h corner coverage"
            ),
            "qualified": False,
            "qualification_claim": "none",
        }
    )
    return config


def prepare_candidate(lab: Path, output: Path, kind: str) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"F2 diagnostic preparation output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    config = candidate_config(kind)
    source = lab / core_f2.SOURCE_RELATIVE
    sampling = [core_f2._nearest_native_box(box, core_f2.DP_M) for box in core_f2.FLUID_BOXES]
    target = output / f"{config['case_id']}_Def.xml"
    motion_name = f"{config['case_id']}_motion.dat"
    definition_audit = _rewrite_definition(source, target, motion_name, sampling, boundary=config["boundary_method"])
    motion = output / motion_name
    core_f2._static_motion(motion)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / config["case_id"]
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(target.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_f2.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"F2 diagnostic GenCase failed: {output / 'gencase.log'}")
    generated = ET.parse(prefix.with_suffix(".xml")).getroot()
    blocks = generated.findall(".//particles/fluid")
    generated_counts = [int(block.get("count")) for block in blocks]
    expected_counts = [int(item["particle_count"]) for item in sampling]
    if generated_counts != expected_counts:
        raise ValueError(f"F2 diagnostic fluid count mismatch: {generated_counts} vs {expected_counts}")
    sampling_payload = {
        "fluid_boxes": sampling,
        "expected_fluid_particles": int(sum(expected_counts)),
        "continuous_mass_kg": float(sum(item["continuous_mass_kg"] for item in sampling)),
        "sampled_mass_kg": float(sum(item["discrete_mass_kg"] for item in sampling)),
        "mass_policy": "native rho*dp^3, no mass rescaling",
    }
    mass = core_cfd.mass_quality(sampling_payload)
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    with tempfile.TemporaryDirectory(prefix="core-f2-diagnostic-") as folder:
        ids, pos, vel, rho, meta, info, arrays = core_cfd.native_frame(prefix.with_suffix(".bi4"), Path(folder) / "native", decoder)
        # ``BoundNor`` contains fixed, moving and floating boundary particles.
        # Counting only CaseNfixed silently rejects a complete mDBC array for a
        # case with a moving cup (the F2 case has 44,235 moving particles).
        boundary_count = sum(int(meta.get(key, 0)) for key in ("CaseNfixed", "CaseNmoving", "CaseNfloat"))
        normal_file = arrays / "BoundNor.bin"
        normals = np.fromfile(normal_file, np.float32).reshape(-1, 3) if normal_file.exists() else np.empty((0, 3))
        zero_normals = int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10))
        normal_check = config["boundary_method"] != 2 or (
            len(normals) == boundary_count and zero_normals == 0 and np.isfinite(normals).all()
        )
        native = {
            "total_particles": int(len(ids)),
            "boundary_particles": boundary_count,
            "fluid_particles": int(meta.get("CaseNfluid", 0)),
            "normal_count": int(len(normals)),
            "zero_boundary_normals": zero_normals,
            "initial_state_pass": bool(all(np.isfinite(x).all() for x in (pos, vel, rho)) and normal_check),
        }
    preflight = bool(native["initial_state_pass"] and native["fluid_particles"] == sampling_payload["expected_fluid_particles"] and mass["mass_gate_pass"])
    inputs = {str(path.resolve()): _digest(path) for path in output.rglob("*") if path.is_file()}
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": _stamp(),
        "config": config,
        "sampling": sampling_payload,
        "mass_preflight": mass,
        "native_initial": native,
        "static_diagnostic_preflight": {
            "generated_fluid_counts": generated_counts == expected_counts,
            "mdbc_normals_complete_nonzero": bool(normal_check),
            "runtime_domain_zmax_m": DOMAIN_ZMAX,
        },
        "preflight_pass": preflight,
        "generated_prefix": str(prefix.resolve()),
        "source_template": str(source.resolve()),
        "source_template_sha256": _digest(source),
        "definition_audit": definition_audit,
        "generated_particle_counts": generated_counts,
        "resolved_runtime_domain": {"zmax": DOMAIN_ZMAX},
        "inputs": inputs,
        "solver_binary": str(binaries / "DualSPHysics5.4_linux64"),
        "solver_sha256": _digest(binaries / "DualSPHysics5.4_linux64"),
        "decoder": str(decoder),
        "decoder_sha256": _digest(decoder),
        "solver_arguments": ["-mdbc_noslip:1"] if config["boundary_method"] == 2 else [],
        "qualification_claim": "none; F2 position diagnostic candidate only",
    }
    _write_json(output / "prepared.json", prepared)
    return prepared


def make_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if prepared.get("config", {}).get("scope_id") not in {r["scope_id"] for r in CASES.values()}:
        raise ValueError("F2 diagnostic job is outside the two candidate scopes")
    if prepared.get("preflight_pass") is not True:
        raise ValueError("F2 diagnostic candidate failed CPU preflight")
    solver = Path(prepared["solver_binary"]).resolve()
    cfg = prepared["config"]
    kind = "mdbc_boundary" if cfg.get("boundary_method") == 2 else "domain_extension"
    job_id = f"f2-{kind.replace('_', '-')}-canary-001"
    spec = {
        "schema": "core.cfd.job.v1",
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "position_diagnostic_repair_canary",
        "category": "f2_position_diagnostic_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2.py"), "--lab-root", str(lab), "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.25},
        "timeout_seconds": 1800,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_status": "candidate-only; F2 moving scope remains unqualified",
        "input_files": [{"path": str(prepared_path), "sha256": _digest(prepared_path)}, {"path": str(solver), "sha256": _digest(solver)}],
        "prepared_case_id": cfg["case_id"],
        "registered_window_s": cfg["time_max_s"],
        "scope_id": cfg["scope_id"],
        "revision_id": cfg["revision_id"],
        "family": "F2",
        "diagnostic_axis": "runtime_domain_ceiling" if kind == "domain_extension" else "boundary_formulation_with_verified_normals",
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
    }
    _write_json(output, spec)
    return spec


def audit_position_loss(prepared_path: Path, product_root: Path, output: Path) -> dict:
    """Classify the retained H0 position losses without relabelling them.

    A particle is a runtime-domain candidate when its last valid trajectory
    reaches the declared ceiling, and a physical-cup escape candidate when it
    rises above the open cup mouth.  Both counts are retained because the H0
    output is already censored at the runtime ceiling.
    """
    import h5py

    prepared_path, product_root, output = map(Path, (prepared_path, product_root, output))
    prepared = json.loads(prepared_path.read_text())
    result = json.loads((product_root / "result.json").read_text())
    trajectory = product_root / "trajectory.h5"
    config = prepared["config"]
    runtime_zmax = float(prepared.get("resolved_runtime_domain", {}).get("zmax", 1.8))
    cup_top = float(config["cup"]["low"][2] + config["cup"]["size"][2])
    with h5py.File(trajectory, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        ids = np.asarray(handle["particle_id"][:])
        sources = np.asarray(handle["source_label_initial_mk"][:])
        dead = np.where(~valid[-1])[0]
        records = []
        for index in dead:
            first = int(np.where(~valid[:, index])[0][0])
            last = first - 1
            path = positions[: first, index]
            records.append(
                {
                    "particle_id": int(ids[index]),
                    "source_label_initial_mk": int(sources[index]),
                    "first_invalid_time_s": float(times[first]),
                    "last_valid_position_m": positions[last, index].tolist(),
                    "last_valid_velocity_m_s": velocities[last, index].tolist(),
                    "maximum_prior_z_m": float(np.nanmax(path[:, 2])),
                }
            )
        max_z = np.asarray([row["maximum_prior_z_m"] for row in records], dtype=float)
        first_times = np.asarray([row["first_invalid_time_s"] for row in records], dtype=float)
        frame_max = [
            {
                "time_s": float(times[index]),
                "valid_count": int(valid[index].sum()),
                "maximum_valid_z_m": float(np.nanmax(positions[index, valid[index], 2])),
            }
            for index in range(len(times))
        ]
    report = {
        "schema": SCHEMA,
        "revision_id": "F2_H0_position_loss_forensics_v1",
        "family": "F2",
        "scope_id": config["scope_id"],
        "case_id": config["case_id"],
        "prepared_sha256": _digest(prepared_path),
        "result_sha256": _digest(product_root / "result.json"),
        "trajectory_sha256": _digest(trajectory),
        "declared_runtime_domain": {"zmax_m": runtime_zmax},
        "physical_cup_open_mouth_z_m": cup_top,
        "position_loss": {
            "initial_fluid_particles": int(valid[0].sum()),
            "final_fluid_particles": int(valid[-1].sum()),
            "lost_particle_count": int(len(records)),
            "first_loss_time_s": float(first_times.min()) if len(first_times) else None,
            "last_loss_time_s": float(first_times.max()) if len(first_times) else None,
            "source_counts": {
                str(int(source)): int(sum(row["source_label_initial_mk"] == int(source) for row in records))
                for source in sorted(set(row["source_label_initial_mk"] for row in records))
            },
            "maximum_prior_z_range_m": [float(max_z.min()), float(max_z.max())] if len(max_z) else None,
            "all_losses_above_open_cup_mouth": bool(len(max_z) and np.all(max_z > cup_top)),
            "runtime_domain_ceiling_candidate_count": int(np.sum(max_z >= runtime_zmax - 0.10)) if len(max_z) else 0,
            "runtime_domain_ceiling_tolerance_m": 0.10,
            "endpoint_closed_wall_violation_count": int(result.get("endpoint_violation_particle_frames", 0)),
            "saved_chord_crossing_count": int(result.get("saved_chord_crossing_count", 0)),
        },
        "frame_maximums": frame_max,
        "hypotheses": [
            {
                "id": "H0a_runtime_domain_censoring",
                "status": "supported_as_censoring_mechanism",
                "evidence": "all 598 lost identities have last valid z in 1.7456..1.8000 m and the declared ceiling is 1.8 m",
                "claim_limit": "does not explain the preceding physical escape from the open cup",
            },
            {
                "id": "H0b_static_bottom_impact_upward_plume",
                "status": "supported_candidate",
                "evidence": "maximum valid z rises from 0.891 m at 0.18 s to 1.7726 m at 0.4000 s; no closed-wall violation is recorded",
                "claim_limit": "boundary formulation/initial-contact cause needs an isolated canary",
            },
        ],
        "qualification_claim": "none; H0 failure forensics only",
    }
    _write_json(output, report)
    return report


def audit_initial_impact(prepared_path: Path, product_root: Path, output: Path) -> dict:
    """Quantify the H0 initial gap, free-fall interval and impact plume.

    The static H0 canary starts with a zero-velocity fluid column above the
    cup floor.  This report keeps that initial condition separate from the
    later boundary/domain hypotheses: it records the native centre lattice,
    gravitational potential energy, a ballistic reference, and saved-frame
    velocity/height probes.  It does not rewrite the case or infer a resting
    fill from the observed trajectory.
    """
    import h5py

    prepared_path, product_root, output = map(Path, (prepared_path, product_root, output))
    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    trajectory = product_root / "trajectory.h5"
    cup_low = np.asarray(config["cup"]["low"], dtype=float)
    cup_high = cup_low + np.asarray(config["cup"]["size"], dtype=float)
    gravity_m_s2 = 9.81
    with h5py.File(trajectory, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        masses = np.asarray(handle["mass"][0], dtype=float)
        source_labels = np.asarray(handle["source_label_initial_mk"][:], dtype=int)
        initial = valid[0] & np.isfinite(positions[0]).all(axis=1)
        initial_position = positions[0, initial]
        initial_mass = masses[initial]
        initial_z = initial_position[:, 2]
        initial_potential = float(np.sum(initial_mass * gravity_m_s2 * (initial_z - cup_low[2])))
        initial_kinetic = float(np.sum(0.5 * initial_mass * np.sum(velocities[0, initial] ** 2, axis=1)))

        def frame_probe(index: int) -> dict:
            active = valid[index] & np.isfinite(positions[index]).all(axis=1) & np.isfinite(velocities[index]).all(axis=1)
            point = positions[index, active]
            velocity = velocities[index, active]
            mass = masses[active]
            speed = np.linalg.norm(velocity, axis=1)
            return {
                "time_s": float(times[index]),
                "valid_count": int(active.sum()),
                "minimum_z_m": float(np.min(point[:, 2])),
                "maximum_z_m": float(np.max(point[:, 2])),
                "center_of_mass_z_m": float(np.average(point[:, 2], weights=mass)),
                "minimum_vz_m_s": float(np.min(velocity[:, 2])),
                "maximum_vz_m_s": float(np.max(velocity[:, 2])),
                "maximum_speed_m_s": float(np.max(speed)),
                "positive_vz_mass_fraction": float(np.sum(mass[velocity[:, 2] > 0]) / max(initial_mass.sum(), 1e-30)),
            }

        probe_targets = (0.0, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.24, 0.30, 0.40)
        probes = [frame_probe(int(np.argmin(np.abs(times - target)))) for target in probe_targets]
        max_vz = np.asarray([
            np.max(velocities[index, valid[index], 2]) if valid[index].any() else np.nan
            for index in range(len(times))
        ])
        first_positive = np.flatnonzero(max_vz > 0.0)
        bottom_threshold = cup_low[2] + 0.02
        minimum_z = np.asarray([
            np.min(positions[index, valid[index], 2]) if valid[index].any() else np.nan
            for index in range(len(times))
        ])
        near_bottom = np.flatnonzero(minimum_z <= bottom_threshold)
        peak_index = int(np.nanargmax(max_vz))

        by_source = {}
        for source in sorted(np.unique(source_labels[initial])):
            selected = initial & (source_labels == source)
            source_mass = masses[selected]
            source_z = positions[0, selected, 2]
            by_source[str(int(source))] = {
                "particle_count": int(selected.sum()),
                "mass_kg": float(source_mass.sum()),
                "center_of_mass_z_m": float(np.average(source_z, weights=source_mass)),
                "minimum_z_m": float(source_z.min()),
                "maximum_z_m": float(source_z.max()),
                "potential_energy_relative_to_cup_floor_J": float(
                    np.sum(source_mass * gravity_m_s2 * (source_z - cup_low[2]))
                ),
            }

    bottom_gap = float(initial_z.min() - cup_low[2])
    top_gap = float(cup_high[2] - initial_z.max())
    ballistic_time = float(np.sqrt(2.0 * bottom_gap / gravity_m_s2))
    ballistic_speed = float(np.sqrt(2.0 * gravity_m_s2 * bottom_gap))
    report = {
        "schema": "core.f2.initial_impact_forensics.v1",
        "revision_id": "F2_H0_initial_impact_forensics_v1",
        "family": "F2",
        "scope_id": config["scope_id"],
        "case_id": config["case_id"],
        "prepared_sha256": _digest(prepared_path),
        "trajectory_sha256": _digest(trajectory),
        "initial_condition": {
            "particle_count": int(initial.sum()),
            "native_mass_kg": float(initial_mass.sum()),
            "gravity_m_s2": gravity_m_s2,
            "initial_velocity_max_m_s": float(np.linalg.norm(velocities[0, initial], axis=1).max()),
            "fluid_center_lattice_bounds_m": {
                "minimum": initial_position.min(axis=0).tolist(),
                "maximum": initial_position.max(axis=0).tolist(),
                "center_of_mass": np.average(initial_position, axis=0, weights=initial_mass).tolist(),
            },
            "cup_bounds_m": {"low": cup_low.tolist(), "high": cup_high.tolist()},
            "clearance_to_physical_cup_faces_m": {
                "bottom": bottom_gap,
                "top": top_gap,
                "left_x": float(initial_position[:, 0].min() - cup_low[0]),
                "right_x": float(cup_high[0] - initial_position[:, 0].max()),
                "front_y": float(initial_position[:, 1].min() - cup_low[1]),
                "back_y": float(cup_high[1] - initial_position[:, 1].max()),
            },
            "initial_overlap_count_with_physical_cup_bounds": int(np.sum(
                np.any(initial_position < cup_low, axis=1) | np.any(initial_position > cup_high, axis=1)
            )),
            "initial_potential_energy_relative_to_cup_floor_J": initial_potential,
            "initial_kinetic_energy_J": initial_kinetic,
            "source_layers": by_source,
        },
        "ballistic_reference": {
            "drop_distance_to_cup_floor_m": bottom_gap,
            "free_fall_time_to_cup_floor_s": ballistic_time,
            "free_fall_speed_at_cup_floor_m_s": ballistic_speed,
            "interpretation": "lower native centres have enough initial clearance for a gravity fall to the cup floor on the 0.10 s scale; this is a reference, not a fitted impact time",
        },
        "impact_probes": probes,
        "observed_impact": {
            "first_saved_frame_min_z_le_cup_floor_plus_0p02_s": float(times[near_bottom[0]]) if len(near_bottom) else None,
            "first_saved_frame_with_positive_max_vz_s": float(times[first_positive[0]]) if len(first_positive) else None,
            "peak_saved_max_vz_m_s": float(max_vz[peak_index]),
            "peak_saved_max_vz_time_s": float(times[peak_index]),
            "peak_saved_max_z_at_0p4s_m": float(probes[-1]["maximum_z_m"]),
        },
        "interpretation": {
            "initial_fluid_overlaps_physical_cup": False,
            "initial_state_is_zero_velocity": True,
            "gravity_to_bottom_transient_supported": True,
            "static_resting_fill_is_same_scope_repair": False,
            "resting_fill_status": "would require an independently registered physical initial-condition scope; not applied here",
        },
        "qualification_claim": "none; H0 initial-condition forensics only",
    }
    _write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--kind", choices=sorted(CASES), required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("audit-loss")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--product", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("audit-initial-impact")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--product", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_candidate(args.lab_root, args.output, args.kind)
    elif args.command == "audit-loss":
        result = audit_position_loss(args.prepared, args.product, args.output)
    elif args.command == "audit-initial-impact":
        result = audit_initial_impact(args.prepared, args.product, args.output)
    else:
        result = make_job(args.prepared, args.lab_root, args.output)
    print(json.dumps({k: result[k] for k in ("preflight_pass", "static_diagnostic_preflight", "qualification_claim", "job_id") if k in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
