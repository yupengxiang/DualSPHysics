from pathlib import Path
import hashlib,json,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
EXPECTED={"S050":(0.50,(.04,.06,.03)),"S075":(.75,(.06,.09,.045)),"S125":(1.25,(.10,.15,.075)),"S150":(1.50,(.12,.18,.09)),"S175":(1.75,(.14,.21,.105))}
def h(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 m=Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/prospective_angular_release_001/cases/coarse/F6_ANGULAR_RELEASE_DP025_Def.xml")
 old=m.read_text().splitlines(True)
 for s,(scale,w) in EXPECTED.items():
  c="F6_STAGE1_ANGULAR_RELEASE_OMEGA_"+s+"_DP025"; p=ROOT/"source"/(c+"_Def.xml")
  assert [i for i,(a,b) in enumerate(zip(old,p.read_text().splitlines(True)),1) if a!=b]==[64]
  x=ET.parse(p).getroot().find(".//casedef/floatings/floating/angularvelini"); assert tuple(float(x.get(a)) for a in "xyz")==w
  assert json.loads((ROOT/"metadata"/(c+".json")).read_text())["source_definition_sha256"]==h(p)
 for p in (ROOT/"gencase/requests").glob("*.json"): assert json.loads(p.read_text())["launch"] is False
 for p in (ROOT/"qualification/requests").glob("*.json"):
  x=json.loads(p.read_text()); assert x["launch"] is False and x["command"][-2:]==["-tmax:12","-tout:0.05"]
 q=json.loads((ROOT/"qa/initial-native-qa-request.json").read_text()); assert q["launch"] is False
 print("fresh069 source contract: PASS")
if __name__=="__main__": main()
