#!/usr/bin/env python3
"""Freeze the F8 r002 design without materializing or executing it.

The closed r001 native-preflight evidence is immutable.  This module records a
new, hash-bound r002 design in a separate scope.  It renders the exact future
Definition and acceleration-table bytes only in memory to precommit their
hashes; it never creates either input, invokes a DualSPHysics binary, or
touches r001 evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
R001_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"
OUTPUT = LAB / ROOT / "static-design-review-v1/receipt.json"
SCHEMA = "core.cfd.f8.r002_static_design_review.v1"
DEFINITION_TARGET = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002_Def.xml"
CONTROL_TARGET = ROOT / "input/acceleration/F8_OPC_q0p500_r002_acceleration.csv"
PREFLIGHT_ROOT = ROOT / "cpu-native-preflight-v1"
GENERATED_PREFIX = PREFLIGHT_ROOT / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"
COPIED_CONTROL = PREFLIGHT_ROOT / "generated/acceleration/F8_OPC_q0p500_r002_acceleration.csv"

DECISION_PACKET = R001_ROOT / "r002-continuation-decision-v1/packet.json"
R001_AUDIT = R001_ROOT / "cpu-native-preflight-postrun-audit-v1/receipt.json"
OFFICIAL_PRECEDENTS = {
    "finite_wall_geometry": Path(
        "vendor/official/DualSPHysics_v5.4/examples/main/15_Poiseuille/"
        "CasePoiseuille_Def.xml"),
    "acceleration_input": Path(
        "vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/"
        "CaseForces_Def.xml"),
    "periodic_boundary": Path(
        "vendor/official/DualSPHysics_v5.4/examples/main/02_Periodicity/"
        "CasePeriodicity_Def.xml"),
    "acceleration_format": Path(
        "vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML_AccInput.xml"),
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {
        "path": str(relative), "sha256": sha256(path),
        "bytes": path.stat().st_size, "role": role,
    }


def parameters() -> dict[str, float | int]:
    """Return the r002 frozen physical/control parameters.

    r002 changes the wall construction and its namespaces, not the registered
    q=0.5 physical point.  Keeping this small explicit set independent from
    r001 avoids treating closed r001 inputs as r002 sources.
    """
    half_height = 0.045
    viscosity = 0.0005
    alpha = 5.0
    omega = alpha * alpha * viscosity / (half_height * half_height)
    period = 2.0 * math.pi / omega
    observation_start = max(2.0 * 4.05, 2.0 * period)
    warmup_cycles = math.ceil(observation_start / period)
    observation_cycles = 3
    points_per_period = 64
    total_cycles = warmup_cycles + observation_cycles
    return {
        "q": 0.5,
        "alpha": alpha,
        "omega": omega,
        "period": period,
        "observation_start": observation_start,
        "warmup_cycles": warmup_cycles,
        "observation_cycles": observation_cycles,
        "total_cycles": total_cycles,
        "points_per_period": points_per_period,
        "t_end": total_cycles * period,
        "amplitude": 0.01,
        "half_height": half_height,
        "length_x": 0.24,
        "length_y": 0.12,
        "rho0": 1000.0,
        "viscosity": viscosity,
        "dp": 0.0075,
        "sound_speed": 10.0,
    }


def definition_xml(values: dict[str, float | int]) -> str:
    """Render the proposed r002 Definition bytes in memory only.

    In contrast with r001, the boundary box has an explicit ``dp`` thickness
    outside each fluid plane and uses the Poiseuille precedent's ``dp | bound``
    shape mode.  This is a reviewable finite-volume construction, not a claim
    that GenCase has run it.
    """
    h, dp = float(values["half_height"]), float(values["dp"])
    outer_min, outer_size = -h - dp, 2.0 * (h + dp)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- Proposed F8 r002 static input. Not materialized or executable authority. -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="0" />
      <rhop0 value="{values['rho0']:.17g}" />
      <speedsound value="{values['sound_speed']:.17g}" auto="false" />
      <coefh value="1.0" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="1" fluidcount="1" />
    <geometry>
      <definition dp="{dp:.17g}">
        <pointref x="0" y="0" z="0" />
        <pointmin x="0" y="0" z="{outer_min:.17g}" />
        <pointmax x="{values['length_x']:.17g}" y="{values['length_y']:.17g}" z="{h + dp:.17g}" />
      </definition>
      <commands>
        <mainlist>
          <setshapemode>dp | bound</setshapemode>
          <setdrawmode mode="full" />
          <setmkbound mk="0" name="FiniteNoSlipZWalls" />
          <drawbox>
            <boxfill>top|bottom</boxfill>
            <point x="0" y="0" z="{outer_min:.17g}" />
            <size x="{values['length_x']:.17g}" y="{values['length_y']:.17g}" z="{outer_size:.17g}" />
          </drawbox>
          <setmkfluid mk="0" name="FullyFilledChannelFluid" />
          <drawbox>
            <boxfill>solid</boxfill>
            <point x="0" y="0" z="{-h:.17g}" />
            <size x="{values['length_x']:.17g}" y="{values['length_y']:.17g}" z="{2.0 * h:.17g}" />
          </drawbox>
        </mainlist>
      </commands>
    </geometry>
  </casedef>
  <execution>
    <special><accinputs><accinput mkfluid="0">
      <acccentre x="0" y="0" z="0" />
      <globalgravity value="0" />
      <acctimesfile value="acceleration/F8_OPC_q0p500_r002_acceleration.csv" />
    </accinput></accinputs></special>
    <parameters>
      <parameter key="Boundary" value="2" />
      <parameter key="ViscoTreatment" value="3" />
      <parameter key="Visco" value="{values['viscosity']:.17g}" />
      <parameter key="TimeMax" value="{values['t_end']:.17g}" />
      <parameter key="TimeOut" value="{float(values['period']) / int(values['points_per_period']):.17g}" />
      <parameter key="PartsOutMax" value="0" />
      <parameter key="RhopOutMin" value="950" />
      <parameter key="RhopOutMax" value="1050" />
      <parameter key="XYPeriodic" value="0" />
    </parameters>
  </execution>
</case>
'''


def acceleration_csv(values: dict[str, float | int]) -> str:
    points, total_cycles = int(values["points_per_period"]), int(values["total_cycles"])
    period, omega, amplitude = (float(values[key]) for key in ("period", "omega", "amplitude"))
    rows = ["#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"]
    for index in range(total_cycles * points + 1):
        time_s = period * index / points
        acceleration = amplitude * math.sin(omega * time_s)
        if index in (0, total_cycles * points):
            acceleration = 0.0
        rows.append(f"{time_s:.17g};{acceleration:.17g};0;0;0;0;0")
    return "\n".join(rows) + "\n"


def load_json(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def require(gaps: list[dict[str, str]], code: str, condition: bool, detail: str) -> None:
    if not condition:
        gaps.append({"code": code, "detail": detail})


def evaluate_design(values: dict[str, float | int]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    packet, audit = load_json(DECISION_PACKET), load_json(R001_AUDIT)
    require(gaps, "R002_USER_AUTHORIZATION", packet.get("schema") == "core.cfd.f8.r002_continuation_decision_packet.v1"
            and packet.get("status") == "awaiting_user_r002_continuation_ruling"
            and packet.get("proposed_new_scope") == SCOPE,
            "the immutable r002 continuation packet must nominate this exact new scope")
    require(gaps, "R001_RETAINED_CLOSED", audit.get("status") == "retained_hard_failure_no_retry_zero_credit"
            and audit.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
            and audit.get("failure_closure", {}).get("same_input_retry_forbidden") is True,
            "r001 must remain a closed hard failure with no same-input retry")
    require(gaps, "FRESH_NAMESPACES", ROOT != R001_ROOT and SCOPE != audit.get("scope_id")
            and not (LAB / DEFINITION_TARGET).exists() and not (LAB / CONTROL_TARGET).exists()
            and not (LAB / PREFLIGHT_ROOT).exists(),
            "r002 inputs and output namespace must be new and absent")
    for name, relative in OFFICIAL_PRECEDENTS.items():
        require(gaps, "OFFICIAL_PRECEDENT", (LAB / relative).is_file(),
                f"required precedent absent: {name}: {relative}")

    definition, control = definition_xml(values), acceleration_csv(values)
    require(gaps, "FINITE_Z_WALL_DESIGN", "<setshapemode>dp | bound</setshapemode>" in definition
            and "<boxfill>top|bottom</boxfill>" in definition
            and f'z="{-float(values["half_height"]) - float(values["dp"]):.17g}"' in definition
            and 'name="FiniteNoSlipZWalls"' in definition,
            "finite z walls must extend one dp beyond each fluid plane under dp | bound")
    require(gaps, "FLUID_WALL_SEPARATION", definition.index('name="FiniteNoSlipZWalls"')
            < definition.index('name="FullyFilledChannelFluid"')
            and f'z="{-float(values["half_height"]):.17g}"' in definition,
            "finite walls must be created before the separate fully-filled fluid box")
    require(gaps, "CONTROL_RELATIVE_PATH", 'value="acceleration/F8_OPC_q0p500_r002_acceleration.csv"' in definition
            and control.startswith("#Time;LinearAccX;")
            and "F8_OPC_q0p500_acceleration.csv" not in definition,
            "r002 Definition must bind only its new relative acceleration path")
    require(gaps, "CONTROL_COVERAGE", control.endswith(";0;0;0;0;0\n")
            and int(values["total_cycles"]) * int(values["points_per_period"]) + 1 == len(control.splitlines()) - 1,
            "precommitted control table must cover complete cycles with one endpoint row")
    return gaps


def build_review() -> dict[str, Any]:
    values = parameters()
    gaps = evaluate_design(values)
    definition = definition_xml(values).encode("utf-8")
    control = acceleration_csv(values).encode("utf-8")
    bindings = [
        binding(DECISION_PACKET, "immutable r002 continuation decision packet"),
        binding(R001_AUDIT, "immutable closed r001 hard-failure audit"),
        binding(Path("scripts/f8_r002_static_design_review_v1.py"), "r002 static design review builder"),
        binding(Path("tests/test_f8_r002_static_design_review_v1.py"), "r002 static design review tests"),
    ]
    for name, relative in OFFICIAL_PRECEDENTS.items():
        bindings.append(binding(relative, f"official syntax precedent: {name}"))
    passed = not gaps
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "r002_static_design_review_passed_inputs_not_authorized" if passed else "r002_static_design_review_failed",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "static_constraint_gaps": gaps,
        "r001_is_immutable_closed_history": {
            "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
            "same_input_retry_forbidden": True,
            "r001_evidence_mutated": False,
        },
        "r002_namespace": {
            "definition_target": str(DEFINITION_TARGET),
            "control_target": str(CONTROL_TARGET),
            "preflight_output_root": str(PREFLIGHT_ROOT),
            "generated_prefix": str(GENERATED_PREFIX),
            "generated_control_copy": str(COPIED_CONTROL),
            "all_targets_absent_at_review": True,
        },
        "precommitted_input_bytes": {
            "definition_sha256": sha256_bytes(definition),
            "definition_bytes": len(definition),
            "control_sha256": sha256_bytes(control),
            "control_bytes": len(control),
            "materialized": False,
            "future_writer_must_match_exactly": True,
        },
        "finite_wall_proof": {
            "shape_mode": "dp | bound",
            "wall_constructor": "drawbox boxfill=top|bottom",
            "wall_marker": "FiniteNoSlipZWalls",
            "fluid_marker": "FullyFilledChannelFluid",
            "fluid_z_interval_m": [-float(values["half_height"]), float(values["half_height"])],
            "lower_wall_z_interval_m": [-float(values["half_height"]) - float(values["dp"]), -float(values["half_height"])],
            "upper_wall_z_interval_m": [float(values["half_height"]), float(values["half_height"]) + float(values["dp"])],
            "claim": "static construction proof only; GenCase realization remains untested",
        },
        "control_dependency_copy_proof": {
            "definition_relative_reference": "acceleration/F8_OPC_q0p500_r002_acceleration.csv",
            "source_control": str(CONTROL_TARGET),
            "required_generated_copy": str(COPIED_CONTROL),
            "required_copy_hash": sha256_bytes(control),
            "r001_path_explicitly_forbidden": "acceleration/F8_OPC_q0p500_acceleration.csv",
        },
        "expected_cpu_preflight_hard_gates": [
            "separate immutable CPU-preflight authorization must name this r002 scope and exact two precommitted hashes",
            "GenCase may be invoked at most once only after that authorization; no r001 executable or output may be reused",
            "generated fixed boundary-particle count must be positive and contain both z-wall planes",
            "native decode must report positive boundary-particle and boundary-normal counts with finite nonzero normals",
            "the generated acceleration dependency must exist at required_generated_copy and hash-match required_copy_hash before native decode",
            "fluid particle count must be positive; zero excluded particles, zero solver/GPU/queue/registry/ledger mutations, and zero qualification credit remain required",
            "any failure closes r002 with no threshold relaxation or same-input retry",
        ],
        "next_authorization_required": {
            "kind": "one-time r002 static input materialization only",
            "required_before": "writing either precommitted input file",
            "does_not_authorize": ["GenCase", "native decoder", "solver", "GPU", "queue", "registry", "ledger", "qualification", "training"],
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
        "parameters": values,
        "bindings": bindings,
    }


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = path.resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r002 static review: {target}")
    review = build_review()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    review = write_review(args.output)
    print(json.dumps({key: review[key] for key in ("schema", "status", "qualification_credit", "static_constraint_gaps")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
