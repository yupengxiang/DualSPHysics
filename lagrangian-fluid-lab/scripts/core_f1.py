#!/usr/bin/env python3
"""Core F1 reference design and bounded execution worker.

The retained ``prepare`` command and its domain-only H1 canary are kept
unchanged.  The reference path below registers one fixed single-obstacle
geometry, varies only the initial water height along one dimension, and uses
the native DBC source recipe.  It prepares cases and emits worker specs; it
never starts a GPU solver from a preparation command.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))
from scripts.core_cfd import (digest, write_json, environment, run,
                               lattice_box, mass_quality, native_frame)
from scripts.finite_wall_audit import wall_penetration, segment_crossing_events
from scripts.l2_f1r_audit import F1_WALL_SPEC, resolve_runtime_domain, apply_runtime_domain_repair
from scripts.l2_f1r_h1_canary import _canonical_without_runtime_domain


# F1 reference registration.  These values are deliberately independent of
# the F4 registration in core_cfd.py: F1 has one fixed physical obstacle and
# one scalar initial-height coordinate.
F1_SCHEMA = "core.cfd.v1"
F1_STATIC_SCHEMA = "core.cfd.static.v1"
F1_REVISION_ID = "F1_H1_obstacle_height_range_v1"
F1_SOURCE_RELATIVE = "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F1_obstacle_nominal_Def.xml"
F1_RESOLUTIONS = (0.01, 0.0075, 0.005)
F1_Q_VALUES = (0.0, 0.5, 1.0, 0.25, 0.75)
F1_HEIGHT_MIN_M = 0.40
F1_HEIGHT_MAX_M = 0.52
F1_HEIGHT_REFERENCE_M = 0.46
F1_EVENT_WINDOW_S = 2.20
F1_MAX_EVENT_WINDOW_S = 4.40
F1_OUTPUT_INTERVAL_S = 0.02
F1_NATIVE_OUTPUT_INTERVAL_S = 0.004
F1_RUNTIME_ZMAX_M = 1.8
F1_SOURCE_MASS_ERROR_MAX = 0.025
F1_TOTAL_MASS_ERROR_MAX = 0.03
F1_GRAVITY_M_S2 = 9.81


def _f1_wall_spec() -> dict:
    spec = copy.deepcopy(F1_WALL_SPEC)
    spec["runtime_domain"] = {
        "xmin": -0.30, "xmax": 1.50,
        "ymin": -0.099375, "ymax": 0.496875,
        "zmin": -0.15, "zmax": F1_RUNTIME_ZMAX_M,
    }
    return spec


def _token(value: float, places: int = 12) -> str:
    return f"{value:.{places}f}".replace("-", "m").replace(".", "p")


def f1_water_height(q: float) -> float:
    """Map the preregistered one-dimensional coordinate to initial height."""
    q = float(q)
    if not math.isfinite(q) or not 0.0 <= q <= 1.0:
        raise ValueError("F1 height coordinate q must be finite and in [0, 1]")
    return F1_HEIGHT_MIN_M + (F1_HEIGHT_MAX_M - F1_HEIGHT_MIN_M) * q


def _registered_dp(dp: float) -> float:
    value = float(dp)
    for candidate in F1_RESOLUTIONS:
        if math.isclose(value, candidate, rel_tol=0.0, abs_tol=1e-12):
            return candidate
    raise ValueError(f"F1 resolution {dp!r} is outside the registered three-cell set")


def f1_config(dp: float = 0.0075, q: float = 0.5, *, stage: str = "canary",
              design_cell: str = "spatial", temporal_variant: str | None = None) -> dict:
    """Return one immutable F1 candidate configuration.

    The tank and obstacle dimensions are fixed.  ``q`` changes only the
    initial fluid drawbox height.  The existing DBC source semantics and the
    explicit z=1.8 runtime ceiling are retained for every cell.
    """
    dp = _registered_dp(dp)
    q = float(q)
    if not math.isfinite(q) or not 0.0 <= q <= 1.0:
        raise ValueError("F1 q must be finite and in [0, 1]")
    if stage not in {"canary", "qualification"}:
        raise ValueError("F1 stage must be canary or qualification")
    if design_cell not in {"spatial", "internal_time", "native_output"}:
        raise ValueError("unknown F1 design cell")
    if design_cell == "spatial" and temporal_variant is not None:
        raise ValueError("spatial F1 cell cannot carry a temporal variant")
    if design_cell != "spatial" and temporal_variant != design_cell:
        raise ValueError("temporal F1 cell requires matching temporal_variant")
    height = f1_water_height(q)
    output_interval = F1_OUTPUT_INTERVAL_S
    cfl = 0.2
    if design_cell == "native_output":
        output_interval = F1_NATIVE_OUTPUT_INTERVAL_S
    elif design_cell == "internal_time":
        cfl = 0.1
    case_id = (
        f"CORE_F1_H1_obstacle_q{_token(q, 8)}_h{_token(height, 8)}"
        f"_dp{_token(dp)}_{stage}"
    )
    if design_cell != "spatial":
        case_id += f"_{design_cell}"
    fluid_box = {"low": [0.04, 0.04, 0.04], "size": [0.34, 0.32, height], "mkfluid": 0}
    tank = {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.6]}
    obstacle = {"id": "center_obstacle", "low": [0.68, 0.15, 0.0], "size": [0.12, 0.10, 0.34]}
    return {
        "schema": F1_SCHEMA,
        "family": "F1",
        "scope_id": "F1_single_obstacle_height_range_v1",
        "revision_id": F1_REVISION_ID,
        "case_id": case_id,
        "recipe_id": "F1_H1_native_dbc_height_v1",
        "recipe": "native_dbc",
        "stage": stage,
        "design_cell": design_cell,
        "temporal_variant": temporal_variant,
        "qualification_claim": "none",
        "qualified": False,
        "parameter": {
            "name": "initial_water_height_m",
            "q": q,
            "value": height,
            "candidate_range": [F1_HEIGHT_MIN_M, F1_HEIGHT_MAX_M],
            "mapping": "h(q)=0.40+0.12*q m",
        },
        "dp_m": dp,
        "fluid_box": fluid_box,
        "initialization_rule": {
            "name": "cell_centre_drawbox_sampling",
            "reason": (
                "retained inclusive drawbox adds edge cells at non-grid-aligned bounds; "
                "explicit cell-centre sampling keeps native representation error within the mass gate"
            ),
            "mass_rescaling": False,
            "continuum_box_preserved": True,
        },
        "continuum_geometry": {
            "tank": tank,
            "obstacle": obstacle,
            "density_kg_m3": 1000.0,
            "unchanged": True,
        },
        "gravity_m_s2": [0.0, 0.0, -F1_GRAVITY_M_S2],
        "initial_velocity_m_s": [0.0, 0.0, 0.0],
        "wall_bounds": copy.deepcopy(F1_WALL_SPEC["container_interior"]),
        "closed_faces": list(F1_WALL_SPEC["closed_faces"]),
        "open_faces": list(F1_WALL_SPEC["open_faces"]),
        "wall_spec": _f1_wall_spec(),
        "runtime_domain_zmax_m": F1_RUNTIME_ZMAX_M,
        "boundary_semantics": "native DBC source Boundary=1 default, finite DBC faces; no mDBC change",
        "source_definition": F1_SOURCE_RELATIVE,
        "cfl": cfl,
        "output_interval_s": output_interval,
        "time_max_s": F1_EVENT_WINDOW_S,
        "event_window": {
            "initial_time_max_s": F1_EVENT_WINDOW_S,
            "maximum_extended_time_max_s": F1_MAX_EVENT_WINDOW_S,
            "output_interval_s": output_interval,
            "extension_policy": "double whole scope once if return event is right-censored",
            "completion_required_for_qualification": True,
        },
        "physical_case_id": "L2_C1_F1_obstacle_nominal",
        "lineage_group_id": "L2_C1_F1_obstacle_nominal_height_range",
        "source_label_semantics": "native numerical source identity, no material qualification",
        "canary_window_reason": (
            "2.20 s covers obstacle approach, downstream split/rejoin and one gravity-time tail; "
            "4.40 s is the single preregistered right-censor extension"
        ),
    }


def _f1_signature(path: Path) -> bytes:
    """Canonicalize a definition while masking only registered dynamic fields."""
    root = ET.parse(path).getroot()
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "simulationdomain":
                parent.remove(child)
    definition = root.find(".//casedef/geometry/definition")
    if definition is None:
        raise ValueError("F1 definition has no geometry definition")
    definition.set("dp", "__registered_dp__")
    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("F1 definition has no geometry mainlist")
    fluid_seen = False
    for node in list(mainlist):
        if node.tag == "setmkfluid" and node.get("mk") == "0":
            fluid_seen = True
            continue
        if fluid_seen and node.tag == "drawbox":
            point = node.find("point")
            size = node.find("size")
            if point is None or size is None:
                raise ValueError("F1 fluid drawbox has no size")
            point.attrib.update({axis: f"__registered_fluid_{axis}__" for axis in "xyz"})
            size.attrib.update({axis: f"__registered_fluid_size_{axis}__" for axis in "xyz"})
            break
    else:
        raise ValueError("F1 fluid drawbox is missing")
    for key, marker in (("TimeMax", "__registered_time_max__"),
                        ("TimeOut", "__registered_output_interval__"),
                        ("DtIni", "__registered_dt_ini__"),
                        ("DtMin", "__registered_dt_min__"),
                        ("DtFixed", "__registered_dt_fixed__")):
        node = root.find(f".//execution/parameters/parameter[@key='{key}']")
        if node is None and key in {"TimeMax", "TimeOut"}:
            raise ValueError(f"F1 definition has no {key} parameter")
        if node is not None:
            node.set("value", marker)
    cfl = root.find(".//constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("F1 definition has no cflnumber")
    cfl.set("value", "__registered_cfl__")
    for node in root.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    return ET.tostring(root, encoding="utf-8")


def _set_parameter(root: ET.Element, key: str, value: float | str) -> None:
    parameters = root.find(".//execution/parameters")
    if parameters is None:
        raise ValueError("F1 definition has no execution parameters")
    node = parameters.find(f"parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(parameters, "parameter", {"key": key})
    node.set("value", str(value))


def reference_definition(config: dict, template: Path, target: Path) -> dict:
    """Materialize one F1 height cell and audit the permitted XML changes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    apply_runtime_domain_repair(template, target, zmax=F1_RUNTIME_ZMAX_M)
    tree = ET.parse(target)
    root = tree.getroot()
    dp = float(config["dp_m"])
    fluid_height = float(config["parameter"]["value"])
    definition = root.find(".//casedef/geometry/definition")
    if definition is None:
        raise ValueError("F1 definition has no geometry definition")
    definition.set("dp", f"{dp:.17g}")
    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise ValueError("F1 definition has no geometry mainlist")
    fluid_seen = False
    fluid_drawbox = None
    for node in list(mainlist):
        if node.tag == "setmkfluid" and node.get("mk") == "0":
            fluid_seen = True
        elif fluid_seen and node.tag == "drawbox":
            fluid_drawbox = node
            break
    if fluid_drawbox is None:
        raise ValueError("F1 fluid drawbox is missing")
    point = fluid_drawbox.find("point")
    size = fluid_drawbox.find("size")
    if point is None or size is None:
        raise ValueError("F1 fluid drawbox is incomplete")
    native_box = _f1_native_box(config["fluid_box"]["low"], config["fluid_box"]["size"], dp)
    point.attrib.update({axis: f"{native_box['first_center_m'][index]:.17g}"
                         for index, axis in enumerate("xyz")})
    size.attrib.update({axis: f"{native_box['draw_size_m'][index]:.17g}"
                        for index, axis in enumerate("xyz")})
    _set_parameter(root, "TimeMax", f"{float(config['time_max_s']):.17g}")
    _set_parameter(root, "TimeOut", f"{float(config['output_interval_s']):.17g}")
    cfl = root.find(".//constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("F1 definition has no cflnumber")
    cfl.set("value", f"{float(config['cfl']):.17g}")
    time_control = config.get("time_control", {})
    for key in ("DtIni", "DtMin", "DtFixed"):
        if key in time_control:
            _set_parameter(root, key, f"{float(time_control[key]):.17g}")
    ET.indent(tree, space="    ")
    tree.write(target, encoding="utf-8", xml_declaration=True)
    if _f1_signature(template) != _f1_signature(target):
        raise ValueError("F1 candidate changed an unregistered physical/numerical field")
    return {
        "source_template": str(template.resolve()),
        "source_template_sha256": digest(template),
        "definition_sha256": digest(target),
        "allowed_changes": [
            "simulationdomain: materialized explicit runtime domain with zmax=1.8 m",
            "geometry.definition.dp: registered spatial resolution",
            "fluid initial drawbox point/size: registered cell-centre sampling of the declared water box",
            "fluid initial drawbox size.z: registered initial water height",
            "execution.parameters.TimeMax: registered 2.2 s window",
            "execution.parameters.TimeOut: registered native output cadence",
            "constantsdef.cflnumber: 0.2, or 0.1 for internal-time cell",
            "execution.parameters.DtIni/DtMin: explicit base or half-step temporal study control",
        ],
        "continuum_geometry_unchanged": True,
        "physical_geometry_unchanged": True,
        "boundary_semantics_unchanged": True,
        "mass_rescaling": False,
    }


def _f1_sampling(config: dict) -> dict:
    box = _f1_native_box(config["fluid_box"]["low"], config["fluid_box"]["size"], config["dp_m"])
    box["mkfluid"] = 0
    return {
        "fluid_boxes": [box],
        "expected_fluid_particles": int(box["particle_count"]),
        "continuous_mass_kg": float(box["continuous_mass_kg"]),
        "sampled_mass_kg": float(box["discrete_mass_kg"]),
        "mass_policy": "native rho*dp^3, no mass rescaling; cell-centre volume error is gated",
    }


def _f1_native_box(low: list[float], size: list[float], dp: float) -> dict:
    """Declare the cell-centre drawbox used by GenCase for the F1 fluid.

    The source drawbox is a continuous box.  GenCase's inclusive drawbox
    semantics add edge cells when its low corner is not on the cell-centre
    lattice.  F1 therefore materializes the declared box at cell centres and
    gates the resulting native volume; this records the initialization rule
    and never changes ``rho*dp**3`` or rescales particle mass.
    """
    low = [float(value) for value in low]
    size = [float(value) for value in size]
    dp = float(dp)
    first = [math.ceil(value / dp - 1e-10) for value in low]
    # Horizontal dimensions use the smallest enclosing centre lattice.  The
    # vertical span is kept inside the declared water height, so the top
    # never exceeds the registered continuous initial condition.
    counts = [
        math.ceil(size[0] / dp - 1e-10),
        math.ceil(size[1] / dp - 1e-10),
        math.floor(size[2] / dp + 1e-10),
    ]
    if any(count <= 0 for count in counts):
        raise ValueError("F1 fluid box is unresolved by the registered lattice")
    first_center = [(index * dp) for index in first]
    draw_size = [(count - 1) * dp for count in counts]
    discrete_mass = float(math.prod(counts) * dp ** 3 * 1000.0)
    continuous_mass = float(math.prod(size) * 1000.0)
    return {
        "continuous_low_m": low,
        "continuous_size_m": size,
        "first_center_m": first_center,
        "draw_size_m": draw_size,
        "counts": counts,
        "particle_count": int(math.prod(counts)),
        "continuous_mass_kg": continuous_mass,
        "discrete_mass_kg": discrete_mass,
        "native_cell_centre_sampling": True,
    }


def _f1_mass_quality(sampling: dict) -> dict:
    # core_cfd.mass_quality is the shared native rho*dp^3 representation gate.
    report = mass_quality(sampling)
    report["source_error_max"] = F1_SOURCE_MASS_ERROR_MAX
    report["total_error_max"] = F1_TOTAL_MASS_ERROR_MAX
    report["pass"] = bool(
        report["max_abs_source_relative_error"] <= F1_SOURCE_MASS_ERROR_MAX
        and abs(report["total_relative_error"]) <= F1_TOTAL_MASS_ERROR_MAX
    )
    report["mass_gate_pass"] = report["pass"]
    report["mass_rescaling"] = False
    return report


def qualification_design() -> dict:
    """Return the frozen 13 spatial + 2 temporal F1 registration."""
    cells = []
    for q in (0.0, 0.5, 1.0):
        for dp in F1_RESOLUTIONS:
            cfg = f1_config(dp, q, stage="qualification")
            cfg["design_cell"] = "spatial"
            cells.append(cfg)
    for q in (0.25, 0.75):
        for dp in F1_RESOLUTIONS[1:]:
            cfg = f1_config(dp, q, stage="qualification")
            cfg["design_cell"] = "spatial"
            cells.append(cfg)
    for variant in ("internal_time", "native_output"):
        cfg = f1_config(0.0075, 0.5, stage="qualification",
                        design_cell=variant, temporal_variant=variant)
        cells.append(cfg)
    static_rows = []
    for index, cfg in enumerate(cells):
        sampling = _f1_sampling(cfg)
        mass = _f1_mass_quality(sampling)
        static_rows.append({
            "index": index,
            "case_id": cfg["case_id"],
            "q": cfg["parameter"]["q"],
            "water_height_m": cfg["parameter"]["value"],
            "dp_m": cfg["dp_m"],
            "design_cell": cfg["design_cell"],
            "particle_count": sampling["expected_fluid_particles"],
            "source_mass_relative_error": mass["source_relative_errors"][0],
            "total_mass_relative_error": mass["total_relative_error"],
            "mass_gate_pass": bool(mass["mass_gate_pass"]),
        })
    return {
        "schema": F1_STATIC_SCHEMA,
        "revision_id": F1_REVISION_ID,
        "scope_id": "F1_single_obstacle_height_range_v1",
        "qualification_claim": "none",
        "created_at": "2026-09-19T00:00:00+00:00",
        "candidate_status": "pre_registered_unqualified",
        "fixed_geometry": {
            "source_definition": F1_SOURCE_RELATIVE,
            "tank": {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.6]},
            "obstacle": {"id": "center_obstacle", "low": [0.68, 0.15, 0.0], "size": [0.12, 0.10, 0.34]},
            "initial_fluid_xy_m": {"low": [0.04, 0.04], "size": [0.34, 0.32]},
            "initialization_rule": "cell-centre drawbox sampling of the declared box; native rho*dp^3 mass",
            "density_kg_m3": 1000.0,
            "gravity_m_s2": -9.81,
            "boundary_semantics": "native DBC source default Boundary=1",
            "runtime_domain_zmax_m": F1_RUNTIME_ZMAX_M,
        },
        "one_dimensional_parameter": {
            "name": "initial_water_height_m",
            "coordinate": "q in [0,1]",
            "mapping": "h(q)=0.40+0.12*q m",
            "q_values": list(F1_Q_VALUES),
            "height_values_m": [f1_water_height(q) for q in F1_Q_VALUES],
            "range_m": [F1_HEIGHT_MIN_M, F1_HEIGHT_MAX_M],
        },
        "resolutions_m": list(F1_RESOLUTIONS),
        "cells": cells,
        "cell_count": len(cells),
        "registered_window": {
            "initial_time_max_s": F1_EVENT_WINDOW_S,
            "output_interval_s": F1_OUTPUT_INTERVAL_S,
            "maximum_extended_time_max_s": F1_MAX_EVENT_WINDOW_S,
            "extension_policy": "one whole-scope doubling only when return is right-censored",
            "event_completion_required": True,
        },
        "hypotheses": [
            {
                "id": "H1_fixed_native_dbc_height",
                "scope": "fixed obstacle/tank and native DBC recipe; only initial height and registered dp/cadence vary",
                "falsifier": "closed-wall or obstacle penetration, missing IDs, or nonfinite trajectory",
                "attempt_limit": 1,
            },
            {
                "id": "H2_conditional_mdbc_boundary_variant",
                "scope": "conditional boundary diagnostic only if H1 has boundary-specific failure evidence; not activated in this card",
                "falsifier": "same failure after a documented matched boundary substitution",
                "attempt_limit": 1,
                "activation": "requires post-canary root-cause evidence",
            },
        ],
        "mass_policy": "native rho*dp^3; no mass rescaling; source representation gate <=2.5%, total <=3.0%",
        "preregistered_gates": {
            "no_missing_native_fluid_ids": True,
            "no_nonfinite_active_values": True,
            "closed_wall_endpoint_tolerance_m": 1e-8,
            "saved_chord_crossings_allowed": 0,
            "source_initial_mass_relative_error_max": F1_SOURCE_MASS_ERROR_MAX,
            "initial_mass_spread_over_continuous_mass_max": F1_TOTAL_MASS_ERROR_MAX,
            "mass_change_relative_max": 1e-8,
            "event_completion_required": True,
            "qualification_requires_all_cells": True,
        },
        "static_mass_check": {
            "pass": bool(all(row["mass_gate_pass"] for row in static_rows)),
            "cell_count": len(static_rows),
            "rows": static_rows,
            "mass_rescaling": False,
        },
    }


