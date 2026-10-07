#!/usr/bin/env python3
"""Read-only validator for F6 fresh188 F5 M105/T080 visual evidence.

The validator reads only JSON/XML/XMF metadata and published PNG visualizations.
It never opens or hashes H5/BI4/CSV/DAT/VTK scientific payloads and never starts work.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ALLOWED={".json", ".xml", ".xmf", ".png"}
FORBIDDEN=(".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk", ".vtu", ".vtp", ".pvd", ".raw")
CASE="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYS="F5_COMPACT_RUNUP_RECOVERY_C082S1_M105_T080"
CANON="8f8c96ac8ec4b36ffe893782830637e45c728e8c509211b6299f3986b83feb73"
LEGACY="f2dae060729b71f946794672e50d07eda4ef2654eeaf2c3a6eb005d51991e5c2"
SOURCEDEF="abb19af7f0897ecc09d96d99b1a13b741bcbe2ae9a44f666c6f35b4555cc95f9"
COUNTS={"fixed":158559,"moving":4210,"floating":0,"fluid":31658,"total":194427}

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def check_ref(item, kind=None):
    assert isinstance(item,dict) and {"path","sha256","bytes","kind"} <= set(item), item
    p=Path(item["path"]); assert p.is_file(), p
    low=str(p).lower(); assert not any(low.endswith(s) for s in FORBIDDEN), p
    assert p.suffix.lower() in ALLOWED, p
    assert sha(p)==item["sha256"], (p,"sha drift")
    assert p.stat().st_size==item["bytes"], (p,"size drift")
    if kind is not None: assert item["kind"]==kind, (p,item["kind"],kind)
    return p

def completed_receipt(item):
    p=check_ref(item,"metadata"); d=json.loads(p.read_text())
    assert d.get("status")=="completed", (p,d.get("status"))
    assert d.get("returncode")==0, (p,d.get("returncode"))
    return d

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,default=Path(__file__).parents[1]); a=ap.parse_args(); pkg=a.package
    d=json.loads((pkg/"metadata/personal-visual-decision.json").read_text())
    assert d["schema"]=="ds02.f6.fresh188.f5-personal-visual-review.v1"
    assert d["fresh_id"]=="fresh188" and d["family_id"]=="F6" and d["assigned_family"]=="F6" and d["actual_family"]=="F5"
    assert d["model"]=="gpt-5.6-luna" and d["reasoning_effort"]=="max" and d["recursive_delegation"] is False
    pred=d["predecessor"]; pp=check_ref(pred,"metadata"); old=json.loads(pp.read_text()); assert old.get("fresh_id",old.get("package"))=="fresh186" and pred["must_remain_unchanged"] is True
    c=d["case"]; assert c["case_id"]==CASE and c["physical_case_id"]==PHYS
    assert c["canonical_native_physical_condition_sha256"]==CANON and c["actual_converter_legacy_scope_sha256"]==LEGACY and c["bed_xmf_source_definition_scope_sha256"]==SOURCEDEF
    assert c["scope_roles"]["equality_claimed"] is False and c["scope_roles"]["native_plan_equals_xmf_plan"] is False
    assert c["source_plan_field_presence"]["native"]["source_plan_condition_sha256"]=={"present":False,"value":None}
    assert c["source_plan_field_presence"]["native"]["source_plan_physical_condition_sha256"]=={"present":False,"value":None}
    assert c["source_plan_field_presence"]["xmf_bed_source_definition"]["source_plan_physical_condition_sha256"]=={"present":True,"value":SOURCEDEF,"role":"registered bed/SourceDef namespace"}
    assert c["declared_counts"]==COUNTS and c["terminal_counts"]==COUNTS and c["dimension"]==3 and c["expected_frames"]==801
    dec=d["decision"]; assert dec["status"]=="visual-approved-by-delegated-agent" and dec["case_credit"]==0 and dec["global_acceptance"] is False
    assert dec["precision_status"]=="not accepted" and dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["production_approval"] is False
    assert "Root1331" in dec["main_process_qi"]
    ev=d["evidence"]
    for item in ev.values(): check_ref(item)
    for key in ("gencase_receipt","initial_qa_receipt","native_receipt","typed_receipt","xmf_receipt","bed_receipt","render_receipt"):
        completed_receipt(ev[key])
    prep=json.loads(Path(ev["prepared_input_report"]["path"]).read_text()); assert prep.get("case_id")==CASE
    manifest=json.loads(Path(ev["xmf_manifest"]["path"]).read_text())
    assert manifest["case_id"]==CASE and manifest["physical_case_id"]==PHYS and manifest["frames"]==manifest["expected_frames"]==801 and manifest["particles"]==194427
    assert manifest["physical_condition_sha256"]==CANON
    report=json.loads(Path(ev["render_report"]["path"]).read_text())
    assert report["schema"]=="ds02.stage1.paraview-full-animation-integrity.v1" and report["frames"]==report["source_frames"]==801
    assert report["all_frames_rendered"] is True and report["actual_times_preserved_exactly"] is True and report["native_identity_axis_preserved"] is True and report["nonfinite_active_states"]==0
    fs=report["frame_diagnostics"]; assert len(fs)==801 and fs[0]["frame"]==0 and fs[-1]["frame"]==800
    expected={"fixed":158559,"moving":4210,"floating":0,"fluid":31658,"unknown":0}
    for x in fs:
        assert x["active"]==194427 and x["missing"]==0 and x["finite_positions_active"] is True and x["identity_axis_preserved"] is True
        assert x["type_counts_active"]==expected and x["floating_points"]==0 and x["fluid_points"]==31658 and x["moving_points"]==4210
        assert all(v.get("finite_active") is True and v.get("nonfinite_active")==0 for v in x["finite_fields"].values())
    pub=json.loads(Path(ev["render_publish_receipt"]["path"]).read_text()); assert pub["status"]=="published_after_atomic_rename" and pub["source_h5_opened_or_hashed_by_wrapper"] is False
    qi=json.loads(Path(ev["main_qi_proof"]["path"]).read_text()); assert qi["case_id"]==CASE and qi["physical_case_id"]==PHYS and qi["full_frames"]==801 and qi["particles"]==194427
    assert qi["actual_native_source_plan_condition_field_present"] is False and qi["actual_native_source_plan_condition_sha256"] is None
    assert qi["XMF_source_plan_condition_field_sha256"]==SOURCEDEF and qi["XMF_source_plan_condition_field_has_SourceDef_role"] is True
    assert qi["q_n_granted"] is False and qi["q_e_granted"] is False and qi["main_scientific_payload_IO"] is False
    vr=d["visual_review"]; assert vr["personally_viewed_with"]=="view_image" and vr["contact_sheet_count"]==34 and len(vr["contact_sheets"])==34 and vr["key_frame_count"]==9 and len(vr["key_frames"])==9
    for i,item in enumerate(vr["contact_sheets"]):
        check_ref(item,"visualization"); assert item["viewed"] is True and item["sheet_index"]==i and item["frame_start"]==i*24 and item["frame_end"]==min(i*24+23,800)
    assert [x["frame"] for x in vr["key_frames"]]==[0,100,200,300,400,500,600,700,800]
    for item in vr["key_frames"]:
        check_ref(item,"visualization"); assert item["viewed"] is True and item["path"].endswith(f"frame_{item['frame']:04d}.png")
    files={x["relative_path"]:x for x in pub["files_excluding_receipt"]}
    for item in vr["contact_sheets"]+vr["key_frames"]:
        p=Path(item["path"]); rel=p.name if p.parent.name!="frames" else f"frames/{p.name}"
        assert rel in files and files[rel]["sha256"]==item["sha256"] and files[rel]["bytes"]==item["bytes"]
    sb=d["source_boundaries"]; assert all(sb[k] is False for k in ("science_payload_read","science_payload_hashed","science_jobs_started","shared_registry_or_ledger_written","historical_source_changed","model_substitution"))
    assert d["future_work"]["no_new_render_or_solver_request"] is True
    print("fresh188 validation PASS: F5 M105/T080 Root1181 completed/0; 801 frames; 34 contacts + 9 keys viewed; canonical/legacy/SourceDef scopes separate; native source-plan fields null; no scientific payload IO; case credit 0")
if __name__=="__main__": main()
