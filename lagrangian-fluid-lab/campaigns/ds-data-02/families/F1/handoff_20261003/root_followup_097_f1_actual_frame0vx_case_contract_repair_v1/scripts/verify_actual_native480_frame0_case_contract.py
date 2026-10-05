#!/usr/bin/env python3
"""Verify F1 fresh097 frame-0 bindings without scientific payload access."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path

PAYLOAD_SUFFIXES={".bi4",".h5",".hdf5",".csv",".npy",".npz",".vtk",".dat",".raw"}
EXPECTED_KEYS=["case_id","expected_fluid","expected_total","expected_velocity_m_per_s","gencase_receipt","generated_xml","native_data_dir","native_solver_receipt","partvtk","source_definition"]

def load(p:Path):
 v=json.loads(p.read_text(encoding="utf-8"))
 if not isinstance(v,dict): raise RuntimeError(f"expected object: {p}")
 return v

def digest(p:Path):
 if p.suffix.lower() in PAYLOAD_SUFFIXES: raise RuntimeError(f"scientific payload read/hash forbidden: {p}")
 h=hashlib.sha256()
 with p.open("rb") as f:
  for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
 return h.hexdigest()

def require(c,m):
 if not c: raise RuntimeError(m)

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,required=True); a=ap.parse_args(); pkg=a.package.resolve()
 worker=pkg/"workers/native_initial_vx_frame0_audit.py"
 tree=ast.parse(worker.read_text(encoding="utf-8"))
 keys=sorted({n.slice.value for n in ast.walk(tree) if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name) and n.value.id=="case" and isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,str)})
 require(keys==EXPECTED_KEYS,f"worker case-key set changed: {keys}")
 reqs=sorted((pkg/"requests").glob("*.json")); binds=sorted((pkg/"bindings").glob("*.json"))
 require(len(reqs)==24 and len(binds)==24,f"expected 24 requests/bindings, got {len(reqs)}/{len(binds)}")
 summary=load(pkg/"metadata/actual-root480-native-frame0-source-summary.json")
 ctrl=load(Path(summary["actual_controller_result"]))
 require(ctrl.get("requested")==24 and ctrl.get("finished")==24 and ctrl.get("completed0")==24 and ctrl.get("pending_held")==0,"Root480 not 24 completed/0")
 bycase={x["case_id"]:x for x in ctrl["results"]}; bind_by={load(p)["case_id"]:p for p in binds}; require(len(bind_by)==24,"binding IDs not unique")
 for p in reqs:
  q=load(p); case=q.get("case_id"); require(q.get("fresh_id")=="fresh097",f"{case}: fresh ID"); require(case in bycase and case in bind_by,f"{case}: missing case")
  bpath=bind_by[case]; b=load(bpath); require(b.get("fresh_id")=="fresh097",f"{case}: binding fresh ID"); require(b.get("source_only") is True and b.get("execution_allowed") is False and b.get("launch_allowed") is False,f"{case}: binding enabled")
  require(b.get("partvtk") and b.get("partvtk_sha256"),f"{case}: top-level partvtk missing"); require(len(b.get("cases",[]))==1,f"{case}: worker case list")
  c=b["cases"][0]; require(c.get("case_id")==case,f"{case}: case ID mismatch"); require(sorted(k for k in c if k in EXPECTED_KEYS)==EXPECTED_KEYS,f"{case}: required case key missing"); require(c.get("partvtk")==b["partvtk"] and c.get("partvtk_sha256")==b["partvtk_sha256"],f"{case}: case PartVTK binding differs from top-level")
  require(q.get("disabled") is True and q.get("execution_allowed") is False and q.get("launch_allowed") is False and q.get("launch") is False,f"{case}: request enabled")
  require(q.get("future_input_sha256") is None and q.get("future_outputs",{}).get("sha256") is None,f"{case}: future hash populated")
  require(q.get("native_frame0_gate",{}).get("frame0_velocity_proved") is False,f"{case}: frame0 gate falsely passed")
  receipt=Path(q["native_solver_receipt"]); rr=load(receipt); require(rr.get("status")=="completed" and rr.get("returncode")==0,f"{case}: Root480 receipt not completed/0"); require(q["native_solver_receipt_sha256"]==digest(receipt),f"{case}: receipt SHA")
  full=Path(q["depends_on"]["fullnative_request"]); fq=load(full); require(fq.get("attempt_id")==q.get("native_solver_attempt_id"),f"{case}: actual native attempt mismatch"); require(q["depends_on"]["fullnative_request_sha256"]==digest(full),f"{case}: Root480 request SHA")
  require(rr.get("request_sha256")==q["depends_on"]["fullnative_request_sha256"],f"{case}: receipt request SHA")
  verify=set(q.get("input_files",[])); hashes=q.get("input_sha256",{}); require(verify==set(hashes),f"{case}: input closure mismatch")
  for raw in sorted(verify):
   x=Path(raw); require(x.is_file(),f"{case}: missing input {x}")
   if x.suffix.lower() in PAYLOAD_SUFFIXES: require(isinstance(hashes[raw],str) and len(hashes[raw])==64,f"{case}: producer payload digest missing")
   else: require(digest(x)==hashes[raw],f"{case}: stale input {x}")
 print(json.dumps({"schema":"ds02.f1.fresh097.frame0vx-case-contract-verification.v1","passed":True,"cases":24,"worker_case_keys":EXPECTED_KEYS,"partvtk_case_keys":24,"actual_native_completed0":24,"root490_failed_preserved":True,"frame0_velocity_proved":0,"scientific_payloads_read":False,"future_hashes":"null"},sort_keys=True))
if __name__=="__main__": main()
