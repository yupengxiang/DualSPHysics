#!/usr/bin/env python3
"""Metadata/XML-only fresh070 source contract preflight."""
from __future__ import annotations
import hashlib, json, re, xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def load(p): return json.loads(p.read_text())
def req(c,m):
 if not c: raise AssertionError(m)
def main():
 plan=load(ROOT/'metadata/first24-plan.json'); req(plan['launch_allowed'] is False,'plan enabled'); req(len(plan['endpoints'])==16,'new endpoint count'); req(plan['new_angles_deg']==[31,32,33,34,36,37,38,39,41,42,43,44,46,47,48,49],'angle list'); req(plan['registry_check']['collision_count']==0,'registry collision'); req(len(set(plan['first24_axis_values_deg']))==24,'first24 duplicate')
 for ep in plan['endpoints']:
  src=(ROOT/'metadata'/ep['source_definition_clone']).resolve(); req(src.is_file(),f'missing {src}'); req(sha(src)==ep['source_definition_clone_sha256'],f'source hash {src}'); root=ET.parse(src).getroot(); d=root.find('casedef/geometry/definition'); req(d is not None and d.get('dp')=='0.02','dp'); params={n.get('key'):n.get('value') for n in root.findall('execution/parameters/parameter')}; req(params.get('TimeMax')=='12' and params.get('TimeOut')=='0.02','time'); motion=root.find("casedef/motion/objreal[@ref='2']/mvrotfile"); req(motion is not None and motion.find('file').get('name')=='motion_obstacle_quintic.dat','motion'); req([motion.find('axisp1').get(k) for k in ('x','y','z')]==['-0.04','0','0.05'],'pivot p1'); req([motion.find('axisp2').get(k) for k in ('x','y','z')]==['-0.04','0','1.05'],'pivot p2'); owner=load(ROOT/'owners'/f"{ep['endpoint_id']}.owner.json"); req(owner['launch_allowed'] is False,'owner enabled'); req(owner['physical_condition_sha256']==ep['physical_condition_sha256'],'condition'); req(hashlib.sha256(json.dumps(owner['physical_binding'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()==owner['canonical_physical_binding_sha256'],'canonical owner hash')
 for p in (ROOT/'requests').rglob('*.json'):
  d=load(p); req(d.get('launch_allowed') is False and d.get('launch') is False,'request enabled: '+str(p)); text=p.read_text(); req(not any(x in text.lower() for x in ('resource-ledger.json','ledger.json') if x in text.lower()),'live ledger bound: '+str(p)); req(d.get('strict_dispatch_sha256') in (None,'81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec'),'strict dispatch hash')
 print(json.dumps({'status':'pass','schema':'ds02.f7.fresh070.source-contract.v1','new_angles':plan['new_angles_deg'],'first24_count':24,'arrays_opened':False,'jobs_started':False,'shared_writes':False},indent=2))
if __name__=='__main__': main()
