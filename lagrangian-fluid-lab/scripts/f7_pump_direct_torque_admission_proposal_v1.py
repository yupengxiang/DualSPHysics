#!/usr/bin/env python3
"""Build a fail-closed proposal for one F7 direct-torque anchor.

The output is a request for root review, not an authorization.  It requests a
fresh CPU-only output namespace and keeps all Core scientific ledgers frozen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922"
OUTPUT = ROOT / "direct-torque-admission-proposal-v1.json"


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
    return {
        "schema": "core.f7.pump.direct_torque_admission_proposal.v1",
        "status": "proposal_pending_root_review_not_authorized",
        "candidate_id": "F7_pump_prescribed_internal_rotor_recirculation_v1",
        "requested_scope_id": "F7_pump_recirculation_direct_torque_anchor_x_v1",
        "requested_case_id": "F7_PUMP_RECIRCULATION_TORQUE_q0p50_dp0p0200_anchor",
        "qualification_claim": "none",
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "qualification_credit": 0,
        "scientific_purpose": "Obtain provenance-verified moving-pump fluid force and intrinsic/extrinsic axis torque for adversarial F7-vs-F6 independence review.",
        "fresh_lineage": {
            "new_scope_id": True,
            "new_case_id": True,
            "new_revision_id": "F7_pump_direct_torque_anchor_revision_20260922",
            "fresh_output_namespace": "campaigns/core-v1/cfd/f7-pump-direct-torque-anchor-v1",
            "existing_h5_canary_reused_as_torque_evidence": False,
            "same_input_retry": False,
        },
        "requested_permissions_exactly_one_anchor": {
            "new_definition_in_fresh_namespace": True,
            "gencase_for_fresh_definition": True,
            "native_cpu_solver_one_anchor_only": True,
            "compute_forces_cpu_one_anchor_only": True,
            "gpu": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "required_runtime_contract": {
            "source_definition": "new literal Definition bound to official Pump geometry/motion sources",
            "native_archive": "all required Part_XXXX.bi4 frames, including mk=2 and fluid particles",
            "compute_forces_filter": "-onlymk:2",
            "moment_axes": ["momentaxisin", "momentaxisex"],
            "time_alignment": "native trajectory, control sidecar and ComputeForces outputs share exact hashed time axis",
            "energy_check": "tau dot omega compared against fluid energy and declared dissipation budget",
        },
        "hard_stop_gates": [
            "missing or non-contiguous native BI4",
            "particle identity or mk=2 XML mismatch",
            "ComputeForces output missing force/moment/time fields",
            "zero or non-finite torque during declared pump motion",
            "axis sign or intrinsic/extrinsic semantics unresolved",
            "energy consistency failure",
            "source/return/residence/unknown regions not frozen",
            "any registry, ledger, matrix, denominator, GPU or queue mutation",
        ],
        "root_review_decision_required": {
            "admit_one_protected_cpu_anchor": True,
            "admit_15_row_matrix": False,
            "admit_32_case_production": False,
            "admit_t1_credit": False,
            "admit_training": False,
        },
        "bindings": {
            "current_root_review": bind(
                "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/root-review-receipt-v1.json",
                "current F7 root review; currently denies admission",
            ),
            "compute_forces_contract": bind(
                "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/compute-forces-contract-v1.json",
                "direct torque command contract",
            ),
            "force_gauge_audit": bind(
                "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/force-gauge-capability-audit-v1.json",
                "official force-gauge capability audit",
            ),
            "candidate_card": bind(
                "campaigns/core-v1/cfd/f7-pump-recirculation-root-review-20260922/candidate-card-v1.json",
                "F7 physical candidate card",
            ),
            "compute_forces_binary": bind(
                "vendor/official/DualSPHysics_v5.4/bin/linux/ComputeForces_linux64",
                "official ComputeForces executable; proposal binding only",
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_proposal()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "status", "requested_scope_id", "requested_permissions_exactly_one_anchor")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
