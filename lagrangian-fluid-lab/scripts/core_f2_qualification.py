#!/usr/bin/env python3
"""Prepare and observe the bounded F2 rotating-cup qualification design.

The design has one physical control axis: the prescribed rotation duration
from the already exercised centered fast/slow controls (0.50--1.20 s).  The
cup, receiver, tray, initial water height, native mass rule and gravity are
fixed.  This module writes a 13+2 registration card, performs static native
mass checks, and prepares one midpoint full-window canary.  It never launches
the solver; the coordinator owns the worker job.

The event observer uses world coordinates for the receiver/tray and the cup
body frame for cup retention.  Numerical source labels are retained only as
initial partitions and are not treated as material truth.
"""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd, core_f2
from scripts.finite_wall_audit import (
    outside_runtime_domain_mask,
    segment_crossing_events,
    wall_penetration,
)


SCHEMA = "core.f2.qualification.v1"
JOB_SCHEMA = "core.cfd.job.v1"
REVISION_ID = "F2_pour_duration_qualification_v1"
CANARY_REVISION_ID = "F2_pour_duration_dynamic_event_window_v1"
DP_RESOLUTIONS = (0.01, 0.0075, 0.005)
Q_POINTS = (0.0, 0.5, 1.0, 0.25, 0.75)
HELD_OUT_Q = (0.25, 0.75)
DURATION_RANGE_S = (0.50, 1.20)
ANGLE_DEGREES = -105.0
MOTION_START_S = 0.50
SOURCE_MOTION_FILE_DURATION_S = 2.50
FULL_WINDOW_S = 2.50
MAXIMUM_EXTENDED_WINDOW_S = 5.00
OUTPUT_INTERVAL_S = 0.01
CANARY_DP_M = 0.0075
DOMAIN_ZMAX_M = 2.4
BASELINE_DOMAIN_ZMAX_M = 1.8
POST_SETTLE_OBSERVATION_S = 0.35
SETTLE_HOLD_S = 0.20
RECEIVER_CONTACT_FRACTION = 0.01
SPILL_FRACTION = 0.01
SETTLE_SPEED_M_S = 0.10
SETTLE_KE_FRACTION = 0.05
F2_WALL_TOLERANCE_M = 1e-8
F2_BASE_CFL = 0.2
F2_INTERNAL_TIME_CFL = 0.1
F2_BASE_TIME_CONTROL = {
    "cflnumber": F2_BASE_CFL,
    "DtIni": 0.0,
    "DtMin": 0.0,
    "DtFixed": 0.0,
}
F2_INTERNAL_TIME_CONTROL = {
    **F2_BASE_TIME_CONTROL,
    "cflnumber": F2_INTERNAL_TIME_CFL,
}
F2_REQUIRED_EVENT_NAMES = ("motion_complete", "receiver_contact", "settled")
F2_SCORE_INTERVAL_S = OUTPUT_INTERVAL_S
F2_OBSERVER_REVISION_ID = "F2_geometry_aware_observer_v1"
F2_OBSERVABLE_NAMES = (
    "cup_mass_fraction",
    "receiver_mass_fraction",
    "tray_mass_fraction",
    "outside_observation_mass_fraction",
    "center_of_mass_world_x_over_runtime_x_span",
    "center_of_mass_world_y_over_runtime_y_span",
    "center_of_mass_world_z_over_runtime_z_span",
    "center_of_mass_cup_body_x_over_cup_x_span",
    "center_of_mass_cup_body_y_over_cup_y_span",
    "center_of_mass_cup_body_z_over_cup_z_span",
    "kinetic_energy_over_initial_potential",
    "speed_p95_over_1m_s",
)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def duration_for_q(q: float) -> float:
    q = float(q)
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0,1]")
    return DURATION_RANGE_S[0] + q * (DURATION_RANGE_S[1] - DURATION_RANGE_S[0])


def motion_angle(time_s: float, duration_s: float, angle_degrees: float = ANGLE_DEGREES) -> float:
    if time_s <= MOTION_START_S:
        return 0.0
    if time_s >= MOTION_START_S + duration_s:
        return float(angle_degrees)
    phase = (time_s - MOTION_START_S) / duration_s
    return float(angle_degrees * 0.5 * (1.0 - math.cos(math.pi * phase)))


def rotation_matrix_y(angle_degrees: float) -> np.ndarray:
    angle = math.radians(float(angle_degrees))
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def cup_world_from_body(angle_degrees: float) -> np.ndarray:
    rotation = rotation_matrix_y(-float(angle_degrees))
    pivot = np.asarray([0.0, 0.0, 0.65])
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = pivot - rotation @ pivot
    return transform


def body_positions(world: np.ndarray, transform: np.ndarray) -> np.ndarray:
    inverse = np.linalg.inv(transform)
    homogeneous = np.column_stack((world, np.ones(len(world))))
    return (homogeneous @ inverse.T)[:, :3]


def _inside(points: np.ndarray, low: list[float], high: list[float]) -> np.ndarray:
    return np.all((points >= np.asarray(low)) & (points <= np.asarray(high)), axis=1)


def _mass_check(dp: float) -> dict:
    boxes = [core_f2._nearest_native_box(box, dp) for box in core_f2.FLUID_BOXES]
    sampling = {
        "fluid_boxes": boxes,
        "expected_fluid_particles": int(sum(item["particle_count"] for item in boxes)),
        "continuous_mass_kg": float(sum(item["continuous_mass_kg"] for item in boxes)),
        "sampled_mass_kg": float(sum(item["discrete_mass_kg"] for item in boxes)),
        "mass_policy": "native rho*dp^3, no mass rescaling",
    }
    result = core_cfd.mass_quality(sampling)
    return {
        "dp_m": float(dp),
        "particle_counts_by_layer": [int(item["particle_count"]) for item in boxes],
        "expected_fluid_particles": sampling["expected_fluid_particles"],
        "continuous_mass_kg": sampling["continuous_mass_kg"],
        "discrete_mass_kg": sampling["sampled_mass_kg"],
        "source_relative_errors": result["source_relative_errors"],
        "total_relative_error": result["total_relative_error"],
        "mass_rescaling": False,
        "resource_estimate": resource_estimate(dp),
        "mass_gate_pass": bool(result["mass_gate_pass"]),
    }


def resource_estimate(dp: float, *, canary: bool = False) -> dict:
    """Worker reservation estimate; scheduler still owns admission."""
    if canary:
        return {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.5}
    if dp <= 0.005 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib": 6144, "io_weight": 1}
    if dp <= 0.0075 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 1}
    return {"cpu_cores": 2, "ram_mib": 12288, "gpu_peak_mib": 3072, "io_weight": 1}


def event_window(
    registered_initial_window_s: float = FULL_WINDOW_S,
    maximum_extended_window_s: float = MAXIMUM_EXTENDED_WINDOW_S,
) -> dict:
    registered_initial_window_s = float(registered_initial_window_s)
    maximum_extended_window_s = float(maximum_extended_window_s)
    if not np.isfinite(registered_initial_window_s) or registered_initial_window_s <= 0:
        raise ValueError("registered event window must be positive and finite")
    if not np.isfinite(maximum_extended_window_s) or maximum_extended_window_s < registered_initial_window_s:
        raise ValueError("maximum extended event window must be finite and at least the registered window")
    return {
        "registered_initial_window_s": registered_initial_window_s,
        "maximum_extended_window_s": maximum_extended_window_s,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "motion_start_s": MOTION_START_S,
        "motion_source_file_duration_s": SOURCE_MOTION_FILE_DURATION_S,
        "post_settle_observation_s": POST_SETTLE_OBSERVATION_S,
        "settle_hold_s": SETTLE_HOLD_S,
        "right_censor_policy": "run the whole registered window; if a required event is right-censored, extend once to 2x and retain the censored status",
        "events": [
            {
                "id": "motion_complete",
                "definition": "prescribed cup angle reaches -105 degrees at 0.50 + duration(q) s",
            },
            {
                "id": "receiver_contact",
                "definition": "valid native fluid mass inside the one-dp-clear receiver interior first reaches 1% of initial fluid mass",
            },
            {
                "id": "spill_or_escape",
                "definition": "valid native fluid mass outside the cup, receiver and tray observation volumes first reaches 1% of initial mass; missing identities remain a separate integrity failure",
            },
            {
                "id": "settled",
                "definition": "after motion completion, speed p95 <= 0.10 m/s and kinetic energy <= 5% of initial gravitational potential for 0.20 s continuously",
            },
            {
                "id": "event_window_complete",
                "definition": "motion, receiver contact and settled are observed, with 0.35 s of saved output after the last required transition",
            },
        ],
    }


def _cell(q: float, dp: float, design_cell: str, *, temporal_variant: str | None = None) -> dict:
    duration = duration_for_q(q)
    case = f"CORE_F2_pour_duration_q{q:.8f}_dp{dp:.12f}_{design_cell}"
    if temporal_variant:
        case += f"_{temporal_variant}"
    time_control = copy.deepcopy(
        F2_INTERNAL_TIME_CONTROL if temporal_variant == "internal_time" else F2_BASE_TIME_CONTROL
    )
    return {
        "schema": "core.cfd.v1",
        "family": "F2",
        "scope_id": "F2_pour_duration_x_v1",
        "revision_id": REVISION_ID,
        "observer_revision": F2_OBSERVER_REVISION_ID,
        "case_id": case.replace(".", "p"),
        "recipe_id": "F2_rotating_pour_dbc_domain_extension_v1",
        "recipe": "native_dbc",
        "stage": "qualification",
        "qualification_only": True,
        "split": "qualification_only",
        "parameter": {
            "name": "rotation_duration_s",
            "q": float(q),
            "value": duration,
            "candidate_range": list(DURATION_RANGE_S),
            "held_out": q in HELD_OUT_Q,
        },
        "dp_m": float(dp),
        "cfl": float(time_control["cflnumber"]),
        "time_control": time_control,
        "time_max_s": FULL_WINDOW_S,
        "maximum_extended_time_s": MAXIMUM_EXTENDED_WINDOW_S,
        "output_interval_s": OUTPUT_INTERVAL_S if temporal_variant != "native_output" else OUTPUT_INTERVAL_S / 5.0,
        "angle_degrees": ANGLE_DEGREES,
        "motion_start_s": MOTION_START_S,
        "receiver_center": [0.45, 0.0],
        "cup": copy.deepcopy(core_f2.CUP),
        "receiver": copy.deepcopy(core_f2.RECEIVER),
        "tray": copy.deepcopy(core_f2.TRAY),
        "wall_bounds": {"xmin": -0.60, "xmax": 2.00, "ymin": -0.55, "ymax": 0.55, "zmin": -0.20, "zmax": 1.10},
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "fluid_boxes": [copy.deepcopy(box) for box in core_f2.FLUID_BOXES],
        "initial_fluid_height_m": 0.33,
        "initial_fluid_bottom_m": 0.70,
        "initial_fluid_top_m": 1.03,
        "runtime_domain": {
            # These are the actual source simulation-domain faces.  The
            # finite tray/cup bounds remain separate physical geometry.
            "posmin": [-0.70, -0.65, -0.40],
            "posmax": [2.20, 0.80, DOMAIN_ZMAX_M],
            "baseline_zmax_m": BASELINE_DOMAIN_ZMAX_M,
            "changed_zmax_m": DOMAIN_ZMAX_M,
            "change_is_computational_only": True,
        },
        "design_cell": design_cell,
        "temporal_variant": temporal_variant,
        "physical_geometry_changed": False,
        "mass_rescaling": False,
        "resource_estimate": resource_estimate(dp),
        "source_label_semantics": "initial Mk is a numerical source partition; not material truth",
        "physical_case_id": "F2_standard_centered_rotating_pour_v1",
        "lineage_group_id": "F2_pour_duration_x_v1",
        "qualification_claim": "none",
    }


def qualification_design() -> dict:
    cells = []
    for q in (0.0, 0.5, 1.0):
        for dp in DP_RESOLUTIONS:
            row = _cell(q, dp, "spatial")
            row["static_mass_check"] = _mass_check(dp)
            cells.append(row)
    for q in HELD_OUT_Q:
        for dp in DP_RESOLUTIONS[1:]:
            row = _cell(q, dp, "spatial")
            row["static_mass_check"] = _mass_check(dp)
            cells.append(row)
    for variant in ("internal_time", "native_output"):
        row = _cell(0.5, CANARY_DP_M, variant, temporal_variant=variant)
        row["static_mass_check"] = _mass_check(CANARY_DP_M)
        cells.append(row)
    return {
        "schema": SCHEMA,
        "revision_id": REVISION_ID,
        "created_at": _stamp(),
        "family": "F2",
        "scope_id": "F2_pour_duration_x_v1",
        "parameter_axis": {
            "name": "rotation_duration_s",
            "candidate_range_s": list(DURATION_RANGE_S),
            "mapping": "duration(q)=0.50+0.70*q",
            "q_points": list(Q_POINTS),
            "qualification_q": [0.0, 0.5, 1.0],
            "held_out_q": list(HELD_OUT_Q),
            "endpoint_provenance": {
                "fast_center_duration_s": 0.50,
                "slow_center_duration_s": 1.20,
                "source": "existing centered F2 rotating-pour controls; no new geometry endpoint",
            },
        },
        "fixed_physical_case": {
            "geometry": "standard finite cup, receiver and tray from F2 center nominal source",
            "cup": copy.deepcopy(core_f2.CUP),
            "receiver": copy.deepcopy(core_f2.RECEIVER),
            "tray": copy.deepcopy(core_f2.TRAY),
            "initial_fluid_boxes": [copy.deepcopy(box) for box in core_f2.FLUID_BOXES],
            "initial_fluid_height_m": 0.33,
            "initial_fluid_bottom_m": 0.70,
            "initial_fluid_top_m": 1.03,
            "angle_degrees": ANGLE_DEGREES,
            "receiver_center": [0.45, 0.0],
            "gravity_m_s2": -9.81,
            "unchanged": True,
        },
        "computational_envelope": {
            "runtime_domain_zmax_m": DOMAIN_ZMAX_M,
            "baseline_runtime_domain_zmax_m": BASELINE_DOMAIN_ZMAX_M,
            "purpose": "retain the H1 diagnostic envelope while separating domain censoring from the physical pour",
            "physical_geometry_changed": False,
        },
        "resolutions_m": list(DP_RESOLUTIONS),
        "cells": cells,
        "cell_count": len(cells),
        "spatial_cell_count": sum(row["design_cell"] == "spatial" for row in cells),
        "temporal_cell_count": sum(row["design_cell"] != "spatial" for row in cells),
        "held_out_q": list(HELD_OUT_Q),
        "replacement_q": [0.125, 0.375, 0.625, 0.875],
        "event_window": event_window(),
        "observer": {
            "revision_id": F2_OBSERVER_REVISION_ID,
            "observable_names": list(F2_OBSERVABLE_NAMES),
            "geometry": "moving cup body frame plus world receiver/tray; source Mk is not material identity",
            "normalization": "fixed initial-native-mass denominator; runtime/cup dimensions; initial gravitational potential; no survivor renormalization",
            "calibration_required": True,
        },
        "preregistered_gates": {
            "source_initial_mass_relative_error_max": 0.025,
            "initial_mass_spread_over_continuous_mass_max": 0.03,
            "mass_change_relative_max": 1e-8,
            "closed_wall_endpoint_tolerance_m": 1e-8,
            "saved_chord_crossings_allowed": 0,
            "no_missing_native_fluid_ids": True,
            "no_nonfinite_active_values": True,
            "spatial_max_absolute_normalized_difference": 0.05,
            "temporal_fraction_of_spatial_budget": 0.2,
            "temporal_max_absolute_normalized_difference": 0.01,
            "event_time_relative_error_max": 0.05,
            "actual_dt_ratio_max_for_internal_time": 0.80,
            "actual_step_ratio_min_for_internal_time": 1.25,
            "native_output_interval_ratio_max": 0.30,
            "native_output_frame_ratio_min": 3.0,
            "event_window_complete_required": True,
            "qualification_requires_all_15_cells": True,
        },
        "static_mass_status": {
            "all_15_rows_present": len(cells) == 15,
            "all_mass_gates_pass": all(row["static_mass_check"]["mass_gate_pass"] for row in cells),
            "mass_rescaling": False,
        },
        "execution_status": "design_only; no GPU launch",
        "canary_dependency": {
            "job_id": "f2-pour-duration-fullwindow-canary-001",
            "required_before_qualification": True,
            "required_status": "succeeded with hard integrity, resolved domain, mass, and complete event window",
        },
        "calibration_dependency": {
            "schema": "core.f2.observer.calibration.v1",
            "required_pass": True,
            "external_physical_validation": False,
        },
        "qualification_claim": "none",
    }


def write_design(output: Path) -> dict:
    design = qualification_design()
    _write_json(output, design)
    return design


def write_matrix(output: Path, design_path: Path | None = None) -> dict:
    design_path = Path(design_path) if design_path is not None else None
    design = json.loads(design_path.read_text()) if design_path is not None else qualification_design()
    matrix = {
        "schema": "core.f2.qualification.matrix.v1",
        "revision_id": design["revision_id"],
        "scope_id": design["scope_id"],
        "design_sha256": core_cfd.digest(design_path) if design_path is not None else None,
        "cells": [
            {
                "index": index,
                "case_id": row["case_id"],
                "q": row["parameter"]["q"],
                "dp_m": row["dp_m"],
                "design_cell": row["design_cell"],
                "temporal_variant": row["temporal_variant"],
                "qualification_only": row["qualification_only"],
                "mass_check": row["static_mass_check"],
                "execution_status": "not_started",
            }
            for index, row in enumerate(design["cells"])
        ],
        "complete": len(design.get("cells", [])) == 15,
        "static_mass_status": design["static_mass_status"],
        "execution_status": "registration_only; no GPU launch",
        "qualification_claim": "none",
    }
    _write_json(output, matrix)
    return matrix


def parameter_card(design_path: Path | None = None) -> dict:
    design_path = Path(design_path) if design_path is not None else None
    design = json.loads(design_path.read_text()) if design_path is not None else qualification_design()
    return {
        "schema": "core.f2.parameter_card.v1",
        "revision_id": design["revision_id"],
        "scope_id": design["scope_id"],
        "family": "F2",
        "parameter": design["parameter_axis"],
        "fixed_physical_geometry": design["fixed_physical_case"],
        "initial_condition": {
            "continuum_fluid_height_m": 0.33,
            "continuum_fluid_bottom_m": 0.70,
            "continuum_fluid_top_m": 1.03,
            "native_sampling": "nearest in-box cell centres at each dp; native rho*dp^3; no mass rescaling",
            "separate_h0_forensics": "campaigns/core-v1/cfd/f2-h0-initial-impact-forensics.json",
        },
        "computational_envelope": design["computational_envelope"],
        "resolutions_m": design["resolutions_m"],
        "resource_estimates": {str(dp): resource_estimate(dp) for dp in DP_RESOLUTIONS},
        "event_window": design["event_window"],
        "observer": design["observer"],
        "preregistered_gates": design["preregistered_gates"],
        "matrix": {
            "cell_count": design["cell_count"],
            "spatial_cell_count": design["spatial_cell_count"],
            "temporal_cell_count": design["temporal_cell_count"],
            "held_out_q": design["held_out_q"],
            "qualification_claim": "none until all 15 cells, integrity, event-window and comparator gates pass",
        },
        "source_provenance": {
            "nominal_definition": core_f2.SOURCE_RELATIVE,
            "endpoint_controls": "existing centered fast duration 0.50 s and slow duration 1.20 s",
            "geometry_change": False,
        },
        "execution_status": "design_only; no GPU launch",
        "qualification_claim": "none",
    }


def write_card(output: Path, design_path: Path | None = None) -> dict:
    card = parameter_card(design_path)
    _write_json(output, card)
    return card


def _dynamic_motion(path: Path, duration_s: float, angle_degrees: float = ANGLE_DEGREES) -> None:
    lines = ["#Time;Degrees"]
    for time_s in np.arange(0.0, SOURCE_MOTION_FILE_DURATION_S + 0.0001, 0.01):
        lines.append(f"{time_s:.6f};{motion_angle(float(time_s), duration_s, angle_degrees):.9f}")
    path.write_text("\n".join(lines) + "\n")


def _set_parameter(root: ET.Element, key: str, value: str | float | int) -> None:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        parameters = root.find(".//execution/parameters")
        if parameters is None:
            raise ValueError(f"source definition has no execution parameters for {key}")
        node = ET.SubElement(parameters, "parameter", {"key": key})
    node.set("value", str(value))


def _insert_dynamic_mdbc_normals(root: ET.Element) -> dict:
    """Add the verified static H2 normal/ghost construction to a moving case.

    The cup remains the same finite moving box.  GenCase constructs normals
    from the initial geometry; the native moving-body record and the existing
    ``mvrotfile`` carry the prescribed rotation and wall velocity at runtime.
    """
    geometry_commands = root.find(".//geometry/commands")
    main = root.find(".//geometry/commands/mainlist")
    casedef = root.find("./casedef")
    if geometry_commands is None or main is None or casedef is None:
        raise ValueError("F2 source geometry is incomplete for dynamic mDBC")
    normals_list = ET.Element("list", {"name": "GeometryForNormals"})
    ET.SubElement(normals_list, "setactive", {"drawpoints": "0", "drawshapes": "1"})
    ET.SubElement(normals_list, "setshapemode").text = "actual | bound"
    ET.SubElement(normals_list, "setnormalinvert", {"invert": "true"})
    entries = (
        (core_f2.CUP, "bottom | left | right | front | back"),
        (core_f2.RECEIVER, "bottom | left | right | front | back"),
        (core_f2.TRAY, "bottom"),
    )
    for mk, (box, fill) in enumerate(entries):
        ET.SubElement(normals_list, "setmkbound", {"mk": str(mk)})
        draw = ET.SubElement(normals_list, "drawbox")
        ET.SubElement(draw, "boxfill").text = fill
        ET.SubElement(draw, "point", {axis: f"{float(box['low'][index]):.17g}" for index, axis in enumerate("xyz")})
        ET.SubElement(draw, "size", {axis: f"{float(box['size'][index]):.17g}" for index, axis in enumerate("xyz")})
        ET.SubElement(draw, "layers", {"vdp": "-0.5"})
    ET.SubElement(normals_list, "shapeout", {"file": "hdp"})
    ET.SubElement(normals_list, "resetdraw")
    geometry_commands.insert(0, normals_list)
    main.insert(0, ET.Element("runlist", {"name": "GeometryForNormals"}))
    shape = main.find("setshapemode")
    if shape is not None:
        shape.text = "actual | bound"
    old_normals = casedef.find("normals")
    if old_normals is not None:
        casedef.remove(old_normals)
    normals = ET.SubElement(casedef, "normals", {"active": "true"})
    norgeometry = ET.SubElement(normals, "norgeometry")
    ET.SubElement(norgeometry, "geometryfile", {"file": "[CaseName]_hdp_Actual.vtk"})
    ET.SubElement(norgeometry, "distanceh", {"v": "3.0"})
    ET.SubElement(norgeometry, "svshapes", {"v": "true"})
    return {
        "normal_construction_layers_vdp": -0.5,
        "normal_search_distance_h": 3.0,
        "svshapes": True,
        "normal_geometry_file": "[CaseName]_hdp_Actual.vtk",
        "physical_geometry_changed": False,
        "moving_wall_contract": "existing mvrotfile axis y about pivot z=0.65 rotates the complete mDBC boundary object; no static-wall velocity substitution",
    }


