"""Actual full same-UID F3 path comparison with no retrospective pass gate."""
import argparse,json,hashlib
from pathlib import Path
import h5py
import numpy as np

def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  while c:=f.read(1048576):h.update(c)
 return h.hexdigest()
def stats(delta,weights):
 if len(delta)==0:return {'identities':0}
 return {'identities':len(delta),'native_mass_kg':float(weights.sum()),'mass_weighted_mean_abs_gap_s':float(np.dot(np.abs(delta),weights)/weights.sum()),'max_abs_gap_s':float(np.abs(delta).max()),'p95_abs_gap_s':float(np.percentile(np.abs(delta),95))}
def main():
 p=argparse.ArgumentParser();p.add_argument('--binding',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();b=json.loads(a.binding.read_text());config=json.loads(Path(b['event_config']).read_text());data={}
 if a.output.exists():raise FileExistsError(a.output)
 for role,s in b['sources'].items():
  r=json.loads(Path(s['receipt']).read_text());report=json.loads(Path(s['labels_report']).read_text())
  if r['status']!='completed' or r['returncode']!=0 or not report['closure']['passed'] or digest(s['labels'])!=s['sha256']:raise ValueError('Immutable actual full canonical labels required')
  with h5py.File(s['labels'],'r') as h:
   if json.loads(h.attrs['config_json'])!=config:raise ValueError('Frozen actual event configuration differs')
   keys=['particle_id','particle_zone','initial_fluid_mass_kg','source_label','final_category','first_passage_censor','first_passage_interval','first_passage_chord_time','residence_time_s','unresolved_interval_time_s','time'];data[role]={k:h[k][:] for k in keys}
  times=data[role]['time']
  if len(times)!=836 or times[0]!=0 or times[-1]<8.35 or not np.isfinite(times).all() or not np.all(np.diff(times)>0):raise ValueError('Full actual native time support missing')
 x,y=data['baseline'],data['halfstep']
 for k in ['particle_id','particle_zone','initial_fluid_mass_kg','source_label']:
  if not np.array_equal(x[k],y[k]):raise ValueError('Same native UID/cohort/weight differs:'+k)
 ids=np.column_stack((x['particle_zone'],x['particle_id']));mass=x['initial_fluid_mass_kg'];fluid=mass>0
 if len(ids)!=179208 or len(np.unique(ids,axis=0))!=179208 or fluid.sum()!=67500:raise ValueError('Actual source partition differs')
 switches=fluid&(x['final_category']!=y['final_category']);events=[]
 for i,event in enumerate(config['events']):
  nx=fluid&(x['first_passage_censor'][:,i]==0);ny=fluid&(y['first_passage_censor'][:,i]==0);joint=nx&ny;ix=x['first_passage_interval'][joint,i];iy=y['first_passage_interval'][joint,i];overlap=np.maximum(ix[:,0],iy[:,0])<=np.minimum(ix[:,1],iy[:,1]);delta=y['first_passage_chord_time'][joint,i]-x['first_passage_chord_time'][joint,i]
  events.append({'event':event['id'],'joint_first_passages':int(joint.sum()),'nominal_only_first_passages':int((nx&~ny).sum()),'half_only_first_passages':int((ny&~nx).sum()),'literal_native_bracket_overlap_count':int(overlap.sum()),'literal_native_bracket_disjoint_count':int((~overlap).sum()),'chord_gap':stats(delta,mass[joint]),'classification':'descriptive sameUID sensitivity, no new perUID timing acceptance or causality'})
 residence=[{'destination':reg['id'],**stats(y['residence_time_s'][fluid,i]-x['residence_time_s'][fluid,i],mass[fluid])} for i,reg in enumerate(config['destination_regions'])]
 result={'schema':'ds02.f3.actual-candidate006-full-native-paired-transport.v1','binding':b,'fluid_identities':67500,'native_initial_mass_kg':float(mass.sum()),'actual_fate_switches':int(switches.sum()),'native_fate_switch_mass_kg':float(mass[switches].sum()),'event_first_passages':events,'residence':residence,'unresolved_time_gap':stats(y['unresolved_interval_time_s'][fluid]-x['unresolved_interval_time_s'][fluid],mass[fluid]),'q_n':'not_granted','production_approval':'none','limitations':['No CDF/macro proxy grants path equivalence.','Canonical numerical loss/unknown/invalid codes remain actual final categories.','Original0075 paired1388fate switches remains negative; no alias transfer.']}
 with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps({'actual_fate_switches':result['actual_fate_switches'],'q_n':'not_granted'}))
if __name__=='__main__':main()
