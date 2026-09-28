#!/usr/bin/env python3
"""Inventory the still-open F8/R008 target and trusted-runtime blockers.

This is a bounded synthetic-only contract for the current blocker shape.  It
does not consume repository reports, target paths, source trees, build
artifacts, kernel state, runtime state, or production data.  Every claim is
explicitly untrusted and every required item remains open.  The contract is
therefore useful for auditing the missing evidence boundary, but it cannot
promote a pin, authenticate a runtime, or authorize execution.
"""
from __future__ import annotations

import argparse
import copy
import json
from typing import Any, Mapping


SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SCHEMA = "core.cfd.f8.r008.untrusted_pin_blocker_inventory.v1"
REPORT_SCHEMA = "core.cfd.f8.r008.untrusted_pin_blocker_inventory_report.v1"
RECORD_ID = "f8-r008-untrusted-pin-blocker-inventory-v1"
REPORT_RECORD_ID = "f8-r008-untrusted-pin-blocker-inventory-report-v1"
STATUS = "synthetic_only_untrusted_pin_blocker_inventory"
INVENTORY_MODE = "bounded_synthetic_current_blocker_shape"

TARGET_PIN_SPECS = (
    (
        "kernel_release",
        "target_kernel_identity_pin_incomplete",
        "separately authorized target evidence must bind the deployed kernel release",
    ),
    (
        "source_commit",
        "target_source_identity_pin_incomplete",
        "separately authorized target evidence must bind the exact source commit",
    ),
    (
        "source_tree_sha256",
        "target_source_tree_pin_incomplete",
        "separately authorized target evidence must bind the complete source-tree digest",
    ),
    (
        "uapi_sha256",
        "target_uapi_pin_incomplete",
        "separately authorized target evidence must bind the deployed UAPI digest",
    ),
    (
        "config_sha256",
        "target_config_pin_incomplete",
        "separately authorized target evidence must bind the deployed kernel config digest",
    ),
    (
        "build_id",
        "target_build_identity_pin_incomplete",
        "separately authorized target evidence must bind the exact build identity",
    ),
)

TRUSTED_RUNTIME_SPECS = (
    (
        "authority_issuer_identity",
        "trusted_authority_identity_unverified",
        "a separately trusted production root must authenticate the authority issuer",
    ),
    (
        "worker_supervisor_identity",
        "trusted_worker_supervisor_identity_unverified",
        "a trusted supervisor witness must bind the worker identity and execution attempt",
    ),
    (
        "loaded_module_runtime_identity",
        "loaded_runtime_identity_unverified",
        "the loaded runtime/module identity must be measured and bound to the target execution",
    ),
    (
        "source_build_callgraph_conformance",
        "source_build_callgraph_conformance_missing",
        "independently trusted target source/build evidence must prove the required callgraph",
    ),
    (
        "target_abi_conformance",
        "target_abi_conformance_missing",
        "target-kernel ABI evidence must prove the deployed selector and fanotify/FID/PIDFD semantics",
    ),
    (
        "target_kernel_runtime_conformance",
        "target_kernel_runtime_conformance_missing",
        "terminal target-runtime evidence must prove the deployed kernel behavior",
    ),
)

ROW_FIELDS = frozenset(
    {
        "component",
        "field",
        "declared_value",
        "claim_state",
        "claim_origin",
        "trust",
        "external_evidence_present",
        "runtime_verified",
        "closed",
        "blocker_code",
        "required_evidence",
    }
)
AUTHORIZATION = {
    "diagnostic_only": True,
    "readiness_pass": False,
    "T1_numerical": False,
    "qualification_credit": 0,
    "execution_authority": False,
    "formal_admission": False,
    "capability_minted": False,
}
SIDE_EFFECTS = {
    "production_paths_read": False,
    "target_source_read": False,
    "target_build_read": False,
    "kernel_state_read": False,
    "runtime_probe_started": False,
    "privileged_probe_started": False,
    "native_started": False,
    "solver_started": False,
    "worker_started": False,
    "gpu_started": False,
    "queue_started": False,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "gate_mutation": 0,
    "completion_mutation": 0,
}
PROHIBITED_OPERATIONS = [
    "production_source_build_or_kernel_path_read",
    "production_runtime_or_loaded_module_probe",
    "privileged_probe_or_root_escalation",
    "native_or_solver",
    "worker_gpu_or_queue",
    "registry_ledger_gate_completion_mutation",
]


