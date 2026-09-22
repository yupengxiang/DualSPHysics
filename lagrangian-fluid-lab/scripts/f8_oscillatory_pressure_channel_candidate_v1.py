#!/usr/bin/env python3
"""Build a static, fail-closed proposal card for the F8 T1 candidate.

This script only inspects repository documents and official XML examples.  It
does not write a Definition, invoke GenCase, start a solver, or mutate the
Core registry and denominators.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
PLAN = Path("/home/jade/.codex/attachments/ece07836-13f3-4e3a-9dd4-55120224dcee/PLAN.md")
OUTPUT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json"


SOURCE_ROLES = {
    str(PLAN): "attached Core plan; target and boundary interpretation",
    "vendor/official/DualSPHysics_v5.4/examples/main/15_Poiseuille/CasePoiseuille_Def.xml": "official viscous channel geometry and laminar parameter precedent",
    "vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/CaseForces_Def.xml": "official accinput and time-file precedent",
    "vendor/official/DualSPHysics_v5.4/examples/main/02_Periodicity/CasePeriodicity_Def.xml": "official periodic-boundary example",
    "vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML_AccInput.xml": "official acceleration-input syntax",
    "vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML__Parameters.xml": "official periodic and mDBC parameter syntax",
}


def source_path(name: str) -> Path:
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
        path = source_path(name)
        if not path.is_file():
            raise FileNotFoundError(path)
        result.append({
            "path": name,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "role": role,
        })
    return result


def xml_text(path: Path) -> str:
    ET.parse(path)
    return path.read_text(encoding="utf-8")


def spec_text(path: Path) -> str:
    """Read an XML-format documentation fragment without claiming it parses."""
    return path.read_text(encoding="utf-8")


def build_card() -> dict[str, Any]:
    poisson = source_path("vendor/official/DualSPHysics_v5.4/examples/main/15_Poiseuille/CasePoiseuille_Def.xml")
    forces = source_path("vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/CaseForces_Def.xml")
    periodic = source_path("vendor/official/DualSPHysics_v5.4/examples/main/02_Periodicity/CasePeriodicity_Def.xml")
    acc_doc = source_path("vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML_AccInput.xml")
    parameter_doc = source_path("vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML__Parameters.xml")
    poisson_text = xml_text(poisson)
    forces_text = xml_text(forces)
    periodic_text = xml_text(periodic)
    acc_text = spec_text(acc_doc)
    parameter_text = spec_text(parameter_doc)
    plan_text = PLAN.read_text(encoding="utf-8")

    static_checks = {
        "official_xml_parses": True,
        "poiseuille_has_fluid_and_fixed_wall_geometry": "<setmkfluid" in poisson_text and "<boxfill>top|bottom</boxfill>" in poisson_text,
        "poiseuille_laminar_viscosity_precedent": 'key="ViscoTreatment" value="2"' in poisson_text,
        "external_forces_has_accinput_and_time_file": "<accinputs>" in forces_text and "<acctimesfile" in forces_text,
        "accinput_spec_supports_globalgravity_zero": 'globalgravity value="0"' in acc_text,
        "periodic_parameter_names_documented": all(token in parameter_text for token in ("XYPeriodic", "YZPeriodic", "SlipMode")),
        "periodic_example_present": "XPeriodicIncZ" in periodic_text,
        "plan_has_three_family_core_gate": "至少三个真正不同家族" in plan_text,
        "plan_has_free_surface_positioning": "三维自由表面流动" in plan_text,
    }
    if not all(static_checks.values()):
        raise AssertionError(static_checks)

    return {
        "schema": "core.cfd.f8_oscillatory_pressure_channel_candidate.v1",
        "status": "proposal_only_root_review_required",
        "scientific_status": "not_executed_not_admitted_zero_credit",
        "admission_granted": False,
        "qualification_credit": 0,
        "family": "F8",
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
        "revision": "r001",
        "mechanism": {
            "name": "oscillatory pressure-driven viscous channel",
            "description": "Fully filled single-phase viscous fluid in a channel periodic in x/y, with fixed no-slip walls at z=+/-H and uniform ax(t)=A sin(omega t).",
            "analytical_reference": "Womersley harmonic response of du/dt = ax(t) + nu*d2u/dz2",
            "falsifiable_observables": [
                "wall-normal velocity profile amplitude and phase",
                "centerline phase lag relative to acceleration",
                "near-zero transverse velocity",
                "near-zero cycle-mean flux for zero-mean forcing",
                "startup decay on the H^2/nu viscous diffusion scale",
                "pre-registered spatial and time-step convergence",
            ],
        },
        "identity": {
            "parameter": "q in [0,1], alpha = 2 + 6*q",
            "production_case_count": 32,
            "production_case_rule": "q_i=(i+0.5)/32, i=0..31",
            "split": {"train": 16, "validation": 4, "id_test": 6, "ood_test": 6},
            "anchor_case": "F8_OPC_q0p500_dp0p0075_anchor_r001",
            "planned_definition": "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001_Def.xml",
            "planned_control": "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/input/acceleration/F8_OPC_q0p500_acceleration.csv",
            "planned_output_root": "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/cases",
        },
        "static_contract": {
            "must_have": [
                "one mkfluid and gravity zero",
                "one fluid accinput with globalgravity zero and finite monotonic control table",
                "x/y periodicity and fixed no-slip z walls",
                "no floating, Chrono, moving body, pump, torque, or material body",
                "fixed geometry and control semantics across coarse/production/fine dp",
                "particle identity, mass, finite-value, overlap, wall-clearance, and lifecycle checks",
                "parser for time, center velocity, full wall-normal profile, and mean flux",
            ],
            "qualification_matrix": "13 physical/spatial cells plus 2 control cells; root review must freeze gates before any execution",
            "hard_failure_policy": "any hard-gate failure closes the scope with fixed denominator; no threshold relaxation or same-input retry",
        },
        "independence_review": {
            "distinct_from": {
                "F1_F2_F5": "no free-surface release, catchment, wave/runup, opening, transfer, or impact event",
                "F6": "no floating body, Chrono state, or fluid-rigid-body feedback",
                "F7": "no prescribed pump, moving boundary, rotation axis, torque, or angular-momentum output",
                "F3_F4": "no sloshing free surface, falling liquid mass, droplet, or collision event",
            },
            "boundary_interpretation": "PLAN foregrounds 3D free-surface flow but its explicit Core family gate says three genuinely different mechanisms; root must decide whether non-free-surface F8 is in Core scope before admission.",
        },
        "blockers": [
            "the official sources separately demonstrate viscous channel, accinput, and periodic syntax; their exact combined Definition has not been executed",
            "weakly-compressible SPH phase and density error gates are not yet calibrated",
            "the attached plan's free-surface emphasis requires explicit root interpretation",
            "no fresh Definition, BI4, native preflight, solver, decoder, or qualification receipt exists",
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
