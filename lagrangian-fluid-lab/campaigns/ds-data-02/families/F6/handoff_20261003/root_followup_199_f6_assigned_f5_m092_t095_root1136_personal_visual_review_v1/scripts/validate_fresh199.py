#!/usr/bin/env python3
"""Read-only validator for fresh199; never opens scientific payloads or hashes PNGs."""
from __future__ import annotations
import hashlib, json, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
META=ROOT/'metadata'/'visual-review.json'
FORBIDDEN={'.h5','.bi4','.csv','.dat','.vtk'}
def sha256(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
 return h.hexdigest()
def fail(msg): raise SystemExit('FAIL: '+msg)
def main():
 d=json.loads(META.read_text())
 assert d['schema']=='ds02.f6.fresh199.f5.personal-visual-review.v1'
 assert d['case_id']=='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M092_T095_NEXT34'
 assert d['physical_case_id']=='F5_COMPACT_RUNUP_RECOVERY_C082S1_M092_T095'
 v=d['personal_visual_review']; assert v['status']=='visual-approved-by-delegated-agent' and v['case_credit']==0 and not v['q_n_granted'] and not v['q_e_granted']
 s=d['producer_metadata_summary']; assert s['full_frames']==801 and s['particles']==194427
 assert s['type_counts_per_frame']=={'fixed':158559,'floating':0,'fluid':31658,'moving':4210,'unknown':0}
 assert s['last_frame_type_counts']==s['type_counts_per_frame'] and s['actual_times_preserved_exactly'] and s['native_identity_axis_preserved'] and s['nonfinite_active_states']==0
 for r in d['producer_chain']:
  p=pathlib.Path(r['path'])
  if p.suffix.lower() in FORBIDDEN: fail(f'scientific payload ref: {p}')
  if not p.is_file(): fail(f'missing metadata ref: {p}')
  if sha256(p)!=r['sha256']: fail(f'metadata SHA drift: {p}')
 rd=json.loads(pathlib.Path(next(r for r in d['producer_chain'] if r['role']=='render_execution_receipt')['path']).read_text())
 if rd.get('status')!='completed' or rd.get('returncode')!=0: fail(f'render receipt {rd.get("status")}/{rd.get("returncode")}')
 pd=json.loads(pathlib.Path(next(r for r in d['producer_chain'] if r['role']=='render_publish_receipt')['path']).read_text())
 if pd.get('status')!='published_after_atomic_rename': fail(f'publish status {pd.get("status")}')
 c=v['contact_sheets']; k=v['key_frames_viewed']
 if len(c)!=34 or [x['index'] for x in c]!=list(range(34)): fail('contact closure')
 if len(k)!=9 or [x['frame'] for x in k]!=[0,100,200,300,400,500,600,700,800]: fail('key closure')
 for x in c+k:
  p=pathlib.Path(x['path'])
  if not p.is_file() or not x['exists'] or x['bytes']!=p.stat().st_size: fail(f'PNG stat drift/missing {p}')
  if not x.get('personally_viewed_with_view_image'): fail(f'not personally viewed {p}')
  if 'sha256' in x: fail(f'PNG hash present {p}')
 roles=d['physical_scope_roles']
 if not roles['roles_are_distinct']: fail('scope roles collapsed')
 if roles['native_source_plan_condition_field_present'] or roles['xmf_source_plan_condition_field_present'] or roles['native_source_plan_condition_sha256'] is not None or roles['xmf_source_plan_condition_sha256'] is not None: fail('source-plan condition presence/value mismatch')
 if roles['native_source_plan_physical_condition_sha256']!=roles['xmf_source_plan_physical_condition_sha256']: fail('native/XMF physical plan mismatch')
 print('PASS fresh199: metadata chain, terminal receipt, atomic publish, 34 contacts, 9 key frames, scope masks')
 return 0
if __name__=='__main__': raise SystemExit(main())
