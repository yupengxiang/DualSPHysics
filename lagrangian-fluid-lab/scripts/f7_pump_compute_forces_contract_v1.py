#!/usr/bin/env python3
"""Prepare a root-review-only ComputeForces contract for F7.

This module validates the official command semantics and emits a command
template.  It deliberately does not materialize native inputs or invoke
ComputeForces; those actions require a fresh F7 root admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
HELP = LAB / "vendor/official/DualSPHysics_v5.4/doc/help/ComputeForces_Help.out"
WRAPPER = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/xCasePump_linux64_CPU.sh"
PUMP_XML = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/CasePump_Def.xml"
OUTPUT = LAB / "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/compute-forces-contract-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    return {"path": str(path.relative_to(LAB)), "sha256": sha256(path),
            "bytes": path.stat().st_size, "role": role}


def build_contract() -> dict[str, Any]:
    help_text = HELP.read_text(encoding="utf-8")
    wrapper_text = WRAPPER.read_text(encoding="utf-8")
    required_help = {
        "native_data_directory": "-dirdata",
        "xml_binding": "-filexml",
        "moving_pump_filter": "-onlymk:<values>",
        "extrinsic_moment_axis": "-momentaxisex",
        "intrinsic_moment_axis": "-momentaxisin",
        "csv_output": "-savecsv",
        "ascii_output": "-saveascii",
        "force_units": "ForceFluid [N]",
        "moment_units": "Moment(s) [Nn]",
    }
    missing = [name for name, needle in required_help.items() if needle not in help_text]
    if missing:
        raise AssertionError(f"ComputeForces help contract changed: {missing}")
    if "computeforces=" not in wrapper_text:
        raise AssertionError("Pump wrapper no longer binds ComputeForces")

    return {
        "schema": "core.f7.pump.compute_forces_contract.v1",
        "status": "root_review_only_pending_native_bi4_and_admission",
        "candidate_id": "F7_pump_prescribed_internal_rotor_recirculation_v1",
        "qualification_claim": "none",
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "execution": {
            "authorized": False,
            "executed": False,
            "native_bi4_present": False,
            "solver_or_queue_mutation": 0,
        },
        "command_template": [
            "ComputeForces",
            "-dirdata <native_bi4_directory>",
            "-filexml <pump_definition.xml_or_AUTO>",
            "-onlymk:2",
            "-viscoauto",
            "-momentaxisex:<axis_p1_x>:<axis_p1_y>:<axis_p1_z>:<axis_p2_x>:<axis_p2_y>:<axis_p2_z>:pump_axis_ex",
            "-momentaxisin:<axis_p1_x>:<axis_p1_y>:<axis_p1_z>:<axis_p2_x>:<axis_p2_y>:<axis_p2_z>:pump_axis_in",
            "-savecsv <output/pump-force-moment.csv>",
            "-saveascii <output/pump-force-moment.asc>",
        ],
        "required_inputs": {
            "native_bi4": "all declared frames, including mk=2 moving pump particles and fluid neighbors",
            "definition_xml": "exact hash-bound F7 Definition used by the native run",
            "geometry_and_motion": "exact fixed/moving geometry and two-point rotation-axis schedule",
            "solver_and_parameters": "binary, kernel, viscosity, gravity, output cadence and time-axis hashes",
        },
        "required_outputs": {
            "time": "same time axis as native trajectory and control sidecar",
            "pump_force_world": "ForceFluid vector for onlymk=2, N",
            "pump_torque_world": "Moment vector from the declared axis options",
            "pump_torque_axis": "named intrinsic/extrinsic moment scalar with sign convention",
            "energy_check": "tau dot omega compared with fluid energy and declared dissipation budget",
        },
        "root_gates": {
            "mk2_filter_exact": True,
            "intrinsic_extrinsic_axis_semantics_frozen": True,
            "time_alignment_and_hash_binding": True,
            "nonzero_torque_during_motion": True,
            "no_external_angular_force_or_floating_body": True,
            "energy_consistency": True,
            "source_return_residence_unknown_regions_frozen": True,
        },
        "bindings": {
            "compute_forces_help": bind(HELP, "official ComputeForces command contract"),
            "pump_cpu_wrapper": bind(WRAPPER, "official Pump wrapper reference"),
            "pump_definition": bind(PUMP_XML, "official Pump Definition source"),
        },
        "not_yet_available": [
            "native BI4 frame archive for the existing F7 canary",
            "ComputeForces CSV/ASCII output",
            "energy consistency receipt",
            "root admission for fresh direct-torque observation",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_contract()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "status", "execution", "root_gates")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
