#!/usr/bin/env python3
from pathlib import Path
import hashlib,json
PKG=Path(__file__).resolve().parents[1]
SCIENCE={'.h5','.hdf5','.dat','.csv','.bi4','.ibi4','.vtk','.vtu','.npy','.npz'}
def load(p): return json.loads(Path(p).read_text())
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def fail(msg): raise SystemExit('fresh104 validation failed: '+msg)
for p in PKG.rglob('*'):
    if p.is_file() and p.suffix.lower() in SCIENCE: fail(f'scientific payload in package: {p}')
d=load(PKG/'metadata/root716-exit143-diagnostic.json')
if d.get('schema')!='ds02.f6.fresh104.root716-exit143-root638-gate-diagnostic.v1': fail('schema')
if d.get('fresh_id')!='fresh104': fail('fresh id')
if d['parent_observation']['tool_handle']!='71522' or d['parent_observation']['reported_exit_code']!=143: fail('parent exit evidence')
if d['payload_policy']['scientific_payload_read'] or d['payload_policy']['scientific_payload_hashed']: fail('payload policy')
if d['root716']['controller_result_exists']: fail('Root716 unexpectedly has result')
if d['root716']['root637_gate_observed']['exists']: fail('Root637 unexpectedly has result')
if d['root716']['root670_gate_observed']['completed0']!=24 or d['root716']['root670_gate_observed']['pending_held']!=0: fail('Root670 evidence')
if d['root715']['declared_plan_count']!=24 or d['root715']['materialized_plan_count']!=24: fail('Root715 count')
if d['root715']['actual_renderer_requests_created']!=0 or not d['root715']['wait_actual638all24_globalrenderdrain']: fail('Root715 gate')
r=d['root638']
if r['request_count']!=24: fail('Root638 request count')
if r['status_counts']!={'completed':8,'running':2,'absent_receipt':14}: fail(f'Root638 status counts: {r["status_counts"]}')
if r['returncode_counts']!={'0':8,'None':16}: fail(f'Root638 returncode counts: {r["returncode_counts"]}')
if r['terminal_all24_completed_zero']: fail('false terminal claim')
roles={p.get('role') for p in d['process_observation']['matching_processes']}
if not roles.issubset({'root637','root716'}): fail(f'unexpected process roles: {roles}')
if not d['process_observation'].get('current_path_processes_are_not_historical_handle_proof'): fail('process attribution guard')
if d['root_cause_class']!='controller_exit143_cause_unknown_wait_gate_unresolved': fail('cause class')
if d['root716']['source_facts']['poll_missing_controller_result']['line'] is None: fail('source poll fact')
if d['root716']['source_facts']['require_each_root638_completed_zero']['line'] is None: fail('source completion fact')
for label,e in d['external_evidence'].items():
    p=Path(e['path'])
    if e['exists']:
        if p.suffix.lower() in SCIENCE: fail(f'scientific evidence path {label}')
        if sha(p)!=e['sha256']: fail(f'evidence hash {label}')
print(json.dumps({'status':'PASS','fresh_id':'fresh104','root716_safe_to_resume':False,'root638_status_counts':r['status_counts'],'process_roles':sorted(roles)},indent=2))