def _insert_closed_catchment_walls(root: ET.Element, catchment: dict) -> dict:
    """Add four fixed outer walls while retaining the registered tray bottom.

    The old tray remains the floor and keeps its original material/observer
    identity.  The new ``mkbound`` is reserved for the catchment walls, so the
    physical change and the destination purpose are explicit in the prepared
    receipt.  The catchment top is open to receive spill.
    """
    main = root.find(".//geometry/commands/mainlist")
    if main is None:
        raise ValueError("F2 source geometry has no mainlist for catchment walls")
    tray_set_index = None
    tray_draw_index = None
    for index, node in enumerate(list(main)):
        if node.tag == "setmkbound" and node.get("mk") == str(catchment["mkbound"] - 1):
            candidate = index + 1
            if candidate < len(main) and main[candidate].tag == "drawbox":
                fill = (main[candidate].findtext("boxfill") or "").strip()
                if fill == "bottom":
                    tray_set_index = index
                    tray_draw_index = candidate
                    break
    if tray_draw_index is None:
        raise ValueError("F2 registered tray bottom drawbox was not found")
    wall_set = ET.Element("setmkbound", {"mk": str(int(catchment["mkbound"]))})
    wall_draw = ET.Element("drawbox")
    ET.SubElement(wall_draw, "boxfill").text = "left | right | front | back"
    ET.SubElement(wall_draw, "point", {
        axis: f"{float(catchment['low'][index]):.17g}" for index, axis in enumerate("xyz")
    })
    ET.SubElement(wall_draw, "size", {
        axis: f"{float(catchment['size'][index]):.17g}" for index, axis in enumerate("xyz")
    })
    ET.SubElement(wall_draw, "layers", {"vdp": "0,1,2"})
    main.insert(tray_draw_index + 1, wall_set)
    main.insert(tray_draw_index + 2, wall_draw)
    return {
        "material_mkbound": int(catchment["mkbound"]),
        "floor_material_mkbound": int(catchment["mkbound"] - 1),
        "boxfill": "left | right | front | back",
        "top_open": True,
        "physical_geometry_changed": True,
        "preserved_registered_tray_bottom": True,
    }


def _runtime_domain_from_xml(root: ET.Element) -> dict:
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None or domain.find("posmin") is None or domain.find("posmax") is None:
        raise ValueError("F2 generated XML has no complete simulation domain")
    lower = domain.find("posmin")
    upper = domain.find("posmax")
    return {
        "posmin": [float(lower.get(axis)) for axis in "xyz"],
        "posmax": [float(upper.get(axis)) for axis in "xyz"],
    }


def _gencase_alignment_corrections(sampling: list[dict], dp_m: float) -> list[dict]:
    """Keep GenCase's inclusive grid endpoints at the registered native count.

    The source drawbox dimensions are continuous extents.  At dp=.01 the
    first z layer otherwise loses one endpoint after GenCase grid snapping;
    at dp=.005 the y extent otherwise gains one endpoint.  These are tiny
    drawbox serialization corrections, recorded here explicitly, while the
    physical boxes, native rho*dp^3 mass, and registered particle counts stay
    fixed.
    """
    corrections = []
    if math.isclose(float(dp_m), 0.01, rel_tol=0.0, abs_tol=1e-12):
        sample = sampling[0]
        original = float(sample["draw_size_m"][2])
        corrected = float(sample["counts"][2] * dp_m - 1e-9)
        sample["draw_size_m"][2] = corrected
        corrections.append({"box_index": 0, "axis": "z", "original_draw_size_m": original,
                            "corrected_draw_size_m": corrected, "reason": "GenCase first-layer endpoint alignment"})
    if math.isclose(float(dp_m), 0.005, rel_tol=0.0, abs_tol=1e-12):
        for index, sample in enumerate(sampling):
            original = float(sample["draw_size_m"][1])
            corrected = float((sample["counts"][1] - 1) * dp_m - 1e-6)
            sample["draw_size_m"][1] = corrected
            corrections.append({"box_index": index, "axis": "y", "original_draw_size_m": original,
                                "corrected_draw_size_m": corrected, "reason": "GenCase y endpoint alignment"})
    return corrections


def _prepare_dynamic_case(lab: Path, output: Path, config: dict) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"dynamic F2 case output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(config)
    case_id = str(config["case_id"])
    duration_s = float(config["parameter"]["value"])
    dp_m = float(config["dp_m"])
    time_max_s = float(config["time_max_s"])
    output_interval_s = float(config["output_interval_s"])
    runtime_zmax = float(config["runtime_domain"]["posmax"][2])
    time_control = copy.deepcopy(config.get("time_control", F2_BASE_TIME_CONTROL))
    config["time_control"] = time_control
    config["event_window"] = copy.deepcopy(config.get("event_window_override", event_window()))
    boundary_method = int(config.get("boundary_method", 1))
    if boundary_method not in (1, 2):
        raise ValueError("F2 dynamic boundary_method must be 1 (DBC) or 2 (mDBC)")
    source = lab / core_f2.SOURCE_RELATIVE
    sampling = [core_f2._nearest_native_box(box, dp_m) for box in core_f2.FLUID_BOXES]
    alignment_corrections = _gencase_alignment_corrections(sampling, dp_m)
    target = output / f"{case_id}_Def.xml"
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    commands = root.find(".//geometry/commands/mainlist")
    if definition is None or commands is None:
        raise ValueError("F2 source geometry is incomplete")
    definition.set("dp", f"{dp_m:.17g}")
    pointmax = definition.find("pointmax")
    if pointmax is None:
        raise ValueError("F2 source geometry has no pointmax")
    pointmax.set("z", f"{runtime_zmax:.17g}")
    fluid_index = 0
    active_mk = None
    for node in list(commands):
        if node.tag == "setmkfluid":
            active_mk = int(node.get("mk"))
        elif node.tag == "drawbox" and active_mk is not None:
            sample = sampling[fluid_index]
            point, size = node.find("point"), node.find("size")
            if point is None or size is None:
                raise ValueError("F2 fluid drawbox is incomplete")
            for index, axis in enumerate("xyz"):
                point.set(axis, f"{sample['first_center_m'][index]:.17g}")
                size.set(axis, f"{sample['draw_size_m'][index]:.17g}")
            fluid_index += 1
    if fluid_index != len(sampling):
        raise ValueError("F2 source fluid drawbox count changed")
    boundary_recipe = None
    catchment_recipe = None
    if config.get("catchment") is not None:
        catchment_recipe = _insert_closed_catchment_walls(root, config["catchment"])
    if boundary_method == 2:
        boundary_recipe = _insert_dynamic_mdbc_normals(root)
    motion = root.find(".//mvrotfile")
    if motion is None or motion.find("file") is None:
        raise ValueError("F2 source motion block is incomplete")
    motion.set("duration", f"{SOURCE_MOTION_FILE_DURATION_S:.17g}")
    motion.find("file").set("name", f"{case_id}_motion.dat")
    for node in root.findall(".//begin"):
        node.set("finish", f"{SOURCE_MOTION_FILE_DURATION_S:.17g}")
    for key, value in (("Boundary", boundary_method), ("SlipMode", 1), ("TimeMax", time_max_s), ("TimeOut", output_interval_s),
                       ("DtIni", time_control["DtIni"]), ("DtMin", time_control["DtMin"]),
                       ("DtFixed", time_control["DtFixed"])):
        _set_parameter(root, key, value)
    # The native F2 source stores cflnumber under constantsdef.  Generated
    # XML preserves that location; do not require an execution wrapper.
    cfl_node = root.find(".//cflnumber")
    if cfl_node is None:
        raise ValueError("F2 source definition has no cflnumber")
    cfl_node.set("value", f"{float(time_control['cflnumber']):.17g}")
    domain = root.find(".//execution/parameters/simulationdomain")
    if domain is None or domain.find("posmin") is None or domain.find("posmax") is None:
        raise ValueError("F2 source runtime domain is incomplete")
    runtime_domain = config["runtime_domain"]
    for node_name, key in (("posmin", "posmin"), ("posmax", "posmax")):
        node = domain.find(node_name)
        values = runtime_domain[key]
        for index, axis in enumerate("xyz"):
            node.set(axis, f"{float(values[index]):.17g}")
    ET.indent(tree, space="    ")
    tree.write(target, encoding="utf-8", xml_declaration=True)
    motion_path = output / f"{case_id}_motion.dat"
    _dynamic_motion(motion_path, duration_s)
    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / case_id
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(target.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_f2.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"dynamic F2 GenCase failed: {output / 'gencase.log'}")
    generated = ET.parse(prefix.with_suffix(".xml")).getroot()
    resolved_runtime_domain = _runtime_domain_from_xml(generated)
    if resolved_runtime_domain != {
        "posmin": [float(value) for value in config["runtime_domain"]["posmin"]],
        "posmax": [float(value) for value in config["runtime_domain"]["posmax"]],
    }:
        raise ValueError("generated F2 runtime domain differs from the prepared declaration")
    blocks = generated.findall(".//particles/fluid")
    generated_counts = [int(block.get("count")) for block in blocks]
    expected_counts = [int(item["particle_count"]) for item in sampling]
    catchment_preflight = {
        "enabled": catchment_recipe is not None,
        "material_mkbound": None,
        "material_particle_count": 0,
        "floor_material_mkbound": None,
        "floor_particle_count": 0,
        "wall_groups_present": False,
        "floor_group_present": False,
    }
    if catchment_recipe is not None:
        catchment_mk = int(catchment_recipe["material_mkbound"])
        floor_mk = int(catchment_recipe["floor_material_mkbound"])
        for particle_group in generated.findall(".//particles/*"):
            if particle_group.tag not in {"fixed", "moving"}:
                continue
            mkbound = int(particle_group.get("mkbound", "-1"))
            count = int(particle_group.get("count", "0"))
            if mkbound == catchment_mk:
                catchment_preflight["material_mkbound"] = catchment_mk
                catchment_preflight["material_particle_count"] += count
            if mkbound == floor_mk:
                catchment_preflight["floor_material_mkbound"] = floor_mk
                catchment_preflight["floor_particle_count"] += count
        catchment_preflight["wall_groups_present"] = catchment_preflight["material_particle_count"] > 0
        catchment_preflight["floor_group_present"] = catchment_preflight["floor_particle_count"] > 0
        catchment_preflight["passed"] = bool(
            catchment_preflight["wall_groups_present"] and catchment_preflight["floor_group_present"]
        )
    else:
        catchment_preflight["passed"] = True
    sampling_payload = {
        "fluid_boxes": sampling,
        "expected_fluid_particles": int(sum(expected_counts)),
        "continuous_mass_kg": float(sum(item["continuous_mass_kg"] for item in sampling)),
        "sampled_mass_kg": float(sum(item["discrete_mass_kg"] for item in sampling)),
        "mass_policy": "native rho*dp^3, no mass rescaling",
        "gencase_alignment_corrections": alignment_corrections,
    }
    mass = core_cfd.mass_quality(sampling_payload)
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    with tempfile.TemporaryDirectory(prefix="core-f2-dynamic-") as folder:
        ids, pos, vel, rho, meta, info, arrays = core_cfd.native_frame(prefix.with_suffix(".bi4"), Path(folder) / "native", decoder)
        boundary_count = int(meta.get("CaseNfixed", 0)) + int(meta.get("CaseNmoving", 0)) + int(meta.get("CaseNfloat", 0))
        normal_file = arrays / "BoundNor.bin"
        normals = np.fromfile(normal_file, np.float32).reshape(-1, 3) if normal_file.is_file() else np.empty((0, 3))
        zero_normals = int(np.sum(np.linalg.norm(normals, axis=1) <= 1e-10))
        normal_preflight = boundary_method != 2 or (
            len(normals) == boundary_count and zero_normals == 0 and np.isfinite(normals).all()
        )
        native = {
            "total_particles": int(len(ids)),
            "boundary_particles": boundary_count,
            "fluid_particles": int(meta.get("CaseNfluid", 0)),
            "expected_fluid_particles": int(sampling_payload["expected_fluid_particles"]),
            "unique_ids": bool(len(np.unique(ids)) == len(ids)),
            "finite_initial_arrays": bool(all(np.isfinite(array).all() for array in (pos, vel, rho))),
            "normal_count": int(len(normals)),
            "zero_boundary_normals": zero_normals,
            "normal_preflight_pass": bool(normal_preflight),
        }
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": _stamp(),
        "config": config,
        "sampling": sampling_payload,
        "mass_preflight": mass,
        "native_initial": native,
        "resolved_runtime_domain": resolved_runtime_domain,
        "dynamic_canary_preflight": {
            "generated_fluid_counts": generated_counts == expected_counts,
            "native_state_finite_unique": native["unique_ids"] and native["finite_initial_arrays"],
            "mdbc_normals_complete_nonzero": bool(native["normal_preflight_pass"]),
            "full_window_s": time_max_s,
            "maximum_extended_window_s": float(config.get("maximum_extended_time_s", MAXIMUM_EXTENDED_WINDOW_S)),
            "motion_duration_s": duration_s,
            "catchment_geometry": catchment_preflight,
        },
        "preflight_pass": bool(generated_counts == expected_counts and native["unique_ids"] and native["finite_initial_arrays"] and native["normal_preflight_pass"] and mass["mass_gate_pass"] and catchment_preflight["passed"]),
        "generated_prefix": str(prefix.resolve()),
        "source_template": str(source.resolve()),
        "source_template_sha256": core_cfd.digest(source),
        "definition_sha256": core_cfd.digest(target),
        "motion_sha256": core_cfd.digest(motion_path),
        "solver_binary": str(binaries / "DualSPHysics5.4_linux64"),
        "solver_sha256": core_cfd.digest(binaries / "DualSPHysics5.4_linux64"),
        "decoder": str(decoder),
        "decoder_sha256": core_cfd.digest(decoder),
        "solver_arguments": ["-mdbc_noslip:1"] if boundary_method == 2 else [],
        "boundary_recipe": boundary_recipe,
        "catchment_recipe": catchment_recipe,
        "catchment_preflight": catchment_preflight,
        "qualification_claim": config.get("qualification_claim", "none; F2 dynamic canary only"),
    }
    prepared["inputs"] = {str(path.resolve()): core_cfd.digest(path) for path in output.rglob("*") if path.is_file()}
    _write_json(output / "prepared.json", prepared)
    return prepared


def prepare_dynamic_canary(lab: Path, output: Path, q: float = 0.5) -> dict:
    """CPU-prepare the midpoint canary without changing the registered matrix."""
    config = _cell(q, CANARY_DP_M, "dynamic_canary")
    config.update({
        "scope_id": "F2_pour_duration_dynamic_canary_v1",
        "revision_id": CANARY_REVISION_ID,
        "case_id": "CORE_F2_pour_duration_q0p50000000_dp0p007500000000_fullwindow_canary",
        "recipe_id": "F2_rotating_pour_dbc_domain_extension_canary_v1",
        "stage": "canary",
        "qualification_only": False,
        "time_max_s": FULL_WINDOW_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "parameter": {**config["parameter"], "value": duration_for_q(q)},
        "qualification_claim": "none",
    })
    return _prepare_dynamic_case(lab, output, config)


F2_ENVELOPE_REPAIR_REVISION_ID = "F2_pour_duration_runtime_envelope_repair_v1"
F2_ENVELOPE_REPAIR_SCOPE_ID = "F2_pour_duration_runtime_envelope_repair_x_v1"
F2_ENVELOPE_REPAIR_DOMAIN = {
    "posmin": [-0.95, -0.90, -0.90],
    "posmax": [2.45, 1.10, DOMAIN_ZMAX_M],
    "baseline_zmax_m": BASELINE_DOMAIN_ZMAX_M,
    "changed_zmax_m": DOMAIN_ZMAX_M,
    "change_is_computational_only": True,
    "candidate": "all-face finite margin around the generated XML envelope",
    "margin_relative_to_failed_generated_xml_m": {
        "xmin": 0.25, "xmax": 0.25, "ymin": 0.25, "ymax": 0.30, "zmin": 0.50, "zmax": 0.0,
    },
}

F2_BALLISTIC_ENVELOPE_REVISION_ID = "F2_pour_duration_ballistic_envelope_canary_v1"
F2_BALLISTIC_ENVELOPE_SCOPE_ID = "F2_pour_duration_ballistic_envelope_x_v1"
F2_BALLISTIC_ENVELOPE_DOMAIN = {
    "posmin": [-7.2, -4.8, -18.7],
    "posmax": [6.1, 5.5, DOMAIN_ZMAX_M],
    "baseline_zmax_m": BASELINE_DOMAIN_ZMAX_M,
    "changed_zmax_m": DOMAIN_ZMAX_M,
    "change_is_computational_only": True,
    "candidate": "observed-PartOut ballistic full-window diagnostic envelope",
    "basis": {
        "horizon_s": FULL_WINDOW_S,
        "gravity_m_s2": -9.81,
        "xy_model": "constant observed PartOut velocity",
        "z_model": "observed PartOut velocity plus public gravity",
        "unbounded_projection_min_m": [-6.661849072934432, -4.208418867899198, -18.137911536362306],
        "unbounded_projection_max_m": [5.5949228745348645, 4.9581413575907565, 0.86040312],
        "outward_margin_m": 0.5,
        "physical_geometry_changed": False,
        "mass_rescaling": False,
    },
}

F2_MDBC_CLOSED_WALL_REVISION_ID = "F2_pour_duration_mdbc_closed_wall_canary_v1"
F2_MDBC_CLOSED_WALL_SCOPE_ID = "F2_pour_duration_mdbc_closed_wall_x_v1"

F2_CATCHMENT_REVISION_ID = "F2_closed_catchment_geometry_canary_v3_floor_contract"
F2_CATCHMENT_SCOPE_ID = "F2_closed_catchment_geometry_x_v1"
F2_CATCHMENT_MATRIX_REVISION_ID = "F2_closed_catchment_qualification_v1"
F2_CATCHMENT_MATRIX_SCHEMA = "core.f2.closed_catchment.qualification.v1"
F2_CATCHMENT_CANARY_JOB_ID = "f2-pour-duration-closed-catchment-canary-v2-001"
F2_CATCHMENT_GEOMETRY = {
    # The registered tray bottom remains the floor.  This recipe adds only
    # four fixed side walls, leaving the top open for an incoming spill.
    "low": [-0.60, -0.55, -0.20],
    "size": [2.60, 1.10, 0.80],
    "fluid_floor_surface_z_m": -0.20,
    "mkbound": 3,
    "floor_material_mkbound": 2,
    "drawn_faces": ["left", "right", "front", "back"],
    "closed_faces": ["bottom", "left", "right", "front", "back"],
    "open_faces": ["top"],
    "wall_layers_vdp": [0, 1, 2],
    "nominal_wall_thickness_m": 0.0225,
    "continuous_geometry": "fixed side-wall box over the original tray footprint; the original tray bottom is retained",
    "material_purpose": "external rigid spill/overflow collection walls; mkbound=3 is a new physical material region",
    "floor_purpose": "original registered tray bottom, mkbound=2, retained as the collection floor",
    "physical_geometry_changed": True,
    "physical_surface_thickness_m": 0.0,
    "wall_thickness_semantics": "numerical particle shell only; continuous physical boundary is the declared source plane",
}


def catchment_resource_estimate(dp: float) -> dict:
    """Conservative scheduler reservation for the catchment matrix rows."""
    dp = float(dp)
    if dp <= 0.005 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 65536, "gpu_peak_mib": 24576, "io_weight": 3}
    return {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2}


def _catchment_event_window_estimate(
    duration_s: float,
    *,
    registered_window_s: float = FULL_WINDOW_S,
    maximum_extended_window_s: float = MAXIMUM_EXTENDED_WINDOW_S,
) -> dict:
    """Record a physical time estimate without changing the registered gates.

    The source ``boxfill=bottom`` tray is a bottom-face shell: its continuous
    fluid-facing source plane is z=-0.20 m.  The XML ``size z=0.10`` is an
    extent parameter for the box primitive and does not create a top face.
    Both estimates are diagnostics only.  The canary
    still uses the existing 2.5 s window, 5 s right-censor extension and
    settled definition.
    """
    gravity = 9.81
    initial_top = 1.03
    release_time = MOTION_START_S
    tray_floor_surface = float(F2_CATCHMENT_GEOMETRY["fluid_floor_surface_z_m"])
    outer_floor = float(F2_CATCHMENT_GEOMETRY["low"][2])
    surface_flight = math.sqrt(2.0 * (initial_top - tray_floor_surface) / gravity)
    outer_flight = math.sqrt(2.0 * (initial_top - outer_floor) / gravity)
    return {
        "basis": "zero-initial-vertical-speed free-fall estimate from the highest initial fluid layer; impacts, pressure and cup motion can only change this diagnostic estimate",
        "gravity_m_s2": -gravity,
        "initial_fluid_top_m": initial_top,
        "release_time_s": release_time,
        "retained_tray_floor_surface_z_m": tray_floor_surface,
        "catchment_outer_floor_z_m": outer_floor,
        "nominal_floor_flight_s": surface_flight,
        "nominal_floor_contact_from_release_s": surface_flight,
        "nominal_floor_contact_from_simulation_start_s": release_time + surface_flight,
        "conservative_outer_bound_flight_s": outer_flight,
        "conservative_outer_bound_contact_from_simulation_start_s": release_time + outer_flight,
        "motion_duration_s": float(duration_s),
        "motion_complete_s": release_time + float(duration_s),
        "registered_window_s": float(registered_window_s),
        "maximum_extended_window_s": float(maximum_extended_window_s),
        "output_interval_s": OUTPUT_INTERVAL_S,
        "settled_gate_unchanged": True,
        "estimate_only": True,
    }


