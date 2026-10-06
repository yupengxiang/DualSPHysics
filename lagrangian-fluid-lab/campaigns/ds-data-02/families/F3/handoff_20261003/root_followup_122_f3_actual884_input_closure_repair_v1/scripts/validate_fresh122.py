#!/usr/bin/env python3
"""Validate fresh122 paths and hashes without opening scientific payloads."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
HERE=Path(__file__).resolve().parents[1]
REQ=HERE/'requests/F3_STAGE1_DP006_P0800_AY0360-typed157-4gib-root122.disabled-request.json'
BIND_LOCAL=HERE/'metadata/F3_STAGE1_DP006_P0800_AY0360-typed157-terminal-binding.json'
PRUNE=HERE/'metadata/fresh118-input-prune.json'
REPORT=HERE/'metadata/fresh122-validator-report.json'
FORBIDDEN={'.bi4','.ibi4','.obi4','.h5','.hdf5','.csv','.dat','.vtk','.vtu','.npy','.npz','.raw'}
EXPECTED_SCOPE='7560a18fa29742681ee567b06567ed4052da8ceb138b601e94b5223df22660f5'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while True:
   b=f.read(1024*1024)
   if not b: break
   h.update(b)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--report',type=Path); args=ap.parse_args()
 req=json.loads(REQ.read_text()); bind=json.loads(BIND_LOCAL.read_text()); prune=json.loads(PRUNE.read_text())
 binding_path=Path(req['binding'])
 payload_inputs=[p for p in req['input_files'] if Path(p).suffix.lower() in FORBIDDEN]
 existing=[p for p in req['input_files'] if not Path(p).is_file()]
 actual_hashes={p:sha(Path(p)) for p in req['input_files'] if Path(p).is_file() and Path(p).suffix.lower() not in FORBIDDEN}
 checks={
  'all_input_paths_absolute': all(Path(p).is_absolute() for p in req['input_files']),
  'all_input_paths_exist': not existing,
  'all_input_hashes_closed': not payload_inputs and all(req['input_sha256'].get(p)==h for p,h in actual_hashes.items()) and set(req['input_sha256'])==set(req['input_files']),
  'binding_uses_request_absolute_path': binding_path.is_absolute() and binding_path.is_file(),
  'binding_bytes_match_package_copy': binding_path.is_file() and binding_path.read_bytes()==BIND_LOCAL.read_bytes(),
  'binding_hash_matches_request': binding_path.is_file() and req['binding_sha256']==sha(binding_path) and req['input_sha256'].get(str(binding_path))==sha(binding_path),
  'no_stale_fresh118_inputs': all('root_followup_118' not in p for p in req['input_files']),
  'fresh118_history_preserved_no_delete': prune['delete_performed'] is False and len(prune['removed_from_successor_request'])>=1,
  'disabled_future_null': req['disabled'] is True and req['source_only'] is True and req['launch'] is False and req['execution_allowed'] is False and all(v is None for k,v in req['future_outputs'].items() if k!='case_credit') and req['future_outputs']['case_credit']==0,
  'recipe_and_scope_unchanged': req['expected_dimension']==3 and req['expected_particles']==179208 and req['expected_frames']==836 and req['actual_converter_scope_sha256']==EXPECTED_SCOPE and bind['actual_converter_scope']['sha256']==EXPECTED_SCOPE,
  'native_terminal_dependency': req['actual_native_dependency']['status']=='completed' and req['actual_native_dependency']['returncode']==0,
  'source_boundary_closed': req['source_agent_boundary']['jobs_started']==0 and req['source_agent_boundary']['scientific_payload_read'] is False and req['source_agent_boundary']['scientific_payload_hashed'] is False and req['source_agent_boundary']['shared_state_modified'] is False,
 }
 report={'schema':'ds02.stage1.f3.fresh122.validator-report.v1','package':str(HERE),'checks':checks,'missing_inputs':existing,'forbidden_payload_inputs':payload_inputs,'binding_request_path':str(binding_path),'source_only':True}
 out=args.report or REPORT; out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n'); print(json.dumps(report,indent=2,sort_keys=True)); return 0 if all(checks.values()) else 1
if __name__=='__main__': raise SystemExit(main())
