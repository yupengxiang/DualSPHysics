from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import ds_data02_stage2_root275_readiness_clarification_v1 as subject


def test_self_test_is_closed() -> None:
    result = subprocess.run(
        [sys.executable, str(subject.SCRIPT), "self-test"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    assert value == {
        "status": "PASS",
        "target_count": 7,
        "payload_content_opened": False,
        "launch_allowed": False,
    }


def test_build_has_seven_future_cases(tmp_path: Path) -> None:
    value = subject.build(tmp_path / "clarification.json")["result"]
    assert value["status"] == "SOURCE_PREPARED_NOT_TYPED_NOT_TERMINAL"
    assert value["target_count"] == 7
    assert len(value["targets"]) == 7
    assert all(row["plan_status"] == "UNSCHEDULED_EXACT_CURRENT_AUDIT" for row in value["targets"])
    assert all(row["typed_terminal_proof"] is False for row in value["targets"])
    assert all(row["native_extraction_allowed"] is False for row in value["targets"])
    assert sum(value["future_parent_groups"].values()) == 7
    assert value["coverage_context"]["after_root269_actual_saved_mask_cases"] == 123
    assert value["coverage_context"]["after_root280_actual_saved_mask_cases"] == 127
    assert value["coverage_context"]["after_root280_target_actual_saved_mask_cases"] == 0
    assert value["read_policy"]["deferred_h5_content_opened"] is False


def test_root275_contracts_are_source_only(tmp_path: Path) -> None:
    value = subject.build(tmp_path / "clarification.json")["result"]
    contracts = value["root275_prepared_contracts"]
    assert contracts["launch_allowed"] is False
    assert contracts["execution_allowed"] is False
    assert contracts["terminal_typed_proof_present"] is False
    assert set(value["future_parent_groups"]) == {
        "F4-typed-lifecycle-continuation-000",
        "F4-typed-lifecycle-continuation-001",
        "F4-typed-lifecycle-continuation-002",
    }
