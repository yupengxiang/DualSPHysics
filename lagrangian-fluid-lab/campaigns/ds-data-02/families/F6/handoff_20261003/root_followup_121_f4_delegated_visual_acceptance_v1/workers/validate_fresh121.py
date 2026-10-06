#!/usr/bin/env python3
"""Validate F6 fresh121 delegated F4 visual-review evidence without scientific payload access."""
from pathlib import Path
import hashlib, json

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "metadata"
FORBIDDEN = (".h5", ".bi4", ".csv", ".vtk", ".dat")
CASES = {
    "F4_DROP_gap0p20000_xoff0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p20000_xoff0p08000_yoffm0p04000_uz0p40000",
}
KEYS = (0, 150, 300, 450, 600, 750, 900, 1050, 1200)

def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def digest(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""): h.update(b)
    return h.hexdigest()
def walk_strings(x):
    if isinstance(x, dict):
        for v in x.values(): yield from walk_strings(v)
    elif isinstance(x, list):
        for v in x: yield from walk_strings(v)
    elif isinstance(x, str): yield x

def assert_no_forbidden(x):
    for s in walk_strings(x):
        assert not s.lower().endswith(FORBIDDEN), s

def assert_file_record(r):
    p = Path(r["path"]); assert p.is_file(), p
    assert digest(p) == r["sha256"], p

index = load(META / "review-index.json")
snapshot = load(META / "accepted-source-snapshot.json")
protocol = load(META / "visual-review-protocol.json")
assert index["schema"] == "ds02.f6.delegated-visual-review.v1"
assert index["fresh_id"] == "fresh121" and index["source_only"] is True
assert snapshot["schema"] == "ds02.f6.fresh121.selection-snapshot.v1"
assert snapshot["selected_case_count"] == 2
assert snapshot["global_credit_updated"] is False
assert snapshot["third_root715_case_excluded"]["selection_status"] == "excluded_before_visual_review"
assert protocol["reviewed_cases"] == sorted(CASES)
assert len(index["cases"]) == 2
assert {x["case_id"] for x in index["cases"]} == CASES
for entry in index["cases"]:
    assert entry["status"] == "visual-approved-by-delegated-agent"
    assert entry["decision"] == "approved"
    assert entry["frames"] == 1201 and entry["contact_sheet_count"] == 51 and entry["key_frame_count"] == 9
    assert entry["no_global_credit_claim"] is True
    closure = load(entry["metadata_closure_path"])
    assert closure["case_id"] == entry["case_id"]
    assert closure["visual_decision"]["status"] == "visual-approved-by-delegated-agent"
    assert closure["visual_decision"]["root_personal_inspection_claim"] is False
    assert closure["visual_decision"]["reviewed_all_contact_sheets_and_key_frames"] is True
    assert closure["selected_root715_terminal_evidence"]["root715_execution_receipt"]["status"] == "completed"
    assert closure["selected_root715_terminal_evidence"]["root715_execution_receipt"]["returncode"] == 0
    rr = closure["selected_root715_terminal_evidence"]["render_report"]
    assert rr["frames"] == 1201 and rr["source_frames"] == 1201 and rr["all_frames_rendered"] is True
    assert rr["actual_times_preserved_exactly"] is True and rr["native_identity_axis_preserved"] is True
    assert rr["nonfinite_active_states"] == 0
    assert closure["producer_metadata"]["gencase"]["counts"] == {
        "total_particles": 83233, "fixed": 24161, "moving": 0, "floating": 0, "fluid": 59072,
        "solver_dimension": 3, "dp_m": "0.01"
    }
    qa = closure["producer_metadata"]["native_initial_frame0_qa"]
    assert qa["pass"] is True and qa["total_particles"] == 83233 and qa["fluid_particles"] == 59072
    assert qa["native_3d_levels"] == [121, 41, 61] and qa["unique_coordinate_count"] == 83233 and qa["unique_identity_count"] == 83233
    assert qa["mass_rescaling"] is False and qa["native_raw_mk_type_observed"] is True
    conv = closure["producer_metadata"]["conversion_report"]
    assert conv["conversion_status"] == "completed" and conv["frames"] == 1201 and conv["particles"] == 83233
    assert conv["solver_dimension"] == 3 and conv["partvtk_all_passed"] is True
    manifest = closure["producer_metadata"]["xmf_manifest"]
    assert manifest["expected_frames"] == 1201 and manifest["expected_particles"] == 83233 and manifest["expected_dimension"] == 3
    assert manifest["vector_semantic_type"] == "N3" and manifest["arrays_read_by_source"] is False
    assert closure["scope_separation"]["must_not_equate_scopes"] is True
    assert len({closure["scope_separation"][k] for k in (
        "actual_converter_physical_condition_sha256", "root715_source_binding_physical_condition_sha256",
        "source_owner_declared_physical_condition_sha256", "source_plan_condition_sha256")}) == 4
    lc = closure["lifecycle"]
    assert lc["transient_missing_frame_count"] >= 0
    assert lc["maximum_missing_particles_per_frame"] >= 0
    assert lc["missing_events_are_not_final_uid_count"] is True
    png = load(closure["png_assets"]["hash_manifest_path"])
    assert png["schema"] == "ds02.f6.fresh121.png-review-evidence.v1"
    assert png["computed_after_view_image"] is True and png["viewed_with"] == "view_image"
    assert len(png["contact_sheets"]) == 51 and len(png["key_frames"]) == 9
    for i, item in enumerate(png["contact_sheets"]):
        p = Path(item["path"]); assert p.name == f"all_frames_{i:03d}.png" and p.is_file()
        assert item["bytes"] == p.stat().st_size and item["sha256"] == digest(p)
    for frame, item in zip(KEYS, png["key_frames"]):
        p = Path(item["path"]); assert item["frame"] == frame and p.name == f"frame_{frame:04d}.png" and p.is_file()
        assert item["bytes"] == p.stat().st_size and item["sha256"] == digest(p)
    for r in closure["producer_metadata"]["source_files"]:
        assert_file_record(r)
    assert_no_forbidden(closure); assert_no_forbidden(png)
print("fresh121 validation PASS: two Root715 completed/0 F4 cases, 1201-frame reports, 51 contact sheets + 9 key frames each, scope/lifecycle boundaries verified")
