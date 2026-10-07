#!/usr/bin/env python3
"""Read-only validator for F6 fresh193 F2 RX063/ROT090 visual evidence.

Only JSON/XML/XMF metadata and published PNGs are opened. This validator never
opens or hashes H5/BI4/CSV/DAT/VTK payloads and never launches work.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ALLOWED_METADATA={".json",".xml",".xmf"}
ALLOWED_VISUAL={".png"}
FORBIDDEN={".h5",".hdf5",".bi4",".csv",".dat",".vtk",".vtu",".vtp",".pvd",".raw"}
CASE="F2_STAGE1_FIRST48_EXPANSION_RX063_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010"
PHYS="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX063_RY014_FILL080_ROT090"
CANON="7d7c2dc27d0a3c8eaa297a3c48dc4cec27bf075003e2933591a537c755f69e23"
LEGACY="a5892c54ca3899cc592df4ea831290e1baef0ffbee453ea6e1700a41e39e6148"

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda:fh.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def check_ref(item:dict, kind:str|None=None)->Path:
    assert isinstance(item,dict) and {"path","sha256","bytes","kind"}<=set(item),item
    p=Path(item["path"]); assert p.is_file(),p
    assert p.suffix.lower() in ALLOWED_METADATA|ALLOWED_VISUAL,p
    assert not any(str(p).lower().endswith(s) for s in FORBIDDEN),p
    assert sha(p)==item["sha256"],(p,"sha drift")
    assert p.stat().st_size==item["bytes"],(p,"size drift")
    if kind is not None: assert item["kind"]==kind,(p,item["kind"],kind)
    return p

def read_ref(ev,key):
    p=check_ref(ev[key],"metadata"); return p,json.loads(p.read_text())

def completed(ev,key):
    p,d=read_ref(ev,key)
    assert d.get("schema")=="ds02.execution-receipt.v1",(p,d.get("schema"))
    assert d.get("status")=="completed" and d.get("returncode")==0,(p,d.get("status"),d.get("returncode"))
    return d

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,default=Path(__file__).resolve().parents[1]); a=ap.parse_args()
    pkg=a.package.resolve(); d=json.loads((pkg/"metadata/personal-visual-decision.json").read_text())
    assert d["schema"]=="ds02.f6.fresh193.f2-personal-visual-review.v1"
    assert d["fresh_id"]=="fresh193" and d["family_id"]==d["assigned_family"]=="F6" and d["actual_family"]=="F2"
    assert d["model"]=="gpt-5.6-luna" and d["reasoning_effort"]=="max" and d["recursive_delegation"] is False
    c=d["case"]
    assert c["case_id"]==CASE and c["physical_case_id"]==PHYS
    assert c["canonical_native_physical_condition_sha256"]==CANON and c["actual_converter_legacy_scope_sha256"]==LEGACY
    assert c["declared_counts"]=={"fixed":372840,"moving":24150,"floating":0,"fluid":21114,"total":418104}
    assert c["terminal_counts"]=={"fixed":372840,"moving":24150,"floating":0,"fluid":21099,"total":418089}
    assert c["dimension"]==3 and c["expected_frames"]==401 and c["actual_time_s"]==[0.0,4.000030243152287]
    roles=c["scope_roles"]
    assert roles["native_canonical_physical"]==CANON and roles["typed_actual_converter_legacy"]==LEGACY
    assert roles["xmf_manifest_physical_condition_legacy"]==LEGACY and roles["xmf_manifest_canonical_source_physical_condition"]==CANON
    assert roles["native_source_plan_condition_sha256"] is None and roles["native_source_plan_physical_condition_sha256"]==CANON
    assert roles["xmf_source_plan_condition_sha256"] is None and roles["xmf_source_plan_physical_condition_sha256"] is None
    assert roles["native_plan_equals_xmf_plan"] is False and roles["equality_claimed"] is False and roles["roles_remain_distinct"] is True
    om=c["lifecycle_omissions"]
    assert (om["final_missing_particles"],om["max_missing_per_frame"],om["first_missing_frame"],om["cumulative_particle_frame_omissions"])==(15,15,158,2278)
    assert om["missing_location_state_cause_unknown"] is True
    dec=d["decision"]
    assert dec["status"]=="visual-approved-by-delegated-agent" and dec["case_credit"]==0 and dec["global_acceptance"] is False
    assert dec["precision_status"]=="not accepted" and dec["q_n_granted"] is False and dec["q_e_granted"] is False and dec["production_approval"] is False
    for f in ("initial_state","mechanism","mid_event","late_event","failure_screen","limits"): assert dec["observations"].get(f)

    ev=d["evidence"]
    required={"main_qi_proof","prior_scientific_integrity_review","gencase_receipt","prepared_input_report","generated_xml","initial_qa_receipt","initial_qa_report","native_request","native_receipt","typed_request","typed_report","typed_receipt","source_owner","xmf_request","xmf_binding","xmf_registration","xmf_manifest","xmf_xml","xmf_receipt","render_request","render_wrapper","render_controller_result","render_controller_config","render_independent_review","render_receipt","render_report","publish_receipt"}
    assert required<=set(ev),sorted(required-set(ev))
    for item in ev.values(): check_ref(item,"metadata")
    for key in ("gencase_receipt","initial_qa_receipt","native_receipt","typed_receipt","xmf_receipt","render_receipt"): completed(ev,key)

    qpath,q=read_ref(ev,"main_qi_proof")
    assert q["case_id"]==CASE and q["physical_case_id"]==PHYS and q["frames"]==401 and q["particles"]==418104
    assert q["actual_initial_type_counts"]=={"fixed":372840,"moving":24150,"floating":0,"fluid":21114,"total":418104}
    assert q["actual_terminal_type_counts"]=={"fixed":372840,"moving":24150,"floating":0,"fluid":21099,"total":418089}
    assert q["actual_time_window_s"]==[0.0,4.000030243152287] and q["native_canonical_condition_sha256"]==CANON and q["typed_XMF_actual_legacy_producer_condition_sha256"]==LEGACY
    assert q["actual_native_XMF_plan_field_namespaces"]=={"native":{"source_plan_condition_sha256":{"present":False,"value":None},"source_plan_physical_condition_sha256":{"present":True,"value":CANON}},"XMF":{"source_plan_condition_sha256":{"present":False,"value":None},"source_plan_physical_condition_sha256":{"present":False,"value":None}}}
    assert q["lifecycle_omissions"]["final_missing_particles"]==15 and q["lifecycle_omissions"]["cumulative_particle_frame_omissions"]==2278
    assert q["lifecycle_omissions"]["final_Idp_sample_is_partial_not_all15"] is True and q["lifecycle_omissions"]["missing_location_state_cause_unknown"] is True
    assert q["genuine_initial_QA_receipt_completed0_and_report_pass"] is True and q["root_QI_is_independent_proof_not_runner_receipt"] is True
    assert q["strict_container_guarantee"] is False and q["subDP_precision_not_claimed"] is True and q["case_credit"]==0 and q["scientific_payload_IO"] is False

    _,prep=read_ref(ev,"prepared_input_report"); assert prep["case_id"]==CASE
    _,qa=read_ref(ev,"initial_qa_report"); assert qa["case_id"]==CASE and qa["status"]=="pass" and all(qa["checks"].values())
    _,man=read_ref(ev,"xmf_manifest")
    assert man["schema"]=="ds02.stage1.paraview-temporal-product.v1" and man["case_id"]==CASE and man["physical_case_id"]==PHYS
    assert man["frames"]==man["expected_frames"]==401 and man["particles"]==418104
    assert man["actual_converter_legacy_scope_sha256"]==LEGACY and man["canonical_source_physical_condition_sha256"]==CANON and man["physical_condition_sha256"]==LEGACY
    assert man["scope_equality_not_claimed"] is True and man["source_h5_read_only"] is True
    _,rep=read_ref(ev,"render_report")
    assert rep["schema"]=="ds02.stage1.paraview-full-animation-integrity.v1" and rep["frames"]==rep["source_frames"]==401
    assert rep["all_frames_rendered"] is True and rep["actual_times_preserved_exactly"] is True and rep["native_identity_axis_preserved"] is True and rep["nonfinite_active_states"]==0
    _,pub=read_ref(ev,"publish_receipt"); assert pub["status"]=="published_after_atomic_rename" and pub["source_h5_opened_or_hashed_by_wrapper"] is False
    published={x["relative_path"]:x for x in pub["files_excluding_receipt"]}
    vr=d["visual_review"]
    assert vr["personally_viewed_with"]=="view_image" and vr["contact_sheet_count"]==17 and len(vr["contact_sheets"])==17 and vr["key_frame_count"]==9 and len(vr["key_frames"])==9
    assert vr["key_frame_indices"]==[0,50,100,150,200,250,300,350,400] and vr["report_frames"]==vr["report_source_frames"]==401
    for i,item in enumerate(vr["contact_sheets"]):
        p=check_ref(item,"visualization"); assert item["viewed"] is True and item["sheet_index"]==i and item["frame_start"]==i*24 and item["frame_end"]==min(i*24+23,400)
        rel=f"all_frames_{i:03d}.png"; assert p.name==rel and published[rel]["sha256"]==item["sha256"] and published[rel]["bytes"]==item["bytes"]
    assert [x["frame"] for x in vr["key_frames"]]==[0,50,100,150,200,250,300,350,400]
    for item in vr["key_frames"]:
        p=check_ref(item,"visualization"); rel=f"frames/frame_{item['frame']:04d}.png"; assert p.name==f"frame_{item['frame']:04d}.png" and published[rel]["sha256"]==item["sha256"] and published[rel]["bytes"]==item["bytes"]
    for f in ("science_payload_read","science_payload_hashed","science_jobs_started","shared_registry_or_ledger_written","historical_source_changed","model_substitution"): assert d["source_boundaries"][f] is False
    assert d["future_work"]["no_new_render_or_solver_request"] is True

    pm=json.loads((pkg/"metadata/package-manifest.json").read_text())
    assert pm["schema"]=="ds02.f6.fresh193.package-manifest.v1" and pm["fresh_id"]=="fresh193" and pm["source_only"] is True
    assert pm["visual_products_viewed"]=={"contact_sheets":17,"key_frames":9,"view_tool":"view_image"}
    for x in pm["files"]:
        p=pkg/x["path"]; assert p.is_file() and p.stat().st_size==x["bytes"] and sha(p)==x["sha256"],p
    print("fresh193 validation PASS: F2 RX063/ROT090 Root1143 completed/0; 401 frames; 17 contacts + 9 keys personally viewed; scopes separate; 15 fluid omissions preserved; no scientific payload IO; case credit 0")

if __name__=="__main__": main()
