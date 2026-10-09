#!/usr/bin/env python3
"""Narrow the ROOT242 recursive discovery into a single-case source handoff.

ROOT242 V7 deliberately recorded every bounded JSON edge it discovered.  That
is useful evidence, but it is not a runnable storage plan: the V7 wrapper has
8,403 input paths and more than 600 GB of logical deferred material.  This
forward builder keeps the explicit ROOT200/179C/V15/runtime graph and the
three payloads referenced by the one typed result.  CURRENT336, the other
case inventories, historical requests, and unrelated native/H5/BI4 edges are
retained as digest/count provenance only.

The builder reads only the already sealed V7 JSON contract/request and source
code metadata.  It does not hash or open a deferred H5, BI4, native frame, or
V16 result.  The resulting handoff is still a source-only parent request;
the parent must implement real post-reservation payload copy/post-hash.  The
legacy V7/V1 sparse-placeholder executor is therefore explicitly rejected by
this contract until a compatible executor consumes ``deferred_payload_policy``.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import os
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024
CONTRACT_SCHEMA = "ds02.stage2.f2-root213-portable-typed-parent-request.v1"
REQUEST_SCHEMA = "ds02.request.v1"
HANDOFF_SCHEMA = "ds02.stage2.f2-root242-v8-single-case-source-binding.v1"
PROVENANCE_PREFIXES = (
    "recursive_v7_", "recursive_metadata_", "nested_directory_anchor",
    "unresolved_or_generated_observation",
)
EXPLICIT_PREFIXES = (
    "root200_", "producer_179c_", "frozen_v15_request", "v12_semantic_sidecar",
    "runtime_", "flux_v16_", "fresh_v16_", "typed_only_", "replay_",
    "root191_", "portable_rebind_", "literal_", "pinned_",
)
PAYLOAD_SUFFIXES = frozenset({".h5", ".hdf5", ".bi4", ".obi4", ".ibi4"})


class Root242V8Error(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise Root242V8Error(message)


def _abs(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        _fail(f"{role} must be an absolute path")
    path = Path(value).expanduser()
    if path.is_symlink():
        _fail(f"{role} may not be a symlink: {path}")
    return path


def _json(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"{role} is not a regular JSON file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        _fail(f"{role} exceeds the bounded metadata limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read {role}: {error}")
    if not isinstance(value, dict):
        _fail(f"{role} must be a JSON object")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _file_sha(path: Path, role: str) -> str:
    if not path.is_file() or path.is_symlink():
        _fail(f"{role} is not a regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        _fail(f"{role} is larger than the source-only bound: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _full_stat(value: Any, role: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        _fail(f"{role} has no stat contract")
    result: dict[str, int] = {}
    for key in ("bytes", "mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        raw = value.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            _fail(f"{role}.{key} is not an integer")
        result[key] = int(raw)
    return result


def _role_is_provenance(item: Mapping[str, Any]) -> bool:
    role = str(item.get("logical_role", "")).lower()
    return role.startswith(PROVENANCE_PREFIXES)


def _keep_role(item: Mapping[str, Any]) -> bool:
    """Return whether this role is in the one ROOT200 typed-consumer graph."""
    role = str(item.get("logical_role", ""))
    lower = role.lower()
    if _role_is_provenance(item):
        return False
    if item.get("administrative_provenance") is True or str(item.get("source_kind", "")).startswith("administrative_"):
        return False
    if lower == "root179c_v16_result_deferred":
        return True
    if lower == "current336_actionable_metadata":
        # CURRENT336 is copied as one bounded catalog identity.  Its case
        # members are an index/provenance surface and are never recursively
        # expanded by V8.
        return True
    if any(lower.startswith(prefix) for prefix in EXPLICIT_PREFIXES):
        return True
    if lower.startswith("closure_"):
        source = str(item.get("source_path_provenance", "")).lower()
        # These are the only recursive closure leaves that the ROOT200 typed
        # result/producer contract can consume.  Other closure rows are
        # seven-family discovery, native input, or historical case material.
        if "/stage2/replay/" in source:
            return True
        if "/scripts/" in source and "ds_data02_stage2_f2_" in source:
            return True
        if "/var/tmp/ds02-stage2/f2/stage2_f2_root145_v66_recovery_root_179c_20261009/" in source:
            names = ("worker-request", "worker-summary", "raw-to-typed-to-label-report",
                     "typed-reconstructed-v2.h5", "v15-reconstructed-label-result-v2.json")
            return any(token in source for token in names)
    return False


def _selected_summary(roles: Sequence[Mapping[str, Any]]) -> tuple[int, int, int, int, dict[str, int], dict[str, int]]:
    logical = deferred = copy_bytes = metadata = 0
    role_counts: dict[str, int] = {}
    suffix_counts: dict[str, int] = {}
    for item in roles:
        stat = item.get("source_stat_provenance") or {}
        size = int(stat.get("bytes", 0) or 0)
        logical += size
        if bool(item.get("deferred_content")):
            deferred += size
        else:
            copy_bytes += size
            metadata += size
        name = str(item.get("logical_role", "")).split("_", 1)[0]
        role_counts[name] = role_counts.get(name, 0) + 1
        suffix = Path(str(item.get("source_path_provenance", ""))).suffix.lower() or "<none>"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
    return logical, deferred, copy_bytes, metadata, role_counts, suffix_counts


def _excluded_summary(roles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    logical = deferred = 0
    role_counts: dict[str, int] = {}
    suffix_counts: dict[str, int] = {}
    for item in roles:
        stat = item.get("source_stat_provenance") or {}
        size = int(stat.get("bytes", 0) or 0)
        logical += size
        deferred += size if bool(item.get("deferred_content")) else 0
        role = str(item.get("logical_role", ""))
        prefix = role.split("_", 1)[0]
        role_counts[prefix] = role_counts.get(prefix, 0) + 1
        suffix = Path(str(item.get("source_path_provenance", ""))).suffix.lower() or "<none>"
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        rows.append({
            "logical_role": role,
            "source_path_provenance": str(item.get("source_path_provenance", "")),
            "source_sha256": item.get("source_sha256"),
            "bytes": size,
            "deferred_content": bool(item.get("deferred_content")),
            "classification": "PROVENANCE_ONLY_NOT_COPIED",
        })
    digest = hashlib.sha256(json.dumps(
        rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
    return {
        "role_count": len(rows), "logical_bytes": logical,
        "deferred_logical_bytes": deferred, "role_prefix_counts": role_counts,
        "suffix_counts": suffix_counts, "roles_sha256": digest,
        "rows_are_digest_only": True,
        "policy": "CURRENT336_AND_HISTORICAL_DISCOVERY_STAT/SHA_ONLY; NO_RECURSIVE_COPY",
    }


def _v7_input_classification(request: Mapping[str, Any],
                             roles_by_path: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Summarise V7's outer input list without opening any input payload."""
    counts: dict[str, int] = {}
    logical: dict[str, int] = {}
    deferred: dict[str, int] = {}
    unbound = 0
    unbound_bytes = 0
    for raw in request.get("input_files", []):
        path = str(raw)
        item = roles_by_path.get(path)
        if item is None:
            unbound += 1
            # The five V7 administrative/generated entries are not part of
            # the scientific role table.  Their declared bytes remain a
            # small metadata audit number, never an execution input.
            stat = request.get("input_sha256", {}).get(path)
            if isinstance(stat, str):
                unbound_bytes += 0
            continue
        role = str(item.get("logical_role", ""))
        if role.startswith("recursive_v7_"):
            bucket = "recursive_discovery"
        elif role.startswith("recursive_metadata_"):
            bucket = "recursive_nested_metadata"
        elif role.startswith("closure_"):
            bucket = "closure_role"
        elif role.startswith(PROVENANCE_PREFIXES[2:]):
            bucket = "provenance_anchor"
        elif role.startswith(EXPLICIT_PREFIXES) or role == "root179c_v16_result_deferred":
            bucket = "explicit_single_case"
        else:
            bucket = "other"
        size = int((item.get("source_stat_provenance") or {}).get("bytes", 0) or 0)
        counts[bucket] = counts.get(bucket, 0) + 1
        logical[bucket] = logical.get(bucket, 0) + size
        if bool(item.get("deferred_content")):
            deferred[bucket] = deferred.get(bucket, 0) + size
    return {"input_file_count": len(request.get("input_files", [])),
            "buckets": counts, "logical_bytes": logical,
            "deferred_logical_bytes": deferred,
            "unbound_generated_or_contract_entries": unbound,
            "unbound_entries_are_not_scientific_inputs": True}


