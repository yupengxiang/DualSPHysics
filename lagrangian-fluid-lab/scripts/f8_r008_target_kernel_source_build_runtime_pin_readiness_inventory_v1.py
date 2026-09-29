#!/usr/bin/env python3
"""Inventory the current F8/R008 target-pin boundary without execution.

This is a live-contract audit, not a v7/v8 rerun.  It reads only the current
checked-in intake/projection sources, the current R008 scope contract, and the
already checked-in fail-closed intake reports.  It does not read a target
source tree, build artifact, kernel/runtime state, production data, or any
external pin document.  Missing external inputs stay missing and cannot be
promoted to readiness, authority, T1, or credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f8_r008_target_kernel_evidence_intake_v1 as evidence_contract
from scripts import f8_r008_target_kernel_readiness_projection_v1 as projection_contract
from scripts import f8_r008_trusted_target_pin_intake_v1 as trusted_contract


SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
REPORT_SCHEMA = (
    "core.cfd.f8.r008.target_kernel_source_build_runtime_pin_readiness_inventory.v1"
)
REPORT_RECORD_ID = (
    "f8-r008-target-kernel-source-build-runtime-pin-readiness-inventory-20260929"
)
STATUS = "blocked_missing_external_target_kernel_source_build_runtime_pins"
DEFAULT_REPORT = Path(
    "reports/F8-R008-TARGET-KERNEL-SOURCE-BUILD-RUNTIME-PIN-READINESS-INVENTORY-V1-2026-09-29.json"
)

MANIFEST_PATH = evidence_contract.DEFAULT_MANIFEST.as_posix()
ATTESTATION_PATH = trusted_contract.DEFAULT_ATTESTATION.as_posix()
TRUST_ANCHOR_PATH = trusted_contract.DEFAULT_TRUST_ANCHOR.as_posix()
CURRENT_INTAKE_REPORT = evidence_contract.DEFAULT_REPORT.as_posix()
CURRENT_TRUSTED_REPORT = trusted_contract.DEFAULT_REPORT.as_posix()
SCOPE_RECEIPT = (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
    "t1-scope-design-v1/receipt.json"
)

LIVE_CONTRACTS = (
    (
        "scripts/f8_r008_target_kernel_evidence_intake_v1.py",
        "external target-kernel manifest intake source",
    ),
    (
        "scripts/f8_r008_trusted_target_pin_intake_v1.py",
        "trusted target/source/build/runtime pin contract source",
    ),
    (
        "scripts/f8_r008_target_kernel_readiness_projection_v1.py",
        "target-kernel readiness projection source",
    ),
    (SCOPE_RECEIPT, "current R008 target scope contract"),
)

MANIFEST_PIN_FIELDS = (
    "kernel_release",
    "source_commit",
    "source_tree_sha256",
    "uapi_sha256",
    "config_sha256",
    "build_id",
)
TRUSTED_DOMAINS = (
    ("target_kernel", trusted_contract.TARGET_KERNEL_FIELDS),
    ("source", trusted_contract.SOURCE_FIELDS),
    ("build", trusted_contract.BUILD_FIELDS),
    ("runtime_abi", trusted_contract.RUNTIME_ABI_FIELDS),
    ("host_identity", trusted_contract.HOST_FIELDS),
)

AUTHORIZATION = {
    "diagnostic_only": True,
    "capability_minted": False,
    "execution_authority": False,
    "formal_admission": False,
    "readiness_pass": False,
    "T1_numerical": False,
    "qualification_credit": 0,
}
SIDE_EFFECTS = {
    "repository_contract_read": True,
    "checked_in_report_read": True,
    "external_pin_inputs_read": False,
    "target_source_read": False,
    "target_build_read": False,
    "kernel_or_runtime_probe": False,
    "privileged_probe": False,
    "native_started": False,
    "solver_started": False,
    "worker_started": False,
    "gpu_started": False,
    "queue_started": False,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "completion_mutation": 0,
    "plan_mutation": 0,
}
PROHIBITED_OPERATIONS = [
    "target_source_or_build_artifact_read",
    "kernel_or_runtime_state_probe",
    "privileged_or_native_probe",
    "solver_worker_gpu_or_queue_execution",
    "registry_ledger_denominator_gate_completion_mutation",
    "PLAN_or_UPDATE-410_mutation",
    "F3_F4_or_A8_file_touch",
]

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
MAX_FILE_BYTES = 16 * 1024 * 1024


class InventoryError(ValueError):
    """The live-contract inventory cannot be established safely."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryError(message)


