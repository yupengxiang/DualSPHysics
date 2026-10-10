#!/usr/bin/env python3
"""Build/validate a ROOT242 V15 request from a complete V14 preflight.

V13 is retained as the immutable request/parent base.  V14 replaces its
50-role source table with the roles emitted by the recursive preflight,
adds the V14 launcher and the sealed preflight report, and refreshes every
serialized request/contract SHA.  The request records the actual copy plan:
all 489 roles are materialized by the parent after reservation, while 410
large scientific roles (9,944,536,758 bytes in the current ROOT242 graph)
remain deferred until that phase.  This builder only reads bounded metadata;
it never reserves, copies, hashes deferred payloads, or mutates a ledger.
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
V13_BUILDER_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_v13_output_slot_request.py"
V14_PREFLIGHT_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_recursive_source_preflight_v14.py"
V14_EXECUTOR_NAME = "ds_data02_stage2_f2_root242_portable_typed_executor_v14.py"
V15_RUNTIME_NAME = "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py"
V14_SCHEMA = "ds02.stage2.f2-root242-v14-recursive-source-binding.v1"
V14_PREFLIGHT_SCHEMA = "ds02.stage2.f2-root242-v14-recursive-source-preflight.v1"
V14_REPORT_ROLE = "v14_recursive_preflight_report"
V14_EXECUTOR_ROLE = "v14_executor"
MAX_METADATA_BYTES = 32 * 1024 * 1024
SAFETY_MARGIN_BYTES = 128 * 1024 * 1024


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V13 = _load(V13_BUILDER_SCRIPT, "ds02_root242_v13_builder_for_v14")
PREFLIGHT = _load(V14_PREFLIGHT_SCRIPT, "ds02_root242_v14_preflight_for_builder")


class Root242V14RequestError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise Root242V14RequestError(message)


def _replace_list_string_runtime_role(roles: list[dict[str, Any]], primary: Path) -> None:
    """Bind the copied V5 entrypoint target to the additive V15 bytes.

    The target-relative filename remains the one consumed by the V11 child;
    only its sealed source is advanced.  This keeps the V14 launcher and
    parent schema compatible while ensuring the child actually executes the
    list-string path fix.
    """
    source = _runtime_source(primary, V15_RUNTIME_NAME)
    if not source.is_file():
        _fail(f"V15 runtime source is unavailable: {source}")
    for role in roles:
        if role.get("logical_role") == "portable_rebind_v2_entrypoint":
            role["source_path_provenance"] = str(source)
            role["source_sha256"] = _sha(source, "V15 runtime source")
            role["source_stat_provenance"] = _stat(source, "V15 runtime source")
            role["source_kind"] = "runtime_source_forward_v15_list_string_rebind"
            role["content_read_by_manifest"] = True
            role["deferred_content"] = False
            role["content_verification_phase"] = "REBOUND_METADATA"
            return
    _fail("V14 contract lacks portable_rebind_v2_entrypoint role")


def _json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} is not a regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        _fail(f"{label} exceeds bounded metadata size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read {label}: {error}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _sha(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} is not a regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        _fail(f"{label} exceeds bounded metadata hash size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, label: str) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} is not a regular file: {path}")
    value = path.stat()
    return {
        "bytes": int(value.st_size), "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
    }


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str,
    ).encode("utf-8")).hexdigest()


def _write(path: Path, value: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                      allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _runtime_source(primary: Path, name: str) -> Path:
    candidate = primary / "lagrangian-fluid-lab" / "scripts" / name
    return candidate if candidate.is_file() else SCRIPT_DIR / name


def _role(logical: str, source: Path, target: str, *, kind: str,
          deferred: bool = False) -> dict[str, Any]:
    value = _stat(source, logical)
    return {
        "logical_role": logical, "source_kind": kind, "actionable": True,
        "content_read_by_manifest": not deferred,
        "source_sha256": _sha(source, logical),
        "source_sha256_basis": "V14_BOUNDED_METADATA_PREFLIGHT",
        "source_stat_provenance": value, "source_path_provenance": str(source),
        "target_relative_path": target, "target_stat": None,
        "target_sha256": None, "content_sha_verified": False,
        "content_verification_phase": "PARENT_AFTER_RESERVATION" if deferred else "REBOUND_METADATA",
        "deferred_content": deferred, "placeholder_only": False,
        "source_inode_mtime_equivalence": "NOT_CLAIMED",
    }


def _check_report(report_path: Path, source_request: Path) -> dict[str, Any]:
    report = _json(report_path, "V14 preflight report")
    if report.get("schema") != V14_PREFLIGHT_SCHEMA:
        _fail("V14 preflight report schema differs")
    if report.get("status") != "READY_FOR_PARENT_GUARD_METADATA_ONLY":
        _fail(f"V14 preflight is not ready: {report.get('status')}")
    if report.get("unbound_actionable_paths") or report.get("graph_errors"):
        _fail("V14 preflight contains unbound/graph errors")
    if (report.get("rewrite") or {}).get("errors"):
        _fail("V14 preflight contains V2 rewrite errors")
    if report.get("request_file_sha256") != _sha(source_request, "V13 source request"):
        _fail("V14 preflight was built from a different source request")
    roles = report.get("roles")
    if not isinstance(roles, list) or not roles:
        _fail("V14 preflight role table is empty")
    seen_names: set[str] = set()
    seen_targets: set[str] = set()
    for item in roles:
        if not isinstance(item, Mapping):
            _fail("V14 role table contains a non-object")
        name = item.get("logical_role")
        target = item.get("target_relative_path")
        source = item.get("source_path_provenance")
        sha = item.get("source_sha256")
        if not isinstance(name, str) or not name or name in seen_names:
            _fail(f"V14 role name is missing/duplicated: {name}")
        if not isinstance(target, str) or not target or Path(target).is_absolute() or ".." in Path(target).parts:
            _fail(f"V14 role target is unsafe: {name}")
        if target in seen_targets:
            _fail(f"V14 role target is duplicated: {target}")
        if not isinstance(source, str) or not source.startswith("/"):
            _fail(f"V14 role source is not absolute: {name}")
        if not isinstance(sha, str) or len(sha) != 64:
            _fail(f"V14 role has no sealed source SHA: {name}")
        stat = item.get("source_stat_provenance")
        if not isinstance(stat, Mapping) or "bytes" not in stat or "mode_bits" not in stat:
            _fail(f"V14 role has no sealed source stat: {name}")
        seen_names.add(name)
        seen_targets.add(target)
    return report


def _append_unique(roles: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if any(str(row.get("logical_role")) == item["logical_role"] for row in roles):
        _fail(f"V14 role already exists: {item['logical_role']}")
    if any(str(row.get("target_relative_path")) == item["target_relative_path"] for row in roles):
        _fail(f"V14 target already exists: {item['target_relative_path']}")
    roles.append(item)


def _deferred_role_classes(report: Mapping[str, Any],
                           roles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Classify copy inputs without treating the whole discovery graph alike.

    The preflight deliberately seals every actionable edge, but the parent
    needs an auditable cost split.  Classification uses only the bounded
    pointer/source metadata already in the report; it never opens a deferred
    BI4/H5/CSV payload.  A role can still be copied and post-hashed even when
    its class is ``deferred_auxiliary``.
    """
    contexts: dict[str, set[str]] = {}
    for binding in report.get("nested_actionable_bindings", []):
        if not isinstance(binding, Mapping):
            continue
        source = binding.get("source_path_provenance")
        if not isinstance(source, str):
            continue
        pointer = str(binding.get("pointer", ""))
        contexts.setdefault(source, set()).add(pointer)

    counts: dict[str, dict[str, int]] = {}
    rows: list[dict[str, Any]] = []
    for role in roles:
        source = str(role.get("source_path_provenance", ""))
        suffix = Path(source).suffix.lower()
        size = int((role.get("source_stat_provenance") or {}).get("bytes", 0) or 0)
        pointers = contexts.get(source, set())
        lower_pointers = " ".join(pointers).lower()
        deferred = bool(role.get("deferred_content"))
        if not deferred:
            category = "sealed_metadata_or_runtime"
        elif suffix == ".bi4" and "/raw_binding/frames/" in lower_pointers:
            category = "raw_frame_input"
        elif suffix in {".h5", ".hdf5"} and any(
                marker in lower_pointers for marker in ("/result/", "/typed_output/", "/products/")):
            category = "typed_scientific_product"
        elif suffix in {".h5", ".hdf5", ".bi4", ".obi4", ".ibi4", ".vtk", ".vtu", ".pvtu"}:
            category = "scientific_auxiliary_input"
        else:
            category = "deferred_auxiliary_input"
        bucket = counts.setdefault(category, {"roles": 0, "bytes": 0})
        bucket["roles"] += 1
        bucket["bytes"] += size
        rows.append({"logical_role": role.get("logical_role"), "category": category,
                     "bytes": size, "source_suffix": suffix or "<none>",
                     "pointer_count": len(pointers)})
    return {"counts": counts, "roles": rows,
            "policy": {
                "all_categories_are_copy_inputs": True,
                "hash_phase": "PARENT_AFTER_RESERVATION",
                "historical_provenance_is_not_actionable": True,
                "live_ledger_requires_frozen_snapshot": True,
            }}


