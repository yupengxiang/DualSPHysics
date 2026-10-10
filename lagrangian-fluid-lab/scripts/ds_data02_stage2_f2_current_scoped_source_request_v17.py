#!/usr/bin/env python3
"""Build an additive V17 copied-runtime request for a canonical CURRENT leaf.

The historical ROOT242 V15 pair is deliberately left untouched.  This
builder clones a V14/V15 contract/request into a fresh namespace, puts the
V17 entrypoint, V15 sibling, V2 sibling, scoped-leaf module, sealed CURRENT
contract, and CURRENT catalog in one target-relative directory, and rewrites
only the cloned ``root200_inner_request`` role.  V14/V13/V11 remain the outer
execution chain; the copied V17 entrypoint is the V11 V2 entrypoint and calls
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
ENTRY_NAME = "ds_data02_stage2_f2_current_scoped_entry_v17.py"
V15_NAME = "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py"
V1_NAME = "ds_data02_stage2_f2_typed_only_portable_rebind_v1.py"
V2_NAME = "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py"
LEAF_NAME = "ds_data02_stage2_f2_current_scoped_leaf_v17.py"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
CONTRACT_SCHEMA = "ds02.stage2.f2-current-scoped-runtime-contract.v17"
BUILDER_SCHEMA = "ds02.stage2.f2-current-scoped-source-request-builder.v17"
PREFLIGHT_SCHEMA = "ds02.stage2.f2-root242-v14-recursive-source-preflight.v1"
MAX_METADATA_BYTES = 32 * 1024 * 1024
CANONICAL_F2_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"
ALIAS_STATUS = frozenset({"HISTORICAL_ALIAS_UNRESOLVED", "UNRESOLVED", "UNKNOWN"})
IDENTITY_MANIFEST_SCHEMA = "ds02.stage2.f2-current-case-identity-manifest.v17"
IDENTITY_REF_ROLES = frozenset({
    "raw", "typed", "producer_report", "receipt", "labels", "evaluator", "current_row",
})
IDENTITY_KEYS = frozenset({
    "case_id", "physical_case_id", "producer_case_id", "source_case_id",
    "current_case_id", "canonical_case_id",
})


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
        "source_sha256_basis": "V17_BOUNDED_SOURCE_METADATA",
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


def _identity_values(value: Any) -> list[str]:
    """Collect identity-bearing values from bounded metadata documents."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for name, item in value.items():
            if name in IDENTITY_KEYS and isinstance(item, str):
                found.append(item)
            found.extend(_identity_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_identity_values(item))
    return found


def _bound_source_pairs(value: Any) -> set[tuple[str, str]]:
    """Collect explicit path/SHA pairs from a source role table."""
    pairs: set[tuple[str, str]] = set()
    if isinstance(value, Mapping):
        path = value.get("source_path_provenance", value.get("path"))
        sha = value.get("source_sha256", value.get("sha256"))
        if isinstance(path, str) and path.startswith("/") and isinstance(sha, str):
            pairs.add((str(Path(path).expanduser().absolute()), sha))
        for item in value.values():
            pairs.update(_bound_source_pairs(item))
    elif isinstance(value, list):
        for item in value:
            pairs.update(_bound_source_pairs(item))
    return pairs


