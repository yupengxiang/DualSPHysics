"""Close ROOT353 failed interface parent; bounded metadata only, no replay."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess

S=Path(__file__).resolve().parents[2]; LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
Q=S/'requests/root279-native-scalar-v2-v10-root-forward-353-001.json'
UNIT='ds02-root279-native-scalar-v2-root-353'

def small(p):
    p=Path(p)
    assert not p.is_symlink() and p.is_file() and p.stat().st_size<=10485760
    assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.pvtu','.jsonl'}
    a=p.stat();data=p.read_bytes();b=p.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns)
    return data,hashlib.sha256(data).hexdigest()

def load(p): return json.loads(small(p)[0])
def ref(p): return {'path':str(p),'sha256':small(p)[1]}
def new(p,v):
    if p.exists(): assert load(p)==v
    else:
        with p.open('x') as f: json.dump(v,f,indent=2,sort_keys=True);f.write('\n')

def main():
    q=load(Q); identity={k:q[k] for k in ('family_id','case_id','attempt_id')}
    parent='/'.join(identity.values());base=D/'families'/q['family_id']/q['case_id']/q['attempt_id']
    rp=base/'execution-receipt.json';r=load(rp)
    assert r['status']=='failed' and r['request_sha256']==small(Q)[1]
    raw=subprocess.check_output(['systemctl','--user','show',UNIT,'-p','Id','-p','SubState','-p','Result','-p','ExecMainStatus','-p','CPUUsageNSec','-p','InvocationID','-p','ExecStart','-p','MainPID','-p','MemoryMax','-p','ControlGroup'],text=True)
    u=dict(line.split('=',1) for line in raw.splitlines())
    assert u['SubState']=='failed' and u['MainPID']=='0' and u['Result']=='exit-code' and not u['ControlGroup']
    assert str(Q) in u['ExecStart'] and int(u['MemoryMax'])==q['max_memory_bytes']
    ns=int(u['CPUUsageNSec'])
    ep=S/'accounting/terminal-cpu-evidence-root-353-failed-v1.json'
    new(ep,dict(schema='ds02.stage2.systemd-cpu-evidence.v1',unit=u['Id'],request=str(Q),request_sha256=small(Q)[1],receipt=str(rp),receipt_sha256=small(rp)[1],identity=identity,charge_id=parent,CPUUsageNSec=ns,cpu_usage_nsec=ns,systemd_properties=u,raw_systemctl_show=raw,terminal=True))
    source=LAB/'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py'
    small(source)
    spec=importlib.util.spec_from_file_location('root353_failed_cpu',source)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    op=S/'accounting/terminal-cpu-delta-v6-root-353-failed.json'
    kw=dict(request_path=Q,receipt_path=rp,evidence_path=ep,ledger_path=D/'runtime/resource-ledger.json',output=op)
    fee=m.reconcile(**kw)
    assert m.reconcile(**kw)['status']=='ALREADY_APPLIED_SAME_PARENT_CPU_DELTA'
    ledger=load(D/'runtime/resource-ledger.json')
    assert not any(x['id']==parent for x in ledger['reservations'])
    gp=base/'observer/root279-guard-result.json';g=load(gp)
    assert g['status']=='PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES'
    cp=base/'observer/.v1-result.json';c=load(cp)
    assert c['status']=='PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES'
    log=base/'stdout.log';logtext=small(log)[0].decode()
    assert 'ROOT279 guarded producer did not return exact PASS' in logtext
    proof=dict(schema='ds02.stage2.root353-failed-native-scalar-metadata-closure.v1',status='VERIFIED_FAILED_PARENT_FULL_CPU_NATIVE_PRODUCER_PRESERVED_NO_CHAIN_CREDIT',request=ref(Q),receipt=ref(rp),guard_result=ref(gp),child_report=ref(cp),stdout=ref(log),systemd_evidence=ref(ep),terminal_cpu_reconciliation=ref(op),full_systemd_cpu_seconds=ns/1e9,delta_cpu_seconds=fee['delta_cpu_core_seconds'],repeat_cpu_fee_idempotent=True,reservation_released=True,unit_cgroup_empty=True,failure='PARENT_V2_REJECTED_ACTUAL_GUARDED_V1_SUCCESS_STATUS',preserved_successful_producer_scope='selected native diagnostic observables only; full compact/scalar chain not completed',chain_credit=0,scientific_Q_credit=0,root_payload_content_read=False,full_goal_complete=False)
    out=S/'checkpoints/ROOT353_FAILED_NATIVE_SCALAR_ACTUAL_METADATA_CLOSURE_V1.json';new(out,proof)
    print(json.dumps({'status':proof['status'],'full_cpu_seconds':ns/1e9,'delta_cpu_seconds':fee['delta_cpu_core_seconds'],'proof':str(out)}))

if __name__=='__main__':main()
