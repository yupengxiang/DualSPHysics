#!/usr/bin/env python3
"""Bind the ROOT242 portable runtime to a seven-anchor metadata endpoint.

This is a source-only admission gate for a future parent run.  It consumes
bounded JSON and file metadata only.  The gate binds the latest CURRENT
catalog, a V6 canonical catalog, a V27 physical-condition union index, one
exact raw-anchor plan per family, the V22 source/access/rights manifest, and
the V11 portable request/contract.  It does not open H5, BI4, native arrays,
JSONL, solver output, or the V11 payload.

The endpoint deliberately distinguishes a physical lookup ID from a
canonical identity.  If an anchor is the unresolved historical alias, the
endpoint is emitted as ``BLOCKED_HISTORICAL_ALIAS_ANCHOR`` and cannot be
launched until a canonical source-bound anchor exists.  Resolution, window,
and recovery remain diagnostic axes; V27's physical-union group is the only
grouping boundary exposed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-root242-dataset-only-endpoint.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
CATALOG_SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v6"
V27_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v27"
ANCHOR_INDEX_SCHEMA = "ds02.stage2.family-raw-anchor-plan-index.v1"
ACCESS_SCHEMA = "ds02.stage2.seven-family-source-access-index.v22"
V11_SCHEMA = "ds02.stage2.f2-root242-v11-dynamic-open-guard-source-binding.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_METADATA_BYTES = 32 * 1024 * 1024
MAX_LICENSE_BYTES = 8 * 1024 * 1024
FORBIDDEN_SPLIT_AXES = ("resolution", "window", "recovery")


class DatasetEndpointError(ValueError):
    """Input is stale, ambiguous, or over-promoted."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({key: item for key, item in value.items()
                                     if key != "sha256"}).encode()).hexdigest()


