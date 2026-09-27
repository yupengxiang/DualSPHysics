#!/usr/bin/env python3
"""Strict, non-authorizing verifier for the future F3 reader capability.

``f3_formal_reader_capability_contract_v1`` already checks the shape of a
synthetic source/descriptor envelope.  This module checks the narrower runtime
binding that that envelope intentionally leaves open: every case's source FD
and geometry/control FDs must be members of one held-FD-only bundle, and every
member must carry the same session, source snapshot nonce, and attempt
identity.  A supplied attempt history is also checked for duplicate IDs,
nonce reuse, bundle reuse, and FD-token reuse.

The verifier is deliberately a JSON-only sidecar.  It does not open an FD,
resolve a pathname, inspect HDF5, verify fs-verity, authenticate a broker or
worker, consult a registry/ledger, or start any process.  Consequently even a
fully consistent synthetic strict envelope is diagnostic evidence only:
``formal_eligible`` is always false and ``qualification_credit`` is always
zero.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from scripts.f3_formal_reader_capability_contract_v1 import (
    CONTRACT_SCHEMA as BASE_CONTRACT_SCHEMA,
    canonical_sha256,
    validate_capability_contract,
)


STRICT_CONTRACT_SCHEMA = "core.f3.formal_reader_strict_capability_contract.v1"
REPORT_SCHEMA = "core.f3.formal_reader_strict_capability_blocker.v1"
NONCE_HEX_LENGTH = 64
ROLES = ("geometry", "control")
ATTEMPT_STATUSES = frozenset({"consumed", "current"})
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
FD_TOKEN = re.compile(r"^fd:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
FD_IDENTITY_FIELDS = frozenset({"st_dev", "st_ino", "st_size"})
TOP_LEVEL_FIELDS = frozenset({
    "schema", "formal_release", "base_contract", "session", "attempt",
    "descriptor_bundle", "attempt_history",
})
SESSION_FIELDS = frozenset({
    "session_id", "session_nonce", "source_snapshot_nonce",
    "source_inventory_sha256",
})
ATTEMPT_FIELDS = frozenset({
    "attempt_id", "attempt_nonce", "session_id", "session_nonce",
    "source_snapshot_nonce", "descriptor_bundle_id",
})
BUNDLE_FIELDS = frozenset({
    "bundle_id", "session_id", "session_nonce", "source_snapshot_nonce",
    "attempt_id", "attempt_nonce", "access_mode", "path_reopen",
    "path_rebind", "cases",
})
CASE_FIELDS = frozenset({"case_id", "source", "descriptors"})
SOURCE_FIELDS = frozenset({
    "case_id", "source_sha256", "bytes", "fd_identity", "fd_token",
    "bundle_id", "session_id", "session_nonce", "source_snapshot_nonce",
    "attempt_id", "attempt_nonce", "access_mode", "path_reopen",
    "path_rebind",
})
DESCRIPTOR_FIELDS = frozenset({
    "role", "case_id", "sha256", "version", "fd_identity", "fd_token",
    "source_fd_token", "source_sha256", "bundle_id", "session_id",
    "session_nonce", "source_snapshot_nonce", "attempt_id", "attempt_nonce",
    "access_mode", "path_reopen", "path_rebind",
})
HISTORY_FIELDS = frozenset({
    "attempt_id", "attempt_nonce", "session_id", "session_nonce",
    "source_snapshot_nonce", "descriptor_bundle_id", "fd_tokens",
    "fd_token_digest", "status",
})


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _nonempty_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(IDENTIFIER.fullmatch(value))


def _nonce(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == NONCE_HEX_LENGTH
            and all(character in "0123456789abcdefABCDEF" for character in value))


def _sha256(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdefABCDEF" for character in value))


def _add(blockers: list[dict[str, str]], code: str, message: str) -> None:
    if not any(item.get("code") == code for item in blockers):
        blockers.append(_error(code, message))


def _fd_identity(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, Mapping) or set(value) != FD_IDENTITY_FIELDS:
        return None
    if any(type(value[key]) is not int or value[key] < 0
           for key in FD_IDENTITY_FIELDS):
        return None
    if value["st_size"] <= 0:
        return None
    return (value["st_dev"], value["st_ino"], value["st_size"])


def _token(value: Any) -> bool:
    return isinstance(value, str) and bool(FD_TOKEN.fullmatch(value))


def _source_inventory_digest(base: Mapping[str, Any]) -> str | None:
    source = base.get("source_trust")
    rows = source.get("case_snapshots") if isinstance(source, Mapping) else None
    if not isinstance(rows, list) or not rows:
        return None
    projected: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("case_id"), str):
            return None
        identity = row.get("fd_identity")
        if _fd_identity(identity) is None:
            return None
        measurement = row.get("measurement")
        if not isinstance(measurement, Mapping):
            return None
        projected.append({
            "case_id": row["case_id"],
            "source_sha256": row.get("source_sha256"),
            "bytes": row.get("bytes"),
            "fd_identity": {
                key: identity[key] for key in ("st_dev", "st_ino", "st_size")
            },
            "measurement": {
                "algorithm": measurement.get("algorithm"),
                "digest": measurement.get("digest"),
            },
        })
    projected.sort(key=lambda row: row["case_id"])
    try:
        return canonical_sha256(projected)
    except (TypeError, ValueError, OverflowError):
        return None


def _base_rows(base: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]],
                                                   Mapping[str, Any] | None,
                                                   Mapping[str, Any] | None]:
    source = base.get("source_trust")
    rows = source.get("case_snapshots") if isinstance(source, Mapping) else None
    snapshots: dict[str, Mapping[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping) and isinstance(row.get("case_id"), str):
                snapshots[row["case_id"]] = row
    descriptors = base.get("descriptors")
    geometry = descriptors.get("geometry") if isinstance(descriptors, Mapping) else None
    control = descriptors.get("control") if isinstance(descriptors, Mapping) else None
    return snapshots, geometry if isinstance(geometry, Mapping) else None, \
        control if isinstance(control, Mapping) else None


def _context_matches(value: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(value.get(key) == expected[key] for key in expected)


def _forbidden_path_claim(value: Any) -> bool:
    """Return true for pathname references or a positive reopen/rebind claim."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"path", "pathname", "path_ref", "path_reference"}:
                return True
            if key in {"path_reopen", "path_rebind", "reopen_by_path",
                       "rebind_by_path"} and child is not False:
                return True
            if _forbidden_path_claim(child):
                return True
    elif isinstance(value, list):
        return any(_forbidden_path_claim(child) for child in value)
    return False