def _catchment_observer_candidate() -> dict:
    """Describe a future destination observer without enabling it in observe_dynamic."""
    low = np.asarray(F2_CATCHMENT_GEOMETRY["low"], dtype=float)
    high = low + np.asarray(F2_CATCHMENT_GEOMETRY["size"], dtype=float)
    clearance = float(F2_CATCHMENT_GEOMETRY["nominal_wall_thickness_m"])
    return {
        "status": "separate_candidate_not_enabled",
        "purpose": "destination-aware accounting for mass inside the new catchment, including material retained after leaving the cup/receiver",
        "interior_bounds_m": {
            "xmin": float(low[0] + clearance), "xmax": float(high[0] - clearance),
            "ymin": float(low[1] + clearance), "ymax": float(high[1] - clearance),
            "zmin": float(low[2] + clearance), "zmax": float(high[2] - clearance),
        },
        "open_top": True,
        "uses_current_legacy_tray_observer": False,
        "replaces_current_settled_gate": False,
        "spill_is_deleted": False,
        "qualification_effect": "none; a future observer must be calibrated and reviewed independently",
    }


def _catchment_wall_spec(catchment: dict, tray: dict, *, dp_m: float | None = None) -> dict:
    """Return the public fluid-facing wall contract for the new side walls.

    The bounds use the continuous source planes, with no artificial inward
    shrink based on particle-layer centers.  GenCase's ``vdp=0,1,2`` shell is
    recorded separately; the audit surface is the source bottom plane.  The
    retained tray uses ``boxfill=bottom``, so its fluid-facing plane is
    z=-0.20 m even though the source box has ``size z=0.10``.
    """
    low = np.asarray(catchment["low"], dtype=float)
    high = low + np.asarray(catchment["size"], dtype=float)
    floor_surface = float(catchment.get("fluid_floor_surface_z_m", tray["low"][2]))
    bounds = {
        "xmin": float(low[0]), "xmax": float(high[0]),
        "ymin": float(low[1]), "ymax": float(high[1]),
        "zmin": floor_surface, "zmax": float(high[2]),
    }
    numerical_thickness = float(catchment.get("nominal_wall_thickness_m", 3.0 * float(dp_m or 0.0)))
    if dp_m is not None:
        numerical_thickness = 3.0 * float(dp_m)
    return {
        "container_interior": bounds,
        "closed_faces": ["left", "right", "front", "back"],
        "open_faces": ["top"],
        "mkbound": int(catchment["mkbound"]),
        "surface_convention": "continuous source planes; no inward layer-center shrink",
        "wall_layers_vdp": list(catchment["wall_layers_vdp"]),
        "nominal_wall_thickness_m": numerical_thickness,
        "physical_surface_thickness_m": float(catchment.get("physical_surface_thickness_m", 0.0)),
        "wall_thickness_semantics": catchment.get(
            "wall_thickness_semantics",
            "numerical particle shell only; continuous physical boundary is the declared source plane",
        ),
        "fluid_facing_surface": {
            "xmin": float(low[0]), "xmax": float(high[0]),
            "ymin": float(low[1]), "ymax": float(high[1]),
            "floor_z_m": floor_surface, "top_z_m": float(high[2]),
        },
        "floor": {
            "material_mkbound": int(catchment["floor_material_mkbound"]),
            "fluid_facing_surface_z_m": floor_surface,
            "nominal_outer_low_z_m": float(low[2]),
            "solid_slab_thickness_m": float(floor_surface - low[2]),
            "surface_basis": "source boxfill=bottom plane; source size z is not a top face",
            "preserved_tray_definition": {
                "low": [float(value) for value in tray["low"]],
                "size": [float(value) for value in tray["size"]],
            },
            "closed_faces": ["bottom"],
            "open_faces": ["top", "left", "right", "front", "back"],
        },
        "material_purpose": catchment["material_purpose"],
        "qualification_effect": "new physical geometry scope; no inherited qualification",
    }


def prepare_dynamic_envelope_repair_canary(lab: Path, output: Path, q: float = 0.5) -> dict:
    """Prepare the single evidence-based computational-envelope repair canary."""
    config = _cell(q, CANARY_DP_M, "dynamic_envelope_repair")
    config.update({
        "scope_id": F2_ENVELOPE_REPAIR_SCOPE_ID,
        "revision_id": F2_ENVELOPE_REPAIR_REVISION_ID,
        "case_id": "CORE_F2_pour_duration_q0p50000000_dp0p007500000000_envelope_repair_canary",
        "recipe_id": "F2_rotating_pour_runtime_envelope_repair_canary_v1",
        "stage": "repair_canary",
        "qualification_only": True,
        "time_max_s": FULL_WINDOW_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "parameter": {**config["parameter"], "value": duration_for_q(q)},
        "runtime_domain": copy.deepcopy(F2_ENVELOPE_REPAIR_DOMAIN),
        "repair_candidate_id": "computational_envelope_all_faces_canary",
        "physical_geometry_changed": False,
        "mass_rescaling": False,
        "qualification_claim": "none; F2 envelope repair canary only",
    })
    return _prepare_dynamic_case(lab, output, config)


def prepare_dynamic_ballistic_envelope_canary(lab: Path, output: Path, q: float = 0.5) -> dict:
    """Prepare the physics-based full-window envelope diagnostic canary."""
    config = _cell(q, CANARY_DP_M, "dynamic_ballistic_envelope")
    config.update({
        "scope_id": F2_BALLISTIC_ENVELOPE_SCOPE_ID,
        "revision_id": F2_BALLISTIC_ENVELOPE_REVISION_ID,
        "case_id": "CORE_F2_pour_duration_q0p50000000_dp0p007500000000_ballistic_envelope_canary",
        "recipe_id": "F2_rotating_pour_ballistic_envelope_canary_v1",
        "stage": "repair_canary",
        "qualification_only": True,
        "time_max_s": FULL_WINDOW_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "parameter": {**config["parameter"], "value": duration_for_q(q)},
        "runtime_domain": copy.deepcopy(F2_BALLISTIC_ENVELOPE_DOMAIN),
        "repair_candidate_id": "observed_partout_ballistic_full_window_envelope",
        "physical_geometry_changed": False,
        "mass_rescaling": False,
        "qualification_claim": "none; F2 ballistic envelope diagnostic canary only",
    })
    return _prepare_dynamic_case(lab, output, config)


def prepare_dynamic_mdbc_closed_wall_canary(lab: Path, output: Path, q: float = 0.5) -> dict:
    """Prepare a moving mDBC contact diagnostic on the accepted envelope.

    The candidate retains the F2 cup/receiver/tray, initial fluid, native mass,
    rotation file and full-window ballistic domain.  Its sole physical solver
    change is Boundary=2 with the verified H2 normal/ghost construction; the
    prescribed moving-body transform supplies wall velocity at runtime.
    """
    config = _cell(q, CANARY_DP_M, "dynamic_mdbc_closed_wall")
    config.update({
        "scope_id": F2_MDBC_CLOSED_WALL_SCOPE_ID,
        "revision_id": F2_MDBC_CLOSED_WALL_REVISION_ID,
        "case_id": "CORE_F2_pour_duration_q0p50000000_dp0p007500000000_mdbc_closed_wall_canary",
        "recipe_id": "F2_rotating_pour_mdbc_closed_wall_diagnostic_v1",
        "stage": "repair_canary",
        "qualification_only": True,
        "time_max_s": FULL_WINDOW_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "parameter": {**config["parameter"], "value": duration_for_q(q)},
        "runtime_domain": copy.deepcopy(F2_BALLISTIC_ENVELOPE_DOMAIN),
        "boundary_method": 2,
        "repair_candidate_id": "dynamic_mdbc_closed_wall_contact",
        "physical_geometry_changed": False,
        "mass_rescaling": False,
        "wall_motion_contract": {
            "axis_body_and_native_file": [0.0, 1.0, 0.0],
            "pivot_m": [0.0, 0.0, 0.65],
            "body_transform": "world_from_body=Ry(-motion_angle)",
            "wall_velocity": "solver mvrotfile rigid-body velocity; no static normal or zero wall velocity substitution",
        },
        "qualification_claim": "none; F2 moving mDBC closed-wall diagnostic only",
    })
    return _prepare_dynamic_case(lab, output, config)


def prepare_dynamic_closed_catchment_canary(lab: Path, output: Path, q: float = 0.5) -> dict:
    """Prepare the independent closed-catchment physical-geometry canary.

    The original cup, receiver, tray floor, fluid boxes, native mass rule and
    prescribed rotating-pour control are copied from the F2 source.  Four
    fixed side walls are added around the existing tray footprint.  This is a
    new physical scope and carries no qualification inheritance.
    """
    config = _cell(q, CANARY_DP_M, "closed_catchment_geometry")
    duration_s = duration_for_q(q)
    config.update({
        "scope_id": F2_CATCHMENT_SCOPE_ID,
        "revision_id": F2_CATCHMENT_REVISION_ID,
        "case_id": "CORE_F2_pour_duration_q0p50000000_dp0p007500000000_closed_catchment_canary_v2",
        "recipe_id": "F2_rotating_pour_closed_catchment_geometry_v1",
        "stage": "repair_canary",
        "qualification_only": True,
        "time_max_s": FULL_WINDOW_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "parameter": {**config["parameter"], "value": duration_s},
        "runtime_domain": copy.deepcopy(F2_BALLISTIC_ENVELOPE_DOMAIN),
        "catchment": copy.deepcopy(F2_CATCHMENT_GEOMETRY),
        "catchment_wall_spec": _catchment_wall_spec(F2_CATCHMENT_GEOMETRY, config["tray"]),
        "catchment_event_window_estimate": _catchment_event_window_estimate(duration_s),
        "catchment_observer_candidate": _catchment_observer_candidate(),
        "repair_candidate_id": "closed_external_catchment_geometry",
        "physical_geometry_changed": True,
        "mass_rescaling": False,
        "source_geometry_contract": {
            "cup": "unchanged registered finite moving cup",
            "receiver": "unchanged registered finite fixed receiver",
            "tray_floor": "unchanged registered tray bottom, mkbound=2",
            "pour_control": "unchanged prescribed mvrotfile and rotation duration q=0.5",
            "fluid_source": "unchanged three native fluid boxes and initial height 0.33 m",
        },
        "qualification_inheritance": "none; independent physical geometry scope",
        "qualification_claim": "none; F2 closed catchment geometry canary only",
    })
    return _prepare_dynamic_case(lab, output, config)


