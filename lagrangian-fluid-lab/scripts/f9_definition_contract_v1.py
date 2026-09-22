#!/usr/bin/env python3
"""Freeze the F9 Definition semantics without materializing or executing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001"
CARD = ROOT / "candidate-card-v1.json"
OUTPUT = ROOT / "definition-contract-v1.json"
PERIODIC_SOURCE = LAB / "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp"
PARAMETER_DOC = LAB / "vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML__Parameters.xml"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_contract() -> dict[str, Any]:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    source = PERIODIC_SOURCE.read_text(encoding="utf-8")
    parameter_doc = PARAMETER_DOC.read_text(encoding="utf-8")
    assert card["scope_id"] == "F9_GRAVITY_FILM_NUSSELT_R001"
    assert card["admission_granted"] is False
    assert 'if(eparms.Exists("XPeriodicIncZ"))' in source
    assert 'if(eparms.Exists("XYPeriodic"))' in source
    assert "XPeriodicIncZ" in parameter_doc and "YPeriodicIncZ" in parameter_doc

    g = 9.81
    length_x = 0.24
    length_y = 0.12
    h = 0.03
    theta_anchor_deg = 6.0
    theta = math.radians(theta_anchor_deg)
    geometric_forward_offset_z = -length_x * math.tan(theta)
    periodic_parameter_offset_z = length_x * math.tan(theta)
    gravity = {"x": 0.0, "y": 0.0, "z": -g}
    free_surface_offset_z = h / math.cos(theta)
    assert geometric_forward_offset_z < 0.0
    assert periodic_parameter_offset_z > 0.0
    assert abs(periodic_parameter_offset_z) < length_x * 0.2
    assert math.isclose(sum(v * v for v in gravity.values()), g * g, rel_tol=0.0, abs_tol=1e-12)

    return {
        "schema": "core.cfd.f9.definition_contract.v1",
        "status": "static_definition_contract_only_no_runtime_authorization",
        "scope_id": card["scope_id"],
        "revision": "r001",
        "admission_granted": False,
        "qualification_credit": 0,
        "planned_definition": "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/input/F9_GRAVITY_FILM_NUSSELT_R001_Def.xml",
        "planned_output_root": "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/cases",
        "coordinate_convention": {
            "streamwise": "local s=x*cos(theta)-z*sin(theta)",
            "spanwise": "global y",
            "normal": "local n=x*sin(theta)+z*cos(theta), 0<=n<=h",
            "up": "global z",
            "bottom_plane": "z_b(x)=-x*tan(theta_anchor) over one periodic cell",
            "fluid_region": "z_b(x) <= z <= z_b(x)+h/cos(theta_anchor), with no top-wall particles",
            "free_surface": "upper geometric boundary of fluid only; no solid top wall",
        },
        "anchor_geometry": {
            "theta_deg": theta_anchor_deg,
            "length_x_m": length_x,
            "length_y_m": length_y,
            "film_normal_thickness_m": h,
            "geometric_forward_translation_m": [length_x, 0.0, geometric_forward_offset_z],
            "runtime_periodic_x_vector_m": [-length_x, 0.0, periodic_parameter_offset_z],
            "periodic_y_translation_m": [0.0, length_y, 0.0],
            "free_surface_vertical_offset_at_anchor_m": free_surface_offset_z,
        },
        "constantsdef_contract": {
            "gravity_m_s2": gravity,
            "gravity_projection": {"g_s_m_s2": g * math.sin(theta), "gravity_dot_normal_m_s2": -g * math.cos(theta), "g_n_abs_for_pressure_m_s2": g * math.cos(theta)},
            "rhop0_kg_m3": 1000.0,
            "kinematic_viscosity_m2_s": 0.001,
            "sound_speed_m_s": 20.0,
            "gamma": 7.0,
            "rhopgradient": 1,
            "density_diffusion": 0,
            "gravity_is_only_driving_input": True,
        },
        "geometry_contract": {
            "one_fluid_marker": True,
            "fixed_bottom_boundary": "mDBC no-slip bottom plane only",
            "top_boundary_particles": False,
            "inlet_outlet": False,
            "obstacle": False,
            "floating_chrono_pump_moving_body": False,
            "surface_tension": False,
            "allowed_geometry_operations": ["drawbeach or equivalent tilted bottom surface", "fluid fill bounded by bottom and free-surface height"],
            "must_reject": ["rectangular top wall", "fluid inlet/outlet zones", "XYPeriodic parameter when nonzero X offset is required"],
        },
        "execution_parameters_contract": {
            "Boundary": 2,
            "SlipMode": 2,
            "NoPenetration": 1,
            "ViscoTreatment": 3,
            "ViscoBoundFactor": 1,
            "Visco_m2_s": 0.001,
            "Kernel": 2,
            "StepAlgorithm": 2,
            "DtFixed_s": 0.00001,
            "TimeOut_s": 0.01,
            "TimeMax_s": 5.0,
            "expected_output_rows": 501,
            "ShiftTFS": 2.75,
            "XPeriodicIncZ": periodic_parameter_offset_z,
            "YPeriodicIncZ": 0.0,
            "XYPeriodic_parameter": "forbidden",
            "DtFixed": "1e-5 s",
            "TimeOut": "0.01 s",
            "TimeMax": "5.0 s",
        },
        "semantic_gates_before_any_runtime": [
            "XML parser accepts one fluid and bottom-only boundary geometry",
            "geometric x copies translate by (+Lx,0,-Lx*tan(theta)); runtime periodic duplicate vector is (-MapRealSize.x,0,+XPeriodicIncZ), with MapRealSize.x required to equal Lx",
            "y copies translate by (0,Ly,0)",
            "global gravity is (0,0,-g), and its local projections are g_s=g*sin(theta), gravity dot normal=-g*cos(theta)",
            "Nusselt q_prime is unit-span flux in m^2/s and total Q=Ly*q_prime in m^3/s",
            "pressure reference is p_atm+rho*g*cos(theta)*(h-n) in local n",
            "U_ref is analytic free-surface speed 1.5*ubar, and Mach uses U_ref/sound_speed",
            "NoPenetration=1, gamma=7, rhopgradient=1, density diffusion=0, DtFixed=1e-5 s, TimeOut=0.01 s and TimeMax=5 s are explicit",
            "profile samples, transient discard/window, norms, denominators, surface reference, pressure and velocity gates are frozen",
            "initial fluid particles occupy the film without top-wall particles, overlaps, or exclusions",
            "all q cases change only the pre-registered theta/geometry axis and dp resolution rules",
            "profile, free-surface, pressure, flux, mass, lifecycle, and exclusion parsers are available",
        ],
        "runtime_authorization": {
            "definition_write": False,
            "gencase": False,
            "native_preflight": False,
            "solver": False,
            "gpu": False,
            "queue": False,
            "registry": False,
            "ledger": False,
            "denominator": False,
        },
        "evidence": [
            {"path": "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001/candidate-card-v1.json", "sha256": sha256(CARD)},
            {"path": "vendor/official/DualSPHysics_v5.4/src/source/JSph.cpp", "sha256": sha256(PERIODIC_SOURCE)},
            {"path": "vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML__Parameters.xml", "sha256": sha256(PARAMETER_DOC)},
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_contract()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("schema", "status", "scope_id", "admission_granted", "runtime_authorization")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
