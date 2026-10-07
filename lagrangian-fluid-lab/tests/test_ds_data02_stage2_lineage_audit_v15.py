from __future__ import annotations

import hashlib
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_lineage_audit_v15 as audit  # noqa: E402


def _asset(content_sha: str, *, end: float = 4.0) -> dict:
    return {
        "asset_kind": "motion_table",
        "selected": {
            "content_sha256": content_sha,
            "time_coverage_s": [0.0, end],
            "header": ["Time", "Degrees"],
        },
    }


def _command(case_path: str, *, tmax: str = "4", case_flag: str | None = None) -> dict:
    semantic = [{"key": "mdbc_noslip", "value": "1"}]
    if case_flag is not None:
        semantic.append({"key": "case_label", "value": case_flag})
    return {
        "semantic_cli_overrides": semantic,
        "prepared_input_path": case_path,
        "solver_tmax_s": float(tmax),
    }


def test_effective_key_excludes_case_resolution_particles_and_save_window() -> None:
    physical = {
        "case_id": "case-a",
        "physical_case_id": "condition-a",
        "geometry": {"size_m": [1.0, 2.0, 3.0], "dp_m": 0.01},
        "initial_state": {"velocity_m_per_s": [0.0, 0.0, 0.0], "particle_count": 1000},
        "saved_window_s": [0.0, 4.0],
    }
    physical_variant = {
        **physical,
        "case_id": "case-b",
        "physical_case_id": "condition-b",
        "geometry": {"size_m": [1.0, 2.0, 3.0], "dp_m": 0.02},
        "initial_state": {"velocity_m_per_s": [0.0, 0.0, 0.0], "particle_count": 2000},
        "saved_window_s": [0.0, 8.0],
    }
    xml = {"control_class": "PRESCRIBED_FILE_MOTION", "control_nodes": []}
    first = audit.build_condition_keys(physical, xml, _command("/old/case-a", tmax="4"), _asset("a" * 64, end=4.0))
    second = audit.build_condition_keys(physical_variant, xml, _command("/new/case-b", tmax="8"), _asset("a" * 64, end=8.0))
    # The asset coverage is control evidence, so a changed source window is
    # intentionally visible in the control key.  The physical key remains
    # equal because all removed values are numerical/discrete identity.
    assert first["physical_key_sha256"] == second["physical_key_sha256"]
    assert first["effective_key_sha256"] != second["effective_key_sha256"]


def test_effective_key_changes_for_motion_content_sha() -> None:
    physical = {"geometry": {"size_m": [1.0, 2.0, 3.0]}, "initial_state": {"velocity_m_per_s": [0.0, 0.0, 0.0]}}
    xml = {"control_class": "PRESCRIBED_FILE_MOTION", "control_nodes": []}
    first = audit.build_condition_keys(physical, xml, _command("/case-a"), _asset("a" * 64))
    second = audit.build_condition_keys(physical, xml, _command("/case-b"), _asset("b" * 64))
    assert first["effective_key_sha256"] != second["effective_key_sha256"]


def test_parse_f3_acceleration_table_reports_units_and_coverage(tmp_path: Path) -> None:
    path = tmp_path / "CaseSloshingAccData.csv"
    path.write_text(
        "#Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ\n"
        "0;0;0;-9.81;0;0.3;0\n"
        "0.5;0.1;0;-9.81;0;0.2;0\n"
        "1.0;0.2;0;-9.81;0;0.1;0\n"
    )
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    result = audit.parse_control_asset(path, declared_sha256=expected, solver_tmax_s=1.2)
    assert result["status"] == "PARSED_MONOTONIC_TABLE"
    assert result["time_coverage_s"] == [0.0, 1.0]
    assert result["coverage_status"] == "CONTROL_ASSET_END_BEFORE_SOLVER_TMAX"
    assert result["units"]["LinearAcc*"] == "m/s^2"
    assert result["units"]["AngularAcc*"] == "rad/s^2"


def test_parse_f5_motion_table_reports_hash_and_monotonic_time(tmp_path: Path) -> None:
    path = tmp_path / "f5_motion.dat"
    path.write_text("0\t0.0\n0.5\t0.1\n1.0\t0.0\n")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    result = audit.parse_control_asset(path, declared_sha256=expected, solver_tmax_s=1.0)
    assert result["status"] == "PARSED_MONOTONIC_TABLE"
    assert result["content_hash_status"] == "HASH_MATCH"
    assert result["coverage_status"] == "COVERS_SOLVER_TMAX"
    assert result["strictly_increasing_time"] is True


def test_receipt_running_without_finish_is_explicitly_incomplete() -> None:
    expected = "a" * 64
    result = audit._receipt_hash_status(
        {"status": "running", "returncode": None,
         "input_hashes_at_launch": {"xml": expected}, "input_hashes_after_run": {}},
        expected,
    )
    assert result["status"] == "INCOMPLETE_RUNNING_NO_FINISH_HASH_SUPPORT"
    assert result["launch_hash_supported"] is True
    assert result["finish_hash_supported"] is False


