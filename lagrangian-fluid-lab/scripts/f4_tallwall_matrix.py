#!/usr/bin/env python3
"""Prepare and audit the independent F4 1.2 m tall-wall qualification matrix.

This module owns only the tall-wall matrix proposal.  It calls the frozen
``core_cfd.prepare`` implementation for CPU GenCase/native preflight and never
launches a solver.  The scope is independent of the 0.6 m F4 qualification
lineage; a passing tall-wall canary supplies input provenance but no inherited
range qualification.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd


SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
REVISION_ID = "F4_tallwall120_13plus2_v2"
RECIPE_ID = "F4_mdbc_laminar_nu1e6_tallwall120_v1"
RECIPE = "mdbc_native"
HEIGHT_M = 1.2
HORIZON_S = 4.34
OUTPUT_INTERVAL_S = 0.02
NATIVE_OUTPUT_INTERVAL_S = 0.004
BASE_CFL = 0.05
TIME_CFL = 0.025
TIME_DT_INI_S = 0.0001729410698200235
TIME_DT_MIN_S = 8.647053619852314e-06
BASE_DT_INI_S = 0.000345882139640047
BASE_DT_MIN_S = 1.729410723970463e-05
DP_VALUES = (0.01, 0.0075, 0.005)
ANCHOR_Q = (0.0, 0.5, 1.0)
HELD_OUT_Q = (0.25, 0.75)
OBSERVATION_VERSION = "fixed_015m_vertical_reference060_v2"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def q_text(q: float) -> str:
    return f"{q:.8f}".replace(".", "p")


def dp_text(dp: float) -> str:
    return f"{dp:.12f}".replace(".", "p")


def expected_signature() -> list[tuple[float, float, str]]:
    cells: list[tuple[float, float, str]] = []
    for q in (0.0, 0.5, 1.0, 0.25, 0.75):
        resolutions = DP_VALUES if q in ANCHOR_Q else DP_VALUES[1:]
        cells.extend((q, dp, "spatial") for dp in resolutions)
    cells.extend(((0.5, 0.0075, "internal_time"), (0.5, 0.0075, "native_output")))
    return cells


def base_config(q: float, dp: float, design_cell: str) -> dict:
    drop_x = 0.25 + 0.22 * q
    pool = {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18], "mkfluid": 0}
    drop = {"low": [drop_x, 0.12, 0.4], "size": [0.26, 0.16, 0.14], "mkfluid": 1}
    case_id = (
        f"F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q{q_text(q)}_DP{dp_text(dp)}_{design_cell}"
    ).upper()
    analytic_horizon = core_cfd.event_horizon(pool, drop, cadence=OUTPUT_INTERVAL_S)
    # Keep the analytic T0=3.84 s calculation visible, while binding the
    # actual qualification execution window and its one allowed extension to
    # the registered 4.34/8.68 s scope values.
    horizon = dict(analytic_horizon)
    horizon.update(
        analytic_initial_horizon_s=analytic_horizon["initial_horizon_s"],
        analytic_maximum_extended_horizon_s=analytic_horizon["maximum_extended_horizon_s"],
        initial_horizon_s=HORIZON_S,
        maximum_extended_horizon_s=2 * HORIZON_S,
        execution_window_s=HORIZON_S,
        extension_window_s=2 * HORIZON_S,
        analytic_horizon_is_design_calculation_only=True,
    )
    config = {
        "schema": "core.cfd.v1",
        "family": "F4",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": case_id,
        "recipe_id": RECIPE_ID,
        "recipe": RECIPE,
        "stage": "qualification",
        "qualification_claim": "none",
        "qualified": False,
        "qualification_only": True,
        "split": "qualification_only",
        "design_cell": design_cell,
        "parameter": {
            "name": "drop_left_x_m",
            "q": q,
            "value": drop_x,
            "candidate_range": [0.25, 0.47],
        },
        "dp_m": dp,
        "pool": pool,
        "drop": drop,
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "initial_drop_velocity_m_s": [0.0, 0.0, -0.5],
        "wall_bounds": {"xmin": 0.0, "xmax": 1.2, "ymin": 0.0, "ymax": 0.4,
                        "zmin": 0.0, "zmax": HEIGHT_M},
        "closed_faces": ["bottom", "left", "right", "front", "back"],
        "open_faces": ["top"],
        "container_height_m": HEIGHT_M,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "time_max_s": HORIZON_S,
        "horizon": horizon,
        "registered_window": {
            "execution_time_max_s": HORIZON_S,
            "maximum_extended_time_max_s": 2 * HORIZON_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "analytic_t0_s": analytic_horizon["initial_horizon_s"],
            "analytic_t0_is_execution_window": False,
        },
        "cfl": BASE_CFL,
        "boundary_layers": [0, 1, 2],
        "source_label_semantics": "initial native Mk numerical source partition; not material truth",
        "physical_case_id": f"F4_tallwall120_drop_x_q{q:g}",
        "lineage_group_id": f"F4_tallwall120_drop_x_q{q:g}",
        "physical_kinematic_viscosity_m2_s": 1e-6,
        "viscosity_formulation": "laminar",
        "observation_version": OBSERVATION_VERSION,
        "physical_geometry_changed": True,
        "qualification_inheritance": False,
        "static_canary_basis": {
            "source_scope": "F4_resting_pool_laminar_tallwall120_x_v1",
            "height_m": HEIGHT_M,
            "old_height_m": 0.6,
            "top_remains_open": True,
            "same_continuum_pool_and_drop": True,
            "same_nu_m2_s": 1e-6,
            "old_failures_retained": True,
            "qualification_inherited": False,
        },
    }
    if design_cell == "internal_time":
        config.update(
            cfl=TIME_CFL,
            dt_ini_s=TIME_DT_INI_S,
            dt_min_s=TIME_DT_MIN_S,
            time_control_variant="actual_dt_floor_half",
            time_control_contract={
                "baseline": {"cfl": BASE_CFL, "DtIni_s": BASE_DT_INI_S, "DtMin_s": BASE_DT_MIN_S},
                "candidate": {"cfl": TIME_CFL, "DtIni_s": TIME_DT_INI_S, "DtMin_s": TIME_DT_MIN_S},
                "actual_steps_required": True,
                "minimum_step_gate": "candidate RunPARTs DtMin must be lower and actual step count must be measured",
                "cfl_only_is_invalid": True,
            },
        )
    elif design_cell == "native_output":
        config.update(
            output_interval_s=NATIVE_OUTPUT_INTERVAL_S,
            time_control_variant="native_output_cadence_only",
            time_control_contract={
                "cfl": BASE_CFL,
                "DtIni_s": 0.0,
                "DtMin_s": 0.0,
                "DtFixed_s": 0.0,
                "actual_steps_unchanged_by_design": True,
                "purpose": "saved native cadence comparison; no temporal qualification without internal-time cell",
            },
        )
    return config


def design(lab: Path) -> dict:
    calibration = lab / "campaigns/core-v1/cfd/f4-tallwall-observer-calibration-v2.json"
    completion = lab / "campaigns/core-v1/cfd/f4-tallwall120-completed-v1/root-integration.json"
    observations = lab / "campaigns/core-v1/cfd/f4-tallwall120-completed-v1/observations-v2.json"
    dt_diagnostic = lab / "campaigns/core-v1/cfd/f4-time-step-diagnostic.json"
    dt_correction = lab / "campaigns/core-v1/cfd/f4-time-control-correction.json"
    for path in (calibration, completion, observations, dt_diagnostic, dt_correction):
        if not path.is_file():
            raise FileNotFoundError(path)
    cells = [base_config(q, dp, kind) for q, dp, kind in expected_signature()]
    return {
        "schema": "core.f4.tallwall120.qualification_design.v1",
        "created_at": stamp(),
        "family": "F4",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "recipe": RECIPE,
        "recipe_id": RECIPE_ID,
        "qualification_claim": "none",
        "qualification_only": True,
        "qualification_inheritance": False,
        "cell_count": 15,
        "cells": cells,
        "resolution_m": list(DP_VALUES),
        "parameter_name": "drop_left_x_m",
        "parameter_q_points": [0.0, 0.5, 1.0, 0.25, 0.75],
        "held_out_q": list(HELD_OUT_Q),
        "continuum_geometry": {
            "pool": {"low": [0.0, 0.0, 0.0], "size": [1.2, 0.4, 0.18]},
            "drop_size_m": [0.26, 0.16, 0.14],
            "density_kg_m3": 1000.0,
            "container_height_m": HEIGHT_M,
            "top_open": True,
            "changed_relative_to_old_scope": True,
            "changed_relative_to_tallwall_canary": False,
        },
        "registered_window": {
            "initial_time_max_s": HORIZON_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "maximum_extended_time_max_s": 2 * HORIZON_S,
            "analytic_t0_s": 3.84,
            "analytic_t0_is_execution_window": False,
            "event_completion_required": True,
            "right_censor_policy": "one whole-scope doubling; never shorten on failure",
        },
        "observer": {
            "version": OBSERVATION_VERSION,
            "calibration": {"path": str(calibration.resolve()), "sha256": digest(calibration)},
            "fixed_vertical_planes_m": [0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.05, 1.2],
            "com_scale_m": [1.2, 0.4, 0.6],
            "mass_histogram": "fixed4x2x8; continuous-mass denominator",
            "legacy_event_rows_unchanged": True,
            "source": "manufactured analytic calibration; no CFD fitting",
        },
        "time_control": {
            "spatial_baseline": {"cfl": BASE_CFL, "DtIni_s": 0.0, "DtMin_s": 0.0, "DtFixed_s": 0.0},
            "internal_time_candidate": {
                "cfl": TIME_CFL, "DtIni_s": TIME_DT_INI_S, "DtMin_s": TIME_DT_MIN_S,
                "baseline_DtIni_s": BASE_DT_INI_S, "baseline_DtMin_s": BASE_DT_MIN_S,
                "actual_steps_required": True,
                "cfl_only_refinement_rejected": True,
            },
            "native_output_candidate": {"cfl": BASE_CFL, "output_interval_s": NATIVE_OUTPUT_INTERVAL_S},
            "diagnostic": {"path": str(dt_diagnostic.resolve()), "sha256": digest(dt_diagnostic)},
            "correction_record": {"path": str(dt_correction.resolve()), "sha256": digest(dt_correction)},
        },
        "canary_evidence": {
            "path": str(completion.resolve()),
            "sha256": digest(completion),
            "observations_v2_path": str(observations.resolve()),
            "observations_v2_sha256": digest(observations),
            "hard_integrity_pass": True,
            "event_window_complete": True,
            "native_particle_count": 737792,
            "qualification_inherited": False,
        },
        "gates": {
            "no_missing_native_fluid_ids": True,
            "no_nonfinite_active_values": True,
            "closed_wall_endpoint_tolerance_m": 1e-8,
            "saved_chord_crossings_allowed": 0,
            "source_initial_mass_relative_error_max": 0.025,
            "initial_mass_spread_over_continuous_mass_max": 0.03,
            "mass_change_relative_max": 1e-8,
            "spatial_max_absolute_normalized_difference": 0.05,
            "temporal_fraction_of_spatial_budget": 0.2,
            "monotone_refinement_required": True,
            "qualified": False,
        },
        "old_results": {
            "old_laminar_scope_preserved": True,
            "old_scope_negative_cells_not_overwritten": True,
            "statement": "This is a new tall-wall physical scope; canary success does not qualify the range.",
        },
    }


def parse_params(prepared: dict) -> dict:
    xml_path = Path(prepared["generated_prefix"]).with_suffix(".xml")
    root = ET.parse(xml_path).getroot()
    cfl = [float(node.get("value")) for node in root.findall(".//cflnumber")]
    params = {}
    for node in root.findall(".//parameter"):
        key = node.get("key")
        if key in {"DtIni", "DtMin", "DtFixed", "TimeMax", "TimeOut"}:
            params[key] = float(node.get("value"))
    return {"xml": str(xml_path), "cflnumber": cfl, "parameters": params}


def validate_cell(prepared_path: Path, q: float, dp: float, kind: str) -> dict:
    prepared_path = Path(prepared_path).resolve()
    issues = []
    if not prepared_path.is_file():
        return {"pass": False, "issues": ["missing prepared.json"], "prepared": str(prepared_path)}
    prepared = json.loads(prepared_path.read_text())
    cfg = prepared.get("config", {})
    if cfg.get("family") != "F4":
        issues.append("family mismatch")
    if cfg.get("scope_id") != SCOPE_ID or cfg.get("revision_id") != REVISION_ID:
        issues.append("scope/revision mismatch")
    if cfg.get("stage") != "qualification" or cfg.get("qualification_only") is not True or cfg.get("split") != "qualification_only":
        issues.append("qualification-only lineage mismatch")
    if cfg.get("design_cell") != kind:
        issues.append("design cell mismatch")
    if abs(float(cfg.get("parameter", {}).get("q", -1.0)) - q) > 1e-12:
        issues.append("q mismatch")
    if abs(float(cfg.get("dp_m", -1.0)) - dp) > 1e-12:
        issues.append("dp mismatch")
    if abs(float(cfg.get("time_max_s", -1.0)) - HORIZON_S) > 1e-9:
        issues.append("time horizon mismatch")
    if abs(float(cfg.get("horizon", {}).get("initial_horizon_s", -1.0)) - HORIZON_S) > 1e-9:
        issues.append("registered horizon metadata mismatch")
    if abs(float(cfg.get("horizon", {}).get("maximum_extended_horizon_s", -1.0)) - 2 * HORIZON_S) > 1e-9:
        issues.append("registered extension metadata mismatch")
    if abs(float(cfg.get("horizon", {}).get("analytic_initial_horizon_s", -1.0)) - 3.84) > 1e-9:
        issues.append("analytic T0 provenance mismatch")
    if abs(float(cfg.get("container_height_m", -1.0)) - HEIGHT_M) > 1e-12:
        issues.append("height mismatch")
    if cfg.get("wall_bounds", {}).get("zmax") != HEIGHT_M:
        issues.append("wall zmax mismatch")
    if cfg.get("observation_version") != OBSERVATION_VERSION:
        issues.append("observer version mismatch")
    if cfg.get("viscosity_formulation") != "laminar" or cfg.get("physical_kinematic_viscosity_m2_s") != 1e-6:
        issues.append("laminar viscosity mismatch")
    if prepared.get("preflight_pass") is not True or prepared.get("native_initial", {}).get("zero_boundary_normals") != 0:
        issues.append("CPU native preflight failed")
    if prepared.get("mass_preflight", {}).get("mass_gate_pass") is not True:
        issues.append("mass gate failed")
    if prepared.get("sampling", {}).get("mass_policy", "").find("no mass rescaling") < 0:
        issues.append("mass rescaling policy missing")
    xml = parse_params(prepared)
    if not xml["cflnumber"] or any(abs(v - float(cfg["cfl"])) > 1e-12 for v in xml["cflnumber"]):
        issues.append("generated CFL does not match config")
    if abs(xml["parameters"].get("TimeMax", -1.0) - HORIZON_S) > 1e-9:
        issues.append("generated TimeMax mismatch")
    if kind == "internal_time":
        for key, expected in (("DtIni", TIME_DT_INI_S), ("DtMin", TIME_DT_MIN_S), ("DtFixed", 0.0)):
            if abs(xml["parameters"].get(key, -1.0) - expected) > 1e-15:
                issues.append(f"internal-time {key} mismatch")
        if cfg.get("time_control_contract", {}).get("actual_steps_required") is not True:
            issues.append("actual-step requirement missing")
    elif kind == "native_output":
        if abs(float(cfg.get("output_interval_s", -1.0)) - NATIVE_OUTPUT_INTERVAL_S) > 1e-12:
            issues.append("native cadence mismatch")
        for key in ("DtIni", "DtMin", "DtFixed"):
            if abs(xml["parameters"].get(key, -1.0)) > 1e-15:
                issues.append(f"native-output {key} unexpectedly changed")
    else:
        if abs(float(cfg.get("output_interval_s", -1.0)) - OUTPUT_INTERVAL_S) > 1e-12:
            issues.append("spatial cadence mismatch")
    return {
        "index": None,
        "q": q,
        "dp_m": dp,
        "design_cell": kind,
        "prepared": str(prepared_path),
        "prepared_sha256": digest(prepared_path),
        "pass": not issues,
        "issues": issues,
        "native_initial": prepared.get("native_initial", {}),
        "mass_preflight": prepared.get("mass_preflight", {}),
        "generated_time_control": xml,
    }


def prepare_matrix(lab: Path, output: Path) -> dict:
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"matrix output is not fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    design_path = output / "design.json"
    write_json(design_path, design(lab))
    rows = []
    for index, (q, dp, kind) in enumerate(expected_signature()):
        target = output / f"cell-{index:02d}"
        config = base_config(q, dp, kind)
        prepared = core_cfd.prepare(config, lab, target)
        rows.append({
            "index": index,
            "case_id": config["case_id"],
            "q": q,
            "dp_m": dp,
            "design_cell": kind,
            "prepared": str((target / "prepared.json").resolve()),
            "prepared_sha256": digest(target / "prepared.json"),
            "preflight_pass": bool(prepared["preflight_pass"]),
            "mass_preflight_pass": bool(prepared["mass_preflight"]["mass_gate_pass"]),
        })
        write_json(output / "prepared-matrix.json", {
            "schema": "core.f4.tallwall120.prepared_matrix.v1",
            "design_sha256": digest(design_path),
            "cells": rows,
            "complete": len(rows) == 15,
            "qualification_claim": "none",
        })
    return validate_matrix(output, lab)


def validate_matrix(matrix_root: Path, lab: Path) -> dict:
    matrix_root = Path(matrix_root).resolve()
    design_path = matrix_root / "design.json"
    matrix_path = matrix_root / "prepared-matrix.json"
    design_payload = json.loads(design_path.read_text())
    matrix_payload = json.loads(matrix_path.read_text())
    issues = []
    if design_payload.get("scope_id") != SCOPE_ID or design_payload.get("cell_count") != 15:
        issues.append("design scope/cell count mismatch")
    if matrix_payload.get("schema") != "core.f4.tallwall120.prepared_matrix.v1":
        issues.append("matrix schema mismatch")
    if matrix_payload.get("design_sha256") != digest(design_path):
        issues.append("design hash mismatch")
    if len(matrix_payload.get("cells", [])) != 15 or matrix_payload.get("complete") is not True:
        issues.append("matrix is not complete 15 cells")
    cells = []
    rows = matrix_payload.get("cells", [])
    for index, (q, dp, kind) in enumerate(expected_signature()):
        row = rows[index] if index < len(rows) else {}
        cell = validate_cell(Path(row.get("prepared", "")), q, dp, kind)
        cell["index"] = index
        cells.append(cell)
        if not cell["pass"]:
            issues.extend([f"cell {index:02d}: {issue}" for issue in cell["issues"]])
    result = {
        "schema": "core.f4.tallwall120.static_validation.v1",
        "created_at": stamp(),
        "matrix_root": str(matrix_root),
        "design_sha256": digest(design_path),
        "matrix_sha256": digest(matrix_path),
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualification_claim": "none",
        "qualification_only": True,
        "static_quality_pass": not issues,
        "issues": issues,
        "cells": cells,
        "observer_version": OBSERVATION_VERSION,
        "actual_dt_floor_cell": {
            "design_cell": "internal_time",
            "cfl": TIME_CFL,
            "DtIni_s": TIME_DT_INI_S,
            "DtMin_s": TIME_DT_MIN_S,
            "actual_steps_required": True,
        },
        "gpu_launched": False,
    }
    write_json(matrix_root / "static-validation.json", result)
    return result


def resource_for(dp: float, kind: str) -> dict:
    if kind == "native_output":
        return {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 8192, "io_weight": 3}
    if kind == "internal_time":
        return {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 8192, "io_weight": 2}
    if dp <= 0.005 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 8192, "io_weight": 2}
    if dp <= 0.0075 + 1e-12:
        return {"cpu_cores": 2, "ram_mib": 24576, "gpu_peak_mib": 6144, "io_weight": 2}
    return {"cpu_cores": 2, "ram_mib": 16384, "gpu_peak_mib": 4096, "io_weight": 1}


def make_jobs(lab: Path, matrix_root: Path, output: Path) -> dict:
    validation = validate_matrix(matrix_root, lab)
    if not validation["static_quality_pass"]:
        raise ValueError("static validation failed; no jobs written")
    matrix = json.loads((Path(matrix_root) / "prepared-matrix.json").read_text())
    jobs_dir = Path(output).resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for index, row in enumerate(matrix["cells"]):
        prepared_path = Path(row["prepared"]).resolve()
        prepared = json.loads(prepared_path.read_text())
        solver = Path(prepared["solver_binary"]).resolve()
        decoder = Path(prepared["decoder"]).resolve()
        # Include the full prepared input closure.  core_runtime transfers only
        # explicit input_files; prepared.inputs is not expanded remotely.
        entries = []
        seen = set()
        def add(path: Path):
            path = Path(path).resolve()
            if str(path) in seen:
                return
            if not path.is_file():
                raise FileNotFoundError(path)
            entries.append({"path": str(path), "sha256": digest(path)})
            seen.add(str(path))
        add(prepared_path)
        add(solver)
        add(decoder)
        add(lab / "scripts/core_cfd.py")
        for path in prepared["inputs"]:
            add(Path(path))
        job_id = f"f4-tallwall120-qualification-cell-{index:02d}"
        spec = {
            "schema": "core.cfd.job.v1",
            "job_id": job_id,
            "logical_id": job_id,
            "attempt_role": "initial",
            "category": "f4_tallwall120_qualification",
            "host": "h200",
            "source_lab": str(lab.resolve()),
            "cwd": str(lab.resolve()),
            "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_cfd.py"),
                     "--lab-root", str(lab), "run", "--prepared", str(prepared_path),
                     "--output", "{attempt_dir}/product"],
            "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
            "resources": resource_for(float(row["dp_m"]), row["design_cell"]),
            "timeout_seconds": 14400,
            "depends_on": [],
            "qualification_claim": "none",
            "qualification_only": True,
            "split": "qualification_only",
            "qualification_status": "prepared-only; tall-wall range remains unqualified",
            "launch_recommendation": "root review/queue only; no automatic launch",
            "input_files": entries,
            "prepared_case_id": prepared["config"]["case_id"],
            "scope_id": SCOPE_ID,
            "revision_id": REVISION_ID,
            "family": "F4",
            "matrix_index": index,
            "q": float(row["q"]),
            "dp_m": float(row["dp_m"]),
            "design_cell": row["design_cell"],
            "registered_window_s": HORIZON_S,
            "maximum_extended_window_s": 2 * HORIZON_S,
            "observer_version": OBSERVATION_VERSION,
            "time_control_contract": prepared["config"].get("time_control_contract", {}),
            "resource_basis": {
                "fluid_particles": prepared["native_initial"]["fluid_particles"],
                "boundary_particles": prepared["native_initial"]["boundary_particles"],
                "trajectory_output_interval_s": prepared["config"]["output_interval_s"],
                "actual_dt_floor_required_for_internal_time": row["design_cell"] == "internal_time",
            },
            "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0; output is attempt_dir/product",
        }
        path = jobs_dir / f"{job_id}.json"
        write_json(path, spec)
        jobs.append({"index": index, "job_id": job_id, "path": str(path), "prepared": str(prepared_path),
                     "sha256": digest(path), "resources": spec["resources"], "input_count": len(entries)})
    manifest = {
        "schema": "core.f4.tallwall120.jobs.v1",
        "created_at": stamp(),
        "matrix_root": str(Path(matrix_root).resolve()),
        "matrix_sha256": digest(Path(matrix_root) / "prepared-matrix.json"),
        "static_validation_sha256": digest(Path(matrix_root) / "static-validation.json"),
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "job_count": len(jobs),
        "jobs": jobs,
        "execution_status": "prepared_only",
        "qualification_claim": "none",
        "gpu_launched": False,
        "time_note": "internal_time cell changes CFL and explicit DtIni/DtMin; actual RunPARTs steps remain a required execution gate",
    }
    write_json(jobs_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare-matrix")
    p.add_argument("--output", type=Path, required=True)
    v = sub.add_parser("validate")
    v.add_argument("--matrix", type=Path, required=True)
    j = sub.add_parser("make-jobs")
    j.add_argument("--matrix", type=Path, required=True)
    j.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = args.lab_root.resolve()
    if args.command == "prepare-matrix":
        result = prepare_matrix(lab, args.output)
    elif args.command == "validate":
        result = validate_matrix(args.matrix, lab)
    else:
        result = make_jobs(lab, args.matrix, args.output)
    print(json.dumps({k: result[k] for k in ("static_quality_pass", "job_count", "qualification_claim", "gpu_launched") if k in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