def _validate_identity_manifest(path: Path, *, source_request: Path,
                                source_contract: Path, source_contract_value: Mapping[str, Any],
                                current: Path,
                                case_id: str, family_id: str) -> dict[str, Any]:
    """Require an explicit exact-case join before producing a V17 request.

    This prevents the historical row78 request from being laundered by
    changing only its outer ``case_id``. Every required producer/consumer
    metadata reference must carry the same physical identity and SHA. The
    function reads only bounded JSON metadata; scientific payloads remain
    parent-after-reservation inputs.
    """
    manifest = _json(path, "V17 identity manifest")
    if manifest.get("schema") != IDENTITY_MANIFEST_SCHEMA:
        _fail("identity manifest schema differs")
    if manifest.get("family_id") != family_id:
        _fail("identity manifest family differs")
    if manifest.get("physical_case_id") != case_id:
        _fail("identity manifest physical identity differs")
    if manifest.get("identity_status") != "CANONICAL":
        _fail("identity manifest is not canonical")
    if manifest.get("current_catalog_sha256") != CURRENT_SHA:
        _fail("identity manifest CURRENT SHA differs")
    if manifest.get("source_request_sha256") != _sha(source_request, "identity source request"):
        _fail("identity source request SHA differs")
    if manifest.get("source_contract_sha256") != _sha(source_contract, "identity source contract"):
        _fail("identity source contract SHA differs")
    bound_pairs = _bound_source_pairs(source_contract_value)
    refs = manifest.get("references")
    if not isinstance(refs, list) or not refs:
        _fail("identity manifest references are missing")
    seen: set[str] = set()
    checked: list[dict[str, Any]] = []
    for row in refs:
        if not isinstance(row, Mapping):
            _fail("identity reference is malformed")
        role = row.get("role")
        if role not in IDENTITY_REF_ROLES or role in seen:
            _fail(f"identity reference role is missing/duplicated: {role}")
        seen.add(str(role))
        ref = _path(row.get("path"), f"identity {role} path")
        expected_sha = row.get("sha256")
        if not isinstance(expected_sha, str) or expected_sha != _sha(ref, f"identity {role}"):
            _fail(f"identity {role} SHA differs")
        if role == "current_row" and ref != current:
            _fail("identity CURRENT reference is not the pinned catalog")
        if role != "current_row" and (str(ref), expected_sha) not in bound_pairs:
            _fail(f"identity {role} is not bound by the source role table")
        document = _json(ref, f"identity {role}")
        values = _identity_values(document)
        # CURRENT is the catalog for all cases, so its document necessarily
        # contains other identities.  It must contain the exact selected row;
        # the producer/typed/receipt/label/evaluator references must contain
        # no competing identity.
        if not values or (case_id not in values if role == "current_row"
                          else any(value != case_id for value in values)):
            _fail(f"identity {role} does not carry exact physical identity")
        checked.append({"role": role, "path": str(ref), "sha256": expected_sha,
                        "identity_values": sorted(set(values))})
    missing = sorted(IDENTITY_REF_ROLES - seen)
    if missing:
        _fail(f"identity manifest lacks required roles: {','.join(missing)}")
    return {
        "schema": IDENTITY_MANIFEST_SCHEMA,
        "path": str(path),
        "sha256": _sha(path, "identity manifest"),
        "physical_case_id": case_id,
        "identity_status": "CANONICAL",
        "references": checked,
    }


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
        "v2_main_dispatch": "COPIED_V2_MAIN_AFTER_V17_SCOPED_VALIDATION",
        "payload_read_by_builder": False,
    }
    for key, source in sources.items():
        descriptor["expected_sha256"][key] = _sha(source, f"V17 {key} source")
        descriptor["source_stat"][key] = _stat(source, f"V17 {key} source")
    descriptor["expected_sha256"]["current"] = current_sha
    descriptor["source_stat"]["current"] = dict(current_stat)
    descriptor["contract_sha256"] = _sha(Path(runtime_contract["source_path"]), "V17 runtime contract") \
        if isinstance(runtime_contract.get("source_path"), str) else None
    return descriptor


def _copy_inner_source(base_roles: Sequence[Mapping[str, Any]], output: Path,
                       descriptor: Mapping[str, Any]) -> tuple[Path, str, dict[str, int], dict[str, Any]]:
    role = _find_role(base_roles, "root200_inner_request")
    source = _path(role.get("source_path_provenance"), "base root200 inner request")
    inner = _json(source, "base root200 inner request")
    value = copy.deepcopy(inner)
    value["v17_scoped_runtime"] = copy.deepcopy(dict(descriptor))
    value["v17_scoped_runtime"]["schema"] = CONTRACT_SCHEMA
    value["sha256"] = _canonical(value)
    sha, stat = _write(output, value, "V17 scoped inner request")
    return output, sha, stat, value