def _relative_path(value: str | Path) -> tuple[Path, str]:
    raw = value.as_posix() if isinstance(value, Path) else value
    path = Path(raw)
    _require(
        not path.is_absolute()
        and path.as_posix() == raw
        and path.parts
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"non-canonical repository path: {raw}",
    )
    return LAB_ROOT / path, path.as_posix()


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _missing_reference(relative: str, error: str = "missing") -> dict[str, Any]:
    return {
        "path": relative,
        "exists": False,
        "regular": False,
        "bytes": None,
        "sha256": None,
        "error": error,
    }


def _capture(value: str | Path, *, required: bool) -> tuple[bytes | None, dict[str, Any]]:
    absolute, relative = _relative_path(value)
    parts = absolute.relative_to(LAB_ROOT).parts
    opened: list[int] = []
    try:
        _require(O_DIRECTORY != 0, "directory no-follow support is unavailable")
        parent_fd = os.open(
            LAB_ROOT,
            os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
        )
        opened.append(parent_fd)
        for component in parts[:-1]:
            parent_fd = os.open(
                component,
                os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC,
                dir_fd=parent_fd,
            )
            opened.append(parent_fd)
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC,
            dir_fd=parent_fd,
        )
        opened.append(descriptor)
    except FileNotFoundError:
        if required:
            raise InventoryError(f"required live-contract file is missing: {relative}")
        return None, _missing_reference(relative)
    except OSError as error:
        if required:
            raise InventoryError(f"cannot safely open live-contract file: {relative}") from error
        return None, _missing_reference(relative, "present but not safely readable")

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise InventoryError(f"live-contract file is not a single-link regular file: {relative}")
        if before.st_size > MAX_FILE_BYTES:
            raise InventoryError(f"live-contract file exceeds bounded size: {relative}")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, MAX_FILE_BYTES + 1 - total))
            if not block:
                break
            total += len(block)
            if total > MAX_FILE_BYTES:
                raise InventoryError(f"live-contract file exceeds bounded size: {relative}")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        _require(
            _identity(before) == _identity(after) == _identity(named)
            and total == before.st_size,
            f"live-contract file changed while being read: {relative}",
        )
        raw = b"".join(chunks)
        return raw, {
            "path": relative,
            "exists": True,
            "regular": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "error": None,
        }
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise InventoryError(f"non-standard JSON constant: {value}")


