#!/usr/bin/env python3
"""Build and verify the v3 proposal-only CPU/native preflight contract.

This module is deliberately a static verifier.  It reads the existing v3 root
receipt, the fresh Definition contract/proposal, and the fresh Definition to
re-check their hash and permission boundaries.  It never invokes GenCase, a
native decoder, a solver, CUDA, a queue, a ledger, a registry, or a job
builder.  The generated-prefix entry is a reserved output identity only; no
generated product is created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = (
    LAB_ROOT
    / "campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1"
)
DEFAULT_REMEDIATION = DEFAULT_BASE / "normal-remediation-v2"
DEFAULT_RECEIPT = DEFAULT_REMEDIATION / "root-review-receipt-v3.json"
DEFAULT_FRESH_CONTRACT = DEFAULT_REMEDIATION / "fresh-definition-contract-v2.json"
DEFAULT_FRESH_PROPOSAL = DEFAULT_REMEDIATION / "fresh-definition-proposal-v2.json"
DEFAULT_DEFINITION = (
    DEFAULT_REMEDIATION
    / "fresh-definition-v2/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2_Def.xml"
)
DEFAULT_OUTPUT = DEFAULT_REMEDIATION / "preflight-contract-v3.json"

SCHEMA = "core.f2.submerged_orifice_transfer.cpu_native_preflight_contract.v3"
CONTRACT_ID = "F2_SUBMERGED_ORIFICE_CPU_NATIVE_PREFLIGHT_CONTRACT_V3"
SCOPE_ID = "F2_submerged_orifice_transfer_v1"
REVISION_ID = "F2_submerged_orifice_normal_remediation_v2"
CASE_ID = "F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2"
MATRIX_INDEX = 4
Q = 0.5
DP_M = 0.0075
ZERO_NORMAL_TOLERANCE_M = 1.0e-12
MASS_RELATIVE_ERROR_MAX = 0.025
CREATED_AT = "2026-09-21T00:00:00+00:00"

BOOL_PERMISSION_KEYS = (
    "cpu_gencase",
    "native_decode",
    "solver_launch",
    "gpu_launch",
    "job_spec_creation",
    "matrix_submission",
)
ZERO_PERMISSION_KEYS = ("queue_mutation", "ledger_mutation", "registry_mutation")


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def verify_ref(item: Mapping[str, Any], label: str,
               expected_path: Path | None = None) -> Path:
    value = item.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: path is missing")
    path = Path(value).resolve()
    if expected_path is not None and path != Path(expected_path).resolve():
        raise ValueError(f"{label}: path mismatch")
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    observed = sha256(path)
    if item.get("sha256") != observed:
        raise ValueError(f"{label}: SHA-256 mismatch")
    if item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: byte count mismatch")
    return path


def _assert_closed_permissions(value: Mapping[str, Any], label: str) -> None:
    for key in BOOL_PERMISSION_KEYS:
        if value.get(key) is not False:
            raise ValueError(f"{label} opened permission: {key}")
    for key in ZERO_PERMISSION_KEYS:
        if value.get(key) != 0:
            raise ValueError(f"{label} opened mutation: {key}")


def _assert_closed_execution(value: Mapping[str, Any], label: str) -> None:
    for key in ("gencase_invoked", "native_decoder_invoked", "solver_invoked", "gpu_invoked"):
        if value.get(key) is not False:
            raise ValueError(f"{label} execution control opened: {key}")
    for key in ZERO_PERMISSION_KEYS:
        if value.get(key) != 0:
            raise ValueError(f"{label} execution control opened: {key}")


def _verify_root_receipt(path: Path) -> dict[str, Any]:
    receipt = load_json(path)
    if receipt.get("schema") != "core.f2.submerged_orifice_transfer.definition_root_review_receipt.v3":
        raise ValueError("v3 root receipt schema mismatch")
    if receipt.get("decision") != "fresh_definition_static_review_passed_cpu_native_still_closed":
        raise ValueError("v3 root receipt decision mismatch")
    if receipt.get("status") != "fresh_definition_hash_bound_no_runtime_authority":
        raise ValueError("v3 root receipt status opened runtime authority")
    if receipt.get("scope_id") != SCOPE_ID or receipt.get("revision_id") != REVISION_ID:
        raise ValueError("v3 root receipt scope/revision mismatch")
    if receipt.get("case_id") != CASE_ID or receipt.get("matrix_index") != MATRIX_INDEX:
        raise ValueError("v3 root receipt case identity mismatch")
    if receipt.get("authorized_for_one_fresh_cpu_native_preflight") is not False:
        raise ValueError("v3 root receipt authorizes CPU/native preflight")
    if receipt.get("qualification_claim") != "none" or receipt.get("matrix_credit") != 0:
        raise ValueError("v3 root receipt carries qualification credit")
    _assert_closed_permissions(receipt.get("authorization", {}), "v3 root receipt")

    static = receipt.get("static_review", {})
    for key in ("all_hash_bindings_current", "fresh_definition_contract_pass",
                "fresh_definition_writer_hash_bound"):
        if static.get(key) is not True:
            raise ValueError(f"v3 root receipt static review failed: {key}")
    if static.get("fresh_definition_runtime_invoked") is not False:
        raise ValueError("v3 root receipt records Definition runtime invocation")
    if static.get("fresh_native_bi4_present") is not False:
        raise ValueError("v3 root receipt records a fresh BI4")
    future = receipt.get("future_single_preflight_conditions", {})
    if future.get("fresh_definition_only") is not True:
        raise ValueError("future preflight is not fresh-definition-only")
    if future.get("case_id") != CASE_ID or future.get("q") != Q or future.get("dp_m") != DP_M:
        raise ValueError("future preflight identity mismatch")
    if future.get("zero_normal_count_must_equal") != 0:
        raise ValueError("future zero-normal gate is not exact zero")
    if future.get("zero_normal_threshold_m") != ZERO_NORMAL_TOLERANCE_M:
        raise ValueError("future zero-normal threshold changed")
    if future.get("qualification_credit") != 0:
        raise ValueError("future preflight carries qualification credit")

    bindings = receipt.get("hash_bindings", {})
    if not isinstance(bindings, dict):
        raise ValueError("v3 root receipt hash_bindings is not an object")
    for key, item in bindings.items():
        if not isinstance(item, dict):
            raise ValueError(f"v3 root receipt binding is not an object: {key}")
        verify_ref(item, f"v3 root receipt {key}")
    return receipt


def _verify_fresh_inputs(receipt: Mapping[str, Any], fresh_contract_path: Path,
                         fresh_proposal_path: Path, definition_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = load_json(fresh_contract_path)
    proposal = load_json(fresh_proposal_path)
    if contract.get("schema") != "core.f2.submerged_orifice_transfer.fresh_definition_contract.v2":
        raise ValueError("fresh Definition contract schema mismatch")
    if contract.get("scope_id") != SCOPE_ID or contract.get("revision_id") != REVISION_ID:
        raise ValueError("fresh Definition contract scope/revision mismatch")
    if contract.get("case_id") != CASE_ID:
        raise ValueError("fresh Definition contract case identity mismatch")
    if contract.get("status") != "fresh_definition_static_contract_not_runtime_authorized":
        raise ValueError("fresh Definition contract status opened runtime")
    _assert_closed_permissions(contract.get("authorization", {}), "fresh Definition contract")
    if contract.get("preflight", {}).get("status") != "not_run":
        raise ValueError("fresh Definition contract preflight is not closed")
    if contract.get("preflight", {}).get("fresh_generated_xml_present") is not False:
        raise ValueError("fresh Definition contract records generated XML")
    if contract.get("preflight", {}).get("fresh_native_bi4_present") is not False:
        raise ValueError("fresh Definition contract records native BI4")
    if contract.get("preflight", {}).get("cpu_native_credit") != 0:
        raise ValueError("fresh Definition contract carries CPU/native credit")
    fresh = contract.get("fresh_definition", {})
    if fresh.get("old_anchor_definition_reused") is not False or fresh.get("old_anchor_bi4_reused") is not False:
        raise ValueError("fresh Definition contract reuses old anchor input")

    if proposal.get("schema") != "core.f2.submerged_orifice_transfer.fresh_definition_proposal.v2":
        raise ValueError("fresh Definition proposal schema mismatch")
    if proposal.get("authorized_now") is not False or proposal.get("case_id") != CASE_ID:
        raise ValueError("fresh Definition proposal opened authority or changed identity")
    if proposal.get("q") != Q or proposal.get("dp_m") != DP_M:
        raise ValueError("fresh Definition proposal q/dp mismatch")
    identity = proposal.get("fresh_input_identity", {})
    if identity.get("old_anchor_definition_reused") is not False or identity.get("old_anchor_bi4_reused") is not False:
        raise ValueError("fresh Definition proposal reuses old anchor input")
    prefix = identity.get("new_generated_prefix")
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("fresh Definition proposal has no new generated prefix")
    prefix_path = Path(prefix).resolve()
    old_anchor = Path(identity.get("old_anchor_path", "")).resolve()
    if old_anchor and old_anchor in prefix_path.parents:
        raise ValueError("new generated prefix is under the failed anchor")
    if prefix_path.name != CASE_ID:
        raise ValueError("new generated prefix case identity mismatch")
    if identity.get("new_native_bi4_present") is not False:
        raise ValueError("fresh Definition proposal records native BI4")
    _assert_closed_execution(proposal.get("execution_controls", {}), "fresh Definition proposal")
    if proposal.get("execution_controls", {}).get("definition_writer_invoked") is not True:
        raise ValueError("fresh Definition proposal lost its static writer provenance")

    receipt_bindings = receipt.get("hash_bindings", {})
    for key, expected in (
        ("fresh_definition", definition_path),
        ("fresh_definition_contract", fresh_contract_path),
        ("fresh_definition_proposal", fresh_proposal_path),
    ):
        verify_ref(receipt_bindings.get(key, {}), f"v3 root receipt {key}", expected)
    verify_ref(fresh.get("definition", {}), "fresh Definition contract definition", definition_path)
    verify_ref(fresh.get("proposal", {}), "fresh Definition contract proposal", fresh_proposal_path)
    proposal_definition = identity.get("definition", {})
    verify_ref(proposal_definition, "fresh Definition proposal definition", definition_path)
    return contract, proposal, {"path": str(prefix_path), "xml": str(prefix_path.with_suffix(".xml")),
                                "bi4": str(prefix_path.with_suffix(".bi4"))}


def _hard_gates() -> dict[str, Any]:
    pending = "pending_fresh_cpu_native_preflight"
    return {
        "zero_boundnor": {
            "required": True,
            "metric": "BoundNor vectors with norm <= threshold",
            "threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "operator": "==",
            "required_value": 0,
            "observed": None,
            "status": pending,
        },
        "normal_size": {
            "required": True,
            "metric": "NormalSize entries <= threshold",
            "threshold_m": ZERO_NORMAL_TOLERANCE_M,
            "operator": "==",
            "required_value": 0,
            "observed": None,
            "status": pending,
        },
        "ids": {
            "required": True,
            "checks": ["native particle IDs are unique", "native IDs align exactly with generated XML IDs"],
            "required_value": True,
            "observed": None,
            "status": pending,
        },
        "finite": {
            "required": True,
            "checks": ["positions", "BoundNor", "NormalSize", "mass/density arrays"],
            "required_value": True,
            "observed": None,
            "status": pending,
        },
        "mass": {
            "required": True,
            "metric": "native mass relative error",
            "operator": "<=",
            "max_relative_error": MASS_RELATIVE_ERROR_MAX,
            "observed": None,
            "status": pending,
        },
        "endpoints": {
            "required": True,
            "checks": {
                "outer_wall_endpoint_count": {"operator": "==", "required_value": 0, "observed": None},
                "gate_endpoint_penetration_count": {"operator": "==", "required_value": 0, "observed": None},
            },
            "status": pending,
        },
    }


def build_contract(
    receipt_path: Path = DEFAULT_RECEIPT,
    fresh_contract_path: Path = DEFAULT_FRESH_CONTRACT,
    fresh_proposal_path: Path = DEFAULT_FRESH_PROPOSAL,
    definition_path: Path = DEFAULT_DEFINITION,
    output: Path = DEFAULT_OUTPUT,
    generated_prefix: Path | None = None,
) -> dict[str, Any]:
    receipt_path = Path(receipt_path).resolve()
    fresh_contract_path = Path(fresh_contract_path).resolve()
    fresh_proposal_path = Path(fresh_proposal_path).resolve()
    definition_path = Path(definition_path).resolve()
    receipt = _verify_root_receipt(receipt_path)
    fresh_contract, proposal, output_identity = _verify_fresh_inputs(
        receipt, fresh_contract_path, fresh_proposal_path, definition_path
    )
    if generated_prefix is not None and Path(generated_prefix).resolve() != Path(output_identity["path"]):
        raise ValueError("explicit generated prefix differs from fresh Definition proposal")
    prefix = Path(output_identity["path"])
    expected_xml = Path(output_identity["xml"])
    expected_bi4 = Path(output_identity["bi4"])
    if expected_xml.exists() or expected_bi4.exists():
        raise ValueError("proposal-only contract refuses pre-existing fresh generated products")

    permissions = {
        **{key: False for key in BOOL_PERMISSION_KEYS},
        **{key: 0 for key in ZERO_PERMISSION_KEYS},
        "qualification_numerator_credit": 0,
    }
    contract = {
        "schema": SCHEMA,
        "contract_id": CONTRACT_ID,
        "created_at_utc": CREATED_AT,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "matrix_index": MATRIX_INDEX,
        "q": Q,
        "dp_m": DP_M,
        "status": "proposal_only_cpu_native_closed",
        "decision": "static_contract_only_no_preflight_authority",
        "proposal_only": True,
        "authorized_now": False,
        "execution_closed": True,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "input_bindings": {
            "v3_root_review_receipt": ref(receipt_path, "existing v3 root-review receipt"),
            "fresh_definition": ref(definition_path, "fresh literal v2 Definition"),
            "fresh_definition_contract": ref(fresh_contract_path, "fresh Definition static contract"),
            "fresh_definition_proposal": ref(fresh_proposal_path, "fresh Definition proposal"),
            "verifier": ref(Path(__file__).resolve(), "v3 proposal-only contract verifier"),
        },
        "fresh_output": {
            "generated_prefix": str(prefix),
            "expected_generated_xml": str(expected_xml),
            "expected_native_bi4": str(expected_bi4),
            "currently_present": {"generated_xml": False, "native_bi4": False},
            "fresh_definition_only": True,
            "old_anchor_definition_reused": False,
            "old_anchor_bi4_reused": False,
            "output_materialized": False,
        },
        "hard_gates": _hard_gates(),
        "gate_evaluation": {
            "status": "not_run",
            "all_hard_gates_pass": False,
            "qualification_credit": 0,
            "threshold_relaxation": False,
            "same_input_retry": False,
            "survivor_renormalization": False,
        },
        "permissions": permissions,
        "denominator": {
            "planned_rows": 15,
            "executed_rows": 0,
            "passed_rows": 0,
            "failed_rows": 0,
            "unattempted_rows": 15,
            "qualification_numerator": 0,
        },
        "prohibited_actions": [
            "do not invoke GenCase or a native decoder",
            "do not launch a solver or GPU",
            "do not create a job",
            "do not mutate queue, ledger, registry, or matrix",
            "do not relax any hard gate or assign qualification credit",
        ],
        "review_note_zh": "这是 proposal-only 静态合约；v3 root receipt 未授权 CPU/native preflight，所有 hard gate 仍待未来独立授权后的 fresh 输出验证。",
    }
    write_json(Path(output), contract)
    return contract


def verify_contract(path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    contract_path = Path(path).resolve()
    contract = load_json(contract_path)
    if contract.get("schema") != SCHEMA or contract.get("contract_id") != CONTRACT_ID:
        raise ValueError("proposal-only contract schema/id mismatch")
    if contract.get("proposal_only") is not True or contract.get("authorized_now") is not False:
        raise ValueError("proposal-only contract opened authority")
    if contract.get("execution_closed") is not True:
        raise ValueError("proposal-only contract execution is not closed")
    if contract.get("qualification_claim") != "none" or contract.get("matrix_credit") != 0:
        raise ValueError("proposal-only contract carries qualification credit")
    _assert_closed_permissions(contract.get("permissions", {}), "proposal-only contract")
    evaluation = contract.get("gate_evaluation", {})
    if evaluation.get("status") != "not_run" or evaluation.get("all_hard_gates_pass") is not False:
        raise ValueError("proposal-only contract records a preflight result")
    if evaluation.get("qualification_credit") != 0:
        raise ValueError("proposal-only contract gate evaluation carries credit")
    gates = contract.get("hard_gates", {})
    if set(gates) != {"zero_boundnor", "normal_size", "ids", "finite", "mass", "endpoints"}:
        raise ValueError("hard-gate set is incomplete")
    for name, gate in gates.items():
        if gate.get("required") is not True or gate.get("observed") is not None:
            if name != "endpoints" or gate.get("required") is not True:
                raise ValueError(f"hard gate {name} is not pending")
        if gate.get("status") != "pending_fresh_cpu_native_preflight":
            raise ValueError(f"hard gate {name} is not pending")
    bindings = contract.get("input_bindings", {})
    receipt_path = verify_ref(bindings.get("v3_root_review_receipt", {}), "contract v3 root receipt")
    definition_path = verify_ref(bindings.get("fresh_definition", {}), "contract fresh Definition")
    fresh_contract_path = verify_ref(bindings.get("fresh_definition_contract", {}), "contract fresh Definition contract")
    fresh_proposal_path = verify_ref(bindings.get("fresh_definition_proposal", {}), "contract fresh Definition proposal")
    verify_ref(bindings.get("verifier", {}), "contract verifier", Path(__file__).resolve())
    rebuilt = build_contract(
        receipt_path=receipt_path,
        fresh_contract_path=fresh_contract_path,
        fresh_proposal_path=fresh_proposal_path,
        definition_path=definition_path,
        output=contract_path.with_suffix(".verify-rebuild.json"),
        generated_prefix=Path(contract["fresh_output"]["generated_prefix"]),
    )
    try:
        rebuilt.pop("created_at_utc", None)
        observed = dict(contract)
        observed.pop("created_at_utc", None)
        if rebuilt != observed:
            raise ValueError("proposal-only contract does not match current v3 inputs")
    finally:
        verify_path = contract_path.with_suffix(".verify-rebuild.json")
        if verify_path.exists():
            verify_path.unlink()
    return contract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("write-contract", "verify-contract"))
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--fresh-contract", type=Path, default=DEFAULT_FRESH_CONTRACT)
    parser.add_argument("--fresh-proposal", type=Path, default=DEFAULT_FRESH_PROPOSAL)
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-prefix", type=Path)
    args = parser.parse_args(argv)
    if args.command == "write-contract":
        result = build_contract(
            receipt_path=args.receipt,
            fresh_contract_path=args.fresh_contract,
            fresh_proposal_path=args.fresh_proposal,
            definition_path=args.definition,
            output=args.output,
            generated_prefix=args.generated_prefix,
        )
    else:
        result = verify_contract(args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
