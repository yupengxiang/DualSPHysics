#!/usr/bin/env python3
"""Static source-only contract checker for F4 fresh081.

It validates canonical identity hashes, byte-local XML mutations, source
counts/recipe, disabled request flags, active input closure, and null future
outputs. It never reads BI4/H5/CSV arrays and never starts a job.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import xml.etree.ElementTree as ET

OLD_LITERAL=b"0.42500000000000004"

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
 return h.hexdigest()
def cjson(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def csha(v): return hashlib.sha256(cjson(v).encode()).hexdigest()
def load(p): return json.loads(Path(p).read_text())
def fail(msg): raise SystemExit(msg)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parent); a=ap.parse_args(); p=a.package
 plan=load(p/'source-plan.json'); receipt=load(p/'source-build-receipt.json')
 if plan['stage_contract']['launch_allowed'] is not False: fail('launch allowed in source plan')
 if len(plan['endpoints']) != 8: fail('endpoint count')
 ids=[]; old=Path(plan['mother_binding']['source_definition_xml']).read_bytes()
 if old.count(OLD_LITERAL) != 1: fail('mother literal count')
 byid={r['endpoint_id']:r for r in receipt['endpoints']}
 for ep in plan['endpoints']:
  eid=ep['endpoint_id']; cid=ep['physical_case_id']; ids.append(cid)
  owner=load(p/'owners'/f'{eid}.owner.json'); bind=owner['physical_binding']
  if csha(bind) != owner['physical_binding_sha256']: fail(f'{eid}: canonical hash')
  if owner['physical_binding_sha256'] != ep['physical_condition_sha256']: fail(f'{eid}: plan owner hash')
  src=p/ep['source_definition_output']; after=src.read_bytes()
  if len(after)!=len(old): fail(f'{eid}: byte length')
  expected=old.replace(OLD_LITERAL,ep['drop_point_z_literal'].encode(),1)
  if after!=expected: fail(f'{eid}: nonlocal source mutation')
  ET.fromstring(after)
  if after.count(ep['drop_point_z_literal'].encode()) != 1: fail(f'{eid}: z literal')
  if sha(src) != byid[eid]['source_definition_sha256']: fail(f'{eid}: source receipt hash')
  if owner['future_outputs']['native_receipt_sha256'] is not None: fail(f'{eid}: future native hash')
  if owner['future_outputs']['typed_h5_sha256'] is not None: fail(f'{eid}: future typed hash')
  for req in sorted((p/'requests').glob('*.json')):
   if req.name == 'index.json': continue
   q=load(req)
   if q.get('launch') is not False or q.get('launch_allowed') is not False or q.get('status') != 'source_only_disabled': fail(f'{req}: disabled contract')
   if q.get('launch_owner') != 'root' or q.get('independent_case_count_increment') != 0: fail(f'{req}: owner/count')
   if q.get('q_n_status') != 'not_assessed' or q.get('precision_status') != 'not_accepted': fail(f'{req}: claim status')
   fs=set(q.get('input_files',[])); hs=set(q.get('input_sha256',{}))
   if fs != hs: fail(f'{req}: active input closure')
   for f in fs:
    fp=Path(f)
    if not fp.is_file(): fail(f'{req}: missing input {f}')
    if sha(fp) != q['input_sha256'][f]: fail(f'{req}: input hash {f}')
    if fp.suffix.lower() in {'.bi4','.h5','.csv'}: fail(f'{req}: raw array input active')
   for f,h in q.get('deferred_input_sha256',{}).items():
    if h is not None: fail(f'{req}: deferred future hash')
  # every request has no produced result hash at source time
 if len(set(ids)) != 8: fail('canonical ids are not unique')
 if sorted(round(float(e['gap_m']),5) for e in plan['endpoints']) != [.185,.195,.205,.215,.225,.235,.245,.255]: fail('gap set')
 print(json.dumps({'status':'pass','scope_id':plan['scope_id'],'endpoint_count':8,'arrays_read':False,'jobs_started':False},sort_keys=True))
if __name__ == '__main__': main()
