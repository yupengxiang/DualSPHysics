from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r003_static_design_review_v1 as r003
from scripts import f8_r004_static_design_review_v1 as review_module


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r004/static-design-review-v1/receipt.json"


def review() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_r004_v1_is_retained_static_rejection_with_all_prior_scopes_closed() -> None:
    value = review()
    assert value["schema"] == review_module.SCHEMA
    assert value["scope_id"] == review_module.SCOPE
    assert value["status"] == "r004_static_design_review_failed"
    assert value["qualification_claim"] == "none"
    assert value["qualification_credit"] == 0
    assert value["static_constraint_gaps"] == [{
        "code": "MINIMAL_CONTROL_PATH_REPAIR",
        "detail": "r004 control must be a bare colocated filename with an unchanged complete table",
    }]
    assert [entry["scope_id"] for entry in value["closed_prior_scopes"]] == [
        "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
        "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002",
        "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003",
    ]
    assert value["r004_namespace"]["all_targets_absent_at_review"] is True


def test_r004_adopts_official_colocated_bare_filename_mode_only() -> None:
    value = review()
    repair = value["minimal_mechanism_repair"]
    proof = repair["official_colocation_proof"]
    assert repair["r003_failed_reference"].startswith("acceleration/")
    assert repair["r004_reference"] == "F8_OPC_q0p500_r004_acceleration.csv"
    assert not repair["r004_reference"].startswith("acceleration/")
    assert proof["reference_is_bare_filename"] is True
    assert proof["control_is_colocated_with_definition"] is True
    assert proof["official_reference"] == "CaseForcesData_0.csv"
    copy = value["control_dependency_copy_proof"]
    assert copy["definition_relative_reference"] == repair["r004_reference"]
    assert copy["source_control"].endswith("/input/F8_OPC_q0p500_r004_acceleration.csv")
    assert copy["required_generated_copy"].endswith("/generated/F8_OPC_q0p500_r004_acceleration.csv")


def test_r004_preserves_r003_constants_finite_walls_physics_and_control_values() -> None:
    values = review_module.parameters()
    definition = review_module.definition_xml(values)
    assert values == r003.parameters()
    assert 'hswl value="0" auto="true"' in definition
    assert "<setshapemode>dp | bound</setshapemode>" in definition
    assert "<boxfill>top|bottom</boxfill>" in definition
    assert 'name="FiniteNoSlipZWalls"' in definition
    assert 'name="FullyFilledChannelFluid"' in definition
    assert review_module.acceleration_csv(values) == r003.acceleration_csv(r003.parameters())
    assert "r003_acceleration.csv" not in definition
    # v1's immutable rejection is precisely that it changed the name but left
    # the child-directory prefix in place.  v2 records the corrective review.
    assert 'value="acceleration/F8_OPC_q0p500_r004_acceleration.csv"' in definition


def test_r004_precommits_in_memory_inputs_and_forbids_execution() -> None:
    value = review()
    precommitted = value["precommitted_input_bytes"]
    assert precommitted["materialized"] is False
    assert precommitted["future_writer_must_match_exactly"] is True
    assert precommitted["definition_sha256"] == review_module.sha256_bytes(review_module.definition_xml(review_module.parameters()).encode())
    assert precommitted["control_sha256"] == review_module.sha256_bytes(review_module.acceleration_csv(review_module.parameters()).encode())
    assert value["next_automatic_step"]["kind"] == "one-time r004 static input materialization"
    controls = value["execution_controls"]
    assert controls["gencase_invoked"] is False
    assert controls["native_decode_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_started"] is False
    assert controls["queue_mutation"] == 0
    assert controls["worker_started"] is False


def test_r004_receipt_is_hash_closed_and_immutable(tmp_path: Path) -> None:
    value = review()
    for item in value["bindings"]:
        path = ROOT / item["path"]
        assert path.is_file()
        if item["path"] == "tests/test_f8_r004_static_design_review_v1.py":
            # v1 recorded the original failed-review test.  This successor
            # test intentionally audits that retained failure rather than
            # pretending its source binding can be rewritten in place.
            assert item["sha256"] != review_module.sha256(path)
            assert item["bytes"] != path.stat().st_size
        else:
            assert item["sha256"] == review_module.sha256(path)
            assert item["bytes"] == path.stat().st_size
    target = tmp_path / "receipt.json"
    written = review_module.write_review(target)
    assert written["schema"] == review_module.SCHEMA
    with pytest.raises(FileExistsError, match="immutable F8 r004 static review"):
        review_module.write_review(target)
