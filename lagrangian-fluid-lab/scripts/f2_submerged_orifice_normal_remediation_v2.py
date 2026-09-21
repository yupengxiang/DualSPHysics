#!/usr/bin/env python3
"""Build and verify a root-review-only v2 normal remediation contract.

The v2 identity is a new prepared-input proposal.  It is derived from the
read-only ``*_Bound.vtk`` partition audit, but it never reads or reuses the
failed anchor Definition/BI4 and never runs GenCase, the decoder, a solver, or
any job/queue/ledger/registry path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.f2_submerged_orifice_scope_v1 import (  # noqa: E402
    DEFAULT_BASE,
    EXPECTED_ROWS,
    REVISION_ID as PARENT_REVISION_ID,
    SCOPE_ID,
    load_json,
    verify_bundle,
)
from scripts.f2_submerged_orifice_boundnor_partition_audit_v1 import (  # noqa: E402
    DEFAULT_OUTPUT as DEFAULT_AUDIT,
)


REVISION_ID = "F2_submerged_orifice_normal_remediation_v2"
CANDIDATE_ID = "F2_submerged_orifice_normal_remediation_q0p5_anchor_v2"
CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2"
SCHEMA_CANDIDATE = "core.f2.submerged_orifice_transfer.normal_remediation_candidate.v2"
SCHEMA_PROPOSAL = "core.f2.submerged_orifice_transfer.cpu_preflight_proposal.v2"
SCHEMA_CONTRACT = "core.f2.submerged_orifice_transfer.normal_remediation.root_review_only.v2"
CREATED_AT = "2026-09-21T00:00:00+00:00"
ANCHOR_INDEX = 4
ANCHOR_Q = 0.5
ANCHOR_DP = 0.0075
ORIFICE_HEIGHT = 0.18
DP_M = ANCHOR_DP
ZERO_TOLERANCE_M = 1.0e-12
NORMAL_DISTANCE_H = 3.0

DEFAULT_REMEDIATION = DEFAULT_BASE / "normal-remediation-v2"
DEFAULT_CANDIDATE = DEFAULT_REMEDIATION / "normal-remediation-candidate-v2.json"
DEFAULT_PROPOSAL = DEFAULT_REMEDIATION / "cpu-preflight-proposal-v2.json"
DEFAULT_CONTRACT = DEFAULT_REMEDIATION / "root-review-only-contract-v2.json"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _verify_ref(item: dict[str, Any], label: str) -> Path:
    path = Path(item.get("path", "")).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path):
        raise ValueError(f"{label}: hash mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: byte count mismatch")
    return path


def _paths(base: Path) -> dict[str, Path]:
    return {
        "candidate": base / "candidate-card-v1.json",
        "matrix": base / "fixed-matrix-v1.json",
        "failure": base / "failure-denominator-v1.json",
        "lineage": base / "lineage-clarification-v1.json",
        "contract": base / "root-review-contract-v1.json",
        "failed_preflight": base / "anchor-q0p5-dp0p0075/preflight.json",
    }


def _parent_bindings(base: Path, audit: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    paths = _paths(base)
    bundle = verify_bundle(base)
    if bundle["status"] != "root_review_only_contract_verified":
        raise ValueError("parent candidate bundle is not independently verified")
    denominator = load_json(paths["failure"])
    if denominator.get("planned") != EXPECTED_ROWS or denominator.get("credit") != 0:
        raise ValueError("parent failure denominator is not the full zero-credit denominator")
    return {
        "parent_candidate_card": _ref(paths["candidate"], "parent submerged-orifice candidate"),
        "parent_fixed_matrix": _ref(paths["matrix"], "parent 15-row fixed matrix"),
        "parent_failure_denominator": _ref(paths["failure"], "parent full zero-credit denominator"),
        "parent_lineage": _ref(paths["lineage"], "parent lineage clarification"),
        "parent_root_contract": _ref(paths["contract"], "parent root-review-only contract"),
        "failed_anchor_preflight_evidence": _ref(paths["failed_preflight"], "failed anchor noncredit evidence"),
        "boundnor_partition_audit": _ref(audit, "read-only generated Bound.vtk partition audit"),
        "remediation_adapter": _ref(Path(__file__).resolve(), "normal remediation contract adapter"),
    }


def _assert_audit(audit_path: Path) -> dict[str, Any]:
    audit = load_json(audit_path)
    if audit.get("schema") != "core.f2.submerged_orifice_transfer.boundnor_partition_audit.v1":
        raise ValueError("normal partition audit schema mismatch")
    if audit.get("case_id") != "F2_ORIFICE_q0p50_dp0075_spatial":
        raise ValueError("partition audit is not for the failed anchor")
    scope = audit.get("input_scope", {})
    for key in ("definition_read", "bi4_read", "native_decoder_invoked", "gencase_invoked", "solver_invoked", "gpu_invoked"):
        if scope.get(key) is not False:
            raise ValueError(f"partition audit reopened prohibited input/runtime: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if scope.get(key) != 0:
            raise ValueError(f"partition audit mutated protected state: {key}")
    summary = audit.get("generated_field_summary", {})
    if summary.get("global_zero_normal_count") != 63161:
        raise ValueError("partition audit no longer binds the observed hard failure")
    partitions = {int(row["mk"]): row for row in audit.get("mk_partitions", [])}
    if partitions.get(17, {}).get("zero_normal_count") != 43526:
        raise ValueError("outer Mk zero-normal partition changed")
    if partitions.get(18, {}).get("zero_normal_count") != 19635:
        raise ValueError("gate Mk zero-normal partition changed")
    return audit


def _geometry_contract() -> dict[str, Any]:
    return {
        "physical_geometry_identity": {
            "outer_tank_low_m": [0.0, 0.0, 0.0],
            "outer_tank_size_m": [1.6, 0.5, 0.8],
            "upper_gate_physical_low_m": [0.72, 0.04, ORIFICE_HEIGHT],
            "upper_gate_physical_size_m": [0.06, 0.42, 0.62],
            "source_low_m": [0.04, 0.04, 0.04],
            "source_size_m": [0.64, 0.42, 0.36],
            "physical_scene_changed": False,
        },
        "normal_geometry_list": {
            "outer_boxfill": "all^top",
            "outer_mkbound": 0,
            "outer_setnormalinvert": True,
            "outer_layers_vdp": "0",
            "gate_boxfill": "bottom | top | left | right | front | back",
            "gate_mkbound": 1,
            "gate_setnormalinvert": False,
            "gate_layers_vdp": "0",
            "shapeout": "hdp",
            "distanceh": NORMAL_DISTANCE_H,
            "svshapes": True,
            "change_reason": "cover the boundary center layer directly; the failed -0.5 source left inner layers with zero generated vectors",
        },
        "mainlist_boundary_contract": {
            "outer_layers_vdp": "0,1,2",
            "gate_void_precursor": {
                "setmkvoid": True,
                "low_m": [0.71625, 0.03625, 0.17625],
                "size_m": [0.0675, 0.4275, 0.6275],
                "formula": "physical gate low - dp/2; physical gate size + dp",
            },
            "gate_boundary_shell": {
                "low_m": [0.72375, 0.04375, 0.18375],
                "size_m": [0.0525, 0.4125, 0.6125],
                "layers_vdp": "0,-1,-2",
                "formula": "physical gate low + dp/2; physical gate size - dp",
            },
            "gate_shell_side": "solid_side_with_void_precursor",
            "old_gate_layers_reused": False,
        },
    }


def build_candidate(base: Path = DEFAULT_BASE, audit_path: Path = DEFAULT_AUDIT,
                    output: Path = DEFAULT_CANDIDATE) -> dict[str, Any]:
    audit_path = Path(audit_path).resolve()
    audit = _assert_audit(audit_path)
    bindings = _parent_bindings(Path(base), audit_path)
    candidate = {
        "schema": SCHEMA_CANDIDATE,
        "created_at_utc": CREATED_AT,
        "family": "F2",
        "scope_id": SCOPE_ID,
        "parent_revision_id": PARENT_REVISION_ID,
        "revision_id": REVISION_ID,
        "candidate_id": CANDIDATE_ID,
        "candidate_status": "root_review_only_no_cpu_preflight",
        "qualification_claim": "none",
        "qualified": False,
        "T1_numerical": False,
        "matrix_credit": 0,
        "repair_class": "mdbc_generated_normal_coverage",
        "new_input_identity": {
            "case_id": CASE_ID,
            "fresh_definition_required": True,
            "fresh_generated_prefix_required": True,
            "old_anchor_definition_reused": False,
            "old_anchor_bi4_reused": False,
            "old_anchor_trajectory_reused": False,
        },
        "observed_failure": {
            "source_audit_schema": audit["schema"],
            "global_zero_normal_count": audit["generated_field_summary"]["global_zero_normal_count"],
            "global_zero_fraction": audit["generated_field_summary"]["global_zero_fraction"],
            "outer_mk17_zero_normal_count": 43526,
            "gate_mk18_zero_normal_count": 19635,
            "hard_gate": "zero Boundary normal vectors remain an unconditional failure at norm <= 1e-12 m",
        },
        "boundary_hypothesis": {
            "statement": "The inner boundary particle layers need an explicit center-layer normal source and the internal gate shell must be built on its solid side with a void precursor.",
            "new_relative_to_failed_anchor": [
                "GeometryForNormals changes from vdp=-0.5 to vdp=0 for both registered Mk roles.",
                "Outer normal coverage uses all^top to make the five closed tank faces explicit as one normal source.",
                "The gate mainlist adds an expanded setmkvoid precursor and changes the gate shell to vdp=0,-1,-2.",
                "A fresh literal Definition and fresh generated/native prefix are required; no failed anchor asset is an input.",
            ],
        },
        "geometry_and_normal_contract": _geometry_contract(),
        "hard_preflight_gates": {
            "generated_boundnor_count_equals_boundary_count": True,
            "zero_normal_count_max": 0,
            "zero_normal_threshold_m": ZERO_TOLERANCE_M,
            "normal_size_zero_count_max": 0,
            "arrays_finite": True,
            "ids_unique_and_native_xml_aligned": True,
            "outer_wall_endpoint_count_max": 0,
            "gate_endpoint_penetration_count_max": 0,
            "native_mass_relative_error_max": 0.025,
            "solver_product_present": False,
            "threshold_relaxation": False,
        },
        "denominator_preservation": {
            "planned_rows": EXPECTED_ROWS,
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "unattempted_rows": EXPECTED_ROWS,
            "qualification_numerator": 0,
            "all_rows_retained": True,
            "same_input_retry": False,
            "survivor_renormalization": False,
            "old_anchor_preflight_credit": 0,
        },
        "hash_bindings": bindings,
        "prohibited_actions": [
            "do not modify or rerun the failed anchor",
            "do not read or reuse the failed anchor Definition or BI4 for v2",
            "do not launch solver or GPU",
            "do not create a job or mutate queue, ledger, or registry",
            "do not relax zero-normal threshold or remove failed rows",
        ],
        "core_gate_effect": {
            "new_t1_family": False,
            "qualification_credit": 0,
            "core_can_finalize_changed": False,
        },
    }
    write_json(output, candidate)
    return candidate


def build_proposal(base: Path = DEFAULT_BASE, audit_path: Path = DEFAULT_AUDIT,
                   output: Path = DEFAULT_PROPOSAL) -> dict[str, Any]:
    audit = _assert_audit(Path(audit_path).resolve())
    bindings = _parent_bindings(Path(base), Path(audit_path).resolve())
    proposal = {
        "schema": SCHEMA_PROPOSAL,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "parent_revision_id": PARENT_REVISION_ID,
        "revision_id": REVISION_ID,
        "status": "root_review_only_cpu_preflight_proposal_not_run",
        "authorized_now": False,
        "case_id": CASE_ID,
        "q": ANCHOR_Q,
        "dp_m": ANCHOR_DP,
        "orifice_height_m": ORIFICE_HEIGHT,
        "fresh_definition": {
            "required": True,
            "path": str((DEFAULT_REMEDIATION / f"{CASE_ID}_Def.xml").resolve()),
            "literal_recipe_required": True,
            "reuse_failed_anchor_definition": False,
            "reuse_failed_anchor_bi4": False,
        },
        "fresh_generated_prefix": str((DEFAULT_REMEDIATION / "generated" / CASE_ID).resolve()),
        "proposed_execution": {
            "cpu_gencase": True,
            "native_decode": True,
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "preflight_order": [
            "root review this v2 candidate, audit, proposal, and all hash bindings",
            "if separately authorized, write a fresh literal Definition at the new path",
            "run CPU GenCase once for the new identity only",
            "decode only the new native BI4 and audit IDs, finite arrays, BoundNor count, zero normals, mass, and geometry",
            "stop with zero credit on any hard-gate failure; no solver decision follows automatically",
        ],
        "required_hard_results": {
            "zero_normal_count": 0,
            "zero_normal_norm_threshold_m": ZERO_TOLERANCE_M,
            "normal_size_zero_count": 0,
            "native_mass_relative_error_max": 0.025,
            "outer_wall_endpoint_count": 0,
            "gate_endpoint_penetration_count": 0,
            "qualification_credit": 0,
        },
        "denominator": {
            "planned": EXPECTED_ROWS,
            "executed": 0,
            "failed": 0,
            "unattempted": EXPECTED_ROWS,
            "credit": 0,
            "threshold_relaxation": False,
            "same_input_retry": False,
        },
        "source_partition_audit": {
            "path": str(Path(audit_path).resolve()),
            "sha256": sha256(Path(audit_path)),
            "global_zero_normal_count": audit["generated_field_summary"]["global_zero_normal_count"],
        },
        "hash_bindings": bindings,
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
    }
    write_json(output, proposal)
    return proposal


def build_contract(base: Path = DEFAULT_BASE, audit_path: Path = DEFAULT_AUDIT,
                   candidate_path: Path = DEFAULT_CANDIDATE,
                   proposal_path: Path = DEFAULT_PROPOSAL,
                   output: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    base = Path(base).resolve()
    audit_path = Path(audit_path).resolve()
    candidate_path = Path(candidate_path).resolve()
    proposal_path = Path(proposal_path).resolve()
    audit = _assert_audit(audit_path)
    candidate = load_json(candidate_path)
    proposal = load_json(proposal_path)
    if (candidate.get("schema") != SCHEMA_CANDIDATE
            or candidate.get("new_input_identity", {}).get("case_id", "") != CASE_ID):
        raise ValueError("v2 candidate identity is invalid")
    if proposal.get("schema") != SCHEMA_PROPOSAL or proposal.get("case_id", "") != CASE_ID:
        raise ValueError("v2 proposal identity is invalid")
    parent = _parent_bindings(base, audit_path)
    contract = {
        "schema": SCHEMA_CONTRACT,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "parent_revision_id": PARENT_REVISION_ID,
        "revision_id": REVISION_ID,
        "decision": "candidate_contract_only_root_review_required",
        "status": "prepared_design_only_cpu_not_authorized",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "authorized_anchor": False,
        "authorized_runtime_preparation": False,
        "authorization": {
            "cpu_gencase": False,
            "native_decode": False,
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
        },
        "repair_review": {
            "new_input_identity": CASE_ID,
            "new_normal_geometry_contract": True,
            "current_anchor_modified": False,
            "current_anchor_rerun": False,
            "current_anchor_definition_reused": False,
            "current_anchor_bi4_reused": False,
            "current_anchor_trajectory_reused": False,
            "zero_t1_credit": True,
            "full_failure_denominator_preserved": True,
        },
        "hash_bindings": {
            "v2_candidate": _ref(candidate_path, "new v2 repair candidate"),
            "v2_cpu_preflight_proposal": _ref(proposal_path, "new CPU-only preflight proposal"),
            "boundnor_partition_audit": _ref(audit_path, "read-only generated Bound.vtk partition audit"),
            "remediation_adapter": _ref(Path(__file__).resolve(), "normal remediation contract adapter"),
            **parent,
        },
        "failure_denominator": {
            "planned_rows": EXPECTED_ROWS,
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "unattempted_rows": EXPECTED_ROWS,
            "qualification_numerator": 0,
            "threshold_relaxation": False,
            "same_input_retry": False,
            "survivor_renormalization": False,
        },
        "preflight": {
            "status": "not_run",
            "fresh_definition_present": False,
            "fresh_native_bi4_present": False,
            "solver_product_present": False,
            "cpu_native_credit": 0,
        },
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
        "required_next_step": "root review the v2 hash-bound contract; no CPU/native preparation is authorized by this artifact",
        "prohibited_until_new_root_authorization": [
            "GenCase", "native decoder", "solver", "GPU", "job creation", "queue", "ledger", "registry", "matrix expansion",
        ],
        "blockers": [
            "The parent anchor has 63,161 hard zero BoundNor vectors and remains failed.",
            "No new Definition or native input is produced in this proposal.",
            "Zero-normal hard gate remains exact at norm <= 1e-12 m; no threshold relaxation is allowed.",
        ],
    }
    write_json(output, contract)
    return contract


def verify_contract(contract_path: Path = DEFAULT_CONTRACT,
                    base: Path = DEFAULT_BASE,
                    audit_path: Path = DEFAULT_AUDIT,
                    candidate_path: Path = DEFAULT_CANDIDATE,
                    proposal_path: Path = DEFAULT_PROPOSAL) -> dict[str, Any]:
    contract = load_json(Path(contract_path).resolve())
    if contract.get("schema") != SCHEMA_CONTRACT:
        raise ValueError("v2 root-review contract schema mismatch")
    if contract.get("decision") != "candidate_contract_only_root_review_required":
        raise ValueError("v2 contract unexpectedly authorizes execution")
    if contract.get("matrix_credit") != 0 or contract.get("qualification_claim") != "none":
        raise ValueError("v2 contract has nonzero credit")
    if contract.get("authorized_anchor") is not False or contract.get("authorized_runtime_preparation") is not False:
        raise ValueError("v2 contract opened runtime authority")
    auth = contract.get("authorization", {})
    for key in ("cpu_gencase", "native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"v2 contract opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"v2 contract opened {key}")
    bindings = contract.get("hash_bindings", {})
    expected_paths = {
        "v2_candidate": Path(candidate_path),
        "v2_cpu_preflight_proposal": Path(proposal_path),
        "boundnor_partition_audit": Path(audit_path),
        "remediation_adapter": Path(__file__),
    }
    for key, path in expected_paths.items():
        item = bindings.get(key, {})
        _verify_ref(item, f"v2 contract {key}")
        if Path(item["path"]).resolve() != path.resolve():
            raise ValueError(f"v2 contract {key} path changed")
    # The parent bundle is reverified and every parent binding is hash-checked;
    # no current anchor Definition or BI4 path is accepted here.
    parent_expected = _parent_bindings(Path(base), Path(audit_path).resolve())
    for key in parent_expected:
        item = bindings.get(key, {})
        _verify_ref(item, f"v2 contract {key}")
        if item.get("sha256") != parent_expected[key]["sha256"]:
            raise ValueError(f"v2 contract {key} is stale")
    forbidden_text = json.dumps(contract, sort_keys=True)
    if "_Def.xml" in forbidden_text or ".bi4" in forbidden_text:
        raise ValueError("v2 contract must not bind a failed Definition or BI4 as an input")
    if contract.get("failure_denominator", {}).get("planned_rows") != EXPECTED_ROWS:
        raise ValueError("v2 contract denominator is not the full 15-row denominator")
    return contract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-candidate", "write-proposal", "write-contract", "verify-contract"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write-candidate":
        result = build_candidate(args.base, args.audit, args.output or args.candidate)
    elif args.command == "write-proposal":
        result = build_proposal(args.base, args.audit, args.output or args.proposal)
    elif args.command == "write-contract":
        result = build_contract(args.base, args.audit, args.candidate, args.proposal, args.output or DEFAULT_CONTRACT)
    else:
        result = verify_contract(args.output or DEFAULT_CONTRACT, args.base, args.audit, args.candidate, args.proposal)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
