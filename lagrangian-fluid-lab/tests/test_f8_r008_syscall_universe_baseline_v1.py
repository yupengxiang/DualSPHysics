from __future__ import annotations

import copy
import hashlib
import json

import pytest

from scripts import f8_r008_syscall_universe_baseline_v1 as baseline


FIXTURE = b"""# fixture, not a Linux kernel source snapshot
0 common read sys_read
1 64 fstat sys_newfstat
3 64 retired_entry
512 x32 read compat_sys_read
"""


def test_parser_preserves_abis_names_and_entryless_table_rows() -> None:
    parsed = baseline.parse_table_rows(FIXTURE)
    assert parsed["native_rows"] == {
        0: {"syscall_number": 0, "abi": "common", "name": "read", "entry_point": "sys_read"},
        1: {"syscall_number": 1, "abi": "64", "name": "fstat", "entry_point": "sys_newfstat"},
        3: {"syscall_number": 3, "abi": "64", "name": "retired_entry", "entry_point": None},
    }
    assert parsed["x32_rows"][512]["name"] == "read"
    assert parsed["x32_rows"][512]["entry_point"] == "compat_sys_read"


def test_parser_rejects_duplicate_native_or_x32_numbers() -> None:
    duplicate_native = FIXTURE + b"2 common open sys_open\n2 64 other sys_other\n"
    duplicate_x32 = FIXTURE + b"512 x32 other compat_other\n"
    with pytest.raises(baseline.SyscallUniverseError, match="duplicate syscall number"):
        baseline.parse_table_rows(duplicate_native)
    with pytest.raises(baseline.SyscallUniverseError, match="duplicate syscall number"):
        baseline.parse_table_rows(duplicate_x32)


def test_parser_fails_closed_on_malformed_rows_and_unknown_abis() -> None:
    with pytest.raises(baseline.SyscallUniverseError, match="malformed syscall table row"):
        baseline.parse_table_rows(b"0 common read sys_read extra\n")
    with pytest.raises(baseline.SyscallUniverseError, match="unsupported ABI tag"):
        baseline.parse_table_rows(b"0 compat read sys_read\n")
    with pytest.raises(baseline.SyscallUniverseError, match="strict ASCII"):
        baseline.parse_table_rows("0 common réad sys_read\n".encode())


def test_pinned_builder_rejects_unpinned_bytes() -> None:
    assert hashlib.sha256(FIXTURE).hexdigest() != baseline.SOURCE_SHA256
    with pytest.raises(baseline.SyscallUniverseError, match="do not match the pinned"):
        baseline.build_baseline(FIXTURE)


def test_baseline_validator_rejects_policy_or_missing_number_rows() -> None:
    value = baseline.verify_output()
    assert value["universe"]["row_count"] == 462
    assert value["universe"]["hole_count"] == 89
    assert value["x32_exclusion"]["number_count"] == 36
    missing = copy.deepcopy(value)
    missing["universe"]["rows"].pop()
    with pytest.raises(baseline.SyscallUniverseError, match="every number"):
        baseline.validate_baseline(missing)
    promoted = copy.deepcopy(value)
    promoted["universe"]["rows"][1]["disposition"] = "static_allow_nonmutating"
    with pytest.raises(baseline.SyscallUniverseError, match="must not imply"):
        baseline.validate_baseline(promoted)


def test_baseline_validator_rejects_type_confusion_and_duplicate_json_keys() -> None:
    value = copy.deepcopy(baseline.verify_output())
    value["policy_state"]["readiness_pass"] = 0
    with pytest.raises(baseline.SyscallUniverseError, match="exact JSON boolean"):
        baseline.validate_baseline(value)
    value = copy.deepcopy(baseline.verify_output())
    value["x32_exclusion"]["runtime_rejection_verified"] = 0
    with pytest.raises(baseline.SyscallUniverseError, match="exact JSON number/boolean"):
        baseline.validate_baseline(value)
    with pytest.raises(baseline.SyscallUniverseError, match="duplicate JSON object key"):
        baseline._strict_object([("readiness_pass", False), ("readiness_pass", True)])


def test_strict_json_decoder_rejects_non_finite_constants() -> None:
    for token in (b"NaN", b"Infinity", b"-Infinity"):
        with pytest.raises(baseline.SyscallUniverseError, match="non-finite JSON constant"):
            baseline._decode_strict_json(b'{"value":' + token + b"}")


def test_baseline_validator_rejects_rehashed_row_tampering() -> None:
    value = copy.deepcopy(baseline.verify_output())
    value["universe"]["rows"][0]["name"] = "not_read"
    canonical = json.dumps(value["universe"]["rows"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    value["universe"]["rows_sha256"] = hashlib.sha256(canonical).hexdigest()
    with pytest.raises(baseline.SyscallUniverseError, match="independently pinned upstream-derived digest"):
        baseline.validate_baseline(value)


def test_table_source_bytes_are_bounded() -> None:
    with pytest.raises(baseline.SyscallUniverseError, match="fixed input bound"):
        baseline.parse_table_rows(b" " * (baseline.MAX_SOURCE_BYTES + 1))
