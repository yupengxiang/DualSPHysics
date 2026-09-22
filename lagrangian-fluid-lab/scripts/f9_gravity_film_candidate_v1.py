#!/usr/bin/env python3
"""Build a static, fail-closed F9 free-surface T1 candidate card."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
PLAN = Path("/home/jade/.codex/attachments/ece07836-13f3-4e3a-9dd4-55120224dcee/PLAN.md")
OUTPUT = LAB / "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/candidate-card-v1.json"


SOURCE_ROLES = {
    str(PLAN): "attached Core plan; default free-surface boundary and completion gates",
    "vendor/official/DualSPHysics_v5.4/examples/inletoutlet/02_OpenChannel/CaseOpenChannel_Re100_Def.xml": "official free-surface open-channel and laminar-parameter precedent; inlet/outlet explicitly excluded from F9",
    "vendor/official/DualSPHysics_v5.4/examples/mdbc/02_Poiseuille/CasePoiseuille_FS_LR_Def.xml": "official mDBC, free-surface threshold, laminar-viscosity syntax precedent; solid upper wall not reused",
    "vendor/official/DualSPHysics_v5.4/examples/main/02_Periodicity/CasePeriodicity_Def.xml": "official periodic-boundary example",
    "vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML__Parameters.xml": "official periodic-offset, mDBC and free-surface parameter syntax",
    "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp": "official runtime parameter precedence for individual periodic offsets versus XYPeriodic",
    "campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v3.json": "closed F1/F2 lineages used for independence review",
    "campaigns/core-v1/evidence/f5-wave-runup-third-t1-route-closed-no-new-hypothesis-v1.json": "closed F5 lineage used for independence review",
    "campaigns/core-v1/cfd/f6-observation-axis-v4-third-t1-route-closed-v1.json": "closed F6 lineage used for independence review",
    "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/root-review-receipt-v2-20260922.json": "F7 no-go receipt used for independence review",
}


def path_for(name: str) -> Path:
    return Path(name) if name.startswith("/") else LAB / name


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind_sources() -> list[dict[str, Any]]:
    result = []
    for name, role in SOURCE_ROLES.items():
        path = path_for(name)
        if not path.is_file():
            raise FileNotFoundError(path)
        result.append({"path": name, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role})
    return result


def parse_xml(path: Path) -> str:
    ET.parse(path)
    return path.read_text(encoding="utf-8")


def build_card() -> dict[str, Any]:
    openchannel = path_for("vendor/official/DualSPHysics_v5.4/examples/inletoutlet/02_OpenChannel/CaseOpenChannel_Re100_Def.xml")
    poiseuille_fs = path_for("vendor/official/DualSPHysics_v5.4/examples/mdbc/02_Poiseuille/CasePoiseuille_FS_LR_Def.xml")
    periodic = path_for("vendor/official/DualSPHysics_v5.4/examples/main/02_Periodicity/CasePeriodicity_Def.xml")
    parameter_doc = path_for("vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML__Parameters.xml")
    periodic_source = path_for("vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp")
    openchannel_text = parse_xml(openchannel)
    poiseuille_text = parse_xml(poiseuille_fs)
    periodic_text = parse_xml(periodic)
    parameter_text = parameter_doc.read_text(encoding="utf-8")
    periodic_source_text = periodic_source.read_text(encoding="utf-8")
    plan_text = PLAN.read_text(encoding="utf-8")

    static_checks = {
        "official_xml_examples_parse": True,
        "openchannel_has_free_surface_candidate_geometry": "<drawbox>" in openchannel_text and "<inout>" in openchannel_text,
        "openchannel_has_laminar_and_free_surface_threshold": 'key="ViscoTreatment" value="2"' in openchannel_text and 'key="ShiftTFS"' in openchannel_text,
        "mdbc_example_has_mdbc_and_viscosity": 'key="Boundary" value="2"' in poiseuille_text and 'key="ViscoTreatment" value="2"' in poiseuille_text,
        "periodic_example_present": "XPeriodicIncZ" in periodic_text,
        "periodic_offset_documented": "XPeriodicIncZ" in parameter_text,
        "periodic_offset_runtime_precedence_visible": 'if(eparms.Exists("XPeriodicIncZ"))' in periodic_source_text and 'if(eparms.Exists("XYPeriodic"))' in periodic_source_text,
        "no_slip_mdbc_documented": "SlipMode" in parameter_text and "No-slip" in parameter_text,
        "plan_default_boundary_mentions_free_surface": "自由表面机制" in plan_text,
        "plan_three_family_gate": "至少三个真正不同家族" in plan_text,
    }
    if not all(static_checks.values()):
        raise AssertionError(static_checks)

    gravity = 9.81
    h = 0.03
    nu = 1.0e-3
    theta_min_deg = 3.0
    theta_max_deg = 9.0
    gs_min = gravity * math.sin(math.radians(theta_min_deg))
    gs_max = gravity * math.sin(math.radians(theta_max_deg))
    pi_min = gs_min * h**3 / nu**2
    pi_max = gs_max * h**3 / nu**2
    re_min = pi_min / 3.0
    re_max = pi_max / 3.0
    ubar_max = gs_max * h**2 / (3.0 * nu)
    usurface_max = 1.5 * ubar_max
    mach_max = usurface_max / 20.0
    assert pi_min > 10.0 and pi_max < 50.0
    assert re_max < 20.0
    assert mach_max < 0.04

    return {
        "schema": "core.cfd.f9.gravity_film_nusselt_candidate.v1",
        "status": "proposal_only_root_review_required",
        "scientific_status": "not_executed_not_admitted_zero_credit",
        "admission_granted": False,
        "qualification_credit": 0,
        "family": "F9",
        "scope_id": "F9_GRAVITY_FILM_NUSSELT_R001",
        "revision": "r001",
        "mechanism": {
            "name": "gravity-driven free-surface viscous film / Nusselt film",
            "description": "A fully developed single-phase Newtonian film on a fixed inclined plane: tangential gravity drives viscous shear, the bottom is no-slip, and the top is a real free surface with zero tangential stress.",
            "local_coordinates": "s=x*cos(theta)-z*sin(theta), n=x*sin(theta)+z*cos(theta), 0<=n<=h",
            "governing_1d_model": "du/dt = g_s + nu*d2u/dn2; u(0)=0; du/dn(h)=0",
            "steady_prediction": "u(n)=g_s/nu*(h*n-n^2/2), ubar=g_s*h^2/(3*nu), q_prime=g_s*h^3/(3*nu) [m^2/s per unit span], Q=Ly*q_prime",
            "transient_prediction": "u(n,t)=u_inf(n)-(2*g_s*h^2/nu)*sum_k[sin(mu_k*n/h)/mu_k^3*exp(-mu_k^2*nu*t/h^2)], mu_k=(k+1/2)*pi",
            "falsifiable_observables": [
                "full wall-normal velocity profile",
                "free-surface height and normal velocity",
                "volume flux",
                "hydrostatic normal pressure profile",
                "zero spanwise velocity",
                "resolution and time-step convergence",
            ],
        },
        "identity": {
            "parameter": "q in [0,1], theta_deg=3+6*q, Pi=g*sin(theta)*h^3/nu^2",
            "production_case_count": 32,
            "production_case_rule": "q_i=(i+0.5)/32, i=0..31",
            "split": {"train": 16, "validation": 4, "id_test": 6, "ood_test": 6},
            "anchor_case": "F9_GFN_q0p500_dp0p0075_anchor_r001",
            "planned_definition": "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/input/F9_GRAVITY_FILM_NUSSELT_R001_Def.xml",
            "planned_output_root": "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/cases",
        },
        "physical_contract": {
            "rho0_kg_m3": 1000.0,
            "gravity_global_m_s2": {"x": 0.0, "y": 0.0, "z": -gravity},
            "film_thickness_h_m": h,
            "kinematic_viscosity_m2_s": nu,
            "theta_range_deg": [theta_min_deg, theta_max_deg],
            "g_tangent_range_m_s2": [gs_min, gs_max],
            "Pi_range": [pi_min, pi_max],
            "Re_f_range": [re_min, re_max],
            "mean_speed_max_m_s": ubar_max,
            "free_surface_speed_max_m_s": usurface_max,
            "sound_speed_m_s": 20.0,
            "Mach_max": mach_max,
            "domain": {"streamwise_length_m": 0.24, "spanwise_length_m": 0.12, "boundary": "periodic streamwise/spanwise with streamwise normal offset; no inlet/outlet"},
            "coordinate_convention": {"bottom": "z_b(x)=-x*tan(theta)", "streamwise_unit": "(cos(theta),0,-sin(theta))", "normal_unit": "(sin(theta),0,cos(theta))", "gravity_projection": "g_s=g*sin(theta), g_n=g*cos(theta)"},
            "resolution_dp_m": {"coarse": 0.01, "production": 0.0075, "fine": 0.006},
            "surface_tension": False,
            "initial_state": "fluid at rest, film parallel to fixed inclined plane, no inherited velocity",
        },
        "static_contract": {
            "must_have": [
                "one fluid block and no top-wall particles",
                "fixed mDBC bottom with no-slip and a real free surface at n=h",
                "global gravity is (0,0,-g), with g_s and g_n obtained only by local projection",
            "periodic streamwise/spanwise boundaries using individual XPeriodicIncZ and YPeriodicIncZ parameters, never XYPeriodic, plus explicitly verified offset sign",
                "no inlet/outlet, pump, moving boundary, floating, Chrono, obstacle, material body, or surface tension",
                "particle identity, mass, finite-value, overlap, initial exclusion, and lifecycle checks",
                "parser for full velocity profile, free-surface height, pressure, flux, and exclusion statistics",
            ],
            "qualification_matrix": "13 physical/spatial cells plus 2 control cells; qualification-only until root admission",
            "hard_failure_policy": "fixed denominator, close scope, no threshold relaxation and no same-input retry",
        },
        "error_gates": {
            "reference_profile": "64 fixed midpoint samples n_j=(j+0.5)*h/64; particle velocities interpolated/averaged in local (s,n) coordinates",
            "reference_time_window": "tau=h^2/nu=0.9 s; discard [0,3*tau); average diagnostics over [3*tau,5*tau] at fixed TimeOut",
            "profile_l2_normalization": "L2 error divided by max(L2 analytic profile,1e-12)",
            "production_profile_relative_l2_max": 0.05,
            "production_flux_relative_max": 0.05,
            "flux_definition": "q_prime=integral_0^h u(n)dn [m^2/s per unit span]; Q=Ly*q_prime [m^3/s]",
            "fine_vs_production_profile_relative_max": 0.03,
            "fine_vs_production_flux_relative_max": 0.03,
            "surface_height_reference": "local normal coordinate n after subtracting theoretical plane n=h and time-window mean",
            "surface_height_rms_max_m": 0.5 * 0.0075,
            "surface_mean_height_bias_max_m": 0.25 * 0.0075,
            "pressure_reference": "p(n)=p_atm+rho*g_n_abs*(h-n), g_n_abs=g*cos(theta); gravity dot normal is -g_n_abs",
            "pressure_profile_relative_l2_max": 0.10,
            "surface_normal_velocity_over_uref_max": 0.05,
            "spanwise_velocity_rms_over_uref_max": 0.05,
            "mass_drift_relative_max": 0.001,
            "U_ref_definition": "U_ref=analytic free-surface speed=1.5*ubar; all velocity gates and Mach use case-specific U_ref",
            "solver_density_valid_interval_kg_m3": [900.0, 1100.0],
            "output_rows_expected": 501,
            "steady_window_and_denominator": "same theta, same physical window, same fixed sample count for fine/production comparisons",
            "excluded_fluid_particles": 0,
            "density_interval_kg_m3": [950.0, 1050.0],
            "hard_failure_policy": "fixed denominator, no threshold relaxation, no same-input retry",
        },
        "independence_review": {
            "distinct_from": {
                "F1_F2": "no dam-break release, obstacle, catchment, weir, or source-to-receiver transfer",
                "F3": "no enclosed-container sloshing or oscillatory free-surface memory",
                "F4": "no falling liquid mass, droplet, collision, or impact",
                "F5": "no wave maker, wave train, runup, shoreline, or breaking wave",
                "F6": "no floating body or fluid-rigid-body feedback",
                "F7": "no pump, moving boundary, rotation, torque, or angular-momentum observation",
            },
            "not_a_parameter_rename": "the falsifier is a different boundary-value problem with free-surface stress condition and Nusselt profile/flux law",
        },
        "blockers": [
            "periodic inclined free-surface geometry and streamwise normal-offset sign require target-specific native semantic verification",
            "the official OpenChannel example has inlet/outlet and cannot be reused as a qualification result",
            "no fresh F9 Definition, BI4, native preflight, solver, decoder, or qualification receipt exists",
            "formal root admission must explicitly accept F9 as the third Core family before any execution",
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
        "static_checks": static_checks,
        "evidence": bind_sources(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_card()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("schema", "status", "family", "qualification_credit", "execution_controls")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
