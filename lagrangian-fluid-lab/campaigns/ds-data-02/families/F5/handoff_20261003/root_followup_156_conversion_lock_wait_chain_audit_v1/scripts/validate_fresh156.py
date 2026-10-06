#!/usr/bin/env python3
"""Validate fresh156 static lock audit without runtime/science-payload access."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
MANIFEST=PKG/'manifest.json'; AUDIT=PKG/'metadata/fresh156-lock-audit.json'; PLAN=PKG/'metadata/fresh156-safe-handoff-plan.json'; PROV=PKG/'metadata/fresh156-source-provenance.json'
FORBIDDEN={'.bi4','.obi4','.ibi4','.h5','.csv','.dat','.vtk','.npy','.npz'}; SAFE={'.json','.py','.md'}; H64=re.compile(r'^[0-9a-f]{64}$'); H40=re.compile(r'^[0-9a-f]{40}$')
def chk(c,m):
    if not c: raise AssertionError(m)
def read(p): return json.loads(p.read_text())
def digest(p):
    chk(p.suffix.lower() not in FORBIDDEN,f'payload hash forbidden: {p}'); h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()
def reject(v,w=''):
    if isinstance(v,dict):
        for k,x in v.items(): reject(x,f'{w}.{k}' if w else k)
    elif isinstance(v,list):
        for i,x in enumerate(v): reject(x,f'{w}[{i}]')
    elif isinstance(v,str): chk(Path(v).suffix.lower() not in FORBIDDEN,f'payload path: {w}={v}')
audit,plan,prov=read(AUDIT),read(PLAN),read(PROV)
for x in (audit,plan,prov): reject(x)
chk(audit['schema']=='ds02.f5.fresh156.conversion-lock-wait-chain-audit.v1','audit schema')
chk(plan['schema']=='ds02.f5.fresh156.safe-handoff-plan.v1','plan schema')
chk(prov['schema']=='ds02.f5.fresh156.lock-audit-source-provenance.v1','provenance schema')
chk(audit['package_id']==plan['package_id']==prov['package_id']=='F5_fresh156_conversion_lock_wait_chain_audit','package id')
s=audit['snapshot']
for k in ('jobs_started_by_source_agent','shared_ledger_or_controller_modified','science_payload_opened_by_source_agent','science_payload_hashed_by_source_agent','science_payload_copied_by_source_agent'): chk(s[k] is False,k)
chk(s['source_only'] is True,'source only'); chk(s['source_commit']=='2776ccd2','source commit'); chk(s['parent_fresh154_commit']=='138b1aa176b33eb6b2b554e71a68baa78eec6b1e','fresh154 parent')
locks={x['name']:x for x in audit['locks']}; c=locks['conversion_dispatch']; chk(c['owner']=={'pid':3840219,'controller_id':'F5-854','lock_mode':'WRITE','owner_row_observed':True},'conversion owner'); chk([x['pid'] for x in c['waiters']]==[3853540,3855556,3870361,3874593,3877047,3885448,3895475],'conversion waiters'); chk(c['waiter_count']==7,'conversion waiter count')
n=locks['native_registration']; chk(n['owner']['pid']==3885447 and n['waiters']==[{'pid':3868473,'controller_id':'F5-871'}],'native lock')
r=locks['render_registration']; chk(r['owner']['pid']==3952170 and r['owner']['controller_id']=='F4-924','render owner'); chk(r['protected_external_renderer']['pid']==3946798,'Root920 metadata protection'); chk(r['current_owner_child']['pid']==3959401,'Root924 child')
controllers={x['controller_id']:x for x in audit['controllers']}
for cid,x in controllers.items():
    chk(x['pid']>0,f'pid {cid}'); chk(str(x['proc_start_ticks']).isdigit(),f'ticks {cid}'); chk(H64.fullmatch(x['controller_sha256'] or ''),f'controller sha {cid}'); chk(H40.fullmatch(x['launch_commit'] or ''),f'commit {cid}'); chk(x['case_credit']==0,f'credit {cid}')
    if cid == 'F6-920':
        chk(x['live_process']['observed_live_at_snapshot'] is False, 'Root920 terminal snapshot state')
        chk(x.get('terminal_metadata_state') == 'controller_exited_after_renderer_work; reservation_and_metadata_retained; no_source_retirement', 'Root920 retained metadata')
    else:
        chk(x['live_process']['observed_live_at_snapshot'] is True,f'live {cid}'); chk(x['live_process']['start_ticks_match'] is True,f'tick {cid}')
chk(controllers['F6-920']['protected_from_retirement'] is True,'920 protected'); chk(controllers['F4-924']['protected_from_retirement'] is True,'924 protected')
ledger=audit['resource_ledger_snapshot']; chk(ledger['ledger_write_performed'] is False,'ledger write'); chk(ledger['reservations_count_at_snapshot']==1,'ledger count'); chk(any(x['launcher_pid']==3959401 for x in ledger['reservations']),'924 reservation'); chk(ledger['limits']['home_min_free_bytes']==536870912000,'home floor')
f5=audit['f5_case_inventory']; chk(f5['case_credit']==0,'F5 credit'); q=f5['root854_conversion_owner']; chk(q['active_tag']=='M095_T080','active tag'); chk(q['maximum_parallel_new_conversions']==1,'serial conversion'); chk(q['estimated_storage_bytes']==32*1024**3,'32GiB estimate'); chk(q['wait_margin_bytes']==16*1024**3,'16GiB margin')
q=f5['next34']; chk(q['actual_native_completed_count']==23,'native completed'); chk(len(q['native_pending_tags'])==11,'native pending'); chk(q['root871_reported_pending_not_launched']==5,'reported pending'); chk(q['pending_reconciliation']['request_files_without_result_count']==7,'request/result mismatch'); chk(q['pending_reconciliation']['overall_native_pending_count']==11,'overall pending'); chk('metadata mismatch' in q['pending_reconciliation']['status'],'mismatch explicit'); chk(len(q['typed_concrete_pending'])==2,'typed concrete'); chk(len(q['native_ready_without_concrete_typed_request'])==20,'typed gap')
chk(len(f5['downstream_waiters']['typed_or_xmf_with_concrete_upstream'])==2,'downstream set')
chk(plan['decision'].startswith('metadata-only'),'plan decision'); chk(plan['global_state_actions_performed']==[],'global actions'); g=plan['four_gib_successor']; chk(g['can_be_registered_by_this_package'] is False,'successor disabled'); chk(g['attempt_id'] is None and g['reservation_id'] is None,'future ids'); chk(g['typed_output_hash'] is None and g['downstream_hashes'] is None,'future hashes'); chk(g['old_storage_reservation_32_gib_unchanged'] is True,'old estimate')
chk(prov['source_only_package'] is True and prov['no_jobs_started'] is True and prov['no_shared_state_modified'] is True,'provenance safety')
for e in prov['source_evidence']:
    p=Path(e['path']); chk(p.exists(),f'missing evidence {p}'); chk(p.suffix.lower() in {'.json','.py'},f'unsafe evidence {p}'); chk(H64.fullmatch(e['sha256']),'evidence sha')
chk(prov['parent_packages'][1]['runtime_bug_followup']=='fresh157','fresh157 separation')
manifest=read(MANIFEST); chk(manifest['schema']=='ds02.f5.fresh156.package-manifest.v1','manifest schema'); chk(manifest['manifest_excludes']==['metadata/fresh156-validator-report.json','manifest.json'],'manifest excludes')
for rel,want in manifest['files'].items():
    p=PKG/rel; chk(p.exists() and p.suffix.lower() in SAFE,f'package file {rel}'); chk(digest(p)==want,f'package digest {rel}')
actual={p.relative_to(PKG).as_posix() for p in PKG.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in {'manifest.json','fresh156-validator-report.json'}}; chk(actual==set(manifest['files']),'manifest inventory')
print(json.dumps({'status':'passed','package':str(PKG),'conversion_owner':'F5-854/PID3840219','conversion_waiters':7,'native_pending':11,'typed_concrete_pending':2,'typed_unbound_native_ready':20,'root920_and_root924_protected':True,'science_payload_opened':False,'shared_state_modified':False},indent=2,sort_keys=True))
