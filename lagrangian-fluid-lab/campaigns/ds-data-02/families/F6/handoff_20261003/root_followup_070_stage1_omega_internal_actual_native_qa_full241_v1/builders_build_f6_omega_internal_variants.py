#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re
import xml.etree.ElementTree as ET
from pathlib import Path
MOTHER = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/prospective_angular_release_001/cases/coarse/F6_ANGULAR_RELEASE_DP025_Def.xml")
MOTHER_SHA = "9a052a620be27668ca5b8f42b0b91f2280a5b85588a94ccf845fb46905d258ba"
VARIANTS = (("S050",.50,(.04,.06,.03)),("S075",.75,(.06,.09,.045)),("S125",1.25,(.10,.15,.075)),("S150",1.50,(.12,.18,.09)),("S175",1.75,(.14,.21,.105)))
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""): h.update(b)
 return h.hexdigest()
def dump(p,x):
 p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n")
def main():
 a=argparse.ArgumentParser(); a.add_argument("--package-root",type=Path,required=True); root=a.parse_args().package_root
 if sha(MOTHER)!=MOTHER_SHA: raise SystemExit("mother hash mismatch")
 text=MOTHER.read_text(); tree=ET.fromstring(text)
 if tree.find(".//geometry/definition").get("dp")!="0.025" or tree.find(".//execution/parameters/parameter[@key='TimeMax']").get("value")!="12" or tree.find(".//execution/parameters/parameter[@key='TimeOut']").get("value")!="0.05": raise SystemExit("mother recipe mismatch")
 old=text.splitlines(True); records=[]
 for suf,scale,omega in VARIANTS:
  vals=[f"{v:g}" for v in omega]
  repl=f'                <angularvelini x="{vals[0]}" y="{vals[1]}" z="{vals[2]}" units_comment="rad/s; finite 3D angular release excitation" />\n'
  out,n=re.subn(r'(?m)^                <angularvelini x="0\.08" y="0\.12" z="0\.06" units_comment="rad/s; finite 3D angular release excitation" />\n',repl,text)
  if n!=1 or [i for i,(x,y) in enumerate(zip(old,out.splitlines(True)),1) if x!=y]!=[64]: raise SystemExit("source edit is not line 64")
  p=root/"source"/("F6_STAGE1_ANGULAR_RELEASE_OMEGA_"+suf+"_DP025_Def.xml"); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(out)
  records.append({"case_id":p.stem[:-4],"scale":scale,"omega_rad_s":list(omega),"source_definition":str(p),"source_definition_sha256":sha(p),"changed_source_line_numbers":[64]})
 dump(root/"source-build-receipt.json",{"schema":"ds02.f6.omega-internal-source-builder-receipt.v1","status":"source_built_only","mother_source":str(MOTHER),"mother_source_sha256":MOTHER_SHA,"mother_scale_verified":1.0,"mother_angular_velocity_rad_s":[.08,.12,.06],"variants":records,"launch_allowed":False,"execution_policy":{"gencase":False,"solver":False,"partvtk":False,"floatinginfo":False,"bi4":False,"h5":False,"csv_arrays":False}})
if __name__=="__main__": main()
