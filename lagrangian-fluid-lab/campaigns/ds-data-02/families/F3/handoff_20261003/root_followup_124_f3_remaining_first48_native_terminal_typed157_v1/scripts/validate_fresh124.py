#!/usr/bin/env python3
"""Validate fresh124 disabled Root157 requests using metadata and stat-only names."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FORBIDDEN={'.bi4','.ibi4','.obi4','.h5','.hdf5','.csv','.dat','.vtk','.vtu','.npy','.npz','.raw'}
ROOT157='nvme_convert_home_capped_v2.py'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
 return h.hexdigest()
def j(p): return json.loads(p.read_text(encoding='utf-8'))
def req(c,v,m):
 if not c: raise RuntimeError(f'{v}: {m}')
def opt(cmd,name):
 try:return cmd[cmd.index(name)+1]
 except (ValueError,IndexError):raise RuntimeError(f'missing {name}')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]);ap.add_argument('--output',type=Path);a=ap.parse_args();pkg=a.package.resolve();idx=j(pkg/'metadata/candidate-index.json');rows=idx['selected_cases'];by={r['case_id']:r for r in rows}; paths=sorted((pkg/'requests').glob('*.json'));req(len(paths)==len(rows),'package','request/index count mismatch');results=[]
 for rp in paths:
  x=j(rp); c=x.get('case_id'); req(c in by,c,'unknown case'); row=by[c]
  req(x.get('fresh_id')=='fresh124',c,'fresh id'); req(x.get('schema')=='ds02.runner-request.v2',c,'schema'); req(x.get('disabled') is True and x.get('source_only') is True,c,'disabled/source'); req(x.get('execution_allowed') is False and x.get('launch_allowed') is False and x.get('launch') is False,c,'launch gate'); req(x.get('case_credit')==0 and x.get('q_n_granted') is False,c,'credit gate');
  binding=Path(x['binding']).resolve(); req(binding.is_file(),c,'owner missing'); req(str(binding)==row['owner_path'],c,'owner path'); req(sha(binding)==x['binding_sha256']==row['owner_sha256'],c,'owner hash'); owner=j(binding); req(owner.get('physical_binding',{}).get('schema')=='ds-data-02.physical-binding.v1',c,'binding schema'); req(x['actual_converter_scope_sha256']==row['physical_condition_sha256'],c,'scope');
  ev=Path(row['native_evidence_path']).resolve(); evx=j(ev); req(evx.get('active_progress_not_runtime_input') is True,c,'progress policy'); req(evx['native_receipt']['status']=='completed' and evx['native_receipt']['returncode']==0,c,'frozen receipt'); req(evx['stat_only_frame_filename_census']['count']==836,c,'evidence frame count');
  rec=Path(x['native_receipt']['path']).resolve(); req(rec.is_file() and sha(rec)==x['native_receipt']['sha256']==evx['native_receipt']['sha256'],c,'receipt'); rr=j(rec); req(rr.get('status')=='completed' and rr.get('returncode')==0,c,'receipt terminal');
  nreq=Path(x['native_request']['path']).resolve(); req(nreq.is_file() and sha(nreq)==x['native_request']['sha256'],c,'native request'); nr=j(nreq); req(nr.get('attempt_id')==x['depends_on_attempt'],c,'native dependency'); req(x['depends_on_attempts']==[x['depends_on_attempt']],c,'dependency list'); req(x.get('historical_root839_negative') is None and x.get('root_distinct_successor_of_unlaunched_request') is None,c,'stale history');
  req(x['actual_native_dependency']['native_saved_frame_file_count']==836 and x['actual_native_dependency']['part_filename_count_stat_only']==836,c,'native count');
  cmd=x['command']; req(isinstance(cmd,list) and '--' in cmd,c,'command'); req(Path(cmd[1]).name==ROOT157,c,'worker'); req(sha(Path(cmd[1]))==x['source157_worker']['sha256'],c,'worker sha'); tail=cmd[cmd.index('--')+1:]; req(not any('ds_data02_direct_convert.py' in z or 'ds_data02_nvme_convert_v1.py' in z for z in tail),c,'redundant converter'); req(Path(opt(cmd,'--owner-metadata')).resolve()==binding,c,'owner argv'); req(opt(cmd,'--current-attempt-id').startswith(f'F3/{c}/'),c,'attempt argv'); req(x.get('cpu_threads')==2 and x.get('estimated_storage_bytes')==4294967296,c,'resources'); pol=x['storage_policy']; req(pol=={'global_conversion_cap':2,'home_free_floor_bytes':536870912000,'home_publish_cap_bytes':4294967296,'home_publish_headroom_bytes':2147483648,'private_nvme_free_reserve_bytes':107374182400,'private_nvme_staging_limit_bytes':25769803776,'resource_ledger':'/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json','resource_ledger_lock':'/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.lock'},c,'storage policy');
  inputs=x['input_files']; req(all(Path(z).is_absolute() for z in inputs),c,'absolute inputs'); req(not any(Path(z).suffix.lower() in FORBIDDEN for z in inputs),c,'science input'); req(not any('actual-progress.json' in z for z in inputs),c,'live progress leaked'); req(all(Path(z).is_file() for z in inputs),c,'input exists'); req(all(x['input_sha256'].get(z)==sha(Path(z)) for z in inputs),c,'input closure'); req(str(binding) in inputs,c,'owner input'); req(x.get('future_input_hashes_null') is True and all(v is None for v in x['future_input_sha256'].values()),c,'future null'); req(all(z is None or z==0 or (isinstance(z,str) and '{attempt_root}' in z) for z in x['future_outputs'].values()),c,'future outputs');
  results.append({'case_id':c,'request_path':str(rp.resolve()),'request_sha256':sha(rp),'native_receipt_sha256':x['native_receipt']['sha256'],'owner_sha256':x['binding_sha256'],'current_input_count':len(inputs),'current_input_sha256_closed':True,'active_progress_input':False,'typed_status':'disabled_wait_root_enablement'})
 out=a.output or pkg/'metadata/fresh124-validator-report.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps({'schema':'ds02.stage1.f3.fresh124.validator-report.v1','package':str(pkg),'selected_count':len(results),'results':results,'science_payload_opened_or_hashed':False,'jobs_started':0,'shared_state_modified':False},indent=2,sort_keys=True)+'\n');print(json.dumps({'status':'pass','selected_count':len(results),'report':str(out.resolve())},indent=2))
if __name__=='__main__':main()
