#!/usr/bin/env python3
"""Validate fresh119 delegated visual-review metadata and PNG evidence only."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
INDEX = META / "review-index.json"
SNAPSHOT = META / "accepted-source-snapshot.json"
FORBIDDEN_SUFFIXES = (".h5", ".bi4", ".csv", ".vtk", ".dat")
EXPECTED_COUNTS = {
    "total_particles": 83233,
    "fluid_particles": 59072,
    "fixed_particles": 24161,
    "moving_particles": 0,
    "floating_particles": 0,
    "solver_dimension": 3,
    "dp_m": 0.01,
}
EXPECTED_KEYS = (0, 150, 300, 400, 600, 750, 900, 1050, 1200)
EXPECTED_CASES = {
    "F4_DROP_gap0p22000_xoffm0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p22000_xoffm0p08000_yoffm0p04000_uz0p60000",
}


def load(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def path_values(value, key=""):
    if isinstance(value, dict):
        for name, child in value.items():
            yield from path_values(child, name)
    elif isinstance(value, list):
        for child in value:
            yield from path_values(child, key)
    elif isinstance(value, str) and (
        key == "path" or key.endswith("_path") or key.endswith("_paths")
    ):
        yield value


def assert_receipt(summary, label):
    assert summary["status"] == "completed", (label, summary)
    assert summary["returncode"] == 0, (label, summary)
    assert Path(summary["path"]).is_file(), (label, summary)


index = load(INDEX)
snapshot = load(SNAPSHOT)
assert index["schema"] == "ds02.f6.delegated-visual-review.v1"
assert index["fresh_id"] == "fresh119"
assert index["source_only"] is True
assert index["reviewer"] == "/root/f6_endpoint_initial_qa"
assert len(index["cases"]) == 2
assert {entry["case_id"] for entry in index["cases"]} == EXPECTED_CASES
assert snapshot["schema"] == "ds02.f6.fresh119.selection-snapshot.v1"
assert snapshot["root638_inventory"]["case_count"] == 24
assert snapshot["root638_inventory"]["request_json_count"] == 25
assert snapshot["root638_inventory"]["selected_case_count"] == 2
assert snapshot["selected_cases_are_requested_gap021_minusx_plusy_pair"] is False
assert snapshot["selected_cases_are_next_actual_completed_unaccepted_fallback_pair"] is True
assert snapshot["selected_cases_are_official_aligned_lattice_cases"] is True
preferred = snapshot["preferred_pair"]
assert preferred["availability"] == "requested_absent_fallback_actual_root638_renderer_terminal"
assert preferred["selection_rule"].startswith("The requested Root638 .21/-x/+y pair is absent")
assert preferred["requested_case_ids"] == [
    "F4_DROP_gap0p21000_xoffm0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p21000_xoffm0p08000_yoff0p04000_uz0p60000",
]
assert len(preferred["requested_pair_evidence"]) == 3
assert Path(preferred["requested_pair_evidence"][0]["path"]).is_dir()
assert preferred["requested_pair_evidence"][0]["match_count"] == 0
assert preferred["requested_pair_evidence"][0]["request_directory_contains_no_requested_gap021_pair"] is True
for evidence in preferred["requested_pair_evidence"][1:]:
    assert evidence["exists"] is False
    assert not Path(evidence["path"]).exists()
assert preferred["fallback_case_ids"] == [
    "F4_DROP_gap0p22000_xoffm0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p22000_xoffm0p08000_yoffm0p04000_uz0p60000",
]
assert len(preferred["fallback_evidence"]) == 4
for evidence in preferred["fallback_evidence"]:
    assert evidence["exists"] is True
    assert Path(evidence["path"]).is_file(), evidence
for evidence in preferred["fallback_evidence"][1::2]:
    assert evidence["status"] == "completed"
    assert evidence["returncode"] == 0
assert snapshot["selection_boundary"].startswith("The requested Root638 .21/-x/+y pair is absent")

for entry in index["cases"]:
    case_id = entry["case_id"]
    assert entry["root638_lineage"] is True
    assert entry["status"] == "visual-approved-by-delegated-agent"
    assert entry["decision"] == "approved"
    assert entry["contact_sheet_count"] == 51
    assert entry["key_frame_count"] == 9
    assert entry["frames"] == 1201
    assert entry["no_global_credit_claim"] is True

    closure_path = Path(entry["metadata_closure_path"])
    assert closure_path.is_file(), closure_path
    closure = load(closure_path)
    assert closure["schema"] == "ds02.f6.fresh119.case-visual-review-closure.v1"
    assert closure["case_id"] == case_id
    assert closure["source_only"] is True
    assert closure["selection"]["root638_lineage"] is True
    assert closure["selection"]["root638_inventory_case_count"] == 24
    assert closure["selection"]["case_not_in_prior_visual_review_batches"] is True
    assert closure["visual_decision"]["status"] == "visual-approved-by-delegated-agent"
    assert closure["visual_decision"]["root_personal_inspection_claim"] is False

    png_path = Path(closure["png_assets"]["hash_manifest_path"])
    assert png_path.is_file(), png_path
    png = load(png_path)
    assert png["schema"] == "ds02.f6.fresh119.png-review-evidence.v1"
    assert png["computed_after_view_image"] is True
    assert png["viewed_with"] == "view_image"
    assert png["contact_sheet_count"] == 51
    assert png["key_frame_count"] == 9
    assert len(png["contact_sheets"]) == 51
    assert len(png["key_frames"]) == 9
    for expected_index, item in enumerate(png["contact_sheets"]):
        path = Path(item["path"])
        assert path.name == f"all_frames_{expected_index:03d}.png"
        assert path.is_file(), path
        assert item["bytes"] == path.stat().st_size
        assert item["sha256"] == sha256(path), path
    for expected_frame, item in zip(EXPECTED_KEYS, png["key_frames"]):
        path = Path(item["path"])
        assert item["frame"] == expected_frame
        assert path.name == f"frame_{expected_frame:04d}.png"
        assert path.is_file(), path
        assert item["bytes"] == path.stat().st_size
        assert item["sha256"] == sha256(path), path

    producer = closure["producer_metadata"]
    required_path_keys = (
        "gencase_receipt_path",
        "prepared_input_report_path",
        "generated_xml_path",
        "generated_definition_xml_path",
        "basic_qa_receipt_path",
        "basic_qa_report_path",
        "frame0_qa_receipt_path",
        "initial_native_qa_report_path",
        "native_receipt_path",
        "typed_receipt_path",
        "conversion_report_path",
        "xmf_receipt_path",
        "xmf_manifest_path",
        "render_receipt_path",
        "render_report_path",
    )
    for key in required_path_keys:
        assert Path(producer[key]).is_file(), (case_id, key, producer[key])
    assert Path(closure["selection"]["root638_request_path"]).is_file()

    for label in ("gencase_receipt", "basic_qa_receipt", "frame0_qa_receipt",
                  "native_receipt", "typed_receipt", "xmf_receipt", "render_receipt"):
        assert_receipt(producer[label], label)

    prepared = load(producer["prepared_input_report_path"])
    basic = load(producer["basic_qa_report_path"])
    frame0 = load(producer["initial_native_qa_report_path"])
    frame0_case = frame0["cases"][0]
    conversion = load(producer["conversion_report_path"])
    manifest = load(producer["xmf_manifest_path"])
    render = load(producer["render_report_path"])

    assert producer["gencase_counts"] == EXPECTED_COUNTS
    assert prepared["actual_total_particles"] == 83233
    assert prepared["generated_xml_particle_counts"] == {
        "fixed": 24161,
        "moving": 0,
        "floating": 0,
        "fluid": 59072,
    }
    assert frame0["schema"] == "ds02.f4.fresh097.native-frame0-partvtk-vz-audit.v1"
    assert frame0_case["pass"] is True
    assert frame0_case["actual_total_particles"] == 83233
    assert frame0_case["fluid_rows"] == 59072
    assert frame0_case["finite_rows"] == 83233
    assert frame0_case["unique_coordinate_count"] == 83233
    assert frame0_case["unique_identity_count"] == 83233
    assert frame0_case["native_raw_mk_type_observed"] is True
    assert frame0_case["native_raw_velocity_observed"] is True
    assert frame0_case["mass_rescaling"] is False
    assert basic["arrays_read_by_source"] is False
    assert basic["audit"]["pass"] is True
    assert basic["audit"]["inside_tank"] is True
    assert basic["q_n_status"] == "not_assessed"
    assert basic["production_approval"] == "none"

    assert conversion["conversion_status"] == "completed"
    assert conversion["frames"] == 1201
    assert conversion["particles"] == 83233
    assert conversion["solver_dimension"]["solver_dimension"] == 3
    assert conversion["partvtk_validation"]["all_passed"] is True
    assert manifest["expected_frames"] == 1201
    assert manifest["expected_particles"] == 83233
    assert manifest["expected_dimension"] == 3
    assert manifest["fluid_particles_expected"] == 59072
    assert manifest["physical_condition_sha256"] == closure["scope_separation"]["actual_converter_physical_condition_sha256"]
    assert manifest["source_plan_condition_sha256"] == closure["scope_separation"]["source_plan_condition_sha256"]
    assert manifest["arrays_read_by_source"] is False
    assert manifest["jobs_started_by_source"] is False
    assert manifest["production_approval"] == "none"
    assert manifest["q_n_status"] == "not_assessed"
    assert manifest["precision_status"] == "not_accepted"

    assert render["frames"] == 1201
    assert render["source_frames"] == 1201
    assert render["all_frames_rendered"] is True
    assert render["actual_times_preserved_exactly"] is True
    assert render["native_identity_axis_preserved"] is True
    assert render["nonfinite_active_states"] == 0
    assert render["diagnostic_only"] is False

    lifecycle = closure["lifecycle"]
    actual_lifecycle = conversion["lifecycle"]
    assert lifecycle["producer_transient_missing_frame_count"] == actual_lifecycle["transient_missing_frame_count"]
    assert lifecycle["producer_first_missing_frame_by_type"] == actual_lifecycle["first_missing_frame_by_type"]
    assert lifecycle["producer_first_missing_frame_by_mk"] == actual_lifecycle["first_missing_frame_by_mk"]
    assert lifecycle["producer_transient_missing_by_type_frame_events"] == actual_lifecycle["transient_missing_by_type_frame_events"]
    assert lifecycle["producer_transient_missing_by_mk_frame_events"] == actual_lifecycle["transient_missing_by_mk_frame_events"]
    assert lifecycle["maximum_missing_particles_per_frame"] is None
    assert lifecycle["late_uid_exclusions_recorded_by_this_review"] == []
    assert "not infer" in lifecycle["maximum_missing_particles_note"].lower()

    scopes = closure["scope_separation"]
    actual_owner = load(scopes["actual_owner_file_path"])
    source_owner = load(scopes["source_owner_path"])
    assert scopes["must_not_equate_scopes"] is True
    assert scopes["actual_converter_equals_manifest_consumer_binding"] is True
    assert scopes["actual_converter_physical_condition_sha256"] == manifest["physical_condition_sha256"]
    assert scopes["manifest_consumer_physical_binding_sha256"] == manifest["physical_condition_sha256"]
    assert scopes["actual_converter_physical_condition_sha256"] != scopes["actual_owner_file_declared_physical_condition_sha256"]
    assert scopes["actual_owner_file_declared_physical_condition_sha256"] == scopes["source_owner_declared_physical_condition_sha256"]
    assert scopes["source_declared_and_source_plan_are_not_equated_to_actual"] is True
    assert scopes["source_plan_condition_sha256"] == manifest["source_plan_condition_sha256"]
    assert sha256(Path(scopes["actual_owner_file_path"])) == scopes["actual_owner_file_sha256"]
    assert sha256(Path(scopes["source_owner_path"])) == scopes["source_owner_sha256"]
    assert actual_owner["physical_condition_sha256"] == scopes["actual_owner_file_declared_physical_condition_sha256"]
    assert source_owner["physical_condition_sha256"] == scopes["source_owner_declared_physical_condition_sha256"]
    assert sha256(Path(producer["generated_xml_path"])) == producer["generated_xml_sha256_attested_by_gencase"]
    assert sha256(Path(producer["generated_definition_xml_path"])) == producer["generated_definition_xml_sha256"]

    for value in path_values(closure):
        assert not value.lower().endswith(FORBIDDEN_SUFFIXES), value
    for value in path_values(png):
        assert not value.lower().endswith(FORBIDDEN_SUFFIXES), value

print("fresh119 validation PASS: 2 delegated Root638 F4 cases, 102 contact sheets, 18 key PNGs, producer metadata and scope separation verified")

