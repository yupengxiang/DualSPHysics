#!/usr/bin/env python3
"""Build a read-only proposal for operational F8 R008 T1 metric semantics.

The proposal clarifies existing gates without changing inputs, matrix rows,
thresholds, or execution authority. It is not authoritative until independent
Terra High review is recorded.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from scripts import f8_r008_execution_readiness_audit_v3 as readiness
from scripts.f8_observation_parser_v1 import fit_harmonic
from scripts.f8_womersley_oracle import ChannelParameters, steady_velocity
from scripts.f8_womersley_oracle_v2 import startup_velocity


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
SCOPE = ROOT / "t1-scope-design-v1/receipt.json"
PARAMETERS = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json")
PARSER_CONTRACT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/observation-parser-v1/contract.json")
REFERENCE_CONTRACT_V1 = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/reference-oracle-v1/contract.json")
REFERENCE_CONTRACT_V2 = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/reference-oracle-v2/contract.json")
PACK = ROOT / "definition-control-pack-v1/receipt.json"
ANCHOR_DEFINITION = ROOT / "definition-control-pack-v1/qualification/space-q0p5-dp0p0075/F8_OPC_space-q0p5-dp0p0075_Def.xml"
PREFLIGHT = ROOT / "cpu-native-preflight-v3/receipt.json"
POSTRUN_AUDIT = ROOT / "cpu-native-postrun-audit-v1/receipt.json"
R008_AUTHORIZATION = ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
PARAMETER_BUILDER = Path("scripts/f8_parameter_contract_v1.py")
PARAMETER_TEST = Path("tests/test_f8_parameter_contract_v1.py")
PARSER = Path("scripts/f8_observation_parser_v1.py")
PARSER_TEST = Path("tests/test_f8_observation_parser_v1.py")
WINDOW_PARSER = Path("scripts/f8_observation_window_parser_v2.py")
WINDOW_TEST = Path("tests/test_f8_observation_window_parser_v2.py")
STEADY_ORACLE = Path("scripts/f8_womersley_oracle.py")
STEADY_ORACLE_TEST = Path("tests/test_f8_womersley_oracle.py")
STARTUP_ORACLE = Path("scripts/f8_womersley_oracle_v2.py")
STARTUP_ORACLE_TEST = Path("tests/test_f8_womersley_oracle_v2.py")
SCOPE_BUILDER = Path("scripts/f8_t1_scope_design_v1.py")
SCOPE_TEST = Path("tests/test_f8_t1_scope_design_v1.py")
READINESS_RECEIPT = ROOT / "t1-execution-readiness-audit-v3/receipt.json"
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_t1_metric_semantics_proposal_v1.py")
OUTPUT = LAB / ROOT / "t1-metric-semantics-proposal-v1/receipt.json"
SCHEMA = "core.cfd.f8.r008_t1_metric_semantics_proposal.v1"

RESOLUTIONS = {
    "coarse": {"dp_m": 0.009, "spacing_intervals": 10, "particle_planes": 11, "definition_count": 3},
    "production": {"dp_m": 0.0075, "spacing_intervals": 12, "particle_planes": 13, "definition_count": 39},
    "fine": {"dp_m": 0.006, "spacing_intervals": 15, "particle_planes": 16, "definition_count": 5},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads((LAB / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve()
    payload = absolute.read_bytes()
    return {
        "path": str(absolute.relative_to(LAB)),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def verify_definition_geometry(half_height_m: float, pack: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pack_root = LAB / ROOT / "definition-control-pack-v1"
    definitions = sorted(pack_root.rglob("*_Def.xml"))
    if len(definitions) != sum(row["definition_count"] for row in RESOLUTIONS.values()):
        raise ValueError("R008 definition pack no longer contains the expected 47 frozen Definitions")
    input_bindings = {
        item["path"]: item for item in pack.get("input_bindings", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    counts = {key: 0 for key in RESOLUTIONS}
    plane_counts = {key: row["particle_planes"] for key, row in RESOLUTIONS.items()}
    definition_evidence: list[dict[str, Any]] = []
    for path in definitions:
        relative = path.relative_to(LAB)
        reference = input_bindings.get(relative.as_posix())
        if reference is None:
            raise ValueError(f"R008 Definition is absent from the frozen 94-input pack: {relative}")
        if (
            reference.get("bytes") != path.stat().st_size
            or reference.get("sha256") != sha256(path)
        ):
            raise ValueError(f"R008 Definition no longer matches its frozen pack hash: {relative}")
        definition_evidence.append(binding(relative, "hash-verified R008 qualification Definition"))
        root = ET.parse(path).getroot()
        dp = float(root.find("./casedef/geometry/definition").get("dp"))
        matches = [key for key, row in RESOLUTIONS.items() if math.isclose(dp, row["dp_m"], rel_tol=0.0, abs_tol=1e-12)]
        if len(matches) != 1:
            raise ValueError(f"unregistered R008 Definition resolution: {path}")
        key = matches[0]
        counts[key] += 1
        boxes = root.findall("./casedef/geometry/commands/mainlist/drawbox")
        fluid_box = next((
            box for box in boxes
            if box.find("point") is not None
            and box.find("size") is not None
            and math.isclose(float(box.find("point").get("z")), -half_height_m, rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(float(box.find("size").get("z")), 2.0 * half_height_m, rel_tol=0.0, abs_tol=1e-12)
        ), None)
        if fluid_box is None:
            raise ValueError(f"R008 fluid Definition does not span the frozen closed wall interval: {path}")
        ratio = 2.0 * half_height_m / dp
        intervals = round(ratio)
        if not math.isclose(ratio, intervals, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"R008 2H/dp is not integral for {path}")
        if intervals != RESOLUTIONS[key]["spacing_intervals"]:
            raise ValueError(f"R008 interval count changed for {path}")
    if counts != {key: row["definition_count"] for key, row in RESOLUTIONS.items()}:
        raise ValueError(f"R008 Definition resolution counts changed: {counts}")
    return ({
            "definition_count": len(definitions),
            "definitions_by_resolution": counts,
            "closed_fluid_z_extent_m": [-half_height_m, half_height_m],
            "expected_spacing_intervals": {key: row["spacing_intervals"] for key, row in RESOLUTIONS.items()},
            "expected_planes_including_endpoints": plane_counts,
            "native_generation_performed_for_this_check": False,
        }, definition_evidence)


def startup_steady_compatibility(rows: list[dict[str, Any]], parameters: dict[str, Any]) -> dict[str, Any]:
    geometry = parameters["geometry_and_fluid"]
    half_height = float(geometry["half_height_m"])
    viscosity = float(geometry["kinematic_viscosity_m2_s"])
    acceleration = float(parameters["parameterization"]["acceleration_amplitude_m_s2"])
    maximum_amplitude_difference = (-1.0, None)
    maximum_phase_difference = (-1.0, None)
    for row in rows:
        intervals = round(2.0 * half_height / float(row["dp_m"]))
        z = -half_height + np.arange(1, intervals, dtype=np.float64) * float(row["dp_m"])
        count = int(row["expected_observation_output_count"])
        dt = float(row["period_s"]) / int(row["native_output_samples_per_period"])
        times = float(row["observation_start_s"]) + np.arange(count, dtype=np.float64) * dt
        if not math.isclose(float(times[-1]), float(row["observation_end_s"]), rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"frozen observation window does not close for {row['case_id']}")
        channel = ChannelParameters(
            half_height, viscosity, float(row["omega_rad_s"]), acceleration
        )
        steady = steady_velocity(times, z, channel)
        startup = startup_velocity(times, z, channel, terms=256)
        for index, z_value in enumerate(z):
            steady_fit = fit_harmonic(
                times, steady[:, index], row["omega_rad_s"],
                start_time_s=row["observation_start_s"],
            )
            startup_fit = fit_harmonic(
                times, startup[:, index], row["omega_rad_s"],
                start_time_s=row["observation_start_s"],
            )
            if steady_fit["amplitude"] <= 0.0:
                raise ValueError(f"steady Womersley profile amplitude is non-positive at z={z_value}")
            amplitude_difference = abs(startup_fit["amplitude"] - steady_fit["amplitude"]) / steady_fit["amplitude"]
            phase_difference = abs(math.atan2(
                math.sin(startup_fit["phase_rad"] - steady_fit["phase_rad"]),
                math.cos(startup_fit["phase_rad"] - steady_fit["phase_rad"]),
            ))
            if amplitude_difference > maximum_amplitude_difference[0]:
                maximum_amplitude_difference = (
                    amplitude_difference, {"case_id": row["case_id"], "z_m": float(z_value)}
                )
            if phase_difference > maximum_phase_difference[0]:
                maximum_phase_difference = (
                    phase_difference, {"case_id": row["case_id"], "z_m": float(z_value)}
                )
    return {
        "method": "fit the zero-initial-condition startup oracle and steady oracle over every frozen T1 native window and interior plane",
        "cases_evaluated": len(rows),
        "profile_samples_per_case": "all registered interior z planes; wall endpoints omitted because the steady reference amplitude is zero there",
        "maximum_relative_amplitude_difference": maximum_amplitude_difference[0],
        "maximum_amplitude_case_and_z": maximum_amplitude_difference[1],
        "maximum_wrapped_phase_difference_rad": maximum_phase_difference[0],
        "maximum_phase_case_and_z": maximum_phase_difference[1],
        "is_a_t1_gate_or_qualification_result": False,
        "solver_invoked": False,
    }


def build_proposal() -> dict[str, Any]:
    readiness_value = readiness.verify_audit(LAB / READINESS_RECEIPT)
    scope = load_json(SCOPE)
    parameters = load_json(PARAMETERS)
    parser_contract = load_json(PARSER_CONTRACT)
    preflight = load_json(PREFLIGHT)
    postrun = load_json(POSTRUN_AUDIT)
    authorization = load_json(R008_AUTHORIZATION)
    pack = load_json(PACK)

    matrix = scope["matrix"]
    rows = matrix["rows"]
    gate_source = scope["predeclared_t1_gates"]
    applicability = gate_source["gate_applicability_by_case_and_comparison"]
    expected_ids = [row["case_id"] for row in rows]
    if not (
        scope.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
        and len(rows) == 15
        and len(expected_ids) == len(set(expected_ids))
        and gate_source.get("all_15_required") is True
        and applicability.get("all_matrix_case_ids_unique") is True
        and pack.get("status") == "static_definition_control_pack_materialized_no_execution_authority"
        and len(pack.get("cases", [])) == 47
        and preflight.get("native_audit", {}).get("native", {}).get("fluid_particles") == 6656
        and authorization.get("hard_gates", {}).get("native_fluid_particle_count_exact") == 6656
        and authorization.get("permissions", {}).get("solver") is False
        and authorization.get("permissions", {}).get("gpu") is False
        and authorization.get("permissions", {}).get("qualification") is False
        and preflight.get("execution_controls", {}).get("solver_invoked") is False
        and postrun.get("qualification_credit") == 0
        and postrun.get("execution_boundary", {}).get("solver_invoked") is False
        and readiness_value.get("qualification_credit") == 0
        and parser_contract.get("qualification_credit") == 0
    ):
        raise ValueError("R008 frozen scope or zero-credit predecessor changed; cannot build this proposal")

    half_height = float(parameters["geometry_and_fluid"]["half_height_m"])
    resolution_contract = parameters["resolution_contract"]
    for name, row in RESOLUTIONS.items():
        if (
            not math.isclose(float(resolution_contract[f"{name}_dp_m"]), row["dp_m"], rel_tol=0.0, abs_tol=1e-12)
            or int(resolution_contract["expected_fluid_layers_across_2H"][name]) != row["spacing_intervals"]
            or not math.isclose(2.0 * half_height / row["dp_m"], row["spacing_intervals"], rel_tol=0.0, abs_tol=1e-12)
        ):
            raise ValueError(f"R008 resolution contract changed for {name}")
    geometry_check, definition_evidence = verify_definition_geometry(half_height, pack)
    frozen_error_gates = parameters["error_gates"]
    profile_gate = next(
        item for item in applicability["per_case_gates"]
        if item["gate_id"] == "womersley_profile_and_cycle_metrics"
    )
    if not (
        profile_gate["limits"]["profile_amplitude_relative_max"] == frozen_error_gates["profile_amplitude_relative_max"]
        and profile_gate["limits"]["profile_phase_absolute_max_rad"] == frozen_error_gates["profile_phase_absolute_max_rad"]
        and profile_gate["limits"]["cycle_mean_flux_over_uref_area_max"] == frozen_error_gates["cycle_mean_flux_over_uref_area_max"]
        and profile_gate["limits"]["transverse_velocity_rms_over_uref_max"] == frozen_error_gates["transverse_velocity_rms_over_uref_max"]
        and len(applicability["cross_resolution_comparisons"]) == 8
        and applicability["time_step_comparison"]["phase_difference_absolute_max_rad"]
        == frozen_error_gates["time_step_control_phase_absolute_max_rad"]
    ):
        raise ValueError("R008 metric limits or comparison inventory changed; proposal must be reviewed again")

    case_rows = [{
        "case_id": row["case_id"],
        "q": row["q"],
        "dp_m": row["dp_m"],
        "observation_start_s": row["observation_start_s"],
        "observation_end_s": row["observation_end_s"],
        "period_s": row["period_s"],
        "observation_cycles": row["observation_cycles"],
        "native_output_samples_per_period": row["native_output_samples_per_period"],
        "expected_observation_output_count": row["expected_observation_output_count"],
    } for row in rows]
    rows_by_id = {row["case_id"]: row for row in case_rows}
    production_intervals = RESOLUTIONS["production"]["spacing_intervals"]
    common_profile_z = [
        -half_height + index * RESOLUTIONS["production"]["dp_m"]
        for index in range(1, production_intervals)
    ]
    comparisons = []
    for pair in applicability["cross_resolution_comparisons"]:
        candidate_id = pair.get("coarse_case", pair.get("fine_case"))
        candidate = rows_by_id[candidate_id]
        production = rows_by_id[pair["production_case"]]
        if not (
            candidate["q"] == production["q"]
            and candidate["period_s"] == production["period_s"]
            and candidate["observation_start_s"] == production["observation_start_s"]
            and candidate["observation_end_s"] == production["observation_end_s"]
            and candidate["native_output_samples_per_period"] == production["native_output_samples_per_period"]
            and common_profile_z[0] >= -half_height
            and common_profile_z[-1] <= half_height
        ):
            raise ValueError(f"R008 cross-resolution comparison is not aligned: {pair}")
        comparisons.append({**pair, "candidate_case_id": candidate_id, "common_grid_point_count": len(common_profile_z)})

    evidence_paths = [
        (SCOPE, "frozen R008 15-case T1 scope and thresholds"),
        (PARAMETERS, "frozen physical, resolution, and normalized-gate contract"),
        (PARSER_CONTRACT, "existing observation payload and harmonic-fit schema"),
        (PARAMETER_BUILDER, "source of the frozen F8 parameter contract"),
        (PARAMETER_TEST, "parameter-contract regression tests"),
        (PARSER, "native observation parser and fixed-frequency harmonic fit"),
        (PARSER_TEST, "observation parser and harmonic-fit tests"),
        (WINDOW_PARSER, "inclusive native-only three-cycle selector"),
        (WINDOW_TEST, "native window cadence and endpoint tests"),
        (REFERENCE_CONTRACT_V1, "steady Womersley oracle contract"),
        (REFERENCE_CONTRACT_V2, "startup-transient Womersley oracle contract"),
        (STEADY_ORACLE, "steady Womersley profile and per-unit-span flux integral"),
        (STEADY_ORACLE_TEST, "steady oracle and flux-integration tests"),
        (STARTUP_ORACLE, "zero-initial-velocity transient reference"),
        (STARTUP_ORACLE_TEST, "startup transient and steady-limit tests"),
        (ROOT / "definition-control-pack-v1/receipt.json", "hash-closed 47-case Definition/control pack"),
        (ANCHOR_DEFINITION, "R008 production anchor geometry Definition"),
        (PREFLIGHT, "retained zero-credit production-resolution native geometry"),
        (POSTRUN_AUDIT, "independent read-only R008 native preflight audit"),
        (R008_AUTHORIZATION, "R008-specific authorization with expected count 6656"),
        (SCOPE_BUILDER, "R008 qualification matrix and gate-applicability builder"),
        (SCOPE_TEST, "R008 matrix and frozen-threshold tests"),
        (READINESS_RECEIPT, "corrected audit of unresolved pre-execution semantics"),
        (Path("scripts/f8_r008_execution_readiness_audit_v3.py"), "corrected R008 readiness-audit builder"),
        (Path("tests/test_f8_r008_execution_readiness_audit_v3.py"), "corrected R008 readiness-audit tests"),
        (Path("scripts/f8_cpu_native_preflight_authorization_v1.py"), "legacy R001-only consumer; excluded from R008 authority"),
        (Path("scripts/f8_input_materialization_v1.py"), "source proving legacy consumer is rooted in R001"),
    ]
    evidence = [binding(path, role) for path, role in evidence_paths]
    evidence.extend(definition_evidence)
    evidence.extend([
        binding(SCRIPT, "read-only F8 R008 metric-semantics proposal builder"),
        binding(TEST, "metric-semantics proposal contract tests"),
    ])

    return {
        "schema": SCHEMA,
        "record_id": "f8-r008-t1-metric-semantics-proposal-v1",
        "scope_id": scope["scope_id"],
        "status": "awaiting_independent_terra_high_review",
        "proposal_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "execution_authority": {
            "solver": False,
            "gpu": False,
            "worker": False,
            "queue": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "amendment_boundary": {
            "kind": "proposed_additive_semantics_closure_only",
            "scope_inputs_changed": False,
            "definition_or_control_hashes_changed": False,
            "matrix_case_count_changed": False,
            "observation_window_changed": False,
            "gate_thresholds_changed": False,
            "new_gate_added": False,
            "r001_or_r008_preflight_repeated": False,
            "solver_or_worker_authorized": False,
            "adoption_requires_independent_review": True,
        },
        "geometry_semantics": {
            "interpretation": "expected_fluid_layers_across_2H denotes spacing intervals, not particle planes",
            "interval_rule": "n_intervals = round(2*H/dp); require 2*H/dp to equal that integer within 1e-12",
            "plane_rule": "z_j = -H + j*dp for j=0..n_intervals; n_planes=n_intervals+1, including both wall endpoints",
            "resolution_counts": RESOLUTIONS,
            "definition_pack_static_check": geometry_check,
            "production_native_check": {
                "native_particle_count": 6656,
                "z_plane_count": 13,
                "matches_r008_specific_authorization": True,
                "credit": 0,
            },
            "legacy_r001_6144_count": {
                "is_r008_authority": False,
                "disposition": "do_not_apply_the_R001_only_layers-as-particle-count consumer to R008",
            },
        },
        "observation_semantics": {
            "closed_native_window": {
                "selector": "scripts/f8_observation_window_parser_v2.py::select_closed_native_window",
                "start_end": "use each frozen scope row's exact inclusive observation_start_s and observation_end_s",
                "cycles": 3,
                "native_rows": "3*native_output_samples_per_period + 1; no interpolation, extrapolation, or synthesized rows",
                "harmonic_fit": "mean + a*sin(omega*t) + b*cos(omega*t), fixed omega, all selected rows, no time shift",
            },
            "initial_particle_plane_assignment": {
                "rule": "map each initial fluid particle to nearest z_j by k=round((z+H)/dp), then retain its immutable particle ID in that plane cohort",
                "maximum_coordinate_residual_m": "max(1e-6*dp, 1e-9)",
                "invalid_mapping": "fail closed on out-of-range plane index, excessive residual, duplicate/missing particle ID, or empty plane cohort",
            },
            "plane_velocity_profile": {
                "plane_value": "mass-weighted mean native v_x of the fixed particle-ID cohort assigned to z_j; equal particle masses make this the arithmetic mean",
                "profile_z_m": "all registered z_j in increasing order, including wall endpoints for flux integration",
                "harmonic_profile_gate_samples": "interior planes j=1..n_intervals-1 only; omit exact wall endpoints where continuum amplitude is zero and phase is undefined",
                "no_spatial_smoothing_or_extrapolation": True,
            },
            "center_velocity_mps": "profile v_x at z=0; use the exact center plane when present, otherwise linear interpolation between the nearest bracketing plane means; no extrapolation",
        },
        "normalization": {
            "u_ref_m_s": "acceleration_amplitude_m_s2 / omega_rad_s for each case row",
            "acceleration_amplitude_source": "frozen parameter contract; currently 0.01 m/s^2",
            "omega_source": "the case row's frozen omega_rad_s",
            "distinction": "case-specific forcing velocity scale; does not replace the range-wide u_ref_max used in the Mach bound",
        },
        "metric_definitions": {
            "continuum_profile": {
                "reference": "steady Womersley oracle sampled at the exact CFD observation times and profile_z_m, then fit with the same fixed-frequency harmonic fitter",
                "amplitude_relative_error": "max over interior z planes of abs(A_cfd-A_ref)/A_ref; fail closed if A_ref is non-positive or non-finite",
                "phase_absolute_error_rad": "max over interior z planes of abs(atan2(sin(phi_cfd-phi_ref), cos(phi_cfd-phi_ref)))",
                "limits_from_frozen_scope": {
                    "profile_amplitude_relative_max": frozen_error_gates["profile_amplitude_relative_max"],
                    "profile_phase_absolute_max_rad": frozen_error_gates["profile_phase_absolute_max_rad"],
                },
            },
            "transverse_velocity_rms": {
                "formula": "sqrt(sum over selected frames and fluid particles of m_i*(v_y_i^2+v_z_i^2) / sum over the same samples of m_i)",
                "normalization": "divide by the case-specific Uref",
                "limit_from_frozen_scope": frozen_error_gates["transverse_velocity_rms_over_uref_max"],
            },
            "cycle_mean_flux": {
                "instantaneous_flux_per_unit_span_m3_s_per_m": "cross_sectional_flux_per_width(profile_z_m, profile_v_x) = trapezoidal integral over z; no multiplication by periodic span length",
                "cycle_mean": "trapezoidal time integral of instantaneous flux over each individual full period divided by that period",
                "three_cycle_reduction": "max absolute value of the three separate cycle means; do not average signed cycle means together",
                "normalization": "divide by Uref*(2*H), the per-unit-span reference flux scale",
                "limit_from_frozen_scope": frozen_error_gates["cycle_mean_flux_over_uref_area_max"],
            },
            "cross_resolution_profile_alignment": {
                "common_grid": "interior production-resolution z_j values for the same q",
                "common_profile_z_m": common_profile_z,
                "interpolation": "linear interpolation in z of fitted sine coefficient a and cosine coefficient b separately; derive amplitude and phase only after interpolation",
                "phase_difference": "wrapped absolute phase difference using atan2(sin(delta),cos(delta))",
                "extrapolation": "forbidden; all target locations must lie within both source profiles' wall-inclusive support",
                "comparisons_from_frozen_scope": comparisons,
                "maximum_relative_amplitude_difference": "max_z abs(A_case-A_production)/A_production; fail closed if denominator is non-positive",
                "limits_from_frozen_scope": {
                    "amplitude_relative_max": frozen_error_gates["fine_vs_production_amplitude_relative_max"],
                    "phase_absolute_max_rad": frozen_error_gates["fine_vs_production_phase_absolute_max_rad"],
                },
            },
            "time_step_control": {
                "comparison": gate_source["gate_applicability_by_case_and_comparison"]["time_step_comparison"],
                "phase_signal": "center_velocity_mps fitted at the fixed forcing frequency",
                "phase_limit_rad_from_frozen_scope": frozen_error_gates["time_step_control_phase_absolute_max_rad"],
            },
            "output_cadence_control": gate_source["gate_applicability_by_case_and_comparison"]["output_cadence_comparison"],
        },
        "steady_reference_compatibility_diagnostic": startup_steady_compatibility(rows, parameters),
        "frozen_scope_rows": case_rows,
        "failure_policy": parameters["error_gates"]["hard_failure_policy"],
        "review_request": {
            "requested_model": "gpt-5.6-terra",
            "requested_reasoning_effort": "high",
            "questions": [
                "Does the interval-to-plane interpretation match every R008 frozen input and native receipt without changing scope?",
                "Are the profile sheet reduction, wall handling, Uref, transverse RMS, and flux normalization mathematically and operationally well-defined?",
                "Does the phasor interpolation rule correctly close all eight registered cross-resolution comparisons without extrapolation?",
                "Does the proposal preserve the existing 15 rows, windows, thresholds, failure denominator, and zero-authority boundary?",
                "Identify any formula, sign, unit, edge-case, or provenance defect that should block adoption.",
            ],
        },
        "evidence": evidence,
    }


def verify_proposal(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_proposal():
        raise ValueError("R008 metric-semantics proposal no longer matches frozen evidence")
    return value


def write_proposal(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 metric-semantics proposal: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(build_proposal(), indent=2, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable review proposal once")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_proposal().relative_to(LAB))
    else:
        print(json.dumps(build_proposal(), indent=2, sort_keys=True))
