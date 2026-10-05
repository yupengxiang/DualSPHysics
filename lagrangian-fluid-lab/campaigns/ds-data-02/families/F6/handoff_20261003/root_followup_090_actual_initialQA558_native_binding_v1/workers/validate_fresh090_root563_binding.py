#!/usr/bin/env python3
"""Validate fresh090 Root563 metadata bindings without scientific payload reads."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def load(p):
 d=json.loads(p.read_text(encoding='utf-8'))
 if not isinstance(d,dict): raise RuntimeError(p)
 return d

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package',required=True,type=Path); ap.add_argument('--output',required=True,type=Path); a=ap.parse_args(); p=a.package.resolve()
 m=load(p/'metadata/root563-native-binding.json'); assert m['case_count']==24
 rows=[]; seen=set(); completed=pending=0
 for row in m['cases']:
  cid=row['case_id']; assert cid not in seen; seen.add(cid)
  rp=Path(row['request']); assert rp.exists(); assert sha(rp)==row['request_sha256']
  receipt=Path(row['receipt']['path']); status=row['receipt']['status']; rc=row['receipt']['returncode']
  if row['receipt']['completed0']:
   assert status=='completed' and rc==0 and receipt.exists() and row['receipt']['sha256']==sha(receipt); completed+=1
  else:
   pending+=1
   if row['receipt']['sha256'] is not None: raise RuntimeError(f'nonterminal receipt hash: {cid}')
  rows.append({'case_id':cid,'status':status,'returncode':rc,'completed0':row['receipt']['completed0']})
 reqs=sorted((p/'qualification/requests').glob('*.json')); assert len(reqs)==24
 for q in reqs:
  d=load(q); cid=d['case_id']; row=next(x for x in m['cases'] if x['case_id']==cid)
  assert d['superseded_by_actual_root563'] is True and d['disabled'] is True and d['launch'] is False
  assert d['actual_root563_native_request']['request']==row['request']
  assert d['actual_root563_native_request']['request_sha256']==row['request_sha256']
  assert d['future_outputs']['native_execution_receipt']==row['receipt']['path']
  assert d['future_outputs']['native_execution_receipt_sha256']==row['receipt']['sha256']
 st=load(p/'floatinginfo/state0-binding.json'); assert st['native_qualification_requests_dir']==m['root563_handoff']; assert st['launch_allowed'] is False and st['execution_allowed'] is False
 for c in st['cases']:
  assert '/root_stage1_f6_actualGen539_QA558_full241_native24_563/' in c['native_request']; assert c['native_request_sha256']; assert '/root-stage1-f6-' in c['solver_receipt'] and c['solver_receipt'].endswith('/execution-receipt.json')
 result={'schema':'ds02.f6.fresh090.root563-validation.v1','pass':True,'case_count':24,'root563_completed0':completed,'root563_pending':pending,'rows':rows,'no_science_payload_read_or_hash':True,'solver_started_by_validator':False}
 a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); print(json.dumps(result,sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