def _source_binding(contract: Mapping[str, Any]) -> Mapping[str, Any]:
    value = contract.get("root242_source_binding")
    if not isinstance(value, Mapping) or not isinstance(value.get("roles"), list):
        _fail("V13 contract role table is missing")
    return value


def build_request(*, source_contract: Path | str, source_request: Path | str,
                  preflight_report: Path | str, output_contract: Path | str,
                  output_request: Path | str, fresh_root: Path | str,
                  home_receipt: Path | str, case_id: str, attempt_id: str,
                  primary_scripts_root: Path | str) -> dict[str, Any]:
    source_request_path = Path(source_request).expanduser().absolute()
    report_path = Path(preflight_report).expanduser().absolute()
    out_contract = Path(output_contract).expanduser().absolute()
    out_request = Path(output_request).expanduser().absolute()
    fresh = Path(fresh_root).expanduser().absolute()
    if out_contract.exists() or out_request.exists():
        _fail("V14 builder refuses existing output request/contract")
    if fresh.exists() and any(fresh.iterdir()):
        _fail("V14 builder refuses a non-empty fresh root")
    report = _check_report(report_path, source_request_path)

    source_contract_path = Path(source_contract).expanduser().absolute()
    source_contract_value = _json(source_contract_path, "V13 source contract")
    source_request_path = Path(source_request).expanduser().absolute()
    source_request_value = _json(source_request_path, "V13 source request")
    source_binding = source_contract_value.get("root242_source_binding")
    source_is_v13 = (
        isinstance(source_binding, Mapping)
        and source_binding.get("schema") == V13.V11_HANDOFF_SCHEMA
        and isinstance(source_request_value.get("root242_v13_source_binding"), Mapping)
    )
    if source_is_v13:
        # V13's builder intentionally rejects a V13 input (it would append a
        # second v13_executor role).  For this additive successor, validate
        # and clone the already sealed V13 pair, then rebind only the new
        # case/attempt/output namespace.  Historical source bytes stay put.
        V13.validate_request(request=source_request_path, contract=source_contract_path)
        contract = copy.deepcopy(source_contract_value)
        request = copy.deepcopy(source_request_value)
        request["case_id"] = case_id
        request["attempt_id"] = attempt_id
        request.setdefault("storage_scope", {})["external_filesystem"] = str(fresh)
        request["storage_scope"]["home_receipt_path"] = str(Path(home_receipt).expanduser().absolute())
        out_contract.parent.mkdir(parents=True, exist_ok=True)
        out_request.parent.mkdir(parents=True, exist_ok=True)
    else:
        # V13 performs the complete base validation and writes a new,
        # isolated request pair.  The source pair and its historical bytes
        # are untouched.
        V13.build_request(
            source_contract=source_contract, source_request=source_request,
            output_contract=out_contract, output_request=out_request,
            fresh_root=fresh, home_receipt=home_receipt,
            case_id=case_id, attempt_id=attempt_id,
            primary_scripts_root=primary_scripts_root,
        )
        contract = _json(out_contract, "V13 intermediate contract")
        request = _json(out_request, "V13 intermediate request")
    base_binding = _source_binding(contract)
    roles = [copy.deepcopy(dict(item)) for item in report["roles"]]
    primary = Path(primary_scripts_root).expanduser().absolute()
    _replace_list_string_runtime_role(roles, primary)
    executor = _runtime_source(primary, V14_EXECUTOR_NAME)
    _append_unique(roles, _role(
        V14_EXECUTOR_ROLE, executor, f"runtime/{V14_EXECUTOR_NAME}",
        kind="runtime_source_forward_v14_recursive_executor",
    ))
    _append_unique(roles, _role(
        V14_REPORT_ROLE, report_path, "metadata/root242-v14-preflight-report.json",
        kind="sealed_v14_recursive_preflight_report",
    ))
    roles.sort(key=lambda item: str(item["logical_role"]))
    logical, deferred, copy_bytes, metadata, role_counts, suffix_counts = V13.V11.V9.V8._selected_summary(roles)
    role_classes = _deferred_role_classes(report, roles)
    digest = hashlib.sha256(json.dumps(
        roles, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
    report_file_sha = _sha(report_path, "V14 preflight report")
    source_sha = _sha(source_request_path, "V13 source request")
    binding = dict(base_binding)
    binding.update({
        # V11/V13 validators intentionally continue to see their historical
        # handoff schema.  V14 is an additive binding under that schema.
        "roles": roles, "selected_role_count": len(roles),
        "selected_roles_sha256": digest, "role_counts": role_counts,
        "suffix_counts": suffix_counts, "logical_bytes": logical,
        "deferred_logical_bytes": deferred, "metadata_bytes": metadata,
        "source_copy_logical_bytes": logical, "source_copy_content_bytes": logical,
        "v14_executor": {"logical_role": V14_EXECUTOR_ROLE,
                          "target_relative_path": f"runtime/{V14_EXECUTOR_NAME}",
                          "source_sha256": next(x["source_sha256"] for x in roles
                                                if x["logical_role"] == V14_EXECUTOR_ROLE)},
        "v14_recursive_preflight": {
            "schema": V14_PREFLIGHT_SCHEMA, "logical_role": V14_REPORT_ROLE,
            "source_path": str(report_path), "source_file_sha256": report_file_sha,
            "source_request_file_sha256": source_sha,
            "role_count": report["role_count"],
            "deferred_role_count": sum(bool(x.get("deferred_content")) for x in report["roles"]),
            "unbound_count": len(report.get("unbound_actionable_paths", [])),
            "rewrite_error_count": len((report.get("rewrite") or {}).get("errors", [])),
            "payload_read": False, "ledger_mutated": False,
        },
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "original_path_fallback": "REJECT",
    })
    contract["root242_source_binding"] = binding
    contract["root242_v14_recursive_preflight"] = binding["v14_recursive_preflight"]
    contract["forward_version"] = "ROOT242_V14_RECURSIVE_SOURCE_CLOSURE"
    interface = dict(contract.get("v2_interface") or {})
    literal = interface.get("literal_python")
    scripts_dir = primary / "lagrangian-fluid-lab" / "scripts"
    interface.update({
        "schema": "ds02.stage2.f2-root242-v14-interface.v1",
        "source_script": str(executor),
        "source_script_sha256": next(x["source_sha256"] for x in roles
                                      if x["logical_role"] == V14_EXECUTOR_ROLE),
        "executor_role": V14_EXECUTOR_ROLE,
        "base_executor_role": "v13_executor",
        "recursive_preflight_role": V14_REPORT_ROLE,
        "command_template": [literal, "-B", "-I", "-c",
                              "import os,sys;sys.path.insert(0,sys.argv[1]);from ds_data02_stage2_f2_root242_portable_typed_executor_v14 import main;raise SystemExit(main(sys.argv[2:]))",
                              str(scripts_dir), "run", "--request", "{root242_v14_request}",
                              "--output-root", "{root242_v14_fresh_root}", "--parent-pid",
                              "{parent_pid}", "--max-wall-seconds", "900"],
        "original_path_fallback": "REJECT",
        "metadata_rewrite_sha_refresh": "REQUIRED_FOR_EVERY_REBASED_DOCUMENT",
        "portable_cold_replay_credit": "NOT_CLAIMED",
    })
    contract["v2_interface"] = interface
    contract["sha256"] = _canonical(contract)
    contract_file_sha = _write(out_contract, contract)
    V13.V11.V9._refresh_request_inputs(request, contract, roles, out_contract, contract_file_sha)
    # Keep the consumed V13 handoff binding intact.  V13.validate_request is
    # the base admission gate used by the parent and requires this exact
    # source/launcher join; V14 adds its own binding below without replacing
    # the V13 identity.
    request["case_id"] = case_id
    request["attempt_id"] = attempt_id
    request["forward_version"] = "ROOT242_V14_RECURSIVE_SOURCE_CLOSURE"
    request["command"] = interface["command_template"]
    request["root242_v11_source_binding"] = {
        **dict(request.get("root242_v11_source_binding") or {}),
        "schema": "ds02.stage2.f2-root242-v11-dynamic-open-guard-source-binding.v1",
        "contract_path": str(out_contract), "contract_sha256": contract["sha256"],
        "selected_roles": len(roles), "selected_roles_sha256": digest,
        "parent_after_reservation_copy_and_trace": True,
    }
    request["root242_v14_source_binding"] = {
        "schema": V14_SCHEMA, "path": str(executor),
        "sha256": next(x["source_sha256"] for x in roles
                        if x["logical_role"] == V14_EXECUTOR_ROLE),
        "role": V14_EXECUTOR_ROLE, "source_fallback": "REJECT",
    }
    request["root242_v14_preflight_binding"] = {
        "schema": V14_PREFLIGHT_SCHEMA, "logical_role": V14_REPORT_ROLE,
        "path": str(report_path), "file_sha256": report_file_sha,
        "source_request_path": str(source_request_path),
        "source_request_file_sha256": source_sha,
        "role_count": report["role_count"],
        "status": report["status"], "unbound_count": 0,
        "rewrite_error_count": 0, "payload_read": False,
    }
    request.setdefault("scope", {})["original_path_fallback"] = "REJECT"
    request["scope"]["root242_v14_recursive_source_closure"] = {
        "preflight_report_role": V14_REPORT_ROLE,
        "preflight_report_sha256": report_file_sha,
        "all_roles_materialized_after_parent_reservation": True,
        "deferred_role_count": sum(bool(x.get("deferred_content")) for x in report["roles"]),
        "unknown_sha_policy": "REJECT_UNTIL_PARENT_POSTHASH",
        "nested_metadata_sha_policy": "RECOMPUTE_AFTER_TARGET_REWRITE",
    }
    storage = request.setdefault("storage_scope", {})
    storage.update({
        "source_logical_bytes_excluding_active_ledger": logical,
        "deferred_source_logical_bytes": deferred,
        "source_copy_content_bytes": logical,
        "bounded_metadata_and_runtime_bytes": metadata,
        "v14_role_count": len(roles),
        "v14_deferred_role_count": sum(bool(x.get("deferred_content")) for x in roles),
        "v14_preflight_report_bytes": int(_stat(report_path, "V14 report")["bytes"]),
        "v14_required_external_bytes_before_outputs": logical + SAFETY_MARGIN_BYTES,
        "v14_external_reservation_must_cover": "SOURCE_COPY_PLUS_TYPED_OUTPUTS_PLUS_SCRATCH",
        "v14_deferred_role_classes": role_classes["counts"],
        "parent_atomic_same_ledger_reservation": True,
        "parent_ledger_owner": "OUTER_PARENT_ONLY",
        "sparse_placeholders_for_deferred_payloads": False,
    })
    request["estimated_deferred_read_bytes"] = deferred
    request["estimated_deferred_copy_and_posthash_bytes"] = deferred
    request["v14_copy_plan"] = {
        "schema": "ds02.stage2.f2-root242-v14-copy-plan.v1",
        "total_role_count": len(roles),
        "metadata_role_count": len(roles) - sum(bool(x.get("deferred_content")) for x in roles),
        "deferred_role_count": sum(bool(x.get("deferred_content")) for x in roles),
        "logical_source_bytes": logical,
        "metadata_and_runtime_bytes": metadata,
        "deferred_after_reservation_bytes": deferred,
        "copy_and_hash_phase": "PARENT_AFTER_RESERVATION",
        "source_sha_unknown_policy": "FAIL_CLOSED_UNTIL_POSTHASH",
        "source_fallback": "REJECT",
        "role_suffix_counts": suffix_counts,
        "deferred_role_classes": role_classes,
        "deferred_roles_are_consumer_actionable": True,
        "historical_provenance_excluded_by_recursive_policy": True,
        "payload_read_by_builder": False,
    }
    request["root213_metadata_contract"] = {
        "path": str(out_contract), "sha256": contract["sha256"],
    }
    request["sha256"] = _canonical(request)
    request_file_sha = _write(out_request, request)
    validate_request(request=out_request, contract=out_contract)
    return {
        "schema": V14_SCHEMA, "status": "READY_FOR_PARENT_STAGE2_GUARD_V14_RECURSIVE_SOURCE_CLOSURE",
        "contract": {"path": str(out_contract), "file_sha256": contract_file_sha,
                     "canonical_sha256": contract["sha256"]},
        "request": {"path": str(out_request), "file_sha256": request_file_sha,
                     "canonical_sha256": request["sha256"]},
        "preflight": {"path": str(report_path), "file_sha256": report_file_sha,
                       "role_count": report["role_count"], "unbound_count": 0},
        "copy_plan": request["v14_copy_plan"],
        "payload_read": False, "ledger_mutated": False, "launch_performed": False,
    }


def validate_request(*, request: Path | str, contract: Path | str) -> dict[str, Any]:
    request_path = Path(request).expanduser().absolute()
    contract_path = Path(contract).expanduser().absolute()
    base = V13.validate_request(request=request_path, contract=contract_path)
    outer = _json(request_path, "V14 request")
    value = _json(contract_path, "V14 contract")
    source = outer.get("root242_v14_source_binding")
    if not isinstance(source, Mapping) or source.get("schema") != V14_SCHEMA:
        _fail("V14 executor source binding is missing")
    source_path = Path(str(source.get("path", "")))
    if not source_path.is_absolute() or source_path.name != V14_EXECUTOR_NAME:
        _fail("V14 executor source path is not the additive launcher")
    if source.get("sha256") != _sha(source_path, "V14 executor source"):
        _fail("V14 executor source SHA changed")
    preflight = outer.get("root242_v14_preflight_binding")
    if not isinstance(preflight, Mapping) or preflight.get("schema") != V14_PREFLIGHT_SCHEMA:
        _fail("V14 preflight binding is missing")
    report_path = Path(str(preflight.get("path", "")))
    report = _check_report(report_path, Path(str(preflight.get("source_request_path"))))
    if preflight.get("file_sha256") != _sha(report_path, "V14 preflight report"):
        _fail("V14 preflight report SHA changed")
    binding = _source_binding(value)
    roles = binding["roles"]
    if len(roles) != int(report["role_count"]) + 2:
        _fail("V14 contract role count does not include executor/report roles")
    if not any(item.get("logical_role") == V14_EXECUTOR_ROLE for item in roles):
        _fail("V14 executor role is absent")
    if not any(item.get("logical_role") == V14_REPORT_ROLE for item in roles):
        _fail("V14 preflight report role is absent")
    runtime_role = next((item for item in roles
                         if item.get("logical_role") == "portable_rebind_v2_entrypoint"), None)
    if not isinstance(runtime_role, Mapping):
        _fail("V15 list-string runtime role is absent")
    runtime_source = Path(str(runtime_role.get("source_path_provenance", "")))
    if runtime_source.name != V15_RUNTIME_NAME or not runtime_source.is_file():
        _fail("V15 list-string runtime source is not bound")
    if runtime_role.get("source_sha256") != _sha(runtime_source, "V15 runtime source"):
        _fail("V15 list-string runtime SHA differs")
    recursive = value.get("root242_v14_recursive_preflight")
    if not isinstance(recursive, Mapping) or recursive.get("source_file_sha256") != preflight.get("file_sha256"):
        _fail("V14 contract/report binding differs")
    plan = outer.get("v14_copy_plan")
    if not isinstance(plan, Mapping) or plan.get("source_fallback") != "REJECT":
        _fail("V14 copy plan is missing fail-closed policy")
    if outer.get("scope", {}).get("original_path_fallback") != "REJECT":
        _fail("V14 request permits original path fallback")
    return {
        "schema": V14_SCHEMA, "status": "ROOT242_V14_METADATA_VALIDATED_READY_FOR_PARENT",
        "base": base, "role_count": len(roles), "preflight": report["status"],
        "deferred_role_count": plan.get("deferred_role_count"),
        "deferred_bytes": plan.get("deferred_after_reservation_bytes"),
        "payload_read": False, "ledger_mutated": False, "launch_performed": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("source-contract", "source-request", "preflight-report",
                 "output-contract", "output-request", "fresh-root", "home-receipt",
                 "primary-scripts-root"):
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
            result = validate_request(request=args.request, contract=args.contract)
        else:
            result = build_request(
                source_contract=args.source_contract, source_request=args.source_request,
                preflight_report=args.preflight_report,
                output_contract=args.output_contract, output_request=args.output_request,
                fresh_root=args.fresh_root, home_receipt=args.home_receipt,
                case_id=args.case_id, attempt_id=args.attempt_id,
                primary_scripts_root=args.primary_scripts_root,
            )
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root242V14RequestError, V13.Root242V13RequestError, OSError,
            ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT242 V14 source request: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
