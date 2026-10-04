"""Root integrity guards around the byte-exact owner F2 array comparison."""
import argparse,importlib.util,json
from pathlib import Path
import h5py
import numpy as np

def main():
 p=argparse.ArgumentParser();p.add_argument('--binding',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();binding=json.loads(a.binding.read_text())
 s=importlib.util.spec_from_file_location('selected_owner',Path(__file__).with_name('owner_worker_v3.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 original_derive=m.derive_per_uid_residence_streaming
 def derive(h,chunk_frames=64):
  times=np.asarray(h['time'][:],dtype=float);n=len(times);role={401:'nominal401',4001:'dense4001'}.get(n)
  if role is None or len(h['particle_id'])!=196608:raise ValueError('Actual registered full source population differs')
  if not np.isfinite(times).all() or times[0]!=0 or times[-1]!=binding['sources'][role]['actual_native_end_s'] or times[-1]<4 or not np.all(np.diff(times)>0):raise ValueError('Full native actual support missing')
  if h['destination_code'].shape!=(n,196608):raise ValueError('Destination identity shape differs')
  for start in range(0,n,64):
   if not np.isin(h['destination_code'][start:start+64],np.arange(5)).all():raise ValueError('Unknown destination code must not be silently negative-indexed')
  events=h['events'][:]
  if events.dtype!=m.EVENT_DTYPE or not np.isfinite(events['time_s']).all() or not np.isfinite(events['mass_kg']).all():raise ValueError('Native event schema/finite states differ')
  return original_derive(h,chunk_frames=chunk_frames)
 m.derive_per_uid_residence_streaming=derive
 original_verify=m.verify_per_uid_residence_properties
 def verify(residence,times,source_mass,obs):
  result=original_verify(residence,times,source_mass,obs)
  for r in result['reproduction_checks'].values():
   if abs(r['delta_fractional_cohort_time'])>1e-10:raise ValueError('Actual per-UID fractional cohort time does not reproduce original aggregate')
  result['root_roundoff_note']='These are numerical summation closure checks, not scientific error acceptance; gamma_(196608+2*4001) times total native mass and duration bounds reassociation roundoff below 1e-8 kg*s; no sqrt(N) deterministic error bound is assumed.'
  return result
 m.verify_per_uid_residence_properties=verify
 for item in binding['sources'].values():
  if m.sha256_file(item['execution_receipt'])!=item['expected_receipt_sha256']:raise ValueError('Actual terminal receipt hash differs')
 m.execute_full_h5_comparison(binding,a.output)
 print(json.dumps({'actual_full_native_label_array_comparison':'completed','q_n':'not_granted','production':'none'}))
if __name__=='__main__':main()
