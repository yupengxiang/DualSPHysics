"""Run the source-bound F1-S2 scalar diagnostic under the actual V10 parent.

The static generated manifest is a sealed input. No nonexistent attempt-local
manifest is assumed. The scientific worker consumes only existing small JSON;
ROOT verifies identity, scope, receipt, fees and terminal resource release.
"""
from pathlib import Path
import datetime
import fcntl
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent;S=HERE.parents[1];LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PY='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
SOURCE=S/'reference/stage2_f1_s2_integral_output_separation_request_v1.json'
MANIFEST=S/'requests/f1-s2-integral-output-primary-prepared-371-001/stage2_f1_s2_integral_output_separation_manifest_v1.json'
PILOT=S/'requests/scientific-field-h5-v3-v10-actual-pilot-root-346-001.json'
spec=importlib.util.spec_from_file_location('root_integral_bounded_helpers',S/'governance/root-owned-scientific-field-pilot-admission-v1/serial_v4.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
sha=helper.sha;load=helper.load;ref=helper.ref;new=helper.new;state=helper.state
QP=S/'requests/f1-s2-integral-output-v1-v10-root-forward-371-002.json'
UNIT='ds02-f1-s2-integral-output-v1-root-371'

def seal():
    q=load(SOURCE);pilot=load(PILOT)
    for p,h in q['input_sha256'].items():assert sha(p)==h,p
    m=load(MANIFEST)
    assert m['schema']=='ds02.stage2.f1-s2.integral-output-separation-manifest.v1'
    assert m['status']=='PREPARED_ROOT371_F1_S2_INTEGRAL_OUTPUT_DIAGNOSTIC'
    q.update(attempt_id='root371-f1-s2-integral-output-v1-actual-002',kind='cpu',cpu_task_kind='audit',
        cwd=str(LAB),worktree_root=str(LAB.parent),cpu_threads=1,omp_threads=1,
        max_wall_seconds=600,max_memory_bytes=1073741824,estimated_peak_memory_bytes=1073741824,
        estimated_storage_bytes=8388608,runtime_binding=pilot['runtime_binding'],
        interpreter_binding=pilot['interpreter_binding'],source_only=False,launch_disabled=False,execution_allowed=True)
    i=q['command'].index('--manifest')
    assert q['command'][i+1]=='{attempt_root}/manifest.json'
    q['command'][i+1]=str(MANIFEST);q['command'].insert(1,'-B')
    q['manifest_contract']=ref(MANIFEST);q['manifest_template']=ref(MANIFEST)
    q['storage_scope']={'schema':'ds02.storage-scope.v2','estimated_storage_bytes':8388608,
        'home_storage_bytes':8388608,'external_storage_bytes':0,'external_headroom_bytes':0,
        'home_headroom_bytes':4194304,'worker_scratch_bytes':0,'source_copy_bytes':0,
        'read_io_excluded_from_storage':True}
    extras=[SOURCE,MANIFEST,PILOT,Path(__file__),
        S/'governance/root-owned-scientific-field-pilot-admission-v1/serial_v4.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
        LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py',
        LAB/'scripts/ds_data02_batch_runner.py',Path(pilot['interpreter_binding']['resolved_path'])]
    extras += [Path(v['path']) for v in q['runtime_binding'].values()]
    q['input_files']=list(dict.fromkeys(q['input_files']+list(map(str,extras))))
    q['input_sha256']=q['input_hashes']={p:sha(p) for p in q['input_files']}
    q['root_integral_admission']={'source_request':ref(SOURCE),'static_manifest':ref(MANIFEST),
        'manifest_materialization_required':False,'native_payload_reopened':False,
        'scientific_Q_credit':0,'root_production_payload_content_read':False}
    sys.path.insert(0,str(LAB/'scripts'))
    from ds_data02_runtime_v8 import _light_validate
    _light_validate(q,data_root=D);new(QP,q)
    print(json.dumps({'event':'SEALED_ACTUAL_F1_S2_INTEGRAL_PARENT','request':str(QP),'sha256':sha(QP),'production_payload_read':False}),flush=True)

def launch():
    q=load(QP);ledger=load(D/'runtime/resource-ledger.json')
    assert not ledger['reservations']
    assert datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=690)<datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])+600<ledger['limits']['cpu_core_seconds']
    disk=os.statvfs(ledger['limits']['home_path'])
    assert disk.f_bavail*disk.f_frsize-8388608>=ledger['limits']['home_min_free_bytes']
    for p,h in q['input_sha256'].items():assert sha(p)==h,p
    code='import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v10_git_bound import run_request;r=run_request('+repr(str(QP))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)'
    argv=['systemd-run','--user','--unit='+UNIT,'--working-directory='+str(LAB),
        '--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec=660',
        '--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes',
        '--property=MemoryAccounting=yes','--property=MemoryMax=1073741824']
    argv+=['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    subprocess.run(argv+[PY,'-B','-I','-c',code],check=True)
    while True:
        u=state(UNIT)
        if u['SubState']!='running':break
        print(json.dumps({'event':'RUNNING_ACTUAL_F1_S2_INTEGRAL_PARENT','cpu_seconds':int(u['CPUUsageNSec'])/1e9}),flush=True)
        time.sleep(10)
    assert u['SubState']=='exited' and u['MainPID']=='0' and u['Result']=='success',u

def verify():
    common=S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    ctx={'__file__':str(common),'__name__':'root_actual_f1_s2_integral_scope'}
    exec(common.read_text(),ctx);ctx.update(sha=sha,load=load)
    q,b,r,p=ctx['common'](QP)
    report=b/'report/f1_s2_integral_output_separation_v1.json';actual=load(report)
    assert actual['schema']=='ds02.stage2.f1-s2.integral-output-separation-worker.v1'
    assert actual['status']=='COMPLETE_F1_S2_INTEGRAL_OUTPUT_DIAGNOSTIC_NO_SCIENTIFIC_Q'
    assert actual['scientific_qualification']=={'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN','scientific_credit':0}
    assert actual['read_scope']['bounded_json_only'] is True
    for key in ['native_bi4_read','vtk_read','hdf5_read','solver_launch','gencase_launch','interpolation']:
        assert actual['read_scope'][key] is False
    assert actual['manifest']['path']==str(MANIFEST) and actual['manifest']['sha256']==sha(MANIFEST)
    for v in actual['lineage'].values():assert sha(v['path'])==v['sha256']
    for v in actual['producers'].values():assert sha(v['report']['path'])==v['report']['sha256']
    assert actual['interpretation']['separation_status']=='NOT_IDENTIFIABLE_INTEGRATION_VS_OUTPUT_FROM_ASYNCHRONOUS_PAIR'
    p.update(status='VERIFIED_ACTUAL_F1_S2_INTEGRAL_OUTPUT_DIAGNOSTIC_METADATA_CLOSURE_NO_Q',
        report=str(report),report_sha256=sha(report),source_request=ref(SOURCE),static_manifest=ref(MANIFEST),
        actual_production_payload_reopened=False,world_orientation='UNKNOWN',scientific_Q_credit=0,
        scientific_error_separation='NOT_IDENTIFIABLE_FROM_ASYNCHRONOUS_PAIR',root_payload_content_read=False)
    footer=(S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text().replace(
        'F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json','F1_S2_INTEGRAL_OUTPUT_ACTUAL_ROOT_VERIFICATION_371.json')
    ctx.update(q=q,b=b,r=r,p=p,qp=QP,num='371',name='f1-s2-integral-output-v1',subprocess=subprocess,importlib=importlib)
    exec(footer,ctx);assert state(UNIT)['SubState']=='dead'
    proof=S/'checkpoints/F1_S2_INTEGRAL_OUTPUT_ACTUAL_ROOT_VERIFICATION_371.json'
    new(S/'checkpoints/ROOT371_ACTUAL_F1_S2_INTEGRAL_OUTPUT_HANDOFF_V1.json',{
        'schema':'ds02.stage2.root-f1-s2-integral-output-actual-handoff.v1','actual_proof':ref(proof),
        'scientific_error_separation':'NOT_IDENTIFIABLE_FROM_ASYNCHRONOUS_PAIR',
        'scientific_Q_credit':0,'goal_complete':False,'goal_status':'ACTIVE_FULL_SEVEN_ITEMS'})

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run'])
    args=parser.parse_args()
    if args.action=='prepare':seal()
    else:
        with (D/'runtime/root-owned-f1-s2-integral-v1.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);launch();verify()
