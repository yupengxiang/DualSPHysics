"""Retry orphaned ROOT301 as ROOT327, then resume the frozen remaining queue."""
from pathlib import Path
import datetime
import fcntl
import importlib.util
import json
import os
import subprocess
import time

HERE=Path(__file__).resolve().parent
LAB=HERE.parents[4]
S=LAB/'campaigns/ds-data-02/stage2'
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def main():
    life=module(HERE/'continue_serial.py','root327_frozen_lifecycle')
    admission=module(S/'governance/root-owned-native-admission-v1/continue_after_serial_v1.py','root327_frozen_admission')
    registry=S/'requests/typed-lifecycle-evidence-registry-v4-after-root301-failed-001.json'
    plan=S/'checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT301_FAILED_V4.json'
    failure=S/'checkpoints/ROOT301_ORPHAN_FAILED_PARENT_RECONCILIATION_V1.json'
    f=life.load(failure);assert f['reservation_released'] and f['scientific_or_saved_mask_credit']==0
    previous=life.load(registry);failed=next(x for x in previous['producers'] if x['producer_id']=='ROOT301');assert failed['status']=='FAILED'
    source=S/'requests/typed-lifecycle-batch-v1-f5-root-forward-301-001.json'
    q=life.load(source);selected=set(q['physical_case_ids'])
    eligible={x['physical_case_id'] for x in life.load(plan)['case_records'] if x['status']=='FAILED_REQUIRES_NEW_ATTEMPT'}
    assert len(selected)==8 and selected==eligible and selected==set(failed['case_ids'])
    assert not any(p.get('status')=='RUNNING_NO_CREDIT' for p in previous['producers'])
    assert not life.load(D/'runtime/resource-ledger.json')['reservations']
    q.update(case_id='ROOT327_F5_TYPED_LIFECYCLE_ROOT301_OOMD_RECOVERY',attempt_id='root327-f5-lifecycle-new-attempt-after-root301-oomd-001',
             max_memory_bytes=8589934592,estimated_peak_memory_bytes=8589934592,estimated_peak_memory_mib=8192,
             root_failed_attempt_lineage=life.ref(failure),root_latest_actual_nonoverlap={'plan':life.ref(plan),'registry':life.ref(registry),
             'selected_count':8,'strict_selected_all_failed_requires_new_attempt':True,'actual_count':279,'source_only_request_does_not_grant_actual_credit':True},
             root_memory_recovery_reason='systemd-oomd at 4GiB; preserve scientific worker and chunk; one 8GiB parent with >200GiB host MemAvailable')
    code=HERE/'root_forward_metadata.py';context={'__file__':str(code),'__name__':'root327_orphan_forward'}
    exec(code.read_text(),context);context['sha']=life.sha
    extra=[Path(__file__),registry,plan,failure,S/'accounting/ROOT301_ORPHAN_SYSTEMD_FAILURE_EVIDENCE_V1.json',HERE/'verify_actual_lifecycle_v2.py',HERE/'resume_serial_v3.py']
    name='typed-lifecycle-batch-v1-f5-root-forward-327-001.json';context['write'](q,source,name,extra=extra)
    qp=S/'requests'/name;q=life.load(qp)
    ledger=life.load(D/'runtime/resource-ledger.json');assert not ledger['reservations']
    assert sum(c.get('cpu_core_seconds',0) for c in ledger['charges'])+q['max_wall_seconds']<ledger['limits']['cpu_core_seconds']
    assert datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=q['max_wall_seconds']+45)<datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert os.statvfs('/home/jade').f_bavail*os.statvfs('/home/jade').f_frsize-q['estimated_storage_bytes']>=ledger['limits']['home_min_free_bytes']
    mem={k:int(v.split()[0])*1024 for k,v in (x.split(':',1) for x in Path('/proc/meminfo').read_text().splitlines()) if v.split() and v.split()[0].isdigit()}
    assert mem['MemAvailable']>4*q['max_memory_bytes']
    for p,h in q['input_sha256'].items():assert life.sha(p)==h
    for row in q['deferred_input_records']:
        st=Path(row['path']).stat();assert st.st_size==row['bytes'] and len(row['sha256'])==64
    unit='ds02-typed-lifecycle-batch-v1-f5-root-327'
    code='import sys,os,json;sys.path.insert(0,'+repr(str(LAB/'scripts'))+');from ds_data02_runtime_v8 import run_request;r=run_request('+repr(str(qp))+',data_root='+repr(str(D))+',parent_pid=os.getppid());print(json.dumps(r));raise SystemExit(0 if r["status"]=="completed" else 1)'
    command=['systemd-run','--user','--unit='+unit,'--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec=3630','--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes','--property=MemoryAccounting=yes','--property=MemoryMax=8589934592']
    command+=['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    command+=[PYTHON,'-B','-I','-c',code];subprocess.run(command,check=True)
    previous['supersedes_registry']=life.ref(registry)
    previous['producers'].append({'producer_id':'ROOT327','kind':'typed_lifecycle_batch','status':'RUNNING_NO_CREDIT','case_ids':q['physical_case_ids'],'request':life.ref(qp),'manifest':q['manifest_contract'],'retry_of_failed_producer':'ROOT301'})
    pending=S/'requests/typed-lifecycle-evidence-registry-v4-root327-pending-001.json';life.new(pending,previous)
    pp=S/'checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT327_PENDING_V4.json';life.plan(pending,pp);life.checkpoint(327,pending,pp,qp,unit)
    while True:
        st=life.state(unit)
        if st['SubState']!='running':break
        print(json.dumps({'event':'RUNNING_ORPHAN_RECOVERY_PARENT','namespace':327,'CPU_core_seconds':int(st['CPUUsageNSec'])/1e9}),flush=True);time.sleep(30)
    assert st['SubState']=='exited' and st['MainPID']=='0' and st['Result']=='success',st
    subprocess.run([PYTHON,'-B',str(HERE/'verify_actual_lifecycle_v2.py'),'327','F5'],cwd=LAB,check=True)
    proof=S/'checkpoints/TYPED_LIFECYCLE_BATCH_F5_ACTUAL_ROOT_VERIFICATION_327.json';p=life.load(proof)
    assert p['parent_reservation_released'] and p['repeat_fee_idempotent'] and not p['failed_cases'] and len(p['case_verifications'])==8
    assert life.state(unit)['SubState']=='dead' and not life.load(D/'runtime/resource-ledger.json')['reservations']
    previous=life.load(pending);next(x for x in previous['producers'] if x['producer_id']=='ROOT327').update(status='COMPLETED',proof=life.ref(proof));previous['supersedes_registry']=life.ref(pending)
    reg=S/'requests/typed-lifecycle-evidence-registry-v4-after-root327-001.json';life.new(reg,previous)
    pp=S/'checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT327_V4.json';life.plan(reg,pp)
    assert life.load(pp)['coverage']['actual_saved_mask_cases']==287 and life.load(pp)['coverage']['failed_requires_new_attempt_cases']==0
    life.checkpoint(327,reg,pp,qp,unit,proof)
    cp=S/'checkpoints/ROOT327_LIFECYCLE_SERIAL_ACTUAL_FULL_GOAL_CONTINUATION_V1.json'
    subprocess.run([PYTHON,'-B',str(HERE/'resume_serial_v3.py'),'--checkpoint',str(cp),'--checkpoint-sha256',life.sha(cp)],cwd=LAB,check=True)


if __name__=='__main__':
    with (D/'runtime/root-owned-lifecycle-orphan301-recovery-v1.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('another ROOT301 recovery owns this queue')
        main()
