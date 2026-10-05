#!/usr/bin/env python3
"""Strict per-case/batch native initial QA for fresh070.
Only Root may run this after actual GenCase.  Science arrays are not read by
source preparation; this worker reads BI4 through official PartVTK at runtime.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, subprocess, xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
import numpy as np
CSV_FIELDS=['Pos.x [m]','Pos.y [m]','Pos.z [m]','Zone','Idp','Type','Mk','Mass [kg]','Vel.x [m/s]','Vel.y [m/s]','Vel.z [m/s]','Rhop [kg/m^3]','Press [Pa]']
def sha(p):
 h=hashlib.sha256();
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def load(p):
 v=json.loads(Path(p).read_text());
 if not isinstance(v,dict): raise ValueError(p)
 return v
def req(c,m):
 if not c: raise RuntimeError(m)
def csv_export(case,out,partvtk):
 bi4=Path(case['generated_bi4']); xml=Path(case['generated_xml']); dst=out/(case['case_id']+'-initial-all.csv'); req(not dst.exists(),f'refusing overwrite: {dst}'); before=sha(bi4)
 cmd=[partvtk,'-filedata',str(bi4),'-filexml',str(xml),'-threads:2','-savecsv',str(dst),'-onlytype:+all','-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone','-csvsep:1']; subprocess.run(cmd,cwd=str(out),check=True)
 req(sha(bi4)==before,f'{case["case_id"]}: PartVTK mutated BI4'); req(dst.is_file(),f'{case["case_id"]}: CSV missing')
 with dst.open(newline='',encoding='utf-8') as f: rows=list(csv.reader(f))
 hi=next((i for i,row in enumerate(rows) if 'Pos.x [m]' in row),None); req(hi is not None,f'{case["case_id"]}: official CSV header missing'); header=rows[hi]; idx=[header.index(k) for k in CSV_FIELDS]; data=rows[hi+1:]
 while data and not any(x.strip() for x in data[-1]): data.pop()
 req(all(any(x.strip() for x in row) for row in data),f'{case["case_id"]}: interior empty CSV row'); req(len(data)==case['expected']['total_particles'],f'{case["case_id"]}: CSV rows {len(data)} != {case["expected"]["total_particles"]}')
 vals=np.asarray([[float(row[i]) for i in idx] for row in data],dtype=float); return vals,{'official_csv':str(dst),'official_csv_sha256':sha(dst),'initial_bi4_sha256':before,'csv_header_index':hi,'partvtk_command':cmd}
def check_xml(case):
 tree=ET.parse(case['generated_xml']).getroot(); c=tree.find('./execution/constants'); p=tree.find('./execution/particles'); d=tree.find('./casedef/geometry/definition'); req(c is not None and p is not None and d is not None,'generated XML missing contract sections'); data2d=c.find('data2d'); params={n.get('key'):n.get('value') for n in tree.findall('./execution/parameters/parameter')}; req(data2d is not None and data2d.get('value')=='false','not actual 3D'); req(d.get('dp')=='0.02' and params.get('TimeMax')=='12' and params.get('TimeOut')=='0.02','native recipe changed'); expected=case['expected']; blocks={}
 for block in expected['type_mk_blocks']:
  node=p.find(block['name']); req(node is not None,f'{case["case_id"]}: block missing {block["name"]}'); blocks[block['name']]={'begin':int(node.get('begin')),'count':int(node.get('count')),'type':int(block['type']),'mk':int(node.get('mk'))}; req(blocks[block['name']]=={k:block[k] for k in ('begin','count','type','mk')},f'{case["case_id"]}: XML block mismatch')
 req(int(p.get('np'))==expected['total_particles'],'XML total mismatch'); return {'xml_contract':True,'xml_sha256':sha(case['generated_xml']),'blocks':blocks}
def check(case,rows):
 e=case['expected']; req(rows.shape==(e['total_particles'],13),f'{case["case_id"]}: shape {rows.shape}'); req(bool(np.isfinite(rows).all()),f'{case["case_id"]}: nonfinite'); req(bool(np.equal(rows[:,3:7],np.floor(rows[:,3:7])).all()),f'{case["case_id"]}: categorical fields nonintegral'); zone=rows[:,3].astype(np.int64); uid=rows[:,4].astype(np.int64); typ=rows[:,5].astype(np.int64); mk=rows[:,6].astype(np.int64); req(bool(np.equal(zone,0).all()),'nonzero zone'); req(bool(np.array_equal(np.sort(uid),np.arange(e['total_particles']))),'UID set/loss mismatch'); order=np.argsort(uid,kind='stable'); rows=rows[order]; typ=typ[order]; mk=mk[order]
 blocks={}
 for b in e['type_mk_blocks']:
  sl=slice(b['begin'],b['begin']+b['count']); req(bool(np.equal(typ[sl],b['type']).all()),f'{case["case_id"]}: Type mismatch'); req(bool(np.equal(mk[sl],b['mk']).all()),f'{case["case_id"]}: Mk mismatch'); blocks[b['name']]={'count':b['count'],'type':b['type'],'mk':b['mk'],'uid_range_exact':True}
 req(bool(np.all(rows[:,7]>0)),'nonpositive weights'); req(bool(np.all(rows[:,11]>0)),'nonpositive density'); req(float(np.max(np.abs(rows[:,8:11])))<=e['velocity_zero_tolerance_m_per_s'],'initial velocity nonzero'); coords=rows[:,:3]; req(np.unique(coords,axis=0).shape[0]==len(rows),'initial coordinate overlap'); sets=[]
 for b in e['type_mk_blocks']:
  s=slice(b['begin'],b['begin']+b['count']); sets.append({tuple(x) for x in coords[s]})
 overlaps={'fixed_moving':len(sets[0]&sets[1]),'fixed_fluid':len(sets[0]&sets[2]),'moving_fluid':len(sets[1]&sets[2])}; req(all(v==0 for v in overlaps.values()),f'pairwise overlap {overlaps}'); fluid=typ==3; req(int(fluid.sum())==e['fluid_particles'],'fluid count mismatch'); fc=coords[fluid]; req(all(np.unique(fc[:,i]).size>1 for i in range(3)),'fluid is not genuinely 3D'); mass=float(rows[fluid,7].sum()); delta=mass-e['native_fluid_mass_kg']; req(np.isfinite(mass) and abs(delta)<=e['mass_tolerance_kg'],f'native fluid mass mismatch {mass} vs {e["native_fluid_mass_kg"]}'); return {'row_shape_exact':True,'all_13_fields_finite':True,'uid_exact_sorted_unique':True,'native_type_mk_blocks':blocks,'all_native_weights_positive':True,'all_native_densities_positive':True,'initial_velocity_zero_within_tolerance':True,'global_coordinate_unique':True,'pairwise_initial_overlap_counts':overlaps,'no_initial_overlap':True,'fluid_count_exact':True,'actual_3d':True,'actual_fluid_envelope_m':[fc.min(axis=0).tolist(),fc.max(axis=0).tolist()],'official_CSV_fluid_mass_sum_kg':mass,'registered_native_fluid_mass_kg':e['native_fluid_mass_kg'],'native_mass_difference_kg':delta,'continuum_envelope_mass_kg':e['continuum_envelope_mass_kg'],'mass_policy':'native unscaled; continuum comparison separately reported; no rescale'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--binding',required=True,type=Path); ap.add_argument('--output-dir',required=True,type=Path); a=ap.parse_args(); b=load(a.binding); req(b.get('schema')=='ds02.f7.first24.actual-gencase-native-qa-binding.v1','binding schema mismatch'); req(b.get('launch_allowed') is False,'binding unexpectedly enabled'); out=a.output_dir; out.mkdir(parents=True,exist_ok=True); results=[]
 for case in b['cases']:
  for key in ('gencase_receipt','prepared_input_report','generated_xml','generated_bi4','generated_definition','generated_motion','source_definition','prepared_definition'):
   req(Path(case[key]).is_file(),f'{case["case_id"]}: missing {key}');
  req(sha(case['gencase_receipt'])==case['gencase_receipt_sha256'],f'{case["case_id"]}: receipt hash'); rec=load(case['gencase_receipt']); req(rec.get('status')=='completed' and rec.get('returncode')==0,f'{case["case_id"]}: GenCase receipt not completed/0'); xml_checks=check_xml(case); rows,prov=csv_export(case,out,'/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64'); row_checks=check(case,rows); results.append({'case_id':case['case_id'],'physical_condition_sha256':case['physical_condition_sha256'],'native_particles':int(rows.shape[0]),'checks':{**xml_checks,**prov,**row_checks},'passed':True})
 report={'schema':'ds02.f7.first24.actual-native-initial-qa.v1','scope_id':b['scope_id'],'binding':str(a.binding),'binding_sha256':sha(a.binding),'cases':results,'all_cases_passed':True,'independent_case_count_increment':0,'q_n':'not_granted','production_approval':'none','precision_status':'not_accepted','visual_acceptance':'not_assessed','claim_boundary':'Native initial UID/type/Mk/mass/3D/no-overlap QA only; no full12 dynamics, visual acceptance, Q-N, or production claim.'}; (out/'native-initial-qa.json').write_text(json.dumps(report,indent=2)+"\n")
if __name__=='__main__': main()
