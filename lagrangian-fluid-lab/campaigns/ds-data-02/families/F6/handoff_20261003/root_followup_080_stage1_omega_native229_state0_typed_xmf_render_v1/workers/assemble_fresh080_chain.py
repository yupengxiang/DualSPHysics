#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def sha(p: Path) -> str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def walk_sha(v):
 if isinstance(v,dict):
  for k,x in v.items():
   if k.endswith('sha256') and x is not None: return True
   if walk_sha(x): return True
 if isinstance(v,list): return any(walk_sha(x) for x in v)
 return False
def check_request(p):
 d=load(p)
 for k in ('launch','launch_allowed','execution_allowed','disabled'):
  expected = False if k != 'disabled' else True
  if d.get(k) is not expected: raise ValueError(f'{p}: {k}={d.get(k)!r}')
 if set(d.get('input_files',[])) != set(d.get('input_sha256',{})): raise ValueError(f'{p}: static input hash closure')
 for name,digest in d.get('input_sha256',{}).items():
  q=Path(name)
  if not q.is_file(): raise ValueError(f'{p}: missing static input {q}')
  if sha(q)!=digest: raise ValueError(f'{p}: static input hash mismatch {q}')
 if set(d.get('future_input_files',[])) != set(d.get('future_input_sha256',{})): raise ValueError(f'{p}: future input closure')
 if any(x is not None for x in d.get('future_input_sha256',{}).values()): raise ValueError(f'{p}: future input hash fabricated')
 if walk_sha(d.get('future_outputs',{})): raise ValueError(f'{p}: future output hash fabricated')
 if d.get('case_id') and 'endpoint_id' in d.get('case_id',''): raise ValueError(f'{p}: legacy endpoint field leaked into case id')
 return {'path':str(p),'case_id':d.get('case_id'),'kind':d.get('kind'),'cpu_task_kind':d.get('cpu_task_kind')}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parents[1]); ap.add_argument('--output',type=Path); a=ap.parse_args(); pkg=a.package.resolve(); rows=[]
 for pattern in ('floatinginfo/state0-request.json','typed/requests/*.json','xmf/requests/*.json','render/requests/*.json'):
  for p in sorted(pkg.glob(pattern)): rows.append(check_request(p))
 idx=load(pkg/'metadata/case-index.json'); assert len(idx['cases'])==8
 for row in idx['cases']:
  assert row['case_id'].startswith('F6_STAGE1_ANGULAR_RELEASE_OMEGA_S')
  assert len(row['omega_rad_s'])==3 and row['expected_native']['dimension']==3
  assert set(row['expected_native']) >= {'dimension','total','fixed','floating','fluid','moving'}
  assert row['mass_policy']['physical_rigid_mass_kg']==128.0 and row['mass_policy']['native_support_mass_kg']==256.0
  assert row['actual_initial_qa']['pass'] is True
 report={'schema':'ds02.f6.fresh080.metadata-only-assembler-report.v1','package':str(pkg),'request_count':len(rows),'requests':rows,'cases':8,'actual_root226_qa':'completed/0 all pass','native229':'all eight completed/0 bound; dependent stages remain disabled','plan_case_id_omega_semantics':True,'counts_separate_from_dimension':True,'future_hashes_null':True,'scientific_arrays_read':False,'jobs_started':False,'shared_mutations':False,'claim_boundary':'Metadata closure only; Root must execute state0, typed conversion, XMF and Root023 render through approved runners.'}
 if a.output: a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__': main()
