#!/usr/bin/env python3
"""Validate a bounded, non-authorizing F3 V13 reader capability envelope.

This module is deliberately separate from ``core_dataset.py`` and
``core_learning.py``.  It validates only a data-shaped capability envelope;
it does not open an HDF5 file, inspect an FD, invoke fs-verity, authenticate a
process, or authorize a formal reader/training/evaluation run.

The envelope is useful for closing the *shape* of the future V13 contract and
for keeping negative tests executable.  Even a structurally complete
synthetic envelope therefore returns ``formal_eligible=False`` and
``qualification_credit=0`` until a real reader/broker/worker implementation
binds these claims to runtime evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


CONTRACT_SCHEMA = "core.f3.formal_reader_capability_contract.v1"
REPORT_SCHEMA = "core.f3.formal_reader_capability_blocker.v1"
NONCE_HEX_LENGTH = 64
IDENTITY_ROLES = ("producer", "broker", "worker")
DESCRIPTOR_ROLES = ("geometry", "control")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical(value).encode("utf-8"))


def _is_sha256(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdefABCDEF" for character in value))


def _is_nonce(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == NONCE_HEX_LENGTH
            and all(character in "0123456789abcdefABCDEF" for character in value))


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _relative_asset_path(value: Any) -> bool:
    if not _nonempty(value):
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _error(blocker: str, message: str) -> dict[str, str]:
    return {"code": blocker, "message": message}


def _validate_source_trust(contract: Mapping[str, Any], blockers: list[dict[str, str]]) -> bool:
    source = contract.get("source_trust")
    if not isinstance(source, Mapping):
        blockers.append(_error(
            "SOURCE_TRUST_REQUIRED",
            "source_trust must provide an attested held-FD/fs-verity snapshot",
        ))
        return False
    checks = {
        "mode": source.get("mode") == "held_fd_fsverity",
        "attested": source.get("attested") is True,
        "same_fd_snapshot": source.get("same_fd_snapshot") is True,
        "snapshot_nonce": _is_nonce(source.get("snapshot_nonce")),
    }
    if not all(checks.values()):
        blockers.append(_error(
            "SOURCE_TRUST_REQUIRED",
            "held-FD, fs-verity, same-FD, and snapshot nonce claims are not all present",
        ))
        return False
    rows = source.get("case_snapshots")
    if not isinstance(rows, list) or not rows:
        blockers.append(_error(
            "SOURCE_SNAPSHOT_REQUIRED",
            "source_trust.case_snapshots must cover every registered case",
        ))
        return False
    case_ids: set[str] = set()
    valid = True
    for row in rows:
        if not isinstance(row, Mapping):
            valid = False
            continue
        case_id = row.get("case_id")
        if not _nonempty(case_id) or case_id in case_ids:
            valid = False
        elif isinstance(case_id, str):
            case_ids.add(case_id)
        identity = row.get("fd_identity")
        measurement = row.get("measurement")
        if not _is_sha256(row.get("source_sha256")) or not isinstance(row.get("bytes"), int) \
                or row.get("bytes", 0) <= 0:
            valid = False
        if not isinstance(identity, Mapping) or any(
                type(identity.get(key)) is not int or identity.get(key) < 0
                for key in ("st_dev", "st_ino", "st_size")):
            valid = False
        if (not isinstance(measurement, Mapping)
                or measurement.get("algorithm") != "fs-verity"
                or not _is_sha256(measurement.get("digest"))):
            valid = False
    if not valid:
        blockers.append(_error(
            "SOURCE_SNAPSHOT_INVALID",
            "each source snapshot requires unique case identity, bytes, FD identity, and fs-verity digest",
        ))
    return valid


def _validate_descriptors(contract: Mapping[str, Any], blockers: list[dict[str, str]]) -> bool:
    descriptors = contract.get("descriptors")
    if not isinstance(descriptors, Mapping):
        blockers.append(_error(
            "DESCRIPTOR_BINDING_REQUIRED",
            "geometry/control descriptor bundle is missing",
        ))
        return False
    valid = True
    for role in DESCRIPTOR_ROLES:
        descriptor = descriptors.get(role)
        if not isinstance(descriptor, Mapping):
            valid = False
            continue
        if (not _relative_asset_path(descriptor.get("path"))
                or not _is_sha256(descriptor.get("sha256"))
                or not _nonempty(descriptor.get("version"))):
            valid = False
    if not valid:
        blockers.append(_error(
            "DESCRIPTOR_BINDING_REQUIRED",
            "geometry/control descriptors require relative path, SHA-256, and version",
        ))
    return valid


def _validate_manifest_binding(contract: Mapping[str, Any], blockers: list[dict[str, str]]) -> bool:
    manifest = contract.get("manifest_identity")
    valid = (isinstance(manifest, Mapping)
             and _relative_asset_path(manifest.get("path"))
             and _is_sha256(manifest.get("sha256")))
    if not valid:
        blockers.append(_error(
            "MANIFEST_BINDING_REQUIRED",
            "the capability envelope must bind the exact manifest path and SHA-256",
        ))
    return valid


def _validate_identities(contract: Mapping[str, Any], blockers: list[dict[str, str]]) -> bool:
    identities = contract.get("identities")
    if not isinstance(identities, Mapping) or not _is_nonce(identities.get("session_nonce")):
        blockers.append(_error(
            "IDENTITY_NONCE_REQUIRED",
            "session nonce and producer/broker/worker identities are required",
        ))
        return False
    valid = True
    names: list[str] = []
    nonces: list[str] = [identities["session_nonce"].lower()]
    for role in IDENTITY_ROLES:
        identity = identities.get(role)
        if not isinstance(identity, Mapping) or not _nonempty(identity.get("identity")) \
                or not _is_nonce(identity.get("nonce")):
            valid = False
            continue
        names.append(identity["identity"])
        nonces.append(identity["nonce"].lower())
    if len(names) != len(set(names)) or len(nonces) != len(set(nonces)):
        valid = False
    if not valid:
        blockers.append(_error(
            "IDENTITY_NONCE_REQUIRED",
            "producer/broker/worker identities and nonces must be present and unique",
        ))
    return valid


def _validate_case_bindings(contract: Mapping[str, Any], blockers: list[dict[str, str]]) -> bool:
    source = contract.get("source_trust")
    descriptors = contract.get("descriptors")
    rows = contract.get("case_bindings")
    if not isinstance(source, Mapping) or not isinstance(descriptors, Mapping) \
            or not isinstance(rows, list):
        blockers.append(_error(
            "CASE_BINDING_REQUIRED",
            "case bindings cannot be checked without source and descriptor records",
        ))
        return False
    snapshot_rows = source.get("case_snapshots")
    if not isinstance(snapshot_rows, list):
        blockers.append(_error(
            "CASE_BINDING_REQUIRED",
            "case bindings require a list of source snapshot records",
        ))
        return False
    snapshots: dict[str, Mapping[str, Any]] = {}
    for snapshot in snapshot_rows:
        if not isinstance(snapshot, Mapping):
            continue
        case_id = snapshot.get("case_id")
        if isinstance(case_id, str) and case_id.strip():
            snapshots[case_id] = snapshot
    expected_nonce = source.get("snapshot_nonce")
    expected_geometry = descriptors.get("geometry", {}).get("sha256") \
        if isinstance(descriptors.get("geometry"), Mapping) else None
    expected_control = descriptors.get("control", {}).get("sha256") \
        if isinstance(descriptors.get("control"), Mapping) else None
    bound_ids: set[str] = set()
    valid = True
    for row in rows:
        if not isinstance(row, Mapping):
            valid = False
            continue
        case_id = row.get("case_id")
        snapshot = snapshots.get(case_id)
        if not _nonempty(case_id) or case_id in bound_ids or snapshot is None:
            valid = False
        elif isinstance(case_id, str):
            bound_ids.add(case_id)
        if (not isinstance(snapshot, Mapping)
                or row.get("source_sha256") != snapshot.get("source_sha256")
                or row.get("snapshot_nonce") != expected_nonce
                or row.get("geometry_sha256") != expected_geometry
                or row.get("control_sha256") != expected_control):
            valid = False
    if bound_ids != set(snapshots):
        valid = False
    if not valid:
        blockers.append(_error(
            "DESCRIPTOR_REBIND",
            "case bindings do not remain bound to the held source snapshot and descriptor hashes",
        ))
    return valid


def validate_capability_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the future contract without authorizing any formal action.

    ``capability_contract_valid`` means that the supplied envelope has the
    required shape and internal bindings.  It is intentionally not an
    admission decision: this isolated validator has no authority to attest a
    real FD, process, broker, worker, or source producer.
    """
    blockers: list[dict[str, str]] = []
    if not isinstance(contract, Mapping):
        blockers.append(_error("CAPABILITY_CONTRACT_REQUIRED", "contract must be a JSON object"))
        return _result(contract_schema=None, checks={}, blockers=blockers)
    if contract.get("schema") != CONTRACT_SCHEMA:
        blockers.append(_error("CAPABILITY_CONTRACT_SCHEMA", "unsupported capability contract schema"))
    formal_release = contract.get("formal_release") is True
    if not formal_release:
        blockers.append(_error(
            "FORMAL_RELEASE_REQUIRED",
            "formal_release must be true before any formal reader admission can be considered",
        ))
    checks = {
        "manifest_binding": _validate_manifest_binding(contract, blockers),
        "source_trust": _validate_source_trust(contract, blockers),
        "descriptor_binding": _validate_descriptors(contract, blockers),
        "identity_nonce": _validate_identities(contract, blockers),
        "case_binding": _validate_case_bindings(contract, blockers),
        "formal_release": formal_release,
    }
    # Preserve first occurrence of a blocker code so callers can compare
    # receipts deterministically even when several dependent checks fail.
    unique_blockers: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in blockers:
        if item["code"] not in seen:
            unique_blockers.append(item)
            seen.add(item["code"])
    return _result(
        contract_schema=contract.get("schema"), checks=checks,
        blockers=unique_blockers,
    )