def _validate_session(contract: Mapping[str, Any], base: Mapping[str, Any],
                      blockers: list[dict[str, str]]) -> tuple[bool, dict[str, Any]]:
    session = contract.get("session")
    valid = isinstance(session, Mapping) and set(session) == SESSION_FIELDS
    source = base.get("source_trust")
    expected_snapshot_nonce = source.get("snapshot_nonce") \
        if isinstance(source, Mapping) else None
    inventory_digest = _source_inventory_digest(base)
    if not valid:
        _add(blockers, "SESSION_BINDING_REQUIRED",
             "session must bind an exact source snapshot inventory and nonce")
        return False, {}
    valid = (
        _nonempty_identifier(session.get("session_id"))
        and _nonce(session.get("session_nonce"))
        and _nonce(session.get("source_snapshot_nonce"))
        and _sha256(session.get("source_inventory_sha256"))
        and session.get("source_snapshot_nonce") == expected_snapshot_nonce
        and session.get("source_inventory_sha256") == inventory_digest
        and len({session.get("session_nonce"), session.get("source_snapshot_nonce")}) == 2
    )
    if not valid:
        _add(blockers, "SESSION_BINDING_REQUIRED",
             "session identity, nonce, source snapshot nonce, or source inventory digest is invalid")
    return valid, dict(session)


