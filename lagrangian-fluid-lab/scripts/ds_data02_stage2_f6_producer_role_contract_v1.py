#!/usr/bin/env python3
"""Build a bounded, source-only F6 producer-role contract.

The ROOT276 support manifest already contains two canonical F6 source-current
producer identities and the ROOT244/ROOT252 owner predicates.  This adapter
turns those small metadata records into an explicit parent-task input.  It
never hashes or opens BI4/VTK/native payloads.  A CURRENT lifecycle plan is a
separate admission input: without it the contract remains source-prepared and
cannot produce event labels.  Even after a strict plan join, this contract
only covers initial position support and continuous-owner provenance; region
ownership, event control and physical fate remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f6.producer-role-contract.v1"
MAX_METADATA_BYTES = 10 * 1024 * 1024
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".ibi4", ".vtk", ".vtu", ".jsonl"}
COMPLETED_PLAN_STATUSES = {"COMPLETED", "COMPLETED_ACTUAL", "ACTUAL_COVERED"}


class F6ProducerRoleContractError(ValueError):
    """The bounded F6 source metadata is not a safe producer contract."""


def _fail(message: str) -> None:
    raise F6ProducerRoleContractError(message)


def _regular_metadata(path: Path) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"metadata path is unavailable: {path}: {error}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"metadata path is not a regular non-symlink file: {path}")
    if info.st_size > MAX_METADATA_BYTES:
        _fail(f"metadata path exceeds bounded limit: {path}")
    return info


def _read_json(path: Path, role: str) -> tuple[dict[str, Any], str, dict[str, int]]:
    before = _regular_metadata(path)
    raw = path.read_bytes()
    after = _regular_metadata(path)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        _fail(f"{role} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{role} is not bounded JSON: {path}: {error}")
    if not isinstance(value, dict):
        _fail(f"{role} must be a JSON object: {path}")
    stat_record = {
        "st_dev": int(before.st_dev), "st_ino": int(before.st_ino),
        "size": int(before.st_size), "mtime_ns": int(before.st_mtime_ns),
        "ctime_ns": int(before.st_ctime_ns),
    }
    return value, hashlib.sha256(raw).hexdigest(), stat_record


def _sha_text(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        _fail(f"{role} must be a SHA-256 hex string")
    try:
        int(value, 16)
    except ValueError:
        _fail(f"{role} is not hexadecimal SHA-256")
    return value


def _ref(record: Mapping[str, Any], *, role: str, payload: bool = False) -> dict[str, Any]:
    path = record.get("path")
    declared = record.get("sha256", record.get("known_sha256"))
    if not isinstance(path, str):
        _fail(f"{role} lacks a path")
    if payload or Path(path).suffix.lower() in PAYLOAD_SUFFIXES:
        if declared is not None:
            _sha_text(declared, f"{role}.sha256")
        return {
            "path": path,
            "sha256": declared,
            "content_read_by_builder": False,
            "deferred_until_parent_after_reservation": True,
            "stat_at_prepare": record.get("stat", record.get("stat_at_prepare")),
            "role": role,
        }
    if declared is None:
        _fail(f"{role} metadata reference lacks SHA")
    _sha_text(declared, f"{role}.sha256")
    # The manifest is authoritative for the digest.  We stat the path to
    # catch a missing source without reading its content a second time here.
    info = _regular_metadata(Path(path))
    return {
        "path": path,
        "sha256": declared,
        "content_read_by_builder": False,
        "stat_at_prepare": {
            "st_dev": int(info.st_dev), "st_ino": int(info.st_ino),
            "size": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "ctime_ns": int(info.st_ctime_ns),
        },
        "role": role,
    }


def _owner_ref(value: Mapping[str, Any], role: str) -> dict[str, Any]:
    path = value.get("path")
    sha = value.get("sha256")
    if not isinstance(path, str) or not isinstance(sha, str):
        _fail(f"{role} owner proof lacks path/SHA")
    return _ref({"path": path, "sha256": sha}, role=role)


def _source_current_cases(manifest: Mapping[str, Any], wanted: set[str] | None) -> list[Mapping[str, Any]]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        _fail("F6 manifest has no cases")
    selected: dict[str, Mapping[str, Any]] = {}
    for case in cases:
        if not isinstance(case, Mapping) or case.get("grid") != "source_current":
            continue
        case_id = case.get("physical_case_id")
        if not isinstance(case_id, str):
            _fail("source-current case lacks physical_case_id")
        if wanted is not None and case_id not in wanted:
            continue
        if case_id in selected:
            _fail(f"duplicate source-current physical case: {case_id}")
        selected[case_id] = case
    if wanted is not None and set(selected) != wanted:
        _fail(f"requested source-current cases missing: {sorted(wanted - set(selected))}")
    if not selected:
        _fail("no source-current F6 cases selected")
    return [selected[key] for key in sorted(selected)]


def _case_contract(case: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    case_id = case.get("physical_case_id")
    if not isinstance(case_id, str):
        _fail("case physical_case_id is missing")
    if case.get("identity_status") not in {"PASS", "PASS_DOMAIN_EQUIVALENCE"}:
        _fail(f"{case_id} does not have a passing producer identity")
    domain = case.get("domain_equivalence_v8")
    if not isinstance(domain, Mapping) or domain.get("status") != "PASS_DIRECT_PRODUCER_PHYSICAL_ID":
        _fail(f"{case_id} lacks direct producer physical identity")
    source_identity = domain.get("source_identity")
    producer = case.get("producer_identity_v6")
    if not isinstance(source_identity, Mapping) or not isinstance(producer, Mapping):
        _fail(f"{case_id} lacks source/producer identity closure")
    if source_identity.get("physical_case_id") != case_id or producer.get("physical_case_id") != case_id:
        _fail(f"{case_id} producer identity does not match case")
    if producer.get("physical_case_status") != "PASS_ACTUAL_PRODUCER_REQUEST":
        _fail(f"{case_id} producer request is not actual-pass metadata")
    mapping = case.get("domain_mapping_v6")
    if not isinstance(mapping, Mapping):
        _fail(f"{case_id} lacks domain mapping")
    owner = mapping.get("owner_proof")
    rigid = mapping.get("rigid_proof")
    if not isinstance(owner, Mapping) or not isinstance(rigid, Mapping):
        _fail(f"{case_id} lacks ROOT252/ROOT244 owner predicates")
    xml = source_identity.get("source_xml")
    definition = source_identity.get("source_def_record")
    receipt = {
        "path": source_identity.get("source_receipt_path"),
        "sha256": source_identity.get("source_receipt_sha256"),
    }
    source_bi4 = {
        "path": source_identity.get("source_bi4_path"),
        "known_sha256": source_identity.get("source_bi4_sha256"),
    }
    if not isinstance(xml, Mapping) or not isinstance(definition, Mapping):
        _fail(f"{case_id} lacks generated XML/Def metadata")
    refs = [
        _ref(xml, role="generated_xml"),
        _ref(definition, role="source_def"),
        _ref(receipt, role="producer_receipt"),
        _ref(source_bi4, role="native_bi4", payload=True),
        _owner_ref(owner, "continuous_owner_proof"),
        _owner_ref(rigid, "rigid_owner_proof"),
    ]
    deferred = case.get("deferred")
    if not isinstance(deferred, Mapping):
        _fail(f"{case_id} deferred source closure is missing")
    deferred_refs = []
    for role, value in sorted(deferred.items()):
        if not isinstance(value, Mapping):
            _fail(f"{case_id} deferred role {role} is malformed")
        deferred_refs.append(_ref(value, role=role, payload=True))
    return {
        "case_identity": {
            "family_id": "F6",
            "physical_case_id": case_id,
            "producer_case_id": producer.get("case_id", case_id),
            "producer_attempt_id": producer.get("attempt_id"),
            "historical_alias": "REQUIRE_CURRENT_PLAN_EXACT_NO_ALIAS",
        },
        "identity_contract": {
            "authority": "producer_identity_v6.physical_case_id",
            "manifest_identity_status": case.get("identity_status"),
            "historical_alias_allowed": False,
            "current_plan_join": "required after parent reservation",
            "required_plan_fields": [
                "physical_case_id", "historical_alias", "actual_saved_mask_coverage",
                "source_join_status", "status",
            ],
        },
        "producer_role": {
            "status": "SOURCE_BOUND",
            "request_status": producer.get("physical_case_status"),
            "scope": "POSITION_ONLY_INITIAL_SUPPORT",
            "source_roles": refs,
            "deferred_roles": deferred_refs,
        },
        "owner_predicate": {
            "status": "SOURCE_BOUND_INITIAL_GEOMETRY_ONLY",
            "basis": manifest.get("source_binding", {}).get("continuous_owner_basis"),
            "continuous_owner_mass_kg": manifest.get("source_binding", {}).get("continuous_owner_mass_kg"),
            "physical_massbody_kg": manifest.get("source_binding", {}).get("physical_massbody_kg"),
            "no_rescale": manifest.get("source_binding", {}).get("no_rescale"),
            "proofs": [_owner_ref(owner, "continuous_owner_proof"), _owner_ref(rigid, "rigid_owner_proof")],
            "missing": ["Vel", "Rhop", "MassFluid", "MassBound", "world_axis_calibration"],
        },
        "event_roles": {
            "source": "UNKNOWN_UNTIL_EVENT_SOURCE_REGION_PROOF",
            "region_owner": "UNKNOWN_UNTIL_EXPLICIT_TARGET_REGION_PROOF",
            "control": "UNKNOWN_FOR_F6_INITIAL_SUPPORT_CONTRACT",
            "event_admission": "UNKNOWN",
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _plan_admission(plan: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = plan.get("case_records", plan.get("cases"))
    if not isinstance(rows, list):
        _fail("CURRENT plan has no explicit case rows")
    result = {}
    for contract in cases:
        case_id = contract["case_identity"]["physical_case_id"]
        matches = [row for row in rows if isinstance(row, Mapping) and row.get("physical_case_id") == case_id]
        if len(matches) != 1:
            _fail(f"CURRENT plan does not have exactly one row for {case_id}")
        row = matches[0]
        admitted = (
            row.get("historical_alias") == "NONE"
            and row.get("actual_saved_mask_coverage") is True
            and row.get("source_join_status") == "EXACT_CURRENT_AUDIT_METADATA_JOIN"
            and row.get("status") in COMPLETED_PLAN_STATUSES
        )
        if not admitted:
            _fail(f"CURRENT plan case {case_id} is not admissible: alias/coverage/status predicate failed")
        result[case_id] = {
            "admitted": admitted,
            "historical_alias": row.get("historical_alias"),
            "actual_saved_mask_coverage": row.get("actual_saved_mask_coverage"),
            "source_join_status": row.get("source_join_status"),
            "status": row.get("status"),
        }
    return result


def build_contract(
    manifest_path: Path | str,
    parent_request_path: Path | str,
    *,
    output_path: Path | str | None = None,
    case_ids: set[str] | None = None,
    plan_path: Path | str | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).expanduser()
    parent_request_path = Path(parent_request_path).expanduser()
    manifest, manifest_sha, manifest_stat = _read_json(manifest_path, "F6 support manifest")
    if manifest.get("schema") != "ds02.stage2.f6-initial-native-support-manifest.v8":
        _fail("unsupported F6 support manifest schema")
    parent_request, parent_sha, parent_stat = _read_json(parent_request_path, "ROOT276 parent request")
    if parent_request.get("schema") != "ds02.request.v1":
        _fail("ROOT276 parent request is not ds02.request.v1")
    cases = [_case_contract(case, manifest) for case in _source_current_cases(manifest, case_ids)]
    plan_result = None
    plan_ref = None
    if plan_path is not None:
        plan, plan_sha, plan_stat = _read_json(Path(plan_path).expanduser(), "CURRENT lifecycle plan")
        plan_result = _plan_admission(plan, cases)
        plan_ref = {"path": str(Path(plan_path).expanduser()), "sha256": plan_sha, "stat": plan_stat}
    contract = {
        "schema": SCHEMA,
        "status": "SOURCE_PREPARED_PENDING_CURRENT_PLAN_JOIN" if plan_result is None else "SOURCE_PREPARED_CURRENT_PLAN_CHECKED",
        "production_eligible": False,
        "payload_content_read_by_builder": False,
        "launch_performed": False,
        "source_manifest": {"path": str(manifest_path), "sha256": manifest_sha, "stat": manifest_stat},
        "parent_task": {
            "namespace": 276,
            "path": str(parent_request_path),
            "sha256": parent_sha,
            "stat": parent_stat,
            "parent_v8_is_sole_resource_owner": True,
            "actual_parent_run": "root-owned only; this builder does not launch",
        },
        "current_plan": plan_ref or {
            "status": "REQUIRED_AT_PARENT_ADMISSION",
            "historical_alias": "must be NONE",
            "actual_saved_mask_coverage": True,
            "source_join_status": "EXACT_CURRENT_AUDIT_METADATA_JOIN",
        },
        "cases": cases,
        "plan_admission": plan_result,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "claim_boundary": {
            "scope": "F6 source-current position-only initial support and owner predicate metadata",
            "event_labels": "UNKNOWN",
            "region_owner": "UNKNOWN",
            "control": "UNKNOWN_FOR_INITIAL_SUPPORT_ONLY",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "mass_fields_not_present": ["Vel", "Rhop", "MassFluid", "MassBound"],
        },
    }
    if output_path is not None:
        output_path = Path(output_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return contract


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--parent-request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--current-plan", type=Path)
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args(argv)
    try:
        contract = build_contract(
            args.manifest, args.parent_request, output_path=args.output,
            case_ids=set(args.cases) if args.cases else None,
            plan_path=args.current_plan,
        )
    except F6ProducerRoleContractError as error:
        print(f"F6_PRODUCER_ROLE_CONTRACT_ERROR: {error}")
        return 2
    print(json.dumps({"schema": contract["schema"], "status": contract["status"],
                      "output": str(args.output), "cases": len(contract["cases"]),
                      "production_eligible": contract["production_eligible"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
