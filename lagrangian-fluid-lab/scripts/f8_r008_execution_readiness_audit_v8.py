#!/usr/bin/env python3
"""Bind the static syscall-selector partition while retaining all R008 runtime blockers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f8_r008_execution_readiness_audit_v7 as predecessor
from scripts import f8_r008_syscall_selector_domain_v1 as selector_domain
from scripts import f8_r008_syscall_universe_baseline_v1 as syscall_baseline

ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
V7_RECEIPT = ROOT / "t1-execution-readiness-audit-v7/receipt.json"
OUTPUT = LAB / ROOT / "t1-execution-readiness-audit-v8/receipt.json"
SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v8"
RECORD_ID = "f8-r008-execution-readiness-audit-v8"
EXPECTED_V7_SHA256 = "bc0fd27b0414f7a57c792215ea14bc12888e455f988eccc9c9130b8d3a8de3e7"
EXPECTED_V7_GAPS = {
    "trusted_worker_execution_source_and_runtime_identity_missing",
    "real_provenance_verified_15_case_t1_results_missing",
    "native_integrity_and_solver_timestep_adjudication_missing",
    "terminal_fanotify_profiles_lack_pinned_kernel_runtime_conformance",
    "trusted_terminal_supervisor_and_final_fput_observer_missing",
}
NEW_EVIDENCE = (
    ("reports/F8-R008-SYSCALL-SELECTOR-DOMAIN-V1.json", "static signed-int32 selector-domain manifest"),
    ("scripts/f8_r008_syscall_selector_domain_v1.py", "selector-domain static verifier and writer"),
    ("tests/test_f8_r008_syscall_selector_domain_v1.py", "selector-domain static tests"),
    ("reports/F8-R008-SYSCALL-UNIVERSE-LINUX-V6.8-X86_64-BASELINE-V1.json", "upstream Linux v6.8 syscall-number inventory"),
    ("scripts/f8_r008_syscall_universe_baseline_v1.py", "syscall-number baseline verifier and writer"),
    ("tests/test_f8_r008_syscall_universe_baseline_v1.py", "syscall-number baseline tests"),
    ("reports/CORE-CONTINUATION-STATUS-2026-09-27-UPDATE-221.zh-CN.md", "source-pinned native syscall table inventory audit"),
    ("reports/CORE-CONTINUATION-STATUS-2026-09-27-UPDATE-222.zh-CN.md", "x86-64 seccomp selector ABI source audit"),
    ("reports/CORE-CONTINUATION-STATUS-2026-09-27-UPDATE-223.zh-CN.md", "review corrections to selector ABI source audit"),
    ("reports/CORE-CONTINUATION-STATUS-2026-09-27-UPDATE-225.zh-CN.md", "selector-domain implementation and review record"),
    ("scripts/f8_r008_execution_readiness_audit_v8.py", "this readiness audit implementation"),
    ("tests/test_f8_r008_execution_readiness_audit_v8.py", "this readiness audit tests"),
)
MAX_RECEIPT_BYTES = 32 * 1024 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class ReadinessAuditError(ValueError):
    """The versioned R008 syscall-domain readiness evidence is inconsistent."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReadinessAuditError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ReadinessAuditError(f"non-standard JSON constant is not permitted: {value}")


