#!/usr/bin/env python3
"""Locate and reconcile bounded F8/R008 target-kernel evidence.

This module joins the existing target-kernel intake, local inventory, target
readiness projection, readiness-v8 receipt, trusted identity/handoff reports,
and admission bridge.  It does not search arbitrary files and it never
follows an external artifact reference.  The checked-in reports are the only
external-evidence inputs consumed here; local ``/boot``/matching-header
observations are reported as local-only candidates and can never become
external target pins.

The output is a locator/reconciliation view, not an execution gate.  A future
target-kernel intake report that has verified all four external artifacts and
all six identity pins closes the external-artifact binding in this report,
but target ABI, source-callgraph, loaded-runtime, trusted-authority, and
runtime-conformance blockers remain independently fail-closed.
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
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))


SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
SCHEMA = "core.cfd.f8.r008.target_kernel_evidence_locator_reconciliation_report.v1"
RECORD_ID = "f8-r008-target-kernel-evidence-locator-reconciliation-v1"
STATUS = "diagnostic_only_target_kernel_locator_reconciliation_blocked"

DEFAULT_REPORT = Path(
    "reports/F8-R008-TARGET-KERNEL-EVIDENCE-LOCATOR-RECONCILIATION-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F8-R008-TARGET-KERNEL-EVIDENCE-LOCATOR-RECONCILIATION-V1-2026-09-28.zh-CN.md"
)

MAX_JSON_BYTES = 4 * 1024 * 1024
SHA256_HEX = frozenset("0123456789abcdef")

DEPENDENCY_SPECS: dict[str, dict[str, Any]] = {
    "admission_bridge": {
        "path": "reports/F8-R008-ADMISSION-VERIFICATION-BRIDGE-V1-2026-09-28.json",
        "schema": "core.cfd.f8.r008_admission_verification_bridge_report.v1",
        "record_id": "f8-r008-admission-verification-bridge-report-v1",
        "statuses": {"diagnostic_only_admission_verification_blocked"},
        "scope": "required",
    },
    "target_kernel_evidence_intake": {
        "path": "reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json",
        "schema": "core.cfd.f8.r008.target_kernel_evidence_intake_report.v1",
        "record_id": "f8-r008-target-kernel-evidence-intake-report-v1",
        "statuses": {
            "blocked_missing_external_target_evidence",
            "blocked_invalid_external_target_evidence",
            "external_target_evidence_intake_valid_non_authorizing",
        },
        "scope": "absent",
    },
    "target_kernel_local_inventory": {
        "path": "reports/F8-R008-TARGET-KERNEL-LOCAL-INVENTORY-V1-2026-09-28.json",
        "schema": "core.cfd.f8.r008.target_kernel_local_inventory_report.v1",
        "record_id": "f8-r008-target-kernel-local-inventory-v1",
        "statuses": {"diagnostic_only_local_target_kernel_inventory_incomplete"},
        "scope": "required",
    },
    "target_kernel_readiness_projection": {
        "path": "reports/F8-R008-TARGET-KERNEL-READINESS-PROJECTION-V1-2026-09-28.json",
        "schema": "core.cfd.f8.r008.target_kernel_readiness_projection_report.v1",
        "record_id": "f8-r008-target-kernel-readiness-projection-v1",
        "statuses": {"diagnostic_only_target_kernel_readiness_blocked"},
        "scope": "required",
    },
    "readiness_v8": {
        "path": (
            "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/"
            "t1-execution-readiness-audit-v8/receipt.json"
        ),
        "schema": "core.cfd.f8.r008_execution_readiness_audit.v8",
        "record_id": "f8-r008-execution-readiness-audit-v8",
        "statuses": {"static_selector_domain_bound_full_runtime_readiness_blocked"},
        "scope": "required",
    },
    "trusted_identity": {
        "path": "reports/F8-R008-TRUSTED-AUTHORITY-WORKER-RUNTIME-IDENTITY-CONTRACT-V1.json",
        "schema": "core.cfd.f8.r008_trusted_identity_contract_report.v1",
        "record_id": "f8-r008-trusted-identity-contract-report-v1",
        "statuses": {"synthetic_only_non_authorizing_contract_design"},
        "scope": "required",
    },
    "trusted_handoff": {
        "path": "reports/F8-R008-TRUSTED-WORKER-RUNTIME-HANDOFF-CONTRACT-V1.json",
        "schema": "core.cfd.f8.r008_trusted_worker_runtime_handoff_report.v1",
        "record_id": "f8-r008-trusted-worker-runtime-handoff-report-v1",
        "statuses": {"synthetic_only_non_authorizing_handoff_contract_design"},
        "scope": "required",
    },
}

PIN_FIELDS = (
    "kernel_release",
    "source_commit",
    "source_tree",
    "uapi",
    "config",
    "build_id",
)
PIN_REPORT_FIELDS = {
    "kernel_release": "kernel_release_pinned",
    "source_commit": "source_commit_pinned",
    "source_tree": "source_tree_pinned",
    "uapi": "uapi_pinned",
    "config": "config_pinned",
    "build_id": "build_id_pinned",
}
PIN_TARGET_FIELDS = {
    "kernel_release": "kernel_release",
    "source_commit": "source_commit",
    "source_tree": "source_tree_sha256",
    "uapi": "uapi_sha256",
    "config": "config_sha256",
    "build_id": "build_id",
}
ARTIFACT_TARGET_FIELDS = {
    "source": "source_tree_sha256",
    "uapi": "uapi_sha256",
    "config": "config_sha256",
}
PIN_BLOCKERS = {
    "kernel_release": "external_kernel_release_pin_missing",
    "source_commit": "external_source_commit_pin_missing",
    "source_tree": "external_source_tree_hash_missing",
    "uapi": "external_complete_uapi_hash_missing",
    "config": "external_config_hash_missing",
    "build_id": "external_build_identity_missing",
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

MUTATIONS = {
    "completion_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "ledger_mutation": 0,
    "plan_mutation": 0,
    "registry_mutation": 0,
}

SIDE_EFFECTS = {
    "completion_mutation": 0,
    "gate_mutation": 0,
    "gpu_started": False,
    "kernel_started": False,
    "ledger_mutation": 0,
    "native_started": False,
    "plan_mutation": 0,
    "privileged_probe_started": False,
    "queue_started": False,
    "registry_mutation": 0,
    "solver_started": False,
    "system_write": 0,
    "worker_started": False,
}

READ_POLICY = {
    "bounded_existing_report_reads_only": True,
    "local_boot_config_or_matching_header_observation": True,
    "external_artifact_reference_followed": False,
    "kernel_image": False,
    "procfs_or_sysfs": False,
    "production_bi4_hdf5_or_solver_frame": False,
    "privileged_probe_or_fanotify": False,
    "native_solver_worker_gpu_queue": False,
    "registry_ledger_gate_completion_plan_write": False,
}

PROHIBITED_OPERATIONS = [
    "external_artifact_reference_follow_or_open",
    "kernel_image_read",
    "procfs_or_sysfs_read",
    "production_bi4_hdf5_or_solver_frame_read",
    "privileged_probe_or_fanotify",
    "native_solver_worker_gpu_queue",
    "registry_ledger_gate_completion_plan_write",
]


class LocatorReconciliationError(ValueError):
    """A bounded dependency or reconciliation input is inconsistent."""

    def __init__(self, message: str, *, code: str = "invalid_locator_input") -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, *, code: str = "invalid_locator_input") -> None:
    raise LocatorReconciliationError(message, code=code)


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _canonical_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        if path.as_posix() != str(path) or not path.parts or any(
            part in {"", ".", ".."} for part in path.parts
        ):
            _fail(f"dependency path is not canonical: {value}", code="path_traversal")
        path = LAB_ROOT / path
    elif path.as_posix() != str(path) or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        _fail(f"dependency path is not canonical: {value}", code="path_traversal")
    return path


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(LAB_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            _fail(f"could not inspect dependency path: {path}", code="path_inspection")
            raise AssertionError from error
        if stat.S_ISLNK(info.st_mode):
            _fail(f"dependency path contains a symlink: {path}", code="symlink_path")


def _read_bounded(path: str | Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    target = _canonical_path(path)
    _assert_no_symlink_components(target)
    descriptor: int | None = None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(os.fspath(target), flags)
    except FileNotFoundError as error:
        _fail(f"{label} is missing: {_display_path(target)}", code="missing_input")
        raise AssertionError from error
    except OSError as error:
        _fail(f"{label} cannot be opened safely: {_display_path(target)}", code="unsafe_input")
        raise AssertionError from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail(f"{label} must be a single-link regular file", code="unsafe_input")
        if before.st_size <= 0 or before.st_size > MAX_JSON_BYTES:
            _fail(f"{label} exceeds the bounded read limit", code="oversize")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                _fail(f"{label} was truncated while being read", code="input_drift")
            chunks.append(block)
            remaining -= len(block)
        if os.read(descriptor, 1) != b"":
            _fail(f"{label} grew while being read", code="input_drift")
        after = os.fstat(descriptor)
        named = os.stat(target, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named):
            _fail(f"{label} changed while being read", code="input_drift")
        raw = b"".join(chunks)
    except LocatorReconciliationError:
        raise
    except OSError as error:
        _fail(f"{label} could not be read safely", code="read_error")
        raise AssertionError from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return raw, {
        "path": _display_path(target),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}", code="duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    _fail(f"non-standard JSON constant is not permitted: {token}", code="non_strict_json")


def _read_json(path: str | Path, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = _read_bounded(path, label=label)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except LocatorReconciliationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not strict UTF-8 JSON", code="invalid_json")
        raise AssertionError from error
    if type(value) is not dict:
        _fail(f"{label} must be a JSON object", code="json_not_object")
    return value, reference


def _sha256(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in SHA256_HEX for char in value):
        _fail(f"{label} is not lowercase SHA-256", code="digest_format")
    return value


def _require(condition: bool, message: str, *, code: str = "invalid_locator_input") -> None:
    if not condition:
        _fail(message, code=code)


def _dependency_ref(
    value: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "path": reference["path"],
        "bytes": reference["bytes"],
        "sha256": reference["sha256"],
        "schema": value["schema"],
        "record_id": value["record_id"],
        "scope_id": value.get("scope_id"),
        "status": value.get("status"),
    }


def _validate_zero_authority(value: Mapping[str, Any], key: str) -> None:
    for field in ("readiness_pass", "T1_numerical", "full_t1_decision"):
        if field in value:
            _require(value[field] is False, f"{key} promoted {field}", code="authorization_drift")
    if "qualification_credit" in value:
        _require(value["qualification_credit"] == 0, f"{key} promoted qualification credit", code="authorization_drift")
    for container_name in ("authorization", "non_authorizing_boundary"):
        container = value.get(container_name)
        if not isinstance(container, dict):
            continue
        for field, expected in AUTHORIZATION.items():
            if field in container:
                _require(container[field] == expected, f"{key} promoted {container_name}.{field}", code="authorization_drift")
        for field in ("completion_mutation", "denominator_mutation", "gate_mutation", "ledger_mutation", "plan_mutation", "registry_mutation"):
            if field in container:
                _require(container[field] == 0, f"{key} mutated {container_name}.{field}", code="side_effect_drift")
    for container_name in ("side_effects", "mutations", "execution_authority", "execution_controls"):
        container = value.get(container_name)
        if not isinstance(container, dict):
            continue
        for field, observed in container.items():
            if isinstance(observed, bool):
                _require(observed is False, f"{key} has active {container_name}.{field}", code="side_effect_drift")
            elif type(observed) is int:
                _require(observed == 0, f"{key} has non-zero {container_name}.{field}", code="side_effect_drift")


def _validate_dependency_identity(
    key: str,
    value: dict[str, Any],
    spec: Mapping[str, Any],
) -> None:
    _require(value.get("schema") == spec["schema"], f"{key} schema drift", code="schema_drift")
    _require(value.get("record_id") == spec["record_id"], f"{key} record_id drift", code="schema_drift")
    _require(value.get("status") in spec["statuses"], f"{key} status drift", code="status_drift")
    if spec["scope"] == "required":
        _require(value.get("scope_id") == SCOPE_ID, f"{key} scope drift", code="scope_drift")
    else:
        _require("scope_id" not in value, f"{key} unexpectedly has a scope_id", code="scope_drift")
    _validate_zero_authority(value, key)


def _validate_target_intake(value: dict[str, Any]) -> dict[str, Any]:
    validation = value.get("validation")
    pins = value.get("pins")
    target = value.get("declared_target")
    artifacts = value.get("artifacts")
    manifest = value.get("manifest")
    _require(isinstance(validation, dict), "target intake validation is missing")
    _require(isinstance(pins, dict) and set(pins) == {
        "build_id_pinned", "config_pinned", "kernel_release_pinned",
        "source_commit_pinned", "source_tree_pinned", "uapi_pinned",
    }, "target intake pin set differs")
    _require(all(type(item) is bool for item in pins.values()), "target intake pins are malformed")
    _require(isinstance(target, dict), "target intake declared_target is missing")
    _require(set(target) == {
        "kernel_release", "source_commit", "source_tree_sha256", "uapi_sha256",
        "build_id", "config_sha256", "required_options",
    }, "target intake declared_target fields differ")
    _require(isinstance(artifacts, dict) and set(artifacts) == {"source", "uapi", "config", "build"}, "target intake artifacts differ")
    _require(isinstance(manifest, dict), "target intake manifest is missing")
    _require(set(manifest) == {"path", "exists", "bytes", "sha256"}, "target intake manifest fields differ")
    _require(type(manifest.get("exists")) is bool, "target intake manifest.exists is malformed")
    for field in ("manifest_present", "manifest_valid", "artifact_files_verified", "external_target_evidence_complete"):
        _require(type(validation.get(field)) is bool, f"target intake validation.{field} is malformed")
    _require(validation["manifest_present"] == manifest["exists"],
             "target intake manifest presence is not bound to its reference", code="pin_drift")
    for pin_name, target_field in PIN_TARGET_FIELDS.items():
        if pins[PIN_REPORT_FIELDS[pin_name]]:
            _require(target.get(target_field) is not None,
                     f"target intake {pin_name} pin is true without {target_field}",
                     code="pin_drift")
    for role, item in artifacts.items():
        _require(isinstance(item, dict), f"target intake artifact {role} is malformed")
        _require(type(item.get("verified")) is bool, f"target intake artifact {role}.verified is malformed")
        if item["verified"]:
            _require(type(item.get("path")) is str and item["path"], f"target intake artifact {role}.path is missing")
            _require(type(item.get("declared_bytes")) is int and item["declared_bytes"] > 0, f"target intake artifact {role}.bytes is malformed")
            _require(item.get("observed_bytes") == item["declared_bytes"], f"target intake artifact {role}.bytes drift")
            _sha256(item.get("declared_sha256"), f"target intake artifact {role}.declared_sha256")
            _sha256(item.get("observed_sha256"), f"target intake artifact {role}.observed_sha256")
            _require(item["declared_sha256"] == item["observed_sha256"], f"target intake artifact {role}.sha256 drift")
        else:
            _require(all(item.get(field) is None for field in (
                "path", "declared_bytes", "declared_sha256", "observed_bytes", "observed_sha256",
            )), f"target intake artifact {role} contains partial evidence")
    complete = (
        value["status"] == "external_target_evidence_intake_valid_non_authorizing"
        and validation["manifest_present"]
        and validation["manifest_valid"]
        and validation["artifact_files_verified"]
        and validation["external_target_evidence_complete"]
        and all(pins.values())
    )
    _require(
        validation["external_target_evidence_complete"] == complete,
        "target intake completeness flag is not bound to status, validation, and pins",
        code="pin_drift",
    )
    if all(pins.values()) and not complete:
        _require(False, "target intake all pin flags are true without complete external evidence", code="pin_drift")
    if complete:
        _require(not validation.get("blockers"),
                 "complete target intake retains blockers", code="pin_drift")
        for role in ("source", "uapi", "config", "build"):
            _require(artifacts[role]["verified"],
                     f"complete target intake artifact {role} is not verified", code="pin_drift")
        for role, target_field in ARTIFACT_TARGET_FIELDS.items():
            _require(
                target[target_field] == artifacts[role]["observed_sha256"],
                f"complete target intake artifact {role} is not bound to {target_field}",
                code="pin_drift",
            )
    return {
        "complete": complete,
        "manifest": manifest,
        "pins": {field: bool(value) for field, value in pins.items()},
        "target": target,
        "artifacts": artifacts,
        "blockers": list(validation.get("blockers", [])),
    }


def _validate_local_inventory(value: dict[str, Any]) -> dict[str, Any]:
    validation = value.get("validation")
    pins = value.get("pins")
    evidence = value.get("evidence")
    paths = value.get("paths")
    _require(isinstance(validation, dict), "local inventory validation is missing")
    _require(validation.get("fail_closed") is True, "local inventory is not fail-closed")
    _require(validation.get("required_pins_complete") is False, "local inventory promoted complete pins", code="authorization_drift")
    _require(validation.get("source_commit_proven") is False and validation.get("source_tree_proven") is False and validation.get("build_id_proven") is False, "local inventory promoted source/build identity", code="authorization_drift")
    _require(isinstance(pins, dict) and isinstance(evidence, dict) and isinstance(paths, dict), "local inventory sections are incomplete")
    for name in ("build_id", "source_commit", "source_tree"):
        _require(isinstance(evidence.get(name), dict) and evidence[name].get("proven") is False, f"local inventory promoted {name}", code="authorization_drift")
    return {"validation": validation, "pins": pins, "evidence": evidence, "paths": paths}


def _validate_readiness_projection(value: dict[str, Any]) -> dict[str, Any]:
    target = value.get("target_kernel")
    runtime = value.get("trusted_runtime")
    validation = value.get("validation")
    _require(isinstance(target, dict) and isinstance(runtime, dict) and isinstance(validation, dict), "readiness projection sections are incomplete")
    _require(type(target.get("all_pins_complete")) is bool, "readiness projection target pin flag is malformed")
    _require(runtime.get("production_authority_authenticated") is False and runtime.get("production_runtime_identity_authenticated") is False, "readiness projection promoted runtime identity", code="authorization_drift")
    for field in ("target_abi_conformance", "source_callgraph_conformance", "target_kernel_runtime_conformance"):
        if field in validation:
            _require(validation[field] is False, f"readiness projection promoted {field}", code="authorization_drift")
    return {"target": target, "runtime": runtime, "validation": validation}


def _validate_readiness_v8(value: dict[str, Any]) -> dict[str, Any]:
    selector = value.get("selector_domain")
    _require(isinstance(selector, dict), "readiness v8 selector domain is missing")
    _require(value.get("readiness_pass") is False and value.get("T1_numerical") is False and value.get("qualification_credit") == 0, "readiness v8 promoted authority", code="authorization_drift")
    _require(selector.get("target_kernel_build_pinned") is False and selector.get("target_kernel_config_pinned") is False, "readiness v8 promoted target pin", code="authorization_drift")
    _require(selector.get("runtime_conformance_passed") is False, "readiness v8 promoted runtime conformance", code="authorization_drift")
    return {"selector": selector, "blocking_gaps": value.get("blocking_gaps", [])}


def _validate_trusted_report(value: dict[str, Any], *, handoff: bool) -> dict[str, Any]:
    boundary = value.get("non_authorizing_boundary")
    input_boundary = value.get("input_boundary")
    _require(isinstance(boundary, dict) and isinstance(input_boundary, dict), "trusted contract boundary is incomplete")
    _require(input_boundary.get("synthetic_only") is True, "trusted contract is not synthetic-only", code="trusted_identity_drift")
    _require(boundary.get("readiness_pass") is False and boundary.get("T1_numerical") is False and boundary.get("execution_authority") is False, "trusted contract promoted authority", code="authorization_drift")
    _require(boundary.get("qualification_credit") == 0, "trusted contract promoted credit", code="authorization_drift")
    if handoff:
        _require(input_boundary.get("production_paths_read") is False, "trusted handoff production boundary drift", code="trusted_identity_drift")
        constraints = value.get("fail_closed_constraints")
        _require(isinstance(constraints, dict) and constraints.get("production_identity") == "not_authenticated" and constraints.get("runtime") == "not_measured", "trusted handoff identity/runtime boundary drift", code="trusted_identity_drift")
    return {
        "synthetic_only": True,
        "production_identity_authenticated": False,
        "runtime_measured": False,
    }


def _validate_admission(value: dict[str, Any]) -> None:
    admission = value.get("admission")
    target = value.get("target_kernel")
    runtime = value.get("runtime_and_terminal")
    dependencies = value.get("dependencies")
    _require(isinstance(admission, dict) and isinstance(target, dict) and isinstance(runtime, dict) and isinstance(dependencies, dict), "admission bridge sections are incomplete")
    for field in ("target_kernel_static_pin_complete", "target_kernel_source_integrity_verified", "source_callgraph_conformance", "trusted_runtime_identity_verified"):
        _require(type(admission.get(field)) is bool, f"admission bridge {field} is malformed")
    for field in ("all_required_pins_complete", "source_commit_proven", "source_tree_proven", "build_id_proven"):
        _require(type(target.get(field)) is bool, f"admission bridge target {field} is malformed")
    _require(runtime.get("production_authority_authenticated") is False and runtime.get("production_runtime_identity_authenticated") is False and runtime.get("target_kernel_runtime_conformance") is False, "admission bridge promoted runtime identity", code="authorization_drift")


def _load_dependencies(
    dependency_paths: Mapping[str, str | Path] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    values: dict[str, dict[str, Any]] = {}
    refs: dict[str, dict[str, Any]] = {}
    supplied = dict(dependency_paths or {})
    for key, spec in DEPENDENCY_SPECS.items():
        path = supplied.get(key, spec["path"])
        value, reference = _read_json(path, label=f"dependency {key}")
        _validate_dependency_identity(key, value, spec)
        values[key] = value
        refs[key] = _dependency_ref(value, reference)

    target = _validate_target_intake(values["target_kernel_evidence_intake"])
    local = _validate_local_inventory(values["target_kernel_local_inventory"])
    projection = _validate_readiness_projection(values["target_kernel_readiness_projection"])
    readiness = _validate_readiness_v8(values["readiness_v8"])
    trusted_identity = _validate_trusted_report(values["trusted_identity"], handoff=False)
    trusted_handoff = _validate_trusted_report(values["trusted_handoff"], handoff=True)
    _validate_admission(values["admission_bridge"])
    return values, {
        "refs": refs,
        "target": target,
        "local": local,
        "projection": projection,
        "readiness": readiness,
        "trusted_identity": trusted_identity,
        "trusted_handoff": trusted_handoff,
    }


def _same_reference(
    item: Any,
    expected: Mapping[str, Any],
    *,
    schema_aliases: tuple[str, ...] = (),
) -> bool:
    if not isinstance(item, dict):
        return False
    for field in ("path", "bytes", "sha256", "record_id"):
        if item.get(field) != expected.get(field):
            return False
    return item.get("schema") in (expected.get("schema"), *schema_aliases)


def _reconcile_dependency_bindings(
    values: Mapping[str, Mapping[str, Any]],
    refs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    admission = values["admission_bridge"].get("dependencies")
    projection = values["target_kernel_readiness_projection"].get("inputs")
    _require(isinstance(admission, dict) and isinstance(projection, dict), "upstream dependency bindings are missing")
    admission_mapping = {
        "target_kernel_evidence_intake": "target_kernel_evidence_intake",
        "target_kernel_local_inventory": "target_kernel_local_inventory",
        "target_kernel_readiness_projection": "target_kernel_readiness_projection",
        "readiness_v8": "readiness_v8",
        "trusted_identity": "trusted_identity",
        "trusted_handoff": "trusted_handoff",
    }
    admission_matches = {
        name: _same_reference(admission.get(name), refs[key])
        for name, key in admission_mapping.items()
    }
    projection_mapping = {
        "target_kernel_evidence_intake": "target_kernel_evidence_intake",
        "readiness_audit_v8": "readiness_v8",
        "trusted_identity_contract": "trusted_identity",
        "trusted_worker_runtime_handoff": "trusted_handoff",
    }
    projection_schema_aliases = {
        "trusted_identity_contract": (
            "core.cfd.f8.r008_trusted_authority_worker_runtime_identity_contract.v1",
        ),
        "trusted_worker_runtime_handoff": (
            "core.cfd.f8.r008_trusted_worker_runtime_handoff_contract.v1",
        ),
    }
    projection_matches = {
        name: _same_reference(
            projection.get(name),
            refs[key],
            schema_aliases=projection_schema_aliases.get(name, ()),
        )
        for name, key in projection_mapping.items()
    }
    trusted_runtime = values["target_kernel_readiness_projection"].get("trusted_runtime", {})
    runtime_matches = {
        "handoff_report_sha256": trusted_runtime.get("handoff_contract_report_sha256") == refs["trusted_handoff"]["sha256"],
        "identity_report_sha256": trusted_runtime.get("identity_contract_report_sha256") == refs["trusted_identity"]["sha256"],
    }
    stale: list[str] = []
    if not all(admission_matches.values()):
        stale.append("admission_bridge_dependency_binding_drift")
    if not all(projection_matches.values()):
        stale.append("readiness_projection_dependency_binding_drift")
    if not all(runtime_matches.values()):
        stale.append("readiness_projection_trusted_runtime_digest_drift")
    return {
        "admission_bridge": admission_matches,
        "readiness_projection": projection_matches,
        "trusted_runtime_digests": runtime_matches,
        "all_current_dependency_bindings_match": not stale,
        "stale_upstream_views": stale,
    }


def _local_candidate(
    *,
    candidate_id: str,
    role: str,
    path: str | None,
    state: str,
    detail: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "candidate_id": candidate_id,
        "role": role,
        "origin": "local_host_observation",
        "path": path,
        "state": state,
        "bindable_to_external_target": False,
        "external_pin_eligible": False,
        "read_by_locator": False,
        "detail": detail,
    }
    if metadata:
        item["metadata"] = dict(metadata)
    return item


def _external_candidate(
    *,
    role: str,
    item: Mapping[str, Any],
    complete: bool,
) -> dict[str, Any]:
    verified = item.get("verified") is True
    bindable = verified and complete
    state = (
        "verified_external_binding_closed"
        if bindable
        else "verified_but_external_binding_incomplete"
        if verified
        else "not_referenced_by_blocked_intake"
    )
    result: dict[str, Any] = {
        "candidate_id": f"external_{role}_artifact",
        "role": role,
        "origin": "external_target_evidence",
        "path": item.get("path"),
        "state": state,
        "bindable_to_external_target": bindable,
        "external_pin_eligible": bindable,
        "read_by_locator": False,
        "detail": "verified by the target-kernel intake report; locator does not follow the artifact path",
    }
    for field in ("declared_bytes", "declared_sha256", "observed_bytes", "observed_sha256"):
        result[field] = item.get(field)
    return result


def _build_artifact_locator(
    *,
    target: Mapping[str, Any],
    local: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = target["manifest"]
    manifest_exists = manifest.get("exists") is True
    manifest_candidate = {
        "candidate_id": "external_target_evidence_manifest",
        "role": "manifest",
        "origin": "external_target_evidence",
        "path": manifest.get("path"),
        "state": "reported_present" if manifest_exists else "reported_missing",
        "bindable_to_external_target": bool(target["complete"] and manifest_exists),
        "external_pin_eligible": bool(target["complete"] and manifest_exists),
        "read_by_locator": False,
        "detail": (
            "manifest is verified through the existing intake report"
            if manifest_exists
            else "the existing intake report says the external manifest is missing; no arbitrary search was performed"
        ),
        "bytes": manifest.get("bytes"),
        "sha256": manifest.get("sha256"),
    }
    external = [
        _external_candidate(role=role, item=target["artifacts"][role], complete=target["complete"])
        for role in ("source", "uapi", "config", "build")
    ]
    paths = local["paths"]
    evidence = local["evidence"]
    local_candidates = [
        _local_candidate(
            candidate_id="local_matching_boot_config",
            role="config",
            path=paths.get("boot_config", {}).get("path"),
            state="observed_local_config",
            detail="matching /boot config is local host evidence only; it cannot satisfy external target config pin",
            metadata={"bytes": paths.get("boot_config", {}).get("bytes"), "sha256": paths.get("boot_config", {}).get("sha256")},
        ),
        _local_candidate(
            candidate_id="local_matching_header_config",
            role="config",
            path=evidence.get("config", {}).get("header_config", {}).get("path"),
            state="observed_local_header_config",
            detail="matching header .config agrees with /boot/config but remains local-only",
            metadata={"bytes": evidence.get("config", {}).get("header_config", {}).get("bytes"), "sha256": evidence.get("config", {}).get("header_config", {}).get("sha256"), "sha256_equal": evidence.get("config", {}).get("sha256_equal")},
        ),
        _local_candidate(
            candidate_id="local_matching_header_root",
            role="headers",
            path=paths.get("header_root", {}).get("resolved_path") or paths.get("header_root", {}).get("path"),
            state="observed_local_header_metadata",
            detail="matching header root and fixed metadata samples are not a complete authenticated source/UAPI tree",
            metadata={"bounded_metadata_sha256": evidence.get("headers", {}).get("bounded_metadata_sha256"), "complete_tree_hash": evidence.get("headers", {}).get("complete_tree_hash")},
        ),
        _local_candidate(
            candidate_id="local_uapi_fixed_sample",
            role="uapi",
            path=evidence.get("uapi", {}).get("root", {}).get("path"),
            state="observed_local_uapi_sample_only",
            detail="fixed UAPI sample is present, but a sample hash is not a complete external UAPI tree pin",
            metadata={"sample_inventory_sha256": evidence.get("uapi", {}).get("sample_inventory_sha256"), "sample_only": evidence.get("uapi", {}).get("sample_only")},
        ),
        _local_candidate(
            candidate_id="local_build_link_metadata",
            role="build",
            path=paths.get("modules_build", {}).get("path"),
            state="observed_local_build_link_metadata",
            detail="matching modules/build metadata identifies a header package only; it is not a kernel build identity",
            metadata={"resolved_target": paths.get("modules_build", {}).get("resolved_target"), "target_directory": paths.get("modules_build", {}).get("target_directory")},
        ),
        _local_candidate(
            candidate_id="local_source_git_metadata",
            role="source",
            path=evidence.get("source_tree", {}).get("git_metadata", {}).get("path"),
            state="source_commit_metadata_not_observed",
            detail="bounded header-root source metadata does not expose an authenticated source commit or complete source-tree digest",
            metadata={"exists": evidence.get("source_tree", {}).get("git_metadata", {}).get("exists"), "complete_tree_hash": evidence.get("source_tree", {}).get("complete_tree_hash")},
        ),
        _local_candidate(
            candidate_id="local_source_marker_metadata",
            role="source",
            path=evidence.get("source_tree", {}).get("source_marker", {}).get("path"),
            state="source_tree_marker_not_authenticated",
            detail="a matching header package/source marker would still not authenticate the external target source tree",
            metadata={"exists": evidence.get("source_tree", {}).get("source_marker", {}).get("exists")},
        ),
    ]
    all_candidates = [manifest_candidate, *external, *local_candidates]
    return {
        "manifest": manifest_candidate,
        "candidates": all_candidates,
        "bindable_artifacts": [
            item["candidate_id"]
            for item in all_candidates
            if item["bindable_to_external_target"]
        ],
        "external_artifact_roles_verified": [
            item["role"] for item in external if item["bindable_to_external_target"]
        ],
        "local_candidates_are_external_pin_eligible": False,
    }


def _local_observed(local: Mapping[str, Any], pin: str) -> tuple[bool, bool]:
    evidence = local["evidence"]
    if pin == "kernel_release":
        item = evidence.get("kernel_release", {})
        return item.get("observed") is True, item.get("proven") is True
    if pin == "config":
        item = evidence.get("config", {})
        return item.get("observed") is True, item.get("proven") is True
    if pin == "uapi":
        item = evidence.get("uapi", {})
        return item.get("observed") is True, False
    if pin == "source_tree":
        item = evidence.get("source_tree", {})
        return item.get("observed") is True, item.get("proven") is True
    if pin == "source_commit":
        item = evidence.get("source_commit", {})
        return item.get("observed") is True, item.get("proven") is True
    if pin == "build_id":
        item = evidence.get("build_id", {})
        return item.get("observed") is True, item.get("proven") is True
    raise AssertionError(pin)


def _build_pin_reconciliation(
    *,
    target: Mapping[str, Any],
    local: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pin in PIN_FIELDS:
        external = bool(target["pins"].get(PIN_REPORT_FIELDS[pin], False))
        local_observed, local_proven = _local_observed(local, pin)
        sample_only = pin == "uapi" and local_observed
        blockers = [] if external else [PIN_BLOCKERS[pin]]
        if external:
            state = "external_pin_verified"
        elif local_observed:
            state = "local_observation_not_external_pin"
        else:
            state = "missing_external_pin"
        rows.append({
            "pin": pin,
            "required": True,
            "external_pin_verified": external,
            "local_observed": local_observed,
            "local_proven": local_proven,
            "local_sample_only": sample_only,
            "state": state,
            "blocker_codes": blockers,
            "external_target_field": PIN_REPORT_FIELDS[pin],
        })
    return rows


def _blocker(code: str, category: str, detail: str, evidence: list[str], next_artifact: str) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "severity": "high",
        "detail": detail,
        "evidence": evidence,
        "next_artifact": next_artifact,
    }


def _build_identity_blockers(
    *,
    target: Mapping[str, Any],
    local: Mapping[str, Any],
    projection: Mapping[str, Any],
    readiness: Mapping[str, Any],
    trusted_identity: Mapping[str, Any],
    trusted_handoff: Mapping[str, Any],
    pin_rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    manifest = target["manifest"]
    if not target["complete"]:
        code = "external_target_manifest_missing" if manifest.get("exists") is not True else "external_target_evidence_incomplete"
        blockers.append(_blocker(
            code,
            "external_artifact",
            "The existing target-kernel intake report does not close a complete external manifest plus source/UAPI/config/build artifact set.",
            ["target_kernel_evidence_intake"],
            "external/f8-r008-target-kernel-evidence-manifest-v1.json plus four verified artifact files",
        ))
    for row in pin_rows:
        if row["external_pin_verified"]:
            continue
        next_artifact = {
            "kernel_release": "external target release identity",
            "source_commit": "external source commit evidence",
            "source_tree": "complete external source-tree digest/tree manifest",
            "uapi": "complete external UAPI/header tree digest",
            "config": "external target config artifact and digest",
            "build_id": "external kernel build/debug identity evidence",
        }[row["pin"]]
        blockers.append(_blocker(
            row["blocker_codes"][0],
            "identity_hash" if row["pin"] in {"config", "uapi", "source_tree"} else "identity",
            f"Required external {row['pin']} pin is not verified; local observations cannot be promoted into an external target pin.",
            ["target_kernel_evidence_intake", "target_kernel_local_inventory"],
            next_artifact,
        ))
    if projection["validation"].get("target_abi_conformance") is not True:
        blockers.append(_blocker(
            "target_kernel_abi_runtime_conformance_missing",
            "runtime_identity",
            "No trusted evidence proves that the deployed target kernel ABI and selector/fanotify behavior conform to the R008 runtime contract.",
            ["target_kernel_readiness_projection", "readiness_v8"],
            "target-kernel ABI/runtime conformance receipt bound to the external target pins",
        ))
    if projection["validation"].get("source_callgraph_conformance") is not True:
        blockers.append(_blocker(
            "target_source_callgraph_conformance_missing",
            "source_tree",
            "Static repository source reviews are not a trusted target source-to-binary or loaded-runtime callgraph proof.",
            ["target_kernel_readiness_projection", "admission_bridge"],
            "external source/build/runtime callgraph identity receipt",
        ))
    if projection["validation"].get("target_kernel_runtime_conformance") is not True or readiness["selector"].get("runtime_conformance_passed") is not True:
        blockers.append(_blocker(
            "target_kernel_runtime_identity_conformance_missing",
            "runtime_identity",
            "The loaded kernel/build/runtime identity and target-kernel runtime conformance remain unmeasured.",
            ["readiness_v8", "target_kernel_readiness_projection", "admission_bridge"],
            "trusted runtime identity and target-kernel conformance receipt",
        ))
    if not trusted_identity["production_identity_authenticated"]:
        blockers.append(_blocker(
            "trusted_authority_identity_missing",
            "runtime_identity",
            "The trusted authority/worker/runtime identity contract is synthetic-only and does not authenticate production authority.",
            ["trusted_identity", "trusted_handoff"],
            "production trusted-authority identity receipt",
        ))
    if not trusted_handoff["production_identity_authenticated"] or not trusted_handoff["runtime_measured"]:
        blockers.append(_blocker(
            "trusted_runtime_identity_missing",
            "runtime_identity",
            "The worker/runtime handoff is a synthetic contract; production runtime identity and measured loaded code are absent.",
            ["trusted_handoff", "target_kernel_readiness_projection"],
            "production worker/runtime identity and measured handoff receipt",
        ))
    return blockers


def _build_runtime_reconciliation(
    *,
    projection: Mapping[str, Any],
    readiness: Mapping[str, Any],
    trusted_identity: Mapping[str, Any],
    trusted_handoff: Mapping[str, Any],
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    validation = projection["validation"]
    return {
        "target_abi_conformance": validation.get("target_abi_conformance") is True,
        "source_callgraph_conformance": validation.get("source_callgraph_conformance") is True,
        "target_kernel_runtime_conformance": validation.get("target_kernel_runtime_conformance") is True,
        "readiness_v8_runtime_conformance": readiness["selector"].get("runtime_conformance_passed") is True,
        "trusted_authority_authenticated": trusted_identity["production_identity_authenticated"],
        "trusted_runtime_identity_authenticated": trusted_handoff["production_identity_authenticated"] and trusted_handoff["runtime_measured"],
        "admission_source_callgraph_conformance": admission.get("admission", {}).get("source_callgraph_conformance") is True,
        "admission_target_kernel_source_integrity": admission.get("admission", {}).get("target_kernel_source_integrity_verified") is True,
        "all_runtime_identity_blockers_closed": False,
        "diagnostic_only": True,
    }


def _next_actions(
    *,
    target: Mapping[str, Any],
    pin_rows: list[Mapping[str, Any]],
    blockers: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not target["complete"]:
        actions.append({
            "priority": 1,
            "action": "provide_and_run_the_existing_external_target_kernel_intake",
            "required_artifacts": [
                "external manifest",
                "source evidence",
                "complete UAPI evidence",
                "config evidence",
                "build identity evidence",
            ],
            "constraint": "locator will not follow arbitrary artifact paths or treat local inventory as external evidence",
        })
    missing = [row["pin"] for row in pin_rows if not row["external_pin_verified"]]
    if missing:
        actions.append({
            "priority": 2,
            "action": "close_missing_external_identity_pins",
            "missing_pins": missing,
            "constraint": "each pin must be bound by the target-kernel intake report; local observations remain diagnostic",
        })
    if blockers:
        actions.append({
            "priority": 3,
            "action": "obtain_independently_trusted_runtime_identity_and_conformance_receipts",
            "blocker_codes": [item["code"] for item in blockers if item["category"] == "runtime_identity" or item["category"] == "source_tree"],
            "constraint": "no privileged probe, kernel image read, native/solver/worker/GPU/queue execution in this locator",
        })
    return actions


def build_report(
    *,
    dependency_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    values, parsed = _load_dependencies(dependency_paths)
    refs = parsed["refs"]
    target = parsed["target"]
    local = parsed["local"]
    projection = parsed["projection"]
    readiness = parsed["readiness"]
    trusted_identity = parsed["trusted_identity"]
    trusted_handoff = parsed["trusted_handoff"]
    _validate_admission(values["admission_bridge"])

    dependency_bindings = _reconcile_dependency_bindings(values, refs)
    locator = _build_artifact_locator(target=target, local=local)
    pin_rows = _build_pin_reconciliation(target=target, local=local)
    blockers = _build_identity_blockers(
        target=target,
        local=local,
        projection=projection,
        readiness=readiness,
        trusted_identity=trusted_identity,
        trusted_handoff=trusted_handoff,
        pin_rows=pin_rows,
    )
    runtime = _build_runtime_reconciliation(
        projection=projection,
        readiness=readiness,
        trusted_identity=trusted_identity,
        trusted_handoff=trusted_handoff,
        admission=values["admission_bridge"],
    )
    target_complete = target["complete"]
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "scope_id": SCOPE_ID,
        "status": STATUS,
        "authorization": dict(AUTHORIZATION),
        "dependencies": refs,
        "artifact_locator": locator,
        "local_observation": {
            "kernel_release": local["evidence"].get("kernel_release", {}).get("release"),
            "matching_config_observed": local["validation"].get("matching_config_observed") is True,
            "uapi_sample_complete": local["validation"].get("uapi_sample_complete") is True,
            "source_commit_proven": False,
            "source_tree_proven": False,
            "build_id_proven": False,
            "external_pin_promotion_allowed": False,
            "local_inventory_status": values["target_kernel_local_inventory"]["status"],
        },
        "pin_reconciliation": pin_rows,
        "identity_blockers": blockers,
        "runtime_reconciliation": runtime,
        "reconciliation": {
            "external_target_binding": {
                "state": "external_artifacts_bound_non_authorizing" if target_complete else "blocked_missing_or_incomplete_external_target_evidence",
                "complete": target_complete,
                "manifest_path": target["manifest"].get("path"),
                "verified_artifact_roles": locator["external_artifact_roles_verified"],
                "missing_pins": [row["pin"] for row in pin_rows if not row["external_pin_verified"]],
            },
            "local_inventory_not_promoted_to_external": locator["local_candidates_are_external_pin_eligible"] is False,
            "dependency_digests_recomputed": True,
            "upstream_dependency_bindings": dependency_bindings,
            "all_current_dependency_bindings_match": dependency_bindings["all_current_dependency_bindings_match"],
            "stale_upstream_views": list(dependency_bindings["stale_upstream_views"]),
            "runtime_identity_reconciled": False,
            "readiness_reconciled": False,
        },
        "next_actions": _next_actions(target=target, pin_rows=pin_rows, blockers=blockers),
        "read_policy": dict(READ_POLICY),
        "prohibited_operations": list(PROHIBITED_OPERATIONS),
        "mutations": dict(MUTATIONS),
        "side_effects": dict(SIDE_EFFECTS),
    }


def validate_report(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(type(value) is dict, "locator report must be a builtin object")
    expected_top = {
        "artifact_locator", "authorization", "dependencies", "identity_blockers",
        "local_observation", "mutations", "next_actions", "pin_reconciliation",
        "prohibited_operations", "read_policy", "record_id", "reconciliation",
        "runtime_reconciliation", "schema", "scope_id", "side_effects", "status",
    }
    _require(set(value) == expected_top, "locator report fields differ")
    _require(value["schema"] == SCHEMA and value["record_id"] == RECORD_ID, "locator report identity drift", code="schema_drift")
    _require(value["scope_id"] == SCOPE_ID and value["status"] == STATUS, "locator report scope/status drift", code="scope_drift")
    _require(value["authorization"] == AUTHORIZATION, "locator authorization boundary drift", code="authorization_drift")
    _require(value["mutations"] == MUTATIONS and value["side_effects"] == SIDE_EFFECTS, "locator mutation boundary drift", code="side_effect_drift")
    _require(value["read_policy"] == READ_POLICY and value["prohibited_operations"] == PROHIBITED_OPERATIONS, "locator read boundary drift", code="read_policy_drift")
    dependencies = value["dependencies"]
    _require(type(dependencies) is dict and set(dependencies) == set(DEPENDENCY_SPECS), "locator dependency inventory drift")
    for key, item in dependencies.items():
        _require(type(item) is dict, f"locator dependency {key} is malformed")
        _require(type(item.get("path")) is str and item["path"], f"locator dependency {key} path is missing")
        _require(type(item.get("bytes")) is int and item["bytes"] > 0, f"locator dependency {key} byte count is malformed")
        _sha256(item.get("sha256"), f"locator dependency {key} digest")
        spec = DEPENDENCY_SPECS[key]
        _require(item.get("schema") == spec["schema"] and item.get("record_id") == spec["record_id"], f"locator dependency {key} identity drift")
        _require(item.get("status") in spec["statuses"], f"locator dependency {key} status drift")

    pins = value["pin_reconciliation"]
    _require(type(pins) is list and len(pins) == len(PIN_FIELDS), "locator pin rows are incomplete")
    _require(tuple(item.get("pin") for item in pins) == PIN_FIELDS, "locator pin order drift")
    for item in pins:
        _require(type(item.get("external_pin_verified")) is bool and type(item.get("local_observed")) is bool, "locator pin flags are malformed")
        _require(item.get("required") is True and item.get("state") in {"external_pin_verified", "local_observation_not_external_pin", "missing_external_pin"}, "locator pin state drift")
        if item["external_pin_verified"]:
            _require(item["blocker_codes"] == [], "verified pin retains a blocker")
        else:
            _require(item["blocker_codes"] == [PIN_BLOCKERS[item["pin"]]], "missing pin blocker drift")

    local = value["local_observation"]
    _require(isinstance(local, dict) and local.get("external_pin_promotion_allowed") is False, "local observation promotion boundary drift", code="authorization_drift")
    _require(local.get("source_commit_proven") is False and local.get("source_tree_proven") is False and local.get("build_id_proven") is False, "local source/build identity was promoted", code="authorization_drift")
    locator = value["artifact_locator"]
    _require(isinstance(locator, dict) and locator.get("local_candidates_are_external_pin_eligible") is False, "local artifact promotion boundary drift", code="authorization_drift")
    for item in locator.get("candidates", []):
        if item.get("origin") == "local_host_observation":
            _require(item.get("bindable_to_external_target") is False and item.get("external_pin_eligible") is False, "local candidate was promoted", code="authorization_drift")

    reconciliation = value["reconciliation"]
    external = reconciliation.get("external_target_binding")
    _require(isinstance(external, dict), "external target binding section is missing")
    _require(type(external.get("complete")) is bool, "external target binding completeness is malformed")
    verified_roles = external.get("verified_artifact_roles")
    _require(type(verified_roles) is list, "external artifact role inventory is malformed")
    if external["complete"]:
        _require(set(verified_roles) == {"source", "uapi", "config", "build"}, "closed external binding lacks all four artifacts", code="pin_drift")
        _require(all(item["external_pin_verified"] for item in pins), "closed external binding lacks all pins", code="pin_drift")
    else:
        _require(not all(item["external_pin_verified"] for item in pins), "incomplete external binding has all pins", code="pin_drift")

    runtime = value["runtime_reconciliation"]
    _require(isinstance(runtime, dict) and runtime.get("all_runtime_identity_blockers_closed") is False and runtime.get("diagnostic_only") is True, "runtime reconciliation promoted authority", code="authorization_drift")
    blockers = value["identity_blockers"]
    _require(type(blockers) is list and blockers and all(isinstance(item, dict) for item in blockers), "identity blocker inventory is missing")
    _require(all(item.get("severity") == "high" for item in blockers), "identity blocker severity drift")
    _require(isinstance(value["next_actions"], list) and value["next_actions"], "locator next actions are missing")
    return dict(value)


def verify_report(path: str | Path = DEFAULT_REPORT) -> dict[str, Any]:
    value, _reference = _read_json(path, label="locator report")
    validate_report(value)
    expected = build_report()
    _require(value == expected, "checked-in locator report differs from current bounded evidence", code="report_digest_drift")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _zh_report(value: Mapping[str, Any]) -> str:
    external = value["reconciliation"]["external_target_binding"]
    missing = ", ".join(external["missing_pins"]) or "无"
    blocker_lines = "\n".join(
        f"- `{item['code']}`（{item['category']}）：{item['detail']}"
        for item in value["identity_blockers"]
    )
    candidate_lines = "\n".join(
        f"- `{item['candidate_id']}`：`{item['state']}`，path=`{item.get('path')}`；{item['detail']}"
        for item in value["artifact_locator"]["candidates"]
    )
    return f"""# F8/R008 target-kernel evidence locator/reconciliation V1

