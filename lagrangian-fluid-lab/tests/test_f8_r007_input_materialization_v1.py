from __future__ import annotations

from pathlib import Path

import pytest

from scripts import f8_r007_input_materialization_v1 as materializer
from scripts import f8_r007_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]


def test_inputs_match_the_immutable_r007_static_precommit() -> None:
    definition = design.definition_xml(design.parameters()).encode("utf-8")
    control = design.acceleration_csv(design.parameters()).encode("utf-8")
    review = materializer.load_json(materializer.REVIEW)
    materializer.validate_review(review, definition, control)
    assert review["precommitted_input_bytes"]["materialized"] is False
    assert review["qualification_credit"] == 0


def test_definition_proof_covers_two_dp_margin_four_layers_and_interface() -> None:
    proof = materializer.prove_definition(design.definition_xml(design.parameters()))
    assert proof["domain_z_m"] == pytest.approx([-0.09, 0.09])
    assert proof["domain_clearance_beyond_outer_layers_dp"] == pytest.approx(2.0)
    assert proof["base_wall_faces_z_m"] == pytest.approx([-0.0525, 0.0525])
    assert proof["normal_interface_expected_z_m"] == pytest.approx([-0.04875, 0.04875])
    assert proof["boundary_layers_vdp"] == [0, 1, 2, 3]
    assert proof["boundary_z_planes_expected_m"] == pytest.approx(
        [-0.075, -0.0675, -0.06, -0.0525, 0.0525, 0.06, 0.0675, 0.075]
    )
    assert proof["boundary_particles_expected"] == 4096
    assert proof["fluid_particles_expected"] == 6656
    assert proof["total_particles_expected"] == 10752
    assert proof["normal_magnitude_minimum_m"] == pytest.approx(0.001875)
    assert proof["static_proof_only"] is True


def test_r007_control_remains_byte_identical_to_r006() -> None:
    control = design.acceleration_csv(design.parameters()).encode("utf-8")
    assert control == (LAB / design.R006_CONTROL).read_bytes()
    assert materializer.sha256_bytes(control) == "bd623b5681f449804a3a2bdf61cded339e180065cf37e2d5d8b6ac92f9e3cfc1"


def test_review_hash_mismatch_is_rejected_before_materialization() -> None:
    definition = design.definition_xml(design.parameters()).encode("utf-8")
    control = design.acceleration_csv(design.parameters()).encode("utf-8")
    review = materializer.load_json(materializer.REVIEW)
    review["precommitted_input_bytes"]["control_sha256"] = "0" * 64
    with pytest.raises(PermissionError, match="does not bind this exact one-time materialization"):
        materializer.validate_review(review, definition, control)


def test_materializer_rejects_namespace_substitution_without_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only permits its registered targets"):
        materializer.write_materialization(
            tmp_path / "definition.xml", tmp_path / "control.csv", tmp_path / "receipt.json"
        )
    assert list(tmp_path.iterdir()) == []


def test_materialization_receipt_is_static_only_and_hash_closed() -> None:
    value = materializer.load_json(materializer.RECEIPT_TARGET)
    assert value["schema"] == materializer.SCHEMA
    assert value["scope_id"] == design.SCOPE
    assert value["status"] == "one_time_r007_inputs_materialized_static_only"
    assert value["qualification_credit"] == 0
    assert value["retained_r006_failure"]["native_decode_invoked"] is False
    assert value["execution_controls"]["gencase_invoked"] is False
    assert value["execution_controls"]["native_decode_invoked"] is False
    assert value["execution_controls"]["solver_invoked"] is False
    assert value["execution_controls"]["queue_mutation"] == 0
    for item in value["bindings"]:
        path = LAB / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert materializer.sha256(path) == item["sha256"]
