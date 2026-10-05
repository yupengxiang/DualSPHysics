#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path
SKIP=(".bi4",".h5",".csv",".dat","Run.out","Part_")
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""): h.update(b)
 return h.hexdigest()
def j(p): return json.loads(p.read_text(encoding="utf-8"))
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,default=Path(__file__).resolve().parents[1]); a=ap.parse_args(); pkg=a.package.resolve()
 req=sorted((pkg/"typed/requests").glob("*.json")); errors=[]; cases=[]
 for p in req:
  q=j(p); c=q.get("case_id"); cases.append(c); fo=q.get("future_outputs",{})
  if (q.get("fresh_id"),q.get("disabled"),q.get("execution_allowed"),q.get("launch_allowed"))!=("fresh098",True,False,False): errors.append(f"{c}:disabled contract")
  if any(fo.get(k) is not None for k in ("conversion_report_sha256","execution_receipt_sha256","trajectory_h5_sha256","typed_partvtk_sha256")): errors.append(f"{c}:future hash")
  if set(q.get("input_files",[]))!=set(q.get("input_sha256",{})): errors.append(f"{c}:input closure set")
  bp=Path(q["binding"]); op=Path(q["owner_metadata"])
  if not bp.exists() or not op.exists(): errors.append(f"{c}:package owner/binding missing"); continue
  if sha(bp)!=q["binding_sha256"] or sha(op)!=q["owner_metadata_sha256"]: errors.append(f"{c}:package sha")
  b=j(bp); o=j(op)
  if b.get("fresh_id")!="fresh098" or o.get("fresh_id")!="fresh098": errors.append(f"{c}:fresh id")
  if b.get("actual_native_receipt_status")!="completed/0": errors.append(f"{c}:native status")
  f=b.get("actual_native_frame0_qa",{})
  if f.get("status")!="completed/0" or f.get("case_passed") is not True: errors.append(f"{c}:frame0 status")
  try:
   if j(Path(b["actual_gencase_receipt"])).get("returncode")!=0: errors.append(f"{c}:GenCase status")
   if j(Path(b["actual_native_receipt"])).get("returncode")!=0: errors.append(f"{c}:native status")
   if j(Path(f["report"]))["cases"][0].get("passed") is not True: errors.append(f"{c}:report")
   if sha(Path(f["receipt"]))!=f["receipt_sha256"] or sha(Path(f["report"]))!=f["report_sha256"]: errors.append(f"{c}:actual QA sha")
  except Exception as e: errors.append(f"{c}:metadata {e}")
  if q.get("raw_scientific_arrays_read_by_builder") is not False: errors.append(f"{c}:array marker")
 if len(req)!=24 or len(set(cases))!=24: errors.append("case cardinality")
 out={"schema":"ds02.f1.fresh098.metadata-verification.v1","case_count":len(req),"unique_case_count":len(set(cases)),"passed":not errors,"errors":errors,"scientific_payload_read":False}
 (pkg/"metadata/metadata-verification.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8"); print(json.dumps(out,indent=2,sort_keys=True)); return 0 if not errors else 1
if __name__=="__main__": raise SystemExit(main())