def _read_json(relative: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = _capture(relative, required=True)
    assert raw is not None
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InventoryError(f"invalid strict JSON: {relative}") from error
    _require(isinstance(value, dict), f"JSON contract must be an object: {relative}")
    return value, reference


def _report_reference(relative: str) -> dict[str, Any]:
    _raw, reference = _capture(relative, required=True)
    return reference


def _expected_authorization() -> dict[str, Any]:
    return dict(AUTHORIZATION)


def _validate_current_reports(
    intake: Mapping[str, Any], trusted: Mapping[str, Any]
) -> None:
    _require(
        intake.get("schema") == evidence_contract.REPORT_SCHEMA
        and intake.get("record_id") == evidence_contract.REPORT_RECORD_ID,
        "current target-kernel intake report identity drift",
    )
    _require(intake.get("status") == evidence_contract.STATUS_BLOCKED_MISSING,
             "current target-kernel intake is no longer the expected missing-input state")
    _require(
        intake.get("manifest", {}).get("path") == MANIFEST_PATH
        and intake.get("manifest", {}).get("exists") is False,
        "current target-kernel intake manifest reference drift",
    )
    _require(
        intake.get("pins") == {field: False for field in sorted(evidence_contract.PIN_FIELDS)},
        "current target-kernel intake contains promoted pins",
    )
    _require(
        intake.get("validation", {}).get("external_target_evidence_complete") is False
        and intake.get("validation", {}).get("manifest_present") is False
        and intake.get("validation", {}).get("manifest_valid") is False,
        "current target-kernel intake validation is not fail-closed",
    )
    _require(intake.get("authorization") == _expected_authorization(),
             "current target-kernel intake authorization drift")

    _require(
        trusted.get("schema") == trusted_contract.REPORT_SCHEMA
        and trusted.get("record_id") == trusted_contract.REPORT_RECORD_ID,
        "current trusted pin intake report identity drift",
    )
    _require(trusted.get("status") == trusted_contract.STATUS_BLOCKED_MISSING,
             "current trusted pin intake is no longer the expected missing-input state")
    inputs = trusted.get("inputs", {})
    _require(
        inputs.get("attestation", {}).get("path") == ATTESTATION_PATH
        and inputs.get("attestation", {}).get("exists") is False
        and inputs.get("trust_anchor", {}).get("path") == TRUST_ANCHOR_PATH
        and inputs.get("trust_anchor", {}).get("exists") is False,
        "current trusted pin input references drift",
    )
    _require(
        trusted.get("pins") == {name: False for name in trusted_contract.PIN_NAMES},
        "current trusted pin intake contains promoted pins",
    )
    validation = trusted.get("validation", {})
    _require(
        all(validation.get(field) is False for field in (
            "attestation_present",
            "trust_anchor_present",
            "schema_valid",
            "cross_bindings_valid",
            "target_kernel_pin_complete",
            "source_pin_complete",
            "build_pin_complete",
            "runtime_abi_pin_complete",
            "host_identity_bound",
        )),
        "current trusted pin intake validation is not fail-closed",
    )
    _require(trusted.get("authorization") == _expected_authorization(),
             "current trusted pin intake authorization drift")


def _target_rows() -> list[dict[str, Any]]:
    return [
        {
            "component": "target_kernel_manifest",
            "field": field,
            "contract": f"manifest.target.{field}",
            "state": "missing_external_evidence",
            "current_value": None,
            "evidence_path": MANIFEST_PATH,
            "evidence_present": False,
            "runtime_verified": False,
            "closed": False,
            "blocker_code": "external_target_kernel_manifest_missing",
            "required_evidence": "external manifest target pin plus verified artifact set",
        }
        for field in MANIFEST_PIN_FIELDS
    ]


def _trusted_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for domain, fields in TRUSTED_DOMAINS:
        for field in sorted(fields):
            rows.append(
                {
                    "component": domain,
                    "field": field,
                    "contract": f"attestation.{domain}.{field}",
                    "state": "missing_external_evidence",
                    "current_value": None,
                    "evidence_path": ATTESTATION_PATH,
                    "evidence_present": False,
                    "runtime_verified": False,
                    "closed": False,
                    "blocker_code": "external_trusted_pin_attestation_missing",
                    "required_evidence": "externally signed attestation cross-bound to an independent trust anchor",
                }
            )
    return rows


def _pin_inventory() -> list[dict[str, Any]]:
    return _target_rows() + _trusted_rows()


def _scope_projection(scope: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "reference": dict(reference),
        "schema": scope.get("schema"),
        "record_id": scope.get("record_id"),
        "scope_id": scope.get("scope_id"),
        "status": scope.get("status"),
        "target_pin_fields_present": any(
            key in scope for key in (
                "kernel_release", "source_commit", "source_tree_sha256",
                "uapi_sha256", "config_sha256", "build_id",
            )
        ),
    }


def build_report() -> dict[str, Any]:
    """Build the deterministic current live-contract inventory."""

    contract_refs = []
    for path, role in LIVE_CONTRACTS:
        reference = _report_reference(path)
        contract_refs.append({**reference, "role": role})

    intake, intake_reference = _read_json(CURRENT_INTAKE_REPORT)
    trusted, trusted_reference = _read_json(CURRENT_TRUSTED_REPORT)
    _validate_current_reports(intake, trusted)
    scope, scope_reference = _read_json(SCOPE_RECEIPT)
    _require(scope.get("scope_id") == SCOPE_ID, "current R008 scope contract identity drift")

    manifest_raw, manifest_reference = _capture(MANIFEST_PATH, required=False)
    attestation_raw, attestation_reference = _capture(ATTESTATION_PATH, required=False)
    anchor_raw, anchor_reference = _capture(TRUST_ANCHOR_PATH, required=False)
    _require(manifest_raw is None and attestation_raw is None and anchor_raw is None,
             "external pin inputs are no longer absent; create a fresh inventory")

    rows = _pin_inventory()
    summary = {
        "target_kernel_manifest": {"open_count": len(_target_rows()), "closed_count": 0},
        "trusted_target_kernel_source_build_runtime_host": {
            "open_count": len(_trusted_rows()),
            "closed_count": 0,
        },
    }
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "scope_id": SCOPE_ID,
        "status": STATUS,
        "audit_mode": "live_repository_contract_only_no_v7_v8_revalidation",
        "historical_revalidation": {
            "v7_revalidated": False,
            "v8_revalidated": False,
            "reason": "only current live source, manifest boundary, and target contract were inspected",
        },
        "live_contracts": contract_refs,
        "target_contract": {
            "scope": _scope_projection(scope, scope_reference),
            "manifest_schema": evidence_contract.MANIFEST_SCHEMA,
            "manifest_record_id": evidence_contract.MANIFEST_RECORD_ID,
            "manifest_target_fields": sorted(evidence_contract.TARGET_FIELDS),
            "manifest_artifact_roles": list(evidence_contract.ARTIFACT_ROLES),
            "trusted_attestation_schema": trusted_contract.SCHEMA,
            "trusted_attestation_record_id": trusted_contract.RECORD_ID,
            "trusted_domains": {
                domain: sorted(fields) for domain, fields in TRUSTED_DOMAINS
            },
            "projection_pin_fields": sorted(projection_contract.PIN_FIELDS),
            "required_cross_bindings": [
                "target source_commit/source_tree_sha256/uapi must bind source evidence",
                "target/build/runtime arch, config_sha256, build_id, and kernel image must agree",
                "runtime kernel release/ABI and host identity must bind the target execution",
                "one-shot receipt must bind the complete pin set and independent trust root",
            ],
        },
        "external_inputs": {
            "target_kernel_manifest": {
                **manifest_reference,
                "expected_schema": evidence_contract.MANIFEST_SCHEMA,
                "expected_record_id": evidence_contract.MANIFEST_RECORD_ID,
                "required_target_pin_fields": list(MANIFEST_PIN_FIELDS),
                "required_artifact_roles": list(evidence_contract.ARTIFACT_ROLES),
            },
            "trusted_pin_attestation": {
                **attestation_reference,
                "expected_schema": trusted_contract.SCHEMA,
                "expected_record_id": trusted_contract.RECORD_ID,
                "required_domains": [domain for domain, _fields in TRUSTED_DOMAINS],
            },
            "independent_trust_anchor": {
                **anchor_reference,
                "expected_schema": trusted_contract.ANCHOR_SCHEMA,
                "expected_record_id": trusted_contract.ANCHOR_RECORD_ID,
                "out_of_band_public_key_required": True,
            },
        },
        "observed_current_intake": {
            "target_kernel_evidence_intake": {
                "reference": dict(intake_reference),
                "status": intake["status"],
                "manifest": dict(intake["manifest"]),
                "pins": dict(intake["pins"]),
                "validation": {
                    key: intake["validation"][key]
                    for key in (
                        "manifest_present",
                        "manifest_valid",
                        "external_target_evidence_complete",
                        "blockers",
                    )
                },
            },
            "trusted_target_pin_intake": {
                "reference": dict(trusted_reference),
                "status": trusted["status"],
                "inputs": dict(trusted["inputs"]),
                "pins": dict(trusted["pins"]),
                "validation": {
                    key: trusted["validation"][key]
                    for key in (
                        "attestation_present",
                        "trust_anchor_present",
                        "schema_valid",
                        "cross_bindings_valid",
                        "target_kernel_pin_complete",
                        "source_pin_complete",
                        "build_pin_complete",
                        "runtime_abi_pin_complete",
                        "host_identity_bound",
                        "blockers",
                    )
                },
            },
        },
        "pin_inventory": {
            "summary": summary,
            "open_count": len(rows),
            "closed_count": 0,
            "rows": rows,
        },
        "blocking_gaps": [
            {
                "code": "external_target_kernel_manifest_missing",
                "path": MANIFEST_PATH,
                "detail": "No external manifest supplies target release/source/UAPI/config/build pins or artifact references.",
            },
            {
                "code": "external_target_artifact_set_unresolvable",
                "path": MANIFEST_PATH,
                "detail": "Source/UAPI/config/build artifacts cannot be resolved until the external manifest is supplied and verified.",
            },
            {
                "code": "external_trusted_pin_attestation_missing",
                "path": ATTESTATION_PATH,
                "detail": "No signed target-kernel/source/build/runtime/host pin attestation is present.",
            },
            {
                "code": "independent_trust_anchor_missing",
                "path": TRUST_ANCHOR_PATH,
                "detail": "No independent trust-anchor document or out-of-band public key is present.",
            },
            {
                "code": "target_kernel_source_build_runtime_pin_set_open",
                "path": "current live target contract",
                "detail": "All 51 field-level pin rows remain open; no target identity can be promoted.",
            },
        ],
        "minimal_unit": {
            "candidate": "F8/R008 external target-pin intake",
            "can_advance": False,
            "reason_code": "blocked_missing_external_target_pins",
            "required_next_inputs": [
                "external target-kernel evidence manifest with six target pin fields and four distinct artifact references",
                "verified source/UAPI/config/build artifact bytes matching the manifest",
                "externally signed trusted attestation covering target_kernel, source, build, runtime_abi, and host_identity",
                "independent trust-anchor document plus explicit out-of-band public-key binding",
            ],
            "execution_allowed": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        },
        "authorization": dict(AUTHORIZATION),
        "side_effects": dict(SIDE_EFFECTS),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "non_changes": [
            "registry",
            "ledger",
            "denominator",
            "gate",
            "completion",
            "PLAN.md",
            "UPDATE-410",
            "F3 files",
            "F4 files",
            "A8 files",
        ],
    }


def validate_report(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = build_report()
    _require(dict(value) == expected, "readiness inventory differs from current live-contract state")
    return dict(value)


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(LAB_ROOT).as_posix()
        except ValueError as error:
            raise InventoryError("report path is outside the lab root") from error
    else:
        relative = candidate.as_posix()
    value, _reference = _read_json(relative)
    return validate_report(value)


def _write_new_report(path: Path, value: Mapping[str, Any]) -> None:
    absolute, _relative = _relative_path(path)
    absolute.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    with absolute.open("xb") as handle:
        handle.write(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verify", action="store_true", help="verify the checked-in report")
    group.add_argument("--write", action="store_true", help="create the report once")
    group.add_argument("--emit-json", action="store_true", help="emit the full deterministic report")
    args = parser.parse_args()
    if args.verify:
        result = verify_report()
    else:
        result = build_report()
        if args.write:
            _write_new_report(DEFAULT_REPORT, result)
    if args.emit_json or not args.write:
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    else:
        print(DEFAULT_REPORT.as_posix())