def sha256_file(path: Path, *, maximum: int = MAX_METADATA_BYTES) -> str:
    if path.is_symlink() or not path.is_file():
        raise DatasetEndpointError(f"expected regular metadata file: {path}")
    if path.stat().st_size > maximum:
        raise DatasetEndpointError(f"metadata file exceeds bounded limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str, role: str, *, maximum: int = MAX_METADATA_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path).expanduser().absolute()
    observed = sha256_file(target, maximum=maximum)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DatasetEndpointError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise DatasetEndpointError(f"{role} must be a JSON object")
    stat = target.stat()
    return value, {
        "role": role, "path": str(target), "file_sha256": observed,
        "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino), "content_policy": "bounded JSON metadata only",
    }


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise DatasetEndpointError(f"{role} is not a lowercase SHA-256")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    if path.exists() or path.is_symlink():
        raise DatasetEndpointError(f"refusing to overwrite endpoint artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                      allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return canonical_sha(value), hashlib.sha256(text.encode()).hexdigest()


def _metadata_ref(path: Path, role: str, *, maximum: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    digest = sha256_file(path, maximum=maximum)
    stat = path.stat()
    return {"role": role, "path": str(path.absolute()), "file_sha256": digest,
            "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev),
            "st_ino": int(stat.st_ino), "content_read": True}


def _validate_current(current: Mapping[str, Any], current_meta: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise DatasetEndpointError("CURRENT catalog schema differs")
    if current_meta.get("file_sha256") != "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b":
        raise DatasetEndpointError("CURRENT catalog is not the pinned df7e...c62b source")
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise DatasetEndpointError("CURRENT catalog must contain 336 rows")
    by_id: dict[str, Mapping[str, Any]] = {}
    family_counts = {family: 0 for family in FAMILIES}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise DatasetEndpointError(f"CURRENT row {index} is not an object")
        case_id = row.get("physical_case_id")
        family = row.get("family_id")
        if not isinstance(case_id, str) or case_id in by_id or family not in family_counts:
            raise DatasetEndpointError("CURRENT identity/family is missing or duplicated")
        if row.get("current_index", index) != index:
            raise DatasetEndpointError(f"CURRENT row index differs for {case_id}")
        by_id[case_id] = row
        family_counts[str(family)] += 1
    if family_counts != {family: 48 for family in FAMILIES}:
        raise DatasetEndpointError(f"CURRENT family coverage differs: {family_counts}")
    return by_id


def _validate_catalog(path: Path, current_meta: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]], dict[str, Any]]:
    catalog, meta = read_json(path, "V6 canonical catalog")
    if catalog.get("schema") != CATALOG_SCHEMA or catalog.get("sha256") != canonical_sha(catalog):
        raise DatasetEndpointError("V6 catalog schema/canonical SHA differs")
    binding = catalog.get("current_binding")
    if not isinstance(binding, Mapping) or binding.get("file_sha256") != current_meta.get("file_sha256"):
        raise DatasetEndpointError("V6 catalog does not bind the exact CURRENT file")
    rows = catalog.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise DatasetEndpointError("V6 catalog must contain 336 rows")
    by_id: dict[str, Mapping[str, Any]] = {}
    canonical_count = 0
    aliases = 0
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("physical_case_id"), str):
            raise DatasetEndpointError("V6 catalog case row is malformed")
        case_id = str(row["physical_case_id"])
        if case_id in by_id:
            raise DatasetEndpointError(f"V6 catalog duplicates {case_id}")
        identity = row.get("identity")
        canonical_id = row.get("canonical_case_id")
        if canonical_id is None:
            aliases += 1
            if not isinstance(identity, Mapping) or identity.get("status") != "HISTORICAL_ALIAS_UNRESOLVED" or identity.get("identity_credit") is not False:
                raise DatasetEndpointError(f"V6 alias row is not quarantined: {case_id}")
        else:
            canonical_count += 1
            if canonical_id != case_id or not isinstance(identity, Mapping) or identity.get("identity_credit") is not True:
                raise DatasetEndpointError(f"V6 canonical identity is malformed: {case_id}")
        by_id[case_id] = row
    if canonical_count != 335 or aliases != 1:
        raise DatasetEndpointError(f"V6 canonical/alias coverage differs: {canonical_count}/{aliases}")
    return catalog, by_id, meta


def _validate_v27(path: Path) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]], dict[str, Any]]:
    index, meta = read_json(path, "V27 physical-union index", maximum=MAX_METADATA_BYTES)
    if index.get("schema") != V27_SCHEMA or index.get("sha256") != canonical_sha(index):
        raise DatasetEndpointError("V27 index schema/canonical SHA differs")
    cases = index.get("cases")
    groups = index.get("physical_union_groups")
    if not isinstance(cases, list) or len(cases) != 336 or not isinstance(groups, list):
        raise DatasetEndpointError("V27 index does not contain 336 cases/groups")
    rows: dict[str, Mapping[str, Any]] = {}
    group_members: dict[str, set[int]] = {}
    for row in cases:
        if not isinstance(row, Mapping) or not isinstance(row.get("physical_case_id"), str):
            raise DatasetEndpointError("V27 case row is malformed")
        case_id = str(row["physical_case_id"])
        group_id = row.get("physical_union_group_id_v27")
        if case_id in rows or not isinstance(group_id, str):
            raise DatasetEndpointError(f"V27 case/group is missing or duplicated: {case_id}")
        forbidden = row.get("forbidden_cross_split_dimensions")
        if not isinstance(forbidden, list) or any(axis not in forbidden for axis in FORBIDDEN_SPLIT_AXES):
            raise DatasetEndpointError(f"V27 row loses a forbidden split axis: {case_id}")
        if row.get("split_safe") is True:
            raise DatasetEndpointError(f"V27 row is incorrectly split-safe: {case_id}")
        rows[case_id] = row
        group_members.setdefault(group_id, set()).add(int(row.get("current_index", -1)))
    declared: dict[str, Mapping[str, Any]] = {}
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("group_id"), str):
            raise DatasetEndpointError("V27 physical group is malformed")
        gid = str(group["group_id"])
        if gid in declared:
            raise DatasetEndpointError(f"V27 physical group is duplicated: {gid}")
        declared[gid] = group
        if group.get("split_safe") is True:
            raise DatasetEndpointError(f"V27 physical group is split-safe: {gid}")
        forbidden = group.get("forbidden_cross_split_dimensions")
        if not isinstance(forbidden, list) or any(axis not in forbidden for axis in FORBIDDEN_SPLIT_AXES):
            raise DatasetEndpointError(f"V27 group loses a forbidden split axis: {gid}")
        if sorted(int(item) for item in group.get("current_indices", [])) != sorted(group_members.get(gid, set())):
            raise DatasetEndpointError(f"V27 group membership differs: {gid}")
    if set(group_members) != set(declared):
        raise DatasetEndpointError("V27 case/group closure is incomplete")
    return index, rows, meta


