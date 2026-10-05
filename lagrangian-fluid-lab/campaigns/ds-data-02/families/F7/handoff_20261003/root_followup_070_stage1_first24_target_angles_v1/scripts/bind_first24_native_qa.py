#!/usr/bin/env python3
"""Bind actual Root003 GenCase JSON/XML/BI4 metadata for the fresh070 QA worker.
Run by Root after GenCase; no source-time array access is performed.
"""
from __future__ import annotations
import argparse, hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path

def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def dump(p,v): Path(p).parent.mkdir(parents=True,exist_ok=True); Path(p).write_text(json.dumps(v,indent=2,sort_keys=True)+"\n")
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--plan',required=True,type=Path); ap.add_argument('--gencase-bindings',required=True,type=Path); ap.add_argument('--output-dir',required=True,type=Path); a=ap.parse_args()
 plan=load(a.plan); group=load(a.gencase_bindings)
 if group.get('schema')!='ds02.f7.first24.gencase-bindings.v1' or len(group.get('bindings',[]))!=16: raise RuntimeError('gencase binding group mismatch')
 byid={x['case_id']:x for x in plan['endpoints']}; cases=[]
 for entry in group['bindings']:
  b=load(entry['binding']); case=b['case_id'];
  if case not in byid or b.get('launch_allowed') is not False: raise RuntimeError(f'bad binding: {case}')
  receipt=Path(b['gencase_receipt']) if b.get('gencase_receipt') else None
  # Root003 runtime places a per-case receipt at the deterministic case root.
  raw=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7')/case
  attempt=raw/f'root-stage1-f7-{case.lower()}-genuine-gencase-070'
  receipt=attempt/'execution-receipt.json'; folder=attempt/'prepared'/case
  xml=folder/f'{case}.xml'; bi4=folder/f'{case}.bi4'; report=folder/'prepared-input-report.json'
  for p in (receipt,xml,bi4,report):
   if not p.is_file(): raise FileNotFoundError(f'{case}: {p}')
  rec=load(receipt)
  if rec.get('status')!='completed' or rec.get('returncode')!=0: raise RuntimeError(f'{case}: GenCase not completed/0')
  tree=ET.parse(xml).getroot(); particles=tree.find('./execution/particles'); constants=tree.find('./execution/constants'); definition=tree.find('./casedef/geometry/definition')
  if particles is None or constants is None or definition is None: raise RuntimeError(f'{case}: XML sections missing')
  data2d=constants.find('data2d'); params={n.get('key'):n.get('value') for n in tree.findall('./execution/parameters/parameter')}
  counts={}
  for name in ('fixed','moving','floating','fluid'):
   counts[name]=sum(int(n.get('count')) for n in particles.findall(name))
  if data2d is None or data2d.get('value')!='false' or definition.get('dp')!='0.02' or params.get('TimeMax')!='12' or params.get('TimeOut')!='0.02': raise RuntimeError(f'{case}: generated XML recipe/dimension mismatch')
  expected={'fixed':27495,'moving':1984,'floating':0,'fluid':40700}
  if counts!=expected or int(particles.get('np'))!=70179: raise RuntimeError(f'{case}: actual XML counts {counts} do not match forecast {expected}; preserve actual failure')
  cases.append({'case_id':case,'physical_case_id':case,'amplitude_deg':byid[case]['amplitude_deg'],'physical_condition_sha256':byid[case]['physical_condition_sha256'],'gencase_receipt':str(receipt),'gencase_receipt_sha256':sha(receipt),'prepared_input_report':str(report),'prepared_input_report_sha256':sha(report),'generated_xml':str(xml),'generated_xml_sha256':sha(xml),'generated_bi4':str(bi4),'generated_bi4_sha256':sha(bi4),'generated_definition':b.get('definition'),'generated_definition_sha256':b.get('definition_sha256'),'generated_motion':b['assets'][0]['source'],'generated_motion_sha256':b['assets'][0]['sha256'],'source_definition':str((Path(a.plan).parent/byid[case]['source_definition_clone']).resolve()),'source_definition_sha256':byid[case]['source_definition_clone_sha256'],'prepared_definition':b['definition'],'prepared_definition_sha256':b['definition_sha256'],'expected':{'total_particles':70179,'fixed_particles':27495,'moving_particles':1984,'fluid_particles':40700,'solver_dimension':3,'dp_m':0.02,'time_max_s':12.0,'time_out_s':0.02,'motion_rows':12001,'type_mk_blocks':[{'name':'fixed','begin':0,'count':27495,'type':0,'mk':10},{'name':'moving','begin':27495,'count':1984,'type':1,'mk':12},{'name':'fluid','begin':29479,'count':40700,'type':3,'mk':2}],'velocity_zero_tolerance_m_per_s':1e-12,'native_fluid_mass_kg':325.60001628,'continuum_envelope_mass_kg':320.1984,'mass_tolerance_kg':1e-8}})
 out=a.output_dir; out.mkdir(parents=True,exist_ok=False)
 dump(out/'binding.json',{'schema':'ds02.f7.first24.actual-gencase-native-qa-binding.v1','scope_id':plan['scope_id'],'partvtk':'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64','partvtk_sha256':'62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00','source_plan':{'source_absolute_path':str(a.plan),'source_sha256':sha(a.plan)},'gencase_binding_group':{'source_absolute_path':str(a.gencase_bindings),'source_sha256':sha(a.gencase_bindings)},'cases':cases,'launch_allowed':False,'arrays_read_by_binder':False,'claim_boundary':'Actual GenCase XML/BI4 metadata only; PartVTK initial UID/type/Mk/mass/3D/no-overlap QA remains pending.'})
if __name__=='__main__': main()
