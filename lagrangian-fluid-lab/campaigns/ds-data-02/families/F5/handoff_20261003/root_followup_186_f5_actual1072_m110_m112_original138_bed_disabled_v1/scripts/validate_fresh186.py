#!/usr/bin/env python3
"""Metadata-only fresh186 validator; no science payload IO or worker launch."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[0].parent
SCIENCE={".h5",".hdf5",".bi4",".ibi4",".csv",".dat",".vtk",".vtu",".npy",".npz"}
def sha(p):
 p=Path(p)
 if p.suffix.lower() in SCIENCE: raise AssertionError("science hash forbidden: "+str(p))
 if not p.is_file(): raise AssertionError("metadata missing: "+str(p))
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def ck(ok,msg):
 if not ok: raise SystemExit("FAIL: "+msg)
def main():
 s=load(PKG/"metadata/fresh186-source-plan.json"); ck(s["execution_allowed"] is False and len(s["cases"])==4,"source plan")
 c=load(PKG/"metadata/worker-contract.json"); w=PKG/"workers/identity_bound_bed_audit_fresh186.py"; ck(sha(w)==c["adapter_sha256"],"worker hash"); ck(c["original_worker_sha256"]=="89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2","original138 hash")
 out=[]
 for case in s["cases"]:
  b=load(case["binding"]); q=load(case["request"]); ch=load(case["chain"]); t=case["tag"]; ck(b["schema"]=="ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1",t+" schema"); ck(b["execution_allowed"] is False and b["disabled"] is True and q["execution_allowed"] is False and q["disabled"] is True,t+" disabled"); ck((q["kind"],q["cpu_task_kind"],q["cpu_threads"],q["declared_cpu_cores"]) == ("cpu","audit",2,2),t+" CPU2"); ck(q["shared_conversion_concurrency_cap"]==1 and q["resource_ledger_lock"].endswith("/runtime/resource-ledger.lock"),t+" serial"); ck(b["case_id"]==case["case_id"]==q["case_id"]==ch["case_id"],t+" identity"); ck((b["expected_particle_axis"],b["expected_fluid_particles"],b["expected_fixed_particles"],b["expected_moving_particles"],b["expected_dimension"],b["expected_frames"])==(194427,31658,158559,4210,3,801),t+" counts"); ck((b["native_bed_marker_mk"],b["source_bed_marker_mkbound"])==(50,40),t+" Mk"); ck(len({b["physical_condition_sha256"],b["source_plan_physical_condition_sha256"],b["source_h5_physical_condition_sha256"]})==3,t+" scopes"); ck(b["source_h5_physical_condition_sha256"]==b["typed_report_physical_condition_sha256"],t+" legacy"); ck(b["bed_audit_receipt"] is None and b["bed_audit_report"] is None,t+" future")
  for k,hk in [("source_definition","source_definition_sha256"),("source_plan_file","source_plan_file_sha256"),("source_generation_report","source_generation_report_sha256"),("owner_metadata","owner_metadata_sha256"),("gencase_receipt","gencase_receipt_sha256"),("gencase_prepared_report","gencase_prepared_report_sha256"),("canonical_generated_xml","canonical_generated_xml_sha256"),("initial_qa_receipt","initial_qa_receipt_sha256"),("initial_qa_report","initial_qa_report_sha256"),("actual_initial_qa_producer_metadata","actual_initial_qa_producer_metadata_sha256"),("full_native_receipt","full_native_receipt_sha256"),("full_typed_receipt","full_typed_receipt_sha256"),("full_typed_conversion_report","full_typed_conversion_report_sha256"),("xmf_manifest","xmf_manifest_sha256"),("xmf_receipt","xmf_receipt_sha256"),("xdmf","xdmf_sha256")]:
   p=Path(b[k]); ck(p.suffix.lower() not in SCIENCE and p.is_file(),t+" "+k); ck(sha(p)==b[hk],t+" "+k+" hash")
  for p,h in q["input_sha256"].items(): pp=Path(p); ck(pp.suffix.lower() not in SCIENCE and pp.is_file() and sha(pp)==h,t+" input closure")
  m=load(b["xmf_manifest"]); ck(m["case_id"]==case["case_id"] and m["frames"]==801 and m["particles"]==194427,t+" XMF shape"); ck(m["source_h5_sha256"]==b["trajectory_h5_sha256"],t+" H5 attestation"); ck(m["physical_condition_sha256"]==b["physical_condition_sha256"] and m["canonical_physical_condition_sha256"]==b["physical_condition_sha256"],t+" canonical"); g=load(b["gencase_prepared_report"]); ck(g["case_id"]==case["case_id"] and g["actual_total_particles"]==194427,t+" GenCase"); a=load(b["initial_qa_report"]); ck(a["all_basic_placement_checks_pass"] is True and a["numerical_precision_result_accepted"] is False and a["actual_counts"]==b["actual_counts"],t+" QA")
  for k in ("gencase_receipt","initial_qa_receipt","full_native_receipt","full_typed_receipt","xmf_receipt"):
   r=load(b[k]); ck(r.get("status") in {"completed","completed/0"} and r.get("returncode")==0,t+" "+k)
  out.append({"tag":t,"case_id":case["case_id"],"physical_case_id":case["physical_case_id"],"counts":b["actual_counts"],"scopes":{"canonical":b["physical_condition_sha256"],"source_def_role":b["source_plan_physical_condition_sha256"],"producer_xmf_source_plan":b["producer_xmf_declared_source_plan_physical_condition_sha256"],"typed_legacy":b["source_h5_physical_condition_sha256"]}})
 print(json.dumps({"schema":"ds02.f5.fresh186.metadata-validator.v1","status":"passed","cases":out,"science_payload_opened_or_hashed":False,"original138_gate":"deferred to Root142; no worker launch or science frame listing"},indent=2,sort_keys=True))
if __name__=="__main__": main()
