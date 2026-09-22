#!/usr/bin/env python3
"""Freeze the pre-admission physical and numerical contract for F8.

The contract is intentionally separate from the candidate card: it resolves
the acceleration-versus-pressure wording before any Definition is written.
It performs no native materialization and starts no simulation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json"
CANDIDATE = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json"
REVIEW = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/root-review/terra-high-root-review-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_contract() -> dict[str, Any]:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert candidate["scope_id"] == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
    assert candidate["admission_granted"] is False
    assert review["decision"] == "conditional_go_static_preparation_no_admission"

    rho0 = 1000.0
    nu = 5.0e-4
    half_height = 0.045
    length_x = 0.24
    length_y = 0.12
    acceleration_amplitude = 0.01
    sound_speed = 10.0
    tau = half_height**2 / nu
    alpha_min = 2.0
    alpha_max = 8.0
    omega_min = alpha_min**2 * nu / half_height**2
    omega_max = alpha_max**2 * nu / half_height**2
    u_ref_max = acceleration_amplitude / omega_min
    mach_max = u_ref_max / sound_speed
    reynolds_max = u_ref_max * half_height / nu

    assert math.isclose(tau, 4.05, rel_tol=0.0, abs_tol=1e-12)
    assert omega_min < omega_max
    assert mach_max < 0.01
    assert reynolds_max < 1.0

    return {
        "schema": "core.cfd.f8.parameter_contract.v1",
        "status": "pre_admission_static_contract_frozen",
        "scope_id": candidate["scope_id"],
        "revision": "r001",
        "admission_granted": False,
        "qualification_credit": 0,
        "semantic_name": "oscillatory body-force-driven viscous channel, Womersley-equivalent",
        "forcing_semantics": {
            "native_input": "accinput linear acceleration ax(t)=A*sin(omega*t) in m/s^2",
            "body_force_density": "f_x=rho*ax(t) in N/m^3",
            "pressure_equivalent_only_if_declared": "dp/dx=-rho*ax(t) for constant-density continuum interpretation",
            "pressure_driven_claim": "not admitted unless sign, units, reference frame, and pressure-gradient equivalence are explicitly verified",
            "gravity": [0.0, 0.0, 0.0],
            "globalgravity": 0,
        },
        "geometry_and_fluid": {
            "rho0_kg_m3": rho0,
            "kinematic_viscosity_m2_s": nu,
            "half_height_m": half_height,
            "length_x_m": length_x,
            "length_y_m": length_y,
            "fluid_domain": "0<=x<Lx, 0<=y<Ly, -H<=z<=H; fully filled single fluid",
            "boundary": "periodic x/y; fixed no-slip mDBC walls at z=+/-H",
            "no_components": ["free_surface", "floating", "Chrono", "moving_body", "pump", "torque", "material_body"],
        },
        "parameterization": {
            "q_rule": "q_i=(i+0.5)/32, i=0..31",
            "alpha_rule": "alpha=2+6*q",
            "omega_rule_rad_s": "omega=alpha^2*nu/H^2",
            "alpha_range": [alpha_min, alpha_max],
            "omega_range_rad_s": [omega_min, omega_max],
            "acceleration_amplitude_m_s2": acceleration_amplitude,
            "zero_mean_control": True,
        },
        "resolution_contract": {
            "coarse_dp_m": 0.009,
            "production_dp_m": 0.0075,
            "fine_dp_m": 0.006,
            "dp_only_changes_resolution": True,
            "expected_fluid_layers_across_2H": {"coarse": 10, "production": 12, "fine": 15},
            "expected_periodic_counts": {"production_x": 32, "production_y": 16},
        },
        "numerical_limits": {
            "sound_speed_m_s": sound_speed,
            "mach_max": mach_max,
            "density_interval_kg_m3": [950.0, 1050.0],
            "excluded_fluid_particles": 0,
            "particle_overlap": False,
            "wall_penetration_max_m": 0.25 * 0.0075,
            "tau_viscous_s": tau,
            "observation_start_rule": "max(2*tau, 2*period)",
            "observation_cycles": 3,
            "control_table_points_per_period": 64,
            "control_table": "finite monotonic time rows covering [0,t_end] with no extrapolation",
        },
        "error_gates": {
            "profile_amplitude_relative_max": 0.15,
            "profile_phase_absolute_max_rad": 0.15,
            "transverse_velocity_rms_over_uref_max": 0.05,
            "cycle_mean_flux_over_uref_area_max": 0.05,
            "fine_vs_production_amplitude_relative_max": 0.10,
            "fine_vs_production_phase_absolute_max_rad": 0.10,
            "time_step_control_phase_absolute_max_rad": 0.05,
            "hard_failure_policy": "fixed denominator, close scope, no threshold relaxation and no same-input retry",
        },
        "pre_admission_sequence": [
            "root decides whether non-free-surface F8 is in Core scope",
            "write a fresh hashed Definition and acceleration control file",
            "run target-specific static and native preflight only after authorization",
            "obtain bounded CPU anchor with decoder/parser/integrity receipts",
            "freeze and run 13+2 qualification",
            "only a successful qualification can authorize 32 production cases",
        ],
        "execution_controls": {
            "definition_written": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
        },
        "evidence": [
            {"path": "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json", "sha256": sha256(CANDIDATE)},
            {"path": "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/root-review/terra-high-root-review-v1.json", "sha256": sha256(REVIEW)},
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_contract()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("schema", "status", "scope_id", "admission_granted", "execution_controls")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
