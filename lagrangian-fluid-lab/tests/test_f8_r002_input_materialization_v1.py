from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r002_input_materialization_v1 as writer
from scripts import f8_r002_static_design_review_v1 as design


ROOT = Path(__file__).resolve().parents[1]


def test_registered_r002_materialization_is_hash_closed_and_static_only() -> None:
    receipt = json.loads((ROOT / writer.RECEIPT_TARGET).read_text(encoding="utf-8"))
    assert receipt["status"] == "one_time_r002_inputs_materialized_static_only"
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["authorization"]["consumed"] is True
    assert receipt["authorization"]["overwrite_or_reuse_allowed"] is False
    assert receipt["r001_is_immutable_closed_history"]["r001_evidence_mutated"] is False
    for item in receipt["bindings"]:
        path = ROOT / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert writer.sha256(path) == item["sha256"]
    review = json.loads((ROOT / writer.REVIEW).read_text(encoding="utf-8"))
    assert receipt["materialized_inputs"]["definition"]["sha256"] == review["precommitted_input_bytes"]["definition_sha256"]
    assert receipt["materialized_inputs"]["control"]["sha256"] == review["precommitted_input_bytes"]["control_sha256"]


def test_r002_materialization_proves_reviewed_walls_and_control_copy_path() -> None:
    receipt = json.loads((ROOT / writer.RECEIPT_TARGET).read_text(encoding="utf-8"))
    proof = receipt["finite_wall_proof"]
    assert proof["shape_mode"] == "dp | bound"
    assert proof["lower_wall_z_interval_m"][1] == proof["fluid_z_interval_m"][0]
    assert proof["upper_wall_z_interval_m"][0] == proof["fluid_z_interval_m"][1]
    copy = receipt["control_dependency_copy_proof"]
    assert copy["definition_relative_reference"].endswith("_r002_acceleration.csv")
    assert "/generated/acceleration/" in copy["required_generated_copy"]
    definition = (ROOT / writer.DEFINITION_TARGET).read_text(encoding="utf-8")
    assert 'value="acceleration/F8_OPC_q0p500_r002_acceleration.csv"' in definition
    assert "acceleration/F8_OPC_q0p500_acceleration.csv" not in definition


def test_r002_materialization_refuses_replacement_or_unregistered_targets(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError, match="one-time F8 r002 materialization"):
        writer.write_materialization()
    with pytest.raises(ValueError, match="registered targets"):
        writer.write_materialization(tmp_path / "other.xml", tmp_path / "other.csv", tmp_path / "other.json")
    with pytest.raises(FileExistsError, match="immutable F8 r002 static review"):
        design.write_review(ROOT / design.OUTPUT)
