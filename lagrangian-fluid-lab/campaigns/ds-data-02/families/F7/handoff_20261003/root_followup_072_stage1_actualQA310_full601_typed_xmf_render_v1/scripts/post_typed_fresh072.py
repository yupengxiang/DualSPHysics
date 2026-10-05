#!/usr/bin/env python3
"""Metadata-only post-typed staging helper for fresh072.

It adopts producer JSON hashes and never opens trajectory.h5/BI4/CSV/motion bytes.
It writes enabled staging copies outside the immutable disabled source requests.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

RAW_SUFFIXES=(".bi4",".csv",".h5",".dat",".ibi4")

def sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def load(p): return json.loads(Path(p).read_text())
def dump(p,d):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,indent=2,sort_keys=True)+"\n")

def safe_inputs(paths, overrides=None):
    overrides=overrides or {}; out={}
    for s in paths:
        p=Path(s).resolve()
        if any(str(p).lower().endswith(x) for x in RAW_SUFFIXES) or "/solver_output/data/" in str(p):
            if str(p) not in overrides: raise SystemExit(f"raw source input forbidden: {p}")
            out[str(p)]=overrides[str(p)]
        else:
            out[str(p)]=overrides.get(str(p),sha(p))
    return out

def enable(req):
    req["launch"]=True; req["launch_allowed"]=True; req["execution_allowed"]=True; req["disabled"]=False
    req["source_only"]=False; req["future_hashes_null"]=False; req["status"]="root_enabled_pending_actual_execution"
    req["disabled_reason"]=None
    return req

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--package-root",type=Path,required=True)
    ap.add_argument("--case-id",required=True)
    ap.add_argument("--typed-receipt",type=Path,required=True)
    ap.add_argument("--conversion-report",type=Path,required=True)
    ap.add_argument("--trajectory-sha256",required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    a=ap.parse_args(); root=a.package_root.resolve(); case=a.case_id
    tr=load(a.typed_receipt); cr=load(a.conversion_report)
    if (tr.get("status"),tr.get("returncode"))!=("completed",0): raise SystemExit("typed receipt is not completed/0")
    if cr.get("conversion_status")!="completed": raise SystemExit("conversion report not completed")
    if cr.get("output_sha256")!=a.trajectory_sha256: raise SystemExit("producer H5 SHA does not match conversion report")
    bpath=root/"bindings"/f"{case}.full601-xmf-binding.json"; b=load(bpath)
    b["typed_receipt"]=str(a.typed_receipt.resolve()); b["typed_receipt_sha256"]=sha(a.typed_receipt)
    b["conversion_report"]=str(a.conversion_report.resolve()); b["conversion_report_sha256"]=sha(a.conversion_report)
    b["trajectory_h5"]=str(Path(cr.get("output_hdf5") or b["trajectory_h5"]).resolve()); b["trajectory_h5_sha256"]=a.trajectory_sha256
    b["producer_conversion_schema"]=cr.get("schema")
    b["producer_scope_schema"]=cr.get("hash_scopes",{}).get("physical_condition",{}).get("schema",b["producer_scope_schema"])
    out=Path(a.output_dir).resolve(); out.mkdir(parents=True,exist_ok=True)
    bout=out/f"{case}.full601-xmf-binding.json"; dump(bout,b)
    req=load(root/"requests/xmf"/f"{case}.full601-normal-xmf-072.disabled-request.json")
    req["command"][req["command"].index("--binding")+1]=str(bout)
    files=[str(Path(x).resolve()) for x in req["input_files"] if str(x)!=str(bpath)]
    files += [str(bout),str(a.typed_receipt.resolve()),str(a.conversion_report.resolve())]
    req["input_files"]=list(dict.fromkeys(files))
    req["input_sha256"]=safe_inputs(req["input_files"],{str(bout):sha(bout),str(Path(b["trajectory_h5"]).resolve()):a.trajectory_sha256})
    req["producer_scope_schema"]=b["producer_scope_schema"]; req["producer_conversion_schema"]=b["producer_conversion_schema"]
    req["typed_producer_bound"]=True; req=enable(req)
    xreq=out/f"{case}.full601-normal-xmf-072.enabled-request.json"; dump(xreq,req)
    print(json.dumps({"stage":"xmf","binding":str(bout),"request":str(xreq)}))
if __name__=="__main__": main()
