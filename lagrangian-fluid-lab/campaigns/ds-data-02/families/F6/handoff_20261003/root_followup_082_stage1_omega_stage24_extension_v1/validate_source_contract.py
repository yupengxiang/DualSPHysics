#!/usr/bin/env python3
"""Fail-closed metadata/XML checks for fresh082; never reads scientific arrays."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import xml.etree.ElementTree as ET
EXPECTED=[0.35,0.45,0.55,0.65,0.70,0.80,0.85,0.95]
def sha(p):
 h=hashlib.sha256();
 with Path(p).open("rb") as f:
  for block in iter(lambda: f.read(1024 * 1024), b''):
   h.update(block)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def digest(v): return hashlib.sha256(canon(v).encode()).hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--package",type=Path,default=Path(__file__).resolve().parent); a=ap.parse_args(); pkg=a.package.resolve(); errors=[]
 def ok(c,m):
  if not c: errors.append(m)
 plan=load(pkg/"metadata/stage24-omega-plan.json"); rows=plan["proposed_rows"]; ok([round(float(r["scale"]),2) for r in rows]==EXPECTED,"dedup/proposed scales"); ok(len({r["case_id"] for r in rows})==8,"unique case IDs")
 for r in rows:
  cid=r["case_id"]; src=Path(r["source_definition"]); owner=Path(r["canonical_owner"]);
  try:
   root=ET.parse(src).getroot(); ang=root.find(".//casedef/floatings/floating/angularvelini"); cen=root.find(".//casedef/floatings/floating/center"); mass=root.find(".//casedef/floatings/floating/massbody"); tm=root.find('.//execution/parameters/parameter[@key="TimeMax"]'); to=root.find('.//execution/parameters/parameter[@key="TimeOut"]')
   ok(ang is not None and [float(ang.get(k)) for k in "xyz"]==[float(x) for x in r["omega_rad_s"]],f"{cid}: XML omega"); ok(cen is not None and [float(cen.get(k)) for k in "xyz"]==[2.4,1.2,1.08],f"{cid}: center"); ok(mass is not None and float(mass.get("value"))==128.0,f"{cid}: physical mass"); ok(tm is not None and tm.get("value")=="12" and to is not None and to.get("value")=="0.05",f"{cid}: time recipe")
  except Exception as exc: errors.append(f"{cid}: XML {exc}")
  try:
   od=load(owner); pb=od["physical_binding"]; ok(od["physical_condition_sha256"]==digest(pb),f"{cid}: physical hash"); ok(pb["parameters"]["initial_angular_velocity_rad_s"]==r["omega_rad_s"],f"{cid}: owner omega"); ok(od["source_definition_sha256"]==r["source_definition_sha256"],f"{cid}: source hash"); ok(od["source_plan_condition_sha256"]==r["source_plan_condition_sha256"],f"{cid}: plan condition hash"); ok(r["canonical_owner_sha256"]==sha(owner),f"{cid}: owner file hash"); ok(od["expected_native"]["total"]==417505 and od["expected_native"]["fluid"]==327680 and od["expected_native"]["floating"]==16384,f"{cid}: counts"); ok(od["expected_native"]["physical_mass_kg"]==128.0 and od["expected_native"]["native_support_mass_kg"]==256.0,f"{cid}: mass semantics")
  except Exception as exc: errors.append(f"{cid}: owner {exc}")
 for pattern in ("gencase/requests/*.json","qualification/requests/*.json","qa/requests/*.json"):
  for p in sorted(pkg.glob(pattern)):
   try:
    d=load(p); ok(d.get("launch") is False and d.get("launch_allowed") is False and d.get("execution_allowed") is False and d.get("disabled") is True,f"{p}: request enabled"); ok(set(d.get("input_files",[]))==set(d.get("input_sha256",{})),f"{p}: static closure"); ok(set(d.get("future_input_files",[]))==set(d.get("future_input_sha256",{})),f"{p}: future closure"); ok(all(v is None for v in d.get("future_input_sha256",{}).values()),f"{p}: future hash fabricated")
    for value in d.get("future_outputs",{}).values():
     if isinstance(value,dict): ok(value.get("sha256") is None,f"{p}: future output hash")
    for f in d.get("input_files",[]): ok(Path(f).suffix.lower() not in {".bi4",".h5",".csv",".ibi4"},f"{p}: source reads scientific payload {f}")
   except Exception as exc: errors.append(f"{p}: request {exc}")
 report={"schema":"ds02.f6.fresh082.source-validation.v1","fresh_id":"fresh082","package":str(pkg),"pass":not errors,"errors":errors,"existing_unique_omega_count":16,"new_proposed_count":8,"projected_omega_grid_count":24,"stage24_target":24,"checks":["metadata-only dedup registry","XML-only omega/center/mass/time contract","canonical physical hash","source-plan/canonical separation","all requests disabled","static/future hash closure","future hashes null","128/256 kg mass distinction","no scientific array read"],"read_policy":"No BI4/H5/CSV/IBI4 scientific arrays opened or hashed by source validator.","claim_boundary":"Source contract only; no actual GenCase/native/QA/qualification result, state0, typed, XMF/render, Q-N, precision, production or acceptance claim."}
 (pkg/"source-validation-report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8"); print(json.dumps(report,indent=2,sort_keys=True)); return 0 if not errors else 1
if __name__=="__main__": raise SystemExit(main())