def write_candidate_card(output: Path) -> dict:
    card = qualification_design()
    write_json(Path(output), card)
    return card


def prepare_reference(config: dict, lab: Path, output: Path) -> dict:
    """CPU-only GenCase/native initialization preparation for one F1 cell."""
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("F1 reference preparation output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    template = lab / F1_SOURCE_RELATIVE
    if not template.is_file():
        raise FileNotFoundError(template)
    target = output / (config["case_id"] + "_Def.xml")
    geometry_audit = reference_definition(config, template, target)
    sampling = _f1_sampling(config)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / config["case_id"]
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(target.with_suffix("")),
               str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=environment(lab),
                                 stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError("GenCase failed; inspect " + str(output / "gencase.log"))
    generated_xml = prefix.with_suffix(".xml")
    generated = ET.parse(generated_xml).getroot()
    blocks = generated.findall(".//particles/fluid")
    if len(blocks) != 1:
        raise ValueError(f"F1 reference expected one fluid source block, got {len(blocks)}")
    generated_count = int(blocks[0].get("count"))
    if generated_count != sampling["expected_fluid_particles"]:
        raise ValueError(
            f"GenCase lattice differs from declaration: {generated_count} != "
            f"{sampling['expected_fluid_particles']}"
        )
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    mass = _f1_mass_quality(sampling)
    with tempfile.TemporaryDirectory(prefix="core-f1-initial-") as folder:
        ids, pos, vel, rho, meta, info, arrays = native_frame(
            prefix.with_suffix(".bi4"), Path(folder) / "native", decoder
        )
        finite = all(np.isfinite(array).all() for array in (pos, vel, rho))
        unique = len(np.unique(ids)) == len(ids)
        fluid_count = int(meta.get("CaseNfluid", generated_count))
        boundary_count = int(meta.get("CaseNfixed", 0))
        native = {
            "total_particles": int(len(ids)),
            "boundary_particles": boundary_count,
            "fluid_particles": fluid_count,
            "generated_fluid_particles": generated_count,
            "unique_ids": unique,
            "finite_initial_arrays": bool(finite),
            "native_initial_mass_kg": float(meta.get("MassFluid", 0.0)) * fluid_count,
            "native_initial_time_s": float(info.get("TimeStep", 0.0)),
            "normal_file_present": (arrays / "BoundNor.bin").is_file(),
        }
    native["initial_state_pass"] = bool(
        native["unique_ids"] and native["finite_initial_arrays"]
        and native["fluid_particles"] == sampling["expected_fluid_particles"]
    )
    resolved_domain = resolve_runtime_domain(generated_xml)
    if resolved_domain is None or not math.isclose(resolved_domain["zmax"], F1_RUNTIME_ZMAX_M, abs_tol=1e-9):
        raise ValueError("generated F1 runtime domain does not resolve to zmax=1.8 m")
    inputs = {str(path.resolve()): digest(path) for path in output.rglob("*") if path.is_file()}
    prepared = {
        "schema": F1_SCHEMA,
        "created_at": "2026-09-19T00:00:00+00:00",
        "config": config,
        "sampling": sampling,
        "mass_preflight": mass,
        "native_initial": native,
        "preflight_pass": bool(native["initial_state_pass"] and mass["mass_gate_pass"]),
        "generated_prefix": str(prefix.resolve()),
        "source_template": str(template.resolve()),
        "source_template_sha256": digest(template),
        "definition_audit": geometry_audit,
        "resolved_runtime_domain": resolved_domain,
        "inputs": inputs,
        "solver_binary": str(binaries / "DualSPHysics5.4_linux64"),
        "solver_sha256": digest(binaries / "DualSPHysics5.4_linux64"),
        "decoder": str(decoder),
        "decoder_sha256": digest(decoder),
        "solver_arguments": [],
        "qualification_claim": "none; one F1 canary preparation, not range or qualification evidence",
    }
    write_json(output / "prepared.json", prepared)
    return prepared


def validate_reference_prepared(prepared_path: Path) -> dict:
    prepared_path = Path(prepared_path).resolve()
    prepared = json.loads(prepared_path.read_text())
    config = prepared.get("config", {})
    issues = []
    if prepared.get("schema") != F1_SCHEMA or config.get("family") != "F1":
        issues.append("F1 schema/family mismatch")
    if config.get("recipe") != "native_dbc":
        issues.append("reference case is not the registered native DBC recipe")
    if config.get("qualification_claim") != "none" or prepared.get("qualification_claim", "").startswith("none") is False:
        issues.append("qualification claim is not explicitly none")
    if not math.isclose(float(config.get("time_max_s", -1)), F1_EVENT_WINDOW_S, abs_tol=1e-9):
        issues.append("initial event window is not 2.20 s")
    if not math.isclose(float(config.get("runtime_domain_zmax_m", -1)), F1_RUNTIME_ZMAX_M, abs_tol=1e-9):
        issues.append("runtime z ceiling is not 1.8 m")
    if config.get("continuum_geometry", {}).get("unchanged") is not True:
        issues.append("continuum geometry is not marked unchanged")
    if config.get("boundary_semantics", "").find("DBC") < 0:
        issues.append("DBC boundary semantics are missing")
    sampling = prepared.get("sampling", {})
    try:
        mass = _f1_mass_quality(sampling)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        mass = {"mass_gate_pass": False, "error": repr(error), "source_relative_errors": []}
        issues.append("mass declaration is incomplete")
    if not mass.get("mass_gate_pass"):
        issues.append("static native mass representation gate failed")
    native = prepared.get("native_initial", {})
    if not prepared.get("preflight_pass") or not native.get("initial_state_pass"):
        issues.append("native static initial-state preflight failed")
    expected = sampling.get("expected_fluid_particles")
    if native.get("fluid_particles") != expected:
        issues.append("native fluid count differs from static declaration")
    passed = not issues
    return {
        "schema": F1_STATIC_SCHEMA,
        "revision_id": F1_REVISION_ID,
        "prepared": str(prepared_path),
        "case_id": config.get("case_id"),
        "static_quality_pass": passed,
        "preflight_pass": passed,
        "continuum_geometry_unchanged": True,
        "mass_rescaling": False,
        "mass_preflight": mass,
        "event_window_s": config.get("time_max_s"),
        "maximum_extended_window_s": config.get("event_window", {}).get("maximum_extended_time_max_s"),
        "qualification_claim": "none",
        "issues": issues,
    }


def _f1_resource_estimate(dp: float) -> dict:
    if dp <= 0.005 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib": 6144, "io_weight": 1}
    if dp <= 0.0075 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 1}
    return {"cpu_cores": 2, "ram_mib": 12288, "gpu_peak_mib": 3072, "io_weight": 1}


