#!/usr/bin/env python3
"""Build the fully bound, fail-closed F7 direct-torque root-review proposal.

This file describes one possible protected CPU anchor.  It does not authorize
or execute GenCase, the native solver, native decoding, or ComputeForces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

try:
    from scripts.f7_pump_geometry_adapter_v1 import parse_pump_definition
except ModuleNotFoundError:  # Support direct execution from the repository root.
    from f7_pump_geometry_adapter_v1 import parse_pump_definition


ROOT = LAB / "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922"
OUTPUT = ROOT / "direct-torque-admission-proposal-v2-20260922.json"
FRESH = "campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1"
FRESH_DEFINITION = f"{FRESH}/input/F7_pump_torque_anchor_Def.xml"
FRESH_DATA = f"{FRESH}/native/data"
FRESH_FORCE = f"{FRESH}/compute-forces"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(relative: str, role: str) -> dict[str, Any]:
    path = LAB / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def build_proposal() -> dict[str, Any]:
    motion = parse_pump_definition()
    p1 = motion["axis_point_m"]
    p2 = motion["axis_p2_m"]
    axis = ":".join(f"{float(value):.10g}" for value in (*p1, *p2))
    command = [
        "vendor/official/DualSPHysics_v5.4/bin/linux/ComputeForces_linux64",
        f"-dirdata {FRESH_DATA}",
        f"-filexml {FRESH_DEFINITION}",
        "-first:0",
        "-last:300",
        "-onlymk:2",
        "-viscoauto",
        f"-momentaxisin:{axis}:pump_axis_in",
        f"-momentaxisex:{axis}:pump_axis_ex",
        f"-savecsv {FRESH_FORCE}/pump-force-moment.csv",
        f"-saveascii {FRESH_FORCE}/pump-force-moment.asc",
    ]
    return {
        "schema": "core.f7.pump.direct_torque_admission_proposal.v2",
        "status": "proposal_pending_root_review_not_authorized",
        "candidate_id": "F7_pump_prescribed_internal_rotor_recirculation_v1",
        "requested_scope_id": "F7_pump_recirculation_direct_torque_anchor_x_v1",
        "requested_case_id": "F7_PUMP_RECIRCULATION_TORQUE_q0p50_dp0p0200_anchor",
        "revision_id": "F7_pump_direct_torque_anchor_revision_20260922_v2",
        "qualification_claim": "none",
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "diagnostic_only": True,
        "scientific_purpose": "Obtain one provenance-verified moving-pump fluid force and intrinsic/extrinsic axis-torque observation for an independence review; this observation cannot register or qualify F7.",
        "fresh_lineage": {
            "new_scope_id": True,
            "new_case_id": True,
            "new_revision_id": True,
            "fresh_output_namespace": FRESH,
            "fresh_definition_path": FRESH_DEFINITION,
            "fresh_definition_materialization_required": True,
            "fresh_definition_expected_source_sha256": motion["definition_sha256"],
            "existing_h5_canary_reused_as_input": False,
            "existing_h5_canary_reused_as_torque_evidence": False,
            "same_input_retry": False,
            "overwrite_existing_namespace": False,
        },
        "requested_permissions_exact_counts": {
            "new_definition_materialization": 1,
            "gencase": 1,
            "native_cpu_solver": 1,
            "native_decode": 1,
            "compute_forces_cpu": 1,
            "gpu": 0,
            "job_submission": 0,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "training_mutation": 0,
            "qualification_credit": 0,
        },
        "fresh_definition_contract": {
            "literal_path": FRESH_DEFINITION,
            "must_copy_official_geometry_and_motion": True,
            "source_definition_path": motion["definition_path"],
            "source_definition_sha256": motion["definition_sha256"],
            "required_mk_labels": {"fixed": 0, "moving": 2, "fluid": 1},
            "required_axis_point_m": p1,
            "required_axis_p2_m": p2,
            "required_axis_coordinate_system": "world Cartesian metres",
            "required_motion_begin_s": motion["begin_start_s"],
            "required_motion_finish_s": motion["finish_s"],
            "materialized_hash_must_be_recorded_before_solver": True,
        },
        "native_bi4_contract": {
            "data_directory": FRESH_DATA,
            "expected_frame_first": 0,
            "expected_frame_last": 300,
            "expected_frame_count": 301,
            "expected_time_start_s": 0.0,
            "expected_time_end_s": 6.0,
            "expected_output_step_s": 0.02,
            "required_particle_groups": ["mk=1 fluid", "mk=2 moving boundary"],
            "required_mk2_particle_count_and_id_hash": "must be measured and hash-bound before acceptance",
            "required_mass_metadata": "must be decoded and hash-bound before acceptance",
            "decoder_identity": "official Part_XXXX.bi4 decoder used by the audit harness; version and SHA256 must be recorded in the native integrity receipt",
            "preflight_present": False,
            "preflight_authorized": False,
        },
        "compute_forces_command": {
            "argv": command,
            "first": 0,
            "last": 300,
            "files": 301,
            "filter": "onlymk:2 exactly; no other boundary group",
            "viscosity": "viscoauto",
            "axis_points_m": {"p1": p1, "p2": p2},
            "axis_coordinate_system": "world Cartesian metres for command input",
            "intrinsic_axis_name": "pump_axis_in",
            "extrinsic_axis_name": "pump_axis_ex",
            "output_csv": f"{FRESH_FORCE}/pump-force-moment.csv",
            "output_ascii": f"{FRESH_FORCE}/pump-force-moment.asc",
            "execution_authorized": False,
            "execution_completed": False,
        },
        "moment_result_contract": {
            "raw_source": "official ComputeForces CSV and ASCII outputs; raw headers and files are immutable evidence",
            "required_time_field": "Time [s] or an explicitly mapped official equivalent",
            "required_force_fields": ["ForceFluid_x [N]", "ForceFluid_y [N]", "ForceFluid_z [N]"],
            "required_moment_fields": ["pump_axis_in", "pump_axis_ex"],
            "force_units": "N",
            "moment_units": "N*m; reject ambiguous headers instead of silently relabeling the official [Nn] help text",
            "sign_convention": "right-hand rule about p1->p2; intrinsic axis rotates with body, extrinsic axis translates but does not rotate",
            "world_axis_semantics": "axis points are world-coordinate inputs; parser records official intrinsic/extrinsic mapping",
            "parser_schema": "core.f7.pump.compute_forces.result_parser.v1",
            "time_alignment_tolerance_s": 1.0e-9,
            "duplicate_or_missing_time_is_failure": True,
            "empty_or_nan_required_field_is_failure": True,
        },
        "numeric_acceptance_gates": {
            "motion_active_interval_s": [motion["begin_start_s"], motion["begin_start_s"] + motion["segments"][0]["duration_s"]],
            "minimum_abs_torque_Nm": 1.0e-8,
            "minimum_active_frames_at_or_above_threshold": 2,
            "nonzero_torque_requires_finite_values": True,
            "energy_dataset": f"{FRESH_FORCE}/energy-consistency.csv",
            "energy_definition": "integral(tau_intrinsic * omega_prescribed) compared against decoded fluid mechanical-energy change plus declared viscous/gravity terms on the same native time axis",
            "energy_relative_residual_tolerance": 0.10,
            "energy_absolute_floor_J": 1.0e-12,
            "energy_failure_on_missing_nan_or_unaligned_samples": True,
            "thresholds_frozen_before_execution": True,
        },
        "hard_failure_policy": {
            "any_gate_failure": "zero credit",
            "denominator_policy": "preserve all Core denominators; add no case or family credit",
            "same_input_retry": "forbidden",
            "retry_requires": "new scope, new revision, new case, new output namespace, and a new root review",
            "partial_csv_or_partial_bi4": "failure; retain immutable artifacts for audit",
            "solver_gpu_queue_registry_ledger_matrix_training_mutation_outside_exact_counts": "failure",
        },
        "core_credit_firewall": {
            "register_t1_scope": False,
            "register_t2_scope": False,
            "evaluate_production_matrix": False,
            "modify_t1_or_t2_denominators": False,
            "release_training": False,
            "credit_even_if_all_diagnostic_gates_pass": 0,
        },
        "root_review_decision_required": {
            "admit_exactly_one_protected_cpu_anchor": True,
            "admit_native_solver_once": True,
            "admit_gencase_once": True,
            "admit_native_decode_once": True,
            "admit_compute_forces_once": True,
            "admit_production_matrix": False,
            "admit_32_case_production": False,
            "admit_t1_credit": False,
            "admit_training": False,
        },
        "bindings": {
            "current_root_review": bind(f"{ROOT.relative_to(LAB)}/root-review-receipt-v1.json", "current F7 root review; denies admission"),
            "v1_proposal": bind(f"{ROOT.relative_to(LAB)}/direct-torque-admission-proposal-v1.json", "superseded incomplete proposal; retained for audit"),
            "compute_forces_contract": bind(f"{ROOT.relative_to(LAB)}/compute-forces-contract-v1.json", "official ComputeForces contract"),
            "force_gauge_audit": bind(f"{ROOT.relative_to(LAB)}/force-gauge-capability-audit-v1.json", "official force-gauge capability audit"),
            "candidate_card": bind(f"{ROOT.relative_to(LAB)}/candidate-card-v1.json", "F7 physical candidate card"),
            "compute_forces_binary": bind("vendor/official/DualSPHysics_v5.4/bin/linux/ComputeForces_linux64", "official ComputeForces executable; not invoked"),
            "compute_forces_help": bind("vendor/official/DualSPHysics_v5.4/doc/help/ComputeForces_Help.out", "official command and output help; not invoked"),
            "pump_cpu_wrapper": bind("vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/xCasePump_linux64_CPU.sh", "official CPU wrapper reference; not invoked"),
            "pump_definition": bind("vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/CasePump_Def.xml", "official geometry and motion source"),
            "geometry_motion_contract": bind("scripts/f7_pump_geometry_adapter_v1.py", "hash-checked geometry/motion parser"),
        },
        "protected_state_mutation": {
            "proposal_generation": 0,
            "gencase_executed": 0,
            "native_solver_executed": 0,
            "native_decode_executed": 0,
            "compute_forces_executed": 0,
            "gpu": 0,
            "job_submission": 0,
            "queue": 0,
            "registry": 0,
            "ledger": 0,
            "matrix": 0,
            "denominator": 0,
            "training": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_proposal()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "status", "requested_permissions_exact_counts", "compute_forces_command")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
