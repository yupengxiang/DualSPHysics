#!/usr/bin/env python3
"""Build the non-executing F8 static review bundle.

This bundle is intentionally a gate before any Definition is materialized.
It freezes the proposed 13+2 matrix, parser semantics, and body-force naming
while leaving the Core-scope interpretation and all runtime actions to a new
root review.  No CFD trajectory is opened by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


LAB = Path(__file__).resolve().parents[1]
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
OUTPUT = LAB / (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
    "static-review-bundle-v1/bundle.json")
SCHEMA = "core.cfd.f8.static_review_bundle.v1"

INPUTS = {
    "candidate_card": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json"),
    "parameter_contract": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json"),
    "prior_root_review": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/root-review/terra-high-root-review-v1.json"),
    "oracle_contract": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/reference-oracle-v1/contract.json"),
    "oracle_implementation": Path("scripts/f8_womersley_oracle.py"),
    "oracle_test": Path("tests/test_f8_womersley_oracle.py"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": str(relative), "sha256": sha256(path),
            "bytes": path.stat().st_size, "role": role}


def _row(row_id: str, *, purpose: str, q: float, dp_m: float,
         time_step_policy: str = "baseline_registered_after_preflight",
         cadence_policy: str = "registered_0p02_s") -> dict[str, Any]:
    return {
        "row_id": row_id,
        "purpose": purpose,
        "q": q,
        "dp_m": dp_m,
        "time_step_policy": time_step_policy,
        "cadence_policy": cadence_policy,
        "qualification_only": True,
        "status": "planned_not_executed",
    }


def qualification_matrix() -> dict[str, Any]:
    rows = []
    row_number = 0
    for q in (0.0, 0.5, 1.0):
        for dp_m, label in ((0.009, "coarse"), (0.0075, "production"), (0.006, "fine")):
            rows.append(_row(
                f"F8-R{row_number:02d}", purpose=f"spatial_anchor_{label}",
                q=q, dp_m=dp_m))
            row_number += 1
    for q in (0.25, 0.75):
        for dp_m, label in ((0.0075, "production"), (0.006, "fine")):
            rows.append(_row(
                f"F8-R{row_number:02d}", purpose=f"independent_internal_{label}",
                q=q, dp_m=dp_m))
            row_number += 1
    rows.append(_row(
        f"F8-R{row_number:02d}", purpose="time_step_control", q=0.5,
        dp_m=0.0075, time_step_policy="tightened_half_baseline_after_preflight"))
    row_number += 1
    rows.append(_row(
        f"F8-R{row_number:02d}", purpose="native_cadence_control", q=0.5,
        dp_m=0.0075, cadence_policy="native_dense_0p002_s_vs_registered_0p02_s"))
    assert len(rows) == 15
    return {
        "schema": "core.cfd.f8.qualification_matrix.v1",
        "scope_id": SCOPE,
        "planned_row_count": 15,
        "physical_spatial_row_count": 13,
        "control_row_count": 2,
        "parameter_rule": "q_i=(i+0.5)/32 for production; qualification q points are fixed independently",
        "resolution_rule": {"coarse_dp_m": 0.009, "production_dp_m": 0.0075, "fine_dp_m": 0.006},
        "rows": rows,
        "denominator_policy": "all 15 rows retained; no partial credit, no survivor renormalization",
    }


def parser_contract() -> dict[str, Any]:
    return {
        "schema": "core.cfd.f8.observation_parser_contract.v1",
        "scope_id": SCOPE,
        "status": "contract_only_no_source_present",
        "required_arrays": {
            "time_s": {"shape": ["T"], "finite": True, "strictly_increasing": True},
            "center_velocity_mps": {"shape": ["T"], "finite": True},
            "profile_z_m": {"shape": ["Z"], "finite": True, "strictly_increasing": True},
            "profile_velocity_mps": {"shape": ["T", "Z"], "finite": True},
            "mean_flux_m3_s_per_m": {"shape": ["T"], "finite": True},
        },
        "phase_observable": {
            "method": "least_squares_sine_cosine_after_registered_observation_start",
            "future_reference_access": False,
            "time_shift_fitting": False,
            "observation_start_rule": "max(2*tau_viscous, 2*period)",
        },
        "profile_observable": "wall_normal_velocity_amplitude_and_phase_at_registered_z_samples",
        "flux_observable": "cross_sectional_integral_over_registered_z_grid",
        "missing_output_policy": "row_failure_fixed_denominator",
    }


def definition_semantics_contract() -> dict[str, Any]:
    return {
        "schema": "core.cfd.f8.definition_semantics_contract.v1",
        "scope_id": SCOPE,
        "status": "expected_semantics_only_definition_not_materialized",
        "required_semantics": {
            "one_mkfluid": True,
            "globalgravity": [0.0, 0.0, 0.0],
            "input_kind": "accinput_linear_acceleration",
            "input_units": "m/s^2",
            "forcing_name": "body-force-driven_oscillatory_channel",
            "pressure_equivalence": "dp/dx=-rho*ax(t), constant-density interpretation only",
            "periodic_axes": ["x", "y"],
            "fixed_no_slip_walls": ["z=-H", "z=+H"],
            "forbidden_components": ["free_surface", "moving_body", "Chrono", "pump", "torque"],
        },
        "naming_decision": {
            "pressure_driven_label_admitted": False,
            "body_force_driven_label_required": True,
            "root_scope_interpretation_required": True,
        },
        "materialization": {
            "definition_path": "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001_Def.xml",
            "control_path": "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/input/acceleration/F8_OPC_q0p500_acceleration.csv",
            "definition_written": False,
            "control_written": False,
            "authorized_by_bundle": False,
        },
    }


def build_bundle() -> dict[str, Any]:
    for relative in INPUTS.values():
        if not (LAB / relative).is_file():
            raise FileNotFoundError(LAB / relative)
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "static_review_bundle_pending_root_decision",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "scope_interpretation": {
            "decision": "pending_root_decision",
            "candidate_is_principally_independent": True,
            "free_surface_required_by_absolute_t1_gate": False,
            "plan_boundary_still_requires_root_interpretation": True,
        },
        "definition_semantics": definition_semantics_contract(),
        "qualification_matrix": qualification_matrix(),
        "parser_contract": parser_contract(),
        "transient_boundary": {
            "steady_oracle_supports_startup_decay": False,
            "startup_decay_scale_s": "H^2/nu",
            "startup_evidence_required": "fresh CFD transient or separately derived transient oracle",
            "steady_reference_must_not_be_used_as_startup_truth": True,
        },
        "execution_controls": {
            "definition_written": False,
            "control_written": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
        },
        "bindings": [binding(path, role) for role, path in INPUTS.items()],
    }


def validate_observation_payload(payload: dict[str, Any]) -> dict[str, int]:
    """Validate the future parser payload without interpreting CFD semantics."""
    required = ("time_s", "center_velocity_mps", "profile_z_m",
                "profile_velocity_mps", "mean_flux_m3_s_per_m")
    if not isinstance(payload, dict) or any(name not in payload for name in required):
        raise ValueError("F8 observation payload is missing required arrays")
    time = np.asarray(payload["time_s"], dtype=float)
    center = np.asarray(payload["center_velocity_mps"], dtype=float)
    z = np.asarray(payload["profile_z_m"], dtype=float)
    profile = np.asarray(payload["profile_velocity_mps"], dtype=float)
    flux = np.asarray(payload["mean_flux_m3_s_per_m"], dtype=float)
    if time.ndim != 1 or center.shape != time.shape or flux.shape != time.shape:
        raise ValueError("F8 time-series arrays must share shape [T]")
    if z.ndim != 1 or profile.shape != (len(time), len(z)):
        raise ValueError("F8 profile arrays must have shape [T,Z]")
    if len(time) < 2 or len(z) < 2 or not np.isfinite(
            np.concatenate((time, center, z, profile.ravel(), flux))).all():
        raise ValueError("F8 observation arrays must be finite and nonempty")
    if np.any(np.diff(time) <= 0) or np.any(np.diff(z) <= 0):
        raise ValueError("F8 time and profile grids must be strictly increasing")
    return {"time_count": int(len(time)), "profile_count": int(len(z))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = build_bundle()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("schema", "status", "qualification_credit", "execution_controls")},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
