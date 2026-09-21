#!/usr/bin/env python3
"""Root-review gate for the one fresh distributed-slot normal-layer repair."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/normal-repair-v2/distributed-slot-normal-repair-proposal-v2.json"
DEFAULT_OUTPUT = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/normal-repair-v2/root-review-v2.json"
SCHEMA = "core.f2.distributed_slot_transfer.normal_repair_root_review.v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def verify_proposal(path: Path = PROPOSAL) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != "core.f2.distributed_slot_transfer.normal_repair_proposal.v2":
        raise ValueError("normal-repair proposal schema mismatch")
    if value.get("status") != "root_review_only_fresh_normal_hypothesis_not_run":
        raise ValueError("normal-repair proposal is not static-only")
    if value.get("revision_id") != "F2_distributed_slot_gate_normal_layers_v2":
        raise ValueError("normal-repair revision mismatch")
    if value.get("matrix_credit") != 0 or value.get("qualification_claim") != "none":
        raise ValueError("normal-repair proposal has credit")
    boundary = value.get("authorization_boundary", {})
    for key in ("definition_writer_authorized", "cpu_native_authorized", "solver", "gpu", "queue", "ledger", "registry", "matrix_submission"):
        if boundary.get(key) is not False:
            raise ValueError(f"proposal unexpectedly authorizes {key}")
    gates = value.get("hard_preflight_gates", {})
    for key in ("zero_boundnor_count_max", "zero_normal_size_count_max", "fluid_boundary_overlap_count_max", "outer_endpoint_count_max", "gate_endpoint_penetration_count_max", "saved_initial_chord_crossing_count_max"):
        if gates.get(key) != 0:
            raise ValueError("normal-repair hard gate relaxed")
    if gates.get("source_mass_relative_error_max") != 0.025 or gates.get("total_mass_relative_error_max") != 0.03:
        raise ValueError("normal-repair mass gate changed")
    changed = value.get("falsifiable_hypothesis", {}).get("changed_contract", {})
    if changed.get("outer_normal_layers_vdp") != "0,-1,-2" or changed.get("gate_frame_normal_layers_vdp") != "0,-1,-2":
        raise ValueError("normal-layer hypothesis changed")
    for label, item in value.get("hash_bindings", {}).items():
        bound = Path(item["path"])
        if item.get("sha256") != sha256(bound) or item.get("bytes") != bound.stat().st_size:
            raise ValueError(f"stale hash binding: {label}")
    return value


def build(output: Path = DEFAULT_OUTPUT, proposal: Path = PROPOSAL) -> dict[str, Any]:
    output = Path(output).resolve()
    proposal = Path(proposal).resolve()
    if output.exists():
        raise FileExistsError(output)
    value = verify_proposal(proposal)
    receipt = {
        "schema": SCHEMA,
        "created_at_utc": "2026-09-21T00:00:00+00:00",
        "record_id": "f2-distributed-slot-normal-repair-root-review-v2",
        "status": "authorized_one_fresh_definition_and_cpu_native_preflight_only",
        "review_decision": {
            "family": "F2",
            "scope_id": value["scope_id"],
            "revision_id": value["revision_id"],
            "candidate_case_id": value["candidate_case_id"],
            "authorized_now": True,
            "authorized_action": "write_one_fresh_literal_definition_then_run_exactly_one_cpu_gencase_native_decode",
            "authorized_solver": False,
            "authorized_gpu": False,
            "authorized_queue": False,
            "authorized_ledger": False,
            "authorized_registry": False,
            "authorized_matrix": False,
            "reason": "the v1 negative evidence localizes zero normals to both Mk partitions; v2 changes only the fresh GeometryForNormals layer construction and preserves all physical and hard gates",
            "next_review_required": "review fresh v2 Definition and CPU/native hash closure before any protected solver anchor",
        },
        "fresh_identity": {
            "new_definition_required": True,
            "new_output_stem": value["output_stem"],
            "old_v1_definition_reused": False,
            "old_v1_generated_xml_reused": False,
            "old_v1_native_bi4_reused": False,
            "old_v1_boundnor_reused": False,
            "same_input_retry": False,
        },
        "fixed_hard_gates": value["hard_preflight_gates"],
        "denominator": {"planned_rows": 15, "executed_rows": 0, "passed_rows": 0, "failed_rows": 0, "unattempted_rows": 15, "qualification_credit": 0},
        "execution_constraints": {"definition_writer_invoked": False, "gencase_invoked": False, "native_decoder_invoked": False, "solver_invoked": False, "gpu_started": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_mutation": 0, "qualification_credit": 0},
        "hash_bindings": {"proposal": ref(proposal, "v2 normal-layer proposal"), "review_implementation": ref(Path(__file__), "v2 root-review implementation")},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "authorize"))
    parser.add_argument("--proposal", type=Path, default=PROPOSAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    value = verify_proposal(args.proposal)
    if args.command == "verify":
        print(json.dumps({"status": "proposal_verified", "revision_id": value["revision_id"], "matrix_credit": 0}, ensure_ascii=False))
    else:
        receipt = build(args.output, args.proposal)
        print(json.dumps({"status": receipt["status"], "output": str(Path(args.output).resolve()), "matrix_credit": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
