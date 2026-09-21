#!/usr/bin/env python3
"""Write a root-review-only F6 revision for actual ``TimePart`` semantics.

The v9 solver attempt is immutable negative evidence.  This proposal does not
reuse its Definition, generated XML/BI4, or trajectory as simulation input. It
only binds the old receipt as hash-only context and prepares a fresh case
identity whose time-axis contract treats the solver-reported native time as
authoritative.  It never runs GenCase, a solver, GPU work, a queue, or any
scientific registry/ledger/matrix update.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
V9_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-solver-canary-v9-20260921"
V9_RECEIPT = V9_ROOT / "attempt-001/execution-receipt.json"
V9_RUNPARTS = V9_ROOT / "attempt-001/solver/RunPARTs.csv"
V9_CONTRACT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v9-20260921/event-window-contract.json"
OUTPUT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cadence-revision-v10-20260921/proposal.json"
SCRIPT = Path(__file__).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str, *, hash_only: bool = False) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        display = str(path.relative_to(LAB))
    except ValueError:
        display = str(path)
    return {
        "path": display,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
        "hash_only": bool(hash_only),
    }


def write_proposal() -> dict[str, Any]:
    for path in (V9_RECEIPT, V9_RUNPARTS, V9_CONTRACT, SCRIPT):
        if not path.is_file():
            raise FileNotFoundError(path)
    proposal = {
        "schema": "core.f6.physical_anchor.cadence_revision_proposal.v1",
        "proposal_id": "F6_physical_anchor_observation_axis_v10_20260921",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "root_review_only_fresh_definition_required",
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_physical_anchor_v2",
        "prior_v9": {
            "status": "completed_negative_evidence_immutable",
            "receipt": ref(V9_RECEIPT, "v9 solver canary negative receipt", hash_only=True),
            "runparts": ref(V9_RUNPARTS, "v9 native output-time diagnostic", hash_only=True),
            "event_contract": ref(V9_CONTRACT, "v9 analytical event context", hash_only=True),
            "same_input_retry": False,
            "resume": False,
        },
        "fresh_identity": {
            "definition_id": "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v10_observation_axis_20260921",
            "case_id": "F6_explicit_body_v10_observation_axis_root_review_20260921",
            "revision_id": "F6_gravity_single_body_observation_axis_actual_time_v10",
            "fresh_definition_required": True,
            "fresh_generated_xml_required": True,
            "fresh_generated_bi4_required": True,
            "old_xml_bi4_hdf5_reused_as_input": False,
            "old_trajectory_reused_as_input": False,
        },
        "time_axis_contract": {
            "requested_output_interval_s": 0.005,
            "native_time_axis": "solver_reported_actual_TimeStep",
            "frame_count": 301,
            "start_time_s": 0.0,
            "end_time_target_s": 1.5,
            "strictly_increasing": True,
            "max_gap_s": 0.0055,
            "max_gap_basis": "pre_registered_10_percent_envelope_over_requested_interval; must be checked on the fresh input before any qualification claim",
            "terminal_coverage": {
                "mode": "bracket_target",
                "target_end_s": 1.5,
                "last_native_time_must_be_at_least_target": True,
                "terminal_overshoot_max_s": 0.0005,
            },
            "interpolation_for_common_grid": "linear_in_solver_reported_actual_time_only; no future CFD values",
        },
        "observation_window_contract": {
            "name": "observation_hold",
            "start_s": 1.0,
            "end_s": 1.5,
            "coverage": "native_time_bracket_with_max_gap_s",
            "requires_equilibrium_claim": False,
            "equilibrium_status": "not_claimed",
            "equilibrium_thresholds": None,
            "reason": "a time interval records post-contact dynamics but does not prove position/velocity/angular-velocity/force equilibrium",
        },
        "runtime_hard_gates": [
            "fresh Definition/XML/BI4 hashes match the new identity",
            "301 native frames, first time 0, strictly increasing actual TimeStep",
            "all native gaps <= 0.0055 s and final time in [1.5,1.5005] s",
            "body sidecar finite and identity fixed on every native row",
            "contact time remains inside the independently recomputed analytical window",
            "closed-face contact and penetration remain zero",
            "open-top mass flux remains zero",
            "observation window is bracketed without an equilibrium claim",
        ],
        "root_review_requirements": [
            "recompute the analytical event window from the fresh Definition",
            "run the v10 GenCase/native CPU preflight exactly once before solver authorization",
            "bind the new worker, solver, decoder, contracts, XML and BI4 by hash",
            "authorize at most one CPU solver attempt with no retry/resume/queue/registry/ledger/matrix mutation",
        ],
        "execution_controls": {
            "definition_written": False,
            "gencase_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "proposal_script": ref(SCRIPT, "proposal generator"),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(proposal, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return proposal


def main() -> int:
    proposal = write_proposal()
    print(json.dumps({"status": proposal["status"], "proposal": str(OUTPUT), "sha256": sha256(OUTPUT)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
