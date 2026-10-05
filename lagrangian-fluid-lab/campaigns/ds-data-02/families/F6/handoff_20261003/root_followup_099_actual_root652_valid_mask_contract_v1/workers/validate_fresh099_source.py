#!/usr/bin/env python3
from __future__ import annotations
import ast,hashlib,json
import numpy as np
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]; REQ=PKG/"requests"; WORKER=PKG/"workers"/"audit_f6_typed_h5_full241_fresh099.py"
FORBIDDEN=(".h5",".bi4",".ibi4",".csv",".dat",".vtu",".vtk")
SCHEMA="ds02.f6.fresh094.typed-h5-full241-audit-request.v1"
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
 qs=sorted(REQ.glob("*.json")); assert len(qs)==24 and WORKER.is_file()
 t=WORKER.read_text(encoding="utf-8")
 assert 'SCHEMA = "ds02.f6.fresh099.typed-h5-full241-audit-result.v1"' in t
 assert "conversion_report.lifecycle.frame_summary" in t and "PRODUCER_TIME_MATCH_TOLERANCE_S = 1.0e-12" in t
 assert "nominal_schedule_is_report_only" in t and "TIME_TOLERANCE_S" not in t
 ast.parse(t)
 assert "def normalized_counts(" in t
 assert "EXPECTED_MK = {30: 73441, 1: 327680, 60: 16384}" in t
 assert "def valid_mask_values(" in t
 nodes=ast.parse(t).body
 fn=next(n for n in nodes if isinstance(n,ast.FunctionDef) and n.name=="normalized_counts")
 valid_fn=next(n for n in nodes if isinstance(n,ast.FunctionDef) and n.name=="valid_mask_values")
 class SyntheticAuditError(Exception): pass
 def synthetic_require(condition,message):
  if not condition: raise SyntheticAuditError(message)
 def synthetic_finite_numeric(array,label):
  values=np.asarray(array)
  if not np.issubdtype(values.dtype,np.number):
   raise SyntheticAuditError(f"{label} is not numeric")
  if not bool(np.all(np.isfinite(values))):
   raise SyntheticAuditError(f"{label} contains non-finite values")
 ns={"np":np,"require":synthetic_require}
 exec(compile(ast.Module(body=[fn],type_ignores=[]),str(WORKER),"exec"),ns)
 normalize=ns["normalized_counts"]
 mask_ns={"np":np,"require":synthetic_require,"finite_numeric":synthetic_finite_numeric}
 exec(compile(ast.Module(body=[valid_fn],type_ignores=[]),str(WORKER),"exec"),mask_ns)
 valid_mask=mask_ns["valid_mask_values"]
 bool_mask=valid_mask(np.array([True,False],dtype=np.bool_),"synthetic-bool")
 assert bool_mask.dtype == np.bool_ and bool_mask.tolist() == [True,False]
 numeric_mask=valid_mask(np.array([0,1],dtype=np.int8),"synthetic-numeric")
 assert numeric_mask.tolist() == [False,True]
 for bad,label in ((np.array([0.0,np.nan]),"nonfinite"),
                   (np.array([0,2]),"unexpected"),
                   (np.array(["0","1"]), "string")):
  try:
   valid_mask(bad,"synthetic-"+label)
  except SyntheticAuditError:
   pass
  else:
   raise AssertionError(f"{label} valid mask was accepted")
 small_type={0:2,1:0,2:1,3:1}
 assert normalize(np.array([0,0,2,3],dtype=np.int64),"synthetic-valid",small_type)==small_type
 try:
  normalize(np.array([0,0,2,3,4],dtype=np.int64),"synthetic-unexpected",small_type)
 except SyntheticAuditError:
  pass
 else:
  raise AssertionError("unexpected type code was accepted")
 try:
  normalize(np.array([0,0,2],dtype=np.int64),"synthetic-missing-fluid",small_type)
 except SyntheticAuditError:
  pass
 else:
  raise AssertionError("missing nonzero fluid code was accepted")
 small_mk={30:2,1:1,60:1}
 assert all(v>0 for v in small_mk.values())
 try:
  normalize(np.array([30,30,1],dtype=np.int64),"synthetic-missing-mk",small_mk)
 except SyntheticAuditError:
  pass
 else:
  raise AssertionError("missing nonzero Mk code was accepted")
 idx=load(PKG/"metadata/root607-typed-snapshot.json"); actual=future=0; seen=set()
 for p in qs:
  d=load(p); c=d["case_id"]; seen.add(c); assert d["schema"]==SCHEMA and d["adapter_fresh_id"]=="fresh099"
  assert d["disabled"] is True and d["execution_allowed"] is False and d["case_count"]==1
  assert d["binding_sha256"]==sha(d["binding"]) and d["worker_sha256"]==sha(WORKER)
  assert d["worker_cli"]==d["command"] and d["worker_cli"][0]=="python3"
  s=d["case"]["state0_dependency"]; assert s["status"]=="actual_pass" and s["checks_all_pass"] is True
  assert s["provenance_status"] in {"actual_root582_state0_pass","actual_root595_state0_pass"}
  if s["provenance_status"]=="actual_root595_state0_pass": assert "root582" not in json.dumps(s).lower()
  td=d["case"]["typed_terminal_dependency"]; assert td["trajectory_h5_sha256"] is None
  if td["status"]=="actual_root607_completed0":
   actual+=1; assert isinstance(td["conversion_report_sha256"],str) and isinstance(td["execution_receipt_sha256"],str) and isinstance(td["producer_physical_condition_sha256"],str)
  else:
   future+=1; assert td["status"]=="future_root607_completed0_required"; assert td["conversion_report_sha256"] is None and td["execution_receipt_sha256"] is None and td["producer_physical_condition_sha256"] is None
  assert d["future_hashes_null"] is True and all(v is None for v in d["future_input_sha256"].values())
  for q in d["input_files"]:
   assert not q.lower().endswith(FORBIDDEN),q; assert Path(q).is_file(),q; assert d["input_sha256"][q]==sha(q),q
 assert seen==set(idx["completed_case_ids"])|set(idx["future_case_ids"])
 assert actual==idx["completed_root607_count"] and future==idx["future_root607_count"] and actual+future==24
 st=load(PKG/"metadata/state0-provenance-summary.json"); assert st["root582_actual_pass_count"]==22 and st["root595_actual_pass_count"]==2
 print(json.dumps({"status":"pass","requests":24,"completed_root607":actual,"future_root607":future,"worker":"fresh099","synthetic_count_contract":"pass","synthetic_valid_mask_contract":"pass"},sort_keys=True))
if __name__=="__main__": main()
