from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import f8_r008_definition_control_pack_v1 as pack
from scripts import f8_t1_scope_design_v1 as scope


def test_builds_hash_closed_static_pack_for_exact_frozen_15_plus_32_cases():
    value = pack.build_pack()
    assert value["status"] == "static_definition_control_pack_rendered_in_memory_not_materialized"
    assert value["case_counts"] == {
        "qualification": 15,
        "production": 32,
        "total": 47,
        "definition_files": 47,
        "control_files": 47,
    }
    expected_ids = {
        row["case_id"] for row in scope.qualification_matrix() + scope.production_manifest()
    }
    assert {row["case_id"] for row in value["cases"]} == expected_ids
    assert len(value["input_bindings"]) == 94
    assert value["execution_controls"]["definitions_written"] is False
    assert value["execution_controls"]["controls_written"] is False


def test_every_definition_and_control_pair_matches_its_frozen_case():
    value = pack.build_pack()
    for case in value["cases"]:
        definition_path = Path(case["definition"]["path"])
        control_path = Path(case["control"]["path"])
        assert definition_path.parent == control_path.parent
        assert case["definition"]["sha256"]
        assert case["control"]["sha256"]
        assert case["qualification_only"] is (case["kind"] != "production")
        assert case["control_covers_zero_to_timemax"] is True
        assert case["control_extrapolation_required"] is False
        assert case["expected_observation_output_count"] == (
            3 * case["native_output_samples_per_period"] + 1
        )


def test_qualification_matrix_contains_13_spatial_rows_and_two_controls():
    value = pack.build_pack()
    cases = [row for row in value["cases"] if row["qualification_only"]]
    assert sum(row["kind"] == "spatial_anchor" for row in cases) == 9
    assert sum(row["kind"] == "independent_internal" for row in cases) == 4
    assert sum(row["kind"] == "time_step_control" for row in cases) == 1
    assert sum(row["kind"] == "native_output_cadence_control" for row in cases) == 1


def test_time_and_cadence_controls_preserve_requested_cfl_and_native_output():
    value = pack.build_pack()
    by_id = {row["case_id"]: row for row in value["cases"]}
    time_case = by_id["time-q0p5-dp0p0075-cfl0p1"]
    cadence_case = by_id["cadence-q0p5-dp0p0075-output128"]
    assert time_case["cflnumber"] == pytest.approx(0.1)
    assert time_case["native_output_samples_per_period"] == 64
    assert cadence_case["cflnumber"] == pytest.approx(0.2)
    assert cadence_case["native_output_samples_per_period"] == 128
    assert cadence_case["expected_observation_output_count"] == 385


def test_q_half_observation_grid_is_aligned_and_control_covers_exact_timemax():
    value = pack.build_pack()
    base = next(row for row in value["cases"] if row["case_id"] == "space-q0p5-dp0p0075")
    dense = next(row for row in value["cases"] if row["case_id"] == "cadence-q0p5-dp0p0075-output128")
    assert base["control_rows"] == dense["control_rows"]
    assert math.isclose(base["observation_start_s"], dense["observation_start_s"], abs_tol=1e-12)
    assert math.isclose(base["observation_end_s"], dense["observation_end_s"], abs_tol=1e-12)
    assert dense["native_output_samples_per_period"] == 128


def test_control_formula_includes_nonzero_endpoint_when_time_max_is_not_period_boundary():
    row = next(item for item in scope.qualification_matrix() if item["case_id"] == "internal-q0p25-dp0p0075")
    control = pack.render_control(row).decode().splitlines()
    last_time, last_ax = float(control[-1].split(";")[0]), float(control[-1].split(";")[1])
    assert math.isclose(last_time, row["observation_end_s"], abs_tol=1e-12)
    assert abs(last_ax) > 1e-10


def test_xml_uses_fresh_colocated_control_reference_and_has_no_runtime_authority():
    row = scope.qualification_matrix()[0]
    control_name = f"F8_OPC_{row['case_id']}_acceleration.csv"
    xml_bytes = pack.render_definition(row, control_name)
    root = ET.fromstring(xml_bytes)
    ref = root.find("./execution/special/accinputs/accinput/acctimesfile")
    assert ref is not None and ref.get("value") == control_name
    assert b"R008 static input candidate" in xml_bytes
    assert root.find("./casedef/geometry/definition").get("dp") == format(row["dp_m"], ".17g")