def make_reference_job(prepared_path: Path, lab: Path, output: Path, *, job_id: str,
                       category: str = "reference_canary", timeout_seconds: int = 3600) -> dict:
    prepared_path = Path(prepared_path).resolve()
    lab = Path(lab).resolve()
    prepared = json.loads(prepared_path.read_text())
    validation = validate_reference_prepared(prepared_path)
    if not validation["static_quality_pass"]:
        raise ValueError("F1 prepared static validation failed; no job written")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    spec = {
        "schema": "core.cfd.job.v1",
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "initial",
        "category": category,
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [
            str(lab / ".venv/bin/python"),
            str(lab / "scripts/core_f1.py"),
            "--lab-root", str(lab),
            "run",
            "--prepared", str(prepared_path),
            "--output", "{attempt_dir}/product",
        ],
        "required_outputs": [
            "product/result.json",
            "product/trajectory.h5",
            "product/audit.json",
            "product/observations.json",
        ],
        "resources": _f1_resource_estimate(float(prepared["config"]["dp_m"])),
        "timeout_seconds": int(timeout_seconds),
        "depends_on": [],
        "qualification_claim": "none",
        "input_files": [
            {"path": str(prepared_path), "sha256": digest(prepared_path)},
            {"path": str(solver), "sha256": digest(solver)},
            {"path": str(decoder), "sha256": digest(decoder)},
        ],
        "prepared_case_id": prepared["config"]["case_id"],
        "registered_window_s": prepared["config"]["time_max_s"],
        "maximum_extended_window_s": prepared["config"]["event_window"]["maximum_extended_time_max_s"],
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
        "static_validation": validation,
    }
    write_json(Path(output), spec)
    return spec


