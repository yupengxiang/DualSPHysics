#!/usr/bin/env python3
"""Strict fresh074 initial native QA; Root runs this only after actual GenCase.
The source agent never invokes it.  Runtime arrays are isolated to this job's
official PartVTK CSV output and are never written to the worktree.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
FIELDS=['Pos.x [m]','Pos.y [m]','Pos.z [m]','Zone','Idp','Type','Mk','Mass [kg]','Vel.x [m/s]','Vel.y [m/s]','Vel.z [m/s]','Rhop [kg/m^3]','Press [Pa]']
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def req(x,m):
 if not x: raise RuntimeError(m)
def export(case,out,partvtk):
 bi4=Path(case['generated_bi4']); xml=Path(case['generated_xml']); dst=out/(case['case_id']+'-initial-all.csv'); req(not dst.exists(),'refusing overwrite: '+str(dst)); before=sha(bi4)
 cmd=[partvtk,'-filedata',str(bi4),'-filexml',str(xml),'-threads:2','-savecsv',str(dst),'-onlytype:+all','-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone','-csvsep:1']; subprocess.run(cmd,cwd=str(out),check=True); req(sha(bi4)==before,'PartVTK mutated BI4'); req(dst.is_file(),'CSV missing')
 with dst.open(newline='',encoding='utf-8') as f: rows=list(csv.reader(f))
 hi=next((i for i,row in enumerate(rows) if 'Pos.x [m]' in row),None); req(hi is not None,'official CSV header missing'); header=rows[hi]; idx=[header.index(k) for k in FIELDS]; data=rows[hi+1:]
 while data and not any(x.strip() for x in data[-1]): data.pop()
 req(len(data)==case['expected']['total_particles'],f'CSV rows {len(data)} != {case["expected"]["total_particles"]}'); vals=np.asarray([[float(row[i]) for i in idx] for row in data],dtype=float); req(vals.shape==(case['expected']['total_particles'],13),'CSV shape mismatch'); return vals,{'official_csv':str(dst),'official_csv_sha256':sha(dst),'initial_bi4_sha256':before,'csv_header_index':hi,'partvtk_command':cmd}
def check_xml(case):
 root=ET.parse(case['generated_xml']).getroot(); c=root.find('./execution/constants'); p=root.find('./execution/particles'); d=root.find('./casedef/geometry/definition'); req(c is not None and p is not None and d is not None,'XML sections missing'); req(c.find('data2d').get('value')=='false','not actual 3D'); params={n.get('key'):n.get('value') for n in root.findall('./execution/parameters/parameter')}; req(d.get('dp')=='0.02' and params.get('TimeMax')=='12' and params.get('TimeOut')=='0.02','native recipe changed'); blocks={}
 for b in case['expected']['type_mk_blocks']:
  n=p.find(b['name']); req(n is not None,'block missing '+b['name']); got={k:int(n.get(k)) for k in ('begin','count','type','mk')}; req(got=={k:b[k] for k in ('begin','count','type','mk')},'XML block mismatch'); blocks[b['name']]=got
 req(int(p.get('np'))==case['expected']['total_particles'],'XML total mismatch'); return {'xml_sha256':sha(case['generated_xml']),'native_type_mk_blocks':blocks}
def check(case,rows):
 e=case['expected']; req(np.isfinite(rows).all(),'nonfinite native field'); req(np.equal(rows[:,3:7],np.floor(rows[:,3:7])).all(),'categorical field nonintegral'); zone=rows[:,3].astype(np.int64); uid=rows[:,4].astype(np.int64); typ=rows[:,5].astype(np.int64); mk=rows[:,6].astype(np.int64); req(np.equal(zone,0).all(),'nonzero zone'); req(np.array_equal(np.sort(uid),np.arange(e['total_particles'])),'UID set/loss mismatch'); order=np.argsort(uid,kind='stable'); rows=rows[order]; typ=typ[order]; mk=mk[order]
 blocks=e['type_mk_blocks']; sets=[]
 for b in blocks:
  sl=slice(b['begin'],b['begin']+b['count']); req(np.equal(typ[sl],b['type']).all(),'Type mismatch'); req(np.equal(mk[sl],b['mk']).all(),'Mk mismatch'); sets.append({tuple(x) for x in rows[sl,:3]})
 req(np.all(rows[:,7]>0),'nonpositive weights'); req(np.all(rows[:,11]>0),'nonpositive density'); req(np.max(np.abs(rows[:,8:11]))<=e['velocity_zero_tolerance_m_per_s'],'initial velocity exceeds strict tolerance'); coords=rows[:,:3]; req(np.unique(coords,axis=0).shape[0]==len(rows),'initial coordinate overlap'); overlaps={'fixed_moving':len(sets[0]&sets[1]),'fixed_fluid':len(sets[0]&sets[2]),'moving_fluid':len(sets[1]&sets[2])}; req(all(v==0 for v in overlaps.values()),'pairwise initial overlap'); fluid=typ==3; req(int(fluid.sum())==e['fluid_particles'],'fluid count mismatch'); fc=coords[fluid]; req(all(np.unique(fc[:,i]).size>1 for i in range(3)),'fluid is not genuinely 3D'); mass=float(rows[fluid,7].sum()); req(np.isfinite(mass) and abs(mass-e['native_fluid_mass_kg'])<=e['mass_tolerance_kg'],f'native fluid mass mismatch {mass} vs {e["native_fluid_mass_kg"]}'); return {'all_13_fields_finite':True,'uid_exact_sorted_unique':True,'all_native_weights_positive':True,'all_native_densities_positive':True,'initial_velocity_zero_within_tolerance':True,'global_coordinate_unique':True,'pairwise_initial_overlap_counts':overlaps,'actual_3d':True,'fluid_count_exact':True,'official_CSV_fluid_mass_sum_kg':mass,'registered_native_fluid_mass_kg':e['native_fluid_mass_kg'],'continuum_envelope_mass_kg':e['continuum_envelope_mass_kg'],'mass_policy':'native unscaled; continuum comparison separate; no rescale'}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--binding',required=True,type=Path); ap.add_argument('--output-dir',required=True,type=Path); a=ap.parse_args(); b=load(a.binding); req(b.get('schema')=='ds02.f7.next24.actual-gencase-native-qa-binding.v1','binding schema mismatch'); req(b.get('launch_allowed') is False,'binding unexpectedly enabled'); out=a.output_dir; out.mkdir(parents=True,exist_ok=True); result=[]
 for case in b['cases']:
  for key in ('gencase_receipt','prepared_input_report','generated_xml','generated_bi4','generated_definition','generated_motion'): req(Path(case[key]).is_file(),case['case_id']+' missing '+key)
  rec=load(case['gencase_receipt']); req(rec.get('status')=='completed' and rec.get('returncode')==0,case['case_id']+' GenCase not completed/0'); xc=check_xml(case); rows,prov=export(case,out,b['partvtk']); rc=check(case,rows); result.append({'case_id':case['case_id'],'physical_condition_sha256':case['physical_condition_sha256'],'canonical_physical_binding_sha256':case['canonical_physical_binding_sha256'],'native_particles':int(rows.shape[0]),'checks':{**xc,**prov,**rc},'passed':True})
 (out/'native-initial-qa.json').write_text(json.dumps({'schema':'ds02.f7.next24.actual-native-initial-qa.v1','scope_id':b['scope_id'],'binding':str(a.binding),'binding_sha256':sha(a.binding),'cases':result,'all_cases_passed':True,'independent_case_count_increment':0,'q_n':'not_granted','production_approval':'none','precision_status':'not_accepted','visual_acceptance':'not_assessed','claim_boundary':'Native initial UID/type/Mk/mass/3D/no-overlap QA only; no full12 dynamics, visual acceptance, Q-N, or production claim.'},indent=2)+'\n')
if __name__=='__main__': main()
