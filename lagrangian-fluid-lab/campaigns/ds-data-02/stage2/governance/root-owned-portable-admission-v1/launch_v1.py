"""Root admission for the sealed portable parent; never hash deferred inputs here."""
from pathlib import Path
import datetime
import importlib.util
import json
import os
import subprocess
import time

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
PYTHON = '/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python'
from external_storage_v1 import small


def launch(request):
    q, _ = small(request)
    ledger, _ = small(D / 'runtime/resource-ledger.json')
    assert not ledger['reservations']
    now = datetime.datetime.now(datetime.timezone.utc)
    assert now + datetime.timedelta(seconds=q['max_wall_seconds'] + 90) < datetime.datetime.fromisoformat(ledger['deadline_utc'])
    assert sum(x.get('cpu_core_seconds', 0) for x in ledger['charges']) + q['cpu_threads'] * q['max_wall_seconds'] < ledger['limits']['cpu_core_seconds']
    home = os.statvfs(ledger['limits']['home_path'])
    assert home.f_bavail * home.f_frsize - q['estimated_storage_bytes'] >= ledger['limits']['home_min_free_bytes']
    external = os.statvfs('/var/tmp')
    a = q['root_external_storage_accounting']
    assert external.f_bavail * external.f_frsize - a['external_reserved_bytes'] >= a['external_free_floor_bytes']
    contract, _ = small(q['root213_metadata_contract']['path'])
    deferred = {r['source_path_provenance'] for r in contract['root242_source_binding']['roles'] if r['deferred_content']}
    for path, digest in q['input_sha256'].items():
        if path in deferred:
            Path(path).stat()
        else:
            p = Path(path)
            assert p.suffix.lower() not in {'.h5','.hdf5','.bi4','.obi4','.ibi4','.vtk','.jsonl'} and p.stat().st_size <= 10485760
            import hashlib
            assert hashlib.sha256(p.read_bytes()).hexdigest() == digest, path
    assert not Path(q['storage_scope']['external_filesystem']).exists()
    assert not (D / 'families' / q['family_id'] / q['case_id'] / q['attempt_id']).exists()
    unit = 'ds02-portable-typed-v11-root-242'
    argv = ['systemd-run', '--user', '--unit=' + unit, '--property=Type=exec',
            '--property=RemainAfterExit=yes', '--property=RuntimeMaxSec=990', '--property=TimeoutStopSec=45',
            '--property=KillMode=mixed', '--property=CPUAccounting=yes', '--property=MemoryAccounting=yes',
            '--property=MemoryMax=' + str(q['max_memory_bytes'])]
    argv += ['--setenv=' + k + '=1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']]
    code = 'import sys;sys.path.insert(0,' + repr(str(HERE)) + ');from parent_entry_v1 import main;raise SystemExit(main())'
    argv += [PYTHON, '-B', '-I', '-c', code, '--request', str(request)]
    subprocess.run(argv, check=True)
    while True:
        raw = subprocess.check_output(['systemctl','--user','show',unit,'-p','SubState','-p','MainPID','-p','Result','-p','CPUUsageNSec'], text=True)
        state = dict(line.split('=', 1) for line in raw.splitlines())
        if state['SubState'] != 'running':
            break
        print(json.dumps({'event': 'RUNNING_PORTABLE_PARENT', 'namespace': 242, 'CPU_core_seconds': int(state['CPUUsageNSec']) / 1e9}), flush=True)
        time.sleep(30)
    assert state['MainPID'] == '0', state
    receipt = D / 'families' / q['family_id'] / q['case_id'] / q['attempt_id'] / 'execution-receipt.json'
    if receipt.exists():
        # Close partial external copies even if systemd killed the entry
        # after its runtime receipt was finalized.
        import sys
        sys.path.insert(0, str(LAB / 'scripts'))
        from ds_data02_runtime_v8 import ledger_locked
        from external_storage_v1 import reconcile
        evidence = S / 'accounting/root242-external-storage-evidence-v1.json'
        reconcile(request, D, ledger_locked, evidence)
        assert reconcile(request, D, ledger_locked, evidence)['status'] == 'ALREADY_APPLIED_SAME_PARENT_EXTERNAL_STORAGE'
    # A failed partial copy must already be charged by parent_entry. Root
    # must inspect it rather than granting portable evidence or relaunching.
    assert state['SubState'] == 'exited' and state['Result'] == 'success', state
    return unit


if __name__ == '__main__':
    import sys
    launch(Path(sys.argv[1]))