def _f1_observations(prepared: dict, hdf5_path: Path) -> dict:
    """Compute fixed-geometry event diagnostics from normalized native frames."""
    cfg = prepared["config"]
    obstacle = cfg["continuum_geometry"]["obstacle"]
    dp = float(cfg["dp_m"])
    continuous_mass = float(prepared["sampling"]["fluid_boxes"][0]["continuous_mass_kg"])
    gravity_time = math.sqrt(1.2 / F1_GRAVITY_M_S2)
    times, rows = [], []
    with h5py.File(hdf5_path, "r") as h:
        for frame, time_s in enumerate(h["time"][:]):
            valid = h["valid"][frame].astype(bool)
            pos = h["position"][frame]
            vel = h["velocity"][frame]
            mass = h["mass"][frame].astype(np.float64)
            active = valid & np.isfinite(pos).all(axis=1) & np.isfinite(vel).all(axis=1) & np.isfinite(mass)
            if not active.any():
                continue
            p, v, m = pos[active], vel[active], mass[active]
            total = max(float(m.sum()), 1e-30)
            com = (m[:, None] * p).sum(axis=0) / total
            corridor = (
                (p[:, 0] >= obstacle["low"][0] - 2 * dp)
                & (p[:, 0] <= obstacle["low"][0] + obstacle["size"][0] + 2 * dp)
                & (p[:, 1] >= obstacle["low"][1] - 2 * dp)
                & (p[:, 1] <= obstacle["low"][1] + obstacle["size"][1] + 2 * dp)
                & (p[:, 2] >= obstacle["low"][2] + obstacle["size"][2] - 2 * dp)
            )
            downstream = p[:, 0] >= obstacle["low"][0] + obstacle["size"][0] + 2 * dp
            rows.append({
                "time_s": float(time_s),
                "active_mass_kg": total,
                "active_mass_fraction_of_continuum": total / max(continuous_mass, 1e-30),
                "center_of_mass_m": com.tolist(),
                "center_of_mass_normalized": (com / np.asarray([1.2, 0.4, 0.6])).tolist(),
                "approach_corridor_mass_fraction": float(m[corridor].sum() / total),
                "downstream_mass_fraction": float(m[downstream].sum() / total),
                "max_x_m": float(p[:, 0].max()),
                "max_z_m": float(p[:, 2].max()),
            })
            times.append(float(time_s))
    if not rows:
        return {"schema": "core.f1.observations.v1", "event_window_complete": False,
                "event_window_status": "no_active_frames", "time_s": [], "rows": []}
    time_axis = np.asarray(times, dtype=float)
    approach = np.asarray([row["approach_corridor_mass_fraction"] for row in rows]) >= .01
    downstream = np.asarray([row["downstream_mass_fraction"] for row in rows]) >= .05
    approach_indices = np.flatnonzero(approach)
    downstream_indices = np.flatnonzero(downstream)
    return_index = None
    if len(downstream_indices):
        start = int(downstream_indices[0])
        peak = max(row["center_of_mass_m"][0] for row in rows[start:])
        for index in range(start + 1, len(rows)):
            if time_axis[index] > time_axis[start] + .1 and rows[index]["center_of_mass_m"][0] <= peak - max(.02, 2 * dp):
                return_index = index
                break
    horizon_reached = bool(time_axis[-1] >= float(cfg["time_max_s"]) - 1e-6)
    return_observed = return_index is not None
    tail_after_return = bool(return_observed and time_axis[-1] - time_axis[return_index] >= gravity_time)
    event_complete = bool(horizon_reached and return_observed and tail_after_return)
    status = "complete" if event_complete else (
        "right_censored_requires_single_doubling" if horizon_reached else "horizon_not_reached"
    )
    return {
        "schema": "core.f1.observations.v1",
        "case_id": cfg["case_id"],
        "time_s": times,
        "rows": rows,
        "event_detector": {
            "approach": ">=1% active mass within 2dp of obstacle horizontal footprint at/above obstacle top",
            "downstream": ">=5% active mass beyond obstacle xmax+2dp",
            "return": "COM x decreases >=max(0.02m,2dp) after downstream and 0.1s separation",
            "completion": "horizon reached, return observed, and one gravity-time tail",
        },
        "event_times_s": {
            "approach": None if not len(approach_indices) else float(time_axis[approach_indices[0]]),
            "downstream": None if not len(downstream_indices) else float(time_axis[downstream_indices[0]]),
            "return": None if return_index is None else float(time_axis[return_index]),
        },
        "gravity_time_s": gravity_time,
        "event_window_complete": event_complete,
        "event_window_status": status,
        "requested_horizon_reached": horizon_reached,
        "maximum_extended_time_max_s": F1_MAX_EVENT_WINDOW_S,
        "source_initial_mass_relative_errors": list(prepared["mass_preflight"]["source_relative_errors"]),
        "source_mass_gate_pass": bool(prepared["mass_preflight"]["mass_gate_pass"]),
        "qualification_claim": "none; fixed-geometry event diagnostics only",
    }


