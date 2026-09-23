from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r003_static_design_review_v1 as r003
from scripts import f8_r004_static_design_review_v2 as review_module


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r004/static-design-review-v2/receipt.json"


def review() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_r004_v2_is_passed_static_only_with_v1_rejection_retained() -> None:
    value = review()
    assert value["schema"] == review_module.SCHEMA
    assert value["scope_id"] == review_module.SCOPE
    assert value["status"] == "r004_static_design_review_v2_passed_inputs_not_authorized"
    assert value["qualification_credit"] == 0
    assert value["static_constraint_gaps"] == []
    assert value["retained_static_rejection"]["execution_performed"] is False
    assert value["r004_namespace"]["all_input_and_preflight_targets_absent_at_review"] is True


def test_r004_v2_exactly_removes_child_directory_reference() -> None:
    value = review()
    repair = value["minimal_mechanism_repair"]
    proof = repair["official_colocation_proof"]
    assert repair["r004_reference"] == "F8_OPC_q0p500_r004_acceleration.csv"
    assert proof["reference_is_bare_filename"] is True
    assert proof["control_is_colocated_with_definition"] is True
    definition = review_module.definition_xml(review_module.parameters())
    assert 'value="F8_OPC_q0p500_r004_acceleration.csv"' in definition
    assert "acceleration/" not in definition
    assert value["control_dependency_copy_proof"]["required_generated_copy"].endswith("/generated/F8_OPC_q0p500_r004_acceleration.csv")


def test_r004_v2_preserves_r003_physics_walls_and_control_values() -> None:
    values = review_module.parameters()
    definition = review_module.definition_xml(values)
    assert values == r003.parameters()
    assert review_module.acceleration_csv(values) == r003.acceleration_csv(r003.parameters())
    assert 'hswl value="0" auto="true"' in definition
    assert "<setshapemode>dp | bound</setshapemode>" in definition
    assert "<boxfill>top|bottom</boxfill>" in definition
    assert 'name="FiniteNoSlipZWalls"' in definition
    assert 'name="FullyFilledChannelFluid"' in definition


def test_r004_v2_is_precommitted_and_nonexecuting() -> None:
    value = review()
    precommit = value["precommitted_input_bytes"]
    assert precommit["materialized"] is False
    assert precommit["future_writer_must_match_exactly"] is True
    assert precommit["definition_sha256"] == review_module.sha256_bytes(review_module.definition_xml(review_module.parameters()).encode())
    assert precommit["control_sha256"] == review_module.sha256_bytes(review_module.acceleration_csv(review_module.parameters()).encode())
    assert value["next_automatic_step"]["kind"] == "one-time r004 static input materialization"
    assert all(value["execution_controls"][key] is False for key in ("gencase_invoked", "native_decode_invoked", "solver_invoked", "gpu_started", "worker_started"))
    assert value["execution_controls"]["queue_mutation"] == 0


def test_r004_v2_receipt_is_hash_closed_and_immutable(tmp_path: Path) -> None:
    value = review()
    for item in value["bindings"]:
        path = ROOT / item["path"]
        assert path.is_file()
        assert item["sha256"] == review_module.sha256(path)
        assert item["bytes"] == path.stat().st_size
    target = tmp_path / "receipt.json"
    assert review_module.write_review(target)["schema"] == review_module.SCHEMA
    with pytest.raises(FileExistsError, match="immutable F8 r004 static review v2"):
        review_module.write_review(target)