状态：`{value['status']}`。

本模块只消费既有 bounded JSON reports，并列出可绑定 artifact、缺失 pin 与 identity/runtime blocker；它不跟随 external artifact path，不启动或控制任何 workload，也不修改 PLAN、registry、ledger、denominator、gate 或 completion。

## External binding

- external manifest：`{external['manifest_path']}`
- binding state：`{external['state']}`
- complete：`{external['complete']}`
- verified artifact roles：`{', '.join(external['verified_artifact_roles']) or '无'}`
- missing pins：`{missing}`

若未来 target-kernel intake 已验证 source/UAPI/config/build 四类 external artifact 且六个 pin 全部为 true，本报告会将 external binding 标为 closed；这不等于 readiness 或 T1。

## Artifact candidates

{candidate_lines}

local inventory 的 `/boot/config`、matching headers 与固定 UAPI sample 只能作为本机观察，`local_candidates_are_external_pin_eligible=false`。

## Identity/runtime blockers

{blocker_lines}

## Zero-authority boundary

- readiness / T1 / formal admission：`false`
- qualification credit：`0`
- runtime identity blockers closed：`false`
- locator 未读取 kernel image、procfs/sysfs、production BI4/HDF5/solver frame，未执行 privileged/fanotify/native/solver/worker/GPU/queue。

