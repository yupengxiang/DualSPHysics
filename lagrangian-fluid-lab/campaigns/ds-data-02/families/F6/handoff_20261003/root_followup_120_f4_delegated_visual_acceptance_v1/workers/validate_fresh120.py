#!/usr/bin/env python3
"""Validate fresh120 visual-review metadata and PNG evidence only."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
INDEX = META / "review-index.json"
SNAPSHOT = META / "accepted-source-snapshot.json"
FORBIDDEN_SUFFIXES = (".h5", ".bi4", ".csv", ".vtk", ".dat")
KEYS = (0, 150, 300, 400, 600, 750, 900, 1050, 1200)
COUNTS = {"total_particles": 83233, "fluid_particles": 59072, "fixed_particles": 24161, "moving_particles": 0, "floating_particles": 0, "solver_dimension": 3, "dp_m": 0.01}
EXPECTED = {"F4_DROP_gap0p24000_xoffm0p08000_yoffm0p04000_uz0p60000"}

def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def sha256(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def path_values(x, key=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from path_values(v, k)
    elif isinstance(x, list):
        for v in x:
            yield from path_values(v, key)
    elif isinstance(x, str) and (key == "path" or key.endswith("_path") or key.endswith("_paths")):
        yield x

def assert_receipt(summary, label, completed=True):
    assert Path(summary["path"]).is_file(), (label, summary)
    if completed:
        assert summary["status"] == "completed" and summary["returncode"] == 0, (label, summary)

index = load(INDEX)
snapshot = load(SNAPSHOT)
assert index["schema"] == "ds02.f6.delegated-visual-review.v1"
assert index["fresh_id"] == "fresh120"
assert index["source_only"] is True
assert len(index["cases"]) == 1
assert {x["case_id"] for x in index["cases"]} == EXPECTED
assert snapshot["schema"] == "ds02.f6.fresh120.selection-snapshot.v1"
assert snapshot["root638_inventory"]["selected_case_count"] == 1
assert snapshot["selected_cases_are_preferred_pair"] is False
assert snapshot["selected_cases_are_next_actual_root638_pair"] is True
assert snapshot["selected_cases_are_actual_root764_recovery_audited"] is True
assert snapshot["preferred_pair"]["availability"] == "already_excluded_by_checkpoint_106"
assert snapshot["preferred_pair"]["checkpoint_106_contains_case_ids"] == [
    "F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p60000",
]
assert snapshot["fallback_pair"]["case_ids"] == list(EXPECTED)
assert snapshot["duplicate_exclusion"]["global_credit_updated"] is False

for entry in index["cases"]:
    assert entry["status"] == "visual-approved-by-delegated-agent"
    assert entry["decision"] == "approved"
    assert entry["contact_sheet_count"] == 51
    assert entry["key_frame_count"] == 9
    assert entry["frames"] == 1201
    assert entry["no_global_credit_claim"] is True
    closure = load(entry["metadata_closure_path"])
    assert closure["schema"] == "ds02.f6.fresh120.case-visual-review-closure.v1"
    assert closure["case_id"] == entry["case_id"]
    assert closure["source_only"] is True
    assert closure["visual_decision"]["status"] == "visual-approved-by-delegated-agent"
    assert closure["visual_decision"]["root_personal_inspection_claim"] is False
    assert closure["selection"]["case_not_in_cp106_or_prior_visual_review_batches"] is True
    assert closure["render_terminal_evidence"]["original_root638_receipt_status"] == "running"
    assert closure["render_terminal_evidence"]["original_root638_returncode"] is None
    assert closure["render_terminal_evidence"]["original_root638_terminal_state"] == "unknown_preserved"
    assert closure["render_terminal_evidence"]["original_root638_receipt_was_not_treated_as_completed"] is True
    recovery_summary = closure["render_terminal_evidence"]["recovery_audit_receipt"]
    assert_receipt(recovery_summary, "recovery_audit")
    assert recovery_summary["status"] == "completed" and recovery_summary["returncode"] == 0
    producer = closure["producer_metadata"]
    for key in ("gencase_receipt_path", "prepared_input_report_path", "generated_xml_path", "generated_definition_xml_path",
                "basic_qa_receipt_path", "basic_qa_report_path", "frame0_qa_receipt_path", "initial_native_qa_report_path",
                "native_receipt_path", "typed_receipt_path", "conversion_report_path", "xmf_receipt_path", "xmf_manifest_path",
                "root638_render_receipt_path", "root638_render_report_path", "root638_reconciliation_path",
                "recovery_audit_receipt_path", "recovery_audit_report_path", "root638_request_path"):
        assert Path(producer[key]).is_file(), (entry["case_id"], key, producer[key])
    for key in ("gencase_receipt", "basic_qa_receipt", "frame0_qa_receipt", "native_receipt", "typed_receipt", "xmf_receipt", "recovery_audit_receipt"):
        assert_receipt(producer[key], key)
    old = load(producer["root638_render_receipt_path"])
    assert old["status"] == "running" and old.get("returncode") is None
    recovery = load(producer["recovery_audit_report_path"])
    assert recovery["audit_completed"] is True
    assert recovery["scientific_payload_read_or_hashed"] is False
    assert recovery["contact_sheet_file_count"] == 51 and recovery["frame_file_count"] == 1201
    prepared = load(producer["prepared_input_report_path"])
    assert producer["gencase_counts"] == COUNTS
    assert prepared["actual_total_particles"] == COUNTS["total_particles"]
    assert prepared["generated_xml_particle_counts"] == {"fixed": 24161, "moving": 0, "floating": 0, "fluid": 59072}
    f0 = load(producer["initial_native_qa_report_path"])
    c = f0["cases"][0]
    assert c["pass"] is True and c["actual_total_particles"] == 83233 and c["fluid_rows"] == 59072
    assert c["native_raw_mk_type_observed"] is True and c["native_raw_velocity_observed"] is True and c["mass_rescaling"] is False
    basic = load(producer["basic_qa_report_path"])
    assert basic["arrays_read_by_source"] is False and basic["audit"]["pass"] is True and basic["audit"]["inside_tank"] is True
    conversion = load(producer["conversion_report_path"])
    assert conversion["conversion_status"] == "completed" and conversion["frames"] == 1201 and conversion["particles"] == 83233
    assert conversion["solver_dimension"]["solver_dimension"] == 3 and conversion["partvtk_validation"]["all_passed"] is True
    manifest = load(producer["xmf_manifest_path"])
    assert manifest["expected_frames"] == 1201 and manifest["expected_particles"] == 83233 and manifest["expected_dimension"] == 3
    assert manifest["fluid_particles_expected"] == 59072 and manifest["arrays_read_by_source"] is False and manifest["jobs_started_by_source"] is False
    assert manifest["production_approval"] == "none" and manifest["q_n_status"] == "not_assessed" and manifest["precision_status"] == "not_accepted"
    render = load(producer["root638_render_report_path"])
    assert render["frames"] == 1201 and render["source_frames"] == 1201 and render["all_frames_rendered"] is True
    assert render["actual_times_preserved_exactly"] is True and render["native_identity_axis_preserved"] is True and render["nonfinite_active_states"] == 0
    lc = closure["lifecycle"]
    actual_lc = conversion["lifecycle"]
    assert lc["producer_transient_missing_frame_count"] == actual_lc["transient_missing_frame_count"]
    assert lc["producer_first_missing_frame_by_type"] == actual_lc["first_missing_frame_by_type"]
    assert lc["producer_first_missing_frame_by_mk"] == actual_lc["first_missing_frame_by_mk"]
    assert lc["producer_transient_missing_by_type_frame_events"] == actual_lc["transient_missing_by_type_frame_events"]
    assert lc["producer_transient_missing_by_mk_frame_events"] == actual_lc["transient_missing_by_mk_frame_events"]
    assert lc["maximum_missing_particles_per_frame"] is None
    png = load(closure["png_assets"]["hash_manifest_path"])
    assert png["schema"] == "ds02.f6.fresh120.png-review-evidence.v1"
    assert png["computed_after_view_image"] is True and png["viewed_with"] == "view_image"
    assert len(png["contact_sheets"]) == 51 and len(png["key_frames"]) == 9
    for i, item in enumerate(png["contact_sheets"]):
        p = Path(item["path"])
        assert p.name == f"all_frames_{i:03d}.png" and p.is_file() and item["bytes"] == p.stat().st_size and item["sha256"] == sha256(p)
    for frame, item in zip(KEYS, png["key_frames"]):
        p = Path(item["path"])
        assert item["frame"] == frame and p.name == f"frame_{frame:04d}.png" and p.is_file() and item["bytes"] == p.stat().st_size and item["sha256"] == sha256(p)
    scopes = closure["scope_separation"]
    ao = load(scopes["actual_owner_file_path"])
    so = load(scopes["source_owner_path"])
    assert scopes["must_not_equate_scopes"] is True
    assert scopes["actual_converter_physical_condition_sha256"] == manifest["physical_condition_sha256"]
    assert scopes["actual_converter_physical_condition_sha256"] != scopes["actual_owner_file_declared_physical_condition_sha256"]
    assert scopes["actual_owner_file_declared_physical_condition_sha256"] == scopes["source_owner_declared_physical_condition_sha256"]
    assert scopes["source_plan_condition_sha256"] == manifest["source_plan_condition_sha256"]
    assert ao["physical_condition_sha256"] == scopes["actual_owner_file_declared_physical_condition_sha256"]
    assert so["physical_condition_sha256"] == scopes["source_owner_declared_physical_condition_sha256"]
    assert sha256(Path(producer["generated_xml_path"])) == producer["generated_xml_sha256_attested_by_gencase"]
    assert sha256(Path(producer["generated_definition_xml_path"])) == producer["generated_definition_xml_sha256"]
    for value in path_values(closure):
        assert not value.lower().endswith(FORBIDDEN_SUFFIXES), value
    for value in path_values(png):
        assert not value.lower().endswith(FORBIDDEN_SUFFIXES), value

print("fresh120 validation PASS: one remaining unaccepted Root638 F4 case, 51 contact sheets, 9 key PNGs, recovery receipt/status boundary, metadata and scope separation verified")

