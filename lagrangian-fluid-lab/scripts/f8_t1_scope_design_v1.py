#!/usr/bin/env python3
"""Freeze a read-only F8 R008 T1 qualification design; do not launch CFD."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
PLAN = Path("/home/jade/.codex/attachments/ece07836-13f3-4e3a-9dd4-55120224dcee/PLAN.md")
PLAN_BYTES = 30379
PLAN_SHA256 = "17491b1f5ea5b7c8464c7afb6f2dc21bdff7cf396cb47aebd625ca22d38c3263"
BASE = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r007")
R001 = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
OUTPUT = LAB / ROOT / "t1-scope-design-v1/receipt.json"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SCHEMA = "core.cfd.f8.t1_scope_design.v1"

ROOT_RULING = R001 / "root-scope-ruling-v1/receipt.json"
PARAMETER_CONTRACT = R001 / "parameter-contract-v1.json"
R007_REVIEW = BASE / "static-design-review-v1/receipt.json"
R007_MATERIALIZATION = BASE / "input-materialization-v1/receipt.json"
R007_AUTHORIZATION = BASE / "cpu-native-preflight-authorization-v1/authorization.json"
R007_PREFLIGHT = BASE / "cpu-native-preflight-v1/receipt.json"
R007_LOCK = BASE / "cpu-native-preflight-v1/one-shot-lock.json"
R007_DEFINITION = BASE / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R007_Def.xml"
R007_CONTROL = BASE / "input/F8_OPC_q0p500_r007_acceleration.csv"
OBSERVATION_PARSER = R001 / "observation-parser-v1/contract.json"
REFERENCE_ORACLE = R001 / "reference-oracle-v2/contract.json"
OBSERVATION_PARSER_V2 = Path("scripts/f8_observation_window_parser_v2.py")
OBSERVATION_PARSER_V2_TEST = Path("tests/test_f8_observation_window_parser_v2.py")

FLUID_NU_M2_S = 0.0005
HALF_HEIGHT_M = 0.045
LENGTH_X_M = 0.24
LENGTH_Y_M = 0.12
RHO0_KG_M3 = 1000.0
ACCELERATION_AMPLITUDE_M_S2 = 0.01
SOUND_SPEED_M_S = 10.0
BASE_CFL = 0.2
TIGHT_CFL = 0.1
CONTROL_SAMPLES_PER_PERIOD = 64
BASE_OUTPUT_SAMPLES_PER_PERIOD = 64
DENSE_OUTPUT_SAMPLES_PER_PERIOD = 128
OBSERVATION_CYCLES = 3
COARSE_DP_M = 0.009
PRODUCTION_DP_M = 0.0075
FINE_DP_M = 0.006
FIRST_EIGHT_INDICES = [0, 4, 8, 14, 18, 20, 22, 31]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve() if not path.is_absolute() else path.resolve()
    return {
        "path": str(absolute) if path.is_absolute() else str(path),
        "role": role,
        "bytes": absolute.stat().st_size,
        "sha256": sha256(absolute),
    }


def bind_plan() -> dict[str, Any]:
    if PLAN.is_file():
        observed_bytes = PLAN.stat().st_size
        observed_sha256 = sha256(PLAN)
        if observed_bytes != PLAN_BYTES or observed_sha256 != PLAN_SHA256:
            raise ValueError("attached Core plan no longer matches the adopted immutable plan hash")
    else:
        observed_bytes = PLAN_BYTES
        observed_sha256 = PLAN_SHA256
    return {
        "path": str(PLAN),
        "role": "adopted Core plan; pinned to root-ruling hash",
        "bytes": observed_bytes,
        "sha256": observed_sha256,
    }


def load_json(path: Path) -> dict[str, Any]:
    absolute = (LAB / path) if not path.is_absolute() else path
    value = json.loads(absolute.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def alpha_for_q(q: float) -> float:
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must lie in the frozen [0,1] interval")
    return 2.0 + 6.0 * q


def period_for_q(q: float) -> float:
    alpha = alpha_for_q(q)
    omega = alpha * alpha * FLUID_NU_M2_S / (HALF_HEIGHT_M * HALF_HEIGHT_M)
    return 2.0 * math.pi / omega


def observation_window(q: float) -> tuple[float, float]:
    period_s = period_for_q(q)
    tau_s = HALF_HEIGHT_M * HALF_HEIGHT_M / FLUID_NU_M2_S
    earliest_start_s = max(2.0 * tau_s, 2.0 * period_s)
    base_output_dt_s = period_s / BASE_OUTPUT_SAMPLES_PER_PERIOD
    start_index = math.ceil(earliest_start_s / base_output_dt_s - 1e-12)
    start_s = start_index * base_output_dt_s
    return start_s, start_s + OBSERVATION_CYCLES * period_s


def case(case_id: str, q_text: str, dp_m: float, *, kind: str,
         cfl: float = BASE_CFL, output_ppp: int = BASE_OUTPUT_SAMPLES_PER_PERIOD,
         compare_to: str | None = None) -> dict[str, Any]:
    q = float(q_text)
    alpha = alpha_for_q(q)
    period_s = period_for_q(q)
    t_start_s, t_end_s = observation_window(q)
    output_dt_s = period_s / output_ppp
    start_index = round(t_start_s / output_dt_s)
    end_index = round(t_end_s / output_dt_s)
    if not (
        math.isclose(start_index * output_dt_s, t_start_s, rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(end_index * output_dt_s, t_end_s, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise ValueError(f"observation endpoints are off native output grid for {case_id}")
    return {
        "case_id": case_id,
        "kind": kind,
        "qualification_only": True,
        "q": q,
        "alpha": alpha,
        "period_s": period_s,
        "omega_rad_s": 2.0 * math.pi / period_s,
        "dp_m": dp_m,
        "cflnumber": cfl,
        "control_samples_per_period": CONTROL_SAMPLES_PER_PERIOD,
        "native_output_samples_per_period": output_ppp,
        "native_output_dt_s": output_dt_s,
        "observation_start_output_index": int(start_index),
        "observation_end_output_index": int(end_index),
        "expected_observation_output_count": OBSERVATION_CYCLES * output_ppp + 1,
        "control_amplitude_m_s2": ACCELERATION_AMPLITUDE_M_S2,
        "observation_start_s": t_start_s,
        "observation_end_s": t_end_s,
        "observation_cycles": OBSERVATION_CYCLES,
        "compare_to": compare_to,
    }


def qualification_matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    resolutions = (("coarse", COARSE_DP_M), ("production", PRODUCTION_DP_M), ("fine", FINE_DP_M))
    for q_text in ("0", "0.5", "1"):
        for resolution, dp_m in resolutions:
            q_label = q_text.replace(".", "p")
            dp_label = f"{dp_m:.4f}".replace(".", "p")
            rows.append(case(f"space-q{q_label}-dp{dp_label}", q_text, dp_m, kind="spatial_anchor"))
    for q_text in ("0.25", "0.75"):
        for resolution, dp_m in (("production", PRODUCTION_DP_M), ("fine", FINE_DP_M)):
            q_label = q_text.replace(".", "p")
            dp_label = f"{dp_m:.4f}".replace(".", "p")
            rows.append(case(f"internal-q{q_label}-dp{dp_label}", q_text, dp_m, kind="independent_internal"))
    baseline_id = "space-q0p5-dp0p0075"
    rows.append(case(
        "time-q0p5-dp0p0075-cfl0p1", "0.5", PRODUCTION_DP_M,
        kind="time_step_control", cfl=TIGHT_CFL, compare_to=baseline_id,
    ))
    rows.append(case(
        "cadence-q0p5-dp0p0075-output128", "0.5", PRODUCTION_DP_M,
        kind="native_output_cadence_control", output_ppp=DENSE_OUTPUT_SAMPLES_PER_PERIOD,
        compare_to=baseline_id,
    ))
    if len(rows) != 15 or len({row["case_id"] for row in rows}) != 15:
        raise AssertionError("F8 T1 matrix must contain exactly 13+2 unique logical configurations")
    return rows


def production_manifest() -> list[dict[str, Any]]:
    split_by_index = {
        "train": {3, 4, 6, 7, 10, 11, 12, 15, 16, 19, 20, 21, 24, 25, 27, 28},
        "validation": {8, 13, 18, 23},
        "id_test": {5, 9, 14, 17, 22, 26},
        "ood_test": {0, 1, 2, 29, 30, 31},
    }
    rows = []
    for index in range(32):
        q = (index + 0.5) / 32.0
        q_text = f"{q:.8f}"
        q_label = q_text.rstrip("0").rstrip(".").replace(".", "p")
        row = case(
            f"prod-i{index:02d}-q{q_label}-dp0p0075", q_text, PRODUCTION_DP_M,
            kind="production", output_ppp=BASE_OUTPUT_SAMPLES_PER_PERIOD,
        )
        matching_splits = [name for name, indices in split_by_index.items() if index in indices]
        if len(matching_splits) != 1:
            raise AssertionError(f"production index {index} must have exactly one split")
        row["production_index"] = index
        row["split"] = matching_splits[0]
        row["qualification_only"] = False
        rows.append(row)
    if len({row["case_id"] for row in rows}) != 32:
        raise AssertionError("all 32 production case IDs must be unique")
    return rows


def gate_applicability(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    all_ids = [row["case_id"] for row in matrix]
    case_id_set = set(all_ids)
    spatial_rows = [row for row in matrix if row["kind"] in ("spatial_anchor", "independent_internal")]
    cross_resolution = []
    for q in (0.0, 0.5, 1.0):
        label = f"{q:g}".replace(".", "p")
        cross_resolution.extend([
            {"q": q, "coarse_case": f"space-q{label}-dp0p0090", "production_case": f"space-q{label}-dp0p0075", "amplitude_relative_max": 0.1, "phase_absolute_max_rad": 0.1},
            {"q": q, "fine_case": f"space-q{label}-dp0p0060", "production_case": f"space-q{label}-dp0p0075", "amplitude_relative_max": 0.1, "phase_absolute_max_rad": 0.1},
        ])
    for q in (0.25, 0.75):
        label = f"{q:g}".replace(".", "p")
        cross_resolution.append({
            "q": q,
            "fine_case": f"internal-q{label}-dp0p0060",
            "production_case": f"internal-q{label}-dp0p0075",
            "amplitude_relative_max": 0.1,
            "phase_absolute_max_rad": 0.1,
        })
    if any(
        pair[key] not in case_id_set
        for pair in cross_resolution
        for key in ("coarse_case", "fine_case", "production_case")
        if key in pair
    ):
        raise AssertionError("every cross-resolution comparison must reference registered matrix rows")
    profile_gate = {
        "gate_id": "womersley_profile_and_cycle_metrics",
        "applies_to_case_ids": all_ids,
    }
    return {
        "per_case_gates": [
            {
                "gate_id": "native_integrity_and_complete_window",
                "applies_to_case_ids": all_ids,
                "checks": ["finite native state", "density range", "Mach limit", "wall penetration limit", "zero excluded fluid particles", "no particle overlap", "complete inclusive aligned three-period sample window", "no extrapolation"],
            },
            {
                **profile_gate,
                "checks": ["continuum profile amplitude relative error", "continuum profile phase error", "cycle-mean flux ratio", "transverse velocity RMS ratio"],
                "limits": {
                    "profile_amplitude_relative_max": 0.15,
                    "profile_phase_absolute_max_rad": 0.15,
                    "cycle_mean_flux_over_uref_area_max": 0.05,
                    "transverse_velocity_rms_over_uref_max": 0.05,
                },
            },
        ],
        "cross_resolution_comparisons": cross_resolution,
        "cross_resolution_limit_source": "reuse the frozen fine-vs-production limits for coarse-vs-production as an additive stricter, pre-execution gate; no threshold is relaxed",
        "time_step_comparison": {
            "case_id": "time-q0p5-dp0p0075-cfl0p1",
            "baseline_case_id": "space-q0p5-dp0p0075",
            "both_cases_must_pass_per_case_gates": True,
            "refined_max_dt_must_be_strictly_less_than_baseline": True,
            "phase_difference_absolute_max_rad": 0.05,
        },
        "output_cadence_comparison": {
            "case_id": "cadence-q0p5-dp0p0075-output128",
            "baseline_case_id": "space-q0p5-dp0p0075",
            "dense_native_rows_per_period": 128,
            "downsample_rule": "take every second dense native output row, including both inclusive aligned endpoints",
            "downsampled_timestamp_array_must_equal_baseline_exactly_with_1e-12_s_absolute_tolerance": True,
            "both_native_series_must_pass_per_case_gates": True,
        },
        "all_matrix_case_ids_unique": len(set(all_ids)) == len(all_ids),
        "all_spatial_cases_have_an_oracle_gate": {row["case_id"] for row in spatial_rows} <= set(profile_gate["applies_to_case_ids"]),
    }


def validate_parent_evidence() -> dict[str, Any]:
    ruling = load_json(ROOT_RULING)
    contract = load_json(PARAMETER_CONTRACT)
    review = load_json(R007_REVIEW)
    materialization = load_json(R007_MATERIALIZATION)
    authorization = load_json(R007_AUTHORIZATION)
    preflight = load_json(R007_PREFLIGHT)
    lock = load_json(R007_LOCK)
    definition_path = LAB / R007_DEFINITION
    control_path = LAB / R007_CONTROL
    definition_ref = preflight["input"]["definition"]
    control_ref = preflight["input"]["control"]

    if not (
        ruling["status"] == "accepted_as_distinct_mechanism_family_static_review_only"
        and ruling["user_ruling"]["selection"] == "mechanism_family_gate"
        and ruling["user_ruling"]["free_surface_required_for_this_family"] is False
        and ruling["scope_effect"]["eligible_for_core_third_family_denominator"] is False
        and contract["status"] == "pre_admission_static_contract_frozen"
        and contract["parameterization"]["q_rule"] == "q_i=(i+0.5)/32, i=0..31"
        and contract["parameterization"]["alpha_rule"] == "alpha=2+6*q"
        and contract["parameterization"]["omega_rule_rad_s"] == "omega=alpha^2*nu/H^2"
        and contract["resolution_contract"]["coarse_dp_m"] == COARSE_DP_M
        and contract["resolution_contract"]["production_dp_m"] == PRODUCTION_DP_M
        and contract["resolution_contract"]["fine_dp_m"] == FINE_DP_M
        and review["status"] == "r007_static_design_review_passed_inputs_not_authorized"
        and review["static_constraint_gaps"] == []
        and materialization["status"] == "one_time_r007_inputs_materialized_static_only"
        and authorization["status"] == "authorized_for_exactly_one_r007_cpu_native_preflight"
        and preflight["status"] == "cpu_native_preflight_passed_zero_credit"
        and preflight["qualification_credit"] == 0
        and preflight["checks"]
        and all(value is True for value in preflight["checks"].values())
        and preflight["native"]["fixed_boundary_particles"] == 4096
        and preflight["native"]["fluid_particles"] == 6656
        and preflight["native"]["total_particles"] == 10752
        and preflight["native"]["minimum_normal_magnitude_m"] >= 0.001875
        and preflight["execution_controls"]["solver_invoked"] is False
        and preflight["execution_controls"]["gpu_invoked"] is False
        and preflight["execution_controls"]["queue_mutation"] == 0
        and lock["same_input_retry"] is False
    ):
        raise ValueError("F8 parent ruling, frozen contract, or closed r007 preflight no longer matches R008 design assumptions")

    for reference, path in ((definition_ref, definition_path), (control_ref, control_path)):
        if not path.is_file() or reference["bytes"] != path.stat().st_size or reference["sha256"] != sha256(path):
            raise ValueError(f"r007 input no longer matches its native preflight receipt: {path}")
    if (
        review["precommitted_input_bytes"]["definition_sha256"] != sha256(definition_path)
        or review["precommitted_input_bytes"]["control_sha256"] != sha256(control_path)
    ):
        raise ValueError("r007 preflight inputs differ from their static precommit hashes")

    xml_root = ET.parse(definition_path).getroot()
    parameters = {item.get("key"): float(item.get("value")) for item in xml_root.findall("./execution/parameters/parameter")}
    cfl = float(xml_root.find("./casedef/constantsdef/cflnumber").get("value"))
    dp = float(xml_root.find("./casedef/geometry/definition").get("dp"))
    r008_start_s, r008_end_s = observation_window(0.5)
    r008_dt_s = period_for_q(0.5) / BASE_OUTPUT_SAMPLES_PER_PERIOD
    r007_time_max_s = parameters["TimeMax"]
    r007_nominal_start_s = float(review["parameters"]["observation_start"])
    r007_first_saved_index = math.ceil(r007_nominal_start_s / r008_dt_s - 1e-12)
    r007_last_saved_index = int(round(r007_time_max_s / r008_dt_s))
    r008_start_index = int(round(r008_start_s / r008_dt_s))
    r008_end_index = int(round(r008_end_s / r008_dt_s))
    if not (
        parameters.get("TimeOut") is not None
        and cfl == BASE_CFL
        and dp == PRODUCTION_DP_M
        and parameters.get("Visco") == FLUID_NU_M2_S
        and math.isclose(parameters.get("TimeOut", math.nan), expected_base_output_dt_s(), rel_tol=1e-12, abs_tol=1e-15)
        and math.isfinite(parameters.get("TimeMax", math.nan))
        and "FullyFilledChannelFluid" in ET.tostring(xml_root, encoding="unicode")
    ):
        raise ValueError("r007 static anchor does not match the frozen q=0.5 production T1 design")
    return {
        "r007_definition_sha256": sha256(definition_path),
        "r007_control_sha256": sha256(control_path),
        "r007_native_preflight_status": preflight["status"],
        "r007_native_geometry_is_input_preflight_only": True,
        "r007_T1_qualification_credit": 0,
        "r007_anchor_TimeMax_s": r007_time_max_s,
        "r007_nominal_observation_start_s": r007_nominal_start_s,
        "r007_first_saved_output_index_at_q0p5": r007_first_saved_index,
        "r007_anchor_end_output_index_at_q0p5": r007_last_saved_index,
        "r007_observation_saved_intervals": r007_last_saved_index - r007_first_saved_index,
        "r007_observation_duration_in_periods": (r007_time_max_s - r007_first_saved_index * r008_dt_s) / period_for_q(0.5),
        "r008_aligned_start_s_at_q0p5": r008_start_s,
        "r008_exact_three_cycle_end_s_at_q0p5": r008_end_s,
        "r008_start_output_index_at_q0p5": r008_start_index,
        "r008_end_output_index_at_q0p5": r008_end_index,
        "r008_observation_saved_intervals": r008_end_index - r008_start_index,
        "r007_minus_r008_end_s": r007_time_max_s - r008_end_s,
        "r007_minus_r008_output_intervals": int(round((r007_time_max_s - r008_end_s) / r008_dt_s)),
        "window_difference_reason": "R007 was a geometry-only preflight and had no solver/T1 credit: its nominal 8.1 s start maps to saved row 510 while its 11T TimeMax maps to row 704, giving 194 intervals (3.03125 periods). R008 uses rows 510..702, exactly 192 intervals/3 periods; the new endpoint is deliberately two T/64 ticks earlier",
        "r007_time_window_reused_for_R008": False,
    }


def expected_base_output_dt_s() -> float:
    return period_for_q(0.5) / BASE_OUTPUT_SAMPLES_PER_PERIOD


def build_receipt() -> dict[str, Any]:
    if (LAB / ROOT / "input").exists() or (LAB / ROOT / "qualification-cases").exists() or (LAB / ROOT / "production-cases").exists():
        raise FileExistsError("R008 input/qualification/production namespace already exists; refusing to adopt or overwrite it")

    parent_summary = validate_parent_evidence()
    contract = load_json(PARAMETER_CONTRACT)
    matrix = qualification_matrix()
    production = production_manifest()
    applicability = gate_applicability(matrix)
    gates = contract["error_gates"]
    numerical = contract["numerical_limits"]
    plan_split = {
        "train": [3, 4, 6, 7, 10, 11, 12, 15, 16, 19, 20, 21, 24, 25, 27, 28],
        "validation": [8, 13, 18, 23],
        "id_test": [5, 9, 14, 17, 22, 26],
        "ood_test": [0, 1, 2, 29, 30, 31],
    }
    return {
        "schema": SCHEMA,
        "record_id": f"{SCOPE_ID}-t1-scope-design-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope_id": SCOPE_ID,
        "status": "static_scope_design_candidate_ready_for_independent_review",
        "family": "F8",
        "mechanism": "fully filled, body-force-driven oscillatory viscous channel; no free surface",
        "root_ruling_effect": "family accepted for Core planning; not T1-qualified and not yet in the T1 denominator",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "qualification_only": True,
        "matrix": {
            "design_rule": "13 spatial configurations + 2 controls = 15 frozen qualification logical configurations",
            "case_count": len(matrix),
            "spatial_anchor_count": sum(row["kind"] == "spatial_anchor" for row in matrix),
            "independent_internal_count": sum(row["kind"] == "independent_internal" for row in matrix),
            "control_count": sum(row["kind"].endswith("control") for row in matrix),
            "rows": matrix,
            "all_rows_are_qualification_only": all(row["qualification_only"] for row in matrix),
            "no_failure_deletion_or_replacement": True,
            "gate_applicability": applicability,
        },
        "frozen_physics_and_control": {
            "q_interval": [0.0, 1.0],
            "alpha_rule": "alpha=2+6*q",
            "omega_rule_rad_s": "omega=alpha^2*nu/H^2",
            "body_acceleration": "ax(t)=0.01*sin(omega*t) m/s^2; zero mean; ay=az=0",
            "rho0_kg_m3": RHO0_KG_M3,
            "nu_m2_s": FLUID_NU_M2_S,
            "sound_speed_m_s": SOUND_SPEED_M_S,
            "gravity_m_s2": [0.0, 0.0, 0.0],
            "geometry_m": {"x": [0.0, LENGTH_X_M], "y": [0.0, LENGTH_Y_M], "z": [-HALF_HEIGHT_M, HALF_HEIGHT_M]},
            "boundary": "periodic x/y; fixed no-slip mDBC z walls; no moving/floating boundaries",
            "observation_window": "earliest=max(2*H^2/nu,2*T); round start upward to the next T/64 native-output grid point; end=start+3*T exactly",
            "sample_window_contract": {
                "baseline_output_dt": "T/64",
                "dense_output_dt": "T/128; uses the same baseline-aligned start/end so every other row matches the 64-ppp baseline",
                "endpoint_policy": "inclusive [t_start,t_end]; both endpoints must be native saved rows",
                "parser_time_filter": "t_start - 1e-12 <= t_native <= t_end + 1e-12; reject any out-of-window row and never extrapolate",
                "expected_sample_count": "3*output_samples_per_period+1 (193 baseline rows; 385 dense rows)",
                "start_rounding": "ceil(earliest_start/(T/64)-1e-12)*(T/64)",
                "duration_check_atol_s": 1e-12,
                "parser_contract_revision": "f8_observation_window_parser_v2.select_closed_native_window",
                "parser_contract_revision_required": "the older parser's one-sided t>=start behavior is not admissible for R008",
            },
            "r007_window_disposition": "R007 TimeMax is retained only as immutable preflight evidence; R008 recomputes t_end=t_start+3*T exactly and uses fresh inputs",
            "control_table_points_per_period": CONTROL_SAMPLES_PER_PERIOD,
            "base_native_output_points_per_period": BASE_OUTPUT_SAMPLES_PER_PERIOD,
            "dense_native_output_points_per_period": DENSE_OUTPUT_SAMPLES_PER_PERIOD,
            "base_cflnumber": BASE_CFL,
            "tight_cflnumber": TIGHT_CFL,
            "production_cases_after_qualification": {
                "count": 32,
                "q_rule": "q_i=(i+0.5)/32, i=0..31",
                "split": plan_split,
                "split_counts": {key: len(value) for key, value in plan_split.items()},
                "case_manifests_in_canonical_index_order": production,
                "fixed_first_8_indices": FIRST_EIGHT_INDICES,
                "fixed_first_8_case_ids": [production[index]["case_id"] for index in FIRST_EIGHT_INDICES],
                "first_8_split_coverage": {
                    "train": [4, 20], "validation": [8, 18], "id_test": [14, 22], "ood_test": [0, 31],
                },
                "fixed_remaining_24_indices": [index for index in range(32) if index not in FIRST_EIGHT_INDICES],
                "fixed_remaining_24_case_ids": [production[index]["case_id"] for index in range(32) if index not in FIRST_EIGHT_INDICES],
                "input_hashes": "new R008 per-case Definition/control hashes must be materialized and bound before any case launch",
                "only_after_all_15_qualification_rows_pass": True,
                "execution_order": "the fixed stratified first 8 in listed order, then remaining indices in ascending order automatically after every fixed release gate passes",
                "first_8_release_gates": {
                    "all_eight_terminal_status_completed": True,
                    "all_eight_input_binary_and_lineage_hashes_match_registry": True,
                    "all_eight_native_frames_finite_and_complete": True,
                    "all_eight_have_exact_inclusive_aligned_three_period_window": True,
                    "all_eight_pass_per_case_physical_and_womersley_gates": True,
                    "all_eight_converted_and_independent_hard_audits_pass": True,
                    "missing_truncated_or_failed_cases": 0,
                    "case_substitution_or_failure_deletion": False,
                    "any_failure_stops_scope_and_preserves_denominator": True,
                    "upon_all_pass_launch_remaining_24_without_case_by_case_confirmation": True,
                },
            },
        },
        "predeclared_t1_gates": {
            "source_parameter_contract_gates": gates,
            "gate_applicability_by_case_and_comparison": applicability,
            "source_hard_integrity_gates": {
                "density_kg_m3": numerical["density_interval_kg_m3"],
                "mach_max": numerical["mach_max"],
                "wall_penetration_max_m": numerical["wall_penetration_max_m"],
                "excluded_fluid_particles": numerical["excluded_fluid_particles"],
                "particle_overlap": numerical["particle_overlap"],
                "all_state_and_control_values_finite": True,
                "control_table_covers_zero_to_t_end_without_extrapolation": True,
                "complete_three_period_observation_window": True,
            },
            "cross_resolution": "at q=0,0.5,1 compare coarse-vs-production and fine-vs-production; at q=0.25,0.75 compare fine-vs-production; use relative amplitude <=0.10 and absolute phase <=0.10 rad for every listed pair",
            "time_step_control": "q=0.5 production dp; CFL 0.1 vs 0.2; record actual dt and require refined max dt < baseline plus phase difference <=0.05 rad",
            "cadence_control": "q=0.5 production dp; native TimeOut=T/128 vs T/64; derive matched downsample from even dense-output rows; each native series meets the same predeclared profile gates",
            "all_15_required": True,
            "threshold_relaxation": False,
            "external_physical_validation_claim": False,
        },
        "lineage_and_execution_boundary": {
            "closed_prior_scopes": [
                {"scope_id": f"F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R00{i}", "same_input_retry_forbidden": True, "prior_output_reuse_forbidden": True}
                for i in range(1, 8)
            ],
            "r007_native_preflight_reused_as_T1_credit": False,
            "r007_native_BI4_reused_for_R008": False,
            "new_definition_control_hashes_required": True,
            "new_output_namespace_required": True,
            "execution_authority_granted": False,
            "required_before_any_R008_runtime": [
                "independent Terra High static review of this frozen matrix and a fresh R008 Definition/control hash closure",
                "separate one-shot CPU/native preflight authorization bound to exact R008 inputs",
                "separate explicit solver/T1 execution authorization and frozen resource admission",
            ],
        },
        "execution_controls": {
            "definition_written": False,
            "control_written": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "worker_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
        },
        "parent_evidence_summary": parent_summary,
        "bindings": [
            bind_plan(),
            bind(ROOT_RULING, "explicit user acceptance of F8 as a distinct mechanism family; no qualification credit"),
            bind(PARAMETER_CONTRACT, "frozen F8 physics, resolution grid, observation, and T1 gates"),
            bind(R007_REVIEW, "passed immutable R007 static design review"),
            bind(R007_MATERIALIZATION, "R007 static-only input materialization receipt"),
            bind(R007_AUTHORIZATION, "consumed one-shot R007 CPU/native authorization"),
            bind(R007_PREFLIGHT, "passed R007 native geometry preflight, zero qualification credit"),
            bind(R007_LOCK, "R007 no-retry one-shot lock"),
            bind(R007_DEFINITION, "R007 preflight-bound anchor Definition; not reused by R008"),
            bind(R007_CONTROL, "R007 preflight-bound anchor control; not reused by R008"),
            bind(OBSERVATION_PARSER, "F8 static observation parser contract"),
            bind(OBSERVATION_PARSER_V2, "closed inclusive native-only F8 observation-window parser v2"),
            bind(OBSERVATION_PARSER_V2_TEST, "parser v2 endpoint/cadence/missing-row regression tests"),
            bind(REFERENCE_ORACLE, "continuum Womersley reference contract; not CFD qualification"),
            bind(Path("scripts/f8_t1_scope_design_v1.py"), "read-only R008 T1 scope matrix builder"),
            bind(Path("tests/test_f8_t1_scope_design_v1.py"), "R008 matrix and boundary contract tests"),
        ],
    }


def write_receipt() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite immutable R008 scope design: {OUTPUT}")
    receipt = build_receipt()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    receipt = write_receipt()
    print(json.dumps({
        "status": receipt["status"],
        "matrix_count": receipt["matrix"]["case_count"],
        "qualification_credit": receipt["qualification_credit"],
        "execution_authority_granted": receipt["lineage_and_execution_boundary"]["execution_authority_granted"],
    }, indent=2, sort_keys=True))
