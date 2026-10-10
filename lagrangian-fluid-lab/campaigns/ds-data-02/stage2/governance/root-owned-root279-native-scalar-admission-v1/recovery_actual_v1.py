"""Recover compact/scalar metadata from the successful failed-parent producer.

ROOT reads only bounded metadata/code; the bound V3 child streams production
H5 after reservation. Scientific qualification and physical authority remain
UNKNOWN. All observations, failed attempts, and complete fees are preserved.
"""
from pathlib import Path
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
import subprocess
import time
import sys

HERE=Path(__file__).resolve().parent;S=HERE.parents[1];LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PY='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
SOURCE=S/'requests/root279-native-scalar-recovery-v1-primary-prepared-362-001/root279-native-scalar-recovery-request.json'
OLD=S/'requests/root279-pair-native-source-v6-prepared-001/request.json'
PILOT=S/'requests/scientific-field-h5-v3-v10-actual-pilot-root-346-001.json'
UNKNOWN={'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'}

def sha(p):
    p=Path(p);assert not p.is_symlink() and p.is_file() and p.stat().st_size<=10485760
    assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.pvtu','.jsonl'}
    a=p.stat();b=p.read_bytes();z=p.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns)
    return hashlib.sha256(b).hexdigest()

def load(p):sha(p);return json.loads(Path(p).read_text())
def ref(p):return {'path':str(p),'sha256':sha(p)}
def new(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')

def state(unit):
    raw=subprocess.check_output(['systemctl','--user','show',unit,'-p','SubState','-p','MainPID','-p','Result','-p','CPUUsageNSec'],text=True)
    return dict(line.split('=',1) for line in raw.splitlines())

def seal():
    q=load(SOURCE);pilot=load(PILOT)
    q.update(kind='cpu',attempt_id='root362-root279-native-scalar-recovery-v1-001',cwd=str(LAB),worktree_root=str(LAB.parent),cpu_threads=1,omp_threads=1,max_wall_seconds=300,max_memory_bytes=1073741824,estimated_peak_memory_bytes=1073741824,estimated_storage_bytes=67108864,runtime_binding=pilot['runtime_binding'],interpreter_binding=pilot['interpreter_binding'],execution_allowed=True,launch_disabled=False,source_only=False)
    q['command'].insert(1,'-B')
    q['storage_scope']={'schema':'ds02.storage-scope.v2','estimated_storage_bytes':67108864,'home_storage_bytes':67108864,'external_storage_bytes':0,'external_headroom_bytes':0,'home_headroom_bytes':33554432,'worker_scratch_bytes':0,'source_copy_bytes':0,'read_io_excluded_from_storage':True}
    q['source_read_cost']={'selected_native_files_reused_as_metadata':10,'native_payload_bytes_reopened':0,'source_native_copy_bytes':0}
    extras=[SOURCE,PILOT,Path(__file__),S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py',S/'reference/stage2_f1_s2_root279_native_scalar_recovery_request_v1.py',LAB/'scripts/ds_data02_batch_runner.py',Path(pilot['interpreter_binding']['resolved_path'])]
    extras += [Path(v['path']) for v in q['runtime_binding'].values()]
    q['input_files']=list(dict.fromkeys(q['input_files']+list(map(str,extras))))
    hashes={p:sha(p) for p in q['input_files']}
    for path,digest in load(SOURCE)['input_sha256'].items():assert hashes[path]==digest,path
    q['input_sha256']=q['input_hashes']=hashes
    assert sha(q['manifest_contract']['path'])==q['manifest_contract']['sha256']
    q['root_source_binding']={'source_request':ref(SOURCE),'failed_parent':ref(S/'checkpoints/ROOT353_FAILED_NATIVE_SCALAR_ACTUAL_METADATA_CLOSURE_V1.json'),'root_production_payload_content_read':False,'native_payload_reopened':False,'actual_execution_scope':'metadata recovery of guarded producer then compact V3/scalar V2/independent verifier; no world-axis or Q'}
    sys.path.insert(0,str(LAB/'scripts'))
    from ds_data02_runtime_v8 import _light_validate
    _light_validate(q,data_root=D)
    out=S/'requests/root279-native-scalar-recovery-v1-v10-root-forward-362-001.json';new(out,q)
    print(json.dumps({'event':'SOURCE_PREPARED_METADATA_RECOVERY','request':str(out),'sha256':sha(out),'native_payload_reopened':False}),flush=True)
    return out

def launch(qp,num):
    q=load(qp);l=load(D/'runtime/resource-ledger.json');assert not l['reservations']
    assert datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=q['max_wall_seconds']+90)<datetime.datetime.fromisoformat(l['deadline_utc'])
    assert sum(x.get('cpu_core_seconds',0) for x in l['charges'])+q['cpu_threads']*q['max_wall_seconds']<l['limits']['cpu_core_seconds']
    disk=os.statvfs(l['limits']['home_path']);assert disk.f_bavail*disk.f_frsize-q['estimated_storage_bytes']>=l['limits']['home_min_free_bytes']
    assert q['cpu_threads']==1 and q['estimated_storage_bytes']==67108864 and q['command'][0]==PY
    assert not (D/'families'/q['family_id']/q['case_id']/q['attempt_id']).exists()
    for p,h in q['input_sha256'].items():assert sha(p)==h,p
    unit=f'ds02-root279-native-scalar-recovery-v1-root-{num}'
    code='import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v10_git_bound import run_request;r=run_request('+repr(str(qp))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)'
    argv=['systemd-run','--user','--unit='+unit,'--working-directory='+str(LAB),'--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec='+str(q['max_wall_seconds']+60),'--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes','--property=MemoryAccounting=yes','--property=MemoryMax='+str(q['max_memory_bytes'])]
    argv+=['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    argv+=[PY,'-B','-I','-c',code];subprocess.run(argv,check=True)
    while True:
        u=state(unit)
        if u['SubState']!='running':break
        print(json.dumps({'event':'RUNNING_ACTUAL_NATIVE_SCALAR_PAIR','namespace':num,'family':q['family_id'],'cpu_seconds':int(u['CPUUsageNSec'])/1e9}),flush=True);time.sleep(30)
    assert u['MainPID']=='0'
    assert u['SubState']=='exited' and u['Result']=='success',u
    return unit

def verify(qp):
    common=S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    ctx={'__file__':str(common),'__name__':'root_actual_native_scalar_pair'}
    exec(common.read_text(),ctx);ctx.update(sha=sha,load=load)
    q,b,r,p=ctx['common'](qp)
    report=b/'observer/root279-native-scalar-recovery-result-v1.json';actual=load(report)
    assert actual['schema']=='ds02.stage2.f1-s2.root279-native-scalar-recovery-worker.v1'
    assert actual['status']=='COMPLETE_ROOT279_METADATA_RECOVERY_COMPACT_V3_SCALAR_V2_VERIFIER_NO_NATIVE_REREAD'
    for key in ['compact_result','compact_sealed_manifest','scalar_result','verification']:
        assert sha(actual[key]['path'])==actual[key]['sha256'],key
    assert actual['read_scope']['native_payload_reopened_by_recovery'] is False
    assert actual['read_scope']['native_paths_stat_or_hash_by_recovery'] is False
    assert actual['producer_scope']['selected_frame_count']==10
    scalar_manifest_ref=ref(b/'observer/recovery-scalar-manifest.json')
    for key,value in actual['recovery_lineage'].items():
        if isinstance(value,dict) and 'path' in value and 'sha256' in value:assert sha(value['path'])==value['sha256'],key
    independent=S/'checkpoints/ROOT362_ROOT279_NATIVE_SCALAR_INDEPENDENT_V1.json'
    verifier=S/'reference/stage2_f1_s2_root279_native_scalar_verify_v1.py'
    subprocess.run([PY,'-B',str(verifier),'--verify','--compact-manifest',actual['compact_sealed_manifest']['path'],'--scalar-manifest',scalar_manifest_ref['path'],'--scalar-output',actual['scalar_result']['path'],'--verification-output',str(independent)],cwd=LAB,check=True)
    v=load(independent);assert v['status']=='VERIFIED_ROOT279_NATIVE_SCALAR_COMPACT_CHAIN_METADATA_ONLY'
    p.update(status='VERIFIED_ACTUAL_ROOT279_METADATA_RECOVERY_COMPACT_SCALAR_CHAIN_NO_NATIVE_REREAD_NO_Q',report=str(report),report_sha256=sha(report),independent_verification=str(independent),independent_verification_sha256=sha(independent),actual_native_selected_read_after_reservation=False, producer_completed_under_root353_parent=True, native_payload_reopened_by_recovery=False,actual_selected_native_count=10,world_orientation='UNKNOWN',scientific_Q_credit=0,root_payload_content_read=False,source_request=ref(SOURCE))
    footer=(S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text().replace('1073741824',str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json','ROOT279_NATIVE_SCALAR_RECOVERY_ACTUAL_ROOT_VERIFICATION_362.json')
    ctx.update(q=q,b=b,r=r,p=p,qp=qp,num='362',name='root279-native-scalar-recovery-v1',subprocess=subprocess,importlib=importlib)
    exec(footer,ctx)
    assert state('ds02-root279-native-scalar-recovery-v1-root-362')['SubState']=='dead'
    proof=S/'checkpoints/ROOT279_NATIVE_SCALAR_RECOVERY_ACTUAL_ROOT_VERIFICATION_362.json'
    new(S/'checkpoints/ROOT362_ACTUAL_ROOT279_NATIVE_SCALAR_RECOVERY_HANDOFF_V1.json',{'schema':'ds02.stage2.root279-native-scalar-actual-handoff.v1','actual_proof':ref(proof),'actual_native_selected_count':10,'world_orientation':'UNKNOWN','scientific_Q_credit':0,'goal_complete':False,'goal_status':'ACTIVE_FULL_SEVEN_ITEMS'})
    return proof

if __name__=='__main__':
    with (D/'runtime/root-owned-root279-native-scalar-v1.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        qp=seal();launch(qp,362);verify(qp)
