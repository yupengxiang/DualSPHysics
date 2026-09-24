#!/usr/bin/env python3
"""Read-only F8 R008 audit for lattice and pre-execution metric closure.

This audit does not modify the frozen scope, authorize a solver, or grant
qualification credit.  It reconciles the one representative native geometry
already retained by the zero-credit CPU/native preflight with the frozen
resolution contract and checks whether the T1 metric reductions are
operationally specified before a solver matrix is run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from scripts.f8_r006_static_design_review_v1 import vtk_binary_points


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
SCOPE = ROOT / "t1-scope-design-v1/receipt.json"
PARAMETERS = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json")
PARSER_CONTRACT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/observation-parser-v1/contract.json")
PARSER = Path("scripts/f8_observation_parser_v1.py")
WINDOW_PARSER = Path("scripts/f8_observation_window_parser_v2.py")
REFERENCE_CONTRACT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/reference-oracle-v2/contract.json")
REFERENCE_ORACLE = Path("scripts/f8_womersley_oracle.py")
STARTUP_ORACLE = Path("scripts/f8_womersley_oracle_v2.py")
PREFLIGHT = ROOT / "cpu-native-preflight-v3/receipt.json"
POSTRUN_AUDIT = ROOT / "cpu-native-postrun-audit-v1/receipt.json"
ANCHOR_DEFINITION = ROOT / "definition-control-pack-v1/qualification/space-q0p5-dp0p0075/F8_OPC_space-q0p5-dp0p0075_Def.xml"
FLUID_VTK = ROOT / "cpu-native-preflight-v3/generated/space-q0p5-dp0p0075_Fluid.vtk"
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_execution_readiness_audit_v1.py")
OUTPUT = LAB / ROOT / "t1-execution-readiness-audit-v1/receipt.json"
SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v1"

_METRIC_KEYS = {
    "profile_sampling": (
        "profile_z_values_m", "profile_z_rule", "profile_sampling_rule",
        "registered_profile_samples_m",
    ),
    "reference_velocity": (
        "u_ref_m_s", "u_ref_formula", "reference_velocity_definition",
    ),
    "transverse_rms": (
        "transverse_velocity_rms_definition", "transverse_rms_formula",
    ),
    "flux_normalization": (
        "cycle_mean_flux_normalization", "flux_reference_definition",
    ),
    "cross_resolution_alignment": (
        "cross_resolution_z_alignment_rule", "profile_grid_comparison_rule",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads((LAB / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve()
    payload = absolute.read_bytes()
    return {
        "path": str(absolute.relative_to(LAB)),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _contains_key(value: Any, keys: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        return any(key in value for key in keys) or any(
            _contains_key(child, keys) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(child, keys) for child in value)
    return False


def build_audit() -> dict[str, Any]:
    scope = _json(SCOPE)
    parameters = _json(PARAMETERS)
    parser_contract = _json(PARSER_CONTRACT)
    reference_contract = _json(REFERENCE_CONTRACT)
    preflight = _json(PREFLIGHT)
    postrun = _json(POSTRUN_AUDIT)

    if not (
        scope.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
        and scope.get("qualification_credit") == 0
        and preflight.get("status") == "cpu_native_preflight_passed_zero_credit"
        and preflight.get("qualification_credit") == 0
        and postrun.get("qualification_credit") == 0
        and postrun.get("execution_boundary", {}).get("solver_invoked") is False
    ):
        raise ValueError("R008 source records no longer identify the frozen zero-credit preflight state")

    points = vtk_binary_points(LAB / FLUID_VTK)
    if not points:
        raise ValueError("R008 retained representative Fluid.vtk has no points")
    x_planes = sorted({round(float(point[0]), 8) for point in points})
    y_planes = sorted({round(float(point[1]), 8) for point in points})
    z_planes = sorted({round(float(point[2]), 8) for point in points})
    root = ET.parse(LAB / ANCHOR_DEFINITION).getroot()
    dp = float(root.find("./casedef/geometry/definition").get("dp"))
    geometry = parameters["geometry_and_fluid"]
    half_height = float(geometry["half_height_m"])
    nominal_intervals = round((2 * half_height) / dp)
    expected_layers = int(
        parameters["resolution_contract"]["expected_fluid_layers_across_2H"]["production"]
    )
    expected_xy = parameters["resolution_contract"]["expected_periodic_counts"]

    metric_sources = {
        "scope_design": scope,
        "parameter_contract": parameters,
        "observation_parser_contract": parser_contract,
        "reference_contract": reference_contract,
    }
    missing_metric_definitions = [
        name for name, keys in _METRIC_KEYS.items()
        if not any(_contains_key(source, keys) for source in metric_sources.values())
    ]

    geometry_ambiguity = len(z_planes) != expected_layers
    gaps: list[dict[str, str]] = []
    if geometry_ambiguity:
        gaps.append({
            "code": "production_z_plane_count_semantics_unresolved",
            "detail": (
                f"The frozen contract says {expected_layers} production fluid layers, while the retained "
                f"dp={dp:g} m native anchor has {len(z_planes)} distinct z particle planes. "
                f"2H/dp={nominal_intervals}; the records do not say whether the contract counts "
                "spacing intervals or particle planes. Do not reinterpret the count silently."
            ),
        })
    for name in missing_metric_definitions:
        gaps.append({
            "code": f"{name}_definition_not_frozen",
            "detail": f"No operational {name.replace('_', ' ')} rule is present in the R008 scope, parameter, or parser contract.",
        })

    # The preflight audit independently records the expected particle total;
    # this cross-check makes the VTK plane census traceable to its receipt.
    receipt_particles = int(
        postrun.get("verified_result", {}).get("fluid_particles", -1)
    )
    if len(points) != receipt_particles:
        gaps.append({
            "code": "retained_vtk_particle_count_mismatch",
            "detail": f"Fluid.vtk has {len(points)} points but post-run audit records {receipt_particles} fluid particles.",
        })
    if len(x_planes) != int(expected_xy["production_x"]):
        gaps.append({
            "code": "production_x_periodic_count_mismatch",
            "detail": f"Retained representative has {len(x_planes)} unique x planes; frozen contract expects {expected_xy['production_x']}.",
        })
    if len(y_planes) != int(expected_xy["production_y"]):
        gaps.append({
            "code": "production_y_periodic_count_mismatch",
            "detail": f"Retained representative has {len(y_planes)} unique y planes; frozen contract expects {expected_xy['production_y']}.",
        })

    bindings = [
        _binding(SCOPE, "frozen R008 T1 scope and metric gates"),
        _binding(PARAMETERS, "frozen F8 physical and resolution contract"),
        _binding(PARSER_CONTRACT, "F8 observation payload and fit contract"),
        _binding(PARSER, "F8 harmonic observation parser"),
        _binding(WINDOW_PARSER, "R008 closed native observation-window selector"),
        _binding(REFERENCE_CONTRACT, "F8 continuum reference contract"),
        _binding(REFERENCE_ORACLE, "steady Womersley continuum oracle"),
        _binding(STARTUP_ORACLE, "startup-transient Womersley continuum oracle"),
        _binding(PREFLIGHT, "zero-credit R008 CPU/native preflight receipt"),
        _binding(POSTRUN_AUDIT, "read-only R008 postrun audit"),
        _binding(ANCHOR_DEFINITION, "R008 production-resolution anchor Definition"),
        _binding(FLUID_VTK, "retained R008 generated representative fluid points"),
        _binding(SCRIPT, "read-only execution-readiness audit builder"),
        _binding(TEST, "execution-readiness audit regression tests"),
    ]
    return {
        "schema": SCHEMA,
        "record_id": "f8-r008-execution-readiness-audit-v1",
        "scope_id": scope["scope_id"],
        "status": "blocked_preexecution_semantics_closure" if gaps else "static_execution_readiness_gaps_closed",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "execution_authority": {
            "solver": False,
            "gpu": False,
            "worker": False,
            "queue": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "retained_geometry": {
            "case_id": "space-q0p5-dp0p0075",
            "particle_count": len(points),
            "x_plane_count": len(x_planes),
            "y_plane_count": len(y_planes),
            "z_plane_count": len(z_planes),
            "z_planes_m": z_planes,
            "dp_m": dp,
            "half_height_m": half_height,
            "nominal_2H_over_dp_intervals": nominal_intervals,
            "contract_expected_production_layers": expected_layers,
            "xy_counts_match_contract": (
                len(x_planes) == int(expected_xy["production_x"])
                and len(y_planes) == int(expected_xy["production_y"])
            ),
            "z_count_interpretation": "unresolved" if geometry_ambiguity else "matches_contract",
        },
        "missing_metric_definitions": missing_metric_definitions,
        "blocking_gaps": gaps,
        "readiness_pass": not gaps,
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "worker_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "evidence": bindings,
    }


def verify_audit(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_audit():
        raise ValueError("R008 execution-readiness audit no longer matches retained evidence")
    return value


def write_audit(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 execution-readiness audit: {target}")
    value = build_audit()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable audit receipt once")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_audit().relative_to(LAB))
    else:
        print(json.dumps(build_audit(), indent=2, sort_keys=True))
