#!/usr/bin/env python3
"""Validate fresh125 visual evidence without reading scientific payloads."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
FORBIDDEN = (".h5", ".bi4", ".csv", ".vtk", ".dat")
CASES = {
    "F4_DROP_gap0p20000_xoffm0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p20000_xoffm0p08000_yoffm0p04000_uz0p60000",
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


def no_science_suffixes(value):
    for text in walk_strings(value):
        assert not text.lower().endswith(FORBIDDEN), text


def file_record(item):
    path = Path(item["path"])
    assert path.is_file(), path
    assert path.suffix.lower() not in FORBIDDEN, path
    assert item["bytes"] == path.stat().st_size, path
    assert item["sha256"] == digest(path), path


def receipt(item, label):
    assert item["schema"] == "ds02.execution-receipt.v1", label
    assert item["status"] == "completed", label
    assert item["returncode"] == 0, label
    file_record(item["file"])


def main():
    index = load(META / "review-index.json")
    selection = load(META / "selection-snapshot.json")
    protocol = load(META / "visual-review-protocol.json")
    assert index["schema"] == "ds02.f6.delegated-visual-review.v1"
    assert index["fresh_id"] == "fresh125"
    assert index["source_only"] and not index["global_credit_updated"]
    assert not index["scientific_payload_read_or_hashed_by_review"]
    assert {x["case_id"] for x in index["cases"]} == CASES
    assert selection["schema"] == "ds02.f6.fresh125.selection-snapshot.v1"
    assert selection["selected_case_ids"] == sorted(CASES)
    assert not selection["global_credit_updated"]
    assert not selection["scientific_payload_read_or_hashed_by_review"]
    assert protocol["reviewed_cases"] == sorted(CASES)
    assert protocol["image_tool"] == "view_image"
    assert protocol["per_case_required_contact_sheets"] == 51
    assert protocol["per_case_required_key_frames"] == list(KEYS)
    no_science_suffixes(index)
    no_science_suffixes(selection)
    no_science_suffixes(protocol)

    for entry in index["cases"]:
        case = entry["case_id"]
        assert case in CASES and "yoffm0p04000" in case
        assert entry["status"] == "visual-approved-by-delegated-agent"
        assert entry["decision"] == "approved"
        assert (entry["frames"], entry["contact_sheet_count"], entry["key_frame_count"]) == (1201, 51, 9)
        assert entry["no_global_credit_claim"] and not entry["root_personal_inspection_claim"]
        closure = load(entry["metadata_closure_path"])
        assert closure["schema"] == "ds02.f6.fresh125.case-visual-review-closure.v1"
        assert closure["case_id"] == case and closure["source_only"]
        visual = closure["visual_decision"]
        assert visual["status"] == "visual-approved-by-delegated-agent"
        assert visual["decision"] == "approved"
        assert visual["reviewed_all_contact_sheets_and_key_frames"]
        assert not visual["root_personal_inspection_claim"]
        assert visual["reviewed_contact_sheet_indices"] == list(range(51))
        assert visual["reviewed_key_frame_indices"] == list(KEYS)
        assert not closure["review_constraints"]["scientific_payload_read_or_hashed_by_review"]
        assert not closure["review_constraints"]["global_case_credit_updated_by_review"]

        terminal = closure["root856_terminal_evidence"]
        receipt(terminal["render_receipt"], "Root856 render")
        for k in ("render_request_file", "render_binding_file", "render_preflight_file"):
            file_record(terminal[k])
        req = terminal["render_request_metadata"]
        assert req["cpu_task_kind"] == "audit"
        assert req["cpu_threads"] == 24
        assert req["expected_frames"] == 1201
        assert req["arrays_read_by_source"] is False and req["jobs_started_by_source"] is False
        assert req["worktree_root"].endswith("ds-data-02-integration/DualSPHysics")
        report = terminal["render_report"]
        file_record(report["file"])
        for k, expected in {
            "schema": "ds02.stage1.paraview-full-animation-integrity.v1",
            "frames": 1201,
            "source_frames": 1201,
            "all_frames_rendered": True,
            "actual_times_preserved_exactly": True,
            "native_identity_axis_preserved": True,
            "nonfinite_active_states": 0,
            "diagnostic_only": False,
        }.items():
            assert report[k] == expected, (case, k, report[k])
        assert report["camera"]["bounds_source"] == "native valid positions scanned through XdmfReader"
        assert report["frame_diagnostics_summary"]["entry_count"] == 1201
        pre = terminal["root856_preflight"]
        file_record(pre["file"])
        assert pre["preflight"]["status"] == "READY_FOR_ROOT023"
        assert pre["actual_grid_count"] == 1201
        assert pre["actual_N3_shapes"] == "83233 3"
        assert pre["shape_summary_derived_from_actual_XML_original_manifest_unmodified"]

        producer = closure["producer_metadata"]
        gen = producer["gencase"]
        assert gen["status"] == "completed/0"
        assert gen["actual_total_particles"] == 83233
        assert gen["generated_xml_particle_counts"] == {"fixed": 24161, "moving": 0, "floating": 0, "fluid": 59072}
        assert gen["dimension"] == 3 and gen["data2d"] is False
        receipt(gen["receipt"], "GenCase")
        for k in ("prepared_report", "generated_xml", "generated_definition_xml", "source_definition_xml"):
            file_record(gen[k])

        qa = producer["initial_geometry_qa"]
        assert qa["status"] == "completed" and qa["pass"]
        assert qa["actual_3d"] and qa["inside_tank"] and qa["drop_pool_nonoverlap"]
        assert qa["finite_positions"] and qa["unique_complete_initial_uid"]
        assert qa["actual_counts"] == {"total": 83233, "fixed": 24161, "fluid": 59072}
        receipt(qa["receipt"], "initial geometry QA")
        file_record(qa["report"])

        n0 = producer["native_initial_frame0_qa"]
        assert n0["status"] == "completed_pass" and n0["pass"]
        assert n0["actual_total_particles"] == 83233 and n0["fluid_particles"] == 59072
        assert n0["finite_rows"] == n0["unique_coordinate_count"] == n0["unique_identity_count"] == 83233
        assert n0["native_3d_levels"] == [121, 41, 61]
        assert n0["native_raw_mk_type_observed"] and n0["native_raw_velocity_observed"]
        assert not n0["gencase_declared_velocity_used_as_evidence"] and not n0["mass_rescaling"]
        receipt(n0["receipt"], "native frame0 QA")
        file_record(n0["report"])

        assert producer["full_native"]["saved_frame_count"] == 1201
        receipt(producer["full_native"]["receipt"], "full native")
        typed = producer["typed_conversion"]
        assert typed["conversion_status"] == "completed"
        assert (typed["frames"], typed["particles"], typed["solver_dimension"]) == (1201, 83233, 3)
        assert typed["partvtk_all_passed"] and typed["time_evidence"]["strictly_increasing"]
        receipt(typed["receipt"], "typed conversion")
        file_record(typed["report"])

        xmf = producer["xmf"]
        assert (xmf["expected_frames"], xmf["expected_particles"], xmf["expected_dimension"]) == (1201, 83233, 3)
        assert xmf["vector_semantic_type"] == "N3" and not xmf["arrays_read_by_source"]
        assert xmf["future_output_hashes_null"]
        receipt(xmf["receipt"], "XMF")
        file_record(xmf["manifest"])
        file_record(xmf["case_xmf"])

        life = closure["lifecycle"]
        assert life["frame_diagnostics_entry_count"] == 1201
        assert life["identity_axis_preserved_all_reported_frames"]
        assert life["transient_missing_frame_count"] >= 0
        assert life["maximum_missing_particles_per_frame"] >= 0
        assert life["missing_events_are_not_final_uid_count"]
        assert life["final_uid_status"] == "not independently observed; visual review does not infer final UID survival"
        if case.endswith("uz0p40000"):
            assert life["transient_missing_frame_count"] == 105
            assert life["maximum_missing_particles_per_frame"] == 3
            assert life["final_frame_missing_particles"] == 3
        else:
            assert life["transient_missing_frame_count"] == 0
            assert life["maximum_missing_particles_per_frame"] == 0
            assert life["final_frame_missing_particles"] == 0

        scopes = closure["scope_separation"]
        assert scopes["must_not_equate_scopes"]
        assert scopes["actual_converter_physical_condition_sha256"] == scopes["canonical_converter_owner_physical_binding_sha256"]
        assert scopes["actual_converter_physical_condition_sha256"] == scopes["xmf_manifest_declared_physical_condition_sha256"]
        assert scopes["actual_converter_physical_condition_sha256"] not in {
            scopes["root648_source_binding_scope_sha256"],
            scopes["source_owner_declared_physical_condition_sha256"],
            scopes["source_plan_condition_sha256"],
        }
        for k in ("source_owner_file", "converter_owner_file", "typed_binding_file", "xmf_binding_file", "render_binding_file"):
            file_record(scopes[k])

        png = load(entry["png_hash_manifest_path"])
        assert png["schema"] == "ds02.f6.fresh125.png-review-evidence.v1"
        assert png["computed_after_view_image"] and png["viewed_with"] == "view_image"
        assert len(png["contact_sheets"]) == 51 and len(png["key_frames"]) == 9
        for i, item in enumerate(png["contact_sheets"]):
            assert Path(item["path"]).name == f"all_frames_{i:03d}.png"
            file_record(item)
        for frame, item in zip(KEYS, png["key_frames"]):
            assert item["frame"] == frame
            assert Path(item["path"]).name == f"frame_{frame:04d}.png"
            file_record(item)
        file_record(png["render_report_file"])
        for item in closure["source_files"]:
            file_record(item)
        no_science_suffixes(closure)
        no_science_suffixes(png)

    print("fresh125 validation PASS: two Root856 yoffm F4 cases, 1201-frame reports, 51 contact sheets + 9 keyframes each, lifecycle and scope boundaries verified")


if __name__ == "__main__":
    main()
