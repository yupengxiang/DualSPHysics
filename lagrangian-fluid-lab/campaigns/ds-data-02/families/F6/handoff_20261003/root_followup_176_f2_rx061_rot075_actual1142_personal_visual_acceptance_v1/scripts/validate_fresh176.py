#!/usr/bin/env python3
"""Read-only validator for F6 fresh176 F2 RX061 ROT075 visual evidence."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
FORBIDDEN=(".h5", ".hdf5", ".bi4", ".csv", ".dat", ".vtk")
ALLOWED=(".json", ".xml", ".xmf", ".png")
def sha(p:Path)->str:
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def check_ref(x:dict, expected_kind:str|None=None)->Path:
 assert isinstance(x,dict)
 for key in ("path","sha256","bytes","kind"): assert key in x,(key,x)
 p=Path(x["path"]); assert p.is_file(),p
 low=str(p).lower(); assert not any(low.endswith(s) for s in FORBIDDEN),p
 assert p.suffix.lower() in ALLOWED,p
 assert sha(p)==x["sha256"],(p,"SHA drift")
 assert p.stat().st_size==x["bytes"],(p,"size drift")
 if expected_kind is not None: assert x["kind"]==expected_kind,(p,x["kind"],expected_kind)
 return p
def load_receipt(x:dict)->dict:
 p=check_ref(x,"metadata"); d=json.loads(p.read_text())
 assert d.get("schema")=="ds02.execution-receipt.v1",(p,d.get("schema"))
 assert d.get("status")=="completed",(p,d.get("status"))
 assert d.get("returncode")==0,(p,d.get("returncode"))
 return d
def main()->None:
 ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,default=Path(__file__).parents[1]); pkg=ap.parse_args().package
 d=json.loads((pkg/"metadata/personal-visual-decision.json").read_text())
 assert d["schema"]=="ds02.f6.fresh176.f2-personal-visual-review.v1"
 assert d["fresh_id"]=="fresh176" and d["family_id"]=="F6" and d["actual_case_family"]=="F2"
 assert d["model"]=="gpt-5.6-luna" and d["reasoning_effort"]=="max" and d["recursive_delegation"] is False
 c=d["case"]; assert c["case_id"].endswith("ROT075_DP010_SPATIAL_REFERENCE_SAVE010"); assert c["physical_case_id"].endswith("ROT075")
 assert c["canonical_native_physical_condition_sha256"]=="81c41048077fd52e0810a850bf5b78b0ab77abf36186f8c9dd7bb66f835dcb89"
 assert c["typed_render_legacy_actual_converter_scope_sha256"]=="9976f5ac3ff397356bd54d417c572c5fd6876a4418ea922cec45833bc0d69744"
 assert c["scope_roles"]["equality_claimed"] is False
 dec=d["decision"]; assert dec["status"]=="visual-approved-by-delegated-agent"; assert dec["case_credit"]==0 and dec["global_acceptance"] is False; assert dec["precision_status"]=="not accepted"; assert dec["q_n_granted"] is False and dec["q_e_granted"] is False; assert dec["production_approval"] is False; assert dec["visual_zero_fluid_loss_claim"] is False and dec["strict_container_guarantee"] is False
 ev=d["evidence"]
 for k in ("gencase_receipt","initial_qa_receipt","native_receipt","typed_receipt","xmf_receipt","render_receipt"): load_receipt(ev[k])
 for k in ("generated_xml","initial_qa_report","typed_report","xmf_manifest","xmf_xml","render_report","publish_receipt","registered_request","render_wrapper","controller_result","producer_chain_review","main_qi_proof"): check_ref(ev[k],"metadata")
 report=json.loads(Path(ev["render_report"]["path"]).read_text()); assert report["frames"]==report["source_frames"]==401; assert report["all_frames_rendered"] is True and report["actual_times_preserved_exactly"] is True; assert report["native_identity_axis_preserved"] is True and report["nonfinite_active_states"]==0; assert len(report["outputs"]["contact_sheets"])==17
 assert d["render_contract"]["publish_status"]=="published_after_atomic_rename" and d["render_contract"]["source_h5_opened_or_hashed_by_wrapper"] is False
 life=d["lifecycle_and_render_metadata"]; assert life["final_missing_particles"]==39 and life["maximum_missing_particles"]==39 and life["first_missing_frame"]==137 and life["transient_missing_frame_count"]==264 and life["particle_frame_omission_events"]==8748 and life["final_missing_id_sample_count"]==8 and life["final_missing_ids_sample_not_complete"] is True and life["missing_locations_states_and_causes_unknown"] is True; assert life["fluid_missing_fraction_of_initial_fluid"]=={"numerator":39,"denominator":21114,"percent":0.1847115658}
 idx=json.loads((pkg/"metadata/png-evidence.json").read_text()); assert idx["personally_viewed_with"]=="view_image" and idx["contact_sheet_count"]==17 and idx["key_frame_count"]==9
 contacts=[x for x in idx["items"] if "sheet_index" in x]; keys=[x for x in idx["items"] if "frame" in x]; assert len(contacts)==17 and len(keys)==9 and [x["sheet_index"] for x in contacts]==list(range(17)) and [x["frame"] for x in keys]==[0,50,100,150,200,250,300,350,400]
 for x in idx["items"]: check_ref(x,"visualization")
 check_ref(d["png_evidence"],"metadata")
 sb=d["source_boundaries"]; assert sb["science_payload_read"] is False and sb["science_payload_hashed"] is False and sb["science_jobs_started"] is False and sb["shared_registry_or_ledger_written"] is False
 print("fresh176 validation PASS: F2 RX061 ROT075; 17 contacts + 9 keys viewed; Root1142 completed/0 and published full401 verified; 39/264/8748 omission stats retained; case credit 0")
if __name__=="__main__": main()
