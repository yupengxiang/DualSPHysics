#!/usr/bin/env python3
"""Read-only metadata validator for fresh222.

This validator hashes only package files and external JSON/XML/XMF/Python
metadata/code references. It never opens or hashes H5, BI4, IBI4, CSV, DAT,
VTK, PNG, or any other science payload.
"""
from pathlib import Path
import hashlib, json, re
ROOT=Path(__file__).resolve().parents[1]
CASE="F2_STAGE1_FIRST48_EXPANSION_RX061_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"
PHYS="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX061_RY014_FILL080_ROT090"
CAN="d5554e9607723d41638618937d2c681cfdec3084b54297bf0e75b4f82a9885bc"
LEG="cb836db0de7dd6e6b9e2beef7f8dbffb85a461af59aa8db10feccdcde9ec11e7"
H5="a8d860bdcd429cf647a7df645138e6281ed2f8fbf2fb6496842b68f895d32815"
EXPECTED={"README.md","metadata/preflight.json","metadata/upstream-metadata-evidence.json","metadata/render-pending.json","scripts/validate_fresh222.py"}
FORBIDDEN={".h5",".bi4",".ibi4",".csv",".dat",".vtk",".png"}
def dg(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def ok(v,m):
    if not v: raise AssertionError(m)
def load(rel): return json.loads((ROOT/rel).read_text())
def main():
    m=load("manifest.json"); ok(m["source_only"] and m["manifest_excludes_self"],"manifest flags")
    ok(m["assigned_family_id"]=="F5" and m["actual_physical_family_id"]=="F2","family")
    ok(not m["science_payloads_copied"] and not m["scientific_jobs_started_by_source_agent"] and not m["shared_state_written_by_source_agent"],"isolation")
    files={x["path"]:x for x in m["files"]}; ok(set(files)==EXPECTED,"package file set")
    for rel,item in files.items():
        p=ROOT/rel; ok(p.is_file(),"missing package file: "+rel); ok(p.stat().st_size==item["bytes"],"package bytes: "+rel); ok(dg(p)==item["sha256"],"package SHA: "+rel)
    p=load("metadata/preflight.json"); u=load("metadata/upstream-metadata-evidence.json"); q=load("metadata/render-pending.json")
    ok(p["case_id"]==CASE and p["physical_case_id"]==PHYS and p["model"]=="gpt-5.6-luna/max" and p["recursive_delegation"] is False,"preflight identity")
    ok(p["identity"]["canonical_source_physical_scope_sha256"]==CAN and p["identity"]["actual_converter_legacy_scope_sha256"]==LEG and p["identity"]["scope_equality_claimed"] is False,"scope identity")
    shape=p["actual_case_shape"]; ok(shape=={**shape,"frames":401,"particles":418104,"contact_sheets":17,"keyframe_indices":[0,50,100,150,200,250,300,350,400],"dimension":3},"shape")
    ok(p["upstream_chain"]["gencase"]["status"]=="completed" and p["upstream_chain"]["gencase"]["returncode"]==0,"GenCase")
    ok(p["upstream_chain"]["initial_qa"]["status"]=="pass" and all(p["upstream_chain"]["initial_qa"]["checks"].values()),"QA")
    n=p["upstream_chain"]["native"]; ok(n["status"]=="completed" and n["returncode"]==0 and n["expected_frames"]==401 and n["expected_particles"]==418104 and n["expected_dimension"]==3,"native")
    ok(n["condition_plan"]=={"field":"source_plan_condition_sha256","present":False,"sha256":None},"native condition mask")
    ok(n["physical_plan"]=={"field":"source_plan_physical_condition_sha256","present":True,"sha256":CAN},"native physical mask")
    t=p["upstream_chain"]["typed"]; ok(t["conversion_status"]=="completed" and t["frames"]==401 and t["particles"]==418104 and t["solver_dimension"]==3 and t["xml_data2d"]=="false","typed")
    x=p["upstream_chain"]["xmf"]; masks=x["raw_binding_masks"]; ok(masks["source_plan_condition_sha256"]["present"] is False and masks["source_plan_physical_condition_sha256"]["present"] is False,"XMF plan masks")
    ok(masks["physical_condition_sha256"]["present"] and masks["physical_condition_sha256"]["sha256"]==LEG,"XMF legacy physical")
    ok(masks["canonical_source_physical_condition_sha256"]["present"] and masks["canonical_source_physical_condition_sha256"]["sha256"]==CAN,"XMF canonical physical")
    miss=p["fluid_missing_history"]; ok(miss["final_missing_particles"]==1 and miss["first_missing_frame"]==157 and miss["frames_with_missing_particles"]==244 and miss["max_missing_particles"]==1 and miss["only_fluid_omitted"] and miss["unknown_missing_locations_states_and_causes"],"missing history")
    ok(p["science_payload_boundary"]["source_agent_computed_science_payload_hashes"] is False and p["science_payload_boundary"]["producer_attested_H5_sha256"]==H5,"payload boundary")
    ok(q["expected"]=={"frames":401,"particles":418104,"contact_sheets":17,"keyframe_indices":[0,50,100,150,200,250,300,350,400]},"render envelope")
    ok(q["receipt"] is None and q["render_report"] is None and q["publish_receipt"] is None and q["main_own_qi"] is None,"pending outputs")
    ok(q["personal_visual_review"]["contacts_viewed"]==0 and q["personal_visual_review"]["keyframes_viewed"]==0,"pending review")
    ok(not p["scope_and_claim_limits"]["strict_containment"] and not p["scope_and_claim_limits"]["q_n_granted"] and p["scope_and_claim_limits"]["case_credit_increment"]==0,"claim limits")
    ok(len(u["external_metadata_refs"])>=30,"metadata refs")
    allowed={".json",".xml",".xmf",".py"}
    for r in u["external_metadata_refs"]:
        path=Path(r["path"]); ok(path.is_file(),"missing external metadata: "+str(path)); ok(path.suffix.lower() in allowed,"forbidden external suffix: "+str(path)); ok(dg(path)==r["sha256"],"external SHA mismatch: "+str(path))
        ok(not any(str(path).lower().endswith(s) for s in FORBIDDEN),"science payload ref")
    print("fresh222 F5-assigned F2 RX061/ROT090 metadata preflight PASS")
    print("package="+str(ROOT))
    print("visual_review=pending; contacts=0; keyframes=0; case_credit_increment=0")
if __name__=="__main__": main()
