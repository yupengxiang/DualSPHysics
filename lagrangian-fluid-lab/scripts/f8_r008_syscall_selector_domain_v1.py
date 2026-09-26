#!/usr/bin/env python3
"""Model a fail-closed x86-64 seccomp selector partition; never execute it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from scripts import f8_r008_syscall_universe_baseline_v1 as source_baseline

LAB = Path(__file__).resolve().parents[1]
OUTPUT = Path("reports/F8-R008-SYSCALL-SELECTOR-DOMAIN-V1.json")
SCHEMA = "core.cfd.f8.r008_syscall_selector_domain.v1"
RECORD_ID = "f8-r008-syscall-selector-domain-v1"
AUDIT_ARCH_X86_64 = 0xC000003E
AUDIT_ARCH_U32_MAX = (1 << 32) - 1
X32_SYSCALL_BIT = 0x40000000
RAW_NR_MIN = -(1 << 31)
RAW_NR_MAX = (1 << 31) - 1
MAX_ARTIFACT_BYTES = 256 * 1024


class SelectorDomainError(ValueError):
    """The selector domain or static partition manifest is malformed."""


def classify_selector(audit_arch: int, raw_nr: int) -> dict[str, Any]:
    """Return a static category and a deny requirement for one seccomp selector."""
    if type(audit_arch) is not int or not 0 <= audit_arch <= AUDIT_ARCH_U32_MAX:
        raise SelectorDomainError("audit_arch must be an exact unsigned 32-bit integer")
    if type(raw_nr) is not int or not RAW_NR_MIN <= raw_nr <= RAW_NR_MAX:
        raise SelectorDomainError("raw_nr must be an exact signed 32-bit integer")

    if audit_arch != AUDIT_ARCH_X86_64:
        return {
            "audit_arch": audit_arch,
            "raw_nr": raw_nr,
            "selector_class": "non_target_audit_arch",
            "required_action": "deny",
        }
    if raw_nr == -1:
        return {
            "audit_arch": audit_arch,
            "raw_nr": raw_nr,
            "selector_class": "minus_one_unattributed_skip_or_user_selector",
            "required_action": "deny_as_target_request_without_separate_trusted_tracer_state",
        }
    if raw_nr < 0:
        return {
            "audit_arch": audit_arch,
            "raw_nr": raw_nr,
            "selector_class": "negative_non_sentinel_raw_number",
            "required_action": "deny",
        }
    if raw_nr & X32_SYSCALL_BIT:
        return {
            "audit_arch": audit_arch,
            "raw_nr": raw_nr,
            "selector_class": "x32_tagged_raw_number",
            "required_action": "deny_x32_abi",
        }
    if raw_nr <= source_baseline.EXPECTED_NATIVE_MAX:
        return {
            "audit_arch": audit_arch,
            "raw_nr": raw_nr,
            "selector_class": "native_source_table_interval",
            "required_action": "deny_until_this_native_number_has_an_explicit_reviewed_policy",
        }
    return {
        "audit_arch": audit_arch,
        "raw_nr": raw_nr,
        "selector_class": "unlisted_non_x32_raw_number",
        "required_action": "deny",
    }


def build_manifest() -> dict[str, Any]:
    baseline = source_baseline.verify_output()
    universe = baseline["universe"]
    table_max = source_baseline.EXPECTED_NATIVE_MAX
    partition = [
        {
            "raw_nr_min": RAW_NR_MIN,
            "raw_nr_max": -2,
            "selector_class": "negative_non_sentinel_raw_number",
            "required_action": "deny",
        },
        {
            "raw_nr_min": -1,
            "raw_nr_max": -1,
            "selector_class": "minus_one_unattributed_skip_or_user_selector",
            "required_action": "deny_as_target_request_without_separate_trusted_tracer_state",
        },
        {
            "raw_nr_min": 0,
            "raw_nr_max": table_max,
            "selector_class": "native_source_table_interval",
            "count": table_max + 1,
            "source_table_holes": universe["hole_count"],
            "source_listed_entry_rows": universe["listed_entry_count"],
            "source_entryless_rows": len(universe["listed_without_entry_point_numbers"]),
            "per_number_dispositions_complete": False,
            "per_number_predicates_complete": False,
            "required_action": "deny_until_this_native_number_has_an_explicit_reviewed_policy",
        },
        {
            "raw_nr_min": table_max + 1,
            "raw_nr_max": X32_SYSCALL_BIT - 1,
            "selector_class": "unlisted_non_x32_raw_number",
            "required_action": "deny",
        },
        {
            "raw_nr_min": X32_SYSCALL_BIT,
            "raw_nr_max": RAW_NR_MAX,
            "selector_class": "x32_tagged_raw_number",
            "required_action": "deny_x32_abi",
        },
    ]
    cursor = RAW_NR_MIN
    for span in partition:
        if span["raw_nr_min"] != cursor or span["raw_nr_max"] < span["raw_nr_min"]:
            raise SelectorDomainError("raw syscall-number partition has a gap or overlap")
        cursor = span["raw_nr_max"] + 1
    if cursor != RAW_NR_MAX + 1:
        raise SelectorDomainError("raw syscall-number partition does not cover signed int32")

    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "static_selector_domain_partition_only_not_execution_policy",
        "source_baseline": {
            "record_id": baseline["record_id"],
            "upstream_ref": baseline["source"]["upstream_ref"],
            "upstream_table_sha256": baseline["source"]["sha256"],
            "native_rows_sha256": universe["rows_sha256"],
        },
        "selector_abi": {
            "seccomp_raw_nr_type": "signed_int32",
            "audit_arch_type": "unsigned_int32",
            "target_audit_arch_hex": f"0x{AUDIT_ARCH_X86_64:08x}",
            "x32_syscall_bit_hex": f"0x{X32_SYSCALL_BIT:08x}",
            "x32_table_dispatch_requires_config_x86_x32_abi": True,
            "x32_runtime_rejection_verified": False,
            "nr_minus_one_is_attributable_to_tracer_from_selector_alone": False,
        },
        "raw_nr_domain": {
            "minimum": RAW_NR_MIN,
            "maximum": RAW_NR_MAX,
            "partition_complete": True,
            "partition": partition,
        },
        "audit_arch_domain": {
            "minimum": 0,
            "maximum": AUDIT_ARCH_U32_MAX,
            "target_arch_value": AUDIT_ARCH_X86_64,
            "partition_complete": True,
            "target_arch_action": "classify raw_nr using the partition above",
            "all_other_arch_values_action": "deny",
        },
        "policy_state": {
            "all_unclassified_selectors_default_deny": True,
            "native_per_number_dispositions_complete": False,
            "native_per_number_predicates_complete": False,
            "target_kernel_build_pinned": False,
            "target_kernel_config_pinned": False,
            "ptrace_seccomp_order_conformance_passed": False,
            "syscall_runtime_conformance_passed": False,
            "execution_authority": False,
            "readiness_pass": False,
            "qualification_credit": 0,
        },
    }


def validate_manifest(value: Any) -> dict[str, Any]:
    expected = build_manifest()
    if not isinstance(value, dict) or value != expected:
        raise SelectorDomainError("selector-domain manifest differs from the pinned static partition")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SelectorDomainError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise SelectorDomainError(f"non-finite JSON constant is not permitted: {value}")


def verify_output() -> dict[str, Any]:
    path = LAB / OUTPUT
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_ARTIFACT_BYTES:
            raise SelectorDomainError("selector-domain artifact must be a bounded single-link regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(65536, MAX_ARTIFACT_BYTES + 1 - total))
            if not block:
                break
            total += len(block)
            if total > MAX_ARTIFACT_BYTES:
                raise SelectorDomainError("selector-domain artifact exceeds the fixed size bound")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns, item.st_nlink)
        if identity(before) != identity(after) or identity(after) != identity(named) or total != before.st_size:
            raise SelectorDomainError("selector-domain artifact changed while being read")
        try:
            value = json.loads(
                b"".join(chunks).decode("utf-8", errors="strict"),
                object_pairs_hook=_strict_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SelectorDomainError("selector-domain artifact is not strict UTF-8 JSON") from error
        return validate_manifest(value)
    except OSError as error:
        raise SelectorDomainError("could not safely open the fixed selector-domain artifact") from error
    finally:
        os.close(descriptor)


def write_output() -> Path:
    payload = (json.dumps(build_manifest(), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise SelectorDomainError("generated selector-domain artifact exceeds the fixed size bound")
    path = LAB / OUTPUT
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        0o644,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
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
    os.close(descriptor)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="create the fixed static manifest once")
    group.add_argument("--verify", action="store_true", help="verify the fixed static manifest")
    args = parser.parse_args()
    if args.write:
        print(write_output().relative_to(LAB))
        return 0
    value = verify_output()
    print(json.dumps({"schema": value["schema"], "status": value["status"], "partition_complete": value["raw_nr_domain"]["partition_complete"], "policy_state": value["policy_state"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
