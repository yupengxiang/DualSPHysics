#!/usr/bin/env python3
"""Build an additive V16 copied-runtime request for a canonical CURRENT leaf.

The historical ROOT242 V15 pair is deliberately left untouched.  This
builder clones a V14/V15 contract/request into a fresh namespace, puts the
V16 entrypoint, V15 sibling, V2 sibling, scoped-leaf module, sealed CURRENT
contract, and CURRENT catalog in one target-relative directory, and rewrites
only the cloned ``root200_inner_request`` role.  V14/V13/V11 remain the outer
execution chain; the copied V16 entrypoint is the V11 V2 entrypoint and calls
the copied V2 ``main`` after validating the scoped leaf.

Only bounded JSON/code and the CURRENT catalog's metadata-sized file are read
while building.  Scientific payloads are deferred to the parent after
reservation.  Historical alias row 78 is rejected explicitly; this builder
cannot turn the ROOT242 diagnostic request into a canonical case.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
ENTRY_NAME = "ds_data02_stage2_f2_current_scoped_entry_v16.py"
V15_NAME = "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py"
V2_NAME = "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
LEAF_NAME = "ds_data02_stage2_f2_current_scoped_leaf_v16.py"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CONTRACT_SCHEMA = "ds02.stage2.f2-current-scoped-runtime-contract.v16"
BUILDER_SCHEMA = "ds02.stage2.f2-current-scoped-source-request-builder.v16"
PREFLIGHT_SCHEMA = "ds02.stage2.f2-root242-v14-recursive-source-preflight.v1"
MAX_METADATA_BYTES = 32 * 1024 * 1024
CANONICAL_F2_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"
ALIAS_STATUS = frozenset({"HISTORICAL_ALIAS_UNRESOLVED", "UNRESOLVED", "UNKNOWN"})


class CurrentScopedSourceRequestError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise CurrentScopedSourceRequestError(message)


def _bounded(path: Path, role: str) -> None:
    if path.is_symlink() or not path.is_file():
        _fail(f"{role} is not a regular non-symlink file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        _fail(f"{role} exceeds bounded metadata limit: {path}")


def _sha(path: Path, role: str) -> str:
    _bounded(path, role)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, role: str) -> dict[str, int]:
    _bounded(path, role)
    value = path.stat()
    return {"bytes": int(value.st_size), "mode_bits": int(value.st_mode & 0o7777),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _json(path: Path, role: str) -> dict[str, Any]:
    _bounded(path, role)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cannot read {role}: {error}")
    if not isinstance(value, dict):
        _fail(f"{role} must be an object")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _write(path: Path, value: Mapping[str, Any], role: str) -> tuple[str, dict[str, int]]:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite {role}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True,
                                ensure_ascii=True, allow_nan=False) + "\n",
                    encoding="utf-8")
    return _sha(path, role), _stat(path, role)


def _path(value: Any, role: str) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.startswith("/"):
        _fail(f"{role} must be absolute")
    return Path(value).expanduser().absolute()


def _rel(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        _fail(f"{role} must be relative")
    path = Path(value)
    if ".." in path.parts or path == Path("."):
        _fail(f"{role} escapes target root")
    return value


def _primary_source(primary: Path, name: str) -> Path:
    candidates = [
        primary / "lagrangian-fluid-lab" / "scripts" / name,
        primary / "DualSPHysics" / "lagrangian-fluid-lab" / "scripts" / name,
        SCRIPT_DIR / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.absolute()
    _fail(f"source module is unavailable: {name}")


def _role(name: str, source: Path, target: str, *, kind: str) -> dict[str, Any]:
    return {
        "logical_role": name, "source_kind": kind, "actionable": True,
        "content_read_by_manifest": True, "source_sha256": _sha(source, name),
        "source_sha256_basis": "V16_BOUNDED_SOURCE_METADATA",
        "source_stat_provenance": _stat(source, name),
        "source_path_provenance": str(source), "target_relative_path": target,
        "target_stat": None, "target_sha256": None, "content_sha_verified": False,
        "content_verification_phase": "PARENT_AFTER_RESERVATION",
        "deferred_content": False, "placeholder_only": False,
        "source_inode_mtime_equivalence": "NOT_CLAIMED",
    }


def _role_digest(roles: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(
        list(roles), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _replace_role(roles: list[dict[str, Any]], logical: str, item: dict[str, Any]) -> None:
    found = [index for index, row in enumerate(roles) if row.get("logical_role") == logical]
    if len(found) != 1:
        _fail(f"expected exactly one base role: {logical}")
    old_target = roles[found[0]].get("target_relative_path")
    if any(row.get("target_relative_path") == item["target_relative_path"] and
           row.get("logical_role") != logical for row in roles):
        _fail(f"target path collides with another role: {item['target_relative_path']}")
    item["historical_target_relative_path"] = old_target
    roles[found[0]] = item


def _append_role(roles: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if any(row.get("logical_role") == item["logical_role"] for row in roles):
        _fail(f"role already exists: {item['logical_role']}")
    if any(row.get("target_relative_path") == item["target_relative_path"] for row in roles):
        _fail(f"target already exists: {item['target_relative_path']}")
    roles.append(item)


def _base_contract_roles(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    binding = contract.get("root242_source_binding")
    if not isinstance(binding, Mapping) or not isinstance(binding.get("roles"), list):
        _fail("base contract lacks root242_source_binding.roles")
    return [copy.deepcopy(dict(row)) for row in binding["roles"]]


def _find_role(roles: Sequence[Mapping[str, Any]], logical: str) -> Mapping[str, Any]:
    rows = [row for row in roles if row.get("logical_role") == logical]
    if len(rows) != 1:
        _fail(f"base contract role is missing/duplicated: {logical}")
    return rows[0]


def _make_runtime_contract(*, current: Path, current_sha: str,
                           current_stat: Mapping[str, Any], case_id: str,
                           family_id: str, target_current: str) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_SCOPED_CURRENT_RUNTIME_AFTER_COPY",
        "current_binding": {
            "source_path_provenance": str(current), "sha256": current_sha,
            "source_stat_provenance": dict(current_stat),
            "target_relative_path": target_current, "target_stat": None,
            "content_verification_phase": "PARENT_AFTER_RESERVATION",
        },
        "case_scope": {"family_id": family_id, "physical_case_id": case_id,
                       "identity_status": "CANONICAL", "selection_is_single_case": True},
        "nested_manifest_paths": {"policy": "SEALED_LEAF", "opened": False, "allowlist": []},
        "original_path_fallback": "REJECT", "payload_read": False,
        "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "portable_cold_replay_credit": "NOT_CLAIMED",
    }
    contract["sha256"] = _canonical(contract)
    return contract


def _make_descriptor(*, root: Path, target_paths: Mapping[str, str],
                     sources: Mapping[str, Path], runtime_contract: Mapping[str, Any],
                     current_sha: str, current_stat: Mapping[str, Any],
                     case_id: str) -> dict[str, Any]:
    descriptor: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_SCOPED_CURRENT_RUNTIME_AFTER_COPY",
        "case_id": case_id, "original_path_fallback": "REJECT",
        "nested_manifest_paths": {"opened": False, "allowlist": [], "policy": "SEALED_LEAF"},
        "runtime_target_root": str(root),
        "target_stat_policy": "MEASURE_AFTER_COPY_BYTES_MODE_AND_DISTINCT_INODE",
        "expected_sha256": {}, "source_stat": {}, "target_relative_paths": dict(target_paths),
        "runtime_contract_target_relative_path": target_paths["contract"],
        "current_target_relative_path": target_paths["current"],
        "current_sha256": current_sha, "current_source_stat": dict(current_stat),
        "entrypoint_calls_v2_main": True,
        "v2_main_dispatch": "COPIED_V2_MAIN_AFTER_V16_SCOPED_VALIDATION",
        "payload_read_by_builder": False,
    }
    for key, source in sources.items():
        descriptor["expected_sha256"][key] = _sha(source, f"V16 {key} source")
        descriptor["source_stat"][key] = _stat(source, f"V16 {key} source")
    descriptor["expected_sha256"]["current"] = current_sha
    descriptor["source_stat"]["current"] = dict(current_stat)
    descriptor["contract_sha256"] = _sha(Path(runtime_contract["source_path"]), "V16 runtime contract") \
        if isinstance(runtime_contract.get("source_path"), str) else None
    return descriptor


def _copy_inner_source(base_roles: Sequence[Mapping[str, Any]], output: Path,
                       descriptor: Mapping[str, Any]) -> tuple[Path, str, dict[str, int], dict[str, Any]]:
    role = _find_role(base_roles, "root200_inner_request")
    source = _path(role.get("source_path_provenance"), "base root200 inner request")
    inner = _json(source, "base root200 inner request")
    value = copy.deepcopy(inner)
    value["v16_scoped_runtime"] = copy.deepcopy(dict(descriptor))
    value["v16_scoped_runtime"]["schema"] = CONTRACT_SCHEMA
    value["sha256"] = _canonical(value)
    sha, stat = _write(output, value, "V16 scoped inner request")
    return output, sha, stat, value


def build_request(*, source_contract: Path | str, source_request: Path | str,
                  preflight_report: Path | str, output_contract: Path | str,
                  output_request: Path | str, fresh_root: Path | str,
                  home_receipt: Path | str, case_id: str, attempt_id: str,
                  primary_scripts_root: Path | str, current_path: Path | str,
                  family_id: str = "F2") -> dict[str, Any]:
    """Clone a V14/V15 pair and bind the actual copied V16 entrypoint."""
    source_contract_path = _path(source_contract, "source contract")
    source_request_path = _path(source_request, "source request")
    report_path = _path(preflight_report, "preflight report")
    base_contract = _json(source_contract_path, "source contract")
    base_request = _json(source_request_path, "source request")
    report = _json(report_path, "preflight report")
    if report.get("schema") != PREFLIGHT_SCHEMA:
        _fail("preflight report schema differs")
    if report.get("status") != "READY_FOR_PARENT_GUARD_METADATA_ONLY":
        _fail("preflight report is not ready for parent guard")
    if report.get("unbound_actionable_paths") or report.get("graph_errors"):
        _fail("preflight report contains unbound or graph errors")
    if (report.get("rewrite") or {}).get("errors"):
        _fail("preflight report contains rewrite errors")
    if base_request.get("case_id") in {"STAGE2_F2_ROOT242_V15_LIST_STRING_20261010_R006",
                                       "STAGE2_F2_ROOT242_V11", "STAGE2_F2_ROOT242"}:
        _fail("legacy_row78_rejected: V16 requires a canonical CURRENT case")
    if case_id != CANONICAL_F2_CASE:
        _fail("legacy_row78_rejected: requested case is not canonical F2 row 65")
    if base_request.get("identity_status") in ALIAS_STATUS or base_request.get("identity_status") == "HISTORICAL_ALIAS_UNRESOLVED":
        _fail("legacy_row78_rejected: base request identity is unresolved")
    out_contract_path = _path(output_contract, "output contract")
    out_request_path = _path(output_request, "output request")
    fresh = _path(fresh_root, "fresh output root")
    home = _path(home_receipt, "home receipt")
    if out_contract_path.exists() or out_request_path.exists():
        _fail("V16 builder refuses existing output contract/request")
    if fresh.exists() and any(fresh.iterdir()):
        _fail("V16 builder refuses non-empty fresh output root")

    primary = Path(primary_scripts_root).expanduser().absolute()
    entry = _primary_source(primary, ENTRY_NAME)
    v15 = _primary_source(primary, V15_NAME)
    v2 = _primary_source(primary, V2_NAME)
    leaf = _primary_source(primary, LEAF_NAME)
    current = _path(current_path, "CURRENT catalog")
    current_sha = _sha(current, "CURRENT catalog")
    if current_sha != CURRENT_SHA:
        _fail("CURRENT catalog SHA differs from pinned df7e identity")
    current_stat = _stat(current, "CURRENT catalog")
    runtime_dir = "runtime/v16"
    target_paths = {
        "entrypoint": f"{runtime_dir}/{ENTRY_NAME}",
        "v2": f"{runtime_dir}/{V2_NAME}",
        "v15": f"{runtime_dir}/{V15_NAME}",
        "leaf_module": f"{runtime_dir}/{LEAF_NAME}",
        "contract": f"{runtime_dir}/current-scoped-runtime-contract.v16.json",
        "current": f"{runtime_dir}/CURRENT336.json",
    }
    runtime_contract = _make_runtime_contract(
        current=current, current_sha=current_sha, current_stat=current_stat,
        case_id=case_id, family_id=family_id, target_current=target_paths["current"])
    runtime_contract_path = out_contract_path.parent / "current-scoped-runtime-contract.v16.json"
    # The descriptor is written into the inner request after the contract's
    # source bytes exist; the target file itself is a separate copied role.
    runtime_contract_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_contract_source_sha, runtime_contract_source_stat = _write(
        runtime_contract_path, runtime_contract, "V16 scoped runtime contract")
    sources = {"entrypoint": entry, "v2": v2, "v15": v15,
               "leaf_module": leaf, "contract": runtime_contract_path}
    descriptor = _make_descriptor(
        root=fresh, target_paths=target_paths, sources=sources,
        runtime_contract={"source_path": str(runtime_contract_path)},
        current_sha=current_sha, current_stat=current_stat, case_id=case_id)
    descriptor["contract_sha256"] = runtime_contract_source_sha
    descriptor["contract_source_stat"] = runtime_contract_source_stat
    descriptor["source_contract_provenance"] = str(source_contract_path)
    descriptor["source_request_provenance"] = str(source_request_path)
    descriptor["preflight_report_provenance"] = str(report_path)

    inner_path = out_contract_path.parent / "current-scoped-inner-request.v16.json"
    inner_path, inner_sha, inner_stat, _inner_value = _copy_inner_source(
        _base_contract_roles(base_contract), inner_path, descriptor)

    roles = _base_contract_roles(base_contract)
    _replace_role(roles, "portable_rebind_v2_entrypoint",
                  _role("portable_rebind_v2_entrypoint", entry, target_paths["entrypoint"],
                        kind="runtime_source_current_scoped_entry_v16"))
    _replace_role(roles, "portable_rebind_v2_core",
                  _role("portable_rebind_v2_core", v2, target_paths["v2"],
                        kind="runtime_source_copied_v2_sibling_for_v16"))
    _replace_role(roles, "typed_only_portable_rebind_v1",
                  _role("typed_only_portable_rebind_v1", v15, target_paths["v15"],
                        kind="runtime_source_copied_v15_sibling_for_v16"))
    root_inner = _role("root200_inner_request", inner_path, 
                       next(row["target_relative_path"] for row in roles
                            if row.get("logical_role") == "root200_inner_request"),
                       kind="root200_inner_request_v16_scoped_overlay")
    _replace_role(roles, "root200_inner_request", root_inner)
    _append_role(roles, _role("current_scoped_leaf_v16", leaf, target_paths["leaf_module"],
                              kind="runtime_source_current_scoped_leaf_v16"))
    _append_role(roles, _role("current_scoped_runtime_contract_v16", runtime_contract_path,
                              target_paths["contract"], kind="sealed_current_scoped_runtime_contract_v16"))
    _append_role(roles, _role("current_catalog_exact_leaf", current, target_paths["current"],
                              kind="sealed_current336_exact_leaf_after_reservation"))
    roles.sort(key=lambda row: str(row.get("logical_role")))

    report_clone = copy.deepcopy(report)
    report_roles = [copy.deepcopy(dict(row)) for row in report.get("roles", [])]
    if not isinstance(report_roles, list):
        _fail("preflight report roles are missing")
    # The report is a copy-plan report; the three extra V16 roles are added so
    # V14/V11 can prove the role-count join without rewriting the consumed
    # report.  The current leaf itself is metadata-sized but remains parent
    # after-reservation content verified.
    for name in ("current_scoped_leaf_v16", "current_scoped_runtime_contract_v16",
                 "current_catalog_exact_leaf"):
        role = next(row for row in roles if row.get("logical_role") == name)
        report_roles.append(copy.deepcopy(role))
    report_clone["roles"] = report_roles
    report_clone["role_count"] = int(report.get("role_count", len(report_roles) - 3)) + 3
    if "discovered_role_count" in report_clone:
        report_clone["discovered_role_count"] = int(report_clone["discovered_role_count"]) + 3
    report_clone["forward_version"] = "ROOT242_V16_SCOPED_CURRENT_RUNTIME"
    report_out = out_contract_path.parent / "current-scoped-v16-preflight-report.json"
    report_sha, _report_stat = _write(report_out, report_clone, "V16 preflight report")

    # The report itself is an immutable copied role.  Rebind that role to the
    # new report before computing the role digest; otherwise V14 sees the
    # request's new report SHA but the contract still seals the consumed V15
    # report path.
    old_report_role = _find_role(roles, "v14_recursive_preflight_report")
    report_target = str(old_report_role.get("target_relative_path"))
    _replace_role(roles, "v14_recursive_preflight_report",
                  _role("v14_recursive_preflight_report", report_out, report_target,
                        kind="sealed_v16_recursive_preflight_report"))
    roles.sort(key=lambda row: str(row.get("logical_role")))
    digest = _role_digest(roles)

    # Rebind the contract to the cloned report and source role table.
    contract = copy.deepcopy(base_contract)
    source_binding = dict(contract.get("root242_source_binding") or {})
    source_binding["roles"] = roles
    source_binding["selected_role_count"] = len(roles)
    source_binding["selected_roles_sha256"] = digest
    source_binding["v16_scoped_runtime_role"] = "current_scoped_runtime_contract_v16"
    source_binding["v16_current_leaf_role"] = "current_catalog_exact_leaf"
    recursive_closure = dict(source_binding.get("recursive_metadata_closure") or {})
    recursive_closure["discovered_source_paths"] = sorted({
        str(row.get("source_path_provenance")) for row in roles
        if isinstance(row.get("source_path_provenance"), str)
    })
    source_binding["recursive_metadata_closure"] = recursive_closure
    source_binding["v14_recursive_preflight"] = {
        **dict(source_binding.get("v14_recursive_preflight") or {}),
        "schema": PREFLIGHT_SCHEMA, "logical_role": "v14_recursive_preflight_report",
        "source_path": str(report_out), "source_file_sha256": report_sha,
        "role_count": report_clone["role_count"], "unbound_count": 0,
        "rewrite_error_count": 0, "payload_read": False,
    }
    contract["root242_source_binding"] = source_binding
    contract["root242_v14_recursive_preflight"] = source_binding["v14_recursive_preflight"]
    contract["forward_version"] = "ROOT242_V16_SCOPED_CURRENT_RUNTIME"
    contract["v16_scoped_runtime"] = {
        "schema": CONTRACT_SCHEMA, "role": "current_scoped_runtime_contract_v16",
        "source_path": str(runtime_contract_path), "source_sha256": runtime_contract_source_sha,
        "target_relative_path": target_paths["contract"], "case_id": case_id,
        "current_sha256": current_sha, "current_target_relative_path": target_paths["current"],
        "entrypoint_calls_v2_main": True, "original_path_fallback": "REJECT",
    }
    contract["sha256"] = _canonical(contract)
    contract_file_sha, _contract_stat = _write(out_contract_path, contract, "V16 output contract")
    contract_canonical_sha = contract["sha256"]

    request = copy.deepcopy(base_request)
    request["case_id"] = case_id
    request["attempt_id"] = attempt_id
    request["family_id"] = family_id
    request.setdefault("storage_scope", {})["external_filesystem"] = str(fresh)
    request["storage_scope"]["home_receipt_path"] = str(home)
    request["root213_metadata_contract"] = {"path": str(out_contract_path), "sha256": contract_canonical_sha}
    request["root242_v11_source_binding"] = {
        **dict(request.get("root242_v11_source_binding") or {}),
        "contract_path": str(out_contract_path), "contract_sha256": contract_canonical_sha,
        "selected_roles": len(roles), "selected_roles_sha256": digest,
        "current_scoped_entrypoint": target_paths["entrypoint"],
    }
    request["root242_v14_preflight_binding"] = {
        **dict(request.get("root242_v14_preflight_binding") or {}),
        "path": str(report_out), "file_sha256": report_sha,
        "role_count": report_clone["role_count"], "unbound_count": 0,
        "rewrite_error_count": 0,
    }
    request["root242_v16_source_binding"] = {
        "schema": "ds02.stage2.f2-current-scoped-source-binding.v16",
        "entrypoint_role": "portable_rebind_v2_entrypoint",
        "entrypoint_target_relative_path": target_paths["entrypoint"],
        "entrypoint_source_sha256": _sha(entry, "V16 entrypoint"),
        "v2_target_relative_path": target_paths["v2"],
        "v15_target_relative_path": target_paths["v15"],
        "leaf_module_target_relative_path": target_paths["leaf_module"],
        "runtime_contract_target_relative_path": target_paths["contract"],
        "current_target_relative_path": target_paths["current"],
        "current_source_sha256": current_sha,
        "current_source_stat_provenance": current_stat,
        "case_id": case_id, "identity_status": "CANONICAL",
        "entrypoint_calls_v2_main": True, "original_path_fallback": "REJECT",
        "source_fallback": "REJECT", "payload_read_by_builder": False,
    }
    request.setdefault("scope", {})["original_path_fallback"] = "REJECT"
    request["forward_version"] = "ROOT242_V16_SCOPED_CURRENT_RUNTIME"
    request["estimated_storage_bytes"] = max(int(request.get("estimated_storage_bytes", 0)),
                                               int(source_binding.get("logical_bytes", 0)))
    request["v16_scoped_runtime"] = {
        "entrypoint_calls_v2_main": True, "nested_manifest_paths": {"opened": False, "allowlist": []},
        "target_relative_paths": target_paths, "source_sha256": current_sha,
        "preflight_report_sha256": report_sha, "role_digest": digest,
    }
    request["sha256"] = _canonical(request)
    request_sha, _request_stat = _write(out_request_path, request, "V16 output request")
    return {
        "schema": BUILDER_SCHEMA,
        "status": "READY_FOR_PARENT_STAGE2_GUARD_V16_SCOPED_CURRENT_RUNTIME",
        "request": {"path": str(out_request_path), "file_sha256": request_sha,
                     "canonical_sha256": request["sha256"]},
        "contract": {"path": str(out_contract_path), "file_sha256": contract_file_sha,
                      "canonical_sha256": contract["sha256"]},
        "preflight": {"path": str(report_out), "file_sha256": report_sha,
                       "role_count": report_clone["role_count"], "unbound_count": 0},
        "roles": {"count": len(roles), "sha256": digest,
                   "v16_targets": target_paths},
        "case_id": case_id, "attempt_id": attempt_id,
        "payload_read": False, "launch_performed": False, "ledger_mutated": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("source-contract", "source-request", "preflight-report", "output-contract",
                 "output-request", "fresh-root", "home-receipt", "primary-scripts-root",
                 "current"):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--family-id", default="F2")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_request(
            source_contract=args.source_contract, source_request=args.source_request,
            preflight_report=args.preflight_report, output_contract=args.output_contract,
            output_request=args.output_request, fresh_root=args.fresh_root,
            home_receipt=args.home_receipt, case_id=args.case_id,
            attempt_id=args.attempt_id, primary_scripts_root=args.primary_scripts_root,
            current_path=args.current, family_id=args.family_id,
        )
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (CurrentScopedSourceRequestError, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(f"V16 scoped source request: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
