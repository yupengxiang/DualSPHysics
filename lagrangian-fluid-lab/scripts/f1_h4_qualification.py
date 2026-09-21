#!/usr/bin/env python3
"""Freeze the F1 H4 qualification design without running GenCase or CFD.

H4 is a new mDBC boundary recipe.  The old H3 handoff is retained as failure
evidence and as the XML template for a fresh materialization; it is never used
as a qualification receipt.  This entry point writes a 13 spatial + 2
temporal design, validates its fixed generator contract, and can materialize
one XML definition for inspection.  ``write-definition`` does not invoke
GenCase.  Matrix GenCase preparation and all solver jobs remain coordinator
actions after the H4 canary passes.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
SOURCE_TEMPLATE = LAB / (
    "campaigns/core-v1/cfd/f1-h2-bottom-contact-forensics-v1/candidate/"
    "CORE_F1_H2_mdbc_obstacle_q0p50000000_h0p46000000_dp0p007500000000_"
    "canary_bottom_face_Def.xml"
)
CANARY_JOB = LAB / (
    "campaigns/core-v1/cfd/f1-h4-obstacle-normal-orientation-v2/"
    "f1-h4-obstacle-normal-orientation-canary-job.json"
)
CANARY_SUBMISSION = LAB / (
    "campaigns/core-v1/cfd/f1-h4-obstacle-normal-orientation-v2/"
    "root-frozen/submission.json"
)
STATIC_AUDIT = LAB / (
    "campaigns/core-v1/cfd/f1-h4-obstacle-normal-orientation-v2/"
    "static-normal-orientation-audit.json"
)
STATIC_PROPOSAL = LAB / (
    "campaigns/core-v1/cfd/f1-h4-obstacle-normal-orientation-v2/"
    "f1-h4-obstacle-normal-orientation-canary-proposal-v1.json"
)
OBSERVER_CODE = LAB / "scripts/core_f1_qualification.py"
CALIBRATION = LAB / "campaigns/core-v1/cfd/f1-h3-qualification-handoff-v1/manufactured-observer-calibration.json"
GENCASE = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"

SCHEMA = "core.f1.h4.qualification_design.v1"
PROPOSAL_SCHEMA = "core.f1.h4.qualification_proposal.v1"
FAMILY = "F1"
SCOPE_ID = "F1_single_obstacle_mdbc_normal_orientation_height_range_v1"
REVISION_ID = "F1_H4_obstacle_normal_orientation_mdbc_13plus2_v1"
RECIPE_ID = "F1_H4_obstacle_normal_orientation_mdbc_v1"
RECIPE = "mdbc_native_boundary_orientation_repair"
OBSERVER_REVISION = "F1_H1_geometry_observer_qualification_v1"
RESOLUTIONS = (0.01, 0.0075, 0.005)
Q_VALUES = (0.0, 0.5, 1.0, 0.25, 0.75)
BASE_TIME_CONTROL = {"DtIni": 0.000345882, "DtMin": 0.0000172941, "DtFixed": 0.0}
HALF_TIME_CONTROL = {key: value / 2.0 for key, value in BASE_TIME_CONTROL.items()}
EVENT_WINDOW_S = 2.2
MAX_EXTENSION_S = 4.4
OUTPUT_INTERVAL_S = 0.02
NATIVE_OUTPUT_INTERVAL_S = 0.004
HEIGHT_RANGE = (0.4, 0.52)
TANK_LOW = (0.0, 0.0, 0.0)
TANK_SIZE = (1.2, 0.4, 0.6)
OBSTACLE_LOW = (0.68, 0.15, 0.0)
OBSTACLE_SIZE = (0.12, 0.10, 0.34)
FLUID_LOW = (0.04, 0.04, 0.04)
FLUID_XY_SIZE = (0.34, 0.32)
RUNTIME_DOMAIN = {
    "xmin": -0.3,
    "xmax": 1.5,
    "ymin": -0.099375,
    "ymax": 0.496875,
    "zmin": -0.15,
    "zmax": 1.8,
}
OBSERVABLE_NAMES = [
    "center_of_mass_x_over_tank_length",
    "center_of_mass_y_over_tank_width",
    "center_of_mass_z_over_tank_height",
    "kinetic_energy_over_initial_potential_energy",
    "active_mass_over_initial_native_mass",
    "obstacle_approach_mass_fraction",
    "downstream_mass_fraction",
    "front_bypass_mass_fraction",
    "back_bypass_mass_fraction",
    "rejoin_mass_fraction",
    "downstream_lateral_centroid_over_tank_width",
    "minimum_obstacle_clearance_over_tank_length",
    "returning_mass_fraction",
]
EVENT_NAMES = ["approach", "downstream", "split", "rejoin", "return"]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def ref(path: Path, role: str) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"missing {role}: {path}")
    return {"path": str(path), "sha256": digest(path), "role": role}


def write_json(path: Path, value: dict) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _float_tag(value: float, places: int = 8) -> str:
    return f"{float(value):.{places}f}".replace("-", "m").replace(".", "p")


def water_height(q: float) -> float:
    q = float(q)
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0,1]")
    return 0.40 + 0.12 * q


def native_box(dp: float, height: float) -> dict:
    """Return the fixed cell-centre sampling contract used by F1."""
    dp = float(dp)
    size = [FLUID_XY_SIZE[0], FLUID_XY_SIZE[1], float(height)]
    # H4 inherits the H3 mDBC cell-centre convention.  The source template
    # has pointref=dp/2, so choose the nearest in-box centre on that lattice;
    # at dp=.0075 this reproduces .04125 m rather than the old H1 .045 m
    # centre.  Changing this rule would change the initial discrete state.
    first = [math.ceil(value / dp - 0.5 - 1.0e-10) for value in FLUID_LOW]
    counts = [
        math.ceil(size[0] / dp - 1.0e-10),
        math.ceil(size[1] / dp - 1.0e-10),
        math.floor(size[2] / dp + 1.0e-10),
    ]
    if any(count <= 0 for count in counts):
        raise ValueError("registered fluid box does not contain a positive centre lattice")
    first_center = [(index + 0.5) * dp for index in first]
    draw_size = [(count - 1) * dp for count in counts]
    continuous_mass = math.prod(size) * 1000.0
    discrete_mass = math.prod(counts) * dp**3 * 1000.0
    return {
        "continuous_low_m": list(FLUID_LOW),
        "continuous_size_m": size,
        "first_center_m": first_center,
        "draw_size_m": draw_size,
        "counts": counts,
        "particle_count": int(math.prod(counts)),
        "continuous_mass_kg": continuous_mass,
        "discrete_mass_kg": discrete_mass,
        "native_cell_centre_sampling": True,
    }


def _time_control(design_cell: str) -> dict:
    if design_cell == "internal_time":
        return deepcopy(HALF_TIME_CONTROL)
    return deepcopy(BASE_TIME_CONTROL)


def _case_id(q: float, dp: float, design_cell: str) -> str:
    suffix = {
        "spatial": "spatial",
        "internal_time": "internal_time",
        "native_output": "native_output",
    }[design_cell]
    return (
        "CORE_F1_H4_mdbc_obstacle_normal_orientation_"
        f"q{_float_tag(q)}_h{_float_tag(water_height(q))}_"
        f"dp{_float_tag(dp, 12)}_{suffix}_qualification"
    )


def _observer() -> dict:
    return {
        "schema": "core.f1.observations.v1",
        "revision_id": OBSERVER_REVISION,
        "observable_names": list(OBSERVABLE_NAMES),
        "normalization": {
            "mass_denominator": "initial_native_fluid_mass_kg_from_frame_zero; never survivor-renormalized",
            "center_of_mass": "active native mass weighted, divided by fixed tank dimensions",
            "kinetic_energy": "active kinetic energy divided by frame-zero native initial gravitational potential energy",
            "obstacle_clearance": "signed nearest distance to finite obstacle, divided by tank length",
            "channel_fractions": "fixed initial-native-mass denominator; front/back/rejoin regions use obstacle geometry",
            "time": "linear interpolation on common registered output grid; no point-index comparison",
        },
        "geometry": {
            "obstacle_source": "config.continuum_geometry.obstacle",
            "container_source": "config.continuum_geometry.tank",
            "clearance": "finite center_obstacle box, 2dp approach margin",
            "front_channel": "downstream x and y < obstacle ymin - 2dp",
            "back_channel": "downstream x and y > obstacle ymax + 2dp",
            "rejoin": "downstream x >= obstacle xmax + 4dp and lateral centroid within 0.125 tank widths of centerline",
        },
        "event_thresholds": {
            "approach_mass_fraction": 0.01,
            "downstream_mass_fraction": 0.05,
            "split_each_channel_mass_fraction": 0.01,
            "rejoin_mass_fraction": 0.05,
            "return_com_x_drop_m": "max(0.02, 2*dp)",
            "return_separation_s": 0.1,
            "post_return_tail_s": "sqrt(1.2/9.81)",
        },
        "event_order": list(EVENT_NAMES),
        "qualification_use": "geometry-aware diagnostic and numerical consistency comparison; no external physical truth claim",
    }


def _wall_spec() -> dict:
    return {
        "container_interior": {
            "xmin": TANK_LOW[0], "xmax": TANK_LOW[0] + TANK_SIZE[0],
            "ymin": TANK_LOW[1], "ymax": TANK_LOW[1] + TANK_SIZE[1],
            "zmin": TANK_LOW[2], "zmax": TANK_LOW[2] + TANK_SIZE[2],
        },
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "obstacles": [{
            "id": "center_obstacle",
            "xmin": OBSTACLE_LOW[0], "xmax": OBSTACLE_LOW[0] + OBSTACLE_SIZE[0],
            "ymin": OBSTACLE_LOW[1], "ymax": OBSTACLE_LOW[1] + OBSTACLE_SIZE[1],
            "zmin": OBSTACLE_LOW[2], "zmax": OBSTACLE_LOW[2] + OBSTACLE_SIZE[2],
        }],
        "runtime_domain": dict(RUNTIME_DOMAIN),
    }


def cell_config(q: float, dp: float, design_cell: str) -> dict:
    if design_cell not in {"spatial", "internal_time", "native_output"}:
        raise ValueError(f"unknown design cell: {design_cell}")
    if design_cell != "spatial" and not math.isclose(dp, 0.0075):
        raise ValueError("temporal cells are fixed at dp=.0075")
    height = water_height(q)
    output = NATIVE_OUTPUT_INTERVAL_S if design_cell == "native_output" else OUTPUT_INTERVAL_S
    cfl = 0.1 if design_cell == "internal_time" else 0.2
    box = native_box(dp, height)
    return {
        "schema": "core.cfd.v1",
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": _case_id(q, dp, design_cell),
        "recipe_id": RECIPE_ID,
        "recipe": RECIPE,
        "stage": "qualification",
        "design_cell": design_cell,
        "temporal_variant": None if design_cell == "spatial" else design_cell,
        "qualification_claim": "none",
        "qualified": False,
        "qualification_only": True,
        "parameter": {
            "name": "initial_water_height_m",
            "q": float(q),
            "value": height,
            "candidate_range": list(HEIGHT_RANGE),
            "mapping": "h(q)=0.40+0.12*q m",
        },
        "dp_m": float(dp),
        "fluid_box": {"low": list(FLUID_LOW), "size": [*FLUID_XY_SIZE, height], "mkfluid": 0},
        "initialization_rule": {
            "name": "cell_centre_drawbox_sampling",
            "reason": "registered centre lattice stays inside the declared continuous box",
            "mass_rescaling": False,
            "continuum_box_preserved": True,
        },
        "continuum_geometry": {
            "tank": {"low": list(TANK_LOW), "size": list(TANK_SIZE)},
            "obstacle": {"id": "center_obstacle", "low": list(OBSTACLE_LOW), "size": list(OBSTACLE_SIZE)},
            "density_kg_m3": 1000.0,
            "unchanged": True,
        },
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "initial_velocity_m_s": [0.0, 0.0, 0.0],
        "wall_bounds": _wall_spec()["container_interior"],
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "wall_spec": _wall_spec(),
        "runtime_domain_zmax_m": RUNTIME_DOMAIN["zmax"],
        "boundary_semantics": "mDBC no-slip; solid-side obstacle shell and boundary-to-interface normals; tank inner-face recipe retained",
        "source_definition_template": str(SOURCE_TEMPLATE.resolve()),
        "cfl": cfl,
        "output_interval_s": output,
        "time_max_s": EVENT_WINDOW_S,
        "event_window": {
            "initial_time_max_s": EVENT_WINDOW_S,
            "maximum_extended_time_max_s": MAX_EXTENSION_S,
            "output_interval_s": output,
            "extension_policy": "single whole-scope doubling after a frozen right-censor",
            "completion_required_for_qualification": True,
        },
        "physical_case_id": "L2_C1_F1_obstacle_nominal",
        "lineage_group_id": "L2_C1_F1_obstacle_nominal_height_range",
        "source_label_semantics": "native numerical source identity, no material qualification",
        "time_control": _time_control(design_cell),
        "observer_revision": OBSERVER_REVISION,
        "observer_observable_names": list(OBSERVABLE_NAMES),
        "event_registration": _observer()["event_thresholds"],
        "solver_arguments": ["-mdbc_noslip:1"],
        "h4_boundary_recipe": {
            "continuum_geometry_changed": False,
            "mass_rescaling": False,
            "obstacle_shell_point": "obstacle_low + dp/2",
            "obstacle_shell_size": "obstacle_size - dp",
            "obstacle_shell_layers": "0,-1,-2",
            "obstacle_normal_invert": False,
            "tank_normal_invert": True,
            "all_obstacle_faces": ["bottom", "top", "left", "right", "front", "back"],
            "zero_normals_allowed": 0,
            "exact_fluid_boundary_overlap_allowed": 0,
        },
        "generator_contract": {
            "source_template_role": "H3 XML template only; no H3 qualification inheritance",
            "definition_entrypoint": "scripts/f1_h4_qualification.py write-definition",
            "gencase_required_after_canary": True,
            "gen_case_binary": str(GENCASE.resolve()),
            "pointref": "dp/2",
            "fluid_sampling": box,
            "physical_geometry_hash_contract": "tank/obstacle/continuum fluid box unchanged except registered initial height",
        },
        "canary_dependency": {
            "job_id": "f1-h4-obstacle-normal-orientation-canary-001",
            "required_before_materialization": True,
            "required_status": "succeeded with hard_integrity_pass, mass gate, and complete event window",
        },
    }


def _base_cells() -> list[dict]:
    cells: list[dict] = []
    for q in (0.0, 0.5, 1.0):
        for dp in RESOLUTIONS:
            cells.append(cell_config(q, dp, "spatial"))
    for q in (0.25, 0.75):
        for dp in RESOLUTIONS[1:]:
            cells.append(cell_config(q, dp, "spatial"))
    cells.append(cell_config(0.5, 0.0075, "internal_time"))
    cells.append(cell_config(0.5, 0.0075, "native_output"))
    return cells


def build_design() -> dict:
    cells = _base_cells()
    if len(cells) != 15:
        raise ValueError("H4 design must contain exactly 15 cells")
    return {
        "schema": SCHEMA,
        "created_at": "2026-09-20T00:00:00+00:00",
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "recipe_id": RECIPE_ID,
        "recipe": RECIPE,
        "qualification_claim": "none",
        "candidate_status": "pre_registered_unqualified; blocked until H4 canary receipt",
        "qualification_only": True,
        "cell_count": len(cells),
        "spatial_cells": 13,
        "temporal_cells": 2,
        "spatial_resolutions_m": list(RESOLUTIONS),
        "one_dimensional_parameter": {
            "name": "initial_water_height_m",
            "coordinate": "q in [0,1]",
            "mapping": "h(q)=0.40+0.12*q m",
            "q_values": list(Q_VALUES),
            "height_values_m": [water_height(q) for q in Q_VALUES],
            "range_m": list(HEIGHT_RANGE),
        },
        "fixed_geometry": {
            "tank": {"low": list(TANK_LOW), "size": list(TANK_SIZE)},
            "obstacle": {"id": "center_obstacle", "low": list(OBSTACLE_LOW), "size": list(OBSTACLE_SIZE)},
            "initial_fluid_xy_m": {"low": list(FLUID_LOW[:2]), "size": list(FLUID_XY_SIZE)},
            "initialization_rule": "cell-centre drawbox sampling of declared box; native rho*dp^3 mass",
            "density_kg_m3": 1000.0,
            "gravity_m_s2": -9.81,
            "runtime_domain": dict(RUNTIME_DOMAIN),
            "continuum_geometry_changed": False,
            "boundary_discretization_recipe": "H4 solid-side obstacle shell; dp-dependent generated boundary layers",
        },
        "registered_window": {
            "initial_time_max_s": EVENT_WINDOW_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "maximum_extended_time_max_s": MAX_EXTENSION_S,
            "extension_policy": "one whole-scope doubling after a frozen event right-censor",
            "event_completion_required": True,
        },
        "observer": _observer(),
        "preregistered_gates": {
            "spatial_max_absolute_normalized_difference": 0.05,
            "temporal_fraction_of_spatial_budget": 0.20,
            "temporal_max_absolute_normalized_difference": 0.01,
            "event_time_relative_error_max": 0.05,
            "actual_dt_ratio_max_for_internal_time": 0.80,
            "actual_step_ratio_min_for_internal_time": 1.25,
            "native_output_interval_ratio_max": 0.30,
            "native_output_frame_ratio_min": 3.0,
            "closed_wall_endpoint_tolerance_m": 1.0e-8,
            "saved_chord_crossings_allowed": 0,
            "source_initial_mass_relative_error_max": 0.025,
            "initial_mass_spread_over_continuous_mass_max": 0.03,
            "no_survivor_renormalization": True,
            "zero_native_normals_allowed": 0,
            "exact_fluid_boundary_overlap_allowed": 0,
            "canary_hard_integrity_required": True,
            "all_15_cells_required": True,
        },
        "temporal_time_control": {
            "base": dict(BASE_TIME_CONTROL),
            "internal_time": dict(HALF_TIME_CONTROL),
            "actual_evidence": "solver/Run.csv Steps and PhysicalTime, not config CFL alone",
        },
        "generator": {
            "entrypoint": ref(Path(__file__), "H4 qualification generator/config entrypoint"),
            "gencase_binary": ref(GENCASE, "fixed GenCase binary"),
            "source_template": ref(SOURCE_TEMPLATE, "H3 XML template used only as fresh H4 source"),
            "static_h4_audit": ref(STATIC_AUDIT, "H4 canary static normal audit"),
            "definition_rule": "patch source XML for each registered dp/q/time cell, then run this exact GenCase binary; no reuse of H3 generated BI4",
            "obstacle_shell_rule": "point=low+dp/2, size=continuum_size-dp, layers=0,-1,-2",
            "normal_rule": "all obstacle faces setnormalinvert=false; tank inner faces setnormalinvert=true",
            "source_snapshot_required": True,
        },
        "canary_dependency": {
            "job": ref(CANARY_JOB, "H4 canary job proposal"),
            "submission": ref(CANARY_SUBMISSION, "root H4 canary submission receipt"),
            "static_proposal": ref(STATIC_PROPOSAL, "H4 static canary proposal"),
            "required_pass": ["hard_integrity_pass", "source_mass_gate_pass", "requested_horizon_reached", "event_window_complete", "full_solid_obstacle_audit"],
            "required_before_matrix_materialization": True,
        },
        "calibration_dependency": {
            "observer_code": ref(OBSERVER_CODE, "frozen geometry-aware F1 observer"),
            "manufactured_calibration": ref(CALIBRATION, "manufactured observer calibration"),
            "external_physical_validation": False,
            "reuse_scope": "observer implementation only; no H3 physical or qualification evidence inherited",
        },
        "cells": cells,
        "matrix_materialization": {
            "authorized_now": False,
            "definition_files_written": False,
            "gen_case_run": False,
            "solver_run": False,
            "jobs_written": False,
            "central_ledger_written": False,
            "after_canary_pass": "materialize all 15 H4 cells from this generator contract, then static hash/mass/normal/overlap preflight before any solver jobs",
        },
        "legacy_records": {
            "h3_handoff_is_not_reusable": True,
            "h3_handoff_reason": "H3 obstacle-bottom topology recipe and generated input hashes differ from H4 solid-side normal recipe",
            "h1_matrix_reusable": False,
            "h1_matrix_reason": "native DBC source and generated assets do not bind H4 mDBC boundary recipe",
        },
    }


def validate_design(design: dict) -> dict:
    if design.get("schema") != SCHEMA:
        raise ValueError("wrong H4 design schema")
    for key, expected in (("family", FAMILY), ("scope_id", SCOPE_ID), ("revision_id", REVISION_ID), ("recipe_id", RECIPE),):
        if key == "recipe_id":
            expected = RECIPE_ID
        if design.get(key) != expected:
            raise ValueError(f"H4 design {key} mismatch")
    if design.get("qualification_only") is not True or design.get("qualification_claim") != "none":
        raise ValueError("H4 design admission flags are not qualification-only")
    cells = design.get("cells")
    if not isinstance(cells, list) or len(cells) != 15 or design.get("cell_count") != 15:
        raise ValueError("H4 design denominator is not 15")
    seen = {(float(c["parameter"]["q"]), float(c["dp_m"]), c["design_cell"]) for c in cells}
    expected = {(q, dp, "spatial") for q in (0.0, 0.5, 1.0) for dp in RESOLUTIONS}
    expected |= {(q, dp, "spatial") for q in (0.25, 0.75) for dp in RESOLUTIONS[1:]}
    expected |= {(0.5, 0.0075, "internal_time"), (0.5, 0.0075, "native_output")}
    if seen != expected:
        raise ValueError(f"H4 design cells differ from fixed 13+2 set: {seen ^ expected}")
    for cell in cells:
        if cell.get("scope_id") != SCOPE_ID or cell.get("revision_id") != REVISION_ID:
            raise ValueError("cell scope/revision mismatch")
        if cell.get("qualification_only") is not True or cell.get("qualified") is not False:
            raise ValueError("cell is not explicitly unqualified")
        recipe = cell.get("h4_boundary_recipe", {})
        if recipe.get("obstacle_normal_invert") is not False or recipe.get("tank_normal_invert") is not True:
            raise ValueError("cell H4 normal recipe changed")
        if recipe.get("obstacle_shell_layers") != "0,-1,-2":
            raise ValueError("cell H4 shell layer contract changed")
    if design.get("matrix_materialization", {}).get("authorized_now") is not False:
        raise ValueError("matrix materialization is unexpectedly authorized")
    return {"schema": SCHEMA, "cell_count": 15, "spatial_cells": 13, "temporal_cells": 2, "valid": True}


def build_proposal(design: dict) -> dict:
    validate_design(design)
    return {
        "schema": PROPOSAL_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "recipe_id": RECIPE_ID,
        "status": "blocked_until_h4_canary_result",
        "qualification_claim": "none; design/proposal only",
        "canary_gate": design["canary_dependency"],
        "generator_contract": design["generator"],
        "qualification_design": {
            "cell_count": 15,
            "spatial_cells": 13,
            "temporal_cells": 2,
            "q_values": list(Q_VALUES),
            "height_range_m": list(HEIGHT_RANGE),
            "resolutions_m": list(RESOLUTIONS),
            "initial_window_s": EVENT_WINDOW_S,
            "single_extension_window_s": MAX_EXTENSION_S,
            "observer_revision": OBSERVER_REVISION,
        },
        "admission_requirements": {
            "canary_must_pass_before_any_matrix_materialization": True,
            "canary_result_must_bind_source_snapshot_and_all_output_hashes": True,
            "all_15_cells_must_be_freshly_generated_with_h4_recipe": True,
            "h3_generated_inputs_must_not_be_reused": True,
            "mass_rescaling": False,
            "continuum_geometry_change": False,
            "hard_integrity_and_event_gates_unchanged": True,
        },
        "after_canary_pass": {
            "step_1": "freeze source snapshot containing this entrypoint, core_f1.py, core_cfd.py, finite_wall_audit.py, observer/evaluator, and exact native tools",
            "step_2": "write fresh H4 definitions for all 15 cells with registered q/dp/time controls",
            "step_3": "run GenCase for all 15 cells and require zero normals, no exact fluid-boundary overlap, fixed mass gates, and all face contract checks",
            "step_4": "only after static preflight, write scheduler-neutral 15 qualification job specs; root remains submission owner",
            "step_5": "evaluate all 15 products using actual temporal/cadence evidence and geometry-aware observer",
        },
        "on_canary_failure": {
            "status": "terminal_negative_result",
            "retain_h4_canary_product_and_denominator": True,
            "materialize_matrix": False,
            "launch_more_same_class_canaries": False,
            "qualification_claim": "none",
        },
        "production_after_t1_only": {
            "registered_case_count": 32,
            "first_batch_indices": [0, 4, 8, 13, 18, 23, 27, 31],
            "remaining_batch_size": 24,
            "qualification_inheritance": False,
            "preparation_now": False,
        },
        "execution": {
            "gen_case_run": False,
            "solver_run": False,
            "gpu_launched": False,
            "jobs_written": False,
            "ledger_written": False,
        },
    }


def _find_obstacle_draw(nodes: list[ET.Element], mk: str | None) -> ET.Element | None:
    active = None
    for node in nodes:
        if node.tag == "setmkbound":
            active = node.get("mk")
        elif node.tag == "setmkvoid":
            active = "void"
        elif node.tag == "drawbox" and active == mk:
            point = node.find("./point")
            if point is not None and math.isclose(float(point.get("x", "nan")), OBSTACLE_LOW[0] - 0.0075 / 2, abs_tol=1e-8):
                return node
    return None


def write_definition(source: Path, target: Path, dp: float, q: float, design_cell: str) -> dict:
    """Write one H4 XML definition; this command never invokes GenCase."""
    source = Path(source).resolve()
    target = Path(target).resolve()
    if target.exists():
        raise ValueError(f"refusing to overwrite definition: {target}")
    if not math.isclose(float(dp), 0.0075, abs_tol=1e-12) and design_cell != "spatial":
        raise ValueError("temporal H4 cells require dp=.0075")
    config = cell_config(q, dp, design_cell)
    root = ET.parse(source).getroot()
    definition = root.find(".//casedef/geometry/definition")
    if definition is None:
        raise ValueError("source lacks geometry definition")
    definition.set("dp", f"{dp:.17g}")
    pointref = definition.find("./pointref")
    if pointref is not None:
        pointref.attrib.update({axis: f"{dp / 2.0:.17g}" for axis in "xyz"})
    mainlist = root.find(".//casedef/geometry/commands/mainlist")
    normals = root.find(".//casedef/geometry/commands/list[@name='GeometryForNormals']")
    if mainlist is None or normals is None:
        raise ValueError("source lacks H4 geometry command lists")
    obstacle_bound = _find_obstacle_draw(list(mainlist), "1")
    obstacle_void = _find_obstacle_draw(list(mainlist), "void")
    if obstacle_bound is None or obstacle_void is None:
        raise ValueError("source obstacle boundary/void drawboxes are missing")
    tank_bound = None
    active = None
    for node in list(mainlist):
        if node.tag == "setmkbound":
            active = node.get("mk")
        elif node.tag == "drawbox" and active == "0" and tank_bound is None:
            tank_bound = node
    if tank_bound is None:
        raise ValueError("source tank boundary drawbox is missing")

    def set_box(node: ET.Element, low: tuple[float, float, float], size: tuple[float, float, float], layers: str | None = None) -> None:
        node.find("./point").attrib.update({axis: f"{value:.17g}" for axis, value in zip("xyz", low)})
        node.find("./size").attrib.update({axis: f"{value:.17g}" for axis, value in zip("xyz", size)})
        if layers is not None:
            layer = node.find("./layers")
            if layer is None:
                layer = ET.SubElement(node, "layers")
            layer.set("vdp", layers)

    set_box(tank_bound, tuple(-dp / 2.0 for _ in range(3)), tuple(TANK_SIZE[i] + dp for i in range(3)), "0,1,2")
    set_box(obstacle_void, tuple(OBSTACLE_LOW[i] - dp / 2.0 for i in range(3)), tuple(OBSTACLE_SIZE[i] + dp for i in range(3)), "0,1,2")
    set_box(obstacle_bound, tuple(OBSTACLE_LOW[i] + dp / 2.0 for i in range(3)), tuple(OBSTACLE_SIZE[i] - dp for i in range(3)), "0,-1,-2")

    fluid_seen = False
    fluid_draw = None
    for node in list(mainlist):
        if node.tag == "setmkfluid" and node.get("mk") == "0":
            fluid_seen = True
        elif fluid_seen and node.tag == "drawbox":
            fluid_draw = node
            break
    if fluid_draw is None:
        raise ValueError("source fluid drawbox is missing")
    box = native_box(dp, water_height(q))
    set_box(fluid_draw, tuple(box["first_center_m"]), tuple(box["draw_size_m"]))

    obstacle_normal = None
    for node in list(normals):
        if node.tag != "drawbox":
            continue
        point = node.find("./point")
        fill = {part.strip() for part in (node.findtext("./boxfill") or "").split("|")}
        if point is not None and fill == {"bottom", "top", "left", "right", "front", "back"} and math.isclose(float(point.get("x", "nan")), OBSTACLE_LOW[0], abs_tol=1e-8):
            obstacle_normal = node
            break
    if obstacle_normal is None:
        raise ValueError("source obstacle normal drawbox is missing")
    previous = list(normals).index(obstacle_normal) - 1
    if previous < 0 or list(normals)[previous].tag != "setnormalinvert" or list(normals)[previous].get("invert") != "false":
        index = list(normals).index(obstacle_normal)
        normals.insert(index, ET.Element("setnormalinvert", {"invert": "false"}))
    obstacle_normal.find("./boxfill").text = "bottom | top | left | right | front | back"

    params = root.find(".//execution/parameters")
    if params is None:
        raise ValueError("source execution parameters are missing")

    def set_param(key: str, value: float) -> None:
        node = params.find(f"parameter[@key='{key}']")
        if node is None:
            node = ET.SubElement(params, "parameter", {"key": key})
        node.set("value", f"{value:.17g}")

    set_param("TimeMax", EVENT_WINDOW_S)
    set_param("TimeOut", config["output_interval_s"])
    for key, value in config["time_control"].items():
        set_param(key, value)
    cfl = root.find(".//casedef/constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("source CFL field is missing")
    cfl.set("value", f"{config['cfl']:.17g}")
    ET.indent(root, space="    ")
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return {
        "schema": "core.f1.h4.definition_materialization.v1",
        "definition": str(target),
        "definition_sha256": digest(target),
        "source_template": str(source),
        "source_template_sha256": digest(source),
        "dp_m": dp,
        "q": q,
        "design_cell": design_cell,
        "gencase_invoked": False,
        "solver_invoked": False,
        "h4_shell_formula": "point=low+dp/2; size=continuum_size-dp; layers=0,-1,-2",
        "obstacle_normal_invert": False,
        "tank_normal_invert": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("write-design")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("validate-design")
    p.add_argument("--design", type=Path, required=True)
    p.add_argument("--output", type=Path)
    p = sub.add_parser("write-proposal")
    p.add_argument("--design", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("write-definition")
    p.add_argument("--source", type=Path, default=SOURCE_TEMPLATE)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dp", type=float, required=True)
    p.add_argument("--q", type=float, required=True)
    p.add_argument("--design-cell", choices=["spatial", "internal_time", "native_output"], default="spatial")
    args = parser.parse_args()
    if args.command == "write-design":
        design = build_design()
        validate_design(design)
        write_json(args.output, design)
        print(json.dumps({"status": "design_written", "cells": 15, "gen_case_run": False, "solver_run": False}, indent=2))
        return 0
    if args.command == "validate-design":
        design = json.loads(Path(args.design).read_text())
        result = validate_design(design)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "write-proposal":
        design = json.loads(Path(args.design).read_text())
        result = build_proposal(design)
        result["design"] = ref(Path(args.design), "H4 qualification design")
        write_json(args.output, result)
        print(json.dumps({"status": result["status"], "cells": 15, "gen_case_run": False, "solver_run": False}, indent=2))
        return 0
    result = write_definition(args.source, args.output, args.dp, args.q, args.design_cell)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
