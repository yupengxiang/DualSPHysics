#!/usr/bin/env python3
"""Audit F2 frozen timing budget scope and generate immutable root_budget_scope_audit_002 sidecar.

This producer audits and formalizes the distinction between:
1. Cumulative save integration total budget:
   SAVE_TOTAL_BUDGET_S = 0.0007336390799938275 s
   (20% of the total event window timing budget 0.0036681953999691376 s).
2. Authoritative applicable per-save output contribution allocation:
   SAVE_ALLOCATION_S = 0.0001467278159987655 s
   (20% of the save integration total budget, i.e. 0.0007336390799938275 / 5).

It documents:
- Why the offset and center sidecars previously referenced 0.0007336390799938275 s
  under 'save_half_width_budget_s' (referencing the total save budget).
- Why the authoritative applicable allocation for each discrete save bracket half-width
  is SAVE_ALLOCATION_S = 0.0001467278159987655 s.
- That observed save interval dt = 0.010 s (half bracket ~0.005 s) exceeds BOTH thresholds
  (6.82x of total budget, 34.08x of per-save allocation).
- All original negative outcomes are retained with ZERO loosening.
- Root's independent verification that all 2,151 PartVTKOut Idp map to terminal
  initial_type=3 fluid (194,457 / 196,608 final valid, 76,676 moving nodes intact),
  confirming that 0.268875 kg unknown fluid mass is fully supported as numerical unknown cohort.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping


FAMILY_ROOT = Path(__file__).resolve().parent
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003"
OFFSET_QI_DIR = HANDOFF_ROOT / "offset_baseline_terminal_v1/qi_audit"
CENTER_QI_DIR = HANDOFF_ROOT / "center_baseline_terminal_v1/qi_audit"
RV4_ROOT = HANDOFF_ROOT / "rv4_matched_three_dp_init_v1"
AUDIT_DIR = HANDOFF_ROOT / "root_budget_scope_audit_002"

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")
OFFSET_CASE = DATA_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"

# Timing budget constants
CHARACTERISTIC_TIME_T_CHAR_S = 0.18340976999845688
EVENT_TIME_FRACTION_MAX = 0.02
EVENT_TIME_ABSOLUTE_BUDGET_S = CHARACTERISTIC_TIME_T_CHAR_S * EVENT_TIME_FRACTION_MAX  # 0.0036681953999691376

SAVE_FRACTION_OF_TOTAL_MAX = 0.2
SAVE_TOTAL_BUDGET_S = EVENT_TIME_ABSOLUTE_BUDGET_S * SAVE_FRACTION_OF_TOTAL_MAX  # 0.0007336390799938275

SAVE_PER_STUDY_ALLOCATION_FRACTION = 0.2
SAVE_ALLOCATION_S = SAVE_TOTAL_BUDGET_S * SAVE_PER_STUDY_ALLOCATION_FRACTION  # 0.0001467278159987655


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate_sidecar() -> dict[str, Any]:
    # Key source artifacts to bind
    offset_sidecar_path = require(
        OFFSET_QI_DIR / "F2_RV4EQ_DP005_OFFSET_actual_pose_labels_qi_sidecar_v1.json",
        "offset actual pose labels qi sidecar",
    )
    center_sidecar_path = require(
        CENTER_QI_DIR / "F2_RV4EQ_DP005_CENTER_actual_pose_labels_qi_sidecar_v1.json",
        "center actual pose labels qi sidecar",
    )
    quality_contract_path = require(
        FAMILY_ROOT / "quality_contract.json",
        "quality contract",
    )
    solver_requests_script_path = require(
        RV4_ROOT / "f2_rv4_matched_solver_requests_v1.py",
        "solver requests generator script",
    )
    save_budget_review_v1_path = require(
        RV4_ROOT / "solver_requests_v1/save-budget-review-v1.json",
        "save budget review v1",
    )
    spatial_reference_budget_path = require(
        RV4_ROOT / "solver_requests_spatial_reference_v1/save-budget-review-v1.json",
        "spatial reference save budget review",
    )
    spatial_macro_manifest_path = require(
        RV4_ROOT / "artifacts/rv4_matched_spatial_macro_preregistration_manifest_v1.json",
        "spatial macro preregistration manifest",
    )

    # Runtime artifacts from OFFSET terminal runs
    offset_obs_path = require(
        OFFSET_CASE / "offset-terminal-nvme-labels-v2-002/f2-v6-observations.json",
        "offset v6 observations",
    )
    offset_labels_receipt_path = require(
        OFFSET_CASE / "offset-terminal-nvme-labels-v2-002/execution-receipt.json",
        "offset labels execution receipt",
    )
    offset_pose_report_path = require(
        OFFSET_CASE / "offset-terminal-nvme-pose-v2-001/rigid-body-state.json",
        "offset pose report",
    )
    offset_pose_receipt_path = require(
        OFFSET_CASE / "offset-terminal-nvme-pose-v2-001/execution-receipt.json",
        "offset pose receipt",
    )
    offset_qi_report_path = require(
        OFFSET_CASE / "qi-f2-rv4eq-offset-v1-baseline-save001-pose-labels-actual-002/f2-offset-qi-integrity.json",
        "offset qi integrity report",
    )
    offset_qi_receipt_path = require(
        OFFSET_CASE / "qi-f2-rv4eq-offset-v1-baseline-save001-pose-labels-actual-002/execution-receipt.json",
        "offset qi execution receipt",
    )

    # Read sidecar and observations for actual bracket measurements
    offset_sidecar = read_json(offset_sidecar_path, "offset sidecar")
    offset_obs = read_json(offset_obs_path, "offset observations")

    obs_stats = offset_obs.get("event_ledger", {}).get("observed_event_bracket_stats_s_by_code", {})
    observed_brackets = {}
    for code, st in obs_stats.items():
        observed_brackets[code] = {
            "count": st.get("count"),
            "min_s": st.get("min_s"),
            "max_s": st.get("max_s"),
            "all_within_total_budget_0p0007336s": False,
            "all_within_applicable_allocation_0p0001467s": False,
        }

    sidecar = {
        "schema": "ds02.f2.root-budget-scope-audit.v2",
        "audit_id": "root_budget_scope_audit_002",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F2",
        "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
        "scope_id": "F2_SCOPE_RV4_MATCHED_THREE_DP_INIT_20261003",
        "status": "frozen_immutable_timing_scope_audit_complete",
        "root_partvtkout_independent_mapping": {
            "status": "confirmed_supported_by_root_and_family_owner",
            "total_native_unknown_fluid_particles": 2151,
            "partvtkout_idp_mapping_finding": (
                "Root independently mapped all 2151 PartVTKOut Idp to terminal initial_type=3 fluid, "
                "finalvalid 194457/196608, moving 76676 intact. Unknown fluid mass .268875kg therefore supported."
            ),
            "initial_fluid_particle_count": 196608,
            "retained_valid_fluid_particle_count": 194457,
            "intact_moving_type1_particle_count": 76676,
            "unknown_fluid_mass_kg": 0.268875,
            "native_motive_code": 1,
            "native_motive_counts": {"1": 2151, "2": 0, "3": 0},
            "interpretation": (
                "The 0.268875 kg unknown fluid mass represents native numerical exclusions "
                "(all 2,151 motive 1 position exclusions at domain boundary), NOT physical spill or receiver exit. "
                "Unknown mass remains strictly documented in denominator and excluded from physical fate."
            ),
        },
        "budget_hierarchy_and_definitions": {
            "characteristic_time_T_char_s": CHARACTERISTIC_TIME_T_CHAR_S,
            "event_time_fraction_max": EVENT_TIME_FRACTION_MAX,
            "event_time_absolute_budget_s": EVENT_TIME_ABSOLUTE_BUDGET_S,
            "save_fraction_of_total_max": SAVE_FRACTION_OF_TOTAL_MAX,
            "save_integration_total_budget_s": SAVE_TOTAL_BUDGET_S,
            "save_per_study_allocation_fraction": SAVE_PER_STUDY_ALLOCATION_FRACTION,
            "authoritative_applicable_save_allocation_s": SAVE_ALLOCATION_S,
        },
        "distinction_analysis": {
            "total_budget": {
                "name": "save_integration_total_budget_s / SAVE_TOTAL_BUDGET_S",
                "value_s": SAVE_TOTAL_BUDGET_S,
                "scientific_meaning": (
                    "Maximum cumulative timing integration error budget allocated to save-frequency "
                    "discretization across the entire 4.0-second event window (20% of total event timing budget)."
                ),
                "sidecar_usage_audit": (
                    "In F2_RV4EQ_DP005_OFFSET_actual_pose_labels_qi_sidecar_v1.json (and CENTER sidecar), "
                    "the field 'save_half_width_budget_s' was set to 0.0007336390799938275 s. "
                    "This referenced the cumulative save integration total budget rather than the per-save contribution."
                ),
            },
            "allocated_output_contribution": {
                "name": "save_per_study_allocation_s / SAVE_ALLOCATION_S",
                "value_s": SAVE_ALLOCATION_S,
                "scientific_meaning": (
                    "Authoritative applicable allocation for each discrete save bracket half-width (Delta t_save / 2). "
                    "To prevent cumulative save integration error from exhausting the total budget, each individual "
                    "output save bracket must satisfy this fractional allocation (20% of total save budget, i.e. 1/5)."
                ),
                "preregistration_usage_audit": (
                    "Explicitly defined in rv4_matched_three_dp_init_v1/f2_rv4_matched_solver_requests_v1.py as "
                    "SAVE_ALLOCATION_S = 0.0001467278159987655 s, against which the candidate spatial save half-bracket "
                    "(0.0005 s for dt=0.001 s, or 0.005 s for dt=0.010 s) was evaluated and marked deferred."
                ),
            },
            "authoritative_status": (
                "The authoritative applicable requirement for individual save-interval qualification is "
                "SAVE_ALLOCATION_S = 0.0001467278159987655 s (half-bracket <= 0.0001467278159987655 s). "
                "Evaluating against SAVE_TOTAL_BUDGET_S (0.0007336390799938275 s) is a looser upper-bound check."
            ),
        },
        "audit_evaluations": {
            "offset_baseline_fine_dp005": {
                "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
                "observed_save_interval_s": 0.010,
                "observed_bracket_half_width_range_s": [0.004989347651231046, 0.005012849578867051],
                "evaluation_against_total_budget_0p0007336s": {
                    "budget_s": SAVE_TOTAL_BUDGET_S,
                    "max_observed_half_width_s": 0.005012849578867051,
                    "ratio_observed_to_budget": 0.005012849578867051 / SAVE_TOTAL_BUDGET_S,
                    "status": "FAIL / PENDING",
                },
                "evaluation_against_authoritative_allocation_0p0001467s": {
                    "budget_s": SAVE_ALLOCATION_S,
                    "max_observed_half_width_s": 0.005012849578867051,
                    "ratio_observed_to_budget": 0.005012849578867051 / SAVE_ALLOCATION_S,
                    "status": "FAIL / PENDING",
                },
                "event_counts_by_code": offset_sidecar.get("labels", {}).get("event_counts_by_code", {}),
                "observed_bracket_stats_by_code": observed_brackets,
                "retained_original_negative": (
                    "No loosening. Under BOTH standards, the observed ~0.005 s half-bracket exceeds the allowance "
                    "(by 6.83x against total budget and by 34.16x against authoritative allocation). "
                    "Event Q-N qualification remains strictly NOT granted (claims.q_n remains 'not_assessed', "
                    "q_n_granted remains false)."
                ),
            },
            "spatial_save010_reference_cases": {
                "case_ids": [
                    "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
                    "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
                    "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
                    "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
                ],
                "observed_save_interval_s": 0.010,
                "observed_bracket_half_width_s": 0.0050,
                "evaluation_against_authoritative_allocation_0p0001467s": {
                    "budget_s": SAVE_ALLOCATION_S,
                    "ratio_observed_to_budget": 0.0050 / SAVE_ALLOCATION_S,
                    "status": "FAIL / PENDING",
                },
                "retained_original_negative": (
                    "Save interval .01 s is insufficient for event temporal allocation 0.0001467278159987655 s. "
                    "Never grant event Q-N from these spatial macros. Trajectory conversions remain disallowed."
                ),
            },
        },
        "preserved_boundaries_and_policies": {
            "retain_original_negatives": True,
            "no_loosening_permitted": True,
            "q_i_status": "actual integrity structure pass only (Q-I-structure-pass)",
            "q_n_status": "not_assessed",
            "production_status": "not_evaluated",
            "q_n_granted": False,
            "production_granted": False,
            "f3_weak_quarter_freeze_preservation": {
                "original_allocation_x_m": 0.010238388262513484,
                "original_allocation_y_m": 0.017270993599294474,
                "actual_conditional_gap_x_m": 0.02248,
                "actual_conditional_gap_y_m": 0.06929,
                "status": "fail (preserved original negative; cohort quantile diagnostic is not original preregistered gate; no new F3 GPU)",
            },
            "operational_ledger": {
                "consumed_h5_preserved": True,
                "consumed_sources_preserved": True,
                "consumed_sidecars_preserved": True,
                "gpu_launches_forbidden_to_delegates": True,
                "trajectory_conversions_forbidden": True,
                "bounded_cpu_audit_permitted": True,
                "qualification_cap": 320,
                "home_floor_gib": 500,
                "machine_learning_models_forbidden": True,
            },
        },
        "source_bindings": {
            "offset_actual_pose_labels_qi_sidecar_v1": {
                "path": str(offset_sidecar_path),
                "sha256": sha256(offset_sidecar_path),
                "bytes": offset_sidecar_path.stat().st_size,
                "role": "canonical OFFSET baseline actual closure sidecar",
            },
            "center_actual_pose_labels_qi_sidecar_v1": {
                "path": str(center_sidecar_path),
                "sha256": sha256(center_sidecar_path),
                "bytes": center_sidecar_path.stat().st_size,
                "role": "canonical CENTER baseline actual closure sidecar",
            },
            "quality_contract": {
                "path": str(quality_contract_path),
                "sha256": sha256(quality_contract_path),
                "bytes": quality_contract_path.stat().st_size,
                "role": "F2 quality contract defining Q-I, Q-N, Q-E and timing budget fractions",
            },
            "solver_requests_script": {
                "path": str(solver_requests_script_path),
                "sha256": sha256(solver_requests_script_path),
                "bytes": solver_requests_script_path.stat().st_size,
                "role": "matched RV4 solver requests producer with explicit SAVE_TOTAL_BUDGET and SAVE_ALLOCATION",
            },
            "save_budget_review_v1": {
                "path": str(save_budget_review_v1_path),
                "sha256": sha256(save_budget_review_v1_path),
                "bytes": save_budget_review_v1_path.stat().st_size,
                "role": "save budget review defining event and per-study allocations",
            },
            "spatial_reference_save_budget_review": {
                "path": str(spatial_reference_budget_path),
                "sha256": sha256(spatial_reference_budget_path),
                "bytes": spatial_reference_budget_path.stat().st_size,
                "role": "spatial reference SAVE010 review marking event qualification deferred",
            },
            "spatial_macro_preregistration_manifest": {
                "path": str(spatial_macro_manifest_path),
                "sha256": sha256(spatial_macro_manifest_path),
                "bytes": spatial_macro_manifest_path.stat().st_size,
                "role": "preregistration manifest enforcing save bracket > event allocation boundary",
            },
            "offset_v6_observations": {
                "path": str(offset_obs_path),
                "sha256": sha256(offset_obs_path),
                "bytes": offset_obs_path.stat().st_size,
                "role": "actual OFFSET v6 finite-cup receiver tray observations",
            },
            "offset_labels_receipt": {
                "path": str(offset_labels_receipt_path),
                "sha256": sha256(offset_labels_receipt_path),
                "bytes": offset_labels_receipt_path.stat().st_size,
                "role": "OFFSET labels execution receipt (code 0, completed)",
            },
            "offset_pose_report": {
                "path": str(offset_pose_report_path),
                "sha256": sha256(offset_pose_report_path),
                "bytes": offset_pose_report_path.stat().st_size,
                "role": "OFFSET moving pose fit report",
            },
            "offset_pose_receipt": {
                "path": str(offset_pose_receipt_path),
                "sha256": sha256(offset_pose_receipt_path),
                "bytes": offset_pose_receipt_path.stat().st_size,
                "role": "OFFSET pose execution receipt (code 0, completed)",
            },
            "offset_qi_report": {
                "path": str(offset_qi_report_path),
                "sha256": sha256(offset_qi_report_path),
                "bytes": offset_qi_report_path.stat().st_size,
                "role": "OFFSET Q-I integrity report (Q-I-structure-pass)",
            },
            "offset_qi_receipt": {
                "path": str(offset_qi_receipt_path),
                "sha256": sha256(offset_qi_receipt_path),
                "bytes": offset_qi_receipt_path.stat().st_size,
                "role": "OFFSET Q-I execution receipt (code 0, completed)",
            },
        },
    }

    # Write to primary audit location and copy to offset qi_audit for easy discovery
    primary_sidecar_path = AUDIT_DIR / "root_budget_scope_audit_002.json"
    dump(primary_sidecar_path, sidecar)

    qi_sidecar_path = OFFSET_QI_DIR / "root_budget_scope_audit_002.json"
    dump(qi_sidecar_path, sidecar)

    return sidecar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    sidecar = generate_sidecar()
    print("Generated root_budget_scope_audit_002 sidecar successfully:")
    print(f"  Primary: {AUDIT_DIR / 'root_budget_scope_audit_002.json'}")
    print(f"  QI Dir:  {OFFSET_QI_DIR / 'root_budget_scope_audit_002.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
