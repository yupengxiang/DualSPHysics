#!/usr/bin/env python3
"""Materialize a fresh103 frame-0 template from actual metadata, then reuse fresh097."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json
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

def marker_map(template):
    # This is only the historical Root530 observation; the registered worker
    # still observes raw Mk and fails if the actual map/velocity rows disagree.
    m=template.get("historical_root530_marker_map") or {"mkfluid:0":"Mk:1","mkfluid:1":"Mk:2"}
    out={}
    for source,raw in m.items():
        if not isinstance(raw,str) or not raw.startswith("Mk:"): raise RuntimeError("invalid marker map")
        out["mk:"+raw.split(":",1)[1]]=template["declared_velocity_by_mkfluid"][source]
    return out

def actual_counts(report):
    audit=report.get("audit",{})
    root=audit.get("root_values",{})
    blocks=report.get("generated_xml_particle_counts") or report.get("particle_counts") or {}
    def pick(*vals):
        for v in vals:
            if v is not None:
                try: return int(v)
                except (TypeError,ValueError): pass
        raise RuntimeError("actual GenCase count missing in basic QA metadata")
    total=pick(root.get("CaseNp"),report.get("actual_total_particles"),blocks.get("total"))
    fixed=pick(root.get("CaseNfixed"),blocks.get("fixed"),report.get("fixed_particles"))
    fluid=pick(root.get("CaseNfluid"),blocks.get("fluid"),report.get("fluid_particles"))
    return {"fixed":fixed,"moving":int(blocks.get("moving",report.get("moving_particles",0)) or 0),"floating":int(blocks.get("floating",report.get("floating_particles",0)) or 0),"fluid":fluid},total

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--binding",required=True,type=Path); ap.add_argument("--output-dir",required=True,type=Path); a=ap.parse_args()
    template=load(a.binding)
    if template.get("schema")!="ds02.f4.fresh103.native-frame0-input-binding.v1": raise RuntimeError("fresh103 frame binding schema mismatch")
    case=template["cases"][0]; receipt_path=Path(case["native_solver_receipt"]); require=receipt_path.is_file()
    if not require: raise RuntimeError("native receipt missing")
    receipt=load(receipt_path)
    if receipt.get("status") not in {"completed","completed/0"} or receipt.get("returncode")!=0: raise RuntimeError("native receipt is not completed/0")
    report_path=Path(case["prepared_input_report"]); report=load(report_path)
    counts,total=actual_counts(report)
    xml_path=Path(case["generated_xml"]); xml_root=ET.parse(xml_path).getroot(); d2=xml_root.find(".//execution/constants/data2d")
    if d2 is None: d2=xml_root.find(".//data2d")
    if d2 is None or str(d2.attrib.get("value","")).lower()!="false": raise RuntimeError("generated XML is not explicit 3-D")
    runtime=json.loads(json.dumps(template)); rc=runtime["cases"][0]
    output_root=Path(receipt.get("output_root") or rc["native_output_root"]); data_root=output_root/"solver_output/data"
    rc["native_solver_status"]="completed/0"; rc["native_solver_receipt_sha256"]=sha(receipt_path); rc["native_output_root"]=str(output_root); rc["native_data_dir"]=str(data_root); rc["native_frame0_bi4"]=str(data_root/"Part_0000.bi4")
    rc["generated_xml_sha256"]=sha(xml_path); rc["gencase_receipt_sha256"]=sha(Path(rc["gencase_receipt"]))
    rc["actual_particle_counts"]=counts; rc["actual_total_particles"]=total; rc["expected_velocity_by_mk"]=marker_map(rc); rc["partvtk_sha256"]=None
    runtime["native_solver_status"]="completed/0"; runtime["future_report_sha256"]=None; runtime["materialized_from_actual_metadata"]=True
    resolved=a.output_dir/"resolved-fresh097-binding.json"; resolved.parent.mkdir(parents=True,exist_ok=True); resolved.write_text(json.dumps(runtime,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    worker=Path(template["worker_contract"]["path"])
    spec=importlib.util.spec_from_file_location("fresh097_worker",worker); mod=importlib.util.module_from_spec(spec); assert spec.loader
    spec.loader.exec_module(mod)
    ns=argparse.Namespace(binding=resolved,output_dir=a.output_dir)
    # Call the worker's public audit loop without reconstructing scientific parsing.
    results=[mod.audit(c,a.output_dir) for c in runtime["cases"]]
    out=a.output_dir/"native-frame0-partvtk-vz-audit.json"
    out.write_text(json.dumps({"schema":"ds02.f4.fresh103.native-frame0-partvtk-vz-audit.v1","source_only_worker":True,"native_frame0_source":"official PartVTK on solver-saved Part_0000.bi4","raw_mk_type_observed":True,"raw_velocity_observed":True,"gencase_raw_velocity_claim":"not_used","mass_rescaling":False,"cases":results,"q_n":"not_assessed","production_approval":"none","independent_case_count_increment":0},indent=2,sort_keys=True)+"\n",encoding="utf-8")
if __name__=="__main__": main()
