#!/usr/bin/env python3
"""Bind completed fresh070 motion metadata to Root003 GenCase bindings.
No BI4/CSV/H5/solver data are read here; Root runs this only after motion prep.
"""
from __future__ import annotations
import argparse, hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path

def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def load(p):
 v=json.loads(Path(p).read_text());
 if not isinstance(v,dict): raise ValueError(p)
 return v
def dump(p,v):
 Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+"\n")
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--plan',required=True,type=Path); ap.add_argument('--motion-report',required=True,type=Path); ap.add_argument('--motion-receipt',required=True,type=Path); ap.add_argument('--prepared-root',required=True,type=Path); ap.add_argument('--output-dir',required=True,type=Path); a=ap.parse_args()
 plan=load(a.plan); report=load(a.motion_report); receipt=load(a.motion_receipt)
 if report.get('schema')!='ds02.f7.target-angle-source-preparation.v1' or report.get('endpoint_count')!=16: raise RuntimeError('motion report schema/count mismatch')
 if receipt.get('status')!='completed' or receipt.get('returncode')!=0: raise RuntimeError('motion receipt not completed/0')
 byid={x['endpoint_id']:x for x in report['endpoints']};
 if set(byid)!={x['endpoint_id'] for x in plan['endpoints']}: raise RuntimeError('motion endpoints do not match plan')
 out=a.output_dir; out.mkdir(parents=True,exist_ok=False); gen=[]
 for ep in plan['endpoints']:
  case=ep['endpoint_id']; row=byid[case]; definition=Path(row['prepared_definition']); motion=Path(row['motion_file'])
  if not definition.is_file() or not motion.is_file(): raise FileNotFoundError(case)
  if sha(definition)!=row['prepared_definition_sha256'] or sha(motion)!=row['motion_file_sha256']: raise RuntimeError(f'prepared hash mismatch: {case}')
  tree=ET.parse(definition).getroot(); params={n.get('key'):n.get('value') for n in tree.findall('execution/parameters/parameter')}; d=tree.find('casedef/geometry/definition')
  if d is None or d.get('dp')!='0.02' or params.get('TimeMax')!='12' or params.get('TimeOut')!='0.02': raise RuntimeError(f'prepared recipe mismatch: {case}')
  binding={'schema':'ds02.f7.first24.root003-gencase-binding.v1','family_id':'F7','case_id':case,'physical_case_id':case,'physical_condition_sha256':ep['physical_condition_sha256'],'definition':str(definition),'definition_sha256':sha(definition),'gencase':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64','gencase_sha256':'a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226','threads':2,'dp_m':0.02,'expected_fluid':40700,'assets':[{'source':str(motion),'sha256':sha(motion),'relative_name':'motion_obstacle_quintic.dat'}],'predictions':{'fixed':27495,'moving':1984,'fluid':40700,'total':70179,'actual_counts_must_be_read_from_generated_xml':True,'forecast_only':True},'source_plan':str(a.plan),'source_plan_sha256':sha(a.plan),'motion_report':str(a.motion_report),'motion_report_sha256':sha(a.motion_report),'motion_receipt':str(a.motion_receipt),'motion_receipt_sha256':sha(a.motion_receipt),'launch_allowed':False,'execution_allowed':False,'arrays_read_by_binder':False}
  path=out/f'{case}.binding.json'; dump(path,binding); gen.append({'case_id':case,'binding':str(path),'binding_sha256':sha(path)})
 dump(out/'gencase-bindings.json',{'schema':'ds02.f7.first24.gencase-bindings.v1','scope_id':plan['scope_id'],'source_plan_sha256':sha(a.plan),'motion_report_sha256':sha(a.motion_report),'motion_receipt_sha256':sha(a.motion_receipt),'bindings':gen,'launch_allowed':False,'arrays_read_by_binder':False})
if __name__=='__main__': main()
