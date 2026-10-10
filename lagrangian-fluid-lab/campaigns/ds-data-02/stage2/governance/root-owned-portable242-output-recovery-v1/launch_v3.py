"""Fresh scoped portable admission; preserve the failed V11 attempt and unit."""
from pathlib import Path
import datetime
import hashlib
import os
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
S=HERE.parents[1]
LAB=S.parents[2]
D=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON='/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
UNIT='ds02-portable-typed-v13-root-242'
sys.path.insert(0,str(S/'governance/root-owned-portable-admission-v1'))
from external_storage_v1 import small,reconcile

def launch(request):
    request=Path(request).absolute();q,_=small(request);ledger,_=small(D/'runtime/resource-ledger.json')
    assert not ledger['reservations']
    now=datetime.datetime.now(datetime.timezone.utc)
    assert now+datetime.timedelta(seconds=q['max_wall_seconds']+90)<datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert sum(x.get('cpu_core_seconds',0) for x in ledger['charges'])+q['cpu_threads']*q['max_wall_seconds']<ledger['limits']['cpu_core_seconds']
    h=os.statvfs(ledger['limits']['home_path'])
    assert h.f_bavail*h.f_frsize-q['estimated_storage_bytes']>=ledger['limits']['home_min_free_bytes']
    e=os.statvfs('/var/tmp');a=q['root_external_storage_accounting']
    assert e.f_bavail*e.f_frsize-a['external_reserved_bytes']>=a['external_free_floor_bytes']
    contract,_=small(q['root213_metadata_contract']['path'])
    deferred={r['source_path_provenance']:r for r in contract['root242_source_binding']['roles'] if r['deferred_content']}
    for raw,digest in q['input_sha256'].items():
        p=Path(raw)
        if raw in deferred:
            z=p.stat();assert z.st_size==deferred[raw]['source_stat_provenance']['bytes']
            assert digest==deferred[raw]['source_sha256']
        else:
            assert (not p.is_symlink() or (str(p)==PYTHON and str(p.resolve())=='/usr/bin/python3.10')) and p.stat().st_size<=10485760 and p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.vtu','.pvtu','.jsonl'}
            assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,raw
    assert not Path(q['storage_scope']['external_filesystem']).exists()
    assert not (D/'families'/q['family_id']/q['case_id']/q['attempt_id']).exists()
    code='import sys;sys.path.insert(0,'+repr(str(HERE))+');from parent_entry_v2 import main;raise SystemExit(main())'
    argv=['systemd-run','--user','--unit='+UNIT,'--working-directory='+str(LAB),'--property=Type=exec','--property=RemainAfterExit=yes','--property=RuntimeMaxSec=990','--property=TimeoutStopSec=45','--property=KillMode=mixed','--property=CPUAccounting=yes','--property=MemoryAccounting=yes','--property=MemoryMax='+str(q['max_memory_bytes'])]
    argv+=['--setenv='+k+'=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    argv+=[PYTHON,'-B','-I','-c',code,'--request',str(request)]
    subprocess.run(argv,check=True)
    while True:
        raw=subprocess.check_output(['systemctl','--user','show',UNIT,'-p','SubState','-p','MainPID','-p','Result','-p','CPUUsageNSec'],text=True)
        u=dict(line.split('=',1) for line in raw.splitlines())
        if u['SubState']!='running':break
        print({'event':'RUNNING_FRESH_PORTABLE_V13','cpu_seconds':int(u['CPUUsageNSec'])/1e9},flush=True);time.sleep(30)
    assert u['MainPID']=='0'
    receipt=D/'families'/q['family_id']/q['case_id']/q['attempt_id']/'execution-receipt.json'
    if receipt.exists():
        sys.path.insert(0,str(LAB/'scripts'));from ds_data02_runtime_v8 import ledger_locked
        ep=Path(q['root_external_storage_evidence']['path'])
        reconcile(request,D,ledger_locked,ep)
        assert reconcile(request,D,ledger_locked,ep)['status']=='ALREADY_APPLIED_SAME_PARENT_EXTERNAL_STORAGE'
    assert u['SubState']=='exited' and u['Result']=='success',u
    return UNIT

if __name__=='__main__': launch(Path(sys.argv[1]))