def _read_bounded(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    target = Path(path)
    raw_path = str(target)
    if target.is_absolute():
        if target.as_posix() != raw_path or any(part in {"", ".", ".."} for part in target.parts):
            raise ReadinessAuditError("absolute receipt path must be canonical")
        root = Path("/")
        parts = target.parts[1:]
        display = target.as_posix()
    else:
        if target.as_posix() != raw_path or not target.parts or any(part in {"", ".", ".."} for part in target.parts):
            raise ReadinessAuditError("receipt path must be canonical and contained")
        root = LAB
        parts = target.parts
        display = target.as_posix()
    if not parts:
        raise ReadinessAuditError("receipt path must name a regular file")

    opened: list[int] = []
    try:
        parent_fd = os.open(root, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        opened.append(parent_fd)
        for component in parts[:-1]:
            parent_fd = os.open(component, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
            opened.append(parent_fd)
        descriptor = os.open(parts[-1], os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
        opened.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReadinessAuditError("receipt must be a single-link regular file")
        if before.st_size > MAX_RECEIPT_BYTES:
            raise ReadinessAuditError("receipt exceeds the fixed 32 MiB read limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, MAX_RECEIPT_BYTES + 1 - total))
            if not block:
                break
            total += len(block)
            if total > MAX_RECEIPT_BYTES:
                raise ReadinessAuditError("receipt exceeds the fixed 32 MiB read limit")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        identity = lambda item: (
            item.st_dev, item.st_ino, item.st_mode, item.st_size,
            item.st_mtime_ns, item.st_ctime_ns, item.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or total != before.st_size:
            raise ReadinessAuditError("receipt changed while being read")
        payload = b"".join(chunks)
        return payload, {"path": display, "bytes": total, "sha256": hashlib.sha256(payload).hexdigest()}
    except OSError as error:
        raise ReadinessAuditError(f"could not safely read readiness receipt: {display}") from error
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _read_json(relative: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, ref = predecessor._read_beneath_lab(relative)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessAuditError(f"evidence is not strict UTF-8 JSON: {relative}") from error
    if not isinstance(value, dict):
        raise ReadinessAuditError(f"evidence must be a JSON object: {relative}")
    return value, ref


def _add_evidence(inventory: dict[str, dict[str, Any]], path: str, role: str) -> None:
    _, reference = predecessor._read_beneath_lab(path)
    if path in inventory:
        current = inventory[path]
        if current["sha256"] != reference["sha256"] or current["bytes"] != reference["bytes"]:
            raise ReadinessAuditError(f"evidence path has conflicting bindings: {path}")
        current["role"] += f" | {role}"
        return
    inventory[path] = {**reference, "role": role}


def build_audit() -> dict[str, Any]:
    prior = predecessor.verify_audit()
    if set(item.get("code") for item in prior["blocking_gaps"] if isinstance(item, dict)) != EXPECTED_V7_GAPS:
        raise ReadinessAuditError("historical readiness v7 blocker inventory changed")
    if not (
        prior.get("readiness_pass") is False
        and prior.get("full_t1_decision") is False
        and prior.get("T1_numerical") is False
        and prior.get("execution_authority", {}).get("solver") is False
        and type(prior.get("qualification_credit")) is int
        and prior["qualification_credit"] == 0
    ):
        raise ReadinessAuditError("historical readiness v7 must retain its zero-credit execution hold")

    _, prior_ref = _read_json(V7_RECEIPT.as_posix())
    if prior_ref["sha256"] != EXPECTED_V7_SHA256:
        raise ReadinessAuditError("historical readiness v7 receipt differs from the fixed source binding")

    baseline = syscall_baseline.verify_output()
    selector = selector_domain.verify_output()
    native_span = selector["raw_nr_domain"]["partition"][2]
    expected_selector_state = {
        "partition_complete": True,
        "native_count": 462,
        "per_number_dispositions_complete": False,
        "per_number_predicates_complete": False,
        "all_unclassified_selectors_default_deny": True,
        "target_kernel_build_pinned": False,
        "target_kernel_config_pinned": False,
        "ptrace_seccomp_order_conformance_passed": False,
        "syscall_runtime_conformance_passed": False,
        "execution_authority": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }
    observed_selector_state = {
        "partition_complete": selector["raw_nr_domain"]["partition_complete"],
        "native_count": native_span["count"],
        "per_number_dispositions_complete": native_span["per_number_dispositions_complete"],
        "per_number_predicates_complete": native_span["per_number_predicates_complete"],
        "all_unclassified_selectors_default_deny": selector["policy_state"]["all_unclassified_selectors_default_deny"],
        "target_kernel_build_pinned": selector["policy_state"]["target_kernel_build_pinned"],
        "target_kernel_config_pinned": selector["policy_state"]["target_kernel_config_pinned"],
        "ptrace_seccomp_order_conformance_passed": selector["policy_state"]["ptrace_seccomp_order_conformance_passed"],
        "syscall_runtime_conformance_passed": selector["policy_state"]["syscall_runtime_conformance_passed"],
        "execution_authority": selector["policy_state"]["execution_authority"],
        "readiness_pass": selector["policy_state"]["readiness_pass"],
        "qualification_credit": selector["policy_state"]["qualification_credit"],
    }
    if observed_selector_state != expected_selector_state:
        raise ReadinessAuditError("selector-domain manifest does not retain the required static-only holds")
    if selector["source_baseline"]["record_id"] != baseline["record_id"]:
        raise ReadinessAuditError("selector-domain manifest is not bound to the verified syscall baseline")
    if baseline["universe"]["row_count"] != 462 or baseline["universe"]["rows_sha256"] != selector["source_baseline"]["native_rows_sha256"]:
        raise ReadinessAuditError("selector-domain native range differs from the verified upstream inventory")

    inventory: dict[str, dict[str, Any]] = {}
    for item in prior["evidence"]:
        path = item["path"]
        _, current = predecessor._read_beneath_lab(path)
        if current["sha256"] != item["sha256"] or current["bytes"] != item["bytes"]:
            raise ReadinessAuditError(f"transitive v7 evidence binding is stale: {path}")
        _add_evidence(inventory, path, f"transitive_v7:{item['role']}")
    _add_evidence(inventory, V7_RECEIPT.as_posix(), "immutable historical readiness v7 receipt")
    for path, role in NEW_EVIDENCE:
        _add_evidence(inventory, path, role)

    gaps = list(prior["blocking_gaps"])
    gaps.extend([
        {
            "code": "native_syscall_per_number_policy_and_target_pin_missing",
            "severity": "high",
            "detail": "The signed-int32 selector domain and Linux v6.8 upstream inventory are statically bound, but all 462 native numbers still lack reviewed per-number dispositions/predicates and the target kernel build/config is not pinned.",
        },
        {
            "code": "ptrace_seccomp_selector_runtime_conformance_missing",
            "severity": "high",
            "detail": "The target-kernel behavior for x32 rejection, nr=-1 handling, and ptrace/seccomp ordering has not been verified; the selector manifest is not an executable policy.",
        },
    ])
    evidence = sorted(inventory.values(), key=lambda item: item["path"])
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008",
        "status": "static_selector_domain_bound_full_runtime_readiness_blocked",
        "supersedes": {
            "path": V7_RECEIPT.as_posix(),
            "sha256": prior_ref["sha256"],
            "reason": "V8 adds a verified complete raw selector-domain partition and its upstream number-universe binding; it does not complete the native per-number policy or any runtime gate.",
        },
        "predecessor_v7": {
            "receipt_preserved": True,
            "receipt_integrity": "source_bound_evidence_reverified",
            "readiness_pass": False,
            "qualification_credit": 0,
        },
        "selector_domain": {
            "manifest_record_id": selector["record_id"],
            "manifest_status": selector["status"],
            "raw_nr_partition_complete": True,
            "raw_nr_minimum": selector["raw_nr_domain"]["minimum"],
            "raw_nr_maximum": selector["raw_nr_domain"]["maximum"],
            "target_audit_arch_hex": selector["selector_abi"]["target_audit_arch_hex"],
            "x32_syscall_bit_hex": selector["selector_abi"]["x32_syscall_bit_hex"],
            "x32_runtime_rejection_verified": selector["selector_abi"]["x32_runtime_rejection_verified"],
            "nr_minus_one_is_attributable_to_tracer_from_selector_alone": selector["selector_abi"]["nr_minus_one_is_attributable_to_tracer_from_selector_alone"],
            "native_table_rows": native_span["count"],
            "native_per_number_dispositions_complete": False,
            "native_per_number_predicates_complete": False,
            "target_kernel_build_pinned": False,
            "target_kernel_config_pinned": False,
            "ptrace_seccomp_order_conformance_passed": False,
            "runtime_conformance_passed": False,
        },
        "execution_authority": {
            "solver": False,
            "worker": False,
            "gpu": False,
            "queue": False,
            "root_or_capability_probe": False,
            "fanotify_init_or_mark": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "execution_controls": {
            "solver_invoked": False,
            "worker_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "root_or_capability_probe": False,
            "fanotify_init_or_mark": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "native_integrity_adjudicated": False,
        "solver_timestep_audit_adjudicated": False,
        "readiness_pass": False,
        "full_t1_decision": False,
        "T1_numerical": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "blocking_gaps": gaps,
        "evidence": evidence,
        "implementation": {
            "path": "scripts/f8_r008_execution_readiness_audit_v8.py",
            **predecessor._read_regular("scripts/f8_r008_execution_readiness_audit_v8.py")[1],
        },
        "test": {
            "path": "tests/test_f8_r008_execution_readiness_audit_v8.py",
            **predecessor._read_regular("tests/test_f8_r008_execution_readiness_audit_v8.py")[1],
        },
    }


def _load_receipt(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, ref = _read_bounded(path)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessAuditError("R008 readiness v8 receipt is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ReadinessAuditError("R008 readiness v8 receipt must be a JSON object")
    return value, ref


def verify_audit(path: str | Path = OUTPUT) -> dict[str, Any]:
    receipt, _ = _load_receipt(path)
    expected = build_audit()
    if receipt.get("schema") != SCHEMA or receipt != expected:
        raise ReadinessAuditError("R008 execution-readiness audit v8 no longer matches its pinned evidence")
    return receipt


def _write_new_file_at(parent_fd: int, name: str, payload: bytes) -> None:
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644, dir_fd=parent_fd)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write while creating immutable v8 receipt")
            offset += written
        os.fsync(descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise
    else:
        os.close(descriptor)
        os.fsync(parent_fd)


def write_audit() -> Path:
    relative = OUTPUT.relative_to(LAB)
    payload = (json.dumps(build_audit(), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_RECEIPT_BYTES:
        raise ReadinessAuditError("R008 readiness v8 receipt exceeds its fixed size cap")
    opened: list[int] = []
    try:
        parent_fd = os.open(LAB, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        opened.append(parent_fd)
        for component in relative.parts[:-1]:
            try:
                os.mkdir(component, 0o755, dir_fd=parent_fd)
            except FileExistsError:
                pass
            parent_fd = os.open(component, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
            opened.append(parent_fd)
        _write_new_file_at(parent_fd, relative.parts[-1], payload)
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
    return OUTPUT


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="write the immutable R008 readiness v8 receipt once")
    group.add_argument("--verify", action="store_true", help="verify the fixed R008 readiness v8 receipt")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_audit().relative_to(LAB))
    else:
        result = verify_audit() if arguments.verify else build_audit()
        print(json.dumps({key: result[key] for key in ("schema", "status", "readiness_pass", "T1_numerical", "qualification_credit", "blocking_gaps")}, indent=2))
