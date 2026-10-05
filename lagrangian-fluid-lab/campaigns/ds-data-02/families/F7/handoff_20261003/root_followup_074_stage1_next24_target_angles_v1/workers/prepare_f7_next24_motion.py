#!/usr/bin/env python3
"""Root-enabled motion preparation for F7 fresh074; no solver or GenCase."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = "ds02.f7.next24-target-angle-source-preparation.v1"
def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def dump(p,v): Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True,type=Path); ap.add_argument("--output-root",required=True,type=Path); ap.add_argument("--execute",action="store_true"); a=ap.parse_args()
    if not a.execute: raise SystemExit("Root must explicitly enable motion preparation")
    plan=load(a.plan); assert plan["launch_allowed"] is False and plan["source_only"] is True
    mp=Path(plan["selected_motion_module"]); assert sha(mp)==plan["selected_motion_module_sha256"]
    spec=importlib.util.spec_from_file_location("f7_next24_motion",mp); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    out=a.output_root; out.mkdir(parents=True,exist_ok=False); rows=[]
    for ep in plan["endpoints"]:
        case=ep["endpoint_id"]; src=Path(a.plan).parent/ep["source_definition_clone"]; assert sha(src)==ep["source_definition_clone_sha256"]
        tree=ET.parse(src).getroot(); d=tree.find("casedef/geometry/definition"); params={n.get("key"):n.get("value") for n in tree.findall("execution/parameters/parameter")}; mv=tree.find("casedef/motion/objreal[@ref='2']/mvrotfile")
        assert d is not None and d.get("dp")=="0.02" and params.get("TimeMax")=="12" and params.get("TimeOut")=="0.02" and mv is not None and mv.find("file").get("name")=="motion_obstacle_quintic.dat"
        assert [mv.find("axisp1").get(k) for k in ("x","y","z")] == ["-0.04","0","0.05"] and [mv.find("axisp2").get(k) for k in ("x","y","z")] == ["-0.04","0","1.05"]
        case_root=out/case; case_root.mkdir(); text=mod.generate_motion_dat_content(float(ep["amplitude_deg"]),12.0,0.001); rows_raw=[x.split() for x in text.splitlines() if x and not x.startswith("#")]; assert len(rows_raw)==12001 and rows_raw[0]==["0","0"] and float(rows_raw[-1][0])==12.0 and float(rows_raw[-1][1])==0.0
        motion=case_root/"motion_obstacle_quintic.dat"; msha=mod.write_motion_file_exclusive(motion,text); definition=case_root/f"{case}_Def.xml"; definition.write_text(mod.generate_smooth_c2_definition_xml(src,motion.name),encoding="utf-8")
        rows.append({"endpoint_id":case,"physical_case_id":case,"amplitude_deg":ep["amplitude_deg"],"source_definition":str(src),"source_definition_sha256":sha(src),"prepared_definition":str(definition),"prepared_definition_sha256":sha(definition),"motion_file":str(motion),"motion_file_sha256":msha,"motion_rows":len(rows_raw),"native_reader":"piecewise_linear_absolute_angle_increment","native_sampled_regular":"not C2","future_gencase_receipt_sha256":None})
    dump(out/"motion-source-preparation.json",{"schema":SCHEMA,"scope_id":plan["scope_id"],"source_plan":str(a.plan),"source_plan_sha256":sha(a.plan),"endpoint_count":len(rows),"endpoints":rows,"gencase":"not performed","native_qa":"not performed","solver":"forbidden","conversion":"forbidden","rendering":"forbidden","launch_allowed":False,"future_hashes_null":False})
if __name__=="__main__": main()