def execute_reference(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared = json.loads(Path(prepared_path).read_text())
    result = run(Path(prepared_path), Path(lab), Path(output))
    spec = prepared["config"]["wall_spec"]
    obstacle_frames = 0
    obstacle_mass = 0.0
    chord_crossings = 0
    wall_endpoint_frames = 0
    with h5py.File(Path(output) / "trajectory.h5", "r") as h:
        previous = None
        for frame in range(len(h["time"])):
            valid = h["valid"][frame].astype(bool)
            pos = h["position"][frame]
            mass = h["mass"][frame]
            check = wall_penetration(pos[valid], mass[valid], spec, tolerance=1e-8)
            obstacle_frames += int(check["obstacle_penetration_count"])
            obstacle_mass += float(check["obstacle_penetration_mass_kg"])
            wall_endpoint_frames += int(check["outside_closed_container_count"])
            if previous is not None:
                previous_pos, previous_valid = previous
                common = previous_valid & valid
                chord_crossings += len(segment_crossing_events(
                    previous_pos[common], pos[common], spec, 1e-8
                ))
            previous = pos, valid
    observations = _f1_observations(prepared, Path(output) / "trajectory.h5")
    result.update({
        "obstacle_penetration_particle_frames": obstacle_frames,
        "obstacle_penetration_mass_kg": obstacle_mass,
        "closed_wall_endpoint_particle_frames": wall_endpoint_frames,
        "finite_geometry_chord_crossings": chord_crossings,
        "event_window_complete": observations["event_window_complete"],
        "event_window_status": observations["event_window_status"],
        "requested_horizon_reached": observations.get("requested_horizon_reached", False),
        "qualified": False,
        "qualification_claim": "none; one F1 full-window canary, not range or qualification evidence",
    })
    result["hard_integrity_pass"] = bool(
        result.get("hard_integrity_pass") and obstacle_frames == 0
        and wall_endpoint_frames == 0 and chord_crossings == 0
    )
    write_json(Path(output) / "observations.json", observations)
    write_json(Path(output) / "audit.json", result)
    write_json(Path(output) / "result.json", result)
    return result


def prepare(lab, output):
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("fresh preparation directory required")
    output.mkdir(parents=True, exist_ok=True)
    source = lab / "campaigns/l2-multifamily/c1-canary/cases/L2_C1_F1_obstacle_nominal_Def.xml"
    case_id = "CORE_F1_H1_domain_z1p8_canary"
    definition = output / (case_id + "_Def.xml")
    apply_runtime_domain_repair(source, definition, zmax=1.8)
    if _canonical_without_runtime_domain(source) != _canonical_without_runtime_domain(definition):
        raise ValueError("domain-only hypothesis changed physical/numerical inputs")
    prefix = output / "generated" / case_id
    prefix.parent.mkdir()
    binary = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    with (output / "gencase.log").open("w") as log:
        subprocess.run([str(binary / "GenCase_linux64"), str(definition.with_suffix("")), str(prefix), "-save:all"],
                       check=True, cwd=output, env=environment(lab), stdout=log, stderr=subprocess.STDOUT)
    domain = resolve_runtime_domain(prefix.with_suffix(".xml"))
    if abs(domain["zmax"] - 1.8) > 1e-9:
        raise ValueError("generated domain differs from requested domain")
    generated = ET.parse(prefix.with_suffix(".xml")).getroot()
    block = generated.find(".//particles/fluid")
    config = {"case_id": case_id, "family": "F1", "scope_id": "F1_retained_obstacle_domain_canary",
              "recipe_id": "F1_legacy_H1_domain_z1p8", "stage": "canary", "time_max_s": .6,
              "wall_bounds": F1_WALL_SPEC["container_interior"], "wall_spec": F1_WALL_SPEC,
              "physical_case_id": "L2_C1_F1_obstacle_nominal", "lineage_group_id": "L2_C1_F1_obstacle_nominal",
              "source_label_semantics": "native numerical source identity, no material qualification"}
    prepared = {"schema": "core.cfd.v1", "config": config, "preflight_pass": True,
                "generated_prefix": str(prefix), "inputs": {str(p): digest(p) for p in output.rglob("*") if p.is_file()},
                "solver_binary": str(binary / "DualSPHysics5.4_linux64"), "solver_sha256": digest(binary / "DualSPHysics5.4_linux64"),
                "decoder": str(lab / "campaigns/l1-resume/artifacts/bi4_dump"),
                "decoder_sha256": digest(lab / "campaigns/l1-resume/artifacts/bi4_dump"),
                "solver_arguments": [], "native_initial": {"fluid_particles": int(block.attrib["count"])},
                "hypothesis": "Retained H1 single missing particle crossed runtime z=1.35 at .600028s with finite speed .4326m/s; increase only runtime ceiling to1.8m.",
                "resolved_runtime_domain": domain, "same_non_domain_recipe": True,
                "qualification_claim": "none; same-physics diagnostic continuation, not a new independent case"}
    write_json(output / "prepared.json", prepared)
    return prepared


def execute(prepared_path, lab, output):
    prepared = json.loads(Path(prepared_path).read_text())
    result = run(Path(prepared_path), Path(lab), Path(output))
    spec = prepared["config"]["wall_spec"]
    obstacle_frames = chord_crossings = 0
    with h5py.File(Path(output) / "trajectory.h5", "r") as h:
        previous = None
        for fi in range(len(h["time"])):
            valid = h["valid"][fi].astype(bool)
            pos = h["position"][fi]
            mass = h["mass"][fi]
            check = wall_penetration(pos[valid], mass[valid], spec, tolerance=1e-8)
            obstacle_frames += check["obstacle_penetration_count"]
            if previous is not None:
                common = previous[1] & valid
                chord_crossings += len(segment_crossing_events(previous[0][common], pos[common], spec, 1e-8))
            previous = pos, valid
    result.update(obstacle_penetration_particle_frames=obstacle_frames, finite_geometry_chord_crossings=chord_crossings)
    result["hard_integrity_pass"] &= not obstacle_frames and not chord_crossings
    result["qualification_claim"] = "none; domain-only canary, finite obstacle audit included"
    write_json(Path(output) / "audit.json", result)
    write_json(Path(output) / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("write-design")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("prepare-reference")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dp", type=float, default=0.0075)
    p.add_argument("--q", type=float, default=0.5)
    p.add_argument("--stage", choices=["canary", "qualification"], default="canary")
    p.add_argument("--design-cell", choices=["spatial", "internal_time", "native_output"], default="spatial")
    p.add_argument("--temporal-variant", choices=["internal_time", "native_output"])
    p = commands.add_parser("validate-reference")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-reference-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--category", default="reference_canary")
    p.add_argument("--timeout", type=int, default=3600)
    p = commands.add_parser("run")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.lab_root, args.output)
    elif args.command == "write-design":
        result = write_candidate_card(args.output)
    elif args.command == "prepare-reference":
        config = f1_config(args.dp, args.q, stage=args.stage,
                           design_cell=args.design_cell,
                           temporal_variant=args.temporal_variant)
        result = prepare_reference(config, args.lab_root, args.output)
    elif args.command == "validate-reference":
        result = validate_reference_prepared(args.prepared)
        write_json(args.output, result)
    elif args.command == "make-reference-job":
        result = make_reference_job(args.prepared, args.lab_root, args.output,
                                    job_id=args.job_id, category=args.category,
                                    timeout_seconds=args.timeout)
    else:
        prepared = json.loads(args.prepared.read_text())
        if prepared.get("config", {}).get("scope_id") == "F1_single_obstacle_height_range_v1":
            result = execute_reference(args.prepared, args.lab_root, args.output)
        else:
            result = execute(args.prepared, args.lab_root, args.output)
    print(json.dumps({k: result[k] for k in ("preflight_pass", "hard_integrity_pass", "qualification_claim",
                                             "static_quality_pass", "job_count", "cell_count") if k in result},
                     indent=2))


if __name__ == "__main__":
    main()
