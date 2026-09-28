#!/usr/bin/env python3
"""Build and verify the non-authorizing F8/R008 syscall static closure.

The closure is deliberately conservative: every native Linux v6.8 number in
the frozen ``0..461`` universe receives an explicit ``deny_errno`` disposition
and an exact audit-arch/raw-number predicate.  It is a complete default-deny
static policy, not a claim that any syscall is safe to execute.

The report also records the target-kernel pin boundary.  Local release/config
and bounded UAPI observations are retained as candidates only; they never
become target source, complete-UAPI, build-id, or external config pins.  The
ptrace/seccomp, x32, and ``nr == -1`` rules are static requirements with
runtime verification intentionally false.  This module never starts native
code, touches a kernel selector, launches a GPU/queue job, or mutates a gate,
registry, ledger, denominator, completion record, or PLAN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from scripts import f8_r008_syscall_selector_domain_v1 as selector_domain
from scripts import f8_r008_syscall_universe_baseline_v1 as source_baseline
from scripts import f8_r008_target_kernel_evidence_intake_v1 as target_intake
from scripts import f8_r008_target_kernel_local_inventory_v1 as local_inventory


LAB = Path(__file__).resolve().parents[1]
OUTPUT = Path("reports/F8-R008-SYSCALL-STATIC-CLOSURE-V1.json")
SCHEMA = "core.cfd.f8.r008_syscall_static_closure_report.v1"
RECORD_ID = "f8-r008-syscall-static-closure-v1"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"
STATUS_MISSING_TARGET = "static_default_deny_policy_closed_target_pin_missing"
STATUS_BOUND_TARGET = "static_default_deny_policy_closed_target_pin_bound_non_authorizing"

SOURCE_AUDIT = Path("reports/F8-R008-FINAL-FPUT-LINUX-V6.8-SOURCE-AUDIT-V1.json")
TARGET_INTAKE = Path("reports/F8-R008-TARGET-KERNEL-EVIDENCE-INTAKE-V1.json")
LOCAL_INVENTORY = Path("reports/F8-R008-TARGET-KERNEL-LOCAL-INVENTORY-V1-2026-09-28.json")

MAX_JSON_BYTES = 4 * 1024 * 1024
HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
HEX40 = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
SAFE_REF = re.compile(r"[A-Za-z0-9_./:-]{1,512}\Z", re.ASCII)
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)

POLICY_SOURCE_REFS = sorted(
    {
        "reports/F8-R008-SYSCALL-SELECTOR-DOMAIN-V1.json",
        "reports/F8-R008-SYSCALL-UNIVERSE-LINUX-V6.8-X86_64-BASELINE-V1.json",
        "reports/F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V14-2026-09-26.zh-CN.md",
    }
)

AUTHORIZATION = {
    "diagnostic_only": True,
    "capability_minted": False,
    "formal_admission": False,
    "execution_authority": False,
    "readiness_pass": False,
    "T1_numerical": False,
    "qualification_credit": 0,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
}

SIDE_EFFECTS = {
    "system_write": 0,
    "kernel_started": False,
    "native_started": False,
    "solver_started": False,
    "worker_started": False,
    "gpu_started": False,
    "queue_started": False,
    "privileged_probe": False,
    "registry_mutation": 0,
    "ledger_mutation": 0,
    "denominator_mutation": 0,
    "gate_mutation": 0,
    "plan_mutation": 0,
}


class StaticClosureError(ValueError):
    """The F8 static closure or one of its bounded dependencies is malformed."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StaticClosureError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    raise StaticClosureError(f"non-standard JSON constant is not permitted: {token}")


