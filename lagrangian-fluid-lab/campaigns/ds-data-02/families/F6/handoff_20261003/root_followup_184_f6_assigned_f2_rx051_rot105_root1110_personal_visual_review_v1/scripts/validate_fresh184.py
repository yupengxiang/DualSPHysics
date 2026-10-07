#!/usr/bin/env python3
"""Read-only validator for F6 fresh184 personal visual evidence.

The validator reads only package JSON plus referenced JSON/XML/XMF metadata and
published PNG visualization products. It never opens scientific H5/BI4/CSV/DAT/VTK
payloads and never launches work.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

FORBIDDEN = (".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp", ".pvd", ".raw")
ALLOWED = (".json", ".xml", ".xmf", ".png")
CASE = "F2_STAGE1_FIRST48_EXPANSION_RX051_RY014_FILL080_ROT105_DP010_SPATIAL_REFERENCE_SAVE010"
PHYS = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX051_RY014_FILL080_ROT105"
CANONICAL = "d10afc2567aaa694ea35846bb5b7827c1ef57e8f47271ed238c269483697c784"
LEGACY = "55d9bbc45377483ed96c74ccb93c6bfd7d3ac83d6dba360f5047f66e9aefa438"

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def check_ref(item, *, kind=None):
    assert isinstance(item, dict) and {"path", "sha256", "bytes"} <= set(item), item
    p = Path(item["path"])
    assert p.is_file(), p
    low = str(p).lower()
    assert not any(low.endswith(s) for s in FORBIDDEN), p
    assert p.suffix.lower() in ALLOWED, p
    assert sha(p) == item["sha256"], (p, "sha drift")
    assert p.stat().st_size == item["bytes"], (p, "size drift")
    if kind is not None:
        assert item.get("kind") == kind, (p, item.get("kind"), kind)
    return p

def completed_receipt(item):
    p = check_ref(item, kind="metadata")
    d = json.loads(p.read_text())
    assert d.get("schema") == "ds02.execution-receipt.v1", (p, d.get("schema"))
    assert d.get("status") == "completed", (p, d.get("status"))
    assert d.get("returncode") == 0, (p, d.get("returncode"))
    return d

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=Path(__file__).parents[1])
    args = ap.parse_args()
    pkg = args.package
    d = json.loads((pkg / "metadata/personal-visual-decision.json").read_text())
    assert d["schema"] == "ds02.f6.fresh184.f2-personal-visual-review.v1"
    assert d["fresh_id"] == "fresh184" and d["family_id"] == "F6"
    assert d["assigned_family"] == "F6" and d["actual_family"] == "F2"
    assert d["model"] == "gpt-5.6-luna" and d["reasoning_effort"] == "max"
    assert d["recursive_delegation"] is False
    pred = d["predecessor"]
    p = check_ref(pred, kind="metadata")
    old = json.loads(p.read_text())
    assert old.get("fresh_id") == "fresh183" and pred["must_remain_unchanged"] is True
    c = d["case"]
    assert c["case_id"] == CASE and c["physical_case_id"] == PHYS
    assert c["canonical_native_physical_condition_sha256"] == CANONICAL
    assert c["typed_legacy_actual_converter_and_xmf_physical_scope_sha256"] == LEGACY
    assert c["scope_roles"]["equality_claimed"] is False
    assert c["source_plan_field_presence"] == {
        "native": {"source_plan_condition_sha256": {"present": False, "value": None},
                    "source_plan_physical_condition_sha256": {"present": True, "value": CANONICAL}},
        "xmf": {"source_plan_condition_sha256": {"present": False, "value": None},
                 "source_plan_physical_condition_sha256": {"present": False, "value": None}},
    }
    assert c["declared_counts"] == {"fixed":372840,"moving":24150,"floating":0,"fluid":21114,"total":418104}
    assert c["terminal_counts"] == {"fixed":372840,"moving":24150,"floating":0,"fluid":21111,"total":418101}
    assert c["dimension"] == 3 and c["expected_frames"] == 401
    dec = d["decision"]
    assert dec["status"] == "visual-approved-by-delegated-agent"
    assert dec["case_credit"] == 0 and dec["global_acceptance"] is False
    assert dec["precision_status"] == "not accepted"
    assert dec["q_n_granted"] is False and dec["q_e_granted"] is False
    assert "Root1308" in dec["main_process_qi"]
    ev = d["evidence"]
    # Every listed evidence item is a real metadata/visual file with an exact immutable digest.
    for k,item in ev.items():
        check_ref(item, kind="visualization" if item.get("kind")=="visualization" else "metadata")
    for key in ("gencase_receipt","initial_qa_receipt","native_receipt","typed_receipt","xmf_receipt","render_receipt"):
        completed_receipt(ev[key])
    qa = json.loads(Path(ev["initial_qa_report"]["path"]).read_text())
    assert qa.get("status") == "pass", qa.get("status")
    manifest = json.loads(Path(ev["xmf_manifest"]["path"]).read_text())
    assert manifest["case_id"] == CASE and manifest["physical_case_id"] == PHYS
    assert manifest["frames"] == manifest["expected_frames"] == 401
    assert manifest["particles"] == 418104
    assert manifest["physical_condition_sha256"] == LEGACY
    assert manifest["actual_converter_legacy_scope_sha256"] == LEGACY
    assert manifest["canonical_source_physical_condition_sha256"] == CANONICAL
    assert manifest["scope_equality_not_claimed"] is True
    assert manifest["producer_scope_schema"] == "legacy-owner-scope.v0"
    assert manifest["full_saved_states"] is True
    report = json.loads(Path(ev["render_report"]["path"]).read_text())
    assert report["schema"] == "ds02.stage1.paraview-full-animation-integrity.v1"
    assert report["frames"] == report["source_frames"] == 401
    assert report["all_frames_rendered"] is True and report["actual_times_preserved_exactly"] is True
    assert report["native_identity_axis_preserved"] is True
    assert report["nonfinite_active_states"] == 0
    assert report["numerical_precision_status"] == "not accepted"
    fs = report["frame_diagnostics"]
    assert len(fs) == 401 and fs[0]["frame"] == 0 and fs[-1]["frame"] == 400
    assert fs[0]["active"] == 418104 and fs[0]["fluid_points"] == 21114
    assert fs[-1]["active"] == 418101 and fs[-1]["fluid_points"] == 21111 and fs[-1]["missing"] == 3
    assert sum(1 for x in fs if x["missing"] > 0) == 236
    assert sum(x["missing"] for x in fs) == 652
    assert max(x["missing"] for x in fs) == 3
    assert next(x["frame"] for x in fs if x["missing"] > 0) == 165
    pub = json.loads(Path(ev["publish_receipt"]["path"]).read_text())
    assert pub["status"] == "published_after_atomic_rename"
    assert pub["source_h5_opened_or_hashed_by_wrapper"] is False
    life = d["lifecycle_and_limits"]
    assert life["frames"] == life["source_frames"] == 401
    assert life["initial_counts"] == c["declared_counts"] and life["terminal_counts"] == c["terminal_counts"]
    assert life["final_missing_fluid_particles"] == 3
    assert life["first_missing_frame"] == 165 and life["max_missing_per_frame"] == 3
    assert life["frames_with_any_missing_particle"] == 236 and life["cumulative_particle_frame_omissions"] == 652
    assert life["uid_closure_claimed"] is False and life["strict_containment_claimed"] is False
    vr = d["visual_review"]
    assert vr["personally_viewed_with"] == "view_image"
    assert vr["contact_sheet_count"] == 17 and len(vr["contact_sheets"]) == 17
    assert vr["key_frame_count"] == 9 and len(vr["key_frames"]) == 9
    for i,item in enumerate(vr["contact_sheets"]):
        check_ref(item, kind="visualization")
        assert item["sheet_index"] == i
        assert item["frame_start"] == i*24 and item["frame_end"] == min(i*24+23,400)
    expected_keys=[0,50,100,150,200,250,300,350,400]
    assert [x["frame"] for x in vr["key_frames"]] == expected_keys
    for item in vr["key_frames"]:
        check_ref(item, kind="visualization")
        assert item["path"].endswith(f"frame_{item['frame']:04d}.png")
    sb=d["source_boundaries"]
    assert sb["science_payload_read"] is False and sb["science_payload_hashed"] is False
    assert sb["science_jobs_started"] is False and sb["shared_registry_or_ledger_written"] is False
    assert d["future_work"]["no_new_render_or_solver_request"] is True
    print("fresh184 validation PASS: F2 RX051 ROT105; 17 contacts + 9 keys viewed; Root1110 completed/0 and published full401 verified; canonical/legacy scopes separate; omission limits 3/165/236/652 preserved; case credit 0")

if __name__ == "__main__":
    main()