def test_pack_is_static_only_and_does_not_create_runtime_case_directories():
    value = pack.build_pack()
    assert value["qualification_credit"] == 0
    assert value["namespace"]["solver_input_directory_created"] is False
    assert value["namespace"]["qualification_case_runtime_directory_created"] is False
    assert value["namespace"]["production_case_runtime_directory_created"] is False
    assert value["execution_authority"]["gencase_authorized"] is False
    assert value["execution_authority"]["native_decoder_authorized"] is False
    assert value["execution_authority"]["solver_authorized"] is False
    assert value["execution_authority"]["new_explicit_native_preflight_authorization_required"] is True
    assert value["execution_controls"]["definitions_rendered_in_memory"] == 47
    assert value["execution_controls"]["controls_rendered_in_memory"] == 47
    assert value["execution_controls"]["definitions_written"] is False
    assert value["execution_controls"]["controls_written"] is False
    assert all(not (pack.LAB / path).exists() for path in pack.FORBIDDEN_RUNTIME_DIRS)


def test_prior_r007_artifacts_are_fingerprinted_but_none_are_reused():
    value = pack.build_pack()
    audit = value["prior_artifact_exclusion_audit"]
    assert audit["scanned_prior_file_count"] == len(audit["scanned_prior_files"]) > 0
    assert audit["r008_input_hash_collision_count"] == 0
    assert audit["r008_input_hash_collisions"] == []
    input_hashes = {item["sha256"] for item in value["input_bindings"]}
    old_hashes = {item["sha256"] for item in audit["scanned_prior_files"]}
    assert input_hashes.isdisjoint(old_hashes)
    assert all(item["path"].startswith(str(pack.R007_ROOT) + "/") for item in audit["scanned_prior_files"])


def test_prior_r007_symlinks_are_not_silently_omitted_from_no_reuse_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "LAB", tmp_path)
    root = tmp_path / pack.R007_ROOT
    root.mkdir(parents=True)
    (root / "dangling").symlink_to(root / "missing", target_is_directory=True)
    with pytest.raises(ValueError, match="unexpanded symlink paths"):
        pack._excluded_r007_artifacts()


def test_prior_r007_scope_root_symlink_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "LAB", tmp_path)
    real_scope = tmp_path / "real-r007"
    real_scope.mkdir()
    root = tmp_path / pack.R007_ROOT
    root.parent.mkdir(parents=True, exist_ok=True)
    root.symlink_to(real_scope, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink scope root"):
        pack._excluded_r007_artifacts()


def test_namespace_guard_rejects_existing_pack_and_broken_symlink(tmp_path):
    existing = tmp_path / "pack"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="existing static-input pack namespace"):
        pack.require_absent_namespace(tmp_path, Path("pack"))

    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "missing", target_is_directory=True)
    with pytest.raises(FileExistsError, match="existing static-input pack namespace"):
        pack.require_absent_namespace(tmp_path, Path("dangling"))


def test_pack_receipt_and_all_input_file_hashes_close_after_materialization(tmp_path):
    temporary_lab = tmp_path / "lab"
    written = pack.write_pack(temporary_lab)
    receipt = json.loads((temporary_lab / pack.RECEIPT_TARGET).read_text(encoding="utf-8"))
    assert receipt == written
    assert receipt["status"] == "static_definition_control_pack_materialized_no_execution_authority"
    assert receipt["materialization"]["all_94_input_hashes_revalidated_after_write"] is True
    assert receipt["execution_controls"]["definitions_written"] is True
    assert receipt["execution_controls"]["controls_written"] is True
    assert receipt["execution_controls"]["gencase_invoked"] is False
    for binding in receipt["source_bindings"]:
        source = pack.LAB / binding["path"]
        assert source.is_file()
        assert source.stat().st_size == binding["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == binding["sha256"]
    for binding in receipt["input_bindings"]:
        source = temporary_lab / binding["path"]
        assert source.is_file()
        assert source.stat().st_size == binding["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == binding["sha256"]
    for binding in receipt["prior_artifact_exclusion_audit"]["scanned_prior_files"]:
        source = pack.LAB / binding["path"]
        assert source.is_file()
        assert source.stat().st_size == binding["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == binding["sha256"]


def test_shared_materialized_pack_is_hash_closed_if_present():
    receipt_path = pack.LAB / pack.RECEIPT_TARGET
    if not receipt_path.exists():
        pytest.skip("shared R008 static pack has not been materialized")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected = pack._close_materialized_pack(pack.build_pack(), pack.LAB)
    assert receipt == expected
    bindings = (
        receipt["source_bindings"]
        + receipt["input_bindings"]
        + receipt["prior_artifact_exclusion_audit"]["scanned_prior_files"]
    )
    for binding in bindings:
        source = pack.LAB / binding["path"]
        assert source.is_file()
        assert source.stat().st_size == binding["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == binding["sha256"]


def test_writer_fails_closed_if_pack_root_exists(tmp_path, monkeypatch):
    target = tmp_path / pack.PACK_ROOT
    target.mkdir(parents=True)
    with pytest.raises(FileExistsError, match="existing static-input pack namespace"):
        pack.write_pack(tmp_path)
