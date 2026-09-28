#!/usr/bin/env python3
"""Validate a non-authoritative F8/R008 per-number syscall policy contract.

This module validates only static structure and immutable source bindings.  It
does not inspect the host kernel, execute a selector, attach a tracer, or mint
any execution/readiness capability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f8_r008_syscall_selector_domain_v1 as selector_domain
from scripts import f8_r008_syscall_universe_baseline_v1 as source_baseline


OUTPUT = Path("reports/F8-R008-SYSCALL-POLICY-CONTRACT-V1.json")
SOURCE_AUDIT = Path("reports/F8-R008-FINAL-FPUT-LINUX-V6.8-SOURCE-AUDIT-V1.json")
SCHEMA = "core.cfd.f8.r008_syscall_policy_contract.v1"
RECORD_ID = "f8-r008-syscall-policy-contract-v1"
STATUS = "static_contract_only_not_target_runtime_or_execution_policy"
CONTRACT_STATES = {
    "incomplete_static_template",
    "complete_static_contract_not_runtime_verified",
}
DISPOSITIONS = {
    "broker_emulated",
    "deny_errno",
    "static_allow_nonmutating",
    "allow_nonoutput_proven",
}
PREDICATE_LANGUAGE = "static-reviewed-predicate-v1"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_RELATIVE_REF = re.compile(r"[A-Za-z0-9_./:-]{1,512}\Z")
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class SyscallPolicyContractError(ValueError):
    """The static per-number policy contract is malformed or inconsistent."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SyscallPolicyContractError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> Any:
    raise SyscallPolicyContractError(f"non-standard JSON constant is not permitted: {token}")


