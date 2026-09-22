#!/usr/bin/env python3
"""Freeze and verify the F9 metric-parser semantics without opening CFD output.

This module is deliberately a static contract builder.  It does not invoke
GenCase, decode BI4, open HDF5, start a solver, or grant qualification credit.
The later runtime parser must bind its receipt to this contract before any F9
qualification result can be considered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001"
CARD = ROOT / "candidate-card-v1.json"
DEFINITION = ROOT / "input/F9_GRAVITY_FILM_NUSSELT_R001_Def.xml"
DEFINITION_CONTRACT = ROOT / "definition-contract-v2.json"
OUTPUT = ROOT / "metric-parser-contract-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value: float, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def build_contract() -> dict[str, Any]:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    definition_contract = json.loads(DEFINITION_CONTRACT.read_text(encoding="utf-8"))
    tree = ET.parse(DEFINITION)
    root = tree.getroot()
    parameters = {
        node.attrib["key"]: node.attrib["value"]
        for node in root.findall(".//parameter")
        if "key" in node.attrib and "value" in node.attrib
    }
    assert card["scope_id"] == "F9_GRAVITY_FILM_NUSSELT_R001"
    assert card["admission_granted"] is False
    assert definition_contract["schema"] == "core.cfd.f9.definition_contract.v2"
    assert definition_contract["admission_granted"] is False
    assert "XYPeriodic" not in parameters
    assert parameters["DtFixed"] == "0.00001"
    assert parameters["TimeOut"] == "0.01"
    assert parameters["TimeMax"] == "5.0"

    g = 9.81
    theta = math.radians(6.0)
    h = 0.03
    nu = 0.001
    rho0 = 1000.0
    ly = 0.12
    gs = g * math.sin(theta)
    gn = g * math.cos(theta)
    ubar = gs * h * h / (3.0 * nu)
    uref = 1.5 * ubar
    q_prime = gs * h**3 / (3.0 * nu)

    # The parser contract is explicit about the field convention.  Native
    # pressure must be declared as gauge pressure in every runtime receipt;
    # silently subtracting an unknown atmospheric offset is forbidden.
    contract = {
        "schema": "core.cfd.f9.metric_parser_contract.v1",
        "scope_id": card["scope_id"],
        "case_definition_revision": "r001",
        "contract_revision": "v1",
        "status": "static_parser_contract_bound_no_runtime_authorization",
        "admission_granted": False,
        "qualification_credit": 0,
        "execution_controls": {
            "hdf5_opened": False,
            "bi4_decoded": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "training_started": False,
        },
        "input_bindings": {
            "candidate_card": {"path": str(CARD.relative_to(LAB)), "sha256": sha256(CARD)},
            "definition": {"path": str(DEFINITION.relative_to(LAB)), "sha256": sha256(DEFINITION)},
            "definition_contract_v2": {
                "path": str(DEFINITION_CONTRACT.relative_to(LAB)),
                "sha256": sha256(DEFINITION_CONTRACT),
            },
        },
        "local_coordinates": {
            "origin": "bottom-plane origin at x=0,z=0 for the anchor cell",
            "streamwise_s": "x*cos(theta)-z*sin(theta)",
            "normal_n": "x*sin(theta)+z*cos(theta)",
            "spanwise_y": "global y",
            "fluid_interval": "0 <= n <= h",
            "velocity_projection": {
                "u_s_mps": "vx*cos(theta)-vz*sin(theta)",
                "u_n_mps": "vx*sin(theta)+vz*cos(theta)",
                "u_y_mps": "vy",
            },
            "periodic_images": "project each native particle once in the primary cell; never duplicate image particles in a denominator",
        },
        "field_conventions": {
            "pressure": {
                "native_field": "pressure",
                "required_receipt_flag": "pressure_is_gauge=true",
                "comparison_field": "gauge_pressure_pa",
                "atmospheric_offset": "p_atm is removed by the solver field contract; parser must reject an unknown offset",
                "reference": "rho0*g*cos(theta)*(h-n)",
                "reference_units": "Pa",
            },
            "mass_density_volume": "volume_weight_m3 = mass_kg / density_kg_m3",
            "valid_particle": "valid=true, finite position/velocity/pressure/mass/density, and 900 <= density <= 1100 kg/m^3",
            "excluded_particle_policy": "excluded particles remain in the fixed denominator and contribute to unknown mass; they are never renormalized away",
        },
        "profile_and_flux": {
            "normal_bins": 64,
            "bin_locations": "n_j=(j+0.5)*h/64 for j=0..63",
            "bin_assignment": "linear hat interpolation from each valid particle n to adjacent fixed midpoint bins",
            "weight": "mass_density_volume",
            "empty_bin": "hard failure; no interpolation from future frames or neighboring time windows",
            "profile": "weighted mean u_s at each fixed midpoint bin",
            "q_prime": "h/64 * sum_j profile_u_s[j]",
            "Q": "Ly*q_prime",
            "unknown_mass": "mass of invalid, excluded, or unsupported particles divided by total registered fluid mass",
            "reference_profile": "g*sin(theta)/nu*(h*n-n^2/2)",
            "profile_error": "L2(profile-reference)/max(L2(reference),1e-12)",
            "flux_error": "abs(q_prime-q_prime_reference)/max(abs(q_prime_reference),1e-12)",
        },
        "surface_height": {
            "grid": "32 uniform streamwise cells x 16 uniform spanwise cells in the primary periodic cell",
            "cell_estimator": "maximum valid local n in each cell after fixed density/finite gates",
            "missing_cell": "hard failure; no carry-forward, temporal interpolation, or survivor renormalization",
            "signed_bias": "mean(cell_n_max-h) over the fixed 512-cell denominator",
            "demeaned_rms": "sqrt(mean(((cell_n_max-mean(cell_n_max))-0)^2)) over the same fixed denominator",
            "normal_velocity": "mean absolute u_n at the selected surface particle per occupied cell, with missing cells failing",
            "surface_reference": "theoretical local plane n=h, not a fitted or time-shifted plane",
        },
        "time_window": {
            "tau_s": "h^2/nu",
            "discard": "0 <= t < 3*tau",
            "score": "3*tau <= t <= 5*tau",
            "frame_selection": "fixed TimeOut axis; right-censored or missing frames fail the case",
            "expected_output_rows": 501,
        },
        "denominators_and_gates": {
            "U_ref_mps": "1.5*ubar, case-specific analytic free-surface speed",
            "ubar_mps": ubar,
            "U_ref_value_mps": uref,
            "Mach_denominator": "sound_speed=20 m/s and U_ref, never a measured survivor maximum",
            "normal_velocity_denominator": "U_ref",
            "spanwise_rms_denominator": "U_ref",
            "profile_samples": 64,
            "surface_cells": 512,
            "mass_denominator": "registered initial fluid mass",
            "fixed_denominator": True,
            "no_survivor_renormalization": True,
        },
        "analytic_anchor_values": {
            "theta_deg": 6.0,
            "g_s_mps2": gs,
            "g_n_abs_mps2": gn,
            "h_m": h,
            "nu_m2ps": nu,
            "rho0_kgm3": rho0,
            "Ly_m": ly,
            "q_prime_m2ps": q_prime,
            "Q_m3ps": ly * q_prime,
            "ubar_mps": ubar,
            "U_ref_mps": uref,
        },
        "required_runtime_receipt_fields": [
            "pressure_is_gauge",
            "theta_deg",
            "MapRealSize_x_m",
            "expected_output_rows",
            "frames_scored",
            "unknown_mass_fraction",
            "profile_u_s",
            "profile_reference_u_s",
            "q_prime_m2ps",
            "surface_mean_height_bias_m",
            "surface_demeaned_rms_m",
            "surface_normal_velocity_over_U_ref",
            "spanwise_velocity_rms_over_U_ref",
            "failure_category",
        ],
        "static_self_check": {
            "definition_xml_parameters_match": True,
            "admission_remains_false": True,
            "runtime_map_width_still_requires_bi4_receipt": True,
            "parser_implementation_receipt_required_before_execution": True,
        },
    }
    return contract


def verify_contract(path: Path = OUTPUT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "core.cfd.f9.metric_parser_contract.v1":
        raise ValueError("metric parser schema mismatch")
    if payload.get("admission_granted") is not False or payload.get("qualification_credit") != 0:
        raise ValueError("metric parser contract cannot grant admission or credit")
    controls = payload.get("execution_controls", {})
    if any(value not in (False, 0) for value in controls.values()):
        raise ValueError("metric parser contract contains runtime execution")
    if payload["profile_and_flux"]["normal_bins"] != 64:
        raise ValueError("profile denominator is not frozen at 64")
    if payload["surface_height"]["grid"] != "32 uniform streamwise cells x 16 uniform spanwise cells in the primary periodic cell":
        raise ValueError("surface grid contract changed")
    if payload["field_conventions"]["pressure"]["required_receipt_flag"] != "pressure_is_gauge=true":
        raise ValueError("pressure convention is not explicit")
    for name in ("ubar_mps", "U_ref_mps", "q_prime_m2ps", "Q_m3ps"):
        _finite(payload["analytic_anchor_values"][name], name)
    bound = payload["input_bindings"]
    for key, expected in (("candidate_card", CARD), ("definition", DEFINITION), ("definition_contract_v2", DEFINITION_CONTRACT)):
        if bound[key]["sha256"] != sha256(expected):
            raise ValueError(f"input hash mismatch: {key}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write", "verify"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.command == "write":
        result = build_contract()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        result = verify_contract(args.output)
    print(json.dumps({key: result[key] for key in ("schema", "status", "admission_granted", "qualification_credit")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
