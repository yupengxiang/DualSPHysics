#!/usr/bin/env python3
"""Validate fresh121 using JSON/code metadata only; never open scientific payloads."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
META = HERE / 'metadata'
REQ = HERE / 'requests/F3_STAGE1_DP006_P0800_AY0360-typed157-4gib-root121.disabled-request.json'
BIND = META / 'F3_STAGE1_DP006_P0800_AY0360-typed157-terminal-binding.json'
PLAN = META / 'source-plan-closure.json'
PREF = META / 'converter-metadata-preflight.json'
CLOSE = META / 'actual-owner-scope-closure.json'
FORBIDDEN = {'.bi4','.ibi4','.obi4','.h5','.hdf5','.csv','.dat','.vtk','.vtu','.npy','.npz','.raw'}
EXPECTED = '7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5'

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def canon(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--report', type=Path); args=ap.parse_args()
    req=json.loads(REQ.read_text()); bind=json.loads(BIND.read_text()); plan=json.loads(PLAN.read_text()); pref=json.loads(PREF.read_text()); close=json.loads(CLOSE.read_text())
    payload_files=[p for p in HERE.rglob('*') if p.is_file() and p.suffix.lower() in FORBIDDEN]
    checks={
      'disabled_terminal_request': req['disabled'] is True and req['source_only'] is True and req['launch'] is False and req['launch_allowed'] is False and req['execution_allowed'] is False,
      'recipe_unchanged': req['expected_dimension']==3 and req['expected_particles']==179208 and req['expected_frames']==836 and req['actual_native_dependency']['window_s']==[0.0,8.35] and req['actual_native_dependency']['save_interval_s']==0.01,
      'native_dependency_completed': req['actual_native_dependency']['status']=='completed' and req['actual_native_dependency']['returncode']==0,
      'scope_sha_closed': req['actual_converter_scope_sha256']==EXPECTED and bind['actual_converter_scope']['sha256']==EXPECTED and close['actual_converter_scope']['sha256']==EXPECTED and pref['result']['sha256']==EXPECTED,
      'scope_schema_closed': bind['actual_converter_scope']['schema']=='ds-data-02.physical-binding.v1' and pref['result']['schema']=='ds-data-02.physical-binding.v1',
      'owner_sha_closed': bind['actual_converter_owner']['sha256']==close['actual_converter_owner']['sha256'] and len(bind['actual_converter_owner']['sha256'])==64,
      'legacy_not_fabricated': bind['legacy_converter_scope']['sha256'] is None and close['legacy_owner_scope']['sha256'] is None and close['legacy_owner_scope']['status']=='not_applicable_explicit_v1_owner',
      'source_plan_closed': plan['source_plan_scope_sha256']==EXPECTED and close['source_plan']['scope_sha256']==EXPECTED,
      'worker_sha_preserved': req['source157_worker']['sha256']=='37fe7eaff4405e9ba6d9b7f666a53d7c02ee65fc6f30992fc1a8fdb0d8a61b11',
      'future_outputs_null': all(v is None for k,v in req['future_outputs'].items() if k!='case_credit') and req['future_outputs']['case_credit']==0 and bind['typed_result']['conversion_report_sha256'] is None and bind['typed_result']['trajectory_h5_sha256'] is None,
      'no_payload_files_in_package': not payload_files,
      'source_boundary_closed': req['source_agent_boundary']['jobs_started']==0 and req['source_agent_boundary']['scientific_payload_read'] is False and req['source_agent_boundary']['scientific_payload_hashed'] is False and req['source_agent_boundary']['shared_state_modified'] is False,
      'runtime_revalidation_required': req['terminal_binding']['status']=='WAIT_ROOT157_METADATA_AND_LIVE_GUARDS' and req['root_review_required'] is True,
      'preflight_payload_boundary': pref['result']['raw_payload_opened'] is False and pref['result']['raw_payload_hashed'] is False,
      'input_closure_metadata_only': all(Path(p).suffix.lower() not in FORBIDDEN for p in req['input_files']),
      'binding_hash_closed': req['binding_sha256']==sha(BIND) and req['input_sha256'][str(BIND)]==sha(BIND),
      'physical_binding_recanonicalizes': canon(bind['physical_binding'])==EXPECTED,
    }
    report={'schema':'ds02.stage1.f3.fresh121.validator-report.v1','package':str(HERE),'checks':checks,'forbidden_payload_files':[str(p) for p in payload_files],'source_only':True}
    out=args.report or (META/'fresh121-validator-report.json'); out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps(report,indent=2,sort_keys=True)); return 0 if all(checks.values()) else 1
if __name__=='__main__': raise SystemExit(main())
