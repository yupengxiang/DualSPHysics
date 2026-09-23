from __future__ import annotations

from pathlib import Path

import pytest

from scripts import f8_r005_input_materialization_v1 as materializer
from scripts import f8_r005_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]


def test_review_binds_exact_r005_static_input_bytes() -> None:
    definition = design.definition_xml(design.parameters()).encode("utf-8")
    control = design.acceleration_csv(design.parameters()).encode("utf-8")
    review = materializer.load_json(materializer.REVIEW)
    materializer.validate_review(review, definition, control)
    assert review["precommitted_input_bytes"]["materialized"] is False
    assert review["qualification_credit"] == 0


def test_definition_proof_covers_both_walls_normals_and_fluid() -> None:
    definition = design.definition_xml(design.parameters())
    proof = materializer.prove_definition(definition)
    assert proof["domain_z_m"] == [-0.0525, 0.06]
    assert proof["physical_wall_planes_z_m"] == [-0.0525, 0.0525]
    assert proof["fluid_z_interval_m"] == [-0.045, 0.045]
    assert proof["normal_geometry_file"] == "[CaseName]_hdp_Actual.vtk"
    assert proof["static_proof_only"] is True


def test_r005_control_is_byte_identical_to_r004_positive_control() -> None:
    control = design.acceleration_csv(design.parameters()).encode("utf-8")
    assert control == (LAB / design.R004_CONTROL).read_bytes()


def test_materializer_rejects_namespace_substitution_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only permits its registered targets"):
        materializer.write_materialization(
            tmp_path / "definition.xml", tmp_path / "control.csv", tmp_path / "receipt.json"
        )
    assert list(tmp_path.iterdir()) == []


def test_static_review_bindings_remain_hash_closed() -> None:
    review = materializer.load_json(materializer.REVIEW)
    assert materializer.bindings_current(review)
    for item in review["bindings"]:
        path = LAB / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert materializer.sha256(path) == item["sha256"]
