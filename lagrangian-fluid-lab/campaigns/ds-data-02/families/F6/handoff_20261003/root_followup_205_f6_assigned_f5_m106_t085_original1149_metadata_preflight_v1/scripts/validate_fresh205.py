#!/usr/bin/env python3
"""Read-only validator for the fresh205 metadata package."""
from __future__ import annotations
import hashlib, json, os, sys
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
META=HERE/'metadata/m106-t085-metadata-preflight.json'
CORR=HERE/'metadata/fresh204-xmf-scope-correction.json'

def load(p):
    with p.open() as f: return json.load(f)

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def fail(msg): raise SystemExit('FAIL: '+msg)

def main():
    m=load(META); c=load(CORR)
    if m['schema']!='ds02.f6.fresh205.m106-t085.metadata-preflight.v1': fail('schema')
    if m['identity']['case_id']!='F5_REF_RUNUP_DP020_C082S1_M106_T085_NEXT34' and m['identity']['case_id']!='F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M106_T085_NEXT34': fail('case identity')
    if m['identity']['physical_case_id']!='F5_COMPACT_RUNUP_RECOVERY_C082S1_M106_T085': fail('physical identity')
    ct=m['counts_and_time']
    if (ct['frames'],ct['expected_particles'],ct['dimension'])!=(801,194427,3): fail('shape')
    if (ct['fixed'],ct['moving'],ct['floating'],ct['fluid'])!=(158559,4210,0,31658): fail('counts')
    if not ct['typed_time_strictly_increasing'] or ct['typed_actual_time_first_s']!=0.0 or ct['typed_actual_time_last_s']!=16.00014041930218: fail('time evidence')
    rr=m['render_preflight']
    if rr['status_at_freeze'] not in {'running','completed'}: fail('render freeze status')
    if rr['status_at_freeze']=='running' and rr['terminal_observed_at_freeze'] is not False: fail('running render must be nonterminal')
    if rr['status_at_freeze']=='completed' and (rr['terminal_observed_at_freeze'] is not True or rr['returncode_at_freeze'] != 0): fail('completed render terminal proof')
    if rr['controller_start_ticks']!='210338104' or rr['controller_pid']!=253004: fail('controller snapshot')
    if rr['worker_pid']!=802577: fail('worker snapshot')
    if m['boundary']['science_payload_opened_or_hashed_by_source_agent'] is not False: fail('science boundary')
    if m['boundary']['private_png_viewed_or_hashed_by_source_agent'] is not False: fail('PNG boundary')
    if m['boundary']['case_credit']!=0 or m['boundary']['q_n'] or m['boundary']['q_e']: fail('credit gate')
    npres=m['scope_roles']['native_request_field_presence']
    if npres != {'physical_condition_sha256':True,'source_plan_condition_sha256':False,'source_plan_physical_condition_sha256':True,'source_definition_sha256':False}: fail('M106 native request field mask')
    pres=m['scope_roles']['xmf_manifest_field_presence']
    if pres != {'source_definition_sha256':True,'source_plan_condition_sha256':False,'source_plan_physical_condition_sha256':True}: fail('M106 XMF field mask')
    if c['corrected_presence'] != {'source_definition_sha256':True,'source_plan_condition_sha256':False,'source_plan_physical_condition_sha256':True}: fail('fresh204 correction')
    if not c['fresh204_bytes_modified'] is False: fail('fresh204 must remain immutable')
    # Every listed ref is metadata/source only and its frozen SHA must match.
    banned=('.h5','.bi4','.dat','.csv','.vtk','.vtu','.png','.jpg','.jpeg')
    for ref in m['metadata_refs']:
        p=Path(ref['path'])
        if any(str(p).lower().endswith(s) for s in banned): fail('payload ref '+str(p))
        if not p.exists(): fail('missing ref '+str(p))
        if sha(p)!=ref['sha256']: fail('metadata SHA drift '+str(p))
    # The local snapshots are immutable package evidence; live source may have changed after freeze.
    snap=load(HERE/'metadata/live-render-execution-receipt.snapshot.json')
    if snap.get('status') not in {'running','completed'}: fail('render receipt snapshot status')
    if snap.get('status')=='running' and snap.get('returncode') is not None: fail('running receipt has returncode')
    if snap.get('status')=='completed' and snap.get('returncode') != 0: fail('completed receipt not zero')
    xmf_ref=next(r for r in m['metadata_refs'] if r['role']=='xmf_manifest')
    xmf=load(Path(xmf_ref['path']))
    if 'source_plan_condition_sha256' in xmf: fail('M106 XMF condition-plan key unexpectedly present')
    if xmf.get('source_plan_physical_condition_sha256')!='0c0013f50e2bca5bee381eadcf19a031f1a4463e550fffc02d41097f911f46bb': fail('M106 XMF physical-plan role')
    cmanifest=load(Path(c['actual_manifest']['path']))
    if 'source_plan_condition_sha256' in cmanifest: fail('fresh204 correction manifest unexpectedly contains condition-plan key')
    if 'source_definition_sha256' not in cmanifest or 'source_plan_physical_condition_sha256' not in cmanifest: fail('fresh204 correction manifest field presence')
    if sha(Path(c['actual_manifest']['path'])) != c['actual_manifest']['sha256']: fail('fresh204 correction manifest SHA')
    print('PASS fresh205 metadata preflight: refs=%d, render status=%s, XMF condition-plan ABSENT' % (len(m['metadata_refs']), rr['status_at_freeze']))
    return 0
if __name__=='__main__': sys.exit(main())
