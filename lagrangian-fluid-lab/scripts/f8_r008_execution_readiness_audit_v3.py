#!/usr/bin/env python3
"""Corrected, provenance-bound F8 R008 pre-execution readiness audit.

This version distinguishes the R008 one-shot consumer from a legacy R001
consumer that reads the same parameter contract. It does not invoke native
tools, mutate the frozen scope, or grant qualification/execution authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from scripts import f8_r008_execution_readiness_audit_v2 as previous


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
PARAMETERS = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/parameter-contract-v1.json")
R008_AUTHORIZATION = ROOT / "cpu-native-preflight-authorization-v1/authorization.json"
R008_PREFLIGHT = ROOT / "cpu-native-preflight-v3/receipt.json"
R008_AUTHORIZATION_BUILDER = Path("scripts/f8_r008_cpu_native_preflight_authorization_v1.py")
R008_AUTHORIZATION_TEST = Path("tests/test_f8_r008_cpu_native_preflight_v1.py")
R008_SCOPE_BUILDER = Path("scripts/f8_t1_scope_design_v1.py")
R008_SCOPE_TEST = Path("tests/test_f8_t1_scope_design_v1.py")
R001_CONSUMER_BUILDER = Path("scripts/f8_cpu_native_preflight_authorization_v1.py")
R001_CONSUMER_OWNER = Path("scripts/f8_input_materialization_v1.py")
R001_CONSUMER_TEST = Path("tests/test_f8_cpu_native_preflight_authorization_v1.py")
V2_SCRIPT = Path("scripts/f8_r008_execution_readiness_audit_v2.py")
V2_TEST = Path("tests/test_f8_r008_execution_readiness_audit_v2.py")
V2_RECEIPT = ROOT / "t1-execution-readiness-audit-v2/receipt.json"
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_execution_readiness_audit_v3.py")
OUTPUT = LAB / ROOT / "t1-execution-readiness-audit-v3/receipt.json"
SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v3"


def binding(path: Path, role: str) -> dict[str, Any]:
    absolute = (LAB / path).resolve()
    payload = absolute.read_bytes()
    return {
        "path": str(absolute.relative_to(LAB)),
        "role": role,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads((LAB / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def build_audit() -> dict[str, Any]:
    value = previous.build_audit()
    parameters = _load(PARAMETERS)
    authorization = _load(R008_AUTHORIZATION)
    preflight = _load(R008_PREFLIGHT)
    r008_expected = int(authorization["hard_gates"]["native_fluid_particle_count_exact"])
    r008_actual = int(preflight["native_audit"]["native"]["fluid_particles"])
    if not (
        authorization.get("scope_id") == value["scope_id"]
        and r008_expected == r008_actual == value["retained_geometry"]["particle_count"]
        and value["retained_geometry"]["nominal_2H_over_dp_intervals"]
        == int(parameters["resolution_contract"]["expected_fluid_layers_across_2H"]["production"])
    ):
        raise ValueError("R008's own one-shot authorization/preflight no longer agrees on its native particle count")

    geometry = value["retained_geometry"]
    r001_expected = (
        int(parameters["resolution_contract"]["expected_periodic_counts"]["production_x"])
        * int(parameters["resolution_contract"]["expected_periodic_counts"]["production_y"])
        * int(parameters["resolution_contract"]["expected_fluid_layers_across_2H"]["production"])
    )
    geometry.pop("contract_expected_particle_count", None)
    geometry.pop("native_particle_count_matches_contract", None)
    geometry.update({
        "resolution_contract_layer_value": int(
            parameters["resolution_contract"]["expected_fluid_layers_across_2H"]["production"]
        ),
        "r008_preflight_expected_particle_count": r008_expected,
        "r008_particle_count_matches_native": r008_expected == r008_actual,
        "r001_legacy_computed_particle_count": r001_expected,
        "r001_legacy_consumer_scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
        "r001_legacy_consumer_is_r008_authority": False,
        "z_count_interpretation": "intervals_plausible_but_not_explicitly_frozen",
    })

    gaps = list(value["blocking_gaps"])
    old_geometry_gap = next(
        (gap for gap in gaps if gap["code"] == "production_particle_lattice_contract_conflict"),
        None,
    )
    if old_geometry_gap is None:
        raise ValueError("v2 geometry finding is missing; refusing to silently change audit basis")
    gaps[gaps.index(old_geometry_gap)] = {
        "code": "production_z_plane_interval_semantics_not_frozen",
        "detail": (
            f"R008's own authorization and retained native audit both expect {r008_expected} particles, "
            f"matching the observed {len(geometry['z_planes_m'])} z planes and {r008_actual} particles. "
            f"The frozen parameter field says {geometry['resolution_contract_layer_value']} fluid layers across 2H, "
            f"and 2H/dp={geometry['nominal_2H_over_dp_intervals']}; interpreting that value as spacing intervals "
            "would yield one additional endpoint plane and is consistent with R008's retained geometry, "
            f"but the parameter contract does not state that relation explicitly. A separate R001-only helper "
            f"computes {r001_expected} from the same field and is not an R008 authority. Freeze the intended "
            "interval/plane relation before using profile samples; do not attribute the R001 helper's count to R008."
        ),
    }

    evidence = list(value["evidence"])
    for item in evidence:
        if item["path"] == R001_CONSUMER_BUILDER.as_posix():
            item["role"] = "legacy R001-only particle-count consumer; not authoritative for R008"
    evidence.extend([
        binding(R008_AUTHORIZATION_BUILDER, "actual R008 one-shot CPU/native authorization consumer"),
        binding(R008_AUTHORIZATION_TEST, "R008 one-shot authorization and particle-count regression tests"),
        binding(R008_SCOPE_BUILDER, "R008 frozen 15-case qualification-scope builder"),
        binding(R008_SCOPE_TEST, "R008 qualification-scope and boundary regression tests"),
        binding(R001_CONSUMER_OWNER, "source proving the legacy count builder is rooted in R001"),
        binding(R001_CONSUMER_TEST, "legacy R001 authorization-builder regression tests"),
        binding(V2_SCRIPT, "superseded v2 audit builder; retained for correction lineage"),
        binding(V2_TEST, "superseded v2 audit tests; retained for correction lineage"),
        binding(V2_RECEIPT, "superseded v2 receipt with the over-attributed R001 consumer finding"),
        binding(SCRIPT, "corrected R008 execution-readiness audit v3 builder"),
        binding(TEST, "corrected R008 execution-readiness audit v3 regression tests"),
    ])

    value.update({
        "schema": SCHEMA,
        "record_id": "f8-r008-execution-readiness-audit-v3",
        "status": "blocked_preexecution_semantics_closure" if gaps else "static_execution_readiness_gaps_closed",
        "supersedes": {
            "path": V2_RECEIPT.as_posix(),
            "sha256": previous.sha256(LAB / V2_RECEIPT),
            "reason": (
                "v2 incorrectly attributed an R001-only legacy count consumer to R008; v3 binds and checks "
                "R008's own authorization/preflight chain and preserves the remaining interval/plane wording gap"
            ),
        },
        "retained_geometry": geometry,
        "blocking_gaps": gaps,
        "readiness_pass": not gaps,
        "evidence": evidence,
    })
    return value


def verify_audit(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_audit():
        raise ValueError("R008 execution-readiness audit v3 no longer matches retained evidence")
    return value


def write_audit(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 execution-readiness audit v3: {target}")
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
