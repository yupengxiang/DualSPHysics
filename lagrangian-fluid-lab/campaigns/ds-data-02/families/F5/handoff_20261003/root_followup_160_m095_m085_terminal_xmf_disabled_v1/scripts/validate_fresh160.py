#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
HEX=set('0123456789abcdefABCDEF')
DENIED={'.h5','.hdf5','.bi4','.ibi4','.csv','.dat','.vtk','.vtu','.npy','.npz'}
def load(p):
    d=json.loads(pathlib.Path(p).read_text())
    if not isinstance(d,dict): raise AssertionError(f'JSON object required: {p}')
    return d
def sha(p):
    p=pathlib.Path(p)
    if p.suffix.lower() in DENIED: raise AssertionError(f'science hash forbidden: {p}')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def req(x,m):
    if not x: raise AssertionError(m)
def nulls(x): return isinstance(x,dict) and all(v is None for v in x.values())
def main():
    plan=load(ROOT/'metadata/fresh160-source-plan.json'); att=load(ROOT/'metadata/terminal-typed-attestations.json'); contract=load(ROOT/'metadata/worker-contract.json')
    req(plan['source_only'] and plan['no_jobs_started'] and plan['no_shared_state_modified'],'source policy')
    worker=pathlib.Path(contract['worker_path']); req(worker.is_file() and sha(worker)==contract['worker_sha256'],'worker SHA')
    req(contract['required_binding_keys']==['typed_receipt','native_receipt','conversion_report','trajectory_h5','physical_condition_sha256','source_h5_physical_condition_sha256','physical_condition_hash_semantics','physical_case_id','expected_frames','physical_window_s','initial_qa_receipt','initial_qa_output_root','initial_qa_report','actual_counts'],'worker key contract')
    results={}
    for tag in ('M095_T080','M085_T100'):
        bpath=ROOT/'bindings'/f'{tag}-terminal-xmf-binding.json'; qpath=ROOT/'requests'/f'{tag}-terminal-xmf-request.json'; b=load(bpath); q=load(qpath); a=att['cases'][tag]
        req(b['schema']=='ds02.f5.c082s1.full801.xmf-binding.fresh160-terminal.v1','binding schema')
        req(b['disabled'] and b['source_only'] and not b['execution_allowed'] and not b['launch_allowed'] and not b['solver_allowed'],'binding disabled')
        req(q['disabled'] and q['source_only'] and not q['execution_allowed'] and not q['launch_allowed'] and not q['solver_allowed'],'request disabled')
        req(q['kind']=='cpu' and q['cpu_task_kind']=='audit' and q['cpu_threads']==2,'runtime contract')
        req(q['binding']==str(bpath) and q['binding_sha256']==sha(bpath),'binding closure')
        req(q['command'][-4:]==['--binding',str(bpath),'--output-dir','{attempt_root}/xmf'],'XMF CLI')
        req(b['typed_receipt']==b['full_typed_receipt'] and b['typed_receipt_sha256']==b['full_typed_receipt_sha256'],'typed aliases')
        req(b['conversion_report']==b['full_typed_conversion_report'] and b['conversion_report_sha256']==b['full_typed_conversion_report_sha256'],'report aliases')
        req(b['native_receipt']==b['full_native_receipt'] and b['native_receipt_sha256']==b['full_native_receipt_sha256'],'native receipt alias')
        req(b['actual_counts']['total_particles']==194427 and b['actual_counts']['fluid_particles']==31658 and b['actual_counts']['solver_dimension']==3,'actual counts')
        qa_receipt=pathlib.Path(b['initial_qa_receipt']); qa_report=pathlib.Path(b['initial_qa_report']); qr=load(qa_receipt); qreport=load(qa_report)
        req(qr['status']=='completed' and qr['returncode']==0,'initial QA receipt')
        req(b['initial_qa_output_root']==str(pathlib.Path(str(qr['output_root'])).resolve()),'initial QA output root')
        req(sha(qa_receipt)==b['initial_qa_receipt_sha256'] and sha(qa_report)==b['initial_qa_report_sha256'],'initial QA metadata hashes')
        req(b['actual_counts']==qreport['actual_counts'],'actual counts normalized to initial QA report')
        req(qreport['all_basic_placement_checks_pass'] is True and qreport['stage1_basic_placement_proof']=='pass_excluding_numerical_precision','initial placement proof')
        req(qreport['numerical_precision_result_accepted'] is False,'precision negative retained')
        req(b['expected_frames']==801 and b['expected_particle_axis']==194427 and b['expected_dimension']==3,'dimensions')
        can=b['physical_condition_sha256']; sp=b['source_plan_physical_condition_sha256']; leg=b['source_h5_physical_condition_sha256']
        req(all(isinstance(x,str) and len(x)==64 and set(x)<=HEX for x in (can,sp,leg)) and len({can,sp,leg})==3,'scope separation')
        sem=b['physical_condition_hash_semantics']; req(sem['canonical_owner_sha256']==can and sem['source_h5_sha256']==leg and sem['cross_resolution_claim'] is False,'scope semantics')
        rec=load(b['typed_receipt']); rep=load(b['conversion_report']); nrec=load(b['native_receipt'])
        req(rec['status']=='completed' and rec['returncode']==0,'typed receipt')
        req(rep['conversion_status']=='completed' and rep['frames']==801 and rep['particles']==194427 and rep['output_sha256']==b['trajectory_h5_sha256'],'conversion report')
        req(rep['hash_scopes']['physical_condition_sha256']==leg,'legacy report scope')
        req(nrec['status']=='completed' and nrec['returncode']==0,'native receipt')
        req(sha(b['typed_receipt'])==b['typed_receipt_sha256'] and sha(b['conversion_report'])==b['conversion_report_sha256'],'upstream JSON hashes')
        req(b['typed_request'] and sha(b['typed_request'])==b['typed_request_sha256'],'typed request hash')
        req(all(v is None for v in b['future_output_hashes'].values()) and all(v is None for v in b['future_xmf_output_hashes'].values()),'binding future hashes')
        req(nulls(q['future_output_hashes']),'request future hashes')
        req('.h5' not in ''.join(q['input_files']).lower() and all(pathlib.Path(p).suffix.lower() not in DENIED for p in q['input_files']),'science inputs excluded')
        req(set(q['input_files'])==set(q['input_sha256'])==set(q['input_sha256_provenance']),'input closure')
        for p,h in q['input_sha256'].items(): req(pathlib.Path(p).is_file() and sha(p)==h,f'input hash {p}')
        h5=pathlib.Path(b['trajectory_h5']); req(h5.is_file(),'producer H5 path exists')
        if tag=='M095_T080':
            st=h5.stat(); obs=b['trajectory_h5_stat']; req(obs['exists_at_source_preparation'] is True and obs['size_bytes']==st.st_size,'M095 H5 stat')
        req(a['producer_h5_sha256']==b['trajectory_h5_sha256'],'attestation')
        results[tag]={'typed_receipt':'completed/0','frames':rep['frames'],'particles':rep['particles'],'native_receipt_alias_verified':True,'initial_qa_output_root_bound':True,'actual_counts_bound_from_initial_qa_report':True,'future_xmf_hashes_null':True,'source_h5_opened_or_hashed':False}
    manifest=load(ROOT/'manifest.json'); paths={x['path'] for x in manifest['files']}
    req('manifest.json' not in paths and 'metadata/fresh160-validator-report.json' not in paths,'manifest self reference')
    for entry in manifest['files']:
        p=ROOT/entry['path']; req(p.is_file(),f'manifest missing {p}'); req(p.suffix.lower() not in DENIED,'manifest science payload'); req(sha(p)==entry['sha256'],f'manifest SHA {p}')
    out={'schema':'ds02.f5.fresh160.validator-report.v1','status':'passed','source_only':True,'science_payload_opened_or_hashed':False,'cases':results,'checks':{'m095_terminal_root939':True,'m085_terminal_root854':True,'native_receipt_alias':True,'canonical_legacy_source_scopes_separate':True,'all_requests_disabled':True,'all_future_hashes_null':True,'home_estimated_storage_bytes':1073741824}}
    (ROOT/'metadata/fresh160-validator-report.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps(out,indent=2,sort_keys=True))
if __name__=='__main__':
    try: main()
    except Exception as e: print(f'fresh160 validation failed: {e}',file=sys.stderr); raise
