"""Serially admit 53 exact missing native joins from existing actual inputs.

The legacy mass326 barrier is a queue predecessor. These frozen scientific
requests consume ROOT307 saved-mask proofs and actual native source inputs,
not mass326 products. Preserve the legacy queue and use fresh identities.
Only bound scientific children read payload; root checks bounded metadata.
"""
from pathlib import Path
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
S=HERE.parents[1]
LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PY='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
spec=importlib.util.spec_from_file_location('independent_join_bounded_control',S/'governance/root-owned-scientific-field-pilot-admission-v1/serial_v4.py')
helper=importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
sha,load,ref,new,state=helper.sha,helper.load,helper.ref,helper.new,helper.state
TERMINAL=S/'checkpoints/ROOT307_LIFECYCLE_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'
BASE_SCOPE=S/'checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT309_ACTUAL_SERIAL_OVERLAY_V1.json'
ADMISSION=S/'checkpoints/ROOT_INDEPENDENT_53_NATIVE_JOIN_SOURCE_ADMISSION_V1.json'
PILOT=S/'requests/scientific-field-h5-v3-v10-actual-pilot-root-346-001.json'
SOURCES=[(711,312,'generic-native-extract-v4-root-forward-312-002.json',7),
    (712,315,'generic-native-extract-v2-root-forward-315-004.json',8),
    *[(n,old,f'generic-native-extract-v3-root-forward-{old}-001.json',6 if old==321 else 8)
      for n,old in zip(range(713,718),range(317,322))]]

def consumers():
    sys.path.insert(0,str(LAB/'scripts'))
    import ds_data02_stage2_verify_generic_native_join_v6 as verifier
    import ds_data02_stage2_build_native_overlay_adapter_v5 as adapter
    return verifier,adapter

def plan_registry():
    value=load(TERMINAL)
    assert value['coverage']['actual_saved_mask_cases']==335
    assert value['coverage']['historical_alias_unresolved']==1
    assert value['goal_complete'] is False
    for key in ['current_registry','strict_current_plan','terminal_proof']:
        assert sha(value[key]['path'])==value[key]['sha256']
    proof=load(value['terminal_proof']['path'])
    assert proof['parent_reservation_released'] and proof['repeat_fee_idempotent']
    return Path(value['strict_current_plan']['path']),Path(value['current_registry']['path'])

def source_admission():
    assert Path.cwd()==LAB
    verifier,_=consumers()
    plan,registry=plan_registry()
    scoped,_=verifier._load_scope_v5(BASE_SCOPE,plan,S/'CURRENT336.json')
    inventory=verifier._base_inventory(BASE_SCOPE)
    rows=[];ids=set()
    for num,old,name,count in SOURCES:
        path=S/'requests'/name
        q=load(path);selected=set(q['physical_case_ids'])
        assert len(selected)==count and not ids & selected
        assert not selected & (inventory['existing']|scoped['aliases'])
        assert selected<=(inventory['bound']|inventory['unresolved'])
        if old==312: assert selected<=inventory['unresolved']
        else: assert selected<=inventory['bound']
        document=json.dumps(q)
        assert not any(t in document for t in ['ROOT242','root242','ROOT276','root276','ROOT314','root314','ROOT326','root326','MASS30','mass30'])
        manifest,mref,contracts=verifier._load_worker_manifest_v5(Path(q['manifest_contract']['path']),scoped)
        verifier.v3.v2._load_request(path,Path(q['manifest_contract']['path']),mref,manifest)
        assert len(contracts)==count
        ids|=selected
        rows.append({'namespace':num,'source_namespace':old,'request':ref(path),
            'manifest':ref(q['manifest_contract']['path']),'selected_case_ids':sorted(selected),
            'science_contract_count':len(contracts),'mass326_output_consumed':False})
    assert len(ids)==53
    new(ADMISSION,{'schema':'ds02.stage2.root-independent-native-join-source-admission.v1',
        'status':'EXACT_53_SCIENTIFIC_INPUT_CONTRACTS_READY_FOR_PARENT_NO_PAYLOAD_READ',
        'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'controller':ref(Path(__file__)),
        'source_terminal':ref(TERMINAL),'actual_scope':ref(BASE_SCOPE),'plan':ref(plan),'registry':ref(registry),
        'verifier':ref(verifier.__file__),'rows':rows,'selected_case_count':53,
        'original_scope':scoped['case_scope'],'legacy_waiters_preserved':True,
        'root_payload_content_read':False,'scientific_Q_credit':0,'goal_complete':False})
    print(json.dumps({'event':'INDEPENDENT_53_NATIVE_JOIN_SOURCE_READY','admission':ref(ADMISSION)}),flush=True)

