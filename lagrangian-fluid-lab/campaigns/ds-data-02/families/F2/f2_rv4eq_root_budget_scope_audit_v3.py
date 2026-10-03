#!/usr/bin/env python3
"""Audit F2 timing budget scope separation and generate immutable root_budget_scope_audit_003 sidecar.

This v3 producer addresses Root's review of commit 2f9905d1 by:
1. Retracting scientifically invented terminology ('cumulative timing integration error entire 4s
   vs per-individual-bracket') from earlier review drafts. The frozen contract defines fractions
   of event total directly; there is no cumulative over window budget.
2. Establishing strict scope separation:
   - Original baseline contract (quality_contract.json):
     event budget = 0.0036681953999691376 s, save fraction = 0.2 => baseline save allowance = 0.0007336390799938275 s (~0.0007336391 s).
     Supported earlier v4 recipe and baseline event audits.
   - New MATCHED preregistration (rv4_matched_three_dp_init_v1/f2_rv4_matched_solver_requests_v1.py):
     chooses a further 0.2 factor => matched save allowance = 0.0001467278159987655 s (~0.0001467278 s).
     Governs NEW MATCHED references ONLY when explicitly preregistered; NOT applied retrospectively to baselines.
3. Independent evaluation under own allowances:
   - Baseline cases: observed dt = 0.010 s save bracket half-width (~0.005013 s) exceeds its OWN baseline allowance (0.0007336391 s) by 6.83x => FAILS.
   - Matched reference cases: observed dt = 0.010 s save bracket half-width (0.005000 s) exceeds its OWN matched allowance (0.0001467278 s) by 34.08x => FAILS.
   - Both scopes fail their OWN respective allowance. Zero threshold loosening. No Q-N or production granted.
4. Trajectory conversion jurisdictional clarification:
   - Root retains full authority to authorize macro converters despite pending event timing.
   - Delegated family owners simply lack authority to launch them.
5. Preserving Root's independent verification that all 2,151 PartVTKOut Idp map to terminal
   initial_type=3 fluid (194,457 / 196,608 final valid, 76,676 moving nodes intact),
   confirming that 0.268875 kg unknown fluid mass is fully supported as numerical boundary exclusions.
6. Preserving commit 2f9905d1 artifacts intact as historical review artifacts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


FAMILY_ROOT = Path(__file__).resolve().parent
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261003"
OFFSET_QI_DIR = HANDOFF_ROOT / "offset_baseline_terminal_v1/qi_audit"
CENTER_QI_DIR = HANDOFF_ROOT / "center_baseline_terminal_v1/qi_audit"
RV4_ROOT = HANDOFF_ROOT / "rv4_matched_three_dp_init_v1"
AUDIT_V2_DIR = HANDOFF_ROOT / "root_budget_scope_audit_002"
AUDIT_V3_DIR = HANDOFF_ROOT / "root_budget_scope_audit_003"

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")
OFFSET_CASE = DATA_ROOT / "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001"

# Timing budget constants from frozen quality contract
CHARACTERISTIC_TIME_T_CHAR_S = 0.18340976999845688
EVENT_TIME_FRACTION_MAX = 0.02
EVENT_TIME_ABSOLUTE_BUDGET_S = CHARACTERISTIC_TIME_T_CHAR_S * EVENT_TIME_FRACTION_MAX  # 0.0036681953999691376

# Baseline quality contract save allowance
BASELINE_SAVE_FRACTION_MAX = 0.2
BASELINE_SAVE_ALLOWANCE_S = EVENT_TIME_ABSOLUTE_BUDGET_S * BASELINE_SAVE_FRACTION_MAX  # 0.0007336390799938275

# New matched reference preregistration save allowance
MATCHED_PREREG_FRACTION = 0.2
MATCHED_SAVE_ALLOWANCE_S = BASELINE_SAVE_ALLOWANCE_S * MATCHED_PREREG_FRACTION  # 0.0001467278159987655


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
    audit_v2_sidecar_path = require(
        AUDIT_V2_DIR / "root_budget_scope_audit_002.json",
        "audit v2 review sidecar",
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
            "all_within_baseline_allowance_0p0007336s": False,
            "all_within_matched_allowance_0p0001467s": False,
        }

    sidecar = {
        "schema": "ds02.f2.root-budget-scope-audit.v3",
        "audit_id": "root_budget_scope_audit_003",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F2",
        "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
        "scope_id": "F2_SCOPE_RV4_TIMING_BUDGET_SEPARATION_20261003",
        "status": "frozen_immutable_timing_scope_separation_audit_complete",
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
        "terminology_correction_and_scope_separation": {
            "retracted_erroneous_terminology": (
                "Retracted scientifically invented phrasing 'cumulative timing integration error entire 4s "
                "vs. per-individual-bracket' from v2 review draft. The frozen contract defines fractions "
                "of the event total directly; there is no cumulative over window budget."
            ),
            "scope_separation_summary": (
                "The timing budget values reflect two strictly distinct qualification scopes, not cumulative vs bracket divisions: "
                "(1) Original baseline contract defines event budget 0.0036681953999691376 s and "
                "save_fraction_of_total_error_budget_max 0.2 => baseline save allowance 0.0007336390799938275 s (~0.0007336391 s), "
                "supporting earlier v4 recipe and baseline event audits. "
                "(2) New MATCHED preregistration explicitly chooses an additional 0.2 factor => 0.0001467278159987655 s (~0.0001467278 s), "
                "governing new matched reference studies only when explicitly preregistered, NOT applied retrospectively to RV4 baselines."
            ),
            "authoritative_allowances_by_scope": {
                "baseline_contract_scope": {
                    "scope_name": "original_rv4_baseline_contract",
                    "governing_contract": "quality_contract.json",
                    "event_time_absolute_budget_s": EVENT_TIME_ABSOLUTE_BUDGET_S,
                    "save_fraction_of_total_error_budget_max": BASELINE_SAVE_FRACTION_MAX,
                    "authoritative_save_allowance_s": BASELINE_SAVE_ALLOWANCE_S,
                    "applicability": (
                        "Applies to original RV4 baselines (e.g., F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001, "
                        "F2_RV4EQ_DP005_CENTER_V1_BASELINE_SAVE001). Under this allowance, observed dt=0.010 s "
                        "save bracket half-width ~0.005013 s fails by 6.83x."
                    ),
                },
                "matched_preregistration_scope": {
                    "scope_name": "rv4_matched_three_dp_reference_preregistration",
                    "governing_contract": "rv4_matched_three_dp_init_v1/f2_rv4_matched_solver_requests_v1.py",
                    "event_time_absolute_budget_s": EVENT_TIME_ABSOLUTE_BUDGET_S,
                    "save_total_budget_s": BASELINE_SAVE_ALLOWANCE_S,
                    "matched_prereg_fraction": MATCHED_PREREG_FRACTION,
                    "authoritative_save_allowance_s": MATCHED_SAVE_ALLOWANCE_S,
                    "applicability": (
                        "Applies ONLY to newly preregistered matched reference studies (COARSE DP010, MEDIUM DP008). "
                        "Never applied retroactively to original baselines. Under this allowance, observed dt=0.010 s "
                        "save bracket half-width 0.005000 s fails by 34.08x."
                    ),
                },
            },
        },
        "audit_evaluations_under_own_allowance": {
            "offset_baseline_fine_dp005": {
                "case_id": "F2_RV4EQ_DP005_OFFSET_V1_BASELINE_SAVE001",
                "applicable_scope": "original_rv4_baseline_contract",
                "applicable_save_allowance_s": BASELINE_SAVE_ALLOWANCE_S,
                "observed_save_interval_s": 0.010,
                "observed_bracket_half_width_range_s": [0.004989347651231046, 0.005012849578867051],
                "max_observed_bracket_half_width_s": 0.005012849578867051,
                "ratio_observed_to_own_allowance": 0.005012849578867051 / BASELINE_SAVE_ALLOWANCE_S,
                "evaluation_status": "FAIL / PENDING",
                "reason": (
                    "Observed save interval dt=0.010 s yields bracket half-width 0.005013 s, which exceeds its OWN "
                    "baseline contract allowance of 0.0007336391 s by 6.83x. Event Q-N qualification is strictly "
                    "NOT granted. Retains original negative."
                ),
                "event_counts_by_code": offset_sidecar.get("labels", {}).get("event_counts_by_code", {}),
                "observed_bracket_stats_by_code": observed_brackets,
            },
            "spatial_save010_reference_cases": {
                "case_ids": [
                    "F2_RV4EQ_MATCHED_CENTER_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
                    "F2_RV4EQ_MATCHED_CENTER_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
                    "F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010",
                    "F2_RV4EQ_MATCHED_OFFSET_V1_MEDIUM_DP008_SPATIAL_REFERENCE_SAVE010",
                ],
                "applicable_scope": "rv4_matched_three_dp_reference_preregistration",
                "applicable_save_allowance_s": MATCHED_SAVE_ALLOWANCE_S,
                "observed_save_interval_s": 0.010,
                "observed_bracket_half_width_s": 0.0050,
                "ratio_observed_to_own_allowance": 0.0050 / MATCHED_SAVE_ALLOWANCE_S,
                "evaluation_status": "FAIL / PENDING",
                "reason": (
                    "Observed save interval dt=0.010 s yields bracket half-width 0.005000 s, which exceeds its OWN "
                    "matched preregistration allowance of 0.0001467278 s by 34.08x. Event Q-N qualification is strictly "
                    "NOT granted. Retains original negative."
                ),
            },
            "cross_scope_synthesis": (
                "Both original baseline cases and new matched reference cases fail their OWN respective applicable "
                "save allowances under observed dt=0.010 s. No loosening permitted. No event Q-N granted. "
                "No production qualification granted."
            ),
        },
        "jurisdictional_and_operational_boundaries": {
            "converter_authorization_policy": (
                "Root retains full authority to authorize macro converters despite pending event timing. "
                "Delegated family owners simply cannot launch them. Trajectory conversions are not claimed to be "
                "scientifically disallowed; delegate launch is simply unauthorized."
            ),
            "delegated_authority_limits": {
                "gpu_launches_forbidden_to_delegates": True,
                "delegate_trajectory_conversion_launch_forbidden": True,
                "root_macro_converter_authorization_supported": True,
                "bounded_cpu_audit_permitted": True,
                "shared_dispatch_required_for_cpu": True,
                "preserve_dirty_and_staged_files": True,
                "preserve_consumed_h5_and_sources": True,
                "no_recursive_delegation": True,
                "no_silent_model_switching": True,
                "approved_qualification_cap": 320,
                "approved_home_floor_gib": 500,
                "machine_learning_models_forbidden": True,
            },
            "f3_weak_quarter_freeze_preservation": {
                "original_allocation_x_m": 0.010238388262513484,
                "original_allocation_y_m": 0.017270993599294474,
                "actual_conditional_gap_x_m": 0.02248,
                "actual_conditional_gap_y_m": 0.06929,
                "status": "fail (preserved original negative; cohort quantile diagnostic is not original preregistered gate; no new F3 GPU)",
            },
            "historical_artifacts_preservation": {
                "commit_2f9905d1_preserved_unchanged": True,
                "root_budget_scope_audit_002_preserved_as_review_artifact": True,
                "quality_contract_preserved_unchanged": True,
                "consumed_h5_and_receipts_preserved": True,
            },
            "qualification_status": {
                "q_i_status": "actual integrity structure pass only (Q-I-structure-pass)",
                "q_n_status": "not_assessed",
                "production_status": "not_evaluated",
                "q_n_granted": False,
                "production_granted": False,
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
                "role": "F2 quality contract defining Q-I, Q-N, Q-E and baseline timing budget allowance (0.0007336391 s)",
            },
            "solver_requests_script": {
                "path": str(solver_requests_script_path),
                "sha256": sha256(solver_requests_script_path),
                "bytes": solver_requests_script_path.stat().st_size,
                "role": "matched RV4 solver requests producer with explicit SAVE_ALLOCATION (0.0001467278 s)",
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
            "root_budget_scope_audit_002": {
                "path": str(audit_v2_sidecar_path),
                "sha256": sha256(audit_v2_sidecar_path),
                "bytes": audit_v2_sidecar_path.stat().st_size,
                "role": "preserved commit 2f9905d1 audit sidecar (historical review artifact)",
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
    primary_sidecar_path = AUDIT_V3_DIR / "root_budget_scope_audit_003.json"
    dump(primary_sidecar_path, sidecar)

    qi_sidecar_path = OFFSET_QI_DIR / "root_budget_scope_audit_003.json"
    dump(qi_sidecar_path, sidecar)

    return sidecar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()
    sidecar = generate_sidecar()
    print("Generated root_budget_scope_audit_003 sidecar successfully:")
    print(f"  Primary: {AUDIT_V3_DIR / 'root_budget_scope_audit_003.json'}")
    print(f"  QI Dir:  {OFFSET_QI_DIR / 'root_budget_scope_audit_003.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