class UntrustedPinBlockerInventoryError(ValueError):
    """The bounded blocker inventory is malformed or attempts promotion."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise UntrustedPinBlockerInventoryError(message)


def _require_exact_keys(value: Any, expected: set[str] | frozenset[str], label: str) -> None:
    _require(isinstance(value, Mapping) and set(value) == set(expected), f"{label} fields differ")


def _row(component: str, field: str, blocker_code: str, required_evidence: str,
         claim_state: str) -> dict[str, Any]:
    return {
        "component": component,
        "field": field,
        "declared_value": None,
        "claim_state": claim_state,
        "claim_origin": "synthetic_fixture",
        "trust": "untrusted",
        "external_evidence_present": False,
        "runtime_verified": False,
        "closed": False,
        "blocker_code": blocker_code,
        "required_evidence": required_evidence,
    }


def _current_rows() -> list[dict[str, Any]]:
    rows = [
        _row("target_kernel_source_build", field, blocker, evidence,
             "missing_external_evidence")
        for field, blocker, evidence in TARGET_PIN_SPECS
    ]
    rows.extend(
        _row("trusted_runtime", field, blocker, evidence, "synthetic_contract_only")
        for field, blocker, evidence in TRUSTED_RUNTIME_SPECS
    )
    return rows


def _blocker_projection(rows: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "component": str(row["component"]),
            "field": str(row["field"]),
            "code": str(row["blocker_code"]),
        }
        for row in rows
    ]


def build_report() -> dict[str, Any]:
    """Build the fixed synthetic current-state inventory."""

    rows = _current_rows()
    target_count = len(TARGET_PIN_SPECS)
    runtime_count = len(TRUSTED_RUNTIME_SPECS)
    return {
        "schema": REPORT_SCHEMA,
        "record_id": REPORT_RECORD_ID,
        "status": STATUS,
        "scope_id": SCOPE_ID,
        "inventory_mode": INVENTORY_MODE,
        "source_and_runtime_claims": {
            "all_claims_untrusted": True,
            "synthetic_fixture_only": True,
            "external_evidence_consumed": False,
            "runtime_evidence_consumed": False,
            "promotion_surface": "none",
        },
        "target_kernel_source_build": {
            "required_fields": [field for field, _blocker, _evidence in TARGET_PIN_SPECS],
            "open_count": target_count,
            "closed_count": 0,
            "rows": rows[:target_count],
        },
        "trusted_runtime": {
            "required_fields": [field for field, _blocker, _evidence in TRUSTED_RUNTIME_SPECS],
            "open_count": runtime_count,
            "closed_count": 0,
            "rows": rows[target_count:],
        },
        "blockers": _blocker_projection(rows),
        "authorization": copy.deepcopy(AUTHORIZATION),
        "side_effects": copy.deepcopy(SIDE_EFFECTS),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "next_step": (
            "collect separately authorized external target pin evidence and trusted runtime "
            "attestations, then re-run a future non-authorizing reconciliation"
        ),
    }


def _validate_row(row: Any, *, component: str, field: str, blocker_code: str,
                  required_evidence: str, claim_state: str) -> None:
    _require_exact_keys(row, ROW_FIELDS, f"{component}.{field} row")
    _require(row["component"] == component, f"{component}.{field} component drift")
    _require(row["field"] == field, f"{component}.{field} field drift")
    _require(row["declared_value"] is None,
             f"{component}.{field} must not carry a declared target value")
    _require(row["claim_state"] == claim_state, f"{component}.{field} claim state drift")
    _require(row["claim_origin"] == "synthetic_fixture",
             f"{component}.{field} claim origin is not synthetic_fixture")
    _require(row["trust"] == "untrusted", f"{component}.{field} trust was promoted")
    _require(row["external_evidence_present"] is False,
             f"{component}.{field} external evidence was promoted")
    _require(row["runtime_verified"] is False,
             f"{component}.{field} runtime verification was promoted")
    _require(row["closed"] is False, f"{component}.{field} was promoted closed")
    _require(row["blocker_code"] == blocker_code, f"{component}.{field} blocker drift")
    _require(row["required_evidence"] == required_evidence,
             f"{component}.{field} required evidence drift")


def validate_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate without allowing any source/runtime claim to gain authority."""

    expected = build_report()
    _require_exact_keys(value, set(expected), "report")
    _require(value["schema"] == REPORT_SCHEMA, "report schema drift")
    _require(value["record_id"] == REPORT_RECORD_ID, "report record_id drift")
    _require(value["status"] == STATUS, "report status drift")
    _require(value["scope_id"] == SCOPE_ID, "report scope drift")
    _require(value["inventory_mode"] == INVENTORY_MODE, "report inventory mode drift")

    claims = value["source_and_runtime_claims"]
    _require_exact_keys(
        claims,
        {"all_claims_untrusted", "synthetic_fixture_only", "external_evidence_consumed",
         "runtime_evidence_consumed", "promotion_surface"},
        "source_and_runtime_claims",
    )
    _require(claims == expected["source_and_runtime_claims"],
             "source/runtime trust boundary was changed")

    target = value["target_kernel_source_build"]
    runtime = value["trusted_runtime"]
    for section, specs, component, claim_state in (
        (target, TARGET_PIN_SPECS, "target_kernel_source_build", "missing_external_evidence"),
        (runtime, TRUSTED_RUNTIME_SPECS, "trusted_runtime", "synthetic_contract_only"),
    ):
        _require_exact_keys(section, {"required_fields", "open_count", "closed_count", "rows"},
                            f"{component} section")
        _require(section["required_fields"] == [field for field, _b, _e in specs],
                 f"{component} required fields drift")
        _require(type(section["open_count"]) is int and section["open_count"] == len(specs),
                 f"{component} open count drift")
        _require(section["closed_count"] == 0, f"{component} closed count was promoted")
        _require(type(section["rows"]) is list and len(section["rows"]) == len(specs),
                 f"{component} row count drift")
        for row, (field, blocker, evidence) in zip(section["rows"], specs, strict=True):
            _validate_row(row, component=component, field=field, blocker_code=blocker,
                          required_evidence=evidence, claim_state=claim_state)

    rows = list(target["rows"]) + list(runtime["rows"])
    _require(value["blockers"] == _blocker_projection(rows), "blocker projection drift")
    _require(value["authorization"] == AUTHORIZATION, "authorization boundary drift")
    _require(value["side_effects"] == SIDE_EFFECTS, "side-effect boundary drift")
    _require(value["prohibited_operations"] == PROHIBITED_OPERATIONS,
             "prohibited operation boundary drift")
    _require(value["next_step"] == expected["next_step"], "next step drift")
    return copy.deepcopy(dict(value))


def verify_report() -> dict[str, Any]:
    """Return the deterministic report after fail-closed validation."""

    report = build_report()
    return validate_report(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="validate and print the report")
    args = parser.parse_args()
    if args.verify:
        report = verify_report()
    else:
        report = build_report()
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
