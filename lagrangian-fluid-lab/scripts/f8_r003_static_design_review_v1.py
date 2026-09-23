#!/usr/bin/env python3
"""Freeze an F8 r003 compatibility-corrected design without executing it.

The completed r001 and r002 CPU preflights are immutable, closed history.
This module produces only a new r003 static review.  It renders the future
Definition and acceleration table in memory to commit their exact bytes, but
does not materialize them or invoke GenCase, a decoder, solver, GPU, queue, or
worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
R001_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
R002_ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002")
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r003")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003"
OUTPUT = LAB / ROOT / "static-design-review-v1/receipt.json"
SCHEMA = "core.cfd.f8.r003_static_design_review.v1"
DEFINITION_TARGET = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003_Def.xml"
CONTROL_TARGET = ROOT / "input/acceleration/F8_OPC_q0p500_r003_acceleration.csv"
PREFLIGHT_ROOT = ROOT / "cpu-native-preflight-v1"
GENERATED_PREFIX = PREFLIGHT_ROOT / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003"
COPIED_CONTROL = PREFLIGHT_ROOT / "generated/acceleration/F8_OPC_q0p500_r003_acceleration.csv"

R001_AUDIT = R001_ROOT / "cpu-native-preflight-postrun-audit-v1/receipt.json"
R002_PREFLIGHT = R002_ROOT / "cpu-native-preflight-v1/receipt.json"
R002_LOG = R002_ROOT / "cpu-native-preflight-v1/gencase.stdout.log"
OFFICIAL_TEMPLATE = Path("vendor/official/DualSPHysics_v5.4/doc/xml_format/GenCase_CaseTemplate.xml")
OFFICIAL_POISEUILLE = Path("vendor/official/DualSPHysics_v5.4/examples/main/15_Poiseuille/CasePoiseuille_Def.xml")
OFFICIAL_FORCES = Path("vendor/official/DualSPHysics_v5.4/examples/main/04_ExternalForces/CaseForces_Def.xml")
OFFICIAL_ACCELERATION_FORMAT = Path("vendor/official/DualSPHysics_v5.4/doc/xml_format/_FmtXML_AccInput.xml")
OFFICIAL_PRECEDENTS = {
    "official_GenCase_case_template": OFFICIAL_TEMPLATE,
    "official_finite_wall_geometry": OFFICIAL_POISEUILLE,
    "official_acceleration_input": OFFICIAL_FORCES,
    "official_acceleration_format": OFFICIAL_ACCELERATION_FORMAT,
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": str(relative), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load_json(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def parameters() -> dict[str, float | int]:
    """Return the registered q=0.5 physics point, independently re-rendered."""
    half_height, viscosity, alpha = 0.045, 0.0005, 5.0
    omega = alpha * alpha * viscosity / (half_height * half_height)
    period = 2.0 * math.pi / omega
    observation_start = max(2.0 * 4.05, 2.0 * period)
    warmup_cycles, observation_cycles, points_per_period = math.ceil(observation_start / period), 3, 64
    return {
        "q": 0.5, "alpha": alpha, "omega": omega, "period": period,
        "observation_start": observation_start, "warmup_cycles": warmup_cycles,
        "observation_cycles": observation_cycles, "total_cycles": warmup_cycles + observation_cycles,
        "points_per_period": points_per_period, "t_end": (warmup_cycles + observation_cycles) * period,
        "amplitude": 0.01, "half_height": half_height, "length_x": 0.24,
        "length_y": 0.12, "rho0": 1000.0, "viscosity": viscosity,
        "dp": 0.0075, "sound_speed": 10.0,
    }


def definition_xml(values: dict[str, float | int]) -> str:
    """Render r003 only in memory with the official constantsdef compatibility set.

    r002's first parser error establishes ``hswl`` as a mandatory field for
    this native GenCase.  The remaining fields below are the relevant explicit
    thermodynamic/sound-speed fields from the official v5.4 template and its
    valid Poiseuille/ExternalForces definitions.  They avoid relying on hidden
    defaults while preserving r002's registered physical point and wall plan.
    """
    h, dp = float(values["half_height"]), float(values["dp"])
    outer_min, outer_size = -h - dp, 2.0 * (h + dp)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- Proposed F8 r003 static input.  Not materialized or executable authority. -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="0" />
      <rhop0 value="{values['rho0']:.17g}" />
      <rhopgradient value="1" />
      <hswl value="0" auto="true" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="1" />
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
      <commands><mainlist>
        <setshapemode>dp | bound</setshapemode>
        <setdrawmode mode="full" />
        <setmkbound mk="0" name="FiniteNoSlipZWalls" />
        <drawbox><boxfill>top|bottom</boxfill>
          <point x="0" y="0" z="{outer_min:.17g}" />
          <size x="{values['length_x']:.17g}" y="{values['length_y']:.17g}" z="{outer_size:.17g}" />
        </drawbox>
        <setmkfluid mk="0" name="FullyFilledChannelFluid" />
        <drawbox><boxfill>solid</boxfill>
          <point x="0" y="0" z="{-h:.17g}" />
          <size x="{values['length_x']:.17g}" y="{values['length_y']:.17g}" z="{2.0 * h:.17g}" />
        </drawbox>
      </mainlist></commands>
    </geometry>
  </casedef>
  <execution>
    <special><accinputs><accinput mkfluid="0">
      <acccentre x="0" y="0" z="0" />
      <globalgravity value="0" />
      <acctimesfile value="acceleration/F8_OPC_q0p500_r003_acceleration.csv" />
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
    points, cycles = int(values["points_per_period"]), int(values["total_cycles"])
    period, omega, amplitude = (float(values[key]) for key in ("period", "omega", "amplitude"))
    rows = ["#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"]
    for index in range(cycles * points + 1):
        time_s = period * index / points
        acceleration = 0.0 if index in (0, cycles * points) else amplitude * math.sin(omega * time_s)
        rows.append(f"{time_s:.17g};{acceleration:.17g};0;0;0;0;0")
    return "\n".join(rows) + "\n"


def require(gaps: list[dict[str, str]], code: str, condition: bool, detail: str) -> None:
    if not condition:
        gaps.append({"code": code, "detail": detail})


def evaluate_design(values: dict[str, float | int]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    r001, r002 = load_json(R001_AUDIT), load_json(R002_PREFLIGHT)
    require(gaps, "R001_RETAINED_CLOSED", r001.get("status") == "retained_hard_failure_no_retry_zero_credit"
            and r001.get("failure_closure", {}).get("same_input_retry_forbidden") is True,
            "r001 must remain immutable closed history")
    require(gaps, "R002_RETAINED_CLOSED", r002.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"
            and r002.get("status") == "cpu_gencase_or_control_copy_failed_hard_audit"
            and r002.get("execution_controls", {}).get("cpu_gencase_invoked") is True
            and r002.get("execution_controls", {}).get("native_decode_invoked") is False,
            "r002 must remain the one-shot GenCase failure, without a decode or retry")
    require(gaps, "R002_HSWL_FAILURE_EVIDENCE", "missing 'hswl'" in (LAB / R002_LOG).read_text(encoding="utf-8"),
            "official GenCase log must retain its missing-hswl parser failure")
    require(gaps, "FRESH_R003_NAMESPACES", ROOT not in (R001_ROOT, R002_ROOT)
            and SCOPE not in {"F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001", "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"}
            and not (LAB / DEFINITION_TARGET).exists() and not (LAB / CONTROL_TARGET).exists()
            and not (LAB / PREFLIGHT_ROOT).exists(),
            "r003 inputs and output must be new and absent; r002 output reuse is forbidden")
    for name, relative in OFFICIAL_PRECEDENTS.items():
        require(gaps, "OFFICIAL_PRECEDENT", (LAB / relative).is_file(), f"required precedent absent: {name}: {relative}")
    definition, control = definition_xml(values), acceleration_csv(values)
    root = ET.fromstring(definition)
    constants = {node.tag: dict(node.attrib) for node in root.findall("./casedef/constantsdef/*")}
    required_constants = {
        "gravity": {"x": "0", "y": "0", "z": "0"},
        "rhop0": {"value": "1000"}, "rhopgradient": {"value": "1"},
        "hswl": {"value": "0", "auto": "true"}, "gamma": {"value": "7"},
        "speedsystem": {"value": "0", "auto": "true"}, "coefsound": {"value": "1"},
        "speedsound": {"value": "10", "auto": "false"}, "coefh": {"value": "1.0"},
        "cflnumber": {"value": "0.2"},
    }
    require(gaps, "CONSTANTSDEF_COMPATIBILITY", all(
        all(constants.get(name, {}).get(key) == value for key, value in attrs.items())
        for name, attrs in required_constants.items()),
        "r003 must explicitly carry hswl and the reviewed official-template thermodynamic/sound-speed compatibility set")
    require(gaps, "FINITE_Z_WALL_DESIGN", "<setshapemode>dp | bound</setshapemode>" in definition
            and "<boxfill>top|bottom</boxfill>" in definition and 'name="FiniteNoSlipZWalls"' in definition
            and 'name="FullyFilledChannelFluid"' in definition,
            "finite z walls must use dp | bound before the separate fluid box")
    require(gaps, "CONTROL_RELATIVE_PATH_AND_COVERAGE", 'value="acceleration/F8_OPC_q0p500_r003_acceleration.csv"' in definition
            and "r002_acceleration.csv" not in definition and control.startswith("#Time;LinearAccX;")
            and control.endswith(";0;0;0;0;0\n")
            and len(control.splitlines()) - 1 == int(values["total_cycles"]) * int(values["points_per_period"]) + 1,
            "r003 must carry a new relative control path and a complete endpoint-closed table")
    return gaps


def build_review() -> dict[str, Any]:
    values, gaps = parameters(), []
    gaps = evaluate_design(values)
    definition, control = definition_xml(values).encode("utf-8"), acceleration_csv(values).encode("utf-8")
    bindings = [
        binding(R001_AUDIT, "immutable closed r001 hard-failure audit"),
        binding(R002_PREFLIGHT, "immutable closed r002 one-shot preflight receipt"),
        binding(R002_LOG, "official GenCase r002 missing-hswl error evidence"),
        binding(Path("scripts/f8_r003_static_design_review_v1.py"), "r003 static design review builder"),
        binding(Path("tests/test_f8_r003_static_design_review_v1.py"), "r003 static design review tests"),
    ] + [binding(path, f"official compatibility precedent: {name}") for name, path in OFFICIAL_PRECEDENTS.items()]
    return {
        "schema": SCHEMA, "scope_id": SCOPE,
        "status": "r003_static_design_review_passed_inputs_not_authorized" if not gaps else "r003_static_design_review_failed",
        "qualification_claim": "none", "qualification_credit": 0, "static_constraint_gaps": gaps,
        "closed_prior_scopes": [
            {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001", "same_input_retry_forbidden": True},
            {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002", "same_input_retry_forbidden": True,
             "failure": "GenCase XML constantsdef missing hswl", "r002_output_reuse_forbidden": True},
        ],
        "r003_namespace": {"definition_target": str(DEFINITION_TARGET), "control_target": str(CONTROL_TARGET),
                            "preflight_output_root": str(PREFLIGHT_ROOT), "generated_prefix": str(GENERATED_PREFIX),
                            "generated_control_copy": str(COPIED_CONTROL), "all_targets_absent_at_review": True},
        "precommitted_input_bytes": {"definition_sha256": sha256_bytes(definition), "definition_bytes": len(definition),
                                      "control_sha256": sha256_bytes(control), "control_bytes": len(control),
                                      "materialized": False, "future_writer_must_match_exactly": True},
        "constantsdef_compatibility_contract": {
            "observed_r002_hard_requirement": "hswl value=0 auto=true",
            "official_template_fields_explicitly_frozen": ["gravity", "rhop0", "rhopgradient", "hswl", "gamma", "speedsystem", "coefsound", "speedsound", "coefh", "cflnumber"],
            "rhopgradient_rationale": "1 selects uniform reference density for the fully filled no-free-surface initial state",
            "sound_speed_rationale": "speedsound is explicitly fixed at 10 with auto=false; its supporting template fields are explicit rather than defaulted",
            "static_proof_only": True,
        },
        "finite_wall_proof": {"shape_mode": "dp | bound", "wall_constructor": "drawbox boxfill=top|bottom",
                               "wall_marker": "FiniteNoSlipZWalls", "fluid_marker": "FullyFilledChannelFluid",
                               "fluid_z_interval_m": [-0.045, 0.045], "lower_wall_z_interval_m": [-0.0525, -0.045],
                               "upper_wall_z_interval_m": [0.045, 0.0525], "claim": "static construction proof only; GenCase realization remains untested"},
        "control_dependency_copy_proof": {"definition_relative_reference": "acceleration/F8_OPC_q0p500_r003_acceleration.csv",
                                            "source_control": str(CONTROL_TARGET), "required_generated_copy": str(COPIED_CONTROL),
                                            "required_copy_hash": sha256_bytes(control),
                                            "r001_and_r002_paths_explicitly_forbidden": ["acceleration/F8_OPC_q0p500_acceleration.csv", "acceleration/F8_OPC_q0p500_r002_acceleration.csv"]},
        "future_cpu_preflight_hard_gates": ["new r003-only authorization must bind both precommitted hashes and this compatibility receipt", "GenCase may be invoked at most once in the new r003 output namespace", "generated fixed boundary count must be positive with both z-wall planes", "generated control copy must exist and hash-match before any native decode", "any failure closes r003 with no same-input retry or r002-output reuse"],
        "next_automatic_step": {"kind": "one-time r003 static input materialization", "requires": ["exclusive creation of exactly the two precommitted input bytes", "an immutable materialization receipt"], "does_not_authorize": ["GenCase", "native decoder", "solver", "GPU", "queue", "worker", "registry", "ledger", "qualification", "training"]},
        "execution_controls": {"definition_written": False, "control_written": False, "gencase_invoked": False, "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False, "queue_mutation": 0, "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0, "training_started": False},
        "parameters": values, "bindings": bindings,
    }


def write_review(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r003 static review: {target}")
    review = build_review()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    review = write_review(parser.parse_args(argv).output)
    print(json.dumps({key: review[key] for key in ("schema", "status", "qualification_credit", "static_constraint_gaps")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
