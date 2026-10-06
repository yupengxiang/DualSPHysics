#!/usr/bin/env python3
"""Read-only validator for F6 fresh170 personal visual evidence.

Only JSON/XML/PNG metadata and visualization artifacts are read. This validator
never opens scientific H5/BI4/CSV/DAT/VTK payloads and never launches work.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

FORBIDDEN = (".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk")
ALLOWED = (".json", ".xml", ".xmf", ".png")

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def check_ref(item, *, kind=None):
    assert isinstance(item, dict) and "path" in item and "sha256" in item, item
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
    assert d["schema"] == "ds02.f6.fresh170.f2-personal-visual-review.v1"
    assert d["fresh_id"] == "fresh170" and d["family_id"] == "F6"
    assert d["model"] == "gpt-5.6-luna" and d["reasoning_effort"] == "max"
    assert d["recursive_delegation"] is False
    pred = d["predecessor"]
    p = check_ref({"path": pred["path"], "sha256": pred["sha256"], "bytes": Path(pred["path"]).stat().st_size, "kind": "metadata"}, kind="metadata")
    old = json.loads(p.read_text())
    assert old.get("fresh_id") == "fresh169" and pred["must_remain_unchanged"] is True
    c = d["case"]
    assert c["case_id"].endswith("ROT090_DP010_SPATIAL_REFERENCE_SAVE010")
    assert c["physical_case_id"].endswith("ROT090")
    assert c["canonical_source_physical_condition_sha256"] == "df5b332e00c37353cd80686d8aa91d7ecd1456deea8447f46ada28dfceb81eab"
    assert c["typed_legacy_and_actual_converter_scope_sha256"] == "bda6cb1faa3099d9fb2e9232af75754c35584acfadfac367478121418aae2b8e"
    assert c["scope_roles"]["equality_claimed"] is False
    assert c["rotation_control"]["physical_control_claim_from_images"] is False
    dec = d["decision"]
    assert dec["status"] == "visual-approved-by-delegated-agent"
    assert dec["case_credit"] == 0 and dec["global_acceptance"] is False
    assert dec["main_process_qi"] == "separate; not claimed by this package"
    assert dec["precision_status"] == "not accepted"
    ev = d["evidence"]
    for k, item in ev.items():
        check_ref(item, kind="metadata")
    chain = d["producer_chain"]
    for stage in ("gencase", "initial_native_qa", "native", "typed", "xmf", "render"):
        assert stage in chain, stage
    for key in ("gencase_receipt", "initial_qa_receipt", "native_receipt", "typed_receipt", "xmf_receipt", "render_receipt"):
        completed_receipt(ev[key])
    qa = json.loads(Path(ev["initial_qa_report"]["path"]).read_text())
    assert qa.get("status") == "pass"
    # This is producer QA evidence only; main-process QI remains explicitly separate.
    assert d["decision"]["main_process_qi"] == "separate; not claimed by this package"
    manifest = json.loads(Path(ev["xmf_manifest"]["path"]).read_text())
    assert manifest["frames"] == manifest["expected_frames"] == 401
    assert manifest["physical_condition_sha256"] == c["typed_legacy_and_actual_converter_scope_sha256"]
    assert manifest["canonical_source_physical_condition_sha256"] == c["canonical_source_physical_condition_sha256"]
    assert manifest["scope_equality_not_claimed"] is True
    assert manifest["producer_scope_schema"] == "legacy-owner-scope.v0"
    report = json.loads(Path(ev["render_report"]["path"]).read_text())
    assert report["frames"] == report["source_frames"] == 401
    assert report["all_frames_rendered"] is True and report["actual_times_preserved_exactly"] is True
    assert report["nonfinite_active_states"] == 0
    assert report["numerical_precision_status"] == "not accepted"
    pub = json.loads(Path(ev["publish_receipt"]["path"]).read_text())
    assert pub["status"] == "published_after_atomic_rename"
    assert pub["source_h5_opened_or_hashed_by_wrapper"] is False
    life = d["lifecycle_and_render_metadata"]
    assert life["frames"] == life["source_frames"] == 401
    assert life["final_missing_particles"] == 1
    assert life["final_missing_fluid_uid"] == "403829"
    assert life["missing_cause_or_location"].startswith("unknown")
    vr = d["visual_review"]
    assert vr["personally_viewed_with"] == "view_image"
    assert vr["contact_sheet_count"] == 17 and len(vr["contact_sheets"]) == 17
    assert vr["key_frame_count"] == 9 and len(vr["key_frames"]) == 9
    for i, item in enumerate(vr["contact_sheets"]):
        check_ref(item, kind="visualization")
        assert item["sheet_index"] == i
    for item in vr["key_frames"]:
        check_ref(item, kind="visualization")
        assert item["path"].endswith(f"frame_{item['frame']:04d}.png")
    sb = d["source_boundaries"]
    assert sb["science_payload_read"] is False and sb["science_payload_hashed"] is False
    assert sb["science_jobs_started"] is False and sb["shared_registry_or_ledger_written"] is False
    assert d["future_work"]["no_new_render_or_solver_request"] is True
    print("fresh170 validation PASS: F2 RX051 ROT090; 17 contacts + 9 keys viewed; completed/0 chain and published full401 verified; canonical/legacy scopes separate; case credit 0")

if __name__ == "__main__":
    main()
