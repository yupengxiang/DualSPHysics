#!/usr/bin/env python3
from pathlib import Path
import hashlib,json
PKG=Path(__file__).resolve().parents[1]
def load(p):return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def science(p):
 s=str(p).lower();return Path(s).suffix in {'.h5','.bi4','.ibi4','.csv'} or s.endswith('/run.out') or s.endswith('/solver_output/data') or '/solver_output/data/' in s
def check(d,f):
 assert d['fresh_id']=='fresh093' and d['disabled'] and not d['launch'] and not d['execution_allowed']
 assert 'root582' not in json.dumps(d).lower()
 assert set(d['input_files'])==set(d['input_sha256'])
 for p,v in d['input_sha256'].items():
  if science(p):assert v is None
  else:assert v and Path(p).is_file() and sha(p)==v,(f,p)
 for p,v in d.get('future_input_sha256',{}).items():assert v is None
 for k,v in d.get('future_outputs',{}).items():
  if k.endswith('_sha256'):assert v is None
 assert d['future_hashes_null'] is True
 assert d['worker_sha256']=='661fa031391b1dd472ead5b99a9dbb3aa95feb6ca2141892b3c1996246139360'
 assert d['audit_worker_sha256']=='c487485ef84cc1e0293db6428b08924566694d53c9f6f02f8741e4abed4e488b'
 assert d['actual_native']['solver_status_snapshot']=='completed' and d['actual_native']['solver_returncode_snapshot']==0
 assert d['root563_request'] and d['root563_request_sha256'] and d['root563_same_case_receipt_sha256']
 assert d['future_outputs']['observed_omega_rad_s'] is None
for p in sorted((PKG/'floatinginfo/requests').glob('*.json')):check(load(p),p)
for p in sorted((PKG/'floatinginfo/bindings').glob('*.json')):check(load(p),p)
assert len(list((PKG/'floatinginfo/requests').glob('*.json')))==2
assert len(list((PKG/'floatinginfo/bindings').glob('*.json')))==2
print(json.dumps({'status':'pass','fresh_id':'fresh093','cases':2},indent=2))
