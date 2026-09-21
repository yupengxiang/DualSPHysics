#!/usr/bin/env python3
"""Build a fresh root-review-only normal-construction hypothesis for F2 slots."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1"
PARENT_PROPOSAL = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-proposal-v1.json"
PARENT_REVIEW = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-root-review-v1.json"
NEGATIVE = LAB_ROOT / "campaigns/core-v1/evidence/f2-distributed-slot-preflight-negative-evidence-v1.json"
DEFAULT_OUTPUT = BASE / "normal-repair-v2/distributed-slot-normal-repair-proposal-v2.json"
SCHEMA = "core.f2.distributed_slot_transfer.normal_repair_proposal.v2"
REVISION_ID = "F2_distributed_slot_gate_normal_layers_v2"
CASE_ID = "F2_SLOT_TRANSFER_q0p50000000_dp0p007500000000_anchor_v2"
OUTPUT_STEM = CASE_ID


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


def build(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    parent = load(PARENT_PROPOSAL)
    review = load(PARENT_REVIEW)
    negative = load(NEGATIVE)
    if parent.get("schema") != "core.f2.distributed_slot_transfer.proposal.v1":
        raise ValueError("parent proposal schema mismatch")
    if review.get("status") != "authorized_one_fresh_definition_and_cpu_native_preflight_only":
        raise ValueError("parent review status mismatch")
    if negative.get("status") != "completed_negative_result" or negative.get("matrix_credit") != 0:
        raise ValueError("parent negative evidence is not closed zero-credit evidence")
    partition = negative.get("partition", {})
    if partition.get("zero_boundnor_count") != 124608 or partition.get("zero_normal_size_count") != 124608:
        raise ValueError("negative normal partition changed")
    rows = negative.get("partition", {}).get("mk_partitions", [])
    by_mk = {int(row["mk"]): row for row in rows}
    if by_mk.get(17, {}).get("zero_boundnor_count") != 81818 or by_mk.get(18, {}).get("zero_boundnor_count") != 42790:
        raise ValueError("negative Mk partition changed")
    proposal = {
        "schema": SCHEMA,
        "created_at_utc": "2026-09-21T00:00:00+00:00",
        "status": "root_review_only_fresh_normal_hypothesis_not_run",
        "family": "F2",
        "scope_id": "F2_distributed_submerged_slot_transfer_x_v1",
        "parent_revision_id": parent["revision_id"],
        "revision_id": REVISION_ID,
        "proposal_id": "F2_distributed_slot_normal_layers_q05_dp0075_v2",
        "candidate_case_id": CASE_ID,
        "output_stem": OUTPUT_STEM,
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "repair_class": "fresh_geometry_for_normals_layer_construction",
        "physical_scope_unchanged": True,
        "new_input_identity": {
            "fresh_literal_definition_required": True,
            "fresh_generated_xml_required": True,
            "fresh_native_bi4_required": True,
            "old_v1_definition_reused": False,
            "old_v1_generated_xml_reused": False,
            "old_v1_native_bi4_reused": False,
            "old_v1_boundnor_reused": False,
            "old_v1_trajectory_reused": False,
            "same_input_retry": False,
        },
        "observed_failure": {
            "source_evidence": ref(NEGATIVE, "v1 CPU/native negative evidence"),
            "zero_boundnor_count": 124608,
            "zero_normal_size_count": 124608,
            "outer_mk17_zero_count": 81818,
            "gate_mk18_zero_count": 42790,
            "source_mass_relative_error": negative["preflight"]["mass_contract"]["relative_error"],
            "hard_gate": "zero BoundNor and zero NormalSize are unconditional failures",
        },
        "falsifiable_hypothesis": {
            "statement": "The fresh v1 GeometryForNormals layer offsets do not match the active mainlist boundary shells. Mirroring the mainlist layer offsets 0,-1,-2 for both the outer tank and all four gate-frame boxes should provide normals for the boundary layers without changing the physical slots or source.",
            "changed_contract": {
                "outer_normal_layers_vdp": "0,-1,-2",
                "gate_frame_normal_layers_vdp": "0,-1,-2",
                "mainlist_outer_layers_vdp": "0,-1,-2",
                "mainlist_gate_frame_layers_vdp": "0,-1,-2",
                "normal_distance_h": 3.0,
                "normal_shape_mode": "actual | bound",
                "normal_surface_output": "hdp",
            },
            "unchanged_contract": [
                "two slot centers and slot width grid",
                "solid central web and four frame boxes",
                "source lattice, native mass policy and 2.5% source mass gate",
                "1.5 s window, 0.01 s output cadence and 15-row denominator",
            ],
            "prediction_status": "unexecuted; only root review may authorize fresh Definition materialization",
        },
        "fixed_matrix": {"planned_rows": 15, "spatial_rows": 13, "temporal_rows": 2, "all_rows_retained": True, "qualification_credit": 0},
        "hard_preflight_gates": {
            "zero_boundnor_count_max": 0,
            "zero_normal_size_count_max": 0,
            "zero_normal_norm_threshold_m": 1.0e-12,
            "ids_unique_and_xml_aligned": True,
            "fluid_ids_match_xml": True,
            "arrays_finite": True,
            "fluid_boundary_overlap_count_max": 0,
            "outer_endpoint_count_max": 0,
            "gate_endpoint_penetration_count_max": 0,
            "saved_initial_chord_crossing_count_max": 0,
            "source_mass_relative_error_max": 0.025,
            "total_mass_relative_error_max": 0.03,
            "threshold_relaxation": False,
            "survivor_renormalization": False,
        },
        "authorization_boundary": {
            "status": "proposal_only_no_runtime_authority",
            "definition_writer_authorized": False,
            "cpu_native_authorized": False,
            "solver": False,
            "gpu": False,
            "queue": False,
            "ledger": False,
            "registry": False,
            "matrix_submission": False,
            "core_gate_changed": False,
            "qualification_credit_added": 0,
            "next_allowed_action": "root review of this single new normal-layer hypothesis",
        },
        "hash_bindings": {
            "parent_proposal": ref(PARENT_PROPOSAL, "v1 distributed-slot physical scope proposal"),
            "parent_root_review": ref(PARENT_REVIEW, "v1 root review"),
            "negative_evidence": ref(NEGATIVE, "v1 CPU/native hard negative evidence"),
            "proposal_implementation": ref(Path(__file__), "v2 root-review-only proposal builder"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proposal, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return proposal


def verify(path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != SCHEMA or value.get("revision_id") != REVISION_ID or value.get("candidate_case_id") != CASE_ID:
        raise ValueError("v2 proposal identity mismatch")
    if value.get("matrix_credit") != 0 or value.get("authorization_boundary", {}).get("definition_writer_authorized") is not False:
        raise ValueError("v2 proposal carries runtime credit")
    for item in value.get("hash_bindings", {}).values():
        path_value = Path(item["path"])
        if item.get("sha256") != sha256(path_value) or item.get("bytes") != path_value.stat().st_size:
            raise ValueError("v2 proposal hash binding is stale")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = build(args.output) if args.command == "build" else verify(args.output)
    print(json.dumps({"status": result["status"], "revision_id": result["revision_id"], "matrix_credit": result["matrix_credit"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