def _validate_attempt(contract: Mapping[str, Any], session: Mapping[str, Any],
                      blockers: list[dict[str, str]]) -> tuple[bool, dict[str, Any]]:
    attempt = contract.get("attempt")
    valid = isinstance(attempt, Mapping) and set(attempt) == ATTEMPT_FIELDS
    if not valid:
        _add(blockers, "ATTEMPT_BINDING_REQUIRED",
             "attempt must bind one unique attempt nonce to the session and bundle")
        return False, {}
    session_nonce = session.get("session_nonce")
    source_nonce = session.get("source_snapshot_nonce")
    valid = (
        _nonempty_identifier(attempt.get("attempt_id"))
        and _nonce(attempt.get("attempt_nonce"))
        and _nonempty_identifier(attempt.get("descriptor_bundle_id"))
        and attempt.get("session_id") == session.get("session_id")
        and attempt.get("session_nonce") == session_nonce
        and attempt.get("source_snapshot_nonce") == source_nonce
        and attempt.get("attempt_nonce") not in (session_nonce, source_nonce)
    )
    if not valid:
        _add(blockers, "ATTEMPT_BINDING_REQUIRED",
             "attempt identity, nonce, session, or source snapshot binding is invalid")
    return valid, dict(attempt)


def _validate_bundle(contract: Mapping[str, Any], base: Mapping[str, Any],
                     session: Mapping[str, Any], attempt: Mapping[str, Any],
                     blockers: list[dict[str, str]]) -> tuple[bool, list[str]]:
    bundle = contract.get("descriptor_bundle")
    if not isinstance(bundle, Mapping) or set(bundle) != BUNDLE_FIELDS:
        _add(blockers, "DESCRIPTOR_BUNDLE_REQUIRED",
             "descriptor_bundle must be an exact held-FD-only bundle")
        return False, []
    if _forbidden_path_claim(bundle):
        _add(blockers, "PATH_REOPEN_FORBIDDEN",
             "strict capability bundles cannot contain pathname references or path reopen/rebind claims")
    context = {
        "bundle_id": bundle.get("bundle_id"),
        "session_id": session.get("session_id"),
        "session_nonce": session.get("session_nonce"),
        "source_snapshot_nonce": session.get("source_snapshot_nonce"),
        "attempt_id": attempt.get("attempt_id"),
        "attempt_nonce": attempt.get("attempt_nonce"),
    }
    valid = (
        _nonempty_identifier(bundle.get("bundle_id"))
        and bundle.get("bundle_id") == attempt.get("descriptor_bundle_id")
        and bundle.get("session_id") == context["session_id"]
        and bundle.get("session_nonce") == context["session_nonce"]
        and bundle.get("source_snapshot_nonce") == context["source_snapshot_nonce"]
        and bundle.get("attempt_id") == context["attempt_id"]
        and bundle.get("attempt_nonce") == context["attempt_nonce"]
        and bundle.get("access_mode") == "held_fd_only"
        and bundle.get("path_reopen") is False
        and bundle.get("path_rebind") is False
    )
    if not valid:
        _add(blockers, "DESCRIPTOR_BUNDLE_REQUIRED",
             "descriptor bundle context must be held_fd_only and exactly bound to the active attempt")

    snapshots, geometry, control = _base_rows(base)
    cases = bundle.get("cases")
    expected_case_ids = list(snapshots)
    if not isinstance(cases, list) or not cases:
        _add(blockers, "DESCRIPTOR_BUNDLE_REQUIRED",
             "descriptor bundle must cover every source snapshot case")
        return False, []
    if any(not isinstance(row, Mapping) or set(row) != CASE_FIELDS for row in cases):
        _add(blockers, "DESCRIPTOR_BUNDLE_REQUIRED",
             "each descriptor bundle case must use the exact source/descriptors fields")
        return False, []
    case_ids = [row.get("case_id") for row in cases]
    case_ids_are_unique_strings = (
        all(isinstance(case_id, str) for case_id in case_ids)
        and len(set(case_ids)) == len(case_ids)
    )
    if case_ids != expected_case_ids or not case_ids_are_unique_strings:
        _add(blockers, "SOURCE_IDENTITY_BINDING_REQUIRED",
             "descriptor bundle case order and coverage must equal the source snapshot inventory")
        valid = False

    tokens: list[str] = []
    identities: set[tuple[int, int, int]] = set()
    all_tokens: set[str] = set()
    for case in cases:
        case_id = case.get("case_id")
        snapshot = snapshots.get(case_id) if isinstance(case_id, str) else None
        source = case.get("source")
        descriptors = case.get("descriptors")
        if snapshot is None or not isinstance(source, Mapping) \
                or set(source) != SOURCE_FIELDS \
                or not isinstance(descriptors, Mapping) \
                or set(descriptors) != set(ROLES):
            _add(blockers, "SOURCE_IDENTITY_BINDING_REQUIRED",
                 "each case must bind its exact source held FD and both descriptor roles")
            valid = False
            continue
        source_identity = _fd_identity(source.get("fd_identity"))
        expected_identity = _fd_identity(snapshot.get("fd_identity"))
        source_ok = (
            source.get("case_id") == case_id
            and source.get("source_sha256") == snapshot.get("source_sha256")
            and source.get("bytes") == snapshot.get("bytes")
            and source_identity is not None
            and source_identity == expected_identity
            and _token(source.get("fd_token"))
            and source.get("bundle_id") == bundle.get("bundle_id")
            and _context_matches(source, context)
            and source.get("access_mode") == "held_fd_only"
            and source.get("path_reopen") is False
            and source.get("path_rebind") is False
            and source.get("case_id") == case_id
        )
        if not source_ok:
            _add(blockers, "SOURCE_IDENTITY_BINDING_REQUIRED",
                 "source held-FD token, inode identity, digest, and attempt context do not match")
            valid = False
        else:
            if source["fd_token"] in all_tokens or source_identity in identities:
                _add(blockers, "DESCRIPTOR_REBIND_FORBIDDEN",
                     "a source held-FD token or identity cannot be reused across cases")
                valid = False
            else:
                tokens.append(source["fd_token"])
                all_tokens.add(source["fd_token"])
                identities.add(source_identity)

        for role in ROLES:
            descriptor = descriptors.get(role)
            expected_descriptor = geometry if role == "geometry" else control
            if not isinstance(descriptor, Mapping) \
                    or set(descriptor) != DESCRIPTOR_FIELDS \
                    or not isinstance(expected_descriptor, Mapping):
                _add(blockers, "DESCRIPTOR_BUNDLE_REQUIRED",
                     "geometry/control descriptor entries must be exact and registered in the base envelope")
                valid = False
                continue
            descriptor_identity = _fd_identity(descriptor.get("fd_identity"))
            descriptor_ok = (
                descriptor.get("role") == role
                and descriptor.get("case_id") == case_id
                and descriptor.get("sha256") == expected_descriptor.get("sha256")
                and descriptor.get("version") == expected_descriptor.get("version")
                and _token(descriptor.get("fd_token"))
                and descriptor.get("source_fd_token") == source.get("fd_token")
                and descriptor.get("source_sha256") == source.get("source_sha256")
                and descriptor_identity is not None
                and descriptor.get("bundle_id") == bundle.get("bundle_id")
                and _context_matches(descriptor, context)
                and descriptor.get("access_mode") == "held_fd_only"
                and descriptor.get("path_reopen") is False
                and descriptor.get("path_rebind") is False
            )
            if not descriptor_ok:
                _add(blockers, "DESCRIPTOR_SOURCE_BINDING_REQUIRED",
                     "descriptor FD must bind the same source FD, session, attempt, and registered digest")
                valid = False
            else:
                if descriptor["fd_token"] in all_tokens or descriptor_identity in identities:
                    _add(blockers, "DESCRIPTOR_REBIND_FORBIDDEN",
                         "descriptor FD tokens and identities must be unique within one held-FD bundle")
                    valid = False
                else:
                    tokens.append(descriptor["fd_token"])
                    all_tokens.add(descriptor["fd_token"])
                    identities.add(descriptor_identity)

    if len(tokens) == len(all_tokens) == len(identities) \
            and case_ids == expected_case_ids:
        tokens = sorted(tokens)
    else:
        tokens = []
    return valid and not any(item["code"] in {
        "DESCRIPTOR_BUNDLE_REQUIRED", "SOURCE_IDENTITY_BINDING_REQUIRED",
        "DESCRIPTOR_SOURCE_BINDING_REQUIRED", "DESCRIPTOR_REBIND_FORBIDDEN",
        "PATH_REOPEN_FORBIDDEN",
    } for item in blockers), tokens


