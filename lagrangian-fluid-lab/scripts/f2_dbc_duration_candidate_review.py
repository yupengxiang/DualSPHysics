#!/usr/bin/env python3
"""Read-only review and proposal for the F2 slow-rotation DBC candidate.

The script reads the completed 5 s DBC product and the already registered
duration design.  It never calls GenCase, the solver, a decoder, or a ledger
writer.  The output is a versioned dynamics review, a one-canary proposal at
the registered q=1 endpoint, and a note that the static volume-hold card is a
prerequisite only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_f2_qualification as f2q


PRODUCT_RELATIVE = Path(
    "campaigns/core-v1/runtime/attempts/"
    "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-extension5s-v2-001/"
    "20260920T031752-07b411be288d/product"
)
PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2_extension5s_v2/"
    "prepared.json"
)
OBSERVATIONS_RELATIVE = PRODUCT_RELATIVE / "observations.json"
COMPLETION_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-extension5s-root-completion-v1.json"
)
OBSERVER_V3_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-extension5s-observer-v3-metadata-reaudit.json"
)
DURATION_CARD_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-duration-qualification-parameter-card-v1.json"
)
DURATION_DESIGN_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-duration-qualification-design-v1.json"
)
STATIC_CARD_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-static-full-cup-volume-hold-candidate-v1.json"
)
STATIC_ANCHOR_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-full-cup-v3-static-hold-root-integration-v1.json"
)
STATIC_PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_canary_v3/prepared.json"
)
STATIC_PREFLIGHT_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_canary_v3/static-preflight.json"
)
DBC_PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2/"
    "prepared.json"
)
DBC_EXTENSION_PREPARED_RELATIVE = PREPARED_RELATIVE
DBC_EXTENSION_JOB_RELATIVE = Path(
    "campaigns/core-v1/cfd/"
    "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-extension5s-v2-job.json"
)
SOLVER_RELATIVE = Path(
    "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
DECODER_RELATIVE = Path("campaigns/l1-resume/artifacts/bi4_dump")

OUTSIDE_MASS_THRESHOLD = 0.01
SETTLE_SPEED_M_S = 0.10
SETTLE_KE_FRACTION = 0.05
SETTLE_HOLD_S = 0.20
POST_SETTLE_OBSERVATION_S = 0.35
BASE_DURATION_S = 0.85
CANDIDATE_DURATION_S = 1.20
MOTION_START_S = 0.50
ANGLE_DEGREES = -105.0
DP_M = 0.0075
REGISTERED_WINDOW_S = 5.0


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path, lab_root: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "relative_to_lab": str(path.relative_to(lab_root.resolve())),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _inside(points: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.all((points >= low) & (points <= high), axis=1)


def _longest_true_run(mask: np.ndarray, times: np.ndarray) -> dict[str, Any]:
    best_count = 0
    best_start: int | None = None
    current_count = 0
    current_start: int | None = None
    for index, value in enumerate(mask.tolist()):
        if value:
            if current_count == 0:
                current_start = index
            current_count += 1
            if current_count > best_count:
                best_count = current_count
                best_start = current_start
        else:
            current_count = 0
            current_start = None
    if best_start is None:
        return {"frame_count": 0, "duration_s": 0.0, "start_s": None, "end_s": None}
    end = best_start + best_count - 1
    return {
        "frame_count": int(best_count),
        "duration_s": float(times[end] - times[best_start]),
        "start_s": float(times[best_start]),
        "end_s": float(times[end]),
    }


def _read_dynamics(lab_root: Path) -> dict[str, Any]:
    product = (lab_root / PRODUCT_RELATIVE).resolve()
    prepared_path = (lab_root / PREPARED_RELATIVE).resolve()
    observations_path = (lab_root / OBSERVATIONS_RELATIVE).resolve()
    completion_path = (lab_root / COMPLETION_RELATIVE).resolve()
    observer_path = (lab_root / OBSERVER_V3_RELATIVE).resolve()
    trajectory = product / "trajectory.h5"
    audit = product / "audit.json"
    result = product / "result.json"
    for path in (trajectory, audit, result, observations_path, prepared_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    observations = json.loads(observations_path.read_text())
    audit_data = json.loads(audit.read_text())
    result_data = json.loads(result.read_text())
    completion = json.loads(completion_path.read_text())
    observer_v3 = json.loads(observer_path.read_text())

    cup = config["cup"]
    receiver = config["receiver"]
    tray = config["tray"]
    dp = float(config["dp_m"])
    duration = float(config["parameter"]["value"])
    cup_low = np.asarray(cup["low"], dtype=float)
    cup_high = cup_low + np.asarray(cup["size"], dtype=float)
    receiver_low = np.asarray(receiver["low"], dtype=float) + dp
    receiver_high = receiver_low + np.asarray(receiver["size"], dtype=float) - 2.0 * dp
    tray_low = np.asarray(tray["low"], dtype=float) + dp
    tray_high = (
        np.asarray(tray["low"], dtype=float)
        + np.asarray(tray["size"], dtype=float)
        - np.asarray([dp, dp, 0.0])
    )

    times = np.asarray(observations["time_s"], dtype=float)
    kinetic = np.asarray(observations["kinetic_energy_over_initial_potential"], dtype=float)
    speed_p95 = np.asarray(observations["speed_p95_m_s"], dtype=float)
    motion_complete_s = MOTION_START_S + duration
    post_motion = times >= motion_complete_s
    settle_speed = post_motion & (speed_p95 <= SETTLE_SPEED_M_S)
    settle_energy = post_motion & (kinetic <= SETTLE_KE_FRACTION)
    settle_both = settle_speed & settle_energy
    with h5py.File(trajectory, "r") as handle:
        native_ids = np.asarray(handle["particle_id"][:])
        initial_valid = np.asarray(handle["valid"][0], dtype=bool)
        final_valid = np.asarray(handle["valid"][-1], dtype=bool)
        final_position = np.asarray(handle["position"][-1], dtype=float)
        final_velocity = np.asarray(handle["velocity"][-1], dtype=float)
        masses = np.asarray(handle["mass"][0], dtype=float)
        final_active = (
            initial_valid
            & final_valid
            & np.isfinite(final_position).all(axis=1)
            & np.isfinite(final_velocity).all(axis=1)
        )
        if int(np.unique(native_ids).size) != int(native_ids.size):
            raise ValueError("trajectory native ids are not unique")
        if not bool(np.all(final_valid[initial_valid])):
            raise ValueError("the completed DBC trajectory has a missing initial native id")
        final_speed = np.linalg.norm(final_velocity, axis=1)
        body = f2q.body_positions(
            final_position,
            f2q.cup_world_from_body(
                f2q.motion_angle(float(handle["time"][-1]), duration)
            ),
        )
        cup_mask = final_active & _inside(body, cup_low, cup_high)
        receiver_mask = final_active & _inside(final_position, receiver_low, receiver_high)
        tray_mask = final_active & _inside(final_position, tray_low, tray_high)
        classified = cup_mask | receiver_mask | tray_mask
        initial_mass = float(masses[initial_valid].sum())
        final_mass = float(masses[final_active].sum())
        high_speed = final_active & (final_speed > 0.4)
        high_speed_mass = float(masses[high_speed].sum())
        high_speed_position = final_position[high_speed]
        high_speed_velocity = final_velocity[high_speed]
        region_masks = {
            "cup": cup_mask,
            "receiver": receiver_mask,
            "tray": tray_mask,
            "outside_observer_union": final_active & ~classified,
        }
        final_regions = {}
        for name, mask in region_masks.items():
            values = final_speed[mask]
            final_regions[name] = {
                "particle_count": int(mask.sum()),
                "mass_fraction": float(masses[mask].sum() / max(initial_mass, 1e-30)),
                "speed_p95_m_s": float(np.quantile(values, 0.95)) if values.size else None,
                "count_speed_gt_0p4_m_s": int(np.sum(values > 0.4)) if values.size else 0,
            }
        final_metrics = {
            "time_s": float(handle["time"][-1]),
            "native_particle_count": int(initial_valid.sum()),
            "final_valid_particle_count": int(final_active.sum()),
            "initial_mass_kg": initial_mass,
            "final_mass_kg": final_mass,
            "mass_fraction": float(final_mass / max(initial_mass, 1e-30)),
            "speed_quantiles_m_s": {
                f"p{int(q * 100):02d}": float(np.quantile(final_speed[final_active], q))
                for q in (0.5, 0.9, 0.95, 0.97, 0.99, 1.0)
            },
            "region_summary": final_regions,
            "high_speed_tray_sheet": {
                "threshold_m_s": 0.4,
                "particle_count": int(high_speed.sum()),
                "mass_fraction": float(high_speed_mass / max(initial_mass, 1e-30)),
                "all_in_tray_observer_region": bool(np.all(tray_mask[high_speed])),
                "position_bounds_m": {
                    "low": high_speed_position.min(axis=0).tolist(),
                    "high": high_speed_position.max(axis=0).tolist(),
                },
                "velocity_mean_m_s": high_speed_velocity.mean(axis=0).tolist(),
                "velocity_std_m_s": high_speed_velocity.std(axis=0).tolist(),
                "z_quantiles_m": {
                    f"p{int(q * 100):02d}": float(np.quantile(high_speed_position[:, 2], q))
                    for q in (0.0, 0.5, 1.0)
                },
            },
        }

    return {
        "paths": {
            "prepared": _ref(prepared_path, lab_root, "completed 5 s DBC prepared input"),
            "trajectory": _ref(trajectory, lab_root, "read-only trajectory"),
            "result": _ref(result, lab_root, "solver result"),
            "audit": _ref(audit, lab_root, "hard audit"),
            "observations": _ref(observations_path, lab_root, "original p95/KE observations"),
            "root_completion": _ref(completion_path, lab_root, "root completion receipt"),
            "observer_v3": _ref(observer_path, lab_root, "read-only metadata/cup-contract re-audit"),
        },
        "execution": {
            "result_execution_status": (
                result_data.get("execution_status")
                or result_data.get("status")
                or completion.get("execution_status")
            ),
            "root_completion_status": completion.get("execution_status"),
            "requested_horizon_reached": bool(completion.get("event_window", {}).get("requested_horizon_reached")),
            "frames": int(completion.get("event_window", {}).get("frames", len(times))),
            "hard_integrity_pass": bool(completion.get("hard_integrity_pass")),
            "all_20_hard_checks_true": bool(
                completion.get("hard_integrity_pass")
                and all(bool(value) for value in completion.get("hard_checks", {}).values())
            ),
            "native_missing_count": 0 if completion.get("hard_checks", {}).get("no_missing_native_fluid_ids") else -1,
            "audit_hard_integrity_pass": bool(audit_data.get("hard_integrity_pass")),
            "solver_rerun_for_this_review": False,
        },
        "motion_and_settling": {
            "baseline_rotation_duration_s": duration,
            "motion_start_s": MOTION_START_S,
            "motion_complete_s": motion_complete_s,
            "last_time_s": float(times[-1]),
            "post_motion_window_s": float(times[-1] - motion_complete_s),
            "settled_thresholds_unchanged": {
                "speed_p95_m_s_max": SETTLE_SPEED_M_S,
                "kinetic_fraction_max": SETTLE_KE_FRACTION,
                "hold_s": SETTLE_HOLD_S,
                "post_observation_s": POST_SETTLE_OBSERVATION_S,
            },
            "post_motion_speed_p95_m_s": {
                "minimum": float(speed_p95[post_motion].min()),
                "maximum": float(speed_p95[post_motion].max()),
                "last": float(speed_p95[-1]),
            },
            "post_motion_kinetic_fraction": {
                "minimum": float(kinetic[post_motion].min()),
                "maximum": float(kinetic[post_motion].max()),
                "last": float(kinetic[-1]),
            },
            "threshold_frames": {
                "kinetic_only": int(np.sum(settle_energy)),
                "speed_only": int(np.sum(settle_speed)),
                "both": int(np.sum(settle_both)),
            },
            "longest_runs": {
                "kinetic_only": _longest_true_run(settle_energy, times),
                "speed_only": _longest_true_run(settle_speed, times),
                "both": _longest_true_run(settle_both, times),
            },
            "settled_event": None,
            "settled_failure_basis": (
                "kinetic energy enters and remains below 0.05 for a long tail, but speed p95 "
                "never reaches 0.10 m/s; therefore the unchanged conjunctive settled gate "
                "has no candidate frame and cannot satisfy the 0.20 s hold"
            ),
        },
        "terminal_observer_reference": {
            "v3_revised_event_times_s": observer_v3["revised_event_times_s"],
            "v3_revised_tail": observer_v3["revised_tail"],
            "physical_spill_verified": bool(
                observer_v3["outside_observer_threshold_semantics"]["physical_spill_verified"]
            ),
            "numeric_thresholds_changed": bool(
                observer_v3["contract_change"]["numeric_thresholds_changed"]
            ),
        },
        "terminal_frame": final_metrics,
        "interpretation": {
            "cause_classification": "dynamic residual transport over the retained tray, not native loss, runtime-domain escape, or a one-particle tail",
            "event_definition_assessment": {
                "speed_gate_is_active": True,
                "speed_gate_is_observer_artifact": False,
                "reason": "the final high-speed population is spatially coherent on the tray floor; low KE alone does not imply that the transported mass is settled",
                "threshold_change_supported": False,
            },
            "viscosity_and_drive_assessment": {
                "visco_value_held_fixed": 0.03,
                "viscosity_change_supported_by_this_product": False,
                "drive_residual_supported": True,
                "drive_basis": "the same cosine law leaves a broad positive-x tray sheet; duration is the only remaining preregistered continuous-motion axis",
            },
            "evidence": [
                "all 54720 native identities remain valid at 5.000003231 s",
                "all 20 hard geometry checks pass",
                "2698 particles (4.929%) exceed 0.4 m/s at the final frame and all are in the tray observer region",
                "the high-speed subset occupies the tray-floor band z=-0.1890..-0.1797 m and has positive mean x velocity",
                "the KE threshold is met for 129 post-motion frames, while speed p95 never meets 0.10 m/s",
            ],
            "not_supported": [
                "no claim that viscosity is the unique cause",
                "no claim that the observer's outside classification proves physical spill",
                "no justification for changing settled thresholds, deleting tray mass, or extending beyond 5 s",
            ],
        },
    }


def _candidate_card(lab_root: Path, dynamics: dict[str, Any]) -> dict[str, Any]:
    duration_card = (lab_root / DURATION_CARD_RELATIVE).resolve()
    duration_design = (lab_root / DURATION_DESIGN_RELATIVE).resolve()
    static_anchor = (lab_root / STATIC_ANCHOR_RELATIVE).resolve()
    static_prepared = (lab_root / STATIC_PREPARED_RELATIVE).resolve()
    static_preflight = (lab_root / STATIC_PREFLIGHT_RELATIVE).resolve()
    dbc_prepared = (lab_root / DBC_PREPARED_RELATIVE).resolve()
    extension_prepared = (lab_root / DBC_EXTENSION_PREPARED_RELATIVE).resolve()
    extension_job = (lab_root / DBC_EXTENSION_JOB_RELATIVE).resolve()
    solver = (lab_root / SOLVER_RELATIVE).resolve()
    decoder = (lab_root / DECODER_RELATIVE).resolve()
    code_paths = {
        "core_f2_qualification": lab_root / "scripts/core_f2_qualification.py",
        "duration_design": lab_root / "scripts/f2_dbc_duration_qualification_design.py",
        "observer_v3": lab_root / "scripts/f2_dbc_extension5s_observer_v3.py",
    }
    return {
        "schema": "core.f2.dbc_slow_duration.canary_proposal.v1",
        "created_at": _stamp(),
        "family": "F2",
        "candidate_id": "F2_dbc_slow_rotation_duration_q1p0_canary",
        "scope_id": "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_x_v1",
        "revision_id": "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_q1p0_v1",
        "status": "design_only_no_prepared_input_no_job",
        "qualification_only": True,
        "qualification_claim": "none; one development canary proposal only",
        "gpu_launch_by_subagent": False,
        "ledger_mutation": 0,
        "candidate_change": {
            "parameter_name": "rotation_duration_s",
            "q": 1.0,
            "baseline_value_s": BASE_DURATION_S,
            "candidate_value_s": CANDIDATE_DURATION_S,
            "registered_mapping": "rotation_duration_s = 0.50 + 0.70*q",
            "registered_range_s": [0.5, 1.2],
            "motion_law": "same cosine smoothstep and same -105 degree target; only duration changes",
            "motion_start_s": MOTION_START_S,
            "baseline_motion_complete_s": MOTION_START_S + BASE_DURATION_S,
            "candidate_motion_complete_s": MOTION_START_S + CANDIDATE_DURATION_S,
            "candidate_post_drive_window_s": REGISTERED_WINDOW_S - (MOTION_START_S + CANDIDATE_DURATION_S),
            "max_angular_rate_ratio_to_baseline": BASE_DURATION_S / CANDIDATE_DURATION_S,
            "max_angular_acceleration_ratio_to_baseline": (BASE_DURATION_S / CANDIDATE_DURATION_S) ** 2,
            "max_angular_rate_rad_s": 2.3988621808203305,
            "max_angular_acceleration_rad_s2": 6.280206503532949,
            "scaling_status": "kinematic hypothesis only; no solver result inferred",
        },
        "fixed_recipe": {
            "boundary_method": 1,
            "boundary": "native DBC Boundary=1",
            "cfl": 0.2,
            "dp_m": DP_M,
            "angle_degrees": ANGLE_DEGREES,
            "initial_condition": "passed full-cup v3 side-wet continuum and native lattice, unchanged",
            "cup": "same moving cup and body-frame hard audit",
            "receiver": "same world-fixed receiver and contact gate",
            "tray_floor": "same retained boxfill=bottom source plane z=-0.20 m",
            "catchment": "same four fixed side walls, top open, floor retained",
            "gravity_m_s2": -9.81,
            "viscosity_and_material": "unchanged ViscoTreatment=1/Visco=.03 as in the frozen F2 DBC XML; no material hypothesis added",
            "mass_policy": "native rho*dp^3; no mass rescaling or survivor renormalization",
        },
        "destination_accounting": {
            "receiver": "world-fixed receiver contact is valid only after native mass inside the one-dp-clear receiver reaches 1% of initial mass",
            "tray_and_catchment": "mass deposited on the retained tray floor or inside the four-wall catchment remains in the denominator and is not deleted",
            "spill_or_escape": "mass outside cup, receiver and tray observation volumes is reported at the unchanged 1% event threshold; observer classification is not used to erase mass",
            "identity_loss": "missing native identities are an independent hard failure even when destination mass appears retained",
            "settled": "the same speed-p95 and kinetic-energy conjunction is required after the prescribed motion; low KE alone is insufficient",
        },
        "event_window_and_gates": {
            "registered_window_s": REGISTERED_WINDOW_S,
            "maximum_extended_window_s": REGISTERED_WINDOW_S,
            "output_interval_s": 0.01,
            "observer_contract": {
                "numeric_gate_baseline": "F2_geometry_aware_observer_v1",
                "read_only_metadata_correction": "F2_geometry_aware_observer_v3_cup_metadata_and_outside_semantics",
                "future_canary_requirement": "freeze a versioned observer using the physical cup faces and the corrected initial side-wet classification before submission",
                "numeric_thresholds_changed": False,
                "hard_audit_changed": False,
                "physical_spill_claim_from_outside_classification": "none",
            },
            "post_settle_observation_s": POST_SETTLE_OBSERVATION_S,
            "settle_speed_p95_m_s_max": SETTLE_SPEED_M_S,
            "settle_kinetic_fraction_max": SETTLE_KE_FRACTION,
            "settle_hold_s": SETTLE_HOLD_S,
            "receiver_contact_fraction": 0.01,
            "spill_fraction": OUTSIDE_MASS_THRESHOLD,
            "hard_integrity": [
                "no_missing_native_fluid_ids",
                "no_nonfinite_active_values",
                "no_runtime_domain_endpoint_outside",
                "no cup/receiver/tray/catchment closed-face endpoint or saved-chord crossings",
            ],
            "event_window_complete_required": True,
            "right_censor_policy": "a required event missing at 5 s fails this canary; no further horizon extension",
            "threshold_change": False,
        },
        "why_this_is_a_distinct_candidate": {
            "mechanism_class": "prescribed continuous motion protocol / impulse reduction",
            "boundary_repair_retry": False,
            "cfl_retry": False,
            "domain_extension": False,
            "horizon_extension": False,
            "geometry_change": False,
            "initial_condition_change": False,
            "material_change": False,
            "evidence": "5 s DBC has hard integrity but broad tray-floor residual motion; slowing the same smooth drive reduces prescribed angular rate and acceleration without changing contact or catchment semantics",
            "quantitative_basis": dynamics["terminal_frame"]["high_speed_tray_sheet"],
        },
        "repair_budget_and_negative_evidence": {
            "legacy_open_tray_domain": "negative and withdrawn; finite-domain expansion is not reused",
            "mdbc_boundary_formulation": "mDBC canary and CFL=.10 mDBC canary are retained negative; no further mDBC/CFL retry",
            "dbc_boundary_formulation": "Boundary=1 hard-passed at 2.5 s and 5 s but failed settled event; this proposal keeps Boundary=1",
            "horizon": "the one registered 5 s extension is exhausted; no further extension",
            "remaining_axis": "the already registered rotation-duration axis, tested at q=1.0 before any matrix preparation",
            "budget_interpretation": "one canary under this new continuous-motion protocol; a failure remains in the denominator and does not authorize blind duration retries",
        },
        "canary_plan": {
            "single_case": {
                "case_id": "CORE_F2_dbc_slow_duration_q1p00000000_dp0p007500000000_canary",
                "q": 1.0,
                "rotation_duration_s": CANDIDATE_DURATION_S,
                "dp_m": DP_M,
                "time_max_s": REGISTERED_WINDOW_S,
                "stage": "repair_canary",
                "split": "qualification_only",
            },
            "fresh_preflight_required": [
                "write a new Definition XML and mvrotfile carrying 1.20 s duration",
                "decode the generated native state and verify zero normal/overlap issues where applicable",
                "verify initial fluid ID/position/velocity/density equivalence with the passed full-cup DBC input",
                "bind all solver, decoder, XML, motion, BI4/VTK and observer hashes before submission",
            ],
            "native_asset_reuse": "permitted only after a fresh byte/decode equivalence check; no prepared or job is created by this proposal",
            "matrix_rule": "do not materialize or launch any 15-cell duration matrix until this canary has hard integrity and event_window_complete true",
            "pass": "root may review a separately registered 15-cell duration range; this canary is never a matrix numerator",
            "fail": "retain the failed canary and all prior denominators; no threshold relaxation, no spill deletion, no automatic second duration trial",
        },
        "resource_estimate": {
            "basis": "completed 54720-particle DBC product and existing duration design; conservative reservation",
            "cpu_cores": 2,
            "ram_mib": 32768,
            "gpu_peak_mib": 12288,
            "timeout_seconds": 14400,
            "io_weight": 2,
            "trajectory_estimate_gib": 1.3,
            "solver_peak_measurement_available": False,
        },
        "provenance": {
            "static_anchor": {
                "integration": _ref(static_anchor, lab_root, "passed static full-cup anchor"),
                "prepared": _ref(static_prepared, lab_root, "passed static native input"),
                "preflight": _ref(static_preflight, lab_root, "passed static decoded preflight"),
            },
            "dbc_baseline": _ref(dbc_prepared, lab_root, "2.5 s DBC predecessor"),
            "dbc_extension": _ref(extension_prepared, lab_root, "completed 5 s DBC input"),
            "dbc_extension_job": _ref(extension_job, lab_root, "completed 5 s DBC job spec"),
            "duration_registration": _ref(duration_card, lab_root, "registered duration axis"),
            "duration_design": _ref(duration_design, lab_root, "registered 13+2 design-only matrix"),
            "analysis_code": _ref(Path(__file__).resolve(), lab_root, "read-only forensic/proposal generator"),
            "solver": _ref(solver, lab_root, "pinned solver; future job only"),
            "decoder": _ref(decoder, lab_root, "pinned native decoder; future preflight only"),
            "code_hashes": {
                name: _ref(path, lab_root, "future frozen source dependency")
                for name, path in code_paths.items()
            },
            "evidence_review": dynamics["paths"],
        },
        "execution_status": "proposal_only; no GenCase, no solver, no GPU submission, no ledger write",
    }


def _static_prerequisite_note(lab_root: Path) -> dict[str, Any]:
    static_card = (lab_root / STATIC_CARD_RELATIVE).resolve()
    anchor = (lab_root / STATIC_ANCHOR_RELATIVE).resolve()
    prepared = (lab_root / STATIC_PREPARED_RELATIVE).resolve()
    preflight = (lab_root / STATIC_PREFLIGHT_RELATIVE).resolve()
    return {
        "schema": "core.f2.static_volume_hold.prerequisite.v2",
        "created_at": _stamp(),
        "family": "F2",
        "status": "prerequisite_only_no_matrix",
        "qualification_claim": "none",
        "matrix_authorized": False,
        "matrix_materialized": False,
        "gpu_submit": False,
        "ledger_mutation": 0,
        "purpose": "the passed fixed full-cup anchor is a precondition for a moving-cup candidate; it is not the third family and cannot replace a receiver-transfer/continuous-motion study",
        "static_anchor": {
            "hard_integrity_pass": True,
            "event_window_complete": True,
            "window_s": 0.6,
            "native_fluid_particles": 54720,
            "max_speed_p95_m_s": 0.03666363262481136,
            "max_kinetic_over_initial_potential": 0.00019179944700252995,
            "minimum_cup_retention_mass_fraction": 1.0,
            "mass_rescaling": False,
        },
        "preserved_source_card": _ref(static_card, lab_root, "original static design card; bytes preserved"),
        "preserved_anchor_inputs": {
            "integration": _ref(anchor, lab_root, "static anchor receipt"),
            "prepared": _ref(prepared, lab_root, "static anchor prepared input"),
            "preflight": _ref(preflight, lab_root, "static anchor decoded preflight"),
        },
        "explicit_non_scope": [
            "do not generate the static card's 15 cells",
            "do not treat static hold as receiver-transfer or dynamic qualification",
            "do not inherit static success into the DBC duration canary or any matrix numerator",
        ],
        "next_use": "only as the initial-condition provenance for the F2 DBC slow-duration canary proposal",
        "execution_status": "metadata_only; no GenCase, no solver, no GPU submission",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--dynamics-output", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--static-prerequisite-output", type=Path, required=True)
    args = parser.parse_args()
    lab_root = args.lab_root.resolve()
    dynamics = _read_dynamics(lab_root)
    report = {
        "schema": "core.f2.dbc_duration.dynamics_forensics.v1",
        "created_at": _stamp(),
        "family": "F2",
        "scope_id": "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_formulation_x_v1",
        "revision_id": "F2_dbc_extension5s_dynamics_forensics_v1",
        "qualification_claim": "none; read-only dynamics diagnosis",
        "read_only": True,
        "solver_rerun": False,
        "gen_case_rerun": False,
        "ledger_written": False,
        "analysis": dynamics,
        "analysis_code": _ref(Path(__file__).resolve(), lab_root, "read-only forensic and proposal generator"),
    }
    _write_json(args.dynamics_output, report)
    _write_json(args.candidate_output, _candidate_card(lab_root, dynamics))
    _write_json(args.static_prerequisite_output, _static_prerequisite_note(lab_root))
    print(json.dumps({
        "dynamics_output": str(Path(args.dynamics_output).resolve()),
        "candidate_output": str(Path(args.candidate_output).resolve()),
        "static_prerequisite_output": str(Path(args.static_prerequisite_output).resolve()),
        "final_speed_p95_m_s": dynamics["motion_and_settling"]["post_motion_speed_p95_m_s"]["last"],
        "final_ke_fraction": dynamics["motion_and_settling"]["post_motion_kinetic_fraction"]["last"],
        "high_speed_tray_particles": dynamics["terminal_frame"]["high_speed_tray_sheet"]["particle_count"],
        "hard_integrity_pass": dynamics["execution"]["hard_integrity_pass"],
        "event_window_complete": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
