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
    openchannel_text = parse_xml(openchannel)
    poiseuille_text = parse_xml(poiseuille_fs)
    periodic_text = parse_xml(periodic)
    parameter_text = parameter_doc.read_text(encoding="utf-8")
    plan_text = PLAN.read_text(encoding="utf-8")

    static_checks = {
        "official_xml_examples_parse": True,
        "openchannel_has_free_surface_candidate_geometry": "<drawbox>" in openchannel_text and "<inout>" in openchannel_text,
        "openchannel_has_laminar_and_free_surface_threshold": 'key="ViscoTreatment" value="2"' in openchannel_text and 'key="ShiftTFS"' in openchannel_text,
        "mdbc_example_has_mdbc_and_viscosity": 'key="Boundary" value="2"' in poiseuille_text and 'key="ViscoTreatment" value="2"' in poiseuille_text,
        "periodic_example_present": "XPeriodicIncZ" in periodic_text,
        "periodic_offset_documented": "XPeriodicIncZ" in parameter_text,
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
    mach_max = ubar_max / 20.0
    assert pi_min > 10.0 and pi_max < 50.0
    assert re_max < 20.0
    assert mach_max < 0.03

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
            "governing_1d_model": "du/dt = g_s + nu*d2u/dn2; u(0)=0; du/dn(h)=0",
            "steady_prediction": "u(n)=g_s/nu*(h*n-n^2/2), ubar=g_s*h^2/(3*nu), q=g_s*h^3/(3*nu)",
            "transient_prediction": "startup decay on h^2/nu with half-integer Neumann/Dirichlet modes",
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
            "gravity_m_s2": gravity,
            "film_thickness_h_m": h,
            "kinematic_viscosity_m2_s": nu,
            "theta_range_deg": [theta_min_deg, theta_max_deg],
            "g_tangent_range_m_s2": [gs_min, gs_max],
            "Pi_range": [pi_min, pi_max],
            "Re_f_range": [re_min, re_max],
            "mean_speed_max_m_s": ubar_max,
            "sound_speed_m_s": 20.0,
            "Mach_max": mach_max,
            "domain": {"streamwise_length_m": 0.24, "spanwise_length_m": 0.12, "boundary": "periodic streamwise/spanwise with streamwise normal offset; no inlet/outlet"},
            "resolution_dp_m": {"coarse": 0.01, "production": 0.0075, "fine": 0.006},
            "surface_tension": False,
            "initial_state": "fluid at rest, film parallel to fixed inclined plane, no inherited velocity",
        },
        "static_contract": {
            "must_have": [
                "one fluid block and no top-wall particles",
                "fixed mDBC bottom with no-slip and a real free surface at n=h",
                "gravity decomposed into tangential and normal components",
                "periodic streamwise/spanwise boundaries and explicitly verified streamwise normal offset sign",
                "no inlet/outlet, pump, moving boundary, floating, Chrono, obstacle, material body, or surface tension",
                "particle identity, mass, finite-value, overlap, initial exclusion, and lifecycle checks",
                "parser for full velocity profile, free-surface height, pressure, flux, and exclusion statistics",
            ],
            "qualification_matrix": "13 physical/spatial cells plus 2 control cells; qualification-only until root admission",
            "hard_failure_policy": "fixed denominator, close scope, no threshold relaxation and no same-input retry",
        },
        "error_gates": {
            "production_profile_relative_l2_max": 0.05,
            "production_flux_relative_max": 0.05,
            "fine_vs_production_profile_relative_max": 0.03,
            "fine_vs_production_flux_relative_max": 0.03,
            "surface_height_rms_max_m": 0.5 * 0.0075,
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
