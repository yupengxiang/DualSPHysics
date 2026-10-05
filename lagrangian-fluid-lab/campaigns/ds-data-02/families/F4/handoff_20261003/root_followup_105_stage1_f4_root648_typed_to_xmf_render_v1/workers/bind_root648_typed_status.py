#!/usr/bin/env python3
"""Poll Root648 typed JSON metadata without reading trajectory/H5 payloads."""
import argparse,json
from pathlib import Path
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--requests-root",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); a=ap.parse_args()
    rows=[]
    for p in sorted(a.requests_root.glob("*-typed-request.json")):
        q=load(p); root=Path(q["attempt_root"]); rec=root/"execution-receipt.json"; report=root/"conversion-report.json"
        row={"case_id":q["case_id"],"request":str(p),"status":"WAIT","receipt":None,"conversion_report":None,"trajectory_h5_sha256":None}
        if rec.is_file():
            r=load(rec); row["receipt"]={"path":str(rec),"status":r.get("status"),"returncode":r.get("returncode")}
            if r.get("status")=="completed" and r.get("returncode")==0 and report.is_file():
                x=load(report); row["conversion_report"]={"path":str(report),"conversion_status":x.get("conversion_status"),"frames":x.get("frames"),"particles":x.get("particles"),"partvtk_validation":x.get("partvtk_validation")}
                if x.get("conversion_status")=="completed" and x.get("frames")==1201 and x.get("partvtk_validation",{}).get("all_passed") is True: row["status"]="completed/0_and_report_pass"
        rows.append(row)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps({"schema":"ds02.f4.root648.typed-status.v1","source_only":True,"rows":rows,"h5_read_or_hashed":False},indent=2)+chr(10)
    a.output.write_text(payload,encoding="utf-8")
if __name__=="__main__": main()