def seal(num,old,name,count,scope,previous):
    verifier,_=consumers();plan,registry=plan_registry()
    source=S/'requests'/name;q=load(source);pilot=load(PILOT)
    admitted=load(ADMISSION)
    row=[r for r in admitted['rows'] if r['namespace']==num]
    assert len(row)==1 and row[0]['request']==ref(source)
    scoped,_=verifier._load_scope_v5(scope,plan,S/'CURRENT336.json')
    manifest,mref,_=verifier._load_worker_manifest_v5(Path(q['manifest_contract']['path']),scoped)
    assert q['physical_case_ids']==manifest['physical_case_ids'] and len(q['physical_case_ids'])==count
    for path,digest in q['input_sha256'].items(): assert sha(path)==digest,path
    q.update(attempt_id=f'root{num}-native-v6-independent-from-{old}-actual-001',
        worktree_root=str(LAB.parent),cwd=str(LAB),cpu_threads=1,omp_threads=1,
        max_wall_seconds=3600,max_memory_bytes=4294967296,estimated_peak_memory_bytes=4294967296,
        estimated_storage_bytes=268435456,runtime_binding=pilot['runtime_binding'],
        interpreter_binding=pilot['interpreter_binding'],source_only=False,execution_allowed=True,launch_disabled=False)
    if '-B' not in q['command']: q['command'].insert(1,'-B')
    q['fresh_native_admission_scope']=ref(scope)
    q['fresh_lifecycle_terminal_registry']=ref(registry)
    q['fresh_lifecycle_terminal_plan']=ref(plan)
    q['preceding_actual_serial_handoff']=ref(previous)
    q['root_independent_native_join_binding']={'namespace':num,'source_namespace':old,
        'source_request':ref(source),'admission':ref(ADMISSION),'selected_case_ids':sorted(q['physical_case_ids']),
        'historical_alias_substitution':False,'legacy_mass326_barrier_satisfied':False,
        'root_payload_content_read':False,'scientific_Q_credit':0}
    q['storage_scope']={'schema':'ds02.storage-scope.v2','estimated_storage_bytes':268435456,
        'home_storage_bytes':268435456,'external_storage_bytes':0,'external_headroom_bytes':0,
        'home_headroom_bytes':67108864,'worker_scratch_bytes':201326592,'source_copy_bytes':0}
    extras=[Path(__file__),HERE/'verify_actual_v2.py',source,ADMISSION,PILOT,scope,plan,registry,previous,
        S/'governance/root-owned-scientific-field-pilot-admission-v1/serial_v4.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
        LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py',
        LAB/'scripts/ds_data02_stage2_normalize_v6_verified_native_join_v2.py',
        LAB/'scripts/ds_data02_stage2_normalize_v6_verified_native_join_v1.py',
        LAB/'scripts/ds_data02_batch_runner.py',Path(pilot['interpreter_binding']['resolved_path'])]
    extras += [LAB/'scripts'/f'ds_data02_stage2_verify_generic_native_join_v{n}.py' for n in range(1,7)]
    extras += [LAB/'scripts'/f'ds_data02_stage2_build_native_overlay_adapter_v{n}.py' for n in range(1,6)]
    extras += [Path(v['path']) for v in q['runtime_binding'].values()]
    q['input_files']=list(dict.fromkeys(q['input_files']+list(map(str,extras))))
    q['input_hashes']=q['input_sha256']={p:sha(p) for p in q['input_files']}
    from ds_data02_runtime_v8 import _light_validate
    _light_validate(q,data_root=D)
    out=S/f'requests/generic-native-join-v6-independent-v10-root-forward-{num}-001.json'
    new(out,q)
    verifier.v3.v2._load_request(out,Path(q['manifest_contract']['path']),mref,manifest)
    return out