def _validate_history(contract: Mapping[str, Any], session: Mapping[str, Any],
                      attempt: Mapping[str, Any], bundle_tokens: list[str],
                      blockers: list[dict[str, str]]) -> bool:
    history = contract.get("attempt_history")
    if not isinstance(history, list) or not history:
        _add(blockers, "ATTEMPT_REPLAY",
             "attempt_history must contain the active attempt and every supplied prior attempt")
        return False
    current_count = 0
    seen_ids: set[str] = set()
    seen_nonces: set[str] = set()
    seen_bundles: set[str] = set()
    seen_tokens: set[str] = set()
    valid = True
    for row in history:
        if not isinstance(row, Mapping) or set(row) != HISTORY_FIELDS:
            _add(blockers, "ATTEMPT_REPLAY",
                 "attempt history records must use the exact replay-guard fields")
            valid = False
            continue
        attempt_id = row.get("attempt_id")
        attempt_nonce = row.get("attempt_nonce")
        bundle_id = row.get("descriptor_bundle_id")
        fd_tokens = row.get("fd_tokens")
        row_ok = (
            _nonempty_identifier(attempt_id)
            and _nonce(attempt_nonce)
            and _nonempty_identifier(bundle_id)
            and row.get("session_id") == session.get("session_id")
            and row.get("session_nonce") == session.get("session_nonce")
            and row.get("source_snapshot_nonce") == session.get("source_snapshot_nonce")
            and isinstance(row.get("status"), str)
            and row.get("status") in ATTEMPT_STATUSES
            and isinstance(fd_tokens, list)
            and bool(fd_tokens)
            and all(_token(token) for token in fd_tokens)
            and len(fd_tokens) == len(set(fd_tokens))
            and fd_tokens == sorted(fd_tokens)
            and _sha256(row.get("fd_token_digest"))
            and row.get("fd_token_digest") == canonical_sha256(fd_tokens)
        )
        if not row_ok:
            _add(blockers, "ATTEMPT_REPLAY",
                 "attempt history contains an invalid identity, nonce, status, or FD-token digest")
            valid = False
            continue
        if attempt_id in seen_ids or attempt_nonce.lower() in seen_nonces \
                or bundle_id in seen_bundles or seen_tokens.intersection(fd_tokens):
            _add(blockers, "ATTEMPT_REPLAY",
                 "duplicate or cross-attempt replay of attempt identity, bundle, nonce, or held FD token")
            valid = False
        seen_ids.add(attempt_id)
        seen_nonces.add(attempt_nonce.lower())
        seen_bundles.add(bundle_id)
        seen_tokens.update(fd_tokens)
        matches_current = (
            attempt_id == attempt.get("attempt_id")
            and attempt_nonce == attempt.get("attempt_nonce")
            and bundle_id == attempt.get("descriptor_bundle_id")
            and fd_tokens == bundle_tokens
            and row.get("status") == "current"
        )
        if matches_current:
            current_count += 1
    if current_count != 1:
        _add(blockers, "ATTEMPT_REPLAY",
             "attempt history must contain exactly one current record matching the active bundle")
        valid = False
    return valid


