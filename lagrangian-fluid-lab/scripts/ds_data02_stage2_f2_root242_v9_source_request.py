#!/usr/bin/env python3
"""Build the executable ROOT242 V9 source handoff.

V8 deliberately stopped at a narrow role table.  The first actual copied V2
+worker exposed one remaining boundary: the ROOT200 request recursively opens
+the ROOT194/ROOT190 request and sidecar views, and the copied producer report
+is a runtime input even though it is a leaf in the metadata graph.  V9 keeps
V8 immutable and adds exactly the bounded JSON roles reached by the real V5
rebinder.  It does not restore the V7 recursive discovery tree.

The builder only reads bounded JSON/code metadata.  Deferred H5/JSON payloads
are represented by their declared SHA/stat and are copied only by the V9
executor after the outer parent has reserved storage.  No ledger is created or
mutated here.
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
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root242_v8_source_request.py"
V5_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_portable_rebind_v5.py"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V8 = _load(V8_SCRIPT, "ds02_root242_v8_builder_for_v9")
V5 = _load(V5_SCRIPT, "ds02_root242_v5_rebinder_for_v9")

HANDOFF_SCHEMA = "ds02.stage2.f2-root242-v9-single-case-source-binding.v1"
V9_EXECUTOR_NAME = "ds_data02_stage2_f2_root242_portable_typed_executor_v9.py"


class Root242V9Error(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise Root242V9Error(message)


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha(path: Path, role: str, maximum: int = 32 * 1024 * 1024) -> str:
    if path.is_symlink() or not path.is_file():
        _fail(f"{role} is not a regular non-symlink file: {path}")
    if path.stat().st_size > maximum:
        _fail(f"{role} exceeds the source-only hash limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, role: str) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        _fail(f"{role} is not a regular non-symlink file: {path}")
    value = path.stat()
    return {"bytes": int(value.st_size), "mode_bits": int(value.st_mode & 0o7777),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _json(path: Path, role: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail(f"{role} is not a regular non-symlink JSON file: {path}")
    if path.stat().st_size > 32 * 1024 * 1024:
        _fail(f"{role} exceeds the bounded metadata limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read {role}: {error}")
    if not isinstance(value, dict):
        _fail(f"{role} must be a JSON object")
    return value


def _abs(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        _fail(f"{role} must be absolute")
    return Path(value).expanduser()


def _discover_nested_sources(v7_contract: Mapping[str, Any], inner: Mapping[str, Any],
                             inner_path: Path) -> list[str]:
    """Run the actual V5 JSON rewriter against a throwaway target namespace.

    This is a metadata-only preflight.  V5 opens only JSON files no larger than
    its bounded metadata limit and reports every source path it materialises;
    H5/BI4/native payloads cannot enter this walk.
    """
    roles = v7_contract.get("root242_source_binding", {}).get("roles")
    if not isinstance(roles, list):
        _fail("V7 contract lacks its role table")
    source_map: dict[str, tuple[Mapping[str, Any], Path]] = {}
    with tempfile.TemporaryDirectory(prefix="root242-v9-metadata-") as temporary:
        root = Path(temporary)
        for index, item in enumerate(roles):
            if not isinstance(item, Mapping):
                continue
            source = item.get("source_path_provenance")
            if not isinstance(source, str) or not source.startswith("/"):
                continue
            source_map[os.path.abspath(source)] = (item, root / "source-map" / str(index))
        if os.path.abspath(str(inner_path)) not in source_map:
            _fail("ROOT200 inner request is not in the V7 source map")
        old_directory_rebind = V5.V2._directory_rebind
        old_target_view = V5._target_view
        materialised: list[str] = []

        def _record_target(target_root: Path, source: Path, label: str) -> Path:
            materialised.append(os.path.abspath(str(source)))
            return old_target_view(target_root, source, label)

        V5.V2._directory_rebind = V5._directory_rebind_v5
        V5._target_view = _record_target
        try:
            V5._recursive_rebase(inner_path, root=root, source_map=source_map,
                                 label="root242-v9-root200")
        except Exception as error:
            _fail(f"V5 recursive source-closure preflight failed: {error}")
        finally:
            V5.V2._directory_rebind = old_directory_rebind
            V5._target_view = old_target_view
    # Preserve first-seen order for audit readability while making the result
    # deterministic across Python mapping implementations.
    return list(dict.fromkeys(materialised))


def _role_for_path(roles: Sequence[Mapping[str, Any]], source: str) -> Mapping[str, Any] | None:
    source_abs = os.path.abspath(source)
    for item in roles:
        if isinstance(item, Mapping) and isinstance(item.get("source_path_provenance"), str):
            if os.path.abspath(str(item["source_path_provenance"])) == source_abs:
                return item
    return None


def _new_target(source: str, sha: str, *, prefix: str = "nested-v9") -> str:
    name = Path(source).name or "metadata.json"
    safe = "".join(character if character.isalnum() or character in "._-" else "_"
                    for character in name)
    return f"evidence/{prefix}/{sha[:16]}-{safe}"


def _update_role(item: Mapping[str, Any], *, target: str, logical: str | None = None,
                 source_kind: str = "nested_metadata_v9") -> dict[str, Any]:
    result = copy.deepcopy(dict(item))
    if logical is not None:
        result["logical_role"] = logical
    result["target_relative_path"] = target
    result["source_kind"] = source_kind
    result["content_read_by_manifest"] = True
    result["deferred_content"] = False
    result["placeholder_only"] = False
    result["content_sha_verified"] = False
    result["target_stat"] = None
    result["target_sha256"] = None
    result["content_verification_phase"] = "PARENT_AFTER_RESERVATION"
    result["source_sha256_basis"] = "V7_DECLARED_BOUNDED_JSON_ROLE"
    return result


def _refresh_request_inputs(request: dict[str, Any], contract: Mapping[str, Any],
                            roles: Sequence[Mapping[str, Any]],
                            contract_path: Path, contract_file_sha: str) -> None:
    request["input_files"] = []
    request["input_sha256"] = {}
    request["deferred_input_files"] = []
    request["deferred_input_sha256"] = {}
    request["deferred_input_records"] = []
    for item in roles:
        path = str(item["source_path_provenance"])
        if path in request["input_sha256"]:
            continue
        request["input_files"].append(path)
        request["input_sha256"][path] = str(item["source_sha256"])
        if bool(item.get("deferred_content")):
            stat = dict(item.get("source_stat_provenance") or {})
            request["deferred_input_files"].append(path)
            request["deferred_input_sha256"][path] = str(item["source_sha256"])
            request["deferred_input_records"].append({
                "path": path, "role": item["logical_role"],
                "sha256": item["source_sha256"],
                "bytes": int(stat.get("bytes", 0)),
                **{key: stat[key] for key in ("mode_bits", "mtime_ns", "ctime_ns",
                                                "st_dev", "st_ino") if key in stat},
                "copy_after_parent_reservation": True,
                "post_copy_sha_and_stat": True,
                "content_read_after_reservation": True,
            })
    request["input_files"].append(str(contract_path))
    request["input_sha256"][str(contract_path)] = contract_file_sha
    # The V8 builder leaves this pointer bound to the pre-forward contract.
    # Refresh it here, after every V9 role/interface mutation.  The pointer
    # carries the contract's canonical (content-without-sha256) digest; the
    # input_sha256 entry carries the serialized file digest.  They are
    # intentionally different identities and both are checked by validate.
    request["root213_metadata_contract"] = {
        "path": str(contract_path),
        "sha256": str(contract.get("sha256", "")),
    }


def _recompute(contract: dict[str, Any], request: dict[str, Any],
               out_contract: Path) -> tuple[str, str]:
    contract["sha256"] = _canonical(contract)
    contract_text = json.dumps(contract, indent=2, sort_keys=True,
                               ensure_ascii=True, allow_nan=False) + "\n"
    out_contract.write_text(contract_text, encoding="utf-8")
    contract_file_sha = hashlib.sha256(contract_text.encode("utf-8")).hexdigest()
    request["root213_metadata_contract"] = {
        "path": str(out_contract), "sha256": contract["sha256"]}
    request["input_sha256"][str(out_contract)] = contract_file_sha
    request["sha256"] = _canonical(request)
    return contract_file_sha, contract["sha256"]


def build_request(*, source_contract: Path | str, source_request: Path | str,
                  output_contract: Path | str, output_request: Path | str,
                  fresh_root: Path | str, home_receipt: Path | str,
                  case_id: str, attempt_id: str,
                  primary_scripts_root: Path | str) -> dict[str, Any]:
    # Capture the broad V7 role table before V8 potentially rebinds
    # ``root_forward_provenance.source_contract`` to its immediate input.
    # A primary V8 request therefore carries the original V7 path in its
    # provenance, while a direct V7 input is already the correct discovery
    # table.  The recursive preflight needs that broad table only to resolve
    # metadata edges; it never expands the V9 copy role set implicitly.
    source_contract_path = Path(source_contract).expanduser().absolute()
    source_request_path = Path(source_request).expanduser().absolute()
    source_contract_value = _json(source_contract_path, "V9 source contract")
    discovery_contract_path = source_contract_path
    if "V8" in str(source_contract_value.get("forward_version", "")):
        source_request_value = _json(source_request_path, "V9 source request")
        provenance = source_request_value.get("root_forward_provenance")
        candidate = provenance.get("source_contract") if isinstance(provenance, Mapping) else None
        if isinstance(candidate, str) and candidate.startswith("/"):
            discovery_contract_path = Path(candidate)
    # V8 remains an immutable input.  It supplies the narrow selected table;
    # the V7 contract is used only to resolve the actual recursive JSON edge
    # set exposed by the V5 rebinder.
    result = V8.build_request(
        source_contract=source_contract, source_request=source_request,
        output_contract=output_contract, output_request=output_request,
        fresh_root=fresh_root, home_receipt=home_receipt,
        case_id=case_id, attempt_id=attempt_id,
        primary_scripts_root=primary_scripts_root)
    out_contract = Path(output_contract)
    out_request = Path(output_request)
    contract = _json(out_contract, "V8 contract")
    request = _json(out_request, "V8 request")
    v7_contract_path = _abs(str(discovery_contract_path), "V7 source contract")
    v7_contract = _json(v7_contract_path, "V7 source contract")
    selected = [copy.deepcopy(item) for item in contract["root242_source_binding"]["roles"]]
    selected_by_source = {
        os.path.abspath(str(item["source_path_provenance"])): item for item in selected}
    v7_roles = v7_contract.get("root242_source_binding", {}).get("roles", [])
    if not isinstance(v7_roles, list):
        _fail("V7 role table is malformed")
    inner_role = _role_for_path(v7_roles, next(
        str(item["source_path_provenance"]) for item in selected
        if item.get("logical_role") == "root200_inner_request"))
    if inner_role is None:
        _fail("V7 source map has no ROOT200 inner request")
    inner_path = Path(str(inner_role["source_path_provenance"]))
    discovered = _discover_nested_sources(v7_contract, _json(inner_path, "ROOT200 inner"), inner_path)
    required_paths = list(discovered)
    producer_role = _role_for_path(v7_roles, next(
        str(item["source_path_provenance"]) for item in v7_roles
        if item.get("logical_role") == "producer_nested_report_v2"))
    if producer_role is None:
        _fail("V7 source map has no producer nested report")
    required_paths.append(str(producer_role["source_path_provenance"]))
    added: list[str] = []
    used_roles = {str(item.get("logical_role")) for item in selected}
    used_targets = {str(item.get("target_relative_path")) for item in selected}
    for source in required_paths:
        source_abs = os.path.abspath(source)
        if source_abs in selected_by_source:
            continue
        candidate = _role_for_path(v7_roles, source)
        if candidate is None:
            _fail(f"recursive source path has no V7 declaration: {source}")
        sha = str(candidate.get("source_sha256", ""))
        if len(sha) != 64:
            _fail(f"recursive source role has no declared SHA: {source}")
        logical = str(candidate.get("logical_role", ""))
        if not logical or logical in used_roles:
            logical = f"v9_nested_{sha[:16]}"
        target = _new_target(source, sha)
        while target in used_targets:
            target = _new_target(source, _sha_text(target), prefix="nested-v9-alt")
        added_role = _update_role(candidate, target=target, logical=logical)
        selected.append(added_role)
        selected_by_source[source_abs] = added_role
        used_roles.add(logical)
        used_targets.add(target)
        added.append(source_abs)
    # The producer report is a leaf in V5's recursive graph but is consumed by
    # V2's runtime binding, so keep its stable logical role as well.
    producer_source = os.path.abspath(str(producer_role["source_path_provenance"]))
    producer_selected = selected_by_source.get(producer_source)
    if producer_selected is None:
        _fail("producer nested report was not selected")
    producer_selected["logical_role"] = "producer_nested_report_v2"
    selected.sort(key=lambda item: str(item.get("logical_role")))
    logical, deferred, copy_bytes, metadata_bytes, role_counts, suffix_counts = V8._selected_summary(selected)
    role_digest = hashlib.sha256(json.dumps(
        selected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
    executor_source = Path(primary_scripts_root) / "lagrangian-fluid-lab" / "scripts" / V9_EXECUTOR_NAME
    if not executor_source.is_file():
        # The local build remains useful before cherry-pick; primary rebuilds
        # bind this role to the same relative script under its own checkout.
        executor_source = SCRIPT
    executor_sha = _file_sha(executor_source, "V9 executor source")
    executor_stat = _stat(executor_source, "V9 executor source")
    selected = [item for item in selected if str(item.get("logical_role")) != "v9_executor"]
    selected.append({
        "logical_role": "v9_executor", "source_kind": "runtime_source_forward_v9",
        "actionable": True, "content_read_by_manifest": True,
        "source_sha256": executor_sha, "source_sha256_basis": "PRIMARY_RUNTIME_SOURCE_AT_V9_BUILD",
        "source_stat_provenance": executor_stat, "source_path_provenance": str(executor_source),
        "target_relative_path": f"runtime/{V9_EXECUTOR_NAME}", "target_stat": None,
        "target_sha256": None, "content_sha_verified": False,
        "content_verification_phase": "SEAL_METADATA", "deferred_content": False,
        "placeholder_only": False, "source_inode_mtime_equivalence": "NOT_CLAIMED",
    })
    selected.sort(key=lambda item: str(item.get("logical_role")))
    logical, deferred, copy_bytes, metadata_bytes, role_counts, suffix_counts = V8._selected_summary(selected)
    role_digest = hashlib.sha256(json.dumps(
        selected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()
    binding = dict(contract.get("root242_source_binding") or {})
    binding.update({
        "schema": HANDOFF_SCHEMA,
        "closure_mode": "SINGLE_CASE_EXPLICIT_GRAPH_V9_RECURSIVE_JSON",
        "roles": selected, "selected_role_count": len(selected),
        "selected_roles_sha256": role_digest, "role_counts": role_counts,
        "suffix_counts": suffix_counts, "logical_bytes": logical,
        "deferred_logical_bytes": deferred, "metadata_bytes": metadata_bytes,
        "source_copy_logical_bytes": logical, "source_copy_content_bytes": logical,
        "recursive_metadata_closure": {
            "preflight": "V5_REAL_RECURSIVE_REBASE",
            "discovered_source_paths": sorted(set(discovered)),
            "discovered_source_paths_sha256": _sha_text(json.dumps(sorted(set(discovered)), separators=(",", ":"))),
            "added_role_count": len(added), "added_source_paths": sorted(added),
            "payload_content_read": False,
            "unbound_actionable_path_policy": "REJECT",
        },
        "executor": {"logical_role": "v9_executor", "target_relative_path": f"runtime/{V9_EXECUTOR_NAME}",
                     "source_sha256": executor_sha},
        "portable_cold_replay_credit": "NOT_CLAIMED",
        "original_path_fallback": "REJECT",
        "legacy_v7_sparse_executor": "REJECTED_BY_CONTRACT",
    })
    contract["root242_source_binding"] = binding
    contract["forward_version"] = "ROOT242_V9_EXECUTABLE_SINGLE_CASE_SOURCE_ONLY"
    interface = dict(contract.get("v2_interface") or {})
    interface.update({
        "schema": "ds02.stage2.f2-root242-v9-interface.v1",
        "source_script": str(executor_source), "source_script_sha256": executor_sha,
        "executor_role": "v9_executor",
        "command_template": [interface.get("literal_python"), "-B", "-I", "-c",
                              "import os,sys;sys.path.insert(0,sys.argv[1]);from ds_data02_stage2_f2_root242_portable_typed_executor_v9 import main;raise SystemExit(main(sys.argv[2:]))",
                              str(Path(primary_scripts_root) / "lagrangian-fluid-lab" / "scripts"),
                              "run", "--request", "{root242_v9_request}", "--output-root", "{root242_v9_fresh_root}",
                              "--parent-pid", "{parent_pid}", "--max-wall-seconds", "900"],
        "recursive_metadata_overlay_after_copy": True,
        "strict_child_runtime_fallback": "REJECT",
        "deferred_payload_copy_and_posthash_bytes": deferred,
        "scientific_json_read_after_reservation_bytes": next((int((item.get("source_stat_provenance") or {}).get("bytes", 0)) for item in selected if item.get("logical_role") == "root179c_v16_result_deferred"), 0),
        "scientific_hdf5_parser_read_bytes": 0,
        "scientific_native_or_bi4_read_bytes": 0,
    })
    contract["v2_interface"] = interface
    contract["sha256"] = _canonical(contract)
    contract_text = json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=True,
                               allow_nan=False) + "\n"
    out_contract.write_text(contract_text, encoding="utf-8")
    contract_file_sha = hashlib.sha256(contract_text.encode("utf-8")).hexdigest()
    request["forward_version"] = "ROOT242_V9_EXECUTABLE_SINGLE_CASE_SOURCE_ONLY"
    request["command"] = interface["command_template"]
    request["root242_v9_source_binding"] = {
        "schema": HANDOFF_SCHEMA, "contract_path": str(out_contract),
        "contract_sha256": contract["sha256"], "selected_roles": len(selected),
        "selected_roles_sha256": role_digest,
        "recursive_metadata_closure": binding["recursive_metadata_closure"],
        "parent_after_reservation_copy_and_trace": True,
        "legacy_v7_sparse_executor": "REJECTED_BY_CONTRACT",
    }
    request["storage_scope"].update({
        "source_logical_bytes_excluding_active_ledger": logical,
        "deferred_source_logical_bytes": deferred,
        "source_copy_content_bytes": logical,
        "bounded_metadata_and_runtime_bytes": metadata_bytes,
        "parent_atomic_same_ledger_reservation": True,
        "parent_ledger_owner": "OUTER_PARENT_ONLY",
        "sparse_placeholders_for_deferred_payloads": False,
    })
    request["estimated_deferred_read_bytes"] = deferred
    request["estimated_deferred_copy_and_posthash_bytes"] = deferred
    request["estimated_result_JSON_read_bytes"] = interface["scientific_json_read_after_reservation_bytes"]
    request["estimated_hdf5_read_bytes"] = next((int((item.get("source_stat_provenance") or {}).get("bytes", 0)) for item in selected if str(item.get("source_path_provenance", "")).lower().endswith("typed-reconstructed-v2.h5")), 0)
    request["estimated_native_read_bytes"] = 0
    request["estimated_bi4_read_bytes"] = 0
    request["source_only_expected_copy_roles"] = {
        "contract_path": str(out_contract), "contract_sha256": contract["sha256"],
        "role_count": len(selected), "roles_sha256": role_digest,
        "copy_content_bytes": logical, "deferred_payload_bytes": deferred,
        "recursive_metadata_closure": binding["recursive_metadata_closure"],
        "metadata_only_builder": True,
    }
    _refresh_request_inputs(request, contract, selected, out_contract, contract_file_sha)
    request["sha256"] = _canonical(request)
    out_request.write_text(json.dumps(request, indent=2, sort_keys=True,
                                      ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    return {
        "schema": HANDOFF_SCHEMA, "status": "READY_FOR_PARENT_STAGE2_GUARD_V9",
        "contract": {"path": str(out_contract), "file_sha256": _file_sha(out_contract, "V9 contract"),
                     "canonical_sha256": contract["sha256"]},
        "request": {"path": str(out_request), "file_sha256": _file_sha(out_request, "V9 request"),
                    "canonical_sha256": request["sha256"]},
        "selected": {"role_count": len(selected), "logical_bytes": logical,
                      "metadata_bytes": metadata_bytes, "deferred_bytes": deferred,
                      "copy_content_bytes": logical, "roles_sha256": role_digest},
        "recursive_metadata_closure": binding["recursive_metadata_closure"],
        "payload_read": False, "ledger_mutated": False, "launch_performed": False,
        "legacy_v7_sparse_executor": "REJECTED_BY_CONTRACT",
    }


def validate_request(*, request: Path | str, contract: Path | str) -> dict[str, Any]:
    request_path = Path(request).expanduser()
    contract_path = Path(contract).expanduser()
    outer = _json(request_path, "ROOT242 V9 request")
    inner = _json(contract_path, "ROOT242 V9 contract")
    if outer.get("schema") != V8.REQUEST_SCHEMA or outer.get("sha256") != _canonical(outer):
        _fail("ROOT242 V9 request schema/canonical SHA differs")
    if inner.get("schema") != V8.CONTRACT_SCHEMA or inner.get("sha256") != _canonical(inner):
        _fail("ROOT242 V9 contract schema/canonical SHA differs")
    binding = inner.get("root242_source_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != HANDOFF_SCHEMA:
        _fail("ROOT242 V9 source binding is missing")
    roles = binding.get("roles")
    if not isinstance(roles, list) or len(roles) < 40:
        _fail("ROOT242 V9 selected role table is incomplete")
    digest = hashlib.sha256(json.dumps(roles, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    if binding.get("selected_roles_sha256") != digest:
        _fail("ROOT242 V9 selected role digest differs")
    if outer.get("root213_metadata_contract", {}).get("path") != str(contract_path):
        _fail("ROOT242 V9 request does not bind exact contract path")
    if outer.get("root213_metadata_contract", {}).get("sha256") != inner.get("sha256"):
        _fail("ROOT242 V9 request/contract SHA differs")
    if outer.get("root242_v9_source_binding", {}).get("selected_roles_sha256") != digest:
        _fail("ROOT242 V9 outer role digest differs")
    paths = {str(item.get("source_path_provenance")) for item in roles if isinstance(item, Mapping)}
    discovered = binding.get("recursive_metadata_closure", {}).get("discovered_source_paths", [])
    if not isinstance(discovered, list) or not set(str(x) for x in discovered).issubset(paths):
        _fail("ROOT242 V9 recursive metadata source closure is incomplete")
    required = {"root200_inner_request", "v12_semantic_sidecar", "frozen_v15_request",
                "producer_nested_report_v2", "portable_rebind_v2_entrypoint", "v9_executor",
                "fresh_v16_proof_consumer_v8", "fresh_v16_proof_consumer_v12",
                "typed_only_evaluator_v1", "typed_only_evaluator_v2", "typed_only_evaluator_v3"}
    names = {str(item.get("logical_role")) for item in roles if isinstance(item, Mapping)}
    if not required.issubset(names):
        _fail(f"ROOT242 V9 runtime closure is incomplete: {sorted(required - names)}")
    if outer.get("scope", {}).get("original_path_fallback") != "REJECT":
        _fail("ROOT242 V9 permits original-path fallback")
    return {"schema": HANDOFF_SCHEMA, "status": "ROOT242_V9_METADATA_VALIDATED_READY_FOR_PARENT",
            "request": {"path": str(request_path), "file_sha256": _file_sha(request_path, "V9 request"),
                        "canonical_sha256": outer["sha256"]},
            "contract": {"path": str(contract_path), "file_sha256": _file_sha(contract_path, "V9 contract"),
                         "canonical_sha256": inner["sha256"]},
            "selected_role_count": len(roles),
            "selected_logical_bytes": int(binding.get("logical_bytes", 0)),
            "deferred_payload_bytes": int(binding.get("deferred_logical_bytes", 0)),
            "recursive_metadata_source_count": len(discovered),
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
            value = validate_request(request=args.request, contract=args.contract)
        else:
            value = build_request(source_contract=args.source_contract, source_request=args.source_request,
                                  output_contract=args.output_contract, output_request=args.output_request,
                                  fresh_root=args.fresh_root, home_receipt=args.home_receipt,
                                  case_id=args.case_id, attempt_id=args.attempt_id,
                                  primary_scripts_root=args.primary_scripts_root)
        print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (Root242V9Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT242 V9 source request: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
