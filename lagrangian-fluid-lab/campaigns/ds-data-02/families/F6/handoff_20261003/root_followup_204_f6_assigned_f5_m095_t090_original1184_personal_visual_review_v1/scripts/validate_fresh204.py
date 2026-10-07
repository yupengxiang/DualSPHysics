#!/usr/bin/env python3
"""Read-only fresh204 validator; never opens or hashes PNG/scientific payloads."""
import hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]; META=PKG/"metadata/m095-t090-personal-visual-review.json"
def digest(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 return h.hexdigest()
def main():
 d=json.loads(META.read_text()); assert d["schema"]=="ds02.f6.fresh204.f5-m095-t090-personal-visual-review.v1"
 assert d["case_id"]=="F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1" and d["physical_case_id"]=="F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
 e=d["visual_evidence"]; assert e["contact_sheet_count"]==34 and e["key_frame_count"]==9 and len(e["items"])==43
 for x in e["items"]:
  p=Path(x["path"]); assert p.exists() and p.stat().st_size==x["bytes"]; assert x["source_agent_viewed_with_view_image"] and not x["source_agent_hashed_png"] and x["source_agent_did_not_hash_png"]; assert len(x["producer_declared_sha256"])==64
 assert d["review_method"]["total_pngs_viewed"]==43 and d["review_method"]["source_agent_did_not_hash_png"]
 t=d["physical_and_time_metadata"]; assert t["actual_frames"]==801 and t["expected_particles"]==194427 and t["actual_time_last_s"]==16.00009662908174
 s=d["scope_roles"]; assert s["native_request_source_plan_condition_sha256"] is None and s["native_request_source_plan_physical_condition_sha256"] is None and not s["native_request_field_presence"]["source_plan_condition_sha256"] and not s["native_request_field_presence"]["source_plan_physical_condition_sha256"]; assert s["xmf_physical_plan_role"]=="SourceDef" and s["xmf_physical_plan_sha256"]==s["source_definition_sha256"]
 q=d["root_qi_evidence"]; assert digest(Path(q["proof_path"]))==q["proof_sha256"]
 assert not d["producer_h5_attestation"]["source_agent_read_or_hashed"] and not d["producer_h5_attestation"]["validator_opens_or_hashes"]
 f=d["flags"]; assert f["case_credit"]==0 and not f["Q_N"] and not f["Q_E"] and not f["precision_accepted"] and not f["strict_containment_claim"] and not f["source_agent_read_scientific_payload"] and not f["source_agent_hashed_scientific_payload"] and not f["source_agent_hashed_png"]
 assert d["visual_decision"]["status"]=="visual-approved-by-delegated-agent"
 for k,r in d["producer_chain"].items():
  p=Path(r["path"]); assert r["exists_at_freeze"] and p.exists(),(k,p)
  if r.get("hash_policy")=="metadata_file": assert digest(p)==r["observed_sha256"],(k,p)
 print("fresh204 validator: PASS (43 PNGs viewed/stat'ed; no PNG/science payload digest computed)")
if __name__=="__main__": main()
