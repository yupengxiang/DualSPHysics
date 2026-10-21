"""Read terminal metadata and the unique paid GPU row; never open native payloads."""
from pathlib import Path
import datetime,json,math,resource,runpy
P=Path(__file__).resolve().parents[1]
ROOT=Path('/data/nas/jade/Simulation/DualSPHysics/lfd-01')
Q=P/'requests/CaseForces-full5-baseline-solver001-v3'
AID='F2/LFD01_F2_OFFICIAL_CASEFORCES_DP020_FULL5/LFD01_SOLVER_001'
JOB='LFD01_CASEFORCES_FULL5_BASELINE_SOLVER_001'
OUT=ROOT/'runs'/AID

def main():
    t=runpy.run_path(str(P/'work/LFD01-F4-header-adapter-software-support/20261021-v4/source/record_F4_header_adapter_software003_terminal_v4.py'))
    gpu=runpy.run_path(str(P/'control/record_F4_A0_exploratory_solver001_terminal_v7.py'))
    h=runpy.run_path(str(P/'control/prepare_F3_existing601_mass_task_actual001_v1.py'))
    read,check,digest=(t[k] for k in ('read_json','check','digest'))
    req,rr,_=read(Q/'request.json');grant,gr,_=read(Q/'grant.json');mat,mr,_=read(Q/'MATERIALIZATION.json')
    check(mat['request']==rr and mat['grant']==gr,'materialization request/grant')
    check(req['reservation_id']==AID and req['controller_job_id']==JOB and req['output_root']==str(OUT),'canonical solver identity')
    check(grant['attempt_id']==AID and grant['tranche_id']==JOB and grant['request_path']==rr['path'] and grant['request_sha256']==rr['sha256'],'grant identity/seal')
    check(grant['payload_sha256']==digest({k:v for k,v in grant.items() if k!='payload_sha256'}),'grant payload seal')
    rows=req['source_bindings'];normal=[r for r in rows if not r['deferred']];deferred=[r for r in rows if r['deferred']]
    check(len({r['path'] for r in rows})==len({r['role'] for r in rows})==len(rows),'unique source roles and paths')
    check(req['input_files']==req['normal_input_paths']==[r['path'] for r in normal],'normal input vector')
    check(grant['source_bindings']==rows and grant['source_bindings_sha256']==req['source_bindings_sha256']==digest(rows),'source seals')
    role={r['role']:r for r in rows}
    receipt,er,_=read(OUT/'execution-receipt.json');cp,cpr,_=read(ROOT/'runs/.lfd01-control/jobs'/JOB/'checkpoint.json')
    check(receipt['request']==req and receipt['request_sha256']==rr['sha256'],'terminal request seal')
    # CUDA selector is inserted by the existing owned GPU runner.
    expected=[req['command'][0],'-gpu:0',*req['command'][2:]]
    check(receipt['command']==expected,'actual command is frozen command with only owned logical GPU selector')
    check(receipt['status'] in ('completed','failed') and type(receipt['returncode']) is int,'terminal status')
    check((receipt['status']=='completed')==(receipt['returncode']==0),'terminal status/returncode')
    check(cp['result']==receipt and cp['worker_alive'] is False and cp['state'] in ('completed','failed','already_settled'),'checkpoint result/worker')
    check(cp['job_id']==JOB and cp['attempt_id']==cp['reservation_id']==AID and cp['grant_sha256']==gr['sha256'],'checkpoint identity/grant')
    check(receipt['input_hashes_at_launch']==receipt['input_hashes_after_run']=={r['path']:r['sha256'] for r in normal},'normal pre/post hashes')
    rt=receipt['lfd01_runtime'];proof=rt['deferred_input_hashes']
    check(rt['candidate_path']==role['forward_runtime_source']['path'] and rt['candidate_sha256']==role['forward_runtime_source']['sha256'] and rt['schema_path']==role['forward_runtime_schema']['path'] and rt['schema_sha256']==role['forward_runtime_schema']['sha256'],'runtime identity')
    check(proof['posthash_status']=='verified' and proof['launch']==proof['after']=={r['path']:r['sha256'] for r in deferred},'all deferred launch/reap hashes')
    check(rt['execution_status']==receipt['status'].upper() and rt['top_level_v6_status']==receipt['status'],'runtime terminal status')
    check(rt['subreaper_enabled'] is True and rt['child_exit_confirmed'] is True and rt['owned_identity_uncertain'] is False and rt['unreaped_branch_unknown'] is False and rt['terminal_settlement_blocked'] is None and rt['final_reap']['completed'] is True,'owned terminal/reap')
    for ident in (rt['owned_child'],cp['worker_identity']):t['validate_process_identity'](ident)
    group=rt['owned_group'];check(group['leader']==rt['owned_child'] and group['pgid']==rt['owned_child']['pid']==receipt['pid'] and group['subreaper_identity']==cp['worker_identity'] and group['identity_uncertain'] is False,'worker and child ownership')
    check(cp['runtime_state']['owned_child']==rt['owned_child'] and cp['runtime_state']['final_reap']==rt['final_reap'],'checkpoint reap mirror')
    uuid=receipt['gpu']['uuid'];check(type(uuid) is str and uuid.startswith('GPU-') and receipt['cuda_visible_devices']==uuid and receipt['cuda_logical_device']==0,'leased physical GPU/logical device')
    check(receipt['binary_sha256']==req['binary_binding']['sha256'] and rt['compiled_binary_reservation_admitted'] is True,'compiled branch hash/admission')
    current=dict(device=53,inode=20185002,bytes=52743392,mtime_ns=1791852734393531912,ctime_ns=1791852734394531912)
    observations=rt['compiled_binary_observations']
    for phase in ('owned_launch','after_owned_reap'):
        obs=observations[phase]
        check(all(obs[k]==req['binary_binding'][k] for k in ('path','bytes','sha256')),'compiled binary phase tuple')
        check(obs['fd_stat_before']==obs['fd_stat_after']==obs['path_lstat_before']==obs['path_lstat_after']==current,'current mount stable FD/path identity')
    settle=gpu['_validate_solver_settlement'];settle.__globals__.update(AID=AID,JOB=JOB)
    charge,attempts=settle(receipt,rr,AID)
    for key,limit in [('gpu_seconds',grant['allocation']['gpu_seconds']),('cpu_core_seconds',grant['allocation']['cpu_core_seconds'])]:
        n=receipt[key];check(type(n) in (int,float) and math.isfinite(n) and n>=0 and (receipt['status']!='completed' or n<=limit),'bounded '+key)
    check(type(receipt['bytes']) is int and receipt['bytes']>=0 and (receipt['status']!='completed' or receipt['bytes']<=grant['allocation']['new_storage_bytes']),'bounded persistent bytes')
    closure=dict(schema='lfd01.Root.CaseForces.full5-solver-terminal.v1',status='completed_solver_pending_actual_G1_G2' if receipt['status']=='completed' else 'failed_solver_no_scientific_qualification',observed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),request=rr,grant=gr,materialization=mr,receipt=er,checkpoint=cpr,contract=h['pin'](req['contract_path']),source_preflight=h['pin'](req['gencase_receipt']),source_science_nonauthor_review={k:role['source_science_nonauthor_review'][k] for k in ('path','bytes','sha256')},unique_parent_charge=charge,unique_parent_attempt=attempts[0],normal_source_posthash_exact=True,deferred_native_XML_forcing_binary_posthash_exact=True,owned_tree_reaped=True,reservation_and_lease_absent=True,old_parent_prefix_unchanged=True,runtime_actual_endpoint_trace_frames_and_arrays='not read or accepted by this terminal accounting closure; next separately admitted full native pipeline',root_native_ELF_generatedXML_or_array_read=False,science_credit=0,core_credit=0,root_self_cpu_pending_infrastructure=sum(resource.getrusage(resource.RUSAGE_SELF)[:2]))
    ref=h['publish'](Q/'ACTUAL_SOLVER_TERMINAL_CLOSURE_V1.json',closure)
    print(json.dumps(dict(closure=ref,status=closure['status'],cost=charge)))

if __name__=='__main__':main()