def _read_bounded(path: Path) -> tuple[bytes, dict[str, Any]]:
    descriptor = os.open(path, os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SyscallPolicyContractError("contract input must be a single-link regular file")
        if before.st_size > MAX_ARTIFACT_BYTES:
            raise SyscallPolicyContractError("contract input exceeds the fixed size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, MAX_ARTIFACT_BYTES + 1 - total))
            if not block:
                break
            total += len(block)
            if total > MAX_ARTIFACT_BYTES:
                raise SyscallPolicyContractError("contract input exceeds the fixed size limit")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        identity = lambda item: (
            item.st_dev,
            item.st_ino,
            item.st_mode,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
            item.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or total != before.st_size:
            raise SyscallPolicyContractError("contract input changed while being read")
        payload = b"".join(chunks)
        return payload, {"bytes": total, "sha256": hashlib.sha256(payload).hexdigest()}
    except OSError as error:
        raise SyscallPolicyContractError(f"could not safely read contract input: {path}") from error
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = _read_bounded(path)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyscallPolicyContractError(f"contract input is not strict UTF-8 JSON: {path}") from error
    if not isinstance(value, dict):
        raise SyscallPolicyContractError(f"contract input must be a JSON object: {path}")
    return value, reference


def _artifact_reference(relative: Path) -> dict[str, Any]:
    value, reference = _read_json(LAB / relative)
    return {"path": relative.as_posix(), "bytes": reference["bytes"], "sha256": reference["sha256"], "value": value}


def _validate_source_audit(value: dict[str, Any]) -> None:
    if value.get("schema") != "core.cfd.f8.r008_final_fput_linux_v6_8_source_audit.v1":
        raise SyscallPolicyContractError("source audit schema is not the pinned Linux v6.8 static audit")
    if value.get("status") != "upstream_static_source_audit_only":
        raise SyscallPolicyContractError("source audit must remain upstream-static-only")
    source = value.get("source")
    if not isinstance(source, dict) or source.get("repository") != "https://github.com/torvalds/linux" or source.get("tag") != "v6.8":
        raise SyscallPolicyContractError("source audit Linux v6.8 binding is malformed")
    if source.get("target_kernel_source_pinned") is not False or source.get("tag_signature_verified") is not False:
        raise SyscallPolicyContractError("source audit must not claim target-kernel or signature verification")
    authorization = value.get("authorization_and_readiness")
    if not isinstance(authorization, dict) or authorization != {
        "runtime_or_capability_probe_performed": False,
        "privileged_action_performed": False,
        "production_data_read": False,
        "native_build_or_worker_started": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "execution_authority": False,
        "qualification_credit": 0,
    }:
        raise SyscallPolicyContractError("source audit authorization/readiness boundary changed")


def _static_bindings() -> dict[str, Any]:
    baseline = source_baseline.verify_output()
    selector = selector_domain.verify_output()
    baseline_ref = _artifact_reference(source_baseline.OUTPUT)
    selector_ref = _artifact_reference(selector_domain.OUTPUT)
    source_audit, source_audit_ref = _read_json(LAB / SOURCE_AUDIT)
    _validate_source_audit(source_audit)
    native_span = selector["raw_nr_domain"]["partition"][2]
    if native_span.get("count") != source_baseline.EXPECTED_NATIVE_MAX + 1:
        raise SyscallPolicyContractError("selector native span is not the pinned 462-number interval")
    if selector["raw_nr_domain"].get("partition_complete") is not True:
        raise SyscallPolicyContractError("selector signed-int32 partition is not complete")
    return {
        "source_baseline": {
            "path": baseline_ref["path"],
            "artifact_bytes": baseline_ref["bytes"],
            "artifact_sha256": baseline_ref["sha256"],
            "record_id": baseline["record_id"],
            "upstream_ref": baseline["source"]["upstream_ref"],
            "upstream_table_sha256": baseline["source"]["sha256"],
            "native_rows_sha256": baseline["universe"]["rows_sha256"],
            "row_count": baseline["universe"]["row_count"],
        },
        "selector_domain": {
            "path": selector_ref["path"],
            "artifact_bytes": selector_ref["bytes"],
            "artifact_sha256": selector_ref["sha256"],
            "record_id": selector["record_id"],
            "schema": selector["schema"],
            "raw_nr_minimum": selector["raw_nr_domain"]["minimum"],
            "raw_nr_maximum": selector["raw_nr_domain"]["maximum"],
            "raw_nr_partition_complete": selector["raw_nr_domain"]["partition_complete"],
            "target_audit_arch_hex": selector["selector_abi"]["target_audit_arch_hex"],
            "x32_syscall_bit_hex": selector["selector_abi"]["x32_syscall_bit_hex"],
        },
        "source_audit": {
            "path": SOURCE_AUDIT.as_posix(),
            "artifact_bytes": source_audit_ref["bytes"],
            "artifact_sha256": source_audit_ref["sha256"],
            "schema": source_audit["schema"],
            "upstream_ref": source_audit["source"]["tag"],
            "target_kernel_source_pinned": source_audit["source"]["target_kernel_source_pinned"],
            "runtime_or_capability_probe_performed": source_audit["authorization_and_readiness"]["runtime_or_capability_probe_performed"],
        },
    }


def _empty_kernel_pin() -> dict[str, Any]:
    return {
        "pin_status": "missing",
        "release": None,
        "source_commit": None,
        "source_tree_sha256": None,
        "uapi_sha256": None,
        "build_id": None,
    }


def _empty_config_pin() -> dict[str, Any]:
    return {
        "pin_status": "missing",
        "config_ref": None,
        "config_sha256": None,
        "required_options": [],
    }


def _baseline_rows() -> list[dict[str, Any]]:
    baseline = source_baseline.verify_output()
    rows: list[dict[str, Any]] = []
    for row in baseline["universe"]["rows"]:
        rows.append({
            "syscall_number": row["syscall_number"],
            "number_state": row["number_state"],
            "abi": row["abi"],
            "name": row["name"],
            "entry_point": row["entry_point"],
            "disposition": None,
            "predicate": None,
        })
    return rows


def build_template() -> dict[str, Any]:
    rows = _baseline_rows()
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": STATUS,
        "contract_state": "incomplete_static_template",
        "bindings": _static_bindings(),
        "target_kernel": _empty_kernel_pin(),
        "target_kernel_config": _empty_config_pin(),
        "policy": {
            "default_action": "deny",
            "rows": rows,
            "row_count": len(rows),
        },
        "policy_state": {
            "per_number_dispositions_complete": False,
            "per_number_predicates_complete": False,
            "unclassified_rows": len(rows),
            "target_kernel_build_pinned": False,
            "target_kernel_config_pinned": False,
            "runtime_conformance_verified": False,
            "execution_authority": False,
            "readiness_pass": False,
            "T1_numerical": False,
            "qualification_credit": 0,
        },
        "authorization": {
            "diagnostic_only": True,
            "capability_minted": False,
            "formal_admission": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
    }


def _require_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise SyscallPolicyContractError(f"{label} schema is malformed")


def _validate_reference(value: Any, label: str) -> None:
    if not isinstance(value, str) or not SAFE_RELATIVE_REF.fullmatch(value) or value.startswith("/") or ".." in value.split("/"):
        raise SyscallPolicyContractError(f"{label} must be a canonical relative reference")


def _validate_predicate(value: Any) -> bool:
    if value is None:
        return False
    _require_keys(value, {"language", "expression", "source_refs"}, "predicate")
    if value["language"] != PREDICATE_LANGUAGE:
        raise SyscallPolicyContractError("predicate language is not the fixed static-reviewed language")
    expression = value["expression"]
    if not isinstance(expression, str) or not 1 <= len(expression) <= 4096 or "\x00" in expression or "*" in expression:
        raise SyscallPolicyContractError("predicate expression must be bounded and must not use wildcards")
    if expression.strip().lower() in {"any", "unknown", "unknown-safe", "wildcard"}:
        raise SyscallPolicyContractError("predicate expression must be explicit, not a wildcard/unknown label")
    refs = value["source_refs"]
    if not isinstance(refs, list) or not 1 <= len(refs) <= 16 or refs != sorted(refs) or len(set(refs)) != len(refs):
        raise SyscallPolicyContractError("predicate source_refs must be sorted, unique, and non-empty")
    for ref in refs:
        _validate_reference(ref, "predicate source reference")
    return True


def _validate_kernel_pin(value: Any) -> bool:
    _require_keys(value, {"pin_status", "release", "source_commit", "source_tree_sha256", "uapi_sha256", "build_id"}, "target kernel pin")
    if value["pin_status"] == "missing":
        if any(value[key] is not None for key in ("release", "source_commit", "source_tree_sha256", "uapi_sha256", "build_id")):
            raise SyscallPolicyContractError("missing target-kernel pin must not contain partial identity")
        return False
    if value["pin_status"] != "declared_static_pin":
        raise SyscallPolicyContractError("target-kernel pin status is not recognized")
    if not isinstance(value["release"], str) or not 1 <= len(value["release"]) <= 128 or any(char.isspace() for char in value["release"]):
        raise SyscallPolicyContractError("target-kernel release identity is malformed")
    if not isinstance(value["source_commit"], str) or not HEX40.fullmatch(value["source_commit"]):
        raise SyscallPolicyContractError("target-kernel source commit must be a lowercase 40-hex digest")
    for key in ("source_tree_sha256", "uapi_sha256"):
        if not isinstance(value[key], str) or not HEX64.fullmatch(value[key]):
            raise SyscallPolicyContractError(f"target-kernel {key} must be a lowercase SHA-256")
    if not isinstance(value["build_id"], str) or not 1 <= len(value["build_id"]) <= 256 or "\x00" in value["build_id"]:
        raise SyscallPolicyContractError("target-kernel build_id is malformed")
    return True


def _validate_config_pin(value: Any) -> bool:
    _require_keys(value, {"pin_status", "config_ref", "config_sha256", "required_options"}, "target kernel config pin")
    if value["pin_status"] == "missing":
        if value["config_ref"] is not None or value["config_sha256"] is not None or value["required_options"] != []:
            raise SyscallPolicyContractError("missing target-config pin must not contain partial identity")
        return False
    if value["pin_status"] != "declared_static_pin":
        raise SyscallPolicyContractError("target-config pin status is not recognized")
    _validate_reference(value["config_ref"], "target-config reference")
    if not isinstance(value["config_sha256"], str) or not HEX64.fullmatch(value["config_sha256"]):
        raise SyscallPolicyContractError("target-config hash must be a lowercase SHA-256")
    options = value["required_options"]
    if not isinstance(options, list) or not options:
        raise SyscallPolicyContractError("target-config pin must enumerate relevant options")
    names: list[str] = []
    for option in options:
        _require_keys(option, {"name", "value"}, "target-config option")
        if not isinstance(option["name"], str) or not re.fullmatch(r"CONFIG_[A-Z0-9_]+", option["name"]):
            raise SyscallPolicyContractError("target-config option name is malformed")
        if option["value"] not in {"y", "m", "n"}:
            raise SyscallPolicyContractError("target-config option value must be y, m, or n")
        names.append(option["name"])
    if names != sorted(names) or len(set(names)) != len(names) or "CONFIG_X86_X32_ABI" not in names:
        raise SyscallPolicyContractError("target-config pin must sort unique options and include CONFIG_X86_X32_ABI")
    return True


def _derive_policy_state(value: dict[str, Any]) -> dict[str, Any]:
    rows = value["policy"]["rows"]
    dispositions_complete = all(row["disposition"] in DISPOSITIONS for row in rows)
    predicates_complete = all(row["predicate"] is not None for row in rows)
    kernel_pinned = _validate_kernel_pin(value["target_kernel"])
    config_pinned = _validate_config_pin(value["target_kernel_config"])
    unclassified = sum(row["disposition"] is None or row["predicate"] is None for row in rows)
    return {
        "per_number_dispositions_complete": dispositions_complete,
        "per_number_predicates_complete": predicates_complete,
        "unclassified_rows": unclassified,
        "target_kernel_build_pinned": kernel_pinned,
        "target_kernel_config_pinned": config_pinned,
        "runtime_conformance_verified": False,
        "execution_authority": False,
        "readiness_pass": False,
        "T1_numerical": False,
        "qualification_credit": 0,
    }


def _expected_static_state(value: dict[str, Any]) -> str:
    state = _derive_policy_state(value)
    if all((state["per_number_dispositions_complete"], state["per_number_predicates_complete"], state["target_kernel_build_pinned"], state["target_kernel_config_pinned"])):
        return "complete_static_contract_not_runtime_verified"
    return "incomplete_static_template"


def validate_contract(value: Any) -> dict[str, Any]:
    _require_keys(
        value,
        {"schema", "record_id", "status", "contract_state", "bindings", "target_kernel", "target_kernel_config", "policy", "policy_state", "authorization"},
        "top-level contract",
    )
    if value["schema"] != SCHEMA or value["record_id"] != RECORD_ID or value["status"] != STATUS:
        raise SyscallPolicyContractError("contract identity or non-authoritative status is malformed")
    if value["contract_state"] not in CONTRACT_STATES:
        raise SyscallPolicyContractError("contract state is not recognized")

    expected_bindings = _static_bindings()
    if value["bindings"] != expected_bindings:
        raise SyscallPolicyContractError("source baseline, selector, or source-audit binding differs from current pinned evidence")

    _validate_kernel_pin(value["target_kernel"])
    _validate_config_pin(value["target_kernel_config"])

    _require_keys(value["policy"], {"default_action", "rows", "row_count"}, "policy")
    if value["policy"]["default_action"] != "deny":
        raise SyscallPolicyContractError("policy default action must be deny")
    rows = value["policy"]["rows"]
    if not isinstance(rows, list) or value["policy"]["row_count"] != source_baseline.EXPECTED_NATIVE_MAX + 1 or len(rows) != value["policy"]["row_count"]:
        raise SyscallPolicyContractError("policy must contain all 462 native numbers")
    baseline_rows = _baseline_rows()
    row_keys = {"syscall_number", "number_state", "abi", "name", "entry_point", "disposition", "predicate"}
    for expected_number, (row, baseline_row) in enumerate(zip(rows, baseline_rows)):
        _require_keys(row, row_keys, "policy row")
        for key in ("syscall_number", "number_state", "abi", "name", "entry_point"):
            if row[key] != baseline_row[key]:
                raise SyscallPolicyContractError(f"policy row {expected_number} does not match source inventory")
        if row["disposition"] is not None and row["disposition"] not in DISPOSITIONS:
            raise SyscallPolicyContractError(f"policy row {expected_number} has an unknown disposition")
        _validate_predicate(row["predicate"])
        if row["number_state"] == "unassigned_hole" and row["disposition"] not in {None, "deny_errno"}:
            raise SyscallPolicyContractError("unassigned holes may only remain unclassified or be denied")

    expected_policy_state = _derive_policy_state(value)
    _require_keys(value["policy_state"], set(expected_policy_state), "policy state")
    if value["policy_state"] != expected_policy_state:
        raise SyscallPolicyContractError("policy-state completeness flags do not match the rows and pins")
    expected_contract_state = _expected_static_state(value)
    if value["contract_state"] != expected_contract_state:
        raise SyscallPolicyContractError("contract state does not match policy/pin completeness")

    expected_authorization = {
        "diagnostic_only": True,
        "capability_minted": False,
        "formal_admission": False,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
    }
    _require_keys(value["authorization"], set(expected_authorization), "authorization boundary")
    if value["authorization"] != expected_authorization:
        raise SyscallPolicyContractError("contract cannot mint execution, readiness, or qualification capability")
    return value


def verify_output(path: str | Path = OUTPUT) -> dict[str, Any]:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    value, _ = _read_json(target)
    return validate_contract(value)


def write_output() -> Path:
    payload = (json.dumps(build_template(), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise SyscallPolicyContractError("generated contract exceeds the fixed size limit")
    path = LAB / OUTPUT
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write while creating policy contract")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="write the non-authoritative 462-row template once")
    group.add_argument("--verify", nargs="?", const=OUTPUT.as_posix(), metavar="PATH", help="verify the fixed template or a supplied static contract")
    group.add_argument("--print-template", action="store_true", help="print the non-authoritative template without writing it")
    args = parser.parse_args()
    if args.write:
        print(write_output().relative_to(LAB))
        return 0
    if args.print_template:
        print(json.dumps(build_template(), indent=2, sort_keys=True, allow_nan=False))
        return 0
    value = verify_output(args.verify)
    state = value["policy_state"]
    print(json.dumps({
        "schema": value["schema"],
        "contract_state": value["contract_state"],
        "native_row_count": value["policy"]["row_count"],
        "per_number_dispositions_complete": state["per_number_dispositions_complete"],
        "per_number_predicates_complete": state["per_number_predicates_complete"],
        "target_kernel_build_pinned": state["target_kernel_build_pinned"],
        "target_kernel_config_pinned": state["target_kernel_config_pinned"],
        "readiness_pass": state["readiness_pass"],
        "qualification_credit": state["qualification_credit"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
