"""CPU-only contracts for the DS-DATA-02 F4 finite-liquid generator."""
from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import ds_data02_f4 as f4


def test_registered_family_is_two_real_3d_finite_mechanisms():
    records = f4.registry_records()
    assert len(records) == 48
    assert {record["mechanism_id"] for record in records} == set(f4.MECHANISMS)
    assert all(record["finite_initial_mass"] for record in records)
    assert all(not record["open_inlet"] for record in records)
    assert all(record["continuum_geometry"]["closed_faces"] == f4.CLOSED_FACES for record in records)
    assert all(len(record["registered_resolution_cells"]) == 3 for record in records)


def test_nested_admission_counts_are_exact_and_disjoint_by_rank():
    records = f4.registry_records()
    assert sum("nested8" in record["admission_stages"] for record in records) == 8
    assert sum("nested24" in record["admission_stages"] for record in records) == 24
    assert sum("nested48" in record["admission_stages"] for record in records) == 48
    for mechanism in f4.MECHANISMS:
        local = [record for record in records if record["mechanism_id"] == mechanism]
        assert [record["axis_rank_within_background"] for record in local] == list(range(24))
        assert all(("nested8" in record["admission_stages"]) == (record["axis_rank_within_background"] < 4)
                   for record in local)


def test_drop_and_columns_have_lateral_layers_and_complete_event_windows():
    drop = f4.drop_config("coarse")
    columns = f4.columns_config("coarse")
    assert drop["event_window"]["sequence"][-1] == "transport_tail"
    assert columns["event_window"]["sequence"][-1] == "transport_tail"
    assert min(box["fluid_y_layers"] for box in drop["geometry"]["native_boxes"].values()) >= 4
    assert min(box["fluid_y_layers"] for box in columns["geometry"]["native_boxes"].values()) >= 4
    assert drop["controls"]["time_max_s"] == pytest.approx(1.2)
    assert columns["controls"]["output_interval_s"] == pytest.approx(0.001)


def test_rendered_definitions_are_finite_3d_inputs(tmp_path: Path):
    for mechanism in f4.MECHANISMS:
        config = f4.make_config(mechanism, "coarse")
        path = tmp_path / f"{mechanism}_Def.xml"
        f4.render_definition(config, path)
        audit = f4.validate_definition(path, config)
        root = ET.parse(path).getroot()
        assert audit["finite_wall_faces"] == f4.CLOSED_FACES
        assert audit["fluid_y_layers_min"] >= 4
        assert len(root.findall("./casedef/initials/velocity")) == 2
        assert not root.findall(".//inout")
        assert not root.findall(".//periodic")
        assert float(root.find("./casedef/geometry/definition").get("dp")) == pytest.approx(0.04)


def test_native_mass_contract_is_positive_and_unscaled():
    for mechanism in f4.MECHANISMS:
        for resolution in f4.RESOLUTIONS:
            config = f4.make_config(mechanism, resolution)
            boxes = config["geometry"]["native_boxes"]
            assert all(box["native_mass_kg"] > 0 for box in boxes.values())
            assert all(box["mass_rescaling"] is False for box in boxes.values())
            assert config["initial_state"]["initial_mass_total_kg"] == pytest.approx(
                sum(box["native_mass_kg"] for box in boxes.values())
            )


def test_gencase_request_uses_extensionless_definition_and_runner_budget(tmp_path: Path):
    config = f4.drop_config("coarse")
    definition = tmp_path / "drop_Def.xml"
    f4.render_definition(config, definition)
    request = f4.make_gencase_request(config, definition, attempt_id="unit-gencase-f4")
    assert request["kind"] == "cpu"
    assert request["cpu_task_kind"] == "gencase"
    assert request["cpu_threads"] == 4
    assert request["max_wall_seconds"] <= 300
    assert request["estimated_storage_bytes"] <= 256 * 1024 * 1024
    assert request["command"][1].endswith("_Def")
    assert request["command"][2].startswith("{attempt_root}/")
    assert all(Path(path).is_file() for path in request["input_files"])


def test_qualification_request_requires_real_completed_receipt(tmp_path: Path):
    config = f4.columns_config("coarse")
    receipt = tmp_path / "execution-receipt.json"
    receipt.write_text(json.dumps({"status": "failed", "returncode": 1}))
    with pytest.raises(ValueError, match="completed GenCase"):
        f4.make_qualification_request(config, receipt)


def test_source_audit_binds_hashes_actual_3d_and_finite_counts():
    evidence = f4.source_evidence()
    assert len(evidence["mothers"]) == 2
    for mother in evidence["mothers"]:
        generated = mother["gencase"]
        assert generated["solver_dimension"] == "3D"
        assert generated["fluid_particles"] > 0
        assert generated["total_particles"] > generated["fixed_particles"]
        assert len(mother["template_sha256"]) == 64
        assert mother["finite_wall_semantics"]["closed_faces"] == f4.CLOSED_FACES
    assert all(row["actual_3d"] for row in evidence["historical_recipe_evidence"])

