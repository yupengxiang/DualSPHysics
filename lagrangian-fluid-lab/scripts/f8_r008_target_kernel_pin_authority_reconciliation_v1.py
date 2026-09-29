#!/usr/bin/env python3
"""Reconcile F8/R008 target-pin observations without minting authority.

The existing F8/R008 contracts intentionally keep three evidence surfaces
separate:

* the bounded local-kernel inventory (what this host happened to observe),
* the target-kernel manifest intake (what an external target manifest claims),
* the trusted target-pin intake (what an independently anchored attestation
  verifies).

This additive contract joins those *status surfaces* and reports the missing
value-level reconciliation boundary.  It never opens the target source tree,
kernel image, build artifact, runtime state, production data, or an external
artifact referenced by a report.  A local value, a caller-shaped ``verified``
flag, or a synthetic fixture cannot become trusted target authority.  Even a
future cryptographically verified pin intake remains non-authorizing here until
an independent runtime measurement and the full value projection are bound.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_strict_json import read_bounded_raw_json, strict_json_object


SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SCHEMA = "core.cfd.f8.r008.target_kernel_pin_authority_reconciliation_report.v1"
RECORD_ID = "f8-r008-target-kernel-pin-authority-reconciliation-v1"
STATUS = "diagnostic_only_target_kernel_pin_authority_reconciliation_blocked"
DEFAULT_REPORT = Path(
    "reports/F8-R008-TARGET-KERNEL-PIN-AUTHORITY-RECONCILIATION-V1-2026-09-29.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F8-R008-TARGET-KERNEL-PIN-AUTHORITY-RECONCILIATION-V1-2026-09-29.zh-CN.md"
)

LOCAL_INVENTORY = Path(
    "reports/F8-R008-TARGET-KERNEL-LOCAL-INVENTORY-V1-2026-09-28.json"
)
TARGET_INTAKE = Path("reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json")
TRUSTED_INTAKE = Path("reports/F8-R008-TRUSTED-TARGET-PIN-INTAKE-V1.json")
READINESS_INVENTORY = Path(
    "reports/F8-R008-TARGET-KERNEL-SOURCE-BUILD-RUNTIME-PIN-READINESS-INVENTORY-V1-2026-09-29.json"
)

DEPENDENCIES = {
    "local_inventory": {
        "path": LOCAL_INVENTORY,
        "schema": "core.cfd.f8.r008.target_kernel_local_inventory_report.v1",
        "record_id": "f8-r008-target-kernel-local-inventory-v1",
        "status": "diagnostic_only_local_target_kernel_inventory_incomplete",
    },
    "target_manifest_intake": {
        "path": TARGET_INTAKE,
        "schema": "core.cfd.f8.r008.target_kernel_evidence_intake_report.v1",
        "record_id": "f8-r008-target-kernel-evidence-intake-report-v1",
        "status": "blocked_missing_external_target_evidence",
    },
    "trusted_pin_intake": {
        "path": TRUSTED_INTAKE,
        "schema": "core.cfd.f8.r008.trusted_target_pin_intake_report.v1",
        "record_id": "f8-r008-trusted-target-pin-intake-report-v1",
        "status": "blocked_missing_external_trusted_pin_attestation",
    },
    "readiness_inventory": {
        "path": READINESS_INVENTORY,
        "schema": "core.cfd.f8.r008.target_kernel_source_build_runtime_pin_readiness_inventory.v1",
        "record_id": "f8-r008-target-kernel-source-build-runtime-pin-readiness-inventory-20260929",
        "status": "blocked_missing_external_target_kernel_source_build_runtime_pins",
    },
}

PIN_FIELDS = (
    "kernel_release",
    "source_commit",
    "source_tree_sha256",
    "uapi_sha256",
    "config_sha256",
    "build_id",
)

LOCAL_FIELD_MAP = {
    "kernel_release": ("kernel_release", "release", "full_value"),
    "source_commit": ("source_commit", "value", "full_value"),
    "source_tree_sha256": ("source_tree", "complete_tree_hash", "full_value"),
    "uapi_sha256": ("uapi", "complete_tree_hash", "sample_only"),
    "config_sha256": ("config", "boot_config.sha256", "full_value"),
    "build_id": ("build_id", "value", "full_value"),
}

TARGET_FIELD_MAP = {
    "kernel_release": "kernel_release",
    "source_commit": "source_commit",
    "source_tree_sha256": "source_tree_sha256",
    "uapi_sha256": "uapi_sha256",
    "config_sha256": "config_sha256",
    "build_id": "build_id",
}

TRUSTED_DOMAIN_MAP = {
    "kernel_release": ("target_kernel", "kernel_release"),
    "source_commit": ("source", "source_commit"),
    "source_tree_sha256": ("source", "source_tree_sha256"),
    "uapi_sha256": ("source", "uapi_sha256"),
    "config_sha256": ("build", "config_sha256"),
    "build_id": ("build", "build_id"),
}

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
    "checked_in_report_reads": True,
    "external_pin_inputs_read": False,
    "target_source_read": False,
    "target_build_read": False,
    "kernel_or_runtime_probe": False,
    "privileged_probe": False,
    "production_data_read": False,
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

READ_POLICY = {
    "bounded_checked_in_reports_only": True,
    "local_observation_promoted_to_authority": False,
    "caller_claim_promoted_to_authority": False,
    "external_artifact_reference_followed": False,
    "target_source_or_build_opened": False,
    "kernel_or_runtime_probe": False,
    "production_hdf5_checkpoint_trajectory_opened": False,
    "native_solver_worker_gpu_queue": False,
}

PROHIBITED_OPERATIONS = [
    "target_source_build_kernel_or_runtime_read",
    "external_artifact_reference_follow_or_open",
    "production_hdf5_checkpoint_trajectory_read",
    "privileged_probe_or_fanotify",
    "native_solver_worker_gpu_queue",
    "registry_ledger_denominator_gate_completion_plan_mutation",
]


class ReconciliationError(ValueError):
    """A dependency, fixture, or report attempts to cross the trust boundary."""

    def __init__(self, message: str, *, code: str = "invalid_reconciliation") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, *, code: str = "invalid_reconciliation") -> None:
    raise ReconciliationError(message, code=code)


def _require(condition: bool, message: str, *, code: str = "invalid_reconciliation") -> None:
    if not condition:
        _fail(message, code=code)


def _path(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = LAB_ROOT / candidate
    return candidate


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(LAB_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json(path: str | Path, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    absolute = _path(path)
    try:
        raw = read_bounded_raw_json(absolute, max_bytes=4 * 1024 * 1024, label=label)
        value = strict_json_object(raw, max_bytes=4 * 1024 * 1024, label=label)
    except (OSError, ValueError) as error:
        raise ReconciliationError(f"{label} cannot be read safely: {error}", code="read_error") from error
    return value, {
        "path": _display_path(absolute),
        "exists": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _exact_mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be an object")
    return value


def _validate_dependency(name: str, value: Mapping[str, Any]) -> None:
    spec = DEPENDENCIES[name]
    _require(value.get("schema") == spec["schema"], f"{name} schema drift", code="dependency_identity_drift")
    _require(value.get("record_id") == spec["record_id"], f"{name} record_id drift", code="dependency_identity_drift")
    _require(value.get("status") == spec["status"], f"{name} status drift", code="dependency_state_drift")
    _require(value.get("scope_id", SCOPE_ID) == SCOPE_ID, f"{name} scope drift", code="dependency_scope_drift")
    authorization = value.get("authorization")
    _require(authorization == AUTHORIZATION, f"{name} authorization was promoted", code="authorization_drift")


def _validate_dependencies(values: Mapping[str, Mapping[str, Any]]) -> None:
    for name, value in values.items():
        _validate_dependency(name, value)

    local = values["local_inventory"]
    local_pins = _exact_mapping(local.get("pins"), "local_inventory.pins")
    _require(
        set(local_pins) == {
            "build_id_pinned", "config_pinned", "header_pinned",
            "kernel_release_pinned", "source_commit_pinned", "source_tree_pinned", "uapi_pinned",
        },
        "local inventory pin fields drift",
        code="dependency_shape_drift",
    )
    _require(all(type(item) is bool for item in local_pins.values()), "local inventory pin types drift")
    validation = _exact_mapping(local.get("validation"), "local_inventory.validation")
    _require(validation.get("fail_closed") is True, "local inventory is not fail-closed", code="authorization_drift")
    _require(validation.get("required_pins_complete") is False, "local inventory pins were promoted", code="authorization_drift")

    target = values["target_manifest_intake"]
    target_pins = _exact_mapping(target.get("pins"), "target_manifest_intake.pins")
    _require(set(target_pins) == {
        "build_id_pinned", "config_pinned", "kernel_release_pinned",
        "source_commit_pinned", "source_tree_pinned", "uapi_pinned",
    }, "target intake pin fields drift", code="dependency_shape_drift")
    _require(target_pins == {key: False for key in target_pins}, "target intake pins were promoted", code="authorization_drift")
    target_validation = _exact_mapping(target.get("validation"), "target_manifest_intake.validation")
    _require(target_validation.get("external_target_evidence_complete") is False, "target intake became complete", code="authorization_drift")

    trusted = values["trusted_pin_intake"]
    trusted_pins = _exact_mapping(trusted.get("pins"), "trusted_pin_intake.pins")
    _require(set(trusted_pins) == {"build", "host_identity", "runtime_abi", "source", "target_kernel"},
             "trusted intake pin fields drift", code="dependency_shape_drift")
    _require(trusted_pins == {key: False for key in trusted_pins}, "trusted intake pins were promoted", code="authorization_drift")
    trusted_validation = _exact_mapping(trusted.get("validation"), "trusted_pin_intake.validation")
    _require(trusted_validation.get("cross_bindings_valid") is False, "trusted intake cross-bindings were promoted", code="authorization_drift")
    trusted_identity = _exact_mapping(trusted.get("identity"), "trusted_pin_intake.identity")
    _require(all(trusted_identity.get(key) is None for key in (
        "kernel_release", "build_id", "runtime_abi_sha256", "host_identity_sha256",
        "trust_root_id", "trust_key_id", "pin_set_sha256",
    )), "trusted intake identity was promoted", code="authorization_drift")

    readiness = values["readiness_inventory"]
    readiness_summary = _exact_mapping(readiness.get("pin_inventory"), "readiness_inventory.pin_inventory")
    _require(readiness_summary.get("closed_count") == 0, "readiness inventory pins were promoted", code="authorization_drift")


def _nested(mapping: Mapping[str, Any], dotted: str) -> Any:
    value: Any = mapping
    for part in dotted.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _local_observations(local: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    evidence = _exact_mapping(local.get("evidence"), "local_inventory.evidence")
    output: dict[str, dict[str, Any]] = {}
    for pin, (section, value_path, kind) in LOCAL_FIELD_MAP.items():
        item = _exact_mapping(evidence.get(section), f"local_inventory.evidence.{section}")
        observed = item.get("observed") is True
        proven = item.get("proven") is True
        value = _nested(item, value_path) if observed else None
        if pin == "uapi_sha256":
            # The bounded inventory deliberately has only a fixed sample hash;
            # a sample is not the complete UAPI tree digest required by R008.
            value = None
        if pin == "config_sha256" and value is None and observed:
            value = _nested(item, "boot_config.sha256")
        output[pin] = {
            "observed": observed,
            "locally_proven": proven,
            "trust_class": "local_observation_only",
            "value": value,
            "value_kind": kind,
            "sample_digest": _nested(item, "sample_inventory_sha256") if pin == "uapi_sha256" else None,
        }
    return output


def _target_manifest_projection(target: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    declared = _exact_mapping(target.get("declared_target"), "target_manifest_intake.declared_target")
    pins = _exact_mapping(target.get("pins"), "target_manifest_intake.pins")
    output: dict[str, dict[str, Any]] = {}
    for pin in PIN_FIELDS:
        pin_key = f"{TARGET_FIELD_MAP[pin]}_pinned"
        verified = pins.get(pin_key) is True
        output[pin] = {
            "verified_by_manifest_intake": verified,
            "trust_class": "external_manifest_claim" if verified else "unavailable_external_manifest",
            "value": declared.get(TARGET_FIELD_MAP[pin]) if verified else None,
            "value_exported": verified and declared.get(TARGET_FIELD_MAP[pin]) is not None,
        }
    return output


def _trusted_projection(trusted: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    pins = _exact_mapping(trusted.get("pins"), "trusted_pin_intake.pins")
    identity = _exact_mapping(trusted.get("identity"), "trusted_pin_intake.identity")
    status = trusted.get("status")
    cryptographically_verified = status == "external_trusted_pin_attestation_cryptographically_verified_non_authorizing"
    output: dict[str, dict[str, Any]] = {}
    for pin in PIN_FIELDS:
        domain, field = TRUSTED_DOMAIN_MAP[pin]
        verified = pins.get(domain) is True and cryptographically_verified
        # The current checked-in intake report intentionally exports only a
        # compact identity summary.  Do not invent source/config/UAPI values.
        exported_value = identity.get(field) if field in identity else None
        output[pin] = {
            "verified_by_trusted_intake": verified,
            "trust_class": "trusted_external_attestation" if verified else "unavailable_trusted_authority",
            "value": exported_value if verified else None,
            "value_exported": verified and exported_value is not None,
            "domain": domain,
            "field": field,
        }
    return output


def _state_for_row(local: Mapping[str, Any], target: Mapping[str, Any], trusted: Mapping[str, Any]) -> tuple[str, str]:
    local_observed = local["observed"] is True
    target_verified = target["verified_by_manifest_intake"] is True
    trusted_verified = trusted["verified_by_trusted_intake"] is True
    values = [item.get("value") for item in (target, trusted) if item.get("value_exported") is True]
    if target_verified and trusted_verified:
        if not target.get("value_exported") or not trusted.get("value_exported"):
            return "authority_value_projection_missing", "trusted and manifest status agree, but a full comparable value is not exported"
        if target["value"] != trusted["value"]:
            return "cross_contract_drift_fail_closed", "manifest and trusted authority values differ"
        if local.get("value") is not None and local["value"] != target["value"]:
            return "local_observation_drift_fail_closed", "local observation differs from both external sources"
        return "cross_contract_match_non_authorizing", "external values match; reconciliation never grants runtime authority"
    if target_verified or trusted_verified:
        return "one_external_source_missing", "only one external source is closed; independent cross-contract equality is unavailable"
    if local_observed:
        if local.get("value_kind") == "sample_only":
            return "local_sample_only_not_external_pin", "local sample is not a complete target pin"
        return "local_observation_not_external_pin", "local observation cannot be promoted into a target authority pin"
    return "external_authority_missing", "no external target manifest or trusted authority value is available"


def _build_rows(
    local: Mapping[str, Mapping[str, Any]],
    target: Mapping[str, Mapping[str, Any]],
    trusted: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pin in PIN_FIELDS:
        state, reason = _state_for_row(local[pin], target[pin], trusted[pin])
        rows.append({
            "pin": pin,
            "required": True,
            "local_observed": local[pin]["observed"],
            "local_value_kind": local[pin]["value_kind"],
            "local_value_exported": local[pin]["value"] is not None,
            "manifest_verified": target[pin]["verified_by_manifest_intake"],
            "manifest_value_exported": target[pin]["value_exported"],
            "trusted_authority_verified": trusted[pin]["verified_by_trusted_intake"],
            "trusted_value_exported": trusted[pin]["value_exported"],
            "state": state,
            "reason": reason,
            "accepted_as_authority": False,
        })
    return rows


def _status_counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        state = str(row["state"])
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def build_report() -> dict[str, Any]:
    """Build the deterministic current-state cross-contract reconciliation."""

    values: dict[str, dict[str, Any]] = {}
    references: dict[str, dict[str, Any]] = {}
    for name, spec in DEPENDENCIES.items():
        value, reference = _read_json(spec["path"], label=f"{name} report")
        values[name] = value
        references[name] = {**reference, "role": name}
    _validate_dependencies(values)

    local = _local_observations(values["local_inventory"])
    target = _target_manifest_projection(values["target_manifest_intake"])
    trusted = _trusted_projection(values["trusted_pin_intake"])
    rows = _build_rows(local, target, trusted)

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "scope_id": SCOPE_ID,
        "status": STATUS,
        "contract_role": "value_level_cross_contract_reconciliation_non_authorizing",
        "dependencies": references,
        "authority_separation": {
            "local_observation_is_authority": False,
            "caller_claim_is_authority": False,
            "synthetic_fixture_is_authority": False,
            "manifest_status_alone_is_authority": False,
            "trusted_intake_status_alone_is_runtime_authority": False,
            "full_value_projection_required_for_comparison": True,
            "independent_runtime_measurement_required": True,
            "independent_consume_path_required": True,
        },
        "local_observation": {
            "trust_class": "local_observation_only",
            "promotable": False,
            "fields": local,
        },
        "target_manifest": {
            "trust_class": "external_manifest_intake_status_only",
            "verified_field_count": sum(item["verified_by_manifest_intake"] for item in target.values()),
            "fields": target,
        },
        "trusted_target_authority": {
            "trust_class": "independent_trusted_intake_status_only",
            "verified_field_count": sum(item["verified_by_trusted_intake"] for item in trusted.values()),
            "value_projection_complete": all(item["value_exported"] for item in trusted.values()),
            "fields": trusted,
        },
        "pin_reconciliation": rows,
        "summary": {
            "required_pin_count": len(PIN_FIELDS),
            "cross_contract_match_count": sum(item["state"] == "cross_contract_match_non_authorizing" for item in rows),
            "drift_rejection_count": sum("drift_fail_closed" in item["state"] for item in rows),
            "local_only_count": sum(item["state"].startswith("local_") for item in rows),
            "authority_missing_count": sum(item["state"] == "external_authority_missing" for item in rows),
            "states": _status_counts(rows),
        },
        "blocking_gaps": [
            {
                "code": "trusted_target_pin_attestation_missing",
                "detail": "The current trusted-pin intake has no external attestation or independent trust anchor.",
                "next_artifact": "externally anchored target/source/build/runtime/host pin attestation",
            },
            {
                "code": "target_manifest_external_evidence_missing",
                "detail": "The current target-kernel manifest intake has no verified external manifest or artifact set.",
                "next_artifact": "verified target-kernel manifest with source/UAPI/config/build artifacts",
            },
            {
                "code": "value_level_cross_contract_join_unavailable",
                "detail": "No current report exports a complete, independently trusted value-level join across local observation, target manifest, and trusted authority.",
                "next_artifact": "producer-issued value projection bound to the same external authority and runtime receipt",
            },
            {
                "code": "target_runtime_conformance_missing",
                "detail": "Source/build/runtime pin equality would still not prove loaded target-kernel ABI or runtime conformance.",
                "next_artifact": "independent target-runtime measurement and conformance receipt",
            },
        ],
        "authorization": copy.deepcopy(AUTHORIZATION),
        "side_effects": copy.deepcopy(SIDE_EFFECTS),
        "read_policy": copy.deepcopy(READ_POLICY),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "non_changes": [
            "target source/build/kernel/runtime state",
            "production HDF5/checkpoint/trajectory",
            "registry",
            "ledger",
            "denominator",
            "gate",
            "completion",
            "PLAN.md",
            "historical receipts",
        ],
    }


def _validate_fixture_record(value: Any, label: str, *, local: bool = False) -> Mapping[str, Any]:
    record = _exact_mapping(value, label)
    expected = {"origin", "synthetic", "verified", "values"}
    _require(set(record) == expected, f"{label} fields differ", code="fixture_shape_drift")
    _require(record["synthetic"] is True, f"{label} is not marked synthetic", code="fixture_authority_spoof")
    _require(record["verified"] is False, f"{label} contains a caller-supplied verified claim", code="fixture_authority_spoof")
    expected_origin = "local_observation" if local else "synthetic_fixture"
    _require(record["origin"] == expected_origin, f"{label} origin is not diagnostic-only", code="fixture_authority_spoof")
    values = _exact_mapping(record["values"], f"{label}.values")
    _require(set(values).issubset(PIN_FIELDS), f"{label}.values contains unknown pin", code="fixture_shape_drift")
    for key, item in values.items():
        _require(type(key) is str and (item is None or type(item) is str), f"{label}.values has invalid value")
    return record


def reconcile_synthetic_fixture(
    *,
    local_observation: Mapping[str, Any],
    target_manifest: Mapping[str, Any],
    trusted_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare synthetic values while proving that none can mint authority.

    The fixture API is intentionally stricter than the report API.  It accepts
    only explicitly synthetic, unverified records.  A matching result is useful
    for testing the join logic, but its decision remains non-authorizing; a
    mismatch is an explicit fail-closed rejection.
    """

    local = _validate_fixture_record(local_observation, "local_observation", local=True)
    target = _validate_fixture_record(target_manifest, "target_manifest")
    trusted = _validate_fixture_record(trusted_authority, "trusted_authority")
    rows: list[dict[str, Any]] = []
    for pin in PIN_FIELDS:
        local_value = local["values"].get(pin)
        target_value = target["values"].get(pin)
        trusted_value = trusted["values"].get(pin)
        available = [item for item in (target_value, trusted_value) if item is not None]
        if len(available) == 2 and available[0] != available[1]:
            state = "cross_contract_drift_fail_closed"
            accepted = False
            reason = "synthetic target and authority values differ"
        elif len(available) == 2 and local_value is not None and local_value not in available:
            state = "local_observation_drift_fail_closed"
            accepted = False
            reason = "synthetic local observation differs from both external-shaped values"
        elif len(available) == 2:
            state = "values_match_but_untrusted"
            accepted = False
            reason = "synthetic values match, but no synthetic fixture is authority"
        else:
            state = "comparison_incomplete_fail_closed"
            accepted = False
            reason = "at least two comparable external-shaped values are required"
        rows.append({
            "pin": pin,
            "state": state,
            "accepted_as_authority": accepted,
            "reason": reason,
        })
    return {
        "schema": "core.cfd.f8.r008.target_kernel_pin_authority_reconciliation_fixture_result.v1",
        "synthetic_only": True,
        "authority_minted": False,
        "decision": "reject_drift" if any("drift_fail_closed" in row["state"] for row in rows) else "diagnostic_non_authorizing",
        "rows": rows,
        "authorization": copy.deepcopy(AUTHORIZATION),
    }


