#!/usr/bin/env python3
"""Materialize the single F8 Definition/control pair authorized by review v1.

This is intentionally a write-only static step.  It never invokes GenCase,
the native decoder, a solver, GPU code, the queue, registries, or ledgers.
Every output is created with exclusive-create semantics: an existing target
closes this one-time authority instead of permitting a replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
AUTHORIZATION = ROOT / "definition-control-static-review-v1/review.json"
CONTRACT = ROOT / "parameter-contract-v1.json"
DEFINITION_TARGET = ROOT / "input/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001_Def.xml"
CONTROL_TARGET = ROOT / "input/acceleration/F8_OPC_q0p500_acceleration.csv"
RECEIPT_TARGET = ROOT / "input-materialization-v1/receipt.json"
SCHEMA = "core.cfd.f8.input_materialization.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": str(relative), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load_json(relative: Path) -> dict[str, Any]:
    value = json.loads((LAB / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative}")
    return value


def parameters(contract: dict[str, Any]) -> dict[str, float | int]:
    geometry = contract["geometry_and_fluid"]
    parameterization = contract["parameterization"]
    limits = contract["numerical_limits"]
    resolution = contract["resolution_contract"]
    q = 0.5
    alpha = 2.0 + 6.0 * q
    half_height = float(geometry["half_height_m"])
    viscosity = float(geometry["kinematic_viscosity_m2_s"])
    omega = alpha * alpha * viscosity / (half_height * half_height)
    period = 2.0 * math.pi / omega
    observation_start = max(2.0 * float(limits["tau_viscous_s"]), 2.0 * period)
    warmup_cycles = math.ceil(observation_start / period)
    observation_cycles = int(limits["observation_cycles"])
    points_per_period = int(limits["control_table_points_per_period"])
    total_cycles = warmup_cycles + observation_cycles
    return {
        "q": q,
        "alpha": alpha,
        "omega": omega,
        "period": period,
        "observation_start": observation_start,
        "warmup_cycles": warmup_cycles,
        "observation_cycles": observation_cycles,
        "total_cycles": total_cycles,
        "points_per_period": points_per_period,
        "t_end": total_cycles * period,
        "amplitude": float(parameterization["acceleration_amplitude_m_s2"]),
        "half_height": half_height,
        "length_x": float(geometry["length_x_m"]),
        "length_y": float(geometry["length_y_m"]),
        "rho0": float(geometry["rho0_kg_m3"]),
        "viscosity": viscosity,
        "dp": float(resolution["production_dp_m"]),
        "sound_speed": float(limits["sound_speed_m_s"]),
    }


def validate_authorization(review: dict[str, Any]) -> None:
    authorization = review.get("static_materialization_authorization", {})
    if not (
        review.get("schema") == "core.cfd.f8.definition_control_static_review.v1"
        and review.get("scope_id") == SCOPE
        and review.get("status") == "static_constraints_satisfied_one_time_definition_control_materialization_authorized"
        and review.get("qualification_claim") == "none"
        and review.get("qualification_credit") == 0
        and review.get("static_constraint_gaps") == []
        and authorization.get("granted") is True
        and authorization.get("authorization_consumed") is False
        and authorization.get("reuse_or_overwrite_allowed") is False
        and authorization.get("definition_target") == str(DEFINITION_TARGET)
        and authorization.get("control_target") == str(CONTROL_TARGET)
    ):
        raise PermissionError("F8 v1 static review does not grant this exact one-time materialization")


def definition_xml(values: dict[str, float | int]) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- Static F8 r001 input.  This is not a solver admission or qualification. -->
<case>
  <casedef>
    <constantsdef>
      <gravity x="0" y="0" z="0" comment="Global gravity disabled; forcing is accinput linear X acceleration." units_comment="m/s^2" />
      <rhop0 value="{values['rho0']:.17g}" comment="Reference density" units_comment="kg/m^3" />
      <rhopgradient value="1" comment="Uniform fully-filled fluid reference density." />
      <hswl value="0" auto="true" comment="No free surface is present." units_comment="metres (m)" />
      <gamma value="7" comment="Polytropic constant." />
      <speedsystem value="0" auto="true" comment="Static input value." />
      <coefsound value="1" comment="Static input value." />
      <speedsound value="{values['sound_speed']:.17g}" auto="false" comment="Contract sound speed." units_comment="m/s" />
      <coefh value="1.0" comment="Smoothing-length coefficient." />
      <cflnumber value="0.2" comment="Static preflight value only." />
    </constantsdef>
    <mkconfig boundcount="1" fluidcount="1" />
    <geometry>
      <definition dp="{values['dp']:.17g}" units_comment="metres (m)">
        <pointref x="0" y="0" z="0" />
        <pointmin x="0" y="0" z="-{values['half_height']:.17g}" />
        <pointmax x="{values['length_x']:.17g}" y="{values['length_y']:.17g}" z="{values['half_height']:.17g}" />
      </definition>
      <commands>
        <mainlist>
          <setshapemode>actual | bound</setshapemode>
          <setdrawmode mode="full" />
          <setmkbound mk="0" name="FixedNoSlipZWalls" />
          <drawbox>
            <boxfill>top|bottom</boxfill>
            <point x="0" y="0" z="-{values['half_height']:.17g}" />
            <size x="{values['length_x']:.17g}" y="{values['length_y']:.17g}" z="{2.0 * float(values['half_height']):.17g}" />
          </drawbox>
          <setmkfluid mk="0" name="FullyFilledChannelFluid" />
          <drawbox>
            <boxfill>solid</boxfill>
            <point x="0" y="0" z="-{values['half_height']:.17g}" />
            <size x="{values['length_x']:.17g}" y="{values['length_y']:.17g}" z="{2.0 * float(values['half_height']):.17g}" />
          </drawbox>
        </mainlist>
      </commands>
    </geometry>
  </casedef>
  <execution>
    <special>
      <accinputs>
        <accinput mkfluid="0">
          <acccentre x="0" y="0" z="0" comment="Fixed acceleration reference centre." units_comment="metres (m)" />
          <globalgravity value="0" comment="Gravity remains disabled for this body-force input." />
          <acctimesfile value="acceleration/F8_OPC_q0p500_acceleration.csv" comment="Zero-mean linear X acceleration table." />
        </accinput>
      </accinputs>
    </special>
    <parameters>
      <parameter key="Boundary" value="2" comment="mDBC fixed boundary method." />
      <parameter key="StepAlgorithm" value="2" comment="Static preflight value only." />
      <parameter key="Kernel" value="2" comment="Wendland kernel." />
      <parameter key="ViscoTreatment" value="3" comment="Laminar viscosity." />
      <parameter key="Visco" value="{values['viscosity']:.17g}" comment="Contract kinematic viscosity." units_comment="m^2/s" />
      <parameter key="ViscoBoundFactor" value="1" comment="Fixed wall viscosity factor." />
      <parameter key="DensityDT" value="0" comment="No density diffusion in this static input." />
      <parameter key="Shifting" value="0" comment="No shifting." />
      <parameter key="RigidAlgorithm" value="1" comment="No floating or rigid-body component is defined." />
      <parameter key="TimeMax" value="{values['t_end']:.17g}" comment="Control coverage end time." units_comment="seconds" />
      <parameter key="TimeOut" value="{float(values['period']) / int(values['points_per_period']):.17g}" comment="One control-table interval." units_comment="seconds" />
      <parameter key="PartsOutMax" value="0" comment="No excluded fluid particles permitted." />
      <parameter key="RhopOutMin" value="950" comment="Contract density lower bound." units_comment="kg/m^3" />
      <parameter key="RhopOutMax" value="1050" comment="Contract density upper bound." units_comment="kg/m^3" />
      <parameter key="XYPeriodic" value="0" comment="Periodic BC in X and Y; value is ignored by native presence semantics." />
      <simulationdomain comment="Use generated channel extent.">
        <posmin x="default" y="default" z="default" />
        <posmax x="default" y="default" z="default" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
'''


def acceleration_csv(values: dict[str, float | int]) -> str:
    points = int(values["points_per_period"])
    total = int(values["total_cycles"]) * points
    period = float(values["period"])
    omega = float(values["omega"])
    amplitude = float(values["amplitude"])
    rows = ["#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ"]
    for index in range(total + 1):
        time_s = period * index / points
        ax = amplitude * math.sin(omega * time_s)
        if index in (0, total):
            ax = 0.0
        rows.append(f"{time_s:.17g};{ax:.17g};0;0;0;0;0")
    return "\n".join(rows) + "\n"


def ensure_absent(*targets: Path) -> None:
    existing = [str(target) for target in targets if target.exists()]
    if existing:
        raise FileExistsError("refusing one-time F8 materialization because target already exists: " + ", ".join(existing))


def build_receipt(values: dict[str, float | int]) -> dict[str, Any]:
    bindings = [
        binding(AUTHORIZATION, "one-time static materialization authorization"),
        binding(CONTRACT, "frozen F8 parameter contract"),
        binding(Path("scripts/f8_input_materialization_v1.py"), "exclusive-create input writer"),
        binding(DEFINITION_TARGET, "new F8 Definition XML"),
        binding(CONTROL_TARGET, "new F8 acceleration CSV"),
    ]
    return {
        "schema": SCHEMA,
        "scope_id": SCOPE,
        "status": "one_time_inputs_materialized_static_only",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "authorization": {
            "source": str(AUTHORIZATION),
            "consumed": True,
            "definition_target": str(DEFINITION_TARGET),
            "control_target": str(CONTROL_TARGET),
            "overwrite_or_reuse_allowed": False,
        },
        "parameters": values,
        "execution_controls": {
            "definition_written": True,
            "control_written": True,
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
        "explicitly_not_authorized": [
            "GenCase", "native decoder", "solver", "GPU", "queue", "registry", "ledger",
            "T1 or T2 qualification", "training", "CPU preflight",
        ],
        "bindings": bindings,
    }


def write_materialization(
    definition_target: Path = LAB / DEFINITION_TARGET,
    control_target: Path = LAB / CONTROL_TARGET,
    receipt_target: Path = LAB / RECEIPT_TARGET,
) -> dict[str, Any]:
    if (definition_target, control_target, receipt_target) != (
        LAB / DEFINITION_TARGET, LAB / CONTROL_TARGET, LAB / RECEIPT_TARGET
    ):
        raise ValueError("F8 one-time writer only permits its registered targets")
    review = load_json(AUTHORIZATION)
    contract = load_json(CONTRACT)
    validate_authorization(review)
    if contract.get("scope_id") != SCOPE or contract.get("admission_granted") is not False:
        raise PermissionError("F8 parameter contract is not the frozen, non-admitted contract")
    ensure_absent(definition_target, control_target, receipt_target)
    values = parameters(contract)
    definition_target.parent.mkdir(parents=True, exist_ok=True)
    control_target.parent.mkdir(parents=True, exist_ok=True)
    receipt_target.parent.mkdir(parents=True, exist_ok=True)
    definition_target.open("x", encoding="utf-8").write(definition_xml(values))
    control_target.open("x", encoding="utf-8").write(acceleration_csv(values))
    receipt = build_receipt(values)
    receipt_target.open("x", encoding="utf-8").write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    receipt = write_materialization()
    print(json.dumps({key: receipt[key] for key in ("schema", "status", "qualification_credit", "authorization")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