机器报告：[F8-R008-TARGET-KERNEL-EVIDENCE-LOCATOR-RECONCILIATION-V1-2026-09-28.json](F8-R008-TARGET-KERNEL-EVIDENCE-LOCATOR-RECONCILIATION-V1-2026-09-28.json)。
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=LAB_ROOT / DEFAULT_REPORT)
    parser.add_argument("--zh-report", type=Path, default=LAB_ROOT / DEFAULT_ZH_REPORT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            value = verify_report(args.report)
        else:
            value = build_report()
            validate_report(value)
            _write_json(args.report, value)
            args.zh_report.parent.mkdir(parents=True, exist_ok=True)
            args.zh_report.write_text(_zh_report(value), encoding="utf-8")
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return 0
    except (LocatorReconciliationError, OSError, ValueError) as error:
        print(f"f8 target-kernel locator/reconciliation failed closed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHORIZATION",
    "DEFAULT_REPORT",
    "DEPENDENCY_SPECS",
    "LAB_ROOT",
    "LocatorReconciliationError",
    "MUTATIONS",
    "PIN_FIELDS",
    "PROHIBITED_OPERATIONS",
    "READ_POLICY",
    "SCHEMA",
    "SIDE_EFFECTS",
    "STATUS",
    "build_report",
    "validate_report",
    "verify_report",
]
