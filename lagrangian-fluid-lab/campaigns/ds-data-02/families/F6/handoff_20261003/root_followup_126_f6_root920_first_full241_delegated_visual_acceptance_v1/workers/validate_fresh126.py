#!/usr/bin/env python3
"""Validate fresh126 without reading scientific payloads."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
FORBIDDEN = (".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz")
CASE = "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025"
KEYS = [0, 24, 48, 72, 96, 120, 168, 192, 240]


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
    assert index["fresh_id"] == "fresh126"
    assert index["source_only"] and not index["global_credit_updated"]
    assert not index["scientific_payload_read_or_hashed_by_review"]
    assert [row["case_id"] for row in index["cases"]] == [CASE]
    assert selection["selected_case_ids"] == [CASE]
    assert selection["unreviewed_future_root920_requests"] == 2
    assert selection["source_only"] and not selection["global_credit_updated"]
    assert protocol["image_tool"] == "view_image"
    assert protocol["per_case_required_contact_sheets"] == 11
    assert protocol["per_case_required_key_frames"] == KEYS
    for obj in (index, selection, protocol):
        no_science_suffixes(obj)

    entry = index["cases"][0]
    assert entry["status"] == "visual-approved-by-delegated-agent"
    assert entry["decision"] == "approved"
    assert entry["frames"] == 241 and entry["contact_sheet_count"] == 11 and entry["key_frame_count"] == 9
    assert entry["no_global_credit_claim"] and not entry["root_personal_inspection_claim"]
    closure = load(entry["metadata_closure_path"])
    assert closure["schema"] == "ds02.f6.fresh126.case-visual-review-closure.v1"
    assert closure["case_id"] == CASE and closure["source_only"]
    assert closure["visual_decision"]["status"] == "visual-approved-by-delegated-agent"
    assert closure["visual_decision"]["reviewed_all_contact_sheets_and_key_frames"]
    assert closure["visual_decision"]["reviewed_contact_sheet_indices"] == list(range(11))
    assert closure["visual_decision"]["reviewed_key_frame_indices"] == KEYS
    assert not closure["review_constraints"]["scientific_payload_read_or_hashed_by_review"]
    assert not closure["review_constraints"]["global_case_credit_updated_by_review"]
    no_science_suffixes(closure)

    ctl = closure["root920_controller_evidence"]
    file_record(ctl["controller_launch"])
    file_record(ctl["actual_request"])
    file_record(ctl["retirement_proof"])
    assert ctl["same_pid_start_ticks_verified_before_actual_dispatch"]
    assert ctl["actual_render_status"] == "completed/0"
    receipt(ctl["actual_receipt"], "Root920 render")
    retirement = ctl["retirement_state"]
    assert retirement["same_metadata_handle_retired"]
    assert retirement["actual_full241_completed0_preserved"] == 1
    assert retirement["case_credit"] == 0
    assert retirement["unlaunched_future_requests_not_reviewed"] == 2

    producer = closure["producer_metadata"]
    assert producer["gencase"]["status"] == "completed/0"
    assert producer["gencase"]["actual_total_particles"] == 417505
    assert producer["gencase"]["fluid_particles"] == 327680
    assert producer["gencase"]["generated_xml_particle_counts"] == {"fixed": 73441, "floating": 16384, "fluid": 327680, "moving": 0}
    assert producer["gencase"]["dimension"] == 3 and producer["gencase"]["data2d"] is False
    receipt(producer["gencase"]["receipt"], "GenCase")
    for key in ("prepared_report", "generated_xml", "generated_definition_xml", "source_definition_xml"):
        file_record(producer["gencase"][key])

    qa = producer["initial_native_qa"]
    assert qa["status"] == "completed_pass" and qa["pass"] and qa["all_reported_checks_true"]
    assert qa["actual_total_particles"] == 417505
    assert qa["actual_counts"] == {"fixed": 73441, "floating": 16384, "fluid": 327680, "moving": 0, "total": 417505}
    assert qa["true_3d_data2d_false"]
    assert qa["center_m"] == [2.4, 1.2, 1.08]
    assert qa["physical_mass_kg"] == 128.0 and qa["native_support_mass_kg"] == 256.0
    assert qa["mass_rescaling"] is False and qa["physical_and_native_support_masses_must_not_be_equal"]
    assert qa["particle_v0_proves_no_angular_velocity"] is False
    receipt(qa["receipt"], "initial native QA")
    file_record(qa["report"])

    assert producer["full_native"]["saved_frame_count"] == 241
    receipt(producer["full_native"]["receipt"], "full native")
    typed = producer["typed_conversion"]
    assert typed["conversion_status"] == "completed"
    assert (typed["frames"], typed["particles"], typed["solver_dimension"]) == (241, 417505, 3)
    assert typed["partvtk_all_passed"] and typed["time_evidence"]["strictly_increasing"]
    receipt(typed["receipt"], "typed conversion")
    file_record(typed["report"])
    xmf = producer["xmf"]
    assert (xmf["expected_frames"], xmf["expected_particles"], xmf["expected_dimension"]) == (241, 417505, 3)
    assert xmf["vector_semantic_type"] == "N3"
    receipt(xmf["receipt"], "N3 XMF")
    file_record(xmf["manifest"])
    file_record(xmf["case_xmf"])
    file_record(xmf["root722_terminal_registry"])
    assert xmf["root722_status"] == "actual_completed0_N3_pass"

    full = closure["full_time_native_state_summary"]
    for k, expected in {"frames": 241, "source_frames": 241, "all_frames_rendered": True, "actual_times_preserved_exactly": True, "native_identity_axis_preserved": True, "nonfinite_active_states": 0, "frame_diagnostics_entry_count": 241}.items():
        assert full[k] == expected, (k, full[k])
    assert full["all_reported_positions_and_fields_finite"]
    assert full["fluid_active_count_range"] == [327677, 327680]
    assert full["floating_active_count_range"] == [16384, 16384]
    assert full["fixed_active_count_range"] == [73441, 73441]
    assert full["moving_active_count_range"] == [0, 0]
    assert full["unknown_active_count_range"] == [0, 0]
    assert full["frame0"]["active_particles"] == 417505 and full["frame0"]["missing_particles"] == 0
    assert full["final_frame"]["active_particles"] == 417502 and full["final_frame"]["missing_particles"] == 3
    assert set(full["two_views"]) == {"isometric", "transverse_side"}

    life = closure["lifecycle"]
    assert life["frame_diagnostics_entry_count"] == 241
    assert life["transient_missing_frame_count"] == 234
    assert life["maximum_missing_particles_per_frame"] == 3
    assert life["final_frame_missing_particles"] == 3
    assert life["missing_events_are_not_final_uid_count"]
    assert life["final_uid_status"] == "not independently observed; visual review does not infer final UID survival"

    scopes = closure["scope_separation"]
    assert scopes["must_not_equate_scopes"]
    assert scopes["actual_converter_physical_condition_sha256"] == scopes["classified_converter_physical_condition_sha256"] == scopes["xmf_manifest_declared_physical_condition_sha256"]
    assert scopes["actual_converter_physical_condition_sha256"] != scopes["source_owner_declared_physical_condition_sha256"]
    assert scopes["actual_converter_physical_condition_sha256"] != scopes["source_plan_condition_sha256"]
    for k in ("source_owner_file", "classified_converter_owner_file", "typed_binding_file", "render_binding_file", "root722_terminal_registration_file", "root917_dynamic_audit_file"):
        file_record(scopes[k])

    png = load(entry["png_hash_manifest_path"])
    assert png["schema"] == "ds02.f6.fresh126.png-review-evidence.v1"
    assert png["computed_after_view_image"] and png["viewed_with"] == "view_image"
    assert len(png["contact_sheets"]) == 11 and len(png["key_frames"]) == 9
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
    no_science_suffixes(png)
    no_science_suffixes(closure["source_files"])
    print("fresh126 validation PASS: one Root920 F6 full241 render, 11 contact sheets + 9 key frames, metadata/lifecycle/scope boundaries verified")


if __name__ == "__main__":
    main()