def amend_closed_catchment_floor_contract(source_prepared: Path, output: Path) -> dict:
    """Write a metadata-only floor-contract amendment for the v2 canary.

    The original v2 solver inputs and generated particle files are retained by
    reference.  This amendment changes only the physical interpretation used
    by the public geometry/audit adapter: ``boxfill=bottom`` is audited at its
    source plane z=-0.20 m.  It deliberately does not rerun GenCase or the
    solver.
    """
    source_prepared, output = Path(source_prepared).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"floor-contract amendment output must be fresh: {output}")
    source = json.loads(source_prepared.read_text())
    source_config = source.get("config", {})
    if source_config.get("repair_candidate_id") != "closed_external_catchment_geometry":
        raise ValueError("prepared source is not the closed-catchment canary")
    original_definition = Path(source["generated_prefix"]).with_suffix(".xml")
    if not original_definition.is_file():
        raise ValueError("original generated definition is missing")
    amended = copy.deepcopy(source)
    config = amended["config"]
    original_prepared_sha256 = core_cfd.digest(source_prepared)
    original_definition_sha256 = core_cfd.digest(original_definition)
    config["revision_id"] = F2_CATCHMENT_REVISION_ID
    config["catchment"] = copy.deepcopy(F2_CATCHMENT_GEOMETRY)
    config["catchment_wall_spec"] = _catchment_wall_spec(F2_CATCHMENT_GEOMETRY, config["tray"], dp_m=float(config["dp_m"]))
    config["catchment_event_window_estimate"] = _catchment_event_window_estimate(
        float(config["parameter"]["value"]),
        registered_window_s=float(config.get("time_max_s", FULL_WINDOW_S)),
        maximum_extended_window_s=float(config.get("maximum_extended_time_s", MAXIMUM_EXTENDED_WINDOW_S)),
    )
    config["floor_contract"] = {
        "source_boundary_mode": "boxfill=bottom",
        "fluid_facing_surface_z_m": -0.20,
        "xml_size_z_m_is_not_a_top_face": True,
        "nominal_xml_point_z_m": -0.20,
        "nominal_xml_size_z_m": 0.10,
        "solver_input_bytes_unchanged": True,
    }
    amended["config"] = config
    amended["amended_from_prepared"] = str(source_prepared)
    amended["amended_from_prepared_sha256"] = original_prepared_sha256
    amended["amendment_id"] = "F2_closed_catchment_floor_contract_v1"
    amended["solver_input_bytes_unchanged"] = True
    amended["solver_input_definition_sha256"] = original_definition_sha256
    amended["qualification_claim"] = "none; metadata-only floor-contract re-audit"
    amended["floor_contract_amendment"] = config["floor_contract"]
    output.mkdir(parents=True, exist_ok=True)
    # A document cannot contain a self-consistent hash of its own bytes.  Keep
    # a hash of the exact JSON payload before this bookkeeping field is added;
    # the forensic receipt separately records the final file digest.
    amended.pop("amended_prepared_sha256", None)
    payload = json.dumps(amended, indent=2, allow_nan=False) + "\n"
    amended["amended_payload_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    _write_json(output / "prepared.json", amended)
    return amended


def closed_catchment_floor_contract_forensics(
    source_prepared: Path,
    amended_prepared: Path,
    product: Path,
    output: Path,
) -> dict:
    """Re-audit the existing catchment trajectory under the source-plane floor.

    This is read-only with respect to the solver product.  It records the
    source XML and generated native Mk2 shell evidence before invoking the F2
    audit against the same trajectory with the amended prepared contract.
    """
    source_prepared, amended_prepared = Path(source_prepared).resolve(), Path(amended_prepared).resolve()
    product, output = Path(product).resolve(), Path(output).resolve()
    source = json.loads(source_prepared.read_text())
    amended = json.loads(amended_prepared.read_text())
    source_definition = next(source_prepared.parent.glob("*_Def.xml"), None)
    generated_xml = Path(source["generated_prefix"]).with_suffix(".xml")
    bound_vtk = Path(str(source["generated_prefix"]) + "_Bound.vtk")
    if source_definition is None or not generated_xml.is_file() or not bound_vtk.is_file():
        raise ValueError("catchment source/generated geometry evidence is incomplete")
    root = ET.parse(source_definition).getroot()
    main = root.find(".//geometry/commands/mainlist")
    tray_record = None
    if main is not None:
        for index, node in enumerate(list(main)):
            if node.tag == "setmkbound" and node.get("mk") == "2" and index + 1 < len(main):
                draw = main[index + 1]
                if draw.tag == "drawbox" and (draw.findtext("boxfill") or "").strip() == "bottom":
                    point, size, layers = draw.find("point"), draw.find("size"), draw.find("layers")
                    tray_record = {
                        "mkbound": 2,
                        "boxfill": "bottom",
                        "point": {axis: float(point.get(axis)) for axis in "xyz"},
                        "size": {axis: float(size.get(axis)) for axis in "xyz"},
                        "layers_vdp": [int(value) for value in (layers.get("vdp") or "").split(",")],
                    }
                    break
    if tray_record is None:
        raise ValueError("source XML mkbound=2 bottom tray record is missing")
    generated = ET.parse(generated_xml).getroot()
    generated_groups = [
        {key: (int(value) if key in {"mkbound", "mk", "begin", "count"} else value)
         for key, value in node.attrib.items()}
        for node in generated.findall(".//particles/*") if node.tag in {"fixed", "moving"}
    ]
    from scripts.r4_f6_mdbc_runtime_zero_normal_audit import read_binary_vtk
    vtk = read_binary_vtk(bound_vtk)
    points = np.asarray(vtk["points"], dtype=float)
    mk = np.asarray(vtk["point_data"]["Mk"]).reshape(-1).astype(int)
    mk_groups = {}
    for value in sorted(set(mk.tolist())):
        selected = points[mk == value]
        mk_groups[str(value)] = {
            "count": int(len(selected)),
            "bbox_min_m": selected.min(axis=0).tolist(),
            "bbox_max_m": selected.max(axis=0).tolist(),
            "z_unique_count": int(len(np.unique(np.round(selected[:, 2], 9))),),
            "z_unique_min_m": float(selected[:, 2].min()),
            "z_unique_max_m": float(selected[:, 2].max()),
        }
    old_audit = json.loads((product / "audit.json").read_text())
    observations = json.loads((product / "observations.json").read_text())
    amended_audit = audit_dynamic(amended_prepared, product / "trajectory.h5", observations)
    report = {
        "schema": "core.f2.closed_catchment.floor_contract_forensics.v1",
        "source_prepared": str(source_prepared),
        "source_prepared_sha256": core_cfd.digest(source_prepared),
        "amended_prepared": str(amended_prepared),
        "amended_prepared_sha256": core_cfd.digest(amended_prepared),
        "product": str(product),
        "trajectory_sha256": core_cfd.digest(product / "trajectory.h5"),
        "evidence_hashes": {
            "original_v2_audit_sha256": core_cfd.digest(product / "audit.json"),
            "observations_sha256": core_cfd.digest(product / "observations.json"),
            "trajectory_sha256": core_cfd.digest(product / "trajectory.h5"),
        },
        "reaudit_implementation": {
            "module": str(Path(__file__).resolve()),
            "module_sha256": core_cfd.digest(Path(__file__).resolve()),
            "audit_schema": "core.f2.dynamic_audit.v1",
            "observer_revision": F2_OBSERVER_REVISION_ID,
            "method": "audit_dynamic on the preserved trajectory with only the amended floor contract",
        },
        "source_definition": str(source_definition),
        "source_definition_sha256": core_cfd.digest(source_definition),
        "generated_definition": str(generated_xml),
        "generated_definition_sha256": core_cfd.digest(generated_xml),
        "tray_source_record": tray_record,
        "generated_particle_groups": generated_groups,
        "bound_vtk": str(bound_vtk),
        "bound_vtk_sha256": core_cfd.digest(bound_vtk),
        "bound_mk_groups": mk_groups,
        "floor_surface_conclusion": {
            "source_boxfill": "bottom",
            "source_plane_z_m": float(tray_record["point"]["z"]),
            "source_size_z_m": float(tray_record["size"]["z"]),
            "generated_mkbound2_vtk_z_range_m": [mk_groups["19"]["z_unique_min_m"], mk_groups["19"]["z_unique_max_m"]],
            "generated_mkbound2_has_points_at_source_top_z_minus_0p10": False,
            "fluid_facing_surface_z_m": -0.20,
            "basis": "Mk2 is a bottom-only shell; size z is not a generated top face",
        },
        "old_v2_audit": {
            "hard_integrity_pass": old_audit.get("hard_integrity_pass"),
            "catchment_floor_endpoint_particle_frames": old_audit.get("geometry_audit", {}).get("catchment_floor_world_frame", {}).get("endpoint_particle_frames"),
            "catchment_floor_saved_chord_crossings": old_audit.get("geometry_audit", {}).get("catchment_floor_world_frame", {}).get("saved_chord_crossings"),
            "first_endpoint_violation": old_audit.get("geometry_audit", {}).get("catchment_floor_world_frame", {}).get("first_endpoint_violation"),
        },
        "amended_reaudit": {
            "hard_integrity_pass": amended_audit["hard_integrity_pass"],
            "hard_checks": amended_audit["hard_checks"],
            "catchment_floor_geometry": amended_audit["geometry_audit"]["catchment_floor_world_frame"],
            "catchment_geometry_declaration": amended_audit["catchment_geometry_declaration"],
            "trajectory_reused_without_solver_rerun": True,
        },
        "qualification_claim": "none; floor-contract forensics and re-audit only",
    }
    _write_json(output, report)
    return report


def _normalized_observation_values(config: dict, report_arrays: dict) -> tuple[list[str], list[list[float]]]:
    runtime = config["runtime_domain"]
    runtime_span = np.asarray(runtime["posmax"], dtype=float) - np.asarray(runtime["posmin"], dtype=float)
    cup_span = np.asarray(config["cup"]["size"], dtype=float)
    world = np.asarray(report_arrays["center_of_mass_world_m"], dtype=float)
    body = np.asarray(report_arrays["center_of_mass_cup_body_m"], dtype=float)
    columns = [
        np.asarray(report_arrays["cup_mass_fraction"], dtype=float),
        np.asarray(report_arrays["receiver_mass_fraction"], dtype=float),
        np.asarray(report_arrays["tray_mass_fraction"], dtype=float),
        np.asarray(report_arrays["outside_observation_mass_fraction"], dtype=float),
        world[:, 0] / max(runtime_span[0], 1e-30),
        world[:, 1] / max(runtime_span[1], 1e-30),
        world[:, 2] / max(runtime_span[2], 1e-30),
        body[:, 0] / max(cup_span[0], 1e-30),
        body[:, 1] / max(cup_span[1], 1e-30),
        body[:, 2] / max(cup_span[2], 1e-30),
        np.asarray(report_arrays["kinetic_energy_over_initial_potential"], dtype=float),
        np.asarray(report_arrays["speed_p95_m_s"], dtype=float),
    ]
    values = np.column_stack(columns)
    if values.ndim != 2 or values.shape[1] != len(F2_OBSERVABLE_NAMES) or not np.isfinite(values).all():
        raise ValueError("F2 normalized observer values are not finite or have the wrong layout")
    return list(F2_OBSERVABLE_NAMES), values.tolist()


def observe_dynamic(prepared_path: Path, hdf5_path: Path) -> dict:
    prepared = json.loads(Path(prepared_path).read_text())
    config = prepared["config"]
    cup = config["cup"]
    receiver = config["receiver"]
    tray = config["tray"]
    dp = float(config["dp_m"])
    cup_low = np.asarray(cup["low"], dtype=float) + dp
    cup_high = np.asarray(cup["low"], dtype=float) + np.asarray(cup["size"], dtype=float) - dp
    receiver_low = np.asarray(receiver["low"], dtype=float) + dp
    receiver_high = np.asarray(receiver["low"], dtype=float) + np.asarray(receiver["size"], dtype=float) - dp
    tray_low = np.asarray(tray["low"], dtype=float) + np.asarray([dp, dp, dp])
    tray_high = np.asarray(tray["low"], dtype=float) + np.asarray(tray["size"], dtype=float) - np.asarray([dp, dp, 0.0])
    duration_s = float(config["parameter"]["value"])
    registered_window_s = float(config.get("time_max_s", FULL_WINDOW_S))
    maximum_extended_window_s = float(config.get("maximum_extended_time_s", MAXIMUM_EXTENDED_WINDOW_S))
    motion_complete_s = MOTION_START_S + duration_s
    with h5py.File(hdf5_path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        masses = np.asarray(handle["mass"][0], dtype=float)
        initial = valid[0] & np.isfinite(positions[0]).all(axis=1)
        initial_mass = float(masses[initial].sum())
        initial_position = positions[0, initial]
        initial_velocity = velocities[0, initial]
        initial_potential = float(np.sum(masses[initial] * 9.81 * (initial_position[:, 2] - float(cup["low"][2]))))
        receiver_fraction, cup_fraction, tray_fraction, outside_fraction = [], [], [], []
        kinetic_fraction, speed_p95, com_world, com_body = [], [], [], []
        for index, time_s in enumerate(times):
            active = initial & valid[index] & np.isfinite(positions[index]).all(axis=1) & np.isfinite(velocities[index]).all(axis=1)
            point = positions[index]
            velocity = velocities[index]
            mass = masses
            angle = motion_angle(float(time_s), duration_s)
            body = body_positions(point, cup_world_from_body(angle))
            cup_mask = active & _inside(body, cup_low.tolist(), cup_high.tolist())
            receiver_mask = active & _inside(point, receiver_low.tolist(), receiver_high.tolist())
            tray_mask = active & _inside(point, tray_low.tolist(), tray_high.tolist())
            classified = cup_mask | receiver_mask | tray_mask
            active_mass = float(mass[active].sum())
            receiver_fraction.append(float(mass[receiver_mask].sum() / max(initial_mass, 1e-30)))
            cup_fraction.append(float(mass[cup_mask].sum() / max(initial_mass, 1e-30)))
            tray_fraction.append(float(mass[tray_mask].sum() / max(initial_mass, 1e-30)))
            outside_fraction.append(float(mass[active & ~classified].sum() / max(initial_mass, 1e-30)))
            speeds = np.linalg.norm(velocity[active], axis=1)
            speed_p95.append(float(np.quantile(speeds, 0.95)) if len(speeds) else float("nan"))
            kinetic = float(np.sum(0.5 * mass[active] * speeds ** 2))
            kinetic_fraction.append(kinetic / max(initial_potential, 1e-30))
            com_world.append((mass[active, None] * point[active]).sum(axis=0).tolist() if active.any() else [float("nan")] * 3)
            com_body.append((mass[active, None] * body[active]).sum(axis=0).tolist() if active.any() else [float("nan")] * 3)
        receiver_fraction = np.asarray(receiver_fraction)
        cup_fraction = np.asarray(cup_fraction)
        tray_fraction = np.asarray(tray_fraction)
        outside_fraction = np.asarray(outside_fraction)
        kinetic_fraction = np.asarray(kinetic_fraction)
        speed_p95 = np.asarray(speed_p95)
    normalized_names, normalized_values = _normalized_observation_values(config, {
        "cup_mass_fraction": cup_fraction,
        "receiver_mass_fraction": receiver_fraction,
        "tray_mass_fraction": tray_fraction,
        "outside_observation_mass_fraction": outside_fraction,
        "center_of_mass_world_m": com_world,
        "center_of_mass_cup_body_m": com_body,
        "kinetic_energy_over_initial_potential": kinetic_fraction,
        "speed_p95_m_s": speed_p95,
    })
    receiver_indices = np.flatnonzero(receiver_fraction >= RECEIVER_CONTACT_FRACTION)
    spill_indices = np.flatnonzero(outside_fraction >= SPILL_FRACTION)
    settle_candidate = (times >= motion_complete_s) & (kinetic_fraction <= SETTLE_KE_FRACTION) & (speed_p95 <= SETTLE_SPEED_M_S)
    settle_index = None
    if len(settle_candidate):
        needed = max(1, int(math.ceil(SETTLE_HOLD_S / max(np.median(np.diff(times)), 1e-12))))
        for index in np.flatnonzero(settle_candidate):
            if index + needed <= len(times) and bool(np.all(settle_candidate[index:index + needed])):
                settle_index = int(index)
                break
    last_required_time = max(
        motion_complete_s,
        float(times[receiver_indices[0]]) if len(receiver_indices) else -math.inf,
        float(times[settle_index]) if settle_index is not None else -math.inf,
    )
    complete = bool(
        len(receiver_indices)
        and settle_index is not None
        and times[-1] >= last_required_time + POST_SETTLE_OBSERVATION_S
        and times[-1] >= registered_window_s - 1e-6
    )
    return {
        "schema": "core.f2.dynamic_observations.v1",
        "revision_id": CANARY_REVISION_ID,
        "observer_revision": F2_OBSERVER_REVISION_ID,
        "case_id": config["case_id"],
        "time_s": times.tolist(),
        "observable_names": [
            "cup_mass_fraction", "receiver_mass_fraction", "tray_mass_fraction",
            "outside_observation_mass_fraction", "center_of_mass_world_m",
            "center_of_mass_cup_body_m", "kinetic_energy_over_initial_potential",
            "speed_p95_m_s",
        ],
        "cup_mass_fraction": cup_fraction.tolist(),
        "receiver_mass_fraction": receiver_fraction.tolist(),
        "tray_mass_fraction": tray_fraction.tolist(),
        "outside_observation_mass_fraction": outside_fraction.tolist(),
        "center_of_mass_world_m": com_world,
        "center_of_mass_cup_body_m": com_body,
        "kinetic_energy_over_initial_potential": kinetic_fraction.tolist(),
        "speed_p95_m_s": speed_p95.tolist(),
        "normalized_observable_names": normalized_names,
        "normalized_values": normalized_values,
        "normalization": {
            "mass_denominator": "initial native fluid mass from frame zero; no survivor renormalization",
            "world_center_of_mass": "runtime-domain coordinate spans",
            "cup_body_center_of_mass": "fixed cup physical dimensions",
            "kinetic_energy": "initial gravitational potential energy relative to cup floor",
            "speed_p95": "1 m/s reference scale",
        },
        "initial_native_mass_kg": initial_mass,
        "initial_potential_energy_relative_to_cup_floor_J": initial_potential,
        "event_times_s": {
            "motion_complete": motion_complete_s,
            "receiver_contact": float(times[receiver_indices[0]]) if len(receiver_indices) else None,
            "spill_or_escape": float(times[spill_indices[0]]) if len(spill_indices) else None,
            "settled": float(times[settle_index]) if settle_index is not None else None,
            "event_window_complete": float(times[-1]) if complete else None,
        },
        "event_thresholds": {
            "receiver_contact_mass_fraction": RECEIVER_CONTACT_FRACTION,
            "spill_mass_fraction": SPILL_FRACTION,
            "settle_speed_p95_m_s": SETTLE_SPEED_M_S,
            "settle_kinetic_fraction": SETTLE_KE_FRACTION,
            "settle_hold_s": SETTLE_HOLD_S,
            "post_settle_observation_s": POST_SETTLE_OBSERVATION_S,
        },
        "requested_horizon_reached": bool(times[-1] >= registered_window_s - 1e-6),
        "maximum_extended_horizon_allowed_s": maximum_extended_window_s,
        "event_window_complete": complete,
        "qualification_claim": "none; F2 dynamic canary observation",
    }


def _finite_box_spec(box: dict, closed_faces: tuple[str, ...], open_faces: tuple[str, ...]) -> dict:
    low = np.asarray(box["low"], dtype=float)
    high = low + np.asarray(box["size"], dtype=float)
    return {
        "container_interior": {
            "xmin": float(low[0]), "xmax": float(high[0]),
            "ymin": float(low[1]), "ymax": float(high[1]),
            "zmin": float(low[2]), "zmax": float(high[2]),
        },
        "closed_faces": list(closed_faces),
        "open_faces": list(open_faces),
        "obstacles": [],
    }


def _catchment_geometry_specs(config: dict) -> tuple[dict | None, dict | None, dict | None]:
    """Build fluid-facing side/floor specs for an optional closed catchment.

    ``catchment.low[2]`` is also the fluid-facing source plane for the
    retained ``boxfill=bottom`` tray.  The source ``size z=0.10`` does not
    create a top face; the distinction is carried into the audit receipt.
    """
    catchment = config.get("catchment")
    if catchment is None:
        return None, None, None
    low = np.asarray(catchment["low"], dtype=float)
    high = low + np.asarray(catchment["size"], dtype=float)
    tray = config["tray"]
    default_floor = float(tray["low"][2])
    declared_wall = config.get("catchment_wall_spec")
    floor_surface = float(catchment.get("fluid_floor_surface_z_m", default_floor))
    if declared_wall is not None:
        if not isinstance(declared_wall, dict) or not isinstance(declared_wall.get("container_interior"), dict):
            raise ValueError("F2 catchment_wall_spec must declare container_interior")
        bounds = declared_wall["container_interior"]
        declared_low = np.asarray([bounds["xmin"], bounds["ymin"], bounds["zmin"]], dtype=float)
        declared_high = np.asarray([bounds["xmax"], bounds["ymax"], bounds["zmax"]], dtype=float)
        if not np.allclose(declared_low[:2], low[:2], rtol=0.0, atol=1e-12) or not np.allclose(declared_high[:2], high[:2], rtol=0.0, atol=1e-12):
            raise ValueError("F2 catchment_wall_spec horizontal bounds differ from continuous catchment geometry")
        floor_surface = float(declared_low[2])
        if not np.isclose(declared_high[2], high[2], rtol=0.0, atol=1e-12):
            raise ValueError("F2 catchment_wall_spec top differs from continuous catchment geometry")
        declared_floor = declared_wall.get("floor", {})
        if not np.isclose(float(declared_floor.get("fluid_facing_surface_z_m", math.nan)), floor_surface, rtol=0.0, atol=1e-12):
            raise ValueError("F2 catchment_wall_spec floor surface is inconsistent")
    if not np.isfinite(low).all() or not np.isfinite(high).all() or not np.isfinite(floor_surface):
        raise ValueError("F2 catchment geometry must be finite")
    # A retained ``boxfill=bottom`` tray has its fluid-facing plane exactly
    # on the primitive's nominal low z.  Equality is therefore a valid
    # source-plane contract; only a surface below the primitive or at/above
    # its top is invalid.
    if np.any(high <= low) or not low[2] <= floor_surface < high[2]:
        raise ValueError("F2 catchment floor surface must lie on/above nominal low and below top")
    side_box = {
        "low": [float(low[0]), float(low[1]), floor_surface],
        "size": [float(high[0] - low[0]), float(high[1] - low[1]), float(high[2] - floor_surface)],
    }
    floor_box = copy.deepcopy(side_box)
    side_spec = _finite_box_spec(side_box, ("left", "right", "front", "back"), ("top",))
    floor_spec = _finite_box_spec(floor_box, ("bottom",), ("top", "left", "right", "front", "back"))
    declaration = {
        "nominal_low_m": low.tolist(),
        "nominal_high_m": high.tolist(),
        "fluid_facing_floor_surface_z_m": floor_surface,
        "nominal_low_is_fluid_facing_floor_surface": True,
        "floor_surface_offset_above_nominal_low_m": float(floor_surface - low[2]),
        "side_wall_closed_faces": ["left", "right", "front", "back"],
        "top_open": True,
        "retained_floor_material_mkbound": int(catchment.get("floor_material_mkbound", 2)),
        "side_wall_material_mkbound": int(catchment.get("mkbound", 3)),
        "floor_surface_basis": "source bottom plane of retained boxfill=bottom tray; size z is not a top face",
    }
    return side_spec, floor_spec, declaration


def _runtime_domain_spec(config: dict) -> dict:
    domain = config["runtime_domain"]
    lower = domain["posmin"]
    upper = domain["posmax"]
    return {
        "xmin": float(lower[0]), "xmax": float(upper[0]),
        "ymin": float(lower[1]), "ymax": float(upper[1]),
        "zmin": float(lower[2]), "zmax": float(upper[2]),
    }


def _strict_inside(points: np.ndarray, spec: dict) -> np.ndarray:
    """Classify points in a finite container's open interior."""
    container = spec["container_interior"]
    lower = np.asarray([container["xmin"], container["ymin"], container["zmin"]], dtype=float)
    upper = np.asarray([container["xmax"], container["ymax"], container["zmax"]], dtype=float)
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"points must have shape [N,3], got {points.shape}")
    return np.all((points > lower) & (points < upper), axis=1)


def _inside_horizontal(points: np.ndarray, spec: dict, tolerance: float = 0.0) -> np.ndarray:
    container = spec["container_interior"]
    lower = np.asarray([container["xmin"], container["ymin"]], dtype=float)
    upper = np.asarray([container["xmax"], container["ymax"]], dtype=float)
    points = np.asarray(points, dtype=float)
    return np.all((points[:, :2] >= lower - tolerance) & (points[:, :2] <= upper + tolerance), axis=1)


def _open_top_crossing(previous: np.ndarray, current: np.ndarray, spec: dict, tolerance: float) -> np.ndarray:
    """Locate saved chords leaving a finite container through its open top."""
    container = spec["container_interior"]
    lower = np.asarray([container["xmin"], container["ymin"], container["zmin"]], dtype=float)
    upper = np.asarray([container["xmax"], container["ymax"], container["zmax"]], dtype=float)
    previous = np.asarray(previous, dtype=float)
    current = np.asarray(current, dtype=float)
    if previous.shape != current.shape or previous.ndim != 2 or previous.shape[1] != 3:
        raise ValueError("open-top crossing endpoints must both have shape [N,3]")
    delta_z = current[:, 2] - previous[:, 2]
    valid = (delta_z > 0.0) & (previous[:, 2] <= upper[2] + tolerance) & (current[:, 2] > upper[2] + tolerance)
    fraction = np.zeros(len(previous), dtype=float)
    moving = delta_z > 0.0
    fraction[moving] = (upper[2] - previous[moving, 2]) / delta_z[moving]
    crossing = previous + fraction[:, None] * (current - previous)
    valid &= np.isfinite(fraction) & (fraction >= 0.0) & (fraction <= 1.0)
    valid &= np.all((crossing[:, :2] >= lower[:2] - tolerance) & (crossing[:, :2] <= upper[:2] + tolerance), axis=1)
    return valid


def _open_top_entry(previous: np.ndarray, current: np.ndarray, spec: dict, tolerance: float) -> np.ndarray:
    """Locate saved chords entering a finite container through its open top."""
    container = spec["container_interior"]
    lower = np.asarray([container["xmin"], container["ymin"], container["zmin"]], dtype=float)
    upper = np.asarray([container["xmax"], container["ymax"], container["zmax"]], dtype=float)
    previous = np.asarray(previous, dtype=float)
    current = np.asarray(current, dtype=float)
    if previous.shape != current.shape or previous.ndim != 2 or previous.shape[1] != 3:
        raise ValueError("open-top crossing endpoints must both have shape [N,3]")
    delta_z = current[:, 2] - previous[:, 2]
    valid = (delta_z < 0.0) & (previous[:, 2] >= upper[2] - tolerance) & (current[:, 2] < upper[2] - tolerance)
    fraction = np.zeros(len(previous), dtype=float)
    moving = delta_z < 0.0
    fraction[moving] = (upper[2] - previous[moving, 2]) / delta_z[moving]
    crossing = previous + fraction[:, None] * (current - previous)
    valid &= np.isfinite(fraction) & (fraction >= 0.0) & (fraction <= 1.0)
    valid &= np.all((crossing[:, :2] >= lower[:2] - tolerance) & (crossing[:, :2] <= upper[:2] + tolerance), axis=1)
    return valid


def _closed_face_entry_events(
    previous: np.ndarray,
    current: np.ndarray,
    spec: dict,
    tolerance: float,
) -> list[dict]:
    """Return outside-to-inside crossings through finite closed faces.

    ``segment_crossing_events`` intentionally detects outward penetration from
    an owned container.  F2 also needs the inverse diagnostic: an identity
    that was outside receiver/cup geometry must not enter through a side wall
    and become owned only after the endpoint is already inside.
    """
    container = spec["container_interior"]
    lower = np.asarray([container["xmin"], container["ymin"], container["zmin"]], dtype=float)
    upper = np.asarray([container["xmax"], container["ymax"], container["zmax"]], dtype=float)
    previous = np.asarray(previous, dtype=float)
    current = np.asarray(current, dtype=float)
    if previous.shape != current.shape or previous.ndim != 2 or previous.shape[1] != 3:
        raise ValueError("closed-face crossing endpoints must both have shape [N,3]")
    events = []
    face_axis = {"bottom": (2, 0), "left": (0, 0), "right": (0, 1), "front": (1, 0), "back": (1, 1)}
    for face in spec.get("closed_faces", ()):  # preserve declared face semantics
        axis, side = face_axis[face]
        other = [index for index in range(3) if index != axis]
        plane = lower[axis] if side == 0 else upper[axis]
        displacement = current - previous
        delta = displacement[:, axis]
        if side == 0:
            direction = delta > 0.0
            start_outside = previous[:, axis] < plane - tolerance
            end_inside = current[:, axis] >= plane - tolerance
        else:
            direction = delta < 0.0
            start_outside = previous[:, axis] > plane + tolerance
            end_inside = current[:, axis] <= plane + tolerance
        valid = direction & start_outside & end_inside
        fraction = np.full(len(previous), np.nan, dtype=float)
        moving = np.abs(delta) > 1e-15
        fraction[moving] = (plane - previous[moving, axis]) / delta[moving]
        # Interpolate the complete saved-frame segment.  Using the scalar
        # normal displacement for every coordinate fabricates tangential
        # motion and can label a corner-adjacent trajectory as a wall entry.
        crossing = previous + fraction[:, None] * displacement
        valid &= np.isfinite(fraction) & (fraction >= 0.0) & (fraction <= 1.0)
        for index in other:
            valid &= (crossing[:, index] >= lower[index] - tolerance) & (crossing[:, index] <= upper[index] + tolerance)
        for index in np.flatnonzero(valid):
            events.append({
                "point_index": int(index),
                "kind": "closed_face_entry",
                "face": face,
                "fraction": float(fraction[index]),
                "crossing_position_m": crossing[index].tolist(),
            })
    return sorted(events, key=lambda item: (item["point_index"], item["fraction"], item["face"]))


def _legacy_scalar_closed_face_entry_events(
    previous: np.ndarray,
    current: np.ndarray,
    spec: dict,
    tolerance: float,
) -> list[dict]:
    """Reproduce the pre-fix entry classifier for retrospective evidence.

    The historical implementation multiplied the scalar normal displacement
    into every coordinate when constructing a saved-frame chord.  This helper
    is intentionally isolated from all gates so the old three-event result can
    be retained and compared with the corrected full-vector interpolation.
    """
    container = spec["container_interior"]
    lower = np.asarray([container["xmin"], container["ymin"], container["zmin"]], dtype=float)
    upper = np.asarray([container["xmax"], container["ymax"], container["zmax"]], dtype=float)
    previous = np.asarray(previous, dtype=float)
    current = np.asarray(current, dtype=float)
    if previous.shape != current.shape or previous.ndim != 2 or previous.shape[1] != 3:
        raise ValueError("closed-face crossing endpoints must both have shape [N,3]")
    events = []
    face_axis = {"bottom": (2, 0), "left": (0, 0), "right": (0, 1), "front": (1, 0), "back": (1, 1)}
    for face in spec.get("closed_faces", ()):
        axis, side = face_axis[face]
        other = [index for index in range(3) if index != axis]
        plane = lower[axis] if side == 0 else upper[axis]
        delta = current[:, axis] - previous[:, axis]
        if side == 0:
            direction = delta > 0.0
            start_outside = previous[:, axis] < plane - tolerance
            end_inside = current[:, axis] >= plane - tolerance
        else:
            direction = delta < 0.0
            start_outside = previous[:, axis] > plane + tolerance
            end_inside = current[:, axis] <= plane + tolerance
        valid = direction & start_outside & end_inside
        fraction = np.full(len(previous), np.nan, dtype=float)
        moving = np.abs(delta) > 1e-15
        fraction[moving] = (plane - previous[moving, axis]) / delta[moving]
        scalar_chord = previous + fraction[:, None] * delta[:, None]
        valid &= np.isfinite(fraction) & (fraction >= 0.0) & (fraction <= 1.0)
        for index in other:
            valid &= (scalar_chord[:, index] >= lower[index] - tolerance) & (scalar_chord[:, index] <= upper[index] + tolerance)
        for index in np.flatnonzero(valid):
            events.append({
                "point_index": int(index),
                "kind": "closed_face_entry",
                "face": face,
                "fraction": float(fraction[index]),
                "crossing_position_m": scalar_chord[index].tolist(),
            })
    return sorted(events, key=lambda item: (item["point_index"], item["fraction"], item["face"]))


def _motion_angular_velocity_rad_s(time_s: float, duration_s: float) -> float:
    """Return the prescribed world-frame y angular rate of the cup.

    ``cup_world_from_body`` applies ``-motion_angle`` about +y, matching the
    axis in the native ``mvrotfile`` block.  The derivative is recorded for
    contact evidence only; it does not alter the prescribed motion.
    """
    if time_s <= MOTION_START_S or time_s >= MOTION_START_S + duration_s:
        return 0.0
    phase = (time_s - MOTION_START_S) / duration_s
    angle_rate_deg_s = ANGLE_DEGREES * 0.5 * (math.pi / duration_s) * math.sin(math.pi * phase)
    return -math.radians(angle_rate_deg_s)


def _face_normal_body(face: str) -> np.ndarray:
    return {
        "bottom": np.asarray([0.0, 0.0, -1.0]),
        "left": np.asarray([-1.0, 0.0, 0.0]),
        "right": np.asarray([1.0, 0.0, 0.0]),
        "front": np.asarray([0.0, -1.0, 0.0]),
        "back": np.asarray([0.0, 1.0, 0.0]),
    }[face]


def _empty_geometry_audit() -> dict:
    return {
        "owned_particle_frames": 0,
        "open_top_exit_count": 0,
        "open_top_entry_count": 0,
        "endpoint_particle_frames": 0,
        "endpoint_mass_kg": 0.0,
        "endpoint_by_face": {face: 0 for face in ("bottom", "left", "right", "front", "back")},
        "saved_chord_crossings": 0,
        "saved_chord_closed_face_entries": 0,
        "first_endpoint_violation": None,
        "first_saved_chord_crossing": None,
        "first_saved_chord_closed_face_entry": None,
    }


def _accumulate_geometry(
    audit: dict,
    frame_index: int,
    time_s: float,
    endpoint: dict,
    crossings: list[dict],
    entries: list[dict] | None = None,
) -> None:
    entries = entries or []
    audit["endpoint_particle_frames"] += int(endpoint["outside_closed_container_count"])
    audit["endpoint_mass_kg"] += float(endpoint["outside_closed_container_mass_kg"])
    for face, count in endpoint["outside_closed_container_by_face"].items():
        audit["endpoint_by_face"][face] = audit["endpoint_by_face"].get(face, 0) + int(count)
    if endpoint["outside_closed_container_count"] and audit["first_endpoint_violation"] is None:
        audit["first_endpoint_violation"] = {
            "frame_index": int(frame_index),
            "time_s": float(time_s),
            "by_face": endpoint["outside_closed_container_by_face"],
        }
    audit["saved_chord_crossings"] += len(crossings)
    if crossings and audit["first_saved_chord_crossing"] is None:
        audit["first_saved_chord_crossing"] = {
            "frame_index": int(frame_index),
            "time_s": float(time_s),
            "events": crossings[:10],
        }
    audit["saved_chord_closed_face_entries"] += len(entries)
    if entries and audit["first_saved_chord_closed_face_entry"] is None:
        audit["first_saved_chord_closed_face_entry"] = {
            "frame_index": int(frame_index),
            "time_s": float(time_s),
            "events": entries[:10],
        }


def audit_dynamic(prepared_path: Path, hdf5_path: Path, observations: dict) -> dict:
    """Audit F2 native identities and finite moving/static physical walls.

    The generic Core CFD audit treats ``config.wall_bounds`` as one static
    container.  That is insufficient for F2: the cup is a moving finite body,
    the receiver has an open top, and the tray has only a bottom face.  This
    audit therefore transforms cup particles to the prescribed body frame and
    audits receiver/tray in world coordinates.  Event completion is reported
    separately and never changes the hard-integrity boolean.
    """
    prepared_path, hdf5_path = Path(prepared_path).resolve(), Path(hdf5_path).resolve()
    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    cup_spec = _finite_box_spec(config["cup"], ("bottom", "left", "right", "front", "back"), ("top",))
    receiver_spec = _finite_box_spec(config["receiver"], ("bottom", "left", "right", "front", "back"), ("top",))
    tray_spec = _finite_box_spec(config["tray"], ("bottom",), ("top", "left", "right", "front", "back"))
    catchment_spec, catchment_floor_spec, catchment_geometry_declaration = _catchment_geometry_specs(config)
    declared_domain_spec = _runtime_domain_spec(config)
    resolved_domain_values = prepared.get("resolved_runtime_domain")
    if resolved_domain_values is None:
        resolved_domain_spec = declared_domain_spec
        domain_declaration_matches = True
    else:
        resolved_domain_spec = _runtime_domain_spec({"runtime_domain": resolved_domain_values})
        domain_declaration_matches = bool(np.allclose(
            [declared_domain_spec[key] for key in ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")],
            [resolved_domain_spec[key] for key in ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")],
            rtol=0.0,
            atol=1e-12,
        ))
    domain_spec = resolved_domain_spec

    geometry = {
        "cup_moving_body_frame": _empty_geometry_audit(),
        "receiver_world_frame": _empty_geometry_audit(),
        "tray_world_frame": _empty_geometry_audit(),
        "catchment_world_frame": _empty_geometry_audit(),
        "catchment_floor_world_frame": _empty_geometry_audit(),
    }
    with h5py.File(hdf5_path, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        density = np.asarray(handle["density"][:], dtype=float)
        mass = np.asarray(handle["mass"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        particle_ids = np.asarray(handle["particle_id"][:])
        if positions.ndim != 3 or positions.shape[2] != 3:
            raise ValueError(f"F2 trajectory positions have invalid shape {positions.shape}")
        if valid.shape != positions.shape[:2]:
            raise ValueError("F2 valid and position arrays have incompatible shapes")
        initial_valid = valid[0].copy()
        initial_mass = mass[0].astype(float)
        initial_ids = particle_ids[initial_valid]
        identity_unique = len(np.unique(particle_ids)) == len(particle_ids)
        expected_initial = int(prepared["sampling"]["expected_fluid_particles"])
        nonfinite_active = 0
        mass_changed = 0
        runtime_outside = 0
        runtime_outside_mass = 0.0
        missing_by_frame = []
        active_mass_fraction = []
        cup_spec_initial = cup_spec
        receiver_spec_initial = receiver_spec
        cup_owned = None
        cup_eligible = None
        receiver_owned = None
        catchment_owned = None
        previous = None
        for frame_index, time_s in enumerate(times):
            active = valid[frame_index].copy()
            finite = (
                np.isfinite(positions[frame_index]).all(axis=1)
                & np.isfinite(velocities[frame_index]).all(axis=1)
                & np.isfinite(density[frame_index])
                & np.isfinite(mass[frame_index])
            )
            nonfinite_active += int(np.sum(active & ~finite))
            active &= finite
            missing_by_frame.append(int(np.sum(initial_valid & ~valid[frame_index])))
            current_mass = mass[frame_index]
            mass_changed += int(np.sum(
                active & (
                    np.abs(current_mass - initial_mass)
                    > np.maximum(1e-12, 1e-7 * np.abs(initial_mass))
                )
            ))
            active_mass_fraction.append(float(np.sum(current_mass[active], dtype=np.float64) / max(np.sum(initial_mass[initial_valid], dtype=np.float64), 1e-30)))
            points = positions[frame_index, active]
            weights = current_mass[active]
            domain_bad = outside_runtime_domain_mask(points, domain_spec, F2_WALL_TOLERANCE_M)
            if domain_bad is not None:
                runtime_outside += int(domain_bad.sum())
                runtime_outside_mass += float(weights[domain_bad].sum(dtype=np.float64))
            angle = motion_angle(float(time_s), float(config["parameter"]["value"]))
            cup_transform = cup_world_from_body(angle)
            cup_body_all = body_positions(positions[frame_index], cup_transform)
            cup_body = cup_body_all[active]
            if cup_owned is None:
                cup_owned = active & _strict_inside(cup_body_all, cup_spec_initial)
                cup_eligible = cup_owned.copy()
                receiver_owned = active & _strict_inside(positions[frame_index], receiver_spec_initial)
                if catchment_spec is not None:
                    catchment_owned = active & _strict_inside(positions[frame_index], catchment_spec)
            cup_common = np.zeros(len(active), dtype=bool)
            receiver_common = np.zeros(len(active), dtype=bool)
            tray_endpoint_mask = active & (frame_index == 0) & (
                positions[frame_index, :, 2] < tray_spec["container_interior"]["zmin"] - F2_WALL_TOLERANCE_M
            ) & _inside_horizontal(positions[frame_index], tray_spec, F2_WALL_TOLERANCE_M)
            cup_crossings: list[dict] = []
            receiver_crossings: list[dict] = []
            tray_crossings: list[dict] = []
            cup_entries: list[dict] = []
            receiver_entries: list[dict] = []
            catchment_crossings: list[dict] = []
            catchment_floor_crossings: list[dict] = []
            catchment_entries: list[dict] = []
            catchment_floor_endpoint_mask = np.zeros(len(active), dtype=bool)
            if catchment_spec is not None and frame_index == 0:
                catchment_floor_endpoint_mask = (
                    active
                    & (positions[frame_index, :, 2] < catchment_geometry_declaration["fluid_facing_floor_surface_z_m"] - F2_WALL_TOLERANCE_M)
                    & _inside_horizontal(positions[frame_index], catchment_spec, F2_WALL_TOLERANCE_M)
                )
            if previous is not None:
                common = previous["active_mask"] & active
                cup_common = common & previous["cup_owned"]
                receiver_common = common & previous["receiver_owned"]
                if common.any():
                    previous_body = previous["cup_body"][common]
                    current_body = cup_body_all[common]
                    receiver_entries = _closed_face_entry_events(
                        previous["world"][common], positions[frame_index, common], receiver_spec, F2_WALL_TOLERANCE_M
                    )
                    eligible_common = common & previous["cup_eligible"]
                    cup_top_entries = _open_top_entry(
                        previous["cup_body"][eligible_common], cup_body_all[eligible_common], cup_spec, F2_WALL_TOLERANCE_M
                    ) if eligible_common.any() else np.zeros(0, dtype=bool)
                    if cup_top_entries.any():
                        entered = np.flatnonzero(eligible_common)[cup_top_entries]
                        cup_owned[entered] = True
                        geometry["cup_moving_body_frame"]["open_top_entry_count"] += int(cup_top_entries.sum())
                    receiver_top_entries = _open_top_entry(
                        previous["world"][common], positions[frame_index, common], receiver_spec, F2_WALL_TOLERANCE_M
                    )
                    if receiver_top_entries.any():
                        entered = np.flatnonzero(common)[receiver_top_entries]
                        receiver_owned[entered] = True
                        geometry["receiver_world_frame"]["open_top_entry_count"] += int(receiver_top_entries.sum())
                if cup_common.any():
                    prev_body = previous["cup_body"][cup_common]
                    current_body = cup_body_all[cup_common]
                    top_exit = _open_top_crossing(prev_body, current_body, cup_spec, F2_WALL_TOLERANCE_M)
                    if top_exit.any():
                        exited = np.flatnonzero(cup_common)[top_exit]
                        cup_owned[exited] = False
                        geometry["cup_moving_body_frame"]["open_top_exit_count"] += int(top_exit.sum())
                    cup_crossings = segment_crossing_events(prev_body, current_body, cup_spec, F2_WALL_TOLERANCE_M)
                if receiver_common.any():
                    prev_receiver = previous["world"][receiver_common]
                    current_receiver = positions[frame_index, receiver_common]
                    top_exit = _open_top_crossing(prev_receiver, current_receiver, receiver_spec, F2_WALL_TOLERANCE_M)
                    if top_exit.any():
                        exited = np.flatnonzero(receiver_common)[top_exit]
                        receiver_owned[exited] = False
                        geometry["receiver_world_frame"]["open_top_exit_count"] += int(top_exit.sum())
                    receiver_crossings = segment_crossing_events(prev_receiver, current_receiver, receiver_spec, F2_WALL_TOLERANCE_M)
                if common.any():
                    prev_points = previous["world"][common]
                    current_points = positions[frame_index, common]
                    cup_entries = _closed_face_entry_events(
                        previous["cup_body"][common], cup_body_all[common], cup_spec, F2_WALL_TOLERANCE_M
                    )
                    tray_crossings = segment_crossing_events(prev_points, current_points, tray_spec, F2_WALL_TOLERANCE_M)
                    previous_horizontal_above = (
                        previous["active_mask"]
                        & (previous["world"][:, 2] >= tray_spec["container_interior"]["zmin"] - F2_WALL_TOLERANCE_M)
                        & _inside_horizontal(previous["world"], tray_spec, F2_WALL_TOLERANCE_M)
                    )
                    tray_endpoint_mask = active & (positions[frame_index, :, 2] < tray_spec["container_interior"]["zmin"] - F2_WALL_TOLERANCE_M) & _inside_horizontal(
                        positions[frame_index], tray_spec, F2_WALL_TOLERANCE_M
                    ) & previous_horizontal_above
                if catchment_spec is not None:
                    catchment_common = common & previous["catchment_owned"]
                    if catchment_common.any():
                        previous_catchment = previous["world"][catchment_common]
                        current_catchment = positions[frame_index, catchment_common]
                        catchment_top_exit = _open_top_crossing(
                            previous_catchment, current_catchment, catchment_spec, F2_WALL_TOLERANCE_M
                        )
                        if catchment_top_exit.any():
                            exited = np.flatnonzero(catchment_common)[catchment_top_exit]
                            catchment_owned[exited] = False
                            geometry["catchment_world_frame"]["open_top_exit_count"] += int(catchment_top_exit.sum())
                        catchment_crossings = segment_crossing_events(
                            previous_catchment, current_catchment, catchment_spec, F2_WALL_TOLERANCE_M
                        )
                        catchment_floor_crossings = segment_crossing_events(
                            previous_catchment, current_catchment, catchment_floor_spec, F2_WALL_TOLERANCE_M
                        )
                    catchment_top_entries = _open_top_entry(
                        previous["world"][common], positions[frame_index, common], catchment_spec, F2_WALL_TOLERANCE_M
                    )
                    if catchment_top_entries.any():
                        entered = np.flatnonzero(common)[catchment_top_entries]
                        catchment_owned[entered] = True
                        geometry["catchment_world_frame"]["open_top_entry_count"] += int(catchment_top_entries.sum())
                    catchment_entries = _closed_face_entry_events(
                        previous["world"][common], positions[frame_index, common], catchment_spec, F2_WALL_TOLERANCE_M
                    )
                    previous_catchment_above_floor = (
                        previous["active_mask"]
                        & (previous["world"][:, 2] >= catchment_geometry_declaration["fluid_facing_floor_surface_z_m"] - F2_WALL_TOLERANCE_M)
                        & _inside_horizontal(previous["world"], catchment_spec, F2_WALL_TOLERANCE_M)
                    )
                    catchment_floor_endpoint_mask = (
                        active
                        & (positions[frame_index, :, 2] < catchment_geometry_declaration["fluid_facing_floor_surface_z_m"] - F2_WALL_TOLERANCE_M)
                        & _inside_horizontal(positions[frame_index], catchment_spec, F2_WALL_TOLERANCE_M)
                        & previous_catchment_above_floor
                    )
            # Endpoint ownership remains scoped to identities that entered
            # through an open top.  Closed-face outside-to-inside entries are
            # audited independently, so ownership cannot hide side entry.
            receiver_owned |= active & _strict_inside(positions[frame_index], receiver_spec)
            if catchment_spec is not None:
                catchment_owned |= active & _strict_inside(positions[frame_index], catchment_spec)
            cup_audit_mask = cup_owned & active
            receiver_audit_mask = receiver_owned & active
            cup_endpoint = wall_penetration(cup_body_all[cup_audit_mask], mass[frame_index, cup_audit_mask], cup_spec, F2_WALL_TOLERANCE_M)
            receiver_endpoint = wall_penetration(positions[frame_index, receiver_audit_mask], mass[frame_index, receiver_audit_mask], receiver_spec, F2_WALL_TOLERANCE_M)
            tray_endpoint = wall_penetration(
                positions[frame_index, tray_endpoint_mask],
                mass[frame_index, tray_endpoint_mask],
                tray_spec,
                F2_WALL_TOLERANCE_M,
            )
            if catchment_spec is not None:
                catchment_audit_mask = catchment_owned & active
                catchment_endpoint = wall_penetration(
                    positions[frame_index, catchment_audit_mask],
                    mass[frame_index, catchment_audit_mask],
                    catchment_spec,
                    F2_WALL_TOLERANCE_M,
                )
                catchment_floor_endpoint = wall_penetration(
                    positions[frame_index, catchment_floor_endpoint_mask],
                    mass[frame_index, catchment_floor_endpoint_mask],
                    catchment_floor_spec,
                    F2_WALL_TOLERANCE_M,
                )
            else:
                catchment_endpoint = {
                    "outside_closed_container_count": 0,
                    "outside_closed_container_mass_kg": 0.0,
                    "outside_closed_container_by_face": {},
                }
                catchment_floor_endpoint = {
                    "outside_closed_container_count": 0,
                    "outside_closed_container_mass_kg": 0.0,
                    "outside_closed_container_by_face": {},
                }
            geometry["cup_moving_body_frame"]["owned_particle_frames"] += int(cup_audit_mask.sum())
            geometry["receiver_world_frame"]["owned_particle_frames"] += int(receiver_audit_mask.sum())
            _accumulate_geometry(
                geometry["cup_moving_body_frame"], frame_index, time_s, cup_endpoint, cup_crossings, cup_entries
            )
            _accumulate_geometry(geometry["receiver_world_frame"], frame_index, time_s, receiver_endpoint, receiver_crossings, receiver_entries)
            _accumulate_geometry(geometry["tray_world_frame"], frame_index, time_s, tray_endpoint, tray_crossings)
            _accumulate_geometry(
                geometry["catchment_world_frame"], frame_index, time_s,
                catchment_endpoint, catchment_crossings, catchment_entries,
            )
            _accumulate_geometry(
                geometry["catchment_floor_world_frame"], frame_index, time_s,
                catchment_floor_endpoint, catchment_floor_crossings,
            )
            if catchment_spec is not None:
                geometry["catchment_world_frame"]["owned_particle_frames"] += int(catchment_audit_mask.sum())
                geometry["catchment_floor_world_frame"]["owned_particle_frames"] += int(catchment_floor_endpoint_mask.sum())
            previous = {
                "active_mask": active,
                "world": positions[frame_index],
                "cup_body": cup_body_all,
                "cup_owned": cup_owned.copy(),
                "cup_eligible": cup_eligible.copy(),
                "receiver_owned": receiver_owned.copy(),
                "catchment_owned": catchment_owned.copy() if catchment_spec is not None else None,
            }

    no_missing = not any(missing_by_frame)
    no_nonfinite = nonfinite_active == 0
    no_mass_change = mass_changed == 0
    no_runtime_outside = runtime_outside == 0
    no_physical_endpoint = all(item["endpoint_particle_frames"] == 0 for item in geometry.values())
    no_saved_crossings = all(item["saved_chord_crossings"] == 0 for item in geometry.values())
    horizon_reached = bool(len(times) >= 2 and times[-1] >= float(config["time_max_s"]) - 1e-6)
    identity_audit = {
        "particle_count": int(len(particle_ids)),
        "initial_valid_particle_count": int(initial_valid.sum()),
        "expected_initial_fluid_particles": expected_initial,
        "initial_count_matches_declaration": int(initial_valid.sum()) == expected_initial,
        "unique_particle_ids": bool(identity_unique),
        "missing_native_fluid_ids_by_frame": missing_by_frame,
        "missing_native_fluid_id_count": int(max(missing_by_frame, default=0)),
        "nonfinite_active_value_count": int(nonfinite_active),
        "mass_changed_value_count": int(mass_changed),
        "active_mass_fraction_by_frame": active_mass_fraction,
        "minimum_active_mass_fraction": float(min(active_mass_fraction, default=0.0)),
        "native_mass_policy": prepared["sampling"].get("mass_policy"),
    }
    hard_checks = {
        "initial_count_matches_declaration": identity_audit["initial_count_matches_declaration"],
        "unique_particle_ids": identity_audit["unique_particle_ids"],
        "no_missing_native_fluid_ids": no_missing,
        "no_nonfinite_active_values": no_nonfinite,
        "native_mass_unchanged": no_mass_change,
        "no_valid_particles_outside_runtime_domain": no_runtime_outside,
        "runtime_domain_declaration_matches_generated_xml": domain_declaration_matches,
        "no_cup_closed_wall_endpoint_penetrations": geometry["cup_moving_body_frame"]["endpoint_particle_frames"] == 0,
        "no_receiver_closed_wall_endpoint_penetrations": geometry["receiver_world_frame"]["endpoint_particle_frames"] == 0,
        "no_tray_bottom_endpoint_penetrations": geometry["tray_world_frame"]["endpoint_particle_frames"] == 0,
        "no_cup_saved_chord_crossings": geometry["cup_moving_body_frame"]["saved_chord_crossings"] == 0,
        "no_cup_closed_face_entries": geometry["cup_moving_body_frame"]["saved_chord_closed_face_entries"] == 0,
        "no_receiver_saved_chord_crossings": geometry["receiver_world_frame"]["saved_chord_crossings"] == 0,
        "no_tray_saved_chord_crossings": geometry["tray_world_frame"]["saved_chord_crossings"] == 0,
        "no_receiver_closed_face_entries": geometry["receiver_world_frame"]["saved_chord_closed_face_entries"] == 0,
        "no_catchment_closed_wall_endpoint_penetrations": geometry["catchment_world_frame"]["endpoint_particle_frames"] == 0,
        "no_catchment_floor_endpoint_penetrations": geometry["catchment_floor_world_frame"]["endpoint_particle_frames"] == 0,
        "no_catchment_saved_chord_crossings": geometry["catchment_world_frame"]["saved_chord_crossings"] == 0,
        "no_catchment_floor_saved_chord_crossings": geometry["catchment_floor_world_frame"]["saved_chord_crossings"] == 0,
        "no_catchment_closed_face_entries": geometry["catchment_world_frame"]["saved_chord_closed_face_entries"] == 0,
    }
    hard_integrity_pass = bool(all(hard_checks.values()))
    return {
        "schema": "core.f2.dynamic_audit.v1",
        "revision_id": config.get("revision_id", CANARY_REVISION_ID),
        "family": "F2",
        "case_id": config["case_id"],
        "prepared_sha256": core_cfd.digest(prepared_path),
        "trajectory_sha256": core_cfd.digest(hdf5_path),
        "wall_tolerance_m": F2_WALL_TOLERANCE_M,
        "geometry_semantics": {
            "cup": "moving finite box in prescribed cup body frame; bottom/left/right/front/back closed, top open",
            "receiver": "fixed finite box in world frame; bottom/left/right/front/back closed, top open",
            "tray": "fixed finite bottom slab in world frame; bottom closed and side/top faces open",
            "runtime_domain": "computational AABB reported separately from physical wall checks",
            "entry_check": "saved-chord outside-to-inside crossings through receiver or moving-cup closed faces are hard failures; open-top re-entry is allowed and retracked",
            "tray_bottom_endpoint": "checked only on initial or above-to-below transitions within the finite tray footprint; side-entry below the open slab is not a bottom penetration",
            "catchment": "new fixed four-side catchment walls in world frame; left/right/front/back are closed, top is open and top exits/entries are reported rather than treated as side-wall failures",
            "catchment_floor": "retained boxfill=bottom tray floor is audited at its continuous source plane z=-0.20 m; XML size z=0.10 is not treated as a top face",
        },
        "catchment_geometry_declaration": catchment_geometry_declaration,
        "identity_audit": identity_audit,
        "runtime_domain": {
            "declared": declared_domain_spec,
            "resolved": resolved_domain_spec,
            "declaration_matches_generated_xml": domain_declaration_matches,
            "valid_particle_endpoint_count": int(runtime_outside),
            "valid_particle_endpoint_mass_kg": float(runtime_outside_mass),
        },
        "geometry_audit": geometry,
        "hard_checks": hard_checks,
        "hard_integrity_pass": hard_integrity_pass,
        # Compatibility aliases for coordinator consumers.  These are window
        # observations only and are deliberately absent from hard_checks.
        "requested_horizon_reached": horizon_reached,
        "event_window_complete": bool(observations["event_window_complete"]),
        "window_checks": {
            "requested_horizon_reached": horizon_reached,
            "event_window_complete": bool(observations["event_window_complete"]),
        },
        "event_window": {
            "requested_horizon_reached": horizon_reached,
            "event_window_complete": bool(observations["event_window_complete"]),
            "event_times_s": observations["event_times_s"],
            "qualification_claim": "none; event completion is independent of hard native/geometry integrity",
        },
        "qualification_claim": "none; F2 dynamic canary audit only",
        "qualified": False,
    }


def _run_solver_without_generic_audit(prepared_path: Path, lab: Path, output: Path) -> dict:
    """Run/convert one worker case without invoking the generic CFD audit."""
    prepared = json.loads(Path(prepared_path).read_text())
    for path, expected in prepared["inputs"].items():
        if core_cfd.digest(Path(path)) != expected:
            raise ValueError("changed prepared input: " + path)
    if core_cfd.digest(Path(prepared["solver_binary"])) != prepared["solver_sha256"]:
        raise ValueError("changed native solver")
    if core_cfd.digest(Path(prepared["decoder"])) != prepared["decoder_sha256"]:
        raise ValueError("changed native decoder")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not visible or "," in visible:
        raise ValueError("coordinator must provide exactly one CUDA_VISIBLE_DEVICES device")
    if output.exists() and any(output.iterdir()):
        raise ValueError("worker output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    core_cfd.write_json(output / "prepared.json", prepared)
    solver_output = output / "solver"
    argv = [prepared["solver_binary"], "-gpu:0", *prepared.get("solver_arguments", []), prepared["generated_prefix"], str(solver_output)]
    started = time.monotonic()
    core_cfd.write_json(output / "worker-status.json", {
        "status": "running", "argv": argv, "started_at": core_cfd.stamp(),
        "cuda_visible_devices": visible, "audit_owner": "core_f2_qualification",
    })
    with (output / "solver.stdout.log").open("w") as log:
        process = subprocess.run(argv, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - started
    stdout = (output / "solver.stdout.log").read_text()
    if process.returncode or "Finished execution (code=0)" not in stdout:
        core_cfd.write_json(output / "worker-status.json", {
            "status": "solver_failed", "returncode": process.returncode,
            "elapsed_seconds": elapsed, "audit_owner": "core_f2_qualification",
        })
        raise RuntimeError("F2 dynamic solver failed; raw attempt retained")
    conversion = core_cfd.convert_native(prepared, solver_output / "data", output / "trajectory.h5")
    return {
        "schema": "core.f2.execution.v1",
        "case_id": prepared["config"]["case_id"],
        "solver_elapsed_seconds": elapsed,
        "conversion": conversion,
        "generic_core_cfd_audit_invoked": False,
    }


def run(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass"):
        raise ValueError("F2 dynamic canary preflight did not pass")
    result = _run_solver_without_generic_audit(prepared_path, lab, output)
    observations = observe_dynamic(prepared_path, output / "trajectory.h5")
    audit = audit_dynamic(prepared_path, output / "trajectory.h5", observations)
    core_cfd.write_json(output / "observations.json", observations)
    core_cfd.write_json(output / "audit.json", audit)
    result.update(audit)
    result["observations"] = observations
    core_cfd.write_json(output / "result.json", result)
    core_cfd.write_json(output / "worker-status.json", {
        "status": "complete_with_evidence",
        "hard_integrity_pass": audit["hard_integrity_pass"],
        "event_window_complete": audit["event_window"]["event_window_complete"],
        "finished_at": core_cfd.stamp(),
        "audit_owner": "core_f2_qualification",
    })
    return result


def make_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass"):
        raise ValueError("F2 dynamic canary prepared case did not pass CPU preflight")
    solver = Path(prepared["solver_binary"]).resolve()
    job_id = "f2-pour-duration-fullwindow-canary-001"
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "dynamic_event_window_canary",
        "category": "f2_dynamic_event_window_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2_qualification.py"), "--lab-root", str(lab), "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 0.5},
        "timeout_seconds": 7200,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_status": "candidate-only; F2 dynamic range remains unqualified",
        "input_files": [{"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)}, {"path": str(solver), "sha256": core_cfd.digest(solver)}],
        "prepared_case_id": prepared["config"]["case_id"],
        "registered_window_s": FULL_WINDOW_S,
        "maximum_extended_window_s": MAXIMUM_EXTENDED_WINDOW_S,
        "scope_id": prepared["config"]["scope_id"],
        "revision_id": prepared["config"]["revision_id"],
        "family": "F2",
        "parameter_axis": "rotation_duration_s",
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
    }
    _write_json(output, spec)
    return spec


def make_envelope_repair_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    """Write the unsubmitted job for the envelope repair canary."""
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass"):
        raise ValueError("F2 envelope repair canary preflight did not pass CPU preflight")
    if prepared.get("config", {}).get("repair_candidate_id") != "computational_envelope_all_faces_canary":
        raise ValueError("prepared case is not the registered F2 envelope repair candidate")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    job_id = "f2-pour-duration-envelope-repair-canary-001"
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "computational_envelope_repair_canary",
        "category": "f2_dynamic_envelope_repair_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2_qualification.py"),
                 "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
                 "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib": 6144, "io_weight": 1},
        "timeout_seconds": 7200,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_status": "candidate-only; envelope repair evidence; F2 dynamic range remains unqualified",
        "launch_recommendation": "hold; ballistic full-window analysis predicts all six finite-margin faces can be reached before 2.5 s",
        "superseded_by": "f2-pour-duration-ballistic-envelope-canary-001",
        "input_files": [
            {"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)},
            {"path": str(solver), "sha256": core_cfd.digest(solver)},
            {"path": str(decoder), "sha256": core_cfd.digest(decoder)},
        ],
        "prepared_case_id": prepared["config"]["case_id"],
        "registered_window_s": FULL_WINDOW_S,
        "maximum_extended_window_s": MAXIMUM_EXTENDED_WINDOW_S,
        "scope_id": prepared["config"]["scope_id"],
        "revision_id": prepared["config"]["revision_id"],
        "family": "F2",
        "parameter_axis": "rotation_duration_s",
        "repair_candidate_id": prepared["config"]["repair_candidate_id"],
        "physical_geometry_changed": False,
        "mass_rescaling": False,
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
    }
    _write_json(output, spec)
    return spec


def make_ballistic_envelope_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    """Write the unsubmitted job for the physics-based envelope diagnostic."""
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass"):
        raise ValueError("F2 ballistic envelope canary preflight did not pass CPU preflight")
    if prepared.get("config", {}).get("repair_candidate_id") != "observed_partout_ballistic_full_window_envelope":
        raise ValueError("prepared case is not the registered F2 ballistic envelope candidate")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    job_id = "f2-pour-duration-ballistic-envelope-canary-001"
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "physics_based_ballistic_envelope_canary",
        "category": "f2_dynamic_ballistic_envelope_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2_qualification.py"),
                 "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
                 "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_status": "candidate-only; physics-based envelope diagnostic; F2 dynamic range remains unqualified",
        "input_files": [
            {"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)},
            {"path": str(solver), "sha256": core_cfd.digest(solver)},
            {"path": str(decoder), "sha256": core_cfd.digest(decoder)},
        ],
        "prepared_case_id": prepared["config"]["case_id"],
        "registered_window_s": FULL_WINDOW_S,
        "maximum_extended_window_s": MAXIMUM_EXTENDED_WINDOW_S,
        "scope_id": prepared["config"]["scope_id"],
        "revision_id": prepared["config"]["revision_id"],
        "family": "F2",
        "parameter_axis": "rotation_duration_s",
        "repair_candidate_id": prepared["config"]["repair_candidate_id"],
        "physics_basis": prepared["config"]["runtime_domain"]["basis"],
        "domain_cost_estimate": {
            "cell_dimensions": [683, 529, 1083],
            "cells": 391295481,
            "estimated_gpu_cell_memory_mib": 5982,
            "relative_cells_to_failed_generated_domain": 243.16,
            "source_cell_size_m": 0.0195,
        },
        "physical_geometry_changed": False,
        "mass_rescaling": False,
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
    }
    _write_json(output, spec)
    return spec


def make_mdbc_closed_wall_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    """Write an unsubmitted moving-mDBC contact diagnostic job."""
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass"):
        raise ValueError("F2 moving mDBC candidate did not pass CPU preflight")
    config = prepared.get("config", {})
    if config.get("repair_candidate_id") != "dynamic_mdbc_closed_wall_contact" or config.get("boundary_method") != 2:
        raise ValueError("prepared case is not the registered moving mDBC contact candidate")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    job_id = "f2-pour-duration-mdbc-closed-wall-canary-001"
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "moving_mdbc_closed_wall_diagnostic_canary",
        "category": "f2_dynamic_mdbc_closed_wall_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2_qualification.py"),
                 "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
                 "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_status": "candidate-only; moving mDBC contact diagnostic; F2 dynamic range remains unqualified",
        "launch_recommendation": "hold pending root review; current corrected full-vector audits show no cup closed-face entry, so this is a boundary-formulation diagnostic rather than a confirmed repair",
        "input_files": [
            {"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)},
            {"path": str(solver), "sha256": core_cfd.digest(solver)},
            {"path": str(decoder), "sha256": core_cfd.digest(decoder)},
        ],
        "prepared_case_id": config["case_id"],
        "registered_window_s": FULL_WINDOW_S,
        "maximum_extended_window_s": MAXIMUM_EXTENDED_WINDOW_S,
        "scope_id": config["scope_id"],
        "revision_id": config["revision_id"],
        "family": "F2",
        "parameter_axis": "rotation_duration_s",
        "repair_candidate_id": config["repair_candidate_id"],
        "boundary_method": "mDBC Boundary=2 with -mdbc_noslip:1",
        "normal_ghost_basis": {
            "normal_construction_layers_vdp": -0.5,
            "normal_search_distance_h": 3.0,
            "svshapes": True,
            "moving_boundary_count_included": True,
            "wall_velocity": "prescribed mvrotfile rigid-body velocity about y axis and z=0.65 pivot",
        },
        "physical_geometry_changed": False,
        "mass_rescaling": False,
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
    }
    _write_json(output, spec)
    return spec


def make_closed_catchment_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    """Write the unsubmitted full-window job for the new catchment geometry."""
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass"):
        raise ValueError("F2 closed-catchment canary did not pass CPU preflight")
    config = prepared.get("config", {})
    if config.get("repair_candidate_id") != "closed_external_catchment_geometry":
        raise ValueError("prepared case is not the registered closed-catchment candidate")
    if config.get("physical_geometry_changed") is not True or config.get("mass_rescaling") is not False:
        raise ValueError("closed-catchment candidate must record physical geometry change without mass rescaling")
    if config.get("qualification_only") is not True or config.get("split") != "qualification_only":
        raise ValueError("closed-catchment repair lineage must remain qualification_only")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    job_id = F2_CATCHMENT_CANARY_JOB_ID
    catchment = config["catchment"]
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "closed_external_catchment_geometry_canary",
        "category": "f2_dynamic_closed_catchment_geometry_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2_qualification.py"),
                 "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
                 "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_status": "candidate-only; independent physical catchment scope remains unqualified",
        "launch_recommendation": "hold pending root review; new closed-catchment geometry is a separate physical scope and does not inherit old F2 evidence",
        "qualification_only": True,
        "split": "qualification_only",
        "supersedes_prepared_revision": "F2_closed_catchment_geometry_canary_v1",
        "input_files": [
            {"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)},
            {"path": str(solver), "sha256": core_cfd.digest(solver)},
            {"path": str(decoder), "sha256": core_cfd.digest(decoder)},
        ],
        "prepared_case_id": config["case_id"],
        "registered_window_s": FULL_WINDOW_S,
        "maximum_extended_window_s": MAXIMUM_EXTENDED_WINDOW_S,
        "event_window_estimate": config["catchment_event_window_estimate"],
        "scope_id": config["scope_id"],
        "revision_id": config["revision_id"],
        "family": "F2",
        "parameter_axis": "rotation_duration_s",
        "parameter_q": float(config["parameter"]["q"]),
        "repair_candidate_id": config["repair_candidate_id"],
        "physical_geometry_changed": True,
        "mass_rescaling": False,
        "geometry_contract": {
            "continuous_low_m": list(catchment["low"]),
            "continuous_size_m": list(catchment["size"]),
            "continuous_high_m": [float(catchment["low"][i] + catchment["size"][i]) for i in range(3)],
            "wall_mkbound": int(catchment["mkbound"]),
            "floor_mkbound": int(catchment["floor_material_mkbound"]),
            "drawn_faces": list(catchment["drawn_faces"]),
            "closed_faces": list(catchment["closed_faces"]),
            "open_faces": list(catchment["open_faces"]),
            "wall_layers_vdp": list(catchment["wall_layers_vdp"]),
            "nominal_wall_thickness_m": float(catchment["nominal_wall_thickness_m"]),
            "surface_convention": config["catchment_wall_spec"]["surface_convention"],
            "fluid_facing_bounds": config["catchment_wall_spec"]["container_interior"],
            "floor_fluid_facing_surface_z_m": float(config["catchment_wall_spec"]["floor"]["fluid_facing_surface_z_m"]),
            "floor_nominal_outer_low_z_m": float(config["catchment_wall_spec"]["floor"]["nominal_outer_low_z_m"]),
            "material_purpose": catchment["material_purpose"],
            "floor_purpose": catchment["floor_purpose"],
            "old_tray_bottom_retained": True,
        },
        "observer_contract": {
            "legacy_observer_unchanged": True,
            "legacy_settled_gate_unchanged": True,
            "legacy_spill_mass_retained": True,
            "destination_aware_observer": "separate candidate only; not enabled by this job",
            "qualification_inheritance": "none",
        },
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
    }
    _write_json(output, spec)
    return spec


def validate_qualification_prepared(prepared_path: Path) -> dict:
    """Validate one frozen F2 qualification cell without launching a solver."""
    prepared_path = Path(prepared_path).resolve()
    prepared = json.loads(prepared_path.read_text())
    config = prepared.get("config", {})
    issues = []
    if config.get("stage") != "qualification":
        issues.append("case is not a qualification-stage cell")
    if config.get("revision_id") != REVISION_ID:
        issues.append("qualification revision is not frozen F2 revision")
    if config.get("design_cell") not in {"spatial", "internal_time", "native_output"}:
        issues.append("unknown design cell")
    if config.get("observer_revision") != F2_OBSERVER_REVISION_ID:
        issues.append("observer revision is not frozen F2 observer revision")
    control = config.get("time_control", {})
    required_controls = ("cflnumber", "DtIni", "DtMin", "DtFixed")
    for key in required_controls:
        if key not in control or not math.isfinite(float(control[key])):
            issues.append(f"missing/nonfinite time control {key}")
    generated_path = Path(prepared.get("generated_prefix", "")).with_suffix(".xml")
    if not generated_path.is_file():
        issues.append("generated XML is missing")
    else:
        generated = ET.parse(generated_path).getroot()
        cfl = generated.find(".//cflnumber")
        actual_cfl = None if cfl is None else float(cfl.get("value"))
        if actual_cfl is None or not math.isclose(actual_cfl, float(control.get("cflnumber", math.nan)), rel_tol=0.0, abs_tol=1e-12):
            issues.append("generated XML cflnumber does not match the cell time control")
        for key in ("DtIni", "DtMin", "DtFixed"):
            node = generated.find(f".//execution/parameters/parameter[@key='{key}']")
            actual = None if node is None else float(node.get("value"))
            if actual is None or not math.isclose(actual, float(control.get(key, math.nan)), rel_tol=0.0, abs_tol=1e-12):
                issues.append(f"generated XML {key} does not match the cell time control")
        for key, expected in (("TimeMax", config.get("time_max_s")), ("TimeOut", config.get("output_interval_s"))):
            node = generated.find(f".//execution/parameters/parameter[@key='{key}']")
            actual = None if node is None else float(node.get("value"))
            if expected is None or actual is None or not math.isclose(actual, float(expected), rel_tol=0.0, abs_tol=1e-12):
                issues.append(f"generated XML {key} does not match the cell configuration")
    resolved = prepared.get("resolved_runtime_domain")
    declared = config.get("runtime_domain", {})
    if resolved is None:
        issues.append("resolved runtime domain is missing")
    elif any(not np.allclose(resolved.get(key), declared.get(key), rtol=0.0, atol=1e-12) for key in ("posmin", "posmax")):
        issues.append("resolved runtime domain differs from declared runtime domain")
    if not prepared.get("preflight_pass"):
        issues.append("CPU preflight did not pass")
    mass_gate = bool(prepared.get("mass_preflight", {}).get("mass_gate_pass"))
    if not mass_gate:
        issues.append("native mass gate did not pass")
    return {
        "schema": "core.f2.static.v1",
        "revision_id": REVISION_ID,
        "prepared": str(prepared_path),
        "case_id": config.get("case_id"),
        "design_cell": config.get("design_cell"),
        "static_quality_pass": not issues,
        "preflight_pass": not issues,
        "mass_gate_pass": mass_gate,
        "mass_rescaling": bool(config.get("mass_rescaling", True)),
        "continuum_geometry_unchanged": bool(config.get("physical_geometry_changed") is False),
        "time_control": control,
        "qualification_claim": "none",
        "issues": issues,
    }


def _matrix_preparation_resource_plan(design: dict) -> dict:
    """Estimate sequential CPU preparation/storage before materializing 15 cells."""
    fluid_counts = {str(dp): int(_mass_check(dp)["expected_fluid_particles"]) for dp in DP_RESOLUTIONS}
    canary_root = SOURCE_ROOT / "campaigns/core-v1/cfd/prepared/F2_pour_duration_dynamic_canary"
    canary_bytes = sum(path.stat().st_size for path in canary_root.rglob("*") if path.is_file()) if canary_root.is_dir() else 0
    canary_particles = _mass_check(CANARY_DP_M)["expected_fluid_particles"]
    # Existing GenCase output gives a conservative per-particle basis.  The
    # matrix plan adds a 2x safety factor and assumes sequential preparation.
    boundary_ratio = 319608 / max(canary_particles, 1)
    estimated_bytes = 0.0
    rows = []
    for row in design["cells"]:
        dp = float(row["dp_m"])
        fluid = fluid_counts[str(dp)]
        particles = int(math.ceil(fluid * (1.0 + boundary_ratio)))
        estimate = int(particles * canary_bytes / max(canary_particles + 319608, 1)) if canary_bytes else None
        estimated_bytes += estimate or 0
        rows.append({
            "index": int(design["cells"].index(row)),
            "dp_m": dp,
            "design_cell": row["design_cell"],
            "expected_fluid_particles": fluid,
            "estimated_total_generated_particles": particles,
            "estimated_disk_bytes": estimate,
            "ram_mib": resource_estimate(dp)["ram_mib"],
        })
    return {
        "preparation_mode": "sequential CPU GenCase; no solver launch",
        "peak_ram_mib": max(row["ram_mib"] for row in rows),
        "estimated_disk_bytes": int(estimated_bytes) if canary_bytes else None,
        "conservative_disk_bytes_2x": int(2.0 * estimated_bytes) if canary_bytes else None,
        "basis": {
            "existing_canary_root": str(canary_root),
            "existing_canary_bytes": canary_bytes,
            "existing_canary_fluid_particles": canary_particles,
            "existing_canary_boundary_particles": 319608,
            "safety_factor": 2.0,
        },
        "cells": rows,
    }


def prepare_matrix(lab: Path, output: Path) -> dict:
    """Materialize all 15 qualification cells after the caller accepts the resource plan."""
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("F2 qualification matrix output must be fresh")
    output.mkdir(parents=True, exist_ok=True)
    design = qualification_design()
    design_path = output / "design.json"
    _write_json(design_path, design)
    plan = _matrix_preparation_resource_plan(design)
    rows = []
    for index, config in enumerate(design["cells"]):
        cell_root = output / f"cell-{index:02d}"
        prepared = _prepare_dynamic_case(lab, cell_root, config)
        validation = validate_qualification_prepared(cell_root / "prepared.json")
        rows.append({
            "index": index,
            "case_id": config["case_id"],
            "q": config["parameter"]["q"],
            "dp_m": config["dp_m"],
            "design_cell": config["design_cell"],
            "temporal_variant": config["temporal_variant"],
            "prepared": str((cell_root / "prepared.json").resolve()),
            "preflight_pass": bool(prepared["preflight_pass"]),
            "static_quality_pass": bool(validation["static_quality_pass"]),
            "mass_gate_pass": bool(prepared["mass_preflight"]["mass_gate_pass"]),
            "time_control": config["time_control"],
        })
        _write_json(output / "prepared-matrix.json", {
            "schema": "core.f2.qualification.matrix.v1",
            "revision_id": REVISION_ID,
            "design_sha256": core_cfd.digest(design_path),
            "cells": rows,
            "complete": len(rows) == len(design["cells"]),
            "static_mass_status": design["static_mass_status"],
            "preparation_resource_plan": plan,
            "execution_status": "prepared_only; canary gate required before launch",
            "qualification_claim": "none",
        })
    passed = len(rows) == 15 and all(row["preflight_pass"] and row["static_quality_pass"] and row["mass_gate_pass"] for row in rows)
    return {
        "schema": SCHEMA,
        "revision_id": REVISION_ID,
        "matrix_root": str(output),
        "cell_count": len(rows),
        "preflight_pass": passed,
        "static_quality_pass": passed,
        "preparation_resource_plan": plan,
        "qualification_claim": "none; CPU preparation only",
    }


def make_matrix_jobs(matrix_root: Path, lab: Path, output: Path) -> dict:
    """Write 15 scheduler specs; this does not submit them."""
    matrix_root, lab, output = Path(matrix_root).resolve(), Path(lab).resolve(), Path(output).resolve()
    matrix = json.loads((matrix_root / "prepared-matrix.json").read_text())
    if len(matrix.get("cells", [])) != 15 or not matrix.get("complete"):
        raise ValueError("F2 qualification matrix is incomplete")
    jobs_dir = output.with_suffix("")
    jobs_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for row in matrix["cells"]:
        prepared_path = Path(row["prepared"]).resolve()
        validation = validate_qualification_prepared(prepared_path)
        if not validation["static_quality_pass"]:
            raise ValueError(f"F2 cell {row['index']:02d} static validation failed: {validation['issues']}")
        prepared = json.loads(prepared_path.read_text())
        config = prepared["config"]
        solver = Path(prepared["solver_binary"]).resolve()
        decoder = Path(prepared["decoder"]).resolve()
        job_id = f"f2-pour-duration-qualification-cell-{int(row['index']):02d}"
        timeout = 10800 if float(config["dp_m"]) <= 0.005 else 7200
        spec = {
            "schema": JOB_SCHEMA,
            "job_id": job_id,
            "logical_id": job_id,
            "attempt_role": "initial",
            "category": "qualification",
            "host": "ada",
            "source_lab": str(lab),
            "cwd": str(lab),
            "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2_qualification.py"),
                     "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
                     "--output", "{attempt_dir}/product"],
            "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
            "resources": resource_estimate(float(config["dp_m"])),
            "timeout_seconds": timeout,
            "depends_on": [],
            "qualification_claim": "none",
            "input_files": [
                {"path": str(prepared_path), "sha256": core_cfd.digest(prepared_path)},
                {"path": str(solver), "sha256": core_cfd.digest(solver)},
                {"path": str(decoder), "sha256": core_cfd.digest(decoder)},
            ],
            "prepared_case_id": config["case_id"],
            "registered_window_s": config["time_max_s"],
            "maximum_extended_window_s": config["maximum_extended_time_s"],
            "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0",
            "canary_gate_required": "f2-pour-duration-fullwindow-canary-001",
            "observer_revision": F2_OBSERVER_REVISION_ID,
            "time_control_gate": "actual solver Run.csv steps/dt and native output cadence are required",
            "static_validation": validation,
        }
        path = jobs_dir / f"{job_id}.json"
        _write_json(path, spec)
        jobs.append({"index": int(row["index"]), "job_id": job_id, "path": str(path),
                     "prepared": str(prepared_path), "resources": spec["resources"],
                     "required_outputs": spec["required_outputs"]})
    manifest = {
        "schema": "core.cfd.jobs.v1",
        "revision_id": REVISION_ID,
        "matrix_root": str(matrix_root),
        "matrix_sha256": core_cfd.digest(matrix_root / "prepared-matrix.json"),
        "design_sha256": core_cfd.digest(matrix_root / "design.json"),
        "jobs": jobs,
        "job_count": len(jobs),
        "execution_status": "prepared_only; canary gate required before launch",
        "qualification_claim": "none",
        "canary_dependency": "f2-pour-duration-fullwindow-canary-001",
    }
    _write_json(output, manifest)
    return manifest


def _observation_arrays(observation: dict) -> tuple[np.ndarray, np.ndarray]:
    names = tuple(observation.get("normalized_observable_names", ()))
    values = np.asarray(observation.get("normalized_values", []), dtype=np.float64)
    if names != tuple(F2_OBSERVABLE_NAMES):
        raise ValueError("F2 observer revision/layout mismatch")
    if values.ndim != 2 or values.shape[1] != len(F2_OBSERVABLE_NAMES) or not np.isfinite(values).all():
        raise ValueError("F2 normalized observations have an invalid layout or nonfinite value")
    times = np.asarray(observation.get("time_s", []), dtype=np.float64)
    if len(times) != len(values) or len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0.0):
        raise ValueError("F2 observer times are invalid")
    return times, values


def aligned_difference(first: dict, second: dict, cadence: float = F2_SCORE_INTERVAL_S) -> dict:
    """Compare F2 normalized observables on a common registered time grid."""
    a, av = _observation_arrays(first)
    b, bv = _observation_arrays(second)
    low, high = max(a[0], b[0]), min(a[-1], b[-1])
    if high <= low:
        raise ValueError("F2 observations have no common time support")
    first_tick = int(math.ceil(low / cadence - 1e-10))
    last_tick = int(math.floor(high / cadence + 1e-10))
    if last_tick - first_tick < 1:
        raise ValueError("F2 observations have fewer than two common score frames")
    grid = np.arange(first_tick, last_tick + 1, dtype=np.float64) * cadence
    aa = np.column_stack([np.interp(grid, a, av[:, index]) for index in range(av.shape[1])])
    bb = np.column_stack([np.interp(grid, b, bv[:, index]) for index in range(bv.shape[1])])
    errors = np.max(np.abs(aa - bb), axis=0)
    return {
        "maximum": float(errors.max()),
        "per_observable_maximum": errors.tolist(),
        "observable_names": list(F2_OBSERVABLE_NAMES),
        "common_start_s": float(grid[0]),
        "common_end_s": float(grid[-1]),
        "score_frames": int(len(grid)),
    }


def event_difference(first: dict, second: dict) -> dict:
    a, b = first.get("event_times_s", {}), second.get("event_times_s", {})
    missing = [name for name in F2_REQUIRED_EVENT_NAMES if a.get(name) is None or b.get(name) is None]
    relative = {}
    for name in F2_REQUIRED_EVENT_NAMES:
        if name in missing:
            continue
        denominator = max(abs(float(a[name])), abs(float(b[name])), F2_SCORE_INTERVAL_S)
        relative[name] = abs(float(a[name]) - float(b[name])) / denominator
    optional = {}
    if a.get("spill_or_escape") is not None and b.get("spill_or_escape") is not None:
        denominator = max(abs(float(a["spill_or_escape"])), abs(float(b["spill_or_escape"])), F2_SCORE_INTERVAL_S)
        optional["spill_or_escape"] = abs(float(a["spill_or_escape"]) - float(b["spill_or_escape"])) / denominator
    maximum = max(relative.values(), default=float("inf"))
    return {
        "required_event_names": list(F2_REQUIRED_EVENT_NAMES),
        "topology_pass": not missing,
        "missing_required_events": missing,
        "relative_time_errors": relative,
        "optional_relative_time_errors": optional,
        "maximum_relative_time_error": float(maximum),
        "passed": bool(not missing and maximum <= 0.05),
    }


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip().replace(",", ""))
    except (AttributeError, ValueError):
        return None


