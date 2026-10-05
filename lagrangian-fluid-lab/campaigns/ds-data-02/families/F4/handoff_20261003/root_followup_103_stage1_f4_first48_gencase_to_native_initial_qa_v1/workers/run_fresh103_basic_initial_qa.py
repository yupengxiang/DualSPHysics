#!/usr/bin/env python3
"""Materialize a fresh103 template from actual GenCase metadata, then reuse fresh095."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, shutil
from pathlib import Path
import xml.etree.ElementTree as ET
HEX=set("0123456789abcdef")

def load(p):
    v=json.loads(Path(p).read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise RuntimeError(f"metadata object required: {p}")
    return v

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def valid(v): return isinstance(v,str) and len(v)==64 and set(v.lower())<=HEX

def first_int(items, label):
    for v in items:
        if v is not None:
            try:
                n=int(v)
            except (TypeError,ValueError):
                continue
            if n>0: return n
    raise RuntimeError(f"actual {label} is missing from registered metadata")

def counts(report, receipt):
    blocks=report.get("generated_xml_particle_counts") or report.get("particle_counts") or {}
    total=first_int([report.get("actual_total_particles"), report.get("total_particles"), blocks.get("total"), blocks.get("np"), receipt.get("total_particles")],"total_particles")
    fixed=first_int([blocks.get("fixed"), blocks.get("nb"), report.get("fixed_particles"), receipt.get("fixed_particles")],"fixed_particles")
    fluid=first_int([blocks.get("fluid"), blocks.get("nfluid"), report.get("fluid_particles"), receipt.get("fluid_particles")],"fluid_particles")
    moving=int(blocks.get("moving", report.get("moving_particles", receipt.get("moving_particles", 0))) or 0)
    floating=int(blocks.get("floating", report.get("floating_particles", receipt.get("floating_particles", 0))) or 0)
    if total != fixed+fluid+moving+floating: raise RuntimeError("actual GenCase counts do not close")
    return {"total":total,"fixed":fixed,"fluid":fluid,"moving":moving,"floating":floating}

def bi4_producer(report, receipt):
    candidates=[]
    for d in (report,receipt):
        for key in ("generated_bi4_sha256","bi4_sha256","producer_sha256"):
            candidates.append(d.get(key))
        for key in ("generated_bi4","bi4"):
            x=d.get(key)
            if isinstance(x,dict): candidates.append(x.get("producer_sha256") or x.get("sha256"))
    for x in candidates:
        if valid(x): return x
    raise RuntimeError("GenCase BI4 producer attestation missing; wrapper never hashes BI4")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--binding",required=True,type=Path); ap.add_argument("--output",required=True,type=Path); a=ap.parse_args()
    template=load(a.binding)
    if template.get("schema")!="ds02.f4.fresh103.gencase-basic-input-binding.v1": raise RuntimeError("fresh103 binding schema mismatch")
    g=template["gencase"]
    receipt_path=Path(g["receipt"]["path"]); report_path=Path(g["prepared_report"]["path"]); xml_path=Path(g["generated_xml"]["path"])
    receipt=load(receipt_path); report=load(report_path)
    if receipt.get("status") not in {"completed","completed/0"} or receipt.get("returncode")!=0: raise RuntimeError("GenCase receipt is not completed/0")
    if receipt.get("solver_dimension_from_gencase") not in {3,"3"}: raise RuntimeError("GenCase receipt is not 3-D")
    c=counts(report,receipt)
    xml_root=ET.parse(xml_path).getroot(); d2=xml_root.find(".//execution/constants/data2d")
    if d2 is None: d2=xml_root.find(".//data2d")
    if d2 is None or str(d2.attrib.get("value","")).lower()!="false": raise RuntimeError("generated XML is not explicit 3-D")
    runtime=json.loads(json.dumps(template))
    runtime["expected"].update({"total_particles":c["total"],"fixed_particles":c["fixed"],"fluid_particles":c["fluid"],"moving_particles":c["moving"],"floating_particles":c["floating"]})
    runtime["gencase"]["receipt"].update({"sha256":sha(receipt_path),"status":receipt.get("status"),"returncode":receipt.get("returncode")})
    runtime["gencase"]["prepared_report"]["sha256"]=sha(report_path)
    runtime["gencase"]["generated_xml"]["sha256"]=sha(xml_path)
    runtime["gencase"]["generated_bi4"]["producer_sha256"]=bi4_producer(report,receipt)
    runtime["materialized_from_actual_metadata"]=True
    resolved=a.output.parent/"resolved-fresh095-binding.json"; resolved.write_text(json.dumps(runtime,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    worker=Path(template["worker_contract"]["path"])
    spec=importlib.util.spec_from_file_location("fresh095_worker",worker); mod=importlib.util.module_from_spec(spec); assert spec.loader
    spec.loader.exec_module(mod)
    ns=argparse.Namespace(binding=resolved,output=a.output)
    raise SystemExit(mod.run(ns))
if __name__=="__main__": main()
