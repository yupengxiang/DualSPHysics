"""Bind nine actual GenCase BI4 headers to one managed, bounded V10 parent.

Native content is read only by the scientific child after reservation. ROOT
closes small reports/receipts/fees and preserves unexposed header fields as
UNKNOWN; this does not qualify continuous owner geometry or physical tasks.
"""
from pathlib import Path
import argparse
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
PACK=S/'requests/three-sentinel-native-header-primary-prepared-709-002'
SOURCE=PACK/'native-header-probe-request-v2.json';MANIFEST=PACK/'native-header-probe-manifest-v2.json'
PILOT=S/'requests/scientific-field-h5-v3-v10-actual-pilot-root-346-001.json'
QP=S/'requests/three-sentinel-native-header-v3-v10-root-forward-709-001.json'
UNIT='ds02-three-sentinel-native-header-v3-root-709'
spec=importlib.util.spec_from_file_location('nine_header_bounded_helpers',S/'governance/root-owned-scientific-field-pilot-admission-v1/serial_v4.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
sha=helper.sha;load=helper.load;ref=helper.ref;new=helper.new;state=helper.state

def seal():
    q=load(SOURCE);pilot=load(PILOT);m=load(MANIFEST)
    assert not q['source_closure_missing'] and len(m['cases'])==9
    assert m['status']=='READY_FOR_PARENT_GUARDED_NATIVE_HEADER_PROBE'
    old=dict(q['input_sha256'])
    for p,h in old.items():assert sha(p)==h,p
    q.update(kind='cpu',cpu_task_kind='audit',attempt_id='root709-three-sentinel-native-header-v3-actual-001',
        cwd=str(LAB),worktree_root=str(LAB.parent),cpu_threads=1,omp_threads=1,
        max_wall_seconds=3600,max_memory_bytes=4294967296,estimated_peak_memory_bytes=4294967296,
        estimated_storage_bytes=3221225472,runtime_binding=pilot['runtime_binding'],
        interpreter_binding=pilot['interpreter_binding'],source_only=False,execution_allowed=True,launch_disabled=False)
    i=q['command'].index('--manifest');assert q['command'][i+1]=='{attempt_root}/native-header-probe-manifest-v2.json'
    q['command'][i+1]=str(MANIFEST);q['command'].insert(1,'-B')
    q['manifest_contract']=ref(MANIFEST)
    q['storage_scope']={'schema':'ds02.storage-scope.v2','estimated_storage_bytes':3221225472,
        'home_storage_bytes':3221225472,'external_storage_bytes':0,'external_headroom_bytes':0,
        'home_headroom_bytes':805306368,'worker_scratch_bytes':2415919104,'source_copy_bytes':0,
        'read_io_excluded_from_storage':True}
    decoder=Path(m['cases'][0]['decoder']['path'])
    extras=[Path(__file__),SOURCE,MANIFEST,PILOT,decoder,
        S/'governance/root-owned-scientific-field-pilot-admission-v1/serial_v4.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
        S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
        LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py',LAB/'scripts/ds_data02_batch_runner.py',
        Path(pilot['interpreter_binding']['resolved_path']),
        S/'checkpoints/ROOT708_NINE_ACTUAL_GENCASE_COST_SCOPE_V1.json',
        S/'checkpoints/F1_S2_INTEGRAL_OUTPUT_ACTUAL_ROOT_VERIFICATION_371.json']
    extras += [Path(v['path']) for v in q['runtime_binding'].values()]
    q['input_files']=list(dict.fromkeys(q['input_files']+list(map(str,extras))))
    q['input_sha256']=q['input_hashes']={p:sha(p) for p in q['input_files']}
    native=[r for r in q['deferred_input_records'] if r.get('role')=='native_bi4']
    assert len(native)==9 and len({r['path'] for r in native})==9
    for r in native:
        p=Path(r['path']);v=p.stat();expected=r['stat']
        assert not p.is_symlink() and p.is_file()
        assert {'bytes':v.st_size,'ctime_ns':v.st_ctime_ns,'mtime_ns':v.st_mtime_ns,
            'st_dev':v.st_dev,'st_ino':v.st_ino}==expected
        assert r['path'] not in q['input_files']
    q['root_nine_header_admission']={'source_request':ref(SOURCE),'static_manifest':ref(MANIFEST),
        'native_payload_content_read_by_root':False,'native_source_bytes':sum(r['stat']['bytes'] for r in native),
        'native_parent_full_prepost_hash_required':True,'decoder_binding':ref(decoder),
        'initial_position_id_finite_audit_performed':False,'scientific_Q_credit':0}
    sys.path.insert(0,str(LAB/'scripts'));from ds_data02_runtime_v8 import _light_validate
    _light_validate(q,data_root=D);new(QP,q)
    print(json.dumps({'event':'SEALED_NINE_ACTUAL_NATIVE_HEADER_PARENT','request':str(QP),'sha256':sha(QP),
        'native_source_bytes':q['root_nine_header_admission']['native_source_bytes'],'root_native_read':False}),flush=True)

def launch():
    q=load(QP);ledger=load(D/'runtime/resource-ledger.json');assert not ledger['reservations']
    assert datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=3690)<datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert sum(r.get('cpu_core_seconds',0) for r in ledger['charges'])+3600<ledger['limits']['cpu_core_seconds']
    disk=os.statvfs(ledger['limits']['home_path'])
    assert disk.f_bavail*disk.f_frsize-q['estimated_storage_bytes']>=ledger['limits']['home_min_free_bytes']
    for p,h in q['input_sha256'].items():assert sha(p)==h,p
    code='import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v10_git_bound import run_request;r=run_request('+repr(str(QP))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)'
    argv=['systemd-run','--user','--unit='+UNIT,'--working-directory='+str(LAB),
        '--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec=3660',
        '--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes',
        '--property=MemoryAccounting=yes','--property=MemoryMax=4294967296']
    argv+=['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    subprocess.run(argv+[PY,'-B','-I','-c',code],check=True)
    while True:
        u=state(UNIT)
        if u['SubState']!='running':break
        print(json.dumps({'event':'RUNNING_NINE_ACTUAL_NATIVE_HEADER_PARENT','cpu_seconds':int(u['CPUUsageNSec'])/1e9}),flush=True);time.sleep(10)
    assert u['SubState']=='exited' and u['MainPID']=='0' and u['Result']=='success',u

def verify():
    common=S/'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py'
    ctx={'__file__':str(common),'__name__':'root_actual_nine_header_scope'}
    exec(common.read_text(),ctx);ctx.update(sha=sha,load=load)
    q,b,r,p=ctx['common'](QP)
    report=b/'report/native-header-probe-v3.json';actual=load(report);manifest=load(MANIFEST)
    assert actual['schema']=='ds02.stage2.native-header-probe.v3' and actual['status']=='COMPLETE_NATIVE_HEADER_PROBE_DIAGNOSTIC'
    assert actual['manifest']==str(MANIFEST) and len(actual['cases'])==9
    assert actual['scientific_qualification']=={'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN','credit':0}
    by_key={v['row_key']:v for v in actual['cases']};assert len(by_key)==9
    for source in manifest['cases']:
        v=by_key[source['row_key']]
        assert v['source_path']==source['native_bi4']['path']
        assert len(v['source_sha256'])==64 and v['source_guard']['full_source_passes']==2
        assert v['source_guard']['pre']['sha256_pre']==v['source_guard']['post']['sha256_post']==v['source_sha256']
        assert v['source_guard']['pre']['stat_pre']==v['source_guard']['post']['stat_post']
        assert v['status'] in {'PASS_NATIVE_HEADER_FIELDS','UNKNOWN_NATIVE_HEADER_FIELDS_NOT_EXPOSED_BY_DECODER'}
    p.update(status='VERIFIED_ACTUAL_NINE_GENCASE_NATIVE_HEADER_DIAGNOSTIC_NO_SCIENTIFIC_Q',
        report=str(report),report_sha256=sha(report),source_request=ref(SOURCE),static_manifest=ref(MANIFEST),
        actual_native_header_count=9,root_native_payload_content_read=False,
        initial_position_id_finite_audit_performed=False,continuous_owner_equivalence='UNKNOWN',scientific_Q_credit=0)
    footer=(S/'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text().replace(
        '1073741824',str(q['max_memory_bytes'])).replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json',
        'NINE_GENCASE_NATIVE_HEADER_ACTUAL_ROOT_VERIFICATION_709.json')
    ctx.update(q=q,b=b,r=r,p=p,qp=QP,num='709',name='three-sentinel-native-header-v3',subprocess=subprocess,importlib=importlib)
    exec(footer,ctx);assert state(UNIT)['SubState']=='dead'
    proof=S/'checkpoints/NINE_GENCASE_NATIVE_HEADER_ACTUAL_ROOT_VERIFICATION_709.json'
    new(S/'checkpoints/ROOT709_ACTUAL_NINE_NATIVE_HEADER_HANDOFF_V1.json',{
        'schema':'ds02.stage2.root-nine-native-header-actual-handoff.v1','actual_proof':ref(proof),
        'initial_support_audited':False,'scientific_Q_credit':0,'goal_complete':False,'goal_status':'ACTIVE_FULL_SEVEN_ITEMS'})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run'])
    args=parser.parse_args()
    if args.action=='prepare':seal()
    else:
        with (D/'runtime/root-owned-nine-native-header-v1.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);launch();verify()