def _runtime_binding(primary_root: Path, relative: str, role: str) -> dict[str, Any]:
    source = primary_root / relative
    sha = _file_sha(source, role)
    st = source.stat()
    return {"path": str(source), "file_sha256": sha,
            "stat": {"bytes": int(st.st_size), "mode_bits": int(st.st_mode & 0o7777),
                      "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns),
                      "st_dev": int(st.st_dev), "st_ino": int(st.st_ino)}}


def build_request(*, source_contract: Path | str, source_request: Path | str,
                  output_contract: Path | str, output_request: Path | str,
                  fresh_root: Path | str, home_receipt: Path | str,
                  case_id: str, attempt_id: str,
                  primary_scripts_root: Path | str) -> dict[str, Any]:
    src_contract_path = _abs(str(source_contract), "ROOT242 V7 contract")
    src_request_path = _abs(str(source_request), "ROOT242 V7 request")
    out_contract = _abs(str(output_contract), "ROOT242 V8 contract output")
    out_request = _abs(str(output_request), "ROOT242 V8 request output")
    fresh_root_path = _abs(str(fresh_root), "ROOT242 V8 fresh root")
    receipt = _abs(str(home_receipt), "ROOT242 V8 Home receipt")
    if out_contract.exists() or out_request.exists() or fresh_root_path.exists() or receipt.exists():
        _fail("ROOT242 V8 output or target already exists; refusing overwrite")
    if "ROOT242" not in case_id or "root-forward-242-" not in attempt_id:
        _fail("case/attempt must carry a fresh ROOT242 forward identity")
    source = _json(src_contract_path, "ROOT242 V7 contract")
    source_request_value = _json(src_request_path, "ROOT242 V7 request")
    if source.get("schema") != CONTRACT_SCHEMA or source.get("sha256") != _canonical(source):
        _fail("ROOT242 V7 contract schema/canonical SHA differs")
    if source_request_value.get("schema") != REQUEST_SCHEMA or source_request_value.get("sha256") != _canonical(source_request_value):
        _fail("ROOT242 V7 request schema/canonical SHA differs")
    old_roles = source.get("root242_source_binding", {}).get("roles")
    if not isinstance(old_roles, list) or not old_roles:
        _fail("ROOT242 V7 role table is missing")
    selected = [copy.deepcopy(item) for item in old_roles if isinstance(item, Mapping) and _keep_role(item)]
    excluded = [item for item in old_roles if isinstance(item, Mapping) and not _keep_role(item)]
    if not selected:
        _fail("ROOT242 V8 selected role table is empty")

    # The V8 entrypoint and its inherited source siblings are bound to the
    # primary checkout at build time.  Runtime code is the only source path
    # intentionally rebased here; scientific/provenance paths retain their
    # frozen path+SHA evidence and are checked by the parent after reserve.
    primary_root = _abs(str(primary_scripts_root), "primary scripts root")
    script_rel = "lagrangian-fluid-lab/scripts"
    runtime_files = {
        "v8_executor": "ds_data02_stage2_f2_root213_portable_typed_executor_v8.py",
        "v7_executor": "ds_data02_stage2_f2_root213_portable_typed_executor_v7.py",
        "v7_rebind_runtime": "ds_data02_stage2_f2_typed_only_portable_rebind_v7.py",
        "v2_rebind_runtime": "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py",
        "runtime_v6_import": "ds_data02_runtime_v6.py",
    }
    runtime_bindings = {}
    for role, filename in runtime_files.items():
        runtime_bindings[role] = _runtime_binding(
            primary_root, f"{script_rel}/{filename}", f"primary {role}")
    by_role = {str(item.get("logical_role")): item for item in selected}
    roles_by_path = {str(item.get("source_path_provenance")): item
                     for item in old_roles if isinstance(item, Mapping)}
    v7_input_classification = _v7_input_classification(source_request_value, roles_by_path)
    for role in ("v7_executor", "v7_rebind_runtime", "v2_rebind_runtime", "runtime_v6_import"):
        if role in by_role:
            binding = runtime_bindings[role]
            item = by_role[role]
            item["source_path_provenance"] = binding["path"]
            item["source_sha256"] = binding["file_sha256"]
            item["source_stat_provenance"] = binding["stat"]
            item["source_sha256_basis"] = "PRIMARY_RUNTIME_SOURCE_AT_V8_BUILD"
    v8_item = {
        "logical_role": "v8_executor", "source_kind": "runtime_source_forward_v8",
        "actionable": True, "content_read_by_manifest": True,
        "source_sha256": runtime_bindings["v8_executor"]["file_sha256"],
        "source_sha256_basis": "PRIMARY_RUNTIME_SOURCE_AT_V8_BUILD",
        "source_stat_provenance": runtime_bindings["v8_executor"]["stat"],
        "source_path_provenance": runtime_bindings["v8_executor"]["path"],
        "target_relative_path": "runtime/ds_data02_stage2_f2_root213_portable_typed_executor_v8.py",
        "target_stat": None, "target_sha256": None, "content_sha_verified": False,
        "content_verification_phase": "SEAL_METADATA", "deferred_content": False,
        "placeholder_only": False, "source_inode_mtime_equivalence": "NOT_CLAIMED",
    }
    selected = [item for item in selected if str(item.get("logical_role")) != "v8_executor"]
    selected.append(v8_item)
    selected.sort(key=lambda item: str(item.get("logical_role")))

    logical, deferred, copy_bytes, metadata_bytes, role_counts, suffix_counts = _selected_summary(selected)
    excluded_meta = _excluded_summary(excluded)
    role_digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()

    contract = copy.deepcopy(source)
    contract.update({
        "case_id": case_id, "attempt_id": attempt_id,
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "forward_version": "ROOT242_V8_SINGLE_CASE_SOURCE_ONLY",
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "ledger_mutated": False, "source_content_read_by_builder": False,
    })
    binding = dict(contract.get("root242_source_binding") or {})
    binding.update({
        "schema": HANDOFF_SCHEMA, "closure_mode": "SINGLE_CASE_EXPLICIT_GRAPH",
        "roles": selected, "selected_role_count": len(selected),
        "selected_roles_sha256": role_digest, "role_counts": role_counts,
        "suffix_counts": suffix_counts, "logical_bytes": logical,
        "deferred_logical_bytes": deferred, "metadata_bytes": metadata_bytes,
        "source_copy_logical_bytes": logical,
        "source_copy_content_bytes": copy_bytes + deferred,
        "excluded_provenance": excluded_meta,
        "current336_policy": "COPY_ONE_CATALOG_IDENTITY; DO_NOT_RECURSE_CASE_ROWS",
        "historical_request_policy": "STAT_SHA_PROVENANCE_ONLY_UNLESS_EXPLICIT_SELECTED_ROLE",
        "deferred_payload_policy": {
            "roles": [str(item["logical_role"]) for item in selected if item.get("deferred_content")],
            "copy_after_parent_reservation": True,
            "post_copy_sha_and_full_stat": True,
            "sparse_placeholder_is_forbidden": True,
            "legacy_v7_v1_sparse_executor": "REJECT",
        },
        "original_path_fallback": "REJECT",
        "active_ledger": "ADMIN_REFERENCE_ONLY_OUTER_PARENT_MUTATES_SHARED_LEDGER",
        "selected_roles_are_not_scientific_qualification": True,
        "v7_input_classification": v7_input_classification,
    })
    contract["root242_source_binding"] = binding
    relocation = dict(contract.get("relocation") or {})
    relocation.update({"fresh_output_root": str(fresh_root_path),
                       "target_runtime_root": str(fresh_root_path / "runtime"),
                       "target_evidence_root": str(fresh_root_path / "evidence"),
                       "target_product_root": str(fresh_root_path / "products"),
                       "target_home_receipt_path": str(receipt),
                       "source_provenance_only": True, "original_absolute_path_fallback": "REJECT"})
    contract["relocation"] = relocation
    interface = dict(contract.get("v2_interface") or {})
    v8_path = runtime_bindings["v8_executor"]["path"]
    interface.update({
        "schema": "ds02.stage2.f2-root242-v8-interface.v1",
        "source_script": v8_path,
        "source_script_sha256": runtime_bindings["v8_executor"]["file_sha256"],
        "literal_python": str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")),
        "parent_reservation_before_source_hash_or_payload_read": True,
        "deferred_payload_copy_after_reservation": True,
        "max_wall_seconds": 900, "cpu_threads": 1, "max_memory_bytes": 16 * 1024**3,
        "command_template": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", "-B", "-I", "-c",
                              "import os,sys,json;sys.path.insert(0,sys.argv[1]);from ds_data02_stage2_f2_root213_portable_typed_executor_v8 import run;r=run(request_path=sys.argv[2],output_root=sys.argv[3],parent_pid=os.getppid(),max_wall_seconds=900);print(json.dumps(r,sort_keys=True))",
                              str(primary_root / script_rel), "{root242_v8_contract}", str(fresh_root_path)],
        "no_h5_bi4_native_read_by_source_builder": True,
        "typed_only_result_read_after_reservation_bytes": next((int((item.get("source_stat_provenance") or {}).get("bytes", 0)) for item in selected if item.get("logical_role") == "root179c_v16_result_deferred"), 0),
    })
    contract["v2_interface"] = interface
    contract["sha256"] = _canonical(contract)
    contract_text = json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    contract_file_sha = hashlib.sha256(contract_text.encode()).hexdigest()

    request = copy.deepcopy(source_request_value)
    request.update({
        "case_id": case_id, "attempt_id": attempt_id,
        "status": "READY_FOR_PARENT_STAGE2_GUARD",
        "command": interface["command_template"],
        "root213_metadata_contract": {"path": str(out_contract), "sha256": contract["sha256"]},
        "root242_v8_source_binding": {
            "contract_path": str(out_contract), "contract_sha256": contract["sha256"],
            "selected_roles": len(selected), "selected_roles_sha256": role_digest,
            "excluded_provenance": excluded_meta,
            "v7_input_classification": v7_input_classification,
            "metadata_only_builder": True, "parent_after_reservation_copy_and_trace": True,
        },
        "storage_scope": {
            "external_filesystem": str(fresh_root_path), "external_reservation_bytes": 12 * 1024**3,
            "home_receipt_path": str(receipt), "home_reservation_bytes": 4 * 1024**3,
            "home_receipt_reserved_bytes": 512 * 1024**2,
            "source_logical_bytes_excluding_active_ledger": logical,
            "deferred_source_logical_bytes": deferred,
            "source_copy_content_bytes": copy_bytes + deferred,
            "bounded_metadata_and_runtime_bytes": metadata_bytes,
            "excluded_provenance_logical_bytes": excluded_meta["logical_bytes"],
            "parent_atomic_same_ledger_reservation": True,
            "parent_ledger_owner": "OUTER_PARENT_ONLY",
            "sparse_placeholders_for_deferred_payloads": False,
        },
        "estimated_storage_bytes": 12 * 1024**3,
        "estimated_result_JSON_read_bytes": interface["typed_only_result_read_after_reservation_bytes"],
        "estimated_deferred_read_bytes": interface["typed_only_result_read_after_reservation_bytes"],
        "estimated_hdf5_read_bytes": 0, "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "scope": {"no_raw_H5_BI4_read_by_builder": True, "model_invoked": False,
                  "cfd_invoked": False, "original_path_fallback": "REJECT",
                  "cold_replay_credit": "NOT_CLAIMED",
                  "source_only_probe_is_not_reserved_execution_or_result_credit": True},
        "launch_allowed": True, "execution_allowed": True,
        "worktree_root": str(primary_root), "cwd": str(primary_root / "lagrangian-fluid-lab"),
        "interpreter_binding": {"invocation_path": interface["literal_python"], "argv0_literal": True,
                                "do_not_resolve_argv0": True},
        "input_files": [], "input_sha256": {}, "deferred_input_files": [],
        "deferred_input_records": [], "deferred_input_sha256": {},
    })
    # Only selected roles are source inputs.  The V8 contract itself and the
    # primary runtime are added as small static inputs; payload SHA values are
    # inherited declared identities and are not recomputed here.
    for item in selected:
        path = str(item["source_path_provenance"])
        if path in request["input_files"]:
            continue
        request["input_files"].append(path)
        request["input_sha256"][path] = str(item["source_sha256"])
        if bool(item.get("deferred_content")):
            stat = dict(item.get("source_stat_provenance") or {})
            request["deferred_input_files"].append(path)
            request["deferred_input_sha256"][path] = str(item["source_sha256"])
            request["deferred_input_records"].append({"path": path, "role": item["logical_role"],
                "sha256": item["source_sha256"], "bytes": int(stat.get("bytes", 0)),
                **{key: stat[key] for key in ("mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino") if key in stat},
                "copy_after_parent_reservation": True, "post_copy_sha_and_stat": True,
                "content_read_after_reservation": item["logical_role"] == "root179c_v16_result_deferred"})
    request["input_files"].append(str(out_contract))
    request["input_sha256"][str(out_contract)] = contract_file_sha
    request["source_only_expected_copy_roles"] = {
        "contract_path": str(out_contract), "contract_sha256": contract["sha256"],
        "role_count": len(selected), "roles_sha256": role_digest,
        "copy_content_bytes": copy_bytes + deferred,
        "deferred_payload_bytes": deferred,
        "excluded_provenance": excluded_meta,
        "metadata_only_builder": True,
    }
    request["root_forward_provenance"] = {
        "source_request": str(src_request_path), "source_request_sha256": _file_sha(src_request_path, "V7 request"),
        "source_contract": str(src_contract_path), "source_contract_sha256": _file_sha(src_contract_path, "V7 contract"),
        "immutable_forward_of": True, "large_payloads_not_read_by_builder": True,
        "old_root_poison_check_required": True, "os_open_trace_required": True,
    }
    request["sha256"] = _canonical(request)
    out_contract.parent.mkdir(parents=True, exist_ok=True)
    out_request.parent.mkdir(parents=True, exist_ok=True)
    out_contract.write_text(contract_text, encoding="utf-8")
    out_request.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    return {"schema": HANDOFF_SCHEMA, "status": "READY_FOR_PARENT_STAGE2_GUARD_V8_SOURCE_ONLY",
            "contract": {"path": str(out_contract), "file_sha256": _file_sha(out_contract, "V8 contract"), "canonical_sha256": contract["sha256"]},
            "request": {"path": str(out_request), "file_sha256": _file_sha(out_request, "V8 request"), "canonical_sha256": request["sha256"]},
            "selected": {"role_count": len(selected), "logical_bytes": logical, "metadata_bytes": metadata_bytes,
                          "deferred_bytes": deferred, "copy_content_bytes": copy_bytes + deferred,
                          "roles_sha256": role_digest},
            "excluded_provenance": excluded_meta,
            "payload_read": False, "ledger_mutated": False, "launch_performed": False,
            "legacy_v7_sparse_executor": "REJECTED_BY_CONTRACT"}


