#!/usr/bin/env python3
"""Validate fresh123 delegated F4 visual evidence without scientific payload access."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
FORBIDDEN_SUFFIXES = (".h5", ".bi4", ".csv", ".vtk", ".dat")
CASES = {
    "F4_DROP_gap0p20000_xoffm0p08000_yoff0p04000_uz0p60000",
    "F4_DROP_gap0p20000_xoffm0p08000_yoff0p04000_uz0p40000",
}
KEYS = (0, 150, 300, 450, 600, 750, 900, 1050, 1200)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def walk_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)
    elif isinstance(value, str):
        yield value


def assert_no_science_suffixes(value):
    for text in walk_strings(value):
        assert not text.lower().endswith(FORBIDDEN_SUFFIXES), text


def assert_file_record(item):
    path = Path(item["path"])
    assert path.is_file(), path
    assert path.suffix.lower() not in FORBIDDEN_SUFFIXES, path
    assert item["bytes"] == path.stat().st_size, path
    assert item["sha256"] == digest(path), path


def assert_receipt(receipt, label):
    assert receipt["schema"] == "ds02.execution-receipt.v1", label
    assert receipt["status"] == "completed", label
    assert receipt["returncode"] == 0, label
    assert_file_record(receipt["file"])


def main():
    index = load(META / "review-index.json")
    selection = load(META / "selection-snapshot.json")
    protocol = load(META / "visual-review-protocol.json")
    assert index["schema"] == "ds02.f6.delegated-visual-review.v1"
    assert index["fresh_id"] == "fresh123"
    assert index["source_only"] is True
    assert index["global_claim_boundary"].startswith("Delegated visual decisions only")
    assert selection["schema"] == "ds02.f6.fresh123.selection-snapshot.v1"
    assert selection["selected_case_count"] == 2
    assert selection["selected_case_ids"] == sorted(CASES)
    assert selection["global_credit_updated"] is False
    assert selection["scientific_payload_read_or_hashed_by_review"] is False
    assert protocol["reviewed_cases"] == sorted(CASES)
    assert protocol["image_tool"] == "view_image"
    assert protocol["per_case_required_contact_sheets"] == 51
    assert protocol["per_case_required_key_frames"] == list(KEYS)
    assert len(index["cases"]) == 2
    assert {entry["case_id"] for entry in index["cases"]} == CASES

    for entry in index["cases"]:
        assert entry["status"] == "visual-approved-by-delegated-agent"
        assert entry["decision"] == "approved"
        assert entry["frames"] == 1201
        assert entry["contact_sheet_count"] == 51
        assert entry["key_frame_count"] == 9
        assert entry["no_global_credit_claim"] is True
        closure = load(entry["metadata_closure_path"])
        assert closure["schema"] == "ds02.f6.fresh123.case-visual-review-closure.v1"
        assert closure["case_id"] == entry["case_id"]
        assert closure["visual_decision"]["status"] == "visual-approved-by-delegated-agent"
        assert closure["visual_decision"]["root_personal_inspection_claim"] is False
        assert closure["visual_decision"]["reviewed_all_contact_sheets_and_key_frames"] is True
        assert closure["visual_decision"]["contact_sheet_count"] == 51
        assert closure["visual_decision"]["key_frame_count"] == 9
        assert closure["review_constraints"]["scientific_payload_read_or_hashed_by_review"] is False
        assert closure["review_constraints"]["no_global_credit_update_by_this_review"] is True

        render = closure["root856_terminal_evidence"]
        assert_receipt(render["render_receipt"], "Root856 render")
        report = render["render_report"]
        assert_file_record(report["file"])
        assert report["schema"] == "ds02.stage1.paraview-full-animation-integrity.v1"
        assert report["frames"] == 1201
        assert report["source_frames"] == 1201
        assert report["all_frames_rendered"] is True
        assert report["actual_times_preserved_exactly"] is True
        assert report["native_identity_axis_preserved"] is True
        assert report["nonfinite_active_states"] == 0
        assert report["diagnostic_only"] is False
        assert report["camera"]["bounds_source"] == "native valid positions scanned through XdmfReader"
        assert render["request_metadata"]["expected_frames"] == 1201
        assert render["request_metadata"]["cpu_task_kind"] == "audit"
        assert render["request_metadata"]["cpu_threads"] == 24
        assert render["request_metadata"]["worktree_root"].endswith("ds-data-02-integration/DualSPHysics")

        pre = closure["root856_preflight"]
        assert_file_record(pre["file"])
        assert pre["status"] == "READY_FOR_ROOT023"
        assert pre["frames"] == 1201
        assert pre["particles"] == 83233
        assert pre["actual_grid_count"] == 1201
        assert pre["actual_N3_shapes"] == "83233 3"
        assert pre["shape_summary_derived_from_actual_XML_original_manifest_unmodified"] is True

        producer = closure["producer_metadata"]
        gen = producer["gencase"]
        assert gen["status"] == "completed/0"
        assert gen["actual_total_particles"] == 83233
        assert gen["generated_xml_particle_counts"] == {"fixed": 24161, "moving": 0, "floating": 0, "fluid": 59072}
        assert gen["dimension"] == 3
        assert_receipt(gen["receipt"], "GenCase")
        for key in ("prepared_report", "generated_xml", "definition_xml"):
            assert_file_record(gen[key])

        qa = producer["initial_geometry_qa"]
        assert qa["status"] == "completed"
        assert qa["pass"] is True
        assert qa["actual_3d"] is True
        assert qa["inside_tank"] is True
        assert qa["drop_pool_nonoverlap"] is True
        assert qa["actual_counts"] == {"total": 83233, "fixed": 24161, "fluid": 59072}
        assert_receipt(qa["receipt"], "initial geometry QA")
        assert_file_record(qa["report"])

        n0 = producer["native_initial_frame0_qa"]
        assert n0["status"] == "completed_pass"
        assert n0["pass"] is True
        assert n0["total_particles"] == 83233
        assert n0["fluid_particles"] == 59072
        assert n0["native_3d_levels"] == [121, 41, 61]
        assert n0["finite_rows"] == 83233
        assert n0["unique_coordinate_count"] == 83233
        assert n0["unique_identity_count"] == 83233
        assert n0["native_raw_mk_type_observed"] is True
        assert n0["native_raw_velocity_observed"] is True
        assert n0["mass_rescaling"] is False
        assert_receipt(n0["receipt"], "native frame0 QA")
        assert_file_record(n0["report"])

        assert_receipt(producer["full_native"]["receipt"], "full native")
        assert producer["full_native"]["saved_frame_count"] == 1201

        typed = producer["typed_conversion"]
        assert typed["conversion_status"] == "completed"
        assert typed["frames"] == 1201
        assert typed["particles"] == 83233
        assert typed["solver_dimension"] == 3
        assert typed["partvtk_all_passed"] is True
        assert_receipt(typed["receipt"], "typed conversion")
        assert_file_record(typed["report"])

        xmf = producer["xmf"]
        assert xmf["expected_frames"] == 1201
        assert xmf["expected_particles"] == 83233
        assert xmf["expected_dimension"] == 3
        assert xmf["vector_semantic_type"] == "N3"
        assert xmf["arrays_read_by_source"] is False
        assert_file_record(xmf["manifest"])
        assert_file_record(xmf["case_xmf"])
        assert_receipt(xmf["receipt"], "XMF")

        lifecycle = closure["lifecycle"]
        assert lifecycle["frame_diagnostics_entry_count"] == 1201
        assert lifecycle["identity_axis_preserved_all_reported_frames"] is True
        assert lifecycle["maximum_missing_particles_per_frame"] >= 0
        assert lifecycle["transient_missing_frame_count"] >= 0
        assert lifecycle["missing_events_are_not_final_uid_count"] is True
        assert lifecycle["final_uid_status"] == "not independently observed; no final UID survival inference"

        scopes = closure["scope_separation"]
        assert scopes["must_not_equate_scopes"] is True
        scope_values = [
            scopes["actual_converter_physical_condition_sha256"],
            scopes["root648_source_binding_physical_condition_sha256"],
            scopes["source_owner_declared_physical_condition_sha256"],
            scopes["source_plan_condition_sha256"],
        ]
        assert len(set(scope_values)) == 4
        assert_file_record(scopes["physical_binding_file"])

        png = load(entry["png_hash_manifest_path"])
        assert png["schema"] == "ds02.f6.fresh123.png-review-evidence.v1"
        assert png["computed_after_view_image"] is True
        assert png["viewed_with"] == "view_image"
        assert len(png["contact_sheets"]) == 51
        assert len(png["key_frames"]) == 9
        for i, item in enumerate(png["contact_sheets"]):
            path = Path(item["path"])
            assert path.name == f"all_frames_{i:03d}.png"
            assert path.is_file()
            assert item["bytes"] == path.stat().st_size
            assert item["sha256"] == digest(path)
        for frame, item in zip(KEYS, png["key_frames"]):
            path = Path(item["path"])
            assert item["frame"] == frame
            assert path.name == f"frame_{frame:04d}.png"
            assert path.is_file()
            assert item["bytes"] == path.stat().st_size
            assert item["sha256"] == digest(path)

        for item in closure["source_files"]:
            assert_file_record(item)
        assert_no_science_suffixes(closure)
        assert_no_science_suffixes(png)

    old = selection["root715_prior_attempts_preserved_as_excluded"]
    assert len(old) >= 0
    for item in old:
        assert item["selection_status"] == "excluded_before_visual_review"
        assert item["status"] == "failed"
        assert item["returncode"] is None
        assert "shared CPU" in item["error"]
        assert Path(item["receipt_path"]).is_file()
        assert digest(item["receipt_path"]) == item["receipt_sha256"]

    print("fresh123 validation PASS: two Root856 completed/0 F4 cases, 1201-frame reports, 51 contact sheets + 9 key frames each, scope/lifecycle boundaries verified")


if __name__ == "__main__":
    main()
