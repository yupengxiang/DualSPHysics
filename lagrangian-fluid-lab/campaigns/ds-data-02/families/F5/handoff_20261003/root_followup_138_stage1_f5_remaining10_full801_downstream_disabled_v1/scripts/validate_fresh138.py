#!/usr/bin/env python3
"""Metadata-only validator for F5 fresh138.

This validator reads JSON/XML/Python metadata and package source only. It never
opens or hashes BI4, DAT, H5, CSV, VTK, or solver payloads and never launches a
job. Future typed/XMF/bed/render products are required to remain null in this
source-only package.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

PKG=Path(__file__).resolve().parents[1]
DENIED={'.bi4','.dat','.h5','.csv','.vtk','.vtu','.vtp'}
TAGS=['M085_T090','M085_T100','M095_T080','M095_T090','M095_T100','M105_T080','M105_T090','M105_T100','M115_T080','M115_T090']
ROOT808=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F5_remaining10_actual807_visual_endpoints_native230_parallel_idle_808')

def load(p:Path): return json.loads(p.read_text())
def sha(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def require(x,msg):
    if not x: raise AssertionError(msg)
def ishex(x): return isinstance(x,str) and len(x)==64 and all(c in '0123456789abcdefABCDEF' for c in x)
def future_null(value):
    if value is None: return True
    if isinstance(value,dict): return all(future_null(v) for v in value.values())
    if isinstance(value,list): return all(future_null(v) for v in value)
    return False

def main():
    m=load(PKG/'manifest.json'); require(m.get('source_only') is True,'manifest source_only'); require('manifest.json' not in {x['path'] for x in m['files']},'manifest self reference'); require('metadata/fresh138-validator-report.json' not in {x['path'] for x in m['files']},'validator report self reference')
    for e in m['files']:
        p=PKG/e['path']; require(p.is_file(),f'missing {p}'); require(p.suffix.lower() not in DENIED,f'science payload in package {p}'); require(sha(p)==e['sha256'],f'manifest mismatch {p}')
    plan=load(PKG/'metadata/fresh138-source-plan.json'); require(plan['candidate_tags']==TAGS and plan['candidate_count']==10,'candidate set'); require(not any('T120' in t for t in TAGS),'T120 included'); require(plan['full801_downstream_enabled'] is False,'downstream enabled'); require(plan['future_payload_hashes'] is None,'future plan hashes')
    ctrl=load(PKG/'metadata/root808-controller-summary.json'); require(ctrl['requested']==10 and ctrl['completed0']==10 and ctrl['actual_full801_native_pass_count']==10 and ctrl['pending_held']==0,'Root808 controller gate')
    results=[]
    for tag in TAGS:
        att=load(PKG/f'metadata/case-attestations/{tag}.json'); require(att['root808_status']=='completed/0' and att['native_saved_frame_file_count']==801,f'{tag} upstream native')
        rp=Path(att['root808_native_request']); rcp=Path(att['root808_native_receipt']); require(rp.is_file() and rcp.is_file(),f'{tag} upstream files'); require(sha(rp)==att['root808_native_request_sha256'],f'{tag} request sha'); require(sha(rcp)==att['root808_native_receipt_sha256'],f'{tag} receipt sha')
        nr=load(rp); rr=load(rcp); require(nr['physical_case_id']==att['physical_case_id'] and nr['attempt_id']==att['actual_native_attempt_id'],f'{tag} native identity'); require(rr.get('status')=='completed' and rr.get('returncode')==0,f'{tag} native receipt'); require(nr['actual_counts']==att['actual_counts'],f'{tag} native counts')
        for role in ('gencase','initial_qa'):
            x=att[role]; receipt=load(Path(x['receipt'])); require(receipt.get('status') in {'completed','completed/0'} and receipt.get('returncode')==0,f'{tag} {role} receipt')
            require(sha(Path(x['receipt']))==x['receipt_sha256'],f'{tag} {role} receipt sha')
        qa=load(Path(att['initial_qa']['report'])); require(qa.get('all_basic_placement_checks_pass') is True,f'{tag} QA basic'); require(qa.get('numerical_precision_result_accepted') is False,f'{tag} precision relabel'); require(qa.get('actual_counts')==att['actual_counts'],f'{tag} QA counts')
        for stage,suffix in [('typed','typed-nvme-request.json'),('xmf','xmf-request.json'),('bed','bed-audit-request.json'),('render','root023-render-request.json')]:
            req=load(PKG/f'requests/{tag}-full801-{suffix}'); bind=load(PKG / f"bindings/{tag}-full801-{ {'typed':'typed-binding.json','xmf':'xmf-binding.json','bed':'bed-audit-binding.json','render':'root023-render-binding.json'}[stage] }")
            require(req['disabled'] is True and req['execution_allowed'] is False and req['launch_allowed'] is False and req['solver_allowed'] is False,f'{tag} {stage} enablement')
            require(bind['disabled'] is True and bind['execution_allowed'] is False,f'{tag} {stage} binding enablement')
            require(req['physical_case_id']==att['physical_case_id'] and bind['physical_case_id']==att['physical_case_id'],f'{tag} {stage} physical identity')
            require(req['actual_native_request']==att['root808_native_request'] and req['actual_native_receipt']==att['root808_native_receipt'],f'{tag} {stage} own native closure')
            require(req['actual_native_request_sha256']==att['root808_native_request_sha256'] and req['actual_native_receipt_sha256']==att['root808_native_receipt_sha256'],f'{tag} {stage} native hashes')
            require(req['actual_counts']==att['actual_counts'] and bind['actual_counts']==att['actual_counts'],f'{tag} {stage} counts')
            require(req['expected_frames']==801 and req['expected_particle_axis']==194427,f'{tag} {stage} frame/axis')
            require(req.get('native_bed_marker_mk')==50 and req.get('source_bed_marker_mkbound')==40,f'{tag} {stage} markers')
            require(f'root-stage1-f5-c082s1-{tag.lower()}-' in req['attempt_id'],f'{tag} {stage} attempt')
            require(Path(str(req.get('actual_native_request'))).name == f'{tag}-full801-native-request.json',f'{tag} stale native request')
            require(set(req.get('input_files',[]))==set(req.get('input_sha256',{}))==set(req.get('input_sha256_provenance',{})),f'{tag} {stage} input closure')
            for p,v in req.get('input_sha256',{}).items():
                ext=Path(p).suffix.lower()
                if ext in DENIED: require(v is not None and 'producer-attested' in req['input_sha256_provenance'][p],f'{tag} opaque producer hash')
            require(f'root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1' in req['binding'],f'{tag} {stage} own binding')
            scope=req.get('canonical_physical_scope',bind.get('canonical_physical_scope',{})); require(scope.get('canonical_and_source_plan_are_distinct') is True,f'{tag} {stage} scope collapse')
            require(future_null(req.get('future_output_hashes')),'future request hashes')
            if stage in {'xmf','bed','render'}:
                require(req.get('cpu_task_kind')=='audit',f'{tag} {stage} cpu kind')
            if stage=='typed': require(req.get('cpu_task_kind')=='conversion',f'{tag} typed kind')
        results.append({'tag':tag,'physical_case_id':att['physical_case_id'],'actual_native_status':'completed/0','actual_gencase_status':'completed/0','actual_initial_qa_status':'completed/0','downstream_requests_disabled':True,'future_hashes_null':True})
    report={'schema':'ds02.f5.c082s1.fresh138-validator-report.v1','status':'passed_metadata_only','candidate_count':10,'results':results,'root808_controller_gate':'completed0/10 with 801 native frames each','T120_included':False,'source_science_payloads_read_or_hashed':False,'jobs_started':False,'shared_state_modified':False,'downstream_enabled':False,'full801_native_is_upstream_only':True}
    (PKG/'metadata/fresh138-validator-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':report['status'],'candidate_count':10,'report':str(PKG/'metadata/fresh138-validator-report.json')},indent=2))
if __name__=='__main__': main()
