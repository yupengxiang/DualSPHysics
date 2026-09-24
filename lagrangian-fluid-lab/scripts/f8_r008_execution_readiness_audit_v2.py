#!/usr/bin/env python3
"""Self-contained, read-only F8 R008 pre-execution semantics audit.

Reconciles the retained native anchor lattice with its frozen resolution
contract and checks operational definitions for the registered T1 metrics.
It does not invoke native tools or grant execution/qualification authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
SCOPE = ROOT / "t1-scope-design-v1/receipt.json"
PARAMETERS = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json")
PARSER_CONTRACT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/observation-parser-v1/contract.json")
PARSER = Path("scripts/f8_observation_parser_v1.py")
WINDOW_PARSER = Path("scripts/f8_observation_window_parser_v2.py")
PARTICLE_COUNT_CONSUMER = Path("scripts/f8_cpu_native_preflight_authorization_v1.py")
REFERENCE_CONTRACT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/reference-oracle-v2/contract.json")
REFERENCE_ORACLE = Path("scripts/f8_womersley_oracle.py")
STARTUP_ORACLE = Path("scripts/f8_womersley_oracle_v2.py")
PREFLIGHT = ROOT / "cpu-native-preflight-v3/receipt.json"
POSTRUN_AUDIT = ROOT / "cpu-native-postrun-audit-v1/receipt.json"
ANCHOR_DEFINITION = ROOT / "definition-control-pack-v1/qualification/space-q0p5-dp0p0075/F8_OPC_space-q0p5-dp0p0075_Def.xml"
FLUID_VTK = ROOT / "cpu-native-preflight-v3/generated/space-q0p5-dp0p0075_Fluid.vtk"
V1_SCRIPT = Path("scripts/f8_r008_execution_readiness_audit_v1.py")
V1_TEST = Path("tests/test_f8_r008_execution_readiness_audit_v1.py")
V1_RECEIPT = ROOT / "t1-execution-readiness-audit-v1/receipt.json"
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_execution_readiness_audit_v2.py")
OUTPUT = LAB / ROOT / "t1-execution-readiness-audit-v2/receipt.json"
SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v2"

METRIC_KEYS = {
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads((LAB / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve()
    payload = absolute.read_bytes()
    return {
        "path": str(absolute.relative_to(LAB)),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def vtk_binary_points(path: Path) -> list[tuple[float, float, float]]:
    """Read the legacy VTK binary POINTS section without project imports."""
    raw = Path(path).read_bytes()
    match = re.search(rb"(?m)^POINTS\s+(\d+)\s+(float|double)\s*$", raw)
    if not match:
        raise ValueError(f"VTK POINTS header missing: {path}")
    count = int(match.group(1))
    width = 4 if match.group(2) == b"float" else 8
    offset = raw.find(b"\n", match.start()) + 1
    size = count * 3 * width
    if count <= 0 or offset <= 0 or len(raw) < offset + size:
        raise ValueError(f"VTK POINTS payload is empty or truncated: {path}")
    values = struct.unpack(f">{count * 3}{'f' if width == 4 else 'd'}", raw[offset:offset + size])
    points = [tuple(values[index:index + 3]) for index in range(0, len(values), 3)]
    if not all(math.isfinite(coordinate) for point in points for coordinate in point):
        raise ValueError(f"VTK POINTS contains non-finite coordinates: {path}")
    return points


def contains_any_key(value: Any, keys: tuple[str, ...]) -> bool:
    if isinstance(value, dict):
        return any(key in value for key in keys) or any(
            contains_any_key(child, keys) for child in value.values()
        )
    if isinstance(value, list):
        return any(contains_any_key(child, keys) for child in value)
    return False


def build_audit() -> dict[str, Any]:
    scope = load_json(SCOPE)
    parameters = load_json(PARAMETERS)
    parser_contract = load_json(PARSER_CONTRACT)
    reference_contract = load_json(REFERENCE_CONTRACT)
    preflight = load_json(PREFLIGHT)
    postrun = load_json(POSTRUN_AUDIT)
    v1_receipt = load_json(V1_RECEIPT)
    if not (
        scope.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
        and scope.get("qualification_credit") == 0
        and preflight.get("status") == "cpu_native_preflight_passed_zero_credit"
        and preflight.get("qualification_credit") == 0
        and postrun.get("qualification_credit") == 0
        and postrun.get("execution_boundary", {}).get("solver_invoked") is False
        and v1_receipt.get("schema") == "core.cfd.f8.r008_execution_readiness_audit.v1"
    ):
        raise ValueError("R008 source records no longer identify the expected zero-credit state")

    points = vtk_binary_points(LAB / FLUID_VTK)
    x_planes = sorted({round(float(point[0]), 8) for point in points})
    y_planes = sorted({round(float(point[1]), 8) for point in points})
    z_planes = sorted({round(float(point[2]), 8) for point in points})
    root = ET.parse(LAB / ANCHOR_DEFINITION).getroot()
    dp = float(root.find("./casedef/geometry/definition").get("dp"))
    half_height = float(parameters["geometry_and_fluid"]["half_height_m"])
    nominal_intervals = round(2 * half_height / dp)
    expected_layers = int(parameters["resolution_contract"]["expected_fluid_layers_across_2H"]["production"])
    expected_xy = parameters["resolution_contract"]["expected_periodic_counts"]
    contract_expected_particles = (
        int(expected_xy["production_x"])
        * int(expected_xy["production_y"])
        * expected_layers
    )

    metric_sources = (scope, parameters, parser_contract, reference_contract)
    missing_metrics = [
        name for name, keys in METRIC_KEYS.items()
        if not any(contains_any_key(source, keys) for source in metric_sources)
    ]
    gaps: list[dict[str, str]] = []
    if len(z_planes) != expected_layers or len(points) != contract_expected_particles:
        gaps.append({
            "code": "production_particle_lattice_contract_conflict",
            "detail": (
                f"The frozen consumer treats {expected_layers} as the production z-plane count, implying "
                f"{contract_expected_particles} particles at {expected_xy['production_x']}x{expected_xy['production_y']} "
                f"periodic counts. Retained dp={dp:g} m native evidence instead has {len(z_planes)} z planes "
                f"and {len(points)} fluid particles; 2H/dp={nominal_intervals}. This is a count-contract "
                "conflict; do not silently relabel the expected layers as intervals."
            ),
        })
    for name in missing_metrics:
        if name == "flux_normalization":
            detail = (
                "The oracle defines unit-span cross-sectional flux integration and a zero-mean cycle oracle, "
                "but the R008 gate has no frozen normalization denominator or rule mapping CFD flux to its scalar."
            )
        else:
            detail = f"No operational {name.replace('_', ' ')} rule is present in the frozen scope/parameter/parser/reference contracts."
        gaps.append({
            "code": f"{name}_definition_not_frozen",
            "detail": detail,
        })

    observed_particles = len(points)
    expected_particles = int(postrun.get("verified_result", {}).get("fluid_particles", -1))
    if observed_particles != expected_particles:
        gaps.append({
            "code": "retained_vtk_particle_count_mismatch",
            "detail": f"Fluid.vtk has {observed_particles} points, post-run audit records {expected_particles}.",
        })
    if len(x_planes) != int(expected_xy["production_x"]) or len(y_planes) != int(expected_xy["production_y"]):
        gaps.append({
            "code": "production_xy_periodic_count_mismatch",
            "detail": f"Retained x/y counts {len(x_planes)}x{len(y_planes)} do not match frozen {expected_xy['production_x']}x{expected_xy['production_y']}.",
        })

    evidence = [
        binding(SCOPE, "frozen R008 T1 scope and metric gates"),
        binding(PARAMETERS, "frozen F8 physical and resolution contract"),
        binding(PARSER_CONTRACT, "F8 observation and harmonic-fit contract"),
        binding(PARSER, "F8 harmonic observation parser"),
        binding(WINDOW_PARSER, "R008 closed native observation-window selector"),
        binding(PARTICLE_COUNT_CONSUMER, "frozen expected-particle-count consumer for the F8 resolution contract"),
        binding(REFERENCE_CONTRACT, "F8 continuum reference contract"),
        binding(REFERENCE_ORACLE, "steady Womersley continuum oracle"),
        binding(STARTUP_ORACLE, "startup-transient Womersley continuum oracle"),
        binding(PREFLIGHT, "zero-credit R008 CPU/native receipt"),
        binding(POSTRUN_AUDIT, "read-only R008 postrun audit"),
        binding(ANCHOR_DEFINITION, "R008 production-resolution anchor Definition"),
        binding(FLUID_VTK, "retained R008 generated representative fluid points"),
        binding(V1_SCRIPT, "superseded audit v1 builder; recorded for history only"),
        binding(V1_TEST, "superseded audit v1 regression tests; recorded for history only"),
        binding(V1_RECEIPT, "superseded audit v1 receipt; recorded for history only"),
        binding(SCRIPT, "self-contained R008 readiness audit v2 builder"),
        binding(TEST, "R008 readiness audit v2 regression tests"),
    ]
    return {
        "schema": SCHEMA,
        "record_id": "f8-r008-execution-readiness-audit-v2",
        "scope_id": scope["scope_id"],
        "status": "blocked_preexecution_semantics_closure" if gaps else "static_execution_readiness_gaps_closed",
        "supersedes": {
            "path": (ROOT / "t1-execution-readiness-audit-v1/receipt.json").as_posix(),
            "sha256": sha256(LAB / V1_RECEIPT),
            "reason": "v1 used an imported legacy VTK decoder without binding its transitive project source; v2 parses the retained VTK locally and binds its full direct evidence set",
        },
        "qualification_claim": "none",
        "qualification_credit": 0,
        "execution_authority": {
            "solver": False, "gpu": False, "worker": False, "queue": False,
            "registry_mutation": 0, "ledger_mutation": 0, "denominator_mutation": 0,
        },
        "retained_geometry": {
            "case_id": "space-q0p5-dp0p0075",
            "particle_count": observed_particles,
            "x_plane_count": len(x_planes),
            "y_plane_count": len(y_planes),
            "z_plane_count": len(z_planes),
            "z_planes_m": z_planes,
            "dp_m": dp,
            "half_height_m": half_height,
            "nominal_2H_over_dp_intervals": nominal_intervals,
            "contract_expected_production_layers": expected_layers,
            "contract_expected_particle_count": contract_expected_particles,
            "native_particle_count_matches_contract": len(points) == contract_expected_particles,
            "xy_counts_match_contract": (
                len(x_planes) == int(expected_xy["production_x"])
                and len(y_planes) == int(expected_xy["production_y"])
            ),
            "z_count_interpretation": "contract_conflict" if len(z_planes) != expected_layers else "matches_contract",
        },
        "missing_metric_definitions": missing_metrics,
        "blocking_gaps": gaps,
        "readiness_pass": not gaps,
        "execution_controls": {
            "solver_invoked": False, "gpu_invoked": False, "worker_started": False,
            "queue_mutation": 0, "registry_mutation": 0,
            "ledger_mutation": 0, "denominator_mutation": 0,
        },
        "evidence": evidence,
    }


def verify_audit(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_audit():
        raise ValueError("R008 execution-readiness audit v2 no longer matches retained evidence")
    return value


def write_audit(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 execution-readiness audit v2: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(build_audit(), indent=2, sort_keys=True, allow_nan=False) + "\n")
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