def validate_request(*, request: Path | str, contract: Path | str) -> dict[str, Any]:
    """Validate the narrow JSON handoff without touching deferred content."""
    request_path = _abs(str(request), "ROOT242 V8 request")
    contract_path = _abs(str(contract), "ROOT242 V8 contract")
    outer = _json(request_path, "ROOT242 V8 request")
    inner = _json(contract_path, "ROOT242 V8 contract")
    if outer.get("schema") != REQUEST_SCHEMA or outer.get("sha256") != _canonical(outer):
        _fail("ROOT242 V8 request schema/canonical SHA differs")
    if inner.get("schema") != CONTRACT_SCHEMA or inner.get("sha256") != _canonical(inner):
        _fail("ROOT242 V8 contract schema/canonical SHA differs")
    binding = inner.get("root242_source_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != HANDOFF_SCHEMA:
        _fail("ROOT242 V8 single-case binding is missing")
    roles = binding.get("roles")
    if not isinstance(roles, list) or not roles:
        _fail("ROOT242 V8 role table is empty")
    if any(_role_is_provenance(item) for item in roles if isinstance(item, Mapping)):
        _fail("ROOT242 V8 copied role table contains recursive provenance rows")
    if any(str(item.get("logical_role", "")).lower() == "admin_live_ledger_reference"
           for item in roles if isinstance(item, Mapping)):
        _fail("ROOT242 V8 copied role table contains the mutable ledger")
    expected_digest = hashlib.sha256(json.dumps(
        roles, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
    if binding.get("selected_roles_sha256") != expected_digest:
        _fail("ROOT242 V8 selected role digest differs")
    if outer.get("root213_metadata_contract", {}).get("path") != str(contract_path):
        _fail("ROOT242 V8 request does not bind the exact contract path")
    if outer.get("root213_metadata_contract", {}).get("sha256") != inner.get("sha256"):
        _fail("ROOT242 V8 request/contract SHA binding differs")
    if outer.get("root242_v8_source_binding", {}).get("selected_roles_sha256") != expected_digest:
        _fail("ROOT242 V8 outer role digest differs")
    deferred = [item for item in roles if isinstance(item, Mapping) and item.get("deferred_content")]
    if len(deferred) != 3 or not all(Path(str(item.get("source_path_provenance", ""))).suffix.lower() in PAYLOAD_SUFFIXES | {".json"} for item in deferred):
        _fail("ROOT242 V8 deferred payload scope is not the bounded one-case set")
    scope = outer.get("storage_scope")
    if not isinstance(scope, Mapping) or int(scope.get("external_reservation_bytes", 0)) < int(scope.get("source_logical_bytes_excluding_active_ledger", 0)):
        _fail("ROOT242 V8 external reservation does not cover selected logical source bytes")
    if outer.get("scope", {}).get("original_path_fallback") != "REJECT":
        _fail("ROOT242 V8 permits original-path fallback")
    return {"schema": HANDOFF_SCHEMA, "status": "ROOT242_V8_METADATA_VALIDATED_READY_FOR_PARENT",
            "request": {"path": str(request_path), "file_sha256": _file_sha(request_path, "V8 request"),
                        "canonical_sha256": outer["sha256"]},
            "contract": {"path": str(contract_path), "file_sha256": _file_sha(contract_path, "V8 contract"),
                         "canonical_sha256": inner["sha256"]},
            "selected_role_count": len(roles),
            "selected_logical_bytes": int(scope["source_logical_bytes_excluding_active_ledger"]),
            "deferred_payload_bytes": int(scope["deferred_source_logical_bytes"]),
            "excluded_provenance": binding["excluded_provenance"],
            "payload_read": False, "ledger_mutated": False, "launch_performed": False,
            "legacy_v7_sparse_executor": "REJECTED_BY_CONTRACT"}


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
            result = validate_request(request=args.request, contract=args.contract)
        else:
            result = build_request(source_contract=args.source_contract, source_request=args.source_request,
                                   output_contract=args.output_contract, output_request=args.output_request,
                                   fresh_root=args.fresh_root, home_receipt=args.home_receipt,
                                   case_id=args.case_id, attempt_id=args.attempt_id,
                                   primary_scripts_root=args.primary_scripts_root)
    except (Root242V8Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT242 V8 source request: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
