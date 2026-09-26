#!/usr/bin/env python3
"""Build a non-authoritative x86-64 syscall-number baseline from pinned Linux v6.8 source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

LAB = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://github.com/torvalds/linux/blob/v6.8/arch/x86/entry/syscalls/syscall_64.tbl"
SOURCE_SHA256 = "4c30abea9a4b69f3409bea7a0c910a8c8feb9a44b22a448b5c82f2bfdd8249c8"
EXPECTED_ROWS_SHA256 = "b1f28269d2ea1c72f6a0899b77c801f665360309309b7d8a819768d1841e85d7"
SOURCE_PATH = "arch/x86/entry/syscalls/syscall_64.tbl"
EXPECTED_NATIVE_MAX = 461
EXPECTED_X32_RANGE = tuple(range(512, 548))
OUTPUT = Path("reports/F8-R008-SYSCALL-UNIVERSE-LINUX-V6.8-X86_64-BASELINE-V1.json")
MAX_SOURCE_BYTES = 256 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class SyscallUniverseError(ValueError):
    """The pinned syscall table or derived number universe is malformed."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SyscallUniverseError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(token: str) -> Any:
    raise SyscallUniverseError(f"non-finite JSON constant is not permitted: {token}")


def _decode_strict_json(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SyscallUniverseError("generated baseline is not strict UTF-8 JSON") from error


def parse_table_rows(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_SOURCE_BYTES:
        raise SyscallUniverseError("upstream syscall table exceeds the fixed input bound")
    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError as error:
        raise SyscallUniverseError("upstream syscall table must be strict ASCII") from error

    native: dict[int, dict[str, Any]] = {}
    x32: dict[int, dict[str, Any]] = {}
    for line_number, source_line in enumerate(text.splitlines(), start=1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) not in {3, 4}:
            raise SyscallUniverseError(f"malformed syscall table row at line {line_number}")
        number_text, abi, name = fields[:3]
        entry_point = fields[3] if len(fields) == 4 else None
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)", number_text):
            raise SyscallUniverseError(f"invalid syscall number at line {line_number}")
        if abi not in {"common", "64", "x32"}:
            raise SyscallUniverseError(f"unsupported ABI tag at line {line_number}: {abi}")
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise SyscallUniverseError(f"invalid syscall name at line {line_number}")
        if entry_point is not None and not re.fullmatch(r"[A-Za-z0-9_]+", entry_point):
            raise SyscallUniverseError(f"invalid syscall entry point at line {line_number}")
        number = int(number_text)
        row = {
            "syscall_number": number,
            "abi": abi,
            "name": name,
            "entry_point": entry_point,
        }
        destination = x32 if abi == "x32" else native
        if number in destination:
            raise SyscallUniverseError(f"duplicate syscall number in ABI universe: {number}")
        destination[number] = row
    if not native:
        raise SyscallUniverseError("source contains no native x86-64 syscall rows")
    return {"native_rows": native, "x32_rows": x32}


def build_baseline(raw: bytes) -> dict[str, Any]:
    source_sha = hashlib.sha256(raw).hexdigest()
    if source_sha != SOURCE_SHA256:
        raise SyscallUniverseError("input bytes do not match the pinned upstream Linux v6.8 table SHA-256")
    parsed = parse_table_rows(raw)
    native: dict[int, dict[str, Any]] = parsed["native_rows"]
    x32: dict[int, dict[str, Any]] = parsed["x32_rows"]
    if max(native) != EXPECTED_NATIVE_MAX:
        raise SyscallUniverseError("pinned source native x86-64 maximum differs from the frozen v1 expectation")
    if tuple(sorted(x32)) != EXPECTED_X32_RANGE:
        raise SyscallUniverseError("pinned source x32 range differs from the frozen v1 expectation")

    rows: list[dict[str, Any]] = []
    holes: list[int] = []
    listed_without_entry: list[int] = []
    for number in range(EXPECTED_NATIVE_MAX + 1):
        source_row = native.get(number)
        if source_row is None:
            holes.append(number)
            rows.append({
                "syscall_number": number,
                "number_state": "unassigned_hole",
                "abi": None,
                "name": None,
                "entry_point": None,
                "disposition": None,
                "predicate": None,
            })
            continue
        if source_row["entry_point"] is None:
            listed_without_entry.append(number)
        rows.append({
            "syscall_number": number,
            "number_state": "listed_without_entry_point" if source_row["entry_point"] is None else "listed_entry",
            "abi": source_row["abi"],
            "name": source_row["name"],
            "entry_point": source_row["entry_point"],
            "disposition": None,
            "predicate": None,
        })

    canonical_rows = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    rows_digest = hashlib.sha256(canonical_rows).hexdigest()
    if rows_digest != EXPECTED_ROWS_SHA256:
        raise SyscallUniverseError("parsed rows differ from the independently pinned upstream-derived digest")
    x32_numbers = sorted(x32)
    canonical_x32 = json.dumps(x32_numbers, separators=(",", ":")).encode("ascii")
    return {
        "schema": "core.cfd.f8.r008_syscall_number_universe_baseline.v1",
        "record_id": "f8-r008-syscall-universe-linux-v6.8-x86_64-baseline-v1",
        "status": "upstream_reference_inventory_only_not_target_kernel_or_execution_policy",
        "architecture": {
            "native_abi": "x86_64",
            "audit_arch_hex": "0xc000003e",
            "native_number_minimum": 0,
            "native_number_maximum": EXPECTED_NATIVE_MAX,
            "native_number_count": EXPECTED_NATIVE_MAX + 1,
        },
        "source": {
            "upstream_ref": "v6.8",
            "path": SOURCE_PATH,
            "url": SOURCE_URL,
            "sha256": source_sha,
            "table_format": "<number> <abi> <name> [<entry-point>]",
            "native_abi_tags_included": ["common", "64"],
            "compat_abi_tags_excluded": ["x32"],
        },
        "x32_exclusion": {
            "number_minimum": min(x32_numbers),
            "number_maximum": max(x32_numbers),
            "number_count": len(x32_numbers),
            "numbers_sha256": hashlib.sha256(canonical_x32).hexdigest(),
            "runtime_rejection_verified": False,
        },
        "universe": {
            "rows": rows,
            "row_count": len(rows),
            "listed_entry_count": sum(row["number_state"] == "listed_entry" for row in rows),
            "listed_without_entry_point_numbers": listed_without_entry,
            "unassigned_holes": holes,
            "hole_count": len(holes),
            "rows_sha256": rows_digest,
        },
        "policy_state": {
            "per_number_dispositions_complete": False,
            "per_number_predicates_complete": False,
            "unclassified_rows": len(rows),
            "target_kernel_build_pinned": False,
            "syscall_runtime_conformance_passed": False,
            "execution_authority": False,
            "readiness_pass": False,
            "qualification_credit": 0,
        },
    }


def validate_baseline(value: Any) -> dict[str, Any]:
    top_keys = {"schema", "record_id", "status", "architecture", "source", "x32_exclusion", "universe", "policy_state"}
    if not isinstance(value, dict) or set(value) != top_keys or value.get("schema") != "core.cfd.f8.r008_syscall_number_universe_baseline.v1":
        raise SyscallUniverseError("unexpected syscall-number baseline schema")
    if value.get("record_id") != "f8-r008-syscall-universe-linux-v6.8-x86_64-baseline-v1":
        raise SyscallUniverseError("unexpected syscall-number baseline record id")
    if value.get("status") != "upstream_reference_inventory_only_not_target_kernel_or_execution_policy":
        raise SyscallUniverseError("baseline must remain a non-authoritative source inventory")

    expected_arch = {
        "native_abi": "x86_64",
        "audit_arch_hex": "0xc000003e",
        "native_number_minimum": 0,
        "native_number_maximum": EXPECTED_NATIVE_MAX,
        "native_number_count": EXPECTED_NATIVE_MAX + 1,
    }
    arch = value["architecture"]
    if not isinstance(arch, dict) or set(arch) != set(expected_arch):
        raise SyscallUniverseError("baseline architecture schema is malformed")
    if any(type(arch.get(field)) is not int for field in ("native_number_minimum", "native_number_maximum", "native_number_count")) or arch != expected_arch:
        raise SyscallUniverseError("baseline native syscall range is malformed")

    expected_source = {
        "upstream_ref": "v6.8",
        "path": SOURCE_PATH,
        "url": SOURCE_URL,
        "sha256": SOURCE_SHA256,
        "table_format": "<number> <abi> <name> [<entry-point>]",
        "native_abi_tags_included": ["common", "64"],
        "compat_abi_tags_excluded": ["x32"],
    }
    if value["source"] != expected_source:
        raise SyscallUniverseError("baseline upstream source pin is malformed")

    x32_numbers = list(EXPECTED_X32_RANGE)
    x32_digest = hashlib.sha256(json.dumps(x32_numbers, separators=(",", ":")).encode("ascii")).hexdigest()
    expected_x32 = {
        "number_minimum": 512,
        "number_maximum": 547,
        "number_count": 36,
        "numbers_sha256": x32_digest,
        "runtime_rejection_verified": False,
    }
    x32_exclusion = value["x32_exclusion"]
    if not isinstance(x32_exclusion, dict) or set(x32_exclusion) != set(expected_x32):
        raise SyscallUniverseError("baseline x32 exclusion schema is malformed")
    if any(type(x32_exclusion[field]) is not int for field in ("number_minimum", "number_maximum", "number_count")) or type(x32_exclusion["runtime_rejection_verified"]) is not bool:
        raise SyscallUniverseError("baseline x32 values must use exact JSON number/boolean types")
    if x32_exclusion != expected_x32:
        raise SyscallUniverseError("baseline x32 exclusion inventory is malformed")

    universe_keys = {
        "rows", "row_count", "listed_entry_count", "listed_without_entry_point_numbers",
        "unassigned_holes", "hole_count", "rows_sha256",
    }
    universe = value["universe"]
    if not isinstance(universe, dict) or set(universe) != universe_keys or not isinstance(universe.get("rows"), list):
        raise SyscallUniverseError("baseline universe rows are missing")
    rows = universe["rows"]
    if len(rows) != EXPECTED_NATIVE_MAX + 1 or type(universe.get("row_count")) is not int or universe["row_count"] != len(rows):
        raise SyscallUniverseError("baseline must enumerate every number in the pinned native interval")

    row_keys = {"syscall_number", "number_state", "abi", "name", "entry_point", "disposition", "predicate"}
    holes: list[int] = []
    entryless: list[int] = []
    listed_entries = 0
    for expected_number, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != row_keys or type(row.get("syscall_number")) is not int or row["syscall_number"] != expected_number:
            raise SyscallUniverseError("baseline rows must be ordered, unique, and gap-free")
        if row["disposition"] is not None or row["predicate"] is not None:
            raise SyscallUniverseError("source inventory must not imply a syscall execution policy")
        state = row["number_state"]
        if state == "unassigned_hole":
            if any(row[field] is not None for field in ("abi", "name", "entry_point")):
                raise SyscallUniverseError("unassigned holes must not contain syscall metadata")
            holes.append(expected_number)
        elif state == "listed_entry":
            if row["abi"] not in {"common", "64"} or not isinstance(row["name"], str) or not re.fullmatch(r"[A-Za-z0-9_]+", row["name"]) or not isinstance(row["entry_point"], str) or not re.fullmatch(r"[A-Za-z0-9_]+", row["entry_point"]):
                raise SyscallUniverseError("listed syscall entry row is malformed")
            listed_entries += 1
        elif state == "listed_without_entry_point":
            if row["abi"] not in {"common", "64"} or not isinstance(row["name"], str) or not re.fullmatch(r"[A-Za-z0-9_]+", row["name"]) or row["entry_point"] is not None:
                raise SyscallUniverseError("entryless table row is malformed")
            entryless.append(expected_number)
        else:
            raise SyscallUniverseError("unknown syscall number state")

    holes_field = universe["unassigned_holes"]
    entryless_field = universe["listed_without_entry_point_numbers"]
    if not isinstance(holes_field, list) or any(type(item) is not int for item in holes_field) or holes_field != holes:
        raise SyscallUniverseError("hole inventory does not match the numbered rows")
    if not isinstance(entryless_field, list) or any(type(item) is not int for item in entryless_field) or entryless_field != entryless:
        raise SyscallUniverseError("entryless-row inventory does not match the numbered rows")
    if type(universe["listed_entry_count"]) is not int or universe["listed_entry_count"] != listed_entries:
        raise SyscallUniverseError("listed-entry count does not match the numbered rows")
    if type(universe["hole_count"]) is not int or universe["hole_count"] != len(holes):
        raise SyscallUniverseError("hole count does not match the numbered rows")
    canonical_rows = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    rows_digest = hashlib.sha256(canonical_rows).hexdigest()
    if universe["rows_sha256"] != rows_digest:
        raise SyscallUniverseError("canonical number rows digest is inconsistent")
    if rows_digest != EXPECTED_ROWS_SHA256:
        raise SyscallUniverseError("canonical number rows differ from the independently pinned upstream-derived digest")

    expected_policy = {
        "per_number_dispositions_complete": False,
        "per_number_predicates_complete": False,
        "unclassified_rows": len(rows),
        "target_kernel_build_pinned": False,
        "syscall_runtime_conformance_passed": False,
        "execution_authority": False,
        "readiness_pass": False,
        "qualification_credit": 0,
    }
    policy = value["policy_state"]
    bool_fields = set(expected_policy) - {"unclassified_rows", "qualification_credit"}
    if not isinstance(policy, dict) or set(policy) != set(expected_policy) or any(type(policy.get(key)) is not bool for key in bool_fields):
        raise SyscallUniverseError("policy-state flags must use exact JSON boolean types")
    if type(policy.get("unclassified_rows")) is not int or type(policy.get("qualification_credit")) is not int or policy != expected_policy:
        raise SyscallUniverseError("baseline may not claim a complete policy, target pin, readiness, or credit")
    return value


def verify_output() -> dict[str, Any]:
    root_fd = os.open(LAB, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
    reports_fd = -1
    descriptor = -1
    try:
        reports_fd = os.open("reports", os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=root_fd)
        descriptor = os.open(OUTPUT.name, os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC, dir_fd=reports_fd)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_SOURCE_BYTES * 8:
            raise SyscallUniverseError("generated baseline must be a bounded single-link regular file")
        chunks: list[bytes] = []
        size = 0
        while True:
            block = os.read(descriptor, min(64 * 1024, MAX_SOURCE_BYTES * 8 + 1 - size))
            if not block:
                break
            size += len(block)
            if size > MAX_SOURCE_BYTES * 8:
                raise SyscallUniverseError("generated baseline exceeds the fixed byte limit")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(OUTPUT.name, dir_fd=reports_fd, follow_symlinks=False)
        identity = lambda item: (
            item.st_dev, item.st_ino, item.st_mode, item.st_size,
            item.st_mtime_ns, item.st_ctime_ns, item.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or size != before.st_size:
            raise SyscallUniverseError("generated baseline changed while being read")
        value = _decode_strict_json(b"".join(chunks))
        return validate_baseline(value)
    except OSError as error:
        raise SyscallUniverseError("could not safely open generated baseline beneath lab root") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if reports_fd >= 0:
            os.close(reports_fd)
        os.close(root_fd)


def write_baseline(raw: bytes) -> Path:
    payload = (json.dumps(validate_baseline(build_baseline(raw)), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    root_fd = os.open(LAB, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
    reports_fd = -1
    descriptor = -1
    created = False
    try:
        reports_fd = os.open("reports", os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=root_fd)
        descriptor = os.open(OUTPUT.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644, dir_fd=reports_fd)
        created = True
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write while publishing syscall-number baseline")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.fsync(reports_fd)
    except BaseException:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if created and reports_fd >= 0:
            try:
                os.unlink(OUTPUT.name, dir_fd=reports_fd)
            except OSError:
                pass
        raise
    finally:
        if reports_fd >= 0:
            os.close(reports_fd)
        os.close(root_fd)
    return LAB / OUTPUT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable baseline at its fixed lab path")
    parser.add_argument("--stdin", action="store_true", help="read the pinned upstream source bytes from stdin")
    parser.add_argument("--verify", action="store_true", help="verify the already generated lab-local manifest")
    args = parser.parse_args()
    if args.verify:
        if args.write or args.stdin:
            parser.error("--verify cannot be combined with --write or --stdin")
        value = verify_output()
        summary = {
            "schema": value["schema"],
            "status": value["status"],
            "universe_count": value["universe"]["row_count"],
            "hole_count": value["universe"]["hole_count"],
            "policy_state": value["policy_state"],
        }
        print(json.dumps(summary, sort_keys=True))
        return 0
    if not args.stdin:
        parser.error("--stdin or --verify is required; no arbitrary source or output path is accepted")
    raw = __import__("sys").stdin.buffer.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise SyscallUniverseError("stdin source exceeds the fixed byte limit")
    if args.write:
        print(write_baseline(raw).relative_to(LAB))
    else:
        print(json.dumps(validate_baseline(build_baseline(raw)), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