def _validate_anchor_index(path: Path, canonical_cases: Mapping[str, Mapping[str, Any]],
                           v27_cases: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    index, meta = read_json(path, "seven-family anchor index")
    if index.get("schema") != ANCHOR_INDEX_SCHEMA or index.get("seven_family_coverage") is not True:
        raise DatasetEndpointError("anchor index schema/coverage differs")
    rows = index.get("families")
    if not isinstance(rows, list) or len(rows) != 7:
        raise DatasetEndpointError("anchor index must contain seven families")
    selected: list[dict[str, Any]] = []
    seen_families: set[str] = set()
    seen_cases: set[str] = set()
    for item in rows:
        if not isinstance(item, Mapping) or item.get("family_id") not in FAMILIES:
            raise DatasetEndpointError("anchor family is malformed")
        family = str(item["family_id"])
        if family in seen_families:
            raise DatasetEndpointError(f"duplicate anchor family: {family}")
        seen_families.add(family)
        plan_path = Path(str(item.get("path", ""))).expanduser().absolute()
        plan, plan_meta = read_json(plan_path, f"{family} anchor plan", maximum=MAX_METADATA_BYTES)
        if plan.get("schema") != "ds02.stage2.family-raw-anchor-plan.v1" or plan.get("family_id") != family:
            raise DatasetEndpointError(f"{family} anchor plan schema/family differs")
        anchor = plan.get("anchor_case")
        raw = plan.get("raw_anchor")
        if not isinstance(anchor, Mapping) or not isinstance(raw, Mapping):
            raise DatasetEndpointError(f"{family} anchor plan is incomplete")
        case_id = anchor.get("physical_case_id")
        if not isinstance(case_id, str) or case_id in seen_cases:
            raise DatasetEndpointError(f"anchor case is missing/duplicated: {case_id}")
        seen_cases.add(case_id)
        catalog_row = canonical_cases.get(case_id)
        union_row = v27_cases.get(case_id)
        if catalog_row is None or union_row is None:
            raise DatasetEndpointError(f"anchor is not in canonical catalog/V27: {case_id}")
        if catalog_row.get("canonical_case_id") is None:
            # Keep this as an explicit endpoint blocker rather than silently
            # selecting another row or turning a historical alias canonical.
            identity_status = "HISTORICAL_ALIAS_UNRESOLVED"
            admission = "BLOCKED_HISTORICAL_ALIAS_ANCHOR"
        else:
            identity_status = "CANONICAL_CURRENT_SAVED_MASK"
            admission = "CANONICAL_ANCHOR"
        if catalog_row.get("family_id") != family or union_row.get("family_id") != family:
            raise DatasetEndpointError(f"anchor family differs across CURRENT/catalog/V27: {case_id}")
        group_id = union_row.get("physical_union_group_id_v27")
        if not isinstance(group_id, str):
            raise DatasetEndpointError(f"anchor physical union group is missing: {case_id}")
        raw_root = raw.get("raw_root")
        if not isinstance(raw_root, str) or not raw_root.startswith("/"):
            raise DatasetEndpointError(f"{family} raw root is not an absolute deferred source")
        selected.append({
            "family_id": family, "current_index": int(anchor.get("current_index", -1)),
            "physical_case_id_lookup": case_id,
            "canonical_case_id": catalog_row.get("canonical_case_id"),
            "identity_status": identity_status, "admission": admission,
            "physical_union_group_id_v27": group_id,
            "physical_union_status": union_row.get("physical_union_status"),
            "forbidden_cross_split_dimensions": list(union_row.get("forbidden_cross_split_dimensions", [])),
            "anchor_plan": {"path": str(plan_path), "file_sha256": plan_meta["file_sha256"],
                            "bytes": plan_meta["bytes"]},
            "raw_binding": {
                "raw_root_provenance": raw_root,
                "raw_root_declared_exists": raw.get("raw_root_exists"),
                "frame_count_expected": raw.get("frame_count_expected"),
                "required_source_arrays": list(raw.get("required_source_arrays", [])),
                "expected_raw_tree_sha256": raw.get("expected_raw_tree_sha256"),
                "content_policy": "parent after-reservation raw tree hash; no source-only payload read",
            },
            "typed_comparison": dict(plan.get("typed_comparison_contract", {})),
            "qualification": dict(UNKNOWN),
        })
    if seen_families != set(FAMILIES):
        raise DatasetEndpointError("anchor index does not cover all seven families")
    return sorted(selected, key=lambda item: item["family_id"]), meta


def _validate_access(path: Path, current_meta: Mapping[str, Any], repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    access, meta = read_json(path, "V22 source/access manifest")
    if access.get("schema") != ACCESS_SCHEMA or access.get("qualification") != UNKNOWN:
        raise DatasetEndpointError("V22 access manifest schema/qualification differs")
    binding = access.get("current_binding")
    if not isinstance(binding, Mapping) or binding.get("sha256") != current_meta.get("file_sha256"):
        raise DatasetEndpointError("V22 access manifest does not bind CURRENT")
    deps = access.get("dependencies_and_licenses")
    if not isinstance(deps, Mapping):
        raise DatasetEndpointError("V22 dependency/license manifest is missing")
    rights: list[dict[str, Any]] = []
    for role in ("repository_license", "reader_dependency_license_index_v13"):
        item = deps.get(role)
        if not isinstance(item, Mapping) or not isinstance(item.get("repo_relative_path"), str):
            rights.append({"role": role, "rights_status": "UNKNOWN_NOT_DECLARED"})
            continue
        target = (repo_root / item["repo_relative_path"]).absolute()
        record = {"role": role, "path": str(target), "declared_sha256": item.get("sha256"),
                  "rights_status": "RIGHTS_UNKNOWN_UNTIL_LICENSE_SCOPE_REVIEW",
                  "redistribution": "NOT_AUTHORIZED_BY_THIS_METADATA_GATE"}
        if target.is_file() and not target.is_symlink() and target.stat().st_size <= MAX_LICENSE_BYTES:
            observed = sha256_file(target, maximum=MAX_LICENSE_BYTES)
            record.update({"observed_sha256": observed, "sha_match": observed == item.get("sha256"),
                           "bytes": int(target.stat().st_size)})
            if observed != item.get("sha256"):
                raise DatasetEndpointError(f"{role} SHA differs")
        else:
            record["availability"] = "MISSING_OR_UNBOUNDED_STAT_ONLY"
        rights.append(record)
    interpreter = deps.get("runtime_interpreter")
    if isinstance(interpreter, Mapping):
        rights.append({"role": "runtime_interpreter", "literal_path": interpreter.get("required_invocation"),
                       "rights_status": "PINNED_EXTERNAL_ENVIRONMENT_EXCEPTION",
                       "standalone_replay": False,
                       "abi_smoke_required": True})
    official = deps.get("official_solver_library")
    rights.append({"role": "official_solver_library", "declared": isinstance(official, Mapping),
                   "rights_status": "UNKNOWN_UNDECLARED_OR_REVIEW_REQUIRED",
                   "standalone_replay": False})
    return {
        "manifest": {"path": meta["path"], "file_sha256": meta["file_sha256"],
                      "bytes": meta["bytes"], "schema": access.get("schema")},
        "exact_paths_only": access.get("access_policy", {}).get("exact_paths_only") is True,
        "latest_or_glob_fallback": access.get("access_policy", {}).get("latest_or_glob_fallback"),
        "external_paths_provenance_only_until_parent_guard": access.get("access_policy", {}).get("external_paths_are_provenance_only_until_parent_guard"),
        "dependencies_and_rights": rights,
        "external_publish": "FORBIDDEN_UNTIL_SEPARATE_RIGHTS_REVIEW",
    }, meta


def _validate_portable(request_path: Path, contract_path: Path) -> dict[str, Any]:
    request, request_meta = read_json(request_path, "V11 portable request")
    contract, contract_meta = read_json(contract_path, "V11 portable contract")
    if request.get("sha256") != canonical_sha(request) or contract.get("sha256") != canonical_sha(contract):
        raise DatasetEndpointError("V11 request/contract canonical SHA differs")
    binding = contract.get("root242_source_binding")
    if not isinstance(binding, Mapping) or binding.get("schema") != V11_SCHEMA:
        raise DatasetEndpointError("portable contract is not ROOT242 V11")
    roles = binding.get("roles")
    if not isinstance(roles, list) or len(roles) < 40:
        raise DatasetEndpointError("V11 portable role closure is incomplete")
    policy = binding.get("dynamic_open_policy")
    if not isinstance(policy, Mapping) or policy.get("membership_rule") != "LEXICAL_AND_RESOLVED_MUST_SHARE_ONE_EXPLICIT_ROOT":
        raise DatasetEndpointError("V11 dynamic open policy is incomplete")
    if request.get("scope", {}).get("original_path_fallback") != "REJECT":
        raise DatasetEndpointError("portable request permits original path fallback")
    outer = request.get("root242_v11_source_binding")
    if not isinstance(outer, Mapping) or outer.get("dynamic_open_audit") is not True:
        raise DatasetEndpointError("V11 request lacks dynamic open binding")
    if outer.get("contract_path") != contract_meta["path"]:
        raise DatasetEndpointError("V11 request/contract path differs")
    if outer.get("contract_sha256") != contract.get("sha256"):
        raise DatasetEndpointError("V11 request/contract canonical SHA differs")
    role_paths = [item.get("source_path_provenance") for item in roles
                  if isinstance(item, Mapping)]
    if any(not isinstance(path, str) or not path.startswith("/") for path in role_paths):
        raise DatasetEndpointError("V11 role closure contains an unbound source path")
    return {
        "request": {"path": request_meta["path"], "file_sha256": request_meta["file_sha256"],
                     "canonical_sha256": request["sha256"], "bytes": request_meta["bytes"]},
        "contract": {"path": contract_meta["path"], "file_sha256": contract_meta["file_sha256"],
                      "canonical_sha256": contract["sha256"], "bytes": contract_meta["bytes"]},
        "schema": V11_SCHEMA, "role_count": len(roles),
        "role_digest": binding.get("selected_roles_sha256"),
        "dynamic_open_audit": True, "original_path_fallback": "REJECT",
        "payload_read_by_endpoint": False,
    }


def _write_endpoint(output: Path, endpoint: Mapping[str, Any]) -> dict[str, Any]:
    canonical_value = dict(endpoint)
    canonical_value["sha256"] = canonical_sha(canonical_value)
    output.mkdir(parents=True, exist_ok=True)
    request_path = output / "root242-v12-dataset-only-endpoint-request.json"
    request_canonical, request_file = _write_new(request_path, canonical_value)
    return {"path": str(request_path), "canonical_sha256": request_canonical,
            "file_sha256": request_file, "status": canonical_value["status"]}


def build_dataset_endpoint(*, current_path: Path | str, catalog_path: Path | str,
                           v27_index_path: Path | str, anchor_index_path: Path | str,
                           source_access_path: Path | str, portable_request_path: Path | str,
                           portable_contract_path: Path | str, repo_root: Path | str,
                           output_dir: Path | str) -> dict[str, Any]:
    current, current_meta = read_json(current_path, "CURRENT336 catalog")
    current_rows = _validate_current(current, current_meta)
    catalog, catalog_rows, catalog_meta = _validate_catalog(Path(catalog_path), current_meta)
    v27, v27_rows, v27_meta = _validate_v27(Path(v27_index_path))
    anchors, anchor_meta = _validate_anchor_index(Path(anchor_index_path), catalog_rows, v27_rows)
    access, access_meta = _validate_access(Path(source_access_path), current_meta, Path(repo_root).expanduser().absolute())
    portable = _validate_portable(Path(portable_request_path), Path(portable_contract_path))
    current_join = []
    for anchor in anchors:
        current_row = current_rows.get(anchor["physical_case_id_lookup"])
        if current_row is None or current_row.get("family_id") != anchor["family_id"]:
            raise DatasetEndpointError(f"anchor no longer joins CURRENT: {anchor['physical_case_id_lookup']}")
        current_join.append({"family_id": anchor["family_id"], "current_index": anchor["current_index"],
                             "physical_case_id": anchor["physical_case_id_lookup"],
                             "catalog_canonical_case_id": anchor["canonical_case_id"],
                             "physical_union_group_id_v27": anchor["physical_union_group_id_v27"],
                             "identity_status": anchor["identity_status"],
                             "admission": anchor["admission"]})
    blocked = [item for item in anchors if item["admission"] != "CANONICAL_ANCHOR"]
    endpoint = {
        "schema": SCHEMA,
        "status": "BLOCKED_HISTORICAL_ALIAS_ANCHOR" if blocked else "READY_FOR_PARENT_STAGE2_GUARD_DATASET_ONLY",
        "request_id": "root242-v12-dataset-only-endpoint-001",
        "scope": "one exact raw-anchor lookup per family; source-bound metadata endpoint only",
        "current_binding": {"path": current_meta["path"], "file_sha256": current_meta["file_sha256"],
                             "schema": CURRENT_SCHEMA, "case_count": len(current_rows)},
        "catalog_binding": {"path": catalog_meta["path"], "file_sha256": catalog_meta["file_sha256"],
                             "canonical_sha256": catalog["sha256"], "schema": CATALOG_SCHEMA,
                             "canonical_case_count": catalog.get("coverage", {}).get("canonical_current_saved_mask_cases")},
        "physical_union_binding": {"path": v27_meta["path"], "file_sha256": v27_meta["file_sha256"],
                                    "canonical_sha256": v27["sha256"], "schema": V27_SCHEMA,
                                    "upper_split_boundary": "physical_union_group_id_v27",
                                    "forbidden_cross_split_dimensions": list(FORBIDDEN_SPLIT_AXES),
                                    "split_safe": False},
        "portable_binding": portable,
        "access_and_rights": access,
        "anchor_binding": {"index": {"path": anchor_meta["path"], "file_sha256": anchor_meta["file_sha256"],
                                       "schema": ANCHOR_INDEX_SCHEMA},
                           "selected": anchors, "canonical_anchor_count": 7 - len(blocked),
                           "blocked_anchor_count": len(blocked),
                           "selection": "exact plan path and physical_case_id; no latest/glob/family fallback"},
        "current_join": current_join,
        "execution": {
            "parent_owner": "OUTER_PARENT_ONLY",
            "reserve_before_copy_or_payload_hash": True,
            "raw_or_h5_read_by_endpoint": False,
            "payload_hash_phase": "PARENT_AFTER_RESERVATION_ONLY",
            "typed_decode_phase": "PARENT_AFTER_SOURCE_AND_TARGET_PREPOST_CLOSURE",
            "v11_dynamic_open_trace_required": True,
            "original_path_poison_required": True,
            "output_policy": "fresh relocated attempt root only; old namespaces immutable",
            "qualification_credit": "NONE",
        },
        "resource_estimate": {
            "cpu_threads": 1, "max_wall_seconds": 900,
            "memory_max_bytes": 16 * 1024 * 1024 * 1024,
            "home_receipt_bytes": 16 * 1024 * 1024,
            "external_storage_bytes": "derive from selected anchor declared raw/typed stats after parent reservation",
            "deferred_payload_bytes": "unknown until parent stat/source closure; no lowball estimate",
        },
        "qualification": dict(UNKNOWN),
        "model_invoked": False, "cfd_invoked": False,
        "claim_boundary": {
            "portable_replay": "NOT_COMPLETED_BY_THIS_METADATA_ENDPOINT",
            "raw_anchor_reconstruction": "NOT_COMPLETED_BY_THIS_METADATA_ENDPOINT",
            "physical_fate": "UNKNOWN", "event_labels": "UNKNOWN",
            "rights": "path/SHA/access metadata only; no redistribution permission",
            "external_publish": "FORBIDDEN",
        },
        "read_scope": {
            "bounded_json_and_small_license_files_only": True,
            "h5_opened": False, "bi4_opened": False, "native_arrays_opened": False,
            "jsonl_opened": False, "solver_output_opened": False,
            "ledger_mutated": False, "launch_performed": False,
        },
        "source_inputs": [current_meta, catalog_meta, v27_meta, anchor_meta, access_meta,
                          portable["request"], portable["contract"]],
    }
    return _write_endpoint(Path(output_dir).expanduser().absolute(), endpoint)


def validate_endpoint(path: Path | str) -> dict[str, Any]:
    request, meta = read_json(Path(path), "dataset-only endpoint request")
    if request.get("schema") != SCHEMA or request.get("sha256") != canonical_sha(request):
        raise DatasetEndpointError("endpoint schema/canonical SHA differs")
    selected = request.get("anchor_binding", {}).get("selected")
    if not isinstance(selected, list) or len(selected) != 7:
        raise DatasetEndpointError("endpoint does not contain seven anchors")
    families = {item.get("family_id") for item in selected if isinstance(item, Mapping)}
    if families != set(FAMILIES):
        raise DatasetEndpointError("endpoint anchor families are incomplete")
    if request.get("execution", {}).get("reserve_before_copy_or_payload_hash") is not True:
        raise DatasetEndpointError("endpoint does not require reservation before payload access")
    if request.get("portable_binding", {}).get("original_path_fallback") != "REJECT":
        raise DatasetEndpointError("endpoint portable binding permits original fallback")
    return {"schema": SCHEMA, "status": request.get("status"),
            "path": meta["path"], "file_sha256": meta["file_sha256"],
            "canonical_sha256": request["sha256"],
            "anchor_count": len(selected),
            "canonical_anchor_count": request.get("anchor_binding", {}).get("canonical_anchor_count"),
            "blocked_anchor_count": request.get("anchor_binding", {}).get("blocked_anchor_count"),
            "payload_read": False, "ledger_mutated": False, "launch_performed": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("current", "catalog", "v27-index", "anchor-index", "source-access",
                 "portable-request", "portable-contract", "repo-root", "output"):
        build.add_argument("--" + name, type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_dataset_endpoint(
                current_path=args.current, catalog_path=args.catalog,
                v27_index_path=args.v27_index, anchor_index_path=args.anchor_index,
                source_access_path=args.source_access,
                portable_request_path=args.portable_request,
                portable_contract_path=args.portable_contract,
                repo_root=args.repo_root, output_dir=args.output)
        else:
            result = validate_endpoint(args.request)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 0
    except (DatasetEndpointError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ROOT242 V12 dataset-only endpoint: {error}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
