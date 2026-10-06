#!/usr/bin/env python3
"""Validate fresh114 metadata and viewed PNG evidence without reading science payloads."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "metadata" / "review-index.json"
SNAPSHOT = ROOT / "metadata" / "accepted-source-snapshot.json"
FORBIDDEN_SUFFIXES = (".h5", ".bi4", ".csv", ".vtk", ".dat")


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


index = load(INDEX)
snapshot = load(SNAPSHOT)
assert index["schema"] == "ds02.f6.delegated-visual-review.v1"
assert index["fresh_id"] == "fresh114"
assert index["source_only"] is True
assert index["reviewer"] == "/root/f6_endpoint_initial_qa"
assert len(index["cases"]) == 2
assert snapshot["root638_inventory"]["gap0p20_case_count"] == 0
assert snapshot["root638_inventory"]["case_count"] == 24
assert snapshot["selected_cases_are_official_aligned_lattice_cases"] is True

for entry in index["cases"]:
    assert entry["status"] == "visual-approved-by-delegated-agent"
    assert entry["decision"] == "approved"
    assert entry["root638_gap20_case"] is False
    assert entry["contact_sheet_count"] == 51
    assert entry["key_frame_count"] == 9
    assert entry["frames"] == 1201

    closure_path = Path(entry["metadata_closure_path"])
    assert closure_path.is_file(), closure_path
    closure = load(closure_path)
    assert closure["schema"] == "ds02.f6.fresh114.case-visual-review-closure.v1"
    assert closure["visual_decision"]["status"] == "visual-approved-by-delegated-agent"
    assert closure["visual_decision"]["root_personal_inspection_claim"] is False
    assert closure["selection"]["root638_lineage"] is False
    assert closure["selection"]["root638_gap20_inventory_count"] == 0

    png_manifest_path = Path(closure["png_assets"]["hash_manifest"])
    assert png_manifest_path.is_file(), png_manifest_path
    png_manifest = load(png_manifest_path)
    assert png_manifest["computed_after_view_image"] is True
    assert len(png_manifest["contact_sheets"]) == 51
    assert len(png_manifest["key_frames"]) == 9
    for expected_index, item in enumerate(png_manifest["contact_sheets"]):
        path = Path(item["path"])
        assert path.name == f"all_frames_{expected_index:03d}.png"
        assert path.is_file(), path
        assert item["bytes"] == path.stat().st_size
        assert item["sha256"] == sha256(path), path
    expected_keys = (0, 150, 300, 400, 600, 750, 900, 1050, 1200)
    for expected_frame, item in zip(expected_keys, png_manifest["key_frames"]):
        path = Path(item["path"])
        assert item["frame"] == expected_frame
        assert path.name == f"frame_{expected_frame:04d}.png"
        assert path.is_file(), path
        assert item["bytes"] == path.stat().st_size
        assert item["sha256"] == sha256(path), path

    producer = closure["producer_metadata"]
    for name in (
        "gencase_receipt",
        "prepared_input_report",
        "generated_xml_path",
        "native_receipt",
        "initial_native_qa_report",
        "typed_receipt",
        "conversion_report",
        "xmf_manifest",
        "xmf_receipt",
        "render_report",
        "render_receipt",
    ):
        assert Path(producer[name]).is_file(), producer[name]

    for receipt_name in (
        "gencase",
        "native",
        "typed",
        "xmf",
        "render",
    ):
        receipt = producer[receipt_name]
        assert receipt["status"] == "completed", (entry["case_id"], receipt_name)
        assert receipt["returncode"] == 0, (entry["case_id"], receipt_name)

    qa = load(producer["initial_native_qa_report"])
    assert qa["pass"] is True
    assert qa["native_audit_returncode"] == 0
    assert qa["checks"]["true_3d"] is True
    assert qa["checks"]["finite_unique_complete_ids"] is True
    assert qa["checks"]["complete_type_partition"] is True
    assert qa["checks"]["finite_tank_face_coverage"] is True
    assert qa["q_n_status"] == "not_assessed"
    assert qa["production_approval"] == "none"

    manifest = load(producer["xmf_manifest"])
    assert manifest["case_id"] == entry["case_id"]
    assert manifest["expected_frames"] == 1201
    assert manifest["expected_particles"] == 83233
    assert manifest["expected_dimension"] == 3
    assert manifest["fluid_particles_expected"] == 59072
    assert manifest["actual_typed_counts"]["frames"] == 1201
    assert manifest["actual_typed_counts"]["particles"] == 83233
    assert manifest["actual_typed_counts"]["partvtk_all_passed"] is True

    render = load(producer["render_report"])
    assert render["frames"] == 1201
    assert render["source_frames"] == 1201
    assert render["all_frames_rendered"] is True
    assert render["actual_times_preserved_exactly"] is True
    assert render["native_identity_axis_preserved"] is True
    assert render["nonfinite_active_states"] == 0
    assert render["diagnostic_only"] is False

    counts = producer["gencase_counts"]
    assert counts == {
        "total_particles": 83233,
        "fluid_particles": 59072,
        "fixed_particles": 24161,
        "moving_particles": 0,
        "floating_particles": 0,
        "solver_dimension": 3,
        "dp_m": 0.01,
    }
    lifecycle = closure["lifecycle"]
    assert lifecycle["producer_transient_missing_frame_count"] == 0
    assert lifecycle["late_uid_exclusions_recorded_by_this_review"] == []

    scopes = closure["scope_separation"]
    assert scopes["must_not_equate_scopes"] is True
    assert scopes["actual_converter_equals_consumer_canonical_after_schema_repair"] is True
    assert scopes["source_declared_and_source_plan_are_not_equated_to_actual"] is True
    assert scopes["actual_converter_physical_condition_sha256"] == manifest[
        "physical_condition_sha256"
    ]
    assert scopes["canonical_owner_consumer_physical_binding_sha256"] == manifest[
        "physical_condition_sha256"
    ]
    assert scopes["source_plan_condition_sha256"] == manifest[
        "source_plan_condition_sha256"
    ]
    owner_path = Path(scopes["consumer_owner_path"])
    assert owner_path.is_file(), owner_path
    assert sha256(owner_path) == scopes["consumer_owner_sha256"]
    source_owner_path = Path(scopes["source_owner_path"])
    assert source_owner_path.is_file(), source_owner_path
    assert sha256(source_owner_path) == scopes["source_owner_sha256"]

    historical = producer["historical_typed_failure"]
    if historical is not None:
        old_receipt = load(historical["receipt"])
        assert old_receipt["status"] == "failed"
        assert old_receipt["returncode"] == 1
        assert historical["preserved"] is True

    for value in path_values(closure):
        assert not value.lower().endswith(FORBIDDEN_SUFFIXES), value

print("fresh114 validation PASS: 2 delegated F4 cases, 102 contact sheets, 18 key PNGs, producer metadata and scope separation verified")
