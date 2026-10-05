#!/usr/bin/env python3
from __future__ import annotations
import argparse, copy, hashlib, json, re
from pathlib import Path
import xml.etree.ElementTree as ET

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024), b''): h.update(block)
 return h.hexdigest()
def canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(v): return hashlib.sha256(canon(v).encode()).hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parent); a=ap.parse_args(); pkg=a.package.resolve(); plan=load(pkg/'metadata/stage24-omega-plan.json'); rows=plan['proposed_rows']; errors=[]
 def ok(c,m):
  if not c: errors.append(m)
 ok(len(rows)==8,'expected 8 proposed rows'); ok(len({r['scale'] for r in rows})==8,'duplicate proposed scales'); ok(all(.25<float(r['scale'])<2.0 for r in rows),'proposed scale outside endpoint range')
 expected=[0.25,.5,.75,1.0,1.25,1.5,1.75,2.0]
 ok(sorted(float(r['scale']) for r in plan['existing_unique_omega_registry'])==expected,'existing omega registry is not the eight confirmed values')
 for r in rows:
  cid=r['case_id']; src=Path(r['source_definition']); owner=Path(r['canonical_owner']);
  try:
   root=ET.parse(src).getroot(); ang=root.find('.//casedef/floatings/floating/angularvelini'); cen=root.find('.//casedef/floatings/floating/center'); mass=root.find('.//casedef/floatings/floating/massbody'); tm=root.find('.//execution/parameters/parameter[@key="TimeMax"]'); to=root.find('.//execution/parameters/parameter[@key="TimeOut"]')
   ok(ang is not None and [float(ang.get(k)) for k in 'xyz']==[float(x) for x in r['omega_rad_s']],f'{cid}: XML omega')
   ok(cen is not None and [float(cen.get(k)) for k in 'xyz']==[2.4,1.2,1.08],f'{cid}: XML center')
   ok(mass is not None and float(mass.get('value'))==128.0,f'{cid}: XML mass')
   ok(tm is not None and tm.get('value')=='12' and to is not None and to.get('value')=='0.05',f'{cid}: mother time recipe drift')
  except Exception as e: errors.append(f'{cid}: XML parse {e}')
  try:
   od=load(owner); pb=od['physical_binding']; ok(od['physical_condition_sha256']==digest(pb),f'{cid}: canonical hash mismatch'); ok(pb['parameters']['initial_angular_velocity_rad_s']==r['omega_rad_s'],f'{cid}: owner omega'); ok(od['source_definition_sha256']==r['source_definition_sha256'],f'{cid}: owner source hash'); ok(od['source_plan_condition_sha256']==r['source_plan_condition_sha256'],f'{cid}: owner plan hash'); ok(r['canonical_owner_sha256']==sha(owner),f'{cid}: plan owner hash');
   plan_base={k:r[k] for k in ('case_id','scale','slug','omega_rad_s','source_definition','source_definition_sha256','physical_condition_sha256')}
   plan_base.update({'time_window_s':[0.0,12.0],'save_interval_s':0.05,'expected_frames':241,'changed_source_paths':['casedef.floatings.floating.angularvelini.@x','casedef.floatings.floating.angularvelini.@y','casedef.floatings.floating.angularvelini.@z'],'forbidden_changes':['geometry','center','massbody','inertia','translationDOF','rotationDOF','initial fluid velocity','forcing','mdbc','solver recipe'],'mass_policy':{'physical_rigid_mass_kg':128.0,'native_support_mass_kg':256.0,'solver_interaction_masspart_kg':0.015625,'normalization':'none','equality_required':False},'expected_native':{'dimension':3,'fixed':73441,'moving':0,'floating':16384,'fluid':327680,'total':417505}})
   ok(r['source_plan_condition_sha256']==digest(plan_base),f'{cid}: source-plan hash semantics'); ok(od['expected_native']['total']==417505 and od['expected_native']['fluid']==327680 and od['expected_native']['floating']==16384,f'{cid}: count contract'); ok(od['expected_native']['physical_mass_kg']==128.0 and od['expected_native']['native_support_mass_kg']==256.0,f'{cid}: mass contract')
  except Exception as e: errors.append(f'{cid}: owner parse {e}')
 for pattern in ('gencase/requests/*.json','qualification/requests/*.json','typed/requests/*.json','xmf/requests/*.json','render/requests/*.json','qa/requests/*.json'):
  for p in sorted(pkg.glob(pattern)):
   try:
    d=load(p); ok(d.get('launch') is False and d.get('launch_allowed') is False and d.get('execution_allowed') is False and d.get('disabled') is True,f'{p}: enabled request'); ok(set(d.get('input_files',[]))==set(d.get('input_sha256',{})),f'{p}: static closure'); ok(set(d.get('future_input_files',[]))==set(d.get('future_input_sha256',{})),f'{p}: future closure'); ok(all(v is None for v in d.get('future_input_sha256',{}).values()),f'{p}: future input hash non-null');
    for k,v in d.get('future_outputs',{}).items():
     if isinstance(v,dict): ok(v.get('sha256') is None,f'{p}: future output {k} hash non-null')
   except Exception as e: errors.append(f'{p}: request parse {e}')
 report={'schema':'ds02.f6.fresh079.source-validation.v1','fresh_id':'fresh079','package':str(pkg),'pass':not errors,'errors':errors,'proposed_count':len(rows),'existing_unique_omega_count':8,'projected_omega_grid_count':16,'stage24_target':24,'checks':['XML-only omega/center/mass/DOF/time recipe','canonical physical binding hash','source-plan/canonical separation','all request disabled','static input hash closures','future input/output hashes null','128/256 kg mass distinction','no scientific array read'],'read_policy':'No BI4/H5/CSV/IBI4 scientific arrays opened or hashed by source validator.','claim_boundary':'Source contract only; no actual GenCase/native/QA/typed/XMF/render result, Q-N, precision or production claim.'}
 (pkg/'source-validation-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(report,indent=2,sort_keys=True)); return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(main())