def validate_report(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = build_report()
    _require(set(value) == set(expected), "report fields differ", code="report_shape_drift")
    _require(value == expected, "checked-in reconciliation differs from current bounded inputs", code="report_binding_drift")
    _require(value["authorization"] == AUTHORIZATION, "report authorization was promoted", code="authorization_drift")
    _require(value["authority_separation"]["local_observation_is_authority"] is False, "local observation promoted", code="authorization_drift")
    _require(value["authority_separation"]["synthetic_fixture_is_authority"] is False, "synthetic fixture promoted", code="authorization_drift")
    _require(all(row["accepted_as_authority"] is False for row in value["pin_reconciliation"]), "pin row promoted authority", code="authorization_drift")
    _require(value["summary"]["cross_contract_match_count"] == 0, "current report unexpectedly contains a trusted match", code="authorization_drift")
    return dict(value)


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    value, _reference = _read_json(path, label="target-kernel pin authority reconciliation report")
    return validate_report(value)


def _write_json(path: str | Path, value: Mapping[str, Any]) -> Path:
    output = _path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    output.write_bytes(payload)
    return output


def render_zh_report(value: Mapping[str, Any]) -> str:
    states = value["summary"]["states"]
    state_lines = "\n".join(f"- `{key}`：{count}" for key, count in states.items())
    rows = "\n".join(
        f"- `{row['pin']}`：`{row['state']}`；local_observed=`{row['local_observed']}`，"
        f"manifest_verified=`{row['manifest_verified']}`，trusted_authority_verified=`{row['trusted_authority_verified']}`。"
        for row in value["pin_reconciliation"]
    )
    gaps = "\n".join(f"- `{item['code']}`：{item['detail']}" for item in value["blocking_gaps"])
    return f"""# F8/R008 target-kernel pin authority reconciliation V1

状态：`{value['status']}`。本报告是值级跨合同诊断，不是执行准入或资格判定。

## 边界

- local inventory 只表示本机 bounded observation，不能升级为 target authority。
- target manifest intake 与 trusted-pin intake 的 status/field projection 只能在独立来源闭合后比较；caller claim、synthetic fixture 和 local probe 都不能代替 external authority。
- 即使未来值级比较相等，仍需独立 runtime measurement、ABI/source-callgraph conformance 与 consume path；本报告固定 readiness/T1/credit 为 false/0。

## 当前 pin reconciliation

{rows}

状态统计：

{state_lines}

当前 local observation、external target manifest 和 trusted authority 没有形成可认证的完整值级 join；特别是 UAPI 只有 sample，source/build/runtime authority 也没有真实 attestation。

## Blockers

{gaps}

## Side effects / non-authorizing result

- readiness / T1 / formal admission：`false`
- qualification credit：`0`
- 未读取 target source/build/kernel/runtime、production HDF5/checkpoint/trajectory；未启动 native/solver/worker/GPU/queue。
- 未修改 registry、ledger、denominator、gate、completion、PLAN 或历史 receipt。

机器报告：`{DEFAULT_REPORT.as_posix()}`。
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="write JSON and Chinese diagnostic reports")
    group.add_argument("--verify", action="store_true", help="verify the checked-in JSON report")
    args = parser.parse_args(argv)
    if args.verify:
        result = verify_report()
    else:
        result = build_report()
        if args.write:
            _write_json(DEFAULT_REPORT, result)
            _path(DEFAULT_ZH_REPORT).write_text(render_zh_report(result), encoding="utf-8")
    if not args.write:
        print(json.dumps({key: result[key] for key in ("schema", "status", "scope_id", "summary", "authorization")}, indent=2, sort_keys=True))
    else:
        print(DEFAULT_REPORT.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
