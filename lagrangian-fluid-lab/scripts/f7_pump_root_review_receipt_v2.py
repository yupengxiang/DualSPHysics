#!/usr/bin/env python3
"""Emit a no-go F7 root-review receipt with complete planned bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922"
OUTPUT = ROOT / "root-review-receipt-v2-20260922.json"


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


def absent(relative: str, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": relative, "exists": path.is_file(), "sha256": None, "bytes": None, "role": role}


def build_receipt() -> dict[str, Any]:
    bindings = [
        bind(f"{ROOT.relative_to(LAB)}/direct-torque-admission-proposal-v2-20260922.json", "v2 direct-torque proposal under review"),
        bind(f"{ROOT.relative_to(LAB)}/root-review-receipt-v1.json", "superseded root receipt; historical execution state retained"),
        bind(f"{ROOT.relative_to(LAB)}/force-gauge-capability-audit-v1.json", "official force-gauge capability audit"),
        bind(f"{ROOT.relative_to(LAB)}/compute-forces-contract-v1.json", "official ComputeForces command contract"),
        bind("vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64", "official GenCase binary; not invoked"),
        bind("vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64", "official CPU solver binary; not invoked"),
        bind("vendor/official/DualSPHysics_v5.4/bin/linux/ComputeForces_linux64", "official ComputeForces binary; not invoked"),
        bind("campaigns/l1-resume/artifacts/bi4_dump", "native BI4 decoder executable; not invoked"),
        bind("vendor/official/DualSPHysics_v5.4/doc/help/ComputeForces_Help.out", "official ComputeForces help"),
        bind("vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/xCasePump_linux64_CPU.sh", "official Pump CPU wrapper; not invoked"),
        bind("vendor/official/DualSPHysics_v5.4/examples/main/13_Pump/CasePump_Def.xml", "official Pump source Definition"),
        bind("scripts/f7_pump_compute_forces_result_contract_v1.py", "frozen ComputeForces result parser contract"),
        bind("scripts/f7_pump_energy_consistency_contract_v1.py", "frozen energy evaluator contract"),
        bind("scripts/f7_pump_direct_torque_admission_proposal_v2.py", "proposal generator"),
    ]
    fresh_definition = "campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/input/F7_pump_torque_anchor_Def.xml"
    fresh_data = "campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/native/data"
    fresh_receipt = "campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1/native/native-integrity-receipt.json"
    return {
        "schema": "core.f7.pump_recirculation.root_review_receipt.v2",
        "status": "root_review_only_no_go_missing_fresh_materialization",
        "decision": "do_not_authorize_f7_anchor; retain candidate for a later independently reviewed admission",
        "candidate_id": "F7_pump_prescribed_internal_rotor_recirculation_v1",
        "proposal_revision": "F7_pump_direct_torque_anchor_revision_20260922_v2",
        "admission_granted": False,
        "definition_authorized": False,
        "preflight_authorized": False,
        "solver_authorized": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "diagnostic_only": True,
        "root_decision_basis": {
            "fresh_definition_materialized": False,
            "native_bi4_materialized": False,
            "native_integrity_receipt_present": False,
            "compute_forces_result_present": False,
            "energy_receipt_present": False,
            "result_parser_bound": True,
            "energy_evaluator_bound": True,
        },
        "historical_canary_separation": {
            "superseded_receipt": f"{ROOT.relative_to(LAB)}/root-review-receipt-v1.json",
            "superseded_receipt_solver_invoked": True,
            "interpretation": "historical isolated canary state only; not an execution by this v2 review",
            "current_v2_execution": False,
            "current_v2_solver_invoked": False,
            "current_v2_gpu_started": False,
            "current_v2_queue_mutation": 0,
        },
        "exact_future_anchor_counts_if_separately_authorized": {
            "definition_materialization": 1,
            "gencase": 1,
            "native_cpu_solver": 1,
            "native_decode": 1,
            "compute_forces": 1,
            "gpu": 0,
            "job_submission": 0,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "training_mutation": 0,
        },
        "fresh_artifact_integrity": {
            "definition": absent(fresh_definition, "required materialized fresh Definition; absent at review time"),
            "native_bi4_directory": absent(fresh_data, "required native BI4 directory; absent at review time"),
            "native_integrity_receipt": absent(fresh_receipt, "required frame/mk2/mass/decoder integrity receipt; absent at review time"),
            "required_integrity_fields": [
                "definition_sha256",
                "frame_first_last_count",
                "all_frame_sha256",
                "mk2_particle_count",
                "mk2_particle_id_hash",
                "mass_metadata_sha256",
                "decoder_path_and_sha256",
                "time_axis_sha256",
            ],
        },
        "future_result_contract": {
            "parser_schema": "core.f7.pump.compute_forces.result_parser.v1",
            "parser_path": "scripts/f7_pump_compute_forces_result_contract_v1.py",
            "normalized_fields": ["time_s", "force_fluid_x_N", "force_fluid_y_N", "force_fluid_z_N", "moment_pump_axis_in_Nm", "moment_pump_axis_ex_Nm"],
            "moment_units": "N*m only through explicit mapping from official [Nn] header",
            "time_alignment_tolerance_s": 1.0e-9,
            "empty_missing_duplicate_nan": "hard failure",
        },
        "energy_contract": {
            "evaluator_schema": "core.f7.pump.energy_consistency.evaluator.v1",
            "evaluator_path": "scripts/f7_pump_energy_consistency_contract_v1.py",
            "relative_tolerance": 0.10,
            "absolute_floor_J": 1.0e-12,
            "required_fields": ["time_s", "tau_axis_Nm", "omega_rad_s", "delta_energy_fluid_J", "dissipation_J", "gravity_work_J"],
            "receipt_present": False,
        },
        "protected_state_mutation": {
            "definition": 0,
            "gencase": 0,
            "native_decode": 0,
            "solver": 0,
            "compute_forces": 0,
            "gpu": 0,
            "job_submission": 0,
            "queue": 0,
            "registry": 0,
            "ledger": 0,
            "matrix": 0,
            "denominator": 0,
            "training": 0,
        },
        "hard_blockers": [
            "fresh Definition materialization and immutable hash receipt are absent",
            "native BI4 archive and integrity receipt are absent",
            "ComputeForces output and parser result receipt are absent",
            "energy sidecar and consistency receipt are absent",
            "the superseded v1 receipt records historical solver_invoked=true and cannot authorize this v2 anchor",
        ],
        "artifact_bindings": bindings,
        "forbidden_actions_until_new_admission": [
            "GenCase",
            "native CPU solver",
            "native decoder",
            "ComputeForces",
            "GPU",
            "queue/job submission",
            "registry/ledger/matrix/denominator/training mutation",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_receipt()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("schema", "status", "admission_granted", "protected_state_mutation")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
