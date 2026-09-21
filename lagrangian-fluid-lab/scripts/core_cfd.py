#!/usr/bin/env python3
"""Isolated Core CFD preparation, native conversion and evidence workers.

GPU workers require the coordinator's single-device CUDA_VISIBLE_DEVICES.
No legacy state, budget, GPU selection or campaign module globals are changed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import h5py
import numpy as np


SCHEMA = "core.cfd.v1"
RESOLUTIONS = (0.01, 0.0075, 0.005)
LEGACY_RESOLUTIONS = (0.09 / 11, 0.0075, 0.006)
REVISION_ID = "F4_H1_native_mdbc_mass_resolved_v1"
QUALIFICATION_HORIZON_S = 4.34
QUALIFICATION_OUTPUT_INTERVAL_S = 0.02
SOURCE_MASS_ERROR_MAX = 0.025
TOTAL_MASS_ERROR_MAX = 0.03
WALL = dict(xmin=0., xmax=1.2, ymin=0., ymax=.4, zmin=0., zmax=.6)
CLOSED = ["bottom", "left", "right", "front", "back"]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def native_frame(path: Path, temporary: Path, decoder: Path) -> tuple:
    if temporary.exists():
        shutil.rmtree(temporary)
    subprocess.run([str(decoder), str(path), str(temporary)], check=True, stdout=subprocess.DEVNULL)
    root = ET.parse(str(temporary) + ".xml").getroot()
    parent = root.find("item")
    node = parent.find("item")
    metadata = {e.get("name"): e.get("v") for e in parent if e.tag != "item"}
    info = {e.get("name"): e.get("v") for e in node if e.tag != "item"}
    folder = temporary / node.get("name")
    ids = np.fromfile(folder / "Idp.bin", np.uint32)
    order = np.argsort(ids)
    position_file = folder / "Posd.bin" if (folder / "Posd.bin").exists() else folder / "Pos.bin"
    position = np.fromfile(position_file, np.float64 if position_file.name == "Posd.bin" else np.float32).reshape(-1, 3)
    velocity = np.fromfile(folder / "Vel.bin", np.float32).reshape(-1, 3)
    density = np.fromfile(folder / "Rhop.bin", np.float32)
    if len(np.unique(ids)) != len(ids):
        raise ValueError("duplicate native identities")
    return ids[order], position[order], velocity[order], density[order], metadata, info, folder


def lattice_box(low: list[float], size: list[float], dp: float) -> dict:
    """Cell-centre sampling of a declared half-open continuous physical box."""
    low_array, size_array = np.asarray(low), np.asarray(size)
    first = np.ceil(low_array / dp - .5 - 1e-10).astype(int)
    stop = np.ceil((low_array + size_array) / dp - .5 - 1e-10).astype(int)
    counts = stop - first
    if np.any(counts <= 0):
        raise ValueError("fluid region unresolved by this lattice")
    return dict(continuous_low_m=low, continuous_size_m=size,
                first_center_m=((first + .5) * dp).tolist(),
                draw_size_m=((counts - 1) * dp).tolist(), counts=counts.tolist(),
                particle_count=int(np.prod(counts)),
                continuous_mass_kg=float(np.prod(size_array) * 1000),
                discrete_mass_kg=float(np.prod(counts) * dp**3 * 1000))


def mass_quality(sampling: dict) -> dict:
    """Check native cell-centre mass against the declared continuum volume.

    The native solver mass remains ``rho*dp**3``.  This report is a gate on
    the representation error; it never changes the mass stored in a case.
    """
    boxes = sampling["fluid_boxes"]
    errors = [float(box["discrete_mass_kg"] / box["continuous_mass_kg"] - 1.) for box in boxes]
    discrete = float(sum(box["discrete_mass_kg"] for box in boxes))
    continuous = float(sum(box["continuous_mass_kg"] for box in boxes))
    total_error = float(discrete / continuous - 1.)
    max_source_error = max(map(abs, errors), default=0.)
    passed = bool(max_source_error <= SOURCE_MASS_ERROR_MAX and abs(total_error) <= TOTAL_MASS_ERROR_MAX)
    return {"source_relative_errors": errors, "max_abs_source_relative_error": max_source_error,
            "total_discrete_mass_kg": discrete, "total_continuous_mass_kg": continuous,
            "total_relative_error": total_error,
            "source_error_max": SOURCE_MASS_ERROR_MAX, "total_error_max": TOTAL_MASS_ERROR_MAX,
            "mass_rescaling": False, "pass": passed, "mass_gate_pass": passed}


def preregistered_numeric_gates() -> dict:
    """Return the frozen numerical gates for the F4 H1 qualification window."""
    return dict(
        no_missing_native_fluid_ids=True,
        no_nonfinite_active_values=True,
        closed_wall_endpoint_tolerance_m=1e-8,
        saved_chord_crossings_allowed=0,
        source_initial_mass_relative_error_max=SOURCE_MASS_ERROR_MAX,
        initial_mass_spread_over_continuous_mass_max=TOTAL_MASS_ERROR_MAX,
        mass_change_relative_max=1e-8,
        observables=["center_of_mass_xyz_over_tank_lengths",
                     "kinetic_energy_over_initial_potential_plus_kinetic",
                     "mass_fractions_in_fixed_4x2x4_cells"],
        spatial_max_absolute_normalized_difference=.05,
        temporal_fraction_of_spatial_budget=.2,
        monotone_refinement_required=True,
        registered_window_s=dict(initial=QUALIFICATION_HORIZON_S,
                                 output_interval=QUALIFICATION_OUTPUT_INTERVAL_S,
                                 maximum_extended=2 * QUALIFICATION_HORIZON_S),
        event_window=("contact, upward propagation, return crossing, and post-return "
                      "gravity-time window; else whole-scope doubling once"),
        qualified=False)


def event_horizon(pool: dict, drop: dict, *, cadence: float = .02) -> dict:
    depth = pool["size"][2]
    height = drop["low"][2] + drop["size"][2] - (pool["low"][2] + depth)
    downward = .5
    ballistic = (math.sqrt(downward**2 + 2 * 9.81 * height) - downward) / 9.81
    length = WALL["xmax"] - WALL["xmin"]
    gravity_time = math.sqrt(length / 9.81)
    wave_time = length / math.sqrt(9.81 * depth)
    horizon = math.ceil((ballistic + 4 * max(gravity_time, wave_time)) / cadence) * cadence
    return dict(ballistic_time_s=ballistic, gravity_time_s=gravity_time,
                wave_time_s=wave_time, predeclared_multiplier=4,
                initial_horizon_s=horizon, maximum_extended_horizon_s=2 * horizon,
                policy="one whole-scope doubling for event right-censoring; never shorten on failure",
                event_completion_proven=False)


def f4_config(dp: float = .006, q: float = .5, recipe: str = "mdbc_native", stage: str = "canary") -> dict:
    if dp not in set(RESOLUTIONS + LEGACY_RESOLUTIONS) or not 0 <= q <= 1 or recipe not in {"mdbc_native", "dbc_three_layers"}:
        raise ValueError("outside registered candidate design")
    # Endpoints are the retained offset (.25) and centre (.47) backgrounds.
    pool = dict(low=[.08, .04, .04], size=[1.04, .32, .14], mkfluid=0)
    drop = dict(low=[.25 + .22 * q, .12, .4], size=[.26, .16, .14], mkfluid=1)
    horizon = event_horizon(pool, drop)
    return dict(schema=SCHEMA, family="F4", scope_id="F4_drop_pool_x_v1",
                case_id=f"CORE_F4_{recipe}_q{q:.8f}_dp{dp:.12f}_{stage}".replace(".", "p"),
                recipe_id=f"CORE_F4_{recipe}_cell_center_v1", recipe=recipe,
                stage=stage, qualification_claim="none", qualified=False,
                parameter=dict(name="drop_left_x_m", q=q, value=.25 + .22*q, candidate_range=[.25, .47]),
                dp_m=dp, pool=pool, drop=drop, gravity_m_s2=[0., 0., -9.81],
                initial_drop_velocity_m_s=[0., 0., -.5],
                wall_bounds=WALL, closed_faces=CLOSED, open_faces=["top"],
                output_interval_s=.02,
                time_max_s=.30 if stage == "canary" else horizon["initial_horizon_s"],
                horizon=horizon, canary_window_reason="historical first failure at .18 s plus six .02 s outputs",
                cfl=.05, boundary_layers=[0, 1, 2],
                source_label_semantics="initial native Mk numerical source partition; not material truth",
                physical_case_id=f"F4_drop_pool_x_q{q:.12g}",
                lineage_group_id=f"F4_drop_pool_x_q{q:.12g}")


def qualification_design(recipe: str = "mdbc_native") -> dict:
    """Frozen 13 spatial + 2 temporal cells, excluded from ML splits."""
    cells=[]
    for q in (0., .5, 1., .25, .75):
        for dp in (RESOLUTIONS if q in (0.,.5,1.) else RESOLUTIONS[1:]):
            cfg=f4_config(dp,q,recipe,"qualification")
            cfg.update(design_cell="spatial",split="qualification_only")
            cells.append(cfg)
    for kind in ("internal_time","native_output"):
        cfg=f4_config(.0075,.5,recipe,"qualification")
        cfg.update(design_cell=kind,split="qualification_only")
        cfg["case_id"] += "_"+kind
        if kind=="internal_time": cfg["cfl"] *= .5
        else: cfg["output_interval_s"] /= 5
        cells.append(cfg)
    return dict(schema=SCHEMA, scope_id="F4_drop_pool_x_v1", revision_id=REVISION_ID,
      created_at=stamp(), recipe=recipe, qualification_claim="none", cells=cells,
      held_out_q=[.25, .75], replacement_q=[.125, .375, .625, .875],
      continuum_geometry=dict(pool={"low": [.08, .04, .04], "size": [1.04, .32, .14]},
                              drop_size_m=[.26, .16, .14], density_kg_m3=1000.,
                              unchanged=True),
      mass_policy="native rho*dp^3, no mass rescaling; continuous-volume representation error is gated",
      registered_window=dict(initial_time_max_s=QUALIFICATION_HORIZON_S,
                            output_interval_s=QUALIFICATION_OUTPUT_INTERVAL_S,
                            maximum_extended_time_max_s=2 * QUALIFICATION_HORIZON_S,
                            event_completion_required=True),
      preregistered_gates=preregistered_numeric_gates())


def prepare_matrix(lab: Path, output: Path, recipe: str) -> dict:
    design=qualification_design(recipe);manifest=output/"design.json"
    if manifest.exists(): raise ValueError("matrix already registered")
    write_json(manifest,design);rows=[]
    for index,config in enumerate(design["cells"]):
        target=output/f"cell-{index:02d}";result=prepare(config,lab,target)
        rows.append(dict(index=index, case_id=config["case_id"],
                         prepared=str((target / "prepared.json").resolve()),
                         preflight_pass=result["preflight_pass"],
                         mass_preflight_pass=result["mass_preflight"]["mass_gate_pass"]))
        write_json(output/"prepared-matrix.json",dict(schema=SCHEMA,design_sha256=digest(manifest),cells=rows,complete=len(rows)==15,qualification_claim="none"))
    return dict(preflight_pass=all(x["preflight_pass"] for x in rows),qualification_claim="none; preparation only")


def _box(parent: ET.Element, fill: str, low: list, size: list, layers: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, "drawbox")
    ET.SubElement(node, "boxfill").text = fill
    ET.SubElement(node, "point", dict(zip("xyz", map(lambda x: f"{x:.17g}", low))))
    ET.SubElement(node, "size", dict(zip("xyz", map(lambda x: f"{x:.17g}", size))))
    if layers is not None:
        ET.SubElement(node, "layers", {"vdp": layers})
    return node


def definition(config: dict, template: Path, target: Path) -> dict:
    tree = ET.parse(template)
    root = tree.getroot()
    dp = config["dp_m"]
    height = float(config.get("container_height_m", .6))
    if not math.isfinite(height) or height <= 0:
        raise ValueError("container height must be finite and positive")
    if "container_height_m" in config and config["wall_bounds"]["zmax"] != height:
        raise ValueError("container height and audit wall bounds differ")
    geometry = root.find(".//casedef/geometry")
    d = geometry.find("definition")
    d.set("dp", f"{dp:.17g}")
    for child in list(d):
        d.remove(child)
    ET.SubElement(d, "pointref", {axis: f"{dp/2:.17g}" for axis in "xyz"})
    ET.SubElement(d, "pointmin", dict(x="-0.2", y="-0.2", z="-0.2"))
    ET.SubElement(d, "pointmax", dict(x="1.4", y="0.6", z="0.8"))
    if "container_height_m" in config:
        d.find("pointmax").set("z", str(height + .2))
    commands = geometry.find("commands")
    commands.clear()
    if config["recipe"] == "mdbc_native":
        normals = ET.SubElement(commands, "list", {"name": "GeometryForNormals"})
        ET.SubElement(normals, "setactive", dict(drawpoints="0", drawshapes="1"))
        ET.SubElement(normals, "setshapemode").text = "actual | bound"
        ET.SubElement(normals, "setnormalinvert", dict(invert="true"))
        ET.SubElement(normals, "setmkbound", dict(mk="0"))
        _box(normals, "all^top", [0, 0, 0], [1.2, .4, height], "0")
        ET.SubElement(normals, "shapeout", dict(file="hdp"))
        ET.SubElement(normals, "resetdraw")
    main = ET.SubElement(commands, "mainlist")
    if config["recipe"] == "mdbc_native":
        ET.SubElement(main, "runlist", dict(name="GeometryForNormals"))
    ET.SubElement(main, "setdrawmode", dict(mode="full"))
    fluid_boxes = []
    for item in (config["pool"], config["drop"]):
        sample = lattice_box(item["low"], item["size"], dp)
        sample["mkfluid"] = item["mkfluid"]
        fluid_boxes.append(sample)
        ET.SubElement(main, "setmkfluid", dict(mk=str(item["mkfluid"])))
        _box(main, "solid", sample["first_center_m"], sample["draw_size_m"])
    ET.SubElement(main, "setmkbound", dict(mk="0"))
    _box(main, "all^top", [-dp/2]*3, [1.2+dp, .4+dp, height+dp/2], "0,1,2")
    casedef = root.find("casedef")
    old_normals = casedef.find("normals")
    if old_normals is not None:
        casedef.remove(old_normals)
    if config["recipe"] == "mdbc_native":
        n = ET.SubElement(casedef, "normals", dict(active="true"))
        ngeom = ET.SubElement(n, "norgeometry")
        ET.SubElement(ngeom, "geometryfile", dict(file="[CaseName]_hdp_Actual.vtk"))
        ET.SubElement(ngeom, "distanceh", dict(v="3.0"))
    initials = casedef.find("initials")
    if initials is None:
        initials = ET.SubElement(casedef, "initials")
    initials.clear()
    ET.SubElement(initials, "velocity", dict(mkfluid="1", x="0", y="0", z="-0.5"))
    execution = root.find("execution")
    special = execution.find("special")
    if special is not None:
        execution.remove(special)
    root.find(".//constantsdef/cflnumber").set("value", str(config["cfl"]))
    parameters = execution.find("parameters")
    changes = dict(SavePosDouble=2, TimeMax=config["time_max_s"], TimeOut=config["output_interval_s"],
                   Boundary=2 if config["recipe"] == "mdbc_native" else 1,
                   SlipMode=2, NoPenetration=1 if config["recipe"] == "mdbc_native" else 0,
                   Shifting=0, PartsOutMax=1)
    # Explicit diagnostic overrides are needed when the inherited minimum
    # step clamps both CFL settings to the same actual integration schedule.
    for field, key in (("dt_min_s", "DtMin"), ("dt_ini_s", "DtIni")):
        if field in config:
            value = float(config[field])
            if not math.isfinite(value) or value <= 0:
                raise ValueError("explicit integration timestep must be finite and positive")
            changes[key] = value
    if "physical_kinematic_viscosity_m2_s" in config:
        viscosity = float(config["physical_kinematic_viscosity_m2_s"])
        if not math.isfinite(viscosity) or viscosity <= 0:
            raise ValueError("physical kinematic viscosity must be finite and positive")
        if config.get("viscosity_formulation") != "laminar":
            raise ValueError("explicit physical viscosity requires laminar formulation")
        changes.update(ViscoTreatment=3, Visco=viscosity)
    for key, value in changes.items():
        node = parameters.find(f"parameter[@key='{key}']")
        if node is None:
            node = ET.SubElement(parameters, "parameter", dict(key=key))
        node.set("value", str(value))
    domain = parameters.find("simulationdomain")
    if domain is None:
        domain = ET.SubElement(parameters, "simulationdomain")
    domain.clear()
    ET.SubElement(domain, "posmin", dict(x="-1.2", y="-0.4", z="-0.6"))
    ET.SubElement(domain, "posmax", dict(x="2.4", y="0.8", z="1.8"))
    if height + .6 > 1.8:
        domain.find("posmax").set("z", str(height + .6))
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return dict(fluid_boxes=fluid_boxes, expected_fluid_particles=sum(b["particle_count"] for b in fluid_boxes),
                continuous_mass_kg=sum(b["continuous_mass_kg"] for b in fluid_boxes),
                sampled_mass_kg=sum(b["discrete_mass_kg"] for b in fluid_boxes),
                mass_policy="native rho*dp^3, no mass rescaling; continuous-volume representation error explicit")


def environment(lab: Path) -> dict:
    env = os.environ.copy()
    binary_dir = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    env["LD_LIBRARY_PATH"] = str(binary_dir) + ":" + env.get("LD_LIBRARY_PATH", "")
    env.setdefault("OMP_NUM_THREADS", "2")
    return env


def prepare(config: dict, lab: Path, output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("preparation output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    template = lab / "campaigns/l1-resume/artifacts/f3-revision075/F3_REV075_R075-ENDPOINT-LOW-0075/F3_CELL3_plain_0p0075_Def.xml"
    target = output / (config["case_id"] + "_Def.xml")
    sampling = definition(config, template, target)
    prefix = output / "generated" / config["case_id"]
    prefix.parent.mkdir()
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    command = [str(binaries / "GenCase_linux64"), str(target.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError("GenCase failed; inspect " + str(output / "gencase.log"))
    generated = ET.parse(prefix.with_suffix(".xml")).getroot()
    blocks = generated.findall(".//particles/fluid")
    if len(blocks) != 2:
        raise ValueError("expected two native source blocks")
    generated_counts = {int(b.get("mkfluid")): int(b.get("count")) for b in blocks}
    expected_counts = {b["mkfluid"]: b["particle_count"] for b in sampling["fluid_boxes"]}
    if generated_counts != expected_counts:
        raise ValueError(f"GenCase lattice differs from declaration: {generated_counts} vs {expected_counts}")
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    mass = mass_quality(sampling)
    with tempfile.TemporaryDirectory(prefix="core-initial-") as folder:
        ids, pos, vel, rho, meta, info, arrays = native_frame(prefix.with_suffix(".bi4"), Path(folder)/"native", decoder)
        boundary_count = int(meta["CaseNfixed"])
        normal_file = arrays / "BoundNor.bin"
        normals = np.fromfile(normal_file, np.float32).reshape(-1, 3) if normal_file.exists() else np.empty((0, 3))
        zero_normals = int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10))
        normal_ok = config["recipe"] != "mdbc_native" or (len(normals) == boundary_count and zero_normals == 0 and np.isfinite(normals).all())
        initial_state_ok = all(np.isfinite(a).all() for a in (pos, vel, rho)) and normal_ok
        native = dict(total_particles=len(ids), boundary_particles=boundary_count,
                      fluid_particles=int(meta["CaseNfluid"]), normal_count=len(normals),
                      zero_boundary_normals=zero_normals, native_initial_mass_kg=float(meta["MassFluid"])*int(meta["CaseNfluid"]),
                      initial_state_pass=bool(initial_state_ok))
    preflight_pass = bool(initial_state_ok and mass["mass_gate_pass"])
    inputs = {str(p.resolve()): digest(p) for p in output.rglob("*") if p.is_file()}
    prepared = dict(schema=SCHEMA, created_at=stamp(), config=config, sampling=sampling,
                    native_initial=native, mass_preflight=mass,
                    preflight_pass=preflight_pass,
                    generated_prefix=str(prefix.resolve()), source_template=str(template),
                    source_template_sha256=digest(template), inputs=inputs,
                    solver_binary=str(binaries/"DualSPHysics5.4_linux64"),
                    solver_sha256=digest(binaries/"DualSPHysics5.4_linux64"),
                    decoder=str(decoder), decoder_sha256=digest(decoder),
                    solver_arguments=["-mdbc_noslip:1"] if config["recipe"] == "mdbc_native" else [],
                    qualification_claim="none; preparation only")
    write_json(output / "prepared.json", prepared)
    return prepared


def _qualification_signature() -> list[tuple[float, float, str]]:
    signature = []
    for q in (0., .5, 1., .25, .75):
        for dp in (RESOLUTIONS if q in (0., .5, 1.) else RESOLUTIONS[1:]):
            signature.append((q, dp, "spatial"))
    signature.extend((.5, .0075, kind) for kind in ("internal_time", "native_output"))
    return signature


def validate_prepared_matrix(matrix_root: Path) -> dict:
    """Validate a prepared F4 revision without launching a solver.

    This is deliberately independent of execution evidence.  It checks the
    registered 13+2 cells, unchanged continuum geometry, native mass policy,
    full-window inputs, and the static native initialization records.
    """
    matrix_root = Path(matrix_root).resolve()
    design_path = matrix_root / "design.json"
    matrix_path = matrix_root / "prepared-matrix.json"
    if not design_path.exists() or not matrix_path.exists():
        raise FileNotFoundError("prepared matrix requires design.json and prepared-matrix.json")
    design = json.loads(design_path.read_text())
    matrix = json.loads(matrix_path.read_text())
    issues = []
    if design.get("schema") != SCHEMA or matrix.get("schema") != SCHEMA:
        issues.append("schema mismatch")
    if design.get("qualification_claim") != "none" or matrix.get("qualification_claim") != "none":
        issues.append("qualification claim is not explicitly none")
    if matrix.get("design_sha256") != digest(design_path):
        issues.append("prepared matrix design hash mismatch")
    gates = design.get("preregistered_gates", {})
    for key, expected in {
        "source_initial_mass_relative_error_max": SOURCE_MASS_ERROR_MAX,
        "initial_mass_spread_over_continuous_mass_max": TOTAL_MASS_ERROR_MAX,
        "closed_wall_endpoint_tolerance_m": 1e-8,
        "saved_chord_crossings_allowed": 0,
        "mass_change_relative_max": 1e-8,
        "spatial_max_absolute_normalized_difference": .05,
        "temporal_fraction_of_spatial_budget": .2,
    }.items():
        if gates.get(key) != expected:
            issues.append(f"gate {key} is not preregistered at {expected}")
    expected = _qualification_signature()
    rows = matrix.get("cells", [])
    if len(rows) != 15 or not matrix.get("complete"):
        issues.append("matrix is not a complete 15-cell registration")
    cells = []
    for index, (q, dp, kind) in enumerate(expected):
        row = rows[index] if index < len(rows) else {}
        prepared_path = Path(row.get("prepared", matrix_root / f"cell-{index:02d}" / "prepared.json"))
        if not prepared_path.exists():
            issues.append(f"cell {index:02d} prepared.json is missing")
            cells.append({"index": index, "q": q, "dp_m": dp, "design_cell": kind,
                          "pass": False, "pass_": False, "issues": ["missing prepared.json"]})
            continue
        prepared = json.loads(prepared_path.read_text())
        cfg = prepared.get("config", {})
        cell_issues = []
        actual_q = cfg.get("parameter", {}).get("q")
        if actual_q is None or not math.isclose(float(actual_q), q, abs_tol=1e-12):
            cell_issues.append(f"q={actual_q} expected {q}")
        if not math.isclose(float(cfg.get("dp_m", -1)), dp, abs_tol=1e-12):
            cell_issues.append(f"dp={cfg.get('dp_m')} expected {dp}")
        if cfg.get("design_cell") != kind or cfg.get("stage") != "qualification":
            cell_issues.append("design cell/stage mismatch")
        if not math.isclose(float(cfg.get("time_max_s", -1)), QUALIFICATION_HORIZON_S, abs_tol=1e-9):
            cell_issues.append("full qualification horizon is not 4.34 s")
        expected_cfg = f4_config(dp, q, cfg.get("recipe", "mdbc_native"), "qualification")
        if design.get('scope_id') in ('F4_drop_resting_pool_x_v2',
                                       'F4_drop_resting_pool_laminar_nu1e6_x_v1'):
            expected_cfg['pool'] = dict(low=[0., 0., 0.], size=[1.2, .4, .18], mkfluid=0)
        elif design.get('scope_id') != 'F4_drop_pool_x_v1':
            cell_issues.append('unregistered F4 physical scope')
        if cfg.get('scope_id') != design.get('scope_id'):
            cell_issues.append('prepared case belongs to another scope')
        if design.get('scope_id') == 'F4_drop_resting_pool_laminar_nu1e6_x_v1':
            if (cfg.get('physical_kinematic_viscosity_m2_s') != 1e-6
                    or cfg.get('viscosity_formulation') != 'laminar'):
                cell_issues.append('fixed physical laminar viscosity differs from registration')
        if cfg.get("pool") != expected_cfg["pool"] or cfg.get("drop") != expected_cfg["drop"]:
            cell_issues.append("continuum pool/drop geometry changed")
        if "no mass rescaling" not in prepared.get("sampling", {}).get("mass_policy", ""):
            cell_issues.append("native mass policy is missing or rescaled")
        try:
            mass = mass_quality(prepared["sampling"])
        except (KeyError, TypeError, ZeroDivisionError) as exc:
            mass = {"mass_gate_pass": False, "source_relative_errors": [], "error": repr(exc)}
            cell_issues.append("mass declaration is incomplete")
        if not mass.get("mass_gate_pass"):
            cell_issues.append("source/aggregate native mass gate failed")
        native = prepared.get("native_initial", {})
        if not prepared.get("preflight_pass"):
            cell_issues.append("native static preflight did not pass")
        if not native.get("initial_state_pass"):
            cell_issues.append("native initial finite/normal state did not pass")
        if native.get("fluid_particles") != prepared.get("sampling", {}).get("expected_fluid_particles"):
            cell_issues.append("native fluid particle count differs from declaration")
        if row.get("case_id") != cfg.get("case_id"):
            cell_issues.append("prepared matrix case identity mismatch")
        if cell_issues:
            issues.extend(f"cell {index:02d}: {item}" for item in cell_issues)
        cell_report = dict(index=index, case_id=cfg.get("case_id"), q=q, dp_m=dp,
                           design_cell=kind, prepared=str(prepared_path),
                           particle_count=prepared.get("sampling", {}).get("expected_fluid_particles"),
                           source_mass_relative_errors=mass.get("source_relative_errors", []),
                           total_mass_relative_error=mass.get("total_relative_error"),
                           mass_gate_pass=bool(mass.get("mass_gate_pass")),
                           full_window_s=cfg.get("time_max_s"), pass_=not cell_issues,
                           issues=cell_issues)
        cell_report["pass"] = not cell_issues
        cells.append(cell_report)
    passed = not issues and len(cells) == 15 and all(cell["pass_"] for cell in cells)
    return dict(schema="core.cfd.static.v1", revision_id=REVISION_ID,
                matrix_root=str(matrix_root), design_sha256=digest(design_path),
                prepared_matrix_sha256=digest(matrix_path), cell_count=len(cells),
                spatial_cell_count=sum(x["design_cell"] == "spatial" for x in cells),
                temporal_cell_count=sum(x["design_cell"] != "spatial" for x in cells),
                registered_resolutions_m=list(RESOLUTIONS), registered_horizon_s=QUALIFICATION_HORIZON_S,
                registered_output_interval_s=QUALIFICATION_OUTPUT_INTERVAL_S,
                continuum_geometry_unchanged=True, mass_rescaling=False,
                static_quality_pass=passed, preflight_pass=passed,
                execution_status="not_started", qualification_claim="none",
                cells=cells, issues=issues,
                gate_summary=dict(source_mass_error_max=SOURCE_MASS_ERROR_MAX,
                                  aggregate_mass_error_max=TOTAL_MASS_ERROR_MAX,
                                  closed_wall_endpoint_tolerance_m=1e-8,
                                  saved_chord_crossings_allowed=0,
                                  spatial_normalized_difference_max=.05,
                                  temporal_fraction_of_spatial_budget=.2,
                                  full_window_event_completion_required=True))


def _resource_estimate(dp: float, *, canary: bool = False) -> dict:
    if canary:
        return dict(cpu_cores=2, ram_mib=16384, gpu_peak_mib=4096, io_weight=1)
    if dp <= .005 + 1e-12:
        return dict(cpu_cores=2, ram_mib=24576, gpu_peak_mib=6144, io_weight=1)
    if dp <= .0075 + 1e-12:
        return dict(cpu_cores=2, ram_mib=16384, gpu_peak_mib=4096, io_weight=1)
    return dict(cpu_cores=2, ram_mib=12288, gpu_peak_mib=3072, io_weight=1)


def _job_spec(prepared_path: Path, lab: Path, job_id: str, *, category: str,
              timeout_seconds: int, canary: bool = False, matrix_index: int | None = None) -> dict:
    prepared_path = Path(prepared_path).resolve()
    prepared = json.loads(prepared_path.read_text())
    solver = Path(prepared["solver_binary"]).resolve()
    # Keep the lab virtualenv path in the spec.  Resolving this symlink to the
    # host interpreter would bypass the worker's declared environment.
    python = Path(lab) / ".venv/bin/python"
    spec = dict(
        schema="core.cfd.job.v1", job_id=job_id, logical_id=job_id,
        attempt_role="initial", category=category, host="ada", source_lab=str(Path(lab).resolve()),
        cwd=str(Path(lab).resolve()),
        argv=[str(python), str((Path(lab) / "scripts/core_cfd.py").resolve()),
              "--lab-root", str(Path(lab).resolve()), "run", "--prepared", str(prepared_path),
              "--output", "{attempt_dir}/product"],
        required_outputs=["product/result.json", "product/trajectory.h5", "product/audit.json",
                          "product/observations.json"],
        resources=_resource_estimate(float(prepared["config"]["dp_m"]), canary=canary),
        timeout_seconds=timeout_seconds, depends_on=[], qualification_claim="none",
        input_files=[dict(path=str(prepared_path), sha256=digest(prepared_path)),
                     dict(path=str(solver), sha256=digest(solver))],
        prepared_case_id=prepared["config"]["case_id"],
        registered_window_s=prepared["config"]["time_max_s"],
        worker_contract="core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0")
    if matrix_index is not None:
        spec["matrix_index"] = matrix_index
    return spec


def make_job(prepared_path: Path, lab: Path, output: Path, *, job_id: str,
             category: str = "qualification_canary", timeout_seconds: int = 1800,
             canary: bool = True) -> dict:
    """Write one runtime-ready worker spec; execution remains coordinator-owned."""
    spec = _job_spec(prepared_path, lab, job_id, category=category,
                     timeout_seconds=timeout_seconds, canary=canary)
    write_json(Path(output), spec)
    return spec


def make_qualification_jobs(matrix_root: Path, lab: Path, output: Path) -> dict:
    """Write 15 immutable job specs after static revision validation passes."""
    matrix_root, lab, output = Path(matrix_root).resolve(), Path(lab).resolve(), Path(output).resolve()
    validation = validate_prepared_matrix(matrix_root)
    if not validation["static_quality_pass"]:
        raise ValueError("static revision validation failed; no qualification jobs written")
    matrix = json.loads((matrix_root / "prepared-matrix.json").read_text())
    jobs_dir = output.with_suffix("")
    jobs_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for index, row in enumerate(matrix["cells"]):
        prepared_path = Path(row["prepared"])
        job_id = f"f4-h1-qualification-cell-{index:02d}"
        spec = _job_spec(prepared_path, lab, job_id, category="qualification",
                         timeout_seconds=7200, canary=False, matrix_index=index)
        path = jobs_dir / f"{job_id}.json"
        write_json(path, spec)
        jobs.append(dict(index=index, job_id=job_id, path=str(path),
                         prepared=str(prepared_path), resources=spec["resources"],
                         argv=spec["argv"], required_outputs=spec["required_outputs"]))
    manifest = dict(schema="core.cfd.jobs.v1", revision_id=REVISION_ID,
                    matrix_root=str(matrix_root), matrix_sha256=digest(matrix_root / "prepared-matrix.json"),
                    static_validation=validation, jobs=jobs, job_count=len(jobs),
                    execution_status="prepared_only", qualification_claim="none")
    write_json(output, manifest)
    return manifest


def convert_native(prepared: dict, data: Path, output: Path) -> dict:
    config = prepared["config"]
    paths = sorted(data.glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    if len(paths) < 2:
        raise ValueError("fewer than two native frames")
    generated = ET.parse(Path(prepared["generated_prefix"]).with_suffix(".xml")).getroot()
    blocks = generated.findall(".//particles/fluid")
    axis = np.concatenate([np.arange(int(b.get("begin")), int(b.get("begin"))+int(b.get("count")), dtype=np.uint32) for b in blocks])
    mk = np.concatenate([np.full(int(b.get("count")), int(b.get("mk")), np.int16) for b in blocks])
    n, nt = len(axis), len(paths)
    partial = output.with_suffix(".h5.partial")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="core-native-") as folder, h5py.File(partial, "w") as h:
        h.attrs.update(schema_version=3, case_id=config["case_id"], family=config["family"],
                       conversion_complete=False, particle_shifting="disabled", identity_key="particle_id",
                       trajectory_semantics="numerical SPH particle identity; material fidelity requires separate audit",
                       source_label_semantics=config["source_label_semantics"],
                       data_qualification_status="candidate_unqualified", recipe_id=config["recipe_id"],
                       physical_case_id=config["physical_case_id"], lineage_group_id=config["lineage_group_id"],
                       control_semantics="known initial geometry, liquid velocity and gravity; no future fluid state",
                       pressure_semantics="EOS from native density and native B/Rhop0/Gamma", T2_macro_status="not_assessed")
        h.create_dataset("particle_id", data=axis)
        h.create_dataset("particle_zone", data=np.zeros(n, np.int16))
        h.create_dataset("source_label_initial_mk", data=mk)
        h.create_dataset("time", shape=(nt,), dtype="f8")
        chunk = min(n, 65536)
        for name in ("position", "velocity", "density", "mass", "pressure", "valid", "type", "mk"):
            vector = name in ("position", "velocity")
            dtype = "f8" if name == "position" else "bool" if name == "valid" else "i2" if name in ("type", "mk") else "f4"
            fill = False if name == "valid" else -1 if name in ("type", "mk") else np.nan
            h.create_dataset(name, shape=(nt,n,3) if vector else (nt,n), dtype=dtype,
                             chunks=(1,chunk,3) if vector else (1,chunk), compression="lzf", fillvalue=fill)
        previous_time = -1.
        for fi, path in enumerate(paths):
            ids, p, v, rho, meta, info, _ = native_frame(path, Path(folder)/"frame", Path(prepared["decoder"]))
            index = np.searchsorted(axis, ids)
            selected = index < n
            selected[selected] &= axis[index[selected]] == ids[selected]
            index = index[selected]
            if np.unique(index).size != len(index):
                raise ValueError("duplicate mapped fluid identities")
            current_time = float(info["TimeStep"])
            if current_time <= previous_time:
                raise ValueError("non-increasing native time")
            previous_time = current_time
            h["time"][fi] = current_time
            h["valid"][fi, index] = True
            pressure = float(meta["B"])*((rho[selected].astype(float)/float(meta["Rhop0"]))**float(meta["Gamma"])-1)
            for name, values in [("position",p[selected]),("velocity",v[selected]),("density",rho[selected]),
                                 ("pressure",pressure),("mass",np.full(len(index),float(meta["MassFluid"]))),
                                 ("type",np.full(len(index),3)),("mk",mk[index])]:
                h[name][fi,index] = values
            h.attrs["conversion_complete_frames"] = fi+1
        h.attrs["conversion_complete"] = True
    partial.replace(output)
    return dict(hdf5=str(output), frames=nt, particle_count=n, sha256=digest(output))


def observation_geometry(cfg: dict):
    """Explicit observer versions; geometry changes must not hide lost sensitivity."""
    height = float(cfg.get("container_height_m", .6))
    version = cfg.get("observation_version", "legacy_tank_scaled_v1")
    if not math.isfinite(height) or height <= 0:
        raise ValueError("observer requires finite positive container height")
    if version == "legacy_tank_scaled_v1":
        edges = [np.linspace(0, 1.2, 5), np.linspace(0, .4, 3), np.linspace(0, height, 5)]
        scale = [1.2, .4, height]
    elif version == "fixed_015m_vertical_reference060_v2":
        # Preserve all original .15 m planes, including for taller containers.
        z = np.arange(0., height, .15)
        if len(z) and math.isclose(z[-1], height, abs_tol=1e-12):
            z = z[:-1]
        edges = [np.linspace(0, 1.2, 5), np.linspace(0, .4, 3), np.append(z, height)]
        scale = [1.2, .4, .6]
    else:
        raise ValueError(f"unknown observation version: {version}")
    return edges, scale, version


def physical_observations(prepared: dict, hdf5: Path) -> dict:
    """Resolution-independent fixed geometric observations, not material labels."""
    cfg=prepared["config"];time_axis=[];values=[];event_rows=[]
    continuous=sum(b["continuous_mass_kg"] for b in prepared["sampling"]["fluid_boxes"])
    source_errors=[]
    with h5py.File(hdf5,"r") as h:
        initial=h["position"][0];m0=h["mass"][0].astype(float);v0=h["velocity"][0].astype(float)
        labels=h["source_label_initial_mk"][:]
        energy0=float(np.sum(m0*(9.81*initial[:,2]+.5*np.sum(v0*v0,axis=1))))
        for label,box in zip(sorted(np.unique(labels)),prepared["sampling"]["fluid_boxes"]):
            source_errors.append(float(m0[labels==label].sum()/box["continuous_mass_kg"]-1))
        drop_mask=labels==max(np.unique(labels));drop_mass=float(m0[drop_mask].sum())
        level=cfg["pool"]["low"][2]+cfg["pool"]["size"][2]
        edges,com_scale,observer_version=observation_geometry(cfg)
        for fi,t in enumerate(h["time"][:]):
            valid=h["valid"][fi].astype(bool);pos=h["position"][fi];vel=h["velocity"][fi];mass=h["mass"][fi].astype(float)
            active=valid & np.isfinite(pos).all(axis=1) & np.isfinite(vel).all(axis=1) & np.isfinite(mass)
            p,v,m=pos[active],vel[active],mass[active]
            com=(m[:,None]*p).sum(axis=0)/max(m.sum(),1e-30)/com_scale
            energy=float(np.sum(.5*m*np.sum(v*v,axis=1))/max(energy0,1e-30))
            grid=np.histogramdd(p,bins=edges,weights=m)[0].reshape(-1)/continuous
            overflow=float(m.sum()/continuous-grid.sum())
            values.append([*com,energy,*grid,overflow]);time_axis.append(float(t))
            d=active & drop_mask
            event_rows.append([float(mass[d & (pos[:,2]<level)].sum()/drop_mass),
                               float(mass[d & (vel[:,2]>.05)].sum()/drop_mass),
                               float(mass[d & (vel[:,2]<-.05)].sum()/drop_mass)])
    rows=np.asarray(event_rows);times=np.asarray(time_axis)
    contact=np.flatnonzero(rows[:,0]>=.05)
    upward=np.flatnonzero((rows[:,1]>=.05)&(times>times[contact[0]])) if len(contact) else []
    returned=np.flatnonzero((rows[:,2]>=.05)&(times>times[upward[0]]+.1)) if len(upward) else []
    completion=bool(len(returned) and times[-1]-times[returned[0]]>=math.sqrt(1.2/9.81))
    return dict(time_s=time_axis,normalized_values=values,source_initial_mass_relative_errors=source_errors,
                source_mass_gate_pass=max(map(abs,source_errors))<=.025,
                observable_layout=("COM xyz / tank lengths; KE / initial energy; fixed4x2x4 mass/continuous mass; overflow mass fraction" if observer_version == "legacy_tank_scaled_v1" else f"COM xyz / declared lengths; KE / initial energy; fixed4x2x{len(edges[2])-1} mass/continuous mass; overflow mass fraction"),
                observation_version=observer_version,
                observation_geometry=dict(bin_edges_m=[e.tolist() for e in edges],com_scale_m=com_scale),
                event_detector="numerical source block: 5% below pool surface, then 5% upward vz>.05, then after .1s 5% downward vz<-.05, plus sqrt(1.2/g) observation",
                event_window_complete=completion,event_observations=event_rows,
                event_times_s=dict(contact=None if not len(contact) else time_axis[contact[0]],upward=None if not len(upward) else time_axis[upward[0]],returning=None if not len(returned) else time_axis[returned[0]]))


def audit(prepared: dict, output: Path) -> dict:
    from scripts.l2_campaign import inspect_hdf5
    from scripts.finite_wall_audit import outside_closed_face_masks, segment_crossing_events
    config = prepared["config"]
    hdf5 = output / "trajectory.h5"
    structural = inspect_hdf5(hdf5, full_scan=True, wall_bounds={**config["wall_bounds"], "closed_faces":CLOSED,"open_faces":["top"]})
    spec = dict(container_interior=config["wall_bounds"], closed_faces=CLOSED, obstacles=[])
    violations, seen, crossings, first = 0, set(), 0, None
    with h5py.File(hdf5,"r") as h:
        ids = h["particle_id"][:]
        prev = None
        for fi,t in enumerate(h["time"][:]):
            p, valid = h["position"][fi], h["valid"][fi].astype(bool)
            masks = outside_closed_face_masks(p,spec,1e-8)
            bad = np.logical_or.reduce(list(masks.values())) & valid
            if bad.any():
                violations += int(bad.sum()); seen.update(map(int,ids[bad]))
                if first is None:
                    first=dict(time_s=float(t), ids=ids[bad].tolist(), positions_m=p[bad].tolist())
            if prev is not None:
                common=valid & prev[1]
                crossings += len(segment_crossing_events(prev[0][common],p[common],spec,1e-8))
            prev=(p,valid)
        horizon_reached=bool(h["time"][-1] >= config["time_max_s"]-1e-6)
    report=dict(schema=SCHEMA, case_id=config["case_id"], structural=structural,
                endpoint_violation_particle_frames=violations, unique_wall_violation_ids=sorted(seen),
                first_wall_violation=first, saved_chord_crossing_count=crossings,
                saved_chord_semantics="saved-frame chord is a diagnostic, not exact substep path",
                requested_horizon_reached=horizon_reached,
                hard_integrity_pass=bool(structural.get("structural_pass") and not violations and not crossings and horizon_reached),
                qualified=False, qualification_claim="none; one case cannot establish range/temporal/reference qualification",
                event_window_complete=False, event_window_status="not_assessed" if config["stage"]!="canary" else "diagnostic_short_window")
    if config["family"]=="F4":
        observations=physical_observations(prepared,hdf5)
        write_json(output/"observations.json",observations)
        report.update(source_mass_gate_pass=observations["source_mass_gate_pass"], event_window_complete=observations["event_window_complete"], event_window_status="observed" if observations["event_window_complete"] else "right_censored_or_unresolved")
    write_json(output/"audit.json",report)
    return report


def run(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared=json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass"):
        raise ValueError("static preflight did not pass")
    declared_mass = mass_quality(prepared.get("sampling", {}))
    if not declared_mass["mass_gate_pass"]:
        raise ValueError("native source mass representation gate did not pass")
    for path, expected in prepared["inputs"].items():
        if digest(Path(path)) != expected:
            raise ValueError("changed prepared input: "+path)
    if digest(Path(prepared["solver_binary"])) != prepared["solver_sha256"] or digest(Path(prepared["decoder"])) != prepared["decoder_sha256"]:
        raise ValueError("changed native tool")
    visible=os.environ.get("CUDA_VISIBLE_DEVICES","")
    if not visible or "," in visible:
        raise ValueError("coordinator must provide exactly one CUDA_VISIBLE_DEVICES device")
    if output.exists() and any(output.iterdir()):
        raise ValueError("worker output must be fresh")
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/"prepared.json",prepared)
    solver_output=output/"solver"
    argv=[prepared["solver_binary"],"-gpu:0",*prepared["solver_arguments"],prepared["generated_prefix"],str(solver_output)]
    started=time.monotonic()
    write_json(output/"worker-status.json",dict(status="running",argv=argv,started_at=stamp(),cuda_visible_devices=visible))
    with (output/"solver.stdout.log").open("w") as log:
        proc=subprocess.run(argv,cwd=output,env=environment(lab),stdout=log,stderr=subprocess.STDOUT)
    solver_seconds=time.monotonic()-started
    if proc.returncode or "Finished execution (code=0)" not in (output/"solver.stdout.log").read_text():
        write_json(output/"worker-status.json",dict(status="solver_failed",returncode=proc.returncode,elapsed_seconds=solver_seconds))
        raise RuntimeError("solver failed; raw attempt retained")
    conversion=convert_native(prepared,solver_output/"data",output/"trajectory.h5")
    result=audit(prepared,output)
    result.update(solver_elapsed_seconds=solver_seconds,total_elapsed_seconds=time.monotonic()-started,conversion=conversion)
    write_json(output/"result.json",result)
    write_json(output/"worker-status.json",dict(status="complete_with_evidence",hard_integrity_pass=result["hard_integrity_pass"],finished_at=stamp()))
    return result


def forensics(lab: Path, output: Path) -> dict:
    from scripts.finite_wall_audit import outside_closed_face_masks
    source=lab/"campaigns/l2-multifamily/resume-c6b28c8/f4r-matrix.json"
    matrix=json.loads(source.read_text()); rows=[]
    spec=dict(container_interior=WALL,closed_faces=CLOSED)
    for cell in matrix["cells"]:
        path=Path(cell["audit"]["hdf5"])
        # Stored absolute paths may belong to the old host.
        if not path.exists():
            path=lab/str(path).split("lagrangian-fluid-lab/",1)[1]
        with h5py.File(path,"r") as h:
            ids=h["particle_id"][:]; seen=set(); count=0; first=None; max_depth=0.
            positions=[]
            for fi,t in enumerate(h["time"][:]):
                p=h["position"][fi]; valid=h["valid"][fi].astype(bool)
                for face,mask in outside_closed_face_masks(p,spec,1e-8).items():
                    mask &= valid
                    if mask.any():
                        count+=int(mask.sum()); seen.update(map(int,ids[mask])); first=float(t) if first is None else first
                        ax,plane,sign={"bottom":(2,0,-1),"left":(0,0,-1),"right":(0,1.2,1),"front":(1,0,-1),"back":(1,.4,1)}[face]
                        max_depth=max(max_depth,float(((p[mask,ax]-plane)*sign).max()))
            for identity in sorted(seen):
                i=int(np.flatnonzero(ids==identity)[0]); positions.append(dict(id=identity,position=h["position"][0,i].tolist(),source_mk=int(h["mk"][0,i])))
            m=h["mass"][0]; labels=h["mk"][0]; continuous=[1.04*.32*.14*1000,.26*.16*.14*1000]
            source_mass=[float(m[labels==label].sum(dtype=np.float64)) for label in sorted(np.unique(labels))]
            rows.append(dict(case_id=cell["cell"]["case_id"],dp_m=cell["cell"]["resolution_m"],
                             hdf5=str(path),hdf5_sha256=digest(path),wall_particle_frames=count,
                             first_violation_s=first,max_penetration_m=max_depth,unique_ids=sorted(seen),initial_affected=positions,
                             discrete_source_mass_kg=source_mass,continuous_source_mass_kg=continuous,
                             source_mass_relative_errors=[a/b-1 for a,b in zip(source_mass,continuous)]))
    report=dict(schema=SCHEMA,created_at=stamp(),source_sha256=digest(source),cells=rows,
                findings=["Fine-grid failures occur in the same four initial pool-corner particles in both backgrounds.",
                          "Original inclusive drawbox sampling changes physical volume representation; native masses are not rescaled.",
                          "Millimetre endpoint penetrations are not floating-point noise; causal boundary mechanism remains a hypothesis."],
                hypotheses=[dict(id="H1_complete_native_mdbc",scope="transfer full registered F3 three-layer, normals, symplectic, native no-penetration numerical recipe to unchanged F4 continuous geometry; cell-centre initialization explicit",attempt_limit=1),
                            dict(id="H2_three_layer_dbc",scope="matched cell-centre, three-layer and temporal configuration, replacing mDBC/native correction by DBC; conditional if H1 fails",attempt_limit=1)],
                qualification_claim="none")
    write_json(output,report);return report


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root",type=Path,required=True)
    parser.add_argument("--source-root",type=Path)
    sub=parser.add_subparsers(dest="command",required=True)
    f=sub.add_parser("forensics");f.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("prepare-f4");p.add_argument("--output",type=Path,required=True)
    p.add_argument("--dp",type=float,default=.006);p.add_argument("--q",type=float,default=.5)
    p.add_argument("--recipe",choices=["mdbc_native","dbc_three_layers"],default="mdbc_native")
    p.add_argument("--stage",choices=["canary","qualification","development"],default="canary")
    m=sub.add_parser("prepare-matrix");m.add_argument("--output",type=Path,required=True);m.add_argument("--recipe",choices=["mdbc_native","dbc_three_layers"],default="mdbc_native")
    v=sub.add_parser("validate-matrix");v.add_argument("--matrix",type=Path,required=True);v.add_argument("--output",type=Path,required=True)
    j=sub.add_parser("make-jobs");j.add_argument("--matrix",type=Path,required=True);j.add_argument("--output",type=Path,required=True)
    j=sub.add_parser("make-job");j.add_argument("--prepared",type=Path,required=True);j.add_argument("--output",type=Path,required=True)
    j.add_argument("--job-id",required=True);j.add_argument("--category",default="qualification_canary");j.add_argument("--timeout",type=int,default=1800)
    r=sub.add_parser("run");r.add_argument("--prepared",type=Path,required=True);r.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();lab=args.lab_root.resolve()
    # ``lab`` is the shared asset root.  A frozen runtime snapshot must own
    # Python helper imports so a later live edit cannot alter an active job.
    source_root=(args.source_root or Path(__file__).resolve().parents[1]).resolve()
    sys.path.insert(0,str(source_root))
    if args.command=="forensics":
        result=forensics(lab,args.output)
    elif args.command=="prepare-matrix":
        result=prepare_matrix(lab,args.output.resolve(),args.recipe)
    elif args.command=="validate-matrix":
        result=validate_prepared_matrix(args.matrix.resolve())
        write_json(args.output.resolve(),result)
    elif args.command=="make-jobs":
        result=make_qualification_jobs(args.matrix.resolve(),lab,args.output.resolve())
    elif args.command=="make-job":
        result=make_job(args.prepared.resolve(),lab,args.output.resolve(),job_id=args.job_id,
                        category=args.category,timeout_seconds=args.timeout,canary=True)
    elif args.command=="prepare-f4":
        result=prepare(f4_config(args.dp,args.q,args.recipe,args.stage),lab,args.output.resolve())
    else:
        result=run(args.prepared.resolve(),lab,args.output.resolve())
    print(json.dumps({k:result[k] for k in ("preflight_pass","native_initial","case_id","hard_integrity_pass",
                                             "static_quality_pass","job_count","qualification_claim") if k in result},indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
