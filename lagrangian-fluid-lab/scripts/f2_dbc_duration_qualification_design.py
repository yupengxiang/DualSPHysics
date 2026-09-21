#!/usr/bin/env python3
"""Register the F2 native-DBC rotation-duration qualification design.

This module is deliberately a design and collection boundary.  It performs
CPU-only static mass checks and writes a 13+2 matrix registration.  It does
not call GenCase, create solver inputs, launch a worker, read a trajectory,
or write a campaign ledger.

The 2.5 s DBC run and its one-time 5 s extension are development canaries.
Even when the extension has a complete event window, its midpoint row stays
excluded from the 15-cell denominator; the qualification cells must be
executed independently.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

# Resolve code from this checkout.  ``--lab-root`` is an asset root only; it
# is never inserted ahead of this source tree, so a runtime snapshot cannot
# silently import changing helpers from a caller-supplied lab directory.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_qualification as f2q


SCHEMA = "core.f2.dbc_duration.qualification.v1"
COLLECTION_SCHEMA = "core.f2.dbc_duration.extension_collection.v1"
FAMILY = "F2"
SCOPE_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_duration_x_v1"
REVISION_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_duration_qualification_v1"
RECIPE_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_duration_qualification_v1"
OBSERVER_REVISION = "F2_geometry_aware_observer_v1"

DP_RESOLUTIONS = (0.01, 0.0075, 0.005)
SPATIAL_Q = (0.0, 0.5, 1.0)
HELD_OUT_Q = (0.25, 0.75)
Q_POINTS = (0.0, 0.25, 0.5, 0.75, 1.0)
DURATION_RANGE_S = (0.50, 1.20)
ANGLE_DEGREES = -105.0
MOTION_START_S = 0.50
REGISTERED_WINDOW_S = 5.0
MAXIMUM_EXTENDED_WINDOW_S = 5.0
OUTPUT_INTERVAL_S = 0.01
NATIVE_OUTPUT_INTERVAL_S = 0.002
BASE_CFL = 0.20

# The DBC canary's completed solver log records the actual controls selected
# when DtIni/DtMin were zero.  The internal-time row has an explicit half
# control based on that observed value.  Its gate is evaluated from actual
# solver steps and dt values, never from this configuration alone.
BASELINE_ACTUAL_DT_INI_S = 0.0002934903685409251
BASELINE_ACTUAL_DT_MIN_S = 0.00001467451864571362
INTERNAL_DT_INI_S = BASELINE_ACTUAL_DT_INI_S / 2.0
INTERNAL_DT_MIN_S = BASELINE_ACTUAL_DT_MIN_S / 2.0

BASE_PREPARED_RELATIVE = (
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2/prepared.json"
)
EXTENSION_PREPARED_RELATIVE = (
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2_extension5s_v2/prepared.json"
)
CANARY_JOB_RELATIVE = (
    "campaigns/core-v1/cfd/f2-dbc-boundary-ada-root-job-v1.json"
)
EXTENSION_JOB_RELATIVE = (
    "campaigns/core-v1/cfd/"
    "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-extension5s-v2-job.json"
)
CANARY_ATTEMPT_RELATIVE = (
    "campaigns/core-v1/runtime/attempts/ada-f2-dbc-boundary-canary-v1/"
    "20260920T030416-78fe3cfbab20/product"
)
EXTENSION_ATTEMPT_RELATIVE = (
    "campaigns/core-v1/runtime/attempts/"
    "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-extension5s-v2-001/"
    "20260920T031752-07b411be288d/product"
)
CANARY_RUN_OUT_RELATIVE = (
    "campaigns/core-v1/runtime/attempts/ada-f2-dbc-boundary-canary-v1/"
    "20260920T030416-78fe3cfbab20/product/solver/Run.out"
)
F1_REVIEW_RELATIVE = "campaigns/core-v1/cfd/f2-dbc-boundary-failure-f1-review-v1.json"


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _sha256(path: Path) -> str:
    return core_cfd.digest(Path(path))


def _duration_for_q(q: float) -> float:
    q = float(q)
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0, 1]")
    return DURATION_RANGE_S[0] + q * (DURATION_RANGE_S[1] - DURATION_RANGE_S[0])


def _event_window() -> dict[str, Any]:
    """Return the unchanged observer gates with one registered 5 s window."""
    value = copy.deepcopy(f2q.event_window(REGISTERED_WINDOW_S, MAXIMUM_EXTENDED_WINDOW_S))
    value["motion_source_file_duration_s"] = REGISTERED_WINDOW_S
    value["right_censor_policy"] = (
        "5 s is the registered qualification window; a right-censored required event "
        "fails the cell and no further extension is permitted"
    )
    value["development_canary_exclusion"] = (
        "the 2.5 s DBC canary and its one-time 5 s extension are evidence for launch "
        "readiness only and cannot populate a qualification cell"
    )
    return value


def _base_prepared(lab_root: Path) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    extension_path = (lab_root / EXTENSION_PREPARED_RELATIVE).resolve()
    base_path = (lab_root / BASE_PREPARED_RELATIVE).resolve()
    extension = json.loads(extension_path.read_text())
    base = json.loads(base_path.read_text())
    if not extension.get("preflight_pass") or not extension.get("qualification_only"):
        raise ValueError("the 5 s DBC extension is not CPU-preflighted qualification-only input")
    if extension.get("config", {}).get("boundary_method") != 1:
        raise ValueError("the extension is not native DBC Boundary=1")
    if extension.get("config", {}).get("time_max_s") != REGISTERED_WINDOW_S:
        raise ValueError("the extension horizon is not the registered 5 s window")
    if not base.get("preflight_pass") or not base.get("qualification_only"):
        raise ValueError("the 2.5 s DBC predecessor is not CPU-preflighted")
    return extension_path, extension, base_path, base


def _mass_check(config: dict[str, Any], dp_m: float) -> dict[str, Any]:
    boxes = [
        core_cfd.lattice_box(box["low"], box["size"], float(dp_m))
        for box in config["fluid_boxes"]
    ]
    quality = core_cfd.mass_quality({"fluid_boxes": boxes})
    return {
        "dp_m": float(dp_m),
        "continuous_box_m": {
            "low": copy.deepcopy(config["fluid_boxes"][0]["low"]),
            "size": copy.deepcopy(config["fluid_boxes"][0]["size"]),
        },
        "particle_counts_by_box": [int(item["particle_count"]) for item in boxes],
        "expected_fluid_particles": int(sum(item["particle_count"] for item in boxes)),
        "continuous_mass_kg": float(sum(item["continuous_mass_kg"] for item in boxes)),
        "discrete_mass_kg": float(sum(item["discrete_mass_kg"] for item in boxes)),
        "source_relative_errors": quality["source_relative_errors"],
        "total_relative_error": quality["total_relative_error"],
        "mass_rescaling": False,
        "mass_gate_pass": bool(quality["mass_gate_pass"]),
        "sampling_rule": "cell-centre lattice in the fixed continuous full-cup box; native rho*dp^3",
    }


def _resource_estimate(dp_m: float, output_interval_s: float) -> dict[str, Any]:
    """Conservative reservation, not a claim about measured solver use."""
    dp_m = float(dp_m)
    if dp_m <= 0.005 + 1e-12:
        return {
            "cpu_cores": 2,
            "ram_mib": 65536,
            "gpu_peak_mib": 24576,
            "timeout_seconds": 28800,
            "io_weight": 3,
            "trajectory_estimate_gib": 5.0 if output_interval_s <= 0.002 else 2.0,
        }
    return {
        "cpu_cores": 2,
        "ram_mib": 32768,
        "gpu_peak_mib": 12288,
        "timeout_seconds": 14400,
        "io_weight": 2 if output_interval_s <= 0.002 else 1,
        "trajectory_estimate_gib": 2.5 if output_interval_s <= 0.002 else 1.3,
    }


def _time_control(variant: str) -> dict[str, float]:
    if variant == "internal_time":
        return {
            "cflnumber": BASE_CFL,
            "DtIni": INTERNAL_DT_INI_S,
            "DtMin": INTERNAL_DT_MIN_S,
            "DtFixed": 0.0,
        }
    return {"cflnumber": BASE_CFL, "DtIni": 0.0, "DtMin": 0.0, "DtFixed": 0.0}


def _cell(
    base_config: dict[str, Any],
    q: float,
    dp_m: float,
    index: int,
    design_cell: str,
    temporal_variant: str | None = None,
) -> dict[str, Any]:
    q = float(q)
    dp_m = float(dp_m)
    duration_s = _duration_for_q(q)
    output_interval = NATIVE_OUTPUT_INTERVAL_S if temporal_variant == "native_output" else OUTPUT_INTERVAL_S
    controls = _time_control(temporal_variant or "base")
    mass = _mass_check(base_config, dp_m)
    case_id = (
        f"CORE_F2_dbc_duration_q{q:.8f}_dp{dp_m:.12f}_{design_cell}"
        + (f"_{temporal_variant}" if temporal_variant else "")
    ).replace(".", "p")
    return {
        "schema": "core.cfd.v1",
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "observer_revision": OBSERVER_REVISION,
        "case_id": case_id,
        "recipe_id": RECIPE_ID,
        "recipe": "native_dbc",
        "stage": "qualification",
        "qualification_only": True,
        "split": "qualification_only",
        "qualification_claim": "none",
        "status": "not_started; design-only registration",
        "parameter": {
            "name": "rotation_duration_s",
            "q": q,
            "value": duration_s,
            "candidate_range_s": list(DURATION_RANGE_S),
            "held_out": q in HELD_OUT_Q,
        },
        "dp_m": dp_m,
        "cfl": BASE_CFL,
        "time_control": controls,
        "time_max_s": REGISTERED_WINDOW_S,
        "maximum_extended_time_s": MAXIMUM_EXTENDED_WINDOW_S,
        "output_interval_s": output_interval,
        "angle_degrees": ANGLE_DEGREES,
        "motion_start_s": MOTION_START_S,
        "design_cell": design_cell,
        "temporal_variant": temporal_variant,
        "physical_geometry_changed": True,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "boundary_method": 1,
        "boundary_semantics": "native DBC Boundary=1; fixed within this matrix",
        "fixed_recipe_inherited_from_extension": True,
        "canary_reuse": {
            "allowed": False,
            "reason": "the 2.5 s DBC canary and 5 s extension are development evidence, not independent matrix executions",
        },
        "static_mass_check": mass,
        "resource_estimate": _resource_estimate(dp_m, output_interval),
        "source_label_semantics": "initial native Mk is a numerical source partition, not material identity",
    }


def _gates() -> dict[str, Any]:
    gates = copy.deepcopy(f2q.qualification_design()["preregistered_gates"])
    # Keep the source values explicit in the receipt and fail closed if the
    # shared evaluator changes unexpectedly.
    expected = {
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
    }
    if gates != expected:
        raise RuntimeError(f"shared F2 gate definition changed: {gates!r}")
    return gates


def _fixed_physical_case(config: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "cup", "receiver", "tray", "fluid_boxes", "catchment", "catchment_wall_spec",
        "runtime_domain", "wall_bounds", "initial_condition", "source_geometry_contract",
        "wall_audit_contract", "sampling_rule", "angle_degrees", "motion_start_s",
        "boundary_method", "control_semantics", "observer_revision",
    )
    return {key: copy.deepcopy(config[key]) for key in keys if key in config}


def build_design(lab_root: Path) -> dict[str, Any]:
    extension_path, extension, base_path, base = _base_prepared(lab_root)
    base_config = extension["config"]
    cells: list[dict[str, Any]] = []
    index = 0
    for q in SPATIAL_Q:
        for dp_m in DP_RESOLUTIONS:
            cells.append(_cell(base_config, q, dp_m, index, "spatial"))
            index += 1
    for q in HELD_OUT_Q:
        for dp_m in DP_RESOLUTIONS[1:]:
            cells.append(_cell(base_config, q, dp_m, index, "spatial_held_out"))
            index += 1
    cells.append(_cell(base_config, 0.5, 0.0075, index, "internal_time", "internal_time"))
    index += 1
    cells.append(_cell(base_config, 0.5, 0.0075, index, "native_output", "native_output"))

    if len(cells) != 15 or sum(row["design_cell"].startswith("spatial") for row in cells) != 13:
        raise AssertionError("F2 DBC design must contain 13 spatial and 2 temporal cells")
    if not all(row["static_mass_check"]["mass_gate_pass"] for row in cells):
        raise AssertionError("one or more DBC matrix rows fail static native mass gate")

    source_hashes = {
        "base_prepared": {"path": str(base_path), "sha256": _sha256(base_path)},
        "extension_prepared": {"path": str(extension_path), "sha256": _sha256(extension_path)},
    }
    canary_job = lab_root / CANARY_JOB_RELATIVE
    extension_job = lab_root / EXTENSION_JOB_RELATIVE
    run_out = lab_root / CANARY_RUN_OUT_RELATIVE
    for path in (canary_job, extension_job, run_out):
        if not path.is_file():
            raise FileNotFoundError(path)

    extension_config = extension["config"]
    return {
        "schema": SCHEMA,
        "revision_id": REVISION_ID,
        "created_at": _stamp(),
        "family": FAMILY,
        "scope_id": SCOPE_ID,
        "status": "candidate_registration_only",
        "qualification_claim": "none",
        "qualification_only": True,
        "physical_geometry_changed": True,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "recipe": "native_dbc",
        "parameter_axis": {
            "normalized_name": "q",
            "physical_name": "rotation_duration_s",
            "candidate_range_s": list(DURATION_RANGE_S),
            "mapping": "rotation_duration_s = 0.50 + 0.70*q",
            "candidate_q_points": list(Q_POINTS),
            "qualification_anchor_q": list(SPATIAL_Q),
            "held_out_q": list(HELD_OUT_Q),
            "semantic_rule": "q is a normalized coordinate; each execution carries the mapped physical duration",
        },
        "fixed_physical_case": _fixed_physical_case(extension_config),
        "fixed_recipe": {
            "boundary_method": 1,
            "boundary": "native DBC Boundary=1",
            "cflnumber": BASE_CFL,
            "dp_resolutions_m": list(DP_RESOLUTIONS),
            "angle_degrees": ANGLE_DEGREES,
            "motion_start_s": MOTION_START_S,
            "gravity_m_s2": -9.81,
            "geometry_contract": "full-cup side-wet initial continuum box, retained cup/receiver/tray floor, four fixed catchment walls, top open",
            "continuous_surface_contract": "catchment floor is the retained tray boxfill=bottom source plane z=-0.20 m; wall shell thickness is numerical only",
            "initial_mass_policy": "native rho*dp^3 with no mass rescaling",
        },
        "event_window": _event_window(),
        "observer": {
            "revision_id": OBSERVER_REVISION,
            "geometry": "moving cup body frame plus world receiver/tray/catchment; destination spill remains observable",
            "normalization": "fixed initial-native-mass denominator; no survivor renormalization",
            "calibration_required": True,
            "settled_gate_unchanged": True,
        },
        "preregistered_gates": _gates(),
        "cells": cells,
        "cell_count": len(cells),
        "spatial_cell_count": 13,
        "temporal_cell_count": 2,
        "held_out_q": list(HELD_OUT_Q),
        "replacement_q": [0.125, 0.375, 0.625, 0.875],
        "static_mass_status": {
            "all_15_rows_present": True,
            "all_mass_gates_pass": True,
            "mass_rescaling": False,
            "continuous_volume_m3": 0.023595,
            "native_count_is_resolution_dependent": True,
        },
        "time_control_provenance": {
            "baseline_run_out": {
                "path": str(run_out),
                "sha256": _sha256(run_out),
                "actual_dt_ini_s": BASELINE_ACTUAL_DT_INI_S,
                "actual_dt_min_s": BASELINE_ACTUAL_DT_MIN_S,
                "source": "completed 2.5 s DBC solver log; controls were zero in XML and solver selected these actual values",
            },
            "internal_time_row": {
                "requested_dt_ini_s": INTERNAL_DT_INI_S,
                "requested_dt_min_s": INTERNAL_DT_MIN_S,
                "ratio_to_baseline_requested": 0.5,
                "gate_basis": "actual dt and actual step counts from solver output; configuration values alone cannot pass",
            },
            "native_output_row": {
                "output_interval_s": NATIVE_OUTPUT_INTERVAL_S,
                "ratio_to_baseline": NATIVE_OUTPUT_INTERVAL_S / OUTPUT_INTERVAL_S,
            },
        },
        "development_canaries": {
            "two_point_five_second": {
                "job_id": "ada-f2-dbc-boundary-canary-v1",
                "prepared": source_hashes["base_prepared"],
                "attempt_product": str((lab_root / CANARY_ATTEMPT_RELATIVE).resolve()),
                "status": "development_only; hard integrity passed at 2.5 s, event window was incomplete",
                "independent_matrix_cell": False,
            },
            "five_second_extension": {
                "job_id": "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-extension5s-v2-001",
                "prepared": source_hashes["extension_prepared"],
                "job_spec": {"path": str(extension_job.resolve()), "sha256": _sha256(extension_job)},
                "attempt_product": str((lab_root / EXTENSION_ATTEMPT_RELATIVE).resolve()),
                "status_at_registration": "solver completed; core audit/collection pending",
                "independent_matrix_cell": False,
            },
            "reuse_rule": "neither development canary may populate cell 04 or any other matrix numerator",
        },
        "matrix_launch_gate": {
            "required_extension_checks": [
                "execution_succeeded",
                "requested_horizon_reached",
                "hard_integrity_pass",
                "event_window_complete",
                "settled_gate_observed_without_threshold_change",
            ],
            "if_any_false": "candidate_insufficient; retain design and all failure denominators; do not extend again",
            "if_all_true": "eligible_for_root_review and independent 15-cell preparation; still not qualified",
            "no_gpu_submission_in_this_artifact": True,
            "ledger_written": False,
        },
        "provenance": {
            "extension_snapshot": "93f49c0d7ad153c73685ba3695e5341c7fff025715aad7e4a8c1340e7c99a319",
            "source_prepared_sha256": source_hashes,
            "f1_fallback_review": {
                "path": str((lab_root / F1_REVIEW_RELATIVE).resolve()),
                "sha256": _sha256(lab_root / F1_REVIEW_RELATIVE),
                "use": "review only if the 5 s extension is incomplete or hard-fails; no blind further extension",
            },
            "code_source": {
                "core_f2_qualification": str((SOURCE_ROOT / "scripts/core_f2_qualification.py").resolve()),
                "core_f2_qualification_sha256": _sha256(SOURCE_ROOT / "scripts/core_f2_qualification.py"),
                "design_script": str(Path(__file__).resolve()),
                "design_script_sha256": _sha256(Path(__file__).resolve()),
            },
        },
        "execution_status": "design_only; no GenCase, no solver, no GPU submission",
        "qualification_claim": "none",
    }


def build_matrix(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "core.f2.dbc_duration.matrix.v1",
        "revision_id": design["revision_id"],
        "scope_id": design["scope_id"],
        "created_at": design["created_at"],
        "design_only": True,
        "qualification_claim": "none",
        "denominator": 15,
        "numerator_status": "0/15 executed; no canary reuse",
        "cells": [
            {
                "index": index,
                "case_id": cell["case_id"],
                "q": cell["parameter"]["q"],
                "rotation_duration_s": cell["parameter"]["value"],
                "dp_m": cell["dp_m"],
                "design_cell": cell["design_cell"],
                "temporal_variant": cell["temporal_variant"],
                "status": "not_started",
                "prepared": None,
                "job": None,
                "result": None,
                "canary_reuse": False,
            }
            for index, cell in enumerate(design["cells"])
        ],
        "required_observer_revision": OBSERVER_REVISION,
        "required_window_s": REGISTERED_WINDOW_S,
        "required_gates": copy.deepcopy(design["preregistered_gates"]),
        "all_rows_must_execute_independently": True,
        "execution_status": "not_submitted; wait for root launch gate",
        "ledger_written": False,
    }


def build_parameter_card(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "core.f2.dbc_duration.parameter_card.v1",
        "family": FAMILY,
        "scope_id": design["scope_id"],
        "revision_id": design["revision_id"],
        "status": "candidate_registration_only",
        "qualification_claim": "none",
        "parameter_axis": copy.deepcopy(design["parameter_axis"]),
        "fixed_recipe": copy.deepcopy(design["fixed_recipe"]),
        "event_window": copy.deepcopy(design["event_window"]),
        "preregistered_gates": copy.deepcopy(design["preregistered_gates"]),
        "independent_interior_policy": {
            "spatial": "q=.25 and .75 held-out rows are independent interior checks at dp=.0075 and .005",
            "temporal": "q=.5, dp=.0075 controls are comparator rows and do not replace spatial interiors",
            "canaries": "2.5 s and 5 s q=.5, dp=.0075 DBC canaries are excluded from all 15 rows",
        },
        "failure_policy": {
            "hard_or_event_failure": "retain the failed row and denominator; no threshold or ownership relaxation",
            "five_second_right_censor": "candidate insufficient; no additional horizon extension",
            "f1_fallback": "review the recorded F1 H1/H2 negative evidence before proposing any distinct mechanism",
        },
        "execution_status": "design_only; no GPU launch",
        "qualification_claim": "none",
    }


def build_collection_plan(lab_root: Path, design: dict[str, Any]) -> dict[str, Any]:
    extension_path = lab_root / EXTENSION_PREPARED_RELATIVE
    attempt_product = lab_root / EXTENSION_ATTEMPT_RELATIVE
    return {
        "schema": COLLECTION_SCHEMA,
        "revision_id": design["revision_id"],
        "scope_id": design["scope_id"],
        "created_at": _stamp(),
        "attempt_product": str(attempt_product.resolve()),
        "prepared": {
            "path": str(extension_path.resolve()),
            "sha256": _sha256(extension_path),
        },
        "safe_collection_contract": {
            "read_json_only": ["worker-status.json", "execution.json", "result.json", "audit.json", "observations.json"],
            "do_not_read": ["trajectory.h5", "trajectory.h5.partial"],
            "wait_until": [
                "worker-status.status is terminal",
                "trajectory.h5.partial is absent",
                "all four JSON outputs exist",
            ],
            "hash_every_collected_file": True,
        },
        "scientific_decision": {
            "matrix_eligibility": "hard_integrity_pass AND requested_horizon_reached AND event_window_complete AND execution_succeeded",
            "pass_meaning": "eligible for root review of independent matrix launch; never a qualification result",
            "fail_meaning": "candidate insufficient; preserve hard/event failure and do not extend again",
            "canary_denominator_rule": "the extension is excluded from the 15-cell numerator and denominator",
        },
        "f1_fallback_review": {
            "path": str((lab_root / F1_REVIEW_RELATIVE).resolve()),
            "sha256": _sha256(lab_root / F1_REVIEW_RELATIVE),
        },
        "execution_status": "collection plan only; no H5 read, no GPU submission, no ledger write",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--design-output", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path, required=True)
    parser.add_argument("--card-output", type=Path, required=True)
    parser.add_argument("--collection-output", type=Path, required=True)
    args = parser.parse_args()
    lab_root = args.lab_root.resolve()
    design = build_design(lab_root)
    _write_json(args.design_output, design)
    _write_json(args.matrix_output, build_matrix(design))
    _write_json(args.card_output, build_parameter_card(design))
    _write_json(args.collection_output, build_collection_plan(lab_root, design))
    print(json.dumps({
        "design": str(args.design_output.resolve()),
        "matrix": str(args.matrix_output.resolve()),
        "card": str(args.card_output.resolve()),
        "collection": str(args.collection_output.resolve()),
        "cell_count": len(design["cells"]),
        "all_mass_gates_pass": design["static_mass_status"]["all_mass_gates_pass"],
        "execution_status": design["execution_status"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
