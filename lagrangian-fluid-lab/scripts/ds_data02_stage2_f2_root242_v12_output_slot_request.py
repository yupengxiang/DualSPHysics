#!/usr/bin/env python3
"""Build a fresh ROOT242 V12 output-slot request.

This builder starts from an immutable V11 source request, creates a new case,
attempt, contract, and external output root, and adds one explicit mapping
for the producer's ``v12_forward.output_root_rebind_v14.path`` marker.  The
old path is retained as provenance and is never made an actionable input.
No reservation, ledger mutation, payload read, or process launch occurs here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V11_BUILDER = SCRIPT_DIR / "ds_data02_stage2_f2_root242_v11_source_request.py"
V12_EXECUTOR_NAME = "ds_data02_stage2_f2_root242_portable_typed_executor_v12.py"
V12_SLOT_SCHEMA = "ds02.stage2.f2-root242-v12-output-slot.v1"
V12_BINDING_SCHEMA = "ds02.stage2.f2-root242-v12-output-slot-source-binding.v1"
V11_HANDOFF_SCHEMA = "ds02.stage2.f2-root242-v11-dynamic-open-guard-source-binding.v1"
MAX_METADATA_BYTES = 32 * 1024 * 1024


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V11 = _load(V11_BUILDER, "ds02_root242_v11_builder_for_v12")


class Root242V12RequestError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise Root242V12RequestError(message)


def _sha(path: Path, role: str) -> str:
    return V11._sha(path, role, maximum=MAX_METADATA_BYTES)


def _stat(path: Path, role: str) -> dict[str, int]:
    return V11._stat(path, role)


def _json(path: Path, role: str) -> dict[str, Any]:
    return V11._json(path, role)


def _canonical(value: Mapping[str, Any]) -> str:
    return V11._canonical(value)


def _write(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                      allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _runtime_source(primary: Path, name: str) -> Path:
    candidate = primary / "lagrangian-fluid-lab" / "scripts" / name
    return candidate if candidate.is_file() else SCRIPT_DIR / name


def _find_marker(value: Any, parts: tuple[str, ...] = ()) -> tuple[str, str] | None:
    if isinstance(value, Mapping):
        marker = value.get("output_root_rebind_v14")
        if isinstance(marker, Mapping) and isinstance(marker.get("path"), str):
            pointer = "".join("/" + item.replace("~", "~0").replace("/", "~1")
                               for item in parts + ("output_root_rebind_v14", "path"))
            return pointer, marker["path"]
        for key, child in value.items():
            found = _find_marker(child, parts + (str(key),))
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_marker(child, parts + (str(index),))
            if found is not None:
                return found
    return None


def _role_digest(roles: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(
        list(roles), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _inner_role(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    binding = contract.get("root242_source_binding")
    roles = binding.get("roles") if isinstance(binding, Mapping) else None
    if not isinstance(roles, list):
        _fail("V11 contract has no role table")
    for role in roles:
        if isinstance(role, Mapping) and role.get("logical_role") == "root200_inner_request":
            return role
    _fail("V11 contract has no root200 inner request role")


def _append_v12_role(roles: list[dict[str, Any]], source: Path) -> None:
    if any(item.get("logical_role") == "v12_executor" for item in roles):
        _fail("V12 executor role already exists")
    roles.append({
        "logical_role": "v12_executor",
        "source_kind": "runtime_source_forward_v12_output_slot",
        "actionable": True,
        "content_read_by_manifest": True,
        "source_sha256": _sha(source, "v12 executor"),
        "source_sha256_basis": "PRIMARY_RUNTIME_SOURCE_AT_V12_BUILD",
        "source_stat_provenance": _stat(source, "v12 executor"),
        "source_path_provenance": str(source),
        "target_relative_path": f"runtime/{V12_EXECUTOR_NAME}",
        "target_stat": None,
        "target_sha256": None,
        "content_sha_verified": False,
        "content_verification_phase": "PARENT_AFTER_RESERVATION",
        "deferred_content": False,
        "placeholder_only": False,
        "source_inode_mtime_equivalence": "NOT_CLAIMED",
    })


def _output_slot(contract: Mapping[str, Any]) -> dict[str, str | bool]:
    inner_role = _inner_role(contract)
    source = inner_role.get("source_path_provenance")
    if not isinstance(source, str) or not source.startswith("/"):
        _fail("inner request provenance is not absolute")
    inner = _json(Path(source), "V12 source inner request")
    found = _find_marker(inner)
    if found is None:
        _fail("source inner request has no /v12_forward/output_root_rebind_v14/path")
    pointer, old_path = found
    if pointer != "/v12_forward/output_root_rebind_v14/path":
        _fail(f"unexpected output marker pointer: {pointer}")
    if not old_path.startswith("/"):
        _fail("old output marker path is not absolute")
    return {
        "schema": V12_SLOT_SCHEMA,
        "target_relative_path": "products",
        "replacement_pointer": pointer,
        "old_source_path": old_path,
        "old_path_role": "HISTORICAL_PROVENANCE_ONLY",
        "proof_output_only": True,
        "attempt_owned": True,
        "original_path_fallback": "REJECT",
    }


def build_request(*, source_contract: Path | str, source_request: Path | str,
                  output_contract: Path | str, output_request: Path | str,
                  fresh_root: Path | str, home_receipt: Path | str,
                  case_id: str, attempt_id: str,
                  primary_scripts_root: Path | str) -> dict[str, Any]:
    out_contract = Path(output_contract).expanduser().absolute()
    out_request = Path(output_request).expanduser().absolute()
    fresh = Path(fresh_root).expanduser().absolute()
    if out_contract.exists() or out_request.exists():
        _fail("V12 builder refuses existing request or contract")
    if fresh.exists() and any(fresh.iterdir()):
        _fail("V12 builder refuses a non-empty fresh output root")
    source_contract_path = Path(source_contract).expanduser().absolute()
    source_request_path = Path(source_request).expanduser().absolute()
    source_contract_value = _json(source_contract_path, "V12 source contract")
    source_request_value = _json(source_request_path, "V12 source request")
    source_binding = source_contract_value.get("root242_source_binding")
    # A ROOT can hand this builder either the original V7/V9 source pair or
    # the already-built V11 pair from the failed attempt.  Cloning a V11
    # pair is essential: rebuilding through V11 would invoke its old V2
    # directory map before this additive output-slot mapping is installed.
    is_v11_pair = (
        isinstance(source_binding, Mapping)
        and source_binding.get("schema") == V11_HANDOFF_SCHEMA
        and isinstance(source_request_value.get("root242_v11_source_binding"), Mapping)
    )
    if is_v11_pair:
        # Admit only a fully sealed consumed V11 pair.  This reads bounded
        # metadata; it does not copy or hash deferred scientific payloads.
        V11.validate_request(request=source_request_path, contract=source_contract_path)
        contract = copy.deepcopy(source_contract_value)
        request = copy.deepcopy(source_request_value)
        request["case_id"] = case_id
        request["attempt_id"] = attempt_id
        request.setdefault("storage_scope", {})["external_filesystem"] = str(fresh)
        request["storage_scope"]["home_receipt_path"] = str(Path(home_receipt).expanduser().absolute())
        out_contract.parent.mkdir(parents=True, exist_ok=True)
        out_request.parent.mkdir(parents=True, exist_ok=True)
    else:
        # V11's builder performs the complete existing source-closure build.
        # It writes only our new files and leaves the consumed source request
        # intact.
        V11.build_request(
            source_contract=source_contract, source_request=source_request,
            output_contract=out_contract, output_request=out_request,
            fresh_root=fresh, home_receipt=home_receipt,
            case_id=case_id, attempt_id=attempt_id,
            primary_scripts_root=primary_scripts_root,
        )
        contract = _json(out_contract, "V11 intermediate contract")
        request = _json(out_request, "V11 intermediate request")
    binding = contract.get("root242_source_binding")
    if not isinstance(binding, Mapping) or not isinstance(binding.get("roles"), list):
        _fail("V11 role table is missing")
    roles = [copy.deepcopy(dict(item)) for item in binding["roles"]
             if isinstance(item, Mapping)]
    primary = Path(primary_scripts_root).expanduser().absolute()
    executor = _runtime_source(primary, V12_EXECUTOR_NAME)
    _append_v12_role(roles, executor)
    roles.sort(key=lambda item: str(item.get("logical_role")))
    slot = _output_slot(contract)
    role_digest = _role_digest(roles)
    try:
        logical, deferred, _copy, metadata, role_counts, suffix_counts = V11.V9.V8._selected_summary(roles)
    except Exception as error:
        _fail(f"cannot summarize V12 role table: {error}")
    new_binding = dict(binding)
    new_binding.update({
        # V11 remains the base schema understood by its consumed validator.
        "schema": V11_HANDOFF_SCHEMA,
        "roles": roles,
        "selected_role_count": len(roles),
        "selected_roles_sha256": role_digest,
        "role_counts": role_counts,
        "suffix_counts": suffix_counts,
        "logical_bytes": logical,
        "deferred_logical_bytes": deferred,
        "metadata_bytes": metadata,
        "source_copy_logical_bytes": logical,
        "source_copy_content_bytes": logical,
        "v12_executor": {
            "logical_role": "v12_executor",
            "target_relative_path": f"runtime/{V12_EXECUTOR_NAME}",
            "source_sha256": next(item["source_sha256"] for item in roles
                                   if item["logical_role"] == "v12_executor"),
        },
        "output_slot": slot,
    })
    contract["root242_source_binding"] = new_binding
    contract["root242_v12_output_slot"] = slot
    contract["forward_version"] = "ROOT242_V12_OUTPUT_SLOT_REBOUND"
    interface = dict(contract.get("v2_interface") or {})
    literal = interface.get("literal_python")
    scripts_dir = primary / "lagrangian-fluid-lab" / "scripts"
    v12_sha = next(item["source_sha256"] for item in roles
                   if item["logical_role"] == "v12_executor")
    interface.update({
        "schema": "ds02.stage2.f2-root242-v12-interface.v1",
        "source_script": str(executor),
        "source_script_sha256": v12_sha,
        "executor_role": "v12_executor",
        "base_executor_role": "v11_executor",
        "output_slot": slot,
        "command_template": [literal, "-B", "-I", "-c",
                              "import os,sys;sys.path.insert(0,sys.argv[1]);from ds_data02_stage2_f2_root242_portable_typed_executor_v12 import main;raise SystemExit(main(sys.argv[2:]))",
                              str(scripts_dir), "run", "--request", "{root242_v12_request}",
                              "--output-root", "{root242_v12_fresh_root}", "--parent-pid",
                              "{parent_pid}", "--max-wall-seconds", "900"],
        "original_path_fallback": "REJECT",
        "portable_cold_replay_credit": "NOT_CLAIMED",
    })
    contract["v2_interface"] = interface
    contract["sha256"] = _canonical(contract)
    contract_file_sha = _write(out_contract, contract)
    V11.V9._refresh_request_inputs(request, contract, roles, out_contract, contract_file_sha)
    request.pop("root242_v9_source_binding", None)
    request["case_id"] = case_id
    request["attempt_id"] = attempt_id
    request["forward_version"] = "ROOT242_V12_OUTPUT_SLOT_REBOUND"
    request["command"] = interface["command_template"]
    request["root242_v11_source_binding"] = {
        "schema": V11_HANDOFF_SCHEMA,
        "contract_path": str(out_contract),
        "contract_sha256": contract["sha256"],
        "selected_roles": len(roles),
        "selected_roles_sha256": role_digest,
        "dynamic_open_audit": True,
        "runtime_worker_target_relative_path": "runtime/ds_data02_stage2_f2_root242_root_runtime_worker_v11.py",
        "parent_after_reservation_copy_and_trace": True,
    }
    request["root242_v12_source_binding"] = {
        "schema": V12_BINDING_SCHEMA,
        "path": str(executor),
        "sha256": v12_sha,
        "role": "v12_executor",
        "source_fallback": "REJECT",
    }
    request["root242_v12_output_slot"] = slot
    request.setdefault("scope", {})["original_path_fallback"] = "REJECT"
    request["scope"]["root242_v12_output_slot"] = {
        "replacement_pointer": slot["replacement_pointer"],
        "target_relative_path": "products",
        "old_source_path": slot["old_source_path"],
        "original_path_fallback": "REJECT",
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
    request["source_only_expected_copy_roles"] = {
        "contract_path": str(out_contract), "contract_sha256": contract["sha256"],
        "role_count": len(roles), "roles_sha256": role_digest,
        "copy_content_bytes": logical, "deferred_payload_bytes": deferred,
        "output_slot": slot, "metadata_only_builder": True,
    }
    request["estimated_deferred_read_bytes"] = deferred
    request["estimated_deferred_copy_and_posthash_bytes"] = deferred
    request["sha256"] = _canonical(request)
    request_file_sha = _write(out_request, request)
    # This validates the actual generated pair and catches stale SHA/path
    # identities before a parent can reserve it.
    validate_request(request=out_request, contract=out_contract)
    return {
        "schema": V12_BINDING_SCHEMA,
        "status": "READY_FOR_PARENT_STAGE2_GUARD_V12_OUTPUT_SLOT",
        "contract": {"path": str(out_contract), "file_sha256": contract_file_sha,
                     "canonical_sha256": contract["sha256"]},
        "request": {"path": str(out_request), "file_sha256": request_file_sha,
                    "canonical_sha256": request["sha256"]},
        "selected": {"role_count": len(roles), "logical_bytes": logical,
                      "metadata_bytes": metadata, "deferred_bytes": deferred,
                      "copy_content_bytes": logical, "roles_sha256": role_digest},
        "output_slot": slot,
        "payload_read": False, "ledger_mutated": False, "launch_performed": False,
    }


def validate_request(*, request: Path | str, contract: Path | str) -> dict[str, Any]:
    request_path = Path(request).expanduser().absolute()
    contract_path = Path(contract).expanduser().absolute()
    base = V11.validate_request(request=request_path, contract=contract_path)
    outer = _json(request_path, "V12 request")
    inner = _json(contract_path, "V12 contract")
    slot = outer.get("root242_v12_output_slot")
    if not isinstance(slot, Mapping) or slot.get("schema") != V12_SLOT_SCHEMA:
        _fail("V12 output-slot request binding is missing")
    contract_slot = inner.get("root242_v12_output_slot")
    if dict(contract_slot or {}) != dict(slot):
        _fail("V12 output-slot request/contract bindings differ")
    if slot.get("replacement_pointer") != "/v12_forward/output_root_rebind_v14/path":
        _fail("V12 output-slot pointer differs")
    if slot.get("target_relative_path") != "products" or slot.get("original_path_fallback") != "REJECT":
        _fail("V12 output-slot target/fallback contract is invalid")
    source = outer.get("root242_v12_source_binding")
    if not isinstance(source, Mapping) or source.get("schema") != V12_BINDING_SCHEMA:
        _fail("V12 executor source binding is missing")
    if (not isinstance(source.get("path"), str)
            or not source["path"].startswith("/")
            or not source["path"].endswith(V12_EXECUTOR_NAME)):
        _fail("V12 executor source path is not the additive launcher")
    v12_role = next((item for item in inner["root242_source_binding"]["roles"]
                     if item.get("logical_role") == "v12_executor"), None)
    if not isinstance(v12_role, Mapping):
        _fail("V12 executor role is missing from contract")
    if v12_role.get("source_path_provenance") != source.get("path") or v12_role.get("source_sha256") != source.get("sha256"):
        _fail("V12 executor role/source binding differs")
    actual_sha = _sha(Path(str(source["path"])), "V12 executor source")
    if actual_sha != source.get("sha256"):
        _fail("V12 executor source SHA changed")
    inner_role = _inner_role(inner)
    inner_value = _json(Path(str(inner_role["source_path_provenance"])), "V12 source inner request")
    marker = _find_marker(inner_value)
    if marker is None or marker[0] != slot.get("replacement_pointer") or marker[1] != slot.get("old_source_path"):
        _fail("V12 output-slot source marker differs")
    return {
        "schema": V12_BINDING_SCHEMA,
        "status": "ROOT242_V12_METADATA_VALIDATED_READY_FOR_PARENT",
        "base": base,
        "output_slot": dict(slot),
        "v12_executor_sha256": actual_sha,
        "payload_read": False, "ledger_mutated": False, "launch_performed": False,
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
    except (Root242V12RequestError, V11.Root242V11Error, OSError, ValueError,
            TypeError, json.JSONDecodeError) as error:
        print(f"ROOT242 V12 source request: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
