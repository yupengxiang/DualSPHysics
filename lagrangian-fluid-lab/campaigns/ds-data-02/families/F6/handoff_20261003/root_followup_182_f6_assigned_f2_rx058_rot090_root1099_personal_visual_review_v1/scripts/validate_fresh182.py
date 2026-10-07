#!/usr/bin/env python3
"""Read-only validator for F6 fresh182 F2 RX058/ROT090 visual evidence."""
import argparse
import hashlib
import json
from pathlib import Path

FORBIDDEN = (".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk")
META = (".json", ".xml", ".xmf")

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def ref(item, kind):
    assert {"path", "sha256", "bytes", "role", "kind"} <= set(item)
    path = Path(item["path"])
    assert path.is_file(), path
    assert not any(str(path).lower().endswith(s) for s in FORBIDDEN), path
    assert item["kind"] == kind
    assert path.suffix.lower() in (META if kind == "metadata" else (".png",)), path
    assert sha(path) == item["sha256"], (path, "sha drift")
    assert path.stat().st_size == item["bytes"], (path, "size drift")
    return path

def completed(item):
    data = json.loads(ref(item, "metadata").read_text())
    assert data.get("schema") == "ds02.execution-receipt.v1"
    assert data.get("status") == "completed" and data.get("returncode") == 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=Path(__file__).parents[1])
    pkg = ap.parse_args().package
    d = json.loads((pkg / "metadata/personal-visual-decision.json").read_text())
    assert d["schema"] == "ds02.f6.fresh182.f2-personal-visual-review.v1"
    assert d["fresh_id"] == "fresh182" and d["family_id"] == d["assigned_family"] == "F6"
    assert d["actual_family"] == "F2"
    assert d["model"] == "gpt-5.6-luna" and d["reasoning_effort"] == "max"
    assert d["recursive_delegation"] is False
    pred = d["predecessor"]
    old = json.loads(ref({**pred, "kind": "metadata"}, "metadata").read_text())
    assert old["schema"] == "ds02.f6.fresh181.f5-personal-visual-review.v1"
    c = d["case"]
    assert c["case_id"] == "F2_STAGE1_FIRST48_EXPANSION_RX058_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"
    assert c["physical_case_id"] == "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX058_RY014_FILL080_ROT090"
    assert c["canonical_native_physical_condition_sha256"] == "45f3a1d822119ae0e524f616dedd22c822688419a9a0ee1166183415903e2907"
    assert c["typed_legacy_actual_converter_and_xmf_physical_scope_sha256"] == "feda775ce33fdc4a2f10ed5b5717d35d7104d2fee0c384f6343f6142f33f8eb8"
    assert c["scope_roles"]["native_plan_equals_xmf_plan"] is False
    assert c["declared_counts"] == {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21114, "total": 418104}
    assert c["terminal_render_counts"] == {"fixed": 372840, "moving": 24150, "floating": 0, "fluid": 21109, "total": 418099}
    assert c["dimension"] == 3 and c["expected_frames"] == 401
    assert c["source_plan_field_presence"]["native"]["source_plan_condition_sha256"] == {"present": False, "value": None}
    assert c["source_plan_field_presence"]["xmf"]["source_plan_physical_condition_sha256"] == {"present": False, "value": None}
    dec = d["decision"]
    assert dec["status"] == "visual-approved-by-delegated-agent" and dec["case_credit"] == 0
    assert dec["global_acceptance"] is False and dec["precision_status"] == "not accepted"
    assert dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["production_approval"] is False
    ev = d["evidence"]
    for item in ev.values():
        ref(item, "metadata")
    for key in ("gencase_receipt", "initial_qa_receipt", "native_receipt", "typed_receipt", "xmf_receipt", "render_receipt"):
        completed(ev[key])
    qa = json.loads(Path(ev["initial_qa_report"]["path"]).read_text())
    assert qa["status"] == "pass" and all(qa["checks"].values())
    man = json.loads(Path(ev["xmf_manifest"]["path"]).read_text())
    assert man["schema"] == "ds02.stage1.paraview-temporal-product.v1"
    assert man["expected_frames"] == man["frames"] == 401 and man["particles"] == 418104
    assert man["physical_condition_sha256"] == c["typed_legacy_actual_converter_and_xmf_physical_scope_sha256"]
    assert man["canonical_source_physical_condition_sha256"] == c["canonical_native_physical_condition_sha256"]
    assert man["actual_converter_legacy_scope_sha256"] == c["typed_legacy_actual_converter_and_xmf_physical_scope_sha256"]
    assert man["scope_equality_not_claimed"] is True
    assert man["fields"]["position"]["shape"] == [401, 418104, 3]
    assert man["fields"]["velocity"]["shape"] == [401, 418104, 3]
    report = json.loads(Path(ev["render_report"]["path"]).read_text())
    assert report["schema"] == "ds02.stage1.paraview-full-animation-integrity.v1"
    assert report["frames"] == report["source_frames"] == 401
    assert report["all_frames_rendered"] and report["actual_times_preserved_exactly"]
    assert report["native_identity_axis_preserved"] and report["nonfinite_active_states"] == 0
    assert report["numerical_precision_status"] == "not accepted"
    assert len(report["outputs"]["contact_sheets"]) == 17 and len(report["frame_diagnostics"]) == 401
    assert report["frame_diagnostics"][-1]["active"] == 418099
    assert report["frame_diagnostics"][-1]["fluid_points"] == 21109
    assert report["frame_diagnostics"][-1]["missing"] == 5
    pub = json.loads(Path(ev["publish_receipt"]["path"]).read_text())
    assert pub["status"] == "published_after_atomic_rename" and pub["source_h5_opened_or_hashed_by_wrapper"] is False
    ctrl = json.loads(Path(ev["controller_result"]["path"]).read_text())
    assert ctrl["status"] == "completed" and ctrl["returncode"] == 0
    visual = d["visual_review"]
    assert visual["personally_viewed_with"] == "view_image"
    assert visual["contact_sheet_count"] == len(visual["contact_sheets"]) == 17
    assert visual["key_frame_count"] == len(visual["key_frames"]) == 9
    assert visual["key_frame_indices"] == [0, 50, 100, 150, 200, 250, 300, 350, 400]
    for i, item in enumerate(visual["contact_sheets"]):
        assert ref(item, "visualization").name == "all_frames_%03d.png" % i
    for item in visual["key_frames"]:
        assert ref(item, "visualization").name == "frame_%04d.png" % item["frame"]
    life = d["lifecycle"]
    assert life["final_missing_particles"] == 5 and life["first_missing_frame"] == 159
    assert life["frames_with_any_missing_particle"] == 242 and life["cumulative_particle_frame_omissions"] == 898
    assert life["unknown_missing_locations_states_and_causes"] is True
    assert life["all_fluid_UIDs_active_or_closed_container_claimed"] is False
    assert d["source_boundaries"]["science_payload_read"] is False
    assert d["source_boundaries"]["science_payload_hashed"] is False
    assert d["source_boundaries"]["science_jobs_started"] is False
    assert d["source_boundaries"]["shared_registry_or_ledger_written"] is False
    print("fresh182 validation PASS: assigned F6 / actual F2 Root1099 completed/0 and published; 17 contacts + 9 keys viewed; scope and omission limits preserved; no case credit")

if __name__ == "__main__":
    main()
