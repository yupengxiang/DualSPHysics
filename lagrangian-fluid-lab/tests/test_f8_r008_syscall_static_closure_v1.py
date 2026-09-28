from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f8_r008_syscall_static_closure_v1 as closure


def test_build_closes_all_462_rows_but_keeps_target_and_runtime_holds() -> None:
    report = closure.build_report()

    assert report["status"] == closure.STATUS_MISSING_TARGET
    assert report["static_policy"]["native_row_count"] == 462
    assert len(report["static_policy"]["rows"]) == 462
    assert report["validation"]["per_number_dispositions_complete"] is True
    assert report["validation"]["per_number_predicates_complete"] is True
    assert report["validation"]["target_kernel_pin_complete"] is False
    assert report["validation"]["runtime_conformance_verified"] is False
    assert report["authorization"] == closure.AUTHORIZATION
    assert report["side_effects"] == closure.SIDE_EFFECTS


def test_each_native_number_has_exact_default_deny_disposition_and_predicate() -> None:
    report = closure.build_report()
    rows = report["static_policy"]["rows"]

    assert [row["syscall_number"] for row in rows] == list(range(462))
    assert all(row["disposition"] == "deny_errno" for row in rows)
    for number, row in enumerate(rows):
        predicate = row["predicate"]
        assert predicate["expression"] == f"audit_arch == 0xc000003e && raw_nr == {number}"
        assert predicate["source_refs"] == closure.POLICY_SOURCE_REFS


def test_selector_conditions_close_static_edges_without_claiming_runtime() -> None:
    conditions = closure.build_report()["selector_conditions"]

    assert conditions["audit_arch"]["other_arch_action"] == "deny"
    assert conditions["raw_nr"]["partition_complete"] is True
    assert conditions["nr_minus_one"]["raw_value"] == -1
    assert conditions["nr_minus_one"]["target_request_action"] == "deny_without_separate_trusted_tracer_state"
    assert conditions["nr_minus_one"]["runtime_behavior_verified"] is False
    assert conditions["x32"]["required_config_value"] == "n"
    assert conditions["x32"]["runtime_rejection_verified"] is False
    assert conditions["ptrace_seccomp"]["seccomp_user_notification"] == "forbidden"
    assert conditions["ptrace_seccomp"]["preexisting_seccomp_filter"] == "reject_profile"
    assert conditions["ptrace_seccomp"]["order_runtime_conformance_verified"] is False


def test_local_candidates_and_reference_hashes_are_not_target_pins() -> None:
    report = closure.build_report()
    slots = report["target_kernel_pin"]["slots"]

    assert slots["kernel_release"]["local_candidate"] == "6.8.0-138-generic"
    assert slots["kernel_release"]["local_candidate_is_external_pin"] is False
    assert slots["config_sha256"]["local_candidate_is_external_pin"] is False
    assert slots["source_commit"]["target_value"] is None
    assert slots["source_tree_sha256"]["target_value"] is None
    assert slots["build_id"]["target_value"] is None
    assert report["known_reference_hashes"]["upstream_syscall_table_sha256"] == "4c30abea9a4b69f3409bea7a0c910a8c8feb9a44b22a448b5c82f2bfdd8249c8"


def test_report_validator_rejects_row_or_runtime_promotion() -> None:
    report = copy.deepcopy(closure.build_report())
    report["static_policy"]["rows"][0]["disposition"] = "static_allow_nonmutating"
    with pytest.raises(closure.StaticClosureError, match="rows differ"):
        closure.validate_report(report)

    report = copy.deepcopy(closure.build_report())
    report["selector_conditions"]["x32"]["runtime_rejection_verified"] = True
    with pytest.raises(closure.StaticClosureError, match="selector condition contract drift"):
        closure.validate_report(report)


def test_report_validator_rejects_promoted_local_pin() -> None:
    report = copy.deepcopy(closure.build_report())
    report["target_kernel_pin"]["slots"]["config_sha256"]["local_candidate_is_external_pin"] = True
    with pytest.raises(closure.StaticClosureError, match="local candidate"):
        closure.validate_report(report)


def test_bounded_json_reader_rejects_duplicate_keys_and_traversal(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(closure.StaticClosureError, match="duplicate JSON object key"):
        closure._strict_object([("schema", "one"), ("schema", "two")])

    with pytest.raises(closure.StaticClosureError, match="not canonical"):
        closure._canonical_path("../outside.json")


def test_report_roundtrip_in_memory_is_strict() -> None:
    report = closure.build_report()
    payload = json.dumps(report, sort_keys=True, allow_nan=False)
    assert closure.validate_report(json.loads(payload))["record_id"] == closure.RECORD_ID


def test_checked_in_report_recomputes_from_bounded_dependencies() -> None:
    checked = closure.verify_output()
    assert checked["record_id"] == closure.RECORD_ID
    assert checked["static_policy"]["native_row_count"] == 462
    assert checked["validation"]["target_kernel_pin_complete"] is False
    assert checked["authorization"]["qualification_credit"] == 0