def test_gencase_generated_xml_is_separate_from_def_input(tmp_path: Path) -> None:
    output_root = tmp_path / "gencase"
    output_root.mkdir()
    xml_path = output_root / "case.xml"
    xml_path.write_text("<case />\n")
    definition = tmp_path / "case_Def.xml"
    definition.write_text("<definition />\n")
    receipt = {
        "status": "completed", "returncode": 0, "output_root": str(output_root),
        "input_hashes_at_launch": {str(definition): hashlib.sha256(definition.read_bytes()).hexdigest()},
        "input_hashes_after_run": {str(definition): hashlib.sha256(definition.read_bytes()).hexdigest()},
    }
    xml_sha = hashlib.sha256(xml_path.read_bytes()).hexdigest()
    result = audit._gencase_evidence({}, xml_path, xml_sha, receipt)
    assert result["generated_xml_is_output_not_expected_input"] is True
    assert result["generated_xml"]["output_status"] == "GENCASE_OUTPUT_XML_HASH_MATCH"
    assert result["input_definition_hash_support_complete"] is True


def test_run_out_uses_exact_receipt_command_output_directory(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    solver_output = attempt / "solver_output"
    solver_output.mkdir(parents=True)
    run_out = solver_output / "Run.out"
    run_out.write_text("exact output\n")
    solver = {
        "output_root": str(attempt),
        "command": ["DualSPHysics", "-gpu:0", str(attempt / "prepared"), str(solver_output), "-tmax:1"],
    }
    result = audit._run_out_summary(solver)
    assert result["status"] == "FOUND_AT_RECEIPT_COMMAND_OUTPUT"
    assert result["path"] == str(run_out)
    assert result["command_output_path"] == str(solver_output)
    assert result["searched_glob"] is False

    # A sibling Run.out at output_root is not an acceptable substitute for a
    # missing file under the exact command output argument.
    run_out.unlink()
    (attempt / "Run.out").write_text("wrong sibling\n")
    missing = audit._run_out_summary(solver)
    assert missing["status"] == "MISSING_AT_RECEIPT_COMMAND_OUTPUT"
    assert missing["path"] == str(run_out)


def test_gencase_finish_support_is_required_for_complete_definition_evidence(tmp_path: Path) -> None:
    output_root = tmp_path / "gencase"
    output_root.mkdir()
    xml_path = output_root / "case.xml"
    xml_path.write_text("<case />\n")
    definition = tmp_path / "case_Def.xml"
    definition.write_text("<definition />\n")
    declared = hashlib.sha256(definition.read_bytes()).hexdigest()
    receipt = {
        "status": "running", "returncode": None, "output_root": str(output_root),
        "input_hashes_at_launch": {str(definition): declared},
        "input_hashes_after_run": {},
    }
    xml_sha = hashlib.sha256(xml_path.read_bytes()).hexdigest()
    result = audit._gencase_evidence({}, xml_path, xml_sha, receipt)
    assert result["input_definition_hash_support_complete"] is False
    assert result["input_definition_hash_support_status"] == "LAUNCH_ONLY_NO_FINISH_DEFINITION_HASH_SUPPORT"
    assert result["input_definition_hash_support"]["finish_map_present"] is False


def test_opaque_owner_hashes_are_provenance_only_for_continuous_physical_key() -> None:
    physical = {"geometry": {"size_m": [1.0, 2.0, 3.0]}, "initial_state": {"gravity": 9.81}}
    xml = {"control_class": "STATIC_OR_UNFORCED_DECLARATION", "control_nodes": []}
    command = _command("/case-a")
    asset = _asset("a" * 64)
    first_payload = audit._physical_key_payload(
        physical, owner_hashes={"physical_condition_sha256": ["a" * 64]},
        manifest_hashes=["b" * 64])
    second_payload = audit._physical_key_payload(
        physical, owner_hashes={"physical_condition_sha256": ["c" * 64]},
        manifest_hashes=["d" * 64])
    first = audit.build_condition_keys(first_payload, xml, command, asset)
    second = audit.build_condition_keys(second_payload, xml, command, asset)
    assert first["physical_key_sha256"] == second["physical_key_sha256"]
    assert first_payload == second_payload == {"physical_evidence": physical}


def test_raw_to_typed_to_label_plan_keeps_real_catalog_bindings_and_unknown_closure(tmp_path: Path) -> None:
    current = tmp_path / "CURRENT336.json"
    current.write_text("{\"schema\": \"fixture\"}\n")
    audited = [{
        "case_index": 7,
        "family_id": "F5",
        "physical_case_id": "case",
        "source_hash_evidence": {
            "generated_xml": {"path": "/source/case.xml", "actual_sha256": "a" * 64, "status": "HASH_MATCH"},
        },
        "control": {"asset": {"assets": []}},
        "catalog_source_index": {
            "raw_root": {"path": "/raw/data"},
            "trajectory": {"path": "/typed/trajectory.h5", "producer_declared_sha256": "b" * 64, "bytes": 12},
            "conversion_report": {"path": "/typed/conversion-report.json", "recomputed_sha256": "c" * 64},
        },
    }]
    plan = audit._raw_to_typed_to_label_plan(current, audited)
    assert plan["status"] == "DEVELOPMENT_ONLY_RAW_TO_TYPED_TO_LABEL_INCOMPLETE"
    assert plan["source_inventory"][0]["native_raw_anchor"]["path"] == "/raw/data"
    assert plan["source_inventory"][0]["typed_trajectory"]["status"] == "PRODUCER_DECLARED_STAT_ONLY_NOT_READ"
    assert "raw_to_typed_reconstruction_receipt" in plan["known_not_closed"]
    assert plan["scope"]["typed_hdf5_opened"] is False
