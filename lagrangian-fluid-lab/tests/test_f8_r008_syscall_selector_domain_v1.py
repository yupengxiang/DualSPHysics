from __future__ import annotations

import copy

import pytest

from scripts import f8_r008_syscall_selector_domain_v1 as domain
from scripts import f8_r008_syscall_universe_baseline_v1 as baseline


ARCH = domain.AUDIT_ARCH_X86_64


def test_raw_nr_partition_covers_signed_int32_without_gaps() -> None:
    manifest = domain.build_manifest()
    spans = manifest["raw_nr_domain"]["partition"]
    assert spans[0]["raw_nr_min"] == -(1 << 31)
    assert spans[-1]["raw_nr_max"] == (1 << 31) - 1
    assert all(left["raw_nr_max"] + 1 == right["raw_nr_min"] for left, right in zip(spans, spans[1:]))
    assert sum(row.get("count", row["raw_nr_max"] - row["raw_nr_min"] + 1) for row in spans) == 1 << 32
    assert manifest["raw_nr_domain"]["partition_complete"] is True
    assert manifest["audit_arch_domain"]["partition_complete"] is True


def test_raw_nr_boundaries_and_abi_domains_are_classified_fail_closed() -> None:
    expected = {
        -(1 << 31): "negative_non_sentinel_raw_number",
        -2: "negative_non_sentinel_raw_number",
        -1: "minus_one_unattributed_skip_or_user_selector",
        0: "native_source_table_interval",
        baseline.EXPECTED_NATIVE_MAX: "native_source_table_interval",
        baseline.EXPECTED_NATIVE_MAX + 1: "unlisted_non_x32_raw_number",
        domain.X32_SYSCALL_BIT - 1: "unlisted_non_x32_raw_number",
        domain.X32_SYSCALL_BIT: "x32_tagged_raw_number",
        domain.X32_SYSCALL_BIT | 512: "x32_tagged_raw_number",
        (1 << 31) - 1: "x32_tagged_raw_number",
    }
    for raw_nr, selector_class in expected.items():
        value = domain.classify_selector(ARCH, raw_nr)
        assert value["selector_class"] == selector_class
        assert value["required_action"] != "allow"
        if raw_nr == -1:
            assert value["required_action"] == "deny_as_target_request_without_separate_trusted_tracer_state"


def test_wrong_audit_arch_is_denied_independently_of_syscall_number() -> None:
    for raw_nr in (-1, 0, 1, (1 << 31) - 1):
        value = domain.classify_selector(0x40000003, raw_nr)
        assert value["selector_class"] == "non_target_audit_arch"
        assert value["required_action"] == "deny"


def test_exact_integer_types_and_raw_ranges_are_required() -> None:
    invalid = [
        (True, 0),
        (ARCH, True),
        (-1, 0),
        (1 << 32, 0),
        (ARCH, -(1 << 31) - 1),
        (ARCH, 1 << 31),
    ]
    for audit_arch, raw_nr in invalid:
        with pytest.raises(domain.SelectorDomainError):
            domain.classify_selector(audit_arch, raw_nr)


def test_manifest_binds_upstream_baseline_and_keeps_all_native_numbers_unclassified() -> None:
    value = domain.build_manifest()
    upstream = baseline.verify_output()
    assert value["status"] == "static_selector_domain_partition_only_not_execution_policy"
    selector_abi = value["selector_abi"]
    assert selector_abi["x32_table_dispatch_requires_config_x86_x32_abi"] is True
    assert selector_abi["x32_runtime_rejection_verified"] is False
    assert selector_abi["nr_minus_one_is_attributable_to_tracer_from_selector_alone"] is False
    assert value["source_baseline"]["record_id"] == upstream["record_id"]
    assert value["source_baseline"]["native_rows_sha256"] == upstream["universe"]["rows_sha256"]
    native_span = value["raw_nr_domain"]["partition"][2]
    assert native_span["count"] == 462
    assert native_span["source_table_holes"] == 89
    assert native_span["source_listed_entry_rows"] == 357
    assert native_span["source_entryless_rows"] == 16
    assert native_span["per_number_dispositions_complete"] is False
    assert native_span["per_number_predicates_complete"] is False
    assert value["policy_state"]["target_kernel_build_pinned"] is False
    assert value["policy_state"]["syscall_runtime_conformance_passed"] is False
    assert value["policy_state"]["execution_authority"] is False
    assert value["policy_state"]["readiness_pass"] is False
    assert value["policy_state"]["qualification_credit"] == 0


def test_manifest_cannot_be_promoted_to_policy_or_qualification() -> None:
    value = domain.build_manifest()
    assert domain.validate_manifest(value) == value
    changed = copy.deepcopy(value)
    changed["policy_state"]["readiness_pass"] = True
    with pytest.raises(domain.SelectorDomainError, match="pinned static partition"):
        domain.validate_manifest(changed)
    changed = copy.deepcopy(value)
    changed["raw_nr_domain"]["partition"][2]["per_number_dispositions_complete"] = True
    with pytest.raises(domain.SelectorDomainError, match="pinned static partition"):
        domain.validate_manifest(changed)
