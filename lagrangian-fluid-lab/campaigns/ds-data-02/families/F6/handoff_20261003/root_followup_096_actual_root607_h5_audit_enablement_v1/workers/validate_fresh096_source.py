#!/usr/bin/env python3
from __future__ import annotations
import ast,hashlib,json
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]; REQ=PKG/"requests"; WORKER=PKG/"workers"/"audit_f6_typed_h5_full241_fresh096.py"
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
 assert 'SCHEMA = "ds02.f6.fresh096.typed-h5-full241-audit-result.v1"' in t
 assert "conversion_report.lifecycle.frame_summary" in t and "PRODUCER_TIME_MATCH_TOLERANCE_S = 1.0e-12" in t
 assert "nominal_schedule_is_report_only" in t and "TIME_TOLERANCE_S" not in t
 ast.parse(t)
 idx=load(PKG/"metadata/root607-typed-snapshot.json"); actual=future=0; seen=set()
 for p in qs:
  d=load(p); c=d["case_id"]; seen.add(c); assert d["schema"]==SCHEMA and d["adapter_fresh_id"]=="fresh096"
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
 print(json.dumps({"status":"pass","requests":24,"completed_root607":actual,"future_root607":future,"worker":"fresh096"},sort_keys=True))
if __name__=="__main__": main()
