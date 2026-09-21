#!/usr/bin/env python3
"""Review and optionally authorize the new distributed-slot F2 proposal.

The review is deliberately a static gate.  It validates the proposal's fresh
scope, geometry identity, strict preflight gates, and hash bindings, then writes
an authorization receipt for exactly one fresh Definition plus CPU/native
preflight.  It has no path to GenCase, the native decoder, a solver, a GPU,
the queue, the ledger, the registry, or a qualification matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROPOSAL = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-proposal-v1.json"
DEFAULT_OUTPUT = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-root-review-v1.json"
SCHEMA = "core.f2.distributed_slot_transfer.root_review_receipt.v1"
PROPOSAL_SCHEMA = "core.f2.distributed_slot_transfer.proposal.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def verify_ref(item: Mapping[str, Any], label: str) -> Path:
    path_value = item.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError(f"{label}: missing path")
    path = Path(path_value).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path):
        raise ValueError(f"{label}: SHA-256 mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: byte-count mismatch")
    return path


def verify_proposal(proposal_path: Path = DEFAULT_PROPOSAL) -> dict[str, Any]:
    proposal_path = Path(proposal_path).resolve()
    proposal = load_json(proposal_path)
    if proposal.get("schema") != PROPOSAL_SCHEMA:
        raise ValueError("proposal schema mismatch")
    if proposal.get("status") != "root_review_only_new_physical_hypothesis_not_run":
        raise ValueError("proposal is not a root-review-only candidate")
    if proposal.get("family") != "F2" or proposal.get("scope_id") != "F2_distributed_submerged_slot_transfer_x_v1":
        raise ValueError("proposal is not the distributed-slot F2 scope")
    if proposal.get("qualification_claim") != "none" or proposal.get("qualified") is not False:
        raise ValueError("proposal carries a qualification claim")
    if proposal.get("matrix_credit") != 0 or proposal.get("root_review_only") is not True:
        raise ValueError("proposal carries matrix credit or is not static-only")

    novelty = proposal.get("novelty_and_lineage", {})
    if novelty.get("distinct_from_failed_scopes") is not True or novelty.get("reuses_failed_scope") is not False:
        raise ValueError("new scope is not separated from failed scopes")
    if not novelty.get("slots") and not proposal.get("fresh_geometry_contract", {}).get("transverse_gate", {}).get("slots"):
        # Keep the error specific while allowing the contract to carry the slots.
        raise ValueError("proposal has no explicit slot topology")

    parameter = proposal.get("minimum_parameter_contract", {})
    q_values = parameter.get("q_values")
    widths = parameter.get("slot_width_values_m")
    if q_values != [0.0, 0.25, 0.5, 0.75, 1.0] or widths != [0.06, 0.075, 0.09, 0.105, 0.12]:
        raise ValueError("slot-width parameter grid changed")
    anchor = parameter.get("anchor", {})
    if anchor.get("q") != 0.5 or anchor.get("slot_width_m") != 0.09 or anchor.get("dp_m") != 0.0075:
        raise ValueError("anchor identity changed")
    matrix = parameter.get("fixed_matrix", {})
    if matrix.get("planned_rows") != 15 or matrix.get("spatial_rows") != 13 or matrix.get("temporal_rows") != 2:
        raise ValueError("fixed qualification matrix changed")

    geometry = proposal.get("fresh_geometry_contract", {})
    gate = geometry.get("transverse_gate", {})
    slots = gate.get("slots")
    if not isinstance(slots, list) or len(slots) != 2:
        raise ValueError("distributed gate must contain exactly two slots")
    if gate.get("solid_web") is not True:
        raise ValueError("central solid web is required")
    centers = [slot.get("center_y_m") for slot in slots]
    if centers != [0.2, 0.4] or any(slot.get("width_parameter") != "slot_width_m" for slot in slots):
        raise ValueError("slot centers or width parameter changed")
    if geometry.get("upstream_source", {}).get("continuous_mass_kg") != 135.0:
        raise ValueError("source mass contract changed")
    if geometry.get("boundary_method") != "native mDBC Boundary=2 with the new gate-frame normal construction":
        raise ValueError("boundary contract changed")

    gates = proposal.get("cpu_native_preflight_gate", {})
    exact_zero_keys = ("zero_boundnor_count_max", "zero_normal_size_count_max", "fluid_boundary_overlap_count_max",
                       "outer_endpoint_count_max", "gate_endpoint_penetration_count_max",
                       "saved_initial_chord_crossing_count_max")
    if any(gates.get(key) != 0 for key in exact_zero_keys):
        raise ValueError("CPU/native zero-integrity gates were relaxed")
    if gates.get("source_mass_relative_error_max") != 0.025 or gates.get("total_mass_relative_error_max") != 0.03:
        raise ValueError("mass gates were changed")
    if gates.get("authorized_by_this_proposal") is not False or gates.get("must_follow_separate_root_review") is not True:
        raise ValueError("proposal unexpectedly authorizes runtime")
    boundary = proposal.get("authorization_boundary", {})
    for key in ("solver", "gpu", "queue", "ledger", "registry", "matrix_materialization", "matrix_submission"):
        if boundary.get(key) is not False:
            raise ValueError(f"proposal authorizes protected action: {key}")
    if boundary.get("qualification_credit_added") != 0 or boundary.get("core_gate_changed") is not False:
        raise ValueError("proposal changes Core credit")

    for label, item in proposal.get("evidence_bindings", {}).items():
        verify_ref(item, f"evidence binding {label}")
    return proposal


def build_receipt(proposal_path: Path = DEFAULT_PROPOSAL, output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    proposal_path = Path(proposal_path).resolve()
    output = Path(output).resolve()
    proposal = verify_proposal(proposal_path)
    if output.exists():
        raise FileExistsError(f"review receipt already exists: {output}")
    receipt = {
        "schema": SCHEMA,
        "created_at_utc": "2026-09-21T00:00:00+00:00",
        "record_id": "f2-distributed-slot-transfer-root-review-v1",
        "status": "authorized_one_fresh_definition_and_cpu_native_preflight_only",
        "review_decision": {
            "family": proposal["family"],
            "scope_id": proposal["scope_id"],
            "revision_id": proposal["revision_id"],
            "authorized_now": True,
            "authorized_action": "write_one_fresh_literal_definition_then_run_exactly_one_cpu_gencase_native_decode",
            "authorized_solver": False,
            "authorized_gpu": False,
            "authorized_queue": False,
            "authorized_ledger": False,
            "authorized_registry": False,
            "authorized_matrix": False,
            "reason": "the proposal binds a new two-slot gate topology and preserves an independent 15-row denominator with strict zero-integrity gates",
            "next_review_required": "root review after fresh Definition/native preflight hash closure before any protected solver anchor",
        },
        "fresh_input_requirements": {
            "new_definition": True,
            "new_output_stem": proposal["minimum_parameter_contract"]["anchor"]["output_stem"],
            "new_generated_xml": True,
            "new_native_bi4": True,
            "parent_orifice_inputs_reused": False,
            "parent_orifice_native_fields_reused": False,
            "source_mass_policy": proposal["cpu_native_preflight_gate"]["source_mass_policy"],
            "time_max_s": proposal["registered_window"]["time_max_s"],
            "output_interval_s": proposal["registered_window"]["output_interval_s"],
        },
        "fixed_hard_gates": proposal["cpu_native_preflight_gate"],
        "denominator": {
            "planned_rows": proposal["minimum_parameter_contract"]["fixed_matrix"]["planned_rows"],
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "unattempted_rows": proposal["minimum_parameter_contract"]["fixed_matrix"]["planned_rows"],
            "qualification_credit": 0,
            "same_input_retry": False,
        },
        "execution_constraints": {
            "definition_writer_invoked": False,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
        },
        "hash_bindings": {
            "proposal": ref(proposal_path, "new distributed-slot root-review proposal"),
            "review_implementation": ref(Path(__file__), "static root-review implementation"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "authorize"))
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    proposal = verify_proposal(args.proposal)
    if args.command == "verify":
        print(json.dumps({"status": "proposal_verified", "scope_id": proposal["scope_id"], "qualification_credit": 0}, ensure_ascii=False))
    else:
        receipt = build_receipt(args.proposal, args.output)
        print(json.dumps({"status": receipt["status"], "output": str(Path(args.output).resolve()), "qualification_credit": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
