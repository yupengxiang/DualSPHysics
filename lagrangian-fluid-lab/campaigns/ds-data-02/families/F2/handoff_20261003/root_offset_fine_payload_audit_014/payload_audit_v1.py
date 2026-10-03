"""Audit immutable F2 fine particle payload before adopting augmentation labels."""
import argparse,hashlib,json,importlib.util
from pathlib import Path
import h5py
import numpy as np

def run(config,output):
 c=json.loads(config.read_text());rc=json.loads(Path(c['pose_receipt']).read_text());assert rc['status']=='completed' and rc['returncode']==0
 for key in ['source_h5','pose_h5']:
  p=Path(c[key]);sha=hashlib.sha256()
  with p.open('rb') as stream:
   for b in iter(lambda:stream.read(8*1024**2),b''):sha.update(b)
  assert sha.hexdigest()==c[key+'_sha256'],key
 spec=importlib.util.spec_from_file_location('root_f2_exact_bytes',c['bitwise_helper']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 keys=['time','particle_id','particle_zone','initial_type','initial_mk','initial_mass','mass','type','mk','valid','position','velocity','density']
 with h5py.File(c['source_h5'],'r') as a,h5py.File(c['pose_h5'],'r') as b:
  assert a['position'].shape==(401,1667249,3)
  for k in keys:m.require_bitwise_dataset(a,b,k)
  t=a['time'][:];assert t[0]==0 and t[-1]>=4 and np.all(np.diff(t)>0)
  fluid=(a['initial_type'][:]==3);assert fluid.sum()==196608
  weights=a['initial_mass'][:][fluid].astype(np.float64);assert np.isfinite(weights).all() and np.all(weights>0)
  native_sum=float(weights.sum());extra=sorted(set(b.keys())-set(a.keys()))
 result={'schema':'ds02.f2.actual-fine-offset-payload-audit.v1','passed':True,'bitwise_invariant_datasets':keys,'frames':len(t),'full_window_s':[float(t[0]),float(t[-1])],'particles':1667249,'fluid_particles':int(fluid.sum()),'converted_native_initial_fluid_mass_sum_kg':native_sum,'xml_decimal_reference_mass_kg':24.576,'representation_delta_kg':native_sum-24.576,'added_datasets':extra,'source_h5_sha256':c['source_h5_sha256'],'pose_h5_sha256':c['pose_h5_sha256'],'interpretation':'Exact payload invariance of converted float32 native state; no normalization. This is not a claim of zero physical mass defect or exact original BI4 DOUBLE precision.','q_n_status':'not_assessed','production_approval':'none'}
 assert not output.exists();output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.config,a.output)
