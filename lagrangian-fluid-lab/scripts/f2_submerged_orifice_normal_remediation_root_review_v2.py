#!/usr/bin/env python3
"""Read-only root review receipt for the v2 normal remediation proposal.

This module verifies the hash-bound v2 candidate and its parent scope.  It
never writes a Definition, reads the failed anchor BI4, invokes GenCase or the
native decoder, launches a solver/GPU, or mutates job/queue/ledger/registry
state.  The current decision intentionally keeps runtime authorization closed
until a fresh literal Definition writer exists and is reviewed.
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
    load_json,
    verify_bundle,
)
from scripts.f2_submerged_orifice_normal_remediation_v2 import (  # noqa: E402
    CASE_ID as REMEDIATION_CASE_ID,
    DEFAULT_AUDIT,
    DEFAULT_CANDIDATE,
    DEFAULT_CONTRACT,
    DEFAULT_PROPOSAL,
    SCHEMA_CANDIDATE,
    SCHEMA_CONTRACT,
    SCHEMA_PROPOSAL,
    verify_contract,
)


SCHEMA = "core.f2.submerged_orifice_transfer.normal_remediation.root_review_receipt.v2"
REVIEW_ID = "F2_SUBMERGED_ORIFICE_NORMAL_REMEDIATION_ROOT_REVIEW_V2"
CREATED_AT = "2026-09-21T00:00:00+00:00"
PARENT_CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial"
PARENT_PREFLIGHT_SCHEMA = "core.f2.submerged_orifice_transfer.cpu_native_preflight.v1"
ZERO_NORMAL_COUNT = 63161
ZERO_NORMAL_TOLERANCE_M = 1.0e-12
DEFAULT_RECEIPT = DEFAULT_BASE / "normal-remediation-v2/root-review-receipt-v2.json"


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


def _verify_ref(item: dict[str, Any], label: str, expected_path: Path | None = None) -> Path:
    path = Path(item.get("path", "")).resolve()
    if expected_path is not None and path != Path(expected_path).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path):
        raise ValueError(f"{label}: SHA mismatch")
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


def _static_bindings(base: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    p = _paths(base)
    return {
        "v2_candidate": _ref(DEFAULT_CANDIDATE, "v2 normal remediation candidate"),
        "v2_cpu_preflight_proposal": _ref(DEFAULT_PROPOSAL, "v2 CPU-only preflight proposal"),
        "v2_root_review_only_contract": _ref(DEFAULT_CONTRACT, "v2 root-review-only contract"),
        "boundnor_partition_audit": _ref(DEFAULT_AUDIT, "read-only Bound.vtk partition audit"),
        "v2_review_adapter": _ref(Path(__file__).resolve(), "v2 root-review adapter"),
        "v2_partition_adapter": _ref(LAB_ROOT / "scripts/f2_submerged_orifice_boundnor_partition_audit_v1.py", "v2 partition adapter"),
        "v2_remediation_adapter": _ref(LAB_ROOT / "scripts/f2_submerged_orifice_normal_remediation_v2.py", "v2 remediation adapter"),
        "v2_review_test": _ref(LAB_ROOT / "tests/test_f2_submerged_orifice_normal_remediation_v2.py", "v2 contract test"),
        "parent_scope_adapter": _ref(LAB_ROOT / "scripts/f2_submerged_orifice_scope_v1.py", "parent scope adapter"),
        "parent_scope_test": _ref(LAB_ROOT / "tests/test_f2_submerged_orifice_scope_v1.py", "parent scope test"),
        "parent_preflight_adapter": _ref(LAB_ROOT / "scripts/f2_submerged_orifice_preflight_v1.py", "failed-anchor preflight adapter"),
        "parent_preflight_test": _ref(LAB_ROOT / "tests/test_f2_submerged_orifice_preflight_v1.py", "failed-anchor preflight test"),
        "parent_candidate": _ref(p["candidate"], "parent candidate card"),
        "parent_matrix": _ref(p["matrix"], "parent fixed 15-row matrix"),
        "parent_failure_denominator": _ref(p["failure"], "parent full failure denominator"),
        "parent_lineage": _ref(p["lineage"], "parent lineage clarification"),
        "parent_root_contract": _ref(p["contract"], "parent root-review-only contract"),
        "failed_anchor_preflight": _ref(p["failed_preflight"], "failed anchor noncredit preflight evidence"),
    }


def _review_inputs(base: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    p = _paths(base)
    parent = verify_bundle(base)
    if parent.get("status") != "root_review_only_contract_verified":
        raise ValueError("parent scope bundle is not verified")
    if parent.get("fixed_matrix", {}).get("rows") != EXPECTED_ROWS:
        raise ValueError("parent matrix does not retain all 15 rows")
    if parent.get("fixed_matrix", {}).get("all_not_started") is not True:
        raise ValueError("parent matrix contains a started row")
    if parent.get("failure_denominator", {}).get("planned") != EXPECTED_ROWS:
        raise ValueError("parent denominator planned count changed")
    if parent.get("failure_denominator", {}).get("credit") != 0:
        raise ValueError("parent denominator credit is nonzero")
    lineage = load_json(p["lineage"])
    source_policy = lineage.get("source_asset_policy", {})
    if (source_policy.get("old_failed_definition_reused") is not False
            or source_policy.get("old_failed_trajectory_reused") is not False):
        raise ValueError("parent lineage permits source reuse")
    if any(item.get("historical_execution_reused") is True
           or item.get("same_input_retry") is True
           for item in lineage.get("comparison_and_noninheritance", [])):
        raise ValueError("parent lineage comparison permits historical reuse")
    failed = load_json(p["failed_preflight"])
    if failed.get("schema") != PARENT_PREFLIGHT_SCHEMA:
        raise ValueError("failed anchor preflight schema mismatch")
    if failed.get("case_id") != PARENT_CASE_ID or failed.get("preflight_pass") is not False:
        raise ValueError("failed anchor evidence identity/status changed")
    if failed.get("native_initial", {}).get("zero_boundary_normals") != ZERO_NORMAL_COUNT:
        raise ValueError("failed anchor zero-normal count changed")
    if failed.get("matrix_credit") != 0 or failed.get("qualification_claim") != "none":
        raise ValueError("failed anchor evidence contains credit")

    verify_contract(DEFAULT_CONTRACT, base, DEFAULT_AUDIT, DEFAULT_CANDIDATE, DEFAULT_PROPOSAL)
    audit = load_json(DEFAULT_AUDIT)
    if audit.get("generated_field_summary", {}).get("global_zero_normal_count") != ZERO_NORMAL_COUNT:
        raise ValueError("v2 partition audit is stale")
    audit_scope = audit.get("input_scope", {})
    for key in ("definition_read", "bi4_read", "native_decoder_invoked", "gencase_invoked", "solver_invoked", "gpu_invoked"):
        if audit_scope.get(key) is not False:
            raise ValueError(f"partition audit opened prohibited path: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if audit_scope.get(key) != 0:
            raise ValueError(f"partition audit mutated state: {key}")

    candidate = load_json(DEFAULT_CANDIDATE)
    proposal = load_json(DEFAULT_PROPOSAL)
    contract = load_json(DEFAULT_CONTRACT)
    if candidate.get("schema") != SCHEMA_CANDIDATE or candidate.get("new_input_identity", {}).get("case_id") != REMEDIATION_CASE_ID:
        raise ValueError("v2 candidate identity is not bound")
    if proposal.get("schema") != SCHEMA_PROPOSAL or proposal.get("case_id") != REMEDIATION_CASE_ID:
        raise ValueError("v2 proposal identity is not bound")
    if contract.get("schema") != SCHEMA_CONTRACT or contract.get("authorized_runtime_preparation") is not False:
        raise ValueError("v2 parent contract is not root-review-only")
    if proposal.get("status") != "root_review_only_cpu_preflight_proposal_not_run":
        raise ValueError("v2 proposal unexpectedly ran")
    fresh = proposal.get("fresh_definition", {})
    if fresh.get("required") is not True or fresh.get("reuse_failed_anchor_definition") is not False or fresh.get("reuse_failed_anchor_bi4") is not False:
        raise ValueError("v2 proposal does not enforce fresh input identity")
    proposed = proposal.get("proposed_execution", {})
    if proposed.get("cpu_gencase") is not True or proposed.get("native_decode") is not True:
        raise ValueError("v2 proposal omitted CPU/native scope")
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if proposed.get(key) is not False:
            raise ValueError(f"v2 proposal opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if proposed.get(key) != 0:
            raise ValueError(f"v2 proposal opened {key}")
    if candidate.get("hard_preflight_gates", {}).get("zero_normal_count_max") != 0:
        raise ValueError("v2 candidate relaxed the zero-normal gate")
    if candidate.get("denominator_preservation", {}).get("planned_rows") != EXPECTED_ROWS:
        raise ValueError("v2 candidate denominator changed")
    return {
        "parent_bundle": parent,
        "parent_lineage": lineage,
        "failed_anchor": failed,
        "v2_candidate": candidate,
        "v2_proposal": proposal,
        "v2_contract": contract,
        "v2_audit": audit,
    }


def build_receipt(base: Path = DEFAULT_BASE, output: Path = DEFAULT_RECEIPT) -> dict[str, Any]:
    base = Path(base).resolve()
    reviewed = _review_inputs(base)
    bindings = _static_bindings(base)
    receipt = {
        "schema": SCHEMA,
        "review_id": REVIEW_ID,
        "created_at_utc": CREATED_AT,
        "scope_id": reviewed["parent_bundle"]["scope_id"],
        "parent_revision_id": reviewed["parent_bundle"]["revision_id"],
        "reviewed_revision_id": reviewed["v2_candidate"]["revision_id"],
        "decision": "not_authorized_pending_fresh_definition_writer",
        "status": "hash_review_passed_runtime_authority_closed",
        "authorized_for_one_fresh_cpu_native_preflight": False,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "authorized_case_id": REMEDIATION_CASE_ID,
        "authorized_matrix_index": 4,
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
        "hash_review": {
            "all_bindings_current": True,
            "parent_matrix_rows": EXPECTED_ROWS,
            "parent_matrix_all_not_started": True,
            "parent_denominator_planned": EXPECTED_ROWS,
            "parent_denominator_credit": 0,
            "parent_lineage_source_reuse": False,
            "failed_anchor_preflight_pass": False,
            "failed_anchor_zero_boundary_normals": ZERO_NORMAL_COUNT,
            "v2_boundnor_audit_zero_normals": ZERO_NORMAL_COUNT,
            "v2_zero_normal_hard_threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "v2_old_definition_reuse": False,
            "v2_old_bi4_reuse": False,
            "v2_proposal_status": reviewed["v2_proposal"]["status"],
        },
        "hash_bindings": bindings,
        "blockers": [
            "v2 is a recipe/proposal only; no fresh literal Definition writer is hash-bound to this review",
            "v2 has no fresh generated XML, native BI4, or CPU/native preflight result",
            "the parent anchor remains a hard zero-normal failure with 63,161 zero vectors",
            "the static Bound.vtk partition diagnoses the failure but cannot prove that v2 generates complete normals",
        ],
        "future_single_preflight_conditions": {
            "fresh_definition_case_id": REMEDIATION_CASE_ID,
            "fresh_definition_required": True,
            "cpu_gencase_only_after_new_review": True,
            "native_decode_only_after_new_review": True,
            "solver_gpu_queue_ledger_registry_forbidden": True,
            "zero_normal_count_must_equal": 0,
            "zero_normal_threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "qualification_credit": 0,
        },
        "failure_denominator": {
            "planned_rows": EXPECTED_ROWS,
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "unattempted_rows": EXPECTED_ROWS,
            "qualification_numerator": 0,
            "same_input_retry": False,
            "threshold_relaxation": False,
            "survivor_renormalization": False,
        },
        "execution_controls": {
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
        "core_gate_effect": {
            "new_t1_family": False,
            "qualification_credit": 0,
            "core_can_finalize_changed": False,
        },
        "required_next_step": "implement and hash-bind a fresh literal v2 Definition writer, then request a new root review; do not run CPU/native preparation under this receipt",
    }
    write_json(output, receipt)
    return receipt


def verify_receipt(receipt_path: Path = DEFAULT_RECEIPT, base: Path = DEFAULT_BASE) -> dict[str, Any]:
    receipt = load_json(Path(receipt_path).resolve())
    if receipt.get("schema") != SCHEMA:
        raise ValueError("root-review receipt schema mismatch")
    if receipt.get("decision") != "not_authorized_pending_fresh_definition_writer":
        raise ValueError("receipt unexpectedly authorizes execution")
    if receipt.get("authorized_for_one_fresh_cpu_native_preflight") is not False:
        raise ValueError("receipt opened CPU/native authority")
    auth = receipt.get("authorization", {})
    for key in ("cpu_gencase", "native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"receipt opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"receipt opened {key}")
    expected = _static_bindings(Path(base).resolve())
    bindings = receipt.get("hash_bindings", {})
    for key, value in expected.items():
        actual = bindings.get(key, {})
        _verify_ref(actual, f"receipt {key}", Path(value["path"]))
        if actual.get("sha256") != value["sha256"]:
            raise ValueError(f"receipt {key} stale")
    if receipt.get("failure_denominator", {}).get("planned_rows") != EXPECTED_ROWS:
        raise ValueError("receipt denominator does not retain 15 rows")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-receipt", "verify-receipt"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args(argv)
    result = build_receipt(args.base, args.output) if args.command == "write-receipt" else verify_receipt(args.output, args.base)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