def _result(*, contract_schema: Any, checks: Mapping[str, bool],
            blockers: list[dict[str, str]]) -> dict[str, Any]:
    capability_valid = bool(checks) and all(checks.values()) and not blockers
    return {
        "schema": REPORT_SCHEMA,
        "validator_schema": CONTRACT_SCHEMA,
        "contract_schema": contract_schema,
        "validation_scope": "synthetic_capability_envelope_only",
        "checks": dict(checks),
        "capability_contract_valid": capability_valid,
        # This module never has authority to make a formal admission claim.
        "authorizes_formal": False,
        "formal_eligible": False,
        "qualification_credit": 0,
        "blockers": blockers,
        "execution_constraints": {
            "read_only": True,
            "opens_source_fd": False,
            "verifies_fsverity": False,
            "authenticates_process_identity": False,
            "starts_gpu": False,
            "starts_solver": False,
            "starts_worker": False,
            "starts_queue": False,
            "mutates_registry": False,
            "mutates_ledger": False,
        },
    }


def inspect_manifest(manifest: Mapping[str, Any], *, raw_sha256: str | None = None,
                     manifest_path: str | None = None) -> dict[str, Any]:
    """Describe what a manifest contains without treating it as V13 capability.

    This function intentionally reports content-addressed references as
    *metadata only*.  A manifest cannot supply held-FD source trust or runtime
    producer/broker/worker identity.
    """
    cases = manifest.get("cases") if isinstance(manifest, Mapping) else None
    rows = [row for row in cases if isinstance(row, Mapping)] if isinstance(cases, list) else []
    source_metadata = all(
        _is_sha256(row.get("sha256")) and isinstance(row.get("bytes"), int)
        and row.get("bytes", 0) > 0 for row in rows
    ) and bool(rows)
    descriptor_metadata = all(
        isinstance(row.get("known_inputs_ref"), Mapping)
        and all(
            isinstance(row["known_inputs_ref"].get(role), Mapping)
            and _is_sha256(row["known_inputs_ref"][role].get("sha256"))
            and _relative_asset_path(row["known_inputs_ref"][role].get("path"))
            for role in DESCRIPTOR_ROLES
        ) for row in rows
    ) and bool(rows)
    return {
        "schema": REPORT_SCHEMA,
        "validation_scope": "manifest_inventory_only",
        "manifest": {
            "path": manifest_path,
            "raw_sha256": raw_sha256,
            "declared_formal_release": manifest.get("formal_release") is True,
            "case_count": len(rows),
            "schema": manifest.get("schema"),
        },
        "observed_capabilities": {
            "source_hash_and_byte_metadata": source_metadata,
            "content_addressed_geometry_control_metadata": descriptor_metadata,
            "held_fd_snapshot_capability": False,
            "fsverity_measurement_attestation": False,
            "same_fd_case_binding": False,
            "producer_broker_worker_identity_chain": False,
            "nonce_bound_session": False,
            "formal_reader_capability_envelope": False,
        },
        "blockers": [
            _error("SOURCE_TRUST_REQUIRED", "manifest does not attest a held-FD/fs-verity source snapshot"),
            _error("DESCRIPTOR_BINDING_REQUIRED", "manifest refs are metadata; no runtime descriptor bundle is bound"),
            _error("IDENTITY_NONCE_REQUIRED", "manifest has no producer/broker/worker identity and nonce chain"),
            _error("CAPABILITY_CONTRACT_REQUIRED", "no V13 capability envelope is present"),
            *([] if manifest.get("formal_release") is True else [
                _error("FORMAL_RELEASE_REQUIRED", "manifest declares formal_release=false"),
            ]),
        ],
        "formal_eligible": False,
        "qualification_credit": 0,
        "execution_constraints": {
            "read_only": True,
            "opens_source_fd": False,
            "starts_gpu": False,
            "starts_solver": False,
            "starts_worker": False,
            "starts_queue": False,
            "mutates_registry": False,
            "mutates_ledger": False,
        },
    }


def _load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    return payload, sha256_bytes(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    manifest, raw_sha256 = _load_manifest(args.manifest)
    report = inspect_manifest(
        manifest, raw_sha256=raw_sha256, manifest_path=str(args.manifest),
    )
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised by CLI smoke tests
    raise SystemExit(main())
