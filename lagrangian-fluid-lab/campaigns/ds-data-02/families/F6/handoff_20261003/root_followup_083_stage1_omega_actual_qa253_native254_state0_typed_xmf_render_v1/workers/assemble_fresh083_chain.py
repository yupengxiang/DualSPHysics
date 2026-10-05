#!/usr/bin/env python3
"""Fail-closed bounded metadata checker for F6 fresh083.
It hashes only static JSON/XML/source inputs. Scientific BI4/IBI4/H5/CSV/NPY/NPZ payloads
remain future job inputs and are never opened by this source checker.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
RAW={'.bi4','.ibi4','.h5','.hdf5','.csv','.vtk','.vtu','.npy','.npz'}
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text())
def check_req(p):
 d=load(p)
 assert d.get('launch') is False and d.get('launch_allowed') is False and d.get('execution_allowed') is False and d.get('disabled') is True, p
 assert set(d.get('input_files',[]))==set(d.get('input_sha256',{})), p
 for name,digest in d.get('input_sha256',{}).items():
  q=Path(name); assert q.suffix.lower() not in RAW and q.is_file() and sha(q)==digest, (p,q)
 assert set(d.get('future_input_files',[]))==set(d.get('future_input_sha256',{})), p
 assert all(v is None for v in d.get('future_input_sha256',{}).values()), p
 def walk(v):
  if isinstance(v,dict):
   for k,x in v.items():
    if k.endswith('sha256') and x is not None and any(t in k for t in ('future','output','receipt','report','manifest','hdf5','trajectory','audit','observed')): raise AssertionError((p,k,x))
    walk(x)
  elif isinstance(v,list):
   for x in v: walk(x)
 walk(d.get('future_outputs',{}))
 return {'path':str(p),'case_id':d.get('case_id'),'cpu_task_kind':d.get('cpu_task_kind')}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]); a=ap.parse_args(); pkg=a.package.resolve()
 g=load(pkg/'metadata/actual-gencase250-bindings.json'); assert g['all_completed_returncode_zero'] and g['all_counts_match'] and len(g['cases'])==8
 q=load(pkg/'metadata/actual-qa253-provenance.json'); assert q['aggregate']['status']=='completed' and q['aggregate']['returncode']==0 and q['aggregate']['pass'] and q['all_reports_pass']
 n=load(pkg/'metadata/actual-native254-snapshot.json'); assert len(n['source082_attempts'])==8
 assert set(d['case_id'] for d in g['cases'])==set(d['case_id'] for d in q['cases'])==set(d['case_id'] for d in n['source082_attempts'])
 reqs=[]
 reqs.append(check_req(pkg/'floatinginfo/state0-request.json'))
 for pat in ('typed/requests/*.json','xmf/requests/*.json','render/requests/*.json'):
  reqs += [check_req(p) for p in sorted(pkg.glob(pat))]
 assert len(reqs)==25, len(reqs)
 for p in pkg.rglob('*'):
  if p.is_file(): assert p.suffix.lower() not in RAW, p
 assert all(d['future_receipt_hash_null'] for d in n['source082_attempts'])
 report={'schema':'ds02.f6.fresh083.metadata-only-preflight.v1','fresh_id':'fresh083','case_count':8,'request_count':len(reqs),'actual_gencase250':'completed/0 all counts 417505/327680/3D','actual_qa253':'completed/0 pass all eight','native254_snapshot':{'all_terminal_completed_zero':n['all_terminal_completed_zero'],'future_receipts_null':True},'typed_request_count':8,'xmf_request_count':8,'render_request_count':8,'state0_request_count':1,'xmf_shape_contract':{'vector':'417505 3','scalar':'417505','implementation':'outshape = shape[1:]'},'arrays_read':False,'jobs_started':False,'shared_state_modified':False,'status':'pass','claim_boundary':'Source metadata closure only; Root must enable jobs and bind new receipts. No Q-N/precision/visual/production claim.'}
 out=pkg/'metadata/metadata-only-preflight-report.json'; out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__': main()
