#!/usr/bin/env python3
"""Root-only fresh070 motion source preparation; no GenCase or solver."""
from __future__ import annotations
import argparse, copy, hashlib, importlib.util, json, xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
SCHEMA = "ds02.f7.target-angle-source-preparation.v1"
def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""): h.update(block)
    return h.hexdigest()
def load(path: Path):
    v=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise ValueError(f"JSON object required: {path}")
    return v
def write(path: Path, value: Any):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def import_motion(path: Path):
    spec=importlib.util.spec_from_file_location("f7_fresh070_motion",path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot import {path}")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
def canonical_without_motion(root):
    clone=copy.deepcopy(root); motion=clone.find("casedef/motion")
    if motion is None: raise ValueError("source Definition lacks casedef/motion")
    motion.clear(); return ET.tostring(clone,encoding="utf-8")
def prepare(plan_path: Path, output_root: Path, execute: bool):
    plan=load(plan_path)
    if plan.get("launch_allowed") is not False or plan.get("source_only") is not True: raise RuntimeError("fresh070 plan must stay disabled source-only")
    if not execute: raise RuntimeError("Root must explicitly pass --execute")
    module_path=Path(plan["selected_motion_module"])
    if sha256(module_path)!=plan["selected_motion_module_sha256"]: raise RuntimeError("motion module hash mismatch")
    template=Path(plan["source_motion_template"])
    if sha256(template)!=plan["source_motion_template_sha256"]: raise RuntimeError("motion template hash mismatch")
    mother=Path(plan["source_definition"])
    if sha256(mother)!=plan["source_definition_sha256"]: raise RuntimeError("mother Definition hash mismatch")
    motion=import_motion(module_path); output_root.mkdir(parents=True,exist_ok=False)
    rows=[]
    expected=plan["fixed_physical_and_numerical_source"]["native_source_particle_counts"]
    for ep in plan["endpoints"]:
        case=str(ep["endpoint_id"]); source=(plan_path.parent/ep["source_definition_clone"]).resolve()
        if sha256(source)!=ep["source_definition_clone_sha256"]: raise RuntimeError(f"source Definition hash mismatch: {case}")
        tree=ET.parse(source).getroot(); definition=tree.find("casedef/geometry/definition")
        params={str(n.get("key")):str(n.get("value")) for n in tree.findall("execution/parameters/parameter")}
        if definition is None or definition.get("dp")!="0.02" or params.get("TimeMax")!="12" or params.get("TimeOut")!="0.02": raise RuntimeError(f"source recipe changed: {case}")
        obj=tree.find("casedef/motion/objreal[@ref='2']/mvrotfile")
        if obj is None or obj.find("file") is None or obj.find("file").get("name")!="motion_obstacle_quintic.dat": raise RuntimeError(f"motion filename changed: {case}")
        if [obj.find("axisp1").get(k) for k in ("x","y","z")] != ["-0.04","0","0.05"] or [obj.find("axisp2").get(k) for k in ("x","y","z")] != ["-0.04","0","1.05"]: raise RuntimeError(f"pivot changed: {case}")
        root=output_root/case; root.mkdir()
        motion_path=root/"motion_obstacle_quintic.dat"; definition_path=root/f"{case}_Def.xml"
        content=motion.generate_motion_dat_content(float(ep["amplitude_deg"]),12.0,0.001)
        data=[line.split() for line in content.splitlines() if line and not line.startswith("#")]
        if len(data)!=12001 or data[0]!=["0","0"] or float(data[-1][0])!=12.0 or float(data[-1][1])!=0.0: raise RuntimeError(f"motion window/rows invalid: {case}")
        motion_sha=motion.write_motion_file_exclusive(motion_path,content)
        definition_path.write_text(motion.generate_smooth_c2_definition_xml(source,motion_path.name),encoding="utf-8")
        prepared=ET.parse(definition_path).getroot(); pm=prepared.find("casedef/motion/objreal[@ref='2']/mvrotfile")
        if pm is None or pm.find("file").get("name")!=motion_path.name: raise RuntimeError(f"prepared motion binding invalid: {case}")
        rows.append({"endpoint_id":case,"physical_case_id":case,"amplitude_deg":float(ep["amplitude_deg"]),"physical_condition_sha256":ep["physical_condition_sha256"],"source_definition":str(source),"source_definition_sha256":sha256(source),"prepared_definition":str(definition_path),"prepared_definition_sha256":sha256(definition_path),"motion_file":str(motion_path),"motion_file_sha256":motion_sha,"motion_rows":len(data),"native_reader":"piecewise_linear_absolute_angle_increment","native_sampled_regular":"not C2","geometry_policy":"motion subtree only; explicit wet geometry and execution recipe retained","mass_policy":"native wet-fluid 325.60001628 kg and continuum 320.1984 kg remain distinct; no rescale","forecast_native_counts":expected})
    write(output_root/"motion-source-preparation.json",{"schema":SCHEMA,"scope_id":plan["scope_id"],"source_plan":str(plan_path),"source_plan_sha256":sha256(plan_path),"endpoint_count":len(rows),"endpoints":rows,"binary_or_particle_outputs":[],"gencase":"not performed","native_qa":"not performed","solver":"forbidden","conversion":"forbidden","rendering":"forbidden","q_n_status":"not_assessed","precision_status":"not_accepted","production_approval":"none","launch_allowed":False})
def main():
    p=argparse.ArgumentParser(); p.add_argument("--plan",required=True,type=Path); p.add_argument("--output-root",required=True,type=Path); p.add_argument("--execute",action="store_true"); a=p.parse_args(); prepare(a.plan,a.output_root,a.execute)
if __name__=="__main__": main()