def build_request(*, source_contract: Path | str, source_request: Path | str,
                  preflight_report: Path | str, output_contract: Path | str,
                  output_request: Path | str, fresh_root: Path | str,
                  home_receipt: Path | str, case_id: str, attempt_id: str,
                  primary_scripts_root: Path | str, current_path: Path | str,
                  identity_manifest: Path | str,
                  family_id: str = "F2") -> dict[str, Any]:
    """Clone a V14/V15 pair and bind the actual copied V17 entrypoint."""
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
    if case_id != CANONICAL_F2_CASE:
        _fail("legacy_row78_rejected: requested case is not canonical F2 row 65")
    if base_request.get("case_id") != case_id:
        _fail("identity_join_rejected: source request is not the exact canonical physical case")
    if base_request.get("physical_case_id") != case_id:
        _fail("identity_join_rejected: source request physical identity differs")
    if base_request.get("identity_status") != "CANONICAL":
        _fail("identity_join_rejected: source request identity is not canonical")
    request_identity_values = _identity_values(base_request)
    if any(value != case_id for value in request_identity_values):
        _fail("identity_join_rejected: nested source request identity differs")
    contract_identity_values = _identity_values(base_contract)
    if any(value != case_id for value in contract_identity_values):
        _fail("identity_join_rejected: nested source contract identity differs")
    current = _path(current_path, "CURRENT catalog")
    identity_manifest_path = _path(identity_manifest, "identity manifest")
    identity = _validate_identity_manifest(
        identity_manifest_path, source_request=source_request_path,
        source_contract=source_contract_path, source_contract_value=base_contract,
        current=current,
        case_id=case_id, family_id=family_id)
    out_contract_path = _path(output_contract, "output contract")
    out_request_path = _path(output_request, "output request")
    fresh = _path(fresh_root, "fresh output root")
    home = _path(home_receipt, "home receipt")
    if out_contract_path.exists() or out_request_path.exists():
        _fail("V17 builder refuses existing output contract/request")
    if fresh.exists() and any(fresh.iterdir()):
        _fail("V17 builder refuses non-empty fresh output root")

    primary = Path(primary_scripts_root).expanduser().absolute()
    entry = _primary_source(primary, ENTRY_NAME)
    v1 = _primary_source(primary, V1_NAME)
    v15 = _primary_source(primary, V15_NAME)
    v2 = _primary_source(primary, V2_NAME)
    leaf = _primary_source(primary, LEAF_NAME)
    current_sha = _sha(current, "CURRENT catalog")
    if current_sha != CURRENT_SHA:
        _fail("CURRENT catalog SHA differs from pinned df7e identity")
    current_stat = _stat(current, "CURRENT catalog")
    runtime_dir = "runtime/v17"
    target_paths = {
        "entrypoint": f"{runtime_dir}/{ENTRY_NAME}",
        "v1": f"{runtime_dir}/{V1_NAME}",
        "v2": f"{runtime_dir}/{V2_NAME}",
        "v15": f"{runtime_dir}/{V15_NAME}",
        "leaf_module": f"{runtime_dir}/{LEAF_NAME}",
        "contract": f"{runtime_dir}/current-scoped-runtime-contract.v17.json",
        "current": f"{runtime_dir}/CURRENT336.json",
    }
    runtime_contract = _make_runtime_contract(
        current=current, current_sha=current_sha, current_stat=current_stat,
        case_id=case_id, family_id=family_id, target_current=target_paths["current"])
    runtime_contract_path = out_contract_path.parent / "current-scoped-runtime-contract.v17.json"
    # The descriptor is written into the inner request after the contract's
    # source bytes exist; the target file itself is a separate copied role.
    runtime_contract_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_contract_source_sha, runtime_contract_source_stat = _write(
        runtime_contract_path, runtime_contract, "V17 scoped runtime contract")
    sources = {"entrypoint": entry, "v1": v1, "v2": v2, "v15": v15,
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

    inner_path = out_contract_path.parent / "current-scoped-inner-request.v17.json"
    inner_path, inner_sha, inner_stat, _inner_value = _copy_inner_source(
        _base_contract_roles(base_contract), inner_path, descriptor)

    roles = _base_contract_roles(base_contract)
    _replace_role(roles, "portable_rebind_v2_entrypoint",
                  _role("portable_rebind_v2_entrypoint", entry, target_paths["entrypoint"],
                        kind="runtime_source_current_scoped_entry_v17"))
    _replace_role(roles, "portable_rebind_v2_core",
                  _role("portable_rebind_v2_core", v2, target_paths["v2"],
                        kind="runtime_source_copied_v2_sibling_for_v17"))
    # V2 imports this exact V1 basename during module import.  V15 is a
    # distinct sibling; aliasing V15 to V1 makes a real copied V2 fail before
    # it can reach V8/V12/scorer.
    _replace_role(roles, "typed_only_portable_rebind_v1",
                  _role("typed_only_portable_rebind_v1", v1, target_paths["v1"],
                        kind="runtime_source_copied_genuine_v1_sibling_for_v17"))
    _append_role(roles, _role("current_scoped_v15_sibling_v17", v15, target_paths["v15"],
                              kind="runtime_source_copied_v15_sibling_for_v17"))
    root_inner = _role("root200_inner_request", inner_path,
                       next(row["target_relative_path"] for row in roles
                            if row.get("logical_role") == "root200_inner_request"),
                       kind="root200_inner_request_v17_scoped_overlay")
    _replace_role(roles, "root200_inner_request", root_inner)
    _append_role(roles, _role("current_scoped_leaf_v17", leaf, target_paths["leaf_module"],
                              kind="runtime_source_current_scoped_leaf_v17"))
    _append_role(roles, _role("current_scoped_runtime_contract_v17", runtime_contract_path,
                              target_paths["contract"], kind="sealed_current_scoped_runtime_contract_v17"))
    _append_role(roles, _role("current_catalog_exact_leaf", current, target_paths["current"],
                              kind="sealed_current336_exact_leaf_after_reservation"))
    roles.sort(key=lambda row: str(row.get("logical_role")))

    report_clone = copy.deepcopy(report)
    report_roles = [copy.deepcopy(dict(row)) for row in report.get("roles", [])]
    if not isinstance(report_roles, list):
        _fail("preflight report roles are missing")
    # Keep the copied preflight's role table aligned with the actual V17
    # target graph.  In particular, the V2-imported V1 role must no longer
    # point at the V15 target, and the V15 sibling is an additional role.
    role_by_name = {str(row.get("logical_role")): row for row in roles}
    for index, row in enumerate(report_roles):
        logical = str(row.get("logical_role"))
        if logical in {"portable_rebind_v2_entrypoint", "portable_rebind_v2_core",
                       "typed_only_portable_rebind_v1"} and logical in role_by_name:
            report_roles[index] = copy.deepcopy(role_by_name[logical])
    # The report is a copy-plan report; the three extra V17 roles are added so
    # V14/V11 can prove the role-count join without rewriting the consumed
    # report.  The current leaf itself is metadata-sized but remains parent
    # after-reservation content verified.
    for name in ("current_scoped_v15_sibling_v17", "current_scoped_leaf_v17",
                 "current_scoped_runtime_contract_v17", "current_catalog_exact_leaf"):
        role = next(row for row in roles if row.get("logical_role") == name)
        report_roles.append(copy.deepcopy(role))
    report_clone["roles"] = report_roles
    report_clone["role_count"] = int(report.get("role_count", len(report_roles) - 4)) + 4
    if "discovered_role_count" in report_clone:
        report_clone["discovered_role_count"] = int(report_clone["discovered_role_count"]) + 4
    report_clone["forward_version"] = "ROOT242_V17_SCOPED_CURRENT_RUNTIME"
    report_out = out_contract_path.parent / "current-scoped-v17-preflight-report.json"
    report_sha, _report_stat = _write(report_out, report_clone, "V17 preflight report")

    # The report itself is an immutable copied role.  Rebind that role to the
    # new report before computing the role digest; otherwise V14 sees the
    # request's new report SHA but the contract still seals the consumed V15
    # report path.
    old_report_role = _find_role(roles, "v14_recursive_preflight_report")
    report_target = str(old_report_role.get("target_relative_path"))
    _replace_role(roles, "v14_recursive_preflight_report",
                  _role("v14_recursive_preflight_report", report_out, report_target,
                        kind="sealed_v17_recursive_preflight_report"))
    roles.sort(key=lambda row: str(row.get("logical_role")))
    digest = _role_digest(roles)

    # Rebind the contract to the cloned report and source role table.
    contract = copy.deepcopy(base_contract)
    source_binding = dict(contract.get("root242_source_binding") or {})
    source_binding["roles"] = roles
    source_binding["selected_role_count"] = len(roles)
    source_binding["selected_roles_sha256"] = digest
    source_binding["v17_scoped_runtime_role"] = "current_scoped_runtime_contract_v17"
    source_binding["v17_current_leaf_role"] = "current_catalog_exact_leaf"
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
    contract["v17_identity_join"] = identity
    contract["forward_version"] = "ROOT242_V17_SCOPED_CURRENT_RUNTIME"
    contract["v17_scoped_runtime"] = {
        "schema": CONTRACT_SCHEMA, "role": "current_scoped_runtime_contract_v17",
        "source_path": str(runtime_contract_path), "source_sha256": runtime_contract_source_sha,
        "target_relative_path": target_paths["contract"], "case_id": case_id,
        "current_sha256": current_sha, "current_target_relative_path": target_paths["current"],
        "entrypoint_calls_v2_main": True, "original_path_fallback": "REJECT",
    }
    contract["sha256"] = _canonical(contract)
    contract_file_sha, _contract_stat = _write(out_contract_path, contract, "V17 output contract")
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
    request["root242_v17_source_binding"] = {
        "schema": "ds02.stage2.f2-current-scoped-source-binding.v17",
        "entrypoint_role": "portable_rebind_v2_entrypoint",
        "entrypoint_target_relative_path": target_paths["entrypoint"],
        "entrypoint_source_sha256": _sha(entry, "V17 entrypoint"),
        "v1_target_relative_path": target_paths["v1"],
        "v1_source_sha256": _sha(v1, "V17 genuine V1 sibling"),
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
        "identity_manifest": identity,
    }
    request.setdefault("scope", {})["original_path_fallback"] = "REJECT"
    request["forward_version"] = "ROOT242_V17_SCOPED_CURRENT_RUNTIME"
    request["estimated_storage_bytes"] = max(int(request.get("estimated_storage_bytes", 0)),
                                               int(source_binding.get("logical_bytes", 0)))
    request["v17_scoped_runtime"] = {
        "entrypoint_calls_v2_main": True, "nested_manifest_paths": {"opened": False, "allowlist": []},
        "target_relative_paths": target_paths, "source_sha256": current_sha,
        "preflight_report_sha256": report_sha, "role_digest": digest,
    }
    request["sha256"] = _canonical(request)
    request_sha, _request_stat = _write(out_request_path, request, "V17 output request")
    return {
        "schema": BUILDER_SCHEMA,
        "status": "READY_FOR_PARENT_STAGE2_GUARD_V17_SCOPED_CURRENT_RUNTIME",
        "request": {"path": str(out_request_path), "file_sha256": request_sha,
                     "canonical_sha256": request["sha256"]},
        "contract": {"path": str(out_contract_path), "file_sha256": contract_file_sha,
                      "canonical_sha256": contract["sha256"]},
        "preflight": {"path": str(report_out), "file_sha256": report_sha,
                       "role_count": report_clone["role_count"], "unbound_count": 0},
        "roles": {"count": len(roles), "sha256": digest,
                   "v17_targets": target_paths},
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
                 "current", "identity-manifest"):
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
            current_path=args.current, identity_manifest=args.identity_manifest,
            family_id=args.family_id,
        )
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, default=str))
        return 0
    except (CurrentScopedSourceRequestError, OSError, ValueError, TypeError,
            json.JSONDecodeError) as error:
        print(f"V17 scoped source request: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
