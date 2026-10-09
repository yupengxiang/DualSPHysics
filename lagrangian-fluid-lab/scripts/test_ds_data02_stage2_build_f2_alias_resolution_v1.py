from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import ds_data02_stage2_build_f2_alias_resolution_v1 as subject


def test_self_test_is_conservative() -> None:
    result = subprocess.run(
        [sys.executable, str(subject.SCRIPT), "self-test"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    assert value["status"] == "PASS"
    assert value["exact_alias_equivalence_proven"] is False
    assert value["payload_content_opened"] is False


def test_alias_remains_unresolved_despite_source_parameter_match(tmp_path: Path) -> None:
    value = subject.build(tmp_path / "alias.json")["result"]
    assert value["status"] == "UNRESOLVED_HISTORICAL_ALIAS_NO_CANONICAL_BINDING"
    assert value["evidence"]["identity_consistent_across_metadata"] is True
    assert value["evidence"]["runtime_alias_consistent_across_producer_metadata"] is True
    assert value["evidence"]["geometry_values_equal_across_manifest_conversion_owner_source"] is True
    assert value["evidence"]["control_family_equal"] is True
    assert value["evidence"]["motion_sha_equal"] is True
    assert value["evidence"]["canonical_binding_present"] is False
    assert value["evidence"]["scope_equality_not_claimed"] is True
    assert value["resolution"]["exact_alias_equivalence_proven"] is False
    assert value["claim_boundary"]["typed_lifecycle_credit"] == "NONE"
    assert value["read_policy"]["trajectory_h5_content_opened"] is False