def _canonical_path(path: str | Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        target = value
    else:
        if value.as_posix() != str(value) or not value.parts or any(
            part in {"", ".", ".."} for part in value.parts
        ):
            raise StaticClosureError(f"dependency path is not canonical: {path}")
        target = LAB / value
    try:
        target.relative_to(LAB)
    except ValueError as error:
        raise StaticClosureError(f"dependency path escapes lab root: {path}") from error
    if target.as_posix() != str(target):
        raise StaticClosureError(f"dependency path is not canonical: {path}")
    return target


def _display(path: Path) -> str:
    return path.relative_to(LAB).as_posix()


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


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise StaticClosureError(f"could not inspect dependency path: {path}") from error
        if stat.S_ISLNK(info.st_mode):
            raise StaticClosureError(f"dependency path contains a symlink: {path}")


def _read_json(path: str | Path, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    target = _canonical_path(path)
    _assert_no_symlink_components(target)
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(target), os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    except OSError as error:
        raise StaticClosureError(f"{label} cannot be opened safely: {_display(target)}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise StaticClosureError(f"{label} must be a single-link regular file")
        if before.st_size <= 0 or before.st_size > MAX_JSON_BYTES:
            raise StaticClosureError(f"{label} exceeds the bounded JSON read limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, MAX_JSON_BYTES + 1 - total))
            if not block:
                break
            total += len(block)
            if total > MAX_JSON_BYTES:
                raise StaticClosureError(f"{label} exceeds the bounded JSON read limit")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(target, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named):
            raise StaticClosureError(f"{label} changed while being read")
        raw = b"".join(chunks)
        try:
            value = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_strict_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StaticClosureError(f"{label} is not strict UTF-8 JSON") from error
        if not isinstance(value, dict):
            raise StaticClosureError(f"{label} must be a JSON object")
        return value, {
            "path": _display(target),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StaticClosureError(message)


def _sha256(value: Any, label: str) -> str:
    _require(type(value) is str and HEX64.fullmatch(value) is not None, f"{label} is not lowercase SHA-256")
    return value


def _sha1(value: Any, label: str) -> str:
    _require(type(value) is str and HEX40.fullmatch(value) is not None, f"{label} is not lowercase SHA-1")
    return value


def _reference(meta: Mapping[str, Any], value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": meta["path"],
        "bytes": meta["bytes"],
        "sha256": meta["sha256"],
        "schema": value.get("schema"),
        "record_id": value.get("record_id"),
        "status": value.get("status"),
    }


def _validate_source_audit(value: Mapping[str, Any]) -> None:
    _require(value.get("schema") == "core.cfd.f8.r008_final_fput_linux_v6_8_source_audit.v1", "source audit schema drift")
    _require(value.get("status") == "upstream_static_source_audit_only", "source audit status drift")
    source = value.get("source")
    _require(isinstance(source, dict), "source audit source section is missing")
    _require(source.get("repository") == "https://github.com/torvalds/linux", "source audit repository drift")
    _require(source.get("tag") == "v6.8", "source audit tag drift")
    _require(source.get("target_kernel_source_pinned") is False, "upstream source audit was promoted to target pin")
    _require(source.get("tag_signature_verified") is False, "upstream source audit signature state drift")
    _sha1(source.get("peeled_commit"), "source audit peeled commit")
    _sha1(source.get("tag_object"), "source audit tag object")
    files = source.get("files")
    _require(isinstance(files, list) and files, "source audit file hash inventory is missing")
    seen: set[str] = set()
    for item in files:
        _require(isinstance(item, dict), "source audit file hash row is malformed")
        _require(set(item) == {"path", "reviewed_symbols", "sha256"}, "source audit file hash row schema drift")
        path = item["path"]
        _require(isinstance(path, str) and SAFE_REF.fullmatch(path) is not None and path not in seen, "source audit file path is malformed")
        seen.add(path)
        _sha256(item["sha256"], f"source audit hash for {path}")
        symbols = item["reviewed_symbols"]
        _require(isinstance(symbols, list) and symbols and all(isinstance(symbol, str) and symbol for symbol in symbols), f"source audit symbols for {path} are malformed")
    _require(
        value.get("authorization_and_readiness") == {
            "runtime_or_capability_probe_performed": False,
            "privileged_action_performed": False,
            "production_data_read": False,
            "native_build_or_worker_started": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "execution_authority": False,
            "qualification_credit": 0,
        },
        "source audit authorization boundary drift",
    )


def _load_dependencies() -> dict[str, Any]:
    baseline = source_baseline.verify_output()
    selector = selector_domain.verify_output()
    source_audit, source_audit_meta = _read_json(SOURCE_AUDIT, label="source audit")
    _validate_source_audit(source_audit)
    intake, intake_meta = _read_json(TARGET_INTAKE, label="target-kernel intake report")
    try:
        target_intake._validate_report(intake)
    except Exception as error:
        raise StaticClosureError(f"target-kernel intake report is invalid: {error}") from error
    local, local_meta = _read_json(LOCAL_INVENTORY, label="local target-kernel inventory")
    try:
        local_inventory.validate_report(local)
    except Exception as error:
        raise StaticClosureError(f"local target-kernel inventory is invalid: {error}") from error
    _require(
        baseline["universe"]["row_count"] == 462
        and selector["raw_nr_domain"]["partition"][2]["count"] == 462,
        "baseline and selector do not bind the 462-number native interval",
    )
    return {
        "baseline": baseline,
        "selector": selector,
        "source_audit": source_audit,
        "source_audit_meta": source_audit_meta,
        "intake": intake,
        "intake_meta": intake_meta,
        "local": local,
        "local_meta": local_meta,
    }


def _dependency_refs(deps: Mapping[str, Any]) -> dict[str, Any]:
    baseline = deps["baseline"]
    selector = deps["selector"]
    source_audit = deps["source_audit"]
    baseline_meta = _read_fixed_reference(source_baseline.OUTPUT, "syscall baseline")
    selector_meta = _read_fixed_reference(selector_domain.OUTPUT, "selector domain")
    return {
        "syscall_baseline": _reference(baseline_meta, baseline),
        "selector_domain": _reference(selector_meta, selector),
        "source_audit": _reference(deps["source_audit_meta"], source_audit),
        "target_kernel_intake": _reference(deps["intake_meta"], deps["intake"]),
        "local_kernel_inventory": _reference(deps["local_meta"], deps["local"]),
    }


def _read_fixed_reference(path: Path, label: str) -> dict[str, Any]:
    _, meta = _read_json(path, label=label)
    return meta


def _target_pin_projection(deps: Mapping[str, Any]) -> dict[str, Any]:
    intake = deps["intake"]
    local = deps["local"]
    target = intake["declared_target"]
    pins = intake["pins"]
    externally_bound = (
        intake["status"] == target_intake.STATUS_VALID_NON_AUTHORIZING
        and intake["validation"]["external_target_evidence_complete"] is True
        and all(pins.values())
    )
    local_evidence = local["evidence"]
    local_config = local_evidence["config"].get("boot_config", {})
    local_uapi = local_evidence["uapi"]
    return {
        "state": "external_target_pins_bound_non_authorizing" if externally_bound else "external_target_pins_missing",
        "external_verified": externally_bound,
        "slots": {
            "kernel_release": {
                "required": True,
                "external_verified": bool(pins["kernel_release_pinned"]),
                "target_value": target["kernel_release"] if externally_bound else None,
                "local_candidate": local_evidence["kernel_release"].get("release") if local_evidence["kernel_release"].get("observed") else None,
                "local_candidate_is_external_pin": False,
            },
            "source_commit": {
                "required": True,
                "external_verified": bool(pins["source_commit_pinned"]),
                "target_value": target["source_commit"] if externally_bound else None,
                "local_candidate": None,
                "local_candidate_is_external_pin": False,
            },
            "source_tree_sha256": {
                "required": True,
                "external_verified": bool(pins["source_tree_pinned"]),
                "target_value": target["source_tree_sha256"] if externally_bound else None,
                "local_candidate": local_evidence["source_tree"].get("complete_tree_hash"),
                "local_candidate_is_external_pin": False,
            },
            "uapi_sha256": {
                "required": True,
                "external_verified": bool(pins["uapi_pinned"]),
                "target_value": target["uapi_sha256"] if externally_bound else None,
                "local_candidate": local_uapi.get("complete_tree_hash"),
                "local_sample_inventory_sha256": local_uapi.get("sample_inventory_sha256"),
                "local_candidate_is_external_pin": False,
            },
            "config_sha256": {
                "required": True,
                "external_verified": bool(pins["config_pinned"]),
                "target_value": target["config_sha256"] if externally_bound else None,
                "local_candidate": local_config.get("sha256"),
                "local_candidate_is_external_pin": False,
            },
            "build_id": {
                "required": True,
                "external_verified": bool(pins["build_id_pinned"]),
                "target_value": target["build_id"] if externally_bound else None,
                "local_candidate": local_evidence["build_id"].get("value"),
                "local_candidate_is_external_pin": False,
            },
        },
        "required_external_artifact_roles": ["build", "config", "source", "uapi"],
        "missing_external_pins": [
            name for name, field in (
                ("kernel_release", "kernel_release_pinned"),
                ("source_commit", "source_commit_pinned"),
                ("source_tree_sha256", "source_tree_pinned"),
                ("uapi_sha256", "uapi_pinned"),
                ("config_sha256", "config_pinned"),
                ("build_id", "build_id_pinned"),
            ) if not pins[field]
        ],
    }


def _known_reference_hashes(deps: Mapping[str, Any]) -> dict[str, Any]:
    baseline = deps["baseline"]
    selector = deps["selector"]
    source = deps["source_audit"]["source"]
    return {
        "upstream_syscall_table_sha256": baseline["source"]["sha256"],
        "upstream_native_rows_sha256": baseline["universe"]["rows_sha256"],
        "selector_domain_artifact_sha256": _dependency_refs(deps)["selector_domain"]["sha256"],
        "source_audit_artifact_sha256": deps["source_audit_meta"]["sha256"],
        "source_audit_upstream_tag": source["tag"],
        "source_audit_peeled_commit": source["peeled_commit"],
        "source_audit_tag_object": source["tag_object"],
        "source_audit_file_hashes": [
            {"path": item["path"], "sha256": item["sha256"]}
            for item in sorted(source["files"], key=lambda item: item["path"])
        ],
        "selector_target_audit_arch_hex": selector["selector_abi"]["target_audit_arch_hex"],
        "selector_x32_syscall_bit_hex": selector["selector_abi"]["x32_syscall_bit_hex"],
    }


def _selector_conditions() -> dict[str, Any]:
    return {
        "audit_arch": {
            "raw_type": "unsigned_int32",
            "target_value_hex": "0xc000003e",
            "target_action": "classify_raw_nr",
            "other_arch_action": "deny",
            "static_condition_complete": True,
        },
        "raw_nr": {
            "raw_type": "signed_int32",
            "minimum": -(1 << 31),
            "maximum": (1 << 31) - 1,
            "partition_complete": True,
            "negative_non_sentinel_action": "deny",
        },
        "nr_minus_one": {
            "raw_value": -1,
            "selector_class": "minus_one_unattributed_skip_or_user_selector",
            "target_request_action": "deny_without_separate_trusted_tracer_state",
            "selector_alone_attributes_to_tracer": False,
            "runtime_behavior_verified": False,
        },
        "x32": {
            "syscall_bit_hex": "0x40000000",
            "tagged_raw_number_action": "deny_x32_abi",
            "required_config_option": "CONFIG_X86_X32_ABI",
            "required_config_value": "n",
            "x32_table_range": {"minimum": 512, "maximum": 547, "count": 36},
            "runtime_rejection_verified": False,
        },
        "ptrace_seccomp": {
            "supervisor_mode": "ptrace_syscall_entry_stop_only",
            "decision_point": "ptrace_entry_stop",
            "entry_to_exit_or_broker_return_required": True,
            "seccomp_user_notification": "forbidden",
            "seccomp_user_notification_continue": "forbidden",
            "preexisting_seccomp_filter": "reject_profile",
            "seccomp_filter_install_or_replace": "forbidden",
            "order_runtime_conformance_verified": False,
            "static_condition_complete": True,
        },
    }


def _policy_rows(baseline: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_row in baseline["universe"]["rows"]:
        number = source_row["syscall_number"]
        rows.append({
            "syscall_number": number,
            "number_state": source_row["number_state"],
            "abi": source_row["abi"],
            "name": source_row["name"],
            "entry_point": source_row["entry_point"],
            "disposition": "deny_errno",
            "predicate": {
                "language": "static-reviewed-predicate-v1",
                "expression": f"audit_arch == 0xc000003e && raw_nr == {number}",
                "source_refs": POLICY_SOURCE_REFS,
            },
        })
    return rows


def _rows_sha256(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_report() -> dict[str, Any]:
    deps = _load_dependencies()
    baseline = deps["baseline"]
    selector = deps["selector"]
    target_pins = _target_pin_projection(deps)
    rows = _policy_rows(baseline)
    target_bound = target_pins["external_verified"]
    blockers = []
    if not target_bound:
        blockers.append("external_target_kernel_source_config_uapi_build_pins_missing")
    blockers.extend([
        "ptrace_seccomp_order_runtime_conformance_missing",
        "x32_runtime_rejection_missing",
        "nr_minus_one_runtime_semantics_missing",
    ])
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "scope_id": SCOPE_ID,
        "status": STATUS_BOUND_TARGET if target_bound else STATUS_MISSING_TARGET,
        "static_policy": {
            "strategy": "complete_native_default_deny_no_allowlist",
            "default_action": "deny",
            "native_number_minimum": 0,
            "native_number_maximum": 461,
            "native_row_count": 462,
            "rows_sha256": _rows_sha256(rows),
            "rows": rows,
        },
        "selector_conditions": _selector_conditions(),
        "target_kernel_pin": target_pins,
        "known_reference_hashes": _known_reference_hashes(deps),
        "dependencies": _dependency_refs(deps),
        "validation": {
            "baseline_rows_bound": True,
            "native_rows_complete": True,
            "per_number_dispositions_complete": True,
            "per_number_predicates_complete": True,
            "selector_conditions_complete": True,
            "target_kernel_pin_complete": target_bound,
            "runtime_conformance_verified": False,
            "fail_closed": True,
            "blockers": blockers,
        },
        "authorization": AUTHORIZATION,
        "side_effects": SIDE_EFFECTS,
    }


def _validate_predicate(value: Any, number: int) -> None:
    _require(isinstance(value, dict), f"row {number} predicate is missing")
    _require(set(value) == {"language", "expression", "source_refs"}, f"row {number} predicate schema drift")
    _require(value["language"] == "static-reviewed-predicate-v1", f"row {number} predicate language drift")
    _require(value["expression"] == f"audit_arch == 0xc000003e && raw_nr == {number}", f"row {number} predicate does not bind its number")
    _require(value["source_refs"] == POLICY_SOURCE_REFS, f"row {number} predicate source refs drift")


def _validate_target_pins(value: Mapping[str, Any]) -> None:
    _require(set(value) == {"state", "external_verified", "slots", "required_external_artifact_roles", "missing_external_pins"}, "target pin projection schema drift")
    _require(value["state"] in {"external_target_pins_missing", "external_target_pins_bound_non_authorizing"}, "target pin state drift")
    _require(type(value["external_verified"]) is bool, "target pin external_verified type drift")
    _require(value["external_verified"] == (value["state"] == "external_target_pins_bound_non_authorizing"), "target pin state/flag mismatch")
    _require(value["required_external_artifact_roles"] == ["build", "config", "source", "uapi"], "target artifact roles drift")
    expected = {"kernel_release", "source_commit", "source_tree_sha256", "uapi_sha256", "config_sha256", "build_id"}
    _require(set(value["slots"]) == expected, "target pin slots drift")
    pin_fields = {
        "kernel_release": "kernel_release_pinned",
        "source_commit": "source_commit_pinned",
        "source_tree_sha256": "source_tree_pinned",
        "uapi_sha256": "uapi_pinned",
        "config_sha256": "config_pinned",
        "build_id": "build_id_pinned",
    }
    expected_missing: list[str] = []
    for name, slot in value["slots"].items():
        _require(isinstance(slot, dict), f"target pin slot {name} is malformed")
        required = {"required", "external_verified", "target_value", "local_candidate", "local_candidate_is_external_pin"}
        if name == "uapi_sha256":
            required.add("local_sample_inventory_sha256")
        _require(set(slot) == required, f"target pin slot {name} schema drift")
        _require(slot["required"] is True, f"target pin slot {name} is not required")
        _require(type(slot["external_verified"]) is bool, f"target pin slot {name} flag is malformed")
        if not slot["external_verified"]:
            expected_missing.append(name)
        _require(slot["local_candidate_is_external_pin"] is False, f"local candidate {name} was promoted")
        if slot["external_verified"]:
            _require(slot["target_value"] is not None, f"verified target pin {name} has no value")
        else:
            _require(slot["target_value"] is None, f"unverified target pin {name} retained a value")
        if name in {"source_commit"} and slot["target_value"] is not None:
            _sha1(slot["target_value"], f"target {name}")
        if name in {"source_tree_sha256", "uapi_sha256", "config_sha256"} and slot["target_value"] is not None:
            _sha256(slot["target_value"], f"target {name}")
        if name == "uapi_sha256" and slot["local_sample_inventory_sha256"] is not None:
            _sha256(slot["local_sample_inventory_sha256"], "local UAPI sample inventory")
        if name == "source_commit" and slot["local_candidate"] is not None:
            _sha1(slot["local_candidate"], "local source commit candidate")
        if name in {"source_tree_sha256", "uapi_sha256", "config_sha256"} and slot["local_candidate"] is not None:
            _sha256(slot["local_candidate"], f"local {name} candidate")
    _require(value["missing_external_pins"] == sorted(expected_missing, key=lambda name: list(pin_fields).index(name)), "target missing-pin inventory drift")
    _require(value["external_verified"] is (not expected_missing), "target slot/global pin mismatch")


def _validate_report_shape(value: Any, deps: Mapping[str, Any]) -> None:
    _require(isinstance(value, dict), "static closure report must be an object")
    expected_keys = {
        "schema", "record_id", "scope_id", "status", "static_policy", "selector_conditions",
        "target_kernel_pin", "known_reference_hashes", "dependencies", "validation",
        "authorization", "side_effects",
    }
    _require(set(value) == expected_keys, "static closure top-level schema drift")
    _require(value["schema"] == SCHEMA and value["record_id"] == RECORD_ID and value["scope_id"] == SCOPE_ID, "static closure identity drift")
    _require(value["status"] in {STATUS_MISSING_TARGET, STATUS_BOUND_TARGET}, "static closure status drift")

    baseline = deps["baseline"]
    expected_rows = _policy_rows(baseline)
    policy = value["static_policy"]
    _require(set(policy) == {"strategy", "default_action", "native_number_minimum", "native_number_maximum", "native_row_count", "rows_sha256", "rows"}, "static policy schema drift")
    _require(policy["strategy"] == "complete_native_default_deny_no_allowlist", "static policy strategy drift")
    _require(policy["default_action"] == "deny", "static policy default action drift")
    _require(policy["native_number_minimum"] == 0 and policy["native_number_maximum"] == 461 and policy["native_row_count"] == 462, "static policy native interval drift")
    _require(policy["rows"] == expected_rows, "static policy rows differ from the pinned baseline")
    _require(policy["rows_sha256"] == _rows_sha256(expected_rows), "static policy row digest drift")
    for row in policy["rows"]:
        _require(row["disposition"] == "deny_errno", f"row {row['syscall_number']} is not default-deny")
        _validate_predicate(row["predicate"], row["syscall_number"])

    _require(value["selector_conditions"] == _selector_conditions(), "selector condition contract drift")
    _validate_target_pins(value["target_kernel_pin"])
    expected_refs = _dependency_refs(deps)
    _require(value["dependencies"] == expected_refs, "dependency identity binding drift")

    known = value["known_reference_hashes"]
    expected_known = _known_reference_hashes(deps)
    _require(known == expected_known, "known reference hash inventory drift")
    for item in known["source_audit_file_hashes"]:
        _sha256(item["sha256"], f"known source audit hash {item['path']}")

    validation = value["validation"]
    _require(set(validation) == {"baseline_rows_bound", "native_rows_complete", "per_number_dispositions_complete", "per_number_predicates_complete", "selector_conditions_complete", "target_kernel_pin_complete", "runtime_conformance_verified", "fail_closed", "blockers"}, "validation schema drift")
    _require(validation["baseline_rows_bound"] is True and validation["native_rows_complete"] is True, "native baseline closure is incomplete")
    _require(validation["per_number_dispositions_complete"] is True and validation["per_number_predicates_complete"] is True, "per-number policy closure is incomplete")
    _require(validation["selector_conditions_complete"] is True and validation["runtime_conformance_verified"] is False and validation["fail_closed"] is True, "selector validation boundary drift")
    _require(validation["target_kernel_pin_complete"] is value["target_kernel_pin"]["external_verified"], "target pin validation mismatch")
    expected_blockers = [
        *( [] if value["target_kernel_pin"]["external_verified"] else ["external_target_kernel_source_config_uapi_build_pins_missing"] ),
        "ptrace_seccomp_order_runtime_conformance_missing",
        "x32_runtime_rejection_missing",
        "nr_minus_one_runtime_semantics_missing",
    ]
    _require(validation["blockers"] == expected_blockers, "static closure blocker inventory drift")
    _require(value["authorization"] == AUTHORIZATION, "authorization boundary drift")
    _require(value["side_effects"] == SIDE_EFFECTS, "side-effect boundary drift")
    expected_status = STATUS_BOUND_TARGET if value["target_kernel_pin"]["external_verified"] else STATUS_MISSING_TARGET
    _require(value["status"] == expected_status, "status does not match target-pin state")


def validate_report(value: Any) -> dict[str, Any]:
    deps = _load_dependencies()
    _validate_report_shape(value, deps)
    return value


def verify_output(path: str | Path = OUTPUT) -> dict[str, Any]:
    value, _ = _read_json(path, label="static closure report")
    validate_report(value)
    expected = build_report()
    if value != expected:
        raise StaticClosureError("checked-in static closure differs from the current bounded dependencies")
    return value


def write_output() -> Path:
    value = build_report()
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise StaticClosureError("static closure report exceeds the bounded JSON write limit")
    path = LAB / OUTPUT
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write while publishing static closure report")
            offset += written
        os.fsync(descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    else:
        os.close(descriptor)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="write the fixed static closure once")
    group.add_argument("--verify", action="store_true", help="verify the fixed static closure")
    group.add_argument("--print", dest="print_report", action="store_true", help="print the deterministic closure")
    args = parser.parse_args(argv)
    if args.write:
        print(write_output().relative_to(LAB))
        return 0
    if args.verify:
        value = verify_output()
    else:
        value = build_report()
    print(json.dumps({
        "schema": value["schema"],
        "status": value["status"],
        "native_row_count": value["static_policy"]["native_row_count"],
        "per_number_dispositions_complete": value["validation"]["per_number_dispositions_complete"],
        "per_number_predicates_complete": value["validation"]["per_number_predicates_complete"],
        "target_kernel_pin_complete": value["validation"]["target_kernel_pin_complete"],
        "runtime_conformance_verified": value["validation"]["runtime_conformance_verified"],
        "qualification_credit": value["authorization"]["qualification_credit"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