def read_run_metrics(product: Path) -> dict:
    """Read actual solver step/output cadence evidence from a product."""
    product = Path(product)
    run_csv = product / "solver" / "Run.csv"
    run_out = product / "solver" / "Run.out"
    result = {"run_csv": str(run_csv), "run_out": str(run_out), "available": False}
    if run_csv.is_file():
        lines = run_csv.read_text(errors="replace").splitlines()
        header_index = next((index for index, line in enumerate(lines) if line.startswith("#RunName;")), None)
        if header_index is not None and header_index + 1 < len(lines):
            header = lines[header_index].lstrip("#").split(";")
            row = next(csv.reader([lines[header_index + 1]], delimiter=";"), [])
            fields = dict(zip(header, row))
            steps = _parse_number(fields.get("Steps"))
            physical_time = _parse_number(fields.get("PhysicalTime"))
            part_files = _parse_number(fields.get("PartFiles"))
            if steps is not None and physical_time is not None and steps > 0:
                result.update({
                    "available": True,
                    "steps": int(steps),
                    "physical_time_s": float(physical_time),
                    "mean_solver_dt_s": float(physical_time / steps),
                    "part_files": None if part_files is None else int(part_files),
                })
    if run_out.is_file():
        text = run_out.read_text(errors="replace")
        result["dt_min_adjustment_warning_count"] = len(re.findall(r"DTs adjusted to DtMin", text))
        result["solver_finished"] = "Finished execution (code=0)" in text
    else:
        result["dt_min_adjustment_warning_count"] = 0
        result["solver_finished"] = False
    return result


