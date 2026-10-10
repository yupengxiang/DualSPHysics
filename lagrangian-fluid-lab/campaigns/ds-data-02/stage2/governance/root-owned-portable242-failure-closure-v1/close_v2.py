"""Close actual failed portable parent using bounded metadata and stat only."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import sys

S = Path(__file__).resolve().parents[2]
LAB = S.parents[2]
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
UNIT = 'ds02-portable-typed-v13-root-242'
Q = S / 'requests/portable-typed-root242-v13-root-forward-242-004.json'

def small(p):
    p = Path(p)
    assert not p.is_symlink() and p.is_file() and p.stat().st_size <= 10485760
    assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.pvtu','.jsonl'}
    a = p.stat()
    data = p.read_bytes()
    b = p.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns) == (b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns)
    return json.loads(data), hashlib.sha256(data).hexdigest()

def write_new(p, v):
    with p.open('x') as f:
        json.dump(v,f,indent=2,sort_keys=True); f.write('\n')

def main():
    q, qsha = small(Q)
    identity = {k:q[k] for k in ('family_id','case_id','attempt_id')}
    parent = '/'.join(identity.values())
    receipt = D/'families'/q['family_id']/q['case_id']/q['attempt_id']/'execution-receipt.json'
    r, rsha = small(receipt)
    assert r['status'] == 'failed' and r['request_sha256'] == qsha
    raw = subprocess.check_output(['systemctl','--user','show',UNIT,'-p','Id','-p','SubState','-p','Result','-p','ExecMainStatus','-p','CPUUsageNSec','-p','InvocationID','-p','ExecStart','-p','MainPID','-p','MemoryMax','-p','ControlGroup'],text=True)
    u = dict(line.split('=',1) for line in raw.splitlines())
    assert u['SubState']=='failed' and u['MainPID']=='0' and u['Result']=='exit-code'
    assert str(Q) in u['ExecStart'] and u['ControlGroup']==''
    ns = int(u['CPUUsageNSec'])
    ep = S/'accounting/terminal-cpu-evidence-root-242-v13-failed-v1.json'
    e = dict(schema='ds02.stage2.systemd-cpu-evidence.v1',unit=u['Id'],request=str(Q),request_sha256=qsha,receipt=str(receipt),receipt_sha256=rsha,identity=identity,charge_id=parent,CPUUsageNSec=ns,cpu_usage_nsec=ns,systemd_properties=u,raw_systemctl_show=raw,terminal=True)
    if ep.exists(): assert small(ep)[0] == e
    else: write_new(ep,e)
    source = LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py'
    assert source.stat().st_size < 10485760
    spec = importlib.util.spec_from_file_location('portable242_failed_cpu',source)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    op = S/'accounting/terminal-cpu-delta-v6-root-242-v13-failed.json'
    kw = dict(request_path=Q,receipt_path=receipt,evidence_path=ep,ledger_path=D/'runtime/resource-ledger.json',output=op)
    fee=m.reconcile(**kw)
    assert m.reconcile(**kw)['status']=='ALREADY_APPLIED_SAME_PARENT_CPU_DELTA'
    sys.path.insert(0,str(S/'governance/root-owned-portable-admission-v1'))
    from external_storage_v1 import snapshot
    extpath=S/'accounting/root242-v13-output-slot-external-storage-evidence-v1.json'
    ext,extsha=small(extpath)
    assert ext['request_sha256']==qsha and ext['receipt_sha256']==rsha and ext['terminal_status']=='failed'
    assert snapshot(Path(q['storage_scope']['external_filesystem']))==ext['external_stat_snapshot']
    ledger,_=small(D/'runtime/resource-ledger.json')
    assert not any(x['id']==parent for x in ledger['reservations'])
    fees=[x for x in ledger['charges'] if x['id']==parent+'/same-parent-external-storage-v1']
    assert len(fees)==1 and fees[0]['evidence_sha256']==extsha and fees[0]['new_storage_bytes']==ext['external_stat_snapshot']['bytes']
    log=receipt.parent/'stdout.log'; logdata,logsha = None,None
    assert log.stat().st_size<10485760
    logtext=log.read_text(); logsha=hashlib.sha256(logtext.encode()).hexdigest()
    assert 'unbound actionable request path at /v66_parent_binding/terminal_delta/path' in logtext
    proof=dict(schema='ds02.stage2.root242-failed-portable-metadata-closure.v1',status='VERIFIED_FAILED_PARENT_FULL_CPU_EXTERNAL_STORAGE_NO_PORTABLE_CREDIT',request=str(Q),request_sha256=qsha,receipt=str(receipt),receipt_sha256=rsha,systemd_evidence=str(ep),systemd_evidence_sha256=small(ep)[1],full_systemd_cpu_seconds=ns/1e9,terminal_cpu_reconciliation=str(op),terminal_cpu_reconciliation_sha256=small(op)[1],delta_cpu_seconds=fee['delta_cpu_core_seconds'],repeat_cpu_fee_idempotent=True,external_storage_evidence=str(extpath),external_storage_evidence_sha256=extsha,external_storage_bytes=ext['external_stat_snapshot']['bytes'],reservation_released=True,unit_cgroup_empty=True,stdout_log=str(log),stdout_sha256=logsha,failure='UNBOUND_OLD_ACTIONABLE_TERMINAL_CPU_EVIDENCE',partial_copies_preserved=True,root_payload_content_read=False,portable_credit='NOT_CLAIMED',qualification={'QI':'UNKNOWN','QN':'UNKNOWN','QE':'UNKNOWN'},full_goal_complete=False)
    out=S/'checkpoints/ROOT242_V13_FAILED_PORTABLE_ACTUAL_METADATA_CLOSURE_V1.json'
    if out.exists(): assert small(out)[0]==proof
    else: write_new(out,proof)
    print(json.dumps({'status':proof['status'],'full_cpu_seconds':ns/1e9,'delta_seconds':fee['delta_cpu_core_seconds'],'external_bytes':proof['external_storage_bytes'],'proof':str(out)}))

if __name__=='__main__': main()