def validate_strict_capability_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate strict bindings without making a formal admission decision."""
    blockers: list[dict[str, str]] = []
    checks = {
        "schema": False,
        "base_contract": False,
        "formal_release": False,
        "session_binding": False,
        "attempt_binding": False,
        "descriptor_bundle": False,
        "replay_guard": False,
    }
    base_report: dict[str, Any] = {}
    if not isinstance(contract, Mapping):
        _add(blockers, "STRICT_CONTRACT_REQUIRED", "strict capability contract must be a JSON object")
        return _result(contract_schema=None, checks=checks, blockers=blockers,
                       base_report=base_report)
    if set(contract) != TOP_LEVEL_FIELDS:
        _add(blockers, "STRICT_CONTRACT_FIELDS",
             "strict capability contract fields must be exact")
    checks["schema"] = contract.get("schema") == STRICT_CONTRACT_SCHEMA
    if not checks["schema"]:
        _add(blockers, "STRICT_CONTRACT_SCHEMA", "unsupported strict capability contract schema")

    base = contract.get("base_contract")
    if isinstance(base, Mapping):
        try:
            base_report = validate_capability_contract(base)
        except (TypeError, ValueError, KeyError, AttributeError):
            base_report = {"capability_contract_valid": False, "blockers": []}
        checks["base_contract"] = (
            base.get("schema") == BASE_CONTRACT_SCHEMA
            and base_report.get("capability_contract_valid") is True
        )
    if not checks["base_contract"]:
        _add(blockers, "BASE_CONTRACT_REQUIRED",
             "strict verifier requires a structurally valid v1 base envelope")

    base_formal = isinstance(base, Mapping) and base.get("formal_release") is True
    checks["formal_release"] = contract.get("formal_release") is True and base_formal
    if not checks["formal_release"]:
        _add(blockers, "FORMAL_RELEASE_REQUIRED",
             "both strict and base formal_release flags must be true; no release means no admission")

    if isinstance(base, Mapping):
        session_ok, session = _validate_session(contract, base, blockers)
    else:
        session_ok, session = False, {}
        _add(blockers, "SESSION_BINDING_REQUIRED", "session cannot bind without a base source envelope")
    checks["session_binding"] = session_ok

    attempt_ok, attempt = _validate_attempt(contract, session, blockers)
    checks["attempt_binding"] = attempt_ok

    if isinstance(base, Mapping) and session_ok and attempt_ok:
        bundle_ok, bundle_tokens = _validate_bundle(
            contract, base, session, attempt, blockers)
    else:
        bundle_ok, bundle_tokens = False, []
        _add(blockers, "DESCRIPTOR_BUNDLE_REQUIRED",
             "descriptor bundle cannot be checked before session and attempt binding pass")
    checks["descriptor_bundle"] = bundle_ok

    if attempt_ok and bundle_ok:
        checks["replay_guard"] = _validate_history(
            contract, session, attempt, bundle_tokens, blockers)
    else:
        _add(blockers, "ATTEMPT_REPLAY",
             "replay guard cannot be checked before the active descriptor bundle passes")

    return _result(contract_schema=contract.get("schema"), checks=checks,
                   blockers=blockers, base_report=base_report)


def _result(*, contract_schema: Any, checks: Mapping[str, bool],
            blockers: list[dict[str, str]], base_report: Mapping[str, Any]) -> dict[str, Any]:
    valid = bool(checks) and all(checks.values()) and not blockers
    return {
        "schema": REPORT_SCHEMA,
        "validator_schema": STRICT_CONTRACT_SCHEMA,
        "base_validator_schema": BASE_CONTRACT_SCHEMA,
        "contract_schema": contract_schema,
        "validation_scope": "synthetic_strict_held_fd_bundle_envelope_only",
        "checks": dict(checks),
        "strict_capability_contract_valid": valid,
        "capability_contract_valid": valid,
        "base_validation": {
            "capability_contract_valid": base_report.get("capability_contract_valid") is True,
            "blockers": list(base_report.get("blockers", []))
            if isinstance(base_report.get("blockers", []), list) else [],
        },
        "authorizes_formal": False,
        "formal_eligible": False,
        "qualification_credit": 0,
        "blockers": blockers,
        "execution_constraints": {
            "read_only": True,
            "opens_source_fd": False,
            "resolves_source_path": False,
            "reopens_by_path": False,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.contract.read_text(encoding="utf-8"))
    report = validate_strict_capability_contract(payload)
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    return 0 if report["strict_capability_contract_valid"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
