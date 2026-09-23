from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f8_r004_input_materialization_v1 as writer
from scripts import f8_r004_static_design_review_v2 as design


ROOT = Path(__file__).resolve().parents[1]


def test_r004_materialization_is_hash_closed_static_only_and_preserves_history() -> None:
    receipt = json.loads((ROOT / writer.RECEIPT_TARGET).read_text(encoding="utf-8"))
    review = json.loads((ROOT / writer.REVIEW).read_text(encoding="utf-8"))
    assert receipt["schema"] == "core.cfd.f8.r004_input_materialization.v1"
    assert receipt["status"] == "one_time_r004_inputs_materialized_static_only"
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["authorization"]["review_schema"] == design.SCHEMA
    assert receipt["authorization"]["consumed"] is True
    assert receipt["authorization"]["overwrite_or_reuse_allowed"] is False
    assert receipt["retained_static_rejection"]["execution_performed"] is False
    assert len(receipt["closed_prior_execution_scopes"]) == 3
    for item in receipt["bindings"]:
        path = ROOT / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert writer.sha256(path) == item["sha256"]
    assert receipt["materialized_inputs"]["definition"]["sha256"] == review["precommitted_input_bytes"]["definition_sha256"]
    assert receipt["materialized_inputs"]["control"]["sha256"] == review["precommitted_input_bytes"]["control_sha256"]


def test_r004_materialization_uses_bare_colocated_control_and_finite_walls() -> None:
    receipt = json.loads((ROOT / writer.RECEIPT_TARGET).read_text(encoding="utf-8"))
    proof = receipt["definition_proof"]
    assert proof["constantsdef"]["hswl"] == {"value": "0", "auto": "true"}
    assert proof["constantsdef"]["rhopgradient"] == {"value": "1"}
    assert proof["constantsdef"]["speedsystem"] == {"value": "0", "auto": "true"}
    assert proof["shape_mode"] == "dp | bound"
    assert proof["lower_wall_z_interval_m"][1] == proof["fluid_z_interval_m"][0]
    assert proof["upper_wall_z_interval_m"][0] == proof["fluid_z_interval_m"][1]
    copy = receipt["control_dependency_copy_proof"]
    assert copy["definition_relative_reference"] == "F8_OPC_q0p500_r004_acceleration.csv"
    assert copy["source_is_colocated_with_definition"] is True
    assert "/generated/F8_OPC_q0p500_r004_acceleration.csv" in copy["required_generated_copy"]
    definition = (ROOT / writer.DEFINITION_TARGET).read_text(encoding="utf-8")
    assert 'value="F8_OPC_q0p500_r004_acceleration.csv"' in definition
    assert "acceleration/" not in definition


def test_r004_materialization_refuses_replacement_or_unregistered_targets(tmp_path: Path) -> None:
    with pytest.raises(FileExistsError, match="one-time F8 r004 materialization"):
        writer.write_materialization()
    with pytest.raises(ValueError, match="registered targets"):
        writer.write_materialization(tmp_path / "other.xml", tmp_path / "other.csv", tmp_path / "other.json")
    with pytest.raises(FileExistsError, match="immutable F8 r004 static review v2"):
        design.write_review(ROOT / design.OUTPUT)
