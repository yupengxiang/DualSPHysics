"""Focused source-only tests for the ROOT226 family-aware batch builder."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_native_typed_cause_batch_v2.py")
SPEC = importlib.util.spec_from_file_location("root226_batch_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


F6_REMAINDER = [
    "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0375_YAWM12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0625_YAWM06_DP025",
]
F4_ZERO_TARGET = "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000"
F6_CONSUMED = "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0875_YAWP06_DP025"
F4_ROOT201 = [
    "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4_DROP_B08_gap0p18000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4_DROP_B08_gap0p26000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p60000",
    "F4_DROP_gap0p18000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p18000_xoff0p08000_yoffm0p04000_uz0p60000",
    "F4_DROP_gap0p24000_xoffm0p08000_yoffm0p04000_uz0p40000",
]


def test_default_remainder_is_four_family_specific_cases() -> None:
    proofs, _ = MODULE._all_proof_cases()
    consumed = MODULE._consumed_cases()
    assert MODULE._default_case_ids(proofs, consumed) == F6_REMAINDER


def test_remainder_contracts_have_exact_family_fluid_counts_and_no_fixed_three_id_rule() -> None:
    contracts, gaps = MODULE._build_contracts(F6_REMAINDER)
    assert not gaps
    assert [item["family_id"] for item in contracts] == ["F6"] * 4
    assert all(item["launchable"] for item in contracts)
    assert {item["expected_fluid_initial_count"] for item in contracts} == {327680}
    assert {item["first_disappearance_count"] for item in contracts} == {3, 4}
    assert all(item["native_status"] == "PER_ID_NATIVE_REPORT_PRESENT" for item in contracts)


def test_batch_size_is_variable_but_bounded() -> None:
    contracts, gaps = MODULE._build_contracts(F6_REMAINDER[:1])
    assert len(contracts) == 1 and not gaps
    contracts, gaps = MODULE._build_contracts(F6_REMAINDER[:3])
    assert len(contracts) == 3 and not gaps
    with pytest.raises(MODULE.CauseBatchError, match="one through eight"):
        MODULE._build_contracts(F6_REMAINDER + ["F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0875_YAWP06_DP025"] * 5)


def test_consumed_case_cannot_be_reintroduced() -> None:
    with pytest.raises(MODULE.CauseBatchError, match="overlaps a consumed"):
        MODULE._build_contracts([F6_CONSUMED])


def test_f4_zero_target_is_source_gap_and_never_empty_match_credit() -> None:
    contracts, gaps = MODULE._build_contracts([F4_ZERO_TARGET])
    assert len(contracts) == 1
    contract = contracts[0]
    assert contract["family_id"] == "F4"
    assert contract["expected_fluid_initial_count"] == 59072
    assert contract["first_disappearance_count"] == 0
    assert contract["launchable"] is False
    assert contract["blocked_reason"] == "NO_PER_ID_NATIVE_TARGET_SOURCE_GAP"
    assert any(item["physical_case_id"] == F4_ZERO_TARGET for item in gaps)


def test_f4_root201_nonzero_target_is_not_reclassified_as_f6() -> None:
    case_id = "F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p60000"
    contracts, _ = MODULE._build_contracts([case_id])
    contract = contracts[0]
    assert contract["family_id"] == "F4"
    assert contract["expected_fluid_initial_count"] == 59072
    assert contract["first_disappearance_count"] == 2
    assert contract["launchable"] is False
    assert contract["blocked_reason"] == "ALREADY_SOURCE_BOUND_NATIVE_CAUSE_NO_NEW_UNLOCATED_TARGET"


def test_root201_f4_cases_split_target_gap_from_prior_bound_evidence() -> None:
    contracts, gaps = MODULE._build_contracts(F4_ROOT201)
    assert len(contracts) == 8
    assert len(gaps) == 8
    by_id = {item["physical_case_id"]: item for item in contracts}
    assert sum(item["blocked_reason"] == "NO_PER_ID_NATIVE_TARGET_SOURCE_GAP" for item in by_id.values()) == 5
    assert sum(item["blocked_reason"] == "ALREADY_SOURCE_BOUND_NATIVE_CAUSE_NO_NEW_UNLOCATED_TARGET" for item in by_id.values()) == 3
    assert all(item["expected_fluid_initial_count"] == 59072 for item in by_id.values())