def launch(qp,num):
    q,l=load(qp),load(D/'runtime/resource-ledger.json')
    assert not l['reservations']
    assert datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=3690)<datetime.datetime.fromisoformat(l['deadline_utc'])
    assert sum(c.get('cpu_core_seconds',0) for c in l['charges'])+3600<l['limits']['cpu_core_seconds']
    st=os.statvfs(l['limits']['home_path'])
    assert st.f_bavail*st.f_frsize-q['estimated_storage_bytes']>=l['limits']['home_min_free_bytes']
    assert not (D/'families'/q['family_id']/q['case_id']/q['attempt_id']).exists()
    for path,digest in q['input_sha256'].items(): assert sha(path)==digest,path
    unit=f'ds02-generic-native-join-v6-root-{num}'
    code='import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v10_git_bound import run_request;r=run_request('+repr(str(qp))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)'
    command=['systemd-run','--user','--unit='+unit,'--working-directory='+str(LAB),
        '--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec=3660',
        '--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes',
        '--property=MemoryAccounting=yes','--property=MemoryMax=4294967296']
    command += ['--setenv='+key+'=1' for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    subprocess.run(command+[PY,'-B','-I','-c',code],check=True)
    while True:
        u=state(unit)
        if u['SubState']!='running':break
        print(json.dumps({'event':'RUNNING_INDEPENDENT_NATIVE_JOIN','namespace':num,
            'cpu_seconds':int(u['CPUUsageNSec'])/1e9}),flush=True);time.sleep(10)
    assert u['SubState']=='exited' and u['MainPID']=='0' and u['Result']=='success',u
    return unit

def main():
    assert Path.cwd()==LAB
    _,adapter=consumers();plan,_=plan_registry()
    scope,previous=BASE_SCOPE,ADMISSION
    for num,old,name,count in SOURCES:
        assert not load(D/'runtime/resource-ledger.json')['reservations']
        qp=S/f'requests/generic-native-join-v6-independent-v10-root-forward-{num}-001.json'
        if num==711 and qp.exists():
            q=load(qp)
            assert q['root_independent_native_join_binding']['admission']==ref(ADMISSION)
            assert q['fresh_native_admission_scope']==ref(scope)
            assert q['root_independent_native_join_binding']['source_request']==ref(S/'requests'/name)
        else:
            assert not qp.exists(), 'Unfinished prior parent requires explicit closure, never implicit relaunch'
            qp=seal(num,old,name,count,scope,previous)
        unit=launch(qp,num)
        subprocess.run([PY,'-B',str(HERE/'verify_actual_v2.py'),str(num),
            '--request',str(qp),'--scope',str(scope),'--plan',str(plan)],cwd=LAB,check=True)
        proof=S/f'checkpoints/GENERIC_NATIVE_JOIN_V6_ACTUAL_ROOT_VERIFICATION_{num}.json'
        p=load(proof)
        assert p['parent_reservation_released'] and p['repeat_fee_idempotent'] and state(unit)['SubState']=='dead'
        terminal=dict(p);terminal.update(actual_join_proof=ref(proof),selected_case_ids=sorted(load(qp)['physical_case_ids']))
        tp=S/f'checkpoints/ROOT{num}_INDEPENDENT_NATIVE_JOIN_CLOSED_TERMINAL_V1.json';new(tp,terminal)
        next_scope=S/f'checkpoints/ORIGINAL118_NATIVE_JOIN_AFTER_ROOT{num}_INDEPENDENT_STRICT_V5_OVERLAY_V1.json'
        adapter.build(scope,tp,next_scope,plan,S/'CURRENT336.json')
        consumers()[0]._load_scope_v5(next_scope,plan,S/'CURRENT336.json')
        cp=S/f'checkpoints/ROOT{num}_INDEPENDENT_NATIVE_JOIN_ACTUAL_HANDOFF_V1.json'
        new(cp,{'schema':'ds02.stage2.root-independent-native-join-actual-handoff.v1',
            'actual_proof':ref(proof),'actual_scope':ref(next_scope),'prior_scope':ref(scope),
            'selected_case_count':count,'legacy_mass326_barrier_satisfied':False,
            'scientific_Q_credit':0,'root_payload_content_read':False,'goal_complete':False})
        print(json.dumps({'event':'CLOSED_INDEPENDENT_NATIVE_JOIN','namespace':num,
            'selected_case_count':count,'proof':ref(proof),'goal_complete':False}),flush=True)
        scope,previous=next_scope,cp

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','run'])
    args=parser.parse_args()
    if args.action=='prepare':
        source_admission()
        print(json.dumps({'event':'SEALED_FIRST_INDEPENDENT_NATIVE_JOIN',
            'request':ref(seal(*SOURCES[0],BASE_SCOPE,ADMISSION))}),flush=True)
    else:
        with (D/'runtime/root-owned-independent-native-joins-v1.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
