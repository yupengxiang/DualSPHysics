#!/usr/bin/env python3
"""Read-only v3 root-review proposal for the fresh v2 Definition.

The v3 receipt confirms the new literal Definition and its static contract,
but deliberately keeps CPU/native and all runtime permissions closed.  It
does not invoke GenCase/native decoding or touch the failed anchor/runtime.
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
from scripts.f2_submerged_orifice_normal_remediation_root_review_v2 import (  # noqa: E402
    DEFAULT_RECEIPT as V2_ROOT_RECEIPT,
    verify_receipt as verify_v2_root_receipt,
)
from scripts.f2_submerged_orifice_definition_writer_v2 import (  # noqa: E402
    CASE_ID,
    DEFAULT_CONTRACT as FRESH_CONTRACT,
    DEFAULT_DEFINITION as FRESH_DEFINITION,
    DEFAULT_PROPOSAL as FRESH_PROPOSAL,
    inspect_definition,
    verify_contract as verify_fresh_contract,
)
from scripts.f2_submerged_orifice_normal_remediation_v2 import (  # noqa: E402
    DEFAULT_AUDIT,
    DEFAULT_CANDIDATE,
    DEFAULT_CONTRACT as V2_CONTRACT,
    DEFAULT_PROPOSAL as V2_PROPOSAL,
    REVISION_ID,
)


SCHEMA = "core.f2.submerged_orifice_transfer.definition_root_review_receipt.v3"
REVIEW_ID = "F2_SUBMERGED_ORIFICE_DEFINITION_ROOT_REVIEW_V3"
CREATED_AT = "2026-09-21T00:00:00+00:00"
DEFAULT_RECEIPT = DEFAULT_BASE / "normal-remediation-v2/root-review-receipt-v3.json"
PARENT_CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial"
ZERO_NORMAL_COUNT = 63161
ZERO_NORMAL_TOLERANCE_M = 1.0e-12


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


def _verify_ref(item: dict[str, Any], label: str, expected_path: Path) -> None:
    path = Path(item.get("path", "")).resolve()
    if path != Path(expected_path).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path):
        raise ValueError(f"{label}: SHA mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: byte count mismatch")


def _parent_paths(base: Path) -> dict[str, Path]:
    base = Path(base).resolve()
    return {
        "candidate": base / "candidate-card-v1.json",
        "matrix": base / "fixed-matrix-v1.json",
        "failure": base / "failure-denominator-v1.json",
        "lineage": base / "lineage-clarification-v1.json",
        "root_contract": base / "root-review-contract-v1.json",
        "failed_preflight": base / "anchor-q0p5-dp0p0075/preflight.json",
    }


def _review_static(base: Path) -> dict[str, Any]:
    base = Path(base).resolve()
    parent = verify_bundle(base)
    p = _parent_paths(base)
    if parent.get("fixed_matrix", {}).get("rows") != EXPECTED_ROWS or parent.get("fixed_matrix", {}).get("all_not_started") is not True:
        raise ValueError("parent 15-row matrix not closed")
    if parent.get("failure_denominator", {}).get("planned") != EXPECTED_ROWS or parent.get("failure_denominator", {}).get("credit") != 0:
        raise ValueError("parent denominator not full zero-credit denominator")
    lineage = load_json(p["lineage"])
    policy = lineage.get("source_asset_policy", {})
    if policy.get("old_failed_definition_reused") is not False or policy.get("old_failed_trajectory_reused") is not False:
        raise ValueError("parent lineage permits old input reuse")
    failed = load_json(p["failed_preflight"])
    if failed.get("case_id") != PARENT_CASE_ID or failed.get("preflight_pass") is not False or failed.get("matrix_credit") != 0:
        raise ValueError("parent failed anchor evidence changed")
    if failed.get("native_initial", {}).get("zero_boundary_normals") != ZERO_NORMAL_COUNT:
        raise ValueError("parent failed anchor zero-normal count changed")
    verify_v2_root_receipt(V2_ROOT_RECEIPT, base)
    verify_fresh_contract(FRESH_CONTRACT, FRESH_PROPOSAL, FRESH_DEFINITION)
    definition = inspect_definition(FRESH_DEFINITION)
    proposal = load_json(FRESH_PROPOSAL)
    contract = load_json(FRESH_CONTRACT)
    if proposal.get("authorized_now") is not False or proposal.get("case_id") != CASE_ID:
        raise ValueError("fresh Definition proposal opened authority or changed identity")
    if contract.get("case_id") != CASE_ID or contract.get("authorization", {}).get("cpu_gencase") is not False:
        raise ValueError("fresh Definition contract opened authority or changed identity")
    audit = load_json(DEFAULT_AUDIT)
    if audit.get("generated_field_summary", {}).get("global_zero_normal_count") != ZERO_NORMAL_COUNT:
        raise ValueError("BoundNor audit stale")
    return {
        "parent": parent,
        "lineage": lineage,
        "failed": failed,
        "definition": definition,
        "proposal": proposal,
        "contract": contract,
        "audit": audit,
    }


def _bindings(base: Path) -> dict[str, Any]:
    p = _parent_paths(Path(base).resolve())
    return {
        "fresh_definition": _ref(FRESH_DEFINITION, "fresh literal v2 Definition"),
        "fresh_definition_proposal": _ref(FRESH_PROPOSAL, "fresh Definition proposal"),
        "fresh_definition_contract": _ref(FRESH_CONTRACT, "fresh Definition static contract"),
        "fresh_definition_writer": _ref(LAB_ROOT / "scripts/f2_submerged_orifice_definition_writer_v2.py", "fresh Definition writer"),
        "fresh_definition_test": _ref(LAB_ROOT / "tests/test_f2_submerged_orifice_definition_writer_v2.py", "fresh Definition test"),
        "v2_root_receipt": _ref(V2_ROOT_RECEIPT, "v2 root-review receipt"),
        "v2_root_review_adapter": _ref(LAB_ROOT / "scripts/f2_submerged_orifice_normal_remediation_root_review_v2.py", "v2 root-review adapter"),
        "v2_candidate": _ref(DEFAULT_CANDIDATE, "v2 normal remediation candidate"),
        "v2_cpu_proposal": _ref(V2_PROPOSAL, "v2 CPU proposal"),
        "v2_contract": _ref(V2_CONTRACT, "v2 normal remediation contract"),
        "boundnor_audit": _ref(DEFAULT_AUDIT, "read-only BoundNor partition audit"),
        "v2_remediation_adapter": _ref(LAB_ROOT / "scripts/f2_submerged_orifice_normal_remediation_v2.py", "v2 remediation adapter"),
        "v2_remediation_test": _ref(LAB_ROOT / "tests/test_f2_submerged_orifice_normal_remediation_v2.py", "v2 remediation test"),
        "parent_candidate": _ref(p["candidate"], "parent candidate"),
        "parent_matrix": _ref(p["matrix"], "parent 15-row matrix"),
        "parent_failure_denominator": _ref(p["failure"], "parent failure denominator"),
        "parent_lineage": _ref(p["lineage"], "parent lineage"),
        "parent_root_contract": _ref(p["root_contract"], "parent root contract"),
        "failed_anchor_preflight": _ref(p["failed_preflight"], "failed anchor preflight evidence"),
    }


def build_receipt(base: Path = DEFAULT_BASE, output: Path = DEFAULT_RECEIPT) -> dict[str, Any]:
    reviewed = _review_static(Path(base).resolve())
    receipt = {
        "schema": SCHEMA,
        "review_id": REVIEW_ID,
        "created_at_utc": CREATED_AT,
        "scope_id": reviewed["parent"]["scope_id"],
        "revision_id": REVISION_ID,
        "decision": "fresh_definition_static_review_passed_cpu_native_still_closed",
        "status": "fresh_definition_hash_bound_no_runtime_authority",
        "authorized_for_one_fresh_cpu_native_preflight": False,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "case_id": CASE_ID,
        "matrix_index": 4,
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
        "static_review": {
            "all_hash_bindings_current": True,
            "fresh_definition_contract_pass": True,
            "fresh_definition_writer_hash_bound": True,
            "fresh_definition_case_id": CASE_ID,
            "fresh_definition_sha256": sha256(FRESH_DEFINITION),
            "fresh_definition_runtime_invoked": False,
            "parent_matrix_rows": EXPECTED_ROWS,
            "parent_matrix_all_not_started": True,
            "parent_denominator_credit": 0,
            "parent_lineage_old_definition_reuse": False,
            "failed_anchor_preflight_pass": False,
            "failed_anchor_zero_boundary_normals": ZERO_NORMAL_COUNT,
            "v2_boundnor_audit_zero_normals": ZERO_NORMAL_COUNT,
            "zero_normal_hard_threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "fresh_native_bi4_present": False,
            "solver_product_present": False,
        },
        "hash_bindings": _bindings(Path(base).resolve()),
        "remaining_blockers": [
            "No GenCase/native decoder has run for the new Definition.",
            "No fresh generated XML/BI4 or native BoundNor result exists.",
            "CPU/native execution remains separately gated; this receipt does not authorize it.",
        ],
        "future_single_preflight_conditions": {
            "fresh_definition_only": True,
            "case_id": CASE_ID,
            "q": 0.5,
            "dp_m": 0.0075,
            "cpu_gencase_only": True,
            "native_decode_only": True,
            "solver_gpu_queue_ledger_registry": False,
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
            "definition_writer_invoked": True,
            "gencase_invoked": False,
            "native_decoder_invoked": False,
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
        "required_next_step": "separately review this v3 receipt before any single CPU/native preflight; no runtime is authorized here",
    }
    write_json(output, receipt)
    return receipt


def verify_receipt(receipt_path: Path = DEFAULT_RECEIPT, base: Path = DEFAULT_BASE) -> dict[str, Any]:
    receipt = load_json(Path(receipt_path).resolve())
    if receipt.get("schema") != SCHEMA or receipt.get("decision") != "fresh_definition_static_review_passed_cpu_native_still_closed":
        raise ValueError("v3 receipt schema/decision mismatch")
    if receipt.get("authorized_for_one_fresh_cpu_native_preflight") is not False:
        raise ValueError("v3 receipt opened CPU/native authority")
    auth = receipt.get("authorization", {})
    for key in ("cpu_gencase", "native_decode", "solver_launch", "gpu_launch", "job_spec_creation", "matrix_submission"):
        if auth.get(key) is not False:
            raise ValueError(f"v3 receipt opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if auth.get(key) != 0:
            raise ValueError(f"v3 receipt opened {key}")
    expected = _bindings(Path(base).resolve())
    for key, value in expected.items():
        _verify_ref(receipt.get("hash_bindings", {}).get(key, {}), f"v3 receipt {key}", Path(value["path"]))
        if receipt["hash_bindings"][key]["sha256"] != value["sha256"]:
            raise ValueError(f"v3 receipt {key} stale")
    _review_static(Path(base).resolve())
    if receipt.get("failure_denominator", {}).get("planned_rows") != EXPECTED_ROWS:
        raise ValueError("v3 receipt denominator changed")
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
