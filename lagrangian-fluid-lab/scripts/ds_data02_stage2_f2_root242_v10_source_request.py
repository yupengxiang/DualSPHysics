#!/usr/bin/env python3
"""Build the additive ROOT242 V10 dynamic-open-guard handoff.

V10 is a forward successor of V9.  It preserves the V9 source table and
adds a copied runtime worker which installs a Python audit hook before the
relocated V2/V8/V12/scorer modules are imported.  The hook allows only the
fresh target root, the explicitly pinned project environment, and declared
system runtime roots; it rejects reads from the original DATA/worktree
roots.  This file only reads bounded metadata and never creates a ledger or
reads a production result/HDF5/BI4/native payload.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V9_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_v9_source_request.py"
V10_EXECUTOR_NAME = "ds_data02_stage2_f2_root242_portable_typed_executor_v10.py"
V10_WORKER_NAME = "ds_data02_stage2_f2_root242_root_runtime_worker_v10.py"
HANDOFF_SCHEMA = "ds02.stage2.f2-root242-v10-dynamic-open-guard-source-binding.v1"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V9 = _load(V9_SCRIPT, "ds02_root242_v9_builder_for_v10")


class Root242V10Error(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise Root242V10Error(message)


def _sha(path: Path, role: str, maximum: int = 32 * 1024 * 1024) -> str:
    return V9._file_sha(path, role, maximum)


def _stat(path: Path, role: str) -> dict[str, int]:
    return V9._stat(path, role)


def _json(path: Path, role: str) -> dict[str, Any]:
    return V9._json(path, role)


def _canonical(value: Mapping[str, Any]) -> str:
    return V9._canonical(value)


def _runtime_source(primary: Path, name: str) -> Path:
    candidate = primary / "lagrangian-fluid-lab" / "scripts" / name
    if not candidate.is_file():
        if name == V10_EXECUTOR_NAME:
            return SCRIPT.parent / name
        return SCRIPT.parent / name
    return candidate


def _append_role(roles: list[dict[str, Any]], *, logical: str,
                 source: Path, target: str, source_kind: str) -> None:
    if any(str(item.get("logical_role")) == logical for item in roles):
        _fail(f"duplicate V10 runtime role: {logical}")
    roles.append({
        "logical_role": logical,
        "source_kind": source_kind,
        "actionable": True,
        "content_read_by_manifest": True,
        "source_sha256": _sha(source, logical),
        "source_sha256_basis": "PRIMARY_RUNTIME_SOURCE_AT_V10_BUILD",
        "source_stat_provenance": _stat(source, logical),
        "source_path_provenance": str(source),
        "target_relative_path": target,
        "target_stat": None,
        "target_sha256": None,
        "content_sha_verified": False,
        "content_verification_phase": "PARENT_AFTER_RESERVATION",
        "deferred_content": False,
        "placeholder_only": False,
        "source_inode_mtime_equivalence": "NOT_CLAIMED",
    })


def _role_digest(roles: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(
        list(roles), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _write(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                       allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_request(*, source_contract: Path | str, source_request: Path | str,
                  output_contract: Path | str, output_request: Path | str,
                  fresh_root: Path | str, home_receipt: Path | str,
                  case_id: str, attempt_id: str,
                  primary_scripts_root: Path | str) -> dict[str, Any]:
    """Rebuild V9 metadata, then replace its executor with the V10 worker."""
    out_contract = Path(output_contract).expanduser().absolute()
    out_request = Path(output_request).expanduser().absolute()
    if out_contract.exists() or out_request.exists():
        _fail("V10 builder refuses existing output files")
    # V9 writes the complete selected/recursive source graph.  The source
    # input remains immutable; only the new output namespace is mutated.
    V9.build_request(
        source_contract=source_contract, source_request=source_request,
        output_contract=out_contract, output_request=out_request,
        fresh_root=fresh_root, home_receipt=home_receipt,
        case_id=case_id, attempt_id=attempt_id,
        primary_scripts_root=primary_scripts_root,
    )
    contract = _json(out_contract, "V9 intermediate contract")
    request = _json(out_request, "V9 intermediate request")
    binding = contract.get("root242_source_binding")
    if not isinstance(binding, Mapping) or not isinstance(binding.get("roles"), list):
        _fail("V9 intermediate role table is missing")
    roles = [copy.deepcopy(dict(item)) for item in binding["roles"]
             if isinstance(item, Mapping) and item.get("logical_role") != "v9_executor"]
    primary = Path(primary_scripts_root).expanduser().absolute()
    executor = _runtime_source(primary, V10_EXECUTOR_NAME)
    worker = _runtime_source(primary, V10_WORKER_NAME)
    _append_role(roles, logical="v10_executor", source=executor,
                 target=f"runtime/{V10_EXECUTOR_NAME}",
                 source_kind="runtime_source_forward_v10")
    _append_role(roles, logical="v10_runtime_worker", source=worker,
                 target=f"runtime/{V10_WORKER_NAME}",
                 source_kind="runtime_source_dynamic_open_guard_v10")
    roles.sort(key=lambda item: str(item.get("logical_role")))
    logical, deferred, _copy, metadata, role_counts, suffix_counts = V9.V8._selected_summary(roles)
    digest = _role_digest(roles)
    binding = dict(binding)
    binding.update({
        "schema": HANDOFF_SCHEMA,
        "closure_mode": "SINGLE_CASE_EXPLICIT_GRAPH_V10_DYNAMIC_OPEN_GUARD",
        "roles": roles,
        "selected_role_count": len(roles),
        "selected_roles_sha256": digest,
        "role_counts": role_counts,
        "suffix_counts": suffix_counts,
        "logical_bytes": logical,
        "deferred_logical_bytes": deferred,
        "metadata_bytes": metadata,
        "source_copy_logical_bytes": logical,
        "source_copy_content_bytes": logical,
        "executor": {
            "logical_role": "v10_executor",
            "target_relative_path": f"runtime/{V10_EXECUTOR_NAME}",
            "source_sha256": next(item["source_sha256"] for item in roles
                                   if item["logical_role"] == "v10_executor"),
        },
        "runtime_worker": {
            "logical_role": "v10_runtime_worker",
            "target_relative_path": f"runtime/{V10_WORKER_NAME}",
            "source_sha256": next(item["source_sha256"] for item in roles
                                   if item["logical_role"] == "v10_runtime_worker"),
        },
        "dynamic_open_policy": {
            "schema": "ds02.stage2.f2-runtime-open-policy.v1",
            "audit_hook": "sys.addaudithook",
            "events": ["open", "os.chdir"],
            "forbidden_original_source_roots": "DERIVED_FROM_ALL_NON_ENVIRONMENT_ROLE_SOURCES",
            "allowed_environment": "DECLARED_LITERAL_VENV_PARENT_AND_SYSTEM_RUNTIME_ROOTS",
            "target_root": "PARENT_BOUND_FRESH_ROOT_ONLY",
            "unbound_paths": "REJECT",
        },
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "original_path_fallback": "REJECT",
        "legacy_v7_sparse_executor": "REJECTED_BY_CONTRACT",
    })
    contract["root242_source_binding"] = binding
    contract["forward_version"] = "ROOT242_V10_EXECUTABLE_DYNAMIC_OPEN_GUARD"
    interface = dict(contract.get("v2_interface") or {})
    literal_python = interface.get("literal_python")
    scripts_dir = primary / "lagrangian-fluid-lab" / "scripts"
    interface.update({
        "schema": "ds02.stage2.f2-root242-v10-interface.v1",
        "source_script": str(executor),
        "source_script_sha256": next(item["source_sha256"] for item in roles
                                     if item["logical_role"] == "v10_executor"),
        "executor_role": "v10_executor",
        "runtime_worker_role": "v10_runtime_worker",
        "command_template": [literal_python, "-B", "-I", "-c",
                              "import os,sys;sys.path.insert(0,sys.argv[1]);from ds_data02_stage2_f2_root242_portable_typed_executor_v10 import main;raise SystemExit(main(sys.argv[2:]))",
                              str(scripts_dir), "run", "--request", "{root242_v10_request}",
                              "--output-root", "{root242_v10_fresh_root}", "--parent-pid",
                              "{parent_pid}", "--max-wall-seconds", "900"],
        "dynamic_open_audit_after_copy": True,
        "runtime_open_policy": "TARGET_ROOT_PLUS_LITERAL_ENVIRONMENT_PLUS_SYSTEM_RUNTIME",
        "strict_child_runtime_fallback": "REJECT",
        "deferred_payload_copy_and_posthash_bytes": deferred,
        "scientific_json_read_after_reservation_bytes": next(
            (int((item.get("source_stat_provenance") or {}).get("bytes", 0))
             for item in roles if item.get("logical_role") == "root179c_v16_result_deferred"), 0),
        "scientific_hdf5_parser_read_bytes": 0,
        "scientific_native_or_bi4_read_bytes": 0,
    })
    contract["v2_interface"] = interface
    contract["sha256"] = _canonical(contract)
    contract_file_sha = _write(out_contract, contract)
    # Refresh every outer binding after V10 role/interface mutation.  V9's
    # helper keeps canonical and serialized-file SHA identities separate.
    V9._refresh_request_inputs(request, contract, roles, out_contract, contract_file_sha)
    request.pop("root242_v9_source_binding", None)
    request["forward_version"] = "ROOT242_V10_EXECUTABLE_DYNAMIC_OPEN_GUARD"
    request["command"] = interface["command_template"]
    request["root242_v10_source_binding"] = {
        "schema": HANDOFF_SCHEMA,
        "contract_path": str(out_contract),
        "contract_sha256": contract["sha256"],
        "selected_roles": len(roles),
        "selected_roles_sha256": digest,
        "dynamic_open_audit": True,
        "runtime_worker_target_relative_path": f"runtime/{V10_WORKER_NAME}",
        "parent_after_reservation_copy_and_trace": True,
        "legacy_v7_sparse_executor": "REJECTED_BY_CONTRACT",
    }
    request.setdefault("scope", {})["runtime_open_policy"] = {
        "audit_hook": "sys.addaudithook",
        "original_path_fallback": "REJECT",
        "environment_exception": "EXPLICIT_PINNED_PROJECT_VENV_AND_SYSTEM_RUNTIME",
        "target_root_only_for_relocated_artifacts": True,
    }
    request.setdefault("storage_scope", {}).update({
        "source_logical_bytes_excluding_active_ledger": logical,
        "deferred_source_logical_bytes": deferred,
        "source_copy_content_bytes": logical,
        "bounded_metadata_and_runtime_bytes": metadata,
        "parent_atomic_same_ledger_reservation": True,
        "parent_ledger_owner": "OUTER_PARENT_ONLY",
        "sparse_placeholders_for_deferred_payloads": False,
    })
    request["estimated_deferred_read_bytes"] = deferred
    request["estimated_deferred_copy_and_posthash_bytes"] = deferred
    request["estimated_result_JSON_read_bytes"] = interface["scientific_json_read_after_reservation_bytes"]
    request["estimated_hdf5_read_bytes"] = next(
        (int((item.get("source_stat_provenance") or {}).get("bytes", 0)) for item in roles
         if str(item.get("source_path_provenance", "")).lower().endswith("typed-reconstructed-v2.h5")), 0)
    request["estimated_native_read_bytes"] = 0
    request["estimated_bi4_read_bytes"] = 0
    request["source_only_expected_copy_roles"] = {
        "contract_path": str(out_contract), "contract_sha256": contract["sha256"],
        "role_count": len(roles), "roles_sha256": digest,
        "copy_content_bytes": logical, "deferred_payload_bytes": deferred,
        "dynamic_open_audit": True, "metadata_only_builder": True,
    }
    request["sha256"] = _canonical(request)
    request_file_sha = _write(out_request, request)
    return {
        "schema": HANDOFF_SCHEMA,
        "status": "READY_FOR_PARENT_STAGE2_GUARD_V10",
        "contract": {"path": str(out_contract), "file_sha256": contract_file_sha,
                     "canonical_sha256": contract["sha256"]},
        "request": {"path": str(out_request), "file_sha256": request_file_sha,
                     "canonical_sha256": request["sha256"]},
        "selected": {"role_count": len(roles), "logical_bytes": logical,
                      "metadata_bytes": metadata, "deferred_bytes": deferred,
                      "copy_content_bytes": logical, "roles_sha256": digest},
        "dynamic_open_audit": True, "payload_read": False,
        "ledger_mutated": False, "launch_performed": False,
        "legacy_v7_sparse_executor": "REJECTED_BY_CONTRACT",
    }


def validate_request(*, request: Path | str, contract: Path | str) -> dict[str, Any]:
    request_path = Path(request).expanduser().absolute()
    contract_path = Path(contract).expanduser().absolute()
    outer = _json(request_path, "ROOT242 V10 request")
    inner = _json(contract_path, "ROOT242 V10 contract")
    if outer.get("schema") != V9.V8.REQUEST_SCHEMA or outer.get("sha256") != _canonical(outer):
        _fail("ROOT242 V10 request schema/canonical SHA differs")
    if inner.get("schema") != V9.V8.CONTRACT_SCHEMA or inner.get("sha256") != _canonical(inner):
        _fail("ROOT242 V10 contract schema/canonical SHA differs")
    binding = inner.get("root242_source_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != HANDOFF_SCHEMA:
        _fail("ROOT242 V10 source binding is missing")
    roles = binding.get("roles")
    if not isinstance(roles, list) or len(roles) < 40:
        _fail("ROOT242 V10 selected role table is incomplete")
    digest = _role_digest(roles)
    if binding.get("selected_roles_sha256") != digest:
        _fail("ROOT242 V10 selected role digest differs")
    if outer.get("root213_metadata_contract", {}).get("path") != str(contract_path):
        _fail("ROOT242 V10 request does not bind exact contract path")
    if outer.get("root213_metadata_contract", {}).get("sha256") != inner.get("sha256"):
        _fail("ROOT242 V10 request/contract SHA differs")
    outer_binding = outer.get("root242_v10_source_binding")
    if not isinstance(outer_binding, Mapping) or outer_binding.get("schema") != HANDOFF_SCHEMA:
        _fail("ROOT242 V10 outer source binding is missing")
    if outer_binding.get("selected_roles_sha256") != digest:
        _fail("ROOT242 V10 outer role digest differs")
    names = {str(item.get("logical_role")) for item in roles if isinstance(item, Mapping)}
    required = {"root200_inner_request", "v12_semantic_sidecar", "frozen_v15_request",
                "producer_nested_report_v2", "portable_rebind_v2_entrypoint",
                "fresh_v16_proof_consumer_v8", "fresh_v16_proof_consumer_v12",
                "typed_only_evaluator_v1", "typed_only_evaluator_v2",
                "typed_only_evaluator_v3", "v10_executor", "v10_runtime_worker"}
    if not required.issubset(names):
        _fail(f"ROOT242 V10 runtime closure is incomplete: {sorted(required - names)}")
    policy = binding.get("dynamic_open_policy")
    if not isinstance(policy, Mapping) or policy.get("audit_hook") != "sys.addaudithook":
        _fail("ROOT242 V10 dynamic open policy is missing")
    if outer.get("scope", {}).get("original_path_fallback") != "REJECT":
        _fail("ROOT242 V10 permits original-path fallback")
    discovered = binding.get("recursive_metadata_closure", {}).get("discovered_source_paths", [])
    paths = {str(item.get("source_path_provenance")) for item in roles if isinstance(item, Mapping)}
    if not isinstance(discovered, list) or not set(map(str, discovered)).issubset(paths):
        _fail("ROOT242 V10 recursive metadata source closure is incomplete")
    return {
        "schema": HANDOFF_SCHEMA,
        "status": "ROOT242_V10_METADATA_VALIDATED_READY_FOR_PARENT",
        "request": {"path": str(request_path), "file_sha256": _sha(request_path, "V10 request"),
                    "canonical_sha256": outer["sha256"]},
        "contract": {"path": str(contract_path), "file_sha256": _sha(contract_path, "V10 contract"),
                     "canonical_sha256": inner["sha256"]},
        "selected_role_count": len(roles),
        "selected_logical_bytes": int(binding.get("logical_bytes", 0)),
        "deferred_payload_bytes": int(binding.get("deferred_logical_bytes", 0)),
        "recursive_metadata_source_count": len(discovered),
        "dynamic_open_audit": True, "payload_read": False,
        "ledger_mutated": False, "launch_performed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("source-contract", "source-request", "output-contract", "output-request",
                 "fresh-root", "home-receipt", "primary-scripts-root"):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--contract", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            value = validate_request(request=args.request, contract=args.contract)
        else:
            value = build_request(
                source_contract=args.source_contract, source_request=args.source_request,
                output_contract=args.output_contract, output_request=args.output_request,
                fresh_root=args.fresh_root, home_receipt=args.home_receipt,
                case_id=args.case_id, attempt_id=args.attempt_id,
                primary_scripts_root=args.primary_scripts_root)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root242V10Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT242 V10 source request: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
