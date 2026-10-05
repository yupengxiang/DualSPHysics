#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
def check_request(p):
 d=json.loads(p.read_text()); files=d.get('input_files',[]); hs=d.get('input_sha256',{})
 assert set(files)==set(hs), p
 assert d['launch'] is False and d['launch_allowed'] is False and d.get('execution_allowed') is False, p
 for s in files:
  q=Path(s); assert '/tmp/root' not in s and '/tmp/f6' not in s, (p,s)
  if q.is_dir(): continue
  assert q.is_file(), (p,s)
  if q.suffix.lower()=='.bi4' or q.name in ('PartFloatInfo.ibi4','PartInfo.ibi4','PartMotionRef.ibi4','Part_Head.ibi4'):
   continue
  assert sha(q)==hs[s], (p,s,sha(q),hs[s])
for p in sorted((ROOT/'requests').glob('*.json')): check_request(p)
for p in sorted((ROOT/'requests').glob('*typed*.json')):
 d=json.loads(p.read_text()); assert d['cpu_task_kind']=='conversion' and d['expected_native_frames']==241
 assert all(d['future_outputs'][k] is None for k in ('trajectory_h5_sha256','conversion_report_sha256','execution_receipt_sha256'))
for p in sorted((ROOT/'requests').glob('*xmf*.json')):
 d=json.loads(p.read_text()); assert d['output_contract']['xdmf_sha256'] is None and d['output_contract']['manifest_sha256'] is None
for p in sorted((ROOT/'requests').glob('*render*.json')):
 d=json.loads(p.read_text()); assert d['camera_bounds_policy'].startswith('omit fixed') and d['output_contract']['frame_count']==241
agg=json.loads((ROOT/'aggregate-binding.json').read_text()); assert agg['case_count']==5 and not agg['launch_allowed']
assert all(v is None for c in agg['cases'] for v in c['typed_output_hashes'].values())
print('fresh077 source contract: PASS')
