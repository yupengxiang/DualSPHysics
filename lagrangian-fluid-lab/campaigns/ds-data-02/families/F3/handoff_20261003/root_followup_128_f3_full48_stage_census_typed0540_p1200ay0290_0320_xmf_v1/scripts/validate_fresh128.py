#!/usr/bin/env python3
"""Validate fresh128 metadata without opening scientific payloads or launching work."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
FORBIDDEN={'.bi4','.ibi4','.obi4','.h5','.hdf5','.csv','.dat','.vtk','.vtu','.npy','.npz','.raw'}
CASES=['F3_STAGE1_DP006_P0800_AY0540','F3_STAGE1_DP006_P1200_AY0290','F3_STAGE1_DP006_P1200_AY0320']
EXCLUDED={
 'F3_STAGE1_DP006_P0800_AY0360','F3_STAGE1_DP006_P0800_AY0290','F3_STAGE1_DP006_P0800_AY0320',
 'F3_STAGE1_DP006_P0800_AY0390','F3_STAGE1_DP006_P0800_AY0430','F3_STAGE1_DP006_P0800_AY0570',
 'F3_STAGE1_DP006_P0800_AY0460','F3_STAGE1_DP006_P0800_AY0500','F3_STAGE1_DP006_P0800_AY0640'}
def load(p):
 p=Path(p); assert p.suffix.lower() not in FORBIDDEN,("forbidden",p); return json.loads(p.read_text())
def digest(p):
 p=Path(p); assert p.suffix.lower() not in FORBIDDEN,("forbidden",p); h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def check_map(m):
 assert isinstance(m,dict)
 for p,e in m.items(): assert Path(p).suffix.lower() not in FORBIDDEN and Path(p).is_file(),p; assert digest(p)==e,(p,e,digest(p))
def main():
 for p in HERE.rglob('*'):
  if p.is_file(): assert p.suffix.lower() not in FORBIDDEN and '__pycache__' not in p.parts,p
 c=load(HERE/'metadata/full48-stage-census.json'); assert c['expected_case_count']==48 and c['selected_new_typed_cases']==CASES and c['global_case_credit_updated'] is False
 assert len(c['cases'])==48 and len({x['case_id'] for x in c['cases']})==48
 sel=load(HERE/'metadata/selection-snapshot.json'); assert sel['selected_case_ids']==CASES and sel['case_credit']==0 and sel['future_xmf_render_hashes'] is None
 ex=load(HERE/'metadata/exclusion-set.json'); assert set(ex['excluded_cases'])==EXCLUDED
 for case in CASES:
  owner=load(HERE/f'metadata/owners/{case}.actual-native-physical-scope.owner.json'); snap=load(HERE/f'metadata/case-snapshots/{case}.json'); ev=load(HERE/f'metadata/typed-terminal-evidence/{case}.json')
  assert owner['case_id']==case and owner['family_id']=='F3' and owner['source_agent_read_science_payloads'] is False and owner['source_agent_hashed_science_payloads'] is False
  assert ev['status']=='completed/0' and ev['conversion_report']['frames']==836 and ev['conversion_report']['particles']==179208 and ev['conversion_report']['solver_dimension']==3 and ev['conversion_report']['partvtk_all_passed'] is True and ev['conversion_report']['producer_reported_trajectory_h5_sha256']
  assert ev['conversion_report']['trajectory_h5_sha256'] is None and snap['typed_terminal_evidence']['trajectory_h5_sha256'] is None
  tp=Path(ev['typed_receipt']['path']); rp=Path(ev['conversion_report']['path']); np=Path(ev['native_receipt']['path']); assert load(tp)['status']=='completed' and load(tp)['returncode']==0; assert load(np)['status']=='completed' and load(np)['returncode']==0; assert load(rp)['conversion_status']=='completed'
  assert ev['typed_receipt']['sha256']==digest(tp) and ev['conversion_report']['sha256']==digest(rp) and ev['native_receipt']['sha256']==digest(np)
  xb=load(HERE/f'requests/xmf/{case}-xmf-binding.json'); xr=load(HERE/f'requests/xmf/{case}-xmf-request.json'); rb=load(HERE/f'requests/render/{case}-render-binding.json'); rw=load(HERE/f'requests/render/{case}-wrapper-request.json'); rr=load(HERE/f'requests/render/{case}-root023-render-request.json')
  for obj in (xb,xr,rb,rw,rr): assert obj['disabled'] is True and obj['execution_allowed'] is False and obj.get('launch_allowed') is False and obj.get('launch_owner')=='root' and obj.get('case_credit',0)==0 and obj['fresh_id']=='fresh128'
  assert xb['typed_receipt_sha256']==digest(tp) and xb['conversion_report_sha256']==digest(rp) and xb['native_receipt_sha256']==digest(np) and xb['trajectory_h5_sha256'] is None and xb['future_outputs']['manifest_sha256'] is None
  assert xb['producer_reported_trajectory_h5_sha256']==ev['conversion_report']['producer_reported_trajectory_h5_sha256']
  assert xr['binding_sha256']==digest(HERE/f'requests/xmf/{case}-xmf-binding.json') and xr['depends_on_typed']['terminal_completed0'] is True
  assert rb['normal_xmf_binding_sha256']==digest(HERE/f'requests/xmf/{case}-xmf-binding.json') and rb['xdmf_sha256'] is None and rb['manifest_sha256'] is None and rb['trajectory_h5_sha256'] is None
  assert rr['binding_sha256']==digest(HERE/f'requests/render/{case}-render-binding.json') and rr['wrapper_request_sha256']==digest(HERE/f'requests/render/{case}-wrapper-request.json')
  for obj in (xr,rw,rr):
   if 'future_input_sha256' in obj: assert all(v is None for v in obj['future_input_sha256'].values())
  for obj in (xb,rb): check_map(obj['bound_metadata_sha256'])
 print(json.dumps({'schema':'ds02.stage1.f3.fresh128.validator-report.v1','status':'pass','full48':48,'selected_terminal_typed_completed0':CASES,'excluded_count':len(EXCLUDED),'source_only':True,'jobs_started':False,'shared_state_modified':False,'science_payload_opened_or_hashed':False},indent=2,sort_keys=True))
if __name__=='__main__': main()
