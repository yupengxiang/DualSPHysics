#!/usr/bin/env python3
"""Metadata-only validator for fresh157; never opens scientific payloads."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/"metadata/f3-actual-first24-delivery-manifest.json"
FORBIDDEN={".h5",".hdf5",".bi4",".csv",".dat",".vtk",".vtp",".pvd",".pvtu"}
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def source_ok(x):
 p=Path(x["path"]); assert p.exists(),p; assert p.suffix.lower() not in FORBIDDEN,p; assert sha(p)==x["sha256"],p
def main():
 r=json.loads(REPORT.read_text())
 assert r["fresh_id"]=="fresh157" and r["family_id"]=="F3"
 b=r["scientific_payload_boundary"]
 assert all(b[k] is False for k in ("opened","read","hashed","copied","jobs_started","jobs_restarted","jobs_stopped","shared_state_modified","global_case_credit_written","png_viewed"))
 c=r["authoritative_counts"]
 assert c["f3_accepted_at_cp214"]==37 and c["f3_registered_final_roster"]==48 and c["f3_current_accepted_rows"]==37
 assert r["frozen_first8"]["count"]==8 and r["source1205_planned_first24"]["count"]==24 and r["actual_first24_delivery"]["count"]==24
 m=r["actual_first24_delivery"]["members"]; assert len(m)==24 and len({(x["case_id"],x["physical_case_id"]) for x in m})==24
 assert all(x["accepted_status"].startswith("visual-approved") for x in m)
 assert all(x["accepted_decision_status"].startswith("visual-approved") for x in m)
 assert all(x["new_case_credit"]==0 for x in m)
 proof=r["membership_proof"]
 assert proof["first8_subset_actual24"] and proof["actual24_subset_current_accepted37"] and proof["current_accepted37_subset_registered_final48"]
 assert proof["no_case_or_physical_alias_silently_equated"] and proof["no_resolution_or_retry_alias_counted_as_new"]
 assert r["scope_role_preservation"]["anchor_accepted_semantic_top_scope_sha256"]=="49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb"
 assert r["scope_role_preservation"]["anchor_actual_native_request_scope_sha256"]=="86562c5afee8228131d58c1b53f360eb6c6a700381c01bf807a0f268bbc675c0"
 assert len(r["scope_role_preservation"]["historical_original_native_os_unknown_cases"])==4
 assert len(r["cp214_f3_accepted_order"])==37
 # The append records must equal the first 16 accepted checkpoint rows after the frozen first8 set.
 first8={(x["case_id"],x["physical_case_id"]) for x in r["frozen_first8"]["members"]}
 cp=[x for x in r["cp214_f3_accepted_order"] if (x["case_id"],x["physical_case_id"]) not in first8]
 append=[x for x in m if x["membership_role"]=="checkpoint_append"]
 assert len(append)==16
 assert [(x["case_id"],x["physical_case_id"]) for x in append]==[(x["case_id"],x["physical_case_id"]) for x in cp[:16]]
 assert [(x["case_id"],x["physical_case_id"]) for x in m[:8]]==[(x["case_id"],x["physical_case_id"]) for x in r["frozen_first8"]["members"]]
 assert r["plan_vs_actual_difference"]["plan_only_count"]==5 and r["plan_vs_actual_difference"]["actual_only_count"]==5
 for x in r["authoritative_sources"].values(): source_ok(x)
 if r.get("index_declared_authoritative_checkpoint"): source_ok(r["index_declared_authoritative_checkpoint"])
 # Check all decision refs used by the manifest and the frozen first8 are unchanged JSON files.
 for x in m:
  source_ok(x["accepted_decision"])
  if x.get("frozen_first8_decision"): source_ok(x["frozen_first8_decision"])
 for x in r["frozen_first8"]["members"]: source_ok(x["frozen_decision"]); source_ok(x["accepted_cp214_decision"])
 # No forbidden scientific artifact is packaged.
 for p in ROOT.rglob("*"):
  if p.is_file(): assert p.suffix.lower() not in FORBIDDEN,p
 integ=ROOT/"metadata/package-integrity.json"; d=json.loads(integ.read_text()); listed={x["path"]:x for x in d["files"]}; actual={str(p.relative_to(ROOT)):p for p in ROOT.rglob("*") if p.is_file() and p.name!="package-integrity.json"}; assert set(listed)==set(actual)
 for rel,x in listed.items(): assert x["bytes"]==actual[rel].stat().st_size and x["sha256"]==sha(actual[rel]),rel
 print("fresh157 metadata validation PASS: frozen first8 + actual accepted first24 + current accepted37/registered48")
if __name__=="__main__": main()
