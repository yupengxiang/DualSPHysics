#!/usr/bin/env python3
"""Bind Root003 GenCase inputs after actual motion preparation; metadata only."""
from __future__ import annotations
import argparse, hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def dump(p,v): Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+"\n")
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--plan",required=True,type=Path); ap.add_argument("--motion-report",required=True,type=Path); ap.add_argument("--motion-receipt",required=True,type=Path); ap.add_argument("--prepared-root",required=True,type=Path); ap.add_argument("--output-dir",required=True,type=Path); a=ap.parse_args()
 plan=load(a.plan); report=load(a.motion_report); receipt=load(a.motion_receipt); assert report.get("schema")=="ds02.f7.next24-target-angle-source-preparation.v1" and report.get("endpoint_count")==24; assert receipt.get("status")=="completed" and receipt.get("returncode")==0
 byid={x["endpoint_id"]:x for x in report["endpoints"]}; assert set(byid)=={x["endpoint_id"] for x in plan["endpoints"]}; out=a.output_dir; out.mkdir(parents=True,exist_ok=False); entries=[]
 for ep in plan["endpoints"]:
  case=ep["endpoint_id"]; row=byid[case]; definition=Path(row["prepared_definition"]); motion=Path(row["motion_file"]); assert definition.is_file() and motion.is_file() and sha(definition)==row["prepared_definition_sha256"] and sha(motion)==row["motion_file_sha256"]
  tree=ET.parse(definition).getroot(); d=tree.find("casedef/geometry/definition"); params={n.get("key"):n.get("value") for n in tree.findall("execution/parameters/parameter")}; assert d is not None and d.get("dp")=="0.02" and params.get("TimeMax")=="12" and params.get("TimeOut")=="0.02"
  b={"schema":"ds02.f7.next24.root003-gencase-binding.v1","family_id":"F7","scope_id":plan["scope_id"],"case_id":case,"physical_case_id":case,"amplitude_deg":ep["amplitude_deg"],"physical_condition_sha256":ep["physical_condition_sha256"],"canonical_physical_binding_sha256":ep["canonical_physical_binding_sha256"],"definition":str(definition),"definition_sha256":sha(definition),"gencase":str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")),"gencase_sha256":"a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226","threads":2,"dp_m":0.02,"expected_fluid":40700,"assets":[{"source":str(motion),"sha256":sha(motion),"relative_name":"motion_obstacle_quintic.dat"}],"predictions":{"fixed":27495,"moving":1984,"floating":0,"fluid":40700,"total":70179,"actual_counts_must_be_read_from_generated_xml":True,"forecast_only":True},"source_plan":str(a.plan),"source_plan_sha256":sha(a.plan),"motion_report":str(a.motion_report),"motion_report_sha256":sha(a.motion_report),"motion_receipt":str(a.motion_receipt),"motion_receipt_sha256":sha(a.motion_receipt),"launch_allowed":False,"execution_allowed":False,"arrays_read_by_binder":False}
  bp=out/f"{case}.binding.json"; dump(bp,b); entries.append({"case_id":case,"binding":str(bp),"binding_sha256":sha(bp)})
 dump(out/"gencase-bindings.json",{"schema":"ds02.f7.next24.gencase-bindings.v1","scope_id":plan["scope_id"],"source_plan_sha256":sha(a.plan),"motion_report_sha256":sha(a.motion_report),"motion_receipt_sha256":sha(a.motion_receipt),"bindings":entries,"launch_allowed":False,"arrays_read_by_binder":False})
if __name__=="__main__": main()
