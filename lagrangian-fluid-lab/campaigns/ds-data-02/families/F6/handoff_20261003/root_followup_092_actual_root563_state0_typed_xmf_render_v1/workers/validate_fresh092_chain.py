#!/usr/bin/env python3
"""Static metadata-only validator for F6 fresh092.
It hashes only JSON/XML/Python and other declared metadata; BI4/H5/CSV/Run.out/data
paths are required to remain null and are never opened.
"""
from pathlib import Path
import hashlib,json,sys
PKG=Path(__file__).resolve().parents[1]

def load(p): return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def science(p):
 s=str(p).lower(); return Path(s).suffix in {'.h5','.bi4','.ibi4','.csv'} or s.endswith('/run.out') or s.endswith('/solver_output/data') or '/solver_output/data/' in s
def check_input(obj, label):
 fs=obj.get('input_files',[]); hm=obj.get('input_sha256',{})
 assert set(fs)==set(hm), f'{label}: input_files/input_sha256 mismatch'
 for p,v in hm.items():
  if science(p): assert v is None, f'{label}: scientific hash must be null: {p}'
  else:
   assert v is not None, f'{label}: non-scientific input hash is null: {p}'
   assert Path(p).is_file(), f'{label}: missing input: {p}'
   assert sha(p)==v, f'{label}: stale input hash: {p}'
def future_null(obj,label):
 for k,v in obj.get('future_input_sha256',{}).items(): assert v is None, f'{label}: future hash not null {k}'
 for k,v in obj.get('future_outputs',{}).items():
  if k.endswith('_sha256') or k.endswith('_hash'): assert v is None, f'{label}: future output hash not null {k}'
 assert obj.get('future_hashes_null') is True, f'{label}: future_hashes_null'

def main():
 ts=sorted((PKG/'typed/requests').glob('*.json')); tb=sorted((PKG/'typed/bindings').glob('*.json'))
 xs=sorted((PKG/'xmf/requests').glob('*.json')); xb=sorted((PKG/'xmf/bindings').glob('*.json'))
 rs=sorted((PKG/'render/requests').glob('*.json')); rb=sorted((PKG/'render/bindings').glob('*.json'))
 assert all(len(x)==24 for x in (ts,tb,xs,xb,rs,rb)), 'expected 24 files in each stage'
 assert len({load(f)['case_id'] for f in ts})==24
 worker_x=PKG/'workers/export_xmf.py'; worker_r=PKG/'workers/render_native023.py'
 assert worker_x.is_file() and worker_r.is_file()
 for f in ts:
  d=load(f); assert d['disabled'] and not d['launch'] and not d['execution_allowed']; assert d['cpu_task_kind']=='conversion' and d['cpu_threads']==2; assert 'root_stage1_home_floor_inventory_dispatch_142' in d['root_runtime_entry']; assert 'Root146' not in json.dumps(d)
  assert d['xmf_shape_contract']['dynamic_vector_dimensions']=='417505 3'; check_input(d,f); future_null(d,f)
 for f in tb:
  d=load(f); assert d['future_output_hashes_null'] is True; check_input(d,f)
 for f in xs:
  d=load(f); assert d['disabled'] and not d['launch'] and not d['execution_allowed']; assert d['cpu_task_kind']=='audit' and d['cpu_threads']==2; assert d['expected_frames']==241; assert d['producer_scope_schema']=='ds-data-02.physical-binding.v1'; assert 'Root146' not in json.dumps(d); check_input(d,f); future_null(d,f)
 for f in xb:
  d=load(f); assert d['future_output_hashes_null'] is True; assert d['xmf_shape_contract']['dynamic_vector_dimensions']=='417505 3'; check_input(d,f)
 for f in rs:
  d=load(f); assert d['disabled'] and not d['launch'] and not d['execution_allowed']; assert d['cpu_task_kind']=='audit' and d['cpu_threads']==2; assert d['expected_native_frames']==241; assert d['camera_policy']['camera_bounds_in_manifest'] is False and d['camera_policy']['fixed_camera_override'] is False; assert 'Root146' not in json.dumps(d); check_input(d,f); future_null(d,f)
 for f in rb:
  d=load(f); assert d['future_output_hashes_null'] is True; assert d['camera_policy']['native_geometry_retained'] is True; check_input(d,f)
 # The final copied worker bytes, rather than fresh091's stale embedded digest, are authoritative.
 for f in xb:
  d=load(f); assert d['input_sha256'][str(worker_x)]==sha(worker_x)
 for f in rb:
  d=load(f); assert d['input_sha256'][str(worker_r)]==sha(worker_r)
 # State0 pass is gated independently; observed omega can only accompany actual pass.
 for f in ts:
  d=load(f); st=d['floatinginfo_state0']; assert st['status'] in ('actual_root582_state0_pass','future_required_same_case_root582_pass')
  if st['status']=='actual_root582_state0_pass': assert st['execution_receipt_sha256'] and st['audit_report_sha256'] and st['checks_all_pass'] is True and st['observed_omega_rad_s']
  else: assert st['execution_receipt_sha256'] is None and st['audit_report_sha256'] is None and st['observed_omega_rad_s'] is None
 print(json.dumps({'status':'pass','fresh_id':'fresh092','cases':24},indent=2))
if __name__=='__main__': main()