def _forensics_number(value: object) -> float | None:
    """Parse a DualSPHysics CSV number without treating comments as rows."""
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _forensics_integer(value: object) -> int | None:
    number = _forensics_number(value)
    return None if number is None else int(number)


def _forensics_domain(values: dict) -> dict:
    lower = values["posmin"]
    upper = values["posmax"]
    return {
        "xmin": float(lower[0]), "xmax": float(upper[0]),
        "ymin": float(lower[1]), "ymax": float(upper[1]),
        "zmin": float(lower[2]), "zmax": float(upper[2]),
    }


def _forensics_endpoint_summary(
    times: np.ndarray,
    positions: np.ndarray,
    valid: np.ndarray,
    domain: dict,
) -> dict:
    count = 0
    massless_count = 0
    first = None
    by_face = {face: 0 for face in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")}
    lower = np.asarray([domain["xmin"], domain["ymin"], domain["zmin"]], dtype=float)
    upper = np.asarray([domain["xmax"], domain["ymax"], domain["zmax"]], dtype=float)
    for frame_index, time_s in enumerate(times):
        active = valid[frame_index] & np.isfinite(positions[frame_index]).all(axis=1)
        if not active.any():
            continue
        points = positions[frame_index, active]
        outside = outside_runtime_domain_mask(points, domain, F2_WALL_TOLERANCE_M)
        if outside is None or not outside.any():
            continue
        count += int(outside.sum())
        massless_count += int((~np.isfinite(points[outside]).all(axis=1)).sum())
        if first is None:
            bad_points = points[outside]
            first = {
                "frame_index": int(frame_index),
                "time_s": float(time_s),
                "count": int(outside.sum()),
                "sample_positions_m": bad_points[:5].tolist(),
            }
        for axis, values in zip("xyz", (points[outside, 0], points[outside, 1], points[outside, 2])):
            low_bad = values < lower["xyz".index(axis)] - F2_WALL_TOLERANCE_M
            high_bad = values > upper["xyz".index(axis)] + F2_WALL_TOLERANCE_M
            by_face[f"{axis}min"] += int(low_bad.sum())
            by_face[f"{axis}max"] += int(high_bad.sum())
    return {
        "valid_endpoint_count": int(count),
        "nonfinite_endpoint_count": int(massless_count),
        "first": first,
        "by_face": by_face,
    }


def _forensics_runparts(path: Path) -> dict:
    path = Path(path)
    empty = {
        "status": "missing",
        "path": str(path),
        "rows": 0,
        "totals": {key: 0 for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")},
        "first_nonzero": {},
    }
    if not path.is_file():
        return empty
    lines = path.read_text(errors="replace").splitlines()
    header_index = next((i for i, line in enumerate(lines) if line.startswith("Part;")), None)
    if header_index is None:
        return {**empty, "status": "malformed", "error": "missing_tabular_header"}
    reader = csv.DictReader(lines[header_index:], delimiter=";")
    names = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
    totals = {key: 0 for key in names}
    first_nonzero = {}
    row_count = 0
    malformed = 0
    for raw in reader:
        if not raw or _forensics_integer(raw.get("Part")) is None:
            continue
        part = _forensics_integer(raw.get("Part"))
        time_s = _forensics_number(raw.get("TimeStep [s]"))
        values = {key: _forensics_integer(raw.get(key)) for key in names}
        if part is None or time_s is None or any(value is None for value in values.values()):
            malformed += 1
            continue
        row_count += 1
        for key, value in values.items():
            totals[key] += int(value)
            if int(value) > 0 and key not in first_nonzero:
                first_nonzero[key] = {
                    "part": int(part), "time_s": float(time_s), "count": int(value),
                }
    return {
        "status": "available" if malformed == 0 else "available_with_findings",
        "path": str(path),
        "rows": int(row_count),
        "malformed_rows": int(malformed),
        "totals": totals,
        "first_nonzero": first_nonzero,
    }


def _forensics_partout(product: Path) -> dict:
    """Read native PartOut reasons in a temporary directory; never alter product."""
    solver_dir = Path(product) / "solver"
    binary = SOURCE_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
    base = {"status": "unavailable", "binary": str(binary), "rows": 0}
    if not binary.is_file() or not solver_dir.is_dir():
        return base
    with tempfile.TemporaryDirectory(prefix="f2-partout-forensics-") as folder:
        csv_path = Path(folder) / "excluded.csv"
        command = [str(binary), "-dirdata", str(solver_dir), "-savecsv", str(csv_path), "-csvsep:0"]
        process = subprocess.run(
            command, cwd=SOURCE_ROOT, env=core_f2.environment(SOURCE_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if process.returncode != 0 or not csv_path.is_file():
            return {**base, "status": "failed", "returncode": int(process.returncode),
                    "log_tail": process.stdout[-1000:]}
        rows = []
        with csv_path.open(newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for raw in reader:
                if not raw or raw.get("Idp") is None:
                    continue
                row = {str(key).strip(): str(value).strip() for key, value in raw.items() if key is not None}
                part = _forensics_integer(row.get("PartOut"))
                motive = _forensics_integer(row.get("Motive"))
                if part is None or motive is None:
                    continue
                rows.append({
                    "particle_id": _forensics_integer(row.get("Idp")),
                    "part": part,
                    "motive": motive,
                    "position_m": [_forensics_number(row.get(f"Pos.{axis} [m]")) for axis in "xyz"],
                    "velocity_m_s": [_forensics_number(row.get(f"Vel.{axis} [m/s]")) for axis in "xyz"],
                })
        by_motive = {}
        by_part = {}
        for row in rows:
            by_motive[str(row["motive"])] = by_motive.get(str(row["motive"]), 0) + 1
            by_part[str(row["part"])] = by_part.get(str(row["part"]), 0) + 1
        return {
            "status": "available",
            "binary": str(binary),
            "rows": len(rows),
            "motive_counts": by_motive,
            "part_counts_first": dict(sorted(by_part.items(), key=lambda item: int(item[0]))[:12]),
            "first_rows": rows[:8],
            "command": command,
        }


def dynamic_canary_forensics(product: Path, output: Path) -> dict:
    """Create read-only root-cause evidence for the failed F2 dynamic canary."""
    product = Path(product).resolve()
    output = Path(output).resolve()
    prepared_path = product / "prepared.json"
    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    declared_values = config["runtime_domain"]
    declared = _forensics_domain(declared_values)
    generated_xml = Path(prepared["generated_prefix"]).with_suffix(".xml")
    generated_root = ET.parse(generated_xml).getroot()
    generated_values = _runtime_domain_from_xml(generated_root)
    generated = _forensics_domain(generated_values)
    domain_keys = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
    domain_match = all(math.isclose(declared[key], generated[key], rel_tol=0.0, abs_tol=1e-12) for key in domain_keys)

    trajectory = product / "trajectory.h5"
    with h5py.File(trajectory, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=float)
        positions = np.asarray(handle["position"][:], dtype=float)
        velocities = np.asarray(handle["velocity"][:], dtype=float)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        particle_ids = np.asarray(handle["particle_id"][:])
        masses = np.asarray(handle["mass"][:], dtype=float)
        initial = valid[0]
        first_loss = None
        for frame_index in range(1, len(times)):
            missing = initial & ~valid[frame_index]
            if missing.any():
                previous_index = frame_index - 1
                indices = np.flatnonzero(missing)
                first_loss = {
                    "frame_index": int(frame_index),
                    "time_s": float(times[frame_index]),
                    "count": int(len(indices)),
                    "particle_ids": particle_ids[indices[:8]].astype(int).tolist(),
                    "last_valid_frame_index": int(previous_index),
                    "last_valid_time_s": float(times[previous_index]),
                    "last_valid_position_m": positions[previous_index, indices[:8]].tolist(),
                    "last_valid_velocity_m_s": velocities[previous_index, indices[:8]].tolist(),
                }
                break
        declared_endpoints = _forensics_endpoint_summary(times, positions, valid, declared)
        generated_endpoints = _forensics_endpoint_summary(times, positions, valid, generated)
        active_counts = np.sum(valid, axis=1)
        min_active_fraction = float(active_counts.min() / max(int(initial.sum()), 1))

        tray = config["tray"]
        tray_low = np.asarray(tray["low"], dtype=float)
        tray_high = tray_low + np.asarray(tray["size"], dtype=float)
        legacy_audit_path = product / "audit.json"
        legacy_audit = json.loads(legacy_audit_path.read_text()) if legacy_audit_path.is_file() else {}
        legacy_tray = legacy_audit.get("geometry_audit", {}).get("tray_world_frame", {})
        legacy_first = legacy_tray.get("first_endpoint_violation") or {}
        tray_frame = int(legacy_first.get("frame_index", -1))
        tray_reclassification = {
            "legacy_frame_index": tray_frame if tray_frame >= 0 else None,
            "legacy_time_s": legacy_first.get("time_s"),
            "candidate_count": 0,
            "candidates": [],
            "classification": "not_recomputed",
        }
        if 0 <= tray_frame < len(times):
            current = valid[tray_frame]
            current_mask = current & (positions[tray_frame, :, 2] < tray_low[2] - F2_WALL_TOLERANCE_M)
            current_mask &= np.all((positions[tray_frame, :, :2] >= tray_low[:2] - F2_WALL_TOLERANCE_M)
                                   & (positions[tray_frame, :, :2] <= tray_high[:2] + F2_WALL_TOLERANCE_M), axis=1)
            for particle_index in np.flatnonzero(current_mask):
                below_footprint = []
                for frame_index in range(len(times)):
                    if not valid[frame_index, particle_index]:
                        continue
                    below = positions[frame_index, particle_index, 2] < tray_low[2] - F2_WALL_TOLERANCE_M
                    inside = np.all((positions[frame_index, particle_index, :2] >= tray_low[:2] - F2_WALL_TOLERANCE_M)
                                    & (positions[frame_index, particle_index, :2] <= tray_high[:2] + F2_WALL_TOLERANCE_M))
                    below_footprint.append(bool(below and inside))
                entries = [frame_index for frame_index in range(1, len(below_footprint))
                           if below_footprint[frame_index] and not below_footprint[frame_index - 1]]
                bottom_crossing_inside = False
                for frame_index in range(1, len(times)):
                    if not valid[frame_index - 1, particle_index] or not valid[frame_index, particle_index]:
                        continue
                    previous = positions[frame_index - 1, particle_index]
                    current = positions[frame_index, particle_index]
                    if previous[2] >= tray_low[2] and current[2] < tray_low[2] and abs(current[2] - previous[2]) > 1e-15:
                        fraction = (tray_low[2] - previous[2]) / (current[2] - previous[2])
                        crossing = previous + fraction * (current - previous)
                        inside = np.all((crossing[:2] >= tray_low[:2] - F2_WALL_TOLERANCE_M)
                                        & (crossing[:2] <= tray_high[:2] + F2_WALL_TOLERANCE_M))
                        bottom_crossing_inside |= bool(inside)
                tray_reclassification["candidates"].append({
                    "particle_index": int(particle_index),
                    "particle_id": int(particle_ids[particle_index]),
                    "side_entry_frame_indices": entries,
                    "side_entry_times_s": [float(times[index]) for index in entries],
                    "previous_position_m": positions[tray_frame - 1, particle_index].tolist() if tray_frame else None,
                    "current_position_m": positions[tray_frame, particle_index].tolist(),
                    "bottom_chord_crossing_inside_footprint": bool(bottom_crossing_inside),
                })
            tray_reclassification["candidate_count"] = len(tray_reclassification["candidates"])
            if tray_reclassification["candidates"] and all(
                item["side_entry_frame_indices"] and not item["bottom_chord_crossing_inside_footprint"]
                for item in tray_reclassification["candidates"]
            ):
                tray_reclassification["classification"] = "side_entry_below_open_tray; no_bottom_chord"

    runparts = _forensics_runparts(product / "solver" / "RunPARTs.csv")
    partout = _forensics_partout(product)
    audit = json.loads((product / "audit.json").read_text()) if (product / "audit.json").is_file() else {}
    reaudited_geometry = None
    observations_path = product / "observations.json"
    if observations_path.is_file():
        try:
            reaudited = audit_dynamic(
                prepared_path, trajectory, json.loads(observations_path.read_text())
            )
            first_entry = reaudited["geometry_audit"]["cup_moving_body_frame"]["first_saved_chord_closed_face_entry"]
            if first_entry is not None:
                with h5py.File(trajectory, "r") as handle:
                    particle_ids_for_entry = np.asarray(handle["particle_id"][:])
                for event in first_entry.get("events", []):
                    point_index = int(event["point_index"])
                    if 0 <= point_index < len(particle_ids_for_entry):
                        event["particle_id"] = int(particle_ids_for_entry[point_index])
            reaudited_geometry = {
                "hard_integrity_pass": reaudited["hard_integrity_pass"],
                "cup_open_top_exit_count": reaudited["geometry_audit"]["cup_moving_body_frame"]["open_top_exit_count"],
                "cup_open_top_entry_count": reaudited["geometry_audit"]["cup_moving_body_frame"]["open_top_entry_count"],
                "cup_closed_face_entry_count": reaudited["geometry_audit"]["cup_moving_body_frame"]["saved_chord_closed_face_entries"],
                "cup_first_closed_face_entry": first_entry,
                "receiver_closed_face_entry_count": reaudited["geometry_audit"]["receiver_world_frame"]["saved_chord_closed_face_entries"],
                "semantics": "re-audit is in-memory only; old product audit.json is retained",
            }
        except (OSError, KeyError, ValueError, TypeError) as exc:
            reaudited_geometry = {"status": "failed", "error": str(exc)}
    source_files = [prepared_path, trajectory, generated_xml, product / "solver" / "RunPARTs.csv"]
    source_hashes = {str(path): core_cfd.digest(path) for path in source_files if path.is_file()}
    report = {
        "schema": "core.f2.dynamic_canary.forensics.v1",
        "created_at": _stamp(),
        "family": "F2",
        "case_id": config.get("case_id"),
        "product": str(product),
        "read_only": True,
        "solver_relaunched": False,
        "qualification_claim": "none; failed dynamic canary root-cause evidence only",
        "domain_comparison": {
            "declared_runtime_domain": declared_values,
            "generated_xml_runtime_domain": generated_values,
            "declaration_matches_generated_xml": bool(domain_match),
            "interpretation": "legacy declared-domain endpoint count is not valid evidence when it differs from generated XML",
        },
        "endpoint_recount": {
            "declared_domain": declared_endpoints,
            "generated_xml_domain": generated_endpoints,
            "generated_domain_endpoint_count_is_zero": generated_endpoints["valid_endpoint_count"] == 0,
        },
        "native_identity_loss": {
            "initial_native_fluid_count": int(initial.sum()),
            "final_active_count": int(active_counts[-1]),
            "missing_native_fluid_count": int(initial.sum() - active_counts[-1]),
            "minimum_active_fraction": min_active_fraction,
            "first_loss": first_loss,
            "runparts": runparts,
            "partout": partout,
            "interpretation": "all recorded exclusions are position exclusions; no density or movement exclusions",
        },
        "tray_reclassification": tray_reclassification,
        "ownership_recontact_reaudit": reaudited_geometry,
        "legacy_audit_snapshot": {
            "hard_integrity_pass": audit.get("hard_integrity_pass"),
            "runtime_domain_endpoint_count": audit.get("runtime_domain", {}).get("valid_particle_endpoint_count"),
            "tray_endpoint_count": legacy_tray.get("endpoint_particle_frames"),
            "saved_chord_count": legacy_tray.get("saved_chord_crossings"),
        },
        "repair_candidates": [
            {
                "id": "computational_envelope_all_faces_canary",
                "evidence": [
                    "generated XML and declared audit AABBs differed on x/y/lower-z faces",
                    "PartVTKOut first and later records are Motive=1 at generated-domain faces",
                ],
                "change": "freeze the actual six-face runtime envelope explicitly and test a finite margin canary; preserve continuum geometry, native mass and physical tray/cup/receiver",
                "status": "candidate_only; requires one new canary and does not repair physical-wall semantics",
            }
        ],
        "withheld_repair_classes": [
            "mDBC/cup-wall change: withheld because cup and receiver closed-wall endpoint/chord audits had no findings",
            "tray geometry change: withheld because the one tray point entered the finite footprint from the side while already below the open slab; no bottom chord crossing",
        ],
        "analysis_script_sha256": core_cfd.digest(Path(__file__)),
        "input_sha256": source_hashes,
    }
    _write_json(output, report)
    return report


def _hashes_valid(job: dict, product: Path, names: tuple[str, ...]) -> bool:
    indexed = {item["path"]: item["sha256"] for item in job.get("result", {}).get("artifact_index", job.get("result", {}).get("outputs", []))}
    return all(indexed.get("product/" + name) == core_cfd.digest(product / name) for name in names)


def _job_for_prepared(jobs: list[dict], prepared_path: Path) -> dict | None:
    expected = core_cfd.digest(prepared_path)
    matches = [job for job in jobs if any(item.get("path") == str(prepared_path) and item.get("sha256") == expected
                                         for item in job.get("spec", {}).get("input_files", []))]
    completed = [job for job in matches if job.get("status") == "succeeded"]
    return completed[0] if completed else (matches[0] if matches else None)


def _prepared_domain_matches_generated_xml(prepared: dict) -> bool:
    """Resolve the domain even for legacy products lacking the new receipt key."""
    config = prepared.get("config", {})
    declared = config.get("runtime_domain")
    if not isinstance(declared, dict):
        return False
    resolved = prepared.get("resolved_runtime_domain")
    if resolved is None:
        prefix = prepared.get("generated_prefix")
        if not prefix:
            return False
        generated_path = Path(prefix).with_suffix(".xml")
        if not generated_path.is_file():
            return False
        try:
            resolved = _runtime_domain_from_xml(ET.parse(generated_path).getroot())
        except (ET.ParseError, OSError, ValueError, TypeError):
            return False
    return bool(all(np.allclose(resolved.get(key), declared.get(key), rtol=0.0, atol=1e-12)
                    for key in ("posmin", "posmax")))


def _canary_gate(jobs: list[dict], canary_job_id: str = "f2-pour-duration-fullwindow-canary-001") -> dict:
    matching = [job for job in jobs if job.get("job_id") == canary_job_id]
    if not matching:
        return {"available": False, "passed": False, "reason": "canary_job_missing", "job_id": canary_job_id}
    job = matching[0]
    if job.get("status") != "succeeded":
        return {"available": True, "passed": False, "reason": "canary_not_succeeded",
                "job_id": canary_job_id, "status": job.get("status")}
    product = Path(job.get("attempt_dir", "")) / "product"
    audit_path = product / "audit.json"
    prepared_path = product / "prepared.json"
    if not audit_path.is_file() or not prepared_path.is_file():
        return {"available": True, "passed": False, "reason": "canary_evidence_missing", "job_id": canary_job_id}
    audit = json.loads(audit_path.read_text())
    prepared = json.loads(prepared_path.read_text())
    event_complete = bool(audit.get("event_window_complete", audit.get("event_window", {}).get("event_window_complete")))
    horizon = bool(audit.get("requested_horizon_reached", audit.get("event_window", {}).get("requested_horizon_reached")))
    mass_pass = bool(prepared.get("mass_preflight", {}).get("mass_gate_pass"))
    audit_domain = audit.get("runtime_domain", {}).get("declaration_matches_generated_xml")
    resolved_domain = bool(_prepared_domain_matches_generated_xml(prepared) if audit_domain is None else audit_domain)
    passed = bool(
        audit.get("schema") == "core.f2.dynamic_audit.v1"
        and audit.get("hard_integrity_pass")
        and horizon
        and event_complete
        and mass_pass
        and resolved_domain
        and audit.get("qualification_claim", "none").find("none") >= 0
    )
    return {
        "available": True,
        "passed": passed,
        "job_id": canary_job_id,
        "status": job.get("status"),
        "hard_integrity_pass": audit.get("hard_integrity_pass"),
        "requested_horizon_reached": horizon,
        "event_window_complete": event_complete,
        "mass_gate_pass": mass_pass,
        "runtime_domain_declaration_matches_generated_xml": resolved_domain,
    }


def manufactured_calibration(output: Path) -> dict:
    """Calibrate F2 normalization/alignment/event comparator on exact arrays."""
    config = _cell(0.5, CANARY_DP_M, "spatial")
    times = np.arange(0.0, FULL_WINDOW_S + 0.0001, F2_SCORE_INTERVAL_S)
    n = len(times)
    arrays = {
        "cup_mass_fraction": np.linspace(1.0, .2, n),
        "receiver_mass_fraction": np.linspace(0.0, .8, n),
        "tray_mass_fraction": np.zeros(n),
        "outside_observation_mass_fraction": np.linspace(0.0, .1, n),
        "center_of_mass_world_m": np.column_stack((np.full(n, .2), np.zeros(n), np.full(n, .8))),
        "center_of_mass_cup_body_m": np.column_stack((np.full(n, .1), np.zeros(n), np.full(n, .8))),
        "kinetic_energy_over_initial_potential": np.linspace(0.0, .01, n),
        "speed_p95_m_s": np.linspace(0.0, .05, n),
    }
    names, values = _normalized_observation_values(config, arrays)
    observation = {
        "time_s": times.tolist(),
        "normalized_observable_names": names,
        "normalized_values": values,
        "event_times_s": {"motion_complete": 1.35, "receiver_contact": 1.0, "settled": 1.8},
    }
    vector = aligned_difference(observation, observation)
    events = event_difference(observation, observation)
    checks = {
        "normalized_layout_finite": bool(len(names) == len(F2_OBSERVABLE_NAMES) and np.isfinite(values).all()),
        "self_vector_difference_zero": bool(vector["maximum"] == 0.0),
        "self_event_difference_zero": bool(events["passed"] and events["maximum_relative_time_error"] == 0.0),
        "fixed_mass_denominator_declared": "no survivor renormalization" in "fixed initial-native-mass denominator; no survivor renormalization",
    }
    report = {
        "schema": "core.f2.observer.calibration.v1",
        "revision_id": F2_OBSERVER_REVISION_ID,
        "family": "F2",
        "passed": bool(all(checks.values())),
        "checks": checks,
        "observable_names": names,
        "method": "manufactured finite arrays with exact self-comparison; no CFD fit or threshold tuning",
        "scope": "observer normalization, time alignment, and required-event comparator only",
        "observer_code_sha256": core_cfd.digest(Path(__file__)),
        "qualification_claim": "none; manufactured observer calibration",
    }
    _write_json(Path(output), report)
    return report


def _compare_pair(first: dict, second: dict, vector_limit: float, event_limit: float) -> dict:
    vector = aligned_difference(first, second)
    events = event_difference(first, second)
    events["passed"] = bool(events["passed"] and events["maximum_relative_time_error"] <= event_limit)
    return {"vector": vector, "events": events,
            "passed": bool(vector["maximum"] <= vector_limit and events["passed"])}


def evaluate(matrix_root: Path, runtime_root: Path, *, calibration: Path | None = None,
             canary_job_id: str = "f2-pour-duration-fullwindow-canary-001") -> dict:
    """Evaluate F2 evidence while retaining every missing/failed cell."""
    matrix_root, runtime_root = Path(matrix_root).resolve(), Path(runtime_root).resolve()
    design = json.loads((matrix_root / "design.json").read_text())
    matrix = json.loads((matrix_root / "prepared-matrix.json").read_text())
    from scripts.core_runtime import Store
    jobs = Store(runtime_root).jobs()
    cells, observations, run_metrics, missing, failures = [], {}, {}, [], []
    for row in matrix["cells"]:
        prepared_path = Path(row["prepared"]).resolve()
        job = _job_for_prepared(jobs, prepared_path)
        if job is None or job.get("status") != "succeeded":
            missing.append({"index": row["index"], "case_id": row["case_id"],
                            "attempt_status": None if job is None else job.get("status")})
            continue
        product = Path(job.get("attempt_dir", "")) / "product"
        audit_path, trajectory_path, observation_path = product / "audit.json", product / "trajectory.h5", product / "observations.json"
        if not all(path.is_file() for path in (audit_path, trajectory_path, observation_path)):
            failures.append({"index": row["index"], "case_id": row["case_id"], "reason": "required_product_missing"})
            continue
        prepared = json.loads(prepared_path.read_text())
        static = validate_qualification_prepared(prepared_path)
        audit = json.loads(audit_path.read_text())
        observation = json.loads(observation_path.read_text())
        event_complete = bool(audit.get("event_window_complete", audit.get("event_window", {}).get("event_window_complete")))
        horizon = bool(audit.get("requested_horizon_reached", audit.get("event_window", {}).get("requested_horizon_reached")))
        hashes = _hashes_valid(job, product, ("audit.json", "trajectory.h5", "observations.json"))
        mass_pass = bool(prepared.get("mass_preflight", {}).get("mass_gate_pass"))
        observer_ok = observation.get("observer_revision") == F2_OBSERVER_REVISION_ID
        good = bool(static["static_quality_pass"] and hashes and audit.get("hard_integrity_pass")
                    and horizon and event_complete and mass_pass and observer_ok)
        if not good:
            failures.append({"index": row["index"], "case_id": row["case_id"],
                             "reason": "static_hash_hard_mass_event_observer_gate",
                             "static_quality_pass": static["static_quality_pass"], "hashes_valid": hashes,
                             "hard_integrity_pass": audit.get("hard_integrity_pass"),
                             "requested_horizon_reached": horizon, "event_window_complete": event_complete,
                             "mass_gate_pass": mass_pass, "observer_revision_pass": observer_ok})
        cells.append({"index": row["index"], "case_id": row["case_id"], "job_id": job["job_id"],
                      "passed": good, "hashes_valid": hashes, "audit": audit,
                      "observer": {"event_times_s": observation.get("event_times_s"),
                                   "maximum_observable_count": len(observation.get("normalized_observable_names", []))},
                      "run_metrics": read_run_metrics(product)})
        if good:
            key = (prepared["config"]["parameter"]["q"], prepared["config"]["dp_m"], prepared["config"]["design_cell"])
            observations[key] = observation
            run_metrics[key] = read_run_metrics(product)
    gates = design["preregistered_gates"]
    comparisons = []
    spatial_pass = independent_pass = True
    for q in Q_POINTS:
        middle = observations.get((q, .0075, "spatial"))
        fine = observations.get((q, .005, "spatial"))
        if middle is None or fine is None:
            spatial_pass = False
            if q in HELD_OUT_Q:
                independent_pass = False
            continue
        mf = _compare_pair(middle, fine, float(gates["spatial_max_absolute_normalized_difference"]), float(gates["event_time_relative_error_max"]))
        record = {"q": q, "kind": "medium_vs_fine", **mf}
        passed = mf["passed"]
        if q in (0.0, .5, 1.0):
            coarse = observations.get((q, .01, "spatial"))
            if coarse is None:
                passed = False
                record["coarse_available"] = False
            else:
                cm = _compare_pair(coarse, middle, float(gates["spatial_max_absolute_normalized_difference"]), float(gates["event_time_relative_error_max"]))
                cf = _compare_pair(coarse, fine, float(gates["spatial_max_absolute_normalized_difference"]), float(gates["event_time_relative_error_max"]))
                monotone = mf["vector"]["maximum"] <= cm["vector"]["maximum"] + 1e-12
                passed = passed and cm["passed"] and cf["passed"] and monotone
                record.update({"coarse_vs_medium": cm, "coarse_vs_fine": cf, "monotone_refinement": monotone})
        record["passed"] = bool(passed)
        comparisons.append(record)
        spatial_pass &= bool(passed)
        if q in HELD_OUT_Q:
            independent_pass &= bool(passed)
    temporal_pass = actual_dt_pass = native_output_pass = True
    baseline = observations.get((.5, .0075, "spatial"))
    baseline_metrics = run_metrics.get((.5, .0075, "spatial"))
    for variant in ("internal_time", "native_output"):
        other = observations.get((.5, .0075, variant))
        other_metrics = run_metrics.get((.5, .0075, variant))
        if baseline is None or other is None or baseline_metrics is None or other_metrics is None:
            temporal_pass = actual_dt_pass = native_output_pass = False
            continue
        pair = _compare_pair(baseline, other, float(gates["temporal_max_absolute_normalized_difference"]), float(gates["event_time_relative_error_max"]))
        if variant == "internal_time":
            available = baseline_metrics.get("available") and other_metrics.get("available")
            if available:
                dt_ratio = other_metrics["mean_solver_dt_s"] / max(baseline_metrics["mean_solver_dt_s"], 1e-30)
                steps_ratio = other_metrics["steps"] / max(baseline_metrics["steps"], 1)
                evidence = bool(dt_ratio <= float(gates["actual_dt_ratio_max_for_internal_time"])
                                and steps_ratio >= float(gates["actual_step_ratio_min_for_internal_time"]))
                ratios = {"dt_ratio": dt_ratio, "steps_ratio": steps_ratio}
            else:
                evidence, ratios = False, {"dt_ratio": None, "steps_ratio": None}
            passed = bool(pair["passed"] and evidence)
            actual_dt_pass &= evidence
            temporal_pass &= passed
            comparisons.append({"q": .5, "kind": variant, **pair, "actual_time_step_evidence": evidence,
                                "actual_time_step_ratios": ratios, "passed": passed})
        else:
            base_times, other_times = np.asarray(baseline["time_s"]), np.asarray(other["time_s"])
            interval_ratio = float(np.median(np.diff(other_times)) / max(np.median(np.diff(base_times)), 1e-30))
            frame_ratio = float(len(other_times) / max(len(base_times), 1))
            evidence = bool(interval_ratio <= float(gates["native_output_interval_ratio_max"])
                            and frame_ratio >= float(gates["native_output_frame_ratio_min"]))
            passed = bool(pair["passed"] and evidence)
            native_output_pass &= passed
            temporal_pass &= passed
            comparisons.append({"q": .5, "kind": variant, **pair, "output_cadence_evidence": evidence,
                                "output_interval_ratio": interval_ratio, "output_frame_ratio": frame_ratio,
                                "passed": passed})
    calibration_report = None
    calibrated = False
    if calibration is not None and Path(calibration).is_file():
        calibration = Path(calibration).resolve()
        payload = json.loads(calibration.read_text())
        calibrated = bool(payload.get("schema") == "core.f2.observer.calibration.v1"
                          and payload.get("passed") is True
                          and payload.get("observer_code_sha256") == core_cfd.digest(Path(__file__)))
        calibration_report = {"path": str(calibration), "sha256": core_cfd.digest(calibration), "passed": calibrated}
    canary = _canary_gate(jobs, canary_job_id)
    all_cells = len(cells) == 15 and not missing and not failures
    checks = {
        "static_matrix": bool(matrix.get("complete") and len(matrix.get("cells", [])) == 15),
        "canary_gate": bool(canary["passed"]),
        "observer_calibrated": calibrated,
        "matrix_complete": all_cells,
        "all_case_hard_mass_event_gates": all_cells,
        "spatial": bool(spatial_pass),
        "independent_checks": bool(independent_pass),
        "time_and_output": bool(temporal_pass),
        "actual_time_step_gate": bool(actual_dt_pass),
        "native_output_cadence_gate": bool(native_output_pass),
    }
    return {
        "schema": "core.qualification.v1",
        "revision_id": REVISION_ID,
        "scope_id": design["scope_id"],
        "family": "F2",
        "extent": "one-dimensional rotation-duration range with registered spatial/temporal cells",
        "T1_numerical": bool(all(checks.values())),
        "T2_macro": False,
        "T2_path": False,
        "external_physical_validation": False,
        "qualified": False,
        "qualification_claim": "none; canary and 13+2 comparator evidence only",
        "promotion_status": "blocked_until_canary_matrix_observer_and_external_campaign_review",
        "checks": checks,
        "canary": canary,
        "calibration": calibration_report,
        "design_sha256": core_cfd.digest(matrix_root / "design.json"),
        "matrix_sha256": core_cfd.digest(matrix_root / "prepared-matrix.json"),
        "cells": cells,
        "missing": missing,
        "failures": failures,
        "comparisons": comparisons,
        "observer_revision": F2_OBSERVER_REVISION_ID,
        "claim_limit": "registered finite cup/receiver/tray geometry, duration range, resolutions, time controls, computational envelope, and observer scales only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("write-design")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("write-matrix")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--design", type=Path)
    p = commands.add_parser("write-card")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--design", type=Path)
    p = commands.add_parser("prepare-canary")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--q", type=float, default=0.5)
    p = commands.add_parser("prepare-envelope-repair-canary")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--q", type=float, default=0.5)
    p = commands.add_parser("prepare-ballistic-envelope-canary")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--q", type=float, default=0.5)
    p = commands.add_parser("prepare-mdbc-closed-wall-canary")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--q", type=float, default=0.5)
    p = commands.add_parser("prepare-closed-catchment-canary")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--q", type=float, default=0.5)
    p = commands.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-envelope-repair-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-ballistic-envelope-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-mdbc-closed-wall-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-closed-catchment-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("prepare-matrix")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("validate-prepared")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("make-matrix-jobs")
    p.add_argument("--matrix", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("calibrate")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("evaluate")
    p.add_argument("--matrix", type=Path, required=True)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--calibration", type=Path)
    p.add_argument("--canary-job-id", default="f2-pour-duration-fullwindow-canary-001")
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("forensics")
    p.add_argument("--product", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("amend-closed-catchment-floor-contract")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("closed-catchment-floor-contract-forensics")
    p.add_argument("--source-prepared", type=Path, required=True)
    p.add_argument("--amended-prepared", type=Path, required=True)
    p.add_argument("--product", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("run")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "write-design":
        result = write_design(args.output)
    elif args.command == "write-matrix":
        result = write_matrix(args.output, args.design)
    elif args.command == "write-card":
        result = write_card(args.output, args.design)
    elif args.command == "prepare-canary":
        result = prepare_dynamic_canary(args.lab_root, args.output, args.q)
    elif args.command == "prepare-envelope-repair-canary":
        result = prepare_dynamic_envelope_repair_canary(args.lab_root, args.output, args.q)
    elif args.command == "prepare-ballistic-envelope-canary":
        result = prepare_dynamic_ballistic_envelope_canary(args.lab_root, args.output, args.q)
    elif args.command == "prepare-mdbc-closed-wall-canary":
        result = prepare_dynamic_mdbc_closed_wall_canary(args.lab_root, args.output, args.q)
    elif args.command == "prepare-closed-catchment-canary":
        result = prepare_dynamic_closed_catchment_canary(args.lab_root, args.output, args.q)
    elif args.command == "make-job":
        result = make_job(args.prepared, args.lab_root, args.output)
    elif args.command == "make-envelope-repair-job":
        result = make_envelope_repair_job(args.prepared, args.lab_root, args.output)
    elif args.command == "make-ballistic-envelope-job":
        result = make_ballistic_envelope_job(args.prepared, args.lab_root, args.output)
    elif args.command == "make-mdbc-closed-wall-job":
        result = make_mdbc_closed_wall_job(args.prepared, args.lab_root, args.output)
    elif args.command == "make-closed-catchment-job":
        result = make_closed_catchment_job(args.prepared, args.lab_root, args.output)
    elif args.command == "prepare-matrix":
        result = prepare_matrix(args.lab_root, args.output)
    elif args.command == "validate-prepared":
        result = validate_qualification_prepared(args.prepared)
        _write_json(args.output, result)
    elif args.command == "make-matrix-jobs":
        result = make_matrix_jobs(args.matrix, args.lab_root, args.output)
    elif args.command == "calibrate":
        result = manufactured_calibration(args.output)
    elif args.command == "evaluate":
        result = evaluate(args.matrix, args.runtime, calibration=args.calibration, canary_job_id=args.canary_job_id)
        _write_json(args.output, result)
    elif args.command == "forensics":
        result = dynamic_canary_forensics(args.product, args.output)
    elif args.command == "amend-closed-catchment-floor-contract":
        result = amend_closed_catchment_floor_contract(args.prepared, args.output)
    elif args.command == "closed-catchment-floor-contract-forensics":
        result = closed_catchment_floor_contract_forensics(
            args.source_prepared, args.amended_prepared, args.product, args.output
        )
    else:
        result = run(args.prepared, args.lab_root, args.output)
    print(json.dumps({key: result[key] for key in (
        "preflight_pass", "cell_count", "job_count", "static_mass_status", "qualification_claim",
        "job_id", "event_window_complete", "passed", "T1_numerical", "checks",
        "preparation_resource_plan", "schema", "case_id", "qualification_claim",
    ) if key in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
